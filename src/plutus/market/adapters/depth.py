"""A data source that serves an order book -- and the age of everything in it.

This is the depth seam a sweep needs. ``DataHubSource`` serves a daily bar and
``TickSource`` serves a price ladder with ``BookLevel.size`` permanently
``None``; neither can answer "how many shares rest at the touch, and how many
one tick behind it". The dev extract at ``hermes-dev-extract`` can, for some
windows and not others, and the whole design of this module is about making
"not others" a stated fact rather than an empty ladder that reads as "nobody is
bidding".

Three measured properties of the corpus shape everything below. The first two
were given; the third and fourth were measured here and change the algorithm.

**1. Depth is three levels.** ``depth`` is 1, 2 or 3 in every price and size
table in the extract, for every ticker. There is no level 4, and this module
never extrapolates one -- a sweep that exhausts level 3 is INDETERMINATE for
its remainder, not filled against an invented level.

**2. The two sides are not observed together.** On FPT, 2022-11-09
(``local_quote``), only **53 of 203** bidprice instants have an askprice
instant at the same microsecond. There is no moment at which the full
two-sided book is observed, so a book here is *reconstructed* by an as-of join
per side and is an inference. Measured cross-side skew on that day: median
**8.3 s**, p90 **51.6 s**, max **529.3 s** across the 2,795 books this source
serves for that ticker-day; restricted to the 203 bid-price instants alone,
median **20.7 s**, p90 **216.6 s**, max **932.6 s**. On thin HTV the same day it
is median **584.9 s**, max **13,785 s** -- nearly four hours between the
freshest quote on one side and the freshest on the other.
:attr:`DepthBook.cross_side_skew` reports it on every book, because a book built
from a 4-second-old bid and a 40-second-old ask is a weaker object than one
where both are current and the caller has to be able to tell.

**3. The tables are per-level CHANGE STREAMS, not per-instant snapshots.**
This is the finding that changes the algorithm, and it is not what "take the
latest price row at or before ``ts``" suggests. Grouping the rows of one table
by instant and listing which depths appear gives, for FPT ``local_quote``:

===================  ==========================================================
``bidprice``         ``{1,2,3}`` 4274, ``{2,3}`` 355, ``{3}`` 119, ``{1,2}`` 58,
                     ``{1}`` 51, ``{2}`` 2
``bidsize``          ``{1}`` 15719, ``{2}`` 4108, ``{1,2,3}`` 4105, ``{3}`` 3211,
                     ``{1,2}`` 630, ``{2,3}`` 603, ``{1,3}`` 323
===================  ==========================================================

``{1,3}`` occurs 323 times, ``{3}`` alone 3211 times. A snapshot cannot have a
level 3 and no level 1; a change stream can, and does. Counted across the whole
extract there are **75,965** bid-size instants and **4,680** bid-price instants
whose depth set is not a prefix ``{1}``/``{1,2}``/``{1,2,3}``.

The consequence: the as-of join must be **per (side, level)**, not per side.
Taking the latest *instant* and reading its rows would return a one-level
ladder at the 15,719 instants where only level 1 changed, and would silently
delete the two levels behind the touch -- which is the difference between a
sweep that walks and a sweep that never gets past the touch.
:meth:`_Stream.at` does one bisect per level, and each level therefore carries
**its own age**. A worked instance: FPT at 2022-11-09 10:30:00 has all three
bid prices from one instant 182 s earlier, and sizes of 1200/1300/6400 from
*three* instants -- 73 s, 14.9 s and 14.9 s old. One age per side could not have
said that.

The same property produces genuine holes. HPG's ask side on 2022-11-09 opens
with a ``{2,3}`` price update and no level 1, leaving **149 of 11,988** books
that day with levels 2 and 3 known and no touch; VN30F2504 on 2025-04-02 does
the same on both sides for its first 150 books. This source refuses those --
:attr:`SideAvailability.ABSENT` with :attr:`Truncation.LADDER_GAP` and the seen
depths in :attr:`DepthSide.observed_depths` -- rather than promote level 2 into
the touch.

**4. A level's price and its size are not always written together.** Measured
share of price rows that have no size row at the same ``(instant, depth)``:
FPT bid 2.28 %, HPG bid 0.16 %, HTV bid **18.97 %** (``local_quote``). Where
they diverge, this module pairs the freshest price with the freshest size *at
that level*, which can pair a new price with the size of the price it replaced.
That mispairing is not detectable row by row, so it is not silently corrected;
it is bounded by the numbers above, and :attr:`DepthLevel.size_age` is greater
than :attr:`DepthLevel.price_age` exactly on the levels where it can have
happened, so a caller can filter on it.

Where the reconstruction is sound, and where it is not
------------------------------------------------------------------------
An independent as-of join per side can produce a book that never existed: a bid
above the ask. That is a free arbitrage a real market would have matched away,
and it is the direct, countable symptom of the skew in point 2. Measured over
every price-change instant in the extract, best bid against best ask, split by
session window (FPT, ``local_quote``, Nov 2022):

============  =========  =========  ========
window        instants   crossed    touching
============  =========  =========  ========
continuous    7022       4 (0.06%)  37
09:00-09:15   26         15 (58%)   4
14:30-14:45   31         1          2
============  =========  =========  ========

So the reconstruction is sound in the continuous session -- 6 crossed books per
ten thousand -- and badly unsound inside the opening auction, where more than
half the reconstructed books are crossed. That is an independent, measured
confirmation that sweeping is a continuous-session mechanic: during ATO/ATC
there is no resting two-sided book to walk, and this corpus cannot pretend
otherwise. :attr:`DepthBook.is_crossed` flags it per book so a sweep can refuse
rather than fill an arbitrage that was not there.

What this source cannot say
------------------------------------------------------------------------
There is **no deletion record**. A ladder that shrinks from three resting
levels to one emits no row saying so; the levels behind simply stop being
updated. A forward-filled level 3 may therefore be a level that no longer
exists, and nothing in the data distinguishes that from a level that is merely
quiet. This is why staleness is reported per level rather than per side, why
``max_age=`` exists, and why :attr:`SideAvailability.EMPTY` is declared but
**never returned** by this source: "the book has no shares" is a fact the
corpus cannot express, and collapsing it into "we have not seen the book" would
be exactly the confusion :class:`SideAvailability` exists to prevent.

Which windows carry depth
------------------------------------------------------------------------
Sizes are not everywhere, and a source that cannot serve depth has to say so
rather than serve an empty ladder. Measured row counts in the extract:

* ``local_quote_*`` -- FPT and HTV Nov 2022, HPG 2022-10-20..11-18. Prices
  **and sizes** for all three.
* ``quote_*`` -- FPT/HPG 2025-04-01..04-18 and VN30F2504 2025-04-01..04-17,
  prices and sizes; plus **HTV Nov 2022 with prices and zero size rows** --
  ``quote_bidsize``/``quote_asksize`` hold no HTV row at all, so every HTV
  price row in that root (564 bid, 371 ask, 100 %) is unmatched by a size.
* HTV is thin even where sizes exist: on 2022-11-09 ``local_quote_bidsize``
  has **41** rows and ``local_quote_asksize`` has 20, against 1,244 and 2,497
  for FPT the same day. The bid and ask sides of HTV that day share **zero**
  instants, and this source serves only **31** books for the whole session.

Sizing is all-or-nothing in practice: across every two-sided book served for
FPT, HPG and HTV on 2022-11-09 and VN30F2504 on 2025-04-02, the count of books
with a served level missing its size is **zero**. Where a window has sizes it
has them at every level; where it does not, it has none. That is why
:attr:`DepthSide.has_sizes` is an ``all()`` and not a per-level flag.

:data:`DepthSource.SERVES` and :data:`DepthSource.WITHHELD` declare the
contract the way ``DataHubSource`` does, and every :class:`DepthBook` carries
:attr:`DepthBook.withheld`. ``BOOK_SIZE`` is deliberately *not* in the class
constant: it is served where the rows exist and named per-book where they do
not, which is the only shape that can tell "this source never has sizes" from
"this window does not". :meth:`DepthSource.coverage` answers the question
before a run starts.

Two boundaries that are set, not inferred
------------------------------------------------------------------------
**Forward fill never crosses a calendar day.** HSX cancels unfilled orders at
the close and has no GTC, so yesterday's ladder is not evidence about today's
09:00 book. It does cross the lunch break, because resting orders genuinely
survive it -- which is why the maximum observed per-level gap is 5,412 s
(11:30:01 to 13:00:13 on 2022-11-09) and why a caller passing ``max_age=``
should size it against that, not against the median 35 s.

**One source reads one table prefix.** ``local_quote_*`` and ``quote_*`` are
two different observers of the same market -- HTV Nov 2022 appears in both,
with the same 564 bid-price rows at timestamps ~100 microseconds apart, and
with sizes in one and not the other. Merging them would invent a lineage no
row carries. The prefix is a constructor argument and the caller picks.
"""

