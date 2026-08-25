"""Settlement business days, and the trading days they are not.

**T+N is a depository fact, not an exchange fact.** T+2 is counted in VSDC
*settlement* business days, published annually as a settlement-holiday calendar
that is a **separate document** from the exchange trading calendar, and the two
diverge around Tet. The worked example the rulebook verifies verbatim
(Announcement 4228/TB-VSDC, 2025-11-20):

    VSDC closed settlement 2026-02-16 -> 2026-02-20 inclusive.
    T+2 of a 2026-02-12 trade settled 2026-02-23.
    T+2 of a 2026-02-13 trade settled 2026-02-24.
    T+1 of a 2026-02-13 trade settled 2026-02-23.

An earlier revision of the design spec claimed T+N was "holiday-correct by
construction" from counting the session dates the data source yields, with no
separate calendar needed. **That claim was false** (rulebook 9.5, and the
audit row at rulebook line ~933): counting exchange sessions gets every
settlement-only holiday wrong, and Tet is a settlement-only holiday of several
days every year. So this module exists, the calendar is a *data input* rather
than a derivation, and nothing here will invent a holiday it was not given.

Three consequences shape the API:

* **The calendar is constructed from dates the caller supplies.** There is no
  hardcoded Vietnamese holiday table in this file, because no such table could
  be sourced for 2020-2026 in one place -- VSDC publishes one notice per year.
  A calendar carries the citation it was built from
  (:attr:`VsdcSettlementCalendar.source`) and reports whether it has one
  (:attr:`~VsdcSettlementCalendar.is_sourced`).
* **Coverage is finite and asking outside it raises.** A calendar that
  answers "weekday, therefore settlement day" one day past the notice it was
  loaded from produces a settlement instant that *looks* sourced and is not.
  Every query outside the loaded window raises
  :class:`CalendarCoverageError`; :meth:`~VsdcSettlementCalendar.covers` is
  the non-raising question.
* **Settlement instants are datetimes.** Locked shape 3. The regime in force
  since 2022-08-29 turns on 13:00 on the settlement day and a ``date`` cannot
  express it. See :meth:`VsdcSettlementCalendar.settles_at` for the daily-bar
  consequence, which is the difference the Tier 1 demo turns on.

The trading calendar lives here too, deliberately as a **different object**
with a different vocabulary (sessions, not settlement days), so that no caller
can reach for the wrong one by accident. A margin call's cure window is
measured in sessions; a delivery is measured in settlement days; they are not
interchangeable and 2026-02-16 is the proof.
"""

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import (Any, FrozenSet, Iterable, Mapping, Optional, Protocol,
                    Tuple, Union, runtime_checkable)

from plutus.core.constant import DS as _DS_SPEC
from plutus.core.constant import HNX as _HNX_SPEC
from plutus.core.constant import HSX as _HSX_SPEC
from plutus.core.constant import UPCOM as _UPCOM_SPEC
from plutus.market.session.types import SettlementRule, Venue

__all__ = [
    # errors
    'CalendarError', 'CalendarCoverageError',
    # settlement
    'SettlementCalendar', 'VsdcSettlementCalendar',
    # trading
    'TradingCalendar', 'VnTradingCalendar',
    # unsourced defaults, for tests and smoke runs only
    'DEFAULT_COVERAGE', 'UNSOURCED_SETTLEMENT_CALENDAR_ID',
    'UNSOURCED_TRADING_CALENDAR_ID', 'weekday_settlement_calendar',
    'weekday_trading_calendar', 'DEFAULT_SETTLEMENT_CALENDAR',
    'DEFAULT_TRADING_CALENDAR',
]


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class CalendarError(Exception):
    """A calendar was asked for something it cannot answer honestly."""


class CalendarCoverageError(CalendarError, LookupError):
    """A date fell outside the window the calendar was loaded for.

    Raised rather than answered, because the alternative -- assuming Mon-Fri
    outside the loaded notice -- returns a settlement date indistinguishable
    from a sourced one. Around Tet that assumption is wrong by up to a week,
    and the caller has no way to tell.

    Subclasses :class:`LookupError` so a caller who genuinely wants to probe
    can catch it narrowly; prefer :meth:`VsdcSettlementCalendar.covers`, which
    asks the same question without an exception.
    """


