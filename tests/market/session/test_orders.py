"""What the order state machine promises, and the rule behind each promise.

Every test here pins a *rule*, not an implementation detail. The rule is named
in the docstring with its rulebook section where one exists, and marked ADOPTED
where the rulebook is silent -- the point of the codebase is that a reader can
tell those two apart.

The organising claim under test is locked shape 4: **in Vietnam the order type
is the time-in-force**. So the tests are grouped by type, and the forbidden
build -- one ``RESTING`` state with a single "expire at every phase boundary"
rule -- fails at least four of them.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.core.order import OrderType, Side
from plutus.market.protocol import Order, SessionPhase
from plutus.market.session.orders import (OrderBookOfRecord, OrderIdFactory,
                                          amend_cancel_lock,
                                          amendment_preserves_priority,
                                          expires_at_boundary,
                                          is_legal_transition,
                                          is_vietnamese_order_type)
from plutus.market.session.types import (LEGAL_TRANSITIONS, TERMINAL_STATES,
                                         TIME_IN_FORCE, Amended, Encumbrance,
                                         EventKind, ExpiryTrigger, Fill,
                                         FillEvidence, OrderId, OrderState,
                                         OrderTransition, Pool, Rejected,
                                         ResourceKind, TimeInForce, Venue)
from plutus.market.verdicts import AdmissionRule, Verdict

# A day inside the 2021-22 window the corpus covers, so no test accidentally
# depends on a rule regime the rulebook has not sourced.
T0 = datetime(2022, 3, 14, 9, 20)
OPEN_CROSS = datetime(2022, 3, 14, 9, 15)
CLOSE_CROSS = datetime(2022, 3, 14, 14, 45)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

class Recorder:
    """Captures the terminal hook, so "exactly once per order" is countable."""

    def __init__(self):
        self.calls = []

    def __call__(self, record, transition, ts):
        self.calls.append((record.order_id, transition, ts, record))

    def count(self, order_id):
        return sum(1 for call in self.calls if call[0] == order_id)


@pytest.fixture
def hook():
    return Recorder()


@pytest.fixture
def book(hook):
    return OrderBookOfRecord(OrderIdFactory(), on_terminal=hook)


def an_order(order_type=OrderType.LIMIT, quantity=1000, side=Side.BUY,
             price='95.5', ticker='FPT'):
    return Order(ticker=ticker, side=side, quantity=quantity,
                 order_type=order_type,
                 limit_price=None if price is None else Decimal(price))


def a_fill(order_id, quantity, price='95.5', ts=T0, ticker='FPT',
           side=Side.BUY, venue=Venue.HSX, seq=1):
    return Fill(fill_id=f'F-{order_id}-{seq}', order_id=order_id,
                ticker=ticker, venue=venue, side=side, quantity=quantity,
                price=Decimal(price), ts=ts,
                evidence=FillEvidence.TRADED_THROUGH)


def a_cash_encumbrance(order_id, amount='95500', ts=T0):
    return Encumbrance.take(order_id, Pool.SECURITIES, ResourceKind.CASH, ts,
                            amount=Decimal(amount), ticker='FPT')


# --------------------------------------------------------------------------
# The graph is data, and this module reads it
# --------------------------------------------------------------------------

def test_is_legal_transition_reads_the_shared_table():
    """The state graph lives in ``types.LEGAL_TRANSITIONS``, not here.

    Two copies of a state graph is how a simulator ends up enforcing a rule it
    does not document, so the predicate is checked against the table for every
    ordered pair rather than against a restatement of it.
    """
    for frm in OrderState:
        for to in OrderState:
            assert is_legal_transition(frm, to) is (
                to in LEGAL_TRANSITIONS[frm])


def test_no_state_machine_edge_leaves_a_terminal_state():
    """Section 12 invariant 2: a terminal order state is never left.

    This holds structurally because every terminal row of ``LEGAL_TRANSITIONS``
    is empty, which is what makes :func:`is_legal_transition` a sufficient
    single enforcement point.
    """
    for state in TERMINAL_STATES:
        assert LEGAL_TRANSITIONS[state] == frozenset()
        for to in OrderState:
            assert not is_legal_transition(state, to)


def test_resting_is_reachable_only_from_accepted():
    """There is no ``PARTIALLY_FILLED -> RESTING`` edge, and that is deliberate.

    The state axis tracks fill progress; "is on the book" is implied by the
    state being live. Without this reading an MTL that partially sweeps and
    rests its residue would need an edge the shared table does not carry.
    """
    entrants = {frm for frm, tos in LEGAL_TRANSITIONS.items()
                if OrderState.RESTING in tos}
    assert entrants == {OrderState.ACCEPTED}


# --------------------------------------------------------------------------
# Invariant 1 -- filled + remaining == original
# --------------------------------------------------------------------------

def test_filled_plus_remaining_equals_original_after_every_partial_fill(book):
    """Section 12 invariant 1, checked after each of a sequence of fills.

    It is structural -- ``OrderRecord`` derives both quantities from ``fills``
    -- but the sequence is pinned anyway, because the invariant is what the
    encumbrance release is computed against.
    """
    record = book.accept(an_order(quantity=1000), Venue.HSX, T0)
    book.rest(record.order_id, T0)
    for n, quantity in enumerate((300, 200, 500), start=1):
        record, _ = book.apply_fill(record.order_id,
                                    a_fill(record.order_id, quantity, seq=n))
        assert record.filled_quantity + record.remaining_quantity == 1000
    assert record.state is OrderState.FILLED
    assert record.filled_quantity == 1000


def test_a_fill_past_the_original_quantity_is_refused(book):
    """Invariant 1 is enforced, not merely reported."""
    record = book.accept(an_order(quantity=100), Venue.HSX, T0)
    with pytest.raises(ValueError, match='filled \\+ remaining'):
        book.apply_fill(record.order_id, a_fill(record.order_id, 200))


# --------------------------------------------------------------------------
# Invariant 2 -- no order reaches a terminal state twice
# --------------------------------------------------------------------------

def _reach(book, state):
    """Drive one fresh order into the named terminal state."""
    if state is OrderState.FILLED:
        record = book.accept(an_order(quantity=100), Venue.HSX, T0)
        record, _ = book.apply_fill(record.order_id,
                                    a_fill(record.order_id, 100))
        return record
    if state is OrderState.CANCELLED:
        record = book.accept(an_order(), Venue.HSX, T0)
        book.rest(record.order_id, T0)
        return book.cancel(record.order_id, T0)
    if state is OrderState.EXPIRED:
        record = book.accept(an_order(), Venue.HSX, T0)
        book.rest(record.order_id, T0)
        return book.expire(record.order_id, T0, ExpiryTrigger.SESSION_END)
    if state is OrderState.REJECTED:
        return book.reject(
            an_order(), Venue.HSX,
            Rejected(rule=AdmissionRule.TICK_GRID,
                     binding_constraint=Decimal('0.05'), ts=T0))
    raise AssertionError(state)


@pytest.mark.parametrize('state', sorted(TERMINAL_STATES, key=lambda s: s.value))
def test_no_order_can_reach_a_terminal_state_twice(book, hook, state):
    """Section 12 invariant 2, exercised through the public transitions.

    Every way of moving an order -- rest, fill, cancel, expire, amend, convert
    -- is attempted against an order already in each of the four terminal
    states. A transition that succeeded would mean the encumbrance-release hook
    could fire twice, releasing resources the order never held a second time,
    which is the leak class section 7.0 exists to close.
    """
    record = _reach(book, state)
    assert record.state is state
    assert hook.count(record.order_id) == 1

    with pytest.raises(ValueError):
        book.rest(record.order_id, T0)
    with pytest.raises(ValueError):
        book.apply_fill(record.order_id, a_fill(record.order_id, 10, seq=9))
    with pytest.raises(ValueError):
        book.expire(record.order_id, T0, ExpiryTrigger.SESSION_END)
    with pytest.raises(ValueError):
        book.convert_residue(record.order_id, T0, Decimal('95.4'))

    refused = book.cancel(record.order_id, T0)
    assert isinstance(refused, Rejected)
    assert refused.rule is AdmissionRule.SESSION_SEMANTICS

    amended = book.amend(record.order_id, T0, quantity=50)
    assert isinstance(amended, Rejected)

    # The hook still fired exactly once, and the state never moved.
    assert hook.count(record.order_id) == 1
    assert book.get(record.order_id).state is state


def test_on_terminal_fires_exactly_once_on_all_four_terminal_edges(hook):
    """Locked shape 4's shared hook: released on **every** terminal transition.

    Wiring the release at construction rather than at each call site is what
    makes a terminal edge that forgets to release impossible by construction.
    Four orders, four different terminal edges, four hook calls.
    """
    book = OrderBookOfRecord(OrderIdFactory(), on_terminal=hook)
    reached = [_reach(book, state)
               for state in (OrderState.FILLED, OrderState.CANCELLED,
                             OrderState.EXPIRED, OrderState.REJECTED)]
    assert len(hook.calls) == 4
    assert {call[1] for call in hook.calls} == {
        OrderTransition.FILL, OrderTransition.CANCEL,
        OrderTransition.EXPIRE, OrderTransition.REJECT}
    for record in reached:
        assert hook.count(record.order_id) == 1


def test_the_hook_sees_the_reservation_and_the_record_then_stops_claiming_it(book, hook):
    """The release hook is handed the encumbrance it has to release.

    Order matters: ``on_terminal`` sees the record with its reservations still
    on it -- that is what the ledger needs the amounts from -- and only after it
    returns does the record stop claiming them. A record that kept claiming a
    released reservation would inflate the net-of-live-orders figures in
    section 7.0.
    """
    order_id = OrderIdFactory().next()
    record = book.accept(an_order(), Venue.HSX, T0,
                         encumbrances=[a_cash_encumbrance(order_id)],
                         order_id=order_id)
    book.rest(order_id, T0)
    book.cancel(order_id, T0)

    seen = hook.calls[-1][3]
    assert seen.encumbered_cash == Decimal('95500')
    assert book.get(order_id).encumbered_cash == Decimal('0')
    assert book.get(order_id).encumbrances[0].is_released


# --------------------------------------------------------------------------
# LO -- the day order
# --------------------------------------------------------------------------

def test_a_limit_order_rests_until_the_end_of_the_last_matching_phase(book):
    """Rulebook 2.3: an LO is a day order and dies at the end of the last
    matching phase of its day (QD 352 Dieu 14.1(c), 17.2, high).

    Not at the first boundary it meets: it crosses into the closing auction and
    participates in the cross ("an unfilled continuous-session LO is carried
    into the following auction").
    """
    record = book.accept(an_order(), Venue.HSX, T0)
    book.rest(record.order_id, T0)

    survivors = book.expire_due(T0, Venue.HSX, SessionPhase.CONTINUOUS,
                                SessionPhase.CLOSING_AUCTION)
    assert survivors == ()
    assert book.get(record.order_id).state is OrderState.RESTING

    dead = book.expire_due(CLOSE_CROSS, Venue.HSX,
                           SessionPhase.CLOSING_AUCTION,
                           SessionPhase.POST_CLOSE)
    assert [r.order_id for r in dead] == [record.order_id]
    assert dead[0].state is OrderState.EXPIRED
    assert dead[0].expiry_trigger is ExpiryTrigger.SESSION_END


def test_a_day_order_on_hnx_dies_at_the_atc_not_in_the_plo_session():
    """HNX's 14:45-15:00 post-close matches PLO orders only.

    A PLO is a limit order without a price that executes at the day's last
    round-lot matched price (rulebook 2.3, high), so no LO can match in that
    session. Treating the post-close as a matching phase would carry an HNX day
    order past the point it actually dies.
    """
    assert expires_at_boundary(TimeInForce.DAY, SessionPhase.CLOSING_AUCTION,
                               SessionPhase.POST_CLOSE_PLO) is (
        ExpiryTrigger.SESSION_END)


def test_the_noon_break_expires_nothing(book):
    """Rulebook 2.1: 11:30-13:00 is a hard shutdown for entry, amendment and
    cancellation (QD 352 Dieu 21, high) -- but the **book survives it**.

    This is the forbidden build's headline failure: a simulator that expires at
    every phase boundary destroys the afternoon book. It is also why
    ``ExpiryTrigger`` has no ``NOON_BREAK`` member; the absence is the
    enforcement.
    """
    for tif in TimeInForce:
        assert expires_at_boundary(tif, SessionPhase.CONTINUOUS,
                                   SessionPhase.NOON_BREAK) is None
        assert expires_at_boundary(tif, SessionPhase.NOON_BREAK,
                                   SessionPhase.CONTINUOUS) is None

    record = book.accept(an_order(), Venue.HSX, T0)
    book.rest(record.order_id, T0)
    assert book.expire_due(T0, Venue.HSX, SessionPhase.CONTINUOUS,
                           SessionPhase.NOON_BREAK) == ()
    assert book.expire_due(T0, Venue.HSX, SessionPhase.NOON_BREAK,
                           SessionPhase.CONTINUOUS) == ()
    assert book.get(record.order_id).state is OrderState.RESTING


def test_an_unknown_phase_expires_nothing():
    """A data gap must not destroy the book.

    Note the direction differs from admission, deliberately: at admission
    absent data yields ``INDETERMINATE`` and keeps the order *out*, because
    absence of evidence is not evidence of admissibility. Here the conservative
    answer is the opposite one -- an order left alive can be expired at the
    next known boundary, an order wrongly expired cannot be recovered.
    """
    assert expires_at_boundary(TimeInForce.DAY, SessionPhase.CONTINUOUS,
                               SessionPhase.UNKNOWN) is None
    assert expires_at_boundary(TimeInForce.AUCTION_ONLY,
                               SessionPhase.UNKNOWN,
                               SessionPhase.CONTINUOUS) is None


# --------------------------------------------------------------------------
# ATO / ATC -- auction-only
# --------------------------------------------------------------------------

def test_an_unmatched_ato_expires_at_the_opening_cross(book, hook):
    """Rulebook 2.3: ATO/ATC are enterable only inside their own auction window
    and the unfilled remainder is auto-cancelled **at the cross** -- they never
    rest and never carry (QD 352 Dieu 14.3(b), 14.4(b), high).
    """
    record = book.accept(an_order(OrderType.AT_THE_OPENING, price=None),
                         Venue.HSX, datetime(2022, 3, 14, 9, 5))
    assert record.time_in_force is TimeInForce.AUCTION_ONLY

    dead = book.expire_due(OPEN_CROSS, Venue.HSX,
                           SessionPhase.OPENING_AUCTION,
                           SessionPhase.CONTINUOUS)
    assert [r.order_id for r in dead] == [record.order_id]
    assert dead[0].state is OrderState.EXPIRED
    assert dead[0].expiry_trigger is ExpiryTrigger.AUCTION_CROSS
    assert hook.count(record.order_id) == 1


def test_an_unmatched_atc_expires_at_the_closing_cross(book):
    """The same rule for the closing call (QD 352 Dieu 14.4(b))."""
    record = book.accept(an_order(OrderType.AT_THE_CLOSE, price=None),
                         Venue.HSX, datetime(2022, 3, 14, 14, 35))
    dead = book.expire_due(CLOSE_CROSS, Venue.HSX,
                           SessionPhase.CLOSING_AUCTION,
                           SessionPhase.POST_CLOSE)
    assert dead[0].expiry_trigger is ExpiryTrigger.AUCTION_CROSS


def test_an_auction_order_never_rests(book):
    """"Never rest, never carry" is enforced, not documented.

    An ATO on the book would be an order the exchange auto-cancelled at the
    cross still sitting there -- and it would then be swept by the day-order
    session-end rule, which is not the rule that killed it.
    """
    record = book.accept(an_order(OrderType.AT_THE_OPENING, price=None),
                         Venue.HSX, T0)
    with pytest.raises(ValueError, match='never rests'):
        book.rest(record.order_id, T0)


def test_an_auction_order_cannot_be_expired_at_session_end(book):
    """``TERMINAL_TRIGGERS_BY_TIF`` is the per-type terminal edge.

    ``AUCTION_ONLY`` maps to ``{AUCTION_CROSS}`` alone, so expiring an ATO at
    ``SESSION_END`` would be this module inventing a rule -- and would
    misattribute the cause in the event log, which is what the trigger exists
    to record.
    """
    record = book.accept(an_order(OrderType.AT_THE_CLOSE, price=None),
                         Venue.HSX, T0)
    with pytest.raises(ValueError, match='session_end cannot end'):
        book.expire(record.order_id, T0, ExpiryTrigger.SESSION_END)


def test_a_partially_filled_ato_expires_its_remainder_at_the_cross(book):
    """The auction cross fills what it can and cancels the rest.

    ``PARTIALLY_FILLED -> EXPIRED`` is a legal edge precisely for this case.
    """
    record = book.accept(an_order(OrderType.AT_THE_OPENING, quantity=1000,
                                  price=None), Venue.HSX, T0)
    record, kind = book.apply_fill(record.order_id,
                                   a_fill(record.order_id, 400))
    assert kind is EventKind.PARTIALLY_FILLED
    dead = book.expire(record.order_id, OPEN_CROSS,
                       ExpiryTrigger.AUCTION_CROSS)
    assert dead.state is OrderState.EXPIRED
    assert dead.filled_quantity == 400
    assert dead.remaining_quantity == 600


# --------------------------------------------------------------------------
# MOK -- fill or kill
# --------------------------------------------------------------------------

def test_an_mok_never_rests(book):
    """Rulebook 2.3: MOK is fill-or-kill -- cancelled entirely if not fillable
    in full at entry -- and never rests (ASEANSC HNX 2.3, MBS VN30F 3.2, high).

    The forbidden build routes every accepted order through ``RESTING``, which
    would put on the book an order that by rule was never on it.
    """
    record = book.accept(an_order(OrderType.MARKET_FILL_OR_KILL, price=None),
                         Venue.HNX, T0)
    assert record.time_in_force is TimeInForce.FILL_OR_KILL
    assert TimeInForce.FILL_OR_KILL.rests is False
    with pytest.raises(ValueError, match='never rests'):
        book.rest(record.order_id, T0)


def test_an_mok_cannot_be_partially_filled(book):
    """Fill-or-kill means in full or not at all.

    A partially filled MOK is not a rare case to tolerate; it is a
    contradiction, and the state machine is where it has to be impossible --
    otherwise the residue sits live, holding encumbrance, with no rule that can
    ever kill it.
    """
    record = book.accept(an_order(OrderType.MARKET_FILL_OR_KILL,
                                  quantity=1000, price=None), Venue.HNX, T0)
    with pytest.raises(ValueError, match='fill-or-kill'):
        book.apply_fill(record.order_id, a_fill(record.order_id, 400))

    filled, kind = book.apply_fill(record.order_id,
                                   a_fill(record.order_id, 1000))
    assert kind is EventKind.FILLED
    assert filled.state is OrderState.FILLED


def test_an_unfillable_mok_dies_naming_the_rule(book):
    """The trigger records *which* rule killed it, not merely that it died."""
    record = book.accept(an_order(OrderType.MARKET_FILL_OR_KILL, price=None),
                         Venue.HNX, T0)
    dead = book.expire(record.order_id, T0,
                       ExpiryTrigger.NOT_FILLABLE_IN_FULL)
    assert dead.expiry_trigger is ExpiryTrigger.NOT_FILLABLE_IN_FULL

    other = book.accept(an_order(OrderType.MARKET_FILL_OR_KILL, price=None),
                        Venue.HNX, T0)
    # Rulebook 2.3: a market order entered with no opposite limit order is
    # cancelled at entry, all venues, whole window.
    dead = book.expire(other.order_id, T0, ExpiryTrigger.NO_OPPOSITE_ORDER)
    assert dead.expiry_trigger is ExpiryTrigger.NO_OPPOSITE_ORDER


# --------------------------------------------------------------------------
# MAK -- immediate or cancel
# --------------------------------------------------------------------------

def test_an_mak_keeps_what_filled_and_kills_the_remainder(book):
    """Rulebook 2.3: MAK is immediate-or-cancel and never rests.

    Unlike MOK it *is* partially fillable -- that is the whole difference
    between the two -- so the residue must die by its own trigger rather than
    by a session-end sweep it is not entitled to.
    """
    record = book.accept(an_order(OrderType.MARKET_IMMEDIATE_OR_CANCEL,
                                  quantity=1000, price=None), Venue.HNX, T0)
    record, kind = book.apply_fill(record.order_id,
                                   a_fill(record.order_id, 400))
    assert kind is EventKind.PARTIALLY_FILLED
    with pytest.raises(ValueError, match='never rests'):
        book.rest(record.order_id, T0)

    dead = book.expire(record.order_id, T0, ExpiryTrigger.IMMEDIATE_REMAINDER)
    assert dead.state is OrderState.EXPIRED
    assert dead.filled_quantity == 400
    assert dead.remaining_quantity == 600


def test_the_immediate_families_are_not_swept_by_a_phase_boundary(book):
    """The rulebook gives MOK and MAK **no** boundary rule, so neither does this.

    Their triggers are entry-time ones. An MOK or MAK still live at a boundary
    is an order the submit path accepted and never decided; sweeping it here
    would invent a rule and hide the bug, so it is left visibly live instead.
    """
    for order_type in (OrderType.MARKET_FILL_OR_KILL,
                       OrderType.MARKET_IMMEDIATE_OR_CANCEL):
        tif = TIME_IN_FORCE[order_type]
        assert expires_at_boundary(tif, SessionPhase.CONTINUOUS,
                                   SessionPhase.POST_CLOSE) is None

    record = book.accept(an_order(OrderType.MARKET_IMMEDIATE_OR_CANCEL,
                                  price=None), Venue.HNX, T0)
    assert book.expire_due(T0, Venue.HNX, SessionPhase.CONTINUOUS,
                           SessionPhase.POST_CLOSE) == ()
    assert book.get(record.order_id).is_live


# --------------------------------------------------------------------------
# MTL -- the one market type that can rest
# --------------------------------------------------------------------------

def test_an_mtl_residue_becomes_a_resting_limit_order(book):
    """Rulebook 2.3: MTL sweeps from the best opposite price and the residue
    **converts to an LO** (VNX QD 22/2025 Dieu 17.2(b) verbatim, high).

    That is why ``IMMEDIATE_THEN_DAY`` exists as a distinct time-in-force:
    neither ``DAY`` nor ``IMMEDIATE_OR_CANCEL`` can express an immediate order
    that becomes a day order.

    The record keeps ``time_in_force = IMMEDIATE_THEN_DAY`` while its
    ``order_type`` becomes ``LIMIT`` -- the exchange's book now holds a limit
    order, but the provenance of the resting price is only explicable if the
    record still says it arrived as a market order.
    """
    record = book.accept(an_order(OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
                                  quantity=1000, price=None), Venue.HNX, T0)
    assert record.time_in_force is TimeInForce.IMMEDIATE_THEN_DAY
    assert TimeInForce.IMMEDIATE_THEN_DAY.rests is True

    record, _ = book.apply_fill(record.order_id,
                                a_fill(record.order_id, 400, price='95.5',
                                       venue=Venue.HNX))
    residue = book.convert_residue(record.order_id, T0, Decimal('95.6'))

    assert residue.order.order_type is OrderType.LIMIT
    assert residue.order.limit_price == Decimal('95.6')
    assert residue.time_in_force is TimeInForce.IMMEDIATE_THEN_DAY
    assert residue.remaining_quantity == 600
    # A partially swept MTL stays PARTIALLY_FILLED: being live is what puts an
    # order on the book, and there is no PARTIALLY_FILLED -> RESTING edge.
    assert residue.state is OrderState.PARTIALLY_FILLED
    assert residue.is_live


def test_an_unswept_mtl_residue_rests(book):
    """With nothing filled, the conversion moves ACCEPTED -> RESTING."""
    record = book.accept(an_order(OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
                                  price=None), Venue.HNX, T0)
    residue = book.convert_residue(record.order_id, T0, Decimal('95.6'))
    assert residue.state is OrderState.RESTING


def test_an_mtl_residue_dies_at_session_end_not_at_an_auction_cross(book):
    """``TERMINAL_TRIGGERS_BY_TIF[IMMEDIATE_THEN_DAY]`` carries ``SESSION_END``
    and not ``AUCTION_CROSS``: once the residue is a limit order it behaves as
    one, and a limit order is carried into the following auction rather than
    killed by it.
    """
    record = book.accept(an_order(OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
                                  price=None), Venue.HNX, T0)
    book.convert_residue(record.order_id, T0, Decimal('95.6'))
    assert book.expire_due(T0, Venue.HNX, SessionPhase.CONTINUOUS,
                           SessionPhase.CLOSING_AUCTION) == ()
    dead = book.expire_due(CLOSE_CROSS, Venue.HNX,
                           SessionPhase.CLOSING_AUCTION,
                           SessionPhase.POST_CLOSE_PLO)
    assert dead[0].expiry_trigger is ExpiryTrigger.SESSION_END


def test_only_an_mtl_converts_a_residue(book):
    """A day order has no residue to convert and an auction order never rests."""
    record = book.accept(an_order(), Venue.HSX, T0)
    with pytest.raises(ValueError, match='IMMEDIATE_THEN_DAY'):
        book.convert_residue(record.order_id, T0, Decimal('95.6'))


# --------------------------------------------------------------------------
# MKT -- the type that matches nothing in Vietnam
# --------------------------------------------------------------------------

def test_mkt_matches_no_vietnamese_order_type():
    """Rulebook 2.2, a graded-high negative finding across all four rulebooks:
    "No such order type exists in Vietnam at any date."

    ``core/order.py:56`` carries ``MKT`` as a synthetic "buy at ceiling / sell
    at floor" convenience. It is named explicitly rather than left to fall
    through a default branch, because a default branch is exactly how a
    synthetic type acquires real semantics.
    """
    assert is_vietnamese_order_type(OrderType.MARKET) is False
    for order_type in OrderType:
        if order_type is not OrderType.MARKET:
            assert is_vietnamese_order_type(order_type) is True


def test_accepting_an_mkt_raises_rather_than_rejecting(book):
    """An MKT on the book of record is a **caller bug, not a market event**.

    ``RuleSet.legal_order_types()`` returns no venue-date pair containing it,
    so an MKT reaching ``accept()`` means that check was skipped. Logging it as
    a rejection would put a phantom row in the rejection log the paper's rates
    are counted from. Same reasoning, and the same loud refusal, as
    ``types.signed_quantity`` on ``Side.CROSS``.
    """
    with pytest.raises(ValueError, match='matches no Vietnamese order type'):
        book.accept(an_order(OrderType.MARKET, price=None), Venue.HSX, T0)


def test_rejecting_an_mkt_is_allowed_so_the_log_row_survives(book):
    """The legality check that catches an MKT must still be able to log it.

    ``reject()`` deliberately does not raise: that is where the market's own
    "this venue does not accept this type" answer is recorded.
    """
    record = book.reject(
        an_order(OrderType.MARKET, price=None), Venue.HSX,
        Rejected(rule=AdmissionRule.SESSION_SEMANTICS,
                 binding_constraint=None, ts=T0,
                 detail={'reason': 'MKT is legal at no venue on any date'}))
    assert record.state is OrderState.REJECTED
    assert record.order_id in book


# --------------------------------------------------------------------------
# Cancellation
# --------------------------------------------------------------------------

def test_a_partially_filled_resting_order_can_be_cancelled(book, hook):
    """A half-filled resting order is exactly the one a caller cancels.

    ``core/order.py:291`` already models ``is_partial_filled_and_cancelled``,
    and the residue's encumbrance must be released on that edge like any other
    -- otherwise the leak is proportional to how often a strategy cancels,
    which is often.
    """
    order_id = OrderId('PLU-CANCEL-1')
    record = book.accept(an_order(quantity=1000), Venue.HSX, T0,
                         order_id=order_id,
                         encumbrances=[a_cash_encumbrance(order_id)])
    book.rest(order_id, T0)
    book.apply_fill(order_id, a_fill(order_id, 400))

    cancelled = book.cancel(order_id, T0)
    assert cancelled.state is OrderState.CANCELLED
    assert cancelled.filled_quantity == 400
    assert cancelled.remaining_quantity == 600
    assert hook.count(order_id) == 1
    assert cancelled.encumbered_cash == Decimal('0')


def test_cancellation_is_legal_from_every_live_state(book):
    """ACCEPTED, RESTING and PARTIALLY_FILLED all admit a cancellation."""
    for state in (OrderState.ACCEPTED, OrderState.RESTING,
                  OrderState.PARTIALLY_FILLED):
        assert OrderState.CANCELLED in LEGAL_TRANSITIONS[state]


def test_a_call_auction_refuses_cancellation_for_its_whole_duration(book):
    """Rulebook 2.5: no amendment and no cancellation of LO, ATO or ATC while a
    call auction is running -- for the whole auction, not merely at the cross
    (QD 352 Dieu 17.1; VNX QD 17 Dieu 22; QD 22/2025 Dieu 21, high).

    The lock covers LOs **carried in from the continuous session**, so from
    14:30 a resting LO can be neither amended nor cancelled. Several write-ups
    present this as a KRX novelty; it is unchanged across the whole window.
    """
    record = book.accept(an_order(), Venue.HSX, T0)
    book.rest(record.order_id, T0)
    for phase in (SessionPhase.OPENING_AUCTION, SessionPhase.CLOSING_AUCTION):
        refused = book.cancel(record.order_id, T0, phase=phase)
        assert isinstance(refused, Rejected)
        assert refused.rule is AdmissionRule.SESSION_SEMANTICS
        assert refused.verdict is Verdict.REJECTED
        assert refused.binding_constraint is None
        assert refused.detail['phase'] == phase.value
    assert book.get(record.order_id).state is OrderState.RESTING


def test_the_noon_break_refuses_cancellation_while_the_book_survives(book):
    """Rulebook 2.1: 11:30-13:00 admits no entry, amend or cancel.

    The break stops **instructions**, not the book. Both halves are pinned in
    one test because a build that gets one right and the other wrong is the
    common failure -- either the afternoon book is destroyed, or a cancellation
    is accepted during a shutdown.
    """
    record = book.accept(an_order(), Venue.HSX, T0)
    book.rest(record.order_id, T0)
    refused = book.cancel(record.order_id, T0, phase=SessionPhase.NOON_BREAK)
    assert isinstance(refused, Rejected)
    assert book.get(record.order_id).state is OrderState.RESTING


def test_the_hnx_post_close_session_is_locked(book):
    """Rulebook 2.5: no amend, no cancel in the after-hours session (VNX QD
    22/2025 Dieu 21.5; ASEANSC HNX 3, high)."""
    assert amend_cancel_lock(SessionPhase.POST_CLOSE_PLO) is not None
    assert amend_cancel_lock(SessionPhase.CONTINUOUS) is None


def test_pre_open_and_post_close_locks_are_declared_adopted():
    """No Vietnamese document in the rulebook settles a cancellation submitted
    outside trading hours -- the question is a broker-channel one.

    Refusing it is an adopted simulator behaviour and the reason string says so,
    which is the difference between a declared omission and a silent one.
    """
    for phase in (SessionPhase.PRE_OPEN, SessionPhase.POST_CLOSE):
        assert 'ADOPTED' in amend_cancel_lock(phase)


def test_an_unasserted_phase_is_not_the_same_as_an_unknown_one(book):
    """``phase=None`` is the absence of a question; ``UNKNOWN`` is an unanswerable
    one.

    The first means the caller has not resolved the phase and the lock is not
    evaluated. The second means the data could not say, which yields
    ``verdict=INDETERMINATE`` so a data gap stays countable apart from a rule
    saying no -- the same distinction ``Rejected.verdict`` exists for.
    """
    first = book.accept(an_order(), Venue.HSX, T0)
    book.rest(first.order_id, T0)
    assert book.cancel(first.order_id, T0).state is OrderState.CANCELLED

    second = book.accept(an_order(), Venue.HSX, T0)
    book.rest(second.order_id, T0)
    refused = book.cancel(second.order_id, T0, phase=SessionPhase.UNKNOWN)
    assert isinstance(refused, Rejected)
    assert refused.verdict is Verdict.INDETERMINATE
    assert refused.is_indeterminate


def test_cancelling_an_unknown_id_raises(book):
    """An id the exchange never issued is a caller bug, not a market answer.

    Returning ``Rejected`` would put a phantom row in the rejection log that
    the paper's rejection rates then count.
    """
    with pytest.raises(KeyError):
        book.cancel(OrderId('PLU-99999999'), T0)


# --------------------------------------------------------------------------
# Amendment
# --------------------------------------------------------------------------

def test_priority_survives_only_a_pure_quantity_decrease():
    """Rulebook 2.5, VNX QD 17 Dieu 22.3 read verbatim (from 2022-03-31):
    priority is preserved only if quantity is reduced, and restarts on a
    quantity increase and/or any price change.

    Vietnam has exactly two priority levels, price then time, with no size or
    member-class priority (rulebook 2.4), so there is no third quantity for
    this rule to turn on.
    """
    assert amendment_preserves_priority(1000, 600, price_changed=False) is True
    assert amendment_preserves_priority(1000, 1400, price_changed=False) is False
    assert amendment_preserves_priority(1000, 600, price_changed=True) is False
    assert amendment_preserves_priority(1000, 1000, price_changed=False) is False


def test_amending_quantity_down_keeps_priority(book):
    record = book.accept(an_order(quantity=1000), Venue.HSX, T0)
    book.rest(record.order_id, T0)
    result = book.amend(record.order_id, T0, quantity=600,
                        phase=SessionPhase.CONTINUOUS)
    assert isinstance(result, Amended)
    assert result.priority_preserved is True
    assert book.get(record.order_id).original_quantity == 600


def test_amending_the_price_restarts_priority(book):
    record = book.accept(an_order(quantity=1000), Venue.HSX, T0)
    book.rest(record.order_id, T0)
    result = book.amend(record.order_id, T0, limit_price=Decimal('96.0'),
                        phase=SessionPhase.CONTINUOUS)
    assert result.priority_preserved is False
    assert book.get(record.order_id).order.limit_price == Decimal('96.0')


def test_a_venue_date_without_priority_preserving_amendment(book):
    """Rulebook 2.5: before 2022-03-31 on HOSE, amendment **was**
    cancel-the-order-and-enter-a-new-one and time priority always restarted
    (QD 352 Dieu 17.1-17.3, verbatim, high).

    The rulebook also records an unresolved CONFLICT for HOSE 2022-03-31 to
    2025-05-04 -- QD 17 permits priority-preserving amendment while Vietcap's
    handbook records the legacy engine as not implementing it -- and that
    choice changes queue-position modelling for three years of the sample. Both
    are expressed through this flag rather than dated inside the state machine.
    """
    record = book.accept(an_order(quantity=1000), Venue.HSX, T0)
    book.rest(record.order_id, T0)
    result = book.amend(record.order_id, T0, quantity=600,
                        phase=SessionPhase.CONTINUOUS,
                        priority_preserving=False)
    assert result.priority_preserved is False


def test_price_and_quantity_in_one_amendment_is_dated(book):
    """Rulebook 2.5: "khong duoc sua dong thoi thong tin khoi luong va gia tren
    cung mot lenh dat" -- one amendment may change price **or** quantity, never
    both, from 2025-05-05 (VNX QD 22/2025 Dieu 21.3 verbatim, high).

    Before that, QD 17 Dieu 22.3's "va/hoac" positively permits both. So this
    is a dated rule, and the state machine takes it as a flag rather than
    keeping a second rulebook.
    """
    record = book.accept(an_order(quantity=1000), Venue.HSX, T0)
    book.rest(record.order_id, T0)

    allowed = book.amend(record.order_id, T0, quantity=600,
                         limit_price=Decimal('96.0'),
                         phase=SessionPhase.CONTINUOUS,
                         allow_price_and_quantity=True)
    assert isinstance(allowed, Amended)

    refused = book.amend(record.order_id, T0, quantity=500,
                         limit_price=Decimal('96.5'),
                         phase=SessionPhase.CONTINUOUS,
                         allow_price_and_quantity=False)
    assert isinstance(refused, Rejected)
    assert 'never both' in refused.detail['reason']


def test_amending_a_non_resting_type_is_refused_and_declared_adopted(book):
    """Every amendment row in rulebook 2.5 names the LO.

    There is no window in which an ATO, MOK or MAK could receive an amendment
    -- the auction is locked for its whole duration and the immediate families
    are decided at entry -- so no document had reason to address it. The
    refusal is ADOPTED and says so in the rejection detail rather than being
    presented as a market rule.
    """
    record = book.accept(an_order(OrderType.AT_THE_CLOSE, price=None),
                         Venue.HSX, T0)
    refused = book.amend(record.order_id, T0, quantity=500,
                         phase=SessionPhase.CONTINUOUS)
    assert isinstance(refused, Rejected)
    assert refused.detail['adopted'] is True


def test_amending_below_the_filled_quantity_is_refused(book):
    """ADOPTED: no Vietnamese document addresses it, and the alternative breaks
    ``filled + remaining == original``."""
    record = book.accept(an_order(quantity=1000), Venue.HSX, T0)
    book.rest(record.order_id, T0)
    book.apply_fill(record.order_id, a_fill(record.order_id, 700))
    refused = book.amend(record.order_id, T0, quantity=500,
                         phase=SessionPhase.CONTINUOUS)
    assert isinstance(refused, Rejected)
    assert refused.detail['adopted'] is True


def test_an_amendment_that_changes_nothing_raises(book):
    record = book.accept(an_order(), Venue.HSX, T0)
    with pytest.raises(ValueError, match='must change something'):
        book.amend(record.order_id, T0)


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

def test_every_transition_but_rest_emits_a_pollable_event(book):
    """``EVENT_FOR_TRANSITION`` is read, not restated.

    ``REST`` is the only silent transition: resting is a state, not news, and
    the caller reads it from ``orders()``. Everything else lands on the cursor,
    because a transition the caller cannot poll is a transition that did not
    happen as far as the strategy is concerned.
    """
    record = book.accept(an_order(quantity=1000), Venue.HSX, T0)
    book.rest(record.order_id, T0)
    book.apply_fill(record.order_id, a_fill(record.order_id, 400))
    book.cancel(record.order_id, T0)

    kinds = [event.kind for event in book.events()]
    assert kinds == [EventKind.ACCEPTED, EventKind.PARTIALLY_FILLED,
                     EventKind.CANCELLED]
    assert all(event.order_id == record.order_id for event in book.events())
    assert [event.seq for event in book.events()] == [1, 2, 3]


def test_a_fill_that_exhausts_the_remainder_is_a_filled_event(book):
    """The event kind is computed from what remains after the fill is applied,
    never passed in: a fill that exhausts the remainder is a ``FILLED``
    whatever its size, and letting the caller name it is how the two drift.
    """
    record = book.accept(an_order(quantity=1000), Venue.HSX, T0)
    book.rest(record.order_id, T0)
    _, first = book.apply_fill(record.order_id,
                               a_fill(record.order_id, 400, seq=1))
    _, second = book.apply_fill(record.order_id,
                                a_fill(record.order_id, 600, seq=2))
    assert first is EventKind.PARTIALLY_FILLED
    assert second is EventKind.FILLED


def test_the_event_cursor_is_destructive(book):
    """One cursor, single consumer: ``drain_events`` empties what it returns."""
    record = book.accept(an_order(), Venue.HSX, T0)
    assert len(book.drain_events()) == 1
    assert book.drain_events() == ()
    book.cancel(record.order_id, T0)
    assert [event.kind for event in book.drain_events()] == [
        EventKind.CANCELLED]


def test_an_external_sink_and_sequence_can_be_wired(hook):
    """``exchange.py`` owns one session-monotonic cursor covering more event
    families than orders, so the book must be able to defer both the sink and
    the ordinal to it rather than numbering events privately.
    """
    sunk = []
    counter = iter(range(100, 200))
    book = OrderBookOfRecord(OrderIdFactory(), on_terminal=hook,
                             on_event=sunk.append,
                             next_seq=lambda: next(counter))
    record = book.accept(an_order(), Venue.HSX, T0)
    book.cancel(record.order_id, T0)
    assert [event.seq for event in sunk] == [100, 101]


def test_a_rejection_is_on_the_cursor_and_carries_the_rule(book):
    """A rejected order still gets an id, so the rejection log joins to the
    submission, and the event carries the rule rather than a string --
    ``AdmissionRule`` **is** the rejected-order log.
    """
    record = book.reject(
        an_order(), Venue.HSX,
        Rejected(rule=AdmissionRule.TICK_GRID,
                 binding_constraint=Decimal('0.05'), ts=T0))
    assert record.order_id is not None
    assert record.rejection.order_id == record.order_id
    event = book.events()[-1]
    assert event.kind is EventKind.REJECTED
    assert event.rule is AdmissionRule.TICK_GRID


# --------------------------------------------------------------------------
# Ids and queries
# --------------------------------------------------------------------------

def test_ids_are_unique_strings_that_sort_in_issue_order():
    """A broker id is a string, and zero padding makes a text-sorted log read in
    the order the exchange saw the orders -- which is one of Vietnam's only two
    priority levels (rulebook 2.4: price, then time).
    """
    ids = OrderIdFactory()
    issued = [ids.next() for _ in range(12)]
    assert len(set(issued)) == 12
    assert issued == sorted(issued)
    assert all(isinstance(order_id, str) for order_id in issued)
    assert ids.issued == 12


def test_an_id_is_never_reused(book):
    order_id = OrderId('PLU-00000001')
    book.accept(an_order(), Venue.HSX, T0, order_id=order_id)
    with pytest.raises(ValueError, match='already in the book'):
        book.accept(an_order(), Venue.HSX, T0, order_id=order_id)


def test_queries_filter_and_preserve_entry_order(book):
    """Entry order is the exchange's own time priority, so it is preserved
    rather than sorted."""
    first = book.accept(an_order(ticker='FPT'), Venue.HSX, T0)
    second = book.accept(an_order(ticker='HPG'), Venue.HSX, T0)
    third = book.accept(an_order(ticker='SHS'), Venue.HNX, T0)
    book.rest(second.order_id, T0)
    book.cancel(third.order_id, T0)

    assert [r.order_id for r in book.orders()] == [
        first.order_id, second.order_id, third.order_id]
    assert [r.order_id for r in book.orders(venue=Venue.HNX)] == [
        third.order_id]
    assert [r.order_id for r in book.orders(ticker='HPG')] == [
        second.order_id]
    assert [r.order_id for r in book.orders(state=OrderState.RESTING)] == [
        second.order_id]
    assert [r.order_id for r in book.live()] == [
        first.order_id, second.order_id]
    assert book.get(OrderId('nope')) is None
    assert len(book) == 3


def test_expire_due_only_touches_the_venue_whose_phase_changed(book):
    """A session spans several exchanges at once -- a VN30 basket against VN30F
    is the canonical Vietnamese use case -- and their phases do not coincide:
    HNXDS opens 15 minutes before the cash market and UPCoM has no auction at
    all. A boundary on one venue must not expire another's book.
    """
    hsx = book.accept(an_order(), Venue.HSX, T0)
    hnx = book.accept(an_order(ticker='SHS'), Venue.HNX, T0)
    book.rest(hsx.order_id, T0)
    book.rest(hnx.order_id, T0)

    dead = book.expire_due(CLOSE_CROSS, Venue.HSX,
                           SessionPhase.CLOSING_AUCTION,
                           SessionPhase.POST_CLOSE)
    assert [r.order_id for r in dead] == [hsx.order_id]
    assert book.get(hnx.order_id).state is OrderState.RESTING


def test_set_encumbrances_lets_the_ledger_correct_a_stale_reservation(book):
    """A partial fill releases encumbrance **pro rata at the fill price**, and
    that arithmetic is the ledger's -- it needs the fill price and the charges
    actually levied, neither of which the state machine sees.

    Without a way to push the result back, ``OrderRecord.encumbered_cash``
    would keep reporting the amount reserved at accept for the whole life of a
    partially filled order, and section 12 invariant 4 would be summed over a
    record that lies.
    """
    order_id = OrderId('PLU-ENC-1')
    book.accept(an_order(quantity=1000), Venue.HSX, T0, order_id=order_id,
                encumbrances=[a_cash_encumbrance(order_id, '95500')])
    book.rest(order_id, T0)
    book.apply_fill(order_id, a_fill(order_id, 400))

    reduced = book.get(order_id).encumbrances[0].reduced_by(
        T0, amount=Decimal('38200'))
    updated = book.set_encumbrances(order_id, [reduced])
    assert updated.encumbered_cash == Decimal('57300')
