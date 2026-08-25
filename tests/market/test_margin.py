"""Variation-margin arithmetic. Exchange-side only: no P&L, no portfolio."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.margin import (
    MarginConfig, evaluate_margin, vsd_initial_margin,
)
from plutus.market.protocol import Position, Side


def _long(entry=Decimal('1441.8'), qty=1):
    return Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.BUY, quantity=qty,
        entry_price=entry, entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'),
    )


def test_defaults_are_the_documented_vietnamese_rates():
    """0.17 is VSD's published ratio. The previous 0.175 matched no source at
    any date -- see VSD_INITIAL_MARGIN for the dated series it came from."""
    c = MarginConfig.VN30F_DEFAULT
    assert c.vsd_initial == Decimal('0.17')
    assert c.broker_buffer == Decimal('0.05')
    assert c.initial_rate == Decimal('0.22')
    assert c.liquidation_rate == Decimal('0')


def test_the_vsd_ratio_is_dated_not_constant():
    """One scalar cannot hold this: VSD moved the ratio twice inside the
    corpus window, and the derivatives tax base is linear in it."""
    assert vsd_initial_margin(date(2018, 1, 1)) == Decimal('0.10')
    assert vsd_initial_margin(date(2018, 7, 18)) == Decimal('0.13')
    assert vsd_initial_margin(date(2022, 12, 14)) == Decimal('0.13')
    assert vsd_initial_margin(date(2022, 12, 15)) == Decimal('0.17')
    assert vsd_initial_margin(date(2026, 8, 25)) == Decimal('0.17')


def test_a_date_before_the_market_opened_has_no_ratio():
    """Refusing beats silently extrapolating a rate backwards."""
    with pytest.raises(ValueError, match='derivatives market opened'):
        vsd_initial_margin(date(2017, 8, 9))


def test_maintenance_is_derived_so_the_buffer_is_the_call_distance():
    """Posting 22% against a 17% requirement leaves exactly 5% of headroom.

    NOTE: `maintenance_rate` models a ratio Vietnam does not publish. This
    test pins the legacy module's internal consistency, not a market fact.
    """
    c = MarginConfig.VN30F_DEFAULT
    assert c.initial_rate - c.maintenance_rate == c.broker_buffer


def test_at_entry_the_ratio_is_the_initial_rate():
    state = evaluate_margin(_long(), Decimal('1441.8'), MarginConfig.VN30F_DEFAULT)
    assert state.ratio == pytest.approx(Decimal('0.22'), abs=Decimal('1e-9'))


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
    assert c.vsd_initial == Decimal('0.17')
    assert c.maintenance_rate == Decimal('0.17')
