"""Variation-margin arithmetic for a single derivatives position.

**Variation margin is exchange-side.** It is a quantity the exchange itself
computes and collects each day. *Strategy P&L* is trader-side: it nets across
positions, subtracts fees and tracks a cash balance, and none of that happens
here. That distinction is what lets this module mark a position to market
daily without becoming a backtester.

Every threshold below is a **modelling assumption with no corpus backing** --
no margin, position-limit or account data exists in any table of either
corpus. The values are the published Vietnamese ones, and they are config, so
a caller can sweep them.
"""

from dataclasses import dataclass
from decimal import Decimal

from plutus.market.protocol import Position, Side

__all__ = ['MarginConfig', 'MarginState', 'evaluate_margin']


@dataclass(frozen=True)
class MarginConfig:
    """Rates governing a derivatives margin account.

    ``maintenance_rate`` is derived rather than invented: it is set to the VSD
    initial requirement, so the broker buffer is what stands between posting
    and a call.

    Note the trigger is not a 5% adverse move. Notional is marked to market
    alongside equity, so the ratio falls more slowly than the price does. The
    exact threshold for a long is::

        S_call / S_entry = (1 - initial_rate) / (1 - maintenance_rate)

    which at the defaults is 0.775 / 0.825 = 0.9394 -- a **6.06%** fall.
    """

    vsd_initial: Decimal = Decimal('0.175')
    broker_buffer: Decimal = Decimal('0.05')
    maintenance_rate: Decimal = Decimal('0.175')
    liquidation_rate: Decimal = Decimal('0')
    default_multiplier: Decimal = Decimal('100000')   # VND per index point

    @property
    def initial_rate(self) -> Decimal:
        """Fraction of notional a position must post at entry."""
        return self.vsd_initial + self.broker_buffer

    def with_initial(self, initial_rate: Decimal) -> 'MarginConfig':
        """A copy whose total initial rate is ``initial_rate``.

        Used by the sensitivity sweep. The buffer absorbs the change so the
        VSD component stays at its published value.
        """
        return MarginConfig(
            vsd_initial=self.vsd_initial,
            broker_buffer=initial_rate - self.vsd_initial,
            maintenance_rate=self.maintenance_rate,
            liquidation_rate=self.liquidation_rate,
            default_multiplier=self.default_multiplier,
        )


MarginConfig.VN30F_DEFAULT = MarginConfig()


@dataclass(frozen=True)
class MarginState:
    """The margin account of one position on one day."""

    settlement: Decimal
    notional: Decimal
    equity: Decimal
    ratio: Decimal


def evaluate_margin(
    position: Position,
    settlement: Decimal,
    config: MarginConfig,
) -> MarginState:
    """Mark one position to one settlement price.

    Raises:
        ValueError: if ``settlement`` is not positive -- notional would be zero
            or negative and the ratio undefined. Refusing beats returning a
            meaningless number.
    """
    if settlement <= 0:
        raise ValueError(
            f'settlement must be positive, got {settlement}; notional and '
            f'margin ratio are undefined otherwise'
        )

    multiplier = position.multiplier or config.default_multiplier
    signed = Decimal(position.quantity) * (
        Decimal('1') if position.side is Side.BUY else Decimal('-1'))

    entry_notional = Decimal(position.quantity) * multiplier * position.entry_price
    notional = Decimal(position.quantity) * multiplier * settlement

    posted = (position.posted_margin if position.posted_margin is not None
              else config.initial_rate * entry_notional)
    equity = posted + signed * multiplier * (settlement - position.entry_price)

    return MarginState(settlement=settlement, notional=notional,
                       equity=equity, ratio=equity / notional)
