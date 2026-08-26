"""EQUITY MARGIN LENDING -- the scenario's assertions.

Three populations, kept apart on purpose:

1. **Statutory refusals**, no data at all. ``BrokerMarginTerms`` refuses a term
   looser than a QD 87 floor at construction, and each floor gets its own test
   so a regression names the clause it broke.
2. **Wiring regressions**, on a hand-written market. Two of these are the bugs
   this work found and fixed, and both were silent: the currency unit and the
   board lot. Each fails loudly without its fix.
3. **The real window**, gated on the corpus. ``HPG`` 2022-09-23 -> 2022-11-04,
   the arms in ``validation/scenarios/equity-margin.py``. Every date and every
   number asserted here was read off the run, not chosen for it.

The scenario module is loaded by path because its filename carries a hyphen and
is not an importable module name.
"""

import importlib.util
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import (DAYS, EQUITY_ROWS, KINDS, StubSource, market,
                      requires_corpus, stub_scenario)

from plutus.market.protocol import Order, OrderType, Side
from plutus.market.session.calendar import VsdcSettlementCalendar
from plutus.market.session.equity_margin import (
    CURRENCY_UNIT, EquityMarginAccount, WIRING_PROVENANCE,
)
from plutus.market.session.margin_lending import (
    AccountingUnit, BrokerMarginTerms, BrokerTermLooserThanLaw, CureMethod,
    DayCount, ForcedSalePrice, ForcedSaleScope, ForcedSaleTrigger,
    InterestTier, LiquidationOrder, MarginAccountStatus, MarginCallStatus,
    MarginEligibility, MarginEventKind, PolicyBound, ProceedsComponent,
    SecurityEligibility, binding_policy,
)
from plutus.market.session.types import Pool, StatefulRule, Venue, Verdict
from plutus.market.verdicts import AdmissionRule

from validation import BaseStrategy, StepPhase, run_scenario
from validation.logs import CashMovement, TradeAction

_SCENARIO_PATH = (Path(__file__).resolve().parents[2]
                  / 'validation' / 'scenarios' / 'equity-margin.py')


def _load_scenario():
    """Load ``validation/scenarios/equity-margin.py`` by path.

    The filename carries a hyphen, so it is not an importable module name.
    It is registered in ``sys.modules`` **before** execution because
    ``@dataclass`` resolves ``cls.__module__`` through ``sys.modules`` and
    raises ``AttributeError`` on a module that is not there yet.
    """
    name = 'validation_scenarios_equity_margin'
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCENARIO_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sc = _load_scenario()


# ==========================================================================
# 1. The statutory floors. A broker term may be stricter and never looser.
# ==========================================================================

def _terms(**overrides):
    return sc.broker_terms(**overrides)


def test_a_call_level_under_the_statutory_floor_is_refused():
    """QD 87 Dieu 5.2: *ty le ky quy duy tri ... khong duoc thap hon 30%*."""
    with pytest.raises(BrokerTermLooserThanLaw) as exc:
        _terms(maintenance=Decimal('0.29'))
    assert 'maintenance_margin_ratio' in str(exc.value)
    assert '0.30' in str(exc.value)


def test_a_force_sell_level_under_the_statutory_floor_is_refused():
    with pytest.raises(BrokerTermLooserThanLaw) as exc:
        _terms(liquidation=Decimal('0.25'))
    assert 'liquidation_margin_ratio' in str(exc.value)


def test_an_initial_margin_ratio_under_fifty_percent_is_refused():
    """QD 87 Dieu 5.1: *khong duoc thap hon 50%*."""
    with pytest.raises(BrokerTermLooserThanLaw) as exc:
        _terms(initial_margin_ratio=Decimal('0.45'))
    assert 'initial_margin_ratio' in str(exc.value)


def test_a_cure_window_longer_than_three_business_days_is_refused():
    """QD 87 Dieu 7.1 alone carries the ceiling; TT 120 Dieu 9.6 has no count."""
    with pytest.raises(BrokerTermLooserThanLaw) as exc:
        _terms(cure_business_days=4)
    assert 'cure_business_days' in str(exc.value)


def test_a_consecutive_breach_term_beyond_the_cure_ceiling_is_refused():
    """The refusal that makes ``CURE_WINDOW_EXPIRED`` hard to reach.

    A firm cannot wait more consecutive breach days than the cure ceiling
    allows, so the consecutive clock is capped at 3 -- and because the breach
    counter increments on the observation that *issues* the call, three
    breaches arrive one session before three business days elapse. See
    ``run_cure_window_arm``'s docstring for the one lawful configuration that
    reaches the statutory trigger.
    """
    with pytest.raises(BrokerTermLooserThanLaw) as exc:
        _terms(consecutive_breach_days=10)
    assert 'consecutive_breach_days_before_sale' in str(exc.value)


def test_valuing_collateral_above_the_last_close_cannot_be_turned_off():
    """QD 87 Dieu 2.4's ceiling is not a broker option."""
    with pytest.raises(BrokerTermLooserThanLaw):
        _terms(collateral_valuation_cap_enforced=False)


def test_ineligible_securities_cannot_be_counted_as_collateral():
    """TT 120 Dieu 9.6 excludes them from the base for BOTH ratios."""
    with pytest.raises(BrokerTermLooserThanLaw):
        _terms(ineligible_counted_as_collateral=True)


def test_a_stricter_broker_term_is_accepted_and_binds():
    """Stricter is always allowed, and ``BindingPolicy`` says who set it."""
    terms = _terms(maintenance=Decimal('0.45'))
    policy = binding_policy(terms)
    assert policy.call_level == Decimal('0.45')
    assert policy.call_level_bound_by is PolicyBound.BROKER
    assert policy.force_sell_level == Decimal('0.30')
    assert policy.force_sell_level_bound_by is PolicyBound.BOTH


