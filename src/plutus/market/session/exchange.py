"""The caller-facing session: the clock, the registry, and the one cursor.

This is the module the six others exist for. It owns four things nobody else
may own -- the clock, the exchange registry, symbol routing and the event
cursor -- and it composes the rest without reimplementing any of it. Every
rule in this file is either a *composition* rule (what order the pieces run
in) or a *declared modelling choice*; no dated market value is decided here,
because a second rulebook is exactly the failure the package is built to
avoid.

**What this is.** A simulated Vietnamese exchange a strategy connects to like
a broker API: submit an order, receive its status, read your holdings and your
margin. The exchange remembers settlement, margin and the rulebook so the
strategy author does not have to.

**What this is not.** A backtesting engine. Plutus never calls user code,
holds no portfolio, computes no P&L and reports no returns. The caller owns
all of that; this object is the counterparty.

Three compositions are worth reading before the code.

**The submit sequence is normative** (interface contract section 1): route,
resolve the rulebook at the instant, resolve the phase, ``Exchange.admits()``,
*then* reserve, *then* accept. Step 5 runs **around** ``admits()``, never
inside it -- a stateless affordability check inside ``admits()`` is the
forbidden build of locked shape 2, and inverting steps 4 and 5 changes the
per-rule composition of the rejection log (an order that breaches the tick
grid is a tick-grid rejection whether or not the caller could afford it).

**The dated rules the venue objects cannot see are resolved here.** The four
``exchanges/`` objects are stateless evaluators built on a module-level
``ExchangeSpec`` -- undated by construction -- and they are shared with the
batch research path, so the gap is closed by copying a venue object and dating
the copy rather than by editing them. Order-type legality and the per-order
size cap are refused before ``admits()`` runs; the tick grid is *installed on
the venue object for one call*, so ``admits()`` still owns the ``TICK_GRID``
rule and still runs it first, against a number the rulebook resolved at the
instant for that instrument. A pre-check would have caught only half of that
defect: it would refuse the illegal price and still let the singleton refuse a
legal one.

**That dating lives in ``SymbolRouter.exchange``, not here.** This module
closed the seam inside itself first, which left the router -- public API under
the Tier 1 interface contract -- still returning the import-time judge to
every direct caller, ``ts`` consumed to pick a venue and then discarded. One
mechanism, in the object that owns ``(ticker, ts)``;
:meth:`ExchangeSession._venue_at` and :meth:`ExchangeSession._evaluate_fills`
are both callers of it.

**Expiry runs before fills** inside :meth:`ExchangeSession.advance_to`, or an
order that died at the cross could still fill in the phase that killed it.

**One terminal hook serves both pools.** ``OrderBookOfRecord`` takes
``on_terminal`` at construction and this module wires it to
``SecuritiesAccount.release`` *and* ``DerivativesAccount.release``. Both are
idempotent no-ops for orders they never reserved, so one callback discharges
locked shape 2's "release on EVERY terminal transition" without either ledger
having to know which pool an order belonged to.

Two declared deviations from the literal interface contract, both forced by
things the contract could not see until the modules were written:

* **The session phase on a daily-resolution run.** ``RuleSet.phase(venue)``
  reads the clock, and a daily bar is stamped midnight, so it answers
  ``PRE_OPEN`` for every bar -- which would reject an entire daily
  measurement and lock every cancellation. On ``Resolution.DAILY`` the
  session therefore takes the phase the *adapter asserts on the bar*, and
  where the adapter is silent asserts ``CONTINUOUS`` on a trading day and
  ``POST_CLOSE`` otherwise. That is not inference from a timestamp: it is the
  declared meaning of a daily bar (both shipped adapters already hardcode
  ``CONTINUOUS``), and the **trading calendar** -- not the clock -- decides
  whether the day trades at all. On any other resolution the rulebook wins,
  exactly as the contract says.
* **The immediate order families are decided in** :meth:`advance_to`, not in
  :meth:`submit`. ``orders.py`` deliberately refuses to sweep MOK/MAK at a
  phase boundary because the rulebook gives them no boundary rule, and Tier 1
  has no intra-submit matching engine to decide them at entry. They are
  therefore decided at the first interval that evaluates them, which is one
  bar later than a real exchange decides them and is declared as such.
"""

import importlib
import json
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from datetime import time as _time
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from pathlib import Path
from typing import (
    Any, Dict, FrozenSet, List, Mapping, Optional, Protocol, Sequence, Set,
    Tuple, Union, runtime_checkable,
)

from plutus.core.order import OrderType, Side
from plutus.market.adapters.base import MarketDataSource
from plutus.market.expiry import expiry_date
from plutus.market.exchanges import (
    Exchange, HNXDS_EXCHANGE, HNX_EXCHANGE, HSX_EXCHANGE, UPCOM_EXCHANGE,
)
from plutus.market.protocol import (
    BandSource, InstrumentKind, InstrumentSpec, MarketState, Order, Resolution,
    SessionPhase,
)
from plutus.market.session.calendar import (
    CalendarError, SettlementCalendar, TradingCalendar,
    VsdcSettlementCalendar, weekday_settlement_calendar,
    weekday_trading_calendar,
)
from plutus.market.session.deposit import (
    ContractLedger, DerivativesAccount, MarginMonitor, UnknownContractMultiplier,
    liquidation_sequence, resolve_contract_multiplier,
)
from plutus.market.session.charges import ChargeContext, assess_at_maturity
from plutus.market.session.corporate import (
    CorporateAction, CorporateActionApplied, CorporateActionEngine,
    CorporateActionSchedule)
from plutus.market.session.fills import (BOOK_WALK_KIND, FillPolicy,
                                         build_fill_policy,
                                         parse_fill_policy_config)
from plutus.market.session.book_walk import (BookProvider, TapeProvider,
                                             build_book_walk_policy)
from plutus.market.session.ledgers import (
    CashLedger, EncumbranceLedger, HoldingsLedger, SecuritiesAccount,
    assess_charges,
)
from plutus.market.session.orders import (
    OrderBookOfRecord, OrderIdFactory, is_legal_transition,
)
from plutus.market.session.overnight import (
    PRE_KRX_CONTINUOUS, UNSTATED_MODEL, OvernightGap, OvernightRequirement,
    is_continuous_model, overnight_requirement, underlying_of,
)
from plutus.market.session.rulebook import (
    Rulebook, RuleName, RuleSet, SymbolRouter, UnresolvedRule, VenueListing,
)
from plutus.market.session.types import (
    Accepted, AccountRef, AccountsConfig, Amended, BrokerProfile, Cancelled,
    Cash, Charge, ChargeBase, ChargeClass, ChargeRule, ContractPosition,
    DataConfig, DataField, DebitedAt, Encumbrance, Event, EventKind,
    ExchangeRulesConfig, ExpiryTrigger, Fill, FillDecision, FillEvidence,
    FillId, FillOutcome, FillPolicyConfig, Holding, IndeterminateReport,
    LiquidationRule, MarginStatus, MarginView, MarketInterval, OrderId,
    OrderRecord, OrderState, OrderTransition, Pin, Pool, Rejected,
    SessionConfig, SessionProvenance, StatefulRule, TimeInForce, Transferred,
    Venue, pool_for_venue,
)
from plutus.market.verdicts import AdmissionRule, SettlementSource, Verdict

__all__ = [
    'CHARGE_CLASS_BY_KIND', 'EXCHANGE_BY_VENUE', 'Blindness', 'Component',
    'ExchangeSession', 'IntervalSource', 'RunIgnorance', 'RunProvenance',
    'Session', 'charge_class_for', 'load_data_source', 'parse_config',
]


# --------------------------------------------------------------------------
# The exchange registry -- section 9's "one session, several exchanges"
# --------------------------------------------------------------------------

#: The ``exchanges/`` object that judges each venue's orders.
#:
#: A session holds **several at once** and routes by ``(ticker, ts)``. This is
#: not a convenience: a VN30 basket against VN30F is the canonical Vietnamese
#: pair trade and it spans HSX and HNXDS, so a one-venue session could not
#: express the use case the package exists for. The registry is a module-level
#: constant because the four objects are stateless rule evaluators; the
#: *session's* registry is the subset named in ``exchange_rules.venues``, and
#: a ticker routing outside that subset is refused rather than silently traded.
#:
#: **No ``ExchangeSession`` method judges an order on one of these.** Each
#: holds the import-time ``core.constant`` ``ExchangeSpec``, undated by
#: construction, and this session reaches every judge through
#: ``SymbolRouter.exchange(ticker, ts)``, which copies the object and installs
#: the rulebook's dated tick grid on the copy. The constant stays exported
#: because ``exchanges/`` is a public surface and the batch research path
#: judges on ``ExchangeSpec`` deliberately -- but a session-side caller
#: reading it is reintroducing locked shape 1's forbidden build. It mirrors
#: ``rulebook._EXCHANGE_BY_VENUE``, which is the copy the router starts from;
#: the two hold the same four singleton objects and neither is authoritative
#: over the other, because a venue's judge is never keyed by anything but the
#: venue.
EXCHANGE_BY_VENUE: Mapping[Venue, Exchange] = {
    Venue.HSX: HSX_EXCHANGE,
    Venue.HNX: HNX_EXCHANGE,
    Venue.UPCOM: UPCOM_EXCHANGE,
    Venue.HNXDS: HNXDS_EXCHANGE,
}


#: Which charge schedule an instrument kind draws on.
#:
#: ``FUND`` maps to ``ETF`` because ``ChargeClass.ETF`` is a refinement of
#: ``InstrumentKind.FUND`` and Tier 1 carries no closed-end-fund row -- a
#: declared simplification, not a claim that the two are charged alike
#: (rulebook 12.2 gives closed-end funds their own row). ``INDEX`` and
#: ``UNKNOWN`` fall to ``EQUITY``, which is the schedule an unclassified
#: listed security is in fact charged on.
CHARGE_CLASS_BY_KIND: Mapping[InstrumentKind, ChargeClass] = {
    InstrumentKind.STOCK: ChargeClass.EQUITY,
    InstrumentKind.WARRANT: ChargeClass.WARRANT,
    InstrumentKind.FUND: ChargeClass.ETF,
    InstrumentKind.FUTURE: ChargeClass.FUTURE,
    InstrumentKind.INDEX: ChargeClass.EQUITY,
    InstrumentKind.UNKNOWN: ChargeClass.EQUITY,
}


def charge_class_for(kind: InstrumentKind) -> ChargeClass:
    """The charge schedule for an instrument kind. Total, never raises."""
    return CHARGE_CLASS_BY_KIND.get(kind, ChargeClass.EQUITY)


#: Which ``AdmissionRule`` reports a rulebook resolution failure.
#:
#: ``UnresolvedRule`` means the rulebook could not answer, which is a data gap
#: and therefore an ``INDETERMINATE`` verdict -- never a rule saying no. The
#: mapping exists so the gap is still *countable by rule*: a covered warrant
#: with no derivable band is a ``BAND_LIMIT`` indeterminate, not an
#: undifferentiated one.
#:
#: **Every entry here is reachable from ``submit()``, and that is a
#: requirement.** ``TICK_SIZE`` was not: the grid was judged against
#: ``ExchangeSpec``'s undated tick function, which answers every question, so
#: no session path could raise ``UnresolvedRule(TICK_SIZE)`` and the row was a
#: plan rather than a wiring. :meth:`ExchangeSession._dated_tick` resolves the
#: grid through ``rulebook.at(ts)`` and an unresolved one lands here; HNX's ETF
#: tick before 2022-03-31 is the live example. A row that no path can produce
#: is worse than a missing row, because ``by_rule`` then reads as a rule with
#: no gaps rather than as a rule nobody asked.
#:
#: **Orchestrator action.** There is no ``AdmissionRule`` member for "the
#: instrument could not be routed to a venue". Routing failures fall to
#: ``SESSION_SEMANTICS`` with an explicit ``detail['reason']``, which is the
#: precedent ``equity.py`` already sets for "the session could not be
#: established" -- but a ``ROUTING`` member would keep the two apart in a log
#: whose whole job is to be countable by rule.
#:
#: ``SESSION_SCHEDULE`` has no entry on purpose. ``RuleSet.phase`` takes the
#: total ``resolve`` path and answers ``SessionPhase.UNKNOWN``, which reaches
#: the log through ``LEGAL_ORDER_TYPES`` -- the ``(None, UNKNOWN)`` row -- so
#: an unresolved clock is already countable and a second mapping for it would
#: be the very thing the paragraph above objects to.
_RULE_FOR_RULENAME: Mapping[RuleName, AdmissionRule] = {
    RuleName.DAILY_TRADING_LIMIT: AdmissionRule.BAND_LIMIT,
    RuleName.WIDENED_TRADING_LIMIT: AdmissionRule.BAND_LIMIT,
    RuleName.TICK_SIZE: AdmissionRule.TICK_GRID,
    RuleName.TRADING_UNIT: AdmissionRule.ROUND_LOT,
    RuleName.LEGAL_ORDER_TYPES: AdmissionRule.SESSION_SEMANTICS,
    RuleName.MAX_ORDER_SIZE: AdmissionRule.SESSION_SEMANTICS,
}


#: How the margin ladder's statuses map onto the event cursor.
#:
#: ``OK`` maps to nothing **on its own**: an ``OK`` view can only reach the
#: session as the *clearance* of an outstanding call, and a clearance is not a
#: rung. It is emitted separately as ``MARGIN_CALL_CLEARED`` by
#: :meth:`ExchangeSession._mark_derivatives`, which knows whether a call was
#: outstanding before the mark; this table cannot, because a status alone does
#: not say what it came from. A ``WARNING`` that clears a call emits **both**
#: rows, for the same reason.
_EVENT_FOR_MARGIN_STATUS: Mapping[MarginStatus, EventKind] = {
    MarginStatus.WARNING: EventKind.MARGIN_WARNING,
    MarginStatus.CALL: EventKind.MARGIN_CALL,
    MarginStatus.FORCED: EventKind.FORCED_LIQUIDATION,
}


#: The trigger that ends each non-resting time-in-force at the day's close.
#:
#: Every entry is that type's **own** terminal edge, taken from
#: ``TERMINAL_TRIGGERS_BY_TIF``: an ATO does not die of a session end and a
#: day order does not die of an auction cross, and ``orders.expire`` refuses
#: an out-of-table trigger precisely so that a session cannot blur them. The
#: two resting time-in-forces are absent because ``expire_due`` already owns
#: them. See :meth:`ExchangeSession._sweep_non_resting`.
_CLOSE_TRIGGER_BY_TIF: Mapping[TimeInForce, ExpiryTrigger] = {
    TimeInForce.AUCTION_ONLY: ExpiryTrigger.AUCTION_CROSS,
    TimeInForce.FILL_OR_KILL: ExpiryTrigger.NOT_FILLABLE_IN_FULL,
    TimeInForce.IMMEDIATE_OR_CANCEL: ExpiryTrigger.IMMEDIATE_REMAINDER,
}


#: Order types that carry no usable limit price, so their deposit margin is
#: taken at the current mark. ATO/ATC are here because they must be funded
#: *before* a clearing price exists.
_MARKET_FAMILY: FrozenSet[OrderType] = frozenset({
    OrderType.MARKET, OrderType.MARKET_FILL_OR_KILL,
    OrderType.MARKET_IMMEDIATE_OR_CANCEL,
    OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
    OrderType.AT_THE_OPENING, OrderType.AT_THE_CLOSE,
})


#: The two refusals that mean "**this pool** could not fund the order".
#:
#: They are the pair a **pair trade** falls foul of, and the reason a
#: Vietnamese pair trade behaves differently from a Western one. Securities
#: cash and the derivatives deposit are segregated accounts with independent
#: purchasing power and **no auto-transfer** (design section 7.3, rulebook 6.3
#: "Where margin is held; segregation"), so a two-leg trade whose total cost
#: the account can easily meet is still refused on the leg whose own pool is
#: short. A caller told only ``INSUFFICIENT_DEPOSIT`` cannot tell that case --
#: one ``transfer()`` away from funded -- apart from being broke, and the
#: difference decides whether the sensible response is to move cash or to
#: cancel the other leg. :meth:`ExchangeSession._annotate_segregation` is what
#: makes the two distinguishable in the rejection itself.
_SEGREGATED_FUNDING_RULES: FrozenSet[StatefulRule] = frozenset({
    StatefulRule.INSUFFICIENT_CASH,
    StatefulRule.INSUFFICIENT_DEPOSIT,
})


# --------------------------------------------------------------------------
# The honesty instrument: what ran, and what ran blind
# --------------------------------------------------------------------------

class Component(str, Enum):
    """A named part of the session that one run either exercised or did not.

    **Why this exists.** A component that returns 0 because nothing called it
    is indistinguishable, in every number this package publishes, from one
    that ran and correctly computed 0. Three of the fidelity audit's findings
    have that exact shape -- a margin layer with no call site, a rule with no
    caller, a policy configuration nothing applied -- and in all three
    ``indeterminate_report()`` answered ``indeterminate=0``. A run that
    records which parts it actually invoked cannot make that mistake again:
    "not wired" appears as an absence from :attr:`RunIgnorance.exercised` and,
    where the run needed it, as a line in :attr:`RunIgnorance.unexercised`.

    **An enum and not free-form strings**, for the reason ``rulebook.py``
    gives about its own keys: a typo in a counter's key is a silent zero, and
    a silent zero is the failure this whole record exists to prevent.

    **Membership is not a claim of coverage.** These are the *session's* seams
    -- the places this module calls out to another one. A component named here
    and exercised was invoked; it does not follow that it was invoked with the
    right arguments, nor that the module behind it is correct. This record
    bounds one failure mode only: never invoked at all.
    """

    #: ``FillPolicy.evaluate`` -- the execution model, per order per interval.
    FILL_POLICY = 'fill_policy'
    #: ``Exchange.admits`` -- the stateless admission rules on the dated judge.
    ADMISSION = 'rule.admits'
    #: ``RuleSet.legal_order_types`` at the submitting instant.
    LEGAL_ORDER_TYPES = 'rule.legal_order_types'
    #: ``RuleSet.resolve(MAX_ORDER_SIZE)`` at the submitting instant.
    MAX_ORDER_SIZE = 'rule.max_order_size'
    #: ``RuleSet.tick_size`` -- the dated grid installed for one call.
    TICK_SIZE = 'rule.tick_size'
    #: ``RuleSet.margin_model`` -- which margin MECHANISM the date is under.
    MARGIN_MODEL = 'rule.margin_model'
    #: ``SecuritiesAccount.reserve_for_buy`` / ``reserve_for_sell``.
    SECURITIES_FUNDING = 'funding.securities_cash'
    #: ``DerivativesAccount.reserve_for_order`` -- initial margin at entry.
    DERIVATIVES_FUNDING = 'funding.derivatives_deposit'
    #: ``DerivativesAccount.margin`` -- the ``MR = IM + VM`` view. The
    #: **intraday** layer: continuously recomputed on the futures traded
    #: price, and the one every surveyed firm's client ladder is tested
    #: against.
    DERIVATIVES_MARK = 'margin.derivatives.mark'
    #: ``overnight.overnight_requirement`` -- the **overnight** layer, once
    #: per session after the close, on the *underlying's* close. A separate
    #: component from ``DERIVATIVES_MARK`` because they are separate models
    #: chosen separately (survey finding F-1), and because the failure this
    #: member exists to report is exactly that one of them ran and the other
    #: never did: ``scenario_margin.py`` had zero call sites in ``src/``
    #: while every derivatives run reported a full margin history.
    OVERNIGHT_MARGIN = 'margin.derivatives.overnight'
    #: ``MarginMonitor.on_mark`` -- the utilisation ladder and the cure clock.
    DERIVATIVES_LADDER = 'margin.derivatives.ladder'
    #: The equity margin account's per-order lending gate.
    EQUITY_MARGIN_GATE = 'margin.equity.gate'
    #: The equity margin account's per-advance maintenance pass.
    EQUITY_MARGIN_ADVANCE = 'margin.equity.advance'


class Blindness(str, Enum):
    """Ignorance that the ``indeterminate`` scalar structurally cannot show.

    Every member is a place where the run **acted anyway**: it produced a
    fill, passed an order, or marked an account while a fact it needed was
    absent. None of them is an ``INDETERMINATE`` outcome, so none of them
    reaches :attr:`IndeterminateReport.indeterminate` -- which is precisely
    why they have to be counted somewhere, and why
    :attr:`RunIgnorance.silent_total` exists.

    The two ``fill.*`` skips are the exception to "acted anyway": there the
    run did **not** act, and a live order was simply never put to the policy.
    That is the same defect wearing the other face -- an order nobody
    evaluated and an order nobody could decide end in the identical expiry
    row, and neither was visible in any published number.

    :attr:`OVERNIGHT_UNCOMPUTED` is the same exception again, and the one
    place a member here is a **duplicate** of something ``indeterminate``
    already counts. That is deliberate: an undecided overnight requirement is
    a real evaluation and moves the scalar, but the scalar cannot say *which
    input was missing*, and the remedy -- name a firm that publishes a
    parameter mirror, add the underlying's close to the source -- is entirely
    in that qualifier. :attr:`OVERNIGHT_ASSUMED` is the ordinary "acted
    anyway" kind: a number was produced with something of ours in it.
    """

    #: A live order whose ticker had no state at this instant, so it was
    #: never offered to the fill policy at all.
    NO_BAR = 'fill.no_bar'
    #: A live order whose ticker routed to no venue at this instant.
    UNROUTED = 'fill.unrouted'
    #: Prefix. A **definite fill** decided from an interval that named this
    #: field as absent. Composed as ``fill.decided_without.<field>``.
    DECIDED_WITHOUT = 'fill.decided_without'
    #: The config names a participation cap and the running policy applies
    #: none, so the fill was uncapped.
    CAP_NOT_APPLIED = 'participation_cap.not_applied'
    #: The running policy carries a cap and filled without the volume to
    #: compute it against.
    CAP_UNCOMPUTABLE = 'participation_cap.uncomputable'
    #: The fill exceeded the cap the running policy carries.
    CAP_EXCEEDED = 'participation_cap.exceeded'
    #: The order size cap could not be resolved at this date and venue, so
    #: the order was passed over the rule rather than judged by it.
    ORDER_SIZE_UNSOURCED = 'rule.max_order_size.unsourced'
    #: The rulebook refuses to name the margin mechanism at this date and the
    #: account was marked on ``IM + VM`` regardless.
    MARGIN_MODEL_UNSOURCED = 'rule.margin_model.unsourced'
    #: Prefix. The overnight requirement could not be computed and the run
    #: did **not** substitute the intraday number. Composed as
    #: ``margin.overnight.uncomputed.<OvernightGap>``, so the missing input
    #: is in the key.
    OVERNIGHT_UNCOMPUTED = 'margin.overnight.uncomputed'
    #: Prefix. The overnight requirement was produced with something of ours
    #: in it -- an underlying-asset grouping nobody publishes, an undated
    #: parameter mirror, an ``R`` inverted out of ``MF``. Composed as
    #: ``margin.overnight.assumed.<OvernightAssumption>``.
    OVERNIGHT_ASSUMED = 'margin.overnight.assumed'


def _blindness_key(what: Blindness,
                   field_: Union[DataField, str, None] = None) -> str:
    """The counter key for one blind spot, qualified where it has a subject.

    ``field_`` is a :class:`DataField` for the fill-side members, whose
    subject is always a field of the data contract, and a plain string for
    the overnight members, whose subject is an :class:`OvernightGap` or
    :class:`OvernightAssumption` value. Both are closed vocabularies with a
    ``.value``, so neither can become the free-form key
    :class:`Component` exists to prevent -- but they are different
    vocabularies, and pretending otherwise would put an enum member from
    ``overnight.py`` where a reader expects a ``DataField``.
    """
    if field_ is None:
        return what.value
    suffix = field_.value if isinstance(field_, DataField) else str(field_)
    return f'{what.value}.{suffix}'


