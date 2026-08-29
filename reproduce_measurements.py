#!/usr/bin/env python3
"""Regenerate every quantitative claim Plutus makes about itself.

Each measurement below backs a specific number in the README, a docstring, or
the paper. Nothing is hard-coded: if a figure changes, this script is what
tells us, and any documented number that this script cannot produce should be
deleted rather than defended.

Usage::

    python reproduce_measurements.py --data-root /path/to/hermes-parquet
    python reproduce_measurements.py --data-root ... --csv-root ... --raw-root ...
    python reproduce_measurements.py --data-root ... --json measurements.json

`--data-root` should point at the Parquet corpus. `--csv-root` and
`--raw-root` are optional; storage and speed comparisons are skipped when they
are absent, and the script says so rather than silently omitting them.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import duckdb
except ImportError:  # pragma: no cover - reported, not raised
    duckdb = None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _dir_bytes(path: Path, suffix: str) -> int:
    return sum(f.stat().st_size for f in path.glob(f"*{suffix}"))


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} TB"


def _time_query(conn, sql: str, repeats: int = 3) -> float:
    """Median wall-clock seconds over `repeats` runs."""
    timings = []
    for _ in range(repeats):
        start = time.perf_counter()
        conn.execute(sql).fetchall()
        timings.append(time.perf_counter() - start)
    return statistics.median(timings)


# --------------------------------------------------------------------------
# measurements
# --------------------------------------------------------------------------

def measure_test_suite(repo_root: Path) -> Dict[str, Any]:
    """Count collected tests. Backs the README test badge."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=600,
            env={"PYTHONPATH": str(repo_root / "src"), "PATH": "/usr/bin:/bin"},
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"error": f"could not collect tests: {exc}"}

    collected = None
    for line in proc.stdout.splitlines():
        if "test" in line and "collected" in line:
            for token in line.split():
                if token.isdigit():
                    collected = int(token)
                    break
    return {"collected": collected, "backs": "README test badge"}


def measure_storage(
    parquet_root: Path,
    csv_root: Optional[Path],
    raw_root: Optional[Path],
) -> Dict[str, Any]:
    """Corpus footprints and the Parquet reduction.

    Backs the README's dataset-size and 'smaller storage footprint' claims.
    Comparison is restricted to tables present in BOTH corpora, so the
    percentage reflects a like-for-like conversion rather than a difference in
    which tables each directory happens to hold.
    """
    out: Dict[str, Any] = {
        "parquet_root": str(parquet_root),
        "parquet_bytes": _dir_bytes(parquet_root, ".parquet"),
    }
    out["parquet_human"] = _fmt_bytes(out["parquet_bytes"])

    if raw_root and raw_root.exists():
        out["raw_csv_bytes"] = _dir_bytes(raw_root, ".csv")
        out["raw_csv_human"] = _fmt_bytes(out["raw_csv_bytes"])
        out["raw_csv_note"] = (
            "Full raw archive as distributed, including the tick tables. This "
            "is the figure the README's dataset size refers to."
        )
    else:
        out["raw_csv_bytes"] = None
        out["raw_csv_note"] = "raw root not provided; skipped"

    if csv_root and csv_root.exists():
        pairs = []
        for csv_file in sorted(csv_root.glob("*.csv")):
            twin = parquet_root / f"{csv_file.stem}.parquet"
            if twin.exists():
                pairs.append((csv_file.stem, csv_file.stat().st_size, twin.stat().st_size))
        if pairs:
            csv_total = sum(p[1] for p in pairs)
            pq_total = sum(p[2] for p in pairs)
            out["comparable_tables"] = len(pairs)
            out["comparable_csv_bytes"] = csv_total
            out["comparable_parquet_bytes"] = pq_total
            out["reduction_pct"] = round((1 - pq_total / csv_total) * 100, 1)
            out["backs"] = "README storage-reduction claim"
    else:
        out["reduction_pct"] = None
        out["csv_note"] = "csv root not provided; storage reduction skipped"

    return out


