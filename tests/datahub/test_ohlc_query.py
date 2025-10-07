"""Unit tests for OHLCQuery class."""

import pytest
from pathlib import Path
from plutus.datahub.config import DataHubConfig
from plutus.datahub.ohlc_query import OHLCQuery


@pytest.fixture
def test_data_root():
    """Get CSV test data root directory."""
    return Path(__file__).parent.parent / 'sample_data' / 'csv'


@pytest.fixture
def parquet_data_root():
    """Get Parquet test data root directory."""
    return Path(__file__).parent.parent / 'sample_data' / 'parquet'


@pytest.fixture
def config(test_data_root):
    """Create DataHubConfig with CSV test data."""
    return DataHubConfig(data_root=str(test_data_root))


@pytest.fixture
def parquet_config(parquet_data_root):
    """Create DataHubConfig with Parquet test data."""
    return DataHubConfig(data_root=str(parquet_data_root), prefer_parquet=True)


@pytest.fixture
def query(config):
    """Create OHLCQuery instance with CSV data."""
    return OHLCQuery(config)


@pytest.fixture
def parquet_query(parquet_config):
    """Create OHLCQuery instance with Parquet data."""
    return OHLCQuery(parquet_config)


class TestOHLCQuery:
    """Tests for OHLCQuery class."""

    def test_init(self, query):
        """Test OHLCQuery initialization."""
        assert query is not None
        assert query.config is not None
        assert query._conn is not None

    def test_init_without_config(self):
        """Test OHLCQuery without config raises helpful error."""
        import os
        import shutil
        from pathlib import Path

        # Save current env var
        old_env = os.environ.get('PLUTUS_DATA_ROOT')

        # Temporarily rename config.cfg if it exists
        config_path = Path('config.cfg')
        config_backup = None
        if config_path.exists():
            config_backup = Path('config.cfg.backup_test')
            shutil.move(str(config_path), str(config_backup))

        try:
            # Clear env var if set
            if 'PLUTUS_DATA_ROOT' in os.environ:
                del os.environ['PLUTUS_DATA_ROOT']

            # Should raise helpful error
            with pytest.raises(FileNotFoundError) as exc_info:
                OHLCQuery()

            # Verify error message is helpful
            error_msg = str(exc_info.value)
            assert "Dataset location not configured" in error_msg
            assert "config.cfg" in error_msg
            assert "PLUTUS_DATA_ROOT" in error_msg

        finally:
            # Restore env var
            if old_env:
                os.environ['PLUTUS_DATA_ROOT'] = old_env

            # Restore config.cfg if it was backed up
            if config_backup and config_backup.exists():
                shutil.move(str(config_backup), str(config_path))

    def test_supported_intervals(self, query):
        """Test that all intervals are defined."""
        expected_intervals = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
        for interval in expected_intervals:
            assert interval in query.INTERVALS

    def test_fetch_1m_bars_with_volume(self, query):
        """Test fetching 1-minute OHLC bars with volume."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1m',
            include_volume=True
        )

        # Convert to list
        bars = list(results)
        assert len(bars) >= 1

        # Check first bar structure
        bar = bars[0]
        assert 'bar_time' in bar
        assert 'tickersymbol' in bar
        assert 'open' in bar
        assert 'high' in bar
        assert 'low' in bar
        assert 'close' in bar
        assert 'volume' in bar

        # Verify OHLC relationships
        assert bar['high'] >= bar['open']
        assert bar['high'] >= bar['close']
        assert bar['high'] >= bar['low']
        assert bar['low'] <= bar['open']
        assert bar['low'] <= bar['close']

    def test_fetch_1m_bars_without_volume(self, query):
        """Test fetching 1-minute OHLC bars without volume."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1m',
            include_volume=False
        )

        bars = list(results)
        assert len(bars) >= 1

        # Check that volume is not included
        bar = bars[0]
        assert 'bar_time' in bar
        assert 'open' in bar
        assert 'high' in bar
        assert 'low' in bar
        assert 'close' in bar
        assert 'volume' not in bar

    def test_fetch_5m_bars(self, query):
        """Test fetching 5-minute OHLC bars."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='5m',
            include_volume=True
        )

        bars = list(results)
        # 5-minute bars should have fewer bars than 1-minute
        assert len(bars) >= 1

    def test_fetch_1d_bars(self, query):
        """Test fetching daily OHLC bars."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1d',
            include_volume=True
        )

        bars = list(results)
        # Should have 1 daily bar for 1-day range
        assert len(bars) == 1

        bar = bars[0]
        assert bar['tickersymbol'] == 'HPG'

    def test_fetch_with_datetime(self, query):
        """Test fetching with datetime (not just date)."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15 09:00:00',
            end_date='2023-06-15 10:00:00',
            interval='1m',
            include_volume=True
        )

        bars = list(results)
        # Should have bars only within the hour
        assert len(bars) >= 1

    def test_fetch_invalid_ticker_returns_empty(self, query):
        """Test that invalid ticker returns empty result."""
        results = query.fetch(
            ticker='INVALID',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1m'
        )

        bars = list(results)
        assert len(bars) == 0

    def test_fetch_invalid_interval_raises(self, query):
        """Test that invalid interval raises ValueError."""
        with pytest.raises(ValueError, match="Invalid interval"):
            query.fetch(
                ticker='HPG',
                start_date='2023-06-15',
                end_date='2023-06-16',
                interval='99m'
            )

    def test_fetch_invalid_date_range_raises(self, query):
        """Test that invalid date range raises ValueError."""
        with pytest.raises(ValueError):
            query.fetch(
                ticker='HPG',
                start_date='2023-06-16',
                end_date='2023-06-15',  # End before start
                interval='1m'
            )

    def test_fetch_invalid_date_format_raises(self, query):
        """Test that invalid date format raises ValueError."""
        with pytest.raises(ValueError):
            query.fetch(
                ticker='HPG',
                start_date='invalid-date',
                end_date='2023-06-16',
                interval='1m'
            )

    def test_result_iterator_to_dataframe(self, query):
        """Test converting OHLC results to DataFrame."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1m'
        )

        df = results.to_dataframe()
        assert df is not None
        assert len(df) >= 1
        assert 'bar_time' in df.columns
        assert 'open' in df.columns
        assert 'high' in df.columns
        assert 'low' in df.columns
        assert 'close' in df.columns

    def test_result_iterator_batches(self, query):
        """Test batch iteration over OHLC results."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1m'
        )

        batch_count = 0
        total_bars = 0
        for batch in results.batches(size=10):
            batch_count += 1
            total_bars += len(batch)
            # Each batch should be a list
            assert isinstance(batch, list)
            # Each item should be a dict
            for bar in batch:
                assert isinstance(bar, dict)
                assert 'bar_time' in bar

        assert total_bars >= 1

    def test_result_iterator_count(self, query):
        """Test counting OHLC bars."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1m'
        )

        count = results.count()
        assert isinstance(count, int)
        assert count >= 0

    def test_build_ohlc_query_with_volume(self, query):
        """Test SQL generation for OHLC with volume."""
        sql = query._build_ohlc_query(
            ticker='HPG',
            start_dt='2023-06-15 00:00:00',
            end_dt='2023-06-16 00:00:00',
            interval='1m',
            include_volume=True
        )

        # Check SQL contains expected keywords
        assert 'time_bucket' in sql
        assert 'INTERVAL' in sql
        assert 'FIRST' in sql
        assert 'LAST' in sql
        assert 'MAX' in sql
        assert 'MIN' in sql
        assert 'SUM' in sql
        assert 'matched_volume' in sql
        assert 'LEFT JOIN' in sql

    def test_build_ohlc_query_without_volume(self, query):
        """Test SQL generation for OHLC without volume."""
        sql = query._build_ohlc_query(
            ticker='HPG',
            start_dt='2023-06-15 00:00:00',
            end_dt='2023-06-16 00:00:00',
            interval='1m',
            include_volume=False
        )

        # Check SQL contains expected keywords
        assert 'time_bucket' in sql
        assert 'FIRST' in sql
        assert 'LAST' in sql
        # Should NOT have volume or join
        assert 'volume' not in sql.lower()
        assert 'LEFT JOIN' not in sql

    def test_repr(self, query):
        """Test string representation."""
        repr_str = repr(query)
        assert 'OHLCQuery' in repr_str
        assert 'data_root' in repr_str

    # Parquet Tests
    def test_fetch_1m_bars_with_volume_parquet(self, parquet_query):
        """Test fetching 1-minute OHLC bars with volume from Parquet files."""
        results = parquet_query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1m',
            include_volume=True
        )

        # Convert to list
        bars = list(results)
        assert len(bars) >= 1

        # Check first bar structure
        bar = bars[0]
        assert 'bar_time' in bar
        assert 'tickersymbol' in bar
        assert 'open' in bar
        assert 'high' in bar
        assert 'low' in bar
        assert 'close' in bar
        assert 'volume' in bar

        # Verify OHLC relationships
        assert bar['high'] >= bar['open']
        assert bar['high'] >= bar['close']
        assert bar['high'] >= bar['low']
        assert bar['low'] <= bar['open']
        assert bar['low'] <= bar['close']

    def test_fetch_1m_bars_without_volume_parquet(self, parquet_query):
        """Test fetching 1-minute OHLC bars without volume from Parquet files."""
        results = parquet_query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1m',
            include_volume=False
        )

        bars = list(results)
        assert len(bars) >= 1

        # Check that volume is not included
        bar = bars[0]
        assert 'bar_time' in bar
        assert 'open' in bar
        assert 'high' in bar
        assert 'low' in bar
        assert 'close' in bar
        assert 'volume' not in bar

    def test_fetch_5m_bars_parquet(self, parquet_query):
        """Test fetching 5-minute OHLC bars from Parquet files."""
        results = parquet_query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='5m',
            include_volume=True
        )

        bars = list(results)
        # 5-minute bars should have fewer bars than 1-minute
        assert len(bars) >= 1

    def test_fetch_1d_bars_parquet(self, parquet_query):
        """Test fetching daily OHLC bars from Parquet files."""
        results = parquet_query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1d',
            include_volume=True
        )

        bars = list(results)
        # Should have 1 daily bar for 1-day range
        assert len(bars) == 1

        bar = bars[0]
        assert bar['tickersymbol'] == 'HPG'

    def test_fetch_with_datetime_parquet(self, parquet_query):
        """Test fetching with datetime (not just date) from Parquet files."""
        results = parquet_query.fetch(
            ticker='HPG',
            start_date='2023-06-15 09:00:00',
            end_date='2023-06-15 10:00:00',
            interval='1m',
            include_volume=True
        )

        bars = list(results)
        # Should have bars only within the hour
        assert len(bars) >= 1

    def test_result_iterator_to_dataframe_parquet(self, parquet_query):
        """Test converting OHLC results to DataFrame from Parquet files."""
        results = parquet_query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            interval='1m'
        )

        df = results.to_dataframe()
        assert df is not None
        assert len(df) >= 1
        assert 'bar_time' in df.columns
        assert 'open' in df.columns
        assert 'high' in df.columns
        assert 'low' in df.columns
        assert 'close' in df.columns
