"""The charge table -- fees and taxes, per venue, dated, itemised.

Every test names the rule it pins, and every number comes from
``docs/reference/citable/vn-exchange-rulebook-2020-2026.md`` with its citation.
Nothing is pinned here that does not appear there.

Three claims run through the file:

1. **A charge is ``(venue, charge class, side, date)``**, not a constant. The
   same call on two dates gives two answers, and a test that only checked
   today's value would pass against the config-at-load singleton the design
   forbids.
2. **The derivatives transfer tax is levied on the margined value, not on
   notional**, and its base is linear in the VSD initial margin ratio -- so
   the tax and the margin requirement must read one series. Two inconsistent
   ratios in one system is the failure this module exists to prevent, and it
   is refused rather than reported.
3. **Broker commission tiers on the day's total per account**, so its rate is
   not knowable at fill time. It is levied at the daily close, and the
   per-order minimum is a clamp on each order rather than on the day.
"""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.core.order import OrderType, Side
from plutus.market import margin
from plutus.market.protocol import Order
from plutus.market.session import charges as C
from plutus.market.session import ledgers
from plutus.market.session.deposit import resolve_initial_margin_rate
from plutus.market.session.rulebook import Rulebook, UnresolvedRule
from plutus.market.session.types import (BrokerProfile, ChargeBase,
                                         ChargeClass, ChargeRule, ChargeSide,
                                         Confidence, DebitedAt, Fill,
                                         FillEvidence, FillId, LeviedBy,
                                         OrderId, Pool, Venue)

BOOK = Rulebook()

#: An ordinary trading instant in 2023: the exchange fee is at its permanent
#: 0.027% level, the VSDC clearing fee has been per-fill since 2022-01-01, and
#: the VSD initial margin ratio has been 17% since 2022-12-15. This is the
#: instant rulebook 12.8's worked round-trips are computed at.
TS = datetime(2023, 6, 15, 10, 0)

#: The VN30 futures multiplier: 100,000 VND per index point. Passed
#: explicitly everywhere, because government-bond futures use 10,000 and the
#: multiplier is a product fact rather than a venue fact (rulebook 12.1).
VN30F_MULTIPLIER = Decimal('100000')


def rules(ts: datetime = TS):
    return BOOK.at(ts)


def equity(side: Side = Side.SELL, *, quantity: int = 10000,
           price: str = '25.5', ts: datetime = TS,
           venue: Venue = Venue.HSX,
           cls_: ChargeClass = ChargeClass.EQUITY,
           ticker: str = 'HPG', order_id: str = 'A') -> C.ChargeContext:
    """Rulebook 12.8's equity example: 10,000 shares at 25,500 VND."""
    return C.ChargeContext(
        venue=venue, charge_class=cls_, side=side, quantity=quantity,
        price=Decimal(price), ts=ts, ticker=ticker,
        order_id=OrderId(order_id))


def future(side: Side = Side.BUY, *, contracts: int = 1,
           price: str = '1100', ts: datetime = TS,
           ticker: str = 'VN30F2306',
           multiplier: Decimal = VN30F_MULTIPLIER,
           order_id: str = 'F') -> C.ChargeContext:
    """Rulebook 12.8's futures example: one VN30 contract at 1,100 points."""
    return C.ChargeContext(
        venue=Venue.HNXDS, charge_class=ChargeClass.FUTURE, side=side,
        quantity=contracts, price=Decimal(price), ts=ts, ticker=ticker,
        multiplier=multiplier, order_id=OrderId(order_id))


def by_kind(levied):
    return {lc.charge.kind: lc for lc in levied}


# --------------------------------------------------------------------------
# The money bases: four of them, and the fourth is the point
# --------------------------------------------------------------------------

def test_a_cash_venue_is_quoted_in_thousands_of_dong():
    """`CURRENCY_UNIT[HSX] == 1000` (rulebook 12.1), so 10,000 shares at 25.5
    move 255,000,000 VND. A missing factor of 1,000 is invisible in a ratio
    and fatal in a balance."""
    assert C.trade_value(Venue.HSX, 10000, Decimal('25.5')) == Decimal(
        '255000000')


def test_the_cash_conversion_refuses_hnxds():
    """`CURRENCY_UNIT['HNXDS'] == 1` is not a multiplier (rulebook 12.1):
    index futures quote points against a contract multiplier. One conversion
    cannot serve both, so the cash one refuses rather than returning the
    notional divided by 100,000."""
    with pytest.raises(ValueError, match='not a multiplier'):
        C.trade_value(Venue.HNXDS, 1, Decimal('1100'))


def test_the_futures_multiplier_is_a_product_fact_not_a_venue_fact():
    """VN30F applies 100,000 VND per point; the government-bond contracts
    quote VND on a 100,000 face and use 10,000. Rulebook 12.1 gives this as
    "a second reason the field cannot be per-venue", so the multiplier is a
    parameter and never read off HNXDS."""
    assert C.derivatives_notional(1, Decimal('1100'), VN30F_MULTIPLIER) == (
        Decimal('110000000'))
    assert C.derivatives_notional(1, Decimal('1100'), Decimal('10000')) == (
        Decimal('11000000'))


