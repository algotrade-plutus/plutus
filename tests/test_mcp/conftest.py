"""Pytest fixtures for MCP server tests."""

import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path

from plutus.mcp.config import MCPServerConfig


@pytest.fixture
def mock_config():
    """Mock MCP server configuration."""
    config = MCPServerConfig(
        name="test-server",
        version="0.0.1",
        data_root=None,  # Will be mocked
        max_row_limit=100,
        default_row_limit=10,
        query_timeout=30,
        log_level="INFO"
    )
    return config


@pytest.fixture
def mock_datahub_config(monkeypatch):
    """Mock DataHubConfig to avoid file system checks."""
    mock_dh_config = Mock()
    mock_dh_config.data_root = "/mock/data/root"
    mock_dh_config.get_file_path = Mock(return_value="/mock/file.csv")

    def mock_get_datahub_config(self):
        return mock_dh_config

    monkeypatch.setattr(
        "plutus.mcp.config.MCPServerConfig.get_datahub_config",
        mock_get_datahub_config
    )

    return mock_dh_config


@pytest.fixture
def sample_tick_data():
    """Sample tick data for testing."""
    return [
        {
            "datetime": "2021-01-15 09:00:00",
            "tickersymbol": "FPT",
            "matched_price": 85500
        },
        {
            "datetime": "2021-01-15 09:00:05",
            "tickersymbol": "FPT",
            "matched_price": 85600
        },
        {
            "datetime": "2021-01-15 09:00:10",
            "tickersymbol": "FPT",
            "matched_price": 85550
        }
    ]


@pytest.fixture
def sample_ohlc_data():
    """Sample OHLC data for testing."""
    return [
        {
            "bar_time": "2021-01-15 09:00:00",
            "tickersymbol": "FPT",
            "open": 85500,
            "high": 85700,
            "low": 85400,
            "close": 85600,
            "volume": 12500
        },
        {
            "bar_time": "2021-01-15 09:05:00",
            "tickersymbol": "FPT",
            "open": 85600,
            "high": 85800,
            "low": 85550,
            "close": 85750,
            "volume": 15200
        }
    ]


@pytest.fixture
def mock_query_historical(monkeypatch, sample_tick_data):
    """Mock query_historical function."""
    def mock_query(ticker_symbol, begin, end, type, **kwargs):
        # Return mock iterator
        if type == "tick":
            return iter(sample_tick_data)
        else:
            return iter([])

    monkeypatch.setattr(
        "plutus.mcp.tools.query_historical",
        mock_query
    )

    return mock_query
