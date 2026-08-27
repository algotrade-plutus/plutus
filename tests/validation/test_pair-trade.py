"""The pair-trade scenario, asserted against the logs it produced.

Every test here reads :mod:`validation.scenarios.pair-trade`'s output. None of
them re-derives a number from the code that produced it: where a margin figure
is checked it is recomputed from the rulebook in :func:`independent_requirement`
first, and where a charge is checked the arithmetic is written out in the test.
A test that asserted ``deposit.py``'s answer against ``deposit.py``'s function
would pass on any bug they shared.

The scenario module is imported through :func:`importlib.import_module` because
its file name carries a hyphen -- the orchestrator's naming, matched by the
sibling scenarios. The import works; ``import validation.scenarios.pair-trade``
would not.

The whole file is gated on the corpus. There is no stub arm: the point of this
scenario is that two venues behave differently on **real Vietnamese market
data**, and a hand-written market would prove the harness rather than the
simulator.
"""

import importlib
from datetime import date, datetime
from decimal import Decimal

import pytest

from conftest import requires_corpus                       # noqa: E402
from plutus.market.session.types import Pool, Venue
from validation.corpus import closes
from validation.logs import CashMovement, SettlementAction, TradeAction

pair = importlib.import_module('validation.scenarios.pair-trade')

pytestmark = requires_corpus

_D = Decimal


# --------------------------------------------------------------------------
# Fixtures -- the runs are expensive, so each is built once for the module
# --------------------------------------------------------------------------

@pytest.fixture(scope='module')
def source():
    return pair._source()


@pytest.fixture(scope='module')
def main_run(source):
    result, scenario = pair.run(source=source)
    return result, scenario


@pytest.fixture(scope='module')
def result(main_run):
    return main_run[0]


@pytest.fixture(scope='module')
def scenario(main_run):
    return main_run[1]


@pytest.fixture(scope='module')
def venue_rules(source):
    return pair.run_venue_rules(source=source)


@pytest.fixture(scope='module')
def bare_cure(source):
    return pair.run_bare_cure(source=source)


@pytest.fixture(scope='module')
def hard_arm(source):
    return pair.run_hard_arm(source=source)


@pytest.fixture(scope='module')
def breach_then_close(source):
    return pair.run_breach_then_close(source=source)


@pytest.fixture(scope='module')
def closing_marks(source):
    day = pair.WINDOW_END
    return {t: closes(source, t, day, day)[day] for t in pair.BASKET}


def _rejected(outcome):
    return type(outcome).__name__ == 'Rejected'


def _rule(outcome):
    return getattr(outcome.rule, 'value', outcome.rule)


# --------------------------------------------------------------------------
# The window is the one the scenario says it is
# --------------------------------------------------------------------------

def test_the_window_is_twenty_sessions_ending_on_the_expiry(source):
    """The corpus decides which days traded; the scenario only names them.

    Ending on 2022-11-17 is load-bearing: it is VN30F2211's last trading day,
    so the run necessarily crosses a cash settlement with the equity leg still
    open.
    """
    sessions = pair.trading_sessions(source)
    assert len(sessions) == 20
    assert sessions[0] == pair.WINDOW_START == date(2022, 10, 21)
    assert sessions[-1] == pair.WINDOW_END == date(2022, 11, 17)
    assert date(2022, 10, 22) not in sessions            # a Saturday
    assert date(2022, 10, 29) not in sessions            # a Saturday


def test_the_basis_is_the_dislocation_the_scenario_claims(source):
    """-25.57 on entry, -31.88 two sessions later, +17.31 at the squeeze."""
    series = pair.basis_series(source)
    assert series[date(2022, 10, 21)][2] == _D('-25.57')
    assert series[date(2022, 10, 24)][2] == _D('-31.88')
    assert series[date(2022, 10, 27)][2] == _D('-3.50')
    assert series[date(2022, 11, 10)][2] == _D('-24.00')
    assert series[date(2022, 11, 16)][2] == _D('17.31')
    widest = min(series.values(), key=lambda row: row[2])
    assert widest[2] == _D('-31.88')


# --------------------------------------------------------------------------
# 1. Routing: two venues, two pools, one session
# --------------------------------------------------------------------------

def test_each_leg_routes_to_its_own_venue_and_its_own_pool(result):
    """Read off the trade log, which is what an auditor has.

    The pool is a routing fact and not an instrument fact (``exchange.py``
    ``_reserve``), and the log has to carry it per row or a statement can be
    right in total while lying about which account paid.
    """
    by_venue = pair.fills_by_venue(result)
    assert set(by_venue) == {'HSX', 'HNXDS'}

    equity = by_venue['HSX']
    assert equity['pools'] == ('securities',)
    assert equity['fills'] == 90                  # 30 buys, 30 sells, 30 buys
    assert equity['quantity'] == 90 * pair.SHARES_PER_NAME
    assert set(equity['tickers']) == set(pair.BASKET)

    futures = by_venue['HNXDS']
    assert futures['pools'] == ('derivatives',)
    assert futures['fills'] == 3                  # open, close, re-open
    assert futures['quantity'] == 3 * pair.CONTRACTS
    assert futures['tickers'] == (pair.FUTURE,)


def test_the_two_instruments_are_dated_and_disagree_about_everything(scenario):
    """One router, one instant, two completely different instrument specs."""
    ts = datetime.combine(pair.ENTER_A, datetime.min.time())
    equity = scenario.session.instrument('ACB', ts)
    futures = scenario.session.instrument(pair.FUTURE, ts)

    assert equity.exchange_code == 'HSX'
    assert equity.trading_unit == 100
    assert equity.multiplier == _D('1')
    assert equity.expiry is None

    assert futures.exchange_code == 'HNXDS'
    assert futures.trading_unit == 1
    assert futures.multiplier == _D('100000')
    assert futures.expiry == pair.WINDOW_END      # third Thursday of Nov 2022
    # The one thing they agree on, and it is a coincidence of this era rather
    # than a shared rule: HOSE and HNX-DS both run +-7%.
    assert equity.daily_trading_limit == futures.daily_trading_limit == _D('0.07')


