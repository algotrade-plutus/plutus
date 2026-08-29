"""J24 — A strategy that runs out of cash mid-run.

Scenario **J24** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.

MECHANISM
    Funding admission on a **domestic retail cash account**: a buy is admitted
    only if the account already holds the cash (pre-funding), and each live
    order encumbers its funding. When the account cannot fund the next order it
    is refused with the binding constraint — not silently skipped. "A strategy
    that keeps trading after the money runs out" is the classic silent backtest
    failure J24 exists to catch.

POLICY (oracle — SCENARIO-CATALOGUE.md J24)
    * Buy-side pre-funding — an investor may place a buy order only with
      sufficient cash already in the account; the duty is on the securities
      company to refuse uncovered orders. TT 203/2015 Điều 7(2) → TT 120/2020
      Điều 7(1)(a) (high). (The exclusivity is scoped to a domestic retail cash
      account — margin/day-trading and foreign-institution NPF are carve-outs.)

SETUP — FPT @ 74.0: initial cash funds two 1,000-share buys (~74M each); the
third cannot be funded.

EXPECTED — Tier 2
    * The first two buys are Accepted.
    * The third is Rejected(INSUFFICIENT_CASH), with required > available and
      the available cash reported as the binding constraint.

RUN
    python scenarios/test_j24_out_of_cash.py
    pytest scenarios/test_j24_out_of_cash.py -v
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted, Rejected  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

CONFIG = {
    "period": {"start": "2022-11-09", "end": "2022-11-10"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HSX"]},
    "accounts": {"securities": {"initial_cash": 160_000_000, "account_no": "SEC-J24"}},
}

TICKER = "FPT"
PRICE = Decimal("74.0")


def run_j24() -> list:
    session = build_session(CONFIG)
    return [session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1000,
                                 order_type=OrderType.LIMIT, limit_price=PRICE))
            for _ in range(3)]


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j24_out_of_cash():
    first, second, third = run_j24()

    # The account funds two orders...
    assert isinstance(first, Accepted), first
    assert isinstance(second, Accepted), second

    # ...and refuses the third for lack of cash, with the binding constraint.
    assert isinstance(third, Rejected), third
    assert third.rule.name == "INSUFFICIENT_CASH", third.rule
    assert third.detail["required"] > third.binding_constraint


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    results = run_j24()
    print("J24 — Out of cash mid-run (FPT @ 74.0, cash 160M)")
    for i, r in enumerate(results, 1):
        rule = getattr(r, "rule", None)
        extra = ""
        if isinstance(r, Rejected):
            extra = f" required={r.detail.get('required')} available={r.binding_constraint}"
        print(f"  buy #{i}: {type(r).__name__}{'(' + rule.name + ')' if rule else ''}{extra}")
    try:
        test_j24_out_of_cash()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
