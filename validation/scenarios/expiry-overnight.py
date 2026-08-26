"""Futures expiry, the roll, and what it costs to still be there at 14:45.

Two questions the author named, and they turn out to be one question asked at
two time scales.

**Expiry.** A VN30F contract is cash-settled against the VN30 index. Nothing
is delivered, nobody is asked whether they want to close: on the last trading
day the position is extinguished and a number lands in the deposit. Four
things have to be right for that number to be right, and each is broken
separately by a plausible implementation:

1. **The last trading day is a trading day.** VN30F2210 printed a close of
   1058.0 on 2022-10-20 and a large part of that session's volume is the roll
   into VN30F2211. A simulator that settles at the first instant it notices
   the date has taken the session away from the caller.
2. **The settlement price has a provenance.** VSDC strikes it from a trimmed
   average of the underlying over 14:15-14:45, not from the close. Where the
   source does not publish one the close stands in, and the substitution has
   to travel on the event -- measured across the 46 post-cutover expiries the
   close proxy runs +0.024% mean signed and 0.333% at worst, which is exactly
   the size of error that vanishes into an average unless every substituted
   row can be excluded.
3. **The cash flow is marked from the variation-margin reference**, not from
   the entry price and not from yesterday's close, or the deposit and the
   requirement stop agreeing at the moment the requirement disappears.
4. **The tax is levied.** Rulebook 8.1/12.3 makes derivatives income taxable
   *"when the order is matched, **or at contract maturity**"*. A contract
   carried to expiry is never matched out, so a fill-only model under-charges
   every held-to-expiry contract by one leg.

**Overnight.** Holding a futures position past the close is the single
decision a Vietnamese derivatives trader is charged extra for and warned
about most, and it is where this simulator's declared boundaries bite:

* the *requirement* over the close is computed by the same continuously
  updated ``MR = IM + VM`` the account faces at 09:30 -- there is no separate
  end-of-day model, and :func:`run_flat_versus_overnight` measures that;
* the *cash* the requirement stands for never moves. ``settle_daily`` has no
  session call site (FEATURES.md D1), so ``VM`` is the cumulative
  since-entry loss rather than the day's, and the whole of it arrives in one
  movement at the close-out. :func:`run_variation_settlement_trail` measures
  the gap in dong per day;
* the *deadline* to answer a call is the **next session's open**, resolved
  through a trading calendar that this repository ships no data for. Over
  Tet 2022 the shipped weekday-only default puts it on 2022-01-31, a day the
  market was shut. :func:`run_cure_across_tet` runs the same account under
  both calendars and gets a forced liquidation under one and none under the
  other.

Windows
-------

``EXPIRY_2022``  2022-10-10 .. 2022-11-18, HNXDS, VN30F2210 -> VN30F2211.
    Two expiries and a roll, on the already-wired Parquet corpus.
    VN30F2210's last trading day is 2022-10-20 and VN30F2211's is
    2022-11-17, so one run settles twice and holds a position across 20
    sessions in between. See :func:`run_expiry_and_roll`.

``TET_2021``  2021-02-03 .. 2021-02-19, HNXDS, VN30F2102.
    The longest unmarked gap in the corpus: the market closes after
    2021-02-09 and reopens on 2021-02-17, and the front month gaps
    **+46.3 index points = 4,630,000 VND a contract** across it. Expiry is
    the session after the reopen. See :func:`run_overnight_across_tet`.

``TET_2022``  2022-01-24 .. 2022-02-11, HSX + HNXDS, VN30F2202.
    A margin call raised at the close of the last session before Tet 2022,
    and the cure deadline that follows it. Bands are published on every
    session here, which the 2021 window cannot say. See
    :func:`run_cure_across_tet`.

``OVERNIGHT_2022``  2022-10-24 .. 2022-10-28, HNXDS, VN30F2211.
    Two accounts, one market: one flat by the close, one not. See
    :func:`run_flat_versus_overnight`.

``POST_KRX_2026``  2026-03-02 .. 2026-03-10, HNXDS, VN30F2603.
    Not on the corpus -- a hand-written market, because the Parquet corpus
    stops on 2022-12-30 and the point of the window is a *date*, not a
    price. See :func:`run_post_krx_margin_model`.

Everything except ``POST_KRX_2026`` runs on the already-wired Parquet corpus.
Nothing here needs the production database.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import (Any, Dict, List, Mapping, Optional, Sequence, Tuple)

from plutus.market.protocol import (
    BandSource, InstrumentKind, InstrumentSpec, MarketState, Resolution,
    SessionPhase,
)
from plutus.market.session.calendar import VnTradingCalendar
from plutus.market.session.rulebook import UnresolvedRule
from plutus.market.session.types import EventKind, MarginStatus, Pool

from validation.corpus import datahub_source
from validation.logs import SettlementAction
from validation.runner import (
    Scenario, ScenarioResult, Window, build_session, run_scenario,
    sessions_from_source,
)
from validation.strategy import BaseStrategy

__all__ = [
    # windows
    'EXPIRY_2022', 'TET_2021', 'TET_2022', 'OVERNIGHT_2022', 'POST_KRX_2026',
    # measured facts
    'TET_2021_CLOSURE', 'TET_2022_CLOSURE', 'VN30F_MULTIPLIER',
    'DERIVATIVES_PIT_RATE', 'PUBLISHED_SETTLEMENT',
    'measured_trading_calendar', 'run_expiry_under_hard_fills',
    # strategies
    'RollAtExpiry', 'HoldOvernight', 'DayTrade', 'CallAndCure',
    # runs
    'run_expiry_and_roll', 'run_overnight_across_tet',
    'run_flat_versus_overnight', 'run_variation_settlement_trail',
    'run_cure_across_tet', 'run_post_krx_margin_model',
    # results
    'ExpiryRun', 'OvernightPair', 'VariationTrail', 'CureRun', 'CureOutcome',
    # helpers
    'maturity_tax', 'settlement_rows', 'margin_events', 'unmarked_gaps',
]

_ZERO = Decimal('0')

#: VN30F contract multiplier, VND per index point. ``adapters/datahub.py``
#: sets it on every ``VN30F`` spec and ``rulebook.resolve_contract_multiplier``
#: carries the dated series; repeated here only so the arithmetic in this
#: module's docstrings can be read without opening either.
VN30F_MULTIPLIER = Decimal('100000')

#: The statutory derivatives transfer tax, against the **margined** base
#: ``notional x IM ratio / 2``. ``charges.DERIVATIVES_PIT_RATE``.
DERIVATIVES_PIT_RATE = Decimal('0.001')

#: What the two expiries in ``EXPIRY_2022`` **actually** settled at, read
#: read-only from the production ``quote.settlementprice`` (the last entry of
#: the expiry day on ``VN30INDEX`` *is* the final settlement price -- it is an
#: already-computed running mean, not a tick to be averaged again).
#:
#: The Parquet corpus publishes none of this, so the session falls back to
#: ``CLOSE_PROXY`` and the run settles at the futures close instead. The cost,
#: for the two contracts this module actually settles:
#:
#: ============  =========  ==========  ==============  =====================
#: contract      published  close used  error (points)  error (VND/contract)
#: ============  =========  ==========  ==============  =====================
#: VN30F2210     1058.29    1058.00     -0.29           **-29,000**
#: VN30F2211      972.78     972.50     -0.28           **-28,000**
#: ============  =========  ==========  ==============  =====================
#:
#: For scale: the transfer tax this module wired onto the same settlement is
#: 6,877 VND. The substitution the run *already* made is four times larger,
#: one-sided, and would be invisible without ``substituted=True``.
#:
#: ``quote.settlementprice`` starts on 2022-08-17, so ``TET_2021``'s expiry on
#: 2021-02-18 has **no oracle at all** -- zero rows on the day. Its close
#: proxy is not merely approximate, it is unfalsifiable from any data this
#: project holds.
PUBLISHED_SETTLEMENT: Mapping[str, Decimal] = {
    'VN30F2210': Decimal('1058.29'),   # 2022-10-20 14:45:12
    'VN30F2211': Decimal('972.78'),    # 2022-11-17 14:45:12
}

#: Tet 2021 closed the market on five consecutive weekdays. Measured: these
#: are the weekdays between 2021-02-09 and 2021-02-17 for which the Parquet
#: corpus carries no row for any VN30F contract, and the corpus's own next
#: session after 2021-02-09 is 2021-02-17.
TET_2021_CLOSURE: Tuple[date, ...] = (
    date(2021, 2, 10), date(2021, 2, 11), date(2021, 2, 12),
    date(2021, 2, 15), date(2021, 2, 16),
)

#: Tet 2022, the same way: last session 2022-01-28, first session 2022-02-07.
TET_2022_CLOSURE: Tuple[date, ...] = (
    date(2022, 1, 31), date(2022, 2, 1), date(2022, 2, 2),
    date(2022, 2, 3), date(2022, 2, 4),
)


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------

EXPIRY_2022 = Window(
    name='expiry-and-roll-2022',
    start=date(2022, 10, 10), end=date(2022, 11, 18),
    tickers=('VN30F2210', 'VN30F2211'),
    reference_ticker='VN30F2212',
    note='VN30F2210 expires 2022-10-20 and VN30F2211 on 2022-11-17. '
         'VN30F2212 is the reference ticker because it is listed across the '
         'whole window and neither of the other two is.',
)

TET_2021 = Window(
    name='overnight-across-tet-2021',
    start=date(2021, 2, 3), end=date(2021, 2, 19),
    tickers=('VN30F2102',), reference_ticker='VN30F2102',
    note='Market closed 2021-02-10 .. 2021-02-16. VN30F2102 expires '
         '2021-02-18, the second session after the reopen.',
)

TET_2022 = Window(
    name='cure-across-tet-2022',
    start=date(2022, 1, 24), end=date(2022, 2, 11),
    tickers=('VN30F2202',), reference_ticker='VN30F2202',
    note='Market closed 2022-01-31 .. 2022-02-04. Bands are published on '
         'every session, which 2021-02-08 and 2021-02-09 are not.',
)

OVERNIGHT_2022 = Window(
    name='flat-versus-overnight-2022',
    start=date(2022, 10, 24), end=date(2022, 10, 28),
    tickers=('VN30F2211',), reference_ticker='VN30F2211',
    note='Five ordinary sessions. Nothing dramatic happens, deliberately: '
         'the question is what the requirement *is*, not whether it breaks.',
)

POST_KRX_2026 = Window(
    name='post-krx-margin-model-2026',
    start=date(2026, 3, 2), end=date(2026, 3, 10),
    tickers=('VN30F2603',),
    sessions=(date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4),
              date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9),
              date(2026, 3, 10)),
    note='Hand-written prices: the Parquet corpus stops 2022-12-30 and this '
         'window is about a date, not a price. The closes are the real ones '
         'from the production database, so the run is recognisable, but the '
         'assertion is about which margin model the session applies.',
)

#: VN30F2603's real daily closes over ``POST_KRX_2026``, read from the
#: production ``quote.close`` (read-only) so a hand-written market is still a
#: real one. 2026-03-09 is a limit-down close.
POST_KRX_CLOSES: Tuple[str, ...] = (
    '2015.0', '1952.0', '1956.0', '1924.4', '1898.9', '1766.0', '1833.0',
)


def measured_trading_calendar(year: int,
                              closure: Sequence[date]) -> VnTradingCalendar:
    """A trading calendar that knows one year's Tet closure.

    The repository ships **no calendar data at all** (FEATURES.md A64/A65),
    so every default run resolves cure deadlines and day-order expiries
    through ``weekday_trading_calendar``, which trades on Tet. This is the
    smallest honest correction: the closure dates are measured from the
    corpus -- they are the weekdays on which no VN30F contract has a row --
    and nothing else about the year is claimed.
    """
    return VnTradingCalendar(
        holidays=frozenset(closure),
        coverage=(date(year, 1, 1), date(year, 12, 31)),
        calendar_id=f'vn-trading-{year}-tet-measured',
        source='measured from the Parquet corpus: weekdays on which no '
               'VN30F contract carries a row',
    )


def maturity_tax(contracts: int, settlement: Decimal,
                 initial_margin_rate: Decimal,
                 multiplier: Decimal = VN30F_MULTIPLIER) -> Decimal:
    """The derivatives transfer tax on a contract carried into settlement.

    ``0.001 x (contracts x multiplier x settlement x IM ratio / 2)``, rounded
    to the whole dong. Written out here so a scenario's expected number is
    derived from the statute's own structure rather than copied out of the
    run it is checking.
    """
    margined = (Decimal(abs(contracts)) * multiplier * settlement
                * initial_margin_rate / Decimal('2'))
    return (DERIVATIVES_PIT_RATE * margined).quantize(Decimal('1'))


# --------------------------------------------------------------------------
# A hand-written market, for the one window the corpus cannot reach
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class _FuturesMarket:
    """A ``MarketDataSource`` over one contract's daily closes.

    Deliberately minimal and deliberately *not* a corpus: it exists for
    ``POST_KRX_2026``, whose whole content is a date. Bands are the real
    +/-7% VN30F limit about the previous close, so an order in this market is
    admitted or refused for the same reason it would be on the corpus.
    """

    ticker: str
    closes: Mapping[date, Decimal]
    expiry: date
    band: Decimal = Decimal('0.07')

    def _reference(self, day: date) -> Decimal:
        days = sorted(self.closes)
        index = days.index(day)
        return self.closes[days[index - 1]] if index else self.closes[day]

    def state_at(self, ticker: str, ts: datetime) -> Optional[MarketState]:
        if ticker != self.ticker:
            return None
        day = ts.date()
        last = self.closes.get(day)
        if last is None:
            return None
        reference = self._reference(day)
        return MarketState(
            ticker=ticker, ts=datetime.combine(day, time.min),
            reference=reference,
            ceiling=reference * (Decimal('1') + self.band),
            floor=reference * (Decimal('1') - self.band),
            band_source=BandSource.PUBLISHED, last=last,
            session=SessionPhase.CONTINUOUS)

    def states(self, ticker: str, start, end, *,
               resolution: Resolution = Resolution.DAILY):
        for day in sorted(self.closes):
            state = self.state_at(ticker, datetime.combine(day, time.min))
            if state is not None and start <= state.ts <= end:
                yield state

    def instrument(self, ticker: str) -> InstrumentSpec:
        return InstrumentSpec(
            ticker=ticker, exchange_code='HNXDS', kind=InstrumentKind.FUTURE,
            trading_unit=1, daily_trading_limit=self.band,
            multiplier=VN30F_MULTIPLIER, expiry=self.expiry,
            underlying='VN30')


# --------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------

class _Recorder(BaseStrategy):
    """Records the margin view at every step. Every strategy here needs it."""

    name = 'recorder'

    def __init__(self) -> None:
        self.marks: List[Dict[str, Any]] = []
        self.events: List[Any] = []

    def on_events(self, ctx, events) -> None:
        self.events.extend(events)
        view = ctx.margin()
        self.marks.append({
            'ts': ctx.now, 'phase': ctx.phase.value,
            'positions': {c: p.net_quantity
                          for c, p in ctx.positions().items()},
            'deposit_balance': view.deposit_balance,
            'required': view.required,
            'initial_margin': view.initial_margin,
            'variation_margin': view.variation_margin,
            'utilisation': view.utilisation,
            'status': view.status.value,
            'cure_by': view.cure_by,
        })

    def at(self, day: date, phase: str) -> Optional[Dict[str, Any]]:
        """The recorded mark for one step, or ``None`` if there was none."""
        for row in self.marks:
            if row['ts'].date() == day and row['phase'] == phase:
                return row
        return None


class RollAtExpiry(_Recorder):
    """Open a front-month long, roll half of it **on the expiry day**.

    Rolling on the last trading day is the ordinary shape of a Vietnamese
    futures book -- VN30F2211's volume goes from a fraction of VN30F2210's to
    all of it in one session -- and it is the case that discriminates hardest,
    because it needs the expiring contract to still be tradable at 09:30 on
    the day it dies. Half the position is deliberately *not* rolled, so one
    run produces both terminal states: a leg closed by an offsetting trade
    and a leg closed by cash settlement, at the same price, on the same day.
    """

    name = 'roll-at-expiry'

    def __init__(self, front: str, back: str, entry: date, roll: date,
                 lots: int = 2) -> None:
        super().__init__()
        self.front, self.back = front, back
        self.entry, self.roll, self.lots = entry, roll, lots
        #: What ``positions()`` reported at 09:30 on the roll day. The whole
        #: point of the scenario: before the fix this read ``{}`` for the
        #: front month, because the contract had already been settled out by
        #: the advance that delivered the strategy to its own decision point.
        self.seen_on_roll_day: Dict[str, int] = {}
        self.after_expiry: List[Any] = []

    def on_session(self, ctx) -> None:
        if ctx.today == self.entry:
            ctx.buy(self.front, self.lots,
                    limit_price=ctx.price(self.front))
            ctx.note(f'open {self.lots} {self.front}',
                     price=ctx.price(self.front))
        elif ctx.today == self.roll:
            self.seen_on_roll_day = {c: p.net_quantity
                                     for c, p in ctx.positions().items()}
            half = self.lots // 2
            ctx.sell(self.front, half, limit_price=ctx.price(self.front))
            ctx.buy(self.back, half, limit_price=ctx.price(self.back))
            ctx.note(f'roll {half} of {self.lots} on the last trading day',
                     front_seen=dict(self.seen_on_roll_day))
        elif ctx.today > self.roll and not self.after_expiry:
            # One attempt to trade a contract whose last trading day has
            # passed. Recorded rather than asserted here: what comes back is
            # the finding.
            self.after_expiry.append(
                ctx.sell(self.front, 1, limit_price=Decimal('1000')))
            ctx.note('order in an expired contract',
                     outcome=type(self.after_expiry[0]).__name__)


class HoldOvernight(_Recorder):
    """Buy once and then do nothing. Overnight holding needs no hook.

    ``on_session`` returning without submitting is what carrying a position
    over the close *is* in this API, which is why the runner's clock and the
    strategy's decisions are separate objects.
    """

    name = 'hold-overnight'

    def __init__(self, code: str, entry: date, lots: int) -> None:
        super().__init__()
        self.code, self.entry, self.lots = code, entry, lots
        self.entry_price: Optional[Decimal] = None
        self.entry_outcome: Any = None

    def on_session(self, ctx) -> None:
        if ctx.today == self.entry:
            self.entry_price = ctx.price(self.code)
            self.entry_outcome = ctx.buy(self.code, self.lots,
                                         limit_price=self.entry_price)
            ctx.note(f'hold {self.lots} {self.code} from {self.entry}',
                     price=self.entry_price,
                     outcome=type(self.entry_outcome).__name__)


class DayTrade(_Recorder):
    """Open and close inside one session, so the account is flat at 14:45.

    Both orders are submitted at the same decision point and both are
    evaluated by the advance that lands inside the day, so the round trip
    completes within the session -- which is what a Vietnamese derivatives
    day-trader does precisely to avoid carrying a requirement overnight.
    """

    name = 'day-trade'

    def __init__(self, code: str, entry: date, lots: int) -> None:
        super().__init__()
        self.code, self.entry, self.lots = code, entry, lots

    def on_session(self, ctx) -> None:
        if ctx.today == self.entry:
            price = ctx.price(self.code)
            ctx.buy(self.code, self.lots, limit_price=price)
            ctx.sell(self.code, self.lots, limit_price=price)
            ctx.note(f'round trip {self.lots} {self.code} inside one session',
                     price=price)


class CallAndCure(_Recorder):
    """Take a position that gets called, then answer the call in cash.

    Answering it is an explicit transfer from the securities pool, because
    there is no auto-transfer in Vietnam and the two pools are segregated. It
    is the *timing* of that transfer against ``cure_by`` that this scenario
    is about.
    """

    name = 'call-and-cure'

    def __init__(self, code: str, entry: date, lots: int,
                 cure_on: Optional[date] = None,
                 cure_amount: Decimal = Decimal('30000000')) -> None:
        super().__init__()
        self.code, self.entry, self.lots = code, entry, lots
        self.cure_on, self.cure_amount = cure_on, cure_amount
        self.transfer: Any = None

    def on_session(self, ctx) -> None:
        if ctx.today == self.entry:
            ctx.buy(self.code, self.lots, limit_price=ctx.price(self.code))
            ctx.note(f'open {self.lots} {self.code} at a utilisation the '
                     f'window is sized to call', price=ctx.price(self.code))
        if self.cure_on is not None and ctx.today == self.cure_on:
            self.transfer = ctx.transfer(Pool.SECURITIES, Pool.DERIVATIVES,
                                         self.cure_amount)
            ctx.note('answer the call: pay into the segregated deposit',
                     amount=self.cure_amount,
                     outcome=type(self.transfer).__name__)


# --------------------------------------------------------------------------
# Reading the logs back
# --------------------------------------------------------------------------

def settlement_rows(result: ScenarioResult) -> Tuple[Any, ...]:
    """Every ``EXPIRY_SETTLED`` row of the settlement log, in order."""
    return tuple(r for r in result.logs.settlement.entries
                 if r.action is SettlementAction.EXPIRY_SETTLED)


def margin_events(result: ScenarioResult,
                  kind: Optional[EventKind] = None) -> Tuple[Any, ...]:
    """The margin events, optionally of one kind.

    ``FORCED_LIQUIDATION`` reports and does not execute
    (``detail['executed'] is False``), so a breached account stays breached
    and the event repeats at **every** mark. Count distinct sessions, not
    events.
    """
    kinds = {EventKind.MARGIN_WARNING, EventKind.MARGIN_CALL,
             EventKind.FORCED_LIQUIDATION}
    return tuple(e for e in result.logs.events
                 if e.kind in kinds and (kind is None or e.kind is kind))


def unmarked_gaps(result: ScenarioResult) -> Tuple[Tuple[date, date, int], ...]:
    """``(previous session, next session, calendar days between)``.

    The gaps are the overnights. A derivatives account is not marked, not
    called and cannot be cured inside one, so their length is the honest
    measure of how much risk "overnight holding" actually carries.
    """
    days = sorted({s.ts.date() for s in result.snapshots})
    return tuple((a, b, (b - a).days)
                 for a, b in zip(days, days[1:]) if (b - a).days > 1)


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ExpiryRun:
    """One expiry-and-roll run, with the numbers a reader will want named."""

    result: ScenarioResult
    strategy: RollAtExpiry
    settlements: Tuple[Any, ...]

    @property
    def sources(self) -> Tuple[str, ...]:
        return tuple(r.detail.get('settlement_source') for r in self.settlements)

    @property
    def substituted(self) -> Tuple[bool, ...]:
        return tuple(bool(r.detail.get('substituted'))
                     for r in self.settlements)

    def settlement_for(self, code: str) -> Optional[Any]:
        for row in self.settlements:
            if row.ticker == code:
                return row
        return None


@dataclass(frozen=True)
class OvernightPair:
    """The same market, two accounts: one flat at the close, one not."""

    holder: ScenarioResult
    holder_strategy: HoldOvernight
    day_trader: ScenarioResult
    day_trader_strategy: DayTrade
    close_day: date

    def requirement(self, *, flat: bool, phase: str = 'close') -> Decimal:
        strategy = self.day_trader_strategy if flat else self.holder_strategy
        row = strategy.at(self.close_day, phase)
        return _ZERO if row is None else row['required']


@dataclass(frozen=True)
class VariationTrail:
    """What the deposit did over a hold, and what daily VM would have done."""

    result: ScenarioResult
    strategy: HoldOvernight
    #: ``(session, close, mark-to-market move since the previous session)``.
    daily: Tuple[Tuple[date, Decimal, Decimal], ...]
    #: Deposit balance at every step, in order.
    balances: Tuple[Decimal, ...]
    #: The one movement that actually carried the whole position's P&L.
    realised_at_close_out: Decimal

    @property
    def deposit_moved_between_entry_and_close_out(self) -> bool:
        interior = self.balances[1:-1]
        return len(set(interior)) > 1

    @property
    def largest_unsettled_daily_move(self) -> Decimal:
        return max((abs(move) for _, _, move in self.daily), default=_ZERO)


@dataclass(frozen=True)
class CureOutcome:
    """One arm of :func:`run_cure_across_tet`."""

    label: str
    calendar_id: str
    result: ScenarioResult
    strategy: CallAndCure
    call_ts: Optional[datetime]
    cure_by: Optional[datetime]
    forced_ts: Optional[datetime]

    @property
    def was_forced(self) -> bool:
        return self.forced_ts is not None

    @property
    def cure_deadline_is_a_trading_day(self) -> Optional[bool]:
        if self.cure_by is None:
            return None
        return self.cure_by.date() in {s.ts.date()
                                       for s in self.result.snapshots}


@dataclass(frozen=True)
class CureRun:
    """The A/B: the same account under two trading calendars."""

    arms: Tuple[CureOutcome, ...]

    def arm(self, label: str) -> CureOutcome:
        for arm in self.arms:
            if arm.label == label:
                return arm
        raise KeyError(label)


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------

def _corpus_sessions(source: Any, window: Window) -> Window:
    if window.sessions:
        return window
    reference = window.reference_ticker or window.tickers[0]
    return window.with_sessions(
        sessions_from_source(source, reference, window.start, window.end))


def run_expiry_and_roll(*, source: Any = None, lots: int = 2,
                        initial_deposit: Any = 200_000_000) -> ExpiryRun:
    """Hold VN30F2210 into its expiry, roll half of it on the expiry day.

    Two lots are opened on 2022-10-10 at 1032.5. On **2022-10-20**, which is
    VN30F2210's last trading day, one lot is sold at 1058.0 and one lot of
    VN30F2211 is bought at 1037.2; the remaining VN30F2210 lot is left to
    settle. Both legs close at 1058.0, so the *trading* difference between
    them is zero and every difference in the logs is a difference of
    treatment:

    * the traded leg pays the exchange service fee, the VSDC clearing fee and
      the transfer tax; the settled leg pays the transfer tax **only**,
      because no source read charges either fee on a final cash settlement;
    * the traded leg leaves a ``FILLED`` row in the trade log and the settled
      leg leaves an ``EXPIRY_SETTLED`` row in the settlement log, with the
      price's provenance on it.

    The VN30F2211 lot is then carried 20 sessions to its own expiry on
    2022-11-17, which is the overnight half of the same run.
    """
    src = source if source is not None else datahub_source()
    window = _corpus_sessions(src, EXPIRY_2022)
    session = build_session(
        start=window.start, end=window.end, venues=['HNXDS'], source=src,
        initial_deposit=initial_deposit, fill_policy='soft')
    strategy = RollAtExpiry(front='VN30F2210', back='VN30F2211',
                            entry=date(2022, 10, 10), roll=date(2022, 10, 20),
                            lots=lots)
    result = run_scenario(Scenario(
        name=window.name, window=window, session=session, strategy=strategy,
        source=src,
        note='The last trading day must still be tradable, and a contract '
             'carried into settlement must still be taxed.'))
    return ExpiryRun(result=result, strategy=strategy,
                     settlements=settlement_rows(result))


def run_expiry_under_hard_fills(*, source: Any = None, lots: int = 2,
                                initial_deposit: Any = 200_000_000
                                ) -> ExpiryRun:
    """The same scenario under ``hard``, which is the calibration for all of it.

    Every other run in this module uses ``soft``, and ``soft`` is the
    optimistic bound: it fills in full whenever the bar's only price is at or
    through the limit, with no queue position and no volume test. That is a
    **model output**, not an observation, and on a daily corpus with no high,
    no low and no volume it is the *only* way to get a fill at all.

    This run proves that. Under ``hard`` the identical strategy on the
    identical window produces **zero fills, zero positions and zero expiry
    settlements**: three orders go INDETERMINATE and are then swept EXPIRED at
    the close, and the whole expiry-and-roll question becomes unanswerable
    from the data. ``indeterminate_report().by_field`` comes back **empty**
    while doing it -- the continuous-touch refusal names no ``DataField``
    (FEATURES.md, harness finding 13) -- so a caller asking *which* data was
    missing gets nothing.

    Read this before quoting any number from the other runs.
    """
    src = source if source is not None else datahub_source()
    window = _corpus_sessions(src, EXPIRY_2022)
    session = build_session(
        start=window.start, end=window.end, venues=['HNXDS'], source=src,
        initial_deposit=initial_deposit, fill_policy='hard')
    strategy = RollAtExpiry(front='VN30F2210', back='VN30F2211',
                            entry=date(2022, 10, 10), roll=date(2022, 10, 20),
                            lots=lots)
    result = run_scenario(Scenario(
        name=f'{window.name}:hard', window=window, session=session,
        strategy=strategy, source=src,
        note='The comparison arm. Nothing fills; that is the finding.'))
    return ExpiryRun(result=result, strategy=strategy,
                     settlements=settlement_rows(result))


def run_overnight_across_tet(*, source: Any = None, lots: int = 6,
                             initial_deposit: Any = 100_000_000) -> ExpiryRun:
    """Carry VN30F2102 across the Tet 2021 closure and into its expiry.

    The position is opened on 2021-02-05 at 1139.9 and never touched again.
    What the run measures:

    * the market is marked on 2021-02-09 and not again until **2021-02-17** --
      **eight calendar days with no mark, no call and no way to cure**;
    * the front month gaps 1130.3 -> 1176.6 across it, **+46.3 points**, which
      at 100,000 VND a point is 4,630,000 VND a contract arriving in a single
      mark;
    * six lots at this size go to ``FORCED`` on 2021-02-08 and stay in breach
      for the rest of the window, and **the deposit balance does not move by
      one dong** while they do.

    A second, unlooked-for finding is recorded rather than worked around: the
    corpus publishes ``ceiling < floor`` for VN30F2102 on **2021-02-08** and
    **2021-02-09** (1060.2/1219.6 and 1015.6/1168.4), so every order on the
    two sessions either side of the break is refused on ``band_limit``. That
    is the swapped-band defect, and it reaches the futures rows too.
    """
    src = source if source is not None else datahub_source()
    window = _corpus_sessions(src, TET_2021)
    session = build_session(
        start=window.start, end=window.end, venues=['HNXDS'], source=src,
        initial_deposit=initial_deposit, fill_policy='soft')
    strategy = HoldOvernight('VN30F2102', date(2021, 2, 5), lots)
    result = run_scenario(Scenario(
        name=window.name, window=window, session=session, strategy=strategy,
        source=src,
        note='Overnight holding across the longest unmarked gap in the '
             'corpus, into an expiry two sessions after the reopen.'))
    return ExpiryRun(result=result, strategy=strategy,
                     settlements=settlement_rows(result))


def run_flat_versus_overnight(*, source: Any = None, lots: int = 2,
                              initial_deposit: Any = 100_000_000
                              ) -> OvernightPair:
    """Two accounts, one market: is the overnight requirement a different one?

    Per finding F-1 the **overnight** requirement is meant to be the scenario
    grid and the **intraday** ladder ``IM + VM``. What this measures is what
    the session actually does:

    * an account flat at 14:45 carries **no** requirement over the close, and
      an account holding two lots carries one -- so the two are different, but
      only because one of them has a position;
    * the holder's requirement at 14:45 is produced by the *same* call, on the
      *same* basis, as its requirement at 09:30. There is no post-close
      recomputation, no underlying-close basis, and no scenario-grid term. The
      one user-facing margin number is the intraday one at every instant.

    ``broker_profile.MarginModel.SCENARIO_GRID`` and ``MarginLayer.OVERNIGHT``
    exist and name ``scenario_margin`` as their engine; no module under
    ``session/`` imports it, and ``RuleSet.margin_model()`` -- the rulebook's
    own answer to "which model applies here" -- has no caller either. See
    :func:`run_post_krx_margin_model` for what that costs after the cutover.
    """
    src = source if source is not None else datahub_source()
    window = _corpus_sessions(src, OVERNIGHT_2022)
    entry = window.sessions[0]
    holder = HoldOvernight('VN30F2211', entry, lots)
    day_trader = DayTrade('VN30F2211', entry, lots)
    runs: List[ScenarioResult] = []
    for strategy in (holder, day_trader):
        session = build_session(
            start=window.start, end=window.end, venues=['HNXDS'], source=src,
            initial_deposit=initial_deposit, fill_policy='soft')
        runs.append(run_scenario(Scenario(
            name=f'{window.name}:{strategy.name}', window=window,
            session=session, strategy=strategy, source=src)))
    return OvernightPair(holder=runs[0], holder_strategy=holder,
                         day_trader=runs[1], day_trader_strategy=day_trader,
                         close_day=entry)


def run_variation_settlement_trail(*, source: Any = None, lots: int = 1,
                                   initial_deposit: Any = 200_000_000
                                   ) -> VariationTrail:
    """Does the daily variation margin settle in cash each day? Measure it.

    One VN30F2211 lot is bought on 2022-10-21 and carried to its expiry on
    2022-11-17 -- 20 sessions, a peak-to-trough of 90 index points, and a
    close-to-close move on 2022-11-16 alone of **+62.6 points = 6,260,000
    VND**. What ``deposit_balance`` does over those 20 sessions is the answer.

    The two designs this distinguishes:

    * **T+1 cash settlement**, which is what VSDC does (Phu luc 7 section C.I:
      report by 16h50, cash on T+1) and what every Vietnamese broker's
      statement shows -- the balance moves every session by the day's mark;
    * **carry the loss in the requirement**, which is what
      ``DerivativesAccount`` declares in its own class docstring ("the deposit
      does not accumulate mark-to-market ... Tier 1 does not model" the T+1
      leg) and what ``settle_daily`` having no session call site produces
      (FEATURES.md D1, A60).

    Under the second, ``VM`` is the **cumulative since-entry** loss rather
    than the day's, because ``variation_reference`` never advances past
    ``average_entry``. The two are internally consistent -- an account that
    never pays must carry the whole loss in ``MR`` -- but they are not the
    same account statement, and the difference is this scenario's output.
    """
    src = source if source is not None else datahub_source()
    window = replace(EXPIRY_2022, name='variation-trail-2022',
                     start=date(2022, 10, 21), end=date(2022, 11, 18),
                     tickers=('VN30F2211',), reference_ticker='VN30F2211',
                     sessions=())
    window = _corpus_sessions(src, window)
    session = build_session(
        start=window.start, end=window.end, venues=['HNXDS'], source=src,
        initial_deposit=initial_deposit, fill_policy='soft')
    strategy = HoldOvernight('VN30F2211', window.sessions[0], lots)
    result = run_scenario(Scenario(
        name=window.name, window=window, session=session, strategy=strategy,
        source=src,
        note='The deposit balance over a 20-session hold is the whole test.'))

    closes: List[Tuple[date, Decimal]] = []
    for day in window.sessions:
        state = src.state_at('VN30F2211', datetime.combine(day, time(9, 30)))
        if state is not None and state.last is not None:
            closes.append((day, state.last))
    daily: List[Tuple[date, Decimal, Decimal]] = []
    for (_, previous), (day, close) in zip(closes, closes[1:]):
        daily.append((day, close,
                      Decimal(lots) * VN30F_MULTIPLIER * (close - previous)))

    settled = settlement_rows(result)
    realised = settled[0].amount if settled else _ZERO
    return VariationTrail(
        result=result, strategy=strategy, daily=tuple(daily),
        balances=tuple(s.deposit_balance for s in result.snapshots),
        realised_at_close_out=realised)


def run_cure_across_tet(*, source: Any = None, lots: int = 5,
                        initial_cash: Any = 50_000_000,
                        initial_deposit: Any = 100_000_000,
                        cure_amount: Decimal = Decimal('30000000'),
                        open_time: time = time(8, 0)) -> CureRun:
    """A margin call raised at the close of the last session before Tet.

    Five VN30F2202 lots are opened on **2022-01-28** at 1528.0 against a
    100,000,000 deposit. The mark at that session's close puts utilisation at
    0.99395, which is the call rung, and the cure deadline is the **next
    session's open**. Then the market shuts for Tet and reopens on
    **2022-02-07**, and on that session the trader pays 30,000,000 into the
    segregated deposit -- the only way a Vietnamese margin call is ever
    answered, since there is no auto-transfer between the two pools.

    Both arms trade identically. They differ only in the trading calendar the
    session was built with:

    =========================  ================  =========================
    calendar                   ``cure_by``       outcome
    =========================  ================  =========================
    ``weekday-only`` (shipped) 2022-01-31 08:45  the deadline is the first
                                                 day of the Tet closure; the
                                                 account is force-closed at
                                                 the first mark after the
                                                 reopen, **and the payment
                                                 arrives too late**
    measured                   2022-02-07 08:45  the deadline is the reopen;
                                                 the payment cures the call
                                                 and no forced liquidation is
                                                 ever emitted
    =========================  ================  =========================

    ``open_time`` is 08:00 rather than the runner's 09:30 default on purpose,
    and the reason is itself a finding: ``cure_by`` is the next session's
    *open* (HNXDS 08:45), while the documented two-advance loop puts the
    caller's first decision point at 09:30. Under that loop the escalation to
    ``FORCED`` happens on the advance **before** ``on_session`` is called, so
    a margin call cannot be cured at all -- not because the state machine is
    wrong, but because the deadline lands between the two advances. Pass
    ``open_time=time(9, 30)`` to reproduce that.
    """
    src = source if source is not None else datahub_source()
    window = _corpus_sessions(src, TET_2022)
    reopen = date(2022, 2, 7)
    arms: List[CureOutcome] = []
    for label, calendar in (
            ('weekday-only', None),
            ('measured', measured_trading_calendar(2022, TET_2022_CLOSURE))):
        session = build_session(
            start=window.start, end=window.end, venues=['HSX', 'HNXDS'],
            source=src, initial_cash=initial_cash,
            initial_deposit=initial_deposit, fill_policy='soft',
            trading=calendar)
        strategy = CallAndCure('VN30F2202', date(2022, 1, 28), lots,
                               cure_on=reopen, cure_amount=cure_amount)
        result = run_scenario(Scenario(
            name=f'{window.name}:{label}', window=window, session=session,
            strategy=strategy, source=src, open_time=open_time,
            note='The same account under two trading calendars.'))
        calls = margin_events(result, EventKind.MARGIN_CALL)
        forced = margin_events(result, EventKind.FORCED_LIQUIDATION)
        arms.append(CureOutcome(
            label=label,
            calendar_id=getattr(calendar, 'calendar_id',
                                'weekday-only-UNSOURCED'),
            result=result, strategy=strategy,
            call_ts=calls[0].ts if calls else None,
            cure_by=calls[0].detail.get('cure_by') if calls else None,
            forced_ts=forced[0].ts if forced else None))
    return CureRun(arms=tuple(arms))


def run_post_krx_margin_model(*, lots: int = 2,
                              initial_deposit: Any = 200_000_000
                              ) -> Tuple[ScenarioResult, HoldOvernight,
                                         Optional[str], Optional[Exception]]:
    """What margin does an overnight position face **after** the KRX cutover?

    ``rulebook.margin_model()`` is the repository's own answer to that
    question and at any date from 2025-05-05 it **raises**::

        margin_model@2026-03-09T09:30:00 is unknown: POST-KRX VALUE NOT
        SOURCED.

    The rulebook is right to raise: QD 26's Phu luc 2 is the scenario grid,
    the requirement is computed once after the close on the *underlying's*
    close, and Phu luc 2's parameter table is unpublished. What this run
    measures is that **the session never asks**. A VN30F2603 position carried
    through the 2026-03-09 limit-down is margined by ``IM + VM`` at 0.17 --
    the pre-KRX broker formula, applied 10 months past the cutover -- and
    nothing raises, nothing is flagged, and ``indeterminate_report`` counts
    zero.

    Returns ``(result, strategy, margin_model, raised)`` where
    ``margin_model`` is the rulebook's answer if it has one and ``raised`` is
    the exception it produced if it does not.
    """
    days = POST_KRX_2026.sessions
    closes = {day: Decimal(price)
              for day, price in zip(days, POST_KRX_CLOSES)}
    src = _FuturesMarket(ticker='VN30F2603', closes=closes,
                         expiry=date(2026, 3, 19))
    session = build_session(
        start=POST_KRX_2026.start, end=POST_KRX_2026.end, venues=['HNXDS'],
        source=src, initial_deposit=initial_deposit, fill_policy='soft')
    strategy = HoldOvernight('VN30F2603', days[0], lots)
    result = run_scenario(Scenario(
        name=POST_KRX_2026.name, window=POST_KRX_2026, session=session,
        strategy=strategy, source=src,
        note='The rulebook refuses to state the post-KRX margin model; the '
             'session applies the pre-KRX one anyway.'))

    model: Optional[str] = None
    raised: Optional[Exception] = None
    try:
        model = session._rulebook.at(
            datetime.combine(days[-2], time(9, 30))).margin_model()
    except UnresolvedRule as exc:
        raised = exc
    return result, strategy, model, raised
