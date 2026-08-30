"""E1 -- population fill-policy divergence, pinned.

The measurement (``measurements/fill_divergence.py``) replaces the old
three-strategy return sweep. This test guards its two load-bearing properties on a
fast slice: the divergence is **non-uniform across order intents** (market orders
diverge ~always, deep passive limits ~never -- acceptance criterion #4 of
``EXPERIMENT-E1-FILL-DIVERGENCE.md``), and it reports **fills, never P&L**.

Gates on the daily Parquet corpus and skips cleanly otherwise.

RUN
    .venv/bin/python -m pytest strategies/test_e1_fill_divergence.py -v
    .venv/bin/python -m measurements.fill_divergence   # full population + figure
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from measurements.fill_divergence import (DEFAULT_ROOT, FillOutcome,
                                          measure_fill_divergence)


def _corpus() -> str:
    return os.environ.get("PLUTUS_DATA_ROOT", DEFAULT_ROOT)


def _ready() -> bool:
    return (Path(_corpus()) / "quote_close.parquet").exists()


@pytest.mark.skipif(not _ready(), reason="E1 needs the daily Parquet corpus")
def test_e1_divergence_is_non_uniform_by_intent_and_reports_no_pnl():
    r = measure_fill_divergence(_corpus(), max_tickers=5)

    # A real flow was evaluated and the policies genuinely diverge (not 0, not 1).
    assert r.questions > 1000
    assert 0 < float(r.agreement_rate) < 1

    div = {i: (1 - a.agreed / a.n) for i, a in r.by_intent.items() if a.n}

    # (4) Divergence is a function of the order mix -- market orders diverge far
    # more than deep passive limits. If it were uniform, the population or the
    # pricing would be wrong.
    assert div["market_buy"] > 0.5
    assert div["limit_sell_at_ceil"] < 0.25
    assert div["market_buy"] > div["limit_sell_at_ceil"] + 0.3

    # The strict policy abstains more than the lenient one -- INDETERMINATE is a
    # first-class column, and `hard` refuses the touch that `soft` fills.
    d = r.to_dict()
    sigs = d["signatures"]
    hard = next(s for s in sigs if s.startswith("hard"))
    soft = next(s for s in sigs if s.startswith("soft"))
    assert (d["by_policy"][hard]["indeterminate_rate"]
            > d["by_policy"][soft]["indeterminate_rate"])

    # Reports fills, not performance: no P&L / return / Sharpe in the *data*
    # (DivergenceReport's contract). The prose `finding` field is excluded -- it
    # legitimately says "reported as fills, never P&L".
    blob = str({k: v for k, v in d.items() if k != "finding"}).lower()
    for banned in ("return", "pnl", "p&l", "sharpe", "profit"):
        assert banned not in blob, banned
    # what it DOES report is quantity and outcomes.
    assert d["by_policy"][soft]["filled_quantity"] > 0
    assert FillOutcome.INDETERMINATE.value in d["by_policy"][hard]["outcomes"]
