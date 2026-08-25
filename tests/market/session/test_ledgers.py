"""Encumbrance, tranche holdings and tranche cash -- locked shapes 2 and 3.

Every test names the rule it pins. The one that matters most is section 12
invariant 4: the sum of encumbrance over live orders equals the ledgers'
committed totals, and committed returns to exactly zero when no order is live.
That single assertion catches the whole leak class -- a terminal edge that
forgets to release, a partial fill that releases the wrong slice, a rejection
that reserved before it refused.

The tests use a minimal stand-in for ``RuleSet``, because ``rulebook.py`` is
authored in parallel and ``ledgers.py`` asks exactly one thing of it:
``charges(venue, cls_) -> Tuple[ChargeRule, ...]``. The two charge rows it
serves are the ones the rulebook says are load-bearing: the 0.1% sell-side
personal income tax withheld at source (rulebook 12.3), and a flat broker
commission (rulebook 12.7).
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.core.order import OrderType, Side
from plutus.market.broker import BrokerTerms
from plutus.market.protocol import BandSource, MarketState, Order
from plutus.market.session.ledgers import (ANNUALISATION_BASIS_360,
                                           ANNUALISATION_BASIS_365,
                                           DECLARED_ANNUALISATION_BASIS,
                                           AdvanceTerms, CashLedger,
                                           EncumbranceLedger, HoldingsLedger,
                                           SaleAdvance, SecuritiesAccount,
                                           assess_charges, estimate_charges,
                                           trade_value)
from plutus.market.session.types import (AccountRef, BrokerProfile, Charge,
                                         ChargeBase, ChargeClass, ChargeRule,
                                         ChargeSide, Confidence, DebitedAt,
                                         Fill, FillEvidence, FillId, LeviedBy,
                                         Encumbrance, OrderId, Pool,
                                         Rejected, ResourceKind, RuleCitation,
                                         StatefulRule, Venue)
from plutus.market.verdicts import AdmissionRule, Verdict

# --------------------------------------------------------------------------
# Fixtures: a rulebook stand-in, a broker, an account
# --------------------------------------------------------------------------

#: Rulebook 12.3: 0.1% of gross sale notional, sell side only, withheld at
#: source by the broker, in force since 2015-01-01. Confidence high on the
#: value. This is the row that makes a sale credit NET.
PIT = ChargeRule(
    charge_id='pit_securities_transfer',
    base=ChargeBase.TRADE_VALUE,
    side=ChargeSide.SELL,
    levied_by=LeviedBy.STATE,
    debited_at=DebitedAt.FILL,
    pool=Pool.SECURITIES,
    applies_to=frozenset({ChargeClass.EQUITY}),
    rate=Decimal('0.001'),
    citation=RuleCitation(document='Circular 111/2013/TT-BTC as amended',
                          effective_from=date(2015, 1, 1),
                          confidence=Confidence.HIGH),
)

#: A flat retail commission. Rulebook 12.7 records that real commissions tier
#: on the day's total traded value per account and are therefore debited at
#: the daily close; a FLAT rate is knowable at fill time, so this row is
#: DebitedAt.FILL and the tiered case is Tier 2.
COMMISSION = ChargeRule(
    charge_id='broker_commission',
    base=ChargeBase.TRADE_VALUE,
    side=ChargeSide.BOTH,
    levied_by=LeviedBy.BROKER,
    debited_at=DebitedAt.FILL,
    pool=Pool.SECURITIES,
    applies_to=frozenset({ChargeClass.EQUITY}),
    rate=Decimal('0.0015'),
)

#: Custody: 0.27 VND per unit per month since 2020-03-19 (rulebook 12.5). The
#: only underlying-market charge that is not per-fill, and it is here to prove
#: a holding charge is never priced into a fill.
CUSTODY = ChargeRule(
    charge_id='vsdc_custody',
    base=ChargeBase.MONTHLY_PER_SECURITY,
    side=ChargeSide.NONE,
    levied_by=LeviedBy.VSD,
    debited_at=DebitedAt.MONTHLY,
    pool=Pool.SECURITIES,
    applies_to=frozenset({ChargeClass.EQUITY}),
    amount=Decimal('0.27'),
    citation=RuleCitation(document='QD 1541/QD-BTC schedule',
                          effective_from=date(2020, 3, 19),
                          confidence=Confidence.HIGH),
)


class StubRuleSet:
    """The one method ``ledgers.py`` asks of a ``RuleSet``.

    ``RuleSet.charges`` refuses to return a ``levied_by == BROKER`` row, so
    this one does too: broker rows arrive through ``BrokerProfile``, and the
    split is the whole reason there are two config objects.
    """

    def __init__(self, rows=(PIT, CUSTODY)):
        self._rows = tuple(rows)

    def charges(self, venue, cls_):
        assert all(r.levied_by is not LeviedBy.BROKER for r in self._rows)
        return self._rows


NO_CHARGES = StubRuleSet(rows=())
RULES = StubRuleSet()
BROKER = BrokerProfile(name='test-retail', commission=(COMMISSION,))
BARE_BROKER = BrokerProfile(name='test-retail-free')

T0 = datetime(2022, 3, 14, 9, 30)
T2_1300 = datetime(2022, 3, 16, 13, 0)


def account(cash=Decimal('150000000'), terms=None, holdings=None,
            profile=BARE_BROKER, rules_profile=None, advance_terms=None):
    """A securities account wired to one shared encumbrance ledger."""
    enc = EncumbranceLedger()
    cash_ledger = CashLedger(cash, terms or BrokerTerms(), enc,
                             advance_terms=advance_terms)
    holdings_ledger = HoldingsLedger(enc, initial=holdings)
    return SecuritiesAccount(
        AccountRef.securities('SEC-0001'), cash_ledger, holdings_ledger, enc,
        profile=profile,
    )


def buy(ticker='FPT', quantity=1000, price='95.5', order_type=OrderType.LIMIT):
    return Order(ticker=ticker, side=Side.BUY, quantity=quantity,
                 order_type=order_type,
                 limit_price=Decimal(price) if price is not None else None)


def sell(ticker='FPT', quantity=1000, price='96.0'):
    return Order(ticker=ticker, side=Side.SELL, quantity=quantity,
                 order_type=OrderType.LIMIT, limit_price=Decimal(price))


def state(ceiling='102.0'):
    return MarketState(ticker='FPT', ts=T0, reference=Decimal('95.5'),
                       ceiling=Decimal(ceiling) if ceiling else None,
                       floor=Decimal('88.9'),
                       band_source=(BandSource.PUBLISHED if ceiling
                                    else BandSource.ABSENT))


def fill(order_id, side=Side.BUY, quantity=1000, price='95.0', ts=T0,
         ticker='FPT', charges=()):
    return Fill(fill_id=FillId(f'F-{order_id}-{quantity}'),
                order_id=OrderId(order_id), ticker=ticker, venue=Venue.HSX,
                side=side, quantity=quantity, price=Decimal(price), ts=ts,
                evidence=FillEvidence.TRADED_THROUGH, charges=tuple(charges))


# --------------------------------------------------------------------------
# Section 12 invariant 4 -- the test that catches the whole leak class
# --------------------------------------------------------------------------

def test_encumbrance_equals_committed_and_returns_to_exactly_zero():
    """Section 12 invariant 4, over every terminal edge in one sequence.

    The sum of encumbrance over live orders must equal the ledgers' committed
    totals at every point, and committed must return to EXACTLY zero when no
    order is live. Decimal, not approx: a leak of one dong per order is still
    a leak, and rounding it away is how the class hides.

    The sequence walks all four terminal edges -- filled, partially filled
    then cancelled, expired, and a rejection that never reserved -- because
    each is a separate place the release hook can be forgotten.
    """
    acct = account(holdings={'FPT': 2000})
    enc = acct.encumbrances

    def check(cash_expected, shares_expected, live):
        """Three readings of one number, computed three different ways.

        The test states independently what should be reserved; the
        encumbrance ledger sums it over live orders; and the read models
        derive `available` and `sellable` from it. Asserting only the last
        two against each other would be vacuous -- they read the same object
        by design -- so the expected value is the anchor.
        """
        cash = acct.cash()
        holding = acct.holding('FPT')
        assert enc.outstanding(pool=Pool.SECURITIES,
                               resource=ResourceKind.CASH) == cash_expected
        assert cash.committed == cash_expected
        assert cash.available == cash.settled_balance - cash_expected
        assert enc.outstanding_quantity('FPT') == shares_expected
        assert holding.committed == shares_expected
        assert holding.sellable == holding.settled - shares_expected
        assert enc.live_order_ids() == frozenset(live)

    check(Decimal('0'), 0, ())

    # 1. a buy that fills in full: 500 x 95.5 x 1000 dong reserved
    a = acct.reserve_for_buy(OrderId('A'), buy(quantity=500), Venue.HSX,
                             state(), RULES, T0)
    assert isinstance(a, Encumbrance)
    check(Decimal('47750000'), 0, ('A',))
    acct.apply_fill(fill('A', quantity=500), T2_1300)
    check(Decimal('0'), 0, ())          # consumed in full, before the edge
    acct.release(OrderId('A'), T0)      # the FILLED terminal edge
    check(Decimal('0'), 0, ())

    # 2. a sell that half fills and is then cancelled
    acct.reserve_for_sell(OrderId('B'), sell(quantity=1000), Venue.HSX, T0)
    check(Decimal('0'), 1000, ('B',))
    acct.apply_fill(fill('B', side=Side.SELL, quantity=400, price='96.0'),
                    T2_1300)
    check(Decimal('0'), 600, ('B',))
    acct.release(OrderId('B'), T0)      # the CANCELLED terminal edge
    check(Decimal('0'), 0, ())

    # 3. a buy that rests and expires unfilled
    acct.reserve_for_buy(OrderId('C'), buy(quantity=300), Venue.HSX, state(),
                         RULES, T0)
    check(Decimal('28650000'), 0, ('C',))
    acct.release(OrderId('C'), T0)      # the EXPIRED terminal edge
    check(Decimal('0'), 0, ())

    # 4. a rejection, which never reserved -- the hook still fires
    rejected = acct.reserve_for_buy(OrderId('D'), buy(quantity=1_000_000),
                                    Venue.HSX, state(), RULES, T0)
    assert rejected.rule is StatefulRule.INSUFFICIENT_CASH
    acct.release(OrderId('D'), T0)      # the REJECTED terminal edge
    check(Decimal('0'), 0, ())

    # 5. two live orders at once, so the sum is over a set and not one row
    acct.reserve_for_buy(OrderId('E'), buy(quantity=200), Venue.HSX, state(),
                         RULES, T0)
    acct.reserve_for_sell(OrderId('F'), sell(quantity=100), Venue.HSX, T0)
    check(Decimal('19100000'), 100, ('E', 'F'))
    acct.release(OrderId('E'), T0)
    acct.release(OrderId('F'), T0)
    check(Decimal('0'), 0, ())


def test_release_is_idempotent_so_the_hook_can_be_unconditional():
    """The terminal hook fires once per order but must survive being wired
    to every edge, including edges of orders that never reserved."""
    acct = account()
    acct.reserve_for_buy(OrderId('A'), buy(), Venue.HSX, state(), RULES, T0)
    assert acct.encumbrances.release(OrderId('A'), T0) != ()
    assert acct.encumbrances.release(OrderId('A'), T0) == ()
    assert acct.encumbrances.release(OrderId('never-seen'), T0) == ()
    assert acct.cash().committed == Decimal('0')


def test_re_reserving_the_same_resource_is_refused_not_merged():
    """An order reserves at most one of each resource. Merging a second
    reservation would double-count it against `available` with nothing left
    to reconcile the two halves against."""
    acct = account()
    acct.reserve_for_buy(OrderId('A'), buy(quantity=100), Venue.HSX, state(),
                         RULES, T0)
    with pytest.raises(ValueError, match='already holds'):
        acct.encumbrances.take(OrderId('A'), Pool.SECURITIES,
                               ResourceKind.CASH, T0, amount=Decimal('1'))


# --------------------------------------------------------------------------
# Net-of-live-orders: the two failures shape 2 exists to prevent
# --------------------------------------------------------------------------

def test_two_individually_affordable_buys_cannot_both_rest():
    """Design section 7.0's first failure mode. Each buy costs 95.5m against
    150m of cash, so each is affordable alone; together they are not, and
    without an encumbrance both rest and the account overdraws by 41m."""
    acct = account(cash=Decimal('150000000'))
    first = acct.reserve_for_buy(OrderId('A'), buy(), Venue.HSX, state(),
                                 RULES, T0)
    assert isinstance(first, Encumbrance)
    assert acct.cash().available == Decimal('150000000') - Decimal('95500000')

    second = acct.reserve_for_buy(OrderId('B'), buy(), Venue.HSX, state(),
                                  RULES, T0)
    assert second.rule is StatefulRule.INSUFFICIENT_CASH
    assert second.binding_constraint == Decimal('54500000')


def test_500_settled_shares_cannot_back_1000_shares_of_resting_sells():
    """Design section 7.0's second failure mode. Two resting sells of 500 are
    fine; a third would be a short equity position, which Vietnam does not
    permit at all."""
    acct = account(holdings={'FPT': 1000})
    acct.reserve_for_sell(OrderId('A'), sell(quantity=500), Venue.HSX, T0)
    acct.reserve_for_sell(OrderId('B'), sell(quantity=500), Venue.HSX, T0)
    assert acct.holding('FPT').sellable == 0

    third = acct.reserve_for_sell(OrderId('C'), sell(quantity=500), Venue.HSX,
                                  T0)
    assert third.rule is StatefulRule.UNSETTLED_HOLDING
    assert third.binding_constraint == 0


def test_a_buy_reserved_at_955_that_fills_at_950_releases_the_difference():
    """The pro-rata release, at the fill price and not the reserved price.

    A limit buy of 1,000 at 95.5 reserves 95,500,000. A partial fill of 400 at
    95.0 spends 38,000,000 but held 38,200,000 against those shares. Releasing
    only what was spent leaves 200,000 reserved behind a quantity that no
    longer exists, and `available` understates by 0.5 per share for the rest
    of the order's life.
    """
    acct = account(cash=Decimal('150000000'))
    acct.reserve_for_buy(OrderId('A'), buy(), Venue.HSX, state(), RULES, T0)
    assert acct.cash().committed == Decimal('95500000')

    acct.apply_fill(fill('A', quantity=400, price='95.0'), T2_1300)

    # 600 shares remain reserved at the reserved price, to the dong.
    assert acct.cash().committed == Decimal('57300000')
    assert acct.cash().settled_balance == Decimal('150000000') - Decimal('38000000')
    assert acct.cash().available == Decimal('112000000') - Decimal('57300000')

    # ... and the residue goes to exactly zero on the terminal edge.
    acct.release(OrderId('A'), T0)
    assert acct.cash().committed == Decimal('0')
    assert acct.cash().available == Decimal('112000000')


def test_a_partial_fill_then_cancel_releases_the_residue_exactly():
    """The exit locked shape 4 says matters most -- a half-filled resting
    order is exactly the one a caller cancels -- read from the ledger side."""
    acct = account(cash=Decimal('150000000'))
    acct.reserve_for_buy(OrderId('A'), buy(), Venue.HSX, state(), RULES, T0)
    acct.apply_fill(fill('A', quantity=400, price='95.5'), T2_1300)
    acct.apply_fill(fill('A', quantity=100, price='95.5'), T2_1300)
    acct.release(OrderId('A'), T0)

    spent = Decimal('500') * Decimal('95.5') * Decimal('1000')
    assert acct.cash().committed == Decimal('0')
    assert acct.cash().settled_balance == Decimal('150000000') - spent
    assert acct.cash().available == acct.cash().settled_balance


# --------------------------------------------------------------------------
# Locked shape 3 -- tranches, and the sale that must not be permitted
# --------------------------------------------------------------------------

def test_the_tier_1_demo_a_same_session_sale_is_refused_with_an_instant():
    """Buy FPT, try to sell it the same session, get
    Rejected(UNSETTLED_HOLDING) carrying `sellable_from`.

    `sellable_from` is attached rather than stored because it is a function of
    the quantity requested, and `binding_constraint` is the quantity that
    bound -- two different numbers in two different fields.
    """
    acct = account()
    acct.reserve_for_buy(OrderId('A'), buy(), Venue.HSX, state(), RULES, T0)
    acct.apply_fill(fill('A'), T2_1300)
    acct.release(OrderId('A'), T0)

    rejection = acct.reserve_for_sell(OrderId('B'), sell(), Venue.HSX,
                                      datetime(2022, 3, 14, 14, 0))
    assert rejection.rule is StatefulRule.UNSETTLED_HOLDING
    assert rejection.verdict is Verdict.REJECTED
    assert rejection.binding_constraint == 0
    assert rejection.sellable_from == T2_1300


def test_the_earlier_tranche_does_not_free_the_later_tranches_shares():
    """The shape-3 failure, in both directions.

    A scalar (quantity, sellable_from) pair forces a wrong choice: the
    earlier instant frees the later parcel -- permitting exactly the sale the
    settlement rule exists to prevent -- or the later instant blocks the
    earlier one, a spurious rejection. A tranche list does neither.
    """
    enc = EncumbranceLedger()
    holdings = HoldingsLedger(enc)
    monday, tuesday = datetime(2022, 3, 16, 13), datetime(2022, 3, 17, 13)
    holdings.credit_unsettled('FPT', 500, monday, T0)
    holdings.credit_unsettled('FPT', 700, tuesday, T0)

    # Nothing is sellable before the first instant, and the LATER parcel does
    # not block the earlier one from settling on time.
    assert holdings.holding('FPT').sellable == 0
    holdings.settle_due(monday)
    assert holdings.holding('FPT').sellable == 500

    # The EARLIER instant did not free the later parcel's shares.
    assert holdings.holding('FPT').unsettled_quantity == 700
    assert holdings.holding('FPT').sellable_from(1000) == tuesday

    holdings.settle_due(tuesday)
    assert holdings.holding('FPT').sellable == 1200


def test_credit_unsettled_never_merges_two_parcels():
    """Even at the same instant. A merge loses which fill bought what, and
    the corporate-action hook needs per-parcel granularity."""
    holdings = HoldingsLedger(EncumbranceLedger())
    holdings.credit_unsettled('FPT', 500, T2_1300, T0, OrderId('A'))
    holdings.credit_unsettled('FPT', 500, T2_1300, T0, OrderId('B'))
    unsettled = holdings.holding('FPT').unsettled
    assert len(unsettled) == 2
    assert {t.source_order_id for t in unsettled} == {'A', 'B'}


def test_t2_at_1300_behaves_as_t3_on_midnight_stamped_daily_bars():
    """A daily bar is stamped midnight, so it does not clear a 13:00
    threshold. That is the conservative direction and it is intended -- it is
    the difference the Tier 1 demo turns on, so it is pinned rather than left
    to emerge from timestamp arithmetic."""
    holdings = HoldingsLedger(EncumbranceLedger())
    holdings.credit_unsettled('FPT', 1000, T2_1300, T0)

    t2_bar = datetime(2022, 3, 16, 0, 0)
    assert holdings.settle_due(t2_bar) == ()
    assert holdings.holding('FPT').settled == 0

    t3_bar = datetime(2022, 3, 17, 0, 0)
    assert len(holdings.settle_due(t3_bar)) == 1
    assert holdings.holding('FPT').settled == 1000


def test_a_sell_never_draws_on_unsettled_quantity():
    """`debit_settled` raises rather than silently overdrawing: the
    encumbrance should have made it unreachable, and an overdraw here is a
    short equity position."""
    holdings = HoldingsLedger(EncumbranceLedger(), initial={'FPT': 300})
    holdings.credit_unsettled('FPT', 1000, T2_1300, T0)
    with pytest.raises(ValueError, match='short equity position'):
        holdings.debit_settled('FPT', 500, T0)


# --------------------------------------------------------------------------
# Cash: pre-funding, net proceeds, and the sale advance
# --------------------------------------------------------------------------

def test_pending_proceeds_do_not_fund_a_buy():
    """Equity is 100% pre-funded, so a buy is refused when `available` is
    short EVEN IF pending proceeds would cover it. Rulebook 5.1's blunt
    consequence: sell-then-rebuy on the same day is not possible on settled
    cash alone."""
    acct = account(cash=Decimal('1000000'), holdings={'FPT': 1000})
    acct.reserve_for_sell(OrderId('S'), sell(), Venue.HSX, T0)
    acct.apply_fill(fill('S', side=Side.SELL, price='96.0'), T2_1300)
    acct.release(OrderId('S'), T0)

    assert acct.cash().pending_total == Decimal('96000000')
    assert acct.cash().available == Decimal('1000000')

    rejection = acct.reserve_for_buy(OrderId('B'), buy(), Venue.HSX, state(),
                                     RULES, T0)
    assert rejection.rule is StatefulRule.INSUFFICIENT_CASH
    assert rejection.binding_constraint == Decimal('1000000')
    assert rejection.detail['pending_proceeds'] == Decimal('96000000')


def test_a_sale_credits_net_of_the_sell_side_pit():
    """Rulebook 12.3: the 0.1% personal income tax is sell-side only and
    withheld at source, so a sale credits NET. Carrying gross and netting
    later is how a sale ends up wrong by more than most commissions."""
    acct = account(holdings={'FPT': 1000}, profile=BROKER)
    acct.reserve_for_sell(OrderId('S'), sell(), Venue.HSX, T0)
    executed = fill('S', side=Side.SELL, price='96.0')
    charges = assess_charges(RULES, BROKER, executed, ChargeClass.EQUITY)
    acct.apply_fill(executed, T2_1300, charges)

    gross = Decimal('96000000')
    pit = Decimal('96000')            # 0.1%
    commission = Decimal('144000')    # 0.15%
    assert {c.kind: c.amount for c in charges} == {
        'pit_securities_transfer': pit, 'broker_commission': commission}
    assert acct.cash().pending_total == gross - pit - commission

    # Withheld at source: recorded in charges(), NOT debited a second time.
    assert len(acct.cash_ledger.charges()) == 2
    assert acct.cash().settled_balance == Decimal('150000000')


def test_a_buy_debits_the_charges_because_they_are_not_withheld():
    """The buy side is the mirror: nothing is withheld out of a purchase, so
    the charges leave settled cash alongside the trade value."""
    acct = account(profile=BROKER)
    acct.reserve_for_buy(OrderId('A'), buy(), Venue.HSX, state(), RULES, T0)
    executed = fill('A', price='95.0')
    charges = assess_charges(RULES, BROKER, executed, ChargeClass.EQUITY)
    acct.apply_fill(executed, T2_1300, charges)

    assert [c.kind for c in charges] == ['broker_commission']   # PIT is sell-only
    spent = Decimal('95000000') + Decimal('142500')
    assert acct.cash().settled_balance == Decimal('150000000') - spent


def test_the_advance_is_off_by_default_because_it_is_a_broker_term():
    """*Ung truoc tien ban* is a commercial product, not an exchange rule. A
    simulator that turns it on by default asserts a house term as market
    law."""
    acct = account(holdings={'FPT': 1000})
    acct.reserve_for_sell(OrderId('S'), sell(), Venue.HSX, T0)
    acct.apply_fill(fill('S', side=Side.SELL, price='96.0'), T2_1300)
    assert BrokerTerms().advance_on_sale_enabled is False
    assert acct.cash().advanced == Decimal('0')
    assert acct.cash().available == Decimal('150000000')


def test_the_advance_makes_unsettled_proceeds_spendable_immediately():
    """With the term enabled, the proceeds enter `available` at once. That is
    the only way to recycle sale proceeds intraday, and the reason it must be
    charged for is that otherwise the backtest overstates turnover."""
    terms = BrokerTerms(advance_on_sale_enabled=True,
                        advance_on_sale_daily_rate=Decimal('0.00035'))
    acct = account(cash=Decimal('1000000'), terms=terms,
                   holdings={'FPT': 1000})
    acct.reserve_for_sell(OrderId('S'), sell(), Venue.HSX, T0)
    acct.apply_fill(fill('S', side=Side.SELL, price='96.0'), T2_1300)
    acct.release(OrderId('S'), T0)

    assert acct.cash().advanced == Decimal('96000000')
    assert acct.cash().available == Decimal('97000000')

    # And it can actually fund a buy the same session.
    reserved = acct.reserve_for_buy(OrderId('B'), buy(), Venue.HSX, state(),
                                    RULES, T0)
    assert isinstance(reserved, Encumbrance)


def test_advance_interest_accrues_at_the_daily_rate_and_is_never_netted():
    """Rulebook 12.7: interest is `amount_advanced x daily_rate x
    days_advanced`. Modelled, not hand-waved -- and reported rather than
    netted, because design section 7.2 leaves what to do with it to the
    caller."""
    terms = BrokerTerms(advance_on_sale_enabled=True,
                        advance_on_sale_daily_rate=Decimal('0.0005'))
    enc = EncumbranceLedger()
    ledger = CashLedger(Decimal('0'), terms, enc)
    ledger.credit_pending(Decimal('96000000'), T2_1300, T0)

    accrued = ledger.accrue_interest(datetime(2022, 3, 15, 9, 30))
    assert accrued == Decimal('96000000') * Decimal('0.0005')   # one day
    assert ledger.cash().interest_accrued == accrued
    # Reported, never netted: the balance and the advance are untouched.
    assert ledger.cash().settled_balance == Decimal('0')
    assert ledger.cash().advanced == Decimal('96000000')


def test_interest_is_not_charged_twice_for_the_same_day():
    """Each tranche carries its own watermark, which moves by whole days
    only, so repeated calls are safe and a part-day is carried, not lost."""
    terms = BrokerTerms(advance_on_sale_enabled=True,
                        advance_on_sale_daily_rate=Decimal('0.0005'))
    ledger = CashLedger(Decimal('0'), terms, EncumbranceLedger())
    ledger.credit_pending(Decimal('10000000'), T2_1300, T0)

    one_day = datetime(2022, 3, 15, 9, 30)
    first = ledger.accrue_interest(one_day)
    assert ledger.accrue_interest(one_day) == Decimal('0')
    assert ledger.accrue_interest(datetime(2022, 3, 15, 20, 0)) == Decimal('0')
    assert ledger.cash().interest_accrued == first


def test_interest_stops_at_settlement_because_the_advance_is_recovered_there():
    """The advance is recovered out of the T+2 proceeds, so a caller that
    advances the clock a week before accruing still pays only to settlement.
    Declared assumption: the day count is calendar days, which no source
    states."""
    terms = BrokerTerms(advance_on_sale_enabled=True,
                        advance_on_sale_daily_rate=Decimal('0.0005'))
    ledger = CashLedger(Decimal('0'), terms, EncumbranceLedger())
    ledger.credit_pending(Decimal('10000000'), T2_1300, T0)

    accrued = ledger.accrue_interest(datetime(2022, 3, 25, 9, 30))
    assert accrued == Decimal('10000000') * Decimal('0.0005') * Decimal('2')


def test_settling_an_advanced_tranche_leaves_available_unchanged():
    """The advance made the money spendable early; it did not create any. On
    settlement the amount simply moves out of `advanced` and into
    `settled_balance`."""
    terms = BrokerTerms(advance_on_sale_enabled=True)
    ledger = CashLedger(Decimal('1000000'), terms, EncumbranceLedger())
    ledger.credit_pending(Decimal('96000000'), T2_1300, T0)
    before = ledger.cash().available

    settled = ledger.settle_due(T2_1300)
    assert len(settled) == 1
    assert ledger.cash().advanced == Decimal('0')
    assert ledger.cash().settled_balance == Decimal('97000000')
    assert ledger.cash().available == before


def test_spending_an_advance_may_take_the_settled_balance_negative():
    """The advanced money is spendable but has not arrived, so spending it
    overdraws the settled balance by design and the settlement squares it.
    What is refused is a debit beyond settled + advanced."""
    terms = BrokerTerms(advance_on_sale_enabled=True)
    ledger = CashLedger(Decimal('1000000'), terms, EncumbranceLedger())
    ledger.credit_pending(Decimal('96000000'), T2_1300, T0)

    ledger.debit(Decimal('50000000'), T0, reason='buy FPT')
    assert ledger.cash().settled_balance == Decimal('-49000000')

    with pytest.raises(ValueError, match='exceeds settled'):
        ledger.debit(Decimal('60000000'), T0, reason='buy again')


# --------------------------------------------------------------------------
# Charges
# --------------------------------------------------------------------------

def test_estimated_charges_are_inside_the_buy_encumbrance():
    """Design section 7.0: the estimate is inside the reservation so
    `available` stays consistent with what a fill will actually cost.
    Leaving it out lets a caller rest a buy it can fund the shares of and not
    the fees."""
    acct = account(profile=BROKER)
    acct.reserve_for_buy(OrderId('A'), buy(), Venue.HSX, state(), RULES, T0)
    expected = Decimal('95500000') + Decimal('95500000') * Decimal('0.0015')
    assert acct.cash().committed == expected


def test_a_holding_charge_is_never_priced_into_a_fill():
    """Custody is monthly per security and the VSD position fee is per open
    contract per day (rulebook 12.2). No per-fill model can express either,
    so they are skipped rather than approximated, and a Tier 2 monthly pass
    owns them."""
    estimate = estimate_charges(StubRuleSet(rows=(CUSTODY,)), buy(),
                                Venue.HSX, ChargeClass.EQUITY,
                                Decimal('95.5'))
    assert estimate == Decimal('0')
    executed = fill('A')
    assert assess_charges(StubRuleSet(rows=(CUSTODY,)), BARE_BROKER, executed,
                          ChargeClass.EQUITY) == ()


def test_a_daily_charge_is_estimated_but_not_levied_at_the_fill():
    """A commission that tiers on the day's total traded value is not
    knowable at fill time (rulebook 12.2), so it is accrued to the daily
    close -- but a reservation that ignored it would under-fund, and
    over-reserving is the conservative direction."""
    tiered = ChargeRule(
        charge_id='tiered_commission', base=ChargeBase.TRADE_VALUE,
        side=ChargeSide.BOTH, levied_by=LeviedBy.BROKER,
        debited_at=DebitedAt.DAILY, pool=Pool.SECURITIES,
        applies_to=frozenset({ChargeClass.EQUITY}), rate=Decimal('0.0025'))
    profile = BrokerProfile(name='tiered', commission=(tiered,))

    estimate = estimate_charges(NO_CHARGES, buy(), Venue.HSX,
                                ChargeClass.EQUITY, Decimal('95.5'),
                                profile=profile)
    assert estimate == Decimal('95500000') * Decimal('0.0025')
    assert assess_charges(NO_CHARGES, profile, fill('A'),
                          ChargeClass.EQUITY) == ()


def test_a_derivatives_charge_cannot_be_paid_from_securities_cash():
    """The two pools are segregated in Vietnamese law and no auto-transfer
    exists. Debiting one for the other's charge would invent one."""
    ledger = CashLedger(Decimal('1000000'), BrokerTerms(), EncumbranceLedger())
    charge = Charge(kind='vsd_position_fee', venue=Venue.HNXDS,
                    base=ChargeBase.PER_OPEN_CONTRACT_PER_DAY,
                    base_value=Decimal('1'), amount=Decimal('2550'),
                    levied_by=LeviedBy.VSD, pool=Pool.DERIVATIVES, ts=T0)
    with pytest.raises(ValueError, match='segregated'):
        ledger.levy(charge)


