"""Does the account-level margin model reproduce the published figures?

The published derivatives headline -- 29 / 48 / 56 front-month longs called
out of 381, at 5 / 10 / 20 sessions held -- was measured through the legacy
per-position path, which tests a maintenance margin ratio Vietnam does not
publish. Before that headline is restated, the account-level model has to be
shown to reproduce it.

**It does, and the earlier answer of "it does not" was wrong twice.** See
``docs/reference/margin-model-adjudication.md``. The two errors are pinned
here so neither can come back:

1. At :data:`FUNDED_AT_REQUIREMENT` the 100% call rate is an **arithmetic
   identity**, not a measurement -- ``MR / assets >= 1`` at every price,
   including a rally and including no move at all. A statistic that cannot
   vary with the data is not evidence of a disagreement about the data.
2. The 20-session miss at the fitted multiple is the **2022-12-15 initial
   margin step**, not a difference in how the two models' call boundaries
   move in the size of the loss. Freeze the ratio at the entry date and
   ``funding_multiple = 1.4120`` reproduces 29 / 48 / 56 exactly.

The published figures are still not restated anywhere: both paths stay
measured and both numbers stay reported.
"""

import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from measurements.margin_incidence import (
    _front_month_series, measure_margin_incidence,
)
from measurements.margin_incidence_account import (
    AGREEMENT_TOLERANCE, BEST_JOINT_FIT, DEGENERACY_PROVENANCE,
    FUNDED_AT_REQUIREMENT, FUNDING_PROVENANCE, PUBLISHED_CALLS,
    REPRODUCING_FUNDING, REQUIREMENT_QUANTILES, VN30F_MULTIPLIER,
    MarginPathComparison, PeakRequirementResult, compare_margin_paths,
    degenerate_funding_ceiling, funding_multiple_sweep,
    measure_account_margin_incidence, measure_peak_requirement,
)
from plutus.market import margin as legacy_margin
from plutus.market.broker import BrokerTerms
from plutus.market.session.deposit import ContractLedger, DerivativesAccount
from plutus.market.session.ledgers import EncumbranceLedger
from plutus.market.session.types import (
    AccountRef, Fill, FillEvidence, MarginStatus, Side, Venue,
)

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

    This test deliberately does **not** pin the *verdict* recorded in
    ``PROVENANCE['reproduction']``. That verdict said DISAGREE, the
    adjudication overturned it, and the wording of ``plutus.market.margin`` is
    owned elsewhere -- pinning a conclusion in a file this suite does not own
    is how a superseded finding survives its own refutation. What is pinned is
    that the label exists and points at the evidence.
    """
    provenance = legacy_margin.PROVENANCE
    assert 'DOES NOT EXIST' in provenance['maintenance_rate']
    assert 'utilisation' in provenance['maintenance_rate']
    assert 'account_margin_requirement' in provenance['replacement']
    assert 'margin_incidence_account' in provenance['reproduction']
    assert 'published margin-incidence figures' in provenance['kept_because']
    assert legacy_margin.MarginConfig.PROVENANCE is provenance
    assert 'DOES NOT EXIST' in legacy_margin.__doc__


# --------------------------------------------------------------------------
# The degeneracy -- arithmetic, no corpus, no price series
# --------------------------------------------------------------------------

_TS = datetime(2022, 6, 1, 10, 0)
_CODE = 'VN30F2206'
_ENTRY = Decimal('1280')
_TICK = Decimal('0.1')


def _one_contract_account(funding_multiple, buffer_=Decimal('0.05')):
    """A real account holding one long, funded at ``funding_multiple x IM``."""
    rate = legacy_margin.vsd_initial_margin(_TS.date()) + buffer_
    deposit = (funding_multiple * rate * VN30F_MULTIPLIER
               * _ENTRY).quantize(Decimal('1'))
    account = DerivativesAccount(
        AccountRef.derivatives('degeneracy'), deposit, BrokerTerms.DEFAULT,
        EncumbranceLedger(), ContractLedger(), margin_buffer=buffer_,
        multipliers={_CODE: VN30F_MULTIPLIER}, opened_at=_TS)
    account.apply_fill(
        Fill(fill_id='f', order_id='o', ticker=_CODE, venue=Venue.HNXDS,
             side=Side.BUY, quantity=1, price=_ENTRY, ts=_TS,
             evidence=FillEvidence.TRADED_THROUGH), rules=None, ts=_TS)
    return account


@pytest.mark.parametrize('price,label', [
    (_ENTRY, 'no move at all'),
    (_ENTRY + _TICK, 'one tick up'),
    (_ENTRY - _TICK, 'one tick down'),
    (_ENTRY * Decimal('1.07'), 'limit up'),
    (_ENTRY * Decimal('0.93'), 'limit down'),
])
def test_funded_at_the_requirement_every_price_is_forced(price, label):
    """The heart of the adjudication, and it needs no data.

    ``MR = IM(current price) + max(0, loss)`` and assets are frozen at the
    deposit, so with the deposit equal to the opening ``IM``::

        price >= entry:  MR/assets = price / entry           >= 1
        price <  entry:  MR/assets = 1 + d(1-r)/r            >  1

    The floor is exactly 1.0000 and it is attained only when the price has not
    moved. ``forced_close_utilisation`` is 1.00 and the comparison in
    ``margin_status`` is ``>=``, so **every** price is FORCED -- including a
    rally, because IM is recomputed on the higher price while the profit is
    not credited to assets (a documented Tier 1 gap: the T+1 cash leg is not
    modelled).

    A 100% call rate measured at this funding level is therefore an identity.
    It would read 100% on a constant price series, on any instrument, in any
    country whose rule has this shape.
    """
    account = _one_contract_account(FUNDED_AT_REQUIREMENT)
    marks = {_CODE: price}
    account.observe_marks(marks, _TS)
    view = account.margin(marks, None, BrokerTerms.DEFAULT, _TS)
    assert view.status is MarginStatus.FORCED, label
    assert view.required / view.deposit_balance >= Decimal('1')
    if price == _ENTRY:
        assert view.required == view.deposit_balance


def test_the_funding_level_below_which_each_rung_is_certain_is_derived():
    """Name the degenerate region rather than rediscovering it per rung.

    Utilisation is ``U / k`` where ``U = MR / opening IM >= 1`` always, so a
    rung ``theta`` is breached at **every** price whenever ``k <= 1/theta``.
    Below those multiples the corresponding rate is a constant, not a
    measurement, and a sweep that starts at 1.00 spends its first quarter
    inside that region.
    """
    ceiling = degenerate_funding_ceiling(BrokerTerms.DEFAULT)
    assert ceiling['warning'] == Decimal('1') / Decimal('0.80')
    assert ceiling['margin_call'] == Decimal('1') / Decimal('0.90')
    assert ceiling['forced_close'] == Decimal('1') / Decimal('1.00')
    assert ceiling['warning'] > ceiling['margin_call'] > \
        ceiling['forced_close']

    tighter = degenerate_funding_ceiling(BrokerTerms(
        warning_utilisation=Decimal('0.75'),
        margin_call_utilisation=Decimal('0.85'),
        forced_close_utilisation=Decimal('0.90')))
    assert tighter['forced_close'] == Decimal('1') / Decimal('0.90')

    degeneracy = DEGENERACY_PROVENANCE['funded_at_requirement'].lower()
    assert 'identity' in degeneracy
    assert 'rally' in degeneracy
    assert DEGENERACY_PROVENANCE['call_rate_as_a_metric']
    assert DEGENERACY_PROVENANCE['overlapping_windows']


def test_the_module_records_that_a_funding_multiple_does_reproduce():
    """The retracted claim, retracted in machine-readable form.

    ``REPRODUCING_FUNDING`` carries the intervals that were measured, so the
    superseded sentence cannot be quoted from this module any more.
    """
    frozen = REPRODUCING_FUNDING['frozen_initial_rate']
    assert frozen['low'] < Decimal('1.4120') < frozen['high']
    assert frozen['counts'] == dict(PUBLISHED_CALLS)
    assert 'dated' in REPRODUCING_FUNDING
    assert REPRODUCING_FUNDING['dated']['counts'][20] != PUBLISHED_CALLS[20]
    assert 'grid' in REPRODUCING_FUNDING['why_the_sweep_missed_it']
    assert '2022-12-15' in REPRODUCING_FUNDING['why_the_sweep_missed_it']


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
    """100% at every holding period, on the first mark, every time.

    The identity proved without data in
    ``test_funded_at_the_requirement_every_price_is_forced``, now measured on
    the corpus. The tell is that the answer does not move with
    ``holding_days``: 5, 10 and 20 sessions all read 381 of 381 because every
    entry is FORCED on its **first** marked bar, so the holding period is
    never an input.

    This is not evidence that the two models disagree. It is evidence that the
    experiment was run at a funding level where the metric is a constant.
    """
    comparison = compare_margin_paths(
        str(corpus_root), holding_days=holding_days,
        funding_multiple=FUNDED_AT_REQUIREMENT)
    assert comparison.entries == 381
    assert comparison.account_called == 381
    assert comparison.legacy_called == PUBLISHED_CALLS[holding_days]
    assert comparison.gap > Decimal('0.85')
    assert any('identity' in note for note in comparison.notes)

    account = measure_account_margin_incidence(
        str(corpus_root), holding_days=holding_days,
        funding_multiple=FUNDED_AT_REQUIREMENT)
    assert account.warned == account.called == account.forced == 381
    assert account.forced_on_first_mark == 381


@requires_corpus
def test_the_published_sweep_misses_the_reproducing_multiple_two_ways(
        corpus_root):
    """Why the module once said *no* multiple reproduces the counts.

    Both reasons are measured here rather than argued:

    * **The grid.** Hundredths from 1.00 to 2.00 never evaluate the interval
      that reproduces the counts, which is ``[1.4110, 1.4136]`` -- strictly
      between two grid points.
    * **The rate confound.** The account path re-resolves VSDC's ratio at each
      marked bar while the legacy path posts an undated 22%, so windows
      straddling the 2022-12-15 step are priced on two different rate series.

    The sweep row itself is unchanged and still reported: on this grid, with
    the dated rate, no row lands on 29 / 48 / 56 and the best is 1.42 at 8
    entries of total error. What changed is the conclusion drawn from it.
    """
    multiples = tuple(Decimal(x) / Decimal('100') for x in range(100, 201))
    rows = funding_multiple_sweep(str(corpus_root), multiples=multiples)
    assert len(rows) == 101
    assert all(row['absolute_error_vs_published'] > 0 for row in rows)

    best = min(rows, key=lambda r: r['absolute_error_vs_published'])
    assert best['funding_multiple'] == pytest.approx(float(BEST_JOINT_FIT))
    assert best['absolute_error_vs_published'] == 8

    # The interval the grid stepped over.
    interval = REPRODUCING_FUNDING['frozen_initial_rate']
    assert not any(interval['low'] <= Decimal(str(row['funding_multiple']))
                   <= interval['high'] for row in rows)


@requires_corpus
def test_freezing_the_initial_rate_reproduces_all_three_published_counts(
        corpus_root):
    """The retraction, measured.

    ``funding_multiple = 1.4120`` with VSDC's ratio held at the entry date
    gives **29 / 48 / 56** -- the published counts, exactly, at all three
    holding periods. Re-resolving the ratio at each bar instead moves only the
    20-session count, 56 -> 64, and every one of those eight extra calls sits
    in a window straddling 2022-12-15.

    So the 20-session miss was never "the two models' call boundaries move
    differently in the size of the loss". Both models test the same thing --
    max drawdown from entry against a threshold -- and the residual was a
    regulatory event that one path priced and the other did not.
    """
    k = Decimal('1.4120')
    frozen = {h: measure_account_margin_incidence(
        str(corpus_root), holding_days=h, funding_multiple=k,
        freeze_initial_rate=True).called for h in (5, 10, 20)}
    assert frozen == dict(PUBLISHED_CALLS)

    dated = {h: measure_account_margin_incidence(
        str(corpus_root), holding_days=h, funding_multiple=k).called
        for h in (5, 10, 20)}
    assert dated[5] == PUBLISHED_CALLS[5]
    assert dated[10] == PUBLISHED_CALLS[10]
    assert dated[20] == 64

    assert measure_account_margin_incidence(
        str(corpus_root), holding_days=20, funding_multiple=k,
        freeze_initial_rate=True).freeze_initial_rate is True


@requires_corpus
def test_the_best_fit_lands_on_ten_sessions_and_still_misses_twenty(
        corpus_root):
    """The originally reported miss, kept and re-explained.

    At 1.42 with the dated ratio the ten-session count is exact -- 48 of 381 --
    and the twenty-session count is 63 against 56. The number is unchanged;
    the reason is not what the module used to say. Freezing the ratio at the
    entry date takes the same 1.42 to 54, an *under*-count, which is what a
    threshold slightly too strict looks like once the regulatory step is out
    of the comparison. A structural difference in "how the boundaries move in
    the size of the loss" could not flip sign like that.
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

    frozen = measure_account_margin_incidence(
        str(corpus_root), holding_days=20, funding_multiple=BEST_JOINT_FIT,
        freeze_initial_rate=True)
    assert frozen.called == 54


