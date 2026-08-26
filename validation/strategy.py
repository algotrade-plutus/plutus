"""The strategy interface: a trading algorithm as a *caller* of the simulator.

Plutus is not a backtesting engine and this does not turn it into one. A
``Strategy`` here owns no portfolio, computes no P&L and holds no cash; it
receives market state and events and submits or cancels orders, exactly as an
algorithm connected to a broker API does. Everything it can see about its own
position, it reads back from the exchange.

Four hooks, and they are the smallest set that expresses the scenarios::

    on_start(ctx)              once, before the first session
    on_events(ctx, events)     the events since the last call
    on_session(ctx)            the decision point: submit and cancel here
    on_finish(ctx)             once, after the last session

Why these four and not fewer:

* **Overnight holding** needs no hook at all -- it is what happens when
  ``on_session`` does nothing. That is the point of separating the runner's
  clock from the strategy's decisions.
* **Rolling at expiry** needs ``ctx.instrument(code).expiry`` and
  ``ctx.positions()``; both are reads off the exchange, so a roll is two
  ordinary orders on one ``on_session`` call.
* **Two venues at once** needs nothing special either: ``ctx.submit`` routes
  on ``(ticker, ts)`` like the session does, and the two legs draw on two
  segregated pools. A pair the account funds *in aggregate* can still be
  refused on one leg, and that refusal is the interesting result.

**The strategy must never call ``session.poll()``.** The session's event
cursor is destructive and single-consumer; the runner drains it and hands the
events to ``on_events``. :class:`StrategyContext` therefore does not expose
``poll``, and does not expose the session object either.

**Market data does not come from the exchange.** ``ctx.market(ticker)`` reads
the run's data source directly, because that is what a real algorithm has: its
own feed. The exchange tells you about *your orders*, not about the market.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import (Any, Callable, Dict, List, Optional, Protocol, Sequence,
                    Tuple, Union, runtime_checkable)

from plutus.core.order import OrderType, Side
from plutus.market.protocol import InstrumentSpec, MarketState, Order
from plutus.market.session.types import (
    Accepted, Amended, Cancelled, Cash, Charge, ContractPosition, Event,
    Holding, MarginView, OrderRecord, OrderState, Pool, Rejected,
    SessionProvenance, TIME_IN_FORCE, Transferred,
)

from validation.logs import (
    SettlementAction, SettlementLog, SettlementLogEntry, TradeAction, TradeLog,
    TradeLogEntry,
)

__all__ = ['Strategy', 'BaseStrategy', 'StrategyContext', 'StepPhase',
           'Annotation']

_ZERO = Decimal('0')


class StepPhase(str, Enum):
    """Where in the trading day a step sits.

    The runner takes two steps per session because ``advance_to``'s own
    docstring requires it: an order must be submitted *between* the advance
    that lands inside the day and the advance that crosses out of it, or the
    day's bar is never offered to it.
    """

    OPEN = 'open'
    CLOSE = 'close'


@dataclass(frozen=True)
class Annotation:
    """A strategy's own note, carried into the result.

    Scenarios use it to record what they *intended* -- "entering the 3-lot
    long that the window is sized to break" -- so a reader of the logs can
    tell a deliberate breach from an accident.
    """

    ts: datetime
    text: str
    detail: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Strategy(Protocol):
    """What a scenario author writes. All four hooks are optional in practice
    -- :class:`BaseStrategy` supplies no-op defaults -- but the protocol names
    them so a strategy written from scratch knows the full surface."""

    name: str

    def on_start(self, ctx: 'StrategyContext') -> None: ...

    def on_events(self, ctx: 'StrategyContext',
                  events: Sequence[Event]) -> None: ...

    def on_session(self, ctx: 'StrategyContext') -> None: ...

    def on_finish(self, ctx: 'StrategyContext') -> None: ...


class BaseStrategy:
    """No-op defaults, so a scenario overrides only what it needs.

    Subclassing is optional: :class:`Strategy` is a structural protocol, so a
    strategy that inherits nothing works as long as it has ``name`` and the
    hooks it uses.
    """

    name = 'unnamed'

    def on_start(self, ctx: 'StrategyContext') -> None:
        """Called once, standing at the first session's OPEN step."""

    def on_events(self, ctx: 'StrategyContext',
                  events: Sequence[Event]) -> None:
        """Called with the events the last advance produced, before
        :meth:`on_session`."""

    def on_session(self, ctx: 'StrategyContext') -> None:
        """The decision point. Submit, cancel, amend and transfer here."""

    def on_finish(self, ctx: 'StrategyContext') -> None:
        """Called once after the last advance, with the run's final state."""


