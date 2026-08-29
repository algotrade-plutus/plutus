"""The sweep: a marketable order walking a real Vietnamese ladder.

What is under test, and why each part earns a section.

`book_walk.py` is the first thing in this package that lets an order *consume
depth*. Everything else fills at one price. So the tests are about four claims:

1. **A sweep produces several fills at several prices**, each at the resting
   level's own price and never at the aggressor's limit or at an average. That
   is the rule (rulebook 2.4, QĐ 352 Điều 6.3), and it is the claim a
   single-price implementation would silently pass every other test while
   getting wrong.
2. **Queue position is an axis the caller chooses**, the three arms give three
   different answers to the same order, and the probabilistic one reproduces
   exactly from its seed.
3. **The band lock needs no rule of its own** — and the measured shape of a
   real locked book is not the shape the brief predicted. See
   `TestTheBandLock`.
4. **Ignorance is never dressed as a refusal.** An absent side, an unsized
   ladder, a crossed book, a side staler than the caller's budget and a queue
   the data cannot resolve are all `INDETERMINATE` naming a field — never a
   confident `NO_FILL`, which suppresses trades a strategy should have made and
   fails in the opposite direction to a confident fill rather than in a safer
   one.

**These run against the real extract.** Every ladder below is a `(ticker,
instant)` pair that exists in `hermes-dev-extract`, and the numbers in the
assertions are that ladder's actual prices and sizes. A synthetic ladder would
have let the sweep be written against a book with no stale levels, no
inversions, no duplicate prices and no ghost touch — which is precisely the
book this corpus does not contain. The handful of tests that need no book at
all (arithmetic, validation, the config refusal) run unconditionally.

Prices are in thousands of dong, the corpus convention.
"""

import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from plutus.core.order import Side
from plutus.market.adapters.depth import (DepthSource, SideAvailability,
                                          Truncation)
from plutus.market.exchanges.equity import HSX_EXCHANGE
from plutus.market.protocol import (BandSource, InstrumentKind, InstrumentSpec,
                                    LockEvidence, MarketState, Order,
                                    OrderType, Resolution, SessionPhase)
from plutus.market.session.book_walk import (BOOK_WALK_KIND,
                                             DEPTH_IS_NOT_EXTRAPOLATED,
                                             SWEEP_IS_CONTINUOUS_ONLY,
                                             BookWalkFillPolicy, Bound,
                                             ConservativeQueue, LadderFault,
                                             OptimisticQueue,
                                             ProbabilisticQueue, QueueClaim,
                                             QueuePolicy, QueuePosition,
                                             QueueRequest, MakerQueuePolicy,
                                             Remainder, SweepStop,
                                             SweptFillDecision, maker_fill,
                                             queue_draw_key, sweep_ignorance,
                                             walk_book)
from plutus.market.session.fills import (FillPolicy, SoftFillPolicy,
                                         build_fill_policy, policy_of)
from plutus.market.session.types import (DataField, FillOutcome,
                                         FillPolicyConfig, FillEvidence,
                                         MarketInterval, OrderRecord,
                                         OrderState, TimeInForce, Venue)

# --------------------------------------------------------------------------
# The extract, and the exact ladders these tests pin
# --------------------------------------------------------------------------

_EXTRACT_DEFAULT = Path('/Users/nadan/algotrade-research/dataset/hermes-dev-extract')


def _extract_root():
    env = os.environ.get('PLUTUS_DEPTH_ROOT')
    for root in ([Path(env)] if env else []) + [_EXTRACT_DEFAULT]:
        if (root / 'local_quote_bidprice.parquet').exists():
            return root
    return None


EXTRACT = _extract_root()

requires_extract = pytest.mark.skipif(
    EXTRACT is None,
    reason='No depth extract found; set PLUTUS_DEPTH_ROOT.',
)

#: FPT, 2022-11-09. The clean three-level ladder every mechanic test uses.
#: ask  73.400 x 5,700 | 73.500 x 200 | 73.900 x 1,000   (all 25.2 s old)
#: bid  73.300 x 3,900 | 73.200 x 200 | 73.000 x 1,000
FPT_CLEAN = datetime(2022, 11, 9, 9, 16, 5, 290870)

#: FPT, same day, 09:00:10.126552. ask 1 is **74.900** and 1.4 s old, a
#: leftover from the auction; asks 2 and 3 are 73.400 and 73.500 and 0.0 s old.
#: An inverted ladder -- 1.52 % of FPT's served ladders that day.
FPT_INVERTED = datetime(2022, 11, 9, 9, 0, 10, 126552)

#: FPT, same day, 14:30:10.317628. ask 1 is 74.100 x 100 and **170 s** old;
#: ask 2 is 74.100 x 40,400 and 0.0 s old. Two adjacent levels at one price.
FPT_DUPLICATE = datetime(2022, 11, 9, 14, 30, 10, 317628)

#: HTV, 2022-11-09 -- the thin name. 31 books for the whole session.
#: 09:00:12.460195: the bid is quoted and the **ask side does not exist yet**.
HTV_NO_ASK = datetime(2022, 11, 9, 9, 0, 12, 460195)
#: 09:21:06.408709: asks 11.250 x 100 | 11.300 x 300 | 11.350 x 400, all fresh.
#: 800 shares of visible depth for the entire ladder.
HTV_THIN = datetime(2022, 11, 9, 9, 21, 6, 408709)
#: 09:19:15.185364: the same three levels 259.7 s stale, cross-side skew 259.7 s.
HTV_STALE = datetime(2022, 11, 9, 9, 19, 15, 185364)
#: Read through the ``quote`` prefix, HTV has **zero** size rows: prices at
#: every level and no quantity anywhere.
HTV_UNSIZED = datetime(2022, 11, 9, 9, 8, 54, 386587)

#: HPG, 2025-04-10 -- a limit-up session, read through ``quote``. The bid is
#: locked at the 22.750 ceiling and the ask is a ghost at the day's floor.
HPG_LOCKED = datetime(2025, 4, 10, 9, 15, 7, 593143)
HPG_CEILING = Decimal('22.750000')
HPG_FLOOR = Decimal('19.850000')

SEED = 20220329
DAY = datetime(2022, 11, 9)

HSX_LOT = InstrumentSpec(
    ticker='FPT', exchange_code='HSX', kind=InstrumentKind.STOCK,
    trading_unit=100, daily_trading_limit=Decimal('0.07'),
)


@pytest.fixture(scope='module')
def local():
    if EXTRACT is None:
        pytest.skip('needs the dev extract')
    return DepthSource(str(EXTRACT), table_prefix='local_quote')


@pytest.fixture(scope='module')
def remote():
    if EXTRACT is None:
        pytest.skip('needs the dev extract')
    return DepthSource(str(EXTRACT), table_prefix='quote')


@pytest.fixture
def fpt(local):
    """The clean FPT ladder. The book most of these tests walk."""
    return local.book_at('FPT', FPT_CLEAN)


def _walk(book, **kw):
    """A walk with the arguments a test does not care about supplied."""
    args = dict(side=Side.BUY, limit=Decimal('73.9'), quantity=6000,
                queue=OptimisticQueue(), order_id='O-1', max_staleness=None)
    args.update(kw)
    return walk_book(book, **args)


# --------------------------------------------------------------------------
# Session scaffolding, so the policy can be exercised end to end
# --------------------------------------------------------------------------

def _state(ts=FPT_CLEAN, ticker='FPT', **kw):
    base = dict(
        ticker=ticker, ts=ts, session=SessionPhase.CONTINUOUS,
        reference=Decimal('73.0'), ceiling=Decimal('78.1'),
        floor=Decimal('67.9'), band_source=BandSource.PUBLISHED,
        last=Decimal('73.4'),
    )
    base.update(kw)
    return MarketState(**base)


def _interval(*, ts=FPT_CLEAN, ticker='FPT', volume=1_000_000,
              resolution=Resolution.TICK, session=SessionPhase.CONTINUOUS,
              missing=(), **state_kw):
    state = _state(ts=ts, ticker=ticker, session=session, **state_kw)
    return MarketInterval(
        ticker=ticker, start=ts, end=ts + timedelta(seconds=1),
        resolution=resolution, state=state, volume=volume,
        close=Decimal('73.4'), missing=frozenset(missing),
    )


def _order(*, side=Side.BUY, quantity=6000, limit=Decimal('73.9'),
           ticker='FPT', order_id='O-1', order_type=OrderType.LIMIT,
           tif=TimeInForce.DAY, ts=FPT_CLEAN):
    return OrderRecord(
        order_id=order_id, venue=Venue.HSX, state=OrderState.RESTING,
        time_in_force=tif, submitted_at=ts, updated_at=ts,
        order=Order(ticker=ticker, side=side, quantity=quantity,
                    order_type=order_type, limit_price=limit),
    )


