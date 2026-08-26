"""Ledger identities, as reusable checks.

Each identity is a statement that must be true of *any* run, whatever the
strategy did. They are the audit: a green scenario that never checked these
proves nothing, and a red one names the account it broke.

Every check returns an :class:`IdentityResult` rather than raising, so one
failing identity does not hide the others -- the runner collects them all and
the scenario decides whether to assert.

The seven:

============================  =============================================
``cash_conservation``         opening + every movement == closing, per pool
``deposit_balance_trail``     the deposit's own audit trail sums to the
                              balance it reports
``encumbrance_zero``          with no live orders, nothing stays reserved
``encumbrance_matches``       records and ledgers agree about what is
                              reserved (design section 12 invariant 4)
``holdings_conservation``     opening + buys - sells == closing, per ticker
``no_negative_settled``       settled holdings are never negative
``order_lifecycle``           every fill traces to an accepted order and
                              every accepted order to a live or terminal
                              state
``deposit_segregation``       the two pools move only through matched,
                              explicit transfers
============================  =============================================
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from plutus.core.order import Side

from validation.logs import (
    CashLog, CashMovement, RunLogs, SettlementAction, TradeAction, json_safe,
)

__all__ = ['IdentityResult', 'check_identities', 'cash_conservation',
           'deposit_balance_trail', 'encumbrance_zero', 'encumbrance_matches',
           'holdings_conservation', 'no_negative_settled', 'order_lifecycle',
           'deposit_segregation']

_ZERO = Decimal('0')
SECURITIES = 'securities'
DERIVATIVES = 'derivatives'


@dataclass(frozen=True)
class IdentityResult:
    """One identity, checked. ``passed`` is the only field a test must read.

    ``expected`` / ``actual`` / ``difference`` are populated for the numeric
    identities and left ``None`` for the structural ones. ``breaches`` names
    every individual violation, so a failure says *which* ticker or *which*
    order, not merely that something is wrong.
    """

    name: str
    passed: bool
    detail: str
    expected: Optional[Decimal] = None
    actual: Optional[Decimal] = None
    difference: Optional[Decimal] = None
    breaches: Tuple[Dict[str, Any], ...] = ()

    #: The check did not run. **A skip is not a pass**, and reporting it as
    #: one was found by two validation scenarios: a run ending with an order
    #: still live and 47,233,456d of committed cash printed ``9/9 held`` over
    #: the leak, because ``encumbrance_zero`` returned ``passed=True`` with
    #: ``detail='not applicable'``. ``passed`` stays ``True`` so a skip never
    #: fails a run that is otherwise sound; ``summary()`` counts it
    #: separately, so a green line can no longer be bought by not looking.
    skipped: bool = False

    def to_row(self) -> Dict[str, Any]:
        return json_safe(asdict(self))

    def __bool__(self) -> bool:
        return self.passed


def _result(name: str, expected: Decimal, actual: Decimal,
            detail: str) -> IdentityResult:
    diff = actual - expected
    return IdentityResult(name=name, passed=diff == _ZERO, detail=detail,
                          expected=expected, actual=actual, difference=diff)


# --------------------------------------------------------------------------
# 1. Cash conservation
# --------------------------------------------------------------------------

def cash_conservation(cash_log: CashLog, pool: str,
                      closing_balance: Decimal) -> IdentityResult:
    """opening + every balance-moving row == the balance the session reports.

    The log's ``OPENING_BALANCE`` row *is* the opening term, so this reduces
    to "the movements sum to the closing balance". Rows with
    ``affects_balance=False`` -- pending sale proceeds, charges withheld at
    source, an advance drawn, interest accrued -- are excluded, because they
    are cash events that do not move a settled balance. Excluding them is the
    substantive claim: if one of them *did* move the balance, this fails.
    """
    total = cash_log.net(pool)
    itemised = {m.value: str(v) for m, v in cash_log.by_movement(pool).items()}
    outcome = _result(
        f'cash_conservation[{pool}]', closing_balance, total,
        f'sum of balance-moving cash-log rows for the {pool} pool against '
        f'the balance the session reports')
    return IdentityResult(**{**asdict(outcome), 'breaches': ()
                             if outcome.passed
                             else ({'itemised': itemised},)})


# --------------------------------------------------------------------------
# 2. The deposit's own audit trail
# --------------------------------------------------------------------------

def deposit_balance_trail(session: Any) -> IdentityResult:
    """``DerivativesAccount.entries`` sums to ``deposit_balance``.

    A stronger statement than it looks: the entries are the *only* record of
    why the deposit moved, so a movement that bypassed ``_move`` would leave
    the balance right and the trail short. This is the check that would catch
    it.
    """
    entries = session._derivatives.entries
    total = sum((e.amount for e in entries), _ZERO)
    balance = session._derivatives.deposit_balance
    last = entries[-1].balance_after if entries else _ZERO
    outcome = _result('deposit_balance_trail', balance, total,
                      'signed sum of every DepositEntry against the '
                      'deposit balance the account reports')
    if outcome.passed and entries and last != balance:
        return IdentityResult(
            name='deposit_balance_trail', passed=False,
            detail='the last DepositEntry.balance_after disagrees with the '
                   'balance the account reports',
            expected=balance, actual=last, difference=last - balance)
    return outcome


# --------------------------------------------------------------------------
# 3 & 4. Encumbrance
# --------------------------------------------------------------------------

def encumbrance_zero(session: Any,
                     tickers: Sequence[str] = ()) -> IdentityResult:
    """With no live orders, every reservation has been released.

    A reservation that survives its order is the leak class the single
    terminal hook exists to prevent; it shows up here as committed cash or
    resting-order margin that nothing owns.
    """
    live = [r for r in session.orders() if not r.is_terminal]
    if live:
        return IdentityResult(
            name='encumbrance_zero', passed=True, skipped=True,
            detail=f'not applicable: {len(live)} order(s) still live at the '
                   f'end of the run',
            breaches=())
    breaches: List[Dict[str, Any]] = []
    cash = session.cash()
    if cash.committed != _ZERO:
        breaches.append({'what': 'cash.committed', 'value': cash.committed})
    resting = session.margin().resting_order_margin
    if resting != _ZERO:
        breaches.append({'what': 'margin.resting_order_margin',
                         'value': resting})
    for ticker in tickers:
        committed = session.holdings(ticker).committed
        if committed:
            breaches.append({'what': f'holdings[{ticker}].committed',
                             'value': committed})
    return IdentityResult(
        name='encumbrance_zero', passed=not breaches,
        detail='no live orders, so committed cash, resting-order margin and '
               'committed quantity must all be zero',
        breaches=tuple(breaches))


def encumbrance_matches(session: Any,
                        tickers: Sequence[str] = ()) -> IdentityResult:
    """Records and ledgers agree about what is reserved.

    Design section 12 invariant 4. The two totals are stored in different
    objects updated by different code paths, which is exactly why they can
    disagree; a run that never checks it can have a record claiming reserved
    cash the ledger has already consumed.
    """
    live = [r for r in session.orders() if not r.is_terminal]
    breaches: List[Dict[str, Any]] = []
    record_cash = sum((r.encumbered_cash for r in live), _ZERO)
    if record_cash != session.cash().committed:
        breaches.append({'what': 'cash', 'records': record_cash,
                         'ledger': session.cash().committed})
    record_deposit = sum((r.encumbered_deposit for r in live), _ZERO)
    if record_deposit != session.margin().resting_order_margin:
        breaches.append({'what': 'deposit', 'records': record_deposit,
                         'ledger': session.margin().resting_order_margin})
    for ticker in tickers:
        held = sum(r.encumbered_quantity for r in live
                   if r.order.ticker == ticker)
        if held != session.holdings(ticker).committed:
            breaches.append({'what': f'quantity[{ticker}]', 'records': held,
                             'ledger': session.holdings(ticker).committed})
    return IdentityResult(
        name='encumbrance_matches', passed=not breaches,
        detail='sum of encumbrance carried on live OrderRecords against the '
               "ledgers' committed totals (design section 12 invariant 4)",
        breaches=tuple(breaches))


# --------------------------------------------------------------------------
# 5 & 6. Holdings
# --------------------------------------------------------------------------

def _net_filled(logs: RunLogs, ticker: str) -> Tuple[int, int, List[int]]:
    """``(bought, sold, rows_with_no_side)`` for one ticker's fills."""
    fills = [e for e in logs.trades
             if e.ticker == ticker
             and e.action in (TradeAction.FILLED,
                              TradeAction.PARTIALLY_FILLED)]
    bought = sum(e.fill_quantity or 0 for e in fills
                 if e.side == Side.BUY.value)
    sold = sum(e.fill_quantity or 0 for e in fills
               if e.side == Side.SELL.value)
    unsided = [e.seq for e in fills
               if e.side not in (Side.BUY.value, Side.SELL.value)]
    return bought, sold, unsided


