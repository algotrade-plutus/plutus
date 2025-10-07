"""Tests for DataHubConfig."""

import pytest
from pathlib import Path
from plutus.datahub.config import DataHubConfig


class TestDataHubConfig:
    """Test suite for DataHubConfig class."""

    def test_init_with_explicit_path(self):
        """Test initialization with explicit data root path."""
        # Use tests/sample_data/csv as a test dataset
        test_root = Path(__file__).parent.parent / "sample_data" / "csv"

        config = DataHubConfig(data_root=str(test_root))
        assert config.data_root == test_root.resolve()

    def test_init_with_invalid_path_raises(self):
        """Test that invalid path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            DataHubConfig(data_root="/nonexistent/path")

    def test_get_file_path_matched_price(self):
        """Test getting file path for matched_price field."""
        test_root = Path(__file__).parent.parent / "sample_data" / "csv"
        config = DataHubConfig(data_root=str(test_root))

        file_path = config.get_file_path('matched_price')
        assert file_path.name == 'quote_matched.csv'
        assert file_path.parent == config.data_root

    def test_get_file_path_with_depth_suffix(self):
        """Test getting file path for field with depth suffix (e.g., bid_price_1)."""
        test_root = Path(__file__).parent.parent / "sample_data" / "csv"
        config = DataHubConfig(data_root=str(test_root))

        # bid_price_1 should map to quote_bidprice.csv
        file_path = config.get_file_path('bid_price_1')
        assert file_path.name == 'quote_bidprice.csv'

    def test_get_file_path_unknown_field_raises(self):
        """Test that unknown field raises ValueError."""
        test_root = Path(__file__).parent.parent / "sample_data" / "csv"
        config = DataHubConfig(data_root=str(test_root))

        with pytest.raises(ValueError, match="Unknown field"):
            config.get_file_path('nonexistent_field')

    def test_get_available_fields(self):
        """Test getting list of available fields."""
        test_root = Path(__file__).parent.parent / "sample_data" / "csv"
        config = DataHubConfig(data_root=str(test_root))

        fields = config.get_available_fields()
        assert isinstance(fields, list)
        assert len(fields) > 0
        assert 'matched_price' in fields
        assert 'bid_price' in fields
        assert 'ask_price' in fields

    def test_field_mappings_complete(self):
        """Test that all expected fields are in mappings."""
        expected_fields = [
            'matched_price',
            'open_price',
            'close_price',
            'high_price',
            'low_price',
            'bid_price',
            'ask_price',
            'matched_volume',
        ]

        test_root = Path(__file__).parent.parent / "sample_data" / "csv"
        config = DataHubConfig(data_root=str(test_root))
        available = config.get_available_fields()

        for field in expected_fields:
            assert field in available, f"Field {field} missing from mappings"

    def test_repr(self):
        """Test string representation."""
        test_root = Path(__file__).parent.parent / "sample_data" / "csv"
        config = DataHubConfig(data_root=str(test_root))

        repr_str = repr(config)
        assert 'DataHubConfig' in repr_str
        assert str(test_root.resolve()) in repr_str

    def test_parquet_only_deployment(self):
        """Test that Parquet-only deployment works (no CSV files)."""
        import tempfile
        import shutil

        # Create temporary directory with only Parquet files
        temp_dir = tempfile.mkdtemp()

        try:
            # Create critical Parquet files (no CSV files)
            (Path(temp_dir) / 'quote_matched.parquet').touch()
            (Path(temp_dir) / 'quote_ticker.parquet').touch()

            # Should not raise error (accepts Parquet without CSV)
            config = DataHubConfig(data_root=temp_dir, prefer_parquet=True)
            assert config.data_root == Path(temp_dir).resolve()

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_get_file_path_prefers_parquet(self):
        """Test that get_file_path prefers Parquet when both formats exist."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()

        try:
            # Create both CSV and Parquet files
            csv_file = Path(temp_dir) / 'quote_matched.csv'
            parquet_file = Path(temp_dir) / 'quote_matched.parquet'
            csv_file.touch()
            parquet_file.touch()

            # Also create critical files for validation
            (Path(temp_dir) / 'quote_ticker.csv').touch()

            config = DataHubConfig(data_root=temp_dir, prefer_parquet=True)

            # Should return Parquet path
            path = config.get_file_path('matched_price')
            assert path.resolve() == parquet_file.resolve()
            assert path.suffix == '.parquet'

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_get_file_path_falls_back_to_csv(self):
        """Test that get_file_path falls back to CSV when Parquet doesn't exist."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()

        try:
            # Create only CSV files
            csv_file = Path(temp_dir) / 'quote_matched.csv'
            csv_file.touch()

            # Critical files for validation
            (Path(temp_dir) / 'quote_ticker.csv').touch()

            config = DataHubConfig(data_root=temp_dir, prefer_parquet=True)

            # Should return CSV path (Parquet doesn't exist)
            path = config.get_file_path('matched_price')
            assert path.resolve() == csv_file.resolve()
            assert path.suffix == '.csv'

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validation_accepts_parquet_or_csv(self):
        """Test that validation accepts either Parquet or CSV for critical files."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()

        try:
            # One critical file as Parquet, one as CSV
            (Path(temp_dir) / 'quote_matched.parquet').touch()
            (Path(temp_dir) / 'quote_ticker.csv').touch()

            # Should not raise error (mixed formats acceptable)
            config = DataHubConfig(data_root=temp_dir)
            assert config is not None

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validation_fails_when_both_formats_missing(self):
        """Test that validation fails when neither CSV nor Parquet exists."""
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()

        try:
            # Only one critical file, missing the other
            (Path(temp_dir) / 'quote_matched.csv').touch()
            # quote_ticker missing in both formats

            # Should raise error
            with pytest.raises(FileNotFoundError, match="Critical files missing"):
                DataHubConfig(data_root=temp_dir)

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_config_with_csv_sample_data(self):
        """Test DataHubConfig works with CSV sample data directory."""
        test_root = Path(__file__).parent.parent / "sample_data" / "csv"
        config = DataHubConfig(data_root=str(test_root))

        # Should find CSV files
        file_path = config.get_file_path('matched_price')
        assert file_path.suffix == '.csv'
        assert file_path.exists()
        assert 'quote_matched.csv' in str(file_path)

    def test_config_with_parquet_sample_data(self):
        """Test DataHubConfig works with Parquet sample data directory."""
        test_root = Path(__file__).parent.parent / "sample_data" / "parquet"
        config = DataHubConfig(data_root=str(test_root), prefer_parquet=True)

        # Should find Parquet files
        file_path = config.get_file_path('matched_price')
        assert file_path.suffix == '.parquet'
        assert file_path.exists()
        assert 'quote_matched.parquet' in str(file_path)