def test_the_derivatives_tax_base_is_not_full_notional():
    """Rulebook 8.1, quoting Cong van 11133/BTC-CST: the per-transfer price is
    `settlement price x multiplier x contracts x initial margin ratio / 2`.
    At a 17% ratio that is 8.5% of notional, so a model that taxes notional
    over-charges by 11.8x -- the single subtlest number in the fee domain."""
    notional = Decimal('110000000')
    base = C.margined_value(1, Decimal('1100'), VN30F_MULTIPLIER,
                            Decimal('0.17'))
    assert base == Decimal('9350000')
    assert base == notional * Decimal('0.17') / 2
    assert base != notional


def test_a_zero_margin_ratio_is_refused_rather_than_deleting_the_tax():
    """The base is linear in the ratio, so a zero would make the tax vanish
    silently. The published series is 10 / 13 / 17 percent and never zero, so
    a zero means the series was not read -- which must be loud."""
    with pytest.raises(ValueError, match='LINEAR|linear in it|must be positive'):
        C.margined_value(1, Decimal('1100'), VN30F_MULTIPLIER, Decimal('0'))


def test_one_charge_base_splits_three_ways_by_venue_and_row():
    """`ChargeBase.TRADE_VALUE` is how the rulebook words three different
    bases. The exchange service price is a fraction of the cash trade value on
    HSX and of the futures notional on HNXDS; the derivatives transfer tax is
    a fraction of neither. Collapsing them is how a model ends up taxing
    notional."""
    fee = ChargeRule(charge_id='exchange_service', base=ChargeBase.TRADE_VALUE,
                     side=ChargeSide.BOTH, levied_by=LeviedBy.EXCHANGE,
                     debited_at=DebitedAt.FILL, pool=Pool.SECURITIES,
                     applies_to=frozenset(ChargeClass), rate=Decimal('0.00027'))
    pit = ChargeRule(charge_id=C.DERIVATIVES_PIT_CHARGE_ID,
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.STATE, debited_at=DebitedAt.FILL,
                     pool=Pool.DERIVATIVES,
                     applies_to=frozenset({ChargeClass.FUTURE}))
    assert C.basis_for(fee, Venue.HSX) is C.ChargeBasis.TRADE_VALUE
    assert C.basis_for(fee, Venue.HNXDS) is C.ChargeBasis.NOTIONAL
    assert C.basis_for(pit, Venue.HNXDS) is C.ChargeBasis.MARGINED_VALUE


# --------------------------------------------------------------------------
# The dated table, resolved through the rulebook
# --------------------------------------------------------------------------

def test_the_equity_transfer_tax_is_sell_side_only():
    """Rulebook 8.1 and 12.3: the 0.1% PIT is charged on the gross transfer
    price of a SALE and the buy side pays none. It is withheld at source, so a
    sale credits cash net -- "without it every sale is wrong by more than most
    commissions". Side is an axis of the table for this one row above all."""
    sold = by_kind(C.assess(rules(), None, equity(Side.SELL)))
    bought = by_kind(C.assess(rules(), None, equity(Side.BUY)))
    assert sold['pit_securities_transfer'].charge.amount == Decimal('255000')
    assert 'pit_securities_transfer' not in bought


def test_the_exchange_trading_fee_is_dated_and_not_a_constant():
    """0.03% under TT 127/2018 and 0.027% from 2020-03-19 under TT 14/2020
    (rulebook 8.2, 12.4). Secondary sources quote 0.027% as "the" fee and
    mis-cost any 2020-Q1 backtest by 11%."""
    early = by_kind(C.assess(rules(datetime(2020, 3, 18, 10, 0)), None,
                             equity(Side.BUY, ts=datetime(2020, 3, 18, 10, 0))))
    late = by_kind(C.assess(rules(datetime(2020, 3, 19, 10, 0)), None,
                            equity(Side.BUY, ts=datetime(2020, 3, 19, 10, 0))))
    assert early['exchange_service_hsx_equity'].charge.amount == Decimal('76500')
    assert late['exchange_service_hsx_equity'].charge.amount == Decimal('68850')


def test_an_etf_takes_a_lower_exchange_fee_than_a_share_on_the_same_venue():
    """0.018% for ETF units and covered warrants against 0.027% for ordinary
    shares (rulebook 12.4). Charge class is an axis of the table, not a label:
    same venue, same date, same notional, different fee."""
    share = by_kind(C.assess(rules(), None, equity(Side.BUY)))
    etf = by_kind(C.assess(rules(), None,
                           equity(Side.BUY, cls_=ChargeClass.ETF,
                                  ticker='E1VFVN30')))
    assert share['exchange_service_hsx_equity'].charge.amount == Decimal('68850')
    assert etf['exchange_service_hsx_etf_cw'].charge.amount == Decimal('45900')