def _pools_by_ticker(logs: RunLogs) -> Dict[str, str]:
    """Which pool each traded ticker belongs to, from the log's own rows.

    Read off the ``ACCEPTED`` and fill rows rather than re-resolved through
    the router, so the identity judges the run that happened.
    """
    pools: Dict[str, str] = {}
    for entry in logs.trades:
        if entry.ticker and entry.pool:
            pools.setdefault(entry.ticker, entry.pool)
    return pools


def holdings_conservation(session: Any, logs: RunLogs,
                          opening: Mapping[str, int],
                          tickers: Sequence[str]) -> IdentityResult:
    """opening + filled buys - filled sells == closing quantity, per ticker.

    Two ledgers, two arithmetics, and the identity is different in each:

    * **securities** -- ``closing`` is ``settled + unsettled``. Shares bought
      and not yet settled are owned; they are merely not deliverable.
    * **derivatives** -- ``closing`` is the contract ledger's net-signed
      quantity, which is zero once the contract expires. Expiry is a real
      reduction, so the ``EXPIRY_SETTLED`` quantity is subtracted from the
      expectation rather than reported as a breach.

    **A corporate action breaks the securities half legitimately** -- a bonus
    issue creates shares no fill produced. The corporate-action engine is not
    wired into ``advance_to`` by design, so a run that applies one must pass
    the resulting quantities in ``opening`` or expect this to fail and say why.
    """
    breaches: List[Dict[str, Any]] = []
    pools = _pools_by_ticker(logs)
    expired: Dict[str, int] = {}
    for row in logs.settlement.of(SettlementAction.EXPIRY_SETTLED):
        if row.ticker is not None:
            expired[row.ticker] = expired.get(row.ticker, 0) + (row.quantity or 0)
    positions = session.positions()
    for ticker in tickers:
        bought, sold, unsided = _net_filled(logs, ticker)
        if unsided:
            breaches.append({'ticker': ticker,
                             'what': 'fill rows with no side; the identity '
                                     'cannot be evaluated',
                             'seqs': unsided})
        pool = pools.get(ticker, SECURITIES)
        if pool == DERIVATIVES:
            expected = (int(opening.get(ticker, 0)) + bought - sold
                        - expired.get(ticker, 0))
            position = positions.get(ticker)
            actual = 0 if position is None else position.net_quantity
            leg = 'contract ledger net quantity'
        else:
            expected = int(opening.get(ticker, 0)) + bought - sold
            actual = session.holdings(ticker).total
            leg = 'settled + unsettled'
        if expected != actual:
            breaches.append({'ticker': ticker, 'pool': pool, 'leg': leg,
                             'opening': opening.get(ticker, 0),
                             'bought': bought, 'sold': sold,
                             'expiry_settled': expired.get(ticker, 0),
                             'expected': expected, 'actual': actual})
    return IdentityResult(
        name='holdings_conservation', passed=not breaches,
        detail='opening quantity plus filled buys less filled sells (less any '
               'expiry settlement) against the closing quantity in the ledger '
               'that owns the instrument',
        breaches=tuple(breaches))


