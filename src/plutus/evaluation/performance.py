import datetime
import math
import statistics

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Tuple


class HistoricalPerformance:
    """Historical Performance calculator"""
    def __init__(
        self,
        returns: List[Decimal],
        annualized_factor: Decimal,
        risk_free_return: Decimal,
        minimal_acceptable_return: Decimal
    ):
        """
        Init a performance history of an investment with a list of performance of consecutive periods

        Args:
            returns (List of Decimal): List of returns
            annualized_factor (Decimal): The number of periods in a year
            risk_free_return (Decimal): The risk-free return
            minimal_acceptable_return (Decimal): The minimal acceptable return
        """
        # self.dates = dates
        self.returns = returns
        self.num_return = len(self.returns)
        self.annualized_factor = annualized_factor
        self.risk_free_return = risk_free_return
        self.minimal_acceptable_return = minimal_acceptable_return
        self.return_mean = statistics.mean(self.returns)
        self.return_std = statistics.stdev(self.returns)

        self.sharpe_ratio = self._get_sharpe_ratio(risk_free_return=self.risk_free_return)
        self.sortino_ratio = self._get_sortino_ratio(minimal_acceptable_return=Decimal('0.07'))
        self.cumulative_performances = self._get_cumulative_performances()
        self.maximum_drawdown = self._get_maximum_drawdown()
        self.annual_return = self._get_annual_return()
        self.longest_drawdown_period = self._get_longest_drawdown_period()

    def _get_sharpe_ratio(self, risk_free_return: Decimal) -> Decimal:
        """Computes sharpe ratio of this history of return"""
        if len(self.returns) <= 1 or all(r == Decimal('0') for r in self.returns):
            return Decimal('0')

        return (
            self.annualized_factor**Decimal('0.5') *
            (self.return_mean - risk_free_return/self.annualized_factor) / self.return_std
        )

    def _get_sortino_ratio(self, minimal_acceptable_return: Decimal) -> Decimal:
        """Computes sortino ratio of this history of return"""
        if len(self.returns) <= 1 or all(r == Decimal('0') for r in self.returns):
            return Decimal('0')

        downside_deviation = (
            statistics.mean(
                [min(Decimal(0), r - minimal_acceptable_return / self.annualized_factor)**2 for r in self.returns]
            ) ** Decimal('0.5')
        )
        return (
            self.annualized_factor**Decimal('0.5') *
            (self.return_mean - minimal_acceptable_return/self.annualized_factor) /
            downside_deviation
            if downside_deviation > 0 else Decimal('Inf')
        )

    def _get_cumulative_performances(self) -> List[Decimal]:
        """Computes cumulative performances of this history of return"""
        cumulative_performances = [Decimal('1')]
        for r in self.returns:
            cumulative_performances.append(
                cumulative_performances[-1] * (1 + r)
            )
        return cumulative_performances

    def _get_maximum_drawdown(self) -> Decimal:
        """Computes maximum drawdown of this history of return"""
        max_performance = [
            max(self.cumulative_performances[:i + 1])
            for i in range(len(self.cumulative_performances))
        ]

        drawdowns = [
            (self.cumulative_performances[i] - max_performance[i])/max_performance[i]
            for i in range(len(max_performance))
        ]

        # min since the drawdowns are negative. The lowest drawdown == maximum drawdown.
        return min(drawdowns)

    def _get_annual_return(self) -> Decimal:
        """Computes annual return of this history of return"""
        return (
            self.cumulative_performances[-1] ** (self.annualized_factor/self.num_return) - 1
        )

    def _get_longest_drawdown_period(self) -> int:
        """Computes the longest drawdown of this history of return"""
        longest_drawdown_period = 0
        max_performance = 1
        max_performance_index = 0
        min_performance = 1

        for i in range(1, len(self.cumulative_performances)):
            if self.cumulative_performances[i] > max_performance:
                max_performance = self.cumulative_performances[i]
                min_performance = max_performance
                max_performance_index = i
            else:
                if self.cumulative_performances[i] < min_performance:
                    min_performance = self.cumulative_performances[i]
                    longest_drawdown_period = max(longest_drawdown_period, i - max_performance_index)

        return longest_drawdown_period
