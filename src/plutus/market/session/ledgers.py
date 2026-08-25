"""The securities account: encumbrance, tranche holdings, tranche cash.

Locked shapes **2** and **3**, which are two halves of one idea: a ledger that
answers "can this order be accepted?" must answer it *net of the orders already
live*, and it must answer it *per settlement instant* rather than per scalar
balance.

**Shape 2 -- encumbrance.** Because orders rest, a raw balance is the wrong
number to test. Without a reservation taken at accept, two individually
affordable resting buys overdraw cash, and 500 settled shares back 1,000 shares
of resting sells -- a short equity position, which Vietnam does not permit at
all. So every accepted order takes a reservation, every terminal transition
releases it, and a partial fill converts its slice of the reservation into a
settled movement and returns the rest. The forbidden build is a stateless
affordability check inside ``admits()``, or scalar balances mutated only at
fill.

**Shape 3 -- tranches.** ``unsettled`` is a *list* of ``(quantity,
settles_at)``, never a scalar ``(quantity, sellable_from)`` pair. Under T+2 up
to two parcels are open at once and a single pair forces a wrong choice either
way: the earlier instant frees the later parcel's shares -- permitting exactly
the sale the settlement rule exists to prevent -- or the later instant blocks
the earlier one, producing a spurious rejection. ``sellable_from`` is therefore
computed per *requested quantity* (:meth:`Holding.sellable_from`), never
stored. Cash mirrors holdings exactly, because cash and securities settle by
DVP at the depository and are allocated to the client in one event (rulebook
5.1).

The three net figures this module owns, from design section 7.0::

    Cash.available   = settled_balance + advanced - sum(encumbrance on live buys)
    Holding.sellable = settled - sum(quantity committed to live sells)

(``free_deposit`` is the third and lives in ``deposit.py``; it shares the
:class:`EncumbranceLedger` so that section 12 invariant 4 is one sum over one
object.)

**Section 12 invariant 4 is the test that matters.** The sum of encumbrance
over live orders equals the ledgers' committed totals, and committed returns to
*exactly* zero when no order is live. That one assertion catches the whole leak
class: a terminal edge that forgets to release, a partial fill that releases the
wrong slice, a rejection that reserved before it refused.

What this module does **not** do: it never reaches into ``orders.py``. It takes
``OrderRecord``/``Fill``/``Order`` as values and is driven by ``exchange.py``,
which wires :meth:`SecuritiesAccount.release` to
``OrderBookOfRecord(on_terminal=...)``. That absent import is what lets
``orders.py`` own the state machine exclusively, and it is what makes "a
terminal transition that forgets to release" impossible by construction rather
than by review.

Money conventions, declared once (rulebook 12.1):

* Prices on the three cash venues are quoted in **thousands of dong**, so
  ``notional = price x quantity x 1000``. :func:`trade_value` is the single
  place that conversion happens; :attr:`Fill.gross_value` is deliberately
  unit-naive so it cannot hide the choice.
* Charge amounts are absolute VND.
* **Rounding charges to whole dong is a MODELLING CHOICE, not a sourced rule.**
  No Vietnamese source states a rounding rule for any fee or tax, and any
  published result sensitive to it must say so.
"""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import (TYPE_CHECKING, Dict, FrozenSet, List, Mapping, Optional,
                    Sequence, Tuple, Union)

from plutus.core.constant import VietnamMarketConstant
from plutus.core.order import OrderType, Side
from plutus.market.broker import BrokerTerms
from plutus.market.protocol import MarketState, Order
from plutus.market.session.types import (AccountRef, BrokerProfile, Cash,
                                         Charge, ChargeBase, ChargeClass,
                                         ChargeRule, DebitedAt, Encumbrance,
                                         Fill, Holding, HoldingTranche,
                                         OrderId, Pool, ProceedsTranche,
                                         Rejected, ResourceKind, StatefulRule,
                                         Venue, pool_for_venue)
from plutus.market.verdicts import AdmissionRule, Verdict

if TYPE_CHECKING:  # pragma: no cover - import-time cycle avoidance
    # ``rulebook.py`` is authored in parallel with this module and imports
    # nothing from here. Taking ``RuleSet`` only as a type keeps ledgers.py
    # importable on its own, which is what lets its tests run before the
    # rulebook lands. At runtime the only thing this module asks of a RuleSet
    # is ``charges(venue, cls_) -> Tuple[ChargeRule, ...]``.
    from plutus.market.session.rulebook import RuleSet

__all__ = [
    'CashLedger',
    'EncumbranceLedger',
    'HoldingsLedger',
    'SecuritiesAccount',
    'assess_charges',
    'estimate_charges',
    'trade_value',
]


# --------------------------------------------------------------------------
# Money units and rounding
# --------------------------------------------------------------------------

#: One dong. Every charge is quantised to this; see the module docstring for
#: why that is a declared modelling choice rather than a sourced rule.
_DONG = Decimal('1')


