"""J12 — MOK vs MAK on the same signal (HNX).

Scenario **J12** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.

MECHANISM — both are market orders, continuous-only, neither rests:
    * MOK (fill-or-kill): cancels entirely unless fillable in FULL.
    * MAK (immediate-or-cancel): keeps whatever fills, kills the remainder.
    The difference is "the whole block or nothing" vs "whatever is there". A
    fill-or-kill sizing strategy that silently takes MAK-style partials is the
    error J12 exists to catch.

POLICY (oracle — SCENARIO-CATALOGUE.md J12)
    * MOK/MAK semantics — ASEANSC HNX §2.3; MBS VN30F §3.2 (broker rule
      sheets: high confidence, secondary citation) · HNX + HNXDS only.
    * Legal on HNX: continuous LO, MTL, MOK, MAK — high. HSX has never
      accepted MOK/MAK, so J12 MUST run on HNX/HNXDS.

DECLARED DEVIATIONS (from the catalogue — not glossed)
    * Synchronous submit with no matching engine: an MOK is decided at the
      first interval that evaluates it, not at entry.
    * The no-opposite-limit-order cancellation (ExpiryTrigger.NO_OPPOSITE_
      ORDER) is not raised on the default daily path — unmodelled.

SETUP — SHS (HNX), 2022-06-01: a soft fill policy with a tiny participation
cap (0.01% of the day's 8.66M-share volume ≈ a few hundred shares) makes a
5,000-share order unfillable in full, which is exactly what separates MOK from
MAK.

EXPECTED — Tier 2
    * MOK 5,000: killed — NO fill (not fillable in full).
    * MAK 5,000: partially filled (the cap) with the remainder killed.

RUN
    python scenarios/test_j12_mok_vs_mak.py
    pytest scenarios/test_j12_mok_vs_mak.py -v
"""
from __future__ import annotations

from datetime import datetime

import pytest

from plutus.market.session import ExchangeSession, Accepted, Rejected  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

CONFIG = {
    "period": {"start": "2022-06-01", "end": "2022-06-02"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HNX"]},
    "accounts": {"securities": {"initial_cash": 500_000_000, "account_no": "SEC-J12"}},
    "fill_policy": {"kind": "soft", "max_participation": 0.0001},
}

TICKER = "SHS"
QTY = 5000
AFTERNOON = datetime(2022, 6, 1, 13, 0)


def run_j12() -> dict:
    session = build_session(CONFIG)
    mok = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=QTY,
                               order_type=OrderType.MARKET_FILL_OR_KILL))
    mak = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=QTY,
                               order_type=OrderType.MARKET_IMMEDIATE_OR_CANCEL))
    events = session.advance_to(AFTERNOON)
    return {"mok": mok, "mak": mak, "events": events}


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def _for(events, order_id):
    return [e for e in events if e.order_id == order_id]


def _filled_qty(events, order_id):
    return sum(e.quantity or 0 for e in _for(events, order_id)
               if _kind(e) in ("filled", "partially_filled"))


def _expiry_reason(events, order_id):
    for e in _for(events, order_id):
        if _kind(e) == "expired":
            detail = e.detail or {}
            return detail.get("trigger") or detail.get("reason")
    return None


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j12_mok_vs_mak():
    obs = run_j12()
    assert isinstance(obs["mok"], Accepted), obs["mok"]
    assert isinstance(obs["mak"], Accepted), obs["mak"]

    # MOK — fill-or-kill: nothing fills, killed as not-fillable-in-full.
    mok_filled = _filled_qty(obs["events"], obs["mok"].order_id)
    assert mok_filled == 0, mok_filled
    assert _expiry_reason(obs["events"], obs["mok"].order_id) == "not_fillable_in_full"

    # MAK — immediate-or-cancel: partial fill, remainder killed at once.
    mak_filled = _filled_qty(obs["events"], obs["mak"].order_id)
    assert 0 < mak_filled < QTY, mak_filled
    assert _expiry_reason(obs["events"], obs["mak"].order_id) == "immediate_remainder"

    # The whole point: same signal, MOK takes nothing, MAK takes a partial.
    assert mok_filled != mak_filled


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j12()
    print("J12 — MOK vs MAK (SHS, HNX, 2022-06-01)")
    print(f"  MOK submit: {type(obs['mok']).__name__}")
    print(f"  MAK submit: {type(obs['mak']).__name__}")
    for label, res in (("MOK", obs["mok"]), ("MAK", obs["mak"])):
        oid = getattr(res, "order_id", None)
        evs = _for(obs["events"], oid)
        print(f"  {label} {oid}: filled={_filled_qty(obs['events'], oid)}  events={[(_kind(e), e.quantity, (e.detail or {}).get('reason') or (e.detail or {}).get('trigger')) for e in evs]}")
