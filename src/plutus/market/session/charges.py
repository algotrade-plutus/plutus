"""The charge table: fees and taxes, per venue, dated, itemised.

Design section 6.1 requires **one generic table, not a pair of constants**,
and the requirement comes from the rules rather than from taste. Three rows no
pair of constants can hold:

* the **0.1% personal income tax** on an equity transfer is *sell-side only*
  and withheld at source, so a sale credits cash net -- without it every sale
  is wrong by more than most commissions (rulebook 8.1, 12.3);
* the **VSD position-management fee** accrued per open contract per account
  per *day* until 2021-12-31, then the charge changed shape into a per-matched
  contract clearing fee on 2022-01-01 (rulebook 12.5);
* **custody** is monthly per security, so a holding that never trades still
  costs money (rulebook 12.5).

This module is the arithmetic. The *rows* live in the dated rulebook
(``rulebook.RuleName.CHARGE``, resolved by ``RuleSet.charges``) for anything
levied by the state, an exchange or the depository, and on
:class:`~plutus.market.session.types.BrokerProfile` for anything commercial.
That split is structural, not stylistic: an exchange row is gazetted, dated,
identical for everyone and carries a :class:`RuleCitation`; a broker row is
per-firm, unsourced, and every default here says so.

The resolution key is ``(venue, charge class, side, date)``
-----------------------------------------------------------
:func:`schedule` is the one place all four axes are applied. ``venue`` and
``charge class`` filter ``RuleSet.charges``; ``date`` is the instant the
``RuleSet`` was resolved at (a venue is ``(ticker, ts)``, so a charge is
``(venue, class, side, ts)`` and never a load-time constant); ``side`` is
applied last by :meth:`ChargeRule.applies`, because it is the axis that
decides whether the biggest charge on the table fires at all.

Four bases, and why the fourth exists
-------------------------------------
:class:`ChargeBasis` names what a rate is actually applied to:

``TRADE_VALUE``
    A cash venue quotes **thousands of dong** (``CURRENCY_UNIT == 1000``), so
    an HSX price of 25.5 is 25,500 VND. :func:`trade_value` is the only place
    that conversion happens.
``NOTIONAL``
    HNXDS quotes **index points** against a contract multiplier, so
    ``CURRENCY_UNIT['HNXDS'] == 1`` is meaningless as a multiplier (rulebook
    12.1). ``notional = points x multiplier x contracts``.
``QUANTITY``
    Per contract or per unit -- the exchange's 2,700d per matched contract,
    VSDC's 2,550d per novated contract, custody's 0.27d per unit.
``MARGINED_VALUE``
    **The derivatives personal income tax, and the reason this is a table.**
    Rulebook 8.1 and 12.3 give the published formula verbatim::

        PIT = 0.1% x [settlement price x multiplier x contracts
                      x VSDC published INITIAL MARGIN RATIO / 2]

    equivalently **0.05% of margined value**, charged per matched order on
    **both** legs and again at contract maturity. The base is *not* full
    notional -- at a 17% ratio it is 8.5% of it -- so a model that taxes
    notional over-charges a derivatives round trip by about 11.8x.

    The consequence the rulebook states in bold: the base is **linear in the
    VSD initial margin ratio**, so "one dated VSD series must feed both
    ``margin.py`` and the tax model, or the paper carries two mutually
    inconsistent margin ratios". This module therefore never carries a ratio
    of its own. It reads :meth:`RuleSet.initial_margin_rate`, which delegates
    to :func:`plutus.market.margin.vsd_initial_margin` -- the same call
    ``deposit.py`` makes for the margin requirement -- and
    :func:`levy` *cross-checks* the two ways of writing the charge and raises
    if they disagree. Drift is refused rather than reported.

The tier variable is the day's total, not the order's
----------------------------------------------------
Rulebook 8.3 and 12.7: retail commission tiers on "Tong gia tri giao dich /
ngay / tai khoan" -- the day's total transaction value per account -- so
**the correct rate is not knowable at fill time**, which the rulebook calls
"the single most useful implementation finding in the fee domain". Hence
:class:`CommissionSchedule` is ``DebitedAt.DAILY`` and :func:`assess_daily`
exists; :func:`assess` deliberately does not levy it. Tiers are also **not
assumed monotone**: SSI's real online schedule runs 0.25% / 0.30% / 0.25%.

Declared, not silently chosen
-----------------------------
* **Rounding is UNVERIFIED for every charge.** No Vietnamese source states a
  rounding rule for any fee or tax (rulebook 12.1). Whole dong, half up, is a
  modelling choice and any result sensitive to it must say so.
* **Every broker number is unsourced.** See
  :attr:`CommissionSchedule.PROVENANCE`, the commercial counterpart of
  :attr:`plutus.market.broker.BrokerTerms.PROVENANCE`.
* **VAT is a per-charge flag, default off.** State-set prices were VAT-exempt
  to 2025-04-28 and VAT-exclusive "(neu co)" from 2025-04-29, yet brokers
  demonstrably billed VSDC derivatives charges grossed up 10% during the
  exemption (rulebook 8.1, 12.1). The conflict is carried, not resolved.

**Orchestrator action.** ``types.ChargeBase`` has no ``MARGINED_VALUE``
member, and ``types.py`` is outside this task's ownership, so the projected
:class:`~plutus.market.session.types.Charge` reports the rulebook row's own
base (``TRADE_VALUE`` against notional) while :class:`LeviedCharge` carries
the statutory restatement (``MARGINED_VALUE`` against the margined base). The
two produce the same dong -- :func:`levy` enforces it -- but the label on the
projected charge is the rulebook's phrasing, not the statute's. Adding
``ChargeBase.MARGINED_VALUE`` and a ``basis`` field to ``Charge`` collapses
the two and is the named follow-up. It is recorded here rather than papered
over by mislabelling ``base_value``.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import (TYPE_CHECKING, Dict, FrozenSet, List, Mapping, Optional,
                    Sequence, Tuple)

from plutus.core.constant import VietnamMarketConstant
from plutus.core.order import Side
from plutus.market.session.types import (BrokerProfile, Charge, ChargeBase,
                                         ChargeClass, ChargeRule, ChargeSide,
                                         Confidence, DebitedAt, FillId,
                                         LeviedBy, OrderId, Pool, RuleCitation,
                                         Venue, pool_for_venue)

if TYPE_CHECKING:  # pragma: no cover - import-time cycle avoidance
    # This module is below ``ledgers.py``: ``ledgers`` imports it, never the
    # other way round, which is what lets ``trade_value`` live here with the
    # other money bases instead of in the account. ``RuleSet`` is taken as a
    # type only, exactly as ``ledgers.py`` does, so ``charges.py`` stays
    # importable on its own. At runtime the only things it asks of a RuleSet
    # are ``charges(venue, cls_)`` and ``initial_margin_rate(code)``.
    from plutus.market.session.rulebook import RuleSet

__all__ = [
    'ChargeBasis',
    'ChargeContext',
    'CommissionSchedule',
    'CommissionTier',
    'DERIVATIVES_PIT_CHARGE_ID',
    'DERIVATIVES_PIT_CITATION',
    'DERIVATIVES_PIT_RATE',
    'DailyTurnover',
    'FILL_BASES',
    'LeviedCharge',
    'TierVariable',
    'assess',
    'assess_at_maturity',
    'assess_daily',
    'basis_for',
    'basis_value',
    'charge_amount',
    'derivatives_notional',
    'estimate',
    'levy',
    'margined_value',
    'schedule',
    'to_dong',
    'trade_value',
    'vat_on',
]


# --------------------------------------------------------------------------
# Money: the conversions a charge is applied to
# --------------------------------------------------------------------------

#: One dong. Every charge is quantised to this; see the module docstring for
#: why that is a declared modelling choice rather than a sourced rule.
_DONG = Decimal('1')

_ZERO = Decimal('0')


def to_dong(amount: Decimal) -> Decimal:
    """Round a charge to whole dong, half up.

    **UNVERIFIED and a modelling choice.** Rulebook 12.1: "No source states a
    rounding rule for any fee or tax amount. Round to whole dong and record it
    as a modelling choice." Half-up rather than banker's rounding only because
    it is the convention a reader assumes; nothing supports either.
    """
    return amount.quantize(_DONG, rounding=ROUND_HALF_UP)


def trade_value(venue: Venue, quantity: int, price: Decimal) -> Decimal:
    """The VND value of a cash-venue trade at ``price``.

    The corpus and the exchanges quote the three cash venues in **thousands of
    dong** (``CURRENCY_UNIT[HSX/HNX/UPCOM] == 1000``), so an HSX price of 25.5
    is 25,500 VND and a 1,000-share trade moves 25,500,000 VND. Every cash
    movement goes through here, because a missing factor of 1,000 is invisible
    in a ratio and fatal in a balance.

    Raises:
        ValueError: on ``HNXDS``. ``CURRENCY_UNIT['HNXDS'] == 1`` is
            meaningless as a multiplier (rulebook 12.1) -- index futures quote
            points and apply a 100,000 VND contract multiplier, and
            government-bond futures quote VND on a 100,000 face -- so one
            conversion cannot serve both. :func:`derivatives_notional` is the
            other one, and it takes the multiplier explicitly.
    """
    if venue is Venue.HNXDS:
        raise ValueError(
            'trade_value is the cash-venue conversion; HNXDS notional is '
            'index points x the contract multiplier and belongs in '
            'derivatives_notional. CURRENCY_UNIT["HNXDS"] = 1 is not a '
            'multiplier.'
        )
    if quantity < 0:
        raise ValueError(f'quantity must not be negative, got {quantity}')
    unit = Decimal(VietnamMarketConstant.CURRENCY_UNIT[venue.value])
    return Decimal(quantity) * price * unit


def derivatives_notional(quantity: int, price: Decimal,
                         multiplier: Decimal) -> Decimal:
    """``contracts x price x multiplier`` -- the futures cash conversion.

    Separate from :func:`trade_value` because the unit differs by product and
    not merely by venue (rulebook 12.1): VN30F quotes index points against a
    100,000 VND multiplier, while government-bond futures quote VND on a
    100,000 VND face. The multiplier is therefore a parameter and never read
    off the venue.

    This is the *notional*, which is **not** the derivatives tax base -- see
    :func:`margined_value`.
    """
    if quantity < 0:
        raise ValueError(f'quantity must not be negative, got {quantity}')
    return Decimal(quantity) * price * multiplier


def margined_value(quantity: int, price: Decimal, multiplier: Decimal,
                   initial_margin_rate: Decimal) -> Decimal:
    """``notional x IM ratio / 2`` -- the published derivatives tax base.

    Rulebook 8.1, quoting Cong van 11133/BTC-CST (2017-08-21) and reproduced
    at circular level by TT 87/2026/TT-BTC Dieu 5.1::

        gia chuyen nhuong tung lan =
            (Gia thanh toan HDTL x He so nhan hop dong
             x So luong hop dong x Ty le ky quy ban dau) / 2

    The ``/ 2`` is in the source and is not a modelling choice.

    ``initial_margin_rate`` must come from the one dated VSD series --
    :meth:`RuleSet.initial_margin_rate`, which delegates to
    :func:`plutus.market.margin.vsd_initial_margin`. This function does not
    look it up, so no second copy of the series can start here.

    Raises:
        ValueError: on a non-positive margin ratio. Zero would make the tax
            vanish and a negative one would refund it; neither is a value the
            published series takes, and defaulting past it would hide exactly
            the drift this module exists to prevent.
    """
    if initial_margin_rate <= _ZERO:
        raise ValueError(
            f'initial margin ratio must be positive, got '
            f'{initial_margin_rate}: the derivatives tax base is linear in '
            f'it, so a zero or negative ratio silently deletes the tax. The '
            f'published series is 10% from 2017-08-10, 13% from 2018-07-18 '
            f'and 17% from 2022-12-15.'
        )
    return (derivatives_notional(quantity, price, multiplier)
            * initial_margin_rate / Decimal('2'))


# --------------------------------------------------------------------------
# Bases
# --------------------------------------------------------------------------

class ChargeBasis(str, Enum):
    """What a rate or amount is *actually* applied to.

    A refinement of :class:`~plutus.market.session.types.ChargeBase`, which
    records the row's shape as the rulebook words it. Two rows share
    ``ChargeBase.TRADE_VALUE`` and do not share a basis: the exchange trading
    service price is a fraction of the cash trade value on HSX and of the
    futures notional on HNXDS, and the derivatives transfer tax is a fraction
    of neither -- it is a fraction of the **margined** value.

    ``CONTRACT_DAYS`` and ``SECURITY_MONTHS`` are holding bases. They are
    listed so the mapping is total, and skipped by every per-fill function
    rather than approximated: no per-trade constant can express "per open
    contract per account per day" (rulebook 12.2).
    """

    TRADE_VALUE = 'trade_value'
    NOTIONAL = 'notional'
    MARGINED_VALUE = 'margined_value'
    QUANTITY = 'quantity'
    PER_TRADE = 'per_trade'
    CONTRACT_DAYS = 'contract_days'
    SECURITY_MONTHS = 'security_months'


#: Bases a single fill can be priced against. The other two are holding
#: charges -- custody is billed monthly per security and the VSD position fee
#: accrued per open contract per day -- and a daily/monthly accrual pass owns
#: them (rulebook 12.2, 12.5).
FILL_BASES: FrozenSet[ChargeBasis] = frozenset({
    ChargeBasis.TRADE_VALUE,
    ChargeBasis.NOTIONAL,
    ChargeBasis.MARGINED_VALUE,
    ChargeBasis.QUANTITY,
    ChargeBasis.PER_TRADE,
})

#: Bases whose ``amount`` is charged per unit of the base rather than flat.
_COUNTED: FrozenSet[ChargeBasis] = frozenset({ChargeBasis.QUANTITY})

#: The rulebook's id for the derivatives transfer tax. Named rather than
#: matched inline because it is the one row whose *basis* is not derivable
#: from ``(ChargeBase, venue)`` -- it shares ``TRADE_VALUE`` with the exchange
#: fee and is levied on a different quantity entirely.
DERIVATIVES_PIT_CHARGE_ID = 'pit_derivatives_transfer'

#: The statutory rate against the **margined** base. 0.1%, not 0.05%: the
#: halving is inside the base (the published formula's trailing ``/ 2``), and
#: writing 0.0005 against notional-times-ratio would state the same number
#: with the statute's own structure destroyed.
DERIVATIVES_PIT_RATE = Decimal('0.001')

#: Where the derivatives tax rate and base come from. Carried here because
#: :func:`levy` may price the charge from the statutory formula even when the
#: row it was handed states the equivalent folded rate, and a charge computed
#: from a constant in this module must still name its source.
DERIVATIVES_PIT_CITATION = RuleCitation(
    document='Cong van 11133/BTC-CST (2017-08-21); Thong tu 87/2026/TT-BTC '
             'Dieu 5 khoan 1 (2026-06-30)',
    effective_from=date(2017, 8, 10),
    confidence=Confidence.MEDIUM,
    note='Rulebook 8.1. Arithmetic identical across the two instruments, so '
         '2017-08-10 -> today is ONE interval and only the legal rank of the '
         'source changes on 2026-07-01. The traceability caveat the paper '
         'must carry: for 2017-2026 the rule rested on a ministry LETTER, '
         'which is not gazetted as a legal normative document, and the '
         "letter's own text was never opened. Collection began 2017-08-10, "
         'eleven days before the letter was written.',
)


def basis_for(rule: ChargeRule, venue: Venue) -> ChargeBasis:
    """The basis one row is levied on at one venue.

    Total over :class:`~plutus.market.session.types.ChargeBase`, and the only
    place the ``(ChargeBase, venue, charge_id)`` -> basis decision is taken.
    The ``TRADE_VALUE`` row is the interesting one and splits three ways: the
    cash conversion on a cash venue, the futures notional on HNXDS, and the
    margined value for the derivatives transfer tax.
    """
    if rule.base is ChargeBase.PER_CONTRACT:
        return ChargeBasis.QUANTITY
    if rule.base is ChargeBase.PER_TRADE:
        return ChargeBasis.PER_TRADE
    if rule.base is ChargeBase.PER_OPEN_CONTRACT_PER_DAY:
        return ChargeBasis.CONTRACT_DAYS
    if rule.base is ChargeBase.MONTHLY_PER_SECURITY:
        return ChargeBasis.SECURITY_MONTHS
    # ChargeBase.TRADE_VALUE
    if venue is not Venue.HNXDS:
        return ChargeBasis.TRADE_VALUE
    if rule.charge_id == DERIVATIVES_PIT_CHARGE_ID:
        return ChargeBasis.MARGINED_VALUE
    return ChargeBasis.NOTIONAL


# --------------------------------------------------------------------------
# What a charge is priced against
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ChargeContext:
    """One trade, as much of it as pricing a charge needs.

    Carries the *four* axes the table resolves on -- venue, charge class,
    side, and the instant the ``RuleSet`` was resolved at -- plus the two
    quantities a cash conversion cannot be done without on HNXDS: the contract
    multiplier and the VSD initial margin ratio.

    ``daily_value`` and ``daily_contracts`` are the account's running totals
    for the day **including this trade**, and they exist because broker
    commission tiers on the day's total rather than the order's (rulebook
    8.3). Left ``None`` they fall back to this trade alone, which is correct
    for the first trade of a day and an under-estimate afterwards --
    :class:`DailyTurnover` is the meter that fills them in.
    """

    venue: Venue
    charge_class: ChargeClass
    side: Side
    quantity: int
    price: Decimal
    ts: datetime
    ticker: Optional[str] = None
    multiplier: Optional[Decimal] = None
    initial_margin_rate: Optional[Decimal] = None
    order_id: Optional[OrderId] = None
    fill_id: Optional[FillId] = None
    daily_value: Optional[Decimal] = None
    daily_contracts: Optional[int] = None

    @property
    def day(self) -> date:
        """The calendar day the tier variable accumulates over."""
        return self.ts.date()

    @property
    def trade_value(self) -> Decimal:
        """The cash-venue conversion. Raises on HNXDS, by design."""
        return trade_value(self.venue, self.quantity, self.price)

    @property
    def notional(self) -> Decimal:
        """``contracts x price x multiplier``.

        Raises:
            ValueError: on a cash venue, which has no contract multiplier and
                whose conversion is :attr:`trade_value`; or on HNXDS with no
                multiplier supplied, because guessing 100,000 would be right
                for VN30F and 10x wrong for the government-bond contracts.
        """
        if self.venue is not Venue.HNXDS:
            raise ValueError(
                f'{self.venue.value} is a cash venue quoted in thousands of '
                f'dong; its conversion is trade_value, not a contract '
                f'multiplier'
            )
        if self.multiplier is None:
            raise ValueError(
                f'no contract multiplier for {self.ticker!r}: HNXDS notional '
                f'is points x multiplier x contracts and the multiplier '
                f'differs by product (100,000 for VN30F, 10,000 for the '
                f'government-bond contracts), so it cannot be defaulted'
            )
        return derivatives_notional(self.quantity, self.price,
                                    self.multiplier)

    @property
    def margined_value(self) -> Decimal:
        """The published derivatives tax base: ``notional x IM ratio / 2``.

        Raises:
            ValueError: when no initial margin ratio has been resolved. The
                tax is linear in it, so a default would be a second margin
                series -- the failure the rulebook names in bold.
        """
        if self.initial_margin_rate is None:
            raise ValueError(
                f'no VSD initial margin ratio resolved for {self.ticker!r}: '
                f'the derivatives transfer tax base is LINEAR in it, so it '
                f'must be read from the one dated series '
                f'(RuleSet.initial_margin_rate -> margin.vsd_initial_margin) '
                f'and never defaulted here'
            )
        # ``notional`` raises on a missing multiplier and on a cash venue, so
        # the base cannot be assembled from a half-known trade.
        return self.notional * self.initial_margin_rate / Decimal('2')

    @property
    def transaction_value(self) -> Decimal:
        """The money this trade moves, whichever venue it is on.

        The tier variable's money quantity and the only property that
        dispatches on venue, so the two conversions stay apart everywhere
        else.
        """
        if self.venue is Venue.HNXDS:
            return self.notional
        return self.trade_value

    @property
    def pool(self) -> Pool:
        """Which account pays. Segregation is enforced by the ledgers."""
        return pool_for_venue(self.venue)


# --------------------------------------------------------------------------
# What was levied
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LeviedCharge:
    """One charge actually levied, with the rule and the citation attached.

    :class:`~plutus.market.session.types.Charge` is what the session itemises
    and what a ledger debits; it names the rule by id and says who levied it,
    which is what design section 6.1 asks for. This wrapper adds the two
    things an *audit* needs and ``Charge`` has no field for: the row itself,
    and the basis the rate was really applied to.

    :attr:`basis_value` is the honest answer to "what was this a percentage
    of". For the derivatives transfer tax it is the **margined** value while
    ``charge.base_value`` is the notional the rulebook row is worded against
    -- see the module docstring's orchestrator note. The two never disagree
    about the dong.
    """

    charge: Charge
    rule: ChargeRule
    basis: ChargeBasis
    basis_value: Decimal
    rate: Optional[Decimal] = None

    @property
    def citation(self) -> Optional[RuleCitation]:
        """Under what rule. ``None`` only for a broker row, which has none."""
        return self.rule.citation

    @property
    def levied_by(self) -> LeviedBy:
        """Who levied it -- state, exchange, depository or broker."""
        return self.rule.levied_by

    @property
    def total(self) -> Decimal:
        """Charge plus VAT: what actually leaves the account."""
        return self.charge.total


# --------------------------------------------------------------------------
# Broker commission -- tiered on the day's total, per account
# --------------------------------------------------------------------------

class TierVariable(str, Enum):
    """What a tiered commission's rate is selected by.

    Rulebook 8.3 is explicit and the distinction is load-bearing: "the tiering
    variable is DAILY value per account, not per-order value. A commission
    model that tiers per order will misprice."
    """

    NONE = 'none'
    DAILY_VALUE_PER_ACCOUNT = 'daily_value_per_account'
    DAILY_CONTRACTS_PER_ACCOUNT = 'daily_contracts_per_account'


@dataclass(frozen=True)
class CommissionTier:
    """One band of a commission schedule.

    ``threshold`` is the inclusive lower bound of the tier variable. Exactly
    one of ``rate`` (a Decimal fraction of transaction value) and ``amount``
    (absolute VND per contract) is set, matching the shape difference the
    rulebook records between the two markets: the cash market prices
    commission as a percentage, the derivatives market as a fixed amount per
    contract.
    """

    threshold: Decimal
    rate: Optional[Decimal] = None
    amount: Optional[Decimal] = None

    def __post_init__(self):
        if (self.rate is None) == (self.amount is None):
            raise ValueError(
                f'commission tier at {self.threshold} must set exactly one of '
                f'rate and amount, got rate={self.rate}, amount={self.amount}')
        if self.threshold < _ZERO:
            raise ValueError(
                f'tier threshold must not be negative, got {self.threshold}')


@dataclass(frozen=True)
class CommissionSchedule:
    """A broker's commission for one venue: tiers, and a per-order minimum.

    **Every number here is a commercial term and none of it is sourced.** See
    :attr:`PROVENANCE`. What *is* sourced is the shape, and the shape is why
    this cannot be a scalar rate:

    * the rate is selected by the **day's** total transaction value per
      account, so it is not knowable when a fill happens (rulebook 8.3, 12.7)
      -- hence :attr:`debited_at` is ``DAILY`` and :func:`assess_daily` is
      where a tiered commission is actually levied;
    * tiers are **not monotone**. SSI's real online schedule is 0.25% below
      100m dong/day, 0.30% from 100m to 500m, and 0.25% above -- confirmed on
      SSI's own page and explicitly *not* a transcription error. Any code that
      assumes commission falls with volume is wrong about a live schedule;
    * some firms impose a **minimum charge per order**, which is a clamp on
      each order and not on the day, so the day's charge is a sum of clamped
      per-order amounts and not a clamp on the sum.

    A statutory **cap** exists and this is not it: max 0.5% of transaction
    value to 2021-12-31 and max 0.45% from 2022-01-01, with **no floor** since
    2019-02-15 -- which is what allowed the 2020-2021 zero-fee price war, so
    a rate of exactly zero is a real schedule and not a misconfiguration.
    :meth:`check_against_cap` tests a schedule against a cap the caller reads
    from the rulebook; nothing here enforces it silently.
    """

    venue: Venue
    base: ChargeBase = ChargeBase.TRADE_VALUE
    tiers: Tuple[CommissionTier, ...] = ()
    minimum_per_order: Optional[Decimal] = None
    tier_variable: TierVariable = TierVariable.DAILY_VALUE_PER_ACCOUNT
    charge_id: Optional[str] = None
    applies_to: FrozenSet[ChargeClass] = frozenset(ChargeClass)

    #: Where each field's content comes from. Read this before quoting any of
    #: it, exactly as with
    #: :attr:`plutus.market.broker.BrokerTerms.PROVENANCE`. Unannotated, so it
    #: is a class attribute and not a dataclass field.
    PROVENANCE = {
        'tiers': 'UNSOURCED. Typical retail equity commission is 0.10%-0.35% '
                 'of transaction value tiered on daily value per account, and '
                 '0% at several entrants; index futures 1,000-3,000 '
                 'VND/contract tiered on contracts per day with breaks '
                 'commonly at 100/200/300. Both are broker schedules, not '
                 'gazetted rules, and each firm changes them at will.',
        'tier_variable': 'SOURCED as a shape, not as a value. VPS states the '
                         'tier is computed on "Tong so luong hop dong tuong '
                         'lai chi so da khop trong ngay" and SSI on "Tong gia '
                         'tri giao dich/ngay/tai khoan".',
        'minimum_per_order': 'UNSOURCED. "Some firms impose a minimum charge '
                             'per order" is the only description found; no '
                             'value was traced to a schedule, and Vietnamese '
                             'fee tables often quote thousand-dong, so a '
                             'figure like 30,000 may mean 30,000,000.',
        'debited_at': 'SOURCED. The rate is only knowable at end of day, '
                      'which the rulebook calls the single most useful '
                      'implementation finding in the fee domain.',
        'per_fill_attribution': 'A MODELLING CHOICE. assess_daily levies the '
                                "day's charge at the close, which is what a "
                                'broker does. Pricing a tiered commission at '
                                'the fill instead would pick the tier from a '
                                'part-formed day and misprice every boundary '
                                'crossing.',
    }

    def __post_init__(self):
        if not self.tiers:
            raise ValueError(
                f'commission schedule for {self.venue.value} has no tiers; a '
                f'schedule with no rate is not a free broker, it is a missing '
                f'config'
            )
        thresholds = [t.threshold for t in self.tiers]
        if thresholds != sorted(thresholds) or len(set(thresholds)) != len(
                thresholds):
            raise ValueError(
                f'commission tiers must have strictly increasing thresholds, '
                f'got {thresholds}. RATES need not increase -- SSI really does '
                f'charge 0.25/0.30/0.25 -- but two tiers cannot start at the '
                f'same place'
            )
        if thresholds[0] != _ZERO:
            raise ValueError(
                f'the first commission tier must start at 0, got '
                f'{thresholds[0]}: a schedule that prices nothing below its '
                f'first threshold would silently make small orders free'
            )
        object.__setattr__(
            self, 'charge_id',
            self.charge_id or f'broker.commission.{self.venue.value.lower()}')

    @property
    def debited_at(self) -> DebitedAt:
        """``DAILY`` when tiered, ``FILL`` when there is one flat tier.

        A single-tier schedule *is* knowable at fill time, so pretending
        otherwise would defer a charge that has no reason to be deferred. More
        than one tier and the rate depends on a total that does not exist
        until the close.
        """
        if len(self.tiers) == 1 or self.tier_variable is TierVariable.NONE:
            return DebitedAt.FILL
        return DebitedAt.DAILY

    def tier_value(self, ctx: ChargeContext) -> Decimal:
        """The tier variable for one context -- the day's total, not the order's."""
        if self.tier_variable is TierVariable.DAILY_CONTRACTS_PER_ACCOUNT:
            return Decimal(ctx.daily_contracts if ctx.daily_contracts
                           is not None else ctx.quantity)
        if self.tier_variable is TierVariable.NONE:
            return _ZERO
        return (ctx.daily_value if ctx.daily_value is not None
                else ctx.transaction_value)

    def tier_at(self, value: Decimal) -> CommissionTier:
        """The band ``value`` falls in: the last tier whose threshold it reaches."""
        chosen = self.tiers[0]
        for tier in self.tiers:
            if value >= tier.threshold:
                chosen = tier
            else:
                break
        return chosen

    def worst_case_tier(self) -> CommissionTier:
        """The dearest band, for an estimate taken before the day is known.

        An encumbrance is taken when an order is accepted, and the tier
        depends on a total that does not exist yet. Reserving at the dearest
        band over-reserves and never under-reserves, which is the direction
        design section 7.0 requires: the reservation is released in full at
        the terminal edge either way, but a buy funded at the cheapest tier
        can be short of cash at the fill.
        """
        rated = [t for t in self.tiers if t.rate is not None]
        if rated:
            return max(rated, key=lambda t: t.rate)
        return max(self.tiers, key=lambda t: t.amount)

    def rule_at(self, tier: CommissionTier) -> ChargeRule:
        """This schedule, collapsed into one row of the generic table.

        The point of returning a :class:`ChargeRule` rather than a private
        shape: a tiered commission then flows through exactly the same
        arithmetic, clamps, VAT flag and rounding as every gazetted row, so
        there is one charge engine and not two. ``minimum_per_order`` becomes
        the row's ``minimum``, which is where the per-order clamp belongs --
        it is a clamp on the order, never on the day.

        The row carries no citation, and that absence is the design: a broker
        row is commercial and unsourced, and ``rulebook.py`` refuses to serve
        one.
        """
        return ChargeRule(
            charge_id=self.charge_id,
            base=self.base,
            side=ChargeSide.BOTH,
            levied_by=LeviedBy.BROKER,
            debited_at=self.debited_at,
            pool=pool_for_venue(self.venue),
            applies_to=self.applies_to,
            venue=self.venue,
            rate=tier.rate,
            amount=tier.amount,
            minimum=self.minimum_per_order,
        )

    def rule_for(self, ctx: ChargeContext) -> ChargeRule:
        """The row in force for one trade, tier selected from the day's total."""
        return self.rule_at(self.tier_at(self.tier_value(ctx)))

    def check_against_cap(self, cap_rate: Optional[Decimal] = None,
                          cap_amount: Optional[Decimal] = None) -> Tuple[str, ...]:
        """Which tiers exceed a statutory cap. Reports, never mutates.

        The cap is a dated exchange-side rule (0.5% to 2021-12-31, 0.45%
        after; 15,000/25,000 VND per contract to 2021-12-31, 5,000/8,000
        after) and belongs in the rulebook, so it is passed in rather than
        held here. Silently clamping a configured commission to a cap would
        make a run report a rate the caller never set.

        Note the derivatives caps are ``medium`` confidence at best: the
        circular could not be opened from any mirror, and SSI's schedule
        charges 5,000 VND on government-bond futures, which sits exactly at
        the claimed *index* cap -- so the two may be transposed.
        """
        breaches: List[str] = []
        for tier in self.tiers:
            if (cap_rate is not None and tier.rate is not None
                    and tier.rate > cap_rate):
                breaches.append(
                    f'tier from {tier.threshold}: rate {tier.rate} exceeds '
                    f'the cap {cap_rate}')
            if (cap_amount is not None and tier.amount is not None
                    and tier.amount > cap_amount):
                breaches.append(
                    f'tier from {tier.threshold}: {tier.amount} VND/contract '
                    f'exceeds the cap {cap_amount}')
        return tuple(breaches)

    @classmethod
    def from_config(cls, row: Mapping[str, object]) -> 'CommissionSchedule':
        """Build from one ``broker_profile.commission`` row.

        Accepts the flat form design section 6 already documents --
        ``{"venue": "HSX", "base": "trade_value", "rate": 0.0015}`` -- and the
        tiered extension::

            {"venue": "HSX", "base": "trade_value",
             "tier_variable": "daily_value_per_account",
             "tiers": [{"from": 0,         "rate": 0.0025},
                       {"from": 100000000, "rate": 0.0030},
                       {"from": 500000000, "rate": 0.0025}],
             "min_per_order": 30000}

        The flat form collapses to a single tier starting at zero, which
        :attr:`debited_at` then reports as ``FILL`` -- so an existing config
        keeps its existing behaviour and only a config that asks for tiers
        gets the daily-close treatment.

        Rates are read through ``str()`` before ``Decimal`` because a JSON
        config delivers them as floats, and ``Decimal(0.0025)`` is not
        0.0025.
        """
        venue = Venue.from_code(str(row['venue']))
        base = ChargeBase(str(row.get('base', ChargeBase.TRADE_VALUE.value)))
        raw_tiers = row.get('tiers')
        if raw_tiers:
            tiers = tuple(
                CommissionTier(
                    threshold=Decimal(str(t.get('from', 0))),
                    rate=(Decimal(str(t['rate'])) if 'rate' in t else None),
                    amount=(Decimal(str(t['amount'])) if 'amount' in t
                            else None),
                )
                for t in raw_tiers  # type: ignore[union-attr]
            )
        else:
            tiers = (CommissionTier(
                threshold=_ZERO,
                rate=(Decimal(str(row['rate'])) if 'rate' in row else None),
                amount=(Decimal(str(row['amount'])) if 'amount' in row
                        else None),
            ),)
        default_variable = (TierVariable.DAILY_CONTRACTS_PER_ACCOUNT
                            if base is ChargeBase.PER_CONTRACT
                            else TierVariable.DAILY_VALUE_PER_ACCOUNT)
        variable = TierVariable(str(row.get('tier_variable',
                                            default_variable.value)))
        minimum = row.get('min_per_order', row.get('min'))
        return cls(
            venue=venue,
            base=base,
            tiers=tiers,
            minimum_per_order=(Decimal(str(minimum)) if minimum is not None
                               else None),
            tier_variable=variable,
        )


