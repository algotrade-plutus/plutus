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

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.core.order import OrderType, Side
from plutus.market.protocol import (
    BandSource, InstrumentKind, InstrumentSpec, MarketState, Order, Resolution,
    SessionPhase,
)
from plutus.market.session import (
    Accepted, DataField, EventKind, ExchangeSession, MarginStatus,
    MarketInterval, OrderState, Pool, Rejected, Session, StatefulRule, Venue,
)
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
        return InstrumentSpec(
            ticker=ticker, exchange_code=code, kind=kind, trading_unit=100,
            daily_trading_limit=Decimal('0.07'),
            multiplier=(Decimal('100000') if kind is InstrumentKind.FUTURE
                        else Decimal('1')))


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
KINDS = {'FPT': ('HSX', InstrumentKind.STOCK),
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
