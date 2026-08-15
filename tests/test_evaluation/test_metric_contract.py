"""WP2a: the metrics results contract, pinned as tests.

Two guarantees are enforced here across the whole metric surface:

1. Undefined metrics return ``None`` — never ``0`` (indistinguishable from a
   real break-even result) and never ``±Infinity`` (not representable in JSON,
   RFC 8259, so it breaks any strict re-read of a results file).
2. A return series that compounds to total loss raises a domain error rather
   than returning a plausible-looking number.

The edge-case matrix is the point: empty, single point, constant, zero
volatility, all negative, and below -100%.
"""

import json
from decimal import Decimal

import pytest

from plutus.evaluation import metrics
from plutus.evaluation.contract import TotalLossError, json_safe

# Every metric that takes a plain return series and yields a scalar.
SERIES_METRICS = [
    metrics.sharpe_ratio,
    metrics.sortino_ratio,
    metrics.calmar_ratio,
    metrics.omega_ratio,
    metrics.cagr,
    metrics.total_return,
    metrics.value_at_risk,
    metrics.conditional_value_at_risk,
    metrics.annualized_volatility,
    metrics.downside_deviation,
    metrics.maximum_drawdown,
    metrics.average_drawdown,
    metrics.average_drawdown_duration,
    metrics.longest_drawdown_duration,
]

EMPTY: list = []
SINGLE = [Decimal('0.01')]
CONSTANT = [Decimal('0.005')] * 100
ZERO_VOL = [Decimal('0')] * 50
ALL_NEGATIVE = [Decimal('-0.01')] * 30

EDGE_CASES = {
    'empty': EMPTY,
    'single': SINGLE,
    'constant': CONSTANT,
    'zero_volatility': ZERO_VOL,
    'all_negative': ALL_NEGATIVE,
}


def _ids(fns):
    return [f.__name__ for f in fns]


@pytest.mark.parametrize('metric', SERIES_METRICS, ids=_ids(SERIES_METRICS))
@pytest.mark.parametrize('case', sorted(EDGE_CASES), ids=sorted(EDGE_CASES))
def test_no_metric_returns_a_non_finite_value(metric, case):
    """No edge case may produce ±Infinity or NaN from any metric."""
    value = metric(EDGE_CASES[case])

    if value is None:
        return
    if isinstance(value, Decimal):
        assert value.is_finite(), (
            f"{metric.__name__} returned non-finite {value!r} on '{case}'"
        )


@pytest.mark.parametrize('metric', SERIES_METRICS, ids=_ids(SERIES_METRICS))
def test_empty_series_is_undefined_not_zero(metric):
    """An empty series must not be reported as a break-even result."""
    assert metric(EMPTY) is None


@pytest.mark.parametrize('metric', SERIES_METRICS, ids=_ids(SERIES_METRICS))
@pytest.mark.parametrize('case', sorted(EDGE_CASES), ids=sorted(EDGE_CASES))
def test_every_edge_case_survives_a_strict_json_round_trip(metric, case):
    """Results must re-read under a parser that rejects non-finite tokens."""
    value = metric(EDGE_CASES[case])

    encoded = json.dumps({'value': json_safe(value)})

    def reject_non_finite(token):
        raise AssertionError(f"non-finite token {token!r} in results JSON")

    decoded = json.loads(encoded, parse_constant=reject_non_finite)
    assert 'value' in decoded


def test_constant_series_gives_one_consistent_verdict():
    """A constant series previously gave 0 / Inf / Inf / Inf simultaneously."""
    verdicts = {
        'sharpe': metrics.sharpe_ratio(CONSTANT),
        'sortino': metrics.sortino_ratio(CONSTANT),
        'calmar': metrics.calmar_ratio(CONSTANT),
        'omega': metrics.omega_ratio(CONSTANT),
    }

    assert all(v is None for v in verdicts.values()), verdicts


def test_zero_volatility_sharpe_is_undefined():
    assert metrics.sharpe_ratio(ZERO_VOL) is None


def test_all_negative_series_still_produces_defined_metrics():
    """Losing money is well-defined; it must not be confused with undefined."""
    assert metrics.total_return(ALL_NEGATIVE) is not None
    assert metrics.total_return(ALL_NEGATIVE) < 0
    assert metrics.maximum_drawdown(ALL_NEGATIVE) < 0


def test_never_drew_down_measures_zero_not_undefined():
    """0 drawdown is a real measurement, distinct from an absent one."""
    assert metrics.maximum_drawdown(CONSTANT) == Decimal('0')


# --- total loss -------------------------------------------------------------
# The prior implementation failed differently depending on series length: when
# the annualization factor divided evenly by the number of periods the exponent
# was a whole number and CAGR returned a clean, plausible -100%; otherwise the
# same input raised a bare decimal.InvalidOperation. Both lengths are covered.

@pytest.mark.parametrize('n_periods', [1, 2, 5, 8, 10])
def test_total_loss_raises_a_domain_error_at_any_series_length(n_periods):
    returns = [Decimal('-1.5')] + [Decimal('0.01')] * (n_periods - 1)

    with pytest.raises(TotalLossError) as excinfo:
        metrics.cagr(returns)

    assert 'total loss' in str(excinfo.value).lower()


def test_calmar_propagates_the_total_loss_error():
    with pytest.raises(TotalLossError):
        metrics.calmar_ratio([Decimal('-1.5')] + [Decimal('0.01')] * 4)


def test_exactly_minus_one_hundred_percent_is_total_loss():
    """Equity of exactly zero is still a wipeout: no growth rate exists."""
    with pytest.raises(TotalLossError):
        metrics.cagr([Decimal('-1.0'), Decimal('0.05')])


def test_json_safe_rejects_a_non_finite_value():
    """The serialiser must fail loudly rather than emit an Infinity token."""
    with pytest.raises(ValueError, match='Non-finite'):
        json_safe(Decimal('Infinity'))


# --- the 250-day default ----------------------------------------------------

def test_default_annualization_is_the_measured_vietnamese_year():
    from plutus.core.constant import VietnamMarketConstant
    from plutus.evaluation.metrics.returns import DEFAULT_ANNUALIZATION

    assert VietnamMarketConstant.TRADING_DAYS_PER_YEAR == 250
    assert DEFAULT_ANNUALIZATION == 250


def test_annualization_factor_remains_overridable():
    """Comparison against NYSE-convention results must stay possible."""
    returns = [Decimal('0.01'), Decimal('-0.005'), Decimal('0.02')] * 10

    vn = metrics.sharpe_ratio(returns)
    nyse = metrics.sharpe_ratio(returns, annualization_factor=252)

    assert vn is not None and nyse is not None
    assert vn != nyse


def test_252_overstates_relative_to_250():
    """Document the direction of the bias the NYSE constant introduces."""
    returns = [Decimal('0.01'), Decimal('-0.005'), Decimal('0.02')] * 10

    vn = metrics.annualized_volatility(returns)
    nyse = metrics.annualized_volatility(returns, annualization_factor=252)

    assert nyse > vn
