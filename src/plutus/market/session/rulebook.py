"""Per-instant resolution of the Vietnamese exchange rulebook.

**A venue is ``(ticker, ts)``, never ``(ticker)``.** Every rule this package
applies -- round lot, tick grid, band width, session phase, accepted order
types, settlement cycle, margin ratio, charge schedule -- is resolved at the
instant being simulated, through :meth:`Rulebook.at`. This is locked shape 1 of
the design, and it is first in the build order because every other lookup reads
it: a frozen venue or a frozen regime here propagates into every band, tick,
lot and fee downstream, and cannot be unpicked later without threading a ``ts``
axis through every call site.

The two builds this module exists to forbid:

* **A config-at-load singleton.** A ``period`` spans regime changes. Settlement
  changed inside 2022, HOSE's round lot changed inside 2021, the VSD margin
  ratio changed inside 2022 and KRX changed HOSE inside 2025, so one scalar
  "version" chosen at load is wrong for most of any multi-month run.
* **A ticker-keyed venue cache.** ``adapters/datahub.py`` holds
  ``Dict[str, InstrumentSpec]`` -- one venue per ticker for the process
  lifetime. From 2025-07 hundreds of tickers genuinely change venue, and a
  transferred ticker then gets UPCoM's 100d tick and +/-15% band on days it
  actually traded on HOSE under a 10d tick and +/-7% band.
  :class:`SymbolRouter` is the seam that contains that defect; it holds no
  cache of its own.

Three conventions, each of which has already caused a bug somewhere in this
repository:

**Half-open intervals, ``[start, end)``.** ``constant.py``'s
``AbstractTradingSession.is_current`` was changed to ``start <= t < end``
because Vietnamese session boundaries abut exactly -- 09:15:00 both ends the
opening auction and begins continuous trading -- so an inclusive upper bound
puts one instant in two sessions and makes the answer order-dependent. Dated
rule intervals here follow the same convention for the same reason: the KRX
cutover date 2025-05-05 must belong to exactly one edition, and a rule that
runs "to 2025-05-04" and its successor that runs "from 2025-05-05" must not
both claim 2025-05-05 nor leave it unclaimed. Closing at the bottom and opening
at the top partitions the timeline exactly once.

**The rulebook document prints CLOSED intervals; this module stores HALF-OPEN
ones.** ``docs/reference/vn-exchange-rulebook-2020-2026.md`` writes
``effective_to = 2025-05-04`` meaning "in force through 2025-05-04 inclusive",
and :class:`plutus.market.session.types.RuleCitation` follows that document
convention (``covers()`` tests ``on > effective_to``). :class:`RuleInterval`
stores the exclusive bound instead, and :func:`_interval` converts between them
so the two can never drift. Transcribing a printed ``effective_to`` straight
into an exclusive bound is a one-day error at every regime boundary in the
file, which is why the conversion is done once, in one place.

**The KRX cutover is a dated rule SET, not a migration.** Both editions ship
and both stay. ``at(ts)`` picks; a run spanning 2025-05-05 gets pre-KRX rules
on one side and post-KRX on the other within one session. Populating post-KRX
values is data entry into the tables below, not a code change. Where a post-KRX
value is *not yet sourced*, the table carries an explicit ``UNKNOWN`` interval
starting at the cutover rather than letting the pre-KRX interval run on --
see :data:`RuleStatus` and :class:`UnresolvedRule`. Silently returning the
pre-KRX value would be the worst available outcome: a wrong number that reports
itself as a sourced one.

**Unknown is not a value.** Resolving a rule at a date where it is unknown is
distinguishable from resolving one that is known. :meth:`RuleSet.resolve`
returns a three-state :class:`RuleResolution` -- ``KNOWN`` /
``NOT_APPLICABLE`` / ``UNKNOWN`` -- mirroring the three-state
:class:`plutus.market.verdicts.Verdict` and for the same reason. The typed
accessors (:meth:`RuleSet.trading_unit` and friends) unwrap that and raise
:class:`UnresolvedRule` on ``UNKNOWN``, so no caller can mistake a gap for an
answer; ``exchange.py`` catches it and reports ``Rejected(verdict=
INDETERMINATE)``, which keeps a data gap countable apart from a market rule.

Units, stated once because mixing them is the single easiest error here:

* Cash-venue prices and ticks are in **thousand VND**, the corpus convention
  (``VietnamMarketConstant.UNIT_PRICE = 1000``). A 100d tick is
  ``Decimal('0.1')``; the 1d put-through tick is ``Decimal('0.001')``.
* HNXDS index futures quote **index points**; the tick is ``Decimal('0.1')``
  index point and VND appears only through the 100,000 multiplier. Government
  bond futures on the same venue quote **VND** on a 100,000d face and step
  ``Decimal('1')`` -- the same numeral attached to a different unit, which is
  why band and tick are keyed to the contract and never to the exchange.
* Charge ``rate`` is a Decimal fraction (``Decimal('0.00027')``); charge
  ``amount`` is absolute VND (``Decimal('2700')``).

Every dated value below carries a :class:`RuleCitation` with a document, an
effective date and a :class:`Confidence` grade, taken from the rulebook
research. That traceability is the rulebook's whole claim, and it is why broker
terms -- commission, the sale-advance rate, the margin cure window, the
utilisation ladder -- are refused here and live in
:class:`plutus.market.broker.BrokerTerms` instead.
"""

