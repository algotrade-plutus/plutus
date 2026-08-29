"""Is the band result engine-backed, and what does the engine actually reproduce?

The paper's band figures are SQL equalities on the vendor's ``quote_ceil``.
``measurements.band_conformance`` replaces that with the library's own band:
:func:`plutus.market.adapters.datahub.reconstruct_bands` fed the inputs
:meth:`DataHubSource._build_state` uses, compared to the vendor edge on the tick
grid. These tests pin (a) that the engine's function is the one being called --
not a reimplementation -- and (b) the numbers it produces on the corpus, whose
shape is the finding: near-perfect where the flat daily limit is the band in
force, and a *named*, measured residual where it is not.
"""

import json
from decimal import Decimal

import pytest

from measurements import band_conformance
from measurements.band_conformance import (
    BAND_START, WIDTH_TOLERANCE, BandConformanceResult,
    measure_band_conformance, wilson_interval,
)

from .conftest import requires_corpus


# --------------------------------------------------------------------------
# Structure -- no corpus needed
# --------------------------------------------------------------------------

def test_the_band_under_test_is_the_engines_not_a_reimplementation():
    """The whole point is engine-backed, so the seam is pinned structurally.

    ``band_conformance`` must call the adapter's *own* ``reconstruct_bands`` --
    the same object ``datahub`` uses to reconstruct an absent band -- so a
    change to the engine's band formula moves this measurement with it. A local
    copy of the formula would pass every numeric test here while silently
    ceasing to measure the engine; this identity is what forbids that.
    """
    from plutus.market.adapters import datahub

    assert band_conformance.reconstruct_bands is datahub.reconstruct_bands
    assert band_conformance.DataHubSource is datahub.DataHubSource
    # The exchange-spec map mirrors the adapter's private one exactly, so the
    # tick function selected here is the tick function the adapter would select.
    assert band_conformance._SPECS == datahub._SPECS


def test_the_band_start_and_width_tolerance_are_declared_constants():
    """A tolerance chosen after seeing the gap is not a tolerance.

    ``WIDTH_TOLERANCE`` (15 bp) is a module constant, tighter than the gap
    between any two Vietnamese limit regimes, so ``disagree_same_width`` is a
    pure function of it and not tuned to a wanted answer. ``BAND_START`` is the
    first published band and gates the population.
    """
    assert BAND_START == '2021-02-05'
    assert WIDTH_TOLERANCE == Decimal('0.0015')
    # 15 bp cannot span 7% -> 10% -> 15% -> 20/30/40%: the regimes stay distinct.
    assert WIDTH_TOLERANCE < Decimal('0.03')


def test_wilson_interval_is_a_valid_score_interval():
    """Bounds, degenerate samples, and two textbook values.

    Wilson rather than the normal approximation because the rate sits near 1,
    where the symmetric interval overshoots past 1 and Wilson does not.
    """
    assert wilson_interval(0, 0) == (Decimal('0'), Decimal('0'))

    lo, hi = wilson_interval(0, 10)
    assert lo >= Decimal('0') and hi < Decimal('1')
    lo, hi = wilson_interval(10, 10)
    assert lo > Decimal('0') and hi <= Decimal('1')

    # Textbook 95% Wilson intervals.
    lo, hi = wilson_interval(50, 100)
    assert float(lo) == pytest.approx(0.4038, abs=1e-3)
    assert float(hi) == pytest.approx(0.5962, abs=1e-3)
    lo, hi = wilson_interval(80, 100)
    assert float(lo) == pytest.approx(0.7112, abs=1e-3)
    assert float(hi) == pytest.approx(0.8666, abs=1e-3)

    # The interval brackets its own point estimate.
    for k, n in ((175460, 179784), (1, 3), (999, 1000)):
        lo, hi = wilson_interval(k, n)
        assert lo <= Decimal(k) / Decimal(n) <= hi


def test_the_result_is_json_safe_and_carries_its_method_and_residual():
    """A serialised result names that it is engine-backed and what it misses.

    A reader who never opens this module must be able to tell the number apart
    from a vendor-SQL equality, and must see the residual named rather than
    screened away.
    """
    result = BandConformanceResult(
        population='HSX stock', rows=1000, ceiling_agree=976, floor_agree=976,
        both_agree=976, disagree=24, disagree_same_width=1,
        excluded_no_reference=3, agreement_rate=Decimal('0.976'),
        ci_low=Decimal('0.965'), ci_high=Decimal('0.984'), confidence=0.95)
    payload = result.to_dict()
    decoded = json.loads(json.dumps(payload))

    assert decoded['rows'] == 1000
    assert decoded['both_agree'] == 976
    assert decoded['agreement_rate'] == pytest.approx(0.976)
    assert 'reconstruct_bands' in decoded['method']
    assert 'not a SQL equality' in decoded['method']
    assert 'engine-fidelity' in decoded['backs']
    assert 'special-limit' in decoded['residual']
    # The identity a reader relies on: disagreements are the complement.
    assert result.both_agree + result.disagree == result.rows


