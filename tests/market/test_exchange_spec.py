"""The renamed rulebook: ExchangeSpec carries published exchange rules as data."""

from decimal import Decimal

import pytest

from plutus.core.constant import DS, HNX, HSX, UPCOM, ExchangeSpec


def test_exchange_spec_is_the_rulebook_type():
    for spec in (HSX, HNX, UPCOM, DS):
        assert isinstance(spec, ExchangeSpec)


def test_old_name_is_gone():
    """The name Exchange is reserved for the behavioral class in plutus.market."""
    import plutus.core.constant as c

    assert not hasattr(c, 'Exchange')


@pytest.mark.parametrize(
    'spec, code, unit, limit',
    [
        (HSX, 'HSX', 100, Decimal('0.07')),
        (HNX, 'HNX', 100, Decimal('0.1')),
        (UPCOM, 'UPCOM', 100, Decimal('0.15')),
        (DS, 'HNXDS', 1, Decimal('0.07')),
    ],
)
def test_rulebook_values_survive_the_rename(spec, code, unit, limit):
    assert spec.code == code
    assert spec.trading_unit == unit
    assert Decimal(str(spec.daily_trading_limit)) == limit


def test_module_docstring_no_longer_has_the_four_quote_typo():
    import plutus.core.constant as c

    assert c.__doc__ is not None
    assert not c.__doc__.startswith('"')
