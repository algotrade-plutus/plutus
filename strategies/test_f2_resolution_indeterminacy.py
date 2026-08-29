"""F2 -- the indeterminate rate per (data resolution x cause), as a test.

The paper's third contribution (``measurements/indeterminate_rate.py``), pinned.
The same population of HSX instrument-days is run under the ``hard`` fill policy
at BAR resolution and the ``book_walk`` policy at TICK resolution, against one
identical probe, and each run's ``indeterminate_report()`` is read back. The
finding this test guards:

* **BAR** is dominated by the resolution-limit cause
  ``FILL_UNOBSERVABLE_AT_RESOLUTION`` -- the touched-at-limit case a daily bar
  cannot decide. It is the honest floor; only a finer resolution lowers it.
* **TICK** carries **zero** of that cause (the book-walk cannot emit it) -- the
  touch is decidable at tick -- and what remains is entirely the *data ceiling*
  (``BOOK_SIZE`` / ``VOLUME``: unsized levels, prices outside the displayed
  ladder, the sized tape this corpus lacks). Under the optimistic queue the tick
  rate falls below the bar's; under the conservative queue it stays high but is
  still 100% data-ceiling.

So refining the resolution does not remove the indeterminacy; it trades the
resolution-limit cause for the data-ceiling one. That is F2.

This runs the measurement on a small deterministic slice of the population for
speed; the full population and the figure come from
``measurements/indeterminate_rate.py`` (its ``main`` writes ``figures/``). It
gates on BOTH corpora being present -- the daily Parquet corpus and the
``local_quote`` tick extract -- and skips cleanly otherwise, the way the S8/S9
tick tests do.

RUN
    .venv/bin/python -m pytest strategies/test_f2_resolution_indeterminacy.py -v
    .venv/bin/python measurements/indeterminate_rate.py   # full population + figure
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from measurements.indeterminate_rate import (
    DEFAULT_BAR_ROOT, DEFAULT_TICK_ROOT, DataField, discover_population,
    measure_indeterminate_rate,
)

#: Per-ticker cap for the test slice: enough days across every ticker for a
#: stable contrast, few enough to stay quick. The figure uses the full set.
DAYS_PER_TICKER = 4

_FILL_UNOBSERVABLE = DataField.FILL_UNOBSERVABLE_AT_RESOLUTION.value


def _data_ready() -> bool:
    """Both corpora present: the daily bar Parquet and the local_quote book."""
    import os

    bar = Path(os.environ.get("PLUTUS_DATA_ROOT", DEFAULT_BAR_ROOT))
    tick = Path(os.environ.get("PLUTUS_DEPTH_ROOT", DEFAULT_TICK_ROOT))
    return ((bar / "quote_close.parquet").exists()
            and (tick / "local_quote_bidprice.parquet").exists())


def _slice() -> list:
    """A deterministic subset: the first ``DAYS_PER_TICKER`` days of each ticker."""
    per = defaultdict(int)
    out = []
    for ticker, day in discover_population(DEFAULT_BAR_ROOT, DEFAULT_TICK_ROOT):
        if per[ticker] < DAYS_PER_TICKER:
            out.append((ticker, day))
            per[ticker] += 1
    return out


@pytest.mark.skipif(not _data_ready(),
                    reason="F2 needs both the daily corpus and the local_quote "
                           "tick extract; set PLUTUS_DATA_ROOT / PLUTUS_DEPTH_ROOT")
def test_f2_resolution_indeterminacy():
    population = _slice()
    assert population, "no bar+tick instrument-days discovered"

    result = measure_indeterminate_rate(
        DEFAULT_BAR_ROOT, DEFAULT_TICK_ROOT,
        queues=("optimistic", "conservative"), population=population)

    bar = result.arm("BAR / hard")
    tick_opt = result.arm("TICK / book-walk (optimistic)")
    tick_con = result.arm("TICK / book-walk (conservative)")

    # Every arm actually evaluated fills, or the comparison is vacuous.
    for arm in (bar, tick_opt, tick_con):
        assert arm.evaluations > 0, arm.label

    # (1) The resolution-limit cause DOMINATES at bar -- it is the single largest
    # cause and a majority of all bar fill evaluations.
    assert bar.by_cause.get(_FILL_UNOBSERVABLE, 0) == max(bar.by_cause.values())
    assert bar.resolution_limit_share > 0.5, dict(bar.by_cause)

    # (2) That cause is STRUCTURALLY ABSENT at tick -- both queue arms. A tick
    # can decide the touch, so the book-walk never names it.
    assert tick_opt.by_cause.get(_FILL_UNOBSERVABLE, 0) == 0
    assert tick_con.by_cause.get(_FILL_UNOBSERVABLE, 0) == 0
    assert tick_opt.resolution_limit_share == 0
    assert tick_con.resolution_limit_share == 0

    # (3) The bar rate EXCEEDS the tick rate (optimistic queue -- the one that
    # decides the touch rather than assuming the queue away).
    assert bar.rate > tick_opt.rate, (float(bar.rate), float(tick_opt.rate))

    # (4) Whatever indeterminacy the tick DOES carry is entirely data-ceiling
    # (missing sizes/tape), and it is real (non-empty) -- the causes have shifted,
    # not vanished. Conservative names the fuller ceiling (book_size + volume).
    assert tick_opt.indeterminate > 0 and tick_opt.data_ceiling_share > 0
    assert tick_con.data_ceiling_share == pytest.approx(float(tick_con.rate))
    assert DataField.VOLUME.value in tick_con.by_cause
    assert DataField.BOOK_SIZE.value in tick_con.by_cause

    # Every tick cause is a data-ceiling field, never a resolution-limit one.
    for arm in (tick_opt, tick_con):
        for cause in arm.by_cause:
            assert cause != _FILL_UNOBSERVABLE


if __name__ == "__main__":
    if not _data_ready():
        raise SystemExit("F2 needs both the daily corpus and the tick extract")
    r = measure_indeterminate_rate(
        DEFAULT_BAR_ROOT, DEFAULT_TICK_ROOT, population=_slice())
    print("F2 -- indeterminate rate per (resolution x cause)  [test slice]")
    for a in r.arms:
        print(f"  {a.label:34} rate={float(a.rate):.1%}  "
              f"res-limit={float(a.resolution_limit_share):.0%}  "
              f"data-ceiling={float(a.data_ceiling_share):.0%}  {a.by_cause}")
