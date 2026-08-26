"""Fixtures for the validation harness tests.

**There is deliberately no ``__init__.py`` in this directory.** Every other
test package in the repo has one, and with no ``tests/__init__.py`` above them
pytest inserts ``tests/`` on ``sys.path`` and imports them as ``market.*``,
``data.*`` and so on. Doing that here would make ``tests/validation`` the
package named ``validation`` and shadow the harness itself, so
``import validation.logs`` would fail. Without the file, ``tests/validation``
goes on ``sys.path`` instead and the module names are the bare basenames --
which must therefore stay unique across the whole suite.

Two populations, deliberately kept apart:

* a **hand-written market** (:class:`StubSource`), so every number in a test
  is visible and the test pins the harness rather than the corpus;
* the **wired Parquet corpus**, gated by :data:`requires_corpus`, for the one
  test that has to prove the harness runs against real data.

The corpus root resolution is the same as ``tests/market/conftest.py``'s, so a
machine that runs one runs the other.
"""

import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from plutus.market.protocol import (
    BandSource, InstrumentKind, InstrumentSpec, MarketState, Resolution,
    SessionPhase,
)
from plutus.market.session.types import MarketInterval

_PARQUET_DEFAULT = Path('/Users/nadan/algotrade-research/dataset/hermes-parquet')


def _corpus_root():
    candidates = []
    env = os.environ.get('PLUTUS_DATA_ROOT')
    if env:
        candidates.append(Path(env))
    candidates.append(_PARQUET_DEFAULT)
    for root in candidates:
        if ((root / 'quote_close.parquet').exists()
                or (root / 'quote_close.csv').exists()):
            return root
    return None


CORPUS = _corpus_root()
requires_corpus = pytest.mark.skipif(
    CORPUS is None, reason='No daily corpus found; set PLUTUS_DATA_ROOT.')


@pytest.fixture(scope='session')
def corpus_root():
    return CORPUS


# --------------------------------------------------------------------------
# A hand-written market
# --------------------------------------------------------------------------
#
# 2024-06-03 .. 2024-06-07 is a Monday to a Friday, so T+2 falls inside the
# week and the weekday-only default settlement calendar agrees with a real
# one. That keeps these tests about the harness and not about Tet.

D1 = date(2024, 6, 3)
D2 = date(2024, 6, 4)
D3 = date(2024, 6, 5)
D4 = date(2024, 6, 6)
D5 = date(2024, 6, 7)
D6 = date(2024, 6, 10)
D7 = date(2024, 6, 11)
D8 = date(2024, 6, 12)

#: Eight consecutive weekdays. Long enough that a buy on D1 settles *and* a
#: sale made after that settles too, so a run over this window exercises both
#: DVP legs rather than only the securities one.
DAYS = (D1, D2, D3, D4, D5, D6, D7, D8)


def market(ticker, day, last, band=Decimal('0.07')):
    """One day's state with a published band, stamped midnight."""
    return MarketState(
        ticker=ticker, ts=datetime.combine(day, datetime.min.time()),
        reference=last, ceiling=last * (1 + band), floor=last * (1 - band),
        band_source=BandSource.PUBLISHED, last=last,
        session=SessionPhase.CONTINUOUS)


class StubSource:
    """A ``MarketDataSource`` over a hand-written table, plus intervals.

    Supplies exactly what the adapter protocol promises. ``interval()`` is
    implemented so a test can hand the fill policy a bar with volume; both
    shipped adapters supply none, which is why ``HardFillPolicy`` answers
    INDETERMINATE on the real corpora.
    """

    def __init__(self, rows, kinds=None, bars=None):
        self._rows = dict(rows)
        self._kinds = dict(kinds or {})
        self._bars = dict(bars or {})

    def state_at(self, ticker, ts):
        return self._rows.get((ticker, ts.date()))

    def states(self, ticker, start, end, *, resolution=Resolution.DAILY):
        for (name, _), state in sorted(self._rows.items(),
                                       key=lambda kv: kv[0][1]):
            if name == ticker and start <= state.ts <= end:
                yield state

    def instrument(self, ticker):
        code, kind = self._kinds.get(ticker, ('', InstrumentKind.UNKNOWN))
        multiplier = Decimal('1')
        expiry = None
        if kind is InstrumentKind.FUTURE:
            multiplier = Decimal('100000')
            expiry = date(2024, 6, 20)
        return InstrumentSpec(
            ticker=ticker, exchange_code=code, kind=kind, trading_unit=100,
            daily_trading_limit=Decimal('0.07'), multiplier=multiplier,
            expiry=expiry)

    def interval(self, ticker, start, end, *, resolution):
        bar = self._bars.get((ticker, start.date()))
        if bar is None:
            return None
        low, high, close, volume = bar
        return MarketInterval(
            ticker=ticker, start=start, end=end, resolution=resolution,
            state=self.state_at(ticker, start), open=close, high=high,
            low=low, close=close, volume=volume)


EQUITY_ROWS = {('FPT', day): market('FPT', day, Decimal('95.5'))
               for day in DAYS}
FUTURES_ROWS = {('VN30F2406', day): market('VN30F2406', day, Decimal('1250'))
                for day in DAYS}
KINDS = {'FPT': ('HSX', InstrumentKind.STOCK),
         'VN30F2406': ('HNXDS', InstrumentKind.FUTURE)}


@pytest.fixture
def stub_source():
    return StubSource({**EQUITY_ROWS, **FUTURES_ROWS}, KINDS)


def stub_scenario(strategy, *, source=None, name='stub', days=DAYS,
                  tickers=('FPT',), venues=('HSX', 'HNXDS'),
                  initial_cash='1000000000', initial_deposit='0',
                  fill_policy='soft', opening_holdings=None, **build):
    """A :class:`~validation.runner.Scenario` over the hand-written market.

    ``sessions`` is passed explicitly rather than derived, so the test says
    which days it runs and does not depend on the stub's row coverage.
    """
    from validation.runner import Scenario, Window, build_session
    src = source or StubSource({**EQUITY_ROWS, **FUTURES_ROWS}, KINDS)
    window = Window(name=name, start=days[0], end=days[-1],
                    tickers=tuple(tickers), sessions=tuple(days))
    session = build_session(
        start=window.start, end=window.end, venues=list(venues), source=src,
        initial_cash=initial_cash, initial_deposit=initial_deposit,
        fill_policy=fill_policy,
        initial_holdings=opening_holdings, **build)
    return Scenario(name=name, window=window, session=session,
                    strategy=strategy, source=src,
                    opening_holdings=dict(opening_holdings or {}))