# --------------------------------------------------------------------------
# 2. Each leg judged by its OWN venue's rules
# --------------------------------------------------------------------------

def test_the_same_quantity_is_legal_on_one_venue_and_not_the_other(venue_rules):
    """Three shares is an odd lot on HOSE and three contracts on HNX-DS."""
    verdicts = venue_rules[1].strategy.verdicts
    equity = verdicts['equity_qty_3']
    assert _rejected(equity)
    assert _rule(equity) == 'round_lot'
    assert equity.binding_constraint == 100       # the HOSE board lot
    assert not _rejected(verdicts['futures_qty_3'])


def test_the_same_trailing_digit_is_on_grid_on_one_venue_and_not_the_other(
        venue_rules):
    """ACB sits in HOSE's 10-50 band and moves on 0.05; VN30F moves on 0.1.

    The two orders differ only in the venue they route to, and the futures
    refusal names 0.1 -- HNX-DS's own grid -- as the constraint. That is the
    dated tick the session installs on the venue object for one call, not the
    import-time singleton's.
    """
    verdicts = venue_rules[1].strategy.verdicts
    assert not _rejected(verdicts['equity_half_tick'])
    futures = verdicts['futures_half_tick']
    assert _rejected(futures)
    assert _rule(futures) == 'tick_grid'
    assert futures.binding_constraint == _D('0.1')


def test_each_band_refusal_names_its_own_venue_s_published_number(venue_rules):
    """Both venues run +-7%, and neither refuses against the other's band."""
    strategy = venue_rules[1].strategy
    verdicts = strategy.verdicts
    equity_ref, equity_ceiling, equity_floor, equity_src = strategy.bands['ACB']
    fut_ref, fut_ceiling, fut_floor, fut_src = strategy.bands[pair.FUTURE]
    assert equity_src == fut_src == 'published'
    assert (equity_ref, equity_ceiling, equity_floor) == (
        _D('21.35'), _D('22.8'), _D('19.9'))
    assert (fut_ref, fut_ceiling, fut_floor) == (
        _D('1037.2'), _D('1109.8'), _D('964.6'))

    above = verdicts['equity_above_ceiling']
    below = verdicts['futures_below_floor']
    assert _rejected(above) and _rule(above) == 'band_limit'
    assert _rejected(below) and _rule(below) == 'band_limit'
    assert above.binding_constraint == equity_ceiling
    assert below.binding_constraint == fut_floor
    # PT-10 in the report, small: the equity refusal says which side bound and
    # the futures one does not. Pinned so the asymmetry is not lost.
    assert above.detail.get('side') == 'above_ceiling'
    assert 'side' not in below.detail


def test_a_naked_short_of_stock_is_refused_but_under_the_wrong_rule(
        venue_rules):
    """Finding PT-4.

    Vietnam has no operational stock short selling, so the *outcome* is right
    and it is the only thing that makes the -3.27% futures discount
    un-arbitrageable here. The *rule* is wrong: an account holding nothing is
    not waiting for T+2, and a rejection log keyed on rules exists to be
    counted. ``sellable_from`` is honestly ``None`` and the detail does carry
    the distinguishing fact; the rule name does not.
    """
    outcome = venue_rules[1].strategy.verdicts['naked_short']
    assert _rejected(outcome)
    assert _rule(outcome) == 'unsettled_holding'
    assert outcome.binding_constraint == 0
    assert outcome.sellable_from is None
    assert outcome.detail == {'requested': pair.SHARES_PER_NAME,
                              'settled': 0, 'committed': 0, 'unsettled': 0}


# --------------------------------------------------------------------------
# 3. Charges under each venue's own schedule
# --------------------------------------------------------------------------

def test_the_two_venues_are_charged_on_different_bases(scenario):
    """Seven rules, two pools, and the bases are not the same kind of thing.

    Every amount is recomputed here from the rate and the notional; none of it
    is read back from ``charges.py``.
    """
    totals = pair.charge_totals(scenario)
    got = {(kind, venue, pool, base): (count, total)
           for (kind, venue, pool, base), (count, total) in totals.items()}

    # -- HSX: everything is a fraction of consideration in thousand-dong -----
    equity_bought = _D('796665000')
    equity_sold = _D('415125000')
    turnover = equity_bought + equity_sold

    count, total = got[('pit_securities_transfer', 'HSX', 'securities',
                        'trade_value')]
    assert count == 30                            # SELL side only, 30 names
    assert total == _D('0.001') * equity_sold == _D('415125')

    count, total = got[('exchange_service_hsx_equity', 'HSX', 'securities',
                        'trade_value')]
    assert count == 90                            # both sides
    assert abs(total - _D('0.00027') * turnover) <= _D('5')   # per-fill rounding

    count, total = got[('broker.commission.hsx', 'HSX', 'securities',
                        'trade_value')]
    assert count == 90
    assert abs(total - _D('0.0015') * turnover) <= _D('15')

    # -- HNXDS: two flat per-contract fees and one notional tax -------------
    novated = 3 * pair.CONTRACTS                  # 12 matched contracts
    assert got[('exchange_service_index_future', 'HNXDS', 'derivatives',
                'per_contract')] == (3, _D('2700') * novated)
    assert got[('vsdc_derivatives_clearing', 'HNXDS', 'derivatives',
                'per_contract')] == (3, _D('2550') * novated)
    assert got[('broker.commission.hnxds', 'HNXDS', 'derivatives',
                'per_contract')] == (3, _D('5000') * novated)

    # The derivatives PIT is 0.0005 x the VSD initial margin ratio of the
    # notional, and the ratio is 0.13 until 2022-12-15 -- so 0.000065 here,
    # and 0.000085 for the same trade six weeks later.
    rate = _D('0.0005') * pair.IM_RATE
    assert rate == _D('0.000065')
    count, total = got[('pit_derivatives_transfer', 'HNXDS', 'derivatives',
                        'trade_value')]
    assert count == 4                             # 3 fills plus the maturity
    expected = sum(
        (rate * _D(pair.CONTRACTS) * pair.MULTIPLIER * price).quantize(_D('1'))
        for price in (_D('985.0'), _D('1025.0'), _D('912.8'),
                      pair.CLOSE_PROXY_SETTLEMENT))
    assert total == expected == _D('101278')

    # No charge in the Vietnamese schedule carried here bills VAT to the
    # investor, so amount and total agree everywhere.
    assert all(charge.vat == 0 for charge in scenario.session.charges())


