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

**Correction, 2026-08-26 -- the utilisation ladder's sourcing has collapsed.**
Until this date every docstring in this module and in
:mod:`plutus.market.session.deposit` said the 80/90/100 ladder's *shape* was
"VSDC-sourced (Article 13 of the clearing rulebook)". The clearing rulebook's
current edition -- **QD 26/QD-HDTV of 2025-04-16**, in force from the KRX
cutover and replacing QD 12/QD-HDTV of 2023-08-10 -- has now been read in
full. **Dieu 13 contains no percentage of any kind.** It is a binary test:
*"Truong hop gia tri tai san ky quy tren tai khoan nha dau tu nho hon gia tri
ky quy yeu cau"* -- margin assets below required margin is the violation,
full stop.

Where 80/90/100 does appear is **Dieu 29**, and it is a ladder on **position
limits**, not on margin: three warning levels at 80%, 90% and 100% *"gioi han
vi the"*, counted in contracts against the published cap. That is a real,
primary-sourced rule about a different quantity, and this object does not
implement it.

So the honest statement, in both directions:

* **Post-KRX (2025-05-05 ->): definitively misattributed.** The margin ladder
  we apply is unsourced. The document at the end of the citation chain has
  been read and does not contain it.
* **Pre-KRX (to 2025-05-04): UNVERIFIED, not disproven.** QD 61/QD-VSD and
  QD 12/QD-HDTV have never been read by anyone on this project; the chain
  QD 96 -> QD 61 -> QD 12 -> QD 26 is broken only at its final link. QD 26
  removing a ladder that QD 61 had is entirely consistent with everything
  read. Do not "correct" the pre-KRX regime to say the ladder is wrong.

