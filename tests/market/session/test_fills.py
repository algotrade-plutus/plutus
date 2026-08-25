"""The fill-policy seam, and the three policies that ship behind it.

What these tests are for. `fills.py` runs one order flow under several fill
assumptions and reports where they disagree. That reporting mode is standard --
NautilusTrader's `FillModel(prob_fill_on_limit, random_seed)`, and Forex
Strategy Builder's `InterpolationMethod` family plus its Method Comparator,
shipped in 2011 -- so nothing here is testing a novel idea. What it tests is
that the standard idea is implemented in a way a researcher can actually use:

1. the seam carries a policy family it was not written for, without the
   signature changing (`test_a_probabilistic_policy_needs_no_new_argument`);
2. a fill can never be reported without the assumption that produced it
   (`test_every_decision_carries_the_policy_that_made_it`);
3. `soft` and `hard` give *different* answers at the touch and the difference
   is exactly the queue-position assumption
   (`test_soft_and_hard_diverge_exactly_at_the_touch`), with `probabilistic`
   drawing between them and nowhere else
   (`test_probabilistic_matches_hard_everywhere_except_the_touch`);
4. a probabilistic run reproduces -- exactly, from the seed on the decision,
   independently of what else was in the run and of the order it was evaluated
   in (the whole `Reproducibility` section). A result that cannot be
   reproduced is not a result.

Prices are in thousands of dong, the corpus convention.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.exchanges.equity import HSX_EXCHANGE
from plutus.market.protocol import (BandSource, InstrumentKind, InstrumentSpec,
                                    MarketState, Order, OrderBook, OrderType,
                                    Resolution, SessionPhase, Side)
from plutus.market.session.fills import (DivergenceReport, FillPolicy,
                                         FillQuestion, HardFillPolicy,
                                         NO_MARKET_IMPACT,
                                         ProbabilisticFillPolicy,
                                         SoftFillPolicy, auction_fill_price,
                                         build_fill_policy, compare_policies,
                                         draw_key, fill_draw, floor_to_lot,
                                         participation_cap, policy_of,
                                         probabilistic_sweep, stamp_policy)
from plutus.market.session.types import (DataField, Fill, FillDecision,
                                         FillEvidence, FillOutcome,
                                         FillPolicyConfig, MarketInterval,
                                         OrderRecord, OrderState, TimeInForce,
                                         Venue)

DAY = datetime(2022, 3, 29)
LIMIT = Decimal('95.5')

#: One seed for every probabilistic test, so that a draw quoted in one test's
#: comment is the draw another test gets. Reproducibility is the property under
#: test; a per-test seed would make these tests the one place it does not hold.
SEED = 20220329

#: HOSE's round lot on this date. Passed explicitly wherever a test cares,
#: because the fallback path is itself under test.
HSX_LOT = InstrumentSpec(
    ticker='FPT', exchange_code='HSX', kind=InstrumentKind.STOCK,
    trading_unit=100, daily_trading_limit=Decimal('0.07'),
)


def _state(**kw):
    base = dict(
        ticker='FPT', ts=DAY, session=SessionPhase.CONTINUOUS,
        reference=Decimal('95.0'), ceiling=Decimal('101.6'),
        floor=Decimal('88.4'), band_source=BandSource.PUBLISHED,
        last=Decimal('95.0'),
    )
    base.update(kw)
    return MarketState(**base)


def _interval(*, low=None, high=None, close=None, volume=100_000,
              session=SessionPhase.CONTINUOUS, resolution=Resolution.TICK,
              open_=None, ticker='FPT', missing=(), book=None, last=None):
    """One evaluated interval. Volume is supplied by default because the
    absence of volume is a separate, explicitly-tested condition."""
    state = _state(ticker=ticker, session=session,
                   last=last if last is not None else close, book=book)
    return MarketInterval(
        ticker=ticker, start=DAY, end=datetime(2022, 3, 30),
        resolution=resolution, state=state, open=open_, high=high, low=low,
        close=close, volume=volume, book=book, missing=frozenset(missing),
    )


def _order(*, side=Side.BUY, quantity=1000, order_type=OrderType.LIMIT,
           limit=LIMIT, ticker='FPT', state=OrderState.RESTING, fills=(),
           order_id='O-1'):
    return OrderRecord(
        order_id=order_id, venue=Venue.HSX, state=state,
        time_in_force=TimeInForce.DAY, submitted_at=DAY, updated_at=DAY,
        fills=tuple(fills),
        order=Order(ticker=ticker, side=side, quantity=quantity,
                    order_type=order_type, limit_price=limit),
    )


#: Uncapped so that the touch is the *only* axis on which this arm differs from
#: `hard`; the capped variant is tested separately.
PROB = ProbabilisticFillPolicy(SEED, max_participation=None)

BOTH = [SoftFillPolicy(), HardFillPolicy()]
BOTH_IDS = ['soft', 'hard']

#: Everything the shared gate and the shared refusals must hold for. A policy
#: that could dodge the phase gate or return INDETERMINATE for an integration
#: bug would corrupt a comparison against the other two, so these are asserted
#: across the whole family rather than only the pair that shipped first.
ALL = BOTH + [PROB]
ALL_IDS = BOTH_IDS + ['probabilistic']

#: Draws for the default interval below, under `SEED`, quoted here once so a
#: test can say *why* it expects a fill. `fill_draw` is pure, so these are
#: constants of the source and not of a run:
#:
#:     O-1 buy @95.5  ->  0.071250298532420778   (fills at p >= 0.08)
#:     O-2 buy @95.5  ->  0.786679250047422214   (fills at p >= 0.79)
#:     O-4 buy @95.5  ->  0.449903417277303170   (fills at p=0.5, not p=0.3)
FILLS_AT_HALF = 'O-1'
MISSES_AT_HALF = 'O-2'
BETWEEN_THREE_AND_FIVE = 'O-4'


# ==========================================================================
# The seam
# ==========================================================================

@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
def test_every_shipped_policy_satisfies_the_protocol(policy):
    """`FillPolicy` is structural, so "arbitrary fill model" is checkable.

    A nominal base class would make the claim untestable from outside: only
    our own subclasses could satisfy it.
    """
    assert isinstance(policy, FillPolicy)


def test_a_probabilistic_policy_needs_no_new_argument():
    """The seam must carry a policy family it was not written for.

    `ProbabilisticFillPolicy` now ships and needed no change to `evaluate`, so
    the claim is no longer hypothetical for our own policy. This stand-in keeps
    testing the harder version of it: a *third-party* probabilistic policy,
    inheriting nothing of ours, that goes further than ours does and estimates
    a queue from `BookLevel.size`. It proves the signature suffices for that
    too -- a seed lives in `__init__`, the fill probability rides on
    `FillDecision.confidence`, a partial is a `quantity` below `remaining`, and
    the missing depth is named as `DataField.BOOK_SIZE`, which is what such a
    policy must return on every corpus available here. If this test ever needs
    a new parameter on `evaluate`, the seam was wrong.
    """

    class ProbabilisticStandIn:
        kind = 'probabilistic'

        def __init__(self, seed: int) -> None:
            self.seed = seed

        def evaluate(self, order, interval, rules, *, already_filled=0,
                     instrument=None):
            if interval.book is None or any(
                    lvl.size is None for lvl in interval.book.asks):
                return FillDecision.indeterminate(
                    'queue estimate needs book sizes', [DataField.BOOK_SIZE])
            return FillDecision.fill(order.remaining_quantity // 2, LIMIT,
                                     FillEvidence.MODELLED,
                                     confidence=Decimal('0.4'))

    policy = ProbabilisticStandIn(seed=7)
    assert isinstance(policy, FillPolicy)

    decision = policy.evaluate(_order(), _interval(low=Decimal('95.0')),
                               HSX_EXCHANGE)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert DataField.BOOK_SIZE in decision.missing


@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
def test_every_policy_can_say_it_does_not_know(policy):
    """INDETERMINATE must be reachable from *every* policy, including soft.

    Design section 13 makes the INDETERMINATE rate the bound on ignorance. If
    the optimistic arm could never return one, the rate would be a property of
    the pessimistic policy rather than of the data.
    """
    blank = _interval(close=None, last=None)
    decision = policy.evaluate(_order(), blank, HSX_EXCHANGE)
    assert decision.outcome is FillOutcome.INDETERMINATE


# ==========================================================================
# The policy stamp -- no result without its assumption
# ==========================================================================

@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
@pytest.mark.parametrize(
    'interval_kw',
    [dict(low=Decimal('95.0')),        # traded through -> fill (soft and hard)
     dict(low=Decimal('95.5')),        # touched        -> fill / indeterminate
     dict(low=Decimal('96.0')),        # never reached  -> no fill
     dict(close=None, last=None)],     # no price       -> indeterminate
    ids=['through', 'touch', 'short', 'blank'],
)
def test_every_decision_carries_the_policy_that_made_it(policy, interval_kw):
    """Section 16 assumption 5: the policy must be reported alongside any
    result derived from it.

    Enforced by the base class's template `evaluate`, not by each policy
    remembering, and asserted here across every outcome so that a future
    policy cannot leak an unstamped decision through one branch.
    """
    decision = policy.evaluate(_order(), _interval(**interval_kw),
                               HSX_EXCHANGE, instrument=HSX_LOT)
    assert policy_of(decision) == policy.signature


def test_the_hard_stamp_carries_the_participation_cap_not_just_the_kind():
    """Two caps are two assumptions and produce different fills, so the kind
    alone would not let a reader reproduce either run."""
    tight, loose = HardFillPolicy(Decimal('0.01')), HardFillPolicy(Decimal('1'))
    interval = _interval(low=Decimal('95.0'), volume=50_000)

    a = tight.evaluate(_order(), interval, HSX_EXCHANGE, instrument=HSX_LOT)
    b = loose.evaluate(_order(), interval, HSX_EXCHANGE, instrument=HSX_LOT)

    assert policy_of(a) == 'hard(max_participation=0.01)'
    assert policy_of(b) == 'hard(max_participation=1)'
    assert a.quantity == 500 and b.quantity == 1000


def test_stamping_is_idempotent_and_refuses_an_unreadable_signature():
    """A stamp that cannot be read back is worse than none: it looks present."""
    once = stamp_policy(FillDecision.no_fill('nothing traded'), 'soft')
    assert stamp_policy(once, 'soft') == once
    assert policy_of(once) == 'soft'

    with pytest.raises(ValueError):
        stamp_policy(once, 'weird: policy')
    with pytest.raises(ValueError):
        stamp_policy(once, '')


def test_an_unstamped_decision_is_attributed_to_nobody():
    """A hand-built or third-party decision reports None rather than being
    silently attributed to one of ours."""
    assert policy_of(FillDecision.no_fill('hand built')) is None
    assert policy_of(FillDecision(outcome=FillOutcome.NO_FILL)) is None


@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
def test_the_no_impact_assumption_travels_with_the_policy(policy):
    """Section 3's standing limitation must be printable from the object that
    caused it, not remembered by whoever writes the paper."""
    assert NO_MARKET_IMPACT in policy.assumptions


# ==========================================================================
# Hard, continuous session: the evidence standard
# ==========================================================================

@pytest.mark.parametrize(
    'side, extreme, expect',
    [(Side.BUY, Decimal('95.4'), FillOutcome.FILL),
     (Side.BUY, Decimal('95.5'), FillOutcome.INDETERMINATE),
     (Side.BUY, Decimal('95.6'), FillOutcome.NO_FILL),
     (Side.SELL, Decimal('95.6'), FillOutcome.FILL),
     (Side.SELL, Decimal('95.5'), FillOutcome.INDETERMINATE),
     (Side.SELL, Decimal('95.4'), FillOutcome.NO_FILL)],
)
def test_hard_fills_only_on_a_trade_strictly_through_the_limit(side, extreme,
                                                               expect):
    """The three-way split that defines the policy, on both sides.

    Through: order priority is price first, time second, with no size priority
    and no pro-rata (rulebook 2.4, QD 352 Dieu 7, 16), so a trade at a price
    worse than our resting limit could not have happened while we sat unfilled.
    At: whether we were ahead in the time queue is unrecoverable. Short: the
    interval's extreme on our side never reached the limit, so nothing traded
    at or through it -- definite.
    """
    kw = {'low': extreme} if side is Side.BUY else {'high': extreme}
    decision = HardFillPolicy().evaluate(
        _order(side=side), _interval(**kw), HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is expect


def test_the_touch_is_indeterminate_with_nothing_missing():
    """Touched-at-limit is the one INDETERMINATE that names no missing field.

    The distinction matters for `IndeterminateReport`: this is not a data gap
    that a better adapter could close, it is unrecoverable from any corpus
    without order ids. 81% of best-quote changes carry no trade, so order flow
    cannot be reconstructed even in principle from what we have.
    """
    decision = HardFillPolicy().evaluate(
        _order(), _interval(low=LIMIT), HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert decision.missing == frozenset()
    assert 'time-priority' in decision.reason


def test_a_hard_fill_is_priced_at_the_orders_own_limit():
    """Convention 1, and it is a rule rather than a convenience: a trade
    happens at the resting order's price, not the aggressor's (rulebook 2.4,
    QD 352 Dieu 6.3). Where our order would have been the aggressor the true
    price is better than our limit, so this is the conservative direction."""
    decision = HardFillPolicy().evaluate(
        _order(), _interval(low=Decimal('90.0'), close=Decimal('91.0')),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.FILL
    assert decision.price == LIMIT
    assert decision.evidence is FillEvidence.TRADED_THROUGH


def test_hard_reports_its_fill_as_certain_rather_than_inventing_a_probability():
    """Confidence is 1 on every definite decision this module makes.

    `FillDecision.confidence` exists for a policy with a distribution behind
    it. Emitting 0.7 "because it probably filled" would put an unsourced number
    into a published result; the soft/hard difference is carried by
    `FillEvidence`, which is a fact about the data.
    """
    decision = HardFillPolicy().evaluate(
        _order(), _interval(low=Decimal('95.0')), HSX_EXCHANGE,
        instrument=HSX_LOT)
    assert decision.confidence == Decimal('1')


# ==========================================================================
# Hard, sizing: the participation cap
# ==========================================================================

def test_without_volume_a_hard_fill_degrades_to_indeterminate_naming_volume():
    """The cap cannot be computed, so how much would have filled is unknown.

    This is not hypothetical: both shipped adapters leave `volume` unsupplied
    on every corpus here, so `hard` is undecidable wherever it would otherwise
    fill. That number is the honest headline, not a defect to paper over.
    """
    decision = HardFillPolicy().evaluate(
        _order(), _interval(low=Decimal('95.0'), volume=None), HSX_EXCHANGE,
        instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert decision.missing == frozenset({DataField.VOLUME})


def test_the_price_test_runs_before_the_size_test():
    """An order the market never reached is a definite NO_FILL whatever the
    volume was.

    Testing size first would raise a missing-volume INDETERMINATE for orders
    about which the data is perfectly clear, inflating the published ignorance
    rate with certainty.
    """
    decision = HardFillPolicy().evaluate(
        _order(), _interval(low=Decimal('96.0'), volume=None), HSX_EXCHANGE,
        instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.NO_FILL


def test_a_capped_quantity_is_floored_to_the_round_lot():
    """Convention 2. An unfloored cap leaves the ledger holding an odd lot that
    `ROUND_LOT` will later refuse to sell, stranding the position for a reason
    the caller cannot see from the fill that created it."""
    decision = HardFillPolicy(Decimal('0.10')).evaluate(
        _order(quantity=5000), _interval(low=Decimal('95.0'), volume=1234),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.quantity == 100          # 123 allowed, floored to 100


def test_the_cap_aggregates_across_the_callers_own_orders():
    """Convention 3. Per-order, a caller splits one order into ten and evades
    the cap, so `already_filled` carries the instrument's aggregate."""
    interval = _interval(low=Decimal('95.0'), volume=1500)   # allowance 150
    policy = HardFillPolicy(Decimal('0.10'))

    first = policy.evaluate(_order(), interval, HSX_EXCHANGE,
                            instrument=HSX_LOT)
    assert first.quantity == 100

    second = policy.evaluate(_order(), interval, HSX_EXCHANGE,
                             already_filled=100, instrument=HSX_LOT)
    assert second.outcome is FillOutcome.NO_FILL
    assert 'round lot' in second.reason


