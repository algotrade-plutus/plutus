"""S3 — Basket vs future, carried across a constituent's ex-date.

Strategy **S3** of ``docs/reference/STRATEGY-BOARD.md``, written as a user writes
it. A market-neutral **index-arb / dividend-carry**: hold a basket of VN30
constituents **long** and short the **VN30F future** against them, so index moves
wash out and what is left is the basket's *carry* — its dividends and
adjustments. The trade lives across an **ex-date**, and the position spans two
segregated pools with two settlement cycles (equity T+2, futures daily VM).

TRADING RATIONALE
    Long the components, short the index future: a classic hedged basket. The
    residual return is the constituents' corporate actions. So we deliberately
    hold through a constituent's ex-dividend to bank the cash leg — the market
    marks the stock down by the dividend, and the holder is paid it, a wash in
    net worth but a real cashflow the book must record.

WHAT THE SIMULATOR MUST GET RIGHT (multi-leg coherence + the ex-date)
    * Two pools at once: an equity basket in the securities account and a short
      future in the derivatives deposit — funded, margined and settled
      independently, no bleed between them (J4/J23).
    * A corporate action is **exogenous data** the strategy supplies; the session
      must apply it to the *held* position — crediting the cash leg on the total
      held (settled + still-unsettled), with value conserved across the ex-date.

THE FEATURE THIS BUILT
    The session had **no** corporate-action entry point — the engine could only
    be reached through a raw ``SecuritiesAccount``. A strategy holding a basket
    in a *session* could not apply an ex-date at all. This adds
    ``ExchangeSession.apply_corporate_action(action, ts=...)`` — the caller-driven
    engine, wired to the account the session holds. Not mocked around; built.

MECHANISM / POLICY (oracle — SCENARIO-CATALOGUE.md, folded scenarios)
    * The ex-date reference is adjusted for the distribution's value; the
      arithmetic (A26) is not gazetted — QĐ 352 Điều 10.3; QĐ 17 Điều 32.4 (J8).
      The cash leg is credited GROSS (the 5% withholding is not levied, D27).
    * A basket is many independent legs on one cash ledger (J23); a pair spans
      two pools (J4). Equity settles T+2, futures VM T+1 — a financing asymmetry.

SETUP — basket {HPG, SSI, MBB} long + VN30F2212 short, 2022-11-08 → 2022-11-18.
    HPG pays a representative 1,500đ/share cash dividend ex 2022-11-11 (exogenous
    data the strategy carries, as J8 supplies its own event).

EXPECTED — Tier 2
    * Every leg is admitted: three basket buys AND the short future — the basket
      is held in the securities pool and the short sits in the deposit, together.
    * Across the ex-date the held HPG is paid the cash dividend through the
      session — credited on the total held, gross, exactly qty × 1,500.
    * The reference adjustment conserves value (no free gain on the ex-date).

RUN
    .venv/bin/python strategies/test_s3_basket_vs_future.py
    .venv/bin/python -m pytest strategies/test_s3_basket_vs_future.py -v
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted, Venue  # noqa: F401
from plutus.market.session.corporate import CorporateAction, adjusted_reference
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import (build_session, data_available, CorpusFeed, Strategy,
                      Context, run, PRICE_SCALE)

BASKET = ["HPG", "SSI", "MBB"]
FUTURE = "VN30F2212"
START = date(2022, 11, 8)
END = date(2022, 11, 18)
LOT = 100
LEG_NOTIONAL = 40_000_000            # ~đồng per basket leg
EX_DATE = date(2022, 11, 11)         # HPG ex-dividend (exogenous)
DIVIDEND = Decimal("1500")           # đồng/share, representative cash dividend

CONFIG = {
    "period": {"start": "2022-11-08", "end": "2022-11-18"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HSX", "HNXDS"]},
    "accounts": {
        "securities": {"initial_cash": 300_000_000, "account_no": "SEC-S3"},
        "derivatives": {"initial_deposit": 30_000_000, "account_no": "DER-S3"},
    },
}


def _held(session: ExchangeSession, ticker: str) -> int:
    h = session.holdings(ticker)
    return int(getattr(h, "settled", 0) or 0) + sum(
        (t.quantity for t in getattr(h, "unsettled", ()) or ()), 0)


class BasketVsFuture(Strategy):
    """Long a VN30 basket, short the future; carry it across an ex-date."""

    name = "basket vs future (dividend carry)"

    def __init__(self, *, start=START):
        self.start = start
        self.legs_admitted: dict = {}
        self.future_admitted = None
        self.built = False
        self.ex_applied = False
        self.dividend_cash = Decimal(0)
        self.held_at_ex = 0

    def on_day(self, ctx: Context) -> None:
        s, feed, day = ctx.session, ctx.feed, ctx.day

        if not self.built:
            # Build the hedge: buy each basket leg (market order, fills at the
            # print) and short one future against the basket.
            for name in BASKET:
                px = feed.closes_before(name, day, 1, start=self.start)
                if not px:
                    return                          # wait for a price
                shares = int((LEG_NOTIONAL / (px[-1] * PRICE_SCALE)) // LOT) * LOT
                self.legs_admitted[name] = s.submit(Order(
                    ticker=name, side=Side.BUY, quantity=shares,
                    order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT))
            self.future_admitted = s.submit(Order(
                ticker=FUTURE, side=Side.SELL, quantity=1,
                order_type=OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT))
            self.built = True
            return

        # Carry across the ex-date: the strategy's dividend calendar says HPG
        # goes ex today, so it books the event against the session's holding.
        if day == EX_DATE and not self.ex_applied:
            self.held_at_ex = _held(s, "HPG")
            before = s.cash().settled_balance
            s.apply_corporate_action(
                CorporateAction.cash_dividend("HPG", day, DIVIDEND))
            self.dividend_cash = s.cash().settled_balance - before
            self.ex_applied = True


def run_s3():
    session = build_session(CONFIG)
    feed = CorpusFeed()
    strategy = BasketVsFuture()
    ledger = run(strategy, session=session, feed=feed,
                 start=START, end=END, universe=BASKET + [FUTURE])
    ledger.strategy = strategy
    return ledger


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_s3_basket_vs_future():
    ledger = run_s3()
    st = ledger.strategy
    session = ledger.session

    # Multi-leg coherence — every basket leg AND the short future admitted...
    assert all(isinstance(a, Accepted) for a in st.legs_admitted.values()), \
        {n: type(a).__name__ for n, a in st.legs_admitted.items()}
    assert isinstance(st.future_admitted, Accepted), st.future_admitted

    # ...and the two pools coexist: the basket is held in securities, the short
    # sits in the derivatives deposit, no bleed.
    for name in BASKET:
        assert _held(session, name) > 0, (name, session.holdings(name))
    fut = session.positions().get(FUTURE)
    assert fut is not None and fut.net_quantity < 0, session.positions()

    # The ex-date paid the held HPG its dividend, through the session, on the
    # total held, gross — exactly qty × 1,500.
    assert st.ex_applied, "the ex-date was never applied"
    assert st.held_at_ex > 0, "held no HPG across the ex-date"
    assert st.dividend_cash == Decimal(st.held_at_ex) * DIVIDEND, \
        (st.dividend_cash, st.held_at_ex, DIVIDEND)

    # The reference adjustment conserves value — no free gain on the ex-date.
    ref = Decimal("22.0")
    adj = adjusted_reference(
        CorporateAction.cash_dividend("HPG", EX_DATE, DIVIDEND), ref, venue=Venue.HSX)
    # a 1,500đ cash dividend drops a 22,000đ reference by 1,500đ (value carried
    # off as cash, not lost): 22.0 -> 20.5 (thousand đồng).
    assert abs(adj.raw_reference - (ref - DIVIDEND / PRICE_SCALE)) < Decimal("0.001"), \
        adj.raw_reference


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    ledger = run_s3()
    st = ledger.strategy
    session = ledger.session
    print("S3 — Basket vs future across an ex-date (HPG/SSI/MBB + VN30F2212)")
    for name in BASKET:
        print(f"  {name}: {'Accepted' if isinstance(st.legs_admitted.get(name), Accepted) else st.legs_admitted.get(name)}"
              f"  held={_held(session, name)}")
    fut = session.positions().get(FUTURE)
    print(f"  {FUTURE} short: {'Accepted' if isinstance(st.future_admitted, Accepted) else st.future_admitted}"
          f"  net={fut.net_quantity if fut else 0}")
    print(f"  ex-date {EX_DATE}: held {st.held_at_ex} HPG, dividend cash "
          f"{st.dividend_cash:,} (= {st.held_at_ex} × {DIVIDEND})")
    try:
        test_s3_basket_vs_future()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
