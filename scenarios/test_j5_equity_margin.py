"""J5 — Margin-financed equity position that gets called and force-sold.

Scenario **J5** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Buy on margin, hold into a decline, receive the call, fail to cure, get sold
out (*bán giải chấp*). Unlike the derivatives side, the equity forced sale
**actually executes**.

MECHANISM
    Equity margin lending: the statutory ratio floors (imr ≥ 50%, mmr ≥ 30%),
    the account algebra, the call at the broker's maintenance rung, the cure
    window, and the forced sale — which goes through ``session.submit`` against
    band, tick, lot and fill policy like any order, so it fills on a tradeable
    day and would be refused ``BAND_LOCK`` on a locked one.

POLICY (oracle — SCENARIO-CATALOGUE.md J5)
    * imr ≥ 50%, mmr ≥ 30% — QĐ 87/QĐ-UBCK Điều 5(1),(2), VERIFIED.
    * Call → cure window ≤ 3 business days → forced sale — QĐ 87 Điều 7.1, 8;
      TT 120 Điều 9.6 (VERIFIED). The call/force LEVELS (0.40/0.30 here) are a
      broker term, UNSOURCED — our modelling choice.

SETUP — HPG, 2022-09-23 → 2022-11-04. Buy 8,000 on margin (~180m against 100m
cash), then HPG slides 22.7 → 14.65 (~35%), eroding the equity through the
call and force levels.

EXPECTED — Tier 2
    * The margin buy is accepted.
    * A margin CALL is issued as the equity ratio falls below the call level.
    * A forced sale FIRES and EXECUTES (detail['executed'] is True) — the
      account is sold out, not carried.

RUN
    python scenarios/test_j5_equity_margin.py
    pytest scenarios/test_j5_equity_margin.py -v
"""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.adapters.datahub import DataHubSource
from plutus.market.session import ExchangeSession, Accepted, Venue  # noqa: F401
from plutus.market.session.calendar import weekday_settlement_calendar
from plutus.market.session.equity_margin import EquityMarginAccount
from plutus.market.session.margin_lending import (
    BrokerMarginTerms, DayCount, ForcedSalePrice, InterestTier,
    LiquidationOrder, MarginEligibility, ProceedsComponent, SecurityEligibility)
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import data_root, data_available

TICKER = "HPG"
WINDOW_START = date(2022, 9, 23)
DAYS = [
    "2022-09-26", "2022-09-27", "2022-09-28", "2022-09-29", "2022-09-30",
    "2022-10-03", "2022-10-04", "2022-10-05", "2022-10-06", "2022-10-07",
    "2022-10-10", "2022-10-11", "2022-10-12", "2022-10-13", "2022-10-14",
    "2022-10-17", "2022-10-18", "2022-10-19", "2022-10-20", "2022-10-21",
    "2022-10-24", "2022-10-25", "2022-10-26", "2022-10-27", "2022-10-28",
    "2022-10-31", "2022-11-01", "2022-11-02", "2022-11-03", "2022-11-04",
]


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def run_j5():
    source = DataHubSource.for_root(data_root())
    cfg = {
        "period": {"start": "2022-09-23", "end": "2022-11-05"},
        "resolution": "1d",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 100_000_000, "account_no": "SEC-J5"}},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(cfg, fh)
        path = fh.name
    session = ExchangeSession.from_config(path, source=source)

    terms = BrokerMarginTerms(
        maintenance_margin_ratio=Decimal("0.40"),   # broker call level (UNSOURCED)
        liquidation_margin_ratio=Decimal("0.30"),   # broker force level (UNSOURCED)
        forced_sale_price=ForcedSalePrice.FLOOR,
        day_count=DayCount.ACT_365,
        liquidation_order=LiquidationOrder.LARGEST_POSITION_FIRST,
        proceeds_application_order=tuple(ProceedsComponent),
        initial_margin_ratio=Decimal("0.50"),       # QĐ 87 Điều 5(1) floor
        rate_schedule=(InterestTier(0, None, Decimal("0.135")),),
    )
    eligibility = {TICKER: SecurityEligibility(
        ticker=TICKER, as_of=WINDOW_START, result=MarginEligibility.ELIGIBLE,
        venue=Venue.HSX, on_broker_list=True,
        note="ASSERTED by this scenario")}
    account = EquityMarginAccount(
        account_id="KQ-J5", terms=terms, calendar=weekday_settlement_calendar(),
        market_feed=source.state_at, eligibility=eligibility, tickers=(TICKER,),
        execute_forced_sale=True)
    session.attach_equity_margin(account)

    session.advance_to(datetime(2022, 9, 23, 11, 0))
    buy = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=8000,
                               order_type=OrderType.LIMIT, limit_price=Decimal("23.0"),
                               on_margin=True))
    session.advance_to(datetime(2022, 9, 23, 14, 0))     # fill the margin buy

    events = []
    for day in DAYS:
        y, m, d = (int(x) for x in day.split("-"))
        # 15:00 is after the 14:45 margin-determination time, so the QĐ 87
        # Điều 6.1 ratio determination runs each session.
        events.extend(session.advance_to(datetime(y, m, d, 15, 0)))

    called = [e for e in events if _kind(e) == "margin_call"]
    forced = [e for e in events if _kind(e) == "forced_liquidation"]
    executed = [e for e in forced if e.detail.get("executed") is True]
    return {"buy": buy, "called": called, "forced": forced, "executed": executed,
            "session": session, "account": account}


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j5_equity_margin():
    obs = run_j5()

    assert isinstance(obs["buy"], Accepted), obs["buy"]
    assert obs["called"], "no margin call issued through the drawdown"
    assert obs["executed"], "forced sale reported but never executed"


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j5()
    print("J5 — Margin-financed equity, called and force-sold (HPG, Oct 2022)")
    acc = obs["account"]
    print(f"  margin buy:       {type(obs['buy']).__name__}  (loan drawn, debt {acc.margin_debt:,})")
    print(f"  determinations:   {len(acc.determinations)} sessions assessed")
    print(f"  margin calls:     {len(obs['called'])}")
    print(f"  forced sales:     {len(obs['forced'])}  (executed: {len(obs['executed'])})")
    try:
        test_j5_equity_margin()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
