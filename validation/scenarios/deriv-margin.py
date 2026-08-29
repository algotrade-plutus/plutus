"""Derivatives margin: the call, the deadline, the cure, the forced close.

The author's first requirement, put to the assembled simulator against a real
Vietnamese drawdown. One leveraged VN30F long, funded the way a retail account
actually is, carried into the October-2022 collapse, run under three broker
profiles whose published ladders differ -- and read back out of the trade, cash
and settlement logs rather than out of the code that produced them.

**The window.** ``VN30F2210``, 2022-09-26 to its expiry 2022-10-20: 19
sessions, front month, in the wired Parquet corpus, and pre-KRX so
``rulebook.margin_model()`` resolves to the ``MR = IM + VM`` shape that
``deposit.py`` implements. The contract falls 1192.0 -> 1058.0, with a
-47.4-point session on 2022-10-03 and a trough of 989.0 on 2022-10-11.

**The funding.** 4 contracts at 1192.0 against a 100,000,000d deposit is an
entry utilisation of **0.6202** -- 61,984,000d of initial margin against
99,948,008d of assets after the entry charges. That is the point of the
number. Funding an account *at* its requirement makes a call an arithmetic
identity and proves nothing; ``docs/reference/margin-model-adjudication.md``
retracts a published figure for exactly that reason. 0.62 is a normal
aggressive retail level, it survives the first four sessions of the drawdown,
and the market -- not the arithmetic -- is what breaks it.

**The three profiles**, all shipped in
:mod:`plutus.market.session.broker_profile`, one synthesis and two named
firms, and the outcomes separate exactly as their ladders predict:

=============== ===================== ================= ================= ==============
profile         ladder (warn/call/fc) first event       first forced      call raised?
=============== ===================== ================= ================= ==============
PLUTUS_DEFAULT  0.80 / 0.90 / 0.95    2022-10-03 CALL   2022-10-04        yes
SSI_FOREIGN     0.75 / 0.80 / 0.85    2022-09-29 WARN   2022-10-03        no
TCBS            0.85 / 0.87 / 0.90    2022-10-03 FORCED 2022-10-03        no
=============== ===================== ================= ================= ==============

SSI_FOREIGN sees the account four sessions before PLUTUS_DEFAULT says anything
at all, and closes it one session sooner. TCBS's rungs are 3 points apart, so
the 2022-10-03 move -- 0.7664 to 0.9314 in one session -- crosses all three of
them at once and the account is liquidated with no warning and no call. That
is the axis the profile module exists to express, measured.

**The cure, all three answers.** ``MarginMonitor``'s docstring says a called
account may *"transfer, reduce, or do nothing"*, and the same PLUTUS_DEFAULT
leg is run three times, once for each.

* **Do nothing** -- force-closed on 2022-10-04, the first mark at or after the
  2022-10-04 08:45 deadline.
* **Transfer** -- **17,000,000d** out of securities cash in the session the
  call arrives, the amount the profile's own ``TargetRef.RUNG_1`` names,
  rounded up to a whole million. Buys three sessions: no forced close until
  2022-10-07. The equity account paid for them and the log says so.
* **Reduce** -- sell one contract. This is the only leg that reaches the
  realised close-out path: the deposit moves by 1 x 100,000 x (1102.6 -
  1192.0) = **-8,940,000d** measured from the variation-margin reference, and
  the requirement falls from four contracts' worth to three. It buys the same
  three sessions, and it is also the leg that shows the forced latch releasing
  properly -- the account comes back to the warning rung on 2022-10-18, the
  latch clears, and a genuinely new call fires on 2022-10-19 with a fresh
  deadline. Four contracts leave at four different prices and the deposit
  reconciles to the dong: -49,640,000d of position P&L, 100,000,000d in and
  50,269,742d out.

None of the three saves the account. That is the honest result: a cure is not
a rescue, it is three more sessions.

**Segregation, proved by the uncured leg.** That account is force-closed while
holding 500,000,000d of settled securities cash and 1,000 FPT -- five times
what the call asked for, sitting one pool away. Neither moves. There is no
auto-transfer in Vietnam and there is none here; ``ctx.transfer`` is the only
bridge and the cured leg is what using it looks like.

WHAT THIS SCENARIO FOUND
------------------------

Nine things, in descending order of how much they would cost a user who
believed the output. Three are fixed; six are not, and :func:`findings`
returns all nine as data so a report cannot quietly drop one. The three fixes
each have a test that fails without them: reverting all three turns nine of
this scenario's assertions red.

1. **A forced close re-granted the cure window** (fixed, ``deposit.py``
   ``MarginMonitor.on_mark``). The machine dropped its call state when it
   escalated, so an account force-closed at the 09:30 mark and still at 0.9335
   at the 14:45 mark of the same session was handed a fresh margin call with a
   fresh next-session deadline: ``margin_call`` 2022-10-03 09:30 ->
   ``forced_liquidation`` 2022-10-04 09:30 -> ``margin_call`` 2022-10-04 14:45,
   ``cure_by`` moving 2022-10-04 08:45 -> 2022-10-05 08:45. The sequence
   de-escalated and the account got a second grace period on a worse exposure.

2. **The profile's first rung is a block on opening and was reported as a
   warning** (fixed, ``deposit.py`` ``reserve_for_order`` +
   ``types.BrokerProfile.block_opening_utilisation``). Every surveyed firm's
   Muc 1 is *"toi da de duoc mo vi the moi"*; ``to_broker_terms`` can only
   project it onto ``warning_utilisation``, which turns a refusal into a
   notification. Measured before the fix: at 0.9314 utilisation on 2022-10-03
   -- past PLUTUS_DEFAULT's own 0.80 block and its 0.90 call -- a fifth
   contract was **accepted**. It is now refused with
   ``binding_constraint=0.80`` while an offsetting sell is still admitted, the
   exception QD 26 Dieu 13.2.a requires.

3. **MBS's liquidation level would have been reported as a margin call**
   (fixed by refusing, ``types.BrokerProfile.from_margin_profile``).
   ``to_broker_terms`` reads the ladder *positionally* and MBS's is
   ``AR duy tri`` (NOTIFY) / ``AR xu ly`` (LIQUIDATE) / ``Nguong xu ly tai
   VSDC`` -- no block-opening rung at all. Filled from PLUTUS_DEFAULT that is
   0.90/0.95/1.00, so the session would emit ``MARGIN_CALL`` at 0.95 where MBS
   closes positions, and would not force-close until the CCP's 1.00. MBS is the
   only shipped profile with this shape and it is now refused rather than
   mapped.

4. **``FORCED_LIQUIDATION`` now executes** (resolved, MUST #3 forced-execute,
   2026-08-27). It runs a real offsetting order through the order path, so
   ``detail['executed']`` is ``True`` on the fill. On the uncured
   PLUTUS_DEFAULT leg the account is force-closed on 2022-10-06 -- reported at
   the 09:30 mark, filled at the 14:45 close -- and the book is flat afterwards
   rather than riding the fall to expiry. The position no longer settles at
   maturity on this leg at all: it is offset three sessions before expiry, so
   the exit is a realised close-out in the cash log, not an ``EXPIRY_SETTLED``
   row.

5. **Variation margin now settles in cash** (resolved, W1 daily cash
   settlement). ``DerivativesAccount.settle_daily`` is wired into the overnight
   layer (``exchange._overnight_margin``), so once per settlement day the
   deposit moves by the day's realised position P&L and the VM baseline rolls.
   The deposit no longer sits at 99,948,008d: it steps down every session the
   mark falls (99,948,008 -> 97,148,008 -> ... -> 69,228,008 before the forced
   close), and each close carries ``VM == 0``. The old substitution -- carrying
   the loss in ``MR`` on a static deposit -- is gone; utilisation is now the
   settled ``(IM + dL) / (D - L_prev)`` shape a real broker statement shows.
   :func:`cash_settlement_divergence` still computes both series as the record
   of *how far apart* the two models were: they agree only while nothing has
   settled -- the first two sessions -- then diverge with the same sign flip
   (as-built the higher through 2022-10-04, cash-settled the higher from
   2022-10-05, the worst gap the up-day 2022-10-12 at **1.2013 as-built against
   2.8432 cash-settled**). What changed is which one the session *does*: the
   run has moved off the as-built column onto the settled one, its utilisation
   strictly below as-built on every session after the first.

6. **The settlement calendar is the unsourced weekday default.** Every run
   here reports ``settlement_calendar_id == 'weekday-only-UNSOURCED'``. The
   2022-10-03 call's deadline, 2022-10-04 08:45, happens to be right because
   2022-10-04 was a trading day; the same arithmetic across a Tet break would
   not be. The scenario asserts the deadline **and** asserts that the calendar
   said UNSOURCED, so the claim stays bounded by its evidence.

WHAT THIS SCENARIO DOES NOT CLAIM
---------------------------------

* The **fill policy is ``soft``**, deliberately and not for convenience. The
  entry here is priced *at* the day's close, and ``hard`` refuses a continuous
  touch because time priority is unrecoverable from a bar -- so the entry
  would never fill and there would be no position to margin. ``soft`` fills at
  the limit when the close touched it, which is a *model output*, and the
  trade log carries ``evidence='touched_at_limit'`` on every fill so a reader
  can see it.

  This paragraph used to say ``hard`` is *"100% INDETERMINATE -- the bars
  carry no high, no low and no volume"*. The volume third of that is no longer
  true: ``adapters/datahub.py`` serves ``quote_dailyvolume``, and ``hard``
  fills on this corpus wherever the close traded **through** a limit (see
  ``order_cycle`` and ``equity-margin``). It changes nothing here, because the
  refusal at this entry is the touch and not the cap, and deciding a touch
  needs ``quote_max`` and ``quote_min``, which are on disk and still not
  served.
* The **utilisation ladder is unsourced** in shape and in levels except at its
  top rung (``FEATURES.md`` A1-A3; QD 26 Dieu 13 is binary and prints no
  percentage). What the profiles supply is what each firm published, which is
  a commercial fact, not a market rule.
* The IM ratio each requirement is built on is **0.13**, the VSD rate in force
  on these dates, resolved per instant by the rulebook. The profiles' own
  ``initial_margin_ratio`` (PLUTUS_DEFAULT 0.1785) is deliberately **not**
  used: it is an absolute ratio published for the 0.17 era and there is no
  date-free arithmetic that turns it into a 2022 buffer. That is stated in
  ``BrokerProfile.from_margin_profile`` and reported by :func:`findings`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from plutus.core.order import OrderType
from plutus.market.margin import vsd_initial_margin
from plutus.market.session import broker_profile as bp
from plutus.market.session.types import EventKind, Pool

from validation.corpus import closes, datahub_source
from validation.runner import (Scenario, ScenarioResult, Window, build_session,
                               run_scenario, sessions_from_source)
from validation.strategy import BaseStrategy

__all__ = [
    'CONTRACT', 'EQUITY_CASH', 'EQUITY_LOTS', 'EQUITY_TICKER', 'DEPOSIT',
    'LOTS', 'MULTIPLIER', 'WINDOW_END', 'WINDOW_START', 'PROFILES',
    'LadderStep', 'Leg', 'LeveragedLong',
    'build_scenario', 'run_leg', 'run_payload_configured', 'ladder_steps',
    'first_events', 'independent_requirement', 'cash_settlement_divergence',
    'findings', 'deposit_trail', 'main',
]

_ZERO = Decimal('0')
_MILLION = Decimal('1000000')

#: The front-month VN30 future through the October-2022 collapse. Listed
#: 2022-09-05, expires 2022-10-20, and the whole life of the position is inside
#: the wired Parquet corpus, so this scenario needs no database adapter.
CONTRACT = 'VN30F2210'

#: Entry the session after the position is opened is not the point; the window
#: starts the day the position is opened so the entry utilisation is a fact of
#: the run rather than a parameter of it.
WINDOW_START = date(2022, 9, 26)
WINDOW_END = date(2022, 10, 20)

#: 100,000d per index point, VSDC, HIGH, from 2017-08-10
#: (``deposit.CONTRACT_MULTIPLIERS``). Restated here only so the independent
#: oracle below is arithmetic a reader can check, not a call back into the
#: module under test.
MULTIPLIER = Decimal('100000')

LOTS = 4
DEPOSIT = Decimal('100000000')

#: The securities side exists to be *not* touched. Five times the largest call
#: this window raises, sitting one pool away, and a settled equity holding on
#: top of it.
EQUITY_CASH = Decimal('500000000')
EQUITY_TICKER = 'FPT'
EQUITY_LOTS = 1000

#: The three shipped profiles this scenario contrasts. One synthesis
#: (PLUTUS_DEFAULT, which warns that it is one and matches no firm) and two
#: named firms whose ladders bracket it from both sides.
PROFILES: Tuple[str, ...] = ('PLUTUS_DEFAULT', 'SSI_FOREIGN', 'TCBS')

#: The margin events, mildest first. Ordered so a test can say "the first thing
#: this profile said" without re-deriving severity.
_MARGIN_EVENTS = (EventKind.MARGIN_WARNING, EventKind.MARGIN_CALL,
                  EventKind.FORCED_LIQUIDATION)


# --------------------------------------------------------------------------
# The algorithm
# --------------------------------------------------------------------------

class LeveragedLong(BaseStrategy):
    """Open a leveraged long once, hold it, and optionally answer the call.

    Deliberately close to what a real retail derivatives algorithm does and no
    closer: it reads its own position and margin back off the exchange, it
    never computes P&L, and holding overnight is what happens when
    :meth:`on_session` declines to act. The only decision it makes after entry
    is whether to top the deposit up when a call arrives.

    ``cure`` picks the leg. When it is off the strategy is the trader who does
    nothing -- which is a real trader, and is what the cure window is measured
    against. When it is on, the top-up is sized from the **profile's own**
    ``TargetRef``: PLUTUS_DEFAULT's Muc 2 restores to Muc 1, so the target is
    0.80 and the amount is ``required / 0.80 - deposit_balance``, rounded up to
    a whole million because that is how a person transfers money. Nothing about
    the amount is invented here; :func:`plutus.market.session.broker_profile.
    resolve_target` supplies the level.

    ``cure='reduce'`` is the other response a called account has, and it is a
    different code path end to end: an offsetting order attracts no new initial
    margin, is admitted on a breaching account, and moves the deposit by the
    realised P&L on the contracts that leave. Nothing else in this scenario
    reaches that path.

    ``open_more_on`` exists for one test and is off by default: it submits an
    additional opening contract on a named date, to show which rung refuses it.
    """

    name = 'leveraged-long-vn30f'

    def __init__(self, *, lots: int = LOTS, cure: Any = False,
                 profile: Optional[Any] = None,
                 open_more_on: Optional[date] = None) -> None:
        self.lots = lots
        #: ``False`` | ``'transfer'`` | ``'reduce'``. ``True`` means transfer,
        #: which is what the first version of this scenario had.
        self.cure = 'transfer' if cure is True else cure
        self.profile = profile
        self.open_more_on = open_more_on
        self.entered = False
        self.topped_up = _ZERO
        self.top_ups: List[Tuple[datetime, Decimal]] = []
        self.reduced = 0
        self.reductions: List[Tuple[datetime, int]] = []
        #: ``(ts, utilisation, opening_outcome, offsetting_outcome)`` for the
        #: admission probe. Kept as the raw verdict objects: a test asserting on
        #: the rule that refused must see the rule.
        self.admission: List[Tuple[datetime, Optional[Decimal], Any, Any]] = []

    # -- entry ------------------------------------------------------------

    def on_start(self, ctx) -> None:
        ctx.note(
            'entering a leveraged VN30F long into a real drawdown',
            contract=CONTRACT, lots=self.lots,
            deposit=str(DEPOSIT), cure=self.cure,
            broker_profile=ctx.provenance().broker_profile_name,
            funding_note='sized to about 0.62 entry utilisation -- an account '
                         'funded at its requirement makes a call an '
                         'arithmetic identity')

    def on_session(self, ctx) -> None:
        if not self.entered:
            self._enter(ctx)
            return
        if self.open_more_on is not None and ctx.today == self.open_more_on:
            self._probe_admission(ctx)
        if self.cure == 'transfer':
            self._answer_any_call(ctx)
        elif self.cure == 'reduce':
            self._reduce_to_answer_call(ctx)

    def _enter(self, ctx) -> None:
        price = ctx.price(CONTRACT)
        if price is None:
            # Not listed yet, or a session the corpus has no row for. A
            # strategy must handle it; the simulator will not invent a price.
            return
        outcome = ctx.buy(CONTRACT, self.lots, limit_price=price,
                          order_type=OrderType.LIMIT)
        self.entered = True
        ctx.note('entry submitted', price=str(price), outcome=type(outcome).__name__)

    # -- the cure ---------------------------------------------------------

    def _answer_any_call(self, ctx) -> None:
        """Top the deposit up when this step delivered a margin call.

        Keyed on the **event**, not on the utilisation, because that is what a
        trader receives: the broker calls, and the account answers. Doing it
        off the ratio would let the strategy pre-empt a call that the broker
        never made, which is a different experiment.
        """
        if not any(e.kind is EventKind.MARGIN_CALL for e in ctx.events):
            return
        view = ctx.margin()
        target = self._cure_target()
        if target is None or target <= 0:
            ctx.note('call arrived and the profile names no target level to '
                     'restore to; no top-up sized', firm=str(self.profile))
            return
        shortfall = view.required / target - view.deposit_balance
        if shortfall <= 0:
            return
        amount = ((shortfall / _MILLION).quantize(Decimal('1'),
                                                  rounding=ROUND_CEILING)
                  * _MILLION)
        outcome = ctx.transfer(Pool.SECURITIES, Pool.DERIVATIVES, amount)
        self.topped_up += amount
        self.top_ups.append((ctx.now, amount))
        ctx.note('answered the margin call out of securities cash',
                 amount=str(amount), target_level=str(target),
                 required=str(view.required),
                 deposit_before=str(view.deposit_balance),
                 outcome=type(outcome).__name__,
                 note='there is no auto-transfer in Vietnam; this is the only '
                      'bridge between the two pools and it is an explicit act')

    def _reduce_to_answer_call(self, ctx) -> None:
        """Answer the call by closing contracts instead of by paying.

        The second of the three responses ``MarginMonitor`` names -- transfer,
        reduce, or do nothing -- and the only one that reaches the realised
        close-out path, where the deposit is moved by the P&L on the contracts
        that leave measured from the variation-margin reference.

        The quantity is derived, not chosen. Both terms of ``MR`` are linear in
        the number of contracts held, so ``MR(n) = n x MR(1)``, and the
        smallest ``n`` with ``n x MR(1) <= target x assets`` is the answer. It
        is an under-estimate of what is needed, deliberately: closing a losing
        contract also *realises* its loss out of the deposit, so the assets
        this sizes against are larger than the assets that result. That the
        call clears anyway is a fact about this window, not an identity, and
        the run reports the resulting ratio rather than assuming it.
        """
        if not any(e.kind is EventKind.MARGIN_CALL for e in ctx.events):
            return
        position = ctx.positions().get(CONTRACT)
        price = ctx.price(CONTRACT)
        target = self._cure_target()
        if position is None or price is None or target is None:
            return
        held = abs(position.net_quantity)
        if held <= 1:
            return
        view = ctx.margin()
        per_contract = view.required / Decimal(held)
        allowed = view.deposit_balance * target
        keep = int(allowed / per_contract)
        to_close = max(1, held - max(keep, 0))
        outcome = ctx.sell(CONTRACT, to_close, limit_price=price,
                           order_type=OrderType.LIMIT)
        self.reduced += to_close
        self.reductions.append((ctx.now, to_close))
        ctx.note('answered the margin call by closing contracts',
                 closed=to_close, held=held, target_level=str(target),
                 required=str(view.required),
                 outcome=type(outcome).__name__,
                 note='an offsetting order attracts no new initial margin and '
                      'is admitted on a breaching account -- QD 26 Dieu '
                      '13.2.a excepts it explicitly')

    def _cure_target(self) -> Optional[Decimal]:
        """The level the profile's call rung restores the ratio to."""
        if self.profile is None:
            return None
        for rung in self.profile.ladder:
            if rung.action is bp.Action.NOTIFY:
                return bp.resolve_target(self.profile, rung)
        return None

    # -- the admission probe ---------------------------------------------

    def _probe_admission(self, ctx) -> None:
        """Try to open one more contract, and to offset one, at today's ratio.

        Both on the same instant so the pair isolates the one thing that
        differs: an opening order raises the worst-case net and an offsetting
        order does not. QD 26 Dieu 13.2.a requires the second to be admitted on
        an account the first is refused on.
        """
        price = ctx.price(CONTRACT)
        if price is None:
            return
        view = ctx.margin()
        opening = ctx.buy(CONTRACT, 1, limit_price=price,
                          order_type=OrderType.LIMIT)
        offsetting = ctx.sell(CONTRACT, 1, limit_price=price,
                              order_type=OrderType.LIMIT)
        self.admission.append((ctx.now, view.utilisation, opening, offsetting))
        ctx.note('admission probe at this utilisation',
                 utilisation=str(view.utilisation),
                 opening=type(opening).__name__,
                 offsetting=type(offsetting).__name__)