def test_an_exhausted_cap_is_a_no_fill_not_an_indeterminate():
    """Zero allowance is a definite answer under the policy's own assumption;
    only an *uncomputable* cap is ignorance."""
    decision = HardFillPolicy(Decimal('0.10')).evaluate(
        _order(), _interval(low=Decimal('95.0'), volume=1000),
        HSX_EXCHANGE, already_filled=100, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.NO_FILL


def test_hard_fills_only_what_remains_of_a_partly_filled_order():
    """A partially filled order is evaluated for what is left of it, so the
    section 12 invariant `filled + remaining == original` cannot be broken by
    a policy that re-fills the original quantity."""
    prior = Fill(fill_id='F-1', order_id='O-1', ticker='FPT', venue=Venue.HSX,
                 side=Side.BUY, quantity=700, price=LIMIT, ts=DAY,
                 evidence=FillEvidence.TRADED_THROUGH)
    decision = HardFillPolicy(Decimal('1')).evaluate(
        _order(quantity=1000, fills=[prior], state=OrderState.PARTIALLY_FILLED),
        _interval(low=Decimal('95.0'), volume=100_000), HSX_EXCHANGE,
        instrument=HSX_LOT)
    assert decision.quantity == 300


# ==========================================================================
# Hard: what it refuses to guess
# ==========================================================================

@pytest.mark.parametrize(
    'order_type',
    [OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT,
     OrderType.MARKET_FILL_OR_KILL,
     OrderType.MARKET_IMMEDIATE_OR_CANCEL],
)
def test_hard_will_not_fill_a_market_order_without_depth(order_type):
    """A market-family order walks the book from the best opposite price
    (rulebook 2.3), and how far it walks is a function of depth.
    `BookLevel.size` is None on every corpus here, so assuming it fills at the
    touch is assuming unbounded size at the best price -- a market-impact
    assumption wearing a different hat, and section 3 forbids those.
    """
    book = OrderBook(asks=(), bids=())
    decision = HardFillPolicy().evaluate(
        _order(order_type=order_type, limit=None),
        _interval(low=Decimal('90.0'), close=Decimal('95.0'), book=book),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert decision.missing == frozenset({DataField.BOOK_SIZE})


def test_a_market_order_with_no_book_at_all_names_the_book_not_its_sizes():
    """The two absences are different and `IndeterminateReport` counts them
    separately: no ladder at all, versus a ladder with no sizes."""
    decision = HardFillPolicy().evaluate(
        _order(order_type=OrderType.MARKET_IMMEDIATE_OR_CANCEL, limit=None),
        _interval(low=Decimal('90.0'), close=Decimal('95.0')),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.missing == frozenset({DataField.BOOK})


def test_a_point_price_can_prove_a_fill_but_never_disprove_one():
    """Deliberately asymmetric.

    A trade strictly through the limit is proof however it was observed. The
    absence of such a trade in a single point observation is not evidence that
    none happened, so without the interval's extreme the answer is ignorance,
    naming the extreme that was missing.
    """
    hard = HardFillPolicy()
    proved = hard.evaluate(_order(), _interval(close=Decimal('95.0')),
                           HSX_EXCHANGE, instrument=HSX_LOT)
    assert proved.outcome is FillOutcome.FILL

    unproved = hard.evaluate(_order(), _interval(close=Decimal('96.0')),
                             HSX_EXCHANGE, instrument=HSX_LOT)
    assert unproved.outcome is FillOutcome.INDETERMINATE
    assert unproved.missing == frozenset({DataField.LOW})


# ==========================================================================
# Auctions are a different mechanic
# ==========================================================================

def test_auction_price_is_the_published_open_or_close():
    """Convention 1 for the other mechanic. Which auction is decided by the
    order type first (ATO opens, ATC closes) and by the phase otherwise, so
    that an LO carried into the cross (rulebook 2.3) prices off the auction it
    actually reached."""
    opening = _interval(session=SessionPhase.OPENING_AUCTION,
                        open_=Decimal('96.0'), close=Decimal('94.0'))
    closing = _interval(session=SessionPhase.CLOSING_AUCTION,
                        open_=Decimal('96.0'), close=Decimal('94.0'))

    ato = _order(order_type=OrderType.AT_THE_OPENING, limit=None)
    atc = _order(order_type=OrderType.AT_THE_CLOSE, limit=None)

    assert auction_fill_price(ato, opening) == Decimal('96.0')
    assert auction_fill_price(atc, closing) == Decimal('94.0')
    assert auction_fill_price(_order(), closing) == Decimal('94.0')
    # No auction applies in continuous session, and an ATO reaching one is not
    # given the opening price of a bar it did not participate in.
    assert auction_fill_price(_order(), _interval(close=Decimal('94'))) is None
    assert auction_fill_price(ato, _interval(close=Decimal('94'))) is None


@pytest.mark.parametrize(
    'clearing, expect',
    [(Decimal('95.0'), FillOutcome.FILL),
     (Decimal('95.5'), FillOutcome.INDETERMINATE),
     (Decimal('96.0'), FillOutcome.NO_FILL)],
)
def test_hard_fills_an_auction_that_cleared_through_the_limit(clearing, expect):
    """The auction standard is a rule, not an inference.

    HOSE's clearing algorithm picks the price at which "every buy above and
    every sell below the chosen price fills in full" (rulebook 2.4, QD 352
    Dieu 6.2(a), verbatim, high confidence), so a through-priced order is a
    guaranteed full execution. **At** the clearing price the order is rationed,
    and rulebook 2.4 records allocation at the marginal price as UNVERIFIED for
    the ATO/ATC cross -- no Vietnamese document states it -- so that is
    ignorance, not a fill. Priced away from the cross, a call auction simply
    cannot execute it.
    """
    interval = _interval(session=SessionPhase.CLOSING_AUCTION, close=clearing,
                         volume=100_000)
    decision = HardFillPolicy().evaluate(_order(), interval, HSX_EXCHANGE,
                                         instrument=HSX_LOT)
    assert decision.outcome is expect
    if expect is FillOutcome.FILL:
        assert decision.price == clearing          # one price for everyone
        assert decision.evidence is FillEvidence.AUCTION_PRICE
    if expect is FillOutcome.INDETERMINATE:
        assert 'UNVERIFIED' in decision.reason


def test_an_ato_fills_at_the_cross_because_it_outranks_every_limit_order():
    """ATO/ATC are unpriced, added to their side's quantity at every price
    level in the cross calculation, and matched ahead of all limit orders
    (rulebook 2.4, QD 352 Dieu 14.3-14.4, unconditional to 2025-05-04). An
    auction order that reaches a cross is therefore through-priced under step
    (a) and fills in full."""
    decision = HardFillPolicy().evaluate(
        _order(order_type=OrderType.AT_THE_OPENING, limit=None),
        _interval(session=SessionPhase.OPENING_AUCTION, open_=Decimal('99.0'),
                  volume=100_000),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.FILL
    assert decision.price == Decimal('99.0')


@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
def test_an_ato_never_fills_outside_its_own_auction(policy):
    """ATO/ATC are "enterable only inside their own auction window, unfilled
    remainder auto-cancelled at the cross; never rest, never carry" (rulebook
    2.3, QD 352 Dieu 14.3(b)/14.4(b)). Reaching continuous session means
    `orders.py` has not expired it yet; the fill answer is still a definite no,
    and both policies must agree on that because it is exchange semantics
    rather than a fill assumption."""
    decision = policy.evaluate(
        _order(order_type=OrderType.AT_THE_CLOSE, limit=None),
        _interval(close=Decimal('90.0')), HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.NO_FILL
    assert 'closing_auction' in decision.reason


def test_a_missing_cross_price_is_ignorance_not_a_no_fill():
    """An absent published open may mean no cross happened or may mean the data
    does not carry it. Nothing silently defaults (design section 9), so the two
    are not collapsed."""
    decision = HardFillPolicy().evaluate(
        _order(order_type=OrderType.AT_THE_OPENING, limit=None),
        _interval(session=SessionPhase.OPENING_AUCTION, open_=None),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert decision.missing == frozenset({DataField.OPEN})


def test_hard_refuses_to_size_an_auction_fill_from_a_daily_bar():
    """A daily bar's volume covers the whole session, including continuous
    trading, so `max_participation` of it is not a bound on the auction's own
    volume. Sizing a cross from liquidity that traded hours earlier would be a
    fabricated number in the only place the policy claims precision."""
    decision = HardFillPolicy().evaluate(
        _order(),
        _interval(session=SessionPhase.CLOSING_AUCTION, close=Decimal('95.0'),
                  volume=1_000_000, resolution=Resolution.DAILY),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert decision.missing == frozenset({DataField.VOLUME})


# ==========================================================================
# The shared phase gate -- identical under both policies on purpose
# ==========================================================================

@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
def test_the_noon_break_is_a_no_fill_and_never_an_expiry(policy):
    """11:30-13:00 is a hard shutdown for entry, amendment and cancellation
    (rulebook 2.1) but resting orders survive it -- which is why `ExpiryTrigger`
    has no NOON_BREAK member. There is nothing undecidable about a shut market,
    so this is a definite NO_FILL rather than an INDETERMINATE that would
    inflate the ignorance rate once per lunch break per order.
    """
    decision = policy.evaluate(
        _order(), _interval(session=SessionPhase.NOON_BREAK,
                            low=Decimal('90.0'), close=Decimal('90.0')),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.NO_FILL
    assert 'noon_break' in decision.reason


@pytest.mark.parametrize('phase', [SessionPhase.PRE_OPEN,
                                   SessionPhase.POST_CLOSE,
                                   SessionPhase.POST_CLOSE_PLO])
@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
def test_no_matching_phase_fills_nothing(policy, phase):
    """PLO is excluded with the rest: HNX's after-hours session matches only
    PLO orders at the day's last round-lot matched price (rulebook 2.3), and
    `core.order.OrderType` carries no PLO member, so no order this package can
    represent participates in it."""
    decision = policy.evaluate(
        _order(), _interval(session=phase, low=Decimal('90.0')),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.NO_FILL


@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
@pytest.mark.parametrize(
    'kw', [dict(session=SessionPhase.UNKNOWN),
           dict(missing=[DataField.SESSION_PHASE])],
    ids=['unknown', 'declared-missing'],
)
def test_an_unknown_phase_is_indeterminate_naming_the_field(policy, kw):
    """Which matching mechanic applies cannot be established, and the phase is
    never inferred from the timestamp: a daily bar is stamped midnight and
    would infer as pre-open, rejecting an entire daily measurement."""
    decision = policy.evaluate(_order(), _interval(low=Decimal('90.0'), **kw),
                               HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert decision.missing == frozenset({DataField.SESSION_PHASE})


# ==========================================================================
# Soft -- the baseline arm, and the spread that is the deliverable
# ==========================================================================

def test_soft_fills_a_touch_in_full_and_records_that_it_did():
    """What every backtester does today. The assumption -- that we were at the
    front of the queue -- is not hidden: the fill carries
    `TOUCHED_AT_LIMIT`, so the share of a soft backtest resting on it is
    countable after the fact rather than invisible."""
    decision = SoftFillPolicy().evaluate(
        _order(quantity=1000), _interval(low=LIMIT), HSX_EXCHANGE)
    assert decision.outcome is FillOutcome.FILL
    assert decision.quantity == 1000
    assert decision.evidence is FillEvidence.TOUCHED_AT_LIMIT


def test_soft_and_hard_diverge_exactly_at_the_touch():
    """The spread the paper reports, isolated to its one cause.

    Same order, same interval, complete data: soft fills in full, hard says the
    data cannot decide. Nothing else differs -- not the phase handling, not the
    price convention -- so the difference between two runs is attributable to
    the queue-position assumption alone.
    """
    interval = _interval(low=LIMIT, volume=100_000)
    soft = SoftFillPolicy().evaluate(_order(), interval, HSX_EXCHANGE,
                                     instrument=HSX_LOT)
    hard = HardFillPolicy().evaluate(_order(), interval, HSX_EXCHANGE,
                                     instrument=HSX_LOT)

    assert soft.outcome is FillOutcome.FILL and soft.quantity == 1000
    assert soft.evidence is FillEvidence.TOUCHED_AT_LIMIT
    assert hard.outcome is FillOutcome.INDETERMINATE
    # Not a data gap: the interval is complete. The gap is queue position.
    assert hard.missing == frozenset()
    assert 'time-priority' in hard.reason
    # And each carries the assumption that produced it, so the two runs cannot
    # be compared without knowing which is which.
    assert policy_of(soft) != policy_of(hard)


def test_soft_needs_no_volume_and_no_cap():
    """The baseline arm assumes the caller's size was available whatever it
    was. Stated here as a test so the assumption is on the record and not
    merely absent from the code."""
    decision = SoftFillPolicy().evaluate(
        _order(quantity=9_999_900), _interval(low=Decimal('95.0'), volume=None),
        HSX_EXCHANGE)
    assert decision.outcome is FillOutcome.FILL
    assert decision.quantity == 9_999_900


def test_soft_still_will_not_fill_a_price_the_market_never_reached():
    """Optimistic is not unconditional: at-or-through remains a price test."""
    decision = SoftFillPolicy().evaluate(
        _order(), _interval(low=Decimal('96.0')), HSX_EXCHANGE)
    assert decision.outcome is FillOutcome.NO_FILL


def test_soft_fills_a_market_order_at_the_observed_price():
    """The backtester answer for the market family, and the counterpart to
    hard's refusal: it executes, at whatever printed, with no depth test."""
    decision = SoftFillPolicy().evaluate(
        _order(order_type=OrderType.MARKET_IMMEDIATE_OR_CANCEL, limit=None),
        _interval(close=Decimal('97.0')), HSX_EXCHANGE)
    assert decision.outcome is FillOutcome.FILL
    assert decision.price == Decimal('97.0')


def test_soft_fills_an_auction_at_the_clearing_price_including_at_the_margin():
    """Soft fills at-or-through in the auction too, so the marginal-price
    rationing that stops `hard` does not stop it."""
    decision = SoftFillPolicy().evaluate(
        _order(), _interval(session=SessionPhase.CLOSING_AUCTION, close=LIMIT),
        HSX_EXCHANGE)
    assert decision.outcome is FillOutcome.FILL
    assert decision.evidence is FillEvidence.AUCTION_PRICE


# ==========================================================================
# Conventions as free functions
# ==========================================================================

@pytest.mark.parametrize(
    'quantity, unit, expect',
    [(123, 100, 100), (100, 100, 100), (99, 100, 0), (0, 100, 0),
     (137, 1, 137),          # HNXDS trades in single contracts
     (115, 10, 110)],        # HOSE before 2021-01-04
)
def test_floor_to_lot(quantity, unit, expect):
    assert floor_to_lot(quantity, unit) == expect


@pytest.mark.parametrize('args', [(-1, 100), (100, 0), (100, -5)])
def test_floor_to_lot_refuses_nonsense_rather_than_returning_zero(args):
    """Both are integration bugs, and silently returning 0 would hide one."""
    with pytest.raises(ValueError):
        floor_to_lot(*args)


def test_participation_cap_distinguishes_no_share_from_no_answer():
    """None and 0 are different answers and must not be collapsed: 0 says "you
    have used your share", None says "the data does not say what the share
    is". The caller turns None into an INDETERMINATE naming VOLUME."""
    absent = _interval(volume=None)
    declared = _interval(volume=100, missing=[DataField.VOLUME])
    present = _interval(volume=1000)

    assert participation_cap(absent, Decimal('0.1'), 0) is None
    assert participation_cap(declared, Decimal('0.1'), 0) is None
    assert participation_cap(present, Decimal('0.1'), 100) == 0
    assert participation_cap(present, Decimal('0.1'), 500) == 0   # never < 0


def test_participation_cap_rounds_down():
    """A fractional allowance is not a share of a lot."""
    assert participation_cap(_interval(volume=1999), Decimal('0.1'), 0) == 199


def test_hard_refuses_a_float_cap_and_a_cap_outside_the_unit_interval():
    """House rule: every rate is a Decimal. A binary fraction of a share count
    is a rounding bug waiting for a large volume. Zero would make the policy
    fill nothing while still reporting itself as a fill policy."""
    with pytest.raises(TypeError):
        HardFillPolicy(0.1)
    for bad in (Decimal('0'), Decimal('-0.1'), Decimal('1.5')):
        with pytest.raises(ValueError):
            HardFillPolicy(bad)


# ==========================================================================
# Selection and the dated lot
# ==========================================================================

def test_build_fill_policy_selects_by_kind_and_carries_the_cap():
    soft = build_fill_policy(FillPolicyConfig(kind='soft'))
    hard = build_fill_policy(FillPolicyConfig(kind='hard',
                                              max_participation=Decimal('0.25')))
    assert isinstance(soft, SoftFillPolicy)
    assert isinstance(hard, HardFillPolicy)
    assert hard.max_participation == Decimal('0.25')


def test_an_unseeded_probabilistic_config_is_refused_rather_than_defaulted():
    """The seed is not defaulted and the kind is not substituted.

    This test replaces the one that pinned `probabilistic` as *deferred*; that
    behaviour is intentionally gone. Both halves of the refusal survive and are
    the same principle: an unseeded probabilistic run cannot be reproduced and
    a result that cannot be reproduced is not a result, so the config is
    refused rather than given a seed nobody recorded -- exactly as an unknown
    kind is refused rather than falling back to `soft`, which would substitute
    a different assumption for the one the caller asked for.
    """
    with pytest.raises(ValueError, match='explicit seed'):
        build_fill_policy(FillPolicyConfig(kind='probabilistic'))
    with pytest.raises(ValueError, match='unknown fill policy'):
        build_fill_policy(FillPolicyConfig(kind='optimistic'))


def test_a_seeded_probabilistic_config_builds_and_records_both_parameters():
    """The config can carry only the seed and the cap, so those two must
    survive the trip; `p_touch` cannot be configured at all today and that is
    declared in `build_fill_policy` rather than faked from another field."""
    policy = build_fill_policy(FillPolicyConfig(
        kind='probabilistic', seed=7, max_participation=Decimal('0.25')))
    assert isinstance(policy, ProbabilisticFillPolicy)
    assert policy.seed == 7
    assert policy.max_participation == Decimal('0.25')
    assert 'seed=7' in policy.signature
    assert 'max_participation=0.25' in policy.signature


def test_the_dated_instrument_lot_beats_the_frozen_exchange_spec():
    """HOSE's round lot was 10 until 2021-01-04 and `ExchangeSpec.trading_unit`
    only carries today's 100. The session passes the spec `SymbolRouter`
    resolved as of the instant, and that must win.

    The fallback's error is one-directional -- flooring to 100 when the true
    lot is 10 fills less than reality permitted, never more -- so the
    conservative policy stays conservative when the session forgets. It is
    still a fallback.
    """
    old_lot = InstrumentSpec(
        ticker='FPT', exchange_code='HSX', kind=InstrumentKind.STOCK,
        trading_unit=10, daily_trading_limit=Decimal('0.07'),
    )
    interval = _interval(low=Decimal('95.0'), volume=1190)   # allowance 119
    policy = HardFillPolicy(Decimal('0.10'))

    assert policy.evaluate(_order(), interval, HSX_EXCHANGE,
                           instrument=old_lot).quantity == 110
    assert policy.evaluate(_order(), interval, HSX_EXCHANGE).quantity == 100


# ==========================================================================
# Refusals: a bug must not be counted as market ignorance
# ==========================================================================

@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
def test_a_ticker_mismatch_raises_rather_than_reporting_ignorance(policy):
    """The INDETERMINATE rate is a headline number, so it must contain only
    real ignorance. An integration bug returned as INDETERMINATE would be
    published as a property of the Vietnamese market."""
    with pytest.raises(ValueError, match='never cross instruments'):
        policy.evaluate(_order(ticker='HPG'), _interval(low=Decimal('95.0')),
                        HSX_EXCHANGE)


@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
def test_a_negotiated_cross_is_refused(policy):
    """`Side.CROSS` is a put-through, not order matching, and its `.sign`
    returns None -- the landmine `types.signed_quantity` exists to refuse. No
    fill policy can decide one."""
    with pytest.raises(ValueError, match='negotiated'):
        policy.evaluate(_order(side=Side.CROSS),
                        _interval(low=Decimal('95.0')), HSX_EXCHANGE)


@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
def test_a_dead_order_is_refused_and_a_finished_one_simply_fills_nothing(
        policy):
    """Terminal-with-quantity-left is a session bug: `exchange.py` iterates
    live orders. Terminal-and-exhausted is ordinary and answers NO_FILL."""
    with pytest.raises(ValueError, match='dead order'):
        policy.evaluate(_order(state=OrderState.CANCELLED),
                        _interval(low=Decimal('95.0')), HSX_EXCHANGE)

    done = Fill(fill_id='F-1', order_id='O-1', ticker='FPT', venue=Venue.HSX,
                side=Side.BUY, quantity=1000, price=LIMIT, ts=DAY,
                evidence=FillEvidence.TRADED_THROUGH)
    decision = policy.evaluate(
        _order(quantity=1000, fills=[done], state=OrderState.FILLED),
        _interval(low=Decimal('95.0')), HSX_EXCHANGE)
    assert decision.outcome is FillOutcome.NO_FILL


@pytest.mark.parametrize('policy', ALL, ids=ALL_IDS)
def test_a_negative_aggregate_is_refused(policy):
    with pytest.raises(ValueError, match='already_filled'):
        policy.evaluate(_order(), _interval(low=Decimal('95.0')),
                        HSX_EXCHANGE, already_filled=-1)


# ==========================================================================
# Probabilistic: the draw, and where it is allowed to happen
# ==========================================================================

@pytest.mark.parametrize(
    'side, extreme, expect',
    [(Side.BUY, Decimal('95.4'), FillOutcome.FILL),
     (Side.BUY, Decimal('95.6'), FillOutcome.NO_FILL),
     (Side.SELL, Decimal('95.6'), FillOutcome.FILL),
     (Side.SELL, Decimal('95.4'), FillOutcome.NO_FILL)],
)
def test_probabilistic_matches_hard_everywhere_except_the_touch(side, extreme,
                                                                expect):
    """The arms must differ on one question only, or the spread between them is
    not attributable to the queue assumption.

    Both consume the same shared price test, so a trade through the limit is
    proven for both and an extreme short of it is definite for both. Only the
    touch is drawn -- and this test deliberately omits the touch row that the
    equivalent `hard` test carries, because that row is the whole difference.
    """
    kw = {'low': extreme} if side is Side.BUY else {'high': extreme}
    hard = HardFillPolicy(Decimal('1')).evaluate(
        _order(side=side), _interval(**kw), HSX_EXCHANGE, instrument=HSX_LOT)
    prob = PROB.evaluate(
        _order(side=side), _interval(**kw), HSX_EXCHANGE, instrument=HSX_LOT)

    assert hard.outcome is expect and prob.outcome is expect
    assert prob.quantity == hard.quantity
    assert prob.price == hard.price
    assert prob.evidence == hard.evidence


def test_a_touch_that_wins_the_draw_is_a_modelled_fill_carrying_its_probability():
    """The one decision this policy makes differently.

    `FillEvidence.MODELLED` exists for exactly this and no Tier 1 policy could
    emit it. `confidence` is the supplied `p_touch` rather than 1, because this
    fill rests on an assumption and the fill itself should say so -- it is
    copied onto `Fill.confidence` by `exchange.py`.
    """
    decision = PROB.evaluate(
        _order(order_id=FILLS_AT_HALF), _interval(low=LIMIT), HSX_EXCHANGE,
        instrument=HSX_LOT)

    assert decision.outcome is FillOutcome.FILL
    assert decision.quantity == 1000
    assert decision.price == LIMIT             # convention 1, unchanged
    assert decision.evidence is FillEvidence.MODELLED
    assert decision.confidence == Decimal('0.5')


def test_a_touch_that_loses_the_draw_is_a_no_fill_not_an_indeterminate():
    """"Eligible, and the draw said no" is a different fact from "the data
    cannot say whether it was eligible", and only the second is ignorance.

    Collapsing them would put the policy's own assumption into
    `IndeterminateReport` and publish it as a property of the Vietnamese
    market. Under this policy's declared assumption the answer here is settled.
    """
    decision = PROB.evaluate(
        _order(order_id=MISSES_AT_HALF), _interval(low=LIMIT), HSX_EXCHANGE,
        instrument=HSX_LOT)

    assert decision.outcome is FillOutcome.NO_FILL
    assert decision.missing == frozenset()
    assert 'seeded draw' in decision.reason


def test_a_proven_fill_is_never_drawn_for_and_stays_certain():
    """A draw where the data is decisive would throw away evidence the corpus
    actually carries, making this arm worse than `hard` rather than merely more
    optimistic. Traded-through keeps `TRADED_THROUGH` and confidence 1."""
    decision = PROB.evaluate(
        _order(), _interval(low=Decimal('95.0')), HSX_EXCHANGE,
        instrument=HSX_LOT)
    assert decision.evidence is FillEvidence.TRADED_THROUGH
    assert decision.confidence == Decimal('1')


def test_p_zero_is_not_the_hard_policy_and_p_one_is_not_the_soft_one():
    """The endpoints bracket the *fill* counts, never the ignorance counts.

    At p=0 this policy asserts the order did not fill; `hard` asserts that the
    data cannot say. Those are different claims and only `hard`'s reaches the
    indeterminate rate. At p=1 it fills, as `soft` does, but records
    `MODELLED` rather than `TOUCHED_AT_LIMIT` -- the fill rests on a drawn
    assumption, not on an observation about the queue.
    """
    interval = _interval(low=LIMIT)
    never = ProbabilisticFillPolicy(SEED, p_touch=Decimal('0'),
                                    max_participation=None)
    always = ProbabilisticFillPolicy(SEED, p_touch=Decimal('1'),
                                     max_participation=None)

    hard = HardFillPolicy().evaluate(_order(), interval, HSX_EXCHANGE,
                                     instrument=HSX_LOT)
    soft = SoftFillPolicy().evaluate(_order(), interval, HSX_EXCHANGE)

    assert never.evaluate(_order(), interval, HSX_EXCHANGE).outcome \
        is FillOutcome.NO_FILL
    assert hard.outcome is FillOutcome.INDETERMINATE

    at_one = always.evaluate(_order(), interval, HSX_EXCHANGE)
    assert at_one.outcome is FillOutcome.FILL and soft.outcome is FillOutcome.FILL
    assert at_one.evidence is FillEvidence.MODELLED
    assert soft.evidence is FillEvidence.TOUCHED_AT_LIMIT


def test_the_probability_is_per_interval_not_per_order_lifetime():
    """An order that draws a no is not killed; it rests and is re-drawn.

    So p is not a per-order fill rate, and the same run at two resolutions is
    not the same experiment at the same p. Asserted by giving one order two
    different intervals and getting two different answers out of one policy.
    """
    # O-15 draws 0.871 on the 29th and 0.207 on the 30th: it rests through the
    # first touch and fills on the second, which is what "per interval" means.
    order = _order(order_id='O-15')
    first = PROB.evaluate(order, _interval(low=LIMIT), HSX_EXCHANGE)

    later = MarketInterval(
        ticker='FPT', start=datetime(2022, 3, 30), end=datetime(2022, 3, 31),
        resolution=Resolution.TICK, state=_state(ts=datetime(2022, 3, 30)),
        low=LIMIT, volume=100_000,
    )
    second = PROB.evaluate(order, later, HSX_EXCHANGE)

    assert first.outcome is FillOutcome.NO_FILL
    assert second.outcome is FillOutcome.FILL


# ==========================================================================
# Probabilistic: what it still refuses to decide
# ==========================================================================

def test_an_unestablished_eligibility_is_still_indeterminate():
    """Probabilistic is not a licence to always decide.

    A point price short of the limit with no extreme cannot rule out a trade
    through the limit, so the data has not established that the order was even
    *eligible* to fill. There is nothing to draw for, and drawing anyway would
    invent an eligibility the corpus never showed.
    """
    decision = PROB.evaluate(_order(), _interval(close=Decimal('96.0')),
                             HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert decision.missing == frozenset({DataField.LOW})


def test_probabilistic_will_not_draw_for_a_market_order_without_depth():
    """How far a market-family order walks the book is a function of depth, and
    `BookLevel.size` is None on every corpus here. A probability drawn here
    would stand in for the depth rather than for the queue, which is a
    market-impact assumption and section 3 forbids those outright."""
    decision = PROB.evaluate(
        _order(order_type=OrderType.MARKET_IMMEDIATE_OR_CANCEL, limit=None),
        _interval(low=Decimal('90.0'), close=Decimal('95.0'),
                  book=OrderBook(asks=(), bids=())),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert decision.missing == frozenset({DataField.BOOK_SIZE})


def test_the_auction_margin_is_not_drawn_for_by_default():
    """The two unknowns are not the same kind of unknown.

    At a continuous touch the *rule* is known (price then time, no pro-rata --
    rulebook 2.4, QD 352 Dieu 7, 16, high) and only our queue position is
    missing. At an auction's clearing price the rule itself is recorded as
    UNVERIFIED for the ATO/ATC cross: no Vietnamese document states it. Drawing
    a number for an unwritten rule is a worse act than drawing one for an
    unobservable queue, so it is opt-in and the default declines.
    """
    decision = PROB.evaluate(
        _order(), _interval(session=SessionPhase.CLOSING_AUCTION, close=LIMIT),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert 'UNVERIFIED' in decision.reason
    assert 'p_auction_margin' in decision.reason


def test_the_auction_margin_can_be_modelled_on_purpose_and_the_run_says_so():
    """Opting in is legal -- and every decision the run produced then carries
    `p_auction_margin` in its stamp, so no result built on an unwritten rule
    can be reported without saying that it was."""
    policy = ProbabilisticFillPolicy(SEED, p_auction_margin=Decimal('1'),
                                     max_participation=None)
    decision = policy.evaluate(
        _order(), _interval(session=SessionPhase.CLOSING_AUCTION, close=LIMIT),
        HSX_EXCHANGE, instrument=HSX_LOT)

    assert decision.outcome is FillOutcome.FILL
    assert decision.evidence is FillEvidence.MODELLED
    assert 'p_auction_margin=1' in policy_of(decision)


def test_an_auction_that_cleared_through_the_limit_is_never_drawn_for():
    """HOSE's clearing algorithm picks the price at which "every buy above and
    every sell below the chosen price fills in full" (rulebook 2.4, QD 352 Dieu
    6.2(a), verbatim, high). A through-priced order is a rule-guaranteed full
    execution; drawing for it would replace a sourced rule with an assumption.
    """
    decision = PROB.evaluate(
        _order(), _interval(session=SessionPhase.CLOSING_AUCTION,
                            close=Decimal('95.0')),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.FILL
    assert decision.evidence is FillEvidence.AUCTION_PRICE
    assert decision.confidence == Decimal('1')


# ==========================================================================
# Probabilistic: the size assumption is a choice, and it is recorded
# ==========================================================================

def test_the_size_assumption_must_be_chosen_because_it_changes_the_answer():
    """`max_participation` is keyword-only and has no default here.

    Capped or uncapped is not a detail: on today's corpus, where both adapters
    leave `volume` unsupplied, it decides whether a would-be fill is a fill or
    an INDETERMINATE. A class that picked for the caller would be picking which
    number the paper prints.
    """
    with pytest.raises(TypeError):
        ProbabilisticFillPolicy(SEED)          # no max_participation


def test_a_capped_probabilistic_fill_degrades_like_hard_without_volume():
    """The capped arm inherits `hard`'s sizing exactly, including its honest
    failure: with no observed volume the cap cannot be computed, so how much
    would have filled cannot be established."""
    capped = ProbabilisticFillPolicy(SEED, max_participation=Decimal('0.10'))
    decision = capped.evaluate(
        _order(order_id=FILLS_AT_HALF),
        _interval(low=LIMIT, volume=None), HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.INDETERMINATE
    assert decision.missing == frozenset({DataField.VOLUME})


def test_a_capped_probabilistic_fill_is_floored_to_the_round_lot():
    """Convention 2 is shared, not reimplemented: an unfloored cap would leave
    the ledger holding an odd lot that `ROUND_LOT` later refuses to sell."""
    capped = ProbabilisticFillPolicy(SEED, max_participation=Decimal('0.10'))
    decision = capped.evaluate(
        _order(order_id=FILLS_AT_HALF, quantity=5000),
        _interval(low=LIMIT, volume=1234), HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.quantity == 100            # 123 allowed, floored to 100
    assert decision.confidence == Decimal('0.5')


def test_uncapped_takes_the_whole_size_and_says_so_in_the_signature():
    """Uncapped is the soft arm's size assumption, and it is not silent: it is
    in the signature stamped on the decision and in `assumptions`."""
    decision = PROB.evaluate(
        _order(order_id=FILLS_AT_HALF, quantity=9_999_900),
        _interval(low=LIMIT, volume=None), HSX_EXCHANGE)
    assert decision.quantity == 9_999_900
    assert 'max_participation=uncapped' in policy_of(decision)
    assert any('uncapped' in a for a in PROB.assumptions)


def test_uncapped_does_not_refuse_to_size_an_auction_from_a_daily_bar():
    """`hard` refuses because a daily bar's volume covers the whole session and
    cannot be attributed to the cross. With no cap there is no attribution to
    make, so the refusal would be a leftover rather than a reason."""
    interval = _interval(session=SessionPhase.CLOSING_AUCTION,
                         close=Decimal('95.0'), volume=1_000_000,
                         resolution=Resolution.DAILY)
    assert HardFillPolicy().evaluate(_order(), interval, HSX_EXCHANGE,
                                     instrument=HSX_LOT).outcome \
        is FillOutcome.INDETERMINATE
    assert PROB.evaluate(_order(), interval, HSX_EXCHANGE,
                         instrument=HSX_LOT).outcome is FillOutcome.FILL


def test_a_fill_or_kill_is_still_all_or_nothing_under_the_draw():
    """Shared sizing means the MOK rule cannot be lost by the new arm: "1,000
    of your 5,000 would have traded" is the finding that the order could not be
    filled in full, which rulebook 2.3 answers with a kill."""
    capped = ProbabilisticFillPolicy(SEED, max_participation=Decimal('0.10'))
    order = OrderRecord(
        order_id=FILLS_AT_HALF, venue=Venue.HSX, state=OrderState.RESTING,
        time_in_force=TimeInForce.FILL_OR_KILL, submitted_at=DAY,
        updated_at=DAY,
        order=Order(ticker='FPT', side=Side.BUY, quantity=5000,
                    order_type=OrderType.LIMIT, limit_price=LIMIT),
    )
    decision = capped.evaluate(order, _interval(low=LIMIT, volume=1234),
                               HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.NO_FILL
    assert 'fill-or-kill' in decision.reason


# ==========================================================================
# Reproducibility -- the requirement, not a nice-to-have
# ==========================================================================

def test_the_seed_and_every_parameter_are_stamped_on_every_decision():
    """A probabilistic result without its seed cannot be reproduced, so the
    seed rides on the decision itself rather than only in a config file that
    may not travel with the result.

    Asserted across all four outcomes, including the ones no draw touched: a
    reader must not have to guess which decisions were random.
    """
    for kw in (dict(low=Decimal('95.0')),   # proven fill, no draw
               dict(low=LIMIT),             # the draw
               dict(low=Decimal('96.0')),   # definite no-fill, no draw
               dict(close=None, last=None)):  # indeterminate, no draw
        decision = PROB.evaluate(_order(), _interval(**kw), HSX_EXCHANGE,
                                 instrument=HSX_LOT)
        assert policy_of(decision) == PROB.signature
        assert f'seed={SEED}' in policy_of(decision)


def test_the_draw_is_written_on_the_decision_so_one_fill_can_be_rechecked():
    """A recorded seed lets a reader rerun the whole thing; the draw and its
    key let them recheck *one* decision without rerunning anything. Both
    numbers are on the decision, and the key is the input to `fill_draw`."""
    order = _order(order_id=MISSES_AT_HALF)
    interval = _interval(low=LIMIT)
    decision = PROB.evaluate(order, interval, HSX_EXCHANGE)

    key = draw_key(order, interval, LIMIT)
    assert key in decision.reason
    assert str(fill_draw(SEED, key)) in decision.reason
    assert fill_draw(SEED, key) == PROB.draw(order, interval, LIMIT)


def test_the_draw_is_a_fixed_function_of_the_seed_and_the_question():
    """A golden value, pinned deliberately.

    The point of the seed is that a number in a published table can be
    recovered years later, which means the draw is part of the contract and not
    an implementation detail. BLAKE2b rather than `hash()` because CPython
    salts string hashing per process under PYTHONHASHSEED, which would make a
    run irreproducible across two invocations of the same script; this literal
    was computed in a different process from the one asserting it.
    """
    key = ('O-1|FPT|2022-03-29T00:00:00|2022-03-30T00:00:00|continuous'
           '|BUY|95.5')
    assert draw_key(_order(), _interval(low=LIMIT), LIMIT) == key
    assert fill_draw(SEED, key) == Decimal('0.071250298532420778')
    assert Decimal('0') <= fill_draw(SEED, key) < Decimal('1')


def test_the_same_question_gets_the_same_answer_every_time():
    """The policy is a function. A stateful RNG advanced once per decision
    would fail this, and a policy that is not a function cannot be audited: the
    explanation you compute afterwards is not the decision that was made."""
    order, interval = _order(order_id=FILLS_AT_HALF), _interval(low=LIMIT)
    first = PROB.evaluate(order, interval, HSX_EXCHANGE)
    for _ in range(5):
        assert PROB.evaluate(order, interval, HSX_EXCHANGE) == first


def test_the_answer_does_not_depend_on_the_order_of_evaluation():
    """The failure a random stream cannot avoid.

    With a stream, the value one order receives depends on how many draws came
    before it, so the session's iteration order becomes an input to the result
    -- and a caller cannot see it, cannot record it, and cannot hold it fixed.
    Keying the draw on the question makes the run order-independent.
    """
    interval = _interval(low=LIMIT)
    ids = ['O-1', 'O-2', 'O-3', 'O-4', 'O-5']

    forward = {i: PROB.evaluate(_order(order_id=i), interval, HSX_EXCHANGE)
               for i in ids}
    backward = {i: PROB.evaluate(_order(order_id=i), interval, HSX_EXCHANGE)
                for i in reversed(ids)}
    assert forward == backward


def test_an_unrelated_order_does_not_perturb_another_orders_fills():
    """Two runs differing by one order must differ only in that order.

    Under a shared stream, inserting an order shifts every later draw, so a
    comparison of two runs would be contaminated by the shift and the reader
    would attribute it to the change they made.
    """
    interval = _interval(low=LIMIT)
    watched = _order(order_id='O-7')

    alone = PROB.evaluate(watched, interval, HSX_EXCHANGE)
    for other in ('O-1', 'O-2', 'O-3'):
        PROB.evaluate(_order(order_id=other), interval, HSX_EXCHANGE)
    crowded = PROB.evaluate(watched, interval, HSX_EXCHANGE)

    assert alone == crowded


def test_a_different_seed_gives_a_different_run():
    """The seed has to actually matter, or "seeded" is decoration."""
    interval = _interval(low=LIMIT)
    other = ProbabilisticFillPolicy(SEED + 1, max_participation=None)
    outcomes = [
        (PROB.evaluate(_order(order_id=f'O-{i}'), interval,
                       HSX_EXCHANGE).outcome,
         other.evaluate(_order(order_id=f'O-{i}'), interval,
                        HSX_EXCHANGE).outcome)
        for i in range(20)
    ]
    assert any(a is not b for a, b in outcomes)


def test_the_draws_are_spread_across_the_unit_interval():
    """A sanity check on the hash, not on the market.

    If the draw were biased, `p_touch` would not mean what the docstring says
    it means and a sweep would not bracket anything. Deterministic despite
    being a frequency test, because every draw here is a pure function.
    """
    draws = [fill_draw(SEED, f'O-{i}|FPT|x') for i in range(2000)]
    hits = sum(1 for d in draws if d < Decimal('0.5'))
    assert 900 <= hits <= 1100
    assert min(draws) < Decimal('0.01') and max(draws) > Decimal('0.99')


def test_a_sweep_is_nested_so_a_higher_p_never_unfills_a_lower_one():
    """Why the draw ignores `p_touch`, stated as a property.

    Sharing a seed across the sweep makes the family monotone: the draw is the
    same, only the threshold moves. The endpoints are then a genuine bracket on
    the assumption, rather than a set of unrelated random runs whose spread is
    partly the RNG's own variance.
    """
    interval = _interval(low=LIMIT)
    sweep = probabilistic_sweep(
        SEED, [Decimal('0.1'), Decimal('0.3'), Decimal('0.5'), Decimal('0.9')],
        max_participation=None)

    for i in range(40):
        order = _order(order_id=f'O-{i}')
        filled = [p.evaluate(order, interval, HSX_EXCHANGE).outcome
                  is FillOutcome.FILL for p in sweep]
        # Monotone: once True, never False again.
        assert filled == sorted(filled)

    # And the sweep is a real spread, not four identical runs.
    order = _order(order_id=BETWEEN_THREE_AND_FIVE)
    at = [p.evaluate(order, interval, HSX_EXCHANGE).outcome for p in sweep]
    assert at[1] is FillOutcome.NO_FILL and at[2] is FillOutcome.FILL


def test_a_sweep_refuses_to_repeat_or_to_be_empty():
    """A repeated p would produce two policies with one signature, which
    `compare_policies` cannot attribute to separate columns."""
    with pytest.raises(ValueError, match='at least one'):
        probabilistic_sweep(SEED, [], max_participation=None)
    with pytest.raises(ValueError, match='repeat'):
        probabilistic_sweep(SEED, [Decimal('0.5'), Decimal('0.5')],
                            max_participation=None)


@pytest.mark.parametrize('bad', [Decimal('-0.1'), Decimal('1.5')])
def test_a_probability_outside_the_unit_interval_is_refused(bad):
    """Unlike `max_participation`, both endpoints are legal here -- 0 and 1 are
    the ends of the bracket -- but nothing outside them is."""
    with pytest.raises(ValueError, match='p_touch'):
        ProbabilisticFillPolicy(SEED, p_touch=bad, max_participation=None)
    with pytest.raises(ValueError, match='p_auction_margin'):
        ProbabilisticFillPolicy(SEED, p_auction_margin=bad,
                                max_participation=None)


def test_a_float_probability_and_a_non_int_seed_are_refused():
    """House rule: every rate is a Decimal. And `seed=True` silently meaning
    seed 1 is a bug worth refusing rather than reproducing faithfully."""
    with pytest.raises(TypeError, match='Decimal'):
        ProbabilisticFillPolicy(SEED, p_touch=0.5, max_participation=None)
    with pytest.raises(TypeError, match='seed must be an int'):
        ProbabilisticFillPolicy('7', max_participation=None)
    with pytest.raises(TypeError, match='seed must be an int'):
        ProbabilisticFillPolicy(True, max_participation=None)


# ==========================================================================
# The comparison helper -- a standard reporting mode, applied here
# ==========================================================================

def _flow():
    """One question per interesting shape, so a comparison has something to
    disagree about: proven, touched, never reached, and undecidable."""
    return [
        FillQuestion(_order(order_id=FILLS_AT_HALF),
                     _interval(low=Decimal('95.0')), HSX_EXCHANGE,
                     instrument=HSX_LOT, label='through'),
        FillQuestion(_order(order_id=FILLS_AT_HALF), _interval(low=LIMIT),
                     HSX_EXCHANGE, instrument=HSX_LOT, label='touch-hits'),
        FillQuestion(_order(order_id=MISSES_AT_HALF), _interval(low=LIMIT),
                     HSX_EXCHANGE, instrument=HSX_LOT, label='touch-misses'),
        FillQuestion(_order(), _interval(low=Decimal('96.0')), HSX_EXCHANGE,
                     instrument=HSX_LOT, label='short'),
        FillQuestion(_order(), _interval(close=None, last=None), HSX_EXCHANGE,
                     instrument=HSX_LOT, label='blank'),
    ]


def test_the_comparator_reports_where_the_arms_disagree_and_where_they_do_not():
    """The tool, doing its job.

    Not a novel reporting mode -- Forex Strategy Builder shipped a Method
    Comparator over an `InterpolationMethod` family in 2011, and
    NautilusTrader's `FillModel` carries the same axis. What is checked here is
    that it isolates the disagreement: the arms agree on the proven fill, on
    the price the market never reached and on the interval with no price at
    all, and diverge only where the assumption differs.
    """
    report = compare_policies([SoftFillPolicy(), HardFillPolicy(Decimal('1')),
                               PROB], _flow())

    assert isinstance(report, DivergenceReport)
    assert report.questions == 5
    by_name = {row.name: row for row in report.rows}
    assert by_name['through'].agreed
    assert by_name['short'].agreed
    assert by_name['blank'].agreed
    assert not by_name['touch-hits'].agreed
    assert not by_name['touch-misses'].agreed
    assert {row.name for row in report.divergent} == {'touch-hits',
                                                      'touch-misses'}
    assert report.agreement_rate == Decimal('3') / Decimal('5')


def test_the_comparator_reports_each_arms_own_ignorance_rate():
    """The measurement the whole package exists to make, per policy.

    `hard` cannot decide either touch; `soft` and `probabilistic` can. Only the
    blank interval defeats all three, so the three rates differ by exactly the
    queue assumption.
    """
    soft, hard = SoftFillPolicy(), HardFillPolicy(Decimal('1'))
    report = compare_policies([soft, hard, PROB], _flow())

    assert report.indeterminate_rate(soft.signature) == Decimal('1') / Decimal('5')
    assert report.indeterminate_rate(hard.signature) == Decimal('3') / Decimal('5')
    assert report.indeterminate_rate(PROB.signature) == Decimal('1') / Decimal('5')

    counts = report.outcomes(PROB.signature)
    assert counts[FillOutcome.FILL] == 2
    assert counts[FillOutcome.NO_FILL] == 2
    assert counts[FillOutcome.INDETERMINATE] == 1


def test_the_comparator_counts_a_quantity_difference_as_divergence():
    """Two policies that both say FILL, for 1,000 and for 100 shares, have
    diverged. Scoring that as agreement would hide the entire effect of the
    participation cap, which is one of the two axes the tool exists to show."""
    question = FillQuestion(_order(order_id=FILLS_AT_HALF),
                            _interval(low=Decimal('95.0'), volume=1000),
                            HSX_EXCHANGE, instrument=HSX_LOT, label='capped')
    report = compare_policies(
        [SoftFillPolicy(), HardFillPolicy(Decimal('0.10'))], [question])

    row = report.rows[0]
    assert row.outcomes_agree            # both say FILL
    assert not row.agreed                # 1000 vs 100
    assert report.agreement_rate == Decimal('0')


def test_the_comparator_reports_filled_quantity_and_never_a_return():
    """Quantity is a statement the exchange can make; P&L is not.

    This package is the counterparty, not a backtester (design section 3), so
    the spread reported here is in shares. What the spread was worth is the
    caller's arithmetic on the caller's side of the boundary.
    """
    soft, hard = SoftFillPolicy(), HardFillPolicy(Decimal('1'))
    report = compare_policies([soft, hard, PROB], _flow())

    assert report.filled_quantity(soft.signature) == 3000     # all three fills
    assert report.filled_quantity(hard.signature) == 1000     # only the proven
    assert report.filled_quantity(PROB.signature) == 2000     # proven + a draw

    assert not hasattr(report, 'pnl')
    assert not hasattr(report, 'sharpe')


def test_the_comparator_carries_every_arms_assumptions():
    """Section 16 requires the fill assumption to travel with the result, and a
    table of three columns is three assumptions, not one."""
    soft = SoftFillPolicy()
    report = compare_policies([soft, HardFillPolicy(), PROB], _flow())

    assert set(report.assumptions) == set(report.signatures)
    assert all(NO_MARKET_IMPACT in a for a in report.assumptions.values())
    assert any('p_touch' in a
               for a in report.assumptions[PROB.signature])
    assert any('optimistic bound' in a
               for a in report.assumptions[soft.signature])


def test_the_comparator_refuses_two_policies_it_could_not_tell_apart():
    """Columns are keyed by signature, so a duplicate would silently overwrite
    the first in every row and the table could attribute neither."""
    with pytest.raises(ValueError, match='share the signature'):
        compare_policies([HardFillPolicy(Decimal('0.1')),
                          HardFillPolicy(Decimal('0.1'))], _flow())

    # Different parameters are a legitimate two-column comparison.
    report = compare_policies([HardFillPolicy(Decimal('0.1')),
                               HardFillPolicy(Decimal('1'))], _flow())
    assert len(report.signatures) == 2


def test_a_comparison_of_one_policy_is_an_error_not_a_clean_bill():
    """A report that always says "100% agreement" is worse than an error,
    because it looks like a finding."""
    with pytest.raises(ValueError, match='at least two policies'):
        compare_policies([PROB], _flow())


def test_an_empty_flow_reports_no_rate_rather_than_perfect_agreement():
    """0/0 is not 100%. Reporting it as such is how an empty run gets published
    as a clean one -- the same reason `IndeterminateReport.rate` is Optional."""
    report = compare_policies([SoftFillPolicy(), HardFillPolicy()], [])
    assert report.questions == 0
    assert report.agreement_rate is None
    assert report.indeterminate_rate(SoftFillPolicy().signature) is None


def test_the_comparator_does_not_swallow_an_integration_bug():
    """A ticker mismatch is a bug, and a bug rendered as a table cell would be
    published as a divergence between assumptions."""
    bad = FillQuestion(_order(ticker='HPG'), _interval(low=LIMIT), HSX_EXCHANGE)
    with pytest.raises(ValueError, match='never cross instruments'):
        compare_policies([SoftFillPolicy(), HardFillPolicy()], [bad])


def test_the_flow_order_does_not_change_the_comparison():
    """Nothing here depends on the sequence questions arrive in -- which is
    only true because the probabilistic arm is order-independent too."""
    policies = [SoftFillPolicy(), HardFillPolicy(Decimal('1')), PROB]
    forward = compare_policies(policies, _flow())
    backward = compare_policies(policies, list(reversed(_flow())))

    assert forward.agreement_rate == backward.agreement_rate
    assert ({r.name: r.decisions for r in forward.rows}
            == {r.name: r.decisions for r in backward.rows})


def test_the_printed_table_names_the_policies_not_their_kinds():
    """A comparison printed without the parameters that produced it is
    unattributable, so the header is the signature -- seed included."""
    report = compare_policies([SoftFillPolicy(), HardFillPolicy(), PROB],
                              _flow())
    text = report.table()

    assert f'seed={SEED}' in text
    assert 'hard(max_participation=0.10)' in text
    assert 'diverges' in text
    assert 'indeterminate' in text
    assert 'touch-hits' in text


def test_a_question_labels_itself_when_the_caller_does_not():
    """A row nobody can identify is not a report."""
    question = FillQuestion(_order(), _interval(low=LIMIT), HSX_EXCHANGE)
    assert question.name == f'O-1@{DAY}'
    assert FillQuestion(_order(), _interval(low=LIMIT), HSX_EXCHANGE,
                        label='mine').name == 'mine'


def test_the_comparator_accepts_a_policy_that_is_not_one_of_ours():
    """`FillPolicy` is structural, so the comparison must work on a third-party
    policy -- otherwise "compare against your own fill model" is not a claim
    the tool can honour."""

    class AlwaysFills:
        kind = 'stub'

        def evaluate(self, order, interval, rules, *, already_filled=0,
                     instrument=None):
            return FillDecision.fill(order.remaining_quantity, LIMIT,
                                     FillEvidence.MODELLED)

    report = compare_policies([HardFillPolicy(Decimal('1')), AlwaysFills()],
                              _flow())
    assert 'stub' in report.signatures
    assert report.assumptions['stub'] == ()
    assert report.filled_quantity('stub') == 5000
