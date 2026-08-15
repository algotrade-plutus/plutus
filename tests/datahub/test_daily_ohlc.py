"""WP1 regression tests: the library must run on the shipped dataset.

These pin the acceptance criteria for the daily-bar path:

* daily bars come from the daily tables, not re-aggregated ticks, so coverage
  reaches back to 2000 rather than starting with the tick archive in 2020-12;
* a dataset root without the tick archive is a legitimate deployment and must
  construct, failing only when a query actually needs a missing table;
* ticker symbols are bound as parameters, not interpolated into SQL.

They are skipped when no dataset is reachable, so the suite still runs on a
machine without the corpus.
"""

import os
from pathlib import Path

import pytest

from plutus.datahub.config import DataHubConfig
from plutus.datahub.ohlc_query import OHLCQuery


def _daily_root():
    """Locate a dataset root carrying the daily tables, or None."""
    candidates = []
    env = os.environ.get('PLUTUS_DATA_ROOT')
    if env:
        candidates.append(Path(env))
    candidates += [
        Path('/Users/nadan/algotrade-research/dataset/hermes-parquet'),
        Path('/Users/nadan/algotrade-research/dataset/hermes-csv'),
    ]
    for root in candidates:
        if (root / 'quote_open.parquet').exists() or (root / 'quote_open.csv').exists():
            return root
    return None


DAILY_ROOT = _daily_root()

requires_daily = pytest.mark.skipif(
    DAILY_ROOT is None,
    reason="No dataset root with daily tables found; set PLUTUS_DATA_ROOT."
)


@pytest.fixture
def daily_query():
    return OHLCQuery(config=DataHubConfig(data_root=str(DAILY_ROOT)))


@requires_daily
def test_daily_bars_match_known_window(daily_query):
    """FPT yields exactly 18 daily bars over 2021-01-15 .. 2021-02-15."""
    df = daily_query.fetch(
        ticker='FPT',
        start_date='2021-01-15',
        end_date='2021-02-15',
        interval='1d',
    ).to_dataframe()

    assert len(df) == 18
    first = df.iloc[0]
    assert float(first['open']) == pytest.approx(67.0)
    assert float(first['high']) == pytest.approx(67.0)
    assert float(first['low']) == pytest.approx(66.4)
    assert float(first['close']) == pytest.approx(66.6)
    assert int(first['volume']) == 1_540_400


@requires_daily
def test_daily_ohlc_invariants_hold_on_returned_bars(daily_query):
    """high/low must bracket open/close on the bars we serve."""
    df = daily_query.fetch(
        ticker='FPT', start_date='2021-01-15', end_date='2021-02-15',
        interval='1d',
    ).to_dataframe()

    assert (df['high'] >= df[['open', 'close']].max(axis=1)).all()
    assert (df['low'] <= df[['open', 'close']].min(axis=1)).all()


@requires_daily
def test_daily_path_reaches_back_before_the_tick_archive(daily_query):
    """Coverage must predate 2020-12; ticks would silently truncate it.

    FPT cannot be used here: it lists 2006-12-13. AGF is one of the 38 symbols
    trading in 2005.
    """
    df = daily_query.fetch(
        ticker='AGF', start_date='2005-01-01', end_date='2005-04-01',
        interval='1d',
    ).to_dataframe()

    assert len(df) > 0
    assert str(df['bar_time'].min())[:4] == '2005'


@requires_daily
def test_ticker_is_bound_not_interpolated(daily_query):
    """A quote in the ticker must not break or subvert the SQL."""
    df = daily_query.fetch(
        ticker="' OR 1=1 --", start_date='2021-01-15', end_date='2021-02-15',
        interval='1d',
    ).to_dataframe()

    # No such ticker: an empty result, not a syntax error and not every row.
    assert len(df) == 0


@requires_daily
def test_include_volume_false_still_returns_bars(daily_query):
    df = daily_query.fetch(
        ticker='FPT', start_date='2021-01-15', end_date='2021-02-15',
        interval='1d', include_volume=False,
    ).to_dataframe()

    assert len(df) == 18


@requires_daily
def test_config_constructs_without_tick_archive():
    """A daily-only deployment is legitimate and must not fail at construction."""
    config = DataHubConfig(data_root=str(DAILY_ROOT))

    assert config.has_field('close_price') is True
    on_disk = config.get_available_fields(on_disk=True)
    assert 'close_price' in on_disk
    assert len(on_disk) <= len(config.get_available_fields())


@requires_daily
def test_missing_field_error_names_field_and_query():
    """The error must identify both the absent table and the requiring query."""
    config = DataHubConfig(data_root=str(DAILY_ROOT))
    if config.has_field('matched_price'):
        pytest.skip("This root carries the tick archive; nothing is missing.")

    query = OHLCQuery(config=config)
    with pytest.raises(FileNotFoundError) as excinfo:
        query.fetch(
            ticker='FPT', start_date='2021-01-15', end_date='2021-01-16',
            interval='5m',
        ).to_dataframe()

    message = str(excinfo.value)
    assert 'matched_price' in message
    assert "get_ohlc(interval='5m')" in message


def test_bot_module_imports_and_refuses_to_run():
    """WP1d: bot.py must import cleanly and never fake a backtest."""
    from plutus.core.bot import Bot

    bot = Bot(algorithm=None, portfolio=None, datahub=None)
    with pytest.raises(NotImplementedError):
        bot.run()