import bisect
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import (ClassVar, Dict, FrozenSet, Iterator, List, Optional, Tuple,
                    Union)

import duckdb

from plutus.core.order import Side
from plutus.market.protocol import BookLevel, OrderBook, Resolution
from plutus.market.session.types import DataField

__all__ = ['DepthSource', 'DepthBook', 'DepthSide', 'DepthLevel',
           'DepthCoverage', 'SideAvailability', 'Truncation', 'MAX_DEPTH']

#: The archive carries depth 1-3 in every table, for every ticker. Levels 4+
#: return no rows anywhere in the extract, and this module never invents one.
MAX_DEPTH = 3

_ZERO = timedelta(0)


class SideAvailability(str, Enum):
    """Why one side of a reconstructed book looks the way it does.

    A tuple of levels cannot carry this distinction: ``asks=()`` reads as "no
    liquidity" whichever of these produced it, and the four causes below have
    nothing in common. Design section 9.2's "nothing silently defaults" applies
    to a *side* as much as to a field.
    """

    OBSERVED = 'observed'
    """A price is known at level 1 at or before ``ts``, so there is a touch to
    sweep into. ``levels`` is non-empty."""

    EMPTY = 'empty'
    """The book was observed and is genuinely empty -- nobody is resting.

    **This source never returns it.** The corpus carries no deletion record: a
    ladder emptying out emits no row, its levels simply stop updating. The
    member exists so that a future source which *can* observe an empty book
    does not have to reuse :attr:`ABSENT` and thereby merge "there are no
    shares" with "we have not looked", which are opposite facts -- one is a
    definite no-fill, the other an INDETERMINATE.
    """

    ABSENT = 'absent'
    """No **servable** touch at ``ts``, although this ticker is inside this
    source's observed window. Read :attr:`DepthSide.truncation` for which of
    three causes it was.

    ``NO_OBSERVATION`` -- the side has not been quoted yet today. HTV's ask
    side on 2022-11-09 is ABSENT until 09:02:25.

    ``LADDER_GAP`` -- level 1 is unobserved while a deeper level is known.
    :attr:`DepthSide.observed_depths` names what was seen. A ladder with no
    touch is not a side an order can sweep, and promoting level 2 into the
    touch would report a book that was never quoted.

    ``MAX_AGE`` -- the touch exists but is older than the caller's budget. Not
    the corpus's ignorance but the caller's own rule, which is why it is a
    separate value and not folded into the others.
    """

    OUT_OF_WINDOW = 'out_of_window'
    """The ticker is in this source, but ``ts`` is outside every day it holds.

    Distinct from :attr:`ABSENT` because it is a fact about the *extract*, not
    about the market: asking ``local_quote`` for FPT in 2023 is a coverage
    error, and reporting it as "the market had not quoted yet" would hide a
    misconfigured run behind a plausible market state.
    """

    UNSERVED = 'unserved'
    """This source holds no row for this ticker in this table at all.

    Asking a ``local_quote`` source for VN30F2504, or any source for a ticker
    outside the extract. Again a configuration fact, not a market fact.
    """


