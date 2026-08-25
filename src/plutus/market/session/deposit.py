"""The segregated derivatives deposit, and account-level margin. Locked shape 5.

**There is no maintenance margin ratio in Vietnam, at any date in 2020-2026.**
Read that again before writing anything in this module, because
:class:`plutus.market.margin.MarginConfig` has a ``maintenance_rate`` field and
someone will copy it. It models a quantity that does not exist. The rulebook is
flat on the point (6.3, "The actual call test"): VSDC publishes no maintenance
ratio and instead monitors, in real time and per investor account, the ratio

    utilisation = MR / total value of valid margin assets

against a three-level ladder. A "maintenance ratio" written as a fraction of
notional is a different mechanism that mis-times calls in both directions --
a draft of the design spec paired initial 0.13 with maintenance 0.10, which
fires at utilisation 1.30, i.e. an 8.89% adverse move, which the +/-7% VN30F
band makes unreachable in a single session. Two correctly-cited numbers still
produce a wrong rule when the mechanism between them is invented. If you find
yourself adding a maintenance rate here, the shape is wrong.

**The margin entry point takes the whole account.**
:func:`account_margin_requirement` takes a :class:`DerivativesAccount` and
raises ``TypeError`` on anything else, including a
:class:`plutus.market.protocol.Position`. That is not defensiveness for its own
sake: rulebook 6.3 records that "the regulated unit of assessment is the
ACCOUNT PORTFOLIO -- not the position. A two-leg calendar spread on one account
is *one* MR calculation, not two independent ones." A function that takes a
lone position cannot express netting, cannot express the loss-only rule (which
is stated over the account portfolio's P&L), and cannot be upgraded to
portfolio margining without re-plumbing every call site.

**The test this module implements**, all four terms sourced (rulebook 6.3):

    IM  = ratio x contracts x price x multiplier, summed over the account.
          ``ratio`` is VSDC's dated initial-margin series (10% from
          2017-08-10, 13% from 2018-07-18, 17% from 2022-12-15) and ``price``
          is the latest matched price in-session or the daily settlement price
          at end of day -- **the current price, never the entry notional**.
          Offsetting trades on the same trading account attract no new IM
          ("giao dich doi ung cua cung mot tai khoan giao dich"), which is why
          :class:`ContractLedger` is net-signed and why
          :meth:`DerivativesAccount.reserve_for_order` charges the *increment*.
    VM  = variation margin, counted **only** when the account portfolio's P&L
          is in a loss state. VSDC verbatim: "Gia tri ky quy bien doi **chi
          duoc tinh vao** gia tri ky quy duy tri yeu cau trong truong hop lai
          lo vi the cua danh muc dau tu tren tai khoan cua nha dau tu **o
          trang thai lo**". A favourable move contributes exactly zero.
    MR  = IM + VM.
    utilisation = MR / deposit assets, tested against
          :class:`plutus.market.broker.BrokerTerms`' warning / call /
          forced-close ladder. The ladder's *shape* (80/90/100) is VSDC-sourced
          (Article 13 of the clearing rulebook); each broker's own levels are
          commercial terms and live in ``BrokerTerms``.

**The deposit is segregated.** Vietnamese derivatives margin sits in a deposit
account ("ky quy") opened by the clearing member in its own name, with margin
cash ultimately held at VSD via the settlement bank -- not in the securities
cash account (rulebook 6.3, "Where margin is held; segregation"). The two pools
have independent purchasing power and **no auto-transfer exists**: the caller
moves cash across explicitly and a margin call resolves against the deposit
only. If the deposit is short, the futures position is force-liquidated and
securities cash is untouched. Nothing in this module can reach securities cash;
that is the segregation, expressed as an import boundary.

**What this module deliberately does not do.** It does not run strategy P&L,
hold a portfolio, or execute a forced liquidation. It reports the margin
consequence of prices and positions; the caller decides what to do about it.
The one place derivative P&L touches the deposit is when a position is *closed*
or *expires* -- see :meth:`DerivativesAccount.apply_fill` for why that is a
margin-correctness requirement rather than P&L accounting sneaking in.

Import boundary (interface contract section 1): this module may import
``types``, ``calendar``, ``rulebook``, ``margin`` and ``broker``, and must not
import ``orders``, ``ledgers`` or ``exchange``. ``rulebook.py`` and
``calendar.py`` do not exist yet and ``ledgers.py`` is forbidden, so the three
collaborators arrive through the structural :class:`typing.Protocol` classes
below. They are protocols, not copies: when the real modules land, the real
``RuleSet``, ``TradingCalendar`` and ``EncumbranceLedger`` satisfy them
structurally and not one line here changes.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import (Any, Dict, Mapping, Optional, Protocol, Sequence, Tuple,
                    Union)

from plutus.market.broker import BrokerTerms
from plutus.market.margin import vsd_initial_margin
from plutus.market.protocol import Order
from plutus.market.session.types import (AccountRef, BrokerProfile,
                                         ContractPosition, Encumbrance, Fill,
                                         InvestorClass, LiquidationRule,
                                         MarginStatus, MarginView, OrderId,
                                         OrderRecord, Pool, Rejected,
                                         RejectionRule, ResourceKind,
                                         StatefulRule, Transferred, Venue,
                                         signed_quantity)

__all__ = [
    # collaborator protocols
    'EncumbranceLedgerLike', 'RuleSetLike', 'TradingCalendarLike',
    # records
    'DepositEntry', 'FillEffect',
    # the ledgers
    'ContractLedger', 'DerivativesAccount',
    # the margin test
    'account_margin_requirement', 'margin_status', 'resolve_initial_margin_rate',
    # the call state machine
    'MarginMonitor', 'liquidation_sequence',
    # constants
    'DEPOSIT_REJECTIONS', 'VN30F_MULTIPLIER',
]


#: VN30 (and, from 2025-10-10, VN100) index futures: 100,000 VND per index
#: point. Rulebook 9.3, "VN30F contract size and multiplier", confidence high,
#: sourced to HNX's published contract template in both editions.
#:
#: This is a **default, not a universal**. Government-bond futures on the same
#: venue carry multiplier 10,000 on a 100,000d face and are quoted in dong
#: rather than index points, so a per-venue multiplier is wrong by construction
#: -- the rulebook flags exactly this as a unit hazard (9.2, "unit hazard"), and
#: ``CURRENCY_UNIT['HNXDS'] = 1`` must never be applied as a multiplier here.
#: Anything that is not a VN30/VN100 index future must be given its multiplier
#: explicitly through ``DerivativesAccount(multipliers=...)``.
VN30F_MULTIPLIER = Decimal('100000')

_ZERO = Decimal('0')


# --------------------------------------------------------------------------
# Collaborators, as structural protocols
# --------------------------------------------------------------------------

class RuleSetLike(Protocol):
    """The slice of ``rulebook.RuleSet`` this module reads.

    Only two dated values are needed on the derivatives side, and both are
    resolved at the instant the ``RuleSet`` was obtained for -- locked shape 1.
    Nothing here caches a rate, and no rate is read at import time.
    """

    ts: datetime

    def initial_margin_rate(self, contract_code: str) -> Decimal:
        """VSDC's dated initial-margin ratio for one listed contract."""

    def position_limit(self, contract_code: str,
                       investor: InvestorClass) -> Optional[int]:
        """Net position cap in contracts, or ``None`` where none applies."""