def test_no_charge_is_debited_from_the_wrong_pool(scenario, result):
    """Every HSX charge hits securities, every HNXDS charge hits derivatives.

    Checked directly rather than through ``deposit_segregation``, whose join
    is on ``charge_kind`` and finds no derivatives rows to check: the cash log
    carries the kind in ``cause`` on that side, not in the field.
    """
    for charge in scenario.session.charges():
        expected = (Pool.SECURITIES if charge.venue is Venue.HSX
                    else Pool.DERIVATIVES)
        assert charge.pool is expected, charge
    pools = {entry.pool for entry in result.logs.cash
             if entry.movement is CashMovement.CHARGE_DEBITED}
    assert pools == {'securities', 'derivatives'}


def test_the_derivatives_pool_now_has_an_itemised_fee_statement(result):
    """Finding PT-2, fixed.

    Before the fix the whole of a fill's charges arrived as one movement
    reading ``charges on FILL-000031``, so the deposit -- whose
    ``DepositEntry`` trail is the only cash journal either pool has on the
    session side -- could not be reconciled line by line against
    ``session.charges()``. This is the statement that did not exist.
    """
    statement = pair.derivatives_fee_statement(result)
    kinds = [kind for _, kind, _ in statement]
    assert kinds.count('exchange_service_index_future') == 3
    assert kinds.count('vsdc_derivatives_clearing') == 3
    assert kinds.count('broker.commission.hnxds') == 3
    assert kinds.count('pit_derivatives_transfer') == 4
    assert '' not in kinds                        # every row names its levy

    entry_day = [row for row in statement if row[0].date() == pair.ENTER_A]
    assert sorted(amount for _, _, amount in entry_day) == [
        _D('10200'), _D('10800'), _D('20000'), _D('25610')]
    assert sum(amount for _, _, amount in entry_day) == _D('66610')


# --------------------------------------------------------------------------
# 4. Segregation -- both shapes, and the pair is not half-filled
# --------------------------------------------------------------------------

def test_the_futures_leg_is_refused_on_its_own_pool_while_cash_sits_next_door(
        result, scenario):
    """``funded_in_aggregate=True``: the money is there, in the wrong account.

    This is the behaviour that makes a Vietnamese pair trade different from a
    Western one, where a single margin account would have netted the two legs.
    """
    strategy = scenario.strategy
    assert len(strategy.refusals) == 2            # one per entry
    first = strategy.refusals[0]
    assert _rule(first) == 'insufficient_deposit'
    assert first.detail['short_pool'] is Pool.DERIVATIVES
    assert first.detail['other_pool'] is Pool.SECURITIES
    assert first.detail['auto_transfer'] is False
    assert first.detail['funded_in_aggregate'] is True
    assert first.detail['required'] == _D('51220000.000')
    assert first.detail['shortfall'] == _D('51220000.000')
    assert first.detail['other_pool_available'] > first.detail['shortfall']
    assert first.detail['cure'].startswith(
        'transfer(securities -> derivatives, 51220000.000)')

    # The requirement reproduces from the rulebook: 0.13 x 4 x 100,000 x 985.0
    assert (pair.IM_RATE * _D(pair.CONTRACTS) * pair.MULTIPLIER
            * _D('985.0')) == first.detail['required']


def test_a_pair_that_cannot_be_funded_in_aggregate_is_abandoned_not_half_done(
        source):
    """``funded_in_aggregate=False``, and the caller cancels the other leg.

    The exchange has no notion of a pair and never learns that two orders were
    meant to be one trade. What it does do is tell the caller *which* of two
    very different situations it is in, and that is enough to act on: here the
    thirty equity orders accepted moments earlier are cancelled rather than
    left as a naked 411,750,000d basket.
    """
    days = (pair.ENTER_A, date(2022, 10, 24))
    strategy = pair.PairTrade(deposit_a=pair.DEPOSIT_A)
    scenario = pair.build_scenario(
        source=source, strategy=strategy, name='underfunded',
        end=days[-1], sessions=days,
        # Enough for the basket and not enough for the futures leg on top.
        initial_cash='420000000')
    from validation.runner import run_scenario
    outcome = run_scenario(scenario, raise_on_error=True)

    refusal = strategy.refusals[0]
    assert refusal.detail['funded_in_aggregate'] is False
    assert 'no transfer can fund it' in refusal.detail['cure']
    assert refusal.detail['other_pool_available'] < refusal.detail['shortfall']

    assert len(strategy.abandoned) == len(pair.BASKET) == 30
    cancelled = outcome.logs.trades.of(TradeAction.CANCELLED)
    assert len({row.order_id for row in cancelled}) == 30
    # Nothing filled on either venue, and no reservation survived.
    assert not outcome.logs.trades.of(TradeAction.FILLED)
    assert scenario.session.cash().committed == 0
    assert scenario.session.margin().deposit_balance == 0
    assert outcome.ok, [r.detail for r in outcome.failed_identities]


