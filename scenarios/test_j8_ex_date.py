"""J8 — Hold across an ex-date.

Scenario **J8** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Hold a position through an ex-dividend / ex-rights date and report the
reference adjustment, the quantity scaling, and the cash leg.

MECHANISM
    The ex-date reference adjustment and the matching quantity rule — the one
    place in this domain where the traceability claim cannot be fully met. The
    engine is **caller-driven**: it is deliberately NOT wired into
    ``advance_to`` (a corporate-action feed is exogenous data), so a user
    applies it explicitly to their account. The conservation principle it
    encodes: market cap is unchanged across the event — no free gain or loss on
    a day when nothing happened economically.

POLICY (oracle — SCENARIO-CATALOGUE.md J8)
    * The gazetted PRINCIPLE (reference adjusted for the dividend/rights value)
      — QĐ 352 Điều 10.3; QĐ 17 Điều 32.4 (high).
    * The adjustment ARITHMETIC is NOT in any gazetted document (A26) —
      P' = (P + Σ(Pa·a) − C)/(1 + Σa + Σb); broker/education sources, medium.
      **Mark this clearly.**
    * The 5% dividend withholding is NOT levied and is not a citable rule as
      things stand — low (uncited) (D27). The cash leg is credited GROSS.

EXPECTED — Tier 2
    * A stock dividend of 0.3 scales 1,000 held shares to 1,300 and adjusts the
      reference by 1/1.3 — and the value (qty × reference) is CONSERVED.
    * A cash dividend is credited GROSS (no 5% withholding).

RUN
    python scenarios/test_j8_ex_date.py
    pytest scenarios/test_j8_ex_date.py -v
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.broker import BrokerTerms
from plutus.market.session.corporate import (
    CorporateAction, CorporateActionEngine, CorporateActionSchedule,
    adjusted_reference, quantity_factor)
from plutus.market.session.ledgers import (
    CashLedger, EncumbranceLedger, HoldingsLedger, SecuritiesAccount)
from plutus.market.session.types import AccountRef, BrokerProfile, Venue

EX_DATE = date(2022, 11, 9)
T0 = datetime(2022, 11, 9, 9, 0)
REFERENCE = Decimal("80.0")   # the pre-ex reference (thousand đồng)


def _account(holdings=None, cash="0"):
    enc = EncumbranceLedger()
    return SecuritiesAccount(
        AccountRef.securities("SEC-J8"),
        CashLedger(Decimal(cash), BrokerTerms(), enc),
        HoldingsLedger(enc, initial=holdings),
        enc,
        profile=BrokerProfile(name="j8-retail"))


def _engine():
    return CorporateActionEngine(CorporateActionSchedule(()))


def _held(holding) -> int:
    return holding.settled + sum(t.quantity for t in holding.unsettled)


def run_j8():
    # A stock dividend of 0.3 on a 1,000-share holding.
    stock = _account(holdings={"FPT": 1000})
    div = CorporateAction.stock_dividend("FPT", EX_DATE, Decimal("0.3"))
    applied_stock = _engine().apply(div, account=stock, ts=T0)
    adj = adjusted_reference(div, REFERENCE, venue=Venue.HSX)
    factor = adj.quantity_factor
    ref_after = adj.raw_reference   # unrounded, so value conservation is exact

    # A cash dividend of 2,000đ/share on a 1,000-share holding.
    cashacct = _account(holdings={"FPT": 1000}, cash="0")
    cashdiv = CorporateAction.cash_dividend("FPT", EX_DATE, Decimal("2000"))
    applied_cash = _engine().apply(cashdiv, account=cashacct, ts=T0)

    return {"applied_stock": applied_stock, "factor": factor, "ref_after": ref_after,
            "applied_cash": applied_cash, "cashacct": cashacct}


def test_j8_ex_date():   # no corpus needed — pure engine + account arithmetic
    obs = run_j8()

    # Quantity scaling: 1,000 -> 1,300 on a 0.3 stock dividend.
    assert _held(obs["applied_stock"].holding_after) == 1300, obs["applied_stock"].holding_after
    assert obs["factor"] == Decimal("1.3"), obs["factor"]

    # Reference adjusted by 1/1.3, and the VALUE is conserved — no free gain.
    value_before = Decimal(1000) * REFERENCE
    value_after = Decimal(1300) * obs["ref_after"]
    assert abs(value_after - value_before) < Decimal("0.01"), (value_before, value_after)

    # Cash dividend credited GROSS — the 5% withholding is not levied (D27).
    assert obs["applied_cash"].cash_leg == Decimal("2000000"), obs["applied_cash"].cash_leg
    assert obs["cashacct"].cash().settled_balance == Decimal("2000000")


if __name__ == "__main__":
    obs = run_j8()
    print("J8 — Hold across an ex-date (FPT, 2022-11-09)")
    print(f"  stock dividend 0.3:  1000 -> {_held(obs['applied_stock'].holding_after)} shares "
          f"(factor {obs['factor']})")
    print(f"  reference {REFERENCE} -> {obs['ref_after']:.4f}  "
          f"(value {1000 * REFERENCE:,} == {1300 * obs['ref_after']:,} — conserved)")
    print(f"  cash dividend 2000đ: cash leg {obs['applied_cash'].cash_leg:,} (GROSS, no 5% withholding)")
    try:
        test_j8_ex_date()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