def test_charge_amounts_are_rounded_to_whole_dong():
    """A declared MODELLING CHOICE: no Vietnamese source states a rounding
    rule for any fee or tax (rulebook 12.1), and any result sensitive to it
    must say so."""
    executed = fill('A', quantity=100, price='95.55')   # 9,555,000 VND
    charges = assess_charges(NO_CHARGES, BROKER, executed, ChargeClass.EQUITY)
    assert charges[0].base_value == Decimal('9555000')
    assert charges[0].amount == Decimal('14333')        # 14,332.5 rounded up


# --------------------------------------------------------------------------
# Units, pools and the derivatives boundary
# --------------------------------------------------------------------------

def test_cash_venue_prices_are_thousands_of_dong():
    """`CURRENCY_UNIT[HSX] == 1000`, so 1,000 shares at 95.5 move 95.5m dong.
    A missing factor of 1,000 is invisible in a ratio and fatal in a
    balance."""
    assert trade_value(Venue.HSX, 1000, Decimal('95.5')) == Decimal('95500000')


def test_the_cash_conversion_refuses_hnxds():
    """`CURRENCY_UNIT['HNXDS'] == 1` is not a multiplier: index futures quote
    points against a 100,000 VND contract multiplier. Derivatives notional is
    deposit.py's business and must not be computed here by accident."""
    with pytest.raises(ValueError, match='not a multiplier'):
        trade_value(Venue.HNXDS, 1, Decimal('1441.8'))


