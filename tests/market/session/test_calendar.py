"""What the settlement calendar must get right, and why.

The whole file turns on one fact: **settlement business days are not trading
days**. Announcement 4228/TB-VSDC closed VSDC settlement 2026-02-16 -> 02-20,
a window inside which the exchanges reopened, so T+2 of a 2026-02-12 trade
settled 2026-02-23. Every simulator that counts bars, sessions or plain
weekdays gets that wrong, and an earlier revision of the design spec claimed
counting sessions was "holiday-correct by construction". These tests pin the
refutation.
"""

import json
from datetime import date, datetime, time, timedelta, timezone

import pytest

from plutus.market.session.calendar import (DEFAULT_SETTLEMENT_CALENDAR,
                                            CalendarCoverageError,
                                            CalendarError, SettlementCalendar,
                                            TradingCalendar, VnTradingCalendar,
                                            VsdcSettlementCalendar,
                                            weekday_settlement_calendar,
                                            weekday_trading_calendar)
from plutus.market.session.types import (Confidence, RuleCitation,
                                         SettlementRule, Venue)

# --------------------------------------------------------------------------
# Fixtures: the Tet 2026 window, as published
# --------------------------------------------------------------------------

#: VSDC settlement closures around Tet 2026, verbatim from Announcement
#: 4228/TB-VSDC (2025-11-20) as recorded in the rulebook: 2026-02-16 through
#: 2026-02-20 inclusive, Monday to Friday.
TET_2026_SETTLEMENT_HOLIDAYS = frozenset(
    date(2026, 2, 16) + timedelta(days=offset) for offset in range(5))

#: A window wide enough to contain the worked example and its arithmetic.
FEB_2026 = (date(2026, 2, 1), date(2026, 3, 31))

VSDC_4228 = 'VSDC Announcement 4228/TB-VSDC (2025-11-20), 2026 schedule'


def vsdc_2026(**kwargs) -> VsdcSettlementCalendar:
    """The sourced Tet-2026 settlement calendar these tests count on."""
    return VsdcSettlementCalendar(
        TET_2026_SETTLEMENT_HOLIDAYS, FEB_2026, 'vsdc-2026',
        source=VSDC_4228, **kwargs)


def current_regime() -> SettlementRule:
    """T+2 with client allocation by 13:00 on T+2, in force from 2022-08-29.

    Decision 109/QD-VSD Art. 4: the custodian member must allocate cash and
    securities to the client no later than 13:00 on T+2.
    """
    return SettlementRule(
        cycle_days=2,
        delivery_time=time(13, 0),
        delivery_on_next_session_open=False,
        citation=RuleCitation(
            document='Decision 109/QD-VSD',
            effective_from=date(2022, 8, 29),
            confidence=Confidence.HIGH,
            article='Art. 4'))


def pre_2022_regime() -> SettlementRule:
    """T+2 completing after the close, so first sellable at the T+3 open.

    Effective 2016-01-01 to 2022-08-26. The cycle length is the same two days
    -- what changed on 2022-08-29 was the time of day, not the number of days
    -- so ``cycle_days`` is 2 here as well, and the difference is carried by
    ``delivery_on_next_session_open``.
    """
    return SettlementRule(
        cycle_days=2,
        delivery_time=time(9, 0),
        delivery_on_next_session_open=True,
        citation=RuleCitation(
            document='Decision 211/QD-VSD',
            effective_from=date(2016, 1, 1),
            confidence=Confidence.HIGH,
            effective_to=date(2022, 8, 26)))


def t_plus_one() -> SettlementRule:
    """T+1, the listed corporate and government bond cycle."""
    return SettlementRule(
        cycle_days=1,
        delivery_time=time(15, 0),
        delivery_on_next_session_open=False,
        citation=RuleCitation(
            document='Decision 109/QD-VSD',
            effective_from=date(2022, 8, 29),
            confidence=Confidence.HIGH,
            article='Art. 4(3)'))


