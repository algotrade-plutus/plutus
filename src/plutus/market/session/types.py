"""The shared vocabulary of the Tier 1 exchange session.

Every one of the seven session modules is written against this file and
against nothing else of each other's. That makes the names here the
integration: a type defined twice is a bug that only shows up at assembly.

**What lives here.** Closed sets (enums), records (frozen dataclasses), the
two rule *tables* that encode locked shape 4, and small pure helpers that
compute a derived quantity all callers would otherwise compute differently
(``Holding.sellable_from``, ``signed_quantity``, ``pool_for_venue``). Nothing
here holds mutable simulation state, opens a file, or reads the clock.

**What does not live here.** Behaviour. The ledgers, the state machine, the
rulebook resolution, the calendar arithmetic and the fill policies are the
seven modules; see
``docs/superpowers/specs/2026-08-25-tier1-interface-contract.md``.

Conventions this module enforces by its types, all of them house style:

* Every money and price quantity is a :class:`~decimal.Decimal`. Never float.
  Rates are Decimal fractions -- ``Decimal('0.001')``, never ``"0.1%"``
  (rulebook 12.1).
* Every quantity of shares or contracts is an ``int``.
* Every settlement instant is a :class:`~datetime.datetime`, never a
  :class:`~datetime.date`. Locked shape 3 forbids date-granularity settlement,
  because the regime that begins 2022-08-29 turns on 13:00 on the settlement
  day and a date cannot express it.
* Every enum that has to survive ``json.dumps`` mixes in ``str``, for the
  reason :mod:`plutus.market.protocol` gives: ``json_safe`` passes a bare
  ``Enum`` through and ``json.dumps`` then raises.

Two upstream landmines this file works around, both verified:

* :class:`plutus.core.order.Side` has a third member, ``CROSS``, whose
  ``.sign`` and ``.reverse()`` both return ``None``. Anything doing
  ``quantity * side.sign`` raises ``TypeError`` on it. Use
  :func:`signed_quantity`, which refuses ``CROSS`` loudly.
* :class:`plutus.market.protocol.Order` carries no identity -- no id, no
  submission timestamp -- and two identical orders compare and hash equal. The
  encumbrance ledger therefore cannot key on an ``Order``; it keys on the
  :data:`OrderId` this session mints and holds the ``Order`` as a payload.
"""

from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import (Any, Dict, FrozenSet, Mapping, NewType, Optional, Sequence,
                    Tuple, Union)

from plutus.core.order import OrderType, Side
from plutus.market.broker import BrokerTerms, CureWindow
from plutus.market.protocol import (MarketState, Order, OrderBook, Resolution,
                                    SessionPhase)
from plutus.market.verdicts import Admissibility, AdmissionRule, Verdict
# Deliberate use of a sibling module's private serialiser rather than a second
# copy of it. The codebase already carries one pair of tick tables that can
# drift (constant.py's TICK_SIZE against get_hsx_tick_size's inline dict); a
# second copy of the enum/temporal unwrap would be the same mistake. If this
# ever needs to be public, promote it in verdicts.py -- do not fork it.
from plutus.market.verdicts import _serialise

__all__ = [
    # identity
    'OrderId', 'FillId', 'new_order_id_seed',
    # closed sets
    'ChargeBase', 'ChargeClass', 'ChargeSide', 'Confidence', 'DataField',
    'DebitedAt', 'EventKind', 'ExpiryTrigger', 'FillEvidence', 'FillOutcome',
    'InvestorClass', 'LeviedBy', 'LiquidationRule', 'MarginStatus',
    'OrderState', 'OrderTransition', 'Pool', 'ResourceKind', 'RulebookEdition',
    'StatefulRule', 'TimeInForce', 'TradingMethod', 'Venue',
    # rule tables
    'INITIAL_STATES', 'LEGAL_TRANSITIONS', 'LIVE_STATES', 'TERMINAL_STATES',
    'EVENT_FOR_TRANSITION', 'TERMINAL_TRIGGERS_BY_TIF', 'TIME_IN_FORCE',
    'POOL_BY_VENUE', 'BROKER_CONFIG_KEYS',
    # helpers
    'pool_for_venue', 'signed_quantity', 'rule_value',
    # records
    'Accepted', 'AccountRef', 'Amended', 'Cancelled', 'Cash', 'Charge',
    'ChargeRule', 'ContractPosition', 'Encumbrance', 'Event', 'Fill',
    'FillDecision', 'Holding', 'HoldingTranche', 'IndeterminateReport',
    'MarginView', 'MarketInterval', 'OrderRecord', 'Pin', 'ProceedsTranche',
    'Rejected', 'RejectionRule', 'RuleCitation', 'SessionProvenance',
    'SettlementRule', 'Transferred',
    # config
    'AccountsConfig', 'BrokerProfile', 'DataConfig', 'ExchangeRulesConfig',
    'FillPolicyConfig', 'SessionConfig',
]


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

#: An exchange-assigned order id. Minted by ``session/orders.py`` on accept
#: *and* on reject -- a rejected order still gets an id so the rejection log
#: has a key, which is what makes the log joinable to the submission.
OrderId = NewType('OrderId', str)

#: An execution id. Unique across the session, not just within an order: a
#: partial-fill sequence is reconstructed by grouping fills on ``order_id``.
FillId = NewType('FillId', str)

#: The first ordinal an id factory should issue. Ids are strings, not ints,
#: because a broker id is a string and the point of this package is to be
#: shaped like a broker.
new_order_id_seed = 1


# --------------------------------------------------------------------------
# Venues and pools
# --------------------------------------------------------------------------

class Venue(str, Enum):
    """The four venues, str-mixed so a ``Venue`` *is* its exchange code.

    ``Venue.HSX == 'HSX'`` is True, so a ``Venue`` can be handed straight to
    :attr:`plutus.market.protocol.InstrumentSpec.exchange_code`,
    :meth:`plutus.core.constant.get_trading_unit` and every existing call site
    that takes a code string, without a conversion at the seam.

    The values match :class:`plutus.core.constant.VietnamMarketConstant`
    exactly, including ``HNXDS`` for the derivatives market -- note that
    ``VietnamMarketConstant.DS`` is the *attribute* name and ``'HNXDS'`` the
    value.
    """

    HSX = 'HSX'
    HNX = 'HNX'
    UPCOM = 'UPCOM'
    HNXDS = 'HNXDS'

    @classmethod
    def from_code(cls, code: str) -> 'Venue':
        """Parse an exchange code, tolerating the two aliases in the wild.

        ``HOSE`` is HOSE's own name for itself and appears in exchange
        publications; ``DS`` is this codebase's attribute name for HNXDS.
        Anything else raises rather than defaulting, because a silently
        defaulted venue is locked shape 1's failure mode.
        """
        aliases = {'HOSE': cls.HSX, 'DS': cls.HNXDS, 'HNX-DS': cls.HNXDS}
        upper = code.strip().upper()
        if upper in aliases:
            return aliases[upper]
        return cls(upper)

    @property
    def is_equity(self) -> bool:
        """True for the three cash venues, False for HNXDS.

        This is the branch locked shape 5 and section 7.3 turn on: a SELL on
        an equity venue needs settled holdings, a SELL on HNXDS opens a short.
        """
        return self is not Venue.HNXDS


class Pool(str, Enum):
    """Which of the two segregated pools of purchasing power a flow touches.

    Vietnamese derivatives margin sits in a separate deposit account
    ("ky quy") funded only by an explicit transfer. The two pools have
    independent purchasing power and **no auto-transfer exists**, so the pool
    has to be an explicit axis on encumbrances, charges and transfers rather
    than an implicit consequence of the instrument.

    Distinct from the ``Account`` composite of design section 4: this names a
    *pool*, not an account object.
    """

    SECURITIES = 'securities'
    DERIVATIVES = 'derivatives'


#: Which pool a venue's orders draw on. Static, not dated: no Vietnamese rule
#: change in 2020-2026 moved a venue between pools, and the KRX cutover did not
#: touch the segregation. If that ever changes this becomes a ``RuleSet``
#: lookup, which is why every caller goes through :func:`pool_for_venue`
#: rather than reading the dict.
POOL_BY_VENUE: Mapping[Venue, Pool] = {
    Venue.HSX: Pool.SECURITIES,
    Venue.HNX: Pool.SECURITIES,
    Venue.UPCOM: Pool.SECURITIES,
    Venue.HNXDS: Pool.DERIVATIVES,
}


def pool_for_venue(venue: Venue) -> Pool:
    """The pool a venue's orders draw on.

    The single routing primitive for section 7.3's "equity orders draw on
    securities cash only, futures margin draws on the deposit only". Three
    modules need this answer; none of them should compute it privately.
    """
    return POOL_BY_VENUE[venue]


class ResourceKind(str, Enum):
    """What an :class:`Encumbrance` reserves.

    Three kinds because section 7.0 defines three net figures, one per kind:
    ``Cash.available``, ``Holding.sellable`` and ``free_deposit``.
    """

    CASH = 'cash'          # securities-pool VND, reserved by a buy
    SHARES = 'shares'      # holding quantity, reserved by a sell
    DEPOSIT = 'deposit'    # derivatives-pool VND, reserved as order margin


class InvestorClass(str, Enum):
    """Which position-limit tier an account falls in.

    Rulebook 6.4 publishes three tiers -- 5,000 / 10,000 / 20,000 contracts --
    and government-bond futures bar individuals outright. Tier 1 runs
    ``INDIVIDUAL`` and never asks the caller; the axis exists so the limit
    lookup has somewhere to put it.
    """

    INDIVIDUAL = 'individual'
    INSTITUTION = 'institution'
    PROFESSIONAL = 'professional'


class TradingMethod(str, Enum):
    """Order matching versus put-through (negotiated) trading.

    Rulebook 9.2's correction to ``ExchangeSpec.get_tick_size``: without a
    method argument the tick grid rejects every legitimate put-through price,
    which is 1 dong at all four venues. Tier 1 only ever submits
    ``ORDER_MATCHING``; the argument exists so the seam is not retrofitted.
    """

    ORDER_MATCHING = 'order_matching'
    PUT_THROUGH = 'put_through'


class RulebookEdition(str, Enum):
    """Which dated rule set an instant resolves to.

    The KRX cutover on 2025-05-05 is a **dated rule set, not a migration**
    (design section 15 item 1). Both editions ship and both stay; a run
    spanning the boundary gets each on its own side. This enum is the
    canonical vocabulary for the free-form ``regime_tag`` that
    :class:`plutus.market.verdicts.Admissibility` already carries -- stamp
    ``edition.value``, so a rejection log can be split on the cutover without
    string-matching.
    """

    PRE_KRX = 'pre_krx'     # ... 2025-05-04
    POST_KRX = 'post_krx'   # 2025-05-05 ...


class Confidence(str, Enum):
    """How well-sourced a dated rule is.

    The rulebook grades every row this way and design section 6.4 makes
    traceability the rulebook's whole claim, so the grade travels with the
    value rather than living in prose. ``UNVERIFIED`` is not a smaller
    ``LOW``: it means no primary or secondary source was found at all, and a
    published result must not rest on one.
    """

    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    UNVERIFIED = 'unverified'


# --------------------------------------------------------------------------
# The order lifecycle -- locked shape 4
# --------------------------------------------------------------------------

class OrderState(str, Enum):
    """Where an order sits in the section 12 state machine.

    Seven states. ``INDETERMINATE`` is deliberately **not** among them: it is
    an *event* meaning the fill policy could not decide for one interval, and
    the order is still ``RESTING`` and re-evaluated on the next. The ledgers
    need a definite answer and "maybe 1000 shares" is not one.

    ``ACCEPTED`` and ``RESTING`` are separate because locked shape 4 says the
    order type *is* the time-in-force: an MOK is accepted and then dies
    without ever resting, so a single "live" state cannot express the
    difference between an order that is on the book and one that never
    reached it.

    Deliberately not :class:`plutus.core.order.OrderStatus`. That enum has no
    ``RESTING`` member, carries eighteen states describing a *broker
    round-trip* (``SENT_TO_BROKER``, ``RECEIVED_EXCHANGE``, ...) that a
    simulated exchange has no analogue for, and is not ``str``-mixed.
    """

    ACCEPTED = 'accepted'
    RESTING = 'resting'
    PARTIALLY_FILLED = 'partially_filled'
    FILLED = 'filled'
    CANCELLED = 'cancelled'
    EXPIRED = 'expired'
    REJECTED = 'rejected'

    @property
    def is_terminal(self) -> bool:
        """True for the four states an order never leaves (invariant 2)."""
        return self in TERMINAL_STATES

    @property
    def is_live(self) -> bool:
        """True while the order still holds encumbrance.

        This is the predicate section 7.0's three net figures are computed
        over -- "net of live orders" means net of orders in one of these
        three states.
        """
        return self in LIVE_STATES


