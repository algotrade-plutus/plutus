"""The daily adapter: reconstruction, provenance, and explicit session."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from plutus.market.adapters.datahub import (
    DataHubSource, reconstruct_bands, round_up_to_tick, truncate_to_tick,
)
from plutus.market.protocol import (
    BandSource, InstrumentKind, LockEvidence, Resolution, SessionPhase,
)
from plutus.core.order import OrderType, Side
from plutus.market.protocol import Order
from plutus.market.session import Accepted, ExchangeSession, parse_config
from plutus.market.session.types import DataField, OrderState

from .conftest import requires_corpus


# --- pure helpers, no corpus needed ---------------------------------------

@pytest.mark.parametrize(
    'value, tick, expected',
    [(Decimal('51.788'), Decimal('0.1'), Decimal('51.7')),
     (Decimal('51.7'), Decimal('0.1'), Decimal('51.7')),
     (Decimal('9.876'), Decimal('0.01'), Decimal('9.87'))],
)
def test_truncate_to_tick(value, tick, expected):
    assert truncate_to_tick(value, tick) == expected


@pytest.mark.parametrize(
    'value, tick, expected',
    [(Decimal('45.012'), Decimal('0.1'), Decimal('45.1')),
     (Decimal('45.1'), Decimal('0.1'), Decimal('45.1')),
     (Decimal('9.871'), Decimal('0.01'), Decimal('9.88'))],
)
def test_round_up_to_tick(value, tick, expected):
    assert round_up_to_tick(value, tick) == expected


def test_reconstruction_keys_the_tick_on_the_result_not_the_reference():
    """DSN 2022-04-25: reference 48.40 sits in the 0.05 band, but 48.40*1.07 =
    51.788 crosses 50 and must be truncated on the 0.1 grid to 51.70."""
    from plutus.core.constant import get_hsx_tick_size

    ceiling, _ = reconstruct_bands(
        reference=Decimal('48.40'), limit=Decimal('0.07'),
        tick_fn=get_hsx_tick_size, ticker='DSN')
    assert ceiling == Decimal('51.7')


def test_reconstruction_returns_none_without_a_reference():
    from plutus.core.constant import get_hsx_tick_size

    assert reconstruct_bands(None, Decimal('0.07'), get_hsx_tick_size,
                             'FPT') == (None, None)


def test_reconstructed_floor_rounds_up_not_down():
    """Floor rounds toward the reference; truncating would widen the band."""
    from plutus.core.constant import get_hsx_tick_size

    _, floor = reconstruct_bands(Decimal('48.40'), Decimal('0.07'),
                                 get_hsx_tick_size, 'DSN')
    assert floor >= Decimal('48.40') * Decimal('0.93')


# --- adapter behaviour, corpus-gated --------------------------------------

@requires_corpus
def test_daily_state_sets_session_explicitly(corpus_root):
    """A daily ts is midnight; inferring the phase would mark it pre-open."""
    source = DataHubSource.for_root(str(corpus_root))
    state = source.state_at('FPT', datetime(2021, 1, 15))
    assert state is not None
    assert state.session is SessionPhase.CONTINUOUS


@requires_corpus
def test_published_bands_are_tagged_as_published(corpus_root):
    source = DataHubSource.for_root(str(corpus_root))
    state = source.state_at('FPT', datetime(2021, 6, 15))
    assert state is not None
    assert state.band_source is BandSource.PUBLISHED
    assert state.floor < state.ceiling


@requires_corpus
def test_a_limit_locked_day_carries_bar_proxy_evidence(corpus_root):
    """When last == ceiling the adapter asserts a buy-side lock and labels the
    evidence an inference, not a book observation."""
    source = DataHubSource.for_root(str(corpus_root))
    locked = [s for s in source.states('FPT', date(2021, 1, 1), date(2023, 1, 1))
              if s.ceiling is not None and s.last == s.ceiling]
    assert locked, 'expected at least one limit-up day for FPT in 2021-2022'
    for state in locked:
        assert state.lock_evidence is LockEvidence.BAR_PROXY
        assert state.locked_side is not None


@requires_corpus
def test_states_is_end_exclusive(corpus_root):
    source = DataHubSource.for_root(str(corpus_root))
    got = list(source.states('FPT', date(2021, 1, 15), date(2021, 1, 16)))
    assert len(got) == 1
    assert got[0].ts.date() == date(2021, 1, 15)


@requires_corpus
def test_tick_resolution_is_refused_by_the_daily_adapter(corpus_root):
    source = DataHubSource.for_root(str(corpus_root))
    with pytest.raises(ValueError, match='DAILY'):
        list(source.states('FPT', date(2021, 1, 15), date(2021, 1, 16),
                           resolution=Resolution.TICK))


@requires_corpus
def test_instrument_never_raises_for_an_unlisted_ticker(corpus_root):
    """87 tickers trade in 2021-22 without a ticker-master row."""
    source = DataHubSource.for_root(str(corpus_root))
    spec = source.instrument('VNINDEX')
    assert spec.kind is InstrumentKind.UNKNOWN
    assert spec.trading_unit in (1, 100)


@requires_corpus
def test_instrument_types_a_futures_contract_by_prefix(corpus_root):
    """The master has no `future` type and no HNXDS rows, so the code prefix is
    the only available signal."""
    source = DataHubSource.for_root(str(corpus_root))
    spec = source.instrument('VN30F2112')
    assert spec.kind is InstrumentKind.FUTURE
    assert spec.exchange_code == 'HNXDS'
    assert spec.trading_unit == 1
    assert spec.expiry == date(2021, 12, 16)   # third Thursday of Dec 2021


@requires_corpus
def test_instrument_types_a_warrant_by_the_eight_char_rule(corpus_root):
    source = DataHubSource.for_root(str(corpus_root))
    spec = source.instrument('CFPT2314')
    assert spec.kind is InstrumentKind.WARRANT
    assert spec.exchange_code == 'HSX'


@requires_corpus
def test_a_known_stock_resolves_from_the_master(corpus_root):
    source = DataHubSource.for_root(str(corpus_root))
    spec = source.instrument('FPT')
    assert spec.kind is InstrumentKind.STOCK
    assert spec.trading_unit == 100


# --- the interval seam: volume, and the contract around it -----------------
#
# The defect these pin. This adapter served snapshots only, so
# `ExchangeSession._interval_for` synthesised an interval and named `VOLUME`
# missing on every bar. `participation_cap` returns None without volume, so
# `hard` -- and every config-built capped policy -- answered INDETERMINATE
# wherever it would otherwise have filled: the conservative arm produced a
# zero-trade backtest and only the uncapped `soft` ran. That was reported as a
# property of the corpus. `quote_dailyvolume` is on disk next to
# `quote_close`.

def test_the_source_declares_a_contract_it_does_not_contradict():
    """`SERVES` and `WITHHELD` are the data contract, and they must not
    overlap: a field claimed and named-missing at once would make
    `indeterminate_report()` count an absence the source says it fills."""
    assert not (DataHubSource.SERVES & DataHubSource.WITHHELD)
    assert DataField.VOLUME in DataHubSource.SERVES
    # Volume is *not* permanently withheld: it is added per-bar where the
    # corpus has no row, which is the only shape that distinguishes "this
    # source never has it" from "this bar does not".
    assert DataField.VOLUME not in DataHubSource.WITHHELD


@requires_corpus
def test_the_adapter_satisfies_the_interval_seam(corpus_root):
    """Structural, not nominal: the session tests `isinstance(source,
    IntervalSource)` and synthesises a bar for anything that fails it."""
    from plutus.market.session.exchange import IntervalSource

    assert isinstance(DataHubSource.for_root(str(corpus_root)), IntervalSource)


@requires_corpus
def test_a_daily_interval_carries_the_corpus_volume(corpus_root):
    """HPG on 2022-10-24 traded 27,973,100 shares and the corpus says so."""
    source = DataHubSource.for_root(str(corpus_root))
    interval = source.interval('HPG', datetime(2022, 10, 24),
                               datetime(2022, 10, 25))
    assert interval is not None
    assert interval.volume == 27_973_100
    assert not interval.lacks(DataField.VOLUME)
    assert interval.close == Decimal('16.4')


@requires_corpus
def test_the_hard_policy_now_fills_on_the_shipped_daily_adapter(corpus_root):
    """The measured failure, end to end: `hard`, BUY 1,000 HPG, 2022-10-24.

    It was accepted and then filled nothing -- INDETERMINATE naming VOLUME,
    every day, on every name. The close of 16.4 is strictly through a limit of
    17.0, so the trade-through is proven; the only thing missing was the
    denominator for the cap.
    """
    from plutus.market.exchanges.equity import HSX_EXCHANGE
    from plutus.market.session.fills import HardFillPolicy
    from plutus.market.session.types import (FillOutcome, OrderRecord,
                                             TimeInForce, Venue)
    from plutus.market.protocol import Order, OrderType, Side

    source = DataHubSource.for_root(str(corpus_root))
    interval = source.interval('HPG', datetime(2022, 10, 24),
                               datetime(2022, 10, 25))
    order = OrderRecord(
        order_id='O-1', venue=Venue.HSX, state=OrderState.RESTING,
        time_in_force=TimeInForce.DAY,
        submitted_at=datetime(2022, 10, 24), updated_at=datetime(2022, 10, 24),
        fills=(),
        order=Order(ticker='HPG', side=Side.BUY, quantity=1000,
                    order_type=OrderType.LIMIT, limit_price=Decimal('17.0')),
    )
    decision = HardFillPolicy(Decimal('0.10')).evaluate(
        order, interval, HSX_EXCHANGE)
    assert decision.outcome is FillOutcome.FILL
    assert decision.quantity == 1000
    assert decision.price == Decimal('17.0')


@requires_corpus
def test_a_ticker_with_no_volume_to_publish_names_the_absence(corpus_root):
    """37% of ticker-days carry a close and no volume row -- every index among
    them. Nothing is defaulted to zero: an absent row is our ignorance and a
    zero is a market fact, and collapsing the first into the second would turn
    a missing row into a definite no-fill."""
    source = DataHubSource.for_root(str(corpus_root))
    interval = source.interval('VNINDEX', datetime(2022, 10, 24),
                               datetime(2022, 10, 25))
    assert interval is not None
    assert interval.volume is None
    assert interval.lacks(DataField.VOLUME)


@requires_corpus
def test_every_withheld_field_is_named_on_every_interval(corpus_root):
    """A field this source cannot serve is named on the bar, so a policy that
    needs one returns INDETERMINATE naming it and the session counts it.
    OPEN/HIGH/LOW are in here and the corpus does hold them -- that gap is
    real, declared, and counted rather than invisible."""
    source = DataHubSource.for_root(str(corpus_root))
    interval = source.interval('HPG', datetime(2022, 10, 24),
                               datetime(2022, 10, 25))
    assert DataHubSource.WITHHELD <= interval.missing
    assert {DataField.OPEN, DataField.HIGH, DataField.LOW} <= interval.missing


@requires_corpus
def test_the_intervals_state_is_the_state_state_at_would_return(corpus_root):
    """Admission judges on `state_at` and fills judge on the state inside the
    interval. Two states built by two paths would let `submit()` and the fill
    policy disagree about the band, the lock or the phase with nothing saying
    so, so both come from the same `_build_state`."""
    source = DataHubSource.for_root(str(corpus_root))
    ts = datetime(2022, 10, 24)
    interval = source.interval('HPG', ts, ts + timedelta(days=1))
    assert interval.state == source.state_at('HPG', ts)


@requires_corpus
def test_a_day_the_corpus_does_not_cover_is_absent_not_invented(corpus_root):
    """2022-10-23 is a Sunday. `None` is the contract's "absent", and leaves
    the session free to synthesise rather than being handed an empty bar."""
    source = DataHubSource.for_root(str(corpus_root))
    assert source.interval('HPG', datetime(2022, 10, 23),
                           datetime(2022, 10, 24)) is None


@requires_corpus
def test_a_window_that_is_not_one_daily_bar_is_refused(corpus_root):
    """A daily bar's volume is one session's. Serving it for a one-second
    window or a three-day one would attribute a whole day's liquidity to a
    window that did not have it -- the permissive direction, and the one a
    backtest must not err in."""
    source = DataHubSource.for_root(str(corpus_root))
    ts = datetime(2022, 10, 24)
    with pytest.raises(ValueError, match='DAILY'):
        source.interval('HPG', ts, ts + timedelta(seconds=1),
                        resolution=Resolution.TICK)
    with pytest.raises(ValueError, match='more than one day'):
        source.interval('HPG', ts, ts + timedelta(days=3))


def test_the_adapter_declares_which_resolutions_it_can_serve():
    """A checkable fact, like `SERVES` and `WITHHELD` beside it.

    `interval()` refuses a resolution it cannot serve, and refusing is right:
    absent is not the same as unserveable, and answering `None` there would
    have the session synthesise a bar that looked fine. But a refusal raised
    from inside `advance_to` is a crash in the middle of a run, after orders
    have been accepted and cash encumbered. The declaration is what lets
    `ExchangeSession` refuse the *configuration* instead, at construction.
    """
    assert DataHubSource.SERVES_RESOLUTIONS == frozenset({Resolution.DAILY})


@requires_corpus
def test_a_tick_session_on_the_daily_adapter_is_refused_before_it_runs(
        corpus_root):
    """The regression, end to end on the shipped adapter.

    `resolution: tick` with a `DataHubSource` built, accepted an order,
    encumbered the cash for it, and then raised `ValueError` out of the first
    `advance_to` that had a live order to evaluate. The message names both
    sides and the adapter to use instead, and it arrives before any of that
    state exists.
    """
    payload = {
        'period': {'start': '2022-11-08', 'end': '2022-11-10'},
        'resolution': Resolution.TICK.value,
        'exchange_rules': {'venues': ['HSX']},
        'accounts': {'securities': {'initial_cash': 200000000000}},
        'fill_policy': {'kind': 'soft'},
        'data': {},
    }
    source = DataHubSource.for_root(str(corpus_root))
    with pytest.raises(ValueError, match='cannot serve'):
        ExchangeSession.build(parse_config(payload), source=source)

    payload['resolution'] = Resolution.DAILY.value
    session = ExchangeSession.build(parse_config(payload), source=source)
    session.advance_to(datetime(2022, 11, 9, 9, 20))
    ack = session.submit(Order(ticker='FPT', side=Side.BUY, quantity=1000,
                               order_type=OrderType.LIMIT,
                               limit_price=Decimal('74.0')))
    assert isinstance(ack, Accepted)
    session.advance_to(datetime(2022, 11, 9, 14, 0))