def test_the_scenario_declares_every_unsourced_term():
    """Overclaiming is a defect: each commercial default names its grade."""
    for field in ('maintenance_margin_ratio', 'liquidation_margin_ratio',
                  'forced_sale_price', 'liquidation_order',
                  'proceeds_application_order', 'rate_schedule', 'day_count',
                  'security_eligibility', 'settlement_calendar'):
        assert field in sc.TERMS_PROVENANCE
    assert 'UNSOURCED' in sc.TERMS_PROVENANCE['maintenance_margin_ratio']
    assert 'SILENT' in sc.TERMS_PROVENANCE['forced_sale_price']


# ==========================================================================
# 2. Wiring regressions, on a hand-written market
# ==========================================================================

_TICKER = 'FPT'
_PRICE = Decimal('95.5')                      # thousands of dong, as HSX quotes


def _stub_terms(**overrides):
    settings = dict(
        maintenance_margin_ratio=Decimal('0.40'),
        liquidation_margin_ratio=Decimal('0.30'),
        forced_sale_price=ForcedSalePrice.FLOOR,
        day_count=DayCount.ACT_365,
        liquidation_order=LiquidationOrder.LARGEST_POSITION_FIRST,
        proceeds_application_order=(ProceedsComponent.PRINCIPAL,
                                    ProceedsComponent.INTEREST,
                                    ProceedsComponent.FEES,
                                    ProceedsComponent.TAXES),
    )
    settings.update(overrides)
    return BrokerMarginTerms(**settings)


def _stub_calendar():
    return VsdcSettlementCalendar(frozenset(), (date(2024, 5, 1),
                                               date(2024, 7, 31)),
                                  'weekday-test')


def _stub_account(source, terms=None, **overrides):
    settings = dict(
        account_id='STUB', terms=terms or _stub_terms(),
        calendar=_stub_calendar(), market_feed=source.state_at,
        eligibility={_TICKER: SecurityEligibility(
            ticker=_TICKER, as_of=DAYS[0],
            result=MarginEligibility.ELIGIBLE, venue=Venue.HSX,
            on_broker_list=True)},
        tickers=(_TICKER,))
    settings.update(overrides)
    return EquityMarginAccount(**settings)


class _BuyOnce(BaseStrategy):
    name = 'buy-once'

    def __init__(self, quantity=1000, on_margin=True, day=DAYS[0]):
        self.quantity = quantity
        self.on_margin = on_margin
        self.day = day
        self.outcome = None

    def on_session(self, ctx):
        if self.outcome is not None or ctx.phase is not StepPhase.OPEN:
            return
        if ctx.today != self.day:
            return
        self.outcome = ctx.submit(Order(
            ticker=_TICKER, side=Side.BUY, quantity=self.quantity,
            order_type=OrderType.LIMIT, limit_price=_PRICE,
            on_margin=self.on_margin))


def _stub_run(strategy, *, account=None, source=None, **build):
    source = source or StubSource(dict(EQUITY_ROWS), KINDS)
    scenario = stub_scenario(strategy, source=source, venues=('HSX',),
                             initial_cash='200000000', **build)
    account = account or _stub_account(source)
    scenario.session.attach_equity_margin(account)
    return run_scenario(scenario, raise_on_error=True), account, scenario


def test_pv_is_in_dong_not_in_the_quoted_thousands():
    """The silent bug. HSX quotes thousands of dong; the ledger holds dong.

    1,000 FPT at 95.5 is **95,500,000 dong**, not 95,500. Passing the quote
    straight through to ``margin_lending`` -- which labels no price with a unit
    -- would make ``PV`` a thousandth of ``CB``, put the ratio near 1.0 on a
    fully margined account and fire no call at any price. Nothing raises;
    ``CollateralLot`` accepts any positive Decimal.
    """
    result, account, _ = _stub_run(_BuyOnce())
    algebra = account.determinations[0]
    assert algebra.pv == Decimal('95500000')
    assert algebra.db == Decimal('47750000')
    # 1000 x 95.5 x 1000 x (1 - 0.50); the loan is exactly half the order.
    assert account.margin_debt == Decimal('47750000')


def test_the_loan_is_exactly_the_order_value_less_the_initial_margin():
    """QD 87 Dieu 2 khoan 8 and Dieu 13.5(d), in one number."""
    result, account, _ = _stub_run(_BuyOnce())
    draw = account.draws[0]
    assert draw.imr == Decimal('0.50')
    assert draw.disbursed == Decimal('95500000') * Decimal('0.50')
    credits = [e for e in result.logs.cash
               if e.movement is CashMovement.OTHER_CREDIT
               and 'margin loan' in e.cause]
    assert len(credits) == 1
    assert credits[0].amount == draw.disbursed


def test_a_margin_order_needs_a_margin_account_on_the_session():
    """An unhonoured ``on_margin`` flag would silently unlever the strategy."""
    source = StubSource(dict(EQUITY_ROWS), KINDS)
    scenario = stub_scenario(_BuyOnce(), source=source, venues=('HSX',),
                             initial_cash='200000000')
    run_scenario(scenario, raise_on_error=True)
    refusals = [e for e in scenario.session.orders() if e.rejection is not None]
    assert refusals, 'the on_margin order should have been refused'
    assert refusals[0].rejection.rule is StatefulRule.MARGIN_LENDING