# --------------------------------------------------------------------------
# The worked example: settlement days are not trading days
# --------------------------------------------------------------------------

def test_tet_2026_t2_of_12_february_settles_on_23_february():
    """T+2 counts VSDC settlement business days, not calendar or trading days.

    Announcement 4228/TB-VSDC, verified verbatim in the rulebook: VSDC closed
    2026-02-16 -> 02-20, so the T+2 of a Thursday 2026-02-12 trade lands on
    Monday 2026-02-23 -- not on Monday 2026-02-16, which is what every
    weekday-counting implementation returns.
    """
    calendar = vsdc_2026()

    assert calendar.settle_date(date(2026, 2, 12), 2) == date(2026, 2, 23)
    assert calendar.settle_date(date(2026, 2, 12), 2) != date(2026, 2, 16)


def test_tet_2026_second_and_third_worked_examples():
    """The other two rows of the same published example.

    T+2 of 2026-02-13 settled 2026-02-24; T+1 of 2026-02-13 settled
    2026-02-23. Pinning all three fixes the *counting convention* as well as
    the answer: each step moves to the next settlement day strictly after the
    cursor ("ngay lam viec thu hai lien ke sau ngay giao dich", Decision
    109/QD-VSD Art. 4(4)).
    """
    calendar = vsdc_2026()

    assert calendar.settle_date(date(2026, 2, 13), 2) == date(2026, 2, 24)
    assert calendar.settle_date(date(2026, 2, 13), 1) == date(2026, 2, 23)


def test_counting_exchange_trading_days_gives_a_different_answer():
    """A calendar built from trading days is the wrong calendar.

    The trading holidays used here are *illustrative, not sourced* -- the
    rulebook publishes the VSDC settlement closure and does not publish the
    2026 exchange closure -- so this test asserts only the shape of the error:
    when the exchange reopens before the depository, counting sessions settles
    a trade on a day the depository is shut. That is the class of bug rulebook
    9.5 describes, and it is why the two calendars are two objects.
    """
    settlement = vsdc_2026()
    # Illustrative: the exchange reopens 2026-02-19, VSDC does not until 02-23.
    trading = VnTradingCalendar(
        frozenset({date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18)}),
        FEB_2026, 'illustrative-not-sourced')

    counted_in_sessions = trading.next_trading_day(
        trading.next_trading_day(date(2026, 2, 12)))

    assert counted_in_sessions == date(2026, 2, 19)
    assert settlement.settle_date(date(2026, 2, 12), 2) == date(2026, 2, 23)
    assert not settlement.is_settlement_day(counted_in_sessions)


def test_weekends_and_listed_closures_are_not_settlement_days():
    """The settlement week is Mon-Fri; the notice lists the rest."""
    calendar = vsdc_2026()

    assert calendar.is_settlement_day(date(2026, 2, 12))       # Thursday
    assert not calendar.is_settlement_day(date(2026, 2, 14))   # Saturday
    assert not calendar.is_settlement_day(date(2026, 2, 15))   # Sunday
    assert not calendar.is_settlement_day(date(2026, 2, 18))   # Tet closure
    assert calendar.is_settlement_day(date(2026, 2, 23))       # reopened


# --------------------------------------------------------------------------
# settles_at: the instant, not the day
# --------------------------------------------------------------------------

def test_settles_at_returns_the_instant_the_regime_turns_on():
    """Locked shape 3: a settlement instant is a datetime, never a date.

    Under the regime in force since 2022-08-29 the client allocation deadline
    is 13:00 on T+2 (Decision 109/QD-VSD Art. 4), so the T+2 of the worked
    example is 2026-02-23T13:00 -- a date could not carry the 13:00 that the
    whole afternoon-sale rule depends on.
    """
    calendar = vsdc_2026()

    settled = calendar.settles_at(
        datetime(2026, 2, 12, 10, 30), current_regime())

    assert settled == datetime(2026, 2, 23, 13, 0)


