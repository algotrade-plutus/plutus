"""Unit tests for CLI interface."""

import pytest
import subprocess
import sys
import json
from pathlib import Path


@pytest.fixture
def test_data_root():
    """Get CSV test data root directory."""
    return str(Path(__file__).parent.parent / 'sample_data' / 'csv')


@pytest.fixture
def parquet_data_root():
    """Get Parquet test data root directory."""
    return str(Path(__file__).parent.parent / 'sample_data' / 'parquet')


@pytest.fixture
def cli_command():
    """Base CLI command."""
    return [sys.executable, '-m', 'plutus.datahub']


class TestCLI:
    """Tests for command-line interface."""

    def test_help(self, cli_command):
        """Test --help flag."""
        result = subprocess.run(
            cli_command + ['--help'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'plutus-datahub' in result.stdout
        assert '--ticker' in result.stdout
        assert '--begin' in result.stdout
        assert '--end' in result.stdout

    def test_version(self, cli_command):
        """Test --version flag."""
        result = subprocess.run(
            cli_command + ['--version'],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert '0.1.0' in result.stdout or '0.1.0' in result.stderr

    def test_ohlc_csv_output(self, cli_command, test_data_root, tmp_path):
        """Test OHLC query with CSV output."""
        output_file = tmp_path / 'ohlc.csv'

        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--interval', '1m',
                '--output', str(output_file),
                '--format', 'csv',
                '--data-root', test_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert output_file.exists()

        # Check CSV content
        content = output_file.read_text()
        assert 'bar_time' in content
        assert 'open' in content
        assert 'high' in content
        assert 'low' in content
        assert 'close' in content
        assert 'HPG' in content

    def test_ohlc_json_output(self, cli_command, test_data_root, tmp_path):
        """Test OHLC query with JSON output."""
        output_file = tmp_path / 'ohlc.json'

        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--interval', '1m',
                '--output', str(output_file),
                '--format', 'json',
                '--data-root', test_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert output_file.exists()

        # Check JSON content
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)
        assert len(data) >= 1

        bar = data[0]
        assert 'bar_time' in bar
        assert 'open' in bar
        assert 'high' in bar
        assert 'low' in bar
        assert 'close' in bar
        assert bar['tickersymbol'] == 'HPG'

    def test_ohlc_table_output(self, cli_command, test_data_root):
        """Test OHLC query with table output."""
        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--interval', '1m',
                '--format', 'table',
                '--data-root', test_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert 'bar_time' in result.stdout
        assert 'open' in result.stdout
        assert 'HPG' in result.stdout
        assert 'rows' in result.stdout

    def test_ohlc_no_volume(self, cli_command, test_data_root, tmp_path):
        """Test OHLC query without volume."""
        output_file = tmp_path / 'ohlc_no_vol.json'

        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--interval', '1m',
                '--no-volume',
                '--output', str(output_file),
                '--format', 'json',
                '--data-root', test_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0

        # Check that volume is not included
        data = json.loads(output_file.read_text())
        assert 'volume' not in data[0]

    def test_tick_query(self, cli_command, test_data_root, tmp_path):
        """Test tick data query."""
        output_file = tmp_path / 'ticks.csv'

        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'tick',
                '--fields', 'matched_price',
                '--output', str(output_file),
                '--format', 'csv',
                '--data-root', test_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert output_file.exists()

        content = output_file.read_text()
        assert 'datetime' in content
        assert 'matched_price' in content
        assert 'HPG' in content

    def test_stats_mode(self, cli_command, test_data_root):
        """Test statistics mode."""
        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--interval', '1m',
                '--stats',
                '--data-root', test_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert 'Query Statistics' in result.stdout
        assert 'Ticker:' in result.stdout
        assert 'HPG' in result.stdout
        assert 'Records:' in result.stdout

    def test_limit_output(self, cli_command, test_data_root):
        """Test --limit flag."""
        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--interval', '1m',
                '--format', 'table',
                '--limit', '1',
                '--data-root', test_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        # Should have header + 1 data row
        lines = [l for l in result.stdout.split('\n') if 'HPG' in l]
        assert len(lines) == 1  # Only 1 data row

    def test_quiet_mode(self, cli_command, test_data_root, tmp_path):
        """Test --quiet flag."""
        output_file = tmp_path / 'quiet.csv'

        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--interval', '1m',
                '--output', str(output_file),
                '--quiet',
                '--data-root', test_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        # Stderr should be empty (no progress messages)
        assert result.stderr == ''

    def test_missing_required_args(self, cli_command):
        """Test error when required arguments are missing."""
        result = subprocess.run(
            cli_command + ['--ticker', 'HPG'],
            capture_output=True,
            text=True
        )

        assert result.returncode != 0
        assert '--begin' in result.stderr or 'required' in result.stderr

    def test_invalid_ticker(self, cli_command, test_data_root, tmp_path):
        """Test query with invalid ticker (should return empty)."""
        output_file = tmp_path / 'invalid.csv'

        result = subprocess.run(
            cli_command + [
                '--ticker', 'INVALID',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--output', str(output_file),
                '--data-root', test_data_root
            ],
            capture_output=True,
            text=True
        )

        # Should succeed but output "No data found"
        assert result.returncode == 0

    def test_invalid_interval(self, cli_command, test_data_root):
        """Test error with invalid interval."""
        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--interval', '99m',  # Invalid
                '--data-root', test_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode != 0
        assert 'invalid choice' in result.stderr.lower()

    def test_multiple_intervals(self, cli_command, test_data_root):
        """Test different OHLC intervals."""
        for interval in ['1m', '5m', '1d']:
            result = subprocess.run(
                cli_command + [
                    '--ticker', 'HPG',
                    '--begin', '2023-06-15',
                    '--end', '2023-06-16',
                    '--type', 'ohlc',
                    '--interval', interval,
                    '--format', 'table',
                    '--data-root', test_data_root
                ],
                capture_output=True,
                text=True
            )

            assert result.returncode == 0, f"Failed for interval {interval}"
            assert 'HPG' in result.stdout

    # Parquet Tests
    def test_ohlc_csv_output_with_parquet_data(self, cli_command, parquet_data_root, tmp_path):
        """Test OHLC query with Parquet input, CSV output."""
        output_file = tmp_path / 'ohlc_from_parquet.csv'

        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--interval', '1m',
                '--output', str(output_file),
                '--format', 'csv',
                '--data-root', parquet_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert output_file.exists()

        # Verify content
        content = output_file.read_text()
        assert 'bar_time' in content
        assert 'open' in content
        assert 'high' in content
        assert 'low' in content
        assert 'close' in content
        assert 'HPG' in content

    def test_tick_query_with_parquet_data(self, cli_command, parquet_data_root, tmp_path):
        """Test tick data query with Parquet files."""
        output_file = tmp_path / 'ticks_from_parquet.json'

        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'tick',
                '--fields', 'matched_price',
                '--output', str(output_file),
                '--format', 'json',
                '--data-root', parquet_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert output_file.exists()

        # Verify JSON content
        data = json.loads(output_file.read_text())
        assert isinstance(data, list)
        assert len(data) >= 1

        # Check first record structure
        first_record = data[0]
        assert 'datetime' in first_record
        assert 'tickersymbol' in first_record
        assert 'matched_price' in first_record

    def test_table_output_with_parquet_data(self, cli_command, parquet_data_root):
        """Test table format output with Parquet files."""
        result = subprocess.run(
            cli_command + [
                '--ticker', 'HPG',
                '--begin', '2023-06-15',
                '--end', '2023-06-16',
                '--type', 'ohlc',
                '--interval', '1m',
                '--format', 'table',
                '--data-root', parquet_data_root
            ],
            capture_output=True,
            text=True
        )

        assert result.returncode == 0
        assert 'bar_time' in result.stdout
        assert 'open' in result.stdout
        assert 'HPG' in result.stdout
        assert 'rows' in result.stdout
