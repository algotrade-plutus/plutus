"""A MarketDataSource backed by plutus.datahub (daily resolution).

Four behaviours are deliberate and load-bearing:

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
* **The data contract is declared, not implied.** :data:`DataHubSource.SERVES`
  and :data:`DataHubSource.WITHHELD` name every field this source can and
  cannot answer, and :meth:`DataHubSource.interval` stamps the second set onto
  every interval it returns. A policy that needs a withheld field therefore
  returns ``INDETERMINATE`` naming it, and the session counts it -- rather
  than the field being quietly ``None`` and the absence unmeasured.

Volume, and why it was missing
------------------------------------------------------------------------
This source used to serve snapshots only, so ``ExchangeSession._interval_for``
synthesised an interval and named ``VOLUME`` missing on every bar. The
consequence was not cosmetic: ``participation_cap`` returns ``None`` without
volume, so ``HardFillPolicy`` -- and any config-built ``probabilistic`` or
``soft``, since ``FillPolicyConfig`` always carries a cap -- answered
``INDETERMINATE`` *wherever it would otherwise have filled*. The conservative
arm produced a zero-trade backtest, which left ``soft`` uncapped as the only
policy that ran. That was reported as a property of the corpus. It is a
property of this adapter: ``quote_dailyvolume`` is on disk next to
``quote_close``.

It is not on disk for everything, and the coverage is stated rather than
assumed. Measured over the Parquet root on this machine, 2021-01-01 to
2022-12-31: **523,619 of 832,752 ticker-days** carrying a close also carry a
daily volume (62.9%). The gap is almost entirely instruments that have no
volume to publish -- every 7-character symbol, i.e. the indices, has zero
coverage -- and every liquid name checked (ACB, FPT, HPG, MWG, SSI, VIC, and
the VN30 futures) has 499 of 499. Where the row is absent, ``VOLUME`` is named
missing and a capped policy is ``INDETERMINATE`` exactly as before. Nothing is
defaulted to zero: a zero volume is a market fact ("nothing traded") and an
absent row is our ignorance, and collapsing the second into the first would
turn a missing row into a definite no-fill.

**Which table, and a correction.** The daily volume in the Parquet corpus is
``quote_dailyvolume`` (columns ``datetime``/``tickersymbol``/``quantity``).
``quote_total`` and ``quote_matchedvolume`` -- the intraday cumulative and
per-print streams -- are **not in the Parquet root at all**; they exist only
in the raw tick archive, which
:class:`~plutus.market.adapters.tick.TickSource` reads. A daily source cannot
take the last value of an intraday stream without reading the whole tick
archive per bar, and does not need to: ``quote_dailyvolume`` is the published
daily figure directly.

**What is still withheld, and it is the larger absence.** ``OPEN``, ``HIGH``
and ``LOW`` are *also* on disk -- ``quote_open``, and ``quote_max`` /
``quote_min`` for the daily extremes (``quote_high``/``quote_low`` are
intraday running streams keyed by timestamp, not daily bars). They are not
wired here, so an order's price test still falls back to the close alone and
``hard`` cannot return a definite ``NO_FILL`` for a limit the day's low never
reached. That is a real remaining gap, it is named in :data:`WITHHELD` and
counted on every fill through ``interval.missing``, and it is deliberately not
closed in the same change as volume: wiring the extremes moves decisions in
*both* directions (unproven becomes filled, and unproven becomes definitely
not filled) and deserves to be measured on its own.
"""

import calendar
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import (Callable, ClassVar, Dict, FrozenSet, Iterator, List,
                    Optional, Tuple, Union)

import duckdb

