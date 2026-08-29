"""The strategy interface and the context facade.

Two claims are load-bearing here and both are about what the facade *refuses*
to expose. The event cursor is destructive and single-consumer, so a strategy
that drained it would silently starve the logs; and market data is the
caller's own feed, not something the exchange hands out.

The rest is the trade log's completeness: the refusals that never reach the
event cursor have to be captured from the return value or they are lost.
"""

from decimal import Decimal

from plutus.market.session.types import Pool, Rejected

from conftest import D1, D2, DAYS, stub_scenario
from validation.logs import TradeAction
from validation.runner import run_scenario
from validation.strategy import (
    BaseStrategy, StepPhase, Strategy, StrategyContext,
)


def test_the_context_does_not_expose_poll_or_the_session():
    """The cursor is destructive and single-consumer.

    ``advance_to()`` returns the events it generated *and* consumes them. If a
    strategy could call ``poll()`` it would take events the runner then never
    sees, and the trade log would be missing them with no error anywhere.
    """
    scenario = stub_scenario(BaseStrategy())
    ctx = StrategyContext(scenario.session, scenario.source, None, lambda: 0)
    assert not hasattr(ctx, 'poll')
    assert not hasattr(ctx, 'session')
    assert not hasattr(ctx, 'advance_to')


def test_base_strategy_satisfies_the_protocol():
    """``Strategy`` is structural: inheriting is optional, shape is not."""
    assert isinstance(BaseStrategy(), Strategy)

    class Handwritten:
        name = 'handwritten'

        def on_start(self, ctx): ...
        def on_events(self, ctx, events): ...
        def on_session(self, ctx): ...
        def on_finish(self, ctx): ...

    assert isinstance(Handwritten(), Strategy)


def test_market_data_comes_from_the_feed_not_from_the_exchange():
    """``ctx.market`` reads the run's data source directly.

    A real algorithm has its own feed; the broker tells it about its orders.
    Reading the price off the session would also read a *stale* state, since
    the session keeps the last observed one for the MTL residual price.
    """
    scenario = stub_scenario(BaseStrategy())
    ctx = StrategyContext(scenario.session, scenario.source, None, lambda: 0)
    scenario.session.advance_to(
        __import__('datetime').datetime.combine(
            D1, __import__('datetime').time(9, 30)))
    assert ctx.price('FPT') == Decimal('95.5')
    assert ctx.market('NOT-A-TICKER') is None
    assert ctx.price('NOT-A-TICKER') is None


class Refuser(BaseStrategy):
    """Provokes the three refusals that never reach the event cursor."""

    name = 'refuser'

    def __init__(self):
        self.cancel_refusal = None
        self.amend_refusal = None
        self.transfer_refusal = None

    def on_session(self, ctx):
        if ctx.today != D1:
            return
        ack = ctx.buy('FPT', 1000, limit_price=Decimal('90.0'))
        # MUST #2 amend re-runs admission, so raising the quantity is no longer
        # refused by design -- it is admitted when it funds. A refusal now comes
        # from a rule the re-admission newly violates: reducing to 50 lands on
        # an odd lot (ROUND_LOT). That refusal still never reaches the cursor.
        self.amend_refusal = ctx.amend(ack.order_id, quantity=50)
        # The deposit is empty, so a transfer out of it is refused.
        self.transfer_refusal = ctx.transfer(
            Pool.DERIVATIVES, Pool.SECURITIES, Decimal('1'))


def test_refusals_that_never_reach_the_cursor_are_still_logged():
    """FEATURES.md D13: amend, cancel and transfer refusals emit no event.

    The context captures them from the return value, which is the only place
    they exist. A trade log built from the event stream alone would show an
    order that was never amended and no reason why. Under MUST #2 the amend
    path re-runs admission, so the refusal here is a re-admission refusal
    (ROUND_LOT) rather than the old blanket amend-up refusal -- still off the
    cursor, still captured off the return value.
    """
    strategy = Refuser()
    result = run_scenario(stub_scenario(strategy, days=DAYS[:2]))
    assert result.error is None
    assert isinstance(strategy.amend_refusal, Rejected)
    assert isinstance(strategy.transfer_refusal, Rejected)

    refused = result.logs.trades.of(TradeAction.AMEND_REFUSED)
    assert refused, 'the amend refusal is missing from the trade log'
    assert refused[0].rule
    assert 'not on the session event cursor' in refused[0].reason

    kinds = {e.kind.value for e in result.logs.events}
    assert 'amended' not in kinds


def test_a_rejection_row_carries_the_rule_and_the_constraint_that_bound():
    """A rejection log keyed on prose cannot be counted."""

    class SellWhatIsNotSettled(BaseStrategy):
        name = 'sell-unsettled'

        def on_session(self, ctx):
            if ctx.today == D1:
                ctx.buy('FPT', 1000, limit_price=Decimal('95.5'))
            elif ctx.today == D2:
                ctx.sell('FPT', 1000, limit_price=Decimal('95.5'))

    result = run_scenario(stub_scenario(SellWhatIsNotSettled(), days=DAYS[:3]))
    rejected = result.logs.trades.of(TradeAction.REJECTED)
    assert [e.rule for e in rejected] == ['unsettled_holding']
    assert rejected[0].verdict == 'rejected'
    assert rejected[0].binding_constraint == 0
    assert rejected[0].sellable_from is not None

    refusals = result.logs.settlement.refusals
    assert len(refusals) == 1
    assert refusals[0].sellable_from == rejected[0].sellable_from
    assert refusals[0].settlement_rule
    assert refusals[0].settlement_calendar_id


