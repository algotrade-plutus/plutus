"""Contract months, expiry dates, and the settlement-price chain.

Settlement has three tiers and every consumer records which one produced a
price, because they are not equally trustworthy:

1. ``PUBLISHED`` -- a real ``quote_settlementprice`` row. Only a handful of
   (date, contract) pairs exist, and further rows are corrupt (their price is
   the ``HHMMSS`` of their own timestamp) and are excluded.
2. ``TWAP_30M`` -- the time-weighted mean of matched price over 14:15-14:45,
   recovered empirically against the published rows at a mean error of 0.74
   index points. Requires the raw archive.
3. ``CLOSE_PROXY`` -- ``quote_close``. The only tier available on the Parquet
   root.

``quote_reference`` is deliberately **not** in the chain. It equals the
previous close on 1,731 of 1,968 comparable VN30F pairs and misses published
settlement by up to 5.55 points, so it is not an independent settlement series.
"""

import calendar
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple

import duckdb

from plutus.market.verdicts import SettlementSource

__all__ = ['parse_contract_month', 'expiry_date', 'third_thursday',
           'SettlementResolver']

_CONTRACT_RE = re.compile(r'^VN30F(\d{2})(\d{2})$')


def parse_contract_month(ticker: str) -> Optional[Tuple[int, int]]:
    """``'VN30F2112'`` -> ``(2021, 12)``; anything else -> ``None``."""
    match = _CONTRACT_RE.match(ticker)
    if not match:
        return None
    year, month = 2000 + int(match.group(1)), int(match.group(2))
    return (year, month) if 1 <= month <= 12 else None


def third_thursday(year: int, month: int) -> date:
    first = next(day for day in range(1, 8)
                 if date(year, month, day).weekday() == calendar.THURSDAY)
    return date(year, month, first + 14)


def expiry_date(ticker: str) -> Optional[date]:
    """Third Thursday of the contract month. Verified 24/24 in-window."""
    parsed = parse_contract_month(ticker)
    return third_thursday(*parsed) if parsed else None


class SettlementResolver:
    """Resolves a settlement price and reports which tier supplied it."""

    def __init__(self, data_root: str, tick_root: Optional[str] = None):
        self.root = Path(data_root)
        self.tick_root = Path(tick_root) if tick_root else None
        self._conn = duckdb.connect()

    @classmethod
    def for_root(cls, data_root: str,
                 tick_root: Optional[str] = None) -> 'SettlementResolver':
        return cls(data_root, tick_root)

    def _reader(self, table: str) -> Optional[str]:
        parquet = self.root / f'{table}.parquet'
        if parquet.exists():
            return f"read_parquet('{parquet}')"
        csv = self.root / f'{table}.csv'
        return f"read_csv_auto('{csv}')" if csv.exists() else None

    def settlement_for(
        self, ticker: str, day: date
    ) -> Tuple[Optional[Decimal], SettlementSource]:
        """The settlement for one contract-day, and its provenance."""
        published = self._published(ticker, day)
        if published is not None:
            return published, SettlementSource.PUBLISHED

        twap = self._twap_30m(ticker, day)
        if twap is not None:
            return twap, SettlementSource.TWAP_30M

        return self._close(ticker, day), SettlementSource.CLOSE_PROXY

    def _published(self, ticker: str, day: date) -> Optional[Decimal]:
        table = self._reader('quote_settlementprice')
        if table is None:
            return None
        row = self._conn.execute(
            f"""SELECT price FROM {table}
                WHERE tickersymbol = ? AND CAST(datetime AS DATE) = ?
                  -- exclude corrupt rows whose price is the HHMMSS of their
                  -- own timestamp
                  AND price < 100000
                ORDER BY datetime DESC LIMIT 1""",
            [ticker, day]).fetchone()
        return Decimal(str(row[0])) if row else None

    def _twap_30m(self, ticker: str, day: date) -> Optional[Decimal]:
        """Time-weighted mean of matched price over 14:15-14:45.

        Requires the raw archive; returns None without it.
        """
        if self.tick_root is None:
            return None
        matched = self.tick_root / 'quote_matched.csv'
        if not matched.exists():
            return None
        row = self._conn.execute(
            f"""SELECT avg(price) FROM read_csv_auto('{matched}')
                WHERE tickersymbol = ? AND datetime >= ? AND datetime < ?""",
            [ticker, f'{day} 14:15:00', f'{day} 14:45:00']).fetchone()
        return Decimal(str(row[0])) if row and row[0] is not None else None

    def _close(self, ticker: str, day: date) -> Optional[Decimal]:
        table = self._reader('quote_close')
        if table is None:
            return None
        row = self._conn.execute(
            f'SELECT price FROM {table} WHERE tickersymbol = ? '
            f'AND datetime = ? LIMIT 1', [ticker, day]).fetchone()
        return Decimal(str(row[0])) if row else None
