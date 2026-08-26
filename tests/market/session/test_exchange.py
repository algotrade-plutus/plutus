"""Integration tests for :mod:`plutus.market.session.exchange`.

These are the only tests in the package that exercise all seven modules at
once, so they pin *compositions* rather than rules: the order the submit path
runs in, what a terminal edge releases, which pool a flow touches, and what
the caller is told. Every rule they rely on is pinned in its own module's
tests; what is new here is that the pieces agree.

The one that must exist is :func:`test_buy_then_sell_same_day_is_refused` --
buy today, try to sell today, and be told exactly why and exactly when the
shares become sellable.
"""

import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.core.order import OrderType, Side
from plutus.market.broker import BrokerTerms
from plutus.market.protocol import (
    BandSource, InstrumentKind, InstrumentSpec, MarketState, Order, Resolution,
    SessionPhase,
)
from plutus.market.session import (
    EXCHANGE_BY_VENUE, Accepted, ChargeBase, DataField, EventKind,
    ExchangeSession, FillDecision, FillEvidence, LeviedBy, LiquidationRule,
    MarginStatus, MarginMonitor, MarketInterval, OrderState, Pool, Rejected,
    Session, SoftFillPolicy, StatefulRule, Venue, parse_config,
)
from plutus.market.session.calendar import (
    CalendarError, weekday_settlement_calendar, weekday_trading_calendar,
)
from plutus.market.session.deposit import UnknownContractMultiplier
from plutus.market.verdicts import AdmissionRule, Verdict

# --------------------------------------------------------------------------
# Fixtures: a hand-written market, so every number in a test is visible
# --------------------------------------------------------------------------

#: 2024-06-03 and 2024-06-04 are a Monday and a Tuesday, so T+2 on the first
#: is the third and the weekday-only default calendar and a real one agree.
#: That keeps these tests about the session and not about Tet.
D1 = date(2024, 6, 3)
D2 = date(2024, 6, 4)
D3 = date(2024, 6, 5)


class StubSource:
    """A ``MarketDataSource`` over a hand-written table of daily states.

    Deliberately *not* one of the shipped adapters. Those read a corpus, and a
    test that depends on a corpus pins the corpus rather than the code. This
    supplies exactly the fields the adapter protocol promises -- and, like both
    real adapters, no volume and no OHLC, which is why ``HardFillPolicy``
    answers ``INDETERMINATE`` below rather than filling.
    """

    def __init__(self, rows, kinds=None):
        self._rows = dict(rows)
        self._kinds = dict(kinds or {})

    def state_at(self, ticker, ts):
        return self._rows.get((ticker, ts.date()))

    def states(self, ticker, start, end, *, resolution=Resolution.DAILY):
        for (name, _), state in sorted(self._rows.items(),
                                       key=lambda kv: kv[0][1]):
            if name == ticker:
                yield state

    def instrument(self, ticker):
        # The adapter protocol promises this never raises: an unknown ticker
        # comes back UNKNOWN with no exchange, which is what makes it
        # unroutable rather than silently HSX.
        code, kind = self._kinds.get(ticker, ('', InstrumentKind.UNKNOWN))
        # 10,000 for a government-bond future and 100,000 for an index one.
        # A stub that answered 100,000 for every FUTURE would be asserting the
        # very thing the deposit's dated multiplier table exists to refuse --
        # HNXDS carries two families whose multipliers differ by 10x.
        multiplier = Decimal('1')
        if kind is InstrumentKind.FUTURE:
            multiplier = (Decimal('10000')
                          if ticker.startswith(('GB05', 'GB10'))
                          else Decimal('100000'))
        return InstrumentSpec(
            ticker=ticker, exchange_code=code, kind=kind, trading_unit=100,
            daily_trading_limit=Decimal('0.07'), multiplier=multiplier)


class BarSource(StubSource):
    """A source that also serves whole intervals, so a bar can carry volume.

    ``MarketDataSource`` promises three questions, all about a snapshot, and
    neither shipped adapter supplies OHLC or volume -- which is why the
    session names those fields missing and ``HardFillPolicy`` answers
    ``INDETERMINATE`` on today's corpora. A richer adapter is not a different
    protocol, though: implementing ``interval()`` is enough, and this stub is
    here to prove the seam takes one.
    """

    def __init__(self, rows, bars, kinds=None):
        super().__init__(rows, kinds)
        self._bars = dict(bars)

    def interval(self, ticker, start, end, *, resolution):
        bar = self._bars.get((ticker, start.date()))
        if bar is None:
            return None
        state = self.state_at(ticker, start)
        low, high, close, volume = bar
        return MarketInterval(
            ticker=ticker, start=start, end=end, resolution=resolution,
            state=state, open=close, high=high, low=low, close=close,
            volume=volume)


def market(ticker, day, last, band=Decimal('0.07')):
    """One day's state, with a published band around the last price."""
    return MarketState(
        ticker=ticker, ts=datetime.combine(day, datetime.min.time()),
        reference=last, ceiling=last * (1 + band), floor=last * (1 - band),
        band_source=BandSource.PUBLISHED, last=last,
        session=SessionPhase.CONTINUOUS)


EQUITY_ROWS = {
    ('FPT', D1): market('FPT', D1, Decimal('95.5')),
    ('FPT', D2): market('FPT', D2, Decimal('96.0')),
    ('FPT', D3): market('FPT', D3, Decimal('96.5')),
}
FUTURES_ROWS = {
    ('VN30F2406', D1): market('VN30F2406', D1, Decimal('1250')),
    ('VN30F2406', D2): market('VN30F2406', D2, Decimal('1150')),
    ('VN30F2406', D3): market('VN30F2406', D3, Decimal('1150')),
}

#: The equity leg of a pair trade is a **basket**, not a ticker. Four VN30
#: constituents at four different price bands, so the HSX tick grid, the
#: ad-valorem HSX charge rows and the round lot all bind on more than one
#: number -- and so "the equity leg was untouched" is a claim about four
#: parcels rather than about one.
BASKET_ROWS = {
    ('VIC', D1): market('VIC', D1, Decimal('45.0')),
    ('VIC', D2): market('VIC', D2, Decimal('45.5')),
    ('VIC', D3): market('VIC', D3, Decimal('46.0')),
    ('VNM', D1): market('VNM', D1, Decimal('70.0')),
    ('VNM', D2): market('VNM', D2, Decimal('70.5')),
    ('VNM', D3): market('VNM', D3, Decimal('71.0')),
    ('HPG', D1): market('HPG', D1, Decimal('28.0')),
    ('HPG', D2): market('HPG', D2, Decimal('28.5')),
    ('HPG', D3): market('HPG', D3, Decimal('29.0')),
}

#: The hedge loses while the basket gains. That ordering is the whole point of
#: the segregation tests below: the pair is *up* in aggregate on every day of
#: the path and the short future is still margin-called, because the basket's
#: gain sits in an account the deposit cannot reach.
#:
#: 1250 -> 1300 is +4.0% and 1300 -> 1385 is +6.5%, both inside the +-7%
#: VN30F band, so no day of the path is a move the exchange would not have
#: allowed.
RISING_FUTURES_ROWS = {
    ('VN30F2406', D1): market('VN30F2406', D1, Decimal('1250')),
    ('VN30F2406', D2): market('VN30F2406', D2, Decimal('1300')),
    ('VN30F2406', D3): market('VN30F2406', D3, Decimal('1385')),
}

#: The four names the basket is long. ``FPT`` is shared with the Tier 1 demo.
VN30_BASKET = ('FPT', 'VIC', 'VNM', 'HPG')

KINDS = {'FPT': ('HSX', InstrumentKind.STOCK),
         'VIC': ('HSX', InstrumentKind.STOCK),
         'VNM': ('HSX', InstrumentKind.STOCK),
         'HPG': ('HSX', InstrumentKind.STOCK),
         'VN30F2406': ('HNXDS', InstrumentKind.FUTURE),
         'ABC': ('UPCOM', InstrumentKind.STOCK)}


def config(**overrides):
    """The design section 6 config, as a mapping, with test defaults."""
    payload = {
        'period': {'start': '2024-06-03', 'end': '2024-06-28'},
        'resolution': '1d',
        'exchange_rules': {'venues': ['HSX', 'HNXDS'],
                           'rulebook': 'vn-2020-2026'},
        'broker_profile': {
            'name': 'test-retail',
            'commission': [
                {'venue': 'HSX', 'base': 'trade_value', 'rate': 0.0015},
                {'venue': 'HNXDS', 'base': 'per_contract', 'amount': 2700},
            ],
        },
        'accounts': {'securities': {'initial_cash': 150000000},
                     'derivatives': {'initial_deposit': 30000000}},
        'fill_policy': {'kind': 'soft'},
        'data': {'adapter': '', 'root': ''},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    return payload


def build(rows=None, **overrides):
    """A session over ``rows``, standing at the start of the period."""
    source = StubSource(rows if rows is not None else EQUITY_ROWS, KINDS)
    return ExchangeSession.from_mapping(config(**overrides), source=source)


def buy(ticker='FPT', quantity=1000, price='95.5',
        order_type=OrderType.LIMIT):
    return Order(ticker=ticker, side=Side.BUY, quantity=quantity,
                 order_type=order_type,
                 limit_price=Decimal(price) if price is not None else None)


def sell(ticker='FPT', quantity=1000, price='96.0',
         order_type=OrderType.LIMIT):
    return Order(ticker=ticker, side=Side.SELL, quantity=quantity,
                 order_type=order_type,
                 limit_price=Decimal(price) if price is not None else None)


# --------------------------------------------------------------------------
# The Tier 1 demo
# --------------------------------------------------------------------------

def test_buy_then_sell_same_day_is_refused():
    """T+2: shares bought today are not sellable today, and the exchange says so.

    **This is the Tier 1 deliverable.** A share bought on T0 settles on T+2,
    so at any instant on T0 the sellable quantity is zero and a sell of it is
    refused with the settlement rule that bound -- not with a generic error,
    and not with ``SESSION_SEMANTICS``, which would say the market was shut.

    Three fields carry the whole answer, and they are three fields because
    they are three different quantities: ``rule`` says which rule refused,
    ``binding_constraint`` says how many shares *were* available (zero), and
    ``sellable_from`` says *when* the requested quantity clears -- 13:00 on
    T+2, the custodian member's allocation deadline to the client under VSD
    Decision 109 (effective 2022-08-29).
    """
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(buy())
    assert isinstance(ack, Accepted)

    session.advance_to(datetime(2024, 6, 3, 14, 0))
    assert session.holdings('FPT').settled == 0
    assert session.holdings('FPT').unsettled_quantity == 1000

    refusal = session.submit(sell())
    assert isinstance(refusal, Rejected)
    assert refusal.rule is StatefulRule.UNSETTLED_HOLDING
    assert refusal.binding_constraint == 0
    assert refusal.sellable_from == datetime(2024, 6, 5, 13, 0)
    assert refusal.verdict is Verdict.REJECTED
    # A refusal that could not be told from a data gap would report the T+2
    # rule as an unknown, so the two must stay separable in the log.
    assert not refusal.is_indeterminate


def test_the_same_sell_is_accepted_once_the_tranche_settles():
    """The refusal is about *when*, not about *whether*. The 13:00 cut binds.

    The same order, unchanged, is still refused at 09:30 on T+2 and accepted
    at 13:00. That is the whole content of the 2022-08-29 regime change: the
    cycle has been T+2 since 2016, and what moved was the *time of day* at
    which the shares reach the client.
    """
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy())
    session.advance_to(datetime(2024, 6, 3, 14, 0))

    session.advance_to(datetime(2024, 6, 5, 9, 30))
    morning = session.submit(sell(price='96.5'))
    assert isinstance(morning, Rejected)
    assert morning.rule is StatefulRule.UNSETTLED_HOLDING

    session.advance_to(datetime(2024, 6, 5, 13, 0))
    assert session.holdings('FPT').settled == 1000
    afternoon = session.submit(sell(price='96.5'))
    assert isinstance(afternoon, Accepted)


def test_settlement_credits_one_event_for_both_dvp_legs():
    """Securities and cash settle together, because DVP is one allocation."""
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy())
    session.advance_to(datetime(2024, 6, 3, 14, 0))

    events = session.advance_to(datetime(2024, 6, 5, 13, 0))
    credits = [e for e in events if e.kind is EventKind.SETTLEMENT_CREDITED]
    assert len(credits) == 1
    assert credits[0].ticker == 'FPT'
    assert credits[0].quantity == 1000
    assert credits[0].pool is Pool.SECURITIES


# --------------------------------------------------------------------------
# Locked shape 2 -- balances are tested net of live orders
# --------------------------------------------------------------------------