def test_the_vsdc_derivatives_charge_changes_shape_on_2022_01_01():
    """Rulebook 8.2 and 12.5, and the correction is worth 3 years 4 months:
    the position-management fee (per open contract per account per DAY) ends
    2021-12-31 and the clearing fee (per novated contract, per FILL) begins
    2022-01-01. A holding basis becomes a trade basis, so a per-fill pass sees
    nothing before the boundary and 2,550d after it."""
    before = by_kind(C.assess(rules(datetime(2021, 12, 31, 10, 0)), None,
                              future(ts=datetime(2021, 12, 31, 10, 0))))
    after = by_kind(C.assess(rules(datetime(2022, 1, 4, 10, 0)), None,
                             future(ts=datetime(2022, 1, 4, 10, 0))))
    assert 'vsdc_derivatives_clearing' not in before
    assert 'vsdc_derivatives_position_management' not in before
    assert after['vsdc_derivatives_clearing'].charge.amount == Decimal('2550')


def test_a_holding_charge_is_never_priced_into_a_fill():
    """Custody is monthly per security and the VSD position fee accrued per
    open contract per day (rulebook 12.2, 12.5). No per-fill model can express
    either -- a fill does not know how many month-ends a holding will cross --
    so they are skipped rather than approximated."""
    custody = ChargeRule(
        charge_id='vsdc_custody_equity', base=ChargeBase.MONTHLY_PER_SECURITY,
        side=ChargeSide.NONE, levied_by=LeviedBy.VSD,
        debited_at=DebitedAt.MONTHLY, pool=Pool.SECURITIES,
        applies_to=frozenset(ChargeClass), amount=Decimal('0.27'))
    assert C.levy(custody, equity()) is None
    assert C.basis_for(custody, Venue.HSX) not in C.FILL_BASES


def test_every_exchange_side_charge_carries_a_dated_citation():
    """Design section 6: exchange rules are gazetted, dated and identical for
    everyone, and the traceability is the rulebook's whole claim. A state,
    exchange or depository row that could not name its document would forfeit
    it, so the citation travels on the levied charge."""
    levied = C.assess(rules(), None, equity(Side.SELL)) + C.assess(
        rules(), None, future())
    assert levied
    for lc in levied:
        assert lc.levied_by is not LeviedBy.BROKER
        assert lc.citation is not None, lc.charge.kind
        assert lc.citation.effective_from is not None
        assert isinstance(lc.citation.confidence, Confidence)


def test_a_charge_names_what_levied_it_and_under_what_rule():
    """Design section 6.1: charges are itemised on the result, never netted
    into a price, and each carries what levied it and under what rule. The
    difference between "brokers charge 0.15%" and "you were charged 255,000
    dong on 2023-06-15 under the personal income tax"."""
    pit = by_kind(C.assess(rules(), None, equity(Side.SELL)))[
        'pit_securities_transfer']
    assert pit.levied_by is LeviedBy.STATE
    assert pit.rule.charge_id == 'pit_securities_transfer'
    assert pit.charge.pool is Pool.SECURITIES
    assert pit.charge.ticker == 'HPG'
    assert pit.charge.order_id == OrderId('A')
    assert pit.charge.ts == TS
    assert pit.basis is C.ChargeBasis.TRADE_VALUE
    assert pit.basis_value == Decimal('255000000')


def test_charge_amounts_are_rounded_to_whole_dong_as_a_declared_choice():
    """A MODELLING CHOICE, not a sourced rule: rulebook 12.1 records that no
    source states a rounding rule for any fee or tax. Half-up to whole dong,
    and any result sensitive to it must say so."""
    ctx = equity(Side.SELL, quantity=100, price='95.55')   # 9,555,000 VND
    fee = by_kind(C.assess(rules(), None, ctx))['exchange_service_hsx_equity']
    assert fee.basis_value == Decimal('9555000')
    assert fee.charge.amount == Decimal('2580')            # 2,579.85 rounded up


# --------------------------------------------------------------------------
# The derivatives tax: the margined base, and the one margin series
# --------------------------------------------------------------------------

def test_the_derivatives_tax_is_levied_on_the_margined_value():
    """Rulebook 12.8's worked figure: one VN30 contract at 1,100 points in
    2023 (IM 17%) pays 0.1% of 9,350,000 = 9,350 VND per leg. Taxing the
    110,000,000 notional instead would charge 110,000 -- 11.8x too much."""
    pit = by_kind(C.assess(rules(), None, future()))[C.DERIVATIVES_PIT_CHARGE_ID]
    assert pit.basis is C.ChargeBasis.MARGINED_VALUE
    assert pit.basis_value == Decimal('9350000')
    assert pit.rate == C.DERIVATIVES_PIT_RATE == Decimal('0.001')
    assert pit.charge.amount == Decimal('9350')
    assert pit.charge.amount != Decimal('110000')


