"""The corporate-action engine: the ex-date reference, the holding, the orders.

Every test names the rule it pins and says whether that rule is **gazetted**,
**market practice** or a **choice this module made**. That three-way split is
the whole point of the module: rulebook 3.6 gazettes the *principle* of the
ex-date adjustment and gazettes nothing about its algebra, so a test suite that
did not distinguish them would assert a broker's arithmetic as market law.

The tests that would be easiest to get wrong, and that a reader should look at
first:

* :func:`test_a_cash_dividend_is_vnd_and_the_close_is_thousands_of_dong` -- the
  unit seam. A 2,000d dividend against a 25.5 HOSE close is 23.5, not -1974.5.
* :func:`test_a_combined_event_is_one_event_and_not_two_applied_in_sequence` --
  the reason HOSE gazettes ex-rights codes 03/05/06/07 at all.
* :func:`test_the_cash_leg_pays_on_unsettled_parcels_because_the_record_date_decides`
  -- who gets the dividend, and why settlement state is the wrong question.
"""

from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

import pytest

from plutus.core.order import OrderType, Side
from plutus.market.broker import BrokerTerms
from plutus.market.protocol import Order, Resolution
from plutus.market.session.corporate import (ARITHMETIC, PROVENANCE,
                                             CorporateAction,
                                             CorporateActionAudit,
                                             CorporateActionEngine,
                                             CorporateActionKind,
                                             CorporateActionSchedule,
                                             RestingOrderPolicy,
                                             RightsSubscriptionUnfunded,
                                             UnhandledCorporateActionError,
                                             UnsourcedCorporateAction,
                                             adjusted_reference,
                                             quantity_factor,
                                             round_to_quotation_unit)
from plutus.market.session.ledgers import (CashLedger, EncumbranceLedger,
                                           HoldingsLedger, SecuritiesAccount)
from plutus.market.session.orders import OrderBookOfRecord, OrderIdFactory
from plutus.market.session.types import (AccountRef, BrokerProfile, Confidence,
                                         OrderId, Pool, ResourceKind,
                                         SessionProvenance, Venue)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

#: A session inside the corpus window, after every carve-out this module
#: knows about is in force, so a test that means to exercise a dated boundary
#: has to say so.
EX_DATE = date(2022, 6, 15)
T0 = datetime(2022, 6, 15, 9, 0)
CUM_DATE = datetime(2022, 6, 14, 9, 30)
SETTLES = datetime(2022, 6, 16, 13, 0)

#: HOSE's quotation unit at a mid-price. Its grid is banded and the tick is
#: resolved by ``RuleSet.tick_size``; the tests pass it in rather than
#: resolving it, because rounding direction is what is under test here.
HSX_TICK_50 = Decimal('0.05')


def account(cash='150000000', holdings=None, profile=None):
    """A securities account on one shared encumbrance ledger."""
    enc = EncumbranceLedger()
    return SecuritiesAccount(
        AccountRef.securities('SEC-0001'),
        CashLedger(Decimal(cash), BrokerTerms(), enc),
        HoldingsLedger(enc, initial=holdings),
        enc,
        profile=profile or BrokerProfile(name='test-retail-free'),
    )


def book(acct=None):
    """An order book wired the way ``ExchangeSession.build`` wires it.

    ``on_terminal`` bound to the account's ``release`` is not optional
    decoration: it is what makes "an order reaching a terminal state without
    releasing its reservation" impossible by construction, and the cancelling
    branch of the corporate-action engine relies on exactly that hook rather
    than releasing by hand.
    """
    return OrderBookOfRecord(
        OrderIdFactory(),
        on_terminal=(lambda record, transition, ts: None) if acct is None
        else (lambda record, transition, ts: acct.release(record.order_id, ts)))


def an_order(ticker='FPT', side=Side.SELL, quantity=1000, price='96.0'):
    return Order(ticker=ticker, side=side, quantity=quantity,
                 order_type=OrderType.LIMIT,
                 limit_price=None if price is None else Decimal(price))


class StubSession:
    """The four public methods :class:`SessionView` needs, and nothing else.

    A stand-in rather than a real ``ExchangeSession`` on purpose: the audit's
    claim is that it reads **only public API**, and a stub that offers only
    those four methods is what makes the claim testable. If the audit ever
    reaches for ``_securities`` or ``_book``, every test here raises
    ``AttributeError``.
    """

    def __init__(self, acct, orders=(), now=T0,
                 period_start=date(2022, 6, 1), period_end=date(2022, 6, 30)):
        self._account = acct
        self._orders = tuple(orders)
        self._now = now
        self._provenance = SessionProvenance(
            rulebook_id='vn-2020-2026', resolution=Resolution.DAILY,
            period_start=period_start, period_end=period_end,
            venues=(Venue.HSX,), fill_policy_kind='soft',
            broker_profile_name='test-retail-free')

    def now(self):
        return self._now

    def provenance(self):
        return self._provenance

    def orders(self, *, state=None, ticker=None):
        return tuple(r for r in self._orders
                     if ticker is None or r.order.ticker == ticker)

    def holdings(self, ticker):
        return self._account.holding(ticker)


# --------------------------------------------------------------------------
# The arithmetic. Rulebook 3.6, and it is NOT gazetted.
# --------------------------------------------------------------------------

def test_the_arithmetic_declares_that_it_is_not_gazetted():
    """Rulebook 3.6 marks the formula NOT IN ANY GAZETTED DOCUMENT and says
    to mark it clearly in the paper. The claim is carried as data on the
    citation and in ``PROVENANCE`` so a published result can print it, rather
    than as prose in a docstring nobody renders."""
    assert ARITHMETIC.confidence is Confidence.MEDIUM
    assert 'NOT IN ANY GAZETTED DOCUMENT' in ARITHMETIC.note
    assert 'NOT GAZETTED' in PROVENANCE['arithmetic']
    for key in ('rounding_direction', 'resting_order_policy',
                'dividend_withholding_tax', 'fractional_residue'):
        assert key in PROVENANCE


def test_a_cash_dividend_is_vnd_and_the_close_is_thousands_of_dong():
    """**The unit seam.** ``cash_per_share`` is VND per share -- the unit
    ``HoldingsLedger.apply_corporate_action`` credits -- while a cash-venue
    price is quoted in thousands of dong (``CURRENCY_UNIT['HSX'] == 1000``).
    So P' = P - C/1000. Subtracting the VND figure straight off the quoted
    close turns a 2,000d dividend on a 25,500d share into a reference of
    -1974.5: invisible in a ratio, fatal in a band."""
    action = CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('2000'))

    adj = adjusted_reference(action, Decimal('25.5'), venue=Venue.HSX)

    assert adj.reference_price == Decimal('23.5')
    assert adj.currency_unit == 1000
    assert adj.quantity_factor == Decimal('1')      # cash changes no quantity
    assert adj.adjusted is True


def test_a_stock_dividend_divides_the_reference_by_one_plus_the_ratio():
    """Rulebook 3.6's degenerate form ``P' = P / (1 + b)``. A 10% stock
    dividend is b = 0.1, not 10."""
    action = CorporateAction.stock_dividend('FPT', EX_DATE, Decimal('0.1'))

    adj = adjusted_reference(action, Decimal('22'), venue=Venue.HSX)

    assert adj.reference_price == Decimal('20')
    assert adj.quantity_factor == Decimal('1.1')


def test_a_bonus_issue_has_the_same_arithmetic_as_a_stock_dividend():
    """HOSE's own ex-rights code 01 reads "stock dividend OR bonus", so the
    two are not distinguishable from the legs. The label is kept because the
    accounting differs and a caller reconciling a disclosure feed needs it to
    match; the numbers must not."""
    ratio = Decimal('0.25')
    stock = CorporateAction.stock_dividend('FPT', EX_DATE, ratio)
    bonus = CorporateAction.bonus_issue('FPT', EX_DATE, ratio)

    base = Decimal('50')
    assert (adjusted_reference(stock, base, venue=Venue.HSX).reference_price
            == adjusted_reference(bonus, base, venue=Venue.HSX).reference_price)
    assert stock.hose_code == bonus.hose_code == '01'
    assert stock.kind is not bonus.kind


