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
* **The annualisation basis for daily financing rates is 365, by
  declaration.** The sources mix bases -- rulebook 8.3 records that the
  0.025-0.05%/day advance range is annualised x360 while DSC's "0.0356%/day =
  13%/yr" is x365, a systematic ~1.4% difference -- so 12.1 requires one basis
  be chosen *and recorded in the config*. It is recorded in
  :attr:`AdvanceTerms.annualisation_basis`, not baked into the arithmetic.
  Accrual itself counts actual calendar days and never reads a year length.

The one brokerage **product** modelled here is *ung truoc tien ban*, the
advance against unsettled sale proceeds (:class:`AdvanceTerms`,
:class:`SaleAdvance`). It earns its place because rulebook 12.7 is blunt about
the consequence of leaving it out: it "is the only way to recycle sale
proceeds intraday, and it must be charged for -- otherwise the backtest
overstates achievable turnover". Its legal status is sourced and its cost
formula is sourced; its rate, its cap and its day-count are not, and every
unsourced default says so in :attr:`AdvanceTerms.PROVENANCE`.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import (TYPE_CHECKING, Dict, FrozenSet, List, Mapping, Optional,
                    Sequence, Tuple, Union)

from plutus.core.order import OrderType, Side
from plutus.market.broker import BrokerTerms
from plutus.market.protocol import MarketState, Order
# The charge table is its own module -- design section 6.1's "one generic
# table, per venue", dated and cited. ``charges.py`` imports nothing from
# here, so the money conversions live with the charge bases they exist to
# serve rather than inside the account that happens to spend them.
from plutus.market.session.charges import (ChargeContext, CommissionSchedule,
                                           to_dong as _to_dong, trade_value)