def _to_dong(amount: Decimal) -> Decimal:
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
    movement in this module goes through here, because a missing factor of
    1,000 is invisible in a ratio and fatal in a balance.

    Raises:
        ValueError: on ``HNXDS``. ``CURRENCY_UNIT['HNXDS'] == 1`` is
            meaningless as a multiplier (rulebook 12.1) -- index futures quote
            points and apply a 100,000 VND contract multiplier, and
            government-bond futures quote VND on a 100,000 face. Derivatives
            notional is ``deposit.py``'s business and must not be computed
            here by accident.
    """
    if venue is Venue.HNXDS:
        raise ValueError(
            'trade_value is the cash-venue conversion; HNXDS notional is '
            'index points x the contract multiplier and belongs in '
            'deposit.py. CURRENCY_UNIT["HNXDS"] = 1 is not a multiplier.'
        )
    if quantity < 0:
        raise ValueError(f'quantity must not be negative, got {quantity}')
    unit = Decimal(VietnamMarketConstant.CURRENCY_UNIT[venue.value])
    return Decimal(quantity) * price * unit


#: Order types whose buy encumbrance is taken at the ceiling rather than at a
#: limit price. The market family has no price to reserve against and the two
#: auction types have no clearing price yet, so both are funded at the worst
#: case the band permits -- which is also what ``core/order.py`` means by
#: "sell at floor or buy at ceiling for guaranteed match".
_CEILING_FUNDED: FrozenSet[OrderType] = frozenset({
    OrderType.MARKET,
    OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
    OrderType.MARKET_FILL_OR_KILL,
    OrderType.MARKET_IMMEDIATE_OR_CANCEL,
    OrderType.AT_THE_OPENING,
    OrderType.AT_THE_CLOSE,
})


# --------------------------------------------------------------------------
# Locked shape 2 -- the encumbrance ledger
# --------------------------------------------------------------------------

class EncumbranceLedger:
    """Reservations held by live orders, keyed ``(order_id, ResourceKind)``.

    One object serves both pools. ``deposit.py`` takes ``DEPOSIT``
    reservations from the same ledger that this module takes ``CASH`` and
    ``SHARES`` from, because section 12 invariant 4 is a statement about *all*
    live orders and a second ledger would give it two places to be true.

    The key is the pair, not an id of its own: an order reserves at most one
    kind of resource, and a synthetic id would let one order hold two cash
    reservations that no balance check would ever reconcile.
    """

    def __init__(self) -> None:
        self._live: Dict[Tuple[OrderId, ResourceKind], Encumbrance] = {}
        #: The order's *full* quantity at the instant the reservation was
        #: taken. Needed because an amount-denominated reservation (CASH,
        #: DEPOSIT) cannot express "how much of me does 400 of 1,000 shares
        #: consume?" from the ``Encumbrance`` alone -- ``Encumbrance.quantity``
        #: is documented as meaningful only for ``SHARES``, and writing an
        #: order quantity into it would make a cash reservation look like a
        #: committed sell to every other reader of that field.
        self._order_quantity: Dict[Tuple[OrderId, ResourceKind], int] = {}

    # -- taking ---------------------------------------------------------

    def take(
        self,
        order_id: OrderId,
        pool: Pool,
        resource: ResourceKind,
        ts: datetime,
        *,
        amount: Decimal = Decimal('0'),
        quantity: int = 0,
        ticker: Optional[str] = None,
        estimated_charges: Decimal = Decimal('0'),
        order_quantity: Optional[int] = None,
    ) -> Encumbrance:
        """Reserve on accept.

        Args:
            order_quantity: the order's whole quantity, so a later partial
                fill can be released pro rata against an amount-denominated
                reservation. Defaults to ``quantity``, which is already right
                for a ``SHARES`` reservation. Not in the interface contract's
                signature; added as a trailing keyword because
                :meth:`consume` cannot compute a correct pro-rata slice
                without it and every caller of ``take`` has the number.

        Raises:
            ValueError: if this key already holds a reservation. Re-reserving
                is not idempotent -- it would double-count the order against
                ``available`` -- so it is refused rather than merged.
        """
        key = (order_id, resource)
        if key in self._live:
            raise ValueError(
                f'order {order_id} already holds a {resource.value} '
                f'reservation; an order reserves at most one of each resource '
                f'and re-taking would double-count it against available'
            )
        if amount < 0 or quantity < 0:
            raise ValueError(
                f'a reservation must be non-negative, got amount={amount} '
                f'quantity={quantity}')
        enc = Encumbrance.take(
            order_id=order_id, pool=pool, resource=resource, ts=ts,
            amount=amount, quantity=quantity, ticker=ticker,
            estimated_charges=estimated_charges,
        )
        self._live[key] = enc
        self._order_quantity[key] = (
            quantity if order_quantity is None else order_quantity)
        return enc

    # -- releasing ------------------------------------------------------

    def consume(
        self,
        order_id: OrderId,
        ts: datetime,
        *,
        resource: ResourceKind,
        amount: Decimal = Decimal('0'),
        quantity: int = 0,
    ) -> Optional[Encumbrance]:
        """Pro-rata release at a fill.

        The rule, and it is the one place a leak hides. A fill releases the
        fill's **pro-rata slice of the original reservation**, not merely the
        cash it actually spent. A limit buy of 1,000 reserved at 95.5 that
        fills 400 at 95.0 spent 38,000,000 dong but had 38,200,000 reserved
        against those 400 shares; releasing only the 38,000,000 leaves 200,000
        dong reserved behind a quantity that no longer exists, and
        ``available`` understates by 0.5 per share for the rest of the order's
        life. The residue after a pro-rata release is exactly what the
        unfilled remainder needs at the reserved price, which is the property
        that makes the invariant-4 test pass at every point in an order's
        life rather than only at its end.

        Args:
            resource: which reservation this fill draws on.
            amount: the cash the fill actually consumed **at the fill price**,
                including the charges levied on it. Used only when the slice
                cannot be computed -- i.e. when the ledger was never told the
                order's quantity.
            quantity: the quantity filled. For a ``SHARES`` reservation this
                is deducted directly, since the reservation is denominated in
                the same units.

        Returns:
            The reduced reservation, or ``None`` if the order holds none --
            which is not an error: a rejected order never took one and the
            release hook fires for it anyway.
        """
        key = (order_id, resource)
        enc = self._live.get(key)
        if enc is None:
            return None

        reduce_by = amount
        order_quantity = self._order_quantity.get(key, 0)
        if quantity > 0 and order_quantity > 0 and enc.original_amount > 0:
            reduce_by = (enc.original_amount * Decimal(quantity)
                         / Decimal(order_quantity))

        updated = enc.reduced_by(ts, amount=reduce_by, quantity=quantity)
        self._live[key] = updated
        return updated

    def release(
        self,
        order_id: OrderId,
        ts: datetime,
        *,
        resource: Optional[ResourceKind] = None,
    ) -> Tuple[Encumbrance, ...]:
        """Full release, called on **every** terminal transition.

        Filled, cancelled, expired, rejected, and the residue of a
        partially-filled order that then terminates: all four edges land here,
        via ``OrderBookOfRecord(on_terminal=...)``. ``resource=None`` releases
        every reservation the order holds.

        Idempotent by design. An order that holds nothing -- because it was
        rejected before reserving, or because it already terminated -- returns
        an empty tuple rather than raising, so the terminal hook can be wired
        unconditionally.
        """
        keys = [k for k in self._live
                if k[0] == order_id and (resource is None or k[1] is resource)]
        released = []
        for key in keys:
            released.append(self._live.pop(key).released(ts))
            self._order_quantity.pop(key, None)
        return tuple(released)

    # -- reading --------------------------------------------------------

    def outstanding(
        self,
        *,
        pool: Optional[Pool] = None,
        resource: Optional[ResourceKind] = None,
        ticker: Optional[str] = None,
    ) -> Decimal:
        """Sum of the reserved *amount* over live orders.

        ``Cash.committed`` is ``outstanding(pool=SECURITIES, resource=CASH)``
        and ``free_deposit``'s reservation term is
        ``outstanding(pool=DERIVATIVES, resource=DEPOSIT)``. Quantity-
        denominated reservations contribute zero here by construction; use
        :meth:`outstanding_quantity` for those.
        """
        total = Decimal('0')
        for enc in self._live.values():
            if pool is not None and enc.pool is not pool:
                continue
            if resource is not None and enc.resource is not resource:
                continue
            if ticker is not None and enc.ticker != ticker:
                continue
            total += enc.amount
        return total

    def outstanding_quantity(self, ticker: str) -> int:
        """Shares of ``ticker`` committed to live sells. ``Holding.committed``.

        Filters on ``resource is SHARES`` rather than summing every
        ``quantity`` field, so that a cash reservation can never be mistaken
        for a committed sell.
        """
        return sum(enc.quantity for enc in self._live.values()
                   if enc.resource is ResourceKind.SHARES
                   and enc.ticker == ticker)

    def of(self, order_id: OrderId) -> Tuple[Encumbrance, ...]:
        """Every reservation this order still holds."""
        return tuple(enc for key, enc in self._live.items()
                     if key[0] == order_id)

    def live_order_ids(self) -> FrozenSet[OrderId]:
        """Orders still holding something.

        An order whose reservation has been consumed down to nothing but whose
        terminal edge has not yet fired is **not** here: it commits no
        resource, so counting it would make invariant 4 assert over a set that
        does not match the sum.
        """
        return frozenset(key[0] for key, enc in self._live.items()
                         if not enc.is_released)


# --------------------------------------------------------------------------
# Locked shape 3 -- holdings as a tranche list
# --------------------------------------------------------------------------

class HoldingsLedger:
    """Equity holdings as settled quantity plus a list of open tranches.

    Sells draw on ``settled`` and never on ``unsettled``. That one sentence is
    the whole T+2 rule as the order path sees it, and the tranche list is what
    makes it expressible: two parcels bought on consecutive days settle at
    different instants, and neither may borrow the other's eligibility.
    """

    def __init__(
        self,
        encumbrances: EncumbranceLedger,
        initial: Optional[Mapping[str, int]] = None,
    ) -> None:
        """
        Args:
            encumbrances: the shared ledger. ``Holding.committed`` is read
                from it rather than tracked here, so the two cannot disagree
                about the same number.
            initial: opening **settled** holdings per ticker. Not in the
                interface contract's signature; added as a trailing keyword so
                a session can start with stock without faking a settled buy,
                which would put a phantom tranche in the audit trail.
        """
        self._encumbrances = encumbrances
        self._settled: Dict[str, int] = dict(initial or {})
        self._unsettled: Dict[str, List[HoldingTranche]] = {}

    # -- movements ------------------------------------------------------

    def credit_unsettled(
        self,
        ticker: str,
        quantity: int,
        settles_at: datetime,
        ts: datetime,
        order_id: Optional[OrderId] = None,
    ) -> HoldingTranche:
        """A buy filled: append a tranche settling at ``settles_at``.

        **Never merges into an existing tranche**, even at the same instant.
        A merge loses the audit trail that says which fill bought what, and
        the corporate-action hook needs per-parcel granularity to scale
        parcels whose settlement instants differ.
        """
        if quantity <= 0:
            raise ValueError(
                f'a holdings credit must move positive quantity, got {quantity}')
        tranche = HoldingTranche(quantity=quantity, settles_at=settles_at,
                                 acquired_at=ts, source_order_id=order_id)
        self._unsettled.setdefault(ticker, []).append(tranche)
        return tranche

    def settle_due(self, now: datetime) -> Tuple[HoldingTranche, ...]:
        """Move every tranche whose ``settles_at <= now`` into ``settled``.

        The comparison is ``<=`` on **datetimes**, and that is what makes
        ``T+2 @ 13:00`` behave as T+3 on midnight-stamped daily bars: the T+2
        bar is stamped 00:00 and does not reach the 13:00 threshold, so the
        shares first become sellable on the T+3 bar. That is the conservative
        direction and it is intended.

        Returns what moved so ``exchange.py`` can emit ``SettlementCredited``.
        Use :meth:`settle_due_by_ticker` when the ticker is needed --
        ``HoldingTranche`` does not carry one, and the event does.
        """
        return tuple(tranche for _, tranche in self.settle_due_by_ticker(now))

    def settle_due_by_ticker(
        self, now: datetime,
    ) -> Tuple[Tuple[str, HoldingTranche], ...]:
        """:meth:`settle_due`, paired with the ticker each tranche belongs to.

        Not in the interface contract. It exists because
        ``Event.settlement_credited`` takes a ``ticker`` and
        ``HoldingTranche`` has no ticker field, so the promised return type
        cannot answer the question its own docstring poses. ``settle_due``
        delegates here, so the contract's signature stays exactly as written.
        """
        moved: List[Tuple[str, HoldingTranche]] = []
        for ticker, tranches in self._unsettled.items():
            due = [t for t in tranches if t.settles_at <= now]
            if not due:
                continue
            due.sort(key=lambda t: t.settles_at)
            self._unsettled[ticker] = [t for t in tranches
                                       if t.settles_at > now]
            for tranche in due:
                self._settled[ticker] = (self._settled.get(ticker, 0)
                                         + tranche.quantity)
                moved.append((ticker, tranche))
        moved.sort(key=lambda pair: pair[1].settles_at)
        return tuple(moved)

    def debit_settled(self, ticker: str, quantity: int, ts: datetime) -> None:
        """A sell filled: draw from ``settled`` only.

        Raises:
            ValueError: if settled quantity is short. The encumbrance taken at
                accept should have made this unreachable, so reaching it is a
                bug in the reservation path -- and a silent overdraw here is a
                short equity position, which Vietnam does not permit at all.
        """
        held = self._settled.get(ticker, 0)
        if quantity <= 0:
            raise ValueError(
                f'a holdings debit must move positive quantity, got {quantity}')
        if quantity > held:
            raise ValueError(
                f'cannot debit {quantity} of {ticker} against {held} settled: '
                f'unsettled quantity is never deliverable, and an overdraw is '
                f'a short equity position'
            )
        self._settled[ticker] = held - quantity

    # -- reading --------------------------------------------------------

    def holding(self, ticker: str) -> Holding:
        """The read model, with ``committed`` taken from the encumbrances."""
        return Holding(
            ticker=ticker,
            settled=self._settled.get(ticker, 0),
            committed=self._encumbrances.outstanding_quantity(ticker),
            unsettled=tuple(sorted(self._unsettled.get(ticker, ()),
                                   key=lambda t: t.settles_at)),
        )

    def tickers(self) -> FrozenSet[str]:
        """Every ticker this account has held, settled or not."""
        return frozenset(self._settled) | frozenset(self._unsettled)

    # -- the corporate-action hook (Tier 2) -----------------------------

    def apply_corporate_action(
        self,
        ticker: str,
        factor: Decimal,
        cash_per_share: Decimal,
        ts: datetime,
    ) -> Tuple[Decimal, Tuple[HoldingTranche, ...]]:
        """Scale every parcel and return the cash leg. **Additive hook only.**

        There is **no corporate-action engine in Tier 1**, and a run spanning
        an ex-date is wrong for that instrument -- a declared limitation
        (design section 15 item 5), not an oversight. This exists so the
        engine is not later retrofitted into a scalar: a split scales open
        parcels *without collapsing them*, so their distinct settlement
        instants survive the adjustment, and that is only possible because the
        holding is a list.

        ``factor`` multiplies quantity (2 for a 1:1 bonus, 1 for a pure cash
        dividend). ``cash_per_share`` is the **gross** cash leg per share held.
        The 5% dividend withholding tax is deliberately *not* applied here: it
        is a charge row, and inventing it inside the holdings ledger would put
        a tax rate somewhere no charge table can see it.

        The cash leg is computed on the **pre-adjustment** quantity, which is
        the entitlement on the record date, and it counts unsettled parcels:
        a share bought T+0 and unsettled on the ex-date still carries the
        entitlement.

        **OPEN, and not settled by the interface contract:** whether a resting
        order survives the ex-date with its quantity scaled or is cancelled.
        That decision picks whether the future engine mutates live orders or
        terminates them; this hook touches neither.

        Returns:
            ``(cash_leg, new_unsettled_tranches)``. The caller credits the
            cash -- this ledger holds no cash.
        """
        if factor <= 0:
            raise ValueError(f'a corporate-action factor must be positive, '
                             f'got {factor}')
        holding = self.holding(ticker)
        cash_leg = cash_per_share * Decimal(holding.total)

        self._settled[ticker] = int(Decimal(holding.settled) * factor)
        scaled = [t.scaled(factor) for t in self._unsettled.get(ticker, ())]
        self._unsettled[ticker] = scaled
        return cash_leg, tuple(scaled)


# --------------------------------------------------------------------------
# Cash: settled balance, pending proceeds, the sale advance, charges
# --------------------------------------------------------------------------

class CashLedger:
    """Settled cash, pending proceeds, the sale advance, and charge debits.

    The mirror of :class:`HoldingsLedger`, deliberately: cash and securities
    settle by DVP at the same instant and are allocated to the client in one
    event, so the two ledgers carry the same tranche shape and are driven from
    the same ``settles_at``.

    ``available`` is never stored. It is
    ``settled_balance + advanced - committed``, and pending proceeds are **not**
    in it unless advanced -- equity requires 100% pre-funding, so a buy is
    refused when available cash is short *even if pending proceeds would cover
    it*. Rulebook 5.1 states the consequence bluntly: sell-then-rebuy on the
    same day is not possible on settled cash alone.
    """

    def __init__(
        self,
        initial_cash: Decimal,
        terms: BrokerTerms,
        encumbrances: EncumbranceLedger,
    ) -> None:
        self._settled = Decimal(initial_cash)
        self._terms = terms
        self._encumbrances = encumbrances
        self._pending: List[ProceedsTranche] = []
        self._charges: List[Charge] = []
        #: Cumulative interest on advances, including advances that have since
        #: settled. Reported, never netted.
        self._interest_accrued = Decimal('0')

    # -- reading --------------------------------------------------------

    def cash(self) -> Cash:
        """The read model. ``available`` is derived, never stored."""
        return Cash(
            settled_balance=self._settled,
            committed=self._encumbrances.outstanding(
                pool=Pool.SECURITIES, resource=ResourceKind.CASH),
            advanced=self.advanced(),
            interest_accrued=self._interest_accrued,
            pending_proceeds=tuple(self._pending),
        )

    def advanced(self) -> Decimal:
        """Unsettled proceeds made spendable early by the sale advance.

        Zero unless the broker offers *ung truoc tien ban* and the caller
        enabled it. It is a **broker term, not an exchange rule** -- which is
        the clearest illustration of why the two config objects are separate.
        """
        return sum((t.amount for t in self._pending if t.advanced),
                   Decimal('0'))

    def charges(self) -> Tuple[Charge, ...]:
        """Everything levied so far, itemised. Backs ``session.charges()``."""
        return tuple(self._charges)

    # -- movements ------------------------------------------------------

    def credit_pending(
        self,
        amount: Decimal,
        settles_at: datetime,
        ts: datetime,
        order_id: Optional[OrderId] = None,
    ) -> ProceedsTranche:
        """A sell filled: proceeds pend until ``settles_at``.

        ``amount`` must **already be net of the sell-side charges withheld at
        source**. The 0.1% personal income tax on a securities transfer is
        sell-side only and the broker deducts it from the proceeds, so a sale
        credits net; carrying gross here and netting later is how a sale ends
        up wrong by more than most commissions.

        When ``terms.advance_on_sale_enabled`` the tranche is marked advanced
        and its amount is spendable immediately, accruing interest at the
        broker's daily rate until it settles.
        """
        if amount < 0:
            raise ValueError(
                f'sale proceeds must not be negative, got {amount}; charges '
                f'are netted out of a sale, they do not invert it')
        tranche = ProceedsTranche(
            amount=amount, settles_at=settles_at, accrued_at=ts,
            source_order_id=order_id,
            advanced=self._terms.advance_on_sale_enabled,
        )
        self._pending.append(tranche)
        return tranche

    def settle_due(self, now: datetime) -> Tuple[ProceedsTranche, ...]:
        """Move matured proceeds into ``settled_balance``, clearing the advance.

        Same ``<=`` comparison and the same instant as
        :meth:`HoldingsLedger.settle_due`, because it is the same allocation
        event. Where the tranche was advanced, the amount simply moves from
        ``advanced`` into ``settled_balance``: ``available`` is unchanged,
        which is the point -- the advance made the money spendable early, it
        did not create any.
        """
        due = [t for t in self._pending if t.settles_at <= now]
        if not due:
            return ()
        self._pending = [t for t in self._pending if t.settles_at > now]
        for tranche in due:
            self._settled += tranche.amount
        return tuple(sorted(due, key=lambda t: t.settles_at))

    def accrue_interest(self, now: datetime) -> Decimal:
        """Accrue interest on outstanding advances up to ``now``.

        The mechanism, modelled rather than hand-waved: interest is
        ``amount_advanced x daily_rate x days_advanced`` (rulebook 12.7), run
        from the instant the advance was taken to the instant the proceeds
        settle and the broker recovers it. Calling this repeatedly is safe --
        each tranche carries its own ``accrued_at`` watermark, which advances
        by whole days only, so the same day is never charged twice and a
        part-day is not lost, it is carried.

        Two declared assumptions, neither sourced:

        * **Day count is calendar days**, not settlement business days. The
          source gives ``amount x days`` with no day-count basis at all, and
          a weekend advance plainly costs the investor something.
        * **Accrual stops at the tranche's settlement instant**, because the
          advance is recovered out of that settlement. A caller that advances
          the clock a week before calling this still pays only to settlement.

        The result is reported in ``Cash.interest_accrued`` and is **never
        netted against anything** -- the caller decides what to do with it
        (design section 7.2). Nothing here debits cash.

        Returns:
            The interest accrued by this call, zero if none was due.
        """
        rate = self._terms.advance_on_sale_daily_rate
        accrued_now = Decimal('0')
        for index, tranche in enumerate(self._pending):
            if not tranche.advanced or rate <= 0:
                continue
            until = min(now, tranche.settles_at)
            days = (until - tranche.accrued_at).days
            if days <= 0:
                continue
            interest = tranche.amount * rate * Decimal(days)
            self._pending[index] = ProceedsTranche(
                amount=tranche.amount,
                settles_at=tranche.settles_at,
                accrued_at=tranche.accrued_at + timedelta(days=days),
                source_order_id=tranche.source_order_id,
                advanced=tranche.advanced,
                interest_accrued=tranche.interest_accrued + interest,
            )
            accrued_now += interest
        self._interest_accrued += accrued_now
        return accrued_now

    def debit(self, amount: Decimal, ts: datetime, reason: str) -> None:
        """Take cash out of the settled balance.

        ``settled_balance`` may legitimately go **negative** while an advance
        is outstanding: the advanced money is spendable but has not arrived,
        so spending it overdraws the settled balance by design and the
        settlement then squares it. What is refused is a debit that exceeds
        ``settled_balance + advanced``, which is a genuine overdraw the
        encumbrance should have prevented.

        Raises:
            ValueError: on a genuine overdraw. This is a bug detector for the
                reservation path, not a market rule -- the market rule is the
                pre-funding check in :meth:`SecuritiesAccount.reserve_for_buy`.
        """
        if amount < 0:
            raise ValueError(f'a debit must be non-negative, got {amount}; '
                             f'use credit() to move cash the other way')
        if amount > self._settled + self.advanced():
            raise ValueError(
                f'debit of {amount} for {reason!r} exceeds settled '
                f'{self._settled} plus advanced {self.advanced()}; the '
                f'encumbrance taken at accept should have made this '
                f'unreachable'
            )
        self._settled -= amount

    def credit(self, amount: Decimal, ts: datetime, reason: str) -> None:
        """Put settled cash in: a deposit, a transfer back from the deposit
        account, or the cash leg of a corporate action."""
        if amount < 0:
            raise ValueError(f'a credit must be non-negative, got {amount}')
        self._settled += amount

    def levy(self, charge: Charge, *, debit: bool = True) -> None:
        """Record one charge, and by default debit it.

        Args:
            debit: ``False`` for a charge **withheld at source** out of sale
                proceeds. Those are already netted out of the amount passed to
                :meth:`credit_pending`, so debiting them here as well would
                charge the investor twice -- but they must still appear in
                ``session.charges()``, or the itemisation silently omits the
                largest charge on every sale. Not in the interface contract's
                signature; a trailing keyword, defaulting to the contract's
                behaviour.

        Raises:
            ValueError: if the charge belongs to the derivatives pool. There
                is no auto-transfer between the two pools in Vietnam, and
                paying a derivatives charge out of securities cash would
                invent one.
        """
        if charge.pool is not Pool.SECURITIES:
            raise ValueError(
                f'charge {charge.kind!r} is levied on the {charge.pool.value} '
                f'pool and cannot be debited from securities cash: the pools '
                f'are segregated and no auto-transfer exists'
            )
        self._charges.append(charge)
        if debit:
            self.debit(charge.total, charge.ts, reason=charge.kind)


# --------------------------------------------------------------------------
# Charges -- estimate for the encumbrance, assess at the fill
# --------------------------------------------------------------------------

#: Charge bases that a single fill can be priced against. The other two --
#: ``PER_OPEN_CONTRACT_PER_DAY`` and ``MONTHLY_PER_SECURITY`` -- are holding
#: charges: custody is billed monthly per security and the VSD position
#: maintenance fee accrues per open contract per day, and no per-fill model can
#: express either (rulebook 12.2). They are skipped here rather than
#: approximated, and a Tier 2 daily/monthly pass owns them.
_FILL_BASES: FrozenSet[ChargeBase] = frozenset({
    ChargeBase.TRADE_VALUE,
    ChargeBase.PER_CONTRACT,
    ChargeBase.PER_TRADE,
})

#: Bases whose ``amount`` is charged per unit of the base rather than flat.
_COUNT_BASES: FrozenSet[ChargeBase] = frozenset({ChargeBase.PER_CONTRACT})


def _base_value(rule: ChargeRule, venue: Venue, quantity: int,
                price: Decimal) -> Optional[Decimal]:
    """What this rule's rate or amount is applied to, or None if not per-fill."""
    if rule.base is ChargeBase.TRADE_VALUE:
        return trade_value(venue, quantity, price)
    if rule.base is ChargeBase.PER_CONTRACT:
        return Decimal(quantity)
    if rule.base is ChargeBase.PER_TRADE:
        return Decimal('1')
    return None