class TradingCalendarLike(Protocol):
    """The slice of ``calendar.TradingCalendar`` a cure window needs.

    A cure window is measured in **sessions**, not in settlement business days
    -- the two calendars diverge around Tet and only one of them is the right
    one here. See :meth:`MarginMonitor.on_mark`.
    """

    def next_session_open(self, ts: datetime, venue: Venue,
                          rules: Any) -> datetime:
        """The instant the next session opens on ``venue``."""


class EncumbranceLedgerLike(Protocol):
    """The slice of ``ledgers.EncumbranceLedger`` the deposit reserves through.

    Taken as a constructor argument rather than imported, because
    ``deposit.py`` must not import ``ledgers.py`` (interface contract section
    1) and because locked shape 2 wants **one** reservation ledger across both
    pools: invariant 4 -- the sum of encumbrance over live orders equals the
    ledgers' committed totals -- is only checkable if the deposit's reservations
    live in the same book as the securities pool's.
    """

    def take(self, order_id: OrderId, pool: Pool, resource: ResourceKind,
             ts: datetime, *, amount: Decimal = _ZERO, quantity: int = 0,
             ticker: Optional[str] = None,
             estimated_charges: Decimal = _ZERO) -> Encumbrance:
        """Reserve on accept."""

    def consume(self, order_id: OrderId, ts: datetime, *,
                resource: ResourceKind, amount: Decimal = _ZERO,
                quantity: int = 0) -> Optional[Encumbrance]:
        """Pro-rata release at a fill."""

    def release(self, order_id: OrderId, ts: datetime, *,
                resource: Optional[ResourceKind] = None
                ) -> Tuple[Encumbrance, ...]:
        """Full release, on every terminal transition."""

    def outstanding(self, *, pool: Optional[Pool] = None,
                    resource: Optional[ResourceKind] = None,
                    ticker: Optional[str] = None) -> Decimal:
        """Sum of reserved amount over live orders."""


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DepositEntry:
    """One movement of the deposit balance, with the balance it produced.

    The deposit is the only asset the margin test is measured against, so
    "how did the balance get here" has to be answerable. Design section 7.4
    requires a ``ForcedLiquidation`` to state "the resulting deposit balance";
    that is not reportable from a scalar that was mutated in place.

    ``amount`` is signed: positive credits the deposit, negative debits it.
    """

    ts: datetime
    amount: Decimal
    reason: str
    balance_after: Decimal


@dataclass(frozen=True)
class FillEffect:
    """What one derivative fill did to the deposit account.

    Returned by :meth:`DerivativesAccount.apply_fill` rather than nothing,
    because all three numbers are needed by the caller and none of them is
    recoverable afterwards: the position is the *new* net (or ``None`` if the
    fill flattened it), ``realised`` has already left or entered the deposit,
    and ``released_margin`` is the order-margin encumbrance that became posted
    margin at this fill.
    """

    position: Optional[ContractPosition]
    realised: Decimal
    released_margin: Decimal


# --------------------------------------------------------------------------
# The contract ledger -- net-signed, one row per contract
# --------------------------------------------------------------------------

class ContractLedger:
    """``{contract_code: ContractPosition}``, net-signed. Where shorts live.

    Locked shape 5's forbidden build is a table of per-position rows. It is
    forbidden because a long and a short in the same contract on the same
    account are **one** position to VSDC, and rulebook 6.3 is explicit that
    offsetting trades on the same trading account attract no new initial
    margin. Per-position rows cannot express that: they would charge IM twice
    on a position that carries no risk.

    A flat contract is **removed**, never stored as a zero, so
    :meth:`positions` never shows a contract the account does not hold.

    This is also the only place a short exists in this package. A SELL on an
    HNXDS symbol opens or increases a short and is never checked against
    holdings; a SELL on an equity venue requires settled holdings, because
    Vietnamese cash equity permits no short selling at any date in the window.
    """

    def __init__(self) -> None:
        self._rows: Dict[str, ContractPosition] = {}

    # -- reads ----------------------------------------------------------

    def position(self, contract_code: str) -> Optional[ContractPosition]:
        """The net position in one contract, or ``None`` when flat."""
        return self._rows.get(contract_code)

    def positions(self) -> Dict[str, ContractPosition]:
        """Every contract held. Flat contracts are absent, not zero."""
        return dict(self._rows)

    def net_quantity(self, contract_code: str) -> int:
        """Signed net. Positive long, negative short, zero when not held.

        A position limit is tested against ``abs()`` of this, because rulebook
        6.4's cap is on the **net** position on one trading account, not on
        gross turnover.
        """
        row = self._rows.get(contract_code)
        return row.net_quantity if row is not None else 0

    def total_contracts(self) -> int:
        """Sum of ``|net|`` over every contract held."""
        return sum(row.abs_quantity for row in self._rows.values())

    # -- writes ---------------------------------------------------------

    def apply_fill(self, fill: Fill, multiplier: Decimal,
                   expiry: Optional[date] = None) -> Optional[ContractPosition]:
        """Resolve open / close / net on one fill.

        Signing goes through :func:`~plutus.market.session.types.signed_quantity`
        and never through ``Side.sign``, which returns ``None`` on
        ``Side.CROSS`` -- a net-signed position computed through that path would
        be silently corrupt rather than loudly wrong.

        Three cases, and the third is the one a naive build gets wrong:

        * **Opening or increasing** in the same direction: ``average_entry``
          becomes the quantity-weighted mean.
        * **Reducing** without crossing: ``average_entry`` is unchanged. The
          remaining contracts were bought at the old average and closing some
          of them does not re-price the rest.
        * **Crossing through flat** (long 2, sell 5 -> short 3):
          ``average_entry`` **resets to the fill price**. The old average
          belongs to a position that no longer exists, and carrying it forward
          would price a short off a long's entry.

        A fill that flattens the position removes the row and returns ``None``.

        Returns:
            The new net position, or ``None`` if the fill flattened it.
        """
        code = fill.ticker
        signed = signed_quantity(fill.side, fill.quantity)
        existing = self._rows.get(code)
        old_net = existing.net_quantity if existing is not None else 0
        new_net = old_net + signed

        if new_net == 0:
            self._rows.pop(code, None)
            return None

        if old_net == 0 or (old_net > 0) != (new_net > 0):
            # Opened from flat, or crossed through it. Either way the position
            # that the old average described is gone.
            average = fill.price
            opened_at = fill.ts
        elif abs(new_net) > abs(old_net):
            assert existing is not None      # abs grew, so a row existed
            total = (Decimal(abs(old_net)) * existing.average_entry
                     + Decimal(fill.quantity) * fill.price)
            average = total / Decimal(abs(new_net))
            opened_at = existing.opened_at
        else:
            assert existing is not None      # reducing implies a row existed
            average = existing.average_entry
            opened_at = existing.opened_at

        row = ContractPosition(
            contract_code=code,
            net_quantity=new_net,
            average_entry=average,
            multiplier=multiplier,
            expiry=expiry if expiry is not None
            else (existing.expiry if existing is not None else None),
            opened_at=opened_at,
            updated_at=fill.ts,
        )
        self._rows[code] = row
        return row

    def remove(self, contract_code: str) -> Optional[ContractPosition]:
        """Drop a contract. Expiry settlement removes it from the ledger."""
        return self._rows.pop(contract_code, None)