def measure_query_speed(parquet_root: Path, csv_root: Optional[Path]) -> Dict[str, Any]:
    """Parquet vs CSV speedups on three query shapes.

    The three shapes are reported separately and on purpose. A single
    'N-times faster' headline is not meaningful here: the speedup depends
    entirely on how much of the file the query must actually read.
    """
    if duckdb is None:
        return {"error": "duckdb not installed"}
    if not csv_root or not csv_root.exists():
        return {"skipped": "csv root not provided; speed comparison needs both formats"}

    table = "quote_close"
    csv_path = csv_root / f"{table}.csv"
    pq_path = parquet_root / f"{table}.parquet"
    if not (csv_path.exists() and pq_path.exists()):
        return {"skipped": f"{table} missing from one of the corpora"}

    conn = duckdb.connect()
    shapes = {
        "full_scan": (
            f"SELECT count(*), avg(price) FROM read_csv_auto('{csv_path}')",
            f"SELECT count(*), avg(price) FROM read_parquet('{pq_path}')",
        ),
        "filtered": (
            f"SELECT count(*) FROM read_csv_auto('{csv_path}') WHERE tickersymbol = 'FPT'",
            f"SELECT count(*) FROM read_parquet('{pq_path}') WHERE tickersymbol = 'FPT'",
        ),
        "group_by": (
            f"SELECT tickersymbol, avg(price) FROM read_csv_auto('{csv_path}') "
            f"GROUP BY tickersymbol",
            f"SELECT tickersymbol, avg(price) FROM read_parquet('{pq_path}') "
            f"GROUP BY tickersymbol",
        ),
        "metadata_only": (
            f"SELECT count(*) FROM read_csv_auto('{csv_path}')",
            f"SELECT count(*) FROM read_parquet('{pq_path}')",
        ),
    }

    results: Dict[str, Any] = {"table": table}
    for name, (csv_sql, pq_sql) in shapes.items():
        csv_s = _time_query(conn, csv_sql)
        pq_s = _time_query(conn, pq_sql)
        results[name] = {
            "csv_seconds": round(csv_s, 4),
            "parquet_seconds": round(pq_s, 4),
            "speedup": round(csv_s / pq_s, 1) if pq_s > 0 else None,
        }

    results["caveat"] = (
        "metadata_only is answered from Parquet footer statistics without "
        "reading row data, so its speedup is not comparable to the others and "
        "must not be quoted as a general query speedup."
    )
    results["backs"] = "README performance claims"
    return results


def measure_coverage(parquet_root: Path) -> Dict[str, Any]:
    """Daily-bar coverage. Backs the '23 years of daily data' claim."""
    if duckdb is None:
        return {"error": "duckdb not installed"}

    conn = duckdb.connect()

    def table(name: str) -> str:
        return f"read_parquet('{parquet_root / (name + '.parquet')}')"

    required = ["quote_open", "quote_max", "quote_min", "quote_close", "quote_dailyvolume"]
    missing = [t for t in required if not (parquet_root / f"{t}.parquet").exists()]
    if missing:
        return {"skipped": f"missing daily tables: {missing}"}

    ohlc_sql = f"""
        SELECT count(*) AS rows,
               count(DISTINCT tickersymbol) AS tickers,
               min(datetime) AS first_day,
               max(datetime) AS last_day
        FROM {table('quote_open')} o
        JOIN {table('quote_max')}   h USING (datetime, tickersymbol)
        JOIN {table('quote_min')}   l USING (datetime, tickersymbol)
        JOIN {table('quote_close')} c USING (datetime, tickersymbol)
    """
    rows, tickers, first_day, last_day = conn.execute(ohlc_sql).fetchone()

    with_vol_sql = ohlc_sql.replace(
        f"JOIN {table('quote_close')} c USING (datetime, tickersymbol)",
        f"JOIN {table('quote_close')} c USING (datetime, tickersymbol)\n"
        f"        JOIN {table('quote_dailyvolume')} v USING (datetime, tickersymbol)",
    )
    v_rows, v_tickers, v_first, v_last = conn.execute(with_vol_sql).fetchone()

    return {
        "ohlc_only": {
            "rows": rows,
            "tickers": tickers,
            "first_day": str(first_day),
            "last_day": str(last_day),
        },
        "ohlc_with_volume": {
            "rows": v_rows,
            "tickers": v_tickers,
            "first_day": str(v_first),
            "last_day": str(v_last),
            "note": (
                "This is what get_ohlc(interval='1d') returns by default. It is "
                "smaller than ohlc_only because the daily volume table does not "
                "cover every ticker-day."
            ),
        },
        "backs": "README daily-coverage claim",
    }


