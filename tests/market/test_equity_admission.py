"""Equity-exchange admission: all six rules."""

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.exchanges.equity import (
    HNX_EXCHANGE, HSX_EXCHANGE, UPCOM_EXCHANGE,
)
from plutus.market.protocol import (
    BandSource, LockEvidence, MarketState, Order, OrderType, SessionPhase, Side,
)
from plutus.market.verdicts import AdmissionRule, Verdict

TS = datetime(2022, 3, 29, 10, 15)


def _state(**kw):
    base = dict(
        ticker='FPT', ts=TS, session=SessionPhase.CONTINUOUS,
        reference=Decimal('95.0'), ceiling=Decimal('101.6'),
        floor=Decimal('88.4'), band_source=BandSource.PUBLISHED,
        last=Decimal('95.0'),
    )
    base.update(kw)
    return MarketState(**base)


def _order(**kw):
    base = dict(ticker='FPT', side=Side.BUY, quantity=100,
                limit_price=Decimal('95.5'))
    base.update(kw)
    return Order(**base)


# --- 1. tick grid ----------------------------------------------------------

@pytest.mark.parametrize(
    'price, admitted',
    [(Decimal('95.5'), True), (Decimal('95.55'), False),
     (Decimal('9.99'), True), (Decimal('9.995'), False),
     (Decimal('25.05'), True), (Decimal('25.03'), False)],
)
def test_hsx_tick_grid(price, admitted):
    state = _state(reference=price, ceiling=price * 2,
                   floor=Decimal('0.01'), last=price)
    r = HSX_EXCHANGE.admits(_order(limit_price=price), state)
    if admitted:
        assert r.verdict is Verdict.ADMITTED
    else:
        assert r.verdict is Verdict.REJECTED
        assert r.rule is AdmissionRule.TICK_GRID


def test_hsx_tick_band_boundary_is_lower_inclusive():
    """At exactly 10.00 the tick is 0.05, not 0.01. The code is authoritative;
    HANDOFF-IMPLEMENTATION-DEPRECATED.md:163 states the opposite and is wrong."""
    state = _state(reference=Decimal('10'), ceiling=Decimal('20'),
                   floor=Decimal('1'), last=Decimal('10'))
    assert HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('10.05')), state).verdict is Verdict.ADMITTED
    off = HSX_EXCHANGE.admits(_order(limit_price=Decimal('10.01')), state)
    assert off.verdict is Verdict.REJECTED
    assert off.rule is AdmissionRule.TICK_GRID


def test_warrant_etf_exception_uses_the_one_cent_grid():
    """8 characters and a leading C/E/F -> 0.01 regardless of price."""
    state = _state(ticker='CFPT2314', reference=Decimal('120.5'),
                   ceiling=Decimal('130'), floor=Decimal('110'),
                   last=Decimal('120.5'))
    r = HSX_EXCHANGE.admits(
        _order(ticker='CFPT2314', limit_price=Decimal('120.51')), state)
    assert r.verdict is Verdict.ADMITTED


def test_eight_chars_without_cef_prefix_falls_through_to_the_bands():
    state = _state(ticker='ABCD1234', reference=Decimal('25'),
                   ceiling=Decimal('30'), floor=Decimal('20'), last=Decimal('25'))
    r = HSX_EXCHANGE.admits(
        _order(ticker='ABCD1234', limit_price=Decimal('25.01')), state)
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.TICK_GRID


def test_unmatched_price_yields_indeterminate_not_a_crash():
    """get_hsx_tick_size returns None for a price no band matches."""
    state = _state(reference=Decimal('-1'), ceiling=Decimal('0'),
                   floor=Decimal('-100'), last=Decimal('-1'))
    r = HSX_EXCHANGE.admits(_order(limit_price=Decimal('-1')), state)
    assert r.verdict is Verdict.INDETERMINATE
    assert r.rule is AdmissionRule.TICK_GRID


