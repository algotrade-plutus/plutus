"""Variation-margin arithmetic. Exchange-side only: no P&L, no portfolio."""

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.margin import MarginConfig, evaluate_margin
from plutus.market.protocol import Position, Side


def _long(entry=Decimal('1441.8'), qty=1):
    return Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.BUY, quantity=qty,
        entry_price=entry, entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'),
    )


def test_defaults_are_the_documented_vietnamese_rates():
    c = MarginConfig.VN30F_DEFAULT
    assert c.vsd_initial == Decimal('0.175')
    assert c.broker_buffer == Decimal('0.05')
    assert c.initial_rate == Decimal('0.225')
    assert c.maintenance_rate == Decimal('0.175')
    assert c.liquidation_rate == Decimal('0')


def test_maintenance_is_derived_so_the_buffer_is_the_call_distance():
    """Posting 22.5% against a 17.5% requirement leaves exactly 5% of headroom."""
    c = MarginConfig.VN30F_DEFAULT
    assert c.initial_rate - c.maintenance_rate == c.broker_buffer


def test_at_entry_the_ratio_is_the_initial_rate():
    state = evaluate_margin(_long(), Decimal('1441.8'), MarginConfig.VN30F_DEFAULT)
    assert state.ratio == pytest.approx(Decimal('0.225'), abs=Decimal('1e-9'))


def test_a_long_loses_equity_as_the_settlement_falls():
    c = MarginConfig.VN30F_DEFAULT
    at_entry = evaluate_margin(_long(), Decimal('1441.8'), c)
    lower = evaluate_margin(_long(), Decimal('1400.0'), c)
    assert lower.equity < at_entry.equity
    assert lower.ratio < at_entry.ratio


def test_a_short_gains_equity_as_the_settlement_falls():
    c = MarginConfig.VN30F_DEFAULT
    short = Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.SELL, quantity=1,
        entry_price=Decimal('1441.8'), entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'),
    )
    assert evaluate_margin(short, Decimal('1400.0'), c).equity > \
        evaluate_margin(short, Decimal('1441.8'), c).equity


def test_quantity_scales_notional_and_equity_but_not_the_ratio():
    c = MarginConfig.VN30F_DEFAULT
    one = evaluate_margin(_long(qty=1), Decimal('1400.0'), c)
    ten = evaluate_margin(_long(qty=10), Decimal('1400.0'), c)
    assert ten.notional == one.notional * 10
    assert ten.ratio == pytest.approx(one.ratio, abs=Decimal('1e-12'))


def test_posted_margin_can_be_supplied_explicitly():
    p = Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.BUY, quantity=1,
        entry_price=Decimal('1441.8'), entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'), posted_margin=Decimal('50000000'),
    )
    got = evaluate_margin(p, Decimal('1441.8'), MarginConfig.VN30F_DEFAULT)
    assert got.equity == Decimal('50000000')


def test_a_settlement_of_zero_is_rejected_rather_than_dividing_by_zero():
    with pytest.raises(ValueError, match='settlement'):
        evaluate_margin(_long(), Decimal('0'), MarginConfig.VN30F_DEFAULT)


def test_with_initial_moves_only_the_buffer():
    c = MarginConfig.VN30F_DEFAULT.with_initial(Decimal('0.300'))
    assert c.initial_rate == Decimal('0.300')
    assert c.vsd_initial == Decimal('0.175')
    assert c.maintenance_rate == Decimal('0.175')
