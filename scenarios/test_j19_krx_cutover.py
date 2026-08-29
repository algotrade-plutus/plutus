"""J19 — Straddle the KRX cutover (2025-05-05): a different margin MODEL each side.

Scenario **J19** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
The same futures position is margined by two different MECHANISMS depending on
the date: the pre-KRX ``MR = IM + VM`` before 2025-05-05, and KRX's post-trade
COMS scenario calculation from the cutover.

MECHANISM — the margin MODEL is a dated rule, resolved at the instant. The
rulebook returns the pre-KRX mechanism before the cutover; from 2025-05-05 the
post-trade COMS formula **could not be obtained**, so the rulebook **raises**
rather than silently returning the pre-KRX shape. That refusal IS the fidelity:
an unsourced post-KRX model says so instead of pretending to be its predecessor.

POLICY (oracle — SCENARIO-CATALOGUE.md J19)
    * Pre-KRX (2017-05-01 → 2025-05-04): one layer, MR = IM + VM, VM loss-only
      — VSDC "Thông tin về ký quỹ"; QĐ 61 (high).
    * Post-KRX (2025-05-05 →): a scenario grid, MR = Max(ΣPgm, 0),
      Pgm = Max(Rm+Sm+Dm, MM) — QĐ 26, Phụ lục 2. The COMS calculation that
      produces the grid is UNSOURCED; the model raises rather than computes.
    * "Any blanket claim that nothing in this domain changed at KRX is false."

EXPECTED — Tier 2
    * A pre-KRX date resolves the margin model to the pre-KRX mechanism.
    * A post-KRX date RAISES — the post-KRX model is unsourced and says so,
      rather than fabricating a number from the old mechanism.
    * The two dates are in different rule editions (pre_krx vs post_krx).

RUN
    python scenarios/test_j19_krx_cutover.py
    pytest scenarios/test_j19_krx_cutover.py -v
"""
from __future__ import annotations

from datetime import datetime

import pytest

from plutus.market.session.rulebook import Rulebook, UnresolvedRule

PRE_KRX = datetime(2022, 11, 9, 10, 0)    # in-corpus, MR = IM + VM
POST_KRX = datetime(2025, 5, 5, 10, 0)    # the cutover day


def run_j19():
    book = Rulebook()

    pre_model = book.at(PRE_KRX).margin_model()

    post_raised = False
    try:
        book.at(POST_KRX).margin_model()
    except UnresolvedRule:
        post_raised = True

    return {
        "pre_model": pre_model,
        "post_raised": post_raised,
        "pre_edition": book.edition_at(PRE_KRX).value,
        "post_edition": book.edition_at(POST_KRX).value,
    }


def test_j19_krx_cutover():
    obs = run_j19()

    # Pre-KRX: the margin mechanism resolves (the IM + VM shape).
    assert obs["pre_model"] == "pre_margin", obs["pre_model"]

    # Post-KRX: the model is UNSOURCED and raises, rather than fabricating a
    # number from the pre-KRX mechanism.
    assert obs["post_raised"] is True, obs

    # The two dates sit in different rule editions.
    assert obs["pre_edition"] != obs["post_edition"], obs


if __name__ == "__main__":
    obs = run_j19()
    print("J19 — KRX cutover margin models (2025-05-05)")
    print(f"  pre-KRX  (2022-11-09): margin_model = {obs['pre_model']!r}  "
          f"[{obs['pre_edition']}]")
    print(f"  post-KRX (2025-05-05): margin_model raises UnresolvedRule = "
          f"{obs['post_raised']}  [{obs['post_edition']}]")
    print("  -> the model is dated, and the post-KRX side says 'unsourced' "
          "rather than pretending to be pre-KRX")
    try:
        test_j19_krx_cutover()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
