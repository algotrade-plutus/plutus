"""Fill determination -- the pluggable policy, and the module's whole point.

A resting order's fate is often genuinely unknowable from historical data. We
have three price levels and no sizes (``quote_asksize``/``quote_bidsize`` are
0-row in both corpus roots), never an order id, and **81% of best-quote changes
carry no trade at all** -- so order flow, and therefore queue position, cannot
be recovered. Rather than guess and call the guess a backtest, the assumption
is named, swappable, and reported alongside every result it produced.

That is why design section 8 calls this the product's selling point rather than
a workaround for missing depth: run one strategy under ``soft`` and under
``hard`` and report the spread, plus the share of the run that rested on
``INDETERMINATE``. *"Sharpe 1.8 under soft fills, 0.4 under hard fills, 31% of
evaluations undecidable"* is a pre-live warning no existing tool produces.

**NO MARKET IMPACT, EVER.**
------------------------------------------------------------------------
Every policy in this module, and every policy that may ever be written against
:class:`FillPolicy`, fills against *observed history*. The simulated order
never moves a price, never consumes displayed depth, never induces a
counterparty reaction, and never changes an auction's clearing price. This is
the standing limitation of any replay simulator (design section 3, assumption 1
of section 16) and it must be restated in every published result. The
participation cap is the only concession to it, and it is a **bound on our own
claimed share of observed liquidity**, not a model of impact: it stops a
1,000,000-share order claiming a 1,000-share day, but it does not say what that
order would have done to the price.

The three fixed conventions
------------------------------------------------------------------------
Section 8's value is a *spread across policies*, so a convention that drifts
between them contaminates the comparison. These three are fixed here, once, and
both shipped policies obey them:

1. **Fill price.** In a call auction, the published open (ATO phase) or close
   (ATC phase). In continuous session, a limit order fills at **its own limit
   price**. That is not merely "the only non-arbitrary choice available" --
   Vietnamese matching is explicit that a trade happens at the **resting
   (passive) order's price, not the aggressor's** (rulebook 2.4, QD 352 Dieu
   6.3, confidence high). A resting order of ours therefore fills at its own
   price by rule. Where our order would have been the *aggressor* the true
   price is the resting side's and is better than our limit, so filling at the
   limit is the conservative direction.
2. **Fill quantity.** A participation-capped quantity is floored to the
   instrument's trading unit. An unfloored cap leaves the ledger holding an odd
   lot that ``ROUND_LOT`` (``exchanges/equity.py``) will later refuse to sell.
3. **max_participation** is a fraction of the volume observed in the evaluated
   interval and it **aggregates across all of the caller's own live orders in
   that instrument** -- passed in as ``already_filled``. Per-order would let a
   caller split one order into ten and evade the cap.

Auctions and continuous session are different mechanics
------------------------------------------------------------------------
They are dispatched separately (:meth:`BaseFillPolicy._auction` against
:meth:`BaseFillPolicy._continuous`) because the questions are not the same one.
A continuous fill asks "did anyone trade through my price, and would I have
been at the front of that queue"; an auction fill asks "did the cross clear
through my price", which the clearing algorithm answers *by rule*: HOSE's step
(a) chooses the price at which "every buy above and every sell below the chosen
price fills in full" (rulebook 2.4, QD 352 Dieu 6.2(a), verbatim, confidence
high). A strictly-through order in an auction is a rule-guaranteed full fill,
not an inference about queue position -- which is why ``hard`` will fill one and
will not fill a continuous touch.

The one thing the auction cannot answer is allocation **at** the marginal
price, which rulebook 2.4 records as **UNVERIFIED for the ATO/ATC cross**: no
Vietnamese document states it. That absence is the direct source of this
module's auction ``INDETERMINATE``.

What is recorded on every decision
------------------------------------------------------------------------
:meth:`BaseFillPolicy.evaluate` is a template method: every decision leaves it
stamped with the policy signature (see :func:`stamp_policy` /
:func:`policy_of`), so a fill can never be reported without the assumption that
generated it. A subclass implements ``_continuous`` and ``_auction`` and cannot
forget the stamp.

``FillDecision`` has no ``policy`` field today, so the stamp rides in ``reason``
as a ``'<signature>: <why>'`` prefix. **Requested of the orchestrator:** a
``policy: Optional[str]`` field on both ``FillDecision`` and ``Fill`` in
``types.py``, at which point :func:`stamp_policy` sets a field instead of
parsing a string and :func:`policy_of` becomes an attribute read. The
convention is deliberately mechanical so that migration is a two-line change.

Confidence is never invented here
------------------------------------------------------------------------
Both shipped policies return ``confidence = 1`` on every definite decision.
``FillDecision.confidence`` exists for a policy with a real distribution behind
it; fabricating "0.5 because it might have filled" would put an unsourced
number into a result, which is the failure mode this whole package exists to
avoid. What distinguishes a soft fill from a hard one is
``FillEvidence.TOUCHED_AT_LIMIT`` against ``FillEvidence.TRADED_THROUGH`` -- a
fact about the data, countable after the fact.
"""

from abc import ABC, abstractmethod
from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal
from typing import ClassVar, FrozenSet, Optional, Protocol, Tuple, runtime_checkable

from plutus.market.exchanges.base import Exchange
from plutus.market.protocol import (InstrumentSpec, OrderType, Resolution,
                                    SessionPhase, Side)
from plutus.market.session.types import (TIME_IN_FORCE, DataField, FillDecision,
                                         FillEvidence, FillPolicyConfig,
                                         MarketInterval, OrderRecord,
                                         TimeInForce)

