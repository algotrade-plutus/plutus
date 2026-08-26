"""Multi-exchange pair trade: a VN30 basket on HSX against VN30F on HNXDS.

The canonical Vietnamese two-venue trade, put to the assembled simulator over a
real basis dislocation. A desk long thirty VN30 constituents on HOSE hedges
with front-month index futures on HNX-DS. **One session object, two venues, two
segregated pools, one clock**, and every number below was read back out of the
trade, cash and settlement logs rather than out of the code that produced it.

**The window.** 2022-10-21 to 2022-11-17, twenty sessions, all in the wired
Parquet corpus. ``VN30F2211`` is front month throughout and expires on the last
session, so the run ends in a cash settlement while the equity leg is still
held. The window contains the **widest front-month basis in the whole
2021-2026 corpus**: F - S is -25.57 on 2022-10-21 and -31.88 on 2022-10-24
(-3.27%), it closes to -3.50 by 2022-10-27, re-opens to -24.00 on 2022-11-10,
and the contract then goes **limit-up 6.99% on 2022-11-16** into its expiry.
That last move is what breaks the short leg.

**The direction is the only one a Vietnamese account can hold.** A -3.27%
futures discount says futures are cheap against spot, and the textbook trade is
to buy futures and sell the basket. **There is no operational stock short
selling in Vietnam**, so that trade does not exist here, and this scenario
checks that the simulator refuses it (:func:`run_venue_rules`, ``naked_short``)
rather than modelling a market that does not exist. What is left is the legal
construction: a desk already long the basket sells futures as a hedge, and at
-25.57 that hedge is put on at a 2.53% give-away. The **-16,000,000d realised
loss on the first futures leg is that give-away**, not a defect.

**The shape of the run.**

===========  =========================================================
2022-10-21   enter. 30 x 300 shares on HSX (411,750,000d) and 4
             VN30F2211 short on HNXDS. The deposit opens at **zero**,
             so every dong it ever holds arrived by an explicit
             transfer and the segregation audit is total. The futures
             leg is **refused** -- and that refusal is the scenario.
2022-10-27   basis back to -3.50: sell the whole basket, buy back the
             four contracts. Realised -16,000,000d on the futures.
2022-10-28   sweep the free deposit back to securities. The reverse
             leg of segregation, bounded by the withdrawal test.
2022-11-10   re-enter at a -24.00 basis, deposit funded to 62,000,000d
             -- deliberately thin enough that the squeeze bites.
2022-11-16   VN30F2211 closes limit-up at 957.6. Forced.
2022-11-17   expiry. Cash settlement of -23,880,000d while the equity
             leg is still held and 137,765,732d of securities cash
             sits one pool away, untouched.
===========  =========================================================

WHAT WAS PROVED
---------------

**Routing.** Every one of the 90 equity fills is logged ``venue='HSX'``,
``pool='securities'``; every one of the 3 futures fills ``venue='HNXDS'``,
``pool='derivatives'``. No order was routed by instrument kind; the pool is a
routing fact (``exchange.py`` ``_reserve``) and the log records it per row.

**Each leg judged by its own venue's rules**, shown as pairs of orders that
differ only in the venue:

============================  ==========================  ==================
order                         HSX                         HNXDS
============================  ==========================  ==================
quantity 3                    ``ROUND_LOT``, bound 100    admitted (lot 1)
limit price ending ``.05``    admitted (0.05 tick band)   ``TICK_GRID``,
                                                          bound 0.1
one tick outside the band     ``BAND_LIMIT``, bound       ``BAND_LIMIT``,
                              22.80 (ACB ceiling)         bound 964.6
sell with no position         ``UNSETTLED_HOLDING``       opens a short
============================  ==========================  ==================

**Charges under each venue's own schedule**, seven rules, two pools, and the
bases are not the same kind of thing -- HSX prices everything off
``TRADE_VALUE`` in thousand-dong units, HNXDS off ``PER_CONTRACT`` in absolute
dong plus one ``TRADE_VALUE`` row whose rate is a function of the VSD initial
margin ratio:

===================================  =====  =============  ==============
charge                               venue  base           run total (d)
===================================  =====  =============  ==============
``pit_securities_transfer``          HSX    trade_value          415,125
``exchange_service_hsx_equity``      HSX    trade_value          327,187
``broker.commission.hsx``            HSX    trade_value        1,817,696
``pit_derivatives_transfer``         HNXDS  trade_value          101,278
``exchange_service_index_future``    HNXDS  per_contract          32,400
``vsdc_derivatives_clearing``        HNXDS  per_contract          30,600
``broker.commission.hnxds``          HNXDS  per_contract          60,000
===================================  =====  =============  ==============

Every one reproduces by hand: 2,700d and 2,550d a contract on 12 novated
contracts; 0.000065 = 0.0005 x 0.13 of notional on each of four occasions
including the maturity; 0.001 of 415,125,000d of sale value withheld at source.

**Segregation, in both of its two shapes.** ``_annotate_segregation`` answers a
question ``Rejected`` alone cannot: is the pair fundable at all?

* ``funded_in_aggregate=True`` -- 2022-10-21, the deposit holds nothing, the
  leg needs 51,220,000d and securities cash has 187,663,198d available. One
  transfer and the same order fits.
* ``funded_in_aggregate=False`` -- with the cash already committed to equity,
  ``other_pool_available`` 35,829,708d against a 51,220,000d requirement, and
  the cure says so: *"no transfer can fund it"*.

**And the pair is not silently half-filled.** In the second case the equity leg
is already accepted and resting. The strategy reads the refusal, cancels all
thirty equity orders and abandons the trade as a trade. The exchange has no
notion of a pair and says so; the caller was told enough to act, which is the
whole point of the annotation.

**A margin call at the right rung on the right day.** The second leg walks the
ladder and every rung reproduces from ``IM = 0.13 x |net| x 100,000 x price``
and ``VM = max(0, -P&L from entry)`` against a 61,935,267d deposit:

==========  =======  ===========  ===========  ======  ==========
session     mark     IM           VM           util    reported
==========  =======  ===========  ===========  ======  ==========
2022-11-10   912.8   47,465,600            0   0.7664  ok
2022-11-11   938.0   48,776,000   10,080,000   0.9503  **CALL**,
                                                       cure by
                                                       11-14 08:45
2022-11-14   932.0   48,464,000    7,680,000   0.9065  **FORCED**
                                                       (uncured)
2022-11-15   895.0   46,540,000            0   0.7514  ok, cleared
2022-11-16   957.6   49,795,200   17,920,000   1.0933  **FORCED**
2022-11-17   972.5   50,570,000   23,880,000   1.2021  FORCED,
                                                       then expiry
==========  =======  ===========  ===========  ======  ==========

The 2022-11-14 row is the one worth reading: utilisation is 0.9065, on the
*call* rung, and the event is a forced close because the 2022-11-11 call went
unanswered past its deadline. The 2022-11-15 row clears it, and 2022-11-16
fires again on the rung itself. Both escalation paths, in one window.

**Every dong accounted for.** Opening 600,000,000d against closing
137,765,732d of securities cash, 38,029,982d of deposit and a basket marked at
393,885,000d is a change of **-30,319,286d**, and it decomposes exactly:
+3,375,000 on the first basket, -16,000,000 realised on the first futures leg,
+8,970,000 on the second basket, -23,880,000 at final settlement, -2,784,286 of
charges. Nothing is left over. :func:`reconciliation` computes it.

WHAT THIS SCENARIO FOUND
------------------------

Two fixed, nine open. :func:`findings` returns all eleven as data so a report
cannot quietly drop them. The last two are the answer to "is anything silently
zero, skipped or defaulted": a ledger identity that passes because it found
nothing to check, and a charge schedule row that is never levied.

1. **A breaching account could not close its position.** FIXED in
   ``deposit.py`` ``DerivativesAccount.reserve_for_order``. An offsetting order
   has ``increment == 0`` and therefore ``required == 0``; ``free_deposit`` is
   ``balance - posted - resting`` and goes negative the moment the mark pushes
   IM past the balance. ``0 > -840733`` is True, so the funding gate refused
   the order. Measured before the fix, 4 short VN30F2211 from 2022-11-10
   against a 48,000,000d deposit: ``forced`` at 1.2278 on 2022-11-11 with
   ``free_deposit`` -840,733d and the closing buy
   ``Rejected(INSUFFICIENT_DEPOSIT, required=0.000)``; refused again on
   2022-11-14 at 1.1712; admitted only on 2022-11-15, once the mark had cured
   the breach by itself. The account was told it was in breach, told
   to reduce, and refused the reduction. That defeats two of the method's own
   documented promises -- "an order that closes a position reserves zero", and
   the level-3 gate that excepts ``increment == 0`` because QD 26 Dieu 13.2.a
   requires the offsetting trade to be admitted on a breaching account. Guarded
   with ``required > 0``; :func:`run_breach_then_close` is the regression.

2. **The derivatives pool had no itemised fee statement.** FIXED in
   ``exchange.py`` (``_debit_charges``). ``DepositEntry`` is the only cash
   journal either pool has on the session side -- ``CashLedger`` keeps none by
   design -- and the futures path debited the *sum* of a fill's charges in one
   movement reading ``charges on FILL-000031`` for -66,610d. That single row
   was four separate levies by four separate parties: 25,610d of state transfer
   tax, 10,800d of HNX trading service price, 10,200d of VSDC clearing fee and
   20,000d of broker commission. The securities pool already itemised, so the
   two halves of the same simulator disagreed about whether a fee statement is
   auditable. Now one debit per charge, each naming its kind.

3. **OPEN -- the segregation cure is short by the fill's own charges, and the
   boundary is inclusive.** ``_annotate_segregation`` prints
   ``transfer(securities -> derivatives, <shortfall>) and resubmit``.
   ``shortfall`` is ``required - free_deposit``, the margin and nothing else,
   while ``reserve_for_buy`` on the equity side adds ``estimate_charges`` to
   its own requirement. Obey the printed cure literally and two things bite at
   once: the deposit lands at *exactly* the initial margin, which
   ``reserve_for_order`` admits (``required > free_deposit`` is False at
   equality) and ``margin_status`` counts as a breach (``utilisation >=
   forced_close_utilisation``); and the fill's charges are then debited from
   the same deposit. Measured: transfer 51,220,000d and the account is already
   at **utilisation exactly 1, status FORCED, before a single charge is
   levied**; the fill of 4 contracts at 985.0 then takes 66,610d out of the
   same deposit, leaving 51,153,390d against 51,220,000d of IM and
   **utilisation 1.0013**. The simulator's own printed advice puts the account
   into forced liquidation on the entry session.
   :func:`run_bare_cure` is that run. Reported and not fixed: the arithmetic
   sits inside the margin model, and this scenario does not have the standing
   to move a margin number.

4. **OPEN -- a naked short is filed under ``unsettled_holding``.** Selling ACB
   with no position at all returns ``Rejected(UNSETTLED_HOLDING,
   binding_constraint=0, sellable_from=None)`` and
   ``detail={'requested': 300, 'settled': 0, 'committed': 0, 'unsettled': 0}``.
   The outcome is right -- Vietnam has no operational short selling and the
   order is refused -- and ``sellable_from=None`` honestly promises nothing.
   The *rule* is wrong: an account that owns none of a name is not waiting for
   settlement. A rejection log keyed on rules exists to be counted, and this
   one cannot separate "you bought today, wait for T+2" from "you own none of
   this and never will", which have different cures. The detail distinguishes
   them (``unsettled == 0``); the rule does not. Not fixed: a new
   ``AdmissionRule`` member is a rulebook-level change.

5. **OPEN -- neither leg of this pair can be adjudicated on the daily corpus,
   and the report cannot say which field was missing.** Under ``hard`` the same
   two orders are ``INDETERMINATE`` at a continuous touch -- the bars carry no
   high, no low and no volume, so an order that was never touched and one that
   filled look identical -- and ``indeterminate_report().by_field`` is
   ``{}``, because the continuous-touch refusal names no ``DataField``. So the
   headline for the whole scenario is that **every fill in the main run is a
   ``soft`` model output, not an observation**: at a 0.6667 indeterminate rate
   under ``hard``, both legs simply expire unfilled. :func:`run_hard_arm`.

6. **OPEN -- the 09:30 margin mark uses the same session's close.** On a daily
   run the whole day's bar is the interval, which ``_interval_for`` declares,
   so the mark taken at the 09:30 step is the 14:45 price. The 2022-10-27
   ``margin_warning`` at 0.8670 is computed from that session's 1025.0 close,
   which at 09:30 nobody had seen. Not a defect in the margin model -- a
   declared consequence of the resolution -- but a margin event timestamped
   09:30 is not an intraday event and a report must not present it as one.

7. **OPEN -- ``FORCED_LIQUIDATION`` reports and does not execute.** Every one
   of the six forced events in this run carries ``detail['executed'] = False``,
   so nothing is closed, the breach persists and the event repeats at each
   mark. The account is still short 4 contracts at expiry and settles them in
   cash. A scenario counting forced closes must count *distinct sessions*, not
   events.

8. **OPEN -- variation margin never settles in cash and the VM baseline never
   rolls.** ``DerivativesAccount.settle_daily`` exists and has no session call
   site, so the deposit balance is flat between fills -- 61,935,267d on every
   one of the six sessions of the second leg -- and ``VM`` is measured from the
   **entry** price, not from yesterday's settlement. The whole 23,880,000d loss
   arrives in one movement at expiry. Any replay that debits VM T+1 will not
   match this simulator, and the utilisations in the table above are only right
   under the no-cash-VM convention.

9. **OPEN -- the published final settlement price is in the corpus and the
   session did not use it.** The expiry event reports
   ``settlement_source='close_proxy'``, ``substituted=True``, and settles at
   the futures close **972.5**. ``quote_settlementprice.parquet`` carries
   ``VN30INDEX`` for 2022-08-17 to 2022-12-15, 180 ticks running 14:15:01 to
   14:45:12 on 2022-11-17, and its last tick -- the published VSD final
   settlement price -- is **972.78**. On this short position that is
   0.28 x 4 x 100,000 = **112,000d of settlement loss the run did not book**.
   The tier is declared rather than hidden, and ``price_basis`` even quantifies
   the proxy error over 46 expiries, so this is a data-plumbing gap
   (``DataHubSource`` has no settlement-price reader) and not a lie -- but the
   oracle was on disk.

10. **OPEN -- one of the nine ledger identities passes on this run because it
    found nothing to check.** ``deposit_segregation`` joins ``session.charges``
    to the cash log on ``charge_kind`` and ``fill_id``. Measured on the main
    run: 223 charges, **210 of 210 on HSX joined, 0 of 13 on HNXDS**. The
    derivatives half of "every charge is debited from the pool it belongs to"
    is vacuous, because the journal builds those rows from ``DepositEntry``,
    which carries ``(ts, amount, reason, balance_after)`` and no typed charge
    reference. Finding 2 put the kind in the reason, where it is legible; the
    fields are still empty. Closing it needs either a field on
    ``DepositEntry`` or a parse in ``validation/journal.py``, and both are
    outside this scenario's ownership -- so the substance is checked directly
    instead, in ``test_no_charge_is_debited_from_the_wrong_pool``.

11. **OPEN -- the equity leg pays no custody fee.** ``vsdc_custody_equity`` is
    a dated rule across this whole window, ``0.27d per unit per month``, and
    every charge whose ``debited_at`` is ``MONTHLY`` has no call site, so it
    is never levied. On the 9,000 shares this run holds that is 2,430d a month
    -- immaterial beside 2,784,286d of transaction charges here, and linear in
    the size of the book. The derivatives position-management fee is correctly
    absent for a different reason: its interval ended on 2022-01-01 and
    ``vsdc_derivatives_clearing`` replaced it, which this run does levy.

Read :func:`findings` for the same list as data, and :func:`main` prints the
whole report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from plutus.market.session.types import Pool, Venue

from validation.corpus import corpus_root, datahub_source
from validation.logs import CashMovement, TradeAction
from validation.runner import (Scenario, ScenarioResult, Window, build_session,
                               run_scenario, sessions_from_source)
from validation.strategy import BaseStrategy

__all__ = [
    # -- the window ---------------------------------------------------------
    'WINDOW_START', 'WINDOW_END', 'FUTURE', 'BASKET', 'SHARES_PER_NAME',
    'CONTRACTS', 'ENTER_A', 'EXIT_A', 'SWEEP', 'ENTER_B', 'DEPOSIT_A',
    'DEPOSIT_B', 'INITIAL_CASH', 'BROKER_PROFILE', 'LADDER',
    # -- the algorithms -----------------------------------------------------
    'PairTrade', 'BareCure', 'VenueRules', 'BreachThenClose',
    # -- the runs -----------------------------------------------------------
    'build_scenario', 'run', 'run_bare_cure', 'run_venue_rules',
    'run_hard_arm', 'run_breach_then_close', 'trading_sessions',
    # -- readers ------------------------------------------------------------
    'LadderStep', 'ladder', 'fills_by_venue', 'charge_totals',
    'derivatives_fee_statement', 'reconciliation', 'basis_series',
    # -- independent arithmetic ---------------------------------------------
    'independent_requirement', 'PUBLISHED_FINAL_SETTLEMENT',
    'CLOSE_PROXY_SETTLEMENT', 'findings', 'main',
]

_ZERO = Decimal('0')
_D = Decimal


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------

WINDOW_START = date(2022, 10, 21)
WINDOW_END = date(2022, 11, 17)

#: Front month for the whole window; expires on the last session of it.
FUTURE = 'VN30F2211'

#: The VN30 as constituted at the 2022-08-01 review, which is the list in force
#: for every session of this window. Read from ``quote_vn30.parquet``, not
#: recalled: the corpus carries twelve review snapshots and this is the last.
#:
#: It is a **proxy basket and not the index**. Equal *lots* is not equal
#: weight, let alone the free-float capitalisation weighting with a 10%
#: single-stock cap that HOSE actually publishes -- the corpus has no
#: shares-outstanding data, so the real weights are not derivable here. An
#: equal-weight 30-name basket tracks the index at R^2 0.98 and drifts about
#: 5 percentage points over five months. Nothing in this scenario claims the
#: basket hedges the index; it claims the two legs route, fund and charge
#: correctly, which is a different question.
BASKET: Tuple[str, ...] = (
    'ACB', 'BID', 'BVH', 'CTG', 'FPT', 'GAS', 'GVR', 'HDB', 'HPG', 'KDH',
    'MBB', 'MSN', 'MWG', 'NVL', 'PDR', 'PLX', 'POW', 'SAB', 'SSI', 'STB',
    'TCB', 'TPB', 'VCB', 'VHM', 'VIB', 'VIC', 'VJC', 'VNM', 'VPB', 'VRE',
)

#: Three HOSE board lots of each name. At 2022-10-21 closes that is
#: 411,750,000d against 4 x 98,500,000d = 394,000,000d of futures notional --
#: a 1.045 hedge ratio, and the closest whole-lot pairing available. One lot of
#: each name is 137,250,000d, i.e. 1.39 contracts, so the pair cannot be
#: lot-matched below three lots.
SHARES_PER_NAME = 300
CONTRACTS = 4

ENTER_A = date(2022, 10, 21)
EXIT_A = date(2022, 10, 27)
SWEEP = date(2022, 10, 28)
ENTER_B = date(2022, 11, 10)

#: Deposit targets. A is comfortable: 51,220,000d of initial margin against
#: 80,000,000d is 0.6408, and the leg never leaves ``ok`` until the basis
#: snaps back on 2022-10-27. B is thin on purpose -- 47,465,600d against
#: 62,000,000d is 0.7664 -- so that the 2022-11-16 limit-up move crosses the
#: forced rung and the ladder is exercised rather than asserted.
DEPOSIT_A = _D('80000000')
DEPOSIT_B = _D('62000000')

#: 600,000,000d, and the derivatives deposit opens at **zero**. Every dong the
#: deposit ever holds therefore arrived through ``ExchangeSession.transfer``,
#: which is what makes ``deposit_segregation`` a total audit of this run rather
#: than a partial one.
INITIAL_CASH = _D('600000000')

#: The ladder is pinned rather than defaulted. ``BrokerTerms`` and the shipped
#: ``PLUTUS_DEFAULT`` profile disagree at the top rung (1.00 against 0.95), so
#: a scenario that asserts *which rung fired on which day* has to say which
#: ladder it ran, and ``provenance()`` records it.
LADDER: Mapping[str, str] = {
    'warning_utilisation': '0.80',
    'margin_call_utilisation': '0.90',
    'forced_close_utilisation': '1.00',
}

#: Two commission rows on two venues, with two different bases, because that is
#: the point: a Vietnamese desk pays a percentage of consideration on HOSE and
#: a flat fee per contract on HNX-DS, and a simulator that charged one schedule
#: for both would hide the difference the scenario exists to show.
BROKER_PROFILE: Mapping[str, Any] = {
    'name': 'pair-desk',
    **LADDER,
    'commission': (
        {'venue': 'HSX', 'base': 'trade_value', 'rate': '0.0015'},
        {'venue': 'HNXDS', 'base': 'per_contract', 'amount': '5000'},
    ),
}

#: The published VSD final settlement price for VN30F2211, read from this
#: corpus: ``quote_settlementprice.parquet``, ``VN30INDEX``, last tick of
#: 2022-11-17 at 14:45:12. The exchange strikes it from the underlying's
#: closing period, not from the futures close.
PUBLISHED_FINAL_SETTLEMENT = _D('972.78')

#: What the session settled at instead -- the futures close on the expiry day,
#: reported as ``SettlementSource.CLOSE_PROXY`` with ``substituted=True``.
CLOSE_PROXY_SETTLEMENT = _D('972.5')

#: ``vsd_initial_margin`` for VN30F over this window, from ``rulebook.py``.
#: 0.17 only from 2022-12-15, which is after this window closes.
IM_RATE = _D('0.13')
MULTIPLIER = _D('100000')


# --------------------------------------------------------------------------
# The algorithms
# --------------------------------------------------------------------------

class PairTrade(BaseStrategy):
    """Long the VN30 proxy basket on HSX, short VN30F on HNXDS.

    A caller of the exchange and nothing more: it holds no cash, computes no
    P&L and reads every position back off the session. What makes it a *pair*
    trade is entirely in this class -- **the exchange has no notion of a
    pair**, and the two legs draw on two pools with independent purchasing
    power, so keeping them together is the caller's job and failing to is the
    caller's loss.

    Three behaviours are the scenario:

    * it **funds the futures leg on demand**. The deposit opens empty, the
      first futures order is refused, and the strategy reads
      ``funded_in_aggregate`` off the refusal and transfers. It transfers to a
      *target*, not to the printed ``shortfall`` -- see :class:`BareCure` for
      what obeying the printed cure literally does.
    * it **abandons the pair rather than half-filling it**. If the futures leg
      cannot be funded even in aggregate, the equity orders accepted moments
      earlier are cancelled. A naked 411,750,000d basket is not a hedged
      position with a missing leg; it is a different trade.
    * it **does not answer margin calls**. The second leg is sized to breach
      and the run is what an unanswered call looks like. That is annotated at
      the call, so a reader of the log can tell a deliberate breach from an
      accident.
    """

    name = 'vn30-basket-vs-vn30f'

    def __init__(self, *, deposit_a: Decimal = DEPOSIT_A,
                 deposit_b: Decimal = DEPOSIT_B,
                 obey_printed_cure: bool = False) -> None:
        self.deposit_a = deposit_a
        self.deposit_b = deposit_b
        self.obey_printed_cure = obey_printed_cure
        #: Every funding refusal the futures leg produced, in order.
        self.refusals: List[Any] = []
        #: Order ids of equity legs cancelled because the pair could not be
        #: completed.
        self.abandoned: List[str] = []

    # -- helpers ---------------------------------------------------------

    def _target(self, today: date) -> Decimal:
        return self.deposit_a if today == ENTER_A else self.deposit_b

    def _fund(self, ctx, refusal, today: date) -> bool:
        """Move cash into the deposit. ``True`` if anything moved."""
        if not refusal.detail.get('funded_in_aggregate'):
            return False
        if self.obey_printed_cure:
            amount = refusal.detail['shortfall']
        else:
            amount = self._target(today) - ctx.margin().deposit_balance
        if amount <= _ZERO:
            return False
        outcome = ctx.transfer(Pool.SECURITIES, Pool.DERIVATIVES, amount)
        return hasattr(outcome, 'amount')

    def _abandon(self, ctx) -> None:
        """Cancel every live equity order: the pair could not be completed."""
        for record in ctx.live_orders():
            if record.venue is Venue.HNXDS:
                continue
            outcome = ctx.cancel(record.order_id)
            if hasattr(outcome, 'cancelled_quantity'):
                self.abandoned.append(record.order_id)

    # -- hooks -----------------------------------------------------------

    def on_events(self, ctx, events) -> None:
        for event in events:
            kind = event.kind.value
            if kind in ('margin_call', 'forced_liquidation'):
                ctx.note(
                    f'{kind} not answered; this leg is sized to breach',
                    utilisation=event.detail.get('utilisation'),
                    cure_by=event.detail.get('cure_by'),
                    executed=event.detail.get('executed'))

    def on_session(self, ctx) -> None:
        today = ctx.today
        if today in (ENTER_A, ENTER_B):
            self._enter(ctx, today)
        elif today == EXIT_A:
            self._exit(ctx)
        elif today == SWEEP:
            self._sweep(ctx)

    # -- the three actions -----------------------------------------------

    def _enter(self, ctx, today: date) -> None:
        for ticker in BASKET:
            price = ctx.price(ticker)
            if price is None:                  # pragma: no cover - corpus is
                continue                       # complete over this window
            ctx.buy(ticker, SHARES_PER_NAME, limit_price=price)

        price = ctx.price(FUTURE)
        outcome = ctx.sell(FUTURE, CONTRACTS, limit_price=price)
        if hasattr(outcome, 'venue'):
            return

        self.refusals.append(outcome)
        ctx.note('the futures leg was refused on its own pool',
                 rule=getattr(outcome.rule, 'value', outcome.rule),
                 short_pool=getattr(outcome.detail.get('short_pool'), 'value',
                                    None),
                 shortfall=outcome.detail.get('shortfall'),
                 other_pool_available=outcome.detail.get(
                     'other_pool_available'),
                 funded_in_aggregate=outcome.detail.get('funded_in_aggregate'),
                 auto_transfer=outcome.detail.get('auto_transfer'),
                 cure=outcome.detail.get('cure'))

        if not self._fund(ctx, outcome, today):
            ctx.note('the pair cannot be funded even in aggregate; '
                     'cancelling the equity leg rather than holding it naked',
                     equity_orders=len([r for r in ctx.live_orders()
                                        if r.venue is not Venue.HNXDS]))
            self._abandon(ctx)
            return

        again = ctx.sell(FUTURE, CONTRACTS, limit_price=price)
        if not hasattr(again, 'venue'):        # pragma: no cover - defensive
            ctx.note('the futures leg was refused after funding',
                     rule=getattr(again.rule, 'value', again.rule))
            self._abandon(ctx)

    def _exit(self, ctx) -> None:
        for ticker in BASKET:
            holding = ctx.holdings(ticker)
            if holding.sellable:
                ctx.sell(ticker, holding.sellable, limit_price=ctx.price(ticker))
        position = ctx.positions().get(FUTURE)
        if position is not None and position.net_quantity:
            ctx.buy(FUTURE, abs(position.net_quantity),
                    limit_price=ctx.price(FUTURE))

    def _sweep(self, ctx) -> None:
        """Take the deposit back to securities now that the leg is flat.

        The reverse direction of the segregation, and it is *not* symmetric
        with the way in: ``transfer_out`` is bounded by the withdrawal test --
        assets less the requirement at the broker's forced-close rung -- not by
        ``free_deposit``. With the position flat there is no requirement, so
        the whole balance is withdrawable and the deposit returns to zero.
        """
        free = ctx.margin().free_deposit
        if free > _ZERO:
            ctx.transfer(Pool.DERIVATIVES, Pool.SECURITIES, free)


class BareCure(BaseStrategy):
    """Obey the printed ``cure`` string literally, and nothing else.

    ``_annotate_segregation`` tells a refused caller
    ``transfer(securities -> derivatives, <shortfall>) and resubmit``. This
    strategy does exactly that. Finding 3: the resulting account is
    ``FORCED`` on the same session, because ``shortfall`` is the margin alone
    -- the fill's charges come out of the same deposit, and the admission test
    is exclusive at the rung while the status test is inclusive.
    """

    name = 'bare-cure'

    def __init__(self) -> None:
        self.refusal: Optional[Any] = None
        self.transferred: Optional[Decimal] = None

    def on_session(self, ctx) -> None:
        if ctx.today != ENTER_A or ctx.positions().get(FUTURE):
            return
        price = ctx.price(FUTURE)
        outcome = ctx.sell(FUTURE, CONTRACTS, limit_price=price)
        if hasattr(outcome, 'venue'):          # pragma: no cover - defensive
            return
        self.refusal = outcome
        self.transferred = outcome.detail['shortfall']
        ctx.transfer(Pool.SECURITIES, Pool.DERIVATIVES, self.transferred)
        ctx.sell(FUTURE, CONTRACTS, limit_price=price)


class VenueRules(BaseStrategy):
    """One order per rule per venue, so the verdicts can be compared in pairs.

    Nothing here is meant to fill. Each order exists to make the session state
    which venue's rule bound it, and the interesting rows are the ones where
    two orders differing only in the venue get opposite verdicts.
    """

    name = 'venue-rules'

    def __init__(self, equity: str = 'ACB') -> None:
        self.equity = equity
        #: ``{label: Accepted | Rejected}``, in submission order.
        self.verdicts: Dict[str, Any] = {}

    def on_session(self, ctx) -> None:
        if self.verdicts:
            return
        equity_price = ctx.price(self.equity)
        futures_price = ctx.price(FUTURE)
        equity_state = ctx.market(self.equity)
        futures_state = ctx.market(FUTURE)
        self.bands = {
            self.equity: (equity_state.reference, equity_state.ceiling,
                          equity_state.floor, equity_state.band_source.value),
            FUTURE: (futures_state.reference, futures_state.ceiling,
                     futures_state.floor, futures_state.band_source.value),
        }
        self.instruments = {
            self.equity: ctx.instrument(self.equity),
            FUTURE: ctx.instrument(FUTURE),
        }

        # No short selling of stock in Vietnam. The only construction that
        # monetises a -3.27% futures discount is unavailable, and this is the
        # order that proves the simulator refuses it.
        self.verdicts['naked_short'] = ctx.sell(
            self.equity, SHARES_PER_NAME, limit_price=equity_price)

        # Lot: 100 on HSX, 1 on HNXDS. Same number, opposite verdicts.
        self.verdicts['equity_qty_3'] = ctx.buy(
            self.equity, 3, limit_price=equity_price)
        self.verdicts['futures_qty_3'] = ctx.sell(
            FUTURE, 3, limit_price=futures_price)

        # Tick: ACB at 20.4 sits in HOSE's 10-50 band and moves on 0.05;
        # VN30F moves on 0.1 everywhere. Same trailing digit, opposite
        # verdicts, and the futures refusal names 0.1 as the constraint.
        self.verdicts['equity_half_tick'] = ctx.buy(
            self.equity, 100, limit_price=equity_price + _D('0.05'))
        self.verdicts['futures_half_tick'] = ctx.sell(
            FUTURE, 1, limit_price=futures_price + _D('0.05'))

        # Band: both venues run +-7% here, but each refuses against its own
        # published number rather than against a shared one.
        self.verdicts['equity_above_ceiling'] = ctx.buy(
            self.equity, 100, limit_price=equity_state.ceiling + _D('0.05'))
        self.verdicts['futures_below_floor'] = ctx.sell(
            FUTURE, 1, limit_price=futures_state.floor - _D('0.1'))


class BreachThenClose(BaseStrategy):
    """Open a short into the squeeze, then try to close it every session.

    The regression for finding 1. Funded at 48,000,000d, four short contracts
    from 2022-11-10 are ``forced`` at 1.2273 on 2022-11-11 with
    ``free_deposit`` at **-820,733d**, and the closing buy reserves *nothing*.
    Before the fix that order was refused on the funding gate and the position
    could not be closed until the market had cured the breach by itself.
    """

    name = 'breach-then-close'

    def __init__(self) -> None:
        #: ``[(date, utilisation, status, free_deposit, outcome)]``
        self.attempts: List[Tuple[date, Optional[Decimal], str, Decimal,
                                  Any]] = []

    def on_session(self, ctx) -> None:
        price = ctx.price(FUTURE)
        if price is None:                      # pragma: no cover
            return
        position = ctx.positions().get(FUTURE)
        if position is None or not position.net_quantity:
            if not self.attempts:
                ctx.sell(FUTURE, CONTRACTS, limit_price=price)
            return
        view = ctx.margin()
        outcome = ctx.buy(FUTURE, abs(position.net_quantity), limit_price=price)
        self.attempts.append((ctx.today, view.utilisation, view.status.value,
                              view.free_deposit, outcome))


# --------------------------------------------------------------------------
# The runs
# --------------------------------------------------------------------------

def _source(root: Optional[Any] = None) -> Any:
    return datahub_source(root)


def trading_sessions(source: Any, start: date = WINDOW_START,
                     end: date = WINDOW_END) -> Tuple[date, ...]:
    """The sessions the corpus carries for the front-month contract.

    Keyed on ``VN30F2211`` rather than on an equity name deliberately: the
    contract is listed for every session of this window and delisted after it,
    so the run cannot accidentally step past the expiry.
    """
    return sessions_from_source(source, FUTURE, start, end)


def build_scenario(*, source: Any = None, root: Optional[Any] = None,
                   strategy: Any = None, name: str = 'pair-trade',
                   start: date = WINDOW_START, end: date = WINDOW_END,
                   sessions: Sequence[date] = (),
                   tickers: Sequence[str] = (),
                   initial_cash: Any = INITIAL_CASH,
                   initial_deposit: Any = '0',
                   fill_policy: str = 'soft',
                   broker_profile: Optional[Mapping[str, Any]] = None,
                   ) -> Scenario:
    """One two-venue scenario, built the supported way.

    ``venues=['HSX', 'HNXDS']`` is the whole multi-exchange configuration:
    routing is per ``(ticker, ts)`` through the session's ``SymbolRouter``,
    the pool follows the venue, and neither leg knows the other exists.
    """
    src = source if source is not None else _source(root)
    days = tuple(sessions) or trading_sessions(src, start, end)
    watched = tuple(tickers) or (BASKET + (FUTURE,))
    profile = dict(BROKER_PROFILE if broker_profile is None else broker_profile)
    profile['commission'] = list(profile.get('commission', ()))
    window = Window(name=name, start=start, end=end, tickers=watched,
                    sessions=days, reference_ticker=FUTURE,
                    note='VN30 proxy basket on HSX against VN30F2211 on '
                         'HNXDS, over the widest front-month basis in the '
                         'corpus')
    session = build_session(
        start=start, end=end, venues=['HSX', 'HNXDS'], source=src,
        initial_cash=str(initial_cash), initial_deposit=str(initial_deposit),
        fill_policy=fill_policy, broker_profile=profile)
    return Scenario(name=name, window=window, session=session,
                    strategy=strategy if strategy is not None else PairTrade(),
                    source=src)


def run(*, source: Any = None, root: Optional[Any] = None,
        strategy: Any = None) -> Tuple[ScenarioResult, Scenario]:
    """The main run. Returns the result **and** the scenario, because the
    charge schedule and the closing balances are read off the session."""
    scenario = build_scenario(source=source, root=root, strategy=strategy)
    return run_scenario(scenario, raise_on_error=True), scenario


def run_bare_cure(*, source: Any = None, root: Optional[Any] = None
                  ) -> Tuple[ScenarioResult, Scenario]:
    """Finding 3: obey the printed ``cure`` and be forced on the same session."""
    scenario = build_scenario(
        source=source, root=root, strategy=BareCure(), name='bare-cure',
        end=date(2022, 10, 24), tickers=(FUTURE,),
        sessions=(ENTER_A, date(2022, 10, 24)))
    return run_scenario(scenario, raise_on_error=True), scenario


def run_venue_rules(*, source: Any = None, root: Optional[Any] = None,
                    equity: str = 'ACB') -> Tuple[ScenarioResult, Scenario]:
    """Each leg judged by its own venue's rules, as matched pairs of orders."""
    scenario = build_scenario(
        source=source, root=root, strategy=VenueRules(equity),
        name='venue-rules', end=date(2022, 10, 24),
        tickers=(equity, FUTURE), sessions=(ENTER_A, date(2022, 10, 24)),
        initial_deposit=str(DEPOSIT_A))
    return run_scenario(scenario, raise_on_error=True), scenario


