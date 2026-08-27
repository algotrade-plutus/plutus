"""Corporate actions: the ex-date reference, the holding, and live orders.

Design section 15 item 5 declared the absence of this module a *limitation*,
not an oversight: "Dividends, splits, bonus and rights issues change both the
reference price and the holdings quantity. Until the rulebook carries the
adjustment formulas, a run spanning an ex-date is wrong for that instrument."
The rulebook research has since sourced them, and this module is the engine.
Two halves, and the second is as load-bearing as the first:

* the **arithmetic** -- one adjusted reference price, one quantity factor, one
  cash leg, applied over the tranche list so a split scales every parcel
  including the unsettled ones and their distinct settlement instants survive;
* the **audit** -- :class:`CorporateActionAudit`, which lets a run *report*
  that it crossed a corporate action it never applied, instead of silently
  returning a number that is wrong for that instrument.

**Where this module sits.** It is driven by the caller, not by
``ExchangeSession.advance_to``. Nothing in ``exchange.py`` reaches into it, and
that is deliberate for one reason worth stating: a corporate-action feed is
*exogenous data*, on the same footing as the market data adapter and the VSDC
settlement calendar. There is no way to derive an ex-date from a price series,
and a session that silently invented one would be worse than a session that
says it does not know. So the caller supplies a :class:`CorporateActionSchedule`
and either drives :class:`CorporateActionEngine` across it or -- the minimum
honest behaviour -- attaches a :class:`CorporateActionAudit` and reads the
report.

Units, declared once and enforced by the constructors, because this is the one
place in the package where two money conventions meet:

* **Every money field on a** :class:`CorporateAction` **is VND per share.** A
  2,000d cash dividend is ``Decimal('2000')``. That matches
  ``HoldingsLedger.apply_corporate_action``'s ``cash_per_share``, which credits
  VND.
* **A price is quoted in the venue's currency unit** -- thousands of dong at
  HSX, HNX and UPCoM (``VietnamMarketConstant.CURRENCY_UNIT``), so an HSX close
  of ``25.5`` is 25,500d. :func:`adjusted_reference` divides the cash leg by
  that unit before subtracting it. Skipping the conversion turns a 2,000d
  dividend on a 25.5 close into a reference of ``-1974.5``; the error is
  invisible in a ratio and fatal in a band.

**The event conserves money, and one of its legs is a purchase.** What the
unsourced algebra encodes -- and the one thing the sources agree on
(:data:`ARITHMETIC`) -- is that market capitalisation is unchanged across the
event: the reference falls by exactly the value that left the company or
diluted in. Three legs move value one way only: a cash dividend pays out, a
stock dividend and a bonus issue dilute. The fourth does not. **Rights shares
are bought, not given**, at ``subscription_price`` per share, and the price
formula already assumes the money went in -- ``Pa * a`` sits in its numerator.
So the engine debits the subscription when, and only when, the caller states
that the rights were taken up, and it refuses to guess
(:meth:`CorporateActionEngine.apply`). Crediting the shares without debiting
what they cost creates money out of the event, and it is the one arithmetic
error here that no downstream number would reveal: the holding is larger, the
cash is untouched, and every invariant in the package still holds.

**What is gazetted and what is not.** The distinction runs through every
docstring below and it is the one claim this package cannot afford to blur.
The *principle* is gazetted: on the ex-rights date the reference is the most
recent close "dieu chinh theo gia tri co tuc duoc nhan hoac gia tri cua cac
quyen kem theo" (QD 352 Dieu 10.3; QD 17 Dieu 32.4; QD 22/2026 Dieu 33.4,
confidence high). The *algebra* is not: rulebook 3.6 records the formula this
module implements as **market practice, NOT IN ANY GAZETTED DOCUMENT**,
broker- and market-education-sourced, confidence medium, and instructs that it
be marked clearly in the paper as "the one place in this domain where the
traceability claim cannot be met". :data:`ARITHMETIC` carries that sentence as
data, not as prose, so a published result can print it.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import Enum
from typing import (Dict, FrozenSet, Iterable, List, Mapping, Optional,
                    Protocol, Sequence, Tuple)

from plutus.core.constant import VietnamMarketConstant
from plutus.core.order import Side
from plutus.market.protocol import SessionPhase
from plutus.market.session.ledgers import SecuritiesAccount
from plutus.market.session.orders import OrderBookOfRecord
from plutus.market.session.types import (Amended, Confidence, Holding,
                                         HoldingTranche, OrderId,
                                         OrderRecord, ResourceKind,
                                         RuleCitation, Venue)

__all__ = [
    'ARITHMETIC',
    'CorporateAction',
    'CorporateActionApplied',
    'CorporateActionAudit',
    'CorporateActionEngine',
    'CorporateActionKind',
    'CorporateActionReport',
    'CorporateActionSchedule',
    'PROVENANCE',
    'ReferenceAdjustment',
    'RestingOrderOutcome',
    'RestingOrderPolicy',
    'RightsSubscriptionUnfunded',
    'SessionView',
    'UnhandledCorporateAction',
    'UnhandledCorporateActionError',
    'UnsourcedCorporateAction',
    'adjusted_reference',
    'quantity_factor',
    'round_to_quotation_unit',
    'subscription_shares',
]


#: One dong. The Vietnamese dong has no subunit, so every cash quantity this
#: module writes back to a ledger is an integer number of them.
_DONG = Decimal('1')


def _whole_dong(amount: Decimal) -> Decimal:
    """Round a cash amount up to a whole dong.

    Used where a ratio is applied to money. ``ROUND_CEILING`` rather than
    ``ROUND_HALF_UP`` because the only caller is re-taking a **reservation**,
    where the safe direction is to hold slightly too much rather than slightly
    too little.
    """
    return amount.quantize(_DONG, rounding=ROUND_CEILING)


# --------------------------------------------------------------------------
# Citations. Every one is a row of rulebook 3.6 or 3.3, quoted by article.
# --------------------------------------------------------------------------

#: The gazetted *principle*: the ex-date reference is the prior close adjusted
#: for the value of the dividend received or of the rights attached. This is
#: what the exchanges actually publish; it fixes no algebra.
EX_DATE_PRINCIPLE = RuleCitation(
    document='QD 352/QD-SGDHCM; VNX QD 17/QD-VNX; QD 22/2026',
    article='Dieu 10.3 / Dieu 32.4 / Dieu 33.4',
    effective_from=date(2021, 7, 5),
    confidence=Confidence.HIGH,
    note='"dieu chinh theo gia tri co tuc duoc nhan hoac gia tri cua cac quyen '
         'kem theo". A principle, not a formula. UPCoM carries the identical '
         'clause with the round-lot VWAP in place of the close '
         '(QD 34 Dieu 19.5; QD 23/2026 Dieu 20.5, from 2022-11-16).',
)

#: The arithmetic this module implements. **Not gazetted anywhere.**
ARITHMETIC = RuleCitation(
    document='Broker and market-education sources; no gazetted text',
    article=None,
    effective_from=date(2020, 1, 1),
    confidence=Confidence.MEDIUM,
    note="P' = (P + sum_i(Pa_i * a_i) - C) / (1 + sum_i a_i + sum_j b_j). "
         'Rulebook 3.6 marks this row NOT IN ANY GAZETTED DOCUMENT and calls '
         'it "the one place in this domain where the traceability claim '
         'cannot be met". What the sources agree on is the conservation '
         'principle it encodes: market capitalisation is unchanged across the '
         'event. The rounding direction after adjustment is unspecified '
         'everywhere.',
)

#: Split and consolidation are framed as a **resumption**, not an ex-date.
SPLIT_RESUMPTION = RuleCitation(
    document='QD 352/QD-SGDHCM; VNX QD 17; QD 22/2026; QD 23/2026',
    article='Dieu 10.5 / Dieu 32.5 / Dieu 33.5 / Dieu 20.6',
    effective_from=date(2021, 7, 5),
    confidence=Confidence.HIGH,
    note='The reference on the day trading RESUMES is the close (HOSE/HNX) or '
         'round-lot VWAP (UPCoM) of the day before the event, adjusted by the '
         'ratio -- the stock stops trading across the event. QD 17 Dieu '
         '40.1(b) makes a split, a consolidation or a demerger a trading-halt '
         'trigger, which is why the reference rule is written as a resumption.',
)

#: "Gia tham chieu duoc lam tron theo don vi yet gia" -- rounded to the
#: quotation unit, **direction not stated**.
REFERENCE_ROUNDED_TO_TICK = RuleCitation(
    document='QD 22/2026 and predecessors',
    article='Dieu 33.8',
    effective_from=date(2022, 3, 31),
    confidence=Confidence.HIGH,
    note='Rulebook 3.5: "Direction not stated in the text. For HOSE/HNX the '
         'reference is a close, already on the grid, so the rule only bites '
         'after a corporate-action adjustment -- and that case is untested." '
         'This module therefore takes the direction as a parameter and '
         'defaults it to half-up, which was the only direction with any '
         'evidence behind it anywhere in the domain (UPCoM references are '
         'rounded half-up to 100d, 98.70% of 410,999 corpus name-days). '
         'THE HOSE CASE IS NO LONGER UNTESTED, and the corpus refutes '
         'rounding it at all: across 9 HOSE ex-dates in 2021-05..2021-07 the '
         'UNROUNDED adjusted reference reproduces the published ceiling and '
         'floor 9/9, while tick-rounding reproduces 5/9 half-up, 4/9 down and '
         '4/9 up. HPG 2021-05-31 settles it -- its published 52.70/45.90 band '
         'brackets the reference into (49.3011, 49.3458), which contains no '
         'multiple of the 0.05 quotation unit, so no rounding direction can '
         'produce it. Pass tick=None for a HOSE ex-date. Evidence and the '
         'nine cases: validation/scenarios/corporate-charges.py, EX_DATES and '
         'reference_evidence().',
)

#: Dividend or bonus paid in TREASURY shares: reference not adjusted, band
#: widened instead. HOSE ex-rights code 16.
NO_ADJUSTMENT_TREASURY_HSX = RuleCitation(
    document='QD 352/QD-SGDHCM; VNX QD 17; QD 22/2026',
    article='Dieu 13.1(a) and 10.4(b) / Dieu 31.6(c) / Dieu 31.3(c)',
    effective_from=date(2021, 7, 5),
    confidence=Confidence.HIGH,
    note='+/-20% at HSX and the reference is NOT adjusted -- the wide band '
         'absorbs the drop. HOSE ex-rights code 16, the only code that '
         'attracts a widened band.',
)

NO_ADJUSTMENT_TREASURY_HNX = RuleCitation(
    document='VNX QD 17 Phu luc III; QD 22/2026 Phu luc III',
    article='S2.4',
    effective_from=date(2022, 3, 31),
    confidence=Confidence.HIGH,
    note='+/-30%. HNX inverts HOSE on the neighbouring case: under QD 17 the '
         'treasury-share OFFERING to existing shareholders is inside the '
         'widened list at HNX and outside it at HOSE, and the 2026 text drops '
         'the offering case again.',
)

NO_ADJUSTMENT_TREASURY_UPCOM = RuleCitation(
    document='VNX QD 34; QD 23/2026',
    article='Dieu 18.2(d) / Dieu 19.2(d), 20.7(a)',
    effective_from=date(2022, 11, 16),
    confidence=Confidence.HIGH,
    note='+/-40%; reference not adjusted.',
)

#: Cash dividend at or above the base price: adjusting would drive the
#: reference to zero or negative, so it is not adjusted and the band is
#: widened instead. **NEW at 2022-03-31** -- QD 352 Dieu 10.4 does not list it.
NO_ADJUSTMENT_LARGE_CASH_HSX_HNX = RuleCitation(
    document='VNX QD 17/QD-VNX',
    article='Dieu 31.6(d), Dieu 32.4(b)',
    effective_from=date(2022, 3, 31),
    confidence=Confidence.HIGH,
    note='Test is against the prior CLOSE. The band values are weaker than '
         'the case: QD 17 Dieu 31.6(d) names the case but delegates the '
         'number and neither S1.4 nor S2.4 lists it, so +/-20% (HOSE) is '
         'first gazetted in QD 22/2025 Phu luc III S1.4 and +/-30% (HNX) in '
         'QD 22/2026 S2.4. Value unsourced for 2022-03-31 -> 2025-05-04.',
)

NO_ADJUSTMENT_LARGE_CASH_UPCOM = RuleCitation(
    document='VNX QD 34; QD 23/2026',
    article='Dieu 18.2(d) / Dieu 19.2(d)',
    effective_from=date(2022, 11, 16),
    confidence=Confidence.HIGH,
    note='+/-40%. The test is against the prior session\'s round-lot VWAP, '
         'not a close -- UPCoM has no close-based reference at all.',
)

#: The finding that settles the resting-order question as far as any document
#: settles it: **no Vietnamese order type outlives a session.**
DAY_ORDER_ONLY = RuleCitation(
    document='QD 352/QD-SGDHCM; HOSE 2025 closing-auction line',
    article='Dieu 14.1(c), 17.2',
    effective_from=date(2020, 1, 1),
    confidence=Confidence.HIGH,
    note='"LO time in force: day order ... dies at the end of the last '
         'matching phase." ATO/ATC are enterable only inside their own '
         'auction and are auto-cancelled at the cross (Dieu 14.3(b), '
         '14.4(b)); MP/MTL/MOK/MAK are decided at entry. Rulebook 2.3 carries '
         'no order type, at any venue, at any date in 2020-2026, that '
         'survives a session close.',
)

#: HOSE ex-rights event codes, gazetted from the KRX cutover.
EX_RIGHTS_CODES = RuleCitation(
    document='QD 22/2025 Phu luc III; QD 22/2026 Phu luc III',
    article='S1.5',
    effective_from=date(2025, 5, 5),
    confidence=Confidence.HIGH,
    note='01 stock dividend or bonus; 02 cash dividend; 03 both on one '
         'session; 04 rights subscription; 05 rights + stock dividend/bonus; '
         '06 rights + cash dividend; 07 all three; 16 dividend/bonus in '
         'treasury shares. Codes 08-15 and 17+ are reserved but not '
         'published. Before 2025-05-05 HOSE used XD/XR/XA/XI.',
)


#: What this module decides for itself, and what nobody has sourced.
#:
#: The same shape as :attr:`plutus.market.broker.BrokerTerms.PROVENANCE`, and
#: for the same reason: an assumption that does not say it is one reads as
#: evidence. Every entry here is a place a published result must disclose.
PROVENANCE: Mapping[str, str] = {
    'arithmetic': 'MARKET PRACTICE, NOT GAZETTED. The formula is broker- and '
                  'market-education-sourced (rulebook 3.6, confidence '
                  'medium). Only the principle it implements is gazetted.',
    'rounding_direction': 'UNSOURCED. "Rounded to the quotation unit" is '
                          'gazetted; the direction is stated nowhere. '
                          'Half-up is the default because it is the only '
                          'direction with corpus evidence anywhere in the '
                          'domain, and it is a parameter so a result can be '
                          'run all three ways.',
    'resting_order_policy': 'A CHOICE, NOT A RULE. No Vietnamese document '
                            'addresses an order live across an ex-date, '
                            'because rulebook 2.3 makes the situation '
                            'unreachable in the market: every order type is a '
                            'day order or narrower. CANCEL is the default as '
                            'the conservative reading. See '
                            ':class:`RestingOrderPolicy`.',
    'fractional_residue': 'UNSOURCED. Share quantities are whole and the '
                          'entitlement is floored, but no source obtained '
                          'states how the residue is bought out or at what '
                          'price. The residue is REPORTED, never priced.',
    'per_parcel_flooring': 'A MODELLING CHOICE. The entitlement is floored '
                           'per tranche, because locked shape 3 forbids '
                           'collapsing parcels. VSDC allocates on the '
                           'registered balance, which is the total, so the '
                           'two differ by at most one lot-fraction per open '
                           'parcel. Reported as `fractional_residue`.',
    'rights_subscription': 'THE ONE LEG THAT COSTS MONEY, and the take-up '
                           'decision itself is UNSOURCED -- it is a portfolio '
                           'decision, not a market rule, so the engine '
                           'refuses to default it. When the caller states a '
                           'take-up the engine DEBITS shares x '
                           'subscription_price from settled cash, because the '
                           'alternative -- crediting rights shares nobody '
                           'paid for -- creates money out of the event. The '
                           'charge is on the per-parcel FLOORED entitlement, '
                           'never on the fractional one; in a combined event '
                           'the floor cannot be split between the rights and '
                           'stock legs and the residue is attributed to the '
                           'free leg, so the holder is never billed for a '
                           'share the ledger did not credit.',
    'dividend_withholding_tax': 'NOT APPLIED, and not in the rulebook. The '
                                'cash leg is credited GROSS. The 5% dividend '
                                'withholding is a charge row and the rulebook '
                                'carries none for it; inventing a tax rate '
                                'here would put it where no charge table can '
                                'see it.',
    'combined_events_not_composable': 'A CONSEQUENCE OF THE ALGEBRA, not a '
                                      'choice: a rights leg and a stock leg '
                                      'on one session divide by (1+a+b), '
                                      'while applying them in sequence '
                                      'divides by (1+a)(1+b). HOSE codes '
                                      '03/05/06/07 exist because combinations '
                                      'are one event.',
}


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class UnsourcedCorporateAction(LookupError):
    """A corporate action lands where no document settles what happens.

    A ``LookupError``, mirroring
    :class:`plutus.market.session.rulebook.UnresolvedRule`, and raised for the
    same reason: the rulebook's whole claim is traceability, so the failure
    mode where nothing is known must be a refusal and not a default. The one
    branch that reaches it today is a cash dividend at or above the base price
    before 2022-03-31 -- see :func:`adjusted_reference`.
    """


class RightsSubscriptionUnfunded(ValueError):
    """A rights take-up costs more than the account can pay.

    A ``ValueError`` because it is the same class of caller error as applying
    an event before its ex-date, and a *named* one because it has an obvious
    remedy the caller may want to take automatically: apply the same action
    with ``take_up=False`` and let the rights lapse.

    Raised **before any leg is applied**. A refusal that had already scaled the
    holding would be the same fabrication this exception exists to prevent,
    only harder to see.
    """


class UnhandledCorporateActionError(RuntimeError):
    """A run crossed a corporate action nothing applied.

    Raised only by :meth:`CorporateActionReport.raise_if_unhandled`, which a
    caller opts into. The default posture is the report, not the exception:
    design section 15 says an omission that is *declared* is not a defect and
    a silent one is, and a report the caller reads satisfies that. The
    exception exists for the caller who would rather fail a run than publish a
    number that is wrong for one instrument.
    """


# --------------------------------------------------------------------------
# The event
# --------------------------------------------------------------------------

class CorporateActionKind(str, Enum):
    """What kind of event this is, as a label over the legs.

    ``STOCK_DIVIDEND`` and ``BONUS_ISSUE`` have **identical arithmetic** --
    both are new shares per existing share at a subscription price of zero --
    and HOSE's own ex-rights code 01 lumps them ("stock dividend or bonus"),
    so the distinction is not derivable from the legs and has to be declared.
    It is kept because the *accounting* differs (a stock dividend is paid out
    of retained earnings, a bonus issue out of share premium or revaluation
    surplus) and a caller reconciling against a disclosure feed needs the
    label to match.

    ``COMBINED`` is not decoration either: see
    ``PROVENANCE['combined_events_not_composable']``.
    """

    CASH_DIVIDEND = 'cash_dividend'
    STOCK_DIVIDEND = 'stock_dividend'
    BONUS_ISSUE = 'bonus_issue'
    RIGHTS_ISSUE = 'rights_issue'
    SPLIT = 'split'
    CONSOLIDATION = 'consolidation'
    COMBINED = 'combined'

    @property
    def is_ratio_event(self) -> bool:
        """True for a split or consolidation -- the two resumption events.

        The rulebook frames these as a **resumption**, not an ex-date: trading
        halts across the event (QD 17 Dieu 40.1(b)) and the reference on the
        resumption day is the pre-halt close scaled by the ratio. They
        therefore take their own degenerate form of the formula and never
        share a session with a dividend leg.
        """
        return self in (CorporateActionKind.SPLIT,
                        CorporateActionKind.CONSOLIDATION)


@dataclass(frozen=True)
class CorporateAction:
    """One event on one ticker on one session, as legs of the one formula.

    Modelled as a **single event with several legs** rather than as a class
    hierarchy, because that is the shape of the source. Rulebook 3.6 gives one
    formula::

        P' = (P + sum_i(Pa_i * a_i) - C) / (1 + sum_i a_i + sum_j b_j)

    and lists the familiar events as its *degenerate forms*: cash only
    ``P - C``; stock dividend at ratio b, ``P / (1 + b)``; rights at ratio a
    and subscription price Pa, ``(P + Pa*a) / (1 + a)``; split 1->n, ``P / n``;
    consolidation m->1, ``P * m``. A hierarchy would have to reassemble the
    formula from the subclasses to handle HOSE ex-rights codes 03, 05, 06 and
    07, which are combinations on one session -- and applying two events in
    sequence gives the **wrong answer**, dividing by ``(1+a)(1+b)`` where the
    formula divides by ``(1+a+b)``.

    Build one through the classmethods; they are the degenerate forms named,
    and they validate the legs against the declared ``kind``.

    Attributes:
        ticker: the symbol. Not a venue -- the venue is ``(ticker, ts)`` and is
            resolved by the caller's ``SymbolRouter``, never stored here
            (locked shape 1).
        ex_date: the **ngay giao dich khong huong quyen**. Buying on this
            session does not acquire the entitlement; selling on it does not
            lose it. For a split or consolidation this is the **resumption**
            day, because the stock does not trade across the event.
        cash_per_share: C, in **VND per share**, gross. See the module
            docstring on units; this is not a quoted price.
        stock_ratio: b -- new shares per existing share at a subscription
            price of zero (stock dividend or bonus issue). A 10% stock
            dividend is ``Decimal('0.1')``, not 10.
        rights_ratio: a -- new shares per existing share taken up in a rights
            issue.
        subscription_price: Pa, in **VND per share**, the price at which the
            rights shares are bought. Only meaningful with ``rights_ratio``.
        ratio_from, ratio_to: m and n for a ratio event. A 1->2 split is
            ``ratio_from=1, ratio_to=2``; a 10->1 consolidation is
            ``ratio_from=10, ratio_to=1``.
        treasury_shares: True when the stock leg is paid in **treasury**
            shares. HOSE ex-rights code 16, and the only code that widens the
            band: the reference is then not adjusted at all.
        record_date: the **ngay dang ky cuoi cung**, for the caller's records.
            Not used in the arithmetic and not needed for the entitlement --
            see :meth:`CorporateActionEngine.apply` for why the ex-date is the
            operative instant in a T+2 market.
        note: free text carried into the report.

    **The price leg of a rights issue is unconditional; the quantity leg is a
    purchase.** The formula's ``a`` is "new shares per existing share from a
    rights issue at subscription price Pa", and the reference is adjusted on
    the *entitlement*, not on what the holder chooses to do -- the exchange
    adjusts the whole market's reference before anyone has subscribed. The
    holding is the other half and does not follow: rights shares are **bought**
    at ``subscription_price``, so applying the quantity leg without paying for
    it credits shares out of nothing, and the fabricated amount is exactly
    ``a x subscription_price`` per share held -- largest, not smallest, on the
    deep-discount issue that is the ordinary Vietnamese case.

    So the two legs are decided separately and the module never applies the
    second one on its own initiative. Whether a right is exercised, sold or
    lapsed remains a portfolio decision on the caller's side (design section
    3), which is why :meth:`CorporateActionEngine.apply` **refuses to default**
    ``take_up`` for an action with a rights leg. What the engine does own is
    the arithmetic of the decision once it is stated: ``take_up=True`` credits
    the shares *and* debits what they cost, in the same call, so the two can
    never be separated; ``take_up=False`` does neither. See
    ``PROVENANCE['rights_subscription']``.
    """

    ticker: str
    ex_date: date
    kind: CorporateActionKind
    cash_per_share: Decimal = Decimal('0')
    stock_ratio: Decimal = Decimal('0')
    rights_ratio: Decimal = Decimal('0')
    subscription_price: Decimal = Decimal('0')
    ratio_from: int = 1
    ratio_to: int = 1
    treasury_shares: bool = False
    record_date: Optional[date] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ValueError('a corporate action must name a ticker')
        for name in ('cash_per_share', 'stock_ratio', 'rights_ratio',
                     'subscription_price'):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(
                    f'{name} must not be negative, got {value}; a corporate '
                    f'action that takes value away from the holder is not a '
                    f'sign flip on one of these legs')
        if self.ratio_from < 1 or self.ratio_to < 1:
            raise ValueError(
                f'a ratio event needs positive whole terms, got '
                f'{self.ratio_from}->{self.ratio_to}')
        if self.kind.is_ratio_event:
            if self.ratio_from == self.ratio_to:
                raise ValueError(
                    f'{self.kind.value} with ratio {self.ratio_from}->'
                    f'{self.ratio_to} changes nothing')
            if (self.cash_per_share or self.stock_ratio or self.rights_ratio):
                raise ValueError(
                    'a split or consolidation carries no dividend or rights '
                    'leg: rulebook 3.6 frames it as a RESUMPTION -- the stock '
                    'stops trading across the event (QD 17 Dieu 40.1(b)) -- '
                    'and gives it its own degenerate form of the formula. '
                    'Nothing sourced says how a combined ratio-and-dividend '
                    'session would be computed, so it is refused rather than '
                    'invented'
                )
        elif self.ratio_from != self.ratio_to:
            raise ValueError(
                f'{self.kind.value} carries a {self.ratio_from}->'
                f'{self.ratio_to} ratio; only SPLIT and CONSOLIDATION do')
        if self.treasury_shares and not self.stock_ratio:
            raise ValueError(
                'treasury_shares marks a dividend or bonus PAID IN treasury '
                'shares (HOSE ex-rights code 16) and needs a stock_ratio; a '
                'cash dividend cannot be paid in shares')
        if self.subscription_price and not self.rights_ratio:
            raise ValueError(
                'a subscription price without a rights ratio buys nothing')
        if not self.legs and not self.kind.is_ratio_event:
            raise ValueError(
                f'{self.kind.value} on {self.ticker} has no legs: it would '
                f'leave both the reference and the quantity unchanged')

    # -- the degenerate forms, named ------------------------------------

    @classmethod
    def cash_dividend(cls, ticker: str, ex_date: date,
                      amount_per_share: Decimal, **kw) -> 'CorporateAction':
        """``P' = P - C``. ``amount_per_share`` is **VND**, gross of tax."""
        return cls(ticker=ticker, ex_date=ex_date,
                   kind=CorporateActionKind.CASH_DIVIDEND,
                   cash_per_share=Decimal(amount_per_share), **kw)

    @classmethod
    def stock_dividend(cls, ticker: str, ex_date: date, ratio: Decimal,
                       **kw) -> 'CorporateAction':
        """``P' = P / (1 + b)``. A 10% stock dividend is ``ratio=0.1``."""
        return cls(ticker=ticker, ex_date=ex_date,
                   kind=CorporateActionKind.STOCK_DIVIDEND,
                   stock_ratio=Decimal(ratio), **kw)

    @classmethod
    def bonus_issue(cls, ticker: str, ex_date: date, ratio: Decimal,
                    **kw) -> 'CorporateAction':
        """``P' = P / (1 + b)``. Identical arithmetic to a stock dividend."""
        return cls(ticker=ticker, ex_date=ex_date,
                   kind=CorporateActionKind.BONUS_ISSUE,
                   stock_ratio=Decimal(ratio), **kw)

    @classmethod
    def rights_issue(cls, ticker: str, ex_date: date, ratio: Decimal,
                     subscription_price: Decimal, **kw) -> 'CorporateAction':
        """``P' = (P + Pa*a) / (1 + a)``. ``subscription_price`` is **VND**."""
        return cls(ticker=ticker, ex_date=ex_date,
                   kind=CorporateActionKind.RIGHTS_ISSUE,
                   rights_ratio=Decimal(ratio),
                   subscription_price=Decimal(subscription_price), **kw)

    @classmethod
    def split(cls, ticker: str, resumption_date: date, *, into: int,
              **kw) -> 'CorporateAction':
        """1->n. ``P' = P / n``, quantity ``x n``. ``resumption_date``, not an
        ex-date: the stock does not trade across the event."""
        return cls(ticker=ticker, ex_date=resumption_date,
                   kind=CorporateActionKind.SPLIT,
                   ratio_from=1, ratio_to=int(into), **kw)

    @classmethod
    def consolidation(cls, ticker: str, resumption_date: date, *, of: int,
                      **kw) -> 'CorporateAction':
        """m->1. ``P' = P * m``, quantity ``/ m``."""
        return cls(ticker=ticker, ex_date=resumption_date,
                   kind=CorporateActionKind.CONSOLIDATION,
                   ratio_from=int(of), ratio_to=1, **kw)

    @classmethod
    def combined(cls, ticker: str, ex_date: date, **legs) -> 'CorporateAction':
        """Several legs on one session -- HOSE ex-rights codes 03, 05, 06, 07.

        The only correct way to express them: two events applied in sequence
        divide the reference by ``(1+a)(1+b)`` where the formula divides by
        ``(1+a+b)``, and :class:`CorporateActionSchedule` refuses two rows on
        one ``(ticker, ex_date)`` for that reason.
        """
        return cls(ticker=ticker, ex_date=ex_date,
                   kind=CorporateActionKind.COMBINED, **legs)

    # -- reading ---------------------------------------------------------

    @property
    def legs(self) -> Tuple[str, ...]:
        """Which legs are non-zero, for the report and for :attr:`hose_code`."""
        present: List[str] = []
        if self.cash_per_share:
            present.append('cash')
        if self.stock_ratio:
            present.append('stock')
        if self.rights_ratio:
            present.append('rights')
        if self.ratio_from != self.ratio_to:
            present.append('ratio')
        return tuple(present)

    @property
    def hose_code(self) -> Optional[str]:
        """HOSE's gazetted ex-rights event code, or ``None``.

        Computed from the legs rather than stored, so it cannot disagree with
        the arithmetic. ``None`` for a split or consolidation: those are not
        ex-rights events at all -- they are resumptions -- and the published
        list (01-07, 16) has no member for them. Codes 08-15 and 17+ are
        reserved but unpublished, so this returns ``None`` rather than
        guessing at one.

        Gazetted from 2025-05-05 (:data:`EX_RIGHTS_CODES`); before that HOSE
        used XD/XR/XA/XI, and this code is anachronistic for an earlier
        ``ex_date``. It is reported, never used to decide anything.
        """
        if self.treasury_shares:
            return '16'
        legs = frozenset(self.legs)
        if 'ratio' in legs:
            return None
        return {
            frozenset({'stock'}): '01',
            frozenset({'cash'}): '02',
            frozenset({'stock', 'cash'}): '03',
            frozenset({'rights'}): '04',
            frozenset({'rights', 'stock'}): '05',
            frozenset({'rights', 'cash'}): '06',
            frozenset({'rights', 'stock', 'cash'}): '07',
        }.get(legs)

    @property
    def key(self) -> Tuple[str, date]:
        """``(ticker, ex_date)`` -- the schedule's uniqueness key."""
        return (self.ticker, self.ex_date)

    def __str__(self) -> str:
        legs = '+'.join(self.legs) or 'none'
        return f'{self.ticker}@{self.ex_date.isoformat()}[{self.kind.value}:{legs}]'