#: The four states an order never leaves. Section 12 invariant 2.
TERMINAL_STATES: FrozenSet[OrderState] = frozenset({
    OrderState.FILLED,
    OrderState.CANCELLED,
    OrderState.EXPIRED,
    OrderState.REJECTED,
})

#: The three states in which an order still holds encumbrance. Section 12
#: invariant 4 -- the sum of encumbrance over exactly these orders must equal
#: the ledgers' committed totals, and must fall to zero when none is live.
LIVE_STATES: FrozenSet[OrderState] = frozenset({
    OrderState.ACCEPTED,
    OrderState.RESTING,
    OrderState.PARTIALLY_FILLED,
})

#: The two states ``submit()`` can produce. Section 12's graph forks here and
#: nowhere else.
INITIAL_STATES: FrozenSet[OrderState] = frozenset({
    OrderState.ACCEPTED,
    OrderState.REJECTED,
})

#: The section 12 graph as data, so ``orders.py`` cannot draw a different one.
#:
#: Three edges are here that the ASCII drawing in the design omits, each
#: forced by locked shape 4 rather than added for convenience:
#:
#: * ``ACCEPTED -> {PARTIALLY_FILLED, FILLED, EXPIRED}``. A non-resting type
#:   never occupies ``RESTING``: an MOK fills in full or dies at entry, an MAK
#:   fills what it can and expires the remainder. Routing them through
#:   ``RESTING`` would put an order on the book that by rule was never on it.
#: * ``RESTING -> FILLED``. A resting order filled in one go never passes
#:   through ``PARTIALLY_FILLED``.
#: * ``PARTIALLY_FILLED -> PARTIALLY_FILLED``. Successive partial fills are
#:   the normal case, and a self-edge is how the state machine says so.
#:
#: ``ACCEPTED -> CANCELLED`` is legal because a caller may cancel between
#: accept and the first evaluation. ``REJECTED`` has no in-edges: it is
#: reached only from ``submit()``.
LEGAL_TRANSITIONS: Mapping[OrderState, FrozenSet[OrderState]] = {
    OrderState.ACCEPTED: frozenset({
        OrderState.RESTING, OrderState.PARTIALLY_FILLED, OrderState.FILLED,
        OrderState.CANCELLED, OrderState.EXPIRED,
    }),
    OrderState.RESTING: frozenset({
        OrderState.PARTIALLY_FILLED, OrderState.FILLED,
        OrderState.CANCELLED, OrderState.EXPIRED,
    }),
    OrderState.PARTIALLY_FILLED: frozenset({
        OrderState.PARTIALLY_FILLED, OrderState.FILLED,
        OrderState.CANCELLED, OrderState.EXPIRED,
    }),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.EXPIRED: frozenset(),
    OrderState.REJECTED: frozenset(),
}


class OrderTransition(str, Enum):
    """The *cause* of a state change. Section 12 invariant 3.

    Separate from :class:`OrderState` because a state says where an order is
    and a transition says why it moved, and the two are not in bijection:
    ``FILL`` and ``PARTIAL_FILL`` both land in a state determined by whether
    any quantity remains, and ``REST`` produces no caller-visible event at
    all.
    """

    ACCEPT = 'accept'
    REJECT = 'reject'
    REST = 'rest'
    PARTIAL_FILL = 'partial_fill'
    FILL = 'fill'
    CANCEL = 'cancel'
    EXPIRE = 'expire'


class TimeInForce(str, Enum):
    """What an order's *type* says about how long it lives.

    In Vietnam the order type **is** the time-in-force -- there is no separate
    TIF field on any venue at any date in the window -- which is why locked
    shape 4 forbids one ``RESTING`` state with a single "expire at every phase
    boundary" rule. Each member below is a distinct terminal edge.

    ``IMMEDIATE_THEN_DAY`` is the one that is not obvious: MTL (and HOSE's
    pre-KRX MP, which is the same economics under an older mnemonic) walks the
    book, and its *residue converts to a resting limit order* one tick beyond
    the last match. So it is an immediate order that becomes a day order,
    which neither ``DAY`` nor ``IMMEDIATE_OR_CANCEL`` can express.
    """

    DAY = 'day'
    AUCTION_ONLY = 'auction_only'
    FILL_OR_KILL = 'fill_or_kill'
    IMMEDIATE_OR_CANCEL = 'immediate_or_cancel'
    IMMEDIATE_THEN_DAY = 'immediate_then_day'

    @property
    def rests(self) -> bool:
        """Whether an order of this time-in-force can occupy ``RESTING``.

        False for the three immediate families and for ATO/ATC, which are
        enterable only inside their own auction window and are auto-cancelled
        at the cross -- they never rest and never carry (rulebook 2.3).
        """
        return self in (TimeInForce.DAY, TimeInForce.IMMEDIATE_THEN_DAY)


#: Order type to time-in-force. **Undated on purpose**, and the one lookup in
#: this package that is allowed to be.
#:
#: What is dated is *legality* -- which types a venue accepts on a date -- and
#: that lives in ``rulebook.py``'s ``RuleSet.legal_order_types()``. The
#: semantics of a type that is legal have not moved in 2020-2026: rulebook 10
#: records order types as explicitly **unchanged** across the KRX cutover on
#: derivatives, and HOSE's MP-to-MTL change is a mnemonic swap with identical
#: economics.
#:
#: ``MARKET`` ("MKT") maps to ``IMMEDIATE_OR_CANCEL`` for completeness only.
#: The rulebook's finding is flat: "No such order type exists in Vietnam at
#: any date" -- the synthetic buy-at-ceiling/sell-at-floor order in
#: ``core/order.py:56`` matches no Vietnamese type. ``legal_order_types()``
#: therefore returns no venue-date pair containing it, and this row is never
#: exercised. It is here so the mapping is total.
TIME_IN_FORCE: Mapping[OrderType, TimeInForce] = {
    OrderType.LIMIT: TimeInForce.DAY,
    OrderType.AT_THE_OPENING: TimeInForce.AUCTION_ONLY,
    OrderType.AT_THE_CLOSE: TimeInForce.AUCTION_ONLY,
    OrderType.MARKET_FILL_OR_KILL: TimeInForce.FILL_OR_KILL,
    OrderType.MARKET_IMMEDIATE_OR_CANCEL: TimeInForce.IMMEDIATE_OR_CANCEL,
    OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT: TimeInForce.IMMEDIATE_THEN_DAY,
    OrderType.MARKET: TimeInForce.IMMEDIATE_OR_CANCEL,
}


class ExpiryTrigger(str, Enum):
    """Why an order expired. The per-type terminal edges of locked shape 4.

    Every member names an event in the trading day, and
    :data:`TERMINAL_TRIGGERS_BY_TIF` says which types each may end. The
    absence is as load-bearing as the presence: **there is no
    ``NOON_BREAK`` member**, because the noon break must not expire the book.
    11:30-13:00 is a hard shutdown for entry, amendment and cancellation
    (rulebook 2.1) but resting orders survive it, and a simulator that expires
    at every phase boundary destroys the afternoon book.
    """

    AUCTION_CROSS = 'auction_cross'
    """An unmatched ATO or ATC dies at its own cross -- 09:15 and 14:45."""

    NOT_FILLABLE_IN_FULL = 'not_fillable_in_full'
    """MOK: fill-or-kill, cancelled entirely if not fillable in full."""

    IMMEDIATE_REMAINDER = 'immediate_remainder'
    """MAK: immediate-or-cancel, the unfilled remainder dies at once."""

    NO_OPPOSITE_ORDER = 'no_opposite_order'
    """A market-family order entered with no opposite limit order on the book
    is cancelled at entry (rulebook 2.3, all venues, whole window)."""

    SESSION_END = 'session_end'
    """A day order dies at the end of the last matching phase of its day."""

    INSTRUMENT_EXPIRY = 'instrument_expiry'
    """A resting order on a futures contract that reached its last trading
    day. Not a Vietnamese rule with a citation -- an adopted simulator
    behaviour, because the alternative is an order resting on a contract that
    no longer exists."""


#: Which expiry triggers may end an order of each time-in-force.
#:
#: This table plus :data:`TIME_IN_FORCE` **is** locked shape 4. A phase
#: boundary does not expire an order; a boundary that appears in this table
#: for that order's type does. ``orders.py`` reads it and must not hard-code a
#: boundary list of its own.
#:
#: ``INSTRUMENT_EXPIRY`` appears against every resting family because it is
#: instrument-driven, not type-driven.
TERMINAL_TRIGGERS_BY_TIF: Mapping[TimeInForce, FrozenSet[ExpiryTrigger]] = {
    TimeInForce.DAY: frozenset({
        ExpiryTrigger.SESSION_END, ExpiryTrigger.INSTRUMENT_EXPIRY,
    }),
    TimeInForce.AUCTION_ONLY: frozenset({
        ExpiryTrigger.AUCTION_CROSS,
    }),
    TimeInForce.FILL_OR_KILL: frozenset({
        ExpiryTrigger.NOT_FILLABLE_IN_FULL, ExpiryTrigger.NO_OPPOSITE_ORDER,
    }),
    TimeInForce.IMMEDIATE_OR_CANCEL: frozenset({
        ExpiryTrigger.IMMEDIATE_REMAINDER, ExpiryTrigger.NO_OPPOSITE_ORDER,
    }),
    TimeInForce.IMMEDIATE_THEN_DAY: frozenset({
        ExpiryTrigger.NO_OPPOSITE_ORDER, ExpiryTrigger.SESSION_END,
        ExpiryTrigger.INSTRUMENT_EXPIRY,
    }),
}


# --------------------------------------------------------------------------
# Rejections -- the four stateful rules the session adds
# --------------------------------------------------------------------------

class StatefulRule(str, Enum):
    """The four rejections that need account state, so ``admits()`` cannot see them.

    .. warning::

       **These belong in :class:`plutus.market.verdicts.AdmissionRule` and
       must be merged into it.** Design section 5 names them as extensions of
       the existing six-member vocabulary, "added rather than substituted",
       and section 10 requires the 617 existing tests to stay green. They sit
       in a second enum only because the task that authored this file may not
       modify ``verdicts.py``, and Python cannot extend an ``Enum`` that
       already has members.

       When the orchestrator merges them: add these four members to
       ``AdmissionRule``, delete this class, and re-point
       :data:`RejectionRule` at ``AdmissionRule``. Every call site reads
       :data:`RejectionRule`, so nothing else changes. The values below are
       already the final ones.

    Reusing ``SESSION_SEMANTICS`` for any of these would be the real damage:
    ``AdmissionRule`` *is* the rejected-order log, and a log that cannot tell
    "you had no cash" from "the market was shut" measures nothing.
    """

    UNSETTLED_HOLDING = 'unsettled_holding'
    INSUFFICIENT_CASH = 'insufficient_cash'
    INSUFFICIENT_DEPOSIT = 'insufficient_deposit'
    POSITION_LIMIT = 'position_limit'


#: Any rule that can refuse a submission, a cancellation or a transfer.
#:
#: The union exists only for the life of :class:`StatefulRule`; see its
#: warning. Type every ``rule`` parameter and field as this, never as one half.
RejectionRule = Union[AdmissionRule, StatefulRule]


def rule_value(rule: RejectionRule) -> str:
    """The wire value of a rejection rule, from either half of the union.

    Both halves are ``str``-mixed, so this is ``rule.value`` -- the function
    exists so that when the two enums merge, no call site has to change.
    """
    return rule.value


# --------------------------------------------------------------------------
# Fills and the data contract
# --------------------------------------------------------------------------

class FillOutcome(str, Enum):
    """What a :class:`FillDecision` decided.

    Three outcomes, mirroring the three-state :class:`Verdict` and for the
    same reason: when the data cannot decide, saying so is required and
    guessing is forbidden. ``INDETERMINATE`` is the measurement design section
    8 sells -- "the share of results resting on ``INDETERMINATE`` fills is a
    direct measure of how much of a backtest is unknowable".
    """

    FILL = 'fill'
    NO_FILL = 'no_fill'
    INDETERMINATE = 'indeterminate'


