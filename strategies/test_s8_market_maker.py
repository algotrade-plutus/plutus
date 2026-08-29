"""S8 — An intraday inventory market-maker, filled off the tape.

Strategy **S8**, the intraday selling point made into a strategy a user would
write. A market-maker posts a two-sided quote at the touch, waits, and sees what
the tape lifted. Its fills are **maker** fills — the resting order filled *at its
own posted price* as trades print through it, by queue position — which the old
book-snapshot model could not produce. (A quote the market crosses into instead
fills at a *different*, better price; those are ordinary taker sweeps, and this
strategy tells the two apart by price and reports the maker fills, which are the
new thing.) The strategy core meets real FPT data on 2022-11-09 and three things
emerge that were not staged:

* **Maker fills on both sides, off the tape**, at the maker's own posted prices.

* **The inventory-management skew fires.** The day's flow is one-sided — buyers
  lift the offer, few sellers hit the bid — so the maker sells its inventory
  down; when the position falls through the lower band it stops offering and
  quotes bid-only, trying to rebuild. The risk control acts; the one-sided flow
  is why it cannot fully rebalance, which is the honest predicament, not a bug.

* **The T+2 constraint (the Vietnamese fact).** The ask can only ever sell down
  the *settled* inventory the day began with — settled inventory only falls —
  and the shares it does buy are unsettled and unsellable today. A maker here
  cannot round-trip intraday the way a futures desk can (see the VN30F variant).

And the run **conserves đồng**: the change in cash (settled + the pending T+2
sale proceeds) equals exactly sells − buys − charges. No money is invented.

The strategy and its intraday driver are in ``strategies/_intraday_mm.py``; S9
reruns the same maker as a controlled experiment to price the queue assumption.

RUN
    python strategies/test_s8_market_maker.py
    pytest strategies/test_s8_market_maker.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from _intraday_mm import (InventoryMarketMaker, run_market_maker,
                          tape_available, _extract, FINE_MARKS)
from plutus.market.session import ExchangeSession, Accepted, parse_config
from plutus.market.adapters.book_session import BookSessionSource
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

TARGET = 40000
BAND = 6000
SIZE = 8000


def run_s8():
    mm = InventoryMarketMaker(ticker="FPT", target=TARGET, band=BAND, size=SIZE,
                              skew=True)
    return run_market_maker(mm, queue="optimistic", marks=FINE_MARKS)


@pytest.mark.skipif(not tape_available(),
                    reason="sized tape (local_quote_total) not found")
def test_s8_market_maker():
    led = run_s8()

    # 1. Genuine two-sided MAKER market-making: both sides fill AT THE POSTED
    # PRICE off the tape -- the new capability, isolated from any taker sweep.
    maker_buys = sum(f["quantity"] for f in led.maker_fills()
                     if f["side"] is Side.BUY)
    maker_sells = sum(f["quantity"] for f in led.maker_fills()
                      if f["side"] is Side.SELL)
    assert maker_buys > 0, "the bid never filled as a maker"
    assert maker_sells > 0, "the ask never filled as a maker"

    # 2. The inventory-management skew fired: the position was pulled out of the
    # band (below it, here), so the maker went one-sided to manage its risk.
    pos = led.position_curve()
    assert not all(TARGET - BAND <= p <= TARGET + BAND for p in pos), pos

    # 3. The T+2 constraint emerges: settled inventory only falls (sold down,
    # never replenished by today's buys), and the shares bought today are
    # unsettled -- unsellable today, so no intraday round-trip.
    settled = [row["settled"] for row in led.inventory]
    assert all(b <= a for a, b in zip(settled, settled[1:])), settled
    assert settled[-1] < led.initial_settled, "nothing was sold down"
    assert led.inventory[-1]["unsettled"] > 0, "nothing bought (T+2 never bit)"

    # 4. Conservation: every đồng that moved is a fill or a charge.
    change, identity, charges = led.conservation()
    assert change == identity, (change, identity)
    assert charges > 0, "a day of trading levied no charges?"

    # 5. Self-reports the maker assumption it ran under.
    assert "book_walk" in led.provenance and "optimistic" in led.provenance


# --------------------------------------------------------------------------
# The VN30F variant: a futures maker, on a derivative venue
# --------------------------------------------------------------------------

def run_s8_vn30f():
    """A resting VN30F short, filled off the futures tape as a maker.

    The contrast the export was for: the same maker arm on a *derivative*. A
    futures desk shorts freely (no inventory to hold, no T+2), so it can rest an
    offer above the touch and be lifted by the tape -- a maker fill at its own
    posted price, on HNXDS, routed through the derivatives pool.
    """
    config = parse_config({
        "period": {"start": "2025-04-08", "end": "2025-04-09"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HNXDS"]},
        "accounts": {"securities": {"initial_cash": 100_000_000,
                                    "account_no": "S-MM"},
                     "derivatives": {"initial_deposit": 800_000_000,
                                     "account_no": "D-MM"}},
        "fill_policy": {"kind": "book_walk", "queue": "optimistic",
                        "max_participation": None, "max_staleness": None},
    })
    source = BookSessionSource.for_roots(str(_extract()), str(_extract()),
                                         table_prefix="quote")
    session = ExchangeSession.build(config, source=source)
    session.advance_to(datetime(2025, 4, 8, 9, 30))
    book = source.book_at("VN30F2504", datetime(2025, 4, 8, 9, 30))
    # Rest the offer two ticks ABOVE the ask, so it cannot cross -- a pure maker
    # that fills only if the tape prints up through it.
    price = book.ask.best.price + Decimal("0.2")
    ack = session.submit(Order(ticker="VN30F2504", side=Side.SELL, quantity=10,
                               order_type=OrderType.LIMIT, limit_price=price))
    events = session.advance_to(datetime(2025, 4, 8, 11, 30))
    fills = [{"quantity": e.quantity, "price": e.price}
             for e in events
             if getattr(e.kind, "value", e.kind) in ("filled", "partially_filled")]
    return {"fills": fills, "price": price,
            "position": session.positions().get("VN30F2504"),
            "provenance": session.provenance().fill_policy_kind}


@pytest.mark.skipif(not tape_available(),
                    reason="sized tape (local_quote_total) not found")
def test_s8_vn30f_futures_maker_fill():
    obs = run_s8_vn30f()
    # It filled as a maker, at its own posted price (not a swept book price), on
    # a derivative venue -- the maker arm routed HNXDS through the futures pool.
    assert obs["fills"], "the futures offer never filled"
    assert all(f["price"] == obs["price"] for f in obs["fills"]), obs["fills"]
    assert obs["provenance"] and "book_walk" in obs["provenance"]
    # A short was opened on the derivative.
    assert obs["position"] is not None and obs["position"].net_quantity < 0


if __name__ == "__main__":
    if not tape_available():
        raise SystemExit("sized tape not found")
    led = run_s8()
    print("S8 — Intraday inventory market-maker (FPT, 2022-11-09)")
    mb = sum(f["quantity"] for f in led.maker_fills() if f["side"] is Side.BUY)
    ms = sum(f["quantity"] for f in led.maker_fills() if f["side"] is Side.SELL)
    print(f"  maker fills: buys {mb}, sells {ms}   taker shares "
          f"(incidental crossings): {led.taker_shares()}")
    print("  settled / unsettled / position by mark:")
    for row in led.inventory:
        print(f"    {row['mark']}  {row['settled']:>7} / {row['unsettled']:>7}"
              f" / {row['position']:>7}")
    change, identity, charges = led.conservation()
    print(f"  conservation: Δcash {change:,.0f} == sells-buys-charges "
          f"{identity:,.0f}  (charges {charges:,.0f})")
    try:
        test_s8_market_maker()
        test_s8_vn30f_futures_maker_fill()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
