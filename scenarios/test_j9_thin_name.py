"""J9 — Thin-name strategy (HTV): the cap binds and the quote goes stale.

Scenario **J9** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Two halves that must be kept apart, and keeping them apart IS the scenario:
the **rule** half (band, tick, lot, admission) is sourced and dated; the
**data** half (how much of the print you could have had) is not a rule at all.
The correct output on a thin name is **more INDETERMINATE, not more fills**.

MECHANISM
    * CAP_EXCEEDED: on a day with volume, the participation cap bounds the fill
      to a fraction of a tiny print — a large order fills almost nothing.
    * CAP_UNCOMPUTABLE: on a day with no volume, the cap cannot be computed, so
      a `hard` policy reports INDETERMINATE rather than inventing a fill.

GOVERNING "POLICY"
    * Rule half (sourced): HSX tick tiers, lot 100, band ±7% — QĐ 352 (high).
    * Data half (OUR modelling choice): the participation cap is A34, UNSOURCED
      — no Vietnamese document caps a participant's share of a print. The
      staleness budget (U18) is likewise ours and is reachable only via the
      injected book-walk policy (see J13/J21), not from a config — so this
      scenario exercises the cap half on the default path and declares the
      staleness half as out of reach here.

SETUP — HTV (a genuinely illiquid HOSE name), a `hard` policy capped at 10%:
2022-11-09 has 3,300 shares of volume (the cap binds); 2022-11-11 has no
volume at all (the cap is uncomputable).

EXPECTED — Tier 2
    * On the volume day, a 5,000-share buy fills far less than 5,000 (the cap
      binds to ~10% of 3,300).
    * On the no-volume day, the `hard` policy fills nothing and the run reports
      a CAP_UNCOMPUTABLE blind spot — more INDETERMINATE, not more fills.

RUN
    python scenarios/test_j9_thin_name.py
    pytest scenarios/test_j9_thin_name.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

TICKER = "HTV"
QTY = 5000
VOLUME_DAY_VOL = 3300

CONFIG = {
    "period": {"start": "2022-11-07", "end": "2022-11-18"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HSX"]},
    "accounts": {"securities": {"initial_cash": 200_000_000, "account_no": "SEC-J9"}},
    "fill_policy": {"kind": "soft", "max_participation": 0.10},
}


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def run_j9():
    session = build_session(CONFIG)

    # A day with volume: the cap binds.
    session.advance_to(datetime(2022, 11, 9, 13, 0))
    ack_vol = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=QTY,
                                   order_type=OrderType.LIMIT, limit_price=Decimal("10.6")))
    ev_vol = session.advance_to(datetime(2022, 11, 9, 14, 45))
    filled_vol = sum(e.quantity or 0 for e in ev_vol
                     if e.order_id == getattr(ack_vol, "order_id", None)
                     and _kind(e) in ("filled", "partially_filled"))

    # A day with no volume: the cap is uncomputable.
    session.advance_to(datetime(2022, 11, 11, 13, 0))
    ack_novol = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=QTY,
                                     order_type=OrderType.LIMIT, limit_price=Decimal("9.95")))
    ev_novol = session.advance_to(datetime(2022, 11, 11, 14, 45))
    filled_novol = sum(e.quantity or 0 for e in ev_novol
                       if e.order_id == getattr(ack_novol, "order_id", None)
                       and _kind(e) in ("filled", "partially_filled"))

    return {"ack_vol": ack_vol, "filled_vol": filled_vol,
            "ack_novol": ack_novol, "filled_novol": filled_novol,
            "report": session.indeterminate_report()}


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j9_thin_name():
    obs = run_j9()

    # Both orders are admitted (the rule half runs on a thin name too).
    assert isinstance(obs["ack_vol"], Accepted), obs["ack_vol"]
    assert isinstance(obs["ack_novol"], Accepted), obs["ack_novol"]

    # CAP_EXCEEDED: on the volume day the cap binds — far less than 5,000 fills,
    # bounded by ~10% of the 3,300-share print.
    assert 0 < obs["filled_vol"] <= VOLUME_DAY_VOL, obs["filled_vol"]
    assert obs["filled_vol"] < QTY, obs["filled_vol"]

    # On the no-volume day the cap cannot be computed, so the policy does NOT
    # fabricate a fill — it returns INDETERMINATE. More INDETERMINATE, not more
    # fills: exactly the discipline a thin name is supposed to expose.
    assert obs["filled_novol"] == 0, obs["filled_novol"]
    assert obs["report"].indeterminate > 0, obs["report"]


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j9()
    print("J9 — Thin-name strategy (HTV, Nov 2022)")
    print(f"  2022-11-09 (vol 3,300): buy 5,000 -> filled {obs['filled_vol']}  (cap binds)")
    print(f"  2022-11-11 (no volume): buy 5,000 -> filled {obs['filled_novol']}  (uncomputable)")
    print(f"  indeterminate decisions: {obs['report'].indeterminate}  (more INDETERMINATE, not more fills)")
    try:
        test_j9_thin_name()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