def test_a_securities_account_refuses_a_derivatives_order():
    """A SELL on HNXDS opens a short and is never checked against holdings; a
    SELL on an equity venue requires settled holdings. The branch is read off
    the account's venue scope, not off a hard-coded list."""
    acct = account()
    with pytest.raises(ValueError, match='deposit.py'):
        acct.reserve_for_sell(OrderId('A'), sell(ticker='VN30F2206'),
                              Venue.HNXDS, T0)


def test_a_market_order_with_no_ceiling_is_indeterminate_not_a_rejection():
    """The order is never funded at a guessed price. An absent band is a data
    gap, not a rule saying no, and design section 5 keeps the two countable
    apart -- conflating them reports a data gap as a market rule."""
    acct = account()
    refused = acct.reserve_for_buy(
        OrderId('A'), buy(price=None, order_type=OrderType.AT_THE_OPENING),
        Venue.HSX, state(ceiling=None), RULES, T0)
    assert refused.rule is AdmissionRule.BAND_LIMIT
    assert refused.verdict is Verdict.INDETERMINATE
    assert refused.is_indeterminate


def test_an_auction_order_is_funded_at_the_ceiling():
    """ATO and ATC must be fundable BEFORE a clearing price exists, and the
    market family reserves there for the code's own 'buy at ceiling for
    guaranteed match' semantics."""
    acct = account(profile=BARE_BROKER)
    acct.reserve_for_buy(
        OrderId('A'), buy(quantity=1000, price=None,
                          order_type=OrderType.AT_THE_CLOSE),
        Venue.HSX, state(ceiling='102.0'), NO_CHARGES, T0)
    assert acct.cash().committed == Decimal('102000000')