def test_a_margin_sell_is_refused():
    """*Giao dich ky quy* is a purchase on credit; a SELL carries no lending."""
    source = StubSource(dict(EQUITY_ROWS), KINDS)

    class _SellOnMargin(BaseStrategy):
        name = 'sell-on-margin'
        outcome = None

        def on_session(self, ctx):
            if self.outcome is None and ctx.phase is StepPhase.OPEN:
                self.outcome = ctx.submit(Order(
                    ticker=_TICKER, side=Side.SELL, quantity=100,
                    order_type=OrderType.LIMIT, limit_price=_PRICE,
                    on_margin=True))

    strategy = _SellOnMargin()
    _stub_run(strategy, source=source, opening_holdings={_TICKER: 1000})
    assert strategy.outcome.rule is StatefulRule.MARGIN_LENDING
    assert 'purchase on credit' in strategy.outcome.detail['reason']


def test_a_foreign_investor_cannot_margin_trade():
    """TT 120 Dieu 9.2 / QD 87 Dieu 10.1(d): a flat prohibition on *ky quy*.

    The refusal text has to carry the Dieu 9a caveat, or an implementer reads
    it as "foreigners cannot buy on credit", which is wrong.
    """
    source = StubSource(dict(EQUITY_ROWS), KINDS)
    account = _stub_account(source, is_foreign_investor=True)
    strategy = _BuyOnce()
    _stub_run(strategy, account=account, source=source)
    assert strategy.outcome.rule is StatefulRule.MARGIN_LENDING
    assert 'investor_not_eligible' in strategy.outcome.detail['refusals']
    assert 'Dieu 9a' in strategy.outcome.detail['reason']


def test_an_unlisted_security_is_indeterminate_not_eligible():
    """The eligible-security list is dated data the caller supplies.

    With none, ``assess_margin_order`` answers INDETERMINATE and the order is
    refused with ``Verdict.INDETERMINATE`` -- kept countable apart from a rule
    saying no, which is the house rule everywhere else in this package.
    """
    source = StubSource(dict(EQUITY_ROWS), KINDS)
    account = _stub_account(source, eligibility={})
    strategy = _BuyOnce()
    _stub_run(strategy, account=account, source=source)
    assert strategy.outcome.rule is StatefulRule.MARGIN_LENDING
    assert strategy.outcome.verdict is Verdict.INDETERMINATE
    assert 'security_not_eligible' in strategy.outcome.detail['indeterminate']


def test_a_second_margin_account_cannot_be_attached():
    """TT 120 Dieu 9.3: one session is one client at one firm."""
    source = StubSource(dict(EQUITY_ROWS), KINDS)
    scenario = stub_scenario(_BuyOnce(), source=source, venues=('HSX',))
    scenario.session.attach_equity_margin(_stub_account(source))
    with pytest.raises(ValueError, match='already has equity margin account'):
        scenario.session.attach_equity_margin(_stub_account(source))


def test_per_deal_granularity_is_refused_rather_than_mislabelled():
    """DNSE's per-deal ratio is a different engine; running the account-level
    one and calling it per-deal is the failure a provenance record cannot
    catch."""
    source = StubSource(dict(EQUITY_ROWS), KINDS)
    with pytest.raises(ValueError, match='accounting_unit'):
        _stub_account(source,
                      terms=_stub_terms(accounting_unit=AccountingUnit.DEAL))


def test_the_breaching_position_shapes_are_refused():
    """Both members read ``is_breaching``, which per-account wiring cannot set."""
    source = StubSource(dict(EQUITY_ROWS), KINDS)
    with pytest.raises(ValueError, match='BREACHING_POSITION'):
        _stub_account(source, terms=_stub_terms(
            forced_sale_scope=ForcedSaleScope.BREACHING_POSITION))
    with pytest.raises(ValueError, match='BREACHING_FIRST'):
        _stub_account(source, terms=_stub_terms(
            liquidation_order=LiquidationOrder.BREACHING_FIRST))


def test_nothing_accrues_without_an_agreed_rate():
    """QD 87 Dieu 11.3 requires the rate agreed IN WRITING.

    An empty ``rate_schedule`` is the correct model of "no contract", and the
    engine must refuse to accrue rather than invent a number.
    """
    source = StubSource(dict(EQUITY_ROWS), KINDS)
    account = _stub_account(source)            # no rate_schedule
    _stub_run(_BuyOnce(), account=account, source=source)
    assert account.accrued_interest == Decimal('0')
    assert not account.events_by_kind(MarginEventKind.INTEREST_ACCRUED)


def test_interest_accrues_into_db_and_never_into_cash():
    """Accrual lowers ``AB`` through ``accrued_charges_in_debt`` and moves no
    money -- so it can fire a call that no cash movement explains."""
    source = StubSource(dict(EQUITY_ROWS), KINDS)
    account = _stub_account(source, terms=_stub_terms(
        rate_schedule=(InterestTier(0, None, Decimal('0.135')),)))
    result, account, _ = _stub_run(_BuyOnce(), account=account, source=source)
    assert account.accrued_interest > Decimal('0')
    last = account.determinations[-1]
    assert last.db == account.margin_debt + account.accrued_interest
    assert not [e for e in result.logs.cash if 'interest' in e.cause.lower()
                and 'advance' not in e.cause.lower()]


class _BuyTwice(BaseStrategy):
    """Two margin buys in one session, each individually affordable."""

    name = 'buy-twice'

    def __init__(self, quantity=1000):
        self.quantity = quantity
        self.outcomes = []

    def on_session(self, ctx):
        if self.outcomes or ctx.phase is not StepPhase.OPEN:
            return
        for _ in range(2):
            self.outcomes.append(ctx.submit(Order(
                ticker=_TICKER, side=Side.BUY, quantity=self.quantity,
                order_type=OrderType.LIMIT, limit_price=_PRICE,
                on_margin=True)))