class FillEvidence(str, Enum):
    """What the fill decision rested on.

    Separates the two cases design section 8 makes the whole Hard/Soft split
    turn on: the market demonstrably traded *through* the limit, versus it
    only touched it. ``Soft`` fills on either; ``Hard`` fills on
    ``TRADED_THROUGH`` and returns ``INDETERMINATE`` on ``TOUCHED_AT_LIMIT``.
    """

    TRADED_THROUGH = 'traded_through'
    TOUCHED_AT_LIMIT = 'touched_at_limit'
    AUCTION_PRICE = 'auction_price'
    """A call-auction fill at the published open or close (design section 8:
    "In a call auction, the published open/close")."""
    MODELLED = 'modelled'
    """A probabilistic or queue-estimated fill. No Tier 1 policy emits this."""


class DataField(str, Enum):
    """A field of the data-source contract, named on an ``INDETERMINATE``.

    Design section 9.2: "**Nothing silently defaults.** A missing field
    produces ``INDETERMINATE`` with the field named, and the session reports
    the rate." This enum is what "named" means -- a free-form string could not
    be counted, and :class:`IndeterminateReport` counts by field.
    """

    LAST = 'last'
    OPEN = 'open'
    HIGH = 'high'
    LOW = 'low'
    CLOSE = 'close'
    REFERENCE = 'reference'
    CEILING = 'ceiling'
    FLOOR = 'floor'
    SESSION_PHASE = 'session_phase'
    VOLUME = 'volume'
    BOOK = 'book'
    BOOK_SIZE = 'book_size'
    """Present on every corpus here as a distinct absence: the ladder has
    prices at up to three levels but ``quote_asksize``/``quote_bidsize`` are
    0-row, so ``BookLevel.size`` is always ``None``. A policy needing sizes
    must name this field, not ``BOOK``."""
    FOREIGN_ROOM = 'foreign_room'
    SETTLEMENT_PRICE = 'settlement_price'


# --------------------------------------------------------------------------
# Margin
# --------------------------------------------------------------------------

class MarginStatus(str, Enum):
    """Where the account sits on the utilisation ladder.

    Four states, because design section 7.4 is explicit that "the 80/90/100
    ladder is three states, not one call boolean" -- plus ``OK`` below the
    warning level. The thresholds are :class:`BrokerTerms` fields
    (``warning_utilisation`` 0.80, ``margin_call_utilisation`` 0.90,
    ``forced_close_utilisation`` 1.00), and the *shape* of the ladder is
    VSDC-sourced (rulebook 6.3, Article 13: levels 1/2/3 at 80/90/100 per
    investor account) while each broker's own levels are commercial terms.

    The ratio tested is ``utilisation = MR / margin assets``, **not** a
    maintenance-margin fraction of notional: Vietnam publishes no maintenance
    margin ratio at any date in 2020-2026.

    :attr:`INDETERMINATE` is **not** a fifth rung of the ladder; it is the
    absence of one. Design section 9 puts ``settlement_price`` in the data
    contract with "absent => margin marks ``INDETERMINATE``", and a rung
    computed from a mark taken in an earlier session is a claim the data does
    not support. It is separate from ``OK`` for the same reason
    :class:`~plutus.market.verdicts.Verdict` separates ``REJECTED`` from
    ``INDETERMINATE``: a rule saying "fine" and nobody having looked are
    different facts, and only one of them belongs in a published margin-
    incidence figure. :class:`MarginView.stale_marks` names the contracts
    responsible.
    """

    OK = 'ok'
    WARNING = 'warning'
    CALL = 'call'
    FORCED = 'forced'
    INDETERMINATE = 'indeterminate'


class LiquidationRule(str, Enum):
    """How a forced close chooses which contracts to shut.

    Design section 7.4 leaves this open and requires the implementation to
    *state* it: "``ForcedLiquidation`` must state its selection rule
    (largest-loss-first, or pro rata)". This contract adopts
    :attr:`LARGEST_LOSS_FIRST` as the default and records it as a **modelling
    choice, not a sourced rule** -- no Vietnamese document prescribes a
    selection order for a broker's forced close, and rulebook 6.3 shows the
    real mechanism is VSDC suspending the account rather than picking legs.
    """

    LARGEST_LOSS_FIRST = 'largest_loss_first'
    PRO_RATA = 'pro_rata'


# --------------------------------------------------------------------------
# Charges
# --------------------------------------------------------------------------

class ChargeClass(str, Enum):
    """Which instrument family a charge applies to (config key ``applies_to``).

    The four of design section 6.1. Rulebook 12.2 carries a wider set --
    closed-end funds, corporate bonds, government debt and bond futures are
    separate rows there -- and those are the Tier 2 extension. Note ``ETF`` is
    a refinement of :attr:`plutus.market.protocol.InstrumentKind.FUND`; the
    discriminator is ``plutus.core.constant.is_etf()``.
    """

    EQUITY = 'equity'
    WARRANT = 'warrant'
    ETF = 'etf'
    FUTURE = 'future'


class ChargeBase(str, Enum):
    """What a charge is levied per.

    The awkward members are the point. ``PER_OPEN_CONTRACT_PER_DAY`` exists
    because the VSD position maintenance fee accrues per open contract per
    account per day, "which no per-trade constant can express";
    ``MONTHLY_PER_SECURITY`` because custody is billed monthly per security.
    A table with only ``TRADE_VALUE`` and ``PER_TRADE`` cannot hold either,
    which is why charges are a table and not a pair of constants.
    """

    TRADE_VALUE = 'trade_value'
    PER_CONTRACT = 'per_contract'
    PER_TRADE = 'per_trade'
    PER_OPEN_CONTRACT_PER_DAY = 'per_open_contract_per_day'
    MONTHLY_PER_SECURITY = 'monthly_per_security'


class ChargeSide(str, Enum):
    """Which side of a trade a charge falls on.

    ``SELL`` is the load-bearing member: the 0.1% personal income tax on a
    securities transfer is sell-side only and withheld at source, so a sale
    credits cash **net**. Without that, every sale is wrong by more than most
    commissions. ``NONE`` is for holding charges, which attach to a position
    rather than a trade.
    """

    BUY = 'buy'
    SELL = 'sell'
    BOTH = 'both'
    NONE = 'none'


class LeviedBy(str, Enum):
    """Who imposes a charge -- and therefore which config object owns it.

    Design section 6.1's routing rule, made structural: ``STATE``,
    ``EXCHANGE`` and ``VSD`` rows are gazetted and dated, so they belong in
    the rulebook and must carry a :class:`RuleCitation`; ``BROKER`` rows are
    commercial and belong in :class:`BrokerProfile`. ``rulebook.py`` rejects a
    ``BROKER`` row and ``BrokerProfile`` rejects the other three.
    """

    STATE = 'state'
    EXCHANGE = 'exchange'
    VSD = 'vsd'
    BROKER = 'broker'


class DebitedAt(str, Enum):
    """When a charge hits cash.

    ``DAILY`` is not a convenience: rulebook 12.2 records that broker
    commissions tier on the day's *total* traded value per account, so "the
    correct rate is not knowable at fill time" and fills must be accrued and
    charged at the daily close. A per-fill-only model silently picks the wrong
    tier.
    """

    FILL = 'fill'
    DAILY = 'daily'
    MONTHLY = 'monthly'


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

class EventKind(str, Enum):
    """Everything the caller can be told about, on one cursor.

    The nine of design section 5, plus three additions each justified below.

    ``ACCEPTED`` and ``REJECTED`` are additions: section 5 delivers them as
    ``submit()`` return values, which is right for the synchronous caller, but
    a cursor that omits them cannot reconstruct an order's history from the
    event log alone. Emitting them as well costs nothing and makes the log
    complete. A caller that only wants post-submission news filters on
    :attr:`is_order_event` minus these two.

    ``MARGIN_WARNING`` is an addition forced by design section 7.4: the ladder
    is "three states, not one call boolean", and the 80% level is invisible to
    a caller if it emits no event. :class:`BrokerTerms.warning_utilisation`
    already exists to trigger it.

    There is deliberately **no ``RESTING`` event**. Resting is a state, not
    news; the caller learns it from ``session.orders()``.
    """

    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    FILLED = 'filled'
    PARTIALLY_FILLED = 'partially_filled'
    CANCELLED = 'cancelled'
    EXPIRED = 'expired'
    INDETERMINATE = 'indeterminate'
    MARGIN_WARNING = 'margin_warning'
    MARGIN_CALL = 'margin_call'
    FORCED_LIQUIDATION = 'forced_liquidation'
    SETTLEMENT_CREDITED = 'settlement_credited'
    EXPIRY_SETTLED = 'expiry_settled'

    @property
    def is_order_event(self) -> bool:
        """True when the event names an order and carries an ``order_id``."""
        return self in _ORDER_EVENTS


_ORDER_EVENTS: FrozenSet[EventKind] = frozenset({
    EventKind.ACCEPTED, EventKind.REJECTED, EventKind.FILLED,
    EventKind.PARTIALLY_FILLED, EventKind.CANCELLED, EventKind.EXPIRED,
    EventKind.INDETERMINATE,
})


#: The event a state-machine transition emits, or ``None`` for a silent one.
#:
#: ``REST`` is the only silent transition, for the reason in
#: :class:`EventKind`. ``FILL`` and ``PARTIAL_FILL`` are distinct rows because
#: the caller needs to know whether anything remains -- and the distinction is
#: not derivable from the fill quantity alone, since a fill that exhausts the
#: remainder of an already-partial order is a ``FILLED``.
EVENT_FOR_TRANSITION: Mapping[OrderTransition, Optional[EventKind]] = {
    OrderTransition.ACCEPT: EventKind.ACCEPTED,
    OrderTransition.REJECT: EventKind.REJECTED,
    OrderTransition.REST: None,
    OrderTransition.PARTIAL_FILL: EventKind.PARTIALLY_FILLED,
    OrderTransition.FILL: EventKind.FILLED,
    OrderTransition.CANCEL: EventKind.CANCELLED,
    OrderTransition.EXPIRE: EventKind.EXPIRED,
}


# --------------------------------------------------------------------------
# Helpers over the upstream vocabulary
# --------------------------------------------------------------------------

def signed_quantity(side: Side, quantity: int) -> int:
    """``quantity`` signed by side: positive for BUY, negative for SELL.

    The one safe way to sign a quantity in this package.
    :attr:`plutus.core.order.Side.CROSS` exists and its ``.sign`` property
    falls off the end of the method with no ``else``, returning ``None`` --
    verified -- so ``quantity * side.sign`` raises ``TypeError`` on it rather
    than producing a wrong number. A net-signed :class:`ContractPosition`
    computed through that path would be silently corrupt, so this refuses
    ``CROSS`` at the boundary instead.

    ``CROSS`` is a put-through (negotiated) marker, and Tier 1 submits only
    :attr:`TradingMethod.ORDER_MATCHING`, so no legitimate Tier 1 call reaches
    the raise.

    Raises:
        ValueError: on ``Side.CROSS``, or on a negative ``quantity``.
    """
    if side is Side.CROSS:
        raise ValueError(
            'Side.CROSS cannot be signed: it is a put-through marker, not a '
            'direction, and Side.CROSS.sign returns None. Route put-through '
            'trades through TradingMethod.PUT_THROUGH, which Tier 1 does not '
            'implement.'
        )
    if quantity < 0:
        raise ValueError(
            f'quantity must not be negative, got {quantity}; the sign comes '
            f'from the side, never from the magnitude'
        )
    return quantity if side is Side.BUY else -quantity


