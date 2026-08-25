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

from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timedelta, timezone
from datetime import time as _time
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
        super().__init__(
            f'{resolution} is {resolution.status.value}: {reason}')


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


# --------------------------------------------------------------------------
# The dated tables
# --------------------------------------------------------------------------
#
# Every table below is keyed ``(RuleName) -> {key tuple: (RuleInterval, ...)}``.
# A ``None`` in a key position is a wildcard, so a rule that does not vary on
# an axis is written once. :func:`_candidate_keys` tries the most specific key
# first, which is what lets "HNXDS index futures" override "HNXDS" without a
# second lookup path.
#
# The tables are module-level constants and are *data*, not configuration:
# nothing here is chosen at load, and nothing here is per-run. What a run
# chooses is which rulebook id to build and which pins to apply.

_D = Decimal


def _trading_unit_table() -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
    """Round lot, delegating the dated values to ``get_trading_unit``.

    The *value* stored is the marker ``'get_trading_unit'`` rather than a
    number: ``core.constant.get_trading_unit(code, on)`` already carries the
    HOSE 10 -> 100 step at 2021-01-04 and is the codebase's single source for
    it. Copying the number here would create the second table that
    ``constant.py``'s own docstring warns about (it already carries one pair of
    tick tables that can drift). What this table adds is the citation, the
    confidence grade, and the ``NOT_APPLICABLE`` row for indices -- none of
    which the function can carry.
    """
    delegate = 'get_trading_unit'
    rows: Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]] = {}
    for venue in (Venue.HSX, Venue.HNX, Venue.UPCOM, Venue.HNXDS):
        rows[(venue, None)] = (
            _interval(
                delegate, date(2020, 1, 1),
                document='QD 894/QD-SGDHCM (2020-12-30, applied 2021-01-04); '
                         'QD 352/QD-SGDHCM Dieu 8.1; VNX QD 17 Phu luc III; '
                         'HNX contract templates (HNXDS, 1 contract)',
                confidence=Confidence.HIGH,
                note='Values delegated to core.constant.get_trading_unit, '
                     'which carries the HOSE 10 -> 100 step at 2021-01-04. '
                     'The 2020 HOSE lot of 10 is medium-confidence (QD 67 was '
                     'never read) but is corroborated by 94,675 HSX stock '
                     'closes in the 10-lot window.',
            ),
        )
    # An index is quoted, not traded. Saying so is a sourced answer, not a gap.
    rows[(None, InstrumentKind.INDEX)] = (
        _interval(None, date(2020, 1, 1), document='not a tradeable instrument',
                  confidence=Confidence.HIGH, status=RuleStatus.NOT_APPLICABLE,
                  note='An index has no round lot because it cannot be traded; '
                       'the future on it can, and is a separate instrument.'),
    )
    return rows


def _daily_trading_limit_table() -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
    """The ORDINARY band, by venue and product family.

    Widened bands -- first listing 20/30/40%, post-suspension resumption,
    UPCoM's 25-session illiquidity 40%, the four corporate-action cases -- turn
    on a *security state* axis (days since last trade, ex-rights flags,
    suspension history) that Tier 1 does not carry. They are a separate rule,
    :attr:`RuleName.WIDENED_TRADING_LIMIT`, tabulated below so that wiring the
    state axis later is data plus one branch, not a redesign. Until then this
    accessor returns the ordinary band and the limitation is declared: the
    UPCoM 40% case alone covers 70,578 of 412,041 UPCoM name-days (17.1%), so
    it is not a corner case.
    """
    hose = 'QD 352/QD-SGDHCM Dieu 9.6 -> VNX QD 17 Phu luc III S1.3'
    return {
        # Corpus-confirmed on 151,005 HOSE stock name-days: monthly median
        # implied ceiling band 0.0690-0.0692, i.e. 7% rounded down to tick.
        (Venue.HSX, None): (
            _interval(_D('0.07'), date(2020, 1, 1), date(2021, 7, 5),
                      document='QD 67/QD-SGDHCM as amended by QD 462 and QD 894',
                      confidence=Confidence.LOW,
                      note='The band instrument itself was amended one day into '
                           'the window and has never been read; the corpus '
                           'starts 2021-02-05, so the first 13 months have '
                           'neither text nor data.'),
            _interval(_D('0.07'), date(2021, 7, 5), document=hose,
                      article='Dieu 9.6', confidence=Confidence.HIGH),
        ),
        (Venue.HNX, None): (
            _interval(_D('0.10'), date(2020, 1, 1), date(2022, 3, 31),
                      document='HNX QD 653/QD-SGDHN (2018-10-12)',
                      confidence=Confidence.LOW,
                      note='Text never retrieved; the saved fetch is a '
                           'Cloudflare interstitial. Corroborated only by the '
                           'corpus fit.'),
            _interval(_D('0.10'), date(2022, 3, 31),
                      document='VNX QD 17 Phu luc III S2.3; QD 22/2026 S2.3',
                      confidence=Confidence.HIGH,
                      note='Corpus-confirmed: 144,521 of 146,102 HNX stock '
                           'name-days reproduce exactly (98.99%).'),
        ),
        (Venue.UPCOM, None): (
            _interval(_D('0.15'), date(2020, 1, 1), date(2022, 11, 16),
                      document='HNX QD 455/QD-SGDHN (2017-06-20)',
                      confidence=Confidence.LOW,
                      note='Text never retrieved.'),
            _interval(_D('0.15'), date(2022, 11, 16),
                      document='VNX QD 34 Dieu 18.1; QD 23/2026 Dieu 19.1',
                      confidence=Confidence.HIGH,
                      note='Corpus-confirmed: 301,732 of 412,041 UPCoM '
                           'name-days fit +/-15% exactly. The residue is very '
                           'largely the 40% illiquidity band, which this row '
                           'does not model.'),
        ),
        # Keyed to the CONTRACT TEMPLATE, never to the exchange -- the two
        # HNXDS product families differ by 2.3x here.
        (Venue.HNXDS, 'INDEX'): (
            _interval(_D('0.07'), date(2020, 1, 1),
                      document='HNX Mau HDTL Chi so VN30 / VN100',
                      confidence=Confidence.HIGH,
                      note='Corpus-confirmed on 1,872 VN30F contract-days: '
                           'implied ceiling band quantiles 0.06991-0.07000. '
                           'VNX QD 20/21 Dieu 15 carries no number -- it '
                           'delegates to the template.'),
        ),
        (Venue.HNXDS, 'GB'): (
            _interval(_D('0.03'), date(2020, 1, 1),
                      document='HNX Mau HDTL TPCP 05 nam / 10 nam',
                      confidence=Confidence.HIGH,
                      note='+/-3%, NOT +/-7%. Notional 100,000d face; a band '
                           'keyed to the exchange rather than the contract '
                           'gets this wrong by more than a factor of two.'),
        ),
        # An unclassified HNXDS contract must not inherit the index band.
        (Venue.HNXDS, None): (
            _unsourced(date(2020, 1, 1),
                       note='Band is a contract-template value on HNXDS. '
                            'Without a contract code the product family is '
                            'unknown, and the index (7%) and government-bond '
                            '(3%) bands differ by 2.3x.'),
        ),
        # Bonds carry no band at all: a sourced answer, not a gap.
        (None, 'BOND'): (
            _interval(None, date(2020, 1, 1),
                      document='QD 352 Dieu 9.1; VNX QD 17 Dieu 35.2',
                      confidence=Confidence.HIGH,
                      status=RuleStatus.NOT_APPLICABLE,
                      note='"Khong quy dinh gioi han dao dong gia doi voi giao '
                           'dich trai phieu niem yet."'),
        ),
        # A covered warrant HAS a band, but not a percentage one.
        (Venue.HSX, InstrumentKind.WARRANT): (
            _unsourced(date(2020, 1, 1),
                       document='QD 352 Dieu 9.3; QD 17 Dieu 31.2(b)',
                       confidence=Confidence.HIGH,
                       note='A covered warrant has NO percentage band. Its '
                            'limits are derived from the underlying and the '
                            'conversion ratio: ceiling_CW = ref_CW + '
                            '(ceiling_und - ref_und) / CR, floor likewise, '
                            'with the floor clamped at the 10d quotation unit '
                            'rather than at the reference. Applying 7% of the '
                            "warrant's own price is wrong in both directions "
                            'and badly wrong for cheap warrants; the '
                            'floor-at-10d branch alone fires on 16,275 of '
                            '46,090 warrant name-days.'),
        ),
    }


def _widened_trading_limit_table() -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
    """Widened bands, keyed ``(venue, case)``.

    Tabulated but not wired: :meth:`RuleSet.widened_trading_limit` resolves
    them, and nothing in Tier 1 decides *which* case applies, because that
    needs a security-state axis. Shipping the values now is what makes wiring
    the axis data entry later.
    """
    return {
        (Venue.HSX, 'first_trading_day'): (
            _interval(_D('0.20'), date(2021, 7, 5),
                      document='QD 352 Dieu 11.1(b); VNX QD 17 Dieu 31.6(a); '
                               'QD 22/2025 Dieu 29.3(a)',
                      confidence=Confidence.HIGH,
                      note='One day only to 2025-05-04; from 2025-05-05 the '
                           'trigger becomes durative -- it holds until a '
                           'round-lot matched price exists.'),
        ),
        (Venue.HNX, 'first_trading_day'): (
            _interval(_D('0.30'), date(2022, 3, 31),
                      document='VNX QD 17 Phu luc III S2.4',
                      confidence=Confidence.HIGH),
        ),
        (Venue.UPCOM, 'first_trading_day'): (
            _interval(_D('0.40'), date(2022, 11, 16),
                      document='VNX QD 34 Dieu 18.2(a)',
                      confidence=Confidence.HIGH),
        ),
        (Venue.HSX, 'resumption'): (
            _interval(_D('0.20'), date(2021, 7, 5),
                      document='QD 352 Dieu 9.7(b), Dieu 12; QD 22/2025 Dieu 29.3(b)',
                      confidence=Confidence.HIGH,
                      note='Threshold is >25 trading days to 2025-05-04 and '
                           '>=25 from 2025-05-05.'),
        ),
        (Venue.HNX, 'resumption'): (
            _interval(_D('0.30'), date(2022, 3, 31),
                      document='VNX QD 17 Phu luc III S2.4',
                      confidence=Confidence.HIGH),
        ),
        # The single largest widened-band population in the corpus.
        (Venue.UPCOM, 'illiquidity'): (
            _interval(_D('0.40'), date(2022, 11, 16),
                      document='VNX QD 34 Dieu 18.2(b); QD 23/2026 Dieu 19.2(b)',
                      confidence=Confidence.HIGH,
                      note='Trigger is illiquidity, not suspension: no trade '
                           'for more than 25 consecutive sessions. 70,578 of '
                           '412,041 UPCoM name-days (17.1%) carry it, and the '
                           'corpus separation is total -- every 40% row last '
                           'traded at least 26 sessions earlier, with no '
                           'counterexample. UPCoM only: 108 of 136 HOSE and '
                           '4,042 of 4,069 HNX name-days past the same '
                           'threshold kept their ordinary band.'),
        ),
        (Venue.HSX, 'convertible_bond_ex_rights'): (
            _unsourced(date(2022, 3, 31),
                       document='QD 17 Dieu 31.6(e) names the case; the HOSE '
                                'appendix omits it in all three instruments',
                       confidence=Confidence.LOW,
                       note='The case exists and the value has never been '
                            'gazetted. The +/-20% figure that circulates for '
                            'it appears in no HOSE appendix, so it is not '
                            'carried here.'),
        ),
    }