def test_two_margin_orders_in_one_session_cannot_spend_the_same_buying_power():
    """``assess_margin_order`` is a pure function of a snapshot and encumbers
    nothing -- its own docstring warns that gating two orders against one state
    admits both if either fits. The gate nets cash committed to live buy
    orders, so the second is refused on **buying power**, which is the rule
    that actually bound, and not on ``INSUFFICIENT_CASH``."""
    source = StubSource(dict(EQUITY_ROWS), KINDS)
    strategy = _BuyTwice(quantity=2000)          # 191 m each, 200 m of cash
    _stub_run(strategy, source=source)
    first, second = strategy.outcomes
    assert not hasattr(first, 'rule')            # Accepted
    assert second.rule is StatefulRule.MARGIN_LENDING
    assert 'buying_power_exceeded' in second.detail['refusals']


def test_no_new_lending_while_the_account_is_in_breach():
    """QD 87 Dieu 10.1(d). The refusal is independent of whether a call issued.

    The stub market falls 95.5 -> 60.0 over the window, which takes an account
    entered at imr 0.50 through the 0.40 call level.
    """
    falling = {}
    prices = [Decimal('95.5'), Decimal('95.5'), Decimal('80.0'),
              Decimal('70.0'), Decimal('62.0'), Decimal('60.0'),
              Decimal('60.0'), Decimal('60.0')]
    for day, price in zip(DAYS, prices):
        falling[(_TICKER, day)] = market(_TICKER, day, price)
    source = StubSource(falling, KINDS)
    account = _stub_account(source)

    class _BuyThenBuyAgain(BaseStrategy):
        name = 'buy-then-buy-again'

        def __init__(self):
            self.first = None
            self.second = None

        def on_session(self, ctx):
            if ctx.phase is not StepPhase.OPEN:
                return
            if self.first is None:
                # 4,000 x 95.5 x 1,000 = 382 m against 200 m of cash: the
                # largest position imr 0.50 admits, so the ratio starts on the
                # floor and the drawdown has somewhere to take it.
                self.first = ctx.submit(Order(
                    ticker=_TICKER, side=Side.BUY, quantity=4000,
                    order_type=OrderType.LIMIT, limit_price=_PRICE,
                    on_margin=True))
            elif self.second is None and ctx.today == DAYS[5]:
                self.second = ctx.submit(Order(
                    ticker=_TICKER, side=Side.BUY, quantity=100,
                    order_type=OrderType.LIMIT, limit_price=Decimal('60.0'),
                    on_margin=True))

    strategy = _BuyThenBuyAgain()
    _stub_run(strategy, account=account, source=source)
    assert account.last_status in (MarginAccountStatus.CALL,
                                   MarginAccountStatus.FORCE_SELL)
    assert strategy.second.rule is StatefulRule.MARGIN_LENDING
    assert 'account_in_breach' in strategy.second.detail['refusals']
    assert 'Dieu 10.1(d)' in strategy.second.detail['reason']


def test_a_loop_that_never_reaches_the_determination_instant_says_so():
    """The one way this wiring can be silently inert.

    The determination runs at the first advance at or after
    ``determination_time``. A loop whose close step lands before it lends,
    never grades, never calls and never sells -- with nothing raised. That
    silence has to be reportable, or a scenario configured slightly wrong
    reports a clean run.
    """
    source = StubSource(dict(EQUITY_ROWS), KINDS)
    account = _stub_account(source, determination_time=time(15, 30))
    result, account, _ = _stub_run(_BuyOnce(), account=account, source=source)
    assert account.determinations == ()
    assert account.missed_determinations == tuple(DAYS)
    assert account.margin_debt > Decimal('0')      # it lent anyway
    assert not result.failed_identities            # and every identity held


def test_the_currency_unit_table_matches_the_charges_module():
    """One conversion, not two. A second table is how the 1,000 comes back."""
    from plutus.core.constant import VietnamMarketConstant
    assert {k: int(v) for k, v in CURRENCY_UNIT.items()} == dict(
        VietnamMarketConstant.CURRENCY_UNIT)


def test_every_wiring_choice_is_declared():
    for key in ('margin_order_flag', 'determination_instant',
                'sale_next_session', 'proceeds_applied_on_settlement',
                'no_double_sale', 'interest_accrual_cadence',
                'accrual_is_not_cash', 'session_event_mapping',
                'loan_sized_on_reserve_price'):
        assert key in WIRING_PROVENANCE
        assert WIRING_PROVENANCE[key].note


# ==========================================================================
# 3. The real window
# ==========================================================================

@pytest.fixture(scope='module')
def hold():
    return sc.run_hold_arm()


@pytest.fixture(scope='module')
def cure():
    return sc.run_cure_arm()


@pytest.fixture(scope='module')
def cure_window():
    return sc.run_cure_window_arm()


@pytest.fixture(scope='module')
def hard():
    return sc.run_hard_policy_arm()


@requires_corpus
def test_the_window_is_the_one_the_scenario_claims(hold):
    """31 HSX sessions, HPG 23.00 -> 14.15."""
    assert hold.result.sessions_run == 31
    assert hold.result.window.sessions[0] == date(2022, 9, 23)
    assert hold.result.window.sessions[-1] == date(2022, 11, 4)
    assert len(hold.account.determinations) == 31


@requires_corpus
def test_the_opening_purchase_is_funded_half_by_the_broker(hold):
    """imr 0.50 on 8,000 HPG at 23.00: 184 m dong, 92 m of it borrowed."""
    draw = hold.account.draws[0]
    assert draw.disbursed == Decimal('92000000')
    assert draw.reserve_price == Decimal('23000')      # dong, not 23.00
    entry = hold.account.determinations[0]
    assert entry.pv == Decimal('181600000')
    assert entry.db == Decimal('92000000')
    assert Decimal('0.51') < entry.margin_ratio < Decimal('0.52')


