"""J14 — ATO vs a marketable LO into the same auction.

Scenario **J14** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
An ATO order and a marketable LO submitted into the same opening auction both
cross at the **published open** — but the ATO gets one shot (it dies at the
cross) while the LO's remainder would carry into continuous.

MECHANISM — the auction crosses at one price for everyone, and we take that
price to be the session's **published open** (ATO) or **close** (ATC). This is
**OUR MODELLING CHOICE**, not a rule: we do not trust the tick data inside the
auction window, so we use the published open/close already in the database.
The auction fill is reached only when a source emits an auction phase (the
default daily adapter stamps every bar CONTINUOUS, so on the session path
J14/J7 are blocked pending that source — publish-checklist SHOULD/MUST #5).
Here we drive the fill directly, like the book walk in J13.

POLICY (oracle — SCENARIO-CATALOGUE.md J14)
    * QĐ 352 Điều 2.5 defines the CLOSE as the day's last match — CONTEXT for
      why the published close is a fair stand-in, not a rule for the cross.
      "giá mở cửa" appears nowhere in the rulebook — no instrument defines an
      opening price at all. So the price rule is ours, carrying no measurement.
    * A cross fills everyone at one price — QĐ 352 Điều 6.2 (the four-step
      algorithm derives it from a book; we substitute the published value).

SETUP — FPT, 2022-11-09: published open 73.3. An ATO buy and a marketable LO
(limit 74.0 ≥ open) both submitted into the opening auction.

EXPECTED — Tier 2
    * The ATO fills at the published open (73.3).
    * The marketable LO fills at the same cross (73.3) — one price for everyone.
    * (The distinction the scenario names: the ATO dies at the cross; the LO's
      remainder carries to continuous — a time-in-force fact, stated here.)

RUN
    python scenarios/test_j14_auction_cross.py
    pytest scenarios/test_j14_auction_cross.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from plutus.market.protocol import (
    BandSource, MarketState, Order, Resolution, SessionPhase)
from plutus.market.session.fills import auction_fill_price
from plutus.market.session.types import (
    MarketInterval, OrderRecord, OrderState, TimeInForce, Venue)
from plutus.core.order import OrderType, Side

TS = datetime(2022, 11, 9, 9, 0)
OPEN = Decimal("73.3")
CLOSE = Decimal("74.0")


def _opening_interval() -> MarketInterval:
    state = MarketState(ticker="FPT", ts=TS, session=SessionPhase.OPENING_AUCTION,
                        reference=Decimal("72.9"), ceiling=Decimal("78.0"),
                        floor=Decimal("67.8"), band_source=BandSource.PUBLISHED,
                        last=OPEN)
    return MarketInterval(ticker="FPT", start=TS, end=TS + timedelta(seconds=1),
                          resolution=Resolution.TICK, state=state,
                          open=OPEN, close=CLOSE)


def _order(order_type, *, limit=None) -> OrderRecord:
    return OrderRecord(
        order_id="O-J14", venue=Venue.HSX, state=OrderState.RESTING,
        time_in_force=TimeInForce.DAY, submitted_at=TS, updated_at=TS,
        order=Order(ticker="FPT", side=Side.BUY, quantity=1000,
                    order_type=order_type, limit_price=limit))


def run_j14():
    interval = _opening_interval()
    ato = _order(OrderType.AT_THE_OPENING)
    lo = _order(OrderType.LIMIT, limit=CLOSE)   # marketable into the auction
    return {
        "ato_price": auction_fill_price(ato, interval),
        "lo_price": auction_fill_price(lo, interval),
    }


def test_j14_auction_cross():
    obs = run_j14()

    # The ATO crosses at the published open.
    assert obs["ato_price"] == OPEN, obs["ato_price"]

    # The marketable LO crosses at the SAME published open — one price for all.
    assert obs["lo_price"] == OPEN, obs["lo_price"]
    assert obs["ato_price"] == obs["lo_price"]


if __name__ == "__main__":
    obs = run_j14()
    print("J14 — ATO vs marketable LO into the opening auction (FPT, 2022-11-09)")
    print(f"  ATO fill:  {obs['ato_price']}  (published open)")
    print(f"  LO  fill:  {obs['lo_price']}  (same cross — one price for everyone)")
    try:
        test_j14_auction_cross()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
