"""A MarketDataSource backed by plutus.datahub (daily resolution).

Three behaviours are deliberate and load-bearing:

* **Session is set, never inferred.** A daily bar's timestamp is midnight, and
  the coded ``before_trading_session`` reports current at midnight, so
  inferring the phase would mark every bar pre-open and the session rule would
  reject an entire daily measurement.
* **Bands carry provenance.** Only ~88% of 2021 stock ticker-days have a
  published ceiling. Where one is absent and a reference exists, bands are
  reconstructed and tagged ``RECONSTRUCTED``; where neither exists the state is
  tagged ``ABSENT`` and the band rules return INDETERMINATE.
* **Lock evidence is labelled an inference.** ``last == ceiling`` on a daily
  bar is a proxy for a locked book, not an observation of one.
"""

import calendar
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Callable, Dict, Iterator, List, Optional, Tuple, Union

import duckdb

from plutus.core.constant import DS, HNX, HSX, UPCOM, VietnamMarketConstant
from plutus.datahub.config import DataHubConfig
from plutus.market.protocol import (
    BandSource, InstrumentKind, InstrumentSpec, LockEvidence, MarketState,
    Resolution, SessionPhase, Side,
)

__all__ = ['DataHubSource', 'reconstruct_bands', 'truncate_to_tick',
           'round_up_to_tick', 'third_thursday']

_SPECS = {'HSX': HSX, 'HNX': HNX, 'UPCOM': UPCOM, 'HNXDS': DS}
_FUTURES_RE = re.compile(r'^(VN30F|VN100F|GB\d)')
_CONTRACT_MONTH_RE = re.compile(r'^VN30F(\d{2})(\d{2})$')