from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from itertools import product
from typing import (Any, Dict, FrozenSet, Iterable, Mapping, Optional, Sequence,
                    Tuple)

from plutus.core.constant import (DS, HNX, HSX, UPCOM, ExchangeSpec,
                                  get_hsx_tick_size, get_trading_unit,
                                  is_covered_warrant, is_etf)
from plutus.market.adapters.base import MarketDataSource
from plutus.market.exchanges import (HNX_EXCHANGE, HNXDS_EXCHANGE,
                                     HSX_EXCHANGE, UPCOM_EXCHANGE, Exchange)
from plutus.market.margin import vsd_initial_margin
from plutus.market.protocol import (InstrumentKind, InstrumentSpec, OrderType,
                                    SessionPhase)
from plutus.market.session.types import (ChargeBase, ChargeClass, ChargeRule,
                                         ChargeSide, Confidence, DebitedAt,
                                         InvestorClass, LeviedBy, Pin, Pool,
                                         RuleCitation, RulebookEdition,
                                         SettlementRule, TradingMethod, Venue)

__all__ = [
    'KRX_CUTOVER', 'COVERAGE_START', 'COVERAGE_END',
    'RuleName', 'RuleStatus', 'RuleResolution', 'RuleInterval',
    'UnresolvedRule', 'RuleSet', 'Rulebook', 'SymbolRouter', 'VenueListing',
    'RULEBOOK_IDS',
]


# --------------------------------------------------------------------------
# The dates that partition the rulebook
# --------------------------------------------------------------------------

#: The KRX go-live. Gazetted rather than announced: Circular 18/2025/TT-BTC
#: (signed 2025-04-26) takes effect on this date, and VNX QD 21's own
#: commencement clause -- "from the day the new information-technology system
#: officially operates" -- is pinned to it by that circular. A dated rule SET
#: boundary, not a migration: the interval that ends here is closed at
#: 2025-05-04 and the interval that begins here opens at 2025-05-05, so this
#: instant belongs to exactly one edition.
KRX_CUTOVER = date(2025, 5, 5)

#: The rulebook research covers 2020-01-01 -> 2026-08-25. Resolving inside the
#: window is a lookup; resolving outside it is an extrapolation, and this
#: module refuses to extrapolate. A few series legitimately start earlier
#: (T+2 from 2016-01-01, VSD margin from 2017-08-10) because their own sources
#: establish the earlier boundary; those resolve fine before 2020.
COVERAGE_START = date(2020, 1, 1)
COVERAGE_END = date(2026, 8, 25)

#: Rulebook editions this module can build. A second entry here is how a
#: counterfactual or a future rulebook ships -- not a fork of the resolver.
RULEBOOK_IDS: Tuple[str, ...] = ('vn-2020-2026',)


# --------------------------------------------------------------------------
# What can be resolved, and in what state
# --------------------------------------------------------------------------

