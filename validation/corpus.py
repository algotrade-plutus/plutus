"""Data wiring for the validation harness, and what each source can decide.

Two corpora, and they cover different eras. A scenario must pick on evidence,
not convenience:

============================  ==========================================
Parquet, ``hermes-parquet``   2020-01-02 .. 2022-12-30, daily bars.
                              Already wired through
                              ``adapters/datahub.py``. **No high, no low,
                              no volume-derived intraday** -- an order
                              that was never touched and one that was
                              fully filled look identical on the bar, so
                              a fill judged from it is a model output,
                              not an observation.
Production Postgres           2021 .. 2026-08-26, read-only, spans the
                              KRX cutover. **No adapter exists.**
============================  ==========================================

:func:`assess_db_adapter` states what building the second one would cost and
what it would buy, so the decision is recorded rather than taken by default.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = ['PARQUET_ROOT', 'corpus_root', 'datahub_source', 'closes',
           'assess_db_adapter']

#: Where the daily corpus lives on this machine. Overridable with
#: ``PLUTUS_DATA_ROOT``, which is the same variable ``tests/market/conftest.py``
#: reads, so a scenario and the existing suite agree about the corpus.
PARQUET_ROOT = Path('/Users/nadan/algotrade-research/dataset/hermes-parquet')


def corpus_root() -> Optional[Path]:
    """The daily-corpus root, or ``None`` if it is not on this machine."""
    candidates: List[Path] = []
    env = os.environ.get('PLUTUS_DATA_ROOT')
    if env:
        candidates.append(Path(env))
    candidates.append(PARQUET_ROOT)
    for root in candidates:
        if ((root / 'quote_close.parquet').exists()
                or (root / 'quote_close.csv').exists()):
            return root
    return None


def datahub_source(root: Optional[Path] = None) -> Any:
    """A ``DataHubSource`` over the daily corpus.

    ``DataHubSource.for_root`` is the only constructor that works from a
    string; ``load_data_source`` cannot build this adapter from a config at
    all, and fails silently when it tries (FEATURES.md §16.3 #3), which is why
    the harness injects the source rather than naming it in the config.
    """
    from plutus.market.adapters.datahub import DataHubSource
    resolved = root or corpus_root()
    if resolved is None:
        raise FileNotFoundError(
            'no daily corpus found; set PLUTUS_DATA_ROOT or pass root=')
    return DataHubSource.for_root(str(resolved))


def closes(source: Any, ticker: str, start: date,
           end: date) -> Dict[date, Any]:
    """``{date: last}`` over the window, ``end`` **inclusive**.

    A scenario needs prices to choose a limit; this reads them from the same
    source the session reads, so the two cannot disagree about what the market
    did. The ``+ 1 day`` is because ``states`` is half-open on whole days --
    see :func:`validation.runner.sessions_from_source`.
    """
    states = source.states(
        ticker, datetime.combine(start, time.min),
        datetime.combine(end + timedelta(days=1), time.min))
    return {s.ts.date(): s.last for s in states
            if start <= s.ts.date() <= end}


def assess_db_adapter() -> Dict[str, Any]:
    """What a minimal read-only Postgres adapter would cost and buy.

    Returned as data rather than prose so a scenario can print it into its own
    report. **This is an assessment, not a build**: nothing in the harness
    depends on the production database.

    The finding: the Parquet corpus stops on 2022-12-30, so every post-KRX
    scenario -- the April-2025 crash, the March-2026 window that should make
    ``margin_model()`` raise, the 2025-2026 corporate actions -- is
    unreachable without one. Two of those windows are the only places the
    unbuilt post-KRX margin model can be exercised at all, which is the
    strongest argument for building it.

    Against: ``MarketDataSource`` has three methods and the session uses two,
    so the adapter surface is small, but the corpus defects are not. The
    ticker master stores the *current* venue, so band, tick and lot are wrong
    for every transferred ticker; ``quote.close`` carries non-Vietnamese rows
    that manufacture trading days on Vietnamese holidays unless the query
    filters on ``exchangeid``; and ``quote.reference`` repeats the previous
    close on ex-dates before 2025-01-07. Each of those has to be handled in
    the adapter or it silently poisons every scenario built on it.
    """
    return {
        'built': False,
        'needed_for': (
            'any scenario after 2022-12-30: the post-KRX margin model, the '
            'April-2025 crash, the 2025-2026 corporate actions, the KRX '
            'cutover itself'),
        'surface': ('MarketDataSource: state_at, states, instrument. The '
                    'session calls only the first and third; states() has no '
                    'session caller, and the harness uses it only to derive '
                    'trading days'),
        'must_handle': (
            'filter quote.close on exchangeid in (HSX, HNX, UPCOM, HNXDS) or '
            'non-Vietnamese rows manufacture trading days on Vietnamese '
            'holidays',
            'quote.ticker.exchangeid is the CURRENT venue, so band, tick and '
            'lot are wrong for every transferred ticker; SymbolRouter needs '
            'dated VenueListing rows instead',
            'quote.reference repeats the previous close on ex-dates before '
            '2025-01-07; the adjusted reference is mid(ceil, floor)',
            'quote.ticker.expdate is wrong for at least five VN30F contracts; '
            'derive expiry from the third-Thursday rule and the calendar',
            'unbounded counts on quote.matched and quote.bidprice time out; '
            'every query must be bounded by ticker and date',
        ),
        'recommendation': (
            'build it when a post-KRX scenario is actually written, not '
            'before. The pre-KRX windows -- 2021-02 Tet, 2022-08-29 '
            'settlement change, 2022-10/11 drawdown and pair trade -- are all '
            'served by the wired Parquet adapter, and they exercise every '
            'part of this harness'),
    }
