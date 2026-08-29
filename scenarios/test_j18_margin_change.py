"""J18 — Straddle the VSD initial-margin change (2022-12-15).

Scenario **J18** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Open the same 1-lot VN30F position on each side of 2022-12-15 and report the
deposit requirement. Same position, more deposit, no price move.

MECHANISM
    The VSDC initial-margin ratio is a **dated series** and
    ``IM = ratio × contracts × price × multiplier`` is recomputed on the
    current price — it is not a fixed fraction of the entry notional. So the
    same lot at the same price reserves 13% before the change and 17% after.

POLICY (oracle — SCENARIO-CATALOGUE.md J18)
    * IM ratio 13% — VSD announcement 2018-07-13, eff. 2018-07-18 → 2022-12-14
      (high). IM ratio 17% — VSD notice 2022-12-12, eff. 2022-12-15 → current,
      VaR-derived (high).
    * THE CITATION POINT: these changes were issued as **thông báo (notices)**
      under a standing delegation — **no `quyết định` number exists**; citing a
      decision number would cite something that does not exist (high).
    * IM = ratio × contracts × price × multiplier (multiplier 100,000đ/point);
      the model is date-keyed only — our declared modelling choice (the real
      key is (contract_code, effective_date)).

SETUP — VN30F2301, a 1-lot buy at the same limit (1060) on 2022-12-14 and
2022-12-16. Reserving on entry isolates the ratio: no VM, held across nothing,
so must-list item 4 (VM) does not bite.

EXPECTED — Tier 2
    * The reserved IM implies ratio ≈ 0.13 on 2022-12-14 and ≈ 0.17 on
      2022-12-16 — the dated series, recomputed.
    * Same position, same price: the deposit requirement jumps ≈ +30.8%.

RUN
    python scenarios/test_j18_margin_change.py
    pytest scenarios/test_j18_margin_change.py -v
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

TICKER = "VN30F2301"
LIMIT = Decimal("1060")
MULTIPLIER = Decimal("100000")


def _reserved_im(day: str) -> Decimal:
    cfg = {
        "period": {"start": day, "end": "2022-12-30"},
        "resolution": "1d",
        "exchange_rules": {"venues": ["HNXDS"]},
        "accounts": {"derivatives": {"initial_deposit": 200_000_000,
                                     "account_no": "DER-J18"}},
    }
    session = build_session(cfg)
    buy = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1,
                               order_type=OrderType.LIMIT, limit_price=LIMIT))
    assert isinstance(buy, Accepted), buy
    return sum(e.amount for e in buy.encumbrances)


def run_j18() -> dict:
    before = _reserved_im("2022-12-14")   # 13% regime
    after = _reserved_im("2022-12-16")    # 17% regime
    notional = LIMIT * MULTIPLIER
    return {"before": before, "after": after,
            "ratio_before": before / notional, "ratio_after": after / notional}


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j18_margin_change():
    obs = run_j18()

    # The dated IM series: 13% before the change, 17% after.
    assert abs(obs["ratio_before"] - Decimal("0.13")) < Decimal("0.001"), obs["ratio_before"]
    assert abs(obs["ratio_after"] - Decimal("0.17")) < Decimal("0.001"), obs["ratio_after"]

    # Same position, same price, more deposit: ~+30.8%.
    jump = (obs["after"] - obs["before"]) / obs["before"]
    assert Decimal("0.30") < jump < Decimal("0.32"), jump


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j18()
    print("J18 — VSD initial-margin change (VN30F2301, 1 lot @ 1060)")
    print(f"  2022-12-14 (13% regime): IM {obs['before']:>14,}  ratio {obs['ratio_before']:.4f}")
    print(f"  2022-12-16 (17% regime): IM {obs['after']:>14,}  ratio {obs['ratio_after']:.4f}")
    jump = (obs["after"] - obs["before"]) / obs["before"]
    print(f"  same position, no price move: deposit +{jump * 100:.1f}%")
    try:
        test_j18_margin_change()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