# --------------------------------------------------------------------------
# The corporate-action hook (Tier 2, exposed now so it is not retrofitted)
# --------------------------------------------------------------------------

def test_a_split_scales_every_parcel_without_collapsing_them():
    """Design section 15 item 5. There is NO corporate-action engine in Tier
    1 and a run spanning an ex-date is wrong for that instrument; the hook
    exists so the engine is not retrofitted into a scalar. Scaling parcels
    separately is what keeps their distinct settlement instants."""
    holdings = HoldingsLedger(EncumbranceLedger(), initial={'FPT': 1000})
    monday, tuesday = datetime(2022, 3, 16, 13), datetime(2022, 3, 17, 13)
    holdings.credit_unsettled('FPT', 500, monday, T0)
    holdings.credit_unsettled('FPT', 700, tuesday, T0)

    cash_leg, tranches = holdings.apply_corporate_action(
        'FPT', Decimal('2'), Decimal('0'), T0)

    assert cash_leg == Decimal('0')
    assert holdings.holding('FPT').settled == 2000
    assert [(t.quantity, t.settles_at) for t in tranches] == [
        (1000, monday), (1400, tuesday)]


def test_a_cash_dividend_pays_on_unsettled_parcels_too():
    """The entitlement is the holding on the record date, and a share bought
    T+0 and unsettled on the ex-date still carries it. The 5% withholding is
    deliberately NOT applied here: it is a charge row, and inventing a tax
    rate inside the holdings ledger puts it where no charge table can see
    it."""
    holdings = HoldingsLedger(EncumbranceLedger(), initial={'FPT': 1000})
    holdings.credit_unsettled('FPT', 500, T2_1300, T0)

    cash_leg, _ = holdings.apply_corporate_action(
        'FPT', Decimal('1'), Decimal('2000'), T0)

    assert cash_leg == Decimal('3000000')      # 1,500 shares x 2,000 dong
    assert holdings.holding('FPT').total == 1500