def run_hard_arm(*, source: Any = None, root: Optional[Any] = None
                 ) -> Tuple[ScenarioResult, Scenario]:
    """Finding 5: the same pair under ``hard``, where nothing can be decided."""
    class OneOfEach(BaseStrategy):
        name = 'one-of-each'

        def on_session(self, ctx):
            if ctx.today == ENTER_A:
                ctx.buy('ACB', SHARES_PER_NAME, limit_price=ctx.price('ACB'))
                ctx.sell(FUTURE, 1, limit_price=ctx.price(FUTURE))

    scenario = build_scenario(
        source=source, root=root, strategy=OneOfEach(), name='hard-arm',
        end=date(2022, 10, 24), tickers=('ACB', FUTURE),
        sessions=(ENTER_A, date(2022, 10, 24)),
        initial_deposit=str(DEPOSIT_A), fill_policy='hard')
    return run_scenario(scenario, raise_on_error=True), scenario


def run_breach_then_close(*, source: Any = None, root: Optional[Any] = None,
                          deposit: Any = '48000000'
                          ) -> Tuple[ScenarioResult, Scenario]:
    """The regression for finding 1: can a breaching account close?"""
    days = (ENTER_B, date(2022, 11, 11), date(2022, 11, 14),
            date(2022, 11, 15), date(2022, 11, 16))
    scenario = build_scenario(
        source=source, root=root, strategy=BreachThenClose(),
        name='breach-then-close', start=days[0], end=days[-1],
        tickers=(FUTURE,), sessions=days, initial_cash='0',
        initial_deposit=str(deposit))
    return run_scenario(scenario, raise_on_error=True), scenario


