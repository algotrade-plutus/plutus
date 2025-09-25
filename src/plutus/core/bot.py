"""Bot module"""

from algorithm import Algorithm
from portfolio import Portfolio
from plutus.data.datahub import DataHub


class Bot:
    """Defines the Bot abstract

    Attributes:
        algorithm (Algorithm): The algorithm, main logic of the bot
        portfolio (Portfolio): The portfolio, main storage of the bot
        datahub (DataHub): The datahub, main input of the bot
        order_manager (OrderManager): The order manager of the bot. Optional
    """
    def __init__(
        self,
        algorithm: Algorithm,
        portfolio: Portfolio,
        datahub: DataHub,
        order_manager=None
    ):
        self.algorithm = algorithm
        self.portfolio = portfolio
        self.datahub = datahub
        self.order_manager = order_manager

    def run(self, mode='backtest'):
        pass