def test_an_action_on_an_unheld_ticker_leaves_no_trace_in_the_ledger():
    """``tickers()`` is this ledger's answer to "what did this run touch", and
    ``corporate.CorporateActionAudit`` sweeps it to decide which crossings the
    account was actually exposed to. Writing a zero back for a name the
    account never held would put every ticker in a market-wide corporate-action
    schedule into that answer, and the audit would then report exposure to all
    of them -- which trains the caller to ignore the report."""
    holdings = HoldingsLedger(EncumbranceLedger(), initial={'FPT': 1000})

    cash_leg, tranches = holdings.apply_corporate_action(
        'VIC', Decimal('2'), Decimal('2000'), T0)

    assert (cash_leg, tranches) == (Decimal('0'), ())
    assert holdings.tickers() == frozenset({'FPT'})
    assert holdings.holding('VIC').total == 0


# --------------------------------------------------------------------------
# Atomicity -- apply_fill moves all three ledgers or none of them
# --------------------------------------------------------------------------
#
# The defect these pin: ``apply_fill`` mutated the encumbrance ledger and the
# holdings ledger, and *then* asked the cash ledger for a movement it could
# refuse. The refusal arrived after the shares were already gone.

#: A broker commission carrying a per-order minimum. Rulebook 8.3 records
#: that "some firms impose a minimum charge per order" and 12.7 repeats it in
#: the config schema; both mark it a **broker term**, not an exchange rule.
#: 200,000 VND is a plausible retail figure and is a fixture value, not a
#: sourced one.
MIN_COMMISSION = ChargeRule(
    charge_id='broker_commission',
    base=ChargeBase.TRADE_VALUE,
    side=ChargeSide.BOTH,
    levied_by=LeviedBy.BROKER,
    debited_at=DebitedAt.FILL,
    pool=Pool.SECURITIES,
    applies_to=frozenset({ChargeClass.EQUITY}),
    rate=Decimal('0.0015'),
    minimum=Decimal('200000'),
)
MIN_BROKER = BrokerProfile(name='min-commission',
                           commission=(MIN_COMMISSION,))


def test_a_sale_whose_charges_exceed_its_proceeds_still_delivers_the_shares():
    """A minimum commission on a penny-stock sale nets below zero, and the
    sale still happens.

    Vietnamese penny stocks quote at 1.0-3.0 thousand dong, so 100 shares at
    1.0 gross 100,000d against a 200,000d commission minimum. That is an
    ordinary retail case, not a corner -- and the ledger used to refuse the
    credit *after* consuming the reservation and debiting the shares, which
    destroyed 100 shares and recorded neither proceeds nor charges.

    The trade matched at the exchange; a broker's fee schedule cannot
    un-match it. So the shares leave, every charge is itemised, and the net
    is a negative tranche that settles against the balance at T+2.
    """
    acct = account(holdings={'PENNY': 1000}, profile=MIN_BROKER)
    acct.reserve_for_sell(OrderId('S'), sell(ticker='PENNY', quantity=100,
                                             price='1.0'),
                          Venue.HSX, T0)
    executed = fill('S', side=Side.SELL, quantity=100, price='1.0',
                    ticker='PENNY')
    charges = assess_charges(RULES, MIN_BROKER, executed, ChargeClass.EQUITY)
    acct.apply_fill(executed, T2_1300, charges)
    acct.release(OrderId('S'), T0)

    gross = Decimal('100000')                     # 100 x 1.0 thousand dong
    levied = sum(c.total for c in charges)
    assert levied == Decimal('200000') + Decimal('100')   # min + 0.1% PIT
    assert acct.holding('PENNY').settled == 900
    assert acct.holding('PENNY').committed == 0
    assert acct.cash().pending_total == gross - levied
    assert acct.cash().pending_total == Decimal('-100100')
    # Withheld at source, so recorded and not debited a second time.
    assert len(acct.cash_ledger.charges()) == 2
    assert acct.cash().settled_balance == Decimal('150000000')