def no_negative_settled(snapshots: Sequence[Any]) -> IdentityResult:
    """Settled holdings are never negative, at any step.

    Vietnam has no operational short selling, so a negative settled quantity
    is not a position, it is a corrupt ledger. Sampled at every step rather
    than at the end, because a transient negative that squares up by the close
    is still a defect.
    """
    breaches: List[Dict[str, Any]] = []
    for snap in snapshots:
        for ticker, holding in snap.holdings.items():
            if holding['settled'] < 0:
                breaches.append({'ts': snap.ts.isoformat(), 'ticker': ticker,
                                 'settled': holding['settled']})
    return IdentityResult(
        name='no_negative_settled', passed=not breaches,
        detail='minimum settled quantity across every ticker and every step',
        breaches=tuple(breaches))


# --------------------------------------------------------------------------
# 7. Order lifecycle
# --------------------------------------------------------------------------

def order_lifecycle(session: Any, logs: RunLogs) -> IdentityResult:
    """Every fill traces to an accepted order; every accepted order resolves.

    Two directions, and both matter. A fill with no accepted order means the
    fill path ran ahead of admission. An accepted order that is neither live
    nor terminal at the end of the run means the state machine lost it -- and
    since a reservation is released on the terminal edge, a lost order is also
    a leaked reservation.
    """
    accepted = {e.order_id for e in logs.trades.of(TradeAction.ACCEPTED)}
    breaches: List[Dict[str, Any]] = []
    for entry in logs.trades.of(TradeAction.FILLED,
                                TradeAction.PARTIALLY_FILLED):
        if entry.order_id not in accepted:
            breaches.append({'what': 'fill with no accepted order',
                             'order_id': entry.order_id, 'seq': entry.seq})
    for order_id in accepted:
        records = [r for r in session.orders() if r.order_id == order_id]
        if not records:
            breaches.append({'what': 'accepted order absent from the book',
                             'order_id': order_id})
            continue
        record = records[0]
        if not (record.is_terminal or record.is_live):
            breaches.append({'what': 'accepted order neither live nor terminal',
                             'order_id': order_id,
                             'state': record.state.value})
    return IdentityResult(
        name='order_lifecycle', passed=not breaches,
        detail='every fill joins to an ACCEPTED row, and every accepted order '
               'is live or terminal in the book at the end of the run',
        breaches=tuple(breaches))


