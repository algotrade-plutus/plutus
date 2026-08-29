"""Regenerate the in-repo strategy-suite fixtures (Workstream W7).

WHAT THIS IS
    The Sx strategy suite (``strategies/test_s1..s9``) is a *fidelity* suite: it
    runs real, documented trading strategies against Plutus on **real Vietnamese
    market data** and asserts that documented market mechanics emerge (margin
    calls, forced liquidation, T+2 throttles, auction crosses, maker fills, the
    queue-assumption spread). Historically that data lived OUTSIDE the repo, on
    the author's machine:

        * S1-S7  read the daily Parquet corpus  ``hermes-parquet``
                 (via ``strategies/_harness.py`` -> ``DataHubSource``)
        * S4     additionally reads ``quote_open`` (auction crosses)
        * S8/S9  read the intraday dev extract   ``hermes-dev-extract``
                 (via ``strategies/_intraday_mm.py`` -> ``BookSessionSource``:
                  a ``DataHubSource`` price/band layer + a ``DepthSource`` book
                  + a ``TapeSource`` sized tape)

    So a fresh ``clone -> pip install -> pytest strategies/`` skipped everything.
    This script curates the *minimal* rows those reads actually touch into two
    in-repo mini-mirrors, ``fixtures/parquet`` and ``fixtures/extract``, that the
    suites now fall back to when ``PLUTUS_DATA_ROOT`` / ``PLUTUS_DEPTH_ROOT`` are
    unset. The full-corpus path is unchanged: set those env vars and the suites
    read the real roots exactly as before.

EXACTLY WHAT EACH TEST READS (the audit this curation is derived from)
    S1  VN30F2210 daily closes/bands, 2022-08-19 .. 2022-10-19   (HNXDS)
    S2  DIG       daily closes/bands, 2022-09-05 .. 2022-11-15   (HSX; incl. the
                  Oct 21-26 limit-down waterfall the forced sale is blocked by)
    S3  HPG,SSI,MBB + VN30F2212,      2022-11-08 .. 2022-11-18
    S4  FPT (+ quote_open),           2022-11-08 .. 2022-11-18   (auction crosses)
    S5  FPT,                          2022-09-06 .. 2022-11-15
    S6  VN30F2210,                    2022-10-03 .. 2022-10-12   (subset of S1)
    S7  = S1 (VN30F2210) under three fill policies
    S8  FPT sized tape + book,        2022-11-09  (local_quote_*), and the VN30F
        variant: VN30F2504 book+tape, 2025-04-08  (quote_*)
    S9  = S8's FPT maker (2022-11-09) under three queue assumptions

    The union of those reads is the seven daily instruments below over their own
    windows, plus two intraday instrument-days. The daily Parquet slice is
    padded a few days each side purely as insurance; the feeds only ever read
    ``[START, END)`` so the pad never changes a result.

WHAT WAS DOWN-SAMPLED / REDUCED
    * The daily Parquet corpus is filtered to the 7 instruments above over their
      test windows (out of ~1,700 instruments x 20+ years). Every daily row a
      test touches is kept verbatim -- no down-sampling of rows within a window.
    * The dev extract's book/tape tables carry FPT/HPG/HTV (and VN30F2504) across
      Oct-Nov 2022 (and Apr 2025). They are filtered to the *single* instrument-
      day each test uses: FPT 2022-11-09 (local_quote_*) and VN30F2504
      2025-04-08 (quote_*). Book/tape reconstruction is day-scoped (a cumulative
      total does not cross the close), so a one-day slice reconstructs
      bit-identically to the full extract -- no fidelity is lost.

HOW TO REGENERATE
    Point at the real roots (or rely on the defaults below) and run with the
    repo venv:

        PLUTUS_DATA_ROOT=/path/to/hermes-parquet \
        PLUTUS_DEPTH_ROOT=/path/to/hermes-dev-extract \
        .venv/bin/python strategies/fixtures/regenerate.py

    It rewrites ``fixtures/parquet`` and ``fixtures/extract`` in place and prints
    a manifest (rows + bytes per file). Column types are preserved verbatim
    (``COPY ... (FORMAT PARQUET)`` over ``SELECT *``): the tape's price stays
    ``DECIMAL(20,6)`` and never round-trips through float.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent

# Source roots: the real corpora (env-overridable so this runs on any machine
# that has them). These are the author-machine defaults.
SRC_PARQUET = Path(os.environ.get(
    "PLUTUS_DATA_ROOT", "/Users/nadan/algotrade-research/dataset/hermes-parquet"))
SRC_EXTRACT = Path(os.environ.get(
    "PLUTUS_DEPTH_ROOT", "/Users/nadan/algotrade-research/dataset/hermes-dev-extract"))

DST_PARQUET = HERE / "parquet"
DST_EXTRACT = HERE / "extract"

# -- the daily Parquet slice (S1-S7) --------------------------------------
# Per-instrument windows, padded a few days each side (reads are bounded by the
# test's own [START, END), so the pad is pure insurance and changes nothing).
DAILY_WHERE = """
    (tickersymbol = 'VN30F2210'
        AND CAST(datetime AS DATE) BETWEEN DATE '2022-08-15' AND DATE '2022-10-22')
 OR (tickersymbol = 'DIG'
        AND CAST(datetime AS DATE) BETWEEN DATE '2022-09-01' AND DATE '2022-11-18')
 OR (tickersymbol IN ('HPG', 'SSI', 'MBB', 'VN30F2212')
        AND CAST(datetime AS DATE) BETWEEN DATE '2022-11-04' AND DATE '2022-11-21')
 OR (tickersymbol = 'FPT'
        AND CAST(datetime AS DATE) BETWEEN DATE '2022-09-02' AND DATE '2022-11-21')