def test_daily_bars_make_t2_at_1300_behave_as_t3():
    """On midnight-stamped daily bars the T+2 bar does not clear 13:00.

    A daily bar's ts is 00:00, so it never reaches an afternoon threshold: the
    T+2 bar cannot use the delivery and the T+3 bar is the first that can.
    This is stated in the calendar's docstring and pinned here because it is
    the behaviour the Tier 1 demo turns on -- the simulator holds shares
    locked one bar longer than the real market did, which is the conservative
    direction and is intended.
    """
    calendar = vsdc_2026()
    settled = calendar.settles_at(
        datetime(2026, 2, 12), current_regime())

    t2_bar = datetime(2026, 2, 23)          # midnight on the settlement day
    t3_bar = datetime(2026, 2, 24)

    assert t2_bar < settled
    assert t3_bar >= settled


def test_pre_2022_regime_is_sellable_at_the_t3_open_not_the_t2_afternoon():
    """Before 2022-08-29 settlement completed after the close on T+2.

    VSD completed settlement between 15:30 and 16:00 on T+2, so the shares
    could not be sold that afternoon and the first usable session was the open
    of T+3. The rule carries ``delivery_on_next_session_open=True`` rather
    than a 16:00 delivery time: encoding it as an afternoon instant on T+2
    would make a T+2 afternoon sale look legal, which it was not.
    """
    trading = weekday_trading_calendar(FEB_2026)
    calendar = vsdc_2026(trading=trading)

    settled = calendar.settles_at(
        datetime(2026, 2, 12, 10, 0), pre_2022_regime())

    assert settled == datetime(2026, 2, 24, 9, 0)
    # The T+2 afternoon is not enough under this regime, and would have been
    # under the later one.
    assert datetime(2026, 2, 23, 14, 0) < settled
    assert datetime(2026, 2, 23, 14, 0) >= calendar.settles_at(
        datetime(2026, 2, 12, 10, 0), current_regime())


def test_next_session_open_delivery_refuses_to_guess_without_a_calendar():
    """"Next session open" is a trading-day question, and it is not this
    calendar's to answer.

    Falling back to the settlement calendar would silently assume the two
    agree on which day the next session is -- the exact assumption this module
    exists to refuse -- so an unbound calendar raises instead.
    """
    calendar = vsdc_2026()

    with pytest.raises(CalendarError, match='next session open'):
        calendar.settles_at(datetime(2026, 2, 12), pre_2022_regime())


def test_settles_at_preserves_the_trade_instants_timezone():
    """A tz-aware session stays tz-aware across settlement.

    Asia/Ho_Chi_Minh has been a fixed +07 with no DST since 1975, so carrying
    the trade's zone onto a later day is safe here in a way it would not be in
    a DST jurisdiction.
    """
    ict = timezone(timedelta(hours=7))
    calendar = vsdc_2026()

    settled = calendar.settles_at(
        datetime(2026, 2, 12, 10, 0, tzinfo=ict), current_regime())

    assert settled == datetime(2026, 2, 23, 13, 0, tzinfo=ict)
    assert settled.tzinfo is ict


def test_t_plus_one_and_t_plus_zero_use_the_same_counting():
    """Bonds settle T+1 and privately placed bonds T+0 on the same calendar.

    T+0 is not a no-op: it is "the trade date if the depository settles that
    day", so a trade stamped inside the Tet closure would settle on the
    reopening. Pinning it here stops ``n=0`` being special-cased into
    returning the trade date unconditionally.
    """
    calendar = vsdc_2026()

    assert calendar.settle_date(date(2026, 2, 12), 1) == date(2026, 2, 13)
    assert calendar.settle_date(date(2026, 2, 12), 0) == date(2026, 2, 12)
    assert calendar.settle_date(date(2026, 2, 14), 0) == date(2026, 2, 23)
    assert calendar.settles_at(
        datetime(2026, 2, 13, 9, 0), t_plus_one()) == datetime(
            2026, 2, 23, 15, 0)


