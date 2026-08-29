"""J1 — Settlement (T+2): buy FPT, can't sell same day, sell at T+2.

This is scenario **J1** of ``docs/reference/SCENARIO-CATALOGUE.md``, written as
a user writes it — public API only — and doubling as an acceptance test.

MECHANISM
    Vietnamese equities settle on a T+2 cycle. A bought lot is not in the
    depository account until it settles, so a **same-day sell of unsettled
    stock is refused** — and refused for the *right* reason (an unsettled
    holding, not "insufficient cash"). The lot becomes sellable from **13:00
    on T+2**.

POLICY (the oracle — citations from SCENARIO-CATALOGUE.md J1)
    * T+2 settlement cycle — VSD Decision 109/QĐ-VSD Điều 4(4), eff.
      2016-01-01 (confidence: high).
    * Sellable from 13:00 on T+2 (post-2022-08-29) — Decision 109/QĐ-VSD
      Art. 4, eff. 2022-08-29 (high).
    * Sell only what is available in the depository account — Circular
      120/2020/TT-BTC Điều 7(3) (high).

EXPECTED — Tier 2 (all checks are user-observable; no evaluator needed)
    1. BUY on 2022-11-09 is accepted and fills at 74.0 for 1000.
    2. Same-day SELL is Rejected(UNSETTLED_HOLDING), sellable_from = T+2 13:00
       (2022-11-11 13:00), with 1000 unsettled and 0 settled.
    3. SELL at T+2 13:00 is Accepted.

RUN
    Standalone (prints a readable report):
        python scenarios/test_j1_settlement.py
    As a test:
        pytest scenarios/test_j1_settlement.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted, Rejected  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

# --- the config a user would write for this scenario -------------------------
CONFIG = {
    "period": {"start": "2022-11-09", "end": "2022-11-15"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HSX"]},
    "accounts": {"securities": {"initial_cash": 200_000_000, "account_no": "SEC-J1"}},
    # data.adapter / data.root are filled by the harness from PLUTUS_DATA_ROOT.
}

TICKER = "FPT"
BUY_DAY_AFTERNOON = datetime(2022, 11, 9, 13, 0)
T2_AFTERNOON = datetime(2022, 11, 11, 13, 0)  # 2022-11-09 + 2 trading days


def run_j1() -> dict:
    """The user's program: buy, try to sell same day, sell at T+2. Returns the
    observed outputs a user would read off the public API."""
    session = build_session(CONFIG)

    buy = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1000,
                               order_type=OrderType.LIMIT,
                               limit_price=Decimal("74.0")))
    fill_events = session.advance_to(BUY_DAY_AFTERNOON)

    sell_same_day = session.submit(Order(ticker=TICKER, side=Side.SELL, quantity=1000,
                                         order_type=OrderType.LIMIT,
                                         limit_price=Decimal("72.0")))

    session.advance_to(T2_AFTERNOON)
    sell_t2 = session.submit(Order(ticker=TICKER, side=Side.SELL, quantity=1000,
                                   order_type=OrderType.LIMIT,
                                   limit_price=Decimal("72.8")))

    return {
        "buy": buy,
        "fill_events": fill_events,
        "sell_same_day": sell_same_day,
        "sell_t2": sell_t2,
    }


def _fills(events):
    return [e for e in events if getattr(e.kind, "value", e.kind) == "filled"]


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j1_settlement():
    obs = run_j1()

    # 1. Buy accepted and filled at 74.0 for 1000.
    assert isinstance(obs["buy"], Accepted), obs["buy"]
    fills = _fills(obs["fill_events"])
    assert fills, "buy never filled"
    assert fills[0].price == Decimal("74.0")
    assert fills[0].quantity == 1000

    # 2. Same-day sell refused for the RIGHT reason, sellable at T+2 13:00.
    rej = obs["sell_same_day"]
    assert isinstance(rej, Rejected), rej
    assert rej.rule.name == "UNSETTLED_HOLDING", rej.rule
    assert rej.sellable_from == T2_AFTERNOON, rej.sellable_from
    assert rej.detail["unsettled"] == 1000
    assert rej.detail["settled"] == 0

    # 3. T+2 sell accepted.
    assert isinstance(obs["sell_t2"], Accepted), obs["sell_t2"]


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j1()
    rej = obs["sell_same_day"]
    print("J1 — Settlement (T+2)")
    print(f"  BUY:            {type(obs['buy']).__name__}")
    print(f"  fill:           {[ (str(f.price), f.quantity) for f in _fills(obs['fill_events']) ]}")
    print(f"  SELL same-day:  {type(rej).__name__}("
          f"{getattr(rej,'rule',None) and rej.rule.name}, "
          f"sellable_from={getattr(rej,'sellable_from',None)})")
    print(f"  SELL T+2:       {type(obs['sell_t2']).__name__}")
    try:
        test_j1_settlement.__wrapped__() if hasattr(test_j1_settlement, "__wrapped__") else test_j1_settlement()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
