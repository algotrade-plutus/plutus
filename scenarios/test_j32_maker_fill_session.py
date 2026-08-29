"""J32 — A resting order fills from the tape: the maker fill.

Scenario **J32** of the intraday extension, and the fill the shipped model
**cannot** produce. J28–J31 are *taker* fills: a marketable order crosses the
spread and sweeps the resting book. A *maker* does the opposite — it posts a
passive order that does not cross, joins the queue at its price, and fills only
as other people's aggressive trades **print through** that price. A book
snapshot cannot show this: at the fill instant the resting SELL sits above the
bid, so a taker/snapshot model fills nothing; the fill comes from the *tape*.

THE SETUP, chosen so the book-snapshot model provably gives zero. FPT,
    2022-11-09. A SELL of 3,000 at **74.30** is posted at 09:20 and left to
    rest. Over 09:20–11:00 the best **bid never reaches 74.30** (it peaks at
    74.20), so the offer is never marketable and a snapshot fill is zero at
    every instant. But **2,000 shares printed at or through 74.30** in that
    window — buyers lifting the offer — so a maker at the front of the queue is
    filled 2,000, at its own posted price, with 1,000 left resting.

MECHANISM — the maker arm of the book-walk policy (design 2026-08-28). The order
    is not marketable, so ``BookWalkFillPolicy`` walks the **tape** (via the
    ``TapeSource`` the ``BookSessionSource`` now composes) rather than the book:
    ``prints_through`` totals the volume through the price since the order
    arrived, the queue policy places the order in the queue (optimistic: the
    front), and ``maker_fill`` books the increment. The fill price is the
    order's own resting price — a maker earns what it posted.

POLICY (oracle)
    * A resting order fills at its **own** price as trades print through it —
      the maker counterpart to QĐ 352 Điều 6.3's resting-price match.
    * WHERE it sits in the queue is UNSOURCED (optimistic here), declared in
      config and stamped in provenance, exactly as for the taker sweep.

EXPECTED — Tier 2
    * The SELL **fills**, at **74.30** (its posted price), as ``MODELLED``
      evidence, and it is a **maker** — a plain fill, not a swept walk.
    * It fills **2,000** — ``min(order, prints through)`` at the front of the
      queue — leaving 1,000 resting.
    * The **best bid never reaches 74.30** over the window, so a book-snapshot
      taker would have filled **zero**: this fill is the tape's, not the book's.

RUN
    python scenarios/test_j32_maker_fill_session.py
    pytest scenarios/test_j32_maker_fill_session.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from plutus.market.session import ExchangeSession, Accepted, parse_config
from plutus.market.adapters.book_session import BookSessionSource
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

EXTRACT = Path("/Users/nadan/algotrade-research/dataset/hermes-dev-extract")
PRICES = "/Users/nadan/algotrade-research/dataset/hermes-parquet"
TICKER = "FPT"
PRICE = Decimal("74.30")
SUBMIT = datetime(2022, 11, 9, 9, 20)
END = datetime(2022, 11, 9, 11, 0)


def _tape_available() -> bool:
    return EXTRACT.is_dir() and (EXTRACT / "local_quote_total.parquet").exists()


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def _max_bid() -> Decimal:
    """The highest best-bid over the resting window -- the book-snapshot check."""
    con = duckdb.connect()
    row = con.execute(
        f"SELECT max(price) FROM read_parquet('{EXTRACT}/local_quote_bidprice.parquet') "
        f"WHERE tickersymbol = ? AND depth = 1 AND datetime >= ? AND datetime < ?",
        [TICKER, str(SUBMIT), str(END)]).fetchone()
    return Decimal(str(row[0]))


def run_j32():
    config = parse_config({
        "period": {"start": "2022-11-09", "end": "2022-11-10"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 200_000_000,
                                    "account_no": "SEC-J32"}},
        "fill_policy": {"kind": "book_walk", "queue": "optimistic",
                        "max_participation": None, "max_staleness": None},
    })
    source = BookSessionSource.for_roots(PRICES, str(EXTRACT))
    session = ExchangeSession.build(config, source=source,
                                    initial_holdings={TICKER: 3000})
    session.advance_to(SUBMIT)
    ack = session.submit(Order(ticker=TICKER, side=Side.SELL, quantity=3000,
                               order_type=OrderType.LIMIT, limit_price=PRICE))
    events = session.advance_to(END)
    fills = [e for e in events if _kind(e) in ("filled", "partially_filled")]
    live = [r for r in session.orders() if not r.is_terminal]
    return {"ack": ack, "fills": fills, "live": live, "session": session}


@pytest.mark.skipif(not _tape_available(),
                    reason="sized tape (local_quote_total) not found")
def test_j32_maker_fill_session():
    obs = run_j32()
    assert isinstance(obs["ack"], Accepted), obs["ack"]

    # It filled as a maker, at its OWN posted price 74.30 -- a taker SELL would
    # have filled at the *bid* levels it swept (~73.x, all below 74.30), so a
    # fill at 74.30 can only be a passive one -- and MODELLED (queue-estimated
    # from the tape, not a print we saw as ours).
    assert obs["fills"], "the resting SELL never filled from the tape"
    assert {e.price for e in obs["fills"]} == {PRICE}, obs["fills"]
    evid = {str(e.detail.get("evidence")) for e in obs["fills"]}
    assert any("MODELLED" in e for e in evid), evid

    # Front of the queue fills min(order, prints) = 2,000, leaving 1,000 resting.
    assert sum(e.quantity for e in obs["fills"]) == 2000
    assert obs["live"] and obs["live"][0].remaining_quantity == 1000

    # The book-snapshot control: the best bid never reaches 74.30, so a taker /
    # snapshot fill is zero at every instant. This fill is the tape's.
    assert _max_bid() < PRICE, _max_bid()


@pytest.mark.skipif(not _tape_available(),
                    reason="sized tape (local_quote_total) not found")
def test_j32_does_not_double_book_across_advances():
    """The tape is cumulative, so stepping the clock must book each increment
    once -- never re-book the whole entitlement. The total over three advances
    is the same 2,000 as the single advance above, not more."""
    config = parse_config({
        "period": {"start": "2022-11-09", "end": "2022-11-10"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 200_000_000,
                                    "account_no": "SEC-J32B"}},
        "fill_policy": {"kind": "book_walk", "queue": "optimistic",
                        "max_participation": None, "max_staleness": None},
    })
    source = BookSessionSource.for_roots(PRICES, str(EXTRACT))
    session = ExchangeSession.build(config, source=source,
                                    initial_holdings={TICKER: 3000})
    session.advance_to(SUBMIT)
    session.submit(Order(ticker=TICKER, side=Side.SELL, quantity=3000,
                         order_type=OrderType.LIMIT, limit_price=PRICE))
    total = 0
    for step in (datetime(2022, 11, 9, 10, 0), datetime(2022, 11, 9, 10, 30),
                 END):
        events = session.advance_to(step)
        total += sum(e.quantity for e in events
                     if _kind(e) in ("filled", "partially_filled"))
    assert total == 2000, total       # not 4,000/6,000 from re-booking


if __name__ == "__main__":
    if not _tape_available():
        raise SystemExit("sized tape (local_quote_total) not found")
    obs = run_j32()
    print("J32 — Maker fill from the tape (FPT, 2022-11-09)")
    print(f"  submit SELL 3000 @ {PRICE}: {type(obs['ack']).__name__}")
    for e in obs["fills"]:
        print(f"  filled {e.quantity} @ {e.price}  (maker, from the tape)")
    filled = sum(e.quantity for e in obs["fills"])
    print(f"  total {filled} filled, {3000 - filled} resting")
    print(f"  best bid never exceeded {_max_bid()} < {PRICE}: "
          f"a book-snapshot fill would be ZERO")
    try:
        test_j32_maker_fill_session()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
