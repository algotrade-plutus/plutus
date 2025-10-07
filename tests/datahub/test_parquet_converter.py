"""Unit tests for ParquetConverter class."""

import pytest
import tempfile
import shutil
from pathlib import Path
from plutus.datahub.converters import ParquetConverter, convert_to_parquet


@pytest.fixture
def temp_dirs():
    """Create temporary CSV and Parquet directories."""
    csv_dir = tempfile.mkdtemp()
    parquet_dir = tempfile.mkdtemp()

    yield Path(csv_dir), Path(parquet_dir)

    # Cleanup
    shutil.rmtree(csv_dir, ignore_errors=True)
    shutil.rmtree(parquet_dir, ignore_errors=True)


@pytest.fixture
def sample_csv_files(temp_dirs):
    """Create sample CSV files for testing."""
    csv_dir, _ = temp_dirs

    # Create a simple CSV file with market data
    csv_content = """datetime,tickersymbol,matched_price,matched_volume
2021-01-15 09:00:00,FPT,85.5,1000
2021-01-15 09:00:05,FPT,85.6,2000
2021-01-15 09:00:10,FPT,85.7,1500
2021-01-15 09:00:15,HPG,42.3,5000
2021-01-15 09:00:20,HPG,42.4,3000
"""

    # Write quote_matched.csv
    matched_file = csv_dir / 'quote_matched.csv'
    matched_file.write_text(csv_content)

    # Write quote_matchedvolume.csv (similar structure)
    volume_file = csv_dir / 'quote_matchedvolume.csv'
    volume_file.write_text(csv_content)

    return csv_dir


