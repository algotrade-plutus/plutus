"""Tick-grid conformity: the library rule against an explicitly named baseline.

The naive baseline is defined here rather than inherited. A previously-quoted
91.62% figure is not reproducible under any candidate grid and appears nowhere
in code, so this module names its own: a flat 0.1 grid over HSX closes.
"""

from decimal import Decimal

import pytest

from measurements.grid_conformity import NAIVE_LABEL, measure_grid_conformity

from .conftest import requires_corpus


@pytest.fixture(scope='module')
def all_hsx(corpus_root):
    return measure_grid_conformity(str(corpus_root), stocks_only=False)


@requires_corpus
def test_library_rule_reproduces_the_grid_almost_exactly(all_hsx):
    assert all_hsx.observations == 1_101_201
    assert all_hsx.library_rate > Decimal('0.9999')


@requires_corpus
def test_the_residual_is_thirteen_real_off_grid_prices(all_hsx):
    """Not rounded away. These are corpus defects: two-decimal closes inside
    the 0.05 band, which could not legally have traded."""
    assert len(all_hsx.off_grid) == 13
    tickers = {row[0] for row in all_hsx.off_grid}
    assert tickers == {'DAG', 'C47', 'SVI', 'NLG', 'CCI', 'MCP'}
    for _, _, price, tick in all_hsx.off_grid:
        assert tick is not None
        assert price % tick != 0


@requires_corpus
def test_all_off_grid_prices_predate_2016(all_hsx):
    for _, day, _, _ in all_hsx.off_grid:
        assert day.year < 2016


@requires_corpus
def test_the_naive_baseline_is_far_worse_and_is_named(all_hsx):
    assert all_hsx.naive_rate < Decimal('0.85')
    assert all_hsx.library_rate > all_hsx.naive_rate
    assert all_hsx.naive_baseline == NAIVE_LABEL


@requires_corpus
def test_no_price_is_unresolvable_on_this_corpus(all_hsx):
    """get_hsx_tick_size returns None for prices no band matches; none occur."""
    assert all_hsx.unresolvable == 0


@requires_corpus
def test_stocks_only_universe_is_smaller_but_equally_conformant(corpus_root,
                                                                all_hsx):
    stocks = measure_grid_conformity(str(corpus_root), stocks_only=True)
    assert stocks.observations == 1_086_518
    assert stocks.observations < all_hsx.observations
    assert stocks.library_rate > Decimal('0.9999')


@requires_corpus
def test_result_is_json_serialisable(all_hsx):
    import json

    decoded = json.loads(json.dumps(all_hsx.to_dict()))
    assert len(decoded['off_grid']) == 13
    assert decoded['naive_baseline'] == NAIVE_LABEL
