"""Unit tests for MCP tools."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from plutus.mcp.tools import register_tools
from plutus.mcp.config import MCPServerConfig


class TestToolsRegistration:
    """Tests for tools registration."""

    def test_register_tools(self, mock_config, mock_datahub_config, monkeypatch):
        """Test that tools are registered correctly."""
        mock_mcp = Mock()
        mock_mcp.tool = Mock(return_value=lambda f: f)  # Decorator returns function unchanged

        # Mock query_historical to avoid file system access
        def mock_query(*args, **kwargs):
            return iter([])

        monkeypatch.setattr("plutus.mcp.tools.query_historical", mock_query)

        # Register tools
        register_tools(mock_mcp, mock_config)

        # Verify tool decorator was called 4 times (4 tools)
        assert mock_mcp.tool.call_count == 4


class TestQueryTickData:
    """Tests for query_tick_data tool."""

    @patch('plutus.mcp.tools.query_historical')
    @patch('plutus.mcp.tools.parse_datetime')
    @patch('plutus.mcp.tools.validate_date_range')
    def test_query_tick_data_success(self, mock_validate, mock_parse, mock_query,
                                      mock_config, mock_datahub_config, sample_tick_data):
        """Test successful tick data query."""
        # Setup mocks
        mock_parse.side_effect = [
            datetime(2021, 1, 15, 9, 0),
            datetime(2021, 1, 15, 10, 0)
        ]
        mock_query.return_value = iter(sample_tick_data)

        # Create mock MCP and register tools
        mock_mcp = Mock()
        tools_dict = {}

        def tool_decorator():
            def wrapper(func):
                tools_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.tool = tool_decorator
        register_tools(mock_mcp, mock_config)

        # Call the tool
        query_tick_data = tools_dict['query_tick_data']
        result = query_tick_data(
            ticker="FPT",
            start_date="2021-01-15 09:00",
            end_date="2021-01-15 10:00",
            fields=["matched_price"],
            limit=10
        )

        # Verify result
        assert result["ticker"] == "FPT"
        assert result["row_count"] == 3
        assert result["limit"] == 10
        assert len(result["data"]) == 3
        assert "error" not in result

    @patch('plutus.mcp.tools.parse_datetime')
    def test_query_tick_data_invalid_ticker(self, mock_parse, mock_config,
                                             mock_datahub_config):
        """Test tick data query with invalid ticker."""
        mock_parse.side_effect = [
            datetime(2021, 1, 15),
            datetime(2021, 1, 16)
        ]

        # Create mock MCP and register tools
        mock_mcp = Mock()
        tools_dict = {}

        def tool_decorator():
            def wrapper(func):
                tools_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.tool = tool_decorator
        register_tools(mock_mcp, mock_config)

        # Call with invalid ticker
        query_tick_data = tools_dict['query_tick_data']
        result = query_tick_data(
            ticker="INVALID-TICKER",  # Invalid: contains hyphen
            start_date="2021-01-15",
            end_date="2021-01-16"
        )

        # Verify error response
        assert "error" in result
        assert result["error"]["code"] == "INVALID_INPUT"
        assert "invalid characters" in result["error"]["message"].lower()

    @patch('plutus.mcp.tools.query_historical')
    @patch('plutus.mcp.tools.parse_datetime')
    @patch('plutus.mcp.tools.validate_date_range')
    def test_query_tick_data_with_limit(self, mock_validate, mock_parse, mock_query,
                                         mock_config, mock_datahub_config):
        """Test tick data query respects limit."""
        # Generate large dataset
        large_data = [{"datetime": f"2021-01-15 09:00:{i:02d}", "price": 85000 + i}
                      for i in range(100)]

        mock_parse.side_effect = [
            datetime(2021, 1, 15, 9, 0),
            datetime(2021, 1, 15, 10, 0)
        ]
        mock_query.return_value = iter(large_data)

        # Create mock MCP and register tools
        mock_mcp = Mock()
        tools_dict = {}

        def tool_decorator():
            def wrapper(func):
                tools_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.tool = tool_decorator
        register_tools(mock_mcp, mock_config)

        # Call with limit
        query_tick_data = tools_dict['query_tick_data']
        result = query_tick_data(
            ticker="FPT",
            start_date="2021-01-15 09:00",
            end_date="2021-01-15 10:00",
            limit=10  # Should only return 10 rows
        )

        # Verify limit is respected
        assert result["row_count"] == 10
        assert len(result["data"]) == 10


class TestQueryOHLCData:
    """Tests for query_ohlc_data tool."""

    @patch('plutus.mcp.tools.query_historical')
    @patch('plutus.mcp.tools.parse_datetime')
    @patch('plutus.mcp.tools.validate_date_range')
    def test_query_ohlc_data_success(self, mock_validate, mock_parse, mock_query,
                                      mock_config, mock_datahub_config, sample_ohlc_data):
        """Test successful OHLC data query."""
        mock_parse.side_effect = [
            datetime(2021, 1, 15),
            datetime(2021, 1, 16)
        ]
        mock_query.return_value = iter(sample_ohlc_data)

        # Create mock MCP and register tools
        mock_mcp = Mock()
        tools_dict = {}

        def tool_decorator():
            def wrapper(func):
                tools_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.tool = tool_decorator
        register_tools(mock_mcp, mock_config)

        # Call the tool
        query_ohlc_data = tools_dict['query_ohlc_data']
        result = query_ohlc_data(
            ticker="FPT",
            start_date="2021-01-15",
            end_date="2021-01-16",
            interval="5m",
            include_volume=True,
            limit=10
        )

        # Verify result
        assert result["ticker"] == "FPT"
        assert result["interval"] == "5m"
        assert result["include_volume"] is True
        assert result["bar_count"] == 2
        assert "error" not in result

    def test_query_ohlc_data_invalid_interval(self, mock_config,
                                                mock_datahub_config):
        """Test OHLC query with invalid interval."""
        # Create mock MCP and register tools
        mock_mcp = Mock()
        tools_dict = {}

        def tool_decorator():
            def wrapper(func):
                tools_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.tool = tool_decorator
        register_tools(mock_mcp, mock_config)

        # Call with invalid interval
        query_ohlc_data = tools_dict['query_ohlc_data']
        result = query_ohlc_data(
            ticker="FPT",
            start_date="2021-01-15",
            end_date="2021-01-16",
            interval="2m"  # Invalid interval
        )

        # Verify error response
        assert "error" in result
        assert result["error"]["code"] == "INVALID_INPUT"
        assert "interval" in result["error"]["message"].lower()


class TestGetAvailableFields:
    """Tests for get_available_fields tool."""

    def test_get_available_fields(self, mock_config, mock_datahub_config):
        """Test getting available fields."""
        # Create mock MCP and register tools
        mock_mcp = Mock()
        tools_dict = {}

        def tool_decorator():
            def wrapper(func):
                tools_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.tool = tool_decorator
        register_tools(mock_mcp, mock_config)

        # Call the tool
        get_available_fields = tools_dict['get_available_fields']
        result = get_available_fields()

        # Verify result structure
        assert "intraday_fields" in result
        assert "aggregation_fields" in result
        assert isinstance(result["intraday_fields"], list)
        assert isinstance(result["aggregation_fields"], list)

        # Verify some expected fields exist
        field_names = [f["name"] for f in result["intraday_fields"]]
        assert "matched_price" in field_names
        assert "matched_volume" in field_names
        assert "bid_price" in field_names
        assert "ask_price" in field_names

        # Verify order book fields have depth levels
        bid_price = next(f for f in result["intraday_fields"] if f["name"] == "bid_price")
        assert bid_price["depth_levels"] == list(range(1, 11))


class TestGetQueryStatistics:
    """Tests for get_query_statistics tool."""

    @patch('plutus.mcp.tools.parse_datetime')
    @patch('plutus.mcp.tools.validate_date_range')
    def test_get_query_statistics_tick(self, mock_validate, mock_parse,
                                        mock_config, mock_datahub_config):
        """Test getting query statistics for tick data."""
        mock_parse.side_effect = [
            datetime(2021, 1, 1),
            datetime(2021, 12, 31)
        ]

        # Create mock MCP and register tools
        mock_mcp = Mock()
        tools_dict = {}

        def tool_decorator():
            def wrapper(func):
                tools_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.tool = tool_decorator
        register_tools(mock_mcp, mock_config)

        # Call the tool
        get_query_statistics = tools_dict['get_query_statistics']
        result = get_query_statistics(
            ticker="FPT",
            start_date="2021-01-01",
            end_date="2021-12-31",
            query_type="tick"
        )

        # Verify result
        assert result["ticker"] == "FPT"
        assert result["query_type"] == "tick"
        assert result["date_range_days"] > 300  # Should be ~365
        assert result["estimated_rows"] > 0
        assert result["data_available"] is True

    @patch('plutus.mcp.tools.parse_datetime')
    @patch('plutus.mcp.tools.validate_date_range')
    def test_get_query_statistics_ohlc(self, mock_validate, mock_parse,
                                        mock_config, mock_datahub_config):
        """Test getting query statistics for OHLC data."""
        mock_parse.side_effect = [
            datetime(2021, 1, 1),
            datetime(2021, 1, 31)
        ]

        # Create mock MCP and register tools
        mock_mcp = Mock()
        tools_dict = {}

        def tool_decorator():
            def wrapper(func):
                tools_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.tool = tool_decorator
        register_tools(mock_mcp, mock_config)

        # Call the tool
        get_query_statistics = tools_dict['get_query_statistics']
        result = get_query_statistics(
            ticker="VIC",
            start_date="2021-01-01",
            end_date="2021-01-31",
            query_type="ohlc"
        )

        # Verify result
        assert result["ticker"] == "VIC"
        assert result["query_type"] == "ohlc"
        assert result["date_range_days"] >= 30
        # OHLC should have fewer rows than tick for same period
        assert result["estimated_rows"] < 1000000
