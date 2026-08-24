"""The narrow boundary between market data and exchange rules.

Keeping this protocol small is what makes the exchange models
vendor-independent: anything that can answer these three questions -- our own
datahub, vnstock, a broker feed -- can drive them.
"""

from datetime import date, datetime
from typing import Iterator, Optional, Protocol, Union, runtime_checkable

from plutus.market.protocol import InstrumentSpec, MarketState, Resolution

__all__ = ['MarketDataSource']


@runtime_checkable
class MarketDataSource(Protocol):
    """Supplies market state to an exchange model."""

    def state_at(self, ticker: str, ts: datetime) -> Optional[MarketState]:
        """The state for one ticker at one instant, or None if absent."""
        ...

    def states(
        self,
        ticker: str,
        start: Union[date, datetime],
        end: Union[date, datetime],
        *,
        resolution: Resolution = Resolution.DAILY,
    ) -> Iterator[MarketState]:
        """States over ``[start, end)``. **End is exclusive**, matching
        ``plutus.datahub.utils.date_utils.validate_date_range``."""
        ...

    def instrument(self, ticker: str) -> InstrumentSpec:
        """Instrument facts. Never raises: unknown tickers come back as
        ``InstrumentKind.UNKNOWN`` rather than an exception."""
        ...
