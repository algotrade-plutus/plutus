"""J3 — Leveraged VN30F long into a real drawdown.

Scenario **J3** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Open a leveraged VN30F long, hold it through the Oct-2022 drawdown, and print
the chain: the position, the margin call, and the forced liquidation that now
**executes** — closing the position rather than reporting a close it never ran.

MECHANISM (pre-KRX, 2022)
    ``MR = IM + VM`` over the deposit; the utilisation ladder issues a call as
    the loss (VM) grows, and past a cure window the broker force-closes. The
    forced close goes through the order path — same band, tick, lot and fill
    policy — so it fills on a tradeable day and would be refused ``BAND_LOCK``
    on a locked one.

WHAT THIS BUILT (publish-checklist MUST #3)
    ``FORCED_LIQUIDATION`` used to report with ``detail['executed'] = False``
    and close nothing — a strategy that would have been liquidated survived
    (measured 17.6% permissive cost). It now submits real offsetting orders
    (``exchange.py::_execute_forced_close``): ``detail['executed']`` is True and
    the position closes. The cure window is honoured — the first mark that
    reports FORCED only reports; the breach persisting past it executes
    (QĐ 26 Điều 13.3).

DECLARED (MUST #4, not yet built): variation margin does not settle in cash
    daily — it is measured cumulative-since-entry (A60), not the day's move. VM
    is reported here; its daily settlement is a separate pending build.

SETUP — VN30F2212, bought 2022-10-03 at 1110 with a deposit near one IM, held
into the Oct-2022 slide (1106 → ~940).

EXPECTED — Tier 2
    * The position opens (net 1 lot).
    * A margin CALL is issued as the drawdown eats the deposit.
    * A FORCED_LIQUIDATION fires with ``executed=True`` and names the leg, and
      the position is CLOSED (net 0) — not permissively carried.

RUN
    python scenarios/test_j3_forced_liquidation.py
    pytest scenarios/test_j3_forced_liquidation.py -v
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
CONFIG = {
    "period": {"start": "2022-10-03", "end": "2022-10-12"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HNXDS"]},
    "accounts": {"derivatives": {"initial_deposit": 18_000_000, "account_no": "DER-J3"}},
}
DAYS = ["2022-10-04", "2022-10-05", "2022-10-06", "2022-10-07",
        "2022-10-10", "2022-10-11"]


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def _net(session) -> int:
    p = session.positions().get(TICKER)
    return p.net_quantity if p else 0


def run_j3():
    session = build_session(CONFIG)
    session.advance_to(datetime(2022, 10, 3, 11, 0))
    session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1,
                         order_type=OrderType.LIMIT, limit_price=Decimal("1110")))
    session.advance_to(datetime(2022, 10, 3, 13, 0))     # fill -> position opens
    opened = _net(session)

    events = []
    for day in DAYS:
        y, m, d = (int(x) for x in day.split("-"))
        events.extend(session.advance_to(datetime(y, m, d, 13, 0)))

    called = [e for e in events if _kind(e) == "margin_call"]
    forced = [e for e in events if _kind(e) == "forced_liquidation"]
    executed = [e for e in forced if e.detail.get("executed") is True]
    return {"opened": opened, "called": called, "forced": forced,
            "executed": executed, "final_net": _net(session)}


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j3_forced_liquidation():
    obs = run_j3()

    # The leveraged position opens.
    assert obs["opened"] == 1, obs["opened"]

    # A margin call is issued as the drawdown eats the deposit.
    assert obs["called"], "no margin call was issued"

    # The forced liquidation EXECUTES (MUST #3) — it names the leg and closes it.
    assert obs["executed"], "forced liquidation reported but never executed"
    assert TICKER in dict(obs["executed"][0].detail.get("closed") or ()), \
        obs["executed"][0].detail

    # The position is closed, not permissively carried through the drawdown.
    assert obs["final_net"] == 0, obs["final_net"]


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_j3()
    print("J3 — Leveraged VN30F long into a drawdown (VN30F2212, Oct 2022)")
    print(f"  position opened:     net {obs['opened']} lot")
    print(f"  margin calls:        {len(obs['called'])}")
    print(f"  forced liquidations: {len(obs['forced'])}  (executed: {len(obs['executed'])})")
    if obs["executed"]:
        print(f"  forced close closed: {obs['executed'][0].detail.get('closed')}")
    print(f"  final position:      net {obs['final_net']} lot (closed, not carried)")
    try:
        test_j3_forced_liquidation()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
