"""J4 — Pair trade: a VN30 proxy basket on HSX against VN30F on HNXDS.

Scenario **J4** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Long a cash basket on HOSE, short the index future on HNXDS, in one session out
of one account object. Two venues, two instrument kinds, two settlement clocks,
two margin regimes — against one ledger, with the securities cash and the
derivatives deposit **segregated** (no auto-transfer between them).

MECHANISM
    Each leg is governed by its own venue's rules, resolved per order: the HSX
    basket draws securities cash and settles T+2 under a ±7% band; the HNXDS
    short reserves the derivatives deposit as margin. A rule error shows up as
    one leg's rules leaking onto the other — an HNXDS tick on the HOSE basket,
    a T+2 clock on the future, or one margin regime covering both.

POLICY (oracle — SCENARIO-CATALOGUE.md J4)
    * HSX: band ±7%, tick 10/50/100đ, lot 100 — QĐ 352 Điều 8.1/8.4/9.6
      (high, 2021-07-05+). HNXDS: tick 0.1 point, multiplier 100,000đ/point,
      order limit 500 — HNX template; VNX QĐ 20/21 (high).
    * The two account pools are segregated with no auto-transfer (TT 120/2020
      Điều 9.3 — segregation is per investor, not shared).

EXPECTED — Tier 2
    * The basket legs (HSX) are held as shares and draw securities cash.
    * The future (HNXDS) is held as a SHORT position and reserves the
      derivatives deposit as margin.
    * The two pools move independently — the future's margin comes from the
      deposit, not from the securities cash, and vice versa.

RUN
    python scenarios/test_j4_pair_trade.py
    pytest scenarios/test_j4_pair_trade.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

# A small VN30 proxy basket (HSX) and the front future (HNXDS), 2022-11-09.
BASKET = {"FPT": "74.0", "HPG": "13.0", "SSI": "14.9"}
FUTURE = "VN30F2212"
FUT_PRICE = Decimal("945")

CONFIG = {
    "period": {"start": "2022-11-09", "end": "2022-11-11"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HSX", "HNXDS"]},
    "accounts": {
        "securities": {"initial_cash": 100_000_000, "account_no": "SEC-J4"},
        "derivatives": {"initial_deposit": 100_000_000, "account_no": "DER-J4"},
    },
}


def _held(holding) -> int:
    return holding.settled + sum(t.quantity for t in holding.unsettled)


def run_j4():
    session = build_session(CONFIG)
    session.advance_to(datetime(2022, 11, 9, 11, 0))
    cash0 = session.cash().settled_balance
    deposit0 = session.margin().deposit_balance

    # Long the basket (HSX, securities cash).
    for name, px in BASKET.items():
        session.submit(Order(ticker=name, side=Side.BUY, quantity=100,
                             order_type=OrderType.LIMIT, limit_price=Decimal(px)))
    # Short the future (HNXDS, derivatives deposit).
    fut = session.submit(Order(ticker=FUTURE, side=Side.SELL, quantity=1,
                               order_type=OrderType.LIMIT, limit_price=FUT_PRICE))

    session.advance_to(datetime(2022, 11, 9, 14, 0))     # fill both legs
    return {
        "fut_ack": fut,
        "holdings": {n: _held(session.holdings(n)) for n in BASKET},
        "positions": session.positions(),
        "cash0": cash0, "cash1": session.cash().settled_balance,
        "deposit0": deposit0, "margin": session.margin(),
    }


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j4_pair_trade():
    obs = run_j4()

    # Basket legs held as shares (HSX), and securities cash was spent on them.
    for name in BASKET:
        assert obs["holdings"][name] == 100, (name, obs["holdings"][name])
    assert obs["cash1"] < obs["cash0"], (obs["cash0"], obs["cash1"])

    # The future is held SHORT (HNXDS) and reserved margin from the deposit.
    fut_pos = obs["positions"].get(FUTURE)
    assert fut_pos is not None and fut_pos.net_quantity == -1, obs["positions"]
    assert obs["margin"].initial_margin > 0, obs["margin"]

    # Segregation, both directions:
    #  - the basket's ~10M spend did NOT touch the deposit (it fell only by the
    #    future's own charges), and
    #  - the future's 12.285M margin did NOT touch the securities cash (which
    #    fell only by the ~10M basket cost, less than the future's margin).
    deposit_drop = obs["deposit0"] - obs["margin"].deposit_balance
    cash_drop = obs["cash0"] - obs["cash1"]
    assert deposit_drop < 1_000_000, deposit_drop
    assert cash_drop < obs["margin"].initial_margin, (cash_drop, obs["margin"].initial_margin)
    assert obs["margin"].posted_margin == obs["margin"].initial_margin, obs["margin"]


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j4()
    print("J4 — Pair trade: VN30 basket (HSX) vs VN30F (HNXDS), 2022-11-09")
    print(f"  basket held: {obs['holdings']}")
    fp = obs["positions"].get(FUTURE)
    print(f"  future:      {FUTURE} net {fp.net_quantity if fp else 0} (short), "
          f"IM {obs['margin'].initial_margin:,}")
    print(f"  securities cash: {obs['cash0']:,} -> {obs['cash1']:,}")
    print(f"  deposit balance: {obs['deposit0']:,} (unchanged by the basket)")
    try:
        test_j4_pair_trade()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