# --------------------------------------------------------------------------
# Encumbrance -- locked shape 2
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Encumbrance:
    """Resources reserved by one live order, on one resource, in one pool.

    Locked shape 2. Because orders now *rest*, every ledger check must test a
    balance net of live orders rather than the raw balance. Without a
    reservation taken at accept, two individually-affordable resting buys
    overdraw cash and 500 settled shares back 1,000 shares of resting sells --
    a short equity position, which Vietnam does not permit at all.

    **The key is ``(order_id, resource)``**, not an id of its own: an order
    reserves at most one kind of resource per pool, and giving it a synthetic
    id would let the same order hold two cash reservations. ``ledgers.py``
    holds ``Dict[Tuple[OrderId, ResourceKind], Encumbrance]``.

    ``amount`` and ``quantity`` are what is *still* reserved. ``original_*``
    is what was taken, kept so a pro-rata release on a partial fill is
    auditable rather than inferred from a difference the ledger no longer
    knows. Exactly one of the two is meaningful per :class:`ResourceKind`:
    ``CASH`` and ``DEPOSIT`` use ``amount``, ``SHARES`` uses ``quantity``.

    ``estimated_charges`` is the slice of ``amount`` that is fees and tax
    rather than trade value. It is inside the encumbrance on purpose (design
    section 7.0), so ``Cash.available`` stays consistent with what a fill will
    actually cost; keeping it separately visible is what lets the ledger
    release the trade-value part at the fill price and settle the charge part
    against the charges actually levied.
    """

    order_id: OrderId
    pool: Pool
    resource: ResourceKind
    amount: Decimal
    quantity: int
    original_amount: Decimal
    original_quantity: int
    taken_at: datetime
    ticker: Optional[str] = None
    estimated_charges: Decimal = Decimal('0')
    released_at: Optional[datetime] = None

    @classmethod
    def take(
        cls,
        order_id: OrderId,
        pool: Pool,
        resource: ResourceKind,
        ts: datetime,
        *,
        amount: Decimal = Decimal('0'),
        quantity: int = 0,
        ticker: Optional[str] = None,
        estimated_charges: Decimal = Decimal('0'),
    ) -> 'Encumbrance':
        """A fresh reservation, with ``original_*`` set from the request."""
        return cls(
            order_id=order_id, pool=pool, resource=resource,
            amount=amount, quantity=quantity,
            original_amount=amount, original_quantity=quantity,
            taken_at=ts, ticker=ticker,
            estimated_charges=estimated_charges,
        )

    @property
    def key(self) -> Tuple[OrderId, ResourceKind]:
        """The ledger key. See the class docstring for why it is this pair."""
        return (self.order_id, self.resource)

    @property
    def is_released(self) -> bool:
        """True once nothing is reserved. Section 12 invariant 4's leaf test."""
        return self.amount <= 0 and self.quantity <= 0

    def reduced_by(
        self,
        ts: datetime,
        *,
        amount: Decimal = Decimal('0'),
        quantity: int = 0,
    ) -> 'Encumbrance':
        """A copy with ``amount``/``quantity`` reduced -- a partial release.

        Used for the pro-rata release on a partial fill. Reducing below zero
        clamps at zero and stamps ``released_at``: an over-release is a leak
        in the other direction and must not create a negative reservation that
        would inflate ``available``.
        """
        new_amount = max(Decimal('0'), self.amount - amount)
        new_quantity = max(0, self.quantity - quantity)
        released = (new_amount <= 0 and new_quantity <= 0)
        return replace(
            self, amount=new_amount, quantity=new_quantity,
            released_at=ts if released else self.released_at,
        )

    def released(self, ts: datetime) -> 'Encumbrance':
        """A copy reserving nothing -- the full release every terminal edge takes."""
        return replace(self, amount=Decimal('0'), quantity=0, released_at=ts)


# --------------------------------------------------------------------------
# Fills
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Fill:
    """One execution against one order. The ledger's unit of truth.

    A fill is what moves every ledger: it credits an unsettled holdings
    tranche or a pending proceeds tranche, releases the encumbrance at the
    *fill* price rather than the reserved price, levies the ``debited_at=fill``
    charges, and nets the contract ledger.

    ``price`` follows design section 8's fixed convention, which must not
    drift or the whole point of a spread across fill policies is lost: in a
    call auction the published open or close; in continuous session under a
    no-impact replay, a limit order fills at **its own limit price** -- the
    only non-arbitrary choice available when the replay cannot move the
    market.

    ``quantity`` is already floored to the instrument's trading unit by the
    fill policy. A ``max_participation`` cap that is not floored leaves the
    ledger holding an odd lot that ``ROUND_LOT`` will later refuse to sell.
    """

    fill_id: FillId
    order_id: OrderId
    ticker: str
    venue: Venue
    side: Side
    quantity: int
    price: Decimal
    ts: datetime
    evidence: FillEvidence
    confidence: Decimal = Decimal('1')
    charges: Tuple['Charge', ...] = ()

    @property
    def gross_value(self) -> Decimal:
        """``quantity x price``, before any multiplier and before charges.

        **Not the cash movement.** Cash venues quote in thousands of dong, so
        the caller must apply ``CURRENCY_UNIT`` (1000); HNXDS quotes index
        points and applies the contract multiplier (100,000 VND per point)
        instead, for which ``CURRENCY_UNIT['HNXDS'] = 1`` is meaningless and
        must not be used as a multiplier. Unit conversion is
        ``ledgers.py``/``deposit.py``'s job because it differs by pool; this
        property is deliberately unit-naive so it cannot hide the choice.
        """
        return Decimal(self.quantity) * self.price

    @property
    def total_charges(self) -> Decimal:
        """Sum of the charges levied on this fill."""
        return sum((c.amount for c in self.charges), Decimal('0'))


@dataclass(frozen=True)
class FillDecision:
    """What a :class:`FillPolicy` decided for one order over one interval.

    Design section 8 writes this as three classes -- ``Fill(qty, price,
    confidence)``, ``NoFill(reason)``, ``Indeterminate(reason)``. It is one
    tagged record here for two reasons: the name ``Fill`` is already taken by
    the execution record above, which is a genuinely different thing; and a
    single shape spares every call site an ``isinstance`` ladder while
    carrying ``reason`` and ``confidence`` on the same object. Construct it
    through :meth:`fill`, :meth:`no_fill` and :meth:`indeterminate`, never
    positionally -- the constructors are the three cases.

    ``missing`` names the data fields whose absence produced an
    ``INDETERMINATE``, which is design section 9.2's "with the field named"
    and is what :class:`IndeterminateReport` counts.
    """

    outcome: FillOutcome
    quantity: int = 0
    price: Optional[Decimal] = None
    confidence: Decimal = Decimal('0')
    evidence: Optional[FillEvidence] = None
    reason: Optional[str] = None
    missing: FrozenSet[DataField] = frozenset()

    @classmethod
    def fill(
        cls,
        quantity: int,
        price: Decimal,
        evidence: FillEvidence,
        confidence: Decimal = Decimal('1'),
    ) -> 'FillDecision':
        """A definite execution of ``quantity`` at ``price``."""
        return cls(outcome=FillOutcome.FILL, quantity=quantity, price=price,
                   confidence=confidence, evidence=evidence)

    @classmethod
    def no_fill(cls, reason: str) -> 'FillDecision':
        """A definite non-execution: the policy is sure nothing traded."""
        return cls(outcome=FillOutcome.NO_FILL, reason=reason)

    @classmethod
    def indeterminate(
        cls,
        reason: str,
        missing: Sequence[DataField] = (),
    ) -> 'FillDecision':
        """The policy could not decide. The order stays ``RESTING``.

        Not a state and not a rejection: section 12 is explicit that drawing
        ``INDETERMINATE`` as a leaf beside ``CANCELLED`` was wrong.
        """
        return cls(outcome=FillOutcome.INDETERMINATE, reason=reason,
                   missing=frozenset(missing))

    @property
    def filled(self) -> bool:
        """True only for a definite execution of positive quantity."""
        return self.outcome is FillOutcome.FILL and self.quantity > 0


# --------------------------------------------------------------------------
# The order book of record
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class OrderRecord:
    """One row of the caller's own order book, in any state.

    Design section 8 calls the argument of ``FillPolicy.evaluate`` a
    ``RestingOrder``. This contract renames it, because the same row is the
    answer to ``session.orders(state=FILLED)`` and calling a filled order a
    "resting order" is a lie in a type name. The fill policy sees only rows
    whose state is live, which is a filter the session applies, not a
    different type.

    **Frozen, and evolved by returning a new instance.** The record is a
    value; the mutable thing is the book that maps ``order_id`` to the latest
    version of it, and that book is ``orders.py``'s ``OrderBookOfRecord``.
    This split is what makes section 12 invariant 2 -- "a terminal order state
    is never left" -- checkable at the one place transitions happen instead of
    everywhere a field is assigned.

    ``filled_quantity``, ``remaining_quantity`` and ``average_fill_price`` are
    **derived from** ``fills`` rather than stored. Section 12 invariant 1
    (``filled + remaining = original``) is then structural rather than
    something a test has to catch after the fact, and there is no second place
    for the two to disagree.

    ``venue`` is resolved once, at accept, from ``instrument(ticker, ts)`` at
    the submission instant -- locked shape 1. It is stored rather than
    re-resolved per evaluation because an order must be governed by the venue
    it was accepted under; re-resolving mid-life would move a resting order
    between rulebooks.
    """

    order_id: OrderId
    order: Order                        # plutus.market.protocol.Order, verbatim
    venue: Venue
    state: OrderState
    time_in_force: TimeInForce
    submitted_at: datetime
    updated_at: datetime
    fills: Tuple[Fill, ...] = ()
    encumbrances: Tuple[Encumbrance, ...] = ()
    regime_tag: Optional[str] = None
    rejection: Optional['Rejected'] = None
    expiry_trigger: Optional[ExpiryTrigger] = None
    last_transition: Optional[OrderTransition] = None

    # -- derived quantities, per the class docstring --------------------

    @property
    def original_quantity(self) -> int:
        """The quantity submitted. Never changes except by ``amend()``."""
        return self.order.quantity

    @property
    def filled_quantity(self) -> int:
        """Total executed quantity across every fill."""
        return sum(f.quantity for f in self.fills)

    @property
    def remaining_quantity(self) -> int:
        """Unexecuted quantity. ``filled + remaining == original``, always."""
        return self.original_quantity - self.filled_quantity

    @property
    def average_fill_price(self) -> Optional[Decimal]:
        """Quantity-weighted mean fill price, or ``None`` before the first fill.

        ``None`` rather than zero: a zero average price is a number, and a
        number that means "no data" is exactly what the three-state
        :class:`Verdict` exists to prevent elsewhere in this package.
        """
        if not self.fills:
            return None
        filled = self.filled_quantity
        if filled <= 0:
            return None
        total = sum((Decimal(f.quantity) * f.price for f in self.fills),
                    Decimal('0'))
        return total / Decimal(filled)

    @property
    def is_live(self) -> bool:
        """True while the order still holds encumbrance."""
        return self.state.is_live

    @property
    def is_terminal(self) -> bool:
        return self.state.is_terminal

    def encumbrance(self, resource: ResourceKind) -> Optional[Encumbrance]:
        """This order's reservation on one resource, if it holds one."""
        for enc in self.encumbrances:
            if enc.resource is resource:
                return enc
        return None

    @property
    def encumbered_cash(self) -> Decimal:
        """Securities-pool cash still reserved by this order."""
        enc = self.encumbrance(ResourceKind.CASH)
        return enc.amount if enc is not None else Decimal('0')

    @property
    def encumbered_quantity(self) -> int:
        """Holding quantity still committed to this order (a sell)."""
        enc = self.encumbrance(ResourceKind.SHARES)
        return enc.quantity if enc is not None else 0

    @property
    def encumbered_deposit(self) -> Decimal:
        """Derivatives-deposit margin still reserved by this resting order.

        Design section 7.4: resting derivative orders must contribute to
        ``MR``, "or a caller can rest futures orders it cannot fund".
        """
        enc = self.encumbrance(ResourceKind.DEPOSIT)
        return enc.amount if enc is not None else Decimal('0')

    # -- evolution ------------------------------------------------------

    def with_state(
        self,
        state: OrderState,
        transition: OrderTransition,
        ts: datetime,
        *,
        trigger: Optional[ExpiryTrigger] = None,
        rejection: Optional['Rejected'] = None,
    ) -> 'OrderRecord':
        """A copy in a new state, stamped with the instant and the cause.

        Section 12 invariant 3 -- "every transition carries a timestamp and a
        cause" -- is satisfied here, not by convention at the call sites.
        Legality of the edge is ``orders.py``'s check against
        :data:`LEGAL_TRANSITIONS`; this method does not validate, so that the
        one enforcement point stays the state machine.
        """
        return replace(self, state=state, updated_at=ts,
                       last_transition=transition,
                       expiry_trigger=trigger if trigger is not None
                       else self.expiry_trigger,
                       rejection=rejection if rejection is not None
                       else self.rejection)

    def with_fill(self, fill: Fill, ts: datetime) -> 'OrderRecord':
        """A copy carrying one more fill, in the state that fill implies.

        The state is computed, not passed: a fill that exhausts the remainder
        is ``FILLED`` whether or not the order was already partial, and a fill
        that does not is ``PARTIALLY_FILLED``. Letting the caller name the
        state is how the two drift apart.

        Raises:
            ValueError: if the fill would take ``filled_quantity`` past
                ``original_quantity``, which would break invariant 1.
        """
        if fill.quantity <= 0:
            raise ValueError(
                f'a fill must move positive quantity, got {fill.quantity}')
        if self.filled_quantity + fill.quantity > self.original_quantity:
            raise ValueError(
                f'fill of {fill.quantity} would take order {self.order_id} to '
                f'{self.filled_quantity + fill.quantity} filled against an '
                f'original {self.original_quantity}; filled + remaining must '
                f'equal original'
            )
        fills = self.fills + (fill,)
        exhausted = sum(f.quantity for f in fills) >= self.original_quantity
        state = OrderState.FILLED if exhausted else OrderState.PARTIALLY_FILLED
        transition = (OrderTransition.FILL if exhausted
                      else OrderTransition.PARTIAL_FILL)
        return replace(self, fills=fills, state=state, updated_at=ts,
                       last_transition=transition)

    def with_encumbrances(
        self,
        encumbrances: Sequence[Encumbrance],
    ) -> 'OrderRecord':
        """A copy holding the given reservations, replacing any it held."""
        return replace(self, encumbrances=tuple(encumbrances))