#: Marker: the value is computed by ``core.constant.get_hsx_tick_size`` rather
#: than stored, so HOSE's three price tiers exist in exactly one place.
_HSX_BANDED = 'get_hsx_tick_size'

#: A neutral three-character symbol fed to ``get_hsx_tick_size`` when this
#: module has already decided, from the instrument KIND, that the banded grid
#: applies.
#:
#: ``get_hsx_tick_size`` keys its ETF/warrant override on the ticker *string*,
#: but the rulebook is explicit that the flat 10d tick "keys on instrument
#: type, not on the ticker string". This module classifies first and then reuses
#: the function purely for its price-tier table -- which is the part that must
#: not be duplicated (the repo already carries two copies of that table, in
#: ``VietnamMarketConstant.TICK_SIZE`` and inside ``get_hsx_tick_size``, and a
#: third would be the same mistake again).
_HSX_BANDED_PROBE = 'AAA'


def _tick_size_table() -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
    """Tick grid, keyed ``(venue, family, method)``.

    ``method`` is not optional. Put-through is 1d at all four cash venues -- a
    hundredfold finer grid than the matched grid at the same price -- and
    without the axis the ``TICK_GRID`` gate rejects every legitimate
    put-through price.
    """
    matching, put_through = TradingMethod.ORDER_MATCHING, TradingMethod.PUT_THROUGH
    hsx_matched = ('QD 352/QD-SGDHCM Dieu 8.4(a); VNX QD 17 Phu luc III S1.2')
    return {
        # --- HOSE ------------------------------------------------------
        (Venue.HSX, 'BANDED', matching): (
            _interval(_HSX_BANDED, date(2020, 1, 1), date(2021, 7, 5),
                      document='QD 66+67/QD-SGDHCM as amended',
                      confidence=Confidence.MEDIUM,
                      note='Never read; corpus-inferred. Sub-10,000d closes '
                           'are 100.0% multiples of 10 but only 44.66% of 50 '
                           '(n=24,847), which is the three-tier grid.'),
            _interval(_HSX_BANDED, date(2021, 7, 5), document=hsx_matched,
                      article='Dieu 8.4(a)', confidence=Confidence.HIGH,
                      note='Three tiers: <10,000d -> 10d; 10,000-49,950d -> '
                           '50d; >=50,000d -> 100d. The breakpoints are '
                           'inclusive-below, so 10.0 takes 0.05 and 50.0 takes '
                           '0.1. The circulating 500d fourth tier is REJECTED '
                           '(FPTS is wrong; the corpus fits three at 99.997%).'),
        ),
        # Flat, and it keys on instrument type rather than on the code string.
        (Venue.HSX, 'ETF_CW', matching): (
            _interval(_D('0.01'), date(2020, 1, 1), document=hsx_matched,
                      confidence=Confidence.HIGH,
                      note='Flat 10d at every price level for ETF certificates '
                           'and covered warrants. Closed-end funds (FUC*) are '
                           'NOT ETFs and take the banded grid: all 151 FUC* '
                           'close rows are multiples of 50.'),
        ),
        (Venue.HSX, None, put_through): (
            _interval(_D('0.001'), date(2020, 1, 1), document=hsx_matched,
                      article='Dieu 8.4(b)', confidence=Confidence.HIGH,
                      note='1d regardless of instrument and price. Note the '
                           'corpus cannot validate it: quote_close is exactly '
                           'representable at 10d resolution for 100% of '
                           '3,899,486 rows, so a 1d price is unrepresentable.'),
        ),
        # --- HNX -------------------------------------------------------
        (Venue.HNX, 'BANDED', matching): (
            _interval(_D('0.1'), date(2020, 1, 1), date(2022, 3, 31),
                      document='HNX QD 653/QD-SGDHN',
                      confidence=Confidence.MEDIUM, note='Never read.'),
            _interval(_D('0.1'), date(2022, 3, 31),
                      document='VNX QD 17 Phu luc III S2.2',
                      confidence=Confidence.HIGH,
                      note='Flat 100d. Corpus: HNX stock closes are 100.00% '
                           'multiples of 100d (n=231,613).'),
        ),
        # The mirror image of HOSE: on HNX the ETF tick is FINER everywhere.
        (Venue.HNX, 'ETF_CW', matching): (
            _interval(_D('0.001'), date(2022, 3, 31),
                      document='VNX QD 17 Phu luc III S2.2',
                      confidence=Confidence.MEDIUM,
                      note='"Doi voi giao dich chung chi quy ETF la 1 dong." '
                           'No corpus support -- the corpus has no HNX fund '
                           'rows.'),
        ),
        (Venue.HNX, None, put_through): (
            _interval(_D('0.001'), date(2022, 3, 31),
                      document='VNX QD 17 Phu luc III S2.2',
                      confidence=Confidence.MEDIUM,
                      note='No corpus support: put-through prints are not '
                           'separable in quote_close.'),
        ),
        # --- UPCoM -----------------------------------------------------
        (Venue.UPCOM, 'BANDED', matching): (
            _interval(_D('0.1'), date(2020, 1, 1),
                      document='VNX QD 34 Dieu 17; QD 23/2026 Dieu 18',
                      confidence=Confidence.HIGH,
                      note='Corpus: 99.44% multiples of 100d (n=665,877). All '
                           '3,729 exceptions are multiples of 10d and are '
                           'venue-transfer artefacts -- each ticker\'s '
                           'off-grid closes stop exactly at its last HOSE '
                           'session -- which is the (ticker, ts) venue defect '
                           'this module exists to fix, not a tick exception.'),
        ),
        (Venue.UPCOM, None, put_through): (
            _interval(_D('0.001'), date(2022, 11, 16),
                      document='VNX QD 34 Dieu 17.2',
                      confidence=Confidence.MEDIUM,
                      note='An unattributed HNX summary tabulates 100d for '
                           'both methods; the primary text says 1d twice and '
                           'two broker mirrors agree, so 1d is adopted.'),
        ),
        # --- HNXDS -----------------------------------------------------
        (Venue.HNXDS, 'INDEX', matching): (
            _interval(_D('0.1'), date(2020, 1, 1),
                      document='HNX Mau HDTL Chi so VN30 / VN100 rows 4, 5, 10, 11',
                      confidence=Confidence.HIGH,
                      note='0.1 INDEX POINT = 10,000 VND per contract per tick '
                           'at the 100,000d multiplier. Corpus: VN30F closes '
                           'are 100.0% on the 0.1-point grid (n=1,996).'),
        ),
        (Venue.HNXDS, 'GB', matching): (
            _interval(_D('1'), date(2020, 1, 1),
                      document='HNX Mau HDTL TPCP 05 nam / 10 nam',
                      confidence=Confidence.HIGH,
                      note='1 VND on a VND quote, not 1 index point. The same '
                           'numeral as the index tick attached to a different '
                           'unit -- exactly the error a venue-keyed lookup '
                           'makes.'),
        ),
        (Venue.HNXDS, None, matching): (
            _unsourced(date(2020, 1, 1),
                       note='Tick is a contract-template value on HNXDS. '
                            'Without a contract code the product family is '
                            'unknown, and the two families differ tenfold.'),
        ),
        (Venue.HNXDS, None, put_through): (
            _unsourced(date(2020, 1, 1),
                       note='No negotiated tick for HNXDS appears in any '
                            'document read. The cash-venue 1d rule must not be '
                            'assumed to carry across to an index-point quote.'),
        ),
    }


