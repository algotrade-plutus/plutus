"""The occupancy census -- how often each exchange rule actually bound.

These pin the headline figures so a corpus refresh that moves them is visible
rather than silent. The paper quotes these numbers; if the corpus changes, the
paper must change with it, and a failing test here is the notification.

They also pin the *honesty* properties: that occupancy is never presented as
exposure, that unmeasurable rules are listed rather than dropped, and that the
two known corpus defects stay quarantined. Those are as load-bearing as the
rates, because a defensible number reported alongside a misleading frame is
still a defect.
"""

from datetime import date
from decimal import Decimal

import pytest

from measurements.occupancy import (
    BAND_DEFECT_DATES, NOT_MEASURABLE, RuleOccupancy,
    measure_band_lock, measure_daily_room_placeholder, measure_occupancy,
    measure_round_lot_reshaping, measure_tick_grid_displacement,
)

from .conftest import TICK_ROOT, requires_corpus, requires_ticks


def _pick(results, rule, venue):
    return next(r for r in results if r.rule == rule and r.venue == venue)


# --------------------------------------------------------------------------
# Structural / honesty properties -- no corpus needed
# --------------------------------------------------------------------------

def test_every_unmeasurable_rule_states_a_reason_and_no_rate():
    """A rule we cannot measure must say so, not quietly report zero.

    Omitting an unmeasurable rule implies the census is exhaustive, which
    would let a reader infer the rule never binds. Session structure binds on
    every order ever placed -- the opposite of never. The pattern follows
    ``dated_rules.measurable_in_corpus``.
    """
    assert NOT_MEASURABLE, 'the census must list what it cannot measure'
    for rule in NOT_MEASURABLE:
        assert rule.measurable_in_corpus is False
        assert rule.binding is None, f'{rule.rule} must not report a count'
        assert rule.occupancy is None, f'{rule.rule} must not report a rate'
        assert len(rule.reason) > 40, f'{rule.rule} needs a real reason'


def test_the_intraday_session_rules_are_all_declared_unmeasurable():
    """A daily close series cannot speak to intraday phase, and must not try.

    Auctions, the PLO session and the noon break are the rules a reader is
    most likely to assume were measured, because a simulator that enforces
    them looks like it must have evidence for them. It does not, and inventing
    a proxy from a daily bar would be the exact overclaim this project treats
    as a defect.
    """
    named = {rule.rule for rule in NOT_MEASURABLE}

    assert {'auction_phase_ato_atc', 'plo_post_close_session', 'noon_break',
            'order_matching_priority', 'settlement_delivery_instant',
            'foreign_room_block_realised'} <= named


def test_every_measured_rule_carries_its_own_binding_definition():
    """Occupancy has no rule-independent meaning, so the predicate travels.

    "9%" is unreadable without "the close sat exactly on the ceiling". Worse,
    two rates whose definitions differ cannot be compared or averaged, and a
    bare rate invites exactly that.
    """
    for rule in NOT_MEASURABLE:
        assert rule.definition, f'{rule.rule} has no definition'


def test_the_census_result_has_no_aggregate_field():
    """Averaging across rules produces a number that means nothing.

    Band lock is a tight, outcome-changing measure; lot reshaping is fixed
    almost entirely by arithmetic. Their mean is not a fidelity score. The
    absence of a total is a deliberate design choice, so it is pinned rather
    than left to convention.
    """
    fields = set(RuleOccupancy.__dataclass_fields__)

    assert not {'total', 'aggregate', 'overall', 'mean'} & fields


# --------------------------------------------------------------------------
# Band lock
# --------------------------------------------------------------------------

@requires_corpus
def test_the_price_band_locks_a_side_on_roughly_a_tenth_of_traded_days(
        corpus_root):
    """The rule most likely to change a real outcome: a locked side is unfillable.

    HSX 13,988 of 171,784 traded stock closes (8.14%) sit exactly on the
    ceiling or the floor. UPCoM is higher at 10.72%, consistent with its wider
    band being reached by thinner names. These are the conservative counts --
    a name that hit the ceiling at 10am and retreated is not counted here.
    """
    results = measure_band_lock(str(corpus_root))

    hsx = _pick(results, 'price_band_close_lock', 'HSX')
    assert hsx.observations == 171_784
    assert hsx.binding == 13_988
    assert float(hsx.occupancy) == pytest.approx(0.0814, abs=0.0005)

    upcom = _pick(results, 'price_band_close_lock', 'UPCOM')
    assert upcom.observations == 176_662
    assert upcom.binding == 18_932