class RuleName(str, Enum):
    """Every rule this module can resolve at an instant.

    A closed vocabulary rather than free-form strings because
    :meth:`RuleSet.citation`, :class:`Pin` paths and any future
    ``IndeterminateReport.by_rule`` count all key on it, and a typo in a
    free-form key is a silent miss rather than an error.
    """

    TRADING_UNIT = 'trading_unit'
    DAILY_TRADING_LIMIT = 'daily_trading_limit'
    WIDENED_TRADING_LIMIT = 'widened_trading_limit'
    TICK_SIZE = 'tick_size'
    LEGAL_ORDER_TYPES = 'legal_order_types'
    SETTLEMENT = 'settlement'
    INITIAL_MARGIN_RATE = 'initial_margin_rate'
    MARGIN_MODEL = 'margin_model'
    POSITION_LIMIT = 'position_limit'
    MAX_ORDER_SIZE = 'max_order_size'
    CHARGE = 'charge'


class RuleStatus(str, Enum):
    """Whether a resolution produced a value, and if not, why not.

    Three states, mirroring :class:`plutus.market.verdicts.Verdict` and for the
    same reason: when the rulebook cannot decide, saying so is required and
    guessing is forbidden.

    The distinction between the two negative states is load-bearing and is not
    a nicety. ``NOT_APPLICABLE`` is a *sourced* answer -- listed bonds have no
    price band at all ("khong quy dinh gioi han dao dong gia"), so "no band" is
    what the rulebook says. ``UNKNOWN`` is an absence of evidence -- no
    document was found, or the post-KRX value has not been sourced yet.
    Collapsing them onto ``None`` would report a research gap as a market rule,
    which is exactly the error this module exists to prevent.
    """

    KNOWN = 'known'
    NOT_APPLICABLE = 'not_applicable'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class RuleResolution:
    """One rule resolved at one instant: the value, and its provenance.

    The total, non-raising API. Every typed accessor on :class:`RuleSet` is a
    thin unwrapping of one of these, so a caller that wants to *count*
    unresolved rules rather than handle an exception reads this instead.

    ``pinned`` is True when a counterfactual :class:`Pin` overrode the dated
    value. A pinned resolution is legal -- it is how a post-KRX rulebook is run
    against pre-KRX data as a control -- but it reports itself as pinned, and
    ``citation`` is then ``None`` because no document says what the pin says.
    That self-report is the whole difference between a counterfactual and a
    lie.
    """

    rule: RuleName
    key: Tuple[Any, ...]
    ts: datetime
    status: RuleStatus
    value: Any = None
    citation: Optional[RuleCitation] = None
    confidence: Optional[Confidence] = None
    note: Optional[str] = None
    pinned: bool = False

    @property
    def is_known(self) -> bool:
        return self.status is RuleStatus.KNOWN

    def __str__(self) -> str:
        key = '.'.join(_key_token(k) for k in self.key if k is not None)
        return f'{self.rule.value}{"." + key if key else ""}@{self.ts.isoformat()}'


class UnresolvedRule(LookupError):
    """A rule was asked for at an instant where the rulebook does not know it.

    Raised only by the typed accessors, which have nowhere to put a
    three-state answer. ``exchange.py`` catches it at the ``submit()``
    boundary and turns it into ``Rejected(verdict=INDETERMINATE)`` with the
    rule named, which keeps "the data could not decide" countable apart from
    "a rule said no" (contract section 2.3).

    A ``LookupError`` rather than a bespoke base because that is what a failed
    table lookup is, and because a caller who forgets to handle it gets a
    traceback naming the rule and the instant instead of a plausible number.
    """

    def __init__(self, resolution: RuleResolution):
        self.resolution = resolution
        reason = resolution.note or 'no dated interval covers this instant'
        super().__init__(f'{resolution}: {reason}')