def test_a_rights_issue_carries_the_subscription_price_into_the_numerator():
    """``P' = (P + Pa*a) / (1 + a)``. The subscription price is VND per share
    like every other money field, so a 10,000d subscription against a 25.0
    close is 10.0 in quote units: (25 + 10*0.5) / 1.5 = 20.

    ``take_up=True`` is stated rather than defaulted: the price leg is
    unconditional, the quantity leg is not, and the default is the arm that
    cannot report shares nobody paid for."""
    action = CorporateAction.rights_issue(
        'FPT', EX_DATE, Decimal('0.5'), Decimal('10000'))

    adj = adjusted_reference(action, Decimal('25'), venue=Venue.HSX,
                             take_up=True)

    assert adj.reference_price == Decimal('20')
    assert adj.quantity_factor == Decimal('1.5')
    # The price leg does not depend on the holder's decision.
    assert adjusted_reference(
        action, Decimal('25'), venue=Venue.HSX).reference_price == Decimal('20')


def test_a_split_divides_the_reference_and_a_consolidation_multiplies_it():
    """Rulebook 3.6: split 1->n gives ``P' = P/n`` and quantity ``x n``;
    consolidation m->1 gives ``P' = P*m`` and quantity ``/ m``. Rulebook's
    split row frames the date as the day trading **resumes**, not an ex-date,
    because QD 17 Dieu 40.1(b) halts the stock across the event."""
    split = CorporateAction.split('FPT', EX_DATE, into=2)
    consolidation = CorporateAction.consolidation('FPT', EX_DATE, of=10)

    a = adjusted_reference(split, Decimal('40'), venue=Venue.HSX)
    b = adjusted_reference(consolidation, Decimal('4'), venue=Venue.HSX)

    assert (a.reference_price, a.quantity_factor) == (Decimal('20'),
                                                      Decimal('2'))
    assert (b.reference_price, b.quantity_factor) == (Decimal('40'),
                                                      Decimal('0.1'))


def test_a_combined_event_is_one_event_and_not_two_applied_in_sequence():
    """**The trap HOSE's ex-rights codes 03/05/06/07 exist to avoid.** The
    sourced formula divides by ``(1 + a + b)``; applying a rights issue and a
    stock dividend one after the other divides by ``(1 + a)(1 + b)``, which is
    a different -- and larger -- denominator. Here: 30/1.7 = 17.647 against
    20/1.2 = 16.667, a 5.6% error that looks entirely plausible."""
    combined = CorporateAction.combined(
        'FPT', EX_DATE, rights_ratio=Decimal('0.5'),
        subscription_price=Decimal('10000'), stock_ratio=Decimal('0.2'))

    adj = adjusted_reference(combined, Decimal('25'), venue=Venue.HSX)

    assert adj.raw_reference == Decimal('30') / Decimal('1.7')
    sequential = (Decimal('25') + Decimal('5')) / Decimal('1.5') / Decimal('1.2')
    assert adj.raw_reference != sequential
    assert combined.hose_code == '05'          # rights + stock dividend/bonus


def test_the_adjustment_conserves_the_position_value():
    """The conservation principle rulebook 3.6 says the sources agree on, even
    though the algebra itself is not gazetted: market capitalisation is
    unchanged across the event. 100 shares at 22.0 is 2,200; 110 at 20.0 is
    2,200."""
    action = CorporateAction.stock_dividend('FPT', EX_DATE, Decimal('0.1'))
    adj = adjusted_reference(action, Decimal('22'), venue=Venue.HSX)

    before = Decimal('100') * adj.base_price
    after = (Decimal('100') * adj.quantity_factor) * adj.reference_price
    assert before == after


def test_rights_that_lapse_leave_the_quantity_alone_but_still_move_the_price():
    """The asymmetry a holder who does not subscribe actually experiences. The
    exchange adjusts the whole market's reference before anyone has
    subscribed, so the price leg is unconditional; the quantity leg is not,
    and whether to take up a right is a portfolio decision design section 3
    puts on the caller's side."""
    action = CorporateAction.rights_issue(
        'FPT', EX_DATE, Decimal('0.5'), Decimal('10000'))

    taken = adjusted_reference(action, Decimal('25'), venue=Venue.HSX,
                               take_up=True)
    lapsed = adjusted_reference(action, Decimal('25'), venue=Venue.HSX,
                                take_up=False)

    assert taken.reference_price == lapsed.reference_price == Decimal('20')
    assert taken.quantity_factor == Decimal('1.5')
    assert lapsed.quantity_factor == Decimal('1')
    assert quantity_factor(action, take_up=False) == Decimal('1')


def test_an_unstated_take_up_never_reports_shares_nobody_paid_for():
    """**The pure-arithmetic half of the rights defect.** ``quantity_factor``
    and :func:`adjusted_reference` move no money, so a default here is safe --
    but only one default is. ``1 + a`` says the holder received the rights
    shares, and receiving them costs ``a x Pa`` per share held; reporting that
    factor without anyone having stated the subscription is the number that
    lets a caller mark a position they never paid for. The default is
    therefore the lapse, and the take-up has to be asked for."""
    action = CorporateAction.rights_issue(
        'FPT', EX_DATE, Decimal('0.5'), Decimal('10000'))

    assert quantity_factor(action) == Decimal('1')
    assert adjusted_reference(
        action, Decimal('25'), venue=Venue.HSX).quantity_factor == Decimal('1')
    # A stock leg is free and needs no such decision.
    assert quantity_factor(
        CorporateAction.stock_dividend('FPT', EX_DATE, Decimal('0.1'))
    ) == Decimal('1.1')


# --------------------------------------------------------------------------
# Rounding to the quotation unit -- gazetted that it happens, not which way
# --------------------------------------------------------------------------

def test_the_reference_is_rounded_to_the_tick_and_the_direction_is_a_parameter():
    """"Gia tham chieu duoc lam tron theo don vi yet gia" is gazetted (QD
    22/2026 Dieu 33.8); **the direction is stated nowhere**, and rulebook 3.5
    notes the rule only bites after a corporate-action adjustment -- "and that
    case is untested". So the direction is a parameter. Half-up is the default
    because it is the only direction with corpus evidence anywhere in the
    domain (UPCoM references, 98.70% of 410,999 name-days)."""
    action = CorporateAction.stock_dividend('FPT', EX_DATE, Decimal('0.03'))

    half_up = adjusted_reference(action, Decimal('25.5'), venue=Venue.HSX,
                                 tick=HSX_TICK_50)
    floor = adjusted_reference(action, Decimal('25.5'), venue=Venue.HSX,
                               tick=HSX_TICK_50, rounding=ROUND_FLOOR)
    ceiling = adjusted_reference(action, Decimal('25.5'), venue=Venue.HSX,
                                 tick=HSX_TICK_50, rounding=ROUND_CEILING)

    assert half_up.raw_reference == Decimal('25.5') / Decimal('1.03')
    assert half_up.reference_price == Decimal('24.75')
    assert floor.reference_price == Decimal('24.75')
    assert ceiling.reference_price == Decimal('24.80')
    assert half_up.rounding == ROUND_HALF_UP


def test_an_unresolved_tick_leaves_the_reference_unrounded():
    """``RuleSet.tick_size`` returns ``None`` when no price tier matches, which
    is a real answer and not an absence. Rounding to a tick nobody resolved
    would be inventing a grid."""
    assert round_to_quotation_unit(Decimal('24.7573'), None) == Decimal('24.7573')
    assert round_to_quotation_unit(Decimal('24.7573'), Decimal('0')) == Decimal('24.7573')


# --------------------------------------------------------------------------
# The two sourced no-adjustment cases. Reference untouched, band widened.
# --------------------------------------------------------------------------