@requires_corpus
def test_the_band_is_touched_intraday_far_more_often_than_it_is_closed_at(
        corpus_root):
    """15.2% touched against 9.2% closed-locked -- both are honest, neither alone is.

    The close-lock count understates binding, because the band can lock a side
    for hours and release before 14:45. The high/low touch count is the upper
    figure for a daily bar. Quoting only one of them would be a choice of
    convenience; the census reports the bracket.
    """
    results = measure_band_lock(str(corpus_root))

    hsx_touch = _pick(results, 'price_band_intraday_touch', 'HSX')
    hsx_close = _pick(results, 'price_band_close_lock', 'HSX')
    assert hsx_touch.binding == 23_097
    assert hsx_touch.binding > hsx_close.binding
    assert float(hsx_touch.occupancy) == pytest.approx(0.1345, abs=0.0005)

    hnx_touch = _pick(results, 'price_band_intraday_touch', 'HNX')
    assert hnx_touch.observations == 111_581
    assert hnx_touch.binding == 17_370


@requires_corpus
def test_band_results_declare_their_2021_2022_window_and_the_defect_dates(
        corpus_root):
    """quote_ceil starts 2021-02-05, so no band number covers the full corpus.

    A reader who takes a band rate as a corpus-wide rate is off by a factor of
    five in the denominator. The two excluded dates matter for a different
    reason: 2021-02-17 holds every inverted-band row in the corpus and
    2021-06-21 has ceiling/floor mis-keyed to the wrong tickers, so including
    them would count rows where the band itself is wrong as rows where the
    band bound.
    """
    results = measure_band_lock(str(corpus_root))

    assert BAND_DEFECT_DATES == (date(2021, 2, 17), date(2021, 6, 21))
    for r in results:
        assert r.window.startswith('2021-02-05')
        assert 'quote_ceil starts 2021-02-05' in r.caveat
        assert '2021-02-17' in r.caveat and '2021-06-21' in r.caveat


# --------------------------------------------------------------------------
# Tick grid
# --------------------------------------------------------------------------

@requires_corpus
def test_the_tick_grid_moves_a_marketable_limit_on_half_the_hsx_sample(
        corpus_root):
    """566,903 of 1,086,518 (52.18%) -- the rule changes the price actually sent.

    This is not conformity. An observed close already sits on the grid, so
    conformity cannot show the rule ever changing an order. Rounding a
    *derived* price -- a 1% marketable limit, which is how a daily backtest
    makes an order price -- is where the rule bites, and it bites on more than
    half the sample at a mean displacement of about 42 VND.
    """
    tick = measure_tick_grid_displacement(str(corpus_root))[0]

    assert tick.venue == 'HSX'
    assert tick.observations == 1_086_518
    assert tick.binding == 566_903
    assert float(tick.occupancy) == pytest.approx(0.5218, abs=0.0005)
    assert float(tick.detail['mean_displacement_thousand_vnd']) == (
        pytest.approx(0.0419, abs=0.0002))


@requires_corpus
def test_the_tick_headline_is_meaningless_without_its_per_band_split(
        corpus_root):
    """The 0.1 band contributes exactly zero, by construction and not by luck.

    Above 50,000 VND the legal tick *is* 0.1, so the naive model is correct
    there and 161,166 observations can never bind. The headline rate is
    therefore partly a statement about how much of HSX trades cheap, which is
    why the per-band detail is reported and why this test exists.
    """
    tick = measure_tick_grid_displacement(str(corpus_root))[0]
    bands = tick.detail['per_tick_band']

    assert bands['0.1']['displaced'] == 0
    assert bands['0.1']['observations'] == 161_166
    assert bands['0.01']['displaced'] == 217_436
    assert bands['0.05']['displaced'] == 349_467
    assert tick.detail['unresolvable_prices'] == 0


@requires_corpus
def test_hnx_and_upcom_are_absent_from_the_tick_census_by_rule(corpus_root):
    """Both carry a flat 0.1 tick, so the naive model is the legal grid there.

    Their absence is a finding, not a scoping shortcut, and the caveat has to
    say so -- otherwise a reader assumes they were simply not looked at and
    that the rule might bind there too.
    """
    results = measure_tick_grid_displacement(str(corpus_root))

    assert [r.venue for r in results] == ['HSX']
    assert 'flat 0.1 tick' in results[0].caveat
    assert '0 by rule' in results[0].caveat


# --------------------------------------------------------------------------
# Round lot
# --------------------------------------------------------------------------

@requires_corpus
def test_a_one_percent_order_dies_under_the_lot_on_over_half_of_upcom_days(
        corpus_root):
    """417,251 of 735,811 UPCoM ticker-days (56.71%) cannot be traded at all.

    An order sized at 1% of daily volume falls below one 100-share lot, so it
    rounds to zero shares. This is the informative lot measure: it varies from
    12.45% to 56.71% across venues and eras, which is what a rule that
    actually binds looks like.
    """
    results = measure_round_lot_reshaping(str(corpus_root))

    upcom = _pick(results, 'round_lot_annihilation', 'UPCOM (lot 100)')
    assert upcom.observations == 735_811
    assert upcom.binding == 417_251
    assert float(upcom.occupancy) == pytest.approx(0.5671, abs=0.0005)

    hnx = _pick(results, 'round_lot_annihilation', 'HNX (lot 100)')
    assert hnx.observations == 639_695
    assert hnx.binding == 346_227