@requires_corpus
def test_the_call_fires_on_the_session_the_ratio_crosses_the_level(hold):
    """2022-10-06: AB/EB = 0.3916, below the 0.40 call level. Not 10-05 (0.4280),
    not 10-07 -- the rung is crossed once and the call issues once."""
    assert hold.status_on(date(2022, 10, 5)) == 'ok'
    assert hold.status_on(date(2022, 10, 6)) == 'call'
    issued = hold.dates_of(MarginEventKind.CALL_ISSUED)
    assert date(2022, 10, 6) in issued
    assert date(2022, 10, 7) not in issued          # state, not an event


@requires_corpus
def test_the_cure_deadline_is_three_business_days_on_a_real_calendar(hold):
    """QD 87 Dieu 7.1. 2022-10-06 Thu + 3 trading days = 2022-10-11 Tue."""
    call = [c for c in hold.account.calls()
            if c.issued_at.date() == date(2022, 10, 6)][0]
    assert call.deadline == datetime(2022, 10, 11, 14, 45)
    assert call.target_ratio == Decimal('0.40')
    assert call.top_up_cash > 0                    # DERIVED, and non-trivial


@requires_corpus
def test_a_call_is_cured_by_the_market_with_no_payment(hold):
    """2022-10-10: HPG rebounds, AB/EB = 0.4018, and the call closes.

    The client paid nothing. A model with a single threshold and no cure test
    either liquidates here or never closes the call; both are wrong.
    """
    assert hold.ratio_on(date(2022, 10, 10)) > Decimal('0.40')
    cured = hold.dates_of(MarginEventKind.CALL_CURED)
    assert date(2022, 10, 10) in cured
    assert not [e for e in hold.result.logs.cash
                if e.ts.date() == date(2022, 10, 10)]
    first = [c for c in hold.account.calls()
             if c.issued_at.date() == date(2022, 10, 6)][0]
    assert first.status is MarginCallStatus.CURED


@requires_corpus
def test_the_forced_sale_fires_on_the_third_consecutive_breach(hold):
    """SSI's rule, at the statutory ceiling: 10-20, 10-21, 10-24."""
    for day in (date(2022, 10, 20), date(2022, 10, 21), date(2022, 10, 24)):
        assert hold.status_on(day) == 'call'
    due = [e for e in hold.events_of(MarginEventKind.FORCED_SALE_DUE)
           if not e.detail.get('suppressed')]
    assert due[0].ts.date() == date(2022, 10, 24)
    assert due[0].detail['trigger'] is (
        ForcedSaleTrigger.CONSECUTIVE_BREACH_DAYS)


@requires_corpus
def test_the_ban_giai_chap_is_placed_next_session_at_the_floor(hold):
    """The ratio is determined after the close of T; the earliest session the
    ticket can reach is T+1, and DNSE's published policy is *gia san*."""
    fills = [e for e in hold.result.logs.trades.of(TradeAction.FILLED)
             if e.side == 'SELL']
    assert fills[0].ts.date() == date(2022, 10, 25)
    assert fills[0].fill_price == Decimal('15.3')   # HPG's floor that session
    assert fills[0].fill_quantity == 1500


@requires_corpus
def test_every_forced_sale_ticket_is_a_whole_board_lot(hold, cure,
                                                       cure_window):
    """The second silent bug. ``plan_forced_sale`` sizes in whole shares and
    says the lot belongs to the order layer; without the rounding every ticket
    -- 1,459, 913, 1,070, 1,633, 1,762 shares -- was ``Rejected(ROUND_LOT)``
    and the account went on breaching while the log said a sale had been
    instructed."""
    for run in (hold, cure, cure_window):
        submitted = [e for e in run.events_of(
            MarginEventKind.FORCED_SALE_INSTRUCTED)
            if e.detail.get('accepted')]
        assert submitted
        for event in submitted:
            assert event.detail['quantity'] % sc.LOT_SIZE == 0
            assert event.detail['quantity'] >= event.detail['planned_quantity']


@requires_corpus
def test_the_sale_barely_moves_the_ratio_until_the_proceeds_settle(hold):
    """**The T+2 finding.** Selling collateral moves value from ``PV`` to
    ``CB`` and leaves ``EB``, ``AB`` and the ratio where they were. On a T+2
    market the liquidated account stays in breach for two more sessions."""
    before = hold.ratio_on(date(2022, 10, 24))     # 0.3313, sale decided
    after = hold.ratio_on(date(2022, 10, 25))      # 0.3445, 1,500 sold
    assert abs(after - before) < Decimal('0.02')
    assert hold.status_on(date(2022, 10, 25)) == 'call'
    assert hold.status_on(date(2022, 10, 26)) == 'call'
    assert hold.status_on(date(2022, 10, 27)) == 'ok'


@requires_corpus
def test_the_debt_falls_by_exactly_the_settled_tranche(hold):
    """QD 87 Dieu 8. The sweep is on settlement day and for the tranche amount,
    net of the charges withheld at source."""
    tranche = [e for e in hold.result.logs.cash
               if e.movement is CashMovement.SETTLEMENT_CREDIT][0]
    assert tranche.ts.date() == date(2022, 10, 27)
    sweep = [e for e in hold.result.logs.cash
             if e.movement is CashMovement.OTHER_DEBIT
             and 'margin debt repaid' in e.cause][0]
    assert sweep.ts.date() == date(2022, 10, 27)
    assert -sweep.amount == tranche.amount

    repaid = [e for e in hold.events_of(MarginEventKind.LOAN_REPAID)
              if e.ts.date() == date(2022, 10, 27)][0]
    assert repaid.detail['applied']['principal'] == tranche.amount

    db_before = [a.db for a in hold.account.determinations
                 if a.as_of.date() == date(2022, 10, 26)][0]
    db_after = [a.db for a in hold.account.determinations
                if a.as_of.date() == date(2022, 10, 27)][0]
    fall = db_before - db_after
    # DB falls by the tranche less one session's interest, and the ORDER of the
    # pass is why. The accrual now runs FIRST, on the principal that was
    # actually outstanding across the day: 92,000,000 x 0.135 / 365 = 34,027.
    #
    # It used to run last, after the sweep, and so charged the day on the
    # already-reduced 69,079,147 -- 25,549 -- forgiving 8,478 of interest for
    # a day on which the full 92 m had been borrowed. Small, but silent,
    # systematic and always in the broker's disfavour. The accrual is a
    # backward-looking quantity and cannot be priced off a balance struck
    # after the period it covers.
    accrued = [e for e in hold.account.events_by_kind(
        MarginEventKind.INTEREST_ACCRUED) if e.ts.date() == date(2022, 10, 27)]
    assert accrued
    assert accrued[0].detail['principal'] == Decimal('92000000')
    assert accrued[0].detail['days'] == 1
    assert accrued[0].detail['amount'] == Decimal('34027')
    assert fall == tranche.amount - accrued[0].detail['amount']


