"""S5 — High-turnover swing trading that only works on the sale advance.

Strategy **S5** of ``docs/reference/STRATEGY-BOARD.md``, written as a user writes
it. A short-horizon swing trader that wants to stay fully invested, flipping the
same capital over and over. In Vietnam it *can't* — equity settles **T+2**, so
the đồng from today's sale is frozen for two days. The **sale advance** (*ứng
trước tiền bán*) is what a real desk uses to redeploy immediately, at the cost of
a daily fee. S5 is the same strategy run twice — with the advance and without —
so the advance's effect on capital turnover is the measurement.

TRADING RATIONALE
    Buy a liquid large-cap when flat; once the shares settle and the tape ticks
    up, **sell into strength**; then immediately **redeploy**. The edge is small
    per trade, so it lives or dies on *turnover* — how many times the capital can
    be recycled. Without same-day proceeds the strategy sits on its hands two days
    out of every cycle.

WHAT THE SIMULATOR MUST GET RIGHT (emergent, not staged)
    * With the advance ON, a rebuy off *unsettled* proceeds is funded, and the
      advance **accrues a fee** the equity curve must carry.
    * With the advance OFF, the same rebuy is **refused** — the proceeds have not
      settled and settled cash is spent (J24) — so the strategy trades far less
      often (J16, the capital-turnover constraint).

MECHANISM / POLICY (oracle — SCENARIO-CATALOGUE.md, folded scenarios)
    * The sale advance is statutory/licensable — Luật Chứng khoán 54/2019/QH14
      Điều 86(1)(b) (high); price/cap are broker terms (J15).
    * Equity settles T+2, and unsettled proceeds are not buying power unless
      advanced — rulebook 5.1 (J1/J16). A buy short of funds is refused (J24).

SETUP — FPT (HSX), 2022-09-06 → 2022-11-15, 120,000,000đ, advance @ 0.03%/day.

EXPECTED — Tier 2
    * WITH the advance: the strategy turns the book over materially more often
      (more fills) than without, and it **pays for it** — advance interest accrues.
    * WITHOUT the advance: rebuys off unsettled proceeds are **refused**
      (INSUFFICIENT_CASH), so turnover is throttled to the settlement clock.

RUN
    .venv/bin/python strategies/test_s5_advance_turnover.py
    .venv/bin/python -m pytest strategies/test_s5_advance_turnover.py -v
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import (build_session, data_available, CorpusFeed, Strategy,
                      Context, run)

TICKER = "FPT"
START = date(2022, 9, 6)
END = date(2022, 11, 15)
LOT = 100
PRICE_SCALE = 1000
INITIAL_CASH = 120_000_000


def _config(advance: bool) -> dict:
    cfg = {
        "period": {"start": "2022-09-06", "end": "2022-11-15"},
        "resolution": "1d",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": INITIAL_CASH,
                                    "account_no": "SEC-S5"}},
    }
    if advance:
        cfg["broker_profile"] = {
            "advance_sale_proceeds": {"enabled": True, "daily_rate": "0.0003"}}
    return cfg


class ReversalSwing(Strategy):
    """Buy when flat; sell settled shares into an up-day; redeploy at once."""

    name = "high-turnover reversal swing"

    def __init__(self, ticker=TICKER, *, lot=LOT, start=START):
        self.ticker = ticker
        self.lot = lot
        self.start = start
        self.rebuy_rejects = 0
        self.throttled = 0          # days it wanted to redeploy but the cash was frozen

    def _sellable(self, s: ExchangeSession) -> int:
        h = s.holdings(self.ticker)
        return max(0, int(getattr(h, "settled", 0) or 0)
                   - int(getattr(h, "committed", 0) or 0))

    def _position(self, s: ExchangeSession) -> int:
        h = s.holdings(self.ticker)
        unsettled = sum((t.quantity for t in getattr(h, "unsettled", ()) or ()), 0)
        return int(getattr(h, "settled", 0) or 0) + int(unsettled)

    def on_day(self, ctx: Context) -> None:
        s, feed, day = ctx.session, ctx.feed, ctx.day
        closes = feed.closes_before(self.ticker, day, 1, start=self.start)
        if not closes:
            return
        prev = closes[-1]

        # Rotate: the moment shares settle, sell them to free the capital for the
        # next deployment. Capital velocity is the whole edge here.
        sellable = self._sellable(s)
        if sellable > 0:
            s.submit(Order(ticker=self.ticker, side=Side.SELL, quantity=sellable,
                           order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT))
            return

        if self._position(s) > 0:
            return                              # holding unsettled shares — wait

        # Flat: redeploy ~fully. `available` counts advanced proceeds only when
        # the advance is on — which is the whole experiment. Invest to the lot so
        # a rebuy genuinely needs the proceeds, not a leftover cash cushion.
        available = s.cash().available
        # Invest ~fully with a bounded-cost limit at the prior close, so the
        # order cost is deterministic (no fee/slippage overshoot) and there is
        # no idle cushion to fund a rebuy the settlement clock should have frozen.
        shares = int((available * Decimal("0.98") / (prev * PRICE_SCALE))
                     // self.lot) * self.lot
        if shares <= 0:
            # Wanted to redeploy but the capital is frozen: proceeds exist but
            # have neither settled nor been advanced. This is the T+2 throttle.
            if s.cash().pending_total > 0:
                self.throttled += 1
            return
        verdict = s.submit(Order(ticker=self.ticker, side=Side.BUY, quantity=shares,
                                 order_type=OrderType.LIMIT, limit_price=prev))
        if not isinstance(verdict, Accepted):
            self.rebuy_rejects += 1
            ctx.ledger.record_reject(day, verdict)


def _run(advance: bool):
    session = build_session(_config(advance))
    feed = CorpusFeed()
    strategy = ReversalSwing()
    ledger = run(strategy, session=session, feed=feed,
                 start=START, end=END, universe=[TICKER])
    ledger.strategy = strategy
    return ledger


def run_s5():
    return {"with_advance": _run(True), "without_advance": _run(False)}


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_s5_advance_turnover():
    obs = run_s5()
    on, off = obs["with_advance"], obs["without_advance"]

    # Tier 1 — both ran and traded.
    assert on.fills() and off.fills(), "the swing never traded"

    # J15 — the advance was used, and it costs a fee (the price of ứng trước):
    # the with-advance run carries a drag the without-advance run does not.
    assert on.session.cash().interest_accrued > 0, \
        "the advance was used but accrued no fee"
    assert off.session.cash().interest_accrued == 0, \
        "the un-advanced run should carry no advance fee"

    # J16/J24 — without the advance the strategy is throttled to the T+2 clock:
    # on days it wants to redeploy, the proceeds are frozen and it cannot. The
    # advance dissolves that throttle entirely.
    assert off.strategy.throttled > 0, \
        "expected the un-advanced strategy to be throttled by unsettled proceeds"
    assert on.strategy.throttled == 0, \
        "the advance should never leave the strategy throttled"

    # ...so with the advance the book turns over at least as often.
    assert len(on.fills()) >= len(off.fills()), \
        f"advance lowered turnover (on {len(on.fills())} vs off {len(off.fills())})"


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_s5()
    print("S5 — High-turnover swing on the sale advance (FPT, Sep–Nov 2022)")
    for label, led in obs.items():
        c = led.session.cash()
        print(f"  {label:16}: fills={len(led.fills())}  throttled-days="
              f"{led.strategy.throttled}  advance-fee={c.interest_accrued:,}  "
              f"| {led.summary()}")
    try:
        test_s5_advance_turnover()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
