"""Unit tests for MCP prompts."""

import pytest
from unittest.mock import Mock

from plutus.mcp.prompts import register_prompts


class TestPromptsRegistration:
    """Tests for prompts registration."""

    def test_register_prompts(self):
        """Test that prompts are registered correctly."""
        mock_mcp = Mock()
        mock_mcp.prompt = Mock(return_value=lambda f: f)

        register_prompts(mock_mcp)

        # Verify prompt decorator was called 5 times (5 prompts)
        assert mock_mcp.prompt.call_count == 5


class TestAnalyzeDailyTrends:
    """Tests for analyze_daily_trends prompt."""

    def test_analyze_daily_trends_prompt(self):
        """Test analyze_daily_trends prompt template."""
        # Create mock MCP and register prompts
        mock_mcp = Mock()
        prompts_dict = {}

        def prompt_decorator():
            def wrapper(func):
                prompts_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.prompt = prompt_decorator
        register_prompts(mock_mcp)

        # Call the prompt
        analyze_daily_trends = prompts_dict['analyze_daily_trends']
        result = analyze_daily_trends(
            ticker="FPT",
            start_date="2021-01-01",
            end_date="2021-12-31"
        )

        # Verify template substitution
        assert isinstance(result, str)
        assert "FPT" in result
        assert "2021-01-01" in result
        assert "2021-12-31" in result

        # Verify key instructions are present
        assert "daily OHLC" in result.lower() or "ohlc" in result.lower()
        assert "query_ohlc_data" in result
        assert "trend" in result.lower()
        assert "volatility" in result.lower()


class TestIntradayVolumeAnalysis:
    """Tests for intraday_volume_analysis prompt."""

    def test_intraday_volume_analysis_prompt(self):
        """Test intraday_volume_analysis prompt template."""
        # Create mock MCP and register prompts
        mock_mcp = Mock()
        prompts_dict = {}

        def prompt_decorator():
            def wrapper(func):
                prompts_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.prompt = prompt_decorator
        register_prompts(mock_mcp)

        # Call the prompt
        intraday_volume_analysis = prompts_dict['intraday_volume_analysis']
        result = intraday_volume_analysis(
            ticker="VIC",
            date="2021-01-15"
        )

        # Verify template substitution
        assert isinstance(result, str)
        assert "VIC" in result
        assert "2021-01-15" in result

        # Verify key instructions are present
        assert "volume" in result.lower()
        assert "intraday" in result.lower()
        assert "query_tick_data" in result or "query_ohlc_data" in result


class TestCompareTickers:
    """Tests for compare_tickers prompt."""

    def test_compare_tickers_prompt(self):
        """Test compare_tickers prompt template."""
        # Create mock MCP and register prompts
        mock_mcp = Mock()
        prompts_dict = {}

        def prompt_decorator():
            def wrapper(func):
                prompts_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.prompt = prompt_decorator
        register_prompts(mock_mcp)

        # Call the prompt
        compare_tickers = prompts_dict['compare_tickers']
        result = compare_tickers(
            ticker1="HPG",
            ticker2="VIC",
            start_date="2021-01-01",
            end_date="2021-12-31"
        )

        # Verify template substitution
        assert isinstance(result, str)
        assert "HPG" in result
        assert "VIC" in result
        assert "2021-01-01" in result
        assert "2021-12-31" in result

        # Verify key instructions are present
        assert "compare" in result.lower()
        assert "return" in result.lower()
        assert "correlation" in result.lower() or "sharpe" in result.lower()


class TestDetectPriceAnomalies:
    """Tests for detect_price_anomalies prompt."""

    def test_detect_price_anomalies_prompt(self):
        """Test detect_price_anomalies prompt template."""
        # Create mock MCP and register prompts
        mock_mcp = Mock()
        prompts_dict = {}

        def prompt_decorator():
            def wrapper(func):
                prompts_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.prompt = prompt_decorator
        register_prompts(mock_mcp)

        # Call the prompt
        detect_price_anomalies = prompts_dict['detect_price_anomalies']
        result = detect_price_anomalies(
            ticker="FPT",
            start_date="2021-01-01",
            end_date="2021-12-31"
        )

        # Verify template substitution
        assert isinstance(result, str)
        assert "FPT" in result
        assert "2021-01-01" in result
        assert "2021-12-31" in result

        # Verify key instructions are present
        assert "anomal" in result.lower()
        assert "volume" in result.lower()
        assert "outlier" in result.lower() or "unusual" in result.lower()


class TestCalculateTechnicalIndicators:
    """Tests for calculate_technical_indicators prompt."""

    def test_calculate_technical_indicators_prompt(self):
        """Test calculate_technical_indicators prompt template."""
        # Create mock MCP and register prompts
        mock_mcp = Mock()
        prompts_dict = {}

        def prompt_decorator():
            def wrapper(func):
                prompts_dict[func.__name__] = func
                return func
            return wrapper

        mock_mcp.prompt = prompt_decorator
        register_prompts(mock_mcp)

        # Call the prompt
        calculate_technical_indicators = prompts_dict['calculate_technical_indicators']
        result = calculate_technical_indicators(
            ticker="FPT",
            start_date="2021-01-01",
            end_date="2021-12-31"
        )

        # Verify template substitution
        assert isinstance(result, str)
        assert "FPT" in result
        assert "2021-01-01" in result
        assert "2021-12-31" in result

        # Verify key technical indicators are mentioned
        assert "RSI" in result or "rsi" in result.lower()
        assert "MACD" in result or "macd" in result.lower()
        assert "moving average" in result.lower()
        assert "Bollinger" in result or "bollinger" in result.lower()