def _legal_order_types_table() -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
    """Legal order MNEMONICS, keyed ``(venue, phase)``.

    Mnemonics rather than ``OrderType`` members, because two of the changes
    this table has to express are invisible in that enum: HOSE's MP -> MTL
    rename at the cutover (same economics), and HNX's PLO (no member exists).
    :meth:`RuleSet.legal_order_types` is the ``OrderType`` view.

    Four facts a naive table gets wrong, each of which this one encodes:

    * **A limit order IS legal in a call auction.** HOSE's own session table
      reads "LO, ATO" and "LO, ATC"; HNX's closing call reads "LO, ATC". What a
      call auction refuses is the market family, whose sweep-the-book semantics
      presuppose a resting book the auction does not have while accumulating.
    * **HNX has no opening auction at all**, so it has no ATO at any date, and
      its continuous session starts at 09:00 rather than 09:15.
    * **UPCoM is LO-only at every date and in every phase.** No market order of
      any kind, no ATO, no ATC, no PLO.
    * **``OrderType.MARKET`` ("MKT") is legal nowhere, ever.** No mnemonic maps
      to it, so no row here can produce it.
    """
    hose_pre = 'QD 352/QD-SGDHCM Dieu 14, 15.4'
    hose_post = 'HOSE "Quy dinh giao dich" (to trinh 51/TTr-HTGD, 2025-04-26) S5.2'
    hnx = 'ASEANSC HNX S2.1, S2.3; SHS 2025; SSI'
    upcom = 'MBS UPCoM 2024-10-14 S4; ASEANSC UPCoM S3'
    ds = 'VNX QD 20 Dieu 22 and QD 21 Dieu 22 (identical lists)'
    none_: FrozenSet[str] = frozenset()

    def phases_off(venue: Venue, *phases: SessionPhase) -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
        """Phases in which a venue does not match at all accept nothing."""
        return {
            (venue, phase): (
                _interval(none_, date(2020, 1, 1),
                          document='venue session structure',
                          confidence=Confidence.HIGH,
                          note=f'{venue.value} does not match in '
                               f'{phase.value}.'),
            )
            for phase in phases
        }

    table: Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]] = {
        # --- HOSE: the dated pair that makes shape 1 visible -------------
        (Venue.HSX, SessionPhase.CONTINUOUS): (
            _interval(frozenset({'LO', 'MP'}), date(2020, 1, 1), KRX_CUTOVER,
                      document=hose_pre, article='Dieu 14, 15.4',
                      confidence=Confidence.HIGH,
                      note='MP is continuous-only; no MTL, MOK or MAK on HOSE '
                           'before the cutover. The 2020 leg is by continuity '
                           'and is low-confidence on its own.'),
            _interval(frozenset({'LO', 'MTL'}), KRX_CUTOVER,
                      document=hose_post, confidence=Confidence.MEDIUM,
                      note='MP withdrawn, MTL introduced -- same economics, '
                           'new mnemonic. MOK/MAK were NOT introduced on HOSE; '
                           'that negative is the weakest link here (SSI '
                           'post-KRX rules page, low confidence). Note VNX QD '
                           '22 still DEFINES MP: the withdrawal is at the '
                           "level of HOSE's applicable-type list in Phu luc "
                           'III, which is unobtained.'),
        ),
        (Venue.HSX, SessionPhase.OPENING_AUCTION): (
            _interval(frozenset({'LO', 'ATO'}), date(2020, 1, 1),
                      document=hose_pre + '; HOSE session table',
                      confidence=Confidence.HIGH),
        ),
        (Venue.HSX, SessionPhase.CLOSING_AUCTION): (
            _interval(frozenset({'LO', 'ATC'}), date(2020, 1, 1),
                      document=hose_pre + '; HOSE session table',
                      confidence=Confidence.HIGH),
        ),
        # --- HNX --------------------------------------------------------
        (Venue.HNX, SessionPhase.CONTINUOUS): (
            _interval(frozenset({'LO', 'MTL', 'MOK', 'MAK'}), date(2020, 1, 1),
                      document=hnx, confidence=Confidence.HIGH,
                      note='No plain MP on HNX at any date.'),
        ),
        (Venue.HNX, SessionPhase.CLOSING_AUCTION): (
            _interval(frozenset({'LO', 'ATC'}), date(2020, 1, 1),
                      document=hnx, confidence=Confidence.HIGH),
        ),
        (Venue.HNX, SessionPhase.POST_CLOSE_PLO): (
            _interval(frozenset({'PLO'}), date(2020, 1, 1),
                      document=hnx, confidence=Confidence.HIGH,
                      note='PLO is a limit order without a price, executing at '
                           "the day's last ROUND-LOT matched price; if no "
                           'round-lot price was established that day, PLO '
                           'orders are not accepted at all. It has no '
                           'OrderType member, so legal_order_types() reports '
                           'an empty set here while the mnemonic set does not.'),
        ),
        # --- UPCoM: one row, every phase, every date ---------------------
        (Venue.UPCOM, None): (
            _interval(frozenset({'LO'}), date(2020, 1, 1),
                      document=upcom, confidence=Confidence.HIGH,
                      note='LO ONLY. No market order of any kind, no ATO, no '
                           'ATC, no PLO, across the whole window. An MTL on '
                           'UPCoM is refused.'),
        ),
        # --- HNXDS: explicitly unchanged across the cutover --------------
        (Venue.HNXDS, SessionPhase.CONTINUOUS): (
            _interval(frozenset({'LO', 'MTL', 'MOK', 'MAK'}), date(2020, 1, 1),
                      document=ds, confidence=Confidence.HIGH),
        ),
        (Venue.HNXDS, SessionPhase.OPENING_AUCTION): (
            _interval(frozenset({'LO', 'ATO'}), date(2020, 1, 1),
                      document=ds, confidence=Confidence.HIGH),
        ),
        (Venue.HNXDS, SessionPhase.CLOSING_AUCTION): (
            _interval(frozenset({'LO', 'ATC'}), date(2020, 1, 1),
                      document=ds, confidence=Confidence.HIGH),
        ),
    }
    # Phases in which each venue is not matching. Explicit rows rather than a
    # fall-through, so "the venue accepts nothing here" is a sourced answer and
    # not an accident of table coverage.
    dark = (SessionPhase.PRE_OPEN, SessionPhase.NOON_BREAK,
            SessionPhase.POST_CLOSE)
    for venue in (Venue.HSX, Venue.HNX, Venue.HNXDS):
        table.update(phases_off(venue, *dark))
    table.update(phases_off(Venue.HSX, SessionPhase.POST_CLOSE_PLO))
    table.update(phases_off(Venue.HNX, SessionPhase.OPENING_AUCTION))
    table.update(phases_off(Venue.HNXDS, SessionPhase.POST_CLOSE_PLO))
    # UPCoM has no auction and no post-close session of any kind, so the
    # LO-only wildcard above is left to cover CONTINUOUS and these rows say
    # what it does not run. The interface contract phrases UPCoM's test as
    # "{LO} at every date and phase"; the stricter reading here keeps the
    # binding claim -- nothing but LO is ever legal on UPCoM -- while not
    # asserting that UPCoM accepts orders in a phase it does not have.
    table.update(phases_off(
        Venue.UPCOM, *dark, SessionPhase.OPENING_AUCTION,
        SessionPhase.CLOSING_AUCTION, SessionPhase.POST_CLOSE_PLO))
    # An unsupplied phase is not a phase in which nothing is legal -- it is a
    # phase nobody has told us. One wildcard row, at every venue and every
    # date, because the instrument/phase axis outranks the venue axis in the
    # tie-break and this must beat UPCoM's LO-only wildcard above.
    # `equity.py` already treats an UNKNOWN phase as INDETERMINATE rather than
    # as a rejection; this keeps the rulebook saying the same thing.
    table[(None, SessionPhase.UNKNOWN)] = (
        _unsourced(date(2020, 1, 1),
                   document='the adapter did not supply a session phase',
                   note='Order-type legality is phase-dependent at every '
                        'venue, so it cannot be resolved without one. '
                        'protocol.SessionPhase is set by the adapter and never '
                        'inferred from a timestamp -- a daily bar is stamped '
                        'midnight, and inferring would mark every bar '
                        'pre-open.'),
    )
    return table


def _settlement_table() -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
    """T+N and the delivery instant, keyed ``(kind,)``.

    **The cycle has been T+2 since 2016-01-01, not since 2022-08-29.** What
    changed on 2022-08-29 was the TIME OF DAY. The design spec's
    "T+3 to 2022-08-26, T+2 from 2022-08-29" is right about the *behaviour* --
    the first sellable session -- and wrong about the cycle length, and
    conflating the two makes the 2016 boundary invisible. So
    :class:`SettlementRule` carries ``cycle_days`` and ``delivery_time``
    separately, and the pre-2022 regime is expressed as
    ``delivery_on_next_session_open`` rather than as an after-close time:
    encoding it as 16:00 on T+2 would make a T+2 afternoon sale look legal,
    which is the rejection the Tier 1 demo turns on.

    Note also the two distinct instants inside the current regime. Depository
    settlement runs 11:00-11:30 on T+2; the 13:00 figure is the *custodian
    member's allocation deadline to the client*. 13:00 is the one that governs
    what a client can do, so it is the one modelled -- and it is a regulatory
    backstop, not a guarantee: allocation has been observed ~2 hours late
    (2026-02-27).

    Never call this regime "T+1.5". The term appears in retail press and broker
    marketing and in no gazetted document, checked against Decision 109/QD-VSD
    and Circulars 119 and 120/2020/TT-BTC.
    """
    d109 = ('VSD Decision 109/QD-VSD (signed 2022-08-19, effective 2022-08-29) '
            'Art. 4')
    d211 = ('VSD Decision 211/QD-VSD (2015-12-18, T+2 from 2016-01-01), '
            "confirmed from Decision 109's own preamble")
    pre = SettlementRule(
        cycle_days=2, delivery_time=_TIME_0900,
        delivery_on_next_session_open=True,
        citation=RuleCitation(document=d211, effective_from=date(2016, 1, 1),
                              confidence=Confidence.HIGH,
                              effective_to=date(2022, 8, 26),
                              note='Settlement completed 15:30-16:00 on T+2, '
                                   'after the close, so the first sellable '
                                   'session was the open of T+3.'))
    post = SettlementRule(
        cycle_days=2, delivery_time=_TIME_1300,
        delivery_on_next_session_open=False,
        citation=RuleCitation(document=d109, effective_from=date(2022, 8, 29),
                              confidence=Confidence.HIGH, article='Art. 4',
                              note='"Cham nhat 13h00" is the custodian '
                                   "member's allocation deadline, not the "
                                   'VSDC settlement moment (11:00-11:30).'))
    equity_kinds = (InstrumentKind.STOCK, InstrumentKind.FUND,
                    InstrumentKind.WARRANT)
    table: Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]] = {}
    for kind in equity_kinds:
        table[(kind,)] = (
            _interval(pre, date(2016, 1, 1), date(2022, 8, 29),
                      document=d211, confidence=Confidence.HIGH),
            _interval(post, date(2022, 8, 29), document=d109, article='Art. 4',
                      confidence=Confidence.HIGH,
                      note='KRX did NOT change this: T+2 and the 13:00 '
                           'deadline both survive the cutover. Launch '
                           'journalism repeatedly asserted T+0/T+1; it did not '
                           'happen. The timetable is verbatim only to '
                           '2024-11-01 -- VSDC Decisions 48/QD-HDTV and '
                           '39/QD-HDTV were never read -- so the tail of this '
                           'interval is continuity plus behavioural evidence.'),
        )
    table[(InstrumentKind.FUTURE,)] = (
        _interval(
            SettlementRule(
                cycle_days=1, delivery_time=_TIME_0900,
                delivery_on_next_session_open=True,
                citation=RuleCitation(
                    document='VSDC "Bu tru va Thanh toan"',
                    effective_from=date(2020, 1, 1),
                    confidence=Confidence.HIGH,
                    note='This is the DAILY VARIATION MARGIN settling T+1, '
                         'not the contract cash-settling T+1. The distinction '
                         'matters because it is exactly what the margin model '
                         'computes: daily P&L leaves or enters the deposit as '
                         'cash on T+1, so the deposit does not accumulate '
                         'mark-to-market.')),
            date(2020, 1, 1),
            document='VSDC "Bu tru va Thanh toan"', confidence=Confidence.HIGH),
    )
    table[(InstrumentKind.INDEX,)] = (
        _interval(None, date(2020, 1, 1), document='not a tradeable instrument',
                  confidence=Confidence.HIGH, status=RuleStatus.NOT_APPLICABLE,
                  note='An index does not settle; the future on it does.'),
    )
    return table


