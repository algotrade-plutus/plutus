"""Does the account-level margin model reproduce the published figures?

The published derivatives headline -- 29 / 48 / 56 front-month longs called
out of 381, at 5 / 10 / 20 sessions held -- was measured through the legacy
per-position path, which tests a maintenance margin ratio Vietnam does not
publish. Before that headline is restated, the account-level model has to be
shown to reproduce it.

**It does not.** These tests pin the disagreement, its size, and the reason,
so that a later change to either path is a test failure rather than a quietly
different number in a paper.
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from measurements.margin_incidence import measure_margin_incidence
from measurements.margin_incidence_account import (
    AGREEMENT_TOLERANCE, BEST_JOINT_FIT, FUNDED_AT_REQUIREMENT,
    FUNDING_PROVENANCE, PUBLISHED_CALLS, MarginPathComparison,
    compare_margin_paths, funding_multiple_sweep,
    measure_account_margin_incidence,
)
from plutus.market import margin as legacy_margin

from .conftest import requires_corpus


# --------------------------------------------------------------------------
# Structure -- no corpus needed
# --------------------------------------------------------------------------

def test_the_tolerance_is_stated_before_the_measurement_not_after():
    """A tolerance chosen once the gap is known is not a tolerance.

    One percentage point of call rate, declared as a module constant, and the
    verdict is a pure function of it. The published headline's own sensitivity
    to the posted initial rate is 26.25% -> 6.82% across five points, so one
    point is comfortably inside the assumptions the figure already carries.
    """
    assert AGREEMENT_TOLERANCE == Decimal('0.01')

    def comparison(gap):
        return MarginPathComparison(
            holding_days=10, entries=381, legacy_called=48,
            account_called=48, legacy_call_rate=Decimal('0.126'),
            account_call_rate=Decimal('0.126') + gap,
            funding_multiple=Decimal('1'), tolerance=AGREEMENT_TOLERANCE,
            legacy_initial_rate=Decimal('0.22'))

    assert comparison(Decimal('0.01')).verdict == 'AGREE'
    assert comparison(Decimal('-0.01')).verdict == 'AGREE'
    assert comparison(Decimal('0.0101')).verdict == 'DISAGREE'
    assert comparison(Decimal('0.02')).gap == Decimal('0.02')


def test_the_comparison_names_both_models_and_never_picks_one():
    """A serialised comparison carries both shapes, so neither can be quoted
    alone by a reader who did not read this module."""
    payload = MarginPathComparison(
        holding_days=10, entries=381, legacy_called=48, account_called=381,
        legacy_call_rate=Decimal('0.126'), account_call_rate=Decimal('1'),
        funding_multiple=FUNDED_AT_REQUIREMENT,
        tolerance=AGREEMENT_TOLERANCE,
        legacy_initial_rate=Decimal('0.22')).to_dict()
    assert payload['verdict'] == 'DISAGREE'
    assert 'does not publish' in payload['legacy_model']
    assert 'utilisation' in payload['account_model']
    assert json.loads(json.dumps(payload))['holding_days'] == 10


def test_the_funding_multiple_is_declared_an_assumption_and_the_fit_a_fit():
    """The free parameter says it is one, and the fitted value says so twice.

    ``BEST_JOINT_FIT`` exists only to show that even the best fit misses. A
    reader who lifts it as a market value has to get past two sentences saying
    it is not one.
    """
    assert FUNDED_AT_REQUIREMENT == Decimal('1')
    assert BEST_JOINT_FIT > FUNDED_AT_REQUIREMENT
    assert 'ASSUMPTION' in FUNDING_PROVENANCE['funding_multiple']
    assert 'fitted' in FUNDING_PROVENANCE['funding_multiple']
    assert 'never be quoted' in FUNDING_PROVENANCE['funding_multiple']
    for key in ('broker_buffer', 'utilisation_ladder', 'initial_margin_rate',
                'variation_margin_baseline'):
        assert FUNDING_PROVENANCE[key]


def test_the_legacy_module_says_it_models_a_quantity_that_does_not_exist():
    """The retirement decision is pending, so the label has to carry it.

    No ``DeprecationWarning``: the path is still the one the published figures
    came from and cannot honestly warn that it is going away. What it can do
    is say, in machine-readable form, what it models and where the replacement
    and the evidence are.
    """
    provenance = legacy_margin.PROVENANCE
    assert 'DOES NOT EXIST' in provenance['maintenance_rate']
    assert 'utilisation' in provenance['maintenance_rate']
    assert 'account_margin_requirement' in provenance['replacement']
    assert 'margin_incidence_account' in provenance['reproduction']
    assert 'DISAGREE' in provenance['reproduction']
    assert 'published margin-incidence figures' in provenance['kept_because']
    assert legacy_margin.MarginConfig.PROVENANCE is provenance
    assert 'DOES NOT EXIST' in legacy_margin.__doc__


def test_the_legacy_walk_warns_where_a_caller_would_actually_look():
    """A module docstring nobody opens is not a warning.

    ``sustains`` is the entry point a caller reaches for, so the label has to
    be on it -- naming the test it runs, the test the market runs, and why it
    was not simply rewired.
    """
    from plutus.market.exchanges.derivatives import HNXDSExchange

    doc = HNXDSExchange.sustains.__doc__
    assert 'does not exist' in doc
    assert 'utilisation' in doc
    assert 'account_margin_requirement' in doc
    assert 'restate' in doc
    assert 'legacy' in HNXDSExchange.__doc__


# --------------------------------------------------------------------------
# The measurement
# --------------------------------------------------------------------------

@requires_corpus
def test_both_paths_walk_exactly_the_same_entries(corpus_root):
    """The comparison is like for like or it is nothing.

    The account path takes its entries from ``margin_incidence``'s own
    front-month query rather than a second copy of it, so a difference in the
    counts can only be a difference in the models.
    """
    legacy = measure_margin_incidence(str(corpus_root), holding_days=10)
    account = measure_account_margin_incidence(
        str(corpus_root), holding_days=10)
    assert legacy.entries == account.entries == 381
    assert legacy.contracts == account.contracts


@requires_corpus
@pytest.mark.parametrize('holding_days', [5, 10, 20])
def test_funded_at_the_requirement_the_account_model_calls_everything(
        corpus_root, holding_days):
    """Utilisation is exactly 1.00 the instant the position opens.

    This is not a bug and it is the heart of the disagreement. ``MR / assets``
    with assets equal to the opening requirement is 1.00 by construction, and
    1.00 is the top rung. The legacy model cannot express this state at all,
    because it never asks how much was deposited -- it derives posted margin
    from entry notional and then measures a *different* ratio.

    So at the one funding level that is not fitted to the answer, the two
    paths are 85 to 92 percentage points apart.
    """
    comparison = compare_margin_paths(
        str(corpus_root), holding_days=holding_days,
        funding_multiple=FUNDED_AT_REQUIREMENT)
    assert comparison.entries == 381
    assert comparison.account_called == 381
    assert comparison.legacy_called == PUBLISHED_CALLS[holding_days]
    assert comparison.verdict == 'DISAGREE'
    assert comparison.gap > Decimal('0.85')
    assert any('1.00 on entry' in note for note in comparison.notes)


@requires_corpus
def test_no_funding_multiple_reproduces_all_three_published_counts(
        corpus_root):
    """The strong form of the finding, and the reason it is a sweep.

    A disagreement at one funding level can always be dismissed as the wrong
    parameter. So the parameter is swept over its whole plausible range in
    hundredths, and *no* row lands on 29 / 48 / 56. The best fit, 1.42, is off
    by 8 entries in total -- and it is a value fitted to the published answer,
    with no source and nothing in either corpus to support it.
    """
    multiples = tuple(Decimal(x) / Decimal('100') for x in range(100, 201))
    rows = funding_multiple_sweep(str(corpus_root), multiples=multiples)
    assert len(rows) == 101
    assert all(row['absolute_error_vs_published'] > 0 for row in rows)

    best = min(rows, key=lambda r: r['absolute_error_vs_published'])
    assert best['funding_multiple'] == pytest.approx(float(BEST_JOINT_FIT))
    assert best['absolute_error_vs_published'] == 8


@requires_corpus
def test_the_best_fit_lands_on_ten_sessions_and_still_misses_twenty(
        corpus_root):
    """Even fitted, the two disagree where it counts.

    At 1.42 the ten-session count is exact -- 48 of 381, the published
    headline -- and the twenty-session count is 63 against 56, an overstated
    16.54% against 14.70%. That 1.84-point miss is what "the call boundaries
    move differently in the size of the loss" looks like as a number: fitting
    one holding period cannot fit the others, because the two models are not
    the same function of the loss.
    """
    ten = compare_margin_paths(str(corpus_root), holding_days=10,
                               funding_multiple=BEST_JOINT_FIT)
    twenty = compare_margin_paths(str(corpus_root), holding_days=20,
                                  funding_multiple=BEST_JOINT_FIT)
    assert ten.account_called == ten.legacy_called == 48
    assert ten.verdict == 'AGREE'

    assert twenty.legacy_called == 56
    assert twenty.account_called == 63
    assert twenty.verdict == 'DISAGREE'
    assert twenty.gap == pytest.approx(Decimal('0.0184'), abs=Decimal('0.0005'))
    assert any('fitted to the answer' in note for note in twenty.notes)


@requires_corpus
def test_daily_rebaselining_without_the_cash_leg_loses_the_whole_loss(
        corpus_root):
    """The Tier 1 simplification, priced.

    VSDC rebaselines variation margin to each day's settlement price *and*
    moves the day's P&L as cash on T+1. Tier 1 models the first and not the
    second, so with ``settle_daily=True`` a position that has fallen for ten
    sessions carries only the last session's move in ``MR`` and has paid for
    none of the rest. Measured, that takes the ten-session incidence from
    12.60% to 2.36% -- more than ten points of understatement, which is why
    the comparison above runs with the baseline held at entry.
    """
    rebaselined = measure_account_margin_incidence(
        str(corpus_root), holding_days=10, funding_multiple=BEST_JOINT_FIT,
        settle_daily=True)
    held = measure_account_margin_incidence(
        str(corpus_root), holding_days=10, funding_multiple=BEST_JOINT_FIT)
    assert rebaselined.settle_daily is True
    assert rebaselined.called == 9
    assert held.called == 48
    assert held.call_rate - rebaselined.call_rate > Decimal('0.10')


@requires_corpus
def test_the_two_paths_post_different_initial_margin_rates_on_this_window(
        corpus_root):
    """A second, independent gap: the legacy path's rate is undated.

    ``MarginConfig`` holds 0.17 whatever the date, so the published figures
    post 22% across a window in which VSDC's ratio was 13% until 2022-12-15 --
    371 of the 381 entries. The account path resolves it per date. The two
    numbers below are therefore not comparable as "the same model at a
    different rate": they are two rate series, and only one of them is the
    published one.
    """
    legacy = measure_margin_incidence(str(corpus_root), holding_days=10)
    assert legacy.initial_rate == Decimal('0.22')

    account = measure_account_margin_incidence(
        str(corpus_root), holding_days=10, broker_buffer=Decimal('0.05'))
    assert account.broker_buffer == Decimal('0.05')
    assert '371 of 381' in FUNDING_PROVENANCE['initial_margin_rate']
    assert legacy_margin.vsd_initial_margin(date(2022, 6, 1)) == Decimal('0.13')


@requires_corpus
def test_the_account_result_is_json_safe_and_carries_its_assumption(
        corpus_root):
    result = measure_account_margin_incidence(
        str(corpus_root), holding_days=5).to_dict()
    decoded = json.loads(json.dumps(result))
    assert decoded['entries'] == 381
    assert 'utilisation' in decoded['model']
    assert 'ASSUMPTION' in decoded['funding_is_an_assumption']
