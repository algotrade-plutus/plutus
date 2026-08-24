"""Contract months, third-Thursday expiry, and settlement provenance."""

from datetime import date
from decimal import Decimal

import pytest

from plutus.market.expiry import (
    SettlementResolver, expiry_date, parse_contract_month,
)
from plutus.market.verdicts import SettlementSource

from .conftest import requires_corpus


@pytest.mark.parametrize(
    'ticker, expected',
    [('VN30F2112', (2021, 12)), ('VN30F2206', (2022, 6)),
     ('VN30F2301', (2023, 1)), ('FPT', None), ('VN30F21XX', None),
     ('VN30F2113', None)],
)
def test_parse_contract_month(ticker, expected):
    assert parse_contract_month(ticker) == expected


@pytest.mark.parametrize(
    'ticker, expected',
    [('VN30F2112', date(2021, 12, 16)), ('VN30F2206', date(2022, 6, 16)),
     ('VN30F2203', date(2022, 3, 17)), ('VN30F2211', date(2022, 11, 17))],
)
def test_expiry_is_the_third_thursday(ticker, expected):
    got = expiry_date(ticker)
    assert got == expected
    assert got.weekday() == 3


def test_expiry_is_none_for_a_non_contract():
    assert expiry_date('FPT') is None


@requires_corpus
def test_close_proxy_is_used_when_no_published_settlement_exists(corpus_root):
    resolver = SettlementResolver.for_root(str(corpus_root))
    price, source = resolver.settlement_for('VN30F2203', date(2022, 1, 10))
    assert price is not None
    assert source is SettlementSource.CLOSE_PROXY


@requires_corpus
def test_published_settlement_wins_where_it_exists(corpus_root):
    """VN30F2206 on 2022-06-13 has a real settlement row: 1265.47."""
    resolver = SettlementResolver.for_root(str(corpus_root))
    price, source = resolver.settlement_for('VN30F2206', date(2022, 6, 13))
    assert source is SettlementSource.PUBLISHED
    assert price == pytest.approx(Decimal('1265.47'), abs=Decimal('0.01'))


@requires_corpus
def test_reference_is_never_used_as_a_settlement(corpus_root):
    """It equals the previous close on 88% of VN30F pairs and is not the
    settlement. Guard against it re-entering the chain."""
    resolver = SettlementResolver.for_root(str(corpus_root))
    for day in (date(2022, 6, 13), date(2022, 1, 10)):
        _, source = resolver.settlement_for('VN30F2206', day)
        assert source in (SettlementSource.PUBLISHED,
                          SettlementSource.CLOSE_PROXY,
                          SettlementSource.TWAP_30M)


@requires_corpus
def test_missing_day_returns_none_not_a_guess(corpus_root):
    resolver = SettlementResolver.for_root(str(corpus_root))
    price, _ = resolver.settlement_for('VN30F2206', date(2019, 1, 2))
    assert price is None