def _charge_amount(rule: ChargeRule, base_value: Decimal) -> Decimal:
    """One charge's dong amount, clamped by ``minimum``/``maximum``.

    ``rate`` multiplies the base value; ``amount`` is per unit for a counted
    base (per contract) and flat otherwise. Rounding to whole dong is the
    declared modelling choice of this module's docstring.
    """
    if rule.rate is not None:
        raw = rule.rate * base_value
    elif rule.amount is not None:
        raw = rule.amount * (base_value if rule.base in _COUNT_BASES
                             else Decimal('1'))
    else:
        raise ValueError(
            f'charge rule {rule.charge_id!r} sets neither rate nor amount')
    if rule.minimum is not None:
        raw = max(raw, rule.minimum)
    if rule.maximum is not None:
        raw = min(raw, rule.maximum)
    return _to_dong(raw)


def _vat(rule: ChargeRule, amount: Decimal) -> Decimal:
    """VAT on one charge, off unless the row says otherwise.

    Per-charge rather than global because the source material conflicts:
    state-set prices were VAT-exempt to 2025-04-28 and VAT-exclusive from
    2025-04-29, yet brokers demonstrably billed VSDC derivatives charges
    grossed up 10% during the exemption (rulebook 12.1). The conflict is
    carried, not resolved.
    """
    if not rule.vat_applies:
        return Decimal('0')
    return _to_dong(amount * rule.vat_rate)


