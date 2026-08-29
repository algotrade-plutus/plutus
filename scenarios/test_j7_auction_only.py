"""J7 — Auction-only strategy trading ATO/ATC.

Scenario **J7** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
A strategy that trades only the opening and closing auctions: an ATO fills at
the session's published OPEN, an ATC at its published CLOSE.

MECHANISM — the auction crosses at one price for everyone, taken to be the
published open (ATO) or close (ATC). This is OUR MODELLING CHOICE, not a rule:
we do not trust the tick data inside the auction window, so we use the
published open/close already in the database. Reaching the auction fill needs a
source that emits an auction phase (the default daily adapter stamps every bar
CONTINUOUS), which is why J7 is blocked on the session path (SHOULD/MUST #5).
Here we drive the fills directly, like J13/J14.

POLICY (oracle — SCENARIO-CATALOGUE.md J7, inheriting J14)
    * QĐ 352 Điều 2.5 defines the close as the day's last match (CONTEXT). No
      instrument defines an opening price at all — the published open/close as
      the cross is ours, carrying no measurement.
    * A cross fills everyone at one price — QĐ 352 Điều 6.2.

SETUP — FPT, 2022-11-09: published open 73.3, close 74.0.

EXPECTED — Tier 2
    * An ATO buy fills at the published open (73.3).
    * An ATC buy fills at the published close (74.0).
    * The two auctions cross at different published prices.

RUN
    python scenarios/test_j7_auction_only.py
    pytest scenarios/test_j7_auction_only.py -v
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


def _interval(phase: SessionPhase) -> MarketInterval:
    state = MarketState(ticker="FPT", ts=TS, session=phase,
                        reference=Decimal("72.9"), ceiling=Decimal("78.0"),
                        floor=Decimal("67.8"), band_source=BandSource.PUBLISHED,
                        last=OPEN)
    return MarketInterval(ticker="FPT", start=TS, end=TS + timedelta(seconds=1),
                          resolution=Resolution.TICK, state=state,
                          open=OPEN, close=CLOSE)


def _order(order_type) -> OrderRecord:
    return OrderRecord(
        order_id="O-J7", venue=Venue.HSX, state=OrderState.RESTING,
        time_in_force=TimeInForce.DAY, submitted_at=TS, updated_at=TS,
        order=Order(ticker="FPT", side=Side.BUY, quantity=1000,
                    order_type=order_type))


def run_j7():
    ato_price = auction_fill_price(
        _order(OrderType.AT_THE_OPENING), _interval(SessionPhase.OPENING_AUCTION))
    atc_price = auction_fill_price(
        _order(OrderType.AT_THE_CLOSE), _interval(SessionPhase.CLOSING_AUCTION))
    return {"ato_price": ato_price, "atc_price": atc_price}


def test_j7_auction_only():
    obs = run_j7()
    assert obs["ato_price"] == OPEN, obs["ato_price"]      # opening auction -> open
    assert obs["atc_price"] == CLOSE, obs["atc_price"]     # closing auction -> close
    assert obs["ato_price"] != obs["atc_price"]


if __name__ == "__main__":
    obs = run_j7()
    print("J7 — Auction-only strategy (FPT, 2022-11-09)")
    print(f"  ATO fill:  {obs['ato_price']}  (published open)")
    print(f"  ATC fill:  {obs['atc_price']}  (published close)")
    try:
        test_j7_auction_only()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
