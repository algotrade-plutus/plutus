"""The daily adapter: reconstruction, provenance, and explicit session."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.adapters.datahub import (
    DataHubSource, reconstruct_bands, round_up_to_tick, truncate_to_tick,
)
from plutus.market.protocol import (
    BandSource, InstrumentKind, LockEvidence, Resolution, SessionPhase,
)

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
