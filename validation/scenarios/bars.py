"""A corpus-backed data source that can answer the questions a fill policy asks.

Why this exists, stated plainly, because it looks like a workaround and is not:

**The shipped ``DataHubSource`` reads four of the corpus's columns and drops
the rest.** It selects ``quote_close``, ``quote_ceil``, ``quote_floor`` and
``quote_reference`` and nothing else (``adapters/datahub.py:135-165``). The
Parquet corpus on this machine also carries, for every ticker-day:

===================  =====================================================
``quote_open``       the day's opening price -- on HOSE, the ATO cross
``quote_max``        the day's **high**
``quote_min``        the day's **low**
``quote_dailyvolume``the day's matched volume
===================  =====================================================

``quote_high`` and ``quote_low`` are *not* those: they are intraday
running-extreme streams keyed by timestamp, which is why a join on the date
returns nothing and why they have been reported as empty. ``quote_max`` and
``quote_min`` are the daily bars, and they are complete -- 22 rows for HPG in
November 2022, one per session.

The consequence of the adapter dropping them is not cosmetic.
``ExchangeSession._interval_for`` synthesises an interval from ``state_at``
and names ``OPEN``, ``HIGH``, ``LOW``, ``VOLUME`` and ``BOOK_SIZE`` missing,
so ``HardFillPolicy`` cannot compute a participation cap and answers
``INDETERMINATE`` wherever it would otherwise fill. That has been reported as
a property of the corpus. It is a property of the adapter: the data is on
disk.

So this module implements the ``IntervalSource`` seam the session already
offers, over the same corpus, and serves what the corpus holds.

Three modelling choices are made here rather than in the simulator, and each
is a choice a reader may disagree with:

1. **The phase is resolved from the clock and the rulebook's own session
   table.** ``DataHubSource`` stamps every state ``CONTINUOUS`` because a
   daily bar is stamped midnight and inference would mark it pre-open. That is
   right for a daily clock and it makes the two call auctions unreachable: no
   ATO or ATC can ever be admitted, because ``legal_order_types(HSX,
   CONTINUOUS)`` does not contain them. A session run at ``Resolution.TICK``
   over a real intraday clock resolves the phase from
   ``RuleSet.session_schedule``, which is sourced; this source stamps the same
   answer on the state so the fill policy and admission agree. (They otherwise
   would not -- see :meth:`interval`.)

2. **What each phase's interval carries.** The opening auction is served the
   day's ``open`` and nothing else; the closing auction the day's ``close``;
   the continuous session the whole day's OHLCV. On HOSE the open *is* the ATO
   clearing price and the close *is* the ATC clearing price, because HOSE
   opens and closes with a call auction -- a fact about the market's
   structure rather than an assumption about the data.

   **The one case where that is not exact**, stated because it is invisible
   in a daily bar: if the opening auction produced no cross at all -- no
   crossing orders -- HOSE's published open is the first continuous match
   instead, and this source would serve it as an ATO clearing price. The
   corpus carries no auction volume, so the two cannot be told apart from it.
   On a name with 21m-99m shares a session, which is every fill leg in the
   scenario that uses this, an empty opening auction is not a live
   possibility; on an illiquid name it is, and a scenario that needs the
   distinction needs the tick tape.

   Auction volume is **not** in the corpus and is left ``None``, so a capped
   policy reports ``VOLUME`` missing for a cross rather than sizing it from
   the day's total.

3. **A lock is asserted only when the whole bar sits on the band.**
   ``DataHubSource`` infers ``locked_side`` from ``last == ceiling`` alone,
   and ``exchanges/equity.py``'s ``BAND_LOCK`` rule then refuses any order
   marketable into it. That inference over-asserts by about a factor of ten.
   Measured over HSX stocks in 2022, 91,999 ticker-days with volume:

   ==========================================  =======  ======
   ``close == ceiling`` (proxy says buy-locked)   3,726
   of which ``open == high == low == close``        365   9.8%
   ``close == floor`` (proxy says sell-locked)    5,304
   of which ``open == high == low == close``        426   8.0%
   ==========================================  =======  ======

   On the 3,361 ticker-days the proxy calls buy-locked and the bar does not,
   the day's low is on average **6.87% below the ceiling** -- nearly the whole
   band. HPG 2022-11-16 is one of them: close 13.35 = the ceiling, low 11.80,
   34.9 million shares, and a buy at the ceiling refused.

   With the full bar the question is answerable, so a lock is asserted here
   only when ``open == high == low == close`` and that price is the band.
   Everything else carries ``locked_side=None``. The divergence is measured
   by ``order_cycle.lock_proxy_divergence``, not hidden.

Nothing here is written back into the simulator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from plutus.market.protocol import (
    BandSource, InstrumentKind, InstrumentSpec, LockEvidence, MarketState,
    Resolution, SessionPhase, Side,
)
from plutus.market.session.types import DataField, MarketInterval, Venue

__all__ = ['Bar', 'CorpusBars', 'PhasedBarSource', 'HSX_SCHEDULE',
           'HNX_SCHEDULE', 'HNXDS_SCHEDULE', 'phase_at']


# --------------------------------------------------------------------------
# The bar
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Bar:
    """One ticker-day, as the corpus holds it. Every price a ``Decimal``."""

    ticker: str
    day: date
    open: Optional[Decimal]
    high: Optional[Decimal]
    low: Optional[Decimal]
    close: Optional[Decimal]
    volume: Optional[int]
    ceiling: Optional[Decimal]
    floor: Optional[Decimal]
    reference: Optional[Decimal]

    @property
    def traded(self) -> bool:
        """Whether anything matched. ``volume == 0`` is a real corpus value.

        On a zero-volume day the corpus still stamps ``open`` and ``close``
        (both equal to the reference), which is a synthetic print: nothing
        traded, so there is no cross price and no last price. Treating those
        as prices would fabricate a fill on a day with no trade, so
        :meth:`PhasedBarSource.interval` suppresses them.
        """
        return bool(self.volume)

    def full_bar_lock(self) -> Tuple[Optional[Side], LockEvidence]:
        """The locked side, asserted only when the whole bar sits on a band.

        Returns ``(None, UNKNOWN)`` otherwise -- including on a day whose
        *close* is the ceiling but whose low is not, which the shipped
        daily proxy calls a lock.
        """
        prices = (self.open, self.high, self.low, self.close)
        if any(p is None for p in prices) or len(set(prices)) != 1:
            return None, LockEvidence.UNKNOWN
        price = self.close
        if self.ceiling is not None and price == self.ceiling:
            return Side.BUY, LockEvidence.BAR_PROXY
        if self.floor is not None and price == self.floor:
            return Side.SELL, LockEvidence.BAR_PROXY
        return None, LockEvidence.UNKNOWN


# --------------------------------------------------------------------------
# The session clock
# --------------------------------------------------------------------------

#: The venue session tables, copied from ``rulebook._session_schedule_table``
#: so this module can answer "which phase" without constructing a ``RuleSet``
#: per call. Kept as data and asserted equal to the rulebook's own in
#: ``tests/validation/test_order_cycle.py`` -- if the rulebook moves, the test
#: fails rather than the two drifting apart.
HSX_SCHEDULE: Tuple[Tuple[SessionPhase, time, time], ...] = (
    (SessionPhase.NOON_BREAK, time(11, 30), time(13, 0)),
    (SessionPhase.OPENING_AUCTION, time(9, 0), time(9, 15)),
    (SessionPhase.CLOSING_AUCTION, time(14, 30), time(14, 45)),
    (SessionPhase.CONTINUOUS, time(9, 15), time(14, 30)),
)
HNX_SCHEDULE: Tuple[Tuple[SessionPhase, time, time], ...] = (
    (SessionPhase.NOON_BREAK, time(11, 30), time(13, 0)),
    (SessionPhase.CLOSING_AUCTION, time(14, 30), time(14, 45)),
    (SessionPhase.POST_CLOSE_PLO, time(14, 45), time(15, 0)),
    (SessionPhase.CONTINUOUS, time(9, 0), time(14, 30)),
)
HNXDS_SCHEDULE: Tuple[Tuple[SessionPhase, time, time], ...] = (
    (SessionPhase.NOON_BREAK, time(11, 30), time(13, 0)),
    (SessionPhase.OPENING_AUCTION, time(8, 45), time(9, 0)),
    (SessionPhase.CLOSING_AUCTION, time(14, 30), time(14, 45)),
    (SessionPhase.CONTINUOUS, time(9, 0), time(14, 30)),
)
UPCOM_SCHEDULE: Tuple[Tuple[SessionPhase, time, time], ...] = (
    (SessionPhase.NOON_BREAK, time(11, 30), time(13, 0)),
    (SessionPhase.CONTINUOUS, time(9, 0), time(15, 0)),
)

_SCHEDULES: Mapping[Venue, Tuple[Tuple[SessionPhase, time, time], ...]] = {
    Venue.HSX: HSX_SCHEDULE,
    Venue.HNX: HNX_SCHEDULE,
    Venue.HNXDS: HNXDS_SCHEDULE,
    Venue.UPCOM: UPCOM_SCHEDULE,
}


def phase_at(venue: Venue, clock: time) -> SessionPhase:
    """The phase, in the rulebook's own normative order.

    The noon break is tested first because ``continuous`` spans it; the
    auctions before ``continuous`` because HOSE's ATC begins at 14:30 exactly
    where the continuous window ends.
    """
    schedule = _SCHEDULES[venue]
    for phase, start, end in schedule:
        if start <= clock < end:
            return phase
    opens = min(start for _, start, _ in schedule)
    closes = max(end for _, _, end in schedule)
    if clock < opens:
        return SessionPhase.PRE_OPEN
    if clock >= closes:
        return SessionPhase.POST_CLOSE
    return SessionPhase.UNKNOWN


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

_FIELDS = (('quote_open', 'open', 'price'),
           ('quote_max', 'high', 'price'),
           ('quote_min', 'low', 'price'),
           ('quote_dailyvolume', 'volume', 'quantity'),
           ('quote_ceil', 'ceiling', 'price'),
           ('quote_floor', 'floor', 'price'),
           ('quote_reference', 'reference', 'price'))


class CorpusBars:
    """Daily OHLCV plus the published band, read once into memory.

    Read once because a scenario asks for the same handful of ticker-days
    hundreds of times as the clock steps, and a DuckDB round trip per
    ``state_at`` makes a run take minutes.
    """

    def __init__(self, root, tickers: Sequence[str], start: date,
                 end: date) -> None:
        import duckdb

        conn = duckdb.connect()
        rp = lambda name: f"read_parquet('{root}/{name}.parquet')"  # noqa: E731
        select = ['c.datetime AS d', 'c.tickersymbol AS t',
                  'c.price AS close']
        joins = []
        for parquet, label, column in _FIELDS:
            alias = label[:3]
            select.append(f'{alias}.{column} AS {label}')
            joins.append(f'LEFT JOIN {rp(parquet)} {alias} '
                         f'USING (datetime, tickersymbol)')
        sql = f"""
            SELECT {', '.join(select)}
            FROM {rp('quote_close')} c
            {' '.join(joins)}
            WHERE c.tickersymbol IN ?
              AND c.datetime >= ? AND c.datetime <= ?
            ORDER BY c.datetime
        """
        rows = conn.execute(sql, [list(tickers), str(start), str(end)]
                            ).fetchall()
        conn.close()

        def dec(value):
            return None if value is None else Decimal(str(value))

        self._bars: Dict[Tuple[str, date], Bar] = {}
        for (stamp, ticker, close, open_, high, low, volume, ceiling, floor,
             reference) in rows:
            day = stamp.date() if isinstance(stamp, datetime) else stamp
            self._bars[(ticker, day)] = Bar(
                ticker=ticker, day=day, open=dec(open_), high=dec(high),
                low=dec(low), close=dec(close),
                volume=None if volume is None else int(volume),
                ceiling=dec(ceiling), floor=dec(floor),
                reference=dec(reference))

    def get(self, ticker: str, day: date) -> Optional[Bar]:
        return self._bars.get((ticker, day))

    def days(self, ticker: str) -> Tuple[date, ...]:
        return tuple(sorted(day for (name, day) in self._bars if name == ticker))

    def __len__(self) -> int:
        return len(self._bars)


# --------------------------------------------------------------------------
# The source
# --------------------------------------------------------------------------

class PhasedBarSource:
    """``MarketDataSource`` + ``IntervalSource`` over :class:`CorpusBars`.

    The venue is supplied per ticker rather than read from the corpus's
    ``quote_ticker.exchangeid``: that column holds the ticker's *current*
    venue and would assign the wrong band, tick and lot to any name that has
    since transferred. A scenario states which venue it means and passes the
    matching ``VenueListing`` rows to the session, so the two agree.
    """

    def __init__(self, bars: CorpusBars, venues: Mapping[str, Venue], *,
                 kinds: Optional[Mapping[str, InstrumentKind]] = None,
                 expiries: Optional[Mapping[str, date]] = None,
                 lots: Optional[Mapping[str, int]] = None) -> None:
        self._bars = bars
        self._venues = dict(venues)
        self._kinds = dict(kinds or {})
        self._expiries = dict(expiries or {})
        self._lots = dict(lots or {})

    # -- MarketDataSource -------------------------------------------------

    def state_at(self, ticker: str, ts: datetime) -> Optional[MarketState]:
        bar = self._bars.get(ticker, ts.date())
        if bar is None:
            return None
        return self._state(bar, ts)

    def states(self, ticker: str, start, end, *,
               resolution: Resolution = Resolution.DAILY
               ) -> Iterator[MarketState]:
        """Half-open on ``[start, end)``, matching the adapter contract."""
        out: List[MarketState] = []
        for day in self._bars.days(ticker):
            stamp = datetime.combine(day, time.min)
            if start <= stamp < end:
                bar = self._bars.get(ticker, day)
                out.append(self._state(bar, stamp))
        return iter(out)

    def instrument(self, ticker: str) -> InstrumentSpec:
        venue = self._venues.get(ticker, Venue.HSX)
        kind = self._kinds.get(
            ticker,
            InstrumentKind.FUTURE if venue is Venue.HNXDS
            else InstrumentKind.STOCK)
        limits = {Venue.HSX: '0.07', Venue.HNX: '0.10',
                  Venue.UPCOM: '0.15', Venue.HNXDS: '0.07'}
        return InstrumentSpec(
            ticker=ticker, exchange_code=venue.value, kind=kind,
            trading_unit=self._lots.get(
                ticker, 1 if kind is InstrumentKind.FUTURE else 100),
            daily_trading_limit=Decimal(limits[venue]),
            multiplier=(Decimal('100000') if kind is InstrumentKind.FUTURE
                        else Decimal('1')),
            expiry=self._expiries.get(ticker))

    # -- IntervalSource ---------------------------------------------------

    def interval(self, ticker: str, start: datetime, end: datetime, *,
                 resolution: Resolution) -> Optional[MarketInterval]:
        """The bar this phase can support, with every absence named.

        **The session's own phase resolution does not reach here.**
        ``ExchangeSession._interval_for`` returns a served interval verbatim,
        so the phase the fill policy reads is the one on *this* state, not the
        one ``submit()`` resolved from the rulebook. The two are the same
        table (see :func:`phase_at`), which is what makes that safe -- and it
        is a real seam hazard for any adapter that stamps a constant phase,
        because admission would then judge in one phase and the fill in
        another.
        """
        bar = self._bars.get(ticker, start.date())
        if bar is None:
            return None
        state = self._state(bar, start)
        phase = state.session
        missing = {DataField.BOOK_SIZE}

        if phase is SessionPhase.OPENING_AUCTION:
            price = bar.open if bar.traded else None
            if price is None:
                missing.add(DataField.OPEN)
            # The corpus publishes no per-auction volume anywhere.
            missing |= {DataField.HIGH, DataField.LOW, DataField.VOLUME}
            return MarketInterval(
                ticker=ticker, start=start, end=end, resolution=resolution,
                state=state, open=price, close=price,
                missing=frozenset(missing))

        if phase is SessionPhase.CLOSING_AUCTION:
            price = bar.close if bar.traded else None
            if price is None:
                missing.add(DataField.CLOSE)
            missing |= {DataField.OPEN, DataField.HIGH, DataField.LOW,
                        DataField.VOLUME}
            return MarketInterval(
                ticker=ticker, start=start, end=end, resolution=resolution,
                state=state, close=price, missing=frozenset(missing))

        # Continuous, or a non-matching phase the policy will refuse anyway.
        # The whole day's bar is offered to an instant inside the day: an
        # over-generosity the daily resolution already declares, restated
        # here because at TICK resolution it is no longer implied by the
        # config.
        if not bar.traded:
            missing |= {DataField.OPEN, DataField.HIGH, DataField.LOW,
                        DataField.CLOSE, DataField.LAST}
            return MarketInterval(
                ticker=ticker, start=start, end=end, resolution=resolution,
                state=state, volume=bar.volume, missing=frozenset(missing))
        return MarketInterval(
            ticker=ticker, start=start, end=end, resolution=resolution,
            state=state, open=bar.open, high=bar.high, low=bar.low,
            close=bar.close, volume=bar.volume, missing=frozenset(missing))

    # -- assembly ---------------------------------------------------------

    def _state(self, bar: Bar, ts: datetime) -> MarketState:
        venue = self._venues.get(bar.ticker, Venue.HSX)
        locked, evidence = bar.full_bar_lock()
        band = (BandSource.PUBLISHED
                if bar.ceiling is not None and bar.floor is not None
                else BandSource.ABSENT)
        return MarketState(
            ticker=bar.ticker, ts=ts, reference=bar.reference,
            ceiling=bar.ceiling, floor=bar.floor, band_source=band,
            last=bar.close if bar.traded else None, book=None,
            session=phase_at(venue, ts.time()),
            foreign_room=None, locked_side=locked, lock_evidence=evidence)