class StrategyContext:
    """The narrow facade a strategy sees. **Not** the session.

    Every order-affecting call made through this object is written to the
    trade log with the verdict it produced -- including the refusals that
    never reach the session's event cursor (``cancel``, ``amend`` and
    ``transfer`` refusals; FEATURES.md D13). That is why the strategy goes
    through the context rather than holding the session: the log would
    otherwise be missing exactly the rows an audit looks for.
    """

    def __init__(self, session: Any, source: Any, trades: TradeLog,
                 next_seq: Callable[[], int],
                 settlement: Optional[SettlementLog] = None) -> None:
        self._session = session
        self._source = source
        self._trades = trades
        self._settlement = settlement
        self._next_seq = next_seq
        self._events: Tuple[Event, ...] = ()
        self._phase: StepPhase = StepPhase.OPEN
        self._annotations: List[Annotation] = []

    # -- clock and step ---------------------------------------------------

    @property
    def now(self) -> datetime:
        """The instant the session is standing at."""
        return self._session.now()

    @property
    def today(self) -> date:
        return self._session.now().date()

    @property
    def phase(self) -> StepPhase:
        """``OPEN`` on the decision step, ``CLOSE`` after the day is marked."""
        return self._phase

    @property
    def events(self) -> Tuple[Event, ...]:
        """The events delivered to the last :meth:`Strategy.on_events` call."""
        return self._events

    @property
    def annotations(self) -> Tuple[Annotation, ...]:
        return tuple(self._annotations)

    def note(self, text: str, **detail: Any) -> Annotation:
        """Record a strategy note against the current instant."""
        entry = Annotation(ts=self.now, text=text, detail=dict(detail))
        self._annotations.append(entry)
        return entry

    # -- market data: the caller's own feed, not the exchange -------------

    def market(self, ticker: str,
               ts: Optional[datetime] = None) -> Optional[MarketState]:
        """The data source's state for ``ticker`` at ``ts`` (default now).

        ``None`` when the source has no row -- a non-trading day, a delisted
        name, or a contract not yet listed. A strategy must handle it; the
        simulator will not invent a price.
        """
        if self._source is None:
            return None
        return self._source.state_at(ticker, ts or self.now)

    def price(self, ticker: str,
              ts: Optional[datetime] = None) -> Optional[Decimal]:
        """``market(ticker).last``, or ``None``."""
        state = self.market(ticker, ts)
        return None if state is None else state.last

    def instrument(self, ticker: str,
                   ts: Optional[datetime] = None) -> InstrumentSpec:
        """The dated instrument: venue, lot, band, multiplier, **expiry**.

        Resolved per instant through the session's ``SymbolRouter``, never
        cached by ticker. ``expiry`` is what a roll strategy keys on.
        """
        return self._session.instrument(ticker, ts)

    # -- account reads ----------------------------------------------------

    def cash(self) -> Cash:
        return self._session.cash()

    def holdings(self, ticker: str) -> Holding:
        return self._session.holdings(ticker)

    def positions(self) -> Dict[str, ContractPosition]:
        return self._session.positions()

    def margin(self) -> MarginView:
        return self._session.margin()

    def charges(self) -> Tuple[Charge, ...]:
        return self._session.charges()

    def orders(self, *, state: Optional[OrderState] = None,
               ticker: Optional[str] = None) -> Tuple[OrderRecord, ...]:
        return tuple(self._session.orders(state=state, ticker=ticker))

    def live_orders(self, ticker: Optional[str] = None
                    ) -> Tuple[OrderRecord, ...]:
        """Every order not in a terminal state."""
        return tuple(r for r in self._session.orders(ticker=ticker)
                     if not r.is_terminal)

    def provenance(self) -> SessionProvenance:
        return self._session.provenance()

    # -- actions ----------------------------------------------------------

    def submit(self, order: Order) -> Union[Accepted, Rejected]:
        """Submit an order and log both the submission and its verdict."""
        self._log_submission(order)
        outcome = self._session.submit(order)
        self._log_outcome(order, outcome)
        return outcome

    def buy(self, ticker: str, quantity: int, *,
            limit_price: Optional[Decimal] = None,
            order_type: OrderType = OrderType.LIMIT,
            is_foreign: bool = False) -> Union[Accepted, Rejected]:
        return self.submit(Order(ticker=ticker, side=Side.BUY,
                                 quantity=quantity, order_type=order_type,
                                 limit_price=limit_price,
                                 is_foreign=is_foreign))

    def sell(self, ticker: str, quantity: int, *,
             limit_price: Optional[Decimal] = None,
             order_type: OrderType = OrderType.LIMIT,
             is_foreign: bool = False) -> Union[Accepted, Rejected]:
        return self.submit(Order(ticker=ticker, side=Side.SELL,
                                 quantity=quantity, order_type=order_type,
                                 limit_price=limit_price,
                                 is_foreign=is_foreign))

    def cancel(self, order_id: str) -> Union[Cancelled, Rejected]:
        """Cancel, and log the refusal if there is one.

        A cancel refusal never reaches the session's event cursor, so this is
        the only place it is observable.
        """
        outcome = self._session.cancel(order_id)
        if isinstance(outcome, Rejected):
            self._append(TradeAction.CANCEL_REFUSED, order_id=order_id,
                         rejection=outcome,
                         reason='cancel() refused; this refusal is not on the '
                                'session event cursor')
        else:
            self._append(TradeAction.CANCELLED, order_id=order_id,
                         quantity=outcome.filled_quantity,
                         reason='cancel() accepted (also emitted as an event)')
        return outcome

    def amend(self, order_id: str, *, quantity: Optional[int] = None,
              limit_price: Optional[Decimal] = None
              ) -> Union[Amended, Rejected]:
        outcome = self._session.amend(order_id, quantity=quantity,
                                      limit_price=limit_price)
        if isinstance(outcome, Rejected):
            self._append(TradeAction.AMEND_REFUSED, order_id=order_id,
                         quantity=quantity, limit_price=limit_price,
                         rejection=outcome,
                         reason='amend() refused; this refusal is not on the '
                                'session event cursor')
        else:
            self._append(TradeAction.AMENDED, order_id=order_id,
                         quantity=outcome.quantity,
                         reason=f'amend() accepted, priority_preserved='
                                f'{outcome.priority_preserved}')
        return outcome

    # -- the sale advance: not on the session API -------------------------

    def advanceable(self, *, order_id: Optional[str] = None) -> Decimal:
        """How much may still be drawn against unsettled sale proceeds.

        **This reaches past the session API, because there is not one.**
        ``CashLedger`` and ``SecuritiesAccount`` both implement
        *ung truoc tien ban* in full -- the cap, the day-count, the accrual,
        the recovery at settlement -- and ``ExchangeSession`` exposes no method
        that reaches it. A strategy connected through the session alone
        therefore cannot use the product at all, and sell-then-rebuy on the
        same day stays impossible even at a broker that offers it.

        Recorded here rather than worked around silently: if the session grows
        a ``request_advance``, delete these two methods and call it.
        """
        return self._session._securities.advanceable(order_id=order_id,
                                                     now=self.now)

    def request_advance(self, amount: Optional[Decimal] = None, *,
                        order_id: Optional[str] = None) -> Tuple[Any, ...]:
        """Draw a sale advance. See :meth:`advanceable` for why this is here.

        Returns the ``SaleAdvance`` rows drawn. Interest on them is
        **reported and never charged**: no code path in the session debits
        it, so the cash log carries the accrual with ``affects_balance=False``
        and says so.
        """
        return self._session._securities.request_advance(
            self.now, amount, order_id=order_id)

    def transfer(self, source: Pool, destination: Pool,
                 amount: Decimal) -> Union[Transferred, Rejected]:
        """Move cash between the two segregated pools.

        There is no auto-transfer in Vietnam, so answering a margin call out
        of securities cash is an explicit act and a scenario has to perform
        it. The refusal, when the source pool is short, is annotated with what
        the *other* pool held.
        """
        outcome = self._session.transfer(source, destination, amount)
        if isinstance(outcome, Rejected):
            self._append(TradeAction.REJECTED, rejection=outcome,
                         reason=f'transfer {source.value} -> '
                                f'{destination.value} of {amount} refused')
        return outcome

    # -- trade-log plumbing -----------------------------------------------

    def _log_submission(self, order: Order) -> None:
        self._trades.append(TradeLogEntry(
            seq=self._next_seq(), ts=self.now, action=TradeAction.SUBMITTED,
            ticker=order.ticker, side=order.side.value,
            order_type=order.order_type.value,
            time_in_force=_tif_name(order.order_type),
            quantity=order.quantity, limit_price=order.limit_price,
            fill_policy=self._policy_signature(),
            reason='strategy submitted an order',
            detail={'is_foreign': order.is_foreign}))

    def _log_outcome(self, order: Order,
                     outcome: Union[Accepted, Rejected]) -> None:
        if isinstance(outcome, Rejected):
            self._append(TradeAction.REJECTED, order_id=outcome.order_id,
                         ticker=order.ticker, order=order, rejection=outcome,
                         reason='submit() refused at admission or funding')
            self._log_unsettled_refusal(order, outcome)
            return
        self._trades.append(TradeLogEntry(
            seq=self._next_seq(), ts=outcome.ts, action=TradeAction.ACCEPTED,
            order_id=outcome.order_id, ticker=order.ticker,
            venue=outcome.venue.value, pool=_pool_of(outcome.venue),
            side=order.side.value, order_type=order.order_type.value,
            time_in_force=_tif_name(order.order_type),
            quantity=order.quantity, limit_price=order.limit_price,
            fill_policy=self._policy_signature(),
            reason='accepted; reservations taken',
            detail={'encumbrances': [
                {'resource': e.resource.value, 'pool': e.pool.value,
                 'amount': e.amount, 'quantity': e.quantity}
                for e in outcome.encumbrances]}))

    def _log_unsettled_refusal(self, order: Order,
                               rejection: Rejected) -> None:
        """A sell refused because the shares have not settled.

        Logged in the **settlement** log as well as the trade log: it is the
        settlement cycle's most visible consequence, and an auditor asking
        "did T+2 bind?" should not have to join two logs to find out.
        """
        if self._settlement is None:
            return
        rule = getattr(rejection.rule, 'value', rejection.rule)
        if rule != 'unsettled_holding':
            return
        self._settlement.append(SettlementLogEntry(
            seq=self._next_seq(), ts=rejection.ts,
            action=SettlementAction.SELL_REFUSED_UNSETTLED, leg='securities',
            pool='securities', ticker=order.ticker, quantity=order.quantity,
            order_id=rejection.order_id,
            sellable_from=rejection.sellable_from,
            binding_constraint=rejection.binding_constraint,
            settlement_rule=self._settlement_label(rejection.ts),
            settlement_calendar_id=(
                self._session.provenance().settlement_calendar_id),
            reason='sell refused: the requested quantity is not deliverable '
                   'yet. binding_constraint is what was sellable; '
                   'sellable_from is when the request becomes sellable',
            detail=dict(rejection.detail)))

    def _settlement_label(self, ts: datetime) -> Optional[str]:
        """The dated settlement regime at ``ts``, or ``None`` if unresolved."""
        from plutus.market.protocol import InstrumentKind
        try:
            rule = self._session._rulebook.at(ts).settlement_rule(
                InstrumentKind.STOCK)
        except Exception:                      # pragma: no cover - defensive
            return None
        return rule.label if rule is not None else None

    def _append(self, action: TradeAction, *,
                order_id: Optional[str] = None,
                ticker: Optional[str] = None,
                quantity: Optional[int] = None,
                limit_price: Optional[Decimal] = None,
                order: Optional[Order] = None,
                rejection: Optional[Rejected] = None,
                reason: Optional[str] = None) -> None:
        detail: Dict[str, Any] = {}
        rule = verdict = unresolved = regime = None
        binding = sellable = None
        if rejection is not None:
            rule = getattr(rejection.rule, 'value', rejection.rule)
            verdict = getattr(rejection.verdict, 'value', rejection.verdict)
            binding = rejection.binding_constraint
            sellable = rejection.sellable_from
            regime = rejection.regime_tag
            detail = dict(rejection.detail)
            unresolved = detail.get('unresolved_rule')
        self._trades.append(TradeLogEntry(
            seq=self._next_seq(), ts=self.now, action=action,
            order_id=order_id,
            ticker=ticker or (order.ticker if order is not None else None),
            side=(order.side.value if order is not None else None),
            order_type=(order.order_type.value if order is not None else None),
            time_in_force=(_tif_name(order.order_type)
                           if order is not None else None),
            quantity=quantity if quantity is not None
            else (order.quantity if order is not None else None),
            limit_price=limit_price if limit_price is not None
            else (order.limit_price if order is not None else None),
            rule=rule, verdict=verdict, binding_constraint=binding,
            unresolved_rule=unresolved, sellable_from=sellable,
            regime_tag=regime, fill_policy=self._policy_signature(),
            reason=reason, detail=detail))

    def _policy_signature(self) -> Optional[str]:
        return self._session.provenance().fill_policy_kind

    # -- runner-only ------------------------------------------------------

    def _set_step(self, phase: StepPhase, events: Sequence[Event]) -> None:
        self._phase = phase
        self._events = tuple(events)


def _tif_name(order_type: OrderType) -> Optional[str]:
    tif = TIME_IN_FORCE.get(order_type)
    return None if tif is None else tif.value


def _pool_of(venue: Any) -> Optional[str]:
    from plutus.market.session.types import pool_for_venue
    try:
        return pool_for_venue(venue).value
    except Exception:                          # pragma: no cover - defensive
        return None