@dataclass(frozen=True)
class RunIgnorance(IndeterminateReport):
    """:class:`IndeterminateReport` plus the ignorance it cannot represent.

    **Why a subclass and not three more fields on the base record.**
    ``IndeterminateReport`` lives in ``types.py``, which this module does not
    own; subclassing keeps every existing reader working unchanged --
    ``validation/runner.py`` stores it as an ``IndeterminateReport`` and the
    ``isinstance`` still holds -- while the session can report more than the
    base shape can carry. *Orchestrator action:* these three fields belong on
    ``IndeterminateReport`` itself, at which point this class collapses into
    it.

    **The three additions map onto three ways a meter reads zero while its
    subject is ignorant**, all three of them observed:

    * :attr:`silent_ignorance` -- the run acted on a fact it did not have. An
      uncapped fill, a fill decided without volume, an order passed over an
      unsourced size cap, a margin mark taken on a mechanism the rulebook
      refuses to name at that date.
    * :attr:`unexercised` -- a component this run **required** and never
      invoked. The margin layer that was never called is not a zero; it is an
      absence, and the two must not look alike.
    * :attr:`exercised` -- the positive half of the same fact, and the one a
      reader should check first: it says what actually ran.

    **These do not move** :attr:`~IndeterminateReport.indeterminate`, and that
    is deliberate rather than timid. That number is a share of
    ``evaluations`` -- fill decisions and margin marks -- and none of the
    three is an evaluation, so folding them in would make the published rate
    mean nothing at all. Read :attr:`is_clean`, never ``indeterminate == 0``,
    to ask whether a run was ignorant of anything.
    """

    silent_ignorance: Mapping[str, int] = field(default_factory=dict)
    """Blind spots by :class:`Blindness` key. Not part of ``indeterminate``."""

    exercised: Mapping[str, int] = field(default_factory=dict)
    """:class:`Component` key -> how many times this run invoked it."""

    unexercised: Tuple[str, ...] = ()
    """Components this run required and never invoked, sorted."""

    @property
    def silent_total(self) -> int:
        """Blind spots counted, summed over every key.

        A count of ``(act, missing fact)`` pairs and **not** of acts: one fill
        on a synthesised interval contributes five, one per absent field, plus
        one for a cap that was not applied. So it is a magnitude to compare
        against itself across runs, not a population with a denominator -- the
        per-key breakdown in :attr:`silent_ignorance` is what a reader acts
        on, and :attr:`is_clean` is the question they usually mean.
        """
        return sum(self.silent_ignorance.values())

    @property
    def is_clean(self) -> bool:
        """True only when **nothing** in this run was undecided or unwitnessed.

        The predicate ``indeterminate == 0`` is the one a reader reaches for
        and it is the one that was wrong on every audited failure. This is the
        honest form of the same question.
        """
        return (self.indeterminate == 0
                and self.silent_total == 0
                and not self.unexercised)

    def blind_spots(self) -> Tuple[str, ...]:
        """One human-readable line per blind spot, for a report to print."""
        lines = [f'{key}: {count}'
                 for key, count in sorted(self.silent_ignorance.items())]
        lines += [f'{name}: required by this run and never invoked'
                  for name in self.unexercised]
        return tuple(lines)


@dataclass(frozen=True)
class RunProvenance(SessionProvenance):
    """:class:`SessionProvenance` plus which parts of the session ran.

    A provenance record says what a run was *configured* with. Configuration
    is not execution: a session configured with an equity margin account whose
    lending pass was never invoked has a provenance record that is entirely
    true and entirely misleading. These two fields close that gap, so a stored
    result can be read for wiring failures without re-running it.

    Subclassed rather than added to ``SessionProvenance`` for the reason given
    on :class:`RunIgnorance`; the same *orchestrator action* applies.
    """

    exercised: Tuple[str, ...] = ()
    """:class:`Component` keys this run invoked at least once, sorted."""

    unexercised: Tuple[str, ...] = ()
    """Components this run required and never invoked, sorted."""

    overnight_model: Optional[str] = None
    """Which model computed the **overnight** layer, at the last close this
    run reached: a ``MarginModel`` name, or
    :data:`~plutus.market.session.overnight.PRE_KRX_CONTINUOUS`.

    Separate from ``margin_model``, which is the *user-facing* one. The two
    being one field is how a run reports a firm's intraday ladder and leaves
    the reader to assume the CCP layer was the same model -- survey finding
    F-1 says it is chosen per layer, and a record with one slot cannot say
    so. ``None`` means the layer never ran."""

    overnight_engine: Optional[str] = None
    """The module that produced :attr:`overnight_model`'s number, by name."""

    overnight_determinate: int = 0
    """End-of-day requirements this run actually computed."""

    overnight_indeterminate: int = 0
    """End-of-day requirements it could not compute. A stored result can be
    read for the layer's coverage without re-running it."""


@runtime_checkable
class IntervalSource(Protocol):
    """A data source that can serve a whole :class:`MarketInterval`.

    ``MarketDataSource`` is deliberately narrow -- three questions, all about
    a *snapshot* -- and a fill policy asks a question a snapshot cannot answer:
    did the market trade *through* this limit, and on what volume. Rather than
    widen the adapter protocol (which would break every existing adapter and
    the tests that use them), the session accepts either shape: an adapter
    implementing this method serves intervals directly, and one that does not
    gets an interval synthesised from ``state_at`` with the OHLC and volume
    fields **named as missing** rather than defaulted.

    That is design section 9.2's "nothing silently defaults" at this seam. On
    today's corpora the synthesised interval carries no volume, so
    ``HardFillPolicy`` returns ``INDETERMINATE`` wherever it would otherwise
    fill, and ``session.indeterminate_report()`` is the number to publish --
    a bound on ignorance, not a defect.

    **Absent, and unserveable, are different answers.** ``None`` means this
    source has no bar for that window and the session may synthesise one. A
    ``resolution`` the source cannot serve at all is not that: it is a
    configuration the run cannot honour, and answering ``None`` would have the
    session synthesise a bar that an uncapped ``soft`` would then fill on --
    at the wrong resolution, silently. So a source **raises** ``ValueError``
    for a resolution it cannot serve, and declares which ones it can in an
    optional class attribute :attr:`SERVES_RESOLUTIONS`, which
    :class:`ExchangeSession` reads at construction so the refusal lands before
    the run rather than inside it.

    ``SERVES_RESOLUTIONS`` is deliberately **not** a member of this protocol.
    Adding one would make every existing source fail the ``isinstance`` below
    and be silently downgraded to synthesised intervals -- a worse failure
    than the one it would prevent. A source that does not declare it is not
    checked, and is then responsible for not raising out of ``advance_to``.
    """

    def interval(self, ticker: str, start: datetime, end: datetime, *,
                 resolution: Resolution) -> Optional[MarketInterval]:
        """The interval over ``[start, end)``, or ``None`` if absent.

        Raises:
            ValueError: on a ``resolution`` this source cannot serve. Not an
                absence and not answerable with ``None`` -- see the class
                docstring.
        """
        ...


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def parse_config(payload: Mapping[str, Any]) -> SessionConfig:
    """Parse the design section 6 config object into a :class:`SessionConfig`.

    Two config objects, because they are two kinds of fact: ``exchange_rules``
    is gazetted, dated and citation-bearing, and ``broker_profile`` is
    commercial and per-firm. Conflating them is how a simulator ends up
    asserting a broker's house rule as market law.

    Named values under ``exchange_rules.pins`` are **counterfactual pins**:
    legal, but recorded as overrides in :meth:`ExchangeSession.provenance` --
    which is the difference between a counterfactual and a lie.

    ``broker_profile.firm`` names a **shipped margin profile** from
    :mod:`plutus.market.session.broker_profile` -- ``"PLUTUS_DEFAULT"``,
    ``"TCBS"``, ``"SSI_FOREIGN"`` and so on -- and is the supported way to run
    a session under one firm's published policy. Without it the three
    utilisation levels are read from the payload and default to
    ``BrokerTerms()``'s 0.80 / 0.90 / 1.00, which **is not any firm's ladder
    and is not PLUTUS_DEFAULT's** (0.80 / 0.90 / **0.95**): the session's
    historical default and the profile module's default synthesis disagree at
    the top rung, and naming the firm is the only way to get the latter.

    Two refusals rather than a merge, because both would otherwise publish a
    firm's name over a number the firm never wrote:

    * naming a firm **and** a utilisation level in the same payload raises --
      the profile owns the ladder;
    * ``fill_from_default: true`` is required before a firm that *delegates* a
      rung (MBS, KIS, VPS) will build, and every filled field is then marked
      as ours by ``BrokerProfile.supplied_fields``.

    **The ``fill_policy`` block is parsed by
    :func:`~plutus.market.session.fills.parse_fill_policy_config`, not read
    key by key here.** It used to be three ``.get`` calls, one of which
    supplied ``'0.10'`` for an absent ``max_participation`` -- which is what
    made every ``kind: soft`` run in this repository uncapped, since
    ``fills.py`` had to read that same 0.10 as "nobody asked for a cap". An
    absent key is now ``None`` and a written one is honoured, 0.10 included.
    Routing through that function also means an **unknown** ``fill_policy``
    key is refused rather than dropped: ``{kind: hard, participation: 0.10}``
    -- a typo for a real key -- used to be an uncapped-by-typo run that
    nothing could see. Unknown keys elsewhere in the payload are still
    tolerated; the fill assumption is the one input a result cannot be read
    without.

    Raises:
        KeyError: on a missing ``period`` or ``exchange_rules.venues``, rather
            than defaulting. A session that silently ran on an invented period
            or venue list would produce a result nobody can reproduce.
        ValueError: on ``firm`` together with an explicit ladder level, and on
            an unknown or unusable ``fill_policy`` key.
    """
    period = payload['period']
    rules_payload = payload.get('exchange_rules') or {}
    accounts_payload = payload.get('accounts') or {}
    securities = accounts_payload.get('securities') or {}
    derivatives = accounts_payload.get('derivatives') or {}
    fill_payload = payload.get('fill_policy') or {}
    data_payload = payload.get('data') or {}

    exchange_rules = ExchangeRulesConfig(
        venues=tuple(Venue.from_code(v) for v in rules_payload['venues']),
        rulebook=str(rules_payload.get('rulebook', 'vn-2020-2026')),
        pins=tuple(
            Pin(path=row['path'], value=row['value'], reason=row.get('reason'))
            for row in rules_payload.get('pins', ())),
    )
    accounts = AccountsConfig(
        initial_cash=Decimal(str(securities.get('initial_cash', 0))),
        initial_deposit=Decimal(str(derivatives.get('initial_deposit', 0))),
        securities_account_no=str(securities.get('account_no', 'SEC-0001')),
        derivatives_account_no=str(derivatives.get('account_no', 'DER-0001')),
    )
    fill_policy = parse_fill_policy_config(fill_payload)
    data = DataConfig(
        adapter=str(data_payload.get('adapter', '')),
        root=str(data_payload.get('root', '')),
        settlement_calendar=data_payload.get('settlement_calendar'),
        book_root=data_payload.get('book_root'),
    )
    return SessionConfig(
        period_start=_as_date(period['start']),
        period_end=_as_date(period['end']),
        resolution=Resolution(payload.get('resolution', Resolution.DAILY.value)),
        exchange_rules=exchange_rules,
        broker_profile=_broker_profile(payload.get('broker_profile') or {}),
        accounts=accounts,
        fill_policy=fill_policy,
        data=data,
    )


#: Payload keys the margin profile owns. Naming a firm and one of these in the
#: same config is a contradiction, not a merge: the whole point of the profile
#: is that the ladder is the firm's.
_PROFILE_OWNED_KEYS = ('warning_utilisation', 'margin_call_utilisation',
                       'forced_close_utilisation', 'margin_cure_window')


def _broker_profile(payload: Mapping[str, Any]) -> BrokerProfile:
    """The session's broker profile: a named firm's, or the payload's own.

    Imported lazily. ``broker_profile.py`` is a pure policy declaration whose
    own test pins that it imports nothing but ``plutus.market.broker``, so the
    bridge between the two same-named classes has to live on this side of it,
    and there is no reason a session with no firm named should pay for the
    module at all.
    """
    firm = payload.get('firm')
    if not firm:
        return BrokerProfile.from_config(payload)

    from plutus.market.session.broker_profile import PLUTUS_DEFAULT, get_profile

    clash = [key for key in _PROFILE_OWNED_KEYS if key in payload]
    if clash:
        raise ValueError(
            f'broker_profile names the firm {firm!r} and also sets '
            f'{", ".join(sorted(clash))}. The firm\'s profile owns its ladder '
            f'and its cure window; overriding one of them and keeping the '
            f'name would publish our number under {firm}\'s label. Drop the '
            f'firm to configure the levels by hand, or drop the levels.')
    profile = get_profile(
        str(firm),
        fill_from=PLUTUS_DEFAULT if payload.get('fill_from_default') else None,
        warn=bool(payload.get('warn', True)))
    session_profile = BrokerProfile.from_margin_profile(
        profile,
        margin_buffer=Decimal(str(payload.get('margin_buffer', 0))),
        # Parsed through the public path so there is one commission parser.
        commission=BrokerProfile.from_config(
            {'commission': payload.get('commission', ())}).commission)

    # The sale advance is a securities product and no margin profile carries
    # it, so it stays a payload key even when a firm is named.
    advance = payload.get('advance_sale_proceeds') or {}
    if advance:
        session_profile = replace(session_profile, terms=replace(
            session_profile.terms,
            advance_on_sale_enabled=bool(advance.get('enabled', False)),
            advance_on_sale_daily_rate=Decimal(
                str(advance.get('daily_rate',
                                session_profile.terms
                                .advance_on_sale_daily_rate)))))
    return session_profile


def load_data_source(config: DataConfig) -> Optional[MarketDataSource]:
    """Import and construct the adapter named in ``data.adapter``.

    ``adapter`` is a dotted path to a class or factory; ``root`` is handed to
    it when it takes one. An empty ``adapter`` yields ``None``, which is a
    legal session: ``SymbolRouter`` accepts ``source=None`` and the run then
    has no market data, so no order can ever fill. That is the right shape for
    an admission-only study, which is why the absence is permitted rather than
    refused.
    """
    if not config.adapter:
        return None
    module_name, _, attribute = config.adapter.rpartition('.')
    if not module_name:
        raise ValueError(
            f'data.adapter must be a dotted path to a class or factory, got '
            f'{config.adapter!r}')
    factory = getattr(importlib.import_module(module_name), attribute)
    try:
        return factory(config.root) if config.root else factory()
    except TypeError:
        return factory()


def _as_date(value: Union[str, date, datetime]) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


# --------------------------------------------------------------------------
# The session
# --------------------------------------------------------------------------

