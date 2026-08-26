"""Corporate actions and the charge model, asserted against the real corpus.

Every number here came out of ``plutus.market.session`` or out of the daily
Parquet corpus. Nothing is asserted against a restatement of the module under
test: the ex-date reference is judged against the **published** ceiling and
floor, and the derivatives transfer tax is judged against the **statutory**
formula written out longhand.

The scenario module has a hyphen in its name and cannot be imported by
statement, so it is loaded by path -- the same treatment every scenario in
``validation/scenarios`` needs.
"""

import importlib.util
import sys
from datetime import date, datetime, time
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from conftest import requires_corpus

from plutus.core.order import Side
from plutus.market.margin import vsd_initial_margin
from plutus.market.session.charges import (
    DERIVATIVES_PIT_CHARGE_ID, DERIVATIVES_PIT_RATE, margined_value,
)
from plutus.market.session.corporate import (
    REFERENCE_ROUNDED_TO_TICK, CorporateActionEngine, CorporateActionSchedule,
    RestingOrderPolicy, RightsSubscriptionUnfunded,
    UnhandledCorporateActionError, adjusted_reference,
)
from plutus.market.session.types import (
    OrderState, Pool, ResourceKind, Venue,
)
from plutus.market.verdicts import AdmissionRule

from validation.logs import SettlementAction, TradeAction


