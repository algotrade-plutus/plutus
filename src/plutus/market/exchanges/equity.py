"""The equity exchanges: HSX, HNX, UPCOM.

One class parameterized by :class:`ExchangeSpec`. The three exchanges differ
only in fields the rulebook already carries -- trading unit, daily trading
limit, tick-size function -- so they are instances, not subclasses.

The six rules run in a fixed order and short-circuit on the first breach. The
order does not change the measured blocked-entry rate (verified: zero off-grid
closes and zero off-grid ceilings over the headline population), but it does
determine the per-rule composition of the rejection log, so it is normative.
"""

from typing import Optional

from plutus.core.constant import HNX, HSX, UPCOM, get_trading_unit
from plutus.market.exchanges.base import Exchange
from plutus.market.protocol import (
    InstrumentSpec, LockEvidence, MarketState, Order, OrderType, SessionPhase,
    Side,
)
from plutus.market.verdicts import Admissibility, AdmissionRule, Verdict

__all__ = ['EquityExchange', 'HSX_EXCHANGE', 'HNX_EXCHANGE', 'UPCOM_EXCHANGE']

#: Order types a call auction accepts.
#:
#: **A limit order is legal in both auctions.** HOSE's own session table reads
#: "LO, ATO" for the opening call and "LO, ATC" for the closing call, and HNX's
#: closing call reads "LO, ATC" likewise -- an LO submitted into an auction
#: joins the auction book and matches at the auction price if it is at or
#: through it. This module previously admitted only the matching auction type
#: and rejected every LO, which refuses a legal order in every call auction on
#: every venue.
#:
#: What a call auction genuinely does not accept is the continuous-session
#: market family -- MTL, MOK, MAK and MKT -- whose semantics (sweep the book,
#: kill the remainder) presuppose a resting book that a call auction does not
#: have while it is accumulating.
_OPENING_AUCTION_TYPES = frozenset({OrderType.AT_THE_OPENING, OrderType.LIMIT})
_CLOSING_AUCTION_TYPES = frozenset({OrderType.AT_THE_CLOSE, OrderType.LIMIT})