def test_a_treasury_share_dividend_leaves_the_reference_alone_but_still_pays():
    """QD 352 Dieu 13.1(a) and 10.4(b): a dividend or bonus paid in **treasury**
    shares is HOSE ex-rights code 16, the only code that widens the band --
    +/-20%, and "the reference is NOT adjusted, the wide band absorbs the
    drop". The holder still receives the shares: the carve-out is about the
    price leg, and reading it as cancelling the quantity leg too would quietly
    confiscate them."""
    action = CorporateAction.stock_dividend(
        'FPT', EX_DATE, Decimal('0.1'), treasury_shares=True)

    adj = adjusted_reference(action, Decimal('22'), venue=Venue.HSX)

    assert adj.adjusted is False
    assert adj.reference_price == adj.base_price == Decimal('22')
    assert adj.quantity_factor == Decimal('1.1')          # shares still arrive
    assert adj.widened_band_case == 'treasury_dividend_ex_date'
    assert action.hose_code == '16'


def test_the_treasury_carve_out_is_dated_and_per_venue():
    """The carve-out starts 2021-07-05 at HOSE (QD 352), only with QD 17 on
    2022-03-31 at HNX -- QD 17 is the first VNX instrument covering HNX and
    HOSE's own decision does not bind it -- and 2022-11-16 at UPCoM (QD 34).
    Before its venue's date the ordinary adjustment applies, which is the
    sourced behaviour of that interval and not a gap."""
    early = CorporateAction.stock_dividend(
        'SHS', date(2022, 1, 10), Decimal('0.1'), treasury_shares=True)
    late = CorporateAction.stock_dividend(
        'SHS', date(2022, 4, 10), Decimal('0.1'), treasury_shares=True)

    before = adjusted_reference(early, Decimal('22'), venue=Venue.HNX)
    after = adjusted_reference(late, Decimal('22'), venue=Venue.HNX)

    assert before.adjusted is True and before.reference_price == Decimal('20')
    assert after.adjusted is False and after.reference_price == Decimal('22')


def test_a_cash_dividend_at_or_above_the_close_is_not_adjusted_from_2022():
    """VNX QD 17 Dieu 31.6(d): adjusting would drive the reference to zero or
    negative, so it is not adjusted and the band is widened instead. The cash
    still arrives -- only the price leg is suspended."""
    action = CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('30000'))

    adj = adjusted_reference(action, Decimal('25.5'), venue=Venue.HSX)

    assert adj.adjusted is False
    assert adj.reference_price == Decimal('25.5')
    assert adj.cash_per_share == Decimal('30000')
    assert adj.widened_band_case == 'cash_dividend_ge_reference'


def test_the_large_cash_carve_out_is_wider_than_its_own_reason_on_a_combined_event():
    """**A documented limit, pinned so it cannot drift into an invention.** The
    carve-out's gazetted test is ``C >= P`` against the prior close, and the
    reason given for it is that adjusting "would drive the reference to zero or
    negative". On HOSE ex-rights code 06 the two part company: a rights leg
    puts ``+Pa*a`` in the numerator, so (25 + 40 - 30) / 2 = 17.5 is a
    perfectly ordinary reference and the carve-out fires anyway.

    Narrowing the test to the numerator would be **inventing** the rule -- the
    text names a cash dividend and tests a close -- so the sourced test is
    applied as written and the limit is recorded rather than papered over."""
    action = CorporateAction.combined(
        'FPT', EX_DATE, cash_per_share=Decimal('30000'),
        rights_ratio=Decimal('1'), subscription_price=Decimal('40000'))

    adj = adjusted_reference(action, Decimal('25'), venue=Venue.HSX,
                             take_up=True)

    assert adj.adjusted is False
    assert adj.reference_price == Decimal('25')          # not the 17.5 below
    assert adj.widened_band_case == 'cash_dividend_ge_reference'
    assert action.hose_code == '06'


def test_the_same_dividend_before_the_carve_out_refuses_to_invent_a_reference():
    """The carve-out is **NEW at 2022-03-31**: rulebook 3.6 records that QD 352
    Dieu 10.4 does not list the case. For an earlier ex-date nothing sourced
    says what the reference becomes, so the module raises rather than clamping
    to a number no document supports. Rulebook 3.4's clamp-at-the-reference
    rule governs the FLOOR and must not be read across."""
    action = CorporateAction.cash_dividend(
        'FPT', date(2021, 11, 10), Decimal('30000'))

    with pytest.raises(UnsourcedCorporateAction) as exc:
        adjusted_reference(action, Decimal('25.5'), venue=Venue.HSX)

    assert '2022-03-31' in str(exc.value)
    assert 'FLOOR' in str(exc.value)


def test_upcom_measures_the_large_dividend_against_its_own_vwap_reference():
    """UPCoM's carve-out is QD 34 Dieu 18.2(d), effective 2022-11-16, and its
    base is the prior session's round-lot VWAP rather than a close -- a real
    per-venue difference. What this pins is the date: the same event on the
    same day is carved out at HOSE and refused at UPCoM."""
    action = CorporateAction.cash_dividend(
        'ABC', date(2022, 6, 15), Decimal('30000'))

    hsx = adjusted_reference(action, Decimal('25.5'), venue=Venue.HSX)
    assert hsx.adjusted is False

    with pytest.raises(UnsourcedCorporateAction):
        adjusted_reference(action, Decimal('25.5'), venue=Venue.UPCOM)


# --------------------------------------------------------------------------
# The event and the schedule
# --------------------------------------------------------------------------

def test_a_split_may_not_carry_a_dividend_leg():
    """Rulebook 3.6 frames a split or consolidation as a **resumption**: the
    stock stops trading across the event, and the source gives it its own
    degenerate form of the formula. Nothing sourced says how a combined
    ratio-and-dividend session is computed, so it is refused rather than
    invented."""
    with pytest.raises(ValueError, match='RESUMPTION'):
        CorporateAction(ticker='FPT', ex_date=EX_DATE,
                        kind=CorporateActionKind.SPLIT,
                        ratio_from=1, ratio_to=2,
                        cash_per_share=Decimal('1000'))


def test_an_event_that_moves_nothing_is_refused():
    """A row with no legs leaves both the reference and the quantity where
    they were. It is a data error in the schedule, and admitting it would put
    a no-op crossing into the audit report where it reads as real."""
    with pytest.raises(ValueError, match='no legs'):
        CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('0'))


def test_treasury_shares_needs_a_stock_leg():
    """``treasury_shares`` marks a dividend or bonus PAID IN treasury shares
    (HOSE code 16). A cash dividend cannot be paid in shares, and letting the
    flag ride on a cash-only row would silently suppress a price adjustment
    that should have happened."""
    with pytest.raises(ValueError, match='cannot be paid in shares'):
        CorporateAction(ticker='FPT', ex_date=EX_DATE,
                        kind=CorporateActionKind.CASH_DIVIDEND,
                        cash_per_share=Decimal('2000'), treasury_shares=True)


def test_the_schedule_refuses_two_actions_on_one_ticker_and_session():
    """Not a uniqueness convention -- an algebraic constraint. Two events
    applied in sequence divide by ``(1+a)(1+b)`` where the formula divides by
    ``(1+a+b)``, and HOSE gazettes ex-rights codes 03, 05, 06 and 07 precisely
    because combinations happen on one session."""
    schedule = CorporateActionSchedule([
        CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('2000'))])

    with pytest.raises(ValueError, match='combined'):
        schedule.add(CorporateAction.stock_dividend(
            'FPT', EX_DATE, Decimal('0.1')))


def test_the_schedule_window_includes_both_endpoints():
    """An ex-date is a whole trading session, and a run that reached it crossed
    it. An exclusive endpoint would let a run ending on an ex-date report
    itself clean, which is the exact failure the audit exists to prevent."""
    action = CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('2000'))
    schedule = CorporateActionSchedule([action])

    assert schedule.between(EX_DATE, EX_DATE) == (action,)
    assert schedule.between(date(2022, 6, 1), EX_DATE) == (action,)
    assert schedule.between(date(2022, 6, 1), date(2022, 6, 14)) == ()


