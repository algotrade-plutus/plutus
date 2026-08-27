"""The derivatives margin scenario, asserted against the real corpus.

Every number here is either read out of ``plutus.market.session`` or computed
longhand from the daily Parquet corpus. Nothing is asserted against a
restatement of the module under test: the margin requirement is checked against
``IM = rate x contracts x multiplier x price`` with the rate taken from the
dated VSD series in ``plutus.market.margin``, and the ladder rung is checked
against ``broker_profile.assess`` -- which is the profile module's own reading
of the firm's published ladder, and knows nothing about ``deposit.py``.

The scenario module has a hyphen in its name and cannot be imported by
statement, so it is loaded by path.

Two runs, done once at module import, because each walks 19 sessions of the
corpus: the uncured PLUTUS_DEFAULT leg and the cured one. The per-profile
contrast and the two controls get their own runs.
"""

import importlib.util
import sys
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import requires_corpus

from plutus.market.margin import vsd_initial_margin
from plutus.market.session import broker_profile as bp
from plutus.market.session.deposit import MarginMonitor
from plutus.market.session.types import (
    BrokerProfile as SessionBrokerProfile, EventKind, MarginStatus, MarginView,
    OrderState, Venue,
)
from plutus.market.broker import BrokerTerms

from validation.corpus import closes, datahub_source
from validation.logs import TradeAction
from validation.runner import build_session


