"""J23 — A 30-name VN30 basket: multi-ticker at scale.

Scenario **J23** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.

MECHANISM — mostly a system property, not a Vietnamese rule: per-name
encumbrance, per-name settlement clocks, and **one cash ledger** serving thirty
names. The per-name rules are J1's and J2's, resolved independently per order;
nothing about a basket changes them. The failure this catches is state bleeding
between names — one ticker's shares or cash showing up under another. Invisible
at three names; not at thirty.

POLICY (oracle — SCENARIO-CATALOGUE.md J23)
    Per-name admission is J1/J2. Two basket-relevant rules are UNMODELLED and
    are NOT tested here (stating them, not asserting them):
    * the simultaneous opposite-side order ban (TT 120/2020 Điều 7, medium;
      scope per-session vs per-day UNVERIFIED) — no implementation.
    * self-crossing (rulebook :208 is HNX/2025-05-05 only; UNVERIFIED on HOSE)
      — NOT BUILT.

EXPECTED — Tier 2
    * All 30 buys are accepted and fill.
    * Each name holds exactly its own 100 shares — no bleed between names.
    * The single cash ledger equals the sum of the legs: cash spent ==
      Σ (per-name settled-holding cost), within charges.

RUN
    python scenarios/test_j23_vn30_basket.py
    pytest scenarios/test_j23_vn30_basket.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted, Rejected  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

# 30 liquid HSX names on 2022-11-09 with their close (thousand đồng).
BASKET = {
    "DIG": "13.4", "STB": "16.25", "HPG": "13.0", "VPB": "17.5", "KBC": "14.2",
    "POW": "10.85", "CTG": "24.45", "SSI": "14.9", "VND": "10.45", "MBB": "16.95",
    "NKG": "9.72", "LPB": "11.4", "HSG": "9.35", "SHB": "11.0", "DXG": "11.35",
    "HAG": "7.9", "GEX": "11.8", "HCM": "20.35", "VIX": "7.0", "PVD": "16.95",
    "TCH": "7.59", "VCI": "23.5", "VHM": "44.55", "BID": "36.15", "HDB": "14.8",
    "VCG": "15.6", "DCM": "29.9", "TCB": "24.35", "HQC": "2.15", "ACB": "20.75",
}
LOT = 100
AFTERNOON = datetime(2022, 11, 9, 13, 0)

CONFIG = {
    "period": {"start": "2022-11-09", "end": "2022-11-10"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HSX"]},
    "accounts": {"securities": {"initial_cash": 200_000_000, "account_no": "SEC-J23"}},
}


def run_j23():
    session = build_session(CONFIG)
    acks = {name: session.submit(Order(ticker=name, side=Side.BUY, quantity=LOT,
                                       order_type=OrderType.LIMIT,
                                       limit_price=Decimal(px)))
            for name, px in BASKET.items()}
    session.advance_to(AFTERNOON)
    return session, acks


def _held(holding) -> int:
    """Total shares held for a name: settled plus filled-but-unsettled."""
    return holding.settled + sum(t.quantity for t in holding.unsettled)


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j23_vn30_basket():
    session, acks = run_j23()

    # All 30 legs admitted.
    assert all(isinstance(a, Accepted) for a in acks.values()), \
        [n for n, a in acks.items() if not isinstance(a, Accepted)]

    # Each name holds exactly its own 100 — no bleed between names.
    for name in BASKET:
        assert _held(session.holdings(name)) == LOT, (name, session.holdings(name))

    # The single cash ledger is the sum of the legs: money spent equals the sum
    # of the per-name costs, within charges.
    spent = Decimal("200000000") - session.cash().settled_balance
    legs = sum(Decimal(px) * LOT * 1000 for px in BASKET.values())
    assert legs <= spent, (legs, spent)               # spent covers every leg
    assert spent - legs < Decimal("2000000"), (spent, legs)  # ...plus only charges


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    session, acks = run_j23()
    n_ok = sum(isinstance(a, Accepted) for a in acks.values())
    print(f"J23 — 30-name VN30 basket (HSX, 2022-11-09)")
    print(f"  accepted: {n_ok}/{len(BASKET)}")
    print(f"  cash: {session.cash()}")
    print(f"  holdings(VHM): {session.holdings('VHM')}")
    print(f"  holdings(HPG): {session.holdings('HPG')}")
    try:
        test_j23_vn30_basket()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