# --------------------------------------------------------------------------
# Tranches -- locked shape 3
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class HoldingTranche:
    """A parcel of bought shares and the instant it becomes deliverable.

    Locked shape 3. ``unsettled`` is a **list** of these, never a scalar
    ``(quantity, sellable_from)`` pair. Under T+2 up to two tranches are open
    at once, and a single pair forces a wrong choice either way: the earlier
    instant frees the later tranche's shares, permitting exactly the sale the
    settlement rule exists to prevent, or the later instant blocks the earlier
    one, producing a spurious rejection.

    ``settles_at`` is a **datetime**, and it is computed by a
    :class:`SettlementCalendar` resolved through ``rulebook.at(ts)`` -- never
    by counting bars. T+2 is counted in VSDC *settlement* business days, which
    diverge from exchange trading days: VSDC closed settlement 2026-02-16 to
    02-20, so T+2 of a 2026-02-12 trade settled on 02-23. The earlier
    "holiday-correct by construction" claim was wrong (rulebook 9.5).

    The time-of-day half of ``settles_at`` is regime-dependent and is why a
    ``date`` will not do. From 2022-08-29 delivery lands by 13:00 on T+2; from
    2016-01-01 to 2022-08-26 settlement completed after the close and the
    first sellable session was the open of T+3. **On daily bars stamped
    midnight, a 13:00 threshold is not met by the T+2 bar, so the current
    regime behaves as T+3.** That is the conservative direction and it is
    intended -- it is stated here rather than left to emerge from timestamp
    arithmetic, because it is the difference the Tier 1 demo turns on.
    """

    quantity: int
    settles_at: datetime
    acquired_at: datetime
    source_order_id: Optional[OrderId] = None

    def scaled(self, factor: Decimal) -> 'HoldingTranche':
        """A copy with quantity scaled by a corporate-action factor.

        The additive hook of design section 15 item 5, at tranche level: a
        split or bonus issue scales every open tranche without collapsing
        them, so their distinct settlement instants survive the adjustment.
        There is **no corporate-action engine in Tier 1** -- a run spanning an
        ex-date is wrong for that instrument -- and this exists only so the
        engine is not retrofitted into a scalar.

        Fractional results are floored: Vietnamese share quantities are whole
        and the residue is normally paid in cash, which the caller's
        ``cash_per_share`` leg carries.
        """
        return replace(self, quantity=int(Decimal(self.quantity) * factor))


@dataclass(frozen=True)
class ProceedsTranche:
    """A parcel of sale proceeds and the instant it becomes spendable.

    The mirror of :class:`HoldingTranche`, on the same cycle and -- rulebook
    5.1 -- at the same instant: cash and securities settle by DVP at the
    depository and are allocated to the client in a single event. There is no
    version of this where the shares land and the money does not.

    ``amount`` is **net of sell-side charges withheld at source**. The 0.1%
    personal income tax is deducted by the broker on the sale, so a sale
    credits net; carrying gross here and netting later is how a sale ends up
    wrong by more than most commissions.

    ``advanced`` marks the brokerage product *ung truoc tien ban*: when
    :attr:`BrokerTerms.advance_on_sale_enabled` is set, the tranche's amount
    is spendable immediately and accrues ``interest_accrued`` at the daily
    rate until it settles. That is a **broker term, not an exchange rule** --
    it is the clearest illustration of why the two config objects are
    separate. Interest is reported, never netted against anything.
    """

    amount: Decimal
    settles_at: datetime
    accrued_at: datetime
    source_order_id: Optional[OrderId] = None
    advanced: bool = False
    interest_accrued: Decimal = Decimal('0')

    def with_interest(self, additional: Decimal) -> 'ProceedsTranche':
        """A copy with one more period's interest accrued on the advance."""
        return replace(self, interest_accrued=self.interest_accrued + additional)


# --------------------------------------------------------------------------
# Read models -- what session.holdings/cash/positions/margin return
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Holding:
    """One ticker's position in the securities account, as the caller sees it.

    ``sellable`` is derived, never stored: ``settled - committed``, where
    ``committed`` is the quantity already promised to live sell orders.
    Storing it would give the encumbrance ledger and this record two places to
    disagree about the same number.

    ``unsettled`` holds the open tranches in settlement order. **Sells
    encumber quantity from ``settled``, never from ``unsettled``** -- that
    single sentence is the whole T+2 rule as the order path sees it.
    """

    ticker: str
    settled: int
    committed: int
    unsettled: Tuple[HoldingTranche, ...] = ()

    @property
    def sellable(self) -> int:
        """Quantity a new sell order may draw on right now."""
        return self.settled - self.committed

    @property
    def unsettled_quantity(self) -> int:
        """Total quantity across open tranches. Not sellable."""
        return sum(t.quantity for t in self.unsettled)

    @property
    def total(self) -> int:
        """Everything owned, settled or not. The caller's economic position."""
        return self.settled + self.unsettled_quantity

    def is_sellable_now(self, quantity: int) -> bool:
        """Whether ``quantity`` can be sold at this instant."""
        return quantity <= self.sellable

    def sellable_from(self, quantity: int) -> Optional[datetime]:
        """The earliest instant at which ``quantity`` becomes sellable.

        Design section 7.1: ``sellable_from`` is **not stored**, because it is
        a function of the quantity *requested*. 500 shares may be sellable
        tomorrow and 1,000 only the day after, and no single stored instant is
        right for both. The walk is over tranches in settlement order until
        the cumulative quantity covers the shortfall.

        This is the value attached to ``Rejected(UNSETTLED_HOLDING)``, and
        that rejection is the feature people will notice first.

        Returns:
            The settlement instant of the tranche that covers the request, or
            ``None`` when the request exceeds everything held -- which is a
            different answer from "later", and the caller must not render it
            as one. Check :meth:`is_sellable_now` first: a quantity already
            sellable also returns a tranche instant or ``None``, and neither
            means what it says in that case.
        """
        shortfall = quantity - self.sellable
        if shortfall <= 0:
            return None
        for tranche in sorted(self.unsettled, key=lambda t: t.settles_at):
            shortfall -= tranche.quantity
            if shortfall <= 0:
                return tranche.settles_at
        return None


@dataclass(frozen=True)
class Cash:
    """The securities-account cash position, as the caller sees it.

    ``available`` is derived from the three stored terms, per design section
    7.0::

        available = settled_balance + advanced - committed

    Section 5 names the field ``advanced`` and section 7.0's formula calls the
    same quantity ``advanced_proceeds``. This contract settles on
    ``advanced``, the field name, and states the identity here so the two
    readings cannot diverge.

    ``committed`` is the sum of encumbrance over live buy orders -- including
    their estimated charges, so ``available`` stays consistent with what a
    fill will actually cost.

    ``pending_proceeds`` are **not** in ``available`` unless advanced. Equity
    requires 100% pre-funding, so a buy is ``Rejected(INSUFFICIENT_CASH)``
    when available cash is short *even if pending proceeds would cover it*.
    Rulebook 5.1 is blunt about the consequence: sell-then-rebuy on the same
    day is not possible on settled cash alone.

    ``interest_accrued`` is reported and never netted against anything. The
    caller decides what to do with it (design section 3: Plutus debits
    charges and reports them, it never nets them into a return).
    """

    settled_balance: Decimal
    committed: Decimal
    advanced: Decimal = Decimal('0')
    interest_accrued: Decimal = Decimal('0')
    pending_proceeds: Tuple[ProceedsTranche, ...] = ()

    @property
    def available(self) -> Decimal:
        """Spendable cash, net of live buy orders. The pre-funding test."""
        return self.settled_balance + self.advanced - self.committed

    @property
    def pending_total(self) -> Decimal:
        """Sale proceeds not yet settled. Spendable only if advanced."""
        return sum((t.amount for t in self.pending_proceeds), Decimal('0'))


@dataclass(frozen=True)
class ContractPosition:
    """One derivatives contract's net position. Locked shape 5.

    ``net_quantity`` is **signed**: positive is long, negative is short, and a
    flat position is not stored at all -- ``ContractLedger`` removes the row
    rather than keeping a zero, so ``positions()`` never shows a contract the
    account does not hold.

    Deliberately not :class:`plutus.market.protocol.Position`, which is
    unsigned with a separate ``side``. An unsigned row cannot net: a long and
    a short in the same contract on the same account are one position to VSDC,
    and rulebook 6.3 is explicit that offsetting trades on the same trading
    account attract no new initial margin. Per-position rows are the forbidden
    build.

    This is also where **shorts** live, and only here. A SELL on an HNXDS
    symbol opens or increases a short and is never checked against holdings; a
    SELL on an equity venue requires settled holdings, because Vietnamese cash
    equity permits no short selling.
    """

    contract_code: str
    net_quantity: int
    average_entry: Decimal
    multiplier: Decimal
    expiry: Optional[date] = None
    opened_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def is_flat(self) -> bool:
        return self.net_quantity == 0

    @property
    def is_long(self) -> bool:
        return self.net_quantity > 0

    @property
    def is_short(self) -> bool:
        return self.net_quantity < 0

    @property
    def abs_quantity(self) -> int:
        """Contracts held either way. What a position limit is tested against.

        Rulebook 6.4: the statutory limit is a maximum **net** position, so
        the comparison is against this magnitude, not against gross turnover.
        """
        return abs(self.net_quantity)

    def notional(self, price: Decimal) -> Decimal:
        """Absolute notional at ``price``: ``|net| x multiplier x price``.

        Unsigned, because a margin requirement is a magnitude. Direction
        enters through variation margin, which is loss-only.
        """
        return Decimal(self.abs_quantity) * self.multiplier * price