@requires_corpus
def test_daily_cash_settlement_now_captures_the_loss_the_rebaseline_alone_lost(
        corpus_root):
    """The Tier 1 simplification, now removed (MUST #4).

    VSDC rebaselines variation margin to each day's settlement price *and*
    moves the day's P&L as cash on T+1. ``settle_daily`` now does BOTH -- it
    moves the cash (QD 26 Dieu 20) -- so a position that has fallen for ten
    sessions has *paid* the loss out of the deposit rather than having it vanish
    when the baseline rolled. The incidence is therefore close to the
    baseline-held-at-entry walk (both capture the cumulative loss, one as
    depleted cash, the other as VM in the requirement), where before the cash
    leg was wired it collapsed to 9 -- the >10-point understatement this test
    used to price. (The legacy maintenance-ratio path itself is retired in W4.)
    """
    settled = measure_account_margin_incidence(
        str(corpus_root), holding_days=10, funding_multiple=BEST_JOINT_FIT,
        settle_daily=True)
    held = measure_account_margin_incidence(
        str(corpus_root), holding_days=10, funding_multiple=BEST_JOINT_FIT)
    assert settled.settle_daily is True
    assert settled.called == 44        # was 9 before the cash leg; now captures the loss
    assert held.called == 48
    # Both now capture the loss, so the gap is small -- not the 10+ points the
    # rebaseline-without-cash artefact produced.
    assert abs(held.call_rate - settled.call_rate) < Decimal('0.05')


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


