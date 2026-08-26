"""Recording seam: where the cash and settlement logs actually come from.

**Why this module exists is a finding, not a design preference.**
``ExchangeSession`` has no cash journal on the securities side.
``CashLedger.debit`` and ``.credit`` take ``ts`` and ``reason`` on every call
and discard both -- their own docstring says the pair is "carried for the
caller's own journal" and that the ledger "itemises charges and nothing else,
because design section 3 puts all reporting on the caller's side". The
derivatives pool is the opposite: ``DerivativesAccount`` keeps
``DepositEntry(ts, amount, reason, balance_after)`` for every movement,
deliberately, because a ``ForcedLiquidation`` event has to state the resulting
balance.

So one pool ships an auditable cash journal and the other does not, and a
caller who wants the second one has to record it. This module records it, at
the call site, by wrapping the ledger methods on **one session instance**.

What that buys, and what it costs:

* every row is the movement itself, not a balance difference, so a cash log
  built here cannot silently attribute two movements to one cause;
* the reason string is the module's own words, verbatim, so the *why* is the
  session's and not ours;
* it is instance-level and reversible (:meth:`LedgerJournal.detach`), so
  nothing outside the attached session changes;
* but it is **coupled to five private method names** on two ledger classes. If
  ``ledgers.py`` grows a sixth way to move cash, the conservation identity in
  :mod:`validation.identities` fails rather than the log going quietly wrong.
  That failure mode is the point: the check is what makes the coupling safe.

Nothing here changes a balance. ``tests/validation/test_journal.py`` proves it
by running the same scenario twice, once with the journal attached and once
without, and comparing every reported figure.

**What it does not record**, stated so a scenario does not assume otherwise:

* **The share creation** of ``HoldingsLedger.apply_corporate_action``. The
  corporate-action engine is not wired into ``advance_to`` by design, so a run
  only crosses an ex-date if the scenario applies one itself -- and then the
  quantity change has no *cash-log* row and ``holdings_conservation`` will
  report it. That is the honest outcome: the identity is genuinely broken by
  an event no fill produced.

  The **tranche rescale** is now recorded, as ``TRANCHE_ADJUSTED``. It used to
  be silent, and that was a defect rather than a declared gap: the settlement
  log's key includes the quantity, so a parcel rescaled 1,500 -> 2,025 in
  place produced a creation row that never settled and a settlement row that
  was never created. ``settlement_completeness`` reported the orphan.
* Charges that are never levied. Custody, VSDC position management and the
  derivatives transfer tax at maturity all have dated rows and no call site,
  so they never move cash and cannot appear in a cash log built from
  movements.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, List, Optional, Tuple

from plutus.market.protocol import InstrumentKind
from plutus.market.session.types import Pool

from validation.logs import (
    CashLog, CashLogEntry, CashMovement, SettlementAction, SettlementLog,
    SettlementLogEntry,
)

__all__ = ['LedgerJournal', 'classify_reason', 'SECURITIES', 'DERIVATIVES']

_ZERO = Decimal('0')

SECURITIES = Pool.SECURITIES.value
DERIVATIVES = Pool.DERIVATIVES.value


#: Reason-string prefix -> cause, for the reasons the session actually passes.
#:
#: These are ``ledgers.py``'s and ``deposit.py``'s own words, matched on a
#: prefix so a reason that carries a ticker or a fill id still classifies.
#: Anything unmatched lands on ``OTHER_CREDIT`` / ``OTHER_DEBIT`` with the raw
#: string preserved -- classification is a convenience, the verbatim reason is
#: the record.
_REASONS: Tuple[Tuple[str, CashMovement], ...] = (
    ('buy ', CashMovement.BUY_CONSIDERATION),
    ('transfer to the derivatives deposit', CashMovement.TRANSFER_OUT),
    ('transfer from the derivatives deposit', CashMovement.TRANSFER_IN),
    ('transfer in from securities', CashMovement.TRANSFER_IN),
    ('transfer out to securities', CashMovement.TRANSFER_OUT),
    ('opening deposit', CashMovement.OPENING_BALANCE),
    ('realised close-out', CashMovement.REALISED_PNL),
    ('final settlement of', CashMovement.EXPIRY_SETTLEMENT),
    ('charges on', CashMovement.CHARGE_DEBITED),
)


def classify_reason(reason: str, amount: Decimal) -> CashMovement:
    """Map a ledger reason string onto a :class:`CashMovement`.

    Falls back to ``OTHER_CREDIT`` / ``OTHER_DEBIT`` by sign. It never guesses
    a specific cause: an unrecognised reason is reported as unrecognised.
    """
    lowered = (reason or '').lower()
    for prefix, movement in _REASONS:
        if lowered.startswith(prefix):
            return movement
    return (CashMovement.OTHER_CREDIT if amount >= 0
            else CashMovement.OTHER_DEBIT)


@dataclass
class _Wrapped:
    """One replaced instance method, kept so :meth:`detach` can restore it."""

    owner: Any
    name: str
    original: Callable[..., Any]


class LedgerJournal:
    """Records every cash and settlement movement of one session.

    Attach before the run, drain after. The journal writes straight into the
    :class:`~validation.logs.CashLog` and
    :class:`~validation.logs.SettlementLog` it is given, sharing the runner's
    sequence counter so cash, settlement and trade rows interleave in one
    total order.

    The securities pool is recorded by wrapping ledger methods; the
    derivatives pool is *read* from ``DerivativesAccount.entries``, which is
    already an audit trail, and is drained by :meth:`drain_deposit`. The two
    halves are deliberately different because the simulator is.
    """

    def __init__(self, session: Any, cash: CashLog, settlement: SettlementLog,
                 next_seq: Callable[[], int]) -> None:
        self._session = session
        self._cash = cash
        self._settlement = settlement
        self._next_seq = next_seq
        self._wrapped: List[_Wrapped] = []
        self._in_levy = False
        self._deposit_cursor = 0
        self._attached = False
        #: Charges the session had levied before this journal attached. Set by
        #: :meth:`record_opening`; copied onto ``RunLogs.charge_baseline``.
        self.charge_baseline = 0
        self._seen_advances: set = set()
        self._repaid_advances: set = set()

    # -- lifecycle ------------------------------------------------------

    def attach(self) -> 'LedgerJournal':
        """Replace the recorded methods on this session's two ledgers."""
        if self._attached:
            raise RuntimeError('journal already attached')
        cash_ledger = self._session._securities.cash_ledger
        holdings = self._session._securities.holdings_ledger

        self._wrap(cash_ledger, 'debit', self._on_debit)
        self._wrap(cash_ledger, 'credit', self._on_credit)
        self._wrap(cash_ledger, 'levy', self._on_levy)
        self._wrap(cash_ledger, 'credit_pending', self._on_credit_pending)
        self._wrap(cash_ledger, 'settle_due', self._on_cash_settle_due)
        self._wrap(cash_ledger, 'accrue_interest', self._on_accrue_interest)
        self._wrap(cash_ledger, 'request_advance', self._on_request_advance)
        self._wrap(holdings, 'credit_unsettled', self._on_credit_unsettled)
        self._wrap(holdings, 'settle_due_by_ticker', self._on_holdings_settle)
        self._wrap(holdings, 'apply_corporate_action',
                   self._on_corporate_action)

        self._attached = True
        self.record_opening()
        return self

    def detach(self) -> None:
        """Restore every wrapped method. Idempotent."""
        for entry in reversed(self._wrapped):
            try:
                delattr(entry.owner, entry.name)
            except AttributeError:  # pragma: no cover - defensive
                setattr(entry.owner, entry.name, entry.original)
        self._wrapped.clear()
        self._attached = False

    def __enter__(self) -> 'LedgerJournal':
        return self.attach()

    def __exit__(self, *exc: Any) -> None:
        self.drain_deposit()
        self.detach()

    def _wrap(self, owner: Any, name: str,
              replacement: Callable[..., Any]) -> None:
        original = getattr(owner, name)
        self._wrapped.append(_Wrapped(owner, name, original))
        setattr(owner, name, _bind(original, replacement))

    # -- opening balances -----------------------------------------------

    def record_opening(self) -> None:
        """Two ``OPENING_BALANCE`` rows, one per pool.

        A cash log that starts at the first movement cannot be reconciled
        without a separately supplied opening figure, so the opening figure is
        a row.
        """
        ts = self._session.now()
        # Everything the session had already levied belongs to an earlier run,
        # not to this log. See ``RunLogs.charge_baseline``.
        self.charge_baseline = len(self._session.charges())
        cash = self._session.cash()
        self._emit_cash(CashLogEntry(
            seq=self._next_seq(), ts=ts, pool=SECURITIES,
            movement=CashMovement.OPENING_BALANCE,
            amount=cash.settled_balance,
            cause='opening securities cash, from AccountsConfig.initial_cash',
            balance_after=cash.settled_balance))
        balance = self._session.margin().deposit_balance
        self._emit_cash(CashLogEntry(
            seq=self._next_seq(), ts=ts, pool=DERIVATIVES,
            movement=CashMovement.OPENING_BALANCE, amount=balance,
            cause='opening derivatives deposit, from '
                  'AccountsConfig.initial_deposit',
            balance_after=balance))
        # The account's own opening entry is now represented; skip it.
        self._deposit_cursor = len(self._session._derivatives.entries)

    # -- the securities pool: recorded at the call site -------------------

    def _settled(self) -> Decimal:
        return self._session._securities.cash_ledger.cash().settled_balance

    def _interest_accrued_total(self) -> Decimal:
        """Advance interest the ledger has recognised so far, in total."""
        return Decimal(
            self._session._securities.cash_ledger.cash().interest_accrued)

    def _on_debit(self, original: Callable[..., Any], amount: Decimal,
                  ts: datetime, reason: str) -> Any:
        result = original(amount, ts, reason)
        if self._in_levy:
            return result                      # the charge row already has it
        self._emit_cash(CashLogEntry(
            seq=self._next_seq(), ts=ts, pool=SECURITIES,
            movement=classify_reason(reason, -Decimal(amount)),
            amount=-Decimal(amount), cause=reason,
            balance_after=self._settled()))
        return result

    def _on_credit(self, original: Callable[..., Any], amount: Decimal,
                   ts: datetime, reason: str) -> Any:
        result = original(amount, ts, reason)
        self._emit_cash(CashLogEntry(
            seq=self._next_seq(), ts=ts, pool=SECURITIES,
            movement=classify_reason(reason, Decimal(amount)),
            amount=Decimal(amount), cause=reason,
            balance_after=self._settled()))
        return result

    def _on_levy(self, original: Callable[..., Any], charge: Any,
                 *, debit: bool = True) -> Any:
        self._in_levy = True
        try:
            result = original(charge, debit=debit)
        finally:
            self._in_levy = False
        movement = (CashMovement.CHARGE_DEBITED if debit
                    else CashMovement.CHARGE_WITHHELD)
        cause = (f'{charge.kind} levied by {charge.levied_by.value} on '
                 f'{charge.base.value} of {charge.base_value}')
        if not debit:
            cause += ' -- withheld at source out of the sale proceeds'
        self._emit_cash(CashLogEntry(
            seq=self._next_seq(), ts=charge.ts, pool=SECURITIES,
            movement=movement, amount=-charge.total, cause=cause,
            affects_balance=bool(debit),
            balance_after=self._settled() if debit else None,
            order_id=charge.order_id, fill_id=charge.fill_id,
            ticker=charge.ticker, charge_kind=charge.kind,
            charge_base=charge.base.value, charge_base_value=charge.base_value,
            vat=charge.vat,
            # ``pool`` is the pool the CHARGE belongs to, which is not always
            # the pool of the row it lands on -- that mismatch is exactly what
            # ``identities.deposit_segregation``'s third clause looks for. It
            # read ``detail['pool']`` and nothing ever wrote the key, so the
            # clause was structurally unreachable.
            detail={'venue': charge.venue.value, 'pool': charge.pool.value}))
        return result

    def _on_credit_pending(self, original: Callable[..., Any],
                           amount: Decimal, settles_at: datetime,
                           ts: datetime, order_id: Optional[str] = None) -> Any:
        tranche = original(amount, settles_at, ts, order_id)
        self._emit_cash(CashLogEntry(
            seq=self._next_seq(), ts=ts, pool=SECURITIES,
            movement=CashMovement.SALE_PROCEEDS_PENDING,
            amount=Decimal(amount),
            cause='sale proceeds, net of charges withheld at source, pending '
                  f'until {settles_at.isoformat()}',
            affects_balance=False, order_id=order_id, settles_at=settles_at))
        self._emit_settlement(SettlementLogEntry(
            seq=self._next_seq(), ts=ts,
            action=SettlementAction.TRANCHE_CREATED, leg='cash',
            pool=SECURITIES, amount=Decimal(amount), settles_at=settles_at,
            order_id=order_id,
            settlement_rule=self._settlement_label(ts),
            settlement_calendar_id=self._calendar_id(),
            reason='a sell filled; the cash leg pends to the DVP instant'))
        self._sync_advances()
        return tranche

    def _on_cash_settle_due(self, original: Callable[..., Any],
                            now: datetime) -> Any:
        balance = self._settled()
        # ``CashLedger._repay`` tops the advance up to its final interest at
        # the settlement instant and writes straight to ``_interest_accrued``,
        # bypassing ``accrue_interest`` and therefore this journal's wrapper.
        # On a clock coarser than one day that top-up is the *whole* charge,
        # and the cash log then reported the financing cost of a financed run
        # as **zero** while the ledger carried 143,503.39146. The runner's
        # two-steps-per-day loop keeps the watermark within a day of every
        # settlement, which is why no shipped arm and no green test saw it;
        # any weekly or event-driven clock does.
        interest_before = self._interest_accrued_total()
        settled = original(now)
        top_up = self._interest_accrued_total() - interest_before
        if top_up:
            self._emit_cash(CashLogEntry(
                seq=self._next_seq(), ts=now, pool=SECURITIES,
                movement=CashMovement.ADVANCE_INTEREST_ACCRUED,
                amount=-top_up,
                cause='interest accrued on an outstanding sale advance, '
                      'trued up at the settlement instant. REPORTED, NEVER '
                      'CHARGED: no code path in the session debits it',
                affects_balance=False))
        for tranche in settled:
            balance += tranche.amount
            self._emit_cash(CashLogEntry(
                seq=self._next_seq(), ts=now, pool=SECURITIES,
                movement=CashMovement.SETTLEMENT_CREDIT,
                amount=tranche.amount,
                cause=f'proceeds tranche promised for '
                      f'{tranche.settles_at.isoformat()} settled',
                balance_after=balance, order_id=tranche.source_order_id,
                settles_at=tranche.settles_at))
            self._emit_settlement(SettlementLogEntry(
                seq=self._next_seq(), ts=now,
                action=SettlementAction.TRANCHE_SETTLED, leg='cash',
                pool=SECURITIES, amount=tranche.amount,
                settles_at=tranche.settles_at, settled_at=now,
                order_id=tranche.source_order_id,
                settlement_rule=self._settlement_label(now),
                settlement_calendar_id=self._calendar_id(),
                detail={'advanced': tranche.advanced,
                        'interest_accrued': tranche.interest_accrued},
                reason='DVP: the cash leg allocated to the client'))
        if settled:
            self._sync_advances()
        return settled

    def _on_accrue_interest(self, original: Callable[..., Any],
                            now: datetime) -> Any:
        accrued = original(now)
        if accrued:
            self._emit_cash(CashLogEntry(
                seq=self._next_seq(), ts=now, pool=SECURITIES,
                movement=CashMovement.ADVANCE_INTEREST_ACCRUED,
                amount=-Decimal(accrued),
                cause='interest accrued on an outstanding sale advance. '
                      'REPORTED, NEVER CHARGED: no code path in the session '
                      'debits it',
                affects_balance=False))
        return accrued

    def _on_request_advance(self, original: Callable[..., Any], ts: datetime,
                            amount: Optional[Decimal] = None,
                            **kwargs: Any) -> Any:
        drawn = original(ts, amount, **kwargs)
        self._sync_advances()
        return drawn

    def _sync_advances(self) -> None:
        """Log any advance drawn or repaid since the last check.

        Diffed rather than recorded at one call site, because a draw does not
        only happen at ``request_advance``: with
        ``AdvanceTerms.auto_register`` on -- the default, and the broker
        practice the terms describe -- the whole tranche is advanced inside
        ``credit_pending`` the moment the sale fills, through a private path.
        A journal wrapping only the public method would miss every automatic
        draw, which is most of them.
        """
        ledger = self._session._securities.cash_ledger
        for advance in ledger.advances(include_repaid=True):
            if advance.advance_id not in self._seen_advances:
                self._seen_advances.add(advance.advance_id)
                self._emit_cash(CashLogEntry(
                    seq=self._next_seq(), ts=advance.taken_at, pool=SECURITIES,
                    movement=CashMovement.ADVANCE_DRAWN,
                    amount=advance.amount,
                    cause='sale advance (ung truoc tien ban) drawn against '
                          'unsettled proceeds; raises Cash.available through '
                          '`advanced`, not the settled balance',
                    affects_balance=False, settles_at=advance.settles_at,
                    order_id=advance.source_order_id,
                    detail={'advance_id': advance.advance_id}))
            if (advance.repaid_at is not None
                    and advance.advance_id not in self._repaid_advances):
                self._repaid_advances.add(advance.advance_id)
                self._emit_cash(CashLogEntry(
                    seq=self._next_seq(), ts=advance.repaid_at,
                    pool=SECURITIES, movement=CashMovement.ADVANCE_REPAID,
                    amount=-advance.amount,
                    cause='advance principal recovered out of the T+2 '
                          'settlement; the settlement credit is gross, so '
                          'this does not move the settled balance again. '
                          f'interest of {advance.interest_accrued} was '
                          'accrued and NEVER CHARGED',
                    affects_balance=False, settles_at=advance.settles_at,
                    order_id=advance.source_order_id,
                    detail={'advance_id': advance.advance_id,
                            'interest_accrued': advance.interest_accrued,
                            'days_accrued': advance.days_accrued}))

    def _on_credit_unsettled(self, original: Callable[..., Any], ticker: str,
                             quantity: int, settles_at: datetime,
                             ts: datetime,
                             order_id: Optional[str] = None) -> Any:
        tranche = original(ticker, quantity, settles_at, ts, order_id)
        self._emit_settlement(SettlementLogEntry(
            seq=self._next_seq(), ts=ts,
            action=SettlementAction.TRANCHE_CREATED, leg='securities',
            pool=SECURITIES, ticker=ticker, quantity=quantity,
            settles_at=settles_at, order_id=order_id,
            settlement_rule=self._settlement_label(ts),
            settlement_calendar_id=self._calendar_id(),
            reason='a buy filled; the shares are not deliverable until the '
                   'DVP instant'))
        return tranche

    def _on_holdings_settle(self, original: Callable[..., Any],
                            now: datetime) -> Any:
        moved = original(now)
        for ticker, tranche in moved:
            self._emit_settlement(SettlementLogEntry(
                seq=self._next_seq(), ts=now,
                action=SettlementAction.TRANCHE_SETTLED, leg='securities',
                pool=SECURITIES, ticker=ticker, quantity=tranche.quantity,
                settles_at=tranche.settles_at, settled_at=now,
                order_id=tranche.source_order_id,
                settlement_rule=self._settlement_label(now),
                settlement_calendar_id=self._calendar_id(),
                reason='DVP: the securities leg allocated to the client'))
        return moved

    def _on_corporate_action(self, original: Callable[..., Any],
                             ticker: str, factor: Decimal,
                             cash_per_share: Decimal, ts: datetime) -> Any:
        """Record a tranche rescaled in place by a corporate action.

        ``HoldingsLedger.apply_corporate_action`` scales every open parcel and
        **preserves each one's ``settles_at``**, which is the right
        behaviour -- a bonus issue does not move the settlement instant. But
        it changes the quantity, and the settlement log's economic key
        includes the quantity, so without this row the log said a tranche of
        1,500 was created and never settled and a tranche of 2,025 settled
        having never been created: one orphan and one ghost, on a run the
        scenario calls correct.

        The row carries the post-event quantity, so it joins forward to the
        settlement, and ``quantity_before`` in ``detail``, so it joins back to
        the creation. It moves no money and asserts no new rule.
        """
        ledger = self._session._securities.holdings_ledger
        before = [t.quantity for t in ledger.holding(ticker).unsettled]
        cash_leg, scaled = original(ticker, factor, cash_per_share, ts)
        for index, tranche in enumerate(scaled):
            was = before[index] if index < len(before) else None
            if was == tranche.quantity:
                continue          # factor 1: a pure cash dividend moved none
            self._emit_settlement(SettlementLogEntry(
                seq=self._next_seq(), ts=ts,
                action=SettlementAction.TRANCHE_ADJUSTED, leg='securities',
                pool=SECURITIES, ticker=ticker, quantity=tranche.quantity,
                settles_at=tranche.settles_at, settled_at=None,
                order_id=tranche.source_order_id,
                settlement_rule=self._settlement_label(ts),
                settlement_calendar_id=self._calendar_id(),
                detail={'quantity_before': was, 'factor': factor},
                reason=f'corporate action rescaled an unsettled parcel by '
                       f'{factor}; the settlement instant is unchanged'))
        return cash_leg, scaled

    # -- the derivatives pool: read from the account's own trail ----------

    def drain_deposit(self) -> Tuple[CashLogEntry, ...]:
        """Copy any new ``DepositEntry`` rows into the cash log.

        Called once per step by the runner. The deposit already keeps
        ``(ts, amount, reason, balance_after)`` for every movement, so nothing
        here is reconstructed -- this only moves rows across, classifies the
        reason, and **re-attaches the charge itemisation**.

        Why the itemisation has to be re-attached here. ``DepositEntry``
        carries only ``(ts, amount, reason, balance_after)``: no
        ``charge_kind``, no ``fill_id``, no ``ticker``. The securities path
        (:meth:`_on_levy`) wraps ``CashLedger.levy``, which takes a whole
        ``Charge``, so it writes all of them. The two halves of the cash log
        therefore disagreed about whether a fee is joinable, and four
        validation scenarios independently found the consequence:
        ``identities.deposit_segregation`` joins ``session.charges()`` to cash
        rows on ``charge_kind`` **and** ``fill_id``, so **it matched nothing,
        ever, for a derivatives charge**. It passed on every derivatives run
        having examined zero of them. Deliberately relabelling three
        derivatives charges onto the securities pool did not move it.

        The join is on ``(ts, total)`` against the session's own charge list,
        consumed one-for-one so two equal charges at one instant map to two
        rows rather than both to the first. A charge that does not match is
        left as it was -- this adds metadata and never invents it.
        """
        entries = self._session._derivatives.entries
        new = entries[self._deposit_cursor:]
        self._deposit_cursor = len(entries)

        # (ts, amount) -> the derivatives charges levied at that instant, in
        # order. ``_debit_charges`` debits once per charge, so the row and the
        # charge are one-to-one; ``pop(0)`` keeps them that way.
        pending: Dict[Any, List[Any]] = {}
        for charge in self._session.charges():
            if getattr(charge.pool, 'value', charge.pool) != DERIVATIVES:
                continue
            if not charge.total:
                continue          # zero-amount charges move no cash and log none
            pending.setdefault((charge.ts, charge.total), []).append(charge)

        out: List[CashLogEntry] = []
        for entry in new:
            movement = classify_reason(entry.reason, entry.amount)
            extra: Dict[str, Any] = {}
            if movement is CashMovement.CHARGE_DEBITED:
                bucket = pending.get((entry.ts, -entry.amount))
                if bucket:
                    charge = bucket.pop(0)
                    extra = {
                        'order_id': charge.order_id,
                        'fill_id': charge.fill_id,
                        'ticker': charge.ticker,
                        'charge_kind': charge.kind,
                        'charge_base': charge.base.value,
                        'charge_base_value': charge.base_value,
                        'vat': charge.vat,
                        'detail': {'venue': charge.venue.value,
                                   'pool': charge.pool.value},
                    }
            row = CashLogEntry(
                seq=self._next_seq(), ts=entry.ts, pool=DERIVATIVES,
                movement=movement,
                amount=entry.amount, cause=entry.reason,
                balance_after=entry.balance_after, **extra)
            out.append(self._emit_cash(row))
        return tuple(out)

    # -- settlement-rule provenance --------------------------------------

    def _settlement_label(self, ts: datetime) -> Optional[str]:
        """The dated settlement regime governing an equity tranche at ``ts``.

        Returns ``None`` rather than a guess if the rulebook cannot resolve
        one. The label distinguishes the pre-2022-08-29 next-session-open
        regime from T+2 at 13:00, which is the difference a settlement log
        exists to make visible.
        """
        try:
            rule = self._session._rulebook.at(ts).settlement_rule(
                InstrumentKind.STOCK)
        except Exception:                      # pragma: no cover - defensive
            return None
        return rule.label if rule is not None else None

    def _calendar_id(self) -> Optional[str]:
        return self._session.provenance().settlement_calendar_id

    # -- sinks ------------------------------------------------------------

    def _emit_cash(self, entry: CashLogEntry) -> CashLogEntry:
        return self._cash.append(entry)

    def _emit_settlement(self, entry: SettlementLogEntry) -> SettlementLogEntry:
        return self._settlement.append(entry)


def _bind(original: Callable[..., Any],
          replacement: Callable[..., Any]) -> Callable[..., Any]:
    """Return a callable with ``original``'s signature that calls ``replacement``.

    The bound method is passed through as the first argument so the recorder
    always calls the real implementation exactly once and can read the
    balance afterwards.
    """
    def call(*args: Any, **kwargs: Any) -> Any:
        return replacement(original, *args, **kwargs)
    call.__name__ = getattr(original, '__name__', 'wrapped')
    call.__doc__ = getattr(original, '__doc__', None)
    return call