# --------------------------------------------------------------------------
# Dated intervals
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleInterval:
    """One dated row of the rulebook, with a HALF-OPEN validity window.

    ``effective_to`` is **exclusive** -- the first date on which this row is no
    longer in force -- while the rulebook document and
    :class:`RuleCitation.effective_to` both print the *inclusive* last date.
    Build these with :func:`_interval`, which does the conversion, rather than
    by hand.

    ``status`` lets a row assert an absence as data. An ``UNKNOWN`` row placed
    at 2025-05-05 is how "the post-KRX value has not been sourced" is expressed
    without leaving a hole that the preceding row would silently fill.
    """

    value: Any
    effective_from: date
    effective_to: Optional[date]
    citation: Optional[RuleCitation] = None
    status: RuleStatus = RuleStatus.KNOWN
    note: Optional[str] = None

    def covers(self, on: date) -> bool:
        """Half-open containment: ``effective_from <= on < effective_to``."""
        if on < self.effective_from:
            return False
        return self.effective_to is None or on < self.effective_to


def _interval(
    value: Any,
    effective_from: date,
    effective_to: Optional[date] = None,
    *,
    document: str,
    confidence: Confidence,
    article: Optional[str] = None,
    note: Optional[str] = None,
    status: RuleStatus = RuleStatus.KNOWN,
) -> RuleInterval:
    """A dated row, with the closed/half-open conversion done once.

    ``effective_to`` here is the **exclusive** bound, matching
    :class:`RuleInterval`; the citation attached to the row gets the
    *inclusive* last date the rulebook document prints, i.e. one day earlier.
    Doing this in one function is what stops a one-day error appearing at every
    regime boundary in the tables below.
    """
    citation = RuleCitation(
        document=document,
        effective_from=effective_from,
        confidence=confidence,
        article=article,
        effective_to=(effective_to - timedelta(days=1)
                      if effective_to is not None else None),
        note=note,
    )
    return RuleInterval(value=value, effective_from=effective_from,
                        effective_to=effective_to, citation=citation,
                        status=status, note=note)


def _unsourced(
    effective_from: date,
    effective_to: Optional[date] = None,
    *,
    note: str,
    document: str = 'no source located',
    confidence: Confidence = Confidence.UNVERIFIED,
) -> RuleInterval:
    """A row that asserts an ABSENCE of evidence, as data.

    This is the mechanism the design requires for the KRX edition: where a
    post-KRX value is not yet sourced, the rulebook must say so explicitly
    rather than letting the pre-KRX row run on. Replacing one of these with an
    :func:`_interval` carrying a document and a value is data entry -- no code
    below changes.
    """
    return _interval(None, effective_from, effective_to, document=document,
                     confidence=confidence, note=note,
                     status=RuleStatus.UNKNOWN)


def _key_token(value: Any) -> str:
    """A stable string for one component of a resolution key."""
    return value.value if isinstance(value, Enum) else str(value)


def _pick(series: Sequence[RuleInterval], on: date) -> Optional[RuleInterval]:
    """The single row in force on ``on``.

    Returns the *last* covering row so that a table whose rows are appended in
    chronological order is read correctly even if two rows overlap by mistake;
    an overlap is a data defect, and preferring the later row makes it behave
    like a correction rather than like a silent revert.
    """
    found = None
    for row in series:
        if row.covers(on):
            found = row
    return found


# --------------------------------------------------------------------------
# Venue plumbing
# --------------------------------------------------------------------------

#: The four ``ExchangeSpec`` singletons, read for SESSION BOUNDARIES and the
#: tick FUNCTION only.
#:
#: Reading them for anything dated is forbidden and is why this mapping is
#: private: ``ExchangeSpec.trading_unit`` is 100 for HSX at every date (wrong
#: before 2021-01-04), ``daily_trading_limit`` is one scalar per exchange for
#: all history and all instrument classes (wrong for warrants, bonds and
#: government-bond futures), and neither carries a citation. Session clock
#: times, by contrast, are unchanged across the whole window on every venue --
#: the KRX delta table lists session times as explicitly NOT a delta -- so
#: reading them here duplicates nothing and drifts from nothing.
_SPEC_BY_VENUE: Mapping[Venue, ExchangeSpec] = {
    Venue.HSX: HSX,
    Venue.HNX: HNX,
    Venue.UPCOM: UPCOM,
    Venue.HNXDS: DS,
}

#: The ``exchanges/`` object that judges each venue's orders.
_EXCHANGE_BY_VENUE: Mapping[Venue, Exchange] = {
    Venue.HSX: HSX_EXCHANGE,
    Venue.HNX: HNX_EXCHANGE,
    Venue.UPCOM: UPCOM_EXCHANGE,
    Venue.HNXDS: HNXDS_EXCHANGE,
}