# --------------------------------------------------------------------------
# The arithmetic
# --------------------------------------------------------------------------

def quantity_factor(action: CorporateAction, *,
                    take_up: bool = False) -> Decimal:
    """The multiplier on every holding of ``action.ticker``.

    Rulebook 3.6, the "matching quantity rule" clause of the same row as the
    price formula: ``qty x (1 + sum a + sum b)``, ``x n`` for a split,
    ``/ m`` for a consolidation. A pure cash dividend returns exactly ``1``.

    ``take_up`` is the rights-issue switch. The *reference* is always adjusted
    on the full entitlement -- the exchange adjusts the market's reference
    before anyone has subscribed -- but the *holding* only grows if the holder
    subscribes, and whether they do is a portfolio decision this package does
    not make. ``take_up=False`` drops the ``a`` term from the quantity while
    leaving the price adjustment alone, which is the asymmetry a caller who
    lets rights lapse actually experiences.

    **It defaults to False, and that is not the conservative-by-habit
    choice.** This function moves no money, so its default is only ever a
    reported number -- but ``1 + a`` is the claim that the holder *received*
    the rights shares, and receiving them costs ``a x subscription_price`` per
    share held. A caller who marks a position off this factor without having
    paid that is holding shares nobody bought. The stock leg needs no such
    decision because it is free. Where the money actually moves, no default
    exists at all: :meth:`CorporateActionEngine.apply` refuses to guess.
    """
    if action.kind.is_ratio_event:
        return Decimal(action.ratio_to) / Decimal(action.ratio_from)
    rights = action.rights_ratio if take_up else Decimal('0')
    return Decimal('1') + rights + action.stock_ratio


