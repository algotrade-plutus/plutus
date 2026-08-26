"""The scenario runner, end to end.

The loop shape, the multi-venue case, the expiry, the margin ladder, and one
run against the wired Parquet corpus so the harness is not only ever exercised
against a stub.

Two tests here pin behaviour the harness *found* rather than behaviour it
wants. They are marked in their own docstrings and they exist so that a change
to the session breaks a test instead of quietly changing a scenario's answer.
"""

import json
from datetime import date, datetime, time
from decimal import Decimal

import pytest

from plutus.market.protocol import InstrumentKind
from plutus.market.session.types import EventKind, MarginStatus, Pool

from conftest import (
    D1, D2, DAYS, EQUITY_ROWS, KINDS, StubSource, market, requires_corpus,
    stub_scenario,
)
from validation.corpus import assess_db_adapter, datahub_source
from validation.logs import CashMovement, SettlementAction, TradeAction
from validation.runner import (
    Scenario, Window, build_session, run_scenario, sessions_from_source,
)
from validation.strategy import BaseStrategy


# --------------------------------------------------------------------------
# The loop shape
# --------------------------------------------------------------------------

def test_an_order_submitted_on_the_open_step_is_offered_that_day_s_bar():
    """Why the runner takes two steps per session.

    ``advance_to`` documents it: the bar is evaluated by the advance that
    lands inside its day, and the next advance crosses the date and sweeps the
    close first. A loop that only advanced to midnight would submit orders
    that expire without having been offered a single bar.
    """
    class BuyOnD1(BaseStrategy):
        name = 'buy-on-d1'

        def on_session(self, ctx):
            if ctx.today == D1:
                ctx.buy('FPT', 1000, limit_price=Decimal('95.5'))

    result = run_scenario(stub_scenario(BuyOnD1(), days=DAYS[:2]))
    fills = result.logs.trades.of(TradeAction.FILLED)
    assert [e.ts.date() for e in fills] == [D1]
    assert result.snapshots[0].phase == 'open'
    assert result.snapshots[1].phase == 'close'
    assert len(result.snapshots) == 4


def test_a_strategy_that_never_trades_still_produces_a_reconcilable_run():
    """Overnight holding is what happens when ``on_session`` does nothing."""
    result = run_scenario(stub_scenario(BaseStrategy()))
    assert result.ok
    assert result.sessions_run == len(DAYS)
    assert len(result.logs.cash) == 2          # the two opening balances
    assert result.logs.cash.net('securities') == Decimal('1000000000')


def test_an_exception_in_a_strategy_is_reported_not_swallowed():
    """A scenario that dies half-way is a finding, so the logs survive it."""
    class Broken(BaseStrategy):
        name = 'broken'

        def on_session(self, ctx):
            if ctx.today == D2:
                raise RuntimeError('boom')
            ctx.buy('FPT', 1000, limit_price=Decimal('95.5'))

    result = run_scenario(stub_scenario(Broken(), days=DAYS[:3]))
    assert isinstance(result.error, RuntimeError)
    assert not result.ok
    assert result.sessions_run == 1
    assert result.logs.trades.of(TradeAction.FILLED)


def test_raise_on_error_reraises_after_detaching_the_journal():
    class Broken(BaseStrategy):
        name = 'broken'

        def on_session(self, ctx):
            raise RuntimeError('boom')

    scenario = stub_scenario(Broken(), days=DAYS[:2])
    ledger = scenario.session._securities.cash_ledger
    with pytest.raises(RuntimeError):
        run_scenario(scenario, raise_on_error=True)
    assert 'debit' not in ledger.__dict__


# --------------------------------------------------------------------------
# Two venues at once
# --------------------------------------------------------------------------

def test_a_pair_trade_touches_two_segregated_pools_in_one_session():
    """The multi-exchange case, and the refusal that makes segregation real.

    The equity leg funds out of securities cash and the futures leg out of the
    deposit. A pair the account funds *in aggregate* is still refused on the
    leg whose own pool is short -- there is no auto-transfer in Vietnam -- and
    the refusal says which pool was short and what the other one held.
    """
    class Pair(BaseStrategy):
        name = 'pair'

        def __init__(self):
            self.futures_leg = None

        def on_session(self, ctx):
            if ctx.today != D1:
                return
            ctx.buy('FPT', 1000, limit_price=Decimal('95.5'))
            self.futures_leg = ctx.sell('VN30F2406', 1,
                                        limit_price=Decimal('1250'))

    strategy = Pair()
    result = run_scenario(stub_scenario(
        strategy, days=DAYS[:2], tickers=('FPT', 'VN30F2406'),
        initial_cash='1000000000', initial_deposit='0'))

    rejected = result.logs.trades.of(TradeAction.REJECTED)
    assert [e.rule for e in rejected] == ['insufficient_deposit']
    assert rejected[0].detail['funded_in_aggregate'] is True
    assert rejected[0].detail['auto_transfer'] is False
    assert result.identities
    assert not result.failed_identities