# --------------------------------------------------------------------------
# Running a leg
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Leg:
    """One run: the profile it ran under, the strategy, and the result.

    ``session`` is carried because the deposit's own audit trail lives on the
    account and not in any of the three logs: ``DerivativesAccount`` keeps a
    ``DepositEntry`` per movement with a signed amount and the resulting
    balance, and a test that wants to prove every dong is accounted for should
    check the account's arithmetic and the cash log's against each other rather
    than trusting either alone.
    """

    firm: str
    cured: Any
    profile: Any
    strategy: LeveragedLong
    result: ScenarioResult
    session: Any

    @property
    def name(self) -> str:
        suffix = f'-{self.cured}' if self.cured else '-uncured'
        return f'{self.firm}{suffix}'


@dataclass(frozen=True)
class LadderStep:
    """One margin event, flattened out of the event stream.

    ``kind`` is the event's own, so a reader never has to re-derive which rung
    fired from the ratio -- which is the mistake ``assess``'s docstring warns
    about, and which the monitor's forced latch would defeat anyway: after a
    forced close a ``CALL``-level mark is reported ``FORCED``, on purpose.
    """

    ts: datetime
    kind: str
    utilisation: Optional[Decimal]
    required: Optional[Decimal]
    deposit_balance: Optional[Decimal]
    cure_by: Optional[datetime]
    executed: Optional[bool]

    @property
    def day(self) -> date:
        return self.ts.date()


