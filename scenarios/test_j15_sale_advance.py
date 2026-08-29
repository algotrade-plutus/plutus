"""J15 — Sell and redeploy on ứng trước tiền bán (the sale advance).

Scenario **J15** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.

MECHANISM
    A filled sale on day T creates a receivable that does not settle until
    T+2. The sale-advance product credits that receivable to buying power
    immediately (charging daily interest, recovered out of the settlement).
    So with the advance you can redeploy sale proceeds the same day; without
    it, the proceeds are unsettled cash and a same-day rebuy is refused.

POLICY (oracle — SCENARIO-CATALOGUE.md J15)
    * The product is statutory and licensable — Luật Chứng khoán 54/2019/QH14
      Điều 86(1)(b), word-for-word (high). The PRICE and CAP are broker
      commercial terms (self-priced, no statutory cap; structure high, numeric
      range not sourced).
    * Day trading (T+0) is legally provided for but never operational (no VSDC
      SBL) — TT 120/2020 Điều 10 (high). The advance is the real "lướt T0",
      and it costs the advance fee.

SETUP — FPT: buy 1,000 on 2022-11-09 with just enough cash; it settles
2022-11-11; sell it that day (proceeds unsettled until 11-15); then try to
rebuy 800 the same day. The rebuy needs the sale proceeds — which only the
advance makes available.

EXPECTED — Tier 2
    * With the advance ENABLED: the same-day rebuy is Accepted.
    * With the advance DISABLED: the same-day rebuy is Rejected (the proceeds
      have not settled and the settled cash is spent).

RUN
    python scenarios/test_j15_sale_advance.py
    pytest scenarios/test_j15_sale_advance.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted, Rejected  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

TICKER = "FPT"
BUY_DAY = datetime(2022, 11, 9, 13, 0)
SETTLE_DAY = datetime(2022, 11, 11, 13, 0)   # T+2: buy settles, shares sellable
SELL_FILL = datetime(2022, 11, 11, 14, 0)    # advance to fill the sale


def _config(advance_enabled: bool) -> dict:
    cfg = {
        "period": {"start": "2022-11-09", "end": "2022-11-15"},
        "resolution": "1d",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 76_000_000, "account_no": "SEC-J15"}},
    }
    if advance_enabled:
        # The sale advance is configured inside the broker_profile block.
        cfg["broker_profile"] = {
            "advance_sale_proceeds": {"enabled": True, "daily_rate": "0.0003"},
        }
    return cfg


def _rebuy(advance_enabled: bool):
    """Buy, hold to settlement, sell, then try to rebuy the same day off the
    (unsettled) proceeds. Return the rebuy verdict."""
    session = build_session(_config(advance_enabled))
    session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1000,
                         order_type=OrderType.LIMIT, limit_price=Decimal("74.0")))
    session.advance_to(BUY_DAY)      # buy fills
    session.advance_to(SETTLE_DAY)   # buy settles (T+2); shares now sellable
    session.submit(Order(ticker=TICKER, side=Side.SELL, quantity=1000,
                         order_type=OrderType.LIMIT, limit_price=Decimal("72.8")))
    session.advance_to(SELL_FILL)    # sale fills -> proceeds; advance credits if enabled
    return session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=800,
                                order_type=OrderType.LIMIT, limit_price=Decimal("72.8")))


def run_j15() -> dict:
    return {"with_advance": _rebuy(True), "without_advance": _rebuy(False)}


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j15_sale_advance():
    obs = run_j15()

    # With the advance, the same-day rebuy off unsettled proceeds is accepted.
    assert isinstance(obs["with_advance"], Accepted), obs["with_advance"]

    # Without it, the proceeds have not settled and settled cash is spent —
    # the same rebuy is refused.
    assert isinstance(obs["without_advance"], Rejected), obs["without_advance"]


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j15()
    for label, v in obs.items():
        rule = getattr(v, "rule", None)
        print(f"  rebuy {label:16}: {type(v).__name__}{'(' + rule.name + ')' if rule else ''}")
    try:
        test_j15_sale_advance()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