def test_the_hose_ex_rights_code_is_derived_from_the_legs():
    """Gazetted in QD 22/2025 Phu luc III S1.5 from 2025-05-05. Derived rather
    than stored so it cannot disagree with the arithmetic. A split gets
    ``None``: it is a resumption, not an ex-rights event, and codes 08-15 and
    17+ are reserved but unpublished, so guessing at one would be inventing a
    gazetted code."""
    cash = CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('2000'))
    rights = CorporateAction.rights_issue('FPT', EX_DATE, Decimal('0.5'),
                                          Decimal('10000'))
    everything = CorporateAction.combined(
        'FPT', EX_DATE, cash_per_share=Decimal('2000'),
        stock_ratio=Decimal('0.1'), rights_ratio=Decimal('0.5'),
        subscription_price=Decimal('10000'))

    assert cash.hose_code == '02'
    assert rights.hose_code == '04'
    assert everything.hose_code == '07'
    assert CorporateAction.split('FPT', EX_DATE, into=2).hose_code is None


# --------------------------------------------------------------------------
# The tranche list -- locked shape 3, and the reason the hook was additive
# --------------------------------------------------------------------------

def engine(*actions, **kw):
    return CorporateActionEngine(CorporateActionSchedule(actions), **kw)


def test_a_split_scales_every_parcel_and_preserves_the_settlement_instants():
    """Locked shape 3, through the engine rather than the raw hook. A split
    scales the settled quantity *and* every open tranche, and the tranches are
    scaled separately so their distinct ``settles_at`` survive -- which is
    only possible because the holding is a list. Collapsing them would let the
    earlier instant free the later parcel's shares, permitting exactly the
    sale the settlement rule exists to prevent."""
    acct = account(holdings={'FPT': 1000})
    monday, tuesday = datetime(2022, 6, 16, 13), datetime(2022, 6, 17, 13)
    acct.holdings_ledger.credit_unsettled('FPT', 500, monday, CUM_DATE)
    acct.holdings_ledger.credit_unsettled('FPT', 700, tuesday, CUM_DATE)
    action = CorporateAction.split('FPT', EX_DATE, into=2)

    applied = engine().apply(action, account=acct, ts=T0)

    assert applied.quantity_factor == Decimal('2')
    assert applied.holding_after.settled == 2000
    assert [(t.quantity, t.settles_at) for t in applied.holding_after.unsettled] == [
        (1000, monday), (1400, tuesday)]


def test_the_cash_leg_pays_on_unsettled_parcels_because_the_record_date_decides():
    """**Who receives a cash dividend is settled by the record date, not by
    settlement state.** The rule is the *ngay dang ky cuoi cung*, and under
    T+2 it is struck one settlement cycle after the ex-date precisely so that
    a buyer who traded on the last cum-rights session -- whose parcel is still
    unsettled on the ex-date -- is on the register when it is. Paying only
    settled parcels would deny the dividend to exactly the buyer the T+2 cycle
    was designed to include, and would do it silently."""
    acct = account(cash='0', holdings={'FPT': 1000})
    acct.holdings_ledger.credit_unsettled('FPT', 500, SETTLES, CUM_DATE)
    action = CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('2000'))

    applied = engine().apply(action, account=acct, ts=T0)

    assert applied.holding_before.settled == 1000
    assert applied.holding_before.unsettled_quantity == 500
    assert applied.cash_leg == Decimal('3000000')      # 1,500 shares x 2,000d
    assert acct.cash().settled_balance == Decimal('3000000')


def test_the_cash_leg_is_credited_gross_of_the_dividend_withholding():
    """The 5% dividend withholding is **not** applied, and the rulebook
    carries no charge row for it at all. Applying it here would put a tax rate
    where no charge table can see it, so the credit is gross and the omission
    is on the record rather than in a comment."""
    acct = account(cash='0', holdings={'FPT': 1000})
    applied = engine().apply(
        CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('2000')),
        account=acct, ts=T0)

    assert applied.cash_leg_is_gross is True
    assert applied.cash_leg == Decimal('2000000')     # not 1,900,000
    assert acct.cash_ledger.charges() == ()
    assert 'NOT APPLIED' in PROVENANCE['dividend_withholding_tax']


def test_the_fractional_residue_is_reported_and_never_priced():
    """Share quantities are whole and the entitlement is floored, but **no
    source obtained states how the residue is bought out or at what price**,
    so it is reported and never priced. It is also the visible cost of the
    per-parcel flooring locked shape 3 requires: 105 settled and 105 unsettled
    at b = 0.3 floor to 136 and 136, losing 0.5 of a share twice, where VSDC
    allocating on the registered 210 would lose 0."""
    acct = account(holdings={'FPT': 105})
    acct.holdings_ledger.credit_unsettled('FPT', 105, SETTLES, CUM_DATE)

    applied = engine().apply(
        CorporateAction.stock_dividend('FPT', EX_DATE, Decimal('0.3')),
        account=acct, ts=T0)

    assert applied.holding_after.settled == 136
    assert applied.holding_after.unsettled_quantity == 136
    assert applied.fractional_residue == Decimal('1.0')
    assert 'UNSOURCED' in PROVENANCE['fractional_residue']


def test_applying_an_action_to_an_unheld_ticker_leaves_no_trace():
    """A market-wide schedule applied blindly must not make the account claim
    exposure it never had. ``HoldingsLedger.tickers`` is the account's own
    answer to "what did this run touch" and is what the audit sweeps, so
    writing a zero back for an unheld name would report exposure to every
    ticker in the schedule."""
    acct = account(holdings={'FPT': 1000})

    applied = engine().apply(
        CorporateAction.stock_dividend('VIC', EX_DATE, Decimal('0.1')),
        account=acct, ts=T0)

    assert applied.cash_leg == Decimal('0')
    assert acct.holdings_ledger.tickers() == frozenset({'FPT'})
    assert acct.holding('VIC').total == 0


# --------------------------------------------------------------------------
# The rights subscription -- the one leg of the formula that COSTS money
# --------------------------------------------------------------------------

def test_a_taken_up_rights_issue_debits_what_the_subscription_cost():
    """**Money conservation across the event, which is the whole claim of the
    arithmetic.** ``ARITHMETIC`` records that what the unsourced formula
    encodes is that market capitalisation is unchanged across it: the price
    falls by exactly the value the new shares dilute in, and for a rights issue
    part of that value is *paid in*, not given. 1,000 VIC at 45.0 is 45m on a
    150m cash balance; a 1-for-1 rights issue at 10,000d takes the reference to
    (45 + 10)/2 = 27.5 and the holding to 2,000, which is 55m -- and the extra
    10m is the subscription, which has to leave the cash balance or the
    position is worth 10m more than it was a moment earlier for no reason.

    A deep-discount rights issue is the ordinary Vietnamese case, so this is
    not an edge: it is the shape of most of them."""
    acct = account(cash='150000000', holdings={'VIC': 1000})
    action = CorporateAction.rights_issue(
        'VIC', EX_DATE, Decimal('1'), Decimal('10000'))

    applied = engine().apply(action, account=acct, ts=T0,
                             base_price=Decimal('45.0'), venue=Venue.HSX,
                             tick=HSX_TICK_50, take_up=True)

    assert applied.subscription_shares == 1000
    assert applied.subscription_outlay == Decimal('10000000')
    assert applied.subscription_outlay_is_debited is True
    assert acct.cash().settled_balance == Decimal('140000000')
    assert acct.holding('VIC').total == 2000

    unit = Decimal(1000)                       # HSX quotes thousands of dong
    before = Decimal('150000000') + Decimal('1000') * Decimal('45.0') * unit
    after = (acct.cash().settled_balance
             + Decimal(acct.holding('VIC').total)
             * applied.reference.reference_price * unit)
    assert before == after == Decimal('195000000')