@dataclass(frozen=True)
class MarginView:
    """The whole derivatives account's margin position at one instant.

    A **session-level aggregate**, deliberately a different type from the
    per-position :class:`plutus.market.margin.MarginState`, which it wraps and
    aggregates. ``MarginState`` models a maintenance ratio Vietnam does not
    publish; this models the test Vietnam actually runs.

    The test, from rulebook 6.3::

        MR          = IM + VM              over the WHOLE account portfolio
                      IM = initial requirement recomputed on the CURRENT
                           price (last match in-session, DSP end of day) --
                           not on entry notional
                      VM = variation margin, counted ONLY when the account is
                           in loss; a favourable move contributes zero
        assets      = deposit_balance      cash-settled, so daily P&L leaves
                                           or enters as cash on T+1 and the
                                           deposit does NOT accumulate MTM
        utilisation = MR / assets          warning >= 0.80, call >= 0.90,
                                           forced >= 1.00

    ``required``, ``free_deposit``, ``utilisation`` and ``equity`` are all
    derived from the stored terms, so the identity cannot be violated by a
    caller assembling the record by hand.

    ``equity`` is defined here as ``deposit_balance - required``: the amount
    by which margin assets exceed the requirement, negative when the account
    is short. Design section 5 lists ``equity`` on this view without defining
    it, and this is an **adopted definition, not a sourced one** -- it is the
    reading consistent with "assets = deposit_balance" and with the deposit
    not accumulating MTM.

    ``utilisation`` is ``None``, never ``NaN``, when assets are zero.
    ``json_safe`` raises ``ValueError`` on a non-finite Decimal, so a NaN here
    would blow up at ``to_dict()`` time rather than at construction.

    ``as_of`` is the instant the view was *taken*, and on its own it asserts a
    currency the numbers may not have: every figure here is computed from a
    price, and a price can be older than ``as_of`` by any number of sessions.
    ``stale_marks`` is what closes that gap -- it names every held contract
    whose mark predates this session, and when it is non-empty ``status`` is
    :attr:`MarginStatus.INDETERMINATE` rather than a rung nobody measured.
    """

    initial_margin: Decimal
    variation_margin: Decimal
    deposit_balance: Decimal
    posted_margin: Decimal
    resting_order_margin: Decimal
    status: MarginStatus
    as_of: datetime
    cure_by: Optional[datetime] = None
    stale_marks: Tuple[str, ...] = ()
    """Held contracts whose price is older than ``as_of``'s session, sorted.

    Empty is the ordinary case and means every figure on this view rests on a
    price observed in the session it claims. Non-empty is design section 9's
    "``settlement_price`` absent" and forces ``status`` to
    ``INDETERMINATE``: the requirement is still arithmetic, but it is
    arithmetic on a price from another day.
    """

    @property
    def is_indeterminate(self) -> bool:
        """Whether the data could not decide this account's ladder position."""
        return self.status is MarginStatus.INDETERMINATE

    @property
    def required(self) -> Decimal:
        """MR = IM + VM, over the whole account portfolio."""
        return self.initial_margin + self.variation_margin

    @property
    def free_deposit(self) -> Decimal:
        """``balance - posted - resting-order margin``. Section 7.0.

        **Not the withdrawable amount**, and the difference is exactly ``VM``.
        This is the pre-funding figure a *new order* is tested against -- the
        deposit not already backing a position or a resting order. Rulebook
        6.3 puts the withdrawal test at assets minus ``MR`` at the broker's
        threshold, which is :attr:`equity` when that threshold is 1.00; see
        :meth:`~plutus.market.session.deposit.DerivativesAccount.transfer_out`,
        which is bounded by that and not by this.
        """
        return (self.deposit_balance - self.posted_margin
                - self.resting_order_margin)

    @property
    def utilisation(self) -> Optional[Decimal]:
        """``MR / assets``, or ``None`` when there are no margin assets."""
        if self.deposit_balance <= 0:
            return None
        return self.required / self.deposit_balance

    @property
    def equity(self) -> Decimal:
        """Margin assets less the requirement. See the class docstring."""
        return self.deposit_balance - self.required


# --------------------------------------------------------------------------
# Account identity
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class AccountRef:
    """Names one of the two pools of one account.

    The two are segregated in Vietnamese law, not merely partitioned in this
    simulator: derivatives margin sits in a deposit account ("ky quy") opened
    by the clearing member, funded only by an explicit transfer out of the
    securities account, and with its own purchasing power. **There is no
    auto-transfer.** A margin call resolves against the deposit only; if the
    deposit is short the futures position is force-liquidated and securities
    cash is untouched.

    ``venue_scope`` records which venues draw on this pool, so the sell-path
    branch of section 7.3 -- holdings check on an equity venue, short on
    HNXDS -- reads off the account rather than off a hard-coded venue list.
    """

    account_no: str
    pool: Pool
    venue_scope: FrozenSet[Venue]

    @classmethod
    def securities(cls, account_no: str) -> 'AccountRef':
        """The cash-equity side: HSX, HNX and UPCoM draw on it."""
        return cls(account_no=account_no, pool=Pool.SECURITIES,
                   venue_scope=frozenset(
                       v for v in Venue if pool_for_venue(v) is Pool.SECURITIES))

    @classmethod
    def derivatives(cls, account_no: str) -> 'AccountRef':
        """The segregated deposit: HNXDS only."""
        return cls(account_no=account_no, pool=Pool.DERIVATIVES,
                   venue_scope=frozenset(
                       v for v in Venue if pool_for_venue(v) is Pool.DERIVATIVES))

    def serves(self, venue: Venue) -> bool:
        """Whether an order on ``venue`` draws on this pool."""
        return venue in self.venue_scope


# --------------------------------------------------------------------------
# Call-and-response results
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Accepted:
    """``submit()`` succeeded: the order has an id and holds its reservation."""

    order_id: OrderId
    ts: datetime
    venue: Venue
    encumbrances: Tuple[Encumbrance, ...] = ()
    state: OrderState = OrderState.ACCEPTED


@dataclass(frozen=True)
class Rejected:
    """A submission, cancellation or transfer was refused, naming the rule.

    ``Rejected`` always carries the **rule** that refused it, never a string.
    ``AdmissionRule`` (with :class:`StatefulRule` merged in) *is* the
    rejected-order log, and a log keyed on prose cannot be counted.

    ``verdict`` distinguishes the two ways an order fails to be admitted.
    ``REJECTED`` means a rule said no. ``INDETERMINATE`` means the data needed
    to judge a rule was absent -- ``Admissibility.admitted`` is already False
    for it, since absence of evidence is not evidence of admissibility. Both
    keep the order out of the book, so section 12's graph is unchanged, but
    conflating them would let a data gap be reported as a market rule and
    would corrupt the rejection-rate figures the paper rests on.
    :class:`IndeterminateReport` counts the second kind.

    What ``binding_constraint`` holds, by rule -- **the number that bound**,
    the same convention the six existing rules already follow:

    ==========================  ====================================
    rule                        binding_constraint
    ==========================  ====================================
    ``TICK_GRID``               the tick size
    ``ROUND_LOT``               the round lot in force
    ``BAND_LIMIT``              the ceiling or floor breached
    ``BAND_LOCK``               ceiling (buy) / floor (sell)
    ``FOREIGN_ROOM``            remaining room, an int
    ``SESSION_SEMANTICS``       ``None``; see ``detail['phase']``
    ``UNSETTLED_HOLDING``       sellable quantity available, an int
    ``INSUFFICIENT_CASH``       ``Cash.available``
    ``INSUFFICIENT_DEPOSIT``    ``free_deposit``
    ``POSITION_LIMIT``          the cap, in contracts
    ==========================  ====================================

    ``sellable_from`` is a separate field rather than the binding constraint
    because it is a *different quantity* from the one that bound: the
    constraint is how many shares were available, and this is when the
    requested quantity becomes available. It is set only for
    ``UNSETTLED_HOLDING``. The Tier 1 demo is exactly this object -- buy FPT,
    try to sell it the same session, read ``sellable_from``.
    """

    rule: RejectionRule
    binding_constraint: Optional[Union[Decimal, int]]
    ts: datetime
    verdict: Verdict = Verdict.REJECTED
    order_id: Optional[OrderId] = None
    sellable_from: Optional[datetime] = None
    regime_tag: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_admissibility(cls, adm: Admissibility,
                           order_id: Optional[OrderId] = None) -> 'Rejected':
        """Lift an ``Exchange.admits()`` verdict into a session rejection.

        Carries ``regime_tag`` through, which matters because
        ``_admits_in_session`` builds its six SESSION_SEMANTICS verdicts
        directly and never receives one -- those arrive with ``regime_tag``
        already ``None``, and the session must stamp its own rather than
        assume the exchange did.

        Raises:
            ValueError: if the verdict is ``ADMITTED``. An admitted order is
                not a rejection and silently producing one would put a
                phantom row in the rejection log.
        """
        if adm.verdict is Verdict.ADMITTED:
            raise ValueError(
                'cannot build a Rejected from an ADMITTED Admissibility')
        return cls(
            rule=adm.rule, binding_constraint=adm.binding_constraint,
            ts=adm.ts, verdict=adm.verdict, order_id=order_id,
            regime_tag=adm.regime_tag, detail=dict(adm.detail),
        )

    @property
    def is_indeterminate(self) -> bool:
        """True when the rule could not be evaluated, rather than failed."""
        return self.verdict is Verdict.INDETERMINATE

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe. Note ``Decimal`` becomes ``float`` -- logging only."""
        return _serialise(asdict(self))


@dataclass(frozen=True)
class Cancelled:
    """``cancel()`` succeeded. Any partial fill already done is reported."""

    order_id: OrderId
    ts: datetime
    cancelled_quantity: int
    filled_quantity: int


@dataclass(frozen=True)
class Amended:
    """``amend()`` succeeded. **Tier 2**; the shape is fixed here only.

    ``priority_preserved`` records the rule that decides whether the amended
    order keeps its place in the queue: priority survives a pure **quantity
    decrease** and restarts on a quantity increase or any price change. From
    2025-05-05 one amendment may change price **or** quantity, never both --
    a dated rule, so ``rulebook.at(ts)`` decides whether a both-at-once
    amendment is legal, not a constant.
    """

    order_id: OrderId
    ts: datetime
    quantity: int
    limit_price: Optional[Decimal]
    priority_preserved: bool


@dataclass(frozen=True)
class Transferred:
    """``transfer()`` succeeded, moving cash between the two pools.

    Bounded by the **net** figures in both directions: out of securities by
    ``Cash.available``, out of the deposit by ``free_deposit``. A transfer
    arrives **immediately** during trading hours -- an adopted assumption,
    stated in design section 16, and intra-day transfer timing is not
    modelled.
    """

    source: Pool
    destination: Pool
    amount: Decimal
    ts: datetime


# --------------------------------------------------------------------------
# The event cursor
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Event:
    """One thing that happened, on the session's single destructive cursor.

    **One tagged record, not twelve classes.** ``advance_to()`` and ``poll()``
    both return ``list[Event]`` off one cursor, and a homogeneous list is what
    lets the caller drain it, dedupe it and switch on ``kind`` without an
    ``isinstance`` ladder. Build events through the classmethods below; the
    optional payload fields are populated per kind and reading one that does
    not apply gives ``None``, not a wrong number.

    **The cursor is destructive and single-consumer.** ``advance_to()``
    returns the events it generated *and* consumes them; ``poll()`` drains
    anything since the last read of either. A strategy and a separate logger
    cannot both drain it, which is acceptable because all reporting is on the
    caller's side.

    ``seq`` is a session-monotonic ordinal. It exists because
    :attr:`dedupe_key` is not unique on its own: two partial fills of the same
    order in the same interval share ``(order_id, kind, ts)``, especially on
    daily bars where every event in a day carries the same midnight timestamp.
    Use ``dedupe_key`` for the caller-facing dedupe design section 5 promises;
    use ``seq`` for a total order.
    """

    kind: EventKind
    ts: datetime
    seq: int
    order_id: Optional[OrderId] = None
    ticker: Optional[str] = None
    venue: Optional[Venue] = None
    pool: Optional[Pool] = None
    quantity: Optional[int] = None
    price: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    rule: Optional[RejectionRule] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> Tuple[Optional[OrderId], EventKind, datetime]:
        """``(order_id, transition, ts)`` -- the triple section 5 promises.

        ``kind`` is this contract's name for section 5's ``transition``; the
        two are the same field. See ``seq`` in the class docstring for why
        this key is not by itself unique.
        """
        return (self.order_id, self.kind, self.ts)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe. ``Decimal`` becomes ``float`` -- never round-trip a price."""
        return _serialise(asdict(self))

    # -- constructors, one per family -----------------------------------

    @classmethod
    def for_order(
        cls,
        kind: EventKind,
        record: OrderRecord,
        ts: datetime,
        seq: int,
        **detail: Any,
    ) -> 'Event':
        """An order-lifecycle event, taking its identity from the record."""
        return cls(kind=kind, ts=ts, seq=seq, order_id=record.order_id,
                   ticker=record.order.ticker, venue=record.venue,
                   pool=pool_for_venue(record.venue),
                   quantity=record.remaining_quantity, detail=dict(detail))

    @classmethod
    def for_fill(cls, record: OrderRecord, fill: Fill, seq: int) -> 'Event':
        """``FILLED`` or ``PARTIALLY_FILLED``, chosen by what remains.

        The kind is computed from the record *after* the fill is applied, for
        the same reason ``OrderRecord.with_fill`` computes the state: a fill
        that exhausts the remainder is a ``FILLED`` whatever its size.
        """
        kind = (EventKind.FILLED if record.remaining_quantity <= 0
                else EventKind.PARTIALLY_FILLED)
        return cls(kind=kind, ts=fill.ts, seq=seq, order_id=record.order_id,
                   ticker=fill.ticker, venue=fill.venue,
                   pool=pool_for_venue(fill.venue), quantity=fill.quantity,
                   price=fill.price,
                   detail={'fill_id': fill.fill_id,
                           'evidence': fill.evidence,
                           'confidence': fill.confidence,
                           'remaining': record.remaining_quantity})

    @classmethod
    def rejected(cls, rejection: Rejected, seq: int,
                 ticker: Optional[str] = None) -> 'Event':
        """A refusal, carrying the rule and the constraint that bound."""
        return cls(kind=EventKind.REJECTED, ts=rejection.ts, seq=seq,
                   order_id=rejection.order_id, ticker=ticker,
                   rule=rejection.rule,
                   detail={'verdict': rejection.verdict,
                           'binding_constraint': rejection.binding_constraint,
                           'sellable_from': rejection.sellable_from,
                           **rejection.detail})

    @classmethod
    def indeterminate(
        cls,
        record: OrderRecord,
        decision: FillDecision,
        ts: datetime,
        seq: int,
    ) -> 'Event':
        """The fill policy could not decide. **The order stays ``RESTING``.**

        Not a state change and not a rejection; the order is re-evaluated on
        the next interval. The named missing fields are what design section
        9.2 requires and what :class:`IndeterminateReport` counts.
        """
        return cls(kind=EventKind.INDETERMINATE, ts=ts, seq=seq,
                   order_id=record.order_id, ticker=record.order.ticker,
                   venue=record.venue,
                   detail={'reason': decision.reason,
                           'missing': sorted(f.value for f in decision.missing)})

    @classmethod
    def margin(
        cls,
        kind: EventKind,
        view: MarginView,
        seq: int,
        **detail: Any,
    ) -> 'Event':
        """A ``MARGIN_WARNING``, ``MARGIN_CALL`` or ``FORCED_LIQUIDATION``.

        A ``FORCED_LIQUIDATION`` must additionally state, in ``detail``, its
        **selection rule** (:class:`LiquidationRule`), the contracts closed,
        the price used and the resulting deposit balance. Design section 7.4
        requires all four; without them the event names an outcome without
        naming the mechanism that produced it.
        """
        return cls(kind=kind, ts=view.as_of, seq=seq, pool=Pool.DERIVATIVES,
                   amount=view.required,
                   detail={'utilisation': view.utilisation,
                           'deposit_balance': view.deposit_balance,
                           'initial_margin': view.initial_margin,
                           'variation_margin': view.variation_margin,
                           'status': view.status,
                           'cure_by': view.cure_by, **detail})

    @classmethod
    def settlement_credited(
        cls,
        ts: datetime,
        seq: int,
        *,
        ticker: Optional[str] = None,
        quantity: Optional[int] = None,
        amount: Optional[Decimal] = None,
        source_order_id: Optional[OrderId] = None,
    ) -> 'Event':
        """A tranche reached its settlement instant and became usable.

        One event covers both legs because they are one allocation event: DVP
        at the depository means securities transfer if and only if the cash
        leg settles, and the broker allocates both to the client in a single
        action. A holdings tranche carries ``quantity``; a proceeds tranche
        carries ``amount``.
        """
        return cls(kind=EventKind.SETTLEMENT_CREDITED, ts=ts, seq=seq,
                   order_id=source_order_id, ticker=ticker,
                   pool=Pool.SECURITIES, quantity=quantity, amount=amount)

    @classmethod
    def expiry_settled(
        cls,
        contract_code: str,
        ts: datetime,
        seq: int,
        *,
        settlement: Decimal,
        cash_flow: Decimal,
        quantity: int,
        **detail: Any,
    ) -> 'Event':
        """A futures contract expired: cash moves and the ledger row goes.

        The final settlement price is the data source's **close on the
        expiring contract's expiry day** -- a declared simplification, not the
        published rule. The exchange publishes an average over the 14:15-14:45
        window; on VN30F2206's 2022-06-16 expiry the window mean was 1281.36
        against a close of 1286.00, so the close overstates by 0.36%. That is
        one contract, and the settlement *basis* itself changed mid-corpus:
        the averaged subject was the contract's own price to 2022-08-16 and
        the VN30 index from 2022-08-17. **Do not report a pre-2022-08-17
        settlement figure as authoritative.**
        """
        return cls(kind=EventKind.EXPIRY_SETTLED, ts=ts, seq=seq,
                   ticker=contract_code, venue=Venue.HNXDS,
                   pool=Pool.DERIVATIVES, quantity=quantity,
                   price=settlement, amount=cash_flow, detail=dict(detail))


