"""The Exchange contract: order admission and position survival."""

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from plutus.core.constant import ExchangeSpec
from plutus.market.protocol import InstrumentSpec, MarketState, Order, Position
from plutus.market.verdicts import Admissibility, Viability

__all__ = ['Exchange']


class Exchange(ABC):
    """Models one exchange's decisions about orders and positions.

    Two method families, deliberately separate because they bind on different
    exchanges: :meth:`admits` (stateless order admission) dominates the equity
    exchanges, :meth:`sustains` (stateful position survival) dominates the
    derivatives exchange. That asymmetry is the central empirical finding, and
    it is visible here in the architecture rather than only in the prose.
    """

    def __init__(self, spec: ExchangeSpec):
        self.spec = spec

    @property
    def code(self) -> str:
        return self.spec.code

    @abstractmethod
    def admits(
        self,
        order: Order,
        state: MarketState,
        *,
        instrument: Optional[InstrumentSpec] = None,
        regime_tag: Optional[str] = None,
    ) -> Admissibility:
        """Would this exchange accept this order at this instant?"""

    def sustains(
        self,
        position: Position,
        path: Sequence[MarketState],
        **kwargs,
    ) -> Viability:
        """Would this exchange let this position survive this path?

        Equity exchanges impose no margin, no position limit and no expiry, so
        the base implementation reports unconditional survival. The derivatives
        exchange overrides it.
        """
        return Viability(
            survived=True, events=(), days_evaluated=len(path),
            days_indeterminate=0,
        )

    def __repr__(self) -> str:
        return f'{type(self).__name__}({self.spec.code!r})'
