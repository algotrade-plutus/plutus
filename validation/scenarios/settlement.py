"""T+2 settlement, and the calendar traps that make a naive T+2 wrong.

The question this scenario asks is the one every Vietnamese retail platform
answers on its front page: *when can I sell what I just bought, and when does
the money from what I just sold actually arrive?* Four things have to be right
at once for the answer to be right, and each of them is broken separately by a
plausible implementation:

1. **The cycle.** T+2, counted in **VSDC settlement business days** -- since
   2016-01-01, not since 2022-08-29.
2. **The calendar.** Those business days are not weekdays. Tet closes the
   depository for five consecutive weekdays and a Mon-Fri counter walks
   straight through it. Measured here, not assumed: see
   :data:`VN_NON_TRADING_WEEKDAYS`.
3. **The time of day.** Before 2022-08-29 settlement completed 15:30-16:00 on
   T+2 -- after the close -- so the first sellable session was the *open of
   T+3*. From 2022-08-29 (Decision 109/QD-VSD Art. 4) allocation to the client
   is due by **13:00 on T+2**, so the shares are sellable that afternoon. Two
   trades one session apart therefore become sellable on the same calendar day
   four hours apart, and :func:`run_regime_boundary` is that pair.
4. **Both legs.** A buy delivers shares at the DVP instant; a sell delivers
   *cash* at its own DVP instant two settlement days later. A simulator that
   settles shares and credits sale proceeds immediately looks identical on the
   first leg and is wrong by 3-12 calendar days on the second.

Windows
-------

``TET_2022``  2022-01-24 .. 2022-02-11, HSX, HPG.
    Tet 2022 closed the market 2022-01-31 .. 2022-02-04. Full band coverage on
    every session -- the 2021 Tet window has no published reference or band
    before 2021-02-17 in either source, so an admission decision there would be
    undecidable and the window is not used. Two discriminating trade dates sit
    in it and they fail a naive calendar in two different ways, one of them in
    a way a scenario asserting only the *settlement date* would not notice. See
    :func:`run_tet_settlement`.

``BOUNDARY_2022``  2022-08-22 .. 2022-09-09, HSX, HPG.
    Contains the 2022-08-29 regime change *and* the National Day closure
    (2022-09-01, 2022-09-02), so one run exercises the time-of-day change and a
    second calendar trap. See :func:`run_regime_boundary`.

``ADVANCE_2022``  2022-01-26 .. 2022-02-18, HSX, HPG.
    *Ung truoc tien ban* across Tet against the same product in an ordinary
    week, so the cost of the break is a measured ratio and not a claim. See
    :func:`run_advance_across_tet`.

Everything below runs on the already-wired Parquet corpus. No scenario here
needs the production database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import (Any, Dict, List, Mapping, Optional, Sequence, Tuple)

from plutus.core.order import Side
from plutus.market.session.calendar import (
    VnTradingCalendar, VsdcSettlementCalendar, weekday_settlement_calendar,
    weekday_trading_calendar,
)
from plutus.market.session.types import EventKind, Rejected

from validation.corpus import datahub_source
from validation.runner import (
    Scenario, ScenarioResult, Window, build_session, run_scenario,
    sessions_from_source,
)
from validation.strategy import BaseStrategy, StepPhase

__all__ = [
    # calendars
    'VN_NON_TRADING_WEEKDAYS', 'CALENDAR_COVERAGE', 'CALENDAR_SOURCE',
    'measured_calendars', 'naive_calendars', 'measure_non_trading_weekdays',
    # windows
    'TET_2022', 'BOUNDARY_2022', 'ADVANCE_2022', 'TICKER',
    # broker profiles
    'BROKER_NO_ADVANCE', 'BROKER_WITH_ADVANCE', 'ADVANCE_DAILY_RATE',
    # algorithms
    'SettlementProbe', 'AdvanceAgainstSale', 'SellAttempt', 'SaleRecord',
    # runs
    'run_tet_settlement', 'run_regime_boundary', 'run_advance_across_tet',
    'run_rebuy_on_the_advance', 'CashSample', 'SettlementRun',
]


TICKER = 'HPG'


# --------------------------------------------------------------------------
# The calendar, measured
# --------------------------------------------------------------------------

#: Every Mon-Fri in 2020-01-01 .. 2022-12-30 on which no Vietnamese venue held
#: a session, **measured from the corpus** -- see
#: :func:`measure_non_trading_weekdays`, which recomputes it, and the test that
#: compares the two. Four independently liquid HSX names (HPG, FPT, VNM, SSI)
#: yield exactly this set, so it is not one ticker's suspension history.
#:
#: These are *exchange* closures. This module also hands them to the **VSDC
#: settlement** calendar, and that is an inference rather than a citation:
#: no date in 2020-2026 could be found on which a Vietnamese venue traded and
#: VSDC did not settle, or the reverse. The inference is recorded in
#: :data:`CALENDAR_SOURCE` and in the calendar id, so a run carrying it says so
#: in its provenance. It is emphatically **not** the claim ``calendar.py``
#: refuses to make -- that weekdays are settlement days. Every one of the
#: twenty-two closures below is a day a naive weekday counter would count.
VN_NON_TRADING_WEEKDAYS: Tuple[date, ...] = tuple(date.fromisoformat(d) for d in (
    # 2020 -- New Year, Tet, Hung Kings, Reunification + Labour, National Day
    '2020-01-01',
    '2020-01-23', '2020-01-24', '2020-01-27', '2020-01-28', '2020-01-29',
    '2020-04-02', '2020-04-30', '2020-05-01', '2020-09-02',
    # 2021
    '2021-01-01',
    '2021-02-10', '2021-02-11', '2021-02-12', '2021-02-15', '2021-02-16',
    '2021-04-21', '2021-04-30', '2021-05-03', '2021-09-02', '2021-09-03',
    # 2022
    '2022-01-03',
    '2022-01-31', '2022-02-01', '2022-02-02', '2022-02-03', '2022-02-04',
    '2022-04-11', '2022-05-02', '2022-05-03', '2022-09-01', '2022-09-02',
))

#: The window the measurement covers, inclusive. Asking outside it raises
#: :class:`~plutus.market.session.calendar.CalendarCoverageError` -- which is
#: the designed behaviour and the reason coverage is not simply widened to the
#: rulebook's span. The corpus's first row is 2020-01-02; 2020-01-01 is
#: included in the holidays above because it is a Wednesday the corpus has no
#: session for, and coverage starts on the 1st so that a January 2020 query is
#: answerable at all.
CALENDAR_COVERAGE: Tuple[date, date] = (date(2020, 1, 1), date(2022, 12, 30))

CALENDAR_SOURCE = (
    'Exchange closures MEASURED from the hermes-parquet corpus over '
    '2020-01-01..2022-12-30: every Mon-Fri with no row for any of HPG, FPT, '
    'VNM, SSI (all four agree exactly, 32 days). Used as the VSDC settlement '
    'closure set as well -- an INFERENCE, not a VSDC notice: no date in '
    '2020-2026 was found on which a Vietnamese venue traded and VSDC did not '
    'settle. The rulebook grades the settlement calendar on Announcement '
    '4228/TB-VSDC (2025-11-20), which is outside this coverage; this calendar '
    'inherits none of that grade.'
)

#: Loud in a provenance record, and deliberately so: it says both that the
#: dates were measured and that the settlement half is derived from trading
#: days rather than read off a depository notice.
SETTLEMENT_CALENDAR_ID = 'vsdc-2020-2022-MEASURED-FROM-TRADING-DAYS'
TRADING_CALENDAR_ID = 'vn-2020-2022-MEASURED'


def measured_calendars() -> Tuple[VsdcSettlementCalendar, VnTradingCalendar]:
    """The measured settlement and trading calendars, in that order.

    Both carry :data:`CALENDAR_SOURCE`, so ``is_sourced`` is ``True`` and the
    string says exactly how far that goes.
    """
    trading = VnTradingCalendar(
        frozenset(VN_NON_TRADING_WEEKDAYS), CALENDAR_COVERAGE,
        TRADING_CALENDAR_ID, source=CALENDAR_SOURCE)
    settlement = VsdcSettlementCalendar(
        frozenset(VN_NON_TRADING_WEEKDAYS), CALENDAR_COVERAGE,
        SETTLEMENT_CALENDAR_ID, source=CALENDAR_SOURCE, trading=trading)
    return settlement, trading


def naive_calendars() -> Tuple[VsdcSettlementCalendar, VnTradingCalendar]:
    """The repo's own unsourced weekday-only defaults, as the control arm.

    The wrong answer is produced by the shipped default rather than by hand
    arithmetic here, so the comparison is against what a caller who supplies no
    calendar actually gets -- which is the failure mode worth measuring.
    """
    trading = weekday_trading_calendar()
    return weekday_settlement_calendar(trading=trading), trading


def measure_non_trading_weekdays(
    source: Any, start: date, end: date,
    tickers: Sequence[str] = ('HPG', 'FPT', 'VNM', 'SSI'),
) -> Tuple[date, ...]:
    """Recompute :data:`VN_NON_TRADING_WEEKDAYS` from a data source.

    A weekday on which *none* of ``tickers`` has a row. Several liquid names
    rather than one, because a single ticker's suspension would manufacture a
    holiday; a disagreement between them is a corpus defect and shows up as a
    difference from the constant rather than being averaged away.
    """
    traded: set = set()
    for ticker in tickers:
        traded.update(sessions_from_source(source, ticker, start, end))
    out: List[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5 and cursor not in traded:
            out.append(cursor)
        cursor += timedelta(days=1)
    return tuple(out)


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------

TET_2022 = Window(
    name='tet-2022-t2',
    start=date(2022, 1, 24), end=date(2022, 2, 11),
    tickers=(TICKER,), reference_ticker=TICKER,
    note='Tet 2022 closed the market 2022-01-31..2022-02-04. Trades on '
         '2022-01-26, -27 and -28 each break a weekday-only T+2 differently.')

BOUNDARY_2022 = Window(
    name='regime-boundary-2022-08-29',
    start=date(2022, 8, 22), end=date(2022, 9, 9),
    tickers=(TICKER,), reference_ticker=TICKER,
    note='Decision 109/QD-VSD takes effect 2022-08-29 (delivery by 13:00 on '
         'T+2, replacing delivery at the open of T+3), and National Day '
         'closes 2022-09-01 and 2022-09-02.')

ADVANCE_2022 = Window(
    name='advance-across-tet-2022',
    start=date(2022, 1, 26), end=date(2022, 2, 18),
    tickers=(TICKER,), reference_ticker=TICKER,
    note='One sale straddling Tet and one in an ordinary week, so the cost of '
         'ung truoc tien ban over the break is a ratio, not a claim.')


# --------------------------------------------------------------------------
# Broker profiles
# --------------------------------------------------------------------------

#: A per-firm commercial number with no statutory floor. 0.15% of trade value
#: is mid-range for a Vietnamese online-only tier; it is here so the trade log
#: carries the charge a real contract note carries, not because any source
#: fixes it. Both profiles use the same rate so the two arms differ in one
#: variable only.
COMMISSION_RATE = '0.0015'

#: ``AdvanceTerms.PROVENANCE`` on ``daily_rate``: the formula
#: ``amount x days x rate`` is sourced; the number is a broker's own, observed
#: 0.00025-0.0005/day. 0.00031/day is DSC's published 0.0356%/day rounded to
#: the ledger's precision and sits inside that range.
ADVANCE_DAILY_RATE = '0.00031'


def _profile(name: str, *, advance: bool) -> Dict[str, Any]:
    return {
        'name': name,
        'commission': [{'venue': 'HSX', 'base': 'trade_value',
                        'rate': COMMISSION_RATE}],
        'advance_sale_proceeds': {'enabled': advance,
                                  'daily_rate': ADVANCE_DAILY_RATE},
    }


BROKER_NO_ADVANCE = _profile('measured-no-advance', advance=False)
BROKER_WITH_ADVANCE = _profile('measured-with-advance', advance=True)


# --------------------------------------------------------------------------
# What the algorithms record
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SellAttempt:
    """One attempt to sell, and what the exchange said about it.

    ``sellable_from`` is the field the whole scenario turns on: a refusal that
    does not name the date is a refusal the caller cannot act on.
    """

    ts: datetime
    phase: str
    quantity: int
    accepted: bool
    order_id: Optional[str] = None
    rule: Optional[str] = None
    binding_constraint: Optional[Any] = None
    sellable_from: Optional[datetime] = None

    @property
    def day(self) -> date:
        return self.ts.date()


@dataclass(frozen=True)
class SaleRecord:
    """A sale the algorithm made, and what it saw of the advance against it."""

    ts: datetime
    quantity: int
    order_id: Optional[str]
    advanceable_before: Decimal
    advanceable_after: Decimal


# --------------------------------------------------------------------------
# The algorithms
# --------------------------------------------------------------------------

class SettlementProbe(BaseStrategy):
    """Buy, then ask the exchange every session whether it may be sold yet.

    This is what a desk actually does with a position it means to flip: it does
    not compute a settlement date and wait, it offers the sale and reads the
    refusal, because the refusal is authoritative and the desk's own calendar
    is not. Four deliberate behaviours:

    * **It probes at both steps of every session, not once a day.** The
      2022-08-29 regime delivers at **13:00 on T+2**, so the same session
      refuses the sale at 09:30 and accepts it at 14:45. A once-a-day probe
      cannot see that and would report the shares as arriving a session late.
    * **It offers the sale twice on the buy day.** Once at the decision step,
      when the buy is still resting and the account holds nothing at all, and
      once at the close step, the moment the fill arrives. Those two refusals
      are not the same refusal: only the second can carry a ``sellable_from``,
      because only then does a tranche exist to date it from. A scenario that
      probes only at the decision step never sees the field it is testing.
    * **It acts on ``binding_constraint``.** When the full quantity is refused
      the exchange states what *is* sellable; the algorithm immediately offers
      that instead. That is the loop a broker API drives in practice, and it
      makes the difference between a right and a wrong calendar observable:
      under a weekday calendar the full quantity is simply accepted and no
      second offer is made.
    * **It never assumes.** ``holdings()`` and the rejection are the only
      inputs; no date arithmetic happens in this class.

    One consequence worth knowing before reading the attempt list: **shares are
    fungible and the exchange answers about the account, not about the parcel
    the algorithm had in mind.** An offer made immediately after a buy can be
    accepted out of an older lot that settled the same morning. That is right,
    and it is why the probe reports quantities rather than lots.
    """

    name = 'settlement-probe'

    def __init__(self, ticker: str, buys: Mapping[date, int]) -> None:
        self.ticker = ticker
        self.buys = dict(buys)
        self.attempts: List[SellAttempt] = []
        #: Reported tallies only -- nothing here drives control flow, which
        #: reads the account instead (see :meth:`_offerable`). They count
        #: *acceptances*, and an accepted order is not a filled one.
        self.bought: int = 0
        self.accepted_quantity: int = 0

    # -- helpers ----------------------------------------------------------

    def _limit(self, ctx: Any) -> Optional[Decimal]:
        """The day's traded price. A limit *at* the print is the honest ask:
        it fills on ``TOUCHED_AT_LIMIT`` and prices at a number the market
        actually printed, so no fill in this scenario rests on a price the
        corpus does not carry."""
        return ctx.price(self.ticker)

    def _offer(self, ctx: Any, quantity: int) -> SellAttempt:
        price = self._limit(ctx)
        outcome = ctx.sell(self.ticker, quantity, limit_price=price)
        if isinstance(outcome, Rejected):
            attempt = SellAttempt(
                ts=ctx.now, phase=ctx.phase.value, quantity=quantity,
                accepted=False, order_id=outcome.order_id,
                rule=getattr(outcome.rule, 'value', outcome.rule),
                binding_constraint=outcome.binding_constraint,
                sellable_from=outcome.sellable_from)
        else:
            attempt = SellAttempt(
                ts=ctx.now, phase=ctx.phase.value, quantity=quantity,
                accepted=True, order_id=outcome.order_id)
            self.accepted_quantity += quantity
        self.attempts.append(attempt)
        return attempt

    @staticmethod
    def _offerable(ctx: Any, ticker: str) -> int:
        """What is left to offer, read off the exchange rather than tallied.

        ``total`` is settled plus unsettled and ``committed`` is the settled
        slice a live sell order has already reserved, so the difference is
        everything the account still owns and has not offered.

        Counting accepted sales instead would be wrong in a way that is easy to
        miss: an order accepted at the last advance of a session **expires
        unfilled** at the next one (``advance_to`` evaluates a day's bar only
        at an advance landing inside that day), and a tally kept on the
        acceptance would then stop offering shares the account still holds.
        The exchange's own numbers do not have that failure mode.
        """
        holding = ctx.holdings(ticker)
        return max(holding.total - holding.committed, 0)

    # -- hooks ------------------------------------------------------------

    def _probe(self, ctx: Any) -> Optional[SellAttempt]:
        """Offer everything still held; if refused, take what was named.

        Guarded on ``live_orders`` so a resting sale is not doubled -- the
        encumbrance would refuse the second one anyway, but on
        ``UNSETTLED_HOLDING`` rather than on the reason that is true, and a
        misleading rejection in the trade log is worse than no row.
        """
        offerable = self._offerable(ctx, self.ticker)
        if offerable <= 0 or ctx.live_orders(self.ticker):
            return None
        attempt = self._offer(ctx, offerable)
        if attempt.accepted:
            return attempt
        partial = attempt.binding_constraint
        if isinstance(partial, int) and partial > 0:
            ctx.note('exchange named a smaller sellable quantity; taking it',
                     requested=attempt.quantity, sellable=partial,
                     rest_sellable_from=attempt.sellable_from)
            return self._offer(ctx, partial)
        return attempt

    def on_events(self, ctx: Any, events: Sequence[Any]) -> None:
        """The close step: probe again, and note whether a buy filled today.

        Probing here is what catches the post-2022-08-29 13:00 delivery inside
        its own session, and on a buy day it is also the first instant at which
        the shares bought this morning actually exist -- so it is the refusal
        that can name a date.
        """
        if ctx.phase is not StepPhase.CLOSE:
            return
        filled = sum(
            event.quantity or 0 for event in events
            if event.kind is EventKind.FILLED
            and event.ticker == self.ticker
            and self._is_buy(ctx, event.order_id))
        if filled:
            ctx.note('a buy filled this session; offering it straight back',
                     ticker=self.ticker, quantity=filled)
        self._probe(ctx)

    @staticmethod
    def _is_buy(ctx: Any, order_id: Optional[str]) -> bool:
        """``Event.for_fill`` carries no side, so the book is the only source.

        The same gap :func:`validation.runner._translate_events` documents: a
        fill row built from the event stream alone cannot say whether shares
        arrived or left.
        """
        for record in ctx.orders():
            if record.order_id == order_id:
                return record.order.side is Side.BUY
        return False

    def on_session(self, ctx: Any) -> None:
        """The decision step: buy if today is a buy day, then probe."""
        quantity = self.buys.get(ctx.today)
        if quantity:
            price = self._limit(ctx)
            outcome = ctx.buy(self.ticker, quantity, limit_price=price)
            if not isinstance(outcome, Rejected):
                self.bought += quantity
                ctx.note('bought; the T+2 clock starts at the fill, not here',
                         ticker=self.ticker, quantity=quantity, price=price)
                # Offered while the buy is still resting: the account may hold
                # nothing at all, in which case there is no tranche to date the
                # refusal from and ``sellable_from`` is honestly ``None``.
                self._offer(ctx, quantity)
            return
        self._probe(ctx)


@dataclass(frozen=True)
class CashSample:
    """Every cash figure the account reports, at one step."""

    ts: datetime
    phase: str
    settled: Decimal
    available: Decimal
    advanced: Decimal
    interest_accrued: Decimal
    advanceable: Decimal

    @property
    def day(self) -> date:
        return self.ts.date()


class AdvanceAgainstSale(BaseStrategy):
    """Sell, then spend the proceeds before they have settled.

    *Ung truoc tien ban* is the product this exercises, and it is exercised the
    only way that proves it is real: the algorithm is funded with far less cash
    than the reinvestment costs, so the buy on ``reinvest_on`` can be paid for
    **only** out of proceeds that have not settled. At a firm that offers the
    advance the order is accepted and the settled balance goes negative until
    DVP squares it -- which is exactly what an advance is. At a firm that does
    not, the identical order is refused for want of cash. One variable, two
    outcomes, both read off the exchange.

    ``advanceable()`` is sampled at every step. With a firm that
    auto-registers -- the default, and the only setting a session built from a
    config can have -- the whole tranche is drawn inside the fill, so this
    figure is zero even in the instant after a sale and the drawn amount shows
    up in ``Cash.advanced`` instead. Recorded rather than worked around.
    """

    name = 'advance-against-sale'

    def __init__(self, ticker: str, sells: Mapping[date, int],
                 buys: Optional[Mapping[date, int]] = None,
                 same_session_buys: Optional[Mapping[date, int]] = None,
                 ) -> None:
        self.ticker = ticker
        self.sells = dict(sells)
        self.buys = dict(buys or {})
        self.same_session_buys = dict(same_session_buys or {})
        self.sales: List[SaleRecord] = []
        self.buy_outcomes: List[Tuple[datetime, int, Any]] = []
        self.samples: List[CashSample] = []

    def _buy(self, ctx: Any, quantity: int, why: str) -> None:
        cash = ctx.cash()
        ctx.note(why, settled=cash.settled_balance, advanced=cash.advanced,
                 available=cash.available)
        outcome = ctx.buy(self.ticker, quantity,
                          limit_price=ctx.price(self.ticker))
        self.buy_outcomes.append((ctx.now, quantity, outcome))

    def on_session(self, ctx: Any) -> None:
        quantity = self.sells.get(ctx.today)
        if quantity:
            before = ctx.advanceable()
            outcome = ctx.sell(self.ticker, quantity,
                               limit_price=ctx.price(self.ticker))
            if not isinstance(outcome, Rejected):
                ctx.note('sold; proceeds pend to DVP and the advance, if the '
                         'firm offers one, is drawn at the fill',
                         ticker=self.ticker, quantity=quantity)
            self.sales.append(SaleRecord(
                ts=ctx.now, quantity=quantity,
                order_id=getattr(outcome, 'order_id', None),
                advanceable_before=before,
                advanceable_after=ctx.advanceable()))

        wanted = self.buys.get(ctx.today)
        if wanted:
            self._buy(ctx, wanted,
                      'reinvesting before the sale has settled; affordable '
                      'only out of the advance')
        self._sample(ctx)

    def on_events(self, ctx: Any, events: Sequence[Any]) -> None:
        """The close step. This is where a same-session rebuy happens.

        The sale filled during the advance that produced these events, so at
        this instant -- and not before it -- the proceeds tranche exists and,
        at a firm that auto-registers, has already been advanced. A buy
        submitted here is funded out of money the depository has not delivered
        and will not deliver for two settlement days. That is the whole product
        and it is reachable through the ordinary session API, with no call to
        ``request_advance``.
        """
        if ctx.phase is StepPhase.CLOSE:
            wanted = self.same_session_buys.get(ctx.today)
            if wanted:
                self._buy(ctx, wanted,
                          'rebuying in the same session the sale filled, out '
                          'of proceeds that will not settle for two '
                          'settlement days')
        self._sample(ctx)

    def _sample(self, ctx: Any) -> None:
        cash = ctx.cash()
        self.samples.append(CashSample(
            ts=ctx.now, phase=ctx.phase.value,
            settled=cash.settled_balance, available=cash.available,
            advanced=cash.advanced, interest_accrued=cash.interest_accrued,
            advanceable=ctx.advanceable()))

    # -- reads a scenario asserts on ---------------------------------------

    def sample_at(self, day: date, phase: str) -> Optional[CashSample]:
        for sample in reversed(self.samples):
            if sample.day == day and sample.phase == phase:
                return sample
        return None


# --------------------------------------------------------------------------
# The runs
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SettlementRun:
    """A scenario result plus the algorithm that produced it.

    The strategy object is kept because its ``attempts`` list is half the
    evidence: the settlement log says when a tranche settled, and the attempt
    list says what the exchange refused, and when, and with which date on it.
    """

    result: ScenarioResult
    strategy: Any
    calendar_id: str
    #: Every charge the session itemised, kept because the *absence* of a row
    #: is an assertion this scenario makes: the cost of a sale advance never
    #: reaches ``session.charges()``.
    charges: Tuple[Any, ...] = ()
    source: Any = field(default=None, repr=False)

    @property
    def logs(self) -> Any:
        return self.result.logs

    def attempts_on(self, day: date) -> Tuple[SellAttempt, ...]:
        return tuple(a for a in self.strategy.attempts if a.day == day)

    @property
    def charge_kinds(self) -> frozenset:
        return frozenset(c.kind for c in self.charges)


def _build(window: Window, *, calendars: str, broker: Mapping[str, Any],
           initial_cash: str, initial_holdings: Optional[Mapping[str, int]],
           source: Any) -> Tuple[Any, str]:
    settlement, trading = (measured_calendars() if calendars == 'measured'
                           else naive_calendars())
    session = build_session(
        start=window.start, end=window.end, venues=['HSX'], source=source,
        initial_cash=initial_cash, fill_policy='soft',
        broker_profile=dict(broker), settlement=settlement, trading=trading,
        initial_holdings=dict(initial_holdings) if initial_holdings else None)
    return session, settlement.calendar_id


def run_tet_settlement(*, calendars: str = 'measured',
                       source: Any = None) -> SettlementRun:
    """Buy either side of Tet 2022; probe for the sellable date every session.

    Two buys, chosen because they break a naive weekday calendar in two
    different ways:

    ==========  ==================  ====================  ==================
    trade date  VSDC T+2            first sellable        weekday-only says
    ==========  ==================  ====================  ==================
    2022-01-26  2022-01-28          2022-02-07 09:00      2022-01-31 -- the
                                                          settlement date is
                                                          right and the
                                                          sellable date is a
                                                          public holiday
    2022-01-27  2022-02-07          2022-02-08 09:00      2022-02-01, wrong
                                                          by five settlement
                                                          days
    ==========  ==================  ====================  ==================

    The 2022-01-26 row is the discriminator that matters most: a test asserting
    only the settlement *date* passes a broken calendar. This scenario asserts
    the sellable *instant*, which is what a seller actually hits.

    Set ``calendars='naive'`` for the control arm. The same algorithm on the
    same window then sells 2,000 shares on 2022-02-07, one full session before
    1,000 of them were deliverable.
    """
    source = source or datahub_source()
    window = TET_2022.with_sessions(
        sessions_from_source(source, TICKER, TET_2022.start, TET_2022.end))
    strategy = SettlementProbe(TICKER, {date(2022, 1, 26): 1000,
                                        date(2022, 1, 27): 1000})
    session, calendar_id = _build(
        window, calendars=calendars, broker=BROKER_NO_ADVANCE,
        initial_cash='1000000000', initial_holdings=None, source=source)
    result = run_scenario(Scenario(
        name=f'{window.name}[{calendars}]', window=window, session=session,
        strategy=strategy, source=source, note=window.note))
    return SettlementRun(result=result, strategy=strategy,
                         calendar_id=calendar_id,
                         charges=tuple(session.charges()), source=source)


def run_regime_boundary(*, calendars: str = 'measured',
                        source: Any = None) -> SettlementRun:
    """Straddle 2022-08-29 and the National Day closure with the same algorithm.

    Three buys:

    * **2022-08-24** -- pre-Decision-109. T+2 = 2022-08-26, delivery at the
      next session's open, so sellable from **09:00 on 2022-08-29**: the
      opening step of that session.
    * **2022-08-25** -- settles on 2022-08-29 itself, the first day the new
      regime is in force. See the note below; the simulator dates the *rule*
      from the trade instant, so it treats this as pre-109 and answers
      2022-08-30.
    * **2022-08-30** -- post-Decision-109 on any reading. T+2 = **2022-09-05**
      (2022-09-01 and -02 are closed) at **13:00**, so the shares are not
      sellable at that session's 09:30 step and are sellable at its 14:45 step.
      A weekday-only calendar answers 2022-09-01, a day the exchange was shut.

    **The 2022-08-25 row is unresolved and is reported, not asserted away.**
    Decision 109 is effective 2022-08-29 and the rulebook's own interval
    endpoints -- ``2016-01-01 .. 2022-08-26`` and ``2022-08-29 .. current`` --
    are *settlement*-day endpoints, not trade-day endpoints;
    ``ExchangeSession._settles_at`` resolves the rule at ``fill.ts``, i.e. by
    trade date. Keying on the settlement date instead would make the
    2022-08-25 trade sellable at 13:00 on 2022-08-29 rather than at 09:00 on
    2022-08-30 -- one full session earlier. No document naming the first
    benefiting trade date could be sourced, so this scenario pins what the
    simulator does and states the alternative.
    """
    source = source or datahub_source()
    window = BOUNDARY_2022.with_sessions(sessions_from_source(
        source, TICKER, BOUNDARY_2022.start, BOUNDARY_2022.end))
    strategy = SettlementProbe(TICKER, {date(2022, 8, 24): 1000,
                                        date(2022, 8, 25): 1000,
                                        date(2022, 8, 30): 1000})
    session, calendar_id = _build(
        window, calendars=calendars, broker=BROKER_NO_ADVANCE,
        initial_cash='1000000000', initial_holdings=None, source=source)
    result = run_scenario(Scenario(
        name=f'{window.name}[{calendars}]', window=window, session=session,
        strategy=strategy, source=source, note=window.note))
    return SettlementRun(result=result, strategy=strategy,
                         calendar_id=calendar_id,
                         charges=tuple(session.charges()), source=source)


#: Deliberately far less than one board lot of HPG costs at this window's
#: prices (~43m VND for 1,000 shares). The reinvestment on 2022-02-07 is
#: therefore unaffordable out of settled cash and affordable only out of the
#: advance, which is the whole point of the arm.
ADVANCE_INITIAL_CASH = '5000000'


def run_advance_across_tet(*, advance: bool = True, reinvest: bool = False,
                           source: Any = None) -> SettlementRun:
    """Sell across Tet and in an ordinary week; watch the advance both times.

    Opening holdings rather than a buy, so the sale can be made on
    **2022-01-28** -- the last session before the break -- and the proceeds
    pend across it. That tranche settles at **09:00 on 2022-02-09** (T+2 =
    2022-02-08, delivered at the next session's open), which is **eleven whole
    days** after the 14:45 fill. The control sale on **2022-02-14** settles at
    09:00 on 2022-02-17, **two whole days** after its fill. Same shares, same
    firm, same daily rate; the only difference is which side of Tet the sale
    was made, so the cost of the break is a ratio the run produces.

    Two switches:

    ``advance``
        whether the firm offers the product at all
        (``BrokerTerms.advance_on_sale_enabled``). With it off,
        ``Cash.available`` does not move until DVP.
    ``reinvest``
        whether the algorithm buys 1,000 shares on **2022-02-07** -- the very
        next session after the sale, with Tet between them, and two sessions
        before the proceeds it is funded from arrive. The account
        holds ``ADVANCE_INITIAL_CASH`` -- far less than the purchase costs --
        so the order is affordable only out of the advance. With
        ``advance=True`` it is accepted and the settled balance goes negative
        until DVP squares it; with ``advance=False`` the same order is refused.

    With ``reinvest=False`` the two arms make identical trades, and their
    closing settled balances are therefore identical to the dong -- which is
    the measurement, not a coincidence: **interest on an advance is accrued
    and never charged anywhere in the session.**
    """
    source = source or datahub_source()
    window = ADVANCE_2022.with_sessions(sessions_from_source(
        source, TICKER, ADVANCE_2022.start, ADVANCE_2022.end))
    strategy = AdvanceAgainstSale(
        TICKER,
        sells={date(2022, 1, 28): 1000, date(2022, 2, 14): 1000},
        buys={date(2022, 2, 7): 1000} if reinvest else {})
    session, calendar_id = _build(
        window, calendars='measured',
        broker=BROKER_WITH_ADVANCE if advance else BROKER_NO_ADVANCE,
        initial_cash=ADVANCE_INITIAL_CASH, initial_holdings={TICKER: 2000},
        source=source)
    result = run_scenario(Scenario(
        name=f'{window.name}[advance={advance},reinvest={reinvest}]',
        window=window, session=session, strategy=strategy, source=source,
        opening_holdings={TICKER: 2000}, note=window.note))
    return SettlementRun(result=result, strategy=strategy,
                         calendar_id=calendar_id,
                         charges=tuple(session.charges()), source=source)


#: The sale whose proceeds fund the rebuy. 2022-02-07 is the first session
#: after Tet; the proceeds do not settle until 09:00 on 2022-02-10.
REBUY_SALE_ON = date(2022, 2, 7)
REBUY_NEXT_ON = date(2022, 2, 8)


def run_rebuy_on_the_advance(*, advance: bool = True,
                             source: Any = None) -> SettlementRun:
    """Sell, then buy again before the proceeds have settled, twice over.

    The account opens with ``ADVANCE_INITIAL_CASH`` -- about a ninth of one
    board lot -- and 2,000 shares. On 2022-02-07 it sells 1,000; the sale fills
    at the close step and, at a firm that auto-registers, the whole net is
    advanced in that same instant. Two rebuys are then offered:

    * **the same session, 14:45**, in ``on_events`` the moment the fill
      arrives. It is **accepted and funded**, which is the claim under test,
      and then it **expires unfilled** at the next advance. That is not a
      defect and not a market outcome: ``ExchangeSession.advance_to`` documents
      that a day's bar is evaluated by the advance that lands inside its day,
      so an order submitted *at* the second and last advance of a daily loop
      has no further advance inside its own day and dies at ``session_end``.
      The admission and funding decision is what proves the advance; the fill
      needs a clock with more than two steps a day.
    * **the next session's open, 2022-02-08 09:30**, two settlement days before
      the proceeds arrive. This one fills.

    That corrects a standing claim about this harness: *ung truoc tien ban* is
    unreachable through ``ExchangeSession`` (there is no ``request_advance`` on
    it, and :meth:`validation.strategy.StrategyContext.advanceable` has to
    reach past the session to find one), but **spending unsettled proceeds is
    not** -- with ``advance_sale_proceeds.enabled`` the draw happens inside
    ``credit_pending`` at the fill and the buying power is simply there. What
    is unreachable is the *investor-initiated* half of the product, and the
    settings that shape it: ``AdvanceTerms``' cap, minimum charge,
    annualisation basis and ``auto_register`` flag have no config key, so every
    config-built session runs at 100% of net proceeds, no minimum, and
    automatic registration.

    With ``advance=False`` both rebuys are refused ``INSUFFICIENT_CASH`` -- and
    the refusal's detail names ``pending_proceeds``, so the account is told the
    money exists and has not settled rather than simply told no.
    """
    source = source or datahub_source()
    window = ADVANCE_2022.with_sessions(sessions_from_source(
        source, TICKER, ADVANCE_2022.start, ADVANCE_2022.end))
    strategy = AdvanceAgainstSale(
        TICKER, sells={REBUY_SALE_ON: 1000},
        buys={REBUY_NEXT_ON: 1000},
        same_session_buys={REBUY_SALE_ON: 1000})
    session, calendar_id = _build(
        window, calendars='measured',
        broker=BROKER_WITH_ADVANCE if advance else BROKER_NO_ADVANCE,
        initial_cash=ADVANCE_INITIAL_CASH, initial_holdings={TICKER: 2000},
        source=source)
    result = run_scenario(Scenario(
        name=f'rebuy-on-the-advance[advance={advance}]', window=window,
        session=session, strategy=strategy, source=source,
        opening_holdings={TICKER: 2000},
        note='spend unsettled sale proceeds: same session, and the next'))
    return SettlementRun(result=result, strategy=strategy,
                         calendar_id=calendar_id,
                         charges=tuple(session.charges()), source=source)