# --------------------------------------------------------------------------
# The replacement statistic: peak requirement, no funding parameter
# --------------------------------------------------------------------------

@requires_corpus
def test_the_peak_requirement_matches_a_closed_form_computed_off_the_prices(
        corpus_root):
    """The statistic is re-derived from the price series and must agree.

    ``measure_peak_requirement`` walks a real
    :class:`~plutus.market.session.deposit.DerivativesAccount` and reads
    ``MarginView.required``. This test never touches the account: it
    recomputes each window's peak from the two closed-form branches

        price >= entry:   U = price / entry
        price <  entry:   U = 1 + drawdown x (1 - r) / r

    and asserts the samples agree. Two independent expressions of the same
    quantity, so a change to either the walk or the requirement formula that
    moves one and not the other fails here rather than in a paper.

    Compared at 1e-12, not exactly: ``(r p + (p0 - p)) / (r p0)`` and
    ``1 + d (1 - r) / r`` are the same number and divide in a different order,
    so they part company in the 28th significant digit of a ``Decimal``.
    Rounding at the 12th is not a tolerance on the finding -- the smallest
    quantity of interest here is a basis point.
    """
    series = _front_month_series(corpus_root)
    rate = legacy_margin.vsd_initial_margin  # dated, buffer 0
    grain = Decimal('1e-12')

    def expected(holding_days):
        out = []
        for _ticker, observations in series.items():
            for i in range(len(observations) - 1):
                window = observations[i:i + holding_days + 1]
                if len(window) < 2:
                    continue
                entry_day, entry = window[0]
                r0 = rate(entry_day)
                peak = None
                for _day, price in window[1:]:
                    if price >= entry:
                        u = price / entry
                    else:
                        drawdown = (entry - price) / entry
                        u = 1 + drawdown * (1 - r0) / r0
                    if peak is None or u > peak:
                        peak = u
                out.append(peak.quantize(grain))
        return out

    for holding_days in (5, 10, 20):
        result = measure_peak_requirement(
            str(corpus_root), holding_days=holding_days,
            freeze_initial_rate=True)
        measured = [value.quantize(grain) for value in result.peak_multiples]
        assert measured == expected(holding_days)