def build_scenario(firm: str = 'PLUTUS_DEFAULT', *, cure: Any = False,
                   source: Any = None, lots: int = LOTS,
                   deposit: Decimal = DEPOSIT,
                   open_more_on: Optional[date] = None,
                   sessions: Sequence[date] = ()) -> Tuple[Scenario, Any,
                                                           LeveragedLong]:
    """A scenario, the margin profile it runs under, and its strategy.

    The profile is resolved and returned rather than being left inside the
    session, because a test's whole job here is to check the session's
    behaviour against the firm's published ladder, and it must read that ladder
    from the same object the session was configured from.

    ``warn=False`` on the profile lookup suppresses the coverage *warnings* and
    nothing else: the gaps are still on the profile, ``material_caveats`` still
    returns them, and :func:`findings` reports them. Left on, every run of this
    scenario would emit a ``SynthesisWarning`` per profile per call and the
    real output would be unreadable.
    """
    src = source if source is not None else datahub_source()
    days = tuple(sessions) or sessions_from_source(
        src, CONTRACT, WINDOW_START, WINDOW_END)
    profile = bp.get_profile(firm, warn=False)
    session = build_session(
        start=WINDOW_START, end=WINDOW_END, venues=['HSX', 'HNXDS'],
        source=src, initial_cash=EQUITY_CASH, initial_deposit=deposit,
        fill_policy='soft',
        initial_holdings={EQUITY_TICKER: EQUITY_LOTS},
        broker_profile={'firm': firm, 'warn': False})
    window = Window(
        name=f'vn30f2210-drawdown-{firm}', start=WINDOW_START, end=WINDOW_END,
        tickers=(CONTRACT, EQUITY_TICKER), sessions=days,
        reference_ticker=CONTRACT,
        note='the October-2022 VN30F collapse, front month, pre-KRX')
    strategy = LeveragedLong(lots=lots, cure=cure, profile=profile,
                             open_more_on=open_more_on)
    scenario = Scenario(
        name=f'deriv-margin/{firm}{"-cured" if cure else ""}',
        window=window, session=session, strategy=strategy, source=src,
        opening_holdings={EQUITY_TICKER: EQUITY_LOTS},
        note='a leveraged VN30F long carried into a real drawdown')
    return scenario, profile, strategy