def measure_field_availability(parquet_root: Path) -> Dict[str, Any]:
    """Which advertised fields actually hold data.

    Backs the MCP surface's field list. A field whose table exists but holds
    zero rows is worse than an absent one: a caller reading the advertised
    field list will request it and get nothing back with no explanation.
    """
    if duckdb is None:
        return {"error": "duckdb not installed"}

    conn = duckdb.connect()
    empty, present, absent = [], [], []

    try:
        from plutus.datahub.config import DataHubConfig
        mappings = DataHubConfig.FIELD_MAPPINGS
    except Exception as exc:  # pragma: no cover
        return {"error": f"could not import DataHubConfig: {exc}"}

    for field, filename in sorted(mappings.items()):
        stem = Path(filename).stem
        pq = parquet_root / f"{stem}.parquet"
        csvf = parquet_root / f"{stem}.csv"
        path = pq if pq.exists() else (csvf if csvf.exists() else None)
        if path is None:
            absent.append(field)
            continue
        reader = "read_parquet" if path.suffix == ".parquet" else "read_csv_auto"
        try:
            n = conn.execute(f"SELECT count(*) FROM {reader}('{path}')").fetchone()[0]
        except Exception:
            absent.append(field)
            continue
        (present if n > 0 else empty).append(field)

    return {
        "present_with_data": sorted(present),
        "present_but_empty": sorted(empty),
        "absent": sorted(absent),
        "counts": {
            "with_data": len(present),
            "empty": len(empty),
            "absent": len(absent),
        },
        "backs": "MCP get_available_fields() honesty",
    }



# --------------------------------------------------------------------------
# exchange fill model (plutus.market)
# --------------------------------------------------------------------------

def measure_exchange_admission(data_root: Path) -> Dict[str, Any]:
    """Blocked-entry rate at both lags. Backs the paper's equity headline.

    Both variants are reported because the difference between them is the
    result: testing the ceiling lock on the session that produced the momentum
    signal embeds look-ahead, and more than halves when corrected.
    """
    try:
        from measurements.band_conformance import measure_band_conformance
        from measurements.equity_admission import measure_blocked_entries
    except ImportError as exc:  # pragma: no cover
        return {"error": f"could not import measurements: {exc}"}

    out: Dict[str, Any] = {}
    for stocks_only in (True, False):
        for lag in (0, 1):
            r = measure_blocked_entries(str(data_root), lag=lag,
                                        stocks_only=stocks_only)
            out[f"{r.population}_lag{lag}"] = r.to_dict()
    # Engine-backed band conformance: the library's own reconstruct_bands vs the
    # vendor ceiling/floor, so the band-family result is the engine reproducing
    # the observed lock rather than a SQL equality on the vendor field. HSX stock
    # is the headline (parallels the bar-vs-tick lock).
    out["band_conformance"] = measure_band_conformance(str(data_root)).to_dict()
    out["note"] = (
        "lag=1 is the tradeable rule and the honest headline; lag=0 is the "
        "figure prior work quoted and tests the lock on the signal session. "
        "band_conformance backs these with the engine's own band computation."
    )
    return out


def measure_exchange_grid(data_root: Path) -> Dict[str, Any]:
    """Tick-grid conformity, library rule against a named naive baseline."""
    try:
        from measurements.grid_conformity import measure_grid_conformity
    except ImportError as exc:  # pragma: no cover
        return {"error": f"could not import measurements: {exc}"}

    return {r.universe: r.to_dict() for r in (
        measure_grid_conformity(str(data_root), stocks_only=False),
        measure_grid_conformity(str(data_root), stocks_only=True),
    )}