class DailyTurnover:
    """Per-account running totals for a day -- the tier variable's source.

    Exists because the commission rate is selected by the *day's* total and a
    fill only knows about itself. Keeps the contexts rather than just the
    sums, because the per-order minimum is a clamp on each order: the day's
    commission is a sum of clamped per-order amounts, not a clamp on the sum,
    and collapsing to a scalar loses the ability to compute it.

    Not thread-safe and not persistent. One instance per account.
    """

    def __init__(self) -> None:
        self._by_day: Dict[date, List[ChargeContext]] = {}

    def add(self, ctx: ChargeContext) -> None:
        """Record one executed trade against its day."""
        self._by_day.setdefault(ctx.day, []).append(ctx)

    def contexts_on(self, day: date) -> Tuple[ChargeContext, ...]:
        """Everything recorded for that day, in the order it was recorded."""
        return tuple(self._by_day.get(day, ()))

    def days(self) -> Tuple[date, ...]:
        """Every day with a trade on it, oldest first."""
        return tuple(sorted(self._by_day))

    def value_on(self, day: date) -> Decimal:
        """Total transaction value on that day, both sides counted.

        Both sides, because the exchange's own base is two-sided -- "Tong gia
        tri giao dich cua moi thanh vien = Gia tri mua chung khoan + Gia tri
        ban chung khoan" (rulebook 8.2) -- and the broker schedules that tier
        on "total transaction value per day" use the same phrase.
        """
        return sum((c.transaction_value for c in self.contexts_on(day)), _ZERO)

    def contracts_on(self, day: date) -> int:
        """Total matched contracts on that day, both legs counted."""
        return sum(c.quantity for c in self.contexts_on(day)
                   if c.venue is Venue.HNXDS)

    def including(self, ctx: ChargeContext) -> ChargeContext:
        """``ctx`` with the day's totals filled in, this trade included.

        The tier a fill sits in is decided by the day's total *including*
        itself, which is what a broker computes at the close. Returns a copy;
        nothing is recorded, so a caller may price a hypothetical trade
        without polluting the meter.
        """
        day = ctx.day
        value = self.value_on(day)
        contracts = self.contracts_on(day)
        own_contracts = ctx.quantity if ctx.venue is Venue.HNXDS else 0
        return replace(ctx,
                       daily_value=value + ctx.transaction_value,
                       daily_contracts=contracts + own_contracts)


