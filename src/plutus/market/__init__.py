"""An executable model of Vietnamese exchange fill rules.

This package models what an **exchange** does to an order and to a position:
the tick-grid, lot, price-band, session and foreign-room checks run before an
order may rest on the book, and the margin, position-limit and expiry logic a
derivatives exchange runs against an open position each day.

It does NOT model the trader's side. There is no strategy, portfolio, cash
balance or P&L here; no order lifecycle, queue-priority matching or
partial-fill sequencing; and no decision about what to do after a margin call
-- only the report that the exchange would issue one. Exchange-side fill
model, not trader-side execution engine.

Market data crosses a single granularity-agnostic boundary
(:class:`~plutus.market.protocol.MarketState`) supplied by an adapter, so the
same rules run on daily bars and on ticks and this package imports no data
vendor.
"""

from plutus.market.protocol import (
    BandSource, BookLevel, InstrumentKind, InstrumentSpec, LockEvidence,
    MarketState, Order, OrderBook, OrderType, Position, Resolution,
    SessionPhase, Side,
)
from plutus.market.verdicts import (
    Admissibility, AdmissionRule, PositionEvent, PositionEventKind,
    SettlementSource, Verdict, Viability,
)

__all__ = [
    'Admissibility', 'AdmissionRule', 'BandSource', 'BookLevel',
    'InstrumentKind', 'InstrumentSpec', 'LockEvidence', 'MarketState',
    'Order', 'OrderBook', 'OrderType', 'Position', 'PositionEvent',
    'PositionEventKind', 'Resolution', 'SessionPhase', 'SettlementSource',
    'Side', 'Verdict', 'Viability',
]