def _wilson_ci(k: int, n: int, z: float = 1.96) -> Dict[str, float]:
    """95% Wilson score interval for a proportion k/n, for the headline rates."""
    if n <= 0:
        return {"lo": 0.0, "hi": 0.0}
    import math
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
    return {"lo": round(centre - half, 4), "hi": round(centre + half, 4)}


def measure_exchange_margin(data_root: Path) -> Dict[str, Any]:
    """Front-month VN30F margin incidence from the real account model, plus the
    KRX-cutover regime split.

    Drives an actual ``DerivativesAccount`` through
    ``deposit.account_margin_requirement`` on the **dated** VSD initial-margin
    series (10 -> 13 -> 17%) with **daily variation-margin cash settlement**
    (MUST #4), replacing the retired flat-maintenance-ratio measurement that
    fired on a fictional ``margin.ratio < 0.17`` -- a quantity the engine itself
    disavows; no Vietnamese regime has a maintenance ratio. ``funding_multiple``
    is the one free parameter (deposit as a multiple of the opening requirement),
    reported at the fitted value and swept so the assumption is visible. Headline
    rates carry a 95% Wilson interval. ``regime_split`` is the dated-editions
    demonstration: the same book under pre-KRX IM vs the post-KRX scenario grid.
    """
    try:
        from decimal import Decimal

        from measurements.margin_incidence_account import (
            BEST_JOINT_FIT, measure_account_margin_incidence)
        from measurements.regime_split import measure_regime_split
    except ImportError as exc:  # pragma: no cover
        return {"error": f"could not import measurements: {exc}"}

    def _with_ci(r: Dict[str, Any]) -> Dict[str, Any]:
        n = int(r.get("entries") or 0)
        r["call_ci95"] = _wilson_ci(int(r.get("called") or 0), n)
        r["forced_ci95"] = _wilson_ci(int(r.get("forced") or 0), n)
        return r

    out: Dict[str, Any] = {
        f"hold_{h}": _with_ci(measure_account_margin_incidence(
            str(data_root), holding_days=h, funding_multiple=BEST_JOINT_FIT,
            settle_daily=True).to_dict())
        for h in (5, 10, 20)
    }
    # The one free parameter, made visible: incidence across funding levels at
    # the 10-session hold (deposit as a multiple of the opening requirement).
    out["funding_sweep"] = {
        str(m): measure_account_margin_incidence(
            str(data_root), holding_days=10, funding_multiple=m,
            settle_daily=True).to_dict()
        for m in (Decimal("1.2"), BEST_JOINT_FIT, Decimal("1.6"), Decimal("2.0"))
    }
    out["regime_split"] = measure_regime_split(str(data_root))
    out["model"] = ("account: dated VSD IM series + daily cash settlement "
                    "(QD 26 Dieu 20); no maintenance ratio")
    return out


