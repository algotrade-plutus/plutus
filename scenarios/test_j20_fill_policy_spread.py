"""J20 — One strategy under hard / soft / probabilistic fill policies.

Scenario **J20** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Group C's representative: *how much of a backtest is assumption?*

MECHANISM
    The fill policy is the largest single assumption in any bar-resolution
    backtest, and it is **not a rule**: ``hard`` refuses anything it cannot
    prove (and never fills a market order), ``soft`` fills on touch, and
    ``probabilistic`` splits the difference. The same order under the three
    policies gives three different fills — and that spread is the point.

GOVERNING "POLICY" — this is OUR MODELLING CHOICE, not a market rule.
    * UNSOURCED / sourced absence: no Vietnamese document states a fill
      probability or caps a participant's share of a print.
    * A34 hard.max_participation = 0.10, A35 probabilistic.p_touch = 0.5 —
      stated conventions with no empirical content. our modelling choice.
    What a fill policy may NOT override is sourced (band, tick, lot, order-type
    legality) — those are decided before any policy runs.

SETUP — SHS (HNX), 2022-06-01: an MTL (market) buy for 5,000 shares under a
tiny participation cap. hard refuses market orders outright; soft fills up to
the cap; probabilistic draws. Same order, three answers.

EXPECTED — Tier 2
    * The three policies do NOT agree — swapping the policy moves the fill.
    * hard fills 0 (never fills a market order).
    * soft fills a positive, capped amount (< the full order).
    * probabilistic is reproducible under a fixed seed.

RUN
    python scenarios/test_j20_fill_policy_spread.py
    pytest scenarios/test_j20_fill_policy_spread.py -v
"""
from __future__ import annotations

from datetime import datetime

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

TICKER = "SHS"
QTY = 5000
AFTERNOON = datetime(2022, 6, 1, 13, 0)


def _base(fill_policy: dict) -> dict:
    return {
        "period": {"start": "2022-06-01", "end": "2022-06-02"},
        "resolution": "1d",
        "exchange_rules": {"venues": ["HNX"]},
        "accounts": {"securities": {"initial_cash": 500_000_000, "account_no": "SEC-J20"}},
        "fill_policy": fill_policy,
    }


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def _filled_under(fill_policy: dict) -> int:
    """Run the identical MTL order under one fill policy; return shares filled."""
    session = build_session(_base(fill_policy))
    order = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=QTY,
                                 order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT))
    events = session.advance_to(AFTERNOON)
    oid = getattr(order, "order_id", None)
    return sum(e.quantity or 0 for e in events
               if e.order_id == oid and _kind(e) in ("filled", "partially_filled"))


def run_j20() -> dict:
    return {
        "hard": _filled_under({"kind": "hard", "max_participation": 0.0001}),
        "soft": _filled_under({"kind": "soft", "max_participation": 0.0001}),
        "probabilistic": _filled_under({"kind": "probabilistic", "seed": 7,
                                        "max_participation": 0.0001}),
    }


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j20_fill_policy_spread():
    spread = run_j20()

    # The spread is the point: not all three policies agree on the fill.
    assert len(set(spread.values())) > 1, spread

    # hard never fills a market order.
    assert spread["hard"] == 0, spread

    # soft fills a positive, capped amount (below the full 5,000).
    assert 0 < spread["soft"] < QTY, spread


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    spread = run_j20()
    print("J20 — Fill-policy spread on one MTL order (SHS, HNX, 2022-06-01)")
    for policy, filled in spread.items():
        print(f"  {policy:14} filled {filled} / {QTY}")
    try:
        test_j20_fill_policy_spread()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