def test_rights_that_lapse_cost_nothing_and_grow_nothing():
    """The other arm, and the one that needs no cash. The price leg still
    lands -- the exchange adjusts the whole market's reference before anyone
    has subscribed -- so a lapsed right is a real loss, visible in the mark and
    not hidden by a quantity that grew for free."""
    acct = account(cash='150000000', holdings={'VIC': 1000})
    action = CorporateAction.rights_issue(
        'VIC', EX_DATE, Decimal('1'), Decimal('10000'))

    applied = engine().apply(action, account=acct, ts=T0,
                             base_price=Decimal('45.0'), venue=Venue.HSX,
                             tick=HSX_TICK_50, take_up=False)

    assert applied.subscription_shares == 0
    assert applied.subscription_outlay == Decimal('0')
    assert acct.cash().settled_balance == Decimal('150000000')
    assert acct.holding('VIC').total == 1000
    assert applied.reference.reference_price == Decimal('27.5')


def test_the_engine_refuses_to_guess_whether_the_holder_subscribed():
    """**Nothing sourced settles this and the engine does not invent it.**
    Whether a right is exercised, sold or lapsed is a portfolio decision, and
    design section 3 puts every portfolio decision on the caller's side -- so
    the one place where the decision spends the holder's cash is the one place
    that must not have a default. The refusal names both arms and the money."""
    acct = account(cash='150000000', holdings={'VIC': 1000})
    action = CorporateAction.rights_issue(
        'VIC', EX_DATE, Decimal('1'), Decimal('10000'))

    with pytest.raises(ValueError, match='take_up'):
        engine().apply(action, account=acct, ts=T0)

    with pytest.raises(ValueError, match='take_up'):
        engine(action).apply_due(T0, account=acct)

    # Nothing moved: the refusal is before any leg is applied.
    assert acct.holding('VIC').total == 1000
    assert acct.cash().settled_balance == Decimal('150000000')


def test_an_event_with_no_rights_leg_needs_no_decision():
    """``take_up`` is a rights-leg question. A cash dividend, a stock dividend
    and a split carry no subscription, so demanding a decision there would be
    ceremony -- and ceremony is what trains a caller to pass the flag without
    reading it."""
    acct = account(cash='0', holdings={'FPT': 1000})

    applied = engine().apply(
        CorporateAction.stock_dividend('FPT', EX_DATE, Decimal('0.1')),
        account=acct, ts=T0)

    assert applied.subscription_outlay == Decimal('0')
    assert acct.holding('FPT').total == 1100


def test_a_subscription_the_account_cannot_fund_is_refused_before_anything_moves():
    """A rights issue is not free money and an account that cannot pay for it
    has not subscribed. The check is made **before** the holdings leg, because
    a refusal that leaves the quantity scaled and the cash untouched is the
    same fabrication by another route.

    ``Cash.available`` is the test -- design section 7.0's one definition of
    spendable cash -- not the settled balance, because cash committed to a
    live buy order is already promised."""
    acct = account(cash='9000000', holdings={'VIC': 1000})
    action = CorporateAction.rights_issue(
        'VIC', EX_DATE, Decimal('1'), Decimal('10000'))
    eng = engine()

    with pytest.raises(RightsSubscriptionUnfunded) as exc:
        eng.apply(action, account=acct, ts=T0, take_up=True)

    assert '10000000' in str(exc.value) and 'take_up=False' in str(exc.value)
    assert acct.holding('VIC').total == 1000
    assert acct.cash().settled_balance == Decimal('9000000')
    assert eng.applied() == ()                 # nothing was recorded either


def test_the_subscription_is_charged_only_on_whole_rights_shares():
    """The entitlement is floored per parcel (locked shape 3), so the holder
    receives whole shares and must be charged for whole shares. 105 settled and
    105 unsettled at a = 0.5 receive 52 each: charging the unfloored 105 would
    bill the holder for a share the ledger never credited.

    In a **combined** event the per-parcel floor cannot be split between the
    rights leg and the free stock leg without inventing a rule nobody sourced.
    The module attributes the residue to the free leg, so the charge is never
    for more shares than the rights leg alone would have produced."""
    acct = account(cash='150000000', holdings={'VIC': 105})
    acct.holdings_ledger.credit_unsettled('VIC', 105, SETTLES, CUM_DATE)
    action = CorporateAction.rights_issue(
        'VIC', EX_DATE, Decimal('0.5'), Decimal('10000'))

    applied = engine().apply(action, account=acct, ts=T0, take_up=True)

    assert applied.subscription_shares == 104          # 52 + 52, not 105
    assert applied.subscription_outlay == Decimal('1040000')
    assert acct.holding('VIC').total == 314            # 157 + 157
    assert acct.cash().settled_balance == Decimal('148960000')


def test_the_subscription_outlay_is_on_the_record_beside_the_gross_cash_leg():
    """``cash_leg_is_gross`` exists because a money fact a report can omit is a
    money fact a report will omit. The subscription is the same kind of fact
    and is carried the same way: the shares, the outlay, and the net of the two
    cash legs on a combined rights-plus-dividend event (HOSE ex-rights code
    06), where the dividend credit and the subscription debit move in opposite
    directions on one session."""
    acct = account(cash='150000000', holdings={'VIC': 1000})
    action = CorporateAction.combined(
        'VIC', EX_DATE, rights_ratio=Decimal('1'),
        subscription_price=Decimal('10000'), cash_per_share=Decimal('2000'))

    applied = engine().apply(action, account=acct, ts=T0, take_up=True)

    assert action.hose_code == '06'
    assert applied.cash_leg == Decimal('2000000')
    assert applied.subscription_outlay == Decimal('10000000')
    assert applied.net_cash_leg == Decimal('-8000000')
    assert acct.cash().settled_balance == Decimal('142000000')
    assert 'THE ONE LEG THAT COSTS MONEY' in PROVENANCE['rights_subscription']


# --------------------------------------------------------------------------
# The open question: a resting order across the ex-date
# --------------------------------------------------------------------------

def a_resting_sell(bk, acct, quantity=1000, price='96.0', ts=CUM_DATE):
    """A sell order on the book with a real share reservation behind it."""
    order = an_order(quantity=quantity, price=price)
    order_id = OrderId('SELL-1')
    enc = acct.reserve_for_sell(order_id, order, Venue.HSX, ts)
    assert hasattr(enc, 'original_quantity'), enc      # not a Rejected
    bk.accept(order, Venue.HSX, ts, order_id=order_id, encumbrances=(enc,))
    bk.rest(order_id, ts)
    return order_id


def test_a_resting_order_is_cancelled_across_the_ex_date_by_default():
    """**The design spec's open question, and this is a CHOICE, not a rule.**
    No Vietnamese document addresses an order live across an ex-date -- and
    rulebook 2.3 explains the silence: an LO is a day order that "dies at the
    end of the last matching phase" (QD 352 Dieu 14.1(c), 17.2), ATO/ATC never
    rest and never carry, and MP/MTL/MOK/MAK are decided at entry. **No order
    type in Vietnam survives a session close**, so no document had reason to
    write the rule. Cancelling is therefore not merely conservative, it is
    what the day-order rule implies: any order still live here is one the real
    market had already killed."""
    acct = account(holdings={'FPT': 1000})
    bk = book(acct)
    order_id = a_resting_sell(bk, acct)
    assert acct.holding('FPT').committed == 1000

    eng = engine()                      # the DEFAULT, asserted below
    assert eng.resting_order_policy is RestingOrderPolicy.CANCEL
    applied = eng.apply(CorporateAction.split('FPT', EX_DATE, into=2),
                        account=acct, ts=T0, book=bk)

    outcome, = applied.resting_orders
    assert outcome.policy is RestingOrderPolicy.CANCEL
    assert (outcome.quantity_before, outcome.quantity_after) == (1000, 0)
    assert bk.get(order_id).state.value == 'cancelled'
    assert acct.holding('FPT').committed == 0        # invariant 4 restored
    assert acct.holding('FPT').settled == 2000
    assert 'A CHOICE, NOT A RULE' in PROVENANCE['resting_order_policy']