def test_two_individually_affordable_buys_cannot_both_rest():
    """One balance cannot fund two orders. Affordability is net of live orders.

    Each buy costs about 95.7m against 150m of cash, so either alone is
    affordable and the pair is not. The encumbrance ledger is what makes the
    second one see the first: a stateless affordability check inside
    ``admits()`` -- the forbidden build of locked shape 2 -- would accept both
    and discover the shortfall only at the fill.

    The refusal carries ``Cash.available`` as the number that bound, which is
    the convention the per-rule table fixes for ``INSUFFICIENT_CASH``.
    """
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))

    first = session.submit(buy())
    assert isinstance(first, Accepted)
    committed = session.cash().committed
    assert committed > Decimal('95000000')

    second = session.submit(buy())
    assert isinstance(second, Rejected)
    assert second.rule is StatefulRule.INSUFFICIENT_CASH
    assert second.binding_constraint == session.cash().available
    assert session.cash().available == Decimal('150000000') - committed


def test_cancelling_the_first_buy_frees_the_balance_for_the_second():
    """Release on every terminal edge, through the one shared hook.

    The pair above is not merely refused: cancelling the first makes the
    second affordable again, and ``committed`` returns to exactly zero. That
    is the invariant a leaked reservation breaks -- and the reason
    ``on_terminal`` is wired once at construction rather than called at each
    terminal edge.
    """
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    first = session.submit(buy())
    assert isinstance(session.submit(buy()), Rejected)

    cancelled = session.cancel(first.order_id)
    assert cancelled.cancelled_quantity == 1000
    assert cancelled.filled_quantity == 0
    assert session.cash().committed == Decimal('0')
    assert session.cash().available == Decimal('150000000')

    assert isinstance(session.submit(buy()), Accepted)


def test_an_expired_order_cannot_fill_in_the_phase_that_killed_it():
    """Expiry runs **before** fills, and the reservation comes back in full.

    The order below is priced at 89.0 against a 95.5 close, so it does not
    fill on its own day -- and the next day the market opens at 88.0, where it
    would. A session that evaluated fills before expiries would fill it, on a
    day the order had already died on: the same defect as a backtest that
    lets a cancelled order trade.

    The expiry is stamped at the venue's close (HSX 14:45) rather than at the
    instant the session noticed the day had rolled. An order that died at the
    close did not die at the next morning's open, and a log that said so could
    not be reconciled against a broker's.
    """
    session = build(rows={
        ('FPT', D1): market('FPT', D1, Decimal('95.5')),
        ('FPT', D2): market('FPT', D2, Decimal('88.0')),
    })
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(buy(price='89.0'))          # inside the band, unfilled
    session.advance_to(datetime(2024, 6, 3, 14, 0))
    assert session.orders(state=OrderState.RESTING)

    events = session.advance_to(datetime(2024, 6, 4, 9, 30))
    expiries = [e for e in events if e.kind is EventKind.EXPIRED]
    assert len(expiries) == 1
    assert expiries[0].order_id == ack.order_id
    assert expiries[0].detail['trigger'] == 'session_end'
    assert expiries[0].ts == datetime(2024, 6, 3, 14, 45)
    assert not [e for e in events if e.kind is EventKind.FILLED]
    assert session.holdings('FPT').total == 0
    assert session.cash().available == Decimal('150000000')
    assert session.cash().committed == Decimal('0')


def test_a_partial_fill_releases_its_reservation_pro_rata():
    """Half the order filled, half the reservation released, order still live.

    This is the one shape where the accept-time reservation and the ledger's
    view can drift apart, so it is the one that catches a record still
    claiming what it no longer holds. The participation cap floors to a whole
    round lot (500 of a 5,000-lot bar at 10%, on a 100-share lot), the filled
    half releases **pro rata at the reserved price**, and the remaining half
    stays committed against the 500 shares that are still working.

    It is also the proof that the fill-policy seam takes a richer adapter
    without a signature change: this source serves whole intervals, so Hard
    can size a fill it would otherwise have to call ``INDETERMINATE``.
    """
    bars = {('FPT', D1): (Decimal('95.0'), Decimal('96.5'), Decimal('95.5'),
                          5000)}
    source = BarSource(EQUITY_ROWS, bars, KINDS)
    session = ExchangeSession.from_mapping(
        config(fill_policy={'kind': 'hard', 'max_participation': 0.10}),
        source=source)
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(buy(price='96.0'))
    reserved = session.cash().committed

    session.advance_to(datetime(2024, 6, 3, 14, 0))
    record = session.orders()[0]
    assert record.state is OrderState.PARTIALLY_FILLED
    assert record.filled_quantity == 500
    assert record.remaining_quantity == 500
    assert session.holdings('FPT').unsettled_quantity == 500

    # Pro rata: half the shares gone, half the reservation with them -- and
    # the record agrees with the ledger, which is what invariant 4 sums over.
    assert session.cash().committed == reserved / 2
    assert sum(e.amount for e in record.encumbrances) == reserved / 2

    session.cancel(ack.order_id)
    assert session.cash().committed == Decimal('0')


def test_an_auction_order_the_clock_jumped_over_still_dies_at_the_cross():
    """Nothing that cannot rest may outlive its session holding a reservation.

    An ATO is enterable only inside its own window and its remainder is
    auto-cancelled at the cross: it never rests and never carries. But
    ``expire_due`` names a trigger for it only when the phase it *leaves* is
    that auction, so a clock that jumps from inside the auction to the next
    day never presents that boundary -- and the order would sit live, holding
    a ceiling-funded reservation of over 100m, for the rest of the run.

    The session closes that gap at the day's close, with the auction order's
    **own** trigger. Reaching for ``SESSION_END`` instead would be inventing a
    rule: a day order dies of a session end and an ATO does not.
    """
    session = build(resolution='tick')
    session.advance_to(datetime(2024, 6, 3, 9, 5))
    assert session.phase('HSX') is SessionPhase.OPENING_AUCTION
    ack = session.submit(buy(price=None,
                             order_type=OrderType.AT_THE_OPENING))
    assert isinstance(ack, Accepted)
    assert session.cash().committed > Decimal('100000000')   # funded at ceiling

    events = session.advance_to(datetime(2024, 6, 4, 9, 5))
    expiries = [e for e in events if e.kind is EventKind.EXPIRED]
    assert [e.detail['trigger'] for e in expiries] == ['auction_cross']
    assert expiries[0].ts == datetime(2024, 6, 3, 14, 45)
    assert session.cash().available == Decimal('150000000')


def test_an_undecided_mok_is_not_killed_on_the_undecided_interval():
    """``INDETERMINATE`` is not a decision, and must not be spent as one.

    An MOK fills in full at entry or is cancelled entirely -- so killing one
    asserts it could *not* be filled in full. When the policy has just said it
    cannot establish whether the order filled, making that assertion would
    turn a data gap into a market rule. The order therefore survives the
    undecided interval and is swept at the day's close instead, which bounds
    the reservation without inventing the fact.
    """
    day = D1
    def blind(on):
        return MarketState(
            ticker='VN30F2406', ts=datetime.combine(on, datetime.min.time()),
            reference=Decimal('1250'), ceiling=Decimal('1337.5'),
            floor=Decimal('1162.5'), band_source=BandSource.PUBLISHED,
            last=None, session=SessionPhase.CONTINUOUS)

    session = build(rows={('VN30F2406', day): blind(day),
                          ('VN30F2406', D2): blind(D2)})
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(
        buy(ticker='VN30F2406', quantity=1, price=None,
            order_type=OrderType.MARKET_FILL_OR_KILL))
    assert isinstance(ack, Accepted)
    posted = session.margin().resting_order_margin
    assert posted > Decimal('0')

    session.advance_to(datetime(2024, 6, 3, 14, 0))
    assert session.indeterminate_report().indeterminate == 1
    assert session.orders(state=OrderState.ACCEPTED)          # still alive

    events = session.advance_to(datetime(2024, 6, 4, 9, 30))
    expiries = [e for e in events if e.kind is EventKind.EXPIRED]
    assert [e.detail['trigger'] for e in expiries] == ['not_fillable_in_full']
    assert session.margin().resting_order_margin == Decimal('0')
    assert session.margin().free_deposit == session.margin().deposit_balance

    # The deposit account must also forget the order, not merely release its
    # encumbrance. Margin is charged on the *increment* to the worst-case net,
    # so a dead buy still counted as live would make the opposing sell below
    # look like an offsetting trade and reserve nothing for it.
    follow = session.submit(sell(ticker='VN30F2406', quantity=1,
                                 price='1250'))
    assert isinstance(follow, Accepted)
    assert session.margin().resting_order_margin > Decimal('0')


# --------------------------------------------------------------------------
# Segregation -- the two pools have independent purchasing power
# --------------------------------------------------------------------------

def two_venue_session():
    """A session holding HSX and HNXDS at once. The pair-trading shape."""
    return build(rows={**EQUITY_ROWS, **FUTURES_ROWS})


def test_a_session_spans_two_venues_in_one_run():
    """Pair trading is the point: one session, one clock, two exchanges.

    A VN30 basket against VN30F is the canonical Vietnamese pair trade and it
    spans HSX and HNXDS. Both orders route from ``(ticker, ts)``, both fill on
    the same advance, and each lands in its own pool -- the equity leg in
    holdings, the futures leg in the contract ledger.
    """
    session = two_venue_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    equity = session.submit(buy())
    futures = session.submit(buy(ticker='VN30F2406', quantity=1, price='1250'))
    assert isinstance(equity, Accepted) and equity.venue is Venue.HSX
    assert isinstance(futures, Accepted) and futures.venue is Venue.HNXDS

    session.advance_to(datetime(2024, 6, 3, 14, 0))
    assert session.holdings('FPT').unsettled_quantity == 1000
    assert session.positions()['VN30F2406'].net_quantity == 1
    assert session.positions()['VN30F2406'].multiplier == Decimal('100000')
    assert {r.venue for r in session.orders()} == {Venue.HSX, Venue.HNXDS}


def test_a_margin_call_touches_only_the_deposit():
    """Securities cash is not an asset of the utilisation test.

    Vietnamese derivatives margin sits in a **segregated deposit account**
    with its own purchasing power, and **no auto-transfer exists**. So an
    account holding 54m of settled securities cash still gets a call when its
    30m deposit is consumed -- the two balances never see each other, which is
    the real behaviour and not a modelling artefact.

    The test also pins the loss-only variation-margin rule from the outside:
    the requirement rises on the adverse move even though the initial margin
    *fell* with the price, because ``VM`` enters ``MR`` only when the account
    is in loss.
    """
    session = two_venue_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy())
    session.submit(buy(ticker='VN30F2406', quantity=1, price='1250'))
    session.advance_to(datetime(2024, 6, 3, 14, 0))

    cash_before = session.cash()
    assert session.margin().status is MarginStatus.OK

    events = session.advance_to(datetime(2024, 6, 4, 14, 0))
    calls = [e for e in events if e.kind is EventKind.MARGIN_CALL]
    assert len(calls) == 1
    assert calls[0].pool is Pool.DERIVATIVES

    view = session.margin()
    assert view.status is MarginStatus.CALL
    assert view.variation_margin == Decimal('10000000')     # loss only
    assert view.initial_margin < Decimal('21250000')        # IM fell with price
    assert view.required > view.initial_margin              # VM pushed MR up

    # The whole point: nothing on the securities side moved.
    assert session.cash() == cash_before
    assert session.cash().settled_balance > Decimal('50000000')


def test_no_auto_transfer_but_an_explicit_one_moves_both_balances():
    """There is no auto-transfer anywhere; the caller must ask.

    A call does not sweep securities cash into the deposit, and nothing in the
    session will do it. An explicit :meth:`transfer` moves both balances by
    exactly the amount asked for, immediately -- which is an **adopted
    assumption** about intraday transfer timing, not a sourced fact.
    """
    session = two_venue_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy(ticker='VN30F2406', quantity=1, price='1250'))
    session.advance_to(datetime(2024, 6, 3, 14, 0))
    session.advance_to(datetime(2024, 6, 4, 14, 0))
    assert session.margin().status is MarginStatus.CALL

    cash_before = session.cash().settled_balance
    deposit_before = session.margin().deposit_balance

    moved = session.transfer(Pool.SECURITIES, Pool.DERIVATIVES,
                             Decimal('20000000'))
    assert moved.amount == Decimal('20000000')
    assert moved.source is Pool.SECURITIES
    assert session.cash().settled_balance == cash_before - Decimal('20000000')
    assert session.margin().deposit_balance == (deposit_before
                                                + Decimal('20000000'))
    assert session.margin().status is MarginStatus.OK