def _margin_table() -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
    """Initial-margin rate and the margin MODEL, keyed ``(contract family,)``.

    The rate delegates to :func:`plutus.market.margin.vsd_initial_margin`,
    which already carries the dated 10 / 13 / 17% series; re-implementing it
    here would create a second copy that can drift from the one the
    derivatives tax base reads, and the rulebook is explicit that both must
    read the same series.

    The *model* is a separate rule because the cutover changed the shape and
    not the number. Pre-KRX, margin was lodged with VSDC before an order could
    be placed and recomputed against live prices intraday. Post-KRX, margin
    sits at the clearing member and VSDC computes the requirement after the
    close from end-of-day open positions using the KRX COMS formula. That
    formula could not be obtained, and Pinetree explicitly confirms no initial
    margin *percentage* is published post-KRX -- so the post-cutover row is
    ``UNKNOWN`` rather than an extension of the pre-KRX shape. This is the
    demonstrator for the design's requirement that an unsourced post-KRX value
    say so rather than silently returning the pre-KRX one.
    """
    delegate = 'vsd_initial_margin'
    return {
        (RuleName.INITIAL_MARGIN_RATE, 'INDEX'): (
            _interval(delegate, date(2017, 8, 10),
                      document='VSD notices (thong bao) under a standing '
                               'delegation in the clearing rulebook; VSDC '
                               'PHU LUC 4 effective 2026-08-21',
                      confidence=Confidence.HIGH,
                      note='10% from 2017-08-10, 13% from 2018-07-18, 17% from '
                           '2022-12-15, and 0.17 verified still in force at '
                           '2026-08-21. NO quyet dinh number exists for any '
                           'step -- citing one would cite a document that does '
                           'not exist. 17.5% matches no source at any date and '
                           'is a transcription slip for 0.17. VSDC publishes '
                           'PER CONTRACT and names time-to-maturity as an '
                           'input, so the correct key is (contract_code, date) '
                           'even though every observed entry is equal.'),
        ),
        (RuleName.INITIAL_MARGIN_RATE, 'GB'): (
            _unsourced(date(2020, 1, 1),
                       document='VSDC margin appendix records the index-future '
                                'delivery-margin column as "-"',
                       confidence=Confidence.LOW,
                       note='Government-bond futures carry a DELIVERY margin '
                            'ratio from E+1 to E+3 that replaces initial '
                            'margin, and its value is not published. The '
                            'index-future series must not be applied to them.'),
        ),
        (RuleName.MARGIN_MODEL,): (
            _interval('pre_margin', date(2017, 5, 1), KRX_CUTOVER,
                      document='VSDC "Thong tin ve ky quy" S II, S IV',
                      confidence=Confidence.HIGH,
                      note='Margin lodged with VSDC BEFORE an order could be '
                           'placed, recomputed against live prices in-session. '
                           'MR = IM + VM over the ACCOUNT PORTFOLIO; VM counts '
                           'only when the account is in loss; the test is '
                           'utilisation = MR / valid margin assets against '
                           '0.80 / 0.90 / 1.00. Vietnam publishes NO '
                           'maintenance margin ratio at any date.'),
            _unsourced(KRX_CUTOVER,
                       document='VSDC QD 26/QD-HDTV (2025-04-16) -- never read; '
                                'the COMS formula could not be obtained',
                       confidence=Confidence.MEDIUM,
                       note='POST-KRX VALUE NOT SOURCED. The shape changed: '
                            'margin is held at the clearing member, the '
                            'investor trades immediately, and VSDC computes '
                            'the requirement after the close (~17:00) from '
                            'END-OF-DAY open positions by the KRX COMS '
                            'formula, topped up by 09:30 the next business '
                            'day. A flat-fraction model may have no post-KRX '
                            'counterpart at all, so the pre-KRX row is '
                            'deliberately not extended across the cutover.'),
        ),
    }


def _position_limit_table() -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
    """Net position cap, keyed ``(contract family, investor class)``.

    The statutory definition is a maximum **net** position in that derivative,
    or in it together with other derivatives on the same underlying, held at
    any one time -- so it is a ledger-level test, which is why the
    ``ContractLedger`` is net-signed.

    Every index-future value here is LOW confidence and the reason is worth
    carrying: the 5,000 / 10,000 / 20,000 triple appears in the 2017 launch
    announcement and in 2025/2026 broker documentation, HNX's current template
    stopped printing a number at all ("Theo quy dinh cua VSDC"), and no VSDC
    notice republishing or revising the limits at any dated point inside
    2020-2026 was located. That a limit exists is high-confidence; the numbers
    are not.

    Zero means *not permitted*, which is a real value and not an absence:
    individuals may not hold government-bond futures at all.
    """
    idx = ('VSD announcement reported 2017-05-29; stale broker reproductions. '
           'HNX template now delegates to VSDC and prints no number.')
    gb = 'HNX published GB futures contract specifications'
    rows: Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]] = {}
    for cls_, cap in ((InvestorClass.INDIVIDUAL, 5000),
                      (InvestorClass.INSTITUTION, 10000),
                      (InvestorClass.PROFESSIONAL, 20000)):
        rows[('INDEX', cls_)] = (
            _interval(cap, date(2017, 8, 10), document=idx,
                      confidence=Confidence.LOW,
                      note='Binds PER ACCOUNT, not per person across the '
                           'market: an investor may hold one derivatives '
                           'account per securities company but accounts at '
                           'several companies.'),
        )
    rows[('GB', InvestorClass.INDIVIDUAL)] = (
        _interval(0, date(2019, 7, 4), document=gb, confidence=Confidence.HIGH,
                  note='Individuals are not permitted to hold government-bond '
                       'futures at all. Zero is the value, not an absence.'),
    )
    rows[('GB', InvestorClass.INSTITUTION)] = (
        _interval(5000, date(2019, 7, 4), document=gb,
                  confidence=Confidence.HIGH),
    )
    rows[('GB', InvestorClass.PROFESSIONAL)] = (
        _interval(10000, date(2019, 7, 4), document=gb,
                  confidence=Confidence.HIGH,
                  note='This is the professional-INSTITUTION tier. GB10 also '
                       'publishes a professional-INDIVIDUAL tier of 3,000, '
                       'which InvestorClass cannot express -- it has one '
                       'PROFESSIONAL member, not a professional x '
                       'individual/institution cross. Reporting 10,000 for a '
                       'professional individual over-permits by 7,000 '
                       'contracts; the axis needs adding before any GB10 '
                       'result is published.'),
    )
    return rows


def _max_order_size_table() -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
    """Per-order quantity cap, keyed ``(venue,)``.

    Included because nothing in the repository enforces one today -- a
    10,000,000-share HOSE order is currently admitted -- and because the two
    venues where it is genuinely unpublished are a clean second demonstration
    of ``UNKNOWN`` as data: "no cap" is an inference, not a sourced rule, and
    the 999,900-share figure that circulates for HNX was neither confirmed nor
    refuted.
    """
    return {
        (Venue.HSX,): (
            _unsourced(date(2020, 1, 1), date(2021, 1, 4),
                       note='Maximum order size for the 10-lot HOSE regime is '
                            'UNVERIFIED.'),
            _interval(500_000, date(2021, 1, 4),
                      document='QD 894/QD-SGDHCM; QD 352 Dieu 8.1; '
                               'QD 17 Phu luc III S1.1',
                      confidence=Confidence.HIGH,
                      note='500,000 units per round-lot matching order. Odd-lot '
                           'orders are capped at 99 by the odd-lot definition '
                           'itself.'),
        ),
        (Venue.HNX,): (
            _unsourced(date(2020, 1, 1),
                       note='None published in any HNX rulebook read. "No cap" '
                            "is an inference from HOSE's clause being "
                            'HOSE-specific, not a sourced rule.'),
        ),
        (Venue.UPCOM,): (
            _unsourced(date(2020, 1, 1),
                       note='None published in any UPCoM rulebook read.'),
        ),
        (Venue.HNXDS,): (
            _interval(500, date(2020, 1, 1),
                      document='HNX contract templates for VN30F, VN100F, '
                               'GB05, GB10 (rows 11, 14); VNX QD 20/21 Dieu 17 '
                               'delegates the limit to the template',
                      confidence=Confidence.HIGH,
                      note='500 CONTRACTS per order, on every listed futures '
                           'contract, unchanged across both template editions.'),
        ),
    }


#: The custodian member's client-allocation deadline on T+2, from 2022-08-29.
#: A regulatory backstop rather than a guarantee -- allocation has been
#: observed ~2 hours late (2026-02-27, KRX-contractor maintenance).
_TIME_1300 = _time(13, 0)

#: The open of the next session, used to express "sellable at the T+3 open"
#: under the pre-2022 regime. It is paired with
#: ``delivery_on_next_session_open=True``, which is what actually governs; the
#: time is carried so the field is never ``None`` and so a calendar that wants
#: an instant has one. 09:00 is the earliest open across the cash venues (HNX
#: and UPCoM); HOSE's own continuous session begins at 09:15 but its opening
#: auction begins at 09:00, and delivery precedes both.
_TIME_0900 = _time(9, 0)