def test_the_derivatives_tax_moves_with_the_dated_margin_ratio():
    """The base is LINEAR in the VSD initial margin ratio, which stepped from
    13% to 17% on 2022-12-15 (rulebook 6.3, 8.1). So the tax on an unchanged
    contract at an unchanged price is a different number on the two sides of
    that date -- 7,150 against 9,350. A tax model with a hard-coded ratio
    cannot produce both."""
    before = datetime(2022, 12, 14, 10, 0)
    after = datetime(2022, 12, 15, 10, 0)
    lo = by_kind(C.assess(rules(before), None,
                          future(ts=before, ticker='VN30F2212')))
    hi = by_kind(C.assess(rules(after), None,
                          future(ts=after, ticker='VN30F2212')))
    assert lo[C.DERIVATIVES_PIT_CHARGE_ID].charge.amount == Decimal('7150')
    assert hi[C.DERIVATIVES_PIT_CHARGE_ID].charge.amount == Decimal('9350')


def test_the_tax_and_the_margin_requirement_read_one_series(monkeypatch):
    """Rulebook 8.1, in bold: "One dated VSD series must feed both margin.py
    and the tax model, or the paper carries two mutually inconsistent margin
    ratios."

    Pinned by moving the series and checking that BOTH move. If the tax ever
    grows a ratio of its own, the levied amount stops tracking
    `deposit.resolve_initial_margin_rate` and this fails."""
    fake = ((date(2017, 8, 10), Decimal('0.25')),)
    monkeypatch.setattr(margin, 'VSD_INITIAL_MARGIN', fake)

    from_deposit = resolve_initial_margin_rate(None, 'VN30F2306', TS)
    from_rulebook = rules().initial_margin_rate('VN30F2306')
    assert from_deposit == from_rulebook == Decimal('0.25')

    pit = by_kind(C.assess(rules(), None, future()))[C.DERIVATIVES_PIT_CHARGE_ID]
    # 110,000,000 x 0.25 / 2 = 13,750,000 -> 0.1% = 13,750
    assert pit.basis_value == Decimal('110000000') * from_deposit / 2
    assert pit.charge.amount == Decimal('13750')


def test_a_second_margin_ratio_in_one_run_is_refused():
    """The failure mode the rulebook names, made a runtime error rather than a
    silent 30% mispricing. `RuleSet.charges` serves the row with the rate
    folded to `0.0005 x IM`; this module prices the same charge from the
    statutory formula and the ratio resolved for this contract. The two agree
    if and only if both read the same series, so disagreement means two
    ratios are live and the run must stop."""
    stale = ChargeRule(
        charge_id=C.DERIVATIVES_PIT_CHARGE_ID, base=ChargeBase.TRADE_VALUE,
        side=ChargeSide.BOTH, levied_by=LeviedBy.STATE,
        debited_at=DebitedAt.FILL, pool=Pool.DERIVATIVES,
        applies_to=frozenset({ChargeClass.FUTURE}), venue=Venue.HNXDS,
        rate=Decimal('0.0005') * Decimal('0.13'))     # the pre-2022-12-15 ratio
    ctx = C.ChargeContext(
        venue=Venue.HNXDS, charge_class=ChargeClass.FUTURE, side=Side.BUY,
        quantity=1, price=Decimal('1100'), ts=TS, ticker='VN30F2306',
        multiplier=VN30F_MULTIPLIER, initial_margin_rate=Decimal('0.17'))
    with pytest.raises(ValueError, match='two different margin ratios'):
        C.levy(stale, ctx)


def test_the_folded_rate_and_the_statutory_formula_agree_at_every_step():
    """The same check, run against the real rulebook at each margin step
    rather than against a planted row. This is what makes the guard a drift
    detector instead of a tautology: it passes only because `RuleSet.charges`
    and this module resolve the ratio from one place."""
    for ts, expected in ((datetime(2021, 6, 1, 10, 0), Decimal('0.13')),
                         (datetime(2023, 6, 15, 10, 0), Decimal('0.17'))):
        rs = rules(ts)
        row = {r.charge_id: r for r in rs.charges(Venue.HNXDS,
                                                  ChargeClass.FUTURE)}
        folded = row[C.DERIVATIVES_PIT_CHARGE_ID].rate
        assert folded == Decimal('0.0005') * expected
        levied = C.levy(
            row[C.DERIVATIVES_PIT_CHARGE_ID],
            replace(future(ts=ts, ticker='VN30F2306'),
                    initial_margin_rate=rs.initial_margin_rate('VN30F2306')))
        assert levied is not None
        assert levied.charge.amount == C.to_dong(
            folded * Decimal('110000000'))


def test_the_derivatives_tax_is_charged_on_both_legs_and_at_maturity():
    """Rulebook 8.1 and 12.3: taxable income is determined when the order is
    matched -- opening leg and closing leg alike -- "or at contract
    maturity". A position carried into final settlement is never matched out,
    so a fills-only model under-charges every held-to-expiry contract by one
    leg."""
    opened = by_kind(C.assess(rules(), None, future(Side.BUY)))
    closed = by_kind(C.assess(rules(), None, future(Side.SELL)))
    matured = by_kind(C.assess_at_maturity(rules(), future(Side.SELL)))
    assert opened[C.DERIVATIVES_PIT_CHARGE_ID].charge.amount == Decimal('9350')
    assert closed[C.DERIVATIVES_PIT_CHARGE_ID].charge.amount == Decimal('9350')
    assert matured[C.DERIVATIVES_PIT_CHARGE_ID].charge.amount == Decimal('9350')


