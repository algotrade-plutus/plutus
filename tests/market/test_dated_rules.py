"""The dated-rule exposure census -- the paper's lead claim, measured.

These pin the numbers the paper quotes. If a corpus refresh moves them, the
paper must move with them; that is the point of pinning.
"""

from datetime import date

import pytest

from measurements.dated_rules import (
    DATED_CHANGES, measure_dated_rule_exposure,
)

from .conftest import requires_corpus


def _by_rule(results, rule):
    return next(r for r in results if r.rule == rule)


def test_every_dated_change_carries_a_citation_and_a_confidence():
    """A change we cannot date cannot demonstrate the value of dating.

    This is the table's entry condition, so it is worth a test rather than a
    convention: an uncited row would quietly weaken the whole census.
    """
    for change in DATED_CHANGES:
        assert change.citation, f'{change.rule} has no citation'
        assert change.confidence in {'high', 'medium', 'low'}
        assert isinstance(change.effective, date)


def test_the_krx_cutover_is_carried_even_though_it_is_outside_the_corpus():
    """Exposure is zero here and total for anyone simulating 2025 onward.

    It is in the table precisely because it is the case the mechanism has to
    exist *before* the data does.
    """
    krx = next(c for c in DATED_CHANGES if c.rule == 'krx_cutover')

    assert krx.effective == date(2025, 5, 5)
    assert krx.measurable_in_corpus is False


@requires_corpus
def test_most_of_the_hsx_sample_predates_the_round_lot_change(corpus_root):
    """82.2% -- the lead claim's warrant, and the tight case.

    HOSE's minimum lot was 10 shares until 2021-01-03 and 100 from 2021-01-04.
    A simulator resolving the lot once at load time applies 100 to all history
    and rejects every legal 10-to-90 share order across four fifths of the
    HSX equity sample.
    """
    lot = _by_rule(measure_dated_rule_exposure(str(corpus_root)), 'round_lot')

    assert lot.observations == 1_086_518
    assert lot.before_side == 893_628
    assert lot.exposure == pytest.approx(0.822, abs=0.001)


@requires_corpus
def test_unmeasurable_changes_report_no_exposure_rather_than_zero(corpus_root):
    """Reporting them as unmeasurable beats omitting them.

    A margin ratio and a settlement time-of-day leave no trace in a close
    series, but they are real dated changes. Omitting them would imply the
    census is exhaustive; returning exposure=None says plainly that the corpus
    cannot speak to them.
    """
    results = measure_dated_rule_exposure(str(corpus_root))

    for rule in ('settlement_delivery_time', 'vsd_initial_margin',
                 'krx_cutover'):
        r = _by_rule(results, rule)
        assert r.measurable is False
        assert r.exposure is None
        assert r.observations == 0


@requires_corpus
def test_the_upcom_row_warns_against_quoting_its_own_exposure(corpus_root):
    """The loose case, and the one most likely to be misquoted.

    The +/-15% ordinary band predates 2022-11-16; only the wide regime was
    added. So a high exposure here does NOT mean most rows are misjudged, and
    the note has to say so, because the tighter figure (17.1% of name-days
    actually carrying the wide band) is the one the paper should cite.
    """
    band = _by_rule(measure_dated_rule_exposure(str(corpus_root)),
                    'price_band_wide_regime')

    assert '17.1%' in band.note
    assert 'Cite 17.1%' in band.note