def run_leg(firm: str = 'PLUTUS_DEFAULT', *, cure: Any = False,
            source: Any = None, **kwargs: Any) -> Leg:
    """Build and run one leg."""
    scenario, profile, strategy = build_scenario(
        firm, cure=cure, source=source, **kwargs)
    result = run_scenario(scenario)
    return Leg(firm=firm, cured=cure, profile=profile, strategy=strategy,
               result=result, session=scenario.session)


def run_payload_configured(*, source: Any = None, lots: int = LOTS,
                           open_more_on: Optional[date] = None,
                           levels: Tuple[str, str, str] = ('0.80', '0.90',
                                                           '0.95'),
                           ) -> Leg:
    """The same run, configured from the payload rather than from the firm.

    The control for finding 2. It sets PLUTUS_DEFAULT's three levels by hand
    and names no firm, so ``block_opening_utilisation`` is ``None`` and the
    session behaves exactly as it did before the fix. Everything else -- the
    window, the contract, the funding, the fill policy -- is identical, so the
    pair isolates one variable: whether the session knows that the first rung
    is an action rather than a notification.

    It is also the honest way to model a firm the bridge refuses. A caller who
    wants MBS sets the three numbers here and owns the mapping; what they must
    not do is name MBS and inherit a shifted ladder.
    """
    src = source if source is not None else datahub_source()
    days = sessions_from_source(src, CONTRACT, WINDOW_START, WINDOW_END)
    session = build_session(
        start=WINDOW_START, end=WINDOW_END, venues=['HSX', 'HNXDS'],
        source=src, initial_cash=EQUITY_CASH, initial_deposit=DEPOSIT,
        fill_policy='soft',
        initial_holdings={EQUITY_TICKER: EQUITY_LOTS},
        broker_profile={'name': 'payload-configured',
                        'warning_utilisation': levels[0],
                        'margin_call_utilisation': levels[1],
                        'forced_close_utilisation': levels[2]})
    strategy = LeveragedLong(lots=lots, cure=False, profile=None,
                             open_more_on=open_more_on)
    scenario = Scenario(
        name='deriv-margin/payload-configured',
        window=Window(name='vn30f2210-drawdown-payload', start=WINDOW_START,
                      end=WINDOW_END, tickers=(CONTRACT, EQUITY_TICKER),
                      sessions=days, reference_ticker=CONTRACT),
        session=session, strategy=strategy, source=src,
        opening_holdings={EQUITY_TICKER: EQUITY_LOTS},
        note='the control for finding 2: same levels, no firm, no actions')
    return Leg(firm='payload-configured', cured=False, profile=None,
               strategy=strategy, result=run_scenario(scenario),
               session=session)