def test_maturity_levies_the_tax_and_not_the_matching_fees():
    """The exchange fee is per MATCHED contract and the clearing fee per
    NOVATED contract. No source read says either is charged on a final cash
    settlement, so levying them would invent a charge -- and inventing one is
    worse than declaring the gap."""
    assert [lc.charge.kind for lc in C.assess_at_maturity(
        rules(), future(Side.SELL))] == [C.DERIVATIVES_PIT_CHARGE_ID]


def test_maturity_refuses_a_cash_venue():
    """Equity has no maturity; the row `assess_at_maturity` exists for is
    HNXDS-only. Silently returning nothing would hide a caller's mistake."""
    with pytest.raises(ValueError, match='do not mature'):
        C.assess_at_maturity(rules(), equity())


def test_a_government_bond_future_refuses_rather_than_borrowing_the_index_ratio():
    """Rulebook 6.3: government-bond futures carry a DELIVERY margin ratio in
    place of initial margin and its value is not published. Since the tax base
    is linear in that ratio, applying the index series to them would invent a
    number -- so the honest answer is UnresolvedRule."""
    gb = C.ChargeContext(
        venue=Venue.HNXDS, charge_class=ChargeClass.FUTURE, side=Side.BUY,
        quantity=1, price=Decimal('100'), ts=TS, ticker='GB05F2306',
        multiplier=Decimal('10000'))
    with pytest.raises(UnresolvedRule):
        C.assess(rules(), None, gb)


def test_the_tax_base_refuses_a_trade_with_no_multiplier():
    """100,000 is right for VN30F and 10x wrong for the government-bond
    contracts, so a default would be a silent 10x error on one product
    family."""
    ctx = C.ChargeContext(
        venue=Venue.HNXDS, charge_class=ChargeClass.FUTURE, side=Side.BUY,
        quantity=1, price=Decimal('1100'), ts=TS, ticker='VN30F2306')
    with pytest.raises(ValueError, match='no contract multiplier'):
        _ = ctx.notional


# --------------------------------------------------------------------------
# Broker commission: tiered on the day, minimum on the order
# --------------------------------------------------------------------------

#: SSI's real online equity schedule, effective 2025-10-10 (rulebook 8.3):
#: 0.25% below 100m dong/day, 0.30% from 100m to 500m, 0.25% above. The
#: NON-MONOTONE middle band is confirmed on SSI's own page and is explicitly
#: not a transcription error. UNSOURCED as a general market value -- it is one
#: firm's commercial term.
SSI = C.CommissionSchedule(
    venue=Venue.HSX,
    tiers=(C.CommissionTier(Decimal('0'), rate=Decimal('0.0025')),
           C.CommissionTier(Decimal('100000000'), rate=Decimal('0.0030')),
           C.CommissionTier(Decimal('500000000'), rate=Decimal('0.0025'))),
)


def test_the_commission_tier_is_the_days_total_not_the_orders():
    """Rulebook 8.3, verbatim: "the tiering variable is DAILY value per
    account, not per-order value. A commission model that tiers per order will
    misprice." Two 60m orders each sit in the 0.25% band on their own; the
    day's 120m puts BOTH in the 0.30% band, so each pays 180,000 and not
    150,000."""
    meter = C.DailyTurnover()
    for oid in ('A', 'B'):
        meter.add(equity(Side.BUY, quantity=1000, price='60', order_id=oid))
    assert meter.value_on(TS.date()) == Decimal('120000000')

    levied = C.assess_daily((SSI,), meter, TS.date())
    assert [lc.charge.amount for lc in levied] == [Decimal('180000'),
                                                   Decimal('180000')]
    assert all(lc.rate == Decimal('0.0030') for lc in levied)


def test_a_non_monotone_tier_table_is_accepted():
    """SSI really charges 0.25 / 0.30 / 0.25. Any code that assumes commission
    falls with volume is wrong about a live schedule, so the schedule requires
    increasing THRESHOLDS and says nothing about the rates."""
    assert SSI.tier_at(Decimal('50000000')).rate == Decimal('0.0025')
    assert SSI.tier_at(Decimal('200000000')).rate == Decimal('0.0030')
    assert SSI.tier_at(Decimal('900000000')).rate == Decimal('0.0025')


def test_the_per_order_minimum_is_a_clamp_on_each_order_not_on_the_day():
    """"Some firms impose a minimum charge per order" (rulebook 8.3). Three
    tiny orders under a 30,000d minimum cost 90,000, not 30,000 -- clamping
    the day's total instead under-charges by twice the minimum here and by
    (n-1) times it in general."""
    sched = C.CommissionSchedule(
        venue=Venue.HSX, tiers=SSI.tiers,
        minimum_per_order=Decimal('30000'))
    meter = C.DailyTurnover()
    for oid in ('A', 'B', 'C'):
        meter.add(equity(Side.BUY, quantity=100, price='1', order_id=oid))

    levied = C.assess_daily((sched,), meter, TS.date())
    assert [lc.charge.amount for lc in levied] == [Decimal('30000')] * 3
    assert sum(lc.charge.amount for lc in levied) == Decimal('90000')


