"""Position survival on HNXDS: margin, liquidation, blocked exits, expiry."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from plutus.market.adapters.datahub import DataHubSource
from plutus.market.exchanges.derivatives import HNXDS_EXCHANGE, HNXDSExchange
from plutus.market.margin import MarginConfig
from plutus.market.protocol import (
    BandSource, LockEvidence, MarketState, Position, SessionPhase, Side,
)
from plutus.market.verdicts import PositionEventKind

from .conftest import requires_corpus


def _path(prices, start=date(2022, 4, 22)):
    """A synthetic daily path with no bands."""
    return [
        MarketState(
            ticker='VN30F2212',
            ts=datetime.combine(start + timedelta(days=i), datetime.min.time()),
            last=Decimal(str(p)), session=SessionPhase.CONTINUOUS,
        )
        for i, p in enumerate(prices)
    ]


def _long(entry=Decimal('1441.8'), qty=1, stop=None):
    return Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.BUY, quantity=qty,
        entry_price=entry, entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'), stop_price=stop,
    )


# --- synthetic, no corpus -------------------------------------------------

def test_a_flat_path_survives_with_no_events():
    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8] * 5))
    assert v.survived is True
    assert v.events == ()
    assert v.days_evaluated == 5


def test_the_legacy_call_threshold_follows_its_own_arithmetic():
    """Pins the LEGACY per-position model against its own formula.

    .. warning::

       This is **not** how Vietnam calls margin. There is no published
       maintenance margin ratio; the real test is utilisation,
       ``MR / margin assets`` where ``MR = IM + VM`` over the whole account,
       against a broker's threshold ladder. This test therefore pins an
       internal consistency of the legacy walk, not a market behaviour, and
       dies with that walk when the account-level model lands.

    Within the legacy model: notional is marked to market alongside equity, so
    the ratio falls more slowly than the price, and the trigger for a long is
    ``(1 - initial) / (1 - maintenance)``.
    """
    cfg = MarginConfig.VN30F_DEFAULT
    entry = Decimal('1441.8')
    threshold = (entry * (Decimal('1') - cfg.initial_rate)
                 / (Decimal('1') - cfg.maintenance_rate))

    just_above = HNXDS_EXCHANGE.sustains(
        _long(), _path([float(entry), float(threshold * Decimal('1.001'))]))
    just_below = HNXDS_EXCHANGE.sustains(
        _long(), _path([float(entry), float(threshold * Decimal('0.999'))]))

    assert just_above.first(PositionEventKind.MARGIN_CALL) is None
    call = just_below.first(PositionEventKind.MARGIN_CALL)
    assert call is not None
    assert call.margin_ratio < MarginConfig.VN30F_DEFAULT.maintenance_rate


def test_a_five_percent_move_is_not_yet_enough_to_call():
    """Guards the imprecise reading: 5% of notional is the buffer, but it is
    not the call distance."""
    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8, 1441.8 * 0.95]))
    assert v.first(PositionEventKind.MARGIN_CALL) is None


def test_margin_call_is_emitted_once_not_daily():
    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8] + [1300.0] * 5))
    calls = [e for e in v.events if e.kind is PositionEventKind.MARGIN_CALL]
    assert len(calls) == 1


def test_equity_wipeout_forces_liquidation_and_ends_the_walk():
    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8, 1100.0, 1000.0, 900.0]))
    assert v.first(PositionEventKind.FORCED_LIQUIDATION) is not None
    assert v.survived is False


def test_forced_liquidation_implies_an_earlier_or_same_day_call():
    """Normative invariant."""
    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8, 1200.0, 1050.0]))
    liq = v.first(PositionEventKind.FORCED_LIQUIDATION)
    call = v.first(PositionEventKind.MARGIN_CALL)
    if liq is not None:
        assert call is not None
        assert call.ts <= liq.ts


def test_a_short_is_called_by_a_rising_market():
    short = Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.SELL, quantity=1,
        entry_price=Decimal('1441.8'), entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'),
    )
    v = HNXDS_EXCHANGE.sustains(short, _path([1441.8, 1500.0, 1560.0]))
    assert v.first(PositionEventKind.MARGIN_CALL) is not None


def test_call_incidence_is_monotone_in_the_initial_rate():
    """Posting more collateral cannot make a call more likely."""
    path = _path([1441.8, 1380.0, 1340.0, 1300.0])
    called = []
    for rate in ('0.100', '0.175', '0.225', '0.300', '0.350'):
        cfg = MarginConfig.VN30F_DEFAULT.with_initial(Decimal(rate))
        v = HNXDS_EXCHANGE.sustains(_long(), path, margin_config=cfg)
        called.append(v.first(PositionEventKind.MARGIN_CALL) is not None)
    assert called == sorted(called, reverse=True)


def test_exit_blocked_fires_when_the_stop_sits_under_a_locked_floor():
    state = MarketState(
        ticker='VN30F2212', ts=datetime(2022, 5, 9), last=Decimal('1340.0'),
        ceiling=Decimal('1434.0'), floor=Decimal('1340.0'),
        band_source=BandSource.PUBLISHED, session=SessionPhase.CONTINUOUS,
        locked_side=Side.SELL, lock_evidence=LockEvidence.BAR_PROXY,
    )
    v = HNXDS_EXCHANGE.sustains(_long(stop=Decimal('1340.0')), [state])
    assert v.first(PositionEventKind.EXIT_BLOCKED) is not None


def test_no_stop_price_means_no_exit_blocked_event():
    state = MarketState(
        ticker='VN30F2212', ts=datetime(2022, 5, 9), last=Decimal('1340.0'),
        ceiling=Decimal('1434.0'), floor=Decimal('1340.0'),
        band_source=BandSource.PUBLISHED, session=SessionPhase.CONTINUOUS,
        locked_side=Side.SELL, lock_evidence=LockEvidence.BAR_PROXY,
    )
    v = HNXDS_EXCHANGE.sustains(_long(stop=None), [state])
    assert v.first(PositionEventKind.EXIT_BLOCKED) is None


def test_unknown_lock_evidence_never_blocks_an_exit():
    """A lock we cannot establish is not a lock."""
    state = MarketState(
        ticker='VN30F2212', ts=datetime(2022, 5, 9), last=Decimal('1340.0'),
        ceiling=Decimal('1434.0'), floor=Decimal('1340.0'),
        band_source=BandSource.PUBLISHED, session=SessionPhase.CONTINUOUS,
        locked_side=Side.SELL, lock_evidence=LockEvidence.UNKNOWN,
    )
    v = HNXDS_EXCHANGE.sustains(_long(stop=Decimal('1340.0')), [state])
    assert v.first(PositionEventKind.EXIT_BLOCKED) is None


def test_position_limit_is_config_asserted_only():
    """No corpus carries account or limit data, so this is a unit test only and
    the paper claims no incidence for it."""
    from plutus.core.constant import DS

    limited = HNXDSExchange(DS, position_limit=5)
    v = limited.sustains(_long(qty=10), _path([1441.8]))
    assert v.first(PositionEventKind.POSITION_LIMIT_EXCEEDED) is not None


def test_indeterminate_days_are_counted_not_silently_skipped():
    """A state with no usable settlement cannot be judged; say so."""
    path = [MarketState(ticker='VN30F2212', ts=datetime(2022, 5, 9),
                        last=None, session=SessionPhase.CONTINUOUS)]
    v = HNXDS_EXCHANGE.sustains(_long(), path)
    assert v.days_indeterminate == 1


def test_viability_is_json_serialisable():
    import json

    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8, 1300.0]))
    json.dumps(v.to_dict())


# --- against the corpus ---------------------------------------------------

@requires_corpus
def test_vn30f2212_matches_its_pinned_fixture(corpus_root):
    """Entry 2022-04-22 @1441.8: first call 2022-05-09, liquidated 2022-10-03."""
    source = DataHubSource.for_root(str(corpus_root))
    path = list(source.states('VN30F2212', date(2022, 4, 22), date(2023, 1, 1)))
    assert path, 'VN30F2212 must have a close path in the corpus'
    assert path[0].last == Decimal('1441.8')

    v = HNXDS_EXCHANGE.sustains(_long(entry=path[0].last), path)
    call = v.first(PositionEventKind.MARGIN_CALL)
    liq = v.first(PositionEventKind.FORCED_LIQUIDATION)

    assert call is not None and call.ts.date() == date(2022, 5, 9)
    assert liq is not None and liq.ts.date() == date(2022, 10, 3)
    assert v.survived is False


@requires_corpus
def test_vn30f2206_is_called_but_never_liquidated(corpus_root):
    """The 'none where it shouldn't' half of the acceptance criterion."""
    source = DataHubSource.for_root(str(corpus_root))
    path = list(source.states('VN30F2206', date(2021, 1, 1), date(2023, 1, 1)))
    assert path

    position = Position(
        ticker='VN30F2206', exchange_code='HNXDS', side=Side.BUY, quantity=1,
        entry_price=path[0].last, entry_ts=path[0].ts,
        multiplier=Decimal('100000'),
    )
    v = HNXDS_EXCHANGE.sustains(position, path)
    assert v.first(PositionEventKind.MARGIN_CALL) is not None
    assert v.first(PositionEventKind.FORCED_LIQUIDATION) is None


@requires_corpus
def test_expiry_settlement_fires_on_the_third_thursday(corpus_root):
    """VN30F2203 is the only contract with complete band coverage across its
    whole close path (167/167), so it is the gap-free fixture."""
    source = DataHubSource.for_root(str(corpus_root))
    path = list(source.states('VN30F2203', date(2021, 7, 16), date(2022, 3, 18)))
    assert path

    position = Position(
        ticker='VN30F2203', exchange_code='HNXDS', side=Side.BUY, quantity=1,
        entry_price=path[0].last, entry_ts=path[0].ts,
        multiplier=Decimal('100000'),
    )
    v = HNXDS_EXCHANGE.sustains(position, path)
    expiry_event = v.first(PositionEventKind.EXPIRY_SETTLEMENT)
    assert expiry_event is not None
    assert expiry_event.ts.date() == date(2022, 3, 17)