class EquityExchange(Exchange):
    """Order admission for a Vietnamese equity exchange."""

    def admits(
        self,
        order: Order,
        state: MarketState,
        *,
        instrument: Optional[InstrumentSpec] = None,
        regime_tag: Optional[str] = None,
    ) -> Admissibility:
        def verdict(v, rule=None, bound=None, **detail) -> Admissibility:
            return Admissibility(
                verdict=v, rule=rule, binding_constraint=bound, ts=state.ts,
                regime_tag=regime_tag, detail=detail,
            )

        price = order.limit_price

        # --- 1. TICK_GRID -------------------------------------------------
        if price is not None:
            tick = self.spec.get_tick_size(order.ticker, price)
            if tick is None:
                # get_hsx_tick_size falls off the end of its band table and
                # returns None despite its Decimal annotation.
                return verdict(
                    Verdict.INDETERMINATE, AdmissionRule.TICK_GRID,
                    reason='no tick band matches this price',
                )
            if (price % tick) != 0:
                return verdict(Verdict.REJECTED, AdmissionRule.TICK_GRID, tick)

        # --- 2. ROUND_LOT -------------------------------------------------
        # Resolved at the state's instant, not at load: HOSE's minimum lot was
        # 10 shares until 2021-01-03 and 100 from 2021-01-04. An explicit
        # instrument overrides the venue default.
        if instrument is not None:
            unit = instrument.trading_unit
        else:
            unit = get_trading_unit(
                self.spec.code,
                state.ts.date() if state.ts is not None else None,
            )
        if order.quantity <= 0 or (order.quantity % unit) != 0:
            return verdict(Verdict.REJECTED, AdmissionRule.ROUND_LOT, unit)

        # --- 3. BAND_LIMIT: stateless, needs no book ----------------------
        if price is not None:
            if state.ceiling is None or state.floor is None:
                return verdict(
                    Verdict.INDETERMINATE, AdmissionRule.BAND_LIMIT,
                    band_source=state.band_source.value,
                    reason='no price band available for this ticker-day',
                )
            if price > state.ceiling:
                return verdict(Verdict.REJECTED, AdmissionRule.BAND_LIMIT,
                               state.ceiling, side='above_ceiling')
            if price < state.floor:
                return verdict(Verdict.REJECTED, AdmissionRule.BAND_LIMIT,
                               state.floor, side='below_floor')

        # --- 4. BAND_LOCK: fillability, needs lock provenance -------------
        # An order priced AT a band is admissible; this asks whether it can
        # fill. Only the side that must cross the lock is blocked.
        if state.locked_side is not None and order.side is state.locked_side:
            marketable = price is None or (
                (order.side is Side.BUY and state.ceiling is not None
                 and price >= state.ceiling)
                or (order.side is Side.SELL and state.floor is not None
                    and price <= state.floor)
            )
            if marketable:
                if state.lock_evidence is LockEvidence.UNKNOWN:
                    return verdict(
                        Verdict.INDETERMINATE, AdmissionRule.BAND_LOCK,
                        lock_evidence=state.lock_evidence.value,
                        reason='lock cannot be established without book or proxy',
                    )
                bound = state.ceiling if order.side is Side.BUY else state.floor
                return verdict(Verdict.REJECTED, AdmissionRule.BAND_LOCK, bound,
                               lock_evidence=state.lock_evidence.value)

        # --- 5. FOREIGN_ROOM ----------------------------------------------
        # Room limits acquisition, not disposal, so only a foreign BUY is
        # constrained.
        #
        # This iteration assumes a DOMESTIC investor: `order.is_foreign`
        # defaults False and the rule short-circuits, so no trade is ever
        # blocked on room. That is a declared scope cut, not a finding that
        # room does not bind -- it does. `quote_foreignroom` carries the
        # REMAINING room (it decrements tick-by-tick within a session; HPG on
        # 2022-11-15 walks 1753953772 -> 1753951472 -> 1753949172), and
        # 34,653 observations sit below a single 100-share lot.
        #
        # An earlier comment here claimed the corpus has no such field. It is
        # false: the field exists, and `adapters/datahub.py` simply hardcodes
        # `foreign_room=None` when building state.
        if order.is_foreign and order.side is Side.BUY:
            if state.foreign_room is None:
                return verdict(
                    Verdict.INDETERMINATE, AdmissionRule.FOREIGN_ROOM,
                    reason='foreign room unavailable in this dataset',
                )
            if order.quantity > state.foreign_room:
                return verdict(Verdict.REJECTED, AdmissionRule.FOREIGN_ROOM,
                               state.foreign_room)

        # --- 6. SESSION_SEMANTICS -----------------------------------------
        session_verdict = self._admits_in_session(order, state)
        if session_verdict is not None:
            return session_verdict

        return verdict(Verdict.ADMITTED)

    def _admits_in_session(
        self, order: Order, state: MarketState
    ) -> Optional[Admissibility]:
        """None when the session poses no objection.

        ATO/ATC are call auctions: a continuous-trading order has no resting
        book to join, and an auction order has no meaning outside its auction.
        The asymmetries are read from the rulebook rather than hard-coded --
        ATO exists only on HSX/HNXDS, ATC not on UPCOM, PLO only on HNX.
        """

        def reject(**detail) -> Admissibility:
            return Admissibility(
                verdict=Verdict.REJECTED, rule=AdmissionRule.SESSION_SEMANTICS,
                binding_constraint=None, ts=state.ts, detail=detail,
            )

        phase = state.session
        if phase is SessionPhase.UNKNOWN:
            return Admissibility(
                verdict=Verdict.INDETERMINATE,
                rule=AdmissionRule.SESSION_SEMANTICS,
                binding_constraint=None, ts=state.ts,
                detail={'reason': 'session phase not supplied by the adapter'},
            )

        if phase in (SessionPhase.PRE_OPEN, SessionPhase.NOON_BREAK,
                     SessionPhase.POST_CLOSE):
            return reject(phase=phase.value, reason='exchange not matching')

        if phase is SessionPhase.OPENING_AUCTION:
            if self.spec.ato_session is None:
                return reject(phase=phase.value,
                              reason=f'{self.spec.code} has no opening auction')
            if order.order_type not in _OPENING_AUCTION_TYPES:
                return reject(phase=phase.value,
                              order_type=order.order_type.value,
                              accepts=[t.value for t in _OPENING_AUCTION_TYPES],
                              reason='order type not accepted in the opening '
                                     'call auction')
            return None

        if phase is SessionPhase.CLOSING_AUCTION:
            if self.spec.atc_session is None:
                return reject(phase=phase.value,
                              reason=f'{self.spec.code} has no closing auction')
            if order.order_type not in _CLOSING_AUCTION_TYPES:
                return reject(phase=phase.value,
                              order_type=order.order_type.value,
                              accepts=[t.value for t in _CLOSING_AUCTION_TYPES],
                              reason='order type not accepted in the closing '
                                     'call auction')
            return None

        if phase is SessionPhase.POST_CLOSE_PLO:
            if self.spec.plo_session is None:
                return reject(phase=phase.value,
                              reason=f'{self.spec.code} has no PLO session')
            return None

        # CONTINUOUS: an auction-only order type has no auction to join.
        if order.order_type in (OrderType.AT_THE_OPENING,
                                OrderType.AT_THE_CLOSE):
            return reject(phase=phase.value, order_type=order.order_type.value,
                          reason='auction order outside its auction')
        return None


HSX_EXCHANGE = EquityExchange(HSX)
HNX_EXCHANGE = EquityExchange(HNX)
UPCOM_EXCHANGE = EquityExchange(UPCOM)
