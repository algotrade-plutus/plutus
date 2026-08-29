"""J26 — Day trader flat by the close vs swing trader overnight.

Scenario **J26** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Two accounts hold the same VN30F position intraday. One is flat by the close;
the other carries it overnight. Report each one's requirement.

MECHANISM (pre-KRX, 2022 — the in-corpus window)
    Pre-KRX (2017-05-01 → 2025-05-04) there is ONE margin engine:
    ``MR = IM + VM`` over the account portfolio, VM counting only in a loss
    state, recomputed against live prices. There is no separate end-of-day
    model, so the day-trader/swing-trader contrast is a difference in
    **exposure, not engine**: the day trader ends flat and carries no overnight
    requirement; the swing trader holds and carries ``IM + VM``. (Post-KRX a
    genuinely different overnight engine applies — out of this corpus window.)

POLICY (oracle — SCENARIO-CATALOGUE.md J26)
    * Pre-KRX single layer, MR = IM + VM, VM loss-only — VSDC "Thông tin về ký
      quỹ" §II/§IV; QĐ 61 (high). IM = 0.13 × contracts × price × 100,000 in
      2022.
    * There is NO cash-market counterpart: a day-trader/swing-trader margin
      contrast is derivatives-only in Vietnam (no short sale, no intraday round
      trip of the same shares) — statutory (high).

EXPECTED — Tier 2
    * Swing trader (holds 1 lot): carries a positive overnight requirement,
      IM ≈ 0.13 × price × 100,000.
    * Day trader (buys then offsets, flat by the close): position is zero and
      the overnight requirement is zero. Same intraday exposure, no overnight
      requirement.

RUN
    python scenarios/test_j26_margin_layers.py
    pytest scenarios/test_j26_margin_layers.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

TICKER = "VN30F2212"
PRICE = Decimal("945")   # 2022-11-09 close


def _config() -> dict:
    return {
        "period": {"start": "2022-11-09", "end": "2022-11-11"},
        "resolution": "1d",
        "exchange_rules": {"venues": ["HNXDS"]},
        "accounts": {"derivatives": {"initial_deposit": 200_000_000,
                                     "account_no": "DER-J26"}},
    }


def _run(day_trader: bool):
    session = build_session(_config())
    session.advance_to(datetime(2022, 11, 9, 11, 0))
    session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1,
                         order_type=OrderType.LIMIT, limit_price=PRICE))
    session.advance_to(datetime(2022, 11, 9, 13, 0))   # fill the buy
    if day_trader:
        session.submit(Order(ticker=TICKER, side=Side.SELL, quantity=1,
                             order_type=OrderType.LIMIT, limit_price=PRICE))
        session.advance_to(datetime(2022, 11, 9, 14, 0))   # fill the offset -> flat
    return session.positions(), session.margin()


def _net_contracts(positions) -> int:
    return sum(abs(p.net_quantity) for p in positions.values())


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j26_margin_layers():
    swing_pos, swing_margin = _run(day_trader=False)
    day_pos, day_margin = _run(day_trader=True)

    # Swing trader holds one lot and carries a positive overnight requirement.
    assert _net_contracts(swing_pos) == 1, swing_pos
    assert swing_margin.initial_margin > 0, swing_margin

    # Day trader is flat by the close: no position, no overnight requirement.
    assert _net_contracts(day_pos) == 0, day_pos
    assert day_margin.initial_margin == 0, day_margin

    # Same intraday exposure; the difference is overnight, and it is real.
    assert swing_margin.initial_margin > day_margin.initial_margin


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    swing_pos, swing_margin = _run(day_trader=False)
    day_pos, day_margin = _run(day_trader=True)
    print("J26 — Day trader vs swing trader (VN30F2212, 2022-11-09, pre-KRX)")
    print(f"  swing (holds):  net {_net_contracts(swing_pos)} lot, IM {swing_margin.initial_margin:>12,}")
    print(f"  day (flat):     net {_net_contracts(day_pos)} lot, IM {day_margin.initial_margin:>12,}")
    print(f"  same intraday exposure; overnight requirement differs by "
          f"{swing_margin.initial_margin - day_margin.initial_margin:,}")
    try:
        test_j26_margin_layers()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
