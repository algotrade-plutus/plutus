"""S2 — Leveraged equity momentum, force-sold when a stop can't clear a lock.

Strategy **S2** of ``docs/reference/STRATEGY-BOARD.md``, written as a user writes
it: a real momentum strategy run on borrowed money, against Plutus as broker.

TRADING RATIONALE
    Momentum: strength begets strength. We buy a large-cap on a **breakout** — a
    strong up-day (≥ 5%) after a base — and we do it **on margin** (2:1) to press
    the edge. A disciplined momentum trader carries a **stop**: if it falls back,
    get out. On paper the stop caps the loss.

THE FLAW THE MARKET PUNISHES
    A stop only works if you can *sell*. In a real crash the tape gaps **limit
    down** and locks: everyone is a seller, there are no bids, and your stop
    order is refused (``BAND_LOCK``) day after day while the position bleeds. The
    leverage that pressed the edge now works in reverse. In **Oct 2022** DIG did
    exactly this — a breakout on 18 Oct, then a **four-day limit-down waterfall**
    (21–26 Oct, −6.9/−6.8/−6.8/−6.8%). A leveraged long can neither be stopped
    nor cured, the maintenance ratio craters, and the broker force-sells (*bán
    giải chấp*) into the same locked tape.

WHAT THE SIMULATOR MUST GET RIGHT (emergent, not staged)
    The position is built by the breakout signal; the loss is real DIG P&L; the
    margin call and forced sale must **emerge** from the equity-margin algebra;
    and orders into a locked book must be **refused**, not filled at a fantasy
    price.

MECHANISM / POLICY (oracle — SCENARIO-CATALOGUE.md, folded scenarios)
    * Equity margin lending: imr ≥ 50%, mmr ≥ 30% — QĐ 87/QĐ-UBCK Điều 5(1),(2)
      (VERIFIED). Call → cure ≤ 3 business days → forced sale — QĐ 87 Điều 7.1, 8
      (J5). The call/force LEVELS are a broker term, UNSOURCED.
    * A locked book refuses an order with ``BAND_LOCK`` — a market fact, not an
      illegal price; the forced sale itself is subject to it (J2/J11).
    * Purchases settle T+2, so proceeds and re-entry are gated (J1/J16); the
      leveraged account can run out of purchasing power (J24).

SETUP — DIG (HSX), 2022-09-05 → 2022-11-15, 100,000,000đ cash, 2:1 margin.

EXPECTED — Tier 2
    * Emergence: the breakout signal opens a leveraged long (a loan is drawn,
      margin_debt > 0), and not on day one.
    * A margin CALL is issued as DIG's slide erodes the maintenance ratio.
    * A forced sale FIRES and EXECUTES — the account is sold out, not carried.
    * A lock bites: at least one order (the forced sale, or a same-day attempt)
      is refused ``BAND_LOCK`` on a limit-down day — the stop that could not
      clear.

RUN
    .venv/bin/python strategies/test_s2_equity_margin_momentum.py
    .venv/bin/python -m pytest strategies/test_s2_equity_margin_momentum.py -v
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.adapters.datahub import DataHubSource
from plutus.market.session import ExchangeSession, Accepted, Venue  # noqa: F401
from plutus.market.session.calendar import weekday_settlement_calendar
from plutus.market.session.equity_margin import EquityMarginAccount
from plutus.market.session.margin_lending import (
    BrokerMarginTerms, DayCount, ForcedSalePrice, InterestTier,
    LiquidationOrder, MarginEligibility, ProceedsComponent, SecurityEligibility)
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import (build_session, data_available, data_root, CorpusFeed,
                      Strategy, Context, run)

TICKER = "DIG"
START = date(2022, 9, 5)
END = date(2022, 11, 15)

BREAKOUT_PCT = Decimal("0.05")     # a strong up-day: momentum entry trigger
LEVERAGE = Decimal("1.8")          # press the edge on borrowed money (imr 50% floor)
LOT = 100                          # HSX round lot (post-2021)
INITIAL_CASH = 100_000_000
PRICE_SCALE = 1000                 # corpus prices are in thousands of đồng (27.0 == 27,000đ)

CONFIG = {
    "period": {"start": "2022-09-05", "end": "2022-11-15"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HSX"]},
    "accounts": {"securities": {"initial_cash": INITIAL_CASH,
                                "account_no": "SEC-S2"}},
}


def _held(session: ExchangeSession, ticker: str) -> int:
    h = session.holdings(ticker)
    unsettled = sum((t.quantity for t in getattr(h, "unsettled", ()) or ()), 0)
    return int(getattr(h, "settled", 0) or 0) + int(unsettled)


class LeveragedMomentum(Strategy):
    """Buy a breakout on 2:1 margin and hold. The stop is the broker's."""

    name = "leveraged equity momentum"

    def __init__(self, ticker=TICKER, *, breakout=BREAKOUT_PCT, leverage=LEVERAGE,
                 lot=LOT, cash=INITIAL_CASH, start=START):
        self.ticker = ticker
        self.breakout = breakout
        self.leverage = leverage
        self.lot = lot
        self.cash = Decimal(cash)
        self.start = start
        self.account: EquityMarginAccount | None = None
        self.entered = False

    def on_day(self, ctx: Context) -> None:
        s, feed, day = ctx.session, ctx.feed, ctx.day

        # Already carrying the position? Hold — a momentum trader rides the
        # trend and lets the (broker's) stop do the work.
        if _held(s, self.ticker) > 0:
            return

        closes = feed.closes_before(self.ticker, day, 2, start=self.start)
        if len(closes) < 2:
            return
        prev, prev2 = closes[-1], closes[-2]
        if prev2 == 0:
            return
        ret = (prev - prev2) / prev2
        if ret < self.breakout:
            return                                   # no breakout -> no entry

        # Size to ~leverage x cash (in đồng — the price field is in thousands)
        # and buy the breakout on margin with a market order (MTL/MP, legal on
        # HSX): it fills at the print, and on a locked book it is refused, which
        # is the point.
        target_notional = self.leverage * self.cash
        shares = int((target_notional / (prev * PRICE_SCALE)) // self.lot) * self.lot
        if shares <= 0:
            return
        verdict = s.submit(Order(
            ticker=self.ticker, side=Side.BUY, quantity=shares,
            order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT, on_margin=True))
        if isinstance(verdict, Accepted):
            self.entered = True
        else:
            ctx.ledger.record_reject(day, verdict)


def _make_account(source) -> EquityMarginAccount:
    terms = BrokerMarginTerms(
        maintenance_margin_ratio=Decimal("0.40"),    # broker call level (UNSOURCED)
        liquidation_margin_ratio=Decimal("0.30"),    # broker force level (UNSOURCED)
        forced_sale_price=ForcedSalePrice.FLOOR,
        day_count=DayCount.ACT_365,
        liquidation_order=LiquidationOrder.LARGEST_POSITION_FIRST,
        proceeds_application_order=tuple(ProceedsComponent),
        initial_margin_ratio=Decimal("0.50"),        # QĐ 87 Điều 5(1) floor
        rate_schedule=(InterestTier(0, None, Decimal("0.135")),))
    eligibility = {TICKER: SecurityEligibility(
        ticker=TICKER, as_of=START, result=MarginEligibility.ELIGIBLE,
        venue=Venue.HSX, on_broker_list=True, note="ASSERTED by this strategy")}
    return EquityMarginAccount(
        account_id="KQ-S2", terms=terms, calendar=weekday_settlement_calendar(),
        market_feed=source.state_at, eligibility=eligibility, tickers=(TICKER,),
        execute_forced_sale=True)


def run_s2():
    source = DataHubSource.for_root(data_root())
    session = build_session(CONFIG, source=source)
    account = _make_account(source)
    session.attach_equity_margin(account)

    feed = CorpusFeed(source=source)
    strategy = LeveragedMomentum()
    strategy.account = account
    ledger = run(strategy, session=session, feed=feed,
                 start=START, end=END, universe=[TICKER])
    ledger.strategy = strategy
    ledger.account = account
    return ledger


def _count_events(account, kind_value: str) -> int:
    return sum(1 for e in account.events
               if getattr(e.kind, "value", e.kind) == kind_value)


def _sell_verdict_on(sell_day: date):
    """Hold real DIG, then try to sell it on ``sell_day``. Returns the verdict —
    used to prove directly that a limit-down lock refuses a sale (J11)."""
    src = DataHubSource.for_root(data_root())
    session = build_session(
        {**CONFIG, "period": {"start": "2022-10-03", "end": "2022-11-15"}},
        source=src)
    session.advance_to(datetime(2022, 10, 4, 11, 0))
    session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=2000,
                         order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT))
    session.advance_to(datetime(2022, 10, 4, 14, 0))
    session.advance_to(datetime(2022, 10, 11, 11, 0))     # settle T+2
    held = int(getattr(session.holdings(TICKER), "settled", 0) or 0)
    session.advance_to(datetime(sell_day.year, sell_day.month, sell_day.day, 11, 0))
    verdict = session.submit(Order(ticker=TICKER, side=Side.SELL,
                                   quantity=held or 1000,
                                   order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT))
    return held, verdict


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_s2_equity_margin_momentum():
    ledger = run_s2()
    account = ledger.account

    # Tier 1 — it ran and it traded on margin.
    assert ledger.strategy.entered, "the breakout signal never opened a position"

    # Emergence — a loan was drawn from the signal, and a call emerged from DIG's slide.
    assert account.draws, "no margin loan was drawn"
    assert account.calls(), "no margin call emerged from the drawdown"

    # Forced — the broker sold the account out, and it executed (real orders,
    # real completions), not merely reported.
    assert account.forced_sale_orders, "no forced sale order was placed"
    assert _count_events(account, "forced_sale_result_sent") >= 1, \
        "the forced sale never completed a sale"

    # J11, in the run — the forced sale was *instructed* far more often than it
    # *completed*, because the limit-down locks kept blocking it. (DIG has 14
    # limit-down-lock days in this window; the mechanism is proven directly in
    # test_s2_forced_sale_is_blocked_by_a_downlock below.)
    instructed = _count_events(account, "forced_sale_instructed")
    completed = _count_events(account, "forced_sale_result_sent")
    assert instructed > completed, \
        f"expected locks to stay the forced sale (instructed {instructed} " \
        f"vs completed {completed})"

    # The leverage did its work in reverse: the account was blown up.
    start_eq, end_eq = ledger.equity_curve[0][1], ledger.equity_curve[-1][1]
    assert end_eq < start_eq / 2, f"no blow-up: {start_eq} -> {end_eq}"


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_s2_forced_sale_is_blocked_by_a_downlock():
    """J11, directly and user-observably: a sale into a limit-down lock is
    refused (``lock_evidence='bar_proxy'``); the same sale on a tradeable day is
    accepted. This is the mechanism that stays S2's forced sale."""
    held_lock, locked = _sell_verdict_on(date(2022, 10, 24))    # a DN-LOCK day
    held_ok, tradeable = _sell_verdict_on(date(2022, 10, 20))   # a normal day
    assert held_lock > 0 and held_ok > 0, (held_lock, held_ok)

    assert not isinstance(locked, Accepted), "a sale into a limit-down lock filled"
    assert (getattr(locked, "detail", {}) or {}).get("lock_evidence") == "bar_proxy", \
        getattr(locked, "detail", None)
    assert isinstance(tradeable, Accepted), "a sale on a tradeable day was refused"


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    ledger = run_s2()
    acc = ledger.account
    print("S2 — Leveraged equity momentum, force-sold (DIG, Sep–Nov 2022)")
    print(f"  {ledger.summary()}")
    print(f"  margin debt drawn:   {acc.margin_debt:,}")
    print(f"  determinations:      {len(acc.determinations)} sessions assessed")
    print(f"  margin calls:        {len(acc.calls())}")
    print(f"  forced sale: instructed {_count_events(acc,'forced_sale_instructed')}, "
          f"completed {_count_events(acc,'forced_sale_result_sent')} "
          f"(locks stayed the rest)")
    for label, test in (("lifecycle", test_s2_equity_margin_momentum),
                        ("downlock refuses the sale (J11)",
                         test_s2_forced_sale_is_blocked_by_a_downlock)):
        try:
            test()
            print(f"  TIER 2 [{label}]: PASS")
        except AssertionError as exc:
            print(f"  TIER 2 [{label}]: FAIL — {exc}")