# --------------------------------------------------------------------------
# Reading the run back
# --------------------------------------------------------------------------

def ladder_steps(result: ScenarioResult) -> Tuple[LadderStep, ...]:
    """Every margin event the run emitted, in order.

    Margin events are deliberately **not** trade-log rows -- they belong to no
    order -- so they are read off ``result.logs.events``, which is the runner's
    verbatim copy of the session's cursor.
    """
    steps = []
    for event in result.logs.events:
        if event.kind not in _MARGIN_EVENTS:
            continue
        detail = event.detail
        steps.append(LadderStep(
            ts=event.ts, kind=event.kind.value,
            utilisation=detail.get('utilisation'),
            required=event.amount,
            deposit_balance=detail.get('deposit_balance'),
            cure_by=detail.get('cure_by'),
            executed=detail.get('executed')))
    return tuple(steps)


def first_events(result: ScenarioResult) -> Dict[str, datetime]:
    """``{event kind: the instant it first fired}``."""
    out: Dict[str, datetime] = {}
    for step in ladder_steps(result):
        out.setdefault(step.kind, step.ts)
    return out


def deposit_trail(leg: Leg) -> Tuple[Tuple[datetime, Decimal, str, Decimal], ...]:
    """Every movement of the segregated deposit, from the account's own log.

    ``DerivativesAccount`` keeps a ``DepositEntry`` for every movement with a
    signed ``amount`` and the resulting ``balance_after``; ``CashLedger`` takes
    a ``ts`` and a ``reason`` on every call and discards both, which is why
    ``validation.journal`` has to wrap the securities half by hand. Read here
    from the account, so that a test comparing this to the cash log is checking
    two independent records against each other.
    """
    return tuple((entry.ts, entry.amount, entry.reason, entry.balance_after)
                 for entry in leg.session._derivatives.entries)


# --------------------------------------------------------------------------
# The independent oracle -- arithmetic a reader can check
# --------------------------------------------------------------------------