def _rows(rules: 'RuleSet', profile: Optional[BrokerProfile], venue: Venue,
          cls_: ChargeClass) -> Tuple[ChargeRule, ...]:
    """The dated exchange/state/VSD rows, plus the broker's own commission.

    Two sources because they are two kinds of fact: ``RuleSet.charges``
    refuses to return a ``BROKER`` row and ``BrokerProfile`` holds nothing
    else.
    """
    exchange_rows = tuple(rules.charges(venue, cls_))
    broker_rows = tuple(profile.commission) if profile is not None else ()
    return exchange_rows + broker_rows


def estimate_charges(
    rules: 'RuleSet',
    order: Order,
    venue: Venue,
    cls_: ChargeClass,
    price: Decimal,
    *,
    profile: Optional[BrokerProfile] = None,
) -> Decimal:
    """Worst-case charges on a hypothetical fill, for the buy encumbrance.

    Estimated charges sit **inside** the encumbrance (design section 7.0) so
    that ``available`` stays consistent with what a fill will actually cost.
    Leaving them out lets a caller rest a buy it can fund the shares of and not
    the fees.

    ``price`` is the price the reservation is taken at -- the limit price for
    an LO, the ceiling for the market and auction families -- so the estimate
    is a worst case in the same sense the reservation is.

    Args:
        profile: the broker's commission rows. Not in the interface contract's
            signature, which passes only a ``RuleSet``; but ``RuleSet.charges``
            refuses to return ``BROKER`` rows by design, so without this the
            estimate omits the single largest charge on a retail equity trade
            and under-funds every buy. Added as a trailing keyword so the
            promised positional call still type-checks.

    Charges debited ``DAILY`` are included in the estimate although
    :func:`assess_charges` does not levy them: a commission that tiers on the
    day's total traded value is not knowable at fill time (rulebook 12.2), and
    a reservation that ignored it would under-fund. Over-reserving is the
    conservative direction and the reservation is released in full at the
    terminal edge either way.
    """
    total = Decimal('0')
    for rule in _rows(rules, profile, venue, cls_):
        if rule.debited_at is DebitedAt.MONTHLY:
            continue
        if rule.base not in _FILL_BASES:
            continue
        if not rule.applies(venue, cls_, order.side):
            continue
        base_value = _base_value(rule, venue, order.quantity, price)
        if base_value is None:
            continue
        amount = _charge_amount(rule, base_value)
        total += amount + _vat(rule, amount)
    return _to_dong(total)