# --------------------------------------------------------------------------
# The margin test
# --------------------------------------------------------------------------

def resolve_initial_margin_rate(rules: Optional[RuleSetLike],
                                contract_code: str,
                                ts: datetime) -> Decimal:
    """VSDC's initial-margin ratio for one contract at one instant.

    Prefers the ``RuleSet``, which resolves per ``(contract_code, ts)`` --
    VSDC publishes the ratio as a table keyed on each individual listed
    contract and re-determines it on the 1st, 10th and 20th of each month, so
    the ratio is capable of differing across expiries of the same product even
    though every entry has been 17% since 2022-12-15.

    Falls back to :func:`plutus.market.margin.vsd_initial_margin`, the dated
    date-keyed series that already exists, when no ``RuleSet`` is supplied.
    That fallback is date-only and therefore coarser than the published data
    structure; it is correct at every date sampled in 2020-2026 and is the
    aggregation of an existing primitive rather than a second copy of the
    series. **0.175 matches no source at any date** -- it is a transcription
    slip for 0.17 -- and neither path can produce it.
    """
    if rules is not None:
        return rules.initial_margin_rate(contract_code)
    return vsd_initial_margin(ts.date())


def margin_status(required: Decimal, assets: Decimal,
                  terms: BrokerTerms) -> MarginStatus:
    """Where ``MR / assets`` sits on the broker's utilisation ladder.

    Four states rather than one call boolean, because the ladder is genuinely
    three-tiered: rulebook 6.3, Article 13 of the clearing rulebook, sets
    level 1 = 80%, level 2 = 90%, level 3 = 100% on utilisation, monitored per
    investor account during the session. Only level 3 carries an
    exchange-level suspension; levels 1 and 2 are notices.

    Two boundary cases, decided rather than left to arithmetic:

    * **No requirement is ``OK``**, whatever the assets. An account with no
      positions and no resting orders is not in breach for holding no deposit.
    * **A requirement with no assets is ``FORCED``**, not an undefined ratio.
      ``MarginView.utilisation`` returns ``None`` there (never ``NaN``, which
      would raise at ``json_safe`` time), and ``None`` must not read as "fine".
    """
    if required <= 0:
        return MarginStatus.OK
    if assets <= 0:
        return MarginStatus.FORCED
    utilisation = required / assets
    if utilisation >= terms.forced_close_utilisation:
        return MarginStatus.FORCED
    if utilisation >= terms.margin_call_utilisation:
        return MarginStatus.CALL
    if utilisation >= terms.warning_utilisation:
        return MarginStatus.WARNING
    return MarginStatus.OK


def account_margin_requirement(account: 'DerivativesAccount',
                               marks: Mapping[str, Decimal],
                               rules: Optional[RuleSetLike],
                               terms: BrokerTerms,
                               ts: datetime,
                               *,
                               resting: Sequence[OrderRecord] = (),
                               ) -> MarginView:
    """**The** margin entry point. Takes the whole account, never a position.

    Locked shape 5. ``TypeError`` on anything that is not a
    :class:`DerivativesAccount` -- including a
    :class:`plutus.market.protocol.Position`, which is what a caller reaching
    for the legacy per-position path would pass. The check is deliberate: the
    regulated unit of assessment is the account portfolio (rulebook 6.3), and a
    signature that accepts one position invites a build that sums independent
    per-position requirements and can never be upgraded to portfolio margining
    without touching every call site.

    The four separately-testable facts in the computation below:

    1. **IM is recomputed on the current price**, not on entry notional, so the
       requirement moves with the market independently of P&L. ``price`` is the
       latest matched price in-session or the daily settlement price at end of
       day (rulebook 6.3, "IM -- definition and formula").
    2. **VM is loss-only and account-level.** The portfolio's P&L since the
       variation-margin reference is netted across contracts; only a net loss
       enters ``MR``. A favourable move contributes exactly zero and does not
       relieve the requirement -- "a symmetric equity/notional model mis-times
       calls in both directions" (rulebook 6.3).
    3. **Assets are the deposit balance**, with no mark-to-market accumulated
       into it: derivatives are cash-settled and the daily P&L leaves or enters
       as cash on T+1, which Tier 1 does not model. The loss is carried in VM
       instead of being deducted from assets, which is why doing both would
       double-count it.
    4. **The thresholds come from** :class:`~plutus.market.broker.BrokerTerms`,
       never from this module. Their *levels* are commercial and unpublished;
       only the ladder's shape is sourced.

    The mark for a contract is resolved ``marks`` -> the account's last
    observed mark -> the position's own ``average_entry``. The last fallback is
    not a default masquerading as data: ``average_entry`` is the last price at
    which this account actually traded that contract, which is precisely "the
    latest matched price" for an account that has traded and not yet been
    marked. :meth:`DerivativesAccount.settle_daily` is the strict path and
    refuses a missing settlement price outright.

    **Tier 1 sums strict per-contract IM and takes no spread credit.** Netting
    *within* a contract is required and implemented (it is what
    ``ContractLedger`` being net-signed buys); netting *across* contracts is
    portfolio margining, whose formula lives in VSDC's unpublished Phu luc 02
    and is marked UNVERIFIED in the rulebook. Summing over-charges and never
    under-charges, which is the conservative direction. Because this function
    takes the account, the netting engine slots in here alone when the formula
    is obtained.

    Args:
        account: the whole derivatives account.
        marks: current price per contract code, in the contract's own quoted
            units (index points for VN30F, dong for GB futures).
        rules: the ``RuleSet`` at ``ts``, or ``None`` to fall back to
            :func:`plutus.market.margin.vsd_initial_margin`.
        terms: the broker's utilisation ladder.
        ts: the instant being marked.
        resting: the caller's live derivative orders. When given it is
            authoritative for resting-order margin; when omitted the
            encumbrance ledger is asked instead. Section 12 invariant 4 says
            the two agree, and passing the records is how a caller checks that.

    Returns:
        A :class:`MarginView` whose ``cure_by`` is always ``None`` -- a cure
        deadline is state carried across days by :class:`MarginMonitor`, not a
        property of one mark.
    """
    if not isinstance(account, DerivativesAccount):
        raise TypeError(
            f'account_margin_requirement takes the whole DerivativesAccount, '
            f'got {type(account).__name__}. Locked shape 5: the regulated unit '
            f'of assessment is the account portfolio, not the position '
            f'(rulebook 6.3). A per-position margin function cannot express '
            f'netting or the loss-only variation-margin rule; if you have a '
            f'lone Position, the batch research path in plutus.market.margin '
            f'is what you want, and it is deliberately not this.'
        )

    initial = _ZERO
    portfolio_pnl = _ZERO
    for code, position in account.contracts.positions().items():
        price = account.mark_for(code, marks)
        rate = resolve_initial_margin_rate(rules, code, ts) + account.margin_buffer
        initial += rate * position.notional(price)
        reference = account.variation_reference(code)
        portfolio_pnl += (Decimal(position.net_quantity) * position.multiplier
                          * (price - reference))

    # The loss-only rule, and the entire reason VM is not just "-P&L". An
    # account in profit posts the same MR as an account exactly flat.
    variation = -portfolio_pnl if portfolio_pnl < 0 else _ZERO

    if resting:
        resting_margin = sum((r.encumbered_deposit for r in resting), _ZERO)
    else:
        resting_margin = account.resting_order_margin()

    balance = account.deposit_balance
    required = initial + resting_margin + variation
    return MarginView(
        initial_margin=initial + resting_margin,
        variation_margin=variation,
        deposit_balance=balance,
        posted_margin=initial,
        resting_order_margin=resting_margin,
        status=margin_status(required, balance, terms),
        as_of=ts,
        cure_by=None,
    )


