"""Portfolio module"""
from abc import ABC, abstractmethod


from plutus.core.position import Position


class AbstractPortfolio(ABC):
    """Abstract class of the Portfolio"""

    @abstractmethod
    def open_position(self):
        """Opens the position"""
        pass

    @abstractmethod
    def close_position(self):
        """Close the position"""
        pass

    @abstractmethod
    def update_portfolio(self):
        """Updates the portfolio"""
        pass


class Portfolio(AbstractPortfolio):
    """Defines the attributes and methods of the portfolio

        Attributes:
            positions (Positions): List of the positions in the portfolio
    """
    def __init__(self):
        """Initializes a Portfolio object."""
        self.positions: List[Position] = None

    def open_position(self, *args, **kwargs):
        """Opens the position"""
        pass

    def close_position(self, *args, **kwargs):
        """Close the position"""
        pass

    def update_portfolio(self, *args, **kwargs):
        """Updates the portfolio"""
        pass
