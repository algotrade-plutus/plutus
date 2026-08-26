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
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
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
from plutus.market.session.fills import FillPolicy, build_fill_policy
from plutus.market.session.ledgers import (
    CashLedger, EncumbranceLedger, HoldingsLedger, SecuritiesAccount,
    assess_charges,
)
from plutus.market.session.orders import (
    OrderBookOfRecord, OrderIdFactory, is_legal_transition,
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
    'CHARGE_CLASS_BY_KIND', 'EXCHANGE_BY_VENUE', 'ExchangeSession',
    'IntervalSource', 'Session', 'charge_class_for', 'load_data_source',
    'parse_config',
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
#: ``OK`` has no member: an ``OK`` view can only reach the session as the
#: *clearance* of an outstanding call, and ``EventKind`` carries no clearance
#: member (see ``deposit.MarginMonitor.on_mark``). A clearance is therefore
#: visible only through ``session.margin()``, which is declared.
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
    """

    def interval(self, ticker: str, start: datetime, end: datetime, *,
                 resolution: Resolution) -> Optional[MarketInterval]:
        """The interval over ``[start, end)``, or ``None`` if absent."""
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

    Raises:
        KeyError: on a missing ``period`` or ``exchange_rules.venues``, rather
            than defaulting. A session that silently ran on an invented period
            or venue list would produce a result nobody can reproduce.
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
    fill_policy = FillPolicyConfig(
        kind=str(fill_payload.get('kind', 'soft')),
        max_participation=Decimal(
            str(fill_payload.get('max_participation', '0.10'))),
        seed=fill_payload.get('seed'),
    )
    data = DataConfig(
        adapter=str(data_payload.get('adapter', '')),
        root=str(data_payload.get('root', '')),
        settlement_calendar=data_payload.get('settlement_calendar'),
    )
    return SessionConfig(
        period_start=_as_date(period['start']),
        period_end=_as_date(period['end']),
        resolution=Resolution(payload.get('resolution', Resolution.DAILY.value)),
        exchange_rules=exchange_rules,
        broker_profile=BrokerProfile.from_config(
            payload.get('broker_profile') or {}),
        accounts=accounts,
        fill_policy=fill_policy,
        data=data,
    )


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
        """
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

        self._evaluations = 0
        self._indeterminate = 0
        self._by_field: Dict[DataField, int] = {}
        self._by_rule: Dict[str, int] = {}

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
        """
        profile = config.broker_profile
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
        policy = fill_policy or build_fill_policy(config.fill_policy)

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
                      policy, securities, deposit, book, monitor)
        cell['session'] = session
        return session

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
        8. drain the cursor and return

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
        return self.poll()

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
        if adm.verdict is not Verdict.ADMITTED:
            return self._reject(order, venue, order_id,
                                Rejected.from_admissibility(adm, order_id))

        reservation = self._reserve(order, order_id, venue, state, rules, ts,
                                    instrument)
        if isinstance(reservation, Rejected):
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
        """**Tier 2.** Tier 1 implements only a priority-preserving decrease.

        The shape is fixed here so it is not retrofitted later, and the dated
        rule is consulted rather than assumed: from 2025-05-05 one amendment
        may change price **or** quantity, never both (VNX QD 22/2025 Dieu
        21.3), so ``rulebook.edition_at(ts)`` decides and not a constant.

        What Tier 1 will not do is change the funding requirement. Design
        section 5 requires that "amending must re-run the encumbrance so an
        amend-up cannot escape funding", and the encumbrance ledger refuses a
        second reservation on the same key by design -- re-taking would
        double-count against ``available``. The alternative,
        release-and-retake, can fail *after* the release and leave a live
        order unfunded, so an amendment that could raise the requirement is
        refused outright and the refusal says it is a tier boundary.

        A pure quantity **decrease** is allowed and leaves the original
        reservation in place. It over-reserves, which is the conservative
        direction, and the whole reservation is released at the terminal edge
        either way.
        """
        record = self._require(order_id)
        ts = self._now
        if limit_price is not None:
            return self._refuse_amend(
                order_id, ts,
                'Tier 1 does not amend a price: the reservation was taken at '
                'the old price, and re-running it needs a release-and-retake '
                'that can fail after the release and leave a live order '
                'unfunded')
        if quantity is None or quantity >= record.original_quantity:
            return self._refuse_amend(
                order_id, ts,
                'Tier 1 amends only downward: an amend-up must re-run the '
                'encumbrance so it cannot escape funding, which is Tier 2')

        phase = self._phase(record.venue,
                            observed=self._observed_phase(record.order.ticker))
        outcome = self._book.amend(
            order_id, ts, quantity=quantity, phase=phase,
            allow_price_and_quantity=self._may_amend_price_and_quantity(ts))
        if isinstance(outcome, Rejected):
            self._count_rejection(outcome)
        return outcome

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
        """
        return SessionProvenance(
            rulebook_id=self._config.exchange_rules.rulebook,
            resolution=self._config.resolution,
            period_start=self._config.period_start,
            period_end=self._config.period_end,
            venues=self._venues,
            fill_policy_kind=getattr(self._policy, 'signature',
                                     self._policy.kind),
            broker_profile_name=self._config.broker_profile.name,
            pins=self._rulebook.pins,
            settlement_calendar_id=getattr(self._settlement, 'calendar_id',
                                           None),
            liquidation_rule=self._liquidation_rule(),
        )

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

    def indeterminate_report(self) -> IndeterminateReport:
        """How much of the run the data could not decide.

        Design section 9.2 requires the session to report this rate, and
        section 8 makes it the honest headline: **a bound on ignorance, not a
        fill rate.**

        ``by_field`` counts fill evaluations the policy could not decide,
        named by the field that was missing. ``by_rule`` counts submissions
        the rulebook or the exchange could not judge, named by the rule. They
        are different populations over different denominators and are
        deliberately not summed -- ``evaluations`` counts only the first.
        """
        return IndeterminateReport(
            evaluations=self._evaluations,
            indeterminate=self._indeterminate,
            by_field=dict(self._by_field),
            by_rule=dict(self._by_rule),
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

        Odd lots do not reach this rule: their 99-unit cap is the odd-lot
        definition itself, and ``admits()``'s ``ROUND_LOT`` rule refuses a
        non-multiple of the trading unit before any of it applies.
        """
        resolution = rules.resolve(RuleName.MAX_ORDER_SIZE, venue)
        if not resolution.is_known:
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
        return MarketInterval(
            ticker=ticker, start=ts, end=ts + span,
            resolution=self._config.resolution, state=state,
            close=close, missing=frozenset(missing))

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
            return self._securities.reserve_for_buy(
                order_id, order, venue, state, rules, ts, cls_=cls_)
        if order.side is Side.SELL:
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
        ``already_filled`` is aggregated **per instrument**, so splitting one
        order into ten does not evade a participation cap.

        Returns the ids the policy answered **definitely** for -- ``FILL`` or
        ``NO_FILL``. An order the data could not reach, or could not decide,
        is not in that set and must not then be decided by
        :meth:`_decide_immediates`: killing an MOK because its ticker had no
        bar would enforce a rule about our data coverage as if it were a
        market rule, and killing one on an ``INDETERMINATE`` would assert the
        very thing the policy just said it could not establish. Those orders
        are caught instead by :meth:`_sweep_non_resting` at the day's close,
        which bounds the leak without inventing the fact.

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
        filled_by_ticker: Dict[str, int] = {}
        decided: Set[OrderId] = set()
        for record in self._book.live():
            ticker = record.order.ticker
            state = self._observe(ticker, ts)
            if state is None:
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
                continue
            decision = self._policy.evaluate(
                record, interval, judge,
                already_filled=filled_by_ticker.get(ticker, 0),
                instrument=instrument)
            self._evaluations += 1

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
            self._apply_fill(record, decision, ts, instrument)
            filled_by_ticker[ticker] = (filled_by_ticker.get(ticker, 0)
                                        + decision.quantity)
        return frozenset(decided)

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
            total = sum((c.total for c in charges), Decimal('0'))
            if total:
                self._derivatives.debit(
                    total, ts, reason=f'charges on {fill.fill_id}')
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
        """
        positions = self._derivatives.positions()
        resting = self._live_derivative_orders()
        if not positions and not resting:
            return
        marks = self._marks()
        if marks:
            self._derivatives.observe_marks(marks, ts)

        rules = self._rulebook.at(ts)
        terms = self._config.broker_profile.terms
        view = self._derivatives.margin(marks, rules, terms, ts,
                                        resting=resting)
        self._evaluations += 1
        if view.stale_marks:
            self._indeterminate += 1
            for _ in view.stale_marks:
                self._by_field[DataField.SETTLEMENT_PRICE] = (
                    self._by_field.get(DataField.SETTLEMENT_PRICE, 0) + 1)

        for news in self._monitor.on_mark(self._derivatives, view, rules, ts):
            kind = _EVENT_FOR_MARGIN_STATUS.get(news.status)
            if kind is None:
                continue
            detail: Dict[str, Any] = {}
            if kind is EventKind.FORCED_LIQUIDATION:
                rule = self._liquidation_rule()
                pro_rata = rule is LiquidationRule.PRO_RATA
                detail = {
                    'selection_rule': rule,
                    'sequence': (None if pro_rata else
                                 liquidation_sequence(self._derivatives,
                                                      marks, rule)),
                    'legs': tuple(sorted(self._derivatives.positions())),
                    'price_basis': 'the contract mark at this instant',
                    'deposit_balance': self._derivatives.deposit_balance,
                    'executed': False,
                    'reason': 'Tier 1 reports a forced close and does not '
                              'execute one; the loop is Tier 2',
                }
                if pro_rata:
                    detail['allocation'] = (
                        'pro rata across every leg. Tier 1 names the legs and '
                        'does not compute the per-leg quantity: that is an '
                        'allocation, not an ordering, and there is no '
                        'sequence to report')
            self._emit(Event.margin(kind, news, self._next_seq(), **detail))

        for code, position in list(positions.items()):
            if position.expiry is None or ts.date() < position.expiry:
                continue
            settlement, source, basis = self._final_settlement(code, ts)
            if settlement is None:
                self._evaluations += 1
                self._indeterminate += 1
                self._by_field[DataField.SETTLEMENT_PRICE] = (
                    self._by_field.get(DataField.SETTLEMENT_PRICE, 0) + 1)
                continue
            quantity = position.net_quantity
            cash_flow = self._derivatives.settle_expiry(code, settlement, ts)
            self._emit(Event.expiry_settled(
                code, ts, self._next_seq(), settlement=settlement,
                cash_flow=cash_flow, quantity=quantity,
                settlement_source=source.value,
                substituted=source is SettlementSource.CLOSE_PROXY,
                price_basis=basis))

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