class Truncation(str, Enum):
    """Why a served ladder stopped short of :data:`MAX_DEPTH`.

    An enum rather than a flag because the two causes need separate counts: one
    is the corpus being quiet, the other is the caller's own staleness budget.
    """

    NONE = 'none'
    """The ladder runs to :data:`MAX_DEPTH` -- as deep as the corpus goes."""

    NO_OBSERVATION = 'no_observation'
    """The side has simply not been quoted that deep today, and nothing deeper
    has been either. The ordinary shape early in a session: HTV's bid on
    2022-11-09 is one level at 09:00:12 and two at 09:00:15 before reaching
    three at 09:13:19. Not a defect, and not evidence that the level does not
    exist -- only that we have not seen it."""

    LADDER_GAP = 'ladder_gap'
    """A level had no observation at or before ``ts`` **while a deeper one
    did** -- a real hole. Everything at and beyond it is dropped: a resting
    book has no holes, so a hole is our ignorance, and serving level 3 as
    though it sat directly behind level 1 would misstate both its price and its
    distance from the touch."""

    MAX_AGE = 'max_age'
    """A level was older than the caller's ``max_age``. Everything at and
    beyond it is dropped -- dropping outward-only, because a stale level 2 says
    nothing good about level 3 behind it."""


@dataclass(frozen=True)
class DepthLevel:
    """One resting level, with the provenance of both of its numbers.

    ``price`` and ``size`` come from two different tables that agree on an
    instant only 81-99.8 % of the time (measured per ticker; see the module
    docstring), so a single ``as_of`` for the level would be a lie about one of
    them. Both are carried.

    ``size`` is ``None`` where the size stream has no row for this level at or
    before ``ts`` -- either because the window carries no sizes at all (HTV in
    ``quote_*``) or because this level has not been sized yet today. Never 0:
    the extract contains no zero-quantity row (minimum quantity 100 in
    ``local_quote``, 1 in ``quote``), and defaulting an unknown to zero would
    turn our ignorance into a definite no-fill.
    """

    depth: int
    price: Decimal
    size: Optional[int]
    price_as_of: datetime
    size_as_of: Optional[datetime]
    ts: datetime
    """The instant the book was requested for. Ages are relative to this."""

    @property
    def price_age(self) -> timedelta:
        return self.ts - self.price_as_of

    @property
    def size_age(self) -> Optional[timedelta]:
        if self.size_as_of is None:
            return None
        return self.ts - self.size_as_of

    @property
    def age(self) -> timedelta:
        """The level's honest age: the older of its two observations.

        Restrictive by construction. A level whose price was refreshed one
        second ago but whose size is four minutes old is a four-minute-old
        level, because a sweep consumes the size and it is the size that may
        have gone.
        """
        size_age = self.size_age
        if size_age is None:
            return self.price_age
        return max(self.price_age, size_age)

    @property
    def sizes_lag_price(self) -> bool:
        """Whether the size was observed strictly before the price.

        This is the visible face of measured property 4: a price row without a
        same-instant size row leaves the previous price's size attached to the
        new price. It cannot be corrected from the data, only flagged.
        """
        return self.size_as_of is not None and self.size_as_of < self.price_as_of

    def to_book_level(self) -> BookLevel:
        """The ``protocol.BookLevel`` view. **Lossy** -- both ages are lost."""
        return BookLevel(price=self.price, size=self.size)