def test_a_transfer_out_of_the_deposit_cannot_strand_an_open_position():
    """``free_deposit`` is the bound, so posted margin cannot be withdrawn."""
    session = two_venue_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy(ticker='VN30F2406', quantity=1, price='1250'))
    session.advance_to(datetime(2024, 6, 3, 14, 0))

    free = session.margin().free_deposit
    refusal = session.transfer(Pool.DERIVATIVES, Pool.SECURITIES,
                               free + Decimal('1'))
    assert isinstance(refusal, Rejected)
    assert refusal.rule is StatefulRule.INSUFFICIENT_DEPOSIT
    assert refusal.binding_constraint == free


def test_securities_cash_cannot_be_transferred_out_of_a_live_order():
    """``Cash.available`` bounds the transfer, so committed money cannot move."""
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy())
    available = session.cash().available

    refusal = session.transfer(Pool.SECURITIES, Pool.DERIVATIVES,
                               available + Decimal('1'))
    assert isinstance(refusal, Rejected)
    assert refusal.rule is StatefulRule.INSUFFICIENT_CASH
    assert refusal.binding_constraint == available


def test_charges_are_itemised_per_pool_and_never_cross():
    """A derivatives charge is paid from the deposit and never from cash.

    ``CashLedger`` refuses a derivatives-pool charge by design, so the session
    keeps that half itself and merges the two here. The test that matters is
    the negative one: every charge on the futures fill has
    ``pool == DERIVATIVES``, and the securities balance is unchanged by it.
    """
    session = two_venue_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy(ticker='VN30F2406', quantity=1, price='1250'))
    cash_before = session.cash().settled_balance
    session.advance_to(datetime(2024, 6, 3, 14, 0))

    charges = session.charges()
    assert charges
    assert all(c.pool is Pool.DERIVATIVES for c in charges)
    assert session.cash().settled_balance == cash_before
    # The 0.0085% derivatives PIT is priced off contracts x multiplier x
    # price, which ledgers.trade_value refuses to compute for HNXDS.
    pit = next(c for c in charges if c.kind == 'pit_derivatives_transfer')
    assert pit.base_value == Decimal('125000000')
    assert pit.amount == Decimal('10625')


# --------------------------------------------------------------------------
# The canonical Vietnamese pair trade, end to end
#
# A VN30 basket on HSX against VN30F on HNXDS, in one session. The hard part
# is not routing -- routing is one lookup -- it is that the two legs live in
# SEGREGATED accounts with independent purchasing power and no auto-transfer
# between them (design section 7.3; rulebook 6.3, "Where margin is held;
# segregation"). So the same pair that a single Western margin account would
# have netted can be funded in aggregate here and still fail on one leg, and
# the hedge can be margin-called on a day the pair is up.
#
# The path is deliberately the awkward one: the basket rises and the SHORT
# hedge loses. Every day of it the pair is ahead, and every day of it the
# deposit is the only account that can answer the call.
# --------------------------------------------------------------------------

#: 100 shares of each basket name at its D1 price, in dong. HSX quotes
#: thousands of dong, hence the 1,000.
BASKET_TRADE_VALUE = {
    'FPT': Decimal('9550000'),      # 100 x 95.5 x 1000
    'VIC': Decimal('4500000'),      # 100 x 45.0 x 1000
    'VNM': Decimal('7000000'),      # 100 x 70.0 x 1000
    'HPG': Decimal('2800000'),      # 100 x 28.0 x 1000
}
BASKET_PRICES = {'FPT': '95.5', 'VIC': '45.0', 'VNM': '70.0', 'HPG': '28.0'}


def pair_session(*, cash=150000000, deposit=30000000, futures=None):
    """One session over the basket, the hedge and nothing else."""
    rows = {**EQUITY_ROWS, **BASKET_ROWS,
            **(futures if futures is not None else RISING_FUTURES_ROWS)}
    return build(rows=rows,
                 accounts={'securities': {'initial_cash': cash},
                           'derivatives': {'initial_deposit': deposit}})


def open_basket(session, quantity=100):
    """Buy ``quantity`` of each of the four names. Returns the acks."""
    return {t: session.submit(buy(ticker=t, quantity=quantity,
                                  price=BASKET_PRICES[t]))
            for t in VN30_BASKET}


def hedge(quantity=1, price='1250'):
    """Short VN30F: the futures leg of the pair, and where shorts are legal."""
    return sell(ticker='VN30F2406', quantity=quantity, price=price)


def test_a_vn30_basket_against_vn30f_opens_in_one_session_across_two_pools():
    """The canonical pair trade: five orders, two venues, two segregated pools.

    Both legs route from ``(ticker, ts)`` on submission, both fill on the same
    advance, and each lands in the ledger its own pool owns -- four parcels of
    unsettled equity in ``HoldingsLedger``, one net-signed short in
    ``ContractLedger``. The short leg is the one only HNXDS permits: a SELL on
    an equity venue needs settled holdings, because Vietnamese cash equity
    allows no short selling at any date in the window.
    """
    session = pair_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    equity = open_basket(session)
    futures = session.submit(hedge())

    assert all(isinstance(a, Accepted) for a in equity.values())
    assert {a.venue for a in equity.values()} == {Venue.HSX}
    assert isinstance(futures, Accepted) and futures.venue is Venue.HNXDS

    session.advance_to(datetime(2024, 6, 3, 14, 0))
    for ticker in VN30_BASKET:
        assert session.holdings(ticker).unsettled_quantity == 100
    position = session.positions()['VN30F2406']
    assert position.net_quantity == -1              # short, and net-signed
    assert position.multiplier == Decimal('100000')
    assert {r.venue for r in session.orders()} == {Venue.HSX, Venue.HNXDS}


def test_a_pair_funded_in_aggregate_still_fails_on_the_futures_leg():
    """The refusal that makes a Vietnamese pair trade different.

    The account holds 150m of securities cash and a 30m deposit. A two-lot
    hedge needs 0.17 x 2 x 100,000 x 1250 = 42.5m of initial margin, so it is
    short by 12.5m -- against 126m of untouched securities cash sitting one
    ``transfer()`` away.

    A bare ``INSUFFICIENT_DEPOSIT`` cannot tell that case apart from being
    broke, and the two call for opposite responses: move cash, or drop a leg.
    So the refusal says which pool was short, by how much, what the *other*
    pool has, and that no auto-transfer will do it for you.
    """
    session = pair_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    open_basket(session)
    available = session.cash().available

    refusal = session.submit(hedge(quantity=2))
    assert isinstance(refusal, Rejected)
    assert refusal.rule is StatefulRule.INSUFFICIENT_DEPOSIT
    assert refusal.verdict is Verdict.REJECTED
    assert refusal.binding_constraint == Decimal('30000000')

    detail = refusal.detail
    assert detail['required'] == Decimal('42500000')
    assert detail['shortfall'] == Decimal('12500000')
    assert detail['short_pool'] is Pool.DERIVATIVES
    assert detail['other_pool'] is Pool.SECURITIES
    assert detail['other_pool_available'] == available
    assert detail['funded_in_aggregate'] is True
    assert detail['auto_transfer'] is False
    assert 'segregated' in detail['segregation']


def test_the_shortfall_the_refusal_names_is_exactly_what_makes_the_leg_fit():
    """The number is actionable, not decorative: transfer it and resubmit.

    Transferring exactly ``shortfall`` -- and not one dong more -- takes the
    free deposit to precisely the requirement, which the reservation admits
    because the test is ``required > free_deposit``. That is what makes the
    reported figure a cure rather than a diagnosis, and it is why the pair
    trade *works* once the caller is told which account to fund.
    """
    session = pair_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    open_basket(session)
    refusal = session.submit(hedge(quantity=2))
    shortfall = refusal.detail['shortfall']

    session.transfer(Pool.SECURITIES, Pool.DERIVATIVES, shortfall)
    assert session.margin().free_deposit == Decimal('42500000')

    retry = session.submit(hedge(quantity=2))
    assert isinstance(retry, Accepted)

    session.advance_to(datetime(2024, 6, 3, 14, 0))
    assert session.positions()['VN30F2406'].net_quantity == -2
    for ticker in VN30_BASKET:
        assert session.holdings(ticker).unsettled_quantity == 100


def test_a_leg_short_in_both_pools_is_not_funded_in_aggregate():
    """The other half of the distinction: no transfer can save this one.

    Same 30m deposit, but the securities account starts at 30m and the basket
    has committed most of it. The shortfall is unchanged at 12.5m and the
    other pool cannot cover it, so ``funded_in_aggregate`` is False and the
    message says so instead of pointing at a transfer that would be refused.
    """
    session = pair_session(cash=30000000)
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    open_basket(session)

    refusal = session.submit(hedge(quantity=2))
    assert refusal.detail['shortfall'] == Decimal('12500000')
    assert refusal.detail['other_pool_available'] < Decimal('12500000')
    assert refusal.detail['funded_in_aggregate'] is False
    assert 'no transfer can fund it' in refusal.detail['cure']


def test_the_equity_leg_is_refused_the_same_way_and_names_the_deposit():
    """Segregation is symmetric: the annotation runs on the cash leg too.

    An equity buy the securities account cannot fund is refused with
    ``INSUFFICIENT_CASH`` even though the deposit is flush -- derivatives
    margin is not equity purchasing power, and the deposit cannot be spent on
    shares any more than securities cash can answer a margin call.
    """
    session = pair_session(cash=5000000, deposit=100000000)
    session.advance_to(datetime(2024, 6, 3, 9, 30))

    refusal = session.submit(buy(ticker='FPT', quantity=100, price='95.5'))
    assert isinstance(refusal, Rejected)
    assert refusal.rule is StatefulRule.INSUFFICIENT_CASH
    assert refusal.detail['short_pool'] is Pool.SECURITIES
    assert refusal.detail['other_pool'] is Pool.DERIVATIVES
    assert refusal.detail['other_pool_available'] == Decimal('100000000')
    assert refusal.detail['funded_in_aggregate'] is True
    assert refusal.detail['auto_transfer'] is False


def test_an_indeterminate_funding_refusal_claims_no_aggregate_verdict():
    """A data gap must not be dressed as a funding fact.

    A market-family derivative order with no observed price is refused
    ``INDETERMINATE`` and has no shortfall to report, so the segregation
    annotation stays off it. Otherwise the log would carry a
    ``funded_in_aggregate`` verdict computed from a number nobody had.
    """
    session = build(rows=EQUITY_ROWS)          # no VN30F rows at all
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    refusal = session.submit(
        Order(ticker='VN30F2406', side=Side.BUY, quantity=1,
              order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT))
    assert isinstance(refusal, Rejected)
    assert refusal.verdict is Verdict.INDETERMINATE
    assert 'funded_in_aggregate' not in refusal.detail
    assert 'shortfall' not in refusal.detail


def test_the_equity_leg_is_untouched_when_the_hedge_is_margin_called():
    """**The segregation property.** The pair is up and the hedge is called.

    This is the whole reason a Vietnamese pair trade behaves differently from
    a Western one. On D2 every basket name is higher than it was bought at and
    the short future is 50 points against -- so a netted margin account would
    see a profitable book and no call at all. Here the deposit is marked
    alone: ``MR = IM + VM`` over the derivatives portfolio only, with ``VM``
    counted because *that* account is in loss, tested as ``MR / deposit``.

    IM on the short is 0.17 x 1 x 100,000 x 1300 = 22.1m, VM is
    100,000 x (1300 - 1250) = 5m, so MR is 27.1m against a 30m deposit:
    utilisation 0.903, over the 0.90 call level. Securities cash is not an
    asset of that test and cannot be pulled into it.

    "Untouched" is then checked as an identity, not as a vibe: the whole
    ``Cash`` view, every basket parcel, and the securities half of the charge
    log are all the same objects they were before the mark.
    """
    session = pair_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    open_basket(session)
    session.submit(hedge())
    session.advance_to(datetime(2024, 6, 3, 14, 0))

    cash_before = session.cash()
    holdings_before = {t: session.holdings(t) for t in VN30_BASKET}
    securities_charges_before = tuple(c for c in session.charges()
                                      if c.pool is Pool.SECURITIES)
    assert session.margin().status is MarginStatus.OK

    events = session.advance_to(datetime(2024, 6, 4, 14, 0))
    calls = [e for e in events if e.kind is EventKind.MARGIN_CALL]
    assert len(calls) == 1
    assert calls[0].pool is Pool.DERIVATIVES

    view = session.margin()
    assert view.status is MarginStatus.CALL
    assert view.posted_margin == Decimal('22100000')
    assert view.variation_margin == Decimal('5000000')
    assert view.required == Decimal('27100000')

    # The pair is ahead on every leg of the basket, and none of it is reachable.
    assert all(BASKET_ROWS[(t, D2)].last > Decimal(BASKET_PRICES[t])
               for t in VN30_BASKET if t != 'FPT')
    assert session.cash() == cash_before
    assert {t: session.holdings(t) for t in VN30_BASKET} == holdings_before
    assert tuple(c for c in session.charges()
                 if c.pool is Pool.SECURITIES) == securities_charges_before
    # No securities-side event was produced by the mark at all.
    assert all(e.pool is not Pool.SECURITIES for e in events
               if e.pool is not None)


