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
from datetime import date
from decimal import Decimal

from plutus.market.protocol import Position, Side

__all__ = ['MarginConfig', 'MarginState', 'evaluate_margin',
           'VSD_INITIAL_MARGIN', 'vsd_initial_margin']


#: VSD/VSDC's initial margin ratio for VN30 index futures, by effective date.
#:
#: Each step was issued as a *thông báo* (notice) under a standing delegation
#: in the clearing rulebook, **not** as a numbered quyết định -- citing
#: "Quyết định XX/QĐ-VSD set margin to 17%" would be citing a document that
#: does not exist.
#:
#: 17.5% -- this module's previous constant -- appears in no source at any
#: date. It is a transcription slip for 0.17.
#:
#: VSD re-determines the ratio on the 1st, 10th and 20th of each month from a
#: VaR assessment over at least 90 trading days, and publishes it **per listed
#: contract**, so the fully correct key is ``(contract_code, date)`` rather
#: than date alone. Every contract has carried the same ratio since
#: 2022-12-15, which is why a date-keyed schedule is sufficient today and will
#: not be sufficient forever.
VSD_INITIAL_MARGIN = (
    (date(2017, 8, 10), Decimal('0.10')),
    (date(2018, 7, 18), Decimal('0.13')),
    (date(2022, 12, 15), Decimal('0.17')),
)


def vsd_initial_margin(on: date) -> Decimal:
    """The VSD initial margin ratio in force on ``on``.

    Raises:
        ValueError: for a date before the derivatives market opened, where no
            ratio existed to look up.
    """
    for effective, rate in reversed(VSD_INITIAL_MARGIN):
        if on >= effective:
            return rate
    raise ValueError(
        f'no VSD initial margin ratio in force on {on}; the Vietnamese '
        f'derivatives market opened {VSD_INITIAL_MARGIN[0][0]}'
    )


@dataclass(frozen=True)
class MarginConfig:
    """Rates governing a derivatives margin account.

    .. warning::

       **This is the legacy per-position model and its shape is wrong.**
       Vietnam margins the whole account, not each position: the requirement
       is ``MR = IM + VM`` computed over the account's entire portfolio and
       tested as a *utilisation* ratio, ``MR / margin assets``, against a
       broker's threshold ladder. There is **no published maintenance margin
       ratio** in Vietnam, so ``maintenance_rate`` below models a quantity
       that does not exist, and the "6.06% call threshold" this docstring
       previously derived from it is an artefact of that invention rather
       than a market fact.

       It is kept, unchanged, as the batch research path that the published
       margin-incidence figures were computed on -- removing it would silently
       restate those numbers. The account-level replacement is specified in
       the exchange-simulator design (section 7.4) and is scheduled work. Do
       not build anything new on this class.

    ``vsd_initial`` defaults to the ratio in force **today**. Anything walking
    a historical path must resolve it per date with
    :func:`vsd_initial_margin`; the derivatives tax base is linear in this
    same ratio, so one dated series has to feed both or the two disagree.
    """

    vsd_initial: Decimal = Decimal('0.17')
    broker_buffer: Decimal = Decimal('0.05')
    #: Models a ratio Vietnam does not publish -- see the class warning. Kept
    #: only so the legacy walk in `exchanges/derivatives.py` still runs.
    maintenance_rate: Decimal = Decimal('0.17')
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