def independent_requirement(price_by_day: Mapping[date, Decimal],
                            *, entry: Decimal, lots: int = LOTS,
                            multiplier: Decimal = MULTIPLIER,
                            ) -> Dict[date, Dict[str, Decimal]]:
    """``MR`` at the **close** recomputed from the corpus closes, longhand.

    Nothing here calls into ``deposit.py``. The IM ratio comes from
    :func:`plutus.market.margin.vsd_initial_margin`, which is the dated VSD
    series and not the margin engine, and everything else is
    multiplication -- so a test comparing this to the session's ``MarginView``
    is comparing the engine to the formula rather than to a restatement of
    itself.

    Resolved under W1 daily cash settlement: at each session's close
    ``settle_daily`` has settled the day's position P&L to cash and rolled the
    variation baseline, so the close carries **no** variation margin.

    * ``IM = rate x |net| x multiplier x price``, on the **current** price,
      never on entry notional (rulebook 6.3);
    * ``VM = 0`` at the close -- the day's loss is settled in cash, not carried;
    * ``MR = IM``.

    ``entry`` is retained for the callers that still pass it, but no longer
    enters the close requirement: the baseline rolls daily, so entry notional
    is settled out rather than carried in ``MR``.
    """
    out: Dict[date, Dict[str, Decimal]] = {}
    quantity = Decimal(lots)
    for day, price in sorted(price_by_day.items()):
        rate = vsd_initial_margin(day)
        initial = rate * quantity * multiplier * price
        out[day] = {'price': price, 'rate': rate, 'initial_margin': initial,
                    'variation_margin': _ZERO,
                    'required': initial}
    return out


def cash_settlement_divergence(price_by_day: Mapping[date, Decimal], *,
                               entry: Decimal, deposit: Decimal,
                               lots: int = LOTS,
                               multiplier: Decimal = MULTIPLIER,
                               ) -> Tuple[Dict[str, Any], ...]:
    """Finding 5, as a measurement rather than an assertion.

    **Resolved under W1:** the simulator now does the cash-settled model, so
    this function is the record of *how far apart* the two models are rather
    than a live limitation. Two utilisation series over the same prices:

    * **as built** -- the old behaviour: the loss stays in ``MR`` as variation
      margin and the deposit never moves: ``u = (IM + L) / D``;
    * **cash settled** -- what VSDC actually does pre-KRX, and what the session
      now does. The day's position P&L is a cash movement settled T+1, so by
      the time a session is marked the *previous* session's loss has left the
      deposit and only the current day's move is unsettled:
      ``u = (IM + dL) / (D - L_prev)``.

    They are not the same number and they do not err in the same direction.
    On this window the sign flips exactly once: the two agree while nothing
    has settled, this session is the higher through 2022-10-04 and the lower
    from 2022-10-05 on, by up to 137%. So the substitution is not
    "conservative" -- it has no single sign, and it understates precisely in
    the tail, which is the stretch where a real account is closed out or
    blown.

    ``deposit_exhausted`` is the case this window does not reach and a bigger
    position would: once the settled loss passes the deposit, the cash-settled
    account has no assets at all and the ratio is not merely large, it is
    undefined. On this window neither column reaches it -- the as-built assets
    are static by construction, and the cash-settled loss never exceeds the
    100,000,000d deposit.

    Returns one row per session with both ratios, so a caller can print the
    divergence rather than being told about it.
    """
    quantity = Decimal(lots)
    rows: List[Dict[str, Any]] = []
    previous_loss = _ZERO
    for day, price in sorted(price_by_day.items()):
        rate = vsd_initial_margin(day)
        initial = rate * quantity * multiplier * price
        pnl = quantity * multiplier * (price - entry)
        loss = -pnl if pnl < 0 else _ZERO

        as_built_required = initial + loss
        as_built_assets = deposit
        settled_assets = deposit - previous_loss
        unsettled = loss - previous_loss
        settled_required = initial + (unsettled if unsettled > 0 else _ZERO)

        rows.append({
            'date': day,
            'price': price,
            'cumulative_loss': loss,
            'as_built_required': as_built_required,
            'as_built_assets': as_built_assets,
            'as_built_utilisation': (as_built_required / as_built_assets
                                     if as_built_assets > 0 else None),
            'cash_settled_required': settled_required,
            'cash_settled_assets': settled_assets,
            'cash_settled_utilisation': (settled_required / settled_assets
                                         if settled_assets > 0 else None),
            'deposit_exhausted': settled_assets <= 0,
        })
        previous_loss = loss
    return tuple(rows)


# --------------------------------------------------------------------------
# Findings, as data
# --------------------------------------------------------------------------