def subscription_shares(action: CorporateAction, holding: Holding) -> int:
    """Whole rights shares ``holding`` subscribes for, floored **per parcel**.

    The quantity the subscription is charged on, and it is deliberately not
    ``holding.total * a``. ``HoldingsLedger.apply_corporate_action`` floors the
    entitlement on each tranche separately -- locked shape 3 forbids collapsing
    parcels, so the distinct settlement instants survive the adjustment -- and
    the holder therefore receives ``sum_i floor(q_i * a)`` new shares, not
    ``floor(sum_i q_i * a)``. Charging the unfloored figure would bill for a
    share the ledger never credited; see ``PROVENANCE['fractional_residue']``
    for why the residue is reported and never priced.

    **A combined event cannot attribute its floor and this module says so.**
    The ledger applies one factor per parcel, ``floor(q * (1 + a + b))``, and
    nothing sourced says whether a lost fraction came off the rights leg or the
    free stock leg. This attributes it to the free leg -- ``floor(q * a)`` is
    never more than the parcel's total gain -- so the charge is never for more
    shares than the rights leg alone would have produced. The opposite reading
    would bill the holder for a share that may not exist.
    """
    if not action.rights_ratio:
        return 0
    parcels = (holding.settled,) + tuple(t.quantity for t in holding.unsettled)
    return sum(
        int((Decimal(q) * action.rights_ratio).to_integral_value(ROUND_FLOOR))
        for q in parcels)


def round_to_quotation_unit(price: Decimal, tick: Optional[Decimal], *,
                            rounding: str = ROUND_HALF_UP) -> Decimal:
    """Round an adjusted reference onto the quotation grid.

    "Gia tham chieu duoc lam tron theo don vi yet gia" is gazetted; the
    **direction is stated nowhere** (:data:`REFERENCE_ROUNDED_TO_TICK`), and
    rulebook 3.5 notes that the rule "only bites after a corporate-action
    adjustment -- and that case is untested". So the direction is a parameter,
    and the default is half-up because that is the only direction with corpus
    evidence anywhere in this domain: UPCoM's own reference is rounded half-up
    to 100d on 98.70% of 410,999 name-days, against 97.03% for round-down and
    97.01% for round-up.

    Do **not** read the ceiling/floor rounding rule across to here. That rule
    is directional for a reason that does not apply -- ceilings round down and
    floors round up so that "the band never widens by rounding" (rulebook 3.4)
    -- and a reference has no such asymmetry.

    ``tick`` of ``None`` returns the price unrounded, which is the honest
    answer when the caller could not resolve a tick: HOSE's grid is banded by
    price and ``RuleSet.tick_size`` returns ``None`` when no tier matches.
    """
    if tick is None or tick <= 0:
        return price
    return (price / tick).quantize(Decimal('1'), rounding=rounding) * tick