# --------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------

def basis_value(rule: ChargeRule, ctx: ChargeContext) -> Optional[Decimal]:
    """What this row's rate or amount is applied to, or ``None`` if not per-fill.

    ``None`` is returned for the two holding bases rather than an approximated
    number: a fill cannot know how many days a contract will be open or how
    many month-ends a holding will cross.
    """
    basis = basis_for(rule, ctx.venue)
    if basis is ChargeBasis.TRADE_VALUE:
        return ctx.trade_value
    if basis is ChargeBasis.NOTIONAL:
        return ctx.notional
    if basis is ChargeBasis.MARGINED_VALUE:
        return ctx.margined_value
    if basis is ChargeBasis.QUANTITY:
        return Decimal(ctx.quantity)
    if basis is ChargeBasis.PER_TRADE:
        return Decimal('1')
    return None


def charge_amount(rule: ChargeRule, base_value: Decimal, *,
                  rate: Optional[Decimal] = None,
                  counted: bool = False) -> Decimal:
    """One charge's dong amount, clamped by ``minimum``/``maximum``.

    ``rate`` multiplies the base value; ``amount`` is per unit for a counted
    base (per contract, per unit) and flat otherwise. Passing ``rate``
    explicitly overrides the row's own, which is how the derivatives transfer
    tax is priced from the statutory 0.1% against the margined base rather
    than from the folded rate the rulebook row states against notional.

    Rounding to whole dong is the declared modelling choice of this module's
    docstring, not a sourced rule.
    """
    effective = rule.rate if rate is None else rate
    if effective is not None:
        raw = effective * base_value
    elif rule.amount is not None:
        raw = rule.amount * (base_value if counted else Decimal('1'))
    else:
        raise ValueError(
            f'charge rule {rule.charge_id!r} sets neither rate nor amount')
    if rule.minimum is not None:
        raw = max(raw, rule.minimum)
    if rule.maximum is not None:
        raw = min(raw, rule.maximum)
    return to_dong(raw)