# --------------------------------------------------------------------------
# The account
# --------------------------------------------------------------------------

class DerivativesAccount:
    """The segregated deposit, its contract ledger, and the margin view.

    Segregation is structural here, not a convention: this object holds a
    balance that only :meth:`transfer_in`, :meth:`transfer_out`,
    :meth:`credit`, :meth:`debit` and position close-out can move, and it has
    no reference of any kind to securities cash. **No auto-transfer exists in
    Vietnam** (rulebook 6.3, "Where margin is held; segregation"), so a caller
    that lets the deposit run short and expects the securities balance to cover
    it gets a forced liquidation, which is the real behaviour.

    A transfer arrives **immediately** during trading hours. That is an adopted
    assumption, stated in design section 16, not a sourced fact: intra-day
    transfer timing is not modelled.

    **The deposit does not accumulate mark-to-market.** Daily P&L on a
    cash-settled future leaves or enters as cash on T+1, which Tier 1 does not
    model, and the adverse half of it is already carried in ``MR`` as variation
    margin. Deducting it from the balance as well would double-count it. What
    *does* move the balance is realising a position: see :meth:`apply_fill`.

    ``posted_margin`` in the resulting :class:`MarginView` is recomputed from
    the current marks, not stored. It is "the requirement attributable to open
    positions right now", which is what IM means once IM is recomputed on the
    current price; a stored figure would drift from the requirement it is meant
    to cover within one bar.
    """

    def __init__(self,
                 ref: AccountRef,
                 initial_deposit: Decimal,
                 terms: BrokerTerms,
                 encumbrances: EncumbranceLedgerLike,
                 contracts: ContractLedger,
                 *,
                 investor: InvestorClass = InvestorClass.INDIVIDUAL,
                 margin_buffer: Decimal = _ZERO,
                 multipliers: Optional[Mapping[str, Decimal]] = None,
                 expiries: Optional[Mapping[str, date]] = None,
                 default_multiplier: Decimal = VN30F_MULTIPLIER,
                 opened_at: Optional[datetime] = None) -> None:
        """
        Args:
            ref: must name :attr:`Pool.DERIVATIVES`. A securities ``AccountRef``
                here would be the segregation breach this class exists to
                prevent, so it is refused rather than coerced.
            initial_deposit: opening balance, from ``AccountsConfig``.
            terms: the broker's ladder and cure window.
            encumbrances: the **shared** reservation ledger. Shared so that
                invariant 4 spans both pools; see
                :class:`EncumbranceLedgerLike`.
            contracts: the net-signed position ledger.
            investor: which position-limit tier rulebook 6.4 puts this account
                in. Tier 1 never asks the caller and runs ``INDIVIDUAL``.
            margin_buffer: the broker's percentage-of-notional add-on above
                VSDC's ratio. A plausible *shape* only -- rulebook 6.3 records
                that "the broker's actual lever in Vietnam is its UTILISATION
                thresholds", which are the three ``BrokerTerms`` fields.
            multipliers: contract code -> multiplier. Required for anything
                that is not a VN30/VN100 index future; see
                :data:`VN30F_MULTIPLIER`.
            expiries: contract code -> last trading day, carried onto
                :class:`ContractPosition` so an expiring contract is
                identifiable without a second lookup.
        """
        if ref.pool is not Pool.DERIVATIVES:
            raise ValueError(
                f'DerivativesAccount needs a derivatives AccountRef, got pool '
                f'{ref.pool.value!r}. The two pools are segregated in '
                f'Vietnamese law, not merely partitioned here: margin cash is '
                f'held at VSD via the settlement bank and cannot be reached '
                f'from the securities account.'
            )
        if initial_deposit < 0:
            raise ValueError(
                f'initial_deposit must not be negative, got {initial_deposit}')

        self.ref = ref
        self.terms = terms
        self.investor = investor
        self.margin_buffer = margin_buffer
        self.contracts = contracts

        self._encumbrances = encumbrances
        self._multipliers: Dict[str, Decimal] = dict(multipliers or {})
        self._expiries: Dict[str, date] = dict(expiries or {})
        self._default_multiplier = default_multiplier

        self._balance = initial_deposit
        self._entries: Tuple[DepositEntry, ...] = ()
        if initial_deposit > 0:
            stamp = opened_at or datetime.min
            self._entries = (DepositEntry(ts=stamp, amount=initial_deposit,
                                          reason='opening deposit',
                                          balance_after=initial_deposit),)

        #: Latest observed price per contract. Seeded by fills (a fill price
        #: *is* a matched price) and refreshed by ``observe_marks``.
        self._marks: Dict[str, Decimal] = {}
        #: The variation-margin baseline per contract: the previous daily
        #: settlement price once one exists, and the position's own opening
        #: price until then. Both readings are VSDC's, per contract:
        #: "the in-session updated trade price versus the previous trading
        #: day's DSP (for carried positions) or versus the position's opening
        #: settlement price (for positions opened during the day)".
        self._settlement_reference: Dict[str, Decimal] = {}
        #: Live derivative orders this account has reserved for.
        self._live_orders: Dict[OrderId, _LiveOrder] = {}

    # -- reads ----------------------------------------------------------

    @property
    def deposit_balance(self) -> Decimal:
        """Margin assets: the deposit balance, and nothing else.

        Securities cash is not an asset of this test. Rulebook 6.3 admits cash
        and a restricted list of securities as valid margin assets, with
        haircuts VSDC does not publish (marked UNVERIFIED) and a cash-share
        floor; Tier 1 models cash-only margin, which is what the great majority
        of retail derivatives accounts post anyway.
        """
        return self._balance

    @property
    def entries(self) -> Tuple[DepositEntry, ...]:
        """Every movement of the balance, oldest first."""
        return self._entries

    def positions(self) -> Dict[str, ContractPosition]:
        """``session.positions()``. Flat contracts are absent, not zero."""
        return self.contracts.positions()

    def position(self, contract_code: str) -> Optional[ContractPosition]:
        """The net position in one contract, or ``None`` when flat."""
        return self.contracts.position(contract_code)

    def multiplier_for(self, contract_code: str) -> Decimal:
        """The contract multiplier. Explicit map first, VN30F default after."""
        held = self.contracts.position(contract_code)
        if contract_code in self._multipliers:
            return self._multipliers[contract_code]
        if held is not None:
            return held.multiplier
        return self._default_multiplier

    def mark_for(self, contract_code: str,
                 marks: Optional[Mapping[str, Decimal]] = None) -> Decimal:
        """The price IM is computed on: supplied mark, last mark, then entry.

        The fallback chain is stated in
        :func:`account_margin_requirement`; the short version is that every
        link is a matched price for this contract, so none of them is a
        silent default.

        Raises:
            KeyError: for a contract that is neither held nor marked, where
                there is genuinely no price to fall back to.
        """
        price = marks.get(contract_code) if marks else None
        if price is None:
            price = self._marks.get(contract_code)
        if price is None:
            held = self.contracts.position(contract_code)
            price = held.average_entry if held is not None else None
        if price is None:
            raise KeyError(
                f'no price for {contract_code}: it is not held and no mark has '
                f'been observed, so there is nothing to compute a requirement '
                f'on. Pass it in `marks` or call observe_marks() first.')
        return price

    def variation_reference(self, contract_code: str) -> Decimal:
        """The baseline the account's P&L is measured from, for VM.

        The previous daily settlement price once :meth:`settle_daily` has run,
        and the position's own ``average_entry`` before that. Both are VSDC's
        stated baselines -- carried positions mark against the previous day's
        DSP, positions opened during the day mark against their own opening
        price -- and which one applies is exactly whether the position has
        lived through a settlement.
        """
        reference = self._settlement_reference.get(contract_code)
        if reference is not None:
            return reference
        held = self.contracts.position(contract_code)
        if held is None:
            raise KeyError(
                f'no variation-margin reference for {contract_code}: it is '
                f'neither held nor settled')
        return held.average_entry

    def resting_order_margin(self) -> Decimal:
        """Deposit reserved by live derivative orders.

        Resting derivative orders must contribute to ``MR``, or a caller can
        rest futures orders it cannot fund and discover the shortfall only when
        they fill.
        """
        return self._encumbrances.outstanding(pool=Pool.DERIVATIVES,
                                              resource=ResourceKind.DEPOSIT)

    def margin(self, marks: Mapping[str, Decimal],
               rules: Optional[RuleSetLike],
               terms: BrokerTerms,
               ts: datetime,
               *,
               resting: Sequence[OrderRecord] = ()) -> MarginView:
        """``session.margin()``. Delegates to :func:`account_margin_requirement`.

        A pure read: it does not update the mark cache, so two callers asking
        the same question at the same instant get the same answer regardless of
        order. Use :meth:`observe_marks` to move the cache forward.
        """
        return account_margin_requirement(self, marks, rules, terms, ts,
                                          resting=resting)

    # -- cash ------------------------------------------------------------

    def credit(self, amount: Decimal, ts: datetime, reason: str) -> Decimal:
        """Add to the deposit. Returns the new balance."""
        if amount < 0:
            raise ValueError(f'credit takes a positive amount, got {amount}; '
                             f'use debit() to take cash out')
        return self._move(amount, ts, reason)

    def debit(self, amount: Decimal, ts: datetime, reason: str) -> Decimal:
        """Take from the deposit. Returns the new balance.

        Deliberately **not** bounded by ``free_deposit``: a VSDC collateral
        management fee or a realised loss is levied whether or not it leaves
        the account adequately margined, and hiding that would hide exactly the
        margin call the caller needs to see. :meth:`transfer_out` is the
        bounded path.
        """
        if amount < 0:
            raise ValueError(f'debit takes a positive amount, got {amount}; '
                             f'use credit() to put cash in')
        return self._move(-amount, ts, reason)

    def transfer_in(self, amount: Decimal, ts: datetime) -> Transferred:
        """The deposit leg of a securities -> deposit transfer.

        The securities leg is ``ledgers.py``'s and the two are wired together
        by ``exchange.py``; **no auto-transfer exists**, so this is only ever
        reached from an explicit ``session.transfer()``. The transfer arrives
        immediately -- an adopted assumption, see the class docstring.
        """
        if amount <= 0:
            raise ValueError(f'a transfer must move a positive amount, got '
                             f'{amount}')
        self._move(amount, ts, 'transfer in from securities')
        return Transferred(source=Pool.SECURITIES, destination=Pool.DERIVATIVES,
                           amount=amount, ts=ts)

    def transfer_out(self, amount: Decimal, marks: Mapping[str, Decimal],
                     rules: Optional[RuleSetLike], ts: datetime,
                     *, terms: Optional[BrokerTerms] = None,
                     resting: Sequence[OrderRecord] = ()
                     ) -> Union[Transferred, Rejected]:
        """The deposit leg of a deposit -> securities transfer.

        Bounded by ``free_deposit = balance - posted - resting-order margin``,
        which is what stops a caller withdrawing the margin backing an open
        position. Short -> ``Rejected(INSUFFICIENT_DEPOSIT)`` carrying
        ``free_deposit`` as the binding constraint, per the interface
        contract's per-rule table.

        **A known tightening, not implemented.** Rulebook 6.3 ("Margin
        withdrawal", VSDC section VI) puts the investor-level test at *assets
        minus the required maintenance value*, i.e. assets minus ``MR``, "not
        assets minus IM". The difference is exactly ``VM``, so ``free_deposit``
        is an upper bound on the truly withdrawable amount and is loose by the
        unrealised loss whenever the account is in loss. ``MarginView.equity``
        is that stricter figure and is reported in ``detail`` on a rejection so
        the gap is visible rather than silent.
        """
        if amount <= 0:
            raise ValueError(f'a transfer must move a positive amount, got '
                             f'{amount}')
        view = self.margin(marks, rules,
                           terms if terms is not None else self.terms, ts,
                           resting=resting)
        if amount > view.free_deposit:
            return Rejected(
                rule=StatefulRule.INSUFFICIENT_DEPOSIT,
                binding_constraint=view.free_deposit,
                ts=ts,
                detail={'requested': amount,
                        'free_deposit': view.free_deposit,
                        'deposit_balance': view.deposit_balance,
                        'posted_margin': view.posted_margin,
                        'resting_order_margin': view.resting_order_margin,
                        'equity': view.equity,
                        'pool': Pool.DERIVATIVES},
            )
        self._move(-amount, ts, 'transfer out to securities')
        return Transferred(source=Pool.DERIVATIVES,
                           destination=Pool.SECURITIES, amount=amount, ts=ts)

    # -- marks -----------------------------------------------------------

    def observe_marks(self, marks: Mapping[str, Decimal],
                      ts: datetime) -> None:
        """Record the latest matched prices. Does not move the VM baseline.

        In-session IM is computed on "the latest matched price at the moment of
        calculation", which is what this cache holds. The variation-margin
        baseline is a *daily* quantity and only :meth:`settle_daily` moves it.
        """
        for code, price in marks.items():
            if price is not None:
                self._marks[code] = price

    def settle_daily(self, settlements: Mapping[str, Decimal],
                     ts: datetime) -> None:
        """Roll the variation-margin baseline to the day's settlement prices.

        **Strict**: every held contract must have a settlement price. Falling
        back here would silently re-baseline a position to its own stale mark
        and make the next day's VM read zero on a day the account actually
        lost, which is the failure mode the loss-only rule exists to catch.

        **No cash moves.** The deposit does not accumulate mark-to-market; see
        the class docstring. The day's adverse move stays in ``MR`` as VM until
        the position is realised.

        Raises:
            KeyError: naming every held contract with no settlement price.
        """
        held = self.contracts.positions()
        missing = sorted(code for code in held if settlements.get(code) is None)
        if missing:
            raise KeyError(
                f'no daily settlement price for {missing}; a margin '
                f'requirement cannot be evaluated without one and defaulting '
                f'would understate it')
        for code in held:
            price = settlements[code]
            self._settlement_reference[code] = price
            self._marks[code] = price

    # -- orders ----------------------------------------------------------

    def reserve_for_order(self, order_id: OrderId, order: Order,
                          price: Decimal, rules: Optional[RuleSetLike],
                          profile: Optional[BrokerProfile], ts: datetime,
                          ) -> Union[Encumbrance, Rejected]:
        """Reserve deposit margin for a resting derivative order.

        Three tests, in this order, each with its own rule so the rejection log
        stays countable:

        1. **Position limit** (rulebook 6.4). Tested against the *worst-case*
           net the account could reach if its live orders filled --
           ``max(|net + all buys|, |net - all sells|)`` -- not against the
           signed sum, because a resting sell that never fills must not create
           room for a buy that then breaches the cap. Conservative by
           construction, and the conservative direction is the right one for a
           cap. Rejected with ``binding_constraint`` = the cap.
        2. **Level 3** (rulebook 6.3, VSDC section V.4): "a trading account may
           open a **new** position only while its utilisation is below the
           level-3 threshold", with offsetting trades excepted. An order that
           reduces the worst-case net is an offsetting trade and passes.
        3. **Free deposit**. Rejected with ``binding_constraint`` =
           ``free_deposit``.

        **The margin charged is the increment, not the gross.** Rulebook 6.3
        is explicit that offsetting trades on the same trading account attract
        no new initial margin, so the amount reserved is the IM the order would
        *add*: ``rate x (worst-case net after - worst-case net before) x
        multiplier x price``. An order that closes a position reserves zero and
        gets a zero-amount encumbrance -- a reservation of nothing, which is
        the honest record of a resource that was not consumed. One consequence
        worth knowing: incremental margining is order-dependent, so of two
        orders that together breach nothing, the first to arrive pays.

        Args:
            price: the price to margin at -- the limit price for a limit order,
                or the current mark for a market-family order. The caller
                chooses because only the caller knows which it submitted.
            profile: the ``BrokerProfile`` this account was configured with.
                Its ``margin_buffer`` must equal the account's, or the order
                would be margined at a different rate from the portfolio it
                joins; the mismatch raises rather than picking one.
        """
        if price <= 0:
            raise ValueError(
                f'cannot margin an order at price {price}; IM = ratio x '
                f'contracts x price x multiplier is undefined or zero')
        buffer_ = getattr(profile, 'margin_buffer', None)
        if buffer_ is not None and buffer_ != self.margin_buffer:
            raise ValueError(
                f'broker profile margin_buffer {buffer_} disagrees with the '
                f'account\'s {self.margin_buffer}; one order margined at a '
                f'different rate from the portfolio it joins makes '
                f'free_deposit incoherent')

        code = order.ticker
        signed = signed_quantity(order.side, order.quantity)
        before = self._worst_case_net(code)
        after = self._worst_case_net(code, extra_signed=signed)
        increment = after - before

        cap = (rules.position_limit(code, self.investor)
               if rules is not None else None)
        if cap is not None and after > cap:
            return Rejected(
                rule=StatefulRule.POSITION_LIMIT,
                binding_constraint=cap,
                ts=ts,
                order_id=order_id,
                detail={'net_quantity': self.contracts.net_quantity(code),
                        'prospective_net': after,
                        'investor_class': self.investor,
                        'contract_code': code},
            )

        # Marked on the account's own latest marks, deliberately not on this
        # order's price: an existing position is margined at the market, and
        # letting a new limit order re-price the portfolio it is joining would
        # let a caller manufacture free deposit with an absurd limit. The
        # caller is expected to have called observe_marks() for the interval.
        view = self.margin({}, rules, self.terms, ts)
        if increment > 0 and view.status is MarginStatus.FORCED:
            # Level 3 suspends the account from OPENING new positions. An
            # offsetting order -- increment == 0 -- is explicitly excepted, and
            # is in fact the action VSDC requires the member to take. The
            # threshold used is the *broker's* forced-close level, which is at
            # or tighter than VSDC's 100%: clearing members must be no looser.
            return Rejected(
                rule=StatefulRule.INSUFFICIENT_DEPOSIT,
                binding_constraint=view.free_deposit,
                ts=ts,
                order_id=order_id,
                detail={'reason': 'utilisation at or above the level-3 '
                                  'threshold; the account may not open a new '
                                  'position, only offset',
                        'utilisation': view.utilisation,
                        'required': view.required,
                        'deposit_balance': view.deposit_balance,
                        'contract_code': code},
            )

        rate = resolve_initial_margin_rate(rules, code, ts) + self.margin_buffer
        multiplier = self.multiplier_for(code)
        required = rate * Decimal(increment) * multiplier * price

        if required > view.free_deposit:
            return Rejected(
                rule=StatefulRule.INSUFFICIENT_DEPOSIT,
                binding_constraint=view.free_deposit,
                ts=ts,
                order_id=order_id,
                detail={'required': required,
                        'free_deposit': view.free_deposit,
                        'deposit_balance': view.deposit_balance,
                        'posted_margin': view.posted_margin,
                        'resting_order_margin': view.resting_order_margin,
                        'contract_code': code,
                        'pool': Pool.DERIVATIVES},
            )

        encumbrance = self._encumbrances.take(
            order_id, Pool.DERIVATIVES, ResourceKind.DEPOSIT, ts,
            amount=required, ticker=code)
        self._live_orders[order_id] = _LiveOrder(
            contract_code=code, signed_quantity=signed,
            remaining_quantity=order.quantity, remaining_margin=required)
        return encumbrance

    def release(self, order_id: OrderId, ts: datetime
                ) -> Tuple[Encumbrance, ...]:
        """The terminal hook, derivatives side.

        Wired to ``OrderBookOfRecord(on_terminal=...)`` by ``exchange.py``, so
        that every terminal edge -- filled, cancelled, expired, rejected, and
        the residue of a partially-filled order that then terminates --
        releases through one callback. Locked shape 2's "release on EVERY
        terminal transition" is then true by construction rather than by
        review. Idempotent: releasing an order this account never reserved for
        is a no-op, because the same callback fires for equity orders.
        """
        self._live_orders.pop(order_id, None)
        return self._encumbrances.release(order_id, ts,
                                          resource=ResourceKind.DEPOSIT)

    def apply_fill(self, fill: Fill, rules: Optional[RuleSetLike],
                   ts: Optional[datetime] = None) -> FillEffect:
        """Net the contract ledger, realise any close-out, convert order margin.

        Three effects, in this order:

        1. **Realise the closed portion into the deposit.** Closing quantity is
           marked from the variation-margin reference to the fill price and the
           result credits or debits the balance. This is *not* P&L accounting
           creeping in -- it is a margin-correctness requirement. Consider a
           long marked 100 points against it: ``VM`` carries the loss, so ``MR``
           is right. Close the position and ``VM`` vanishes with it; if the
           balance did not move, the account would show margin assets it does
           not have and the utilisation test would silently pass. Realising
           against the VM *reference* rather than against ``average_entry`` is
           what makes the two cancel exactly: the deposit is debited precisely
           the amount VM was charging for. The earlier P&L is the part that,
           per design section 7.4, already left as cash on T+1 -- a leg Tier 1
           does not model.
        2. **Net the contract ledger.** Offsetting reduces ``|net|`` and
           therefore reduces IM on the next mark, with no new initial margin
           charged, per rulebook 6.3.
        3. **Consume the order's margin encumbrance pro rata.** The filled
           portion is now an open position carrying posted margin, so leaving
           it reserved as order margin would count it twice. The final fill
           takes the residue exactly, so repeated division cannot leave a
           rounding crumb reserved forever.

        The fill price also becomes the contract's latest mark: a fill *is* a
        matched price, which is what in-session IM is computed on.
        """
        stamp = ts if ts is not None else fill.ts
        code = fill.ticker
        multiplier = self.multiplier_for(code)
        before = self.contracts.position(code)

        signed = signed_quantity(fill.side, fill.quantity)
        realised = _ZERO
        if before is not None and (before.net_quantity > 0) != (signed > 0):
            closed = min(abs(signed), before.abs_quantity)
            reference = self.variation_reference(code)
            direction = Decimal('1') if before.is_long else Decimal('-1')
            realised = (direction * Decimal(closed) * multiplier
                        * (fill.price - reference))

        position = self.contracts.apply_fill(
            fill, multiplier, self._expiries.get(code))
        self._marks[code] = fill.price
        if position is None:
            # Flat: the baseline described a position that no longer exists.
            self._settlement_reference.pop(code, None)

        if realised != 0:
            self._move(realised, stamp,
                       f'realised close-out on {code} at {fill.price}')

        released = self._consume_order_margin(fill, stamp)
        return FillEffect(position=position, realised=realised,
                          released_margin=released)

    def settle_expiry(self, contract_code: str, settlement: Decimal,
                      ts: datetime) -> Decimal:
        """Final settlement of an expiring contract: cash moves, the row goes.

        Design section 7.4: ``ExpirySettled`` is a cash movement into or out of
        the deposit at the index-referenced final settlement, **with the
        contract removed from the ledger**. Marked from the variation-margin
        reference for the same reason :meth:`apply_fill` is.

        ``settlement`` is the caller's; Tier 1's ``exchange.py`` reads the data
        source's **close on the expiry day**, which is a declared
        simplification and not the published rule. The exchange publishes a
        trimmed average over the 14:15-14:45 window; on VN30F2206's 2022-06-16
        expiry the window mean was 1281.36 against a close of 1286.00, so the
        close overstates by 0.36% -- one contract, n=1. The settlement *basis*
        itself changed on 2022-08-17 from the contract's own price to the VN30
        index. **Do not report a pre-2022-08-17 settlement figure as
        authoritative.**

        Returns:
            The signed cash flow applied to the deposit. Zero if not held.
        """
        position = self.contracts.position(contract_code)
        if position is None:
            return _ZERO
        reference = self.variation_reference(contract_code)
        cash_flow = (Decimal(position.net_quantity) * position.multiplier
                     * (settlement - reference))
        self.contracts.remove(contract_code)
        self._settlement_reference.pop(contract_code, None)
        self._marks[contract_code] = settlement
        if cash_flow != 0:
            self._move(cash_flow, ts,
                       f'final settlement of {contract_code} at {settlement}')
        return cash_flow

    # -- internals -------------------------------------------------------

    def _move(self, amount: Decimal, ts: datetime, reason: str) -> Decimal:
        """Apply a signed movement and record it. The only balance mutator."""
        self._balance += amount
        self._entries += (DepositEntry(ts=ts, amount=amount, reason=reason,
                                       balance_after=self._balance),)
        return self._balance

    def _worst_case_net(self, contract_code: str,
                        extra_signed: int = 0) -> int:
        """Largest ``|net|`` reachable if live orders on this contract filled.

        ``max(|net + buys|, |net - sells|)`` rather than the signed sum,
        because the two sides need not both fill and a cap must hold in the
        worst case. Monotone in ``extra_signed``, so the increment a new order
        adds is never negative.
        """
        net = self.contracts.net_quantity(contract_code)
        buys = 0
        sells = 0
        for live in self._live_orders.values():
            if live.contract_code != contract_code:
                continue
            if live.signed_quantity > 0:
                buys += live.remaining_quantity
            else:
                sells += live.remaining_quantity
        if extra_signed > 0:
            buys += extra_signed
        elif extra_signed < 0:
            sells += -extra_signed
        return max(abs(net + buys), abs(net - sells))

    def _consume_order_margin(self, fill: Fill, ts: datetime) -> Decimal:
        """Release the filled share of an order's margin reservation."""
        live = self._live_orders.get(fill.order_id)
        if live is None:
            return _ZERO
        if fill.quantity >= live.remaining_quantity or live.remaining_quantity <= 0:
            amount = live.remaining_margin
            self._live_orders.pop(fill.order_id, None)
        else:
            amount = (live.remaining_margin * Decimal(fill.quantity)
                      / Decimal(live.remaining_quantity))
            self._live_orders[fill.order_id] = replace(
                live,
                remaining_quantity=live.remaining_quantity - fill.quantity,
                remaining_margin=live.remaining_margin - amount)
        if amount > 0:
            self._encumbrances.consume(fill.order_id, ts,
                                       resource=ResourceKind.DEPOSIT,
                                       amount=amount)
        return amount


