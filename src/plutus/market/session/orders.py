"""The order state machine -- locked shape 4, *the order type is the time-in-force*.

Vietnam has no separate time-in-force field on any venue at any date in
2020-2026. What a broker screen elsewhere calls "DAY / IOC / FOK" is here the
**order type itself**: an LO is a day order because it is an LO, an MOK is
fill-or-kill because it is an MOK. So the forbidden build is a single
``RESTING`` state with one "expire at every phase boundary" rule -- it would
expire the whole book at the noon break, put an MOK on the book that by rule
was never on it, and carry an ATO past its own cross.

The graph, the legal edges, the type-to-time-in-force map and the per-type
terminal triggers are **data**, in :mod:`plutus.market.session.types`:
``LEGAL_TRANSITIONS``, ``TIME_IN_FORCE``, ``TERMINAL_TRIGGERS_BY_TIF``,
``EVENT_FOR_TRANSITION``. This module reads them. It deliberately holds no
second copy of any of them, because two copies of a state graph is how a
simulator ends up enforcing a rule it does not document.

State-transition table
----------------------

``submit()`` forks once and nowhere else::

                       submit()
                          |
            +-------------+-------------+
        REJECTED                     ACCEPTED
      (rule named)                      |
       [terminal]                       |
                        +---------------+---------------+
                        |               |               |
                     RESTING     PARTIALLY_FILLED     FILLED
                        |          (self-edge)      [terminal]
                        +--------> CANCELLED (caller)  [terminal]
                        +--------> EXPIRED   (per type) [terminal]

Every edge, with its cause and the event it emits:

===================  ==================  ==============  ====================
from                 to                  transition      event
===================  ==================  ==============  ====================
(submit)             ACCEPTED            ``ACCEPT``      ``ACCEPTED``
(submit)             REJECTED            ``REJECT``      ``REJECTED``
ACCEPTED             RESTING             ``REST``        -- (silent)
ACCEPTED             PARTIALLY_FILLED    ``PARTIAL_FILL``  ``PARTIALLY_FILLED``
ACCEPTED             FILLED              ``FILL``        ``FILLED``
ACCEPTED             CANCELLED           ``CANCEL``      ``CANCELLED``
ACCEPTED             EXPIRED             ``EXPIRE``      ``EXPIRED``
RESTING              PARTIALLY_FILLED    ``PARTIAL_FILL``  ``PARTIALLY_FILLED``
RESTING              FILLED              ``FILL``        ``FILLED``
RESTING              CANCELLED           ``CANCEL``      ``CANCELLED``
RESTING              EXPIRED             ``EXPIRE``      ``EXPIRED``
PARTIALLY_FILLED     PARTIALLY_FILLED    ``PARTIAL_FILL``  ``PARTIALLY_FILLED``
PARTIALLY_FILLED     FILLED              ``FILL``        ``FILLED``
PARTIALLY_FILLED     CANCELLED           ``CANCEL``      ``CANCELLED``
PARTIALLY_FILLED     EXPIRED             ``EXPIRE``      ``EXPIRED``
===================  ==================  ==============  ====================

``REST`` is the only silent transition: resting is a state, not news, and the
caller reads it from :meth:`OrderBookOfRecord.orders`. ``INDETERMINATE`` is
**not** in this table at all -- it is an event meaning the fill policy could
not decide for one interval, and the order stays where it is.

**``RESTING`` is reachable only from ``ACCEPTED``, and that is not an
omission.** ``LEGAL_TRANSITIONS`` has no ``PARTIALLY_FILLED -> RESTING`` edge,
so a partially filled order that remains on the book stays in
``PARTIALLY_FILLED``. The state axis tracks fill progress; "is on the book" is
implied by the state being live. This is what makes an MTL residue expressible
at all (see :meth:`OrderBookOfRecord.convert_residue`).

Per type, which is per time-in-force
------------------------------------

=======  =====================  =================================================
type     time-in-force          lifecycle
=======  =====================  =================================================
LO       ``DAY``                Rests until filled, cancelled, or the last
                                matching phase of its day ends. Enterable in
                                continuous *and* auction phases; an unfilled
                                continuous LO is carried into the following
                                auction and participates in the cross
                                (rulebook 2.3, QD 352 Dieu 14.1(c), 17.2, high).
ATO      ``AUCTION_ONLY``       Only meaningful inside the opening call.
                                Enterable only in its own window; the unmatched
                                remainder is auto-cancelled *at the cross* --
                                it never rests and never carries
                                (rulebook 2.3, QD 352 Dieu 14.3(b), high).
ATC      ``AUCTION_ONLY``       The same, for the closing call
                                (QD 352 Dieu 14.4(b), high).
MOK      ``FILL_OR_KILL``       Fills in full at entry or is cancelled entirely.
                                **Never rests and is never partially filled** --
                                a partial fill of an MOK is a contradiction, and
                                :meth:`OrderBookOfRecord.apply_fill` raises on
                                one (rulebook 2.3, ASEANSC HNX 2.3, high).
MAK      ``IMMEDIATE_OR_CANCEL``  Keeps whatever fills at entry; the remainder
                                dies at once. Never rests (same source).
MTL      ``IMMEDIATE_THEN_DAY``  Sweeps the book from the best opposite price;
                                the residue **converts to a limit order** and
                                rests. The one market type that can rest, which
                                is why ``IMMEDIATE_THEN_DAY`` exists as a
                                distinct time-in-force. Cancelled at entry if no
                                opposite limit order exists (rulebook 2.3, VNX
                                QD 22/2025 Dieu 17.2(b), high).
MKT      -- none --             **Matches no Vietnamese order type at any
                                date.** See :func:`is_vietnamese_order_type`.
=======  =====================  =================================================

Two types the rulebook carries and this module cannot see, stated so the
absence is declared rather than silent:

* **PLO** (HNX post-close, 14:45-15:00) has no member in
  :class:`plutus.core.order.OrderType`, so no order in this simulator can be
  one. Its rules -- limit order without a price, executes at the day's last
  round-lot matched price, no amend, no cancel, expires 15:00 -- are therefore
  unimplemented, not merely untested.
* **MP** is HOSE's pre-2025-05-05 mnemonic for the same economics as MTL. The
  rulebook records the KRX change as a mnemonic swap, so anything true of MTL
  here is true of MP on its dates.

What this module does not own
-----------------------------

It does not import ``ledgers.py`` and must not. Locked shape 4 requires the
per-type terminal edges to *share* the encumbrance-release hook, so
:class:`OrderBookOfRecord` takes that hook as a callback (``on_terminal``) and
``exchange.py`` wires it to the ledgers. One callback, every terminal edge, no
import cycle -- and a terminal transition that forgets to release becomes
impossible by construction rather than by review.

It also does not decide *whether* an order fills (``fills.py``), what it may
cost (``ledgers.py``), or which types a venue accepts on a date
(``rulebook.py``'s ``RuleSet.legal_order_types``). It records what happened and
refuses to record something the state machine forbids.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import (Callable, Dict, FrozenSet, List, Mapping, Optional,
                    Sequence, Set, Tuple, Union)

from plutus.core.order import OrderType
from plutus.market.protocol import Order, SessionPhase
from plutus.market.session.types import (EVENT_FOR_TRANSITION,
                                         LEGAL_TRANSITIONS,
                                         TERMINAL_TRIGGERS_BY_TIF,
                                         TIME_IN_FORCE, Amended, Encumbrance,
                                         Event, EventKind, ExpiryTrigger, Fill,
                                         OrderId, OrderRecord, OrderState,
                                         OrderTransition, Rejected,
                                         ResourceKind, TimeInForce, Venue,
                                         new_order_id_seed)
from plutus.market.verdicts import AdmissionRule, Verdict

__all__ = [
    'OrderIdFactory', 'OrderBookOfRecord', 'EncumbranceDivergence',
    'amend_cancel_lock', 'amendment_preserves_priority', 'expires_at_boundary',
    'is_legal_transition', 'is_vietnamese_order_type',
    'UNVENUED_ORDER_TYPES',
]


# --------------------------------------------------------------------------
# Order types with no Vietnamese counterpart
# --------------------------------------------------------------------------

#: Types carried by :class:`plutus.core.order.OrderType` that no Vietnamese
#: venue accepts at any date.
#:
#: The rulebook's finding is a flat negative and it is graded ``high``:
#: "Synthetic 'market at ceiling/floor' order -- **No such order type exists in
#: Vietnam at any date**" (rulebook 2.2, negative finding across all four
#: rulebooks). ``core/order.py:56`` documents ``MKT`` as "sell at floor or buy
#: at ceiling for guaranteed match", which is a *backtester's* convenience, not
#: an order a matching engine ever received.
#:
#: It is named here rather than left to fall through a default branch because a
#: default branch is exactly how a synthetic type acquires real semantics.
UNVENUED_ORDER_TYPES: FrozenSet[OrderType] = frozenset({OrderType.MARKET})


def is_vietnamese_order_type(order_type: OrderType) -> bool:
    """Whether any Vietnamese venue accepts this type at any date.

    False only for :data:`UNVENUED_ORDER_TYPES`. This is a *categorical*
    question and is deliberately not the dated one: which types a given venue
    accepts in a given phase on a given day is
    ``rulebook.RuleSet.legal_order_types(venue, phase)``, and it is that call,
    not this one, that produces a market rejection.
    """
    return order_type not in UNVENUED_ORDER_TYPES


# --------------------------------------------------------------------------
# Phase-shaped rules
# --------------------------------------------------------------------------

#: Phases in which an order can match. Used only by
#: :func:`expires_at_boundary`, to answer "was that the last matching phase of
#: the day" without being told the venue.
#:
#: ``POST_CLOSE_PLO`` is deliberately **absent**. HNX's 14:45-15:00 session
#: matches PLO orders only -- a limit order without a price, executing at the
#: day's last round-lot matched price -- so no LO, MTL or auction order can
#: match in it. Treating it as a matching phase would carry a day order past
#: the ATC on HNX, which is where a day order actually dies.
_MATCHING_PHASES: FrozenSet[SessionPhase] = frozenset({
    SessionPhase.OPENING_AUCTION,
    SessionPhase.CONTINUOUS,
    SessionPhase.CLOSING_AUCTION,
})

#: The two call auctions. An ``AUCTION_ONLY`` order dies at the end of one.
_AUCTION_PHASES: FrozenSet[SessionPhase] = frozenset({
    SessionPhase.OPENING_AUCTION,
    SessionPhase.CLOSING_AUCTION,
})

#: Phases in which the venue accepts no amendment and no cancellation, and the
#: sourced reason for each. Every entry is a rulebook row, not a guess, except
#: the two marked ADOPTED.
_AMEND_CANCEL_LOCKS: Mapping[SessionPhase, str] = {
    SessionPhase.OPENING_AUCTION: (
        'the opening call auction is locked: no amendment and no cancellation '
        'of LO, ATO or ATC while a call auction is running, for its whole '
        'duration and not merely at the cross (rulebook 2.5; QD 352 Dieu 17.1, '
        'VNX QD 17 Dieu 22, QD 22/2025 Dieu 21; unchanged across the whole '
        'window -- several write-ups present this as a KRX novelty and it is '
        'not)'
    ),
    SessionPhase.CLOSING_AUCTION: (
        'the closing call auction is locked, and the lock covers LOs carried '
        'in from the continuous session ("bao gom ca cac lenh LO duoc chuyen '
        'tu phien khop lenh lien tuc sang"), so from 14:30 a resting LO can be '
        'neither amended nor cancelled (rulebook 2.5; VNX QD 22/2025 Dieu '
        '21.4). Whether that parenthetical is present in the pre-KRX QD 17 '
        'Dieu 22.4 is UNVERIFIED; we apply the lock across the whole window '
        'because the auction lock itself is high-confidence at every date'
    ),
    SessionPhase.NOON_BREAK: (
        'the lunch break is a hard shutdown: 11:30-13:00 admits no entry, no '
        'amendment and no cancellation (rulebook 2.1; QD 352 Dieu 21, high). '
        'Note this stops *instructions*, not the book -- resting orders '
        'survive the break, which is why ExpiryTrigger has no NOON_BREAK '
        'member'
    ),
    SessionPhase.POST_CLOSE_PLO: (
        'the HNX post-close session is locked: no amend, no cancel (rulebook '
        '2.5; VNX QD 22/2025 Dieu 21.5, ASEANSC HNX 3, high)'
    ),
    SessionPhase.PRE_OPEN: (
        'ADOPTED, not sourced: no matching session is running to receive the '
        'instruction. No Vietnamese document in the rulebook states what '
        'happens to a cancellation submitted outside trading hours, because '
        'the question is a broker-channel one rather than an exchange one'
    ),
    SessionPhase.POST_CLOSE: (
        'ADOPTED, not sourced: the market has closed for the day and the book '
        'is gone. Same absence of evidence as PRE_OPEN'
    ),
    SessionPhase.UNKNOWN: (
        'the session phase is not known, so whether the venue would accept the '
        'instruction cannot be judged. Absence of evidence is not evidence of '
        'admissibility'
    ),
}


def is_legal_transition(frm: OrderState, to: OrderState) -> bool:
    """Whether the state machine permits this edge.

    Reads ``LEGAL_TRANSITIONS`` and nothing else. This is the single
    enforcement point for section 12 invariant 2 -- *a terminal order state is
    never left* -- which holds because every terminal state maps to an empty
    frozenset, so no edge out of one is ever legal.
    """
    return to in LEGAL_TRANSITIONS.get(frm, frozenset())


def expires_at_boundary(
    tif: TimeInForce,
    ending: SessionPhase,
    beginning: SessionPhase,
) -> Optional[ExpiryTrigger]:
    """The trigger a phase change fires for this time-in-force, or ``None``.

    **A phase boundary does not expire an order. A boundary that this function
    names a trigger for does.** That difference is locked shape 4, and the
    three cases below are the ones a naive build gets wrong.

    * **The noon break expires nothing, ever.** 11:30-13:00 is a hard shutdown
      for entry, amendment and cancellation (rulebook 2.1, QD 352 Dieu 21) but
      the book survives it, and a simulator that expires at every boundary
      destroys the afternoon book. This is checked first and returns ``None``
      whichever side of the boundary the break is on. It is also why
      :class:`ExpiryTrigger` has no ``NOON_BREAK`` member -- the absence is the
      enforcement.
    * **An unmatched ATO dies at its own cross**, 09:15 on HSX and 09:00 on
      HNXDS; likewise an ATC at 14:45. They are enterable only inside their own
      window and the remainder is auto-cancelled at the cross: they never rest
      and never carry (rulebook 2.3, QD 352 Dieu 14.3(b)/14.4(b), high).
    * **A day order dies at the end of the last matching phase of its day**, not
      at the first boundary it meets. So a resting LO crosses
      ``CONTINUOUS -> CLOSING_AUCTION`` untouched and participates in the ATC
      cross (rulebook 2.3, QD 352 Dieu 17.2), and dies only when the phase it
      leaves could match and the phase it enters cannot.

    The venue is deliberately **not** a parameter. Framing the last matching
    phase as ``ending in _MATCHING_PHASES and beginning not in`` answers it for
    HSX (``CLOSING_AUCTION -> POST_CLOSE``), HNX (``CLOSING_AUCTION ->
    POST_CLOSE_PLO``, because PLO matches no LO) and UPCoM (``CONTINUOUS ->
    POST_CLOSE``) with one rule and no venue table to drift.

    The immediate families -- ``FILL_OR_KILL`` and ``IMMEDIATE_OR_CANCEL`` --
    always return ``None``. Their terminal triggers fire at *entry*, not at a
    boundary: nothing in the rulebook gives an MOK or MAK a boundary rule,
    because by the time a boundary arrives one cannot still be live. If one is,
    that is a bug in ``exchange.py``'s submit path, and inventing a boundary
    rule here would hide it. See :meth:`OrderBookOfRecord.expire_due`.

    An ``UNKNOWN`` phase on either side returns ``None``. Note the direction:
    at *admission* absent data yields ``INDETERMINATE`` and keeps the order
    out, but here the conservative answer is the opposite one, because expiring
    a book on a data gap destroys state that cannot be recovered while leaving
    it alone can be corrected on the next known boundary.
    """
    if SessionPhase.NOON_BREAK in (ending, beginning):
        return None
    if SessionPhase.UNKNOWN in (ending, beginning):
        return None
    if tif is TimeInForce.AUCTION_ONLY:
        if ending in _AUCTION_PHASES:
            return ExpiryTrigger.AUCTION_CROSS
        return None
    if tif.rests:
        if ending in _MATCHING_PHASES and beginning not in _MATCHING_PHASES:
            return ExpiryTrigger.SESSION_END
        return None
    return None


def amend_cancel_lock(phase: SessionPhase) -> Optional[str]:
    """Why this phase refuses amendment and cancellation, or ``None``.

    The rulebook expresses the equity lock **per order type** ("no amendment
    and no cancellation of LO, ATO, ATC while an auction is running") and the
    derivatives lock **per session** (the whole 08:45-09:00 and 14:30-14:45
    periodic sessions are locked, not merely their crosses). The two readings
    coincide on everything Tier 1 submits, so this function is phase-shaped:
    it takes the widest of the two, which is the derivatives form.

    Returns the sourced reason string so a rejection can carry *why* rather
    than only *that*, and so the two ADOPTED entries -- ``PRE_OPEN`` and
    ``POST_CLOSE``, for which the rulebook has nothing -- say so in the log.
    """
    return _AMEND_CANCEL_LOCKS.get(phase)


def amendment_preserves_priority(
    old_quantity: int,
    new_quantity: int,
    price_changed: bool,
) -> bool:
    """Whether an amendment keeps the order's place in the queue.

    **Priority survives a pure quantity decrease and nothing else.** It
    restarts on a quantity increase and on any price change (rulebook 2.5, VNX
    QD 17 Dieu 22.3 read verbatim, effective 2022-03-31; retained by QD 22/2025
    Dieu 21.3 and QD 22/2026 Dieu 23). Vietnam has exactly two priority levels,
    price then time, with no size or member-class priority (rulebook 2.4), so
    there is no third quantity for this rule to turn on.

    This is the rule *from 2022-03-31*. Two dated qualifications the caller
    must supply rather than this function assume:

    * **Before 2022-03-31 on HOSE there was no priority-preserving amendment at
      all** -- amendment *was* cancel-the-order-and-enter-a-new-one, and time
      priority always restarted (QD 352 Dieu 17.1-17.3, read verbatim, high).
    * **The rulebook records an unresolved CONFLICT for HOSE 2022-03-31 to
      2025-05-04**: QD 17 permits priority-preserving amendment, while
      Vietcap's KRX handbook records the legacy HOSE engine as not implementing
      it and brokers offering cancel-and-replace instead. The rulebook adopts
      "permitted in the rulebook, not implemented by the engine" and records
      both readings, because the choice changes queue-position modelling for
      three years of the sample.

    Both are expressed through ``OrderBookOfRecord.amend``'s
    ``priority_preserving`` flag, which ``exchange.py`` resolves from
    ``rulebook.at(ts)``. This function does not date itself, because a dated
    lookup in this module would be a second rulebook.
    """
    if price_changed:
        return False
    return new_quantity < old_quantity


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

class OrderIdFactory:
    """Mints exchange-assigned order ids.

    Ids are strings because a broker id is a string, and the point of this
    package is to be shaped like a broker. They are zero-padded so that lexical
    order matches issue order -- a log sorted as text then reads in the order
    the exchange saw the orders, which is the only priority axis Vietnam has
    besides price (rulebook 2.4: two levels only, price then time).
    """

    def __init__(self, prefix: str = 'PLU', start: int = new_order_id_seed
                 ) -> None:
        self._prefix = prefix
        self._next = start
        self._start = start

    def next(self) -> OrderId:
        """The next id. Shadows the builtin deliberately: the interface
        contract names this method ``next``."""
        order_id = OrderId(f'{self._prefix}-{self._next:08d}')
        self._next += 1
        return order_id

    @property
    def issued(self) -> int:
        """How many ids have been minted. One per submission, accepted or not."""
        return self._next - self._start


# --------------------------------------------------------------------------
# The book of record
# --------------------------------------------------------------------------

#: The encumbrance-release hook. Fires on every edge into a terminal state,
#: exactly once per order, with the terminal record, the transition that got it
#: there and the instant.
TerminalHook = Callable[[OrderRecord, OrderTransition, datetime], None]

#: Optional event sink. ``exchange.py`` wires this to its single destructive
#: cursor; without it, events accumulate in the book's own journal.
EventSink = Callable[[Event], None]

#: Optional ordinal source. ``Event.seq`` must be *session*-monotonic, and the
#: session owns more event families than orders, so the session may supply its
#: own counter rather than let the book number events privately.
SeqSource = Callable[[], int]


@dataclass(frozen=True)
class EncumbranceDivergence:
    """One order, one resource, on which the record and the ledger disagree.

    A row of :meth:`OrderBookOfRecord.encumbrance_divergence`. Both numbers are
    carried rather than their difference, because *which side is high* is the
    whole diagnosis: a record above the ledger overstates what the account has
    promised and costs the caller nothing but a wrong report, while a record
    *below* the ledger under-reports a commitment -- a summed-over-records view
    would then let the same parcel be sold twice.

    Exactly one of the two pairs is meaningful per resource, the same split
    :class:`~plutus.market.session.types.Encumbrance` makes: ``CASH`` and
    ``DEPOSIT`` are denominated in ``*_amount``, ``SHARES`` in ``*_quantity``.
    Both pairs are reported anyway so a reader never has to know which, and
    :attr:`is_clean` compares both.
    """

    order_id: OrderId
    state: OrderState
    resource: ResourceKind
    record_amount: Decimal
    ledger_amount: Decimal
    record_quantity: int
    ledger_quantity: int
    ticker: Optional[str] = None

    @property
    def is_clean(self) -> bool:
        """True when the two sides agree on both denominations."""
        return (self.record_amount == self.ledger_amount
                and self.record_quantity == self.ledger_quantity)

    def __str__(self) -> str:
        return (f'{self.order_id} ({self.state.value}) '
                f'{self.resource.value}'
                f'{"" if self.ticker is None else " " + self.ticker}: '
                f'record {self.record_amount}/{self.record_quantity} vs '
                f'ledger {self.ledger_amount}/{self.ledger_quantity}')


class OrderBookOfRecord:
    """The caller's own orders, by id. The mutable half; ``OrderRecord`` is frozen.

    Every transition happens here and nowhere else. That is what makes section
    12's invariants checkable at one point instead of everywhere a field is
    assigned:

    1. ``filled + remaining == original`` -- structural, because
       :class:`OrderRecord` derives both from ``fills``.
    2. A terminal state is never left -- enforced by
       :func:`is_legal_transition` against ``LEGAL_TRANSITIONS``, whose
       terminal rows are empty.
    3. Every transition carries a timestamp and a cause --
       ``OrderRecord.with_state`` takes both and this class never bypasses it.
    4. Encumbrance is released on **every** terminal edge -- ``on_terminal``
       fires from one private method that all four edges route through.

    Insertion order is preserved, so :meth:`orders` and :meth:`live` return
    orders in the sequence the exchange received them. Time priority is one of
    Vietnam's only two priority levels and there is nowhere else to record it:
    :class:`OrderRecord` carries ``submitted_at`` but no separate queue-priority
    instant, so an amendment that *restarts* priority cannot be represented in
    the record. It is reported through ``Amended.priority_preserved`` instead.
    Tier 1 runs no queue-position matching, so nothing reads it yet.
    """

    def __init__(
        self,
        ids: OrderIdFactory,
        *,
        on_terminal: TerminalHook,
        on_event: Optional[EventSink] = None,
        next_seq: Optional[SeqSource] = None,
    ) -> None:
        """Wire the shared hooks.

        ``on_terminal`` is the encumbrance-release hook. Wiring it **here**,
        once, rather than at each call site is what makes "released on every
        terminal transition" structural: there is no way to add a terminal edge
        that skips it, because every terminal edge goes through
        :meth:`_terminate`.

        ``on_event`` and ``next_seq`` are additions to the interface contract's
        signature, both keyword-only with defaults, so the promised
        ``OrderBookOfRecord(ids, on_terminal=...)`` call is unchanged. They
        exist because a transition that emits no event is a transition the
        caller cannot poll: the design puts every order event on one
        session-level destructive cursor, and the book has to be able to feed
        it. Without ``on_event`` the events accumulate in the book's own
        journal and :meth:`drain_events` empties it.
        """
        self._ids = ids
        self._on_terminal = on_terminal
        self._on_event = on_event
        self._next_seq: SeqSource = next_seq or self._own_seq
        self._seq = 0
        self._records: Dict[OrderId, OrderRecord] = {}
        self._events: List[Event] = []
        self._terminated: Set[OrderId] = set()

    # -- internals ------------------------------------------------------

    def _own_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _store(self, record: OrderRecord) -> OrderRecord:
        self._records[record.order_id] = record
        return record

    def _require(self, order_id: OrderId) -> OrderRecord:
        """The record, or ``KeyError``.

        An unknown id is a *programming* error -- the caller invented an id the
        exchange never issued -- and is raised rather than returned as a
        ``Rejected``. A ``Rejected`` is a market answer, and reporting a
        caller bug as a market rule would put a phantom row in the rejection
        log that the paper's rejection rates then count.
        """
        try:
            return self._records[order_id]
        except KeyError:
            raise KeyError(
                f'no order {order_id!r} in the book of record; ids are minted '
                f'by OrderIdFactory and never guessed'
            ) from None

    def _require_legal(self, frm: OrderState, to: OrderState,
                       order_id: OrderId) -> None:
        if not is_legal_transition(frm, to):
            raise ValueError(
                f'illegal transition {frm.value} -> {to.value} for order '
                f'{order_id}: LEGAL_TRANSITIONS does not carry that edge. If '
                f'{frm.value} is terminal this is invariant 2 -- a terminal '
                f'order state is never left.'
            )

    def _emit(self, event: Event) -> Event:
        self._events.append(event)
        if self._on_event is not None:
            self._on_event(event)
        return event

    def _terminate(self, record: OrderRecord, transition: OrderTransition,
                   ts: datetime) -> OrderRecord:
        """Fire the release hook once, then stamp the reservations released.

        Order matters. ``on_terminal`` sees the record with its reservations
        still on it, because that is what the ledger needs in order to release
        the right amounts; only after it returns does the record stop claiming
        them. A caller reacting to the event that follows therefore sees
        ledgers and book already agreeing.

        What *happened* to the resources -- consumed at the fill price,
        returned in full, released pro rata -- is ``ledgers.py``'s accounting.
        The book records only that this order no longer reserves anything,
        which is what section 12 invariant 4's "committed returns to zero when
        no order is live" tests against.
        """
        if record.order_id in self._terminated:
            raise RuntimeError(
                f'order {record.order_id} reached a terminal state twice; the '
                f'release hook must fire exactly once per order'
            )
        self._terminated.add(record.order_id)
        self._on_terminal(record, transition, ts)
        released = tuple(enc.released(ts) for enc in record.encumbrances)
        return self._store(record.with_encumbrances(released))

    # -- entry ----------------------------------------------------------

    def accept(
        self,
        order: Order,
        venue: Venue,
        ts: datetime,
        *,
        regime_tag: Optional[str] = None,
        encumbrances: Sequence[Encumbrance] = (),
        order_id: Optional[OrderId] = None,
    ) -> OrderRecord:
        """Admit an order in ``ACCEPTED``, with its time-in-force fixed.

        ``time_in_force`` comes from ``TIME_IN_FORCE[order.order_type]`` and is
        stored, not recomputed. Locked shape 4 in one line: the order's type
        *is* how long it lives, and fixing it at accept is what lets an MTL
        residue keep saying it was an MTL after it has become a resting LO.

        ``order_id`` is an addition to the contract's signature, keyword-only.
        It is needed because the contract's own ``submit()`` sequence reserves
        before it accepts and ``reserve_for_buy(order_id, ...)`` takes an id --
        so the id must exist before this call. Pass the one you minted; omit it
        and the book mints one.

        Raises:
            ValueError: on ``OrderType.MARKET``. **This is not a market
                rejection and must not be logged as one.** No Vietnamese venue
                accepts ``MKT`` at any date (rulebook 2.2, negative finding
                across all four rulebooks, high), so an ``MKT`` reaching the
                book of record means ``exchange.py`` skipped
                ``RuleSet.legal_order_types()`` -- a bug in the caller, not an
                event in the market. The same reasoning, and the same loud
                refusal, as ``types.signed_quantity`` on ``Side.CROSS``.
                :meth:`reject` deliberately does *not* raise on it, so the
                legality check that catches it can still log its row.
            ValueError: if ``order_id`` is already in the book.
        """
        if not is_vietnamese_order_type(order.order_type):
            raise ValueError(
                f'{order.order_type} matches no Vietnamese order type at any '
                f'date: core/order.py carries MKT as a synthetic "buy at '
                f'ceiling / sell at floor" convenience and no matching engine '
                f'in Vietnam ever received one. Reject it through '
                f'RuleSet.legal_order_types(), which returns no venue-date '
                f'pair containing it; do not put one on the book of record.'
            )
        order_id = self._claim(order_id)
        record = OrderRecord(
            order_id=order_id,
            order=order,
            venue=venue,
            state=OrderState.ACCEPTED,
            time_in_force=TIME_IN_FORCE[order.order_type],
            submitted_at=ts,
            updated_at=ts,
            encumbrances=tuple(encumbrances),
            regime_tag=regime_tag,
            last_transition=OrderTransition.ACCEPT,
        )
        self._store(record)
        self._emit_for(OrderTransition.ACCEPT, record, ts,
                       time_in_force=record.time_in_force.value,
                       order_type=order.order_type.value)
        return record

    def reject(self, order: Order, venue: Venue,
               rejection: Rejected) -> OrderRecord:
        """Record a ``REJECTED`` row, with an id.

        A rejected order still gets an id so the rejection log joins to the
        submission. If ``rejection`` already carries one -- which it will
        whenever the refusal came from the reservation step, since those take
        the id -- that id is adopted rather than a second one minted.

        ``REJECTED`` is terminal, so ``on_terminal`` fires here too. It has
        nothing to release when the refusal came from ``admits()`` (no
        reservation was taken yet) and something to release when a later check
        refused after an earlier one reserved. Firing unconditionally is what
        makes "every terminal edge" true without the book having to know which
        step refused.
        """
        order_id = self._claim(rejection.order_id)
        if rejection.order_id is None:
            rejection = replace(rejection, order_id=order_id)
        record = OrderRecord(
            order_id=order_id,
            order=order,
            venue=venue,
            state=OrderState.REJECTED,
            time_in_force=TIME_IN_FORCE[order.order_type],
            submitted_at=rejection.ts,
            updated_at=rejection.ts,
            regime_tag=rejection.regime_tag,
            rejection=rejection,
            last_transition=OrderTransition.REJECT,
        )
        self._store(record)
        record = self._terminate(record, OrderTransition.REJECT, rejection.ts)
        self._emit(Event.rejected(rejection, self._next_seq(),
                                  ticker=order.ticker))
        return record

    def _claim(self, order_id: Optional[OrderId]) -> OrderId:
        if order_id is None:
            return self._ids.next()
        if order_id in self._records:
            raise ValueError(
                f'order id {order_id!r} is already in the book of record; an '
                f'id identifies one submission for the life of the session'
            )
        return order_id

    # -- transitions ----------------------------------------------------

    def rest(self, order_id: OrderId, ts: datetime) -> OrderRecord:
        """``ACCEPTED -> RESTING``. Emits no event: resting is a state, not news.

        Raises:
            ValueError: when ``record.time_in_force.rests`` is False. An MOK
                fills in full at entry or dies, an MAK keeps what filled and
                kills the rest, and an ATO/ATC is auto-cancelled at its own
                cross -- none of the three ever reaches a book. Putting one
                there is *the* shape-4 failure, so it raises rather than
                quietly succeeding.
            ValueError: from ``ACCEPTED``-only. ``LEGAL_TRANSITIONS`` has no
                ``PARTIALLY_FILLED -> RESTING`` edge; see the module docstring
                for why that is deliberate.
        """
        record = self._require(order_id)
        if not record.time_in_force.rests:
            raise ValueError(
                f'order {order_id} is {record.order.order_type} '
                f'({record.time_in_force.value}) and never rests: the order '
                f'type is the time-in-force, and only DAY and '
                f'IMMEDIATE_THEN_DAY reach a book'
            )
        self._require_legal(record.state, OrderState.RESTING, order_id)
        record = record.with_state(OrderState.RESTING, OrderTransition.REST, ts)
        self._store(record)
        self._emit_for(OrderTransition.REST, record, ts)
        return record

    def convert_residue(self, order_id: OrderId, ts: datetime,
                        limit_price: Decimal) -> OrderRecord:
        """Turn an MTL's unfilled residue into a resting limit order.

        MTL is the one market type that can rest, and this is the mechanism:
        the order walks the book from the best opposite price and *the residue
        converts to an LO*, which is why its time-in-force is
        ``IMMEDIATE_THEN_DAY`` and neither ``DAY`` nor
        ``IMMEDIATE_OR_CANCEL`` would do.

        ``limit_price`` is supplied by the caller, not computed here, because
        the price is a **tick-grid** question and the grid is dated and
        venue-specific -- ``rulebook.RuleSet.tick_size``, not this module. The
        rule the caller must implement (rulebook 2.3, VNX QD 22/2025 Dieu
        17.2(b) verbatim, high) is: **one tick beyond the last matched price**
        -- buy +1 tick, sell -1 tick -- **capped at the ceiling (buy) or floor
        (sell)** when the last match was already there. Two earlier extractions
        read "+/-1 tick" and "at the ceiling/floor" as rival rules; the
        gazetted sentence contains both clauses. A third reading, "exactly the
        last matched price", is rejected by the rulebook, and the brief that
        commissioned this module states that third reading -- so it is called
        out here rather than silently implemented.

        **Unresolved for derivatives.** On HNXDS the residual price is a
        recorded CONFLICT: the equity rule and MBS give last matched +/-1 tick,
        Vietcap's handbook gives best bid +1 / best ask -1, and the two differ
        whenever the book is not tight (rulebook 2.3, confidence low). This
        module takes a price and so is neutral between them; the choice, and
        the fact that it is a choice, belongs in whatever computes it.

        The converted record keeps ``time_in_force = IMMEDIATE_THEN_DAY`` while
        its ``order.order_type`` becomes ``LIMIT``. That is deliberate and it
        is the one place in this module where the stored time-in-force and
        ``TIME_IN_FORCE[order.order_type]`` disagree: the exchange's book now
        holds a limit order, and both time-in-forces rest and die at
        ``SESSION_END``, so behaviour is identical -- but the provenance of the
        resting price is only explicable if the record still says it arrived as
        a market order.

        A residue with nothing filled yet moves ``ACCEPTED -> RESTING``. A
        residue after a partial sweep **stays in ``PARTIALLY_FILLED``**: there
        is no ``PARTIALLY_FILLED -> RESTING`` edge, and being live is what puts
        an order on the book.
        """
        record = self._require(order_id)
        if record.time_in_force is not TimeInForce.IMMEDIATE_THEN_DAY:
            raise ValueError(
                f'only an IMMEDIATE_THEN_DAY order (MTL, and HOSE MP before '
                f'2025-05-05) converts its residue to a limit order; order '
                f'{order_id} is {record.time_in_force.value}'
            )
        if record.is_terminal:
            raise ValueError(
                f'order {order_id} is {record.state.value} and has no residue')
        if record.remaining_quantity <= 0:
            raise ValueError(
                f'order {order_id} has no remaining quantity to convert')
        converted = replace(record,
                            order=replace(record.order,
                                          order_type=OrderType.LIMIT,
                                          limit_price=limit_price),
                            updated_at=ts)
        self._store(converted)
        if converted.state is OrderState.ACCEPTED:
            return self.rest(order_id, ts)
        return converted

    def apply_fill(self, order_id: OrderId,
                   fill: Fill) -> Tuple[OrderRecord, EventKind]:
        """Record one execution. The resulting state is computed, never passed.

        A fill that exhausts the remainder is ``FILLED`` whatever its size, and
        one that does not is ``PARTIALLY_FILLED``; letting the caller name the
        state is how the two drift apart. ``OrderRecord.with_fill`` does the
        arithmetic and raises if it would break ``filled + remaining ==
        original``.

        Raises:
            ValueError: on a terminal order. Filling a cancelled order would
                be an edge out of a terminal state (invariant 2), and it is
                caught here rather than only by the quantity arithmetic,
                because a cancelled order with quantity remaining would
                otherwise slip through.
            ValueError: on a partial fill of an ``MOK``. Fill-or-kill means
                fillable **in full at entry** or cancelled entirely (rulebook
                2.3, ASEANSC HNX 2.3, high). A partially filled MOK is not a
                rare case to be tolerated; it is a contradiction, and the state
                machine is where it must be impossible.
            ValueError: if ``fill.order_id`` names a different order.
        """
        record = self._require(order_id)
        if record.is_terminal:
            raise ValueError(
                f'order {order_id} is {record.state.value}: a terminal order '
                f'state is never left, so it cannot take a fill'
            )
        if fill.order_id != order_id:
            raise ValueError(
                f'fill {fill.fill_id} belongs to order {fill.order_id}, not '
                f'{order_id}'
            )
        if (record.time_in_force is TimeInForce.FILL_OR_KILL
                and fill.quantity != record.remaining_quantity):
            raise ValueError(
                f'order {order_id} is fill-or-kill (MOK): it fills in full at '
                f'entry or is cancelled entirely, so a fill of '
                f'{fill.quantity} against {record.remaining_quantity} '
                f'remaining is not a state this order can occupy'
            )
        after = record.with_fill(fill, fill.ts)
        self._require_legal(record.state, after.state, order_id)
        self._store(after)
        if after.state is OrderState.FILLED:
            after = self._terminate(after, OrderTransition.FILL, fill.ts)
        self._emit(Event.for_fill(after, fill, self._next_seq()))
        kind = (EventKind.FILLED if after.remaining_quantity <= 0
                else EventKind.PARTIALLY_FILLED)
        return after, kind

    def cancel(
        self,
        order_id: OrderId,
        ts: datetime,
        *,
        phase: Optional[SessionPhase] = None,
    ) -> Union[OrderRecord, Rejected]:
        """Caller cancellation.

        Legal from ``ACCEPTED``, ``RESTING`` and ``PARTIALLY_FILLED``. The
        third matters: a half-filled resting order is exactly the one a caller
        cancels, and the residue's encumbrance is released on the terminal edge
        like any other.

        ``phase`` is an addition to the contract's signature, keyword-only, and
        its two falsy-looking values mean different things:

        * ``None`` -- the caller is not asserting a phase, so the phase lock is
          **not evaluated**. This is not a default answer; it is the absence of
          a question. ``exchange.py`` resolves the phase from
          ``rulebook.at(ts).phase(venue)`` and passes it, and the phase is
          never inferred from the timestamp (a daily bar is stamped midnight,
          which would mark every bar pre-open).
        * ``SessionPhase.UNKNOWN`` -- the question was asked and the data could
          not answer it. That yields ``Rejected`` with
          ``verdict=INDETERMINATE``, which keeps it countable apart from a rule
          saying no.

        Returns ``Rejected(SESSION_SEMANTICS)`` when the order is already
        terminal, or when the phase forbids the instruction -- the auctions are
        locked for their whole duration including LOs carried in from the
        continuous session, the noon break is a hard shutdown, and the HNX
        post-close session is locked. See :func:`amend_cancel_lock` for the
        citations.

        Returns the terminal ``OrderRecord`` on success. ``exchange.py`` builds
        the caller-facing ``Cancelled(order_id, ts, cancelled_quantity,
        filled_quantity)`` from ``remaining_quantity`` and ``filled_quantity``;
        the book returns the record because the record is what it owns.
        """
        record = self._require(order_id)
        refusal = self._refuse_instruction(record, ts, phase, 'cancelled')
        if refusal is not None:
            return refusal
        self._require_legal(record.state, OrderState.CANCELLED, order_id)
        cancelled_quantity = record.remaining_quantity
        record = record.with_state(OrderState.CANCELLED,
                                   OrderTransition.CANCEL, ts)
        self._store(record)
        record = self._terminate(record, OrderTransition.CANCEL, ts)
        self._emit_for(OrderTransition.CANCEL, record, ts,
                       cancelled_quantity=cancelled_quantity,
                       filled_quantity=record.filled_quantity)
        return record

    def amend(
        self,
        order_id: OrderId,
        ts: datetime,
        *,
        quantity: Optional[int] = None,
        limit_price: Optional[Decimal] = None,
        phase: Optional[SessionPhase] = None,
        allow_price_and_quantity: bool = True,
        priority_preserving: bool = True,
        encumbrances: Optional[Sequence[Encumbrance]] = None,
    ) -> Union[Amended, Rejected]:
        """Amend a resting limit order's price and/or quantity.

        The interface contract puts ``amend()`` **out of Tier 1**; what is
        built here is the mechanism and the rules, with every dated choice
        pushed onto the caller as a flag rather than decided in this module.
        A dated lookup here would be a second rulebook.

        The two flags, and the dated rules behind them:

        * ``allow_price_and_quantity`` -- whether one amendment may change both.
          **True to 2025-05-04**: QD 17 Dieu 22.3 reads "sua tang khoi luong
          va/hoac sua gia". **False from 2025-05-05**: "khong duoc sua dong
          thoi thong tin khoi luong va gia tren cung mot lenh dat" (VNX QD
          22/2025 Dieu 21.3 verbatim, retained in QD 22/2026 Dieu 23; same
          rule verbatim in the UPCoM rulebook and, for derivatives, VNX QD 21
          Dieu 24.3). HOSE's own web regulation omits the ban; the rulebook
          adopts the VNX text as higher-ranking and records the discrepancy.
        * ``priority_preserving`` -- whether priority-preserving amendment
          exists at all on this venue at this date. **False before 2022-03-31
          on HOSE**, where amendment *was* cancel-and-replace and priority
          always restarted (QD 352 Dieu 17.1-17.3, verbatim, high), and False
          under the reading that HOSE's legacy engine never implemented QD 17's
          permission (rulebook 2.5 records this as an unresolved CONFLICT for
          2022-03-31 to 2025-05-04, and it changes queue-position modelling for
          three years of the sample).

        Where the rulebook does not settle it, this module says so instead of
        inventing a rule:

        * **Amendment of a non-resting type is refused.** Every amendment row
          in rulebook 2.5 names the LO. There is no window in which an ATO, an
          MOK or an MAK could receive an amendment -- the auction is locked for
          its whole duration and the immediate families are decided at entry --
          so no document had reason to address it. The refusal is an ADOPTED
          reading, recorded in ``detail['adopted']``.
        * **Amending quantity below what is already filled is refused.** No
          Vietnamese document addresses it. ADOPTED, because the alternative
          breaks ``filled + remaining == original``.
        * **A true cancel-and-replace mints a new id** and re-runs admission and
          reservation. That composition is ``exchange.py``'s; the book models
          the in-place form and reports the queue loss as
          ``priority_preserved=False``.

        No event is emitted. ``EventKind`` carries no ``AMENDED`` member --
        an amendment is not a state transition, the state is unchanged -- so
        the amendment is reported only through the returned :class:`Amended`.
        If the session ever needs amendments on the cursor, the member belongs
        in ``types.py``, not in a private enum here.
        """
        if quantity is None and limit_price is None:
            raise ValueError(
                'amend() must change something: pass quantity, limit_price or '
                'both'
            )
        record = self._require(order_id)
        refusal = self._refuse_instruction(record, ts, phase, 'amended')
        if refusal is not None:
            return refusal
        if not record.time_in_force.rests:
            return self._session_refusal(
                record, ts, phase,
                f'{record.order.order_type} is not amendable: every amendment '
                f'rule in the rulebook names the LO, and a '
                f'{record.time_in_force.value} order is decided at entry or '
                f'inside a locked auction',
                adopted=True)
        if (quantity is not None and limit_price is not None
                and not allow_price_and_quantity):
            return self._session_refusal(
                record, ts, phase,
                'one amendment may change price or quantity, never both '
                '(VNX QD 22/2025 Dieu 21.3, effective 2025-05-05)')
        new_quantity = record.original_quantity if quantity is None else quantity
        if new_quantity < record.filled_quantity:
            return self._session_refusal(
                record, ts, phase,
                f'cannot amend quantity to {new_quantity} below the '
                f'{record.filled_quantity} already filled; filled + remaining '
                f'must equal original',
                adopted=True)
        new_price = (record.order.limit_price if limit_price is None
                     else limit_price)
        price_changed = new_price != record.order.limit_price
        preserved = (priority_preserving
                     and amendment_preserves_priority(record.original_quantity,
                                                      new_quantity,
                                                      price_changed))
        amended_record = replace(record,
                                 order=replace(record.order, quantity=new_quantity,
                                               limit_price=new_price),
                                 updated_at=ts)
        # ``exchange.py`` re-runs the funding when it composes admission around
        # this call and hands back the fresh reservation; store it so the
        # record's encumbrance matches the amended order rather than the
        # pre-amendment one. Absent (the book-only path), the reservation is
        # left as it was -- a pure quantity decrease over-reserves, which is the
        # conservative direction.
        if encumbrances is not None:
            amended_record = replace(amended_record,
                                     encumbrances=tuple(encumbrances))
        self._store(amended_record)
        return Amended(order_id=order_id, ts=ts, quantity=new_quantity,
                       limit_price=new_price, priority_preserved=preserved)

    def expire(self, order_id: OrderId, ts: datetime,
               trigger: ExpiryTrigger) -> OrderRecord:
        """Expire one order, naming why.

        Raises:
            ValueError: if ``trigger`` is not in
                ``TERMINAL_TRIGGERS_BY_TIF[record.time_in_force]``. That table
                **is** the per-type terminal edge of locked shape 4, so an
                out-of-table trigger means the caller has invented a rule --
                expiring an ATO at ``SESSION_END`` rather than at its cross, or
                killing a day order with ``IMMEDIATE_REMAINDER``. Either would
                be a rule this simulator enforces and does not document.
            ValueError: on an already-terminal order.
        """
        record = self._require(order_id)
        if record.is_terminal:
            raise ValueError(
                f'order {order_id} is already {record.state.value}: a terminal '
                f'order state is never left'
            )
        allowed = TERMINAL_TRIGGERS_BY_TIF[record.time_in_force]
        if trigger not in allowed:
            raise ValueError(
                f'{trigger.value} cannot end a '
                f'{record.time_in_force.value} order '
                f'({record.order.order_type}); TERMINAL_TRIGGERS_BY_TIF allows '
                f'{sorted(t.value for t in allowed)}'
            )
        self._require_legal(record.state, OrderState.EXPIRED, order_id)
        expired_quantity = record.remaining_quantity
        record = record.with_state(OrderState.EXPIRED, OrderTransition.EXPIRE,
                                   ts, trigger=trigger)
        self._store(record)
        record = self._terminate(record, OrderTransition.EXPIRE, ts)
        self._emit_for(OrderTransition.EXPIRE, record, ts,
                       trigger=trigger.value,
                       expired_quantity=expired_quantity,
                       filled_quantity=record.filled_quantity)
        return record

    def expire_due(self, ts: datetime, venue: Venue, ending: SessionPhase,
                   beginning: SessionPhase) -> Tuple[OrderRecord, ...]:
        """Expire everything this phase change kills on this venue, per type.

        The per-type rule is :func:`expires_at_boundary` and this method adds
        nothing to it: no boundary list is hard-coded here, and the noon break
        consequently expires nothing without this method having to know what a
        noon break is.

        **The immediate families are deliberately not swept.** An MOK or MAK
        still live at a phase boundary is an order ``exchange.py`` accepted and
        never decided, and the rulebook gives neither type a boundary rule to
        invoke -- their triggers are entry-time ones. Sweeping them would mean
        inventing that rule; leaving them means the leak stays visible as a
        live order with a live reservation, which is the failure mode that can
        be found. Deciding an MOK or MAK at entry is the submit path's job.
        """
        expired: List[OrderRecord] = []
        for record in self.live():
            if record.venue != venue:
                continue
            trigger = expires_at_boundary(record.time_in_force, ending,
                                          beginning)
            if trigger is None:
                continue
            expired.append(self.expire(record.order_id, ts, trigger))
        return tuple(expired)

    def set_encumbrances(self, order_id: OrderId,
                         encumbrances: Sequence[Encumbrance]) -> OrderRecord:
        """Replace an order's reservations with the ledger's current view.

        An addition to the contract, and a necessary one: a partial fill
        releases encumbrance **pro rata** at the fill price, and that
        arithmetic is ``ledgers.py``'s -- it needs the fill price and the
        charges actually levied, neither of which the state machine sees.

        Without this the ``OrderRecord``'s ``encumbrances`` tuple would keep
        reporting the amount reserved at accept for the whole life of a
        partially filled order, and ``OrderRecord.encumbered_cash`` -- which
        exists precisely so section 12 invariant 4 can be summed over live
        orders -- would overstate. A record that lies is worse than a record
        that is absent.

        **The rule this method carries is general, and the partial fill is
        only its first instance:** any path that moves the encumbrance ledger
        for an order that is still live owes the record this call, in the same
        operation. Two paths do so today -- ``exchange.py``'s partial fill and
        ``corporate.py``'s ``SCALE`` of a resting order across an ex-date --
        and the second was found by measurement, not by review: a scaled order
        rested for the remainder of its life with a record 2,034,329 dong
        above the ledger and a share leg 1,000 below it. Anything that adds a
        third path and forgets this call re-opens the same hole, and
        :meth:`encumbrance_divergence` is what makes the hole findable.

        Raises:
            ValueError: on a terminal order. :meth:`_terminate` has already
                stamped its reservations released, and letting a later write
                put one back would let a terminal order claim resources it no
                longer holds -- the same leak from the other direction.
        """
        record = self._require(order_id)
        if record.is_terminal:
            raise ValueError(
                f'order {order_id} is {record.state.value} and reserves '
                f'nothing; its encumbrance was released on the terminal edge'
            )
        return self._store(record.with_encumbrances(encumbrances))

    def encumbrance_divergence(
        self,
        reservations: Callable[[OrderId], Sequence[Encumbrance]],
    ) -> Tuple['EncumbranceDivergence', ...]:
        """Every order whose record and the ledger disagree, right now.

        **The meter for the failure this book cannot prevent.** Section 12
        invariant 4 -- the sum of encumbrance over live orders equals the
        ledgers' committed totals -- is checked in ``validation/identities.py``
        as two *totals*, and totals are sampled at the end of a run, when
        nothing is live and both sides are zero. A record that overstated by
        2,034,329 dong for the whole life of a resting order therefore read as
        clean: an ignorance meter that reads zero during known ignorance.

        This is the per-order, any-instant form. It names the order, the
        resource and both numbers, so a divergence is attributable rather than
        merely present, and it sweeps **terminal** orders too: a terminal
        record reserves nothing by construction (:meth:`_terminate`), so a
        reservation the ledger still holds for one is a leak the totals would
        only show while some other order happened to be flat.

        The book does not import ``ledgers.py`` and must not, so the ledger
        arrives as a callable rather than an object -- pass
        ``account.encumbrances.of``. That also lets a caller sweep against the
        derivatives side or against a stub.

        Args:
            reservations: ``order_id -> the reservations the ledger holds``.

        Returns:
            One row per (order, resource) that disagrees, in the order the
            book received the orders. **Empty is the passing answer**, and it
            is the only passing answer.
        """
        rows: List['EncumbranceDivergence'] = []
        for record in self._records.values():
            on_record = {e.resource: e for e in record.encumbrances}
            in_ledger = {e.resource: e for e in reservations(record.order_id)}
            resources = sorted(set(on_record) | set(in_ledger),
                               key=lambda r: r.value)
            for resource in resources:
                mine = on_record.get(resource)
                theirs = in_ledger.get(resource)
                row = EncumbranceDivergence(
                    order_id=record.order_id,
                    state=record.state,
                    resource=resource,
                    record_amount=(Decimal('0') if mine is None
                                   else mine.amount),
                    ledger_amount=(Decimal('0') if theirs is None
                                   else theirs.amount),
                    record_quantity=0 if mine is None else mine.quantity,
                    ledger_quantity=0 if theirs is None else theirs.quantity,
                    ticker=(mine if mine is not None else theirs).ticker,
                )
                if not row.is_clean:
                    rows.append(row)
        return tuple(rows)

    # -- refusals -------------------------------------------------------

    def _refuse_instruction(self, record: OrderRecord, ts: datetime,
                            phase: Optional[SessionPhase],
                            verb: str) -> Optional[Rejected]:
        """The refusal shared by cancel and amend, or ``None`` to proceed."""
        if record.is_terminal:
            return self._session_refusal(
                record, ts, phase,
                f'order is already {record.state.value} and cannot be {verb}')
        if phase is None:
            return None
        reason = amend_cancel_lock(phase)
        if reason is None:
            return None
        return self._session_refusal(record, ts, phase, reason)

    def _session_refusal(self, record: OrderRecord, ts: datetime,
                         phase: Optional[SessionPhase], reason: str,
                         *, adopted: bool = False) -> Rejected:
        """A ``SESSION_SEMANTICS`` refusal, shaped per the contract's table.

        ``binding_constraint`` is ``None`` for ``SESSION_SEMANTICS`` -- the
        rule is not about a number -- and the phase and the reason go in
        ``detail``, which is the convention the six existing rules already
        follow.

        ``SESSION_SEMANTICS`` is the only member of the rejection vocabulary
        that fits an instruction the venue will not accept right now.
        ``AdmissionRule`` has no member for an illegal *amendment*, and
        inventing a private one here would put a rule outside the enum that
        **is** the rejected-order log. Flagged for the orchestrator alongside
        the ``StatefulRule`` merge.
        """
        indeterminate = phase is SessionPhase.UNKNOWN
        return Rejected(
            rule=AdmissionRule.SESSION_SEMANTICS,
            binding_constraint=None,
            ts=ts,
            verdict=(Verdict.INDETERMINATE if indeterminate
                     else Verdict.REJECTED),
            order_id=record.order_id,
            regime_tag=record.regime_tag,
            detail={'phase': phase.value if phase is not None else None,
                    'reason': reason,
                    'state': record.state.value,
                    'adopted': adopted},
        )

    # -- events ---------------------------------------------------------

    def _emit_for(self, transition: OrderTransition, record: OrderRecord,
                  ts: datetime, **detail: object) -> Optional[Event]:
        """Emit the event this transition carries, if it carries one.

        The mapping is ``EVENT_FOR_TRANSITION`` and is read, not restated:
        ``REST`` maps to ``None`` and so emits nothing, which is the single
        place "resting is a state, not news" is enforced.
        """
        kind = EVENT_FOR_TRANSITION[transition]
        if kind is None:
            return None
        return self._emit(Event.for_order(kind, record, ts, self._next_seq(),
                                          **detail))

    def drain_events(self) -> Tuple[Event, ...]:
        """Take the journal and empty it. Destructive, single-consumer.

        The session's cursor works the same way and for the same reason: the
        design puts all reporting on the caller's side, so two consumers
        draining one cursor is a case that does not need to work. A session
        that wired ``on_event`` will normally never call this -- its own cursor
        already has every event -- but a book used on its own still needs to be
        pollable, which is what "every transition emits an event the caller can
        poll" requires.
        """
        drained = tuple(self._events)
        self._events.clear()
        return drained

    def events(self) -> Tuple[Event, ...]:
        """Read the journal without consuming it. For tests and assertions."""
        return tuple(self._events)

    # -- queries --------------------------------------------------------

    def get(self, order_id: OrderId) -> Optional[OrderRecord]:
        """The record, or ``None``. Unlike the transitions, this does not raise:
        asking whether an id is known is a legitimate question."""
        return self._records.get(order_id)

    def orders(self, *, state: Optional[OrderState] = None,
               ticker: Optional[str] = None,
               venue: Optional[Venue] = None) -> Tuple[OrderRecord, ...]:
        """Every order matching the filters, in the order they were received.

        Entry order is the exchange's own time priority (rulebook 2.4: two
        priority levels only, price then time), so it is preserved rather than
        sorted.
        """
        return tuple(
            record for record in self._records.values()
            if (state is None or record.state is state)
            and (ticker is None or record.order.ticker == ticker)
            and (venue is None or record.venue == venue)
        )

    def live(self, *, ticker: Optional[str] = None) -> Tuple[OrderRecord, ...]:
        """Orders in ``ACCEPTED``, ``RESTING`` or ``PARTIALLY_FILLED``.

        What the fill policy is offered, and what section 7.0's three
        net-of-live-orders figures sum over. ``LIVE_STATES`` is the definition
        and ``OrderState.is_live`` reads it.
        """
        return tuple(
            record for record in self._records.values()
            if record.is_live
            and (ticker is None or record.order.ticker == ticker)
        )

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, order_id: object) -> bool:
        return order_id in self._records
