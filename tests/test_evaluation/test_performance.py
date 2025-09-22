import json
import os
import pytest

from pathlib import Path
from decimal import Decimal
from typing import List

from utils import pytest_generate_tests

from src.plutus.evaluation.performance import Performance, HistoricalPerformance


FIXTURE_FILE = os.path.join(Path(__file__).parent.parent, 'test_evaluation/fixtures/performance_test_data.json')


@pytest.fixture
def returns(return_data) -> List[Decimal]:
    return [Decimal(r) for r in return_data]


class TestHistoricalPerformance:

    params = json.load(open(FIXTURE_FILE, 'r'))

    def test_historical_performance(
        self, returns,
        annualized_factor, risk_free_return, minimal_acceptable_return,
        expected_sharpe_ratio, expected_sortino_ratio, expected_cumulative_performances,
        expected_maximum_drawdown, expected_annual_return, expected_longest_drawdown_period
    ):
        historical_performance = HistoricalPerformance(
            returns=returns,
            # convert float params to Decimals
            annualized_factor=Decimal(annualized_factor),
            risk_free_return=Decimal(risk_free_return),
            minimal_acceptable_return=Decimal(minimal_acceptable_return)
        )
        expected_sharpe_ratio = Decimal(expected_sharpe_ratio)
        expected_sortino_ratio = Decimal(expected_sortino_ratio)
        expected_cumulative_performances = [
            Decimal(performance) for performance in expected_cumulative_performances
        ]
        expected_maximum_drawdown = Decimal(expected_maximum_drawdown)
        expected_annual_return = Decimal(expected_annual_return)

        assert historical_performance.sharpe_ratio == pytest.approx(expected_sharpe_ratio)
        assert historical_performance.sortino_ratio == pytest.approx(expected_sortino_ratio)
        assert historical_performance.cumulative_performances == pytest.approx(
            expected_cumulative_performances, rel=Decimal('1e-4')
        )
        assert historical_performance.maximum_drawdown == pytest.approx(expected_maximum_drawdown)
        assert historical_performance.annual_return == pytest.approx(expected_annual_return)
        assert historical_performance.longest_drawdown_period == expected_longest_drawdown_period
