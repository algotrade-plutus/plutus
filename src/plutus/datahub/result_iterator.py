"""Lazy iterator for query results with memory-efficient streaming."""

import warnings
from typing import Iterator, List, Dict, Any, Optional
import duckdb
import pandas as pd


class ResultIterator:
    """Lazy iterator over DuckDB query results.

    Supports three modes:
    1. Lazy iteration (one row at a time) - memory efficient
    2. Batch iteration (chunks of N rows) - good for bulk processing
    3. Full materialization (.to_dataframe()) - convenient but memory-heavy

    Example:
        >>> # Lazy iteration
        >>> for row in results:
        ...     print(row['datetime'], row['price'])
        >>>
        >>> # Batch processing
        >>> for batch in results.batches(size=10000):
        ...     process_batch(batch)
        >>>
        >>> # Full materialization
        >>> df = results.to_dataframe()
    """

    def __init__(self, query: str, connection: duckdb.DuckDBPyConnection):
        """Initialize result iterator.

        Args:
            query: SQL query string
            connection: DuckDB connection object
        """
        self._query = query
        self._conn = connection
        self._cursor = None
        self._column_names = None
        self._materialized = False
        self._count = None

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        """Start lazy iteration over results.

        Yields:
            Dictionary mapping column names to values

        Example:
            >>> for row in results:
            ...     print(f"{row['datetime']}: {row['price']}")
        """
        # Always create a fresh cursor for new iteration
        # This allows the iterator to be reused (e.g., list() then iterate again)
        self._cursor = self._conn.execute(self._query)
        self._column_names = [desc[0] for desc in self._cursor.description]
        self._materialized = False  # Reset materialization flag

        return self

    def __next__(self) -> Dict[str, Any]:
        """Fetch next row.

        Returns:
            Dictionary with column names as keys

        Raises:
            StopIteration: When no more rows available
        """
        if self._cursor is None:
            # Initialize cursor if __iter__() wasn't called
            self._cursor = self._conn.execute(self._query)
            self._column_names = [desc[0] for desc in self._cursor.description]

        row = self._cursor.fetchone()
        if row is None:
            raise StopIteration

        return self._row_to_dict(row)

    def batches(self, size: int = 10000) -> Iterator[List[Dict[str, Any]]]:
        """Iterate in batches (memory efficient).

        Useful for processing large result sets without loading everything
        into memory at once.

        Args:
            size: Number of rows per batch (default: 10,000)

        Yields:
            List of row dictionaries

        Example:
            >>> for batch in results.batches(size=5000):
            ...     df_batch = pd.DataFrame(batch)
            ...     save_to_database(df_batch)
        """
        cursor = self._conn.execute(self._query)
        self._column_names = [desc[0] for desc in cursor.description]

        while True:
            rows = cursor.fetchmany(size)
            if not rows:
                break

            batch = [self._row_to_dict(row) for row in rows]
            yield batch

    def to_dataframe(self, warn_threshold: int = 1_000_000) -> pd.DataFrame:
        """Materialize full result as Pandas DataFrame.

        Loads all results into memory. Shows warning if result set is large.

        Args:
            warn_threshold: Show warning if row count exceeds this (default: 1M)

        Returns:
            Pandas DataFrame with all query results

        Warns:
            UserWarning: If result set is very large

        Example:
            >>> df = results.to_dataframe()
            >>> df.to_csv('output.csv', index=False)
        """
        # Estimate size first
        if not self._materialized:
            row_count = self._get_count()

            # Warn if large
            if row_count > warn_threshold:
                est_mb = row_count * 80 / 1024 / 1024  # Rough estimate: 80 bytes/row
                warnings.warn(
                    f"Large result set: {row_count:,} rows (estimated {est_mb:.0f}MB). "
                    f"Consider using batches() for memory-efficient processing.",
                    UserWarning,
                    stacklevel=2
                )

        # Materialize using DuckDB's built-in pandas conversion
        df = self._conn.execute(self._query).df()
        self._materialized = True
        return df

    def _row_to_dict(self, row: tuple) -> Dict[str, Any]:
        """Convert DuckDB row tuple to dictionary.

        Args:
            row: Tuple of values from DuckDB

        Returns:
            Dictionary mapping column names to values
        """
        if self._column_names is None:
            raise RuntimeError("Column names not initialized")

        return dict(zip(self._column_names, row))

    def _get_count(self) -> int:
        """Get total row count (executes COUNT(*) query).

        Returns:
            Number of rows in result set
        """
        if self._count is None:
            count_query = f"SELECT COUNT(*) FROM ({self._query}) AS _count_subquery"
            self._count = self._conn.execute(count_query).fetchone()[0]
        return self._count

    def count(self) -> int:
        """Get result count by executing a COUNT(*) query.

        Note: This executes a separate COUNT(*) query and should be used sparingly.
        For iterating through results, use the iterator interface directly.

        Returns:
            Number of rows in result set

        Example:
            >>> results = query.fetch(...)
            >>> print(f"Found {results.count()} records")
        """
        return self._get_count()

    def __repr__(self) -> str:
        """String representation."""
        if self._count is not None:
            return f"ResultIterator({self._count:,} rows)"
        return "ResultIterator(not materialized)"
