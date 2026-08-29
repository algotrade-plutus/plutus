"""J36 — The sized tape is complete: total deltas, not matchedvolume.

Scenario **J36** of the intraday extension, and the data-integrity guard the
whole maker fill rests on. The sized tape a maker fills against is reconstructed
from ``quote.total`` (the cumulative matched volume): its consecutive deltas are
the per-event traded volume, and they must sum to the day's actual volume. This
scenario pins that — and, in doing so, the finding that motivated the whole
reconstruction:

THE FINDING (measured, and the reason ``matchedvolume`` is not used). The
    obvious-looking table, ``quote.matchedvolume``, is **lossy**: on FPT
    2022-11-09 it omits match events entirely and understates others, summing to
    **402,300** shares against the day's true **697,700**. The authoritative
    volume is ``quote.total``, whose last intraday value equals
    ``quote.dailyvolume`` exactly. A maker fill built on ``matchedvolume`` would
    silently under-fill by ~40 %; built on ``total`` deltas it is complete.

SETUP — the exported FPT tape (``local_quote_matched`` + ``local_quote_total``),
    reconstructed by :class:`TapeSource`.

The lossy ``matchedvolume`` number (402,300) is stated here for the record, from
the manifest -- it is NOT re-measured, because the lossy table was deliberately
removed from the extract; the guard is that the ``total``-based reconstruction
lands on the day's real volume, which ``matchedvolume`` provably does not.

EXPECTED — Tier 2
    * The reconstructed per-event volumes sum to **697,700**, the day's measured
      ``dailyvolume`` (pinned, this is the measured tier).
    * Every event is **in-session** (08:00–15:30): the spurious ``00:00:00``
      daily-summary row that ``total`` carries is dropped, not counted.
    * Every per-event volume is **non-negative**: the intraday ``total`` is
      monotone once the summary row is removed.

RUN
    python scenarios/test_j36_tape_integrity.py
    pytest scenarios/test_j36_tape_integrity.py -v
"""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from plutus.market.adapters.tape import TapeSource

EXTRACT = Path("/Users/nadan/algotrade-research/dataset/hermes-dev-extract")
TICKER = "FPT"
DAY = date(2022, 11, 9)
DAILY_VOLUME = 697700          # == quote.dailyvolume (independent table)
MATCHEDVOLUME_SUM = 402300     # the lossy stream's daily sum, for contrast


def _tape_available() -> bool:
    return EXTRACT.is_dir() and (EXTRACT / "local_quote_total.parquet").exists()


def run_j36():
    src = TapeSource(str(EXTRACT), table_prefix="local_quote")
    tape = src.sized_tape(TICKER, DAY)
    return {"tape": tape, "volume": sum(e.volume for e in tape)}


@pytest.mark.skipif(not _tape_available(),
                    reason="sized tape (local_quote_total) not found")
def test_j36_tape_integrity():
    obs = run_j36()
    tape = obs["tape"]
    assert tape, "the reconstructed tape is empty"

    # Complete: the reconstructed volume equals the day's measured volume. (The
    # lossy matchedvolume would have summed to 402,300 -- documented, not
    # re-measured here, since that table was removed from the extract.)
    assert obs["volume"] == DAILY_VOLUME, obs["volume"]

    # In-session: the 00:00:00 daily-summary row is excluded.
    assert all(time(8, 0) <= e.ts.time() <= time(15, 30) for e in tape)

    # Monotone: every per-event volume is non-negative.
    assert all(e.volume >= 0 for e in tape)


if __name__ == "__main__":
    if not _tape_available():
        raise SystemExit("sized tape (local_quote_total) not found")
    obs = run_j36()
    print("J36 — The sized tape is complete (FPT, 2022-11-09)")
    print(f"  reconstructed volume (total deltas): {obs['volume']}")
    print(f"  published dailyvolume:               {DAILY_VOLUME}")
    print(f"  lossy matchedvolume sum (NOT used):  {MATCHEDVOLUME_SUM}")
    print(f"  events: {len(obs['tape'])}, all in-session and non-negative")
    try:
        test_j36_tape_integrity()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
