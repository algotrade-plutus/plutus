"""T+2 settlement against the real corpus, including the calendar traps.

Every number asserted here came out of ``plutus.market.session``; the only
things this file supplies are the window, the algorithm and the dates a
Vietnamese trader would have hit. The dates themselves are not computed by the
code under test -- they are written out literally, from the exchange closures
measured in the corpus and from Decision 109/QD-VSD -- because a test that
derived the expected settlement date from the same calendar the session used
would pass whatever that calendar said.

The runs are module-scoped: each is a full multi-session pass over the Parquet
corpus, and every test in its group reads the same logs an auditor would.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from conftest import requires_corpus                       # noqa: F401

from plutus.market.session.calendar import CalendarCoverageError
from plutus.market.session.types import Pool, StatefulRule
from validation import Scenario, Window, build_session, run_scenario
from validation.corpus import datahub_source
from validation.logs import CashMovement, SettlementAction, TradeAction
from validation.runner import sessions_from_source
from validation.scenarios import settlement as S

pytestmark = requires_corpus


# --------------------------------------------------------------------------
# The dates, written out rather than computed
# --------------------------------------------------------------------------

#: Tet 2022 closed the market for five consecutive weekdays.
TET_CLOSURE = tuple(date(2022, 1, 31) + timedelta(days=n) for n in range(5))

#: Trade date -> the instant the shares become sellable, under the VSDC
#: settlement calendar and the pre-2022-08-29 regime (T+2 settlement business
#: days, delivered at the next session's open).
TET_SELLABLE = {
    date(2022, 1, 26): datetime(2022, 2, 7, 9, 0),
    date(2022, 1, 27): datetime(2022, 2, 8, 9, 0),
}

#: What the shipped weekday-only calendar answers for the same two trades.
#: 2022-01-31 and 2022-02-01 are both inside the Tet closure.
TET_SELLABLE_NAIVE = {
    date(2022, 1, 26): datetime(2022, 1, 31, 9, 0),
    date(2022, 1, 27): datetime(2022, 2, 1, 9, 0),
}

#: Sale date -> the instant the proceeds are delivered, same regime.
TET_PROCEEDS = {
    date(2022, 2, 7): datetime(2022, 2, 10, 9, 0),
    date(2022, 2, 8): datetime(2022, 2, 11, 9, 0),
}

BOUNDARY_SELLABLE = {
    # pre-Decision-109: T+2 = 2022-08-26, delivered at the next session's open
    date(2022, 8, 24): datetime(2022, 8, 29, 9, 0),
    # settles on 2022-08-29 itself; see the unresolved-keying test
    date(2022, 8, 25): datetime(2022, 8, 30, 9, 0),
    # post-Decision-109: T+2 = 2022-09-05 (National Day closes 09-01, 09-02)
    date(2022, 8, 30): datetime(2022, 9, 5, 13, 0),
}

SECURITIES = Pool.SECURITIES.value


# --------------------------------------------------------------------------
# Fixtures: one pass over the corpus per arm
# --------------------------------------------------------------------------

@pytest.fixture(scope='module')
def source():
    return datahub_source()


@pytest.fixture(scope='module')
def tet(source):
    return S.run_tet_settlement(source=source)


@pytest.fixture(scope='module')
def tet_naive(source):
    return S.run_tet_settlement(calendars='naive', source=source)


@pytest.fixture(scope='module')
def boundary(source):
    return S.run_regime_boundary(source=source)


@pytest.fixture(scope='module')
def advanced(source):
    return S.run_advance_across_tet(advance=True, source=source)


@pytest.fixture(scope='module')
def unadvanced(source):
    return S.run_advance_across_tet(advance=False, source=source)


@pytest.fixture(scope='module')
def rebuy(source):
    return S.run_rebuy_on_the_advance(advance=True, source=source)


@pytest.fixture(scope='module')
def rebuy_refused(source):
    return S.run_rebuy_on_the_advance(advance=False, source=source)


def _created(run, leg):
    return tuple(e for e in run.logs.settlement.of(
        SettlementAction.TRANCHE_CREATED) if e.leg == leg)


def _settled(run, leg):
    return tuple(e for e in run.logs.settlement.of(
        SettlementAction.TRANCHE_SETTLED) if e.leg == leg)


# --------------------------------------------------------------------------
# 1. The calendar is measured, and it says so
# --------------------------------------------------------------------------

def test_the_holiday_table_is_what_the_corpus_actually_measures(source):
    """The constant is not a recalled holiday list; it is a measurement, and
    this recomputes it from four independently liquid names."""
    first, last = S.CALENDAR_COVERAGE
    measured = S.measure_non_trading_weekdays(source, first, last)
    assert measured == S.VN_NON_TRADING_WEEKDAYS
    assert len(measured) == 32


def test_tet_2022_closed_five_consecutive_weekdays_and_the_corpus_agrees(source):
    """The trap this whole scenario is built on. 2022-01-28 is the last
    session before the break and 2022-02-07 the first after it."""
    for day in TET_CLOSURE:
        assert day.weekday() < 5
        assert day in S.VN_NON_TRADING_WEEKDAYS
    sessions = sessions_from_source(source, S.TICKER,
                                    date(2022, 1, 25), date(2022, 2, 8))
    assert date(2022, 1, 28) in sessions
    assert date(2022, 2, 7) in sessions
    assert not set(sessions) & set(TET_CLOSURE)


def test_the_measured_calendar_states_exactly_how_far_its_sourcing_goes():
    """``is_sourced`` alone would overclaim: the settlement closures are
    inferred from trading days, not read off a VSDC notice, and both the id and
    the source string have to say so."""
    settlement, trading = S.measured_calendars()
    assert settlement.is_sourced and trading.is_sourced
    assert 'MEASURED-FROM-TRADING-DAYS' in settlement.calendar_id
    assert 'INFERENCE' in settlement.source
    assert 'not a VSDC notice' in settlement.source


def test_the_naive_arm_really_is_the_shipped_default():
    """The control must be what a caller who supplies nothing gets, or the
    comparison measures a strawman."""
    settlement, _ = S.naive_calendars()
    assert settlement.calendar_id == 'weekday-only-UNSOURCED'
    assert settlement.is_sourced is False


# --------------------------------------------------------------------------
# 2. Buy, try to sell the same day, be refused -- and be told when
# --------------------------------------------------------------------------

def test_a_sell_offered_before_the_buy_has_filled_is_refused_with_no_date(tet):
    """At the decision step the buy is still resting and the account holds
    nothing at all, so ``sellable_from`` is honestly ``None``: there is no
    tranche to date it from. That is a different answer from "later" and
    ``Holding.sellable_from`` says so in terms.

    Worth stating because ``ExchangeSession.submit``'s own docstring calls this
    the Tier 1 demo -- "buy FPT, try to sell it the same session, and the sell
    comes back Rejected carrying sellable_from". It carries one only once the
    buy has filled.
    """
    first = tet.attempts_on(date(2022, 1, 26))[0]
    assert first.phase == 'open'
    assert first.accepted is False
    assert first.rule == StatefulRule.UNSETTLED_HOLDING.value
    assert first.binding_constraint == 0
    assert first.sellable_from is None


def test_the_same_session_sell_after_the_fill_names_the_vsdc_correct_date(tet):
    """The headline. The buy filled at 14:45 on 2022-01-26; the shares exist,
    they are not deliverable, and the exchange says when they will be --
    2022-02-07, across a five-weekday depository closure."""
    after_fill = tet.attempts_on(date(2022, 1, 26))[1]
    assert after_fill.phase == 'close'
    assert after_fill.accepted is False
    assert after_fill.rule == StatefulRule.UNSETTLED_HOLDING.value
    assert after_fill.binding_constraint == 0
    assert after_fill.sellable_from == TET_SELLABLE[date(2022, 1, 26)]


def test_the_refusal_is_in_the_settlement_log_as_well_as_the_trade_log(tet):
    """An auditor asking "did T+2 bind?" should not have to join two logs."""
    refusals = tet.logs.settlement.refusals
    assert refusals
    same_day = [e for e in refusals if e.ts == datetime(2022, 1, 26, 14, 45)]
    assert len(same_day) == 1
    row = same_day[0]
    assert row.pool == SECURITIES
    assert row.ticker == S.TICKER
    assert row.sellable_from == TET_SELLABLE[date(2022, 1, 26)]
    assert row.settlement_rule == 'T+2 at next session open'
    assert row.settlement_calendar_id == tet.calendar_id


def test_the_weekday_calendar_names_a_public_holiday_as_the_sellable_day(
        tet_naive):
    """The control. The shipped default answers 2022-01-31 -- a day the
    exchange and the depository were both shut. The 2022-01-27 lot is dated
    2022-02-01, also inside the Tet closure."""
    after_fill = tet_naive.attempts_on(date(2022, 1, 26))[1]
    named = after_fill.sellable_from
    assert named == TET_SELLABLE_NAIVE[date(2022, 1, 26)]
    assert named.date() in S.VN_NON_TRADING_WEEKDAYS

    later = tet_naive.attempts_on(date(2022, 1, 27))[1]
    assert later.sellable_from == TET_SELLABLE_NAIVE[date(2022, 1, 27)]
    assert later.sellable_from.date() in S.VN_NON_TRADING_WEEKDAYS


def test_a_2022_01_26_trade_settles_on_the_same_date_under_both_calendars():
    """**The trap a settlement-date assertion walks straight into.**

    T+2 of a 2022-01-26 trade is 2022-01-28 under the measured calendar *and*
    under the weekday-only one -- the break starts on the 31st, after both
    counts have finished. A test that asserted only the settlement date would
    therefore pass a calendar that knows nothing about Tet. The two calendars
    disagree about the instant that actually binds a seller, and they disagree
    by five sessions.
    """
    measured, _ = S.measured_calendars()
    naive, _ = S.naive_calendars()
    assert measured.settle_date(date(2022, 1, 26), 2) == date(2022, 1, 28)
    assert naive.settle_date(date(2022, 1, 26), 2) == date(2022, 1, 28)
    assert (TET_SELLABLE[date(2022, 1, 26)]
            - TET_SELLABLE_NAIVE[date(2022, 1, 26)]).days == 7


# --------------------------------------------------------------------------
# 3. The securities leg settles on the settlement business day
# --------------------------------------------------------------------------

def test_the_securities_tranches_are_dated_in_settlement_business_days(tet):
    created = _created(tet, 'securities')
    assert len(created) == 2
    assert [e.ts.date() for e in created] == [date(2022, 1, 26),
                                              date(2022, 1, 27)]
    assert [e.settles_at for e in created] == [TET_SELLABLE[date(2022, 1, 26)],
                                               TET_SELLABLE[date(2022, 1, 27)]]
    assert all(e.quantity == 1000 for e in created)


def test_no_tranche_settles_before_it_was_promised(tet, boundary, advanced):
    """A tranche delivered early is the same defect as one delivered late, and
    only a log carrying both instants can show either."""
    for run in (tet, boundary, advanced):
        for row in run.logs.settlement.of(SettlementAction.TRANCHE_SETTLED):
            assert row.settled_at >= row.settles_at
            # Same session: the runner steps twice a day, so the observed lag
            # is at most one step, never a day.
            assert row.settled_at.date() == row.settles_at.date()


def test_the_exchange_names_what_is_sellable_and_the_algorithm_takes_it(tet):
    """2022-02-07: the 01-26 lot has settled and the 01-27 lot has not, so an
    offer of 2,000 is refused with ``binding_constraint=1000`` and the date the
    rest clears. The algorithm re-offers 1,000 and is accepted."""
    attempts = tet.attempts_on(date(2022, 2, 7))
    refused, accepted = attempts[0], attempts[1]
    assert refused.quantity == 2000 and refused.accepted is False
    assert refused.binding_constraint == 1000
    assert refused.sellable_from == TET_SELLABLE[date(2022, 1, 27)]
    assert accepted.quantity == 1000 and accepted.accepted is True


def test_the_second_lot_is_sellable_exactly_one_session_later(tet):
    accepted = [a for a in tet.strategy.attempts if a.accepted]
    assert [(a.day, a.quantity) for a in accepted] == [
        (date(2022, 2, 7), 1000), (date(2022, 2, 8), 1000)]


def test_the_weekday_calendar_sells_shares_that_were_not_deliverable(
        tet, tet_naive):
    """The measurable consequence of the wrong calendar, and the reason this
    scenario probes with the whole position rather than one lot at a time.

    Under the weekday calendar both lots are reported settled on 2022-02-07 and
    the algorithm sells 2,000 shares in one order. Under the measured calendar
    only 1,000 of them were deliverable that session. The other 1,000 is a
    settlement fail: shares delivered to a buyer that the seller did not have.
    """
    naive_sold = sum(a.quantity for a in tet_naive.strategy.attempts
                     if a.accepted and a.day == date(2022, 2, 7))
    real_sold = sum(a.quantity for a in tet.strategy.attempts
                    if a.accepted and a.day == date(2022, 2, 7))
    assert naive_sold == 2000
    assert real_sold == 1000
    assert not tet_naive.attempts_on(date(2022, 2, 7))[0].sellable_from


def test_the_wrong_calendar_changes_the_money_and_not_only_the_dates(
        tet, tet_naive):
    """The reason a settlement calendar is not a cosmetic detail.

    Both arms buy the same 2,000 shares at the same two prices. The measured
    arm can only sell 1,000 on 2022-02-07 at 43.05 and sells the rest on
    2022-02-08 at 45.55; the weekday arm dumps all 2,000 on 2022-02-07. Same
    algorithm, same data, same fill policy -- and the closing balances differ
    by 2,493,074 VND on an 85.6m purchase, about 2.9%.
    """
    measured_close = tet.result.snapshots[-1].settled_cash
    naive_close = tet_naive.result.snapshots[-1].settled_cash
    assert measured_close == Decimal('1002603064')
    assert naive_close == Decimal('1000109990')
    assert measured_close - naive_close == Decimal('2493074')
    # the purchases were identical; only the sales differ
    buys = tet.logs.cash.by_movement(SECURITIES)[
        CashMovement.BUY_CONSIDERATION]
    assert buys == tet_naive.logs.cash.by_movement(SECURITIES)[
        CashMovement.BUY_CONSIDERATION] == Decimal('-85600000.00')


# --------------------------------------------------------------------------
# 4. The cash leg: proceeds arrive on the right day
# --------------------------------------------------------------------------

def test_sale_proceeds_are_delivered_two_settlement_days_after_the_fill(tet):
    created = _created(tet, 'cash')
    assert len(created) == 2
    assert {e.ts.date(): e.settles_at for e in created} == TET_PROCEEDS
    assert [e.amount for e in created] == [Decimal('42930751.00'),
                                           Decimal('45423826.00')]


def test_the_proceeds_do_not_touch_the_settled_balance_until_dvp(tet):
    """A sale credits a *pending* tranche. The settled balance moves once, at
    the DVP instant, and the cash log carries both rows with the pending one
    marked as not affecting the balance."""
    pending = [e for e in tet.logs.cash
               if e.movement is CashMovement.SALE_PROCEEDS_PENDING]
    credits = [e for e in tet.logs.cash
               if e.movement is CashMovement.SETTLEMENT_CREDIT]
    assert [e.affects_balance for e in pending] == [False, False]
    assert [e.affects_balance for e in credits] == [True, True]
    assert [e.ts.date() for e in credits] == [date(2022, 2, 10),
                                              date(2022, 2, 11)]
    assert ([e.amount for e in pending] == [e.amount for e in credits])


def test_settlement_moves_money_between_buckets_and_creates_none(tet,
                                                                 advanced):
    """``settled_balance + pending_total`` may only change when a trade fills.

    Sampled at both steps of every session. A settlement instant moves money
    out of ``pending`` and into ``settled`` and must leave the sum alone; a
    simulator that credited the proceeds without retiring the tranche, or
    retired it without crediting, breaks this and nothing else in the run
    would show it. The buy legs are excluded because a purchase does leave the
    account -- see the asymmetry recorded below.
    """
    for run in (tet, advanced):
        fills = {row.ts for row in run.logs.trades.of(TradeAction.FILLED)}
        snapshots = run.result.snapshots
        for previous, current in zip(snapshots, snapshots[1:]):
            if current.ts in fills:
                continue
            assert (previous.settled_cash + previous.pending_total
                    == current.settled_cash + current.pending_total), (
                f'{run.result.name}: {previous.ts} -> {current.ts}')


def test_the_pending_line_is_what_a_broker_statement_would_show(tet):
    """"Tien ban cho ve" -- money sold and not yet received. It is the sum of
    the outstanding tranches at every instant, and it is zero once the run's
    last DVP has passed."""
    by_step = {(s.ts, s.phase): s.pending_total for s in tet.result.snapshots}
    assert by_step[(datetime(2022, 2, 7, 14, 45), 'close')] == Decimal(
        '42930751.00')
    assert by_step[(datetime(2022, 2, 8, 14, 45), 'close')] == Decimal(
        '88354577.00')
    assert by_step[(datetime(2022, 2, 10, 9, 30), 'open')] == Decimal(
        '45423826.00')
    assert by_step[(datetime(2022, 2, 11, 9, 30), 'open')] == Decimal('0')


def test_every_tranche_created_is_a_tranche_settled(tet, boundary, advanced):
    """Matched on the tranche's economic identity, not on object identity."""
    for run in (tet, boundary, advanced):
        assert run.logs.settlement.unsettled_at_end() == ()
        created = run.logs.settlement.of(SettlementAction.TRANCHE_CREATED)
        closed = run.logs.settlement.of(SettlementAction.TRANCHE_SETTLED)
        assert len(created) == len(closed)