def _charge_table() -> Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]:
    """State, exchange and VSD charge rows, keyed ``(charge_id,)``.

    Charges are modelled because they move cash and therefore change admission
    outcomes: the buy encumbrance includes estimated charges, and the 0.1%
    personal income tax is sell-side only and withheld at source, so a sale
    credits cash **net** -- without it every sale is wrong by more than most
    commissions.

    Broker rows are refused here by construction (:meth:`RuleSet.charges`
    raises on one). Commission, the sale-advance rate and the utilisation
    ladder are commercial terms that differ by firm and change at will; putting
    them in a dated rulebook would destroy the traceability claim that is the
    rulebook's whole point.

    Two rows the shape had to be widened for, both from the source material
    rather than from taste: the VSD derivatives position-management fee accrued
    **per open contract per day**, which no per-trade constant can express, and
    custody is **monthly per security**.

    Rounding is UNVERIFIED for every charge below. No source states a rule for
    any fee or tax amount, so rounding to whole dong is a modelling choice and
    must be reported as one.
    """
    tt127 = 'Thong tu 127/2018/TT-BTC; QD 1541/QD-BTC (2025-04-29, re-issued unchanged)'
    vsdc = 'VSDC price schedule (TT 127/2018 as amended; QD 1541/QD-BTC)'
    cash_classes = frozenset({ChargeClass.EQUITY, ChargeClass.WARRANT,
                              ChargeClass.ETF})

    def rule(**kw) -> ChargeRule:
        return ChargeRule(**kw)

    return {
        # --- state -----------------------------------------------------
        ('pit_securities_transfer',): (
            _interval(
                rule(charge_id='pit_securities_transfer',
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.SELL,
                     levied_by=LeviedBy.STATE, debited_at=DebitedAt.FILL,
                     pool=Pool.SECURITIES, applies_to=cash_classes,
                     rate=_D('0.001')),
                date(2015, 1, 1),
                document='Personal income tax on securities transfer, withheld '
                         'at source by the broker',
                confidence=Confidence.HIGH,
                note='SELL SIDE ONLY, and withheld at source, so a sale '
                     'credits cash net of it. Applies to put-through sales '
                     'too. This single row is worth more than most commission '
                     'models.'),
        ),
        ('pit_derivatives_transfer',): (
            _interval(
                rule(charge_id='pit_derivatives_transfer',
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.STATE, debited_at=DebitedAt.FILL,
                     pool=Pool.DERIVATIVES,
                     applies_to=frozenset({ChargeClass.FUTURE}),
                     venue=Venue.HNXDS, rate=None),
                date(2017, 8, 10),
                document='PIT on derivatives transfer, withheld at source',
                confidence=Confidence.MEDIUM,
                note='The published base is settlement_price x multiplier x '
                     'contracts x IM_ratio / 2 at 0.001, which is LINEAR IN '
                     'THE VSD INITIAL MARGIN RATIO. Expressed against '
                     'TRADE_VALUE the effective rate is therefore '
                     '0.0005 x IM_ratio and is DATED: 0.000065 while the ratio '
                     'was 0.13, 0.000085 from 2022-12-15. RuleSet.charges '
                     'fills the rate in at the resolved instant from the same '
                     'series margin.py reads, because the rulebook requires '
                     'the two to agree.'),
        ),
        # --- exchange trading service price ----------------------------
        # rate x (buy notional + sell notional), charged to BOTH members'
        # transaction value, no minimum, no maximum, no per-order component.
        ('exchange_service_hsx_equity',): (
            _interval(
                rule(charge_id='exchange_service_hsx_equity',
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.EXCHANGE, debited_at=DebitedAt.FILL,
                     pool=Pool.SECURITIES, venue=Venue.HSX,
                     applies_to=frozenset({ChargeClass.EQUITY}),
                     rate=_D('0.0003')),
                date(2019, 2, 15), date(2020, 3, 19),
                document=tt127, confidence=Confidence.HIGH),
            _interval(
                rule(charge_id='exchange_service_hsx_equity',
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.EXCHANGE, debited_at=DebitedAt.FILL,
                     pool=Pool.SECURITIES, venue=Venue.HSX,
                     applies_to=frozenset({ChargeClass.EQUITY}),
                     rate=_D('0.00027')),
                date(2020, 3, 19), document=tt127, confidence=Confidence.HIGH,
                note='2025-01-10 -> 2025-04-28 is assumed unchanged with no '
                     'gazetted source; QD 1541/QD-BTC re-issued the rate '
                     'unchanged from 2025-04-29. No fee or tax change is '
                     'traceable to KRX.'),
        ),
        ('exchange_service_hnx_equity',): (
            _interval(
                rule(charge_id='exchange_service_hnx_equity',
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.EXCHANGE, debited_at=DebitedAt.FILL,
                     pool=Pool.SECURITIES, venue=Venue.HNX,
                     applies_to=frozenset({ChargeClass.EQUITY}),
                     rate=_D('0.0003')),
                date(2019, 2, 15), date(2020, 3, 19),
                document=tt127, confidence=Confidence.HIGH),
            _interval(
                rule(charge_id='exchange_service_hnx_equity',
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.EXCHANGE, debited_at=DebitedAt.FILL,
                     pool=Pool.SECURITIES, venue=Venue.HNX,
                     applies_to=frozenset({ChargeClass.EQUITY}),
                     rate=_D('0.00027')),
                date(2020, 3, 19), document=tt127, confidence=Confidence.HIGH),
        ),
        ('exchange_service_hsx_etf_cw',): (
            _interval(
                rule(charge_id='exchange_service_hsx_etf_cw',
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.EXCHANGE, debited_at=DebitedAt.FILL,
                     pool=Pool.SECURITIES, venue=Venue.HSX,
                     applies_to=frozenset({ChargeClass.ETF,
                                           ChargeClass.WARRANT}),
                     rate=_D('0.0002')),
                date(2019, 2, 15), date(2020, 3, 19),
                document=tt127, confidence=Confidence.HIGH),
            _interval(
                rule(charge_id='exchange_service_hsx_etf_cw',
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.EXCHANGE, debited_at=DebitedAt.FILL,
                     pool=Pool.SECURITIES, venue=Venue.HSX,
                     applies_to=frozenset({ChargeClass.ETF,
                                           ChargeClass.WARRANT}),
                     rate=_D('0.00018')),
                date(2020, 3, 19), document=tt127, confidence=Confidence.HIGH,
                note='ETF units and covered warrants take a LOWER rate than '
                     'ordinary shares -- 0.00018 against 0.00027.'),
        ),
        ('exchange_service_upcom_equity',): (
            _interval(
                rule(charge_id='exchange_service_upcom_equity',
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.EXCHANGE, debited_at=DebitedAt.FILL,
                     pool=Pool.SECURITIES, venue=Venue.UPCOM,
                     applies_to=frozenset({ChargeClass.EQUITY}),
                     rate=_D('0.0002')),
                date(2019, 2, 15), date(2020, 3, 19),
                document=tt127, confidence=Confidence.HIGH),
            _interval(
                rule(charge_id='exchange_service_upcom_equity',
                     base=ChargeBase.TRADE_VALUE, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.EXCHANGE, debited_at=DebitedAt.FILL,
                     pool=Pool.SECURITIES, venue=Venue.UPCOM,
                     applies_to=frozenset({ChargeClass.EQUITY}),
                     rate=_D('0.00018')),
                date(2020, 3, 19), document=tt127, confidence=Confidence.HIGH),
        ),
        ('exchange_service_index_future',): (
            _interval(
                rule(charge_id='exchange_service_index_future',
                     base=ChargeBase.PER_CONTRACT, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.EXCHANGE, debited_at=DebitedAt.FILL,
                     pool=Pool.DERIVATIVES, venue=Venue.HNXDS,
                     applies_to=frozenset({ChargeClass.FUTURE}),
                     amount=_D('3000')),
                date(2019, 2, 15), date(2020, 3, 19),
                document=tt127, confidence=Confidence.HIGH),
            _interval(
                rule(charge_id='exchange_service_index_future',
                     base=ChargeBase.PER_CONTRACT, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.EXCHANGE, debited_at=DebitedAt.FILL,
                     pool=Pool.DERIVATIVES, venue=Venue.HNXDS,
                     applies_to=frozenset({ChargeClass.FUTURE}),
                     amount=_D('2700')),
                date(2020, 3, 19), document=tt127, confidence=Confidence.HIGH,
                note='2,700 VND per MATCHED CONTRACT -- absolute VND, not '
                     'thousand-VND, and per contract rather than per lot. '
                     'Government-bond futures take 4,500 and are not carried '
                     'here because ChargeRule has no product-family axis '
                     'within a venue.'),
        ),
        # --- depository ------------------------------------------------
        ('vsdc_custody_equity',): (
            _interval(
                rule(charge_id='vsdc_custody_equity',
                     base=ChargeBase.MONTHLY_PER_SECURITY, side=ChargeSide.NONE,
                     levied_by=LeviedBy.VSD, debited_at=DebitedAt.MONTHLY,
                     pool=Pool.SECURITIES, applies_to=cash_classes,
                     amount=_D('0.3')),
                date(2019, 2, 15), date(2020, 3, 19),
                document=vsdc, confidence=Confidence.HIGH),
            _interval(
                rule(charge_id='vsdc_custody_equity',
                     base=ChargeBase.MONTHLY_PER_SECURITY, side=ChargeSide.NONE,
                     levied_by=LeviedBy.VSD, debited_at=DebitedAt.MONTHLY,
                     pool=Pool.SECURITIES, applies_to=cash_classes,
                     amount=_D('0.27')),
                date(2020, 3, 19), document=vsdc, confidence=Confidence.HIGH,
                note='0.27 VND per unit per month. The only underlying-market '
                     'charge that is not per-fill: 100,000 shares held for a '
                     'month costs 27,000d regardless of turnover.'),
        ),
        ('vsdc_derivatives_position_management',): (
            _interval(
                rule(charge_id='vsdc_derivatives_position_management',
                     base=ChargeBase.PER_OPEN_CONTRACT_PER_DAY,
                     side=ChargeSide.NONE, levied_by=LeviedBy.VSD,
                     debited_at=DebitedAt.MONTHLY, pool=Pool.DERIVATIVES,
                     venue=Venue.HNXDS,
                     applies_to=frozenset({ChargeClass.FUTURE}),
                     amount=_D('3000')),
                date(2019, 2, 15), date(2020, 3, 19),
                document=vsdc, confidence=Confidence.HIGH),
            _interval(
                rule(charge_id='vsdc_derivatives_position_management',
                     base=ChargeBase.PER_OPEN_CONTRACT_PER_DAY,
                     side=ChargeSide.NONE, levied_by=LeviedBy.VSD,
                     debited_at=DebitedAt.MONTHLY, pool=Pool.DERIVATIVES,
                     venue=Venue.HNXDS,
                     applies_to=frozenset({ChargeClass.FUTURE}),
                     amount=_D('2550')),
                date(2020, 3, 19), date(2022, 1, 1),
                document=vsdc, confidence=Confidence.HIGH,
                note='Accrues per open contract per account per DAY, billed '
                     'monthly. The basis switched to per-fill on 2022-01-01, '
                     'and this row ENDS rather than continuing -- see '
                     'vsdc_derivatives_clearing. Brokers demonstrably billed '
                     'the per-day fee through at least 2024-07-11, so a run '
                     'reproducing actual retail costs and a run applying the '
                     'gazetted schedule disagree for three years.'),
        ),
        ('vsdc_derivatives_clearing',): (
            _interval(
                rule(charge_id='vsdc_derivatives_clearing',
                     base=ChargeBase.PER_CONTRACT, side=ChargeSide.BOTH,
                     levied_by=LeviedBy.VSD, debited_at=DebitedAt.FILL,
                     pool=Pool.DERIVATIVES, venue=Venue.HNXDS,
                     applies_to=frozenset({ChargeClass.FUTURE}),
                     amount=_D('2550')),
                date(2022, 1, 1), document=vsdc, confidence=Confidence.HIGH,
                note='2,550 VND per novated contract, BOTH legs. The shape '
                     'change on 2022-01-01 -- holding basis to per-fill basis '
                     '-- made intraday round trips more expensive and '
                     'multi-day holds cheaper: opening 20 and closing 8 in one '
                     'day costs (20+8) x 2,550 = 71,400d.'),
        ),
    }


#: Every table, assembled once. Assembling by rulebook id -- rather than
#: reading a module-level dict directly -- is what makes a second edition (a
#: counterfactual, a future rulebook, another market) data entry rather than a
#: fork of the resolver.
def _build_tables(rulebook_id: str) -> Dict[RuleName, Dict[Tuple[Any, ...], Tuple[RuleInterval, ...]]]:
    if rulebook_id not in RULEBOOK_IDS:
        raise ValueError(
            f'unknown rulebook id {rulebook_id!r}; this build carries '
            f'{RULEBOOK_IDS}. A rulebook is data, so adding one is a new '
            f'table set here, not a change to the resolver.'
        )
    margin = _margin_table()
    return {
        RuleName.TRADING_UNIT: _trading_unit_table(),
        RuleName.DAILY_TRADING_LIMIT: _daily_trading_limit_table(),
        RuleName.WIDENED_TRADING_LIMIT: _widened_trading_limit_table(),
        RuleName.TICK_SIZE: _tick_size_table(),
        RuleName.LEGAL_ORDER_TYPES: _legal_order_types_table(),
        RuleName.SETTLEMENT: _settlement_table(),
        RuleName.INITIAL_MARGIN_RATE: {
            k[1:]: v for k, v in margin.items()
            if k[0] is RuleName.INITIAL_MARGIN_RATE},
        RuleName.MARGIN_MODEL: {
            k[1:]: v for k, v in margin.items()
            if k[0] is RuleName.MARGIN_MODEL},
        RuleName.POSITION_LIMIT: _position_limit_table(),
        RuleName.MAX_ORDER_SIZE: _max_order_size_table(),
        RuleName.CHARGE: _charge_table(),
    }


def _candidate_keys(key: Tuple[Any, ...]) -> Tuple[Tuple[Any, ...], ...]:
    """``key`` and its wildcard generalisations, most specific first.

    A ``None`` in a table key is a wildcard, so a rule that does not vary on an
    axis is written once -- ``(Venue.UPCOM, None)`` says "LO only, in every
    phase" without repeating a row per phase. Trying the most specific key
    first is what lets ``(HNXDS, 'INDEX')`` override ``(HNXDS, None)`` without
    a second lookup path or an ordering convention the caller has to know.

    Ties between equally specific masks are broken **right-first**: the
    instrument or phase axis outranks the venue axis. That is the right
    precedence for this rulebook, and the bond row is why. A venue-wide band
    (``(HSX, None) -> 7%``) is a *default*; an instrument-class rule
    (``(None, 'BOND') -> no band at all``) is a *refinement* that holds at every
    venue and must therefore beat the default it refines. Breaking the tie the
    other way silently gives listed bonds a 7% band, which no venue imposes.
    """
    masks = sorted(
        product(*((True, False) for _ in key)),
        key=lambda m: (-sum(m), list(m)),
    )
    return tuple(
        tuple(k if keep else None for k, keep in zip(key, mask))
        for mask in masks
    )