class TestParquetConverter:
    """Tests for ParquetConverter class."""

    def test_init_with_valid_paths(self, temp_dirs):
        """Test initialization with valid paths."""
        csv_dir, parquet_dir = temp_dirs

        converter = ParquetConverter(str(csv_dir), str(parquet_dir))

        assert converter.csv_root == csv_dir
        assert converter.parquet_root == parquet_dir
        assert parquet_dir.exists()

    def test_init_with_invalid_csv_path(self, temp_dirs):
        """Test initialization with invalid CSV path raises error."""
        _, parquet_dir = temp_dirs

        with pytest.raises(FileNotFoundError) as exc_info:
            ParquetConverter('/invalid/path', str(parquet_dir))

        assert 'CSV directory not found' in str(exc_info.value)

    def test_init_creates_parquet_dir(self, temp_dirs):
        """Test that parquet directory is created if it doesn't exist."""
        csv_dir, _ = temp_dirs

        # Use non-existent parquet directory
        parquet_dir = csv_dir / 'new_parquet_dir'
        assert not parquet_dir.exists()

        converter = ParquetConverter(str(csv_dir), str(parquet_dir))

        assert parquet_dir.exists()

    def test_convert_single_file(self, sample_csv_files, temp_dirs):
        """Test converting a single CSV file to Parquet."""
        csv_dir, parquet_dir = temp_dirs

        converter = ParquetConverter(str(csv_dir), str(parquet_dir))
        results = converter.convert(['quote_matched.csv'], show_progress=False)

        # Check results
        assert 'quote_matched.csv' in results
        stats = results['quote_matched.csv']

        assert stats['csv_size'] > 0
        assert stats['parquet_size'] > 0
        # Note: For very small files, Parquet may be larger due to metadata overhead
        # This is expected behavior - Parquet is optimized for large datasets
        assert stats['reduction'] is not None  # Reduction is calculated (may be negative)
        assert stats['duration'] >= 0

        # Check Parquet file was created
        parquet_file = parquet_dir / 'quote_matched.parquet'
        assert parquet_file.exists()

    def test_convert_multiple_files(self, sample_csv_files, temp_dirs):
        """Test converting multiple CSV files."""
        csv_dir, parquet_dir = temp_dirs

        converter = ParquetConverter(str(csv_dir), str(parquet_dir))
        results = converter.convert(
            ['quote_matched.csv', 'quote_matchedvolume.csv'],
            show_progress=False
        )

        # Check both files were converted
        assert len(results) == 2
        assert 'quote_matched.csv' in results
        assert 'quote_matchedvolume.csv' in results

        # Check Parquet files exist
        assert (parquet_dir / 'quote_matched.parquet').exists()
        assert (parquet_dir / 'quote_matchedvolume.parquet').exists()

    def test_convert_nonexistent_file_raises(self, sample_csv_files, temp_dirs):
        """Test converting non-existent file raises error."""
        csv_dir, parquet_dir = temp_dirs

        converter = ParquetConverter(str(csv_dir), str(parquet_dir))

        with pytest.raises(FileNotFoundError) as exc_info:
            converter.convert(['nonexistent.csv'], show_progress=False)

        assert 'CSV file not found' in str(exc_info.value)

    def test_convert_all(self, sample_csv_files, temp_dirs):
        """Test converting all CSV files in directory."""
        csv_dir, parquet_dir = temp_dirs

        converter = ParquetConverter(str(csv_dir), str(parquet_dir))
        results = converter.convert_all(show_progress=False)

        # Should convert both CSV files
        assert len(results) == 2
        assert 'quote_matched.csv' in results
        assert 'quote_matchedvolume.csv' in results

    def test_parquet_file_readable(self, sample_csv_files, temp_dirs):
        """Test that generated Parquet file is readable."""
        import duckdb

        csv_dir, parquet_dir = temp_dirs

        converter = ParquetConverter(str(csv_dir), str(parquet_dir))
        converter.convert(['quote_matched.csv'], show_progress=False)

        # Read Parquet file with DuckDB
        parquet_file = parquet_dir / 'quote_matched.parquet'
        conn = duckdb.connect(':memory:')

        result = conn.execute(
            f"SELECT COUNT(*) as cnt FROM read_parquet('{parquet_file}')"
        ).fetchone()

        # Should have 5 rows (from sample CSV)
        assert result[0] == 5

    def test_parquet_preserves_data(self, sample_csv_files, temp_dirs):
        """Test that Parquet conversion preserves data correctly."""
        import duckdb

        csv_dir, parquet_dir = temp_dirs

        # Read original CSV
        csv_file = csv_dir / 'quote_matched.csv'
        conn = duckdb.connect(':memory:')

        csv_data = conn.execute(
            f"SELECT * FROM read_csv_auto('{csv_file}') ORDER BY datetime"
        ).fetchall()

        # Convert to Parquet
        converter = ParquetConverter(str(csv_dir), str(parquet_dir))
        converter.convert(['quote_matched.csv'], show_progress=False)

        # Read Parquet
        parquet_file = parquet_dir / 'quote_matched.parquet'
        parquet_data = conn.execute(
            f"SELECT * FROM read_parquet('{parquet_file}') ORDER BY datetime"
        ).fetchall()

        # Data should match
        assert csv_data == parquet_data


class TestConvertToParquetFunction:
    """Tests for convert_to_parquet convenience function."""

    def test_convert_specific_files(self, sample_csv_files, temp_dirs):
        """Test converting specific files using convenience function."""
        csv_dir, parquet_dir = temp_dirs

        results = convert_to_parquet(
            csv_root=str(csv_dir),
            parquet_root=str(parquet_dir),
            files=['quote_matched.csv'],
            show_progress=False
        )

        assert len(results) == 1
        assert 'quote_matched.csv' in results
        assert (parquet_dir / 'quote_matched.parquet').exists()

    def test_convert_all_files(self, sample_csv_files, temp_dirs):
        """Test converting all files using convenience function."""
        csv_dir, parquet_dir = temp_dirs

        results = convert_to_parquet(
            csv_root=str(csv_dir),
            parquet_root=str(parquet_dir),
            files=None,  # Convert all
            show_progress=False
        )

        assert len(results) == 2
        assert 'quote_matched.csv' in results
        assert 'quote_matchedvolume.csv' in results
