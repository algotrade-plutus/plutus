"""Value types crossing the exchange boundary.

Every price is a :class:`~decimal.Decimal`. Every reason enum defined here
mixes in ``str``: :func:`plutus.evaluation.contract.json_safe` passes a bare
``Enum`` through unchanged and ``json.dumps`` then raises, so the mixin is part
of what makes verdicts serialisable.

Note that :class:`plutus.core.order.Side` and ``OrderType`` are *not* str-mixed
-- they predate this package -- so anything placing them in a serialisable
payload must go through :func:`plutus.market.verdicts._serialise`, which
unwraps any ``Enum`` by value.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

# Importable and safe. Unlike plutus.core.position / transaction / portfolio /
# algorithm / bot, which all raise ModuleNotFoundError on a bare `import utils`.
from plutus.core.order import OrderType, Side

__all__ = [
    'BandSource', 'BookLevel', 'InstrumentKind', 'InstrumentSpec',
    'LockEvidence', 'MarketState', 'Order', 'OrderBook', 'OrderType',
    'Position', 'Resolution', 'SessionPhase', 'Side',
]


class SessionPhase(str, Enum):
    """Which phase of the trading day a state belongs to.

    Set explicitly by the adapter. **Never infer this from a timestamp**: a
    daily bar's ``ts`` is midnight, and the coded ``before_trading_session``
    reports ``is_current()`` True at midnight, so inference would mark every
    daily bar pre-open and reject an entire daily measurement.
    """

    PRE_OPEN = 'pre_open'
    OPENING_AUCTION = 'opening_auction'      # ATO -- HSX and HNXDS only
    CONTINUOUS = 'continuous'
    NOON_BREAK = 'noon_break'
    CLOSING_AUCTION = 'closing_auction'      # ATC -- not UPCOM
    POST_CLOSE_PLO = 'post_close_plo'        # PLO -- HNX only
    POST_CLOSE = 'post_close'
    UNKNOWN = 'unknown'


class LockEvidence(str, Enum):
    """How a band lock was established.

    Distinguishing these is what keeps the fillability rule honest: the
    resting-book evidence is authoritative, the bar proxy is an inference, and
    absence must be sayable rather than guessed.
    """

    TICK_BOOK = 'tick_book'   # forward-filled ask/bid ladder: authoritative
    BAR_PROXY = 'bar_proxy'   # last == ceiling (or == floor) on a daily bar
    UNKNOWN = 'unknown'       # -> the lock rule yields INDETERMINATE


class BandSource(str, Enum):
    """Where a state's ceiling/floor came from."""

    PUBLISHED = 'published'
    RECONSTRUCTED = 'reconstructed'
    ABSENT = 'absent'


class Resolution(str, Enum):
    """The granularities an adapter may serve.

    Deliberately NOT ``OHLCQuery.INTERVALS``: its six intraday keys all raise
    ``FileNotFoundError`` eagerly on the Parquet root, which carries no ticks.
    """

    DAILY = '1d'
    TICK = 'tick'


class InstrumentKind(str, Enum):
    STOCK = 'stock'
    WARRANT = 'warrant'
    FUND = 'fund'
    FUTURE = 'future'
    INDEX = 'index'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class BookLevel:
    """One price level of a resting ladder.

    ``size`` is ``None`` on every corpus available here: ``quote_asksize``,
    ``quote_bidsize``, ``quote_totalask`` and ``quote_totalbid`` are all 0-row
    in both roots. The field exists so the type is correct; no rule may
    *require* it.
    """

    price: Decimal
    size: Optional[int] = None


@dataclass(frozen=True)
class OrderBook:
    """Up to three levels per side. The sides are not synchronised in time."""

    bids: Tuple[BookLevel, ...] = ()
    asks: Tuple[BookLevel, ...] = ()
    as_of: Optional[datetime] = None


@dataclass(frozen=True)
class MarketState:
    """Everything an exchange needs to judge one order at one instant.

    Whether this was built from a daily bar, a single tick or a book snapshot
    is the adapter's business. That is what lets one rule set run at both
    resolutions.
    """

    ticker: str
    ts: datetime
    reference: Optional[Decimal] = None
    ceiling: Optional[Decimal] = None
    floor: Optional[Decimal] = None
    band_source: BandSource = BandSource.ABSENT
    last: Optional[Decimal] = None
    book: Optional[OrderBook] = None
    session: SessionPhase = SessionPhase.UNKNOWN
    foreign_room: Optional[int] = None
    locked_side: Optional[Side] = None
    lock_evidence: LockEvidence = LockEvidence.UNKNOWN


@dataclass(frozen=True)
class InstrumentSpec:
    """Per-instrument facts the exchange rulebook alone cannot supply."""

    ticker: str
    exchange_code: str
    kind: InstrumentKind
    trading_unit: int
    daily_trading_limit: Decimal
    multiplier: Decimal = Decimal('1')
    expiry: Optional[date] = None
    underlying: Optional[str] = None


@dataclass(frozen=True)
class Order:
    """An order as presented to an exchange for admission."""

    ticker: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.LIMIT
    limit_price: Optional[Decimal] = None
    is_foreign: bool = False


@dataclass(frozen=True)
class Position:
    """An open position, for position-survival evaluation.

    Deliberately NOT ``plutus.core.position.Position``: that module is
    unimportable, and it requires ``portfolio_id`` and ``capital`` -- portfolio
    concepts this package excludes by design.
    """

    ticker: str
    exchange_code: str
    side: Side
    quantity: int
    entry_price: Decimal
    entry_ts: datetime
    multiplier: Decimal = Decimal('1')
    posted_margin: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