@dataclass(frozen=True)
class ReferenceAdjustment:
    """The ex-date reference, and everything needed to defend the number.

    ``ratio`` is ``reference_price / base_price``. It is here because it is
    the one quantity with a *gazetted* precedent for adjusting a contractual
    price across a corporate action: QD 22/2026 Dieu 36 sets a covered
    warrant's new strike to ``old strike x (adjusted underlying ref / '
    unadjusted underlying ref)``. :class:`RestingOrderPolicy`'s ``SCALE``
    branch reuses it for a resting limit price for that reason and no other.

    ``adjusted`` is ``False`` in the two sourced no-adjustment cases, and then
    ``reference_price == base_price`` and ``widened_band_case`` names the case
    whose band replaces the ordinary one. **The rulebook module carries no
    row for either case**: ``RuleSet.widened_trading_limit`` tabulates only
    ``first_trading_day``, ``resumption``, ``illiquidity`` and
    ``convertible_bond_ex_rights``, so asking it for one of these names raises
    ``UnresolvedRule``. The sourced values are HSX +/-20%, HNX +/-30%, UPCoM
    +/-40%; they are named in the citations rather than returned, because
    inventing a band accessor here would be a second rulebook.
    """

    ticker: str
    ex_date: date
    venue: Venue
    base_price: Decimal
    raw_reference: Decimal
    reference_price: Decimal
    quantity_factor: Decimal
    cash_per_share: Decimal
    adjusted: bool
    reason: str
    citations: Tuple[RuleCitation, ...]
    rounding: str = ROUND_HALF_UP
    currency_unit: int = 1
    widened_band_case: Optional[str] = None

    @property
    def ratio(self) -> Decimal:
        """``reference_price / base_price``; ``1`` in a no-adjustment case."""
        if not self.base_price:
            return Decimal('1')
        return self.reference_price / self.base_price


def adjusted_reference(
    action: CorporateAction,
    base_price: Decimal,
    *,
    venue: Venue,
    tick: Optional[Decimal] = None,
    rounding: str = ROUND_HALF_UP,
    take_up: bool = False,
) -> ReferenceAdjustment:
    """The reference price on ``action.ex_date``, with its provenance.

    Implements rulebook 3.6's one formula::

        P' = (P + sum_i(Pa_i * a_i) - C) / (1 + sum_i a_i + sum_j b_j)

    with ``P' = P * m / n`` for a ratio event. **The formula is not gazetted**
    (:data:`ARITHMETIC`); only the principle it encodes is
    (:data:`EX_DATE_PRINCIPLE`). Both citations travel on the result.

    ``base_price`` is P: the previous session's **close** at HSX and HNX, and
    the previous session's **round-lot VWAP** at UPCoM (QD 34 Dieu 19.5 -- a
    real per-venue difference, not a simplification). This function does not
    fetch it, because choosing it correctly needs the data source and the
    dated closing-price definition, which changed at the KRX cutover in a way
    rulebook 3.5 calls "the most consequential missed delta in this research":
    before 2025-05-05 an unadjusted prior close rolls forward through a
    no-trade session and silently undoes this adjustment.

    ``take_up`` reaches only the quantity factor and never the price: the
    reference here is the *market's*, and the exchange adjusts it on the full
    entitlement before anyone has subscribed. It defaults to ``False`` so that
    the factor reported alongside the price never claims shares the holder has
    not paid for; see :func:`quantity_factor`.

    Raises:
        UnsourcedCorporateAction: when a cash dividend at or above
            ``base_price`` falls before the no-adjustment carve-out took
            effect at that venue. Adjusting drives the reference to zero or
            negative, and rulebook 3.6 is explicit that the carve-out is
            **new at 2022-03-31** -- QD 352 Dieu 10.4 does not list it. So for
            an earlier ex-date nothing sourced says what happens, and the
            module refuses rather than clamping to a number no document
            supports. Rulebook 3.4's "clamp at the reference" rule is about
            the **floor**, not the reference, and must not be read across.
    """
    unit = Decimal(VietnamMarketConstant.CURRENCY_UNIT[venue.value])
    factor = quantity_factor(action, take_up=take_up)

    if action.kind.is_ratio_event:
        raw = base_price * Decimal(action.ratio_from) / Decimal(action.ratio_to)
        return ReferenceAdjustment(
            ticker=action.ticker, ex_date=action.ex_date, venue=venue,
            base_price=base_price, raw_reference=raw,
            reference_price=round_to_quotation_unit(raw, tick,
                                                    rounding=rounding),
            quantity_factor=factor, cash_per_share=Decimal('0'),
            adjusted=True,
            reason=f'{action.kind.value} {action.ratio_from}->{action.ratio_to} '
                   f'on the resumption day',
            citations=(SPLIT_RESUMPTION, ARITHMETIC,
                       REFERENCE_ROUNDED_TO_TICK),
            rounding=rounding, currency_unit=int(unit))

    # Both money legs are VND per share; P is quoted in the venue's unit.
    cash = action.cash_per_share / unit
    subscription = action.subscription_price / unit

    no_adjustment = _no_adjustment_case(action, base_price, cash, venue)
    if no_adjustment is not None:
        case, reason, citation = no_adjustment
        return ReferenceAdjustment(
            ticker=action.ticker, ex_date=action.ex_date, venue=venue,
            base_price=base_price, raw_reference=base_price,
            reference_price=base_price,
            # The quantity leg still moves: the reference is not adjusted, but
            # the holder still receives the treasury shares, and still
            # receives the cash on an outsized dividend.
            quantity_factor=factor, cash_per_share=action.cash_per_share,
            adjusted=False, reason=reason, citations=(citation,),
            rounding=rounding, currency_unit=int(unit),
            widened_band_case=case)

    numerator = base_price + subscription * action.rights_ratio - cash
    denominator = (Decimal('1') + action.rights_ratio + action.stock_ratio)
    raw = numerator / denominator
    return ReferenceAdjustment(
        ticker=action.ticker, ex_date=action.ex_date, venue=venue,
        base_price=base_price, raw_reference=raw,
        reference_price=round_to_quotation_unit(raw, tick, rounding=rounding),
        quantity_factor=factor, cash_per_share=action.cash_per_share,
        adjusted=True,
        reason=f'ex-date adjustment, legs {"+".join(action.legs)}',
        citations=(EX_DATE_PRINCIPLE, ARITHMETIC, REFERENCE_ROUNDED_TO_TICK),
        rounding=rounding, currency_unit=int(unit))


#: When the reference is left alone and the band is widened instead. Keyed by
#: venue, each entry ``(effective_from, citation)``.
#:
#: HNX has **no separate treasury-dividend row before 2022-03-31**: QD 17 is
#: the first VNX instrument covering HNX, and HSX's QD 352 does not bind it.
#: An HNX treasury dividend with an earlier ex-date therefore falls through to
#: the ordinary adjustment, which is the sourced behaviour of that interval
#: rather than a gap.
_TREASURY_NO_ADJUSTMENT: Mapping[Venue, Tuple[date, RuleCitation]] = {
    Venue.HSX: (date(2021, 7, 5), NO_ADJUSTMENT_TREASURY_HSX),
    Venue.HNX: (date(2022, 3, 31), NO_ADJUSTMENT_TREASURY_HNX),
    Venue.UPCOM: (date(2022, 11, 16), NO_ADJUSTMENT_TREASURY_UPCOM),
}

_LARGE_CASH_NO_ADJUSTMENT: Mapping[Venue, Tuple[date, RuleCitation]] = {
    Venue.HSX: (date(2022, 3, 31), NO_ADJUSTMENT_LARGE_CASH_HSX_HNX),
    Venue.HNX: (date(2022, 3, 31), NO_ADJUSTMENT_LARGE_CASH_HSX_HNX),
    Venue.UPCOM: (date(2022, 11, 16), NO_ADJUSTMENT_LARGE_CASH_UPCOM),
}


def _no_adjustment_case(
    action: CorporateAction,
    base_price: Decimal,
    cash_in_quote_units: Decimal,
    venue: Venue,
) -> Optional[Tuple[str, str, RuleCitation]]:
    """The two sourced cases where the reference is **not** adjusted.

    Both are dated and both are per-venue, which is why this is a lookup and
    not a boolean: HOSE's treasury carve-out starts 2021-07-05, HNX's only
    with QD 17 on 2022-03-31, UPCoM's with QD 34 on 2022-11-16, and the
    outsized-cash-dividend case is new at 2022-03-31 everywhere.

    **The outsized-cash test is ``C >= P`` and nothing else, which is wider
    than its own justification on a combined event.** The sourced test is
    against the prior close (:data:`NO_ADJUSTMENT_LARGE_CASH_HSX_HNX`) and the
    reason given for it is that adjusting "would drive the reference to zero
    or negative". On a cash-only row the two coincide. On HOSE ex-rights code
    06 or 07 they do not: a rights leg puts ``+Pa*a`` in the numerator, so
    ``P = 25``, ``C = 30`` and ``a = 1`` at ``Pa = 40`` adjusts to a perfectly
    positive ``(25 + 40 - 30)/2 = 17.5``, and this function still takes the
    no-adjustment arm and leaves the reference at 25. The gazetted text names
    a cash dividend and tests a close; **nothing sourced says what a combined
    outsized-dividend-plus-rights session does**, and narrowing the test to the
    numerator would be inventing the rule rather than reading it. So the
    sourced test is applied as written and the limit is recorded here. A caller
    who meets one of these -- they are rare, and rarer still inside the corpus
    window -- is looking at a reference no document supports either way.

    Returns ``(widened_band_case, reason, citation)`` or ``None``.

    Raises:
        UnsourcedCorporateAction: a cash dividend at or above the base price
            before the carve-out exists at that venue.
    """
    on = action.ex_date

    if action.treasury_shares:
        entry = _TREASURY_NO_ADJUSTMENT.get(venue)
        if entry is not None and on >= entry[0]:
            return ('treasury_dividend_ex_date',
                    'dividend or bonus paid in treasury shares: the reference '
                    'is not adjusted and the band is widened instead (HOSE '
                    'ex-rights code 16)',
                    entry[1])

    if cash_in_quote_units and cash_in_quote_units >= base_price:
        entry = _LARGE_CASH_NO_ADJUSTMENT.get(venue)
        if entry is not None and on >= entry[0]:
            return ('cash_dividend_ge_reference',
                    'cash dividend at or above the base price: adjusting '
                    'would drive the reference to zero or negative, so it is '
                    'not adjusted and the band is widened instead',
                    entry[1])
        raise UnsourcedCorporateAction(
            f'{action}: a cash dividend of {action.cash_per_share} VND is at '
            f'or above the base price of {base_price} in quote units, and the '
            f'no-adjustment carve-out does not exist at {venue.value} on '
            f'{on.isoformat()} -- it is NEW at 2022-03-31 (VNX QD 17 Dieu '
            f'31.6(d)) and QD 352 Dieu 10.4 does not list it. Nothing sourced '
            f'says what the reference becomes, and rulebook 3.4\'s '
            f'clamp-at-the-reference rule governs the FLOOR, not the '
            f'reference, so it must not be read across'
        )
    return None


# --------------------------------------------------------------------------
# The schedule -- exogenous data, on the same footing as the market feed
# --------------------------------------------------------------------------

