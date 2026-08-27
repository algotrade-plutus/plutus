"""The sweep: a marketable order walking a real ladder, level by level.

Every fill policy in ``fills.py`` answers one question -- *did the market trade
at or through my price* -- and then fills the whole order at one price. That is
not a simulation of a market: no order in it ever consumes a level, no order
ever produces two fills at two prices, and the depth an order would have eaten
is never consulted because ``BookLevel.size`` was ``None`` on every corpus this
package could read. ``adapters/depth.py`` changed the second half of that
sentence. This module is the first half.

The mechanic, and why it is a sweep rather than a rest
------------------------------------------------------------------------
In Vietnam a limit order priced *through* the touch is **marketable**: it does
not join the queue at its own price, it takes the resting side outward until it
is filled or runs out of book. The author, correcting an earlier
misdescription of this module's subject:

    "In the 09:30 book normal --> submit Buy FPT @ ceiling --> Accepted, but
    not rests. The rule of Vietnamese market in this case it fill at the best
    ask possible at that time. If the volume is too big and the ask 1 get fill
    all, and it goes to ask 2 to fill, and so on."

So::

    BUY  is marketable iff limit >= best ask
    SELL is marketable iff limit <= best bid

and the walk takes ``min(remaining, size at level)`` at levels 1, 2, 3 --
**each tranche priced at the resting level's own price**, never at the
aggressor's limit and never at an average. That is not a modelling choice; it
is the rule ``fills.py`` already cites for the single-price case (rulebook 2.4,
QD 352 Dieu 6.3, confidence high: a trade happens at the *resting* order's
price). A single-price sweep would misprice every tranche past the touch, and
in the restrictive direction only by accident.

:class:`BookWalk` therefore carries a **tuple of tranches**, and the trade log
is the tranches. :class:`SweptFillDecision` exists because ``FillDecision``
carries one price and cannot represent this; see its docstring for the lossy
projection it makes for callers that predate depth, and for the one-line change
requested of ``exchange.py``.

Four terminations, and only one of them is a fill
------------------------------------------------------------------------

==============================  ==========================================
filled inside the ladder        ``FILLED``    -> a definite full fill
next level beyond the limit     ``LIMIT``     -> partial; remainder **rests**
ladder exhausted at level 3     ``EXHAUSTED`` -> partial; remainder
                                **INDETERMINATE** -- depth is not
                                extrapolated (confirmed by the author)
no level at or through it       ``LIMIT`` with no tranches -> **NO FILL**
==============================  ==========================================

The last row is the **band lock**, and it needs no rule of its own: a book
locked at the ceiling has no offer at or below the ceiling, a marketable buy
finds nothing to take, and the walk returns no tranches. Item 3 of the brief
asked this to be verified rather than asserted, and verifying it produced a
finding that is the most important measured statement in this module -- see
"What a locked book actually looks like" below.

Queue position is the user's choice, and it is an axis
------------------------------------------------------------------------
A level displays N shares. How many of them sit *ahead of us* is not in this
corpus and is not in any corpus with no order ids. Rather than pick one answer,
:class:`QueuePolicy` is a seam with three shipped implementations
(:class:`OptimisticQueue`, :class:`ConservativeQueue`,
:class:`ProbabilisticQueue`), the caller selects, and the choice is recorded in
the policy signature stamped on every decision. This is the same shape
``fills.py`` uses for the soft/hard/probabilistic axis and for the same reason:
the assumption must travel with the result.

None of that shape is novel. NautilusTrader's ``FillModel`` ships a seeded
``prob_fill_on_limit``; Forex Strategy Builder shipped an
``InterpolationMethod`` family in 2011. What is here is a queue axis applied to
a *reconstructed Vietnamese ladder*, with the reconstruction's own ignorance
carried through to the answer.

The four refusals, which are not no-fills
------------------------------------------------------------------------
A reconstructed book can be wrong, and the ways it is wrong are measurable.
Each one returns ``INDETERMINATE`` naming a field, never a confident no-fill:
a confident no-fill silently suppresses trades a strategy should have made, and
fails in the opposite direction to a confident fill rather than in a safer one.

1. **The resting side is not observed** -- ``ABSENT``/``UNSERVED``/
   ``OUT_OF_WINDOW``, or a ``LADDER_GAP`` that ate the touch. ``BOOK``.
2. **The resting side carries no sizes.** A ladder of prices with no
   quantities cannot be walked at all; assuming unbounded size at the touch is
   a market-impact assumption wearing a hat. ``BOOK_SIZE``.
3. **The book is crossed.** Best bid above best ask is not a market state, it
   is the direct symptom of the per-side as-of join (``adapters/depth.py``
   measures 4 crossed books in 7,022 continuous-session instants on FPT, and
   15 of 26 inside the opening auction). ``BOOK``.
4. **The resting side is staler than the caller's budget.** ``max_staleness``
   is a **required** argument for exactly the reason ``max_participation`` is
   required on ``ProbabilisticFillPolicy``: it changes which decisions are
   answerable, so the caller must make it rather than inherit it. ``None`` is
   accepted and means *any age*, and it is recorded in the signature so a run
   that took that risk says so.

Two more refusals come from the ladder's own shape, and both were measured
here rather than assumed. See :class:`LadderFault`.

What a locked book actually looks like -- the finding
------------------------------------------------------------------------
The expectation was that a ceiling-locked book has an empty ask side, so a
marketable buy finds nothing and the band lock falls out as a ``NO_FILL``.
Measured on HPG, 2025-04-10 (the ``quote`` prefix; a limit-up session), best
bid at the 22.750 ceiling on **14,775 of 16,707** reconstructed books:

* the ask side is ``OBSERVED`` on **all 14,775**; it is never absent;
* **all 14,775 have an ask at or below the ceiling**, so a naive walk fills
  every single one of them;
* **all 14,775 are crossed** -- the "ask" is 19.850, the day's *floor*;
* the ask side's age over those books is median **5,201 s**, min **904.5 s**,
  max **20,701 s**. The touch that a naive sweep would have bought 29,800
  shares of at 19.850, in a market locked bid at 22.750, was last quoted
  before the open and never updated again.

That is the whole case for this module's refusals in one instrument-day. The
corpus has **no deletion record** (``adapters/depth.py``): a ladder that empties
out emits nothing, so a locked book does not present as empty -- it presents as
a stale ghost that reads as free money. The band lock does fall out of the walk
with no rule of its own, but on *this* corpus it falls out through the crossed
and stale refusals, as ``INDETERMINATE``, and not as the ``NO_FILL`` the brief
predicted. The ``NO_FILL`` shape is real and is reachable (an ask ladder that
is coherent and simply starts above our limit); it is not what a real Vietnamese
lock looks like in this data. Both are tested.

The asymmetry this closes
------------------------------------------------------------------------
``exchanges/equity.py``'s ``BAND_LOCK`` rule refuses a marketable order **at
entry** when ``state.locked_side`` matches its side. Nothing at *fill* time
read that field, so the identical order, already resting, filled at the same
instant. :meth:`BookWalkFillPolicy._continuous` reads it -- and reads it in one
direction only: the lock may **refuse** a fill, it may never authorise one. See
that method.

Composition with the participation cap
------------------------------------------------------------------------
The cap and the walk bound different things and both hold. See
:meth:`BookWalkFillPolicy._bounded`, which also states why the order of
application is forced rather than chosen.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import Enum
from typing import (Callable, ClassVar, FrozenSet, Iterable, List, Optional,
                    Protocol, Tuple, runtime_checkable)

from plutus.core.order import Side
from plutus.market.adapters.depth import (MAX_DEPTH, DepthBook, DepthLevel,
                                          SideAvailability)
from plutus.market.protocol import LockEvidence, Resolution
from plutus.market.session.fills import (BOOK_WALK_KIND, NO_MARKET_IMPACT,
                                         POLICY_SEPARATOR, FillPolicy,
                                         _CappedFillPolicy, fill_draw,
                                         floor_to_lot, participation_cap)
from plutus.market.session.types import (DataField, FillDecision, FillEvidence,
                                         FillOutcome, MarketInterval,
                                         OrderRecord, TimeInForce)

__all__ = [
    'SWEEP_IS_CONTINUOUS_ONLY', 'DEPTH_IS_NOT_EXTRAPOLATED',
    'QUEUE_DRAW_DOMAIN',
    'Bound', 'LadderFault', 'Remainder', 'SweepStop',
    'QueueClaim', 'QueuePolicy', 'QueueRequest', 'PrintsThrough',
    'OptimisticQueue', 'ConservativeQueue', 'ProbabilisticQueue',
    'Tranche', 'BookWalk', 'walk_book', 'queue_draw_key',
    'BookProvider', 'BookWalkFillPolicy', 'SweptFillDecision',
    'sweep_ignorance',
]


#: Why ``_auction`` never sweeps, stated once and importable.
#:
#: ATO and ATC cross at **one price for everyone**; there is no resting
#: two-sided book to walk and no price-time question to answer. The corpus
#: agrees independently and loudly: ``adapters/depth.py`` measures **15 of 26**
#: reconstructed opening-auction books on FPT Nov 2022 as *crossed*, against 4
#: in 7,022 in the continuous session. Sweeping an auction here would be
#: filling arbitrages that the reconstruction invented.
SWEEP_IS_CONTINUOUS_ONLY = (
    'A sweep is a continuous-session mechanic. ATO/ATC match at a single '
    'auction clearing price, and the reconstructed book is measurably unsound '
    'inside them (15 of 26 opening-auction books crossed, against 4 of 7,022 '
    'in continuous session). This policy does not walk an auction.'
)

#: The corpus carries three levels. A sweep that consumes level 3 and still has
#: quantity left is **INDETERMINATE for the remainder** -- there is no level 4
#: anywhere in the extract, and inventing one would be a market-impact
#: assumption in the permissive direction. Confirmed by the author.
DEPTH_IS_NOT_EXTRAPOLATED = (
    'Depth is not extrapolated: the corpus carries three levels, so an order '
    'that exhausts level 3 is INDETERMINATE for whatever is left of it, never '
    'filled against an invented level 4.'
)

#: Domain tag opening every :func:`queue_draw_key`. It makes a queue draw
#: structurally incapable of colliding with ``fills.draw_key``: that function's
#: first field is an order id and its third is an ISO timestamp, where this
#: one's first field is this literal and its third is a side token.
QUEUE_DRAW_DOMAIN = 'book_walk.queue'


# --------------------------------------------------------------------------
# What a walk can find, and where it can stop
# --------------------------------------------------------------------------

class LadderFault(str, Enum):
    """A served ladder that cannot be a resting book. Measured, not feared.

    A real exchange ladder is strictly monotone outward: ask 1 < ask 2 < ask 3.
    A reconstructed one need not be, because ``adapters/depth.py`` joins **per
    (side, level)** -- each level carries its own age, so a stale level 1 can
    sit outside a fresh level 2. Both faults below are counted in the extract
    and neither is rare enough to ignore.

    Where a fault is found the ladder is **truncated at it** rather than
    repaired or refused whole: everything from the offending level outward is
    dropped, the levels in front of it are still swept, and the remainder is
    ``INDETERMINATE``. That is the restrictive direction twice over -- less
    depth means the sweep runs out sooner, and the kept touch is the *worse*
    price of the two in an inversion.
    """

    NONE = 'none'

    INVERTED = 'inverted'
    """A level priced **better** than the level in front of it.

    Measured share of served ladders of two or more levels: FPT 2022-11-09
    **1.52 %**, HPG the same day **2.17 %**, HPG 2025-04-10 **1.41 %**. A
    worked instance -- FPT ask side at 09:00:10.126552: level 1 is 74.900 and
    **1.4 s** old, a leftover from the auction, while levels 2 and 3 are 73.400
    and 73.500 and **0.0 s** old. Sweeping in ladder order would buy 200 at
    74.900 and then 5,600 at 73.400, which is not a thing that can happen.
    Truncating keeps the 200 at 74.900: fewer shares, at the worse price.
    """

    DUPLICATE_PRICE = 'duplicate_price'
    """Two adjacent levels quoting the **same** price.

    Impossible in a price-ranked ladder, so its presence is evidence that the
    per-level as-of join has paired a stale row with a fresh one. Measured:
    FPT 2022-11-09 **1.16 %** of served ladders, HPG the same day 0.02 %, and
    HPG 2025-04-10 **53.39 %** -- that last being the limit-up session whose
    ask side is a frozen ghost, which is the same finding from another angle.
    Worked instance, FPT ask at 14:30:10.317628: level 1 is 74.100 for 100
    shares and **170 s** old, level 2 is 74.100 for 40,400 shares and **0.0 s**
    old. Consuming both would claim 40,500 shares at 74.100 when at most 40,400
    exist; truncating claims 100.
    """


class SweepStop(str, Enum):
    """Why the walk stopped. Every value maps to exactly one honest outcome."""

    FILLED = 'filled'
    """The order was filled inside the visible, trusted ladder."""

    LIMIT = 'limit'
    """The next level is priced beyond the limit. With tranches this is a
    partial whose remainder **rests**; with none it is a definite ``NO_FILL``
    -- the band lock, arrived at with no rule of its own."""

    EXHAUSTED = 'exhausted'
    """Every trusted level was consumed and quantity remains. The remainder is
    ``INDETERMINATE``: see :data:`DEPTH_IS_NOT_EXTRAPOLATED`."""

    LADDER_FAULT = 'ladder_fault'
    """The trusted prefix ended at a :class:`LadderFault` and quantity
    remains. Remainder ``INDETERMINATE`` -- the levels behind the fault exist,
    we simply cannot trust their order or their sizes."""

    QUEUE_BLOCKED = 'queue_blocked'
    """A queue policy granted **zero** shares at a level it could decide.
    The walk stops there rather than skipping outward: price-time priority
    means level 2 cannot be reached until level 1 is exhausted, so a level
    that yields us nothing yields us nothing behind it either. Definite under
    the declared queue assumption; the remainder rests."""

    QUEUE_UNKNOWN = 'queue_unknown'
    """A queue policy could not decide a level from the data it has -- the
    ``ConservativeQueue`` case, which needs sized subsequent prints this corpus
    does not carry. Remainder ``INDETERMINATE``, naming ``VOLUME``."""

    NO_BOOK = 'no_book'
    """The resting side is not ``OBSERVED``. ``BOOK``."""

    NO_SIZES = 'no_sizes'
    """The resting side is priced but unsized. ``BOOK_SIZE``."""

    CROSSED = 'crossed'
    """Best bid above best ask: a book that never existed. ``BOOK``."""

    STALE = 'stale'
    """The resting side is older than the caller's ``max_staleness``.
    ``BOOK``."""

    CAPPED = 'capped'
    """Set by :meth:`BookWalk.bounded_to` when the participation cap or the
    round lot, rather than the ladder, decided the quantity. It replaces
    whatever the walk's own stop was, and it **removes** any depth ignorance:
    an order capped short of the ladder never reached the end of it."""


class Remainder(str, Enum):
    """What is true of the part of the order that did not fill.

    The distinction ``FillDecision`` cannot carry and this module refuses to
    lose: an order that stopped at its limit knows nothing more was available
    at its price, and an order that ate level 3 knows only that it cannot see
    any further.
    """

    NONE = 'none'
    """Nothing remains."""

    RESTS = 'rests'
    """A definite non-fill for this interval, under this walk's declared
    assumptions. The remainder stays live and is re-evaluated next interval."""

    INDETERMINATE = 'indeterminate'
    """The data cannot say whether this part would have filled. See
    :attr:`BookWalk.missing` for what would have decided it."""


class Bound(str, Enum):
    """Which constraint set the final quantity. Reported, never inferred."""

    WALK = 'walk'
    """Visible depth at prices through the limit, or the order's own size."""

    PARTICIPATION = 'participation'
    """``max_participation`` of the interval's observed volume."""

    ROUND_LOT = 'round_lot'
    """The dated trading unit floored the capped quantity."""