def _policy(source, *, queue=None, cap=None, stale=None, auction=None,
            tape=None):
    return BookWalkFillPolicy(
        source, queue=queue or OptimisticQueue(), max_participation=cap,
        max_staleness=stale, tape=tape, auction=auction)


class _FakeTape:
    """A tape that reports a fixed prints-through total, for the maker arm.

    Isolates the arm from the reconstruction: the real :class:`TapeSource` is
    pinned in ``test_tape_adapter.py``; here the number is handed in so the
    fill maths is what is under test. ``None`` stands for an unserved window.
    """

    def __init__(self, prints):
        self._prints = prints
        self.calls = []

    def prints_through(self, ticker, price, side, since, until):
        self.calls.append((ticker, price, side, since, until))
        return self._prints


def _decide(source, *, order=None, interval=None, **kw):
    policy = _policy(source, **kw)
    return policy.evaluate(order or _order(), interval or _interval(),
                           HSX_EXCHANGE, instrument=HSX_LOT)


# ==========================================================================
# 1. The mechanic: several fills, at several prices, at the resting price
# ==========================================================================

@requires_extract
class TestTheSweep:
    """The walk itself, against FPT's real 09:16:05 ladder."""

    def test_a_sweep_takes_two_levels_at_two_prices(self, fpt):
        """6,000 at 73.500 eats the whole 5,700 at 73.400, then 200 at 73.500.

        The touch is not big enough, so the order walks. This is the claim the
        whole module exists for and the one a single-price fill cannot make.
        """
        walk = _walk(fpt, quantity=6000, limit=Decimal('73.5'))

        assert [(t.depth, t.price, t.quantity) for t in walk.tranches] == [
            (1, Decimal('73.400000'), 5700),
            (2, Decimal('73.500000'), 200),
        ]
        assert walk.filled_quantity == 5900

    def test_a_sweep_takes_three_levels_at_three_prices(self, fpt):
        """6,000 at 73.900 walks all three levels and finishes inside level 3."""
        walk = _walk(fpt, quantity=6000, limit=Decimal('73.9'))

        assert [(t.depth, t.price, t.quantity) for t in walk.tranches] == [
            (1, Decimal('73.400000'), 5700),
            (2, Decimal('73.500000'), 200),
            (3, Decimal('73.900000'), 100),
        ]
        assert walk.stop is SweepStop.FILLED
        assert walk.remainder_status is Remainder.NONE
        assert walk.remainder == 0

    def test_each_tranche_is_priced_at_the_resting_level_not_the_limit(self, fpt):
        """The rule, and the thing implementations get wrong.

        A buy at 73.900 that swept 5,700 shares at 73.400 pays 73.400 for them.
        Vietnamese matching trades at the *resting* order's price (QĐ 352 Điều
        6.3), so the aggressor's limit prices nothing at all.
        """
        walk = _walk(fpt, quantity=6000, limit=Decimal('73.9'))

        assert walk.prices == (Decimal('73.400000'), Decimal('73.500000'),
                               Decimal('73.900000'))
        assert len(set(walk.prices)) == 3
        # 5700*73.4 + 200*73.5 + 100*73.9 -- not 6000 * anything.
        assert walk.consideration == Decimal('440470.000000')

    def test_the_average_price_is_not_a_price_anything_traded_at(self, fpt):
        """Why the sweep is not collapsed into one averaged fill.

        The VWAP of this sweep is 73.411666..., which is off the 0.1 tick grid
        HOSE quotes this band on, is not any of the three prices that traded,
        and does not terminate. It is available for reporting and it is not a
        fill price; the three tranches are the record.
        """
        walk = _walk(fpt, quantity=6000, limit=Decimal('73.9'))

        assert len(walk.tranches) == 3
        assert walk.vwap not in walk.prices
        assert walk.vwap.quantize(Decimal('0.1')) != walk.vwap
        # And the decision projects onto a price that DID trade, not onto this.
        assert SweptFillDecision.swept(walk).price == Decimal('73.900000')

    def test_a_sweep_stops_at_the_limit_and_the_remainder_rests(self, fpt):
        """Level 3 at 73.900 is beyond a 73.500 limit, so 100 of the 6,000
        rests. `RESTS`, not `INDETERMINATE`: the book is fully visible up to
        the limit and it is a fact that nothing more was available there."""
        walk = _walk(fpt, quantity=6000, limit=Decimal('73.5'))

        assert walk.stop is SweepStop.LIMIT
        assert walk.remainder == 100
        assert walk.remainder_status is Remainder.RESTS
        assert walk.missing == frozenset()
        assert walk.indeterminate_quantity == 0

    def test_a_sweep_that_exhausts_the_ladder_is_indeterminate_for_the_rest(
            self, fpt):
        """8,000 eats all 6,900 visible shares and the last 1,100 is unknowable.

        Depth is not extrapolated: there is no level 4 anywhere in the extract
        and inventing one would fill an order against liquidity nobody observed.
        """
        walk = _walk(fpt, quantity=8000, limit=Decimal('73.9'))

        assert walk.filled_quantity == 6900
        assert walk.stop is SweepStop.EXHAUSTED
        assert walk.remainder == 1100
        assert walk.remainder_status is Remainder.INDETERMINATE
        assert walk.indeterminate_quantity == 1100
        assert walk.missing == frozenset({DataField.BOOK})
        assert DEPTH_IS_NOT_EXTRAPOLATED in walk.reason

    def test_a_limit_at_the_touch_is_marketable(self, fpt):
        """`limit >= best_ask` is inclusive. A buy at exactly 73.400 sweeps the
        touch and stops, because level 2 at 73.500 is beyond it."""
        walk = _walk(fpt, quantity=8000, limit=Decimal('73.4'))

        assert walk.filled_quantity == 5700
        assert walk.stop is SweepStop.LIMIT

    def test_an_order_priced_short_of_the_touch_takes_nothing(self, fpt):
        """73.300 is a tick below the 73.400 offer. Nothing rests at or through
        it, so the walk takes nothing -- with no rule about marketability
        anywhere in it. See `TestTheBandLock` for why this shape matters."""
        walk = _walk(fpt, quantity=1000, limit=Decimal('73.3'))

        assert walk.tranches == ()
        assert walk.stop is SweepStop.LIMIT
        assert walk.remainder_status is Remainder.RESTS
        assert 'not marketable' in walk.reason

    def test_a_sell_sweeps_the_bids_downward(self, fpt):
        """The mirror. FPT's bids are 73.300 x 3,900 | 73.200 x 200 | 73.000 x
        1,000, and a sell at 73.200 takes the first two and stops."""
        walk = _walk(fpt, side=Side.SELL, quantity=5000,
                     limit=Decimal('73.2'))

        assert [(t.price, t.quantity) for t in walk.tranches] == [
            (Decimal('73.300000'), 3900),
            (Decimal('73.200000'), 200),
        ]
        assert walk.stop is SweepStop.LIMIT
        assert walk.remainder == 900

    def test_a_market_order_has_no_price_bound_and_still_stops_at_level_3(
            self, fpt):
        """`limit=None` walks the whole trusted ladder. Its remainder is
        INDETERMINATE for two reasons at once -- no level 4, and rulebook 2.3's
        residual-limit conversion is not modelled."""
        walk = _walk(fpt, quantity=99_999, limit=None)

        assert walk.filled_quantity == 6900
        assert walk.stop is SweepStop.EXHAUSTED
        assert walk.remainder_status is Remainder.INDETERMINATE

    def test_a_thin_book_runs_out_almost_immediately(self, local):
        """HTV's whole ladder is 800 shares: 100 + 300 + 400. A 2,000-share
        order takes all of it and is indeterminate for 1,200 -- which is what
        a thin Vietnamese name actually does to an order."""
        book = local.book_at('HTV', HTV_THIN)
        walk = _walk(book, quantity=2000, limit=Decimal('11.35'))

        assert [(t.price, t.quantity) for t in walk.tranches] == [
            (Decimal('11.250000'), 100),
            (Decimal('11.300000'), 300),
            (Decimal('11.350000'), 400),
        ]
        assert walk.filled_quantity == 800
        assert walk.indeterminate_quantity == 1200

    def test_a_walk_refuses_an_integration_bug_rather_than_reporting_ignorance(
            self, fpt):
        """A zero quantity and a CROSS side are bugs, not market conditions.
        An INDETERMINATE returned for either would be counted as market
        ignorance in the published rate."""
        with pytest.raises(ValueError, match='positive quantity'):
            _walk(fpt, quantity=0)
        with pytest.raises(ValueError, match='one-sided'):
            _walk(fpt, side=Side.CROSS)
        with pytest.raises(ValueError, match='max_levels'):
            _walk(fpt, max_levels=4)