def test_a_forced_close_on_the_hedge_does_not_reach_the_basket():
    """Escalation changes nothing on the other side of the wall.

    D3 takes utilisation past the forced-close level, and the report names the
    legs it would close: the futures contract, and only the futures contract.
    Meanwhile the basket's T+2 settlement lands on the same advance and is
    paid in full -- a suspended derivatives account does not divert, delay or
    net against a securities settlement, because they are two accounts at two
    institutions.
    """
    session = pair_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    open_basket(session)
    session.submit(hedge())
    session.advance_to(datetime(2024, 6, 3, 14, 0))
    session.advance_to(datetime(2024, 6, 4, 14, 0))

    events = session.advance_to(datetime(2024, 6, 5, 14, 0))
    forced = [e for e in events if e.kind is EventKind.FORCED_LIQUIDATION]
    assert len(forced) == 1
    assert forced[0].pool is Pool.DERIVATIVES
    assert forced[0].detail['legs'] == ('VN30F2406',)
    assert forced[0].detail['executed'] is False

    credits = [e for e in events if e.kind is EventKind.SETTLEMENT_CREDITED]
    assert {e.ticker for e in credits} == set(VN30_BASKET)
    assert all(e.pool is Pool.SECURITIES for e in credits)
    for ticker in VN30_BASKET:
        assert session.holdings(ticker).settled == 100


def test_each_leg_is_charged_under_its_own_venues_schedule():
    """Two venues, two schedules, and the fees are not even the same *shape*.

    The HSX exchange service fee is **ad valorem** (0.027% of trade value) and
    the HNXDS one is **flat per contract** (2,700), which is why the 125m
    futures trade pays a smaller exchange fee than the 9.55m FPT trade. The
    broker's own commission splits the same way: 0.15% of value on HSX,
    2,700 per contract on HNXDS, from one ``broker_profile`` with one row per
    venue.

    The negative half is the one that matters: no charge kind appears on both
    legs, and no charge crosses pools.
    """
    session = pair_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    open_basket(session)
    session.submit(hedge())
    session.advance_to(datetime(2024, 6, 3, 14, 0))

    charges = session.charges()
    equity_leg = [c for c in charges if c.venue is Venue.HSX]
    futures_leg = [c for c in charges if c.venue is Venue.HNXDS]
    assert len(equity_leg) + len(futures_leg) == len(charges)
    assert all(c.pool is Pool.SECURITIES for c in equity_leg)
    assert all(c.pool is Pool.DERIVATIVES for c in futures_leg)
    assert ({c.kind for c in equity_leg} & {c.kind for c in futures_leg}
            == set())

    fpt_fee = next(c for c in equity_leg
                   if c.ticker == 'FPT' and c.kind.startswith('exchange_'))
    futures_fee = next(c for c in futures_leg
                       if c.kind.startswith('exchange_'))
    assert fpt_fee.base is ChargeBase.TRADE_VALUE
    assert fpt_fee.base_value == BASKET_TRADE_VALUE['FPT']
    assert fpt_fee.amount == Decimal('2579')            # 0.00027 x 9,550,000
    assert futures_fee.base is ChargeBase.PER_CONTRACT
    assert futures_fee.amount == Decimal('2700')        # flat, on 125m
    assert futures_fee.amount > fpt_fee.amount

    commissions = [c for c in charges if c.levied_by is LeviedBy.BROKER]
    hsx_comm = next(c for c in commissions
                    if c.venue is Venue.HSX and c.ticker == 'VNM')
    ds_comm = next(c for c in commissions if c.venue is Venue.HNXDS)
    assert hsx_comm.amount == Decimal('10500')          # 0.0015 x 7,000,000
    assert ds_comm.amount == Decimal('2700')            # per contract


def test_the_two_legs_pay_two_different_personal_income_taxes():
    """0.1% sell-side on HSX against 0.0085% both-sides on HNXDS.

    The clearest case of "its own venue's schedule": the same statute taxes a
    securities transfer and a derivatives transfer at rates two orders of
    magnitude apart, and only the equity one is sell-side. The basket's sale
    on T+2 pays 0.1% of trade value; the hedge pays 0.0085% of *notional* --
    contracts x multiplier x price, which the cash-venue conversion refuses to
    compute -- on the opening leg, before it has closed anything.
    """
    session = pair_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    open_basket(session)
    session.submit(hedge())
    session.advance_to(datetime(2024, 6, 3, 14, 0))

    opening = session.charges()
    assert not [c for c in opening if c.kind == 'pit_securities_transfer']
    ds_pit = next(c for c in opening if c.kind == 'pit_derivatives_transfer')
    assert ds_pit.venue is Venue.HNXDS
    assert ds_pit.base_value == Decimal('125000000')    # 1 x 100,000 x 1250
    assert ds_pit.amount == Decimal('10625')            # 0.0085%

    session.advance_to(datetime(2024, 6, 5, 13, 0))
    assert isinstance(session.submit(sell(ticker='VNM', quantity=100,
                                          price='71.0')), Accepted)
    session.advance_to(datetime(2024, 6, 5, 14, 0))

    eq_pit = next(c for c in session.charges()
                  if c.kind == 'pit_securities_transfer')
    assert eq_pit.venue is Venue.HSX
    assert eq_pit.ticker == 'VNM'
    assert eq_pit.base_value == Decimal('7100000')      # 100 x 71.0 x 1000
    assert eq_pit.amount == Decimal('7100')             # 0.1%
    # And neither venue's row reached the other leg.
    assert all(c.venue is Venue.HSX for c in session.charges()
               if c.kind == 'pit_securities_transfer')
    assert all(c.venue is Venue.HNXDS for c in session.charges()
               if c.kind == 'pit_derivatives_transfer')


# --------------------------------------------------------------------------
# The cursor
# --------------------------------------------------------------------------

def test_advance_to_consumes_what_it_returns():
    """One cursor, destructive, single-consumer.

    ``advance_to()`` returns the events it generated *and* consumes them, so a
    following ``poll()`` is empty. A strategy and a separate logger cannot
    both drain it, which is acceptable because every reporting concern is on
    the caller's side.
    """
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy())
    events = session.advance_to(datetime(2024, 6, 3, 14, 0))
    assert [e.kind for e in events] == [EventKind.ACCEPTED, EventKind.FILLED]
    assert session.poll() == []


def test_a_submission_reaches_the_cursor_before_the_next_advance():
    """``submit()`` returns synchronously *and* journals, so the log is complete.

    Design section 5 delivers acceptance and rejection as return values, which
    is right for a synchronous caller -- but a cursor that omitted them could
    not reconstruct an order's history from the event log alone.
    """
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy())
    session.submit(sell())
    kinds = [e.kind for e in session.poll()]
    assert kinds == [EventKind.ACCEPTED, EventKind.REJECTED]


def test_event_sequence_numbers_are_session_wide_and_monotone():
    """``Event.seq`` gives a total order across every source of events."""
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy())
    first = session.poll()
    rest = session.advance_to(datetime(2024, 6, 5, 13, 0))
    seqs = [e.seq for e in first + rest]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_the_clock_refuses_to_run_backwards():
    """A session that could step back would settle a tranche twice."""
    session = build()
    session.advance_to(datetime(2024, 6, 4, 9, 30))
    with pytest.raises(ValueError, match='monotone'):
        session.advance_to(datetime(2024, 6, 3, 9, 30))


# --------------------------------------------------------------------------
# Shape 1 -- a venue is (ticker, ts), and rules resolve per instant
# --------------------------------------------------------------------------

def test_the_hose_round_lot_is_dated_end_to_end():
    """Same order, same venue, two dates, two answers. Locked shape 1.

    HOSE's minimum lot was 10 units to 2021-01-03 and 100 from 2021-01-04.
    A ten-share order is therefore legal in one session and a ``ROUND_LOT``
    rejection in another, with nothing changed but the clock -- and the
    rejection carries the lot that bound.

    This also exercises the pre-2022-08-29 settlement regime, whose delivery
    is at the *next session's open* and so needs the trading calendar as well
    as the settlement one.
    """
    old = build(rows={('FPT', date(2020, 6, 15)):
                      market('FPT', date(2020, 6, 15), Decimal('95.5'))},
                period={'start': '2020-06-15', 'end': '2020-06-30'})
    old.advance_to(datetime(2020, 6, 15, 9, 30))
    assert isinstance(old.submit(buy(quantity=10)), Accepted)

    new = build(period={'start': '2021-06-15', 'end': '2021-06-30'},
                rows={('FPT', date(2021, 6, 15)):
                      market('FPT', date(2021, 6, 15), Decimal('95.5'))})
    new.advance_to(datetime(2021, 6, 15, 9, 30))
    refusal = new.submit(buy(quantity=10))
    assert isinstance(refusal, Rejected)
    assert refusal.rule is AdmissionRule.ROUND_LOT
    assert refusal.binding_constraint == 100


def test_one_session_spans_the_krx_cutover_with_both_rule_sets():
    """The KRX cutover is a dated rule set, not a migration.

    Both rule sets ship and both stay; the rulebook resolves at the instant
    simulated, so a single run that crosses 2025-05-05 gets pre-KRX rules on
    one side and post-KRX on the other. The session stamps the edition on
    every order it accepts, which is how a result computed across the boundary
    can say which rules produced which row.
    """
    friday, monday = date(2025, 5, 2), date(2025, 5, 5)
    session = build(
        period={'start': '2025-05-02', 'end': '2025-05-09'},
        rows={('FPT', friday): market('FPT', friday, Decimal('95.5')),
              ('FPT', monday): market('FPT', monday, Decimal('95.5'))})

    session.advance_to(datetime(2025, 5, 2, 9, 30))
    before = session.submit(buy(price='89.0'))
    session.advance_to(datetime(2025, 5, 5, 9, 30))
    after = session.submit(buy(price='89.0'))

    tags = {r.order_id: r.regime_tag for r in session.orders()}
    assert tags[before.order_id] == 'pre_krx'
    assert tags[after.order_id] == 'post_krx'
    # One rulebook served both sides. A second session, or a reload, would
    # make the cutover a migration -- which is exactly what it is not.
    assert session.provenance().rulebook_id == 'vn-2020-2026'


def test_upcom_accepts_nothing_but_a_limit_order():
    """The dated order-type table runs at the session, not only in the rulebook.

    ``Exchange.admits()`` knows which types a call auction accepts; it does
    not know that UPCoM has accepted nothing but an LO at any date. That is a
    dated rulebook fact, and the session resolves it before ``admits()`` --
    so an MTL on UPCoM is refused rather than admitted.
    """
    day = D1
    session = build(
        exchange_rules={'venues': ['HSX', 'UPCOM', 'HNXDS']},
        rows={('ABC', day): market('ABC', day, Decimal('20.0'),
                                   band=Decimal('0.15'))})
    session.advance_to(datetime(2024, 6, 3, 9, 30))

    refusal = session.submit(
        buy(ticker='ABC', quantity=100, price=None,
            order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT))
    assert isinstance(refusal, Rejected)
    assert refusal.rule is AdmissionRule.SESSION_SEMANTICS
    assert refusal.detail['mnemonics'] == ['LO']

    assert isinstance(session.submit(buy(ticker='ABC', quantity=100,
                                         price='20.0')), Accepted)


def test_a_market_order_is_legal_at_no_venue_on_any_date():
    """``OrderType.MARKET`` ('MKT') matches no Vietnamese order type, ever.

    ``core/order.py`` carries MKT as a synthetic "buy at ceiling / sell at
    floor" convenience and no matching engine in Vietnam ever received one.
    The book of record *raises* on it rather than rejecting it, so the session
    must refuse it first -- and it must refuse it as a market rejection with a
    row in the log, not as an exception.
    """
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    refusal = session.submit(buy(price=None, order_type=OrderType.MARKET))
    assert isinstance(refusal, Rejected)
    assert refusal.rule is AdmissionRule.SESSION_SEMANTICS
    assert refusal.detail['order_type'] == 'MKT'
    assert session.orders(state=OrderState.REJECTED)


