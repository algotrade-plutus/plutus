"""F2 -- the indeterminate rate per (data resolution x cause), as a test.

**Superseded by E1** (the population fill-divergence experiment,
``docs/reference/EXPERIMENT-E1-FILL-DIVERGENCE.md``); kept and reconciled to the
O/H/L-wired daily adapter (2026-08-30) so it stays green and honest. The same
population of HSX instrument-days is run under ``hard`` at BAR resolution and the
``book_walk`` policy at TICK, against one identical probe, and each run's
``indeterminate_report()`` is read back. What this test now guards is the
*classification* of the ignorance -- which is robust -- not its magnitude, which
the OHLC wiring inverted:

* **BAR** (now that ``quote_max`` / ``quote_min`` serve the day's high/low) is
  MOSTLY DECIDABLE. Its residual indeterminacy is entirely the resolution-limit
  cause ``FILL_UNOBSERVABLE_AT_RESOLUTION`` -- the touched-at-limit case a daily
  bar cannot decide even with full OHLC -- and the former ``low`` data-ceiling
  cause is gone (the served low decides it). The close-only 100% was an adapter
  artifact, since removed; this is the honest floor.
* **TICK** carries **zero** of that resolution-limit cause (the touch is
  decidable at tick), and what remains is entirely the *data ceiling*
  (``BOOK_SIZE`` / ``VOLUME``: the sized tape this corpus lacks). Here it is now
  *higher* than the bar, because this tick extract is missing the sized prints --
  so refining bar->tick raises the rate while shifting its cause.

So the two resolutions carry different KINDS of ignorance -- bar = resolution
limit, tick = data ceiling -- and the KIND, not the magnitude, is the finding.

This runs the measurement on a small deterministic slice for speed; the full
population and the figure come from ``measurements/indeterminate_rate.py``. It
gates on BOTH corpora being present and skips cleanly otherwise.

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

    # (1) At BAR, with the day's high/low now served, the bar is MOSTLY DECIDABLE
    # and its residual indeterminacy is ENTIRELY the resolution-limit touch: the
    # only cause left is FILL_UNOBSERVABLE, the former `low` data-ceiling cause is
    # gone (the served low decides it), and the rate has collapsed off its old
    # close-only 100%. This is the OHLC fix, reconciled.
    assert float(bar.rate) < 0.5, (float(bar.rate), dict(bar.by_cause))
    assert set(bar.by_cause) == {_FILL_UNOBSERVABLE}, dict(bar.by_cause)
    assert bar.data_ceiling_share == 0, dict(bar.by_cause)
    assert float(bar.resolution_limit_share) == pytest.approx(float(bar.rate))

    # (2) That resolution-limit cause is STRUCTURALLY ABSENT at tick -- both queue
    # arms. A tick can decide the touch, so the book-walk never names it.
    assert tick_opt.by_cause.get(_FILL_UNOBSERVABLE, 0) == 0
    assert tick_con.by_cause.get(_FILL_UNOBSERVABLE, 0) == 0
    assert tick_opt.resolution_limit_share == 0
    assert tick_con.resolution_limit_share == 0

    # (3) The KIND of ignorance, not its magnitude, separates the resolutions. The
    # bar is entirely resolution-limit, the tick entirely data-ceiling. With full
    # OHLC the bar is now MORE decidable than this sized-tape-poor tick extract, so
    # the bar rate is BELOW the tick's -- the inverse of the close-only era.
    assert bar.data_ceiling_share == 0 and tick_opt.resolution_limit_share == 0
    assert float(bar.rate) < float(tick_opt.rate), (float(bar.rate), float(tick_opt.rate))

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
