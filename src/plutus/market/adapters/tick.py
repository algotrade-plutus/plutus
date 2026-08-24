"""A MarketDataSource backed by the raw tick archive.

At bar resolution a band lock is *inferred* from ``last == ceiling``. At tick
resolution it is *observed*: there is no ask at or below the ceiling anywhere
in the resting ladder. That upgrades
:class:`~plutus.market.protocol.LockEvidence` from ``BAR_PROXY`` to
``TICK_BOOK``, and it is the whole reason this adapter exists.

Two limits, both structural:

* ``quote_asksize`` / ``quote_bidsize`` are 0-row in every corpus available
  here, so :attr:`BookLevel.size` is always ``None``. Depth-of-book *liquidity*
  is not measurable; the price ladder is.
* The two sides are not synchronised in time. Each is forward-filled
  independently and the fill origin is recorded on
  :attr:`OrderBook.as_of`.

Bands are not in the archive at tick granularity, so they are supplied by a
daily source passed in as ``band_source``.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Union

import duckdb

from plutus.market.protocol import (
    BookLevel, InstrumentSpec, LockEvidence, MarketState, OrderBook,
    Resolution, SessionPhase, Side,
)

__all__ = ['TickSource']

MAX_DEPTH = 3   # the archive carries depth 1-3; 4-10 return no rows


class TickSource:
    """Tick-resolution MarketDataSource over the raw CSV archive."""

    def __init__(self, archive_root: str, band_source):
        self.root = Path(archive_root)
        self.band_source = band_source
        self._conn = duckdb.connect()

    def _table(self, name: str) -> Optional[str]:
        path = self.root / f'{name}.csv'
        return f"read_csv_auto('{path}')" if path.exists() else None

    def instrument(self, ticker: str) -> InstrumentSpec:
        """Delegated to the daily source, which owns the fallback chain."""
        return self.band_source.instrument(ticker)

    def states(
        self,
        ticker: str,
        start: Union[date, datetime],
        end: Union[date, datetime],
        *,
        resolution: Resolution = Resolution.TICK,
    ) -> Iterator[MarketState]:
        """Tick states over ``[start, end)``. End is exclusive."""
        if resolution is not Resolution.TICK:
            raise ValueError(
                'TickSource serves Resolution.TICK only; use '
                'plutus.market.adapters.datahub.DataHubSource for DAILY'
            )
        matched = self._table('quote_matched')
        if matched is None:
            return iter(())
        return iter(self._build(ticker, start, end, matched))

    def _build(self, ticker, start, end, matched) -> List[MarketState]:
        ask_t = self._table('quote_askprice')
        bid_t = self._table('quote_bidprice')

        trades = self._conn.execute(
            f'SELECT datetime, price FROM {matched} '
            f'WHERE tickersymbol = ? AND datetime >= ? AND datetime < ? '
            f'ORDER BY datetime',
            [ticker, str(start)[:10], str(end)[:10]]).fetchall()
        if not trades:
            return []

        asks = self._ladder(ask_t, ticker, start, end)
        bids = self._ladder(bid_t, ticker, start, end)

        daily: Dict[date, MarketState] = {}
        out: List[MarketState] = []
        for ts, price in trades:
            day = ts.date()
            if day not in daily:
                daily[day] = self.band_source.state_at(
                    ticker, datetime.combine(day, datetime.min.time()))
            bands = daily[day]
            book = OrderBook(
                bids=self._at(bids, ts), asks=self._at(asks, ts), as_of=ts)
            ceiling = bands.ceiling if bands else None
            floor = bands.floor if bands else None

            locked_side, evidence = self._lock(book, ceiling, floor)
            out.append(MarketState(
                ticker=ticker, ts=ts,
                reference=bands.reference if bands else None,
                ceiling=ceiling, floor=floor,
                band_source=bands.band_source if bands else None,
                last=Decimal(str(price)), book=book,
                session=SessionPhase.CONTINUOUS,
                locked_side=locked_side, lock_evidence=evidence,
            ))
        return out

    def _ladder(self, table, ticker, start, end
                ) -> List[Tuple[datetime, int, Decimal]]:
        if table is None:
            return []
        return [
            (ts, int(depth), Decimal(str(price)))
            for ts, depth, price in self._conn.execute(
                f'SELECT datetime, depth, price FROM {table} '
                f'WHERE tickersymbol = ? AND datetime >= ? AND datetime < ? '
                f'AND depth <= ? ORDER BY datetime',
                [ticker, str(start)[:10], str(end)[:10], MAX_DEPTH]).fetchall()
        ]

    @staticmethod
    def _at(ladder, ts) -> Tuple[BookLevel, ...]:
        """Forward-fill each depth level to ``ts``.

        Sizes are always None: the size tables are 0-row in every corpus.
        """
        latest: Dict[int, Decimal] = {}
        for row_ts, depth, price in ladder:
            if row_ts > ts:
                break
            latest[depth] = price
        return tuple(BookLevel(price=latest[d]) for d in sorted(latest))

    @staticmethod
    def _lock(book: OrderBook, ceiling, floor
              ) -> Tuple[Optional[Side], LockEvidence]:
        """Observe a lock from the resting ladder, rather than infer one.

        A buy-side lock means no ask rests below the ceiling: nothing is on
        offer under the cap, so a buyer cannot cross. Absence of a ladder is
        reported as UNKNOWN, never as 'not locked'.
        """
        if ceiling is not None and book.asks:
            if min(level.price for level in book.asks) >= ceiling:
                return Side.BUY, LockEvidence.TICK_BOOK
        if floor is not None and book.bids:
            if max(level.price for level in book.bids) <= floor:
                return Side.SELL, LockEvidence.TICK_BOOK
        if not book.asks and not book.bids:
            return None, LockEvidence.UNKNOWN
        return None, LockEvidence.TICK_BOOK

    def state_at(self, ticker: str, ts: datetime) -> Optional[MarketState]:
        day = ts.date() if isinstance(ts, datetime) else ts
        latest = None
        for state in self.states(ticker, day, day + timedelta(days=1)):
            if state.ts > ts:
                break
            latest = state
        return latest