def vat_on(rule: ChargeRule, amount: Decimal) -> Decimal:
    """VAT on one charge, off unless the row says otherwise.

    Per-charge rather than global because the source material conflicts:
    state-set prices were VAT-exempt to 2025-04-28 and VAT-exclusive from
    2025-04-29, yet brokers demonstrably billed VSDC derivatives charges
    grossed up exactly 10% during the exemption -- 2,805 = 2,550 x 1.1,
    0.00264% = 0.0024% x 1.1 (rulebook 8.1, 12.1). The conflict is carried,
    not resolved.
    """
    if not rule.vat_applies:
        return _ZERO
    return to_dong(amount * rule.vat_rate)


def _pit_rate_check(rule: ChargeRule, ctx: ChargeContext,
                    margined: Decimal) -> None:
    """Refuse a derivatives tax row whose folded rate implies another ratio.

    The rulebook states the coupling in bold: the derivatives tax base is
    linear in the VSD initial margin ratio, so "one dated VSD series must feed
    both ``margin.py`` and the tax model, or the paper carries two mutually
    inconsistent margin ratios".

    ``RuleSet.charges`` serves the row with the rate already folded --
    ``0.0005 x IM`` against notional -- because that is how the row is worded
    against ``ChargeBase.TRADE_VALUE``. This module prices the same charge the
    way the statute writes it, ``0.001 x margined value``, from the ratio
    resolved for *this* contract at *this* instant. The two are the same
    number if and only if both read the same series, so comparing them is a
    live drift detector rather than a restatement. It fires the moment a
    second ratio appears anywhere upstream.
    """
    if rule.rate is None:
        return
    folded = rule.rate * ctx.notional
    statutory = DERIVATIVES_PIT_RATE * margined
    if folded != statutory:
        raise ValueError(
            f'derivatives transfer tax disagrees with itself for '
            f'{ctx.ticker!r} at {ctx.ts}: the charge row states '
            f'{rule.rate} x notional = {folded}, the published formula gives '
            f'0.001 x (notional x IM / 2) = {statutory} at an initial margin '
            f'ratio of {ctx.initial_margin_rate}. The tax base is LINEAR in '
            f'that ratio, so this means two different margin ratios are live '
            f'in one run -- fix the series, do not reconcile the numbers.'
        )