# --------------------------------------------------------------------------
# 8. Segregation
# --------------------------------------------------------------------------

def deposit_segregation(session: Any, logs: RunLogs) -> IdentityResult:
    """The two pools move only through matched, explicit transfers.

    Vietnam has no auto-transfer between the securities account and the
    derivatives deposit, so a caller whose deposit runs short while holding
    securities cash gets a call. Three ways that can go wrong, all checked:

    * a transfer that debits one pool and does not credit the other;
    * a charge levied against the wrong pool;
    * securities cash paying a derivatives charge;
    * a charge with no cash row at all.

    **All four clauses were once unreachable for a derivatives charge**, and
    four validation scenarios found it independently. ``drain_deposit`` built
    derivatives cash rows from ``DepositEntry``, which carries no
    ``charge_kind`` and no ``fill_id``, so the join below matched nothing,
    ever; ``_on_levy`` never wrote ``detail['pool']``, so the third clause
    could not fire; and a run with no transfers left the first vacuous. This
    identity reported ``passed`` on derivatives runs having evaluated zero of
    its clauses -- and deliberately relabelling three derivatives charges onto
    the securities pool did not move it. Both journal gaps are now closed;
    the fourth clause is new, and exists because an *unmatched* charge used to
    be indistinguishable from a correctly matched one: the loop body simply
    did not execute.
    """
    breaches: List[Dict[str, Any]] = []
    transfers: Dict[Any, Decimal] = {}
    for entry in logs.cash:
        if entry.movement in (CashMovement.TRANSFER_IN,
                              CashMovement.TRANSFER_OUT):
            transfers[entry.ts] = transfers.get(entry.ts, _ZERO) + entry.amount
    for ts, net in transfers.items():
        if net != _ZERO:
            breaches.append({'what': 'unmatched transfer', 'ts': ts.isoformat(),
                             'net': net})
    # ``session.charges()`` is the session's whole life; ``logs`` is one run.
    # A session driven through two ``run_scenario`` calls carries the first
    # run's charges into the second run's check, and they have no row in the
    # second run's log for a reason that is scoping, not segregation -- the
    # same artefact ``order_lifecycle`` and ``holdings_conservation`` already
    # report on a chained pair. ``charge_baseline`` is an index and not a
    # timestamp because a measured chained run had a run-1 charge at exactly
    # the run-2 opening row's instant, where any ts window is ambiguous.
    for charge in session.charges()[logs.charge_baseline:]:
        if not charge.total:
            continue      # a levy of nothing moves no cash and logs no row
        rows = [e for e in logs.cash
                if e.charge_kind == charge.kind and e.fill_id == charge.fill_id
                and e.ts == charge.ts]
        if not rows:
            breaches.append({'what': 'charge with no cash row',
                             'kind': charge.kind,
                             'fill_id': charge.fill_id,
                             'pool': charge.pool.value,
                             'ts': charge.ts.isoformat()})
            continue
        for row in rows:
            if row.pool != charge.pool.value:
                breaches.append({'what': 'charge logged against the wrong pool',
                                 'kind': charge.kind, 'charge_pool':
                                 charge.pool.value, 'logged_pool': row.pool})
    for entry in logs.cash:
        if (entry.movement is CashMovement.CHARGE_DEBITED
                and entry.detail.get('pool') is not None
                and entry.detail['pool'] != entry.pool):
            breaches.append({'what': f'{entry.detail["pool"]} charge paid from '
                                     f'{entry.pool} cash', 'seq': entry.seq,
                             'kind': entry.charge_kind})
    return IdentityResult(
        name='deposit_segregation', passed=not breaches,
        detail='transfers net to zero across the two pools, and every charge '
               'is debited from the pool it belongs to',
        breaches=tuple(breaches))


