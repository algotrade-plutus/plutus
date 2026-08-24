"""Bar-vs-tick divergence, pinned on one common population."""

from decimal import Decimal

import pytest

from measurements.bar_vs_tick import measure_bar_vs_tick

from .conftest import requires_corpus, requires_ticks


@pytest.fixture(scope='module')
def divergence(corpus_root, tick_root):
    if corpus_root is None or tick_root is None:
        pytest.skip('needs both corpora')
    return measure_bar_vs_tick(str(corpus_root), str(tick_root))


@requires_corpus
@requires_ticks
def test_population_reproduces_exactly(divergence):
    assert divergence.n == 173_168


@requires_corpus
@requires_ticks
def test_both_arms_share_one_denominator(divergence):
    """Without a common population the divergence is undefined."""
    assert divergence.bar_blocked <= divergence.n
    assert divergence.tick_blocked_at_close <= divergence.n
    assert divergence.tick_blocked_all_session <= divergence.n


@requires_corpus
@requires_ticks
def test_the_comparable_arm_reproduces_exactly(divergence):
    """Pinned as integers. The closing-ask tie-break is explicit
    (ORDER BY datetime DESC, price ASC) rather than arg_max, which picks
    arbitrarily among rows sharing the max timestamp and made this figure
    flip between 7,529 and 7,530 across runs."""
    assert divergence.bar_blocked == 7_170
    assert divergence.tick_blocked_at_close == 7_529
    assert divergence.both == 5_240


@requires_corpus
@requires_ticks
def test_the_bar_proxy_errs_in_both_directions(divergence):
    """It is not merely noisy: it invents locks the closing book contradicts
    AND misses locks the bar cannot see."""
    assert divergence.bar_only == 1_930
    assert divergence.tick_only == 2_289


@requires_corpus
@requires_ticks
def test_the_bar_proxy_understates_locks_on_net(divergence):
    assert divergence.tick_blocked_at_close > divergence.bar_blocked


@requires_corpus
@requires_ticks
def test_all_session_lock_is_strictly_stronger_than_at_close(divergence):
    """Nothing on offer all day implies nothing on offer at the close."""
    assert divergence.tick_blocked_all_session < divergence.tick_blocked_at_close


@requires_corpus
@requires_ticks
def test_agreement_is_high_but_not_total(divergence):
    assert Decimal('0.97') < divergence.agreement < Decimal('0.98')


@requires_corpus
@requires_ticks
def test_result_is_json_serialisable_and_names_its_population(divergence):
    import json

    decoded = json.loads(json.dumps(divergence.to_dict()))
    assert 'HSX stock ticker-days' in decoded['population']