# --------------------------------------------------------------------------
# The queue axis
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class QueueRequest:
    """One level, and everything a queue policy may look at to price it.

    Deliberately does **not** carry the order's original quantity or anything
    about other orders in the run: a queue policy answers *how much of this
    level is ours*, and a draw that moved when an unrelated order was added to
    the run would make two runs incomparable for a reason that has nothing to
    do with what changed (``fills.fill_draw`` makes the same argument at
    length).
    """

    ticker: str
    ts: datetime
    """The instant the book was reconstructed for."""
    side: Side
    """The **aggressor's** side. A BUY takes asks."""
    order_id: str
    level: DepthLevel
    remaining: int
    """What is left of the order when it arrives at this level."""

    @property
    def displayed(self) -> int:
        """Shares shown at this level. Never ``None`` here -- :func:`walk_book`
        refuses an unsized side before any queue policy is consulted."""
        assert self.level.size is not None
        return self.level.size


@dataclass(frozen=True)
class QueueClaim:
    """How many of a level's displayed shares this policy says are ours.

    ``determinate`` is the whole reason this is a record and not an ``int``.
    Zero-and-known ("everything displayed is ahead of you, and the prints prove
    nothing got past it") and zero-and-unknown ("nobody can tell you what is
    ahead of you") are opposite facts: the first is a no-fill, the second is
    ``INDETERMINATE``, and a policy that returned ``0`` for both would publish
    ignorance as a definite refusal.
    """

    quantity: int
    determinate: bool
    note: str
    """One sentence, recorded on the tranche or on the decision's reason. It
    must state the assumption, not merely the number."""
    missing: FrozenSet[DataField] = frozenset()
    """Fields whose absence made this claim indeterminate. Empty otherwise."""

    def __post_init__(self):
        if self.quantity < 0:
            raise ValueError(
                f'a queue claim may not be negative, got {self.quantity}')
        if not self.determinate and self.quantity:
            raise ValueError(
                'an indeterminate queue claim may not also assert a quantity; '
                'that would publish a guess as a decision')