def test_a_midnight_stamped_daily_bar_is_not_treated_as_pre_open():
    """The declared daily deviation, and why it is not optional.

    A daily bar is stamped midnight, and the dated session table answers
    ``PRE_OPEN`` at midnight -- so a session that took the rulebook's phase on
    a daily run would refuse **every order of the run** with
    ``SESSION_SEMANTICS`` and lock every cancellation behind the pre-open
    lock. The bar means a whole trading day whose matching phase is the
    continuous session, which is what both shipped adapters already assert on
    the state they build, so that is what the session uses.

    The phase is still never inferred from the timestamp: it comes from the
    adapter's assertion, and where the adapter is silent from the **trading
    calendar**, which is the object whose job it is to say whether a day
    trades.
    """
    session = build()
    assert session.now() == datetime(2024, 6, 3)      # midnight, period start
    ack = session.submit(buy())
    assert isinstance(ack, Accepted)
    session.advance_to(datetime(2024, 6, 3, 14, 0))
    assert session.orders(state=OrderState.FILLED)[0].order_id == ack.order_id


def test_the_phase_comes_from_the_rulebook_on_an_intraday_clock():
    """12:00 is the noon break, not the continuous session.

    ``ExchangeSpec.lo_session`` spans the break by construction -- HOSE's
    09:15-14:30 window is one interval with a hole in it -- so a session that
    tested continuous first would admit orders into a closed market. On a
    daily-resolution run the rulebook cannot answer (a daily bar is stamped
    midnight), which is the one declared deviation; on a tick clock it is
    authoritative.
    """
    session = build(resolution='tick')
    session.advance_to(datetime(2024, 6, 3, 12, 0))
    assert session.phase('HSX') is SessionPhase.NOON_BREAK
    session.advance_to(datetime(2024, 6, 3, 13, 30))
    assert session.phase(Venue.HSX) is SessionPhase.CONTINUOUS


# --------------------------------------------------------------------------
# Ignorance, measured rather than guessed
# --------------------------------------------------------------------------

def test_hard_returns_indeterminate_when_the_data_carries_no_volume():
    """The honest headline: a bound on ignorance, not a fill rate.

    Neither shipped adapter supplies volume, and the session names the absence
    rather than defaulting it. ``HardFillPolicy`` then cannot size a fill it
    would otherwise make, so it says so -- and the order stays ``RESTING`` and
    is re-evaluated on the next interval, because ``INDETERMINATE`` is an
    event and never a state.
    """
    session = build(fill_policy={'kind': 'hard'})
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(buy(price='96.0'))          # priced through the close

    events = session.advance_to(datetime(2024, 6, 3, 14, 0))
    undecided = [e for e in events if e.kind is EventKind.INDETERMINATE]
    assert len(undecided) == 1
    assert 'volume' in undecided[0].detail['missing']

    report = session.indeterminate_report()
    assert report.evaluations == 1
    assert report.indeterminate == 1
    assert report.by_field[DataField.VOLUME] == 1
    assert session.orders(state=OrderState.RESTING)[0].order_id == ack.order_id


def test_an_indeterminate_order_is_re_evaluated_on_the_next_interval():
    """An undecided interval is not a decision. The order lives on."""
    session = build(fill_policy={'kind': 'hard'})
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(buy(price='96.0'))
    session.advance_to(datetime(2024, 6, 3, 14, 0))
    session.advance_to(datetime(2024, 6, 3, 15, 0))
    assert session.indeterminate_report().evaluations == 2
    assert session.indeterminate_report().indeterminate == 2


def test_soft_and_hard_disagree_on_the_same_bar():
    """The spread between the two policies is the queue assumption, isolated.

    Identical data, identical order: Soft fills at the touch and Hard reports
    that it cannot tell. Neither is wrong -- what would be wrong is a single
    number that hides which assumption produced it, which is why the policy's
    full signature is on the provenance record.
    """
    soft = build()
    soft.advance_to(datetime(2024, 6, 3, 9, 30))
    soft.submit(buy())
    soft.advance_to(datetime(2024, 6, 3, 14, 0))
    assert soft.orders(state=OrderState.FILLED)
    assert soft.indeterminate_report().indeterminate == 0

    hard = build(fill_policy={'kind': 'hard', 'max_participation': 0.10})
    hard.advance_to(datetime(2024, 6, 3, 9, 30))
    hard.submit(buy())
    hard.advance_to(datetime(2024, 6, 3, 14, 0))
    assert not hard.orders(state=OrderState.FILLED)
    assert hard.indeterminate_report().indeterminate == 1
    assert hard.provenance().fill_policy_kind == 'hard(max_participation=0.1)'


def test_an_unroutable_ticker_is_refused_rather_than_defaulted():
    """A silently defaulted venue is locked shape 1's failure mode.

    It would produce a plausible band, tick, lot and fee that are all wrong
    together. The refusal is ``INDETERMINATE`` because the data could not
    decide, and it is counted by rule so the gap is measurable.
    """
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    refusal = session.submit(buy(ticker='ZZZZ'))
    assert isinstance(refusal, Rejected)
    assert refusal.verdict is Verdict.INDETERMINATE
    assert session.indeterminate_report().by_rule
    # No row on the book: writing one would mean inventing a venue for it.
    assert not session.orders(ticker='ZZZZ')


def test_build_wires_a_dated_per_contract_multiplier_not_vn30fs():
    """`build()` is the only place the deposit is assembled -- and it never
    passed a multiplier, so every HNXDS contract fell back to VN30F's 100,000.

    Government-bond futures take 10,000 (rulebook 4.1, HIGH), so a GB order
    reserved ten times its initial margin and the account was refused a
    position it could afford -- with ``free_deposit`` named as the constraint,
    so the log blamed the balance for what was a unit error.

    White-box on ``_derivatives`` deliberately: what is under test is the
    *wiring* ``build()`` performs, there is no public accessor for a contract
    multiplier, and the end-to-end path is closed for a second reason --
    ``build()`` hardwires ``InvestorClass.INDIVIDUAL`` and rulebook 6.4 bars
    individuals from government-bond futures outright, so a GB order is
    refused on ``POSITION_LIMIT`` before its margin is computed. Reaching the
    margin needs an investor class in ``AccountsConfig``, which is a config
    change and not one this test can make.
    """
    session = build()
    ts = datetime(2024, 6, 3, 9, 30)
    deposit = session._derivatives

    assert deposit.multiplier_for('VN30F2406', ts) == Decimal('100000')
    assert deposit.multiplier_for('GB05F2406', ts) == Decimal('10000')
    with pytest.raises(UnknownContractMultiplier):
        deposit.multiplier_for('FPT', ts)


def test_an_unresolvable_multiplier_is_indeterminate_not_a_funding_refusal():
    """The submit boundary reports a unit gap as a gap, not as no money.

    ``IM = ratio x contracts x price x multiplier`` is linear in the
    multiplier, so a guessed one scales the requirement rather than blurring
    it, and the resulting ``INSUFFICIENT_DEPOSIT`` would be a data gap
    reported as a market rule. The order is refused ``INDETERMINATE`` and the
    detail names the rule that could not be resolved.

    The contract is a **VN100 future in June 2024**, sixteen months before
    HNX listed the product on 2025-10-10. Every other dated table waves it
    through: the rulebook keys band, tick and position limit on the product
    *family*, and VN100F has been in the ``INDEX`` family since that family
    existed, so it draws VN30F's +-7% band, 0.1-point tick and 5,000-contract
    cap on a date when no such contract traded. The multiplier table is the
    one place that knows the template had not been listed, which is precisely
    why the multiplier is dated rather than keyed on family alone.
    """
    rows = {**FUTURES_ROWS,
            ('VN100F2409', D1): market('VN100F2409', D1, Decimal('1250'))}
    kinds = {**KINDS, 'VN100F2409': ('HNXDS', InstrumentKind.FUTURE)}
    source = StubSource(rows, kinds)
    session = ExchangeSession.from_mapping(config(), source=source)
    session.advance_to(datetime(2024, 6, 3, 9, 30))

    refusal = session.submit(sell(ticker='VN100F2409', quantity=1,
                                  price='1250'))
    assert isinstance(refusal, Rejected)
    assert refusal.verdict is Verdict.INDETERMINATE
    assert refusal.detail['unresolved_rule'] == 'contract_multiplier'
    assert refusal.detail['contract_code'] == 'VN100F2409'
    assert '2025-10-10' in refusal.detail['reason']
    # And the deposit is untouched: nothing was reserved on a guess.
    view = session.margin()
    assert view.required == Decimal('0')
    assert view.deposit_balance == Decimal('30000000')


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

def test_provenance_lists_every_pin():
    """A pinned run reports that it was pinned.

    That is the difference between a counterfactual and a lie: the same
    session may legally be run with a post-KRX value against pre-KRX data as a
    control, and the record has to say so.
    """
    session = build(exchange_rules={
        'venues': ['HSX'],
        'pins': [{'path': 'margin_model.post_krx',
                  'value': 'flat_fraction',
                  'reason': 'control run: no post-cutover value is sourced'}],
    })
    provenance = session.provenance()
    assert provenance.is_counterfactual
    assert [p.path for p in provenance.pins] == ['margin_model.post_krx']
    assert provenance.pins[0].reason.startswith('control run')


def test_provenance_names_the_unsourced_calendar_loudly():
    """The default settlement calendar is wrong around Tet, and says so.

    Its id contains ``UNSOURCED`` precisely so that a published result cannot
    hide behind it: T+2 counts VSDC settlement business days, which diverge
    from weekdays and from trading days around Tet.
    """
    provenance = build().provenance()
    assert 'UNSOURCED' in provenance.settlement_calendar_id
    assert provenance.venues == (Venue.HSX, Venue.HNXDS)
    assert provenance.broker_profile_name == 'test-retail'


def test_the_session_alias_matches_the_spec_example():
    """Design section 5 writes ``Session.from_config``; the alias keeps it valid."""
    assert Session is ExchangeSession


def test_amending_upward_is_refused_as_a_tier_boundary():
    """An amend-up must re-run the encumbrance, so Tier 1 will not do it.

    Refusing is the conservative direction: the alternative is a
    release-and-retake that can fail *after* the release and leave a live
    order unfunded. A pure quantity decrease is allowed and preserves
    priority, which is the only amendment Vietnam's rules preserve priority
    for anyway.
    """
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(buy(price='89.0'))

    up = session.amend(ack.order_id, quantity=2000)
    assert isinstance(up, Rejected)
    assert up.detail['tier'] == 2

    down = session.amend(ack.order_id, quantity=500)
    assert down.quantity == 500
    assert down.priority_preserved is True


def test_an_unknown_order_id_raises_rather_than_rejecting():
    """An invented id is a programming error, not a market event.

    Returning a ``Rejected`` for one would put a phantom row in the rejection
    log, which is the one artefact this package promises is countable.
    """
    session = build()
    with pytest.raises(KeyError):
        session.cancel('PLU-99999999')


# --------------------------------------------------------------------------
# Atomicity -- a fill that cannot be recorded must never have been paid for
# --------------------------------------------------------------------------
#
# Every test below reproduces a defect an independent reviewer found against a
# live session: the ledgers moved, the state machine then refused, and nothing
# rolled back. They are grouped because they are one disease -- irreversible
# ledger mutation performed before the operation is known to be legal -- and
# they must keep failing if that ordering is ever restored.

PENNY_ROWS = {
    ('PENNY', D1): market('PENNY', D1, Decimal('1.0')),
    ('PENNY', D2): market('PENNY', D2, Decimal('1.0')),
}
HNX_ROWS = {
    ('SHS', D1): market('SHS', D1, Decimal('98.0')),
    ('SHS', D2): market('SHS', D2, Decimal('98.0')),
}
ATOMIC_KINDS = {**KINDS,
                'SHS': ('HNX', InstrumentKind.STOCK),
                'PENNY': ('HSX', InstrumentKind.STOCK)}


class UndersizingPolicy:
    """A caller-supplied policy that proposes a fill the book must refuse.

    ``FillPolicy`` is a **structural** protocol, deliberately: design section
    8 promises a caller may ship a fill model of their own without inheriting
    anything of ours. That promise is exactly why the session cannot assume
    the decision it is handed is legal -- a third-party policy that under-sizes
    a fill-or-kill order is reachable by construction, not by our own bug.

    Sizing to ``quantity`` regardless of the order is the whole trick; it
    stands in for any policy that hands back a partial fill of an order whose
    time-in-force forbids one.
    """

    kind = 'undersizing'
    signature = 'undersizing'

    def __init__(self, quantity):
        self.quantity = quantity
        self.calls = 0

    def evaluate(self, order, interval, rules, *, already_filled=0,
                 instrument=None):
        self.calls += 1
        return FillDecision.fill(self.quantity, interval.close,
                                 FillEvidence.MODELLED)