def test_a_tiered_commission_is_not_levied_at_the_fill():
    """"The applicable rate is only known at END OF DAY" -- rulebook 8.3 calls
    this the single most useful implementation finding in the fee domain. A
    tiered schedule is DebitedAt.DAILY, so the fill pass leaves it alone and
    the daily pass levies it."""
    assert SSI.debited_at is DebitedAt.DAILY
    at_fill = [lc.charge.kind for lc in C.assess(
        rules(), None, equity(Side.BUY), commission=(SSI,))]
    assert SSI.charge_id not in at_fill


def test_a_flat_commission_is_still_levied_at_the_fill():
    """A single-tier schedule IS knowable at fill time, so deferring it would
    postpone a charge for no reason. The daily treatment is bought by the
    tiering, not by being a broker row."""
    flat = C.CommissionSchedule(
        venue=Venue.HSX,
        tiers=(C.CommissionTier(Decimal('0'), rate=Decimal('0.0015')),))
    assert flat.debited_at is DebitedAt.FILL
    levied = by_kind(C.assess(rules(), None, equity(Side.BUY),
                              commission=(flat,)))
    assert levied[flat.charge_id].charge.amount == Decimal('382500')


def test_the_estimate_reserves_at_the_dearest_tier():
    """Design section 7.0: estimated charges sit inside the buy encumbrance so
    `available` stays honest. The tier depends on a day that has not happened
    when the order is accepted, so the reservation takes the dearest band --
    over-reserving is the conservative direction and the reservation is
    released in full at the terminal edge either way."""
    assert SSI.worst_case_tier().rate == Decimal('0.0030')
    # 255,000,000 x (0.00027 exchange + 0.0030 commission)
    assert C.estimate(rules(), None, equity(Side.BUY),
                      commission=(SSI,)) == Decimal('833850')


def test_a_schedule_shadows_a_flat_profile_row_for_the_same_venue():
    """Both describe the same broker's commission on the same venue, so
    levying both would double-charge every trade."""
    flat = ChargeRule(
        charge_id='broker.commission.hsx', base=ChargeBase.TRADE_VALUE,
        side=ChargeSide.BOTH, levied_by=LeviedBy.BROKER,
        debited_at=DebitedAt.FILL, pool=Pool.SECURITIES,
        applies_to=frozenset(ChargeClass), venue=Venue.HSX,
        rate=Decimal('0.0015'))
    profile = BrokerProfile(name='double', commission=(flat,))
    rows = C.schedule(rules(), profile, equity(Side.BUY), commission=(SSI,))
    assert [r.charge_id for r in rows].count('broker.commission.hsx') == 1


def test_commission_tiers_must_start_at_zero_and_increase():
    """A schedule that prices nothing below its first threshold would silently
    make small orders free, and two tiers starting at the same place have no
    defined winner. Rates may do what they like; thresholds may not."""
    with pytest.raises(ValueError, match='must start at 0'):
        C.CommissionSchedule(
            venue=Venue.HSX,
            tiers=(C.CommissionTier(Decimal('100'), rate=Decimal('0.0025')),))
    with pytest.raises(ValueError, match='strictly increasing'):
        C.CommissionSchedule(
            venue=Venue.HSX,
            tiers=(C.CommissionTier(Decimal('0'), rate=Decimal('0.0025')),
                   C.CommissionTier(Decimal('0'), rate=Decimal('0.0030'))))


def test_the_statutory_commission_cap_is_reported_never_enforced():
    """The cap is a dated exchange-side rule -- 0.5% to 2021-12-31, 0.45%
    after (rulebook 8.3, 12.7) -- so it is passed in rather than held on a
    broker object. Silently clamping a configured rate would make a run report
    a commission the caller never set."""
    greedy = C.CommissionSchedule(
        venue=Venue.HSX,
        tiers=(C.CommissionTier(Decimal('0'), rate=Decimal('0.006')),))
    assert greedy.check_against_cap(cap_rate=Decimal('0.0045'))
    assert greedy.check_against_cap(cap_rate=Decimal('0.0070')) == ()
    # Reported, not applied: the rate is still what the caller configured.
    assert greedy.tier_at(Decimal('0')).rate == Decimal('0.006')


def test_a_zero_commission_is_a_real_schedule_and_not_a_misconfiguration():
    """TT 128/2018 removed the FLOOR on 2019-02-15, "which is what enabled the
    2020-2021 zero-fee price war (DNSE, Pinetree)". A model that treats 0 as
    missing config cannot represent those brokers."""
    free = C.CommissionSchedule(
        venue=Venue.HSX,
        tiers=(C.CommissionTier(Decimal('0'), rate=Decimal('0')),))
    levied = by_kind(C.assess(rules(), None, equity(Side.BUY),
                              commission=(free,)))
    assert levied[free.charge_id].charge.amount == Decimal('0')