def assess_charges(
    rules: 'RuleSet',
    profile: BrokerProfile,
    fill: Fill,
    cls_: ChargeClass,
) -> Tuple[Charge, ...]:
    """The charges actually levied on one fill.

    ``debited_at == FILL`` rows only. ``DAILY`` rows (broker commission, whose
    tier is only known at the daily close) and ``MONTHLY`` rows (custody, the
    VSD collateral fee) are deliberately not levied here; accruing them is a
    Tier 2 daily/monthly pass, and pricing them per fill would silently pick
    the wrong commission tier.

    Rounding each charge to whole dong is a **modelling choice** and must be
    reported as one -- no Vietnamese source states a rounding rule for any fee
    or tax.
    """
    levied: List[Charge] = []
    for rule in _rows(rules, profile, fill.venue, cls_):
        if rule.debited_at is not DebitedAt.FILL:
            continue
        if rule.base not in _FILL_BASES:
            continue
        if not rule.applies(fill.venue, cls_, fill.side):
            continue
        base_value = _base_value(rule, fill.venue, fill.quantity, fill.price)
        if base_value is None:
            continue
        amount = _charge_amount(rule, base_value)
        levied.append(Charge(
            kind=rule.charge_id, venue=fill.venue, base=rule.base,
            base_value=base_value, amount=amount, levied_by=rule.levied_by,
            pool=rule.pool, ts=fill.ts, ticker=fill.ticker,
            order_id=fill.order_id, fill_id=fill.fill_id,
            vat=_vat(rule, amount),
        ))
    return tuple(levied)


