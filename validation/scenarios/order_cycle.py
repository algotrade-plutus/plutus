"""ORDER LIFECYCLE, exhaustively: every Vietnamese order type, every terminal edge.

The claim under test is locked shape 4 -- **the order type is the
time-in-force** -- and it is tested by driving real orders through the
assembled ``ExchangeSession`` over real corpus days and reading the terminal
edge back out of the trade log:

=========  =================  ==============================================
type       time-in-force      terminal edges this module reaches
=========  =================  ==============================================
LO         ``day``            filled, partially filled, cancelled,
                              expired ``session_end``, rejected
ATO        ``auction_only``   filled at the opening cross,
                              expired ``auction_cross``
ATC        ``auction_only``   filled at the closing cross,
                              expired ``auction_cross``
MOK        ``fill_or_kill``   filled in full, expired
                              ``not_fillable_in_full``
MAK        ``immediate_or_``  partially filled then expired
           ``cancel``         ``immediate_remainder``
MTL / MP   ``immediate_``     partially filled then **residue converted** to
           ``then_day``       a resting limit, then expired ``session_end``
=========  =================  ==============================================

and the admission refusals: off-tick, odd lot, above the ceiling, below the
floor, marketable into a locked band, the wrong type for the phase, an order
larger than the venue's cap, an unfunded order, and a sale of shares that have
not settled.

Why this scenario runs at ``Resolution.TICK`` over daily bars
-------------------------------------------------------------
``DataHubSource`` stamps every state ``SessionPhase.CONTINUOUS``, which is
right for a daily clock and makes **both call auctions unreachable**: HOSE
accepts ``{LO, ATO}`` only in ``OPENING_AUCTION`` and ``{LO, ATC}`` only in
``CLOSING_AUCTION`` (``rulebook._order_type_table``), so on a daily run every
ATO and every ATC is refused ``SESSION_SEMANTICS`` before it can have a
lifecycle at all. Two of the six order types would be untestable.

So the session is configured at ``Resolution.TICK``, which makes
``ExchangeSession._phase`` resolve the phase from ``RuleSet.session_schedule``
-- the sourced session table -- and the clock is stepped to instants inside
each phase. The market data is still the daily bar; see
:mod:`validation.scenarios.bars` for exactly what each phase is served and
what is deliberately withheld.

Why several small runs and not one long one
-------------------------------------------
``Scenario`` carries ``open_time`` and ``close_time``, and the runner takes
exactly two advances per session. An ATO can only fill if an advance lands
inside 09:00-09:15 **after** it was submitted, because ``advance_to`` expires
at boundaries before it evaluates fills -- so proving an ATO fills needs a
09:05/09:10 pair, and proving an ATC fills needs 14:35/14:40. One clock cannot
do both. Each leg therefore states its own two instants, which is what the
author asked for: "each scenario can have their own time frame".

Where a leg needs a third touch point in one day -- cancelling an order that
has already partially filled -- it chains a second ``run_scenario`` over the
**same session object** at later instants. The session clock is monotone and
carries state across the two calls; the logs do not, which is why the leg
asserts on the second call's log.

What this scenario found
------------------------
Recorded here because a green test file hides it. Each has a test that pins
the behaviour as it is, so a later fix breaks the test rather than passing
unnoticed.

1. **The shipped adapter drops four columns the corpus holds**, and the
   consequence is that ``HardFillPolicy`` cannot decide a fill it has the
   evidence for. Measured by :func:`adapter_gap`; explained in
   :mod:`validation.scenarios.bars`.
2. **The daily lock proxy over-asserts a lock by about ten to one.**
   ``close == ceiling`` is called a locked book; over HSX stocks in 2022 only
   9.8% of those ticker-days have ``open == high == low == close``, and on the
   rest the day's low is on average 6.87% below the ceiling. Measured by
   :func:`lock_proxy_divergence`.
3. **No shipped fill policy can decide an MTL, MOK or MAK** on any corpus in
   this repository, so three terminal edges the session implements have no
   reachable path end to end. See :class:`DepthProxyFillPolicy`.
4. **``ExpiryTrigger.INSTRUMENT_EXPIRY`` is declared and never produced.**
5. **``orders.py`` and ``calendar.py`` disagree about when an HNX day order
   dies** -- the trigger follows one and the timestamp the other.
6. **A definite ``NO_FILL`` leaves no row in any log**, so "why did my order
   not fill" cannot be answered from the three logs.
7. **``indeterminate_report()`` counts fills, margin marks and expiry
   settlements in one denominator** while its docstring says it counts only
   the first, which makes the published rate a function of how often the
   caller sampled the clock.
8. **A cancellation is written to the trade log twice** (harness, not
   session), with the filled quantity on one row and the cancelled quantity
   on the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from typing import (Any, Callable, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

from plutus.core.order import OrderType
from plutus.market.protocol import Resolution
from plutus.market.session.fills import HardFillPolicy
from plutus.market.session.rulebook import VenueListing
from plutus.market.session.types import DataField, FillEvidence, Venue

from validation.corpus import corpus_root
from validation.logs import TradeAction
from validation.runner import (
    Scenario, ScenarioResult, Window, build_session, run_scenario,
)
from validation.scenarios.bars import CorpusBars, PhasedBarSource
from validation.strategy import BaseStrategy

__all__ = [
    'WINDOW_START', 'WINDOW_END', 'SESSIONS', 'TICKERS', 'VENUES', 'LISTINGS',
    'DepthProxyFillPolicy', 'Leg', 'ScriptedStrategy', 'Step',
    'build_source', 'legs', 'run_leg', 'run_all',
    'partial_fill_then_cancel', 'combined_identities', 'adapter_gap',
    'lock_proxy_divergence',
    'terminal_rows', 'unterminated', 'rejections', 'expiries', 'fills',
    'partials',
]

_ZERO = Decimal('0')


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------
#
# 2022-11-08 .. 2022-11-18, all four venues. Nine consecutive trading sessions
# with no Vietnamese holiday inside them, so the unsourced weekday-only
# settlement calendar the session defaults to is **not** wrong here -- which
# matters, because this scenario asserts a settlement date and a scenario that
# asserted one across Tet would be asserting the default's bug.
#
# What the window carries, all verified against the corpus:
#
#   HPG (HSX)  liquid: 21.5m-99.7m shares a session, a 12.10 low on 11-10 and
#              a 15.10 close on 11-18, and four sessions closing exactly at
#              the ceiling. The name every fill leg trades.
#   NVL (HSX)  floor-locked with open == high == low == close == floor on
#              every session from 11-04 to 11-21. The band-lock refusal.
#   HPX (HSX)  floor-locked on the same days on 100-900 shares a session. The
#              participation cap below one round lot.
#   PVS (HNX)  liquid, and HNX is the only equity venue that accepts MOK and
#              MAK at any date. The immediate-family legs.
#   TDW (HSX)  no ``quote_dailyvolume`` row at all on any of these days: it
#              did not trade. The INDETERMINATE leg.
#   BSR (UPCoM) +/-15% band on a 0.1 tick, and UPCoM accepts an LO and
#              nothing else at any date or phase.
#   VN30F2211  the front future, last trading day 2022-11-17. The derivatives
#   (HNXDS)    pool and the instrument-expiry edge.

WINDOW_START = date(2022, 11, 8)
WINDOW_END = date(2022, 11, 18)

#: The nine sessions, as the corpus carries them. Stated rather than derived
#: so a leg can name a day directly and a missing corpus row is a test failure
#: instead of a silently shorter run.
SESSIONS: Tuple[date, ...] = (
    date(2022, 11, 8), date(2022, 11, 9), date(2022, 11, 10),
    date(2022, 11, 11), date(2022, 11, 14), date(2022, 11, 15),
    date(2022, 11, 16), date(2022, 11, 17), date(2022, 11, 18),
)

TICKERS: Tuple[str, ...] = ('HPG', 'NVL', 'HPX', 'PVS', 'TDW', 'BSR',
                            'VN30F2211')

VENUES: Mapping[str, Venue] = {
    'HPG': Venue.HSX, 'NVL': Venue.HSX, 'HPX': Venue.HSX, 'TDW': Venue.HSX,
    'PVS': Venue.HNX, 'BSR': Venue.UPCOM, 'VN30F2211': Venue.HNXDS,
}

#: Dated listings, passed to the session so ``SymbolRouter`` resolves the
#: venue from these rather than from the corpus's ``quote_ticker.exchangeid``
#: -- which holds each ticker's *current* venue and would assign the wrong
#: band, tick and lot to any name that has since transferred.
LISTINGS: Tuple[VenueListing, ...] = tuple(
    VenueListing(ticker, venue, date(2020, 1, 1))
    for ticker, venue in VENUES.items())

#: VN30F2211's last trading day, the third Thursday of November 2022,
#: confirmed as its last ``quote_close`` row in the corpus.
F_EXPIRY = date(2022, 11, 17)

_BARS: Optional[CorpusBars] = None


def build_source() -> PhasedBarSource:
    """The corpus source for this window. Bars are loaded once per process."""
    global _BARS
    root = corpus_root()
    if root is None:
        raise FileNotFoundError(
            'no daily corpus found; set PLUTUS_DATA_ROOT')
    if _BARS is None:
        _BARS = CorpusBars(str(root), TICKERS, WINDOW_START, WINDOW_END)
    return PhasedBarSource(_BARS, VENUES, expiries={'VN30F2211': F_EXPIRY})


# --------------------------------------------------------------------------
# The fill policy that makes the market family reachable
# --------------------------------------------------------------------------

class DepthProxyFillPolicy(HardFillPolicy):
    """``hard``, except that a market-family order is sized from volume.

    **This is a harness instrument and it must not be read as a shipped
    model.** It exists because of a finding, and the finding is the point:

    *No shipped fill policy can produce a definite decision for an MTL, MOK or
    MAK on any corpus in this repository.* ``HardFillPolicy._continuous`` and
    ``ProbabilisticFillPolicy._continuous`` both route an order with no limit
    price to ``_market_family_undecidable``, which returns ``INDETERMINATE``
    naming ``DataField.BOOK`` -- correctly, because how far a market order
    walks is a function of depth and ``BookLevel.size`` is ``None`` on both
    shipped adapters. ``SoftFillPolicy`` answers, but with
    ``max_participation`` unset it fills the whole order at the point price
    and therefore never partially fills anything.

    The consequence is that three terminal edges the session implements have
    no reachable path end to end:

    * ``ExpiryTrigger.NOT_FILLABLE_IN_FULL`` *by the cap* -- the
      all-or-nothing branch in ``_CappedFillPolicy._sized_fill``;
    * ``ExpiryTrigger.IMMEDIATE_REMAINDER`` *after a partial fill*;
    * ``OrderBookOfRecord.convert_residue`` and
      ``ExchangeSession._residual_price`` -- the gazetted MTL residue rule
      (VNX QD 22/2025 Dieu 17.2(b)) -- which needs an MTL in
      ``PARTIALLY_FILLED`` or ``ACCEPTED`` *and* a definite decision.

    So this policy changes exactly one answer: a market-family order in the
    continuous session is treated as having reached the last matched price,
    and is then sized by the **shipped** ``_sized_fill`` -- the same
    participation cap, the same round-lot floor, the same fill-or-kill
    all-or-nothing rule. Everything else, including every limit-priced
    decision and every auction decision, is ``HardFillPolicy`` verbatim.

    The assumption it adds, stated so no result can quote this policy without
    it: **a market order transacts at the last matched price for as much as
    the participation cap allows.** That is a depth assumption standing in for
    the depth the corpus does not carry. It is optimistic on price -- a real
    market order walks *through* the touch and pays worse -- and it is
    deliberately not calibrated, because there is nothing here to calibrate it
    against.
    """

    kind = 'depth-proxy'

    @property
    def signature(self) -> str:
        return (f'{self.kind}(max_participation={self.max_participation};'
                f'market-family priced at last match, sized by the cap)')

    @property
    def assumptions(self) -> Tuple[str, ...]:
        return super().assumptions + (
            'Market family (MTL/MOK/MAK): assumed to transact at the last '
            'matched price for as much as the participation cap allows. A '
            'depth assumption standing in for depth the corpus does not '
            'carry; harness instrument, not a shipped model.',
        )

    def _continuous(self, order, interval, rules, *, already_filled,
                    instrument):
        if order.order.limit_price is not None:
            return super()._continuous(order, interval, rules,
                                       already_filled=already_filled,
                                       instrument=instrument)
        price = interval.close
        if price is None:
            price = interval.state.last
        if price is None:
            from plutus.market.session.types import FillDecision
            return FillDecision.indeterminate(
                'a market-family order needs a matched price to stand in for '
                'the depth it would walk, and this interval carries none',
                [DataField.CLOSE, DataField.LAST])
        return self._sized_fill(order, interval, rules, price,
                                FillEvidence.MODELLED,
                                already_filled=already_filled,
                                instrument=instrument)


# --------------------------------------------------------------------------
# A scripted strategy
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    """One instruction, on one session, for :class:`ScriptedStrategy`.

    ``do`` receives the :class:`~validation.strategy.StrategyContext` and may
    do anything a strategy may do. It is a callable rather than a declarative
    order so a step can read state back -- cancel the order it just placed,
    check what settled -- which is what a lifecycle test is made of.
    """

    day: date
    do: Callable[[Any], None]
    note: Optional[str] = None


class ScriptedStrategy(BaseStrategy):
    """Runs :class:`Step` instructions on the sessions that name them.

    A trading algorithm in the sense this harness means: it owns no P&L, reads
    everything back off the exchange, and its only outputs are submissions and
    cancellations.
    """

    def __init__(self, name: str, steps: Sequence[Step]) -> None:
        self.name = name
        self._steps = tuple(steps)
        self.results: Dict[str, Any] = {}

    def on_session(self, ctx) -> None:
        for step in self._steps:
            if step.day != ctx.today:
                continue
            if step.note:
                ctx.note(step.note, day=step.day.isoformat())
            step.do(ctx)


# --------------------------------------------------------------------------
# Running a leg
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Leg:
    """One lifecycle question, with the clock it needs to be asked at."""

    name: str
    steps: Tuple[Step, ...]
    open_time: time
    close_time: time
    sessions: Tuple[date, ...]
    policy: str = 'hard'
    policy_object: Any = None
    initial_cash: str = '200000000000'
    initial_deposit: str = '0'
    opening_holdings: Mapping[str, int] = field(default_factory=dict)
    tickers: Tuple[str, ...] = TICKERS
    max_participation: str = '0.10'
    note: Optional[str] = None


def run_leg(leg: Leg, *, source: Optional[PhasedBarSource] = None,
            session: Any = None) -> Tuple[ScenarioResult, Any]:
    """Run one leg and return its result **and the session it ran on**.

    The session is returned so a leg needing a third instant in one day can
    chain a second run over the same clock; see the module docstring.
    """
    src = source or build_source()
    if session is None:
        session = build_session(
            start=leg.sessions[0], end=leg.sessions[-1],
            venues=['HSX', 'HNX', 'UPCOM', 'HNXDS'], source=src,
            initial_cash=leg.initial_cash,
            initial_deposit=leg.initial_deposit,
            fill_policy=leg.policy, max_participation=leg.max_participation,
            resolution=Resolution.TICK, listings=LISTINGS,
            initial_holdings=dict(leg.opening_holdings) or None,
            fill_policy_object=leg.policy_object)
    window = Window(name=leg.name, start=leg.sessions[0],
                    end=leg.sessions[-1], tickers=leg.tickers,
                    sessions=leg.sessions, note=leg.note)
    scenario = Scenario(
        name=leg.name, window=window, session=session,
        strategy=ScriptedStrategy(leg.name, leg.steps), source=src,
        opening_holdings=dict(leg.opening_holdings),
        open_time=leg.open_time, close_time=leg.close_time, note=leg.note)
    return run_scenario(scenario, raise_on_error=True), session


# --------------------------------------------------------------------------
# Reading the log back
# --------------------------------------------------------------------------

def _rows(result: ScenarioResult, action: TradeAction) -> Tuple[Any, ...]:
    return tuple(e for e in result.logs.trades if e.action is action)


def rejections(result: ScenarioResult) -> Tuple[Any, ...]:
    return _rows(result, TradeAction.REJECTED)


def fills(result: ScenarioResult) -> Tuple[Any, ...]:
    return _rows(result, TradeAction.FILLED)


def partials(result: ScenarioResult) -> Tuple[Any, ...]:
    return _rows(result, TradeAction.PARTIALLY_FILLED)


def expiries(result: ScenarioResult) -> Tuple[Any, ...]:
    return _rows(result, TradeAction.EXPIRED)


_TERMINAL = frozenset({TradeAction.FILLED, TradeAction.CANCELLED,
                       TradeAction.EXPIRED, TradeAction.REJECTED})


def terminal_rows(result: ScenarioResult) -> Dict[str, Any]:
    """``{order_id: the row that ended it}``.

    The lifecycle assertion every leg makes: **every accepted order reaches
    exactly one terminal row**. An order that is still live at the end of a
    run holds a reservation for ever, which is the leak section 12 invariant 4
    exists to catch.
    """
    out: Dict[str, Any] = {}
    for entry in result.logs.trades:
        if entry.action in _TERMINAL and entry.order_id:
            out[entry.order_id] = entry
    return out


def unterminated(result: ScenarioResult) -> Tuple[str, ...]:
    """Order ids accepted by the exchange that never reached a terminal row."""
    accepted = {e.order_id for e in result.logs.trades
                if e.action is TradeAction.ACCEPTED and e.order_id}
    return tuple(sorted(accepted - set(terminal_rows(result))))


# --------------------------------------------------------------------------
# The legs
# --------------------------------------------------------------------------
#
# Prices below are corpus values, quoted in the corpus's units (thousand VND
# a share for equities, index points for the future). They are named as
# constants so a reader can check each against the table in the module
# docstring instead of decoding a literal in a lambda.

HPG_08 = dict(open=Decimal('13.10'), high=Decimal('13.70'),
              low=Decimal('13.00'), close=Decimal('13.15'),
              volume=46_273_800, ceiling=Decimal('14.65'),
              floor=Decimal('12.75'))
HPG_09 = dict(open=Decimal('13.20'), high=Decimal('13.60'),
              low=Decimal('12.95'), close=Decimal('13.00'),
              volume=32_786_100, ceiling=Decimal('14.05'),
              floor=Decimal('12.25'))
NVL_14 = dict(close=Decimal('38.95'), floor=Decimal('38.95'),
              ceiling=Decimal('44.75'), volume=29_300)
PVS_08 = dict(close=Decimal('23.0'), volume=7_652_900,
              ceiling=Decimal('23.7'), floor=Decimal('19.5'))

HPX_10 = dict(open=Decimal('21.15'), high=Decimal('21.50'),
              low=Decimal('21.15'), close=Decimal('21.50'),
              volume=650_600, ceiling=Decimal('24.25'),
              floor=Decimal('21.15'))
HPX_14 = dict(open=Decimal('18.60'), high=Decimal('18.60'),
              low=Decimal('18.60'), close=Decimal('18.60'),
              volume=100, ceiling=Decimal('21.40'), floor=Decimal('18.60'))
F_17 = dict(open=Decimal('953.0'), high=Decimal('973.8'),
            low=Decimal('950.2'), close=Decimal('972.5'), volume=291_529,
            ceiling=Decimal('1024.6'), floor=Decimal('890.6'))

DAY1, DAY2, DAY3 = SESSIONS[0], SESSIONS[1], SESSIONS[2]
DAY4, DAY5 = SESSIONS[3], SESSIONS[4]
DAY6, DAY7, DAY8, DAY9 = SESSIONS[5], SESSIONS[6], SESSIONS[7], SESSIONS[8]


def _buy(ticker, qty, price=None, order_type=OrderType.LIMIT):
    def do(ctx):
        ctx.buy(ticker, qty, limit_price=price, order_type=order_type)
    return do


def _sell(ticker, qty, price=None, order_type=OrderType.LIMIT):
    def do(ctx):
        ctx.sell(ticker, qty, limit_price=price, order_type=order_type)
    return do


def _buy_foreign(ticker, qty, price):
    def do(ctx):
        ctx.buy(ticker, qty, limit_price=price, is_foreign=True)
    return do


def _submit_then_cancel(ticker, qty, price):
    def do(ctx):
        outcome = ctx.buy(ticker, qty, limit_price=price)
        order_id = getattr(outcome, 'order_id', None)
        if order_id is not None:
            ctx.cancel(order_id)
    return do


def _submit_then(ticker, qty, price, then):
    """Submit, then run ``then(ctx, order_id)`` on the order just accepted."""
    def do(ctx):
        outcome = ctx.buy(ticker, qty, limit_price=price)
        order_id = getattr(outcome, 'order_id', None)
        if order_id is not None:
            then(ctx, order_id)
    return do


def _cancel_every_live(ctx) -> None:
    for record in ctx.live_orders():
        ctx.cancel(record.order_id)


def legs() -> Tuple[Leg, ...]:
    """Every lifecycle leg, in the order the report reads them."""
    cont = (time(9, 20), time(9, 25))
    ato = (time(9, 5), time(9, 10))
    atc = (time(14, 35), time(14, 40))

    return (
        # -- LO: the four terminal edges of a day order ------------------
        Leg(name='lo-filled',
            steps=(Step(DAY2, _buy('HPG', 1000, Decimal('13.50')),
                        'buy above the day low of 12.95: traded through'),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2, DAY3),
            note='a day LO that the market demonstrably traded through'),

        Leg(name='lo-expired-session-end',
            steps=(Step(DAY2, _buy('HPG', 1000, Decimal('12.30')),
                        'buy below the day low of 12.95: never reached'),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2, DAY3),
            note='a day LO the market never reached dies at the close'),

        Leg(name='lo-cancelled',
            steps=(Step(DAY2, _submit_then_cancel('HPG', 1000,
                                                  Decimal('12.30')),
                        'cancel in the continuous session'),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2, DAY3),
            note='cancellation is admitted in the continuous session'),

        # -- the auction lock: a cancel that must be refused --------------
        Leg(name='cancel-refused-in-auction',
            steps=(Step(DAY2, _submit_then_cancel('HPG', 1000,
                                                  Decimal('12.30')),
                        'cancel inside the closing call auction'),),
            open_time=atc[0], close_time=atc[1],
            sessions=(DAY1, DAY2, DAY3),
            note='the closing auction is locked for its whole duration'),

        # -- ATO ----------------------------------------------------------
        Leg(name='ato-filled-at-open',
            steps=(Step(DAY1, _buy('HPG', 1000,
                                   order_type=OrderType.AT_THE_OPENING)),),
            open_time=ato[0], close_time=ato[1],
            sessions=(DAY1, DAY2), policy='soft',
            note='an ATO reaching its own cross fills at the published open'),

        Leg(name='ato-expired-at-cross',
            steps=(Step(DAY1, _buy('HPG', 1000,
                                   order_type=OrderType.AT_THE_OPENING)),),
            open_time=ato[0], close_time=ato[1],
            sessions=(DAY1, DAY2),
            note='an ATO that did not fill evaporates at the cross'),

        # -- ATC ----------------------------------------------------------
        Leg(name='atc-filled-at-close',
            steps=(Step(DAY1, _buy('HPG', 1000,
                                   order_type=OrderType.AT_THE_CLOSE)),),
            open_time=atc[0], close_time=atc[1],
            sessions=(DAY1, DAY2), policy='soft',
            note='an ATC reaching its own cross fills at the published close'),

        Leg(name='atc-expired-at-cross',
            steps=(Step(DAY1, _buy('HPG', 1000,
                                   order_type=OrderType.AT_THE_CLOSE)),),
            open_time=atc[0], close_time=atc[1],
            sessions=(DAY1, DAY2),
            note='an ATC that did not fill evaporates at the cross'),

        # -- the market family, on HNX, where it is legal -----------------
        Leg(name='mok-filled-in-full',
            steps=(Step(DAY1, _buy('PVS', 1000,
                                   order_type=OrderType.MARKET_FILL_OR_KILL)),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2),
            policy_object=DepthProxyFillPolicy(Decimal('0.10')),
            note='an MOK inside the cap fills in full'),

        Leg(name='mok-killed-not-fillable-in-full',
            steps=(Step(DAY1, _buy('PVS', 2_000_000,
                                   order_type=OrderType.MARKET_FILL_OR_KILL)),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2),
            policy_object=DepthProxyFillPolicy(Decimal('0.10')),
            note='an MOK the cap cannot fill in full is killed entirely'),

        Leg(name='mak-partial-then-remainder-killed',
            steps=(Step(DAY1, _buy(
                'PVS', 2_000_000,
                order_type=OrderType.MARKET_IMMEDIATE_OR_CANCEL)),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2),
            policy_object=DepthProxyFillPolicy(Decimal('0.10')),
            note='an MAK keeps what filled and kills the rest at once'),

        Leg(name='mtl-residue-converts-and-rests',
            steps=(Step(DAY1, _buy(
                'PVS', 2_000_000,
                order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT)),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2),
            policy_object=DepthProxyFillPolicy(Decimal('0.10')),
            note='an MTL residue converts to a resting limit one tick beyond '
                 'the last match, and then dies as a day order'),

        # -- admission ----------------------------------------------------
        Leg(name='admission-refusals',
            steps=(
                Step(DAY2, _buy('HPG', 1000, Decimal('13.02')),
                     'off the 0.05 tick grid'),
                Step(DAY2, _buy('HPG', 150, Decimal('13.00')),
                     'an odd lot on HOSE'),
                Step(DAY2, _buy('HPG', 1000, Decimal('14.10')),
                     'above the 14.05 ceiling'),
                Step(DAY2, _buy('HPG', 1000, Decimal('12.20')),
                     'below the 12.25 floor'),
                Step(DAY2, _buy('HPG', 600_000, Decimal('13.00')),
                     'above the 500,000 HOSE per-order cap'),
                Step(DAY2, _buy('HPG', 500_000, Decimal('13.00')),
                     'inside the cap but far beyond the cash'),
            ),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2, DAY3), initial_cash='100000000',
            note='every stateless admission rule, and the funding rule'),

        Leg(name='phase-refusals-continuous',
            steps=(
                Step(DAY2, _buy('HPG', 1000,
                                order_type=OrderType.AT_THE_OPENING),
                     'ATO in the continuous session'),
                Step(DAY2, _buy('HPG', 1000,
                                order_type=OrderType.AT_THE_CLOSE),
                     'ATC in the continuous session'),
                Step(DAY2, _buy('HPG', 1000,
                                order_type=OrderType.MARKET_FILL_OR_KILL),
                     'MOK on HOSE, which has never accepted one'),
                Step(DAY2, _buy('HPG', 1000,
                                order_type=OrderType.MARKET_IMMEDIATE_OR_CANCEL),
                     'MAK on HOSE, which has never accepted one'),
            ),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2, DAY3),
            note='the dated order-type table, refusing by phase and venue'),

        Leg(name='phase-refusals-noon',
            steps=(Step(DAY2, _buy('HPG', 1000, Decimal('13.00')),
                        'an LO during the lunch shutdown'),),
            open_time=time(12, 0), close_time=time(12, 5),
            sessions=(DAY1, DAY2, DAY3),
            note='11:30-13:00 admits nothing at any venue'),

        Leg(name='phase-refusals-pre-open',
            steps=(Step(DAY2, _buy('HPG', 1000, Decimal('13.00')),
                        'an LO before the market opens'),),
            open_time=time(8, 30), close_time=time(8, 40),
            sessions=(DAY1, DAY2, DAY3),
            note='PRE_OPEN is ADOPTED, not sourced, and admits nothing'),

        Leg(name='noon-break-expires-nothing',
            steps=(Step(DAY2, _buy('HPG', 1000, Decimal('12.30')),
                        'a resting LO must survive the lunch break'),),
            open_time=time(11, 0), close_time=time(12, 0),
            sessions=(DAY2,),
            note='the book survives 11:30-13:00; only instructions stop'),

        # -- the locked band ----------------------------------------------
        Leg(name='band-lock-refuses-the-locked-side',
            steps=(
                Step(DAY5, _sell('NVL', 1000, Decimal('38.95')),
                     'sell into a full-day floor lock'),
                Step(DAY5, _buy('NVL', 1000, Decimal('38.95')),
                     'buy at the same floor: the unlocked side'),
            ),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY4, DAY5, DAY6), opening_holdings={'NVL': 10_000},
            note='NVL 2022-11-14 traded only at its floor, all day'),

        Leg(name='participation-cap-below-one-lot',
            steps=(Step(DAY5, _buy('HPX', 1000, Decimal('18.65')),
                        'HPX traded 100 shares on 2022-11-14'),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY4, DAY5, DAY6),
            note='10% of 100 shares is below one 100-share round lot'),

        # -- no data at all -----------------------------------------------
        Leg(name='indeterminate-no-trade',
            steps=(Step(DAY2, _buy('TDW', 1000, Decimal('43.25')),
                        'TDW did not trade on any day of this window'),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2, DAY3),
            note='no matched price, so no fill claim can be made either way'),

        # -- T+2, and the 13:00 allocation cut ----------------------------
        Leg(name='settlement-t2-morning',
            steps=(
                Step(DAY1, _buy('HPG', 1000, Decimal('13.50')),
                     'buy on T'),
                Step(DAY1, _sell('HPG', 1000, Decimal('13.00')),
                     'sell the same shares on T, before the buy has filled'),
                Step(DAY2, _sell('HPG', 1000, Decimal('13.00')),
                     'sell on T+1'),
                Step(DAY3, _sell('HPG', 1000, Decimal('12.50')),
                     'sell on the MORNING of T+2, before the 13:00 cut'),
                Step(DAY4, _sell('HPG', 1000, Decimal('12.10')),
                     'sell once the shares are in the account'),
            ),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2, DAY3, DAY4, DAY5),
            note='T+2 binds three times and then releases'),

        Leg(name='settlement-t2-afternoon',
            steps=(
                Step(DAY1, _buy('HPG', 1000, Decimal('13.50')),
                     'buy on T'),
                Step(DAY3, _sell('HPG', 1000, Decimal('12.50')),
                     'sell on the AFTERNOON of T+2, after the 13:00 cut'),
            ),
            open_time=time(13, 30), close_time=time(14, 0),
            sessions=(DAY1, DAY2, DAY3, DAY4, DAY5),
            note='Decision 109: allocation no later than 13:00 on T+2, so the '
                 'same sale refused at 09:20 is admitted at 13:30'),

        # -- the derivatives pool -----------------------------------------
        Leg(name='futures-lifecycle-to-expiry',
            steps=(
                Step(DAY1, _buy('VN30F2211', 2, Decimal('960.0')),
                     'open two lots'),
                Step(DAY7, _buy('VN30F2211', 1, Decimal('900.0')),
                     'add a third'),
            ),
            open_time=cont[0], close_time=cont[1],
            sessions=SESSIONS, initial_deposit='500000000',
            note='an order routed to the segregated deposit, held to the '
                 "contract's last trading day and cash-settled"),

        Leg(name='futures-order-on-the-last-trading-day',
            steps=(Step(DAY8, _buy('VN30F2211', 1, Decimal('940.0')),
                        'a limit below the day low of 950.2, resting on a '
                        'contract that expires tonight'),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY7, DAY8, DAY9), initial_deposit='500000000',
            note='ExpiryTrigger.INSTRUMENT_EXPIRY is declared and never '
                 'produced; this leg records which trigger actually fires'),

        # -- MP: the same type under the pre-KRX mnemonic, on HOSE ---------
        Leg(name='mp-on-hose-residue-converts',
            steps=(Step(DAY5, _buy(
                'NVL', 100_000,
                order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT)),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY4, DAY5, DAY6),
            policy_object=DepthProxyFillPolicy(Decimal('0.10')),
            note='HOSE accepted no MTL before 2025-05-05 and did accept MP, '
                 'and the rulebook maps both to one OrderType. NVL traded '
                 '29,300 shares on 2022-11-14, so the cap bites at 2,900'),

        # -- UPCoM: LO and nothing else, at every date and every phase -----
        Leg(name='upcom-accepts-only-lo',
            steps=(
                Step(DAY2, _buy('BSR', 1000, Decimal('17.1')),
                     'an LO on UPCoM'),
                Step(DAY2, _buy(
                    'BSR', 1000,
                    order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT),
                    'an MP/MTL on UPCoM'),
                Step(DAY2, _buy('BSR', 1000,
                                order_type=OrderType.AT_THE_CLOSE),
                     'an ATC on UPCoM, which has no closing auction'),
            ),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2, DAY3),
            note='UPCoM: LO only, +/-15% band, 0.1 tick, no auction'),

        # -- the two refusals the securities legs cannot produce -----------
        Leg(name='futures-insufficient-deposit',
            steps=(Step(DAY1, _buy('VN30F2211', 1, Decimal('960.0')),
                        'IM is 12,480,000 and the deposit holds 1,000,000'),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2), initial_deposit='1000000',
            note='the segregated deposit refuses on its own balance'),

        Leg(name='foreign-room-is-not-in-this-corpus',
            steps=(Step(DAY2, _buy_foreign('HPG', 1000, Decimal('13.00')),
                        'a foreign buy, which room limits'),),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2, DAY3),
            note='room binds in reality; the Parquet corpus carries the room '
                 'LIMIT and not the remaining room, so the rule cannot decide'),

        # -- amendment ----------------------------------------------------
        Leg(name='amend-tier-boundaries',
            steps=(
                Step(DAY2, _submit_then(
                    'HPG', 1000, Decimal('12.30'),
                    lambda ctx, oid: ctx.amend(oid, quantity=1500)),
                    'amend up: refused, it could raise the requirement'),
                Step(DAY2, _submit_then(
                    'HPG', 1000, Decimal('12.30'),
                    lambda ctx, oid: ctx.amend(oid,
                                               limit_price=Decimal('12.35'))),
                    'amend the price: refused, Tier 2'),
                Step(DAY2, _submit_then(
                    'HPG', 1000, Decimal('12.30'),
                    lambda ctx, oid: ctx.amend(oid, quantity=400)),
                    'amend down: admitted, priority preserved'),
            ),
            open_time=cont[0], close_time=cont[1],
            sessions=(DAY1, DAY2, DAY3),
            note='the amendment rule and the two Tier 1 refusals'),
    )


def run_all(source: Optional[PhasedBarSource] = None
            ) -> Dict[str, ScenarioResult]:
    """Every leg, keyed by name. Used by the tests and by the report."""
    src = source or build_source()
    return {leg.name: run_leg(leg, source=src)[0] for leg in legs()}


# --------------------------------------------------------------------------
# The one edge two advances a day cannot reach on their own
# --------------------------------------------------------------------------

def partial_fill_then_cancel(source: Optional[PhasedBarSource] = None
                             ) -> Tuple[ScenarioResult, ScenarioResult, Any]:
    """Cancel an order that has already partially filled. Two runs, one clock.

    **Why it needs two runs.** The runner's loop is the one ``advance_to``
    documents: an order submitted in ``on_session`` is evaluated by the day's
    *second* advance, and the next advance crosses the date and sweeps the
    day's close before ``on_session`` is called again. So on a one-scenario
    clock a partially-filled day order is always dead by the time the strategy
    could cancel it, and the ``CANCELLED``-with-a-partial edge is
    **unreachable**. That is a property of the two-advance loop, not of the
    exchange -- a real broker session has an order that is filling while the
    trader is watching it.

    The fix uses the session's own monotone clock: the first run leaves the
    session standing at 09:25 with the order live and partly filled, and the
    second run resumes it at 09:30 on the same day and cancels. Nothing is
    reset between them; only the logs are separate, which is why the assertion
    is on the second run's log.

    A consequence worth reading rather than glossing: the 09:30 advance
    evaluates the same day's bar again, so the order fills a **second** cap's
    worth before it is cancelled. The participation cap is per evaluated
    interval, so a day sampled twice permits twice the daily cap. That is the
    declared over-generosity of running a daily bar on an intraday clock, and
    it is visible in the numbers here rather than hidden.

    HPX on 2022-11-10 traded 650,600 shares between 21.15 and 21.50, so at a
    10% cap one interval sizes 65,000 shares against a 200,000-share order.
    """
    src = source or build_source()
    order_ids: List[str] = []

    def enter(ctx):
        outcome = ctx.buy('HPX', 200_000, limit_price=Decimal('21.50'))
        order_id = getattr(outcome, 'order_id', None)
        if order_id is not None:
            order_ids.append(order_id)

    first = Leg(name='partial-fill', steps=(Step(DAY3, enter),),
                open_time=time(9, 20), close_time=time(9, 25),
                sessions=(DAY3,),
                note='an LO sized past the participation cap')
    result_one, session = run_leg(first, source=src)

    second = Leg(name='partial-fill-then-cancel',
                 steps=(Step(DAY3, _cancel_every_live),),
                 open_time=time(9, 30), close_time=time(9, 35),
                 sessions=(DAY3,),
                 note='the same clock, resumed, with the order still live')
    result_two, _ = run_leg(second, source=src, session=session)
    return result_one, result_two, session


def combined_identities(one: ScenarioResult, two: ScenarioResult,
                        session: Any, *, tickers: Sequence[str] = ('HPX',)
                        ) -> Tuple[Any, ...]:
    """Re-check the identities across a chained pair, on the merged logs.

    Each ``run_scenario`` call checks the identities against **its own** log,
    so on a chained pair the second call sees a fill whose ``ACCEPTED`` row is
    in the first log and reports ``order_lifecycle`` and
    ``holdings_conservation`` broken. That is a scoping artefact of chaining,
    not an accounting hole, and the way to show it is an artefact is to run
    the same checks over the union -- which is what this does, rather than
    asserting the failures away.
    """
    from validation.identities import check_identities
    from validation.logs import CashLog, RunLogs, SettlementLog, TradeLog

    from validation.logs import CashMovement

    trades, cash, settlement = TradeLog(), CashLog(), SettlementLog()
    for index, result in enumerate((one, two)):
        for entry in result.logs.trades:
            trades.append(entry)
        for entry in result.logs.cash:
            # The journal writes an OPENING_BALANCE row on every attach, and
            # the second one carries the balance *after* the first run's
            # fills. Keeping both would credit the opening balance twice and
            # break cash conservation on the merge rather than on the ledger.
            if (index and entry.movement is CashMovement.OPENING_BALANCE):
                continue
            cash.append(entry)
        for entry in result.logs.settlement:
            settlement.append(entry)
    merged = RunLogs(trades=trades, cash=cash, settlement=settlement,
                     events=tuple(one.logs.events) + tuple(two.logs.events))
    snapshots = tuple(one.snapshots) + tuple(two.snapshots)
    return check_identities(session, merged, snapshots, tickers=tickers)


# --------------------------------------------------------------------------
# What the shipped adapter costs, measured
# --------------------------------------------------------------------------

def adapter_gap(source: Optional[PhasedBarSource] = None) -> Dict[str, Any]:
    """The same order, the same day, judged on both sources. Returned as data.

    ``DataHubSource`` selects four columns of the corpus and drops
    ``quote_open``, ``quote_max``, ``quote_min`` and ``quote_dailyvolume``,
    all of which are present for every ticker-day of this window. The session
    then synthesises an interval with ``OPEN``, ``HIGH``, ``LOW`` and
    ``VOLUME`` named missing, and ``HardFillPolicy`` cannot compute a
    participation cap -- so it answers ``INDETERMINATE`` wherever it would
    otherwise fill.

    That has been written up as a property of the corpus. This function
    measures it as a property of the adapter: the identical order, on the
    identical day, decided by the identical policy, against a source that
    reads the columns the corpus already holds.
    """
    src = source or build_source()
    leg = Leg(name='adapter-gap',
              steps=(Step(DAY2, _buy('HPG', 1000, Decimal('13.50'))),),
              open_time=time(9, 20), close_time=time(9, 25),
              sessions=(DAY1, DAY2, DAY3))
    rich, _ = run_leg(leg, source=src)

    from validation.corpus import datahub_source
    plain = datahub_source()
    thin = build_session(
        start=DAY1, end=DAY3, venues=['HSX', 'HNX', 'UPCOM', 'HNXDS'], source=plain,
        initial_cash='200000000000', fill_policy='hard',
        max_participation='0.10', resolution=Resolution.DAILY,
        listings=LISTINGS)
    thin_result = run_scenario(Scenario(
        name='adapter-gap-datahub',
        window=Window(name='adapter-gap-datahub', start=DAY1, end=DAY3,
                      tickers=('HPG',), sessions=(DAY1, DAY2, DAY3)),
        session=thin, strategy=ScriptedStrategy(
            'adapter-gap-datahub',
            (Step(DAY2, _buy('HPG', 1000, Decimal('13.50'))),)),
        source=plain, open_time=time(9, 20), close_time=time(9, 25)),
        raise_on_error=True)

    def summarise(result: ScenarioResult) -> Dict[str, Any]:
        return {
            'fill_policy': result.provenance.fill_policy_kind,
            'evaluations': result.indeterminate.evaluations,
            'indeterminate': result.indeterminate.indeterminate,
            'by_field': {k.value: v
                         for k, v in result.indeterminate.by_field.items()},
            'fills': len(fills(result)),
            'terminal': {e.order_id: (e.action.value, e.trigger)
                         for e in terminal_rows(result).values()},
        }

    return {
        'window': f'{DAY1} .. {DAY3}, HPG buy 1000 @ 13.50',
        'corpus_columns_dropped_by_datahub': [
            'quote_open', 'quote_max (the daily high)',
            'quote_min (the daily low)', 'quote_dailyvolume'],
        'phased_bar_source': summarise(rich),
        'shipped_datahub_source': summarise(thin_result),
    }


#: HPG on 2022-11-16: reference 12.50, ceiling 13.35, floor 11.65, and the
#: bar ran open 12.30, high 13.35, low 11.80, close 13.35 on 34,902,600
#: shares. The close *is* the ceiling and the day *is not* a lock.
LOCK_DAY = date(2022, 11, 16)
LOCK_PRICE = Decimal('13.35')


def lock_proxy_divergence(source: Optional[PhasedBarSource] = None
                          ) -> Dict[str, Any]:
    """What ``last == ceiling`` costs, on a day the bar can settle.

    ``adapters/datahub.py`` builds ``locked_side`` from the close alone::

        if last_d == ceiling_d: locked_side, evidence = Side.BUY, BAR_PROXY

    and ``exchanges/equity.py``'s ``BAND_LOCK`` rule then refuses any buy
    marketable into that inferred lock. On HPG 2022-11-16 the close is the
    ceiling and the day's low is 11.80 -- the market traded 11.6% below the
    ceiling on 34.9 million shares -- so the inference refuses an order the
    same day's bar proves was fillable.

    The rule is right; the proxy behind it is what a daily close can support
    and no more. With ``open``, ``high`` and ``low`` the question is
    answerable, and this scenario's source asserts a lock only when the whole
    bar sits on the band. Measured here rather than argued.
    """
    src = source or build_source()
    leg = Leg(name='lock-proxy-rich',
              steps=(Step(LOCK_DAY, _buy('HPG', 1000, LOCK_PRICE)),),
              open_time=time(9, 20), close_time=time(9, 25),
              sessions=(DAY6, LOCK_DAY, DAY8))
    rich, _ = run_leg(leg, source=src)

    from validation.corpus import datahub_source
    plain = datahub_source()
    thin = build_session(
        start=DAY6, end=DAY8, venues=['HSX', 'HNX', 'UPCOM', 'HNXDS'],
        source=plain, initial_cash='200000000000', fill_policy='hard',
        max_participation='0.10', resolution=Resolution.DAILY,
        listings=LISTINGS)
    thin_result = run_scenario(Scenario(
        name='lock-proxy-datahub',
        window=Window(name='lock-proxy-datahub', start=DAY6, end=DAY8,
                      tickers=('HPG',), sessions=(DAY6, LOCK_DAY, DAY8)),
        session=thin, strategy=ScriptedStrategy(
            'lock-proxy-datahub',
            (Step(LOCK_DAY, _buy('HPG', 1000, LOCK_PRICE)),)),
        source=plain, open_time=time(9, 20), close_time=time(9, 25)),
        raise_on_error=True)

    def verdict(result: ScenarioResult) -> Dict[str, Any]:
        row = [e for e in result.logs.trades
               if e.action in (TradeAction.ACCEPTED, TradeAction.REJECTED)][0]
        return {'action': row.action.value, 'rule': row.rule,
                'binding_constraint': row.binding_constraint,
                'fills': len(fills(result))}

    return {
        'day': LOCK_DAY.isoformat(),
        'bar': {'open': '12.30', 'high': '13.35', 'low': '11.80',
                'close': '13.35', 'ceiling': '13.35', 'floor': '11.65',
                'volume': 34_902_600},
        'order': f'HPG buy 1000 @ {LOCK_PRICE} (at the ceiling)',
        'phased_bar_source': verdict(rich),
        'shipped_datahub_source': verdict(thin_result),
    }