@runtime_checkable
class QueuePolicy(Protocol):
    """How much of a displayed level is ours. The axis the author asked for.

    Structural rather than nominal, so a caller may ship their own without
    inheriting anything of ours -- the same promise ``fills.FillPolicy`` makes.
    A policy is a pure function of its request and its own parameters; it holds
    no state across levels or orders, which is what makes a run reproducible
    independently of the order in which orders were evaluated.

    Attributes:
        signature: the policy **and its parameters**, recorded inside
            :attr:`BookWalkFillPolicy.signature` and therefore stamped on every
            decision. It must not contain ``': '`` -- ``fills.stamp_policy``
            refuses a signature that would make the stamp unreadable.
    """

    signature: str

    def claim(self, request: QueueRequest) -> QueueClaim:
        """How much of ``request.level`` this order gets."""
        ...


class OptimisticQueue:
    """We are at the front: take the full displayed size at every level.

    The bound, not a forecast. It is what every backtester does implicitly
    whenever it fills at the touch, and it ships for the same reason
    ``SoftFillPolicy`` does -- a spread needs an arm to be measured against.

    What it assumes, stated because it is invisible otherwise: that at the
    instant of our arrival no other aggressor was ahead of us at any level we
    swept, on every level, in every instrument, for the whole run. On a level
    displaying 81,700 shares (HPG, 2022-11-09, ask 2 at 13.500) that is a claim
    about 81,700 shares nobody else wanted first.
    """

    signature: ClassVar[str] = 'optimistic'

    def claim(self, request: QueueRequest) -> QueueClaim:
        return QueueClaim(
            quantity=request.displayed,
            determinate=True,
            note=(f'optimistic queue: assumed first in the queue at depth '
                  f'{request.level.depth}, so all {request.displayed} '
                  f'displayed shares are available'),
        )

    def __repr__(self) -> str:
        return 'OptimisticQueue()'


#: What :class:`ConservativeQueue` needs and this corpus does not have: the
#: number of shares that printed at or through a level's price after our
#: arrival. A caller who has a sized tape supplies one of these; ``None``
#: returned for a level means *unknown*, which is not zero.
PrintsThrough = Callable[[QueueRequest], Optional[int]]


class ConservativeQueue:
    """We are behind everything displayed. A level yields nothing until more
    than its displayed size trades through.

    **What this needs that we do not have, exactly.** To know whether the
    queue in front of us cleared, we need the *subsequent prints* at that
    price -- how many shares traded there after we arrived. This corpus cannot
    supply them, and the reason is sharper than "no order ids": the trade tape
    itself is unsized. ``local_quote_matched`` and ``quote_matched`` carry
    ``(datetime, tickersymbol, price)`` and **no quantity column** -- verified
    on both prefixes. So "more than N shares traded through" is not merely
    unobserved here, it is unobservable, and no amount of care with the book
    tables would recover it.

    **What it does in their absence.** It returns an *indeterminate* claim
    naming :attr:`DataField.VOLUME`, and :func:`walk_book` turns that into an
    ``INDETERMINATE`` for the whole order. It does **not** return zero. Zero
    would be a confident no-fill built out of a missing column, and a confident
    no-fill silently suppresses every trade the strategy should have made --
    the failure mode is the mirror of a confident fill, not a safer version of
    it. The consequence is worth stating plainly rather than burying: **on the
    corpus shipped with this repository, the conservative arm decides
    nothing.** That is a measurement of the data, it is reported rather than
    worked around, and it names the one column that would fix it.

    **What it does when they are supplied.** ``prints`` is a callable the
    caller provides; given a level it returns the shares seen printing at or
    through that price since the order arrived, or ``None`` for *unknown*. The
    claim is then ``min(displayed, max(0, printed - displayed))``: everything
    displayed is ahead of us, so the first ``displayed`` shares of the print
    are not ours, and we never claim more than the level showed even if the
    print was larger -- shares that arrived behind us are not visible depth
    and this module does not invent them.
    """

    def __init__(self, prints: Optional[PrintsThrough] = None) -> None:
        """
        Args:
            prints: subsequent-print lookup, or ``None`` -- the default, and
                the only thing this corpus supports. Recorded in
                :attr:`signature` either way, because a conservative run with
                prints and one without are different experiments that must not
                share a provenance string.
        """
        self.prints = prints

    @property
    def signature(self) -> str:
        return (f'conservative(prints='
                f'{"supplied" if self.prints is not None else "absent"})')

    def claim(self, request: QueueRequest) -> QueueClaim:
        printed = None if self.prints is None else self.prints(request)
        if printed is None:
            return QueueClaim(
                quantity=0,
                determinate=False,
                note=(f'conservative queue: all {request.displayed} displayed '
                      f'shares at depth {request.level.depth} are assumed '
                      f'ahead of this order, and whether more than that traded '
                      f'through cannot be established -- the matched tape in '
                      f'this corpus carries no quantity column, so subsequent '
                      f'print sizes are unobservable'),
                missing=frozenset({DataField.VOLUME}),
            )
        if printed < 0:
            raise ValueError(
                f'a subsequent-print total may not be negative, got {printed}')
        available = min(request.displayed, max(0, printed - request.displayed))
        return QueueClaim(
            quantity=available,
            determinate=True,
            note=(f'conservative queue: {request.displayed} displayed shares '
                  f'at depth {request.level.depth} are ahead of this order and '
                  f'{printed} traded through, leaving {available}'),
        )

    def __repr__(self) -> str:
        return f'ConservativeQueue(prints={self.prints!r})'


def queue_draw_key(request: QueueRequest) -> str:
    """The identity of one queue question, as a stable string.

    Pure function of the *question*, so re-asking it gets the same answer and a
    fill can be audited after the fact from the seed in the signature. The
    fields, and why each is in:

    * :data:`QUEUE_DRAW_DOMAIN` -- separates this from ``fills.draw_key``
      structurally, not by convention;
    * ``order_id`` -- whose order;
    * side, ticker, the book's instant -- which question;
    * the level's **depth and price** -- so the three levels of one sweep draw
      independently, and so an order arriving at a level whose price has
      changed draws afresh rather than inheriting the answer about a price that
      is gone.

    Deliberately **out**: ``remaining``, the displayed size, and anything about
    other orders. A partial fill elsewhere in the run must not re-roll our
    position in a queue we have not moved in.
    """
    return '|'.join((
        QUEUE_DRAW_DOMAIN,
        request.order_id,
        request.side.value,
        request.ticker,
        request.ts.isoformat(),
        str(request.level.depth),
        str(request.level.price),
    ))