# --------------------------------------------------------------------------
# The settlement calendar
# --------------------------------------------------------------------------

@runtime_checkable
class SettlementCalendar(Protocol):
    """VSDC settlement business days. Pluggable, resolved via ``rulebook.at``.

    A Protocol rather than a base class because the calendar is a per-year
    data input: a caller with a better source (a broker's own settlement
    schedule, a future year's notice) substitutes an object, not a subclass.
    """

    calendar_id: str

    def is_settlement_day(self, day: date) -> bool:
        """Whether VSDC settles on ``day``. Raises outside coverage."""
        ...

    def add_business_days(self, start: date, days: int) -> date:
        """``start`` + N settlement business days.

        ``days=0`` returns the next settlement day at or after ``start``.
        """
        ...

    def settle_date(self, trade_date: date, n: int) -> date:
        """The T+N settlement *date*.

        The same arithmetic as :meth:`add_business_days`, named for its use.
        """
        ...

    def settles_at(self, traded_at: datetime,
                   rule: SettlementRule) -> datetime:
        """THE function. Trade instant + rule -> settlement instant."""
        ...

    def covers(self, day: date) -> bool:
        """Whether the loaded calendar spans ``day``. Never raises."""
        ...


class VsdcSettlementCalendar:
    """A loaded VSDC settlement calendar for a stated coverage window.

    Two ways to build one, because two kinds of source exist:

    * ``VsdcSettlementCalendar(holidays, coverage)`` -- the usual case. The
      settlement week is Mon-Fri and ``holidays`` is the list of *extra*
      closures from that year's VSDC notice. Weekends are not listed.
    * :meth:`from_settlement_days` -- the explicit positive set. Use it when a
      source shows VSDC working a day the Mon-Fri assumption would exclude
      (a compensating Saturday). No such day is attested in 2020-2026, which
      is why the Mon-Fri default exists at all; the escape hatch exists
      because "no such day is attested" is weaker than "no such day occurs".

    ``source`` is the document the dates came from, and it is what
    :attr:`is_sourced` reports on. A calendar with no source string still
    computes, but says so -- ``exchange.py`` puts ``calendar_id`` into
    :class:`~plutus.market.session.types.SessionProvenance`, and a published
    result should not be resting on a calendar nobody can trace.

    The calendar is immutable after construction. :meth:`with_trading` returns
    a copy bound to a trading calendar rather than mutating in place, so a
    calendar handed to two accounts cannot be reconfigured under one of them.
    """

    def __init__(
        self,
        holidays: FrozenSet[date],
        coverage: Tuple[date, date],
        calendar_id: str = 'vsdc',
        *,
        source: Optional[str] = None,
        trading: Optional['TradingCalendar'] = None,
        _settlement_days: Optional[FrozenSet[date]] = None,
    ) -> None:
        """Build a calendar over an explicit, finite window.

        Args:
            holidays: settlement closures beyond the Mon-Fri working week, as
                published in that year's VSDC notice. Annotated as a
                ``FrozenSet`` to match the interface contract; any iterable of
                :class:`~datetime.date` is accepted and frozen.
            coverage: ``(first_day, last_day)``, both inclusive. Every query
                outside this raises. Set it to the window the source notices
                actually cover -- not to the backtest period, and never wider
                than the dates you hold.
            calendar_id: recorded in the session's provenance.
            source: the citation the dates came from, e.g.
                ``'VSDC Announcement 4228/TB-VSDC (2025-11-20)'``.
            trading: the trading calendar used only by the pre-2022-08-29
                settlement regime, whose delivery instant is the *next
                session's open* rather than a time on T+N. Optional here
                because the current regime does not need it; if a rule needs
                it and it is absent, :meth:`settles_at` raises rather than
                guessing which day the next session falls on.
            _settlement_days: internal. Set by :meth:`from_settlement_days`.
        """
        first, last = coverage
        if first > last:
            raise CalendarError(
                f'coverage {first} .. {last} runs backwards')
        self.calendar_id = calendar_id
        self.source = source
        self._coverage: Tuple[date, date] = (first, last)
        self._holidays: FrozenSet[date] = frozenset(holidays)
        self._settlement_days: Optional[FrozenSet[date]] = (
            None if _settlement_days is None else frozenset(_settlement_days))
        self._trading: Optional['TradingCalendar'] = trading

    # -- construction ------------------------------------------------------

    @classmethod
    def from_settlement_days(
        cls,
        days: Iterable[date],
        coverage: Tuple[date, date],
        calendar_id: str = 'vsdc',
        *,
        source: Optional[str] = None,
        trading: Optional['TradingCalendar'] = None,
    ) -> 'VsdcSettlementCalendar':
        """Build from the explicit set of days VSDC *does* settle.

        The complement of the usual constructor. Nothing is inferred: a day
        not in ``days`` is not a settlement day even if it is a Tuesday.
        """
        return cls(frozenset(), coverage, calendar_id, source=source,
                   trading=trading, _settlement_days=frozenset(days))

    @classmethod
    def from_file(
        cls, path: Union[str, Path],
    ) -> 'VsdcSettlementCalendar':
        """Load a calendar from JSON.

        The schema, which is deliberately explicit about its own limits::

            {
              "calendar_id": "vsdc-2026",
              "coverage": ["2026-01-01", "2026-12-31"],
              "holidays": ["2026-01-01", "2026-02-16", "..."],
              "source": "VSDC Announcement 4228/TB-VSDC (2025-11-20)"
            }

        ``holidays`` may be replaced by ``settlement_days`` -- the explicit
        positive set -- but not combined with it: a file carrying both is two
        answers to one question, so it is an error rather than a precedence
        rule. ``coverage`` is mandatory and is not inferred from the min and
        max of the dates, because the notice covers a year and the holidays in
        it do not.
        """
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(payload, dict):
            raise CalendarError(f'{path}: expected a JSON object')

        if 'coverage' not in payload:
            raise CalendarError(
                f'{path}: "coverage" is mandatory. A calendar with no stated '
                f'window cannot refuse a question it should refuse.')
        raw_coverage = payload['coverage']
        if (not isinstance(raw_coverage, (list, tuple))
                or len(raw_coverage) != 2):
            raise CalendarError(
                f'{path}: "coverage" must be [first_day, last_day]')
        coverage = (date.fromisoformat(raw_coverage[0]),
                    date.fromisoformat(raw_coverage[1]))

        has_holidays = 'holidays' in payload
        has_days = 'settlement_days' in payload
        if has_holidays and has_days:
            raise CalendarError(
                f'{path}: carries both "holidays" and "settlement_days". '
                f'They are two answers to one question -- keep one.')
        if not has_holidays and not has_days:
            raise CalendarError(
                f'{path}: needs "holidays" or "settlement_days". An empty '
                f'holiday list must be written out as [] -- a year with no '
                f'closures is a claim, and it should be made explicitly.')

        calendar_id = payload.get('calendar_id', Path(path).stem)
        source = payload.get('source')
        if has_days:
            return cls.from_settlement_days(
                [date.fromisoformat(d) for d in payload['settlement_days']],
                coverage, calendar_id, source=source)
        return cls(frozenset(date.fromisoformat(d)
                             for d in payload['holidays']),
                   coverage, calendar_id, source=source)

    def with_trading(
        self, trading: 'TradingCalendar',
    ) -> 'VsdcSettlementCalendar':
        """A copy bound to ``trading``, for the pre-2022-08-29 regime."""
        return VsdcSettlementCalendar(
            self._holidays, self._coverage, self.calendar_id,
            source=self.source, trading=trading,
            _settlement_days=self._settlement_days)

    # -- what this calendar is ---------------------------------------------

    @property
    def coverage(self) -> Tuple[date, date]:
        """The inclusive window this calendar can answer for."""
        return self._coverage

    @property
    def holidays(self) -> FrozenSet[date]:
        """The extra closures; empty when built from settlement days."""
        return self._holidays

    @property
    def is_sourced(self) -> bool:
        """Whether the dates carry a citation.

        False is not an error and does not stop the arithmetic. It is the flag
        a published result must check: rulebook 9.5 grades the settlement
        calendar ``high`` *because of* Announcement 4228/TB-VSDC, and a
        calendar with no such document behind it inherits none of that grade.
        """
        return self.source is not None

    def __repr__(self) -> str:
        first, last = self._coverage
        return (f'VsdcSettlementCalendar(calendar_id={self.calendar_id!r}, '
                f'coverage=({first.isoformat()}, {last.isoformat()}), '
                f'is_sourced={self.is_sourced})')

    # -- coverage ----------------------------------------------------------

    def covers(self, day: date) -> bool:
        """Whether the loaded calendar spans ``day``. Never raises."""
        first, last = self._coverage
        return first <= day <= last

    def assert_covers(self, day: date) -> None:
        """Raise rather than extrapolate past the loaded window.

        A calendar that silently assumes weekdays-only outside its coverage
        produces a settlement instant that looks sourced and is not. The T+2
        of 2026-02-12 is 2026-02-23 only if the 2026 notice is loaded; from
        the 2025 notice alone the honest answer is "I do not know", and that
        is what this raises.
        """
        if not self.covers(day):
            first, last = self._coverage
            raise CalendarCoverageError(
                f'{day.isoformat()} is outside settlement calendar '
                f'{self.calendar_id!r}, which covers '
                f'{first.isoformat()} .. {last.isoformat()}. Load the VSDC '
                f'notice for that year rather than extrapolating weekdays: '
                f'settlement-only closures (Tet) make the weekday answer '
                f'wrong by days.')

    # -- the arithmetic ----------------------------------------------------

    def is_settlement_day(self, day: date) -> bool:
        """Whether VSDC settles on ``day``.

        Raises :class:`CalendarCoverageError` outside coverage rather than
        returning False, because "not a settlement day" and "I was not told
        about that day" are different answers and only one of them is safe to
        count with.
        """
        self.assert_covers(day)
        if self._settlement_days is not None:
            return day in self._settlement_days
        # The Mon-Fri working week is the VSDC convention (the settlement
        # notices list closures against it, never weekends). Where a source
        # shows a working Saturday, build with from_settlement_days instead.
        return day.weekday() < 5 and day not in self._holidays

    def settle_date(self, trade_date: date, n: int) -> date:
        """The date T+``n`` settles on, counted in settlement business days.

        Decision 109/QD-VSD Art. 4(4), verbatim: "Ngay thanh toan giao dich co
        phieu, chung chi quy, chung quyen co bao dam la ngay lam viec thu hai
        lien ke sau ngay giao dich (T+2)" -- *the second working day
        immediately following the trading day*. So each of the ``n`` steps
        moves to the next settlement business day **strictly after** the
        cursor, and ``n=0`` means the trade date itself when it is a
        settlement day (the T+0 cycle privately placed bonds settle on).

        **Counting exchange trading days here would be wrong.** They are a
        different calendar published by a different institution, and around
        Tet the settlement break is the longer of the two. Worked example,
        verified verbatim from Announcement 4228/TB-VSDC: VSDC closed
        2026-02-16 -> 02-20, so T+2 of a 2026-02-12 trade is 2026-02-23 --
        seven calendar days later than the weekday answer, and later still
        than counting bars, by however many sessions the exchange ran while
        the depository was shut.

        Raises:
            ValueError: if ``n`` is negative. Settlement runs forwards; a
                negative cycle is a caller bug, not a request to look back.
            CalendarCoverageError: if the trade date or any day the count
                walks through falls outside the loaded window.
        """
        if n < 0:
            raise ValueError(
                f'settle_date needs n >= 0, got {n}; T+N counts forwards')
        self.assert_covers(trade_date)
        cursor = trade_date
        if n == 0:
            while not self.is_settlement_day(cursor):
                cursor += timedelta(days=1)
                self.assert_covers(cursor)
            return cursor
        for _ in range(n):
            cursor += timedelta(days=1)
            self.assert_covers(cursor)
            while not self.is_settlement_day(cursor):
                cursor += timedelta(days=1)
                self.assert_covers(cursor)
        return cursor

    def add_business_days(self, start: date, days: int) -> date:
        """``start`` + ``days`` settlement business days.

        The interface contract's name for :meth:`settle_date`, kept because
        ``ledgers.py`` and ``deposit.py`` are written against it. Identical
        semantics, including ``days=0`` returning the next settlement day at
        or after ``start``.
        """
        return self.settle_date(start, days)

    def settles_at(
        self,
        traded_at: datetime,
        rule: SettlementRule,
        *,
        trading: Optional['TradingCalendar'] = None,
    ) -> datetime:
        """Trade instant + settlement rule -> the instant delivery lands.

        Returns a **datetime**, never a date (locked shape 3): the two dated
        regimes differ in the time of day, not in the cycle length, and a date
        cannot express the difference.

        * From 2022-08-29: T+2, custodian-member allocation to the client no
          later than 13:00 (Decision 109/QD-VSD Art. 4). Result:
          ``13:00 on T+2``.
        * 2016-01-01 to 2022-08-26: T+2, but settlement completed 15:30-16:00,
          *after the close*, so the first usable session was the open of T+3.
          The rule carries ``delivery_on_next_session_open=True`` and this
          method resolves the next **trading** day -- a session question,
          which is why a :class:`TradingCalendar` is required for it and why
          it raises instead of guessing when none was supplied. Encoding this
          regime as 16:00 on T+2 would make a T+2 afternoon sale look legal.

        **On midnight-stamped daily bars, T+2 @ 13:00 behaves as T+3.** A
        daily bar's ``ts`` is 00:00, so the T+2 bar does not reach a 13:00
        threshold and the T+3 bar is the first that does. That is stated here
        rather than left to emerge from timestamp arithmetic because it is the
        behaviour the Tier 1 demo turns on. It is the conservative direction
        -- the simulator holds shares locked for one bar longer than the real
        market did -- and it is intended.

        The returned instant carries ``traded_at``'s ``tzinfo`` so a tz-aware
        session stays tz-aware. Asia/Ho_Chi_Minh has been a fixed +07 with no
        DST since 1975, so attaching the zone to a different day is safe here
        in a way it would not be in a DST jurisdiction.

        Note that 13:00 is a **regulatory deadline, not a guarantee**: on
        2026-02-27 VSDC allocation ran ~2 hours late. The simulator models the
        deadline; a strategy whose edge lives inside that slippage is not
        modelled by it.
        """
        day = self.settle_date(traded_at.date(), rule.cycle_days)
        if rule.delivery_on_next_session_open:
            calendar = trading if trading is not None else self._trading
            if calendar is None:
                raise CalendarError(
                    f'settlement rule {rule.label!r} delivers at the next '
                    f'session open, which is a trading-day question this '
                    f'settlement calendar cannot answer. Pass a '
                    f'TradingCalendar to settles_at(trading=...) or bind one '
                    f'with with_trading(). Falling back to the settlement '
                    f'calendar would silently assume the two agree, which is '
                    f'the exact assumption this module exists to refuse.')
            day = calendar.next_trading_day(day)
        settled = datetime.combine(day, rule.delivery_time)
        if traded_at.tzinfo is not None:
            settled = settled.replace(tzinfo=traded_at.tzinfo)
        return settled