class CorporateActionSchedule:
    """Every corporate action a run knows about, keyed by ticker and date.

    Exogenous input. There is no way to derive an ex-date from a price series
    -- the whole point of this module is that a price series crossing one is
    *wrong* unless something tells it -- so the schedule is supplied by the
    caller exactly as the VSDC settlement calendar and the market data adapter
    are.

    **At most one action per ``(ticker, ex_date)``**, and the refusal is not
    tidiness. HOSE gazettes ex-rights codes 03, 05, 06 and 07 precisely
    because combinations happen on a single session, and the formula divides
    by ``(1 + a + b)`` where two events applied in sequence divide by
    ``(1 + a)(1 + b)``. Silently accepting two rows would produce a reference
    that is wrong by exactly ``ab/(1+a+b)`` of itself and would look
    plausible. Use :meth:`CorporateAction.combined`.
    """

    def __init__(self, actions: Iterable[CorporateAction] = ()) -> None:
        self._by_key: Dict[Tuple[str, date], CorporateAction] = {}
        for action in actions:
            self.add(action)

    def add(self, action: CorporateAction) -> CorporateAction:
        """Register one action.

        Raises:
            ValueError: if the ``(ticker, ex_date)`` pair is already taken.
                See the class docstring -- this is an algebraic constraint,
                not a uniqueness convention.
        """
        existing = self._by_key.get(action.key)
        if existing is not None:
            raise ValueError(
                f'{action.ticker} already has a corporate action on '
                f'{action.ex_date.isoformat()} ({existing}). Two events on one '
                f'session are ONE event with several legs: the sourced formula '
                f'divides by (1 + a + b) and applying them in sequence divides '
                f'by (1 + a)(1 + b), which is a different number. HOSE '
                f'gazettes ex-rights codes 03/05/06/07 for exactly this. Use '
                f'CorporateAction.combined()'
            )
        self._by_key[action.key] = action
        return action

    def for_ticker(self, ticker: str) -> Tuple[CorporateAction, ...]:
        """Every action on one ticker, in ex-date order."""
        return tuple(sorted((a for a in self._by_key.values()
                             if a.ticker == ticker),
                            key=lambda a: a.ex_date))

    def between(self, start: date, end: date, *,
                tickers: Optional[Iterable[str]] = None,
                ) -> Tuple[CorporateAction, ...]:
        """Actions with ``start <= ex_date <= end``, in ``(ex_date, ticker)`` order.

        **Both ends inclusive.** An ex-date is a whole trading session and a
        run that reached it crossed it; excluding the endpoint would let a run
        ending on an ex-date report itself clean.
        """
        wanted = None if tickers is None else frozenset(tickers)
        return tuple(sorted(
            (a for a in self._by_key.values()
             if start <= a.ex_date <= end
             and (wanted is None or a.ticker in wanted)),
            key=lambda a: (a.ex_date, a.ticker)))

    def get(self, ticker: str, ex_date: date) -> Optional[CorporateAction]:
        """One action by its key, or ``None``."""
        return self._by_key.get((ticker, ex_date))

    def tickers(self) -> FrozenSet[str]:
        """Every ticker the schedule carries an action for."""
        return frozenset(a.ticker for a in self._by_key.values())

    def __len__(self) -> int:
        return len(self._by_key)

    def __iter__(self):
        return iter(sorted(self._by_key.values(),
                           key=lambda a: (a.ex_date, a.ticker)))

    def __repr__(self) -> str:
        return (f'CorporateActionSchedule({len(self._by_key)} actions on '
                f'{len(self.tickers())} tickers)')


# --------------------------------------------------------------------------
# The open question, and the answer
# --------------------------------------------------------------------------

class RestingOrderPolicy(str, Enum):
    """What happens to an order that is live when the adjustment lands.

    **This is a choice, not a sourced rule**, and the design spec flags it as
    the open question that "decides whether the CA engine mutates live orders
    or cancels them" (section 15 item 5). The research answer, in two parts:

    1. **No Vietnamese document addresses it**, at any venue, at any date in
       2020-2026. Searched: the amendment and cancellation articles (QD 352
       Dieu 17, QD 17 Dieu 22, QD 22/2025 Dieu 21), the corporate-action
       reference rules (rulebook 3.6), the halt triggers (QD 17 Dieu 40) and
       the post-halt resumption procedure. Nothing.

    2. **The rulebook explains the silence**: no document had reason to
       address it, because in this market the situation cannot arise. Rulebook
       2.3 (:data:`DAY_ORDER_ONLY`) records that an LO is a day order that
       "dies at the end of the last matching phase"; ATO and ATC are
       auto-cancelled at their own cross and "never rest, never carry"; and
       MP, MTL, MOK and MAK are all decided at entry. **There is no order type
       in Vietnam that survives a session close.** An order cannot be live at
       the previous close and still live on the ex-date's open, and a split or
       consolidation is worse still -- trading is halted across it entirely
       (QD 17 Dieu 40.1(b)).

    So ``CANCEL`` is the default, and it is not merely the conservative
    reading: it is the reading the day-order rule implies. Any order this
    engine finds live across an adjustment is one the real market would
    already have killed at the previous close, and terminating it is what
    reproduces that. It is also the only branch that leaves the encumbrance
    ledger exactly where section 12 invariant 4 requires, since cancellation
    releases through the book's terminal hook like every other terminal edge.

    ``SCALE`` exists because the question is genuinely open and a caller
    running an intraday adjustment, or modelling a venue that does carry
    orders across, needs the other arm. It scales the quantity by the factor
    and the limit price by ``ReferenceAdjustment.ratio`` -- the one ratio with
    a gazetted precedent for adjusting a contractual price across a corporate
    action (QD 22/2026 Dieu 36 adjusts a covered warrant's strike by exactly
    it) -- and re-takes the reservation so the invariant still holds. Three
    things make it the non-default:

    * a scaled quantity need not land on the round lot, and an order off the
      lot can never fill (``ROUND_LOT``). ``apply(lot=...)`` floors it when
      the caller supplies the lot and reports that it did not when they do
      not;
    * a scaled limit price need not land on the tick grid, which this module
      cannot check without the venue's dated banded tick;
    * a **partially filled** order cannot be scaled coherently. Its fills are
      a record of what actually traded and must not be rewritten, so
      ``filled + remaining == original`` (section 12 invariant 1) forces the
      whole scaling onto the remainder: a 1,000-share order half filled and
      then doubled has 500 filled and 1,000 remaining, and an *original* of
      1,500 rather than 2,000. The already-filled 500 shares do grow -- in the
      *holding*, where the same factor reaches them -- so nothing is lost, but
      the order's own numbers no longer read as a clean multiple. **Nothing
      sourced settles this**; it is the only arrangement the invariant permits
      that does not scale a pre-event quantity as though it were a post-event
      one;
    * it keeps alive an order the market's own time-in-force rule had already
      ended.
    """

    CANCEL = 'cancel'
    SCALE = 'scale'


@dataclass(frozen=True)
class RestingOrderOutcome:
    """What one live order's adjustment did, for the applied record.

    ``policy`` is carried per order rather than once per event because the
    ``SCALE`` branch falls back to ``CANCEL`` when the scaled order would be
    degenerate -- zero quantity, or below what is already filled -- and a
    caller reconciling order ids needs to see which arm each one took.
    """

    order_id: OrderId
    ticker: str
    side: Side
    policy: RestingOrderPolicy
    quantity_before: int
    quantity_after: int
    limit_price_before: Optional[Decimal] = None
    limit_price_after: Optional[Decimal] = None
    lot_enforced: bool = False
    reason: Optional[str] = None


# --------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CorporateActionApplied:
    """One event, applied: what moved, and what could not be sourced.

    ``fractional_residue`` is the share quantity lost to flooring, exact and
    signed positive. Vietnamese share quantities are whole and the entitlement
    is floored, but **no source obtained states how the residue is bought out
    or at what price**, so it is reported and never priced -- see
    ``PROVENANCE['fractional_residue']``. It is also the visible cost of the
    per-parcel flooring that locked shape 3 requires: the entitlement is
    computed on each tranche so distinct settlement instants survive, while
    VSDC allocates on the registered total, and the two differ by at most one
    fraction per open parcel.

    ``reference`` is ``None`` when the caller applied the holdings leg without
    supplying a base price. That is legal and common -- a caller whose data
    source already carries adjusted prices needs only the quantity and cash
    legs -- but it means no reference number was produced and the report says
    so rather than implying one.

    ``late`` is True when the engine was driven at an instant after the
    ex-date. The entitlement is then measured on a holding that may already
    include shares bought **on** the ex-date, which are not entitled, so the
    cash leg and the quantity leg are both potentially overstated. It is a
    fidelity warning, not an error, and it is on the record rather than in a
    log line.

    ``cash_leg`` and ``subscription_outlay`` are the event's **two** money
    legs and they move in opposite directions: the dividend is credited, the
    subscription is debited, and :attr:`net_cash_leg` is what the account
    actually saw. Both are on the record for the same reason
    :attr:`cash_leg_is_gross` is a field rather than a comment -- a money fact
    a report can omit is a money fact a report will omit.
    """

    action: CorporateAction
    ts: datetime
    quantity_factor: Decimal
    cash_per_share: Decimal
    cash_leg: Decimal
    holding_before: Holding
    holding_after: Holding
    tranches_after: Tuple[HoldingTranche, ...]
    fractional_residue: Decimal
    resting_orders: Tuple[RestingOrderOutcome, ...] = ()
    reference: Optional[ReferenceAdjustment] = None
    late: bool = False
    take_up: bool = False
    subscription_shares: int = 0
    subscription_outlay: Decimal = Decimal('0')

    @property
    def ticker(self) -> str:
        return self.action.ticker

    @property
    def cash_leg_is_gross(self) -> bool:
        """Always True, and stated as a field so a report cannot omit it.

        The 5% dividend withholding is **not** applied. It is a charge row and
        the rulebook carries none for it (there is no dividend row anywhere in
        rulebook section 12), so applying it here would put a tax rate where
        no charge table can see it. A caller reporting net income must deduct
        it themselves and say which rate they used.
        """
        return True

    @property
    def subscription_outlay_is_debited(self) -> bool:
        """Always True, and stated as a field for the mirror-image reason.

        ``cash_leg_is_gross`` exists so a report cannot silently omit a charge
        this module did *not* take. This exists so a report cannot silently
        omit a payment this module *did*: whenever
        :attr:`subscription_outlay` is non-zero, that money has already left
        ``account.cash_ledger`` at :attr:`ts`. A caller who wants the rights
        to lapse instead asks for it at ``apply(take_up=False)``; there is no
        arrangement in which the shares arrive and the payment does not.
        """
        return True

    @property
    def net_cash_leg(self) -> Decimal:
        """``cash_leg - subscription_outlay``: what the account actually saw.

        Negative on a rights issue, and on HOSE ex-rights code 06 (rights plus
        cash dividend) it is the difference between the two legs on one
        session. It is derived rather than stored so it cannot disagree with
        the two ledger movements it summarises.
        """
        return self.cash_leg - self.subscription_outlay