def test_a_negative_net_is_never_advanced_and_accrues_no_interest():
    """*Ung truoc tien ban* is a loan against money coming in. When the net is
    negative there is none coming in, so there is nothing to advance and
    nothing to charge interest on.

    Without this, a broker term switched on for the account would report
    negative ``advanced``, which would *raise* ``available`` on a sale that
    lost money, and negative interest, which would pay the investor for
    owing the broker.
    """
    terms = BrokerTerms(advance_on_sale_enabled=True,
                        advance_on_sale_daily_rate=Decimal('0.0005'))
    ledger = CashLedger(Decimal('1000000'), terms, EncumbranceLedger())
    tranche = ledger.credit_pending(Decimal('-100100'), T2_1300, T0)

    assert tranche.advanced is False
    assert ledger.advanced() == Decimal('0')
    assert ledger.accrue_interest(T2_1300) == Decimal('0')
    assert ledger.cash().available == Decimal('1000000')

    ledger.settle_due(T2_1300)
    assert ledger.cash().settled_balance == Decimal('899900')


def test_a_fill_that_cannot_be_paid_for_moves_no_ledger_at_all():
    """The buy branch's version of the same disease, and its regression test.

    ``apply_fill`` consumed the reservation and credited the unsettled
    tranche before asking ``CashLedger.debit`` for money the account did not
    have. The debit's overdraw guard then raised -- after the shares were
    already on the books.

    A genuine overdraw here is still a bug in the reservation path and still
    raises. What must not survive is the half-applied fill it used to leave
    behind.
    """
    acct = account(cash=Decimal('1000000'), profile=BROKER)
    executed = fill('A', quantity=1000, price='95.0')
    charges = assess_charges(RULES, BROKER, executed, ChargeClass.EQUITY)

    with pytest.raises(ValueError, match='exceeds'):
        acct.apply_fill(executed, T2_1300, charges)

    assert acct.holding('FPT').total == 0
    assert acct.holding('FPT').unsettled == ()
    assert acct.cash().settled_balance == Decimal('1000000')
    assert acct.cash_ledger.charges() == ()


# --------------------------------------------------------------------------
# ung truoc tien ban -- the advance against unsettled sale proceeds
#
# Rulebook 8.3/8.4 and 12.7. The formula and the legal status are sourced; the
# rate, the cap and the annualisation basis are not, and every test below that
# depends on one of those says so.
# --------------------------------------------------------------------------

#: A firm that offers the product. 0.05%/day is the top of the observed
#: 0.025-0.05%/day band (rulebook 12.7, medium confidence), chosen because it
#: makes the arithmetic in these tests legible, not because it is typical.
ADVANCE_ON = BrokerTerms(advance_on_sale_enabled=True,
                         advance_on_sale_daily_rate=Decimal('0.0005'))

#: The same firm, but the investor must ask per sale rather than the broker
#: advancing every tranche on a standing registration.
ON_REQUEST = AdvanceTerms.from_broker(ADVANCE_ON, auto_register=False)


def cash_ledger(cash=Decimal('0'), terms=ADVANCE_ON, advance_terms=ON_REQUEST):
    return CashLedger(cash, terms, EncumbranceLedger(),
                      advance_terms=advance_terms)


def test_the_declared_annualisation_basis_is_365_and_is_recorded_not_baked_in():
    """Rulebook 12.1: "Declare one basis and use it... Recommend 365 with the
    basis recorded in the config."

    Recorded, not baked in: it is a field on the terms, so a caller reading a
    360-basis quote can say so and get that quote's own arithmetic."""
    assert DECLARED_ANNUALISATION_BASIS == ANNUALISATION_BASIS_365 == 365
    assert ANNUALISATION_BASIS_360 == 360
    assert AdvanceTerms.from_broker(ADVANCE_ON).annualisation_basis == 365

    on_360 = AdvanceTerms.from_broker(ADVANCE_ON, annualisation_basis=360)
    assert on_360.annualisation_basis == 360


def test_the_two_bases_in_the_sources_disagree_by_about_one_point_four_percent():
    """Rulebook 8.3's ANNUALISATION BASIS CONFLICT, reproduced.

    The 0.025-0.05%/day industry range is annualised as "9-18% p.a.", which is
    x360; DSC's "0.0356%/day = 13%/yr" is x365. Feeding one annual quote
    through the other basis misprices the advance by 365/360 - 1, and the
    error is systematic rather than noisy. So the basis is a named argument
    and it is stored on the result."""
    thirteen = Decimal('0.13')
    on_365 = AdvanceTerms.from_annual_rate(thirteen)
    on_360 = AdvanceTerms.from_annual_rate(
        thirteen, annualisation_basis=ANNUALISATION_BASIS_360)

    # DSC's published pair is reproduced by the 365 basis, not the 360 one.
    assert on_365.daily_rate.quantize(Decimal('0.000001')) == Decimal('0.000356')
    assert on_360.daily_rate.quantize(Decimal('0.000001')) == Decimal('0.000361')

    divergence = on_360.daily_rate / on_365.daily_rate - 1
    assert divergence.quantize(Decimal('0.0001')) == Decimal('0.0139')

    # And each basis inverts with its own number, so a printed headline rate
    # cannot silently be on a different basis from the terms it came from.
    assert on_365.annual_rate == thirteen
    assert on_360.annual_rate == thirteen


def test_the_basis_never_enters_the_daily_accrual():
    """Accrual counts actual calendar days between two instants; no year
    length appears in it. Two ledgers on the same daily rate and different
    bases must charge the same interest -- if they did not, the basis would be
    being applied twice."""
    on_365 = cash_ledger(advance_terms=AdvanceTerms.from_broker(
        ADVANCE_ON, auto_register=False))
    on_360 = cash_ledger(advance_terms=AdvanceTerms.from_broker(
        ADVANCE_ON, auto_register=False, annualisation_basis=360))
    for ledger in (on_365, on_360):
        ledger.credit_pending(Decimal('10000000'), T2_1300, T0)
        ledger.request_advance(T0)

    assert (on_365.accrue_interest(T2_1300)
            == on_360.accrue_interest(T2_1300)
            == Decimal('10000000') * Decimal('0.0005') * 2)


def test_an_advance_is_drawn_against_the_tranche_the_caller_names():
    """The product is a draw on a *particular* receivable. A request naming
    one parcel must leave the others untouched -- otherwise "request an
    advance" is just "turn the flag on"."""
    ledger = cash_ledger()
    first = ledger.credit_pending(Decimal('20000000'), T2_1300, T0,
                                  OrderId('S1'))
    ledger.credit_pending(Decimal('30000000'), T2_1300, T0, OrderId('S2'))
    assert ledger.advanced() == Decimal('0')

    drawn = ledger.request_advance(T0, tranche=first)

    assert len(drawn) == 1
    assert drawn[0].amount == Decimal('20000000')
    assert drawn[0].source_order_id == OrderId('S1')
    assert ledger.advanced() == Decimal('20000000')

    by_order = {t.source_order_id: t for t in ledger.cash().pending_proceeds}
    assert by_order[OrderId('S1')].advanced is True
    assert by_order[OrderId('S2')].advanced is False


def test_a_partial_draw_leaves_the_rest_advanceable():
    """A cap phrased as "up to 100%" is meaningless if the only representable
    draw is exactly 100%. Tier 1's boolean could not express this at all."""
    ledger = cash_ledger()
    tranche = ledger.credit_pending(Decimal('50000000'), T2_1300, T0)

    ledger.request_advance(T0, Decimal('20000000'))
    assert ledger.advanced() == Decimal('20000000')
    assert ledger.advanceable() == Decimal('30000000')
    assert ledger.cash().pending_proceeds[0].advanced is True

    ledger.request_advance(T0, Decimal('30000000'), tranche=tranche)
    assert ledger.advanced() == Decimal('50000000')
    assert ledger.advanceable() == Decimal('0')
    assert len(ledger.advances()) == 2