# --------------------------------------------------------------------------
# The trading calendar -- deliberately a different object
# --------------------------------------------------------------------------

#: Session boundaries by venue, read from the specs already in
#: :mod:`plutus.core.constant` rather than retyped. ``trading_time_start`` is
#: the opening auction where one exists (HSX 09:00, HNXDS 08:45) and the
#: continuous open otherwise; ``trading_time_end`` is the last matching phase's
#: end (HSX 14:45 at the ATC, HNX 15:00 after the PLO).
#:
#: **These are undated**, which is an assumption, not a sourced fact: they are
#: the sessions in force today, applied to every date. No session-time change
#: is attested in 2020-2026, but the KRX cutover is exactly the kind of event
#: that would move them, and when the rulebook carries dated session times
#: these defaults should give way to ``rules``.
_VENUE_SPECS = {
    Venue.HSX: _HSX_SPEC,
    Venue.HNX: _HNX_SPEC,
    Venue.UPCOM: _UPCOM_SPEC,
    Venue.HNXDS: _DS_SPEC,
}


def _spec_close(spec: Any) -> time:
    """The last matching phase's end, tolerating a venue with no auction.

    ``ExchangeSpec.trading_time_end`` reads
    ``plo_session.end if plo_session else atc_session.end`` and **raises
    AttributeError on UPCoM**, which has neither: UPCoM runs continuous to
    15:00 with no closing auction and no post-close session. Reaching past the
    property rather than through it keeps this module importable; the fix
    belongs in ``constant.py``, which this task may not edit.
    """
    for session in (spec.plo_session, spec.atc_session, spec.lo_session):
        if session is not None:
            return session.end
    raise CalendarError(f'{spec.code} has no session with an end time')


