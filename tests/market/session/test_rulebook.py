"""Per-instant rulebook resolution -- locked shape 1.

Every test here pins a *behaviour* and names the rule behind it. The theme
running through the file is one claim: **the same call, at the same venue, on
two dates, gives two answers.** A test that only checks today's value would
pass against a config-at-load singleton, which is the build this module exists
to forbid.

Numbers are taken from ``docs/reference/vn-exchange-rulebook-2020-2026.md``
with their citations; nothing is pinned here that does not appear there.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from plutus.core.constant import get_trading_unit
from plutus.market.exchanges import HNXDS_EXCHANGE, HSX_EXCHANGE
from plutus.market.margin import vsd_initial_margin
from plutus.market.protocol import (InstrumentKind, InstrumentSpec, OrderType,
                                    SessionPhase)
from plutus.market.session.rulebook import (COVERAGE_START, KRX_CUTOVER,
                                            RuleName, RuleSet, RuleStatus,
                                            Rulebook, SymbolRouter,
                                            UnresolvedRule, VenueListing)
from plutus.market.session.types import (ChargeClass, Confidence, InvestorClass,
                                         LeviedBy, Pin, RulebookEdition,
                                         TradingMethod, Venue)

BOOK = Rulebook()

#: Two ordinary trading instants inside the continuous session, one on each
#: side of the KRX cutover. Both are Mondays, so the weekday branch of
#: ``phase()`` never confounds a rule test.
PRE_KRX_TS = datetime(2024, 1, 8, 10, 0)
POST_KRX_TS = datetime(2025, 6, 2, 10, 0)


def at(ts: datetime) -> RuleSet:
    return BOOK.at(ts)


# --------------------------------------------------------------------------
# The KRX cutover is a dated rule SET, not a migration
# --------------------------------------------------------------------------

def test_edition_boundary_is_half_open_at_the_cutover():
    """2025-05-04 is PRE_KRX and 2025-05-05 is POST_KRX.

    Pins the half-open convention at the one boundary where getting it wrong
    is most expensive. Both editions ship and both stay; a run spanning the
    date gets each on its own side, so the boundary instant must belong to
    exactly one edition -- not to both (an inclusive upper bound) and not to
    neither (an off-by-one).
    """
    assert BOOK.edition_at(datetime(2025, 5, 4, 23, 59)) is RulebookEdition.PRE_KRX
    assert BOOK.edition_at(datetime(2025, 5, 5, 0, 0)) is RulebookEdition.POST_KRX
    assert KRX_CUTOVER == date(2025, 5, 5)


def test_one_rulebook_serves_both_sides_of_the_cutover():
    """One ``Rulebook`` object answers for both editions.

    The design's framing: the KRX delta is not a migration to be run once but
    a dated rule set resolved per instant. If populating post-KRX values ever
    required a second rulebook object, a run spanning the boundary could not
    be a single session.
    """
    assert at(PRE_KRX_TS).edition is RulebookEdition.PRE_KRX
    assert at(POST_KRX_TS).edition is RulebookEdition.POST_KRX


def test_unsourced_post_krx_value_says_so_rather_than_returning_the_pre_krx_one():
    """The margin *model* refuses to resolve after the cutover.

    Pre-KRX, margin was lodged with VSDC before an order could be placed.
    Post-KRX it is held at the clearing member and VSDC computes the
    requirement after the close by the KRX COMS formula -- which could not be
    obtained, and Pinetree confirms no initial-margin percentage is published
    post-KRX. So the pre-KRX row deliberately stops at the cutover instead of
    running on.

    This is the design's requirement made testable: where a post-KRX value is
    not yet sourced, the resolved rule must **say so explicitly**. Returning
    ``'pre_margin'`` here would be a wrong answer that reported itself as a
    sourced one.
    """
    assert at(PRE_KRX_TS).margin_model() == 'pre_margin'

    with pytest.raises(UnresolvedRule):
        at(POST_KRX_TS).margin_model()

    resolution = at(POST_KRX_TS).resolve(RuleName.MARGIN_MODEL)
    assert resolution.status is RuleStatus.UNKNOWN
    assert resolution.value is None
    assert 'COMS' in resolution.note


def test_populating_a_post_krx_value_is_data_entry_not_a_code_change():
    """A pin fills the unsourced post-KRX slot without touching the resolver.

    The mechanism the design asks for: the post-KRX edition is a table, so
    supplying a value is one row (or, here, one override). Nothing about
    ``resolve`` changes, and the pinned answer reports itself as pinned with no
    citation -- because no document says what a counterfactual says.
    """
    pinned = Rulebook(pins=[Pin(path='margin_model', value='coms',
                                reason='COMS formula assumed')])
    resolution = pinned.at(POST_KRX_TS).resolve(RuleName.MARGIN_MODEL)

    assert resolution.status is RuleStatus.KNOWN
    assert resolution.value == 'coms'
    assert resolution.pinned is True
    assert resolution.citation is None


# --------------------------------------------------------------------------
# Round lot -- the dated value the repo already gets wrong
# --------------------------------------------------------------------------

@pytest.mark.parametrize('on, unit', [
    (datetime(2020, 6, 15, 10, 0), 10),
    (datetime(2021, 1, 3, 10, 0), 10),
    (datetime(2021, 1, 4, 10, 0), 100),
    (datetime(2021, 6, 15, 10, 0), 100),
])
def test_hose_round_lot_is_dated(on, unit):
    """HOSE's minimum lot was 10 units until 2021-01-03 and 100 from 2021-01-04.

    A date-blind lookup rejects every legal 10-share HOSE order placed before
    then, and the corpus holds 94,675 HSX stock closes in the 10-lot window --
    most of a year of the equity sample, not a corner case.
    """
    assert at(on).trading_unit(Venue.HSX) == unit


def test_round_lot_delegates_rather_than_copying_the_table():
    """The dated lot comes from ``core.constant.get_trading_unit``.

    ``constant.py`` already carries the 2021-01-04 step, and it already carries
    one pair of tick tables that can drift apart. A second copy of the lot
    schedule here would be the same mistake again, so this module supplies the
    ``ts`` axis and the citation and delegates the number.
    """
    for venue in Venue:
        for on in (date(2020, 6, 15), date(2022, 6, 15)):
            ts = datetime(on.year, on.month, on.day, 10, 0)
            assert at(ts).trading_unit(venue) == get_trading_unit(venue.value, on)


def test_round_lot_carries_a_citation():
    """Every dated value is traceable. That traceability is the whole claim."""
    citation = at(PRE_KRX_TS).citation(
        RuleName.TRADING_UNIT, Venue.HSX, InstrumentKind.STOCK)
    assert citation is not None
    assert citation.document
    assert citation.effective_from is not None
    assert citation.confidence in set(Confidence)


# --------------------------------------------------------------------------
# Order types -- the same call, two dated answers
# --------------------------------------------------------------------------

def test_hose_market_order_is_mp_before_the_cutover_and_mtl_after():
    """HOSE quoted its market order as MP to 2025-05-04 and MTL from 2025-05-05.

    Same call, same venue, same phase, two dates, two answers -- this is shape
    1 in one assertion.

    The change is a **rename, not a semantic change**: both walk the book and
    convert the residue to a limit order one tick beyond the last match, capped
    at the band. So the mnemonic set moves and the ``OrderType`` set does not,
    and reporting a changed ``OrderType`` set would fabricate a semantic delta
    out of a mnemonic swap.
    """
    pre = at(PRE_KRX_TS).legal_order_mnemonics(Venue.HSX, SessionPhase.CONTINUOUS)
    post = at(POST_KRX_TS).legal_order_mnemonics(Venue.HSX, SessionPhase.CONTINUOUS)

    assert 'MP' in pre and 'MTL' not in pre
    assert 'MTL' in post and 'MP' not in post

    assert at(PRE_KRX_TS).order_type_mnemonic(
        Venue.HSX, OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT) == 'MP'
    assert at(POST_KRX_TS).order_type_mnemonic(
        Venue.HSX, OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT) == 'MTL'


def test_hose_never_accepted_mok_or_mak():
    """MOK and MAK are HNX and HNXDS types; HOSE has never taken either.

    Pre-KRX this is gazetted (QD 352 Dieu 14: LO, MP, ATO, ATC). Post-KRX the
    best evidence says HOSE is LO + MTL + ATO + ATC only, and MOK/MAK were not
    introduced -- carried here at low confidence, which is why the rule's own
    note records the weakness rather than the table quietly asserting it.
    """
    for ts in (PRE_KRX_TS, POST_KRX_TS):
        types = at(ts).legal_order_types(Venue.HSX, SessionPhase.CONTINUOUS)
        assert OrderType.MARKET_FILL_OR_KILL not in types
        assert OrderType.MARKET_IMMEDIATE_OR_CANCEL not in types


def test_limit_order_is_legal_in_a_call_auction():
    """LO **is** legal in both auctions; the market family is what is refused.

    HOSE's own session table reads "LO, ATO" and "LO, ATC", and HNX's closing
    call reads "LO, ATC". An LO submitted into an auction joins the auction
    book and matches at the auction price. What a call auction cannot accept is
    MTL/MOK/MAK/MKT, whose sweep-the-book semantics presuppose a resting book
    the auction does not have while it is accumulating.
    """
    rules = at(PRE_KRX_TS)
    for venue, phase in ((Venue.HSX, SessionPhase.OPENING_AUCTION),
                         (Venue.HSX, SessionPhase.CLOSING_AUCTION),
                         (Venue.HNX, SessionPhase.CLOSING_AUCTION),
                         (Venue.HNXDS, SessionPhase.OPENING_AUCTION),
                         (Venue.HNXDS, SessionPhase.CLOSING_AUCTION)):
        types = rules.legal_order_types(venue, phase)
        assert OrderType.LIMIT in types, (venue, phase)
        assert OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT not in types
        assert OrderType.MARKET_FILL_OR_KILL not in types
        assert OrderType.MARKET_IMMEDIATE_OR_CANCEL not in types


def test_upcom_accepts_nothing_but_lo_at_any_date_or_phase():
    """UPCoM is LO-only across the whole window: no market order, no auction.

    An MTL on UPCoM is refused, which the simulator currently admits. Phrased
    as "never anything but LO" rather than "always exactly {LO}" because UPCoM
    has no opening auction, no closing auction and no post-close session at
    all, and claiming it accepts LO in a phase it does not run would be a
    different error.
    """
    for ts in (datetime(2020, 6, 15, 10, 0), PRE_KRX_TS, POST_KRX_TS):
        for phase in _REAL_PHASES:
            mnemonics = at(ts).legal_order_mnemonics(Venue.UPCOM, phase)
            assert mnemonics <= {'LO'}, (ts, phase, mnemonics)
    assert at(PRE_KRX_TS).legal_order_mnemonics(
        Venue.UPCOM, SessionPhase.CONTINUOUS) == {'LO'}


def test_hnx_has_no_opening_auction_at_any_date():
    """HNX runs no ATO, which is why its continuous session starts at 09:00.

    Four sources give 09:00; MBS's HNX sheet prints 09:15 and is read as a
    copy-paste from its HOSE table -- HNX has no opening auction to occupy
    09:00-09:15.
    """
    for ts in (PRE_KRX_TS, POST_KRX_TS):
        assert at(ts).legal_order_types(
            Venue.HNX, SessionPhase.OPENING_AUCTION) == frozenset()


def test_market_order_type_is_legal_at_no_venue_on_any_date():
    """``OrderType.MARKET`` ("MKT") matches no Vietnamese order type, ever.

    A flat negative finding across all four rulebooks. The synthetic
    "sell at floor or buy at ceiling for a guaranteed match" order in
    ``core/order.py`` is neither HOSE's MP nor HNX's MTL. No mnemonic maps to
    it, so no venue-date-phase triple can produce it -- and the exhaustive
    sweep is the point: this is a claim about the whole table, not one row.
    """
    dates = (datetime(2020, 1, 1, 10), datetime(2022, 6, 15, 10),
             datetime(2025, 5, 4, 10), datetime(2025, 5, 5, 10),
             datetime(2026, 8, 25, 10))
    for ts in dates:
        for venue in Venue:
            for phase in _REAL_PHASES:
                assert OrderType.MARKET not in at(ts).legal_order_types(
                    venue, phase), (ts, venue, phase)


#: Every phase a venue can actually be in. ``SessionPhase.UNKNOWN`` is excluded
#: because it is not a phase -- it is the adapter not having supplied one --
#: and the rulebook says so rather than answering; see the test below.
_REAL_PHASES = tuple(p for p in SessionPhase if p is not SessionPhase.UNKNOWN)


def test_an_unsupplied_session_phase_resolves_unknown_rather_than_empty():
    """``SessionPhase.UNKNOWN`` is a missing input, not a closed market.

    Order-type legality is phase-dependent at every venue, so without a phase
    there is no answer -- and "no types are legal" would be a *rejection*,
    which is a different claim from "we cannot tell". ``equity.py`` already
    returns INDETERMINATE for an unsupplied phase; the rulebook agrees rather
    than quietly returning UPCoM's LO-only wildcard.
    """
    for venue in Venue:
        with pytest.raises(UnresolvedRule):
            at(PRE_KRX_TS).legal_order_mnemonics(venue, SessionPhase.UNKNOWN)


def test_hnx_post_close_takes_plo_which_the_order_type_enum_cannot_say():
    """HNX's PLO is real and has no ``OrderType`` member.

    A limit order without a price, executing at the day's last **round-lot**
    matched price. ``core/order.py`` does not carry it, so the mnemonic set is
    the primary datum and the ``OrderType`` view is lossy here. Pinning the
    asymmetry stops a later author "fixing" the empty ``OrderType`` set by
    inventing a mapping.
    """
    rules = at(PRE_KRX_TS)
    assert rules.legal_order_mnemonics(
        Venue.HNX, SessionPhase.POST_CLOSE_PLO) == {'PLO'}
    assert rules.legal_order_types(
        Venue.HNX, SessionPhase.POST_CLOSE_PLO) == frozenset()


# --------------------------------------------------------------------------
# Session phase -- the noon break must be tested first
# --------------------------------------------------------------------------

def test_noon_is_the_noon_break_and_not_continuous():
    """``lo_session`` spans the break by construction, so order matters.

    HOSE's continuous window is 09:15-14:30 *with a hole in it*, not two
    intervals. A resolver that tests ``lo_session`` before ``noon_break``
    reports 12:00 as CONTINUOUS and admits orders into a hard shutdown -- no
    entry, no amend, no cancel, no put-through activity of any kind between
    11:30 and 13:00. Nothing in the repository does this ordering today: both
    adapters hardcode CONTINUOUS.
    """
    for venue in (Venue.HSX, Venue.HNX, Venue.UPCOM, Venue.HNXDS):
        assert at(datetime(2024, 1, 8, 12, 0)).phase(venue) is SessionPhase.NOON_BREAK


@pytest.mark.parametrize('clock, phase', [
    ((8, 59), SessionPhase.PRE_OPEN),
    ((9, 0), SessionPhase.OPENING_AUCTION),
    ((9, 14, 59), SessionPhase.OPENING_AUCTION),
    ((9, 15), SessionPhase.CONTINUOUS),
    ((11, 29, 59), SessionPhase.CONTINUOUS),
    ((11, 30), SessionPhase.NOON_BREAK),
    ((12, 59, 59), SessionPhase.NOON_BREAK),
    ((13, 0), SessionPhase.CONTINUOUS),
    ((14, 29, 59), SessionPhase.CONTINUOUS),
    ((14, 30), SessionPhase.CLOSING_AUCTION),
    ((14, 44, 59), SessionPhase.CLOSING_AUCTION),
    ((14, 45), SessionPhase.POST_CLOSE),
])
def test_hose_session_boundaries_are_half_open(clock, phase):
    """Each boundary instant belongs to exactly one phase.

    Vietnamese session boundaries abut exactly -- the opening auction ends at
    09:15:00 and continuous trading begins at 09:15:00 -- so an inclusive upper
    bound puts 09:15, 11:30, 13:00 and 14:30 in two phases at once and makes
    the answer order-dependent. This is the same ``[start, end)`` convention
    ``AbstractTradingSession.is_current`` now uses, applied to phase
    resolution.
    """
    assert at(datetime(2024, 1, 8, *clock)).phase(Venue.HSX) is phase


def test_upcom_is_still_continuous_when_hose_has_closed():
    """UPCoM trades to 15:00 and has no auction; HOSE stops matching at 14:45.

    Phase is per venue and per instant. A session holding several exchanges at
    once -- which the VN30/VN30F pair trade requires -- gets a different answer
    per venue from the same clock.
    """
    ts = datetime(2024, 1, 8, 14, 50)
    assert at(ts).phase(Venue.UPCOM) is SessionPhase.CONTINUOUS
    assert at(ts).phase(Venue.HNX) is SessionPhase.POST_CLOSE_PLO
    assert at(ts).phase(Venue.HSX) is SessionPhase.POST_CLOSE


def test_derivatives_open_fifteen_minutes_before_the_cash_market():
    """HNXDS runs its ATO 08:45-09:00, before HOSE's 09:00-09:15.

    The contract template defines the hours *relatively* -- "mo cua truoc thi
    truong co so 15 phut" -- and this is the one clock difference that matters
    for a pair trade spanning HSX and HNXDS.
    """
    ts = datetime(2024, 1, 8, 8, 50)
    assert at(ts).phase(Venue.HNXDS) is SessionPhase.OPENING_AUCTION
    assert at(ts).phase(Venue.HSX) is SessionPhase.PRE_OPEN


def test_a_saturday_is_not_a_trading_phase():
    """Weekends resolve to POST_CLOSE, which ``equity.py`` refuses.

    ``SessionPhase`` has no "closed all day" member; POST_CLOSE is the only one
    meaning "not matching, and not going to today". Public holidays are *not*
    handled here and are declared as such: the trading calendar belongs to
    ``calendar.py``, which this module must not import.
    """
    assert at(datetime(2024, 1, 6, 10, 0)).phase(Venue.HSX) is SessionPhase.POST_CLOSE


def test_a_midnight_daily_bar_resolves_pre_open_which_is_why_phase_is_never_inferred():
    """Pinning the trap ``protocol.SessionPhase`` warns about.

    A daily bar is stamped midnight, so clock-based resolution marks it
    PRE_OPEN and a daily run that used it would reject its entire measurement.
    The phase is set by the adapter for daily data; this resolver is for a
    tick-resolution clock. The test exists so the limitation is asserted rather
    than discovered.
    """
    assert at(datetime(2022, 6, 15, 0, 0)).phase(Venue.HSX) is SessionPhase.PRE_OPEN


def test_the_session_schedule_is_a_dated_sourced_rule_like_every_other():
    """``phase()`` resolves a rulebook row, not a module-level ``ExchangeSpec``.

    The clock behind a phase is a *rule*: rulebook section 2.1 carries three
    dated HOSE rows for it, and the earliest is graded ``low`` ("inferred by
    continuity from QD 352; the governing articles were never read") while the
    two later ones are graded ``high``. A resolver reading
    ``constant.py``'s ``HSX`` singleton cannot report any of that -- it has one
    undated window per venue and no citation at all -- so a caller auditing the
    run cannot tell a read regulation from an inference.

    Two dates, two citations, is the whole test.
    """
    early = at(datetime(2020, 6, 15, 10, 0)).citation(
        RuleName.SESSION_SCHEDULE, Venue.HSX)
    later = at(PRE_KRX_TS).citation(RuleName.SESSION_SCHEDULE, Venue.HSX)
    assert early is not None and later is not None
    assert early.confidence is Confidence.LOW
    assert later.confidence is Confidence.HIGH
    assert early.document != later.document
    # The clock itself did not move across that boundary; only the evidence
    # for it did, which is exactly what a citation is for.
    assert (at(datetime(2020, 6, 15, 10, 0)).phase(Venue.HSX)
            is at(PRE_KRX_TS).phase(Venue.HSX)
            is SessionPhase.CONTINUOUS)


def test_a_phase_outside_the_dated_schedule_is_unknown_not_the_singleton():
    """No dated row means UNKNOWN, and never a silent fall-back.

    2019-06-14 is a Friday one rulebook-year before ``COVERAGE_START``. A
    resolver backed by ``_SPEC_BY_VENUE`` answers ``CONTINUOUS`` for it with
    the same confidence it answers 2024 -- a value invented from a singleton
    that has no dates on it, which is locked shape 1's forbidden build at the
    rule that decides order-type legality, the cancel lock, and when a day
    order dies.
    """
    outside = datetime(2019, 6, 14, 10, 0)
    for venue in (Venue.HSX, Venue.HNX, Venue.UPCOM, Venue.HNXDS):
        assert at(outside).resolve(
            RuleName.SESSION_SCHEDULE, venue).status is RuleStatus.UNKNOWN
        assert at(outside).phase(venue) is SessionPhase.UNKNOWN
    with pytest.raises(UnresolvedRule):
        at(outside).session_schedule(Venue.HSX)


# --------------------------------------------------------------------------
# Tick grid
# --------------------------------------------------------------------------

@pytest.mark.parametrize('price, tick', [
    (Decimal('9.99'), Decimal('0.01')),
    (Decimal('10.0'), Decimal('0.05')),
    (Decimal('49.95'), Decimal('0.05')),
    (Decimal('50.0'), Decimal('0.1')),
])
def test_hose_tick_tiers_are_inclusive_below(price, tick):
    """Three tiers, breaking at exactly 10,000d and 50,000d.

    QD 352 Dieu 8.4 says ">= 50.000"; one broker sheet says "> 50.000" and
    leaves 50,000 undefined. The primary text wins, so 50.0 takes the 100d
    tick. The circulating 500d fourth tier is rejected: HOSE's own guide, SSI
    and every VNX appendix give three, and the corpus fits three at 99.997%.
    """
    assert at(PRE_KRX_TS).tick_size(
        Venue.HSX, InstrumentKind.STOCK, price) == tick


def test_etf_takes_the_flat_tick_and_a_closed_end_fund_does_not():
    """``FUE*``/``E1*`` are ETFs; ``FUC*`` are closed-end funds.

    Both are eight characters and both begin with ``F``, which is why the old
    ``ticker[0] in 'CEF'`` predicate swept the closed-end funds in with the
    ETFs. The corpus settles it decisively: all 151 ``FUC*`` close rows are
    multiples of 50, which is the banded grid, not a flat 10d one.
    """
    rules = at(PRE_KRX_TS)
    price = Decimal('25.0')
    assert rules.tick_size(Venue.HSX, InstrumentKind.FUND, price,
                           ticker='FUEVFVND') == Decimal('0.01')
    assert rules.tick_size(Venue.HSX, InstrumentKind.FUND, price,
                           ticker='FUCVREIT') == Decimal('0.05')


def test_put_through_is_one_dong_and_needs_its_own_axis():
    """Negotiated trading is 1d at every cash venue, at every price.

    A hundredfold finer grid than the matched grid at the same price. Without
    the ``method`` argument the ``TICK_GRID`` gate rejects every legitimate
    put-through price, which is why the axis is required rather than optional.
    """
    rules = at(PRE_KRX_TS)
    for venue in (Venue.HSX, Venue.HNX, Venue.UPCOM):
        assert rules.tick_size(venue, InstrumentKind.STOCK, Decimal('25.0'),
                               method=TradingMethod.PUT_THROUGH) == Decimal('0.001')


def test_futures_tick_is_keyed_to_the_contract_not_to_the_exchange():
    """VN30F steps 0.1 index point; a bond future steps 1 VND.

    The same venue, the same instant, two grids that differ tenfold -- and with
    ``CURRENCY_UNIT['HNXDS'] = 1`` both collapse to the same nominal unit,
    which is exactly the confusion a venue-keyed lookup produces. Asking
    without a contract code refuses rather than guessing the index grid.
    """
    rules = at(PRE_KRX_TS)
    assert rules.tick_size(Venue.HNXDS, InstrumentKind.FUTURE,
                           ticker='VN30F2401') == Decimal('0.1')
    assert rules.tick_size(Venue.HNXDS, InstrumentKind.FUTURE,
                           ticker='GB05F2401') == Decimal('1')
    with pytest.raises(UnresolvedRule):
        rules.tick_size(Venue.HNXDS, InstrumentKind.FUTURE)


# --------------------------------------------------------------------------
# Price bands
# --------------------------------------------------------------------------

@pytest.mark.parametrize('venue, band', [
    (Venue.HSX, Decimal('0.07')),
    (Venue.HNX, Decimal('0.10')),
    (Venue.UPCOM, Decimal('0.15')),
])
def test_ordinary_bands_by_venue(venue, band):
    """7 / 10 / 15%, all corpus-confirmed, and all unchanged by KRX."""
    for ts in (PRE_KRX_TS, POST_KRX_TS):
        assert at(ts).daily_trading_limit(venue) == band


def test_government_bond_futures_take_three_percent_not_seven():
    """A band keyed to the exchange gets HNXDS wrong by more than 2x.

    VN30F and VN100F are +/-7%; GB05 and GB10 are +/-3%, from their own
    contract templates. ``DAILY_TRADING_LIMIT[DS] = 0.07`` in ``constant.py``
    is right for one product family and wrong for the other.
    """
    rules = at(PRE_KRX_TS)
    assert rules.daily_trading_limit(
        Venue.HNXDS, InstrumentKind.FUTURE, 'VN30F2401') == Decimal('0.07')
    assert rules.daily_trading_limit(
        Venue.HNXDS, InstrumentKind.FUTURE, 'GB10F2401') == Decimal('0.03')


def test_a_covered_warrant_has_no_percentage_band_and_says_so():
    """A warrant's limits derive from the underlying, not from its own price.

    ``ceiling_CW = ref_CW + (ceiling_und - ref_und) / CR``, with the floor
    clamped at the 10d quotation unit rather than at the reference. Applying 7%
    of the warrant's own price is wrong in both directions and badly wrong for
    cheap warrants: the floor-at-10d branch fires on 16,275 of 46,090 warrant
    name-days. So this is UNKNOWN, not a number -- and distinguishably so.
    """
    with pytest.raises(UnresolvedRule):
        at(PRE_KRX_TS).daily_trading_limit(
            Venue.HSX, InstrumentKind.WARRANT, 'CFPT2314')

    resolution = at(PRE_KRX_TS).resolve(
        RuleName.DAILY_TRADING_LIMIT, Venue.HSX, InstrumentKind.WARRANT)
    assert resolution.status is RuleStatus.UNKNOWN


def test_the_widened_band_table_is_populated_even_though_it_is_not_wired():
    """Widened bands are data now so wiring the state axis is data later.

    The UPCoM illiquidity band is the one that matters most: 70,578 of 412,041
    UPCoM name-days (17.1%) carry +/-40%, and the corpus separation is total --
    every 40% row last traded at least 26 sessions earlier, with no
    counterexample. The ordinary accessor deliberately reports 15% and the
    limitation is declared rather than hidden.
    """
    rules = at(PRE_KRX_TS)
    assert rules.widened_trading_limit(Venue.UPCOM, 'illiquidity') == Decimal('0.40')
    assert rules.widened_trading_limit(Venue.HSX, 'first_trading_day') == Decimal('0.20')
    assert rules.widened_trading_limit(Venue.HNX, 'first_trading_day') == Decimal('0.30')
    assert rules.daily_trading_limit(Venue.UPCOM) == Decimal('0.15')


# --------------------------------------------------------------------------
# Settlement
# --------------------------------------------------------------------------

def test_the_cycle_is_t_plus_2_on_both_sides_of_2022_08_29():
    """What changed on 2022-08-29 was the TIME OF DAY, not the cycle length.

    The single most important correction in the rulebook research. T+2 has been
    the cycle since 2016-01-01 (VSD Decision 211/QD-VSD); Decisions 109 and 110
    moved completion from after the close to mid-day. Labelling the earlier
    regime "T+3" is right about the first sellable session and wrong about the
    cycle, and it hides the 2016 boundary entirely.
    """
    before = at(datetime(2022, 6, 15, 10, 0)).settlement_rule(InstrumentKind.STOCK)
    after = at(datetime(2022, 9, 15, 10, 0)).settlement_rule(InstrumentKind.STOCK)

    assert before.cycle_days == 2
    assert after.cycle_days == 2
    assert before.delivery_on_next_session_open is True
    assert after.delivery_on_next_session_open is False
    assert after.delivery_time.hour == 13


def test_the_settlement_regime_label_is_never_t_plus_1_point_5():
    """"T+1.5" appears in no gazetted document at any date.

    Retail press and broker marketing only -- checked against Decision
    109/QD-VSD and Circulars 119 and 120/2020/TT-BTC. The regime's name is
    "T+2 with mid-day settlement".
    """
    for ts in (datetime(2022, 9, 15, 10), POST_KRX_TS):
        label = at(ts).settlement_rule(InstrumentKind.STOCK).label
        assert '1.5' not in label
        assert label.startswith('T+2')


def test_krx_did_not_change_the_settlement_cycle():
    """T+2 and the 13:00 deadline both survive 2025-05-05.

    Launch journalism repeatedly asserted KRX would bring T+0 or T+1. It did
    not happen, and VSDC re-issued its rulebook preserving both.
    """
    before = at(datetime(2025, 5, 2, 10)).settlement_rule(InstrumentKind.STOCK)
    after = at(datetime(2025, 5, 6, 10)).settlement_rule(InstrumentKind.STOCK)
    assert (before.cycle_days, before.delivery_time) == (after.cycle_days,
                                                         after.delivery_time)


def test_an_index_does_not_settle_and_that_is_not_a_gap():
    """``None`` here means "no settlement applies", a sourced answer.

    Distinguishable from UNKNOWN, which raises. Conflating the two would report
    a research gap as a market rule.
    """
    assert at(PRE_KRX_TS).settlement_rule(InstrumentKind.INDEX) is None
    assert at(PRE_KRX_TS).resolve(
        RuleName.SETTLEMENT, InstrumentKind.INDEX).status is RuleStatus.NOT_APPLICABLE


# --------------------------------------------------------------------------
# Margin, limits
# --------------------------------------------------------------------------

@pytest.mark.parametrize('on, rate', [
    (date(2020, 6, 15), Decimal('0.13')),
    (date(2022, 12, 14), Decimal('0.13')),
    (date(2022, 12, 15), Decimal('0.17')),
    (date(2026, 6, 15), Decimal('0.17')),
])
def test_initial_margin_is_the_dated_vsd_series(on, rate):
    """10 / 13 / 17%, and never 17.5%.

    17.5% appears in no source at any date and is a transcription slip for
    0.17. The value is delegated to ``margin.vsd_initial_margin`` rather than
    copied, because the derivatives transfer tax base is linear in the same
    ratio and the two must read one series.
    """
    ts = datetime(on.year, on.month, on.day, 10, 0)
    assert at(ts).initial_margin_rate('VN30F2401') == rate
    assert at(ts).initial_margin_rate('VN30F2401') == vsd_initial_margin(on)


def test_the_margin_rate_is_keyed_per_contract_even_though_values_agree():
    """VSDC publishes per listed contract and names time-to-maturity as an input.

    Every observed entry has been equal since 2022-12-15, so a date-keyed
    schedule is sufficient *today* -- and will not be forever. The axis exists
    now so it does not have to be threaded through later, and a government-bond
    contract does not silently inherit the index-future series.
    """
    rules = at(PRE_KRX_TS)
    assert rules.initial_margin_rate('VN100F2401') == rules.initial_margin_rate('VN30F2401')
    with pytest.raises(UnresolvedRule):
        rules.initial_margin_rate('GB05F2401')


def test_individuals_may_not_hold_government_bond_futures():
    """Zero is a value, not an absence.

    The index-future tiers are 5,000 / 10,000 / 20,000 by class, all low
    confidence -- HNX's current template prints no number and no in-window VSDC
    notice was located. The GB bar on individuals is high confidence and is a
    hard zero.
    """
    rules = at(PRE_KRX_TS)
    assert rules.position_limit('VN30F2401', InvestorClass.INDIVIDUAL) == 5000
    assert rules.position_limit('VN30F2401', InvestorClass.INSTITUTION) == 10000
    assert rules.position_limit('VN30F2401', InvestorClass.PROFESSIONAL) == 20000
    assert rules.position_limit('GB05F2401', InvestorClass.INDIVIDUAL) == 0


def test_max_order_size_is_published_on_hose_and_hnxds_and_nowhere_else():
    """"No cap" on HNX and UPCoM is an inference, not a sourced rule.

    HOSE's 500,000 is a HOSE-specific clause and the 999,900-share figure that
    circulates for HNX was neither confirmed nor refuted, so those two venues
    resolve UNKNOWN rather than to an unbounded default that would silently
    admit a 10,000,000-share order.
    """
    rules = at(PRE_KRX_TS)
    assert rules.max_order_size(Venue.HSX) == 500_000
    assert rules.max_order_size(Venue.HNXDS) == 500
    for venue in (Venue.HNX, Venue.UPCOM):
        with pytest.raises(UnresolvedRule):
            rules.max_order_size(venue)


# --------------------------------------------------------------------------
# Charges
# --------------------------------------------------------------------------

def test_the_sell_side_personal_income_tax_is_in_force_and_sell_side_only():
    """0.1% of gross sale notional, withheld at source, so a sale credits net.

    Without it every sale is wrong by more than most commissions, which is why
    charges are modelled at all: they move cash and therefore change admission
    outcomes.
    """
    rows = {c.charge_id: c for c in at(PRE_KRX_TS).charges(Venue.HSX,
                                                           ChargeClass.EQUITY)}
    pit = rows['pit_securities_transfer']
    assert pit.rate == Decimal('0.001')
    assert pit.side.value == 'sell'
    assert pit.levied_by is LeviedBy.STATE


def test_the_exchange_trading_service_price_is_dated():
    """0.0003 to 2020-03-18, then 0.00027; ETFs and warrants take less.

    Two dated answers to the same call, and a per-instrument-class split within
    one venue -- neither of which a pair of constants can express.
    """
    early = {c.charge_id: c for c in at(datetime(2020, 2, 3, 10)).charges(
        Venue.HSX, ChargeClass.EQUITY)}
    later = {c.charge_id: c for c in at(PRE_KRX_TS).charges(
        Venue.HSX, ChargeClass.EQUITY)}
    assert early['exchange_service_hsx_equity'].rate == Decimal('0.0003')
    assert later['exchange_service_hsx_equity'].rate == Decimal('0.00027')

    etf = {c.charge_id: c for c in at(PRE_KRX_TS).charges(Venue.HSX,
                                                          ChargeClass.ETF)}
    assert etf['exchange_service_hsx_etf_cw'].rate == Decimal('0.00018')


def test_the_vsdc_derivatives_charge_changes_SHAPE_on_2022_01_01():
    """Per open contract per DAY before; per matched contract at FILL after.

    No per-trade constant can express the first, which is why charges are a
    generic table. The switch made intraday round trips more expensive and
    multi-day holds cheaper, so a run either side of the boundary that used one
    shape for both would misprice turnover in opposite directions.
    """
    before = {c.charge_id for c in at(datetime(2021, 6, 15, 10)).charges(
        Venue.HNXDS, ChargeClass.FUTURE)}
    after = {c.charge_id for c in at(PRE_KRX_TS).charges(Venue.HNXDS,
                                                         ChargeClass.FUTURE)}
    assert 'vsdc_derivatives_position_management' in before
    assert 'vsdc_derivatives_clearing' not in before
    assert 'vsdc_derivatives_clearing' in after
    assert 'vsdc_derivatives_position_management' not in after


def test_the_derivatives_tax_rate_tracks_the_same_margin_series():
    """Its published base is linear in the VSD initial margin ratio.

    So the effective rate against trade value is dated by the *margin* series,
    not by a tax schedule: 0.0005 x 0.13 before 2022-12-15 and 0.0005 x 0.17
    after. Reading a second copy of the ratio here would let the tax and the
    margin disagree, which the rulebook explicitly forbids.
    """
    def rate(ts):
        rows = {c.charge_id: c for c in at(ts).charges(Venue.HNXDS,
                                                       ChargeClass.FUTURE)}
        return rows['pit_derivatives_transfer'].rate

    assert rate(datetime(2022, 12, 14, 10)) == Decimal('0.0005') * Decimal('0.13')
    assert rate(datetime(2022, 12, 15, 10)) == Decimal('0.0005') * Decimal('0.17')


def test_no_broker_row_can_reach_the_dated_rulebook():
    """Commission and the sale-advance rate are commercial terms.

    They differ by firm and change at will, so a dated rulebook carrying them
    would forfeit the traceability that is its whole claim. Every row served
    here is levied by the state, an exchange or the depository.
    """
    for venue in Venue:
        for cls_ in ChargeClass:
            for row in at(PRE_KRX_TS).charges(venue, cls_):
                assert row.levied_by is not LeviedBy.BROKER
                assert row.citation is not None, row.charge_id


# --------------------------------------------------------------------------
# Resolution mechanics: unknown is distinguishable, pins are reported
# --------------------------------------------------------------------------

def test_resolving_outside_the_coverage_window_is_unknown_not_a_guess():
    """The research covers 2020-01-01 -> 2026-08-25 and refuses to extrapolate.

    Asking for a HOSE band in 2015 gets UNKNOWN with the window named, not the
    2020 value quietly extended backwards.
    """
    early = datetime(2015, 6, 15, 10, 0)
    resolution = at(early).resolve(RuleName.DAILY_TRADING_LIMIT, Venue.HSX,
                                   InstrumentKind.STOCK)
    assert resolution.status is RuleStatus.UNKNOWN
    assert str(COVERAGE_START) in resolution.note
    with pytest.raises(UnresolvedRule):
        at(early).daily_trading_limit(Venue.HSX)


def test_resolve_is_total_and_never_raises():
    """The counting path must not throw, or the indeterminate rate is unmeasurable.

    ``IndeterminateReport`` counts what the run could not decide, and a
    counter that has to be wrapped in a try/except would systematically
    undercount whatever the author forgot to wrap.
    """
    for rule in RuleName:
        resolution = at(datetime(1999, 1, 1, 10)).resolve(rule, 'nonsense')
        assert resolution.status in set(RuleStatus)


def test_a_known_and_an_unknown_answer_are_never_both_none():
    """The three states are genuinely distinguishable at the API surface.

    A bond has no band (NOT_APPLICABLE) and a warrant's band is unknown
    (UNKNOWN). Both would be ``None`` under a two-state design, and the log
    would then report a research gap as a market rule.
    """
    rules = at(PRE_KRX_TS)
    not_applicable = rules.resolve(RuleName.DAILY_TRADING_LIMIT, Venue.HSX, 'BOND')
    unknown = rules.resolve(RuleName.DAILY_TRADING_LIMIT, Venue.HSX,
                            InstrumentKind.WARRANT)
    assert not_applicable.status is RuleStatus.NOT_APPLICABLE
    assert unknown.status is RuleStatus.UNKNOWN
    assert not_applicable.status is not unknown.status


def test_a_pin_overrides_only_what_it_names_and_reports_itself():
    """Counterfactuals are legal; unreported counterfactuals are not.

    ``exchange_rules`` pins are how a post-KRX rulebook is run against pre-KRX
    data as a control. The pin appears in ``Rulebook.pins`` for the provenance
    record, the resolution is stamped ``pinned``, and its citation is dropped
    because no document says what the pin says.
    """
    book = Rulebook(pins=[Pin(path='daily_trading_limit.HSX',
                              value=Decimal('0.99'), reason='control arm')])
    rules = book.at(PRE_KRX_TS)

    assert rules.daily_trading_limit(Venue.HSX) == Decimal('0.99')
    assert rules.daily_trading_limit(Venue.HNX) == Decimal('0.10')
    assert rules.daily_trading_limit(Venue.UPCOM) == Decimal('0.15')

    resolution = rules.resolve(RuleName.DAILY_TRADING_LIMIT, Venue.HSX,
                               InstrumentKind.STOCK)
    assert resolution.pinned is True
    assert resolution.citation is None
    assert book.pins[0].reason == 'control arm'


def test_a_pin_can_target_one_field_of_a_record():
    """``settlement.cycle_days`` is the ``Pin`` docstring's own example.

    Without field-level pinning a caller wanting a T+3 control arm would have
    to hand-build a whole ``SettlementRule`` including a citation which, being
    counterfactual, does not exist.
    """
    book = Rulebook(pins=[Pin(path='settlement.cycle_days', value=3)])
    rule = book.at(PRE_KRX_TS).settlement_rule(InstrumentKind.STOCK)
    assert rule.cycle_days == 3
    assert rule.delivery_time.hour == 13   # untouched by the pin


def test_a_pin_naming_no_rule_is_refused_at_construction():
    """A typo'd pin path must not silently do nothing.

    A pin that resolves to no rule is a counterfactual the run believes it
    applied and did not, which is worse than either applying it or refusing it.
    """
    with pytest.raises(ValueError):
        Rulebook(pins=[Pin(path='not_a_rule.HSX', value=1)])


def test_an_unknown_rulebook_id_is_refused():
    """A rulebook is data; asking for one this build does not carry raises."""
    with pytest.raises(ValueError):
        Rulebook.load('vn-2030-something')


def test_the_ruleset_carries_its_instant_so_it_cannot_be_reused_across_a_boundary():
    """``at(ts)`` returns a view bound to ``ts``, not a materialised bundle.

    A bundle of resolved values could be held and reused at a different
    instant, which is the config-at-load singleton wearing a different hat.
    Every accessor here re-resolves against ``self.ts``.
    """
    pre, post = at(PRE_KRX_TS), at(POST_KRX_TS)
    assert pre.ts == PRE_KRX_TS and post.ts == POST_KRX_TS
    assert pre.legal_order_mnemonics(
        Venue.HSX, SessionPhase.CONTINUOUS) != post.legal_order_mnemonics(
        Venue.HSX, SessionPhase.CONTINUOUS)


def test_dated_intervals_abut_without_gap_or_overlap():
    """Walking a rule day by day across a boundary yields exactly one answer.

    The half-open convention is only worth anything if the table respects it.
    This sweeps the HOSE round lot and the settlement rule across their own
    boundaries a day at a time and asserts a single, changing answer -- which
    catches both an inclusive-bound overlap and an off-by-one gap.
    """
    for day in range(-3, 4):
        on = date(2021, 1, 4) + timedelta(days=day)
        ts = datetime(on.year, on.month, on.day, 10, 0)
        expected = 10 if on < date(2021, 1, 4) else 100
        assert at(ts).trading_unit(Venue.HSX) == expected

    for day in range(-3, 4):
        on = date(2022, 8, 29) + timedelta(days=day)
        ts = datetime(on.year, on.month, on.day, 10, 0)
        rule = at(ts).settlement_rule(InstrumentKind.STOCK)
        assert rule is not None
        assert rule.delivery_on_next_session_open is (on < date(2022, 8, 29))


# --------------------------------------------------------------------------
# SymbolRouter -- the (ticker, ts) -> venue seam
# --------------------------------------------------------------------------

class _StaticSource:
    """A ``MarketDataSource`` that knows one venue per ticker, forever.

    Deliberately shaped like ``adapters/datahub.py``, whose ``instrument()``
    takes no ``ts`` and caches one ``InstrumentSpec`` per ticker for the
    process lifetime. The router has to contain that, not inherit it.
    """

    def __init__(self, code: str, kind: InstrumentKind = InstrumentKind.STOCK):
        self._code, self._kind = code, kind

    def state_at(self, ticker, ts):
        return None

    def states(self, ticker, start, end, resolution=None):
        return iter(())

    def instrument(self, ticker):
        return InstrumentSpec(
            ticker=ticker, exchange_code=self._code, kind=self._kind,
            trading_unit=100, daily_trading_limit=Decimal('0.15'))


def test_a_transferred_ticker_resolves_to_a_different_venue_on_each_side():
    """``(ticker, ts) -> venue``, which is the whole point of shape 1.

    The corpus shows what a static map costs: all 3,729 UPCoM off-grid closes
    are venue-transfer artefacts, each ticker's off-grid rows stopping exactly
    at its last HOSE session. A frozen venue then assigns UPCoM's 100d tick and
    +/-15% band to days that traded on HOSE under a 10d tick and +/-7%.
    """
    router = SymbolRouter(_StaticSource('UPCOM'), BOOK, listings=[
        VenueListing('AAA', Venue.HSX, date(2020, 1, 1), date(2025, 7, 1)),
        VenueListing('AAA', Venue.UPCOM, date(2025, 7, 1)),
    ])
    assert router.venue('AAA', datetime(2022, 3, 1, 10)) is Venue.HSX
    assert router.venue('AAA', datetime(2025, 8, 1, 10)) is Venue.UPCOM
    assert router.exchange('AAA', datetime(2022, 3, 1, 10)) is HSX_EXCHANGE


def test_the_router_overwrites_the_adapters_undated_trading_unit():
    """The returned spec's lot is date-correct, which is what makes it safe to pass.

    ``equity.py``'s ``ROUND_LOT`` rule prefers ``instrument.trading_unit`` when
    an ``InstrumentSpec`` is given and falls back to the dated
    ``get_trading_unit()`` otherwise -- so passing the adapter's spec
    *disables* the dated rule. The source here reports 100 at every date; the
    router must report 10 in 2020.
    """
    router = SymbolRouter(_StaticSource('HSX'), BOOK)
    assert router.instrument('AAA', datetime(2020, 6, 15, 10)).trading_unit == 10
    assert router.instrument('AAA', datetime(2021, 6, 15, 10)).trading_unit == 100


def test_the_router_overwrites_the_adapters_undated_band():
    """Same seam, the band axis.

    The source reports UPCoM's 15% for a HOSE ticker. The rulebook's 7% wins,
    because the band is a dated venue value and the adapter's spec is neither
    dated nor venue-correct.
    """
    router = SymbolRouter(_StaticSource('HSX'), BOOK)
    spec = router.instrument('AAA', datetime(2022, 6, 15, 10))
    assert spec.daily_trading_limit == Decimal('0.07')
    assert spec.exchange_code == 'HSX'


def test_a_futures_code_routes_to_hnxds_without_a_ticker_master():
    """No ticker master in this repository carries HNXDS rows at all.

    So the futures code shape is authoritative for derivatives, and it must
    outrank whatever a cash-venue source says.
    """
    router = SymbolRouter(_StaticSource('HSX'), BOOK)
    assert router.venue('VN30F2206', datetime(2022, 6, 1, 10)) is Venue.HNXDS
    assert router.exchange('VN30F2206', datetime(2022, 6, 1, 10)) is HNXDS_EXCHANGE


def test_an_unroutable_ticker_refuses_rather_than_defaulting():
    """A silently defaulted venue is shape 1's failure mode.

    It would produce a plausible band, tick, lot and fee that are all wrong
    together, and nothing downstream could tell.
    """
    router = SymbolRouter(None, BOOK)
    with pytest.raises(UnresolvedRule):
        router.venue('AAA', datetime(2022, 6, 15, 10))


def test_the_router_holds_no_ticker_keyed_cache():
    """Two calls at two instants must not share an answer.

    Asserted structurally as well as behaviourally: a cache is the forbidden
    build, and a later author adding one for speed would break the transfer
    case above in a way that only shows up on 2025-07 data.
    """
    router = SymbolRouter(_StaticSource('HSX'), BOOK)
    assert not any(isinstance(v, dict) and v for v in vars(router).values())