def _matches_pin(pin_path: Sequence[str], rule: RuleName,
                 key: Tuple[Any, ...]) -> bool:
    """Whether a pin's dotted path selects this rule and key.

    The path is a *prefix* over ``[rule] + key``, so ``'tick_size'`` pins every
    tick and ``'tick_size.HSX'`` pins only HOSE's. A path longer than the key
    does not match, which is what keeps a field-selecting pin
    (``'settlement.cycle_days'``) from being mistaken for a key-selecting one.
    """
    if not pin_path or pin_path[0] != rule.value:
        return False
    rest = pin_path[1:]
    if len(rest) > len(key):
        return False
    return all(k is not None and _key_token(k) == want
               for want, k in zip(rest, key))


# --------------------------------------------------------------------------
# RuleSet -- every rule in force at one instant
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleSet:
    """Every dated rule at one instant. Obtain only from :meth:`Rulebook.at`.

    Immutable and cheap: it holds an instant, an edition and a reference to the
    rulebook that produced it. It is deliberately *not* a snapshot of resolved
    values, because materialising every rule per instant would reintroduce the
    thing shape 1 forbids -- a bundle of values that a caller can hold onto and
    reuse at a different instant. Each accessor resolves against ``self.ts``,
    so a ``RuleSet`` cannot be silently reused across a regime boundary.

    Two accessor families, and the difference is the point:

    * :meth:`resolve` is total. It returns a three-state
      :class:`RuleResolution` and never raises, so a caller that wants to count
      what the rulebook could not decide reads this.
    * the typed accessors (:meth:`trading_unit`, :meth:`tick_size`, ...) return
      the value directly and raise :class:`UnresolvedRule` when it is unknown.
      They have nowhere to put a third state, and returning ``None`` for both
      "no band applies" and "nobody knows" is the conflation this module
      exists to prevent.
    """

    ts: datetime
    edition: RulebookEdition
    book: 'Rulebook'

    # -- the total, non-raising path ------------------------------------

    def resolve(self, rule: RuleName, *key: Any) -> RuleResolution:
        """The dated row in force for ``rule`` at ``self.ts``, or why not."""
        return self.book._resolve(rule, key, self.ts)

    def require(self, rule: RuleName, *key: Any) -> Any:
        """:meth:`resolve`, unwrapped. Raises on anything but ``KNOWN``.

        ``NOT_APPLICABLE`` raises too: a caller asking for a number has no use
        for "there isn't one", and the accessors that legitimately want that
        answer (:meth:`daily_trading_limit`, :meth:`settlement_rule`) call
        :meth:`resolve` and handle it explicitly.
        """
        resolution = self.resolve(rule, *key)
        if not resolution.is_known:
            raise UnresolvedRule(resolution)
        return resolution.value

    def citation(self, rule: RuleName, *key: Any) -> Optional[RuleCitation]:
        """The document behind a value. Traceability is the whole claim.

        ``None`` for a pinned value, because no document says what a
        counterfactual says -- which is how a provenance record tells a pinned
        run from a sourced one.
        """
        return self.resolve(rule, *key).citation

    # -- instrument-level facts, all resolved at self.ts ----------------

    def trading_unit(self, venue: Venue,
                     kind: InstrumentKind = InstrumentKind.STOCK) -> int:
        """The round lot in force.

        HOSE's minimum was **10 units until 2021-01-03 and 100 from
        2021-01-04**. A date-blind lookup rejects every legal 10-share HOSE
        order placed before then, and that is not a corner case: the corpus
        holds 94,675 HSX stock closes in the 10-lot window.

        Delegates the numbers to ``core.constant.get_trading_unit``, which
        already carries the step. What this adds is the ``ts`` axis, a
        citation, and a refusal rather than a guess where the venue is not
        carried.
        """
        marker = self.require(RuleName.TRADING_UNIT, venue, kind)
        unit = get_trading_unit(venue.value, self.ts.date())
        if unit is None:
            raise UnresolvedRule(RuleResolution(
                rule=RuleName.TRADING_UNIT, key=(venue, kind), ts=self.ts,
                status=RuleStatus.UNKNOWN,
                note=f'core.constant.get_trading_unit carries no lot for '
                     f'{venue.value!r}'))
        assert marker == 'get_trading_unit'   # the table stores a delegation
        return unit

    def daily_trading_limit(self, venue: Venue,
                            kind: InstrumentKind = InstrumentKind.STOCK,
                            ticker: Optional[str] = None) -> Optional[Decimal]:
        """The ORDINARY band width, as a Decimal fraction of the reference.

        ``None`` means **no band applies** -- a sourced answer, currently only
        for listed bonds. It does *not* mean "unknown": an unknown band raises
        :class:`UnresolvedRule`, which is what a covered warrant does (its
        limits are derived from the underlying and the conversion ratio, not
        from a percentage of its own price) and what an unclassifiable HNXDS
        contract does (the index and government-bond bands differ by 2.3x).

        ``ticker`` is not decoration on HNXDS: band and tick there are
        contract-template values, so ``VN30F2206`` and ``GB05F2206`` resolve
        differently on the same venue at the same instant.

        **Declared limitation.** This is the ordinary band only. Widened bands
        -- first listing, post-suspension resumption, UPCoM's 25-session
        illiquidity band, the corporate-action cases -- need a security-state
        axis Tier 1 does not carry; they are tabulated under
        :meth:`widened_trading_limit`. The UPCoM 40% case alone covers 17.1% of
        UPCoM name-days, so a run over UPCoM understates the band on roughly
        one name-day in six.
        """
        resolution = self.resolve(
            RuleName.DAILY_TRADING_LIMIT, venue, self._band_key(venue, kind, ticker))
        if resolution.status is RuleStatus.NOT_APPLICABLE:
            return None
        if not resolution.is_known:
            raise UnresolvedRule(resolution)
        return resolution.value

    def widened_trading_limit(self, venue: Venue, case: str) -> Decimal:
        """The band that replaces the ordinary one in a named widened case.

        Tabulated but not wired: nothing in Tier 1 decides which case applies.
        ``case`` is one of ``first_trading_day``, ``resumption``,
        ``illiquidity`` or ``convertible_bond_ex_rights``.
        """
        return self.require(RuleName.WIDENED_TRADING_LIMIT, venue, case)

    def tick_size(self, venue: Venue,
                  kind: InstrumentKind = InstrumentKind.STOCK,
                  price: Optional[Decimal] = None, *,
                  method: TradingMethod = TradingMethod.ORDER_MATCHING,
                  ticker: Optional[str] = None) -> Optional[Decimal]:
        """The tick grid at this price, on this venue, under this method.

        ``method`` is required and is not a convenience. Put-through is 1d at
        all four cash venues -- a hundredfold finer grid than the matched grid
        at the same price -- so without the axis the ``TICK_GRID`` gate rejects
        every legitimate put-through price.

        ``None`` means **no band of the price table matches this price**, which
        is the existing ``get_hsx_tick_size`` behaviour and is treated by
        ``equity.py`` as INDETERMINATE. A tick that the rulebook does not carry
        at all raises instead.

        Classification is by instrument **kind**, not by the ticker string: the
        rulebook is explicit that HOSE's flat 10d ETF/warrant tick "keys on
        instrument type". ``ticker`` refines two things the kind cannot say --
        whether a ``FUND`` is an ETF (flat tick) or a closed-end fund (banded
        grid: all 151 FUC* close rows lie on the 50d grid), and which HNXDS
        product family a contract belongs to.
        """
        family = self._tick_family(venue, kind, ticker)
        value = self.require(RuleName.TICK_SIZE, venue, family, method)
        if value != _HSX_BANDED:
            return value
        if price is None:
            raise UnresolvedRule(RuleResolution(
                rule=RuleName.TICK_SIZE, key=(venue, family, method),
                ts=self.ts, status=RuleStatus.UNKNOWN,
                note="HOSE's matched tick is banded by price; a price is "
                     'required to resolve it'))
        # Reuse of the one price-tier table in the codebase, with the
        # instrument classification already made here.
        return get_hsx_tick_size(_HSX_BANDED_PROBE, price)

    # -- order types ----------------------------------------------------

    def legal_order_mnemonics(self, venue: Venue,
                              phase: SessionPhase) -> FrozenSet[str]:
        """The Vietnamese mnemonics this venue accepts in this phase.

        The primary datum, because two of the dated changes are invisible in
        ``core.order.OrderType``: HOSE's market order is **MP to 2025-05-04 and
        MTL from 2025-05-05** (a rename, not a semantic change, so both map to
        the same ``OrderType``), and HNX's post-close **PLO has no member at
        all**.
        """
        return self.require(RuleName.LEGAL_ORDER_TYPES, venue, phase)

    def legal_order_types(self, venue: Venue,
                          phase: SessionPhase) -> FrozenSet[OrderType]:
        """The ``OrderType`` view of :meth:`legal_order_mnemonics`.

        A limit order **is** legal in a call auction -- HOSE's session table
        reads "LO, ATO" and "LO, ATC" -- and what an auction refuses is the
        market family. ``OrderType.MARKET`` ("MKT") is legal at no venue on any
        date: it matches no Vietnamese order type, so no mnemonic maps to it
        and it cannot appear in any answer here.

        Empty for HNX's post-close session even though the venue accepts PLO
        there, because the enum cannot say PLO. Read
        :meth:`legal_order_mnemonics` when that distinction matters.
        """
        return _types_of(self.legal_order_mnemonics(venue, phase))

    def order_type_mnemonic(self, venue: Venue,
                            order_type: OrderType) -> Optional[str]:
        """What this venue calls ``order_type`` at this instant.

        ``MARKET_WITH_LEFTOVER_AS_LIMIT`` is ``'MP'`` on HOSE to 2025-05-04 and
        ``'MTL'`` from 2025-05-05. This is where the KRX rename lives; the
        legality set does not move, because the economics did not.
        """
        for phase in (SessionPhase.CONTINUOUS, SessionPhase.OPENING_AUCTION,
                      SessionPhase.CLOSING_AUCTION, SessionPhase.POST_CLOSE_PLO):
            for mnemonic in sorted(self.legal_order_mnemonics(venue, phase)):
                if _ORDER_TYPE_BY_MNEMONIC[mnemonic] is order_type:
                    return mnemonic
        return None

    # -- session phase --------------------------------------------------

    def phase(self, venue: Venue) -> SessionPhase:
        """The session phase at ``self.ts``.

        **The noon break is tested BEFORE the continuous session**, because
        ``ExchangeSpec.lo_session`` spans the break by construction -- HOSE's
        09:15-14:30 window is one interval with a hole in it, not two -- so
        testing continuous first reports 12:00 as CONTINUOUS. Nothing in the
        repository does this ordering today: both adapters hardcode
        CONTINUOUS. The break is a hard shutdown (no entry, amend, cancel, or
        put-through activity of any kind), so getting it wrong admits orders
        into a closed market.

        Two things this deliberately does not know, both declared:

        * **Holidays.** The trading calendar is ``calendar.py``'s, and this
          module must not import it. A public holiday therefore resolves like
          an ordinary weekday here, and the caller must gate on the trading
          calendar. Weekends *are* handled, because ``ExchangeSpec``'s own
          ``effective_day`` carries Mon-Fri.
        * **Daily bars.** A daily bar is stamped midnight, so this returns
          ``PRE_OPEN`` for it. That is why ``protocol.SessionPhase`` says the
          phase is set by the adapter and never inferred from a timestamp: a
          daily run that called this would mark every bar pre-open and reject
          the entire measurement. Use this for a tick-resolution clock, not for
          a daily one.
        """
        spec = _SPEC_BY_VENUE[venue]
        ts = self.ts.astimezone(_ICT) if self.ts.tzinfo is not None else self.ts
        if ts.weekday() not in (0, 1, 2, 3, 4):
            # No SessionPhase member says "closed all day". POST_CLOSE is the
            # only one meaning "not matching, and not going to today", and it
            # is what `equity.py` refuses with SESSION_SEMANTICS -- the right
            # outcome for a Saturday.
            return SessionPhase.POST_CLOSE
        clock = ts.time()

        def within(session) -> bool:
            return session is not None and session.start <= clock < session.end

        # Order is normative. Noon break first, for the reason above; the
        # auctions before the continuous window because HSX's ATC (14:30-14:45)
        # begins exactly where lo_session ends and an inclusive bound would put
        # 14:30 in both.
        if within(spec.noon_break):
            return SessionPhase.NOON_BREAK
        if within(spec.ato_session):
            return SessionPhase.OPENING_AUCTION
        if within(spec.atc_session):
            return SessionPhase.CLOSING_AUCTION
        if within(spec.plo_session):
            return SessionPhase.POST_CLOSE_PLO
        if within(spec.lo_session):
            return SessionPhase.CONTINUOUS
        if within(spec.before_trading_session):
            return SessionPhase.PRE_OPEN
        after = spec.after_trading_session
        if after is not None and clock >= after.start:
            return SessionPhase.POST_CLOSE
        return SessionPhase.UNKNOWN

    # -- settlement, margin, limits -------------------------------------

    def settlement_rule(self, kind: InstrumentKind) -> Optional[SettlementRule]:
        """T+N and the delivery instant for this instrument class.

        The cycle has been **T+2 since 2016-01-01**; what changed on 2022-08-29
        was the *time of day*. Before then settlement completed after the
        close, so the first sellable session was the T+3 open; from then,
        client allocation is due by 13:00 on T+2 and the shares are sellable in
        the afternoon session.

        ``None`` for an instrument class that does not settle (an index).
        """
        resolution = self.resolve(RuleName.SETTLEMENT, kind)
        if resolution.status is RuleStatus.NOT_APPLICABLE:
            return None
        if not resolution.is_known:
            raise UnresolvedRule(resolution)
        return resolution.value

    def initial_margin_rate(self, contract_code: str) -> Decimal:
        """VSD's initial margin ratio for one contract at this instant.

        10% from 2017-08-10, 13% from 2018-07-18, 17% from 2022-12-15, and 0.17
        verified still in force at 2026-08-21. **17.5% matches no source at any
        date** and is a transcription slip for 0.17.

        Delegates to :func:`plutus.market.margin.vsd_initial_margin`, which is
        already dated. The series must not be re-implemented here: the
        derivatives transfer tax base is linear in this same ratio, and the
        rulebook requires both to read one series or the two disagree.

        ``contract_code`` is required even though every observed entry is
        equal, because VSDC publishes the ratio **per listed contract** and
        names time-to-maturity as an input -- so the correct key is
        ``(contract_code, date)`` and the axis must exist before it is needed.
        """
        family = _futures_family(contract_code)
        marker = self.require(RuleName.INITIAL_MARGIN_RATE, family)
        assert marker == 'vsd_initial_margin'
        try:
            return vsd_initial_margin(self.ts.date())
        except ValueError as exc:
            raise UnresolvedRule(RuleResolution(
                rule=RuleName.INITIAL_MARGIN_RATE, key=(family,), ts=self.ts,
                status=RuleStatus.UNKNOWN, note=str(exc))) from exc

    def margin_model(self) -> str:
        """Which margin MECHANISM is in force -- not which rate.

        ``'pre_margin'`` to 2025-05-04. From the cutover the mechanism is KRX's
        post-trade COMS calculation, whose formula could not be obtained, so
        this raises rather than reporting the pre-KRX shape. That refusal is
        the design's requirement made concrete: an unsourced post-KRX value
        says so instead of silently returning its predecessor.
        """
        return self.require(RuleName.MARGIN_MODEL)

    def position_limit(self, contract_code: str,
                       investor: InvestorClass = InvestorClass.INDIVIDUAL
                       ) -> Optional[int]:
        """Net position cap in contracts, or 0 where the class may not hold.

        5,000 / 10,000 / 20,000 by investor class for index futures, all
        LOW confidence -- the triple appears in the 2017 launch announcement
        and in 2025/2026 broker material, HNX's current template prints no
        number, and no VSDC notice inside 2020-2026 republishes them. That a
        limit exists is not in doubt; the numbers are.

        **Individuals may not hold government-bond futures at all**, which is
        the value 0 rather than an absence.
        """
        family = _futures_family(contract_code)
        return self.require(RuleName.POSITION_LIMIT, family, investor)

    def max_order_size(self, venue: Venue) -> int:
        """Largest quantity one order may carry.

        HOSE 500,000 units from 2021-01-04; HNXDS 500 contracts. HNX and UPCoM
        publish none in any rulebook read, so they raise: "no cap" is an
        inference from HOSE's clause being HOSE-specific, not a sourced rule,
        and the 999,900-share figure that circulates for HNX was neither
        confirmed nor refuted.
        """
        return self.require(RuleName.MAX_ORDER_SIZE, venue)

    # -- charges --------------------------------------------------------

    def charges(self, venue: Venue,
                cls_: ChargeClass = ChargeClass.EQUITY) -> Tuple[ChargeRule, ...]:
        """State, exchange and VSD charge rows in force at this instant.

        Refuses to return a broker row. Commission, the sale-advance rate and
        the utilisation ladder are commercial terms that differ by firm and
        change at will; a dated rulebook that carried them would forfeit the
        traceability that is its whole claim. They live on
        :class:`plutus.market.session.types.BrokerProfile`.

        The derivatives transfer tax is the one row whose rate is computed
        here rather than stored: its published base is linear in the VSD
        initial margin ratio, so it is dated by the same series
        :meth:`initial_margin_rate` reads.
        """
        out = []
        for key in sorted(self.book._tables[RuleName.CHARGE]):
            resolution = self.resolve(RuleName.CHARGE, *key)
            if not resolution.is_known:
                continue
            row: ChargeRule = resolution.value
            if row.levied_by is LeviedBy.BROKER:
                raise ValueError(
                    f'charge {row.charge_id!r} is levied_by=BROKER and must '
                    f'not be in the dated rulebook; broker terms belong in '
                    f'BrokerProfile'
                )
            if row.venue is not None and row.venue is not venue:
                continue
            if cls_ not in row.applies_to:
                continue
            if row.charge_id == 'pit_derivatives_transfer' and row.rate is None:
                row = replace(row,
                              rate=_D('0.0005') * self.initial_margin_rate(
                                  'VN30F'))
            # The citation lives on the dated interval, because one charge id
            # spans several rate regimes with different sources. Stamping it
            # onto the row here is what makes ChargeRule's own rule -- a
            # state/exchange/VSD row MUST carry a citation -- true by
            # construction rather than by each table entry remembering.
            if row.citation is None:
                row = replace(row, citation=resolution.citation)
            out.append(row)
        return tuple(out)

    # -- private --------------------------------------------------------

    @staticmethod
    def _band_key(venue: Venue, kind: InstrumentKind,
                  ticker: Optional[str]) -> Any:
        """The second axis of the band table: family on HNXDS, kind elsewhere."""
        if venue is Venue.HNXDS:
            return _futures_family(ticker)
        if kind is InstrumentKind.WARRANT or (
                ticker is not None and is_covered_warrant(ticker)):
            return InstrumentKind.WARRANT
        return kind

    @staticmethod
    def _tick_family(venue: Venue, kind: InstrumentKind,
                     ticker: Optional[str]) -> Optional[str]:
        """The second axis of the tick table.

        ``'ETF_CW'`` covers the two instrument types that take a flat tick;
        ``'BANDED'`` covers everything that takes the venue's price-tiered or
        flat share grid -- including closed-end funds, which are eight
        characters and begin with ``F`` like the ETFs but are not ETFs and do
        not get the flat tick.
        """
        if venue is Venue.HNXDS:
            return _futures_family(ticker)
        if kind is InstrumentKind.WARRANT:
            return 'ETF_CW'
        if kind is InstrumentKind.FUND:
            # An ETF takes the flat tick; a closed-end fund does not.
            return 'ETF_CW' if (ticker is None or is_etf(ticker)) else 'BANDED'
        if ticker is not None and (is_covered_warrant(ticker) or is_etf(ticker)):
            return 'ETF_CW'
        return 'BANDED'