class ProbabilisticQueue:
    """Draw our position in the queue. Seeded, and the seed on every fill.

    The model, stated in full because a drawn number with no stated model is
    just a number: our position is **uniform over the displayed size**. Given a
    level showing ``N`` shares, the count resting ahead of us is drawn uniformly
    over ``{0, 1, ..., N}`` -- ``N + 1`` outcomes, from ``0`` (first in the
    queue, the optimistic arm) to ``N`` (behind everything, the conservative
    arm). Our claim is ``N - ahead``. The endpoints are the other two policies,
    which is the property that makes this an *axis* rather than a third
    unrelated assumption.

    Nothing sources that distribution. No Vietnamese document states a queue
    rule beyond price-then-time priority (rulebook 2.4, QD 352 Dieu 7 and 16),
    and what is missing is not the rule but the data to apply it. Uniform is a
    declared convention, chosen because it interpolates the two bounds, and it
    is recorded in :attr:`signature` so no result can be reported without it.

    **Reproducibility is not "we called ``random.seed``".** The draw is a pure
    function of ``(seed, question)`` via ``fills.fill_draw`` -- counter-based
    rather than a stream, so it does not depend on how many draws happened
    before it, and therefore not on the order in which the session iterated
    over orders and intervals. Adding an unrelated order to a run does not move
    this one's fills; re-evaluating a single order in isolation reproduces the
    fill the run gave it. The seed rides in the signature stamped on every
    decision and the draw itself is written into every tranche's note, so a
    reader with the decision can recompute the number that made it.
    """

    def __init__(self, seed: int) -> None:
        """
        Args:
            seed: required, an ``int``, no default and no unseeded mode. A
                probabilistic result that cannot be reproduced is not a result,
                and a default seed would make a run reproducible by accident
                rather than by record.

        Raises:
            TypeError: on a non-``int`` or a ``bool``. ``True`` silently
                meaning seed 1 is a bug worth refusing.
        """
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError(
                f'seed must be an int, got {type(seed).__name__}; a '
                f'probabilistic queue that cannot be reproduced is not a result'
            )
        self.seed = seed

    @property
    def signature(self) -> str:
        return f'probabilistic(seed={self.seed},ahead=uniform)'

    def draw(self, request: QueueRequest) -> Decimal:
        """The uniform ``[0, 1)`` draw behind one level. Public so a fill can
        be re-checked from its own recorded key."""
        return fill_draw(self.seed, queue_draw_key(request))

    def claim(self, request: QueueRequest) -> QueueClaim:
        displayed = request.displayed
        value = self.draw(request)
        ahead = int(value * (displayed + 1))
        available = displayed - ahead
        return QueueClaim(
            quantity=available,
            determinate=True,
            note=(f'probabilistic queue: a seeded draw of {value} against '
                  f'seed {self.seed} places {ahead} of the {displayed} '
                  f'displayed shares at depth {request.level.depth} ahead of '
                  f'this order, leaving {available} '
                  f'[key {queue_draw_key(request)}]'),
        )

    @staticmethod
    def confidence_of(taken: int, displayed: int) -> Decimal:
        """``P(our claim would have been at least this large)``, under uniform.

        A genuine tail probability of the realised draw and not a repurposed
        number: with the count ahead uniform over ``N + 1`` outcomes, the claim
        is uniform over ``{0..N}`` and ``P(claim >= t) = (N - t + 1) / (N + 1)``.
        Taking everything displayed is the least likely outcome and scores
        ``1 / (N + 1)``; taking a sliver of a deep level scores close to 1.

        This is what a probabilistic sweep puts in ``FillDecision.confidence``,
        multiplied across the levels it swept -- the probability that a fresh
        draw would have granted at least what this one did **at every level**.
        """
        if displayed <= 0:
            raise ValueError(
                f'a displayed size must be positive, got {displayed}')
        with localcontext() as ctx:
            ctx.prec = 28
            return (Decimal(displayed - taken + 1)
                    / Decimal(displayed + 1))

    def __repr__(self) -> str:
        return f'ProbabilisticQueue(seed={self.seed})'


# --------------------------------------------------------------------------
# The walk
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Tranche:
    """One fill, at one resting level's own price. The unit of the trade log.

    Carries the provenance of the level it ate, not just the numbers: a tranche
    taken from a level whose size was observed four minutes before its price
    (``sizes_lag_price``) is a weaker record than one whose two observations
    coincide, and the difference is not recoverable after the fact.
    """

    depth: int
    price: Decimal
    quantity: int
    displayed: int
    """What the level showed. ``quantity`` is what the queue policy allowed and
    the order needed, and the two are equal only under
    :class:`OptimisticQueue` on a fully-consumed level."""
    price_as_of: datetime
    size_as_of: Optional[datetime]
    age: timedelta
    """The level's honest age: the older of its two observations."""
    sizes_lag_price: bool
    queue_note: str
    queue_confidence: Decimal = Decimal('1')

    @property
    def consideration(self) -> Decimal:
        """``price * quantity``, exact. The sum of these over a sweep is the
        cash the sweep moved; no average is involved anywhere."""
        return self.price * Decimal(self.quantity)

    def __str__(self) -> str:
        return f'{self.quantity}@{self.price}(L{self.depth})'