def test_the_scale_policy_rescales_both_the_quantity_and_the_limit_price():
    """The other arm of the open question, and the price leg has a gazetted
    precedent: QD 22/2026 Dieu 36 adjusts a covered warrant's strike by
    ``adjusted underlying reference / unadjusted underlying reference``, which
    is exactly ``ReferenceAdjustment.ratio``. A 1->2 split doubles 1,000
    shares to 2,000 and halves a 96.0 limit to 48.0."""
    acct = account(holdings={'FPT': 1000})
    bk = book(acct)
    order_id = a_resting_sell(bk, acct)

    applied = engine(resting_orders=RestingOrderPolicy.SCALE).apply(
        CorporateAction.split('FPT', EX_DATE, into=2),
        account=acct, ts=T0, book=bk, base_price=Decimal('96.0'),
        venue=Venue.HSX, lot=100)

    outcome, = applied.resting_orders
    assert outcome.policy is RestingOrderPolicy.SCALE
    assert (outcome.quantity_before, outcome.quantity_after) == (1000, 2000)
    assert outcome.limit_price_after == Decimal('48.0')
    assert outcome.lot_enforced is True
    assert bk.get(order_id).state.value == 'resting'


def test_a_scaled_limit_outside_the_ex_date_band_is_cancelled_not_rested():
    """The worst finding of the corporate-charges audit, closed.

    Measured: a VIB sell resting at the published ceiling of 53.40 was scaled
    across the ex-date to ``38.14285714285714285714285714`` -- 26 significant
    digits, off the 0.05 grid, and **8.31 below the published floor of
    46.45** -- and the fill pass matched it, levying 14,418 of exchange fee
    and 53,400 of PIT on a 53,400,000 trade value the exchange could not have
    printed. Eight of nine identities passed; the ninth failed for an
    unrelated and expected reason, so the impossible print was masked.

    ``book.amend`` deliberately does not re-run admission, so nothing
    downstream re-checked the band. The engine cannot resolve a band for
    itself, so it takes one -- and refuses when the scaled price falls
    outside it, which is the fallback this branch already uses for a
    degenerate quantity.
    """
    acct = account(holdings={'FPT': 1000})
    bk = book(acct)
    order_id = a_resting_sell(bk, acct)          # rests at 96.0

    # A 1->2 split halves the limit to 48.0, below a floor of 60.0.
    applied = engine(resting_orders=RestingOrderPolicy.SCALE).apply(
        CorporateAction.split('FPT', EX_DATE, into=2),
        account=acct, ts=T0, book=bk, base_price=Decimal('96.0'),
        venue=Venue.HSX, lot=100,
        band=(Decimal('60.0'), Decimal('80.0')))

    outcome, = applied.resting_orders
    assert outcome.policy is RestingOrderPolicy.SCALE
    assert bk.get(order_id).state.value == 'cancelled'
    assert 'outside the ex-date band' in outcome.reason
    assert outcome.limit_price_after is None
    # The reservation went with the order, through the book's terminal hook.
    assert acct.holding('FPT').committed == 0

    # Control: the same split with a band the scaled price sits inside is
    # rested, so the guard refuses prices and not corporate actions.
    acct2 = account(holdings={'FPT': 1000})
    bk2 = book(acct2)
    ok_id = a_resting_sell(bk2, acct2)
    engine(resting_orders=RestingOrderPolicy.SCALE).apply(
        CorporateAction.split('FPT', EX_DATE, into=2),
        account=acct2, ts=T0, book=bk2, base_price=Decimal('96.0'),
        venue=Venue.HSX, lot=100,
        band=(Decimal('40.0'), Decimal('60.0')))
    assert bk2.get(ok_id).state.value == 'resting'
    assert bk2.get(ok_id).order.limit_price == Decimal('48.0')


def test_a_scaled_limit_is_put_on_the_order_tick_grid_not_the_reference_one():
    """``tick`` rounds the reference; ``order_tick`` rounds the limit.

    One parameter served both roundings and they are incompatible: F-1 says
    the HOSE ex-date reference must **not** be tick-rounded, and a limit price
    must be or it can never match. A caller resolving the conflict in favour
    of the reference -- which is the correct choice -- got a limit price with
    26 significant digits.

    A 3-for-2 bonus takes 96.0 to 64.0 exactly; a 1.35 stock dividend takes it
    to 71.111... , which is what needs a grid.
    """
    acct = account(holdings={'FPT': 1000})
    bk = book(acct)
    order_id = a_resting_sell(bk, acct)

    applied = engine(resting_orders=RestingOrderPolicy.SCALE).apply(
        CorporateAction.stock_dividend('FPT', EX_DATE, ratio=Decimal('0.35')),
        account=acct, ts=T0, book=bk, base_price=Decimal('96.0'),
        venue=Venue.HSX, lot=100, order_tick=Decimal('0.05'))

    outcome, = applied.resting_orders
    price = outcome.limit_price_after
    assert price == Decimal('71.10')
    assert (price / Decimal('0.05')) % 1 == 0, 'the limit is on the grid'
    assert bk.get(order_id).order.limit_price == price
    # Nothing unchecked is left silent: the band was not supplied and the
    # outcome says so rather than implying the price was validated.
    assert 'no ex-date band supplied' in outcome.reason
    assert 'no order tick supplied' not in outcome.reason


def test_scaling_re_takes_the_reservation_so_invariant_4_still_holds():
    """The book's ``amend`` does not touch encumbrances -- a reservation
    change would have to re-run admission, which is ``exchange.py``'s
    composition. So the scaling branch releases and re-takes by hand, and the
    share reservation must track the rescaled holding exactly: 1,000 committed
    against 1,000 settled becomes 2,000 against 2,000, not 1,000 against
    2,000, which would let the caller sell the same parcel twice."""
    acct = account(holdings={'FPT': 1000})
    bk = book(acct)
    a_resting_sell(bk, acct)

    engine(resting_orders=RestingOrderPolicy.SCALE).apply(
        CorporateAction.split('FPT', EX_DATE, into=2),
        account=acct, ts=T0, book=bk, base_price=Decimal('96.0'),
        venue=Venue.HSX, lot=100)

    holding = acct.holding('FPT')
    assert (holding.settled, holding.committed, holding.sellable) == (
        2000, 2000, 0)


def test_scaling_a_cash_reservation_preserves_its_value_not_its_quantity():
    """A buy reserves cash, and the corporate action moves the quantity one
    way and the price the other. A 1,000-share buy reserved at 95.5 becomes
    2,000 shares at 47.75 across a 1->2 split, and the reservation must be the
    same money -- scaling the quantity alone would double what the order
    commits and refuse buys the caller can afford."""
    acct = account(cash='150000000')
    bk = book(acct)
    order = an_order(side=Side.BUY, price='95.5')
    order_id = OrderId('BUY-1')
    acct.encumbrances.take(order_id, Pool.SECURITIES, ResourceKind.CASH, CUM_DATE,
                           amount=Decimal('95500000'), ticker='FPT',
                           order_quantity=1000)
    bk.accept(order, Venue.HSX, CUM_DATE, order_id=order_id)
    bk.rest(order_id, CUM_DATE)
    before = acct.cash().committed

    engine(resting_orders=RestingOrderPolicy.SCALE).apply(
        CorporateAction.split('FPT', EX_DATE, into=2),
        account=acct, ts=T0, book=bk, base_price=Decimal('95.5'),
        venue=Venue.HSX, lot=100)

    assert acct.cash().committed == before == Decimal('95500000')
    assert bk.get(order_id).order.limit_price == Decimal('47.75')
    assert bk.get(order_id).order.quantity == 2000


def test_a_scaled_order_with_nothing_left_is_cancelled_instead():
    """A remainder that scales below the round lot is not an order. A 10->1
    consolidation takes the 500 shares still working down to 50, and an order
    off the lot can never fill (``ROUND_LOT``), so the scaling branch falls
    back to cancelling and says which arm it took."""
    acct = account(holdings={'FPT': 10000})
    bk = book(acct)
    order = an_order(quantity=1000)
    order_id = OrderId('SELL-2')
    enc = acct.reserve_for_sell(order_id, order, Venue.HSX, CUM_DATE)
    bk.accept(order, Venue.HSX, CUM_DATE, order_id=order_id, encumbrances=(enc,))
    bk.rest(order_id, CUM_DATE)
    bk.apply_fill(order_id, _a_fill(order_id, 500))

    applied = engine(resting_orders=RestingOrderPolicy.SCALE).apply(
        CorporateAction.consolidation('FPT', EX_DATE, of=10),
        account=acct, ts=T0, book=bk, lot=100)

    outcome, = applied.resting_orders
    assert outcome.policy is RestingOrderPolicy.SCALE
    assert outcome.quantity_after == 0
    assert 'cancelled instead' in outcome.reason
    assert bk.get(order_id).state.value == 'cancelled'