class ExchangeSession:
    """A simulated Vietnamese exchange you point a strategy at.

    Synchronous, call-and-response, deliberately close in shape to a broker
    API. Event-driven callbacks are explicitly future work (design section
    13); everything here is ``submit`` / ``poll`` / ``advance_to``.

    **One cursor, destructive, single-consumer.** :meth:`advance_to` returns
    the events it generated *and* consumes them, and :meth:`poll` drains
    anything since the last read of either. A strategy and a separate logger
    cannot both drain it, which is acceptable because design section 3 puts
    all reporting on the caller's side. ``Event.seq`` gives a total order and
    ``Event.dedupe_key`` is ``(order_id, kind, ts)`` for a caller that wants
    one.

    **A session may span several exchanges.** Symbols route to their venue
    from ``(ticker, ts)`` on every call -- never from a ticker-keyed cache,
    which is locked shape 1's forbidden build and which the corpus shows
    misprices every transferred ticker (all 3,729 UPCoM off-grid closes are
    venue-transfer artefacts).
    """

    def __init__(
        self,
        config: SessionConfig,
        source: Optional[MarketDataSource],
        rulebook: Rulebook,
        router: SymbolRouter,
        settlement: SettlementCalendar,
        trading: TradingCalendar,
        fill_policy: FillPolicy,
        securities: SecuritiesAccount,
        derivatives: DerivativesAccount,
        orders: OrderBookOfRecord,
        monitor: Optional[MarginMonitor] = None,
        equity_margin: Optional[Any] = None,
    ) -> None:
        """Compose the six modules. Nothing they own is rebuilt here.

        The wiring this constructor cannot do for itself is the order book's:
        ``orders`` must already carry ``on_terminal`` bound to both accounts'
        ``release`` and ``on_event`` bound to this session's cursor.
        :meth:`build` does that, and a caller assembling the pieces by hand
        must do it too -- an order reaching a terminal state without releasing
        its reservation is the leak class section 12 invariant 4 exists to
        catch.

        ``monitor`` is authoritative for two things this session then reports
        rather than decides: the cure window it measures, and the liquidation
        selection rule that :meth:`provenance` and every
        ``FORCED_LIQUIDATION`` event state. Passing one and having the session
        report a different rule is the failure
        :meth:`_liquidation_rule` exists to make impossible.

        Raises:
            ValueError: if ``source`` declares the resolutions it serves and
                ``config.resolution`` is not one of them. See
                :meth:`_refuse_unserveable_resolution`.
        """
        self._refuse_unserveable_resolution(config, source)
        self._config = config
        self._source = source
        self._rulebook = rulebook
        self._router = router
        self._settlement = settlement
        self._trading = trading
        self._policy = fill_policy
        self._securities = securities
        self._derivatives = derivatives
        self._book = orders
        self._monitor = monitor or MarginMonitor(
            config.broker_profile.terms, trading)

        #: The equity margin account, or ``None`` for a cash-only session.
        #:
        #: Typed ``Any`` on purpose: ``equity_margin.py`` imports this module's
        #: ``Event`` and ``Rejected``, so importing its class here would close
        #: a cycle. The contract is three methods -- ``gate``, ``unwind`` and
        #: ``on_advance`` -- and nothing in this file constructs one. A session
        #: without one **refuses** an ``on_margin`` order rather than treating
        #: it as an ordinary cash buy, which is the only safe default: silently
        #: dropping the credit leg would turn a leveraged strategy into an
        #: unleveraged one and report the result as if it had been asked for.
        self._equity_margin = equity_margin

        #: The venues this session is configured for. A ticker routing
        #: outside the set is refused rather than silently traded.
        #:
        #: **Deliberately not a ``Dict[Venue, Exchange]``.** It was one, built
        #: at construction from :data:`EXCHANGE_BY_VENUE`, and after the
        #: judging moved to ``SymbolRouter.exchange`` nothing read its values
        #: any more -- leaving a venue-keyed map of undated exchange objects
        #: sitting inside the session for the next author to reach for. A
        #: tuple of venues cannot be mistaken for a source of judges, which is
        #: the point: every ``admits()`` in this module goes through the
        #: router, and there is no second place to get an exchange from.
        self._venues: Tuple[Venue, ...] = tuple(config.exchange_rules.venues)
        self._daily = config.resolution is Resolution.DAILY

        #: The session mints every order id, including a rejected order's, so
        #: the rejection log joins to the submission. The book's own factory
        #: is never reached: every ``accept``/``reject`` is handed an id.
        self._ids = OrderIdFactory()
        self._now = datetime.combine(config.period_start, datetime.min.time())
        self._seq = 0
        self._fills_issued = 0
        self._events: List[Event] = []

        #: The last market state observed per ticker. Read for an MTL's
        #: residual price and for the derivatives marks, never for admission
        #: -- admission always re-reads the source at the submitting instant,
        #: because a stale band is worse than no band.
        self._last_state: Dict[str, MarketState] = {}
        #: Charges levied out of the deposit. ``CashLedger`` owns the
        #: securities half and **refuses a derivatives-pool charge by design**,
        #: and ``DerivativesAccount`` has no charge ledger at all, so the
        #: session keeps this half and :meth:`charges` merges the two.
        self._deposit_charges: List[Charge] = []

        #: Quantity filled per ticker **in the bar currently being evaluated**,
        #: and the bar it belongs to. Session state rather than a local of
        #: :meth:`_evaluate_fills`, and that is the whole of a repair.
        #:
        #: The participation cap aggregates across the caller's live orders so
        #: that splitting one order into ten does not evade it. It has to
        #: aggregate across ``advance_to`` calls for the same reason: every
        #: source in this package serves a whole day's volume for any instant
        #: inside the day, so a counter reset per advance let the same caller
        #: claim 10% of the same 3,300 shares once per advance -- 1,800 of
        #: them, 54.5% of the day, under a signature reading
        #: ``hard(max_participation=0.10)``. Splitting the order and advancing
        #: the clock are the same evasion; only the first was closed.
        #:
        #: **The bar is the trading date**, and that is a claim about the data
        #: rather than about the config. ``_interval_for`` asks for
        #: ``[ts, ts + one bar)``, but no source in this repository serves a
        #: sub-daily volume for it: ``DataHubSource`` serves the day's row and
        #: says so, ``PhasedBarSource`` serves the day's row even at
        #: ``Resolution.TICK``, and ``TickSource`` implements no ``interval``
        #: at all, so its intervals are synthesised with no volume and the cap
        #: never computes. Whatever the resolution, the liquidity the cap is
        #: taken from is one session's, and claiming a share of it twice in a
        #: day is claiming the same shares twice.
        #:
        #: If a source ever serves genuinely disjoint sub-daily volumes, this
        #: key is too coarse and will under-fill -- the restrictive direction,
        #: and the one to err in. The fix then is to key on the served
        #: interval's own window, which is only sound once a served window
        #: means something, which today it does not.
        self._filled_in_bar: Dict[str, int] = {}
        self._filled_bar: Optional[date] = None

        self._evaluations = 0
        self._indeterminate = 0
        self._by_field: Dict[DataField, int] = {}
        self._by_rule: Dict[str, int] = {}

        #: Blind spots, keyed by :class:`Blindness`. Counted separately from
        #: ``_indeterminate`` because they are not evaluations -- see
        #: :class:`RunIgnorance`.
        self._silent: Dict[str, int] = {}
        #: :class:`Component` value -> invocations. The positive record of
        #: what this run actually ran.
        self._exercised: Dict[str, int] = {}
        #: Components this run **requires**. Seeded with the fill policy,
        #: which every session claims to have, and grown by what the run does:
        #: opening a futures position requires the deposit's margin layer, and
        #: attaching a margin account requires its maintenance pass. Requiring
        #: a component only once the run needs it is what keeps
        #: ``unexercised`` a finding rather than a standing complaint about
        #: every venue in the config.
        self._needed: Set[str] = {Component.FILL_POLICY.value}
        if equity_margin is not None:
            self._needed.add(Component.EQUITY_MARGIN_ADVANCE.value)

        #: The overnight requirement per calculation date, in the order the
        #: run computed them. A list rather than one latest value because the
        #: layer's whole content is how the requirement moved across the
        #: window, and because a run that computed it once and then stopped
        #: is a finding a scalar cannot show.
        self._overnight: List[OvernightRequirement] = []
        #: Dates the overnight layer has already answered for. The layer runs
        #: once per session, *"sau khi ket thuc phien giao dich"* (QD 26 Dieu
        #: 5.5), and a caller polling the clock four times after the close
        #: must not get four requirements and four evaluations.
        self._overnight_dates: Set[date] = set()

    # -- the honesty instrument's two write paths -----------------------

    def _exercise(self, component: Component) -> None:
        """Record that this run actually invoked ``component``."""
        key = component.value
        self._exercised[key] = self._exercised.get(key, 0) + 1

    def _needs(self, component: Component) -> None:
        """Record that this run **requires** ``component`` to have run."""
        self._needed.add(component.value)

    def _blind(self, what: Blindness,
               field_: Union[DataField, str, None] = None) -> None:
        """Record one act taken without a fact the run needed."""
        key = _blindness_key(what, field_)
        self._silent[key] = self._silent.get(key, 0) + 1

    # -- construction ---------------------------------------------------

    @classmethod
    def from_config(cls, path: Union[str, Path], *,
                    source: Optional[MarketDataSource] = None,
                    listings: Sequence[VenueListing] = (),
                    settlement: Optional[SettlementCalendar] = None,
                    trading: Optional[TradingCalendar] = None,
                    ) -> 'ExchangeSession':
        """Build from the design section 6 config file.

        Parses into :class:`SessionConfig`, builds the ``Rulebook`` with its
        pins, loads both calendars, constructs the two accounts and selects
        the fill policy by ``fill_policy.kind``.

        The four keyword-only injection points are additions to the contract's
        one-argument signature, so the promised call is unchanged. They exist
        because three of them are things a config file cannot express
        honestly: a sourced VSDC settlement calendar is a *document*, a dated
        venue listing is a *table*, and a test needs a data source that is not
        on disk.
        """
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        return cls.from_mapping(payload, source=source, listings=listings,
                                settlement=settlement, trading=trading)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *,
                     source: Optional[MarketDataSource] = None,
                     listings: Sequence[VenueListing] = (),
                     settlement: Optional[SettlementCalendar] = None,
                     trading: Optional[TradingCalendar] = None,
                     ) -> 'ExchangeSession':
        """:meth:`from_config` from an already-parsed mapping."""
        config = parse_config(payload)
        if source is None:
            source = load_data_source(config.data)
        return cls.build(config, source=source, listings=listings,
                         settlement=settlement, trading=trading)

    @classmethod
    def build(cls, config: SessionConfig, *,
              source: Optional[MarketDataSource] = None,
              listings: Sequence[VenueListing] = (),
              settlement: Optional[SettlementCalendar] = None,
              trading: Optional[TradingCalendar] = None,
              rulebook: Optional[Rulebook] = None,
              fill_policy: Optional[FillPolicy] = None,
              initial_holdings: Optional[Mapping[str, int]] = None,
              monitor: Optional[MarginMonitor] = None,
              equity_margin: Optional[Any] = None,
              ) -> 'ExchangeSession':
        """Assemble a session from a parsed config, wiring the shared hooks.

        The wiring is why this is a separate method. Two joins are structural
        rather than incidental:

        * **One encumbrance ledger serves both pools**, so section 12
          invariant 4 -- the sum of encumbrance over live orders equals the
          ledgers' committed totals -- spans them. The pools stay segregated
          because ``Pool`` is a field on every reservation, not because they
          have separate ledgers.
        * **One ``on_terminal`` hook serves both accounts.** A terminal
          transition that forgets to release is then impossible by
          construction rather than by review.
        * **The derivatives account is given a dated multiplier resolver**,
          named here rather than left to a constructor default. It was left to
          one, and the default was VN30F's 100,000 VND per index point applied
          to every contract on HNXDS -- so a government-bond future, whose
          multiplier is 10,000 (rulebook 4.1, HIGH), reserved ten times its
          initial margin and the account was refused a position it could
          afford. ``build`` is the only place a session's accounts are
          assembled, so it is the only place that could have passed the
          multipliers and never did; naming
          :func:`~plutus.market.session.deposit.resolve_contract_multiplier`
          makes the join visible and makes a silent family-wide default
          impossible to reintroduce by omission.

        **Orchestrator action:** ``build`` also hardwires the deposit's
        ``investor`` to ``InvestorClass.INDIVIDUAL``, and rulebook 6.4 bars
        individuals from government-bond futures entirely (cap 0). So a GB
        order submitted through a session built here is refused on
        ``POSITION_LIMIT`` before its margin is ever computed, and the
        multiplier fix is not reachable end-to-end until ``AccountsConfig``
        carries an investor class. That is a ``config`` change, not a change
        here.

        **Both calendars default to the unsourced weekday-only ones**, whose
        ids contain ``UNSOURCED`` and whose settlement dates are wrong around
        every Tet in the period. The default exists so a smoke run works, and
        :meth:`provenance` reports the id so a published result cannot hide
        it. A run that means to be right passes a sourced calendar -- as the
        ``settlement`` argument, or by naming the VSDC notice under
        ``data.settlement_calendar`` in the config, which
        :meth:`_settlement_calendar` loads.

        ``monitor`` is here for the same reason ``rulebook`` and
        ``fill_policy`` are: it carries a choice the config file cannot
        express, in this case the liquidation selection rule that every
        ``FORCED_LIQUIDATION`` event and the provenance record must state.
        The constructor has always taken one; ``build`` dropping it on the
        floor meant there was no supported way to configure it.

        **The margin model is selected here and refused here.** When the config
        carries a firm's margin profile, that profile's ``margin_model`` names
        which engine computes the one user-facing margin number. This session
        runs exactly one of them -- ``deposit.py``'s ``MR = IM + VM`` family --
        so a profile selecting ``SCENARIO_GRID`` raises
        :class:`NotImplementedError` rather than silently being marked on a
        model it did not choose. See :meth:`_check_margin_model`.
        """
        profile = config.broker_profile
        cls._check_margin_model(profile)
        trading = trading or weekday_trading_calendar()
        settlement = cls._settlement_calendar(config.data, settlement)
        if isinstance(settlement, VsdcSettlementCalendar):
            # The pre-2022-08-29 regime delivers at the *next session open*,
            # which is a trading-day question a settlement calendar cannot
            # answer alone -- and the Tier 1 demo period sits inside it.
            settlement = settlement.with_trading(trading)

        rulebook = rulebook or Rulebook(config.exchange_rules.rulebook,
                                        pins=config.exchange_rules.pins)
        router = SymbolRouter(source, rulebook, listings=listings)
        if fill_policy is not None:
            policy = fill_policy
        elif config.fill_policy.kind == BOOK_WALK_KIND:
            # The one policy the session builds itself, because it alone needs a
            # book provider (fills.build_fill_policy cannot import book_walk).
            # The book is decoupled from the price/instrument source: admission,
            # bands and venue come from ``source`` (a DataHubSource), while the
            # fill sweeps a ``DepthSource``. If the source already provides a
            # book we use it; otherwise we open a DepthSource over the same
            # data root (the depth tables sit beside the price tables).
            if isinstance(source, BookProvider):
                book_provider: BookProvider = source
                # A source that also serves the tape (a BookSessionSource) makes
                # the maker arm available; one that does not leaves resting
                # orders to rest.
                tape_provider: Optional[TapeProvider] = (
                    source if isinstance(source, TapeProvider) else None)
            elif config.data is not None and (config.data.book_root
                                              or config.data.root):
                from plutus.market.adapters.depth import DepthSource
                from plutus.market.adapters.tape import TapeSource
                depth_root = config.data.book_root or config.data.root
                book_provider = DepthSource(depth_root)
                # The tape tables (``*_matched`` + ``*_total``) sit in the same
                # root; TapeSource serves nothing (INDETERMINATE) where absent.
                tape_provider = TapeSource(depth_root)
            else:
                raise ValueError(
                    "fill_policy.kind='book_walk' needs an order book: set "
                    "data.root to a depth extract (local_quote_* tables) or "
                    "pass a DepthSource to from_config(..., source=...)")
            policy = build_book_walk_policy(config.fill_policy,
                                            book_provider=book_provider,
                                            tape_provider=tape_provider)
        else:
            policy = build_fill_policy(config.fill_policy)

        encumbrances = EncumbranceLedger()
        securities = SecuritiesAccount(
            AccountRef.securities(config.accounts.securities_account_no),
            CashLedger(config.accounts.initial_cash, profile.terms,
                       encumbrances),
            HoldingsLedger(encumbrances, initial=initial_holdings),
            encumbrances, profile=profile)
        deposit = DerivativesAccount(
            AccountRef.derivatives(config.accounts.derivatives_account_no),
            config.accounts.initial_deposit, profile.terms, encumbrances,
            ContractLedger(), margin_buffer=profile.margin_buffer,
            multiplier_resolver=resolve_contract_multiplier,
            opened_at=datetime.combine(config.period_start,
                                       datetime.min.time()))

        # The book needs the session's cursor and the session needs the book,
        # so one of the two references is late-bound. A one-slot cell is the
        # smallest thing that does it without either object growing a setter.
        cell: Dict[str, 'ExchangeSession'] = {}

        def on_terminal(record: OrderRecord, transition: OrderTransition,
                        ts: datetime) -> None:
            """The one release hook, serving both segregated pools."""
            deposit.release(record.order_id, ts)
            securities.release(record.order_id, ts)

        book = OrderBookOfRecord(
            OrderIdFactory(),
            on_terminal=on_terminal,
            on_event=lambda event: cell['session']._events.append(event),
            next_seq=lambda: cell['session']._next_seq(),
        )
        session = cls(config, source, rulebook, router, settlement, trading,
                      policy, securities, deposit, book, monitor,
                      equity_margin=equity_margin)
        cell['session'] = session
        return session

    def attach_equity_margin(self, account: Any) -> None:
        """Bind an equity margin account to a session already built.

        ``build`` takes one too; this exists because the account needs a
        business-day calendar and a price feed the config file cannot express,
        so a caller often has the session first.

        Refuses to replace one and refuses after the clock has moved. Both are
        the same failure in different clothes: a margin account that did not
        see the disbursement of a loan cannot reconcile it, and one swapped
        mid-run leaves an open call in an object nobody reads.
        """
        if self._equity_margin is not None:
            raise ValueError(
                f'this session already has equity margin account '
                f'{self._equity_margin.account_id!r}. TT 120 Dieu 9.3 makes '
                f'the margin account segregated per investor per CTCK; one '
                f'session is one client at one firm')
        if self._now > datetime.combine(self._config.period_start,
                                        datetime.min.time()):
            raise ValueError(
                f'the clock has already advanced to {self._now.isoformat()}. '
                f'An account attached mid-run has no record of the loans, '
                f'holdings and calls that came before it, so its DB, its '
                f'breach-day counter and its cure clock would all start from a '
                f'state that never existed')
        self._equity_margin = account
        # A session holding a margin account is a session whose published
        # provenance implies leverage was modelled. If the maintenance pass
        # never runs, that implication is false and must be reported as such.
        self._needs(Component.EQUITY_MARGIN_ADVANCE)

    @staticmethod
    def _check_margin_model(profile: BrokerProfile) -> None:
        """Check that the model the profile's user-facing layer names is wired.

        The author's sixth axis, enforced. A profile carries **two** margin
        models -- the intraday continuously-updated one and the overnight CCP
        submission -- and ``user_facing_model`` names which of them the
        client's ladder is tested against.

        **Both are now wired**, which is what changed here.
        ``MarginModel.SCENARIO_GRID`` is QD 26 Phu luc 2's 21-scenario grid,
        implemented in :mod:`plutus.market.session.scenario_margin` and
        reached through :mod:`plutus.market.session.overnight` from
        :meth:`_overnight_margin`; everything else is ``deposit.py``'s.
        This method used to raise ``NotImplementedError`` for the grid, and
        the refusal was correct for as long as the engine had no call site --
        running the grid-selecting profile on ``IM + VM`` would have put our
        number on the firm's ladder and reported it under the firm's name.

        What replaces the refusal is **not** a silent acceptance. The grid
        needs a ``VsdcParameterSet`` most profiles do not publish
        (``BrokerProfile.parameters_for`` raises for TCBS, MBS, KIS and VPS),
        and where it is missing the layer answers INDETERMINATE with the
        missing input named -- see :meth:`_overnight_margin`. A refusal at
        build time would have been the *wrong* place for that: whether the
        parameters are there is a fact about the run's dates and the account's
        underlyings, not about the config.

        ``MarginModel.UNSTATED`` -- SSI, Pinetree, TCBS's intraday numerator --
        is not refused either. Those firms publish a real ladder and no
        formula, so the levels are theirs and the divisor is ours; the session
        runs and ``SessionProvenance.margin_model_is_assumed`` says so.

        **What is still refused, and it is a narrower thing than before**: a
        profile whose ``user_facing_model`` is ``OVERNIGHT``. The overnight
        number is computed for every profile and reported by
        :meth:`overnight_margin`, but the utilisation *ladder* cannot be run
        on it, because ``MarginView`` has no field for a requirement it did
        not decompose -- ``required`` is the property ``initial_margin +
        variation_margin``, and the grid produces neither of those terms (QD
        26 Dieu 20 settles position P&L as a separate cash movement and Phu
        luc 2 section 6.2 has no ``VM`` term at all). The only way to put the
        grid's number on the ladder today would be to write it into
        ``initial_margin`` and zero ``variation_margin``, which would report
        a decomposition that did not happen and would corrupt
        ``free_deposit`` and ``posted_margin`` with it. Refusing beats
        fabricating. *Orchestrator action:* ``MarginView`` needs to carry a
        requirement and its layer, at which point this refusal goes.

        No shipped profile is in that position -- all twelve name
        ``INTRADAY`` -- so nothing this repository ships is refused here.

        Raises:
            NotImplementedError: for an ``OVERNIGHT``-facing profile, and for
                a model whose engine is neither of the two this session can
                reach. The second has no instance today; the check is kept so
                that a *new* ``MarginModel`` member cannot be added upstream
                and silently margined on the wrong engine.
        """
        margin_profile = getattr(profile, 'margin_profile', None)
        if margin_profile is None:
            return
        model = margin_profile.margin_model
        layer = margin_profile.user_facing_model
        if layer.name == 'OVERNIGHT':
            raise NotImplementedError(
                f'{margin_profile.firm} declares its user-facing margin '
                f'number to be the OVERNIGHT layer. This session computes '
                f'that layer -- see ExchangeSession.overnight_margin() -- but '
                f'cannot run the utilisation ladder on it: MarginView.required '
                f'is initial_margin + variation_margin, and QD 26 Phu luc 2 '
                f'produces neither term. Grading {margin_profile.firm}\'s '
                f'client on the intraday number while reporting the firm\'s '
                f'name is the failure a provenance record cannot catch.')
        if model.engine in (None,
                            'plutus.market.session.deposit',
                            'plutus.market.session.scenario_margin'):
            return
        raise NotImplementedError(
            f'{margin_profile.firm} declares its user-facing margin number to '
            f'be the {margin_profile.user_facing_model.name} layer, whose '
            f'model is {model.name}. That model is computed by '
            f'{model.engine}, which is not wired into ExchangeSession: this '
            f'session reaches deposit.py for the intraday layer and '
            f'scenario_margin.py for the overnight one, and nothing else. '
            f'Running it anyway would put our number on '
            f'{margin_profile.firm}\'s ladder and report it under '
            f'{margin_profile.firm}\'s name.')

    @staticmethod
    def _settlement_calendar(data: DataConfig,
                             supplied: Optional[SettlementCalendar],
                             ) -> SettlementCalendar:
        """Resolve the settlement calendar: the config's file, or the default.

        ``data.settlement_calendar`` is the one remedy ``calendar.py`` asks
        for and it was parsed and then never read, so a caller who supplied
        the real VSDC notice still ran on the weekday-only calendar and still
        got ``settlement_calendar_id == 'weekday-only-UNSOURCED'`` in its
        provenance. For a 2026-02-12 trade that answers T+2 = 2026-02-16 where
        VSDC settled 2026-02-23 -- five counted days the depository was shut.

        Two refusals, both matching :func:`parse_config`'s treatment of a
        missing ``period``:

        * a **named calendar that will not load** raises out of
          :meth:`VsdcSettlementCalendar.from_file` rather than falling back,
          because a run that silently substituted the unsourced calendar for
          the one its config named is unreproducible from its own config;
        * **naming one twice** -- a file in the config *and* an injected
          object -- is two answers to one question, which is the same shape
          ``from_file`` already refuses for ``holidays`` alongside
          ``settlement_days``. Neither is preferred; the caller is told.
        """
        configured = data.settlement_calendar if data is not None else None
        if configured and supplied is not None:
            raise ValueError(
                f'the settlement calendar is named twice: '
                f'data.settlement_calendar={configured!r} in the config and a '
                f'settlement= object passed to build(). They are two answers '
                f'to one question and the provenance record can carry only '
                f'one id, so neither is preferred -- pass one.')
        if configured:
            return VsdcSettlementCalendar.from_file(configured)
        return supplied if supplied is not None else weekday_settlement_calendar()

    # -- clock ----------------------------------------------------------

    def now(self) -> datetime:
        """The instant the session is standing at."""
        return self._now

    def phase(self, venue: Union[Venue, str]) -> SessionPhase:
        """The phase at :meth:`now` on that venue. **Never from ``ts`` alone.**

        On any resolution but ``DAILY`` this is
        ``rulebook.at(now).phase(venue)`` verbatim -- the dated session table,
        resolved at the instant, with the noon break tested before the
        continuous window so 12:00 is ``NOON_BREAK`` and not ``CONTINUOUS``.

        On ``Resolution.DAILY`` it is the phase a daily bar *means*. A daily
        bar is stamped midnight, so the dated table would answer ``PRE_OPEN``
        for every bar of the run: every order refused with
        ``SESSION_SEMANTICS`` and every cancellation refused by the pre-open
        lock. The bar covers a whole trading day whose matching phase is the
        continuous session -- which is exactly what both shipped adapters
        already assert on the state they build -- and the **trading
        calendar**, not the clock, decides whether the day trades. See the
        module docstring; this is a declared deviation from the contract's
        literal wording, taken because the alternative is a measurement that
        rejects itself.
        """
        venue = Venue.from_code(venue) if isinstance(venue, str) else venue
        return self._phase(venue)

    def advance_to(self, ts: datetime) -> List[Event]:
        """Advance the clock and return the events generated.

        Per advance, in order:

        1. every phase boundary crossed -> ``orders.expire_due(...)``
        2. every live order -> ``fill_policy.evaluate(record, interval, rules)``
        3. fills applied to both accounts; ``Filled`` / ``PartiallyFilled``
        4. the immediate order families decided, an MTL residue converted
        5. ``holdings.settle_due(now)`` and ``cash.settle_due(now)``
           -> ``SettlementCredited``
        6. ``cash.accrue_interest(now)``
        7. the derivatives mark -> ``MarginWarning`` / ``MarginCall`` /
           ``ForcedLiquidation``; expiries -> ``ExpirySettled``
        7c. at or after the derivatives close, once per day, the **overnight**
           requirement -> :meth:`overnight_margin`
        8. drain the cursor and return

        **Step 7c runs after step 7**, and the order is load-bearing: a
        contract that cash-settled today is not carried past tonight's close,
        so the end-of-day book has to be the post-expiry one.

        **Step 1 runs before step 2**, or an order that died at the cross can
        still fill in the phase that killed it.

        **The loop shape this expects**, and it matters on a daily clock::

            for day in days:
                session.advance_to(datetime.combine(day, time(9, 30)))
                session.submit(...)                       # orders for `day`
                events = session.advance_to(
                    datetime.combine(day, time(14, 45)))  # `day` matches

        The two advances are not decoration. The bar is evaluated by the
        advance that lands inside its day, so an order submitted *after* that
        advance is not evaluated against that day's bar -- and the next
        advance crosses the date, which sweeps the day's close before it
        evaluates anything. A loop that only ever advances to midnight would
        therefore submit orders that expire without having been offered a
        single bar. That is correct behaviour for a synchronous API with no
        matching engine behind ``submit()``, and it is stated here rather than
        discovered.

        Raises:
            ValueError: on a backwards advance. The clock is monotone: a
                session that could step back would settle a tranche twice and
                re-evaluate a fill against data it has already consumed.
        """
        if ts < self._now:
            raise ValueError(
                f'cannot advance to {ts.isoformat()} from '
                f'{self._now.isoformat()}: the session clock is monotone, and '
                f'stepping back would re-settle tranches and re-evaluate '
                f'fills against data already consumed')
        previous = self._now
        self._now = ts

        self._expire_boundaries(previous, ts)
        decided = self._evaluate_fills(ts)
        self._decide_immediates(ts, decided)
        self._settle(ts)
        self._securities.cash_ledger.accrue_interest(ts)
        self._mark_derivatives(ts)
        self._overnight_margin(ts)
        self._run_equity_margin(ts)
        return self.poll()

    def _run_equity_margin(self, ts: datetime) -> None:
        """Step 7b: the equity margin pass. QD 87 Dieu 6.1, 7, 8.

        **After** the derivatives mark and after settlement, and the order is
        not arbitrary: the margin ratio is computed over ``CB`` -- *tien + tien
        ban chung khoan cho ve* -- so a tranche settling this instant has to be
        in the settled balance before the account is graded, or the
        determination runs against a cash position that ceased to exist one
        line earlier.

        Unlike ``_mark_derivatives``, this pass **can submit orders**: a *ban
        giai chap* is a real sell order and it goes through ``submit()`` like
        any other, so it faces the same band, the same tick grid, the same lot
        and the same fill policy. That is deliberate and it is the difference
        between reporting a liquidation and running one.
        """
        if self._equity_margin is None:
            return
        self._exercise(Component.EQUITY_MARGIN_ADVANCE)
        for event in self._equity_margin.on_advance(self, ts, self._next_seq):
            self._emit(event)

    # -- orders ---------------------------------------------------------

    def submit(self, order: Order) -> Union[Accepted, Rejected]:
        """Submit for admission and funding. The section 1 sequence, in order.

        ``route -> rulebook.at(ts) -> phase -> dated legality -> dated size cap
        -> dated tick -> admits() -> reserve -> accept``. The reservation runs
        **around** ``Exchange.admits()`` and never inside it: a stateless
        affordability check inside ``admits()`` is locked shape 2's forbidden
        build, and it would break the existing tests that call ``admits()``
        with no account at all.

        **Three rules are resolved here and not inside ``admits()``**, and
        they are the three the venue objects in ``exchanges/`` cannot date:
        which order types this venue accepts in this phase
        (:meth:`_legal_here`), the per-order quantity cap
        (:meth:`_size_here`), and the tick grid (:meth:`_dated_tick`). The
        first two refuse here. The third does not: it is *installed* on the
        venue object for this one call, so ``admits()`` still runs the grid
        rule, still reports it as ``TICK_GRID``, and still runs it first --
        the per-rule composition of the rejection log is unchanged, only the
        number it compares against is now dated. See :meth:`_venue_at`.

        Every refusal is a :class:`Rejected` carrying the **rule** that bound,
        never a string, and a ``verdict`` separating "a rule said no" from
        "the data could not decide". Both keep the order out of the book;
        conflating them would report a data gap as a market rule and corrupt
        the rejection-rate figures.

        **The Tier 1 demo lives here**: buy today, try to sell today, and the
        sell comes back ``Rejected(UNSETTLED_HOLDING, binding_constraint=0)``
        carrying ``sellable_from`` -- the instant the requested quantity
        actually becomes sellable.

        **A funding refusal also says which pool was short and what the other
        one held** -- see :meth:`_annotate_segregation`. That is the pair
        trade's refusal: the two legs of a VN30-basket-against-VN30F trade
        draw on two segregated accounts, so a pair the account funds in
        aggregate can still be refused on one leg, and the caller is told
        which of the two situations it is in rather than left to infer it.
        """
        ts = self._now
        order_id = self._ids.next()

        routed = self._route(order, order_id, ts)
        if isinstance(routed, Rejected):
            return self._reject_unrouted(order, routed)
        venue, instrument = routed

        if venue not in self._venues:
            return self._reject(order, venue, order_id, Rejected(
                rule=AdmissionRule.SESSION_SEMANTICS, binding_constraint=None,
                ts=ts, order_id=order_id,
                detail={'reason': f'{venue.value} is not configured for this '
                                  f'session',
                        'configured': [v.value for v in self._venues]}))

        rules = self._rulebook.at(ts)
        state = self._market_state(order.ticker, ts)
        phase = self._phase(venue, observed=state.session)
        state = replace(state, session=phase)
        regime_tag = self._rulebook.edition_at(ts).value

        refusal = self._legal_here(order, venue, phase, rules, order_id, ts)
        if refusal is not None:
            return self._reject(order, venue, order_id, refusal)

        refusal = self._size_here(order, venue, rules, order_id, ts)
        if refusal is not None:
            return self._reject(order, venue, order_id, refusal)

        tick = self._dated_tick(order, venue, instrument, rules, order_id, ts)
        if isinstance(tick, Rejected):
            return self._reject(order, venue, order_id, tick)

        adm = self._venue_at(order.ticker, ts, tick).admits(
            order, state, instrument=instrument, regime_tag=regime_tag)
        self._exercise(Component.ADMISSION)
        if adm.verdict is not Verdict.ADMITTED:
            return self._reject(order, venue, order_id,
                                Rejected.from_admissibility(adm, order_id))

        draw = None
        if order.on_margin:
            gated = self._margin_gate(order, order_id, venue, state, ts)
            if isinstance(gated, Rejected):
                if gated.regime_tag is None:
                    gated = replace(gated, regime_tag=regime_tag)
                return self._reject(order, venue, order_id, gated)
            draw = gated

        reservation = self._reserve(order, order_id, venue, state, rules, ts,
                                    instrument)
        if isinstance(reservation, Rejected):
            if draw is not None:
                # The loan was credited so the pre-funding test could see it;
                # the order never reached the book, so it is unwound in full.
                # Leaving it drawn would give the account borrowed cash with no
                # position behind it and a DB nobody can explain.
                self._equity_margin.unwind(
                    draw, ts, self,
                    f'the reservation refused the order: '
                    f'{reservation.rule.value}')
            if reservation.regime_tag is None:
                reservation = replace(reservation, regime_tag=regime_tag)
            reservation = self._annotate_segregation(reservation, venue)
            return self._reject(order, venue, order_id, reservation)

        record = self._book.accept(order, venue, ts, regime_tag=regime_tag,
                                   encumbrances=(reservation,),
                                   order_id=order_id)
        if record.time_in_force is TimeInForce.DAY:
            # Only a plain day order joins the book at accept. An MTL reaches
            # RESTING through convert_residue and nothing else rests at all --
            # putting an MOK or an ATO on a book is *the* shape-4 failure.
            record = self._book.rest(order_id, ts)
        return Accepted(order_id=order_id, ts=ts, venue=venue,
                        encumbrances=record.encumbrances, state=record.state)

    def cancel(self, order_id: OrderId) -> Union[Cancelled, Rejected]:
        """Caller cancellation, subject to the phase locks.

        The auctions are locked for their whole duration -- including LOs
        carried in from the continuous session -- the noon break is a hard
        shutdown, and HNX's post-close session is locked. Those four are
        sourced; ``PRE_OPEN`` and ``POST_CLOSE`` are ADOPTED and the refusal
        reason says so, so the log can tell the two apart.

        A partially-filled resting order is exactly the one a caller cancels,
        and the residue's encumbrance is released on the terminal edge like
        any other, through the one shared hook.

        Raises:
            KeyError: for an id this session never issued. That is a
                programming error, not a market event, and returning a
                ``Rejected`` for it would put a phantom row in the log.
        """
        record = self._require(order_id)
        phase = self._phase(record.venue,
                            observed=self._observed_phase(record.order.ticker))
        outcome = self._book.cancel(order_id, self._now, phase=phase)
        if isinstance(outcome, Rejected):
            self._count_rejection(outcome)
            return outcome
        return Cancelled(order_id=order_id, ts=self._now,
                         cancelled_quantity=outcome.remaining_quantity,
                         filled_quantity=outcome.filled_quantity)

    def amend(self, order_id: OrderId, *, quantity: Optional[int] = None,
              limit_price: Optional[Decimal] = None
              ) -> Union[Amended, Rejected]:
        """Amend a resting order, re-running admission and funding.

        An amendment is the one instruction that can change an order's funding
        requirement and its admissibility *after* admission has already run, so
        design section 5 requires it to re-run both. This composes the pieces
        ``submit`` uses, in the same order, against the amended order:

        * **Re-admission** -- the amended quantity is re-checked against the
          dated round-lot and per-order size cap, and the amended price against
          the dated tick grid and band. A quantity reduction that lands on an
          odd lot (100 -> 50 on HOSE after 2021-01-04) is refused ``ROUND_LOT``;
          a price moved outside the band is refused ``BAND_LIMIT``.
        * **Re-reservation** -- the old reservation is released and a fresh one
          taken for the amended order, so an amend-up cannot escape funding: it
          is refused ``INSUFFICIENT_CASH`` when the larger requirement is not
          funded. The release-before-take order matters because the ledger
          tests net of every live order, so the old reservation must be gone or
          it double-counts. Any refusal restores the original reservation and
          leaves the order exactly as it was.

        The dated in-place rules -- whether one amendment may change both price
        and quantity (``_may_amend_price_and_quantity``), whether priority
        survives (``_priority_preserving_at``), the phase locks, and the
        below-filled floor -- are the book's, applied last, after funding is
        secured.

        Derivatives amendment re-funding is not built yet and is refused
        rather than skipped, so a futures amend never bypasses the margin re-run.
        """
        record = self._require(order_id)
        ts = self._now
        if quantity is None and limit_price is None:
            raise ValueError(
                'amend() must change something: pass quantity, limit_price or '
                'both')

        if pool_for_venue(record.venue) is Pool.DERIVATIVES:
            return self._refuse_amend(
                order_id, ts,
                'amending a derivatives order is not yet supported; cancel and '
                'resubmit so the margin requirement is re-run')

        new_quantity = (record.original_quantity if quantity is None
                        else quantity)
        new_price = (record.order.limit_price if limit_price is None
                     else limit_price)
        amended = replace(record.order, quantity=new_quantity,
                          limit_price=new_price)

        routed = self._route(amended, order_id, ts)
        if isinstance(routed, Rejected):
            return self._reject_unrouted(amended, routed)
        venue, instrument = routed

        rules = self._rulebook.at(ts)
        state = self._market_state(amended.ticker, ts)
        phase = self._phase(venue, observed=state.session)
        state = replace(state, session=phase)
        regime_tag = self._rulebook.edition_at(ts).value

        # Re-admission: exactly the rules an amendment can newly violate.
        refusal = self._size_here(amended, venue, rules, order_id, ts)
        if refusal is None:
            tick = self._dated_tick(amended, venue, instrument, rules,
                                    order_id, ts)
            if isinstance(tick, Rejected):
                refusal = tick
            else:
                adm = self._venue_at(amended.ticker, ts, tick).admits(
                    amended, state, instrument=instrument, regime_tag=regime_tag)
                if adm.verdict is not Verdict.ADMITTED:
                    refusal = Rejected.from_admissibility(adm, order_id)
        if refusal is not None:
            if refusal.regime_tag is None:
                refusal = replace(refusal, regime_tag=regime_tag)
            return self._count_rejection(refusal)

        # Re-reservation: release the old, take the new; restore on refusal.
        self._securities.release(order_id, ts)
        new_res = self._reserve(amended, order_id, venue, state, rules, ts,
                                instrument)
        if isinstance(new_res, Rejected):
            self._reserve(record.order, order_id, venue, state, rules, ts,
                          instrument)
            if new_res.regime_tag is None:
                new_res = replace(new_res, regime_tag=regime_tag)
            return self._count_rejection(
                self._annotate_segregation(new_res, venue))

        outcome = self._book.amend(
            order_id, ts, quantity=quantity, limit_price=limit_price,
            phase=phase,
            allow_price_and_quantity=self._may_amend_price_and_quantity(ts),
            priority_preserving=self._priority_preserving_at(ts, venue),
            encumbrances=(new_res,))
        if isinstance(outcome, Rejected):
            # A dated in-place rule refused after the swap: put the original
            # reservation back and leave the order unchanged.
            self._securities.release(order_id, ts)
            self._reserve(record.order, order_id, venue, state, rules, ts,
                          instrument)
            return self._count_rejection(outcome)
        return outcome

    def _priority_preserving_at(self, ts: datetime, venue: Venue) -> bool:
        """Whether priority-preserving amendment exists on this venue and date.

        HOSE before 2022-03-31: amendment was cancel-and-re-enter and time
        priority **always** restarted (QD 352 Dieu 17.1-17.3), so no in-place
        amendment preserves priority. From 2022-03-31 (VNX QD 17 Dieu 22.3)
        priority is preserved on a quantity reduction, which the book's
        ``amendment_preserves_priority`` applies. HNX, UPCoM and HNXDS use that
        structural rule throughout the window.
        """
        if venue is Venue.HSX and ts.date() < date(2022, 3, 31):
            return False
        return True

    def orders(self, *, state: Optional[OrderState] = None,
               ticker: Optional[str] = None) -> Tuple[OrderRecord, ...]:
        """The caller's own orders, in the sequence the exchange received them.

        Section 5 writes ``orders(status=OrderStatus.RESTING)``; the parameter
        is ``state`` and the enum is ``OrderState``, because
        ``core.order.OrderStatus`` has no ``RESTING`` member and carries
        eighteen broker-round-trip states a simulated exchange has no analogue
        for.
        """
        return self._book.orders(state=state, ticker=ticker)

    def poll(self) -> List[Event]:
        """Drain events since the last read of :meth:`poll` or :meth:`advance_to`.

        **One cursor, destructive, single-consumer.** ``advance_to()`` returns
        the events it generated *and* consumes them, so a following ``poll()``
        is empty. That is acceptable because design section 3 puts every
        reporting concern on the caller's side; a caller who wants a log keeps
        the list this returns.
        """
        drained = list(self._events)
        self._events.clear()
        # The book journals every event as well as forwarding it here, so its
        # journal holds the same rows this cursor has just delivered. Emptying
        # it keeps one cursor authoritative and stops the journal growing for
        # the life of the run.
        self._book.drain_events()
        return drained

    # -- state the exchange legitimately knows --------------------------

    def holdings(self, ticker: str) -> Holding:
        """Settled, committed, and the open unsettled tranches.

        ``sellable = settled - committed``: **net of live orders**, which is
        what stops two resting sells sharing one parcel. The unsettled
        tranches are a list of ``(quantity, settles_at)`` and never a scalar
        pair -- two parcels bought on consecutive days settle at different
        instants and neither may borrow the other's eligibility.
        """
        return self._securities.holding(ticker)

    def apply_corporate_action(
        self, action: CorporateAction, *, ts: Optional[datetime] = None,
    ) -> CorporateActionApplied:
        """Apply an exogenous corporate action to the securities holdings.

        A corporate-action feed (dividends, splits, rights) is **exogenous
        data**, so the caller supplies the event and the session applies it to
        the account it holds -- scaling the held quantity and crediting the
        cash leg, with market value conserved across the ex-date (A26). This is
        the session-level entry point for the caller-driven engine that a raw
        ``SecuritiesAccount`` otherwise had to reach directly; it is
        deliberately **not** wired into :meth:`advance_to`, because the session
        carries no corporate-action feed of its own.

        The entitlement is computed on the held total, so a parcel bought on
        the last cum-rights session and still unsettled on the ex-date is
        included -- which is exactly whom the T+2 record date is set to catch.

        ``ts`` defaults to :meth:`now`. Returns the applied record (cash leg,
        holding before and after, whether the cash leg is gross) so a strategy
        can reconcile the event it just booked.
        """
        ts = ts if ts is not None else self._now
        engine = CorporateActionEngine(CorporateActionSchedule(()))
        return engine.apply(action, account=self._securities, ts=ts)

    def cash(self) -> Cash:
        """Settled cash, what live orders have committed, and pending proceeds.

        ``available`` excludes pending proceeds unless the broker's sale
        advance is on. Equity is 100% pre-funded and unadvanced proceeds are
        not money yet, which is why sell-then-rebuy on the same day is not
        possible on settled cash alone.
        """
        return self._securities.cash()

    def positions(self) -> Dict[str, ContractPosition]:
        """The net-signed contract ledger. One row per contract, never per fill."""
        return self._derivatives.positions()

    def margin(self) -> MarginView:
        """The account-level margin view at :meth:`now`.

        The **whole account**, never a position: ``MR = IM + VM`` over the
        portfolio with ``VM`` counted only when the account is in loss, tested
        as ``utilisation = MR / margin assets``. Vietnam publishes no
        maintenance margin ratio at any date in 2020-2026, so there is no
        maintenance fraction of notional to compare against, and the
        thresholds are broker terms rather than market law.
        """
        return self._derivatives.margin(
            self._marks(), self._rulebook.at(self._now),
            self._config.broker_profile.terms, self._now,
            resting=self._live_derivative_orders())

    def outstanding_call(self) -> Optional[datetime]:
        """The cure deadline of an unanswered margin call, else ``None``.

        Closes the gap recorded as ``FEATURES.md`` §17 D41 and re-found by two
        validation scenarios. :meth:`margin` deliberately returns
        ``cure_by=None`` -- a deadline is state across days, not a property of
        one mark -- so before this accessor existed the deadline was stamped
        on the ``MARGIN_CALL`` event and **nowhere else**. A caller that polls
        its account rather than draining the cursor, or one that restarted,
        could not find out when it had to pay.

        Pair it with :meth:`in_forced_breach`: this answers *"by when"*, that
        answers *"is the account already being processed"*.
        """
        return self._monitor.outstanding_call

    def in_forced_breach(self) -> bool:
        """A forced close has been reported and nothing has cured it.

        Distinct from ``margin().status is FORCED``: an account that slips
        from the forced rung back to the call rung without ever reaching the
        warning rung is still being processed, and :meth:`margin` reports the
        rung while the monitor latches the processing. The two disagreeing is
        the documented latch, not a defect -- but a caller could previously
        only see one of them.
        """
        return self._monitor.in_forced_breach

    def charges(self) -> Tuple[Charge, ...]:
        """Everything debited or withheld so far, itemised, across both pools.

        Merged from two places because they are two pools: ``CashLedger`` owns
        the securities half and refuses a derivatives-pool charge by design,
        and ``DerivativesAccount`` has no charge ledger at all. Ordered by
        instant, then pool, then kind, so a run's charge log is stable.

        Charges are reported and debited; they are never netted into a return,
        because Plutus computes no returns.
        """
        merged = list(self._securities.cash_ledger.charges())
        merged.extend(self._deposit_charges)
        merged.sort(key=lambda c: (c.ts, c.pool.value, c.kind))
        return tuple(merged)

    def transfer(self, source: Pool, destination: Pool,
                 amount: Decimal) -> Union[Transferred, Rejected]:
        """Move cash between the two segregated pools. Always explicit.

        **No auto-transfer exists in Vietnam.** Derivatives margin sits in a
        segregated deposit account with its own purchasing power, so a caller
        who lets the deposit run short while holding securities cash gets a
        margin call -- which is the real behaviour, not a modelling artefact.

        Bounded by the **net** figure in both directions: out of securities by
        ``Cash.available``, so money already committed to a resting buy cannot
        be moved; out of the deposit by ``MarginView.free_deposit``, which is
        what stops a caller withdrawing the margin backing an open position.

        Arrival is immediate during trading hours -- an **adopted assumption**,
        not a sourced fact. Intraday transfer timing is not modelled.
        """
        if source is destination:
            raise ValueError(
                f'a transfer must move between the two pools, got '
                f'{source.value} -> {destination.value}')
        if amount <= 0:
            raise ValueError(
                f'a transfer must move a positive amount, got {amount}')
        ts = self._now
        if source is Pool.SECURITIES:
            available = self._securities.cash().available
            if amount > available:
                return self._count_rejection(Rejected(
                    rule=StatefulRule.INSUFFICIENT_CASH,
                    binding_constraint=available, ts=ts,
                    detail={'requested': amount, 'available': available,
                            'pool': Pool.SECURITIES}))
            self._securities.cash_ledger.debit(
                amount, ts, reason='transfer to the derivatives deposit')
            return self._derivatives.transfer_in(amount, ts)

        outcome = self._derivatives.transfer_out(
            amount, self._marks(), self._rulebook.at(ts), ts,
            terms=self._config.broker_profile.terms,
            resting=self._live_derivative_orders())
        if isinstance(outcome, Rejected):
            return self._count_rejection(outcome)
        self._securities.cash_ledger.credit(
            amount, ts, reason='transfer from the derivatives deposit')
        return outcome

    # -- provenance -----------------------------------------------------

    def provenance(self) -> SessionProvenance:
        """What this run was configured with, every pin recorded as an override.

        A pinned run reports that it was pinned -- the difference between a
        counterfactual and a lie. ``settlement_calendar_id`` is here for the
        same reason: the default weekday-only calendar is wrong around every
        Tet in the period and its id says ``UNSOURCED``, so a published result
        cannot hide behind it.

        ``fill_policy_kind`` carries the policy's full *signature*, not just
        its kind: ``hard`` at a 10% participation cap and ``hard`` at 100% are
        different assumptions and produce different fills, so the kind alone
        cannot reproduce a result.

        ``liquidation_rule`` is read off the **monitor this session is
        running**, never off the enum's default. A constant here reported
        ``largest_loss_first`` for a session configured pro rata, which is the
        one failure a provenance record cannot have: an unrecorded assumption
        is a gap, but a recorded wrong one is a false claim that reads as
        evidence.

        The three ``margin_model*`` fields are ``None``/``False`` for a session
        configured without a firm's margin profile. That is deliberate: a
        session that selected nothing must not report a selection. When a firm
        *is* named, ``margin_model_is_assumed`` is the honest half of the
        record -- five of the shipped profiles publish a ladder and no formula,
        and a result from one of those is our divisor under their levels.

        **``exercised`` and ``unexercised`` are the difference between what a
        run was configured with and what it ran.** Everything above this
        paragraph is configuration, and configuration is not execution: a
        record naming a margin model, a fill policy and a liquidation rule is
        entirely true of a session in which none of the three was ever
        invoked. That is not hypothetical -- it is what the fidelity audit
        found -- so the record carries the wiring as well, and a stored result
        can be checked for it without re-running. See :class:`Component`.
        """
        profile = self._config.broker_profile
        margin_profile = getattr(profile, 'margin_profile', None)
        model = None if margin_profile is None else margin_profile.margin_model
        return RunProvenance(
            rulebook_id=self._config.exchange_rules.rulebook,
            resolution=self._config.resolution,
            period_start=self._config.period_start,
            period_end=self._config.period_end,
            venues=self._venues,
            fill_policy_kind=getattr(self._policy, 'signature',
                                     self._policy.kind),
            broker_profile_name=profile.name,
            pins=self._rulebook.pins,
            settlement_calendar_id=getattr(self._settlement, 'calendar_id',
                                           None),
            liquidation_rule=self._liquidation_rule(),
            margin_model=None if model is None else model.name,
            margin_model_engine=(None if model is None
                                 else model.engine
                                 or 'plutus.market.session.deposit'),
            margin_model_is_assumed=(model is not None and model.engine is None),
            block_opening_utilisation=getattr(
                profile, 'block_opening_utilisation', None),
            exercised=tuple(sorted(self._exercised)),
            unexercised=self._unexercised(),
            overnight_model=(self._overnight[-1].model
                             if self._overnight else None),
            overnight_engine=(self._overnight[-1].engine
                              if self._overnight else None),
            overnight_determinate=sum(1 for r in self._overnight
                                      if r.is_determinate),
            overnight_indeterminate=sum(1 for r in self._overnight
                                        if not r.is_determinate),
        )

    def _unexercised(self) -> Tuple[str, ...]:
        """Components this run required and never invoked, sorted.

        One reader, used by :meth:`provenance` and :meth:`indeterminate_report`
        alike, for the reason :meth:`_liquidation_rule` is one: the record and
        the meter must not be able to disagree about the same fact.
        """
        return tuple(sorted(name for name in self._needed
                            if not self._exercised.get(name)))

    def _liquidation_rule(self) -> LiquidationRule:
        """The selection rule this session's forced closes are reported under.

        One reader for the monitor's ``liquidation``, used by
        :meth:`provenance` and by :meth:`_mark_derivatives`, so the record and
        the event cannot disagree. ``getattr`` with a default because
        ``monitor`` is an injection point and a caller's own monitor need only
        satisfy ``on_mark``; a monitor that states no rule falls to the
        contract's declared default rather than to nothing, since a forced
        close must state *some* rule.
        """
        return getattr(self._monitor, 'liquidation',
                       LiquidationRule.LARGEST_LOSS_FIRST)

    def _execute_forced_close(self, marks: Mapping[str, Decimal],
                              rule: LiquidationRule, ts: datetime,
                              ) -> Tuple[Tuple[str, str], ...]:
        """MUST #3: close positions in a forced breach with real orders.

        The equity *ban giai chap* executes through :meth:`submit`, and so does
        this. Each offsetting order -- sell a long, buy back a short, in the
        selection rule's order -- faces the same band, tick, lot and fill
        policy as any order, which is exactly why a locked book refuses it
        (``BAND_LOCK``) and the position rides. That refusal is the measured
        17.6% permissive cost the report alone hid, and reporting it truthfully
        is the point of the loop.

        A contract that already carries a live order (a close from an earlier
        session that has not filled, or one the caller placed) is skipped, so a
        resting close is never re-submitted into a double. The close is priced
        at the contract's current mark: on a tradeable day that is marketable
        and fills at the next advance; on a locked day it is at the band and is
        refused.

        Returns ``(contract_code, verdict)`` for each leg it acted on.
        """
        positions = self._derivatives.positions()
        if not positions:
            return ()
        live = {record.order.ticker
                for record in self._live_derivative_orders()}
        sequence = liquidation_sequence(self._derivatives, marks, rule) \
            or tuple(sorted(positions))
        placed: List[Tuple[str, str]] = []
        submitted_any = False
        for code in sequence:
            position = positions.get(code)
            if position is None or position.net_quantity == 0 or code in live:
                continue
            state = self._market_state(code, ts)
            side = Side.SELL if position.net_quantity > 0 else Side.BUY
            # Price at the band edge so the close is marketable regardless of
            # which way the mark moved -- the floor for a sell, the ceiling for
            # a buy. On a locked book the edge IS the mark and the order is
            # refused BAND_LOCK, which is the position riding, correctly. Fall
            # back to the mark when the band is unknown.
            edge = state.floor if side is Side.SELL else state.ceiling
            price = edge if edge is not None else getattr(state, 'last', None)
            if price is None:
                continue          # no mark to price the close on a blind session
            result = self.submit(Order(
                ticker=code, side=side, quantity=abs(position.net_quantity),
                order_type=OrderType.LIMIT, limit_price=price))
            placed.append((code, type(result).__name__))
            submitted_any = submitted_any or isinstance(result, Accepted)
        # The forced close is an intraday event on the breach day: fill it in
        # the same advance rather than leaving it to a next-day evaluation that
        # a day order would not survive. Re-running the fill pass is safe --
        # terminal orders are skipped and a NO_FILL records nothing.
        if submitted_any:
            self._evaluate_fills(ts)
        return tuple(placed)

    def indeterminate_report(self) -> RunIgnorance:
        """How much of the run rested on something the run did not have.

        Design section 9.2 requires the session to report this rate, and
        section 8 makes it the honest headline: **a bound on ignorance, not a
        fill rate.** This docstring states the bound's *scope*, because a
        meter whose scope is undocumented invites the mistake it was built to
        prevent -- and did: ``indeterminate`` answered **zero** on every
        failure an independent fidelity audit found.

        What each field counts
        ----------------------
        ``evaluations``
            Questions this session put to the data and had to answer before it
            could act: one per live order per :meth:`advance_to` that reached
            the fill policy, **plus** one per derivatives mark, one per
            expiry settlement it could not price, and one per **overnight**
            requirement (:meth:`_overnight_margin`, once per session after the
            close). Four populations in one denominator, so the rate moves
            with how often the caller samples the clock -- a known defect of
            the figure, recorded here rather than in a comment.
        ``indeterminate``
            The subset of those the data could not decide: a fill policy
            answering ``INDETERMINATE``, a mark with a stale contract, an
            expiry with no settlement price, an overnight requirement whose
            parameters were not available. The last of those is **never** a
            silent fall back to the intraday number -- that substitution is
            the direction that costs a user money, and
            ``margin.overnight.uncomputed.<gap>`` names the input that was
            missing.
        ``by_field``
            The :class:`DataField` named **on an ``INDETERMINATE``** -- a
            decision *not* taken. Never a decision taken anyway.
        ``by_rule``
            ``INDETERMINATE`` **rejections** at ``submit()``, by admission
            rule. A different population over a different denominator, and
            deliberately not summed into the two above.

        What those four structurally cannot see
        ---------------------------------------
        Each of these was a real, measured zero, and each now has a counter:

        1. **A decision taken without the data.** ``by_field`` is written only
           on an ``INDETERMINATE``, so a full-size ``soft`` fill on a bar with
           no volume, no high and no low counted nothing at all. Now
           ``silent_ignorance['fill.decided_without.volume']`` and its
           siblings -- see :meth:`_audit_fill`.
        2. **A configuration the running policy could not honour.** Every
           config states a participation cap and not every policy carries
           one. An uncapped fill under a config naming 10% is now
           ``'participation_cap.not_applied'``; a cap carried but not
           computable, and a cap computed and exceeded, are kept apart from it
           because the remedies differ -- see :meth:`_audit_fill`.
        3. **A rule passed over rather than tested.** An unsourced per-order
           size cap refuses nothing (:meth:`_size_here`) and an unsourced
           margin mechanism marks on ``IM + VM`` anyway
           (:meth:`_mark_derivatives`). Both are now counted.
        4. **An order never evaluated at all.** No bar, or no venue at that
           instant, and the loop simply skipped it -- indistinguishable in
           every published number from an order the market never reached.
        5. **A component that never ran.** The general case, and the reason
           for :class:`Component`: a margin layer returning 0 because nothing
           called it looked exactly like one that computed 0. Now
           :attr:`RunIgnorance.unexercised`. The instance that named the
           class was the overnight layer -- ``scenario_margin.py``, 1,069
           executable lines with **zero call sites** -- and it is now
           :attr:`Component.OVERNIGHT_MARGIN`, exercised or listed.

        What is *still* outside the bound, and would need work elsewhere:
        rules resolved correctly but from a LOW-confidence rulebook row (the
        rulebook's own citations carry that, not this record); a component
        invoked with wrong arguments (this counts invocations, not
        correctness); and the sampling artefact in ``evaluations`` noted
        above.

        Read :attr:`RunIgnorance.is_clean`, never ``indeterminate == 0``.
        """
        return RunIgnorance(
            evaluations=self._evaluations,
            indeterminate=self._indeterminate,
            by_field=dict(self._by_field),
            by_rule=dict(self._by_rule),
            silent_ignorance=dict(self._silent),
            exercised=dict(self._exercised),
            unexercised=self._unexercised(),
        )

    def instrument(self, ticker: str,
                   ts: Optional[datetime] = None) -> InstrumentSpec:
        """The instrument as of ``ts`` (default :meth:`now`).

        Delegates to ``SymbolRouter`` -- a per-event call, never a cached
        lookup. A ticker-keyed instrument cache is locked shape 1's forbidden
        build: for a transferred ticker it assigns the wrong venue's tick, lot
        and band to every row on the other side of the transfer.
        """
        return self._router.instrument(
            ticker, ts if ts is not None else self._now)

    def __repr__(self) -> str:
        return (f'ExchangeSession(now={self._now.isoformat()}, '
                f'venues={[v.value for v in self._venues]}, '
                f'orders={len(self._book)})')

    # ==================================================================
    # Internals
    # ==================================================================

    def _next_seq(self) -> int:
        """The session-level event sequence. One counter, one total order."""
        self._seq += 1
        return self._seq

    def _emit(self, event: Event) -> Event:
        self._events.append(event)
        return event

    def _next_fill_id(self) -> str:
        self._fills_issued += 1
        return f'FILL-{self._fills_issued:06d}'

    def _require(self, order_id: OrderId) -> OrderRecord:
        record = self._book.get(order_id)
        if record is None:
            raise KeyError(
                f'order {order_id!r} is not in this session\'s book of record; '
                f'an id names one submission for the life of the session')
        return record

    # -- routing and phase ----------------------------------------------

    def _route(self, order: Order, order_id: OrderId, ts: datetime
               ) -> Union[Tuple[Venue, Optional[InstrumentSpec]], Rejected]:
        """``(venue, instrument)`` as of ``ts``, or why neither could be had.

        Both lookups are per-instant. The instrument matters at admission
        because ``equity.py``'s ``ROUND_LOT`` rule prefers
        ``instrument.trading_unit`` when a spec is passed -- and
        ``SymbolRouter`` overwrites that field from the dated ``RuleSet``,
        which is precisely what makes passing the spec safe rather than
        disabling the dated rule.

        A covered warrant has no percentage band at all, and
        ``InstrumentSpec.daily_trading_limit`` is a required ``Decimal``, so
        the router refuses rather than filling in the venue's 7%. That refusal
        becomes an ``INDETERMINATE`` rejection: the data could not decide,
        which is not the same as a rule saying no.
        """
        try:
            venue = self._router.venue(order.ticker, ts)
        except UnresolvedRule as exc:
            return self._unresolved(exc, order_id, ts,
                                    rule=AdmissionRule.SESSION_SEMANTICS)
        try:
            instrument = self._router.instrument(order.ticker, ts)
        except UnresolvedRule as exc:
            return self._unresolved(exc, order_id, ts)
        return venue, instrument

    def _unresolved(self, exc: UnresolvedRule, order_id: OrderId,
                    ts: datetime,
                    rule: Optional[AdmissionRule] = None) -> Rejected:
        """An ``UnresolvedRule`` as an ``INDETERMINATE`` rejection, by rule."""
        resolution = exc.resolution
        chosen = rule or _RULE_FOR_RULENAME.get(
            resolution.rule, AdmissionRule.SESSION_SEMANTICS)
        return Rejected(
            rule=chosen, binding_constraint=None, ts=ts,
            verdict=Verdict.INDETERMINATE, order_id=order_id,
            detail={'reason': resolution.note or str(resolution),
                    'unresolved_rule': resolution.rule.value,
                    'status': resolution.status.value})

    def _phase(self, venue: Venue,
               observed: Optional[SessionPhase] = None) -> SessionPhase:
        """The phase, from the adapter or the rulebook -- never from ``ts``.

        See :meth:`phase` for the daily-resolution deviation and why it is not
        inference. Note the two calendars answer different questions here: the
        *trading* calendar says whether the day trades at all, and only the
        rulebook says which phase a clock is standing in.
        """
        if self._daily:
            if observed is not None and observed is not SessionPhase.UNKNOWN:
                return observed
            try:
                trading = self._trading.is_trading_day(self._now.date())
            except CalendarError:
                return SessionPhase.UNKNOWN
            return (SessionPhase.CONTINUOUS if trading
                    else SessionPhase.POST_CLOSE)
        resolved = self._rulebook.at(self._now).phase(venue)
        if resolved is SessionPhase.UNKNOWN and observed is not None:
            return observed
        return resolved

    def _observed_phase(self, ticker: str) -> Optional[SessionPhase]:
        state = self._last_state.get(ticker)
        return state.session if state is not None else None

    def _may_amend_price_and_quantity(self, ts: datetime) -> bool:
        """Whether one amendment may change both, at this instant.

        True to 2025-05-04 (QD 17 Dieu 22.3, "sua tang khoi luong va/hoac sua
        gia"); False from 2025-05-05 (VNX QD 22/2025 Dieu 21.3, "khong duoc
        sua dong thoi thong tin khoi luong va gia tren cung mot lenh dat").
        The KRX cutover is a dated rule set, not a migration, so this resolves
        at the instant and a run spanning it gets each answer on its own side.
        """
        return self._rulebook.edition_at(ts).value == 'pre_krx'

    def _legal_here(self, order: Order, venue: Venue, phase: SessionPhase,
                    rules: RuleSet, order_id: OrderId,
                    ts: datetime) -> Optional[Rejected]:
        """The dated order-type legality the stateless ``admits()`` cannot see.

        ``Exchange.admits()`` knows which types a *call auction* accepts. It
        does not know that UPCoM has accepted nothing but an LO at any date,
        that HOSE's MP became MTL at the KRX cutover, or that
        ``OrderType.MARKET`` matches no Vietnamese type at any venue on any
        date. Those are dated rulebook facts, resolved here at the instant and
        refused with ``SESSION_SEMANTICS`` -- this venue, in this phase, at
        this date, does not accept this order type.

        It also protects ``OrderBookOfRecord.accept``, which *raises* on
        ``OrderType.MARKET`` rather than rejecting it: an MKT reaching the book
        of record means this check was skipped, which is a bug in the caller
        and not an event in the market.
        """
        self._exercise(Component.LEGAL_ORDER_TYPES)
        try:
            legal = rules.legal_order_types(venue, phase)
        except UnresolvedRule as exc:
            return self._unresolved(exc, order_id, ts)
        if order.order_type in legal:
            return None
        try:
            mnemonics = sorted(rules.legal_order_mnemonics(venue, phase))
        except UnresolvedRule:
            mnemonics = []
        return Rejected(
            rule=AdmissionRule.SESSION_SEMANTICS, binding_constraint=None,
            ts=ts, order_id=order_id,
            detail={'phase': phase.value,
                    'order_type': order.order_type.value,
                    'accepts': sorted(t.value for t in legal),
                    'mnemonics': mnemonics,
                    'reason': f'{venue.value} does not accept '
                              f'{order.order_type.value} in {phase.value} at '
                              f'this date'})

    def _size_here(self, order: Order, venue: Venue, rules: RuleSet,
                   order_id: OrderId, ts: datetime) -> Optional[Rejected]:
        """The dated per-order quantity cap. HOSE 500,000; HNXDS 500.

        ``RuleSet.max_order_size`` carried these numbers from the first
        commit and had exactly one caller in the repository -- its own test --
        so a 1,000,000-share FPT order reached the reservation and was judged
        on funding alone. The rulebook's own summary of what this package
        fixes lists it in those terms: "Maximum order size: does not exist. A
        10,000,000-share HOSE order would be admitted."

        Dated, because HOSE's cap is dated: 500,000 units per round-lot
        matching order **from 2021-01-04**, alongside the round lot that moved
        the same day. It binds before the reservation, because a size the
        exchange will not take is not a question about the account.

        **An UNKNOWN cap refuses nothing, and that is an ASSUMPTION.** HNX and
        UPCoM publish no cap in any rulebook read, and the rulebook records the
        absence rather than a number because "no cap" is an inference from
        HOSE's clause being HOSE-specific. Turning that absence into an
        ``INDETERMINATE`` would refuse *every* HNX and UPCoM order in a run --
        reporting a research gap as a market rule, which is the inversion this
        package exists to prevent -- so the total ``resolve`` path is taken and
        an unresolved cap is passed over. This is a genuine scope cut in one
        direction and it is not free: HOSE's own 2020 row is UNKNOWN too (the
        cap for the 10-lot regime was never sourced), so a 600,000-share HOSE
        order in 2020 is admitted here and may well have been refused by HOSE.
        The declared alternative -- refusing on an unsourced ceiling -- is
        worse, and the gap is visible in the rulebook rather than hidden here.
        **It is now visible in the run too**: an order passed over a cap the
        rulebook could not resolve is counted under
        ``Blindness.ORDER_SIZE_UNSOURCED``, so a run on HNX or UPCoM reports
        how many orders it admitted without ever testing this rule instead of
        reading as a run in which the rule was tested and bound nothing.

        Odd lots do not reach this rule: their 99-unit cap is the odd-lot
        definition itself, and ``admits()``'s ``ROUND_LOT`` rule refuses a
        non-multiple of the trading unit before any of it applies.
        """
        self._exercise(Component.MAX_ORDER_SIZE)
        resolution = rules.resolve(RuleName.MAX_ORDER_SIZE, venue)
        if not resolution.is_known:
            self._blind(Blindness.ORDER_SIZE_UNSOURCED)
            return None
        cap = resolution.value
        if order.quantity <= cap:
            return None
        return Rejected(
            rule=AdmissionRule.SESSION_SEMANTICS, binding_constraint=cap,
            ts=ts, order_id=order_id,
            detail={'quantity': order.quantity,
                    'max_order_size': cap,
                    'reason': f'{venue.value} caps one matching order at '
                              f'{cap} at this date, and this order carries '
                              f'{order.quantity}'})

    def _dated_tick(self, order: Order, venue: Venue,
                    instrument: Optional[InstrumentSpec], rules: RuleSet,
                    order_id: OrderId, ts: datetime
                    ) -> Union[Optional[Decimal], Rejected]:
        """The tick grid AT THIS INSTANT, for this instrument, or why not.

        The seam locked shape 1 leaves open at the **first** admission rule
        ``submit()`` runs. ``equity.py`` and ``derivatives.py`` both ask
        ``self.spec.get_tick_size(...)``, and ``self.spec`` is a module-level
        ``ExchangeSpec`` bound at import: one flat ``Decimal('0.1')`` per
        venue, with no date, no instrument kind and no contract family. The
        two neighbouring rules had their seams closed and this one did not --
        ``ROUND_LOT`` is date-correct because ``SymbolRouter.instrument``
        overwrites ``InstrumentSpec.trading_unit`` from the ``RuleSet``, and
        ``LEGAL_ORDER_TYPES`` is date-correct through :meth:`_legal_here` --
        so one file priced an MTL residue on the dated grid
        (:meth:`_residual_price`) and judged every submission on the undated
        one.

        Two failures, both verified, and they run in opposite directions:

        * **An illegal price admitted.** GB05F2306 routes to HNXDS, where the
          tick is 1 VND on a 100,000d face (HIGH confidence, from the contract
          template). The singleton returns 0.1, so a limit of 100,523.5 -- off
          the real grid -- is admitted, and the run reports a fill at a price
          HNX would never have matched.
        * **A legal order refused.** HNX's ETF tick is 0.001 from 2022-03-31
          (VNX QD 17 Phu luc III S2.2), a hundredth of the singleton's 0.1, so
          99 of every 100 legal FUEHNX01 prices come back
          ``Rejected(TICK_GRID, binding_constraint=0.1)``.

        Returns the resolved tick, ``None`` where the grid does not apply or
        no band of the price table matches, or a ``Rejected`` when the
        rulebook cannot answer. That last case is what makes
        ``_RULE_FOR_RULENAME[TICK_SIZE] -> TICK_GRID`` reachable: before this,
        no session path could raise ``UnresolvedRule(TICK_SIZE)`` at all, so a
        tick data gap was a mapping nobody could exercise rather than a
        countable line in ``indeterminate_report().by_rule``. HNX's ETF tick
        before 2022-03-31 is the live example.

        ``method`` is left at its ``ORDER_MATCHING`` default deliberately: a
        put-through is negotiated at a hundredfold finer grid, and this session
        refuses a negotiated side outright (see :meth:`_reserve`).
        """
        price = order.limit_price
        if price is None:
            # No price, no grid. `admits()` skips the rule for the market
            # family too, so resolving here would raise on HOSE's banded grid
            # for an order the rule never touches.
            return None
        kind = (instrument.kind if instrument is not None
                else InstrumentKind.STOCK)
        self._exercise(Component.TICK_SIZE)
        try:
            return rules.tick_size(venue, kind, price, ticker=order.ticker)
        except UnresolvedRule as exc:
            return self._unresolved(exc, order_id, ts)

    def _venue_at(self, ticker: str, ts: datetime,
                  tick: Optional[Decimal]) -> Exchange:
        """The venue object for ONE submission, holding the dated tick.

        **The mechanism is the router's, not this session's.**
        ``SymbolRouter.exchange`` builds the dated judge -- a shallow copy of
        the ``exchanges/`` singleton carrying an ``ExchangeSpec`` whose
        ``tick_size_function`` reads the dated ``RuleSet.tick_size``. It has
        to live there rather than here: the Tier 1 interface contract
        advertises the router as public API, and a session-private copy of the
        repair left ``router.exchange(ticker, ts)`` handing every direct
        caller the import-time grid back -- ``ts`` consumed to pick a venue
        and then thrown away. One seam, one closure of it, in the object that
        owns the ``(ticker, ts)`` question.

        What this method still owns is the *pre-resolution*. The grid is
        resolved here first, by :meth:`_dated_tick`, because
        ``RuleSet.tick_size`` raises ``UnresolvedRule`` where the rulebook
        carries no row -- HNX's ETF tick before 2022-03-31 -- and the session
        must report that as ``Rejected(verdict=INDETERMINATE)`` filed under
        ``TICK_GRID`` rather than let it escape from inside ``admits()``.
        Passing the resolved value on as ``tick_size`` pins the judge to the
        exact number this session already reported on, instead of trusting two
        independent resolutions to agree.

        ``tick`` is ``None`` for an order with no limit price -- where the
        installed function is never called -- and for a price that matches no
        band of HOSE's table, where ``admits()`` reads the ``None`` and
        answers ``INDETERMINATE`` on ``TICK_GRID``, which is the behaviour
        ``get_hsx_tick_size`` has always had and which this preserves.
        """
        return self._router.exchange(
            ticker, ts, tick_size=lambda _ticker, _price: tick)

    # -- market data ----------------------------------------------------

    def _observe(self, ticker: str, ts: datetime) -> Optional[MarketState]:
        """The source's state at an instant, repaired and cached.

        **Never returns ``band_source=None``.** ``adapters/tick.py`` can build
        one and ``equity.py`` reads ``state.band_source.value``
        unconditionally, so a ``None`` there raises ``AttributeError`` instead
        of returning ``INDETERMINATE`` -- an upstream landmine every author at
        this seam hits.
        """
        if self._source is None:
            return None
        state = self._source.state_at(ticker, ts)
        if state is None:
            return None
        if state.band_source is None:
            state = replace(state, band_source=BandSource.ABSENT)
        self._last_state[ticker] = state
        return state

    def _market_state(self, ticker: str, ts: datetime) -> MarketState:
        """:meth:`_observe`, or an explicitly empty state.

        An empty state is not a neutral one: with no ceiling and no floor,
        ``admits()`` answers ``INDETERMINATE`` on ``BAND_LIMIT``, which keeps
        the order out and counts as ignorance rather than as a rule saying no.
        That is the correct outcome for an instrument the data does not cover.
        """
        state = self._observe(ticker, ts)
        if state is not None:
            return state
        return MarketState(ticker=ticker, ts=ts,
                           band_source=BandSource.ABSENT,
                           session=SessionPhase.UNKNOWN)

    @staticmethod
    def _refuse_unserveable_resolution(
        config: SessionConfig,
        source: Optional[MarketDataSource],
    ) -> None:
        """Refuse a resolution the source has declared it cannot serve.

        **At construction, and that is the whole point.** ``resolution: tick``
        with the shipped ``DataHubSource`` used to build a session, accept
        orders, encumber the cash behind them, and then raise ``ValueError``
        out of the first :meth:`advance_to` that had a live order --
        :meth:`_interval_for` calls ``source.interval(...,
        resolution=self._config.resolution)`` and catches nothing, and that
        adapter raises for anything but ``DAILY``. A run that dies mid-flight
        with state already moved is the one outcome that is wrong here; the
        two defensible ones are a source that answers and a configuration that
        is refused, and this is the second delivered before it costs anything.

        The adapter's refusal is **not** the defect and is not softened. An
        unserveable resolution is not an absence: answering ``None`` would
        have the session synthesise a bar with the OHLC and volume fields
        named missing, on which ``hard`` and ``probabilistic`` would return
        ``INDETERMINATE`` -- but an uncapped ``soft`` would *fill*, at the
        daily close, in a session the caller asked to run at tick resolution.
        A silent fill at the wrong resolution is the permissive direction and
        the one this package may not err in. See ``IntervalSource``.

        **A source that declares nothing is not checked.**
        ``SERVES_RESOLUTIONS`` is an optional class attribute, read with
        ``getattr``, and not a member of the ``IntervalSource`` protocol:
        adding one there would fail the ``isinstance`` in
        :meth:`_interval_for` for every source that lacks it and silently
        downgrade it to synthesised intervals, which is a worse failure than
        the one being fixed. So this is a check that catches the shipped
        adapter and any source that opts in, and is stated as exactly that
        rather than as a guarantee it cannot make.

        Raises:
            ValueError: naming the configured resolution, what the source
                serves, and the adapter to use instead.
        """
        declared = getattr(source, 'SERVES_RESOLUTIONS', None)
        if declared is None or config.resolution in declared:
            return
        served = ', '.join(sorted(r.value for r in declared)) or '(none)'
        raise ValueError(
            f'{type(source).__name__} cannot serve resolution '
            f'{config.resolution.value!r}; it serves {served}. A session '
            f'configured this way would build, accept orders and encumber '
            f'cash for them, and then fail on the first advance with a live '
            f'order, so it is refused here instead. Set resolution to one it '
            f'serves, or use an adapter that serves this one -- '
            f'plutus.market.adapters.tick.TickSource for Resolution.TICK'
        )

    def _interval_for(self, ticker: str, ts: datetime,
                      state: MarketState) -> MarketInterval:
        """The interval a fill policy evaluates, with absences **named**.

        A source implementing :class:`IntervalSource` answers directly. One
        that does not gets an interval synthesised from the snapshot: the last
        matched price becomes ``close``, and every OHLC and volume field the
        adapter contract cannot supply is listed in ``missing`` rather than
        left silently ``None``. That is what makes
        :meth:`indeterminate_report` a measurement instead of a guess, and it
        is why ``HardFillPolicy`` on today's corpora is ``INDETERMINATE``
        wherever it would otherwise fill.

        The interval spans ``[ts, ts + one bar)``, half-open, matching
        ``MarketDataSource.states()``. On a daily run that is the whole
        trading day the bar stands for -- so an order entered at 14:00 is
        evaluated against the whole day, an over-generosity that is a declared
        consequence of the resolution and not something a fill policy may
        silently correct.

        **The served ``resolution`` is the session's, and a source that cannot
        serve it raises.** That is not caught here, deliberately: the
        configuration is refused at construction by
        :meth:`_refuse_unserveable_resolution` for any source that declares
        what it serves, so a raise reaching this line means a source that
        declared nothing and cannot honour the contract. Swallowing it would
        substitute a synthesised bar for an answer the source has just said it
        does not have, which for an uncapped ``soft`` is a silent fill at the
        wrong resolution.

        What is served is **not** re-checked against the request. A source may
        answer a tick request with a day's bar -- ``PhasedBarSource`` does,
        and says so -- and that is the source's declared assumption to make,
        not something this method may overrule. It does bear on the
        participation cap, which is why :attr:`_filled_in_bar` is keyed on the
        trading date rather than on the requested window.
        """
        span = timedelta(days=1) if self._daily else timedelta(seconds=1)
        source = self._source
        if isinstance(source, IntervalSource):
            served = source.interval(ticker, ts, ts + span,
                                     resolution=self._config.resolution)
            if served is not None:
                return served
        missing = {DataField.OPEN, DataField.HIGH, DataField.LOW,
                   DataField.VOLUME, DataField.BOOK_SIZE}
        close = state.last
        if close is None:
            missing.add(DataField.LAST)
            missing.add(DataField.CLOSE)
        # D71: a synthesised interval carries no published open OR close to hand
        # a call auction. OPEN is always absent (interval.open is never set), so
        # an ATO is already INDETERMINATE; without the same for CLOSE an ATC
        # would cross at ``state.last`` -- a pre-auction print -- under the
        # published close's name (fills.auction_fill_price returns interval.close
        # directly). In an auction phase drop the close and name it missing, so
        # the ATC returns the published close where an IntervalSource supplies
        # one (handled above) and INDETERMINATE on a bare snapshot, exactly as
        # the ATO does.
        #
        # Expiry settlement is unaffected, though NOT because it skips
        # interval.close -- ``_final_settlement`` reads interval.close first and
        # falls back to state.last. It is safe because the settlement interval
        # is built from the raw observed state, not this fill path's rulebook
        # re-stamp, and both shipped adapters stamp CONTINUOUS, so this auction
        # branch never fires there; and were it to, the close it drops was only
        # ever state.last -- the exact value the fallback then supplies.
        if state.session in (SessionPhase.OPENING_AUCTION,
                             SessionPhase.CLOSING_AUCTION):
            close = None
            missing.add(DataField.CLOSE)
        return MarketInterval(
            ticker=ticker, start=ts, end=ts + span,
            resolution=self._config.resolution, state=state,
            close=close, missing=frozenset(missing))

    # -- equity margin lending -------------------------------------------

    def securities_cash_ledger(self) -> CashLedger:
        """The securities cash ledger, for the equity margin account.

        A margin loan is a **credit to the client's own cash** and its
        repayment is a debit -- QD 87 Dieu 2 khoan 5 counts the disbursed dong
        in ``CB`` like any other *tien*. There is no second pool: TT 120 Dieu
        9.3's segregation is per investor, not per product, and the margin
        account **is** the securities account at a firm the client margins at.

        Exposed rather than reached for, so the one module that needs it does
        not have to touch ``session._securities``. Nothing else in this package
        calls it.
        """
        return self._securities.cash_ledger

    def _margin_gate(self, order: Order, order_id: OrderId, venue: Venue,
                     state: MarketState, ts: datetime) -> Any:
        """Step 4b: QD 87 Dieu 13.5(d), for an ``on_margin`` order only.

        Runs **after** ``admits()`` and **before** the reservation, and both
        halves of that matter. After ``admits()``, because an order off the
        tick grid is a tick-grid rejection whether or not the client could have
        borrowed for it -- the same rule that puts the cash reservation last.
        Before the reservation, because the reservation tests ``Cash.available``
        and the borrowed dong must be in it by then.

        A session with no margin account **refuses**. Treating the order as an
        ordinary cash buy would silently unlever the strategy and report the
        result as if that was what was asked for; the flag is on the ticket and
        an unhonoured flag is a defect, not a default.
        """
        if pool_for_venue(venue) is not Pool.SECURITIES:
            return Rejected(
                rule=StatefulRule.MARGIN_LENDING, binding_constraint=None,
                ts=ts, order_id=order_id,
                detail={'reason': 'giao dich ky quy is equity margin lending '
                                  'under QD 87/QD-UBCK. A derivatives order '
                                  'margins against the segregated VSDC deposit '
                                  '-- a different product, a different '
                                  'regulator and a different call test',
                        'venue': venue.value})
        if self._equity_margin is None:
            return Rejected(
                rule=StatefulRule.MARGIN_LENDING, binding_constraint=None,
                ts=ts, order_id=order_id,
                detail={'reason': 'this order is flagged on_margin and the '
                                  'session has no equity margin account. '
                                  'TT 120 Dieu 9.1 / QD 87 Dieu 12.1 make the '
                                  'hop dong giao dich ky quy the credit '
                                  'agreement: with no account there is no '
                                  'contract and no lending to discuss',
                        'article': 'TT 120 Dieu 9.1'})
        self._exercise(Component.EQUITY_MARGIN_GATE)
        return self._equity_margin.gate(self, order, order_id, state, ts)

    # -- reservation ----------------------------------------------------

    def _reserve(self, order: Order, order_id: OrderId, venue: Venue,
                 state: MarketState, rules: RuleSet, ts: datetime,
                 instrument: Optional[InstrumentSpec],
                 ) -> Union[Encumbrance, Rejected]:
        """Step 5: reserve, tested net of every live order. Locked shape 2.

        Which pool is a routing fact, not an instrument fact: equity orders
        draw on securities cash only and futures margin draws on the
        segregated deposit only, with no path between them. The three
        reservation shapes belong to the two account objects and none of their
        arithmetic is repeated here.

        An unresolvable contract multiplier is caught here and reported as
        ``INDETERMINATE``, for the same reason ``UnresolvedRule`` is:
        ``IM = ratio x contracts x price x multiplier`` is linear in the
        multiplier, so answering with a plausible one does not blur the number,
        it scales it -- and the resulting ``INSUFFICIENT_DEPOSIT`` would blame
        the balance for what was a unit gap. The data could not decide, which
        is not the same as a rule saying no.
        """
        if pool_for_venue(venue) is Pool.DERIVATIVES:
            price = self._margin_price(order, state)
            if price is None:
                return Rejected(
                    rule=AdmissionRule.BAND_LIMIT, binding_constraint=None,
                    ts=ts, verdict=Verdict.INDETERMINATE, order_id=order_id,
                    detail={'reason': 'no price to margin this order at: a '
                                      'market-family derivative order is '
                                      'margined at the current mark and none '
                                      'has been observed',
                            'order_type': order.order_type.value})
            self._exercise(Component.DERIVATIVES_FUNDING)
            # A run that margins an order at entry requires the layer that
            # marks it afterwards. Declared here rather than from the config's
            # venue list, so a session merely *configured* for HNXDS that
            # never trades a contract is not reported as missing a layer it
            # never needed.
            self._needs(Component.DERIVATIVES_MARK)
            self._needs(Component.DERIVATIVES_LADDER)
            try:
                return self._derivatives.reserve_for_order(
                    order_id, order, price, rules,
                    self._config.broker_profile, ts)
            except UnknownContractMultiplier as exc:
                # SESSION_SEMANTICS is what ``_unresolved`` files any rule with
                # no dedicated admission bucket under; ``detail`` carries the
                # rule name so a report can still count multiplier gaps
                # separately. The permanent home is a
                # ``RuleName.CONTRACT_MULTIPLIER`` row in ``rulebook.py`` --
                # see ``deposit.UnknownContractMultiplier``.
                return Rejected(
                    rule=AdmissionRule.SESSION_SEMANTICS,
                    binding_constraint=None, ts=ts,
                    verdict=Verdict.INDETERMINATE, order_id=order_id,
                    detail={'reason': str(exc),
                            'unresolved_rule': 'contract_multiplier',
                            'status': 'unknown',
                            'contract_code': exc.contract_code})

        cls_ = charge_class_for(instrument.kind if instrument is not None
                                else InstrumentKind.STOCK)
        if order.side is Side.BUY:
            self._exercise(Component.SECURITIES_FUNDING)
            return self._securities.reserve_for_buy(
                order_id, order, venue, state, rules, ts, cls_=cls_)
        if order.side is Side.SELL:
            self._exercise(Component.SECURITIES_FUNDING)
            return self._securities.reserve_for_sell(order_id, order, venue, ts)
        raise ValueError(
            f'{order.side} is a negotiated put-through, not order matching; '
            f'this session models order matching only')

    def _margin_price(self, order: Order,
                      state: MarketState) -> Optional[Decimal]:
        """The price a derivative order's initial margin is taken at.

        The limit price for a limit order and the current mark for the market
        family, because those are the only two prices the order could actually
        transact at. There is deliberately **no fallback to the band**: a
        futures ceiling is 7% above the reference, and margining an order
        there would over-reserve by a factor the caller cannot see and would
        call it a market rule.
        """
        if order.order_type not in _MARKET_FAMILY and order.limit_price:
            return order.limit_price
        for candidate in (state.last, state.reference):
            if candidate:
                return candidate
        try:
            return self._derivatives.mark_for(order.ticker)
        except KeyError:
            return None

    def _annotate_segregation(self, rejection: Rejected,
                              venue: Venue) -> Rejected:
        """Say, on a funding refusal, what the *other* pool could have done.

        **This is the pair-trading refusal.** The canonical Vietnamese pair
        trade is a VN30 basket on HSX against VN30F on HNXDS, and its two legs
        draw on two segregated accounts with independent purchasing power:
        the equity leg spends securities cash, the futures leg spends the
        derivatives deposit, and **no auto-transfer exists between them**
        (design section 7.3; rulebook 6.3, "Where margin is held;
        segregation", confidence HIGH). So a pair the account can fund *in
        aggregate* can still be refused on one leg -- which is precisely the
        behaviour that makes a Vietnamese pair trade different from a Western
        one, where a single margin account would have netted the two.

        ``Rejected`` already names the rule and the number that bound. What it
        could not say is *which of two very different situations* the caller
        is in:

        * ``funded_in_aggregate`` is True -- the other pool holds at least the
          shortfall. One ``transfer()`` of ``shortfall`` and the same order
          fits. The trade is fundable; the account is merely mis-partitioned.
        * ``funded_in_aggregate`` is False -- the money is not there at all.
          Transferring cannot help and the caller must resize or drop a leg.

        Told only ``INSUFFICIENT_DEPOSIT``, a caller cannot tell those apart,
        and the two call for opposite responses. Told them apart, it can
        either fund the leg or cancel its partner -- and *not* discover the
        segregation by holding a naked basket with no hedge behind it.

        Three things this deliberately does **not** do, all for the same
        reason -- the exchange has no notion of a "pair":

        * it does not transfer. ``auto_transfer`` is reported as ``False``
          because that is the market fact, and a session that quietly swept
          securities cash into the deposit would model a Vietnam that does
          not exist;
        * it does not cancel, amend or re-price the other leg. The session
          never learns that two orders were meant to be one trade;
        * it does not fire on an ``INDETERMINATE`` refusal. A stale-mark
          refusal has no shortfall to report -- ``binding_constraint`` is
          ``None`` there -- and naming an aggregate-funding verdict on a
          number nobody computed would dress a data gap as a funding fact.

        ``other_pool_available`` is the *net* figure in both directions,
        matching :meth:`transfer`'s own bounds: ``Cash.available`` on the
        securities side (money already committed to a resting buy cannot
        move) and ``MarginView.free_deposit`` on the deposit side (margin
        backing an open position cannot move). So a caller acting on
        ``funded_in_aggregate`` is reading the same number the transfer would
        be tested against, not a gross balance the transfer would then refuse.
        """
        if rejection.rule not in _SEGREGATED_FUNDING_RULES:
            return rejection
        required = rejection.detail.get('required')
        bound = rejection.binding_constraint
        if not isinstance(required, Decimal) or not isinstance(bound, Decimal):
            return rejection
        shortfall = required - bound
        if shortfall <= 0:
            return rejection

        short_pool = pool_for_venue(venue)
        other = (Pool.SECURITIES if short_pool is Pool.DERIVATIVES
                 else Pool.DERIVATIVES)
        elsewhere = (self._securities.cash().available
                     if other is Pool.SECURITIES
                     else self.margin().free_deposit)
        return replace(rejection, detail={
            **rejection.detail,
            'short_pool': short_pool,
            'shortfall': shortfall,
            'other_pool': other,
            'other_pool_available': elsewhere,
            'funded_in_aggregate': elsewhere >= shortfall,
            'auto_transfer': False,
            'cure': (f'transfer({other.value} -> {short_pool.value}, '
                     f'{shortfall}) and resubmit'
                     if elsewhere >= shortfall else
                     f'{other.value} holds {elsewhere}, which is short of the '
                     f'{shortfall} this leg needs; no transfer can fund it'),
            'segregation': (
                'Vietnamese securities cash and the derivatives deposit are '
                'segregated accounts with independent purchasing power and no '
                'auto-transfer (rulebook 6.3). A pair trade funded in '
                'aggregate can still fail on one leg, and this is that case '
                'reported rather than half-filled.'),
        })

    # -- the advance pipeline -------------------------------------------

    def _expire_boundaries(self, previous: datetime, ts: datetime) -> None:
        """Step 1: expire what each crossed phase boundary kills, per type.

        No boundary list is written here: :func:`orders.expires_at_boundary`
        owns the per-type rule, which is why **the noon break expires nothing**
        without this method having to know what a noon break is.

        Two things this method does add, both declared:

        * **A day that ended inside the advance is swept.** The session sees
          only the two endpoints of an advance, so a caller stepping from
          09:30 straight to the next day's 09:30 would cross a session end
          that an endpoint comparison cannot see -- both endpoints are
          ``CONTINUOUS``. Whenever the date changes, the previous day's close
          is swept explicitly. On a daily clock that is the only boundary
          there is.
        * **Every order type that cannot rest is swept at that close.** See
          :meth:`_sweep_non_resting`.
        """
        if ts <= previous:
            return
        crossed_a_day = ts.date() > previous.date()
        for venue in self._venues:
            if crossed_a_day:
                stamp = self._session_close(previous, venue) or previous
                self._book.expire_due(stamp, venue, SessionPhase.CONTINUOUS,
                                      SessionPhase.POST_CLOSE)
                self._sweep_non_resting(venue, stamp)
            if self._daily:
                continue
            ending = self._rulebook.at(previous).phase(venue)
            beginning = self._rulebook.at(ts).phase(venue)
            if ending is not beginning:
                self._book.expire_due(ts, venue, ending, beginning)

    def _session_close(self, ts: datetime,
                       venue: Venue) -> Optional[datetime]:
        """The venue's close on ``ts``'s day, or ``None`` if it had none.

        A day order that dies at the session end is stamped with the session
        end, not with the instant the session noticed. ``None`` on a
        non-trading day or outside the calendar's coverage -- the calendar
        refuses rather than returning a plausible 14:45 on a Sunday, and the
        caller falls back to the instant it has rather than inventing one.
        """
        try:
            return self._trading.session_end(ts, venue, self._rulebook.at(ts))
        except CalendarError:
            return None

    def _sweep_non_resting(self, venue: Venue, ts: datetime) -> None:
        """At the day's close, kill every order type that cannot rest.

        ``orders.expire_due`` will not do this, and correctly so.
        ``expires_at_boundary`` names a trigger for an auction-only order only
        when the phase it *leaves* is that auction, and gives the immediate
        families no boundary rule at all -- because the rulebook gives them
        none, their triggers being entry-time ones. Both refusals are right in
        that module: inventing a boundary rule there would hide a submit-path
        bug behind a plausible expiry.

        At the *session's* level the omission has to be closed, because none
        of these three types can outlive the session it was entered in under
        any reading of the rulebook, and one that does holds a live
        reservation for the rest of the run -- the leak section 12 invariant 4
        exists to catch. So each is expired here with its **own** terminal
        trigger, never a shared one:

        =====================  =====================================
        ATO / ATC              ``AUCTION_CROSS`` -- enterable only in
                               their own window, remainder
                               auto-cancelled at the cross
        MOK                    ``NOT_FILLABLE_IN_FULL``
        MAK                    ``IMMEDIATE_REMAINDER``
        =====================  =====================================

        This is the *backstop*, not the normal path. An intraday clock stepped
        through the cross has already killed the auction orders at the
        boundary, and an immediate order whose interval gave a definite answer
        was already decided by :meth:`_decide_immediates`. What reaches here is
        an order the clock jumped over or the data could not decide -- and
        being unable to decide whether an MOK filled is not a reason to let it
        hold margin overnight.
        """
        for record in self._book.live():
            if record.venue != venue:
                continue
            trigger = _CLOSE_TRIGGER_BY_TIF.get(record.time_in_force)
            if trigger is not None:
                self._book.expire(record.order_id, ts, trigger)

    def _evaluate_fills(self, ts: datetime) -> FrozenSet[OrderId]:
        """Steps 2-3: evaluate every live order and apply what filled.

        Orders are evaluated in the sequence the exchange received them, which
        is Vietnam's second priority level and the only one Tier 1 can honour
        -- there is no queue-position matching, by design.

        ``already_filled`` is aggregated **per instrument and per bar**, and
        both halves are needed for the same reason. Per instrument, so
        splitting one order into ten does not evade a participation cap; per
        bar, so *advancing the clock* does not either. The counter lives on
        the session (:attr:`_filled_in_bar`) rather than in this method, and
        resets when the bar does. It was a local, and while the cap was
        unreachable -- no volume, no cap, ``INDETERMINATE`` -- that cost
        nothing; once the corpus adapter served volume it meant N advances
        inside one day recomputed the cap from the full day's volume N times.

        Returns the ids the policy answered **definitely** for -- ``FILL`` or
        ``NO_FILL``. An order the data could not reach, or could not decide,
        is not in that set and must not then be decided by
        :meth:`_decide_immediates`: killing an MOK because its ticker had no
        bar would enforce a rule about our data coverage as if it were a
        market rule, and killing one on an ``INDETERMINATE`` would assert the
        very thing the policy just said it could not establish. Those orders
        are caught instead by :meth:`_sweep_non_resting` at the day's close,
        which bounds the leak without inventing the fact. **Both skips are
        counted** -- ``Blindness.NO_BAR`` and ``Blindness.UNROUTED`` -- because
        an order nobody could evaluate and an order nobody evaluated end in
        the identical expiry row, and until they were counted the second was
        invisible in every number this session publishes.

        **The venue object handed to the policy is dated too.** ``FillPolicy``
        is an extension point and the contract says a policy "may consult it
        and the venue spec", so passing ``EXCHANGE_BY_VENUE[venue]`` straight
        through would publish the import-time ``ExchangeSpec`` -- one flat
        0.1 tick per venue at every date -- as the fill seam's view of the
        rules, which is the same singleton ``submit()`` stopped judging on.
        It is :meth:`_venue_at`'s judge, resolved lazily by the router: the
        policy's price is the market's, not the order's, so the grid cannot be
        pre-resolved here the way admission's can.
        """
        if self._filled_bar != ts.date():
            # A new bar is new liquidity, and gets its own allowance. Cleared
            # rather than accumulated: a cap that never reset would be a
            # lifetime quota, which is restrictive past the point of honesty.
            self._filled_in_bar = {}
            self._filled_bar = ts.date()
        decided: Set[OrderId] = set()
        for record in self._book.live():
            ticker = record.order.ticker
            state = self._observe(ticker, ts)
            if state is None:
                self._blind(Blindness.NO_BAR)
                continue
            phase = self._phase(record.venue, observed=state.session)
            interval = self._interval_for(ticker, ts,
                                          replace(state, session=phase))
            try:
                instrument = self._router.instrument(ticker, ts)
            except UnresolvedRule:
                instrument = None
            try:
                judge = self._router.exchange(ticker, ts)
            except UnresolvedRule:
                # The ticker routes to no venue at THIS instant -- a dated
                # listing that has ended is the way that happens -- so there
                # is no rule set to evaluate it under. Falling back to
                # ``record.venue`` would judge it on the venue it was accepted
                # on while the router has just said it has none, which is the
                # frozen-venue assumption shape 1 forbids. Treated like an
                # unreachable bar above: undecided here, bounded at the close
                # by :meth:`_sweep_non_resting`.
                self._blind(Blindness.UNROUTED)
                continue
            already = self._filled_in_bar.get(ticker, 0)
            decision = self._policy.evaluate(
                record, interval, judge,
                already_filled=already,
                instrument=instrument)
            self._evaluations += 1
            self._exercise(Component.FILL_POLICY)

            if decision.outcome is FillOutcome.INDETERMINATE:
                self._indeterminate += 1
                for field_ in decision.missing:
                    self._by_field[field_] = self._by_field.get(field_, 0) + 1
                self._emit(Event.indeterminate(record, decision, ts,
                                               self._next_seq()))
                continue
            decided.add(record.order_id)
            if decision.outcome is FillOutcome.NO_FILL:
                continue
            self._audit_fill(decision, interval, already)
            self._apply_fill(record, decision, ts, instrument)
            self._filled_in_bar[ticker] = already + decision.quantity
        return frozenset(decided)

    def _audit_fill(self, decision: FillDecision, interval: MarketInterval,
                    already_filled: int) -> None:
        """Count what a **definite fill** rested on that the data did not have.

        The two classes the fidelity audit found, and neither of them was an
        ``INDETERMINATE``, so neither reached any published number:

        **A fill decided while a contract field was absent.** ``by_field``
        counts fields named on an ``INDETERMINATE`` -- a decision *not* taken.
        The opposite case is the dangerous one: a decision taken anyway, with
        the field missing. Every such field is counted under
        ``Blindness.DECIDED_WITHOUT``. This is deliberately a **superset**: a
        field absent from the interval that produced a fill is not proof the
        fill depended on it, and the bound is drawn wide because the direction
        of error matters -- a fill this simulator books that the real market
        would not have printed costs a user money in production.

        **A NO_FILL is not audited**, for the same reason. A refusal decided
        without OHLC is the restrictive direction: it costs an opportunity,
        never a position, and counting it would bury the fills under noise.

        **A cap the run did not apply.** A config may name a cap that the
        policy actually running does not carry: ``ExchangeSession.build``
        takes a constructed ``fill_policy`` that overrides the config, and an
        uncapped ``soft`` or any third-party policy has no
        ``max_participation`` at all. A run whose config names 10% and whose
        policy applies none produced *uncapped* fills, which is exactly the
        audit's finding, and it now says so. A config that names no cap and a
        policy that carries none agree, and there is nothing to report.

        **A cap the policy carries and did not honour.** Audited whatever the
        config says, and that is a repair: this whole block used to return
        early unless the *config* named a cap, so a constructed policy handed
        to ``build()`` under a config with no ``fill_policy`` cap was never
        checked against its own bound. Volume absent means the cap could not
        be computed and was not honoured; a quantity past ``cap x volume``
        means it was computed and exceeded.

        The exceeded branch is **arithmetically unreachable for the shipped
        policies**, and is meant to be: they size to
        ``floor(cap x volume) - already_filled``, so ``already + quantity``
        cannot pass ``cap x volume``. It exists for a policy this package did
        not write -- ``FillPolicy`` is an advertised extension point -- and
        until the fill counter was carried across advances it could not catch
        one of those either, because ``already_filled`` restarted at zero
        every advance. Now a policy that ignores ``already_filled`` is caught
        on its second advance into the same bar.

        Counting and not refusing, throughout. The session audits a component
        it does not own, which is the only place the check can live -- a
        policy that got its own cap wrong cannot be the witness to that fact
        -- but overruling a caller's policy would substitute one assumption
        for another, which this package does nowhere.
        """
        if not decision.filled:
            return
        for field_ in sorted(interval.missing, key=lambda f: f.value):
            self._blind(Blindness.DECIDED_WITHOUT, field_)

        cap = getattr(self._policy, 'max_participation', None)
        if cap is None:
            if self._config.fill_policy.max_participation is not None:
                self._blind(Blindness.CAP_NOT_APPLIED)
            return
        if interval.volume is None:
            self._blind(Blindness.CAP_UNCOMPUTABLE)
            return
        if already_filled + decision.quantity > cap * interval.volume:
            self._blind(Blindness.CAP_EXCEEDED)

    def _apply_fill(self, record: OrderRecord, decision: FillDecision,
                    ts: datetime,
                    instrument: Optional[InstrumentSpec]) -> None:
        """Move both ledgers and the state machine, account first -- **or
        neither**.

        Atomicity, and the mechanism chosen for it
        ------------------------------------------
        A fill touches five mutable things: the encumbrance ledger, the
        holdings ledger, the cash ledger, the contract ledger and the deposit
        balance -- and then the order book, which can *refuse*
        (``OrderBookOfRecord.apply_fill`` raises on a terminal order, on a
        partial fill of an MOK, and on a fill that would take filled past
        original). A refusal after the ledgers had moved was a reproduced
        defect: 98m dong spent, 1,000 shares credited, a 10-contract futures
        long opened, and the order still ``ACCEPTED`` with zero filled -- and
        it repeated on every subsequent ``advance_to``.

        The mechanism is **validate-then-commit**, not rollback, and the
        choice is forced rather than stylistic:

        * The ledgers are not journalled. ``DerivativesAccount._move`` appends
          an immutable ``DepositEntry`` to an audit trail, and the audit trail
          is the product -- a rollback would have to *un-write history*, which
          is a worse thing to own than a pre-check.
        * A rollback spanning ``deposit.py``'s contract ledger, its deposit
          balance and ``ledgers.py``'s three ledgers would need a
          transaction manager over two modules that share only an encumbrance
          ledger. Every one of those objects would have to grow a snapshot
          method that is right for every future field.
        * Nothing here needs to be *tried* to be known. Every refusal on the
          path is a pure function of state the session already holds, so the
          question can simply be asked first. :meth:`_fill_refusal` asks it.

        The two lower layers are held to the same rule from the inside:
        ``SecuritiesAccount.apply_fill`` validates the whole fill before
        moving any of its three ledgers, so the guard here is about the
        *book*, not about the account.

        A refusal raises rather than silently skipping the fill. An illegal
        decision is a bug in the fill policy -- ``FillPolicy`` is a structural
        protocol and a caller may ship their own -- not a market event, and
        the house idiom for "the path that should have made this unreachable
        did not" is a loud ``ValueError`` (compare ``CashLedger.debit``).
        Swallowing it would turn a broken policy into silently missing fills.

        Ordering, once the fill is known to be legal
        -------------------------------------------
        The account moves **first** and the book second, so that the
        reservation is still live when the ledger consumes it. The book's
        terminal hook releases the whole reservation, and a fill applied to
        the book first would leave ``EncumbranceLedger.consume`` nothing to
        find -- it returns ``None`` silently for an order holding none,
        because a rejected order never took one. The *balances* come out the
        same either way on a fill that completes an order; what does not is
        the encumbrance record, which would say "released in full" where the
        truth is "consumed at the fill price". That distinction is the audit
        trail invariant 4 is checked against, so it is not cosmetic.

        The record's ``encumbrances`` tuple is then re-read from the ledger,
        because a partial fill releases encumbrance **pro rata** and that
        arithmetic is the ledger's -- it needs the fill price and the charges
        actually levied, neither of which the state machine sees. A record
        still reporting its accept-time reservation would make section 12
        invariant 4 sum over a lie for the rest of the order's life.

        Raises:
            ValueError: if the book would refuse this fill. Raised **before**
                any ledger has moved, so the session is left exactly as it
                was and a caller that catches it holds consistent books.
        """
        walk = getattr(decision, 'walk', None)
        if walk is not None and len(walk.tranches) > 1:
            # A sweep that took several levels is several fills at several
            # prices, not one fill at the worst of them. Spend the tranches.
            self._apply_swept(record, decision, ts, instrument)
            return

        refusal = self._fill_refusal(record, decision, ts)
        if refusal is not None:
            raise ValueError(refusal)

        fill = Fill(
            fill_id=self._next_fill_id(), order_id=record.order_id,
            ticker=record.order.ticker, venue=record.venue,
            side=record.order.side, quantity=decision.quantity,
            price=decision.price, ts=ts,
            evidence=decision.evidence or FillEvidence.MODELLED,
            confidence=decision.confidence,
        )
        rules = self._rulebook.at(ts)
        profile = self._config.broker_profile
        kind = instrument.kind if instrument is not None else (
            InstrumentKind.FUTURE if record.venue is Venue.HNXDS
            else InstrumentKind.STOCK)

        if pool_for_venue(record.venue) is Pool.DERIVATIVES:
            charges = self._derivative_charges(fill, rules)
            fill = replace(fill, charges=charges)
            self._derivatives.apply_fill(
                fill, rules, ts, expiry=self._expiry_for(fill.ticker,
                                                         instrument))
            self._debit_charges(charges, ts, f'on {fill.fill_id}')
            self._deposit_charges.extend(charges)
        else:
            charges = assess_charges(rules, profile, fill,
                                     charge_class_for(kind))
            fill = replace(fill, charges=charges)
            self._securities.apply_fill(fill, self._settles_at(fill, kind),
                                        charges)

        after, _ = self._book.apply_fill(record.order_id, fill)
        if after.is_live:
            self._book.set_encumbrances(
                record.order_id,
                self._securities.encumbrances.of(record.order_id))

    def _apply_swept(self, record: OrderRecord, decision: FillDecision,
                     ts: datetime,
                     instrument: Optional[InstrumentSpec]) -> None:
        """Spend a multi-level sweep tranche by tranche, charged once.

        A sweep that walked three ask levels moved ``sum(price x quantity)``
        in cash, at three prices. :class:`SweptFillDecision` cannot carry that
        -- it holds one price and one quantity and projects the sweep onto its
        **worst** touched price for a caller that predates depth (see that
        class). Booking the ledger at that projection over-charges every
        tranche past the touch: 6,900 shares at 95.90 when 5,700 traded at
        95.40. The tranches on :attr:`SweptFillDecision.walk` are the real
        record, and this method books one :class:`Fill` per tranche at the
        tranche's own resting price (QD 352 Dieu 6.3, one match at the resting
        order's price) -- so the cash spent is the exact consideration and the
        holdings carry a per-lot cost basis.

        **The order's charges are assessed once, on the whole consideration.**
        ``minimum_per_order`` is a clamp on the *order* (``charges.py``), and a
        sweep is one order that happened to match at several prices; levying
        the minimum per tranche would charge a small-order floor three times.
        The assessment needs a notional equal to the consideration, which no
        single on-grid price expresses, so it runs against an aggregate priced
        at the walk's VWAP -- a charge basis only, never booked as a fill. The
        charges ride on the first tranche's fill; the rest carry none, because
        one order pays its charge once.

        **Atomicity is the single-fill path's, unchanged.** The only refusals
        ``OrderBookOfRecord.apply_fill`` can raise -- a terminal order, an MOK
        partial, a fill past original -- are a function of the *total*
        quantity, so the one aggregate :meth:`_fill_refusal` clears every
        tranche prefix. A swept MOK is a kill at ``BookWalkFillPolicy._decide``
        and never arrives here as a fill. Each tranche is affordable because
        the reservation was taken at the order's limit and every tranche price
        is at or through it, so the running consideration never exceeds what
        was reserved -- no tranche can fail funding after an earlier one moved.
        """
        walk = decision.walk
        refusal = self._fill_refusal(record, decision, ts)
        if refusal is not None:
            raise ValueError(refusal)

        rules = self._rulebook.at(ts)
        profile = self._config.broker_profile
        kind = instrument.kind if instrument is not None else (
            InstrumentKind.FUTURE if record.venue is Venue.HNXDS
            else InstrumentKind.STOCK)
        pool = pool_for_venue(record.venue)

        def _tranche_fill(quantity: int, price: Decimal,
                          charges: Tuple[Charge, ...]) -> Fill:
            return Fill(
                fill_id=self._next_fill_id(), order_id=record.order_id,
                ticker=record.order.ticker, venue=record.venue,
                side=record.order.side, quantity=quantity, price=price, ts=ts,
                evidence=decision.evidence or FillEvidence.MODELLED,
                confidence=decision.confidence, charges=charges)

        # The order's charges, assessed once. The aggregate is priced at the
        # VWAP so its notional is exactly the sweep's consideration; it is a
        # charge basis and is never booked.
        aggregate = Fill(
            fill_id=FillId('SWEEP'), order_id=record.order_id,
            ticker=record.order.ticker, venue=record.venue,
            side=record.order.side, quantity=walk.filled_quantity,
            price=walk.vwap, ts=ts,
            evidence=decision.evidence or FillEvidence.MODELLED,
            confidence=decision.confidence)
        if pool is Pool.DERIVATIVES:
            order_charges = self._derivative_charges(aggregate, rules)
        else:
            order_charges = assess_charges(rules, profile, aggregate,
                                           charge_class_for(kind))

        after = record
        for index, tranche in enumerate(walk.tranches):
            fill = _tranche_fill(tranche.quantity, tranche.price,
                                 order_charges if index == 0 else ())
            if pool is Pool.DERIVATIVES:
                self._derivatives.apply_fill(
                    fill, rules, ts,
                    expiry=self._expiry_for(fill.ticker, instrument))
                if fill.charges:
                    self._debit_charges(fill.charges, ts, f'on {fill.fill_id}')
                    self._deposit_charges.extend(fill.charges)
            else:
                self._securities.apply_fill(
                    fill, self._settles_at(fill, kind), fill.charges)
            after, _ = self._book.apply_fill(record.order_id, fill)

        if after.is_live:
            self._book.set_encumbrances(
                record.order_id,
                self._securities.encumbrances.of(record.order_id))

    def _fill_refusal(self, record: OrderRecord, decision: FillDecision,
                      ts: datetime) -> Optional[str]:
        """Would ``OrderBookOfRecord.apply_fill`` refuse this decision?

        The pre-check that makes :meth:`_apply_fill` atomic. It asks the same
        three questions the book asks, from the same record, before anything
        irreversible happens.

        The last question is asked by **running the book's own arithmetic**:
        ``OrderRecord.with_fill`` is pure -- it returns a copy and stores
        nothing -- so a dry run costs a tuple and cannot drift from the real
        one. Only the two guard clauses the book states separately are
        restated here, and they are restated rather than shared because
        ``orders.py`` exposes them as raises and not as predicates.

        **Orchestrator action:** ``OrderBookOfRecord`` should offer a
        ``would_refuse(order_id, fill)`` predicate, so that the state
        machine's refusal conditions live in exactly one place. Until it
        does, this duplication is deliberate and its cost is one test --
        ``test_a_fill_the_book_refuses_moves_no_ledger_at_all`` fails loudly
        if the two ever answer differently, because the guard's message and
        the book's must both match ``fill-or-kill``.

        Returns:
            The reason the fill is impossible, or ``None`` if it is legal.
            A reason is never a market outcome -- an MOK that cannot be
            filled in full is decided by ``fills.py`` returning ``NO_FILL``
            and killed by :meth:`_decide_immediates`, and never reaches here.
        """
        quantity = decision.quantity
        if record.is_terminal:
            return (f'order {record.order_id} is {record.state.value}: a '
                    f'terminal order state is never left, so it cannot take '
                    f'a fill')
        if (record.time_in_force is TimeInForce.FILL_OR_KILL
                and quantity != record.remaining_quantity):
            return (f'order {record.order_id} is fill-or-kill (MOK): it '
                    f'fills in full at entry or is cancelled entirely, so a '
                    f'fill of {quantity} against '
                    f'{record.remaining_quantity} remaining is not a state '
                    f'this order can occupy. The fill policy proposed it; '
                    f'no ledger has moved')
        probe = Fill(
            fill_id=FillId('PROBE'), order_id=record.order_id,
            ticker=record.order.ticker, venue=record.venue,
            side=record.order.side, quantity=quantity, price=decision.price,
            ts=ts, evidence=decision.evidence or FillEvidence.MODELLED,
        )
        try:
            after = record.with_fill(probe, ts)
        except ValueError as exc:
            return str(exc)
        if not is_legal_transition(record.state, after.state):
            return (f'illegal transition {record.state.value} -> '
                    f'{after.state.value} for order {record.order_id}: '
                    f'LEGAL_TRANSITIONS does not carry that edge')
        return None

    def _expiry_for(self, ticker: str,
                    instrument: Optional[InstrumentSpec]) -> Optional[date]:
        """The contract's last trading day, resolved at the fill.

        Two sources, and the order matters. The **instrument spec** wins: it
        is what the ticker master says, and a listed contract's last trading
        day is a published fact, not a computation. Where the spec carries
        none -- ``SymbolRouter`` passes the adapter's ``expiry`` straight
        through, and it is ``None`` for every source that does not populate it
        -- :func:`plutus.market.expiry.expiry_date` computes the third
        Thursday of the contract month, which that module records as verified
        24/24 in-window. Design section 10 lists ``expiry.py`` among the
        primitives this build reuses; recomputing the rule here instead would
        be a second copy of it.

        **A position with no expiry never expires**, so ``None`` is not a
        neutral answer: the contract is margined for the rest of the run,
        ``ExpirySettled`` can never fire for it, and the position survives its
        own last trading day. It is still the honest answer for the families
        ``expiry_date`` does not parse -- it matches ``VN30F`` only, so the
        government-bond and VN100F codes fall through here and need an
        explicit ``expiries`` map on the account. That gap is stated rather
        than papered over with a guessed third Thursday for a contract whose
        calendar has never been read.

        Resolved per fill and not once at build time. A build-time table would
        have to be filled in before the session knows which contracts it will
        trade, and a ticker-keyed table of instrument facts is locked shape 1's
        forbidden build.
        """
        if instrument is not None and instrument.expiry is not None:
            return instrument.expiry
        return expiry_date(ticker)

    def _debit_charges(self, charges: Sequence[Charge], ts: datetime,
                       occasion: str) -> Decimal:
        """Debit the deposit **once per charge**, naming the charge each time.

        One aggregate debit was cheaper and it cost the derivatives pool its
        itemisation. ``DepositEntry`` is the only cash journal either pool has
        on the session side -- ``CashLedger`` keeps none, by design -- so a
        single ``charges on FILL-000031`` row for -66,610 is the whole record
        of what was actually four separate levies by four separate parties:
        the state's transfer tax, HNX's trading service price, VSDC's clearing
        fee and the broker's commission. The securities pool already itemises
        (``CashLedger.levy`` takes one ``Charge``), so the two halves of the
        same simulator disagreed about whether a fee statement is auditable,
        and a caller reconciling a derivatives statement against
        ``session.charges()`` had one number to reconcile four rows against.

        The reason string keeps its ``charges <occasion>`` opening and appends
        ``: <kind>``, so every caller that classified the old string on its
        prefix still classifies these, and the levy is now identifiable
        without joining anything. Zero-amount charges are still skipped: a
        levy of nothing moved no cash and ``DepositEntry`` records movements.

        Returns:
            The total debited, which the expiry event reports.
        """
        total = Decimal('0')
        for charge in charges:
            if charge.total:
                self._derivatives.debit(
                    charge.total, ts,
                    reason=f'charges {occasion}: {charge.kind}')
                total += charge.total
        return total

    def _derivative_charges(self, fill: Fill,
                            rules: RuleSet) -> Tuple[Charge, ...]:
        """The charges on one futures fill. **Not** ``ledgers.assess_charges``.

        ``assess_charges`` prices a ``TRADE_VALUE`` row through
        ``ledgers.trade_value``, which **raises on HNXDS by design**: a
        Vietnamese cash venue quotes thousands of dong, an index future quotes
        points against a 100,000d multiplier, and government-bond futures
        quote dong on a 100,000d face, so one conversion cannot serve both and
        ``CURRENCY_UNIT['HNXDS'] == 1`` is not a multiplier. The rulebook's
        derivatives schedule nonetheless contains a ``TRADE_VALUE`` row -- the
        0.0085% personal income tax on a derivatives transfer -- so calling
        ``assess_charges`` on a futures fill raises rather than returning.

        The notional is therefore computed here, where the contract's
        multiplier is known: ``quantity x multiplier x price``. Everything
        else -- which rows apply, the min/max clamp, the whole-dong rounding
        as a declared modelling choice, the per-row VAT flag -- follows
        ``ledgers.py``'s own arithmetic exactly.

        The multiplier is resolved **at the fill instant**, per contract, not
        taken from an account-wide default. This is the second site the default
        leaked into: the derivatives PIT base is ``settlement price x
        multiplier x contracts x IM ratio / 2`` (rulebook 12.3), so it is
        linear in the multiplier and a government-bond fill was taxed on ten
        times its notional. It cannot raise in practice -- an order reaches a
        fill only through ``_reserve``, which resolves the same multiplier at
        submission and refuses as ``INDETERMINATE`` when it cannot -- and if it
        ever does, raising here is right: a fill priced on a guessed unit is
        worse than no fill.

        **Orchestrator action:** either ``assess_charges`` should take the
        notional (or a multiplier) rather than deriving it, or ``ChargeRule``
        should carry a derivatives-notional base. Until then this is the only
        place a futures charge can be priced, and the duplication is
        deliberate rather than accidental.
        """
        multiplier = self._derivatives.multiplier_for(fill.ticker, fill.ts)
        notional = Decimal(fill.quantity) * multiplier * fill.price
        rows: Tuple[ChargeRule, ...] = (
            tuple(rules.charges(fill.venue, ChargeClass.FUTURE))
            + tuple(self._config.broker_profile.commission))
        levied: List[Charge] = []
        for rule in rows:
            if rule.debited_at is not DebitedAt.FILL:
                continue
            if not rule.applies(fill.venue, ChargeClass.FUTURE, fill.side):
                continue
            if rule.base is ChargeBase.TRADE_VALUE:
                base_value = notional
            elif rule.base is ChargeBase.PER_CONTRACT:
                base_value = Decimal(fill.quantity)
            elif rule.base is ChargeBase.PER_TRADE:
                base_value = Decimal('1')
            else:
                # PER_OPEN_CONTRACT_PER_DAY and MONTHLY_PER_SECURITY are
                # skipped rather than approximated: they accrue on a position,
                # not on a trade, and the daily/monthly pass is Tier 2.
                continue
            if rule.rate is not None:
                raw = rule.rate * base_value
            elif rule.amount is not None:
                raw = rule.amount * (base_value
                                     if rule.base is ChargeBase.PER_CONTRACT
                                     else Decimal('1'))
            else:
                raise ValueError(
                    f'charge rule {rule.charge_id!r} sets neither rate nor '
                    f'amount')
            if rule.minimum is not None:
                raw = max(raw, rule.minimum)
            if rule.maximum is not None:
                raw = min(raw, rule.maximum)
            amount = raw.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            vat = (amount * rule.vat_rate).quantize(
                Decimal('1'), rounding=ROUND_HALF_UP
            ) if rule.vat_applies else Decimal('0')
            levied.append(Charge(
                kind=rule.charge_id, venue=fill.venue, base=rule.base,
                base_value=base_value, amount=amount,
                levied_by=rule.levied_by, pool=rule.pool, ts=fill.ts,
                ticker=fill.ticker, order_id=fill.order_id,
                fill_id=fill.fill_id, vat=vat))
        return tuple(levied)

    def _settles_at(self, fill: Fill, kind: InstrumentKind) -> datetime:
        """When this fill's two legs become usable.

        **T+2 counting VSDC settlement business days, which diverge from
        trading days around Tet**, with a 13:00 delivery cut from 2022-08-29
        and delivery at the next session's open before that. Neither is
        computed here: the rulebook gives the dated ``SettlementRule`` and the
        settlement calendar counts the days.
        """
        rule = self._rulebook.at(fill.ts).settlement_rule(kind)
        if rule is None:
            return fill.ts
        return self._settlement.settles_at(fill.ts, rule, trading=self._trading)

    def _decide_immediates(self, ts: datetime,
                           decided: FrozenSet[OrderId]) -> None:
        """Step 4: decide the order families that never rest.

        Locked shape 4 in its most literal form -- the order type **is** the
        time-in-force, and each of these has its own terminal edge:

        * **MOK** fills in full at entry or is cancelled entirely, so an
          evaluated MOK still live could not be filled in full:
          ``NOT_FILLABLE_IN_FULL``.
        * **MAK** keeps whatever filled and kills the rest:
          ``IMMEDIATE_REMAINDER``.
        * **MTL** walks the book and its residue *converts to a resting limit
          order*, which is why its time-in-force is ``IMMEDIATE_THEN_DAY`` and
          neither ``DAY`` nor ``IMMEDIATE_OR_CANCEL`` would do. A residue that
          cannot be priced is left live rather than converted at a guess: it
          is a day order by time-in-force and dies at the session end anyway.

        Only orders the policy answered **definitely** for are decided here.
        One whose ticker had no data, or whose interval was ``INDETERMINATE``,
        is left alone: killing it would assert the very thing the policy just
        said it could not establish. :meth:`_sweep_non_resting` catches those
        at the day's close, so the leak is bounded without the fact being
        invented.

        **This is one interval later than a real exchange decides them**, and
        Tier 1 declares it: ``submit()`` is synchronous with no matching
        engine behind it, so an MOK is decided at the first interval that
        evaluates it rather than at entry.
        """
        for record in self._book.live():
            if record.order_id not in decided:
                continue
            tif = record.time_in_force
            if tif is TimeInForce.FILL_OR_KILL:
                self._book.expire(record.order_id, ts,
                                  ExpiryTrigger.NOT_FILLABLE_IN_FULL)
            elif tif is TimeInForce.IMMEDIATE_OR_CANCEL:
                self._book.expire(record.order_id, ts,
                                  ExpiryTrigger.IMMEDIATE_REMAINDER)
            elif (tif is TimeInForce.IMMEDIATE_THEN_DAY
                    and record.order.order_type
                    is OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT
                    and record.state in (OrderState.ACCEPTED,
                                         OrderState.PARTIALLY_FILLED)):
                price = self._residual_price(record, ts)
                if price is not None:
                    self._book.convert_residue(record.order_id, ts, price)

    def _residual_price(self, record: OrderRecord,
                        ts: datetime) -> Optional[Decimal]:
        """One tick beyond the last matched price, capped at the band.

        The rule is gazetted -- VNX QD 22/2025 Dieu 17.2(b): buy +1 tick, sell
        -1 tick, capped at the ceiling or floor when the last match was
        already there. Two earlier extractions read "+/-1 tick" and "at the
        ceiling/floor" as rival rules; the sentence contains both clauses, and
        a third reading, "exactly the last matched price", the rulebook
        rejects.

        **Unresolved for derivatives, and deliberately not resolved here.** On
        HNXDS the residual price is a recorded CONFLICT: the equity rule and
        MBS give last matched +/-1 tick, Vietcap's handbook gives best bid +1
        / best ask -1, and the two differ whenever the book is not tight. The
        equity rule is applied to both venues and the conflict is declared
        rather than silently picked.
        """
        last = record.fills[-1].price if record.fills else None
        state = self._last_state.get(record.order.ticker)
        if last is None and state is not None:
            last = state.last
        if last is None:
            return None
        try:
            instrument = self._router.instrument(record.order.ticker, ts)
            tick = self._rulebook.at(ts).tick_size(
                record.venue, instrument.kind, last,
                ticker=record.order.ticker)
        except UnresolvedRule:
            return None
        if tick is None:
            return None
        if record.order.side is Side.BUY:
            price = last + tick
            ceiling = state.ceiling if state is not None else None
            return min(price, ceiling) if ceiling is not None else price
        price = last - tick
        floor = state.floor if state is not None else None
        return max(price, floor) if floor is not None else price

    def _settle(self, ts: datetime) -> None:
        """Step 5: settle both DVP legs at one instant.

        Cash and securities settle by delivery-versus-payment at the
        depository and are allocated to the client in a single action, so both
        legs are driven from one call and reported as one event family. There
        is no version of this where the shares land and the money does not.
        """
        moved, proceeds = self._securities.settle_due(ts)
        for ticker, tranche in moved:
            self._emit(Event.settlement_credited(
                ts, self._next_seq(), ticker=ticker,
                quantity=tranche.quantity,
                source_order_id=tranche.source_order_id))
        for tranche in proceeds:
            self._emit(Event.settlement_credited(
                ts, self._next_seq(), amount=tranche.amount,
                source_order_id=tranche.source_order_id))

    def _mark_derivatives(self, ts: datetime) -> None:
        """Steps 6-7: mark the deposit, run the ladder, settle expiries.

        The mark touches **only** the deposit. Securities cash is not an asset
        of the utilisation test and cannot answer a call: Vietnamese
        derivatives margin sits in a segregated deposit account with its own
        purchasing power and no auto-transfer exists, so a caller who lets the
        deposit run short while holding securities cash gets a call. That is
        the real behaviour, not a modelling artefact.

        A ``FORCED`` status **reports** rather than liquidates. The margin-call
        state machine as a built loop is Tier 2 (interface contract section
        13); what Tier 1 owes is an event that states its selection rule, the
        contracts it would close and the price basis -- which is why
        ``liquidation_sequence`` is called and its answer carried in
        ``detail`` even though nothing is closed. ``detail['executed']`` is
        ``False`` so no reader can mistake the report for the act. The rule
        stated is :meth:`_liquidation_rule`, the one this session is actually
        running, and it decides the shape of the answer: ``LARGEST_LOSS_FIRST``
        is an *ordering* and reports a ``sequence``; ``PRO_RATA`` is a
        proportional reduction across every leg and is not an ordering at all,
        so it reports ``sequence=None`` and names the ``legs`` instead.
        ``liquidation_sequence`` refuses ``PRO_RATA`` by design and is not
        asked for one.

        **A stale mark is counted, not smoothed over.** A held contract with no
        price this session makes the view ``INDETERMINATE``; the monitor does
        not advance on one, and each such contract is counted under
        :attr:`DataField.SETTLEMENT_PRICE` so
        :meth:`indeterminate_report` publishes the blind sessions rather than
        letting them read as quiet ones.

        **The rulebook is now ASKED which margin mechanism the date is
        under.** ``RuleSet.margin_model`` had no caller anywhere in ``src/``
        and raises from the KRX cutover, where the post-trade COMS calculation
        is unsourced -- so a 2026 position was margined ``IM + VM`` on the
        pre-KRX shape, the run completed, and the ignorance meter read zero.
        The mark still runs, because refusing to margin an open position is
        not a safer answer than margining it on last year's mechanism, but the
        run now records ``Blindness.MARGIN_MODEL_UNSOURCED`` once per mark it
        took without a sourced mechanism, and ``Component.MARGIN_MODEL``
        appears in ``exercised`` when the rulebook could answer. That converts
        a rule with no caller into a rule with a counted one. *What this does
        not do* is compute the KRX model: no source states it, and the layer
        that would -- ``scenario_margin`` -- is refused at build rather than
        silently substituted (see :meth:`_check_margin_model`).
        """
        positions = self._derivatives.positions()
        resting = self._live_derivative_orders()
        if not positions and not resting:
            return
        # Declared before the work, not after it: a run holding an open
        # contract requires this layer whether or not the layer then
        # completes, and a requirement recorded only on success could never
        # report the failure it exists to report.
        self._needs(Component.DERIVATIVES_MARK)
        self._needs(Component.DERIVATIVES_LADDER)
        marks = self._marks()
        if marks:
            self._derivatives.observe_marks(marks, ts)

        rules = self._rulebook.at(ts)
        try:
            rules.margin_model()
        except UnresolvedRule:
            self._blind(Blindness.MARGIN_MODEL_UNSOURCED)
        else:
            self._exercise(Component.MARGIN_MODEL)
        terms = self._config.broker_profile.terms
        view = self._derivatives.margin(marks, rules, terms, ts,
                                        resting=resting)
        self._evaluations += 1
        self._exercise(Component.DERIVATIVES_MARK)
        if view.stale_marks:
            self._indeterminate += 1
            for _ in view.stale_marks:
                self._by_field[DataField.SETTLEMENT_PRICE] = (
                    self._by_field.get(DataField.SETTLEMENT_PRICE, 0) + 1)

        # Read the call state BEFORE the mark. ``on_mark`` clears ``_cure_by``
        # in place when the account comes back, so afterwards there is no way
        # to tell a clearance from an ordinary quiet mark.
        call_before = self._monitor.outstanding_call
        # A forced close is not immediate: QD 26 Dieu 13.3 gives a cure window
        # before positions are shut, so the *first* mark that reports FORCED
        # only reports -- the account is given the session to cure. Execution
        # happens once the breach has persisted past that first mark, which is
        # what ``in_forced_breach`` being latched BEFORE this mark tells us.
        forced_before = self._monitor.in_forced_breach
        self._exercise(Component.DERIVATIVES_LADDER)
        for news in self._monitor.on_mark(self._derivatives, view, rules, ts):
            # A call that was outstanding and is now answered gets its own
            # row, whether the account came back to WARNING or all the way to
            # OK. Escalation also drops ``_cure_by``, so the FORCED status is
            # excluded here -- that is the call being enforced, not cured.
            if (call_before is not None
                    and self._monitor.outstanding_call is None
                    and news.status in (MarginStatus.OK,
                                        MarginStatus.WARNING)):
                self._emit(Event.margin(
                    EventKind.MARGIN_CALL_CLEARED, news, self._next_seq(),
                    cure_by=call_before,
                    cured_at=ts,
                    reason='utilisation returned below the call level before '
                           'the cure deadline; the outstanding call is '
                           'discharged'))
            kind = _EVENT_FOR_MARGIN_STATUS.get(news.status)
            if kind is None:
                continue
            detail: Dict[str, Any] = {}
            if kind is EventKind.FORCED_LIQUIDATION:
                rule = self._liquidation_rule()
                pro_rata = rule is LiquidationRule.PRO_RATA
                # Snapshot the report from the positions as they stand NOW,
                # because executing the close empties the very positions the
                # sequence and legs describe.
                sequence = (None if pro_rata else
                            liquidation_sequence(self._derivatives, marks, rule))
                legs = tuple(sorted(self._derivatives.positions()))
                deposit_before = self._derivatives.deposit_balance
                # Execute the close: submit real offsetting orders through the
                # order path, in the selection rule's order. They face the same
                # band, tick, lot and fill policy as any order -- so a locked
                # book refuses them (BAND_LOCK) and the position rides, which is
                # the measured 17.6% permissive cost the report alone hid.
                # PRO_RATA is an allocation, not an ordering; its per-leg
                # quantity is not yet computed, so it is still report-only.
                closed = (() if pro_rata or not forced_before
                          else self._execute_forced_close(marks, rule, ts))
                detail = {
                    'selection_rule': rule,
                    'sequence': sequence,
                    'legs': legs,
                    'price_basis': 'the contract mark at this instant',
                    'deposit_balance': deposit_before,
                    'executed': bool(closed),
                    'closed': closed,
                    'reason': ('offsetting close orders submitted through the '
                               'order path; a locked book refuses them and the '
                               'position rides' if closed else
                               'nothing to close, or a close is already live '
                               'for every leg, or PRO_RATA (report-only)'),
                }
                if pro_rata:
                    detail['allocation'] = (
                        'pro rata across every leg. Tier 1 names the legs and '
                        'does not compute the per-leg quantity: that is an '
                        'allocation, not an ordering, and there is no '
                        'sequence to report')
            self._emit(Event.margin(kind, news, self._next_seq(), **detail))

        for code, position in list(positions.items()):
            expiry = position.expiry
            if expiry is None or not self._expiry_reached(expiry, rules, ts):
                continue
            struck = self._expiry_instant(expiry, ts)
            settlement, source, basis = self._final_settlement(code, struck)
            if settlement is None:
                self._evaluations += 1
                self._indeterminate += 1
                self._by_field[DataField.SETTLEMENT_PRICE] = (
                    self._by_field.get(DataField.SETTLEMENT_PRICE, 0) + 1)
                continue
            quantity = position.net_quantity
            # ``struck``, not ``ts``: the settlement happened when the
            # contract expired, not when this caller noticed. See
            # ``_expiry_instant``.
            cash_flow = self._derivatives.settle_expiry(code, settlement,
                                                        struck)
            charges = self._maturity_charges(code, quantity, settlement,
                                             rules, struck)
            total = self._debit_charges(
                charges, struck, f'on the final settlement of {code}')
            self._deposit_charges.extend(charges)
            self._emit(Event.expiry_settled(
                code, struck, self._next_seq(), settlement=settlement,
                cash_flow=cash_flow, quantity=quantity,
                settlement_source=source.value,
                substituted=source is SettlementSource.CLOSE_PROXY,
                price_basis=basis,
                charges=tuple(c.kind for c in charges),
                charges_total=total))

    # -- the overnight layer --------------------------------------------

    def _derivatives_venues(self) -> Tuple[Venue, ...]:
        """The configured venues whose orders draw on the deposit."""
        return tuple(v for v in self._venues
                     if pool_for_venue(v) is Pool.DERIVATIVES)

    def _overnight_model(self, ts: datetime) -> str:
        """Which model computes the requirement carried past *this* close.

        Two questions in order, and they are different questions.

        **The regime, from the dated rulebook.** ``RuleName.MARGIN_MODEL``
        records ``'pre_margin'`` to 2025-05-04 at HIGH confidence: margin
        lodged with VSDC before an order could be placed and recomputed
        against live prices in-session. That regime has **no separate
        end-of-day model**, so the overnight requirement in it is the
        continuous one on the positions still held at the close. Running QD
        26's 21-scenario grid on a 2022 account would report a number under a
        regulation that did not exist, which is precisely the date-blindness
        the rulebook exists to prevent -- so the regime is asked first and it
        can veto the profile.

        **The firm, from the broker profile**, once the rulebook has stopped
        answering. ``margin_model_overnight`` is the firm's own statement
        about the CCP layer, and it is a different field from
        ``margin_model_intraday`` because the evidence is different: all ten
        firms that state a client-ladder formula state ``IM + VM + DM``, and
        the four that publish scenario-grid material label it as the
        end-of-day submission (survey finding F-1).

        A session with no margin profile has no firm to ask, so past the
        cutover it gets ``UNSTATED`` -- which is INDETERMINATE, not
        ``IM + VM`` by default.
        """
        rules = self._rulebook.at(ts)
        try:
            rules.margin_model()
        except UnresolvedRule:
            pass
        else:
            return PRE_KRX_CONTINUOUS
        margin_profile = getattr(self._config.broker_profile,
                                 'margin_profile', None)
        if margin_profile is None:
            return UNSTATED_MODEL
        return margin_profile.margin_model_overnight.name

    def _overnight_margin(self, ts: datetime) -> None:
        """Step 7c: the requirement the account carries past the close.

        **This is the layer the fidelity audit found missing.**
        ``scenario_margin.py`` -- 1,069 executable lines implementing QD 26
        Phu luc 2, unit-tested and checked against TCBS's own published
        worked example -- had **zero call sites** anywhere in ``src/`` or
        ``validation/``, and every derivatives run nevertheless reported a
        complete margin history and ``indeterminate=0``. A margin layer that
        is never invoked returns nothing, and nothing is indistinguishable
        from a correct zero in every number this package used to publish.
        :attr:`Component.OVERNIGHT_MARGIN` is what makes the two different.

        **Once per session, after the close.** QD 26 Dieu 5.5 computes ``MR``
        *"sau khi ket thuc phien giao dich"* for the position portfolio on
        each investor account, so this runs on the first advance at or after
        the derivatives venue's own session end and not again that day. A
        day with no session -- the calendar refusing, a holiday -- gets no
        requirement and is **not** counted as ignorance: there was no close
        to carry a position past.

        **The intraday number is never substituted.** Where the overnight
        layer cannot be computed the answer is ``amount is None``, one
        ``indeterminate`` against one ``evaluations``, and a
        ``margin.overnight.uncomputed.<gap>`` key naming the missing input.
        Substituting ``IM + VM`` would be wrong in the direction that costs a
        user money: the grid stresses a book at the initial-margin move in
        both directions and adds a basis charge on a calendar spread, so on
        the books it is strictest about it is the larger number, and a
        backtest quietly given the smaller one holds positions the real
        account would have been called on.

        **This reports; it does not grade.** ``user_facing_model`` names which
        layer the client's ladder is tested against and all twelve shipped
        profiles say ``INTRADAY``, so the ladder stays exactly where it was
        and the accounting half of the simulator is untouched by this method.
        An ``OVERNIGHT``-facing profile is refused at build rather than
        graded on the wrong layer -- see :meth:`_check_margin_model` for the
        ``MarginView`` shape that stops it.
        """
        venues = self._derivatives_venues()
        if not venues:
            return
        if ts.date() in self._overnight_dates:
            return
        closes = [self._session_close(ts, v) for v in venues]
        ends = [c for c in closes if c is not None]
        if not ends or ts < min(ends):
            return
        self._overnight_dates.add(ts.date())

        positions = self._derivatives.positions()
        # A run that never opened a derivatives position does not need this
        # layer, and declaring it needed anyway would put a line in
        # ``unexercised`` on every equity run -- the standing complaint that
        # trains a reader to ignore the field.
        if not positions and not self._overnight:
            return
        self._needs(Component.OVERNIGHT_MARGIN)

        model = self._overnight_model(ts)
        margin_profile = getattr(self._config.broker_profile,
                                 'margin_profile', None)
        parameters = getattr(margin_profile, 'vsdc_parameters', None)
        factor = getattr(margin_profile, 'minimum_margin_factor', None)

        # The continuous engine's view of the same instant. Computed on every
        # path, not only the one that returns it -- the grid needs the view's
        # ``VM`` to know whether it is excluding a loss that this run never
        # settled in cash. See
        # ``OvernightAssumption.VARIATION_MARGIN_UNSETTLED``.
        #
        # ``resting_order_margin`` is then **subtracted** rather than asked
        # for by passing ``resting=()``: ``account_margin_requirement`` tests
        # ``if resting:``, so an empty sequence means "ask the account", not
        # "there are none", and a caller who reads the default as the latter
        # gets the account's own figure back. Subtracting from the returned
        # view says what is meant and leaves that function untouched.
        view = self._derivatives.margin(
            self._marks(), self._rulebook.at(ts),
            self._config.broker_profile.terms, ts,
            resting=self._live_derivative_orders())
        held_only = view.required - view.resting_order_margin
        continuous = is_continuous_model(model)

        result = overnight_requirement(
            as_of=ts.date(),
            account_id=self._derivatives.ref.account_no,
            positions=positions,
            model=model,
            parameters=parameters,
            underlying_closes=self._underlying_closes(positions, ts),
            minimum_margin_factor=factor,
            intraday_amount=held_only if continuous else None,
            intraday_is_determinate=not view.stale_marks,
            unsettled_variation_margin=view.variation_margin)

        self._overnight.append(result)
        self._exercise(Component.OVERNIGHT_MARGIN)
        self._evaluations += 1
        if not result.is_determinate:
            self._indeterminate += 1
            for gap in result.gaps:
                self._blind(Blindness.OVERNIGHT_UNCOMPUTED,
                            gap.split(':', 1)[0])
            # The underlying's close is a field of the data contract that no
            # other counter names, so it goes to ``by_field``.
            # ``INTRADAY_INDETERMINATE`` deliberately does **not**: the
            # missing settlement price behind it has already been counted by
            # the mark in this same advance, and one absent price counted
            # twice under one field key turns a population into a magnitude.
            # The overnight layer's own share of it is the
            # ``margin.overnight.uncomputed.intraday.indeterminate`` key.
            if OvernightGap.UNDERLYING_CLOSE.value in result.subjects:
                self._by_field[DataField.CLOSE] = (
                    self._by_field.get(DataField.CLOSE, 0) + 1)
        for assumed in result.assumptions:
            self._blind(Blindness.OVERNIGHT_ASSUMED, assumed)

    def _underlying_closes(self, positions: Mapping[str, ContractPosition],
                           ts: datetime) -> Dict[str, Decimal]:
        """The **underlying asset's** close per held contract, from the source.

        Read from the same ``MarketDataSource`` the marks are read from, at
        the same instant, by the underlying's own ticker -- ``'VN30'`` for
        VN30F, which the wired Parquet corpus carries with 2,725 daily rows.
        A source that does not carry the index simply has no entry here and
        the layer answers INDETERMINATE naming
        :attr:`OvernightGap.UNDERLYING_CLOSE`.

        **The futures price is not substituted for it**, and the temptation
        is real because it is right there in ``_marks()``. Phu luc 2 section
        1.1's ``S`` is the underlying's close and section 1.2's ``S0`` is the
        same quantity; the futures price differs from it by the basis, which
        is what a calendar spread is *made of* and what section 3's ``Sm``
        charges for. Folding the basis into ``S`` would put it into all 21
        scenarios and then charge for it again.
        """
        wanted: Dict[str, Decimal] = {}
        for code in positions:
            name = underlying_of(code)
            if name is None or name in wanted:
                continue
            state = self._observe(name, ts)
            if state is not None and state.last is not None:
                wanted[name] = state.last
        return wanted

    def overnight_margin(self) -> Optional[OvernightRequirement]:
        """The most recent end-of-day requirement, or ``None`` if never run.

        ``None`` is a real answer and it is the one the audit was looking
        for: this session has not computed an overnight requirement at all,
        either because it holds no derivatives or because the run never
        reached a close.
        """
        return self._overnight[-1] if self._overnight else None

    def overnight_margins(self) -> Tuple[OvernightRequirement, ...]:
        """Every end-of-day requirement this run computed, in order."""
        return tuple(self._overnight)

    def _expiry_reached(self, expiry: date, rules: RuleSet,
                        ts: datetime) -> bool:
        """Has the contract stopped trading by ``ts``?

        **The last trading day is a trading day.** A VN30F contract trades
        through its whole expiry session -- on 2022-10-20 VN30F2210 printed a
        close and the front-month roll into VN30F2211 is a large part of that
        day's volume -- and VSDC's final settlement is struck from the
        underlying's closing period, after the market shuts. Settling at the
        first advance that lands on the expiry *date* therefore extinguished
        the position at 09:30 and made the session unreachable: a roll
        submitted that morning found nothing to close, and the offsetting
        order opened a brand-new naked position in a contract that had
        already cash-settled. So the test is the venue's own close, resolved
        for this instant, and not the date alone.

        Falls back to the date test when the schedule cannot be resolved --
        that is the behaviour this replaces, and refusing to settle at all on
        an unresolved clock would strand the position forever.
        """
        if ts.date() > expiry:
            return True
        if ts.date() < expiry:
            return False
        try:
            close = rules.session_close(Venue.HNXDS)
        except UnresolvedRule:
            return True
        return close is None or ts.time() >= close

    def _expiry_instant(self, expiry: date, ts: datetime) -> datetime:
        """The instant the final settlement is struck -- price **and** cash.

        Always on the expiry date, whatever instant the caller noticed the
        expiry at. :meth:`_final_settlement` already says that a close carried
        over from another session is not a worse settlement price but a
        different contract-day's price; that only holds if the read is pinned
        to the expiry date, and it was not -- an advance that first crossed
        the expiry on a *later* date read that later date's row and found
        nothing, silently turning a settlement into an INDETERMINATE.

        **The money is now pinned here too.** It was not: the price read used
        this method and the cash movement, the maturity tax and the
        ``EXPIRY_SETTLED`` event all used ``ts``, the observing advance. So
        one contract, one code and one settlement price produced two
        different settlement *dates* depending only on when the caller
        happened to poll -- ``2022-11-17T14:45`` for a run that stepped to
        14:50 on the expiry day, ``2022-11-18T09:20`` for the same position
        in a run whose next step was the following morning. A settlement log
        dated by observation cannot answer "was this settled on time".

        The same-date branch now returns the venue **close** rather than
        ``ts`` for the same reason: VSDC strikes the final settlement from the
        underlying's closing period, so 14:50 and 15:30 on the expiry day are
        both the close's settlement. :meth:`_expiry_reached` already
        guarantees ``ts`` is at or after that close, so this never dates a
        settlement in the future -- and the ``_time.max`` fallback, reachable
        only when the schedule will not resolve, is clamped to ``ts`` so an
        unresolved clock cannot either.
        """
        if ts.date() == expiry:
            try:
                close = self._rulebook.at(ts).session_close(Venue.HNXDS)
            except (UnresolvedRule, CalendarError):
                close = None
            if close is None:
                return ts
            return min(datetime.combine(expiry, close), ts)
        try:
            close = self._rulebook.at(
                datetime.combine(expiry, _time.min)).session_close(
                    Venue.HNXDS)
        except (UnresolvedRule, CalendarError):
            close = None
        return datetime.combine(expiry, close or _time.max)

    def _maturity_charges(self, code: str, quantity: int,
                          settlement: Decimal, rules: RuleSet,
                          ts: datetime) -> Tuple[Charge, ...]:
        """The derivatives transfer tax on a contract carried into settlement.

        Rulebook 8.1 and 12.3: taxable income on a futures contract is
        determined when the order is matched **or at contract maturity**. A
        position carried to expiry is never matched out, so a fill-only model
        under-charges every held-to-expiry contract by exactly one leg -- the
        leg the trader who closed the day before pays. ``assess_at_maturity``
        was implemented, sourced and tested with no call site (FEATURES.md
        s16.3 #16); this is the call site.

        **Only the tax.** ``assess_at_maturity`` refuses to levy the exchange
        trading fee and the VSDC clearing fee, because neither is sourced as
        charged on a final cash settlement, and inventing them here would be
        worse than omitting them. The side is whichever direction closes the
        position, and the row is two-sided, so a short pays it too.
        """
        if quantity == 0:
            return ()
        try:
            multiplier = self._derivatives.multiplier_for(code, ts)
        except UnknownContractMultiplier:
            return ()
        ctx = ChargeContext(
            venue=Venue.HNXDS, charge_class=ChargeClass.FUTURE,
            side=Side.SELL if quantity > 0 else Side.BUY,
            quantity=abs(quantity), price=settlement, ts=ts, ticker=code,
            multiplier=multiplier)
        return tuple(levied.charge for levied in assess_at_maturity(rules, ctx))

    def _final_settlement(self, code: str, ts: datetime
                          ) -> Tuple[Optional[Decimal],
                                     Optional[SettlementSource], str]:
        """The price an expiring contract settles at, and which tier gave it.

        The data source's own ``MarketInterval.settlement_price`` first: it is
        a field of the design section 9 contract and a source that fills it is
        answering the question that was asked. Only when it is absent does the
        close stand in, and then the **substitution is recorded on the event**
        rather than absorbed.

        Recording it is not ceremony. Measured across all 46 post-cutover
        expiries the close-proxy error against the published settlement is
        +0.024% mean signed, 0.042% mean absolute and 0.333% at worst: small,
        one-sided and systematic, which is precisely the profile that
        disappears into an aggregate unless every substituted row can be
        excluded. ``expiry.py`` names the same three tiers
        (:class:`~plutus.market.verdicts.SettlementSource`) and this reuses
        them so one vocabulary covers the batch path and the session.

        ``PUBLISHED`` here means *the source published one*. This module
        cannot tell a ``quote_settlementprice`` row from a 14:15-14:45 TWAP
        the adapter computed; an adapter doing the second should say so on the
        interval it serves, and ``expiry.SettlementResolver`` is the component
        that distinguishes them.

        **The expiry day is read, and only the expiry day.** Unlike a mark,
        which may honestly stand at the last price seen, a final settlement is
        a price *on a named date* -- it is what the contract is extinguished
        at. So there is no ``_last_state`` fall-back here: a close carried
        over from an earlier session is not a worse settlement price, it is a
        different contract-day's price, and paying it into the deposit would
        be a fabricated cash flow rather than an approximate one.

        Returns:
            ``(price, tier, price_basis)``, with ``price`` ``None`` when the
            source has neither a settlement price nor a close on the expiry
            day -- in which case nothing is settled, the position stays on the
            ledger and the caller counts the gap.
        """
        state = self._observe(code, ts)
        interval = (self._interval_for(code, ts, state)
                    if state is not None else None)
        if interval is not None and interval.settlement_price is not None:
            return (interval.settlement_price, SettlementSource.PUBLISHED,
                    'the final settlement price the data source published for '
                    'the expiry day')
        close = None
        if interval is not None:
            close = interval.close
        if close is None and state is not None:
            close = state.last
        if close is None:
            return None, None, ''
        return (close, SettlementSource.CLOSE_PROXY,
                'the data source close on the expiry day, standing in for a '
                'final settlement price the source did not supply. Across the '
                '46 post-cutover expiries the close proxy runs +0.024% mean '
                'signed and 0.042% mean absolute against the published '
                'settlement, 0.333% at worst; the exchange publishes a '
                'trimmed 14:15-14:45 average and the settlement basis itself '
                'changed on 2022-08-17')

    def _marks(self) -> Dict[str, Decimal]:
        """Current price per held or ordered contract, re-read at :meth:`now`.

        The source is re-read rather than the cache trusted, because an open
        futures position must be marked whether or not the account still has a
        live order on it -- and :meth:`_evaluate_fills` reads the source only
        for tickers that *have* one. Trusting the cache would margin a quiet
        account against the price it opened at for the rest of the run: the
        requirement would never move, no call would ever fire, and the one
        thing a segregated deposit exists to demonstrate would be silently
        unreachable.

        **Only prices observed at this instant.** Where the source has nothing,
        the contract is simply absent from the result and
        ``DerivativesAccount.mark_for`` falls back to its own cache -- which
        holds the same price, and, unlike ``_last_state``, holds it with the
        instant it was observed at. That is the whole difference: passing the
        stale price back in as this session's mark makes
        ``observe_marks`` re-stamp it current, and an account can then be
        margined against its entry price for the rest of a run with the view
        reporting a definite ``OK``. Dropping it here is what lets
        ``MarginView.stale_marks`` be true.
        """
        codes = set(self._derivatives.positions())
        codes.update(r.order.ticker for r in self._live_derivative_orders())
        marks: Dict[str, Decimal] = {}
        for code in codes:
            state = self._observe(code, self._now)
            if state is not None and state.last is not None:
                marks[code] = state.last
        return marks

    def _live_derivative_orders(self) -> Tuple[OrderRecord, ...]:
        """The live orders whose margin sits in the segregated deposit."""
        return tuple(r for r in self._book.live()
                     if pool_for_venue(r.venue) is Pool.DERIVATIVES)

    # -- rejection bookkeeping ------------------------------------------

    def _reject(self, order: Order, venue: Venue, order_id: OrderId,
                rejection: Rejected) -> Rejected:
        """Write the refusal to the book of record and the cursor.

        A rejected order still gets an id, so the rejection log joins to the
        submission -- and the id is the session's, adopted rather than a
        second one minted, because two ids for one submission is a log that
        cannot be joined at all. ``REJECTED`` is terminal, so the shared
        release hook fires here too: nothing to release when ``admits()``
        refused before anything was reserved, something to release when a
        later check refused after an earlier one reserved. Firing
        unconditionally is what makes "every terminal edge" true without the
        book knowing which step refused.
        """
        if rejection.order_id is None:
            rejection = replace(rejection, order_id=order_id)
        self._count_rejection(rejection)
        record = self._book.reject(order, venue, rejection)
        return record.rejection if record.rejection is not None else rejection

    def _reject_unrouted(self, order: Order,
                         rejection: Rejected) -> Rejected:
        """A refusal for a ticker that has no venue, kept off the book.

        ``OrderRecord`` requires a venue and this order has none, so writing a
        row would mean inventing one -- and a fabricated venue on a rejection
        row is worse than an absent row, because everything downstream that
        groups the log by venue would silently believe it. The rejection still
        reaches the cursor, so no refusal is invisible.
        """
        self._count_rejection(rejection)
        self._emit(Event.rejected(rejection, self._next_seq(),
                                  ticker=order.ticker))
        return rejection

    def _count_rejection(self, rejection: Rejected) -> Rejected:
        """Count an ``INDETERMINATE`` refusal by rule, for section 9.2.

        Only ``INDETERMINATE`` is counted. A rule saying no is a *result*, not
        ignorance, and mixing the two would inflate the one number this
        session publishes as a bound on what the data could not decide.
        """
        if rejection.verdict is Verdict.INDETERMINATE:
            key = (rejection.rule.value if rejection.rule is not None
                   else 'unknown')
            self._by_rule[key] = self._by_rule.get(key, 0) + 1
        return rejection

    def _refuse_amend(self, order_id: OrderId, ts: datetime,
                      reason: str) -> Rejected:
        """An amendment Tier 1 declines, marked as a tier boundary.

        ``detail['adopted']`` is True because no Vietnamese document refuses
        these amendments -- Tier 1 does, and the log must say which.
        """
        return Rejected(
            rule=AdmissionRule.SESSION_SEMANTICS, binding_constraint=None,
            ts=ts, order_id=order_id,
            detail={'reason': reason, 'adopted': True, 'tier': 2})


#: Section 5 writes ``Session.from_config``. The module is ``exchange.py``, so
#: the class is ``ExchangeSession`` and this alias keeps the spec's example
#: valid without a second implementation.
Session = ExchangeSession