def test_the_cash_log_accounts_for_every_dong_of_the_tet_run(tet):
    """Opening balance plus every balance-moving row equals the closing
    balance, and the closing balance is the one the trades imply.

    1,000,000,000 - 43,526,907 (buy 1,000 @ 43.45 + fees) - 42,224,606
    (buy 1,000 @ 42.15 + fees) + 42,930,751 (sale @ 43.05, net) + 45,423,826
    (sale @ 45.55, net) = 1,002,603,064.
    """
    closing = tet.result.snapshots[-1].settled_cash
    assert closing == Decimal('1002603064')
    assert tet.logs.cash.net(SECURITIES) == closing
    itemised = tet.logs.cash.by_movement(SECURITIES)
    assert itemised[CashMovement.BUY_CONSIDERATION] == Decimal('-85600000.00')
    assert itemised[CashMovement.SETTLEMENT_CREDIT] == Decimal('88354577.00')
    # Buy-side charges are debited; sell-side charges are withheld out of the
    # proceeds and must never be debited a second time.
    assert itemised[CashMovement.CHARGE_DEBITED] == Decimal('-151513')
    assert itemised[CashMovement.CHARGE_WITHHELD] == Decimal('-245423')


def test_the_cash_leg_carries_no_ticker_and_has_to_be_joined_on_the_order(tet):
    """A gap in the settlement log, recorded because the brief asks for a log
    a real broker produces and a real one names the security on both legs.

    ``ProceedsTranche`` has ``amount``, ``settles_at``, ``accrued_at``,
    ``source_order_id`` and the two financing fields, and no ticker;
    ``CashLedger.credit_pending`` is never given one. The securities leg has a
    ticker because ``credit_unsettled`` takes one. So "which stock did this
    money come from" is answerable only by joining ``order_id`` back to the
    trade log -- recoverable, but not readable off the settlement log alone.
    """
    cash_legs = _created(tet, 'cash')
    assert all(row.ticker is None for row in cash_legs)
    assert all(row.ticker == S.TICKER for row in _created(tet, 'securities'))

    by_order = {row.order_id: row.ticker
                for row in tet.logs.trades.of(TradeAction.FILLED)}
    assert all(by_order[row.order_id] == S.TICKER for row in cash_legs)


