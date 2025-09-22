"""This module defines the Algorithm concepts."""
from abc import ABC, abstractmethod

from plutus.core.portfolio import Portfolio


class AbstractAlgorithm(ABC):
    """Defines the abstraction of the Trading Algorithm."""

    @abstractmethod
    def is_signal(self) -> bool:
        """Detects the signal given the data"""
        pass

    @abstractmethod
    def take_profit(self):
        """Takes the profit based on signal"""
        pass

    @abstractmethod
    def cut_loss(self):
        """Cut the loss based on signal"""
        pass

    @abstractmethod
    def open_position(self):
        """Opens trading position based on signal."""
        pass

    @abstractmethod
    def close_position(self):
        """Closes trading position based on signal."""
        pass


class Algorithm(AbstractAlgorithm):
    """Defines the Trading Algorithm

    Attributes:
        portfolio (Portfolio): The portfolio associated with the algorithm.

    """
    def __init__(
        self,
        portfolio: Portfolio = None
    ):
        """Initiates the portfolio object"""
        self.portfolio = portfolio

    def is_signal(self, *args, **kwargs):
        """Defines the signals in this Algorithm"""
        pass

    def open_position(self, *args, **kwargs):
        """Opens position"""
        pass

    def close_position(self, *args, **kwargs):
        """Closes position"""

    def take_profit(self, *args, **kwargs):
        """Takes profit"""
        pass

    def cut_loss(self, *args, **kwargs):
        """Cut loss"""
        pass