**The numeric defaults below are unchanged and deliberately so.** An unsourced
default that behaves correctly is better than a silent behaviour change, and
the choice is the author's. One thing the primary text does settle in their
favour: with ``forced_close_utilisation = 1.00``, the test ``MR / assets >=
1.00`` is arithmetically ``assets <= MR``, and ``assets < MR`` is the *whole*
of Dieu 13. So the top rung reproduces the regulated binary test everywhere
except the boundary ``assets == MR``, which Dieu 13.2.c treats as cured
(*"bang hoac lon hon muc ky quy yeu cau"*) and we treat as a breach --
conservative by one tick. The two lower rungs correspond to nothing in the
read text.
"""

from dataclasses import dataclass
from decimal import Decimal

__all__ = ['BrokerTerms', 'CureWindow']


class CureWindow:
    """How long an investor has to answer a margin call, in sessions.

    ``NEXT_SESSION`` -- the call must be cured before the next session's close.
    ``SAME_SESSION`` -- intraday call; the broker may force-close the same day.

    **Two deadlines are regulated and one is not. Do not merge them.**

    Regulated, and now primary-sourced to QD 26/QD-HDTV Dieu 13:

    * **Top-up before 09h30 the next trading day.** Dieu 13.1: VSDC computes
      MR per investor account by 16h30 and wires the clearing member; where
      assets fall short the member *"co trach nhiem nop bo sung truoc 09h30
      ngay giao dich lien ke tiep theo"*.
    * **03 working days, then somebody else closes you.** Dieu 13.3.b: if the
      breach is uncured 03 working days after VSDC's wire, VSDC directs
      **another clearing member** to place the offsetting trades, and the
      resulting positions are transferred back to the breaching member. The
      identical 03-day window and mechanism appear at Dieu 29.5 for a
      position-limit level-3 breach.

    Both of those run **clearing member <-> VSDC**. Neither is a broker's
    deadline to its retail client, and nothing read on this project fixes that
    one: it is a term of the account-opening agreement. That is why the number
    lives here and not in the dated rulebook.

    The default is one session and the author's decision is that it stays one
    session, configurability deferred. For HNXDS the next session opens at
    08:45 (the opening auction), so the default deadline lands **45 minutes
    ahead of** the regulated 09h30 T+1 top-up -- tighter than the rule, which
    is the direction a broker's own term is allowed to move in. That is a
    corroboration of the default's plausibility, **not** a source for it.
    """

    SAME_SESSION = 0
    NEXT_SESSION = 1


@dataclass(frozen=True)
class BrokerTerms:
    """Commercial terms of one securities company.

    Attributes:
        margin_call_utilisation: the utilisation ratio ``MR / margin assets``
            at or above which the broker issues a call. Vietnam publishes
            **no maintenance margin ratio**; the call is a utilisation test,
            so this is a fraction of the requirement consumed, not a fraction
            of notional. **The three-rung ladder is ours, not VSDC's** -- see
            the module docstring and :attr:`PROVENANCE`. QD 26 Dieu 13 tests
            ``assets < MR`` and nothing else; a broker that layers a call and
            a warning underneath the regulated breach is doing something
            entirely plausible and entirely undocumented.
        forced_close_utilisation: the level at which the broker stops asking
            and closes positions itself. At the default ``1.00`` this rung
            *is* the regulated test, up to the ``assets == MR`` boundary.
        warning_utilisation: the level at which the broker warns but takes no
            action. Corresponds to nothing in any document read.
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
    #: **Nothing here is sourced to a document, including the ladder's shape.**
    #: An earlier revision of this dict claimed the shape was primary-sourced
    #: to Article 13 of the clearing rulebook. QD 26/QD-HDTV Dieu 13 has since
    #: been read in full and has no percentages; the 80/90/100 that the chain
    #: was tracking is Dieu 29's ladder on **position limits**. See the module
    #: docstring for the pre-KRX / post-KRX split -- post-KRX the margin
    #: attribution is dead, pre-KRX it is UNVERIFIED rather than disproven,
    #: because QD 61 and QD 12 have never been read.
    #:
    #: 0.031%/day sits inside the 0.025-0.05%/day range brokers quote for the
    #: sale advance, which is the nearest observable product, not the same one.
    #: The next-session cure window is the common case and the safe one to
    #: assume, not a rule -- and the regulated deadlines that *do* exist run
    #: between the clearing member and VSDC, never between broker and client
    #: (:class:`CureWindow`).
    #:
    #: A broker survey -- the commercial counterpart to the exchange-rulebook
    #: research -- is scheduled work. Until it lands, a published result that
    #: is sensitive to any of these must say which value it used and that the
    #: value is an assumption.
    PROVENANCE = {
        'margin_call_utilisation':
            'UNSOURCED. Applying a utilisation ladder to margin is our shape, '
            'not a published one: QD 26 Dieu 13 (post-KRX, read in full) is a '
            'binary assets < MR test and carries no percentage. 80/90/100 IS '
            'primary-sourced -- at QD 26 Dieu 29, as three warning levels on '
            'the POSITION LIMIT, a different rule on a different quantity '
            'that this object does not implement. Pre-KRX (to 2025-05-04) the '
            'margin thresholds are UNVERIFIED, not disproven: QD 61 and QD 12 '
            'have never been read. The level is in any case per-broker and '
            'unpublished.',
        'forced_close_utilisation':
            'UNSOURCED as a rung; as margin_call_utilisation. The default '
            '1.00 is not arbitrary though: MR / assets >= 1.00 is assets <= '
            'MR, and assets < MR is the entire QD 26 Dieu 13 test, so this '
            'rung reproduces the regulated binary breach except at assets == '
            'MR, which Dieu 13.2.c treats as cured and we treat as breach.',
        'warning_utilisation':
            'UNSOURCED; as margin_call_utilisation, and with no counterpart '
            'at all in the read text -- Dieu 13 has one state, not three.',
        'advance_on_sale_daily_rate':
            'assumed; inside the 0.025-0.05%/day band brokers quote for the '
            'sale advance itself. An earlier revision attributed the band to '
            'margin lending, which is a different product.',
        'cure_window_sessions':
            'assumed for the broker-to-investor window, which no document '
            'read sets. PARTLY REGULATED at the member-to-VSDC level: QD 26 '
            'Dieu 13.1 requires top-up before 09h30 the next trading day, and '
            'Dieu 13.3.b gives 03 working days before VSDC directs another '
            'clearing member to close the account (Dieu 29.5, same window, '
            'for a position-limit breach). Author decision: default stays '
            'NEXT_SESSION.',
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