def test_the_buy_has_no_cash_settlement_tranche(tet):
    """Recorded because it is an asymmetry, not because it is wrong.

    A sale pends its cash to the DVP instant; a purchase debits settled cash at
    the fill and pends only the shares. For buying power the two are
    equivalent -- blocked and debited spend the same -- but the settlement log
    therefore carries no cash-leg obligation for a purchase, so "show me every
    settlement obligation outstanding" answers with the share legs and the
    sale proceeds and nothing else.
    """
    cash_legs = _created(tet, 'cash')
    assert len(cash_legs) == 2                     # the two sales, not the buys
    buy_rows = [e for e in tet.logs.cash
                if e.movement is CashMovement.BUY_CONSIDERATION]
    assert len(buy_rows) == 2
    assert all(e.affects_balance and e.settles_at is None for e in buy_rows)


def test_the_identities_hold_on_every_arm(tet, tet_naive, boundary,
                                          advanced, unadvanced, rebuy,
                                          rebuy_refused):
    for run in (tet, tet_naive, boundary, advanced, unadvanced, rebuy,
                rebuy_refused):
        assert run.result.error is None, run.result.error
        assert run.result.ok, [r.to_row() for r in
                               run.result.failed_identities]


def test_the_session_actually_used_the_calendar_it_was_given(tet, tet_naive):
    """``ExchangeSession.build``'s own docstring records that
    ``data.settlement_calendar`` was parsed and then never read, so a caller
    who supplied the real notice still ran on the weekday-only one. This checks
    the injected object reached provenance -- otherwise every date asserted in
    this file would be measuring the default."""
    assert (tet.result.provenance.settlement_calendar_id
            == S.SETTLEMENT_CALENDAR_ID)
    assert (tet_naive.result.provenance.settlement_calendar_id
            == 'weekday-only-UNSOURCED')
    for row in tet.logs.settlement:
        assert row.settlement_calendar_id == S.SETTLEMENT_CALENDAR_ID