def levy(rule: ChargeRule, ctx: ChargeContext) -> Optional[LeviedCharge]:
    """Price one row against one trade, or ``None`` if it does not bite.

    ``None`` rather than a zero charge for three distinct reasons, all of
    which are "this row is not about this trade": the side does not match (the
    0.1% equity tax on a buy), the venue or instrument class does not match,
    or the basis is a holding basis no fill can price.

    The derivatives transfer tax is the one row priced off its own statutory
    formula rather than off the row's stated rate -- see
    :func:`_pit_rate_check` for why that is a check and not a duplication.
    """
    if not rule.applies(ctx.venue, ctx.charge_class, ctx.side):
        return None
    basis = basis_for(rule, ctx.venue)
    if basis not in FILL_BASES:
        return None
    value = basis_value(rule, ctx)
    if value is None:  # pragma: no cover - FILL_BASES already excluded these
        return None

    rate: Optional[Decimal] = rule.rate
    reported_base_value = value
    if basis is ChargeBasis.MARGINED_VALUE:
        _pit_rate_check(rule, ctx, value)
        rate = DERIVATIVES_PIT_RATE
        # The projected ``Charge`` keeps the rulebook row's own wording --
        # ``TRADE_VALUE`` against notional -- because ``ChargeBase`` has no
        # ``MARGINED_VALUE`` member to label it with. The statutory base
        # travels on the LeviedCharge instead. See the module docstring.
        reported_base_value = ctx.notional

    amount = charge_amount(rule, value, rate=rate,
                           counted=basis in _COUNTED)
    vat = vat_on(rule, amount)
    citation = rule.citation
    if citation is None and rule.charge_id == DERIVATIVES_PIT_CHARGE_ID:
        citation = DERIVATIVES_PIT_CITATION
        rule = replace(rule, citation=citation)
    return LeviedCharge(
        charge=Charge(
            kind=rule.charge_id, venue=ctx.venue, base=rule.base,
            base_value=reported_base_value, amount=amount,
            levied_by=rule.levied_by, pool=rule.pool, ts=ctx.ts,
            ticker=ctx.ticker, order_id=ctx.order_id, fill_id=ctx.fill_id,
            vat=vat,
        ),
        rule=rule, basis=basis, basis_value=value, rate=rate,
    )


