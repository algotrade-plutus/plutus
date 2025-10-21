"""MCP Resources for Plutus DataHub.

Resources provide read-only metadata about the dataset to help LLMs understand
what data is available. Each resource has a URI and returns structured data.
"""

from typing import Any, Dict
import logging

from plutus.mcp.config import MCPServerConfig

logger = logging.getLogger(__name__)


def register_resources(mcp, config: MCPServerConfig) -> None:
    """Register all MCP resources with the server.

    Args:
        mcp: FastMCP server instance
        config: MCP server configuration
    """

    @mcp.resource("dataset://metadata")
    def dataset_metadata() -> Dict[str, Any]:
        """General dataset information.

        Provides overview of the Vietnamese market data dataset including size,
        date range, and data type classifications.

        URI: dataset://metadata

        Returns:
            Dictionary containing:
            - name: Dataset name
            - description: Dataset description
            - size_gb: Dataset size in gigabytes
            - date_range: Start and end dates
            - data_types: Count of different data type files
            - total_files: Total number of CSV files

        Example:
            >>> # Access via MCP client
            >>> metadata = read_resource("dataset://metadata")
            >>> print(f"Dataset: {metadata['name']}")
            >>> print(f"Date range: {metadata['date_range']['start']} to {metadata['date_range']['end']}")
        """
        return {
            "name": "Hermes Market Data Pre-2023",
            "description": "Vietnamese stock market data (2000-2022) from HOSE, HNX, and UPCOM exchanges",
            "size_gb": 21,
            "date_range": {
                "start": "2000-01-01",
                "end": "2022-12-31"
            },
            "data_types": {
                "intraday": 17,
                "aggregation": 21,
                "metadata": 3
            },
            "total_files": 41,
            "exchanges": ["HOSE", "HNX", "UPCOM"],
            "note": "Data includes equities, ETFs, covered warrants, and derivatives"
        }

    @mcp.resource("dataset://tickers")
    def dataset_tickers() -> Dict[str, Any]:
        """List of all available ticker symbols.

        Provides comprehensive list of ticker symbols available in the dataset,
        including exchange information and instrument types.

        URI: dataset://tickers

        Returns:
            Dictionary containing:
            - tickers: List of ticker dictionaries
              Each ticker has: symbol, exchange, type (optional)
            - total_count: Total number of tickers
            - exchanges: List of exchanges
            - note: Additional information

        Example:
            >>> # Access via MCP client
            >>> tickers_data = read_resource("dataset://tickers")
            >>> print(f"Total tickers: {tickers_data['total_count']}")
            >>> fpt = [t for t in tickers_data['tickers'] if t['symbol'] == 'FPT'][0]
            >>> print(f"FPT is on {fpt['exchange']} exchange")
        """
        # Common Vietnamese stock tickers (sample)
        # In production, this would be dynamically loaded from the dataset
        sample_tickers = [
            {"symbol": "FPT", "exchange": "HOSE", "type": "stock"},
            {"symbol": "VIC", "exchange": "HOSE", "type": "stock"},
            {"symbol": "HPG", "exchange": "HOSE", "type": "stock"},
            {"symbol": "VHM", "exchange": "HOSE", "type": "stock"},
            {"symbol": "VNM", "exchange": "HOSE", "type": "stock"},
            {"symbol": "VCB", "exchange": "HOSE", "type": "stock"},
            {"symbol": "TCB", "exchange": "HOSE", "type": "stock"},
            {"symbol": "MBB", "exchange": "HOSE", "type": "stock"},
            {"symbol": "BID", "exchange": "HOSE", "type": "stock"},
            {"symbol": "CTG", "exchange": "HOSE", "type": "stock"},
            {"symbol": "GAS", "exchange": "HOSE", "type": "stock"},
            {"symbol": "MSN", "exchange": "HOSE", "type": "stock"},
            {"symbol": "PLX", "exchange": "HOSE", "type": "stock"},
            {"symbol": "VPB", "exchange": "HOSE", "type": "stock"},
            {"symbol": "POW", "exchange": "HOSE", "type": "stock"},
            {"symbol": "VRE", "exchange": "HOSE", "type": "stock"},
            {"symbol": "NVL", "exchange": "HOSE", "type": "stock"},
            {"symbol": "HDB", "exchange": "HOSE", "type": "stock"},
            {"symbol": "STB", "exchange": "HOSE", "type": "stock"},
            {"symbol": "SSI", "exchange": "HOSE", "type": "stock"},
            {"symbol": "SAB", "exchange": "HOSE", "type": "stock"},
            {"symbol": "VJC", "exchange": "HOSE", "type": "stock"},
            {"symbol": "MWG", "exchange": "HOSE", "type": "stock"},
            {"symbol": "BCM", "exchange": "HOSE", "type": "stock"},
            {"symbol": "GMD", "exchange": "HOSE", "type": "stock"},
            {"symbol": "ACB", "exchange": "HNX", "type": "stock"},
            {"symbol": "SHB", "exchange": "HNX", "type": "stock"},
            {"symbol": "PVS", "exchange": "HNX", "type": "stock"},
            {"symbol": "VN30F1M", "exchange": "HOSE", "type": "futures"},
            {"symbol": "VN30F2M", "exchange": "HOSE", "type": "futures"}
        ]

        return {
            "tickers": sample_tickers,
            "total_count": len(sample_tickers),
            "exchanges": ["HOSE", "HNX", "UPCOM"],
            "note": "This is a sample list of common tickers. Full dataset contains ~1850 ticker symbols. Use ticker validation in queries to check availability."
        }

    @mcp.resource("dataset://fields")
    def dataset_fields() -> Dict[str, Any]:
        """Available data fields and their descriptions.

        Provides detailed information about all data fields available for queries,
        organized by category (trade data, order book, foreign flows, etc.).

        URI: dataset://fields

        Returns:
            Dictionary containing:
            - intraday_fields: List of tick-level field definitions
            - aggregation_fields: List of daily aggregation field definitions
            - categories: Field categories with descriptions
            - note: Usage instructions

        Example:
            >>> # Access via MCP client
            >>> fields_data = read_resource("dataset://fields")
            >>> orderbook_fields = [
            ...     f for f in fields_data['intraday_fields']
            ...     if f['category'] == 'order_book'
            ... ]
            >>> print(f"Order book fields: {[f['name'] for f in orderbook_fields]}")
        """
        intraday_fields = [
            {
                "name": "matched_price",
                "description": "Matched trade price",
                "category": "trade",
                "unit": "VND",
                "depth_levels": None,
                "nullable": False
            },
            {
                "name": "matched_volume",
                "description": "Matched trade volume",
                "category": "trade",
                "unit": "shares",
                "depth_levels": None,
                "nullable": False
            },
            {
                "name": "bid_price",
                "description": "Bid order book price (10 levels)",
                "category": "order_book",
                "unit": "VND",
                "depth_levels": list(range(1, 11)),
                "nullable": True
            },
            {
                "name": "ask_price",
                "description": "Ask order book price (10 levels)",
                "category": "order_book",
                "unit": "VND",
                "depth_levels": list(range(1, 11)),
                "nullable": True
            },
            {
                "name": "bid_size",
                "description": "Bid order book size/quantity (10 levels)",
                "category": "order_book",
                "unit": "shares",
                "depth_levels": list(range(1, 11)),
                "nullable": True
            },
            {
                "name": "ask_size",
                "description": "Ask order book size/quantity (10 levels)",
                "category": "order_book",
                "unit": "shares",
                "depth_levels": list(range(1, 11)),
                "nullable": True
            },
            {
                "name": "open_price",
                "description": "Opening price",
                "category": "daily_snapshot",
                "unit": "VND",
                "depth_levels": None,
                "nullable": False
            },
            {
                "name": "close_price",
                "description": "Closing price",
                "category": "daily_snapshot",
                "unit": "VND",
                "depth_levels": None,
                "nullable": False
            },
            {
                "name": "high_price",
                "description": "Highest price of the day",
                "category": "daily_snapshot",
                "unit": "VND",
                "depth_levels": None,
                "nullable": False
            },
            {
                "name": "low_price",
                "description": "Lowest price of the day",
                "category": "daily_snapshot",
                "unit": "VND",
                "depth_levels": None,
                "nullable": False
            },
            {
                "name": "foreign_buy_volume",
                "description": "Foreign investor buy volume",
                "category": "foreign_flow",
                "unit": "shares",
                "depth_levels": None,
                "nullable": True
            },
            {
                "name": "foreign_sell_volume",
                "description": "Foreign investor sell volume",
                "category": "foreign_flow",
                "unit": "shares",
                "depth_levels": None,
                "nullable": True
            },
            {
                "name": "foreign_buy_value",
                "description": "Foreign investor buy value",
                "category": "foreign_flow",
                "unit": "VND",
                "depth_levels": None,
                "nullable": True
            },
            {
                "name": "foreign_sell_value",
                "description": "Foreign investor sell value",
                "category": "foreign_flow",
                "unit": "VND",
                "depth_levels": None,
                "nullable": True
            }
        ]

        aggregation_fields = [
            {
                "name": "daily_volume",
                "description": "Total daily trading volume",
                "category": "daily_stats",
                "unit": "shares"
            },
            {
                "name": "daily_value",
                "description": "Total daily trading value",
                "category": "daily_stats",
                "unit": "VND"
            },
            {
                "name": "reference_price",
                "description": "Daily reference price (used for floor/ceiling calculation)",
                "category": "daily_stats",
                "unit": "VND"
            },
            {
                "name": "ceiling_price",
                "description": "Daily ceiling price (max allowed price)",
                "category": "daily_stats",
                "unit": "VND"
            },
            {
                "name": "floor_price",
                "description": "Daily floor price (min allowed price)",
                "category": "daily_stats",
                "unit": "VND"
            },
            {
                "name": "settlement_price",
                "description": "Settlement price (derivatives contracts)",
                "category": "derivatives",
                "unit": "VND"
            },
            {
                "name": "open_interest",
                "description": "Open interest (derivatives contracts)",
                "category": "derivatives",
                "unit": "contracts"
            }
        ]

        categories = {
            "trade": "Matched trade data (price and volume)",
            "order_book": "Order book depth (bid/ask prices and sizes)",
            "foreign_flow": "Foreign investor activity",
            "daily_snapshot": "Daily OHLC snapshots",
            "daily_stats": "Daily aggregated statistics",
            "derivatives": "Derivatives-specific fields (futures, options)"
        }

        return {
            "intraday_fields": intraday_fields,
            "aggregation_fields": aggregation_fields,
            "categories": categories,
            "note": "For order book fields with depth_levels, append _1 to _10 to field name (e.g., bid_price_1, bid_price_2, ...bid_price_10)"
        }

    @mcp.resource("dataset://intervals")
    def dataset_intervals() -> Dict[str, Any]:
        """Supported OHLC time intervals.

        Provides list of all supported time intervals for OHLC bar generation,
        with descriptions and typical use cases.

        URI: dataset://intervals

        Returns:
            Dictionary containing:
            - intervals: List of interval definitions
            - note: Usage instructions

        Example:
            >>> # Access via MCP client
            >>> intervals_data = read_resource("dataset://intervals")
            >>> for interval in intervals_data['intervals']:
            ...     print(f"{interval['code']}: {interval['description']}")
        """
        intervals = [
            {
                "code": "1m",
                "description": "1-minute bars",
                "bars_per_day": 390,
                "use_case": "High-frequency intraday analysis, scalping strategies"
            },
            {
                "code": "5m",
                "description": "5-minute bars",
                "bars_per_day": 78,
                "use_case": "Intraday trend analysis, day trading"
            },
            {
                "code": "15m",
                "description": "15-minute bars",
                "bars_per_day": 26,
                "use_case": "Intraday swing trading, pattern recognition"
            },
            {
                "code": "30m",
                "description": "30-minute bars",
                "bars_per_day": 13,
                "use_case": "Medium-term intraday analysis"
            },
            {
                "code": "1h",
                "description": "1-hour bars",
                "bars_per_day": 7,
                "use_case": "Intraday to daily transition analysis"
            },
            {
                "code": "4h",
                "description": "4-hour bars",
                "bars_per_day": 2,
                "use_case": "Multi-day trend analysis"
            },
            {
                "code": "1d",
                "description": "1-day bars",
                "bars_per_day": 1,
                "use_case": "Daily analysis, swing trading, position trading"
            }
        ]

        return {
            "intervals": intervals,
            "trading_hours": {
                "morning_session": "09:00 - 11:30",
                "afternoon_session": "13:00 - 15:00",
                "total_minutes": 270
            },
            "note": "Vietnamese stock market trades 6.5 hours per day (390 minutes). Bars per day are approximate and exclude lunch break."
        }