def findings() -> Tuple[Dict[str, Any], ...]:
    """What this scenario found, so a report cannot silently drop one.

    ``status`` is one of ``fixed``, ``open`` or ``declared``. ``open`` means
    the simulator is wrong and this scenario did not fix it; ``declared`` means
    the behaviour is a documented modelling choice whose cost this scenario
    measured.
    """
    return (
        {'id': 'F1', 'status': 'fixed',
         'where': 'deposit.py MarginMonitor.on_mark',
         'what': 'a forced close dropped the call state, so a still-breached '
                 'account was handed a fresh margin call with a fresh cure '
                 'deadline in the same session',
         'evidence': 'margin_call 2022-10-03 09:30 -> forced_liquidation '
                     '2022-10-04 09:30 -> margin_call 2022-10-04 14:45, '
                     'cure_by 2022-10-04 08:45 -> 2022-10-05 08:45',
         'fix': 'the forced state latches until the account comes back to '
                'WARNING or OK'},
        {'id': 'F2', 'status': 'fixed',
         'where': 'deposit.py reserve_for_order, types.py BrokerProfile',
         'what': "the profile's first rung blocks OPENING a position and "
                 'to_broker_terms could only report it as a warning',
         'evidence': 'the same account at the same instant, 0.9176 '
                     'utilisation on 2022-10-03: configured from the payload '
                     'at 0.80/0.90/0.95 a fifth contract is REJECTED at the '
                     'funding bound; configured from the firm it is REJECTED '
                     'with binding_constraint 0.80. The offsetting sell is '
                     'accepted either way',
         'fix': 'block_opening_utilisation is carried on the session profile '
                'and read by reserve_for_order; offsetting orders still pass'},
        {'id': 'F3', 'status': 'fixed',
         'where': 'types.py BrokerProfile.from_margin_profile',
         'what': 'to_broker_terms reads the ladder positionally, and MBS has '
                 'no block-opening rung, so its liquidation level would be '
                 'reported as a margin call',
         'evidence': 'MBS filled from PLUTUS_DEFAULT is 0.90/0.95/1.00 where '
                     'rung 1 (0.95) is "AR xu ly", Action.LIQUIDATE',
         'fix': 'a profile whose first closing rung is not the third is '
                'refused rather than mapped'},
        {'id': 'F4', 'status': 'fixed',
         'where': 'exchange.py FORCED_LIQUIDATION (MUST #3, 2026-08-27)',
         'what': 'FORCED_LIQUIDATION now executes a real offsetting order '
                 'through the order path rather than only reporting',
         'evidence': 'the uncured PLUTUS_DEFAULT leg is force-closed on '
                     '2022-10-06 -- reported at 09:30 (executed False, the fill '
                     'has not landed), filled at 14:45 (executed True) -- and '
                     'the book is flat afterwards, three sessions before '
                     'expiry, so the exit is a realised close-out, not an '
                     'EXPIRY_SETTLED row',
         'fix': 'the close runs through the order path (band, tick, lot); a '
                'locked or bandless book refuses it and the position rides, '
                'but where liquidity admits it, it fills'},
        {'id': 'F5', 'status': 'fixed',
         'where': 'exchange._overnight_margin, deposit.py settle_daily (W1)',
         'what': 'variation margin now settles in cash daily: settle_daily is '
                 'wired into the overnight layer, so the deposit moves with the '
                 'mark and the VM baseline rolls each session',
         'evidence': 'the deposit steps 99,948,008 -> 97,148,008 -> ... -> '
                     '69,228,008 before the forced close instead of sitting '
                     'static, and each close carries VM == 0; the run has moved '
                     'off the as-built column onto the settled one, its '
                     'utilisation strictly below as-built every session after '
                     'the first',
         'fix': 'settle_daily settles the day position P&L to cash and rolls '
                'the baseline once per settlement day; '
                'cash_settlement_divergence() still records how far the two '
                'models were apart (worst gap the up-day 2022-10-12, 1.2013 '
                'as-built against 2.8432 cash-settled)'},
        {'id': 'F6', 'status': 'declared',
         'where': "the profiles' initial_margin_ratio",
         'what': 'a profile publishes its own IM ratio and the session does '
                 'not use it; every requirement here is built on the dated '
                 'VSD rate, 0.13 on these dates',
         'evidence': 'PLUTUS_DEFAULT publishes 0.1785 and VNDIRECT 0.175, '
                     'both absolute ratios for the 0.17 era',
         'fix': 'not made -- margin_buffer is an add-on above the VSD rate at '
                'the simulated instant, and no date-free subtraction turns an '
                'absolute 2025 ratio into a 2022 buffer'},
        {'id': 'F7', 'status': 'declared',
         'where': 'the settlement and trading calendars',
         'what': "every run reports settlement_calendar_id "
                 "'weekday-only-UNSOURCED', and the cure deadline is measured "
                 'on the weekday trading calendar',
         'evidence': "the 2022-10-03 call's deadline of 2022-10-04 08:45 is "
                     'right because 2022-10-04 traded; the same arithmetic '
                     'across a Tet break would not be',
         'fix': 'not made -- no calendar data ships (A64/A65); the scenario '
                'asserts the deadline and the UNSOURCED id together'},
        {'id': 'F8', 'status': 'declared',
         'where': "rulebook.py, charge id vsdc_derivatives_position_management",
         'what': 'no position-management fee is levied, because the gazetted '
                 'row ends 2022-01-01 when the basis moved to per-fill -- but '
                 "the rulebook's own note records that brokers went on "
                 'billing the per-day fee through at least 2024-07-11',
         'evidence': '4 open contracts x 2,550d x 19 sessions = 193,800d that '
                     'a real 2022 retail account would have paid and this run '
                     'does not, 0.19% of the deposit',
         'fix': 'nothing to fix -- the run applies the gazetted schedule, '
                'which is the right default. Recorded so a cost comparison '
                'against a real 2022 statement is not read as a defect'},
        {'id': 'F9', 'status': 'declared',
         'where': 'the event stream against the snapshot stream',
         'what': 'a snapshot is taken after the whole step and an event is '
                 'emitted during it, so the two disagree at exactly the '
                 'instants that matter and joining them on the timestamp is '
                 'unsound',
         'evidence': 'on 2022-10-03 the cured leg emits margin_call at 0.9176 '
                     'and the snapshot at the same instant reads ok at '
                     '0.7935, because the strategy cured in between; on '
                     '2022-10-06 14:45 the ladder marks a breach at 1.0146 on '
                     'four contracts and MUST #3 offsets them in the same '
                     'step, so the snapshot reads ok on an empty account',
         'fix': 'nothing to fix -- every number is right about the moment it '
                'describes. Recorded because a report built by joining the '
                'two streams shows a margin call on a healthy account and a '
                'forced liquidation on an empty one'},
        {'id': 'F10', 'status': 'fixed',
         'where': 'exchange.py _overnight_margin, session/overnight.py, '
                  'scenario_margin.py',
         'what': 'the overnight margin layer had no runtime path at all: '
                 'scenario_margin.py -- 1,069 executable lines implementing '
                 'QD 26 Phu luc 2, unit-tested and checked against TCBS\'s '
                 'own worked example -- had zero call sites anywhere in src/ '
                 'or validation/, and every derivatives run nevertheless '
                 'reported a full margin history with indeterminate=0',
         'evidence': 'this window now produces 19 end-of-day requirements, '
                     'one per session, and the last of them -- the expiry -- '
                     'is a DETERMINATE ZERO with flat=True, because the '
                     'contract cash-settled in the same advance and nothing '
                     'is carried past that close. Component '
                     '"margin.derivatives.overnight" appears in exercised. '
                     'The model is PRE_KRX_CONTINUOUS and not the grid, '
                     'because RuleName.MARGIN_MODEL records one mechanism and '
                     'no separate end-of-day model to 2025-05-04 -- running '
                     'the grid on a 2022 account would report a number under '
                     'a regulation that did not exist',
         'fix': 'the layer is dated by the rulebook and modelled by the '
                'broker profile (survey finding F-1); where a parameter is '
                'unavailable it is INDETERMINATE with the input named, never '
                'the intraday number under a different label'},
        {'id': 'F11', 'status': 'fixed',
         'where': 'session/overnight.py, exchange._overnight_margin (W1)',
         'what': 'past the KRX cutover the two layers now COINCIDE: Phu luc 2 '
                 'section 6.2 has no VM term because QD 26 Dieu 20 settles '
                 'position P&L as a separate T+1 cash movement -- and W1 now '
                 'makes that movement, so the continuous IM+VM view carries '
                 'VM == 0 at the close and equals the grid (F5)',
         'evidence': 'measured in expiry-overnight.run_post_krx_overnight_'
                     'layer: 60,044,000d intraday against 60,044,000d '
                     'overnight on one 2-lot VN30F position, difference zero; '
                     'the variation_margin_unsettled assumption is gone',
         'fix': 'settle_daily is wired into the overnight layer, so the VM is '
                'paid rather than carried and the two requirements agree; no '
                'grid result is now computed over an unsettled VM'},
    )