def atomic_session(rows, bars, policy=None, cash=1_000_000_000,
                   deposit=30_000_000, holdings=None, broker=None,
                   kind='hard'):
    """A session over HSX + HNX + HNXDS with bars rich enough to size a fill.

    Built through :meth:`ExchangeSession.build` rather than
    ``from_mapping`` because two of these tests need what a config file
    cannot express: an injected fill policy, and opening settled holdings.

    ``kind='soft'`` is for the tests that are about the *charge* arithmetic
    rather than about sizing: Soft fills the whole remainder off a bare
    ``MarketState``, so those tests need no volume and say nothing about a
    participation cap they do not care about.
    """
    source = BarSource({**EQUITY_ROWS, **rows}, bars, ATOMIC_KINDS)
    overrides = {
        'exchange_rules': {'venues': ['HSX', 'HNX', 'HNXDS'],
                           'rulebook': 'vn-2020-2026'},
        'fill_policy': ({'kind': 'hard', 'max_participation': 0.10}
                        if kind == 'hard' else {'kind': kind}),
        'accounts': {'securities': {'initial_cash': cash},
                     'derivatives': {'initial_deposit': deposit}},
    }
    if broker is not None:
        overrides['broker_profile'] = broker
    return ExchangeSession.build(
        parse_config(config(**overrides)), source=source,
        fill_policy=policy, initial_holdings=holdings)


def ledger_state(session, tickers=()):
    """Every number a fill moves, as one comparable tuple.

    Asserting on this rather than on one balance is the point: the defect was
    that *some* of these moved and the rest did not, so a test that watched
    only the cash balance would have passed while shares appeared out of
    nowhere.
    """
    cash = session.cash()
    return (cash.settled_balance, cash.committed, cash.pending_total,
            session.margin().deposit_balance,
            tuple(sorted((c, p.net_quantity)
                         for c, p in session.positions().items())),
            tuple((t, session.holdings(t).settled,
                   session.holdings(t).unsettled_quantity) for t in tickers))


def assert_invariant_4(session, tickers=()):
    """Section 12 invariant 4, read from the caller-facing API only.

    The sum of encumbrance carried on the **records** equals the **ledgers'**
    committed totals. The two are stored in different objects and updated by
    different code paths, which is precisely why they can disagree: the
    defect this file pins left a record claiming 524,441,561d of reserved
    cash while the ledger had consumed it down to 419,553,248.80d.
    """
    live = [r for r in session.orders() if not r.is_terminal]
    assert (sum((r.encumbered_cash for r in live), Decimal('0'))
            == session.cash().committed)
    assert (sum((r.encumbered_deposit for r in live), Decimal('0'))
            == session.margin().resting_order_margin)
    for ticker in tickers:
        committed = sum(r.encumbered_quantity for r in live
                        if r.order.ticker == ticker)
        assert committed == session.holdings(ticker).committed


def test_an_undersized_mok_is_killed_rather_than_partly_filled():
    """Fill-or-kill means fillable in full or cancelled entirely (rulebook 2.3).

    ``HardFillPolicy`` sizes a fill at ``floor_to_lot(min(remaining, cap))``.
    On a 10,000-share bar at a 10% participation cap that is 1,000 shares of
    a 5,000-share order -- and for an MOK "1,000 of your 5,000" is not a
    partial fill, it is the statement that the order **could not be filled in
    full**. The only outcome that rule permits is a kill.

    Before this was fixed the policy proposed the partial anyway, the
    securities ledger paid for 1,000 shares, and the state machine then
    refused the fill with the order still ``ACCEPTED`` at zero filled.
    """
    bars = {('SHS', D1): (Decimal('97.0'), Decimal('99.0'), Decimal('98.0'),
                          10000)}
    session = atomic_session(HNX_ROWS, bars)
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(Order(ticker='SHS', side=Side.BUY, quantity=5000,
                               order_type=OrderType.MARKET_FILL_OR_KILL,
                               limit_price=Decimal('98')))
    assert isinstance(ack, Accepted)

    events = session.advance_to(datetime(2024, 6, 3, 14, 0))

    assert [e.detail['trigger'] for e in events
            if e.kind is EventKind.EXPIRED] == ['not_fillable_in_full']
    assert not [e for e in events if e.kind is EventKind.FILLED]
    record = session.orders()[0]
    assert record.state is OrderState.EXPIRED
    assert record.filled_quantity == 0
    # Nothing was bought, so nothing was paid for and nothing stays reserved.
    assert session.holdings('SHS').total == 0
    assert session.cash().settled_balance == Decimal('1000000000')
    assert session.cash().committed == Decimal('0')
    assert_invariant_4(session, tickers=('SHS',))


def test_a_fill_the_book_refuses_moves_no_ledger_at_all():
    """The atomicity guarantee, stated as a test: all of it, or none of it.

    A policy that under-sizes an MOK is refused by ``OrderBookOfRecord``, and
    the refusal must arrive **before** any ledger has moved. Before the fix
    the securities account had already consumed the reservation, credited an
    unsettled tranche and debited 98,173,540d when the book raised, leaving
    the session holding shares no order had bought.

    The raise itself is kept -- an illegal decision is a bug in the policy,
    not a market event, and the house idiom for "the reservation path should
    have made this unreachable" is a ``ValueError``, not a silent skip.
    """
    bars = {('SHS', D1): (Decimal('97.0'), Decimal('99.0'), Decimal('98.0'),
                          10000)}
    session = atomic_session(HNX_ROWS, bars, policy=UndersizingPolicy(1000))
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(Order(ticker='SHS', side=Side.BUY, quantity=5000,
                               order_type=OrderType.MARKET_FILL_OR_KILL,
                               limit_price=Decimal('98')))
    assert isinstance(ack, Accepted)
    before = ledger_state(session, tickers=('SHS',))

    with pytest.raises(ValueError, match='fill-or-kill'):
        session.advance_to(datetime(2024, 6, 3, 14, 0))

    assert ledger_state(session, tickers=('SHS',)) == before
    assert session.orders()[0].filled_quantity == 0
    assert_invariant_4(session, tickers=('SHS',))


def test_a_refused_fill_does_not_drain_the_account_on_every_advance():
    """The leak repeated: each advance spent another 98m and credited 1,000
    more shares, because nothing about the failure was remembered and nothing
    was undone.

    Two advances are the minimum that can show it, and the balance after the
    second must equal the balance after the first -- which, since neither may
    move at all, is the opening balance.
    """
    bars = {('SHS', D1): (Decimal('97.0'), Decimal('99.0'), Decimal('98.0'),
                          10000)}
    session = atomic_session(HNX_ROWS, bars, policy=UndersizingPolicy(1000))
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(Order(ticker='SHS', side=Side.BUY, quantity=5000,
                         order_type=OrderType.MARKET_FILL_OR_KILL,
                         limit_price=Decimal('98')))
    before = ledger_state(session, tickers=('SHS',))

    for hour in (14, 15):
        with pytest.raises(ValueError, match='fill-or-kill'):
            session.advance_to(datetime(2024, 6, 3, hour, 0))
        assert ledger_state(session, tickers=('SHS',)) == before
        assert session.holdings('SHS').total == 0
        assert_invariant_4(session, tickers=('SHS',))


def test_a_refused_fill_opens_no_futures_position_either():
    """The derivatives variant, and the worse half of the defect.

    On the deposit side the pre-refusal work is not merely a debit: it nets
    the ``ContractLedger``, realises the close-out into the deposit balance
    and consumes the order's margin encumbrance. A refusal after that leaves
    an **open futures position that no order created** -- a 10-contract long
    against an order still reporting zero filled.

    Locked shape 5 makes that unusually expensive: margin takes the whole
    account, so a phantom position mis-states the margin requirement for
    every other contract too.
    """
    bars = {('VN30F2406', D1): (Decimal('1240'), Decimal('1260'),
                                Decimal('1250'), 100)}
    session = atomic_session(FUTURES_ROWS, bars, policy=UndersizingPolicy(10),
                             deposit=2_000_000_000)
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(Order(ticker='VN30F2406', side=Side.BUY, quantity=20,
                               order_type=OrderType.MARKET_FILL_OR_KILL,
                               limit_price=Decimal('1250')))
    assert isinstance(ack, Accepted)
    before = ledger_state(session)

    with pytest.raises(ValueError, match='fill-or-kill'):
        session.advance_to(datetime(2024, 6, 3, 14, 0))

    assert session.positions() == {}
    assert ledger_state(session) == before
    assert session.orders()[0].filled_quantity == 0
    assert_invariant_4(session)


def test_a_sale_whose_charges_exceed_its_proceeds_does_not_destroy_shares():
    """A minimum commission on a tiny sale is an ordinary Vietnamese case.

    Penny stocks quote at 1.0-3.0 thousand dong and some brokers impose a
    per-order minimum (rulebook 8.3 and 12.7, both **broker terms**). Selling
    100 shares at 1.0 grosses 100,000d against a 200,000d minimum, so the net
    is negative -- and the ledger used to refuse the credit *after* it had
    already zeroed the reservation and removed the shares. 100 shares were
    destroyed, with no proceeds and no charges recorded.

    The trade matched at HSX, so it stands: the shares leave, the charges are
    itemised, and the net debits the account.
    """
    broker = {'name': 'min-commission',
              'commission': [{'venue': 'HSX', 'base': 'trade_value',
                              'rate': 0.0015, 'min': 200000}]}
    session = atomic_session(PENNY_ROWS, {}, holdings={'PENNY': 1000},
                             broker=broker, kind='soft')
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(Order(ticker='PENNY', side=Side.SELL, quantity=100,
                               order_type=OrderType.LIMIT,
                               limit_price=Decimal('1.0')))
    assert isinstance(ack, Accepted)

    events = session.advance_to(datetime(2024, 6, 3, 14, 0))
    assert [e.kind for e in events if e.kind is EventKind.FILLED]

    holding = session.holdings('PENNY')
    assert holding.settled == 900          # sold, not destroyed
    assert holding.committed == 0
    assert session.orders()[0].state is OrderState.FILLED

    # 100 shares x 1.0 thousand dong = 100,000d gross, less a 200,000d
    # commission minimum and the 0.1% transfer tax withheld at source.
    charged = sum(c.total for c in session.charges())
    assert charged > Decimal('100000')
    assert session.cash().pending_total == Decimal('100000') - charged
    assert session.cash().pending_total < Decimal('0')
    assert_invariant_4(session, tickers=('PENNY',))


def test_the_negative_net_settles_against_the_balance_at_t_plus_2():
    """The shortfall is collected on the settlement leg, like any other net.

    It is not a separate cash movement at the fill: the whole point of the
    module's "withheld at source" model is that a sale produces exactly one
    tranche, and DVP moves it at one instant (rulebook 5.1). A negative
    tranche is that same tranche with a sign.
    """
    broker = {'name': 'min-commission',
              'commission': [{'venue': 'HSX', 'base': 'trade_value',
                              'rate': 0.0015, 'min': 200000}]}
    session = atomic_session(PENNY_ROWS, {}, holdings={'PENNY': 1000},
                             broker=broker, kind='soft')
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    session.submit(Order(ticker='PENNY', side=Side.SELL, quantity=100,
                         order_type=OrderType.LIMIT,
                         limit_price=Decimal('1.0')))
    session.advance_to(datetime(2024, 6, 3, 14, 0))
    shortfall = session.cash().pending_total
    assert shortfall < Decimal('0')
    opening = session.cash().settled_balance

    session.advance_to(datetime(2024, 6, 5, 13, 0))
    assert session.cash().pending_total == Decimal('0')
    assert session.cash().settled_balance == opening + shortfall
    # An advance is a loan against money coming in; there is none coming in.
    assert session.cash().advanced == Decimal('0')


