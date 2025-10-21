"""Unit tests for MCP utility functions."""

import pytest

from plutus.mcp.utils import (
    create_error_response,
    format_tick_response,
    format_ohlc_response,
    validate_ticker,
    validate_interval,
    truncate_list,
    format_statistics_response,
    get_sample_tickers
)


class TestErrorResponse:
    """Tests for error response formatting."""

    def test_create_error_response_minimal(self):
        """Test error response with minimal parameters."""
        error = create_error_response(
            code="TEST_ERROR",
            message="Test error message"
        )

        assert "error" in error
        assert error["error"]["code"] == "TEST_ERROR"
        assert error["error"]["message"] == "Test error message"
        assert "details" not in error["error"]
        assert "suggestion" not in error["error"]

    def test_create_error_response_full(self):
        """Test error response with all parameters."""
        error = create_error_response(
            code="INVALID_TICKER",
            message="Ticker not found",
            details={"ticker": "INVALID"},
            suggestion="Use get_available_fields()"
        )

        assert error["error"]["code"] == "INVALID_TICKER"
        assert error["error"]["message"] == "Ticker not found"
        assert error["error"]["details"] == {"ticker": "INVALID"}
        assert error["error"]["suggestion"] == "Use get_available_fields()"


class TestResponseFormatting:
    """Tests for response formatting functions."""

    def test_format_tick_response(self):
        """Test tick data response formatting."""
        data = [{"datetime": "2021-01-15", "price": 100}]
        response = format_tick_response(
            ticker="FPT",
            start_date="2021-01-15",
            end_date="2021-01-16",
            fields=["matched_price"],
            data=data,
            limit=1000
        )

        assert response["ticker"] == "FPT"
        assert response["start_date"] == "2021-01-15"
        assert response["end_date"] == "2021-01-16"
        assert response["fields"] == ["matched_price"]
        assert response["row_count"] == 1
        assert response["limit"] == 1000
        assert response["data"] == data

    def test_format_ohlc_response(self):
        """Test OHLC response formatting."""
        data = [{"bar_time": "2021-01-15", "open": 100, "close": 105}]
        response = format_ohlc_response(
            ticker="VIC",
            start_date="2021-01-15",
            end_date="2021-01-16",
            interval="5m",
            include_volume=True,
            data=data,
            limit=1000
        )

        assert response["ticker"] == "VIC"
        assert response["interval"] == "5m"
        assert response["include_volume"] is True
        assert response["bar_count"] == 1
        assert response["data"] == data

    def test_format_statistics_response(self):
        """Test statistics response formatting."""
        response = format_statistics_response(
            ticker="HPG",
            start_date="2021-01-01",
            end_date="2021-12-31",
            query_type="tick",
            estimated_rows=1000000,
            estimated_size_mb=123.456,
            date_range_days=365,
            data_available=True
        )

        assert response["ticker"] == "HPG"
        assert response["query_type"] == "tick"
        assert response["estimated_rows"] == 1000000
        assert response["estimated_size_mb"] == 123.46  # Rounded
        assert response["date_range_days"] == 365
        assert response["data_available"] is True


class TestValidation:
    """Tests for validation functions."""

    def test_validate_ticker_valid(self):
        """Test valid ticker validation."""
        assert validate_ticker("FPT") == "FPT"
        assert validate_ticker("fpt") == "FPT"
        assert validate_ticker("  FPT  ") == "FPT"
        assert validate_ticker("VN30F1M") == "VN30F1M"

    def test_validate_ticker_invalid(self):
        """Test invalid ticker validation."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_ticker("")

        with pytest.raises(ValueError, match="invalid characters"):
            validate_ticker("FPT-ABC")

        with pytest.raises(ValueError, match="invalid characters"):
            validate_ticker("FPT.VN")

        with pytest.raises(ValueError, match="length must be between"):
            validate_ticker("VERYLONGTICKER")

    def test_validate_interval_valid(self):
        """Test valid interval validation."""
        assert validate_interval("1m") == "1m"
        assert validate_interval("5m") == "5m"
        assert validate_interval("1h") == "1h"
        assert validate_interval("1d") == "1d"

    def test_validate_interval_invalid(self):
        """Test invalid interval validation."""
        with pytest.raises(ValueError, match="Invalid interval"):
            validate_interval("2m")

        with pytest.raises(ValueError, match="Invalid interval"):
            validate_interval("invalid")


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_truncate_list(self):
        """Test list truncation."""
        data = [1, 2, 3, 4, 5]

        assert truncate_list(data, 3) == [1, 2, 3]
        assert truncate_list(data, 10) == [1, 2, 3, 4, 5]
        assert truncate_list(data, 0) == []
        assert truncate_list(data, -1) == []

    def test_get_sample_tickers(self):
        """Test getting sample tickers."""
        tickers = get_sample_tickers(5)
        assert len(tickers) == 5
        assert "FPT" in tickers
        assert "VIC" in tickers

        tickers_all = get_sample_tickers(20)
        assert len(tickers_all) == 20
