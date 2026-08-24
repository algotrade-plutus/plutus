"""How much does bar-resolution analysis misstate a band lock?

At bar resolution a lock is *inferred*: the close printed at the ceiling.
At tick resolution it is *observed*: no ask rested at or below the ceiling all
session, so nothing was on offer under the cap.

Both arms are computed on **one identical population**, or the divergence is
undefined. The population is HSX ``instrumenttype='stock'`` ticker-days in
2021-02-17..2022-12-30 that (a) have ``quote_askprice`` rows that date and
(b) pass a band-consistency screen (the published ceiling really is 7% above
the reference), which excludes ticker-days whose bands belong to a different
limit regime.

**Two tick arms, because only one of them is comparable to the bar.**

``locked_at_close`` uses the last ask of the session: directly comparable to
"the closing print was at the ceiling", and the arm the divergence figure
should be read from.

``locked_all_session`` uses the minimum ask over the whole day, i.e. nothing
was ever on offer below the cap. It is strictly stronger than the bar proxy
and is reported for contrast, not as the comparison.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import duckdb

__all__ = ['DivergenceResult', 'measure_bar_vs_tick']

START, END = '2021-02-17', '2022-12-31'
BAND_TOLERANCE = 0.004


@dataclass(frozen=True)
class DivergenceResult:
    population: str
    n: int
    bar_blocked: int
    tick_blocked_at_close: int
    tick_blocked_all_session: int
    both: int
    bar_only: int
    tick_only: int
    agreement: Decimal

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out['agreement'] = float(self.agreement)
        out['backs'] = (
            'methodological result: how far a daily-bar proxy for a band lock '
            'diverges from the observed order book'
        )
        return out


def _reader(root: Path, table: str, suffix: str = '.parquet') -> str:
    parquet = root / f'{table}{suffix}'
    if parquet.exists():
        return f"read_parquet('{parquet}')"
    return f"read_csv_auto('{root / (table + '.csv')}')"


def measure_bar_vs_tick(data_root: str, tick_root: str) -> DivergenceResult:
    """Compare inferred and observed locks on one population."""
    root, archive = Path(data_root), Path(tick_root)
    conn = duckdb.connect()

    ask = f"read_csv_auto('{archive / 'quote_askprice.csv'}')"
    sql = f"""
        WITH eligible AS (
            SELECT c.tickersymbol, c.datetime, c.price AS close,
                   ce.price AS ceiling
            FROM {_reader(root, 'quote_close')} c
            JOIN {_reader(root, 'quote_ceil')}  ce USING (datetime, tickersymbol)
            JOIN {_reader(root, 'quote_floor')} fl USING (datetime, tickersymbol)
            JOIN {_reader(root, 'quote_reference')} rf USING (datetime, tickersymbol)
            JOIN {_reader(root, 'quote_ticker')} tk USING (tickersymbol)
            WHERE tk.exchangeid = 'HSX' AND tk.instrumenttype = 'stock'
              AND c.datetime >= '{START}' AND c.datetime < '{END}'
              AND ce.price >= fl.price
              AND rf.price > 0
              AND abs(ce.price / rf.price - 1.07) < {BAND_TOLERANCE}
        ), ladder AS (
            SELECT tickersymbol, CAST(datetime AS DATE) AS d, datetime, price,
                   -- Deterministic tie-break. arg_max() picks arbitrarily
                   -- among rows sharing the max timestamp, which makes a
                   -- pinned test non-reproducible across runs.
                   row_number() OVER (
                       PARTITION BY tickersymbol, CAST(datetime AS DATE)
                       ORDER BY datetime DESC, price ASC
                   ) AS rn
            FROM {ask}
            WHERE datetime >= '{START}' AND datetime < '{END}'
        ), book AS (
            SELECT tickersymbol, d,
                   min(price) AS min_ask,
                   -- the last ask of the session, comparable to a closing print
                   min(price) FILTER (WHERE rn = 1) AS closing_ask
            FROM ladder
            GROUP BY 1, 2
        )
        SELECT count(*) AS n,
               sum(CASE WHEN e.close = e.ceiling THEN 1 ELSE 0 END) AS bar_blocked,
               sum(CASE WHEN b.closing_ask >= e.ceiling THEN 1 ELSE 0 END)
                   AS tick_close,
               sum(CASE WHEN b.min_ask >= e.ceiling THEN 1 ELSE 0 END)
                   AS tick_session,
               sum(CASE WHEN e.close = e.ceiling AND b.closing_ask >= e.ceiling
                        THEN 1 ELSE 0 END) AS both
        FROM eligible e
        JOIN book b ON b.tickersymbol = e.tickersymbol AND b.d = e.datetime
    """
    n, bar_blocked, tick_close, tick_session, both = conn.execute(sql).fetchone()
    n = int(n or 0)
    bar_blocked, tick_close = int(bar_blocked or 0), int(tick_close or 0)
    tick_session, both = int(tick_session or 0), int(both or 0)
    agree = n - (bar_blocked - both) - (tick_close - both)

    return DivergenceResult(
        population=(
            f'HSX stock ticker-days {START}..{END} with an ask ladder and a '
            f'7% band (tolerance {BAND_TOLERANCE})'
        ),
        n=n, bar_blocked=bar_blocked, tick_blocked_at_close=tick_close,
        tick_blocked_all_session=tick_session, both=both,
        bar_only=bar_blocked - both, tick_only=tick_close - both,
        agreement=Decimal(agree) / Decimal(n) if n else Decimal('0'),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--tick-root', required=True)
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()

    r = measure_bar_vs_tick(args.data_root, args.tick_root)
    print(f'population : {r.population}')
    print(f'n          : {r.n:,}')
    print(f'bar-blocked      : {r.bar_blocked:,}  (close printed at the ceiling)')
    print(f'tick, at close   : {r.tick_blocked_at_close:,}  '
          f'(no ask below the ceiling at the close) <- comparable arm')
    print(f'tick, all session: {r.tick_blocked_all_session:,}  '
          f'(no ask below the ceiling all day) <- strictly stronger')
    print(f'both             : {r.both:,}')
    print(f'bar only         : {r.bar_only:,}   inferred a lock the closing '
          f'book contradicts')
    print(f'tick only        : {r.tick_only:,}   a lock the daily bar cannot see')
    print(f'agreement        : {float(r.agreement):.4%}')
    if args.json:
        args.json.write_text(json.dumps(r.to_dict(), indent=2))
        print(f'wrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