@dataclass(frozen=True)
class BookWalk:
    """One order's pass through one reconstructed book. The whole record.

    Returned for every call including the ones that fill nothing, because the
    interesting cases here are the refusals and a ``None`` would collapse six
    of them into one.
    """

    ticker: str
    ts: datetime
    side: Side
    """The aggressor's side."""
    limit: Optional[Decimal]
    """``None`` for the market family, which has no price bound."""
    requested: int
    tranches: Tuple[Tranche, ...]
    stop: SweepStop
    remainder_status: Remainder
    reason: str
    queue_signature: str
    missing: FrozenSet[DataField] = frozenset()
    """Named only where something is ``INDETERMINATE``. A walk that filled
    inside the ladder is missing nothing."""
    bound: Bound = Bound.WALK
    ladder_fault: LadderFault = LadderFault.NONE
    fault_at_depth: Optional[int] = None
    resting_availability: SideAvailability = SideAvailability.OBSERVED
    resting_age: Optional[timedelta] = None
    """Age of the **oldest** ingredient on the side we swept."""
    cross_side_skew: Optional[timedelta] = None
    """``|bid.as_of - ask.as_of|``, reported on every two-sided book. Never
    gates anything -- an aggressor needs one side -- but a sweep taken from a
    book whose two halves are four minutes apart is a weaker claim and the
    caller has to be able to see it."""
    is_touching: bool = False
    """Best bid exactly equal to best ask. Flagged, not refused: unlike a
    crossed book this is what a book looks like in the instant before a match
    and may be nothing worse than a fractional-second stale side."""
    trusted_depth: int = 0
    """Levels the walk was willing to consider, after ladder faults and after
    ``max_age`` truncation upstream. Compare against
    ``DepthSide.observed_depths`` to see what was dropped."""
    table_prefix: str = ''

    # -- the numbers ----------------------------------------------------

    @property
    def filled_quantity(self) -> int:
        return sum(t.quantity for t in self.tranches)

    @property
    def remainder(self) -> int:
        return self.requested - self.filled_quantity

    @property
    def indeterminate_quantity(self) -> int:
        """The part of this order the data could not decide. **The number this
        module most wants counted and the one the shipped meter cannot see** --
        see :class:`SweptFillDecision`."""
        return (self.remainder
                if self.remainder_status is Remainder.INDETERMINATE else 0)

    @property
    def consideration(self) -> Decimal:
        """Exact cash the sweep moved: ``sum(price * quantity)``. Not derived
        from any average and never equal to ``quantity * price`` unless the
        sweep took one level."""
        return sum((t.consideration for t in self.tranches), Decimal('0'))

    @property
    def prices(self) -> Tuple[Decimal, ...]:
        return tuple(t.price for t in self.tranches)

    @property
    def worst_price(self) -> Optional[Decimal]:
        """The least favourable price in the sweep -- highest for a buy, lowest
        for a sell. This is what :class:`SweptFillDecision` projects onto
        ``FillDecision.price``; see there for why it, and not the average."""
        if not self.tranches:
            return None
        prices = self.prices
        return max(prices) if self.side is Side.BUY else min(prices)

    @property
    def vwap(self) -> Optional[Decimal]:
        """Volume-weighted average of the tranches, for reporting only.

        **Not a fill price.** It is generally off the tick grid, it is a price
        at which nothing traded, and ``quantity * vwap`` will not equal
        :attr:`consideration` exactly. It exists so a report can quote one
        number next to the tranches that are the actual record.
        """
        filled = self.filled_quantity
        if not filled:
            return None
        with localcontext() as ctx:
            ctx.prec = 28
            return self.consideration / Decimal(filled)

    @property
    def confidence(self) -> Decimal:
        """Product of the tranches' queue confidences.

        Under :class:`ProbabilisticQueue` this is the probability that a fresh
        draw would have granted at least this quantity at *every* level swept.
        Under the two deterministic policies every factor is 1: their
        assumption is declared rather than distributed, which is exactly how
        ``fills.py`` treats ``soft`` and ``hard``.
        """
        with localcontext() as ctx:
            ctx.prec = 28
            out = Decimal('1')
            for tranche in self.tranches:
                out *= tranche.queue_confidence
            return out

    @property
    def filled(self) -> bool:
        return bool(self.tranches)

    # -- composition with a bound outside the book ----------------------

    def bounded_to(self, quantity: int, bound: Bound) -> 'BookWalk':
        """This walk, trimmed to ``quantity`` from the **best price outward**.

        The direction is forced, not chosen. Price-time priority means a sweep
        consumes level 1 before it can touch level 2, so if some constraint
        outside the book allows only ``q`` shares, those ``q`` are necessarily
        the first ``q`` of the sweep -- the best-priced ones. Trimming from the
        other end would describe an order that reached level 3 without clearing
        level 1.

        **What a bound does to this walk's depth ignorance depends on which
        bound it is**, and conflating the two was a real defect found by
        mutating this method:

        * :attr:`Bound.PARTICIPATION` **erases** it. The cap is a hard bound on
          what this caller may take from this interval whatever the book held,
          so an order capped at 1,000 of an available 6,900 would have been
          capped at 1,000 against a ladder of any depth. There is nothing left
          for an invisible level 4 to have decided, and the remainder becomes
          :attr:`Remainder.RESTS`.
        * :attr:`Bound.ROUND_LOT` **preserves** it, and preserves the stop that
          produced it. Flooring to a lot rounds *our own* quantity and says
          nothing whatever about the book: an order that ate all three visible
          levels and was then floored from 2,497 to 2,400 is still an order
          that could not see past level 3, and reporting it as a clean rest
          would delete the only ignorance in it.
        """
        if quantity < 0:
            raise ValueError(f'a bound may not be negative, got {quantity}')
        if quantity >= self.filled_quantity:
            return self
        kept: List[Tranche] = []
        left = quantity
        for tranche in self.tranches:
            if left <= 0:
                break
            take = min(left, tranche.quantity)
            kept.append(tranche if take == tranche.quantity
                        else replace(tranche, quantity=take))
            left -= take

        erases = bound is Bound.PARTICIPATION
        if quantity == self.requested:
            remainder = Remainder.NONE
        elif erases or self.remainder_status is Remainder.NONE:
            remainder = Remainder.RESTS
        else:
            remainder = self.remainder_status
        return replace(
            self,
            tranches=tuple(kept),
            stop=SweepStop.CAPPED if erases else self.stop,
            remainder_status=remainder,
            bound=bound,
            missing=frozenset() if erases else self.missing,
            reason=(f'{self.reason}; then trimmed from {self.filled_quantity} '
                    f'to {quantity} by {bound.value}, best price first'),
        )

    def __str__(self) -> str:
        body = ' + '.join(str(t) for t in self.tranches) or 'nothing'
        return (f'{self.side.value} {self.requested} {self.ticker} '
                f'@ {self.limit}: {body} [{self.stop.value}]')


def walk_book(
    book: DepthBook,
    *,
    side: Side,
    limit: Optional[Decimal],
    quantity: int,
    queue: QueuePolicy,
    order_id: str,
    max_staleness: Optional[timedelta],
    max_levels: int = MAX_DEPTH,
) -> BookWalk:
    """Walk ``book``'s resting side outward. The mechanic, and nothing else.

    Pure: no exchange, no interval, no account, no cap. Everything it consults
    is on the book it was handed, which is what makes the sweep testable
    against a real ladder without a session around it.

    Args:
        book: a reconstructed :class:`~plutus.market.adapters.depth.DepthBook`.
        side: the **aggressor's** side. A BUY sweeps asks.
        limit: the aggressor's limit, or ``None`` for the market family, which
            has no price bound and walks until the ladder runs out. Note that
            an unbounded walk reaches :attr:`SweepStop.EXHAUSTED` and its
            remainder is ``INDETERMINATE``, which is also the honest answer for
            an MTL residue: rulebook 2.3 converts it to a limit one tick beyond
            the last match and that conversion is not modelled here.
        quantity: what is left of the order. Must be positive.
        queue: the caller's queue assumption. Consulted **per level**.
        order_id: identifies the question for a seeded draw. Required, with no
            default, because a shared default would give every order in a run
            the same queue position.
        max_staleness: refuse the resting side if its oldest ingredient is
            older than this. ``None`` means *accept any age* and is a real
            choice, not an omission -- see the module docstring on why it has
            no default. Pass the same value to
            ``DepthSource.book_at(max_age=...)`` to have stale *levels* dropped
            before they get here; this gate is the backstop for a provider that
            does not.
        max_levels: how deep to go. Defaults to the corpus's three.

    Raises:
        ValueError: on a non-positive quantity, on ``Side.CROSS`` (a negotiated
            put-through is not order matching), or on ``max_levels`` outside
            ``1..3``. All three are integration bugs and an ``INDETERMINATE``
            returned for a bug would be published as market ignorance.
    """
    if quantity <= 0:
        raise ValueError(f'a walk needs a positive quantity, got {quantity}')
    if side not in (Side.BUY, Side.SELL):
        raise ValueError(
            f'{side} is a negotiated trade rather than order matching; a '
            f'sweep is one-sided and cannot be walked for it')
    if not 1 <= max_levels <= MAX_DEPTH:
        raise ValueError(
            f'max_levels must be 1..{MAX_DEPTH}, got {max_levels}; the corpus '
            f'carries no level beyond {MAX_DEPTH} and this module does not '
            f'extrapolate one')

    resting = book.resting_side_for(side)
    common = dict(
        ticker=book.ticker, ts=book.ts, side=side, limit=limit,
        requested=quantity, queue_signature=queue.signature,
        resting_availability=resting.availability,
        resting_age=resting.age,
        cross_side_skew=book.cross_side_skew,
        is_touching=book.is_touching,
        table_prefix=book.table_prefix,
    )

    def refused(stop: SweepStop, reason: str,
                missing: FrozenSet[DataField]) -> BookWalk:
        return BookWalk(tranches=(), stop=stop,
                        remainder_status=Remainder.INDETERMINATE,
                        reason=reason, missing=missing, **common)

    # -- 1. the four refusals about the book itself ---------------------
    if resting.availability is not SideAvailability.OBSERVED:
        return refused(
            SweepStop.NO_BOOK,
            f'the {_name(_resting_of(side))} side is '
            f'{resting.availability.value} ({resting.truncation.value}; '
            f'observed depths {list(resting.observed_depths)}), so there is no '
            f'touch to sweep into and whether this order would have filled '
            f'cannot be established',
            frozenset({DataField.BOOK}))

    if not resting.has_sizes:
        return refused(
            SweepStop.NO_SIZES,
            f'the {_name(_resting_of(side))} side is priced but unsized, so no '
            f'level can be consumed; filling at the touch anyway would assume '
            f'unbounded size there, which is a market-impact assumption',
            frozenset({DataField.BOOK_SIZE}))

    if book.is_crossed:
        return refused(
            SweepStop.CROSSED,
            f'the reconstructed book is crossed -- best bid '
            f'{book.bid.best.price} above best ask {book.ask.best.price} -- '
            f'which is not a market state but the symptom of a per-side as-of '
            f'join; sweeping it would fill an arbitrage that never existed',
            frozenset({DataField.BOOK}))

    age = resting.age
    if max_staleness is not None and age is not None and age > max_staleness:
        return refused(
            SweepStop.STALE,
            f'the {_name(_resting_of(side))} side is {age.total_seconds():.1f}s '
            f'old against a budget of {max_staleness.total_seconds():.1f}s; '
            f'this corpus carries no deletion record, so a level this stale may '
            f'be a level that no longer exists',
            frozenset({DataField.BOOK}))

    # -- 2. the ladder's own shape --------------------------------------
    trusted, fault, fault_at = _trusted_prefix(resting.levels[:max_levels],
                                               side)
    common['ladder_fault'] = fault
    common['fault_at_depth'] = fault_at
    common['trusted_depth'] = len(trusted)

    # -- 3. the walk ----------------------------------------------------
    tranches: List[Tranche] = []
    remaining = quantity
    stop = SweepStop.EXHAUSTED
    missing: FrozenSet[DataField] = frozenset()
    note = ''

    for level in trusted:
        if limit is not None and _beyond(side, level.price, limit):
            stop = SweepStop.LIMIT
            note = (f'depth {level.depth} is priced {level.price}, beyond a '
                    f'limit of {limit}')
            break
        request = QueueRequest(
            ticker=book.ticker, ts=book.ts, side=side, order_id=order_id,
            level=level, remaining=remaining)
        claim = queue.claim(request)
        if not claim.determinate:
            stop = SweepStop.QUEUE_UNKNOWN
            missing = claim.missing
            note = claim.note
            break
        if claim.quantity <= 0:
            stop = SweepStop.QUEUE_BLOCKED
            note = claim.note
            break
        take = min(remaining, claim.quantity)
        confidence = (
            ProbabilisticQueue.confidence_of(take, request.displayed)
            if isinstance(queue, ProbabilisticQueue) else Decimal('1'))
        tranches.append(Tranche(
            depth=level.depth, price=level.price, quantity=take,
            displayed=request.displayed,
            price_as_of=level.price_as_of, size_as_of=level.size_as_of,
            age=level.age, sizes_lag_price=level.sizes_lag_price,
            queue_note=claim.note, queue_confidence=confidence,
        ))
        remaining -= take
        if remaining == 0:
            stop = SweepStop.FILLED
            break
    else:
        if remaining > 0 and fault is not LadderFault.NONE:
            stop = SweepStop.LADDER_FAULT
            note = (f'the ladder was truncated at depth {fault_at}: '
                    f'{fault.value}')

    # -- 4. what is true of the remainder -------------------------------
    if remaining == 0:
        remainder = Remainder.NONE
    elif stop in (SweepStop.LIMIT, SweepStop.QUEUE_BLOCKED):
        remainder = Remainder.RESTS
    else:
        remainder = Remainder.INDETERMINATE
        if stop in (SweepStop.EXHAUSTED, SweepStop.LADDER_FAULT):
            missing = frozenset({DataField.BOOK})

    return BookWalk(tranches=tuple(tranches), stop=stop,
                    remainder_status=remainder, missing=missing,
                    reason=_walk_reason(side, limit, quantity, tranches, stop,
                                        remainder, note, trusted),
                    **common)