def test_add_business_days_is_the_same_arithmetic_under_the_contract_name():
    """``add_business_days`` and ``settle_date`` must not drift apart.

    The interface contract names the operation ``add_business_days``; T+N is
    what it is for. Two names, one implementation, so no caller can find a
    third answer.
    """
    calendar = vsdc_2026()

    for n in (0, 1, 2, 3):
        assert (calendar.add_business_days(date(2026, 2, 12), n)
                == calendar.settle_date(date(2026, 2, 12), n))


def test_a_negative_cycle_is_a_caller_bug():
    """T+N counts forwards. A negative N is refused, not reinterpreted."""
    with pytest.raises(ValueError, match='n >= 0'):
        vsdc_2026().settle_date(date(2026, 2, 12), -1)


# --------------------------------------------------------------------------
# Coverage: the calendar refuses what it was not told
# --------------------------------------------------------------------------

def test_a_day_outside_the_loaded_coverage_raises():
    """Beyond the loaded notice the honest answer is "I do not know".

    The alternative -- assuming Mon-Fri outside coverage -- returns a
    settlement date indistinguishable from a sourced one, and around Tet it is
    wrong by a week. So every query outside the window raises.
    """
    calendar = vsdc_2026()

    with pytest.raises(CalendarCoverageError):
        calendar.is_settlement_day(date(2026, 4, 1))
    with pytest.raises(CalendarCoverageError):
        calendar.settle_date(date(2026, 1, 30), 2)
    assert not calendar.covers(date(2026, 4, 1))
    assert calendar.covers(date(2026, 2, 12))


def test_a_count_that_walks_off_the_end_raises_rather_than_extrapolating():
    """The refusal covers days the *arithmetic* reaches, not just the input.

    A calendar loaded only to 2026-02-13 knows the 02-12 trade date and knows
    nothing about the closure that follows it. Answering "2026-02-16" from
    weekday arithmetic would be exactly the sourced-looking fabrication this
    class exists to prevent.
    """
    stub = VsdcSettlementCalendar(
        frozenset(), (date(2026, 2, 1), date(2026, 2, 13)), 'vsdc-truncated',
        source='deliberately truncated for this test')

    assert stub.covers(date(2026, 2, 12))
    with pytest.raises(CalendarCoverageError, match='2026-02-14'):
        stub.settle_date(date(2026, 2, 12), 2)


def test_coverage_running_backwards_is_refused_at_construction():
    """A window ending before it begins covers nothing, yet answers."""
    with pytest.raises(CalendarError, match='runs backwards'):
        VsdcSettlementCalendar(
            frozenset(), (date(2026, 3, 31), date(2026, 2, 1)))


# --------------------------------------------------------------------------
# Construction and provenance
# --------------------------------------------------------------------------

def test_explicit_settlement_days_can_express_a_working_saturday():
    """The Mon-Fri week is a convention, and the escape hatch is explicit.

    No working Saturday is attested for VSDC in 2020-2026, which is why the
    Mon-Fri default exists; "not attested" is weaker than "does not occur", so
    a source showing one is expressible without editing this module.
    """
    calendar = VsdcSettlementCalendar.from_settlement_days(
        [date(2026, 2, 13), date(2026, 2, 14), date(2026, 2, 23)],
        FEB_2026, 'vsdc-with-working-saturday', source='hypothetical')

    assert calendar.is_settlement_day(date(2026, 2, 14))     # Saturday
    assert not calendar.is_settlement_day(date(2026, 2, 12))  # not listed
    assert calendar.settle_date(date(2026, 2, 13), 2) == date(2026, 2, 23)


def test_from_file_loads_dates_coverage_and_the_citation(tmp_path):
    """A calendar is a data input, and it carries the document it came from."""
    path = tmp_path / 'vsdc-2026.json'
    path.write_text(json.dumps({
        'calendar_id': 'vsdc-2026',
        'coverage': ['2026-02-01', '2026-03-31'],
        'holidays': [d.isoformat()
                     for d in sorted(TET_2026_SETTLEMENT_HOLIDAYS)],
        'source': VSDC_4228,
    }), encoding='utf-8')

    calendar = VsdcSettlementCalendar.from_file(path)

    assert calendar.calendar_id == 'vsdc-2026'
    assert calendar.coverage == FEB_2026
    assert calendar.is_sourced
    assert calendar.settle_date(date(2026, 2, 12), 2) == date(2026, 2, 23)


