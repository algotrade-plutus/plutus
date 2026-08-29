"""The three logs a real broker produces: trade, cash, settlement.

Each entry is timestamped and carries **why** -- the rule that bound, the
reason string the module itself passed, the settlement rule in force. A log
that says what happened but not why cannot support an audit, which is the
whole reason these are separate objects rather than a filtered event stream.

**None of this is reconstructed from balances.** Every row is recorded at the
instant the movement happens, either from the session's own event cursor
(trade log) or from the ledger call that moved the money
(:mod:`validation.journal`). The one place a number is derived rather than
observed is :attr:`CashLogEntry.balance_after`, which is read back off the
ledger immediately after the movement.

Money is ``Decimal`` throughout. ``to_rows()`` renders each log as a list of
plain dicts for a report or a snapshot test; it converts ``Decimal`` to ``str``
rather than ``float``, because a rounded price in an audit log is a defect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

__all__ = [
    'TradeAction', 'TradeLogEntry', 'TradeLog',
    'CashMovement', 'CashLogEntry', 'CashLog',
    'SettlementAction', 'SettlementLogEntry', 'SettlementLog',
    'RunLogs', 'json_safe',
]

_ZERO = Decimal('0')


def json_safe(value: Any) -> Any:
    """Reduce to JSON-serialisable types **without losing a Decimal's value**.

    ``Decimal`` becomes ``str``, not ``float``. ``types._serialise`` (which
    backs ``Event.to_dict``) chooses ``float`` and says so; that is right for a
    debug dump and wrong for a ledger, so this module does not reuse it.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v) for v in value]
    return value


# --------------------------------------------------------------------------
# Trade log
# --------------------------------------------------------------------------

class TradeAction(str, Enum):
    """Every thing that can happen to an order, from the caller's side.

    ``SUBMITTED`` is recorded separately from ``ACCEPTED`` / ``REJECTED``
    because a submission that never reaches the book still happened and still
    has to be countable -- and because the session mints an order id even for a
    rejection, so the two rows join.

    ``CANCEL_REFUSED`` and ``AMEND_REFUSED`` exist because those refusals
    **never reach the session's event cursor** (FEATURES.md D13). They are
    captured from the return value of ``cancel()`` / ``amend()`` instead, which
    is the only place they are observable.
    """

    SUBMITTED = 'submitted'
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    PARTIALLY_FILLED = 'partially_filled'
    FILLED = 'filled'
    CANCELLED = 'cancelled'
    CANCEL_REFUSED = 'cancel_refused'
    AMENDED = 'amended'
    AMEND_REFUSED = 'amend_refused'
    EXPIRED = 'expired'
    INDETERMINATE = 'indeterminate'


@dataclass(frozen=True)
class TradeLogEntry:
    """One row of the trade log.

    The fields that carry the *why*:

    * ``rule`` -- the ``RejectionRule`` that refused, never a string. A
      rejection log keyed on prose cannot be counted.
    * ``verdict`` -- ``rejected`` (a rule said no) or ``indeterminate`` (the
      data could not decide). Conflating them reports a data gap as a market
      rule.
    * ``binding_constraint`` -- the number that bound: the tick, the lot, the
      band bound, the sellable quantity, ``Cash.available``.
    * ``unresolved_rule`` -- set when the rulebook could not resolve at all.
    * ``fill_policy`` -- the policy signature **in force for this decision**,
      not just its kind: ``hard`` at a 10% participation cap and ``hard`` at
      100% are different assumptions.
    * ``evidence`` / ``confidence`` -- how the fill was determined.
    """

    seq: int
    ts: datetime
    action: TradeAction
    order_id: Optional[str] = None
    ticker: Optional[str] = None
    venue: Optional[str] = None
    pool: Optional[str] = None
    side: Optional[str] = None
    order_type: Optional[str] = None
    time_in_force: Optional[str] = None
    quantity: Optional[int] = None
    limit_price: Optional[Decimal] = None
    fill_quantity: Optional[int] = None
    fill_price: Optional[Decimal] = None
    remaining: Optional[int] = None
    rule: Optional[str] = None
    verdict: Optional[str] = None
    binding_constraint: Optional[Any] = None
    unresolved_rule: Optional[str] = None
    sellable_from: Optional[datetime] = None
    regime_tag: Optional[str] = None
    trigger: Optional[str] = None
    evidence: Optional[str] = None
    confidence: Optional[Decimal] = None
    fill_policy: Optional[str] = None
    missing_fields: Tuple[str, ...] = ()
    reason: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> Dict[str, Any]:
        return json_safe(asdict(self))