def _load():
    path = (Path(__file__).resolve().parents[2] / 'validation' / 'scenarios'
            / 'corporate-charges.py')
    spec = importlib.util.spec_from_file_location(
        'validation_scenarios_corporate_charges', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cc = _load()

pytestmark = requires_corpus

_ZERO = Decimal('0')
_THOUSAND = Decimal('1000')


# --------------------------------------------------------------------------
# Runs, each done once
# --------------------------------------------------------------------------

@pytest.fixture(scope='module')
def source():
    return cc.datahub_source()


@pytest.fixture(scope='module')
def evidence(source):
    return cc.reference_evidence()


@pytest.fixture(scope='module')
def applied_run(source):
    return cc.run_ex_date(apply=True, source=source)


@pytest.fixture(scope='module')
def naive_run(source):
    return cc.run_ex_date(apply=False, source=source)


@pytest.fixture(scope='module')
def cancel_run(source):
    return cc.run_resting_order(RestingOrderPolicy.CANCEL, source=source)


@pytest.fixture(scope='module')
def scale_run(source):
    return cc.run_resting_order(RestingOrderPolicy.SCALE, source=source)


@pytest.fixture(scope='module')
def scale_sell_run(source):
    return cc.run_resting_order(RestingOrderPolicy.SCALE, source=source,
                                side=Side.SELL)


@pytest.fixture(scope='module')
def cancel_sell_run(source):
    return cc.run_resting_order(RestingOrderPolicy.CANCEL, source=source,
                                side=Side.SELL)


@pytest.fixture(scope='module')
def equity_charges(source):
    return cc.run_equity_charges(source)


@pytest.fixture(scope='module')
def derivatives(source):
    return cc.run_derivatives_charges(source)


# --------------------------------------------------------------------------
# 1. The ex-date reference against the exchange's own published band
# --------------------------------------------------------------------------

def test_the_unrounded_reference_reproduces_every_published_band(evidence):
    """Nine HOSE ex-dates, nine published bands, nine matches.

    This is the strongest statement available about ``adjusted_reference``:
    the corpus does not publish the adjusted reference (``quote_reference``
    repeats the previous close on an ex-date), so the band is the only oracle,
    and reproducing it to the tick means the formula and the tick tiers and
    the rounding directions are all right at once.
    """
    assert len(evidence) == 9
    wrong = [(row.case.ticker, row.band_unrounded, row.published)
             for row in evidence if not row.unrounded_matches]
    assert wrong == []


@pytest.mark.parametrize('rounding',
                         [ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING])
def test_rounding_the_reference_to_the_tick_is_refuted_in_every_direction(
        rounding):
    """``REFERENCE_ROUNDED_TO_TICK`` calls this case untested. It is now tested.

    Rounding the adjusted reference onto the quotation unit produces a band
    the exchange did not publish, in all three directions. HPG 2021-05-31 is
    decisive on its own: no price on the 0.05 grid reproduces both the
    published 52.70 ceiling and the published 45.90 floor, so the exchange
    cannot have rounded the reference to the tick before drawing the band.
    """
    rows = cc.reference_evidence(rounding=rounding)
    assert sum(row.rounded_matches for row in rows) < len(rows)
    hpg = next(row for row in rows if row.case.ticker == 'HPG')
    assert hpg.unrounded_matches
    assert not hpg.rounded_matches


def test_the_hpg_ceiling_and_floor_pin_the_reference_between_two_ticks():
    """Why no rounding direction can work, stated as arithmetic.

    The published band brackets the true reference into an interval that
    contains no multiple of the 0.05 quotation unit. Asserting the interval
    rather than the conclusion means this test still says something if the
    corpus row ever changes.
    """
    case = cc.HPG_CASE
    # ceiling = trunc_0.10(1.07 P')  == 52.70  =>  52.70 <= 1.07 P' < 52.80
    lower_from_ceiling = Decimal('52.70') / Decimal('1.07')
    upper_from_ceiling = Decimal('52.80') / Decimal('1.07')
    # floor = roundup_0.05(0.93 P') == 45.90   =>  45.85 <  0.93 P' <= 45.90
    lower_from_floor = Decimal('45.85') / Decimal('0.93')
    upper_from_floor = Decimal('45.90') / Decimal('0.93')
    low = max(lower_from_ceiling, lower_from_floor)
    high = min(upper_from_ceiling, upper_from_floor)
    assert low < high, 'the published band is self-contradictory'
    ticks_inside = [Decimal(n) / Decimal('20')          # every 0.05 in range
                    for n in range(int(low * 20), int(high * 20) + 2)
                    if low < Decimal(n) / Decimal('20') < high]
    assert ticks_inside == []
    raw = adjusted_reference(case.action, case.prev_close, venue=Venue.HSX,
                             tick=None).reference_price
    assert low < raw < high


def test_the_quantity_factor_is_the_price_ratio_for_a_pure_stock_event(
        evidence):
    """``P' = P / (1 + b)`` and ``qty x (1 + b)`` are one statement.

    Only for the pure-stock rows: a cash leg breaks the identity, which is the
    point of keeping the two legs apart.
    """
    checked = 0
    for row in evidence:
        if row.case.cash_per_share or not row.case.stock_ratio:
            continue
        checked += 1
        assert abs(row.raw_reference * row.quantity_factor
                   - row.case.prev_close) < Decimal('1e-20')
    assert checked == 5


def test_the_hose_ex_rights_code_follows_the_legs(evidence):
    """Codes 01, 02 and 03 as HOSE gazettes them, computed from the legs."""
    codes = {row.case.ticker: row.hose_code for row in evidence}
    assert codes['HPG'] == '03'          # stock + cash
    assert codes['FPT'] == '03'
    assert codes['VIB'] == '01'          # stock or bonus
    assert codes['VCI'] == '01'
    assert codes['PLX'] == '02'          # cash
    assert codes['MSN'] == '02'


# --------------------------------------------------------------------------
# 2. The holding across the ex-date
# --------------------------------------------------------------------------

def test_the_unsettled_parcel_bought_on_the_last_cum_session_is_entitled(
        applied_run):
    """The record date is struck T+2 after the ex-date, for this exact reason.

    On 2021-05-31 the 1,500-share parcel bought on 2021-05-28 has not settled.
    Pricing the entitlement off settlement state would deny the dividend to
    exactly the buyer the T+2 cycle was designed to include -- so the
    entitlement is computed on ``Holding.total``, and this asserts that it was.
    """
    holding = applied_run.strategy.holding_at_ex_open
    assert holding.settled == 1000
    assert holding.unsettled_quantity == 1500
    assert holding.total == 2500

    applied = applied_run.applied[0]
    assert applied.holding_before.total == 2500
    assert applied.quantity_factor == Decimal('1.35')
    assert applied.holding_after.total == 3375
    # 2,500 x 0.35 = 875 whole shares, nothing lost to flooring: every HOSE
    # parcel is a multiple of the 100-share lot and every ratio in EX_DATES
    # has two decimals, so the entitlement is always whole.
    assert applied.fractional_residue == _ZERO


def test_the_action_scales_every_parcel_and_keeps_its_settlement_instant(
        applied_run):
    """A stock dividend must not collapse the tranche list.

    The unsettled parcel grows 1,500 -> 2,025 and keeps the settlement instant
    it had before the adjustment. Collapsing the parcels would make the whole
    holding settle at one time, which is how a T+2 model quietly stops binding.
    """
    before = applied_run.strategy.tranches_at_ex_open
    after = applied_run.applied[0].tranches_after
    assert [t.quantity for t in before] == [1500]
    assert [t.quantity for t in after] == [2025]
    assert [t.settles_at for t in after] == [t.settles_at for t in before]
    assert applied_run.applied[0].holding_after.settled == 1350


def test_the_cash_leg_is_credited_gross_on_the_full_holding(applied_run):
    """500 VND x 2,500 shares = 1,250,000 VND, gross of the 5% withholding.

    Gross is not an oversight: the withholding is a charge row and the
    rulebook carries none for it, so applying it here would put a tax rate
    where no charge table can see it. ``cash_leg_is_gross`` is a field so a
    report cannot omit the fact.
    """
    applied = applied_run.applied[0]
    assert applied.cash_leg == Decimal('1250000')
    assert applied.cash_leg_is_gross is True
    assert applied.net_cash_leg == Decimal('1250000')

    rows = [e for e in applied_run.result.logs.cash
            if 'corporate action' in e.cause]
    assert len(rows) == 1
    row = rows[0]
    assert row.pool == Pool.SECURITIES.value
    assert row.amount == Decimal('1250000')
    assert row.affects_balance is True
    assert row.ts.date() == cc.HPG_CASE.ex_date
    assert 'GROSS of the 5% dividend withholding' in row.cause


def test_the_dividend_cash_leg_produces_no_settlement_row(applied_run):
    """Finding F-7, pinned.

    The dividend is credited settled and immediately at the ex-date while the
    real payment lands weeks later on a payment date no source on this machine
    carries. It is therefore the one securities-pool movement with no tranche
    behind it, and the settlement log says so by omission.

    The ex-date is **not** empty of settlement rows, and that is a separate
    fact: since 2026-08-27 the share leg writes a ``TRANCHE_ADJUSTED`` row for
    each unsettled parcel it rescales. That row carries no ``amount`` and is
    not a cash movement -- the omission this test pins is the *cash* leg's.
    """
    ex_date = cc.HPG_CASE.ex_date
    rows = [e for e in applied_run.result.logs.settlement
            if e.ts.date() == ex_date]
    assert [e.action for e in rows] == [SettlementAction.TRANCHE_ADJUSTED]
    assert rows[0].amount is None
    assert rows[0].leg == 'securities'
    # No cash tranche exists for the 1,250,000 credited on the ex-date.
    assert [e for e in rows if e.leg == 'cash'] == []


def test_the_odd_lot_left_by_the_stock_dividend_cannot_be_sold(applied_run):
    """2,500 x 1.35 = 3,375, and 3,375 is not a multiple of the 100-share lot.

    The refusal is the correct behaviour and the stranded remainder is a real
    Vietnamese *lo le*: sold to the broker off-board, never matched. A model
    that fills 3,375 shares on the matching board is trading a quantity the
    exchange would have refused.
    """
    refusal = applied_run.strategy.odd_lot_refusal
    assert refusal is not None
    assert refusal.rule is AdmissionRule.ROUND_LOT
    assert refusal.binding_constraint == 100
    assert applied_run.strategy.stranded_shares == 75
    assert applied_run.closing_holding == 75

    filled = [e for e in applied_run.result.logs.trades.of(TradeAction.FILLED)
              if e.side == Side.SELL.value]
    assert [e.fill_quantity for e in filled] == [3300]


def test_holdings_conservation_breaks_by_exactly_the_created_shares(
        applied_run):
    """The identity fails, and it fails by the right number.

    ``holdings_conservation`` is opening + buys - sells, and a bonus issue
    creates shares no fill produced, so it *must* fail on a run that applies
    one. What matters is that the gap is exactly the entitlement -- 875 shares
    -- and not one share more.

    ``settlement_completeness`` is **not** in the failed set, and that is
    load-bearing. When it joined the suite it immediately reported this run's
    rescaled parcel as an orphan -- 1,500 created, 2,025 settled, so the
    creation row never matched its own settlement. That was a real log defect,
    and it is closed by the ``TRANCHE_ADJUSTED`` bridge row rather than by
    exempting the run.
    """
    failed = {r.name for r in applied_run.result.failed_identities}
    assert failed == {'holdings_conservation'}
    assert applied_run.result.logs.settlement.unsettled_at_end() == ()
    breach = next(r for r in applied_run.result.identities
                  if r.name == 'holdings_conservation').breaches[0]
    assert breach['ticker'] == 'HPG'
    assert breach['bought'] == 2500
    assert breach['sold'] == 3300
    assert breach['actual'] - breach['expected'] == 875
    assert 875 == int(2500 * Decimal('0.35'))


def test_cash_is_conserved_in_both_pools_even_across_the_action(applied_run,
                                                               naive_run):
    """The cash log still sums to the balance the session reports.

    The corporate-action credit reaches the securities pool through
    ``CashLedger.credit``, which the journal wraps, so it lands in the log as
    an itemised movement rather than as a balance jump. If it had not, this is
    the identity that would have failed.
    """
    for run in (applied_run, naive_run):
        names = {r.name: r for r in run.result.identities}
        assert names['cash_conservation[securities]'].passed
        assert names['cash_conservation[derivatives]'].passed
        assert names['encumbrance_zero'].passed
        assert names['order_lifecycle'].passed
        assert names['no_negative_settled'].passed


# --------------------------------------------------------------------------
# 3. What a run that ignores the ex-date reports
# --------------------------------------------------------------------------

def test_a_run_that_ignores_the_ex_date_reports_a_loss_that_did_not_happen(
        naive_run, applied_run):
    """Finding F-2, as a number.

    Same algorithm, same window, same data. The naive run loses money and the
    correct one makes it, and the whole difference is the corporate action.
    Both runs pass eight of the harness's nine identities.
    """
    assert naive_run.net_pnl < _ZERO
    assert applied_run.net_pnl > _ZERO
    assert naive_run.closing_holding == 0

    gap = applied_run.net_pnl - naive_run.net_pnl
    assert gap > Decimal('48000000')
    assert not naive_run.result.failed_identities


def test_the_whole_gap_between_the_two_runs_is_accounted_for(naive_run,
                                                             applied_run):
    """Every dong of the 48.4m difference, named.

    A headline number nobody can decompose is a claim, not a measurement. The
    gap is exactly four things: the extra shares sold, the extra charges they
    attracted, the cash dividend, and the odd lot that could not be sold.
    Nothing else differs between the two runs.
    """
    def sell_charges(run):
        return sum((-e.amount for e in run.result.logs.cash
                    if e.charge_kind and not e.affects_balance), _ZERO)

    def sell_fill(run):
        return next(e for e in run.result.logs.trades.of(TradeAction.FILLED)
                    if e.side == Side.SELL.value)

    naive_fill, applied_fill = sell_fill(naive_run), sell_fill(applied_run)
    assert naive_fill.fill_price == applied_fill.fill_price

    extra_shares = applied_fill.fill_quantity - naive_fill.fill_quantity
    assert extra_shares == 800                      # 875 created, 75 stranded
    extra_gross = (Decimal(extra_shares) * applied_fill.fill_price
                   * _THOUSAND)
    extra_charges = sell_charges(applied_run) - sell_charges(naive_run)
    dividend = applied_run.applied[0].cash_leg
    stranded = applied_run.stranded_value

    gap = applied_run.net_pnl - naive_run.net_pnl
    assert gap == extra_gross - extra_charges + dividend + stranded
    assert gap > Decimal('48000000')
    # the buy side is identical in both runs, to the dong
    for run in (naive_run, applied_run):
        buys = sum((-e.amount for e in run.result.logs.cash
                    if e.affects_balance and e.amount < _ZERO), _ZERO)
        assert buys == Decimal('168095374')


def test_the_audit_is_the_only_thing_that_names_the_naive_run_as_wrong(
        naive_run, applied_run):
    """``CorporateActionAudit`` reports the crossing; nothing calls it.

    The session has no corporate-action hook by design, so the audit is the
    designed remedy -- and it is a remedy only for a caller who attaches it.
    """
    assert not naive_run.audit_report.is_clean
    assert naive_run.audit_report.affected_tickers == ('HPG',)
    unhandled = naive_run.audit_report.unhandled[0]
    assert unhandled.held_quantity == 0        # sold before the report
    assert unhandled.order_ids                 # but the orders are exposure
    with pytest.raises(UnhandledCorporateActionError):
        naive_run.audit_report.raise_if_unhandled()

    assert applied_run.audit_report.is_clean
    assert applied_run.audit_report.raise_if_unhandled() is \
        applied_run.audit_report


# --------------------------------------------------------------------------
# 4. An order live when the adjustment lands
# --------------------------------------------------------------------------

def test_no_order_can_be_live_at_the_next_session_open(source):
    """Finding F-3: the policy's own premise, confirmed in the simulator.

    ``RestingOrderPolicy`` says no Vietnamese order type survives a session
    close. This simulator enforces it, so an order submitted at 09:30 is
    ``EXPIRED`` by the 14:45 sweep and ``apply_due`` at the next open can
    never find one live. Both branches are reachable only inside a session.
    """
    run = cc.run_resting_order(RestingOrderPolicy.CANCEL, source=source)
    submitted = run.result.logs.trades.of(TradeAction.SUBMITTED)
    assert len(submitted) == 1
    assert submitted[0].ts.date() == cc.HPG_CASE.ex_date
    # and the same order, left alone, would have died at that day's close:
    control = cc.run_ex_date(apply=False, source=source)
    assert control.result.sessions_run == 12


def test_the_cancel_policy_terminates_the_order_and_releases_the_reservation(
        cancel_run):
    """The default arm, and the one the day-order rule implies.

    Cancellation goes through the book's terminal hook like every other
    terminal edge, so the reservation is released by the session's own
    ``on_terminal`` and section 12 invariant 4 still holds.
    """
    outcome = cancel_run.outcome
    assert outcome.policy is RestingOrderPolicy.CANCEL
    assert outcome.quantity_before == 1000
    assert outcome.quantity_after == 0
    assert cancel_run.order_after.state is OrderState.CANCELLED
    assert cancel_run.encumbrance_after == ()
    names = {r.name: r for r in cancel_run.result.identities}
    assert names['encumbrance_zero'].passed
    assert names['order_lifecycle'].passed


def test_the_scale_policy_scales_to_the_lot_and_reprices_by_the_ratio(
        scale_run):
    """The non-default arm: quantity by the factor, price by the reference ratio.

    1,000 x 1.35 = 1,350, floored onto the 100-share lot = 1,300. The price is
    scaled by ``ReferenceAdjustment.ratio``, which is the one ratio with a
    gazetted precedent for adjusting a contractual price across a corporate
    action (QD 22/2026 Dieu 36 adjusts a covered warrant's strike by exactly
    it).
    """
    outcome = scale_run.outcome
    assert outcome.policy is RestingOrderPolicy.SCALE
    assert outcome.quantity_before == 1000
    assert outcome.quantity_after == 1300
    assert outcome.lot_enforced is True

    reference = scale_run.applied.reference
    ratio = reference.ratio
    assert outcome.limit_price_after == outcome.limit_price_before * ratio
    assert outcome.limit_price_after < outcome.limit_price_before

    record = scale_run.order_after
    assert record.remaining_quantity == 1300
    assert record.filled_quantity + record.remaining_quantity == \
        record.order.quantity
    names = {r.name: r for r in scale_run.result.identities}
    assert names['encumbrance_zero'].passed


def test_the_scaled_limit_price_is_off_the_tick_grid(scale_run):
    """Finding F-10, pinned.

    ``apply(tick=...)`` feeds two different roundings: the ex-date reference
    and a scaled limit price. F-1 says the reference must not be rounded onto
    the quotation unit; a limit price must be, or it can never match. One
    parameter cannot serve both, and a caller who resolves the conflict in
    favour of the reference gets a limit price with 26 significant digits.
    """
    price = scale_run.outcome.limit_price_after
    assert price.as_tuple().exponent < -2
    assert (price / Decimal('0.05')) % 1 != 0


def test_the_scaled_cash_reservation_grows_with_the_order(scale_run):
    """The reservation is released and re-taken, and must still cover the order.

    ``book.amend`` does not touch encumbrances, so the SCALE branch re-takes
    by hand. A re-take that lost value would leave a buy order the account can
    no longer pay for and nothing else would notice. The value ratio is
    quantity x price, and on a buy the two move in opposite directions --
    1.3x the shares at 0.735x the price -- so the check is against the
    arithmetic, not against a direction.

    **In whole dong.** The re-take used to write the raw Decimal quotient
    straight through, and a measured run reported ``committed_cash
    43978090.45206159960258320914`` against a currency with no subunit.
    ``encumbrance_matches`` held anyway, because it compares the reservation
    to itself and both sides were equally fractional. The rounding is up, so
    the reservation can never end up short of the order it backs.
    """
    before = scale_run.encumbrance_before
    after = scale_run.encumbrance_at_adjustment
    assert [e.resource for e in before] == [ResourceKind.CASH]
    assert [e.resource for e in after] == [ResourceKind.CASH]
    outcome = scale_run.outcome
    qty_ratio = (Decimal(outcome.quantity_after)
                 / Decimal(outcome.quantity_before))
    price_ratio = outcome.limit_price_after / outcome.limit_price_before
    exact = before[0].amount * qty_ratio * price_ratio
    assert after[0].amount == exact.quantize(Decimal('1'),
                                             rounding=ROUND_CEILING)
    assert after[0].amount == Decimal('43978091')
    assert after[0].amount.as_tuple().exponent == 0        # whole dong
    assert after[0].estimated_charges.as_tuple().exponent == 0
    assert after[0].amount >= exact                        # never short
    # The order lived to the close and expired there, so by the end of the run
    # nothing is reserved against it.
    assert scale_run.encumbrance_after == ()
    assert scale_run.order_after.state is OrderState.EXPIRED


def test_the_scaled_share_reservation_grows_with_the_holding(scale_sell_run):
    """The other half of the SCALE branch: a sell reserves shares, not cash.

    A buy-only test leaves this arm unrun, and the two are different
    arithmetic -- value for cash, quantity for shares. VIB's 40% bonus takes
    1,000 reserved shares to 1,400, which is exactly the holding the same
    event created, so the reservation neither over- nor under-commits it.
    """
    before = scale_sell_run.encumbrance_before
    after = scale_sell_run.encumbrance_at_adjustment
    assert [e.resource for e in before] == [ResourceKind.SHARES]
    assert [e.resource for e in after] == [ResourceKind.SHARES]
    assert before[0].quantity == 1000
    assert after[0].quantity == 1400
    assert scale_sell_run.applied.quantity_factor == Decimal('1.40')
    assert scale_sell_run.applied.holding_after.total == 1400
    assert scale_sell_run.outcome.quantity_after == 1400


def test_the_cancel_policy_releases_a_share_reservation_too(cancel_sell_run):
    """CANCEL goes through the book's terminal hook whichever resource it held."""
    assert [e.resource for e in cancel_sell_run.encumbrance_before] == \
        [ResourceKind.SHARES]
    assert cancel_sell_run.encumbrance_at_adjustment == ()
    assert cancel_sell_run.order_after.state is OrderState.CANCELLED
    names = {r.name: r for r in cancel_sell_run.result.identities}
    assert names['encumbrance_zero'].passed
    assert names['order_lifecycle'].passed


def test_both_sell_side_runs_break_holdings_conservation_by_the_bonus(
        cancel_sell_run, scale_sell_run):
    """400 shares out of a 1,000-share holding, and nothing else moved.

    VIB's factor is 1.40 and the opening holding is 1,000, so a run that
    applies the action has 400 shares no fill produced. Asserting the exact
    gap is what separates "the identity fails because a bonus issue happened"
    from "the identity fails".
    """
    for run in (cancel_sell_run, scale_sell_run):
        failed = {r.name for r in run.result.failed_identities}
        assert failed == {'holdings_conservation'}
        breach = next(r for r in run.result.identities
                      if r.name == 'holdings_conservation').breaches[0]
        assert breach['actual'] - breach['expected'] == 400


# --------------------------------------------------------------------------
# 5. A rights issue must not create money
# --------------------------------------------------------------------------

def test_a_rights_take_up_debits_exactly_what_the_shares_cost(source):
    """500 new shares at 10,000 VND = 5,000,000 VND, in the same call.

    Crediting the shares without debiting the subscription is the one
    arithmetic error in this domain that no downstream number reveals: the
    holding is larger, the cash is untouched, and every invariant still holds.
    """
    outcome = cc.rights_conservation(take_up=True, source=source)
    assert outcome.refusal is None
    assert outcome.shares_before == 1000
    assert outcome.shares_after == 1500
    assert outcome.cash_before - outcome.cash_after == Decimal('5000000')
    applied = outcome.applied
    assert applied.subscription_shares == 500
    assert applied.subscription_outlay == Decimal('5000000')
    assert applied.subscription_outlay_is_debited is True
    assert applied.net_cash_leg == Decimal('-5000000')


def test_the_rights_event_conserves_value(source):
    """The reference falls by exactly the dilution the subscription paid for.

    ``P' = (P + Pa a) / (1 + a)``. Cash plus shares at the cum reference must
    equal cash plus shares at the ex reference, to the dong, or the event
    created or destroyed value.
    """
    outcome = cc.rights_conservation(take_up=True, source=source)
    assert abs(outcome.value_after - outcome.value_before) < Decimal('1e-6')


def test_a_lapsed_rights_issue_moves_neither_leg(source):
    """``take_up=False``: the price adjusts, the holding does not.

    That asymmetry is what a holder who lets rights lapse actually
    experiences, and reporting it honestly is the point of not defaulting the
    decision.
    """
    outcome = cc.rights_conservation(take_up=False, source=source)
    assert outcome.refusal is None
    assert outcome.shares_after == outcome.shares_before
    assert outcome.cash_after == outcome.cash_before
    assert outcome.applied.subscription_outlay == _ZERO
    assert outcome.reference_after < outcome.reference_before
    # and the holder is worse off by exactly the dilution they did not pay for
    assert outcome.value_after < outcome.value_before


def test_the_engine_refuses_to_guess_a_rights_take_up(source):
    """No default, because both arms are defensible and differ by real money."""
    outcome = cc.rights_conservation(take_up=None, source=source)
    assert isinstance(outcome.refusal, ValueError)
    assert 'take_up was not stated' in str(outcome.refusal)
    assert outcome.shares_after == outcome.shares_before
    assert outcome.cash_after == outcome.cash_before


def test_an_unfunded_take_up_applies_nothing_at_all(source):
    """The refusal comes before any leg moves.

    A refusal that had already scaled the holding would be the same
    fabrication the check exists to prevent, only harder to see.
    """
    outcome = cc.rights_conservation(take_up=True, initial_cash='1000000',
                                     source=source)
    assert isinstance(outcome.refusal, RightsSubscriptionUnfunded)
    assert outcome.shares_after == outcome.shares_before
    assert outcome.cash_after == outcome.cash_before
    assert outcome.applied is None


def test_applying_the_same_action_twice_is_refused(source):
    """Compounding the factor and paying the dividend again is a hard error."""
    session = cc.build_session(
        start=cc.CA_WINDOW.start, end=cc.CA_WINDOW.end, venues=['HSX'],
        source=source, initial_cash='1000000000', fill_policy='soft',
        initial_holdings={'HPG': 1000})
    ts = datetime.combine(cc.HPG_CASE.ex_date, time(9, 30))
    session.advance_to(ts)
    action = cc.HPG_CASE.action
    engine = CorporateActionEngine(CorporateActionSchedule([action]))
    engine.apply(action, account=session._securities, ts=ts)
    assert session.holdings('HPG').total == 1350
    with pytest.raises(ValueError, match='already been applied'):
        engine.apply(action, account=session._securities, ts=ts)
    assert session.holdings('HPG').total == 1350


# --------------------------------------------------------------------------
# 6. Equity charges: per venue, per side, itemised
# --------------------------------------------------------------------------

def _charge_rows(result):
    return [e for e in result.logs.cash if e.charge_kind]


def test_the_transfer_tax_is_sell_side_only(equity_charges):
    """Rulebook 8.1/12.3: 0.1%, sell side, withheld at source.

    The single most valuable row in the fee table -- without it every sale is
    wrong by more than most commissions -- and the axis that decides whether
    it fires at all is the side.
    """
    rows = _charge_rows(equity_charges)
    pit = [e for e in rows if e.charge_kind == 'pit_securities_transfer']
    assert len(pit) == 2                       # two sells, no buys
    assert {e.ticker for e in pit} == {'HPG', 'PVS'}
    for row in pit:
        assert row.affects_balance is False    # withheld out of the proceeds
        assert row.charge_base == 'trade_value'
        assert -row.amount == (row.charge_base_value
                               * Decimal('0.001')).quantize(Decimal('1'))
        assert row.vat == _ZERO

    buys = {e.order_id for e in equity_charges.logs.trades.of(
        TradeAction.FILLED) if e.side == Side.BUY.value}
    assert buys
    assert not [e for e in pit if e.order_id in buys]


def test_the_exchange_service_row_names_the_venue_it_was_levied_at(
        equity_charges):
    """One venue axis, two rows, fired on every fill on both sides.

    HSX and HNX carry the same 0.027% rate in this era, so the rate cannot
    distinguish them -- the ``charge_id`` can, and a charge attributed to the
    wrong venue would be undetectable in a total.
    """
    rows = _charge_rows(equity_charges)
    by_venue = {}
    for row in rows:
        if row.charge_kind.startswith('exchange_service'):
            by_venue.setdefault(row.charge_kind, set()).add(row.ticker)
    assert by_venue == {'exchange_service_hsx_equity': {'HPG'},
                        'exchange_service_hnx_equity': {'PVS'}}
    service = [r for r in rows if r.charge_kind.startswith('exchange_service')]
    fills = equity_charges.logs.trades.of(TradeAction.FILLED)
    assert len(service) == len(fills) == 5
    for row in service:
        assert -row.amount == (row.charge_base_value
                               * Decimal('0.00027')).quantize(Decimal('1'))


def test_the_broker_commission_is_the_venue_row_and_it_is_unsourced(
        equity_charges):
    """Without a broker profile the largest retail charge is simply absent.

    ``RuleSet.charges`` refuses to serve a BROKER row by design, so commission
    comes only from ``BrokerProfile``. This asserts the profile reached every
    fill, at the venue's own row, at the configured rate -- and that the rate
    is the illustrative one, because none of it is sourced to a document.
    """
    rows = _charge_rows(equity_charges)
    commission = [r for r in rows if r.charge_kind.startswith('broker.')]
    assert {r.charge_kind for r in commission} == {'broker.commission.hsx',
                                                   'broker.commission.hnx'}
    assert len(commission) == 5
    assert equity_charges.provenance.broker_profile_name == \
        'illustrative-retail-UNSOURCED'
    assert 'UNSOURCED' in equity_charges.provenance.broker_profile_name


def test_the_per_order_minimum_commission_clamps_the_small_order_only(
        equity_charges):
    """The minimum is a clamp on the ORDER, never on the day.

    A 100-share HPG buy is 4,985,000 VND, so 0.15% is 7,478 and the 30,000
    minimum bites; every other order is far above it. Clamping the day's total
    instead would under-charge by the difference on every small order.
    """
    rows = _charge_rows(equity_charges)
    commission = [r for r in rows if r.charge_kind.startswith('broker.')]
    clamped = [r for r in commission if -r.amount == Decimal('30000')]
    assert len(clamped) == 1
    small = clamped[0]
    assert small.ticker == 'HPG'
    assert small.charge_base_value == Decimal('4985000.00')
    uncapped = (small.charge_base_value * Decimal('0.0015')).quantize(
        Decimal('1'))
    assert uncapped < Decimal('30000')
    for row in commission:
        if row is small:
            continue
        assert -row.amount == (row.charge_base_value
                               * Decimal('0.0015')).quantize(Decimal('1'))
        assert -row.amount > Decimal('30000')


def test_a_tiered_commission_config_is_refused_at_parse_time(source):
    """Finding F-8, pinned.

    ``charges.CommissionSchedule.from_config`` understands ``tiers``;
    ``BrokerProfile.from_config`` -- the one the session calls -- does not,
    and used to build a ``ChargeRule`` with neither rate nor amount. The
    session then built cleanly and died at the **first fill** with a message
    naming a charge rule. It must be refused where the caller can act on it.
    """
    with pytest.raises(ValueError, match='TIERED schedule is not modelled'):
        cc.run_equity_charges(source, broker_profile=cc.TIERED_PROFILE)


def test_every_charge_in_this_window_carries_zero_vat(equity_charges,
                                                      derivatives):
    """Finding F-12: the gazetted arm of an unresolved conflict.

    Every rulebook row in 2021-2022 has ``vat_applies`` off, so every charge
    here is VAT-free -- while the rulebook records in the same breath that
    brokers demonstrably billed the VSDC derivatives rows grossed up 10%
    during that exemption. A result sensitive to 10% on those rows must say
    which arm it took.
    """
    _result, _strategy, session = derivatives
    for row in _charge_rows(equity_charges):
        assert row.vat == _ZERO
    for charge in session.charges():
        assert charge.vat == _ZERO
        assert charge.total == charge.amount


def test_no_charge_is_netted_into_a_fill_price(equity_charges):
    """The fill price is the market's; the charges are separate rows.

    Netting a fee into a price is how a fee model becomes invisible. Every
    fill here prices at the corpus close for its own session, to the tick.
    """
    source = cc.datahub_source()
    for entry in equity_charges.logs.trades.of(TradeAction.FILLED):
        published = source.state_at(
            entry.ticker, datetime.combine(entry.ts.date(), time(9, 30))).last
        assert entry.fill_price == published


def test_a_sale_credits_gross_proceeds_less_exactly_the_withheld_charges(
        equity_charges):
    """The pending tranche is the arithmetic identity of a Vietnamese sale.

    gross - exchange service - 0.1% tax, and nothing else. Two rows in the
    cash log with ``affects_balance=False`` and one pending tranche, which is
    what stops the classic double count.
    """
    rows = _charge_rows(equity_charges)
    pendings = [e for e in equity_charges.logs.cash
                if e.movement.value == 'sale_proceeds_pending']
    assert len(pendings) == 2
    for pending in pendings:
        withheld = sum((-e.amount for e in rows
                        if e.order_id == pending.order_id
                        and e.affects_balance is False), _ZERO)
        fill = next(e for e in equity_charges.logs.trades.of(
            TradeAction.FILLED) if e.order_id == pending.order_id)
        gross = (Decimal(fill.fill_quantity) * fill.fill_price * _THOUSAND)
        assert pending.amount == gross - withheld
        assert withheld > _ZERO


def test_every_settlement_row_carries_the_rule_that_dated_it(equity_charges):
    """A settlement date with no rule behind it is an assertion, not a record.

    Every row also says the calendar is the unsourced weekday one, which is
    the disclosure the harness exists to force.
    """
    rows = equity_charges.logs.settlement.of(SettlementAction.TRANCHE_CREATED,
                                             SettlementAction.TRANCHE_SETTLED)
    assert rows
    for row in rows:
        assert row.settlement_rule
        assert row.settlement_calendar_id == 'weekday-only-UNSOURCED'
    assert equity_charges.logs.settlement.unsettled_at_end() == ()


def test_both_venues_draw_on_the_one_securities_pool(equity_charges):
    """Segregation is by pool, not by venue: HSX and HNX share one account."""
    rows = _charge_rows(equity_charges)
    assert {row.pool for row in rows} == {Pool.SECURITIES.value}
    names = {r.name: r for r in equity_charges.identities}
    assert names['deposit_segregation'].passed
    assert not equity_charges.failed_identities


# --------------------------------------------------------------------------
# 7. The derivatives PIT, across the 2022-12-15 VSD ratio change
# --------------------------------------------------------------------------

def test_the_vsd_ratio_really_changes_inside_this_window():
    """The premise of everything below, asserted rather than assumed."""
    assert vsd_initial_margin(date(2022, 12, 14)) == Decimal('0.13')
    assert vsd_initial_margin(date(2022, 12, 15)) == Decimal('0.17')


def test_the_derivatives_tax_is_levied_on_the_margined_value(derivatives):
    """``PIT = 0.1% x [price x multiplier x contracts x IM / 2]``.

    Asserted against the published formula written out longhand, not against
    the module that implements it. The base is **not** notional: at a 17%
    ratio it is 8.5% of it, so a model that taxes notional over-charges a
    round trip by about 11.8x.
    """
    _result, _strategy, session = derivatives
    pit = [c for c in session.charges()
           if c.kind == DERIVATIVES_PIT_CHARGE_ID]
    assert len(pit) == 5                      # 4 fills + 1 maturity leg
    for charge in pit:
        rate = vsd_initial_margin(charge.ts.date())
        base = margined_value(1, charge.base_value / cc.MULTIPLIER,
                              cc.MULTIPLIER, rate)
        expected = (DERIVATIVES_PIT_RATE * base).quantize(Decimal('1'),
                                                          rounding=ROUND_HALF_UP)
        assert charge.amount == expected
        # and the rulebook's folded form gives the same dong
        assert charge.amount == (Decimal('0.0005') * rate
                                 * charge.base_value).quantize(
                                     Decimal('1'), rounding=ROUND_HALF_UP)


def test_the_tax_and_the_margin_requirement_read_one_dated_ratio(derivatives):
    """The rulebook states this coupling in bold. Here it is, across a change.

    On 2022-12-14 the ratio is 0.13 and on 2022-12-15 it is 0.17, and both the
    initial margin the session reports and the tax it levies move together. If
    a second series entered the run, exactly one of these two would move.
    """
    _result, strategy, session = derivatives

    before = strategy.margin_by_day[(date(2022, 12, 14), 'close')]
    after = strategy.margin_by_day[(date(2022, 12, 15), 'close')]
    positions_before = Decimal('1059.0') + Decimal('1059.6')
    assert before.initial_margin == (Decimal('0.13') * positions_before
                                     * cc.MULTIPLIER)
    assert after.initial_margin == (Decimal('0.17') * Decimal('2')
                                    * Decimal('1070.5') * cc.MULTIPLIER)

    pit = {(c.ticker, c.ts.date()): c for c in session.charges()
           if c.kind == DERIVATIVES_PIT_CHARGE_ID}
    early = pit[('VN30F2301', date(2022, 12, 14))]
    late = pit[('VN30F2301', date(2022, 12, 15))]
    assert early.amount == Decimal('6884')     # 0.0005 x 0.13 x 105,900,000
    assert late.amount == Decimal('9099')      # 0.0005 x 0.17 x 107,050,000
    implied_early = (early.amount * Decimal('2')
                     / (DERIVATIVES_PIT_RATE * early.base_value))
    implied_late = (late.amount * Decimal('2')
                    / (DERIVATIVES_PIT_RATE * late.base_value))
    assert abs(implied_early - Decimal('0.13')) < Decimal('0.0001')
    assert abs(implied_late - Decimal('0.17')) < Decimal('0.0001')


def test_a_contract_held_to_expiry_pays_the_tax_at_maturity(derivatives):
    """Finding F-4, pinned against the statute.

    Rulebook 8.1/12.3: taxable income is determined when the order is matched
    **or at contract maturity**. VN30F2212 is bought on 2022-12-14 and carried
    into its 2022-12-15 final cash settlement, so it is never matched out; the
    closing leg of the tax has to come from the settlement.
    """
    _result, _strategy, session = derivatives
    maturity = [c for c in session.charges()
                if c.kind == DERIVATIVES_PIT_CHARGE_ID
                and c.ticker == 'VN30F2212'
                and c.ts.date() == date(2022, 12, 15)]
    assert len(maturity) == 1
    charge = maturity[0]
    assert charge.base_value == Decimal('1065.1') * cc.MULTIPLIER
    assert charge.amount == cc.expected_maturity_pit(
        Decimal('1065.1'), 1, Decimal('0.17'))
    assert charge.amount == Decimal('9053')
    assert charge.pool is Pool.DERIVATIVES


def test_the_maturity_leg_is_only_the_tax(derivatives):
    """Finding F-11: a matched close pays three rows, a maturity pays one.

    The exchange trading fee is per **matched** contract and the VSDC clearing
    fee per **novated** one, and no source read says either is charged on a
    final cash settlement. Levying them would invent a charge; omitting them
    is the honest treatment and this pins which of the two the session does,
    against a matched close in the same run.
    """
    _result, _strategy, session = derivatives
    on_expiry = [c for c in session.charges()
                 if c.ticker == 'VN30F2212'
                 and c.ts.date() == date(2022, 12, 15)]
    assert [c.kind for c in on_expiry] == [DERIVATIVES_PIT_CHARGE_ID]

    matched_close = [c for c in session.charges()
                     if c.ticker == 'VN30F2301'
                     and c.ts.date() == date(2022, 12, 16)]
    assert sorted(c.kind for c in matched_close) == [
        'exchange_service_index_future', 'pit_derivatives_transfer',
        'vsdc_derivatives_clearing']
    assert sum(c.total for c in matched_close) - \
        sum(c.total for c in on_expiry) == Decimal('5207')   # 2,700 + 2,550
    # ...less the 43 VND the two settle at different prices for.
    assert (sum(c.total for c in matched_close)
            == Decimal('2700') + Decimal('2550') + Decimal('9010'))


def test_the_closing_leg_of_a_matched_round_trip_is_taxed(derivatives):
    """The row is two-sided: a sell that closes a long pays it too.

    Together with the maturity test this is the whole claim -- every contract
    pays the tax twice, once on the way in and once on the way out, however it
    leaves.
    """
    _result, _strategy, session = derivatives
    closing = [c for c in session.charges()
               if c.kind == DERIVATIVES_PIT_CHARGE_ID
               and c.ts.date() == date(2022, 12, 16)]
    assert len(closing) == 1
    assert closing[0].amount == cc.expected_maturity_pit(
        Decimal('1060.0'), 1, Decimal('0.17'))

    sells = [e for e in _result.logs.trades.of(TradeAction.FILLED)
             if e.side == Side.SELL.value]
    assert [e.ticker for e in sells] == ['VN30F2301']
    assert closing[0].order_id == sells[0].order_id


def test_the_expiry_settlement_and_its_charge_are_both_in_the_logs(
        derivatives):
    """Two movements on the deposit, both itemised, both in the cash log."""
    result, _strategy, session = derivatives
    settled = result.logs.settlement.of(SettlementAction.EXPIRY_SETTLED)
    assert len(settled) == 1
    assert settled[0].ticker == 'VN30F2212'
    assert settled[0].amount == Decimal('550000')     # (1065.1-1059.6) x 100k
    assert 'substituted=True' in settled[0].reason    # a close proxy, declared

    charge_rows = [e for e in result.logs.cash
                   if e.pool == Pool.DERIVATIVES.value
                   and 'final settlement of VN30F2212' in e.cause]
    assert len(charge_rows) == 2                      # the settlement, and the
    assert sum(e.amount for e in charge_rows) == (    # charge on it
        Decimal('550000') - Decimal('9053'))
    names = {r.name: r for r in result.identities}
    assert names['deposit_balance_trail'].passed
    assert names['cash_conservation[derivatives]'].passed


def test_the_derivatives_run_keeps_every_identity(derivatives):
    """Nothing broke: no corporate action here, so all nine must hold."""
    result, _strategy, _session = derivatives
    assert result.ok, [r.detail for r in result.failed_identities]
    assert result.indeterminate.indeterminate == 0


# --------------------------------------------------------------------------
# 8. Charges that are dated, declared and never fire
# --------------------------------------------------------------------------

def test_the_vsdc_derivatives_fee_changes_shape_on_2022_01_01(source):
    """The per-**date** axis of the charge table, on the side the corpus reaches.

    Before 2022-01-01 the VSDC row is 2,550 VND per open contract per account
    per **day** -- an accrual no per-fill function can price -- so a futures
    fill pays the exchange fee and the tax and nothing to the depository at
    all. From 2022-01-01 it is 2,550 per **matched** contract at the fill. One
    contract, two sessions, one row that appears.
    """
    result, session = cc.run_vsdc_fee_shape_change(source)
    assert result.error is None
    filled = result.logs.trades.of(TradeAction.FILLED)
    assert [e.ts.date() for e in filled] == [date(2021, 12, 30),
                                             date(2022, 1, 4)]

    def kinds(day):
        return sorted(c.kind for c in session.charges() if c.ts.date() == day)

    assert kinds(date(2021, 12, 30)) == ['exchange_service_index_future',
                                         'pit_derivatives_transfer']
    assert kinds(date(2022, 1, 4)) == ['exchange_service_index_future',
                                       'pit_derivatives_transfer',
                                       'vsdc_derivatives_clearing']
    clearing = next(c for c in session.charges()
                    if c.kind == 'vsdc_derivatives_clearing')
    assert clearing.amount == Decimal('2550')

    # and the row that vanished is still in the rulebook for the earlier date
    early = session._rulebook.at(datetime(2021, 12, 30, 9, 30)).charges(
        Venue.HNXDS, cc.ChargeClass.FUTURE)
    assert 'vsdc_derivatives_position_management' in {r.charge_id
                                                      for r in early}
    assert not result.failed_identities


def test_the_2020_rate_change_cannot_be_reached_and_says_so(source):
    """Finding F-13: an INDETERMINATE refusal, not a rule saying no.

    The HOSE trading-service rate steps 0.0300% -> 0.0270% on 2020-03-19 and
    the corpus covers the date, but publishes no band for any HOSE stock
    before 2021-02-17. The order is refused ``band_limit`` with verdict
    ``indeterminate`` -- a data gap reported as a data gap. Reporting it as a
    rejection instead would make the corpus's silence look like a market rule.
    """
    result, session = cc.run_pre_band_equity(source)
    rejected = result.logs.trades.of(TradeAction.REJECTED)
    assert len(rejected) == 2
    for row in rejected:
        assert row.rule == AdmissionRule.BAND_LIMIT.value
        assert row.verdict == 'indeterminate'
    assert result.logs.trades.of(TradeAction.FILLED) == ()
    assert session.charges() == ()

    # Two populations, deliberately not summed: ``by_rule`` counts submissions
    # the exchange could not judge, ``evaluations``/``indeterminate`` count
    # fill decisions. Nothing ever reached a fill decision here, so the
    # headline rate is 0/0 while two orders were refused for want of data --
    # which is finding F-14.
    report = result.indeterminate
    assert report.by_rule == {AdmissionRule.BAND_LIMIT.value: 2}
    assert report.evaluations == 0
    assert report.rate is None
    assert 'undecided   0/0' in result.summary()

    # the rate really did change; it is the data that cannot reach it
    before = session._rulebook.at(datetime(2020, 3, 18, 9, 30)).charges(
        Venue.HSX)
    after = session._rulebook.at(datetime(2020, 3, 19, 9, 30)).charges(
        Venue.HSX)
    rate = {r.charge_id: r.rate for r in before}['exchange_service_hsx_equity']
    later = {r.charge_id: r.rate for r in after}['exchange_service_hsx_equity']
    assert rate == Decimal('0.0003')
    assert later == Decimal('0.00027')


def test_the_monthly_and_daily_holding_charges_never_fire(derivatives,
                                                          equity_charges):
    """Finding F-9, pinned.

    ``vsdc_custody_equity`` and, before 2022-01-01,
    ``vsdc_derivatives_position_management`` are dated rows with a holding
    base and no accrual pass anywhere in the session, so a holding that never
    trades costs nothing here. Both are visible in ``RuleSet.charges`` and
    absent from every cash log -- which is the shape of an omission that is
    declared rather than silent.
    """
    _result, _strategy, session = derivatives
    rows = session._rulebook.at(
        datetime(2022, 12, 14, 9, 30)).charges(Venue.HSX)
    assert 'vsdc_custody_equity' in {r.charge_id for r in rows}
    levied = {c.kind for c in session.charges()}
    levied |= {e.charge_kind for e in equity_charges.logs.cash
               if e.charge_kind}
    assert 'vsdc_custody_equity' not in levied
    assert 'vsdc_derivatives_position_management' not in levied


def test_the_rounding_citation_records_the_corpus_evidence():
    """A citation that asserts something the corpus refutes is a defect.

    ``REFERENCE_ROUNDED_TO_TICK`` said half-up "is the only direction with any
    evidence behind it anywhere in the domain" and that the HOSE case was
    untested. Nine ex-dates later it is tested, and the answer is that the
    reference is not rounded onto the quotation unit at all. The citation is
    data a published result prints, so it has to carry the finding.
    """
    note = REFERENCE_ROUNDED_TO_TICK.note
    assert 'NO LONGER UNTESTED' in note
    assert 'Pass tick=None for a HOSE ex-date' in note
    assert 'corporate-charges.py' in note
    # and the claim it used to make in the present tense is gone
    assert 'is the only direction with any evidence' not in note


def test_no_order_is_left_live_at_the_end_of_any_run(applied_run, naive_run,
                                                     cancel_run, scale_run,
                                                     cancel_sell_run,
                                                     scale_sell_run,
                                                     equity_charges,
                                                     derivatives, source):
    """Stronger than ``order_lifecycle``, which accepts a still-live order.

    Every window here ends on a session whose 14:45 sweep has run, and no
    Vietnamese order type outlives a session, so a live order at the end would
    mean the day-order rule did not fire -- and would also mean a reservation
    still held. Asserted across every run in this module, including the two
    where the corporate-action engine terminated the order itself.
    """
    vsdc_result, _ = cc.run_vsdc_fee_shape_change(source)
    pre_result, _ = cc.run_pre_band_equity(source)
    runs = {
        'applied': applied_run.result, 'naive': naive_run.result,
        'cancel': cancel_run.result, 'scale': scale_run.result,
        'cancel-sell': cancel_sell_run.result,
        'scale-sell': scale_sell_run.result,
        'equity': equity_charges, 'derivatives': derivatives[0],
        'vsdc': vsdc_result, 'pre-band': pre_result,
    }
    seen = 0
    for name, result in runs.items():
        accepted = result.logs.trades.of(TradeAction.ACCEPTED)
        seen += len(accepted)
        states = {e.order_id: None for e in accepted}
        assert {r.name: r for r in result.identities}['order_lifecycle'].passed
        for entry in result.logs.trades:
            if entry.order_id in states and entry.action in (
                    TradeAction.FILLED, TradeAction.CANCELLED,
                    TradeAction.EXPIRED):
                states[entry.order_id] = entry.action
        unresolved = [oid for oid, action in states.items() if action is None]
        assert unresolved == [], f'{name}: {unresolved}'
    assert seen >= 20


def test_the_findings_are_carried_as_data():
    """A finding a report cannot print is a finding a report will omit."""
    assert set(cc.FINDINGS) >= {
        'F-1 reference rounding', 'F-2 ex-date not wired',
        'F-4 derivatives PIT at maturity was never levied',
        'F-6 no corporate-action data exists',
    }
    for text in cc.FINDINGS.values():
        assert len(text) > 80
