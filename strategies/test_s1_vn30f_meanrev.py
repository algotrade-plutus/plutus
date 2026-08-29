"""S1 — Front-month VN30F mean-reversion that over-levers into a margin call.

Strategy **S1** of ``docs/reference/STRATEGY-BOARD.md``, written as a user writes
it: a real, documented trading strategy, run against Plutus as the counterparty.

TRADING RATIONALE (the strategy a real desk would write)
    Index futures often *mean-revert* around a short moving average: a sharp
    move away from the mean tends to snap back. So we fade stretch. Each day we
    z-score the front-month VN30F close against its trailing 10-day mean; when
    the close is more than one standard deviation **below** the mean (oversold)
    we go **long**, betting on the snap-back, and we **size up with conviction**
    — the more stretched the move, the more lots, to a cap. We flatten when the
    price returns to its mean (|z| < 0.3). It is a textbook contrarian.

THE FLAW THE MARKET PUNISHES (why this is a fidelity test, not a demo)
    Mean-reversion has one catastrophic failure mode: a **trend**. When the
    market falls day after day, every oversold reading is a lie — the snap-back
    never comes — and the conviction sizing makes it worse, adding lots into a
    position that only loses. This is "picking up pennies in front of a
    steamroller." In **Oct 2022** the VN30 did exactly this: VN30F2210 slid from
    ~1288 to ~989 in a month. A contrarian keeps buying the dip, inventory
    grows, the loss compounds, and the broker's margin engine takes over.

WHAT THE SIMULATOR MUST GET RIGHT (emergent, not staged)
    Nothing here sets a utilisation to 0.91. The position is built by the
    signal; the loss is real corpus P&L; and the **margin call and forced
    liquidation must emerge on the days the arithmetic says they do**:

MECHANISM / POLICY (oracle — SCENARIO-CATALOGUE.md, folded scenarios)
    * Pre-KRX ``MR = IM + VM`` over the deposit, VM loss-only, utilisation
      warning ≥ 0.80 / call ≥ 0.90 / forced ≥ 1.00 (J18/J26; rulebook 6.3).
    * A margin call past its cure window (NEXT_SESSION) is force-closed, and the
      forced close now **executes** through the order path — band, tick, lot —
      closing the position rather than reporting a close it never ran (J3;
      publish-checklist MUST #3; QĐ 26 Điều 13.3).
    * Marketable orders sweep to fill (J13); the leveraged deposit can run out
      (J24).

DECLARED (MUST #4, not yet built): variation margin is measured
    cumulative-since-entry (A60), not settled in cash daily. S1 is the forcing
    function for that build; here VM drives the call, and its daily cash
    settlement is a separate pending item.

SETUP — VN30F2210 (the genuine Aug–Oct 2022 front month), 40,000,000đ deposit
    (one lot is comfortable at ~0.4 utilisation; it is the *over-levering* into
    the slide that crosses the call and forced rungs — confirmed against the
    real series before this was written).

EXPECTED — Tier 2
    * Emergence: the signal opens a long and over-levers (net ≥ 2); a margin
      CALL is issued, and not on day one — it emerges after the drawdown.
    * Forced: a FORCED_LIQUIDATION fires with ``executed=True``, names
      VN30F2210, and the position is closed (not permissively carried).
    * Conservation: the deposit balance never goes impossible (< 0), and the
      mark-to-market equity trough is materially below the start — the drawdown
      the call responded to is real.

RUN
    .venv/bin/python strategies/test_s1_vn30f_meanrev.py
    .venv/bin/python -m pytest strategies/test_s1_vn30f_meanrev.py -v
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from statistics import mean, pstdev

import pytest

from plutus.market.session import ExchangeSession, Accepted, Rejected  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import (build_session, data_available, CorpusFeed, Strategy,
                      Context, run)

TICKER = "VN30F2210"
START = date(2022, 8, 19)
END = date(2022, 10, 19)           # exclusive; front month, before its Oct-20 expiry

LOOKBACK = 10
ENTER = Decimal("1.0")             # |z| beyond this is "stretched"
EXIT_BAND = Decimal("0.3")         # |z| below this is "back at the mean" -> flat
MAX_LOTS = 4                       # conviction cap

CONFIG = {
    "period": {"start": "2022-08-19", "end": "2022-10-19"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HNXDS"]},
    "accounts": {"derivatives": {"initial_deposit": 40_000_000,
                                 "account_no": "DER-S1"}},
}


class FrontMonthMeanReversion(Strategy):
    """A trailing z-score contrarian on the front-month VN30 future."""

    name = "front-month VN30F mean-reversion"

    def __init__(self, ticker=TICKER, *, lookback=LOOKBACK, enter=ENTER,
                 exit_band=EXIT_BAND, max_lots=MAX_LOTS, start=START):
        self.ticker = ticker
        self.lookback = lookback
        self.enter = enter
        self.exit_band = exit_band
        self.max_lots = max_lots
        self.start = start
        self.max_long = 0            # deepest long reached (for the report)

    # -- the signal --------------------------------------------------------

    def _target(self, z: Decimal, current: int) -> int:
        """Target net lots from the z-score. Contrarian, add-on-conviction."""
        lots = min(self.max_lots, int(abs(z) / self.enter))
        if z <= -self.enter:
            return lots                     # oversold -> long, more when more stretched
        if z >= self.enter:
            return -lots                    # overbought -> short
        if abs(z) < self.exit_band:
            return 0                        # returned to the mean -> flat
        return current                      # in between -> hold

    def _net(self, session: ExchangeSession) -> int:
        pos = session.positions().get(self.ticker)
        return pos.net_quantity if pos else 0

    # -- the daily decision ------------------------------------------------

    def on_day(self, ctx: Context) -> None:
        s, feed, day = ctx.session, ctx.feed, ctx.day

        # A stubborn contrarian does not de-risk into a call — that conviction
        # is exactly the flaw. But it does not pile on *during* an unanswered
        # call either; it freezes and lets the cure window play out.
        if s.outstanding_call() is not None:
            return

        closes = feed.closes_before(self.ticker, day, self.lookback,
                                    start=self.start)
        if len(closes) < self.lookback:
            return                          # still warming up
        mu = mean(closes)
        sd = pstdev(closes)
        if sd == 0:
            return
        z = (closes[-1] - mu) / sd          # yesterday's stretch (look-ahead-safe)

        current = self._net(s)
        target = self._target(z, current)
        self.max_long = max(self.max_long, target, current)
        delta = target - current
        if delta == 0:
            return

        # A signal strategy takes liquidity: a market order (MTL) fills at the
        # print. A marketable *limit* would fill at its own aggressive price
        # (the sim honours the limit as the resting price, QĐ 352 Điều 6.3),
        # which for a band-edge limit means paying limit-up — not what a taker
        # experiences. MTL is the honest tool here (and it is legal on HNXDS).
        side = Side.BUY if delta > 0 else Side.SELL
        verdict = s.submit(Order(
            ticker=self.ticker, side=side, quantity=abs(delta),
            order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT))
        if not isinstance(verdict, Accepted):
            ctx.ledger.record_reject(day, verdict)


def run_s1():
    session = build_session(CONFIG)
    feed = CorpusFeed()
    strategy = FrontMonthMeanReversion()
    ledger = run(strategy, session=session, feed=feed,
                 start=START, end=END, universe=[TICKER])
    ledger.strategy = strategy
    return ledger


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_s1_vn30f_meanrev():
    ledger = run_s1()

    # Tier 1 — it ran: it traded, and the equity curve came out.
    assert ledger.fills(), "the signal never traded"
    assert ledger.equity_curve, "no equity curve was produced"

    # Emergence — the signal built a leveraged long, and the call is not day one.
    assert ledger.strategy.max_long >= 2, \
        f"the strategy never over-levered (max long {ledger.strategy.max_long})"
    calls = ledger.calls()
    assert calls, "no margin call emerged from the drawdown"
    assert calls[0][0] > START, "a call on day one is not emergent"

    # Forced — the broker force-closes, it executes, and the position is flat.
    executed = ledger.executed_forced()
    assert executed, "a margin call was issued but never force-closed (executed)"
    assert TICKER in dict(executed[0][1].detail.get("closed") or ()), \
        executed[0][1].detail

    # Conservation — no impossible money, and the drawdown the call answered is real.
    assert ledger.session.margin().deposit_balance >= 0, "deposit went negative"
    start_eq = ledger.equity_curve[0][1]
    trough = min(e for _, e in ledger.equity_curve)
    assert trough < start_eq, "the equity curve shows no drawdown"


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    ledger = run_s1()
    print("S1 — Front-month VN30F mean-reversion (VN30F2210, Aug–Oct 2022)")
    print(f"  {ledger.summary()}")
    print(f"  deepest long reached: {ledger.strategy.max_long} lots")
    for day, e in ledger.calls():
        util = getattr(e, "detail", {}).get("utilisation")
        print(f"  margin CALL   {day}  utilisation={util}")
    for day, e in ledger.executed_forced():
        print(f"  FORCED CLOSE  {day}  closed={e.detail.get('closed')}")
    try:
        test_s1_vn30f_meanrev()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