def measure_exchange_bar_vs_tick(
    data_root: Path, raw_root: Optional[Path]
) -> Dict[str, Any]:
    """Divergence between an inferred and an observed band lock.

    Needs the raw archive; skips with a stated reason without it, matching the
    --csv-root convention used elsewhere in this file.
    """
    if raw_root is None or not raw_root.exists():
        return {"skipped": "raw root not provided; the tick arm needs the "
                           "order book, which only the raw archive carries"}
    try:
        from measurements.bar_vs_tick import measure_bar_vs_tick
    except ImportError as exc:  # pragma: no cover
        return {"error": f"could not import measurements: {exc}"}

    return measure_bar_vs_tick(str(data_root), str(raw_root)).to_dict()


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate Plutus's documented measurements.",
    )
    parser.add_argument(
        "--data-root", required=True, type=Path,
        help="Parquet corpus root (required).",
    )
    parser.add_argument(
        "--csv-root", type=Path, default=None,
        help="CSV twin of the Parquet corpus, for storage/speed comparison.",
    )
    parser.add_argument(
        "--raw-root", type=Path, default=None,
        help="Full raw CSV archive, for the headline dataset size.",
    )
    parser.add_argument(
        "--json", type=Path, default=None,
        help="Also write results to this path as JSON.",
    )
    parser.add_argument(
        "--skip-tests", action="store_true",
        help="Skip test collection (it shells out to pytest).",
    )
    args = parser.parse_args()

    if not args.data_root.exists():
        print(f"error: --data-root does not exist: {args.data_root}", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parent
    results: Dict[str, Any] = {"data_root": str(args.data_root)}

    print("=" * 72)
    print("Plutus measurement reproduction")
    print("=" * 72)

    print("\n[1/9] storage ...")
    results["storage"] = measure_storage(args.data_root, args.csv_root, args.raw_root)
    s = results["storage"]
    print(f"      parquet corpus : {s.get('parquet_human')}")
    if s.get("raw_csv_bytes"):
        print(f"      raw CSV archive: {s.get('raw_csv_human')}")
    if s.get("reduction_pct") is not None:
        print(f"      reduction      : {s['reduction_pct']}% "
              f"over {s['comparable_tables']} comparable tables")

    print("\n[2/9] daily coverage ...")
    results["coverage"] = measure_coverage(args.data_root)
    cov = results["coverage"].get("ohlc_with_volume")
    if cov:
        print(f"      {cov['first_day']} -> {cov['last_day']}: "
              f"{cov['rows']:,} rows, {cov['tickers']} tickers")

    print("\n[3/9] query speed ...")
    results["speed"] = measure_query_speed(args.data_root, args.csv_root)
    sp = results["speed"]
    for shape in ("full_scan", "filtered", "group_by", "metadata_only"):
        if shape in sp:
            print(f"      {shape:15s} {sp[shape]['speedup']}x")

    print("\n[4/9] field availability ...")
    results["fields"] = measure_field_availability(args.data_root)
    fc = results["fields"].get("counts")
    if fc:
        print(f"      {fc['with_data']} with data, "
              f"{fc['empty']} empty, {fc['absent']} absent")
        if results["fields"]["present_but_empty"]:
            print(f"      empty: {', '.join(results['fields']['present_but_empty'])}")

    if args.skip_tests:
        results["tests"] = {"skipped": True}
        print("\n[5/9] test suite ... skipped")
    else:
        print("\n[5/9] test suite ...")
        results["tests"] = measure_test_suite(repo_root)
        print(f"      collected: {results['tests'].get('collected')}")

    print("\n[6/9] exchange admission (equity headline) ...")
    results["exchange_admission"] = measure_exchange_admission(args.data_root)
    for key, value in results["exchange_admission"].items():
        if isinstance(value, dict) and "rate" in value:
            print(f"      {key:<26} {value['blocked']:>7,} / "
                  f"{value['attempts']:>8,} = {value['rate']:.4%}")

    print("\n[7/9] tick-grid conformity ...")
    results["exchange_grid"] = measure_exchange_grid(args.data_root)
    for universe, value in results["exchange_grid"].items():
        print(f"      {universe:<22} library {value['library_rate']:.4%}  "
              f"naive {value['naive_rate']:.4%}")

    print("\n[8/9] derivatives margin incidence ...")
    results["exchange_margin"] = measure_exchange_margin(args.data_root)
    for hold in (5, 10, 20):
        value = results["exchange_margin"][f"hold_{hold}"]
        print(f"      hold {hold:>2}  {value['called']:>4,} / "
              f"{value['entries']:>4,} = {value['call_rate']:.2%}")

    print("\n[9/9] bar-vs-tick divergence ...")
    results["exchange_bar_vs_tick"] = measure_exchange_bar_vs_tick(
        args.data_root, args.raw_root)
    div = results["exchange_bar_vs_tick"]
    if "skipped" in div:
        print(f"      skipped: {div['skipped']}")
    else:
        print(f"      n={div['n']:,}  bar {div['bar_blocked']:,}  "
              f"tick {div['tick_blocked_at_close']:,}  "
              f"agreement {div['agreement']:.4%}")

    if args.json:
        args.json.write_text(json.dumps(results, indent=2, default=str))
        print(f"\nwrote {args.json}")

    print("\nDone. Every documented number should trace to a field above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