def test_the_deposit_only_ever_moved_through_explicit_transfers(result,
                                                                scenario):
    """The segregation audit is total because the deposit opened at zero.

    Every dong that reached it is a ``TRANSFER_IN`` row with a matching
    ``TRANSFER_OUT`` on the securities side at the same instant, and the only
    other things that moved it are this account's own fills, charges and
    settlement. There is no path from securities cash to the deposit that is
    not ``ExchangeSession.transfer``.
    """
    cash = result.logs.cash
    assert cash.by_movement('derivatives')[CashMovement.OPENING_BALANCE] == 0

    transfers_in = [e for e in cash
                    if e.pool == 'derivatives'
                    and e.movement is CashMovement.TRANSFER_IN]
    assert [e.amount for e in transfers_in] == [_D('80000000'),
                                                _D('62000000.0')]
    for entry in transfers_in:
        partner = [e for e in cash
                   if e.pool == 'securities' and e.ts == entry.ts
                   and e.movement is CashMovement.TRANSFER_OUT]
        assert len(partner) == 1
        assert partner[0].amount == -entry.amount

    moved = {m for m in cash.by_movement('derivatives')}
    assert moved == {CashMovement.OPENING_BALANCE, CashMovement.TRANSFER_IN,
                     CashMovement.TRANSFER_OUT, CashMovement.CHARGE_DEBITED,
                     CashMovement.REALISED_PNL,
                     CashMovement.EXPIRY_SETTLEMENT}


def test_a_futures_margin_call_never_touches_equity_cash(result):
    """The forced sessions and the securities balance, side by side.

    On 2022-11-16 the deposit is in breach at 1.0933 utilisation while
    137,765,732d of settled securities cash and 27,000 shares sit one pool
    away. Neither moves, and no cash-log row on any breach date touches the
    securities pool.
    """
    breached = [step for step in pair.ladder(result)
                if 'forced_liquidation' in step.events]
    assert [step.day for step in breached] == [
        date(2022, 11, 14), date(2022, 11, 16), date(2022, 11, 17)]
    assert {step.securities_cash for step in breached} == {_D('137765732.00')}

    days = {step.day for step in breached}
    touched = [e for e in result.logs.cash
               if e.pool == 'securities' and e.ts.date() in days]
    assert touched == []


def test_the_deposit_can_be_swept_back_but_only_within_the_withdrawal_bound(
        result, scenario):
    """The reverse leg, and it is not symmetric with the way in.

    ``transfer_out`` is bounded by assets less the requirement at the broker's
    forced-close rung, not by ``free_deposit``; with the first leg flat there
    is no requirement, so the whole balance is withdrawable and the deposit
    returns to exactly zero before the second leg funds it again.
    """
    out = [e for e in result.logs.cash
           if e.pool == 'derivatives'
           and e.movement is CashMovement.TRANSFER_OUT]
    assert len(out) == 1
    assert out[0].ts.date() == pair.SWEEP
    assert out[0].amount == _D('-63865740.0')
    assert out[0].balance_after == 0

    refusal = scenario.session.transfer(
        Pool.DERIVATIVES, Pool.SECURITIES,
        scenario.session.margin().deposit_balance + 1)
    assert _rejected(refusal)
    assert _rule(refusal) == 'insufficient_deposit'


# --------------------------------------------------------------------------
# 5. The margin ladder: the right rung, on the right day
# --------------------------------------------------------------------------

def test_the_ladder_reproduces_from_the_rulebook_not_from_deposit_py(result):
    """Finding PT-8 is baked in here, deliberately.

    ``VM`` is recomputed **from the entry price**, because
    ``DerivativesAccount.settle_daily`` has no session call site and the
    variation-margin baseline therefore never rolls. If a future change wires
    daily settlement in, this test fails -- which is the correct outcome, not
    a nuisance: the ladder below is only right under the no-cash-VM
    convention.
    """
    marks = [(date(2022, 11, 10), _D('912.8')),
             (date(2022, 11, 11), _D('938.0')),
             (date(2022, 11, 14), _D('932.0')),
             (date(2022, 11, 15), _D('895.0')),
             (date(2022, 11, 16), _D('957.6')),
             (date(2022, 11, 17), _D('972.5'))]
    deposit = _D('61935267.0')
    expected = pair.independent_requirement(
        marks, net_contracts=-pair.CONTRACTS, entry_price=_D('912.8'),
        deposit=deposit)

    by_day = {step.day: step for step in pair.ladder(result)}
    for row in expected:
        if row['day'] == pair.WINDOW_END:
            # The close step of the expiry session is *after* the cash
            # settlement, so the contract ledger is empty and the deposit has
            # already been debited. The last mark that has a position behind
            # it is the 09:30 one, and it is the forced event that carries it.
            continue
        step = by_day[row['day']]
        assert step.deposit_balance == deposit, row['day']
        assert step.initial_margin == row['initial_margin'], row['day']
        assert step.variation_margin == row['variation_margin'], row['day']
        assert step.required == row['required'], row['day']

    expiry_mark = [e for e in result.logs.events
                   if e.kind.value == 'forced_liquidation'
                   and e.ts == datetime(2022, 11, 17, 9, 30)][0]
    final = expected[-1]
    assert expiry_mark.detail['initial_margin'] == final['initial_margin']
    assert expiry_mark.detail['variation_margin'] == final['variation_margin']
    assert expiry_mark.detail['utilisation'] == final['utilisation']

    # And the rungs the run actually reported, spelled out.
    assert [(row['day'], row['status']) for row in expected] == [
        (date(2022, 11, 10), 'ok'),
        (date(2022, 11, 11), 'call'),
        (date(2022, 11, 14), 'call'),
        (date(2022, 11, 15), 'ok'),
        (date(2022, 11, 16), 'forced'),
        (date(2022, 11, 17), 'forced'),
    ]


def test_the_call_fires_on_the_day_the_rung_is_crossed_and_names_a_deadline(
        result):
    """One call in the whole run, on 2022-11-11, at 0.9503.

    Not on 2022-11-10 (0.7664, below the warning rung) and not on 2022-11-15
    (0.7514, cured by the market). The deadline is the next session's HNX-DS
    open, which the trading calendar -- not the clock -- resolves to
    2022-11-14 08:45 across the weekend.
    """
    calls = [e for e in result.logs.events if e.kind.value == 'margin_call']
    assert len(calls) == 1
    call = calls[0]
    assert call.ts.date() == date(2022, 11, 11)
    assert call.detail['status'].value == 'call'
    assert _D('0.9502') < call.detail['utilisation'] < _D('0.9504')
    assert call.detail['cure_by'] == datetime(2022, 11, 14, 8, 45)