# --------------------------------------------------------------------------
# Rulebook -- the dated rule sets
# --------------------------------------------------------------------------

class Rulebook:
    """The dated rule sets. Resolves at an instant, never at load.

    Construction chooses a rulebook *id* and a set of counterfactual pins, and
    nothing else. In particular it does not choose a regime, a venue, a
    settlement cycle or an edition: those are answers to
    :meth:`at`, because a run's ``period`` spans regime changes and a single
    scalar version chosen here would be wrong for most of it.

    Pins are legal and are the mechanism by which a post-KRX rulebook is run
    against pre-KRX data as a control. Every pin is reported in
    :attr:`pins` and stamped ``pinned=True`` on the resolution it overrides,
    which is exactly the difference between a counterfactual and a lie.
    """

    def __init__(self, rulebook_id: str = 'vn-2020-2026',
                 pins: Sequence[Pin] = ()) -> None:
        self.rulebook_id = rulebook_id
        self._tables = _build_tables(rulebook_id)
        self._pins = tuple(pins)
        for pin in self._pins:
            head = pin.path.split('.')[0]
            if head not in {r.value for r in RuleName}:
                raise ValueError(
                    f'pin path {pin.path!r} does not name a rule; the first '
                    f'component must be one of '
                    f'{sorted(r.value for r in RuleName)}'
                )

    @classmethod
    def load(cls, rulebook_id: str, pins: Sequence[Pin] = ()) -> 'Rulebook':
        """Build a rulebook by id, applying counterfactual pins."""
        return cls(rulebook_id=rulebook_id, pins=pins)

    # -- THE entry point ------------------------------------------------

    def at(self, ts: datetime) -> RuleSet:
        """Every rule in force at one instant.

        The single call every other module makes. Cheap by design -- a
        ``RuleSet`` is an instant plus a reference, not a materialised bundle
        -- so calling it per event, which is what shape 1 requires, costs
        nothing worth optimising away with a cache that would reintroduce the
        problem.
        """
        return RuleSet(ts=ts, edition=self.edition_at(ts), book=self)

    @property
    def pins(self) -> Tuple[Pin, ...]:
        """Overrides in force, for the session's provenance record."""
        return self._pins

    def edition_at(self, ts: datetime) -> RulebookEdition:
        """``PRE_KRX`` before 2025-05-05, ``POST_KRX`` from it.

        A dated rule set, not a migration: both editions ship, both stay, and a
        run spanning the boundary gets each on its own side within one session.
        The boundary is half-open, so 2025-05-04 is PRE and 2025-05-05 is POST
        with no instant in both and none in neither.
        """
        return (RulebookEdition.POST_KRX if ts.date() >= KRX_CUTOVER
                else RulebookEdition.PRE_KRX)

    # -- resolution -----------------------------------------------------

    def _resolve(self, rule: RuleName, key: Tuple[Any, ...],
                 ts: datetime) -> RuleResolution:
        """Resolve one rule at one instant. Total: never raises."""
        table = self._tables[rule]
        on = ts.date()
        row = None
        matched_key = key
        for candidate in _candidate_keys(key):
            series = table.get(candidate)
            if series is None:
                continue
            row = _pick(series, on)
            if row is not None:
                matched_key = candidate
                break
        if row is None:
            return self._apply_pins(RuleResolution(
                rule=rule, key=key, ts=ts, status=RuleStatus.UNKNOWN,
                note=(f'no dated row for {rule.value} at '
                      f'{tuple(_key_token(k) for k in key)} on {on}; this '
                      f'rulebook covers {COVERAGE_START}..{COVERAGE_END}')))
        return self._apply_pins(RuleResolution(
            rule=rule, key=matched_key, ts=ts, status=row.status,
            value=row.value, citation=row.citation,
            confidence=row.citation.confidence if row.citation else None,
            note=row.note))

    def _apply_pins(self, resolution: RuleResolution) -> RuleResolution:
        """Overlay any counterfactual pin selecting this rule and key.

        Two path forms, and both are needed. ``'tick_size.HSX'`` replaces the
        whole value for a key; ``'settlement.cycle_days'`` replaces one *field*
        of a record value, which is what the :class:`Pin` docstring's own
        example does. A trailing component naming a field of the resolved
        dataclass selects the second form -- otherwise a caller wanting to pin
        T+3 would have to hand-build a whole ``SettlementRule`` including a
        citation that, being counterfactual, does not exist.

        The most specific matching pin wins, so a general pin can be narrowed
        by a specific one rather than the two racing.
        """
        best: Optional[Tuple[int, Pin, Optional[str]]] = None
        for pin in self._pins:
            path = pin.path.split('.')
            field_name = None
            if (len(path) > 1 and resolution.value is not None
                    and _is_dataclass_field(resolution.value, path[-1])):
                field_name, path = path[-1], path[:-1]
            if not _matches_pin(path, resolution.rule, resolution.key):
                continue
            specificity = len(path)
            if best is None or specificity >= best[0]:
                best = (specificity, pin, field_name)
        if best is None:
            return resolution
        _, pin, field_name = best
        value = (replace(resolution.value, **{field_name: pin.value})
                 if field_name else pin.value)
        return replace(resolution, status=RuleStatus.KNOWN, value=value,
                       citation=None, confidence=None, pinned=True,
                       note=pin.reason or 'counterfactual pin')

    def __repr__(self) -> str:
        return (f'{type(self).__name__}({self.rulebook_id!r}, '
                f'pins={len(self._pins)})')