__all__ = [
    'NO_MARKET_IMPACT', 'MATCHING_PHASES', 'POLICY_SEPARATOR',
    'FillPolicy', 'BaseFillPolicy', 'SoftFillPolicy', 'HardFillPolicy',
    'auction_fill_price', 'build_fill_policy', 'floor_to_lot',
    'participation_cap', 'policy_of', 'stamp_policy',
]


#: Stated once, importable, and meant to be printed next to any result derived
#: from this module. Design section 16 assumption 1; section 3 non-goal 3.
NO_MARKET_IMPACT = (
    'No market impact: orders fill against observed history. The simulated '
    'order never moves a price, never consumes displayed depth, never induces '
    'a counterparty reaction and never changes an auction clearing price.'
)

#: The three phases in which any matching happens at all.
#:
#: The absence of ``NOON_BREAK`` is the same absence ``ExpiryTrigger`` makes in
#: ``types.py``, seen from the other side: 11:30-13:00 is a hard shutdown for
#: entry, amendment and cancellation (rulebook 2.1) but resting orders survive
#: it and simply do not match. So the break is a definite ``NO_FILL``, never an
#: expiry and never an ``INDETERMINATE`` -- there is nothing undecidable about
#: a shut market.
#:
#: ``POST_CLOSE_PLO`` is excluded on purpose. HNX's after-hours session matches
#: only PLO orders at the day's last round-lot matched price (rulebook 2.3), and
#: ``plutus.core.order.OrderType`` carries no PLO member, so no order this
#: package can represent participates in it.
MATCHING_PHASES: FrozenSet[SessionPhase] = frozenset({
    SessionPhase.CONTINUOUS,
    SessionPhase.OPENING_AUCTION,
    SessionPhase.CLOSING_AUCTION,
})

#: Separator between the policy signature and the reason body in a stamped
#: ``FillDecision.reason``. See the module docstring.
POLICY_SEPARATOR = ': '


# --------------------------------------------------------------------------
# The extension point
# --------------------------------------------------------------------------

@runtime_checkable
class FillPolicy(Protocol):
    """Swappable fill determination. The seam this module exists to create.

    Structural, not nominal, so a caller may ship a policy of their own without
    inheriting anything of ours -- that is what "arbitrary fill model" has to
    mean if it is to be a checkable claim. :class:`BaseFillPolicy` is the
    convenience base that also guarantees the policy stamp; implementing this
    Protocol directly is legal and the type system will accept it.

    **The signature must not have to change to admit a new family of policy.**
    That is the load-bearing claim of the seam, so it is worth showing how each
    of the three families design section 8 names is expressed through it:

    ==================  =================================================
    Policy family       What it uses, all of it already here
    ==================  =================================================
    deterministic-soft  ``interval.close`` / ``high`` / ``low`` against
                        ``order.order.limit_price``. No volume needed.
    deterministic-hard  the same, plus ``interval.volume`` for the
                        participation cap, plus ``already_filled`` to
                        aggregate the cap across the caller's own orders.
    probabilistic       a seed and any internal state in ``__init__``;
                        ``interval.book`` for a queue estimate;
                        ``FillDecision.confidence`` to carry the fill
                        probability; ``quantity`` below ``remaining`` for
                        a partial; ``FillEvidence.MODELLED`` as evidence;
                        ``DataField.BOOK_SIZE`` on the ``INDETERMINATE``
                        it must return on every corpus here, because
                        ``BookLevel.size`` is ``None`` in all of them.
    ==================  =================================================

    A queue-position policy matching against a full reconstructed book is
    deferred, not unrepresentable: it needs no new argument, only data that
    does not exist (design section 13).

    Attributes:
        kind: the config token that selects this policy
            (``FillPolicyConfig.kind``), and the value recorded in
            ``SessionProvenance.fill_policy_kind``.
    """

    kind: str

    def evaluate(
        self,
        order: OrderRecord,
        interval: MarketInterval,
        rules: Exchange,
        *,
        already_filled: int = 0,
        instrument: Optional[InstrumentSpec] = None,
    ) -> FillDecision:
        """Decide this order's fate over this interval.

        Args:
            order: the caller's own order row. The policy reads
                ``remaining_quantity``, never ``original_quantity`` -- a
                partially filled order is evaluated for what is left of it.
            interval: what the market did over ``[start, end)`` for this
                instrument; ``end`` is exclusive. **The session owns the
                clipping.** A policy evaluates the whole interval it is handed
                and does not re-clip it against ``order.submitted_at``, because
                only the session knows what its data resolution can express --
                on daily bars an order entered at 14:00 can only be evaluated
                against the whole day's bar, and that over-generosity is a
                declared consequence of the resolution rather than something a
                fill policy may silently correct.
            rules: the existing ``exchanges.base.Exchange`` that judges this
                venue. A policy may consult it and the venue spec; it must
                **never** see account state. Fill determination that could read
                the ledger would be able to fill exactly what the caller can
                afford, which is not a market model.
            already_filled: the caller's own aggregated fill quantity in this
                *instrument* over this interval, for the participation cap.
                Aggregated rather than per-order so that splitting one order
                into ten does not evade the cap.
            instrument: the ``InstrumentSpec`` **as of this instant**, from
                ``SymbolRouter.instrument(ticker, ts)``. Supplies the dated
                trading unit for convention 2. Optional, and its absence is
                handled conservatively -- see :meth:`BaseFillPolicy._lot`.

        Returns:
            A :class:`FillDecision`: ``FILL``, ``NO_FILL``, or
            ``INDETERMINATE``. The third is not a hedge, it is the measurement:
            ``INDETERMINATE`` means *the data cannot establish whether this
            fills*, which is a different statement from *it does not fill*, and
            the session counts it into ``IndeterminateReport``. An order that
            gets one stays ``RESTING`` and is re-evaluated on the next interval
            (design section 12 -- ``INDETERMINATE`` is an event, never a state).
        """
        ...


