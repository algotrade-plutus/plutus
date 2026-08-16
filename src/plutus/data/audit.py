"""Machine-checkable dataset characterization.

This is a documented characterization of the corpus, not a bug list. Each
check below states an invariant a consumer would reasonably assume, measures
how often the data violates it, and emits a machine-readable result. Two
consequences follow:

* Analyses that must exclude bad rows can do so by a named, reproducible rule
  rather than an ad-hoc filter buried in a notebook. That is what
  ``strict=True`` on the query layer is for.
* A published result can state exactly which rows it excluded and why.

Run it directly::

    python -m plutus.data.audit --data-root /path/to/dataset
    python -m plutus.data.audit --data-root /path/to/dataset --json report.json
    python -m plutus.data.audit --data-root /path/to/dataset --check ohlc_invariants

Exit status is 0 when every check ran, 1 when a check could not run (a missing
table, say). A check that *finds* violations is a successful run, not a
failure: the violations are the output.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import duckdb
except ImportError:  # pragma: no cover
    duckdb = None


# --------------------------------------------------------------------------
# result types
# --------------------------------------------------------------------------

@dataclass
class CheckResult:
    """The outcome of one audit check."""

    name: str
    description: str
    #: What a consumer would assume, stated so the violation count is readable.
    invariant: str
    violations: Optional[int] = None
    total: Optional[int] = None
    #: Structured detail: offending days, symbols, per-table counts.
    detail: Dict[str, Any] = field(default_factory=dict)
    ran: bool = True
    skipped_reason: Optional[str] = None

    @property
    def rate(self) -> Optional[float]:
        """Violations as a fraction of rows examined."""
        if self.violations is None or not self.total:
            return None
        return self.violations / self.total

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out['rate'] = self.rate
        return out


@dataclass
class AuditReport:
    """The full set of check results for one dataset root."""

    data_root: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def ran(self) -> List[CheckResult]:
        return [c for c in self.checks if c.ran]

    @property
    def skipped(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.ran]

    @property
    def total_violations(self) -> int:
        return sum(c.violations or 0 for c in self.ran)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'data_root': self.data_root,
            'checks': [c.to_dict() for c in self.checks],
            'summary': {
                'checks_run': len(self.ran),
                'checks_skipped': len(self.skipped),
                'total_violations': self.total_violations,
            },
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


# --------------------------------------------------------------------------
# the auditor
# --------------------------------------------------------------------------

class DataAudit:
    """Runs dataset characterization checks against a Parquet/CSV corpus.

    Example:
        >>> audit = DataAudit('/path/to/hermes-parquet')
        >>> report = audit.run()
        >>> report.total_violations
        38377
    """

    def __init__(self, data_root: str | Path):
        if duckdb is None:  # pragma: no cover
            raise ImportError("duckdb is required for plutus.data.audit")
        self.data_root = Path(data_root)
        if not self.data_root.exists():
            raise FileNotFoundError(f"Dataset root not found: {self.data_root}")
        self._conn = duckdb.connect()

    # -- plumbing ----------------------------------------------------------

    def _path(self, table: str) -> Optional[Path]:
        for suffix in ('.parquet', '.csv'):
            candidate = self.data_root / f"{table}{suffix}"
            if candidate.exists():
                return candidate
        return None

    def _reader(self, table: str) -> Optional[str]:
        path = self._path(table)
        if path is None:
            return None
        fn = 'read_parquet' if path.suffix == '.parquet' else 'read_csv_auto'
        return f"{fn}('{path}')"

    def _missing(self, *tables: str) -> List[str]:
        return [t for t in tables if self._reader(t) is None]

    def _query(self, sql: str) -> List[tuple]:
        return self._conn.execute(sql).fetchall()

    # -- checks ------------------------------------------------------------

    def check_price_band_invariant(self) -> CheckResult:
        """Ceiling must not sit below floor.

        A ceiling below its floor makes the day's tradable range empty, and any
        limit-band analysis over those rows is meaningless. In this corpus the
        violations are concentrated on three days and look like a swapped pair.
        """
        result = CheckResult(
            name='price_band_invariant',
            description='Daily price ceiling must be >= floor',
            invariant='quote_ceil.price >= quote_floor.price',
        )
        missing = self._missing('quote_ceil', 'quote_floor')
        if missing:
            result.ran = False
            result.skipped_reason = f"missing tables: {missing}"
            return result

        ceil_r, floor_r = self._reader('quote_ceil'), self._reader('quote_floor')
        join = (
            f"FROM {ceil_r} cl JOIN {floor_r} f USING (datetime, tickersymbol)"
        )
        result.violations = self._query(
            f"SELECT count(*) {join} WHERE cl.price < f.price"
        )[0][0]
        result.total = self._query(f"SELECT count(*) {join}")[0][0]
        result.detail['by_day'] = {
            str(day): n for day, n in self._query(
                f"SELECT datetime, count(*) {join} WHERE cl.price < f.price "
                f"GROUP BY 1 ORDER BY 1"
            )
        }
        return result

    def check_ohlc_invariants(self) -> CheckResult:
        """High must bound open and close from above; low from below.

        Independent of the ceiling/floor defect. A bar whose high is below its
        close cannot have occurred, and any high/low-derived measure over those
        rows (true range, gap statistics, breakout rules) is wrong.
        """
        result = CheckResult(
            name='ohlc_invariants',
            description='Session high/low must bracket open and close',
            invariant='high >= max(open, close) AND low <= min(open, close)',
        )
        tables = ('quote_max', 'quote_min', 'quote_open', 'quote_close')
        missing = self._missing(*tables)
        if missing:
            result.ran = False
            result.skipped_reason = f"missing tables: {missing}"
            return result

        h, l, o, c = (self._reader(t) for t in tables)
        join = (
            f"FROM {h} h "
            f"JOIN {l} l USING (datetime, tickersymbol) "
            f"JOIN {o} o USING (datetime, tickersymbol) "
            f"JOIN {c} c USING (datetime, tickersymbol)"
        )
        high_bad, low_bad, total = self._query(
            f"SELECT "
            f"  sum(CASE WHEN h.price < greatest(o.price, c.price) THEN 1 ELSE 0 END), "
            f"  sum(CASE WHEN l.price > least(o.price, c.price) THEN 1 ELSE 0 END), "
            f"  count(*) {join}"
        )[0]
        result.violations = int(high_bad or 0) + int(low_bad or 0)
        result.total = total
        result.detail['high_below_open_or_close'] = int(high_bad or 0)
        result.detail['low_above_open_or_close'] = int(low_bad or 0)
        return result

    #: Exchanges that make an instrument Vietnamese.
    VIETNAM_EXCHANGES = ('HSX', 'HNX', 'HNXDS', 'UPCOM')

    #: The Ho Chi Minh exchange opened on this date. Nothing Vietnamese
    #: predates it.
    MARKET_OPENING = '2000-07-28'

    def check_non_vietnamese_symbols(self) -> CheckResult:
        """Tables billed as Vietnamese must not carry foreign instruments.

        Identification is by *symbol*, not by date, and uses two independent
        signals:

        * **Exchange registration.** A ticker registered to an exchange outside
          Vietnam is foreign whatever its dates. This is the signal that
          matters for contemporaneous foreign data, which a date rule cannot
          see at all.
        * **Calendar.** A ticker with observations predating the market's
          opening cannot be Vietnamese. This catches unregistered foreign
          series, which carry no exchange to test.

        Once a symbol is identified, **all** of its rows count as violations,
        not merely the ones that tripped the test. An earlier date-only version
        of this check reported a foreign index's pre-2000 tail (33,210 rows)
        while silently passing the remaining 5,643 rows of the same instrument.

        Unregistered is not the same as foreign: the VNINDEX itself and the
        VN30F futures series carry no exchange but are Vietnamese. They are
        reported by :meth:`check_orphan_symbols` instead.
        """
        result = CheckResult(
            name='non_vietnamese_symbols',
            description='No instruments from outside the Vietnamese market',
            invariant=(
                f"every symbol is registered to {'/'.join(self.VIETNAM_EXCHANGES)} "
                f"or has no observations before {self.MARKET_OPENING}"
            ),
        )
        if self._missing('quote_close'):
            result.ran = False
            result.skipped_reason = 'missing table: quote_close'
            return result

        close_r = self._reader('quote_close')
        ticker_r = self._reader('quote_ticker')

        # Signal 1: registered to a non-Vietnamese exchange.
        by_exchange: Dict[str, str] = {}
        if ticker_r:
            vn_list = ', '.join(f"'{e}'" for e in self.VIETNAM_EXCHANGES)
            by_exchange = {
                sym: exch for sym, exch in self._query(
                    f"SELECT DISTINCT t.tickersymbol, t.exchangeid "
                    f"FROM {ticker_r} t "
                    f"WHERE t.exchangeid IS NOT NULL "
                    f"  AND t.exchangeid NOT IN ({vn_list})"
                )
            }

        # Signal 2: observations predating the market's opening.
        by_calendar = [
            row[0] for row in self._query(
                f"SELECT DISTINCT tickersymbol FROM {close_r} "
                f"WHERE datetime < '{self.MARKET_OPENING}'"
            )
        ]

        foreign = sorted(set(by_exchange) | set(by_calendar))
        result.total = self._query(f"SELECT count(*) FROM {close_r}")[0][0]

        if not foreign:
            result.violations = 0
            result.detail.update({
                'by_symbol': {}, 'flagged_by_exchange': {}, 'flagged_by_calendar': [],
            })
            return result

        symbol_list = ', '.join(f"'{s}'" for s in foreign)
        per_symbol = {
            sym: n for sym, n in self._query(
                f"SELECT tickersymbol, count(*) FROM {close_r} "
                f"WHERE tickersymbol IN ({symbol_list}) "
                f"GROUP BY 1 ORDER BY 2 DESC"
            )
        }
        result.violations = sum(per_symbol.values())
        result.detail.update({
            'by_symbol': per_symbol,
            'flagged_by_exchange': by_exchange,
            'flagged_by_calendar': sorted(by_calendar),
        })
        return result

    def check_non_session_timestamps(self) -> CheckResult:
        """No rows on days the exchange does not trade.

        Weekend rows inflate any per-session denominator and shift
        day-of-week effects.
        """
        result = CheckResult(
            name='non_session_timestamps',
            description='No observations on Saturdays or Sundays',
            invariant='dayofweek(datetime) NOT IN (0, 6)',
        )
        if self._missing('quote_close'):
            result.ran = False
            result.skipped_reason = 'missing table: quote_close'
            return result

        reader = self._reader('quote_close')
        result.violations = self._query(
            f"SELECT count(*) FROM {reader} WHERE dayofweek(datetime) IN (0, 6)"
        )[0][0]
        result.total = self._query(f"SELECT count(*) FROM {reader}")[0][0]
        result.detail['distinct_weekend_days'] = self._query(
            f"SELECT count(DISTINCT datetime) FROM {reader} "
            f"WHERE dayofweek(datetime) IN (0, 6)"
        )[0][0]
        return result

    def check_orphan_symbols(self) -> CheckResult:
        """Every quoted symbol should appear in the ticker master.

        An orphan cannot be resolved to an exchange, so its tick size, round
        lot and price-limit band are all unknown. Instrument-aware analysis
        must either resolve or exclude these.
        """
        result = CheckResult(
            name='orphan_symbols',
            description='Quoted symbols must exist in the ticker master',
            invariant='quote_close.tickersymbol IN quote_ticker.tickersymbol',
        )
        missing = self._missing('quote_close', 'quote_ticker')
        if missing:
            result.ran = False
            result.skipped_reason = f"missing tables: {missing}"
            return result

        close_r, ticker_r = self._reader('quote_close'), self._reader('quote_ticker')
        orphans = self._query(
            f"SELECT DISTINCT c.tickersymbol FROM {close_r} c "
            f"LEFT JOIN {ticker_r} t ON c.tickersymbol = t.tickersymbol "
            f"WHERE t.tickersymbol IS NULL ORDER BY 1"
        )
        result.violations = len(orphans)
        result.total = self._query(
            f"SELECT count(DISTINCT tickersymbol) FROM {close_r}"
        )[0][0]
        result.detail['symbols'] = [row[0] for row in orphans]
        return result

    def check_empty_tables(self) -> CheckResult:
        """A table present but empty is worse than one that is absent.

        An absent table produces a clear error. An empty one satisfies every
        existence check and then silently returns nothing.
        """
        result = CheckResult(
            name='empty_tables',
            description='Tables present in the corpus must hold rows',
            invariant='count(*) > 0 for every table file',
        )
        files = sorted(
            list(self.data_root.glob('*.parquet')) or list(self.data_root.glob('*.csv'))
        )
        if not files:
            result.ran = False
            result.skipped_reason = 'no data files found'
            return result

        empty = []
        for path in files:
            fn = 'read_parquet' if path.suffix == '.parquet' else 'read_csv_auto'
            try:
                n = self._query(f"SELECT count(*) FROM {fn}('{path}')")[0][0]
            except Exception:
                continue
            if n == 0:
                empty.append(path.stem)

        result.violations = len(empty)
        result.total = len(files)
        result.detail['tables'] = empty
        return result

    def check_ragged_coverage(self) -> CheckResult:
        """Report where each table's history begins.

        Tables in one corpus can span very different periods. Joining a
        2000-onward table to a 2021-onward one silently truncates the result to
        the shorter one, which is easy to mistake for a genuine data gap.
        """
        result = CheckResult(
            name='ragged_coverage',
            description='Tables start at widely different dates',
            invariant='(reported, not enforced)',
        )
        files = sorted(
            list(self.data_root.glob('*.parquet')) or list(self.data_root.glob('*.csv'))
        )
        if not files:
            result.ran = False
            result.skipped_reason = 'no data files found'
            return result

        starts: Dict[str, str] = {}
        for path in files:
            fn = 'read_parquet' if path.suffix == '.parquet' else 'read_csv_auto'
            try:
                row = self._query(
                    f"SELECT min(datetime), max(datetime) FROM {fn}('{path}')"
                )[0]
            except Exception:
                continue
            if row[0] is None:
                continue
            starts[path.stem] = {'first': str(row[0]), 'last': str(row[1])}

        late = {k: v for k, v in starts.items() if v['first'] >= '2021-01-01'}
        result.violations = len(late)
        result.total = len(starts)
        result.detail['coverage'] = starts
        result.detail['starting_2021_or_later'] = sorted(late)
        return result

    def check_vn30_survivorship(self) -> CheckResult:
        """Quantify the survivorship gap in the index membership snapshots.

        Back-projecting today's members over history is the single most common
        silent bias in index-based backtests. The gap between distinct members
        ever seen and members per snapshot is its magnitude.
        """
        result = CheckResult(
            name='vn30_survivorship',
            description='VN30 membership changes over time',
            invariant='(reported, not enforced)',
        )
        if self._missing('quote_vn30'):
            result.ran = False
            result.skipped_reason = 'missing table: quote_vn30'
            return result

        reader = self._reader('quote_vn30')
        snapshots, distinct_members, rows = self._query(
            f"SELECT count(DISTINCT datetime), count(DISTINCT tickersymbol), "
            f"count(*) FROM {reader}"
        )[0]
        per_snapshot = rows // snapshots if snapshots else 0

        # Members ever in the index, beyond what any single snapshot shows.
        result.violations = distinct_members - per_snapshot
        result.total = distinct_members
        result.detail.update({
            'snapshots': snapshots,
            'members_per_snapshot': per_snapshot,
            'distinct_members_ever': distinct_members,
            'note': (
                'Using the latest snapshot for all history would omit '
                f'{distinct_members - per_snapshot} tickers that were members '
                'at some point.'
            ),
        })
        return result

    # -- reusable exclusions ----------------------------------------------

    def inverted_band_exclusions(self) -> List[tuple]:
        """Return the ``(date, ticker)`` pairs whose price band is inverted.

        Published results that depend on the price-limit bands must exclude
        these rows and say so. Returning them as data — rather than leaving
        each analysis to re-derive its own filter — is what makes that
        exclusion reproducible and auditable.

        The OHLC query's ``strict=True`` mode cannot apply this filter itself:
        it does not join the ceiling/floor tables, so there is nothing there to
        filter. Band-dependent analyses should anti-join against this list.

        Returns:
            A list of ``(datetime, tickersymbol)`` tuples. Empty if the band
            tables are absent.
        """
        if self._missing('quote_ceil', 'quote_floor'):
            return []

        ceil_r, floor_r = self._reader('quote_ceil'), self._reader('quote_floor')
        return self._query(
            f"SELECT cl.datetime, cl.tickersymbol "
            f"FROM {ceil_r} cl JOIN {floor_r} f USING (datetime, tickersymbol) "
            f"WHERE cl.price < f.price "
            f"ORDER BY cl.datetime, cl.tickersymbol"
        )

    # -- driver ------------------------------------------------------------

    CHECKS: Dict[str, str] = {
        'price_band_invariant': 'check_price_band_invariant',
        'ohlc_invariants': 'check_ohlc_invariants',
        'non_vietnamese_symbols': 'check_non_vietnamese_symbols',
        'non_session_timestamps': 'check_non_session_timestamps',
        'orphan_symbols': 'check_orphan_symbols',
        'empty_tables': 'check_empty_tables',
        'ragged_coverage': 'check_ragged_coverage',
        'vn30_survivorship': 'check_vn30_survivorship',
    }

    def run(self, only: Optional[List[str]] = None) -> AuditReport:
        """Run every check, or the named subset.

        Args:
            only: Check names to run. ``None`` runs all of them.

        Returns:
            An :class:`AuditReport`.
        """
        names = only or list(self.CHECKS)
        unknown = [n for n in names if n not in self.CHECKS]
        if unknown:
            raise ValueError(
                f"Unknown check(s): {unknown}. "
                f"Available: {sorted(self.CHECKS)}"
            )

        report = AuditReport(data_root=str(self.data_root))
        for name in names:
            method: Callable[[], CheckResult] = getattr(self, self.CHECKS[name])
            report.checks.append(method())
        return report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _render(report: AuditReport) -> str:
    lines = [
        '=' * 74,
        'Plutus dataset audit',
        f'root: {report.data_root}',
        '=' * 74,
        '',
    ]
    for check in report.checks:
        if not check.ran:
            lines.append(f"[skip] {check.name}: {check.skipped_reason}")
            continue
        rate = f" ({check.rate * 100:.3f}%)" if check.rate is not None else ""
        total = f" of {check.total:,}" if check.total is not None else ""
        lines.append(f"[{check.name}]")
        lines.append(f"  invariant : {check.invariant}")
        lines.append(f"  violations: {check.violations:,}{total}{rate}")

        detail = check.detail
        if 'by_day' in detail and detail['by_day']:
            days = ', '.join(f"{d} ({n:,})" for d, n in detail['by_day'].items())
            lines.append(f"  days      : {days}")
        if 'by_symbol' in detail and detail['by_symbol']:
            syms = ', '.join(f"{s} ({n:,})" for s, n in detail['by_symbol'].items())
            lines.append(f"  symbols   : {syms}")
        if check.name == 'ohlc_invariants':
            lines.append(
                f"  breakdown : high<max(o,c) {detail['high_below_open_or_close']:,}"
                f", low>min(o,c) {detail['low_above_open_or_close']:,}"
            )
        if check.name == 'orphan_symbols' and detail.get('symbols'):
            shown = ', '.join(detail['symbols'][:8])
            more = len(detail['symbols']) - 8
            lines.append(f"  examples  : {shown}" + (f" (+{more} more)" if more > 0 else ""))
        if check.name == 'empty_tables' and detail.get('tables'):
            lines.append(f"  tables    : {', '.join(detail['tables'])}")
        if check.name == 'ragged_coverage':
            lines.append(
                f"  late start: {len(detail['starting_2021_or_later'])} of "
                f"{check.total} tables begin 2021 or later"
            )
        if check.name == 'vn30_survivorship':
            lines.append(
                f"  detail    : {detail['snapshots']} snapshots x "
                f"{detail['members_per_snapshot']} members; "
                f"{detail['distinct_members_ever']} distinct ever"
            )
        lines.append('')

    lines.append('-' * 74)
    lines.append(
        f"{len(report.ran)} checks run, {len(report.skipped)} skipped, "
        f"{report.total_violations:,} total violations"
    )
    return '\n'.join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m plutus.data.audit',
        description='Characterize a Plutus market-data corpus.',
    )
    # Not `required`: --list-checks is informational and needs no corpus.
    parser.add_argument('--data-root', help='Dataset root directory')
    parser.add_argument(
        '--check', action='append', dest='checks', default=None,
        help='Run only this check (repeatable). Default: all.',
    )
    parser.add_argument('--json', type=Path, default=None, help='Write the report as JSON')
    parser.add_argument(
        '--list-checks', action='store_true', help='List available checks and exit',
    )
    args = parser.parse_args(argv)

    if args.list_checks:
        for name in sorted(DataAudit.CHECKS):
            print(name)
        return 0

    if not args.data_root:
        parser.error('--data-root is required (or use --list-checks)')

    try:
        audit = DataAudit(args.data_root)
    except (FileNotFoundError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        report = audit.run(only=args.checks)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(_render(report))

    if args.json:
        args.json.write_text(report.to_json())
        print(f"\nwrote {args.json}")

    # A check that finds violations still ran successfully; only a check that
    # could not run is an error.
    return 1 if report.skipped else 0


if __name__ == '__main__':
    raise SystemExit(main())