@requires_corpus
def test_the_proceeds_pay_principal_first_and_the_interest_goes_unpaid(hold):
    """The proceeds ORDER is SILENT (Dieu 12.2(i)) and decides which component
    goes unpaid. Here 22.9 m meets a 92 m principal, so the accrued interest
    gets nothing -- and that is the firm's stated order, not a rule."""
    repaid = [e for e in hold.events_of(MarginEventKind.LOAN_REPAID)
              if e.detail.get('applied')][0]
    applied = repaid.detail['applied']
    assert applied['principal'] > Decimal('0')
    assert applied['interest'] == Decimal('0')
    assert repaid.detail['unpaid']['interest'] > Decimal('0')
    assert repaid.detail['fully_discharged'] is False


@requires_corpus
def test_no_second_sale_is_planned_while_one_is_in_flight(hold):
    """UNSOURCED, and declared. Without it the T+2 lag makes the machine sell
    the account three times over for one breach."""
    suppressed = [e for e in hold.events_of(MarginEventKind.FORCED_SALE_DUE)
                  if e.detail.get('suppressed')]
    assert [e.ts.date() for e in suppressed][:2] == [date(2022, 10, 25),
                                                     date(2022, 10, 26)]


@requires_corpus
def test_a_forced_sale_into_a_floor_locked_market_does_not_execute(cure):
    """2022-10-31: HPG opens and closes at its floor, 15.65. The *ban giai
    chap* is placed at the floor, the sell side is locked, and the exchange
    refuses it. The right existed and could not be exercised.

    The evidence is ``bar_proxy`` -- an inference from the daily bar, not an
    observation -- and the event says so rather than claiming a book.
    """
    refused = [e for e in cure.events_of(MarginEventKind.FORCED_SALE_INSTRUCTED)
               if e.detail.get('accepted') is False
               and e.detail.get('refusal')]
    assert refused, 'the corpus should refuse at least one giai chap'
    event = refused[0]
    assert event.ts.date() == date(2022, 10, 31)
    assert event.detail['refusal']['rule'] == AdmissionRule.BAND_LOCK.value
    assert event.detail['refusal']['detail']['lock_evidence'] == 'bar_proxy'

    # And it is in the TRADE LOG, not only in the margin event stream. The
    # refused ``ban giai chap`` is the single most interesting event in this
    # arm and the deliverable log did not mention it at all: it had zero rows
    # of any kind, because ``_translate_events`` skipped REJECTED outright and
    # ``StrategyContext`` never sees a broker-placed order.
    rejected = [r for r in cure.result.logs.trades
                if r.action is TradeAction.REJECTED]
    assert len(rejected) == 1
    assert rejected[0].ts.date() == date(2022, 10, 31)
    assert rejected[0].rule == AdmissionRule.BAND_LOCK.value
    assert rejected[0].order_id is not None, (
        'the refusal must join to an order, not float free in the log')


@requires_corpus
def test_a_cash_cure_closes_the_call_and_shows_in_the_cash_log(cure):
    """QD 87 Dieu 7, the cheapest of the three methods: cash swept against DB."""
    assert cure.strategy.cured
    deposit = [e for e in cure.result.logs.cash
               if 'client cash top-up' in e.cause]
    repay = [e for e in cure.result.logs.cash
             if 'client top-up answering' in e.cause]
    assert len(deposit) == len(repay) == 1
    assert deposit[0].amount == -repay[0].amount == cure.strategy.cure_amount
    contributions = cure.events_of(MarginEventKind.CALL_CURED)
    assert any(e.detail.get('method') is CureMethod.DEPOSIT_CASH
               for e in contributions)


@requires_corpus
def test_a_cash_cure_is_provisional_and_a_new_call_can_issue_the_same_day(cure):
    """``MarginCallMonitor.cure`` says the full cure is measured against the
    DERIVED requirement **at issue**; the authoritative test is the next
    ratio. Here the client pays the 2022-10-06 gap on 2022-10-07, the call
    closes, and the 14:45 determination the same day issues a new one."""
    day = date(2022, 10, 7)
    cured = [e for e in cure.events_of(MarginEventKind.CALL_CURED)
             if e.ts.date() == day]
    issued = [e for e in cure.events_of(MarginEventKind.CALL_ISSUED)
              if e.ts.date() == day]
    assert cured and issued
    assert cured[0].detail.get('provisional') is True
    assert cure.ratio_on(day) < Decimal('0.40')