# --------------------------------------------------------------------------
# The data-source contract
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class MarketInterval:
    """What the market did over one interval, for one instrument.

    Distinct from :class:`plutus.market.protocol.MarketState`, which is a
    snapshot at an instant. A fill policy asks a question a snapshot cannot
    answer -- did the market trade *through* this limit, and on what volume --
    so section 8's protocol takes an interval.

    ``state`` is carried whole rather than unpacked: the band, the lock and
    its evidence, the session phase and the foreign room all live there
    already, and copying them here would create a second copy that can drift.
    Read them as ``interval.state.ceiling`` and so on.

    ``missing`` names the fields this interval could not supply, which is how
    design section 9.2's "**nothing silently defaults**" is enforced rather
    than hoped for. Both shipped adapters leave ``volume`` unsupplied and
    ``BookLevel.size`` ``None`` on every corpus here, so ``VOLUME`` and
    ``BOOK_SIZE`` are the members that will actually appear.

    ``end`` is **exclusive**, matching the existing
    ``MarketDataSource.states()`` convention.
    """

    ticker: str
    start: datetime
    end: datetime
    resolution: Resolution
    state: MarketState
    open: Optional[Decimal] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    close: Optional[Decimal] = None
    volume: Optional[int] = None
    book: Optional[OrderBook] = None
    settlement_price: Optional[Decimal] = None
    missing: FrozenSet[DataField] = frozenset()

    @property
    def session(self) -> SessionPhase:
        """The phase, from ``state``. **Never inferred from a timestamp.**

        A daily bar's ``ts`` is midnight and ``before_trading_session``
        reports ``is_current()`` True at midnight, so inference marks every
        daily bar pre-open and rejects an entire daily measurement. Design
        section 9 calls the phase "derivable from ts"; ``protocol.py`` says
        never to derive it, and ``protocol.py`` wins.
        """
        return self.state.session

    @property
    def traded(self) -> bool:
        """Whether any price is known for this interval at all."""
        return self.close is not None or self.state.last is not None

    def lacks(self, field_: DataField) -> bool:
        """Whether a named field is absent, so a policy can say which."""
        return field_ in self.missing


# --------------------------------------------------------------------------
# Dated rules and their provenance
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleCitation:
    """Where a dated rule comes from, and how well it is sourced.

    Design section 6.4: "Every value in the rulebook must be traceable to a
    HOSE/HNX/VSD/MoF document with an effective date. That traceability is the
    rulebook's whole claim, and it is why broker terms must not live here."
    Making the citation a field rather than a comment is what makes that claim
    checkable -- ``rulebook.py`` can refuse to serve a value that has none.

    ``document`` should be the identifier as it is actually issued. Note that
    the VSD initial-margin steps were issued as *thong bao* (notices) under a
    standing delegation, **not** as numbered *quyet dinh*: citing "Quyet dinh
    XX/QD-VSD set margin to 17%" cites a document that does not exist.

    ``effective_to`` is ``None`` for a rule still in force.
    ``effective_from`` is ``None`` only for broker terms, which have no
    gazetted start; ``rulebook.py`` rejects an exchange-side rule without one.
    """

    document: str
    effective_from: Optional[date]
    confidence: Confidence
    article: Optional[str] = None
    effective_to: Optional[date] = None
    note: Optional[str] = None

    def covers(self, on: date) -> bool:
        """Whether this citation's interval contains ``on``."""
        if self.effective_from is not None and on < self.effective_from:
            return False
        if self.effective_to is not None and on > self.effective_to:
            return False
        return True


@dataclass(frozen=True)
class SettlementRule:
    """The settlement cycle in force, as a rule the calendar can apply.

    Two independent components, and conflating them is the mistake rulebook
    9.5 corrects in the design spec:

    * ``cycle_days`` -- N in T+N, counted in **VSDC settlement business days**,
      not exchange trading days. This has been 2 since 2016-01-01, not since
      2022-08-29.
    * ``delivery_time`` -- the time of day on T+N at which the client can use
      the delivery. **This is what changed on 2022-08-29**, from after the
      close to 13:00, and it is why ``settles_at`` must be a datetime.

    The two dated regimes inside the coverage window::

        2016-01-01 .. 2022-08-26   T+2, settlement completed 15:30-16:00 on
                                   T+2 -- after the close -- so the first
                                   sellable session was the open of T+3
        2022-08-29 .. current      T+2, client allocation no later than 13:00
                                   on T+2; sellable in the afternoon session

    Note the current regime has *two* instants, and the design spec conflated
    them: depository settlement runs 11:00-11:30 on T+2, while the 13:00
    figure is the **custodian member's allocation deadline** to the client.
    13:00 is the one that governs what a client can do, so it is the one
    modelled here -- and it is a regulatory backstop rather than a guarantee.
    Allocation has been observed up to ~2 hours late (2026-02-27).

    ``delivery_time`` for the pre-2022 regime is expressed as the *next
    session's open* rather than an after-close time, because "sellable at the
    open of T+3" is the behaviour and encoding it as 16:00 on T+2 would make a
    T+2 afternoon sale look legal.
    """

    cycle_days: int
    delivery_time: time
    delivery_on_next_session_open: bool
    citation: RuleCitation

    @property
    def label(self) -> str:
        """A short regime name for provenance and test ids.

        Never ``"T+1.5"``. That term appears in retail press and broker
        marketing and in **no** gazetted document -- checked against Decision
        109/QD-VSD, Circular 119/2020/TT-BTC and Circular 120/2020/TT-BTC. The
        2022-08-29 regime is "T+2 with mid-day settlement".
        """
        if self.delivery_on_next_session_open:
            return f'T+{self.cycle_days} at next session open'
        return f'T+{self.cycle_days} at {self.delivery_time.isoformat()}'


@dataclass(frozen=True)
class Pin:
    """A counterfactual override of a rulebook value.

    Legal, and the mechanism by which a post-KRX rulebook can be run against
    pre-KRX data as a control. Every pin is recorded as an override in
    :class:`SessionProvenance`, which is the difference between a
    counterfactual and a lie: a pinned run reports that it was pinned.

    ``path`` is a dotted key under ``exchange_rules``, e.g.
    ``'settlement.cycle_days'``.
    """

    path: str
    value: Any
    reason: Optional[str] = None


@dataclass(frozen=True)
class SessionProvenance:
    """What a run was configured with, for the record attached to its results.

    Design section 6.3 requires pins to be recorded as overrides; section 9.2
    requires the session to state which resolution mode it is running in;
    section 3 requires the no-impact and policy assumptions to be stated in
    every published result. This record is where a caller gets all of it in
    one object rather than reconstructing it from the config file.
    """

    rulebook_id: str
    resolution: Resolution
    period_start: date
    period_end: date
    venues: Tuple[Venue, ...]
    fill_policy_kind: str
    broker_profile_name: str
    pins: Tuple[Pin, ...] = ()
    settlement_calendar_id: Optional[str] = None
    liquidation_rule: LiquidationRule = LiquidationRule.LARGEST_LOSS_FIRST

    @property
    def is_counterfactual(self) -> bool:
        """True when any rulebook value was pinned away from its dated one."""
        return bool(self.pins)


@dataclass(frozen=True)
class IndeterminateReport:
    """How much of a run the data could not decide.

    Design section 9.2 requires the session to report this rate, and section 8
    makes it the product's honest headline: "the share of results resting on
    ``INDETERMINATE`` fills is a direct measure of how much of a backtest is
    unknowable". It is a bound on ignorance, not a fill rate.

    ``by_field`` counts against :class:`DataField`, which is why that enum
    exists rather than free-form reason strings.

    An *evaluation* is any question the session put to the data and had to get
    an answer to before it could act. That is fill evaluations, and it is also
    the derivatives mark: design section 9 lists ``settlement_price`` in the
    same table as ``volume`` and ``foreign_room``, with "absent => margin marks
    ``INDETERMINATE``", so a mark the data could not supply is the same kind of
    ignorance and is counted the same way -- under
    :attr:`DataField.SETTLEMENT_PRICE`. Leaving it out was how eleven
    unmarked sessions could report ``indeterminate=0``.
    """

    evaluations: int
    indeterminate: int
    by_field: Mapping[DataField, int] = field(default_factory=dict)
    by_rule: Mapping[str, int] = field(default_factory=dict)

    @property
    def rate(self) -> Optional[Decimal]:
        """Indeterminate share of evaluations, or ``None`` if none were made."""
        if self.evaluations <= 0:
            return None
        return Decimal(self.indeterminate) / Decimal(self.evaluations)