def schedule(rules: 'RuleSet', profile: Optional[BrokerProfile],
             ctx: ChargeContext, *,
             commission: Sequence[CommissionSchedule] = (),
             worst_case: bool = False) -> Tuple[ChargeRule, ...]:
    """Every row in force for ``(venue, charge class, side, date)``.

    Three sources, because they are three kinds of fact and must not be
    merged upstream:

    * ``RuleSet.charges(venue, cls_)`` -- gazetted, dated, cited, and it
      *refuses* to return a ``BROKER`` row;
    * ``BrokerProfile.commission`` -- flat commercial rows, already parsed;
    * ``commission`` -- :class:`CommissionSchedule` objects, whose rate is
      resolved here from the day's total on ``ctx``.

    A schedule shadows a profile row with the same ``charge_id``. Both
    describe the same broker's commission on the same venue, and levying both
    would double-charge every trade; the richer object wins because the flat
    row is what a config produces when it has nothing better to say.

    ``worst_case`` takes each tiered schedule at its **dearest** band instead
    of at the band the day's total puts it in. That is what an encumbrance
    needs, because the day does not exist yet when an order is accepted.
    """
    rows: List[ChargeRule] = list(rules.charges(ctx.venue, ctx.charge_class))
    tiered = tuple(s for s in commission if s.venue is ctx.venue)
    shadowed = {s.charge_id for s in tiered}
    if profile is not None:
        rows.extend(r for r in profile.commission
                    if r.charge_id not in shadowed)
    rows.extend(s.rule_at(s.worst_case_tier()) if worst_case
                else s.rule_for(ctx) for s in tiered)
    return tuple(rows)