def test_the_record_and_the_ledger_agree_on_every_path_including_failed_ones():
    """Invariant 4 held at every step of one run that walks all of them.

    Accepted, partially filled, cancelled, expired, killed as not fillable in
    full, and -- the one the defect broke -- an advance that raised part-way
    through. The record's ``encumbered_cash`` is read from the order book and
    the committed total from the encumbrance ledger; they are two objects
    updated by two code paths, and this is the assertion that stops them
    drifting.
    """
    bars = {('FPT', D1): (Decimal('95.0'), Decimal('96.5'), Decimal('95.5'),
                          5000),
            ('SHS', D1): (Decimal('97.0'), Decimal('99.0'), Decimal('98.0'),
                          10000)}
    session = atomic_session(HNX_ROWS, bars)
    watched = ('FPT', 'SHS')

    session.advance_to(datetime(2024, 6, 3, 9, 30))
    assert_invariant_4(session, watched)

    # accepted, then partially filled at the participation cap
    partial = session.submit(buy(price='96.0'))
    assert_invariant_4(session, watched)
    session.advance_to(datetime(2024, 6, 3, 10, 0))
    assert session.orders(state=OrderState.PARTIALLY_FILLED)
    assert_invariant_4(session, watched)

    # a live sell, so shares and cash are encumbered at the same instant
    session.advance_to(datetime(2024, 6, 5, 13, 0))
    assert_invariant_4(session, watched)
    sold = session.submit(sell(quantity=100, price='96.5'))
    assert isinstance(sold, Accepted)
    assert_invariant_4(session, watched)

    # cancelled
    session.cancel(sold.order_id)
    assert_invariant_4(session, watched)
    session.cancel(partial.order_id)
    assert_invariant_4(session, watched)
    assert session.cash().committed == Decimal('0')

    # and a failed path: the book refuses the policy's decision mid-advance
    broken = atomic_session(HNX_ROWS, bars, policy=UndersizingPolicy(1000))
    broken.advance_to(datetime(2024, 6, 3, 9, 30))
    broken.submit(Order(ticker='SHS', side=Side.BUY, quantity=5000,
                        order_type=OrderType.MARKET_FILL_OR_KILL,
                        limit_price=Decimal('98')))
    assert_invariant_4(broken, watched)
    with pytest.raises(ValueError):
        broken.advance_to(datetime(2024, 6, 3, 14, 0))
    assert_invariant_4(broken, watched)


# --------------------------------------------------------------------------
# The dated admission rules the session used to resolve from a singleton
#
# TICK_GRID and MAX_ORDER_SIZE both reach `submit()` through the rulebook now.
# Every test below fails against a session that judges the grid with
# `ExchangeSpec.tick_size_function` (one flat 0.1 per venue, no date, no
# instrument kind, no contract family) or that never asks for a size cap.
# --------------------------------------------------------------------------

#: A 5-year government bond future and an HNX ETF -- the two instruments whose
#: real tick is nowhere near the singleton's flat 0.1. GB05 quotes VND on a
#: 100,000d face and steps 1 VND; FUEHNX01 steps 0.001 (1d) from 2022-03-31.
TICK_ROWS = {
    ('GB05F2306', D1): market('GB05F2306', D1, Decimal('100523'),
                              band=Decimal('0.03')),
    ('FUEHNX01', D1): market('FUEHNX01', D1, Decimal('15.5'),
                             band=Decimal('0.07')),
}
TICK_KINDS = {**KINDS,
              'GB05F2306': ('HNXDS', InstrumentKind.FUTURE),
              'FUEHNX01': ('HNX', InstrumentKind.FUND),
              'SHS': ('HNX', InstrumentKind.STOCK)}


def tick_session(rows=None, **overrides):
    """A session over HSX + HNX + HNXDS holding the tick-grid instruments."""
    payload = {'exchange_rules': {'venues': ['HSX', 'HNX', 'HNXDS'],
                                  'rulebook': 'vn-2020-2026'}}
    payload.update(overrides)
    source = StubSource({**EQUITY_ROWS, **(rows if rows is not None
                                           else TICK_ROWS)}, TICK_KINDS)
    return ExchangeSession.from_mapping(config(**payload), source=source)


def test_a_government_bond_future_is_judged_on_its_own_one_vnd_grid():
    """GB05 steps 1 VND, and 100,523.5 is off that grid.

    The tick of an HNXDS contract is a **contract-template** value, not a
    venue value: VN30F steps 0.1 INDEX POINT and GB05 steps 1 VND on a
    100,000d face. The rulebook row for the bond futures says so in terms --
    "the same numeral as the index tick attached to a different unit, exactly
    the error a venue-keyed lookup makes" -- and a venue-keyed lookup is what
    ``ExchangeSpec`` is: one flat ``Decimal('0.1')`` for everything HNXDS
    lists, at every date.

    Under that singleton 100,523.5 is a legal price (a multiple of 0.1) and
    the order is ADMITTED with ``rule=None``. It is not a legal price: HNX
    would refuse it, and a simulator that accepts it reports a fill that
    could never have happened.
    """
    session = tick_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    refusal = session.submit(Order(
        ticker='GB05F2306', side=Side.BUY, quantity=1,
        order_type=OrderType.LIMIT, limit_price=Decimal('100523.5')))

    assert isinstance(refusal, Rejected)
    assert refusal.rule is AdmissionRule.TICK_GRID
    assert refusal.binding_constraint == Decimal('1')
    assert refusal.verdict is Verdict.REJECTED
    # A price ON the 1-VND grid gets past the grid rule. It may still be
    # refused further down the sequence (a bond future is margined at a
    # 100,000d multiplier and this deposit is small), but not on the tick.
    on_grid = session.submit(Order(
        ticker='GB05F2306', side=Side.BUY, quantity=1,
        order_type=OrderType.LIMIT, limit_price=Decimal('100523')))
    assert not (isinstance(on_grid, Rejected)
                and on_grid.rule is AdmissionRule.TICK_GRID)


def test_an_hnx_etf_is_not_refused_on_a_grid_a_hundred_times_too_coarse():
    """HNX's ETF tick is 0.001 from 2022-03-31, so 15.501 is a legal price.

    The mirror image of the government-bond defect, and the one that costs
    orders rather than admitting impossible ones: VNX QD 17 Phu luc III S2.2
    makes the HNX ETF tick 1d where the share grid is 100d, and the
    ``ExchangeSpec`` singleton returns 100d for every HNX instrument. Every
    legal ETF price that is not also a multiple of 100d -- 99 out of every
    100 of them -- comes back ``Rejected(TICK_GRID, binding_constraint=0.1)``.
    """
    session = tick_session()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(Order(
        ticker='FUEHNX01', side=Side.BUY, quantity=100,
        order_type=OrderType.LIMIT, limit_price=Decimal('15.501')))

    assert isinstance(ack, Accepted), getattr(ack, 'detail', ack)
    assert ack.venue is Venue.HNX


def test_an_unresolved_tick_is_indeterminate_and_countable_by_rule():
    """A tick the rulebook cannot supply is a data gap, not a rule saying no.

    HNX's ETF tick is sourced only from 2022-03-31; before that the rulebook
    carries no row, so ``RuleSet.tick_size`` raises ``UnresolvedRule``. The
    session must turn that into ``Rejected(verdict=INDETERMINATE)`` filed
    under ``TICK_GRID`` -- the mapping ``_RULE_FOR_RULENAME`` has always
    carried and no session path could ever reach, because the grid was judged
    against a singleton that answers every question.
    """
    early = date(2021, 6, 15)          # a Tuesday, before the HNX ETF row
    rows = {('FUEHNX01', early): market('FUEHNX01', early, Decimal('15.5'))}
    session = tick_session(rows, period={'start': '2021-06-15',
                                         'end': '2021-06-30'})
    session.advance_to(datetime(2021, 6, 15, 9, 30))
    refusal = session.submit(Order(
        ticker='FUEHNX01', side=Side.BUY, quantity=100,
        order_type=OrderType.LIMIT, limit_price=Decimal('15.5')))

    assert isinstance(refusal, Rejected)
    assert refusal.rule is AdmissionRule.TICK_GRID
    assert refusal.verdict is Verdict.INDETERMINATE
    assert refusal.detail['unresolved_rule'] == 'tick_size'
    assert session.indeterminate_report().by_rule['tick_grid'] == 1


def test_a_million_share_hose_order_breaches_the_dated_cap():
    """HOSE caps one matching order at 500,000 units from 2021-01-04.

    ``RuleSet.max_order_size`` carried the number and had exactly one caller
    in the repository -- its own test -- so a 1,000,000-share FPT order was
    admitted on funding alone. The rulebook's own summary names this: "a
    10,000,000-share HOSE order would be admitted".

    The cap binds **before** the reservation, which is why this session is
    funded for the order it refuses: a size the exchange will not take is not
    a question about the account.
    """
    session = build()
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    refusal = session.submit(buy(quantity=1_000_000, price='95.5'))

    assert isinstance(refusal, Rejected)
    assert refusal.rule is AdmissionRule.SESSION_SEMANTICS
    assert refusal.binding_constraint == 500_000
    assert refusal.verdict is Verdict.REJECTED
    assert refusal.detail['quantity'] == 1_000_000
    # It is a cap, not a ban: the largest legal order is not refused on size.
    at_the_cap = session.submit(buy(quantity=500_000, price='95.5'))
    assert not (isinstance(at_the_cap, Rejected)
                and at_the_cap.rule is AdmissionRule.SESSION_SEMANTICS)


def test_the_futures_cap_is_five_hundred_contracts_not_five_hundred_thousand():
    """The cap is per venue and dated, so HNXDS gets its own number.

    500 CONTRACTS per order on every listed futures contract, from the HNX
    contract templates. Reading HOSE's 500,000 here -- or reading nothing --
    admits an order three orders of magnitude larger than the exchange takes.
    """
    session = build({**EQUITY_ROWS, **FUTURES_ROWS})
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    refusal = session.submit(Order(
        ticker='VN30F2406', side=Side.BUY, quantity=501,
        order_type=OrderType.LIMIT, limit_price=Decimal('1250')))

    assert isinstance(refusal, Rejected)
    assert refusal.rule is AdmissionRule.SESSION_SEMANTICS
    assert refusal.binding_constraint == 500


def test_an_unsourced_cap_refuses_nothing_and_says_so():
    """HNX and UPCoM publish no cap, and UNKNOWN must not become a refusal.

    "No cap" is an inference from HOSE's clause being HOSE-specific, so the
    rulebook records the absence rather than a number. A session that turned
    that absence into ``INDETERMINATE`` would refuse **every** HNX and UPCoM
    order in the run and report a research gap as a market rule -- the exact
    inversion this package exists to prevent. The gap is declared in
    ``_size_here``'s docstring instead.
    """
    rows = {('SHS', D1): market('SHS', D1, Decimal('98.0'))}
    session = tick_session(rows, accounts={
        'securities': {'initial_cash': 100_000_000_000},
        'derivatives': {'initial_deposit': 30_000_000}})
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(Order(ticker='SHS', side=Side.BUY, quantity=600_000,
                               order_type=OrderType.LIMIT,
                               limit_price=Decimal('98')))
    assert isinstance(ack, Accepted), getattr(ack, 'detail', ack)


class _JudgeSpy(SoftFillPolicy):
    """Records the ``Exchange`` the session hands the fill seam."""

    def __init__(self):
        super().__init__()
        self.seen = []

    def evaluate(self, order, interval, rules, *, already_filled=0,
                 instrument=None):
        self.seen.append(rules)
        return super().evaluate(order, interval, rules,
                                already_filled=already_filled,
                                instrument=instrument)


def test_the_fill_seam_is_handed_a_dated_judge_not_the_singleton():
    """``FillPolicy`` is an extension point, so what it is handed is API.

    The contract says a policy "may consult it and the venue spec". Passing
    ``EXCHANGE_BY_VENUE[venue]`` straight through therefore publishes the
    import-time ``ExchangeSpec`` -- one flat 0.1 tick per venue, at every
    date, for every instrument -- as the fill seam's view of the rules, which
    is the same singleton ``submit()`` stopped judging on. Admission being
    dated while the fill path is not would be worse than either alone: the
    two halves of one run would disagree about what the grid is.

    Here the resting order is an HNX ETF, whose real tick is 0.001 from
    2022-03-31 and whose singleton tick is 0.1 -- a hundredfold gap, so the
    two are not confusable.
    """
    spy = _JudgeSpy()
    source = StubSource({**EQUITY_ROWS, **TICK_ROWS}, TICK_KINDS)
    session = ExchangeSession.build(
        parse_config(config(exchange_rules={'venues': ['HSX', 'HNX', 'HNXDS'],
                                            'rulebook': 'vn-2020-2026'})),
        source=source, fill_policy=spy)
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    assert isinstance(session.submit(Order(
        ticker='FUEHNX01', side=Side.BUY, quantity=100,
        order_type=OrderType.LIMIT, limit_price=Decimal('15.501'))), Accepted)

    session.advance_to(datetime(2024, 6, 3, 14, 0))

    assert spy.seen, 'the resting order was never evaluated'
    judge = spy.seen[0]
    assert judge.code == 'HNX'
    assert judge.spec.get_tick_size(
        'FUEHNX01', Decimal('15.501')) == Decimal('0.001')
    assert judge is not EXCHANGE_BY_VENUE[Venue.HNX]


# --------------------------------------------------------------------------
# Expiry -- the contract has a last trading day and the session knows it
# --------------------------------------------------------------------------

#: VN30F2406's last trading day: the third Thursday of June 2024.
JUN_EXPIRY = date(2024, 6, 20)


