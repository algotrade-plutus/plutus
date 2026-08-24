"""Value types crossing the exchange boundary."""

import dataclasses
from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.protocol import (
    BandSource, BookLevel, InstrumentKind, InstrumentSpec, LockEvidence,
    MarketState, Order, OrderBook, Position, Resolution, SessionPhase, Side,
)


def test_all_reason_enums_defined_here_are_str_mixed():
    """Load-bearing: json_safe passes bare enums through and dumps then raises."""
    for enum_cls in (SessionPhase, LockEvidence, BandSource, Resolution,
                     InstrumentKind):
        assert isinstance(next(iter(enum_cls)), str), enum_cls.__name__


def test_value_types_are_frozen():
    for cls in (Order, Position, BookLevel, OrderBook, MarketState,
                InstrumentSpec):
        assert cls.__dataclass_params__.frozen is True, cls.__name__


def test_market_state_defaults_are_honest_about_absence():
    state = MarketState(ticker='FPT', ts=datetime(2022, 3, 29))
    assert state.ceiling is None
    assert state.floor is None
    assert state.reference is None
    assert state.last is None
    assert state.book is None
    assert state.foreign_room is None
    assert state.locked_side is None
    assert state.lock_evidence is LockEvidence.UNKNOWN
    assert state.band_source is BandSource.ABSENT
    assert state.session is SessionPhase.UNKNOWN


def test_bands_are_optional_with_provenance():
    state = MarketState(
        ticker='FPT', ts=datetime(2022, 3, 29), reference=Decimal('95.0'),
        ceiling=None, floor=None, band_source=BandSource.ABSENT,
        session=SessionPhase.CONTINUOUS,
    )
    assert state.ceiling is None
    assert state.band_source is BandSource.ABSENT


def test_book_level_size_is_optional_because_no_corpus_has_sizes():
    assert BookLevel(price=Decimal('95.5')).size is None


def test_order_book_holds_up_to_three_levels_per_side():
    book = OrderBook(
        asks=(BookLevel(Decimal('95.5')), BookLevel(Decimal('95.6'))),
        bids=(BookLevel(Decimal('95.4')),),
        as_of=datetime(2022, 3, 29, 10, 15),
    )
    assert len(book.asks) == 2 and len(book.bids) == 1


def test_order_defaults_to_a_domestic_limit_order():
    o = Order(ticker='FPT', side=Side.BUY, quantity=100,
              limit_price=Decimal('95.5'))
    assert o.is_foreign is False
    assert o.limit_price == Decimal('95.5')


def test_position_defaults_multiplier_to_one_and_margin_to_none():
    p = Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.BUY, quantity=1,
        entry_price=Decimal('1441.8'), entry_ts=datetime(2022, 4, 22),
    )
    assert p.multiplier == Decimal('1')
    assert p.posted_margin is None
    assert p.stop_price is None


def test_instrument_spec_carries_expiry_and_underlying():
    spec = InstrumentSpec(
        ticker='VN30F2212', exchange_code='HNXDS', kind=InstrumentKind.FUTURE,
        trading_unit=1, daily_trading_limit=Decimal('0.07'),
        multiplier=Decimal('100000'), expiry=date(2022, 12, 15),
        underlying='VN30',
    )
    assert spec.kind is InstrumentKind.FUTURE
    assert spec.expiry == date(2022, 12, 15)


def test_resolution_has_exactly_the_two_supported_granularities():
    assert Resolution.DAILY.value == '1d'
    assert Resolution.TICK.value == 'tick'
    assert len(list(Resolution)) == 2