def test_a_file_carrying_both_holiday_shapes_is_refused(tmp_path):
    """Two answers to one question is an error, not a precedence rule."""
    path = tmp_path / 'ambiguous.json'
    path.write_text(json.dumps({
        'coverage': ['2026-02-01', '2026-03-31'],
        'holidays': ['2026-02-16'],
        'settlement_days': ['2026-02-12'],
    }), encoding='utf-8')

    with pytest.raises(CalendarError, match='two answers to one question'):
        VsdcSettlementCalendar.from_file(path)


def test_a_file_with_no_coverage_is_refused(tmp_path):
    """Coverage is not inferred from the holidays in the file.

    The notice covers a year; the closures in it do not. Inferring the window
    from min/max would produce a calendar that refuses January and answers
    freely for December.
    """
    path = tmp_path / 'no-coverage.json'
    path.write_text(json.dumps({'holidays': ['2026-02-16']}), encoding='utf-8')

    with pytest.raises(CalendarError, match='coverage'):
        VsdcSettlementCalendar.from_file(path)


def test_an_empty_holiday_year_must_be_written_out(tmp_path):
    """A year with no closures is a claim and has to be made explicitly."""
    path = tmp_path / 'silent.json'
    path.write_text(json.dumps({'coverage': ['2026-02-01', '2026-03-31']}),
                    encoding='utf-8')

    with pytest.raises(CalendarError, match='holidays'):
        VsdcSettlementCalendar.from_file(path)


def test_a_calendar_without_a_citation_reports_that_it_has_none():
    """``is_sourced`` is the flag a published result checks.

    Rulebook 9.5 grades the settlement calendar ``high`` *because of*
    Announcement 4228/TB-VSDC. A calendar with no such document behind it
    inherits none of that grade, and the arithmetic cannot tell the
    difference -- so the object says so itself.
    """
    sourced = vsdc_2026()
    unsourced = VsdcSettlementCalendar(
        TET_2026_SETTLEMENT_HOLIDAYS, FEB_2026, 'vsdc-2026-uncited')

    assert sourced.is_sourced
    assert not unsourced.is_sourced


# --------------------------------------------------------------------------
# The unsourced default
# --------------------------------------------------------------------------

def test_the_default_calendar_is_wrong_around_tet_and_says_so():
    """The weekday default must never back a published result.

    It holds no holidays at all, so it settles on Tet: the T+2 of the worked
    example comes back 2026-02-16, a week before VSDC actually settled. That
    is pinned deliberately -- the default exists for smoke runs, its id shouts
    UNSOURCED in any provenance record, and ``is_sourced`` is False so a
    caller can refuse it.
    """
    default = weekday_settlement_calendar(FEB_2026)

    assert default.settle_date(date(2026, 2, 12), 2) == date(2026, 2, 16)
    assert vsdc_2026().settle_date(date(2026, 2, 12), 2) == date(2026, 2, 23)
    assert not default.is_sourced
    assert 'UNSOURCED' in default.calendar_id
    assert 'UNSOURCED' in DEFAULT_SETTLEMENT_CALENDAR.calendar_id
    assert not DEFAULT_SETTLEMENT_CALENDAR.is_sourced


def test_the_module_default_covers_the_rulebook_window_and_no_more():
    """Even the throwaway calendar has a finite window it refuses past."""
    assert DEFAULT_SETTLEMENT_CALENDAR.covers(date(2020, 1, 1))
    assert DEFAULT_SETTLEMENT_CALENDAR.covers(date(2026, 12, 31))
    with pytest.raises(CalendarCoverageError):
        DEFAULT_SETTLEMENT_CALENDAR.is_settlement_day(date(2027, 1, 4))


