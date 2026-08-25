"""The fill-policy seam, and the two policies that ship behind it.

What these tests are for. `fills.py` is the module design section 8 calls the
product's selling point: a strategy is run under several fill assumptions and
the *spread* between the results is the deliverable. That makes two things
testable that are usually only assertable --

1. that the seam can carry a policy family it was not written for, without the
   signature changing (`test_a_probabilistic_policy_needs_no_new_argument`);
2. that a fill can never be reported without the assumption that produced it
   (`test_every_decision_carries_the_policy_that_made_it`).

and one thing that is the whole point of the exercise: `soft` and `hard` must
give *different* answers at the touch, and the difference must be exactly the
queue-position assumption (`test_soft_and_hard_diverge_exactly_at_the_touch`).

Prices are in thousands of dong, the corpus convention.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.exchanges.equity import HSX_EXCHANGE
from plutus.market.protocol import (BandSource, InstrumentKind, InstrumentSpec,
                                    MarketState, Order, OrderBook, OrderType,
                                    Resolution, SessionPhase, Side)
from plutus.market.session.fills import (FillPolicy, HardFillPolicy,
                                         NO_MARKET_IMPACT, SoftFillPolicy,
                                         auction_fill_price, build_fill_policy,
                                         floor_to_lot, participation_cap,
                                         policy_of, stamp_policy)
from plutus.market.session.types import (DataField, Fill, FillDecision,
                                         FillEvidence, FillOutcome,
                                         FillPolicyConfig, MarketInterval,
                                         OrderRecord, OrderState, TimeInForce,
                                         Venue)

DAY = datetime(2022, 3, 29)
OPEN_TS = datetime(2022, 3, 29, 9, 15)
LIMIT = Decimal('95.5')

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
           limit=LIMIT, ticker='FPT', state=OrderState.RESTING, fills=()):
    return OrderRecord(
        order_id='O-1', venue=Venue.HSX, state=state,
        time_in_force=TimeInForce.DAY, submitted_at=DAY, updated_at=DAY,
        fills=tuple(fills),
        order=Order(ticker=ticker, side=side, quantity=quantity,
                    order_type=order_type, limit_price=limit),
    )


BOTH = [SoftFillPolicy(), HardFillPolicy()]
BOTH_IDS = ['soft', 'hard']


# ==========================================================================
# The seam
# ==========================================================================

@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
def test_both_shipped_policies_satisfy_the_protocol(policy):
    """`FillPolicy` is structural, so "arbitrary fill model" is checkable.

    A nominal base class would make the claim untestable from outside: only
    our own subclasses could satisfy it.
    """
    assert isinstance(policy, FillPolicy)


def test_a_probabilistic_policy_needs_no_new_argument():
    """The seam must carry the third policy family design section 8 names.

    `ProbabilisticFillPolicy` is deferred because `BookLevel.size` is None on
    every corpus here -- not because the interface cannot express it. This
    stand-in proves the signature suffices: a seed lives in `__init__`, the
    fill probability rides on `FillDecision.confidence`, a partial is a
    `quantity` below `remaining`, and the missing depth is named as
    `DataField.BOOK_SIZE`. If this test ever needs a new parameter on
    `evaluate`, the seam was wrong.
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


@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
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

@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
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


@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
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


@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
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

@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
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
@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
def test_no_matching_phase_fills_nothing(policy, phase):
    """PLO is excluded with the rest: HNX's after-hours session matches only
    PLO orders at the day's last round-lot matched price (rulebook 2.3), and
    `core.order.OrderType` carries no PLO member, so no order this package can
    represent participates in it."""
    decision = policy.evaluate(
        _order(), _interval(session=phase, low=Decimal('90.0')),
        HSX_EXCHANGE, instrument=HSX_LOT)
    assert decision.outcome is FillOutcome.NO_FILL


@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
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
    assert hard.outcome is FillOutcome.INDETERMINATE
    assert soft.price == hard.price or hard.price is None


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


def test_probabilistic_is_refused_with_its_reason_rather_than_defaulted():
    """It needs `BookLevel.size`, which is None on every corpus here. Silently
    falling back to `soft` would substitute a different assumption for the one
    the caller asked for -- the exact failure this module exists to prevent."""
    with pytest.raises(ValueError, match='order-book sizes'):
        build_fill_policy(FillPolicyConfig(kind='probabilistic'))
    with pytest.raises(ValueError, match='unknown fill policy'):
        build_fill_policy(FillPolicyConfig(kind='optimistic'))


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

@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
def test_a_ticker_mismatch_raises_rather_than_reporting_ignorance(policy):
    """The INDETERMINATE rate is a headline number, so it must contain only
    real ignorance. An integration bug returned as INDETERMINATE would be
    published as a property of the Vietnamese market."""
    with pytest.raises(ValueError, match='never cross instruments'):
        policy.evaluate(_order(ticker='HPG'), _interval(low=Decimal('95.0')),
                        HSX_EXCHANGE)


@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
def test_a_negotiated_cross_is_refused(policy):
    """`Side.CROSS` is a put-through, not order matching, and its `.sign`
    returns None -- the landmine `types.signed_quantity` exists to refuse. No
    fill policy can decide one."""
    with pytest.raises(ValueError, match='negotiated'):
        policy.evaluate(_order(side=Side.CROSS),
                        _interval(low=Decimal('95.0')), HSX_EXCHANGE)


@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
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


@pytest.mark.parametrize('policy', BOTH, ids=BOTH_IDS)
def test_a_negative_aggregate_is_refused(policy):
    with pytest.raises(ValueError, match='already_filled'):
        policy.evaluate(_order(), _interval(low=Decimal('95.0')),
                        HSX_EXCHANGE, already_filled=-1)
