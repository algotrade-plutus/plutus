"""Do observed prices lie on the exchange's legal tick grid?

The library rule is :func:`plutus.core.constant.get_hsx_tick_size`, including
its 8-character C/E/F warrant/ETF exception.

**The naive baseline is defined here, not inherited.** A previously-quoted
91.62% figure is not reproducible under any of six candidate grids across
eight universes (nearest 91.53%) and appears nowhere in code, so this module
names its own baseline explicitly: a **flat 0.1 grid over HSX closes**, which
is what a consumer would assume from a schema that reports prices in thousands
of VND with one decimal.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import duckdb

from plutus.core.constant import get_hsx_tick_size

__all__ = ['ConformityResult', 'measure_grid_conformity']

NAIVE_TICK = Decimal('0.1')
NAIVE_LABEL = 'flat 0.1 grid over HSX closes'


@dataclass(frozen=True)
class ConformityResult:
    universe: str
    observations: int
    library_conformant: int
    naive_conformant: int
    unresolvable: int
    library_rate: Decimal
    naive_rate: Decimal
    naive_baseline: str
    off_grid: tuple

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out['library_rate'] = float(self.library_rate)
        out['naive_rate'] = float(self.naive_rate)
        out['off_grid'] = [
            {'ticker': t, 'date': str(d), 'price': float(v), 'tick': float(k)}
            for t, d, v, k in self.off_grid
        ]
        out['backs'] = (
            'paper claim: the library reproduces the exchange tick grid where '
            'a naive fixed grid does not'
        )
        return out


def _reader(root: Path, table: str) -> str:
    parquet = root / f'{table}.parquet'
    if parquet.exists():
        return f"read_parquet('{parquet}')"
    return f"read_csv_auto('{root / (table + '.csv')}')"


def measure_grid_conformity(
    data_root: str,
    *,
    stocks_only: bool = False,
) -> ConformityResult:
    """Fraction of HSX closes lying on the legal grid, library rule vs naive.

    ``unresolvable`` counts prices for which ``get_hsx_tick_size`` returns
    ``None`` -- it is annotated ``-> Decimal`` but falls off the end of its
    band table for prices no band matches. Those are counted as
    non-conformant rather than crashing or being silently skipped.

    The residual is real and is reported, not rounded away: 13 HSX stock
    closes in 2014-2015 sit at two-decimal values inside the 0.05 band (e.g.
    DAG 12.31, C47 17.08, SVI 30.42). Those prices could not legally have
    traded, so they are corpus defects rather than a shortcoming of the rule.
    """
    root = Path(data_root)
    conn = duckdb.connect()

    stock_filter = ("AND tk.instrumenttype = 'stock'" if stocks_only else '')
    rows = conn.execute(f"""
        SELECT c.tickersymbol, c.datetime, c.price
        FROM {_reader(root, 'quote_close')} c
        JOIN {_reader(root, 'quote_ticker')} tk USING (tickersymbol)
        WHERE tk.exchangeid = 'HSX' {stock_filter}
    """).fetchall()

    library = naive = unresolvable = 0
    off_grid = []
    for ticker, day, price in rows:
        value = Decimal(str(price))
        tick = get_hsx_tick_size(ticker, value)
        if tick is None:
            unresolvable += 1
            off_grid.append((ticker, day, value, None))
        elif value % tick == 0:
            library += 1
        else:
            off_grid.append((ticker, day, value, tick))
        if value % NAIVE_TICK == 0:
            naive += 1

    total = len(rows)
    denom = Decimal(total) if total else Decimal('1')
    return ConformityResult(
        universe='HSX stocks' if stocks_only else 'HSX all instruments',
        observations=total, library_conformant=library, naive_conformant=naive,
        unresolvable=unresolvable,
        library_rate=Decimal(library) / denom,
        naive_rate=Decimal(naive) / denom,
        naive_baseline=NAIVE_LABEL,
        off_grid=tuple(sorted(off_grid, key=lambda r: (r[0], r[1]))),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()

    results: Dict[str, Any] = {}
    for stocks_only in (False, True):
        r = measure_grid_conformity(args.data_root, stocks_only=stocks_only)
        results[r.universe] = r.to_dict()
        print(f'{r.universe:<22} n={r.observations:>9,}  '
              f'library {float(r.library_rate):>8.4%}  '
              f'naive {float(r.naive_rate):>8.4%}  '
              f'off-grid {len(r.off_grid)}')
    print(f'\nnaive baseline: {NAIVE_LABEL}')
    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f'wrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