class BaseFillPolicy(ABC):
    """Shared scaffolding: the phase gate, the stamp, and the lot lookup.

    Subclasses implement :meth:`_continuous` and :meth:`_auction` only. Three
    things are deliberately *not* left to them, because a policy that got any
    of them privately wrong would corrupt the spread the whole comparison
    reports:

    1. **The phase gate.** Which phases match at all, and what an order type is
       allowed to do in each, is exchange semantics rather than a fill
       assumption. Both policies therefore return the same answer in the noon
       break, pre-open and post-close, and any difference between ``soft`` and
       ``hard`` is attributable to their evidence standard alone.
    2. **The policy stamp.** :meth:`evaluate` is a template method; a subclass
       cannot return an unstamped decision.
    3. **Input validation.** A ticker mismatch or a ``Side.CROSS`` raises
       rather than producing a decision, because both are integration bugs and
       an ``INDETERMINATE`` returned for a bug would be counted as market
       ignorance in the published rate.
    """

    #: Config token; also ``SessionProvenance.fill_policy_kind``.
    kind: ClassVar[str] = ''

    # -- the template method --------------------------------------------

    def evaluate(
        self,
        order: OrderRecord,
        interval: MarketInterval,
        rules: Exchange,
        *,
        already_filled: int = 0,
        instrument: Optional[InstrumentSpec] = None,
    ) -> FillDecision:
        """Decide, then stamp. See :meth:`FillPolicy.evaluate`."""
        decision = self._dispatch(
            order, interval, rules,
            already_filled=already_filled, instrument=instrument,
        )
        return stamp_policy(decision, self.signature)

    @property
    def signature(self) -> str:
        """The policy *and its parameters*, as recorded on every decision.

        The kind alone is not enough to reproduce a result: ``hard`` at a 10%
        participation cap and ``hard`` at 100% are different assumptions and
        produce different fills. Overridden by any policy that has parameters.
        """
        return self.kind

    @property
    def assumptions(self) -> Tuple[str, ...]:
        """Everything a published result using this policy must restate.

        Design section 16 requires the fill assumption to travel with the
        result; this is that text, in the policy that owns it, so a report can
        print it rather than a human remembering to.
        """
        return (NO_MARKET_IMPACT,)

    def __repr__(self) -> str:
        return f'{type(self).__name__}({self.signature!r})'

    # -- the parts a subclass provides ----------------------------------

    @abstractmethod
    def _continuous(
        self,
        order: OrderRecord,
        interval: MarketInterval,
        rules: Exchange,
        *,
        already_filled: int,
        instrument: Optional[InstrumentSpec],
    ) -> FillDecision:
        """Decide a continuous-session order. Order-matching, price-time."""

    @abstractmethod
    def _auction(
        self,
        order: OrderRecord,
        interval: MarketInterval,
        rules: Exchange,
        *,
        already_filled: int,
        instrument: Optional[InstrumentSpec],
    ) -> FillDecision:
        """Decide a call-auction order. One clearing price for everyone."""

    # -- the shared gate ------------------------------------------------

    def _dispatch(
        self,
        order: OrderRecord,
        interval: MarketInterval,
        rules: Exchange,
        *,
        already_filled: int,
        instrument: Optional[InstrumentSpec],
    ) -> FillDecision:
        """Validate, then route to the right mechanic for this phase."""
        _validate(order, interval, already_filled)

        if order.remaining_quantity <= 0:
            return FillDecision.no_fill(
                'nothing remains unfilled on this order')

        phase = interval.session
        if phase is SessionPhase.UNKNOWN or interval.lacks(
                DataField.SESSION_PHASE):
            # Design section 9: a missing field produces INDETERMINATE with the
            # field named. Never inferred from the timestamp -- a daily bar is
            # stamped midnight and would infer as pre-open, rejecting an entire
            # daily measurement (protocol.py, SessionPhase).
            return FillDecision.indeterminate(
                'the session phase is unknown, so which matching mechanic '
                'applies cannot be established',
                [DataField.SESSION_PHASE],
            )

        tif = TIME_IN_FORCE[order.order.order_type]
        if tif is TimeInForce.AUCTION_ONLY:
            want = _auction_phase(order, interval)
            if phase is not want:
                # ATO/ATC are "enterable only inside their own auction window,
                # unfilled remainder auto-cancelled at the cross; never rest,
                # never carry" (rulebook 2.3, QD 352 Dieu 14.3(b)/14.4(b)).
                # Reaching another phase means orders.py has not expired it at
                # the cross; the fill answer is still a definite no.
                return FillDecision.no_fill(
                    f'{order.order.order_type.value} may only match in '
                    f'{want.value if want else "its own auction"}, and this '
                    f'interval is {phase.value}'
                )
            return self._auction(order, interval, rules,
                                 already_filled=already_filled,
                                 instrument=instrument)

        if phase not in MATCHING_PHASES:
            return FillDecision.no_fill(
                f'no matching takes place in {phase.value}')

        if phase is SessionPhase.CONTINUOUS:
            return self._continuous(order, interval, rules,
                                    already_filled=already_filled,
                                    instrument=instrument)

        # An unfilled continuous-session LO is carried into the following
        # auction and participates in the cross (rulebook 2.3, QD 352 Dieu
        # 14.1(c)/17.2). A limit order IS legal in a call auction; it is the
        # market family that an auction cannot accept.
        return self._auction(order, interval, rules,
                             already_filled=already_filled,
                             instrument=instrument)

    # -- shared helpers a subclass may use ------------------------------

    def _lot(
        self,
        rules: Exchange,
        instrument: Optional[InstrumentSpec],
    ) -> int:
        """The round lot to floor a capped quantity to (convention 2).

        Prefers the ``InstrumentSpec`` the session resolved **as of this
        instant**, which is the only date-correct source: ``SymbolRouter``
        overwrites ``trading_unit`` from the dated ``RuleSet`` precisely so
        that passing the spec is safe.

        Falls back to ``Exchange.spec.trading_unit``, which is the *present-day*
        table and is wrong for HOSE before 2021-01-04, when the lot was 10
        rather than 100. The error is one-directional: flooring to 100 when the
        true lot is 10 fills **less** than reality permits, never more, so the
        conservative policy stays conservative under the fallback. It is still
        a fallback, and the session should always pass ``instrument``.
        """
        if instrument is not None and instrument.trading_unit:
            return int(instrument.trading_unit)
        return int(rules.spec.trading_unit)