# --------------------------------------------------------------------------
# The measurement -- on the corpus
# --------------------------------------------------------------------------

@requires_corpus
def test_hsx_stock_band_is_reproduced_on_976_percent_of_days(corpus_root):
    """The headline: the engine's band == the vendor band on 97.6% of HSX days.

    This is the engine-backed parallel of the paper's bar-vs-tick lock, which
    screens to the 7% band and compares vendor close to vendor ceiling. Here
    nothing is screened: the engine reconstructs the ceiling and floor from the
    reference and its own 7% limit and tick grid, and they match the published
    edge on 175,460 of 179,784 reference-carrying HSX stock-days.
    """
    result = measure_band_conformance(str(corpus_root))  # defaults: HSX stock

    assert result.rows == 179_784
    assert result.ceiling_agree == 175_460
    assert result.floor_agree == 175_462
    assert result.both_agree == 175_460
    assert result.disagree == 4_324
    assert result.excluded_no_reference == 598

    # The identity and the interval.
    assert result.both_agree + result.disagree == result.rows
    assert result.agreement_rate == Decimal(175_460) / Decimal(179_784)
    assert float(result.agreement_rate) == pytest.approx(0.9759, abs=1e-4)
    assert result.ci_low <= result.agreement_rate <= result.ci_high
    assert float(result.ci_low) == pytest.approx(0.9752, abs=1e-3)

    decoded = json.loads(json.dumps(result.to_dict()))
    assert decoded['rows'] == 179_784


@requires_corpus
def test_when_the_width_is_right_the_formula_misses_two_of_738k(corpus_root):
    """The fidelity claim, isolated from the regime the engine does not model.

    ``disagree_same_width`` counts misses whose *implied* width matches the
    width the engine assumed -- so a wrong daily limit is excluded and only the
    reconstruction formula and tick grid are on trial. Over every stock-day in
    the corpus there are **2**, both on 2021-06-21 where the vendor's own
    ceiling sits off the 0.05 tick and the engine, on the grid, is the more
    correct. The reconstruction is, to that precision, exact.

    HNX stocks -- a flat 10% limit and a flat 0.1 tick, no price-banded grid --
    have zero such residual and read 99.0%.
    """
    hsx = measure_band_conformance(str(corpus_root))
    assert hsx.disagree_same_width == 2
    # Tiny against the disagreement total: the misses are regime, not formula.
    assert hsx.disagree_same_width < hsx.disagree / 100

    all_stock = measure_band_conformance(
        str(corpus_root), instrument_types=('stock',), exchanges=None)
    assert all_stock.rows == 737_927
    assert all_stock.both_agree == 646_340
    assert all_stock.disagree_same_width == 2   # the SAME two, corpus-wide

    hnx = measure_band_conformance(
        str(corpus_root), instrument_types=('stock',), exchanges=('HNX',))
    assert hnx.disagree_same_width == 0
    assert float(hnx.agreement_rate) == pytest.approx(0.9899, abs=1e-4)


@requires_corpus
def test_the_residual_is_a_named_regime_not_a_formula_error(corpus_root):
    """UPCOM's ~79% is the ±40% resumption band, measured not hidden.

    UPCOM stocks are illiquid enough that the ±40% post-suspension limit recurs
    constantly, and the engine's flat 15% limit does not model it -- so the
    UPCOM-stock agreement falls to ~79% while HSX/HNX sit at 97-99%. Widening
    the population from HSX-stock to all-stock therefore *lowers* the rate: the
    added instruments carry regimes the flat limit cannot state. That is the
    limitation, reported as a fact of the data rather than screened out.
    """
    hsx = measure_band_conformance(
        str(corpus_root), instrument_types=('stock',), exchanges=('HSX',))
    upcom = measure_band_conformance(
        str(corpus_root), instrument_types=('stock',), exchanges=('UPCOM',))
    all_stock = measure_band_conformance(
        str(corpus_root), instrument_types=('stock',), exchanges=None)

    assert float(upcom.agreement_rate) == pytest.approx(0.7918, abs=1e-3)
    assert upcom.rows == 412_041
    # HSX/HNX high, UPCOM materially lower, all-stock in between and below HSX.
    assert hsx.agreement_rate > Decimal('0.97')
    assert upcom.agreement_rate < Decimal('0.85')
    assert all_stock.agreement_rate < hsx.agreement_rate
