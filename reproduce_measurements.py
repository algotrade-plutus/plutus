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

    print("\n[1/5] storage ...")
    results["storage"] = measure_storage(args.data_root, args.csv_root, args.raw_root)
    s = results["storage"]
    print(f"      parquet corpus : {s.get('parquet_human')}")
    if s.get("raw_csv_bytes"):
        print(f"      raw CSV archive: {s.get('raw_csv_human')}")
    if s.get("reduction_pct") is not None:
        print(f"      reduction      : {s['reduction_pct']}% "
              f"over {s['comparable_tables']} comparable tables")

    print("\n[2/5] daily coverage ...")
    results["coverage"] = measure_coverage(args.data_root)
    cov = results["coverage"].get("ohlc_with_volume")
    if cov:
        print(f"      {cov['first_day']} -> {cov['last_day']}: "
              f"{cov['rows']:,} rows, {cov['tickers']} tickers")

    print("\n[3/5] query speed ...")
    results["speed"] = measure_query_speed(args.data_root, args.csv_root)
    sp = results["speed"]
    for shape in ("full_scan", "filtered", "group_by", "metadata_only"):
        if shape in sp:
            print(f"      {shape:15s} {sp[shape]['speedup']}x")

    print("\n[4/5] field availability ...")
    results["fields"] = measure_field_availability(args.data_root)
    fc = results["fields"].get("counts")
    if fc:
        print(f"      {fc['with_data']} with data, "
              f"{fc['empty']} empty, {fc['absent']} absent")
        if results["fields"]["present_but_empty"]:
            print(f"      empty: {', '.join(results['fields']['present_but_empty'])}")

    if args.skip_tests:
        results["tests"] = {"skipped": True}
        print("\n[5/5] test suite ... skipped")
    else:
        print("\n[5/5] test suite ...")
        results["tests"] = measure_test_suite(repo_root)
        print(f"      collected: {results['tests'].get('collected')}")

    if args.json:
        args.json.write_text(json.dumps(results, indent=2, default=str))
        print(f"\nwrote {args.json}")

    print("\nDone. Every documented number should trace to a field above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