# --------------------------------------------------------------------------
# Readers -- everything below reads the logs, nothing recomputes the session
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LadderStep:
    """One session's derivatives margin, as the run reported it."""

    day: date
    mark: Optional[Decimal]
    deposit_balance: Decimal
    initial_margin: Decimal
    variation_margin: Decimal
    required: Decimal
    utilisation: Optional[Decimal]
    status: str
    events: Tuple[str, ...]
    securities_cash: Decimal
    net_contracts: int


def ladder(result: ScenarioResult, *,
           marks: Optional[Mapping[date, Decimal]] = None
           ) -> Tuple[LadderStep, ...]:
    """The close-step margin view of every session, with its margin events.

    Sampled at the close rather than at both steps because the close step is
    the one whose mark is unambiguously that session's price. See finding 6
    for why the open step's mark is not an intraday number on a daily run.
    """
    by_day: Dict[date, List[str]] = {}
    for event in result.logs.events:
        if event.kind.value in ('margin_warning', 'margin_call',
                                'forced_liquidation', 'expiry_settled'):
            by_day.setdefault(event.ts.date(), []).append(event.kind.value)
    out: List[LadderStep] = []
    for snap in result.snapshots:
        if snap.phase != 'close':
            continue
        day = snap.ts.date()
        out.append(LadderStep(
            day=day,
            mark=None if marks is None else marks.get(day),
            deposit_balance=snap.deposit_balance,
            initial_margin=snap.initial_margin,
            variation_margin=snap.variation_margin,
            required=snap.margin_required,
            utilisation=snap.utilisation,
            status=snap.margin_status,
            events=tuple(by_day.get(day, ())),
            securities_cash=snap.settled_cash,
            net_contracts=snap.positions.get(FUTURE, 0)))
    return tuple(out)


