"""How often would the exchange call a front-month VN30F long? (RETIRED path.)

**Retired from the paper's measurement path (W4).** This module applies a
**flat** VSD initial-margin rate and never settles variation margin in cash, so
its incidence is not the Vietnamese regime's -- no regime has a flat maintenance
rate. ``reproduce_measurements.py`` now measures margin incidence with
``margin_incidence_account.measure_account_margin_incidence``: the real
``DerivativesAccount`` on the **dated** VSD series (10 -> 13 -> 17%) with MUST #4
daily variation-margin cash settlement. This module is kept only as the legacy
comparator these two are contrasted against.

The entry policy is part of the result and is stated in the output: enter long
one contract at each session close of the front-month series, hold H sessions
or to expiry, whichever comes first.

Front-month membership comes from ``quote_futurecontractcode`` where
``futurecode = 'VN30F1M'``, which begins 2021-06-01 (VN30F2101-2105 are absent
from the corpus entirely, so no front-month series can start earlier).

The margin rate here is a **flat modelling assumption** -- a fixed VSD initial
rate plus a 5% broker buffer, swept across a range -- which is precisely why the
path is retired: the flat rate is not dated and no maintenance ratio exists in
either regime. The dated 10/13/17% series lives in ``plutus.market.margin.
vsd_initial_margin`` and is what the account path applies.

Do not report a buy-and-hold-to-expiry figure as an incidence: holding every
contract from first close to last calls all of them at these rates, which is a
monotonicity fixture rather than a publishable rate.
"""

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

from plutus.market.exchanges.derivatives import HNXDSExchange
from plutus.market.margin import MarginConfig
from plutus.market.protocol import MarketState, Position, SessionPhase, Side
from plutus.market.verdicts import PositionEventKind

__all__ = ['MarginIncidenceResult', 'measure_margin_incidence']

FRONT_MONTH_CODE = 'VN30F1M'


@dataclass(frozen=True)
class MarginIncidenceResult:
    entries: int
    called: int
    liquidated: int
    call_rate: Decimal
    liquidation_rate: Decimal
    holding_days: int
    initial_rate: Decimal
    contracts: int

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for key in ('call_rate', 'liquidation_rate', 'initial_rate'):
            out[key] = float(getattr(self, key))
        out['entry_policy'] = (
            'long 1 front-month contract at each session close; hold '
            f'{self.holding_days} sessions or to expiry'
        )
        out['backs'] = (
            'paper derivatives headline: share of front-month longs the '
            'exchange would margin-call'
        )
        return out


def _reader(root: Path, table: str) -> str:
    parquet = root / f'{table}.parquet'
    if parquet.exists():
        return f"read_parquet('{parquet}')"
    return f"read_csv_auto('{root / (table + '.csv')}')"


def _front_month_series(root: Path) -> Dict[str, List[Tuple[date, Decimal]]]:
    """Per-contract close series, restricted to days it was the front month."""
    conn = duckdb.connect()
    rows = conn.execute(f"""
        SELECT f.tickersymbol, c.datetime, c.price
        FROM {_reader(root, 'quote_futurecontractcode')} f
        JOIN {_reader(root, 'quote_close')} c
          ON c.tickersymbol = f.tickersymbol AND c.datetime = f.datetime
        WHERE f.futurecode = ?
        ORDER BY f.tickersymbol, c.datetime
    """, [FRONT_MONTH_CODE]).fetchall()

    series: Dict[str, List[Tuple[date, Decimal]]] = defaultdict(list)
    for ticker, day, price in rows:
        series[ticker].append((day, Decimal(str(price))))
    return dict(series)


def measure_margin_incidence(
    data_root: str,
    *,
    holding_days: int,
    initial_rate: Optional[Decimal] = None,
) -> MarginIncidenceResult:
    """Measure front-month margin-call incidence at one holding period."""
    series = _front_month_series(Path(data_root))

    config = MarginConfig.VN30F_DEFAULT
    if initial_rate is not None:
        config = config.with_initial(initial_rate)
    exchange = HNXDSExchange(margin_config=config)

    entries = called = liquidated = 0
    for ticker, observations in series.items():
        for i in range(len(observations) - 1):
            window = observations[i:i + holding_days + 1]
            if len(window) < 2:
                continue
            entry_day, entry_price = window[0]
            path = [
                MarketState(
                    ticker=ticker,
                    ts=datetime.combine(day, datetime.min.time()),
                    last=price, session=SessionPhase.CONTINUOUS,
                )
                for day, price in window[1:]
            ]
            position = Position(
                ticker=ticker, exchange_code='HNXDS', side=Side.BUY,
                quantity=1, entry_price=entry_price,
                entry_ts=datetime.combine(entry_day, datetime.min.time()),
                multiplier=config.default_multiplier,
            )
            viability = exchange.sustains(position, path)
            entries += 1
            if viability.first(PositionEventKind.MARGIN_CALL) is not None:
                called += 1
            if viability.first(PositionEventKind.FORCED_LIQUIDATION) is not None:
                liquidated += 1

    denom = Decimal(entries) if entries else Decimal('1')
    return MarginIncidenceResult(
        entries=entries, called=called, liquidated=liquidated,
        call_rate=Decimal(called) / denom,
        liquidation_rate=Decimal(liquidated) / denom,
        holding_days=holding_days, initial_rate=config.initial_rate,
        contracts=len(series),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--json', type=Path, default=None)
    parser.add_argument('--sweep', action='store_true',
                        help='also report incidence across a range of rates')
    args = parser.parse_args()

    results: Dict[str, Any] = {}
    print(f"{'hold':>5} {'entries':>8} {'called':>7} {'call%':>8} "
          f"{'liq':>5} {'liq%':>7}")
    for hold in (5, 10, 20):
        r = measure_margin_incidence(args.data_root, holding_days=hold)
        results[f'hold_{hold}'] = r.to_dict()
        print(f'{hold:>5} {r.entries:>8,} {r.called:>7,} '
              f'{float(r.call_rate):>7.2%} {r.liquidated:>5,} '
              f'{float(r.liquidation_rate):>6.2%}')

    if args.sweep:
        print('\nsensitivity to the posted initial rate (hold=10):')
        for rate in ('0.150', '0.175', '0.200', '0.225', '0.250', '0.300'):
            r = measure_margin_incidence(args.data_root, holding_days=10,
                                         initial_rate=Decimal(rate))
            results[f'sweep_{rate}'] = r.to_dict()
            marker = '  <- published' if rate == '0.225' else ''
            print(f'  {rate}  call {float(r.call_rate):>7.2%}  '
                  f'liq {float(r.liquidation_rate):>6.2%}{marker}')

    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f'\nwrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