@runtime_checkable
class TradingCalendar(Protocol):
    """Exchange trading days. Deliberately a DIFFERENT object.

    Not a superset and not a subset of :class:`SettlementCalendar`: 2026-02-19
    can be a trading day and not a settlement day. Keeping them apart in the
    type system is what stops a delivery being counted in sessions, which is
    the mistake rulebook 9.5 documents.
    """

    calendar_id: str

    def is_trading_day(self, day: date) -> bool:
        """Whether the exchange holds a session on ``day``."""
        ...

    def next_trading_day(self, day: date) -> date:
        """The first trading day strictly after ``day``."""
        ...

    def next_session_open(self, ts: datetime, venue: Venue,
                          rules: Any = None) -> datetime:
        """The next session's open on ``venue``, strictly after ``ts``."""
        ...

    def session_end(self, ts: datetime, venue: Venue,
                    rules: Any = None) -> datetime:
        """End of the last matching phase of ``ts``'s day."""
        ...

    def covers(self, day: date) -> bool:
        """Whether the loaded calendar spans ``day``. Never raises."""
        ...


class VnTradingCalendar:
    """Mon-Fri minus Labour Code holidays, plus SSC-ordered closures.

    "Mon-Fri, minus Labour Code holidays" is the exchange rule itself
    (QD 352/QD-SGDHCM Dieu 4.1, which cites the Labour Code clause and nothing
    more), so ``holidays`` is the Labour Code list for the years covered plus
    any ad-hoc closure the SSC ordered. As with the settlement calendar, none
    of it is hardcoded here.

    ``rules`` on :meth:`next_session_open` and :meth:`session_end` is the
    ``RuleSet`` at that instant. It is honoured when it can answer -- a
    rulebook that grows dated session times will be used without a change here
    -- and the injected ``session_open`` / ``session_close`` maps answer
    otherwise. Session times are *dated rules* and belong in the rulebook; the
    maps are where they live until it carries them.
    """

    def __init__(
        self,
        holidays: FrozenSet[date],
        coverage: Tuple[date, date],
        calendar_id: str = 'vn-trading',
        *,
        source: Optional[str] = None,
        session_open: Optional[Mapping[Venue, time]] = None,
        session_close: Optional[Mapping[Venue, time]] = None,
    ) -> None:
        first, last = coverage
        if first > last:
            raise CalendarError(f'coverage {first} .. {last} runs backwards')
        self.calendar_id = calendar_id
        self.source = source
        self._coverage: Tuple[date, date] = (first, last)
        self._holidays: FrozenSet[date] = frozenset(holidays)
        self._open: Mapping[Venue, time] = dict(session_open) if session_open \
            else {v: s.trading_time_start for v, s in _VENUE_SPECS.items()}
        self._close: Mapping[Venue, time] = dict(session_close) \
            if session_close \
            else {v: _spec_close(s) for v, s in _VENUE_SPECS.items()}

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> 'VnTradingCalendar':
        """Load from JSON. Same schema as the settlement calendar's, minus
        ``settlement_days``; ``holidays`` here are exchange closures."""
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(payload, dict):
            raise CalendarError(f'{path}: expected a JSON object')
        if 'coverage' not in payload or 'holidays' not in payload:
            raise CalendarError(
                f'{path}: needs "coverage" and "holidays". An empty holiday '
                f'list must be written out as [].')
        raw = payload['coverage']
        coverage = (date.fromisoformat(raw[0]), date.fromisoformat(raw[1]))
        return cls(frozenset(date.fromisoformat(d)
                             for d in payload['holidays']),
                   coverage,
                   payload.get('calendar_id', Path(path).stem),
                   source=payload.get('source'))

    @property
    def coverage(self) -> Tuple[date, date]:
        """The inclusive window this calendar can answer for."""
        return self._coverage

    @property
    def is_sourced(self) -> bool:
        """Whether the closures carry a citation."""
        return self.source is not None

    def __repr__(self) -> str:
        first, last = self._coverage
        return (f'VnTradingCalendar(calendar_id={self.calendar_id!r}, '
                f'coverage=({first.isoformat()}, {last.isoformat()}), '
                f'is_sourced={self.is_sourced})')

    def covers(self, day: date) -> bool:
        """Whether the loaded calendar spans ``day``. Never raises."""
        first, last = self._coverage
        return first <= day <= last

    def assert_covers(self, day: date) -> None:
        """Raise rather than extrapolate past the loaded window."""
        if not self.covers(day):
            first, last = self._coverage
            raise CalendarCoverageError(
                f'{day.isoformat()} is outside trading calendar '
                f'{self.calendar_id!r}, which covers '
                f'{first.isoformat()} .. {last.isoformat()}.')

    def is_trading_day(self, day: date) -> bool:
        """Whether the exchange holds a session on ``day``."""
        self.assert_covers(day)
        return day.weekday() < 5 and day not in self._holidays

    def next_trading_day(self, day: date) -> date:
        """The first trading day **strictly after** ``day``.

        Strictly after, because its caller is the pre-2022-08-29 settlement
        regime: settlement completed after the close on T+2, so the first
        session that can use it is the next one, never the same day.
        """
        cursor = day + timedelta(days=1)
        self.assert_covers(cursor)
        while not self.is_trading_day(cursor):
            cursor += timedelta(days=1)
            self.assert_covers(cursor)
        return cursor

    def next_session_open(self, ts: datetime, venue: Venue,
                          rules: Any = None) -> datetime:
        """The next open on ``venue`` strictly after ``ts``.

        This is the unit a margin call's ``cure_by`` is measured in --
        sessions, not settlement days. A call raised in Friday's afternoon is
        curable at Monday's open; a call raised before Monday's open is
        curable at that open, which is why "strictly after ``ts``" and not
        "the next day".
        """
        open_time = self._session_open_time(venue, rules)
        day = ts.date()
        self.assert_covers(day)
        if self.is_trading_day(day):
            candidate = datetime.combine(day, open_time)
            if ts.tzinfo is not None:
                candidate = candidate.replace(tzinfo=ts.tzinfo)
            if candidate > ts:
                return candidate
        nxt = datetime.combine(self.next_trading_day(day), open_time)
        if ts.tzinfo is not None:
            nxt = nxt.replace(tzinfo=ts.tzinfo)
        return nxt

    def session_end(self, ts: datetime, venue: Venue,
                    rules: Any = None) -> datetime:
        """End of the last matching phase of ``ts``'s day on ``venue``.

        Where a DAY order expires
        (:class:`~plutus.market.session.types.ExpiryTrigger`
        ``SESSION_END``) -- and note it is the end of the *last matching
        phase*, so HNX's is 15:00 after the PLO and HSX's is 14:45 after the
        ATC. The noon break is not an end of anything, which is the reason
        ``ExpiryTrigger`` has no ``NOON_BREAK`` member.

        Raises on a non-trading day: there is no session to end, and returning
        a plausible 14:45 on a Sunday would let a DAY order expire at an
        instant the exchange was shut.
        """
        day = ts.date()
        self.assert_covers(day)
        if not self.is_trading_day(day):
            raise CalendarError(
                f'{day.isoformat()} is not a trading day on {venue.value}, '
                f'so it has no session end')
        end = datetime.combine(day, self._session_close_time(venue, rules))
        if ts.tzinfo is not None:
            end = end.replace(tzinfo=ts.tzinfo)
        return end

    # -- session times -----------------------------------------------------

    def _session_open_time(self, venue: Venue, rules: Any) -> time:
        """The venue's open, preferring a rulebook that carries dated times."""
        from_rules = getattr(rules, 'session_open', None)
        if callable(from_rules):
            return from_rules(venue)
        try:
            return self._open[venue]
        except KeyError:
            raise CalendarError(
                f'no session open known for {venue.value}; pass '
                f'session_open={{{venue.value}: ...}} or a RuleSet that '
                f'answers session_open(venue)') from None

    def _session_close_time(self, venue: Venue, rules: Any) -> time:
        """The venue's close, preferring a rulebook with dated times."""
        from_rules = getattr(rules, 'session_close', None)
        if callable(from_rules):
            return from_rules(venue)
        try:
            return self._close[venue]
        except KeyError:
            raise CalendarError(
                f'no session close known for {venue.value}; pass '
                f'session_close={{{venue.value}: ...}} or a RuleSet that '
                f'answers session_close(venue)') from None