# ==========================================================================
# 2. Ladder faults -- the two shapes a resting book cannot have
# ==========================================================================

@requires_extract
class TestLadderFaults:
    """Both are measured in the extract, and both truncate rather than repair."""

    def test_an_inverted_ladder_is_truncated_at_the_inversion(self, local):
        """FPT 09:00:10.126552: ask 1 is 74.900 and 1.4 s old while asks 2 and
        3 are 73.400 and 73.500 and *fresh*. Sweeping in ladder order would buy
        200 at 74.900 and then 5,600 at 73.400, which cannot happen. Keeping
        only the touch is restrictive twice: fewer shares, worse price."""
        book = local.book_at('FPT', FPT_INVERTED)
        assert [str(l.price) for l in book.ask.levels] == [
            '74.900000', '73.400000', '73.500000']

        walk = _walk(book, quantity=8000, limit=Decimal('75.0'))

        assert walk.ladder_fault is LadderFault.INVERTED
        assert walk.fault_at_depth == 2
        assert walk.trusted_depth == 1
        assert [(t.price, t.quantity) for t in walk.tranches] == [
            (Decimal('74.900000'), 200)]
        assert walk.stop is SweepStop.LADDER_FAULT
        assert walk.remainder_status is Remainder.INDETERMINATE

    def test_a_duplicate_price_ladder_is_truncated_at_the_duplicate(self, local):
        """FPT 14:30:10.317628: ask 1 is 74.100 x 100 and 170 s old, ask 2 is
        74.100 x 40,400 and fresh. Consuming both would claim 40,500 shares at
        one price when at most 40,400 exist."""
        book = local.book_at('FPT', FPT_DUPLICATE)
        assert [(str(l.price), l.size) for l in book.ask.levels][:2] == [
            ('74.100000', 100), ('74.100000', 40400)]

        walk = _walk(book, quantity=50_000, limit=Decimal('75.0'))

        assert walk.ladder_fault is LadderFault.DUPLICATE_PRICE
        assert walk.fault_at_depth == 2
        assert walk.filled_quantity == 100
        assert walk.remainder_status is Remainder.INDETERMINATE

    def test_a_fault_behind_a_filled_order_costs_nothing(self, local):
        """The truncation only bites when the order needed the levels behind
        it. 100 shares at the FPT duplicate fills cleanly."""
        book = local.book_at('FPT', FPT_DUPLICATE)
        walk = _walk(book, quantity=100, limit=Decimal('75.0'))

        assert walk.stop is SweepStop.FILLED
        assert walk.ladder_fault is LadderFault.DUPLICATE_PRICE
        assert walk.remainder_status is Remainder.NONE


# ==========================================================================
# 3. The queue axis
# ==========================================================================

