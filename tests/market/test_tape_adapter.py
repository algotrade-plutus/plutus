"""The tape adapter: a reconstructed sized tape that reports what it cannot see.

Two tiers, like ``test_depth_adapter.py``.

The **synthetic** tier builds tiny ``matched``/``total`` Parquet tables in
``tmp_path`` and runs unconditionally, pinning every reconstruction rule: the
total-delta volume, the dropped out-of-session summary row, the forward-filled
price, the resting-side print condition, and -- the honesty rule that matters
most -- served-but-empty (a definite 0, the order simply did not trade through)
versus unserved (``None``, INDETERMINATE, the tape cannot say).

The **measured** tier runs against ``hermes-dev-extract`` and pins that the
reconstructed volume sums to ``dailyvolume`` for the two exported names.
"""

import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from plutus.core.order import Side
from plutus.market.adapters.tape import TapeSource

_EXTRACT_DEFAULT = Path('/Users/nadan/algotrade-research/dataset/hermes-dev-extract')


def _extract_root():
    env = os.environ.get('PLUTUS_DEPTH_ROOT')
    for root in ([Path(env)] if env else []) + [_EXTRACT_DEFAULT]:
        if (root / 'local_quote_total.parquet').exists():
            return root
    return None


EXTRACT = _extract_root()
requires_extract = pytest.mark.skipif(
    EXTRACT is None, reason='No tape extract found; set PLUTUS_DEPTH_ROOT.')

DAY = date(2022, 11, 9)


# --------------------------------------------------------------------------
# A synthetic extract, so the invariants hold with no corpus present
# --------------------------------------------------------------------------

def _write_tape(conn, path, rows, column):
    """One tape table: ``(datetime, tickersymbol, <column>)`` -- no depth."""
    if rows:
        values = ',\n'.join(
            f"(TIMESTAMP '{ts}', '{tk}', {value})" for ts, tk, value in rows)
        select = (f"SELECT * FROM (VALUES {values}) "
                  f"AS t(datetime, tickersymbol, {column})")
    else:
        typ = 'DECIMAL(20,6)' if column == 'price' else 'BIGINT'
        select = (f"SELECT NULL::TIMESTAMP AS datetime, "
                  f"NULL::VARCHAR AS tickersymbol, NULL::{typ} AS {column} "
                  f"WHERE FALSE")
    conn.execute(f"COPY ({select}) TO '{path}' (FORMAT PARQUET)")


@pytest.fixture
def toy(tmp_path):
    """A hand-built tape with the shapes the real one has.

    ``TOY`` on 2022-11-09, prefix ``local_quote``:

    * ``matched`` is a price change stream: 73.30 at 09:15, 73.40 at 09:16,
      73.90 at 09:17 -- sparser than the volume stream, forward-filled onto it.
    * ``total`` is cumulative, and carries a spurious ``00:00:00`` daily-summary
      row (10000) before the intraday series -- exactly FPT's real quirk. The
      intraday series is 500, 1200, 2000, so the per-event volumes are 500, 700,
      800 at prices 73.30, 73.40, 73.90.
    """
    conn = duckdb.connect()
    tk = 'TOY'
    _write_tape(conn, tmp_path / 'local_quote_matched.parquet', [
        ('2022-11-09 09:15:00', tk, '73.30'),
        ('2022-11-09 09:16:00', tk, '73.40'),
        ('2022-11-09 09:17:00', tk, '73.90'),
    ], 'price')
    _write_tape(conn, tmp_path / 'local_quote_total.parquet', [
        ('2022-11-09 00:00:00', tk, 10000),   # out-of-session summary -> dropped
        ('2022-11-09 09:15:05', tk, 500),
        ('2022-11-09 09:16:05', tk, 1200),
        ('2022-11-09 09:17:05', tk, 2000),
    ], 'quantity')
    conn.close()
    return TapeSource(tmp_path, table_prefix='local_quote')


@pytest.fixture
def toy_unpriced(tmp_path):
    """A tape whose first trade prints *before* its first price row.

    The thin-ticker shape: ``total`` has a 09:15:05 event but ``matched`` does
    not start until 09:16:00, so the first event has no forward-fillable price.
    A query that has to classify it must go INDETERMINATE, not skip it.
    """
    conn = duckdb.connect()
    tk = 'TOY'
    _write_tape(conn, tmp_path / 'local_quote_matched.parquet', [
        ('2022-11-09 09:16:00', tk, '73.40'),
        ('2022-11-09 09:17:00', tk, '73.90'),
    ], 'price')
    _write_tape(conn, tmp_path / 'local_quote_total.parquet', [
        ('2022-11-09 09:15:05', tk, 500),      # no matched precedes it
        ('2022-11-09 09:16:05', tk, 1200),
    ], 'quantity')
    conn.close()
    return TapeSource(tmp_path, table_prefix='local_quote')


OPEN = datetime(2022, 11, 9, 9, 0)
CLOSE = datetime(2022, 11, 9, 15, 0)


# -- reconstruction --------------------------------------------------------