def test_an_unanswered_call_escalates_on_the_deadline_not_on_the_rung(result):
    """2022-11-14 is a forced close at 0.9065 -- on the *call* rung.

    Both escalation paths appear in this one window: the 2022-11-14 event is
    the 2022-11-11 call going past its deadline unanswered, and the
    2022-11-16 event is utilisation reaching the forced rung outright.
    """
    forced = [e for e in result.logs.events
              if e.kind.value == 'forced_liquidation']
    days = sorted({e.ts.date() for e in forced})
    assert days == [date(2022, 11, 14), date(2022, 11, 16),
                    date(2022, 11, 17)]

    deadline = [e for e in forced if e.ts.date() == date(2022, 11, 14)][0]
    assert deadline.ts == datetime(2022, 11, 14, 9, 30)
    assert deadline.detail['cure_by'] == datetime(2022, 11, 14, 8, 45)
    assert deadline.detail['utilisation'] < _D('0.91')       # the call rung

    rung = [e for e in forced if e.ts.date() == date(2022, 11, 16)][0]
    assert rung.detail['utilisation'] > _D('1.00')
    assert rung.detail['cure_by'] is None


def test_the_forced_close_reports_and_does_not_execute(result, scenario):
    """Finding PT-7, pinned.

    Six events, none of them executed, and the position is still short four
    contracts when the contract expires. A report counting forced closes must
    count distinct sessions, not events.
    """
    forced = [e for e in result.logs.events
              if e.kind.value == 'forced_liquidation']
    assert len(forced) == 6
    assert len({e.ts.date() for e in forced}) == 3
    assert all(e.detail['executed'] is False for e in forced)

    settled = [row for row in result.logs.settlement.of(
        SettlementAction.EXPIRY_SETTLED)]
    assert len(settled) == 1
    assert settled[0].quantity == -pair.CONTRACTS


def test_a_margin_event_stamped_0930_was_computed_from_that_day_s_close(
        result, source):
    """Finding PT-6, pinned rather than papered over.

    The 2022-10-27 warning is computed from IM of 53,300,000d, which is
    0.13 x 4 x 100,000 x 1025.0 -- that session's *close*. On a daily run the
    interval is the whole day, which ``_interval_for`` declares, so a margin
    event timestamped 09:30 is not an intraday event.
    """
    warnings = [e for e in result.logs.events
                if e.kind.value == 'margin_warning']
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.ts == datetime(2022, 10, 27, 9, 30)

    close = closes(source, pair.FUTURE, date(2022, 10, 27),
                   date(2022, 10, 27))[date(2022, 10, 27)]
    assert close == _D('1025.0')
    previous = closes(source, pair.FUTURE, date(2022, 10, 26),
                      date(2022, 10, 26))[date(2022, 10, 26)]
    from_close = pair.IM_RATE * _D(pair.CONTRACTS) * pair.MULTIPLIER * close
    from_previous = (pair.IM_RATE * _D(pair.CONTRACTS) * pair.MULTIPLIER
                     * previous)
    assert warning.detail['initial_margin'] == from_close == _D('53300000.0')
    assert warning.detail['initial_margin'] != from_previous


def test_the_deposit_does_not_move_with_the_daily_mark(result):
    """Finding PT-8: no cash variation margin, at all.

    Six sessions, utilisation 0.7664 to 1.2021, and one deposit balance. The
    whole loss arrives as a single movement at the expiry.
    """
    second_leg = [step for step in pair.ladder(result)
                  if pair.ENTER_B <= step.day < pair.WINDOW_END]
    assert len(second_leg) == 5
    assert {step.deposit_balance for step in second_leg} == {_D('61935267.0')}

    movements = [e for e in result.logs.cash
                 if e.pool == 'derivatives'
                 and pair.ENTER_B < e.ts.date() < pair.WINDOW_END]
    assert movements == []


# --------------------------------------------------------------------------
# 6. Settlement: T+2 on one venue, cash settlement on the other
# --------------------------------------------------------------------------

def test_the_equity_leg_settles_t_plus_two_and_the_futures_leg_does_not(
        result):
    """Two settlement regimes in one log, keyed by pool.

    Thirty tranches created on 2022-10-21 all settle at 13:00 on 2022-10-25 --
    T+2 in settlement business days under Decision 109 -- while the futures
    leg has no tranche at all and resolves once, in cash, at the expiry.
    """
    created = result.logs.settlement.of(SettlementAction.TRANCHE_CREATED)
    settled = result.logs.settlement.of(SettlementAction.TRANCHE_SETTLED)
    assert len(created) == len(settled) == 90
    assert all(row.pool == 'securities' for row in created)

    entry = [row for row in created if row.ts.date() == pair.ENTER_A]
    assert len(entry) == 30
    assert {row.settles_at for row in entry} == {
        datetime(2022, 10, 25, 13, 0)}
    assert {row.settlement_rule for row in entry} == {'T+2 at 13:00:00'}

    expiry = result.logs.settlement.of(SettlementAction.EXPIRY_SETTLED)
    assert len(expiry) == 1
    assert expiry[0].pool == 'derivatives'
    assert expiry[0].ticker == pair.FUTURE
    assert expiry[0].settles_at is None           # cash settlement, not DVP


def test_both_dvp_legs_are_tranched_not_only_the_share_leg(result):
    """Delivery *and* payment, and the cash leg is the one easily forgotten.

    Sixty share tranches from the two rounds of buying, thirty cash tranches
    from the one round of selling, and the cash from a Thursday sale is not
    spendable until the following Monday. The sale proceeds sit as
    ``SALE_PROCEEDS_PENDING`` -- a cash event that moves no settled balance --
    until then.
    """
    created = result.logs.settlement.of(SettlementAction.TRANCHE_CREATED)
    legs = {}
    for row in created:
        legs[row.leg] = legs.get(row.leg, 0) + 1
    assert legs == {'securities': 60, 'cash': 30}

    cash_legs = [row for row in created if row.leg == 'cash']
    assert {row.ts.date() for row in cash_legs} == {pair.EXIT_A}
    assert {row.settles_at for row in cash_legs} == {
        datetime(2022, 10, 31, 13, 0)}          # Thursday sale, Monday cash
    assert sum(row.amount for row in cash_legs) == _D('413975099.00')

    settled = [row for row in result.logs.settlement.of(
        SettlementAction.TRANCHE_SETTLED) if row.leg == 'cash']
    assert {row.settled_at for row in settled} == {
        datetime(2022, 10, 31, 14, 45)}
    assert all(row.settled_at >= row.settles_at for row in settled)

    pending = [e for e in result.logs.cash
               if e.movement is CashMovement.SALE_PROCEEDS_PENDING]
    assert len(pending) == 30
    assert all(not e.affects_balance for e in pending)
    credited = [e for e in result.logs.cash
                if e.movement is CashMovement.SETTLEMENT_CREDIT]
    assert {e.ts.date() for e in credited} == {date(2022, 10, 31)}