def _is_dataclass_field(value: Any, name: str) -> bool:
    """Whether ``name`` is a field of ``value``'s dataclass type."""
    try:
        return any(f.name == name for f in fields(value))
    except TypeError:
        return False


# --------------------------------------------------------------------------
# SymbolRouter -- the (ticker, ts) -> venue seam
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class VenueListing:
    """One dated listing of a ticker on a venue.

    The authoritative half of the router. ``effective_to`` is **exclusive**,
    matching :class:`RuleInterval`, so a ticker that moves from HNX to HOSE on
    2025-07-01 gets ``(HNX, ..., 2025-07-01)`` and ``(HSX, 2025-07-01, None)``
    and belongs to exactly one venue on that day.

    Empty by default and populated as data. Within 2021-2022 nothing varies and
    no ticker changes venue -- the HNX-to-HOSE transfers are 2025-07 -- so the
    seam is thin today. It must exist from this module anyway: without it every
    band, tick, lot and fee lookup inherits a frozen venue, and adding the
    ``ts`` axis later means threading it through every call site.
    """

    ticker: str
    venue: Venue
    effective_from: date
    effective_to: Optional[date] = None
    citation: Optional[RuleCitation] = None

    def covers(self, on: date) -> bool:
        if on < self.effective_from:
            return False
        return self.effective_to is None or on < self.effective_to


class SymbolRouter:
    """``(ticker, ts) -> venue``. The seam locked shape 1 exists to create.

    **Forbidden build: a ticker-keyed venue cache.**
    ``adapters/datahub.py:225`` holds ``Dict[str, InstrumentSpec]`` -- one
    venue per ticker for the process lifetime, built from the corpus's
    *static* ``exchangeid``. For a transferred ticker that assigns UPCoM's 100d
    tick and +/-15% band to rows that actually traded on HOSE under a 10d tick
    and +/-7% band, and the corpus shows the damage: all 3,729 UPCoM off-grid
    closes are venue-transfer artefacts, each ticker's off-grid rows stopping
    exactly at its last HOSE session. This class holds no cache and resolves on
    every call.

    ``MarketDataSource.instrument(ticker)`` has **no ``ts``** -- the one
    violation of shape 1 in the codebase. This class is what contains it: the
    source is asked for *classification* only (kind, multiplier, expiry,
    underlying), and everything dated is overwritten from the ``RuleSet``
    before the spec is returned.

    That overwrite is not cosmetic. ``equity.py``'s ``ROUND_LOT`` rule prefers
    ``instrument.trading_unit`` when an ``InstrumentSpec`` is passed and falls
    back to the dated ``get_trading_unit()`` otherwise -- so passing the
    adapter's spec **disables** the dated rule. Returning a spec whose
    ``trading_unit`` is already date-correct is what makes passing it safe.
    """

    def __init__(self, source: Optional[MarketDataSource],
                 rulebook: Rulebook, *,
                 listings: Sequence[VenueListing] = ()) -> None:
        self._source = source
        self._rulebook = rulebook
        self._listings = tuple(listings)

    # -- venue ----------------------------------------------------------

    def venue(self, ticker: str, ts: datetime) -> Venue:
        """The venue this ticker traded on at this instant.

        Resolution order, most authoritative first:

        1. a dated :class:`VenueListing`, which is the only source that can
           express a transfer;
        2. the futures code shape, because no ticker master in this repository
           carries HNXDS rows at all;
        3. the data source's static classification, which is *contained* here
           rather than trusted: it is the latest exchange assignment, not the
           one in force at ``ts``, and it is right only while no transfer has
           happened.

        Raises :class:`UnresolvedRule` rather than defaulting when none of the
        three answers. A silently defaulted venue is shape 1's failure mode and
        would produce a plausible band, tick, lot and fee that are all wrong
        together.
        """
        on = ts.date()
        for listing in self._listings:
            if listing.ticker == ticker and listing.covers(on):
                return listing.venue
        if _futures_family(ticker) is not None:
            return Venue.HNXDS
        if self._source is not None:
            code = self._source.instrument(ticker).exchange_code
            if code:
                try:
                    return Venue.from_code(code)
                except ValueError:
                    pass
        raise UnresolvedRule(RuleResolution(
            rule=RuleName.TRADING_UNIT, key=(ticker,), ts=ts,
            status=RuleStatus.UNKNOWN,
            note=(f'no venue for {ticker!r} at {on}: no dated listing, not a '
                  f'futures code, and no data source classified it')))

    def exchange(self, ticker: str, ts: datetime) -> Exchange:
        """The ``exchanges/`` object that judges this ticker at this instant."""
        return _EXCHANGE_BY_VENUE[self.venue(ticker, ts)]

    # -- instrument -----------------------------------------------------

    def instrument(self, ticker: str, ts: datetime) -> InstrumentSpec:
        """The instrument AS OF ``ts``.

        ``exchange_code`` stays scalar -- ``InstrumentSpec`` is frozen and this
        module may not change it -- but it is the venue *at that instant*, and
        ``trading_unit`` and ``daily_trading_limit`` come from the
        :class:`RuleSet` rather than from the adapter's undated spec.

        Raises :class:`UnresolvedRule` for a covered warrant, deliberately.
        ``InstrumentSpec.daily_trading_limit`` is a required ``Decimal`` and a
        warrant has no percentage band at all -- its limits are derived from
        the underlying and the conversion ratio -- so there is no honest value
        to put there. Filling in the venue's 7% is exactly the defect the
        rulebook names: wrong in both directions, and badly wrong for cheap
        warrants, where the floor-at-10d branch fires on 35% of name-days.
        ``exchange.py`` turns this into ``Rejected(verdict=INDETERMINATE)``.
        """
        rules = self._rulebook.at(ts)
        venue = self.venue(ticker, ts)
        base = self._source.instrument(ticker) if self._source else None
        kind = self._classify(ticker, base)
        limit = rules.daily_trading_limit(venue, kind, ticker)
        if limit is None:
            raise UnresolvedRule(RuleResolution(
                rule=RuleName.DAILY_TRADING_LIMIT, key=(venue, kind), ts=ts,
                status=RuleStatus.NOT_APPLICABLE,
                note=(f'{ticker!r} has no price band at this instant, and '
                      f'InstrumentSpec.daily_trading_limit cannot say so')))
        return InstrumentSpec(
            ticker=ticker,
            exchange_code=venue.value,
            kind=kind,
            trading_unit=rules.trading_unit(venue, kind),
            daily_trading_limit=limit,
            multiplier=(base.multiplier if base is not None
                        else self._default_multiplier(ticker)),
            expiry=base.expiry if base is not None else None,
            underlying=base.underlying if base is not None else None,
        )

    # -- private --------------------------------------------------------

    @staticmethod
    def _classify(ticker: str,
                  base: Optional[InstrumentSpec]) -> InstrumentKind:
        """Instrument kind, preferring the source and falling back to shape.

        Classification is the one thing the source is genuinely authoritative
        about -- it reads the ticker master -- so it wins where it has an
        answer. The shape fallback exists so a session can run without a
        corpus, and it uses the same ``is_covered_warrant`` / ``is_etf``
        predicates the tick rule uses, which is what stops the two drifting
        apart the way the old ``len == 8 and ticker[0] in 'CEF'`` test did.
        """
        if base is not None and base.kind is not InstrumentKind.UNKNOWN:
            return base.kind
        if _futures_family(ticker) is not None:
            return InstrumentKind.FUTURE
        if is_covered_warrant(ticker):
            return InstrumentKind.WARRANT
        if is_etf(ticker):
            return InstrumentKind.FUND
        return InstrumentKind.STOCK

    @staticmethod
    def _default_multiplier(ticker: str) -> Decimal:
        """VND per quoted unit, for a contract with no source spec.

        100,000 VND per index point for VN30F and VN100F; 10,000 for the
        government-bond futures, which quote VND on a 100,000d face. One is not
        a substitute for the other.
        """
        family = _futures_family(ticker)
        if family == 'INDEX':
            return _D('100000')
        if family == 'GB':
            return _D('10000')
        return _D('1')