# --------------------------------------------------------------------------
# Conventions, as free functions -- the contract's promised surface
# --------------------------------------------------------------------------

def floor_to_lot(quantity: int, trading_unit: int) -> int:
    """Floor a quantity to a whole round lot. Convention 2.

    A capped quantity that is not floored leaves the ledger holding an odd lot,
    and an odd lot is not sellable through the ordinary board: ``ROUND_LOT`` in
    ``exchanges/equity.py`` will refuse the sale later, stranding the position
    for a reason the caller cannot see from the fill that created it. Flooring
    at the point of the fill is the only place the problem is cheap.

    ``trading_unit`` of 1 (HNXDS, and odd-lot boards) makes this the identity.

    Raises:
        ValueError: on a negative quantity or a trading unit below 1. Neither
            is a market condition; both are integration bugs, and silently
            returning 0 would hide one.
    """
    if quantity < 0:
        raise ValueError(f'quantity must not be negative, got {quantity}')
    if trading_unit < 1:
        raise ValueError(
            f'trading_unit must be at least 1, got {trading_unit}')
    return (quantity // trading_unit) * trading_unit


def participation_cap(
    interval: MarketInterval,
    max_participation: Decimal,
    already_filled: int,
) -> Optional[int]:
    """Quantity this instrument may still take in this interval, or ``None``.

    Convention 3: the cap is a fraction of the volume **observed in the
    evaluated interval**, aggregated across every one of the caller's own live
    orders in the instrument -- hence ``already_filled`` rather than a
    per-order budget. Per-order, a caller splits one order into ten and evades
    it.

    ``None`` means *the cap cannot be computed*, which is a different answer
    from zero and must not be collapsed into it: zero says "you have used your
    share", ``None`` says "the data does not say what the share is". The caller
    turns ``None`` into an ``INDETERMINATE`` naming ``DataField.VOLUME``. This
    is not hypothetical -- both shipped adapters leave ``volume`` unsupplied on
    every corpus here, so a volume-capped policy is honestly undecidable on
    today's data, and reporting that is the point.

    Rounds **down**: a fractional allowance is not a share of a lot.
    """
    if interval.volume is None or interval.lacks(DataField.VOLUME):
        return None
    allowance = (Decimal(interval.volume) * max_participation
                 ).to_integral_value(rounding=ROUND_FLOOR)
    return max(int(allowance) - already_filled, 0)


def auction_fill_price(
    order: OrderRecord,
    interval: MarketInterval,
) -> Optional[Decimal]:
    """The published open (ATO phase) or close (ATC phase). Convention 1.

    A call auction crosses at **one price for everyone**, so there is no
    price-time question to answer and no per-order price: whoever fills, fills
    here. Design section 8 fixes it to the published value, and Tier 3 item 14
    is the separate exercise of computing our own clearing price and grading it
    against this -- evidence, not a feature.

    Which auction is decided by the order type first (ATO opens, ATC closes)
    and by the interval's phase otherwise, so that a limit order carried into
    the cross prices off the auction it actually reached.

    Returns ``None`` in three distinguishable-by-the-caller situations, all of
    which mean "no auction price applies here": this is not an auction interval
    and the order is not auction-only; the order is auction-only and this is
    not its auction; or the auction is right but the published price is absent
    from the data. The caller separates the third by testing ``interval.open`` /
    ``interval.close`` itself, and names ``DataField.OPEN`` / ``CLOSE``.
    """
    phase = _auction_phase(order, interval)
    if phase is None or phase is not interval.session:
        return None
    if phase is SessionPhase.OPENING_AUCTION:
        return interval.open
    return interval.close


# --------------------------------------------------------------------------
# The policy stamp
# --------------------------------------------------------------------------

def stamp_policy(decision: FillDecision, signature: str) -> FillDecision:
    """Record the policy that produced a decision, on the decision.

    Design section 16 assumption 5: "fill determination is policy-dependent,
    and the policy must be reported alongside any result derived from it". A
    stamp applied by the base class rather than by each policy is the
    difference between that being true and it being a convention someone
    remembers.

    Implemented as a ``'<signature>: <why>'`` prefix on ``reason`` because
    ``FillDecision`` has no ``policy`` field yet; see the module docstring for
    the requested change. Idempotent, so a decision that has already been
    stamped by this signature passes through unchanged.

    Raises:
        ValueError: on an empty signature, or one containing the separator --
            either would make :func:`policy_of` unable to read the stamp back,
            and an unreadable stamp is worse than none because it looks present.
    """
    if not signature:
        raise ValueError('a fill policy must have a non-empty signature')
    if POLICY_SEPARATOR in signature:
        raise ValueError(
            f'a policy signature may not contain {POLICY_SEPARATOR!r}, '
            f'got {signature!r}'
        )
    body = decision.reason
    if body is None:
        body = (decision.evidence.value if decision.evidence is not None
                else decision.outcome.value)
    prefix = signature + POLICY_SEPARATOR
    if body.startswith(prefix):
        body = body[len(prefix):]
    # ``replace`` rather than a direct construction: ``FillDecision``'s own
    # docstring reserves positional construction for its three case
    # constructors, and stamping is a copy, not a fourth case.
    return replace(decision, reason=prefix + body)


def policy_of(decision: FillDecision) -> Optional[str]:
    """The signature of the policy that produced ``decision``, if stamped.

    ``None`` for an unstamped decision -- one built by hand in a test, or by a
    third-party policy that implements :class:`FillPolicy` structurally without
    going through :class:`BaseFillPolicy`. ``None`` is the honest answer there;
    inventing a default would attribute someone else's assumption to us.
    """
    reason = decision.reason
    if not reason or POLICY_SEPARATOR not in reason:
        return None
    return reason.split(POLICY_SEPARATOR, 1)[0]


# --------------------------------------------------------------------------
# SoftFillPolicy -- the baseline arm
# --------------------------------------------------------------------------

class SoftFillPolicy(BaseFillPolicy):
    """Fill if the price traded at or through the limit, full size.

    **This is what every backtester does today**, and that is exactly why it
    ships: it is the comparison arm without which "hard fills cost you 1.4
    Sharpe" is a number with nothing to be relative to. It is not the
    recommended policy and its docstring should not be read as endorsing it.

    What it assumes, all of it unstated in the tools that do this by default:

    - that the caller's order was at the front of the queue at its price, on
      every interval, in every instrument -- i.e. that ``TOUCHED_AT_LIMIT`` is
      as good as ``TRADED_THROUGH``;
    - that the caller's size was available, whatever it was, with no reference
      to the volume that actually traded;
    - that a market-family order executes at the observed price with no depth.

    Each is recorded on the decision it produced: a soft fill carries
    ``FillEvidence.TOUCHED_AT_LIMIT`` when that is what it rested on, so the
    share of a soft backtest resting on the queue assumption is countable after
    the fact rather than invisible.

    ``INDETERMINATE`` is still reachable, and it matters that it is: when the
    interval carries no traded price at all, even this policy has nothing to
    assert. A policy that could never say "I do not know" would make the
    ``INDETERMINATE`` rate a property of the data alone.
    """

    kind: ClassVar[str] = 'soft'

    @property
    def assumptions(self) -> Tuple[str, ...]:
        return super().assumptions + (
            'Soft fills: an order fills in full whenever the market traded at '
            'or through its limit, with no queue-position and no volume test. '
            'This is the optimistic bound, not a forecast.',
        )

    def _continuous(self, order, interval, rules, *, already_filled,
                    instrument) -> FillDecision:
        side = order.order.side
        limit = order.order.limit_price

        if limit is None:
            # Market family (MTL/MOK/MAK, and core/order.py's synthetic MKT).
            # The backtester answer: it executes, at whatever printed.
            price = _point_price(interval)
            if price is None:
                return FillDecision.indeterminate(
                    'a market-family order needs an observed traded price and '
                    'this interval carries none',
                    [DataField.CLOSE, DataField.LAST],
                )
            return FillDecision.fill(order.remaining_quantity, price,
                                     FillEvidence.TRADED_THROUGH)

        observed, field = _extreme_toward(side, interval)
        if observed is None:
            observed = _point_price(interval)
            if observed is None:
                return FillDecision.indeterminate(
                    'this interval carries no traded price, so not even an '
                    'at-or-through test can be made',
                    [field, DataField.CLOSE, DataField.LAST],
                )

        reach = _reach(side, observed, limit)
        if reach < 0:
            return FillDecision.no_fill(
                f'the market never reached {limit} on the '
                f'{"buy" if side is Side.BUY else "sell"} side '
                f'(best observed {observed})'
            )
        evidence = (FillEvidence.TRADED_THROUGH if reach > 0
                    else FillEvidence.TOUCHED_AT_LIMIT)
        return FillDecision.fill(order.remaining_quantity, limit, evidence)

    def _auction(self, order, interval, rules, *, already_filled,
                 instrument) -> FillDecision:
        clearing, field = _clearing_price(order, interval)
        if clearing is None:
            return FillDecision.indeterminate(
                'no published cross price for this auction, so whether it '
                'crossed at all cannot be established',
                [field] if field is not None else (),
            )

        limit = order.order.limit_price
        if limit is None:
            # ATO/ATC, or an unmodelled MTL residue. The backtester answer for
            # all of them is the cross price.
            return FillDecision.fill(order.remaining_quantity, clearing,
                                     FillEvidence.AUCTION_PRICE)

        if _reach(order.order.side, clearing, limit) < 0:
            return FillDecision.no_fill(
                f'the auction cleared at {clearing}, past a limit of {limit}')
        return FillDecision.fill(order.remaining_quantity, clearing,
                                 FillEvidence.AUCTION_PRICE)


# --------------------------------------------------------------------------
# HardFillPolicy -- what is defensible going live
# --------------------------------------------------------------------------

class HardFillPolicy(BaseFillPolicy):
    """Fill only where the data can support the claim that it would have.

    The standard is evidential, and it has exactly one form in each mechanic:

    **Continuous session.** Fill only where the market demonstrably traded
    *through* the limit -- a trade strictly better than our price. That is
    proof: order priority is price first, time second, with no size priority
    and no pro-rata anywhere in Vietnamese rules (rulebook 2.4, QD 352 Dieu 7,
    16, confidence high), so a trade at a price worse than our resting limit
    could not have happened while our order sat unfilled. **Touched at limit
    is INDETERMINATE, not a fill and not a no-fill**: whether we were in front
    of that trade is decided by time priority, and time priority is exactly
    what this corpus cannot recover -- there are no order ids, and 81% of
    best-quote changes carry no trade, so order flow cannot be reconstructed.

    **Call auction.** Fill only where the cross cleared strictly through the
    limit. That is a rule-guaranteed full execution rather than an inference:
    HOSE's clearing algorithm picks the price at which "every buy above and
    every sell below the chosen price fills in full" (rulebook 2.4, QD 352 Dieu
    6.2(a), verbatim, confidence high). At the clearing price exactly, the
    order is rationed, and rulebook 2.4 records allocation at the marginal
    price as **UNVERIFIED for the ATO/ATC cross** -- no Vietnamese document
    states the rule -- so that too is ``INDETERMINATE``.

    **Size.** Capped at ``max_participation`` of the volume observed in the
    interval. Where ``interval.volume`` is absent the cap cannot be computed
    and the decision degrades to ``INDETERMINATE`` naming ``DataField.VOLUME``.
    On both shipped adapters volume is unsupplied, so on today's corpus this
    policy is undecidable wherever it would otherwise fill -- which is the
    honest reading of the data, and the number the paper should print.

    The order of those two tests is deliberate and is a modelling choice worth
    naming: **price is tested before size**. An order the market never reached
    is a definite ``NO_FILL`` whatever the volume was, so the missing-volume
    ``INDETERMINATE`` is raised only for orders that would otherwise have
    filled. Testing size first would inflate the reported ignorance rate with
    orders about which the data is perfectly clear.

    What it does *not* claim: that a filled order was actually filled in
    reality. Traded-through establishes that a fill was **possible and
    unavoidable given priority**, on the observed tape, under no market impact.
    It does not model our own order's absence from that tape.
    """

    kind: ClassVar[str] = 'hard'

    def __init__(self, max_participation: Decimal = Decimal('0.10')) -> None:
        """
        Args:
            max_participation: the fraction of observed interval volume this
                caller may claim across all of its live orders in one
                instrument. The 10% default is a **modelling convention, not a
                sourced rule** -- no Vietnamese document caps a participant's
                share of a print -- and it is carried in :attr:`signature` so
                that no result can be reported without it.

        Raises:
            TypeError: if given a ``float``. House rule: every rate is a
                ``Decimal``, because a binary fraction of a share count is a
                rounding bug waiting for a large volume.
            ValueError: outside ``(0, 1]``. Zero would make the policy fill
                nothing while still reporting itself as a fill policy, and
                above 1 claims more than the whole market traded.
        """
        if isinstance(max_participation, float):
            raise TypeError(
                'max_participation must be a Decimal, not a float; rates in '
                'this package are Decimal fractions'
            )
        max_participation = Decimal(max_participation)
        if not Decimal('0') < max_participation <= Decimal('1'):
            raise ValueError(
                f'max_participation must lie in (0, 1], got {max_participation}'
            )
        self.max_participation = max_participation

    @property
    def signature(self) -> str:
        """``hard(max_participation=0.10)`` -- the kind *and* the parameter.

        Two runs at different caps are two different assumptions and will
        produce different fills, so the kind alone would not let a reader
        reproduce either one.
        """
        return f'{self.kind}(max_participation={self.max_participation})'

    @property
    def assumptions(self) -> Tuple[str, ...]:
        return super().assumptions + (
            'Hard fills: an order fills only where the market traded strictly '
            'through its limit (continuous) or the cross cleared strictly '
            'through it (auction). At the limit is INDETERMINATE, because '
            'time priority is unrecoverable from this data.',
            f'Participation cap: at most {self.max_participation} of the '
            f'volume observed in the evaluated interval, aggregated across all '
            f'of the caller\'s live orders in the instrument. A modelling '
            f'convention, not a sourced rule.',
        )

    # -- continuous -----------------------------------------------------

    def _continuous(self, order, interval, rules, *, already_filled,
                    instrument) -> FillDecision:
        side = order.order.side
        limit = order.order.limit_price

        if limit is None:
            return self._market_family_undecidable(interval)

        observed, field = _extreme_toward(side, interval)
        if observed is not None:
            reach = _reach(side, observed, limit)
            if reach < 0:
                # The extreme of the interval on our side never reached the
                # limit, so nothing traded at or through it. Definite.
                return FillDecision.no_fill(
                    f'the interval\'s {field.value} of {observed} never '
                    f'reached a limit of {limit}'
                )
            if reach == 0:
                return _touched(observed)
            return self._sized_fill(order, interval, rules, limit,
                                    FillEvidence.TRADED_THROUGH,
                                    already_filled=already_filled,
                                    instrument=instrument)

        # No extreme. A single point price can still *prove* a fill -- a trade
        # strictly through the limit is proof however it was observed -- but it
        # can never disprove one, because an unobserved trade through the limit
        # cannot be ruled out without the extreme. Asymmetric on purpose.
        point = _point_price(interval)
        if point is None:
            return FillDecision.indeterminate(
                'this interval carries neither a traded extreme nor a traded '
                'price, so nothing can be established about the limit',
                [field, DataField.CLOSE, DataField.LAST],
            )
        reach = _reach(side, point, limit)
        if reach > 0:
            return self._sized_fill(order, interval, rules, limit,
                                    FillEvidence.TRADED_THROUGH,
                                    already_filled=already_filled,
                                    instrument=instrument)
        if reach == 0:
            return _touched(point)
        return FillDecision.indeterminate(
            f'the only observed price is {point}, which did not reach a limit '
            f'of {limit}; without the interval\'s {field.value} a trade '
            f'through the limit cannot be ruled out',
            [field],
        )

    def _market_family_undecidable(self, interval) -> FillDecision:
        """Why ``hard`` never fills MTL/MOK/MAK, and why that is not a gap.

        A market-family order walks the book from the best opposite price and
        its residue converts to a limit one tick beyond the last match
        (rulebook 2.3, QD 352 Dieu 14.2, VNX QD 22/2025 Dieu 17.2(b)). How far
        it walks is a function of **depth**, and ``BookLevel.size`` is ``None``
        on every corpus available here. Assuming it fills at the touch is
        assuming unbounded size at the best price, which is a market-impact
        assumption wearing a different hat -- and section 3 forbids those
        outright. So the honest answer is that the data cannot decide.
        """
        missing = (DataField.BOOK_SIZE if interval.book is not None
                   else DataField.BOOK)
        return FillDecision.indeterminate(
            'a market-family order walks the book, and the depth it would '
            'walk is not observable here; assuming it fills at the touch '
            'would be a market-impact assumption',
            [missing],
        )

    # -- auction --------------------------------------------------------

    def _auction(self, order, interval, rules, *, already_filled,
                 instrument) -> FillDecision:
        clearing, field = _clearing_price(order, interval)
        if clearing is None:
            # An absent published open/close may mean no cross happened or may
            # mean the data does not carry it. Nothing silently defaults
            # (design section 9), so the two are not collapsed into a no-fill.
            return FillDecision.indeterminate(
                'no published cross price for this auction, so whether it '
                'crossed at all cannot be established',
                [field] if field is not None else (),
            )

        limit = order.order.limit_price
        if limit is None:
            tif = TIME_IN_FORCE[order.order.order_type]
            if tif is not TimeInForce.AUCTION_ONLY:
                # An MTL residue rests as a limit one tick beyond the last
                # match (rulebook 2.3); we do not model that conversion, so we
                # do not know the price it would carry into the cross.
                return FillDecision.indeterminate(
                    'a market-family order carries into an auction as its '
                    'residual limit one tick beyond the last match, and that '
                    'conversion is not modelled here',
                    [DataField.BOOK_SIZE],
                )
            # ATO/ATC. Unpriced, added to their side's quantity at every price
            # level in the cross calculation, and matched ahead of all limit
            # orders (rulebook 2.4, QD 352 Dieu 14.3-14.4, unconditional to
            # 2025-05-04 and still ahead of in-band limits after it). An
            # auction-order that reaches a cross is therefore a through-priced
            # order under step (a) and fills in full.
            return self._sized_fill(order, interval, rules, clearing,
                                    FillEvidence.AUCTION_PRICE,
                                    already_filled=already_filled,
                                    instrument=instrument)

        reach = _reach(order.order.side, clearing, limit)
        if reach < 0:
            return FillDecision.no_fill(
                f'the auction cleared at {clearing}, past a limit of {limit}; '
                f'a call auction cannot execute an order priced away from the '
                f'clearing price'
            )
        if reach == 0:
            return FillDecision.indeterminate(
                f'the auction cleared exactly at the limit of {limit}; '
                f'allocation at the marginal price is UNVERIFIED for the '
                f'ATO/ATC cross -- no Vietnamese document states the rule '
                f'(rulebook 2.4)',
                (),
            )
        return self._sized_fill(order, interval, rules, clearing,
                                FillEvidence.AUCTION_PRICE,
                                already_filled=already_filled,
                                instrument=instrument)

    # -- sizing ---------------------------------------------------------

    def _sized_fill(
        self,
        order: OrderRecord,
        interval: MarketInterval,
        rules: Exchange,
        price: Decimal,
        evidence: FillEvidence,
        *,
        already_filled: int,
        instrument: Optional[InstrumentSpec],
    ) -> FillDecision:
        """Apply conventions 2 and 3 to an established fill.

        Reached only once the price test has already said yes, so a missing
        volume is reported as ignorance about *this* order rather than about
        every order in the book.
        """
        if (evidence is FillEvidence.AUCTION_PRICE
                and interval.resolution is Resolution.DAILY):
            # A daily bar's volume is the whole session's, including continuous
            # trading. max_participation of it is not a bound on the auction's
            # own volume, and pretending otherwise would size an auction fill
            # from liquidity that traded hours earlier.
            return FillDecision.indeterminate(
                'a daily bar\'s volume covers the whole session, so the '
                'auction\'s own volume cannot be attributed and the '
                'participation cap cannot be applied to a cross',
                [DataField.VOLUME],
            )

        cap = participation_cap(interval, self.max_participation,
                                already_filled)
        if cap is None:
            return FillDecision.indeterminate(
                'the market traded through the limit, but with no observed '
                'volume the participation cap cannot be computed, so how much '
                'would have filled cannot be established',
                [DataField.VOLUME],
            )
        if cap <= 0:
            return FillDecision.no_fill(
                'the participation cap for this instrument is already '
                'exhausted by this caller\'s own fills in this interval'
            )

        lot = self._lot(rules, instrument)
        quantity = floor_to_lot(min(order.remaining_quantity, cap), lot)
        if quantity <= 0:
            return FillDecision.no_fill(
                f'the remaining participation allowance of {cap} is below one '
                f'round lot of {lot}'
            )
        return FillDecision.fill(quantity, price, evidence)


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

def build_fill_policy(config: FillPolicyConfig) -> FillPolicy:
    """The policy named by ``fill_policy.kind`` in the session config.

    Raises:
        ValueError: on an unknown kind. ``'probabilistic'`` gets its own
            message: it is not unimplemented by oversight, it needs
            ``BookLevel.size``, which is ``None`` on every corpus available
            here (``quote_asksize``, ``quote_bidsize``, ``quote_totalask`` and
            ``quote_totalbid`` are 0-row in both roots). Defaulting it to
            ``soft`` would silently substitute a different assumption for the
            one the caller asked for.
    """
    kind = (config.kind or '').strip().lower()
    if kind == SoftFillPolicy.kind:
        return SoftFillPolicy()
    if kind == HardFillPolicy.kind:
        return HardFillPolicy(max_participation=config.max_participation)
    if kind == 'probabilistic':
        raise ValueError(
            'the probabilistic fill policy needs order-book sizes, and '
            'BookLevel.size is None on every corpus available here; it is '
            'deferred until the size backfill lands (design section 8)'
        )
    raise ValueError(
        f'unknown fill policy {config.kind!r}; known kinds are '
        f'{SoftFillPolicy.kind!r} and {HardFillPolicy.kind!r}'
    )


# --------------------------------------------------------------------------
# Private helpers
# --------------------------------------------------------------------------

def _validate(order: OrderRecord, interval: MarketInterval,
              already_filled: int) -> None:
    """Refuse an evaluation that cannot mean anything, loudly.

    These raise rather than returning ``INDETERMINATE`` on purpose: each is an
    integration bug, and an ``INDETERMINATE`` returned for a bug is counted
    into ``IndeterminateReport`` and published as market ignorance. The
    ignorance rate is a headline number; it must contain only real ignorance.
    """
    if order.order.ticker != interval.ticker:
        raise ValueError(
            f'order {order.order_id} is on {order.order.ticker} but the '
            f'interval is {interval.ticker}; a fill policy must never cross '
            f'instruments'
        )
    if order.order.side not in (Side.BUY, Side.SELL):
        # Side.CROSS is a negotiated put-through, not order matching, and its
        # .sign returns None -- the landmine types.py's signed_quantity exists
        # to refuse. No order-matching fill can be determined for it.
        raise ValueError(
            f'order {order.order_id} has side {order.order.side}, which is a '
            f'negotiated trade rather than order matching; no fill policy can '
            f'decide it'
        )
    if already_filled < 0:
        raise ValueError(
            f'already_filled must not be negative, got {already_filled}')
    if order.is_terminal and order.remaining_quantity > 0:
        raise ValueError(
            f'order {order.order_id} is terminal in state {order.state.value} '
            f'with {order.remaining_quantity} unfilled; the session must not '
            f'evaluate a dead order'
        )


def _auction_phase(order: OrderRecord,
                   interval: MarketInterval) -> Optional[SessionPhase]:
    """Which auction, if any, this order would participate in here.

    The order type decides first because ATO and ATC each name their own
    window; the interval's phase decides for everything else, so that a limit
    order carried from the continuous session into the cross (rulebook 2.3)
    prices off the auction it actually reached.
    """
    order_type = order.order.order_type
    if order_type is OrderType.AT_THE_OPENING:
        return SessionPhase.OPENING_AUCTION
    if order_type is OrderType.AT_THE_CLOSE:
        return SessionPhase.CLOSING_AUCTION
    if interval.session in (SessionPhase.OPENING_AUCTION,
                            SessionPhase.CLOSING_AUCTION):
        return interval.session
    return None


def _clearing_price(
    order: OrderRecord,
    interval: MarketInterval,
) -> Tuple[Optional[Decimal], Optional[DataField]]:
    """The cross price and, when it is absent, the field to name for it."""
    phase = _auction_phase(order, interval)
    field = (DataField.OPEN if phase is SessionPhase.OPENING_AUCTION
             else DataField.CLOSE)
    return auction_fill_price(order, interval), field


def _point_price(interval: MarketInterval) -> Optional[Decimal]:
    """A single observed traded price for the interval, if there is one.

    ``close`` first, then the snapshot's ``last``. Both are prices that
    actually traded; neither bounds the interval, which is why every use of
    this is asymmetric -- it can prove a fill and never disprove one.
    """
    if interval.close is not None:
        return interval.close
    return interval.state.last


def _extreme_toward(
    side: Side,
    interval: MarketInterval,
) -> Tuple[Optional[Decimal], DataField]:
    """The interval extreme that decides this side, and its field name.

    A buy is decided by the ``low`` (the best price anyone sold at) and a sell
    by the ``high``. Returning the field alongside the value is what lets an
    ``INDETERMINATE`` name the one that was missing, per design section 9.
    """
    if side is Side.BUY:
        return interval.low, DataField.LOW
    return interval.high, DataField.HIGH


def _reach(side: Side, observed: Decimal, limit: Decimal) -> int:
    """How far an observed price got relative to a limit, from ``side``'s view.

    ``1`` strictly through (better for us than our own price), ``0`` exactly at
    it, ``-1`` short of it. One function so that the buy/sell inversion is
    written once; every policy in this module reads its answer, and a second
    copy of the comparison is how a sell-side sign error survives review.
    """
    if side is Side.BUY:
        if observed < limit:
            return 1
        return 0 if observed == limit else -1
    if observed > limit:
        return 1
    return 0 if observed == limit else -1


def _touched(observed: Decimal) -> FillDecision:
    """The touched-at-limit ``INDETERMINATE``, with its reasoning attached.

    Named because it is the single most important decision this module makes.
    Trades happened at our exact price; whether ours was among them is decided
    by time priority (rulebook 2.4: price then time, no size priority, no
    pro-rata), and time priority cannot be recovered from a corpus with no
    order ids in which 81% of best-quote changes carry no trade. Calling it a
    fill is the soft policy's assumption; calling it a no-fill would be equally
    unfounded and merely pessimistic.
    """
    return FillDecision.indeterminate(
        f'the market touched the limit at {observed} but did not trade '
        f'through it; whether this order was ahead in the time-priority queue '
        f'cannot be recovered -- there are no order ids and 81% of best-quote '
        f'changes carry no trade',
        (),
    )
