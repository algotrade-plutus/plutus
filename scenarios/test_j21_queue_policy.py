"""J21 — One strategy under optimistic / conservative / probabilistic queues.

Scenario **J21** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Walk the SAME book with the SAME order under three queue policies and report
how much of the result is queue luck.

MECHANISM — the queue policy decides where in the resting queue at each level
our order is assumed to sit, and so how much of that level we get. Vietnam
matches price-then-time with no size priority, but WHERE our order sat in time
at a given price is not observable from a reconstructed book — so it is a
modelling choice, and swapping it moves the fill.

GOVERNING "POLICY" — OUR MODELLING CHOICE, not a market rule.
    * UNSOURCED: queue position is not recoverable from the corpus. Optimistic
      (front of queue), conservative (back), probabilistic (a seeded draw
      between) are ours. Price-then-time priority itself IS sourced —
      QĐ 352 Điều 7, 16 — but the time-rank of our own order is not.

DATA — the 3-level FPT ladder in the dev extract (`hermes-dev-extract`),
2022-11-09.

EXPECTED — Tier 2
    * The three queue policies do NOT agree on the fill for the same order —
      optimistic fills the most, conservative the least, probabilistic between.
    * Probabilistic is reproducible under a fixed seed.

RUN
    python scenarios/test_j21_queue_policy.py
    pytest scenarios/test_j21_queue_policy.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from plutus.market.adapters.depth import DepthSource
from plutus.market.session.book_walk import (
    walk_book, OptimisticQueue, ConservativeQueue, ProbabilisticQueue)
from plutus.core.order import Side

EXTRACT = Path("/Users/nadan/algotrade-research/dataset/hermes-dev-extract")
FPT_CLEAN = datetime(2022, 11, 9, 9, 16, 5, 290870)


def _depth_available() -> bool:
    return EXTRACT.is_dir() and any(EXTRACT.glob("local_quote_asksize*.parquet"))


def _filled_under(book, queue) -> int:
    walk = walk_book(book, side=Side.BUY, limit=Decimal("78.0"), quantity=50_000,
                     queue=queue, order_id="O-J21", max_staleness=None)
    return walk.filled_quantity


def run_j21():
    source = DepthSource(str(EXTRACT), table_prefix="local_quote")
    book = source.book_at("FPT", FPT_CLEAN)
    return {
        "optimistic": _filled_under(book, OptimisticQueue()),
        "conservative": _filled_under(book, ConservativeQueue()),
        "probabilistic": _filled_under(book, ProbabilisticQueue(seed=7)),
        "probabilistic_again": _filled_under(book, ProbabilisticQueue(seed=7)),
    }


@pytest.mark.skipif(not _depth_available(),
                    reason="order-book depth (dev extract) not found")
def test_j21_queue_policy():
    f = run_j21()

    # The queue policy moves the fill: not all three agree.
    assert len({f["optimistic"], f["conservative"], f["probabilistic"]}) > 1, f

    # Optimistic (front of queue) fills at least as much as conservative (back).
    assert f["optimistic"] >= f["conservative"], f

    # Probabilistic is reproducible under a fixed seed.
    assert f["probabilistic"] == f["probabilistic_again"], f


if __name__ == "__main__":
    if not _depth_available():
        raise SystemExit("order-book depth (dev extract) not found")
    f = run_j21()
    print("J21 — Queue-policy spread on the FPT ladder (2022-11-09)")
    for policy in ("optimistic", "conservative", "probabilistic"):
        print(f"  {policy:14} filled {f[policy]:>6} of 50,000")
    print(f"  probabilistic reproducible under seed 7: "
          f"{f['probabilistic'] == f['probabilistic_again']}")
    try:
        test_j21_queue_policy()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