@dataclass(frozen=True)
class DepthSide:
    """One side of a reconstructed book, and the age of what it is made of."""

    side: Side
    availability: SideAvailability
    levels: Tuple[DepthLevel, ...] = ()
    truncation: Truncation = Truncation.NONE
    truncated_at_depth: Optional[int] = None
    """The first depth that was dropped, or ``None`` if nothing was."""
    observed_depths: Tuple[int, ...] = ()
    """Every depth with *some* observation at or before ``ts``, before
    truncation. Compare against ``[l.depth for l in levels]`` to see what a
    ladder gap cost."""
    ts: Optional[datetime] = None

    def __post_init__(self):
        # The invariant the whole type exists to hold: OBSERVED is exactly the
        # state in which there is a touch. Everything else serves no levels,
        # and a caller may therefore read `availability` alone.
        observed = self.availability is SideAvailability.OBSERVED
        if observed != bool(self.levels):
            raise ValueError(
                f'DepthSide invariant broken: availability='
                f'{self.availability.value} with {len(self.levels)} levels; '
                f'OBSERVED means a level-1 price is known and nothing else does'
            )

    @property
    def best(self) -> Optional[DepthLevel]:
        """The touch, or ``None`` when the side is not OBSERVED."""
        return self.levels[0] if self.levels else None

    @property
    def as_of(self) -> Optional[datetime]:
        """The **freshest** observation the side is built from.

        This is the "when did this side last move, as far as we know" instant,
        and it is what :attr:`DepthBook.cross_side_skew` compares -- the brief's
        "a bid quoted 4 seconds ago and an ask quoted 40 seconds ago".
        """
        stamps = self._stamps()
        return max(stamps) if stamps else None

    @property
    def oldest_as_of(self) -> Optional[datetime]:
        """The **stalest** observation the side is built from."""
        stamps = self._stamps()
        return min(stamps) if stamps else None

    def _stamps(self) -> List[datetime]:
        out: List[datetime] = []
        for level in self.levels:
            out.append(level.price_as_of)
            if level.size_as_of is not None:
                out.append(level.size_as_of)
        return out

    @property
    def age(self) -> Optional[timedelta]:
        """The side's honest age: the age of its **oldest** ingredient.

        The restrictive reading. A side is not fresh because its touch is
        fresh; it is as old as the oldest thing a sweep would consume.
        """
        oldest = self.oldest_as_of
        return None if oldest is None or self.ts is None else self.ts - oldest

    @property
    def freshest_age(self) -> Optional[timedelta]:
        """Age of the newest ingredient. Reported alongside :attr:`age` so the
        *spread* between them is visible: a side with a 2-second touch and a
        20-minute level 3 is a specific, common shape in this corpus."""
        as_of = self.as_of
        return None if as_of is None or self.ts is None else self.ts - as_of

    @property
    def has_sizes(self) -> bool:
        """Whether **every** served level carries a size.

        All-or-nothing on purpose: a ladder sized at level 1 and unsized behind
        it cannot be swept past the touch, so partial sizing is not a partial
        capability, and ``BOOK_SIZE`` is named missing for the whole book.
        """
        return bool(self.levels) and all(l.size is not None for l in self.levels)

    @property
    def total_size(self) -> Optional[int]:
        """Shares visible across the served levels, or ``None`` if any level is
        unsized. Never a partial sum -- a partial sum of a ladder understates
        or overstates depending on which level is missing, and either way it is
        a number nobody measured."""
        if not self.has_sizes:
            return None
        return sum(l.size for l in self.levels)

    def to_levels(self) -> Tuple[BookLevel, ...]:
        return tuple(level.to_book_level() for level in self.levels)