def test_a_submission_is_logged_even_when_it_is_refused():
    """The session mints an order id for a rejection, so the two rows join."""

    class Impossible(BaseStrategy):
        name = 'impossible'

        def on_session(self, ctx):
            if ctx.today == D1:
                ctx.buy('FPT', 1, limit_price=Decimal('95.5'))  # odd lot

    result = run_scenario(stub_scenario(Impossible(), days=DAYS[:2]))
    actions = [e.action for e in result.logs.trades]
    assert TradeAction.SUBMITTED in actions
    assert TradeAction.REJECTED in actions
    rejected = result.logs.trades.of(TradeAction.REJECTED)[0]
    assert rejected.rule == 'round_lot'
    assert rejected.order_id is not None


def test_a_strategy_note_is_carried_into_the_result():
    class Noting(BaseStrategy):
        name = 'noting'

        def on_session(self, ctx):
            if ctx.today == D1:
                ctx.note('deliberately breaching', lots=3)

    result = run_scenario(stub_scenario(Noting(), days=DAYS[:2]))
    assert [a.text for a in result.annotations] == ['deliberately breaching']
    assert result.annotations[0].detail == {'lots': 3}


def test_the_context_reports_which_step_it_is_on():
    seen = []

    class Watcher(BaseStrategy):
        name = 'watcher'

        def on_events(self, ctx, events):
            seen.append(ctx.phase)

    run_scenario(stub_scenario(Watcher(), days=DAYS[:2]))
    assert seen[:4] == [StepPhase.OPEN, StepPhase.CLOSE,
                        StepPhase.OPEN, StepPhase.CLOSE]


def test_the_sale_advance_is_reachable_only_by_reaching_past_the_session():
    """**A finding, pinned.** ``ExchangeSession`` exposes no sale advance.

    *Ung truoc tien ban* is implemented in full in ``ledgers.py`` -- the cap,
    the day-count, the accrual, the recovery out of the T+2 settlement -- and
    there is no session method that reaches it. A strategy connected through
    the session API alone cannot draw one, so sell-then-rebuy on the same day
    is impossible even at a broker that offers the product.

    The context supplies it and says so. If the session ever grows a
    ``request_advance``, the first assertion here fails.
    """
    scenario = stub_scenario(BaseStrategy(), days=DAYS[:2])
    assert not hasattr(scenario.session, 'request_advance')
    assert not hasattr(scenario.session, 'advanceable')

    class SellThenRebuy(BaseStrategy):
        name = 'sell-then-rebuy'

        def __init__(self):
            self.headroom = None
            self.advanced = None
            self.rebuy = None

        def on_session(self, ctx):
            if ctx.today == D1:
                ctx.sell('FPT', 1000, limit_price=Decimal('95.5'))
            elif ctx.today == D2:
                self.headroom = ctx.advanceable()
                self.advanced = ctx.cash().advanced
                # 900, not 1000: the advance is net of the charges withheld
                # on the sale, so the round trip does not buy back the same
                # quantity. A 1000-share rebuy is Rejected(INSUFFICIENT_CASH)
                # by 121,285 dong, which is the sale's own charges.
                self.rebuy = ctx.buy('FPT', 900, limit_price=Decimal('95.5'))

    strategy = SellThenRebuy()
    scenario = stub_scenario(
        strategy, days=DAYS[:4], initial_cash='0',
        opening_holdings={'FPT': 1000},
        broker_profile={'name': 'advance-offering',
                        'advance_sale_proceeds': {'enabled': True,
                                                  'daily_rate': '0.00031'}})
    result = run_scenario(scenario)
    assert result.error is None

    # `AdvanceTerms.auto_register` defaults to True, so the whole tranche is
    # advanced inside `credit_pending` the instant the sale fills, through a
    # private path. Nothing is left to draw, and a journal that only wrapped
    # the public `request_advance` would record no draw at all.
    assert strategy.advanced > 0
    assert strategy.headroom == 0
    assert not isinstance(strategy.rebuy, Rejected), (
        'the rebuy is funded out of the advance, which is the whole point of '
        'the product: without it sell-then-rebuy the same day is impossible')

    from validation.logs import CashMovement
    drawn = [e for e in result.logs.cash
             if e.movement is CashMovement.ADVANCE_DRAWN]
    assert len(drawn) == 1
    assert drawn[0].affects_balance is False, (
        'an advance raises Cash.available through `advanced`, not the '
        'settled balance')

    interest = [e for e in result.logs.cash
                if e.movement is CashMovement.ADVANCE_INTEREST_ACCRUED]
    assert interest, 'the advance accrued no interest at all'
    assert all(e.affects_balance is False for e in interest), (
        'FEATURES.md records that advance interest is reported and never '
        'charged; if a code path now debits it, this assertion is the one '
        'that should change')

    repaid = [e for e in result.logs.cash
              if e.movement is CashMovement.ADVANCE_REPAID]
    assert len(repaid) == 1
    assert repaid[0].detail['interest_accrued'] > 0
    assert not result.failed_identities