def test_the_run_reports_that_its_settlement_calendar_is_unsourced(result):
    """A green run must not hide behind the weekday default.

    No calendar data ships, and the whole of this window is holiday-free, so
    the default happens to be right here -- which is exactly why the
    provenance has to say it was the default.
    """
    assert result.provenance.settlement_calendar_id == 'weekday-only-UNSOURCED'
    assert all(row.settlement_calendar_id == 'weekday-only-UNSOURCED'
               for row in result.logs.settlement)


def test_the_final_settlement_used_a_proxy_when_the_oracle_was_on_disk(
        result, source):
    """Finding PT-9.

    ``quote_settlementprice.parquet`` carries the VN30INDEX closing average
    the exchange strikes the final settlement price from. Its last tick on
    2022-11-17 is 972.78; the session settled at the futures close 972.5 and
    said so. On four short contracts that is 112,000d of loss not booked.
    """
    expiry = [e for e in result.logs.events
              if e.kind.value == 'expiry_settled'][0]
    assert expiry.price == pair.CLOSE_PROXY_SETTLEMENT == _D('972.5')
    assert expiry.detail['settlement_source'] == 'close_proxy'
    assert expiry.detail['substituted'] is True
    assert expiry.detail['price_basis']            # the tier states itself

    understated = ((pair.PUBLISHED_FINAL_SETTLEMENT
                    - pair.CLOSE_PROXY_SETTLEMENT)
                   * _D(pair.CONTRACTS) * pair.MULTIPLIER)
    assert understated == _D('112000.0')

    # The realised cash flow, from the entry price, at the proxy.
    assert expiry.amount == (_D('912.8') - pair.CLOSE_PROXY_SETTLEMENT) * _D(
        pair.CONTRACTS) * pair.MULTIPLIER == _D('-23880000.0')


def test_the_published_settlement_price_really_is_in_this_corpus():
    """The oracle PT-9 says was available, read straight out of the corpus."""
    import duckdb

    from validation.corpus import corpus_root
    root = corpus_root()
    path = root / 'quote_settlementprice.parquet'
    if not path.exists():                          # pragma: no cover
        pytest.skip('this corpus carries no settlement-price table')
    rows = duckdb.connect().execute(
        f"SELECT datetime, price FROM read_parquet('{path}') "
        "WHERE tickersymbol = 'VN30INDEX' "
        "AND datetime::date = DATE '2022-11-17' ORDER BY datetime").fetchall()
    assert len(rows) == 180
    assert rows[0][0] == datetime(2022, 11, 17, 14, 15, 1)
    assert rows[-1][0] == datetime(2022, 11, 17, 14, 45, 12)
    assert _D(str(rows[-1][1])) == pair.PUBLISHED_FINAL_SETTLEMENT


# --------------------------------------------------------------------------
# 7. The findings that are fixes
# --------------------------------------------------------------------------

def test_a_breaching_account_can_close_its_position(breach_then_close):
    """Finding PT-1, and this is the test that fails without the fix.

    The condition is the one that used to refuse: ``free_deposit`` negative,
    status ``forced``, and a purely offsetting order that reserves nothing.
    Restore ``if required > view.free_deposit`` and ``0 > -840733`` is True
    again, the outcome becomes ``Rejected(INSUFFICIENT_DEPOSIT,
    required=0.000)``, and the account cannot close until 2022-11-15 -- by
    which time the market has cured the breach and the test has no subject.
    """
    _, scenario = breach_then_close
    attempts = scenario.strategy.attempts
    assert len(attempts) == 1, 'the close should succeed on the first attempt'

    day, utilisation, status, free_deposit, outcome = attempts[0]
    assert day == date(2022, 11, 11)
    assert status == 'forced'
    assert utilisation > _D('1.22')
    assert free_deposit < 0
    assert free_deposit == _D('-840733.000')
    assert not _rejected(outcome), (
        'an offsetting order reserves nothing and cannot be unaffordable')
    assert scenario.session.positions() == {}


def test_closing_reserves_nothing_which_is_why_it_must_not_be_funding_tested(
        breach_then_close):
    """The zero-amount encumbrance the docstring promises, observed.

    ``reserve_for_order`` says an offsetting order "reserves zero and gets a
    zero-amount encumbrance -- a reservation of nothing, which is the honest
    record of a resource that was not consumed". This is that record.
    """
    result, _ = breach_then_close
    accepted = [row for row in result.logs.trades.of(TradeAction.ACCEPTED)
                if row.side == 'BUY']
    assert len(accepted) == 1
    encumbrances = accepted[0].detail['encumbrances']
    assert len(encumbrances) == 1
    assert encumbrances[0]['resource'] == 'deposit'
    assert encumbrances[0]['pool'] == 'derivatives'
    assert encumbrances[0]['amount'] == 0


# --------------------------------------------------------------------------
# 8. The findings that are not fixes
# --------------------------------------------------------------------------