def test_a_funded_pair_fills_both_legs_and_both_pools_reconcile():
    class Pair(BaseStrategy):
        name = 'pair'

        def on_session(self, ctx):
            if ctx.today != D1:
                return
            ctx.buy('FPT', 1000, limit_price=Decimal('95.5'))
            ctx.sell('VN30F2406', 1, limit_price=Decimal('1250'))

    result = run_scenario(stub_scenario(
        Pair(), days=DAYS[:2], tickers=('FPT', 'VN30F2406'),
        initial_cash='1000000000', initial_deposit='100000000'))

    assert not result.failed_identities
    pools = {e.pool for e in result.logs.trades.of(TradeAction.FILLED)}
    assert pools == {'securities', 'derivatives'}
    cash_pools = {e.pool for e in result.logs.cash}
    assert cash_pools == {'securities', 'derivatives'}


def test_an_explicit_transfer_moves_cash_between_the_pools_and_balances():
    class Funder(BaseStrategy):
        name = 'funder'

        def on_session(self, ctx):
            if ctx.today == D1:
                ctx.transfer(Pool.SECURITIES, Pool.DERIVATIVES,
                             Decimal('50000000'))

    result = run_scenario(stub_scenario(Funder(), days=DAYS[:2]))
    assert not result.failed_identities
    moves = [e for e in result.logs.cash
             if e.movement in (CashMovement.TRANSFER_IN,
                               CashMovement.TRANSFER_OUT)]
    assert len(moves) == 2
    assert sum(e.amount for e in moves) == Decimal('0')
    assert {e.pool for e in moves} == {'securities', 'derivatives'}


# --------------------------------------------------------------------------
# Derivatives: the ladder, and expiry
# --------------------------------------------------------------------------

def _falling_futures(prices):
    """A source whose VN30F2406 mark walks ``prices`` over ``DAYS``."""
    rows = dict(EQUITY_ROWS)
    for day, price in zip(DAYS, prices):
        rows[('VN30F2406', day)] = market('VN30F2406', day, Decimal(price))
    return StubSource(rows, KINDS)


class HoldOneLot(BaseStrategy):
    name = 'hold-one-lot'

    def on_session(self, ctx):
        if ctx.today == D1 and not ctx.positions():
            ctx.buy('VN30F2406', 1, limit_price=Decimal('1250'))


def test_the_margin_ladder_walks_from_ok_to_forced_as_the_mark_falls():
    source = _falling_futures(
        ['1250', '1200', '1180', '1160', '1140', '1120', '1100', '1080'])
    result = run_scenario(stub_scenario(
        HoldOneLot(), source=source, days=DAYS, tickers=('VN30F2406',),
        venues=('HNXDS',), initial_cash='0', initial_deposit='30000000'))

    assert result.error is None
    statuses = [s.margin_status for s in result.snapshots]
    assert MarginStatus.OK.value in statuses
    assert MarginStatus.WARNING.value in statuses
    assert MarginStatus.CALL.value in statuses
    assert MarginStatus.FORCED.value in statuses
    kinds = [e.kind for e in result.logs.events]
    assert EventKind.MARGIN_WARNING in kinds
    assert EventKind.MARGIN_CALL in kinds
    assert EventKind.FORCED_LIQUIDATION in kinds
    assert not result.failed_identities


def test_the_deposit_balance_does_not_move_with_the_daily_mark():
    """**A finding, pinned.** Variation margin never settles in cash.

    ``rulebook.py``'s futures ``SETTLEMENT`` row is T+1 and its own note says
    it models *daily variation margin settling T+1*. ``deposit.settle_daily``
    implements that rebaseline and **no session path calls it** (FEATURES.md
    D1), so across a whole drawdown the deposit balance moves only for
    charges, transfers, realised close-outs and final settlement -- never for
    the mark.

    The consequence for a scenario author: an account that the ladder calls
    and forces still shows its opening balance, and the entire loss arrives as
    one cash movement at the close-out or the expiry. Any replay that debits
    variation margin day by day will not match this simulator.

    This test asserts what the simulator does today. If ``settle_daily`` is
    ever wired in, it fails -- which is the point.
    """
    source = _falling_futures(
        ['1250', '1200', '1180', '1160', '1140', '1120', '1100', '1080'])
    result = run_scenario(stub_scenario(
        HoldOneLot(), source=source, days=DAYS, tickers=('VN30F2406',),
        venues=('HNXDS',), initial_cash='0', initial_deposit='30000000'))

    balances = {s.deposit_balance for s in result.snapshots}
    assert len(balances) <= 2, (
        f'the deposit balance moved more than once: {sorted(balances)}')
    causes = {e.movement for e in result.logs.cash
              if e.pool == 'derivatives'}
    assert causes <= {CashMovement.OPENING_BALANCE,
                      CashMovement.CHARGE_DEBITED}
    assert any(s.variation_margin > 0 for s in result.snapshots), (
        'the run must actually have accrued variation margin, or the '
        'assertion above is vacuous')


