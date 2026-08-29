"""A data source that serves the **sized trade tape** -- and says when it can't.

This is the seam a *maker* fill needs. ``DepthSource`` serves the resting book
(how much sits at each price), which is what a *taker* sweeps into.
:class:`TapeSource` serves the other half: the stream of trades that actually
printed -- ``(instant, price, volume)`` -- which is what lifts a *resting* order
by queue position. Neither the daily bar nor the reconstructed book can answer
"how many shares traded at or through my resting price since I joined the queue";
this can, for the windows the extract carries and not otherwise.

Two measured properties of the corpus shape the whole module.

**1. The volume source is ``total``, not ``matchedvolume``.** ``quote.total`` is
the running cumulative matched volume; its **consecutive deltas** are the
complete per-event traded volume, and its last intraday value equals
``quote.dailyvolume`` exactly. ``quote.matchedvolume`` -- the obvious-looking
table -- is *lossy*: on FPT 2022-11-09 it omits events entirely and understates
others, summing to 402,300 against the true 697,700. This module reads ``total``
and never ``matchedvolume``; the difference is a fill that is right versus a fill
that silently under-fills by ~40 %.

**2. Price and volume run on different clocks.** ``matched`` (the price) updates
only when the price *changes* (~584 rows on FPT's day) while ``total`` updates on
every trade, and they do not share datetimes. So the tape is *reconstructed*: for
each ``total`` update the price is the most recent ``matched`` price at or before
it (forward-filled). Where no matched price precedes an event its price is
``None`` and any query that would have to classify it is INDETERMINATE, never
guessed.

Two boundaries that are set, not inferred
------------------------------------------------------------------------
**Reconstruction is scoped to a calendar day**, like ``DepthSource``: a cumulative
total does not carry across the close, and HSX cancels unfilled orders there.

**Out-of-session rows are dropped.** FPT's ``total`` carries a spurious
``00:00:00`` row equal to the whole day's volume before the intraday series
begins; taken literally its first delta would be hugely negative. Rows outside
:attr:`session_start`..:attr:`session_end` are removed, after which the intraday
series is monotone (a residual decrease is a data fault and is raised, not
smoothed).

The honesty rule this exists to keep
------------------------------------------------------------------------
:meth:`prints_through` distinguishes **served-and-zero** from **unserved**. A
window this source covers in which nothing traded through the price returns
``0`` -- a definite no-fill, the resting order simply was not reached. A ticker
or day this source does not hold returns ``None`` -- INDETERMINATE, the tape
cannot say. Collapsing the two would turn ignorance into a confident no-fill,
which suppresses exactly the fills a maker strategy should have made.
"""

import bisect
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple, Union

import duckdb

from plutus.core.order import Side

__all__ = ['TapeSource', 'TapeEvent']

#: Generous intraday bounds: VN30 futures pre-open at 08:45, equities at 09:00,
#: the ATC closes by ~14:45. Anything outside is a summary row, not a trade.
_SESSION_START = time(8, 0)
_SESSION_END = time(15, 30)


@dataclass(frozen=True)
class TapeEvent:
    """One reconstructed trade: a volume at a price at an instant.

    ``price`` is ``None`` where no ``matched`` price precedes the volume event
    -- the price is unknown, never guessed, and a query that depends on it is
    INDETERMINATE.
    """

    ts: datetime
    price: Optional[Decimal]
    volume: int


@dataclass(frozen=True)
class _DayTape:
    """One ticker-day of reconstructed events, and whether it was served."""

    events: Tuple[TapeEvent, ...]
    served: bool
    stamps: Tuple[datetime, ...]      # events' ts, for bisect