def _load():
    path = (Path(__file__).resolve().parents[2] / 'validation' / 'scenarios'
            / 'deriv-margin.py')
    spec = importlib.util.spec_from_file_location(
        'validation_scenarios_deriv_margin', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


dm = _load()

_ZERO = Decimal('0')

#: The two instants the runner drives every session to.
OPEN = time(9, 30)
CLOSE = time(14, 45)

#: The session the drawdown first breaches on, and the one before it.
CALL_DAY = date(2022, 10, 3)
DEADLINE_DAY = date(2022, 10, 4)
BOUNCE_DAY = date(2022, 10, 5)
TROUGH_DAY = date(2022, 10, 11)
EXPIRY_DAY = date(2022, 10, 20)


# --------------------------------------------------------------------------
# Runs, done once
# --------------------------------------------------------------------------

@pytest.fixture(scope='module')
def source():
    return datahub_source()


@pytest.fixture(scope='module')
def prices(source):
    return closes(source, dm.CONTRACT, dm.WINDOW_START, dm.WINDOW_END)


@pytest.fixture(scope='module')
def uncured(source):
    return dm.run_leg('PLUTUS_DEFAULT', source=source)


@pytest.fixture(scope='module')
def cured(source):
    return dm.run_leg('PLUTUS_DEFAULT', cure='transfer', source=source)


@pytest.fixture(scope='module')
def reduced(source):
    return dm.run_leg('PLUTUS_DEFAULT', cure='reduce', source=source)


def _closes(steps, kind):
    return tuple(step for step in steps if step.kind == kind)


def _snapshot(result, day, phase='close'):
    for snapshot in result.snapshots:
        if snapshot.ts.date() == day and snapshot.phase == phase:
            return snapshot
    raise AssertionError(f'no {phase} snapshot for {day}')


# --------------------------------------------------------------------------
# The window is the window the scenario says it is
# --------------------------------------------------------------------------

@requires_corpus
def test_the_window_is_a_real_drawdown_and_the_entry_is_not_at_the_requirement(
        uncured, prices):
    """The premise, checked before anything is concluded from it.

    Two things have to be true or the whole scenario proves nothing. The market
    has to actually fall -- if it does not, a margin call is a bug -- and the
    account has to start with room. ``docs/reference/margin-model-
    adjudication.md`` retracted a published figure precisely because it was
    computed at funding = 1x the requirement, where a 100% call rate is an
    arithmetic identity rather than a finding.
    """
    assert len(uncured.result.window.sessions) == 19
    assert uncured.result.sessions_run == 19
    assert prices[dm.WINDOW_START] == Decimal('1192.0')
    assert prices[TROUGH_DAY] == Decimal('989.0')
    assert prices[EXPIRY_DAY] == Decimal('1058.0')

    entry = _snapshot(uncured.result, dm.WINDOW_START)
    assert entry.positions == {dm.CONTRACT: dm.LOTS}
    # 61,984,000 of requirement against 99,948,008 of deposit: the account has
    # 38% of its margin capacity spare on the day it opens.
    assert entry.margin_required == Decimal('61984000.000')
    assert entry.utilisation < Decimal('0.63')
    assert entry.margin_status == 'ok'
    assert uncured.profile.to_broker_terms().warning_utilisation > entry.utilisation


# --------------------------------------------------------------------------
# The ladder fires at the right rung, on the right day, at the right number
# --------------------------------------------------------------------------

@requires_corpus
def test_every_requirement_matches_the_formula_computed_longhand(uncured,
                                                                 prices):
    """``MR = IM + VM`` against multiplication, not against ``deposit.py``.

    The independent oracle takes the IM rate from
    :func:`plutus.market.margin.vsd_initial_margin` -- the dated VSD series,
    which is not the margin engine -- and does the arithmetic by hand. If this
    passes, every utilisation the scenario reports is a number a reader can
    reproduce from the corpus with a calculator.

    It also pins the rate itself. 0.13 is what was in force on these dates;
    0.17 arrives 2022-12-15, after the window, and a run that silently picked
    it up would inflate every requirement by 31% and every rung would fire
    early.
    """
    oracle = dm.independent_requirement(prices, entry=Decimal('1192.0'))
    assert vsd_initial_margin(dm.WINDOW_START) == Decimal('0.13')

    checked = 0
    for snapshot in uncured.result.snapshots:
        if snapshot.phase != 'close' or not snapshot.positions:
            continue
        row = oracle[snapshot.ts.date()]
        assert snapshot.initial_margin == row['initial_margin'], snapshot.ts
        assert snapshot.variation_margin == row['variation_margin'], snapshot.ts
        assert snapshot.margin_required == row['required'], snapshot.ts
        checked += 1
    assert checked == 18            # every session but the expiry


@requires_corpus
def test_the_call_fires_on_the_first_session_that_crosses_the_call_rung(
        uncured):
    """0.9314 on 2022-10-03, and nothing before it.

    The four sessions before are a real drawdown -- 1192.0 to 1150.0, a 6.9%
    unrealised loss -- and the account is inside its ladder for all of them.
    PLUTUS_DEFAULT's rungs are 0.80/0.90/0.95 and the account goes from 0.7664
    to 0.9314 in one session, so it crosses the warning rung and the call rung
    together. The monitor reports **one** step and does not invent the warning
    that never fired: exactly what ``on_mark``'s docstring promises for a jump.
    """
    steps = dm.ladder_steps(uncured.result)
    assert steps[0].kind == 'margin_call'
    assert steps[0].ts == datetime.combine(CALL_DAY, OPEN)
    assert steps[0].utilisation.quantize(Decimal('0.0001')) == Decimal('0.9314')
    assert steps[0].required == Decimal('93095200.000')
    assert steps[0].deposit_balance == Decimal('99948008')

    # Nothing at all before the call, on any rung.
    before = [s for s in steps if s.ts.date() < CALL_DAY]
    assert before == []
    for day in (date(2022, 9, 27), date(2022, 9, 28), date(2022, 9, 29),
                date(2022, 9, 30)):
        assert _snapshot(uncured.result, day).margin_status == 'ok'


@requires_corpus
def test_the_call_carries_a_deadline_and_it_is_the_next_session_open(uncured):
    """A call is state with a window, and the window is a trading question.

    ``cure_window_sessions`` comes off the profile's own call rung
    (PLUTUS_DEFAULT's Muc 2 publishes ``CureSpec(SESSIONS, 1)``) and the
    deadline is measured through the trading calendar, not in calendar days.
    08:45 is HNXDS's open.

    The second assertion is the honest half. The calendar under this run is the
    unsourced weekday default, and 2022-10-04 is right only because that
    Tuesday traded. Asserting the deadline without asserting the calendar's id
    would publish a correct number as though it were a sound method.
    """
    assert uncured.profile.ladder[1].cure.sessions == 1
    call = dm.ladder_steps(uncured.result)[0]
    assert call.cure_by == datetime.combine(DEADLINE_DAY, time(8, 45))
    assert (uncured.result.provenance.settlement_calendar_id
            == 'weekday-only-UNSOURCED')


@requires_corpus
def test_an_uncured_call_force_closes_at_the_deadline_and_not_before(uncured):
    """The cure window is respected in both directions.

    The account is above the call rung at the 2022-10-03 close as well, and
    nothing is emitted: an outstanding call inside its window is state, not a
    per-mark reminder. The first mark at or after 2022-10-04 08:45 is the
    09:30 step of 2022-10-04, and that is where the forced close lands.
    """
    steps = dm.ladder_steps(uncured.result)
    same_session_close = [s for s in steps
                          if s.ts == datetime.combine(CALL_DAY, CLOSE)]
    assert same_session_close == []
    assert _snapshot(uncured.result, CALL_DAY).margin_status == 'call'

    forced = _closes(steps, 'forced_liquidation')
    assert forced[0].ts == datetime.combine(DEADLINE_DAY, OPEN)
    assert forced[0].cure_by == datetime.combine(DEADLINE_DAY, time(8, 45))
    # Escalated by the elapsed deadline, not by the level: 0.9335 is still
    # below PLUTUS_DEFAULT's own 0.95 forced-close rung.
    assert forced[0].utilisation < Decimal('0.95')


@requires_corpus
def test_the_session_rung_agrees_with_the_profiles_own_reading_at_every_mark(
        uncured):
    """``deposit.margin_status`` against ``broker_profile.assess``.

    Two independent readings of the same ladder: one is the session's, one is
    the profile module's, and the profile module imports neither margin engine.
    If they disagreed, the bridge from a firm's published rungs into
    ``BrokerTerms`` would be lying about which rung an account is on -- and
    every event in the run would name the wrong action.
    """
    expected = {None: 'ok', 0: 'warning', 1: 'call', 2: 'forced'}
    checked = 0
    for snapshot in uncured.result.snapshots:
        reading = bp.assess(uncured.profile,
                            required=snapshot.margin_required,
                            assets=snapshot.deposit_balance, warn_once=False)
        assert expected[reading.rung_index] == snapshot.margin_status, (
            snapshot.ts, snapshot.phase, snapshot.utilisation)
        checked += 1
    assert checked == 38            # both steps of all 19 sessions


# --------------------------------------------------------------------------
# The cure
# --------------------------------------------------------------------------

@requires_corpus
def test_answering_the_call_clears_it_and_buys_three_sessions(cured, uncured):
    """The same window, the same position, one act: a 17,000,000d transfer.

    The amount is not chosen here. PLUTUS_DEFAULT's call rung publishes
    ``TargetRef.RUNG_1``, so the level to restore to is its own Muc 1 at 0.80,
    and the strategy transfers ``required / 0.80 - balance`` rounded up to a
    whole million because that is how a person moves money.

    What it buys is the measurement: forced on 2022-10-04 without the transfer,
    2022-10-07 with it. Three sessions -- and the account is closed in the end
    anyway, which is the honest result. A cure is not a rescue.
    """
    assert cured.strategy.topped_up == Decimal('17000000')
    assert len(cured.strategy.top_ups) == 1
    assert cured.strategy.top_ups[0][0] == datetime.combine(CALL_DAY, OPEN)

    call = dm.ladder_steps(cured.result)[0]
    assert call.kind == 'margin_call'
    assert call.ts == datetime.combine(CALL_DAY, OPEN)

    # Cured inside the session it arrived in, and never escalated at the
    # deadline.
    assert _snapshot(cured.result, CALL_DAY).margin_status == 'ok'
    assert _snapshot(cured.result, DEADLINE_DAY).margin_status == 'ok'
    forced = _closes(dm.ladder_steps(cured.result), 'forced_liquidation')
    assert forced[0].ts.date() == date(2022, 10, 7)

    uncured_forced = _closes(dm.ladder_steps(uncured.result),
                             'forced_liquidation')
    assert uncured_forced[0].ts.date() == DEADLINE_DAY
    survived = [d for d in cured.result.window.sessions
                if DEADLINE_DAY <= d < date(2022, 10, 7)]
    assert len(survived) == 3


@requires_corpus
def test_curing_by_closing_a_contract_moves_the_deposit_by_the_realised_pnl(
        reduced):
    """The second of the three answers, and the only one that realises P&L.

    ``MarginMonitor`` names three responses to a call -- transfer, reduce, or
    do nothing -- and reducing is a different code path end to end. The
    offsetting order raises no worst-case net, so it reserves nothing and is
    admitted on a breaching account (QD 26 Dieu 13.2.a). On the fill the
    deposit moves by the realised P&L on the contract that left, **measured
    from the variation-margin reference**, which is exactly the amount of VM
    that stops being charged -- the design property that makes a double count
    impossible.

    One contract at 1102.6 out of a book referenced at 1192.0:
    100,000 x (1102.6 - 1192.0) = -8,940,000d, and the requirement drops from
    four contracts' worth to three.
    """
    assert reduced.strategy.reductions[0] == (
        datetime.combine(CALL_DAY, OPEN), 1)

    trail = dm.deposit_trail(reduced)
    realised = [(entry[0].date(), entry[1]) for entry in trail
                if entry[2].startswith('realised close-out')]
    assert realised[0] == (CALL_DAY, Decimal('-8940000.0'))
    assert realised[0][1] == (Decimal('100000')
                              * (Decimal('1102.6') - Decimal('1192.0')))

    before = _snapshot(reduced.result, date(2022, 9, 30))
    after = _snapshot(reduced.result, CALL_DAY)
    assert before.positions == {dm.CONTRACT: 4}
    assert after.positions == {dm.CONTRACT: 3}
    assert after.deposit_balance == Decimal('90995591.0')
    # Cured inside the session the call arrived in, and by three quarters of
    # the book rather than by fresh cash.
    assert after.margin_status == 'ok'
    # Below PLUTUS_DEFAULT's Muc 1, which is the level its call rung publishes
    # as the target -- the strategy sized the reduction from that and did not
    # invent it.
    assert after.utilisation < Decimal('0.80')
    assert reduced.strategy.topped_up == _ZERO


@requires_corpus
def test_every_dong_of_a_book_closed_at_four_prices_reconciles(reduced):
    """The hardest accounting case in the scenario, checked to the dong.

    Four contracts leave at four different prices -- one on 2022-10-03, one on
    2022-10-19, two at the 2022-10-20 settlement -- and each leg is priced off
    the same variation-margin reference, because ``settle_daily`` never rolls
    it. Total position P&L is
    ``100,000 x [(1102.6 - 1192) + (1053 - 1192) + 2 x (1058 - 1192)]``
    = -49,640,000d, and the deposit walks from 100,000,000d to 50,269,742d
    through that plus 90,258d of charges, with no movement unaccounted for.
    """
    trail = dm.deposit_trail(reduced)
    position_pnl = sum(entry[1] for entry in trail
                       if entry[2].startswith('realised close-out')
                       or entry[2].startswith('final settlement'))
    assert position_pnl == Decimal('100000') * (
        (Decimal('1102.6') - Decimal('1192.0'))
        + (Decimal('1053.0') - Decimal('1192.0'))
        + 2 * (Decimal('1058.0') - Decimal('1192.0')))
    assert position_pnl == Decimal('-49640000.0')

    charges = sum(entry[1] for entry in trail if 'charges on' in entry[2])
    assert charges == Decimal('-90258')
    assert dm.DEPOSIT + position_pnl + charges == Decimal('50269742.0')
    assert trail[-1][3] == Decimal('50269742.0')

    # The trail is a closed chain: every balance_after follows from the one
    # before it and the movement in between.
    for previous, current in zip(trail, trail[1:]):
        assert previous[3] + current[1] == current[3]

    # And the session agrees: nothing held, nothing reserved.
    assert reduced.session.positions() == {}
    assert reduced.session._derivatives.resting_order_margin() == _ZERO
    assert reduced.result.ok


@requires_corpus
def test_the_forced_latch_releases_and_a_genuinely_new_call_can_fire(reduced):
    """The other half of finding 1: the latch is not a permanent gag.

    On the reduce leg the account is force-closed from 2022-10-07, comes back
    to the warning rung on 2022-10-18 when the market recovers, and is called
    again on 2022-10-19 with a fresh 2022-10-20 08:45 deadline. That second
    call is real -- it followed a clearance -- and the strategy answers it by
    closing a second contract.

    Without a release condition the fix in finding 1 would silence every
    subsequent call for the life of the account, which would be a worse bug
    than the one it replaced.
    """
    steps = dm.ladder_steps(reduced.result)
    kinds = Counter(step.kind for step in steps)
    assert kinds['margin_call'] == 2
    assert kinds['margin_warning'] == 2

    calls = _closes(steps, 'margin_call')
    assert calls[0].ts == datetime.combine(CALL_DAY, OPEN)
    assert calls[1].ts == datetime.combine(date(2022, 10, 19), OPEN)
    assert calls[1].cure_by == datetime.combine(date(2022, 10, 20),
                                                time(8, 45))

    # The clearance that released the latch sits between them.
    between = [s for s in steps if calls[0].ts < s.ts < calls[1].ts]
    assert between[-1].kind == 'margin_warning'
    assert between[-1].ts == datetime.combine(date(2022, 10, 18), OPEN)

    assert reduced.strategy.reductions[1] == (
        datetime.combine(date(2022, 10, 19), OPEN), 1)


@requires_corpus
def test_the_market_cures_a_call_by_itself_and_the_monitor_reports_it(uncured):
    """2022-10-05 bounces 13.2 points and the uncured account comes back.

    The cure window is not only about what the trader does. On the uncured leg
    the account is force-closed on 2022-10-04, and the next session the market
    lifts it from 0.9335 to 0.8876 -- back to the warning rung -- and the
    monitor says so. That is the de-escalation the machine is allowed to make,
    and it is the one the forced latch deliberately leaves open.
    """
    warnings_ = _closes(dm.ladder_steps(uncured.result), 'margin_warning')
    assert len(warnings_) == 1
    assert warnings_[0].ts == datetime.combine(BOUNCE_DAY, OPEN)
    assert _snapshot(uncured.result, BOUNCE_DAY).margin_status == 'warning'
    assert warnings_[0].utilisation < Decimal('0.90')


@requires_corpus
def test_a_forced_close_does_not_re_grant_the_cure_window(uncured):
    """Finding 1, pinned. No call may follow a forced close uncured.

    Before the fix the uncured leg emitted ``margin_call`` at 2022-10-04 14:45
    -- five hours after being force-closed at 09:30, at a *worse* utilisation
    -- with ``cure_by`` pushed out a further session. The sequence de-escalated
    and the account was handed a second grace period it had not earned.

    Asserted twice over: on the emitted sequence here, and on the monitor in
    isolation below, because a scenario that only checks the corpus run cannot
    say the state machine is right, only that this window did not expose it.
    """
    steps = dm.ladder_steps(uncured.result)
    seen_forced = False
    for step in steps:
        if step.kind == 'forced_liquidation':
            seen_forced = True
        elif step.kind == 'margin_call':
            assert not seen_forced, (
                f'a margin call at {step.ts} after a forced close, with no '
                f'warning or clearance in between')
        elif step.kind == 'margin_warning':
            seen_forced = False

    # Exactly one call in the whole run, and it precedes the first forced.
    assert Counter(s.kind for s in steps)['margin_call'] == 1
    assert steps[0].kind == 'margin_call'
    assert steps[1].kind == 'forced_liquidation'
    assert steps[1].ts.date() == DEADLINE_DAY
    assert steps[2].ts == datetime.combine(DEADLINE_DAY, CLOSE)
    assert steps[2].kind == 'forced_liquidation'


def test_the_forced_latch_holds_without_the_corpus():
    """The state machine, driven directly, with no market in the way.

    ``MarginMonitor`` takes a ``MarginView`` and a clock; nothing about the
    latch needs a corpus. Four marks: a call, the escalation at the deadline, a
    still-breached mark at the call level, and the clearance. Fails without the
    fix on the third.
    """
    terms = BrokerTerms()

    class Calendar:
        def next_session_open(self, ts, venue, rules):
            return datetime(ts.year, ts.month, ts.day + 1, 8, 45)

    def view(status, ts, utilisation):
        return MarginView(
            initial_margin=Decimal('90'), variation_margin=_ZERO,
            deposit_balance=Decimal('100'), posted_margin=Decimal('90'),
            resting_order_margin=_ZERO, status=status, as_of=ts,
            cure_by=None, stale_marks=())

    monitor = MarginMonitor(terms, Calendar())
    t0 = datetime(2023, 1, 4, 9, 30)
    t1 = datetime(2023, 1, 5, 9, 30)
    t2 = datetime(2023, 1, 5, 14, 45)
    t3 = datetime(2023, 1, 6, 9, 30)

    (call,) = monitor.on_mark(None, view(MarginStatus.CALL, t0, None), None, t0)
    assert call.status is MarginStatus.CALL
    assert call.cure_by == datetime(2023, 1, 5, 8, 45)

    (forced,) = monitor.on_mark(None, view(MarginStatus.CALL, t1, None), None, t1)
    assert forced.status is MarginStatus.FORCED
    assert monitor.in_forced_breach

    # The mark that used to open a second call.
    (again,) = monitor.on_mark(None, view(MarginStatus.CALL, t2, None), None, t2)
    assert again.status is MarginStatus.FORCED
    assert again.cure_by is None
    assert monitor.outstanding_call is None

    (cleared,) = monitor.on_mark(None, view(MarginStatus.WARNING, t3, None),
                                 None, t3)
    assert cleared.status is MarginStatus.WARNING
    assert not monitor.in_forced_breach


# --------------------------------------------------------------------------
# Segregation
# --------------------------------------------------------------------------

@requires_corpus
def test_the_equity_account_is_untouched_while_the_deposit_is_liquidated(
        uncured):
    """The whole point of a segregated deposit, on a run that needed the cash.

    That account is force-closed twelve sessions running while holding
    500,000,000d of settled securities cash -- five times the largest shortfall
    the window raises -- and 1,000 settled FPT. Neither moves. There is no
    auto-transfer in Vietnam and there is none here.
    """
    for snapshot in uncured.result.snapshots:
        assert snapshot.settled_cash == dm.EQUITY_CASH, snapshot.ts
        assert snapshot.committed_cash == _ZERO
        assert snapshot.advanced == _ZERO
        assert snapshot.holdings[dm.EQUITY_TICKER]['settled'] == dm.EQUITY_LOTS
        assert snapshot.holdings[dm.EQUITY_TICKER]['committed'] == 0

    securities_rows = [row for row in uncured.result.logs.cash.to_rows()
                       if row['pool'] == 'securities']
    assert len(securities_rows) == 1
    assert securities_rows[0]['movement'] == 'opening_balance'

    # And the account really was short: at the trough the requirement exceeded
    # the deposit by more than 32,000,000d, with half a billion next door.
    trough = _snapshot(uncured.result, TROUGH_DAY)
    assert trough.margin_required - trough.deposit_balance > Decimal('32000000')
    assert trough.margin_status == 'forced'


@requires_corpus
def test_the_only_bridge_between_the_pools_is_an_explicit_transfer(cured):
    """The cured leg is what using that bridge looks like, in the cash log.

    Two rows, one per pool, at the same instant, equal and opposite. A model
    that let the deposit draw on securities cash by itself would show one.
    """
    rows = [row for row in cured.result.logs.cash.to_rows()
            if row['movement'] in ('transfer_out', 'transfer_in')]
    assert len(rows) == 2
    out, into = rows
    assert out['pool'] == 'securities'
    assert out['amount'] == '-17000000'
    assert out['balance_after'] == '483000000'
    assert into['pool'] == 'derivatives'
    assert into['amount'] == '17000000'
    assert into['balance_after'] == '116948008'
    assert out['ts'] == into['ts']

    for snapshot in cured.result.snapshots:
        if snapshot.ts >= datetime.combine(CALL_DAY, OPEN):
            assert snapshot.settled_cash == dm.EQUITY_CASH - Decimal('17000000')
        else:
            assert snapshot.settled_cash == dm.EQUITY_CASH
        assert snapshot.holdings[dm.EQUITY_TICKER]['settled'] == dm.EQUITY_LOTS


# --------------------------------------------------------------------------
# Two profiles, and outcomes that differ as the profiles predict
# --------------------------------------------------------------------------

@requires_corpus
def test_three_ladders_separate_the_same_position_by_four_sessions(source):
    """PLUTUS_DEFAULT, SSI_FOREIGN and TCBS on one identical account.

    Same contract, same 4 lots, same 100,000,000d, same window, same fill
    policy. The only variable is the firm's published ladder, and it moves the
    first breach by four sessions and changes which rungs fire at all:

    * **SSI_FOREIGN** (0.75/0.80/0.85) warns on 2022-09-29, four sessions
      before PLUTUS_DEFAULT says anything, and closes on 2022-10-03. It never
      issues a call, because 2022-10-03 crosses its 0.80 and its 0.85 in one
      move.
    * **TCBS** (0.85/0.87/0.90) has three points between its rungs, so
      2022-10-03 clears all three: no warning, no call, straight to a forced
      close.
    * **PLUTUS_DEFAULT** (0.80/0.90/0.95) is the only one that raises a call,
      and it does not close until the deadline passes on 2022-10-04.

    A ``{warn, call, liquidate}`` triple with one set of numbers cannot express
    that, which is the survey's whole argument.
    """
    outcomes = {}
    for firm in dm.PROFILES:
        leg = dm.run_leg(firm, source=source)
        outcomes[firm] = (dm.first_events(leg.result),
                          leg.profile.to_broker_terms())

    default, default_terms = outcomes['PLUTUS_DEFAULT']
    foreign, foreign_terms = outcomes['SSI_FOREIGN']
    tcbs, tcbs_terms = outcomes['TCBS']

    assert (default_terms.warning_utilisation,
            default_terms.margin_call_utilisation,
            default_terms.forced_close_utilisation) == (
        Decimal('0.80'), Decimal('0.90'), Decimal('0.95'))
    assert (foreign_terms.warning_utilisation,
            foreign_terms.forced_close_utilisation) == (Decimal('0.75'),
                                                        Decimal('0.85'))
    assert (tcbs_terms.warning_utilisation,
            tcbs_terms.forced_close_utilisation) == (Decimal('0.85'),
                                                     Decimal('0.90'))

    assert 'margin_warning' not in default or (
        default['margin_warning'].date() > CALL_DAY)
    assert default['margin_call'].date() == CALL_DAY
    assert default['forced_liquidation'].date() == DEADLINE_DAY

    assert foreign['margin_warning'].date() == date(2022, 9, 29)
    assert 'margin_call' not in foreign
    assert foreign['forced_liquidation'].date() == CALL_DAY

    assert 'margin_warning' not in tcbs
    assert 'margin_call' not in tcbs
    assert tcbs['forced_liquidation'].date() == CALL_DAY

    # The separation, stated as the thing the ladders bought.
    assert (default['margin_call'] - foreign['margin_warning']).days == 4
    assert (default['forced_liquidation']
            - tcbs['forced_liquidation']).days == 1


@requires_corpus
def test_the_provenance_names_the_firm_the_model_and_who_supplied_it(source):
    """A result carries which firm's policy produced it, and how much is ours.

    ``margin_model_is_assumed`` is the honest half. SSI and TCBS publish a real
    ladder and **no formula** for their client-facing number, so a run under
    either is our divisor under their levels -- a different claim from "this is
    SSI's model", and one a reader must be able to see without opening the
    profile.
    """
    default = dm.run_leg('PLUTUS_DEFAULT', source=source).result.provenance
    assert default.broker_profile_name == 'PLUTUS_DEFAULT'
    assert default.margin_model == 'IM_PLUS_VM_PLUS_DM'
    assert default.margin_model_engine == 'plutus.market.session.deposit'
    assert default.margin_model_is_assumed is False
    assert default.block_opening_utilisation == Decimal('0.80')

    tcbs = dm.run_leg('TCBS', source=source).result.provenance
    assert tcbs.broker_profile_name == 'TCBS'
    assert tcbs.margin_model == 'UNSTATED'
    assert tcbs.margin_model_is_assumed is True
    assert tcbs.block_opening_utilisation == Decimal('0.85')

    # A session configured without a firm selected nothing and claims nothing.
    bare = build_session(start=dm.WINDOW_START, end=dm.WINDOW_END,
                         venues=['HNXDS'], source=source).provenance()
    assert bare.margin_model is None
    assert bare.margin_model_engine is None
    assert bare.margin_model_is_assumed is False
    assert bare.block_opening_utilisation is None


# --------------------------------------------------------------------------
# The wiring: profile system and margin-model selection
# --------------------------------------------------------------------------

def test_the_grid_is_computed_and_still_may_not_be_put_on_the_ladder():
    """The author's sixth axis, and what changed when the grid was wired.

    **What this used to assert:** a profile whose ``user_facing_model`` was
    ``OVERNIGHT`` raised ``NotImplementedError`` naming ``scenario_margin``,
    because the module *"is not wired into ExchangeSession"*. That was true --
    it had zero call sites in ``src/`` -- and refusing beat running the
    grid-selecting profile on ``IM + VM``.

    It is wired now, through ``session/overnight.py``, and the refusal
    survives for a narrower and more specific reason: ``MarginView.required``
    is the property ``initial_margin + variation_margin`` and QD 26 Phu luc 2
    produces neither term (Dieu 20 settles position P&L as a separate cash
    movement; section 6.2 has no ``VM`` at all). Putting the grid's number on
    the ladder would mean writing it into ``initial_margin`` and zeroing
    ``variation_margin`` -- a decomposition that did not happen, which would
    corrupt ``free_deposit`` and ``posted_margin`` with it.

    So the refusal is now about the *ladder*, not about the engine, and the
    message says so. ``ExchangeSession.overnight_margin()`` computes the
    number for every profile either way.
    """
    from dataclasses import replace
    from plutus.market.session.exchange import ExchangeSession

    grid = replace(bp.get_profile('PLUTUS_DEFAULT', warn=False),
                   user_facing_model=bp.MarginLayer.OVERNIGHT,
                   margin_model_overnight=bp.MarginModel.SCENARIO_GRID)
    assert grid.margin_model is bp.MarginModel.SCENARIO_GRID
    assert grid.margin_engine == 'plutus.market.session.scenario_margin'

    profile = SessionBrokerProfile.from_margin_profile(grid)
    with pytest.raises(NotImplementedError) as caught:
        ExchangeSession._check_margin_model(profile)
    assert 'OVERNIGHT' in str(caught.value)
    assert 'MarginView' in str(caught.value)

    # An INTRADAY-facing profile carrying the grid overnight now builds, and
    # every shipped profile is in that position.
    intraday = replace(grid, user_facing_model=bp.MarginLayer.INTRADAY)
    ExchangeSession._check_margin_model(
        SessionBrokerProfile.from_margin_profile(intraday))
    for firm in dm.PROFILES:
        shipped = bp.get_profile(firm, warn=False)
        assert shipped.user_facing_model is bp.MarginLayer.INTRADAY
        assert shipped.margin_model.engine in (
            None, 'plutus.market.session.deposit')


@requires_corpus
def test_the_overnight_layer_now_runs_on_every_session_of_the_window(
        uncured):
    """The layer the fidelity audit found missing, exercised on real data.

    ``scenario_margin.py`` had zero call sites anywhere in ``src/`` or
    ``validation/`` and ``indeterminate_report()`` answered ``indeterminate=0``
    throughout, because a layer nobody calls has no evaluation to be undecided
    about. There is now one end-of-day requirement per session, and it is
    ``Component.OVERNIGHT_MARGIN`` in ``exercised`` that distinguishes "ran and
    computed" from "never ran".

    **This window is pre-KRX, so the model is the pre-KRX one and that is the
    point.** ``RuleName.MARGIN_MODEL`` records ``'pre_margin'`` to 2025-05-04
    at HIGH confidence -- one continuously-recomputed mechanism, no separate
    end-of-day model -- so running QD 26's grid on a 2022 account would report
    a number under a regulation that did not exist.

    The last session is the expiry. The contract cash-settles inside the same
    advance, so what is carried past that close is nothing: a **determinate
    zero** with ``flat`` set, which is a different fact from an undecided one.
    """
    trail = uncured.session.overnight_margins()
    assert len(trail) == 19
    assert {r.model for r in trail} == {'PRE_KRX_CONTINUOUS'}
    assert all(r.is_determinate for r in trail)
    assert all(r.engine == 'plutus.market.session.deposit' for r in trail)

    entry, expiry = trail[0], trail[-1]
    assert entry.as_of == date(2022, 9, 26)
    assert entry.flat is False
    assert entry.amount == Decimal('61984000.000')
    assert expiry.as_of == date(2022, 10, 20)
    assert expiry.flat is True
    assert expiry.amount == Decimal('0')

    report = uncured.session.indeterminate_report()
    assert report.exercised['margin.derivatives.overnight'] == 19
    assert 'margin.derivatives.overnight' not in report.unexercised

    provenance = uncured.session.provenance()
    assert provenance.overnight_model == 'PRE_KRX_CONTINUOUS'
    assert provenance.overnight_determinate == 19
    assert provenance.overnight_indeterminate == 0


@requires_corpus
def test_the_overnight_requirement_is_not_the_intraday_one(uncured):
    """It drops the resting-order margin, and it is read at the close.

    ``account_margin_requirement`` adds ``resting_order_margin`` to ``IM +
    VM`` because a live order has margin lodged against it. Past the close the
    day's orders are gone, so the overnight figure is the held book alone --
    which is why the layer passes ``resting=()`` rather than reusing the mark's
    view.
    """
    trail = {r.as_of: r for r in uncured.session.overnight_margins()}
    crash = trail[date(2022, 10, 3)]
    # 4 contracts at the 2022-10-03 close of 1102.6, at the dated VSD ratio,
    # plus the loss against the 1192.0 entry. The ratio is read from the
    # dated series rather than written down, because it steps 0.13 -> 0.17 on
    # 2022-12-15 and a constant here would pass for the wrong reason.
    rate = vsd_initial_margin(date(2022, 10, 3))
    assert rate == Decimal('0.13')
    initial = rate * Decimal('4') * Decimal('100000') * Decimal('1102.6')
    variation = Decimal('4') * Decimal('100000') * (Decimal('1192.0')
                                                    - Decimal('1102.6'))
    assert crash.amount == initial + variation
    assert crash.amount == Decimal('93095200.000')


def test_naming_a_firm_and_a_ladder_level_in_one_config_is_refused():
    """A firm's name over our number is the failure the profile exists to stop.

    Not a merge and not a precedence rule: a refusal, so the caller has to
    choose whose ladder the result is.
    """
    from plutus.market.session.exchange import parse_config

    payload = {
        'period': {'start': '2022-09-26', 'end': '2022-10-20'},
        'exchange_rules': {'venues': ['HNXDS']},
        'broker_profile': {'firm': 'TCBS', 'warning_utilisation': '0.50'},
    }
    with pytest.raises(ValueError) as caught:
        parse_config(payload)
    assert 'TCBS' in str(caught.value)
    assert 'warning_utilisation' in str(caught.value)


def test_a_ladder_whose_rungs_do_not_line_up_positionally_is_refused():
    """Finding 3. MBS's liquidation level would be reported as a call.

    ``to_broker_terms`` reads ``ladder[0..2]`` into warning / call / forced by
    position, and MBS's ladder has no block-opening rung: it is ``AR duy tri``
    (NOTIFY) / ``AR xu ly`` (LIQUIDATE) / ``Nguong xu ly tai VSDC``. Filled
    from PLUTUS_DEFAULT that is 0.90 / 0.95 / 1.00, so a session would emit a
    ``MARGIN_CALL`` at 0.95 -- the level MBS closes positions at -- and would
    not force-close until the CCP's threshold. Every event on that run would
    name a milder action than MBS's own document.

    MBS is the only shipped profile with this shape, which is exactly why the
    check has to be mechanical rather than a note.
    """
    mbs = bp.get_profile('MBS', fill_from=bp.PLUTUS_DEFAULT, warn=False)
    terms = mbs.to_broker_terms()
    # The mis-mapping is real, and this is it.
    assert terms.margin_call_utilisation == Decimal('0.95')
    assert mbs.ladder[1].action is bp.Action.LIQUIDATE
    assert mbs.ladder[1].level == Decimal('0.95')

    with pytest.raises(bp.CoverageError) as caught:
        SessionBrokerProfile.from_margin_profile(mbs)
    assert 'rung 1' in str(caught.value)
    assert 'AR xu ly' in str(caught.value)

    # The profiles this scenario runs are all clean.
    for firm in dm.PROFILES:
        SessionBrokerProfile.from_margin_profile(
            bp.get_profile(firm, warn=False))


def test_profiles_that_cannot_configure_a_session_say_so_rather_than_guessing():
    """Eight of the eighteen refuse, each for a stated reason.

    Silence is the guarantee the profile module makes: a profile with no gaps
    warns nothing. The mirror of it is that a profile that cannot produce three
    rising-utilisation numbers must not be given three.
    """
    refused = {}
    for firm in bp.PROFILE_NAMES:
        try:
            SessionBrokerProfile.from_margin_profile(
                bp.get_profile(firm, warn=False))
        except bp.CoverageError as exc:
            refused[firm] = str(exc)
        except bp.BrokerProfileError as exc:   # pragma: no cover - defensive
            refused[firm] = str(exc)
    assert set(refused) == {'Vietcap', 'HSC', 'MBS', 'KIS', 'VPS', 'DNSE',
                            'VCBS', 'ACBS'}
    assert 'FALLING_COVERAGE' in refused['HSC']
    assert 'delegates' in refused['KIS']
    assert '0 rungs' in refused['DNSE']
    assert '2 rungs' in refused['Vietcap']


# --------------------------------------------------------------------------
# The block-opening rung
# --------------------------------------------------------------------------

@requires_corpus
def test_the_firms_first_rung_refuses_a_new_position_and_admits_an_offset(
        source):
    """Finding 2, and its control, at one instant on one account.

    On 2022-10-03 the account sits at 0.9314 -- past PLUTUS_DEFAULT's 0.80
    block-opening rung and past its 0.90 call. A fifth contract is refused,
    naming 0.80 as the binding constraint, while an offsetting sell of one is
    admitted. That exception is not ours: QD 26 Dieu 13.2.a requires the member
    to stop new positions on a breaching account *"ngoai tru giao dich doi ung
    de dong vi the"*.

    The control is the same run configured from the payload at the same three
    levels with no firm named. There ``block_opening_utilisation`` is ``None``
    and the *rung* gate does not exist -- but the fifth contract is still
    refused, by the **funding** gate underneath it.

    That control used to assert ``Accepted``, and in doing so it pinned a
    defect as expected behaviour. ``reserve_for_order`` tested
    ``required > free_deposit``, which excludes VM: the account had 42,612,808
    of "free" deposit and only 1,855,407.6 of room below its own 0.95
    forced-close level, and the 14,333,800 order was admitted into the gap.
    Funding it took the account to utilisation 1.0748 and status ``FORCED``
    in the same instant, on a mark that had not moved. The order now names
    ``openable`` -- ``balance x 0.95 - required``, the mirror of
    ``transfer_out``'s bound -- as the constraint that bit.

    So the two gates are distinguishable and both live: the firm leg is
    refused at the **rung** (binding constraint 0.80, a ratio), the control at
    the **funding** bound (binding constraint 1,855,407.6, an amount). The
    offsetting sell is admitted on both, which is the Dieu 13.2.a exception.
    """
    firm_leg = dm.run_leg('PLUTUS_DEFAULT', source=source,
                          open_more_on=CALL_DAY)
    (ts, utilisation, opening, offsetting), = firm_leg.strategy.admission
    assert ts == datetime.combine(CALL_DAY, OPEN)
    assert utilisation.quantize(Decimal('0.0001')) == Decimal('0.9314')
    assert opening.__class__.__name__ == 'Rejected'
    assert opening.binding_constraint == Decimal('0.80')
    assert opening.detail['block_opening_utilisation'] == Decimal('0.80')
    assert offsetting.__class__.__name__ == 'Accepted'

    control = dm.run_payload_configured(source=source, open_more_on=CALL_DAY)
    (_, control_utilisation, control_opening,
     control_offsetting), = control.strategy.admission
    assert control_utilisation == utilisation
    assert control.result.provenance.block_opening_utilisation is None
    assert control_opening.__class__.__name__ == 'Rejected'
    # Refused by the funding bound, not by the rung: no rung is configured.
    assert 'block_opening_utilisation' not in control_opening.detail
    assert control_opening.detail['required'] == Decimal('14333800.000')
    assert control_opening.detail['free_deposit'] == Decimal('42612808.000')
    assert control_opening.detail['variation_margin'] == Decimal('35760000.0')
    # 99,948,008 x 0.95 - 93,095,200. The order is 12.5m past it.
    assert control_opening.detail['openable'] == Decimal('1855407.600')
    assert control_opening.binding_constraint == Decimal('1855407.600')
    assert control_offsetting.__class__.__name__ == 'Accepted'

    # And the refusal is in the trade log, not only in the return value.
    rejections = [row for row in firm_leg.result.logs.trades.to_rows()
                  if row['action'] == TradeAction.REJECTED.value]
    assert len(rejections) == 1
    assert rejections[0]['binding_constraint'] == '0.80'
    assert rejections[0]['rule'] == 'insufficient_deposit'


# --------------------------------------------------------------------------
# Accounting: every dong, every order
# --------------------------------------------------------------------------

@requires_corpus
def test_every_dong_of_the_deposit_is_accounted_for(uncured, cured):
    """The deposit's own audit trail reconciles to the arithmetic, twice.

    ``DerivativesAccount`` keeps a signed ``DepositEntry`` with a
    ``balance_after`` for every movement, so this is a closed sum and not an
    estimate. The uncured leg has six entries and no transfer; the cured leg
    has eight and moves 17,000,000d in.

    The charges are named, not lumped: 10,800 exchange service (2,550 x 4 is
    the VSDC row, the exchange row is 2,700 x 4), 30,992 derivatives PIT
    (0.0005 x IM at entry) and 10,200 VSDC clearing at 2,550 a contract, then
    27,508 of PIT again when the contract matures -- because taxable income on
    a future is determined when the order is matched **or at contract
    maturity**, and a position carried into final settlement is never matched
    out.
    """
    trail = dm.deposit_trail(uncured)
    assert [entry[3] for entry in trail][-1] == Decimal('46320500.0')
    assert sum(entry[1] for entry in trail) == Decimal('46320500.0')
    for previous, current in zip(trail, trail[1:]):
        assert previous[3] + current[1] == current[3]

    amounts = {entry[2].split(': ')[-1]: entry[1] for entry in trail}
    assert amounts['opening deposit'] == dm.DEPOSIT
    assert amounts['exchange_service_index_future'] == Decimal('-10800')
    assert amounts['vsdc_derivatives_clearing'] == Decimal('-10200')
    # 0.0005 x (0.13 x 4 x 100,000 x 1192.0) = 0.0005 x 61,984,000
    assert amounts['pit_derivatives_transfer'] == Decimal('-27508')
    entry_pit = [e[1] for e in trail
                 if 'pit_derivatives_transfer' in e[2]][0]
    assert entry_pit == Decimal('-30992')
    assert entry_pit == -(Decimal('0.0005') * Decimal('0.13') * 4
                          * Decimal('100000') * Decimal('1192.0'))

    # 4 x 100,000 x (1058.0 - 1192.0)
    settlement = [e[1] for e in trail
                  if e[2].startswith('final settlement')]
    assert settlement == [Decimal('-53600000.0')]

    cured_trail = dm.deposit_trail(cured)
    assert [e[1] for e in cured_trail if e[2] == 'transfer in from securities'] \
        == [Decimal('17000000')]
    assert cured_trail[-1][3] == Decimal('63320500.0')
    assert (cured_trail[-1][3] - trail[-1][3]) == Decimal('17000000')


@requires_corpus
def test_the_cash_log_and_the_deposit_trail_are_the_same_movements(uncured):
    """Two independent records of the same money, reconciled against each other.

    The cash log is built by ``validation.journal`` wrapping the ledgers; the
    deposit trail is the account's own. Neither is derived from the other, so
    a movement that appears in one and not the other is a real hole -- and
    ``CashLedger`` discarding its ``ts`` and ``reason`` is exactly why the
    securities half needs wrapping at all.
    """
    trail = dm.deposit_trail(uncured)
    rows = [row for row in uncured.result.logs.cash.to_rows()
            if row['pool'] == 'derivatives']
    assert len(rows) == len(trail)
    for entry, row in zip(trail, rows):
        assert Decimal(row['amount']) == entry[1]
        assert Decimal(row['balance_after']) == entry[3]
        assert row['affects_balance'] is True


@requires_corpus
def test_every_order_reaches_a_terminal_state_and_releases_its_reservation(
        uncured):
    """No order left live, no encumbrance left standing.

    A margin scenario is exactly where a leak would hide: the position is
    breached for twelve sessions and the entry order's deposit reservation was
    converted to posted margin on the fill. Section 12 invariant 4 says the sum
    of encumbrance over live orders equals the ledgers' committed totals, and
    ``encumbrance_zero`` says it is zero when nothing is live.
    """
    records = uncured.session.orders()
    assert len(records) == 1
    assert all(record.is_terminal for record in records)
    assert records[0].state is OrderState.FILLED
    assert records[0].filled_quantity == dm.LOTS
    assert uncured.session.orders(state=OrderState.RESTING) == ()

    names = {result.name: result.passed for result in uncured.result.identities}
    assert names['encumbrance_zero'] is True
    assert names['encumbrance_matches'] is True
    assert names['deposit_segregation'] is True
    assert names['order_lifecycle'] is True
    assert uncured.result.ok


@requires_corpus
def test_the_position_settles_at_expiry_and_the_settlement_log_says_how(
        uncured):
    """The exit leg of a held-to-maturity future, in the settlement log.

    One row, and it names the tier the price came from. ``close_proxy`` with
    ``substituted=True`` is the honest answer on the Parquet corpus: the real
    final settlement price is a trimmed 14:15-14:45 index average and the daily
    bars do not carry it.
    """
    rows = uncured.result.logs.settlement.to_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row['action'] == 'expiry_settled'
    assert row['ticker'] == dm.CONTRACT
    assert row['quantity'] == dm.LOTS
    assert row['amount'] == '-53600000.0'
    assert row['detail']['settlement_source'] == 'close_proxy'
    assert row['detail']['substituted'] is True
    assert row['settlement_calendar_id'] == 'weekday-only-UNSOURCED'
    assert _snapshot(uncured.result, EXPIRY_DAY).positions == {}


# --------------------------------------------------------------------------
# The findings that are not fixed, pinned so they cannot be lost
# --------------------------------------------------------------------------

@requires_corpus
def test_the_forced_close_reports_and_does_not_execute(uncured):
    """Finding 4, with the price of it.

    24 forced liquidations over 12 distinct sessions, ``executed`` ``False`` on
    every one, and the position still open at the end of all of them. The first
    named a mark of 1102.0 on 2022-10-04; the contract settles at 1058.0, so
    the difference between the close that was reported and the one that
    happened is 4 x 100,000 x 44.0 = 17,600,000d on a 100,000,000d account.

    Counting **distinct sessions** rather than events is deliberate: the two
    marks per session mean an event count is a property of the runner's loop,
    not of the market.
    """
    forced = _closes(dm.ladder_steps(uncured.result), 'forced_liquidation')
    assert len(forced) == 24
    assert len({step.day for step in forced}) == 12
    assert {step.executed for step in forced} == {False}

    for event in uncured.result.logs.events:
        if event.kind is EventKind.FORCED_LIQUIDATION:
            assert event.detail['selection_rule'].value == 'largest_loss_first'
            assert event.detail['sequence'] == (dm.CONTRACT,)
            assert event.detail['price_basis'] == (
                'the contract mark at this instant')
            break

    # Nothing was closed: the position is intact until it expires.
    for day in (date(2022, 10, 6), TROUGH_DAY, date(2022, 10, 19)):
        assert _snapshot(uncured.result, day).positions == {dm.CONTRACT: 4}

    unclosed_cost = (Decimal(dm.LOTS) * dm.MULTIPLIER
                     * (Decimal('1102.0') - Decimal('1058.0')))
    assert unclosed_cost == Decimal('17600000.0')


@requires_corpus
def test_the_deposit_balance_never_moves_with_the_mark(uncured, prices):
    """Finding 5, first half: ``settle_daily`` has no session call site.

    The balance is 99,948,008d from the entry fill to the expiry -- 18 sessions
    -- while the mark-to-market loss reaches 81,200,000d, and the whole loss
    arrives as one movement on 2022-10-20. A replay that debits variation
    margin T+1, which is what VSDC does, will not reproduce these utilisations.
    """
    balances = {snapshot.deposit_balance
                for snapshot in uncured.result.snapshots
                if snapshot.positions}
    assert balances == {Decimal('99948008')}

    worst_loss = (Decimal(dm.LOTS) * dm.MULTIPLIER
                  * (Decimal('1192.0') - prices[TROUGH_DAY]))
    assert worst_loss == Decimal('81200000.0')
    assert _snapshot(uncured.result, TROUGH_DAY).variation_margin == worst_loss

    movements = [row for row in uncured.result.logs.cash.to_rows()
                 if row['pool'] == 'derivatives'
                 and row['movement'] == 'expiry_settlement']
    assert len(movements) == 1
    assert movements[0]['ts'].startswith(EXPIRY_DAY.isoformat())


@requires_corpus
def test_carrying_the_loss_in_the_requirement_is_not_the_same_as_settling_it(
        uncured, prices):
    """Finding 5, second half, and it is the number the docstring defends.

    ``deposit.py``'s module docstring justifies not moving the balance by
    saying the loss is carried in ``MR`` instead, "which is why doing both
    would double-count it". The arithmetic is sound; the **substitution** is
    not. Utilisation here is ``(IM + L) / D`` on a balance that never moves,
    and under real T+1 cash settlement it is ``(IM + dL) / (D - L_prev)``,
    because the previous session's P&L has already left the deposit. Those are
    different numbers and the difference **changes sign**, so "conservative"
    is not a property this substitution has.

    Measured, on the deposit this run actually held:

    * the two agree only while nothing has settled -- the first two sessions;
    * as built is the larger through 2022-10-04, by up to 4%;
    * cash settled is the larger from 2022-10-05 to the end, by up to
      **137%**;
    * the worst gap is 2022-10-12, an **up** session, because the previous
      day's 81,200,000d loss settles out on T+1 exactly as the price
      rebounds. This session reports 1.2013 where daily cash settlement gives
      2.8432, and the real account has 18,748,008d of assets left against a
      53,305,200d requirement.

    An account that cannot be drained cannot be blown, and this one is never
    drained: it reaches expiry with 46,320,500d.
    """
    rows = {row['date']: row for row in dm.cash_settlement_divergence(
        prices, entry=Decimal('1192.0'), deposit=Decimal('99948008'))}

    # The as-built column reproduces the session exactly, so the comparison is
    # like for like and not a re-derivation with a different base.
    for snapshot in uncured.result.snapshots:
        if snapshot.phase != 'close' or not snapshot.positions:
            continue
        row = rows[snapshot.ts.date()]
        assert row['as_built_utilisation'] == snapshot.utilisation

    equal = {d for d, r in rows.items()
             if r['as_built_utilisation'] == r['cash_settled_utilisation']}
    as_built_larger = {d for d, r in rows.items()
                       if r['as_built_utilisation'] > r['cash_settled_utilisation']}
    cash_larger = {d for d, r in rows.items()
                   if r['cash_settled_utilisation'] > r['as_built_utilisation']}

    assert equal == {dm.WINDOW_START, date(2022, 9, 27)}
    assert max(as_built_larger) == DEADLINE_DAY
    assert min(cash_larger) == BOUNCE_DAY
    assert as_built_larger | cash_larger | equal == set(rows)
    # The sign flips exactly once, which is why a single-signed adjective
    # cannot describe the substitution.
    assert all(d < BOUNCE_DAY for d in as_built_larger)
    assert all(d >= BOUNCE_DAY for d in cash_larger)

    trough = rows[TROUGH_DAY]
    assert trough['as_built_utilisation'].quantize(
        Decimal('0.0001')) == Decimal('1.3270')
    assert trough['cash_settled_utilisation'].quantize(
        Decimal('0.0001')) == Decimal('1.9041')

    worst = rows[date(2022, 10, 12)]
    assert worst['price'] > trough['price']            # an up day
    assert worst['as_built_utilisation'].quantize(
        Decimal('0.0001')) == Decimal('1.2013')
    assert worst['cash_settled_utilisation'].quantize(
        Decimal('0.0001')) == Decimal('2.8432')
    assert worst['cash_settled_assets'] == Decimal('18748008')
    ratios = {d: r['cash_settled_utilisation'] / r['as_built_utilisation']
              for d, r in rows.items()}
    assert max(ratios, key=ratios.get) == date(2022, 10, 12)
    assert ratios[date(2022, 10, 12)].quantize(
        Decimal('0.0001')) == Decimal('2.3669')

    # None of the cash-settled balances went negative on this window, so the
    # claim is understatement and not an unmodelled blow-up. At 6 lots it
    # would be: 6 x 100,000 x 203.0 = 121,800,000 against a 100,000,000
    # deposit.
    assert all(row['cash_settled_assets'] > _ZERO for row in rows.values())
    assert not any(row['deposit_exhausted'] for row in rows.values())


@requires_corpus
def test_the_profiles_own_initial_margin_ratio_is_not_used(uncured):
    """Finding 6, stated rather than left for a reader to discover.

    PLUTUS_DEFAULT publishes ``initial_margin_ratio = 0.1785``. Every
    requirement in this run is built on 0.13, the VSD rate in force in
    September 2022, resolved per instant by the rulebook. The two are not
    reconcilable by subtraction -- ``margin_buffer`` is an add-on above
    whatever the VSD rate is *at the simulated instant*, and 0.1785 is an
    absolute ratio published for the 0.17 era -- so nothing here pretends
    otherwise.
    """
    assert uncured.profile.initial_margin_ratio == Decimal('0.1785')
    assert uncured.session._config.broker_profile.margin_buffer == _ZERO
    assert uncured.session._derivatives.margin_buffer == _ZERO

    entry = _snapshot(uncured.result, dm.WINDOW_START)
    assert entry.initial_margin == (Decimal('0.13') * 4 * Decimal('100000')
                                    * Decimal('1192.0'))
    assert entry.initial_margin != (Decimal('0.1785') * 4 * Decimal('100000')
                                    * Decimal('1192.0'))


@requires_corpus
def test_no_position_management_fee_is_levied_and_that_is_the_gazetted_answer(
        uncured):
    """Finding 8: an accounting difference that is not an accounting hole.

    ``vsdc_derivatives_position_management`` accrues per open contract per day,
    and the rulebook's dated row **ends 2022-01-01** when VSDC moved the basis
    to per-fill. So a September-2022 run charging nothing is right, and this
    scenario's deposit is complete.

    The rulebook's own note on that row records the other half: *"Brokers
    demonstrably billed the per-day fee through at least 2024-07-11, so a run
    reproducing actual retail costs and a run applying the gazetted schedule
    disagree for three years."* This window is inside those three years, and
    the amount is 4 x 2,550 x 19 = 193,800d. Recorded here so nobody
    reconciling against a real 2022 statement reads the gap as a bug.
    """
    kinds = {charge.kind for charge in uncured.session.charges()}
    assert kinds == {'exchange_service_index_future',
                     'pit_derivatives_transfer', 'vsdc_derivatives_clearing'}
    assert 'vsdc_derivatives_position_management' not in kinds

    rules = uncured.session._rulebook.at(
        datetime.combine(dm.WINDOW_START, OPEN))
    charge_ids = {rule.charge_id for rule in rules.charges(Venue.HNXDS)}
    assert 'vsdc_derivatives_position_management' not in charge_ids

    would_have_been = (Decimal('2550') * dm.LOTS
                       * len(uncured.result.window.sessions))
    assert would_have_been == Decimal('193800')


@requires_corpus
def test_the_snapshot_rung_and_the_emitted_event_are_different_questions(
        reduced):
    """A trap this scenario would otherwise leave for the next reader.

    ``Snapshot.margin_status`` is ``MarginView.status`` -- where the account
    sits on the ladder right now. The emitted event is the **monitor's** state,
    which carries history: after a forced close, a mark that is merely at the
    call rung is reported ``FORCED``, because the position is still being
    processed. So the two disagree on 2022-10-13 through 2022-10-17, and both
    are right about different questions.

    Pinned rather than smoothed over, because a test that read the rung off the
    snapshot and the severity off the event would silently conflate them.
    """
    for day in (date(2022, 10, 13), date(2022, 10, 14), date(2022, 10, 17)):
        assert _snapshot(reduced.result, day).margin_status == 'call'
    emitted = {step.day: step.kind for step in dm.ladder_steps(reduced.result)}
    for day in (date(2022, 10, 13), date(2022, 10, 14), date(2022, 10, 17)):
        assert emitted[day] == 'forced_liquidation'


@requires_corpus
def test_no_escalation_anywhere_in_any_leg_passes_without_an_event(source):
    """The capstone: hunting for a margin call that should have fired.

    Walks every mark of all five legs -- three profiles plus the two cures --
    and checks two directions at once.

    **No miss.** Every time the rung the account sits on gets *worse* than the
    previous mark, an event has to be emitted at that instant. An escalation
    that produced no event is a margin call the account never heard, which is
    the failure mode the author named. Both steps of every session are
    checked, not only the close, so a breach that appears at 09:30 and is gone
    by 14:45 cannot hide.

    **No phantom.** Every event that *was* emitted has to sit on a mark that
    is at least at the warning rung. An event on a healthy account would be
    the mirror failure.

    38 marks per leg, five legs, and the emitted events include the ones the
    forced latch reports at call-level marks -- which is why the phantom check
    is against the warning rung and not against the event's own severity.
    """
    rank = {'ok': 0, 'warning': 1, 'call': 2, 'forced': 3}
    legs = [dm.run_leg(firm, source=source) for firm in dm.PROFILES]
    legs.append(dm.run_leg('PLUTUS_DEFAULT', cure='transfer', source=source))
    legs.append(dm.run_leg('PLUTUS_DEFAULT', cure='reduce', source=source))

    total_marks = 0
    for leg in legs:
        emitted = {step.ts for step in dm.ladder_steps(leg.result)}
        previous = 0
        for snapshot in leg.result.snapshots:
            total_marks += 1
            if not snapshot.positions and snapshot.margin_status == 'ok':
                # After the expiry there is nothing to be in breach about.
                previous = 0
                continue
            current = rank[snapshot.margin_status]
            if current > previous:
                assert snapshot.ts in emitted, (
                    f'{leg.name}: rung went {previous} -> {current} at '
                    f'{snapshot.ts} ({snapshot.utilisation}) and no margin '
                    f'event was emitted')
            previous = current

        # The phantom check is against the **event's own** numbers, not
        # against the snapshot, and that is not a convenience. A snapshot is
        # taken after the whole step -- after the strategy has cured, after an
        # expiry has settled -- while the event was emitted during it, so the
        # two disagree at exactly the instants that matter and joining them on
        # the timestamp is unsound. See the test below this one.
        for step in dm.ladder_steps(leg.result):
            reading = bp.assess(leg.profile, required=step.required,
                                assets=step.deposit_balance, warn_once=False)
            assert reading.rung_index is not None, (
                f'{leg.name}: {step.kind} at {step.ts} on an account the '
                f'firm\'s own ladder puts on no rung at all '
                f'({step.required} against {step.deposit_balance})')

    assert total_marks == 5 * 38


@requires_corpus
def test_a_snapshot_is_taken_after_the_step_and_the_event_during_it(cured,
                                                                    uncured):
    """Why the capstone test cannot join events to snapshots on the timestamp.

    Two instants in this scenario where the two streams disagree, both of them
    correct and neither of them safe to join:

    * **the cure.** On 2022-10-03 the call is emitted inside ``advance_to``,
      the strategy answers it in ``on_session``, and the snapshot is taken
      after that. The event says ``margin_call`` at 0.9314; the snapshot at
      the same instant says ``ok`` at 0.7960. The account really was called
      and really did cure, in that order.
    * **the expiry.** ``_mark_derivatives`` runs the ladder and *then* the
      expiry loop, so on 2022-10-20 at 14:45 the account is marked in breach
      at 1.0867 on four open contracts and those contracts cash-settle in the
      same call. The snapshot reports an empty account at ``ok``.

    Neither is called a defect: every number is right about the moment it
    describes. Recorded because a report built by joining the two streams
    would show a margin call on a healthy account and a forced liquidation on
    an empty one.
    """
    call = dm.ladder_steps(cured.result)[0]
    assert call.kind == 'margin_call'
    assert call.utilisation.quantize(Decimal('0.0001')) == Decimal('0.9314')
    at_the_same_instant = _snapshot(cured.result, CALL_DAY, phase='open')
    assert at_the_same_instant.ts == call.ts
    assert at_the_same_instant.margin_status == 'ok'
    assert at_the_same_instant.utilisation.quantize(
        Decimal('0.0001')) == Decimal('0.7960')

    final = dm.ladder_steps(uncured.result)[-1]
    assert final.ts == datetime.combine(EXPIRY_DAY, CLOSE)
    assert final.kind == 'forced_liquidation'
    assert final.deposit_balance == Decimal('99948008')
    assert final.utilisation.quantize(Decimal('0.0001')) == Decimal('1.0867')

    settlement = [event for event in uncured.result.logs.events
                  if event.kind is EventKind.EXPIRY_SETTLED]
    assert len(settlement) == 1
    assert settlement[0].ts == final.ts
    assert settlement[0].seq > [e.seq for e in uncured.result.logs.events
                                if e.kind is EventKind.FORCED_LIQUIDATION][-1]

    after = _snapshot(uncured.result, EXPIRY_DAY)
    assert after.positions == {}
    assert after.margin_status == 'ok'
    assert after.deposit_balance == Decimal('46320500.0')


def test_the_findings_register_is_complete_and_states_its_own_status():
    """A report cannot quietly drop the ones that are not fixed.

    ``F10`` and ``F11`` are the overnight layer: the engine that had no call
    site, and the gap between the two layers that wiring it exposed.
    """
    found = dm.findings()
    assert {row['id'] for row in found} == {'F1', 'F2', 'F3', 'F4', 'F5', 'F6',
                                            'F7', 'F8', 'F9', 'F10', 'F11'}
    assert {row['status'] for row in found} == {'fixed', 'open', 'declared'}
    assert sum(1 for row in found if row['status'] == 'fixed') == 4
    assert sum(1 for row in found if row['status'] == 'open') == 1
    for row in found:
        assert row['where'] and row['evidence'] and row['fix']


# --------------------------------------------------------------------------
# What the run could not decide
# --------------------------------------------------------------------------

@requires_corpus
def test_the_run_decided_everything_it_evaluated_and_says_on_what_evidence(
        uncured):
    """Zero indeterminate, and the reason it is zero is the fill policy.

    ``soft`` fills at the limit when the close touched it. That is a **model
    output**: this entry is priced at the day's close, and the bars carry no
    high and no low, so an order that was never touched and one that was fully
    filled are the same row. ``hard`` refuses that touch and the entry would
    never fill at all. The trade log carries the evidence on every fill so a
    reader can see which it was.

    ``indeterminate`` is still zero here and ``is_clean`` is not: the
    overnight layer runs 19 times on this window and decides every one, but
    each ``soft`` fill was taken from an interval that named the day's
    extremes absent, and those are counted separately.
    """
    report = uncured.result.indeterminate
    assert report.indeterminate == 0
    assert report.evaluations > 0
    assert uncured.result.provenance.fill_policy_kind.startswith('soft')

    fills = [row for row in uncured.result.logs.trades.to_rows()
             if row['action'] == TradeAction.FILLED.value]
    assert len(fills) == 1
    assert fills[0]['evidence'] == 'touched_at_limit'
    assert fills[0]['fill_price'] == '1192.0'
    assert fills[0]['fill_quantity'] == dm.LOTS


@requires_corpus
def test_under_the_hard_policy_this_scenario_does_not_happen_at_all(source):
    """The choice of ``soft`` is load-bearing and this is what it costs.

    Run the identical entry under ``hard`` and the order is INDETERMINATE and
    expires: the daily bar says the market touched 1192.0 and did not trade
    through it, and with no order ids there is no way to know whether this
    order was ahead in the queue. No position is opened, so there is no margin
    call, no forced close and nothing for the rest of this file to assert on.

    Two consequences worth stating plainly. The scenario's entire ladder rests
    on a **modelled** fill, not an observed one. And ``by_field`` is empty --
    the continuous-touch refusal names no ``DataField`` -- so a run reporting
    *which* data was missing gets nothing back for this case and has to say so.
    """
    from validation.runner import Scenario, Window, run_scenario, \
        sessions_from_source

    days = sessions_from_source(source, dm.CONTRACT, dm.WINDOW_START,
                                dm.WINDOW_END)
    session = build_session(
        start=dm.WINDOW_START, end=dm.WINDOW_END, venues=['HSX', 'HNXDS'],
        source=source, initial_cash=dm.EQUITY_CASH,
        initial_deposit=dm.DEPOSIT, fill_policy='hard',
        broker_profile={'firm': 'PLUTUS_DEFAULT', 'warn': False})
    result = run_scenario(Scenario(
        name='hard', session=session, source=source,
        strategy=dm.LeveragedLong(profile=None),
        window=Window(name='hard', start=dm.WINDOW_START, end=dm.WINDOW_END,
                      tickers=(dm.CONTRACT,), sessions=days)))

    assert session.positions() == {}
    assert result.indeterminate.indeterminate == 1
    assert result.indeterminate.by_field == {}
    actions = [row['action'] for row in result.logs.trades.to_rows()]
    assert actions == ['submitted', 'accepted', 'indeterminate', 'expired']
    assert dm.ladder_steps(result) == ()