def test_sized_tape_is_total_deltas_priced_by_forward_fill(toy):
    tape = toy.sized_tape('TOY', DAY)
    # The 00:00:00 summary row is gone; three intraday events remain.
    assert [(e.volume, e.price) for e in tape] == [
        (500, Decimal('73.30')),      # first event = first intraday total
        (700, Decimal('73.40')),      # delta 1200-500, price forward-filled
        (800, Decimal('73.90')),      # delta 2000-1200
    ], tape
    # The volumes sum to the day's last cumulative total.
    assert sum(e.volume for e in tape) == 2000


# -- the resting-side print condition --------------------------------------

def test_prints_through_a_resting_sell_sums_at_or_above_its_price(toy):
    # A resting SELL at 73.40 is lifted by buys trading at 73.40 or through it.
    got = toy.prints_through('TOY', Decimal('73.40'), Side.SELL, OPEN, CLOSE)
    assert got == 1500, got                       # 700 @ 73.40 + 800 @ 73.90


def test_prints_through_a_resting_buy_sums_at_or_below_its_price(toy):
    # A resting BUY at 73.40 is hit by sells trading at 73.40 or below it.
    got = toy.prints_through('TOY', Decimal('73.40'), Side.BUY, OPEN, CLOSE)
    assert got == 1200, got                       # 500 @ 73.30 + 700 @ 73.40


# -- the honesty rule: served-and-empty vs unserved ------------------------

def test_a_served_window_with_no_prints_through_is_zero_not_none(toy):
    # Nothing traded at or above 74.00 -- a definite 0 (the order rests), not
    # ignorance. This is what J34 rests on.
    got = toy.prints_through('TOY', Decimal('74.00'), Side.SELL, OPEN, CLOSE)
    assert got == 0, got


def test_an_unserved_ticker_is_none_not_zero(toy):
    # The tape holds no row for FPT -- INDETERMINATE, not a no-fill. J35.
    assert toy.prints_through('FPT', Decimal('73.40'), Side.SELL,
                              OPEN, CLOSE) is None


def test_an_unpriceable_in_window_event_is_indeterminate(toy_unpriced):
    # The first event has no matched price before it: its price is None, not a
    # guess. This is the dangerous arm of the honesty rule.
    tape = toy_unpriced.sized_tape('TOY', DAY)
    assert (tape[0].volume, tape[0].price) == (500, None), tape

    # A window that includes the unpriceable event cannot be classified: None,
    # never a partial sum of only the events that happen to be priced.
    assert toy_unpriced.prints_through('TOY', Decimal('73.40'), Side.SELL,
                                       OPEN, CLOSE) is None

    # A window that starts AFTER it sees only priced events and is answerable.
    since = datetime(2022, 11, 9, 9, 16)
    assert toy_unpriced.prints_through('TOY', Decimal('73.40'), Side.SELL,
                                       since, CLOSE) == 700


def test_an_inverted_window_is_refused_not_counted_as_zero(toy):
    # until < since is a swapped-argument bug, refused loudly (like DepthSource),
    # not silently swallowed as a zero that would read as a definite no-fill.
    with pytest.raises(ValueError, match='inverted'):
        toy.prints_through('TOY', Decimal('73.40'), Side.SELL, CLOSE, OPEN)


def test_the_window_bounds_the_prints(toy):
    # From 09:16:30 onward only the 09:17:05 event (73.90, 800) is in range.
    since = datetime(2022, 11, 9, 9, 16, 30)
    got = toy.prints_through('TOY', Decimal('73.40'), Side.SELL, since, CLOSE)
    assert got == 800, got


# --------------------------------------------------------------------------
# Measured against the real extract
# --------------------------------------------------------------------------

@requires_extract
def test_fpt_reconstructed_volume_sums_to_dailyvolume():
    src = TapeSource(str(EXTRACT), table_prefix='local_quote')
    tape = src.sized_tape('FPT', DAY)
    assert tape, 'FPT tape empty'
    assert sum(e.volume for e in tape) == 697700           # == quote.dailyvolume
    assert all(e.volume >= 0 for e in tape)                # monotone total


@requires_extract
def test_vn30f_reconstructed_volume_sums_to_dailyvolume():
    src = TapeSource(str(EXTRACT), table_prefix='quote')
    day = date(2025, 4, 8)
    a, b = datetime(2025, 4, 8, 9, 0), datetime(2025, 4, 8, 15, 0)
    tape = src.sized_tape('VN30F2504', day)
    assert tape, 'VN30F tape empty'
    assert sum(e.volume for e in tape) == 378696
    prices = [e.price for e in tape if e.price is not None]
    lo, hi = min(prices), max(prices)
    # The resting-SELL filter is monotone in the price and actually filters:
    # below the day's low it is lifted by everything, above the high by nothing,
    # and at a mid price by a strict fraction (not 0, not the whole day).
    assert src.prints_through('VN30F2504', lo, Side.SELL, a, b) == 378696
    assert src.prints_through('VN30F2504', hi + Decimal('1'), Side.SELL,
                              a, b) == 0
    mid = src.prints_through('VN30F2504', (lo + hi) / 2, Side.SELL, a, b)
    assert 0 < mid < 378696, (mid, lo, hi)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