class TapeSource:
    """The sized trade tape for one table prefix, reconstructed from ``total``.

    One source reads one prefix (``local_quote`` or ``quote``), the same rule
    ``DepthSource`` follows: the two are different observers of the same market
    and merging them would invent a lineage no row carries.
    """

    def __init__(self, root: Union[str, Path], *,
                 table_prefix: str = 'local_quote',
                 session_start: time = _SESSION_START,
                 session_end: time = _SESSION_END):
        self.root = Path(root)
        self.table_prefix = table_prefix
        self.session_start = session_start
        self.session_end = session_end
        self._conn = duckdb.connect()
        self._tapes: Dict[Tuple[str, date], _DayTape] = {}
        self._tickers: Optional[FrozenSet[str]] = None

    @classmethod
    def for_root(cls, root: Union[str, Path], **kwargs) -> 'TapeSource':
        return cls(root, **kwargs)

    # -- tables ------------------------------------------------------------

    def _reader(self, suffix: str) -> Optional[str]:
        path = self.root / f'{self.table_prefix}_{suffix}.parquet'
        if path.exists():
            return f"read_parquet('{path}')"
        csv = self.root / f'{self.table_prefix}_{suffix}.csv'
        return f"read_csv_auto('{csv}')" if csv.exists() else None

    def tickers(self) -> FrozenSet[str]:
        """Every ticker with a volume row under this prefix."""
        if self._tickers is None:
            reader = self._reader('total')
            found = set()
            if reader is not None:
                found.update(row[0] for row in self._conn.execute(
                    f'SELECT DISTINCT tickersymbol FROM {reader}').fetchall())
            self._tickers = frozenset(found)
        return self._tickers

    # -- reconstruction ----------------------------------------------------

    def sized_tape(self, ticker: str, day: Union[date, datetime]
                   ) -> Tuple[TapeEvent, ...]:
        """The reconstructed ``(ts, price, volume)`` tape for one ticker-day."""
        day = day.date() if isinstance(day, datetime) else day
        return self._tape(ticker, day).events

    def _tape(self, ticker: str, day: date) -> _DayTape:
        key = (ticker, day)
        if key not in self._tapes:
            self._tapes[key] = self._reconstruct(ticker, day)
        return self._tapes[key]

    def _rows(self, ticker: str, day: date, suffix: str,
              column: str) -> List[Tuple[datetime, object]]:
        reader = self._reader(suffix)
        if reader is None:
            return []
        raw = self._conn.execute(
            f'SELECT datetime, {column} FROM {reader} '
            f'WHERE tickersymbol = ? AND datetime >= ? AND datetime < ? '
            f'ORDER BY datetime, {column}',
            [ticker, str(day), str(day + timedelta(days=1))]).fetchall()
        # Drop out-of-session rows (the 00:00:00 daily-summary quirk). Prices
        # arrive as DECIMAL and stay Decimal -- never re-parsed through float.
        return [(ts, val) for ts, val in raw
                if self.session_start <= ts.time() <= self.session_end]

    def _reconstruct(self, ticker: str, day: date) -> _DayTape:
        totals = self._rows(ticker, day, 'total', 'quantity')
        if not totals:
            return _DayTape(events=(), served=False, stamps=())

        matched = self._rows(ticker, day, 'matched', 'price')
        m_stamps = [ts for ts, _ in matched]
        m_prices = [price for _, price in matched]

        def price_at(ts: datetime) -> Optional[Decimal]:
            # last matched price at or before ts (forward fill); None if none.
            i = bisect.bisect_right(m_stamps, ts)
            return m_prices[i - 1] if i > 0 else None

        events: List[TapeEvent] = []
        previous = 0
        for ts, quantity in totals:
            quantity = int(quantity)
            volume = quantity - previous
            if volume < 0:
                raise ValueError(
                    f'{self.table_prefix}.total for {ticker} on {day} decreases '
                    f'({previous} -> {quantity} at {ts}) inside the trading '
                    f'session; a cumulative total may not go backwards, so this '
                    f'is a data fault, not a trade')
            previous = quantity
            if volume:
                events.append(TapeEvent(ts=ts, price=price_at(ts),
                                        volume=volume))
        return _DayTape(events=tuple(events), served=True,
                        stamps=tuple(e.ts for e in events))

    # -- the query a maker fill asks --------------------------------------

    def prints_through(self, ticker: str, price: Decimal, side: Side,
                       since: datetime, until: datetime) -> Optional[int]:
        """Shares that traded **at or through** ``price`` in ``[since, until)``.

        ``side`` is the **resting** order's side. A resting SELL (an ask at
        ``price``) is lifted by buys trading at ``price`` or above it; a resting
        BUY (a bid at ``price``) is hit by sells trading at ``price`` or below
        it -- price-time priority means a trade beyond our price could not have
        happened without clearing ours first.

        Returns the total (``0`` if the window is served but nothing traded
        through), or ``None`` if this source does not serve the ticker-day, or
        if an in-window event has no reconstructable price (INDETERMINATE).

        The window must lie within one calendar day: reconstruction is
        day-scoped (a cumulative total does not cross the close), so the tape is
        that of ``since.date()`` and only events on that day are counted. And it
        is **auction-agnostic** -- it counts every trade in the window,
        including an ATO/ATC uncross; a caller that wants continuous-session
        prints only must bound the window to the continuous phase, exactly as a
        sweep is a continuous-session mechanic.

        Raises:
            ValueError: on ``until < since`` -- an inverted window is a
                swapped-argument integration bug, not an empty one, and is
                refused loudly rather than silently counted as zero (the sibling
                ``DepthSource`` refuses the same shape).
        """
        if side not in (Side.BUY, Side.SELL):
            raise ValueError(
                f'{side} is not a resting order side; prints_through is asked '
                f'for a BUY or a SELL')
        if until < since:
            raise ValueError(
                f'prints_through window is inverted: until {until} is before '
                f'since {since}')
        tape = self._tape(ticker, since.date())
        if not tape.served:
            return None
        if until == since:
            return 0                       # a zero-length window on a served day
        lo = bisect.bisect_left(tape.stamps, since)
        hi = bisect.bisect_left(tape.stamps, until)
        total = 0
        for event in tape.events[lo:hi]:
            if event.price is None:
                return None
            through = (event.price >= price if side is Side.SELL
                       else event.price <= price)
            if through:
                total += event.volume
        return total