def test_a_consolidation_scales_the_remainder_rather_than_killing_the_order():
    """**The unit defect.** The factor belongs to the shares still working, not
    to the order's headline quantity: ``original`` is
    ``filled + remaining``, and ``filled`` is a pre-event number that the event
    does not touch. Scaling ``original`` and then subtracting the *unscaled*
    ``filled`` subtracts pre-consolidation units from post-consolidation units,
    and the difference is ``filled x (factor - 1)`` shares of pure arithmetic
    error -- here 2,000 x (0.1 - 1) = -1,800, which is why a perfectly ordinary
    20%-filled order came out negative and was cancelled as "nothing left"
    while 8,000 shares were still working. 8,000 remaining consolidated 10->1
    is 800 remaining, and the order lives."""
    acct = account(holdings={'FPT': 20000})
    bk = book(acct)
    order = an_order(quantity=10000)
    order_id = OrderId('SELL-4')
    enc = acct.reserve_for_sell(order_id, order, Venue.HSX, CUM_DATE)
    bk.accept(order, Venue.HSX, CUM_DATE, order_id=order_id, encumbrances=(enc,))
    bk.rest(order_id, CUM_DATE)
    bk.apply_fill(order_id, _a_fill(order_id, 2000))

    applied = engine(resting_orders=RestingOrderPolicy.SCALE).apply(
        CorporateAction.consolidation('FPT', EX_DATE, of=10),
        account=acct, ts=T0, book=bk, lot=100)

    outcome, = applied.resting_orders
    record = bk.get(order_id)
    assert record.state.value == 'partially_filled'    # alive, not cancelled
    assert record.is_terminal is False
    assert (outcome.quantity_before, outcome.quantity_after) == (8000, 800)
    assert (record.filled_quantity, record.remaining_quantity) == (2000, 800)
    assert record.original_quantity == 2800        # filled + remaining, exactly


def test_scaling_a_partly_filled_buy_preserves_the_value_it_reserved():
    """The money face of the same defect. A buy reserves cash, and a 1->2 split
    doubles the working quantity while halving the price, so the reservation is
    the same money before and after. Scaling the order's headline quantity
    instead inflates the remainder by ``filled x (factor - 1)`` -- 400 extra
    shares here -- and the re-taken cash reservation grows with it, committing
    money the order can never spend and refusing buys the caller can afford."""
    acct = account(cash='150000000')
    bk = book(acct)
    order = an_order(side=Side.BUY, price='95.5')
    order_id = OrderId('BUY-2')
    acct.encumbrances.take(order_id, Pool.SECURITIES, ResourceKind.CASH,
                           CUM_DATE, amount=Decimal('95500000'), ticker='FPT',
                           order_quantity=1000)
    bk.accept(order, Venue.HSX, CUM_DATE, order_id=order_id)
    bk.rest(order_id, CUM_DATE)
    bk.apply_fill(order_id, _a_fill(order_id, 400, side=Side.BUY))

    engine(resting_orders=RestingOrderPolicy.SCALE).apply(
        CorporateAction.split('FPT', EX_DATE, into=2),
        account=acct, ts=T0, book=bk, base_price=Decimal('95.5'),
        venue=Venue.HSX, lot=100)

    assert acct.cash().committed == Decimal('95500000')
    assert bk.get(order_id).order.limit_price == Decimal('47.75')
    assert bk.get(order_id).remaining_quantity == 1200


def _a_fill(order_id, quantity, price='96.0', side=Side.SELL):
    from plutus.market.session.types import Fill, FillEvidence
    return Fill(fill_id=f'F-{order_id}', order_id=order_id, ticker='FPT',
                venue=Venue.HSX, side=side, quantity=quantity,
                price=Decimal(price), ts=CUM_DATE,
                evidence=FillEvidence.TRADED_THROUGH)


# --------------------------------------------------------------------------
# Engine lifecycle
# --------------------------------------------------------------------------

def test_applying_the_same_action_twice_is_refused():
    """Compounding the factor and paying the dividend a second time is the
    quietest way to corrupt a run: nothing raises later and the holding is
    merely wrong. The engine refuses on ``(ticker, ex_date)``, which is the
    same key the schedule enforces uniqueness on."""
    acct = account(holdings={'FPT': 1000})
    eng = engine()
    action = CorporateAction.split('FPT', EX_DATE, into=2)
    eng.apply(action, account=acct, ts=T0)

    with pytest.raises(ValueError, match='already been applied'):
        eng.apply(action, account=acct, ts=T0)

    assert acct.holding('FPT').settled == 2000
    assert eng.has_applied(action) is True


def test_applying_before_the_ex_date_is_refused():
    """The entitlement is the holding at the ex-date's **open** and does not
    exist before it. Applying early would hand the adjustment to a holder who
    could still sell out cum-rights."""
    acct = account(holdings={'FPT': 1000})
    with pytest.raises(ValueError, match='does not exist before'):
        engine().apply(CorporateAction.split('FPT', EX_DATE, into=2),
                       account=acct, ts=CUM_DATE)


def test_applying_after_the_ex_date_is_applied_and_marked_late():
    """A caller who advanced past an ex-date gets the action applied, not
    skipped -- silently skipping is the failure this module exists to end --
    but the entitlement is then measured on a holding that may already include
    shares bought ON the ex-date, which are not entitled. So it is a fidelity
    warning carried on the record rather than a log line."""
    acct = account(holdings={'FPT': 1000})
    late_ts = datetime(2022, 6, 20, 9, 0)

    applied = engine().apply(CorporateAction.split('FPT', EX_DATE, into=2),
                             account=acct, ts=late_ts)

    assert applied.late is True
    assert applied.holding_after.settled == 2000


def test_due_returns_everything_not_yet_applied_up_to_the_instant():
    """``<=``, not ``==``: an action whose ex-date the caller advanced past is
    still due. It is applied late and flagged, which is strictly better than
    disappearing."""
    a = CorporateAction.cash_dividend('FPT', date(2022, 6, 10), Decimal('1000'))
    b = CorporateAction.cash_dividend('VIC', EX_DATE, Decimal('2000'))
    c = CorporateAction.cash_dividend('FPT', date(2022, 7, 1), Decimal('1000'))
    eng = engine(a, b, c)

    assert eng.due(T0) == (a, b)
    eng.apply(a, account=account(holdings={'FPT': 100}), ts=T0)
    assert eng.due(T0) == (b,)
    assert eng.due(T0, tickers=['VIC']) == (b,)


def test_a_base_price_without_a_venue_is_refused():
    """Locked shape 1 at the arithmetic's own seam. The currency unit that
    converts a VND cash leg into quote units is per venue, and so is every
    no-adjustment carve-out, so a price with no venue cannot be adjusted --
    and defaulting the venue is exactly the forbidden build."""
    acct = account(holdings={'FPT': 1000})
    with pytest.raises(ValueError, match='needs a venue'):
        engine().apply(CorporateAction.split('FPT', EX_DATE, into=2),
                       account=acct, ts=T0, base_price=Decimal('40'))


def test_applying_without_a_base_price_moves_quantity_and_reports_no_reference():
    """Legal and common: a caller whose data source already carries adjusted
    prices needs only the quantity and cash legs. What must not happen is a
    reference appearing anyway -- ``reference is None`` says no number was
    produced, rather than implying one."""
    acct = account(holdings={'FPT': 1000})

    applied = engine().apply(CorporateAction.split('FPT', EX_DATE, into=2),
                             account=acct, ts=T0)

    assert applied.reference is None
    assert applied.holding_after.settled == 2000