def test_nothing_in_the_run_was_left_undecided(tet, boundary, advanced):
    """A green run that could not decide anything would prove nothing. Soft
    fills on daily bars decide every evaluation here, and the report says so."""
    for run in (tet, boundary, advanced):
        report = run.result.indeterminate
        assert report.evaluations > 0
        assert report.indeterminate == 0
        assert report.rate == Decimal('0')


def test_the_custody_fee_is_sourced_and_never_levied(tet):
    """A charge with a citation, a rate and no call site.

    ``vsdc_custody_equity`` is 0.27 VND per unit per month from 2020-03-19,
    graded *high* against the VSDC schedule, and it is the one underlying-market
    charge that is not per fill. ``assess_charges`` levies ``debited_at=FILL``
    rows only and ``charges.py`` says outright that "the monthly accrual is not
    built". This run holds 1,000 shares from 2022-01-26 and 2,000 from
    2022-01-27 across the January-February boundary and is charged nothing for
    custody, so an account statement produced from these logs understates the
    cost of holding by the whole custody line.
    """
    assert tet.charge_kinds == {'exchange_service_hsx_equity',
                                'pit_securities_transfer',
                                'broker.commission.hsx'}
    assert not any('custody' in kind for kind in tet.charge_kinds)
    assert not any(e.charge_kind and 'custody' in e.charge_kind
                   for e in tet.logs.cash)