#: Vietnam's wall clock. ``AbstractTradingSession.is_current`` compares
#: ``given_datetime.time()`` and ignores ``tzinfo`` entirely, so an aware
#: timestamp in any other zone would silently resolve to the wrong phase.
#: :meth:`RuleSet.phase` converts first.
_ICT = timezone(timedelta(hours=7))


# --------------------------------------------------------------------------
# Order types: the mnemonic is the datum, the OrderType is a view of it
# --------------------------------------------------------------------------

#: Vietnamese order-type mnemonic to :class:`plutus.core.order.OrderType`.
#:
#: Two mnemonics that the existing enum cannot express, and both matter:
#:
#: * **MP and MTL are one type under two names.** HOSE quoted the market order
#:   as ``MP`` to 2025-05-04 and as ``MTL`` from 2025-05-05, and the rulebook is
#:   explicit that this is "same economics, new mnemonic" -- both walk the book
#:   and convert the residue to a limit order one tick beyond the last match,
#:   capped at the band, cancelled at entry with no opposite limit order. So
#:   both map to ``MARKET_WITH_LEFTOVER_AS_LIMIT``, and the KRX change is
#:   visible in :meth:`RuleSet.legal_order_mnemonics` rather than in the
#:   ``OrderType`` set. Reporting the *set* as changing would fabricate a
#:   semantic change out of a rename.
#: * **PLO has no ``OrderType`` member at all.** HNX's post-close order -- a
#:   limit order without a price, executing at the day's last round-lot match --
#:   is simply not in ``core/order.py``. It maps to ``None`` here, which is why
#:   the mnemonic set and not the ``OrderType`` set is the primary datum: an
#:   ``OrderType``-only table would silently report HNX's post-close session as
#:   accepting nothing, which is not what the venue does.
#:
#: ``MKT`` is deliberately absent. ``OrderType.MARKET`` ("sell at floor or buy
#: at ceiling for guaranteed match") matches no Vietnamese order type at any
#: date -- a flat negative finding across all four rulebooks -- so no mnemonic
#: maps to it and no venue-date-phase triple below can contain it.
_ORDER_TYPE_BY_MNEMONIC: Mapping[str, Optional[OrderType]] = {
    'LO': OrderType.LIMIT,
    'ATO': OrderType.AT_THE_OPENING,
    'ATC': OrderType.AT_THE_CLOSE,
    'MP': OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
    'MTL': OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
    'MOK': OrderType.MARKET_FILL_OR_KILL,
    'MAK': OrderType.MARKET_IMMEDIATE_OR_CANCEL,
    'PLO': None,
}


def _types_of(mnemonics: Iterable[str]) -> FrozenSet[OrderType]:
    """The ``OrderType`` view of a mnemonic set, dropping what it cannot say."""
    return frozenset(
        t for t in (_ORDER_TYPE_BY_MNEMONIC[m] for m in mnemonics)
        if t is not None
    )


#: Futures product families, because band, tick, multiplier and position limit
#: are keyed to the CONTRACT TEMPLATE and never to the exchange.
#:
#: VN30F and VN100F quote index points on a 100,000d multiplier with a +/-7%
#: band and a 0.1-point tick. GB05 and GB10 quote VND on a 100,000d face with a
#: +/-3% band and a 1 VND tick, and bar individual investors outright. With
#: ``CURRENCY_UNIT['HNXDS'] = 1`` both collapse to the same nominal unit while
#: their ticks differ tenfold and their bands by 2.3x, which is precisely the
#: confusion a venue-keyed lookup produces.
_FUTURES_INDEX_PREFIXES = ('VN30F', 'VN100F')
_FUTURES_BOND_PREFIXES = ('GB05', 'GB10')


def _futures_family(ticker: Optional[str]) -> Optional[str]:
    """``'INDEX'``, ``'GB'``, or None when the contract cannot be classified."""
    if not ticker:
        return None
    upper = ticker.upper()
    if upper.startswith(_FUTURES_INDEX_PREFIXES):
        return 'INDEX'
    if upper.startswith(_FUTURES_BOND_PREFIXES):
        return 'GB'
    return None