def test_derivatives_commission_tiers_on_contracts_not_on_value():
    """Rulebook 8.3: the derivatives shape is a fixed amount per contract
    tiered on contracts matched per DAY -- VPS 2,000d below 200 contracts and
    1,000d at or above. A percentage-of-value model has the wrong shape
    entirely, which is why `base` and `tier_variable` are separate fields."""
    vps = C.CommissionSchedule(
        venue=Venue.HNXDS, base=ChargeBase.PER_CONTRACT,
        tier_variable=C.TierVariable.DAILY_CONTRACTS_PER_ACCOUNT,
        tiers=(C.CommissionTier(Decimal('0'), amount=Decimal('2000')),
               C.CommissionTier(Decimal('200'), amount=Decimal('1000'))),
        applies_to=frozenset({ChargeClass.FUTURE}))
    meter = C.DailyTurnover()
    meter.add(future(contracts=150, order_id='F1'))
    meter.add(future(contracts=150, order_id='F2'))
    assert meter.contracts_on(TS.date()) == 300

    levied = C.assess_daily((vps,), meter, TS.date())
    assert [lc.charge.amount for lc in levied] == [Decimal('150000'),
                                                   Decimal('150000')]


def test_the_commission_provenance_says_every_number_is_an_assumption():
    """The commercial counterpart of `BrokerTerms.PROVENANCE`. Exchange rules
    are gazetted and cited; broker terms are not, and each default must SAY it
    is an assumption rather than leaving a reader to infer it."""
    assert 'UNSOURCED' in C.CommissionSchedule.PROVENANCE['tiers']
    assert 'UNSOURCED' in C.CommissionSchedule.PROVENANCE['minimum_per_order']
    assert 'MODELLING CHOICE' in C.CommissionSchedule.PROVENANCE[
        'per_fill_attribution']
    assert SSI.rule_at(SSI.tiers[0]).citation is None
    assert SSI.rule_at(SSI.tiers[0]).levied_by is LeviedBy.BROKER


def test_a_config_row_reads_rates_through_str_not_through_float():
    """`Decimal(0.0025)` is not 0.0025, and a JSON config delivers floats.
    The flat form of design section 6 collapses to one tier at zero, so an
    existing config keeps its existing per-fill behaviour."""
    flat = C.CommissionSchedule.from_config(
        {'venue': 'HSX', 'base': 'trade_value', 'rate': 0.0015})
    assert flat.tiers == (C.CommissionTier(Decimal('0'),
                                           rate=Decimal('0.0015')),)
    assert flat.debited_at is DebitedAt.FILL

    tiered = C.CommissionSchedule.from_config(
        {'venue': 'HSX', 'tiers': [{'from': 0, 'rate': 0.0025},
                                   {'from': 100000000, 'rate': 0.003}],
         'min_per_order': 30000})
    assert tiered.debited_at is DebitedAt.DAILY
    assert tiered.minimum_per_order == Decimal('30000')
    assert tiered.tier_at(Decimal('200000000')).rate == Decimal('0.003')


def test_a_partially_filled_order_pays_one_commission_on_its_whole_value():
    """Commission is charged on the order, and an order that filled in three
    parcels has one value. Pricing each parcel separately would apply the
    per-order minimum three times."""
    sched = C.CommissionSchedule(
        venue=Venue.HSX, tiers=SSI.tiers, minimum_per_order=Decimal('30000'))
    meter = C.DailyTurnover()
    for _ in range(3):
        meter.add(equity(Side.BUY, quantity=1000, price='20', order_id='A'))
    levied = C.assess_daily((sched,), meter, TS.date())
    assert len(levied) == 1
    # 3 x 1,000 x 20,000 = 60,000,000 at the 0.25% band
    assert levied[0].basis_value == Decimal('60000000')
    assert levied[0].charge.amount == Decimal('150000')


# --------------------------------------------------------------------------
# The rulebook's own worked round-trips
# --------------------------------------------------------------------------

def test_the_worked_equity_round_trip_matches_the_rulebook():
    """Rulebook 12.8, verbatim: 10,000 HSX shares at 25,500 VND in 2023 --
    exchange fee 68,850 per leg, PIT 255,000 on the sell leg only, commission
    2 x 0.25%. "A fee model that omits the PIT understates round-trip cost by
    about 15%; one that omits commission understates it by about 76%.\""""
    quarter_pct = C.CommissionSchedule(
        venue=Venue.HSX,
        tiers=(C.CommissionTier(Decimal('0'), rate=Decimal('0.0025')),))
    buy = by_kind(C.assess(rules(), None, equity(Side.BUY),
                           commission=(quarter_pct,)))
    sell = by_kind(C.assess(rules(), None, equity(Side.SELL),
                            commission=(quarter_pct,)))

    assert buy['exchange_service_hsx_equity'].charge.amount == Decimal('68850')
    assert sell['exchange_service_hsx_equity'].charge.amount == Decimal('68850')
    assert sell['pit_securities_transfer'].charge.amount == Decimal('255000')
    assert buy[quarter_pct.charge_id].charge.amount == Decimal('637500')
    assert sell[quarter_pct.charge_id].charge.amount == Decimal('637500')

    total = sum(lc.charge.total for lc in
                (*buy.values(), *sell.values()))
    assert total == Decimal('1667700')     # 12.8's 1,670,400 less custody


