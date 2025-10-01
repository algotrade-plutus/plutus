"""Metadata models for instrument reference data, index constituents, and futures contracts.

This module provides data structures for market metadata that is distinct from time-series
Quote data. Metadata includes instrument reference information, index constituent listings,
and futures contract code mappings.

Key Differences from Quote:
    - Quote: Time-series market data (prices, volumes) with high-frequency updates
    - Metadata: Reference data with infrequent updates, used for lookups and context

Data Models:
    - InstrumentMetadata: Instrument properties from quote_ticker.csv
    - IndexConstituent: Index membership from quote_vn30.csv
    - FutureContractCode: Futures contract codes from quote_futurecontractcode.csv

Usage:
    >>> from datetime import date
    >>> metadata = InstrumentMetadata(
    ...     ticker_symbol="VIC",
    ...     exchange_id="HSX",
    ...     instrument_type="stock",
    ...     last_updated=date(2023, 6, 15)
    ... )
    >>> constituent = IndexConstituent(
    ...     index_name="VN30",
    ...     ticker_symbol="VIC",
    ...     effective_date=date(2023, 6, 15)
    ... )
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class InstrumentMetadata:
    """Instrument reference data from quote_ticker.csv.

    This metadata provides static or slowly-changing properties of trading instruments,
    such as their exchange listing, instrument type (stock/futures), and lifecycle dates.

    Attributes:
        ticker_symbol: Ticker symbol (e.g., "VIC", "HPG", "VN30F2306")
        exchange_id: Exchange identifier ("HSX", "HNX", "UPCOM")
        instrument_type: Type of instrument ("stock", "futures", "index")
        last_updated: Date when metadata was last updated
        start_date: Instrument start/listing date (None for stocks)
        exp_date: Instrument expiration date (relevant for futures, None for stocks)

    Examples:
        >>> # Stock metadata
        >>> stock = InstrumentMetadata(
        ...     ticker_symbol="VIC",
        ...     exchange_id="HSX",
        ...     instrument_type="stock",
        ...     last_updated=date(2023, 6, 15)
        ... )

        >>> # Futures metadata with expiration
        >>> futures = InstrumentMetadata(
        ...     ticker_symbol="VN30F2306",
        ...     exchange_id="HSX",
        ...     instrument_type="futures",
        ...     last_updated=date(2023, 6, 15),
        ...     start_date=date(2023, 6, 15),
        ...     exp_date=date(2023, 6, 30)
        ... )
    """
    ticker_symbol: str
    exchange_id: str
    instrument_type: str
    last_updated: date
    start_date: Optional[date] = None
    exp_date: Optional[date] = None

    def __post_init__(self):
        """Validate metadata fields after initialization."""
        if not self.ticker_symbol:
            raise ValueError("ticker_symbol cannot be empty")
        if not self.exchange_id:
            raise ValueError("exchange_id cannot be empty")
        if not self.instrument_type:
            raise ValueError("instrument_type cannot be empty")
        if not isinstance(self.last_updated, date):
            raise TypeError(f"last_updated must be a date, got {type(self.last_updated)}")


@dataclass
class IndexConstituent:
    """Index membership data from quote_vn30.csv.

    This metadata tracks which securities are constituents of market indices
    (e.g., VN30 index) at a given date. Index constituent lists are typically
    updated quarterly during rebalancing events.

    Attributes:
        index_name: Name of the index (e.g., "VN30", "VNINDEX")
        ticker_symbol: Ticker symbol of the constituent security
        effective_date: Date when this constituent membership became effective

    Examples:
        >>> constituent = IndexConstituent(
        ...     index_name="VN30",
        ...     ticker_symbol="VIC",
        ...     effective_date=date(2023, 6, 15)
        ... )

        >>> # Check if security is in index
        >>> if constituent.index_name == "VN30":
        ...     print(f"{constituent.ticker_symbol} is a VN30 constituent")
    """
    index_name: str
    ticker_symbol: str
    effective_date: date

    def __post_init__(self):
        """Validate constituent fields after initialization."""
        if not self.index_name:
            raise ValueError("index_name cannot be empty")
        if not self.ticker_symbol:
            raise ValueError("ticker_symbol cannot be empty")
        if not isinstance(self.effective_date, date):
            raise TypeError(f"effective_date must be a date, got {type(self.effective_date)}")


@dataclass
class FutureContractCode:
    """Futures contract code mapping from quote_futurecontractcode.csv.

    This metadata maps specific futures contract symbols (e.g., VN30F2306) to
    standardized contract codes (e.g., VN30F1M for front-month, VN30F1Q for
    front-quarter). This is useful for rolling contracts and identifying
    contract series.

    Contract Code Conventions:
        - VN30F1M: Front month contract
        - VN30F2M: Second month contract
        - VN30F1Q: Front quarter contract
        - VN30F2Q: Second quarter contract

    Attributes:
        ticker_symbol: Full futures contract symbol (e.g., "VN30F2306")
        contract_code: Standardized contract code (e.g., "VN30F1M")
        effective_date: Date when this code mapping became effective

    Examples:
        >>> code = FutureContractCode(
        ...     ticker_symbol="VN30F2306",
        ...     contract_code="VN30F1M",
        ...     effective_date=date(2023, 6, 1)
        ... )

        >>> # Identify front-month contract
        >>> if code.contract_code == "VN30F1M":
        ...     print(f"{code.ticker_symbol} is the front month contract")
    """
    ticker_symbol: str
    contract_code: str
    effective_date: date

    def __post_init__(self):
        """Validate contract code fields after initialization."""
        if not self.ticker_symbol:
            raise ValueError("ticker_symbol cannot be empty")
        if not self.contract_code:
            raise ValueError("contract_code cannot be empty")
        if not isinstance(self.effective_date, date):
            raise TypeError(f"effective_date must be a date, got {type(self.effective_date)}")