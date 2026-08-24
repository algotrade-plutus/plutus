"""Blocked-entry rate: how often a momentum entry cannot fill.

Two variants, and the difference between them matters more than either number.

``lag=0`` tests the ceiling lock on the **same** session that produced the
momentum signal. That is how the previously-quoted figure was obtained, and it
embeds look-ahead: a close-to-close signal cannot be acted on inside the
session that generated it.

``lag=1`` tests the lock on the **next** session, which is when an entry could
actually be attempted. It is the tradeable rule, and it is less than half the
size.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import duckdb

__all__ = ['BlockedFillResult', 'measure_blocked_entries']


@dataclass(frozen=True)
class BlockedFillResult:
    attempts: int
    blocked: int
    rate: Decimal
    lag: int
    population: str
    excluded_inverted: int

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out['rate'] = float(self.rate)
        out['variant'] = ('same_session_look_ahead' if self.lag == 0
                          else 'next_session_tradeable')
        out['backs'] = (
            'paper equity headline: share of naive momentum entries the '
            'exchange would not fill'
        )
        return out


def _reader(root: Path, table: str) -> str:
    parquet = root / f'{table}.parquet'
    if parquet.exists():
        return f"read_parquet('{parquet}')"
    return f"read_csv_auto('{root / (table + '.csv')}')"


def measure_blocked_entries(
    data_root: str,
    *,
    lag: int,
    stocks_only: bool = True,
) -> BlockedFillResult:
    """Measure the blocked-entry rate.

    Args:
        data_root: dataset root.
        lag: 0 tests the lock on the signal session (look-ahead); 1 tests it on
            the next session (tradeable).
        stocks_only: restrict to ``instrumenttype = 'stock'``.

    The ``ce.price >= fl.price`` predicate excludes the 1,272 inverted-band
    rows. That filter is load-bearing rather than cosmetic: 1,226 of them are
    cash stock ticker-days.
    """
    if lag not in (0, 1):
        raise ValueError('lag must be 0 (same session) or 1 (next session)')

    root = Path(data_root)
    close = _reader(root, 'quote_close')
    ceil_t = _reader(root, 'quote_ceil')
    floor_t = _reader(root, 'quote_floor')
    ticker_t = _reader(root, 'quote_ticker')
    conn = duckdb.connect()

    stock_join = (
        f"JOIN {ticker_t} tk ON tk.tickersymbol = s.tickersymbol "
        f"AND tk.instrumenttype = 'stock'" if stocks_only else ''
    )
    # The lead() MUST be computed over the full per-ticker series, in the
    # signals CTE, before the momentum filter. SQL evaluates window functions
    # after WHERE, so computing it alongside the filter would yield the next
    # *momentum day* rather than the next *session* -- which returns ~12.9%,
    # nearly indistinguishable from the same-session figure, because momentum
    # days cluster.
    if lag == 0:
        attempt_dt, attempt_close = 's.datetime', 's.price'
    else:
        attempt_dt, attempt_close = 's.next_dt', 's.next_price'

    sql = f"""
        WITH signals AS (
            SELECT c.tickersymbol, c.datetime, c.price,
                   lag(c.price) OVER (PARTITION BY c.tickersymbol
                                      ORDER BY c.datetime) AS prev_price,
                   lead(c.datetime) OVER (PARTITION BY c.tickersymbol
                                          ORDER BY c.datetime) AS next_dt,
                   lead(c.price) OVER (PARTITION BY c.tickersymbol
                                       ORDER BY c.datetime) AS next_price
            FROM {close} c
        ), fired AS (
            SELECT s.tickersymbol,
                   {attempt_dt}    AS attempt_dt,
                   {attempt_close} AS attempt_close
            FROM signals s
            {stock_join}
            WHERE s.prev_price IS NOT NULL
              AND s.price > s.prev_price
        )
        SELECT count(*) AS attempts,
               sum(CASE WHEN f.attempt_close = ce.price THEN 1 ELSE 0 END)
                   AS blocked
        FROM fired f
        JOIN {ceil_t}  ce ON ce.tickersymbol = f.tickersymbol
                          AND ce.datetime = f.attempt_dt
        JOIN {floor_t} fl ON fl.tickersymbol = f.tickersymbol
                          AND fl.datetime = f.attempt_dt
        WHERE f.attempt_dt IS NOT NULL
          AND ce.price >= fl.price
    """
    attempts, blocked = conn.execute(sql).fetchone()
    attempts, blocked = int(attempts or 0), int(blocked or 0)

    excluded = conn.execute(
        f"""SELECT count(*) FROM {ceil_t} ce
            JOIN {floor_t} fl USING (datetime, tickersymbol)
            WHERE ce.price < fl.price"""
    ).fetchone()[0]

    rate = Decimal(blocked) / Decimal(attempts) if attempts else Decimal('0')
    return BlockedFillResult(
        attempts=attempts, blocked=blocked, rate=rate, lag=lag,
        population='stocks' if stocks_only else 'all_instruments',
        excluded_inverted=int(excluded),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()

    results: Dict[str, Any] = {}
    for stocks_only in (True, False):
        for lag in (0, 1):
            r = measure_blocked_entries(args.data_root, lag=lag,
                                        stocks_only=stocks_only)
            results[f'{r.population}_lag{lag}'] = r.to_dict()
            label = ('same-session (LOOK-AHEAD)' if lag == 0
                     else 'next-session (tradeable)')
            print(f'{r.population:<16} {label:<27} '
                  f'{r.blocked:>7,} / {r.attempts:>8,} = {float(r.rate):.4%}')

    print('\nThe next-session figure is the tradeable one. The same-session '
          'figure tests the lock\non the very session that produced the '
          'signal, which no strategy could act on.')
    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f'wrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
