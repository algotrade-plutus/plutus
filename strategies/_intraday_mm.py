"""A reusable intraday market-maker and its driver, for S8 and S9.

The S1–S7 harness is *daily*: it advances two marks a day and reads daily closes.
A market-maker lives on a finer clock — it posts a two-sided quote, waits, sees
what the tape lifted, re-quotes. So this module drives the session **intraday**,
tick-resolution, exactly the way the Jx book-walk scenarios do (``advance_to`` an
instant, ``submit``/``cancel`` orders), with a strategy loop on top.

The strategy is a genuine, if small, **inventory** market-maker. On HSX there is
no shorting, so it does not quote a symmetric book out of thin air; it starts
with inventory and works it: it quotes both sides at the touch, and skews —
posting only the ask when it is too long, only the bid when it is too short — to
pull its position back toward a target. Two Vietnamese facts shape it and are
left to *emerge* rather than be asserted into being:

* **T+2.** Shares bought today are unsettled and cannot be re-sold today
  (:meth:`ExchangeSession` enforces it), so the ask can only ever sell down the
  *settled* inventory the day began with. A maker here cannot round-trip intraday
  the way a futures maker can; it sells inventory and buys replacements that
  arrive T+2. The driver simply does not post an ask it cannot cover, and the
  unsettled pile that builds up is that constraint made visible.
* **The queue.** Every fill is a *maker* fill off the tape, so it depends on the
  declared queue position — which is the whole point of S9, which reruns this
  under optimistic / conservative / probabilistic and reads the spread.

Nothing here is privileged: it submits and cancels ordinary orders and reads
``holdings``/``cash`` back through the public surface.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from plutus.market.session import ExchangeSession, Accepted, parse_config
from plutus.market.adapters.book_session import BookSessionSource
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

PRICE_SCALE = Decimal(1000)          # corpus prices are thousands of đồng

#: The shipped in-repo fixtures (Workstream W7): the minimal intraday book/tape
#: slice S8/S9 read (FPT 2022-11-09 + the VN30F2504 variant), plus the daily
#: price/band slice, so a bare clone runs with no external extract mounted. The
#: env vars override each to the full corpus. See ``strategies/fixtures/``.
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _extract() -> Path:
    return Path(os.environ.get("PLUTUS_DEPTH_ROOT", str(_FIXTURES / "extract")))


def _prices() -> str:
    return os.environ.get("PLUTUS_DATA_ROOT", str(_FIXTURES / "parquet"))


def tape_available() -> bool:
    return (_extract() / "local_quote_total.parquet").exists()


def _kind(e):
    return getattr(e.kind, "value", e.kind)


# --------------------------------------------------------------------------
# The strategy: an inventory market-maker
# --------------------------------------------------------------------------

@dataclass
class InventoryMarketMaker:
    """Quote both sides at the touch, skewing to pull inventory to target.

    ``skew`` is the inventory-management logic and is on by default (S8). S9
    turns it **off**: to measure what the *queue assumption alone* is worth, the
    strategy's decisions must not themselves depend on the queue-dependent fills
    — an off-skew maker quotes a pure function of the market, so the only thing
    that differs across the three runs is the queue. That is a deliberate
    experimental control, not a different strategy.
    """

    ticker: str
    target: int                      # the inventory it wants to hold
    band: int                        # how far it lets inventory drift first
    size: int                        # shares per quote
    skew: bool = True                # manage inventory (S8); off isolates queue (S9)

    def quotes(self, best_bid: Optional[Decimal], best_ask: Optional[Decimal],
               position: int) -> Tuple[Optional[Decimal], Optional[Decimal]]:
        """(bid_price, ask_price) to post this interval, either may be ``None``.

        With ``skew``: too long -> ask only (sell down); too short -> bid only
        (buy up); otherwise both. Without it, always both. Prices are the current
        touch, so the quotes rest and fill only as the tape trades through them.
        """
        bid = best_bid
        ask = best_ask
        if self.skew and position >= self.target + self.band:   # too long
            bid = None
        elif self.skew and position <= self.target - self.band:  # too short
            ask = None
        return bid, ask


# --------------------------------------------------------------------------
# The intraday driver
# --------------------------------------------------------------------------

@dataclass
class MMLedger:
    """What one market-making run produced, read back through the public API."""

    ticker: str
    initial_cash: Decimal
    initial_settled: int
    fills: List[dict] = field(default_factory=list)          # side/qty/price/mark
    inventory: List[dict] = field(default_factory=list)      # mark/settled/unsettled
    provenance: str = ""

    def buys(self) -> List[dict]:
        return [f for f in self.fills if f["side"] is Side.BUY]

    def sells(self) -> List[dict]:
        return [f for f in self.fills if f["side"] is Side.SELL]

    def _value(self, fills) -> Decimal:
        return sum((Decimal(f["quantity"]) * f["price"] * PRICE_SCALE
                    for f in fills), Decimal(0))

    def buy_value(self) -> Decimal:
        return self._value(self.buys())

    def sell_value(self) -> Decimal:
        return self._value(self.sells())

    def position_curve(self) -> List[int]:
        return [row["position"] for row in self.inventory]

    # -- maker vs taker (a fill at its own posted price is a maker) ---------

    def maker_fills(self) -> List[dict]:
        return [f for f in self.fills if f.get("maker")]

    def taker_fills(self) -> List[dict]:
        return [f for f in self.fills if not f.get("maker")]

    def maker_shares(self) -> int:
        return sum(f["quantity"] for f in self.maker_fills())

    def taker_shares(self) -> int:
        return sum(f["quantity"] for f in self.taker_fills())

    def conservation(self) -> Tuple[Decimal, Decimal, Decimal]:
        """``(cash_change, sells - buys - charges, charges)`` -- the two must
        be equal: every đồng that moved is a fill or a charge, nothing else.

        A sale settles T+2, so its proceeds are *pending* not *settled* on the
        day; the check reads ``settled + pending`` so an intraday sell is not
        mistaken for money that vanished.
        """
        session = self._session
        cash = session.cash()
        charged = sum((c.total for c in session.charges()), Decimal(0))
        change = (cash.settled_balance + cash.pending_total) - self.initial_cash
        return change, self.sell_value() - self.buy_value() - charged, charged


#: The intraday marks: a quote is posted at each, and lifted (or not) by the
#: tape before the next. Spread across the continuous session, avoiding the
#: opening/closing auctions where a sweep/maker is not modelled.
MARKS = [time(9, 30), time(10, 15), time(11, 0), time(13, 15), time(14, 0),
         time(14, 30)]

#: A finer cadence. It matters for the queue: over a short interval the volume
#: that prints through a quote is comparable to the depth queued ahead of it, so
#: **where** the order sits in that queue changes how much fills. Over a long
#: interval the prints swamp the queue and every position fills the same — which
#: is why the coarse ``MARKS`` above make the maker fill queue-*insensitive* and
#: S9 uses this schedule to let the queue assumption actually bite.
FINE_MARKS = [time(9, 30), time(9, 45), time(10, 0), time(10, 15),
              time(10, 30), time(10, 45), time(11, 0), time(11, 15),
              time(13, 15), time(13, 30), time(13, 45), time(14, 0)]


def _session(queue: str, seed: Optional[int], *, ticker: str, venue: str,
             table_prefix: str, initial_cash: int, initial_holdings: dict,
             day: str) -> Tuple[ExchangeSession, BookSessionSource]:
    fill_policy = {"kind": "book_walk", "queue": queue,
                   "max_participation": None, "max_staleness": None}
    if seed is not None:
        fill_policy["seed"] = seed
    end = (datetime.fromisoformat(day).date().toordinal() + 1)
    from datetime import date as _date
    config = parse_config({
        "period": {"start": day, "end": _date.fromordinal(end).isoformat()},
        "resolution": "tick",
        "exchange_rules": {"venues": [venue]},
        "accounts": {"securities": {"initial_cash": initial_cash,
                                    "account_no": "SEC-MM"}},
        "fill_policy": fill_policy,
    })
    # For VN30F the band lives in the extract's quote_* tables, not the daily
    # price root, so the price source reads the extract there too.
    price_root = str(_extract()) if table_prefix == "quote" else _prices()
    source = BookSessionSource.for_roots(price_root, str(_extract()),
                                         table_prefix=table_prefix)
    session = ExchangeSession.build(config, source=source,
                                    initial_holdings=initial_holdings)
    return session, source


def run_market_maker(mm: InventoryMarketMaker, *, queue: str = "optimistic",
                     seed: Optional[int] = None, day: str = "2022-11-09",
                     venue: str = "HSX", table_prefix: str = "local_quote",
                     initial_cash: int = 1_000_000_000,
                     marks: Optional[List[time]] = None) -> MMLedger:
    """Drive ``mm`` through one intraday session under one queue assumption."""
    schedule = marks or MARKS
    session, source = _session(
        queue, seed, ticker=mm.ticker, venue=venue, table_prefix=table_prefix,
        initial_cash=initial_cash, initial_holdings={mm.ticker: mm.target},
        day=day)
    ledger = MMLedger(ticker=mm.ticker, initial_cash=Decimal(initial_cash),
                      initial_settled=mm.target)
    orders: Dict[str, Tuple[Side, Decimal]] = {}   # order_id -> (side, limit)

    def _touch(now: datetime):
        try:
            book = source.book_at(mm.ticker, now)
        except Exception:
            return None, None, False
        bid = book.bid.best.price if book.bid.best else None
        ask = book.ask.best.price if book.ask.best else None
        return bid, ask, book.is_crossed

    def _record_fills(mark, events):
        """Classify each fill by the arm the SESSION actually took, read off the
        fill event. ``detail['maker']`` is stamped by the exchange: True when a
        resting order filled from the tape as a maker, False when it was swept as
        a taker. Reading the stamped arm -- rather than re-deriving marketability
        here -- makes this a single source of truth: it can never disagree with
        the routing the session performed, however that routing later changes."""
        for e in events:
            if _kind(e) not in ("filled", "partially_filled"):
                continue
            side, _limit = orders.get(e.order_id, (None, None))
            ledger.fills.append({
                "mark": mark, "side": side, "quantity": e.quantity,
                "price": e.price, "maker": bool(e.detail.get("maker"))})

    def _position() -> Tuple[int, int]:
        h = session.holdings(mm.ticker)
        settled = int(getattr(h, "settled", 0) or 0)
        unsettled = int(getattr(h, "unsettled_quantity", 0) or 0)
        return settled, unsettled

    def _submit(side: Side, price: Decimal):
        ack = session.submit(Order(ticker=mm.ticker, side=side,
                                   quantity=mm.size, order_type=OrderType.LIMIT,
                                   limit_price=price))
        if isinstance(ack, Accepted):
            orders[ack.order_id] = (side, price)

    def _post(now: datetime):
        bid, ask, crossed = _touch(now)
        if crossed:
            # A reconstructed crossed book (bid above ask) is not a market; a
            # quote posted on it would be marketable at once and swept, which is
            # a taker artifact, not the maker behaviour under study.
            return
        settled, unsettled = _position()
        bid, ask = mm.quotes(bid, ask, position=settled + unsettled)
        if ask is not None and settled >= mm.size:            # T+2: sell settled only
            _submit(Side.SELL, ask)
        if bid is not None:
            _submit(Side.BUY, bid)

    d = datetime.fromisoformat(day).date()
    session.advance_to(datetime.combine(d, schedule[0]))
    _post(datetime.combine(d, schedule[0]))
    for mark in schedule[1:]:
        now = datetime.combine(d, mark)
        events = session.advance_to(now)
        _record_fills(mark, events)
        for record in session.orders():                        # cancel, re-quote
            if not record.is_terminal:
                session.cancel(record.order_id)
        settled, unsettled = _position()
        ledger.inventory.append({"mark": mark, "settled": settled,
                                 "unsettled": unsettled,
                                 "position": settled + unsettled})
        _post(now)

    # End of day: stop quoting and let the last interval's fills land.
    close = datetime.combine(d, time(14, 40))
    _record_fills(time(14, 40), session.advance_to(close))
    for record in session.orders():
        if not record.is_terminal:
            session.cancel(record.order_id)
    settled, unsettled = _position()
    ledger.inventory.append({"mark": time(14, 40), "settled": settled,
                             "unsettled": unsettled,
                             "position": settled + unsettled})
    ledger.provenance = session.provenance().fill_policy_kind
    ledger._session = session          # for conservation, read back publicly
    return ledger


if __name__ == "__main__":
    if not tape_available():
        raise SystemExit("sized tape not found")
    mm = InventoryMarketMaker(ticker="FPT", target=40000, band=8000, size=3000)
    led = run_market_maker(mm)
    print("S8 — intraday inventory market-maker (FPT, 2022-11-09, optimistic)")
    print(f"  provenance: {led.provenance}")
    print(f"  fills: {len(led.fills)}  buys {len(led.buys())} "
          f"sells {len(led.sells())}")
    print(f"  buy value {led.buy_value():,.0f}  sell value {led.sell_value():,.0f}")
    print("  inventory (mark: settled / unsettled / position):")
    for row in led.inventory:
        print(f"    {row['mark']}  {row['settled']:>7} / {row['unsettled']:>7}"
              f" / {row['position']:>7}")
    c = led._session.cash()
    print(f"  cash: settled {c.settled_balance:,.0f}  pending {c.pending_total:,.0f}")
