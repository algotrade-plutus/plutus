"""J17 — Straddle the HOSE round-lot change (2021-01-04).

Scenario **J17** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.

MECHANISM
    An order's quantity must be an exact multiple of the venue's trading unit,
    **resolved at the order's own date**. HOSE raised its round lot from 10 to
    100 units on 2021-01-04, so an identical 50-share order is a legal round
    lot before and a rejected odd lot after. The tell of a date-blind bug:
    ``AdmissionRule.ROUND_LOT`` returning the same unit on both dates.

POLICY (oracle — SCENARIO-CATALOGUE.md J17)
    * Round lot HSX 10 units, 2020-01-01 → 2021-01-03 — QĐ 67/QĐ-SGDHCM
      (never read; press/broker-corroborated) · medium.
    * Round lot HSX 100 units, 2021-01-04 → current — QĐ 894/QĐ-SGDHCM
      (2020-12-30), restated QĐ 352 Điều 8.1 · high (value) / medium (citation).
    * Odd lot is the derived 1..unit-1 range — QĐ 17 Điều 3.20 · high.

DATA NOTE
    The corpus carries no price bands before 2021-01-04 (``reference`` begins
    2021-01-04; ``ceil``/``floor`` begin 2021-02-05). The round-lot rule is
    resolved from the order's DATE and the venue trading unit, independent of
    price — so this scenario asserts the ROUND_LOT verdict directly, which is
    exactly the mechanism, and does not depend on band data the corpus lacks
    for the lot=10 era.

EXPECTED — Tier 2
    * 50-share HOSE order on 2020-12-31 (lot 10): NOT rejected for ROUND_LOT.
    * 50-share HOSE order on 2021-01-05 (lot 100): Rejected(ROUND_LOT).
    * The date-blindness tell is absent: the two dates disagree.

RUN
    python scenarios/test_j17_round_lot_change.py
    pytest scenarios/test_j17_round_lot_change.py -v
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted, Rejected  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

TICKER = "FPT"


def _config(day: str):
    return {
        "period": {"start": day, "end": day},
        "resolution": "1d",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 200_000_000, "account_no": "SEC-J17"}},
    }


def _submit_50(day: str, price: str):
    """Submit an identical 50-share HOSE buy on `day`, return the verdict."""
    session = build_session(_config(day))
    return session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=50,
                                order_type=OrderType.LIMIT, limit_price=Decimal(price)))


def run_j17() -> dict:
    before = _submit_50("2020-12-31", "59.1")   # lot = 10  -> 50 is a legal round lot
    after = _submit_50("2021-01-05", "62.7")     # lot = 100 -> 50 is an odd lot
    return {"before": before, "after": after}


def _round_lot_rejected(verdict) -> bool:
    return isinstance(verdict, Rejected) and verdict.rule.name == "ROUND_LOT"


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j17_round_lot_change():
    obs = run_j17()

    # Before the change: 50 shares is a legal round lot (multiple of 10),
    # so it is NOT rejected for ROUND_LOT.
    assert not _round_lot_rejected(obs["before"]), obs["before"]

    # After the change: 50 shares is an odd lot (lot is 100) -> ROUND_LOT.
    assert _round_lot_rejected(obs["after"]), obs["after"]


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j17()
    for label, v in (("2020-12-31 (lot 10)", obs["before"]),
                     ("2021-01-05 (lot 100)", obs["after"])):
        rule = getattr(v, "rule", None)
        print(f"  50-share HOSE order {label}: {type(v).__name__}"
              f"({rule.name if rule else ''})")
    try:
        test_j17_round_lot_change()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