# --------------------------------------------------------------------------
# 5. The 2022-08-29 regime change, inside one session
# --------------------------------------------------------------------------

def test_before_decision_109_the_shares_arrive_at_the_next_sessions_open(
        boundary):
    """T+2 of a 2022-08-24 trade is 2022-08-26, settlement completed after that
    day's close, so the first sellable session is 2022-08-29's open."""
    after_fill = boundary.attempts_on(date(2022, 8, 24))[1]
    assert after_fill.sellable_from == BOUNDARY_SELLABLE[date(2022, 8, 24)]
    created = [e for e in _created(boundary, 'securities')
               if e.ts.date() == date(2022, 8, 24)]
    assert created[0].settles_at == datetime(2022, 8, 29, 9, 0)
    assert created[0].settlement_rule == 'T+2 at next session open'
    settled = [e for e in _settled(boundary, 'securities')
               if e.settles_at == datetime(2022, 8, 29, 9, 0)]
    assert settled[0].settled_at == datetime(2022, 8, 29, 9, 30)


def test_after_decision_109_the_shares_arrive_at_1300_on_t_plus_2(boundary):
    """**The 13:00 delivery, proven inside its own session.**

    A 2022-08-30 purchase settles on 2022-09-05 -- National Day closed
    2022-09-01 and 2022-09-02 -- at 13:00, so the same session refuses the sale
    at 09:30 and accepts it at 14:45. Nothing about the position changed in
    between; the depository allocated.
    """
    created = [e for e in _created(boundary, 'securities')
               if e.ts.date() == date(2022, 8, 30)]
    assert created[0].settles_at == BOUNDARY_SELLABLE[date(2022, 8, 30)]
    assert created[0].settlement_rule == 'T+2 at 13:00:00'

    morning, afternoon = boundary.attempts_on(date(2022, 9, 5))
    assert morning.phase == 'open' and morning.ts.time() == time(9, 30)
    assert morning.accepted is False
    assert morning.rule == StatefulRule.UNSETTLED_HOLDING.value
    assert morning.sellable_from == datetime(2022, 9, 5, 13, 0)
    assert afternoon.phase == 'close' and afternoon.ts.time() == time(14, 45)
    assert afternoon.accepted is True

    settled = [e for e in _settled(boundary, 'securities')
               if e.settles_at == datetime(2022, 9, 5, 13, 0)]
    assert settled[0].settled_at == datetime(2022, 9, 5, 14, 45)


def test_national_day_sits_inside_the_t_plus_2_of_a_2022_08_30_trade():
    """The weekday answer is 2022-09-01, a day both the exchange and the
    depository were shut. Two settlement days of error."""
    naive_settlement, _ = S.naive_calendars()
    naive = naive_settlement.settle_date(date(2022, 8, 30), 2)
    assert naive == date(2022, 9, 1)
    assert naive in S.VN_NON_TRADING_WEEKDAYS
    measured, _ = S.measured_calendars()
    assert measured.settle_date(date(2022, 8, 30), 2) == date(2022, 9, 5)


def test_the_cash_leg_switches_regime_on_the_same_window(boundary):
    """A sale on 2022-08-29 is governed by Decision 109: T+2 = 2022-08-31, and
    the money lands at that session's 13:00 rather than the next session's
    open. The two regimes are visible in one run."""
    legs = _created(boundary, 'cash')
    assert legs[0].ts.date() == date(2022, 8, 29)
    assert legs[0].settles_at == datetime(2022, 8, 31, 13, 0)
    assert legs[0].settlement_rule == 'T+2 at 13:00:00'
    credit = [e for e in boundary.logs.cash
              if e.movement is CashMovement.SETTLEMENT_CREDIT][0]
    assert credit.ts == datetime(2022, 8, 31, 14, 45)


