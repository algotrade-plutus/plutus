"""``validation`` -- the harness that stresses the assembled simulator.

This package is **not** part of the simulator. It is a caller: it drives
``plutus.market.session.ExchangeSession`` the way a trading desk would, records
what a broker would record, and checks the identities an auditor would check.
Nothing here decides a market outcome; if a scenario produces a wrong number,
the number came from the session.

Four pieces:

===========================  ============================================
:mod:`validation.strategy`   the strategy interface. A trading algorithm
                             is a caller of the simulator: it receives
                             market state and events and submits or
                             cancels orders. It owns no P&L.
:mod:`validation.logs`       the three logs a real broker produces --
                             trade, cash, settlement -- each row
                             timestamped and carrying **why**.
:mod:`validation.identities` the ledger identities as reusable checks.
:mod:`validation.runner`     a window, a source, a broker profile and a
                             strategy in, three logs and the identity
                             results out.
===========================  ============================================

:mod:`validation.journal` is the seam the cash and settlement logs are
recorded through, and it exists because of a finding: the derivatives deposit
keeps a full audit trail of every movement and the securities cash ledger
keeps none -- ``CashLedger.debit`` takes ``ts`` and ``reason`` on every call
and discards both. Read that module's docstring before changing it.

The shortest scenario that exercises the whole harness::

    from validation import (BaseStrategy, Scenario, Window, build_session,
                            datahub_source, run_scenario)

    class BuyAndHold(BaseStrategy):
        name = 'buy-and-hold'
        def on_session(self, ctx):
            if ctx.holdings('FPT').total == 0 and not ctx.live_orders():
                price = ctx.price('FPT')
                if price is not None:
                    ctx.buy('FPT', 1000, limit_price=price)

    source = datahub_source()
    window = Window(name='demo', start=date(2022, 3, 1), end=date(2022, 3, 10),
                    tickers=('FPT',), reference_ticker='FPT')
    session = build_session(start=window.start, end=window.end,
                            venues=['HSX'], source=source,
                            initial_cash='1000000000')
    result = run_scenario(Scenario(name='demo', window=window, session=session,
                                   strategy=BuyAndHold(), source=source))
    assert result.ok, [r.detail for r in result.failed_identities]
"""

from validation.corpus import (
    PARQUET_ROOT, assess_db_adapter, closes, corpus_root, datahub_source,
)
from validation.identities import IdentityResult, check_identities
from validation.journal import LedgerJournal
from validation.logs import (
    CashLog, CashLogEntry, CashMovement, RunLogs, SettlementAction,
    SettlementLog, SettlementLogEntry, TradeAction, TradeLog, TradeLogEntry,
    json_safe,
)
from validation.runner import (
    DEFAULT_CLOSE, DEFAULT_OPEN, Scenario, ScenarioResult, Snapshot, Window,
    build_session, run_scenario, sessions_from_source,
)
from validation.strategy import (
    Annotation, BaseStrategy, StepPhase, Strategy, StrategyContext,
)

__all__ = [
    # -- the strategy interface -------------------------------------------
    'Strategy', 'BaseStrategy', 'StrategyContext', 'StepPhase', 'Annotation',
    # -- the three logs ----------------------------------------------------
    'TradeLog', 'TradeLogEntry', 'TradeAction',
    'CashLog', 'CashLogEntry', 'CashMovement',
    'SettlementLog', 'SettlementLogEntry', 'SettlementAction',
    'RunLogs', 'json_safe', 'LedgerJournal',
    # -- the identities ----------------------------------------------------
    'IdentityResult', 'check_identities',
    # -- the runner --------------------------------------------------------
    'Window', 'Scenario', 'ScenarioResult', 'Snapshot', 'run_scenario',
    'build_session', 'sessions_from_source', 'DEFAULT_OPEN', 'DEFAULT_CLOSE',
    # -- data --------------------------------------------------------------
    'datahub_source', 'corpus_root', 'closes', 'PARQUET_ROOT',
    'assess_db_adapter',
]