# --------------------------------------------------------------------------
# Charges -- one generic table, per venue
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ChargeRule:
    """One row of the charge table: a charge that *may* apply.

    Charges are modelled because they move cash and therefore change
    admission outcomes, and every venue has a different schedule -- so this is
    a table, not a pair of constants. The shape is forced by the rules
    themselves, not by taste. Three rows no per-trade constant can express:

    * The **0.1% personal income tax** on a securities transfer is sell-side
      only and withheld at source, so a sale credits cash net.
    * The **VSD position maintenance fee** accrues per open contract per
      account per **day** (:attr:`ChargeBase.PER_OPEN_CONTRACT_PER_DAY`).
    * **Custody** is monthly per security
      (:attr:`ChargeBase.MONTHLY_PER_SECURITY`).

    Exactly one of ``rate`` and ``amount`` is set. ``rate`` is a Decimal
    fraction of the base -- ``Decimal('0.001')``, never a percent string.
    ``amount`` is absolute VND -- ``2700``, never thousand-VND.

    Rows with ``levied_by`` of ``STATE``, ``EXCHANGE`` or ``VSD`` belong in
    the dated rulebook and must carry a ``citation``; ``BROKER`` rows belong
    in :class:`BrokerProfile` and need none.

    Two declared Tier 1 gaps, both from rulebook 12: **rounding is
    UNVERIFIED** for every charge -- no source states a rule, so rounding to
    whole dong is a modelling choice and must be reported as one -- and
    **tiered broker commissions are not modelled**. A commission that tiers on
    the day's total traded value per account is not knowable at fill time,
    which is what ``DebitedAt.DAILY`` exists to express; the tier table itself
    is Tier 2.

    ``vat_applies`` is a per-charge boolean because the source material
    conflicts: prices were VAT-exempt to 2025-04-28 and VAT-exclusive from
    2025-04-29, yet brokers demonstrably billed VSDC derivatives charges
    grossed up 10% during the exemption. Default off, and the conflict is
    noted rather than resolved.
    """

    charge_id: str
    base: ChargeBase
    side: ChargeSide
    levied_by: LeviedBy
    debited_at: DebitedAt
    pool: Pool
    applies_to: FrozenSet[ChargeClass]
    venue: Optional[Venue] = None          # None means every venue
    rate: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    minimum: Optional[Decimal] = None
    maximum: Optional[Decimal] = None
    citation: Optional[RuleCitation] = None
    vat_applies: bool = False
    vat_rate: Decimal = Decimal('0.10')

    def applies(self, venue: Venue, cls_: ChargeClass, side: Side) -> bool:
        """Whether this row bites for a given venue, instrument class and side."""
        if self.venue is not None and self.venue is not venue:
            return False
        if cls_ not in self.applies_to:
            return False
        if self.side is ChargeSide.BOTH:
            return True
        if self.side is ChargeSide.NONE:
            return False
        want = ChargeSide.BUY if side is Side.BUY else ChargeSide.SELL
        return self.side is want


@dataclass(frozen=True)
class Charge:
    """A charge actually levied: what ``session.charges()`` itemises.

    Distinct from :class:`ChargeRule`, which is the row in the table that
    produced it. Design section 6.1 names both "Charge"; keeping them apart is
    the difference between "brokers charge 0.15%" and "you were charged
    225,000 dong on 2022-03-14".

    ``base_value`` is the quantity the rate was applied to, kept so an
    itemised charge can be checked without re-deriving the trade. ``kind`` is
    the originating :attr:`ChargeRule.charge_id`.
    """

    kind: str
    venue: Venue
    base: ChargeBase
    base_value: Decimal
    amount: Decimal
    levied_by: LeviedBy
    pool: Pool
    ts: datetime
    ticker: Optional[str] = None
    order_id: Optional[OrderId] = None
    fill_id: Optional[FillId] = None
    vat: Decimal = Decimal('0')

    @property
    def total(self) -> Decimal:
        """Charge plus VAT, which is what actually leaves the account."""
        return self.amount + self.vat


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

#: Config key to :class:`BrokerTerms` field. The mapping layer design section
#: 6 needs and does not name, written once here so three modules cannot each
#: invent their own.
#:
#: ``margin_buffer`` is the odd one out: it has **no** ``BrokerTerms`` field.
#: It is a percentage-of-notional add-on above the VSD initial rate, and it
#: lives on :class:`BrokerProfile` directly. Rulebook 6.3 is worth reading
#: before leaning on it: the add-on is a plausible *shape*, but "the broker's
#: actual lever in Vietnam is its UTILISATION thresholds (75/85/90 style)",
#: which the example config does not expose at all -- so a caller wanting to
#: model a real broker sets the three utilisation fields, not this.
BROKER_CONFIG_KEYS: Mapping[str, str] = {
    'margin_cure_window': 'cure_window_sessions',
    'advance_sale_proceeds.enabled': 'advance_on_sale_enabled',
    'advance_sale_proceeds.daily_rate': 'advance_on_sale_daily_rate',
    'warning_utilisation': 'warning_utilisation',
    'margin_call_utilisation': 'margin_call_utilisation',
    'forced_close_utilisation': 'forced_close_utilisation',
}

#: How ``margin_cure_window``'s string form maps to a session count.
_CURE_WINDOWS: Mapping[str, int] = {
    'same_session': CureWindow.SAME_SESSION,
    'next_session': CureWindow.NEXT_SESSION,
}


@dataclass(frozen=True)
class BrokerProfile:
    """The commercial half of the rulebook, for one securities company.

    Exchange rules are gazetted, dated and identical for everyone. Broker
    terms are commercial, differ by firm and change at will. Conflating them
    is how a simulator ends up asserting a house rule as market law -- which
    is why the sale advance, the cure window and the utilisation ladder's
    *levels* live here while the ladder's *shape* is VSDC-sourced.

    ``terms`` is :class:`plutus.market.broker.BrokerTerms`, reused whole and
    not rebuilt. Read its ``PROVENANCE`` before quoting any default: none of
    them is sourced to a document.
    """

    name: str
    terms: BrokerTerms = BrokerTerms()
    margin_buffer: Decimal = Decimal('0')
    commission: Tuple[ChargeRule, ...] = ()

    @classmethod
    def from_config(cls, payload: Mapping[str, Any]) -> 'BrokerProfile':
        """Build from the ``broker_profile`` object of the session config.

        The config's key names and ``BrokerTerms``' field names differ; see
        :data:`BROKER_CONFIG_KEYS`. ``margin_cure_window`` accepts either the
        string form (``"next_session"``) or an integer count of sessions.

        Raises:
            ValueError: on an unknown ``margin_cure_window`` string, rather
                than defaulting -- a silently-defaulted cure window changes
                when a position is force-closed.
        """
        advance = payload.get('advance_sale_proceeds') or {}
        window = payload.get('margin_cure_window', CureWindow.NEXT_SESSION)
        if isinstance(window, str):
            if window not in _CURE_WINDOWS:
                raise ValueError(
                    f'unknown margin_cure_window {window!r}; expected one of '
                    f'{sorted(_CURE_WINDOWS)} or an integer session count')
            window = _CURE_WINDOWS[window]
        terms = BrokerTerms(
            advance_on_sale_enabled=bool(advance.get('enabled', False)),
            advance_on_sale_daily_rate=Decimal(
                str(advance.get('daily_rate',
                                BrokerTerms.advance_on_sale_daily_rate))),
            cure_window_sessions=int(window),
            **{f: Decimal(str(payload[f])) for f in (
                'warning_utilisation', 'margin_call_utilisation',
                'forced_close_utilisation') if f in payload},
        )
        return cls(
            name=str(payload.get('name', 'unnamed')),
            terms=terms,
            margin_buffer=Decimal(str(payload.get('margin_buffer', 0))),
            commission=tuple(
                _commission_rule(row) for row in payload.get('commission', ())),
        )


def _commission_rule(row: Mapping[str, Any]) -> ChargeRule:
    """One ``broker_profile.commission`` row as a :class:`ChargeRule`.

    Commission rows carry no ``applies_to`` and no ``side``, so they default
    to every instrument class on that venue, both sides, debited at the fill.
    ``debited_at`` is deliberately ``FILL`` and not ``DAILY``: Tier 1 does not
    model tiered commission, and pretending otherwise would produce a daily
    charge computed at a flat rate, which is worse than an honest per-fill one.
    """
    venue = Venue.from_code(row['venue'])
    return ChargeRule(
        charge_id=f'broker.commission.{venue.value.lower()}',
        base=ChargeBase(row['base']),
        side=ChargeSide.BOTH,
        levied_by=LeviedBy.BROKER,
        debited_at=DebitedAt.FILL,
        pool=pool_for_venue(venue),
        applies_to=frozenset(ChargeClass),
        venue=venue,
        rate=Decimal(str(row['rate'])) if 'rate' in row else None,
        amount=Decimal(str(row['amount'])) if 'amount' in row else None,
        minimum=Decimal(str(row['min'])) if 'min' in row else None,
        maximum=Decimal(str(row['max'])) if 'max' in row else None,
    )


@dataclass(frozen=True)
class ExchangeRulesConfig:
    """The ``exchange_rules`` object: which venues, which rulebook, what pinned.

    **The rulebook is resolved per event instant** -- ``rulebook.at(ts)`` --
    not once here. A ``period`` spans regime changes (settlement changed
    inside 2022; KRX changed HOSE inside 2025), so a single scalar version
    cannot be right for a multi-month run. Anything named under this object is
    therefore a *pin*, not a version selection.
    """

    venues: Tuple[Venue, ...]
    rulebook: str = 'vn-2020-2026'
    pins: Tuple[Pin, ...] = ()


@dataclass(frozen=True)
class AccountsConfig:
    """Opening balances for the two segregated pools.

    Two numbers because there are two pools with independent purchasing
    power, and no auto-transfer between them.
    """

    initial_cash: Decimal = Decimal('0')
    initial_deposit: Decimal = Decimal('0')
    securities_account_no: str = 'SEC-0001'
    derivatives_account_no: str = 'DER-0001'


@dataclass(frozen=True)
class FillPolicyConfig:
    """Which fill policy, and its one parameter.

    ``max_participation`` is a fraction of the volume observed in the
    evaluated interval, and it **aggregates across all of the caller's own
    live orders in that instrument** -- not per order, or a caller splits one
    order into ten and evades the cap.
    """

    kind: str = 'soft'
    max_participation: Decimal = Decimal('0.10')
    seed: Optional[int] = None


@dataclass(frozen=True)
class DataConfig:
    """Which adapter serves market data, and from where.

    ``settlement_calendar`` is a path to a VSDC notice in
    :meth:`~plutus.market.session.calendar.VsdcSettlementCalendar.from_file`'s
    schema, and it is the **only** way a config file can stop a run using the
    weekday-only default -- which is wrong around every Tet in the period and
    settles T+2 of a 2026-02-12 trade on 2026-02-16 where VSDC settled
    2026-02-23. ``ExchangeSession.build`` loads it; a named calendar that
    cannot be loaded is an error, not a fall-back, on the same reasoning that
    makes a missing ``period`` a ``KeyError``.
    """

    adapter: str
    root: str
    settlement_calendar: Optional[str] = None


@dataclass(frozen=True)
class SessionConfig:
    """A whole run, parsed. The argument of ``ExchangeSession.from_config``.

    Two config objects, because they are two kinds of fact:
    :class:`ExchangeRulesConfig` is gazetted, dated and citation-bearing;
    :class:`BrokerProfile` is commercial and per-firm.

    ``resolution`` is declared here and by the source, and the session states
    which mode it is running in. It is not cosmetic: on daily bars a T+2
    13:00 delivery behaves as T+3, which is the conservative direction and is
    intended.
    """

    period_start: date
    period_end: date
    resolution: Resolution
    exchange_rules: ExchangeRulesConfig
    broker_profile: BrokerProfile
    accounts: AccountsConfig
    fill_policy: FillPolicyConfig
    data: DataConfig
