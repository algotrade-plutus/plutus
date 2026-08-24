"""Corpus gating for plutus.market tests.

The repo has no shared conftest; tests/data/test_audit.py and
tests/datahub/test_daily_ohlc.py each carry their own root helper. This module
consolidates the pattern for the market package and adds the raw-archive root,
which nothing resolved before.
"""

import os
from pathlib import Path

import pytest

_PARQUET_DEFAULT = Path('/Users/nadan/algotrade-research/dataset/hermes-parquet')
_ARCHIVE_DEFAULT = Path(
    '/Users/nadan/algotrade-research/dataset/hermes-offline-market-data-pre-2023'
)


def _corpus_root():
    """A root carrying the daily tables, or None."""
    candidates = []
    env = os.environ.get('PLUTUS_DATA_ROOT')
    if env:
        candidates.append(Path(env))
    candidates.append(_PARQUET_DEFAULT)
    for root in candidates:
        if (root / 'quote_close.parquet').exists() or (root / 'quote_close.csv').exists():
            return root
    return None


def _tick_root():
    """A root carrying ticks and the order book, or None."""
    candidates = []
    env = os.environ.get('PLUTUS_TICK_ROOT')
    if env:
        candidates.append(Path(env))
    candidates.append(_ARCHIVE_DEFAULT)
    for root in candidates:
        if (root / 'quote_askprice.csv').exists():
            return root
    return None


CORPUS = _corpus_root()
TICK_ROOT = _tick_root()

requires_corpus = pytest.mark.skipif(
    CORPUS is None, reason='No daily corpus found; set PLUTUS_DATA_ROOT.'
)
requires_ticks = pytest.mark.skipif(
    TICK_ROOT is None, reason='No tick archive found; set PLUTUS_TICK_ROOT.'
)


@pytest.fixture(scope='session')
def corpus_root():
    return CORPUS


@pytest.fixture(scope='session')
def tick_root():
    return TICK_ROOT