# --------------------------------------------------------------------------
# Unsourced defaults -- tests and smoke runs only
# --------------------------------------------------------------------------

#: The window the rulebook covers, and therefore the widest window a default
#: calendar pretends to. It is a *span*, not a claim about holidays.
DEFAULT_COVERAGE: Tuple[date, date] = (date(2020, 1, 1), date(2026, 12, 31))

#: Ids chosen to be loud in a provenance record. If one of these turns up in a
#: published result's :class:`~plutus.market.session.types.SessionProvenance`,
#: the result is wrong around every Tet in its period.
UNSOURCED_SETTLEMENT_CALENDAR_ID = 'weekday-only-UNSOURCED'
UNSOURCED_TRADING_CALENDAR_ID = 'weekday-only-UNSOURCED'


def weekday_settlement_calendar(
    coverage: Tuple[date, date] = DEFAULT_COVERAGE,
    *,
    trading: Optional[TradingCalendar] = None,
) -> VsdcSettlementCalendar:
    """Every Mon-Fri in ``coverage`` is a settlement day. **Not Tet-correct.**

    A convenience for tests and smoke runs, and it is wrong by construction:
    it holds **no** holidays, so it settles on Tet, on 30 April, on
    2 September and on every other closure Vietnam observes. Against the one
    case the rulebook verifies verbatim it returns 2026-02-16 for the T+2 of a
    2026-02-12 trade, where VSDC settled on 2026-02-23: a week early, arrived
    at by counting five days the depository was shut.

    **Must not back a published result.** Load the VSDC notices for the years
    the run covers and build a real
    :class:`VsdcSettlementCalendar`; this one exists so a test does not need a
    data file to exercise arithmetic that is not about holidays, and it
    reports ``is_sourced == False`` so a caller can refuse it.
    """
    return VsdcSettlementCalendar(
        frozenset(), coverage, UNSOURCED_SETTLEMENT_CALENDAR_ID,
        source=None, trading=trading)


def weekday_trading_calendar(
    coverage: Tuple[date, date] = DEFAULT_COVERAGE,
) -> VnTradingCalendar:
    """Every Mon-Fri in ``coverage`` is a trading day. **Not Tet-correct.**

    The trading-side twin of :func:`weekday_settlement_calendar`, carrying the
    same warning: no Labour Code holidays, no SSC closures, ``is_sourced ==
    False``, and not fit to stand behind a published number.
    """
    return VnTradingCalendar(
        frozenset(), coverage, UNSOURCED_TRADING_CALENDAR_ID, source=None)


#: Module-level unsourced defaults. Immutable, so sharing them is safe; wrong
#: around every holiday, so shipping a result on them is not.
DEFAULT_TRADING_CALENDAR: VnTradingCalendar = weekday_trading_calendar()
DEFAULT_SETTLEMENT_CALENDAR: VsdcSettlementCalendar = (
    weekday_settlement_calendar(trading=DEFAULT_TRADING_CALENDAR))