@pytest.mark.parametrize('exchange', [HNX_EXCHANGE, UPCOM_EXCHANGE])
def test_non_hsx_equity_exchanges_use_a_flat_tenth(exchange):
    state = _state(reference=Decimal('25'), ceiling=Decimal('30'),
                   floor=Decimal('20'), last=Decimal('25'))
    assert exchange.admits(_order(limit_price=Decimal('25.1')),
                           state).verdict is Verdict.ADMITTED
    bad = exchange.admits(_order(limit_price=Decimal('25.05')), state)
    assert bad.verdict is Verdict.REJECTED
    assert bad.rule is AdmissionRule.TICK_GRID


# --- 2. round lot ----------------------------------------------------------

@pytest.mark.parametrize('qty, admitted',
                         [(100, True), (1000, True), (150, False),
                          (1, False), (0, False)])
def test_equity_round_lot_is_one_hundred(qty, admitted):
    r = HSX_EXCHANGE.admits(_order(quantity=qty), _state())
    if admitted:
        assert r.verdict is Verdict.ADMITTED
    else:
        assert r.verdict is Verdict.REJECTED
        assert r.rule is AdmissionRule.ROUND_LOT
        assert r.binding_constraint == 100


@pytest.mark.parametrize('day, qty, admitted', [
    # HOSE's minimum lot was 10 shares until 2021-01-03 ...
    (datetime(2020, 6, 15, 10, 15), 10, True),
    (datetime(2020, 6, 15, 10, 15), 50, True),
    (datetime(2020, 6, 15, 10, 15), 5, False),
    # ... and 100 from 2021-01-04.
    (datetime(2021, 1, 4, 10, 15), 10, False),
    (datetime(2021, 1, 4, 10, 15), 100, True),
])
def test_the_hsx_round_lot_is_resolved_at_the_order_instant(day, qty, admitted):
    """A date-blind lot rejects orders the real HOSE accepted.

    The corpus holds 94,675 HSX stock closes in 2020, so a lot of 100 applied
    to all history refuses legal 10-share orders across most of a year of the
    equity sample.
    """
    r = HSX_EXCHANGE.admits(_order(quantity=qty), _state(ts=day))
    if admitted:
        assert r.verdict is Verdict.ADMITTED
    else:
        assert r.verdict is Verdict.REJECTED
        assert r.rule is AdmissionRule.ROUND_LOT


def test_rule_order_is_tick_then_lot():
    """Both broken: the tick grid is reported, because it is checked first."""
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('95.55'), quantity=150), _state())
    assert r.rule is AdmissionRule.TICK_GRID


# --- 3. BAND_LIMIT ---------------------------------------------------------

def test_price_above_ceiling_is_rejected():
    r = HSX_EXCHANGE.admits(_order(limit_price=Decimal('101.7')), _state())
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.BAND_LIMIT
    assert r.binding_constraint == Decimal('101.6')


def test_price_below_floor_is_rejected():
    r = HSX_EXCHANGE.admits(
        _order(side=Side.SELL, limit_price=Decimal('88.3')), _state())
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.BAND_LIMIT


def test_price_exactly_at_ceiling_is_admissible():
    """The exchange accepts it. Whether it FILLS is BAND_LOCK's question."""
    r = HSX_EXCHANGE.admits(_order(limit_price=Decimal('101.6')), _state())
    assert r.verdict is Verdict.ADMITTED


def test_absent_bands_yield_indeterminate_not_admission():
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('95.5')),
        _state(ceiling=None, floor=None, band_source=BandSource.ABSENT))
    assert r.verdict is Verdict.INDETERMINATE
    assert r.rule is AdmissionRule.BAND_LIMIT


# --- 4. BAND_LOCK ----------------------------------------------------------