def test_the_bound_is_the_unsourced_hundred_percent_of_net_after_fees_and_pit():
    """Rulebook 8.3: "up to 100% of net proceeds after fees and PIT" -- and it
    is flagged there as the common *description*, not a sourced figure. No
    statutory cap exists and no broker schedule stating a maximum could be
    retrieved (low confidence).

    "After fees and PIT" comes for free, because ``credit_pending`` already
    receives the net: the bound here is 96m gross less the 0.1% PIT withheld
    at source and less the broker's 0.15%."""
    acct = account(holdings={'FPT': 1000}, terms=ADVANCE_ON, profile=BROKER,
                   advance_terms=ON_REQUEST)
    acct.reserve_for_sell(OrderId('S'), sell(), Venue.HSX, T0)
    executed = fill('S', side=Side.SELL, price='96.0')
    acct.apply_fill(executed, T2_1300,
                    assess_charges(RULES, BROKER, executed, ChargeClass.EQUITY))

    net = Decimal('96000000') - Decimal('96000') - Decimal('144000')
    assert acct.cash().pending_total == net
    assert acct.advanceable() == net

    # The caveat travels with the number, not just with the prose.
    provenance = AdvanceTerms.PROVENANCE['max_advanceable_fraction']
    assert 'ASSUMPTION' in provenance
    assert 'not a sourced figure' in provenance


def test_a_request_beyond_the_bound_is_refused_rather_than_clamped():
    """Silently clamping turns a funding decision into an unexplained
    INSUFFICIENT_CASH two calls later. Refused with the bound in the message,
    and refused as a ValueError rather than a Rejected -- the rejection enums
    are the record of what the *market* refused, and a broker declining to
    lend more than it agreed to is not that."""
    ledger = cash_ledger()
    ledger.credit_pending(Decimal('10000000'), T2_1300, T0)

    with pytest.raises(ValueError, match='at most 10000000 is advanceable'):
        ledger.request_advance(T0, Decimal('10000001'))
    assert ledger.advanced() == Decimal('0')
    assert ledger.advances() == ()


def test_the_cap_is_configurable_and_a_seventy_percent_cap_bites():
    """The 100% default is an assumption, so it must be possible to run a
    result against a different one and see the difference."""
    terms = AdvanceTerms.from_broker(
        ADVANCE_ON, auto_register=False,
        max_advanceable_fraction=Decimal('0.7'))
    ledger = cash_ledger(advance_terms=terms)
    ledger.credit_pending(Decimal('10000000'), T2_1300, T0)

    assert ledger.advanceable() == Decimal('7000000')
    with pytest.raises(ValueError, match='at most 7000000'):
        ledger.request_advance(T0, Decimal('7000001'))
    assert ledger.request_advance(T0)[0].amount == Decimal('7000000')


def test_a_cap_above_one_is_refused_because_that_would_be_a_loan():
    """A securities company may not lend money in any form except margin and
    error correction (TT 121/2020 Art. 27, rulebook 8.4). Advancing more than
    the sale produced is exactly the thing the product is structured to avoid
    being."""
    with pytest.raises(ValueError, match=r'\[0, 1\]'):
        AdvanceTerms(daily_rate=Decimal('0.0005'),
                     max_advanceable_fraction=Decimal('1.2'))


def test_a_negative_net_tranche_cannot_be_advanced_on_request_either():
    """Tier 1 established that auto-registration skips a negative net. The
    request path must refuse it too, or the rule holds only on the path that
    happens not to be used."""
    ledger = cash_ledger()
    tranche = ledger.credit_pending(Decimal('-100100'), T2_1300, T0)

    assert tranche.advanced is False
    assert ledger.advanceable() == Decimal('0')
    with pytest.raises(ValueError, match='nothing is advanceable'):
        ledger.request_advance(T0, tranche=tranche)
    with pytest.raises(ValueError, match='nothing is advanceable'):
        ledger.request_advance(T0, Decimal('50000'), tranche=tranche)

    assert ledger.accrue_interest(T2_1300) == Decimal('0')
    ledger.settle_due(T2_1300)
    assert ledger.cash().interest_accrued == Decimal('0')
    assert ledger.cash().settled_balance == Decimal('-100100')


def test_interest_runs_per_advance_so_each_draw_pays_for_its_own_days():
    """Two draws against one tranche, taken a day apart. The second owes one
    day, not two. A model that prices interest per *tranche* charges the
    later draw for a day it did not have the money -- 3,000 instead of
    2,000 here."""
    ledger = cash_ledger()
    ledger.credit_pending(Decimal('10000000'), T2_1300, T0)
    ledger.request_advance(T0, Decimal('1000000'))
    day_two = datetime(2022, 3, 15, 9, 30)
    ledger.request_advance(day_two, Decimal('2000000'))

    accrued = ledger.accrue_interest(T2_1300)
    two_days = Decimal('1000000') * Decimal('0.0005') * 2
    one_day = Decimal('2000000') * Decimal('0.0005') * 1
    assert accrued == two_days + one_day == Decimal('2000')
    assert accrued != Decimal('3000000') * Decimal('0.0005') * 2


def test_settlement_repays_every_advance_and_interest_stops_there():
    """Rulebook 8.3: the advance "is recovered automatically from the sale
    proceeds at T+2 settlement". After that there is no principal outstanding
    and no further interest, however far the clock is advanced."""
    ledger = cash_ledger(cash=Decimal('1000000'))
    ledger.credit_pending(Decimal('10000000'), T2_1300, T0)
    ledger.request_advance(T0)
    before = ledger.cash().available

    settled = ledger.settle_due(T2_1300)

    assert len(settled) == 1
    assert ledger.advanced() == Decimal('0')
    assert ledger.advances() == ()
    assert ledger.cash().settled_balance == Decimal('11000000')
    assert ledger.cash().available == before

    charged = ledger.cash().interest_accrued
    assert charged == Decimal('10000000') * Decimal('0.0005') * 2
    assert ledger.accrue_interest(datetime(2022, 4, 30, 9, 30)) == Decimal('0')
    assert ledger.cash().interest_accrued == charged


def test_the_cost_does_not_depend_on_how_often_the_caller_accrues():
    """The bill for an advance is a property of the advance, not of the
    caller's polling loop. Tier 1 lost every day between the last watermark
    and settlement, so a caller that never called ``accrue_interest`` got the
    advance for free -- which is precisely the free intraday turnover the
    product exists to charge for (rulebook 12.7)."""
    daily = cash_ledger()
    never = cash_ledger()
    once = cash_ledger()
    for ledger in (daily, never, once):
        ledger.credit_pending(Decimal('10000000'), T2_1300, T0)
        ledger.request_advance(T0)

    daily.accrue_interest(datetime(2022, 3, 15, 9, 30))
    daily.accrue_interest(datetime(2022, 3, 16, 9, 30))
    once.accrue_interest(datetime(2022, 3, 16, 11, 0))
    for ledger in (daily, never, once):
        ledger.settle_due(T2_1300)

    expected = Decimal('10000000') * Decimal('0.0005') * 2
    assert daily.cash().interest_accrued == expected
    assert never.cash().interest_accrued == expected
    assert once.cash().interest_accrued == expected


def test_an_advance_funds_a_buy_the_same_session_which_is_the_whole_product():
    """Rulebook 5.1: without the advance, sell-then-rebuy on the same day is
    not possible on settled cash alone. Rulebook 12.7: the advance "is the
    only way to recycle sale proceeds intraday, and it must be charged for".

    So the test is the round trip: the buy is refused, the advance is drawn,
    the same buy is accepted, and the account is charged for it."""
    acct = account(cash=Decimal('1000000'), terms=ADVANCE_ON,
                   holdings={'FPT': 1000}, advance_terms=ON_REQUEST)
    acct.reserve_for_sell(OrderId('S'), sell(), Venue.HSX, T0)
    acct.apply_fill(fill('S', side=Side.SELL, price='96.0'), T2_1300)
    acct.release(OrderId('S'), T0)

    refused = acct.reserve_for_buy(OrderId('B'), buy(), Venue.HSX, state(),
                                   RULES, T0)
    assert isinstance(refused, Rejected)
    assert refused.rule is StatefulRule.INSUFFICIENT_CASH

    acct.request_advance(T0, order_id=OrderId('S'))
    assert acct.cash().advanced == Decimal('96000000')
    assert acct.cash().available == Decimal('97000000')

    reserved = acct.reserve_for_buy(OrderId('B'), buy(), Venue.HSX, state(),
                                    RULES, T0)
    assert isinstance(reserved, Encumbrance)

    acct.apply_fill(fill('B', price='95.0'), datetime(2022, 3, 16, 13, 0))
    acct.release(OrderId('B'), T0)
    assert acct.cash().settled_balance == Decimal('-94000000')
    assert acct.holding('FPT').total == 1000

    acct.cash_ledger.accrue_interest(T2_1300)
    assert acct.cash().interest_accrued == (Decimal('96000000')
                                            * Decimal('0.0005') * 2)


