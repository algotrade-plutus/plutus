"""EQUITY MARGIN LENDING -- *giao dich ky quy* -- against the real 2022 crash.

Buy on credit, let the collateral fall, and prove that QD 87/QD-UBCK behaves:
the ratio is computed at the right time, the call is raised at the right rung,
the cure window runs on business days, and the *ban giai chap* is placed,
filled, settled and applied to the debt -- in that order, on those days.

**The window.** ``HPG`` on HSX, **2022-09-23 -> 2022-11-04**, 31 sessions from
the Parquet corpus. HPG closed 23.00 on the first session and 14.15 on the
last: **-38.5 %** in seven weeks, on 20-80 m shares a day, with no trading halt
and no corporate action in the window. It is the largest drawdown in a top-five
HSX name that the wired corpus covers, and the shape matters as much as the
size -- three separate crossings of the call level, two of them cured by the
market inside a day, and only then a sustained breach. A single cliff would
prove the call fires; this proves it fires, clears, re-fires and escalates.

The two dates the scenario turns on::

    2022-10-06   AB/EB = 0.3916 -> below the 0.40 call level. CALL ISSUED,
                 deadline 2022-10-11, three business days on the corpus's own
                 trading calendar.
    2022-10-10   AB/EB = 0.4018 -> at the target. CURED BY THE MARKET, with no
                 payment from the client. This is the case a one-threshold
                 model gets wrong in both directions.

and the two that matter most::

    2022-10-24   third consecutive session below the call level ->
                 FORCED_SALE_DUE(CONSECUTIVE_BREACH_DAYS).
    2022-10-25   1,500 HPG sold at the floor, 15.30. The ratio moves from
                 0.3313 to 0.3445 -- **almost not at all** -- because the
                 proceeds are unsettled and the debt is untouched.
    2022-10-27   T+2. The proceeds settle, 22,920,853 dong is applied to DB,
                 and the ratio jumps 0.3382 -> 0.4198. The account is only
                 cured on the second session after the liquidation.

That last sequence is the point of running this against a Vietnamese market
rather than a generic one. ``value_to_restore``'s own docstring warns that
selling collateral without applying the proceeds to the debt changes the ratio
by exactly nothing; on a T+2 market that is not a footnote, it is a two-session
hole in which a liquidated account is still in breach and still liquidating.

**What is sourced and what is not.** The statutory half is QD 87 and TT 120 and
lives in ``MarginRegulation``; nothing here overrides it. The commercial half
is ``BrokerMarginTerms`` and **not one number in it is sourced** -- the
research found no verified numeric call or force-sell threshold at any
Vietnamese broker for statutory margin. :data:`TERMS_PROVENANCE` says so field
by field. In particular the 0.40 call level is a plausible market value and
nothing more; what is sourced is the *shape* (two levels, a call above a
force-sell) and the floors the levels may not go below (0.30, QD 87 Dieu 5.2).

**Fill policy is ``soft`` and that is a limit of the data, not a preference.**
The Parquet corpus carries no high, no low and no volume, so ``hard`` is
INDETERMINATE on every evaluation and nothing fills at all -- including the
opening purchase. ``soft`` fills at the limit whenever the day's close reached
through it. :func:`run_hard_policy_arm` runs the same window under ``hard`` and
reports the difference rather than leaving it implied.

Run it directly for the three logs::

    PYTHONPATH=src:. python validation/scenarios/equity-margin.py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from plutus.market.protocol import Order, OrderType, Side
from plutus.market.session.calendar import VsdcSettlementCalendar
from plutus.market.session.equity_margin import EquityMarginAccount
from plutus.market.session.margin_lending import (
    BrokerMarginTerms, CureContribution, CureMethod, DayCount, ForcedSalePrice,
    InterestTier, LiquidationOrder, MarginEligibility, MarginEventKind,
    ProceedsComponent, SecurityEligibility,
)
from plutus.market.session.types import Venue

from validation import (BaseStrategy, Scenario, ScenarioResult, StepPhase,
                        Window, build_session, datahub_source, run_scenario,
                        sessions_from_source)

__all__ = [
    'TICKER', 'WINDOW_START', 'WINDOW_END', 'CALENDAR_START', 'CALENDAR_END',
    'OPENING_CASH', 'LOT_SIZE', 'PURCHASE_QUANTITY',
    'CALL_LEVEL', 'FORCE_LEVEL', 'INITIAL_MARGIN_RATIO',
    'TERMS_PROVENANCE', 'broker_terms', 'eligibility_list',
    'corpus_calendar', 'BuyOnMarginAndHold', 'BuyOnMarginAndCure',
    'MarginRun', 'run_hold_arm', 'run_cure_arm', 'run_cure_window_arm',
    'run_hard_policy_arm', 'main',
]

TICKER = 'HPG'
WINDOW_START = date(2022, 9, 23)
WINDOW_END = date(2022, 11, 4)

#: The calendar must cover more than the window: a cure deadline issued on the
#: last session lands after it, and ``VsdcSettlementCalendar`` **raises** rather
#: than extrapolating weekdays. That refusal is correct and it is why this is
#: wider -- see :func:`corpus_calendar`.
CALENDAR_START = date(2022, 6, 1)
CALENDAR_END = date(2022, 12, 30)

OPENING_CASH = Decimal('100000000')          # 100 m dong
LOT_SIZE = 100                               # HSX, from 2021-01-04
PURCHASE_QUANTITY = 8000                     # 80 lots

#: The firm's *TLKQ duy tri*. **UNSOURCED.**
CALL_LEVEL = Decimal('0.40')
#: The firm's *TLKQ xu ly*, set at the statutory floor. **The floor is sourced;
#: choosing to sit on it is not.**
FORCE_LEVEL = Decimal('0.30')
#: *Ty le ky quy ban dau*. The statutory floor, QD 87 Dieu 5.1, and also what
#: every broker in the research caps at.
INITIAL_MARGIN_RATIO = Decimal('0.50')


TERMS_PROVENANCE: Mapping[str, str] = MappingProxyType({
    'maintenance_margin_ratio':
        'UNSOURCED. 0.40. The research read no broker margin contract and the '
        'one published threshold table (DNSE) is a giao dich tien mat '
        'cash-product table, not a margin ladder. What is sourced is that '
        'brokers run TWO levels and that neither may go below 0.30 (QD 87 Dieu '
        '5.2). The number itself is a plausible market value',
    'liquidation_margin_ratio':
        'The VALUE 0.30 is QD 87 Dieu 5.2\'s floor, VERIFIED. Setting the '
        'firm\'s own level exactly on the floor is UNSOURCED -- it makes the '
        'statutory floor the binding force-sell level, which BindingPolicy '
        'reports as PolicyBound.BOTH',
    'initial_margin_ratio':
        'QD 87 Dieu 5.1\'s floor, VERIFIED as a floor. Using it is REPORTED: '
        'SSI\'s per-ticker maximum is exactly 50 % and DNSE, FNS and Pinetree '
        'all cap there. NOTE the restatement "max loan-to-value 50 %" is '
        'DERIVED and is not in the text',
    'cure_business_days':
        '3, the QD 87 Dieu 7.1 CEILING used in full -- VERIFIED as a ceiling, '
        'REPORTED that SSI and ACBS use all of it. Dieu 7.1 ALONE carries the '
        'day count; TT 120 Dieu 9.6 has the call and the sale right and no '
        'number',
    'consecutive_breach_days_before_sale':
        '3. REPORTED at SSI, and BrokerMarginTerms refuses anything above the '
        'QD 87 Dieu 7.1 cure ceiling -- 10 raises BrokerTermLooserThanLaw. '
        '**This term dominates the cure window whenever the breach is '
        'uninterrupted**: the counter increments on the observation that '
        'ISSUES the call, so three breaches arrive on the third observation '
        'and three business days elapse on the fourth. CURE_WINDOW_EXPIRED -- '
        'the only statutory trigger of the five -- is therefore unreachable in '
        'the hold arm. run_cure_window_arm() sets cure_target_ratio above the '
        'call level instead, which is the one lawful configuration that '
        'reaches it',
    'forced_sale_price':
        'FLOOR (*gia san*). SILENT in the regulation -- no rule sets the '
        'execution price. DNSE publishes a floor policy and nothing else is '
        'published. It systematically under-raises against the sizing, which '
        'plan_forced_sale declares',
    'liquidation_order':
        'LARGEST_POSITION_FIRST. SILENT -- QD 87 Dieu 12.2(i) requires the '
        'CONTRACT to state the disposal method and prescribes none. With one '
        'holding it is not observable; it is stated because the field has no '
        'default and a run must say what it ran',
    'proceeds_application_order':
        'PRINCIPAL, INTEREST, FEES, TAXES. SILENT, same clause. It changes '
        'nothing while the proceeds cover everything and decides which '
        'component goes unpaid when they do not -- which is this run: the '
        '2022-10-27 sweep pays 22.9 m against a 92 m principal and the accrued '
        'interest gets nothing',
    'rate_schedule':
        'One open-ended tier at 13.5 %/nam. REPORTED at SSI. QD 87 Dieu 11.3 '
        'sets no statutory rate and no cap beyond the Civil Code; Dieu 11.4 '
        'delegates the calculation method entirely. An EMPTY schedule would '
        'mean no rate was agreed and nothing would accrue',
    'day_count':
        'ACT/365. SILENT -- and not recoverable from the rate: SSI\'s 13.5 % is '
        'over 360 and DNSE\'s 12.5 % over 365. Stated because it must be',
    'accrued_charges_in_debt':
        'True, the module default and OUR choice, not the article\'s: QD 87 '
        'Dieu 2 khoan 3 defines DB as du no ky quy and does not say. It lowers '
        'AB, so calls fire sooner. Visible in this run -- DB on 2022-09-26 is '
        '92,102,082, which is the 92,000,000 principal plus three days of '
        'accrued interest',
    'settlement_calendar':
        'DERIVED from the corpus\'s own trading days, NOT from a VSDC notice. '
        'No calendar data ships with the repo. It is right for this window '
        '(no Tet, no settlement-only closure observed in 2022-09..11) and it '
        'is not a source',
    'security_eligibility':
        'HPG asserted ELIGIBLE and on the broker list, as of the window start. '
        'DATED DATA THE CALLER SUPPLIES and nothing in the corpus carries it: '
        'QD 87 Dieu 3\'s predicates need issuer financial statements. Without '
        'this assertion assess_margin_order returns INDETERMINATE and refuses '
        'the order, which is the correct behaviour and is pinned by a test',
})


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def broker_terms(*, consecutive_breach_days: int = 3,
                 maintenance: Decimal = CALL_LEVEL,
                 liquidation: Decimal = FORCE_LEVEL,
                 **overrides: Any) -> BrokerMarginTerms:
    """One securities company's margin product. **Nothing here is a rule.**

    Every default is listed in :data:`TERMS_PROVENANCE` with its grade. The
    construction itself is a check: ``BrokerMarginTerms.__post_init__`` refuses
    anything looser than the statutory floors, so a caller cannot use this
    helper to build an illegal firm.
    """
    settings: Dict[str, Any] = dict(
        maintenance_margin_ratio=maintenance,
        liquidation_margin_ratio=liquidation,
        forced_sale_price=ForcedSalePrice.FLOOR,
        day_count=DayCount.ACT_365,
        liquidation_order=LiquidationOrder.LARGEST_POSITION_FIRST,
        proceeds_application_order=(ProceedsComponent.PRINCIPAL,
                                    ProceedsComponent.INTEREST,
                                    ProceedsComponent.FEES,
                                    ProceedsComponent.TAXES),
        firm='UNSOURCED demonstration terms -- see TERMS_PROVENANCE',
        initial_margin_ratio=INITIAL_MARGIN_RATIO,
        cure_business_days=3,
        consecutive_breach_days_before_sale=consecutive_breach_days,
        rate_schedule=(InterestTier(0, None, Decimal('0.135')),),
    )
    settings.update(overrides)
    return BrokerMarginTerms(**settings)


def eligibility_list(as_of: date = WINDOW_START
                     ) -> Dict[str, SecurityEligibility]:
    """The caller-supplied margin list. See ``security_eligibility`` above."""
    return {TICKER: SecurityEligibility(
        ticker=TICKER, as_of=as_of, result=MarginEligibility.ELIGIBLE,
        venue=Venue.HSX, on_broker_list=True,
        note='ASSERTED by this scenario. QD 87 Dieu 3 is an exchange-published '
             'negative list and Dieu 4.2 a broker positive list; the corpus '
             'carries neither, and answering ELIGIBLE on absent data is the '
             'thing SecurityEligibility exists to make visible')}


def corpus_calendar(source: Any) -> VsdcSettlementCalendar:
    """Business days from the corpus's own trading days.

    Built from the **positive set** rather than a holiday list, because the
    corpus knows which days traded and does not know why the others did not.
    ``source`` is stamped on it so ``provenance().settlement_calendar_id``
    cannot be mistaken for a VSDC notice.
    """
    days = sessions_from_source(source, TICKER, CALENDAR_START, CALENDAR_END)
    return VsdcSettlementCalendar.from_settlement_days(
        list(days), (CALENDAR_START, CALENDAR_END), 'corpus-trading-days',
        source='DERIVED from the trading days the Parquet corpus carries for '
               'HPG -- NOT a VSDC settlement notice. It coincides with the '
               'exchange calendar by construction, which is exactly the '
               'assumption calendar.py refuses to make for Tet')


# --------------------------------------------------------------------------
# The algorithms
# --------------------------------------------------------------------------

class BuyOnMarginAndHold(BaseStrategy):
    """Buy once on credit at the published reference, then do nothing.

    The purchase is priced at the session **reference** -- the previous close,
    published before the open -- and not at the day's last price. On a daily
    bar ``state.last`` is the close, so limiting at it would be look-ahead in a
    scenario whose whole subject is what the broker knew when.

    Doing nothing afterwards is the algorithm. Everything that follows is the
    broker's: the determination, the call, the window, the sale.
    """

    name = 'buy-on-margin-and-hold'

    def __init__(self, quantity: int = PURCHASE_QUANTITY) -> None:
        self.quantity = quantity
        self.entry: Optional[Any] = None

    def on_session(self, ctx: Any) -> None:
        if self.entry is not None or ctx.phase is not StepPhase.OPEN:
            return
        state = ctx.market(TICKER)
        if state is None or state.reference is None:
            return
        self.entry = ctx.submit(Order(
            ticker=TICKER, side=Side.BUY, quantity=self.quantity,
            order_type=OrderType.LIMIT, limit_price=state.reference,
            on_margin=True))
        ctx.note('opened on margin', ticker=TICKER, quantity=self.quantity,
                 limit=state.reference, outcome=type(self.entry).__name__)


class BuyOnMarginAndCure(BuyOnMarginAndHold):
    """As above, but answer the first call with cash. QD 87 Dieu 7.

    The client deposits the DERIVED ``top_up_cash`` and has it swept against
    ``DB`` -- the ACBS behaviour, and the cheapest of the three cure methods
    for any target below 0.5. The deposit is an **external inflow**: a broker
    does not create a client's money, so it enters through
    :meth:`EquityMarginAccount.deposit_cash` and leaves through
    :meth:`EquityMarginAccount.repay`, both of which appear in the cash log.

    The cure is recorded against the call as well as paid, because
    ``MarginCallMonitor`` scores contributions against the requirement it
    issued and a payment nobody recorded cures the ratio without ever closing
    the call.
    """

    name = 'buy-on-margin-and-cure-the-first-call'

    def __init__(self, account: EquityMarginAccount,
                 quantity: int = PURCHASE_QUANTITY) -> None:
        super().__init__(quantity)
        self.account = account
        self.cured = False
        self.cure_amount: Optional[Decimal] = None

    def on_session(self, ctx: Any) -> None:
        super().on_session(ctx)
        if self.cured or ctx.phase is not StepPhase.OPEN:
            return
        call = self.account.open_call
        if call is None or call.top_up_cash <= 0:
            return
        amount = Decimal(call.top_up_cash).quantize(Decimal('1'))
        session = self.account_session(ctx)
        self.account.deposit_cash(session, amount, ctx.now)
        self.account.repay(session, amount, ctx.now,
                           reason='client top-up answering ' + call.call_id)
        self.account.cure(CureContribution(
            method=CureMethod.DEPOSIT_CASH, amount=amount, at=ctx.now,
            applied_to_debt=True,
            note='swept against DB at deposit, the ACBS behaviour'))
        self.cured = True
        self.cure_amount = amount
        ctx.note('cured the call with cash', call_id=call.call_id,
                 amount=amount, deadline=call.deadline,
                 target_ratio=call.target_ratio)

    @staticmethod
    def account_session(ctx: Any) -> Any:
        """The session behind the context.

        ``StrategyContext`` deliberately does not expose the session -- it owns
        the event cursor and the cursor is destructive. A cash deposit is not
        an order, so it has no context method, and reaching for the private
        attribute is the honest way to say that this arm is doing something the
        strategy API does not model. Recorded here rather than hidden.
        """
        return ctx._session


# --------------------------------------------------------------------------
# The runs
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class MarginRun:
    """One arm: the harness result, the margin account and the session.

    The session is carried because the order book is the authority on an
    order's fate and the trade log is not -- a *ban giai chap* is submitted by
    the session itself, so the harness's trade log has no ACCEPTED row for it
    (see the scenario's own findings). An assertion about order lifecycle has
    to ask the book.
    """

    result: ScenarioResult
    account: EquityMarginAccount
    strategy: Any
    session: Any

    def ratio_on(self, day: date) -> Optional[Decimal]:
        for algebra in self.account.determinations:
            if algebra.as_of.date() == day:
                return algebra.margin_ratio
        return None

    def status_on(self, day: date) -> Optional[str]:
        for algebra in self.account.determinations:
            if algebra.as_of.date() == day:
                return algebra.status.value
        return None

    def events_of(self, *kinds: MarginEventKind) -> Tuple[Any, ...]:
        return tuple(e for e in self.account.events if e.kind in kinds)

    def dates_of(self, *kinds: MarginEventKind) -> Tuple[date, ...]:
        return tuple(e.ts.date() for e in self.events_of(*kinds))


def _build(*, terms: BrokerMarginTerms, fill_policy: str = 'soft',
           execute_forced_sale: bool = True,
           is_foreign_investor: bool = False,
           source: Any = None) -> Tuple[Any, EquityMarginAccount, Any,
                                        Tuple[date, ...]]:
    source = source if source is not None else datahub_source()
    sessions = sessions_from_source(source, TICKER, WINDOW_START, WINDOW_END)
    calendar = corpus_calendar(source)
    session = build_session(
        start=WINDOW_START, end=WINDOW_END, venues=['HSX'], source=source,
        initial_cash=OPENING_CASH, fill_policy=fill_policy,
        settlement=calendar)
    account = EquityMarginAccount(
        account_id='KQ-HPG-2022', terms=terms, calendar=calendar,
        market_feed=source.state_at, eligibility=eligibility_list(),
        tickers=(TICKER,), execute_forced_sale=execute_forced_sale,
        is_foreign_investor=is_foreign_investor)
    session.attach_equity_margin(account)
    return session, account, source, sessions


def _run(session: Any, account: EquityMarginAccount, source: Any,
         sessions: Sequence[date], strategy: Any, name: str,
         note: str) -> MarginRun:
    window = Window(name='HPG 2022 margin drawdown', start=WINDOW_START,
                    end=WINDOW_END, tickers=(TICKER,),
                    sessions=tuple(sessions), reference_ticker=TICKER,
                    note='HPG 23.00 -> 14.15, -38.5 %, 31 HSX sessions')
    scenario = Scenario(name=name, window=window, session=session,
                        strategy=strategy, source=source, note=note)
    return MarginRun(result=run_scenario(scenario), account=account,
                     strategy=strategy, session=session)


def run_hold_arm(source: Any = None) -> MarginRun:
    """The primary arm: buy on credit and let the market do the rest."""
    session, account, source, sessions = _build(terms=broker_terms(),
                                                source=source)
    return _run(session, account, source, sessions, BuyOnMarginAndHold(),
                'equity-margin/hold',
                'the client does nothing: every call, the escalation and both '
                'ban giai chap are the broker\'s')


def run_cure_arm(source: Any = None) -> MarginRun:
    """The client answers the first call with cash, inside the window."""
    session, account, source, sessions = _build(terms=broker_terms(),
                                                source=source)
    return _run(session, account, source, sessions,
                BuyOnMarginAndCure(account), 'equity-margin/cure',
                'QD 87 Dieu 7: cash deposited and swept against DB')


def run_cure_window_arm(source: Any = None) -> MarginRun:
    """``cure_target_ratio = 0.45``, so the **statutory** trigger can fire.

    ``CURE_WINDOW_EXPIRED`` is the only one of the five forced-sale triggers
    that comes from an article -- QD 87 Dieu 8, on the Dieu 7.1 window closing
    uncured. The other four are broker terms. And with the terms every other
    arm uses it is **unreachable**, for a reason worth stating precisely:

    * ``BrokerMarginTerms`` refuses ``consecutive_breach_days_before_sale``
      **above** ``max_cure_business_days`` -- 10 raises
      :class:`BrokerTermLooserThanLaw`, because letting an uncured account sit
      below the maintenance ratio longer than Dieu 7.1 allows is unlawful, not
      commercial. So the consecutive clock is capped at 3;
    * the breach counter increments on the observation that **issues** the
      call, so three consecutive breaches are reached on the third
      observation, while three business days elapse on the fourth. The
      consecutive trigger therefore fires exactly one session **before** the
      window closes, every time, whenever the breach is uninterrupted.

    The one lawful configuration that reaches the statutory path is a firm
    whose **cure target sits above its call level** -- a buffer, so that curing
    does not leave the client back on the edge. A ratio landing between the two
    is not a breach (the counter resets) and is not a cure (the call stays
    open), so the window runs on while the consecutive clock does not. That is
    what happens here on 2022-10-10: 0.4018 is above the 0.40 call level and
    below the 0.45 target, the counter resets, and the call issued on 2022-10-06
    expires on its own deadline the next session.

    A run that reported "no cure window ever expired" and left it there would
    have been reporting an interaction between two broker terms as if it were
    the law.
    """
    session, account, source, sessions = _build(
        terms=broker_terms(cure_target_ratio=Decimal('0.45')), source=source)
    return _run(session, account, source, sessions, BuyOnMarginAndHold(),
                'equity-margin/cure-window',
                'the statutory trigger: the Dieu 7.1 window closes uncured and '
                'the Dieu 8 right arises')


def run_hard_policy_arm(source: Any = None) -> MarginRun:
    """The same window under ``hard``. Expected to admit and fill **nothing**.

    Not a control that should pass. The Parquet corpus carries no high, no low
    and no volume, so the continuous-touch test has nothing to stand on and
    every evaluation is INDETERMINATE -- including the opening purchase. The
    arm exists so the scenario states the cost of its own fill policy in
    numbers rather than in a caveat.
    """
    session, account, source, sessions = _build(terms=broker_terms(),
                                                fill_policy='hard',
                                                source=source)
    return _run(session, account, source, sessions, BuyOnMarginAndHold(),
                'equity-margin/hard',
                'hard fills on a corpus with no high, low or volume')


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def _ratio_table(run: MarginRun) -> str:
    head = (f'{"date":<12}{"ratio":>9} {"status":<12}{"DB":>16}{"CB":>16}'
            f'{"PV":>16}{"AB":>16}')
    lines = [head, '-' * len(head)]
    for a in run.account.determinations:
        ratio = 'n/a' if a.margin_ratio is None else f'{a.margin_ratio:.4f}'
        lines.append(f'{a.as_of.date()!s:<12}{ratio:>9} {a.status.value:<12}'
                     f'{a.db:>16,.0f}{a.cb:>16,.0f}{a.pv:>16,.0f}'
                     f'{a.ab:>16,.0f}')
    return '\n'.join(lines)


def _margin_events(run: MarginRun) -> str:
    lines = []
    for event in run.account.events:
        if event.kind is MarginEventKind.INTEREST_ACCRUED:
            continue
        keys = ('ratio', 'target_ratio', 'deadline', 'trigger', 'quantity',
                'limit_price', 'accepted', 'refusal', 'suppressed', 'applied',
                'filled_quantity', 'principal', 'credit', 'shortfall')
        detail = {k: v for k, v in event.detail.items() if k in keys}
        lines.append(f'{event.ts.date()}  {event.kind.value:<26} {detail}')
    return '\n'.join(lines)


def _logs(run: MarginRun) -> str:
    logs = run.result.logs
    out: List[str] = ['TRADE LOG']
    for e in logs.trades:
        out.append(f'  {e.seq:>3} {e.ts.date()} {e.action.value:<12} '
                   f'{str(e.order_id):<16}{str(e.side):<6}{e.quantity} '
                   f'@ {e.limit_price}  fill={e.fill_quantity}@{e.fill_price} '
                   f'{e.rule or ""} {e.reason or ""}')
    out.append('CASH LOG')
    for e in logs.cash:
        balance = ('' if e.balance_after is None
                   else f'{e.balance_after:>16,.0f}')
        out.append(f'  {e.seq:>3} {e.ts.date()} {e.movement.value:<24}'
                   f'{e.amount:>16,.0f}{balance}  {e.cause}')
    out.append('SETTLEMENT LOG')
    for e in logs.settlement:
        out.append(f'  {e.seq:>3} {e.ts.date()} {e.action.value:<18}'
                   f'{str(e.ticker):<6}{str(e.quantity):>8} '
                   f'{"" if e.amount is None else f"{e.amount:,.0f}":>16}  '
                   f'due {e.settles_at} settled {e.settled_at}')
    return '\n'.join(out)


def main() -> None:                                       # pragma: no cover
    for label, runner in (('HOLD', run_hold_arm),
                          ('CURE', run_cure_arm),
                          ('CURE WINDOW', run_cure_window_arm),
                          ('HARD POLICY', run_hard_policy_arm)):
        run = runner()
        print('=' * 78)
        print(f'{label}: {run.result.name}')
        print('=' * 78)
        print(run.result.summary())
        print()
        print(_ratio_table(run))
        print()
        print(_margin_events(run))
        print()
        print(_logs(run))
        print()


if __name__ == '__main__':                                # pragma: no cover
    main()