class _Log:
    """Shared plumbing: append, iterate, filter, render."""

    _entry_type: type

    def __init__(self) -> None:
        self._entries: List[Any] = []

    def append(self, entry: Any) -> Any:
        if not isinstance(entry, self._entry_type):
            raise TypeError(
                f'{type(self).__name__} holds {self._entry_type.__name__}, '
                f'got {type(entry).__name__}')
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> Tuple[Any, ...]:
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def to_rows(self) -> List[Dict[str, Any]]:
        return [e.to_row() for e in self._entries]


class TradeLog(_Log):
    """Every order and every fill, in the order the session produced them."""

    _entry_type = TradeLogEntry

    def of(self, *actions: TradeAction) -> Tuple[TradeLogEntry, ...]:
        """Rows whose action is one of ``actions``."""
        wanted = frozenset(actions)
        return tuple(e for e in self._entries if e.action in wanted)

    def for_order(self, order_id: str) -> Tuple[TradeLogEntry, ...]:
        """One order's whole history, submission to terminal state."""
        return tuple(e for e in self._entries if e.order_id == order_id)

    @property
    def order_ids(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for entry in self._entries:
            if entry.order_id is not None and entry.order_id not in seen:
                seen.append(entry.order_id)
        return tuple(seen)


# --------------------------------------------------------------------------
# Cash log
# --------------------------------------------------------------------------

class CashMovement(str, Enum):
    """Why money moved. One member per cause the session actually has.

    ``OTHER_CREDIT`` / ``OTHER_DEBIT`` are not slack: they are what a movement
    lands on when the ledger's own reason string matches none of the known
    causes. A new cash movement added to the session therefore shows up in the
    log as unclassified rather than silently vanishing, and
    :func:`validation.identities.check_cash_conservation` still balances.
    """

    OPENING_BALANCE = 'opening_balance'
    BUY_CONSIDERATION = 'buy_consideration'
    SALE_PROCEEDS_PENDING = 'sale_proceeds_pending'
    SETTLEMENT_CREDIT = 'settlement_credit'
    CHARGE_DEBITED = 'charge_debited'
    CHARGE_WITHHELD = 'charge_withheld'
    TRANSFER_IN = 'transfer_in'
    TRANSFER_OUT = 'transfer_out'
    ADVANCE_DRAWN = 'advance_drawn'
    ADVANCE_REPAID = 'advance_repaid'
    ADVANCE_INTEREST_ACCRUED = 'advance_interest_accrued'
    REALISED_PNL = 'realised_pnl'
    VARIATION_SETTLEMENT = 'variation_settlement'
    EXPIRY_SETTLEMENT = 'expiry_settlement'
    OTHER_CREDIT = 'other_credit'
    OTHER_DEBIT = 'other_debit'


@dataclass(frozen=True)
class CashLogEntry:
    """One money movement, with its cause.

    ``amount`` is **signed from the pool's point of view**: positive is money
    arriving, negative is money leaving.

    ``affects_balance`` is the field the conservation identity reads. It is
    ``False`` for the three movements that are real cash events but do not move
    a settled balance:

    * ``SALE_PROCEEDS_PENDING`` -- a sale credits a *pending* tranche; the
      settled balance moves later, at ``SETTLEMENT_CREDIT``;
    * ``CHARGE_WITHHELD`` -- a sell-side charge already netted out of the
      pending amount. Debiting it again is the classic double count, and
      omitting it from the log entirely would hide the largest charge on every
      sale;
    * ``ADVANCE_DRAWN`` and ``ADVANCE_INTEREST_ACCRUED`` -- the advance raises
      ``Cash.available`` through ``advanced``, not through ``settled_balance``,
      and **interest on an advance is reported and never charged** anywhere in
      the session (``ledgers.py`` says so in terms).

    ``cause`` is the ledger's own reason string, verbatim where one exists.
    ``movement`` is this module's classification of it; where the two could
    disagree, the verbatim string is authoritative.
    """

    seq: int
    ts: datetime
    pool: str
    movement: CashMovement
    amount: Decimal
    cause: str
    affects_balance: bool = True
    balance_after: Optional[Decimal] = None
    order_id: Optional[str] = None
    fill_id: Optional[str] = None
    ticker: Optional[str] = None
    charge_kind: Optional[str] = None
    charge_base: Optional[str] = None
    charge_base_value: Optional[Decimal] = None
    vat: Optional[Decimal] = None
    settles_at: Optional[datetime] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> Dict[str, Any]:
        return json_safe(asdict(self))


class CashLog(_Log):
    """Every money movement in both pools, in the order they happened."""

    _entry_type = CashLogEntry

    def for_pool(self, pool: str) -> Tuple[CashLogEntry, ...]:
        return tuple(e for e in self._entries if e.pool == pool)

    def net(self, pool: Optional[str] = None,
            *, only_effective: bool = True) -> Decimal:
        """Signed sum. ``only_effective`` restricts to balance-moving rows."""
        rows: Iterable[CashLogEntry] = self._entries
        if pool is not None:
            rows = (e for e in rows if e.pool == pool)
        if only_effective:
            rows = (e for e in rows if e.affects_balance)
        return sum((e.amount for e in rows), _ZERO)

    def by_movement(self, pool: Optional[str] = None
                    ) -> Dict[CashMovement, Decimal]:
        """Signed totals per cause -- the itemisation an audit reads first."""
        out: Dict[CashMovement, Decimal] = {}
        for entry in self._entries:
            if pool is not None and entry.pool != pool:
                continue
            out[entry.movement] = out.get(entry.movement, _ZERO) + entry.amount
        return out


# --------------------------------------------------------------------------
# Settlement log
# --------------------------------------------------------------------------

class SettlementAction(str, Enum):
    """The life of a settlement tranche, plus the refusals it causes.

    ``SELL_REFUSED_UNSETTLED`` is in the settlement log rather than only in the
    trade log because it is the settlement cycle's most visible consequence and
    an auditor looking for "did T+2 bind" should not have to join two logs to
    find out.

    ``TRANCHE_ADJUSTED`` is a corporate action rescaling a tranche in place.
    It carries the post-event quantity, and it exists because without it the
    log is internally inconsistent: ``HoldingsLedger.apply_corporate_action``
    rescales 1,500 shares to 2,025 and preserves ``settles_at``, so the log
    showed a tranche **created** at 1,500 that never settled and a tranche
    **settled** at 2,025 that was never created -- one orphan and one ghost,
    on a run the scenario calls correct.
    """

    TRANCHE_CREATED = 'tranche_created'
    TRANCHE_ADJUSTED = 'tranche_adjusted'
    TRANCHE_SETTLED = 'tranche_settled'
    SELL_REFUSED_UNSETTLED = 'sell_refused_unsettled'
    EXPIRY_SETTLED = 'expiry_settled'


@dataclass(frozen=True)
class SettlementLogEntry:
    """One tranche event, carrying the rule that dated it.

    ``settles_at`` is the instant the tranche was *promised*; ``settled_at`` is
    when it actually settled. They are separate fields because the difference
    is the thing under test -- a tranche settled early or late is exactly the
    defect a settlement log exists to expose.

    ``settlement_rule`` and ``settlement_calendar_id`` carry the why: which
    dated ``SettlementRule`` was in force (T+2 with 13:00 delivery, or the
    pre-2022-08-29 next-session-open regime) and which calendar counted the
    business days. The default calendar's id contains ``UNSOURCED``, so a run
    whose settlement dates are wrong around Tet says so on every row.
    """

    seq: int
    ts: datetime
    action: SettlementAction
    leg: str                          # 'securities' | 'cash' | 'derivatives'
    pool: str
    ticker: Optional[str] = None
    quantity: Optional[int] = None
    amount: Optional[Decimal] = None
    settles_at: Optional[datetime] = None
    settled_at: Optional[datetime] = None
    order_id: Optional[str] = None
    settlement_rule: Optional[str] = None
    settlement_calendar_id: Optional[str] = None
    sellable_from: Optional[datetime] = None
    binding_constraint: Optional[Any] = None
    reason: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> Dict[str, Any]:
        return json_safe(asdict(self))


class SettlementLog(_Log):
    """Every tranche created, when it settled, and every unsettled-sell refusal."""

    _entry_type = SettlementLogEntry

    def of(self, *actions: SettlementAction) -> Tuple[SettlementLogEntry, ...]:
        wanted = frozenset(actions)
        return tuple(e for e in self._entries if e.action in wanted)

    @property
    def refusals(self) -> Tuple[SettlementLogEntry, ...]:
        return self.of(SettlementAction.SELL_REFUSED_UNSETTLED)

    def unsettled_at_end(self) -> Tuple[SettlementLogEntry, ...]:
        """Tranches created and never observed settling.

        Matched on ``(leg, order_id, settles_at, quantity, amount)`` -- the
        tranche's economic identity, the same key ``CashLedger`` uses, not
        object identity.

        **Matched with multiplicity, which is the fix.** The key was a
        ``set``, so two identical tranches -- same order, same size, same due
        instant -- collapsed to one entry and *one* settlement discharged
        *both*. Measured: ``partial_fill_then_cancel`` creates exactly that
        pair (two ``HoldingTranche(65000, settles 2022-11-14 13:00,
        PLU-00000001)``); with 2 created and 1 settled this method returned
        **0**. An auditor reaching for the one tool that answers "was a
        tranche created and never settled" got the answer "no" from a log
        that said "yes". Counting instead of set-membership costs nothing and
        cannot under-report.
        """
        def key(e: SettlementLogEntry) -> Tuple[Any, ...]:
            return (e.leg, e.order_id, e.settles_at, e.quantity, e.amount)

        settled: Dict[Tuple[Any, ...], int] = {}
        for entry in self.of(SettlementAction.TRANCHE_SETTLED):
            k = key(entry)
            settled[k] = settled.get(k, 0) + 1
        # A rescaled tranche settles under its NEW quantity, so the creation
        # row's key no longer matches the settlement row's. The adjustment row
        # is the bridge: it carries the post-event quantity, so it stands in
        # for the creation it superseded and the original is discharged.
        adjusted: Dict[Tuple[Any, ...], int] = {}
        for entry in self.of(SettlementAction.TRANCHE_ADJUSTED):
            before = (entry.leg, entry.order_id, entry.settles_at,
                      entry.detail.get('quantity_before'), entry.amount)
            adjusted[before] = adjusted.get(before, 0) + 1
            k = key(entry)
            if settled.get(k, 0) > 0:
                settled[k] -= 1
        out: List[SettlementLogEntry] = []
        for entry in self.of(SettlementAction.TRANCHE_CREATED):
            k = key(entry)
            if settled.get(k, 0) > 0:
                settled[k] -= 1        # one settlement discharges one tranche
            elif adjusted.get(k, 0) > 0:
                adjusted[k] -= 1       # superseded by a corporate action
            else:
                out.append(entry)
        return tuple(out)


# --------------------------------------------------------------------------
# The bundle
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RunLogs:
    """The three logs of one run, plus the raw event stream they came from.

    ``events`` is kept because the session's cursor is **destructive and
    single-consumer**: once the runner drains it nothing else can, so a
    scenario that wants the raw events must get them from here.
    """

    trades: TradeLog
    cash: CashLog
    settlement: SettlementLog
    events: Tuple[Any, ...] = ()

    #: How many charges the session had already levied when this run's journal
    #: attached. ``ExchangeSession.charges()`` is the session's whole life, not
    #: this run's, so an identity comparing charges to rows must skip the first
    #: ``charge_baseline`` of them or a chained pair reports the *first* run's
    #: charges as missing from the *second* run's log. Index rather than
    #: timestamp: the two runs of a chained pair can share an instant, and one
    #: measured case had a run-1 charge at exactly the run-2 opening row's ts.
    charge_baseline: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'trade_log': self.trades.to_rows(),
            'cash_log': self.cash.to_rows(),
            'settlement_log': self.settlement.to_rows(),
        }

    def counts(self) -> Dict[str, int]:
        return {'trade_log': len(self.trades),
                'cash_log': len(self.cash),
                'settlement_log': len(self.settlement),
                'events': len(self.events)}