@requires_corpus
def test_the_dated_lot_saves_166013_orders_a_date_blind_lot_would_destroy(
        corpus_root):
    """The exposure-to-occupancy bridge, and the tightest number in the census.

    dated_rules.py reports 82.2% *exposure* to the 2021-01-04 lot change: the
    share of the HSX sample sitting under the old 10-share lot. That is a
    ceiling. This is the occupancy underneath it -- 166,013 specific orders
    (19.75% of the era) that a date-blind lot of 100 destroys and the correct
    lot of 10 lets through. Exposure bounds the problem; this is the problem.
    """
    results = measure_round_lot_reshaping(str(corpus_root))
    hsx10 = _pick(results, 'round_lot_annihilation', 'HSX (lot 10)')

    assert hsx10.observations == 840_641
    assert hsx10.binding == 104_670
    assert hsx10.detail['annihilated_under_date_blind_lot_100'] == 270_683
    assert hsx10.detail['orders_wrongly_destroyed_by_date_blind_lot'] == 166_013
    assert float(hsx10.detail['wrongly_destroyed_rate']) == (
        pytest.approx(0.1975, abs=0.0005))


@requires_corpus
def test_the_reshaped_count_is_labelled_uncitable_because_it_is_arithmetic(
        corpus_root):
    """99.14% reshaped is the combinatorial prior, not evidence the lot matters.

    A size uniform mod 100 is a non-multiple 99% of the time. Measuring 99.14%
    therefore says only that the lot exists. Reporting it unlabelled next to a
    real occupancy figure would invite it to be cited as fidelity evidence, so
    the key name itself carries the warning.
    """
    results = measure_round_lot_reshaping(str(corpus_root))
    hsx100 = _pick(results, 'round_lot_annihilation', 'HSX (lot 100)')

    rate = hsx100.detail['reshaped_rate_IS_COMBINATORIAL_DO_NOT_CITE']
    assert float(rate) == pytest.approx(0.9914, abs=0.0005)
    assert any('DO_NOT_CITE' in key for key in hsx100.detail)
    assert 'must not' in hsx100.caveat and 'cited' in hsx100.caveat


@requires_corpus
def test_the_two_hsx_lot_eras_are_never_merged(corpus_root):
    """Merging them would hide the very thing a dated lot exists to represent.

    One HSX row averaging a 10-share era with a 100-share era would report a
    lot that was never in force on any date, which is precisely the date-blind
    failure the paper is about.
    """
    venues = [r.venue for r in measure_round_lot_reshaping(str(corpus_root))]

    assert 'HSX (lot 10)' in venues and 'HSX (lot 100)' in venues
    assert 'HSX' not in venues


# --------------------------------------------------------------------------
# Foreign room -- the constraint we chose not to enforce
# --------------------------------------------------------------------------

@requires_ticks
@pytest.mark.skipif(
    TICK_ROOT is None or not (TICK_ROOT / 'quote_foreignroom.csv').exists(),
    reason='quote_foreignroom.csv not in the archive root.')
def test_foreign_room_falls_below_a_hundred_share_lot_34653_times(corpus_root,
                                                                  tick_root):
    """Reproduces the prior finding and dates it: 34,653 of 12,790,234 rows.

    Foreign room is not enforced in this iteration -- declared tradeoff T1 --
    which is exactly why it is measured. A tradeoff is only honest if the
    thing given up is quantified, and this quantifies it: the constraint we
    chose not to enforce reaches a sub-lot level tens of thousands of times.
    Room never actually reaches zero; the observed minimum is 1 share.
    """
    census = measure_occupancy(str(corpus_root), archive_root=str(tick_root))
    row_level = census.by_rule('foreign_room_below_lot', 'ALL')

    assert row_level.observations == 12_790_234
    assert row_level.binding == 34_653
    assert row_level.detail['below_10_shares'] == 24_212
    assert row_level.detail['exactly_zero'] == 0
    assert row_level.detail['minimum_room_observed'] == 1


@requires_ticks
@pytest.mark.skipif(
    TICK_ROOT is None or not (TICK_ROOT / 'quote_foreignroom.csv').exists(),
    reason='quote_foreignroom.csv not in the archive root.')