@dataclass(frozen=True)
class DepthBook:
    """A book reconstructed as of an instant, with its ignorance attached.

    Returned for **every** query, including ones the corpus cannot answer.
    ``DataHubSource.interval`` returns ``None`` for an absent bar because the
    session can then synthesise one; there is nothing to synthesise a book
    from, and a ``None`` here would leave the caller unable to distinguish "no
    ask side yet", "this window has no sizes" and "wrong ticker".
    """

    ticker: str
    ts: datetime
    bid: DepthSide
    ask: DepthSide
    resolution: Resolution = Resolution.TICK
    withheld: FrozenSet[DataField] = frozenset()
    """Fields this source cannot answer, stamped from
    :data:`DepthSource.WITHHELD` plus whatever *this book* lacks -- ``BOOK``
    when neither side has a touch, ``BOOK_SIZE`` when any served level is
    unsized. The per-book part is what distinguishes a source that never has
    sizes from a window that does not."""
    table_prefix: str = ''
    """Which observer this came from. Two prefixes in the extract hold HTV Nov
    2022 with different lineage and different size coverage; a book that did
    not say which one it came from could not be reproduced."""

    # -- the two-sided facts ------------------------------------------------

    @property
    def cross_side_skew(self) -> Optional[timedelta]:
        """``|bid.as_of - ask.as_of|``, or ``None`` unless both are OBSERVED.

        The headline weakness number. Measured on FPT 2022-11-09: median
        20.7 s, p90 216.6 s, max 932.6 s. Always non-negative -- which side is
        stale is read off ``bid.as_of`` and ``ask.as_of`` directly.
        """
        if self.bid.as_of is None or self.ask.as_of is None:
            return None
        return abs(self.bid.as_of - self.ask.as_of)

    @property
    def stalest_age(self) -> Optional[timedelta]:
        """The oldest ingredient anywhere in the book."""
        ages = [side.age for side in (self.bid, self.ask) if side.age is not None]
        return max(ages) if ages else None

    @property
    def is_two_sided(self) -> bool:
        return (self.bid.availability is SideAvailability.OBSERVED
                and self.ask.availability is SideAvailability.OBSERVED)

    @property
    def spread(self) -> Optional[Decimal]:
        if not self.is_two_sided:
            return None
        return self.ask.best.price - self.bid.best.price

    @property
    def is_crossed(self) -> bool:
        """Best bid strictly **above** best ask -- a book that never existed.

        Not a market state: it is the direct symptom of the cross-side skew
        above, an arbitrage the exchange would have matched away in the instant
        it appeared. Measured 4 in 7,022 continuous-session instants and 15 in
        26 opening-auction instants on FPT Nov 2022. A sweep should refuse a
        crossed book rather than fill through it.

        **Not** ``LockEvidence`` and not a band lock. This is about the two
        sides of the ladder relative to each other, nothing to do with the
        ceiling or the floor.
        """
        return self.is_two_sided and self.bid.best.price > self.ask.best.price

    @property
    def is_touching(self) -> bool:
        """Best bid exactly **equal** to best ask. Also not a resting state a
        continuous market holds, but a weaker signal than :attr:`is_crossed`:
        it is what a book looks like in the instant before a match, and one of
        the two sides may simply be stale by a fraction of a second."""
        return self.is_two_sided and self.bid.best.price == self.ask.best.price

    @property
    def is_reconstructable(self) -> bool:
        """Whether the two-sided book is coherent enough to sweep into."""
        return self.is_two_sided and not self.is_crossed and not self.is_touching

    # -- the contract -------------------------------------------------------

    def side(self, resting: Side) -> DepthSide:
        return self.bid if resting is Side.BUY else self.ask

    def resting_side_for(self, aggressor: Side) -> DepthSide:
        """The side an aggressor sweeps into: a BUY takes asks, a SELL bids."""
        if aggressor is Side.BUY:
            return self.ask
        if aggressor is Side.SELL:
            return self.bid
        raise ValueError(
            f'{aggressor} has no resting side; a sweep is one-sided'
        )

    def missing_for(self, aggressor: Side) -> FrozenSet[DataField]:
        """The contract fields an aggressor on ``side`` would find missing.

        The seam a fill policy reads. A BUY only needs the ask side, so a book
        with an ABSENT bid is a perfectly good book to buy into and naming
        ``BOOK`` missing for it would produce an INDETERMINATE the data does
        not require. Sizes are named per **resting side** for the same reason.
        """
        resting = self.resting_side_for(aggressor)
        missing = set(self.withheld)
        missing.discard(DataField.BOOK)
        missing.discard(DataField.BOOK_SIZE)
        if resting.availability is not SideAvailability.OBSERVED:
            missing.add(DataField.BOOK)
        elif not resting.has_sizes:
            missing.add(DataField.BOOK_SIZE)
        return frozenset(missing)

    def to_order_book(self) -> OrderBook:
        """The ``protocol.OrderBook`` view. **Lossy, and lossy in one specific
        way**: ``OrderBook`` has a single ``as_of`` and this book has up to
        twelve observation instants behind it.

        ``as_of`` is set to the **oldest** contributing observation, not to
        ``ts``. That is the restrictive collapse -- "this book is no fresher
        than this instant" is true, whereas ``as_of=ts`` asserts a currency
        nothing in the corpus supports. It also makes the field mean what
        ``adapters/tick.py``'s own module docstring already claims for it
        ("the fill origin is recorded on ``OrderBook.as_of``") while that
        module in fact stamps ``ts``.

        An ABSENT side and an empty one collapse here -- both become ``()`` --
        which is exactly why :class:`DepthBook` is the type to pass around and
        this method is a bridge for code that predates it.
        """
        stamps = [s for s in (self.bid.oldest_as_of, self.ask.oldest_as_of)
                  if s is not None]
        return OrderBook(
            bids=self.bid.to_levels(),
            asks=self.ask.to_levels(),
            as_of=min(stamps) if stamps else None,
        )


@dataclass(frozen=True)
class DepthCoverage:
    """What one ticker-day actually holds, answerable before a run starts.

    Requirement: a source that cannot serve depth must say so rather than serve
    an empty ladder that reads as "no liquidity". This is how it says so.
    """

    ticker: str
    day: date
    table_prefix: str
    bid_price_rows: int = 0
    ask_price_rows: int = 0
    bid_size_rows: int = 0
    ask_size_rows: int = 0
    ticker_in_source: bool = False
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None

    @property
    def serves_prices(self) -> bool:
        return bool(self.bid_price_rows or self.ask_price_rows)

    @property
    def serves_depth(self) -> bool:
        """Whether *sizes* exist for this ticker-day.

        ``False`` for HTV Nov 2022 read through the ``quote`` prefix, which has
        564 bid-price rows and **zero** bid-size rows. A run that needs depth
        must stop here rather than sweep a ladder of ``None``.
        """
        return bool(self.bid_size_rows or self.ask_size_rows)

    @property
    def withheld(self) -> FrozenSet[DataField]:
        missing = set(DepthSource.WITHHELD)
        if not self.serves_prices:
            missing.add(DataField.BOOK)
        if not self.serves_depth:
            missing.add(DataField.BOOK_SIZE)
        return frozenset(missing)


