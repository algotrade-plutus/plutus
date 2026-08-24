"""The paper's equity number, pinned as integers.

Both lag variants are asserted. lag=1 is the tradeable rule and the honest
headline; lag=0 is the figure prior work quoted and embeds look-ahead, because
it tests the lock on the same session that produced the signal.
"""

from decimal import Decimal

import pytest

from measurements.equity_admission import measure_blocked_entries

from .conftest import requires_corpus


@pytest.fixture(scope='module')
def same_session(corpus_root):
    return measure_blocked_entries(str(corpus_root), lag=0, stocks_only=True)


@pytest.fixture(scope='module')
def next_session(corpus_root):
    return measure_blocked_entries(str(corpus_root), lag=1, stocks_only=True)


@requires_corpus
def test_same_session_variant_reproduces_exactly(same_session):
    """Integers, not a tolerance: the population is deterministic."""
    assert same_session.attempts == 197_337
    assert same_session.blocked == 25_464
    assert same_session.rate == pytest.approx(Decimal('0.129038'),
                                              abs=Decimal('0.000001'))


@requires_corpus
def test_next_session_variant_reproduces_exactly(next_session):
    assert next_session.attempts == 197_521
    assert next_session.blocked == 11_543
    assert next_session.rate == pytest.approx(Decimal('0.058439'),
                                              abs=Decimal('0.000001'))


@requires_corpus
def test_all_instruments_variants_reproduce(corpus_root):
    same = measure_blocked_entries(str(corpus_root), lag=0, stocks_only=False)
    nxt = measure_blocked_entries(str(corpus_root), lag=1, stocks_only=False)
    assert (same.blocked, same.attempts) == (27_216, 210_459)
    assert (nxt.blocked, nxt.attempts) == (12_520, 210_563)


@requires_corpus
def test_the_lag_more_than_halves_the_rate(same_session, next_session):
    """The look-ahead in the same-session rule is the whole story."""
    assert same_session.rate > next_session.rate * 2


@requires_corpus
def test_the_lead_is_computed_over_the_full_series_not_the_filtered_one(
        next_session, same_session):
    """Regression guard for a subtle SQL bug.

    Window functions evaluate after WHERE. Computing lead() alongside the
    momentum filter yields the next *momentum day* rather than the next
    *session*, which produces ~12.88% -- nearly indistinguishable from the
    same-session figure, because momentum days cluster. If these two rates ever
    come within a percentage point of each other, that bug is back.
    """
    assert abs(same_session.rate - next_session.rate) > Decimal('0.05')


@requires_corpus
def test_inverted_bands_are_excluded_and_the_count_is_reported(next_session):
    """1,226 of the 1,272 inverted pairs are cash stock ticker-days, so this
    filter is load-bearing rather than cosmetic."""
    assert next_session.excluded_inverted == 1272


@requires_corpus
def test_an_invalid_lag_is_rejected(corpus_root):
    with pytest.raises(ValueError, match='lag'):
        measure_blocked_entries(str(corpus_root), lag=2)


@requires_corpus
def test_every_result_is_json_serialisable(next_session):
    import json

    decoded = json.loads(json.dumps(next_session.to_dict()))
    assert decoded['lag'] == 1
    assert decoded['population'] == 'stocks'
    assert decoded['variant'] == 'next_session_tradeable'