def _with_margin_rate(rules: 'RuleSet', ctx: ChargeContext) -> ChargeContext:
    """Fill in the VSD initial margin ratio from the one dated series.

    Only on HNXDS, only when the caller has not supplied one, and only from
    :meth:`RuleSet.initial_margin_rate` -- which delegates to
    :func:`plutus.market.margin.vsd_initial_margin`, the same call
    ``deposit.py`` makes for the margin requirement. There is deliberately no
    fallback constant: a contract family whose ratio VSDC does not publish
    (the government-bond futures carry a delivery margin instead, and its
    value is not published) must raise rather than borrow the index series.
    """
    if ctx.venue is not Venue.HNXDS or ctx.initial_margin_rate is not None:
        return ctx
    if ctx.ticker is None:
        return ctx
    return replace(ctx,
                   initial_margin_rate=rules.initial_margin_rate(ctx.ticker))


def estimate(rules: 'RuleSet', profile: Optional[BrokerProfile],
             ctx: ChargeContext, *,
             commission: Sequence[CommissionSchedule] = ()) -> Decimal:
    """Worst-case charges on a hypothetical fill, for the buy encumbrance.

    Estimated charges sit **inside** the encumbrance (design section 7.0) so
    ``available`` stays consistent with what a fill will actually cost.
    Leaving them out lets a caller rest a buy it can fund the shares of and
    not the fees.

    ``DAILY`` rows are included even though :func:`assess` does not levy them:
    a commission that tiers on the day's total is not knowable at fill time,
    and a reservation that ignored it would under-fund. For a tiered schedule
    the **dearest** tier is used -- see
    :meth:`CommissionSchedule.worst_case_tier` -- because over-reserving is
    the conservative direction and the reservation is released in full at the
    terminal edge either way. ``MONTHLY`` rows are excluded: a fill does not
    know how many month-ends the holding will cross.
    """
    ctx = _with_margin_rate(rules, ctx)
    total = _ZERO
    for rule in schedule(rules, profile, ctx, commission=commission,
                         worst_case=True):
        if rule.debited_at is DebitedAt.MONTHLY:
            continue
        priced = levy(rule, ctx)
        if priced is None:
            continue
        total += priced.total
    return to_dong(total)