@requires_corpus
def test_the_statutory_trigger_fires_only_when_the_cure_target_is_above_the_call_level(
        hold, cure_window):
    """``CURE_WINDOW_EXPIRED`` is the only one of the five triggers that comes
    from an article (QD 87 Dieu 8 on Dieu 7.1). With target == call level it is
    unreachable at any lawful firm; with a 0.45 target over a 0.40 call level
    it fires on 2022-10-11."""
    assert ForcedSaleTrigger.CURE_WINDOW_EXPIRED not in [
        e.detail.get('trigger')
        for e in hold.events_of(MarginEventKind.FORCED_SALE_DUE)]

    expired = cure_window.events_of(MarginEventKind.CALL_EXPIRED)
    assert [e.ts.date() for e in expired][0] == date(2022, 10, 11)
    due = [e for e in cure_window.events_of(MarginEventKind.FORCED_SALE_DUE)
           if not e.detail.get('suppressed')][0]
    assert due.ts.date() == date(2022, 10, 11)
    assert due.detail['trigger'] is ForcedSaleTrigger.CURE_WINDOW_EXPIRED
    call = [c for c in cure_window.account.calls()
            if c.issued_at.date() == date(2022, 10, 6)][0]
    assert call.status is MarginCallStatus.ESCALATED


@requires_corpus
def test_the_ratio_that_reset_the_breach_counter_did_not_cure_the_call(
        cure_window):
    """2022-10-10 at 0.4018 is above the 0.40 call level and below the 0.45
    target: not a breach, so the consecutive counter resets, and not a cure,
    so the window keeps running. That gap is the whole mechanism."""
    assert cure_window.status_on(date(2022, 10, 10)) == 'ok'
    assert cure_window.ratio_on(date(2022, 10, 10)) < Decimal('0.45')
    assert date(2022, 10, 10) not in cure_window.dates_of(
        MarginEventKind.CALL_CURED)


@requires_corpus
def test_every_margin_event_reaching_the_cursor_names_the_securities_pool(hold):
    """An equity margin call under the same ``EventKind`` as a futures one is
    indistinguishable unless the pool says which product it is."""
    from plutus.market.session.types import EventKind
    margin = [e for e in hold.result.logs.events
              if e.kind in (EventKind.MARGIN_CALL, EventKind.MARGIN_WARNING,
                            EventKind.FORCED_LIQUIDATION)]
    assert margin
    for event in margin:
        assert event.pool is Pool.SECURITIES
        assert event.detail['equity_margin_event']
        assert event.detail['product'].startswith('equity margin')


@requires_corpus
def test_the_forced_liquidation_event_states_that_it_executed(hold):
    """The derivatives side reports a forced close and does not run one
    (``detail['executed'] is False``). This one does, and says so."""
    from plutus.market.session.types import EventKind
    forced = [e for e in hold.result.logs.events
              if e.kind is EventKind.FORCED_LIQUIDATION]
    assert forced
    assert all(e.detail['executed'] is True for e in forced)
    assert all('selection_rule' in e.detail for e in forced)


def _call_open_on(run):
    """Dates on which a *lenh goi ky quy bo sung* was outstanding.

    Reconstructed from the event stream rather than from the monitor, because
    the monitor keeps only its current state and the question is about every
    session the run passed through.
    """
    open_from = None
    covered = set()
    for event in run.account.events:
        day = event.ts.date()
        if event.kind is MarginEventKind.CALL_ISSUED:
            open_from = day
        elif event.kind in (MarginEventKind.CALL_CURED,
                            MarginEventKind.CALL_EXPIRED,
                            MarginEventKind.FORCED_SALE_INSTRUCTED):
            if open_from is not None:
                covered.add((open_from, day))
                open_from = None
    if open_from is not None:
        covered.add((open_from, run.account.determinations[-1].as_of.date()))
    days = set()
    for start, end in covered:
        for algebra in run.account.determinations:
            if start <= algebra.as_of.date() <= end:
                days.add(algebra.as_of.date())
    return days


@requires_corpus
def test_no_breaching_session_passes_without_a_call_or_a_sale(hold, cure,
                                                              cure_window):
    """**The margin-call-miss check.** The author's question, asked directly.

    For every determination the ladder graded ``call`` or ``force_sell``, the
    account must be under an outstanding call, or a forced sale must be due or
    instructed that session. A breaching session with neither is a miss: the
    client was below the maintenance ratio and nobody told them.
    """
    for run in (hold, cure, cure_window):
        breaching = [a for a in run.account.determinations
                     if a.status in (MarginAccountStatus.CALL,
                                     MarginAccountStatus.FORCE_SELL)]
        # Not vacuous: each arm really does breach, repeatedly.
        assert len(breaching) >= 8, run.result.name
        covered = _call_open_on(run)
        acted = {e.ts.date() for e in run.events_of(
            MarginEventKind.FORCED_SALE_DUE,
            MarginEventKind.FORCED_SALE_INSTRUCTED,
            MarginEventKind.CALL_ISSUED,
            MarginEventKind.CALL_EXPIRED,
            MarginEventKind.CALL_PARTIALLY_CURED)}
        misses = [a.as_of.date() for a in run.account.determinations
                  if a.status in (MarginAccountStatus.CALL,
                                  MarginAccountStatus.FORCE_SELL)
                  and a.as_of.date() not in covered
                  and a.as_of.date() not in acted]
        assert misses == [], f'{run.result.name}: unanswered breaches {misses}'


@requires_corpus
def test_every_session_the_account_lived_through_was_graded(hold, cure,
                                                            cure_window,
                                                            hard):
    """QD 87 Dieu 6.1 is an end-of-**every**-trading-day determination."""
    for run in (hold, cure, cure_window, hard):
        assert run.account.missed_determinations == ()
        graded = [a.as_of.date() for a in run.account.determinations]
        assert graded == list(run.result.window.sessions)


@requires_corpus
def test_the_only_unsettled_leg_at_the_end_is_the_last_sale(hold):
    """Nothing is left half-settled that the window could have finished."""
    outstanding = hold.result.logs.settlement.unsettled_at_end()
    assert len(outstanding) == 1
    entry = outstanding[0]
    assert entry.ts.date() == date(2022, 11, 3)
    assert entry.settles_at.date() > hold.result.window.sessions[-1]
    assert entry.settled_at is None