@dataclass(frozen=True)
class _LiveOrder:
    """What the account remembers about one live derivative order.

    Private because it is bookkeeping, not vocabulary: the caller-visible
    record of a live order is ``OrderRecord``, which ``orders.py`` owns and
    this module must not import.
    """

    contract_code: str
    signed_quantity: int
    remaining_quantity: int
    remaining_margin: Decimal


# --------------------------------------------------------------------------
# The margin-call state machine
# --------------------------------------------------------------------------

def liquidation_sequence(account: DerivativesAccount,
                         marks: Mapping[str, Decimal],
                         rule: LiquidationRule = LiquidationRule.LARGEST_LOSS_FIRST,
                         ) -> Tuple[str, ...]:
    """The order in which a forced close would shut contracts.

    **A modelling choice, not a sourced rule.** No Vietnamese document
    prescribes a selection order for a broker's forced close; rulebook 6.3
    shows the real level-3 mechanism is VSDC requesting HNX suspend the account
    from opening new positions while the clearing member reduces it, and one
    broker's published behaviour (Pinetree, 2024) prioritises the *nearest
    expiry* rather than the largest loss. Design section 7.4 therefore requires
    the selection rule to be **stated** rather than assumed, which is what this
    function's return value and ``Event.margin(..., selection_rule=...)`` are
    for.

    ``LARGEST_LOSS_FIRST`` orders by the contract's P&L against its
    variation-margin reference, most-negative first, because that is the leg
    contributing most to ``VM`` and closing it relieves ``MR`` fastest.

    Raises:
        NotImplementedError: for ``PRO_RATA``, which is not an ordering at all
            but a proportional allocation across every leg. Returning an
            ordering for it would be answering a different question.
    """
    if rule is not LiquidationRule.PRO_RATA:
        scored = []
        for code, position in account.contracts.positions().items():
            price = account.mark_for(code, marks)
            pnl = (Decimal(position.net_quantity) * position.multiplier
                   * (price - account.variation_reference(code)))
            scored.append((pnl, code))
        return tuple(code for _, code in sorted(scored, key=lambda p: (p[0], p[1])))
    raise NotImplementedError(
        'LiquidationRule.PRO_RATA is a proportional reduction across every '
        'leg, not a selection order; it needs a quantity allocation, which '
        'Tier 1 does not implement. Use LARGEST_LOSS_FIRST and state it.')


