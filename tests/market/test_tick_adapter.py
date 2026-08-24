"""The tick adapter: observed book locks rather than inferred ones."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.adapters.datahub import DataHubSource
from plutus.market.adapters.tick import TickSource
from plutus.market.protocol import LockEvidence, Resolution

from .conftest import requires_corpus, requires_ticks


@pytest.fixture(scope='module')
def tick_source(corpus_root, tick_root):
    if corpus_root is None or tick_root is None:
        pytest.skip('needs both corpora')
    return TickSource(str(tick_root), DataHubSource.for_root(str(corpus_root)))


@requires_corpus
@requires_ticks
def test_tick_states_carry_an_observed_book(tick_source):
    states = list(tick_source.states('FPT', date(2021, 6, 15), date(2021, 6, 16)))
    assert states, 'FPT traded on 2021-06-15'
    with_book = [s for s in states if s.book and s.book.asks]
    assert with_book


@requires_corpus
@requires_ticks
def test_book_sizes_are_always_none(tick_source):
    """quote_asksize and quote_bidsize are 0-row in every corpus here, so
    depth-of-book liquidity is not measurable -- only the price ladder."""
    states = list(tick_source.states('FPT', date(2021, 6, 15), date(2021, 6, 16)))
    for state in states:
        if state.book:
            for level in state.book.asks + state.book.bids:
                assert level.size is None


@requires_corpus
@requires_ticks
def test_the_ladder_never_exceeds_three_levels(tick_source):
    """The archive carries depth 1-3; deeper requests return no rows."""
    states = list(tick_source.states('FPT', date(2021, 6, 15), date(2021, 6, 16)))
    for state in states:
        if state.book:
            assert len(state.book.asks) <= 3
            assert len(state.book.bids) <= 3


@requires_corpus
@requires_ticks
def test_lock_evidence_is_tick_book_not_bar_proxy(tick_source):
    """The whole reason this adapter exists: locks are observed, not inferred."""
    states = list(tick_source.states('FPT', date(2021, 6, 15), date(2021, 6, 16)))
    evidences = {s.lock_evidence for s in states if s.book and s.book.asks}
    assert LockEvidence.BAR_PROXY not in evidences
    assert LockEvidence.TICK_BOOK in evidences


@requires_corpus
@requires_ticks
def test_daily_resolution_is_refused(tick_source):
    with pytest.raises(ValueError, match='TICK'):
        list(tick_source.states('FPT', date(2021, 6, 15), date(2021, 6, 16),
                                resolution=Resolution.DAILY))


@requires_corpus
@requires_ticks
def test_a_ticker_with_no_ticks_yields_nothing_rather_than_guessing(tick_source):
    states = list(tick_source.states('FPT', date(2019, 1, 2), date(2019, 1, 3)))
    assert states == []