class SettlingSource(StubSource):
    """A source that publishes a final settlement price on the expiry day.

    ``MarketInterval.settlement_price`` is a field of the section 9 data
    contract that no shipped adapter fills, so this stub is the only thing in
    the suite that exercises the *supplied* branch. It serves an interval on
    one named day and ``None`` everywhere else, so every other advance still
    runs the synthesised-interval path the rest of the file pins.
    """

    def __init__(self, rows, kinds=None, settlements=None):
        super().__init__(rows, kinds)
        self._settlements = dict(settlements or {})

    def interval(self, ticker, start, end, *, resolution):
        price = self._settlements.get((ticker, start.date()))
        if price is None:
            return None
        state = self.state_at(ticker, start)
        return MarketInterval(
            ticker=ticker, start=start, end=end, resolution=resolution,
            state=state, close=state.last if state else None,
            settlement_price=price)


def expiry_rows(last=Decimal('1300')):
    return {('VN30F2406', D1): market('VN30F2406', D1, Decimal('1250')),
            ('VN30F2406', JUN_EXPIRY): market('VN30F2406', JUN_EXPIRY, last)}


def opened_future(session):
    """One long VN30F2406 opened at 1250 on D1, carried to the expiry."""
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    assert isinstance(
        session.submit(buy(ticker='VN30F2406', quantity=1, price='1250')),
        Accepted)
    session.advance_to(datetime(2024, 6, 3, 14, 0))
    assert session.positions()['VN30F2406'].net_quantity == 1
    return session


def test_a_futures_contract_carries_its_last_trading_day():
    """``expiry.py`` computes it 24/24 in-window; the position must carry it.

    A ``ContractPosition`` whose ``expiry`` is ``None`` can never reach
    ``ExpirySettled``, so the contract is margined for the rest of the run --
    past a last trading day the same repository computes exactly. The value is
    resolved at the fill, not read from a build-time table.
    """
    session = opened_future(build(rows=expiry_rows()))
    assert session.positions()['VN30F2406'].expiry == JUN_EXPIRY


def test_the_position_settles_on_its_expiry_day_and_leaves_the_ledger():
    """Design section 7.4: cash moves, the row goes, ``ExpirySettled`` fires.

    Marked from the variation-margin reference -- 1250, the opening price,
    since no daily settlement has run -- to the final settlement at 1300, so
    one contract at 100,000 VND a point pays 5,000,000 into the deposit.
    """
    session = opened_future(build(rows=expiry_rows()))
    deposit_before = session.margin().deposit_balance

    events = session.advance_to(datetime(2024, 6, 20, 14, 45))
    settled = [e for e in events if e.kind is EventKind.EXPIRY_SETTLED]
    assert len(settled) == 1
    assert settled[0].ticker == 'VN30F2406'
    assert settled[0].price == Decimal('1300')
    assert settled[0].amount == Decimal('5000000')
    assert settled[0].pool is Pool.DERIVATIVES

    assert 'VN30F2406' not in session.positions()
    assert session.margin().deposit_balance == (deposit_before
                                                + Decimal('5000000'))
    assert session.margin().required == Decimal('0')


def test_the_close_proxy_substitution_is_recorded_and_never_silent():
    """A close standing in for a settlement price is a *substitution*.

    Measured against every one of the 46 post-cutover expiries the close-proxy
    error is +0.024% mean signed, 0.042% mean absolute and 0.333% at worst --
    small, systematic and one-sided, which is exactly the kind of error a
    reader must be told about rather than one that can be absorbed. So the
    event says which tier produced its price.
    """
    substituted = opened_future(build(rows=expiry_rows()))
    events = substituted.advance_to(datetime(2024, 6, 20, 14, 45))
    proxied = [e for e in events if e.kind is EventKind.EXPIRY_SETTLED][0]
    assert proxied.detail['substituted'] is True
    assert proxied.detail['settlement_source'] == 'close_proxy'
    assert proxied.price == Decimal('1300')

    published = ExchangeSession.from_mapping(
        config(), source=SettlingSource(
            expiry_rows(), KINDS,
            {('VN30F2406', JUN_EXPIRY): Decimal('1281.36')}))
    opened_future(published)
    events = published.advance_to(datetime(2024, 6, 20, 14, 45))
    real = [e for e in events if e.kind is EventKind.EXPIRY_SETTLED][0]
    assert real.detail['substituted'] is False
    assert real.detail['settlement_source'] == 'published'
    assert real.price == Decimal('1281.36')


def test_an_expiry_with_no_price_at_all_is_indeterminate_not_invented():
    """No settlement price and no close: the row stays and the gap is counted.

    Settling on a price nobody observed would put a fabricated cash flow in
    the deposit. ``DataField.SETTLEMENT_PRICE`` is the field that was missing
    and the report is where it is published.
    """
    rows = {('VN30F2406', D1): market('VN30F2406', D1, Decimal('1250'))}
    session = opened_future(build(rows=rows))
    events = session.advance_to(datetime(2024, 6, 20, 14, 45))

    assert [e for e in events if e.kind is EventKind.EXPIRY_SETTLED] == []
    assert 'VN30F2406' in session.positions()
    report = session.indeterminate_report()
    assert report.by_field.get(DataField.SETTLEMENT_PRICE, 0) > 0


# --------------------------------------------------------------------------
# The settlement calendar the caller supplied
# --------------------------------------------------------------------------

#: VSDC Announcement 4228/TB-VSDC: the depository was shut 2026-02-16 through
#: 2026-02-20, so T+2 of a 2026-02-12 trade settled 2026-02-23 and not the
#: 2026-02-16 a weekday-only calendar counts to.
TET_2026 = ['2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19',
            '2026-02-20']


def tet_calendar_file(tmp_path):
    path = tmp_path / 'vsdc-2026.json'
    path.write_text(json.dumps({
        'calendar_id': 'vsdc-2026',
        'coverage': ['2026-01-01', '2026-12-31'],
        'holidays': TET_2026,
        'source': 'VSDC Announcement 4228/TB-VSDC',
    }), encoding='utf-8')
    return path


def test_a_configured_settlement_calendar_is_loaded_and_not_ignored(tmp_path):
    """``data.settlement_calendar`` is the remedy; parsing it and dropping it
    is worse than not offering the field.

    A caller who supplies the real VSDC notice must not silently run on the
    weekday-only calendar whose id says ``UNSOURCED`` -- and the provenance
    record is where the substitution would have hidden.
    """
    day = date(2026, 2, 12)
    session = build(period={'start': '2026-02-09', 'end': '2026-02-27'},
                    rows={('FPT', day): market('FPT', day, Decimal('95.5'))},
                    data={'settlement_calendar': str(
                        tet_calendar_file(tmp_path))})
    assert session.provenance().settlement_calendar_id == 'vsdc-2026'


def test_the_tet_closure_moves_the_settlement_the_caller_asked_for(tmp_path):
    """The whole point of loading it: T+2 of 2026-02-12 is 2026-02-23.

    The weekday-only default counts five days the depository was shut and
    answers 2026-02-16 -- a week early, and wrong in the direction that lets a
    backtest sell shares it does not have.
    """
    day = date(2026, 2, 12)
    rows = {('FPT', day): market('FPT', day, Decimal('95.5'))}
    session = build(period={'start': '2026-02-09', 'end': '2026-02-27'},
                    rows=rows,
                    data={'settlement_calendar': str(
                        tet_calendar_file(tmp_path))})
    session.advance_to(datetime(2026, 2, 12, 9, 30))
    assert isinstance(session.submit(buy()), Accepted)
    session.advance_to(datetime(2026, 2, 12, 14, 0))

    refusal = session.submit(sell(price='95.5'))
    assert isinstance(refusal, Rejected)
    assert refusal.rule is StatefulRule.UNSETTLED_HOLDING
    assert refusal.sellable_from == datetime(2026, 2, 23, 13, 0)


def test_a_settlement_calendar_named_twice_is_refused(tmp_path):
    """Two answers to one question. ``calendar.py`` refuses the same shape.

    A config naming a calendar file *and* an injected calendar object is a run
    whose provenance record cannot be read off its config, so it is an error
    rather than a precedence rule.
    """
    with pytest.raises(ValueError, match='settlement_calendar'):
        ExchangeSession.from_mapping(
            config(data={'settlement_calendar': str(
                tet_calendar_file(tmp_path))}),
            source=StubSource(EQUITY_ROWS, KINDS),
            settlement=weekday_settlement_calendar())


def test_a_settlement_calendar_that_will_not_load_raises(tmp_path):
    """``parse_config`` KeyErrors on a missing ``period`` rather than
    defaulting; a named calendar that is not there gets the same treatment."""
    with pytest.raises((CalendarError, OSError)):
        ExchangeSession.from_mapping(
            config(data={'settlement_calendar': str(tmp_path / 'absent.json')}),
            source=StubSource(EQUITY_ROWS, KINDS))


# --------------------------------------------------------------------------
# Stale marks at the session level
# --------------------------------------------------------------------------

def test_eleven_blind_sessions_do_not_produce_a_definite_margin_status():
    """Design section 9: ``settlement_price`` absent -> margin marks
    ``INDETERMINATE``.

    One long opened on 2024-06-03 and then no market data at all. The
    requirement is still computable -- from the entry price, through the mark
    cache -- and reporting it as a definite ``OK`` is the lie: nothing has been
    observed for eleven sessions and the account could be anywhere.
    """
    rows = {('VN30F2406', D1): market('VN30F2406', D1, Decimal('1250'))}
    session = opened_future(build(rows=rows))
    assert session.margin().status is MarginStatus.OK
    assert session.margin().stale_marks == ()

    for day in (4, 5, 6, 7, 10, 11, 12, 13, 14, 17, 18):
        session.advance_to(datetime(2024, 6, day, 14, 45))

    blind = session.margin()
    assert blind.status is MarginStatus.INDETERMINATE
    assert blind.stale_marks == ('VN30F2406',)
    assert blind.as_of == datetime(2024, 6, 18, 14, 45)

    report = session.indeterminate_report()
    assert report.by_field.get(DataField.SETTLEMENT_PRICE, 0) == 11
    assert report.indeterminate >= 11


# --------------------------------------------------------------------------
# The injected liquidation rule
# --------------------------------------------------------------------------

def forced_rows():
    """A long opened at 1250 that is under water enough to force by D3."""
    return {('VN30F2406', D1): market('VN30F2406', D1, Decimal('1250')),
            ('VN30F2406', D2): market('VN30F2406', D2, Decimal('1150')),
            ('VN30F2406', D3): market('VN30F2406', D3, Decimal('1000'))}


def forced_session(monitor=None):
    parsed = parse_config(config())
    return ExchangeSession.build(
        parsed, source=StubSource(forced_rows(), KINDS), monitor=monitor)


def test_the_default_liquidation_rule_is_stated_and_orders_the_legs():
    """Unchanged behaviour, pinned so the injected case cannot be got by
    breaking the default: largest-loss-first is an ordering and it is named."""
    session = opened_future(forced_session())
    session.advance_to(datetime(2024, 6, 4, 14, 45))
    events = session.advance_to(datetime(2024, 6, 5, 14, 45))

    forced = [e for e in events if e.kind is EventKind.FORCED_LIQUIDATION]
    assert len(forced) == 1
    assert forced[0].detail['selection_rule'] is LiquidationRule.LARGEST_LOSS_FIRST
    assert forced[0].detail['sequence'] == ('VN30F2406',)
    assert forced[0].detail['executed'] is False
    assert session.provenance().liquidation_rule is (
        LiquidationRule.LARGEST_LOSS_FIRST)


def test_an_injected_liquidation_rule_is_honoured_and_not_overwritten():
    """``MarginMonitor(liquidation=...)`` was stored and never read.

    A run configured pro rata reported ``largest_loss_first`` in its
    provenance *and* on the event, with a sequence computed by the rule the
    caller did not choose. Design section 7.4 requires the forced-close event
    to state its selection rule; stating the wrong one is worse than stating
    none.
    """
    monitor = MarginMonitor(BrokerTerms(), weekday_trading_calendar(),
                            liquidation=LiquidationRule.PRO_RATA)
    session = opened_future(forced_session(monitor))
    assert session.provenance().liquidation_rule is LiquidationRule.PRO_RATA

    session.advance_to(datetime(2024, 6, 4, 14, 45))
    events = session.advance_to(datetime(2024, 6, 5, 14, 45))
    forced = [e for e in events if e.kind is EventKind.FORCED_LIQUIDATION]
    assert len(forced) == 1
    assert forced[0].detail['selection_rule'] is LiquidationRule.PRO_RATA
    # Pro rata is a proportional reduction across every leg, not an ordering,
    # so there is no sequence to report -- and reporting one anyway is how the
    # defect read as plausible.
    assert forced[0].detail['sequence'] is None
    assert forced[0].detail['legs'] == ('VN30F2406',)