# --------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------

def _fmt(value: Any, places: str = '0.0001') -> str:
    if value is None:
        return '-'
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal(places)))
    return str(value)


def main() -> int:                                 # pragma: no cover - report
    """Run every leg and print the report. Returns a process exit code."""
    source = datahub_source()
    price_by_day = closes(source, CONTRACT, WINDOW_START, WINDOW_END)
    entry = price_by_day[WINDOW_START]

    print('=' * 78)
    print('DERIVATIVES MARGIN CALL AND FORCED CLOSE')
    print(f'{CONTRACT}  {WINDOW_START} .. {WINDOW_END}  '
          f'{LOTS} lots @ {entry}  deposit {DEPOSIT:,}')
    print('=' * 78)

    legs = [run_leg(firm, source=source) for firm in PROFILES]
    legs.append(run_leg('PLUTUS_DEFAULT', cure='transfer', source=source))
    legs.append(run_leg('PLUTUS_DEFAULT', cure='reduce', source=source))

    print()
    print('--- per profile ---')
    for leg in legs:
        provenance = leg.result.provenance
        terms = leg.profile.to_broker_terms()
        firsts = first_events(leg.result)
        print(f'{leg.name:26s} ladder '
              f'{terms.warning_utilisation}/{terms.margin_call_utilisation}/'
              f'{terms.forced_close_utilisation}  '
              f'block={provenance.block_opening_utilisation}  '
              f'model={provenance.margin_model}'
              f'{" (ASSUMED)" if provenance.margin_model_is_assumed else ""}')
        for kind in ('margin_warning', 'margin_call', 'forced_liquidation'):
            when = firsts.get(kind)
            print(f'    first {kind:20s} {when if when else "never"}')
        print(f'    identities {len(leg.result.identities) - len(leg.result.failed_identities)}'
              f'/{len(leg.result.identities)} held   '
              f'topped up {leg.strategy.topped_up:,}   '
              f'contracts closed early {leg.strategy.reduced}   '
              f'deposit out {deposit_trail(leg)[-1][3]:,}')

    print()
    print('--- the uncured PLUTUS_DEFAULT ladder, session by session ---')
    uncured = legs[0]
    oracle = independent_requirement(price_by_day, entry=entry)
    print(f'{"date":12s} {"close":>8s} {"IM":>14s} {"VM":>14s} {"MR":>14s} '
          f'{"assets":>14s} {"util":>8s}  status')
    for snapshot in uncured.result.snapshots:
        if snapshot.phase != 'close':
            continue
        day = snapshot.ts.date()
        row = oracle.get(day, {})
        print(f'{day!s:12s} {row.get("price", "-")!s:>8s} '
              f'{snapshot.initial_margin:>14,.0f} '
              f'{snapshot.variation_margin:>14,.0f} '
              f'{snapshot.margin_required:>14,.0f} '
              f'{snapshot.deposit_balance:>14,.0f} '
              f'{_fmt(snapshot.utilisation):>8s}  {snapshot.margin_status}')

    print()
    print('--- the three logs, uncured leg ---')
    print(f'counts {uncured.result.logs.counts()}')
    for row in uncured.result.logs.cash.to_rows():
        print(f'  cash       {row["ts"]} {row["pool"]:12s} '
              f'{row["movement"]:20s} {row["amount"]:>16s} -> '
              f'{row["balance_after"]}')
    for row in uncured.result.logs.settlement.to_rows():
        print(f'  settlement {row["ts"]} {row["action"]:16s} '
              f'{row.get("ticker")} {row.get("quantity")} {row.get("amount")}')
    for row in uncured.result.logs.trades.to_rows():
        print(f'  trade      {row["ts"]} {row["action"]:12s} '
              f'{row.get("ticker")} {row.get("quantity")} '
              f'@ {row.get("fill_price") or row.get("limit_price")}')

    print()
    print('--- finding 5 (resolved, W1): variation margin now settles in cash ---')
    # The deposit the account actually ran on -- the opening balance less the
    # entry charges. Under W1 the session now settles, so it no longer tracks
    # the "as built" column: the two columns below are the record of how far the
    # loss-carried and cash-settled models were apart.
    working_deposit = min(
        (snapshot.deposit_balance for snapshot in uncured.result.snapshots
         if snapshot.positions), default=DEPOSIT)
    print(f'both series on the deposit the run actually held, '
          f'{working_deposit:,}')
    rows = cash_settlement_divergence(price_by_day, entry=entry,
                                      deposit=working_deposit)
    print(f'{"date":12s} {"close":>8s} {"cum loss":>14s} '
          f'{"u as built":>12s} {"u cash-settled":>15s}')
    for row in rows:
        print(f'{row["date"]!s:12s} {row["price"]!s:>8s} '
              f'{row["cumulative_loss"]:>14,.0f} '
              f'{_fmt(row["as_built_utilisation"]):>12s} '
              f'{_fmt(row["cash_settled_utilisation"]):>15s}')

    print()
    print('--- findings ---')
    for finding in findings():
        print(f'  [{finding["id"]}] {finding["status"].upper():9s} '
              f'{finding["what"]}')
        print(f'        where    {finding["where"]}')
        print(f'        evidence {finding["evidence"]}')

    failed = [leg for leg in legs if not leg.result.ok]
    print()
    print(f'legs run {len(legs)}, identity failures {len(failed)}')
    return 1 if failed else 0


if __name__ == '__main__':                         # pragma: no cover
    raise SystemExit(main())