@dataclass
class _Stream:
    """One table, indexed for a per-level as-of lookup.

    ``stamps[d]`` is ascending and ``values[d]`` is parallel to it, so a level
    lookup is a bisect. Per level and not per instant, because measured
    property 3 says these are change streams: the latest instant's rows are the
    latest *changes*, not the latest book.
    """

    stamps: Dict[int, List[datetime]] = field(default_factory=dict)
    values: Dict[int, List] = field(default_factory=dict)
    rows: int = 0

    def at(self, depth: int, ts: datetime):
        stamps = self.stamps.get(depth)
        if not stamps:
            return None
        i = bisect.bisect_right(stamps, ts)
        if i == 0:
            return None
        return self.values[depth][i - 1], stamps[i - 1]

    def instants(self) -> List[datetime]:
        out: List[datetime] = []
        for stamps in self.stamps.values():
            out.extend(stamps)
        return out


@dataclass
class _DayTape:
    bid_price: _Stream
    ask_price: _Stream
    bid_size: _Stream
    ask_size: _Stream


class DepthSource:
    """An order-book source over a DuckDB-over-Parquet root.

    One instance reads **one table prefix**; see the module docstring on why
    ``local_quote_*`` and ``quote_*`` are not merged.

    Not a ``MarketDataSource``: it answers no ``state_at``/``states`` and knows
    nothing about bands, the last price or the session phase. Those come from
    ``DataHubSource``, and this composes beside it rather than reimplementing
    a second, drifting copy of the band logic.
    """

    #: Book-only. ``Resolution.DAILY`` is not here and never will be: a daily
    #: bar has no instant to be as-of, and forward-filling a ladder to
    #: "midnight" would answer with the previous session's book.
    SERVES_RESOLUTIONS: ClassVar[FrozenSet[Resolution]] = frozenset({
        Resolution.TICK,
    })

    #: What this source can answer. ``BOOK_SIZE`` is **not** listed as
    #: permanently withheld and is not promised here either: it is served where
    #: the rows exist and named on the individual book where they do not,
    #: mirroring how ``DataHubSource`` handles ``VOLUME``. Ask
    #: :meth:`coverage` for a ticker-day answer.
    SERVES: ClassVar[FrozenSet[DataField]] = frozenset({
        DataField.BOOK, DataField.BOOK_SIZE,
    })

    #: What it cannot, stamped onto every book it returns. This is a book
    #: source and nothing else -- it holds no bands, no last price, no volume
    #: and no phase, so a policy needing one of those must get it from the
    #: daily source and will name the field if it cannot.
    WITHHELD: ClassVar[FrozenSet[DataField]] = frozenset({
        DataField.LAST, DataField.OPEN, DataField.HIGH, DataField.LOW,
        DataField.CLOSE, DataField.VOLUME, DataField.REFERENCE,
        DataField.CEILING, DataField.FLOOR, DataField.SESSION_PHASE,
        DataField.FOREIGN_ROOM, DataField.SETTLEMENT_PRICE,
    })

    #: The two observers in the dev extract.
    LOCAL_PREFIX: ClassVar[str] = 'local_quote'
    REMOTE_PREFIX: ClassVar[str] = 'quote'

    def __init__(self, root: Union[str, Path], *,
                 table_prefix: str = 'local_quote',
                 max_depth: int = MAX_DEPTH):
        if not 1 <= max_depth <= MAX_DEPTH:
            raise ValueError(
                f'max_depth must be 1..{MAX_DEPTH}; the extract carries no '
                f'level beyond {MAX_DEPTH} for any ticker and this source '
                f'does not extrapolate one'
            )
        self.root = Path(root)
        self.table_prefix = table_prefix
        self.max_depth = max_depth
        self._conn = duckdb.connect()
        self._tapes: Dict[Tuple[str, date], _DayTape] = {}
        self._tickers: Optional[FrozenSet[str]] = None
        self._windows: Dict[str, Optional[Tuple[datetime, datetime]]] = {}

    @classmethod
    def for_root(cls, root: Union[str, Path], **kwargs) -> 'DepthSource':
        return cls(root, **kwargs)

    # -- tables ------------------------------------------------------------

    def _reader(self, suffix: str) -> Optional[str]:
        path = self.root / f'{self.table_prefix}_{suffix}.parquet'
        if path.exists():
            return f"read_parquet('{path}')"
        csv = self.root / f'{self.table_prefix}_{suffix}.csv'
        return f"read_csv_auto('{csv}')" if csv.exists() else None

    @property
    def tables(self) -> Tuple[str, ...]:
        """The four tables this prefix resolves, for a caller checking a root
        before it builds anything."""
        return tuple(s for s in ('bidprice', 'askprice', 'bidsize', 'asksize')
                     if self._reader(s) is not None)

    def tickers(self) -> FrozenSet[str]:
        """Every ticker with a price row under this prefix."""
        if self._tickers is None:
            found = set()
            for suffix in ('bidprice', 'askprice'):
                reader = self._reader(suffix)
                if reader is None:
                    continue
                found.update(row[0] for row in self._conn.execute(
                    f'SELECT DISTINCT tickersymbol FROM {reader}').fetchall())
            self._tickers = frozenset(found)
        return self._tickers

    def window(self, ticker: str) -> Optional[Tuple[datetime, datetime]]:
        """``(first, last)`` price observation for a ticker, or ``None``.

        Used to separate :attr:`SideAvailability.OUT_OF_WINDOW` from
        :attr:`SideAvailability.ABSENT` -- a coverage error from a market fact.
        """
        if ticker not in self._windows:
            bounds: List[Tuple[datetime, datetime]] = []
            for suffix in ('bidprice', 'askprice'):
                reader = self._reader(suffix)
                if reader is None:
                    continue
                row = self._conn.execute(
                    f'SELECT min(datetime), max(datetime) FROM {reader} '
                    f'WHERE tickersymbol = ?', [ticker]).fetchone()
                if row and row[0] is not None:
                    bounds.append((row[0], row[1]))
            self._windows[ticker] = (
                (min(b[0] for b in bounds), max(b[1] for b in bounds))
                if bounds else None)
        return self._windows[ticker]

    # -- coverage ----------------------------------------------------------

    def coverage(self, ticker: str, day: Union[date, datetime]
                 ) -> DepthCoverage:
        """Row counts for one ticker-day. Cheap; four aggregate queries."""
        day = day.date() if isinstance(day, datetime) else day
        counts = {}
        for suffix in ('bidprice', 'askprice', 'bidsize', 'asksize'):
            reader = self._reader(suffix)
            if reader is None:
                counts[suffix] = 0
                continue
            counts[suffix] = self._conn.execute(
                f'SELECT count(*) FROM {reader} WHERE tickersymbol = ? '
                f'AND datetime >= ? AND datetime < ? '
                f'AND depth >= 1 AND depth <= ?',
                [ticker, str(day), str(day + timedelta(days=1)),
                 self.max_depth]).fetchone()[0]
        window = self.window(ticker)
        return DepthCoverage(
            ticker=ticker, day=day, table_prefix=self.table_prefix,
            bid_price_rows=counts['bidprice'],
            ask_price_rows=counts['askprice'],
            bid_size_rows=counts['bidsize'],
            ask_size_rows=counts['asksize'],
            ticker_in_source=ticker in self.tickers(),
            first_ts=window[0] if window else None,
            last_ts=window[1] if window else None,
        )

    # -- reconstruction ----------------------------------------------------

    def _tape(self, ticker: str, day: date) -> _DayTape:
        """One day of change streams, indexed per level.

        Scoped to a calendar day because forward fill must not cross one: HSX
        cancels unfilled orders at the close, so yesterday's ladder is not
        evidence about today's open. Cached, so stepping through a session is
        four queries, not four per instant.
        """
        key = (ticker, day)
        if key not in self._tapes:
            self._tapes[key] = _DayTape(
                bid_price=self._load(ticker, day, 'bidprice', 'price'),
                ask_price=self._load(ticker, day, 'askprice', 'price'),
                bid_size=self._load(ticker, day, 'bidsize', 'quantity'),
                ask_size=self._load(ticker, day, 'asksize', 'quantity'),
            )
        return self._tapes[key]

    def _load(self, ticker: str, day: date, suffix: str,
              column: str) -> _Stream:
        stream = _Stream()
        reader = self._reader(suffix)
        if reader is None:
            return stream
        rows = self._conn.execute(
            f'SELECT datetime, depth, {column} FROM {reader} '
            f'WHERE tickersymbol = ? AND datetime >= ? AND datetime < ? '
            f'AND depth >= 1 AND depth <= ? ORDER BY datetime, depth',
            [ticker, str(day), str(day + timedelta(days=1)),
             self.max_depth]).fetchall()
        for ts, depth, value in rows:
            depth = int(depth)
            stream.stamps.setdefault(depth, []).append(ts)
            # Prices arrive as DECIMAL(20,6) and stay Decimal -- never float,
            # and never re-parsed through str(), which would be a second
            # rounding this module has no authority to perform.
            stream.values.setdefault(depth, []).append(
                int(value) if column == 'quantity' else value)
            stream.rows += 1
        return stream

    def book_at(self, ticker: str, ts: datetime, *,
                resolution: Resolution = Resolution.TICK,
                max_age: Optional[timedelta] = None) -> DepthBook:
        """The book as of ``ts``, always returned, never ``None``.

        Per side, per level: the latest price row at or before ``ts`` and the
        latest size row at or before ``ts``, on ``ts``'s own day. The two sides
        are never equality-joined -- measured, only 53 of 203 instants coincide
        on FPT 2022-11-09 -- so each side is filled independently and the skew
        between them is reported rather than hidden.

        ``max_age`` drops levels older than the budget, outward from the first
        offender, and records :attr:`Truncation.MAX_AGE`. Dropping is the
        restrictive direction: less depth means a sweep runs out sooner and
        returns INDETERMINATE for the remainder, which costs an opportunity
        rather than money. Note the lunch break makes wall-clock age a poor
        proxy for staleness across 11:30-13:00; the largest per-level gap
        measured in this extract is 5,412 s and it is the break.

        Raises:
            ValueError: on a resolution this source does not serve. A book is
                an instantaneous object and a daily request is an integration
                bug, not an absence -- answering it with a forward-filled
                ladder at midnight would serve the previous session's book.
        """
        if resolution not in self.SERVES_RESOLUTIONS:
            raise ValueError(
                f'DepthSource serves {sorted(r.value for r in self.SERVES_RESOLUTIONS)} '
                f'only, got {resolution}; a reconstructed book is as-of an '
                f'instant and a daily bar has no instant to be as-of'
            )
        if max_age is not None and max_age < _ZERO:
            raise ValueError(f'max_age must be non-negative, got {max_age}')

        tape = self._tape(ticker, ts.date())
        bid = self._side(tape, ticker, Side.BUY, ts, max_age)
        ask = self._side(tape, ticker, Side.SELL, ts, max_age)

        withheld = set(self.WITHHELD)
        if (bid.availability is not SideAvailability.OBSERVED
                and ask.availability is not SideAvailability.OBSERVED):
            withheld.add(DataField.BOOK)
        sized = [s for s in (bid, ask)
                 if s.availability is SideAvailability.OBSERVED]
        if not sized or not all(s.has_sizes for s in sized):
            withheld.add(DataField.BOOK_SIZE)

        return DepthBook(
            ticker=ticker, ts=ts, bid=bid, ask=ask,
            resolution=Resolution.TICK,
            withheld=frozenset(withheld),
            table_prefix=self.table_prefix,
        )

    def _side(self, tape: _DayTape, ticker: str, side: Side, ts: datetime,
              max_age: Optional[timedelta]) -> DepthSide:
        price = tape.bid_price if side is Side.BUY else tape.ask_price
        size = tape.bid_size if side is Side.BUY else tape.ask_size

        # Every depth with some observation at or before ``ts``, computed
        # first and independently of what we end up serving, so a hole is a
        # measured fact rather than an inference from where we stopped.
        observed = tuple(d for d in range(1, self.max_depth + 1)
                         if price.at(d, ts) is not None)

        levels: List[DepthLevel] = []
        truncated_at: Optional[int] = None
        aged_out = False

        for depth in range(1, self.max_depth + 1):
            found = price.at(depth, ts)
            if found is None:
                truncated_at = depth
                break
            price_value, price_as_of = found
            sized = size.at(depth, ts)
            level = DepthLevel(
                depth=depth,
                price=price_value,
                size=None if sized is None else sized[0],
                price_as_of=price_as_of,
                size_as_of=None if sized is None else sized[1],
                ts=ts,
            )
            if max_age is not None and level.age > max_age:
                truncated_at, aged_out = depth, True
                break
            levels.append(level)

        if truncated_at is None:
            truncation = Truncation.NONE
        elif aged_out:
            truncation = Truncation.MAX_AGE
        elif any(d > truncated_at for d in observed):
            truncation = Truncation.LADDER_GAP
        else:
            truncation = Truncation.NO_OBSERVATION

        if levels:
            availability = SideAvailability.OBSERVED
        elif ticker not in self.tickers():
            availability, truncation, truncated_at = (
                SideAvailability.UNSERVED, Truncation.NONE, None)
        else:
            window = self.window(ticker)
            if window is not None and not (
                    window[0].date() <= ts.date() <= window[1].date()):
                availability, truncation, truncated_at = (
                    SideAvailability.OUT_OF_WINDOW, Truncation.NONE, None)
            else:
                availability = SideAvailability.ABSENT

        return DepthSide(
            side=side, availability=availability, levels=tuple(levels),
            truncation=truncation, truncated_at_depth=truncated_at,
            observed_depths=observed, ts=ts,
        )

    # -- iteration ---------------------------------------------------------

    def instants(self, ticker: str, start: datetime,
                 end: datetime) -> List[datetime]:
        """Every instant in ``[start, end)`` at which either side changed.

        The union across all four tables, deduplicated and sorted. This is the
        event clock a sweep should step on: between two of these instants the
        reconstructed book is by definition unchanged, so sampling more finely
        produces identical books and sampling on a fixed grid steps over
        changes.

        ``end`` is exclusive, matching ``MarketDataSource.states``.
        """
        if not start < end:
            raise ValueError(f'[{start}, {end}) is empty or inverted')
        out: set = set()
        day = start.date()
        while day <= end.date():
            tape = self._tape(ticker, day)
            for stream in (tape.bid_price, tape.ask_price,
                           tape.bid_size, tape.ask_size):
                out.update(stream.instants())
            day += timedelta(days=1)
        return sorted(t for t in out if start <= t < end)

    def books(self, ticker: str, start: datetime, end: datetime, *,
              max_age: Optional[timedelta] = None) -> Iterator[DepthBook]:
        """A book at every instant either side changed over ``[start, end)``."""
        for ts in self.instants(ticker, start, end):
            yield self.book_at(ticker, ts, max_age=max_age)