def _resting_of(aggressor: Side) -> Side:
    return Side.SELL if aggressor is Side.BUY else Side.BUY


def _name(resting: Side) -> str:
    return 'ask' if resting is Side.SELL else 'bid'


def _beyond(side: Side, price: Decimal, limit: Decimal) -> bool:
    """Whether a resting price is past the aggressor's limit.

    The one place the buy/sell inversion is written. A buy will not pay above
    its limit; a sell will not accept below it. Equality is *not* beyond -- a
    limit exactly at the touch is marketable, which is the whole premise the
    author stated.
    """
    return price > limit if side is Side.BUY else price < limit


def _trusted_prefix(
    levels: Tuple[DepthLevel, ...],
    side: Side,
) -> Tuple[Tuple[DepthLevel, ...], LadderFault, Optional[int]]:
    """The longest prefix that could be a resting ladder. See
    :class:`LadderFault` for the two faults and their measured rates."""
    kept: List[DepthLevel] = []
    for level in levels:
        if kept:
            previous = kept[-1].price
            if level.price == previous:
                return tuple(kept), LadderFault.DUPLICATE_PRICE, level.depth
            # "Not beyond the level in front of it" is exactly an inversion:
            # for asks, a price that is not greater than the one before.
            if not _beyond(side, level.price, previous):
                return tuple(kept), LadderFault.INVERTED, level.depth
        kept.append(level)
    return tuple(kept), LadderFault.NONE, None


def _walk_reason(side, limit, quantity, tranches, stop, remainder, note,
                 trusted) -> str:
    """The sentence recorded on the decision. States the sweep, then the stop."""
    verb = 'buy' if side is Side.BUY else 'sell'
    priced = f'at {limit}' if limit is not None else 'at market'
    if not tranches:
        if stop is SweepStop.LIMIT:
            return (f'a {verb} of {quantity} {priced} is not marketable: the '
                    f'best {_name(_resting_of(side))} of '
                    f'{trusted[0].price} is beyond it, so nothing rests at or '
                    f'through this order\'s price and it takes nothing '
                    f'(this is what a band lock looks like from the walk: no '
                    f'rule of its own, just an empty side of the limit)')
        return note or f'a {verb} of {quantity} {priced} took nothing'
    body = ' + '.join(str(t) for t in tranches)
    filled = sum(t.quantity for t in tranches)
    head = (f'a {verb} of {quantity} {priced} swept {len(tranches)} '
            f'level(s) of the visible ladder for {filled}: {body}')
    if remainder is Remainder.NONE:
        return head
    left = quantity - filled
    if remainder is Remainder.RESTS:
        return f'{head}; {left} rests -- {note}'
    if stop is SweepStop.EXHAUSTED:
        return (f'{head}; the ladder is exhausted at depth '
                f'{tranches[-1].depth} and {left} is INDETERMINATE -- '
                f'{DEPTH_IS_NOT_EXTRAPOLATED}')
    return f'{head}; {left} is INDETERMINATE -- {note}'


# --------------------------------------------------------------------------
# The fill policy
# --------------------------------------------------------------------------

@runtime_checkable
class BookProvider(Protocol):
    """Anything that can hand back a reconstructed book at an instant.

    ``adapters.depth.DepthSource`` satisfies it structurally and is the
    intended implementation; the Protocol exists so this module does not import
    a concrete source and so a caller can supply their own.
    """

    def book_at(self, ticker: str, ts: datetime, *,
                max_age: Optional[timedelta] = None) -> DepthBook:
        ...


@dataclass(frozen=True)
class SweptFillDecision(FillDecision):
    """A ``FillDecision`` that still knows it was a sweep.

    ``FillDecision`` carries **one** quantity and **one** price and cannot
    represent several fills at several prices. Rather than change a type this
    module does not own, it extends it: everything downstream that expects a
    ``FillDecision`` gets one, and anything that knows about depth reads
    :attr:`walk` and finds the tranches that are the real record.

    Two deliberate lossy projections, both in the restrictive direction:

    **``price`` is the sweep's worst price**, not its average. A buy is booked
    at the highest price it swept and a sell at the lowest. The average would
    be off the tick grid, would be a price at which nothing traded, and would
    make ``quantity * price`` disagree with the cash the sweep actually moved;
    the worst price is an actual resting price on the actual grid, and erring
    there costs the simulated account money rather than handing it money it
    would not have had. ``walk.consideration`` is the exact figure and
    ``walk.vwap`` is available for reporting.

    **``missing`` is empty on a partial fill whose remainder is
    ``INDETERMINATE``.** ``exchange.py`` counts ``decision.missing`` only when
    the *outcome* is ``INDETERMINATE`` (``exchange.py:2869``), so naming a
    field on a ``FILL`` would put it nowhere. The ignorance is real and is on
    :attr:`walk` -- ``walk.indeterminate_quantity`` and ``walk.missing``.

    *Requested of the orchestrator*, and it is two lines: count
    ``getattr(decision, 'walk', None)``'s ``indeterminate_quantity`` in
    ``_evaluate_fills`` alongside the outcome test, so that an order that swept
    6,900 of 8,000 and could not see past level 3 reports 1,100 shares of
    ignorance instead of a clean fill. Until then a run using this policy must
    read the walks, and :func:`sweep_ignorance` totals them.
    """

    walk: Optional[BookWalk] = None

    @classmethod
    def swept(cls, walk: BookWalk) -> 'SweptFillDecision':
        """The decision a completed, bounded walk implies.

        ``FillEvidence.MODELLED`` on every sweep, including the optimistic one.
        That enum member is documented in ``types.py`` as "a probabilistic or
        queue-estimated fill", and *every* sweep is queue-estimated: optimistic
        estimates our position as zero, which is an estimate. Recording a sweep
        as ``TRADED_THROUGH`` would claim a print that this decision never
        consulted -- the walk reads a resting book, not a tape.
        """
        price = walk.worst_price
        assert price is not None, 'a swept decision needs at least one tranche'
        return cls(outcome=FillOutcome.FILL,
                   quantity=walk.filled_quantity, price=price,
                   confidence=walk.confidence, evidence=FillEvidence.MODELLED,
                   reason=walk.reason, walk=walk)


