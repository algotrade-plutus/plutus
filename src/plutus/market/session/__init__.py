"""``plutus.market.session`` -- a simulated Vietnamese exchange, as a session.

A strategy connects to this package the way it connects to a broker: submit an
order, receive its status, read your holdings and your margin. The exchange
remembers settlement, margin and the dated rulebook so the strategy author does
not have to remember that a share bought today cannot be sold today, or that a
futures margin call cannot be met with equity cash.

**It is not a backtesting engine.** No strategy execution, no portfolio, no
P&L, no returns. The caller owns all of those; this package is the
counterparty. Charges *are* modelled, because they move cash and therefore
change admission outcomes -- but they are reported and debited, never netted
into a return.

The one screen that matters::

    from plutus.market.session import ExchangeSession
    from plutus.market.protocol import Order
    from plutus.core.order import OrderType, Side

    session = ExchangeSession.from_config('config.json')
    ack = session.submit(Order(ticker='FPT', side=Side.BUY, quantity=1000,
                               order_type=OrderType.LIMIT,
                               limit_price=Decimal('95.5')))
    session.advance_to(same_day_afternoon)
    rej = session.submit(Order(ticker='FPT', side=Side.SELL, quantity=1000,
                               order_type=OrderType.LIMIT,
                               limit_price=Decimal('96.0')))
    # Rejected(rule=UNSETTLED_HOLDING, binding_constraint=0,
    #          sellable_from=datetime(..., 13, 0))

Seven modules, and the dependency graph flows downward only:

==============  =====================================================
``types.py``    the shared vocabulary. Imports no session module.
``rulebook.py`` per-instant rule resolution and the ``(ticker, ts) ->
                venue`` seam. **A venue is ``(ticker, ts)``, never
                ``(ticker)``.**
``calendar.py`` VSDC settlement business days, which diverge from
                trading days around Tet, and the trading calendar.
``orders.py``   the order state machine. The order type **is** the
                time-in-force, so each type has its own terminal edge.
``ledgers.py``  the encumbrance ledger, tranche-list holdings and
                tranche-list proceeds. Balances are net of live orders.
``deposit.py``  the segregated derivatives deposit and the
                account-level margin entry point.
``fills.py``    the pluggable fill policy, and ``INDETERMINATE`` where
                the data cannot decide.
``exchange.py`` the session: clock, registry, routing, one cursor.
==============  =====================================================

What this package refuses to do is as load-bearing as what it does. Where the
data cannot decide, the answer is ``INDETERMINATE`` and the missing field is
named; where a value is an assumption rather than a sourced fact, the
docstring says so; and ``session.provenance()`` reports every counterfactual
pin and the settlement calendar's id, because a pinned run that does not say
it was pinned is not a counterfactual but a lie.
"""

from plutus.market.session.calendar import (
    CalendarCoverageError, CalendarError, SettlementCalendar, TradingCalendar,
    VnTradingCalendar, VsdcSettlementCalendar, weekday_settlement_calendar,
    weekday_trading_calendar,
)
from plutus.market.session.deposit import (
    ContractLedger, DerivativesAccount, MarginMonitor,
    account_margin_requirement, liquidation_sequence, margin_status,
)
from plutus.market.session.exchange import (
    EXCHANGE_BY_VENUE, ExchangeSession, IntervalSource, Session,
    charge_class_for, load_data_source, parse_config,
)
from plutus.market.session.evidence_level import (
    AssumptionKind, FillEvidenceLevel, assumption_kind, fill_evidence_level,
)
from plutus.market.session.fills import (
    BaseFillPolicy, FillPolicy, HardFillPolicy, SoftFillPolicy,
    build_fill_policy, floor_to_lot, participation_cap,
)
from plutus.market.session.ledgers import (
    CashLedger, EncumbranceLedger, HoldingsLedger, SecuritiesAccount,
    assess_charges, estimate_charges, trade_value,
)
from plutus.market.session.orders import (
    EncumbranceDivergence, OrderBookOfRecord, OrderIdFactory,
    expires_at_boundary, is_legal_transition,
)
from plutus.market.session.overnight import (
    PRE_KRX_CONTINUOUS, OvernightAssumption, OvernightGap,
    OvernightRequirement, overnight_requirement, scenario_grid_requirement,
    underlying_of,
)
from plutus.market.session.rulebook import (
    KRX_CUTOVER, RuleName, RuleResolution, RuleSet, RuleStatus, Rulebook,
    SymbolRouter, UnresolvedRule, VenueListing,
)
from plutus.market.session.types import (
    Accepted, AccountRef, AccountsConfig, Amended, BrokerProfile, Cancelled,
    Cash, Charge, ChargeBase, ChargeClass, ChargeRule, ChargeSide, Confidence,
    ContractPosition, DataConfig, DataField, DebitedAt, Encumbrance, Event,
    EventKind, ExchangeRulesConfig, ExpiryTrigger, Fill, FillDecision,
    FillEvidence, FillOutcome, FillPolicyConfig, Holding, HoldingTranche,
    IndeterminateReport, InvestorClass, LeviedBy, LiquidationRule,
    MarginStatus, MarginView, MarketInterval, OrderId, OrderRecord, OrderState,
    OrderTransition, Pin, Pool, ProceedsTranche, Rejected, RejectionRule,
    RuleCitation, RulebookEdition, SessionConfig, SessionProvenance,
    SettlementRule, StatefulRule, TimeInForce, Transferred, Venue,
    pool_for_venue, rule_value, signed_quantity,
)