class CorporateActionEngine:
    """Applies a :class:`CorporateActionSchedule` to a securities account.

    Driven by the caller between advances, in the loop shape
    ``ExchangeSession.advance_to``'s docstring already prescribes::

        for day in days:
            session.advance_to(datetime.combine(day, time(9, 0)))
            engine.apply_due(session.now(), account=..., book=...)
            session.submit(...)
            session.advance_to(datetime.combine(day, time(14, 45)))

    **The ex-date's open is the operative instant, and that is the whole
    reason this is not called at the close.** See :meth:`apply`.
    """

    def __init__(
        self,
        schedule: CorporateActionSchedule,
        *,
        resting_orders: RestingOrderPolicy = RestingOrderPolicy.CANCEL,
        rounding: str = ROUND_HALF_UP,
    ) -> None:
        """
        Args:
            resting_orders: what happens to an order live when the adjustment
                lands. Defaults to ``CANCEL``; see :class:`RestingOrderPolicy`
                for why that is a choice and what the research says.
            rounding: the direction the adjusted reference is rounded to the
                quotation unit. Gazetted that it *is* rounded, unsourced
                *which way*; a parameter so a result can be run all three
                ways. Any ``decimal`` rounding constant.
        """
        self._schedule = schedule
        self._resting_orders = resting_orders
        self._rounding = rounding
        self._applied: Dict[Tuple[str, date], CorporateActionApplied] = {}

    # -- reading ---------------------------------------------------------

    @property
    def schedule(self) -> CorporateActionSchedule:
        return self._schedule

    @property
    def resting_order_policy(self) -> RestingOrderPolicy:
        return self._resting_orders

    @property
    def rounding(self) -> str:
        return self._rounding

    def applied(self) -> Tuple[CorporateActionApplied, ...]:
        """Everything this engine has applied, in the order it applied it."""
        return tuple(self._applied.values())

    def has_applied(self, action: CorporateAction) -> bool:
        """Whether this engine has already applied that exact event."""
        return action.key in self._applied

    def due(self, ts: datetime, *,
            tickers: Optional[Iterable[str]] = None,
            ) -> Tuple[CorporateAction, ...]:
        """Scheduled actions with ``ex_date <= ts.date()`` not yet applied.

        ``<=`` and not ``==``: a caller who advanced past an ex-date without
        driving the engine should still get the action, applied late and
        flagged as such, rather than have it silently skipped. Silently
        skipping is the failure this whole module exists to end.
        """
        wanted = None if tickers is None else frozenset(tickers)
        return tuple(a for a in self._schedule
                     if a.ex_date <= ts.date()
                     and a.key not in self._applied
                     and (wanted is None or a.ticker in wanted))

    # -- applying --------------------------------------------------------

    def apply_due(
        self,
        ts: datetime,
        *,
        account: SecuritiesAccount,
        book: Optional[OrderBookOfRecord] = None,
        phase: Optional[SessionPhase] = None,
        prices: Optional[Mapping[str, Decimal]] = None,
        venues: Optional[Mapping[str, Venue]] = None,
        ticks: Optional[Mapping[str, Decimal]] = None,
        order_ticks: Optional[Mapping[str, Decimal]] = None,
        bands: Optional[Mapping[str, Tuple[Decimal, Decimal]]] = None,
        lots: Optional[Mapping[str, int]] = None,
        take_up: Optional[bool] = None,
    ) -> Tuple[CorporateActionApplied, ...]:
        """Apply every action due at ``ts``, in ``(ex_date, ticker)`` order.

        The four mappings are per-ticker inputs the engine cannot resolve for
        itself, and all four are optional. ``prices`` supplies the base price
        P -- the prior close at HSX/HNX, the prior round-lot VWAP at UPCoM --
        without which the quantity and cash legs still apply and
        ``CorporateActionApplied.reference`` is ``None``. ``venues`` supplies
        the venue at ``ts`` and must come from a ``SymbolRouter``, never from
        a ticker-keyed cache (locked shape 1). ``ticks`` and ``lots`` come
        from ``rulebook.at(ts)``.

        ``take_up`` is **one decision for every rights issue due at this
        instant**, which is why it is not a mapping like the other four: it is
        a portfolio decision and not a per-ticker datum the engine could look
        up. It is passed straight through to :meth:`apply`, including its
        refusal to guess -- a caller with rights on two names on one session
        who wants to subscribe to one and lapse the other must drive
        :meth:`apply` per action rather than have this method invent a policy.
        """
        results: List[CorporateActionApplied] = []
        for action in self.due(ts):
            ticker = action.ticker
            results.append(self.apply(
                action, account=account, ts=ts, book=book, phase=phase,
                base_price=None if prices is None else prices.get(ticker),
                venue=None if venues is None else venues.get(ticker),
                tick=None if ticks is None else ticks.get(ticker),
                order_tick=(None if order_ticks is None
                            else order_ticks.get(ticker)),
                band=None if bands is None else bands.get(ticker),
                lot=None if lots is None else lots.get(ticker),
                take_up=take_up,
            ))
        return tuple(results)

    def apply(
        self,
        action: CorporateAction,
        *,
        account: SecuritiesAccount,
        ts: datetime,
        book: Optional[OrderBookOfRecord] = None,
        phase: Optional[SessionPhase] = None,
        base_price: Optional[Decimal] = None,
        venue: Optional[Venue] = None,
        tick: Optional[Decimal] = None,
        order_tick: Optional[Decimal] = None,
        band: Optional[Tuple[Decimal, Decimal]] = None,
        lot: Optional[int] = None,
        take_up: Optional[bool] = None,
    ) -> CorporateActionApplied:
        """Apply one event to the account, and to any order still live.

        ``tick`` rounds the ex-date **reference**; ``order_tick`` rounds a
        rescaled **limit price**; ``band`` is the ``(floor, ceiling)`` the
        exchange publishes for the ex-date. All three are per-ticker inputs
        the engine cannot resolve for itself, and the last two exist because
        ``RestingOrderPolicy.SCALE`` was measured writing a limit price off
        the quotation grid and below the published floor -- which then
        filled, because ``book.amend`` does not re-run admission. See
        :meth:`_scale`.

        **Who receives a cash dividend: the register on the record date, not
        the settlement state of the parcel.** The rule is
        ``ngay dang ky cuoi cung``, and under T+2 the record date is set one
        settlement cycle after the ex-date precisely so that a buyer who
        traded on the last cum-rights session -- whose trade is still
        unsettled on the ex-date itself -- is on the register when it is
        struck. So a parcel bought on the session before the ex-date and still
        sitting in ``Holding.unsettled`` **is entitled**, and the entitlement
        is computed on ``Holding.total``, not on ``Holding.settled``. Pricing
        it off settlement state would deny the dividend to exactly the buyer
        the T+2 cycle was designed to include, and would do it silently.

        The mirror holds and needs no special handling: a parcel sold before
        the ex-date has already left ``settled`` at the fill, so it draws
        nothing. This is why the engine must be driven at the **ex-date's
        open, before that session's fills**. A share bought *on* the ex-date
        is not entitled, and the only thing that keeps it out of the
        entitlement is that it is not in the holding yet. Driven late, the
        result is marked ``late=True`` rather than silently overstated.

        **A rights take-up is a purchase, and this method will not guess at
        one.** ``take_up`` has no default for an action carrying a rights leg:
        whether the holder subscribes, sells the right or lets it lapse is a
        portfolio decision (design section 3), and it is the only decision
        here that spends the account's cash. Stated ``True``, the shares and
        the payment move together in this one call --
        ``subscription_shares(action, holding) x subscription_price`` debited
        from settled cash -- so no caller can end up holding rights shares
        nobody paid for. Stated ``False``, neither moves and the lapse shows up
        honestly as a price adjustment with no matching quantity. The price leg
        is unaffected either way: the exchange adjusts the whole market's
        reference before anyone has subscribed.

        This module is exchange-side and the caller owns the portfolio, so
        moving cash here is a small impurity -- but it is the same impurity the
        gross cash leg already makes for a dividend, and the two legs of one
        event belong on the same side of that line. The alternative, reporting
        the outlay and trusting the caller to debit it, was rejected for one
        reason: it fails open. A caller who ignores the field gets a bigger
        position and unchanged cash, every invariant in the package still
        holds, and nothing downstream can detect it.

        The order of operations, and none of it is arbitrary:

        1. the subscription is **priced and funded before anything moves**.
           The entitlement is computed on the pre-event holding and tested
           against ``Cash.available``; an unaffordable take-up raises
           :class:`RightsSubscriptionUnfunded` with the account untouched,
           because a refusal that had already scaled the holding would be the
           same fabrication by another route. ``available`` and not
           ``settled_balance``: design section 7.0 owns the definition of
           spendable cash, and cash committed to a live buy order is already
           promised. The dividend leg of the *same* event does not fund the
           subscription -- this module credits it at the ex-date while the
           real payment lands weeks later, and letting that credit pay for the
           shares would build the simplification into a money movement;
        2. the holding and the cash leg, through
           ``HoldingsLedger.apply_corporate_action`` -- the additive Tier 1
           hook, used rather than retrofitted, so a split scales every parcel
           including the unsettled ones and their settlement instants survive;
        3. the cash credit, gross, and the subscription debit;
        4. the live orders. Last, because a reservation is not a holding and
           cannot change the entitlement, and because scaling a share
           reservation before the parcel it names has grown would briefly
           commit more than is settled.

        Args:
            base_price: P. Optional: without it no reference is computed and
                the quantity and cash legs still apply.
            venue: the venue at ``ts``, from a ``SymbolRouter``. Required with
                ``base_price``, because the currency unit and both
                no-adjustment carve-outs are per venue.
            tick: the quotation unit, for rounding the adjusted reference.
            lot: the round lot, used only on the ``SCALE`` branch.
            take_up: whether the rights entitlement is subscribed for.
                **Required for an action with a rights leg**; ignored, and
                needed by nothing, for every other kind.

        Raises:
            ValueError: if the event has already been applied, if ``ts`` is
                before the ex-date, if ``base_price`` is given without a
                ``venue``, or if the action carries a rights leg and
                ``take_up`` was not stated.
            RightsSubscriptionUnfunded: if the stated take-up costs more than
                the account has available. Nothing is applied.
            UnsourcedCorporateAction: see :func:`adjusted_reference`.
        """
        if action.key in self._applied:
            raise ValueError(
                f'{action} has already been applied by this engine; applying '
                f'it twice would compound the factor and pay the dividend '
                f'again')
        if ts.date() < action.ex_date:
            raise ValueError(
                f'cannot apply {action} at {ts.isoformat()}: the entitlement '
                f'is the holding at the ex-date\'s open and does not exist '
                f'before it')
        if base_price is not None and venue is None:
            raise ValueError(
                'a base price needs a venue: the currency unit that converts '
                'a VND cash leg into quote units is per venue (1,000 at the '
                'three cash venues), and so is each no-adjustment carve-out. '
                'Resolve it with SymbolRouter.venue(ticker, ts)')
        subscribed = self._resolve_take_up(action, take_up)

        reference: Optional[ReferenceAdjustment] = None
        if base_price is not None and venue is not None:
            reference = adjusted_reference(
                action, base_price, venue=venue, tick=tick,
                rounding=self._rounding, take_up=subscribed)

        factor = quantity_factor(action, take_up=subscribed)
        holdings = account.holdings_ledger
        before = holdings.holding(action.ticker)

        # Priced and funded before a single leg moves. See the docstring: a
        # refusal that had already scaled the holding fabricates exactly what
        # this check exists to prevent.
        rights_shares = (subscription_shares(action, before) if subscribed
                         else 0)
        outlay = Decimal(rights_shares) * action.subscription_price
        if outlay:
            available = account.cash().available
            if outlay > available:
                raise RightsSubscriptionUnfunded(
                    f'{action}: taking up {rights_shares} rights shares at '
                    f'{action.subscription_price} VND costs {outlay} VND and '
                    f'the account has {available} available. Nothing has been '
                    f'applied. A rights issue is not free money -- an account '
                    f'that cannot pay for the shares has not subscribed -- so '
                    f'either fund the account before the ex-date or apply the '
                    f'same action with take_up=False and let the rights '
                    f'lapse. Partial take-up is NOT modelled: nothing sourced '
                    f'says how a partly funded subscription is allotted')

        cash_leg, tranches = holdings.apply_corporate_action(
            action.ticker, factor, action.cash_per_share, ts)
        after = holdings.holding(action.ticker)

        # Summed over the two populations rather than zipped pairwise:
        # ``Holding.unsettled`` is sorted by settlement instant while the
        # ledger's own list is in acquisition order, so a pairwise walk can
        # line up the wrong parcels. sum(q_i)*f - sum(floor(q_i*f)) is the
        # same per-parcel residue and is order-independent.
        residue = (
            (Decimal(before.settled) * factor - Decimal(after.settled))
            + (Decimal(before.unsettled_quantity) * factor
               - Decimal(sum(t.quantity for t in tranches)))
        )

        if cash_leg:
            account.cash_ledger.credit(
                cash_leg, ts,
                f'corporate action {action} cash leg, GROSS of the 5% '
                f'dividend withholding, which is a charge row the rulebook '
                f'does not carry')
        if outlay:
            account.cash_ledger.debit(
                outlay, ts,
                f'corporate action {action} rights subscription: '
                f'{rights_shares} shares at {action.subscription_price} VND, '
                f'taken up at the caller\'s instruction. The shares are '
                f'credited by the same call; neither leg exists without the '
                f'other')

        outcomes: Tuple[RestingOrderOutcome, ...] = ()
        if book is not None:
            outcomes = self._adjust_resting(
                book, account, action, factor, reference, ts, phase, lot,
                tick, order_tick=order_tick, band=band)

        applied = CorporateActionApplied(
            action=action, ts=ts, quantity_factor=factor,
            cash_per_share=action.cash_per_share, cash_leg=cash_leg,
            holding_before=before, holding_after=after,
            tranches_after=tranches, fractional_residue=residue,
            resting_orders=outcomes, reference=reference,
            late=ts.date() > action.ex_date, take_up=subscribed,
            subscription_shares=rights_shares, subscription_outlay=outlay)
        self._applied[action.key] = applied
        return applied

    @staticmethod
    def _resolve_take_up(action: CorporateAction,
                         take_up: Optional[bool]) -> bool:
        """Turn a three-state ``take_up`` into a decision, or refuse to.

        ``None`` means *not stated*, and for an action with a rights leg that
        is the one thing this engine will not resolve for itself. Both arms
        are defensible and they differ by real money, so choosing either as a
        default would be the module deciding a portfolio question -- and the
        expensive default is the one that reads as harmless, since crediting
        the shares without the payment leaves every invariant intact.

        For every other kind of action the flag reaches nothing:
        :func:`quantity_factor` ignores it without a rights ratio, and there
        is no subscription to pay. Demanding a decision there would be
        ceremony, and ceremony is what teaches a caller to pass the flag
        without reading it.
        """
        if not action.rights_ratio:
            return bool(take_up)
        if take_up is None:
            raise ValueError(
                f'{action} carries a rights leg and take_up was not stated. '
                f'Pass take_up=True to subscribe -- the engine will credit '
                f'the shares AND debit '
                f'{action.subscription_price} VND per share for them in the '
                f'same call -- or take_up=False to let the rights lapse, '
                f'which leaves the quantity alone while the reference still '
                f'adjusts. There is no default: whether a right is exercised, '
                f'sold or lapsed is a portfolio decision (design section 3), '
                f'it is the only leg of a corporate action that COSTS money, '
                f'and a deep-discount rights issue -- the ordinary Vietnamese '
                f'case -- is exactly where guessing wrong is most expensive')
        return bool(take_up)

    def _adjust_resting(
        self,
        book: OrderBookOfRecord,
        account: SecuritiesAccount,
        action: CorporateAction,
        factor: Decimal,
        reference: Optional[ReferenceAdjustment],
        ts: datetime,
        phase: Optional[SessionPhase],
        lot: Optional[int],
        tick: Optional[Decimal],
        order_tick: Optional[Decimal] = None,
        band: Optional[Tuple[Decimal, Decimal]] = None,
    ) -> Tuple[RestingOrderOutcome, ...]:
        """Cancel or scale every live order on the ticker. The open question.

        See :class:`RestingOrderPolicy`: the rulebook does not settle this,
        and it does not settle it because rulebook 2.3 makes the situation
        unreachable -- no Vietnamese order type survives a session close.
        ``CANCEL`` is the default and is what the day-order rule implies.
        """
        outcomes: List[RestingOrderOutcome] = []
        for record in book.live(ticker=action.ticker):
            if self._resting_orders is RestingOrderPolicy.CANCEL:
                outcomes.append(self._cancel(book, record, ts, phase,
                                             'RestingOrderPolicy.CANCEL'))
                continue
            outcomes.append(self._scale(book, account, record, factor,
                                        reference, ts, phase, lot, tick,
                                        order_tick=order_tick, band=band))
        return tuple(outcomes)

    @staticmethod
    def _cancel(book: OrderBookOfRecord, record: OrderRecord, ts: datetime,
                phase: Optional[SessionPhase],
                reason: str) -> RestingOrderOutcome:
        """Terminate one order. The reservation is released by the book's own
        terminal hook, exactly as on every other terminal edge -- which is why
        this branch cannot leak and the scaling branch has to re-take by hand.

        A refusal from the book (a locked auction phase, say) is reported
        rather than swallowed: the order survives with its old quantity
        against a rescaled holding, and a caller must know.
        """
        before = record.remaining_quantity
        result = book.cancel(record.order_id, ts, phase=phase)
        refused = not isinstance(result, OrderRecord)
        return RestingOrderOutcome(
            order_id=record.order_id, ticker=record.order.ticker,
            side=record.order.side, policy=RestingOrderPolicy.CANCEL,
            quantity_before=before,
            quantity_after=before if refused else 0,
            limit_price_before=record.order.limit_price,
            limit_price_after=record.order.limit_price if refused else None,
            reason=(f'REFUSED by the order book, order left unadjusted: '
                    f'{getattr(result, "detail", result)}') if refused
                   else reason)

    def _scale(
        self,
        book: OrderBookOfRecord,
        account: SecuritiesAccount,
        record: OrderRecord,
        factor: Decimal,
        reference: Optional[ReferenceAdjustment],
        ts: datetime,
        phase: Optional[SessionPhase],
        lot: Optional[int],
        tick: Optional[Decimal],
        order_tick: Optional[Decimal] = None,
        band: Optional[Tuple[Decimal, Decimal]] = None,
    ) -> RestingOrderOutcome:
        """Scale one order's quantity by the factor and its price by the ratio.

        The price leg uses ``ReferenceAdjustment.ratio``, which is the one
        ratio with a gazetted precedent for adjusting a contractual price
        across a corporate action: QD 22/2026 Dieu 36 sets a covered
        warrant's new strike to ``old strike x (adjusted underlying reference
        / unadjusted underlying reference)``. Without a reference the price is
        left alone and only the quantity moves, which is reported.

        Falls back to :meth:`_cancel` when the scaled order would be
        degenerate -- nothing left after scaling, or nothing left after the
        round lot is enforced on it -- because an order with no remainder is
        not an order and one off the lot can never fill.

        **The factor multiplies the remainder, and the remainder only.** This
        is the whole of the unit discipline on this branch and it is easy to
        get backwards. ``original`` is ``filled + remaining``; ``filled``
        records what actually traded, in *pre-event* shares, and the event does
        not reach back and rewrite it. So the event scales ``remaining``, and
        ``original`` is whatever the two then sum to: 400 filled of 1,000,
        doubled, is 400 filled, 1,200 remaining and an original of 1,600.

        Scaling ``original`` instead and taking ``remaining`` as the leftover
        mixes the two units -- it subtracts a pre-event ``filled`` from a
        post-event total -- and inflates the remainder by exactly
        ``filled x (factor - 1)`` shares. That is not a rounding-scale error:
        on a 10->1 consolidation it goes *negative* for any order more than
        ``1/m`` filled, so an ordinary 20%-filled order is cancelled as
        "nothing left" while 80% of it is still working. On a split it commits
        the account to shares it never bought, and the cash reservation
        re-taken below grows with it.

        The already-filled shares are not lost by this. They grow in the
        **holding**, where the same factor reaches them; growing them here as
        well would count them twice. Nothing sourced settles the arrangement --
        see :class:`RestingOrderPolicy` -- but only one arrangement keeps
        ``filled + remaining == original`` (section 12 invariant 1) without
        rewriting a fill.

        **The reservation is released and re-taken here**, since the book's
        ``amend`` does not touch encumbrances (an amendment that changed a
        reservation would have to re-run admission, which is ``exchange.py``'s
        composition, not the book's). The re-take preserves the *value* of a
        cash reservation and the *quantity* of a share reservation across the
        adjustment. What it does not preserve is the accept-time
        ``original_amount``: the re-taken reservation's history restarts at the
        adjustment, and the pre-event numbers live on
        :class:`CorporateActionApplied` instead.

        **And the record is rewritten from the ledger in the same breath**,
        via ``OrderBookOfRecord.set_encumbrances`` -- which is what actually
        makes section 12 invariant 4 hold. Moving the ledger alone left the
        ``OrderRecord`` reporting its accept-time reservation for the rest of
        a scaled order's life; measured on HPG 2021-05-31 with the order still
        ``RESTING``, the record said 46,012,420 of committed cash where the
        ledger said 43,978,091.
        """
        before_qty = record.remaining_quantity
        before_price = record.order.limit_price
        remaining_after = int(
            (Decimal(before_qty) * factor).to_integral_value(ROUND_FLOOR))
        lot_enforced = bool(lot and lot > 1)
        if lot_enforced:
            # The lot is enforced on the REMAINDER: that is the quantity that
            # has to match, and an order whose remainder is off the lot can
            # never fill however tidy its headline number is.
            remaining_after = (remaining_after // lot) * lot
        scaled_original = record.filled_quantity + remaining_after
        if remaining_after <= 0:
            return replace(
                self._cancel(book, record, ts, phase,
                             'RestingOrderPolicy.SCALE'),
                policy=RestingOrderPolicy.SCALE,
                reason=f'scaling the {before_qty} still working by {factor} '
                       f'leaves {remaining_after}'
                       + (f' once the {lot}-share lot is enforced'
                          if lot_enforced else '')
                       + f', which is not an order; cancelled instead')

        # The scaled LIMIT price, which is a different rounding from the
        # scaled REFERENCE and now takes a different parameter. F-10, in the
        # corporate-charges scenario's own words: "one tick parameter, two
        # incompatible roundings ... the two roundings want separate
        # parameters". ``tick`` is the reference's (and on a HOSE ex-date it
        # must be ``None``, per F-1); ``order_tick`` is the order's, and a
        # limit price must be on the grid or it can never match.
        new_price = before_price
        if before_price is not None and reference is not None:
            new_price = round_to_quotation_unit(
                before_price * reference.ratio, order_tick,
                rounding=self._rounding)

        # **A price this branch cannot show to be admissible is not written.**
        #
        # Measured: a VIB sell resting at the published ceiling of 53.40 was
        # scaled to 38.14285714285714285714285714 -- 26 significant digits,
        # off the 0.05 grid, and 8.31 BELOW the published floor of 46.45 --
        # and the fill pass then matched it, levying real charges on a print
        # the exchange could not have made. ``book.amend`` deliberately does
        # not re-run admission (its own docstring says so: admission is
        # ``exchange.py``'s composition, not the book's), so nothing
        # downstream re-checks the band, the tick or the lot.
        #
        # The engine cannot resolve a band for itself -- it is a per-ticker
        # input, like ``prices`` and ``ticks`` -- so it refuses on the ones it
        # was given and *says* which ones it was not. Cancelling is the same
        # fallback this branch already takes for a degenerate quantity, and
        # ``CANCEL`` is the policy default in any case.
        if new_price is not None and new_price != before_price:
            outside = (band is not None
                       and not (band[0] <= new_price <= band[1]))
            if outside:
                return replace(
                    self._cancel(book, record, ts, phase,
                                 'RestingOrderPolicy.SCALE'),
                    policy=RestingOrderPolicy.SCALE,
                    limit_price_after=None,
                    reason=f'the scaled limit {new_price} falls outside the '
                           f'ex-date band [{band[0]}, {band[1]}]; an order '
                           f'the exchange would refuse is cancelled rather '
                           f'than rested at a price that cannot legally '
                           f'match')

        live = account.encumbrances.of(record.order_id)
        amended = book.amend(
            record.order_id, ts, quantity=scaled_original,
            limit_price=None if new_price == before_price else new_price,
            phase=phase, priority_preserving=False)
        if not isinstance(amended, Amended):
            return replace(
                self._cancel(book, record, ts, phase,
                             'RestingOrderPolicy.SCALE'),
                policy=RestingOrderPolicy.SCALE,
                reason=f'the order book refused the amendment '
                       f'({getattr(amended, "detail", amended)}); cancelled '
                       f'rather than left against a rescaled holding')

        qty_ratio = Decimal(remaining_after) / Decimal(before_qty)
        price_ratio = (Decimal('1') if before_price in (None, 0)
                       or new_price is None
                       else new_price / before_price)
        account.encumbrances.release(record.order_id, ts)
        for enc in live:
            if enc.resource is ResourceKind.SHARES:
                account.encumbrances.take(
                    record.order_id, enc.pool, enc.resource, ts,
                    quantity=int(Decimal(enc.quantity) * qty_ratio),
                    ticker=enc.ticker, order_quantity=remaining_after)
            else:
                # **Whole dong.** ``qty_ratio`` and ``price_ratio`` are exact
                # Decimal quotients, so the product is a repeating fraction
                # far more often than not, and the re-taken reservation used
                # to carry it: a measured run reported ``committed_cash
                # 43978090.45206159960258320914`` and an available balance
                # with 20 decimal places, on a currency with no subunit.
                # ``encumbrance_matches`` held throughout because both sides
                # were equally fractional -- the identity compares the
                # reservation to itself.
                #
                # Rounded UP, and the direction is deliberate: a reservation
                # is a promise that the money is there, so the error must
                # never be in the direction of under-reserving. At most one
                # dong is over-committed per leg, and it is released on the
                # same terminal edge as the rest.
                value_ratio = qty_ratio * price_ratio
                account.encumbrances.take(
                    record.order_id, enc.pool, enc.resource, ts,
                    amount=_whole_dong(enc.amount * value_ratio),
                    ticker=enc.ticker,
                    estimated_charges=_whole_dong(
                        enc.estimated_charges * value_ratio),
                    order_quantity=remaining_after)

        # **The record is rewritten from the ledger, in the same breath.**
        #
        # ``book.amend`` does not touch encumbrances, so the release/re-take
        # above left the ``OrderRecord`` still carrying its accept-time
        # reservation while the ledger carried the scaled one -- and
        # ``OrderRecord.encumbered_cash`` exists precisely so section 12
        # invariant 4 can be summed over live orders. Measured on HPG
        # 2021-05-31 with the order still RESTING: the record said 46,012,420
        # of committed cash where the ledger said 43,978,091, 2,034,329 apart,
        # for as long as the scaled order rested. The share leg diverged the
        # other way -- a record saying 1,000 committed against a ledger saying
        # 2,000 -- which *under*-reports what the account has promised, so a
        # caller summing records would think it could sell the parcel twice.
        #
        # :meth:`OrderBookOfRecord.set_encumbrances` is the method that exists
        # for exactly this, and the partial-fill path in ``exchange.py`` was
        # its only caller. The ledger is read back rather than the tuple
        # rebuilt here, so the record is a *copy* of the ledger and not a
        # second opinion: the arithmetic happens in one place and the record
        # cannot drift from it by a rounding.
        book.set_encumbrances(record.order_id,
                              account.encumbrances.of(record.order_id))

        # An admissibility guard this branch could not run is NAMED, never
        # silently skipped. The three are independent, and a scaled order that
        # passed none of them is one the exchange might refuse on any of the
        # three grounds -- which is what produced a fill 8.31 below the
        # published floor on a price with 26 significant digits.
        unchecked: List[str] = []
        if not lot_enforced:
            unchecked.append(
                'no round lot supplied: a scaled quantity off the lot can '
                'never fill (ROUND_LOT)')
        if new_price != before_price and order_tick is None:
            unchecked.append(
                'no order tick supplied: a limit price off the quotation grid '
                'can never match')
        if new_price != before_price and band is None:
            unchecked.append(
                'no ex-date band supplied: a limit price outside it would be '
                'refused (BAND_LIMIT), and book.amend does not re-run '
                'admission')
        return RestingOrderOutcome(
            order_id=record.order_id, ticker=record.order.ticker,
            side=record.order.side, policy=RestingOrderPolicy.SCALE,
            quantity_before=before_qty, quantity_after=remaining_after,
            limit_price_before=before_price, limit_price_after=new_price,
            lot_enforced=lot_enforced,
            reason=None if not unchecked else
            'this branch did not check: ' + '; '.join(unchecked))


# --------------------------------------------------------------------------
# The audit -- reporting a crossing instead of returning a wrong number
# --------------------------------------------------------------------------

class SessionView(Protocol):
    """The four public methods the audit needs from a session.

    A ``Protocol`` and not ``ExchangeSession`` for two reasons. The engine
    must not import ``exchange.py`` -- ``exchange.py`` composes this package
    and a back-edge would make the dependency graph cyclic, and the module
    docstring's "the dependency graph flows downward only" is a claim the
    imports have to keep. And the audit reads **only public API**: it never
    reaches into ``_securities`` or ``_book``, so nothing here can drift when
    the session's internals change.

    ``holdings(ticker)`` on an unheld ticker returns a zero
    :class:`~plutus.market.session.types.Holding` rather than raising, which
    is what lets the audit sweep the schedule's tickers without first knowing
    which of them the account touched.
    """

    def now(self) -> datetime: ...
    def provenance(self): ...
    def orders(self, **kw) -> Sequence[OrderRecord]: ...
    def holdings(self, ticker: str) -> Holding: ...


@dataclass(frozen=True)
class UnhandledCorporateAction:
    """One action a run crossed and nothing applied, with its exposure.

    ``held_quantity`` and ``order_ids`` are why this matters and are the
    difference between a warning and noise: a schedule entry for a ticker the
    run never touched is not a defect in the run, and reporting it as one
    would train the caller to ignore the report. Only rows where the account
    was actually exposed reach :attr:`CorporateActionReport.unhandled`.
    """

    action: CorporateAction
    held_quantity: int
    order_ids: Tuple[OrderId, ...]
    reason: str

    @property
    def ticker(self) -> str:
        return self.action.ticker


@dataclass(frozen=True)
class CorporateActionReport:
    """What a run crossed, what was applied, and what was not.

    The mechanism design section 15 asks for in one sentence -- "an omission
    that is *declared* is not a defect; a silent one is" -- for the one
    limitation that survived Tier 1. It sits beside
    :class:`~plutus.market.session.types.IndeterminateReport` in spirit: both
    are bounds on how much of a run is not to be trusted, reported rather than
    hidden, and neither is a result.

    ``exposed_tickers`` is the universe the sweep ran over, so a caller can
    tell "clean because nothing happened" from "clean because we looked at
    nothing".
    """

    period_start: date
    period_end: date
    crossed: Tuple[CorporateAction, ...]
    applied: Tuple[CorporateAction, ...]
    unhandled: Tuple[UnhandledCorporateAction, ...]
    exposed_tickers: Tuple[str, ...]

    @property
    def is_clean(self) -> bool:
        """True when every action the run was exposed to was applied."""
        return not self.unhandled

    @property
    def affected_tickers(self) -> Tuple[str, ...]:
        """The instruments whose numbers are wrong, in ticker order.

        The precise scope of the damage: design section 15 item 5 says a run
        spanning an ex-date "is wrong for that instrument", not for the run.
        A caller can drop these instruments and keep the rest.
        """
        return tuple(sorted({u.ticker for u in self.unhandled}))

    def raise_if_unhandled(self) -> 'CorporateActionReport':
        """Raise when the run is not clean; return ``self`` when it is.

        Opt-in, so the default posture stays "report, do not fail". Returns
        ``self`` so it chains onto a call that already produced the report.

        Raises:
            UnhandledCorporateActionError: naming every affected instrument.
        """
        if self.is_clean:
            return self
        rows = '; '.join(
            f'{u.action} (held {u.held_quantity}, '
            f'{len(u.order_ids)} live order(s))' for u in self.unhandled)
        raise UnhandledCorporateActionError(
            f'this run crossed {len(self.unhandled)} corporate action(s) that '
            f'nothing applied, between {self.period_start.isoformat()} and '
            f'{self.period_end.isoformat()}: {rows}. Every number for '
            f'{", ".join(self.affected_tickers)} is wrong across the ex-date '
            f'-- the reference price, the band computed from it, and the '
            f'holding quantity. Drive a CorporateActionEngine over the '
            f'schedule, or drop these instruments from the result')

    def __str__(self) -> str:
        if self.is_clean:
            return (f'corporate actions {self.period_start.isoformat()}..'
                    f'{self.period_end.isoformat()}: {len(self.crossed)} '
                    f'crossed, {len(self.applied)} applied, none unhandled '
                    f'over {len(self.exposed_tickers)} ticker(s)')
        return (f'corporate actions {self.period_start.isoformat()}..'
                f'{self.period_end.isoformat()}: {len(self.unhandled)} '
                f'UNHANDLED on {", ".join(self.affected_tickers)}')


class CorporateActionAudit:
    """Answers "did this run cross a corporate action nothing applied?".

    The reporting half of the module, and the half a caller who is *not*
    modelling corporate actions still needs. Attach it to a schedule and a
    session and read :meth:`report`; the result names the instruments whose
    numbers are wrong rather than letting the run return them silently.

    Reads the session through :class:`SessionView` -- four public methods, no
    private attributes -- so it works against ``ExchangeSession`` and against
    any stand-in a test builds.
    """

    def __init__(self, schedule: CorporateActionSchedule,
                 engine: Optional[CorporateActionEngine] = None) -> None:
        """
        Args:
            engine: the engine that has been applying actions, if any. Without
                one every crossing the account was exposed to is unhandled,
                which is the correct verdict for a run that never modelled
                corporate actions at all.
        """
        self._schedule = schedule
        self._engine = engine

    def report(
        self,
        session: SessionView,
        *,
        through: Optional[date] = None,
        tickers: Iterable[str] = (),
    ) -> CorporateActionReport:
        """Everything crossed between the run's start and ``through``.

        ``through`` defaults to ``session.now().date()`` -- the run *so far*,
        not the configured period. A caller mid-run gets what has already gone
        wrong; a caller who wants the forward warning passes
        ``session.provenance().period_end``.

        The exposure sweep, in the order it decides:

        1. every ticker with a live or historical order in the session, from
           ``session.orders()`` -- an order is exposure even if it never
           filled, because it was priced against a reference the ex-date moved;
        2. every ticker in the schedule the account still holds, from
           ``session.holdings(ticker).total``;
        3. anything the caller names in ``tickers``, for exposure the session
           cannot see -- an instrument held at the start of the run and sold
           before the report, say.

        An action on a ticker outside that union is *crossed* but not
        *unhandled*: the run was never exposed to it, and reporting it would
        train the caller to ignore the report.
        """
        end = session.now().date() if through is None else through
        start = session.provenance().period_start
        if end < start:
            end = start

        order_tickers = {r.order.ticker for r in session.orders()}
        exposed = set(order_tickers) | set(tickers)
        for ticker in self._schedule.tickers():
            if session.holdings(ticker).total > 0:
                exposed.add(ticker)

        crossed = self._schedule.between(start, end)
        applied_keys = ({a.action.key for a in self._engine.applied()}
                        if self._engine is not None else set())

        unhandled: List[UnhandledCorporateAction] = []
        for action in crossed:
            if action.key in applied_keys or action.ticker not in exposed:
                continue
            held = session.holdings(action.ticker)
            ids = tuple(r.order_id for r in session.orders(
                ticker=action.ticker))
            unhandled.append(UnhandledCorporateAction(
                action=action, held_quantity=held.total, order_ids=ids,
                reason='crossed with exposure and never applied: the '
                       'reference price, the band derived from it and the '
                       'holding quantity are all wrong for this instrument '
                       'from the ex-date onward'))

        return CorporateActionReport(
            period_start=start, period_end=end, crossed=crossed,
            applied=tuple(a for a in crossed if a.key in applied_keys),
            unhandled=tuple(unhandled),
            exposed_tickers=tuple(sorted(exposed)))
