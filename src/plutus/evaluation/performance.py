import datetime
import math
import statistics

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Tuple


class Performance:
    """Performance in a period of an investment
    Args:
        absolute_return (Decimal): return of this investment in the period
    """
    absolute_return: Decimal


@dataclass
class IndexPerformance(Performance):
    """Performance of an index"""
    index: str
    period_return: Decimal
    absolute_return: Decimal = field(init=False)

    def __post_init__(self):
        self.absolute_return = self.period_return


class PerformanceHistory:
    """History of an investment"""
    def __init__(
        self, dates: List[Tuple[datetime.date, ...]],
        performances: List[Performance],
        annualized_factor: Decimal
    ):
        """
        Init a performance history of an investment with a list of performance of consecutive periods

        Args:
            dates: a list of dates that define the consecutive periods of an investment, two consecutive dates in the
                   list are in turn the start and end dates of a period
            performances: list of performances that correspond to periods defined by argument dates
            annualized_factor: the number of periods in a year
        """
        self.dates = dates
        self.performances = performances
        self.n_periods = len(performances)
        self.annualized_factor = annualized_factor
        self.sharpe_ratio = self._get_sharpe_ratio()
        self.sortino_ratio = self._get_sortino_ratio(mar=Decimal('0.07'))
        self.cumulative_performance = self._get_cumulative_performance()
        self.maximum_drawdown = self._get_maximum_drawdown()
        self.annual_return = self._get_annual_return()
        self.longest_drawdown = self._get_longest_drawdown()

    def _get_sharpe_ratio(self) -> Decimal:
        """Compute sharpe ratio of this history of investment"""
        returns = [performance.absolute_return for performance in self.performances]
        if len(returns) <= 1 or all(r == Decimal('0') for r in returns):
            return Decimal('0')
        risk_free_return = Decimal('0.03')
        return Decimal(self.annualized_factor**Decimal(1/2))*(
                statistics.mean(returns)-risk_free_return/self.annualized_factor
        )/statistics.stdev(returns)

    def _get_sortino_ratio(self, mar: Decimal) -> Decimal:
        """Compute sortino ratio of this history of investment"""
        returns = [performance.absolute_return for performance in self.performances]
        if len(returns) <= 1 or all(r == Decimal('0') for r in returns):
            return Decimal('0')
        target_semi_deviation = Decimal(math.pow(
            sum(min(Decimal(0), r - mar/self.annualized_factor)**2 for r in returns)/len(returns), Decimal('0.5')
        ))
        return (
            Decimal(self.annualized_factor**Decimal(1/2))*(
                    statistics.mean(returns)-mar/self.annualized_factor
            )/target_semi_deviation
            if target_semi_deviation > 0 else Decimal('Inf')
        )

    def _get_cumulative_performance(self) -> List[Decimal]:
        """Compute cumulative performance of this history of investment"""
        cumulative_performance = [Decimal('1')]
        for performance in self.performances:
            cumulative_performance.append(
                cumulative_performance[-1]*(1 + performance.absolute_return)
            )
        return cumulative_performance

    def _get_maximum_drawdown(self) -> Decimal:
        """Compute maximum drawdown of this history of investment"""
        max_performance = [
            max(self.cumulative_performance[:i + 1])
            for i in range(len(self.cumulative_performance))
        ]

        dd = [
            (self.cumulative_performance[i] - max_performance[i])/max_performance[i]
            for i in range(len(max_performance))
        ]

        return min(dd)

    def _get_annual_return(self) -> Decimal:
        """Compute annual return of this history of investment"""
        return Decimal(
            math.pow(self.cumulative_performance[-1], self.annualized_factor/len(
                self.performances
            ))
        ) - 1

    def _get_longest_drawdown(self) -> int:
        """Compute the longest drawdown of this history of investment"""
        longest_drawdown = 0
        max_performance = 1
        max_performance_index = 0
        min_performance = 1
        for i in range(1, len(self.cumulative_performance)):
            if self.cumulative_performance[i] > max_performance:
                max_performance = self.cumulative_performance[i]
                min_performance = max_performance
                max_performance_index = i
            else:
                if self.cumulative_performance[i] < min_performance:
                    min_performance = self.cumulative_performance[i]
                    longest_drawdown = max(longest_drawdown, i - max_performance_index)
        return longest_drawdown