from plutus.market.session.charges import assess as _assess_charges
from plutus.market.session.charges import estimate as _estimate_charges
from plutus.market.session.types import (AccountRef, BrokerProfile, Cash,
                                         Charge, ChargeClass, Encumbrance,
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
    'ANNUALISATION_BASIS_360',
    'ANNUALISATION_BASIS_365',
    'AdvanceTerms',
    'CashLedger',
    'EncumbranceLedger',
    'HoldingsLedger',
    'SaleAdvance',
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


# ``_to_dong`` (round a charge to whole dong, half up) and ``trade_value``
# (the cash-venue thousands-of-dong conversion) are imported from
# ``charges.py`` above rather than defined here. Both are properties of the
# charge table, not of the account: a second copy of either is a second answer
# to "what does this trade cost", and the rounding in particular is a declared
# modelling choice that must be made in exactly one place.


def _floor_dong(amount: Decimal) -> Decimal:
    """Round a **cap** down to whole dong.

    Same declared modelling choice as :func:`_to_dong` -- no source states a
    rounding rule -- but deliberately the other rounding. This one is applied
    to a *ceiling* on how much may be advanced, and half-up on a ceiling can
    hand out half a dong more than the ceiling allows. A cap must never be
    exceeded by its own rounding.
    """
    return amount.quantize(_DONG, rounding=ROUND_DOWN)


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

        The primitive under ``session/corporate.py``. It was written for Tier
        1 with no engine above it -- a declared limitation, design section 15
        item 5 -- so that the engine would not later be retrofitted into a
        scalar: a split scales open parcels *without collapsing them*, so
        their distinct settlement instants survive the adjustment, and that is
        only possible because the holding is a list.

        ``factor`` multiplies quantity (2 for a 1:1 bonus, 1 for a pure cash
        dividend). ``cash_per_share`` is the **gross** cash leg per share held,
        in **VND**, not in the venue's quote unit. The 5% dividend withholding
        tax is deliberately *not* applied here: it is a charge row, and
        inventing it inside the holdings ledger would put a tax rate somewhere
        no charge table can see it.

        **The entitlement is settled by the RECORD DATE, not by settlement
        state**, which is why the cash leg is computed on ``holding.total``
        and counts unsettled parcels. The rule is the *ngay dang ky cuoi
        cung*, and under T+2 it is struck one settlement cycle after the
        ex-date precisely so that a buyer who traded on the last cum-rights
        session -- whose parcel is still unsettled on the ex-date itself -- is
        on the register when it is. Pricing the entitlement off settlement
        state would deny the dividend to exactly the buyer the T+2 cycle was
        designed to include, and would do it silently. The mirror needs no
        special handling: a parcel sold before the ex-date left ``settled`` at
        the fill and draws nothing.

        **The open question is now answered, and not here.** Whether an order
        live across the ex-date is cancelled or scaled is decided by
        ``corporate.RestingOrderPolicy``, which defaults to cancelling; the
        rulebook does not settle it, and it does not settle it because
        rulebook 2.3 makes the situation unreachable in the market (no
        Vietnamese order type survives a session close). This hook still
        touches no order: it moves quantity and reports cash, and the engine
        composes the rest.

        Returns:
            ``(cash_leg, new_unsettled_tranches)``. The caller credits the
            cash -- this ledger holds no cash.
        """
        if factor <= 0:
            raise ValueError(f'a corporate-action factor must be positive, '
                             f'got {factor}')
        holding = self.holding(ticker)
        cash_leg = cash_per_share * Decimal(holding.total)

        # An action on a ticker this account has never held must leave no
        # trace. Writing the zero back would put the ticker into
        # :meth:`tickers`, which is the account's own answer to "what did this
        # run touch" and is what a corporate-action audit sweeps -- so a
        # market-wide schedule applied blindly would report exposure to every
        # name in it.
        if not holding.total and ticker not in self._settled:
            return cash_leg, ()

        self._settled[ticker] = int(Decimal(holding.settled) * factor)
        scaled = [t.scaled(factor) for t in self._unsettled.get(ticker, ())]
        self._unsettled[ticker] = scaled
        return cash_leg, tuple(scaled)


# --------------------------------------------------------------------------
# ung truoc tien ban -- the advance against unsettled sale proceeds
# --------------------------------------------------------------------------

#: The two annualisation bases the sources mix. Rulebook 8.3 records the
#: conflict verbatim: the 0.025-0.05%/day broker range is annualised as
#: "9-18% p.a." on a **360**-day year, while DSC's "0.0356%/day = 13%/yr" is a
#: **365**-day year (0.0356 x 365 = 12.99). A sweep configured from both rows
#: is internally inconsistent by ~1.4%, so one basis must be declared.
ANNUALISATION_BASIS_360 = 360
ANNUALISATION_BASIS_365 = 365

#: **THE DECLARED BASIS OF THIS MODULE IS 365.** Rulebook 12.1's convention
#: table: "Declare one basis and use it. The source material mixes x360 and
#: x365, producing a ~1.4% inconsistency. Recommend 365 with the basis
#: recorded in the config." It is recorded in the config -- it is a field on
#: :class:`AdvanceTerms`, not a constant baked into the accrual -- so a caller
#: reading a 360-basis quote can say so and get the arithmetic that quote
#: meant. Nothing in this module reads this name except the default.
DECLARED_ANNUALISATION_BASIS = ANNUALISATION_BASIS_365


@dataclass(frozen=True)
class AdvanceTerms:
    """The commercial terms of *ung truoc tien ban*, and the conventions.

    A **broker term, not an exchange rule**, and the clearest illustration of
    why the two config objects are separate: the exchange never sees it, the
    depository never sees it, and two investors selling the same shares on the
    same day through different firms pay different amounts for it. The
    statutory layer says only that a brokerage-licensed firm *may* offer the
    service with prior written SSC approval (Luat Chung khoan 54/2019 Art.
    86(1)(b), rulebook 8.4) and that it is **self-priced** -- neither TT
    128/2018 nor TT 102/2021 lists a price for it, so it falls under the
    unlisted-services clause and each firm sets its own charge (rulebook 8.3,
    *high* confidence on that structural claim).

    :class:`~plutus.market.broker.BrokerTerms` owns the two facts a caller is
    most likely to want to set -- whether the firm offers the product at all,
    and the daily rate -- because Tier 1 put them there. This object owns the
    rest, and exists because three of its four remaining fields are things
    **no source fixes** and which a published result may be sensitive to. Use
    :meth:`from_broker` to derive one from a :class:`BrokerTerms`.

    Attributes:
        daily_rate: interest per calendar day, as a fraction of the amount
            advanced. ``fee = amount_advanced x days_advanced x daily_rate``
            is the sourced *structure* (rulebook 8.3, 12.7); the number is a
            broker's own.
        annualisation_basis: days per year used to convert between this daily
            rate and an annual one. **365 by declaration** -- see
            :data:`DECLARED_ANNUALISATION_BASIS`. Never read during accrual,
            which is per-day; it is read by :attr:`annual_rate` and
            :meth:`from_annual_rate`, which are the only two places the
            conflict can bite.
        max_advanceable_fraction: the cap, as a fraction of the tranche's net
            proceeds. **UNSOURCED.** Rulebook 8.3 and 12.7 both say so in
            terms: "up to 100% of net proceeds after fees and PIT" is the
            common description, not a sourced figure -- no statutory cap
            exists and no broker fee schedule stating an explicit maximum
            percentage could be retrieved (*low* confidence). The default is
            that unsourced 100%, and it is an **assumption** that any
            published result must state.
        minimum_charge: a per-advance floor on the interest, applied once when
            the advance is recovered. ``None`` means no minimum, which is what
            several firms do. **UNSOURCED in both value and unit**: rulebook
            8.3 lists VSCS at 30,000 and SSI at 50,000 but flags that
            Vietnamese fee schedules often quote thousand-dong, so the figure
            may be 30,000d or 30,000,000d. Left ``None`` by default rather
            than guessing which.
        auto_register: whether the firm's standing registration advances each
            new tranche in full the moment the sell fills. Rulebook 8.3's
            mechanics row: "On registration the advance is credited to buying
            power immediately after the sell order fills on T". ``True``
            preserves the Tier 1 behaviour. Set ``False`` for a firm where the
            investor asks per sale, which is the path
            :meth:`CashLedger.request_advance` exists for.

    Note that ``max_advanceable_fraction`` is applied to the tranche's **net**
    amount -- net of the 0.1% PIT withheld at source and of commission -- for
    free, because :meth:`CashLedger.credit_pending` already receives the net.
    That is what "after fees and PIT" means and it is why the description can
    be honoured without a second charge model.
    """

    daily_rate: Decimal
    annualisation_basis: int = DECLARED_ANNUALISATION_BASIS
    max_advanceable_fraction: Decimal = Decimal('1')
    minimum_charge: Optional[Decimal] = None
    auto_register: bool = True

    #: Where each of these came from. Read before quoting any of them. The
    #: counterpart of :attr:`BrokerTerms.PROVENANCE`, and the same rule: every
    #: default here is a plausible market value, not a sourced one.
    PROVENANCE = {
        'daily_rate': 'broker term, self-priced, no statutory cap; observed '
                      '0.00025-0.0005/day (rulebook 12.7, medium). The '
                      'formula amount x days x rate is sourced; the number '
                      'is not',
        'annualisation_basis': 'DECLARED, not sourced. The sources mix x360 '
                               'and x365 and disagree by ~1.4%; rulebook '
                               '12.1 recommends 365 and requires the choice '
                               'be recorded in the config',
        'max_advanceable_fraction': 'ASSUMPTION. "Up to 100% of net proceeds '
                                    'after fees and PIT" is a common '
                                    'description, not a sourced figure; no '
                                    'statutory cap exists and no broker '
                                    'schedule stating a maximum was '
                                    'retrieved (rulebook 8.3, low)',
        'minimum_charge': 'UNSOURCED in value and in unit -- 30,000/50,000 '
                          'are quoted but Vietnamese fee schedules often '
                          'quote thousand-dong (rulebook 8.3). Default None',
        'auto_register': 'market practice: the advance is credited to buying '
                         'power immediately after the sell fills on T (some '
                         'firms T+0 or T+1). Rulebook 8.3, low',
    }

    def __post_init__(self) -> None:
        if self.daily_rate < 0:
            raise ValueError(f'an advance daily_rate must not be negative, '
                             f'got {self.daily_rate}')
        if self.annualisation_basis <= 0:
            raise ValueError(f'annualisation_basis must be positive, got '
                             f'{self.annualisation_basis}')
        if not 0 <= self.max_advanceable_fraction <= 1:
            raise ValueError(
                f'max_advanceable_fraction must lie in [0, 1], got '
                f'{self.max_advanceable_fraction}; above 1 would advance more '
                f'than the sale produced, which is a loan, and a Vietnamese '
                f'securities company may not lend money (TT 121/2020 Art. 27, '
                f'rulebook 8.4)')
        if self.minimum_charge is not None and self.minimum_charge < 0:
            raise ValueError(f'minimum_charge must not be negative, got '
                             f'{self.minimum_charge}')

    @classmethod
    def from_broker(cls, terms: BrokerTerms, **overrides) -> 'AdvanceTerms':
        """Derive the mechanics from a :class:`BrokerTerms`' daily rate.

        ``terms.advance_on_sale_enabled`` is deliberately **not** copied here.
        Whether the firm offers the product is a fact about the firm and stays
        on ``BrokerTerms``, where Tier 1 put it and where
        :meth:`CashLedger.credit_pending` reads it; this object says only what
        the terms are *if* it is offered. Two objects, one fact each.
        """
        return cls(daily_rate=terms.advance_on_sale_daily_rate, **overrides)

    @classmethod
    def from_annual_rate(
        cls,
        annual_rate: Decimal,
        *,
        annualisation_basis: int = DECLARED_ANNUALISATION_BASIS,
        **overrides,
    ) -> 'AdvanceTerms':
        """Terms from an annual quote, on an explicitly named basis.

        This is where the conflict rulebook 8.3 flags actually bites. DSC
        quotes "0.0356%/day = 13%/yr", which is x365; the 0.025-0.05%/day
        industry range is annualised elsewhere as "9-18% p.a.", which is x360.
        Feeding one annual figure through the other basis misprices the
        advance by ``365/360 - 1`` = ~1.39%, and the error is systematic
        rather than noisy. There is no default that is right for both, so the
        basis is a named argument, it is stored on the result, and
        :attr:`annual_rate` inverts with the same number.
        """
        basis = Decimal(annualisation_basis)
        return cls(daily_rate=Decimal(annual_rate) / basis,
                   annualisation_basis=annualisation_basis, **overrides)

    @property
    def annual_rate(self) -> Decimal:
        """The daily rate annualised on **this object's own basis**.

        Reported, never used in accrual. Accrual is ``amount x rate x days``
        over actual calendar days, so it never touches a year length; this
        exists so a caller can print a comparable headline number and so that
        the number it prints cannot silently be on a different basis from the
        one the terms were built with.
        """
        return self.daily_rate * Decimal(self.annualisation_basis)


@dataclass(frozen=True)
class SaleAdvance:
    """One drawdown against one unsettled proceeds tranche.

    Deliberately **not** a boolean on the tranche. Tier 1 carried
    ``ProceedsTranche.advanced``, which can express "this whole tranche is
    financed" and nothing else -- not a partial draw, not two draws taken on
    different days at different points in the accrual, and not the repayment
    instant. A cap phrased as "up to 100%" is meaningless if the only
    representable draw is exactly 100%.

    ``amount`` is the principal and is always strictly positive: a tranche
    whose net proceeds are negative is never advanced (see
    :meth:`CashLedger.request_advance`).

    ``settles_at`` is copied from the tranche rather than referenced, because
    it is the instant the advance is **repaid** and interest stops, and an
    advance that could not answer that question on its own would have to be
    read together with a tranche to be interpreted at all.

    ``accrued_to`` is the watermark, moved by whole days only, so repeated
    :meth:`CashLedger.accrue_interest` calls never double-charge a day and
    never lose a part-day -- it is carried.
    """

    advance_id: str
    amount: Decimal
    taken_at: datetime
    settles_at: datetime
    accrued_to: datetime
    interest_accrued: Decimal = Decimal('0')
    source_order_id: Optional[OrderId] = None
    repaid_at: Optional[datetime] = None

    @property
    def is_outstanding(self) -> bool:
        """Whether the broker is still owed this principal.

        The one thing ``Cash.advanced`` sums over. A repaid advance keeps its
        row so its interest stays itemised, but it is no longer spendable
        money and must not appear in ``available``.
        """
        return self.repaid_at is None

    @property
    def days_accrued(self) -> int:
        """Whole calendar days interest has actually been charged for."""
        return (self.accrued_to - self.taken_at).days


@dataclass
class _PendingRow:
    """A pending tranche and the advances drawn against it.

    Private, and the reason :class:`CashLedger` no longer stores a bare list
    of tranches. ``ProceedsTranche`` lives in ``types.py`` and cannot grow an
    ``advances`` field from here, so the association lives in the ledger --
    which is the right place anyway: an advance is a fact about the account's
    relationship with its broker, not about the sale.

    ``tranche`` is stored **exactly as credited and is never replaced**. That
    is load-bearing: it makes ``(amount, settles_at, source_order_id)`` a
    stable key over the tranche's whole life, which is what lets a caller
    hand a tranche back to :meth:`CashLedger.request_advance` and have it
    name the same parcel. Tier 1 replaced the tranche object on every accrual,
    so no caller-held tranche stayed valid for longer than one call.
    """

    tranche: ProceedsTranche
    advances: List[SaleAdvance] = field(default_factory=list)

    @property
    def outstanding_advance(self) -> Decimal:
        return sum((a.amount for a in self.advances if a.is_outstanding),
                   Decimal('0'))

    @property
    def drawn(self) -> Decimal:
        """Principal drawn against this tranche, repaid or not.

        Repaid draws still count against the cap. Once the tranche has
        settled it is gone from the ledger entirely, so the only way to see a
        repaid draw here would be a bug.
        """
        return sum((a.amount for a in self.advances), Decimal('0'))


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
        *,
        advance_terms: Optional[AdvanceTerms] = None,
    ) -> None:
        """
        Args:
            advance_terms: the mechanics of *ung truoc tien ban* -- the cap,
                the annualisation basis, the per-advance minimum, whether the
                firm auto-registers. Not in the interface contract's
                signature, which passes only a ``BrokerTerms``; a trailing
                keyword defaulting to :meth:`AdvanceTerms.from_broker`, so
                every existing three-argument construction keeps the Tier 1
                behaviour exactly. ``terms.advance_on_sale_enabled`` still
                decides whether the product exists at all.
        """
        self._settled = Decimal(initial_cash)
        self._terms = terms
        self._advance_terms = (advance_terms
                               if advance_terms is not None
                               else AdvanceTerms.from_broker(terms))
        self._encumbrances = encumbrances
        self._rows: List[_PendingRow] = []
        self._charges: List[Charge] = []
        #: Cumulative interest on advances, including advances that have since
        #: settled. Reported, never netted.
        self._interest_accrued = Decimal('0')
        #: Advances recovered at settlement, kept so the cost of a closed
        #: advance stays itemised after its tranche has left the ledger.
        self._repaid: List[SaleAdvance] = []
        self._next_advance = 1

    # -- reading --------------------------------------------------------

    @property
    def advance_terms(self) -> AdvanceTerms:
        """The advance's commercial terms. Read them before quoting a cost."""
        return self._advance_terms

    def cash(self) -> Cash:
        """The read model. ``available`` is derived, never stored."""
        return Cash(
            settled_balance=self._settled,
            committed=self._encumbrances.outstanding(
                pool=Pool.SECURITIES, resource=ResourceKind.CASH),
            advanced=self.advanced(),
            interest_accrued=self._interest_accrued,
            pending_proceeds=tuple(self._view(row) for row in self._rows),
        )

    def advanced(self) -> Decimal:
        """Unsettled proceeds made spendable early by the sale advance.

        The sum of **outstanding principal**, not of financed tranches: a
        tranche advanced 60% contributes 60%, and a tranche whose advance has
        been recovered at settlement contributes nothing. Zero unless the
        broker offers *ung truoc tien ban* and the caller enabled it. It is a
        **broker term, not an exchange rule** -- which is the clearest
        illustration of why the two config objects are separate.
        """
        return sum((row.outstanding_advance for row in self._rows),
                   Decimal('0'))

    def advances(self, *, include_repaid: bool = False
                 ) -> Tuple[SaleAdvance, ...]:
        """Every drawdown, in the order it was taken.

        Args:
            include_repaid: also return advances already recovered out of a
                settlement. They are kept because their interest is a real
                cost that must stay itemised after the tranche is gone, and
                excluded by default because the usual question is what is
                still owed.
        """
        live = [a for row in self._rows for a in row.advances
                if include_repaid or a.is_outstanding]
        if include_repaid:
            live = self._repaid + live
        return tuple(sorted(live, key=lambda a: (a.taken_at, a.advance_id)))

    def advanceable(
        self,
        *,
        tranche: Optional[ProceedsTranche] = None,
        order_id: Optional[OrderId] = None,
        now: Optional[datetime] = None,
    ) -> Decimal:
        """How much may still be drawn, over the selected pending tranches.

        **Zero at a firm that does not offer the product**, whatever the
        tranches hold. ``terms.advance_on_sale_enabled`` is the fact about the
        firm (:meth:`AdvanceTerms.from_broker` says so in terms), and
        :meth:`request_advance` already refuses outright when it is unset, so
        without this guard the two methods answered differently about the same
        firm: a caller sizing an order off ``advanceable()`` would be told it
        had headroom and then be refused ``INSUFFICIENT_CASH`` for spending
        it. A read model that disagrees with the action it describes is worse
        than no read model.

        The bound is ``max_advanceable_fraction x net_proceeds`` less what has
        already been drawn, floored to whole dong (:func:`_floor_dong` -- a
        cap must not be exceeded by its own rounding), summed over the
        selection. Zero for a tranche whose net is not positive, and zero once
        ``now`` has reached a tranche's settlement instant: there is nothing
        left to advance *against* when the money is already due.

        **The 100% default is an assumption, not a rule.** Rulebook 8.3 and
        12.7 both record that "up to 100% of net proceeds after fees and PIT"
        is the common description of the product and *not* a sourced figure --
        no statutory cap exists and no broker schedule stating an explicit
        maximum could be retrieved. See
        :attr:`AdvanceTerms.max_advanceable_fraction`.

        Args:
            tranche: name one parcel. Matched on ``(amount, settles_at,
                source_order_id)`` -- the tranche's economic identity, which
                never changes -- not on object identity, so a tranche read out
                of an older ``cash()`` still names the same parcel.
            order_id: name every parcel from one sell order. A partially
                filled order produces one tranche per fill and they are
                separate parcels settling separately, so this selects all of
                them.
            now: the instant to judge maturity at. ``None`` means "do not
                exclude matured tranches", which is the right answer for a
                caller that only wants the headline number.
        """
        if not self._terms.advance_on_sale_enabled:
            return Decimal('0')
        rows = self._select(tranche=tranche, order_id=order_id)
        return sum((self._headroom(row, now) for row in rows), Decimal('0'))

    def charges(self) -> Tuple[Charge, ...]:
        """Everything levied so far, itemised. Backs ``session.charges()``."""
        return tuple(self._charges)

    # -- the advance: selection, bound, view ----------------------------

    @staticmethod
    def _key(tranche: ProceedsTranche) -> Tuple:
        """A pending tranche's economic identity.

        ``amount``, ``settles_at`` and ``source_order_id`` are the three
        fields that are fixed the moment the sale fills. ``accrued_at`` and
        ``interest_accrued`` are not in the key because they are financing
        state, and ``advanced`` is not because it is exactly what the caller
        is asking to change.
        """
        return (tranche.amount, tranche.settles_at, tranche.source_order_id)

    def _select(
        self,
        *,
        tranche: Optional[ProceedsTranche] = None,
        order_id: Optional[OrderId] = None,
    ) -> List[_PendingRow]:
        """The pending rows a request names, in settlement order.

        Settlement order matters: a request that spans two tranches draws on
        the one that settles first, so the advance with the shortest life --
        and therefore the smallest interest bill -- is used up first. That is
        the cheaper allocation for the investor and the one a broker's own
        recovery order implies, but no source states it, so it is a **declared
        choice**.

        Raises:
            ValueError: if both selectors are given. They would have to be
                intersected, and a request that silently matched nothing
                because its two selectors disagreed is the kind of quiet
                no-op this module refuses everywhere else.
        """
        if tranche is not None and order_id is not None:
            raise ValueError(
                'name a tranche or an order id, not both: the two selectors '
                'would have to be intersected and a request that silently '
                'matched nothing is worse than a refusal')
        rows = self._rows
        if tranche is not None:
            key = self._key(tranche)
            rows = [r for r in rows if self._key(r.tranche) == key]
        elif order_id is not None:
            rows = [r for r in rows if r.tranche.source_order_id == order_id]
        return sorted(rows, key=lambda r: r.tranche.settles_at)

    def _headroom(self, row: _PendingRow,
                  now: Optional[datetime] = None) -> Decimal:
        """What may still be drawn against one tranche. Never negative."""
        if row.tranche.amount <= 0:
            return Decimal('0')
        if now is not None and row.tranche.settles_at <= now:
            return Decimal('0')
        cap = _floor_dong(row.tranche.amount
                          * self._advance_terms.max_advanceable_fraction)
        return max(cap - row.drawn, Decimal('0'))

    def _view(self, row: _PendingRow) -> ProceedsTranche:
        """The tranche as the caller sees it, financing state folded in.

        The stored tranche is never mutated (see :class:`_PendingRow`), so the
        three fields that *do* move are recomputed here from the advances:
        ``advanced`` is true while any principal is outstanding -- including a
        partial draw, because a partly financed tranche is financed --
        ``interest_accrued`` is the sum over its advances, and ``accrued_at``
        is the furthest watermark any of them has reached.
        """
        if not row.advances:
            return row.tranche
        return replace(
            row.tranche,
            advanced=any(a.is_outstanding for a in row.advances),
            interest_accrued=sum((a.interest_accrued for a in row.advances),
                                 Decimal('0')),
            accrued_at=max(a.accrued_to for a in row.advances),
        )

    # -- movements ------------------------------------------------------

    def credit_pending(
        self,
        amount: Decimal,
        settles_at: datetime,
        ts: datetime,
        order_id: Optional[OrderId] = None,
    ) -> ProceedsTranche:
        """A sell filled: the net pends until ``settles_at``.

        ``amount`` must **already be net of the sell-side charges withheld at
        source**. The 0.1% personal income tax on a securities transfer is
        sell-side only and the broker deducts it from the proceeds, so a sale
        credits net; carrying gross here and netting later is how a sale ends
        up wrong by more than most commissions.

        **The net may be negative, and that is an ordinary case rather than a
        contradiction.** A broker per-order minimum (rulebook 8.3 and 12.7,
        both broker terms) exceeds the gross whenever the sale is small
        enough, and Vietnamese penny stocks quote at 1.0-3.0 thousand dong.
        This method used to refuse a negative amount, and the refusal landed
        *after* ``SecuritiesAccount.apply_fill`` had already removed the
        shares -- destroying them. The trade matched at the exchange, so it
        stands: the tranche carries the net with its sign and settles against
        the balance at T+2 like any other. See
        :meth:`SecuritiesAccount.apply_fill` for why the fill is not refused
        instead, and for the declared assumption about *when* the shortfall
        is collected, which no source states.

        When ``terms.advance_on_sale_enabled`` and the firm auto-registers
        (:attr:`AdvanceTerms.auto_register`, the default) the tranche is
        advanced up to the cap immediately and that amount is spendable at
        once, accruing interest at the broker's daily rate until it settles.
        Rulebook 8.3's mechanics row: "On registration the advance is credited
        to buying power immediately after the sell order fills on T". With
        ``auto_register=False`` nothing is drawn and the investor must ask --
        see :meth:`request_advance`.

        **A negative net is never advanced**, whatever the terms say.
        Rulebook 8.3 describes the product as advancing "up to 100% of net
        proceeds after fees and PIT" -- itself flagged there as an unsourced
        common description rather than a cap anyone published -- and 100% of
        a negative net is nothing to lend. Marking one advanced would raise
        ``available`` on a sale that lost money and accrue negative interest,
        paying the investor for owing the broker.
        """
        row = _PendingRow(tranche=ProceedsTranche(
            amount=amount, settles_at=settles_at, accrued_at=ts,
            source_order_id=order_id,
        ))
        self._rows.append(row)
        if (self._terms.advance_on_sale_enabled
                and self._advance_terms.auto_register):
            headroom = self._headroom(row, ts)
            if headroom > 0:
                self._draw(row, headroom, ts)
        return self._view(row)

    def request_advance(
        self,
        ts: datetime,
        amount: Optional[Decimal] = None,
        *,
        tranche: Optional[ProceedsTranche] = None,
        order_id: Optional[OrderId] = None,
    ) -> Tuple[SaleAdvance, ...]:
        """Draw an advance against named unsettled proceeds. *Ung truoc tien ban*.

        The investor-initiated half of the product, and the reason the draw is
        a :class:`SaleAdvance` record rather than a flag: the request is for
        *an amount*, against *particular* parcels, and both are things a
        boolean cannot carry. A request spanning two tranches produces two
        advances, because each is recovered out of its own tranche's
        settlement and they can settle on different days.

        Args:
            ts: when the advance is taken. Interest runs from here.
            amount: the principal wanted. ``None`` means "everything
                advanceable on the selection", which is the common case and
                what auto-registration does.
            tranche: draw against one parcel only.
            order_id: draw against every parcel from one sell order.

        Returns:
            The advances created, earliest-settling first. Their principals
            sum to ``amount``.

        Raises:
            ValueError: and deliberately **not** ``Rejected``. Every value in
                :class:`~plutus.market.session.types.StatefulRule` and
                :class:`~plutus.market.verdicts.AdmissionRule` is a reason the
                *market* refused an order, and those two enums are the
                rejected-order log that design section 8 measures. A broker
                declining to advance more than it agreed to is a commercial
                refusal that the exchange never sees; putting it in that log
                would make ``broker_profile`` able to write rows into a
                measurement of what ``exchange_rules`` refused. Refused, not
                clamped, for the same reason: an advance silently smaller than
                asked for shows up later as an unexplained ``INSUFFICIENT_CASH``
                on a buy the caller believed it had funded.
        """
        if not self._terms.advance_on_sale_enabled:
            raise ValueError(
                'this broker does not offer ung truoc tien ban; set '
                'BrokerTerms(advance_on_sale_enabled=True). It is a licensed, '
                'SSC-approved service (Luat Chung khoan 54/2019 Art. 86(1)(b)) '
                'and a firm that has not registered it simply cannot advance')
        if amount is not None and amount <= 0:
            raise ValueError(f'an advance must be for a positive amount, got '
                             f'{amount}')

        rows = self._select(tranche=tranche, order_id=order_id)
        if not rows:
            raise ValueError(
                'no pending proceeds match that selection; there is nothing '
                'to advance against. An advance is a draw on a receivable, '
                'not a loan -- a Vietnamese securities company may not lend '
                '(TT 121/2020 Art. 27, rulebook 8.4)')

        headroom = [self._headroom(row, ts) for row in rows]
        total = sum(headroom, Decimal('0'))
        if total <= 0:
            # Tested before the size of the request, so that "there is nothing
            # here to draw on" never arrives dressed as "you asked for too
            # much". They are different facts and the caller acts on them
            # differently.
            raise ValueError(
                'nothing is advanceable against the selected proceeds: they '
                'are already drawn to the cap, have reached settlement, or '
                'are negative -- a sale that netted below zero has nothing '
                'to advance, and 100% of it is still nothing')
        wanted = total if amount is None else Decimal(amount)
        if wanted > total:
            raise ValueError(
                f'cannot advance {wanted}: at most {total} is advanceable '
                f'against the selected proceeds, at '
                f'{self._advance_terms.max_advanceable_fraction} of net '
                f'proceeds after fees and PIT less what is already drawn. '
                f'That cap is an ASSUMPTION, not a sourced rule -- see '
                f'AdvanceTerms.PROVENANCE')

        drawn: List[SaleAdvance] = []
        remaining = wanted
        for row, room in zip(rows, headroom):
            if remaining <= 0:
                break
            take = min(room, remaining)
            if take <= 0:
                continue
            drawn.append(self._draw(row, take, ts))
            remaining -= take
        return tuple(drawn)

    def _draw(self, row: _PendingRow, amount: Decimal,
              ts: datetime) -> SaleAdvance:
        """Record one drawdown. The single place an advance comes into being."""
        # Zero-padded so the id sorts in issue order as a string, which is
        # what :meth:`advances` breaks ties on when two draws share an instant.
        advance = SaleAdvance(
            advance_id=f'ADV-{self._next_advance:06d}',
            amount=amount,
            taken_at=ts,
            settles_at=row.tranche.settles_at,
            accrued_to=ts,
            source_order_id=row.tranche.source_order_id,
        )
        self._next_advance += 1
        row.advances.append(advance)
        return advance

    def settle_due(self, now: datetime) -> Tuple[ProceedsTranche, ...]:
        """Move matured proceeds into ``settled_balance``, repaying the advance.

        Same ``<=`` comparison and the same instant as
        :meth:`HoldingsLedger.settle_due`, because it is the same allocation
        event. Where the tranche was advanced, the amount simply moves from
        ``advanced`` into ``settled_balance``: ``available`` is unchanged,
        which is the point -- the advance made the money spendable early, it
        did not create any. Rulebook 8.3: the advance "is recovered
        automatically from the sale proceeds at T+2 settlement".

        **Interest is brought up to the settlement instant here, and stops.**
        The accrual is done in this method rather than left to the caller's
        next :meth:`accrue_interest` because after this call the advance is
        gone from the ledger and the days between the last watermark and
        settlement would be uncollectable. The consequence is the one that
        matters: the total cost of an advance is the same whether the caller
        accrues every day, once, or never.

        Any :attr:`AdvanceTerms.minimum_charge` is applied once per advance at
        this instant, as a floor on that advance's total interest -- rulebook
        12.7 puts the charge "at recovery, from the T+2 settlement proceeds".
        The floor is off by default because the published minima cannot be
        read: 30,000 and 50,000 are quoted, but Vietnamese fee schedules often
        quote thousand-dong, so the figure may be a thousandfold out.
        """
        due = [r for r in self._rows if r.tranche.settles_at <= now]
        if not due:
            return ()
        self._rows = [r for r in self._rows if r.tranche.settles_at > now]
        settled: List[ProceedsTranche] = []
        for row in due:
            self._repay(row, now)
            self._settled += row.tranche.amount
            settled.append(self._view(row))
        return tuple(sorted(settled, key=lambda t: t.settles_at))

    def _repay(self, row: _PendingRow, now: datetime) -> None:
        """Recover every advance on a settling tranche, interest first."""
        minimum = self._advance_terms.minimum_charge
        for index, advance in enumerate(row.advances):
            if not advance.is_outstanding:  # pragma: no cover - defensive
                continue
            final = advance.interest_accrued + self._interest_on(
                advance, row.tranche.settles_at)
            if minimum is not None:
                final = max(final, minimum)
            self._interest_accrued += final - advance.interest_accrued
            row.advances[index] = replace(
                advance,
                accrued_to=row.tranche.settles_at,
                interest_accrued=final,
                repaid_at=now,
            )
            self._repaid.append(row.advances[index])

    def _interest_on(self, advance: SaleAdvance, until: datetime) -> Decimal:
        """Interest on one advance for the whole days from its watermark to
        ``until``, capped at its settlement instant. Never negative."""
        rate = self._advance_terms.daily_rate
        if rate <= 0:
            return Decimal('0')
        horizon = min(until, advance.settles_at)
        days = (horizon - advance.accrued_to).days
        if days <= 0:
            return Decimal('0')
        return advance.amount * rate * Decimal(days)

    def accrue_interest(self, now: datetime) -> Decimal:
        """Accrue interest on outstanding advances up to ``now``.

        The mechanism, modelled rather than hand-waved: interest is
        ``amount_advanced x daily_rate x days_advanced`` (rulebook 8.3 and
        12.7 -- the *formula* is the sourced part, at high confidence; the
        rate is a per-firm commercial number and is not), run from the instant
        the advance was taken to the instant the proceeds settle and the
        broker recovers it. Calling this repeatedly is safe -- each advance
        carries its own ``accrued_to`` watermark, which moves by whole days
        only, so the same day is never charged twice and a part-day is not
        lost, it is carried.

        **Day count and annualisation are two different things and only one
        of them enters here.** This method counts actual calendar days between
        two instants; no year length appears in the arithmetic. The year
        length matters only when a *quoted annual* rate is turned into a daily
        one, and rulebook 8.3 records that the sources disagree there: the
        0.025-0.05%/day industry range is annualised x360 ("9-18% p.a.") while
        DSC's "0.0356%/day = 13%/yr" is x365, a systematic ~1.4% difference.
        **This module declares 365** (rulebook 12.1's recommendation) and
        records the choice in :attr:`AdvanceTerms.annualisation_basis` rather
        than baking it in, so a caller working from a 360-basis quote can say
        so via :meth:`AdvanceTerms.from_annual_rate` and get that quote's own
        arithmetic.

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

        **It is also not in** :meth:`charges`, and that is a gap rather than a
        decision. Rulebook 12.7 lists the advance in the charge table with a
        base of ``amount_advanced x days_advanced``, and
        :class:`~plutus.market.session.types.ChargeBase` has no such member --
        its five bases are trade value, per contract, per trade, per open
        contract per day, and monthly per security. Inventing a
        ``TRADE_VALUE`` row for it would put a financing cost in the same
        column as a transaction fee, and no member here can honestly hold it.
        Until ``ChargeBase`` grows a financing base, the cost of an advance is
        readable only through ``Cash.interest_accrued`` and
        :meth:`advances`, and a caller itemising costs must add it there.

        Returns:
            The interest accrued by this call, zero if none was due.
        """
        accrued_now = Decimal('0')
        for row in self._rows:
            for index, advance in enumerate(row.advances):
                if not advance.is_outstanding:  # pragma: no cover - defensive
                    continue
                interest = self._interest_on(advance, now)
                if interest <= 0:
                    continue
                days = (min(now, advance.settles_at)
                        - advance.accrued_to).days
                row.advances[index] = replace(
                    advance,
                    accrued_to=advance.accrued_to + timedelta(days=days),
                    interest_accrued=advance.interest_accrued + interest,
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
        account, or the cash leg of a corporate action.

        ``ts`` and ``reason`` are the interface contract's signature and are
        carried for the caller's own journal; this ledger itemises charges
        (:meth:`charges`) and nothing else, because design section 3 puts all
        reporting on the caller's side.
        """
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

#: What an estimate stamps its context with when nothing better is on offer.
#: The estimate never keeps its charges -- it returns one total -- so the
#: instant is inert there: the *date* axis of the charge table was already
#: fixed when the caller chose which ``RuleSet`` to pass. A real ``RuleSet``
#: carries ``ts`` and is used; anything standing in for one need not, which
#: keeps this module asking a rulebook for exactly what it documents.
_UNSTAMPED = datetime.min

#: The engine both functions below run on. ``charges.py`` owns the table --
#: which rows are in force at ``(venue, charge class, side, date)``, what each
#: is levied on, the min/max clamp, the whole-dong rounding as a declared
#: modelling choice, the per-row VAT flag -- and this module owns only the
#: *account* half: what the estimate reserves and what the fill debits. The
#: two functions here are the seam design section 6.1 promised, kept at their
#: Tier 1 signatures so no caller has to move.
def estimate_charges(
    rules: 'RuleSet',
    order: Order,
    venue: Venue,
    cls_: ChargeClass,
    price: Decimal,
    *,
    profile: Optional[BrokerProfile] = None,
    commission: Sequence[CommissionSchedule] = (),
    ticker: Optional[str] = None,
    multiplier: Optional[Decimal] = None,
    ts: Optional[datetime] = None,
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
        profile: the broker's flat commission rows. Not in the interface
            contract's signature, which passes only a ``RuleSet``; but
            ``RuleSet.charges`` refuses to return ``BROKER`` rows by design, so
            without this the estimate omits the single largest charge on a
            retail equity trade and under-funds every buy. Added as a trailing
            keyword so the promised positional call still type-checks.
        commission: tiered schedules
            (:class:`plutus.market.session.charges.CommissionSchedule`). The
            tier depends on a day that has not happened yet when an order is
            accepted, so the reservation is taken at the **dearest** band.
        ticker, multiplier: needed only on HNXDS, where the conversion is
            points x contract multiplier rather than the cash venues'
            thousands of dong.

    Charges debited ``DAILY`` are included although :func:`assess_charges`
    does not levy them: a commission that tiers on the day's total traded
    value is not knowable at fill time (rulebook 12.2), and a reservation that
    ignored it would under-fund. Over-reserving is the conservative direction
    and the reservation is released in full at the terminal edge either way.
    """
    return _estimate_charges(
        rules, profile,
        ChargeContext(venue=venue, charge_class=cls_, side=order.side,
                      quantity=order.quantity, price=price,
                      ts=ts or getattr(rules, 'ts', _UNSTAMPED),
                      ticker=ticker or getattr(order, 'ticker', None),
                      multiplier=multiplier),
        commission=commission)


def assess_charges(
    rules: 'RuleSet',
    profile: Optional[BrokerProfile],
    fill: Fill,
    cls_: ChargeClass,
    *,
    commission: Sequence['CommissionSchedule'] = (),
    multiplier: Optional[Decimal] = None,
) -> Tuple[Charge, ...]:
    """The charges actually levied on one fill.

    ``debited_at == FILL`` rows only. ``DAILY`` rows (a tiered broker
    commission, whose rate is only known at the daily close -- see
    :func:`plutus.market.session.charges.assess_daily`) and ``MONTHLY`` rows
    (custody, the VSDC collateral fee) are deliberately not levied here, and
    pricing either per fill would pick a number the rules do not produce.

    ``multiplier`` is what makes this callable on an HNXDS fill: the cash
    conversion refuses that venue by design, so a futures fill must supply the
    contract multiplier and the derivatives transfer tax is then levied on the
    margined value from the same dated margin series ``deposit.py`` reads.

    Rounding each charge to whole dong is a **modelling choice** and must be
    reported as one -- no Vietnamese source states a rounding rule for any fee
    or tax.
    """
    return tuple(lc.charge for lc in _assess_charges(
        rules, profile,
        ChargeContext(venue=fill.venue, charge_class=cls_, side=fill.side,
                      quantity=fill.quantity, price=fill.price, ts=fill.ts,
                      ticker=fill.ticker, multiplier=multiplier,
                      order_id=fill.order_id, fill_id=fill.fill_id),
        commission=commission))


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

    # -- the sale advance -----------------------------------------------

    def advanceable(
        self,
        *,
        tranche: Optional[ProceedsTranche] = None,
        order_id: Optional[OrderId] = None,
        now: Optional[datetime] = None,
    ) -> Decimal:
        """How much *ung truoc tien ban* is still available to draw.

        Delegates to :meth:`CashLedger.advanceable`. It is on the account
        because the account is the object ``exchange.py`` holds, and because
        the advance is the one thing that makes ``Cash.available`` larger than
        the settled balance -- a caller asking "why can I afford this?" should
        not have to reach through to a sub-ledger to find out.
        """
        return self.cash_ledger.advanceable(
            tranche=tranche, order_id=order_id, now=now)

    def request_advance(
        self,
        ts: datetime,
        amount: Optional[Decimal] = None,
        *,
        tranche: Optional[ProceedsTranche] = None,
        order_id: Optional[OrderId] = None,
    ) -> Tuple[SaleAdvance, ...]:
        """Draw against unsettled sale proceeds. See
        :meth:`CashLedger.request_advance` for the terms and the refusals.

        Advanced cash is spendable the instant it is drawn: it enters
        ``Cash.advanced``, hence ``Cash.available``, hence
        :meth:`reserve_for_buy`. That is the entire point of the product --
        rulebook 5.1 is blunt that without it sell-then-rebuy on the same day
        is impossible, and rulebook 12.7 that it "is the only way to recycle
        sale proceeds intraday, and it must be charged for -- otherwise the
        backtest overstates achievable turnover".
        """
        return self.cash_ledger.request_advance(
            ts, amount, tranche=tranche, order_id=order_id)

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

        Validate first, then commit
        ---------------------------
        The method is in two halves, and the comment marking the boundary is
        load-bearing: **no statement below it may refuse**. Three ledgers move
        here and none of them can be un-moved, so every refusal is hoisted
        above the boundary and evaluated while the account is still untouched.

        This is not hypothetical tidiness. It was a reproduced defect twice
        over: a sell whose charges exceeded its proceeds zeroed the
        reservation and removed the shares before ``credit_pending`` refused
        the negative amount (100 shares destroyed, no proceeds, no charges),
        and a buy the account could not fund credited its holdings tranche
        before ``debit`` found the overdraw. The refusals are still refusals
        -- an overdraw here is a bug in the reservation path, exactly as
        :meth:`CashLedger.debit` says -- but they now arrive before the
        account has changed.

        The buy-side guard tests the **whole outlay**, ``value +
        charge_total``, not the trade value alone: the charges are debited
        separately below, and a check that ignored them would pass and then
        fail half-way through the charge loop.

        When the charges exceed the proceeds
        ------------------------------------
        A minimum commission on a small sale nets below zero: 100 shares of a
        1.0-thousand-dong penny stock gross 100,000d against a broker's
        200,000d per-order minimum. **The fill stands and the net is
        negative**, debiting the account at settlement.

        The alternative -- refusing the fill -- was rejected because it
        models a broker's price list as an exchange rule. The trade matched
        at HSX; the exchange knows nothing of the member's commission
        schedule, and no member could un-match a trade because its own
        minimum fee bit. Refusing here would also make ``broker_profile``
        able to reject orders that ``exchange_rules`` admitted, which is
        precisely the confusion the two config objects exist to prevent.

        **The rulebook does not settle this.** Section 8.3 records only that
        "some firms impose a minimum charge per order" and 12.7 repeats it as
        a broker term (both *medium* confidence, broker-sourced); neither
        states how the shortfall is collected, or when. That it is collected
        out of the T+2 settlement rather than debited at the fill is an
        **assumption**, adopted because it is what the module's "withheld at
        source" model already says about every other sale -- one tranche, one
        DVP instant (rulebook 5.1) -- and because inventing a second cash
        movement would be inventing a mechanism no source describes.

        Raises:
            ValueError: on a fill this account cannot honour -- a
                non-positive quantity, a foreign venue, a side with no sign,
                a charge belonging to the other pool, a buy exceeding
                spendable cash, or a sell exceeding settled holdings. All are
                bug detectors for the reservation path, and all fire before
                any ledger has moved.
        """
        # -- validate: everything that can refuse, before anything moves --
        if fill.quantity <= 0:
            raise ValueError(f'a fill must move positive quantity, got '
                             f'{fill.quantity}')
        if not self.ref.serves(fill.venue):
            raise ValueError(
                f'fill on {fill.venue.value} does not belong to the '
                f'{self.ref.pool.value} pool')
        if fill.side not in (Side.BUY, Side.SELL):
            raise ValueError(
                f'{fill.side} cannot move a securities ledger; Side.CROSS is '
                f'an exchange-internal marker with no sign')

        value = trade_value(fill.venue, fill.quantity, fill.price)
        levied = tuple(charges)
        charge_total = sum((c.total for c in levied), Decimal('0'))

        for charge in levied:
            if charge.pool is not Pool.SECURITIES:
                raise ValueError(
                    f'charge {charge.kind!r} is levied on the '
                    f'{charge.pool.value} pool and cannot be settled against '
                    f'securities cash: the pools are segregated and no '
                    f'auto-transfer exists')

        if fill.side is Side.BUY:
            outlay = value + charge_total
            spendable = (self.cash_ledger.cash().settled_balance
                         + self.cash_ledger.advanced())
            if outlay > spendable:
                raise ValueError(
                    f'buying {fill.quantity} {fill.ticker} costs {outlay} '
                    f'including {charge_total} of charges, which exceeds '
                    f'settled plus advanced cash of {spendable}; the '
                    f'encumbrance taken at accept should have made this '
                    f'unreachable')
        else:
            held = self.holdings_ledger.holding(fill.ticker).settled
            if fill.quantity > held:
                raise ValueError(
                    f'cannot debit {fill.quantity} of {fill.ticker} against '
                    f'{held} settled: unsettled quantity is never '
                    f'deliverable, and an overdraw is a short equity position')

        # -- commit: nothing below this line may refuse -------------------
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
        else:
            self.encumbrances.consume(
                fill.order_id, fill.ts, resource=ResourceKind.SHARES,
                quantity=fill.quantity)
            self.holdings_ledger.debit_settled(
                fill.ticker, fill.quantity, fill.ts)
            self.cash_ledger.credit_pending(
                value - charge_total, settles_at, fill.ts, fill.order_id)
            for charge in levied:
                self.cash_ledger.levy(charge, debit=False)

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