def test_buy_into_a_locked_ceiling_is_not_fillable():
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('101.6')),
        _state(last=Decimal('101.6'), locked_side=Side.BUY,
               lock_evidence=LockEvidence.BAR_PROXY))
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.BAND_LOCK
    assert r.detail['lock_evidence'] == 'bar_proxy'


def test_sell_into_a_locked_ceiling_is_fine():
    """A lock blocks the side that must cross it, not the side supplying it."""
    r = HSX_EXCHANGE.admits(
        _order(side=Side.SELL, limit_price=Decimal('101.6')),
        _state(last=Decimal('101.6'), locked_side=Side.BUY,
               lock_evidence=LockEvidence.BAR_PROXY))
    assert r.verdict is Verdict.ADMITTED


def test_sell_into_a_locked_floor_is_not_fillable():
    r = HSX_EXCHANGE.admits(
        _order(side=Side.SELL, limit_price=Decimal('88.4')),
        _state(last=Decimal('88.4'), locked_side=Side.SELL,
               lock_evidence=LockEvidence.BAR_PROXY))
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.BAND_LOCK


def test_unknown_lock_evidence_yields_indeterminate():
    """Absence of a book is not evidence of fillability."""
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('101.6')),
        _state(last=Decimal('101.6'), locked_side=Side.BUY,
               lock_evidence=LockEvidence.UNKNOWN))
    assert r.verdict is Verdict.INDETERMINATE
    assert r.rule is AdmissionRule.BAND_LOCK


def test_tick_book_evidence_is_honoured_the_same_way():
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('101.6')),
        _state(last=Decimal('101.6'), locked_side=Side.BUY,
               lock_evidence=LockEvidence.TICK_BOOK))
    assert r.verdict is Verdict.REJECTED
    assert r.detail['lock_evidence'] == 'tick_book'


def test_band_limit_precedes_band_lock():
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('101.7')),
        _state(last=Decimal('101.6'), locked_side=Side.BUY,
               lock_evidence=LockEvidence.BAR_PROXY))
    assert r.rule is AdmissionRule.BAND_LIMIT


# --- 5. foreign room -------------------------------------------------------

def test_domestic_order_ignores_foreign_room():
    assert HSX_EXCHANGE.admits(_order(is_foreign=False),
                               _state(foreign_room=0)).verdict is Verdict.ADMITTED


def test_foreign_buy_exceeding_room_is_rejected():
    r = HSX_EXCHANGE.admits(_order(is_foreign=True, quantity=1000),
                            _state(foreign_room=500))
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.FOREIGN_ROOM
    assert r.binding_constraint == 500


def test_foreign_buy_within_room_is_admitted():
    assert HSX_EXCHANGE.admits(
        _order(is_foreign=True, quantity=100),
        _state(foreign_room=500)).verdict is Verdict.ADMITTED


def test_foreign_sell_is_not_constrained_by_room():
    """Room limits acquisition, not disposal."""
    r = HSX_EXCHANGE.admits(
        _order(is_foreign=True, side=Side.SELL, quantity=1000,
               limit_price=Decimal('95.5')), _state(foreign_room=0))
    assert r.verdict is Verdict.ADMITTED


def test_absent_room_yields_indeterminate_for_a_foreign_buy():
    """This is the state of every ticker-day on the shipped Parquet corpus."""
    r = HSX_EXCHANGE.admits(_order(is_foreign=True), _state(foreign_room=None))
    assert r.verdict is Verdict.INDETERMINATE
    assert r.rule is AdmissionRule.FOREIGN_ROOM


# --- 6. session semantics --------------------------------------------------

def test_limit_order_in_continuous_session_is_admitted():
    assert HSX_EXCHANGE.admits(
        _order(), _state(session=SessionPhase.CONTINUOUS)).verdict \
        is Verdict.ADMITTED


def test_limit_order_during_the_noon_break_is_rejected():
    r = HSX_EXCHANGE.admits(_order(), _state(session=SessionPhase.NOON_BREAK))
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.SESSION_SEMANTICS


