"""HNXDS: the derivatives exchange.

Admission here is nearly trivial, and that is the finding. The round lot is one
contract so the lot rule never binds; the tick grid is a flat 0.1 so the grid
rule is uninteresting; there is no foreign-ownership cap at all. What binds
instead is position survival -- margin, forced liquidation, blocked exits,
position limits and expiry -- none of which has a equity analogue.

Everything here reports what the **exchange** would do. It does not liquidate
on the trader's behalf, re-enter, roll, or compute strategy P&L.
"""

from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from plutus.core.constant import DS, ExchangeSpec
from plutus.market.exchanges.base import Exchange
from plutus.market.expiry import expiry_date
from plutus.market.margin import MarginConfig, MarginState, evaluate_margin
from plutus.market.protocol import (
    InstrumentSpec, LockEvidence, MarketState, Order, Position, Side,
)
from plutus.market.verdicts import (
    Admissibility, AdmissionRule, PositionEvent, PositionEventKind,
    SettlementSource, Verdict, Viability,
)

__all__ = ['HNXDSExchange', 'HNXDS_EXCHANGE']


class HNXDSExchange(Exchange):
    """Order admission and position survival for VN30 futures.

    :meth:`admits` is sourced and current. :meth:`sustains` is the **legacy
    batch research path**: its margin test models a maintenance margin ratio
    Vietnam does not publish, and it is kept because the published
    margin-incidence figures were computed through it. Read its warning before
    using it for anything new; the session's margin entry point is
    :func:`plutus.market.session.deposit.account_margin_requirement`.
    """

    def __init__(
        self,
        spec: ExchangeSpec = DS,
        margin_config: Optional[MarginConfig] = None,
        position_limit: Optional[int] = None,
    ):
        super().__init__(spec)
        self.margin_config = margin_config or MarginConfig.VN30F_DEFAULT
        self.position_limit = position_limit

    # -- admission ---------------------------------------------------------

    def admits(
        self,
        order: Order,
        state: MarketState,
        *,
        instrument: Optional[InstrumentSpec] = None,
        regime_tag: Optional[str] = None,
    ) -> Admissibility:
        """Tick grid, a lot of one, and the band rules. No foreign-room rule."""

        def verdict(v, rule=None, bound=None, **detail) -> Admissibility:
            return Admissibility(verdict=v, rule=rule, binding_constraint=bound,
                                 ts=state.ts, regime_tag=regime_tag,
                                 detail=detail)

        price = order.limit_price
        if price is not None:
            tick = self.spec.get_tick_size(order.ticker, price)
            if tick is None:
                return verdict(Verdict.INDETERMINATE, AdmissionRule.TICK_GRID)
            if (price % tick) != 0:
                return verdict(Verdict.REJECTED, AdmissionRule.TICK_GRID, tick)

        unit = instrument.trading_unit if instrument else self.spec.trading_unit
        if order.quantity <= 0 or (order.quantity % unit) != 0:
            return verdict(Verdict.REJECTED, AdmissionRule.ROUND_LOT, unit)

        if price is not None:
            if state.ceiling is None or state.floor is None:
                return verdict(Verdict.INDETERMINATE, AdmissionRule.BAND_LIMIT,
                               band_source=state.band_source.value)
            if price > state.ceiling:
                return verdict(Verdict.REJECTED, AdmissionRule.BAND_LIMIT,
                               state.ceiling)
            if price < state.floor:
                return verdict(Verdict.REJECTED, AdmissionRule.BAND_LIMIT,
                               state.floor)

        return verdict(Verdict.ADMITTED)

    # -- position survival -------------------------------------------------

    def sustains(
        self,
        position: Position,
        path: Sequence[MarketState],
        *,
        settlements: Optional[Dict[object, Decimal]] = None,
        settlement_source: SettlementSource = SettlementSource.CLOSE_PROXY,
        margin_config: Optional[MarginConfig] = None,
    ) -> Viability:
        """Walk a position along a price path; report what the exchange would do.

        .. warning::

           **The margin test this walks is the legacy per-position one, and
           the quantity it tests does not exist.** ``MARGIN_CALL`` fires when
           ``evaluate_margin``'s ``equity / notional`` falls below
           ``config.maintenance_rate`` -- a maintenance margin ratio no
           Vietnamese rule states at any date. The real test is account-level:
           ``MR = IM + VM`` over the whole portfolio, VM loss-only, against
           ``utilisation = MR / margin assets`` on an 80/90/100 ladder
           (rulebook 6.3; VSDC "Thông tin về ký quỹ" §II.4(b), §V.4).
           See :mod:`plutus.market.margin`'s module warning and
           ``PROVENANCE``.

           This method is nevertheless **not deprecated and not rewired**, for
           a reason that is about evidence rather than inertia. It is the path
           the published margin-incidence figures were computed on, and
           ``measurements/margin_incidence_account.py`` measured whether the
           account-level model reproduces them: it does not, at any funding
           level, and the disagreement is structural -- the utilisation test
           divides by a deposit balance this signature has no way to receive.
           Rewiring it would restate a published number without saying so,
           which is the one thing that must not happen quietly.

           Two further reasons this shape cannot simply become the session's:
           it takes a whole ``Sequence[MarketState]`` in one batch with
           nowhere to carry an outstanding call across days (which is what
           :class:`~plutus.market.session.deposit.MarginMonitor` exists for),
           and it takes a lone
           :class:`~plutus.market.protocol.Position`, which
           :func:`~plutus.market.session.deposit.account_margin_requirement`
           refuses outright.

        Args:
            position: the open position.
            path: daily states in ascending time order.
            settlements: optional ``{date: settlement}`` overriding the close
                proxy. Supply this from
                :class:`plutus.market.expiry.SettlementResolver` to use the
                published or TWAP tiers.
            settlement_source: provenance recorded on each event; must match
                whatever ``settlements`` came from.
            margin_config: overrides the exchange default (used by the sweep).
        """
        config = margin_config or self.margin_config
        events: List[PositionEvent] = []
        indeterminate = 0
        called = False
        expiry = expiry_date(position.ticker)

        if (self.position_limit is not None
                and position.quantity > self.position_limit):
            events.append(PositionEvent(
                kind=PositionEventKind.POSITION_LIMIT_EXCEEDED,
                ts=path[0].ts if path else position.entry_ts,
                settlement=None, settlement_source=settlement_source,
                equity=None, notional=None, margin_ratio=None,
                detail={'quantity': position.quantity,
                        'limit': self.position_limit,
                        'note': 'config-asserted; no corpus carries account data'},
            ))

        for state in path:
            day = state.ts.date()
            settlement = (settlements or {}).get(day, state.last)
            if settlement is None or Decimal(str(settlement)) <= 0:
                indeterminate += 1
                continue

            margin = evaluate_margin(position, Decimal(str(settlement)), config)

            if not called and margin.ratio < config.maintenance_rate:
                called = True
                events.append(self._event(
                    PositionEventKind.MARGIN_CALL, state, margin,
                    settlement_source,
                    maintenance_rate=str(config.maintenance_rate)))

            if margin.ratio <= config.liquidation_rate:
                events.append(self._event(
                    PositionEventKind.FORCED_LIQUIDATION, state, margin,
                    settlement_source))
                return Viability(False, tuple(events), len(path), indeterminate)

            if (position.stop_price is not None
                    and self._exit_blocked(position, state)):
                events.append(self._event(
                    PositionEventKind.EXIT_BLOCKED, state, margin,
                    settlement_source, stop_price=str(position.stop_price),
                    lock_evidence=state.lock_evidence.value))

            if expiry is not None and day >= expiry:
                events.append(self._event(
                    PositionEventKind.EXPIRY_SETTLEMENT, state, margin,
                    settlement_source, expiry=expiry.isoformat()))
                return Viability(True, tuple(events), len(path), indeterminate)

        return Viability(True, tuple(events), len(path), indeterminate)

    @staticmethod
    def _exit_blocked(position: Position, state: MarketState) -> bool:
        """Would the exchange refuse the exit because the band is locked?"""
        if (state.lock_evidence is LockEvidence.UNKNOWN
                or state.locked_side is None):
            return False
        # A long exits by selling: a locked floor blocks it.
        if position.side is Side.BUY:
            return (state.locked_side is Side.SELL and state.floor is not None
                    and position.stop_price <= state.floor)
        return (state.locked_side is Side.BUY and state.ceiling is not None
                and position.stop_price >= state.ceiling)

    @staticmethod
    def _event(kind, state: MarketState, margin: MarginState,
               source: SettlementSource, **detail) -> PositionEvent:
        return PositionEvent(
            kind=kind, ts=state.ts, settlement=margin.settlement,
            settlement_source=source, equity=margin.equity,
            notional=margin.notional, margin_ratio=margin.ratio, detail=detail,
        )


HNXDS_EXCHANGE = HNXDSExchange(DS)