def test_the_settlement_regime_is_dated_from_the_trade_and_that_is_unresolved(
        boundary):
    """**Reported, not asserted away.**

    ``ExchangeSession._settles_at`` resolves the ``SettlementRule`` at
    ``fill.ts`` -- the *trade* instant. The rulebook's interval endpoints for
    the two regimes are ``2016-01-01 .. 2022-08-26`` and
    ``2022-08-29 .. current``, and 2022-08-26 is a Friday *settlement* date
    with a weekend after it, so those endpoints read naturally as settlement
    days rather than trade days.

    A trade on 2022-08-25 settles on 2022-08-29, the first day Decision 109 is
    in force. Keying the rule on the settlement date would make it sellable at
    13:00 on 2022-08-29; keying it on the trade date -- what the simulator
    does, and what this test pins -- makes it sellable at 09:00 on 2022-08-30,
    one full session later. No document naming the first benefiting trade date
    could be sourced, so the divergence is pinned rather than resolved.
    """
    after_fill = boundary.attempts_on(date(2022, 8, 25))[1]
    assert after_fill.sellable_from == BOUNDARY_SELLABLE[date(2022, 8, 25)]

    created = [e for e in _created(boundary, 'securities')
               if e.ts.date() == date(2022, 8, 25)]
    assert created[0].settlement_rule == 'T+2 at next session open'

    settlement, _ = S.measured_calendars()
    assert settlement.settle_date(date(2022, 8, 25), 2) == date(2022, 8, 29)
    # the alternative keying, computed here so the size of the difference is
    # on the record rather than in a comment
    alternative = datetime(2022, 8, 29, 13, 0)
    assert after_fill.sellable_from > alternative


# --------------------------------------------------------------------------
# 6. Ung truoc tien ban
# --------------------------------------------------------------------------

def test_the_advance_is_drawn_at_the_fill_and_is_spendable_at_once(advanced):
    """Rulebook 8.3's mechanics row: on registration the advance is credited to
    buying power immediately after the sell order fills on T."""
    at_fill = advanced.strategy.sample_at(date(2022, 1, 28), 'close')
    assert at_fill.advanced == Decimal('42083106')
    assert at_fill.settled == Decimal(S.ADVANCE_INITIAL_CASH)
    assert at_fill.available == at_fill.settled + at_fill.advanced

    drawn = [e for e in advanced.logs.cash
             if e.movement is CashMovement.ADVANCE_DRAWN]
    assert len(drawn) == 2
    assert drawn[0].ts == datetime(2022, 1, 28, 14, 45)
    assert drawn[0].amount == Decimal('42083106')
    assert drawn[0].affects_balance is False


def test_without_the_advance_nothing_is_spendable_until_dvp(unadvanced):
    at_fill = unadvanced.strategy.sample_at(date(2022, 1, 28), 'close')
    assert at_fill.advanced == Decimal('0')
    assert at_fill.available == at_fill.settled == Decimal(
        S.ADVANCE_INITIAL_CASH)
    assert not [e for e in unadvanced.logs.cash
                if e.movement is CashMovement.ADVANCE_DRAWN]


def test_advanceable_is_zero_at_a_firm_that_does_not_offer_the_advance(
        unadvanced):
    """**Regression test for a fixed defect.**

    ``CashLedger.advanceable()`` summed tranche headroom without consulting
    ``BrokerTerms.advance_on_sale_enabled``, so a firm that cannot advance
    reported 42,083,106 VND of headroom -- while ``request_advance()`` on the
    same ledger raised ``ValueError`` for the same firm. A caller sizing an
    order off the read model would have been told it had buying power and then
    refused ``INSUFFICIENT_CASH`` for spending it.
    """
    assert all(sample.advanceable == Decimal('0')
               for sample in unadvanced.strategy.samples)
    at_fill = unadvanced.strategy.sample_at(date(2022, 1, 28), 'close')
    assert at_fill.advanceable == Decimal('0')


def test_auto_registration_leaves_no_headroom_for_a_second_request(advanced):
    """Every session built from a config auto-registers: ``AdvanceTerms`` is
    not reachable through ``BROKER_CONFIG_KEYS``, so ``auto_register``, the
    cap, the minimum charge and the annualisation basis are fixed at their
    defaults. The whole tranche is therefore drawn inside ``credit_pending``
    and ``advanceable()`` is zero even in the instant after the fill."""
    assert all(sample.advanceable == Decimal('0')
               for sample in advanced.strategy.samples)
    assert all(sale.advanceable_after == Decimal('0')
               for sale in advanced.strategy.sales)


def test_the_advance_across_tet_costs_eleven_days_and_the_control_two(
        advanced):
    """Same shares, same firm, same daily rate; the only difference is which
    side of Tet the sale was made.

    2022-01-28 fill -> 2022-02-09 09:00 delivery: 42,083,106 x 0.00031 x 11 =
    143,503.39146. 2022-02-14 fill -> 2022-02-17 09:00: 46,072,026 x 0.00031 x
    2 = 28,564.65612. Five and a half times the financing cost for the same
    product, because the depository was shut for five weekdays.
    """
    rate = Decimal(S.ADVANCE_DAILY_RATE)
    tet_cost = Decimal('42083106') * rate * 11
    control_cost = Decimal('46072026') * rate * 2
    assert tet_cost == Decimal('143503.39146')
    assert control_cost == Decimal('28564.65612')
    total = advanced.result.snapshots[-1].interest_accrued
    assert total == tet_cost + control_cost == Decimal('172068.04758')


def test_the_advance_day_count_is_whole_days_measured_from_the_fill_instant(
        advanced):
    """An assumption worth seeing rather than inferring.

    The Tet advance is outstanding from 14:45 on 2022-01-28 to 09:00 on
    2022-02-09 -- eleven days and eighteen and a quarter hours -- and is
    charged for eleven. The residual part-day is free, and the count therefore
    moves with the *time of day* of the fill: the same trade filled before
    09:00 would have been charged twelve. On a daily clock the fill instant is
    a property of the harness's step times, not of the market, so the financing
    cost of an advance is not invariant to a choice with no market meaning.
    Nothing sources a day-count basis, so this is pinned, not corrected.
    """
    created = _created(advanced, 'cash')[0]
    outstanding = created.settles_at - created.ts
    assert outstanding.days == 11
    assert outstanding.seconds == 18 * 3600 + 15 * 60
    charged = Decimal('42083106') * Decimal(S.ADVANCE_DAILY_RATE) * 11
    assert charged == Decimal('143503.39146')