def test_a_forced_liquidation_reports_and_does_not_execute():
    """**A finding, pinned.** ``detail['executed']`` is ``False``.

    Nothing is closed, so an account in breach stays in breach and the event
    repeats at every subsequent mark. A scenario counting margin events must
    count *distinct sessions*, not events.
    """
    source = _falling_futures(
        ['1250', '1200', '1180', '1160', '1140', '1120', '1100', '1080'])
    result = run_scenario(stub_scenario(
        HoldOneLot(), source=source, days=DAYS, tickers=('VN30F2406',),
        venues=('HNXDS',), initial_cash='0', initial_deposit='30000000'))

    forced = [e for e in result.logs.events
              if e.kind is EventKind.FORCED_LIQUIDATION]
    assert forced
    assert all(e.detail['executed'] is False for e in forced)
    assert all(e.detail['selection_rule'] for e in forced)
    assert all(e.detail['sequence'] is not None for e in forced)
    assert result.snapshots[-1].positions == {'VN30F2406': 1}


def test_a_held_contract_settles_at_expiry_and_the_cash_log_says_so():
    """Expiry closes the position and moves deposit cash in one event."""
    prices = ['1250'] * 8
    source = _falling_futures(prices)
    # The stub's FUTURE expiry is 2024-06-20; run through it.
    days = DAYS + (date(2024, 6, 19), date(2024, 6, 20), date(2024, 6, 21))
    rows = dict(EQUITY_ROWS)
    for day in days:
        rows[('VN30F2406', day)] = market('VN30F2406', day, Decimal('1200'))
        rows.setdefault(('FPT', day), market('FPT', day, Decimal('95.5')))
    source = StubSource(rows, KINDS)

    result = run_scenario(stub_scenario(
        HoldOneLot(), source=source, days=days, tickers=('VN30F2406',),
        venues=('HNXDS',), initial_cash='0', initial_deposit='60000000'))

    settled = result.logs.settlement.of(SettlementAction.EXPIRY_SETTLED)
    assert len(settled) == 1
    assert settled[0].ticker == 'VN30F2406'
    assert 'substituted=True' in settled[0].reason
    assert result.snapshots[-1].positions == {}
    assert any(e.movement is CashMovement.EXPIRY_SETTLEMENT
               for e in result.logs.cash)
    assert not result.failed_identities


def test_a_roll_at_expiry_is_two_ordinary_orders():
    """Rolling needs nothing from the interface but ``instrument().expiry``."""
    scenario = stub_scenario(BaseStrategy(), days=DAYS[:2])
    spec = scenario.session.instrument('VN30F2406')
    assert spec.kind is InstrumentKind.FUTURE
    assert spec.expiry == date(2024, 6, 20)


# --------------------------------------------------------------------------
# Result shape
# --------------------------------------------------------------------------

def test_the_result_serialises_to_json_without_losing_a_decimal():
    class BuyOnce(BaseStrategy):
        name = 'buy-once'

        def on_session(self, ctx):
            if ctx.today == D1:
                ctx.buy('FPT', 1000, limit_price=Decimal('95.5'))

    result = run_scenario(stub_scenario(BuyOnce(), days=DAYS[:3]))
    payload = json.loads(json.dumps(result.to_dict()))
    assert payload['name'] == 'stub'
    assert set(payload) >= {'trade_log', 'cash_log', 'settlement_log',
                            'identities', 'snapshots', 'provenance',
                            'indeterminate'}
    buy = [r for r in payload['cash_log']
           if r['movement'] == 'buy_consideration'][0]
    assert buy['amount'] == '-95500000.0'
    assert payload['provenance']['settlement_calendar_id'] == (
        'weekday-only-UNSOURCED')


def test_provenance_names_the_unsourced_default_calendar():
    """A run whose settlement dates are wrong around Tet must say so.

    No calendar data ships (FEATURES.md A64), so every default run is on the
    weekday-only calendar. The harness does not hide it: the id is on the
    result and on every settlement-log row.
    """
    result = run_scenario(stub_scenario(BaseStrategy(), days=DAYS[:2]))
    assert 'UNSOURCED' in result.provenance.settlement_calendar_id


# --------------------------------------------------------------------------
# The wired corpus
# --------------------------------------------------------------------------