@requires_corpus
def test_the_peak_requirement_is_the_utilisation_of_an_account_at_the_minimum(
        corpus_root):
    """The degenerate experiment and the useful statistic are one sample.

    An account funded at exactly the opening requirement has
    ``utilisation = MR / IM_0``, which *is* the peak multiple. So the 100%
    call rate is this distribution collapsed to ``P(U* >= 1)``, and every
    value of that indicator is 1 because ``U* >= 1`` identically. Reporting
    the distribution instead of the indicator recovers everything the
    experiment threw away, and needs no funding assumption to do it.
    """
    result = measure_peak_requirement(str(corpus_root), holding_days=10,
                                      broker_buffer=Decimal('0.05'))
    assert result.entries == 381
    assert min(result.peak_multiples) >= Decimal('1')
    assert result.call_rate(FUNDED_AT_REQUIREMENT,
                            Decimal('1.00')) == Decimal('1')

    incidence = measure_account_margin_incidence(
        str(corpus_root), holding_days=10,
        funding_multiple=FUNDED_AT_REQUIREMENT)
    assert incidence.called == result.entries


@requires_corpus
def test_the_derived_funding_curve_agrees_with_the_walked_model(corpus_root):
    """The sweep becomes a view of one distribution, and must not drift.

    ``call_rate(k, theta)`` is ``P(U* >= theta k)`` read off the stored
    sample; ``measure_account_margin_incidence`` walks the account bar by bar.
    They are the same number computed two ways, so they are checked against
    each other at multiples spanning the degenerate region and beyond it.
    """
    result = measure_peak_requirement(str(corpus_root), holding_days=10,
                                      broker_buffer=Decimal('0.05'))
    call_rung = BrokerTerms.DEFAULT.margin_call_utilisation
    for k in ('1.00', '1.10', '1.25', '1.42', '1.60', '1.90'):
        walked = measure_account_margin_incidence(
            str(corpus_root), holding_days=10, funding_multiple=Decimal(k))
        assert result.call_rate(Decimal(k), call_rung) == walked.call_rate, k


