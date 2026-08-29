"""S7 — One strategy, three fill policies: how much of the result is assumption.

Strategy **S7** of ``docs/reference/STRATEGY-BOARD.md``. Not a market stress — a
**methodological** one, and the whole value proposition of a high-fidelity sim
made measurable. We take S1 (the VN30F mean-reversion) **unchanged** and run it
under the three bar-resolution fill policies. The strategy, the data, the signal
and the sizing are identical; only the fill *assumption* changes. What comes out
is not one number but a spread — and the spread is the finding.

WHY IT MATTERS
    The fill policy is the largest single assumption in any bar backtest, and it
    is **not a rule** (A34/A35 — our modelling choices, no Vietnamese document
    states a fill probability or caps a print). ``soft`` fills optimistically on
    touch; ``hard`` fills only what it can prove traded through, and **never
    fills a market order**; ``probabilistic`` splits the difference on a seed. A
    strategy built on market orders therefore reports a *completely different*
    history depending on which one you believed — here, "blew up −76%" under the
    optimistic policy versus "never established a position" under the strict one.
    A backtest that quotes one policy and hides the spread is quoting an
    assumption as a result.

MECHANISM / POLICY (oracle — SCENARIO-CATALOGUE.md, folded scenarios)
    * The fill-policy spread is our choice, not a rule (J10/J20); the
      participation cap is a convention (J22). What a policy may NOT override —
      band, tick, lot, order-type legality — is decided before it runs.
    * The order-book queue policy (optimistic/conservative/probabilistic) is the
      *microstructure* counterpart of the same idea and is covered on the depth
      extract by J13/J21; S7 measures the session-level fill assumption.

SETUP — S1 unchanged (VN30F2210 mean-reversion, 40M deposit, Aug–Oct 2022) under
    fill policies {soft, hard, probabilistic}, participation cap 0.10.

EXPECTED — Tier 2
    * The three policies do NOT agree — the same strategy gives a different
      history under each (the spread is real).
    * Under ``soft`` the strategy trades and the margin story unfolds (fills > 0,
      a call is issued); under ``hard`` its market orders never fill, so nothing
      happens (fills == 0, no call) — the whole result was the fill assumption.
    * ``probabilistic`` is reproducible under a fixed seed.

RUN
    .venv/bin/python strategies/test_s7_fill_sensitivity.py
    .venv/bin/python -m pytest strategies/test_s7_fill_sensitivity.py -v
"""
from __future__ import annotations

import pytest

from _harness import build_session, data_available, CorpusFeed, run
from test_s1_vn30f_meanrev import (FrontMonthMeanReversion, TICKER, START, END,
                                   CONFIG as S1_CONFIG)


def _run_under(fill_policy: dict):
    cfg = {**S1_CONFIG, "fill_policy": fill_policy}
    session = build_session(cfg)
    feed = CorpusFeed()
    strategy = FrontMonthMeanReversion()
    ledger = run(strategy, session=session, feed=feed,
                 start=START, end=END, universe=[TICKER])
    ledger.strategy = strategy
    return ledger


def run_s7() -> dict:
    return {
        "soft": _run_under({"kind": "soft", "max_participation": 0.10}),
        "hard": _run_under({"kind": "hard", "max_participation": 0.10}),
        "probabilistic": _run_under({"kind": "probabilistic", "seed": 7,
                                     "max_participation": 0.10}),
        "probabilistic_again": _run_under({"kind": "probabilistic", "seed": 7,
                                           "max_participation": 0.10}),
    }


def _outcome(ledger) -> tuple:
    """A compact fingerprint of the run: (fills, calls, forced, end-equity)."""
    return (len(ledger.fills()), len(ledger.calls()), len(ledger.forced()),
            ledger.equity_curve[-1][1] if ledger.equity_curve else None)


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_s7_fill_sensitivity():
    r = run_s7()
    soft, hard, prob = r["soft"], r["hard"], r["probabilistic"]

    # The spread is the point: the same strategy does not give the same history
    # under the three policies.
    outcomes = {name: _outcome(r[name]) for name in ("soft", "hard", "probabilistic")}
    assert len(set(outcomes.values())) > 1, outcomes

    # Under the optimistic policy the strategy trades and the margin story runs...
    assert len(soft.fills()) > 0, "soft never traded"
    assert len(soft.calls()) > 0, "soft never reached a margin call"

    # ...under the strict policy its market orders never fill, so nothing at all
    # happens — the entire −76% history was the fill assumption (J10/J20).
    assert len(hard.fills()) == 0, "hard filled a market order (it should not)"
    assert len(hard.calls()) == 0, "hard produced a margin call with no fills"

    # Probabilistic is reproducible under a fixed seed.
    assert _outcome(r["probabilistic"]) == _outcome(r["probabilistic_again"]), \
        (_outcome(r["probabilistic"]), _outcome(r["probabilistic_again"]))


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    r = run_s7()
    print("S7 — One strategy (S1) under three fill policies")
    print(f"  {'policy':16} {'fills':>6} {'calls':>6} {'forced':>7} {'end-equity':>14}")
    for name in ("soft", "hard", "probabilistic"):
        f, c, fo, eq = _outcome(r[name])
        print(f"  {name:16} {f:>6} {c:>6} {fo:>7} {float(eq):>14,.0f}")
    print("  -> the same strategy, three different histories: the fill policy IS "
          "the result")
    try:
        test_s7_fill_sensitivity()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