@pytest.mark.parametrize('phase', [SessionPhase.OPENING_AUCTION,
                                   SessionPhase.CLOSING_AUCTION])
def test_a_limit_order_is_legal_in_a_call_auction(phase):
    """HOSE's session table reads "LO, ATO" and "LO, ATC".

    An LO submitted into a call auction joins the auction book and matches at
    the auction price. This module used to reject every LO in every auction on
    every venue, which refuses a legal order.
    """
    r = HSX_EXCHANGE.admits(_order(order_type=OrderType.LIMIT),
                            _state(session=phase))
    assert r.verdict is Verdict.ADMITTED


@pytest.mark.parametrize('order_type', [
    OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
    OrderType.MARKET_FILL_OR_KILL,
    OrderType.MARKET_IMMEDIATE_OR_CANCEL,
    OrderType.MARKET,
])
def test_the_market_order_family_is_rejected_in_a_call_auction(order_type):
    """MTL/MOK/MAK/MKT sweep a resting book and kill the remainder. A call
    auction has no resting book while it accumulates, so their semantics have
    nothing to act on."""
    r = HSX_EXCHANGE.admits(_order(order_type=order_type, limit_price=None),
                            _state(session=SessionPhase.OPENING_AUCTION))
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.SESSION_SEMANTICS


def test_an_atc_order_is_rejected_in_the_opening_auction():
    """The right auction type, the wrong auction."""
    r = HSX_EXCHANGE.admits(
        _order(order_type=OrderType.AT_THE_CLOSE, limit_price=None),
        _state(session=SessionPhase.OPENING_AUCTION))
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.SESSION_SEMANTICS


def test_ato_order_type_is_admissible_in_the_opening_auction():
    r = HSX_EXCHANGE.admits(
        _order(order_type=OrderType.AT_THE_OPENING, limit_price=None),
        _state(session=SessionPhase.OPENING_AUCTION))
    assert r.verdict is Verdict.ADMITTED


def test_atc_order_type_is_admissible_in_the_closing_auction():
    r = HSX_EXCHANGE.admits(
        _order(order_type=OrderType.AT_THE_CLOSE, limit_price=None),
        _state(session=SessionPhase.CLOSING_AUCTION))
    assert r.verdict is Verdict.ADMITTED


def test_upcom_has_no_opening_or_closing_auction():
    """UPCOM's spec carries ato_session=None and atc_session=None."""
    r = UPCOM_EXCHANGE.admits(
        _order(order_type=OrderType.AT_THE_CLOSE, limit_price=None),
        _state(session=SessionPhase.CLOSING_AUCTION))
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.SESSION_SEMANTICS


def test_hnx_has_no_opening_auction():
    r = HNX_EXCHANGE.admits(
        _order(order_type=OrderType.AT_THE_OPENING, limit_price=None),
        _state(session=SessionPhase.OPENING_AUCTION))
    assert r.verdict is Verdict.REJECTED


def test_only_hnx_has_a_plo_session():
    ok = HNX_EXCHANGE.admits(_order(), _state(session=SessionPhase.POST_CLOSE_PLO))
    no = HSX_EXCHANGE.admits(_order(), _state(session=SessionPhase.POST_CLOSE_PLO))
    assert ok.verdict is Verdict.ADMITTED
    assert no.verdict is Verdict.REJECTED


def test_unknown_session_yields_indeterminate():
    r = HSX_EXCHANGE.admits(_order(), _state(session=SessionPhase.UNKNOWN))
    assert r.verdict is Verdict.INDETERMINATE
    assert r.rule is AdmissionRule.SESSION_SEMANTICS


def test_every_verdict_is_json_serialisable():
    import json

    for state in (_state(), _state(session=SessionPhase.NOON_BREAK),
                  _state(foreign_room=None)):
        for order in (_order(), _order(is_foreign=True)):
            json.dumps(HSX_EXCHANGE.admits(order, state).to_dict())