__all__ = [
    # -- the entry point --------------------------------------------------
    'ExchangeSession', 'Session', 'parse_config', 'load_data_source',
    'EXCHANGE_BY_VENUE', 'IntervalSource', 'charge_class_for',
    # -- configuration ----------------------------------------------------
    'SessionConfig', 'ExchangeRulesConfig', 'AccountsConfig',
    'FillPolicyConfig', 'DataConfig', 'BrokerProfile', 'Pin',
    # -- the rulebook and its seam ----------------------------------------
    'Rulebook', 'RuleSet', 'RuleName', 'RuleStatus', 'RuleResolution',
    'UnresolvedRule', 'SymbolRouter', 'VenueListing', 'KRX_CUTOVER',
    'RuleCitation', 'RulebookEdition', 'SettlementRule', 'Confidence',
    # -- calendars --------------------------------------------------------
    'SettlementCalendar', 'VsdcSettlementCalendar', 'TradingCalendar',
    'VnTradingCalendar', 'weekday_settlement_calendar',
    'weekday_trading_calendar', 'CalendarError', 'CalendarCoverageError',
    # -- orders -----------------------------------------------------------
    'OrderBookOfRecord', 'OrderIdFactory', 'OrderRecord', 'OrderState',
    'OrderTransition', 'TimeInForce', 'ExpiryTrigger', 'OrderId',
    'is_legal_transition', 'expires_at_boundary', 'EncumbranceDivergence',
    # -- ledgers ----------------------------------------------------------
    'EncumbranceLedger', 'HoldingsLedger', 'CashLedger', 'SecuritiesAccount',
    'estimate_charges', 'assess_charges', 'trade_value',
    'Encumbrance', 'Holding', 'HoldingTranche', 'Cash', 'ProceedsTranche',
    # -- the segregated deposit -------------------------------------------
    'DerivativesAccount', 'ContractLedger', 'MarginMonitor',
    'account_margin_requirement', 'margin_status', 'liquidation_sequence',
    'ContractPosition', 'MarginView', 'MarginStatus', 'LiquidationRule',
    'InvestorClass',
    # -- the overnight layer ----------------------------------------------
    'OvernightRequirement', 'OvernightGap', 'OvernightAssumption',
    'overnight_requirement', 'scenario_grid_requirement', 'underlying_of',
    'PRE_KRX_CONTINUOUS',
    # -- fills ------------------------------------------------------------
    'FillPolicy', 'BaseFillPolicy', 'SoftFillPolicy', 'HardFillPolicy',
    'build_fill_policy', 'floor_to_lot', 'participation_cap',
    'Fill', 'FillDecision', 'FillOutcome', 'FillEvidence', 'MarketInterval',
    'FillEvidenceLevel', 'AssumptionKind', 'fill_evidence_level', 'assumption_kind',
    'DataField',
    # -- results and provenance -------------------------------------------
    'Accepted', 'Rejected', 'Cancelled', 'Amended', 'Transferred',
    'RejectionRule', 'StatefulRule', 'Event', 'EventKind',
    'SessionProvenance', 'IndeterminateReport',
    # -- charges ----------------------------------------------------------
    'Charge', 'ChargeRule', 'ChargeBase', 'ChargeClass', 'ChargeSide',
    'DebitedAt', 'LeviedBy',
    # -- vocabulary -------------------------------------------------------
    'Venue', 'Pool', 'AccountRef', 'pool_for_venue', 'signed_quantity',
    'rule_value',
]