def test_the_interest_is_accrued_and_never_charged(advanced, unadvanced):
    """The accounting hole, measured.

    Both arms make exactly the same two sales, so if the advance cost anything
    the two closing balances would differ by 172,068.04758 VND. They do not
    differ by a dong. Rulebook 12.7 puts the charge "at recovery, from the T+2
    settlement proceeds" and says the product "must be charged for -- otherwise
    the backtest overstates achievable turnover"; ``CashLedger.settle_due``
    computes the final figure inside ``_repay`` and then does not take it.
    It is also absent from ``session.charges()``: ``ChargeBase`` has no
    financing member, which ``accrue_interest`` records as a gap rather than a
    decision.
    """
    assert (advanced.result.snapshots[-1].settled_cash
            == unadvanced.result.snapshots[-1].settled_cash
            == Decimal('93155132'))
    assert advanced.result.snapshots[-1].interest_accrued == Decimal(
        '172068.04758')
    assert unadvanced.result.snapshots[-1].interest_accrued == Decimal('0')

    interest_rows = [e for e in advanced.logs.cash
                     if e.movement is CashMovement.ADVANCE_INTEREST_ACCRUED]
    assert interest_rows
    assert not any(e.affects_balance for e in interest_rows)
    # **The itemisation reconciles to the ledger.** ``CashLedger._repay``
    # trues the advance up at the settlement instant by writing straight to
    # ``_interest_accrued``, which bypasses the ``accrue_interest`` wrapper
    # the journal hooks -- so on a clock coarser than one day the whole charge
    # escaped the log and ``CashLog.by_movement()``, "the itemisation an audit
    # reads first", reported the financing cost of a financed run as zero
    # while the ledger carried it. The runner's two-steps-per-day loop keeps
    # the watermark within a day of every settlement, which is why the shipped
    # arms never showed it; the sum is the check that would have.
    assert (-sum(e.amount for e in interest_rows)
            == advanced.result.snapshots[-1].interest_accrued
            == Decimal('172068.04758'))
    # ... and it is not in session.charges() either
    kinds = advanced.charge_kinds
    assert kinds and not any('advance' in kind for kind in kinds)


@requires_corpus
def test_the_financing_cost_reaches_the_cash_log_on_a_coarse_clock():
    """The itemisation an audit reads first said the advance was free.

    ``CashLedger._repay`` trues an advance up to its final interest **at the
    settlement instant**, writing straight to ``_interest_accrued`` and
    bypassing ``accrue_interest`` -- which is the method the journal wraps.
    Everything between the last daily accrual and the DVP instant therefore
    escaped the cash log.

    The shipped arms hide it: the runner steps twice a day, so the accrual
    watermark is never more than a day behind a settlement and the residue is
    zero. Here the clock is two steps for the whole run -- 2022-01-28, then
    2022-02-09, the settlement date -- so *all* of it is residue. Measured
    before the fix: ``by_movement()`` reported ``ADVANCE_INTEREST_ACCRUED``
    total **0** against ``Cash.interest_accrued`` of 143,503.39146.

    The number survived in ``ADVANCE_REPAID.detail`` and in the settlement
    row, so it was recoverable -- but the movement class lied, and a movement
    class that lies is worse than one that is absent.
    """
    source = datahub_source()
    window = S.ADVANCE_2022.with_sessions((date(2022, 1, 28),
                                           date(2022, 2, 9)))
    strategy = S.AdvanceAgainstSale(S.TICKER,
                                    sells={date(2022, 1, 28): 1000}, buys={})
    session, _ = S._build(window, calendars='measured',
                          broker=S.BROKER_WITH_ADVANCE,
                          initial_cash=S.ADVANCE_INITIAL_CASH,
                          initial_holdings={S.TICKER: 2000}, source=source)
    result = run_scenario(Scenario(
        name='coarse-clock-advance', window=window, session=session,
        strategy=strategy, source=source,
        opening_holdings={S.TICKER: 2000}))

    ledger_total = session.cash().interest_accrued
    assert ledger_total > 0, 'the arm must actually finance something'
    logged = -sum(e.amount for e in result.logs.cash
                  if e.movement is CashMovement.ADVANCE_INTEREST_ACCRUED)
    assert logged == ledger_total
    assert result.logs.cash.by_movement()[
        CashMovement.ADVANCE_INTEREST_ACCRUED.value] == -ledger_total


def test_the_advance_principal_is_recovered_out_of_the_settlement(advanced):
    """The settlement credit is gross and the repayment does not move the
    balance a second time; ``available`` is unchanged across the DVP instant,
    which is the point -- the advance made money spendable early, it did not
    create any."""
    repaid = [e for e in advanced.logs.cash
              if e.movement is CashMovement.ADVANCE_REPAID]
    assert [e.amount for e in repaid] == [Decimal('-42083106'),
                                          Decimal('-46072026')]
    assert not any(e.affects_balance for e in repaid)
    before = advanced.strategy.sample_at(date(2022, 2, 8), 'close')
    after = advanced.strategy.sample_at(date(2022, 2, 9), 'open')
    assert before.available == after.available
    assert after.advanced == Decimal('0')
    assert after.settled == before.settled + Decimal('42083106')


