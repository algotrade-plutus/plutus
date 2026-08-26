"""The scenario runner: a window, a source, a broker profile, a strategy.

One call runs a scenario and emits the three logs plus the identity results as
structured data. Nothing here decides anything about the market; it drives the
session's clock in the shape ``advance_to`` documents and gets out of the way.

The loop, and why it is two steps per session::

    for day in window.sessions:
        events = session.advance_to(day @ open_time)      # OPEN step
        strategy.on_events(ctx, events)
        strategy.on_session(ctx)                          # orders for `day`
        events = session.advance_to(day @ close_time)     # CLOSE step
        strategy.on_events(ctx, events)

``ExchangeSession.advance_to`` says outright that a loop advancing only to
midnight submits orders that expire without having been offered a single bar:
the bar is evaluated by the advance that lands inside its day, and the next
advance crosses the date and sweeps the close first. Two advances per session
is the documented shape, not a stylistic choice.

**Trading days come from the data, not from a calendar.** No settlement or
trading-calendar data ships with the repo (FEATURES.md A64/A65), so a runner
that generated weekdays would trade on Tet. :func:`sessions_from_source` reads
the dates the corpus actually carries for a reference ticker; a scenario may
also pass ``sessions=`` explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import (Any, Dict, List, Mapping, Optional, Sequence, Tuple)

from plutus.market.protocol import Resolution
from plutus.market.session.exchange import ExchangeSession, parse_config
from plutus.market.session.types import (
    Event, EventKind, IndeterminateReport, SessionProvenance,
)

from validation.identities import IdentityResult, check_identities
from validation.journal import LedgerJournal
from validation.logs import (
    CashLog, RunLogs, SettlementAction, SettlementLog, SettlementLogEntry,
    TradeAction, TradeLog, TradeLogEntry, json_safe,
)
from validation.strategy import Annotation, StepPhase, StrategyContext

__all__ = ['Window', 'Scenario', 'ScenarioResult', 'Snapshot', 'run_scenario',
           'build_session', 'sessions_from_source', 'DEFAULT_OPEN',
           'DEFAULT_CLOSE']

_ZERO = Decimal('0')

#: The two instants each session is driven to. 09:30 sits inside HOSE's
#: continuous session at every date in the coverage window; 14:45 sits after
#: the closing auction, so the day's non-resting orders are swept.
DEFAULT_OPEN = time(9, 30)
DEFAULT_CLOSE = time(14, 45)


# --------------------------------------------------------------------------
# Window
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Window:
    """A stress window: what it is called, when it runs, and over what.

    ``sessions`` is the list of trading days to step through. When empty the
    runner derives it from the data source using ``reference_ticker``, which
    is the honest default -- the corpus knows which days traded and the repo
    ships no calendar.
    """

    name: str
    start: date
    end: date
    tickers: Tuple[str, ...] = ()
    sessions: Tuple[date, ...] = ()
    reference_ticker: Optional[str] = None
    note: Optional[str] = None

    def with_sessions(self, sessions: Sequence[date]) -> 'Window':
        return replace(self, sessions=tuple(sessions))

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'start': self.start.isoformat(),
                'end': self.end.isoformat(), 'tickers': list(self.tickers),
                'sessions': [d.isoformat() for d in self.sessions],
                'note': self.note}


def sessions_from_source(source: Any, ticker: str, start: date,
                         end: date) -> Tuple[date, ...]:
    """The dates the corpus carries a row for ``ticker``, ``end`` **inclusive**.

    A trading calendar derived from the data rather than asserted. It inherits
    the corpus's own defects: a suspended ticker loses days that the market
    traded, so pick a liquid reference name. It is still better than a weekday
    generator, which trades through Tet.

    ``MarketDataSource.states`` is half-open and, in ``DataHubSource``, keyed
    on the **date** -- it does ``str(end)[:10]``, so a time component is
    dropped and ``end`` itself is excluded. That is easy to miss and silently
    loses the last session of a window, so this helper adds the day and
    filters, rather than making every scenario remember.
    """
    if source is None:
        raise ValueError(
            'sessions_from_source needs a data source; pass Window.sessions '
            'explicitly for a source-less run')
    states = source.states(ticker, datetime.combine(start, time.min),
                           datetime.combine(end + timedelta(days=1), time.min))
    seen: List[date] = []
    for state in states:
        day = state.ts.date()
        if start <= day <= end and day not in seen:
            seen.append(day)
    return tuple(sorted(seen))


# --------------------------------------------------------------------------
# Session construction
# --------------------------------------------------------------------------

def build_session(*, start: date, end: date, venues: Sequence[str],
                  source: Any = None,
                  initial_cash: Any = 0, initial_deposit: Any = 0,
                  fill_policy: str = 'hard',
                  max_participation: Any = '0.10',
                  seed: Optional[int] = None,
                  broker_profile: Optional[Mapping[str, Any]] = None,
                  rulebook: str = 'vn-2020-2026',
                  pins: Sequence[Mapping[str, Any]] = (),
                  resolution: Resolution = Resolution.DAILY,
                  settlement: Any = None, trading: Any = None,
                  listings: Sequence[Any] = (),
                  initial_holdings: Optional[Mapping[str, int]] = None,
                  monitor: Any = None,
                  fill_policy_object: Any = None) -> ExchangeSession:
    """Build a session on the supported path: ``build(parse_config(payload))``.

    A convenience, not a second construction route -- everything goes through
    ``parse_config`` and ``ExchangeSession.build`` so a scenario cannot end up
    on a path the session's own tests do not cover.

    ``data`` is deliberately left empty in the payload and the source is
    injected: ``load_data_source`` cannot construct either shipped adapter
    from a config (FEATURES.md §16.3 #3), and the ``DataHubSource`` case fails
    *silently*. Naming an adapter in the config would therefore give a session
    with no data and no error.

    Both calendars default to the unsourced weekday-only ones. That is wrong
    around every Tet in the period, and ``provenance().settlement_calendar_id``
    says ``UNSOURCED`` when it happens, so a scenario that cares must pass a
    real one.
    """
    payload: Dict[str, Any] = {
        'period': {'start': start.isoformat(), 'end': end.isoformat()},
        'resolution': resolution.value,
        'exchange_rules': {'venues': list(venues), 'rulebook': rulebook,
                           'pins': list(pins)},
        'accounts': {'securities': {'initial_cash': str(initial_cash)},
                     'derivatives': {'initial_deposit': str(initial_deposit)}},
        'fill_policy': {'kind': fill_policy,
                        'max_participation': str(max_participation)},
        'data': {},
    }
    if seed is not None:
        payload['fill_policy']['seed'] = seed
    if broker_profile is not None:
        payload['broker_profile'] = dict(broker_profile)
    return ExchangeSession.build(
        parse_config(payload), source=source, listings=tuple(listings),
        settlement=settlement, trading=trading,
        initial_holdings=dict(initial_holdings) if initial_holdings else None,
        fill_policy=fill_policy_object, monitor=monitor)


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Snapshot:
    """Every balance the run reports, at one step.

    Sampled at both steps of every session, so a transient breach -- a
    negative settled quantity that squares up by the close, a utilisation
    spike that is cured next morning -- is visible instead of averaged away.
    """

    ts: datetime
    phase: str
    settled_cash: Decimal
    committed_cash: Decimal
    available_cash: Decimal
    advanced: Decimal
    pending_total: Decimal
    interest_accrued: Decimal
    deposit_balance: Decimal
    margin_required: Decimal
    initial_margin: Decimal
    variation_margin: Decimal
    posted_margin: Decimal
    resting_order_margin: Decimal
    free_deposit: Decimal
    utilisation: Optional[Decimal]
    margin_status: str
    stale_marks: Tuple[str, ...]
    holdings: Dict[str, Dict[str, int]]
    positions: Dict[str, int]
    live_orders: int

    def to_row(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return json_safe(asdict(self))


def _snapshot(session: Any, phase: StepPhase,
              tickers: Sequence[str]) -> Snapshot:
    cash = session.cash()
    view = session.margin()
    holdings = {}
    for ticker in tickers:
        holding = session.holdings(ticker)
        holdings[ticker] = {'settled': holding.settled,
                            'committed': holding.committed,
                            'unsettled': holding.unsettled_quantity,
                            'total': holding.total}
    return Snapshot(
        ts=session.now(), phase=phase.value,
        settled_cash=cash.settled_balance, committed_cash=cash.committed,
        available_cash=cash.available, advanced=cash.advanced,
        pending_total=cash.pending_total,
        interest_accrued=cash.interest_accrued,
        deposit_balance=view.deposit_balance, margin_required=view.required,
        initial_margin=view.initial_margin,
        variation_margin=view.variation_margin,
        posted_margin=view.posted_margin,
        resting_order_margin=view.resting_order_margin,
        free_deposit=view.free_deposit,
        utilisation=view.utilisation, margin_status=view.status.value,
        stale_marks=tuple(view.stale_marks),
        holdings=holdings,
        positions={code: p.net_quantity
                   for code, p in session.positions().items()},
        live_orders=len([r for r in session.orders() if not r.is_terminal]),
    )


# --------------------------------------------------------------------------
# Scenario and result
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Scenario:
    """One run: a window, a built session, a data source and a strategy.

    The session is built by the scenario author (usually with
    :func:`build_session`) rather than by the runner, because the interesting
    scenarios differ precisely in how the session is configured -- the broker
    profile, the fill policy, the calendar, the opening balances.
    """

    name: str
    window: Window
    session: ExchangeSession
    strategy: Any
    source: Any = None
    opening_holdings: Mapping[str, int] = field(default_factory=dict)
    open_time: time = DEFAULT_OPEN
    close_time: time = DEFAULT_CLOSE
    note: Optional[str] = None


@dataclass(frozen=True)
class ScenarioResult:
    """Everything one run produced, as structured data.

    ``failed_identities`` is the first thing to read. ``logs`` is the second.
    ``error`` is set when the strategy or the session raised: the run stops,
    the logs up to that instant are kept, and the exception is reported rather
    than swallowed -- a scenario that dies half-way is a finding.
    """

    name: str
    window: Window
    provenance: SessionProvenance
    logs: RunLogs
    identities: Tuple[IdentityResult, ...]
    snapshots: Tuple[Snapshot, ...]
    annotations: Tuple[Annotation, ...]
    indeterminate: IndeterminateReport
    sessions_run: int
    error: Optional[BaseException] = None
    note: Optional[str] = None

    @property
    def failed_identities(self) -> Tuple[IdentityResult, ...]:
        return tuple(r for r in self.identities if not r.passed)

    @property
    def skipped_identities(self) -> Tuple[IdentityResult, ...]:
        """Checks that did not run. Counted apart from the ones that held.

        A skip reported as a pass is how a run printed ``9/9 held`` over
        47,233,456d of live encumbrance. ``ok`` still ignores skips -- a run
        with a live order at the end is not thereby broken -- but the headline
        no longer claims the check was made.
        """
        return tuple(r for r in self.identities if r.skipped)

    @property
    def ok(self) -> bool:
        """No identity broken and no exception. Says nothing about profit."""
        return not self.failed_identities and self.error is None

    def summary(self) -> str:
        """A few lines a scenario can print. Never a substitute for the logs.

        Deliberately states the two things a green run can hide: how much of
        it the data could not decide, and whether the settlement calendar was
        the unsourced default.
        """
        failed = self.failed_identities
        skipped = self.skipped_identities
        rate = self.indeterminate.rate
        lines = [
            f'{self.name}: {self.sessions_run} session(s) over '
            f'{self.window.start} .. {self.window.end}',
            f'  logs        {self.logs.counts()}',
            f'  identities  {len(self.identities) - len(failed) - len(skipped)}'
            f'/{len(self.identities)} held'
            + ('' if not skipped
               else f', {len(skipped)} SKIPPED: '
                    + ', '.join(r.name for r in skipped))
            + ('' if not failed
               else ' -- FAILED: ' + ', '.join(r.name for r in failed)),
            f'  undecided   {self.indeterminate.indeterminate}/'
            f'{self.indeterminate.evaluations} evaluations'
            + ('' if rate is None else f' (rate {rate:.4f})'),
            f'  calendar    {self.provenance.settlement_calendar_id}',
            f'  fill policy {self.provenance.fill_policy_kind}',
        ]
        if self.error is not None:
            lines.append(f'  ERROR       {self.error!r}')
        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'window': self.window.to_dict(),
            'note': self.note,
            'sessions_run': self.sessions_run,
            'provenance': {
                'rulebook_id': self.provenance.rulebook_id,
                'resolution': self.provenance.resolution.value,
                'venues': [v.value for v in self.provenance.venues],
                'fill_policy': self.provenance.fill_policy_kind,
                'broker_profile': self.provenance.broker_profile_name,
                'settlement_calendar_id':
                    self.provenance.settlement_calendar_id,
                'liquidation_rule': self.provenance.liquidation_rule.value,
                'pins': [{'path': p.path, 'value': json_safe(p.value),
                          'reason': p.reason} for p in self.provenance.pins],
                'is_counterfactual': self.provenance.is_counterfactual,
            },
            'indeterminate': {
                'evaluations': self.indeterminate.evaluations,
                'indeterminate': self.indeterminate.indeterminate,
                'rate': json_safe(self.indeterminate.rate),
                'by_field': {k.value: v
                             for k, v in self.indeterminate.by_field.items()},
                'by_rule': dict(self.indeterminate.by_rule),
            },
            'identities': [r.to_row() for r in self.identities],
            'snapshots': [s.to_row() for s in self.snapshots],
            'annotations': [{'ts': a.ts.isoformat(), 'text': a.text,
                             'detail': json_safe(a.detail)}
                            for a in self.annotations],
            'error': None if self.error is None else repr(self.error),
            **self.logs.to_dict(),
        }


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------

#: Order-lifecycle events the context has already written from the *return
#: value* of ``submit()``, with more detail than the event carries. Translating
#: them again would double every accepted order in the trade log.
_ALREADY_LOGGED = frozenset({EventKind.ACCEPTED, EventKind.REJECTED})

#: The trade-log actions ``_ALREADY_LOGGED`` maps onto, so the translator can
#: ask whether *this* order already has one rather than assuming every order
#: does. A broker-placed order never passes through ``StrategyContext``.
_ALREADY_LOGGED_ACTIONS = frozenset({TradeAction.ACCEPTED,
                                     TradeAction.REJECTED})

_ACTION_FOR_EVENT: Mapping[EventKind, TradeAction] = {
    EventKind.ACCEPTED: TradeAction.ACCEPTED,
    EventKind.REJECTED: TradeAction.REJECTED,
    EventKind.FILLED: TradeAction.FILLED,
    EventKind.PARTIALLY_FILLED: TradeAction.PARTIALLY_FILLED,
    EventKind.CANCELLED: TradeAction.CANCELLED,
    EventKind.EXPIRED: TradeAction.EXPIRED,
    EventKind.INDETERMINATE: TradeAction.INDETERMINATE,
}


def run_scenario(scenario: Scenario, *,
                 raise_on_error: bool = False) -> ScenarioResult:
    """Run one scenario and return its logs, snapshots and identity results.

    The runner never asserts. It records; the scenario asserts.
    """
    session = scenario.session
    window = scenario.window
    if not window.sessions:
        reference = window.reference_ticker or (
            window.tickers[0] if window.tickers else None)
        if reference is None:
            raise ValueError(
                f'scenario {scenario.name!r}: window has no sessions and no '
                f'reference_ticker to derive them from')
        window = window.with_sessions(
            sessions_from_source(scenario.source, reference,
                                 window.start, window.end))

    trades = TradeLog()
    cash = CashLog()
    settlement = SettlementLog()
    counter = _Counter()
    ctx = StrategyContext(session, scenario.source, trades, counter.next,
                          settlement=settlement)
    journal = LedgerJournal(session, cash, settlement, counter.next).attach()

    snapshots: List[Snapshot] = []
    events_seen: List[Event] = []
    tickers = tuple(dict.fromkeys(
        list(window.tickers) + list(scenario.opening_holdings)))
    error: Optional[BaseException] = None
    ran = 0

    def deliver(raw: Sequence[Event], phase: StepPhase) -> None:
        events_seen.extend(raw)
        _translate_events(session, raw, trades, settlement, counter,
                          session.provenance().settlement_calendar_id)
        journal.drain_deposit()
        ctx._set_step(phase, raw)
        scenario.strategy.on_events(ctx, tuple(raw))

    try:
        for index, day in enumerate(window.sessions):
            opened = session.advance_to(
                datetime.combine(day, scenario.open_time))
            deliver(opened, StepPhase.OPEN)
            if index == 0:
                scenario.strategy.on_start(ctx)
            scenario.strategy.on_session(ctx)
            journal.drain_deposit()
            snapshots.append(_snapshot(session, StepPhase.OPEN, tickers))

            closed = session.advance_to(
                datetime.combine(day, scenario.close_time))
            deliver(closed, StepPhase.CLOSE)
            snapshots.append(_snapshot(session, StepPhase.CLOSE, tickers))
            ran += 1
        ctx._set_step(StepPhase.CLOSE, ())
        scenario.strategy.on_finish(ctx)
    except BaseException as exc:               # noqa: BLE001 -- reported
        error = exc
        if raise_on_error:
            journal.drain_deposit()
            journal.detach()
            raise
    finally:
        journal.drain_deposit()
        journal.detach()

    logs = RunLogs(trades=trades, cash=cash, settlement=settlement,
                   events=tuple(events_seen),
                   charge_baseline=journal.charge_baseline)
    identities = check_identities(
        session, logs, snapshots,
        opening_holdings=scenario.opening_holdings, tickers=tickers)
    return ScenarioResult(
        name=scenario.name, window=window, provenance=session.provenance(),
        logs=logs, identities=identities, snapshots=tuple(snapshots),
        annotations=ctx.annotations,
        indeterminate=session.indeterminate_report(),
        sessions_run=ran, error=error, note=scenario.note)


class _Counter:
    """One monotone sequence shared by all three logs, so they interleave."""

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        self._n += 1
        return self._n


def _translate_events(session: Any, events: Sequence[Event], trades: TradeLog,
                      settlement: SettlementLog, counter: _Counter,
                      calendar_id: Optional[str]) -> None:
    """Write the session's own events into the trade and settlement logs.

    ``ACCEPTED`` and ``REJECTED`` are skipped **only when the log already has
    them**: :class:`StrategyContext` logs them from ``submit()``'s return
    value, which carries the binding constraint and the reservations the event
    does not, so translating those again would double every order a *strategy*
    placed.

    It logs nothing for an order the **broker** places, and a *ban giai chap*
    is the first of those in this simulator. Measured: a forced sale the
    exchange refused at the floor lock -- the single most interesting event in
    the equity-margin CURE arm -- had **zero** rows in the deliverable "trade
    log a real broker produces", surviving only in the margin event stream and
    the order book. ``order_lifecycle`` could not see it either: it checks
    fills-without-accepted and accepted-without-record, and a wholly absent
    order trips neither, so the identity under-reported its own breach.

    Margin events are **not** trade-log rows -- they belong to no order. They
    reach the caller as raw ``events`` on the result, and their cash effect,
    where they have one, is in the cash log.

    **``side`` is looked up from the order book, not read off the event.**
    ``Event.for_fill`` carries ticker, venue, quantity and price and *not* the
    side, so a fill row built from the event alone cannot say whether shares
    arrived or left -- which is the one thing holdings conservation needs.
    """
    by_id = {r.order_id: r for r in session.orders()}
    already = {(row.order_id, row.action) for row in trades
               if row.action in _ALREADY_LOGGED_ACTIONS}
    for event in events:
        if event.kind in _ALREADY_LOGGED:
            action = _ACTION_FOR_EVENT.get(event.kind)
            if (event.order_id, action) in already:
                continue                       # the strategy logged this one
            # A broker-placed order. Write the row the context could not.
        if event.kind is EventKind.SETTLEMENT_CREDITED:
            continue                           # the journal records both legs
        if event.kind is EventKind.EXPIRY_SETTLED:
            settlement.append(SettlementLogEntry(
                seq=counter.next(), ts=event.ts,
                action=SettlementAction.EXPIRY_SETTLED, leg='derivatives',
                pool=(event.pool.value if event.pool else 'derivatives'),
                ticker=event.ticker, quantity=event.quantity,
                amount=event.amount, settled_at=event.ts,
                settlement_calendar_id=calendar_id,
                reason=f'final settlement at {event.price} '
                       f'({event.detail.get("settlement_source")}; '
                       f'substituted={event.detail.get("substituted")})',
                detail=dict(event.detail)))
            continue
        action = _ACTION_FOR_EVENT.get(event.kind)
        if action is None:
            continue                           # margin events; see docstring
        detail = dict(event.detail)
        record = by_id.get(event.order_id)
        trades.append(TradeLogEntry(
            seq=counter.next(), ts=event.ts, action=action,
            order_id=event.order_id, ticker=event.ticker,
            venue=event.venue.value if event.venue else None,
            pool=event.pool.value if event.pool else None,
            side=(record.order.side.value if record is not None else None),
            order_type=(record.order.order_type.value
                        if record is not None else None),
            time_in_force=(record.time_in_force.value
                           if record is not None else None),
            limit_price=(record.order.limit_price
                         if record is not None else None),
            quantity=event.quantity,
            fill_quantity=(event.quantity
                           if action in (TradeAction.FILLED,
                                         TradeAction.PARTIALLY_FILLED)
                           else None),
            fill_price=event.price,
            remaining=detail.get('remaining'),
            trigger=_value(detail.get('trigger')),
            evidence=_value(detail.get('evidence')),
            confidence=detail.get('confidence'),
            missing_fields=tuple(detail.get('missing', ())),
            reason=detail.get('reason'),
            # A refusal names the rule that refused it. ``Event.rejected``
            # puts the rule on the event and the constraint in ``detail``, so
            # the row reads both. Only reachable for a broker-placed order,
            # since a strategy's refusals are written by ``StrategyContext``
            # from ``submit()``'s return value.
            rule=_value(getattr(event, 'rule', None)),
            binding_constraint=detail.get('binding_constraint'),
            verdict=_value(detail.get('verdict')),
            detail=detail))


def _value(item: Any) -> Any:
    return getattr(item, 'value', item)