@requires_extract
class TestTheQueueAxis:
    """Three answers to one order, and the caller picks which one is theirs."""

    def test_the_three_policies_give_three_different_answers(self, fpt):
        """The point of the axis. Same book, same order, three quantities."""
        results = {}
        for queue in (OptimisticQueue(), ConservativeQueue(),
                      ProbabilisticQueue(SEED)):
            walk = _walk(fpt, quantity=6000, limit=Decimal('73.9'), queue=queue)
            results[queue.signature] = (walk.stop, walk.filled_quantity)

        assert results['optimistic'] == (SweepStop.FILLED, 6000)
        # Nothing can be decided at all without sized subsequent prints.
        assert results['conservative(prints=absent)'] == (
            SweepStop.QUEUE_UNKNOWN, 0)
        # A drawn position takes a slice of each level and still runs out.
        stop, filled = results['probabilistic(seed=20220329,ahead=uniform)']
        assert stop is SweepStop.EXHAUSTED
        assert 0 < filled < 6000

    def test_optimistic_takes_the_whole_displayed_size(self, fpt):
        """And says so on the tranche, so the assumption is countable after
        the fact rather than invisible."""
        walk = _walk(fpt, quantity=6000, limit=Decimal('73.9'),
                     queue=OptimisticQueue())

        assert walk.tranches[0].quantity == walk.tranches[0].displayed == 5700
        assert 'assumed first in the queue' in walk.tranches[0].queue_note
        assert walk.confidence == Decimal('1')

    def test_conservative_cannot_decide_without_sized_subsequent_prints(
            self, fpt):
        """The honest answer, and the finding: **the conservative arm decides
        nothing on this corpus.** Not because we were lazy about the book
        tables -- because `local_quote_matched` and `quote_matched` carry
        `(datetime, tickersymbol, price)` and no quantity column, so "more than
        N traded through" is unobservable here.

        `INDETERMINATE` naming VOLUME, never a zero. A zero would be a
        confident no-fill assembled out of a missing column.
        """
        walk = _walk(fpt, quantity=6000, limit=Decimal('73.9'),
                     queue=ConservativeQueue())

        assert walk.tranches == ()
        assert walk.stop is SweepStop.QUEUE_UNKNOWN
        assert walk.remainder_status is Remainder.INDETERMINATE
        assert walk.missing == frozenset({DataField.VOLUME})
        assert 'no quantity column' in walk.reason

    def test_conservative_fills_once_the_prints_are_supplied(self, fpt):
        """The seam works the moment a sized tape exists. 5,700 are displayed
        ahead of us at the touch; a print of 7,000 through it leaves 1,300."""
        queue = ConservativeQueue(prints=lambda request: 7000)
        walk = _walk(fpt, quantity=1000, limit=Decimal('73.4'), queue=queue)

        assert walk.filled_quantity == 1000
        assert walk.tranches[0].price == Decimal('73.400000')
        assert queue.signature == 'conservative(prints=supplied)'

    def test_conservative_yields_nothing_when_the_queue_did_not_clear(self, fpt):
        """A print smaller than the displayed size is a *definite* no-fill under
        this policy's declared assumption -- the data decided it, so it is
        `RESTS` and not `INDETERMINATE`."""
        queue = ConservativeQueue(prints=lambda request: 100)
        walk = _walk(fpt, quantity=1000, limit=Decimal('73.9'), queue=queue)

        assert walk.tranches == ()
        assert walk.stop is SweepStop.QUEUE_BLOCKED
        assert walk.remainder_status is Remainder.RESTS
        assert walk.missing == frozenset()

    def test_a_blocked_level_stops_the_walk_rather_than_skipping_outward(
            self, fpt):
        """Price-time priority: level 2 cannot be reached until level 1 is
        cleared. A policy that skipped a blocked level would fill deeper in the
        book than an order could ever have reached."""
        # Enough to clear level 2 (200 displayed) but not level 1 (5,700).
        queue = ConservativeQueue(prints=lambda request: 500)
        walk = _walk(fpt, quantity=1000, limit=Decimal('73.9'), queue=queue)

        assert walk.tranches == ()
        assert walk.stop is SweepStop.QUEUE_BLOCKED

    def test_a_seeded_probabilistic_run_reproduces_exactly(self, fpt):
        """Not "we called random.seed". Two separately constructed policies
        with the same seed produce byte-identical tranches, and a third seed
        produces different ones."""
        one = _walk(fpt, quantity=6000, queue=ProbabilisticQueue(SEED))
        two = _walk(fpt, quantity=6000, queue=ProbabilisticQueue(SEED))
        other = _walk(fpt, quantity=6000, queue=ProbabilisticQueue(SEED + 1))

        assert one.tranches == two.tranches
        assert one.confidence == two.confidence
        assert other.tranches != one.tranches

    def test_a_draw_does_not_depend_on_the_rest_of_the_run(self, fpt):
        """Order-independence, which is what makes two runs comparable. The
        draw keys off the *question* -- order, instrument, instant, side, level
        -- and not off how much of the order is left, so a partial fill
        elsewhere cannot re-roll this order's queue position."""
        queue = ProbabilisticQueue(SEED)
        big = _walk(fpt, quantity=6000, queue=queue)
        small = _walk(fpt, quantity=50, queue=queue)

        assert big.tranches[0].queue_note == small.tranches[0].queue_note
        assert small.filled_quantity == 50

    def test_two_orders_draw_two_positions(self, fpt):
        """The order id is in the key, so two orders in the same book at the
        same instant are not handed the same queue position."""
        queue = ProbabilisticQueue(SEED)
        mine = _walk(fpt, quantity=6000, queue=queue, order_id='O-1')
        yours = _walk(fpt, quantity=6000, queue=queue, order_id='O-2')

        assert mine.tranches[0].quantity != yours.tranches[0].quantity

    def test_each_level_draws_independently(self, fpt):
        """Depth and price are in the key, so a sweep is three draws and not
        one position applied three times."""
        walk = _walk(fpt, quantity=99_999, queue=ProbabilisticQueue(SEED))
        fractions = {(t.quantity, t.displayed) for t in walk.tranches}

        assert len(walk.tranches) == 3
        assert len(fractions) == 3

    def test_the_seed_and_the_draw_are_recorded_on_every_fill(self, fpt):
        """A probabilistic fill that cannot be re-checked is not research-grade.
        The seed rides in the signature stamped on the decision, and the draw
        and its key ride on the tranche, so a reader can recompute the number
        that made the fill."""
        queue = ProbabilisticQueue(SEED)
        walk = _walk(fpt, quantity=6000, queue=queue)
        note = walk.tranches[0].queue_note

        assert f'seed {SEED}' in note
        assert 'seeded draw of' in note
        request = QueueRequest(
            ticker='FPT', ts=FPT_CLEAN, side=Side.BUY, order_id='O-1',
            level=fpt.ask.levels[0], remaining=6000)
        assert f'[key {queue_draw_key(request)}]' in note
        assert str(queue.draw(request)) in note

    def test_probabilistic_confidence_is_a_real_tail_probability(self, fpt):
        """`P(claim >= t)` with the count ahead uniform over `N + 1` outcomes.
        Taking everything displayed is the least likely outcome and is never
        zero; taking a sliver of a deep level is nearly certain."""
        assert ProbabilisticQueue.confidence_of(0, 100) == Decimal('1')
        assert ProbabilisticQueue.confidence_of(100, 100) == (
            Decimal('1') / Decimal('101'))

        walk = _walk(fpt, quantity=6000, queue=ProbabilisticQueue(SEED))
        assert Decimal('0') < walk.confidence < Decimal('1')

    def test_the_queue_endpoints_are_the_other_two_arms(self, fpt):
        """The axis is an axis: position 0 is `optimistic` and position N is
        `conservative` with nothing printed through."""
        class _AtTheFront:
            signature = 'front'

            def claim(self, request):
                return QueueClaim(request.displayed, True, 'front')

        class _AtTheBack:
            signature = 'back'

            def claim(self, request):
                return QueueClaim(0, True, 'back')

        front = _walk(fpt, quantity=6000, queue=_AtTheFront())
        back = _walk(fpt, quantity=6000, queue=_AtTheBack())

        assert front.filled_quantity == _walk(
            fpt, quantity=6000, queue=OptimisticQueue()).filled_quantity
        assert back.filled_quantity == 0

    def test_a_third_party_queue_policy_satisfies_the_protocol(self):
        """Structural, so a caller ships their own without inheriting ours."""
        class _Half:
            signature = 'half'

            def claim(self, request):
                return QueueClaim(request.displayed // 2, True, 'half')

        assert isinstance(_Half(), QueuePolicy)
        assert isinstance(OptimisticQueue(), QueuePolicy)


class TestQueueClaimValidation:
    """No book needed: the invariants that keep a claim readable."""

    def test_an_indeterminate_claim_may_not_also_assert_a_quantity(self):
        """Otherwise a guess would be published as a decision."""
        with pytest.raises(ValueError, match='indeterminate queue claim'):
            QueueClaim(100, determinate=False, note='')

    def test_a_negative_claim_is_refused(self):
        with pytest.raises(ValueError, match='may not be negative'):
            QueueClaim(-1, determinate=True, note='')

    def test_a_probabilistic_queue_refuses_an_unusable_seed(self):
        """No default and no unseeded mode; `True` silently meaning seed 1 is a
        bug worth refusing."""
        with pytest.raises(TypeError, match='seed must be an int'):
            ProbabilisticQueue(True)
        with pytest.raises(TypeError, match='seed must be an int'):
            ProbabilisticQueue('7')

    def test_a_negative_print_total_is_an_integration_bug(self):
        queue = ConservativeQueue(prints=lambda request: -1)
        with pytest.raises(ValueError, match='may not be negative'):
            queue.claim(QueueRequest(
                ticker='FPT', ts=DAY, side=Side.BUY, order_id='O-1',
                remaining=100, level=_level()))


def _level(depth=1, price='73.4', size=100):
    """One `DepthLevel`, for the tests that need no corpus."""
    from plutus.market.adapters.depth import DepthLevel
    return DepthLevel(depth=depth, price=Decimal(price), size=size,
                      price_as_of=DAY, size_as_of=DAY, ts=DAY)


# ==========================================================================
# 4. The four refusals -- ignorance is never dressed as a no-fill
# ==========================================================================

@requires_extract
class TestTheRefusals:
    """Each one names a `DataField` and returns INDETERMINATE, never NO_FILL.

    A confident no-fill is as wrong as a confident fill; it just fails in the
    opposite direction, and it silently suppresses trades a strategy should
    have made instead of booking ones it should not.
    """

    def test_an_absent_resting_side_is_indeterminate_naming_book(self, local):
        """HTV at 09:00:12 has a bid and no ask at all -- the side has not been
        quoted yet today. That is not "nobody is offering"; this corpus carries
        no deletion record and cannot express an empty book."""
        book = local.book_at('HTV', HTV_NO_ASK)
        assert book.ask.availability is SideAvailability.ABSENT
        assert book.ask.truncation is Truncation.NO_OBSERVATION

        walk = _walk(book, quantity=1000, limit=Decimal('12.0'))

        assert walk.stop is SweepStop.NO_BOOK
        assert walk.remainder_status is Remainder.INDETERMINATE
        assert walk.missing == frozenset({DataField.BOOK})
        assert walk.indeterminate_quantity == 1000

    def test_a_buy_does_not_need_the_bid_side(self, local):
        """The other half of the same seam. HTV's ask is absent at 09:00:12 but
        its *bid* is fully observed, so a SELL sweeps happily -- an absent side
        the aggressor never touches must not manufacture an INDETERMINATE."""
        book = local.book_at('HTV', HTV_NO_ASK)
        walk = _walk(book, side=Side.SELL, quantity=100, limit=Decimal('10.0'))

        assert walk.filled_quantity == 100
        assert walk.tranches[0].price == Decimal('10.200000')

    def test_an_unsized_ladder_is_indeterminate_naming_book_size(self, remote):
        """Read through the `quote` prefix, HTV has prices at every level and
        **zero** size rows anywhere. A ladder of prices cannot be walked, and
        filling at the touch anyway would assume unbounded size there."""
        book = remote.book_at('HTV', HTV_UNSIZED)
        assert book.bid.availability is SideAvailability.OBSERVED
        assert not book.bid.has_sizes

        walk = _walk(book, side=Side.SELL, quantity=1000, limit=Decimal('9.0'))

        assert walk.stop is SweepStop.NO_SIZES
        assert walk.missing == frozenset({DataField.BOOK_SIZE})
        assert walk.remainder_status is Remainder.INDETERMINATE

    def test_the_same_ticker_day_is_sizeable_through_the_other_prefix(
            self, local, remote):
        """Which is why the refusal above is about a *window*, not a source.
        HTV Nov 2022 lives in both prefixes with the same price rows; only
        `local_quote` carries its sizes."""
        assert not remote.coverage('HTV', date(2022, 11, 9)).serves_depth
        assert local.coverage('HTV', date(2022, 11, 9)).serves_depth

    def test_a_crossed_book_is_refused_rather_than_swept(self, remote):
        """Best bid above best ask is not a market state -- it is the symptom
        of joining the two sides as-of independently. Sweeping it would fill an
        arbitrage that never existed."""
        book = remote.book_at('HPG', HPG_LOCKED)
        assert book.is_crossed

        walk = _walk(book, quantity=1000, limit=HPG_CEILING)

        assert walk.stop is SweepStop.CROSSED
        assert walk.missing == frozenset({DataField.BOOK})
        assert walk.remainder_status is Remainder.INDETERMINATE

    def test_a_stale_side_is_refused_when_the_caller_set_a_budget(self, local):
        """HTV at 09:19:15 shows a three-level ask ladder that is 259.7 s old.
        With no budget it sweeps; with a 60 s budget it is INDETERMINATE, and
        the reason gives the age against the budget."""
        book = local.book_at('HTV', HTV_STALE)
        assert book.ask.age.total_seconds() == pytest.approx(259.7, abs=0.1)

        permissive = _walk(book, quantity=100, limit=Decimal('11.4'),
                           max_staleness=None)
        strict = _walk(book, quantity=100, limit=Decimal('11.4'),
                       max_staleness=timedelta(seconds=60))

        assert permissive.filled_quantity == 100
        assert strict.stop is SweepStop.STALE
        assert strict.missing == frozenset({DataField.BOOK})
        assert 'no deletion record' in strict.reason

    def test_the_staleness_budget_has_no_default(self, local):
        """It changes which orders are answerable, so the caller makes it. The
        same argument `ProbabilisticFillPolicy` makes for `max_participation`.
        """
        book = local.book_at('FPT', FPT_CLEAN)
        with pytest.raises(TypeError):
            walk_book(book, side=Side.BUY, limit=Decimal('73.9'),
                      quantity=100, queue=OptimisticQueue(), order_id='O-1')

    def test_the_cross_side_skew_is_reported_on_every_walk(self, local):
        """Never gates anything -- an aggressor needs one side -- but a sweep
        taken from a book whose two halves are four minutes apart is a weaker
        claim and the caller has to be able to see it. HTV's is 259.7 s here.
        """
        book = local.book_at('HTV', HTV_STALE)
        walk = _walk(book, quantity=100, limit=Decimal('11.4'))

        assert walk.cross_side_skew.total_seconds() == pytest.approx(
            259.7, abs=0.1)
        assert walk.resting_age == book.ask.age

    def test_a_level_whose_size_lags_its_price_is_flagged_on_the_tranche(
            self, local):
        """Measured property 4 of the depth adapter, carried through to the
        trade log: 2.28 % of FPT's bid-price rows have no size row at the same
        instant, so a fresh price can inherit the previous price's size. It
        cannot be corrected from the data, only surfaced."""
        book = local.book_at('FPT', FPT_DUPLICATE)
        walk = _walk(book, quantity=100, limit=Decimal('75.0'))

        assert walk.tranches[0].sizes_lag_price is (
            book.ask.levels[0].sizes_lag_price)
        assert walk.tranches[0].age == book.ask.levels[0].age


# ==========================================================================
# 5. The band lock -- and what one actually looks like in this corpus
# ==========================================================================

@requires_extract
class TestTheBandLock:
    """Item 3: verify the lock falls out of the walk, do not assert it.

    Verifying it produced a finding. The predicted shape -- a locked book with
    an empty ask side, so a marketable buy finds nothing and NO_FILLs -- is
    *not* what a real Vietnamese lock looks like in this data, because the
    corpus has no deletion record. What it looks like is a ghost.
    """

    def test_the_mechanical_shape_needs_no_lock_rule(self, fpt):
        """No level at or through the limit means no tranches, and nothing in
        `walk_book` consults a ceiling, a floor or `locked_side` to get there.
        """
        walk = _walk(fpt, quantity=1000, limit=Decimal('73.3'))

        assert walk.tranches == ()
        assert walk.remainder_status is Remainder.RESTS
        assert 'band lock' in walk.reason

    def test_a_real_ceiling_locked_book_is_a_ghost_not_an_empty_side(
            self, remote):
        """HPG, 2025-04-10, a limit-up session. The bid is locked at the 22.750
        ceiling with 21.6 million shares displayed, and the "best ask" is
        19.850 -- the day's **floor** -- for 29,800 shares, last quoted 904.5 s
        earlier and never updated again.

        A naive walk buys 29,800 shares at 19.850 in a market locked bid at
        22.750. That is the single most expensive mistake this module exists to
        refuse, and it is refused twice over: the book is crossed, and the side
        is stale beyond any defensible budget.
        """
        book = remote.book_at('HPG', HPG_LOCKED)

        assert book.bid.best.price == HPG_CEILING
        assert book.ask.availability is SideAvailability.OBSERVED
        assert book.ask.best.price == HPG_FLOOR
        assert book.ask.best.size == 29_800
        assert book.ask.age.total_seconds() == pytest.approx(904.5, abs=0.1)

        naive = _walk(book, quantity=10_000, limit=HPG_CEILING,
                      max_staleness=None)
        assert naive.stop is SweepStop.CROSSED
        assert naive.remainder_status is Remainder.INDETERMINATE

    def test_every_locked_book_that_day_is_refused(self, remote):
        """The measurement behind the claim, over the whole session rather than
        one instant. Of HPG's 16,707 reconstructed books on 2025-04-10, 14,775
        have the best bid at the ceiling; **every one of them** is crossed,
        **every one** shows an ask at or below the ceiling that a naive walk
        would have filled against, and none has an absent ask side.

        So on this corpus the band lock lands as INDETERMINATE, not as the
        NO_FILL the brief predicted. Both are honest; only one is available.
        """
        locked = crossed = fillable = absent = 0
        for book in remote.books('HPG', datetime(2025, 4, 10, 9, 0),
                                 datetime(2025, 4, 10, 15, 0)):
            best_bid = book.bid.best
            if best_bid is None or best_bid.price < HPG_CEILING:
                continue
            locked += 1
            crossed += book.is_crossed
            if book.ask.availability is not SideAvailability.OBSERVED:
                absent += 1
            elif any(level.price <= HPG_CEILING for level in book.ask.levels):
                fillable += 1

        assert locked == 14_775
        assert crossed == 14_775
        assert fillable == 14_775
        assert absent == 0

    def test_a_locked_side_is_refused_at_fill_time(self, local):
        """The asymmetry item 3 names, closed.

        `exchanges/equity.py`'s BAND_LOCK rule refuses a marketable order at
        **entry**; nothing read `state.locked_side` afterwards, so the identical
        order, already resting, filled at the same instant. It no longer does.
        """
        order = _order(limit=Decimal('78.1'), quantity=1000)
        interval = _interval(locked_side=Side.BUY,
                             lock_evidence=LockEvidence.TICK_BOOK)

        decision = _decide(local, order=order, interval=interval)

        assert decision.outcome is FillOutcome.NO_FILL
        assert 'BAND_LOCK' in decision.reason
        assert 'a resting order do what a new one may not' in decision.reason

    def test_a_lock_on_the_other_side_says_nothing_about_this_order(self, local):
        """One direction only. A lock may refuse a fill; it may never authorise
        one, and a lock against sellers is not a fact about a buy."""
        order = _order(limit=Decimal('73.9'), quantity=1000)
        interval = _interval(locked_side=Side.SELL,
                             lock_evidence=LockEvidence.TICK_BOOK)

        decision = _decide(local, order=order, interval=interval)

        assert decision.outcome is FillOutcome.FILL

    def test_an_order_inside_the_band_is_not_refused_by_a_lock(self, local):
        """Marketability through the lock is the same predicate admission uses:
        a buy at 73.900 does not cross a 78.100 ceiling, so the lock does not
        reach it."""
        order = _order(limit=Decimal('73.9'), quantity=1000)
        interval = _interval(locked_side=Side.BUY,
                             lock_evidence=LockEvidence.TICK_BOOK)

        assert _decide(local, order=order,
                       interval=interval).outcome is FillOutcome.FILL

    def test_an_unproven_lock_is_indeterminate_not_a_refusal(self, local):
        """`LockEvidence.UNKNOWN` means the lock rests on no book and no bar
        proxy. Admission returns INDETERMINATE there and so does this."""
        order = _order(limit=Decimal('78.1'), quantity=1000)
        interval = _interval(locked_side=Side.BUY,
                             lock_evidence=LockEvidence.UNKNOWN)

        decision = _decide(local, order=order, interval=interval)

        assert decision.outcome is FillOutcome.INDETERMINATE
        assert decision.missing == frozenset({DataField.BOOK})


# ==========================================================================
# 6. Composition with the participation cap
# ==========================================================================

@requires_extract
class TestTheCapAndTheWalk:
    """Two different bounds, both of which hold. Order of application matters.

    The walk bounds by *visible depth at prices through the limit*; the cap
    bounds by *our share of the volume the interval traded*. Neither implies
    the other, and the walk runs first.
    """

    def test_an_uncapped_policy_takes_the_whole_walk(self, local):
        order = _order(quantity=6000, limit=Decimal('73.9'))
        decision = _decide(local, order=order, cap=None)

        assert decision.quantity == 6000
        assert decision.walk.bound is Bound.WALK

    def test_the_cap_trims_the_sweep_from_the_best_price_outward(self, local):
        """A cap of 0.001 of 1,000,000 traded allows 1,000 shares. Those 1,000
        are necessarily the *first* 1,000 of the sweep: price-time priority
        means level 2 cannot be reached until level 1 is cleared, so trimming
        from the far end is forced rather than chosen."""
        order = _order(quantity=6000, limit=Decimal('73.9'))
        decision = _decide(local, order=order, cap=Decimal('0.001'))

        assert decision.quantity == 1000
        assert [(t.price, t.quantity) for t in decision.walk.tranches] == [
            (Decimal('73.400000'), 1000)]
        assert decision.walk.bound is Bound.PARTICIPATION
        assert decision.price == Decimal('73.400000')

    def test_the_cap_binding_removes_the_walks_depth_ignorance(self, local):
        """An order stopped at 1,000 of an available 6,900 never reached level
        3, so there is nothing left for the invisible level 4 to have decided.
        Uncapped the same order carries 1,100 shares of ignorance."""
        order = _order(quantity=8000, limit=Decimal('73.9'))

        uncapped = _decide(local, order=order, cap=None)
        capped = _decide(local, order=order, cap=Decimal('0.001'))

        assert uncapped.walk.indeterminate_quantity == 1100
        assert capped.walk.indeterminate_quantity == 0
        assert capped.walk.remainder_status is Remainder.RESTS

    def test_the_walk_runs_first_so_an_unmarketable_order_needs_no_volume(
            self, local):
        """Testing size first would report ignorance about an order the book is
        perfectly clear about. `HardFillPolicy` orders its two tests the same
        way and for the same reason; keeping them identical is what makes the
        two arms' ignorance rates comparable."""
        order = _order(quantity=1000, limit=Decimal('73.3'))
        interval = _interval(volume=None, missing=(DataField.VOLUME,))

        decision = _decide(local, order=order, interval=interval,
                           cap=Decimal('0.10'))

        assert decision.outcome is FillOutcome.NO_FILL
        assert decision.missing == frozenset()

    def test_a_sweep_the_cap_cannot_bound_is_indeterminate_naming_volume(
            self, local):
        """The order of the two bounds, from the other side: the book settled
        that 6,000 shares were there, and it is the *cap* that cannot be
        computed, so the ignorance is about our entitlement and names VOLUME.
        """
        order = _order(quantity=6000, limit=Decimal('73.9'))
        interval = _interval(volume=None, missing=(DataField.VOLUME,))

        decision = _decide(local, order=order, interval=interval,
                           cap=Decimal('0.10'))

        assert decision.outcome is FillOutcome.INDETERMINATE
        assert decision.missing == frozenset({DataField.VOLUME})
        assert 'entitled' in decision.reason
        # The walk is still attached, so what the book said is not lost.
        assert decision.walk.filled_quantity == 6000

    def test_an_exhausted_cap_is_a_definite_no_fill(self, local):
        """Nothing is unknown: the policy established how much this caller was
        entitled to and it is zero."""
        order = _order(quantity=6000, limit=Decimal('73.9'))
        decision = _decide(local, order=order, cap=Decimal('0.001'),
                           interval=_interval(volume=1_000_000))
        assert decision.quantity == 1000

        policy = _policy(local, cap=Decimal('0.001'))
        exhausted = policy.evaluate(order, _interval(volume=1_000_000),
                                    HSX_EXCHANGE, already_filled=1000,
                                    instrument=HSX_LOT)
        assert exhausted.outcome is FillOutcome.NO_FILL
        assert 'whatever the book showed' in exhausted.reason

    def test_the_round_lot_floors_the_total_not_each_tranche(self, local):
        """Three tranches each floored to a lot would silently lose up to three
        lots of an order the book can genuinely fill.

        A drawn queue gives FPT's three levels 4,312 + 65 + 342 = **4,719**.
        Flooring the total gives 4,700. Flooring each tranche gives 4,300 + 0 +
        300 = 4,600 -- a whole lot lost, and the level-2 tranche deleted
        outright because 65 is below one lot on its own.
        """
        order = _order(quantity=6000, limit=Decimal('73.9'))
        raw = _walk(local.book_at('FPT', FPT_CLEAN), quantity=6000,
                    queue=ProbabilisticQueue(SEED))
        assert [t.quantity for t in raw.tranches] == [4312, 65, 342]

        decision = _decide(local, order=order, cap=None,
                           queue=ProbabilisticQueue(SEED))

        assert [t.quantity for t in decision.walk.tranches] == [4312, 65, 323]
        assert decision.quantity == 4700
        assert decision.walk.bound is Bound.ROUND_LOT

    def test_the_round_lot_does_not_erase_the_walks_depth_ignorance(self, local):
        """The two bounds are not interchangeable. Flooring to a lot rounds
        *our own* quantity and says nothing about the book, so an order that
        ate all three visible levels and was then floored from 4,719 to 4,700
        is still an order that could not see past level 3.

        The participation cap is the other case and behaves oppositely: it
        binds whatever the book held, so an order it stops never reached the
        end of the ladder and has no depth ignorance left to report.
        """
        order = _order(quantity=6000, limit=Decimal('73.9'))
        decision = _decide(local, order=order, cap=None,
                           queue=ProbabilisticQueue(SEED))

        assert decision.walk.bound is Bound.ROUND_LOT
        assert decision.walk.stop is SweepStop.EXHAUSTED
        assert decision.walk.remainder_status is Remainder.INDETERMINATE
        assert decision.walk.missing == frozenset({DataField.BOOK})
        assert decision.walk.indeterminate_quantity == 1300

    def test_a_capped_quantity_below_one_lot_is_a_no_fill(self, local):
        order = _order(quantity=6000, limit=Decimal('73.9'))
        decision = _decide(local, order=order, cap=Decimal('0.00001'))

        assert decision.outcome is FillOutcome.NO_FILL
        assert 'below one round lot' in decision.reason

    def test_a_fill_or_kill_order_is_all_or_nothing(self, local):
        """For an MOK, "1,000 of your 6,000 would have traded" is the finding
        that it could not be filled in full, which rulebook 2.3 answers with a
        kill. The state machine refuses a partially filled MOK outright, so
        proposing one is unsatisfiable."""
        order = _order(quantity=6000, limit=Decimal('73.5'),
                       tif=TimeInForce.FILL_OR_KILL)
        decision = _decide(local, order=order, cap=None)

        assert decision.outcome is FillOutcome.NO_FILL
        assert 'fill-or-kill' in decision.reason

    def test_an_unresolvable_round_lot_is_indeterminate(self, local):
        """Nothing silently defaults: a quantity floored to a lot nobody has
        established would be a definite fill sized by a guess."""
        order = _order(quantity=6000, limit=Decimal('73.9'))
        spec = InstrumentSpec(ticker='FPT', exchange_code='XXXX',
                              kind=InstrumentKind.STOCK, trading_unit=0,
                              daily_trading_limit=Decimal('0.07'))
        policy = _policy(local, cap=Decimal('0.10'))
        decision = policy.evaluate(order, _interval(), _NoLotExchange(),
                                   instrument=spec)

        assert decision.outcome is FillOutcome.INDETERMINATE
        assert 'no round lot is known' in decision.reason


class _NoLotExchange:
    """An exchange whose venue has no dated trading unit. Not a market state --
    a venue this package cannot size a fill on."""

    class _Spec:
        code = 'XXXX'

    spec = _Spec()


# ==========================================================================
# 7. The policy surface
# ==========================================================================

@requires_extract
class TestThePolicy:

    def test_every_decision_carries_the_policy_and_its_assumptions(self, local):
        """A fill can never be reported without the assumptions that produced
        it -- the queue, the cap and the staleness budget are all in the stamp.
        """
        decision = _decide(local, queue=ProbabilisticQueue(SEED),
                           cap=Decimal('0.10'), stale=timedelta(seconds=30))

        signature = policy_of(decision)
        assert signature == (
            'book_walk(queue=probabilistic(seed=20220329,ahead=uniform),'
            'max_participation=0.10,max_staleness=30.0s,tape=off,auction=off)')
        assert str(SEED) in signature

    def test_the_evidence_of_a_sweep_is_modelled(self, local):
        """Every sweep is queue-estimated -- optimistic estimates our position
        as zero, which is an estimate. Recording it as TRADED_THROUGH would
        claim a print the walk never consulted; it reads a resting book, not a
        tape."""
        decision = _decide(local)

        assert decision.evidence is FillEvidence.MODELLED

    def test_the_decision_price_is_the_sweeps_worst_price(self, local):
        """The lossy projection onto a type that carries one price, made in the
        restrictive direction and onto the tick grid: a buy is booked at the
        highest price it swept. The exact cash is on the walk."""
        decision = _decide(local, order=_order(quantity=6000,
                                               limit=Decimal('73.9')))

        assert decision.price == Decimal('73.900000')
        assert decision.walk.consideration == Decimal('440470.000000')
        assert decision.walk.worst_price == decision.price

    def test_a_sell_is_booked_at_the_lowest_price_it_swept(self, local):
        decision = _decide(local, order=_order(side=Side.SELL, quantity=5000,
                                               limit=Decimal('73.2')))

        assert decision.price == Decimal('73.200000')

    def test_a_swept_decision_is_a_fill_decision(self, local):
        """Everything downstream that expects a `FillDecision` gets one; only
        code that knows about depth reads `.walk`."""
        from plutus.market.session.types import FillDecision

        decision = _decide(local)
        assert isinstance(decision, FillDecision)
        assert isinstance(decision, SweptFillDecision)

    def test_a_daily_interval_cannot_be_swept(self, local):
        """A book is an instantaneous object and a daily bar is stamped
        midnight; forward-filling a ladder to it would answer with the previous
        session's book."""
        decision = _decide(local, interval=_interval(
            resolution=Resolution.DAILY))

        assert decision.outcome is FillOutcome.INDETERMINATE
        assert decision.missing == frozenset({DataField.BOOK})
        assert 'no instant' in decision.reason

    def test_an_auction_is_never_swept(self, local):
        """ATO/ATC cross at one price for everyone. The corpus agrees loudly:
        15 of 26 reconstructed opening-auction books are crossed.

        The identical order in the continuous session sweeps 6,000 shares off
        this same ladder, so this is a refusal about the *mechanic* and not
        about the book being unavailable.
        """
        decision = _decide(local, interval=_interval(
            session=SessionPhase.OPENING_AUCTION))

        assert decision.outcome is FillOutcome.INDETERMINATE
        assert decision.quantity == 0
        assert not isinstance(decision, SweptFillDecision)
        assert SWEEP_IS_CONTINUOUS_ONLY in decision.reason
        assert _decide(local).quantity == 6000

    def test_an_auction_delegate_decides_the_cross_and_is_attributed(
            self, local):
        """The intended composition. The delegate's own signature is stamped
        inside this one's, so a decision says which arm decided it."""
        policy = _policy(local, auction=SoftFillPolicy())
        interval = _interval(session=SessionPhase.OPENING_AUCTION)
        interval = interval.__class__(
            **{**interval.__dict__, 'open': Decimal('73.0')})

        decision = policy.evaluate(_order(), interval, HSX_EXCHANGE,
                                   instrument=HSX_LOT)

        assert decision.outcome is FillOutcome.FILL
        assert policy_of(decision).startswith('book_walk(')
        assert 'soft(max_participation=uncapped)' in decision.reason

    def test_the_noon_break_is_a_definite_no_fill(self, local):
        """Inherited from the shared phase gate, and worth pinning: a shut
        market is not undecidable."""
        decision = _decide(local, interval=_interval(
            session=SessionPhase.NOON_BREAK))

        assert decision.outcome is FillOutcome.NO_FILL

    def test_sweep_ignorance_totals_what_the_shipped_meter_cannot_see(
            self, local):
        """`exchange.py` counts `decision.missing` only on an INDETERMINATE
        outcome, so a partial fill whose remainder is unknowable reports as a
        clean fill. Until that is a two-line change there, this is the stopgap.
        """
        decision = _decide(local, order=_order(quantity=8000,
                                               limit=Decimal('73.9')))

        assert decision.outcome is FillOutcome.FILL
        assert decision.missing == frozenset()
        assert sweep_ignorance([decision]) == 1100
        # A decision from any other policy contributes nothing.
        assert sweep_ignorance([SoftFillPolicy().evaluate(
            _order(), _interval(), HSX_EXCHANGE, instrument=HSX_LOT)]) == 0

    def test_the_three_assumptions_have_no_default(self, local):
        """Each changes which orders are answerable, so the caller names it --
        the queue, the participation cap and the staleness budget."""
        with pytest.raises(TypeError):          # no max_staleness
            BookWalkFillPolicy(local, queue=OptimisticQueue(),
                               max_participation=None)
        with pytest.raises(TypeError):          # no queue
            BookWalkFillPolicy(local, max_participation=None,
                               max_staleness=None)
        with pytest.raises(TypeError):          # no max_participation
            BookWalkFillPolicy(local, queue=OptimisticQueue(),
                               max_staleness=None)

    def test_a_float_participation_is_refused(self, local):
        """House rule, inherited unchanged from `_CappedFillPolicy` so the two
        cannot drift: a binary fraction of a share count is a rounding bug
        waiting for a large volume."""
        with pytest.raises(TypeError, match='must be a Decimal'):
            _policy(local, cap=0.10)

    def test_a_negative_staleness_budget_is_refused(self, local):
        with pytest.raises(ValueError, match='must not be negative'):
            _policy(local, stale=timedelta(seconds=-1))

    def test_a_queue_signature_that_would_break_the_stamp_is_refused(
            self, local):
        """`stamp_policy` writes `'<signature>: <why>'`, so a signature holding
        the separator would make the stamp unreadable -- worse than absent,
        because it looks present."""
        class _Bad:
            signature = 'oops: here'

            def claim(self, request):
                return QueueClaim(0, True, '')

        with pytest.raises(ValueError, match='unreadable'):
            _policy(local, queue=_Bad())

    def test_the_policy_satisfies_the_fill_policy_protocol(self, local):
        """The seam's load-bearing claim: a new family of policy needed no
        change to `FillPolicy.evaluate`'s signature. Depth is pulled from a
        provider the policy holds, not passed as a new argument."""
        assert isinstance(_policy(local), FillPolicy)

    def test_the_max_age_budget_reaches_the_provider(self, local):
        """One knob, applied twice: stale *levels* are dropped outward by the
        source before the walk sees them, and the side gate in `walk_book` is
        the backstop for a provider that ignores it."""
        seen = {}

        class _Recording:
            def book_at(self, ticker, ts, *, max_age=None):
                seen['max_age'] = max_age
                return local.book_at(ticker, ts, max_age=max_age)

        policy = BookWalkFillPolicy(_Recording(), queue=OptimisticQueue(),
                                    max_participation=None,
                                    max_staleness=timedelta(seconds=30))
        policy.evaluate(_order(), _interval(), HSX_EXCHANGE,
                        instrument=HSX_LOT)

        assert seen['max_age'] == timedelta(seconds=30)


class TestConfigRegistration:
    """No corpus needed."""

    def test_build_fill_policy_refuses_book_walk_with_a_useful_sentence(self):
        """`build_fill_policy` cannot build book_walk here: it has no book
        provider, and this module cannot import `book_walk` (that module imports
        this one). The session builds it at `build_book_walk_policy` with its own
        DepthSource; the queue assumption now travels in `FillPolicyConfig.queue`,
        so what is missing here is only the provider."""
        with pytest.raises(ValueError, match='needs a book provider'):
            build_fill_policy(FillPolicyConfig(kind=BOOK_WALK_KIND))

    def test_the_refusal_names_the_route_that_does_work(self):
        # The session config route, and the direct build_book_walk_policy call.
        with pytest.raises(ValueError, match='build_book_walk_policy'):
            build_fill_policy(FillPolicyConfig(kind='book_walk'))

    def test_an_unknown_kind_is_still_unknown(self):
        with pytest.raises(ValueError, match='unknown fill policy'):
            build_fill_policy(FillPolicyConfig(kind='sweep'))


class TestTheMakerAxis:
    """The queue as a **position**, and a resting order filled by the tape.

    No corpus: ``ahead`` is a pure position and ``maker_fill`` a pure function,
    so the whole maker mechanic is pinned here before any tape or session. The
    worked example is the author's: sell 500 with 1,000 already displayed at the
    price -- the front fills on the first prints, the back only once 1,000 has
    traded through, the draw in between.
    """

    def _req(self, displayed, *, side=Side.SELL, remaining=500,
             order_id='o1', price='73'):
        return QueueRequest(ticker='FPT', ts=DAY, side=side, order_id=order_id,
                            level=_level(price=price, size=displayed),
                            remaining=remaining)

    def test_the_three_positions_are_front_back_and_between(self):
        req = self._req(1000)
        assert OptimisticQueue().ahead(req).ahead == 0            # the front
        assert ConservativeQueue().ahead(req).ahead == 1000       # the back
        drawn = ProbabilisticQueue(7).ahead(req).ahead
        assert 0 <= drawn <= 1000                                 # between

    def test_front_of_queue_fills_on_the_prints(self):
        pos = OptimisticQueue().ahead(self._req(1000))
        assert maker_fill(pos, 500, 500).quantity == 500     # a 500 print fills
        assert maker_fill(pos, 300, 500).quantity == 300     # a 300 print, 300

    def test_back_of_queue_waits_for_the_queue_to_clear(self):
        pos = ConservativeQueue().ahead(self._req(1000))
        assert maker_fill(pos, 500, 500).quantity == 0       # 500 < 1000 ahead
        assert maker_fill(pos, 1200, 500).quantity == 200    # 1200-1000, capped

    def test_probabilistic_is_reproducible_and_between_the_bounds(self):
        req = self._req(1000)
        first = ProbabilisticQueue(7).ahead(req)
        assert first.ahead == ProbabilisticQueue(7).ahead(req).ahead   # seeded
        mid = maker_fill(first, 1200, 500).quantity
        opt = maker_fill(OptimisticQueue().ahead(req), 1200, 500).quantity
        con = maker_fill(ConservativeQueue().ahead(req), 1200, 500).quantity
        assert con <= mid <= opt                             # (200 <= mid <= 500)

    def test_an_unserved_tape_is_indeterminate_not_zero(self):
        pos = OptimisticQueue().ahead(self._req(1000))
        claim = maker_fill(pos, None, 500)
        assert not claim.determinate and claim.quantity == 0
        assert DataField.VOLUME in claim.missing

    def test_the_fill_never_exceeds_the_order(self):
        pos = OptimisticQueue().ahead(self._req(1000))
        assert maker_fill(pos, 100000, 500).quantity == 500

    def test_cumulative_prints_do_not_re_book_across_intervals(self):
        # prints are cumulative and plateau at 1400; a conservative maker (1000
        # ahead) owes min(500, 1400-1000) = 400 in total. Booking each interval
        # as the increment over already_filled must converge to 400 and never
        # re-book the cumulative entitlement into an over-fill.
        pos = ConservativeQueue().ahead(self._req(1000))
        booked = 0
        for prints in (500, 900, 1200, 1400, 1400):        # cumulative, plateaus
            booked += maker_fill(pos, prints, 500,
                                 already_filled=booked).quantity
        assert booked == 400, booked

    def test_zero_prints_on_a_served_tape_is_a_definite_no_fill(self):
        # 0 (served, nothing traded through) is a DETERMINATE no-fill -- the
        # order rests -- not INDETERMINATE. The distinction J34 rests on.
        pos = OptimisticQueue().ahead(self._req(1000))
        claim = maker_fill(pos, 0, 500)
        assert claim.determinate and claim.quantity == 0 and not claim.missing

    def test_the_maker_position_agrees_with_the_taker_claim(self):
        # ahead == displayed - claim.quantity for the probabilistic draw, so a
        # taker and a maker place the order in the SAME spot in the queue -- the
        # one axis, not two that can drift.
        req = self._req(1000)
        queue = ProbabilisticQueue(7)
        assert queue.ahead(req).ahead == req.displayed - queue.claim(req).quantity

    def test_negative_inputs_are_integration_bugs(self):
        pos = OptimisticQueue().ahead(self._req(1000))
        with pytest.raises(ValueError, match='print total may not be negative'):
            maker_fill(pos, -1, 500)
        with pytest.raises(ValueError, match='order_size may not be negative'):
            maker_fill(pos, 100, -1)
        with pytest.raises(ValueError, match='already_filled may not be'):
            maker_fill(pos, 100, 500, already_filled=-1)
        with pytest.raises(ValueError, match='position may not be negative'):
            QueuePosition(-1, 'x')

    def test_shipped_policies_are_maker_capable_a_taker_only_one_is_not(self):
        for policy in (OptimisticQueue(), ConservativeQueue(),
                       ProbabilisticQueue(7)):
            assert isinstance(policy, MakerQueuePolicy)

        class _TakerOnly:
            signature = 'taker'

            def claim(self, request):
                return QueueClaim(0, True, 'x')

        assert not isinstance(_TakerOnly(), MakerQueuePolicy)
        assert isinstance(_TakerOnly(), QueuePolicy)      # still a taker policy


@requires_extract
class TestTheMakerArm:
    """A resting order filled by the tape, through the policy's public surface.

    The book is the real FPT ladder at 09:16:05 (73.40x5700, 73.50x200,
    73.90x1000); the tape is a fake so the *fill maths* is what is exercised.
    A SELL at 73.90 does not cross the 73.30 bid, so it rests -- the maker arm,
    not the sweep. Order and interval share the clean instant, so the queue
    ahead is read from that book.
    """

    def _sell(self, price='73.90', quantity=500):
        return _order(side=Side.SELL, quantity=quantity, limit=Decimal(price),
                      order_id='M-1', ts=FPT_CLEAN)

    def _decide(self, policy, order):
        return policy.evaluate(order, _interval(), HSX_EXCHANGE,
                               instrument=HSX_LOT)

    def test_a_resting_sell_fills_from_the_tape_at_its_own_price(self, local):
        # Optimistic (front): 400 printed through 73.90 fills 400 of the 500,
        # at the resting price, MODELLED -- and it is NOT a sweep (no walk).
        policy = _policy(local, queue=OptimisticQueue(), tape=_FakeTape(400))
        d = self._decide(policy, self._sell())
        assert d.outcome is FillOutcome.FILL
        assert d.quantity == 400 and d.price == Decimal('73.90')
        assert d.evidence is FillEvidence.MODELLED
        assert getattr(d, 'walk', None) is None          # maker, not taker

    def test_the_back_of_the_queue_waits_for_the_displayed_to_clear(self, local):
        # Conservative: 1,000 rest ahead at 73.90 (the level's displayed size).
        # 500 prints clear nothing for us; 1,400 clear the 1,000 and fill 400.
        thin = _policy(local, queue=ConservativeQueue(), tape=_FakeTape(500))
        assert self._decide(thin, self._sell()).outcome is FillOutcome.NO_FILL
        thick = _policy(local, queue=ConservativeQueue(), tape=_FakeTape(1400))
        d = self._decide(thick, self._sell())
        assert d.outcome is FillOutcome.FILL and d.quantity == 400

    def test_a_marketable_order_still_takes_the_book(self, local):
        # A SELL at 73.00 crosses the 73.30 bid -> the taker sweep, which
        # produces a SweptFillDecision carrying a walk.
        policy = _policy(local, queue=OptimisticQueue(), tape=_FakeTape(999))
        d = self._decide(policy, _order(side=Side.SELL, quantity=500,
                                        limit=Decimal('73.00'), ts=FPT_CLEAN))
        assert getattr(d, 'walk', None) is not None      # taker, not maker

    def test_a_resting_order_with_no_tape_rests_as_a_taker_would(self, local):
        # No tape wired = a taker-only policy: an order that does not cross rests
        # (NO_FILL), the same definite outcome as before the maker arm. A tape
        # that is present but unserved is the INDETERMINATE case (below).
        policy = _policy(local, queue=OptimisticQueue(), tape=None)
        d = self._decide(policy, self._sell())
        assert d.outcome is FillOutcome.NO_FILL
        assert 'no sized tape' in (d.reason or '')

    def test_an_unserved_tape_is_indeterminate_naming_volume(self, local):
        policy = _policy(local, queue=OptimisticQueue(), tape=_FakeTape(None))
        d = self._decide(policy, self._sell())
        assert d.outcome is FillOutcome.INDETERMINATE
        assert DataField.VOLUME in d.missing

    def test_a_price_beyond_the_ladder_is_indeterminate_for_a_positioned_queue(
            self, local):
        # 74.30 is above the deepest observed ask (73.90): the queue ahead is
        # unknowable, so conservative/probabilistic refuse INDETERMINATE rather
        # than collapse to the optimistic front-of-queue.
        con = _policy(local, queue=ConservativeQueue(), tape=_FakeTape(5000))
        d = self._decide(con, self._sell(price='74.30'))
        assert d.outcome is FillOutcome.INDETERMINATE
        assert DataField.BOOK_SIZE in d.missing
        # Optimistic assumes the front, needs no book, and still fills.
        opt = _policy(local, queue=OptimisticQueue(), tape=_FakeTape(5000))
        assert self._decide(
            opt, self._sell(price='74.30')).outcome is FillOutcome.FILL

    def test_a_maker_fill_is_floored_to_a_round_lot(self, local):
        # 250 printed through, front of queue -> 250 owed, floored to 200 (the
        # HSX board lot is 100); the 50 keeps resting until a whole lot prints.
        policy = _policy(local, queue=OptimisticQueue(), tape=_FakeTape(250))
        d = self._decide(policy, self._sell())
        assert d.outcome is FillOutcome.FILL and d.quantity == 200

    def test_the_provenance_records_that_a_tape_was_used(self, local):
        policy = _policy(local, queue=OptimisticQueue(), tape=_FakeTape(400))
        assert 'tape=on' in policy.signature
