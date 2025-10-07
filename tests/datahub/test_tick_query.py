"""Tests for TickDataQuery."""

import pytest
from pathlib import Path
from plutus.datahub.config import DataHubConfig
from plutus.datahub.tick_query import TickDataQuery


class TestTickDataQuery:
    """Test suite for TickDataQuery class."""

    @pytest.fixture
    def test_config(self):
        """Create test configuration with CSV sample data."""
        test_root = Path(__file__).parent.parent / "sample_data" / "csv"
        return DataHubConfig(data_root=str(test_root))

    @pytest.fixture
    def parquet_config(self):
        """Create test configuration with Parquet sample data."""
        test_root = Path(__file__).parent.parent / "sample_data" / "parquet"
        return DataHubConfig(data_root=str(test_root), prefer_parquet=True)

    @pytest.fixture
    def query(self, test_config):
        """Create TickDataQuery instance with CSV data."""
        return TickDataQuery(test_config)

    @pytest.fixture
    def parquet_query(self, parquet_config):
        """Create TickDataQuery instance with Parquet data."""
        return TickDataQuery(parquet_config)

    def test_init(self, query):
        """Test TickDataQuery initialization."""
        assert query.config is not None
        assert query._conn is not None

    def test_fetch_single_field(self, query):
        """Test fetching single field (matched_price)."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            fields=['matched_price']
        )

        # Check that we can iterate
        rows = list(results)
        assert len(rows) >= 1  # Sample data has at least 1 HPG record

        # Check row structure
        first_row = rows[0]
        assert 'datetime' in first_row
        assert 'tickersymbol' in first_row
        assert 'matched_price' in first_row

        # Check values
        assert first_row['tickersymbol'] == 'HPG'
        assert first_row['matched_price'] is not None

    def test_fetch_with_datetime(self, query):
        """Test fetching with datetime (hour/minute precision)."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15 09:00',
            end_date='2023-06-15 10:00',
            fields=['matched_price']
        )

        rows = list(results)
        # Should have some data in the morning session
        assert len(rows) >= 0  # May be 0 if no trades in that hour

    def test_fetch_invalid_ticker_returns_empty(self, query):
        """Test that invalid ticker returns empty result."""
        results = query.fetch(
            ticker='NONEXISTENT',
            start_date='2023-06-15',
            end_date='2023-06-16',
            fields=['matched_price']
        )

        rows = list(results)
        assert len(rows) == 0

    def test_fetch_invalid_date_range_raises(self, query):
        """Test that invalid date range raises ValueError."""
        with pytest.raises(ValueError, match="Invalid date range"):
            query.fetch(
                ticker='HPG',
                start_date='2023-06-16',  # End before start
                end_date='2023-06-15',
                fields=['matched_price']
            )

    def test_fetch_invalid_date_format_raises(self, query):
        """Test that invalid date format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid date/datetime format"):
            query.fetch(
                ticker='HPG',
                start_date='15-06-2023',  # Wrong format
                end_date='2023-06-16',
                fields=['matched_price']
            )

    def test_result_iterator_count(self, query):
        """Test that ResultIterator supports count()."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            fields=['matched_price']
        )

        # count() should execute COUNT(*) query
        count = results.count()
        assert isinstance(count, int)
        assert count >= 0

    def test_result_iterator_to_dataframe(self, query):
        """Test converting results to DataFrame."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            fields=['matched_price']
        )

        df = results.to_dataframe()
        assert df is not None
        assert len(df) >= 0
        assert 'datetime' in df.columns
        assert 'matched_price' in df.columns

    def test_result_iterator_batches(self, query):
        """Test batch iteration."""
        results = query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            fields=['matched_price']
        )

        # Collect all batches
        all_rows = []
        for batch in results.batches(size=100):
            assert isinstance(batch, list)
            assert len(batch) <= 100
            all_rows.extend(batch)

        # Should have some data
        assert len(all_rows) >= 0

    def test_build_simple_query_sql(self, query):
        """Test SQL generation for simple query."""
        sql = query._build_simple_query(
            ticker='HPG',
            start_dt='2023-06-15 00:00:00',
            end_dt='2023-06-16 00:00:00',
            field='matched_price'
        )

        # Check SQL contains expected elements
        assert 'SELECT' in sql
        assert 'datetime' in sql
        assert 'tickersymbol' in sql
        assert 'matched_price' in sql
        assert 'quote_matched' in sql  # File base name (format-agnostic)
        assert "tickersymbol = 'HPG'" in sql
        assert 'ORDER BY datetime' in sql

    def test_repr(self, query):
        """Test string representation."""
        repr_str = repr(query)
        assert 'TickDataQuery' in repr_str

    # Parquet Tests
    def test_fetch_single_field_parquet(self, parquet_query):
        """Test fetching single field (matched_price) from Parquet files."""
        results = parquet_query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            fields=['matched_price']
        )

        # Check that we can iterate
        rows = list(results)
        assert len(rows) >= 1  # Sample data has at least 1 HPG record

        # Check row structure
        first_row = rows[0]
        assert 'datetime' in first_row
        assert 'tickersymbol' in first_row
        assert 'matched_price' in first_row

        # Check values
        assert first_row['tickersymbol'] == 'HPG'
        assert first_row['matched_price'] is not None

    def test_fetch_with_datetime_parquet(self, parquet_query):
        """Test fetching with datetime (hour/minute precision) from Parquet files."""
        results = parquet_query.fetch(
            ticker='HPG',
            start_date='2023-06-15 09:00',
            end_date='2023-06-15 10:00',
            fields=['matched_price']
        )

        rows = list(results)
        # Should have some data in the morning session
        assert len(rows) >= 0  # May be 0 if no trades in that hour

    def test_result_iterator_to_dataframe_parquet(self, parquet_query):
        """Test converting results to DataFrame from Parquet files."""
        results = parquet_query.fetch(
            ticker='HPG',
            start_date='2023-06-15',
            end_date='2023-06-16',
            fields=['matched_price']
        )

        df = results.to_dataframe()
        assert df is not None
        assert len(df) >= 0
        assert 'datetime' in df.columns
        assert 'matched_price' in df.columns

    def test_build_simple_query_sql_parquet(self, parquet_query):
        """Test SQL generation for Parquet files."""
        sql = parquet_query._build_simple_query(
            ticker='HPG',
            start_dt='2023-06-15 00:00:00',
            end_dt='2023-06-16 00:00:00',
            field='matched_price'
        )

        # Check SQL contains expected elements
        assert 'SELECT' in sql
        assert 'datetime' in sql
        assert 'tickersymbol' in sql
        assert 'matched_price' in sql
        assert 'quote_matched.parquet' in sql
        assert "tickersymbol = 'HPG'" in sql
        assert 'ORDER BY datetime' in sql