# --------------------------------------------------------------------------
# The trading calendar is a different object
# --------------------------------------------------------------------------

def test_next_session_open_is_measured_in_sessions_not_settlement_days():
    """A margin call's cure window is counted in sessions.

    Two things are pinned: the open is strictly after ``ts`` (a call raised
    before Monday's open is curable at that open, not Tuesday's), and it skips
    the weekend rather than the settlement closure.
    """
    trading = VnTradingCalendar(frozenset(), FEB_2026, 'vn-2026')

    friday_afternoon = datetime(2026, 2, 13, 14, 0)
    assert trading.next_session_open(friday_afternoon, Venue.HSX) == datetime(
        2026, 2, 16, 9, 0)

    before_the_open = datetime(2026, 2, 13, 8, 0)
    assert trading.next_session_open(before_the_open, Venue.HSX) == datetime(
        2026, 2, 13, 9, 0)


def test_session_boundaries_are_per_venue():
    """The venue axis is real: HNXDS opens before the cash market closes late.

    HNXDS opens its auction at 08:45 against HSX's 09:00, and HNX's day ends
    at 15:00 after the PLO against HSX's 14:45 after the ATC. A DAY order's
    expiry instant therefore depends on where it rests.
    """
    trading = VnTradingCalendar(frozenset(), FEB_2026, 'vn-2026')
    monday = datetime(2026, 2, 23, 10, 0)

    assert trading.next_session_open(
        datetime(2026, 2, 23, 8, 0), Venue.HNXDS).time() == time(8, 45)
    assert trading.next_session_open(
        datetime(2026, 2, 23, 8, 0), Venue.HSX).time() == time(9, 0)
    assert trading.session_end(monday, Venue.HSX).time() == time(14, 45)
    assert trading.session_end(monday, Venue.HNX).time() == time(15, 0)
    # UPCoM has neither an ATC nor a PLO; its day ends when continuous
    # trading does. ExchangeSpec.trading_time_end raises on it, which is why
    # this module does not go through that property.
    assert trading.session_end(monday, Venue.UPCOM).time() == time(15, 0)


def test_a_non_trading_day_has_no_session_end():
    """Returning a plausible 14:45 on a Sunday would expire DAY orders while
    the exchange was shut, so it raises instead."""
    trading = VnTradingCalendar(frozenset(), FEB_2026, 'vn-2026')

    with pytest.raises(CalendarError, match='not a trading day'):
        trading.session_end(datetime(2026, 2, 15, 14, 0), Venue.HSX)


def test_a_rulebook_that_carries_dated_session_times_wins():
    """Session times are dated rules and belong in the rulebook.

    The injected maps are where they live until it carries them, so a
    ``RuleSet`` that can answer ``session_open`` is preferred over them
    without a change to this module.
    """
    class DatedRules:
        def session_open(self, venue):
            return time(9, 30)

        def session_close(self, venue):
            return time(14, 0)

    trading = VnTradingCalendar(frozenset(), FEB_2026, 'vn-2026')
    monday = datetime(2026, 2, 23, 8, 0)

    assert trading.next_session_open(
        monday, Venue.HSX, DatedRules()) == datetime(2026, 2, 23, 9, 30)
    assert trading.session_end(
        monday, Venue.HSX, DatedRules()) == datetime(2026, 2, 23, 14, 0)


def test_both_calendars_satisfy_their_protocols():
    """The Protocols are the seam ``ledgers``/``deposit`` type against.

    They are separate Protocols on purpose: a settlement calendar cannot be
    passed where a trading calendar is wanted, which is the type-level version
    of the mistake this whole module refutes.
    """
    settlement = vsdc_2026()
    trading = weekday_trading_calendar(FEB_2026)

    assert isinstance(settlement, SettlementCalendar)
    assert isinstance(trading, TradingCalendar)
    assert not isinstance(settlement, TradingCalendar)
