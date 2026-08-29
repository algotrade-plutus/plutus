"""J22 — Participation-cap sweep: does the edge survive being smaller?

Scenario **J22** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Group C: capacity. One order at 1%, 3% and 10% of the session's volume — how
much of the print the model is willing to give you, and what happens to the
fill as that share shrinks.

MECHANISM — the participation cap bounds the fill to a fraction of the day's
volume. It is the only thing standing between a backtest and infinite capacity.

GOVERNING "POLICY" — OUR MODELLING CHOICE, not a market rule.
    * UNSOURCED / sourced absence: no Vietnamese document caps a participant's
      share of a print at any date. The cap concept and the 0.10 default are
      A34, our modelling choice.
    * (A real, separate rule that IS sourced: HOSE's 500,000-unit maximum per
      round-lot matching order — QĐ 894 → QĐ 352 Điều 8.1. HNX/UPCoM max order
      size is UNVERIFIED. Not what this cap models.)

SETUP — SHS (HNX), 2022-06-01, day volume 8,660,900 shares. A 1,000,000-share
marketable buy under caps of 1% / 3% / 10%. All three caps bind (the order is
larger than 10% of volume), so the fill is exactly the cap × volume, floored to
the lot.

EXPECTED — Tier 2
    * Fills scale with the cap: fill(1%) < fill(3%) < fill(10%).
    * Each fill ≈ cap × day-volume (≈ 86,600 / 259,800 / 866,000).
    * So a 10× larger cap fills ≈ 10× more — capacity is the cap, not the edge.

RUN
    python scenarios/test_j22_participation_cap.py
    pytest scenarios/test_j22_participation_cap.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

TICKER = "SHS"
QTY = 1_000_000
DAY_VOLUME = 8_660_900
AFTERNOON = datetime(2022, 6, 1, 13, 0)
CAPS = (0.01, 0.03, 0.10)


def _base(cap: float) -> dict:
    return {
        "period": {"start": "2022-06-01", "end": "2022-06-02"},
        "resolution": "1d",
        "exchange_rules": {"venues": ["HNX"]},
        "accounts": {"securities": {"initial_cash": 30_000_000_000, "account_no": "SEC-J22"}},
        "fill_policy": {"kind": "soft", "max_participation": cap},
    }


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def _filled_at(cap: float) -> int:
    session = build_session(_base(cap))
    order = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=QTY,
                                 order_type=OrderType.LIMIT, limit_price=Decimal("20.0")))
    events = session.advance_to(AFTERNOON)
    oid = getattr(order, "order_id", None)
    return sum(e.quantity or 0 for e in events
               if e.order_id == oid and _kind(e) in ("filled", "partially_filled"))


def run_j22() -> dict:
    return {cap: _filled_at(cap) for cap in CAPS}


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j22_participation_cap():
    fills = run_j22()

    # Fills scale monotonically with the cap.
    assert fills[0.01] < fills[0.03] < fills[0.10], fills

    # Each fill is the cap × day-volume, floored to the lot (100).
    for cap in CAPS:
        expected = int(DAY_VOLUME * cap) // 100 * 100
        assert abs(fills[cap] - expected) <= 100, (cap, fills[cap], expected)

    # A 10x cap fills ~10x more — capacity is the cap.
    assert 9.0 < fills[0.10] / fills[0.01] < 11.0, fills


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    fills = run_j22()
    print("J22 — Participation-cap sweep (SHS, HNX, 2022-06-01, vol 8,660,900)")
    for cap in CAPS:
        print(f"  cap {cap:>5.0%}: filled {fills[cap]:>8,} / {QTY:,}")
    try:
        test_j22_participation_cap()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