def fills_by_venue(result: ScenarioResult) -> Dict[str, Dict[str, Any]]:
    """``{venue: {pool, tickers, fills, quantity}}`` off the trade log alone.

    The point of reading it from the log rather than from the router: the log
    is what an auditor has, and if the pool on a fill row were wrong the
    identity checks would still pass while the statement lied.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for entry in result.logs.trades.of(TradeAction.FILLED,
                                       TradeAction.PARTIALLY_FILLED):
        venue = entry.venue or 'UNROUTED'
        row = out.setdefault(venue, {'pool': entry.pool, 'tickers': set(),
                                     'fills': 0, 'quantity': 0,
                                     'pools': set()})
        row['tickers'].add(entry.ticker)
        row['pools'].add(entry.pool)
        row['fills'] += 1
        row['quantity'] += entry.fill_quantity or 0
    for row in out.values():
        row['tickers'] = tuple(sorted(row['tickers']))
        row['pools'] = tuple(sorted(p or '' for p in row['pools']))
    return out


def charge_totals(scenario: Scenario) -> Dict[Tuple[str, str, str, str],
                                              Tuple[int, Decimal]]:
    """``{(kind, venue, pool, base): (count, total)}`` from the session.

    ``Charge.total`` is amount plus VAT. Nothing in the Vietnamese schedule
    carried here charges VAT to the investor, so the two agree -- asserted
    rather than assumed in the test.
    """
    out: Dict[Tuple[str, str, str, str], Tuple[int, Decimal]] = {}
    for charge in scenario.session.charges():
        key = (charge.kind, charge.venue.value, charge.pool.value,
               charge.base.value)
        count, total = out.get(key, (0, _ZERO))
        out[key] = (count + 1, total + charge.total)
    return out


def derivatives_fee_statement(result: ScenarioResult
                              ) -> Tuple[Tuple[datetime, str, Decimal], ...]:
    """``(ts, charge kind, amount)`` for every derivatives fee, from the log.

    This is the row an itemised broker statement has and a single aggregated
    debit does not. It exists because it *did* not before finding 2 was fixed:
    the cause string was ``charges on FILL-000031`` for the sum of four
    separate levies.
    """
    out: List[Tuple[datetime, str, Decimal]] = []
    for entry in result.logs.cash:
        if (entry.pool != Pool.DERIVATIVES.value
                or entry.movement is not CashMovement.CHARGE_DEBITED):
            continue
        cause = entry.cause or ''
        kind = cause.split(': ', 1)[1] if ': ' in cause else ''
        out.append((entry.ts, kind, -entry.amount))
    return tuple(out)


def reconciliation(result: ScenarioResult, scenario: Scenario,
                   closing_marks: Mapping[str, Decimal]) -> Dict[str, Decimal]:
    """Every dong, twice: the balance change and its decomposition.

    ``residual`` is the whole point. It is the balance change less the four
    things that could have caused one -- equity consideration, realised
    derivatives P&L, final settlement, and charges -- and it must be exactly
    zero. Anything else means a movement happened that no log row explains.

    ``closing_marks`` is supplied by the caller because the *session* does not
    mark equity: ``Holding`` carries quantity, never value, and Plutus computes
    no P&L by design. The caller's feed prices its own book.
    """
    session = scenario.session
    cash = result.logs.cash
    opening = _movement(cash, 'securities', CashMovement.OPENING_BALANCE) + \
        _movement(cash, 'derivatives', CashMovement.OPENING_BALANCE)
    closing_cash = session.cash().settled_balance
    closing_deposit = session.margin().deposit_balance

    holdings_value = _ZERO
    for ticker in BASKET:
        quantity = session.holdings(ticker).total
        if quantity:
            holdings_value += (Decimal(quantity) * closing_marks[ticker]
                               * _D('1000'))

    buys = -_movement(cash, 'securities', CashMovement.BUY_CONSIDERATION)
    proceeds_net = _movement(cash, 'securities',
                             CashMovement.SETTLEMENT_CREDIT)
    # ``SETTLEMENT_CREDIT`` is already net of the sell-side charges, which are
    # withheld at source and logged with ``affects_balance=False``. Adding
    # them back gives the gross consideration, which is what the charge total
    # must then be subtracted from -- counting both the net credit and the
    # withheld charges is a double count of exactly the withheld amount, and
    # it shows up in ``residual`` if you do it.
    withheld = -_movement(cash, 'securities', CashMovement.CHARGE_WITHHELD)
    debited = -_movement(cash, 'securities', CashMovement.CHARGE_DEBITED)
    proceeds_gross = proceeds_net + withheld
    equity_charges = withheld + debited
    realised = _movement(cash, 'derivatives', CashMovement.REALISED_PNL)
    expiry = _movement(cash, 'derivatives', CashMovement.EXPIRY_SETTLEMENT)
    deposit_charges = -_movement(cash, 'derivatives',
                                 CashMovement.CHARGE_DEBITED)

    change = closing_cash + closing_deposit + holdings_value - opening
    explained = (proceeds_gross - buys + holdings_value + realised + expiry
                 - equity_charges - deposit_charges)
    return {
        'opening': opening,
        'closing_cash': closing_cash,
        'closing_deposit': closing_deposit,
        'closing_holdings_value': holdings_value,
        'change': change,
        'equity_bought': buys,
        'equity_sold_gross': proceeds_gross,
        'equity_sold_net': proceeds_net,
        'equity_charges_withheld': withheld,
        'equity_charges_debited': debited,
        'equity_charges': equity_charges,
        'derivatives_realised': realised,
        'derivatives_expiry': expiry,
        'derivatives_charges': deposit_charges,
        'explained': explained,
        'residual': change - explained,
    }


def _movement(cash: Any, pool: str, movement: CashMovement) -> Decimal:
    return cash.by_movement(pool).get(movement, _ZERO)


def basis_series(source: Any, start: date = WINDOW_START,
                 end: date = WINDOW_END) -> Dict[date, Tuple[Decimal, Decimal,
                                                             Decimal]]:
    """``{day: (futures, VN30, basis)}`` -- the trade's own signal.

    Read from the same source the session reads, so the strategy and the
    exchange cannot disagree about what the market did. ``VN30`` is an index
    and the corpus carries no band for it, which is why it is never submitted
    as an order: it is a level, not an instrument.
    """
    from validation.corpus import closes
    futures = closes(source, FUTURE, start, end)
    index = closes(source, 'VN30', start, end)
    out: Dict[date, Tuple[Decimal, Decimal, Decimal]] = {}
    for day, price in sorted(futures.items()):
        spot = index.get(day)
        if price is None or spot is None:
            continue
        out[day] = (price, spot, price - spot)
    return out


# --------------------------------------------------------------------------
# Independent arithmetic -- deliberately not the session's code
# --------------------------------------------------------------------------

def independent_requirement(marks: Sequence[Tuple[date, Decimal]], *,
                            net_contracts: int, entry_price: Decimal,
                            deposit: Decimal, rate: Decimal = IM_RATE,
                            multiplier: Decimal = MULTIPLIER,
                            warning: Decimal = _D('0.80'),
                            call: Decimal = _D('0.90'),
                            forced: Decimal = _D('1.00'),
                            ) -> Tuple[Dict[str, Any], ...]:
    """The ladder recomputed from the rulebook, without touching ``deposit.py``.

    ``IM = rate x |net| x multiplier x price``; ``VM = max(0, -P&L)`` measured
    **from the entry price**, because the variation-margin baseline is only
    moved by ``settle_daily`` and that has no session call site (finding 8);
    ``MR = IM + VM``; ``utilisation = MR / deposit``. A test that asserted the
    session's numbers against the session's own function would prove nothing.
    """
    out: List[Dict[str, Any]] = []
    quantity = Decimal(abs(net_contracts))
    for day, price in marks:
        initial = rate * quantity * multiplier * price
        pnl = Decimal(net_contracts) * multiplier * (price - entry_price)
        variation = -pnl if pnl < _ZERO else _ZERO
        required = initial + variation
        utilisation = required / deposit if deposit > _ZERO else None
        if utilisation is None:
            status = 'ok'
        elif utilisation >= forced:
            status = 'forced'
        elif utilisation >= call:
            status = 'call'
        elif utilisation >= warning:
            status = 'warning'
        else:
            status = 'ok'
        out.append({'day': day, 'mark': price, 'initial_margin': initial,
                    'variation_margin': variation, 'required': required,
                    'utilisation': utilisation, 'status': status})
    return tuple(out)


# --------------------------------------------------------------------------
# Findings, as data
# --------------------------------------------------------------------------

def findings() -> Tuple[Dict[str, Any], ...]:
    """The nine, in descending order of what they would cost a believer."""
    return (
        {'id': 'PT-1', 'status': 'fixed', 'severity': 'high',
         'where': 'src/plutus/market/session/deposit.py '
                  'DerivativesAccount.reserve_for_order',
         'what': 'a breaching account could not close its position: an '
                 'offsetting order reserves nothing, and "required > '
                 'free_deposit" is True whenever free_deposit is negative, '
                 'which is exactly the breach state',
         'evidence': '4 short VN30F2211 from 2022-11-10 on a 48,000,000d '
                     'deposit: forced at utilisation 1.2278 on 2022-11-11 '
                     'with free_deposit -840,733d, closing buy '
                     'Rejected(INSUFFICIENT_DEPOSIT, required=0.000); refused '
                     'again 2022-11-14 at 1.1712; admitted 2022-11-15 only '
                     'after the mark had cured the breach. After the fix the '
                     'position closes on the first attempt, 2022-11-11',
         'fix': 'guard the funding test with "required > 0"',
         'regression': 'run_breach_then_close'},
        {'id': 'PT-2', 'status': 'fixed', 'severity': 'medium',
         'where': 'src/plutus/market/session/exchange.py _debit_charges',
         'what': 'the derivatives pool had no itemised fee statement: the '
                 'only cash journal the deposit has recorded one aggregate '
                 'debit per fill, so four levies by four parties appeared as '
                 'one number and could not be reconciled against '
                 'session.charges()',
         'evidence': 'one DepositEntry "charges on FILL-000031" for -66,610d '
                     'standing for 25,610 PIT + 10,800 HNX + 10,200 VSDC + '
                     '20,000 broker; the securities pool already itemised',
         'fix': 'one debit per charge, each reason naming the kind',
         'regression': 'derivatives_fee_statement'},
        {'id': 'PT-3', 'status': 'open', 'severity': 'high',
         'where': 'src/plutus/market/session/exchange.py '
                  '_annotate_segregation, with deposit.py reserve_for_order',
         'what': 'the printed cure understates the transfer needed, and the '
                 'admission boundary is exclusive while the status boundary '
                 'is inclusive, so obeying the cure literally is forced '
                 'liquidation on the same session',
         'evidence': 'cure "transfer(securities -> derivatives, 51220000.000) '
                     'and resubmit" on 2022-10-21; the deposit lands at '
                     'utilisation exactly 1 and status forced before any '
                     'charge is levied, and after the fill it is 51,153,390d '
                     'against 51,220,000d of IM, utilisation 1.0013',
         'fix': None,
         'regression': 'run_bare_cure'},
        {'id': 'PT-4', 'status': 'open', 'severity': 'medium',
         'where': 'src/plutus/market/session/ledgers.py '
                  'SecuritiesAccount.reserve_for_sell',
         'what': 'a naked short -- no position at all -- is refused under '
                 'unsettled_holding, so the rejection log cannot count "wait '
                 'for T+2" apart from "Vietnam has no stock short selling"',
         'evidence': "sell ACB 300 with no holding: Rejected(UNSETTLED_"
                     "HOLDING, binding_constraint=0, sellable_from=None, "
                     "detail={'requested': 300, 'settled': 0, 'committed': 0, "
                     "'unsettled': 0}). The outcome is right and the detail "
                     'distinguishes the two cases; the rule does not',
         'fix': None,
         'regression': 'run_venue_rules'},
        {'id': 'PT-5', 'status': 'open', 'severity': 'high',
         'where': 'src/plutus/market/session/fills.py HardFillPolicy, with '
                  'adapters/datahub.py',
         'what': 'neither leg of this pair can be adjudicated on the daily '
                 'corpus, and indeterminate_report().by_field is empty, so a '
                 'report cannot even name the field that was missing',
         'evidence': 'hard arm over 2022-10-21: 2 of 3 evaluations '
                     'INDETERMINATE (rate 0.6667), by_field {}, by_rule {}, '
                     'both orders expire unfilled, missing_fields empty on '
                     'the INDETERMINATE trade rows. Every fill in the main '
                     'run is therefore a soft model output, not an '
                     'observation',
         'fix': None,
         'regression': 'run_hard_arm'},
        {'id': 'PT-6', 'status': 'open', 'severity': 'medium',
         'where': 'src/plutus/market/session/exchange.py _interval_for and '
                  '_mark_derivatives',
         'what': 'on a daily run the 09:30 margin mark is the same session\'s '
                 'close, so a margin event timestamped 09:30 rests on '
                 'information nobody had at 09:30',
         'evidence': 'margin_warning 2022-10-27 09:30 at utilisation 0.8670, '
                     'computed from IM 53,300,000d = 0.13 x 4 x 100,000 x '
                     '1025.0, which is that session\'s close',
         'fix': None,
         'regression': 'ladder'},
        {'id': 'PT-7', 'status': 'open', 'severity': 'high',
         'where': 'src/plutus/market/session/exchange.py _mark_derivatives',
         'what': 'FORCED_LIQUIDATION reports and does not execute, so the '
                 'breach persists and the event repeats at every mark',
         'evidence': "six forced_liquidation events in the main run, every "
                     "one detail['executed'] is False; the account is still "
                     'short 4 contracts at the 2022-11-17 expiry and settles '
                     'them in cash',
         'fix': None,
         'regression': 'ladder'},
        {'id': 'PT-8', 'status': 'open', 'severity': 'high',
         'where': 'src/plutus/market/session/deposit.py settle_daily, no call '
                  'site',
         'what': 'variation margin never settles in cash and the VM baseline '
                 'never rolls, so the deposit is flat between fills and VM '
                 'accrues from the entry price rather than from yesterday\'s '
                 'settlement',
         'evidence': 'deposit 61,935,267d on all six sessions of the second '
                     'leg while utilisation went 0.7664 -> 1.2021; the whole '
                     '23,880,000d loss arrives as one movement at expiry',
         'fix': None,
         'regression': 'ladder'},
        {'id': 'PT-9', 'status': 'open', 'severity': 'medium',
         'where': 'src/plutus/market/adapters/datahub.py, no settlement-price '
                  'reader',
         'what': 'the published final settlement price is in this corpus and '
                 'the session settled on the close proxy instead',
         'evidence': 'quote_settlementprice.parquet carries VN30INDEX for '
                     '2022-08-17..2022-12-15; 180 ticks on 2022-11-17 running '
                     '14:15:01..14:45:12 and the last is 972.78. The run '
                     'settled at the futures close 972.5, reported as '
                     'settlement_source=close_proxy with substituted=True: '
                     '0.28 x 4 x 100,000 = 112,000d of loss not booked',
         'fix': None,
         'regression': 'PUBLISHED_FINAL_SETTLEMENT'},
        {'id': 'PT-10', 'status': 'open', 'severity': 'medium',
         'where': 'validation/identities.py deposit_segregation, with '
                  'validation/journal.py drain_deposit',
         'what': 'the identity that claims "every charge is debited from the '
                 'pool it belongs to" joins the cash log on charge_kind and '
                 'fill_id, and the derivatives cash rows carry neither, so '
                 'the derivatives half of it checks nothing and passes '
                 'vacuously',
         'evidence': 'main run: 223 charges on the session, 210 of 210 HSX '
                     'charges joined by the identity and 0 of 13 HNXDS. '
                     'Itemising the debits (PT-2) put the kind in the cause '
                     'string, which is where it is legible, but DepositEntry '
                     'carries only (ts, amount, reason, balance_after) so the '
                     'typed fields stay None',
         'fix': 'either DepositEntry grows a charge reference, or the journal '
                'parses the kind out of the reason it already records. Both '
                'are outside this scenario: deposit.py is under concurrent '
                'edit and journal.py is shared harness. The substance is '
                'checked directly by '
                'test_no_charge_is_debited_from_the_wrong_pool',
         'regression': 'test_no_charge_is_debited_from_the_wrong_pool'},
        {'id': 'PT-11', 'status': 'open', 'severity': 'low',
         'where': 'src/plutus/market/session/exchange.py, no daily or monthly '
                  'charge pass',
         'what': 'the equity leg pays no custody fee: vsdc_custody_equity is '
                 'a dated rule over this whole window and every charge with '
                 'debited_at=MONTHLY has no call site, so a cost model built '
                 'on this run understates the cost of holding',
         'evidence': 'rulebook at 2022-10-21 carries vsdc_custody_equity '
                     '(monthly_per_security, 0.27d per unit per month) for '
                     'HSX equity; session.charges() contains none of it. On '
                     'the 9,000 shares this run holds that is 2,430d a month '
                     '-- immaterial beside 2,784,286d of transaction charges '
                     'here, and linear in the size of the book. The '
                     'derivatives position-management fee is correctly absent '
                     'for a different reason: its interval ended 2022-01-01 '
                     'and vsdc_derivatives_clearing replaced it',
         'fix': None,
         'regression': 'test_the_holding_charges_are_never_levied'},
    )


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def main() -> int:                             # pragma: no cover - report
    if corpus_root() is None:
        print('no daily corpus on this machine; set PLUTUS_DATA_ROOT')
        return 1
    source = _source()
    result, scenario = run(source=source)
    print(result.summary())

    print('\nbasis (futures - VN30)')
    for day, (fut, spot, spread) in basis_series(source).items():
        flag = ''
        if day in (ENTER_A, ENTER_B):
            flag = '  <- enter'
        elif day == EXIT_A:
            flag = '  <- exit'
        print(f'  {day}  {fut:>8}  {spot:>8}  {spread:>8}{flag}')

    print('\nrouting')
    for venue, row in sorted(fills_by_venue(result).items()):
        print(f'  {venue:<6} pool={row["pools"]} fills={row["fills"]:>3} '
              f'quantity={row["quantity"]:>7} names={len(row["tickers"])}')

    print('\ncharges')
    for key, (count, total) in sorted(charge_totals(scenario).items()):
        kind, venue, pool, base = key
        print(f'  {kind:<34} {venue:<6} {pool:<12} {base:<13} '
              f'n={count:<3} {total:>12}')

    print('\nderivatives margin ladder')
    for step in ladder(result):
        util = '' if step.utilisation is None else f'{step.utilisation:.4f}'
        print(f'  {step.day}  dep={step.deposit_balance:>14} '
              f'IM={step.initial_margin:>14} VM={step.variation_margin:>12} '
              f'util={util:>7} {step.status:<8} {",".join(step.events)}')

    print('\nreconciliation')
    from validation.corpus import closes
    marks = {t: closes(source, t, WINDOW_END, WINDOW_END)[WINDOW_END]
             for t in BASKET}
    for key, value in reconciliation(result, scenario, marks).items():
        print(f'  {key:<26} {value:>20}')

    print('\nidentities')
    for row in result.identities:
        print(f'  {"OK " if row.passed else "FAIL"} {row.name}')

    print('\nfindings')
    for finding in findings():
        print(f'  [{finding["status"]:<5}] {finding["id"]} '
              f'({finding["severity"]}) {finding["what"]}')
    return 0 if result.ok else 2


if __name__ == '__main__':                     # pragma: no cover
    raise SystemExit(main())
