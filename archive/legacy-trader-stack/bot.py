"""Bot module.

.. warning::

   **Experimental and unsupported.** This module is a stub. It is not part of
   the public API, it is not exported from :mod:`plutus`, and Plutus does not
   ship a backtesting or live-execution engine. ``Bot.run()`` is a no-op.

   Plutus contributes a market-faithful data and instrument layer; execution
   belongs to whatever engine consumes it. Do not build on this module.

   It remains in the tree only to keep the object vocabulary (algorithm,
   portfolio, datahub) that the instrument layer is designed around visible.
"""

from typing import TYPE_CHECKING, Any, Optional

from plutus.core.algorithm import Algorithm
from plutus.core.portfolio import Portfolio

if TYPE_CHECKING:
    # Imported for type checking only. The legacy `plutus.data` stack is not
    # importable at runtime (`plutus.data.datahub` requests a `QuoteNamedTuple`
    # that `plutus.data.model.quote` does not define), and the modern query
    # path lives in `plutus.datahub` instead. Keeping this behind TYPE_CHECKING
    # lets the module import cleanly without reviving that stack.
    from plutus.data.datahub import DataHub

__all__ = ["Bot"]


class Bot:
    """Defines the Bot abstract.

    Experimental; see the module docstring. Constructing a ``Bot`` is
    permitted, but ``run()`` does nothing.

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
        datahub: "DataHub",
        order_manager: Optional[Any] = None
    ):
        self.algorithm = algorithm
        self.portfolio = portfolio
        self.datahub = datahub
        self.order_manager = order_manager

    def run(self, mode='backtest'):
        """No-op. Plutus does not implement an execution engine.

        Raises:
            NotImplementedError: Always. Kept explicit so that no caller can
                mistake a silent no-op for a completed backtest.
        """
        raise NotImplementedError(
            "Plutus does not ship a backtesting or live-execution engine. "
            "Bot.run() is a stub; use Plutus for market-faithful data and "
            "instrument modelling and run execution in a dedicated engine."
        )