def test_obeying_the_printed_cure_is_a_forced_close_on_the_same_session(
        bare_cure):
    """Finding PT-3, in full.

    The refusal prints ``transfer(securities -> derivatives, 51220000.000) and
    resubmit``. Doing exactly that lands the deposit at *exactly* the initial
    margin, which ``reserve_for_order`` admits -- its test is
    ``required > free_deposit``, false at equality -- and which
    ``margin_status`` counts as a breach, its test being
    ``utilisation >= forced_close_utilisation``. So the account is FORCED at
    utilisation 1 before a single charge is levied, and the fill's own 66,610d
    of charges then take it to 1.0013.
    """
    result, scenario = bare_cure
    strategy = scenario.strategy
    assert strategy.transferred == _D('51220000.000')
    assert strategy.refusal.detail['cure'] == (
        'transfer(securities -> derivatives, 51220000.000) and resubmit')

    entry = [s for s in result.snapshots if s.ts.date() == pair.ENTER_A]
    opening, closing = entry[0], entry[1]

    # Exactly at the rung, before any charge.
    assert opening.deposit_balance == _D('51220000.000')
    assert opening.initial_margin == _D('51220000.000')
    assert opening.utilisation == 1
    assert opening.margin_status == 'forced'

    # And past it, after the fill's charges come out of the same deposit.
    assert closing.deposit_balance == _D('51153390.000')
    assert (_D('51220000.000') - closing.deposit_balance) == _D('66610')
    assert closing.utilisation > 1
    assert closing.margin_status == 'forced'

    forced = [e for e in result.logs.events
              if e.kind.value == 'forced_liquidation']
    assert forced and forced[0].ts.date() == pair.ENTER_A


def test_neither_leg_can_be_adjudicated_on_the_daily_corpus(hard_arm):
    """Finding PT-5, and it is the caveat over the whole scenario.

    Under ``hard`` the equity leg and the futures leg are both INDETERMINATE
    at a continuous touch, both orders expire unfilled, and
    ``by_field`` is empty -- the continuous-touch refusal names no
    ``DataField``, so a report cannot even say which column was missing. Every
    fill in the main run is therefore a ``soft`` model output.
    """
    result, _ = hard_arm
    assert result.provenance.fill_policy_kind == 'hard(max_participation=0.10)'
    assert result.indeterminate.evaluations == 3
    assert result.indeterminate.indeterminate == 2
    assert result.indeterminate.by_field == {}
    assert result.indeterminate.by_rule == {}

    undecided = result.logs.trades.of(TradeAction.INDETERMINATE)
    assert {row.ticker for row in undecided} == {'ACB', pair.FUTURE}
    assert all(row.missing_fields == () for row in undecided)

    expired = result.logs.trades.of(TradeAction.EXPIRED)
    assert {row.ticker for row in expired} == {'ACB', pair.FUTURE}
    assert not result.logs.trades.of(TradeAction.FILLED)


def test_the_soft_arm_says_what_it_assumed(result):
    """The other half of PT-5: the main run declares its own policy.

    The signature is now ``soft(max_participation=uncapped)`` and the bare
    token ``'soft'`` is no longer produced by anything. That is deliberate on
    the policy's side: ``soft`` became a capped policy, so a record written
    while the configured cap was being silently discarded must not be
    confusable with a repaired uncapped run.
    """
    assert result.provenance.fill_policy_kind == 'soft(max_participation=uncapped)'
    assert result.indeterminate.indeterminate == 0
    fills = result.logs.trades.of(TradeAction.FILLED)
    assert len(fills) == 93
    assert {row.detail['evidence'].value for row in fills} == {
        'touched_at_limit'}


# --------------------------------------------------------------------------
# 9. The audit: every dong, every order, every identity
# --------------------------------------------------------------------------

def test_every_identity_holds_over_the_whole_run(result):
    assert result.error is None
    assert result.sessions_run == 20
    assert result.ok, [row.to_row() for row in result.failed_identities]
    # Ten since 2026-08-27: ``settlement_completeness`` joined the suite.
    assert len(result.identities) == 10
    assert 'settlement_completeness' in {r.name for r in result.identities}
    # And it is not vacuous here: 90 tranches were created and discharged.
    assert len(result.logs.settlement.of(SettlementAction.TRANCHE_SETTLED)) == 90


def test_every_order_reached_a_terminal_state(result, scenario):
    """Not a restatement of ``order_lifecycle``: that one checks the *book*.

    This checks the log, which is the thing a broker hands a client, and
    counts the terminal rows against the accepted ones.
    """
    accepted = result.logs.trades.of(TradeAction.ACCEPTED)
    assert len(accepted) == 93
    assert len({row.order_id for row in accepted}) == 93

    filled = {row.order_id for row in result.logs.trades.of(
        TradeAction.FILLED, TradeAction.PARTIALLY_FILLED)}
    cancelled = {row.order_id for row in result.logs.trades.of(
        TradeAction.CANCELLED)}
    expired = {row.order_id for row in result.logs.trades.of(
        TradeAction.EXPIRED)}
    assert filled | cancelled | expired == {row.order_id for row in accepted}

    assert not [r for r in scenario.session.orders() if not r.is_terminal]
    assert scenario.session.cash().committed == 0
    assert scenario.session.margin().resting_order_margin == 0


def test_every_dong_is_accounted_for(result, scenario, closing_marks):
    """The residual is zero, and that is the whole assertion.

    Opening balances against closing cash, closing deposit and the basket
    marked on the caller's own feed, less the four things that can cause a
    change: equity consideration, realised derivatives P&L, final settlement
    and charges. Anything left over is a movement no log row explains.
    """
    book = pair.reconciliation(result, scenario, closing_marks)
    assert book['residual'] == 0

    assert book['opening'] == pair.INITIAL_CASH == _D('600000000')
    assert book['closing_cash'] == _D('137765732.00')
    assert book['closing_deposit'] == _D('38029982.0')
    assert book['closing_holdings_value'] == _D('393885000.00')
    assert book['change'] == _D('-30319286.00')

    assert book['equity_bought'] == _D('796665000.00')
    assert book['equity_sold_gross'] == _D('415125000.00')
    assert book['equity_charges'] == _D('2560008')
    assert book['derivatives_realised'] == _D('-16000000.0')
    assert book['derivatives_expiry'] == _D('-23880000.0')
    assert book['derivatives_charges'] == _D('224278')

    # The hedge cost, stated as such: short 4 at 985.0, bought back at 1025.0
    # when the basis closed from -25.57 to -3.50.
    assert book['derivatives_realised'] == (
        _D('985.0') - _D('1025.0')) * _D(pair.CONTRACTS) * pair.MULTIPLIER


