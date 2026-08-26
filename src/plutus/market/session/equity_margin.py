"""Equity margin lending, wired into :class:`~plutus.market.session.exchange.ExchangeSession`.

``margin_lending.py`` is the policy: QD 87's algebra, the two config objects,
the call/forced-sale state machine. It owns no ledger, no clock and no order
book, and its own docstring says so -- *"nothing imports it yet -- wiring is a
later stage"*. **This module is that stage**, and it is deliberately the only
place the two halves meet.

What it adds, and nothing else:

1. a **funding path for a margin buy**. ``SecuritiesAccount.reserve_for_buy``
   enforces 100 % pre-funding against ``Cash.available``, which is right for a
   cash account and makes a margin purchase unrepresentable. Here the broker
   disburses the loan into the securities cash ledger *before* the reservation
   runs, so the existing pre-funding check is left exactly as it is and a
   margin buy funds through it. The loan is then ``DB``;
2. the **end-of-day determination** QD 87 Dieu 6.1 requires -- once per date,
   at or after a stated instant -- feeding :class:`MarginCallMonitor`;
3. **execution** of the *ban giai chap*. The derivatives side reports a forced
   close and does not execute one (``exchange.py``'s ``detail['executed'] =
   False``). This side submits real sell orders through ``session.submit`` and
   they fill, or fail to fill, against the same market data as any other order.
   A liquidation into a locked market is therefore a thing this simulator can
   *fail to complete*, which is the point;
4. the **proceeds application**, on settlement.

Five decisions this module makes, all of them ours and all of them declared in
:data:`WIRING_PROVENANCE`:

``margin_order_flag``
    QD 87 Dieu 13.5(e) requires margin order tickets to be **distinguishable**
    from ordinary ones, and ``assess_margin_order``'s docstring reads that as
    "whatever wires this into ``orders.py`` must add a type". We add
    ``Order.on_margin`` -- a flag, not a type. A new ``OrderType`` member would
    have to be threaded through the transition graph, the per-type terminal
    edges, the time-in-force table and every fill policy, and the order *type*
    in this package already carries the time-in-force. The ticket is
    distinguishable and the trade log says so; it is not literally a distinct
    type, and that gap is recorded rather than papered over.

``determination_instant``
    Dieu 6.1 says *cuoi ngay giao dich* on a within-day timestamp agreed in
    writing, and names no time. We determine at the **first advance at or after
    ``determination_time`` on each date**, once per date. A second observation
    on the same date is skipped rather than absorbed, because
    ``RatioDetermination.END_OF_DAY`` on two observations of one day is a claim
    about a regime that was not run.

``sale_next_session``
    The ratio is determined after the close of T and the tickets are submitted
    at the **next session's open**, because there is no session left on T to
    submit into. Dieu 8 does not date the sale.

``proceeds_applied_on_settlement``
    A forced sale raises cash that settles T+2. Until the proceeds are applied
    to ``DB`` the ratio does not move at all -- ``PV`` falls and ``CB`` rises by
    the same amount, exactly as ``value_to_restore`` warns. We apply them when
    the tranche settles. Dieu 8 is SILENT on the timing, and the alternative
    (sweeping against the receivable on trade date) is a real broker practice;
    it is a constructor flag, not a hidden default.

``interest_accrual``
    Accrued only where ``BrokerMarginTerms.rate_schedule`` is non-empty. An
    empty schedule is "no rate has been agreed" (QD 87 Dieu 11.3 requires the
    rate in writing) and the engine refuses to invent one, exactly as the field
    documents. Accrual is a **DB** movement and not a cash movement: nothing is
    debited, and the ratio feels it through
    ``BrokerMarginTerms.accrued_charges_in_debt``.

Import boundary: this module may import ``margin_lending``, ``types``,
``protocol`` and ``ledgers``. It must **not** be imported by ``margin_lending``
-- that module's import fence (``Venue`` and ``Cash``, nothing else) is the
thing that keeps the policy replayable without a session.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal
from types import MappingProxyType
from typing import (Any, Callable, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

from plutus.core.constant import VietnamMarketConstant
from plutus.market.protocol import MarketState, Order, OrderType, Side
from plutus.market.session.margin_lending import (
    AccountingUnit, BrokerMarginTerms, BusinessDayCalendar, CollateralLot,
    CureContribution, ForcedSalePlan, ForcedSalePrice, ForcedSaleScope,
    LiquidationOrder, LoanStatus, MarginAccountAlgebra, MarginAccountState,
    MarginAccountStatus, MarginCall, MarginCallMonitor,
    MarginCollateralPosition, MarginEligibility,
    MarginEvent, MarginEventKind, MarginLoan, MarginOrderAssessment,
    MarginRegulation, ProceedsComponent, Provenance, SecurityEligibility,
    SourceGrade, apply_sale_proceeds, assess_margin_order, build_account_state,
    compute_account_algebra, order_initial_margin_ratio,
)
from plutus.market.session.types import (
    Event, EventKind, OrderId, Pool, Rejected, StatefulRule, Verdict,
)

__all__ = [
    'EquityMarginAccount', 'MarginDraw', 'WIRING_PROVENANCE',
    'EQUITY_MARGIN_EVENT_KIND', 'DEFAULT_DETERMINATION_TIME',
]

_ZERO = Decimal('0')
_ONE = Decimal('1')
_DONG = Decimal('1')

#: The instant the statutory end-of-day determination is taken at, unless the
#: caller states another. **Not sourced** -- QD 87 Dieu 6.1 names no time; see
#: ``determination_instant`` in :data:`WIRING_PROVENANCE`.
DEFAULT_DETERMINATION_TIME = time(14, 45)


def _p(article: Optional[str], grade: SourceGrade, note: str) -> Provenance:
    return Provenance(article=article, grade=grade, note=note)


_D = SourceGrade.DERIVED
_S = SourceGrade.SILENT


#: Everything this wiring decided that neither config object decides.
WIRING_PROVENANCE: Mapping[str, Provenance] = MappingProxyType({
    'margin_order_flag': _p('QD 87 Dieu 13.5(e)', _D,
        'The article requires a margin order ticket to be DISTINGUISHABLE from '
        'an ordinary one, client-confirmed, and an inseparable annex to the '
        'contract. We add Order.on_margin, a boolean, rather than an OrderType '
        'member: in this package the order TYPE carries the time-in-force and '
        'the per-type terminal edges, so a sixth "margin" type would have to '
        'answer questions about resting and expiry that have nothing to do '
        'with lending. The ticket is distinguishable and the trade log carries '
        'the flag. It is NOT literally a distinct type and this row is the '
        'declaration of that gap'),
    'determination_instant': _p('QD 87 Dieu 6.1', _S,
        'The article sets an end-of-trading-day determination on a within-day '
        'timestamp agreed IN WRITING with the client, and names no time. The '
        'wiring determines once per date, at the first advance at or after '
        'determination_time. A second observation on the same date is skipped, '
        'because two END_OF_DAY determinations in one day describe a regime '
        'nobody ran'),
    'sale_next_session': _p('QD 87 Dieu 8', _S,
        'The article gives the right and does not date the sale. The ratio is '
        'determined after the close of T, so the earliest session the tickets '
        'can reach is T+1. Reported on every instruction as issued_at'),
    'proceeds_applied_on_settlement': _p('QD 87 Dieu 8 / Dieu 12.2(i)', _S,
        'Dieu 8 gives the client the remainder after the debt is deducted and '
        'does not say when the deduction happens; Dieu 12.2(i) delegates the '
        'proceeds order to the contract. Vietnamese equity settles T+2, so a '
        'forced sale raises cash that is not there yet -- and until it is '
        'applied to DB the ratio does not move AT ALL, because PV falls and CB '
        'rises by the same amount. We apply on settlement. Set '
        'apply_proceeds_on_settlement=False for a firm that sweeps the '
        'receivable on trade date'),
    'no_double_sale': _p(None, _D,
        'While a forced-sale ticket is live, or its proceeds are sold and '
        'unsettled, no second sale is planned for the same account. Nothing '
        'sources this; the alternative is that the T+2 lag makes the machine '
        'sell the account three times over for one breach. A broker does not '
        'do that. The suppression is reported in the plan note'),
    'interest_accrual_cadence': _p('QD 87 Dieu 11.4', _S,
        'The article delegates the calculation method entirely. Accrual runs '
        'at the determination, over the calendar or business days elapsed '
        'since the previous determination, on the outstanding principal, at '
        'the rate_schedule tier for the loan age. An EMPTY rate_schedule means '
        'no rate was agreed and NOTHING accrues -- the engine refuses to '
        'invent a number'),
    'accrual_is_not_cash': _p(None, _D,
        'Accrued interest is a DB movement and not a cash movement: no debit '
        'is taken. It reaches the ratio only through '
        'BrokerMarginTerms.accrued_charges_in_debt, which is True by default. '
        'A firm that charges interest in cash monthly is a different model and '
        'is not implemented'),
    'session_event_mapping': _p(None, _D,
        'types.EventKind has three margin members and margin_lending has '
        'eighteen. Only the ladder-relevant ones reach the session cursor, '
        'under MARGIN_CALL / MARGIN_WARNING / FORCED_LIQUIDATION with '
        'pool=SECURITIES and detail["equity_margin_event"] naming the real '
        'kind. The full stream is EquityMarginAccount.events and is lossless. '
        'MarginEvent\'s own docstring says the two streams merge as new '
        'members; until they do, this mapping is lossy by construction'),
    'loan_sized_on_reserve_price': _p('QD 87 Dieu 2 khoan 8', _D,
        'khoan 8 values the order at market price AT TRADE TIME. A limit order '
        'has no trade price when it is funded, so the loan is disbursed on the '
        'reservation price (the limit, or the ceiling for a market-family '
        'order) and RECONCILED to the executed value once the order reaches a '
        'terminal state. An order that never fills repays its whole draw'),
})


#: Which session event kind an equity margin event surfaces under. Absent
#: members do not reach the session cursor at all; see
#: ``session_event_mapping`` in :data:`WIRING_PROVENANCE`.
EQUITY_MARGIN_EVENT_KIND: Mapping[MarginEventKind, EventKind] = MappingProxyType({
    MarginEventKind.CALL_ISSUED: EventKind.MARGIN_CALL,
    MarginEventKind.CALL_PARTIALLY_CURED: EventKind.MARGIN_CALL,
    MarginEventKind.CALL_EXPIRED: EventKind.MARGIN_CALL,
    MarginEventKind.CALL_CURED: EventKind.MARGIN_WARNING,
    MarginEventKind.FORCED_SALE_DUE: EventKind.FORCED_LIQUIDATION,
    MarginEventKind.FORCED_SALE_INSTRUCTED: EventKind.FORCED_LIQUIDATION,
    MarginEventKind.COLLATERAL_BECAME_INELIGIBLE: EventKind.MARGIN_WARNING,
    MarginEventKind.LENDING_SUSPENDED: EventKind.MARGIN_WARNING,
    MarginEventKind.LENDING_RESUMED: EventKind.MARGIN_WARNING,
    MarginEventKind.INDETERMINATE: EventKind.MARGIN_WARNING,
})


def _floor_dong(amount: Decimal) -> Decimal:
    """Round down to the dong. Vietnam has no sub-dong money."""
    return amount.quantize(_DONG, rounding=ROUND_FLOOR)


#: Thousands of dong per quoted unit, by venue -- ``charges.trade_value``'s
#: ``CURRENCY_UNIT``, restated here because this is the boundary where it bites.
#:
#: **The three cash venues quote in thousands of dong and ``margin_lending``
#: does not know that.** Every price in that module -- ``CollateralLot``'s three
#: prices, ``assess_margin_order``'s ``price``, ``MarginCollateralPosition``'s
#: ``price`` -- is an unlabelled ``Decimal``, while ``MarginAccountState.cash``
#: comes off a ledger denominated in dong. Handing an HSX quote of ``22.70``
#: straight through makes ``PV`` **one thousand times too small** against
#: ``CB``: an account that has borrowed 90 m dong and holds 181 m of stock
#: reports ``EB`` as 100,181,600 and a ratio of 0.0999 instead of 0.524 -- and
#: on the way down it reports the ratio *rising*, because the only term moving
#: is the one that is right. Nothing raises. This wiring converts at the
#: boundary, in :meth:`EquityMarginAccount._dong`, and a test pins it.
CURRENCY_UNIT: Mapping[str, Decimal] = MappingProxyType({
    venue: Decimal(unit)
    for venue, unit in VietnamMarketConstant.CURRENCY_UNIT.items()
})


@dataclass
class MarginDraw:
    """One margin order's disbursement, and what it was sized on.

    Mutable on purpose: :attr:`principal` is reconciled downward as the order's
    real fate becomes known, and the record is the audit trail of that.

    Attributes:
        order_id: the order this funded.
        loan_id: the :class:`MarginLoan` it created.
        ticker: what it bought.
        quantity: shares ordered.
        reserve_price: the price the loan was sized on -- the limit, or the
            ceiling for a ceiling-funded type. **Not a trade price**; see
            ``loan_sized_on_reserve_price`` in :data:`WIRING_PROVENANCE`.
        imr: the per-order *ty le ky quy ban dau* applied (khoan 8).
        disbursed: what was credited to the securities cash ledger at accept.
        principal: what is still owed on this draw. Falls on reconciliation and
            on a proceeds application.
        at: when it was disbursed.
        reconciled: whether the order has reached a terminal state and the
            undrawn remainder has been repaid.
    """

    order_id: OrderId
    loan_id: str
    ticker: str
    quantity: int
    reserve_price: Decimal
    imr: Decimal
    disbursed: Decimal
    principal: Decimal
    at: datetime
    reconciled: bool = False


class EquityMarginAccount:
    """One segregated margin account, joined to one :class:`ExchangeSession`.

    TT 120 Dieu 9.3 makes the margin account segregated per investor per CTCK,
    which is why this is an object with an ``account_id`` and not a set of
    functions on the session.

    **It does not decide anything.** Every threshold, every ordering, every
    clock is ``margin_lending``'s; this class supplies that policy with the
    ledger reads it cannot do for itself and turns its answers into session
    orders and session events. Where it had to choose, the choice is in
    :data:`WIRING_PROVENANCE` and nowhere else.
    """

    def __init__(
        self,
        *,
        account_id: str,
        terms: BrokerMarginTerms,
        calendar: BusinessDayCalendar,
        market_feed: Callable[[str, datetime], Optional[MarketState]],
        eligibility: Optional[Mapping[str, SecurityEligibility]] = None,
        regulation: Optional[MarginRegulation] = None,
        determination_time: time = DEFAULT_DETERMINATION_TIME,
        tickers: Sequence[str] = (),
        execute_forced_sale: bool = True,
        apply_proceeds_on_settlement: bool = True,
        sell_on_ineligible_collateral: bool = False,
        broker_ranking: Sequence[str] = (),
        is_foreign_investor: bool = False,
        margin_contract_signed: bool = True,
        holder_classes: Tuple[Any, ...] = (),
        lending_suspended: bool = False,
    ) -> None:
        """
        Args:
            account_id: the segregated margin account (TT 120 Dieu 9.3).
            terms: the firm's commercial terms. Constructing them already
                refused anything looser than the statutory floors.
            calendar: business days, for the cure deadline and the overdue
                clock. ``margin_lending`` refuses to own one and says why --
                *ngay lam viec* is not attributed to a body, and the VSDC and
                exchange calendars diverge around Tet by more than a whole cure
                window.
            market_feed: ``(ticker, ts) -> MarketState | None``. Read for
                ``last`` (the Dieu 2.4 valuation ceiling) and ``floor`` (*gia
                san*, for :attr:`ForcedSalePrice.FLOOR`). ``None`` makes the
                ticker unpriced, which makes the whole account INDETERMINATE --
                deliberately, per :class:`MarginAccountState`.
            eligibility: per-ticker :class:`SecurityEligibility`, **dated data
                the caller supplies**. A ticker with no entry is assessed as
                ``None``, which ``assess_margin_order`` treats as
                INDETERMINATE and refuses. Nothing here ships a list.
            regulation: the statutory row in force for the run. Defaults to
                ``terms.regulation``.
            determination_time: see ``determination_instant`` in
                :data:`WIRING_PROVENANCE`.
            tickers: securities already held at the start of the run, so the
                first valuation sees them. Tickers touched by a margin order
                are added automatically.
            execute_forced_sale: ``True`` submits the tickets.  ``False``
                plans and reports without submitting -- the derivatives side's
                posture, kept available so the two can be compared, and
                **not** the default.
            apply_proceeds_on_settlement: see
                ``proceeds_applied_on_settlement`` in
                :data:`WIRING_PROVENANCE`.
            sell_on_ineligible_collateral: forwarded to
                :class:`MarginCallMonitor`.
            broker_ranking: forwarded to :class:`MarginCallMonitor`.
            is_foreign_investor: TT 120 Dieu 9.2 bars *ky quy* outright. Read
                the warning on
                :attr:`MarginRegulation.foreign_investors_allowed` before
                reading this as "may not buy on credit".
            margin_contract_signed: TT 120 Dieu 9.1 -- the *hop dong giao dich
                ky quy* IS the credit agreement.
            holder_classes: QD 87 Dieu 13.4 categories.
            lending_suspended: TT 120 Dieu 9.9 / 9.7.
        """
        if terms.accounting_unit is not AccountingUnit.ACCOUNT:
            raise ValueError(
                f'accounting_unit is {terms.accounting_unit.value}. This '
                f'wiring runs one monitor over one segregated account, which '
                f'is the statutory unit (QD 87 Dieu 2 computes the ratio over '
                f'the account). DEAL granularity -- DNSE\'s per-deal ratio -- '
                f'needs one MarginCallMonitor and one loan per deal and is not '
                f'built; refusing here is better than running an account-level '
                f'ratio and labelling it per-deal')
        if terms.forced_sale_scope is ForcedSaleScope.BREACHING_POSITION:
            raise ValueError(
                'forced_sale_scope=BREACHING_POSITION is a per-deal shape and '
                'this wiring is per-account: no position here carries '
                'is_breaching, so the scope would select nothing and report an '
                'empty plan as if the account had no collateral')
        if terms.liquidation_order is LiquidationOrder.BREACHING_FIRST:
            raise ValueError(
                'liquidation_order=BREACHING_FIRST reads '
                'MarginCollateralPosition.is_breaching, which this wiring '
                'cannot establish at account granularity -- see '
                '_positions(). It would degenerate into an alphabetical sort, '
                'which is an ordering no contract chose')
        self.account_id = account_id
        self.terms = terms
        self.calendar = calendar
        self.regulation = regulation
        self.market_feed = market_feed
        self.eligibility: Dict[str, SecurityEligibility] = dict(eligibility or {})
        self.determination_time = determination_time
        self.execute_forced_sale = bool(execute_forced_sale)
        self.apply_proceeds_on_settlement = bool(apply_proceeds_on_settlement)
        self.is_foreign_investor = bool(is_foreign_investor)
        self.margin_contract_signed = bool(margin_contract_signed)
        self.holder_classes = tuple(holder_classes)
        self.lending_suspended = bool(lending_suspended)

        self.monitor = MarginCallMonitor(
            account_id, terms, calendar, regulation=regulation,
            broker_ranking=broker_ranking,
            sell_on_ineligible_collateral=sell_on_ineligible_collateral)
        self.policy = self.monitor.policy

        self._tickers: List[str] = list(dict.fromkeys(tickers))
        self._draws: Dict[OrderId, MarginDraw] = {}
        self._loans: Dict[str, MarginLoan] = {}
        self._events: List[MarginEvent] = []
        self._algebra: List[MarginAccountAlgebra] = []
        self._assessments: List[MarginOrderAssessment] = []
        self._plans: List[ForcedSalePlan] = []
        self._applications: List[Tuple[datetime, Any]] = []
        self._determined: Dict[date, datetime] = {}
        self._dates_seen: List[date] = []
        self._pending_plan: Optional[ForcedSalePlan] = None
        self._sale_orders: Dict[OrderId, Decimal] = {}
        self._awaiting_proceeds: Dict[OrderId, bool] = {}
        self._live_instructions: Dict[OrderId, str] = {}
        self._accrued_to: Optional[date] = None
        self._seq = 0

    # -- what a caller can read -------------------------------------------

    @property
    def events(self) -> Tuple[MarginEvent, ...]:
        """The **lossless** equity margin event stream, oldest first."""
        return tuple(self._events)

    @property
    def missed_determinations(self) -> Tuple[date, ...]:
        """Dates the account was advanced through and never graded on.

        **The one way this wiring can be silently inert.** The determination
        runs at the first advance at or after ``determination_time``; a caller
        whose loop never advances that far past the open -- the harness's
        ``close_time`` moved to 14:30, say -- gets an account that lends, never
        computes a ratio, never calls and never sells, with nothing raised and
        nothing logged. This property is the check, and it is a property rather
        than an exception because the account cannot know the run has ended.
        """
        return tuple(d for d in self._dates_seen if d not in self._determined)

    def events_by_kind(self, *kinds: MarginEventKind) -> Tuple[MarginEvent, ...]:
        """Every event of the given kinds, oldest first."""
        return tuple(e for e in self._events if e.kind in kinds)

    @property
    def determinations(self) -> Tuple[MarginAccountAlgebra, ...]:
        """One QD 87 Dieu 2 algebra per determined date, in order."""
        return tuple(self._algebra)

    @property
    def assessments(self) -> Tuple[MarginOrderAssessment, ...]:
        """Every pre-trade gate verdict, admitted or refused."""
        return tuple(self._assessments)

    @property
    def plans(self) -> Tuple[ForcedSalePlan, ...]:
        """Every *ban giai chap* plan raised."""
        return tuple(self._plans)

    @property
    def loans(self) -> Tuple[MarginLoan, ...]:
        """The loan book, in disbursement order."""
        return tuple(self._loans.values())

    @property
    def draws(self) -> Tuple[MarginDraw, ...]:
        """Every disbursement, with its reconciliation state."""
        return tuple(self._draws.values())

    @property
    def margin_debt(self) -> Decimal:
        """``DB`` -- outstanding principal across live loans."""
        return sum((loan.principal for loan in self._loans.values()
                    if loan.status in _LIVE), _ZERO)

    @property
    def accrued_interest(self) -> Decimal:
        return sum((loan.accrued_interest for loan in self._loans.values()
                    if loan.status in _LIVE), _ZERO)

    @property
    def forced_sale_orders(self) -> Tuple[OrderId, ...]:
        """Ids of every order this account submitted as a *ban giai chap*."""
        return tuple(self._sale_orders)

    @property
    def open_call(self) -> Optional[MarginCall]:
        """The outstanding *lenh goi ky quy bo sung*, or ``None``.

        ``PARTIALLY_CURED`` still appears here: QD 87 Dieu 8 treats a partial
        top-up exactly as a failure to top up for the force-sale right.
        """
        return self.monitor.open_call

    @property
    def last_status(self) -> Optional[MarginAccountStatus]:
        """The ladder rung of the last determination that could decide one."""
        return self.monitor.last_status

    @property
    def forced_sale_due(self) -> Optional[Any]:
        """The highest-priority live forced-sale trigger, or ``None``."""
        return self.monitor.forced_sale_due

    def calls(self) -> Tuple[MarginCall, ...]:
        """Every call issued, with its final status (QD 87 Dieu 13.8)."""
        return self.monitor.calls

    def cure(self, contribution: CureContribution) -> Tuple[MarginEvent, ...]:
        """Record a client answer to the open call. See
        :meth:`MarginCallMonitor.cure`.

        **This records the answer; it does not move money.** Depositing is
        :meth:`deposit_cash` and repaying is :meth:`repay`, and the split is
        deliberate: QD 87 Dieu 7 lets a client cure by depositing cash, posting
        collateral **or selling**, and only the first of those is a payment to
        the CTCK. An engine that repaid ``DB`` inside ``cure`` would move money
        for the two methods that do not.
        """
        news = self.monitor.cure(contribution)
        self._events.extend(news)
        return news

    def deposit_cash(self, session: Any, amount: Decimal,
                     ts: datetime) -> None:
        """The client pays money into the margin account.

        An **external inflow** -- the client's own money arriving from a bank.
        Nothing in this package models where it came from, and nothing should:
        a broker does not create a client's cash. It lands in ``CB`` like any
        other *tien* and raises ``EB`` and ``AB`` together, which is why cash
        left sitting in the account cures less than the same cash swept against
        the debt (:class:`TopUpRequirement`).
        """
        _require_positive('amount', amount)
        session.securities_cash_ledger().credit(
            amount, ts,
            f'client cash top-up into margin account {self.account_id}')

    def repay(self, session: Any, amount: Decimal, ts: datetime, *,
              reason: str = 'client repayment') -> Tuple[MarginEvent, ...]:
        """Pay down ``DB`` from settled cash. QD 87 Dieu 13.5(c).

        The article has the client paying interest on ``DB`` and permits a cash
        withdrawal only after every debt to the CTCK is cleared, so a voluntary
        repayment is the ordinary way out. **Which component it pays first is
        the firm's** ``proceeds_application_order`` -- Dieu 12.2(i) states that
        order for *sale* proceeds and says nothing about a voluntary payment,
        so reusing it is our choice and recorded as one rather than a second
        ordering appearing from nowhere.

        Raises:
            ValueError: for a non-positive amount, or one larger than
                ``Cash.available`` -- the ledger would refuse the debit anyway,
                and refusing here names the reason.
        """
        _require_positive('amount', amount)
        available = session.cash().available
        if amount > available:
            raise ValueError(
                f'a repayment of {amount} exceeds available cash {available}. '
                f'QD 87 Dieu 13.5(c) is about paying the CTCK out of the '
                f'client\'s own money; borrowing to repay a margin loan is not '
                f'a thing this account does')
        news = self._sweep(session, ts, amount, None, reason=reason)
        self._events.extend(news)
        return tuple(news)

    # -- the pre-trade gate, called from ExchangeSession.submit ------------

    def gate(self, session: Any, order: Order, order_id: OrderId,
             state: MarketState, ts: datetime,
             ) -> Any:
        """QD 87 Dieu 13.5(d), then disburse. Returns a
        :class:`MarginDraw` or :class:`Rejected`.

        The disbursement happens **here**, before the reservation, because
        ``SecuritiesAccount.reserve_for_buy`` tests ``Cash.available`` and the
        borrowed dong have to be in it. If the reservation then refuses for a
        reason this gate cannot see -- an absent ceiling, a live order already
        holding the cash -- the caller must call :meth:`unwind`.
        """
        if order.side is not Side.BUY:
            return Rejected(
                rule=StatefulRule.MARGIN_LENDING, binding_constraint=None,
                ts=ts, order_id=order_id,
                detail={'reason': 'a margin order is a purchase on credit; '
                                  'a SELL carries no lending and must not be '
                                  'flagged on_margin',
                        'article': 'QD 87 Dieu 2 khoan 8'})

        quoted = _reserve_price(order, state)
        reserve_price = self._dong(session, order.ticker, ts, quoted)
        if reserve_price is None:
            return Rejected(
                rule=StatefulRule.MARGIN_LENDING, binding_constraint=None,
                ts=ts, verdict=Verdict.INDETERMINATE, order_id=order_id,
                detail={'reason': 'no price to size the loan against: khoan 8 '
                                  'values the order at market price at trade '
                                  'time, and either no price is published here '
                                  '(a ceiling-funded type with no band) or the '
                                  'ticker\'s venue -- hence its currency unit '
                                  '-- could not be resolved',
                        'order_type': order.order_type.value,
                        'quoted_price': quoted,
                        'band_source': state.band_source.value})

        if order.ticker not in self._tickers:
            self._tickers.append(order.ticker)

        # -- The gate nets cash already promised to live buy orders, and the
        #    account-level ratio does not. Both are right.
        #
        #    khoan 5 defines CB as *tien*, and money reserved against an
        #    unfilled order is still the client's, so the ratio must not net
        #    it -- CashBase.cb does not. But assess_margin_order is a pure
        #    function of a snapshot and encumbers nothing: gate two orders
        #    against the same state and BOTH pass if either fits, which is the
        #    warning its own docstring gives. Netting here is the "commit each
        #    into the state you pass to the next" it asks for, and it is
        #    exactly what reserve_for_buy does with Cash.available.
        #
        #    Without it a second margin buy in one session is admitted by the
        #    lending gate and then refused by the cash reservation -- so the
        #    rejection log calls a credit refusal a funding refusal, the loan
        #    is disbursed and immediately unwound, and a run that counted
        #    refusals by reason would report the wrong one.
        cash = session.cash()
        account_state = replace(
            self.state_at(session, ts),
            cash=max(_ZERO, cash.settled_balance - cash.committed))
        assessment = assess_margin_order(
            account_state, self.terms, ticker=order.ticker,
            quantity=order.quantity, price=reserve_price, as_of=ts,
            security=self.eligibility.get(order.ticker),
            regulation=self.regulation)
        self._assessments.append(assessment)

        if not assessment.admitted:
            undecided = bool(assessment.indeterminate)
            return Rejected(
                rule=StatefulRule.MARGIN_LENDING,
                binding_constraint=assessment.excess_equity,
                ts=ts,
                # A rule saying no and the data not deciding stay countable
                # apart: assess_margin_order keeps refusals and indeterminates
                # in two tuples for exactly this reason.
                verdict=Verdict.INDETERMINATE if undecided else Verdict.REJECTED,
                order_id=order_id,
                detail={
                    'reason': '; '.join(
                        assessment.detail['reasons'].values()) or
                        'the margin gate refused this order',
                    'refusals': tuple(r.value for r in assessment.refusals),
                    'indeterminate':
                        tuple(r.value for r in assessment.indeterminate),
                    'order_value': assessment.order_value,
                    'required_margin': assessment.required_margin,
                    'excess_equity': assessment.excess_equity,
                    'buying_power': assessment.buying_power,
                    'margin_ratio': assessment.detail['margin_ratio'],
                    'account_status': assessment.detail['account_status'],
                    'article': 'QD 87 Dieu 13.5(d)',
                    'basis': 'CB net of cash committed to live buy orders. '
                             'khoan 5 does not net it and the account-level '
                             'ratio does not either; the GATE does, so two '
                             'orders in one session cannot both spend the same '
                             'buying power. See CashBase.uncommitted',
                })

        imr = order_initial_margin_ratio(self.terms, order.ticker)
        loan = _floor_dong(assessment.order_value - assessment.required_margin)
        draw = MarginDraw(
            order_id=order_id, loan_id=self._next_id('loan'),
            ticker=order.ticker, quantity=order.quantity,
            reserve_price=reserve_price, imr=imr,
            disbursed=loan, principal=loan, at=ts)

        if loan > _ZERO:
            session.securities_cash_ledger().credit(
                loan, ts,
                f'margin loan {draw.loan_id} disbursed on order {order_id} '
                f'({order.quantity} {order.ticker} at {quoted}, imr {imr})')
        self._draws[order_id] = draw
        self._loans[draw.loan_id] = MarginLoan(
            loan_id=draw.loan_id, account_id=self.account_id,
            principal=loan, disbursed_on=ts.date(),
            due_on=_add_days(ts.date(), self.terms.base_term_days),
            status=LoanStatus.OUTSTANDING, ticker=order.ticker,
            quantity=order.quantity,
            rate_at_disbursement=_rate_for_age(self.terms, 0))
        self._record(MarginEventKind.LOAN_DISBURSED, ts, loan_id=draw.loan_id,
                     detail={'order_id': order_id, 'ticker': order.ticker,
                             'quantity': order.quantity,
                             'reserve_price': reserve_price, 'imr': imr,
                             'principal': loan,
                             'grade': 'loan sized on the RESERVATION price, '
                                      'reconciled to the executed value at the '
                                      'order\'s terminal state'})
        return draw

    def unwind(self, draw: MarginDraw, ts: datetime, session: Any,
               reason: str) -> None:
        """Repay a draw whose order never reached the book."""
        if draw.principal > _ZERO:
            session.securities_cash_ledger().debit(
                draw.principal, ts,
                f'margin loan {draw.loan_id} unwound: {reason}')
        self._retire(draw.loan_id)
        draw.principal = _ZERO
        draw.reconciled = True
        self._draws.pop(draw.order_id, None)

    # -- the day loop, called from ExchangeSession.advance_to --------------

    def on_advance(self, session: Any, ts: datetime,
                   next_seq: Callable[[], int]) -> List[Event]:
        """One advance. Returns the session events this pass produced.

        Order inside the pass, and it is normative:

        0. accrue interest for the days that have elapsed since the last
           accrual, **before anything in this pass can repay principal**;
        1. reconcile every terminal margin order's draw against what it
           actually executed, and repay the remainder;
        2. apply any forced-sale proceeds that have now settled;
        3. submit the tickets from the previous determination -- a sale
           decided after yesterday's close reaches today's session;
        4. run the QD 87 Dieu 6.1 determination, once per date at or after
           ``determination_time``.

        3 before 4 so that a sale placed this morning is inside the ratio the
        close is graded on; 2 before 4 so that proceeds settling today are in
        ``DB`` before the account is graded.

        **0 before 1 and 2, and this is a fix rather than a preference.**
        Accrual used to sit inside step 4, and :meth:`_accrue` multiplies the
        elapsed days by the loan's *current* principal -- so a repayment
        landing earlier in the same pass retroactively cut the interest for a
        day the money had already been borrowed for. Measured on the corpus:
        on 2022-10-27 the account accrued 25,549 on a post-sweep principal of
        69,079,147 for a day on which 92,000,000 was owed; correct ACT/365 is
        34,027, so 8,478 was forgiven. Across the three live arms 8,478,
        11,119 and 9,032. Small in dong, but silent, systematic and always in
        the broker's disfavour -- a component returning a number because it
        was never ordered correctly.

        The ratio is unaffected in direction: accrued interest reaches ``DB``
        either way, and this can only ever make it larger.
        """
        if ts.date() not in self._dates_seen:
            self._dates_seen.append(ts.date())
        news: List[MarginEvent] = []
        news.extend(self._accrue(ts))
        news.extend(self._reconcile(session, ts))
        news.extend(self._report_results(session, ts))
        news.extend(self._apply_settled_proceeds(session, ts))
        news.extend(self._submit_pending(session, ts))
        if (ts.time() >= self.determination_time
                and ts.date() not in self._determined):
            self._determined[ts.date()] = ts
            news.extend(self._determine(session, ts))
        self._events.extend(news)
        return [e for e in (self._as_session_event(n, next_seq) for n in news)
                if e is not None]

    # -- reading the ledgers ----------------------------------------------

    def _dong(self, session: Any, ticker: str, ts: datetime,
              price: Optional[Decimal]) -> Optional[Decimal]:
        """A quoted price, in dong. See :data:`CURRENCY_UNIT`.

        ``None`` in gives ``None`` out -- an absent price stays absent, which is
        what makes the lot UNPRICED and the account INDETERMINATE. An
        **unresolvable venue** also gives ``None``, deliberately: a price whose
        unit nobody can name is not a price, and defaulting it to 1,000 would
        be right on three venues and silently wrong on any fourth.
        """
        if price is None:
            return None
        try:
            code = session.instrument(ticker, ts).exchange_code
        except Exception:                       # noqa: BLE001 -- reported as None
            return None
        unit = CURRENCY_UNIT.get(code)
        if unit is None:
            return None
        return price * unit

    def collateral(self, session: Any, ts: datetime) -> Tuple[CollateralLot, ...]:
        """Every held security as a :class:`CollateralLot`, priced from the feed.

        A settled parcel and an unsettled one are **separate lots**: the firms
        disagree about whether a bought-and-unsettled share counts toward
        ``PV`` (SSI, ACBS and FNS all count it) and the flag is
        ``BrokerMarginTerms.collateral_includes_pending_buys``, so they cannot
        share a record.

        **``live_price`` and ``last_close`` are the same number on a daily
        run, and that is a property of the data and not of the firm.** A daily
        bar carries one observation, so a firm configured
        :attr:`PriceSource.LIVE_MARKET` -- DNSE's *"ty le Deal tinh theo gia
        thi truong"* -- gets the close, and the QD 87 Dieu 2.4 cap binds
        trivially because the two sides of it are equal. At tick resolution
        they diverge and the cap does real work; a result quoting a
        live-market ratio off a daily corpus should say which it had.
        """
        lots: List[CollateralLot] = []
        for ticker in self._tickers:
            holding = session.holdings(ticker)
            settled = holding.settled
            unsettled = holding.unsettled_quantity
            if settled <= 0 and unsettled <= 0:
                continue
            state = self.market_feed(ticker, ts)
            last = self._dong(session, ticker, ts,
                              None if state is None else state.last)
            reference = self._dong(session, ticker, ts,
                                   None if state is None else state.reference)
            ruling = self.eligibility.get(ticker)
            eligible = (ruling.result if ruling is not None
                        else MarginEligibility.INDETERMINATE)
            if ruling is not None and ruling.on_broker_list is False:
                eligible = MarginEligibility.INELIGIBLE
            if settled > 0:
                lots.append(CollateralLot(
                    ticker=ticker, quantity=settled, last_close=last,
                    live_price=last, reference_price=reference,
                    eligibility=eligible))
            if unsettled > 0:
                lots.append(CollateralLot(
                    ticker=ticker, quantity=unsettled, last_close=last,
                    live_price=last, reference_price=reference,
                    eligibility=eligible, pending_settlement=True))
        return tuple(lots)

    def state_at(self, session: Any, ts: datetime) -> MarginAccountState:
        """Join the tranche ledger and the price feed into one algebra input."""
        return build_account_state(
            account_id=self.account_id, as_of=ts, cash=session.cash(),
            collateral=self.collateral(session, ts), terms=self.terms,
            margin_debt=self.margin_debt,
            accrued_interest=self.accrued_interest,
            accrued_fees=sum((l.accrued_fees for l in self._loans.values()
                              if l.status in _LIVE), _ZERO),
            loans=tuple(l for l in self._loans.values() if l.status in _LIVE),
            open_calls=tuple(c for c in self.monitor.calls if c.is_open),
            is_foreign_investor=self.is_foreign_investor,
            margin_contract_signed=self.margin_contract_signed,
            holder_classes=self.holder_classes,
            lending_suspended=self.lending_suspended)

    def algebra_at(self, session: Any, ts: datetime) -> MarginAccountAlgebra:
        """QD 87 Dieu 2 khoan 3-12 over this account, right now.

        A read model. It does **not** record a determination and does not
        advance the monitor, so a caller may ask at any instant without
        claiming an end-of-day computation.
        """
        return compute_account_algebra(
            self.state_at(session, ts), self.terms,
            regulation=self.regulation)

    # -- the four steps of a pass ------------------------------------------

    def _reconcile(self, session: Any, ts: datetime) -> List[MarginEvent]:
        """Bring each draw back to what its order actually executed."""
        news: List[MarginEvent] = []
        by_id = {r.order_id: r for r in session.orders()}
        for order_id, draw in list(self._draws.items()):
            if draw.reconciled:
                continue
            record = by_id.get(order_id)
            if record is None or not record.is_terminal:
                continue
            executed = _ZERO
            for fill in record.fills:
                price = self._dong(session, draw.ticker, fill.ts, fill.price)
                if price is None:
                    price = fill.price * (
                        CURRENCY_UNIT.get(record.venue.value) or _ONE)
                executed += Decimal(fill.quantity) * price
            target = _floor_dong(executed * (_ONE - draw.imr))
            if target > draw.principal:
                target = draw.principal
            repay = draw.principal - target
            if repay > _ZERO:
                session.securities_cash_ledger().debit(
                    repay, ts,
                    f'margin loan {draw.loan_id} reduced to the executed '
                    f'value: {record.filled_quantity} of '
                    f'{record.original_quantity} {draw.ticker} filled')
            draw.principal = target
            draw.reconciled = True
            self._reprincipal(draw.loan_id, target)
            if target <= _ZERO:
                self._retire(draw.loan_id)
            if repay <= _ZERO and target > _ZERO:
                # The order filled in full at the price the loan was sized on,
                # so the reconciliation is a no-op. Emitting LOAN_DISBURSED for
                # it would put a second disbursement in the Dieu 13.8 book for
                # a loan that was drawn once.
                continue
            news.append(self._event(
                MarginEventKind.LOAN_REPAID if target <= _ZERO
                else MarginEventKind.LOAN_DISBURSED, ts,
                loan_id=draw.loan_id,
                detail={'order_id': order_id,
                        'state': record.state.value,
                        'filled': record.filled_quantity,
                        'original': record.original_quantity,
                        'executed_value': executed,
                        'disbursed': draw.disbursed,
                        'repaid': repay,
                        'principal': target,
                        'note': 'reconciliation, not a new disbursement: the '
                                'draw was sized on the reservation price and '
                                'is now sized on what executed'}))
        return news

    def _report_results(self, session: Any, ts: datetime) -> List[MarginEvent]:
        """The statement QD 87 Dieu 8 requires **after** the sell order.

        The article has two limbs and they are equally binding: notify before
        the order, and send a statement of results after it. An engine that
        modelled only the notice would discharge half the duty and report the
        whole of it. ``MarginCallMonitor.report_sale_results`` is the half that
        had no call site until this wiring made one.
        """
        if not self._live_instructions:
            return []
        by_id = {r.order_id: r for r in session.orders()}
        news: List[MarginEvent] = []
        for order_id, instruction_id in list(self._live_instructions.items()):
            record = by_id.get(order_id)
            if record is None or not record.is_terminal:
                continue
            self._live_instructions.pop(order_id, None)
            filled = record.filled_quantity
            note = (f'order {order_id} ended {record.state.value}; '
                    f'submitted {record.original_quantity} shares')
            try:
                news.extend(self.monitor.report_sale_results(
                    instruction_id, ts, filled_quantity=filled,
                    average_price=record.average_fill_price, note=note))
            except ValueError:
                # report_sale_results refuses a fill larger than the ticket it
                # sized, and the board-lot rounding this layer applies makes
                # the submitted order larger than that ticket. Both quantities
                # go on the record rather than clamping the fill to a number
                # that did not happen.
                news.append(self._event(
                    MarginEventKind.FORCED_SALE_RESULT_SENT, ts,
                    instruction_id=instruction_id,
                    detail={'ticker': record.order.ticker,
                            'filled_quantity': filled,
                            'ordered_quantity': record.original_quantity,
                            'average_price': record.average_fill_price,
                            'unfilled': record.remaining_quantity,
                            'note': note, 'raised_by_monitor': False,
                            'article': 'QD 87 Dieu 8 -- the statement of '
                                       'results after the sale'}))
        return news

    def _apply_settled_proceeds(self, session: Any,
                                ts: datetime) -> List[MarginEvent]:
        """Apply *ban giai chap* proceeds to ``DB`` once the tranche settles.

        **The T+2 lag is the whole reason this is a separate step.** A forced
        sale moves value out of ``PV`` and into ``CB`` and changes the ratio by
        exactly nothing -- ``value_to_restore``'s own docstring says so. The
        breach is cured when the debt is paid, and on a Vietnamese equity
        account that is two settlement days after the sale, not on the day of
        it. A model that netted the sale against the debt at execution would
        report a cure the client never got.

        Settlement is detected from the read model: a tranche carrying this
        order's ``source_order_id`` is in ``Cash.pending_proceeds`` until
        ``CashLedger.settle_due`` retires it, so its disappearance -- with a
        recorded amount -- **is** the settlement.
        """
        if not self._awaiting_proceeds:
            return []
        pending: Dict[OrderId, Decimal] = {}
        for tranche in session.cash().pending_proceeds:
            if tranche.source_order_id in self._sale_orders:
                pending[tranche.source_order_id] = (
                    pending.get(tranche.source_order_id, _ZERO)
                    + tranche.amount)
        for order_id, amount in pending.items():
            if amount > self._sale_orders[order_id]:
                self._sale_orders[order_id] = amount

        terminal = {r.order_id for r in session.orders() if r.is_terminal}
        news: List[MarginEvent] = []
        for order_id in list(self._awaiting_proceeds):
            if order_id in pending:
                continue
            proceeds = self._sale_orders.get(order_id, _ZERO)
            if proceeds <= _ZERO:
                if order_id in terminal:
                    # cancelled, expired or filled nothing: no money is coming
                    self._awaiting_proceeds.pop(order_id, None)
                continue
            self._awaiting_proceeds.pop(order_id, None)
            if not self.apply_proceeds_on_settlement:
                continue
            news.extend(self._sweep(session, ts, proceeds, order_id))
        return news

    def _sweep(self, session: Any, ts: datetime, proceeds: Decimal,
               order_id: Optional[OrderId], *,
               reason: str = 'sale proceeds') -> List[MarginEvent]:
        """Pay down what is owed in the firm's stated order. Dieu 8 / 12.2(i)."""
        owed = {
            ProceedsComponent.PRINCIPAL: self.margin_debt,
            ProceedsComponent.INTEREST: self.accrued_interest,
            ProceedsComponent.FEES: sum(
                (l.accrued_fees for l in self._loans.values()
                 if l.status in _LIVE), _ZERO),
            ProceedsComponent.TAXES: _ZERO,
        }
        # The sweep can only move money that is actually in the account. A
        # client who spent the proceeds between the sale and its settlement
        # leaves the broker sweeping less than the sale raised, and that gap is
        # reported rather than netted away -- it is the difference between a
        # debt reduced and a debt the CTCK is still owed under Dieu 8's
        # residual-recovery limb.
        spendable = session.cash().available
        available = min(proceeds, spendable)
        application = apply_sale_proceeds(
            available, owed, self.terms.proceeds_application_order)
        self._applications.append((ts, application))

        paid = application.applied.get(ProceedsComponent.PRINCIPAL, _ZERO)
        paid += application.applied.get(ProceedsComponent.INTEREST, _ZERO)
        paid += application.applied.get(ProceedsComponent.FEES, _ZERO)
        if paid > _ZERO:
            session.securities_cash_ledger().debit(
                paid, ts,
                f'margin debt repaid from {reason}'
                + (f' of {order_id}' if order_id else ''))
        self._reduce_debt(
            application.applied.get(ProceedsComponent.PRINCIPAL, _ZERO),
            application.applied.get(ProceedsComponent.INTEREST, _ZERO),
            application.applied.get(ProceedsComponent.FEES, _ZERO), ts)
        return [self._event(
            MarginEventKind.LOAN_REPAID, ts,
            detail={'order_id': order_id, 'source': reason,
                    'proceeds': proceeds,
                    'cash_available': spendable,
                    'proceeds_not_swept': proceeds - available,
                    'applied_from_cash': paid,
                    'order': tuple(c.value for c in application.order),
                    'applied': {c.value: v
                                for c, v in application.applied.items()},
                    'unpaid': {c.value: v
                               for c, v in application.unpaid.items()},
                    'residual': application.residual,
                    'fully_discharged': application.fully_discharged,
                    'article': 'QD 87 Dieu 8 (the residual is the client\'s '
                               'only after the debt is deducted); the ORDER is '
                               'Dieu 12.2(i) and is SILENT -- it comes from '
                               'BrokerMarginTerms.proceeds_application_order'})]

    def _submit_pending(self, session: Any, ts: datetime) -> List[MarginEvent]:
        """Place the tickets a previous determination raised. QD 87 Dieu 8."""
        plan = self._pending_plan
        if plan is None or not self.execute_forced_sale:
            return []
        self._pending_plan = None
        news: List[MarginEvent] = []
        for instruction in plan.instructions:
            state = self.market_feed(instruction.ticker, ts)
            limit = _sale_limit(self.terms.forced_sale_price, instruction, state)
            order_type = (OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT
                          if limit is None else OrderType.LIMIT)
            quantity, lot = self._to_lot(session, instruction, ts)
            if quantity <= 0:
                news.append(self._event(
                    MarginEventKind.FORCED_SALE_INSTRUCTED, ts,
                    instruction_id=instruction.instruction_id,
                    call_id=instruction.call_id,
                    detail={'ticker': instruction.ticker,
                            'planned_quantity': instruction.quantity,
                            'quantity': 0, 'round_lot': lot,
                            'accepted': False,
                            'refusal': {'rule': 'round_lot',
                                        'reason': 'the sized quantity is below '
                                                  'one board lot and there is '
                                                  'no odd-lot order matching '
                                                  'here'}}))
                continue
            outcome = session.submit(Order(
                ticker=instruction.ticker, side=Side.SELL,
                quantity=quantity, order_type=order_type,
                limit_price=limit))
            accepted = not isinstance(outcome, Rejected)
            if accepted:
                self._sale_orders[outcome.order_id] = _ZERO
                self._awaiting_proceeds[outcome.order_id] = True
                self._live_instructions[outcome.order_id] = (
                    instruction.instruction_id)
            news.append(self._event(
                MarginEventKind.FORCED_SALE_INSTRUCTED, ts,
                instruction_id=instruction.instruction_id,
                call_id=instruction.call_id,
                detail={'ticker': instruction.ticker,
                        'planned_quantity': instruction.quantity,
                        'quantity': quantity, 'round_lot': lot,
                        'price_policy': self.terms.forced_sale_price.value,
                        'limit_price': limit,
                        'order_type': order_type.value,
                        'trigger': instruction.trigger.value,
                        'accepted': accepted,
                        'order_id': (None if not accepted
                                     else outcome.order_id),
                        'refusal': (None if accepted
                                    else {'rule': outcome.rule.value,
                                          'verdict': outcome.verdict.value,
                                          'detail': dict(outcome.detail)}),
                        'notice_satisfied': instruction.notice_satisfied,
                        'article': 'QD 87 Dieu 8. A REFUSED ticket is the '
                                   'finding, not an error: a giai chap into a '
                                   'floor-locked market does not execute '
                                   'because the broker wanted it to'}))
        return news

    def _determine(self, session: Any, ts: datetime) -> List[MarginEvent]:
        """The QD 87 Dieu 6.1 end-of-day determination, once per date.

        Interest is **not** accrued here. It is accrued at the top of
        :meth:`on_advance`, before this pass can repay anything -- see that
        method's step 0.
        """
        news: List[MarginEvent] = []
        state = self.state_at(session, ts)
        algebra = compute_account_algebra(state, self.terms,
                                          regulation=self.regulation)
        self._algebra.append(algebra)
        news.extend(self.monitor.observe(state, algebra))

        if self.monitor.forced_sale_due is None:
            return news
        if self._sale_in_flight(session):
            news.append(self._event(
                MarginEventKind.FORCED_SALE_DUE, ts,
                detail={'trigger': self.monitor.forced_sale_due.value,
                        'suppressed': True,
                        'note': 'a ban giai chap is already in flight for this '
                                'account -- a live ticket, or one filled whose '
                                'proceeds have not settled. No second sale is '
                                'planned. UNSOURCED; see WIRING_PROVENANCE '
                                'under no_double_sale'}))
            return news

        positions = self._positions(session, ts)
        plan, planned = self.monitor.plan_forced_sale(
            positions, algebra, notified_at=ts, disclosed_at=ts)
        self._plans.append(plan)
        news.extend(planned)
        if plan.instructions:
            self._pending_plan = plan
        return news

    def _accrue(self, ts: datetime) -> List[MarginEvent]:
        """Interest on ``DB``. **Nothing accrues without an agreed rate.**"""
        if not self.terms.rate_schedule:
            return []
        day = ts.date()
        if self._accrued_to is None:
            self._accrued_to = day
            return []
        if day <= self._accrued_to:
            return []
        news: List[MarginEvent] = []
        per_year = Decimal(self.terms.day_count.days_per_year)
        for loan_id, loan in list(self._loans.items()):
            if loan.status not in _LIVE or loan.principal <= _ZERO:
                continue
            days = _elapsed(self._accrued_to, day, self.calendar,
                            calendar_days=self.terms.calendar_days)
            if days <= 0:
                continue
            rate = _rate_for_age(self.terms, loan.age_days(day))
            if rate is None:
                continue
            amount = loan.principal * rate * Decimal(days) / per_year
            if loan.status is LoanStatus.OVERDUE:
                amount *= self.terms.overdue_multiplier
            amount = _floor_dong(amount)
            if amount <= _ZERO:
                continue
            self._loans[loan_id] = _replace_loan(
                loan, accrued_interest=loan.accrued_interest + amount)
            news.append(self._event(
                MarginEventKind.INTEREST_ACCRUED, ts, loan_id=loan_id,
                detail={'days': days, 'annual_rate': rate,
                        'day_count': self.terms.day_count.value,
                        'principal': loan.principal, 'amount': amount,
                        'accrued_total':
                            self._loans[loan_id].accrued_interest,
                        'affects_cash': False,
                        'article': 'QD 87 Dieu 11.3 (rate agreed in writing) '
                                   'and 11.4 (method delegated entirely). No '
                                   'cash moves; it reaches the ratio only '
                                   'through accrued_charges_in_debt'}))
        self._accrued_to = day
        return news

    # -- helpers -----------------------------------------------------------

    def _positions(self, session: Any,
                   ts: datetime) -> Tuple[MarginCollateralPosition, ...]:
        """Sellable collateral, at the Dieu 2.4 capped valuation."""
        out: List[MarginCollateralPosition] = []
        for ticker in self._tickers:
            holding = session.holdings(ticker)
            if holding.sellable <= 0:
                continue
            state = self.market_feed(ticker, ts)
            last = self._dong(session, ticker, ts,
                              None if state is None else state.last)
            ruling = self.eligibility.get(ticker)
            out.append(MarginCollateralPosition(
                ticker=ticker, quantity=holding.sellable, price=last,
                loan_ratio=self.terms.loan_ratio_by_ticker.get(ticker),
                is_eligible=(ruling is not None
                             and ruling.result is MarginEligibility.ELIGIBLE),
                # is_breaching stays False, and that is not an oversight. At
                # AccountingUnit.ACCOUNT there is no breaching *position* --
                # the account breaches -- so marking every holding as the one
                # that broke would be a fact nobody established. The two
                # members that read it are refused at construction.
                is_breaching=False))
        return tuple(out)

    def _to_lot(self, session: Any, instruction: Any,
                ts: datetime) -> Tuple[int, int]:
        """Round a ticket to the venue's board lot. Returns ``(quantity, lot)``.

        **The planner deliberately does not do this** -- ``plan_forced_sale``
        says lot sizes are the exchange's and belong to the order layer that
        submits the tickets, and inventing one inside ``margin_lending`` would
        put a second lot table in the codebase. This is that order layer, and
        it is the bug this method exists to have fixed: every ticket the
        planner sized -- 1,459, 913, 1,070, 1,633, 1,762 shares -- was
        ``Rejected(ROUND_LOT)`` by the exchange, and the account went on
        breaching while the log said a sale had been instructed.

        Rounded **up**, because ``value_to_restore`` is a minimum: a ticket
        rounded down raises less than the target needs and leaves the account
        in breach by construction. Capped at the sellable quantity floored to a
        lot -- an odd-lot remainder cannot be sold by order matching at all,
        which is why a sub-lot ticket is reported as unsellable rather than
        submitted and refused.
        """
        try:
            lot = int(session.instrument(instruction.ticker, ts).trading_unit)
        except Exception:                       # noqa: BLE001
            lot = 1
        if lot <= 1:
            return int(instruction.quantity), max(lot, 1)
        wanted = -(-int(instruction.quantity) // lot) * lot
        sellable = session.holdings(instruction.ticker).sellable
        cap = (sellable // lot) * lot
        return min(wanted, cap), lot

    def _sale_in_flight(self, session: Any) -> bool:
        if self._pending_plan is not None:
            return True
        if any(self._awaiting_proceeds.values()):
            return True
        live = {r.order_id for r in session.orders() if not r.is_terminal}
        return bool(live & set(self._sale_orders))

    def _reprincipal(self, loan_id: str, principal: Decimal) -> None:
        loan = self._loans.get(loan_id)
        if loan is not None:
            self._loans[loan_id] = _replace_loan(loan, principal=principal)

    def _retire(self, loan_id: str) -> None:
        """Close a loan out. The Dieu 13.8 book keeps the row, with its status."""
        loan = self._loans.get(loan_id)
        if loan is None:
            return
        self._loans[loan_id] = _replace_loan(
            loan, principal=_ZERO, status=LoanStatus.REPAID)

    def _reduce_debt(self, principal: Decimal, interest: Decimal,
                     fees: Decimal, ts: datetime) -> None:
        """Apply a payment across the loan book, oldest loan first."""
        for loan_id, loan in list(self._loans.items()):
            if loan.status not in _LIVE:
                continue
            take = min(principal, loan.principal)
            take_i = min(interest, loan.accrued_interest)
            take_f = min(fees, loan.accrued_fees)
            if take <= _ZERO and take_i <= _ZERO and take_f <= _ZERO:
                continue
            principal -= take
            interest -= take_i
            fees -= take_f
            updated = _replace_loan(
                loan, principal=loan.principal - take,
                accrued_interest=loan.accrued_interest - take_i,
                accrued_fees=loan.accrued_fees - take_f)
            if updated.total_owed <= _ZERO:
                updated = _replace_loan(updated, status=LoanStatus.REPAID)
            self._loans[loan_id] = updated
            for draw in self._draws.values():
                if draw.loan_id == loan_id:
                    draw.principal = updated.principal

    def _record(self, kind: MarginEventKind, ts: datetime, **kwargs: Any) -> None:
        self._events.append(self._event(kind, ts, **kwargs))

    def _event(self, kind: MarginEventKind, ts: datetime, *,
               loan_id: Optional[str] = None, call_id: Optional[str] = None,
               instruction_id: Optional[str] = None,
               detail: Optional[Mapping[str, Any]] = None) -> MarginEvent:
        return MarginEvent(kind=kind, ts=ts, account_id=self.account_id,
                           loan_id=loan_id, call_id=call_id,
                           instruction_id=instruction_id,
                           detail=dict(detail or {}))

    def _as_session_event(self, news: MarginEvent,
                          next_seq: Callable[[], int]) -> Optional[Event]:
        kind = EQUITY_MARGIN_EVENT_KIND.get(news.kind)
        if kind is None:
            return None
        detail: Dict[str, Any] = dict(news.detail)
        detail['equity_margin_event'] = news.kind.value
        detail['account_id'] = news.account_id
        detail['call_level'] = self.policy.call_level
        detail['force_sell_level'] = self.policy.force_sell_level
        detail['product'] = 'equity margin lending (giao dich ky quy)'
        if news.call_id is not None:
            detail['call_id'] = news.call_id
        if news.instruction_id is not None:
            detail['instruction_id'] = news.instruction_id
        if news.loan_id is not None:
            detail['loan_id'] = news.loan_id
        if kind is EventKind.FORCED_LIQUIDATION:
            detail.setdefault('selection_rule', self.terms.liquidation_order)
            detail.setdefault('price_basis', self.terms.forced_sale_price)
            detail['executed'] = self.execute_forced_sale
        # ``amount`` is deliberately left unset. On the derivatives side it is
        # ``MarginView.required``, a requirement; the equity analogue is the
        # DERIVED top-up, and putting DB there instead would make two events
        # under one EventKind mean two different quantities. The numbers are
        # in ``detail``, each under its own name.
        detail['margin_debt_after_this_pass'] = self.margin_debt
        return Event(kind=kind, ts=news.ts, seq=next_seq(),
                     pool=Pool.SECURITIES, ticker=detail.get('ticker'),
                     detail=detail)

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f'{prefix}-{self.account_id}-{self._seq:04d}'


_LIVE = (LoanStatus.OUTSTANDING, LoanStatus.EXTENDED, LoanStatus.OVERDUE)

#: The order types ``SecuritiesAccount.reserve_for_buy`` funds at the ceiling.
#: Restated here rather than imported so that a change to one is a visible
#: divergence rather than a silent coupling -- but it **must** stay equal to
#: ``ledgers._CEILING_FUNDED``, and :func:`_reserve_price` says why.
_CEILING_FUNDED = frozenset({
    OrderType.MARKET,
    OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
    OrderType.MARKET_FILL_OR_KILL,
    OrderType.MARKET_IMMEDIATE_OR_CANCEL,
    OrderType.AT_THE_OPENING,
    OrderType.AT_THE_CLOSE,
})


def _reserve_price(order: Order, state: MarketState) -> Optional[Decimal]:
    """The price the loan is sized on. Mirrors ``reserve_for_buy`` exactly.

    It **must** mirror it: a loan sized on a different price than the
    reservation leaves the client's own contribution wrong by the difference,
    silently.
    """
    if order.order_type is OrderType.LIMIT:
        return order.limit_price
    if order.order_type in _CEILING_FUNDED:
        return state.ceiling
    return None


def _sale_limit(policy: ForcedSalePrice, instruction: Any,
                state: Optional[MarketState]) -> Optional[Decimal]:
    """Resolve :class:`ForcedSalePrice` to a limit, or ``None`` for market.

    ``FLOOR`` is *gia san* on the day the ticket is placed, read from the band.
    With no band there is no floor, and the ticket degrades to a market-family
    order rather than to a guessed price -- a guessed floor is a price the
    market never published.
    """
    if policy is ForcedSalePrice.LIMIT:
        return instruction.limit_price
    if policy is ForcedSalePrice.FLOOR:
        return None if state is None else state.floor
    return None


def _rate_for_age(terms: BrokerMarginTerms, age: int) -> Optional[Decimal]:
    for tier in terms.rate_schedule:
        if age < tier.day_from:
            continue
        if tier.day_to is None or age <= tier.day_to:
            return tier.annual_rate
    return None


def _elapsed(start: date, end: date, calendar: BusinessDayCalendar, *,
             calendar_days: bool) -> int:
    if calendar_days:
        return (end - start).days
    count = 0
    cursor = start
    while cursor < end:
        cursor = calendar.add_business_days(cursor, 1)
        if cursor > end:
            break
        count += 1
    return count


def _add_days(day: date, days: int) -> date:
    return day + timedelta(days=days)


def _require_positive(name: str, amount: Any) -> None:
    if not isinstance(amount, Decimal):
        raise TypeError(
            f'{name} must be a Decimal, got {type(amount).__name__}. Money is '
            f'never a float in this package')
    if amount <= _ZERO:
        raise ValueError(f'{name} must be strictly positive, got {amount}')


def _replace_loan(loan: MarginLoan, **changes: Any) -> MarginLoan:
    from dataclasses import replace
    return replace(loan, **changes)
