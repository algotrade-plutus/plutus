"""J6 — Roll a futures position across expiry.

Scenario **J6** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Hold VN30F into the last trading day; it cash-settles; open the next contract.

MECHANISM
    A VN30F contract's last trading day is the third Thursday of the expiry
    month. A position held to expiry is cash-settled at the final settlement
    price (never matched out), so after expiry it is gone. The roll then opens
    the next contract. The bug this catches: the roll finding nothing to close
    on expiry morning and opening a naked position in a contract that has
    already cash-settled.

POLICY (oracle — SCENARIO-CATALOGUE.md J6)
    * Last trading day = third Thursday of the expiry month, moved backward off
      a holiday — HNX contract template, 2017-08-10 → current (high). VN30F2212
      expires 2022-12-15.
    * Final settlement day is T+1, cash-settled — template + VSDC (high).
    * FSP method changed at regulation-effective 2022-06-01 / behavioural
      boundary 2022-06-16 (30-min trimmed average of the index); the corpus
      settlement series changes subject at 2022-08-17 — a DATA date, not the
      rule date. (VN30F2212 settles under the current-FSP rule.)

EXPECTED — Tier 2
    * A VN30F2212 lot held into 2022-12-15 is cash-settled by 2022-12-16 — the
      position is gone (net 0), not carried as a naked position.
    * The roll into VN30F2301 opens cleanly — one lot in the new contract.

RUN
    python scenarios/test_j6_futures_roll.py
    pytest scenarios/test_j6_futures_roll.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

FRONT = "VN30F2212"   # expires 2022-12-15
NEXT = "VN30F2301"

CONFIG = {
    "period": {"start": "2022-12-12", "end": "2022-12-20"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HNXDS"]},
    "accounts": {"derivatives": {"initial_deposit": 300_000_000, "account_no": "DER-J6"}},
}


def _net(positions, code) -> int:
    p = positions.get(code)
    return abs(p.net_quantity) if p is not None else 0


def run_j6():
    session = build_session(CONFIG)

    # Hold the front contract into its last trading day.
    session.advance_to(datetime(2022, 12, 12, 11, 0))
    session.submit(Order(ticker=FRONT, side=Side.BUY, quantity=1,
                         order_type=OrderType.LIMIT, limit_price=Decimal("1040")))
    session.advance_to(datetime(2022, 12, 12, 13, 0))     # fill the front lot
    held_before = _net(session.positions(), FRONT)

    # Advance past the 2022-12-15 expiry: the front contract cash-settles.
    settle_events = session.advance_to(datetime(2022, 12, 16, 11, 0))
    held_after = _net(session.positions(), FRONT)

    # Roll into the next contract.
    session.submit(Order(ticker=NEXT, side=Side.BUY, quantity=1,
                         order_type=OrderType.LIMIT, limit_price=Decimal("1060")))
    session.advance_to(datetime(2022, 12, 16, 13, 0))     # fill the roll
    next_held = _net(session.positions(), NEXT)

    return {"held_before": held_before, "settle_events": settle_events,
            "held_after": held_after, "next_held": next_held}


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j6_futures_roll():
    obs = run_j6()

    # The front lot was held...
    assert obs["held_before"] == 1, obs["held_before"]
    # ...and is cash-settled by T+1 after the 2022-12-15 expiry — gone, not naked.
    assert obs["held_after"] == 0, obs["held_after"]
    # The roll opens the next contract cleanly.
    assert obs["next_held"] == 1, obs["next_held"]


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j6()
    kinds = [getattr(e.kind, "value", e.kind) for e in obs["settle_events"]]
    print("J6 — Roll a futures position across expiry (VN30F2212 -> VN30F2301)")
    print(f"  VN30F2212 held before expiry: {obs['held_before']} lot")
    print(f"  events crossing 2022-12-15 expiry: {sorted(set(kinds))}")
    print(f"  VN30F2212 after expiry:       {obs['held_after']} lot (cash-settled)")
    print(f"  VN30F2301 after roll:         {obs['next_held']} lot")
    try:
        test_j6_futures_roll()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