class MarginMonitor:
    """The day-loop state machine. A margin call is **state**, not an event.

    This is a class and not a function for one reason: an outstanding call has
    to be carried **across days**::

        day T    mark -> assets no longer cover MR -> MarginCall(cure_by)
                 caller may transfer, reduce, or do nothing
        day T+1  re-mark -> still short -> ForcedLiquidation
                         -> restored    -> the call clears

    That is also why ``Exchange.sustains()`` cannot be reused for it:
    ``sustains()`` takes a whole ``Sequence[MarketState]`` in one batch and has
    nowhere to put a call that survives to the next element. It stays untouched
    as the batch research path.

    **The cure window is a broker term.** The rulebook records this as an
    important negative finding: the length of a retail cure window is a
    commercial term in the account-opening agreement, not an exchange or
    statutory number, and it must live in ``BrokerTerms``. (LuatVietnam's
    summary of QD 61 attributes a 3-business-day cure to Article 13 and a
    5-business-day cure to Article 28; VSDC's own page says the member may
    require an intraday top-up. Those reconcile if the multi-day periods are
    clearing-member-to-VSD deadlines while the broker-to-client call is
    intraday and contractual -- so **do not hard-code either number**.)

    The window is measured in **sessions** through a ``TradingCalendar``, not
    in settlement business days: the two calendars diverge around Tet, and a
    cure deadline is a trading deadline.
    """

    def __init__(self, terms: BrokerTerms, calendar: TradingCalendarLike, *,
                 liquidation: LiquidationRule = LiquidationRule.LARGEST_LOSS_FIRST,
                 venue: Venue = Venue.HNXDS) -> None:
        self.terms = terms
        self.calendar = calendar
        self.liquidation = liquidation
        self.venue = venue
        self._cure_by: Optional[datetime] = None
        self._call_opened_at: Optional[datetime] = None
        self._last_status: MarginStatus = MarginStatus.OK

    @property
    def outstanding_call(self) -> Optional[datetime]:
        """``cure_by`` of an unanswered call, else ``None``."""
        return self._cure_by

    @property
    def last_status(self) -> MarginStatus:
        """The ladder status of the most recent mark."""
        return self._last_status

    def on_mark(self, account: DerivativesAccount, view: MarginView,
                rules: Optional[RuleSetLike], ts: datetime,
                ) -> Tuple[MarginView, ...]:
        """One mark. Returns the views that are *news*, oldest first.

        Empty when nothing changed -- in particular, an outstanding call that
        is still inside its cure window is not re-reported on every mark, which
        is what makes the call state rather than a repeated event.

        How ``exchange.py`` should map the result to events:

        =================  ==================================================
        returned status    event
        =================  ==================================================
        ``WARNING``        ``EventKind.MARGIN_WARNING``
        ``CALL``           ``EventKind.MARGIN_CALL``, ``cure_by`` set
        ``FORCED``         ``EventKind.FORCED_LIQUIDATION``, which must also
                           state the selection rule, the contracts closed, the
                           price used and the resulting deposit balance
        ``OK``             nothing -- an ``OK`` view can only appear here as
                           the *clearance* of an outstanding call, and there is
                           no ``EventKind`` for a clearance
        =================  ==================================================

        Escalation to ``FORCED`` has two independent paths, and both are real:
        utilisation reaching the broker's forced-close level (its own trigger),
        or an outstanding call whose cure deadline has passed with utilisation
        still at or above the call level. A mark reports at most one step, and
        a jump straight past the call level reports ``FORCED`` without
        inventing an intermediate call that never happened.
        """
        ladder = view.status
        out: Tuple[MarginView, ...] = ()

        if self._cure_by is not None:
            if ladder in (MarginStatus.OK, MarginStatus.WARNING):
                self._cure_by = None
                self._call_opened_at = None
                out = (replace(view, cure_by=None),)
            elif ladder is MarginStatus.FORCED or (
                    ts >= self._cure_by
                    and self._call_opened_at is not None
                    and ts > self._call_opened_at):
                out = (replace(view, status=MarginStatus.FORCED,
                               cure_by=self._cure_by),)
                self._cure_by = None
                self._call_opened_at = None
                ladder = MarginStatus.FORCED
            # else: still inside the window. Not news.
        elif ladder is MarginStatus.FORCED:
            out = (replace(view, cure_by=None),)
        elif ladder is MarginStatus.CALL:
            self._cure_by = self._cure_deadline(ts, rules)
            self._call_opened_at = ts
            out = (replace(view, cure_by=self._cure_by),)
        elif ladder is MarginStatus.WARNING:
            if self._last_status is not MarginStatus.WARNING:
                out = (view,)

        self._last_status = ladder
        return out

    def _cure_deadline(self, ts: datetime,
                       rules: Optional[RuleSetLike]) -> datetime:
        """``ts`` advanced by the broker's cure window, in sessions.

        ``CureWindow.SAME_SESSION`` (0) yields ``ts`` itself: the deadline is
        already due, so the next mark that is still short forces. That is what
        "the broker may force-close the same day" means as a state machine.
        """
        deadline = ts
        for _ in range(self.terms.cure_window_sessions):
            deadline = self.calendar.next_session_open(deadline, self.venue,
                                                       rules)
        return deadline


#: Every rejection this module can produce is a :data:`RejectionRule`, never a
#: string. ``AdmissionRule`` (once :class:`StatefulRule` is merged into it) *is*
#: the rejected-order log, and a log keyed on prose cannot be counted. Named
#: here so a reader can see the whole surface at a glance.
DEPOSIT_REJECTIONS: Tuple[RejectionRule, ...] = (
    StatefulRule.INSUFFICIENT_DEPOSIT,
    StatefulRule.POSITION_LIMIT,
)