def test_foreign_room_is_rated_over_ticker_days_because_rows_change_regime(
        corpus_root, tick_root):
    """The row denominator is invalid across 2021; the ticker-day one is not.

    quote_foreignroom emits one row per ticker-day before 2021 and polls
    intraday after, roughly 26 rows per ticker-day. A rate over rows therefore
    divides a daily series by an intraday one and silently reports the change
    in vendor sampling as a change in the market. HSX pre-2021 is the highest
    rate here at 2.71%, under a *stricter* 10-share threshold and with fewer
    observations per day -- the era of the well-documented full-room names.
    """
    census = measure_occupancy(str(corpus_root), archive_root=str(tick_root))

    hsx10 = census.by_rule('foreign_room_below_lot', 'HSX (lot 10)')
    assert hsx10.observations == 828_293
    assert hsx10.binding == 22_464

    hsx100 = census.by_rule('foreign_room_below_lot', 'HSX (lot 100)')
    assert hsx100.observations == 230_046
    assert hsx100.binding == 2_428
    assert hsx10.occupancy > hsx100.occupancy
    assert 'ONE observation each' in hsx10.caveat


@requires_corpus
def test_foreign_room_reports_unmeasurable_without_the_archive(corpus_root):
    """The Parquet corpus alone cannot measure room, and must say so.

    Silently dropping the rule when the archive is absent would make the
    census look complete on a machine that cannot compute it. An explicit
    unmeasurable entry names the missing input instead.
    """
    census = measure_occupancy(str(corpus_root), archive_root=None)
    room = census.by_rule('foreign_room_below_lot', 'ALL')

    assert room.measurable_in_corpus is False
    assert room.occupancy is None
    assert 'raw archive' in room.reason


# --------------------------------------------------------------------------
# The defect that masquerades as occupancy
# --------------------------------------------------------------------------

@requires_corpus
def test_the_daily_room_tables_24416_zeros_are_absent_data_not_full_rooms(
        corpus_root):
    """16.5% of quote_totalforeignroom reads as "room exhausted" and is not.

    This is the trap the census exists to avoid, and it has a precedent: a
    prior session's 15,504 "off-grid UPCoM closes" were correctly-gridded HOSE
    prices with the wrong venue label. Here 262 tickers report zero on every
    one of the table's 83 dates while appearing in neither quote_foreignroom
    nor quote_dailyforeignbuy -- zero ticker-days in each. A value present in
    one table and absent from both corroborators is a placeholder. It is filed
    under defects, never under rules.
    """
    defect = measure_daily_room_placeholder(str(corpus_root))

    assert defect.observations == 147_620
    assert defect.binding == 24_416
    assert defect.detail['tickers_always_zero'] == 262
    assert defect.detail['dates'] == 83
    assert 'CORPUS DEFECT, NOT A RULE OCCUPANCY' in defect.caveat


@requires_corpus
def test_the_defect_is_kept_out_of_the_rules_list(corpus_root):
    """Quarantine, not annotation -- a caveat on a rule row still gets quoted.

    The census separates ``rules`` from ``defects`` structurally so that
    anything iterating the rules to build a table cannot pick up the fake
    16.5% "occupancy" no matter how carelessly it reads the caveats.
    """
    census = measure_occupancy(str(corpus_root), archive_root=None)

    rule_names = {r.rule for r in census.rules}
    assert 'daily_foreign_room_zero_placeholder' not in rule_names
    assert [d.rule for d in census.defects] == [
        'daily_foreign_room_zero_placeholder']


# --------------------------------------------------------------------------
# Census-level shape
# --------------------------------------------------------------------------

@requires_corpus
def test_the_census_serialises_with_the_exposure_distinction_attached(
        corpus_root):
    """The distinction has to survive serialisation, because JSON is what travels.

    Occupancy and exposure are different numbers -- one says a rule bound, the
    other says a rule could have. A consumer reading the JSON without the
    module docstring has only this note to tell them apart.
    """
    payload = measure_occupancy(str(corpus_root),
                                archive_root=None).to_dict()

    assert 'exposure' in payload['reading_note']
    assert 'dated_rules.py' in payload['reading_note']
    assert 'no average across rules is meaningful' in payload['reading_note']
    assert all(isinstance(r['occupancy'], (float, type(None)))
               for r in payload['rules'])


@requires_corpus
def test_occupancy_rates_are_exact_decimals_not_floats(corpus_root):
    """House rule: Decimal for money and prices, never float.

    A rate is a ratio of exact integer counts, so there is no reason for it to
    acquire binary-float error before it reaches a paper table. Serialisation
    to float is a deliberate boundary; the measurement itself is not.
    """
    census = measure_occupancy(str(corpus_root), archive_root=None)

    for rule in census.rules:
        if rule.occupancy is not None:
            assert isinstance(rule.occupancy, Decimal), rule.rule
