"""DataHub configuration and dataset discovery."""

import os
import configparser
from pathlib import Path
from typing import Dict, Optional


class DataHubConfig:
    """Configuration for market data access.

    Manages dataset location, file mappings, and schema information.
    Automatically discovers dataset location using priority order:
    1. Explicit data_root parameter
    2. PLUTUS_DATA_ROOT environment variable
    3. config.cfg file in project root
    4. Error if not found

    Attributes:
        data_root: Path to dataset root directory
        file_mappings: Dictionary mapping field names to CSV filenames
        prefer_parquet: Whether to use .parquet files if available

    Example:
        >>> # Auto-detect from env/config
        >>> config = DataHubConfig()
        >>> config.data_root
        Path('/path/to/hermes-offline-market-data-pre-2023')

        >>> # Explicit path
        >>> config = DataHubConfig(data_root='/custom/path')
        >>> config.get_file_path('matched_price')
        Path('/custom/path/quote_matched.csv')
    """

    # Config file location (project root)
    CONFIG_FILE = 'config.cfg'

    # Field name → CSV filename mappings
    FIELD_MAPPINGS = {
        # Price fields
        'matched_price': 'quote_matched.csv',
        'open_price': 'quote_open.csv',
        'high_price': 'quote_high.csv',
        'low_price': 'quote_low.csv',
        'close_price': 'quote_close.csv',
        'avg_price': 'quote_average.csv',
        'ref_price': 'quote_reference.csv',
        'ceiling_price': 'quote_ceil.csv',
        'floor_price': 'quote_floor.csv',
        'max_price': 'quote_max.csv',
        'min_price': 'quote_min.csv',
        'settlement_price': 'quote_settlementprice.csv',

        # Adjusted prices
        'adj_open': 'quote_adjopen.csv',
        'adj_high': 'quote_adjhigh.csv',
        'adj_low': 'quote_adjlow.csv',
        'adj_close': 'quote_adjclose.csv',

        # Volume fields
        'matched_volume': 'quote_matchedvolume.csv',
        'daily_volume': 'quote_dailyvolume.csv',
        'total_volume': 'quote_total.csv',

        # Order book (with depth parameter)
        'bid_price': 'quote_bidprice.csv',
        'ask_price': 'quote_askprice.csv',
        'bid_size': 'quote_bidsize.csv',
        'ask_size': 'quote_asksize.csv',

        # Foreign investment
        'foreign_buy_qty': 'quote_foreignbuy.csv',
        'foreign_sell_qty': 'quote_foreignsell.csv',
        'foreign_room': 'quote_foreignroom.csv',
        'daily_foreign_buy': 'quote_dailyforeignbuy.csv',
        'daily_foreign_sell': 'quote_dailyforeignsell.csv',
        'total_foreign_room': 'quote_totalforeignroom.csv',

        # Foreign value
        'foreign_buy_value': 'quote_foreignbuyvalue.csv',
        'foreign_sell_value': 'quote_foreignsellvalue.csv',

        # Futures
        'open_interest': 'quote_oi.csv',

        # Price changes
        'price_change': 'quote_change.csv',

        # VN30 aggregates
        'vn30_foreign_buy_value': 'quote_vn30foreignbuyvalue.csv',
        'vn30_foreign_sell_value': 'quote_vn30foreignsellvalue.csv',
        'vn30_foreign_trade_value': 'quote_vn30foreigntradevalue.csv',

        # Metadata
        'ticker_metadata': 'quote_ticker.csv',
        'vn30_constituents': 'quote_vn30.csv',
        'future_contracts': 'quote_futurecontractcode.csv',
    }

    def __init__(self, data_root: Optional[str] = None, prefer_parquet: bool = True):
        """Initialize DataHub configuration.

        Args:
            data_root: Path to dataset root directory (auto-detected if None)
            prefer_parquet: Use .parquet files if available (default: True)

        Raises:
            FileNotFoundError: If dataset cannot be found
        """
        self.data_root = self._resolve_data_root(data_root)
        self.prefer_parquet = prefer_parquet
        self.file_mappings = self.FIELD_MAPPINGS.copy()

        # Validate dataset
        self._validate_dataset()

    def _find_project_root(self) -> Optional[Path]:
        """Find project root by looking for config.cfg or pyproject.toml.

        Searches upward from current directory for project markers.

        Returns:
            Path to project root or None if not found
        """
        current = Path.cwd()

        # Check up to 5 levels up
        for _ in range(5):
            # Check for config file
            if (current / self.CONFIG_FILE).exists():
                return current
            # Check for pyproject.toml (another project marker)
            if (current / 'pyproject.toml').exists():
                return current
            # Check for src directory (common structure)
            if (current / 'src' / 'plutus' / 'datahub').exists():
                return current

            # Move up one level
            if current.parent == current:  # Reached root
                break
            current = current.parent

        return None

    def _read_config_file(self) -> Optional[str]:
        """Read PLUTUS_DATA_ROOT from config.cfg file.

        Returns:
            Path from config file or None if not found/not set
        """
        project_root = self._find_project_root()
        if not project_root:
            return None

        config_path = project_root / self.CONFIG_FILE
        if not config_path.exists():
            return None

        try:
            config = configparser.ConfigParser()
            config.read(config_path)

            # Read from [datahub] section
            if 'datahub' in config:
                data_root = config['datahub'].get('PLUTUS_DATA_ROOT', '').strip()
                if data_root and not data_root.startswith('#'):
                    return data_root
        except Exception:
            # Ignore parsing errors, just return None
            pass

        return None

    def _resolve_data_root(self, data_root: Optional[str]) -> Path:
        """Resolve dataset root directory.

        Priority order (highest to lowest):
        1. Explicit data_root parameter
        2. PLUTUS_DATA_ROOT environment variable
        3. config.cfg file in project root
        4. Error if not found

        Args:
            data_root: Explicitly provided path (optional)

        Returns:
            Path object to dataset root

        Raises:
            FileNotFoundError: If dataset not found
        """
        # 1. Check explicit parameter
        if data_root:
            path = Path(data_root).expanduser().resolve()
            if path.exists():
                return path
            raise FileNotFoundError(f"Dataset not found at: {path}")

        # 2. Check environment variable
        env_path = os.getenv('PLUTUS_DATA_ROOT')
        if env_path:
            path = Path(env_path).expanduser().resolve()
            if path.exists():
                return path
            raise FileNotFoundError(
                f"Dataset not found at PLUTUS_DATA_ROOT: {path}"
            )

        # 3. Check config file
        config_path = self._read_config_file()
        if config_path:
            path = Path(config_path).expanduser().resolve()
            if path.exists():
                return path
            raise FileNotFoundError(
                f"Dataset not found at path from config.cfg: {path}\n"
                f"Please check the PLUTUS_DATA_ROOT setting in config.cfg"
            )

        # 4. Not found - provide helpful error message
        raise FileNotFoundError(
            "Dataset location not configured.\n\n"
            "Please configure the dataset location using one of these methods:\n\n"
            "  1. Create config.cfg from template:\n"
            "     cp config.cfg.template config.cfg\n"
            "     Then edit config.cfg and set: PLUTUS_DATA_ROOT=/path/to/dataset\n\n"
            "  2. Set environment variable:\n"
            "     export PLUTUS_DATA_ROOT=/path/to/dataset\n\n"
            "  3. Pass as parameter:\n"
            "     DataHubConfig(data_root='/path/to/dataset')\n\n"
            "See SETUP.md for detailed instructions."
        )

    def _validate_dataset(self):
        """Validate that critical files exist in dataset.

        Accepts either .csv or .parquet format for critical files.
        This allows Parquet-only deployments (CSV files deleted after conversion).

        Raises:
            FileNotFoundError: If critical files missing
        """
        critical_files = [
            'quote_matched',      # Primary tick data
            'quote_ticker',       # Metadata
        ]

        missing = []
        for base_name in critical_files:
            csv_path = self.data_root / f'{base_name}.csv'
            parquet_path = self.data_root / f'{base_name}.parquet'

            # Accept either CSV or Parquet
            if not csv_path.exists() and not parquet_path.exists():
                missing.append(f'{base_name}.csv/.parquet')

        if missing:
            raise FileNotFoundError(
                f"Critical files missing from dataset at {self.data_root}:\n"
                f"  {', '.join(missing)}\n"
                f"Please verify dataset integrity.\n"
                f"Note: Either .csv or .parquet format is acceptable."
            )

    def get_file_path(self, field: str, prefer_parquet: Optional[bool] = None) -> Path:
        """Get full path to CSV/Parquet file for a field.

        Args:
            field: Field name (e.g., 'matched_price', 'bid_price_1')
            prefer_parquet: Override default parquet preference

        Returns:
            Path to data file (.parquet or .csv)

        Raises:
            ValueError: If field not recognized
            FileNotFoundError: If file doesn't exist

        Example:
            >>> config = DataHubConfig()
            >>> config.get_file_path('matched_price')
            Path('/path/to/dataset/quote_matched.csv')
        """
        # Remove depth suffix if present (e.g., bid_price_1 → bid_price)
        base_field = field
        if field.endswith(tuple(f'_{i}' for i in range(1, 11))):
            # Extract base field (e.g., 'bid_price_1' → 'bid_price')
            parts = field.rsplit('_', 1)
            if parts[1].isdigit():
                base_field = parts[0]

        # Get filename from mapping
        if base_field not in self.file_mappings:
            raise ValueError(
                f"Unknown field: {field}. "
                f"Available fields: {', '.join(sorted(self.file_mappings.keys()))}"
            )

        filename = self.file_mappings[base_field]
        use_parquet = prefer_parquet if prefer_parquet is not None else self.prefer_parquet

        csv_path = self.data_root / filename
        parquet_name = filename.replace('.csv', '.parquet')
        parquet_path = self.data_root / parquet_name

        # Try parquet first if preferred
        if use_parquet and parquet_path.exists():
            return parquet_path

        # Fall back to CSV
        if csv_path.exists():
            return csv_path

        # Neither format exists - provide helpful error
        raise FileNotFoundError(
            f"Data file not found for field '{field}':\n"
            f"  CSV:     {csv_path} (not found)\n"
            f"  Parquet: {parquet_path} (not found)\n"
            f"Expected mapping: {field} → {filename}\n\n"
            f"Hint: Check if dataset is complete or run Parquet conversion."
        )

    def get_available_fields(self) -> list:
        """Get list of all available data fields.

        Returns:
            Sorted list of field names

        Example:
            >>> config = DataHubConfig()
            >>> fields = config.get_available_fields()
            >>> 'matched_price' in fields
            True
        """
        return sorted(self.file_mappings.keys())

    def __repr__(self) -> str:
        """String representation."""
        return f"DataHubConfig(data_root='{self.data_root}')"