# --------------------------------------------------------------------------
# 7. Spending proceeds the depository has not delivered
# --------------------------------------------------------------------------

def test_the_rebuy_is_admitted_in_the_same_session_the_sale_filled(rebuy):
    """The sale fills at 14:45; the advance is drawn in that same instant; the
    rebuy submitted at that instant is accepted and funded out of proceeds that
    do not settle until 09:00 on 2022-02-10."""
    ts, quantity, outcome = rebuy.strategy.buy_outcomes[0]
    assert ts == datetime(2022, 2, 7, 14, 45)
    assert quantity == 1000
    assert type(outcome).__name__ == 'Accepted'


def test_that_rebuy_then_expires_unfilled_and_that_is_the_clock_not_the_market(
        rebuy):
    """``advance_to`` evaluates a day's bar at an advance landing inside that
    day. An order submitted at the second and last advance of a daily loop has
    no third advance inside its own day, so it dies at ``session_end`` without
    ever being offered a bar. Recorded so the acceptance above is not read as a
    fill."""
    expired = rebuy.logs.trades.of(TradeAction.EXPIRED)
    assert len(expired) == 1
    assert expired[0].ts == datetime(2022, 2, 7, 14, 45)
    assert expired[0].detail.get('trigger') == 'session_end'
    assert expired[0].detail.get('filled_quantity') == 0


def test_the_next_session_rebuy_fills_two_settlement_days_before_dvp(rebuy):
    ts, quantity, outcome = rebuy.strategy.buy_outcomes[1]
    assert ts == datetime(2022, 2, 8, 9, 30)
    assert type(outcome).__name__ == 'Accepted'
    fills = rebuy.logs.trades.of(TradeAction.FILLED)
    buy_fill = [e for e in fills if e.side == 'BUY']
    assert len(buy_fill) == 1
    assert buy_fill[0].ts == datetime(2022, 2, 8, 14, 45)
    assert buy_fill[0].fill_price == Decimal('45.55')
    # funded before the proceeds arrived
    proceeds = _created(rebuy, 'cash')[0]
    assert proceeds.settles_at == datetime(2022, 2, 10, 9, 0)
    assert buy_fill[0].ts < proceeds.settles_at


def test_spending_the_advance_overdraws_the_settled_balance_until_dvp(rebuy):
    """What an advance *is*: the money is spendable and has not arrived, so the
    settled balance goes negative and the settlement squares it. Not a defect
    -- ``CashLedger.debit`` says so in terms -- and not a short position: the
    ``no_negative_settled`` identity is about holdings and still holds."""
    trough = min(sample.settled for sample in rebuy.strategy.samples)
    assert trough == Decimal('-40630624.00')
    assert rebuy.result.snapshots[-1].settled_cash == Decimal('2300127.00')
    assert rebuy.result.ok


def test_the_same_rebuy_is_refused_at_a_firm_that_does_not_advance(
        rebuy_refused):
    """One variable, two outcomes. The refusal names ``pending_proceeds``, so
    the account is told the money exists and has not settled rather than simply
    told no."""
    outcomes = [o for _, _, o in rebuy_refused.strategy.buy_outcomes]
    assert len(outcomes) == 2
    for outcome in outcomes:
        assert type(outcome).__name__ == 'Rejected'
        assert outcome.rule is StatefulRule.INSUFFICIENT_CASH
        assert outcome.binding_constraint == Decimal(S.ADVANCE_INITIAL_CASH)
        assert outcome.detail['pending_proceeds'] == Decimal('42930751.00')
        assert outcome.detail['funded_in_aggregate'] is False
    # 1,000 @ 43.05 on 2022-02-07 and @ 45.55 on 2022-02-08, both plus fees
    assert [o.detail['required'] for o in outcomes] == [
        Decimal('43126199.00'), Decimal('45630624.00')]
    assert min(s.settled for s in rebuy_refused.strategy.samples) >= 0


# --------------------------------------------------------------------------
# 8. The calendar refuses to answer what it was not told
# --------------------------------------------------------------------------

def test_the_calendar_refuses_to_extrapolate_past_its_coverage(source):
    """A trade on 2022-12-29 settles in 2023, which the measured calendar does
    not cover. It raises rather than assuming Mon-Fri -- and the run stops with
    the exception on the result instead of producing a settlement instant that
    looks sourced and is not.

    The refusal arrives *before* anything moves: ``_settles_at`` is evaluated
    as an argument to ``SecuritiesAccount.apply_fill``, so no ledger changed
    and every identity still holds.
    """
    start, end = date(2022, 12, 26), date(2022, 12, 30)
    days = sessions_from_source(source, S.TICKER, start, end)
    settlement, trading = S.measured_calendars()
    session = build_session(
        start=start, end=end, venues=['HSX'], source=source,
        initial_cash='1000000000', fill_policy='soft',
        broker_profile=S.BROKER_NO_ADVANCE,
        settlement=settlement, trading=trading)
    strategy = S.SettlementProbe(S.TICKER, {date(2022, 12, 29): 1000})
    result = run_scenario(Scenario(
        name='coverage-edge',
        window=Window(name='coverage-edge', start=start, end=end,
                      tickers=(S.TICKER,), sessions=days),
        session=session, strategy=strategy, source=source))

    assert isinstance(result.error, CalendarCoverageError)
    assert '2022-12-31 is outside settlement calendar' in str(result.error)
    assert result.sessions_run == 3
    assert not result.failed_identities
    assert result.logs.settlement.unsettled_at_end() == ()