def truncate_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    """Largest multiple of ``tick`` at or below ``value``."""
    return (value / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


def round_up_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    """Smallest multiple of ``tick`` at or above ``value``."""
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


def reconstruct_bands(
    reference: Optional[Decimal],
    limit: Decimal,
    tick_fn: Callable[[str, Decimal], Optional[Decimal]],
    ticker: str,
) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """Derive ``(ceiling, floor)`` from a reference price and a daily limit.

    The tick is keyed on the **resulting band price**, not the reference. That
    detail is what makes the rule work: DSN on 2022-04-25 has reference 48.40
    (a 0.05-tick price) but its ceiling 51.70 lands above 50 and so sits on the
    0.1 grid. Reference-keyed ticks score 93.2%/96.7% against 95.7%/99.2% for
    result-keyed on HSX. Round-to-nearest is decisively wrong (47.8-58.0%
    against 91.3-93.3% for truncation).

    Returns ``(None, None)`` when no reference is available.
    """
    if reference is None:
        return None, None

    raw_ceiling = reference * (Decimal('1') + limit)
    raw_floor = reference * (Decimal('1') - limit)

    ceiling_tick = tick_fn(ticker, raw_ceiling)
    floor_tick = tick_fn(ticker, raw_floor)
    if ceiling_tick is None or floor_tick is None:
        return None, None

    return (truncate_to_tick(raw_ceiling, ceiling_tick),
            round_up_to_tick(raw_floor, floor_tick))


def third_thursday(year: int, month: int) -> date:
    """VN30 futures expire on the third Thursday of the contract month."""
    first = next(day for day in range(1, 8)
                 if date(year, month, day).weekday() == calendar.THURSDAY)
    return date(year, month, first + 14)


class DataHubSource:
    """Daily-resolution MarketDataSource over the datahub corpus."""

    def __init__(self, config: DataHubConfig,
                 resolution: Resolution = Resolution.DAILY):
        if resolution is not Resolution.DAILY:
            raise ValueError(
                'DataHubSource serves daily resolution only; use '
                'plutus.market.adapters.tick.TickSource for Resolution.TICK'
            )
        self.config = config
        self.resolution = resolution
        self._conn = duckdb.connect()
        self._instruments: Dict[str, InstrumentSpec] = {}

    @classmethod
    def for_root(cls, data_root: str) -> 'DataHubSource':
        return cls(DataHubConfig(data_root=data_root))

    # -- reading -----------------------------------------------------------

    def _reader(self, field: str) -> Optional[str]:
        if not self.config.has_field(field):
            return None
        path = self.config.get_file_path(field)
        fn = 'read_parquet' if path.suffix == '.parquet' else 'read_csv_auto'
        return f"{fn}('{path}')"

    def states(
        self,
        ticker: str,
        start: Union[date, datetime],
        end: Union[date, datetime],
        *,
        resolution: Resolution = Resolution.DAILY,
    ) -> Iterator[MarketState]:
        """States over ``[start, end)``. End is exclusive."""
        if resolution is not Resolution.DAILY:
            raise ValueError('DataHubSource serves Resolution.DAILY only')

        close = self._reader('close_price')
        if close is None:
            return iter(())
        return iter(self._fetch(ticker, start, end, close))

    def _fetch(self, ticker, start, end, close) -> List[MarketState]:
        ceil_r = self._reader('ceiling_price')
        floor_r = self._reader('floor_price')
        ref_r = self._reader('ref_price')

        select = ['c.datetime AS ts', 'c.price AS last']
        joins = []
        for reader, alias, label in ((ceil_r, 'ce', 'ceiling'),
                                     (floor_r, 'fl', 'floor'),
                                     (ref_r, 'rf', 'reference')):
            if reader:
                select.append(f'{alias}.price AS {label}')
                joins.append(
                    f'LEFT JOIN {reader} {alias} USING (datetime, tickersymbol)')
            else:
                select.append(f'NULL AS {label}')

        sql = f"""
            SELECT {', '.join(select)}
            FROM {close} c
            {' '.join(joins)}
            WHERE c.tickersymbol = ?
              AND c.datetime >= ?
              AND c.datetime < ?
            ORDER BY c.datetime
        """
        rows = self._conn.execute(
            sql, [ticker, str(start)[:10], str(end)[:10]]).fetchall()

        spec = self.instrument(ticker)
        return [self._build_state(ticker, *row, spec) for row in rows]

    def state_at(self, ticker: str, ts: datetime) -> Optional[MarketState]:
        day = ts.date() if isinstance(ts, datetime) else ts
        for state in self.states(ticker, day, day + timedelta(days=1)):
            return state
        return None

    # -- assembly ----------------------------------------------------------

    def _build_state(self, ticker, ts, last, ceiling, floor, reference,
                     spec: InstrumentSpec) -> MarketState:
        def dec(v):
            return None if v is None else Decimal(str(v))

        last_d, ceiling_d = dec(last), dec(ceiling)
        floor_d, reference_d = dec(floor), dec(reference)

        if ceiling_d is not None and floor_d is not None:
            band_source = BandSource.PUBLISHED
        else:
            exchange_spec = _SPECS.get(spec.exchange_code)
            tick_fn = exchange_spec.tick_size_function if exchange_spec else None
            if reference_d is not None and tick_fn is not None:
                ceiling_d, floor_d = reconstruct_bands(
                    reference_d, spec.daily_trading_limit, tick_fn, ticker)
                band_source = (BandSource.RECONSTRUCTED if ceiling_d is not None
                               else BandSource.ABSENT)
            else:
                band_source = BandSource.ABSENT

        # A daily bar cannot observe a book; last == band is an inference.
        locked_side, lock_evidence = None, LockEvidence.UNKNOWN
        if last_d is not None and ceiling_d is not None and last_d == ceiling_d:
            locked_side, lock_evidence = Side.BUY, LockEvidence.BAR_PROXY
        elif last_d is not None and floor_d is not None and last_d == floor_d:
            locked_side, lock_evidence = Side.SELL, LockEvidence.BAR_PROXY

        return MarketState(
            ticker=ticker,
            ts=(ts if isinstance(ts, datetime)
                else datetime(ts.year, ts.month, ts.day)),
            reference=reference_d, ceiling=ceiling_d, floor=floor_d,
            band_source=band_source, last=last_d, book=None,
            # Set, never inferred: a daily ts is midnight.
            session=SessionPhase.CONTINUOUS,
            foreign_room=None,
            locked_side=locked_side, lock_evidence=lock_evidence,
        )

    # -- instruments -------------------------------------------------------

    def instrument(self, ticker: str) -> InstrumentSpec:
        """Never raises. Unknown tickers return ``InstrumentKind.UNKNOWN``.

        Fallback chain, in order: futures code prefix, 8-char C/E/F
        warrant/ETF, ticker-master lookup, then UNKNOWN. The master carries no
        ``future`` type and no HNXDS rows, so derivatives can only be typed by
        prefix; and it stores only the *latest* exchange assignment, so
        ``exchange_code`` is unreliable for historical by-exchange work.
        """
        if ticker not in self._instruments:
            self._instruments[ticker] = self._resolve_instrument(ticker)
        return self._instruments[ticker]

    @staticmethod
    def _limit_for(code: str) -> Decimal:
        return Decimal(str(VietnamMarketConstant.DAILY_TRADING_LIMIT[code]))

    def _resolve_instrument(self, ticker: str) -> InstrumentSpec:
        if _FUTURES_RE.match(ticker):
            month = _CONTRACT_MONTH_RE.match(ticker)
            expiry = None
            if month:
                yy, mm = int(month.group(1)), int(month.group(2))
                if 1 <= mm <= 12:
                    expiry = third_thursday(2000 + yy, mm)
            return InstrumentSpec(
                ticker=ticker, exchange_code='HNXDS',
                kind=InstrumentKind.FUTURE, trading_unit=1,
                daily_trading_limit=self._limit_for('HNXDS'),
                multiplier=Decimal('100000'), expiry=expiry, underlying='VN30',
            )

        if len(ticker) == 8 and ticker[0] in ('C', 'E', 'F'):
            return InstrumentSpec(
                ticker=ticker, exchange_code='HSX',
                kind=InstrumentKind.WARRANT, trading_unit=100,
                daily_trading_limit=self._limit_for('HSX'),
            )

        master = self._reader('ticker_metadata')
        if master is not None:
            row = self._conn.execute(
                f'SELECT exchangeid, instrumenttype FROM {master} '
                f'WHERE tickersymbol = ? LIMIT 1', [ticker]).fetchone()
            if row and row[0] in _SPECS:
                kinds = {'stock': InstrumentKind.STOCK,
                         'warrant': InstrumentKind.WARRANT,
                         'fund': InstrumentKind.FUND,
                         'index': InstrumentKind.INDEX,
                         'futures': InstrumentKind.FUTURE}
                return InstrumentSpec(
                    ticker=ticker, exchange_code=row[0],
                    kind=kinds.get(row[1], InstrumentKind.UNKNOWN),
                    trading_unit=VietnamMarketConstant.TRADING_UNIT[row[0]],
                    daily_trading_limit=self._limit_for(row[0]),
                )

        return InstrumentSpec(
            ticker=ticker, exchange_code='HSX', kind=InstrumentKind.UNKNOWN,
            trading_unit=100, daily_trading_limit=self._limit_for('HSX'),
        )