def test_the_worked_futures_round_trip_matches_the_rulebook():
    """Rulebook 12.8: one VN30 contract opened and closed the same day in 2023
    at 1,100 points with a 17% margin ratio -- 5,400 exchange + 5,100 clearing
    + 18,700 tax + 4,000 commission = 33,200 VND. Under the pre-correction
    dating of the clearing fee this same round trip was charged 2,550 once
    instead of twice, a 7.7% understatement for every day of 2022-01-01 ->
    2025-04-28."""
    two_thousand = C.CommissionSchedule(
        venue=Venue.HNXDS, base=ChargeBase.PER_CONTRACT,
        tier_variable=C.TierVariable.NONE,
        tiers=(C.CommissionTier(Decimal('0'), amount=Decimal('2000')),),
        applies_to=frozenset({ChargeClass.FUTURE}))
    legs = (C.assess(rules(), None, future(Side.BUY), commission=(two_thousand,))
            + C.assess(rules(), None, future(Side.SELL),
                       commission=(two_thousand,)))
    by = {}
    for lc in legs:
        by[lc.charge.kind] = by.get(lc.charge.kind, Decimal('0')) + lc.charge.total

    assert by['exchange_service_index_future'] == Decimal('5400')
    assert by['vsdc_derivatives_clearing'] == Decimal('5100')
    assert by[C.DERIVATIVES_PIT_CHARGE_ID] == Decimal('18700')
    assert by[two_thousand.charge_id] == Decimal('4000')
    assert sum(by.values()) == Decimal('33200')


# --------------------------------------------------------------------------
# The ledgers seam: one engine, not two
# --------------------------------------------------------------------------

def test_the_account_and_the_table_share_one_money_conversion():
    """`ledgers.trade_value` IS `charges.trade_value`, not a copy of it. A
    second implementation of the thousands-of-dong conversion is a second
    answer to what a trade costs, and the whole-dong rounding is a declared
    modelling choice that has to be made in exactly one place."""
    assert ledgers.trade_value is C.trade_value


def test_the_ledger_estimate_reserves_a_tiered_commission():
    """The buy encumbrance is taken through `ledgers.estimate_charges`, so a
    tiered schedule that the fill pass will not levy still has to be reserved
    for -- otherwise an account funds the shares and not the fees. Extends the
    Tier 1 seam rather than paralleling it: same function, same positional
    signature, one new keyword."""
    order = Order(ticker='HPG', side=Side.BUY, quantity=10000,
                  order_type=OrderType.LIMIT, limit_price=Decimal('25.5'))
    without = ledgers.estimate_charges(rules(), order, Venue.HSX,
                                       ChargeClass.EQUITY, Decimal('25.5'))
    with_tiers = ledgers.estimate_charges(rules(), order, Venue.HSX,
                                          ChargeClass.EQUITY, Decimal('25.5'),
                                          commission=(SSI,))
    assert without == Decimal('68850')                   # exchange fee only
    assert with_tiers == Decimal('833850')               # + 0.30%, the dearest


def test_the_ledger_seam_can_now_price_a_futures_fill():
    """Tier 1's `assess_charges` raised on HNXDS -- the cash conversion refuses
    that venue by design -- so `exchange.py` grew a second copy of the whole
    charge loop for futures, and said so in its own docstring. Supplying the
    contract multiplier is all the seam needed: the same function now levies
    the exchange fee, the clearing fee and the transfer tax on the margined
    base, from the one dated margin series."""
    fill = Fill(fill_id=FillId('F1'), order_id=OrderId('F'),
                ticker='VN30F2306', venue=Venue.HNXDS, side=Side.BUY,
                quantity=1, price=Decimal('1100'), ts=TS,
                evidence=FillEvidence.MODELLED)
    with pytest.raises(ValueError, match='no contract multiplier'):
        ledgers.assess_charges(rules(), None, fill, ChargeClass.FUTURE)

    levied = {c.kind: c for c in ledgers.assess_charges(
        rules(), None, fill, ChargeClass.FUTURE,
        multiplier=VN30F_MULTIPLIER)}
    assert levied['exchange_service_index_future'].amount == Decimal('2700')
    assert levied['vsdc_derivatives_clearing'].amount == Decimal('2550')
    assert levied[C.DERIVATIVES_PIT_CHARGE_ID].amount == Decimal('9350')


def test_the_ledger_seam_still_refuses_a_derivatives_charge_without_a_multiplier():
    """`CURRENCY_UNIT['HNXDS'] == 1` must never be applied as a multiplier, so
    the absence of one is an error and not a fallback. The refusal is what
    kept the Tier 1 seam honest and it is kept."""
    with pytest.raises(ValueError, match='not a multiplier'):
        ledgers.trade_value(Venue.HNXDS, 1, Decimal('1100'))
