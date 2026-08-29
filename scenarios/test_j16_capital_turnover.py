"""J16 — Capital turnover under T+2.

Scenario **J16** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Run one rule for a month and count the round trips; then run it again with the
sale advance enabled. What caps turnover is not commission but the **settlement
cycle** — and the advance relaxes the cash leg.

MECHANISM
    A round trip is buy → hold to settlement (T+2) → sell. After the sale the
    proceeds do not settle for another T+2, so without the advance the capital
    cannot be redeployed until then; with the advance it is spendable at once.
    So the same capital turns over more times in the same window with the
    advance than without it.

POLICY (oracle — SCENARIO-CATALOGUE.md J16)
    * Cash and securities settle on the same T+2 cycle; sell-then-rebuy on the
      same day is not possible on settled cash alone — QĐ 109 Điều 4;
      TT 120/2020 Điều 7(3), Điều 11 (high). No short sale, no intraday round
      trip of the same shares.
    * Day trading (T+0) is legally provided for and never operational (no VSDC
      SBL) — TT 120/2020 Điều 10 (high). The advance is the real "lướt T0", and
      it costs the advance fee (a broker term).

EXPECTED — Tier 2
    * The greedy buy/sell rule completes strictly MORE round trips with the
      advance enabled than without — capital turns over faster.
    * Without the advance, turnover is bounded by the settlement cycle.

RUN
    python scenarios/test_j16_capital_turnover.py
    pytest scenarios/test_j16_capital_turnover.py -v
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted, Rejected  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

TICKER = "FPT"
LOT = 1000
# FPT trading days in Nov 2022 with their close (thousand đồng).
DAYS = [
    ("2022-11-01", "75.5"), ("2022-11-02", "74.0"), ("2022-11-03", "74.1"),
    ("2022-11-04", "72.9"), ("2022-11-07", "72.6"), ("2022-11-08", "73.3"),
    ("2022-11-09", "74.0"), ("2022-11-10", "73.0"), ("2022-11-11", "72.8"),
    ("2022-11-14", "70.8"), ("2022-11-15", "65.9"), ("2022-11-16", "69.3"),
    ("2022-11-17", "71.0"), ("2022-11-18", "71.5"), ("2022-11-21", "70.1"),
    ("2022-11-22", "70.5"), ("2022-11-23", "70.5"), ("2022-11-24", "70.5"),
    ("2022-11-25", "72.0"), ("2022-11-28", "74.3"), ("2022-11-29", "74.3"),
]


def _config(advance_enabled: bool) -> dict:
    cfg = {
        "period": {"start": "2022-11-01", "end": "2022-12-01"},
        "resolution": "1d",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 80_000_000, "account_no": "SEC-J16"}},
    }
    if advance_enabled:
        cfg["broker_profile"] = {
            "advance_sale_proceeds": {"enabled": True, "daily_rate": "0.0003"},
        }
    return cfg


def _dt(day: str, hh: int, mm: int) -> datetime:
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, hh, mm)


def count_round_trips(advance_enabled: bool) -> int:
    """A greedy rule: sell the settled position when you have one, else buy.
    Returns how many complete round trips finished in the window."""
    session = build_session(_config(advance_enabled))
    round_trips = 0
    for day, close in DAYS:
        session.advance_to(_dt(day, 13, 0))              # settle anything due
        held = session.holdings(TICKER).settled
        price = Decimal(close)
        if held >= LOT:
            r = session.submit(Order(ticker=TICKER, side=Side.SELL, quantity=LOT,
                                     order_type=OrderType.LIMIT, limit_price=price))
            if isinstance(r, Accepted):
                session.advance_to(_dt(day, 14, 45))     # fill the sale
                round_trips += 1
        else:
            r = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=LOT,
                                     order_type=OrderType.LIMIT, limit_price=price))
            if isinstance(r, Accepted):
                session.advance_to(_dt(day, 14, 45))     # fill the buy
    return round_trips


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j16_capital_turnover():
    without = count_round_trips(False)
    with_advance = count_round_trips(True)

    # Settlement gates turnover: without the advance at least one round trip
    # completes, but capital idles between the sale and its settlement.
    assert without >= 1, without

    # The advance recycles the sale proceeds sooner, so more round trips fit
    # the same month — turnover is higher.
    assert with_advance > without, (without, with_advance)


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    without = count_round_trips(False)
    with_advance = count_round_trips(True)
    print("J16 — Capital turnover under T+2 (FPT, Nov 2022)")
    print(f"  round trips WITHOUT advance: {without}")
    print(f"  round trips WITH advance:    {with_advance}")
    print(f"  the advance added {with_advance - without} round trips of turnover")
    try:
        test_j16_capital_turnover()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
