"""S6 — A VN30F strategy that straddles the KRX cutover and respects it.

Strategy **S6** of ``docs/reference/STRATEGY-BOARD.md``, written as a user writes
it. The same futures book, two regimes. Before **2025-05-05** Vietnam margins a
derivatives account ``MR = IM + VM``; from the KRX cutover the post-trade COMS
scenario calculation applies — and that model **could not be sourced**, so the
rulebook **raises** rather than pretend the old shape still holds. A regime-aware
strategy must not trade a market it cannot margin. S6 is that strategy: it runs
live before the cutover, and **refuses to size a position after it**, because the
exchange tells it — honestly — that the margin rule has changed and the new one
is unknown.

WHY THIS IS A FIDELITY TEST
    The failure mode a naive backtest hides is *silent continuation*: applying
    2022's margin mechanism to a 2025 position, completing the run, and reporting
    a number computed on a rule that no longer exists. The dated rulebook makes
    that impossible — ``margin_model()`` resolves pre-KRX and raises post-KRX —
    and S6 shows a strategy consuming that honesty: it stops rather than trade
    blind. "Any blanket claim that nothing changed at KRX is false."

DATA NOTE (declared, not worked around)
    The corpus ends **2022-12-30**; there is **no data past the cutover**. So the
    pre-KRX side is run **live** against real 2022 prices, and the post-KRX side
    is asserted at the **rulebook / edition level** — never with fabricated
    post-cutover prices. This is the honest shape the design fixed for S6.

MECHANISM / POLICY (oracle — SCENARIO-CATALOGUE.md, folded scenarios)
    * Pre-KRX ``MR = IM + VM`` (VSDC; QĐ 61) resolves; post-KRX the COMS grid
      (QĐ 26 Phụ lục 2) is UNSOURCED and the model raises (J18/J19).
    * The two dates sit in different rule editions (pre_krx / post_krx) — the
      dated rulebook, not a config-at-load singleton (J19).

SETUP — a live VN30F2210 long in Oct 2022 (pre-KRX), plus a regime check the
    strategy runs at 2022-11-09 (pre) and 2025-05-05 (the cutover).

EXPECTED — Tier 2
    * Live pre-KRX: the position trades and is margined — ``margin_model`` is
      ``pre_margin`` and ``session.margin()`` returns a real requirement.
    * The regime guard: the strategy *can* margin pre-KRX and *cannot* post-KRX
      (``margin_model`` raises) — so it refuses to trade the post-KRX regime.
    * The two dates are in different editions (pre_krx ≠ post_krx).

RUN
    .venv/bin/python strategies/test_s6_krx_regime.py
    .venv/bin/python -m pytest strategies/test_s6_krx_regime.py -v
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.session.rulebook import Rulebook, UnresolvedRule
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

TICKER = "VN30F2210"
PRE_KRX = datetime(2022, 11, 9, 10, 0)     # in-corpus, MR = IM + VM
POST_KRX = datetime(2025, 5, 5, 10, 0)     # the cutover day (no data)

CONFIG = {
    "period": {"start": "2022-10-03", "end": "2022-10-12"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HNXDS"]},
    "accounts": {"derivatives": {"initial_deposit": 40_000_000,
                                 "account_no": "DER-S6"}},
}


class RegimeAwareFutures:
    """Trades VN30F, but only in a regime whose margin model it can source."""

    name = "regime-aware VN30F"

    def can_margin_at(self, rulebook: Rulebook, ts: datetime) -> bool:
        """Whether a position can be safely margined at ``ts``. Refuses when the
        margin model is unsourced — the strategy will not size blind."""
        try:
            rulebook.at(ts).margin_model()
            return True
        except UnresolvedRule:
            return False


def run_s6():
    rulebook = Rulebook()
    strategy = RegimeAwareFutures()

    # The regime guard, at both edges of the cutover.
    can_pre = strategy.can_margin_at(rulebook, PRE_KRX)
    can_post = strategy.can_margin_at(rulebook, POST_KRX)

    pre_model = rulebook.at(PRE_KRX).margin_model()
    post_raises = False
    try:
        rulebook.at(POST_KRX).margin_model()
    except UnresolvedRule:
        post_raises = True

    pre_edition = rulebook.edition_at(PRE_KRX).value
    post_edition = rulebook.edition_at(POST_KRX).value

    # Live pre-KRX: because it CAN margin the pre-KRX regime, it trades — a real
    # VN30F long against real Oct-2022 prices, margined MR = IM + VM.
    session = build_session(CONFIG)
    filled = False
    margined = None
    if can_pre:
        session.advance_to(datetime(2022, 10, 3, 11, 0))
        v = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1,
                                 order_type=OrderType.LIMIT,
                                 limit_price=Decimal("1110")))
        session.advance_to(datetime(2022, 10, 3, 13, 0))
        pos = session.positions().get(TICKER)
        filled = bool(pos and pos.net_quantity != 0)
        margined = session.margin()          # the pre-KRX model, live

    return {"can_pre": can_pre, "can_post": can_post, "pre_model": pre_model,
            "post_raises": post_raises, "pre_edition": pre_edition,
            "post_edition": post_edition, "filled": filled, "margined": margined,
            "session": session}


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_s6_krx_regime():
    obs = run_s6()

    # Live pre-KRX: the strategy could margin the regime, so it traded, and the
    # position is margined under the pre-KRX model.
    assert obs["can_pre"] is True, "the strategy could not margin the pre-KRX regime"
    assert obs["filled"], "the live pre-KRX position never opened"
    assert obs["pre_model"] == "pre_margin", obs["pre_model"]
    assert obs["margined"] is not None and obs["margined"].initial_margin > 0, \
        obs["margined"]

    # The regime guard: post-KRX the margin model is UNSOURCED and raises, so the
    # strategy refuses to trade blind — it does not silently reuse 2022's shape.
    assert obs["post_raises"] is True, "post-KRX margin model did not raise"
    assert obs["can_post"] is False, "the strategy would have traded post-KRX blind"

    # The two dates are in different rule editions — the change is dated, not global.
    assert obs["pre_edition"] != obs["post_edition"], \
        (obs["pre_edition"], obs["post_edition"])


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_s6()
    print("S6 — Regime-aware VN30F across the KRX cutover (2025-05-05)")
    print(f"  pre-KRX  [{obs['pre_edition']}]: can_margin={obs['can_pre']}  "
          f"model={obs['pre_model']!r}  live position opened={obs['filled']}  "
          f"IM={obs['margined'].initial_margin if obs['margined'] else None:,}")
    print(f"  post-KRX [{obs['post_edition']}]: can_margin={obs['can_post']}  "
          f"model=RAISES UnresolvedRule ({obs['post_raises']})  -> strategy refuses to trade")
    print("  -> the same book, two regimes: the strategy trades what it can margin "
          "and stops where the rule is unknown")
    try:
        test_s6_krx_regime()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