def assess(rules: 'RuleSet', profile: Optional[BrokerProfile],
           ctx: ChargeContext, *,
           commission: Sequence[CommissionSchedule] = ()
           ) -> Tuple[LeviedCharge, ...]:
    """The charges actually levied on one fill.

    ``debited_at == FILL`` rows only. ``DAILY`` rows -- a tiered broker
    commission, whose rate is only knowable at the daily close -- and
    ``MONTHLY`` rows -- custody, the VSDC collateral fee -- are deliberately
    not levied here. :func:`assess_daily` owns the first; the monthly accrual
    is not built, and skipping is the honest treatment because pricing either
    per fill picks a number the rules do not produce.
    """
    ctx = _with_margin_rate(rules, ctx)
    levied: List[LeviedCharge] = []
    for rule in schedule(rules, profile, ctx, commission=commission):
        if rule.debited_at is not DebitedAt.FILL:
            continue
        priced = levy(rule, ctx)
        if priced is not None:
            levied.append(priced)
    return tuple(levied)


def assess_at_maturity(rules: 'RuleSet',
                       ctx: ChargeContext) -> Tuple[LeviedCharge, ...]:
    """The derivatives transfer tax at contract maturity.

    Rulebook 8.1 and 12.3: taxable income on a futures contract is determined
    "when the order is matched, **or at contract maturity**". A position
    carried into final settlement is never matched out, so a model that levies
    the tax only on fills under-charges every held-to-expiry contract by one
    leg.

    ``ctx.price`` is the final settlement price and ``ctx.quantity`` the
    contracts settled. The side is whichever direction closes the position;
    the row is two-sided, so it bites either way.

    **Only the tax.** The exchange trading fee is charged per *matched*
    contract and the VSDC clearing fee per *novated* contract, and no source
    read says either is charged on a final cash settlement. Levying them here
    would invent a charge; a run that needs them must source them first.

    Raises:
        ValueError: on a cash venue. Equity has no maturity, and the row this
            function exists for is HNXDS-only.
    """
    if ctx.venue is not Venue.HNXDS:
        raise ValueError(
            f'{ctx.venue.value} instruments do not mature; assess_at_maturity '
            f'levies the derivatives transfer tax, which is an HNXDS row'
        )
    ctx = _with_margin_rate(rules, ctx)
    levied: List[LeviedCharge] = []
    for rule in rules.charges(ctx.venue, ctx.charge_class):
        if rule.charge_id != DERIVATIVES_PIT_CHARGE_ID:
            continue
        priced = levy(rule, ctx)
        if priced is not None:
            levied.append(priced)
    return tuple(levied)


def assess_daily(commission: Sequence[CommissionSchedule],
                 turnover: DailyTurnover, day: date, *,
                 ts: Optional[datetime] = None
                 ) -> Tuple[LeviedCharge, ...]:
    """The daily-close pass: charges whose rate needs the whole day.

    This is where a tiered broker commission is actually levied. Rulebook 8.3
    and 12.7: the rate is selected on "Tong gia tri giao dich/ngay/tai khoan",
    so it does not exist until the session is over, and the rulebook calls
    applying commission at the close "the single most useful implementation
    finding in the fee domain".

    Three things this gets right that a per-fill model cannot:

    * **The tier is picked once**, from the day's total, and then applied to
      every trade of the day -- so an account that crosses a boundary on its
      last trade is re-priced for the whole day, which is what the schedule
      says and what a per-fill model can never reproduce.
    * **The minimum is per order, not per day.** A schedule with a 30,000d
      minimum and six orders charges the minimum six times if all six are
      small. Clamping the day's total instead would under-charge by up to
      five times the minimum.
    * **Both sides count** toward the tier variable, matching the two-sided
      base the exchange itself uses (rulebook 8.2).

    ``ts`` is the instant to stamp the charges at; it defaults to the last
    trade of the day, which is the closest thing to "the close" this module
    can know without a session calendar.

    Returns one charge per (schedule, order), because the minimum is a clamp
    on the order. Fills of the same order are aggregated first.
    """
    contexts = turnover.contexts_on(day)
    if not contexts:
        return ()
    stamp = ts or max(c.ts for c in contexts)
    day_value = turnover.value_on(day)
    day_contracts = turnover.contracts_on(day)

    levied: List[LeviedCharge] = []
    for sched in commission:
        if sched.debited_at is not DebitedAt.DAILY:
            continue
        mine = [c for c in contexts if c.venue is sched.venue
                and c.charge_class in sched.applies_to]
        if not mine:
            continue
        probe = replace(mine[0], daily_value=day_value,
                        daily_contracts=day_contracts)
        rule = sched.rule_for(probe)
        for _order_id, group in _by_order(mine):
            merged = _merge_for_commission(group, stamp)
            priced = levy(rule, merged)
            if priced is not None:
                levied.append(priced)
    return tuple(levied)


def _by_order(contexts: Sequence[ChargeContext]
              ) -> Tuple[Tuple[Optional[OrderId], Tuple[ChargeContext, ...]], ...]:
    """Group a day's contexts by order, preserving first-seen order.

    Contexts with no ``order_id`` are each their own group: the per-order
    minimum cannot be applied to a set of trades that do not claim to belong
    to one order, and merging them would apply one minimum where several are
    due.
    """
    groups: Dict[object, List[ChargeContext]] = {}
    anonymous: List[Tuple[Optional[OrderId], Tuple[ChargeContext, ...]]] = []
    order: List[object] = []
    for ctx in contexts:
        if ctx.order_id is None:
            anonymous.append((None, (ctx,)))
            continue
        if ctx.order_id not in groups:
            groups[ctx.order_id] = []
            order.append(ctx.order_id)
        groups[ctx.order_id].append(ctx)
    named = tuple((oid, tuple(groups[oid])) for oid in order)  # type: ignore[index]
    return named + tuple(anonymous)


def _merge_for_commission(group: Sequence[ChargeContext],
                          stamp: datetime) -> ChargeContext:
    """One order's fills, as a single context priced at its average.

    Commission is charged on the order's value, and an order that filled in
    three parcels has one value. The quantity is summed and the price is the
    value-weighted average, so ``quantity x price`` reproduces the order's
    value exactly for a ``TRADE_VALUE`` row and the contract count exactly for
    a ``PER_CONTRACT`` row.
    """
    first = group[0]
    quantity = sum(c.quantity for c in group)
    if quantity == 0:  # pragma: no cover - a zero-quantity fill is refused upstream
        return replace(first, ts=stamp)
    weighted = sum((Decimal(c.quantity) * c.price for c in group), _ZERO)
    return replace(first, quantity=quantity,
                   price=weighted / Decimal(quantity), ts=stamp,
                   fill_id=None)