"""
DAILY_TABLES = ["quote_close", "quote_ceil", "quote_floor", "quote_reference",
                "quote_dailyvolume", "quote_open"]
DAILY_TICKERS = ("VN30F2210", "DIG", "HPG", "SSI", "MBB", "VN30F2212", "FPT")

# -- the intraday extract slice (S8/S9) -----------------------------------
# The composite book-walk source reads: book (bid/ask price+size change streams),
# the reconstructed sized tape (matched price + cumulative total), and -- for the
# VN30F variant only -- the daily price/band layer from the SAME extract root.
FPT_DAY = "2022-11-09"           # S8/S9 FPT maker  (local_quote_* prefix)
VN30F_DAY = "2025-04-08"         # S8 VN30F variant (quote_* prefix)

LOCAL_BOOK_TAPE = ["local_quote_bidprice", "local_quote_askprice",
                   "local_quote_bidsize", "local_quote_asksize",
                   "local_quote_matched", "local_quote_total"]
QUOTE_BOOK_TAPE = ["quote_bidprice", "quote_askprice", "quote_bidsize",
                   "quote_asksize", "quote_matched", "quote_total"]
# Daily price/band tables the VN30F variant's price source reads from the extract.
QUOTE_DAILY = ["quote_close", "quote_ceil", "quote_floor", "quote_reference",
               "quote_dailyvolume"]


def _copy(conn, src_file: Path, dst_file: Path, where: str) -> None:
    """Copy the rows matching ``where`` from ``src_file`` to ``dst_file``,
    preserving column types verbatim. Skips silently if the source is absent."""
    if not src_file.exists():
        print(f"  SKIP  {src_file.name:28} (absent in source root)")
        return
    conn.execute(
        f"COPY (SELECT * FROM read_parquet('{src_file}') WHERE {where}) "
        f"TO '{dst_file}' (FORMAT PARQUET)")
    rows = conn.execute(f"SELECT count(*) FROM read_parquet('{dst_file}')").fetchone()[0]
    size = dst_file.stat().st_size
    print(f"  {dst_file.name:28} rows={rows:>7}  bytes={size:>8,}")


def main() -> None:
    conn = duckdb.connect()
    DST_PARQUET.mkdir(parents=True, exist_ok=True)
    DST_EXTRACT.mkdir(parents=True, exist_ok=True)

    print(f"daily Parquet slice  {SRC_PARQUET}  ->  {DST_PARQUET}")
    for tbl in DAILY_TABLES:
        _copy(conn, SRC_PARQUET / f"{tbl}.parquet",
              DST_PARQUET / f"{tbl}.parquet", DAILY_WHERE)
    # The ticker master (required by DataHubConfig; used to type the stocks).
    _copy(conn, SRC_PARQUET / "quote_ticker.parquet",
          DST_PARQUET / "quote_ticker.parquet",
          "tickersymbol IN " + str(DAILY_TICKERS))

    print(f"\nintraday extract slice  {SRC_EXTRACT}  ->  {DST_EXTRACT}")
    fpt = f"tickersymbol = 'FPT' AND CAST(datetime AS DATE) = DATE '{FPT_DAY}'"
    for tbl in LOCAL_BOOK_TAPE:
        _copy(conn, SRC_EXTRACT / f"{tbl}.parquet",
              DST_EXTRACT / f"{tbl}.parquet", fpt)
    vn = f"tickersymbol = 'VN30F2504' AND CAST(datetime AS DATE) = DATE '{VN30F_DAY}'"
    for tbl in QUOTE_BOOK_TAPE + QUOTE_DAILY:
        _copy(conn, SRC_EXTRACT / f"{tbl}.parquet",
              DST_EXTRACT / f"{tbl}.parquet", vn)
    # The ticker master for the extract root (required by DataHubConfig; the
    # VN30F future itself resolves by prefix so this only has to exist).
    _copy(conn, SRC_EXTRACT / "quote_ticker.parquet",
          DST_EXTRACT / "quote_ticker.parquet",
          "tickersymbol IN ('VN30F2504', 'FPT')")

    total = sum(p.stat().st_size for p in
                list(DST_PARQUET.glob("*.parquet")) + list(DST_EXTRACT.glob("*.parquet")))
    print(f"\nTOTAL fixture size: {total:,} bytes ({total / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
