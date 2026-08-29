"""J27 — Amend a resting order: up, down, and across the price.

Scenario **J27** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
This scenario exists because must-list item 2 was exhibited by no other
scenario: amendment is the one instruction that can change an order's funding
requirement and its admissibility *after* admission already ran, and the
exchange must re-run both.

MECHANISM
    * An amend-UP re-runs the encumbrance — it grows the reservation, or is
      refused INSUFFICIENT_CASH when the larger order is not funded. It cannot
      escape funding.
    * A price amendment re-runs admission (band) and the encumbrance.
    * A quantity amendment is re-checked against round lot: 1500 → 50 on HOSE
      after 2021-01-04 is an odd lot with nowhere to trade, and is refused.
    * Priority survives only where the dated rule says so — an increase never
      preserves it; a decrease does (from 2022-03-31, VNX QĐ 17 Điều 22.3).

POLICY (oracle — SCENARIO-CATALOGUE.md J27)
    * The pre-funding, round-lot and priority rules are Vietnamese and dated
      (TT 120/2020 Điều 7(1)(a); QĐ 894 round lot; QĐ 17 Điều 22.3). But NO
      Vietnamese document requires an exchange to re-run funding or admission
      on an amendment — that is the broker's duty. So MUST #2 is a defect
      against OUR design §5 ("amending must re-run the encumbrance so an
      amend-up cannot escape funding"), not against a gazetted rule.

SETUP — FPT, 2022-11-09 (post-2021 lot = 100; post-2022-03-31 priority rule).
A resting buy of 1,000 @ 70.0 (below the market, so it rests unfilled), then a
sequence of amendments. Cash 150M funds up to ~2,100 shares at 70.0.

EXPECTED — Tier 2
    a. amend UP to 1,500 -> Amended, reservation grows, priority NOT preserved.
    b. amend the PRICE to 72.0 -> Amended (within band), reservation re-taken.
    c. amend DOWN to 50 (odd lot) -> Rejected(ROUND_LOT) — the illegal size is
       caught; the order is unchanged.
    d. amend DOWN to 500 (legal lot) -> Amended, priority preserved.

RUN
    python scenarios/test_j27_amend.py
    pytest scenarios/test_j27_amend.py -v
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from plutus.market.session import (
    ExchangeSession, Accepted, Amended, Rejected,  # noqa: F401
)
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

CONFIG = {
    "period": {"start": "2022-11-09", "end": "2022-11-10"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HSX"]},
    "accounts": {"securities": {"initial_cash": 150_000_000, "account_no": "SEC-J27"}},
}
TICKER = "FPT"


def run_j27():
    session = build_session(CONFIG)
    # A resting buy below the market — it does not fill, so it can be amended.
    ack = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1000,
                               order_type=OrderType.LIMIT, limit_price=Decimal("70.0")))
    committed0 = session.cash().committed

    up = session.amend(ack.order_id, quantity=1500)          # a: amend-up, re-fund
    committed_up = session.cash().committed
    price = session.amend(ack.order_id, limit_price=Decimal("72.0"))  # b: price, re-admit
    odd = session.amend(ack.order_id, quantity=50)            # c: odd lot -> refused
    down = session.amend(ack.order_id, quantity=500)         # d: legal decrease

    return {"ack": ack, "committed0": committed0, "up": up,
            "committed_up": committed_up, "price": price, "odd": odd, "down": down}


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j27_amend():
    obs = run_j27()

    assert isinstance(obs["ack"], Accepted), obs["ack"]

    # a. Amend-up re-runs the encumbrance: the reservation grows, and an
    #    increase gives up queue priority.
    assert isinstance(obs["up"], Amended), obs["up"]
    assert obs["up"].quantity == 1500
    assert obs["up"].priority_preserved is False
    assert obs["committed_up"] > obs["committed0"], (obs["committed0"], obs["committed_up"])

    # b. A price amendment is re-admitted against the band and accepted.
    assert isinstance(obs["price"], Amended), obs["price"]
    assert obs["price"].limit_price == Decimal("72.0")

    # c. A decrease onto an odd lot is caught by round-lot re-admission.
    assert isinstance(obs["odd"], Rejected), obs["odd"]
    assert obs["odd"].rule.name == "ROUND_LOT", obs["odd"].rule

    # d. A legal decrease succeeds and preserves priority (post-2022-03-31).
    assert isinstance(obs["down"], Amended), obs["down"]
    assert obs["down"].quantity == 500
    assert obs["down"].priority_preserved is True


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j27()
    print("J27 — Amend a resting order (FPT, 2022-11-09)")
    print(f"  rest 1000 @ 70.0:      {type(obs['ack']).__name__}, committed={obs['committed0']}")
    up = obs["up"]
    print(f"  a. amend UP -> 1500:   {type(up).__name__}"
          f"(qty={getattr(up,'quantity','')}, priority={getattr(up,'priority_preserved','')}), "
          f"committed={obs['committed_up']}")
    pr = obs["price"]
    print(f"  b. amend PRICE -> 72:  {type(pr).__name__}(price={getattr(pr,'limit_price','')})")
    odd = obs["odd"]
    print(f"  c. amend DOWN -> 50:   {type(odd).__name__}"
          f"({getattr(odd,'rule',None) and odd.rule.name})")
    dn = obs["down"]
    print(f"  d. amend DOWN -> 500:  {type(dn).__name__}"
          f"(qty={getattr(dn,'quantity','')}, priority={getattr(dn,'priority_preserved','')})")
    try:
        test_j27_amend()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