def test_the_cash_log_reconciles_against_both_reported_balances(result,
                                                                scenario):
    """``cash_conservation`` for both pools, spelled out with the itemisation.

    The identity already asserts this; repeating it with the movement
    breakdown is what makes a failure legible, because the identity reports a
    difference and not which movement produced it.
    """
    securities = result.logs.cash.by_movement('securities')
    derivatives = result.logs.cash.by_movement('derivatives')
    assert (sum(v for m, v in securities.items()
                if m is not CashMovement.CHARGE_WITHHELD
                and m is not CashMovement.SALE_PROCEEDS_PENDING)
            == scenario.session.cash().settled_balance)
    assert sum(derivatives.values()) == (
        scenario.session.margin().deposit_balance)
    # Balance-neutral rows are neutral: the pending proceeds and the charges
    # withheld from them never touch a settled balance.
    assert all(not entry.affects_balance for entry in result.logs.cash
               if entry.movement in (CashMovement.SALE_PROCEEDS_PENDING,
                                     CashMovement.CHARGE_WITHHELD))


def test_holdings_are_conserved_across_two_ledgers_at_once(result, scenario):
    """The identity routes by pool; this checks it did so for both.

    30 equity names on the securities holdings ledger, one contract code on
    the derivatives contract ledger, and the derivatives leg is zero at the
    end because the contract expired -- which is a real reduction and not a
    breach.
    """
    conservation = [row for row in result.identities
                    if row.name == 'holdings_conservation'][0]
    assert conservation.passed, conservation.breaches

    for ticker in pair.BASKET:
        assert scenario.session.holdings(ticker).total == pair.SHARES_PER_NAME
        assert scenario.session.holdings(ticker).settled == pair.SHARES_PER_NAME
    assert scenario.session.positions() == {}


def test_the_segregation_identity_now_checks_both_pools(result, scenario):
    """Finding PT-10, **closed**. This test is the inversion it asked for.

    It used to read ``test_one_identity_passes_because_it_found_nothing_to
    _check`` and assert ``joined['HNXDS'] == [13, 0]`` with the note *"if this
    becomes [13, 13] the finding is closed and this test should be inverted"*.
    It has, so it is.

    The cause was one-sided journalling: ``deposit_segregation`` joins on
    ``charge_kind`` and ``fill_id``, those fields were populated on every
    securities cash row and on **none** of the derivatives ones, and so the
    check ran 210 times on one pool and zero times on the other while
    reporting a pass either way. ``LedgerJournal.drain_deposit`` now
    re-attaches the itemisation from ``session.charges()``.
    """
    identity = [row for row in result.identities
                if row.name == 'deposit_segregation'][0]
    assert identity.passed, identity.breaches

    joined = {'HSX': [0, 0], 'HNXDS': [0, 0]}
    for charge in scenario.session.charges():
        rows = [e for e in result.logs.cash
                if e.charge_kind == charge.kind and e.fill_id == charge.fill_id
                and e.ts == charge.ts]
        bucket = joined[charge.venue.value]
        bucket[0] += 1
        bucket[1] += 1 if rows else 0
    assert joined['HSX'] == [210, 210]
    assert joined['HNXDS'] == [13, 13]     # was [13, 0]

    # Both the typed fields and the prose are now present, so the fee
    # statement and the identity read the same row.
    derivatives = [e for e in result.logs.cash
                   if e.pool == 'derivatives'
                   and e.movement is CashMovement.CHARGE_DEBITED]
    assert len(derivatives) == 13
    assert all(e.charge_kind is not None for e in derivatives)
    assert all(e.detail.get('pool') == 'derivatives' for e in derivatives)
    assert all(': ' in (e.cause or '') for e in derivatives)


def test_the_holding_charges_are_never_levied(scenario):
    """Finding PT-11: a dated charge rule with no call site.

    Everything with ``debited_at=FILL`` is levied; everything with
    ``debited_at=MONTHLY`` is not, because no daily or monthly pass exists.
    The custody fee is the one that bites over this window.
    """
    from datetime import datetime as _dt

    from plutus.market.session.types import ChargeClass

    rules = scenario.session._rulebook.at(
        _dt.combine(pair.ENTER_A, _dt.min.time()))
    scheduled = {rule.charge_id: rule
                 for rule in rules.charges(Venue.HSX, ChargeClass.EQUITY)}
    assert 'vsdc_custody_equity' in scheduled
    custody = scheduled['vsdc_custody_equity']
    assert custody.base.value == 'monthly_per_security'
    assert custody.debited_at.value == 'monthly'
    assert custody.amount == _D('0.27')

    levied = {charge.kind for charge in scenario.session.charges()}
    assert 'vsdc_custody_equity' not in levied
    assert 'vsdc_derivatives_position_management' not in levied
    assert {rule.charge_id for rule in scheduled.values()
            if rule.debited_at.value == 'fill'} <= levied

    # What it would have come to, so the omission has a size.
    units = _D(len(pair.BASKET) * pair.SHARES_PER_NAME)
    assert units == _D('9000')
    assert custody.amount * units == _D('2430.00')


# --------------------------------------------------------------------------
# 10. The findings are carried as data
# --------------------------------------------------------------------------

def test_the_findings_are_reported_as_data_not_only_as_prose():
    rows = pair.findings()
    assert len(rows) == 11
    assert {row['id'] for row in rows} == {f'PT-{i}' for i in range(1, 12)}
    assert {row['status'] for row in rows} == {'fixed', 'open'}
    fixed = [row for row in rows if row['status'] == 'fixed']
    assert {row['id'] for row in fixed} == {'PT-1', 'PT-2'}
    for row in rows:
        assert row['where'] and row['what'] and row['evidence']
        assert row['severity'] in ('high', 'medium', 'low')
        if row['status'] == 'fixed':
            assert row['fix']