@requires_corpus
@pytest.mark.parametrize('holding_days,rally,never,median,p95', [
    (5, 139, 120, '1.0666', '1.4589'),
    (10, 126, 98, '1.0939', '1.7093'),
    (20, 112, 83, '1.1342', '1.8275'),
])
def test_the_peak_requirement_distribution_is_pinned(
        corpus_root, holding_days, rally, never, median, p95):
    """The headline the paper should print, pinned to four decimals.

    ``broker_buffer`` is 0 here and that is the point: the requirement is then
    exactly VSDC's published ``MR = IM + VM`` on VSDC's own dated ratio, with
    no unsourced input anywhere in it.

    ``peaks_on_a_rally`` is reported beside it because roughly a third of the
    peaks are attained on a *rising* price -- IM recomputed on the higher
    price with the profit not credited to assets. That is the Tier 1 cash-leg
    gap, and it is why the loss-branch series is reported separately: on a
    rally a real account's assets grow faster than its requirement, so those
    peaks cannot become calls in the market even though they can in the model.
    """
    result = measure_peak_requirement(
        str(corpus_root), holding_days=holding_days)
    assert result.entries == 381
    assert result.contracts == 20
    assert result.broker_buffer == Decimal('0')
    assert result.peaks_on_a_rally == rally
    assert result.windows_never_in_loss == never

    def rounded(value):
        return value.quantize(Decimal('0.0001'))

    assert rounded(result.peak_multiple['median']) == Decimal(median)
    assert rounded(result.peak_multiple['p95']) == Decimal(p95)
    assert result.peak_multiple['min'] >= Decimal('1')
    assert result.loss_peak_multiple['min'] == Decimal('1')
    assert (result.loss_peak_multiple['median']
            <= result.peak_multiple['median'])

    assert set(result.peak_multiple) == set(REQUIREMENT_QUANTILES)
    decoded = json.loads(json.dumps(result.to_dict()))
    assert decoded['entries'] == 381
    assert 'no funding' in decoded['statistic']