def sweep_ignorance(decisions: Iterable[FillDecision]) -> int:
    """Shares of ignorance the shipped meter cannot see, totalled.

    The stopgap named in :class:`SweptFillDecision`: sum
    ``walk.indeterminate_quantity`` over decisions this policy produced. A
    ``FillDecision`` from any other policy contributes nothing, so a mixed run
    is safe to pass whole.
    """
    total = 0
    for decision in decisions:
        walk = getattr(decision, 'walk', None)
        if walk is not None:
            total += walk.indeterminate_quantity
    return total


class BookWalkFillPolicy(_CappedFillPolicy):
    """Fill by sweeping the reconstructed ladder. The depth arm.

    Derives from ``fills._CappedFillPolicy`` -- private, and imported
    deliberately -- so that the participation cap's validation and the dated
    round-lot lookup are the *same code* the three shipped policies run rather
    than a second copy that can drift. What this class adds is the sizing, and
    the sizing is the only thing about it that is new.

    Three assumptions have no default and must be named by the caller, because
    each one changes which orders are answerable and a default would make that
    choice invisible: the queue policy, the participation cap and the staleness
    budget. All three are carried in :attr:`signature` and therefore stamped on
    every decision this policy makes.
    """

    kind: ClassVar[str] = BOOK_WALK_KIND

    def __init__(
        self,
        books: BookProvider,
        *,
        queue: QueuePolicy,
        max_participation: Optional[Decimal],
        max_staleness: Optional[timedelta],
        auction: Optional[FillPolicy] = None,
    ) -> None:
        """
        Args:
            books: where the ladder comes from -- a ``DepthSource``, or
                anything satisfying :class:`BookProvider`. Asked for
                ``interval.start``, which is the instant the interval is judged
                at everywhere else in this package (``fills.BaseFillPolicy._lot``
                makes the same choice and states the same caveat: an interval
                that straddled a change would be judged by its opening state).
            queue: the queue assumption. Required. See :class:`QueuePolicy`.
            max_participation: keyword-only and required, ``None`` meaning
                uncapped. Required rather than defaulted for the reason
                ``ProbabilisticFillPolicy`` requires it: the choice materially
                changes which decisions are answerable.
            max_staleness: keyword-only and required, ``None`` meaning *accept
                any age*. Passed to the provider as ``max_age`` -- so stale
                levels are dropped outward before the walk sees them -- and
                enforced again inside :func:`walk_book` for a provider that
                ignores it. **Size it against the lunch break, not the
                median**: ``adapters/depth.py`` measures the largest per-level
                gap in the corpus at 5,412 s and it is 11:30:01 to 13:00:13, so
                a budget picked off the 35 s median discards the entire book on
                the first tick after lunch.
            auction: a :class:`~plutus.market.session.fills.FillPolicy` to hand
                ATO/ATC intervals to, or ``None``. A sweep is a
                continuous-session mechanic (:data:`SWEEP_IS_CONTINUOUS_ONLY`)
                and this class will not invent an auction answer; with ``None``
                every auction interval is ``INDETERMINATE``, which is honest
                but inflates a run's ignorance with questions ``hard`` and
                ``soft`` can answer perfectly well. Passing
                ``HardFillPolicy(...)`` is the intended composition, and the
                delegate's own signature is stamped inside this one's, so a
                decision says which arm decided it.

        Raises:
            TypeError: on a ``float`` ``max_participation``; on a
                ``max_staleness`` that is not a ``timedelta``.
            ValueError: on a ``max_participation`` outside ``(0, 1]``, on a
                negative ``max_staleness``, or on a queue policy whose
                signature would make the policy stamp unreadable.
        """
        self.books = books
        self.queue = queue
        self.max_participation: Optional[Decimal] = (
            self._validated_participation(max_participation,
                                          allow_uncapped=True))
        if max_staleness is not None:
            if not isinstance(max_staleness, timedelta):
                raise TypeError(
                    f'max_staleness must be a timedelta or None, got '
                    f'{type(max_staleness).__name__}')
            if max_staleness < timedelta(0):
                raise ValueError(
                    f'max_staleness must not be negative, got {max_staleness}')
        self.max_staleness = max_staleness
        signature = getattr(queue, 'signature', '')
        if not signature:
            raise ValueError(
                f'{queue!r} has no signature, so the queue assumption behind '
                f'every fill it produced could not be recorded')
        if POLICY_SEPARATOR in signature:
            raise ValueError(
                f'a queue signature may not contain {POLICY_SEPARATOR!r}, got '
                f'{signature!r}; it would make the policy stamp unreadable')
        self.auction = auction

    # -- what a run records ---------------------------------------------

    @property
    def signature(self) -> str:
        cap = ('uncapped' if self.max_participation is None
               else str(self.max_participation))
        stale = ('any' if self.max_staleness is None
                 else f'{self.max_staleness.total_seconds()}s')
        auction = ('off' if self.auction is None
                   else getattr(self.auction, 'signature',
                                getattr(self.auction, 'kind', 'unknown')))
        return (f'{self.kind}(queue={self.queue.signature},'
                f'max_participation={cap},max_staleness={stale},'
                f'auction={auction})')

    @property
    def assumptions(self) -> Tuple[str, ...]:
        cap = (
            'Size: uncapped by volume -- an order takes as much visible depth '
            'as the queue policy allows, with no reference to what actually '
            'traded in the interval.'
            if self.max_participation is None else
            f'Participation cap: at most {self.max_participation} of the '
            f'volume observed in the evaluated interval, aggregated across all '
            f'of the caller\'s live orders in the instrument, applied AFTER '
            f'the depth walk. A modelling convention, not a sourced rule.'
        )
        stale = (
            'Staleness: no budget -- a level of any age is swept. This corpus '
            'carries no deletion record, so a forward-filled level may be one '
            'that no longer exists; measured on HPG 2025-04-10, every one of '
            'the 14,775 ceiling-locked books shows an ask a median 5,201s old '
            'at the day\'s floor.'
            if self.max_staleness is None else
            f'Staleness: a resting side older than '
            f'{self.max_staleness.total_seconds()}s is refused as '
            f'INDETERMINATE, and levels older than it are dropped outward '
            f'before the walk.'
        )
        return (NO_MARKET_IMPACT, SWEEP_IS_CONTINUOUS_ONLY,
                DEPTH_IS_NOT_EXTRAPOLATED,
                'Fill price: every tranche is priced at the RESTING level\'s '
                'own price (rulebook 2.4, QD 352 Dieu 6.3), so one order '
                'produces several fills at several prices. FillDecision.price '
                'projects them onto the sweep\'s worst price; the tranches on '
                'SweptFillDecision.walk are the record.',
                f'Queue position: {self.queue.signature}. Which shares of a '
                f'displayed level are ours is not observable in a corpus with '
                f'no order ids, so it is a declared assumption and the caller '
                f'chose this one.',
                cap, stale)

    # -- continuous ------------------------------------------------------

    def _continuous(self, order, interval, rules, *, already_filled,
                    instrument) -> FillDecision:
        if interval.resolution is not Resolution.TICK:
            # A book is an instantaneous object. A daily bar is stamped
            # midnight, so forward-filling a ladder to it would answer with the
            # previous session's book -- or, here, with nothing at all.
            return FillDecision.indeterminate(
                f'a sweep needs an instantaneous book and this interval is '
                f'{interval.resolution.value}; a daily bar has no instant for '
                f'a ladder to be as-of',
                [DataField.BOOK],
            )

        locked = self._lock_refusal(order, interval)
        if locked is not None:
            return locked

        book = self.books.book_at(interval.ticker, interval.start,
                                  max_age=self.max_staleness)
        walk = walk_book(
            book, side=order.order.side, limit=order.order.limit_price,
            quantity=order.remaining_quantity, queue=self.queue,
            order_id=str(order.order_id), max_staleness=self.max_staleness,
        )
        return self._decide(walk, order, interval, rules,
                            already_filled=already_filled,
                            instrument=instrument)

    def _lock_refusal(self, order: OrderRecord,
                      interval: MarketInterval) -> Optional[FillDecision]:
        """The band lock read at **fill** time. The asymmetry item 3 names.

        ``exchanges/equity.py``'s ``BAND_LOCK`` rule refuses an order at entry
        when it is marketable through a lock on its own side. Nothing read
        ``state.locked_side`` afterwards, so the identical order, already
        resting, filled at the same instant under every shipped policy. This
        closes it, using the venue's own predicate rather than a second one:
        same side, same marketability test, same evidence ladder.

        **One direction only.** A lock may refuse a fill; it may never
        authorise one. ``locked_side`` that does *not* match this order says
        nothing about it, and a book that shows liquidity while the state says
        locked is refused rather than filled -- refusing a trade the market
        allowed costs an opportunity, filling one it refused costs money.

        Evidence decides which refusal:
        ``LockEvidence.UNKNOWN`` (the lock could not be established from a book
        or a bar proxy) is ``INDETERMINATE``; a lock established from either is
        a definite ``NO_FILL``, exactly as admission treats it.
        """
        state = interval.state
        if state.locked_side is None or order.order.side is not state.locked_side:
            return None
        price = order.order.limit_price
        marketable = price is None or (
            (order.order.side is Side.BUY and state.ceiling is not None
             and price >= state.ceiling)
            or (order.order.side is Side.SELL and state.floor is not None
                and price <= state.floor))
        if not marketable:
            return None
        if state.lock_evidence is LockEvidence.UNKNOWN:
            return FillDecision.indeterminate(
                f'the band is reported locked against the '
                f'{order.order.side.value} side and this order is marketable '
                f'through it, but the lock rests on no book and no bar proxy, '
                f'so whether it would have filled cannot be established',
                [DataField.BOOK],
            )
        bound = (state.ceiling if order.order.side is Side.BUY
                 else state.floor)
        return FillDecision.no_fill(
            f'the band is locked at {bound} against the '
            f'{order.order.side.value} side ({state.lock_evidence.value}) and '
            f'this order is marketable through it; admission refuses the '
            f'identical order at entry under BAND_LOCK, so filling it here '
            f'would let a resting order do what a new one may not'
        )

    # -- auction ---------------------------------------------------------

    def _auction(self, order, interval, rules, *, already_filled,
                 instrument) -> FillDecision:
        """Never sweeps. Delegates, or admits it cannot say."""
        if self.auction is None:
            return FillDecision.indeterminate(
                SWEEP_IS_CONTINUOUS_ONLY + ' Construct this policy with '
                'auction=HardFillPolicy(...) to have the cross decided by an '
                'arm that models it.',
                (),
            )
        return self.auction.evaluate(order, interval, rules,
                                     already_filled=already_filled,
                                     instrument=instrument)

    # -- sizing: where the walk and the cap compose ----------------------

    def _decide(self, walk: BookWalk, order, interval, rules, *,
                already_filled, instrument) -> FillDecision:
        """Turn a completed walk into a decision, applying the two bounds.

        **How the cap and the walk compose, and why in this order.**
        They bound different things and both hold. The walk bounds by *visible
        depth at prices through the limit* -- a statement about the book at one
        instant. The participation cap bounds by *our share of the volume the
        interval actually traded* -- a statement about the tape over a span.
        Neither implies the other: a thin book can sit in a heavy interval and
        a deep one in a quiet interval.

        The walk runs **first**, for three reasons and none of them is taste:

        1. *It can answer questions the cap cannot reach.* An order that is not
           marketable takes nothing whatever the volume was, so running the
           walk first turns that into a definite ``NO_FILL`` instead of a
           missing-volume ``INDETERMINATE``. This is the same argument
           ``HardFillPolicy`` makes for testing price before size, and keeping
           the order identical is what stops the two arms' ignorance rates from
           being incomparable.
        2. *The cap has no per-level meaning.* It is a fraction of an interval's
           whole volume; splitting it across three ladder levels would require
           a rule for how volume distributes over the book, which nothing here
           has. So it can only apply to a total, and a total only exists after
           the walk.
        3. *Trimming is forced to be outward.* Price-time priority means level 2
           cannot be reached until level 1 is cleared, so a cap that allows
           ``q`` shares allows the *first* ``q`` of the sweep. See
           :meth:`BookWalk.bounded_to`.

        Then the round lot floors the total -- the dated one in force at the
        instant, resolved by ``BaseFillPolicy._lot``, and ``INDETERMINATE``
        where it cannot be resolved at all. Flooring the **total** and
        redistributing outward, rather than flooring each tranche, is
        deliberate: three tranches each floored to a lot would silently lose up
        to three lots of an order the book could genuinely fill.

        The cap binding also collapses the walk's own depth ignorance: an order
        stopped at 5,000 of an available 6,900 never reached level 3, so there
        is nothing left for the invisible level 4 to have decided.
        """
        if not walk.tranches:
            if walk.remainder_status is Remainder.INDETERMINATE:
                return replace(
                    SweptFillDecision.indeterminate(walk.reason,
                                                    sorted(walk.missing,
                                                           key=lambda f: f.value)),
                    walk=walk)
            return replace(SweptFillDecision.no_fill(walk.reason), walk=walk)

        if self.max_participation is None:
            bounded = walk
        else:
            cap = participation_cap(interval, self.max_participation,
                                    already_filled)
            if cap is None:
                return replace(SweptFillDecision.indeterminate(
                    f'{walk.reason}; but with no observed volume the '
                    f'participation cap cannot be computed, so how much of '
                    f'that sweep this caller was entitled to cannot be '
                    f'established',
                    [DataField.VOLUME]), walk=walk)
            if cap <= 0:
                return replace(SweptFillDecision.no_fill(
                    f'a participation cap of {self.max_participation} of the '
                    f'{interval.volume} traded in this interval leaves nothing '
                    f'for this order after {already_filled} already filled in '
                    f'this instrument, whatever the book showed'), walk=walk)
            bounded = walk.bounded_to(min(cap, walk.filled_quantity),
                                      Bound.PARTICIPATION)

        lot = self._lot(rules, interval, instrument)
        if lot is None:
            return replace(SweptFillDecision.indeterminate(
                f'{walk.reason}; but no round lot is known for '
                f'{rules.spec.code!r} at {interval.start.date()}, so the swept '
                f'quantity cannot be floored to a whole lot',
                ()), walk=walk)
        floored = floor_to_lot(bounded.filled_quantity, lot)
        if floored <= 0:
            return replace(SweptFillDecision.no_fill(
                f'{bounded.reason}; and {bounded.filled_quantity} is below one '
                f'round lot of {lot}'), walk=bounded)
        if floored != bounded.filled_quantity:
            bounded = bounded.bounded_to(floored, Bound.ROUND_LOT)

        if (order.time_in_force is TimeInForce.FILL_OR_KILL
                and bounded.filled_quantity < order.remaining_quantity):
            # Same rule ``_CappedFillPolicy._sized_fill`` applies: for an MOK,
            # "1,000 of your 5,000 would have traded" is the finding that it
            # could not be filled in full, which rulebook 2.3 answers with a
            # kill rather than a partial. The state machine refuses a partially
            # filled MOK outright, so proposing one is unsatisfiable.
            return replace(SweptFillDecision.no_fill(
                f'{bounded.reason}; and a fill-or-kill order fills in full at '
                f'entry or is cancelled entirely (rulebook 2.3), so '
                f'{bounded.filled_quantity} of {order.remaining_quantity} is a '
                f'kill'), walk=bounded)

        return SweptFillDecision.swept(bounded)