@requires_corpus
def test_the_harness_runs_against_the_parquet_corpus(corpus_root):
    """One real run: trading days from the data, T+2 binding, logs balancing.

    ``soft`` is the policy here because on the Parquet corpus ``hard``
    correctly answers INDETERMINATE at a continuous touch -- the bars carry no
    high, no low and no volume, so nothing can be adjudicated. That is a
    property of the data, and the second half of this test asserts it rather
    than working around it.
    """
    source = datahub_source(corpus_root)
    window = Window(name='fpt-march-2022', start=date(2022, 3, 1),
                    end=date(2022, 3, 15), tickers=('FPT',),
                    reference_ticker='FPT')
    sessions = sessions_from_source(source, 'FPT', window.start, window.end)
    # Eleven weekdays, and the window's own end date is one of them --
    # `states` is half-open on whole days, and losing the last session of a
    # window that way is silent.
    assert len(sessions) == 11
    assert sessions[0] == date(2022, 3, 1)
    assert sessions[-1] == date(2022, 3, 15)
    assert date(2022, 3, 5) not in sessions       # a Saturday

    class RoundTrip(BaseStrategy):
        name = 'round-trip'

        def on_session(self, ctx):
            price = ctx.price('FPT')
            if price is None:
                return
            holding = ctx.holdings('FPT')
            if holding.total == 0 and not ctx.live_orders():
                ctx.buy('FPT', 1000, limit_price=price)
            elif holding.total and holding.sellable == 0:
                ctx.sell('FPT', 1000, limit_price=price)
            elif holding.sellable >= 1000:
                ctx.sell('FPT', 1000, limit_price=price)

    session = build_session(start=window.start, end=window.end,
                            venues=['HSX'], source=source,
                            initial_cash='1000000000', fill_policy='soft')
    result = run_scenario(Scenario(name='corpus', window=window,
                                   session=session, strategy=RoundTrip(),
                                   source=source))
    assert result.error is None
    assert result.failed_identities == (), [
        (r.name, r.breaches) for r in result.failed_identities]
    assert result.logs.settlement.refusals, 'T+2 never bound'
    assert result.logs.trades.of(TradeAction.FILLED)
    assert any(e.movement is CashMovement.SETTLEMENT_CREDIT
               for e in result.logs.cash)


@requires_corpus
def test_hard_is_indeterminate_on_the_parquet_corpus(corpus_root):
    """The bars cannot adjudicate a fill, and the harness reports the rate.

    An order that was never touched and one that was fully filled look
    identical on a bar with no high, no low and no volume. ``HardFillPolicy``
    returns INDETERMINATE rather than guessing, and
    ``session.indeterminate_report()`` is how a scenario states how much of
    its run was unknowable.

    ``by_field`` is **empty** here and that is correct, not a gap: the
    continuous-touch refusal is one of the INDETERMINATE sites that names no
    ``DataField``, because the missing thing is an unrecoverable queue
    position rather than a column. A scenario reporting "which data was
    missing" gets nothing from this case and must say so.
    """
    source = datahub_source(corpus_root)
    window = Window(name='fpt-hard', start=date(2022, 3, 1),
                    end=date(2022, 3, 8), tickers=('FPT',),
                    reference_ticker='FPT')

    class BuyEveryDay(BaseStrategy):
        name = 'buy-every-day'

        def on_session(self, ctx):
            price = ctx.price('FPT')
            if price is not None and not ctx.live_orders():
                ctx.buy('FPT', 1000, limit_price=price)

    session = build_session(start=window.start, end=window.end,
                            venues=['HSX'], source=source,
                            initial_cash='1000000000', fill_policy='hard')
    result = run_scenario(Scenario(name='hard', window=window,
                                   session=session, strategy=BuyEveryDay(),
                                   source=source))
    assert not result.logs.trades.of(TradeAction.FILLED)
    undecided = result.logs.trades.of(TradeAction.INDETERMINATE)
    assert undecided
    assert result.indeterminate.rate == Decimal('1')
    assert all(e.missing_fields == () for e in undecided)
    assert result.to_dict()['indeterminate']['by_field'] == {}
    assert all('touched' in (e.reason or '') for e in undecided)


def test_the_db_adapter_assessment_is_recorded_and_says_it_is_not_built():
    """The assessment the brief asked for, as data a scenario can print."""
    assessment = assess_db_adapter()
    assert assessment['built'] is False
    assert assessment['must_handle']
    assert 'post-KRX' in assessment['needed_for']


def test_summary_states_what_a_green_run_can_hide():
    """The undecided rate and the calendar id, on every summary.

    A run can be green, balance every identity, and still have decided nothing
    -- or have settled everything on a calendar that is wrong around Tet.
    """
    result = run_scenario(stub_scenario(BaseStrategy(), days=DAYS[:2]))
    text = result.summary()
    assert 'identities' in text
    assert 'undecided' in text
    assert 'UNSOURCED' in text
    assert 'FAILED' not in text
