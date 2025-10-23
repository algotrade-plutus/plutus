"""Unit tests for MCP resources."""

import pytest
from unittest.mock import Mock

from plutus.mcp.resources import register_resources
from plutus.mcp.config import MCPServerConfig


class TestResourcesRegistration:
    """Tests for resources registration."""

    def test_register_resources(self, mock_config):
        """Test that resources are registered correctly."""
        mock_mcp = Mock()
        mock_mcp.resource = Mock(return_value=lambda f: f)

        register_resources(mock_mcp, mock_config)

        # Verify resource decorator was called 4 times (4 resources)
        assert mock_mcp.resource.call_count == 4


class TestDatasetMetadata:
    """Tests for dataset://metadata resource."""

    def test_dataset_metadata(self, mock_config):
        """Test dataset metadata resource."""
        # Create mock MCP and register resources
        mock_mcp = Mock()
        resources_dict = {}

        def resource_decorator(uri):
            def wrapper(func):
                resources_dict[uri] = func
                return func
            return wrapper

        mock_mcp.resource = resource_decorator
        register_resources(mock_mcp, mock_config)

        # Call the resource
        dataset_metadata = resources_dict['dataset://metadata']
        result = dataset_metadata()

        # Verify result structure
        assert "name" in result
        assert "description" in result
        assert "size_gb" in result
        assert "date_range" in result
        assert "data_types" in result
        assert "total_files" in result

        # Verify content
        assert result["name"] == "Hermes Market Data Pre-2023"
        assert result["size_gb"] == 21
        assert result["date_range"]["start"] == "2000-01-01"
        assert result["date_range"]["end"] == "2022-12-31"
        assert result["total_files"] == 41


class TestDatasetTickers:
    """Tests for dataset://tickers resource."""

    def test_dataset_tickers(self, mock_config):
        """Test dataset tickers resource."""
        # Create mock MCP and register resources
        mock_mcp = Mock()
        resources_dict = {}

        def resource_decorator(uri):
            def wrapper(func):
                resources_dict[uri] = func
                return func
            return wrapper

        mock_mcp.resource = resource_decorator
        register_resources(mock_mcp, mock_config)

        # Call the resource
        dataset_tickers = resources_dict['dataset://tickers']
        result = dataset_tickers()

        # Verify result structure
        assert "tickers" in result
        assert "total_count" in result
        assert "exchanges" in result
        assert isinstance(result["tickers"], list)

        # Verify content
        assert result["total_count"] > 0
        assert len(result["tickers"]) == result["total_count"]

        # Verify ticker structure
        if result["total_count"] > 0:
            ticker = result["tickers"][0]
            assert "symbol" in ticker
            assert "exchange" in ticker

        # Verify common tickers exist
        ticker_symbols = [t["symbol"] for t in result["tickers"]]
        assert "FPT" in ticker_symbols
        assert "VIC" in ticker_symbols


class TestDatasetFields:
    """Tests for dataset://fields resource."""

    def test_dataset_fields(self, mock_config):
        """Test dataset fields resource."""
        # Create mock MCP and register resources
        mock_mcp = Mock()
        resources_dict = {}

        def resource_decorator(uri):
            def wrapper(func):
                resources_dict[uri] = func
                return func
            return wrapper

        mock_mcp.resource = resource_decorator
        register_resources(mock_mcp, mock_config)

        # Call the resource
        dataset_fields = resources_dict['dataset://fields']
        result = dataset_fields()

        # Verify result structure
        assert "intraday_fields" in result
        assert "aggregation_fields" in result
        assert "categories" in result
        assert isinstance(result["intraday_fields"], list)
        assert isinstance(result["aggregation_fields"], list)

        # Verify field structure
        if len(result["intraday_fields"]) > 0:
            field = result["intraday_fields"][0]
            assert "name" in field
            assert "description" in field
            assert "category" in field
            assert "unit" in field
            assert "depth_levels" in field
            assert "nullable" in field

        # Verify specific fields exist
        intraday_names = [f["name"] for f in result["intraday_fields"]]
        assert "matched_price" in intraday_names
        assert "bid_price" in intraday_names
        assert "ask_price" in intraday_names

        aggregation_names = [f["name"] for f in result["aggregation_fields"]]
        assert "daily_volume" in aggregation_names
        assert "reference_price" in aggregation_names


class TestDatasetIntervals:
    """Tests for dataset://intervals resource."""

    def test_dataset_intervals(self, mock_config):
        """Test dataset intervals resource."""
        # Create mock MCP and register resources
        mock_mcp = Mock()
        resources_dict = {}

        def resource_decorator(uri):
            def wrapper(func):
                resources_dict[uri] = func
                return func
            return wrapper

        mock_mcp.resource = resource_decorator
        register_resources(mock_mcp, mock_config)

        # Call the resource
        dataset_intervals = resources_dict['dataset://intervals']
        result = dataset_intervals()

        # Verify result structure
        assert "intervals" in result
        assert "trading_hours" in result
        assert isinstance(result["intervals"], list)

        # Verify interval structure
        if len(result["intervals"]) > 0:
            interval = result["intervals"][0]
            assert "code" in interval
            assert "description" in interval
            assert "bars_per_day" in interval
            assert "use_case" in interval

        # Verify all expected intervals exist
        interval_codes = [i["code"] for i in result["intervals"]]
        expected_intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
        for expected in expected_intervals:
            assert expected in interval_codes

        # Verify trading hours
        assert "morning_session" in result["trading_hours"]
        assert "afternoon_session" in result["trading_hours"]
        assert result["trading_hours"]["total_minutes"] == 270
