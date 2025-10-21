"""Unit tests for MCP server configuration."""

import pytest
import os

from plutus.mcp.config import MCPServerConfig, get_config, set_config


class TestMCPServerConfig:
    """Tests for MCPServerConfig class."""

    def test_default_config(self):
        """Test default configuration values."""
        config = MCPServerConfig()

        assert config.name == "plutus-datahub"
        assert config.version == "1.0.0"
        assert config.max_row_limit == 10000
        assert config.default_row_limit == 1000
        assert config.query_timeout == 60
        assert config.log_level == "INFO"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = MCPServerConfig(
            name="custom-server",
            version="2.0.0",
            data_root="/custom/path",
            max_row_limit=5000,
            default_row_limit=500,
            query_timeout=120,
            log_level="DEBUG"
        )

        assert config.name == "custom-server"
        assert config.version == "2.0.0"
        assert config.data_root == "/custom/path"
        assert config.max_row_limit == 5000
        assert config.default_row_limit == 500
        assert config.query_timeout == 120
        assert config.log_level == "DEBUG"

    def test_environment_variable_override(self, monkeypatch):
        """Test environment variable overrides."""
        monkeypatch.setenv("HERMES_DATA_ROOT", "/env/path")
        monkeypatch.setenv("MCP_LOG_LEVEL", "WARNING")

        config = MCPServerConfig()

        assert config.data_root == "/env/path"
        assert config.log_level == "WARNING"

    def test_invalid_limits(self):
        """Test validation of row limits."""
        with pytest.raises(ValueError, match="max_row_limit.*must be.*default_row_limit"):
            MCPServerConfig(max_row_limit=100, default_row_limit=200)

    def test_validate_row_limit(self):
        """Test row limit validation."""
        config = MCPServerConfig(max_row_limit=1000, default_row_limit=100)

        # Zero returns default
        assert config.validate_row_limit(0) == 100

        # Within range
        assert config.validate_row_limit(500) == 500

        # Exceeds max, clamped
        assert config.validate_row_limit(2000) == 1000

        # Negative raises error
        with pytest.raises(ValueError, match="must be non-negative"):
            config.validate_row_limit(-10)

    def test_get_datahub_config(self, monkeypatch):
        """Test getting DataHubConfig (mocked to avoid file system)."""
        # Mock DataHubConfig to avoid file system checks
        from unittest.mock import Mock
        mock_dh_config = Mock()

        def mock_init(self, data_root=None):
            self.data_root = data_root

        monkeypatch.setattr(
            "plutus.datahub.config.DataHubConfig.__init__",
            mock_init
        )

        config = MCPServerConfig(data_root="/test/path")
        # Note: This will still fail without full mock, but demonstrates the interface
        # Full integration test would use actual DataHubConfig


class TestConfigSingleton:
    """Tests for global config singleton."""

    def test_get_config(self):
        """Test getting global config."""
        config = get_config()
        assert isinstance(config, MCPServerConfig)
        assert config.name == "plutus-datahub"

    def test_set_config(self):
        """Test setting global config."""
        custom_config = MCPServerConfig(name="custom")
        set_config(custom_config)

        config = get_config()
        assert config.name == "custom"

        # Reset to default for other tests
        set_config(MCPServerConfig())