# --------------------------------------------------------------------------
# The securities account -- where the stateful admission checks live
# --------------------------------------------------------------------------

class SecuritiesAccount:
    """``CashLedger`` + ``HoldingsLedger`` + the shared ``EncumbranceLedger``.

    The stateful admission checks live here so that they run **around**
    ``Exchange.admits()`` and never inside it. ``admits()`` judges the order
    against the market -- tick grid, round lot, band, phase -- and cannot see
    an account; putting an affordability test inside it is the forbidden build
    of locked shape 2, and it would also break the ~20 existing tests that
    call ``admits()`` with no account at all.

    The call order in ``submit()`` is normative: ``admits()`` first, then
    ``reserve_*``. An order that breaches the tick grid is a tick-grid
    rejection whether or not the caller could have afforded it, and inverting
    the two changes the per-rule composition of the rejection log.
    """

    def __init__(
        self,
        ref: AccountRef,
        cash: CashLedger,
        holdings: HoldingsLedger,
        encumbrances: EncumbranceLedger,
        profile: Optional[BrokerProfile] = None,
    ) -> None:
        """
        Args:
            profile: the broker's commission rows, for the charge estimate
                inside a buy reservation. Not in the interface contract's
                signature; a trailing optional parameter, and ``None`` simply
                means the estimate carries state/exchange/VSD charges only.
        """
        self.ref = ref
        self.cash_ledger = cash
        self.holdings_ledger = holdings
        self.encumbrances = encumbrances
        self.profile = profile

    # -- read models ----------------------------------------------------

    def cash(self) -> Cash:
        """``session.cash()``."""
        return self.cash_ledger.cash()

    def holding(self, ticker: str) -> Holding:
        """``session.holdings(ticker)``."""
        return self.holdings_ledger.holding(ticker)

    # -- reservation ----------------------------------------------------

    def reserve_for_buy(
        self,
        order_id: OrderId,
        order: Order,
        venue: Venue,
        state: MarketState,
        rules: 'RuleSet',
        ts: datetime,
        *,
        cls_: ChargeClass = ChargeClass.EQUITY,
    ) -> Union[Encumbrance, Rejected]:
        """100% pre-funding, tested net of every live buy.

        The amount reserved, by order type (design section 7.0):

        ==========================  ===================================
        ``LIMIT`` (LO)              ``qty x limit_price`` + est. charges
        ``MKT``/``MTL``/``MOK``/``MAK``  ``qty x ceiling`` + est. charges
        ``ATO``/``ATC``             ``qty x ceiling`` + est. charges
        ==========================  ===================================

        The market family reserves at the ceiling because that is the code's
        own "buy at ceiling for guaranteed match" semantics; the two auction
        types reserve there because they must be fundable *before* a clearing
        price exists.

        Returns:
            The reservation, or ``Rejected``:

            * ``INSUFFICIENT_CASH`` when ``available`` is short -- **even if
              pending proceeds would cover it**. Equity is 100% pre-funded and
              unadvanced proceeds are not money yet.
            * ``BAND_LIMIT`` with ``verdict=INDETERMINATE`` when a
              ceiling-funded type meets an absent band. The order is never
              funded at a guessed price: absence of a ceiling is a data gap,
              not a rule saying no, and the two must stay countable apart.
        """
        if not self.ref.serves(venue):
            raise ValueError(
                f'{venue.value} does not draw on the {self.ref.pool.value} '
                f'pool; derivatives orders reserve against the segregated '
                f'deposit in deposit.py'
            )
        if order.side is not Side.BUY:
            raise ValueError(
                f'reserve_for_buy got a {order.side} order; a sell reserves '
                f'shares, not cash')

        if order.order_type is OrderType.LIMIT:
            reserve_price = order.limit_price
            if reserve_price is None:
                raise ValueError(
                    'a limit order must carry a limit price; admits() should '
                    'have refused it before the reservation path')
        elif order.order_type in _CEILING_FUNDED:
            reserve_price = state.ceiling
            if reserve_price is None:
                return Rejected(
                    rule=AdmissionRule.BAND_LIMIT,
                    binding_constraint=None,
                    ts=ts,
                    verdict=Verdict.INDETERMINATE,
                    order_id=order_id,
                    detail={'reason': 'no ceiling to fund a market or auction '
                                      'order against',
                            'order_type': order.order_type.value,
                            'band_source': state.band_source.value},
                )
        else:  # pragma: no cover - the enum has no other members
            raise ValueError(f'unfundable order type {order.order_type}')

        value = trade_value(venue, order.quantity, reserve_price)
        estimated = estimate_charges(rules, order, venue, cls_, reserve_price,
                                     profile=self.profile)
        required = value + estimated

        available = self.cash_ledger.cash().available
        if required > available:
            return Rejected(
                rule=StatefulRule.INSUFFICIENT_CASH,
                binding_constraint=available,
                ts=ts,
                order_id=order_id,
                detail={'required': required,
                        'reserve_price': reserve_price,
                        'estimated_charges': estimated,
                        'pending_proceeds':
                            self.cash_ledger.cash().pending_total},
            )

        return self.encumbrances.take(
            order_id, pool_for_venue(venue), ResourceKind.CASH, ts,
            amount=required, ticker=order.ticker,
            estimated_charges=estimated, order_quantity=order.quantity,
        )

    def reserve_for_sell(
        self,
        order_id: OrderId,
        order: Order,
        venue: Venue,
        ts: datetime,
    ) -> Union[Encumbrance, Rejected]:
        """Commit quantity from ``settled``, **never** from ``unsettled``.

        **This is the Tier 1 demo.** Buy FPT, try to sell it the same session,
        and get back ``Rejected(UNSETTLED_HOLDING)`` carrying the instant the
        requested quantity becomes sellable.

        ``sellable_from`` is attached rather than stored, because it is a
        function of the quantity *requested*: 500 shares may be sellable
        tomorrow and 1,000 only the day after, and no single stored instant is
        right for both.

        ``binding_constraint`` is the sellable quantity that bound;
        ``sellable_from`` is when the request clears. They are different
        quantities and are carried in different fields for that reason.
        """
        if not self.ref.serves(venue):
            raise ValueError(
                f'{venue.value} does not draw on the {self.ref.pool.value} '
                f'pool; a SELL on HNXDS opens a short and belongs in '
                f'deposit.py, where it is never checked against holdings'
            )
        if order.side is not Side.SELL:
            raise ValueError(
                f'reserve_for_sell got a {order.side} order; a buy reserves '
                f'cash, not shares')

        holding = self.holdings_ledger.holding(order.ticker)
        if order.quantity > holding.sellable:
            return Rejected(
                rule=StatefulRule.UNSETTLED_HOLDING,
                binding_constraint=holding.sellable,
                ts=ts,
                order_id=order_id,
                sellable_from=holding.sellable_from(order.quantity),
                detail={'requested': order.quantity,
                        'settled': holding.settled,
                        'committed': holding.committed,
                        'unsettled': holding.unsettled_quantity},
            )

        return self.encumbrances.take(
            order_id, pool_for_venue(venue), ResourceKind.SHARES, ts,
            quantity=order.quantity, ticker=order.ticker,
        )

    # -- fills and the terminal hook ------------------------------------

    def apply_fill(
        self,
        fill: Fill,
        settles_at: datetime,
        charges: Sequence[Charge] = (),
    ) -> None:
        """Consume the reservation at the fill price and move the tranches.

        The one place a fill touches the securities pool, so that the three
        movements a fill causes -- release, ledger move, charge -- cannot get
        out of step.

        A **buy** releases its pro-rata slice of the reservation, debits the
        cash actually spent, credits an *unsettled* holdings tranche settling
        at ``settles_at``, and debits the fill charges. The difference between
        the reserved price and the fill price returns to ``available``
        immediately.

        A **sell** releases the committed quantity, debits ``settled``
        holdings, and credits a *pending* proceeds tranche **net of the
        charges withheld at source**. Those charges are recorded but not
        debited again: they are already out of the proceeds, and debiting them
        twice is the classic double-count. Every securities-pool charge on a
        sale is treated as withheld, which is how a Vietnamese contract note
        reads -- the 0.1% personal income tax is deducted at source by law and
        commission is settled out of the same proceeds.
        """
        if fill.quantity <= 0:
            raise ValueError(f'a fill must move positive quantity, got '
                             f'{fill.quantity}')
        if not self.ref.serves(fill.venue):
            raise ValueError(
                f'fill on {fill.venue.value} does not belong to the '
                f'{self.ref.pool.value} pool')

        value = trade_value(fill.venue, fill.quantity, fill.price)
        levied = tuple(charges)
        charge_total = sum((c.total for c in levied), Decimal('0'))

        if fill.side is Side.BUY:
            self.encumbrances.consume(
                fill.order_id, fill.ts, resource=ResourceKind.CASH,
                amount=value + charge_total, quantity=fill.quantity)
            self.holdings_ledger.credit_unsettled(
                fill.ticker, fill.quantity, settles_at, fill.ts,
                fill.order_id)
            self.cash_ledger.debit(value, fill.ts,
                                   reason=f'buy {fill.ticker}')
            for charge in levied:
                self.cash_ledger.levy(charge)
        elif fill.side is Side.SELL:
            self.encumbrances.consume(
                fill.order_id, fill.ts, resource=ResourceKind.SHARES,
                quantity=fill.quantity)
            self.holdings_ledger.debit_settled(
                fill.ticker, fill.quantity, fill.ts)
            self.cash_ledger.credit_pending(
                value - charge_total, settles_at, fill.ts, fill.order_id)
            for charge in levied:
                self.cash_ledger.levy(charge, debit=False)
        else:
            raise ValueError(
                f'{fill.side} cannot move a securities ledger; Side.CROSS is '
                f'an exchange-internal marker with no sign')

    def release(self, order_id: OrderId, ts: datetime) -> None:
        """The terminal hook, wired to ``OrderBookOfRecord.on_terminal``.

        Fires on all four terminal edges -- filled, cancelled, expired,
        rejected -- and is idempotent, so an order that never reserved (a
        rejection) or that has already been released costs nothing. That is
        what makes "a terminal transition that forgets to release" impossible
        by construction: there is one hook and it is unconditional.
        """
        self.encumbrances.release(order_id, ts)

    def settle_due(
        self, now: datetime,
    ) -> Tuple[Tuple[Tuple[str, HoldingTranche], ...],
               Tuple[ProceedsTranche, ...]]:
        """Settle both legs at one instant. Returns ``(securities, cash)``.

        Cash and securities settle by DVP at the depository and are allocated
        to the client in a single event (rulebook 5.1): there is no version of
        this where the shares land and the money does not. Driving both from
        one call is how that stays true, and it is why the two ledgers take
        the same ``now``.

        Not in the interface contract, which drives the two ledgers
        separately; this exists so a caller cannot settle one leg and forget
        the other. The securities leg carries its ticker because
        ``Event.settlement_credited`` needs one and ``HoldingTranche`` has no
        ticker field.
        """
        moved = self.holdings_ledger.settle_due_by_ticker(now)
        proceeds = self.cash_ledger.settle_due(now)
        return moved, proceeds