@requires_corpus
def test_the_ledger_and_the_loan_book_agree_at_every_determination(hold):
    """``DB`` is the loan book, not a running total the wiring keeps its own
    copy of. The two would drift silently: nothing in the algebra checks the
    loans behind the number it is handed."""
    for algebra in hold.account.determinations:
        assert algebra.db == algebra.margin_debt
    principal = sum((l.principal for l in hold.account.loans), Decimal('0'))
    assert principal == hold.account.margin_debt
    last = hold.account.determinations[-1]
    assert last.db == principal + hold.account.accrued_interest


@requires_corpus
def test_cash_is_conserved_across_the_lending(hold, cure, cure_window):
    """Every dong: the loan in, the purchase out, the charges, the proceeds,
    the sweep. The one identity that would catch a disbursement with no
    matching debt."""
    for run in (hold, cure, cure_window):
        failed = {r.name for r in run.result.failed_identities}
        assert 'cash_conservation[securities]' not in failed
        assert 'holdings_conservation' not in failed
        assert 'encumbrance_zero' not in failed


@requires_corpus
def test_every_order_reaches_a_terminal_state(hold, cure, cure_window):
    """Checked on the session's own book, not on the trade log -- the next test
    is why the trade log cannot answer this for a broker-initiated order.

    Every *ban giai chap* the account believes it placed must be an order the
    session knows about, and every one of those must be terminal by the end of
    the run: nothing left resting, nothing holding a reservation.
    """
    for run in (hold, cure, cure_window):
        ids = set(run.account.forced_sale_orders)
        assert ids
        instructed = {e.detail['order_id'] for e in run.events_of(
            MarginEventKind.FORCED_SALE_INSTRUCTED)
            if e.detail.get('accepted')}
        assert instructed == ids
        book = {r.order_id: r for r in run.session.orders()}
        for order_id in ids:
            assert order_id in book
            assert book[order_id].is_terminal
        assert not [r for r in run.session.orders() if not r.is_terminal]


@requires_corpus
def test_a_broker_initiated_order_reaches_the_trade_log(hold):
    """**D52, closed.** This test used to assert the defect.

    ``_translate_events`` skipped ``ACCEPTED`` and ``REJECTED`` outright,
    because ``StrategyContext`` writes them from ``submit()``'s return value.
    That holds for every order a *strategy* places and fails for every order
    the *session* places -- and a ``ban giai chap`` is the first of those in
    this simulator. The fill rows joined to no ACCEPTED row, so
    ``order_lifecycle`` reported broken on every equity-margin arm, and a
    forced sale the exchange *refused* had no row at all: not accepted, not
    rejected, not filled. The most interesting event in the run was invisible
    in the deliverable log.

    The skip is now conditional on the log already holding that order's row,
    so the strategy's orders are still logged exactly once and the broker's
    are logged at all.
    """
    assert hold.result.failed_identities == ()

    forced = set(hold.account.forced_sale_orders)
    assert forced, 'the arm must actually force a sale for this to mean anything'
    rows = hold.result.logs.trades
    for order_id in forced:
        actions = {r.action for r in rows.for_order(order_id)}
        assert TradeAction.ACCEPTED in actions, (
            f'{order_id} is a broker-placed order with no ACCEPTED row')
        assert actions & {TradeAction.FILLED, TradeAction.PARTIALLY_FILLED,
                          TradeAction.REJECTED, TradeAction.CANCELLED,
                          TradeAction.EXPIRED}

    # Exactly once: the strategy's own orders must not be doubled.
    for order_id in rows.order_ids:
        accepted = [r for r in rows.for_order(order_id)
                    if r.action is TradeAction.ACCEPTED]
        assert len(accepted) <= 1, f'{order_id} logged ACCEPTED twice'


@requires_corpus
def test_hard_fills_make_the_whole_scenario_vacuous_and_still_green(hard):
    """The control that must NOT be read as a pass.

    The Parquet corpus carries no high, no low and no volume, so ``hard``
    cannot compute a participation cap and answers INDETERMINATE on the one
    evaluation it makes. Nothing fills, the loan is unwound at the order's
    expiry, the account holds its opening cash for 31 sessions at a ratio of
    exactly 1 -- and **all nine identities hold**. A green run that exercised
    nothing.
    """
    assert hard.result.indeterminate.rate == Decimal('1')
    assert not hard.result.logs.trades.of(TradeAction.FILLED)
    assert not hard.result.failed_identities
    assert hard.account.margin_debt == Decimal('0')
    assert all(a.margin_ratio == Decimal('1')
               for a in hard.account.determinations[1:])
    assert not hard.account.events_by_kind(MarginEventKind.CALL_ISSUED)


@requires_corpus
def test_the_unwound_loan_is_repaid_in_full_when_the_order_never_fills(hard):
    """A draw against an order that executed nothing leaves no debt behind."""
    draw = hard.account.draws[0]
    assert draw.disbursed == Decimal('92000000')
    assert draw.principal == Decimal('0')
    assert draw.reconciled
    debits = [e for e in hard.result.logs.cash
              if e.movement is CashMovement.OTHER_DEBIT]
    assert len(debits) == 1
    assert -debits[0].amount == Decimal('92000000')


@requires_corpus
def test_the_settlement_calendar_says_it_is_not_a_vsdc_notice(hold):
    """No calendar data ships with the repo. A run resting on trading days
    derived from the corpus has to say so."""
    assert hold.result.provenance.settlement_calendar_id == 'corpus-trading-days'
    assert 'NOT from a VSDC notice' in sc.TERMS_PROVENANCE[
        'settlement_calendar']