def test_apply_due_routes_the_per_ticker_inputs_the_engine_cannot_resolve():
    """The engine resolves no venue, price, tick or lot for itself. The venue
    must come from a ``SymbolRouter`` at ``ts`` (locked shape 1) and the price
    from the data source, so ``apply_due`` takes them as per-ticker mappings
    and applies each action in ``(ex_date, ticker)`` order."""
    acct = account(holdings={'FPT': 1000, 'SHS': 500})
    eng = engine(CorporateAction.split('FPT', EX_DATE, into=2),
                 CorporateAction.stock_dividend('SHS', EX_DATE, Decimal('0.1')))

    results = eng.apply_due(
        T0, account=acct,
        prices={'FPT': Decimal('40'), 'SHS': Decimal('22')},
        venues={'FPT': Venue.HSX, 'SHS': Venue.HNX})

    assert [r.ticker for r in results] == ['FPT', 'SHS']
    assert results[0].reference.reference_price == Decimal('20')
    assert results[1].reference.reference_price == Decimal('20')
    assert results[1].reference.venue is Venue.HNX


# --------------------------------------------------------------------------
# The audit -- reporting a crossing instead of returning a wrong number
# --------------------------------------------------------------------------

def test_a_run_that_crossed_an_unapplied_action_reports_it():
    """Design section 15: "an omission that is *declared* is not a defect; a
    silent one is." Until this module landed, a run spanning an ex-date
    returned a number that was wrong for that instrument and said nothing.
    The report is the minimum honest behaviour for a caller who is not
    modelling corporate actions at all."""
    acct = account(holdings={'FPT': 1000})
    action = CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('2000'))
    audit = CorporateActionAudit(CorporateActionSchedule([action]))

    report = audit.report(StubSession(acct))

    assert report.is_clean is False
    assert report.crossed == (action,)
    assert report.affected_tickers == ('FPT',)
    assert report.unhandled[0].held_quantity == 1000
    assert 'wrong for this instrument' in report.unhandled[0].reason


def test_an_action_on_a_ticker_the_run_never_touched_is_crossed_not_unhandled():
    """A schedule entry for a name the account never held and never ordered is
    not a defect in the run. Reporting it as one would train the caller to
    ignore the report, which is worse than not having one."""
    acct = account(holdings={'FPT': 1000})
    mine = CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('2000'))
    theirs = CorporateAction.cash_dividend('VIC', EX_DATE, Decimal('3000'))
    audit = CorporateActionAudit(CorporateActionSchedule([mine, theirs]))

    report = audit.report(StubSession(acct))

    assert set(report.crossed) == {mine, theirs}
    assert report.affected_tickers == ('FPT',)
    assert 'VIC' not in report.exposed_tickers


def test_an_order_is_exposure_even_if_it_never_filled():
    """The order was priced against a reference the ex-date moved, so a run
    that only ever rested an order on the name still produced numbers that are
    wrong. Exposure is not the same question as position."""
    acct = account()
    bk = book(acct)
    order = an_order(side=Side.BUY, price='95.5')
    record = bk.accept(order, Venue.HSX, CUM_DATE, order_id=OrderId('B-1'))
    action = CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('2000'))

    report = CorporateActionAudit(CorporateActionSchedule([action])).report(
        StubSession(acct, orders=(record,)))

    assert report.affected_tickers == ('FPT',)
    assert report.unhandled[0].held_quantity == 0
    assert report.unhandled[0].order_ids == (OrderId('B-1'),)


def test_applying_the_action_clears_the_report():
    """The audit reads the engine's own applied set, so the two cannot
    disagree about whether an event was handled -- which is the one failure a
    report like this cannot have."""
    acct = account(holdings={'FPT': 1000})
    action = CorporateAction.cash_dividend('FPT', EX_DATE, Decimal('2000'))
    schedule = CorporateActionSchedule([action])
    eng = CorporateActionEngine(schedule)
    audit = CorporateActionAudit(schedule, eng)

    assert audit.report(StubSession(acct)).is_clean is False
    eng.apply(action, account=acct, ts=T0)
    report = audit.report(StubSession(acct))

    assert report.is_clean is True
    assert report.applied == (action,)
    assert report.raise_if_unhandled() is report


def test_raise_if_unhandled_names_the_affected_instruments():
    """Opt-in, because the default posture is "report, do not fail". When a
    caller does opt in, the message has to name the instruments and say what
    is wrong about them -- the reference, the band derived from it, and the
    quantity -- because "a corporate action was missed" is not actionable."""
    acct = account(holdings={'FPT': 1000})
    audit = CorporateActionAudit(CorporateActionSchedule([
        CorporateAction.split('FPT', EX_DATE, into=2)]))

    with pytest.raises(UnhandledCorporateActionError) as exc:
        audit.report(StubSession(acct)).raise_if_unhandled()

    message = str(exc.value)
    assert 'FPT' in message
    assert 'reference price' in message and 'holding quantity' in message


def test_the_report_window_is_the_run_so_far_not_the_configured_period():
    """``through`` defaults to ``session.now().date()``. A caller mid-run gets
    what has already gone wrong; a caller who wants the forward warning asks
    for it explicitly against ``provenance().period_end``."""
    acct = account(holdings={'FPT': 1000})
    later = CorporateAction.cash_dividend('FPT', date(2022, 6, 25),
                                          Decimal('2000'))
    audit = CorporateActionAudit(CorporateActionSchedule([later]))
    session = StubSession(acct, now=T0)

    assert audit.report(session).is_clean is True
    forward = audit.report(session,
                           through=session.provenance().period_end)
    assert forward.affected_tickers == ('FPT',)


def test_the_report_says_what_it_swept_so_clean_is_not_ambiguous():
    """"Clean because nothing happened" and "clean because we looked at
    nothing" are different claims, and a report that cannot tell them apart is
    not evidence. ``exposed_tickers`` is the universe the sweep ran over."""
    empty = CorporateActionAudit(CorporateActionSchedule()).report(
        StubSession(account()))

    assert empty.is_clean is True
    assert empty.crossed == () and empty.exposed_tickers == ()
    assert 'none unhandled' in str(empty)


def test_scaling_a_partly_filled_order_puts_the_whole_factor_on_the_remainder():
    """**Nothing sourced settles this**, and it is recorded rather than left
    to emerge. A fill is a record of what actually traded and is not
    rewritten, so ``filled + remaining == original`` (section 12 invariant 1)
    leaves one arrangement: 400 filled of 1,000, doubled, is 400 filled and
    1,200 remaining, and the order's *original* becomes 1,600 -- not 2,000.
    The factor multiplies the 600 shares still working; it cannot also
    multiply the 400 that already traded, because those grew in the **holding**
    instead, where the same factor reaches them, and growing them twice would
    put shares on the order that the account never received. The order's own
    numbers simply stop reading as a clean multiple. It is a fourth reason
    ``SCALE`` is not the default."""
    acct = account(holdings={'FPT': 5000})
    bk = book(acct)
    order = an_order(quantity=1000)
    order_id = OrderId('SELL-3')
    enc = acct.reserve_for_sell(order_id, order, Venue.HSX, CUM_DATE)
    bk.accept(order, Venue.HSX, CUM_DATE, order_id=order_id, encumbrances=(enc,))
    bk.rest(order_id, CUM_DATE)
    bk.apply_fill(order_id, _a_fill(order_id, 400))

    applied = engine(resting_orders=RestingOrderPolicy.SCALE).apply(
        CorporateAction.split('FPT', EX_DATE, into=2),
        account=acct, ts=T0, book=bk, lot=100)

    outcome, = applied.resting_orders
    record = bk.get(order_id)
    assert (outcome.quantity_before, outcome.quantity_after) == (600, 1200)
    assert (record.filled_quantity, record.remaining_quantity) == (400, 1200)
    assert record.original_quantity == 1600
    assert acct.holding('FPT').settled == 10000    # the filled 400 grew HERE
