"""A composite tick source for the intraday book-walk session.

The order-book fill (``BookWalkFillPolicy``) needs a **TICK**-resolution interval
so a ladder has an instant to be as-of, and it needs an order book at that
instant. But the price/band/instrument data (daily bands, the ticker's venue and
tick grid) lives in a :class:`~plutus.market.adapters.datahub.DataHubSource`,
which serves only ``Resolution.DAILY``; and the book lives in a
:class:`~plutus.market.adapters.depth.DepthSource`, which serves only the book.
Neither is a complete session source on its own.

``BookSessionSource`` composes the two. It **serves TICK** (so a tick session is
not refused at construction), delegates instrument/band/state to the price
source, delegates ``book_at`` to the depth source (so it *is* a
:class:`~plutus.market.session.book_walk.BookProvider`), and answers
:meth:`interval` with a tick interval whose state is the day's band and whose
instant is the request time. The daily band on an intraday instant is honest —
a price band is a daily fact — and the phase rides through as the price source
stamped it. This keeps both underlying adapters untouched (``DepthSource`` is
slated for reimplementation; this does not build on that).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import ClassVar, FrozenSet, Optional, Union

from plutus.core.order import Side
from plutus.market.adapters.datahub import DataHubSource
from plutus.market.adapters.depth import DepthBook, DepthSource
from plutus.market.adapters.tape import TapeSource
from plutus.market.protocol import InstrumentSpec, MarketState, Resolution
from plutus.market.session.types import DataField, MarketInterval

#: The OHLC/volume a price source withholds on a synthesised tick interval; the
#: book-walk fill reads the ladder, not these, so naming them keeps a run's
#: ignorance honest without blocking the sweep.
_WITHHELD_ON_TICK: FrozenSet[DataField] = frozenset({
    DataField.OPEN, DataField.HIGH, DataField.LOW, DataField.VOLUME,
})


class BookSessionSource:
    """Price/band/instrument from a ``DataHubSource``, the book from a
    ``DepthSource``, served at ``Resolution.TICK`` for a book-walk session."""

    SERVES_RESOLUTIONS: ClassVar[FrozenSet[Resolution]] = frozenset({
        Resolution.TICK,
    })

    def __init__(self, prices: DataHubSource, book: DepthSource,
                 tape: Optional[TapeSource] = None) -> None:
        self._prices = prices
        self._book = book
        self._tape = tape

    @classmethod
    def for_roots(cls, price_root: Union[str, Path],
                  book_root: Union[str, Path], *,
                  table_prefix: str = 'local_quote') -> 'BookSessionSource':
        # The sized tape (``{prefix}_matched`` + ``{prefix}_total``) sits beside
        # the book tables in the same root, so one prefix resolves all three.
        return cls(DataHubSource.for_root(str(price_root)),
                   DepthSource(book_root, table_prefix=table_prefix),
                   TapeSource(book_root, table_prefix=table_prefix))

    # -- instrument / state (delegated to the price source) ----------------

    def instrument(self, ticker: str) -> InstrumentSpec:
        return self._prices.instrument(ticker)

    def state_at(self, ticker: str, ts: datetime) -> Optional[MarketState]:
        # The day's band and reference; the phase is the price source's. A daily
        # band on an intraday instant is a daily fact used at its own resolution.
        return self._prices.state_at(ticker, ts)

    # -- the tick interval the book-walk policy accepts --------------------

    def interval(self, ticker: str, start: datetime, end: datetime, *,
                 resolution: Resolution = Resolution.TICK
                 ) -> Optional[MarketInterval]:
        if resolution not in self.SERVES_RESOLUTIONS:
            raise ValueError(
                f'BookSessionSource serves '
                f'{sorted(r.value for r in self.SERVES_RESOLUTIONS)}, not '
                f'{resolution.value}; the price/band layer is daily and the '
                f'book layer is tick, and this composite exists to run a tick '
                f'book-walk session on top of them')
        state = self.state_at(ticker, start)
        if state is None:
            return None
        return MarketInterval(
            ticker=ticker, start=start, end=end, resolution=Resolution.TICK,
            state=state, close=state.last, missing=_WITHHELD_ON_TICK)

    # -- the book (delegated to the depth source) --------------------------

    def book_at(self, ticker: str, ts: datetime, *,
                resolution: Resolution = Resolution.TICK,
                max_age: Optional[timedelta] = None) -> DepthBook:
        return self._book.book_at(ticker, ts, resolution=resolution,
                                  max_age=max_age)

    # -- the sized tape (delegated to the tape source) ---------------------

    def prints_through(self, ticker: str, price: Decimal, side: Side,
                       since: datetime, until: datetime) -> Optional[int]:
        """Shares printed through ``price`` in ``[since, until)`` -- so this
        composite is also a ``TapeProvider`` and a maker fill can rest on it.
        ``None`` where no tape was composed or it does not serve the window,
        which the maker arm reads as INDETERMINATE."""
        if self._tape is None:
            return None
        return self._tape.prints_through(ticker, price, side, since, until)
