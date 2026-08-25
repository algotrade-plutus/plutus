"""Broker terms -- the commercial half of the rulebook.

Two kinds of rule govern a Vietnamese trade and they must not live in the same
object.

**Exchange rules** are gazetted and dated. The round lot, the tick grid, the
price band, the session calendar, the VSD initial margin ratio: every firm in
the market is bound by the same value on the same day, and that value has a
decision or notice behind it. Those belong in
:mod:`plutus.core.constant` and the dated rulebook.

**Broker terms** are commercial and per-firm. The margin-call threshold, the
interest rate on an advance against sale proceeds, the cure window, the
commission schedule: two investors trading the same instrument on the same day
through different brokers face different numbers, and no public document fixes
them. They belong here, in caller-supplied config.

Conflating the two is how a simulator ends up asserting a broker's house rule
as if it were market law. Every default below is a **plausible market value,
not a sourced one** -- see :attr:`BrokerTerms.PROVENANCE`. They exist so a
caller can run without filling in a form, and every one is meant to be
overridden from the session config.
"""

from dataclasses import dataclass
from decimal import Decimal

__all__ = ['BrokerTerms', 'CureWindow']


class CureWindow:
    """How long an investor has to answer a margin call, in sessions.

    ``NEXT_SESSION`` -- the call must be cured before the next session's close.
    ``SAME_SESSION`` -- intraday call; the broker may force-close the same day.
    """

    SAME_SESSION = 0
    NEXT_SESSION = 1


@dataclass(frozen=True)
class BrokerTerms:
    """Commercial terms of one securities company.

    Attributes:
        margin_call_utilisation: the utilisation ratio ``MR / margin assets``
            at or above which the broker issues a call. VSDC runs a ladder --
            warning, call, forced close -- and each clearing member sets its
            own levels, which must be no looser than VSDC's. Vietnam publishes
            **no maintenance margin ratio**; the call is a utilisation test,
            so this is a fraction of the requirement consumed, not a fraction
            of notional.
        forced_close_utilisation: the level at which the broker stops asking
            and closes positions itself.
        warning_utilisation: the level at which the broker warns but takes no
            action.
        advance_on_sale_enabled: whether this broker offers *ứng trước tiền
            bán* -- an advance against unsettled sale proceeds, letting an
            investor use T+0 what would otherwise arrive T+2.
        advance_on_sale_daily_rate: the daily interest charged on that
            advance, as a fraction of the advanced amount.
        cure_window_sessions: sessions allowed to answer a call before forced
            closure -- see :class:`CureWindow`.
    """

    margin_call_utilisation: Decimal = Decimal('0.90')
    forced_close_utilisation: Decimal = Decimal('1.00')
    warning_utilisation: Decimal = Decimal('0.80')

    advance_on_sale_enabled: bool = False
    advance_on_sale_daily_rate: Decimal = Decimal('0.00031')   # 0.031%/day

    cure_window_sessions: int = CureWindow.NEXT_SESSION

    #: Where each default came from. Read this before quoting any of them.
    #:
    #: Nothing here is sourced to a document. The utilisation ladder's *shape*
    #: is primary-sourced -- VSDC does run a three-level test against
    #: ``MR / margin assets`` -- but the levels a given broker sets are its own
    #: commercial choice and are not published. 0.031%/day sits inside the
    #: 0.025-0.05%/day range brokers quote for margin lending, which is the
    #: nearest observable product, not the same one. The next-session cure
    #: window is the common case and the safe one to assume, not a rule.
    #:
    #: A broker survey -- the commercial counterpart to the exchange-rulebook
    #: research -- is scheduled work. Until it lands, a published result that
    #: is sensitive to any of these must say which value it used and that the
    #: value is an assumption.
    PROVENANCE = {
        'margin_call_utilisation': 'assumed; ladder shape is VSDC-sourced, '
                                   'the level is per-broker and unpublished',
        'forced_close_utilisation': 'assumed; as above',
        'warning_utilisation': 'assumed; as above',
        'advance_on_sale_daily_rate': 'assumed; inside the 0.025-0.05%/day '
                                      'band brokers quote for margin lending, '
                                      'which is a different product',
        'cure_window_sessions': 'assumed; next-session is the common case',
    }

    def __post_init__(self):
        ladder = (self.warning_utilisation,
                  self.margin_call_utilisation,
                  self.forced_close_utilisation)
        if not ladder[0] <= ladder[1] <= ladder[2]:
            raise ValueError(
                f'utilisation ladder must be non-decreasing '
                f'(warning <= call <= forced close), got {ladder}'
            )
        if self.advance_on_sale_daily_rate < 0:
            raise ValueError(
                f'advance_on_sale_daily_rate must not be negative, got '
                f'{self.advance_on_sale_daily_rate}'
            )
        if self.cure_window_sessions < 0:
            raise ValueError(
                f'cure_window_sessions must not be negative, got '
                f'{self.cure_window_sessions}'
            )


BrokerTerms.DEFAULT = BrokerTerms()