def test_a_request_by_order_id_spans_every_tranche_of_a_partial_fill():
    """A partially filled sell produces one tranche per fill, and they settle
    separately. Naming the order draws on all of them, earliest-settling
    first -- the shortest-lived, cheapest advance is used up first, which is a
    DECLARED choice: no source states the recovery order."""
    ledger = cash_ledger()
    later = datetime(2022, 3, 17, 13, 0)
    ledger.credit_pending(Decimal('4000000'), later, T0, OrderId('S'))
    ledger.credit_pending(Decimal('6000000'), T2_1300, T0, OrderId('S'))
    ledger.credit_pending(Decimal('9000000'), T2_1300, T0, OrderId('OTHER'))

    drawn = ledger.request_advance(T0, Decimal('7000000'),
                                   order_id=OrderId('S'))

    assert [a.amount for a in drawn] == [Decimal('6000000'),
                                         Decimal('1000000')]
    assert [a.settles_at for a in drawn] == [T2_1300, later]
    assert ledger.advanced() == Decimal('7000000')
    assert ledger.advanceable(order_id=OrderId('OTHER')) == Decimal('9000000')


def test_a_tranche_read_from_an_older_cash_view_still_names_the_same_parcel():
    """Tranches are matched on (amount, settles_at, source_order_id) -- their
    economic identity, fixed the moment the sale fills -- not on object
    identity. Tier 1 replaced the tranche object on every accrual, so no
    caller-held tranche stayed valid for longer than one call."""
    day_two = datetime(2022, 3, 15, 9, 30)
    ledger = cash_ledger()
    ledger.credit_pending(Decimal('10000000'), T2_1300, T0, OrderId('S'))

    # Read the parcel out *after* it is already financed, so the view the
    # caller is holding carries live accrual state and not just the credit.
    ledger.request_advance(T0, Decimal('1000000'))
    ledger.accrue_interest(day_two)
    stale = ledger.cash().pending_proceeds[0]
    assert stale.advanced is True
    assert stale.interest_accrued == Decimal('500')

    # Now the view moves under it: another day of interest, another draw.
    ledger.accrue_interest(datetime(2022, 3, 16, 9, 30))
    fresh = ledger.cash().pending_proceeds[0]
    assert fresh != stale
    assert fresh.interest_accrued > stale.interest_accrued

    drawn = ledger.request_advance(day_two, Decimal('2000000'), tranche=stale)
    assert drawn[0].amount == Decimal('2000000')
    assert ledger.advanced() == Decimal('3000000')
    assert ledger.advanceable(tranche=stale) == Decimal('7000000')


def test_a_tranche_that_has_reached_its_settlement_instant_is_not_advanceable():
    """There is nothing to advance *against* once the money is due: the
    advance is a bridge over the T+2 gap and outside that gap it is a loan."""
    ledger = cash_ledger()
    ledger.credit_pending(Decimal('10000000'), T2_1300, T0)

    assert ledger.advanceable(now=T0) == Decimal('10000000')
    assert ledger.advanceable(now=T2_1300) == Decimal('0')
    with pytest.raises(ValueError, match='nothing is advanceable'):
        ledger.request_advance(T2_1300)


def test_a_broker_that_does_not_offer_the_product_cannot_advance():
    """It is a licensable service requiring prior written SSC approval (Luat
    Chung khoan 54/2019 Art. 86(1)(b), rulebook 8.4), and the SSC has
    sanctioned firms for offering it without one. A firm that has not
    registered it simply cannot advance, whatever the mechanics say."""
    ledger = CashLedger(Decimal('0'), BrokerTerms(), EncumbranceLedger())
    ledger.credit_pending(Decimal('10000000'), T2_1300, T0)

    assert ledger.advanced() == Decimal('0')
    with pytest.raises(ValueError, match='does not offer ung truoc tien ban'):
        ledger.request_advance(T0)


def test_naming_both_a_tranche_and_an_order_id_is_refused():
    """The two selectors would have to be intersected, and a request that
    silently matched nothing because they disagreed is a quiet no-op."""
    ledger = cash_ledger()
    tranche = ledger.credit_pending(Decimal('10000000'), T2_1300, T0,
                                    OrderId('S'))
    with pytest.raises(ValueError, match='not both'):
        ledger.request_advance(T0, tranche=tranche, order_id=OrderId('S'))


def test_a_minimum_charge_is_a_floor_applied_once_at_recovery():
    """Rulebook 12.7 lists a per-firm minimum per advance and 8.3 quotes
    30,000 and 50,000 -- while flagging that Vietnamese fee schedules often
    quote thousand-dong, so the figure may be a thousandfold out. It is off by
    default for that reason, and when set it lands at recovery, which is where
    the rulebook puts the charge."""
    terms = AdvanceTerms.from_broker(ADVANCE_ON, auto_register=False,
                                     minimum_charge=Decimal('50000'))
    assert AdvanceTerms.from_broker(ADVANCE_ON).minimum_charge is None

    ledger = cash_ledger(advance_terms=terms)
    ledger.credit_pending(Decimal('1000000'), T2_1300, T0)
    ledger.request_advance(T0)

    # Accrual alone is the raw formula; the floor is not applied per day.
    assert ledger.accrue_interest(T2_1300) == Decimal('1000')
    ledger.settle_due(T2_1300)
    assert ledger.cash().interest_accrued == Decimal('50000')


def test_a_repaid_advance_stays_itemised_after_its_tranche_is_gone():
    """The interest on a closed advance is a real cost. ``advanced()`` must
    forget it -- it is not spendable money -- and the itemisation must not."""
    ledger = cash_ledger()
    ledger.credit_pending(Decimal('10000000'), T2_1300, T0, OrderId('S'))
    ledger.request_advance(T0)
    ledger.settle_due(T2_1300)

    assert ledger.advances() == ()
    closed = ledger.advances(include_repaid=True)
    assert len(closed) == 1
    assert isinstance(closed[0], SaleAdvance)
    assert closed[0].is_outstanding is False
    assert closed[0].repaid_at == T2_1300
    assert closed[0].days_accrued == 2
    assert closed[0].interest_accrued == Decimal('10000')
    assert closed[0].source_order_id == OrderId('S')


def test_auto_registration_still_advances_the_whole_tranche_at_the_fill():
    """Rulebook 8.3's mechanics row: "On registration the advance is credited
    to buying power immediately after the sell order fills on T". Tier 1's
    behaviour, unchanged -- but now it is a SaleAdvance record with a
    principal and a repayment instant, not a flag."""
    ledger = CashLedger(Decimal('0'), ADVANCE_ON, EncumbranceLedger())
    assert ledger.advance_terms.auto_register is True

    tranche = ledger.credit_pending(Decimal('10000000'), T2_1300, T0,
                                    OrderId('S'))
    assert tranche.advanced is True
    assert ledger.advanced() == Decimal('10000000')
    assert ledger.advanceable() == Decimal('0')

    only = ledger.advances()[0]
    assert only.amount == Decimal('10000000')
    assert only.taken_at == T0
    assert only.settles_at == T2_1300


def test_every_unsourced_advance_default_is_declared():
    """The counterpart of BrokerTerms.PROVENANCE. Nothing on this object is
    sourced to a document, and a field that acquired a default without
    acquiring a provenance line is how an assumption becomes a fact."""
    fields = {'daily_rate', 'annualisation_basis', 'max_advanceable_fraction',
              'minimum_charge', 'auto_register'}
    assert set(AdvanceTerms.PROVENANCE) == fields
    assert 'DECLARED' in AdvanceTerms.PROVENANCE['annualisation_basis']
    assert 'UNSOURCED' in AdvanceTerms.PROVENANCE['minimum_charge']