@requires_corpus
def test_the_overlap_in_the_denominator_is_reported_not_hidden(corpus_root):
    """381 entries are not 381 independent observations.

    They are overlapping windows on 401 daily observations of 20 contracts.
    At 20 sessions held, the 381 peaks fall on 64 distinct days, so a
    confidence interval computed as if n = 381 is wrong by a large factor.
    The result carries the day count so a reader cannot miss it.
    """
    twenty = measure_peak_requirement(str(corpus_root), holding_days=20)
    assert twenty.entries == 381
    assert twenty.contracts == 20
    assert twenty.distinct_peak_days == 64
    assert twenty.observations == 401

    five = measure_peak_requirement(str(corpus_root), holding_days=5)
    assert five.distinct_peak_days == 180


@requires_corpus
def test_time_to_peak_is_defined_where_time_to_first_call_is_not(corpus_root):
    """The horizon statistic the call rate cannot express.

    Time-to-first-call is identically 1 for every entry at any funding below
    ``1/rung`` and undefined for an entry never called. Time to *peak
    requirement* is defined for all 381 entries at every funding level,
    because it does not mention funding.

    The reading is a result in its own right: the median peak lands on session
    **6** of a twenty-session hold, so the second fortnight adds almost
    nothing. A call rate cannot say that.
    """
    medians = {}
    for holding_days in (5, 10, 20):
        result = measure_peak_requirement(
            str(corpus_root), holding_days=holding_days)
        medians[holding_days] = result.peak_session['median']
        assert result.peak_session['min'] >= Decimal('1')
        assert result.peak_session['max'] <= Decimal(holding_days)
    assert medians == {5: Decimal('3'), 10: Decimal('5'), 20: Decimal('6')}


def test_the_provenance_does_not_reassert_the_refuted_disagreement():
    """A guard for a claim this repo already got wrong once.

    An earlier revision recorded 'MEASURED VERDICT: DISAGREE' and 'no funding
    multiple reproduces all three counts' in four places. Both are false --
    with the VSD ratio frozen at entry, a funding multiple in [1.4110, 1.4136]
    reproduces 29/48/56 exactly, and the earlier search stepped over that
    interval on a 0.01 grid.

    When that was corrected, the assertion pinning it was DELETED rather than
    the strings fixed, which left the repo shipping a machine-readable claim
    its own suite disproved. This test is the replacement guard: it fails if
    the refuted wording comes back.
    """
    from plutus.market.margin import PROVENANCE

    reproduction = PROVENANCE['reproduction']

    # A retraction has to NAME what it retracts, so a naive "the phrase must
    # not appear" guard fails on the correction itself -- it did, on the first
    # attempt. The property that actually matters is that the phrase never
    # appears in an ASSERTING context: if it is present at all, the retraction
    # must be present too.
    for refuted in ('no funding multiple reproduces',
                    'VERDICT: DISAGREE'):
        if refuted in reproduction:
            assert 'FALSE' in reproduction, (
                f'{refuted!r} is stated without a retraction alongside it')

    # And the retraction must say what IS true, not merely disown the lie.
    assert 'SUPERSEDED' in reproduction
    assert '1.4110' in reproduction
    assert 'margin-model-adjudication' in reproduction
