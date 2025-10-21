"""MCP Server Configuration.

Configuration management for the Plutus MCP server, including server metadata,
data paths, and operational parameters.
"""

import os
from dataclasses import dataclass
from typing import Optional

from plutus.datahub import DataHubConfig


@dataclass
class MCPServerConfig:
    """Configuration for MCP server.

    Attributes:
        name: Server name (shown to MCP clients)
        version: Server version
        description: Server description
        data_root: Root directory for market data (inherits from DataHubConfig)
        max_row_limit: Maximum number of rows per query
        default_row_limit: Default row limit if not specified
        query_timeout: Query timeout in seconds
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """

    name: str = "plutus-datahub"
    version: str = "1.0.0"
    description: str = "Vietnamese market data access via Model Context Protocol"
    data_root: Optional[str] = None
    max_row_limit: int = 10000
    default_row_limit: int = 1000
    query_timeout: int = 60
    log_level: str = "INFO"

    def __post_init__(self):
        """Initialize configuration with environment variables."""
        # Override with environment variables if present
        self.data_root = os.getenv("HERMES_DATA_ROOT", self.data_root)
        self.log_level = os.getenv("MCP_LOG_LEVEL", self.log_level)

        # Validate limits
        if self.max_row_limit < self.default_row_limit:
            raise ValueError(
                f"max_row_limit ({self.max_row_limit}) must be >= "
                f"default_row_limit ({self.default_row_limit})"
            )

    def get_datahub_config(self) -> DataHubConfig:
        """Get DataHub configuration.

        Returns:
            DataHubConfig instance with same data_root
        """
        return DataHubConfig(data_root=self.data_root)

    def validate_row_limit(self, limit: int) -> int:
        """Validate and normalize row limit.

        Args:
            limit: Requested row limit

        Returns:
            Validated row limit (clamped to max)

        Raises:
            ValueError: If limit is negative
        """
        if limit < 0:
            raise ValueError(f"Row limit must be non-negative, got {limit}")

        if limit == 0:
            return self.default_row_limit

        return min(limit, self.max_row_limit)


# Global configuration instance (can be overridden)
_config: Optional[MCPServerConfig] = None


def get_config() -> MCPServerConfig:
    """Get global MCP server configuration.

    Returns:
        MCPServerConfig instance
    """
    global _config
    if _config is None:
        _config = MCPServerConfig()
    return _config


def set_config(config: MCPServerConfig) -> None:
    """Set global MCP server configuration.

    Args:
        config: New configuration instance
    """
    global _config
    _config = config