# --------------------------------------------------------------------------
# 9. Settlement completeness
# --------------------------------------------------------------------------

def settlement_completeness(logs: RunLogs, now: Any = None) -> IdentityResult:
    """Every tranche due inside the run settled, and none settled early.

    **This identity did not exist**, and two validation scenarios showed what
    that cost. One sold 1,000 HPG on 2022-02-14 with the tranche promised for
    2022-02-17 and stopped the run on 2022-02-15: 46,072,026d created as an
    obligation, never delivered, and the audit reported *nine of nine held*.
    Another carried a futures position past its last trading day with margin
    still posted and 2,500,000d owed, and every identity passed.

    Two clauses, and both directions matter:

    * **Due and undelivered.** A tranche whose ``settles_at`` is at or before
      the run's last observed instant and which never settled. Tranches due
      *after* the window are correct and are not reported -- the run simply
      ended first.
    * **Delivered early.** ``settled_at < settles_at`` is money made spendable
      before DVP, which is the direction that flatters a backtest.

    ``now`` is the run's last instant. Passed explicitly rather than read off
    the session so this can be checked against a merged log.
    """
    breaches: List[Dict[str, Any]] = []
    outstanding = logs.settlement.unsettled_at_end()
    for row in outstanding:
        if row.settles_at is None:
            continue        # no promised instant: nothing to be late against
        if now is not None and row.settles_at > now:
            continue        # due after the run ended, correctly still open
        breaches.append({'what': 'tranche due and never settled',
                         'seq': row.seq, 'leg': row.leg, 'ticker': row.ticker,
                         'quantity': row.quantity, 'amount': row.amount,
                         'settles_at': row.settles_at.isoformat()})
    for row in logs.settlement.of(SettlementAction.TRANCHE_SETTLED):
        if (row.settles_at is not None and row.settled_at is not None
                and row.settled_at < row.settles_at):
            breaches.append({'what': 'tranche settled before its DVP instant',
                             'seq': row.seq, 'leg': row.leg,
                             'ticker': row.ticker,
                             'settles_at': row.settles_at.isoformat(),
                             'settled_at': row.settled_at.isoformat()})
    return IdentityResult(
        name='settlement_completeness', passed=not breaches,
        detail='every tranche due inside the run was delivered, and none was '
               'delivered before its settlement instant',
        breaches=tuple(breaches))


# --------------------------------------------------------------------------
# The whole suite
# --------------------------------------------------------------------------

def check_identities(session: Any, logs: RunLogs, snapshots: Sequence[Any],
                     *, opening_holdings: Mapping[str, int] = (),
                     tickers: Sequence[str] = ()) -> Tuple[IdentityResult, ...]:
    """Run every identity and return the results, failures included.

    Never raises on a failure: a scenario collects the results and asserts on
    them, so one broken identity cannot mask another.
    """
    opening = dict(opening_holdings or {})
    watched = tuple(dict.fromkeys(list(tickers) + list(opening)))
    return (
        cash_conservation(logs.cash, SECURITIES,
                          session.cash().settled_balance),
        cash_conservation(logs.cash, DERIVATIVES,
                          session.margin().deposit_balance),
        deposit_balance_trail(session),
        encumbrance_matches(session, watched),
        encumbrance_zero(session, watched),
        holdings_conservation(session, logs, opening, watched),
        no_negative_settled(snapshots),
        order_lifecycle(session, logs),
        deposit_segregation(session, logs),
        settlement_completeness(logs, session.now()),
    )