from plutus.core.constant import (
    DS, HNX, HSX, UPCOM, VietnamMarketConstant, is_covered_warrant, is_etf,
)
from plutus.datahub.config import DataHubConfig
from plutus.market.protocol import (
    BandSource, InstrumentKind, InstrumentSpec, LockEvidence, MarketState,
    Resolution, SessionPhase, Side,
)
from plutus.market.session.types import DataField, MarketInterval

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
    """Daily-resolution MarketDataSource + IntervalSource over the corpus.

    It satisfies ``session.exchange.IntervalSource`` structurally -- see
    :meth:`interval` -- so the session serves its intervals verbatim instead of
    synthesising one from a snapshot.
    """

    #: The resolutions this source can serve an interval for, declared so the
    #: session can refuse a configuration it cannot run **at construction**.
    #:
    #: :meth:`interval` raises on anything else, and raising is right -- see
    #: its docstring on why an unserveable resolution is not an absence. But
    #: raising is only right at the *right time*: ``resolution: tick`` with
    #: this adapter used to build, accept orders, encumber the cash for them,
    #: and then raise out of the first ``advance_to`` that had a live order,
    #: because ``ExchangeSession._interval_for`` calls this method with the
    #: session's resolution and catches nothing. Reading this set at
    #: construction turns that crash into a refused config, which is the same
    #: answer delivered before it costs anything.
    #:
    #: A source that declares nothing is not checked, and the session says so:
    #: this is an optional declaration, not a protocol member, because adding
    #: one to ``IntervalSource`` would drop every source that does not have it
    #: out of the ``isinstance`` and silently downgrade it to synthesised
    #: intervals.
    SERVES_RESOLUTIONS: ClassVar[FrozenSet[Resolution]] = frozenset({
        Resolution.DAILY,
    })

    #: The data-contract fields this source can answer at daily resolution.
    #: Declared so that "what this adapter serves" is a checkable fact rather
    #: than something a reader infers from a SELECT clause.
    SERVES: ClassVar[FrozenSet[DataField]] = frozenset({
        DataField.LAST, DataField.CLOSE, DataField.VOLUME,
        DataField.REFERENCE, DataField.CEILING, DataField.FLOOR,
        DataField.SESSION_PHASE,
    })

    #: The fields it cannot, named on **every** interval it serves so that a
    #: policy needing one returns ``INDETERMINATE`` naming it and the session
    #: counts it. ``VOLUME`` is not here: it is served where the corpus has a
    #: row and added to ``missing`` per-bar where it does not, which is the
    #: only shape that can tell "this source never has it" from "this bar does
    #: not". See the module docstring for why ``OPEN``/``HIGH``/``LOW`` are
    #: still on this list even though the corpus holds them.
    #:
    #: ``BOOK`` and ``BOOK_SIZE`` are permanent for this source: a daily bar
    #: has no book, and ``quote_asksize``/``quote_bidsize`` are 0-row in both
    #: corpus roots so even the tick adapter cannot supply sizes.
    WITHHELD: ClassVar[FrozenSet[DataField]] = frozenset({
        DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.BOOK_SIZE,
    })

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
        return iter(state for state, _ in self._fetch(ticker, start, end, close))

    def _fetch(self, ticker, start, end,
               close) -> List[Tuple[MarketState, Optional[int]]]:
        """``(state, volume)`` per bar. Volume is ``None`` where absent.

        The volume rides alongside the state rather than inside it because
        ``MarketState`` is a *snapshot* type and a day's matched volume is an
        interval quantity: putting it on the snapshot would invite a caller to
        read "the volume at 10:03" off a field that means the whole session.
        :meth:`interval` is the type that can hold it honestly.
        """
        ceil_r = self._reader('ceiling_price')
        floor_r = self._reader('floor_price')
        ref_r = self._reader('ref_price')
        vol_r = self._reader('daily_volume')

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

        # The day's matched volume. LEFT JOIN, never INNER: 37% of ticker-days
        # in the Parquet root carry a close and no volume row, and an inner
        # join would drop those bars entirely -- turning a missing field into a
        # missing *day*, which no policy could name and no report could count.
        if vol_r:
            select.append('vo.quantity AS volume')
            joins.append(
                f'LEFT JOIN {vol_r} vo USING (datetime, tickersymbol)')
        else:
            select.append('NULL AS volume')

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
        return [(self._build_state(ticker, *row[:-1], spec),
                 None if row[-1] is None else int(row[-1]))
                for row in rows]

    def state_at(self, ticker: str, ts: datetime) -> Optional[MarketState]:
        day = ts.date() if isinstance(ts, datetime) else ts
        for state in self.states(ticker, day, day + timedelta(days=1)):
            return state
        return None

    # -- intervals ---------------------------------------------------------

    def interval(
        self,
        ticker: str,
        start: datetime,
        end: datetime,
        *,
        resolution: Resolution = Resolution.DAILY,
    ) -> Optional[MarketInterval]:
        """The daily bar over ``[start, end)``, or ``None`` if the day is absent.

        This is the ``session.exchange.IntervalSource`` seam. Implementing it
        is what lets ``participation_cap`` compute anything at all on this
        corpus: without it the session synthesises an interval from
        :meth:`state_at` and names ``VOLUME`` missing on every bar, so every
        capped policy answers ``INDETERMINATE`` wherever it would have filled.

        The :class:`~plutus.market.protocol.MarketState` carried is the **same
        object** :meth:`state_at` would return for this instant, built by the
        same :meth:`_build_state`. That is not an optimisation: the session
        judges admission on the state from ``state_at`` and fills on the state
        inside the interval, and two states built by two paths would let
        ``submit()`` and the fill policy disagree about the band, the lock or
        the phase with nothing saying so.

        ``missing`` is :data:`WITHHELD` plus whatever this particular bar could
        not supply -- ``VOLUME`` where the corpus has no row, and
        ``CLOSE``/``LAST`` where there is no price. Nothing is defaulted; see
        the module docstring on why an absent volume row is not zero.

        Returns ``None`` when the corpus has no bar for ``start``'s date, which
        is the contract's "absent" and leaves the session free to synthesise.
        Absent is different from *unserveable*: a resolution this source cannot
        answer raises instead, because a session running at
        ``Resolution.TICK`` against a daily adapter is an integration bug and a
        ``None`` there would be silently answered with a synthesised bar that
        looked fine.

        Raises:
            ValueError: on a non-daily resolution, or on an interval spanning
                more than one day. A daily bar's volume is one session's, and
                serving it for a multi-day or one-second window would attribute
                a whole day's liquidity to a window that did not have it --
                which is the permissive direction, the one a backtest must not
                err in.
        """
        if resolution is not Resolution.DAILY:
            raise ValueError(
                f'DataHubSource serves Resolution.DAILY intervals only, got '
                f'{resolution}; a daily bar carries one session\'s volume and '
                f'serving it for a {resolution.value} window would attribute '
                f'the whole day\'s liquidity to it. Use '
                f'plutus.market.adapters.tick.TickSource for Resolution.TICK'
            )

        day = start.date() if isinstance(start, datetime) else start
        end_day = end.date() if isinstance(end, datetime) else end
        if not (start < end) or end_day > day + timedelta(days=1):
            raise ValueError(
                f'DataHubSource serves one daily bar per interval; '
                f'[{start}, {end}) spans more than one day and this source '
                f'cannot aggregate volume across sessions honestly'
            )

        close = self._reader('close_price')
        if close is None:
            return None
        rows = self._fetch(ticker, day, day + timedelta(days=1), close)
        if not rows:
            return None
        state, volume = rows[0]

        missing = set(self.WITHHELD)
        if volume is None:
            missing.add(DataField.VOLUME)
        if state.last is None:
            missing.add(DataField.CLOSE)
            missing.add(DataField.LAST)

        return MarketInterval(
            ticker=ticker,
            start=start if isinstance(start, datetime) else (
                datetime(start.year, start.month, start.day)),
            end=end if isinstance(end, datetime) else (
                datetime(end.year, end.month, end.day)),
            resolution=Resolution.DAILY,
            state=state,
            # A daily bar's close *is* its last matched price, which is what
            # ``quote_close`` holds; open/high/low stay unserved and named.
            close=state.last,
            volume=volume,
            book=None,
            missing=frozenset(missing),
        )

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

        # Shares the classifier with the tick-size rule so the two cannot drift
        # apart. The old test here -- 8 chars starting C, E or F -- also caught
        # closed-end fund certificates (FUCTVGF1, FUCVREIT) and typed them
        # WARRANT. They now fall through to the ticker master below, which
        # types them FUND, and to the banded tick grid, which is the grid their
        # prices actually lie on.
        if is_covered_warrant(ticker) or is_etf(ticker):
            return InstrumentSpec(
                ticker=ticker, exchange_code='HSX',
                kind=(InstrumentKind.WARRANT if is_covered_warrant(ticker)
                      else InstrumentKind.FUND),
                trading_unit=100,
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
