"""J34 — A resting order the tape never trades through is a no-fill, not ignorance.

Scenario **J34** of the intraday extension, and the other half of the honesty
rule J35 states. A maker that posts where nothing trades **rests**: that is a
*definite* no-fill, decided from a tape the session **does** serve — absence of
prints on an observed tape is knowledge, not ignorance. It must NOT be reported
as INDETERMINATE (which would inflate a run's ignorance with a question the data
actually answered), and it must NOT phantom-fill.

SETUP — FPT, 2022-11-09. A SELL of 2,000 at **74.50** is posted at 09:20 and left
    to rest to 14:30. Nothing prints at or through 74.50 all session (the day's
    trades stay below it), so the resting offer is never lifted.

MECHANISM — the maker arm asks the tape for prints through 74.50 and gets a
    served **0** (not ``None``): the window is covered, nothing traded through.
    ``maker_fill`` returns a determinate 0, so the arm returns a definite
    NO_FILL and the order simply keeps resting, interval after interval.

EXPECTED — Tier 2
    * The order **never fills** and is **not terminal** — it rests with its full
      quantity, re-evaluated each interval.
    * The run's **ignorance is clean**: a served-but-empty tape is a definite
      no-fill, so nothing is counted INDETERMINATE.

RUN
    python scenarios/test_j34_maker_no_fill_session.py
    pytest scenarios/test_j34_maker_no_fill_session.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from plutus.market.session import ExchangeSession, Accepted, parse_config
from plutus.market.adapters.book_session import BookSessionSource
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

EXTRACT = Path("/Users/nadan/algotrade-research/dataset/hermes-dev-extract")
PRICES = "/Users/nadan/algotrade-research/dataset/hermes-parquet"
TICKER = "FPT"
PRICE = Decimal("74.50")           # nothing trades at or through this all day
SUBMIT = datetime(2022, 11, 9, 9, 20)
END = datetime(2022, 11, 9, 14, 30)


def _tape_available() -> bool:
    return EXTRACT.is_dir() and (EXTRACT / "local_quote_total.parquet").exists()


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def run_j34():
    config = parse_config({
        "period": {"start": "2022-11-09", "end": "2022-11-10"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 200_000_000,
                                    "account_no": "SEC-J34"}},
        "fill_policy": {"kind": "book_walk", "queue": "optimistic",
                        "max_participation": None, "max_staleness": None},
    })
    source = BookSessionSource.for_roots(PRICES, str(EXTRACT))
    session = ExchangeSession.build(config, source=source,
                                    initial_holdings={TICKER: 2000})
    session.advance_to(SUBMIT)
    ack = session.submit(Order(ticker=TICKER, side=Side.SELL, quantity=2000,
                               order_type=OrderType.LIMIT, limit_price=PRICE))
    # step through the session so the order is re-evaluated many times
    fills = []
    for hour in (10, 11, 13, 14):
        events = session.advance_to(datetime(2022, 11, 9, hour, 0))
        fills += [e for e in events if _kind(e) in ("filled", "partially_filled")]
    session.advance_to(END)
    order = session.orders()[0]
    return {"ack": ack, "fills": fills, "order": order,
            "ignorance": session.indeterminate_report()}


@pytest.mark.skipif(not _tape_available(),
                    reason="sized tape (local_quote_total) not found")
def test_j34_maker_no_fill_session():
    obs = run_j34()
    assert isinstance(obs["ack"], Accepted), obs["ack"]

    # Never fills, and never terminal -- it rests with its full quantity.
    assert not obs["fills"], obs["fills"]
    assert not obs["order"].is_terminal
    assert obs["order"].filled_quantity == 0

    # A served-but-empty tape is a DEFINITE no-fill, so the run's ignorance is
    # clean -- nothing here was INDETERMINATE.
    assert obs["ignorance"].is_clean, obs["ignorance"]

    # The mechanism, checked directly so the no-fill is earned, not incidental:
    # the tape SERVES this window and answers a definite 0 (an int, not None).
    # That -- not an unwired tape -- is why the rest is definite. (An unserved
    # tape returns None and is INDETERMINATE; that is J35.)
    from plutus.market.adapters.tape import TapeSource
    served = TapeSource(str(EXTRACT), table_prefix="local_quote").prints_through(
        TICKER, PRICE, Side.SELL, SUBMIT, END)
    assert served == 0, served                  # served 0, not None


if __name__ == "__main__":
    if not _tape_available():
        raise SystemExit("sized tape (local_quote_total) not found")
    obs = run_j34()
    print("J34 — A maker where nothing trades rests (FPT, SELL 2000 @ 74.50)")
    print(f"  submit: {type(obs['ack']).__name__}")
    print(f"  fills: {len(obs['fills'])}   filled_quantity: "
          f"{obs['order'].filled_quantity}   terminal: {obs['order'].is_terminal}")
    print(f"  ignorance clean (served-but-empty is definite): "
          f"{obs['ignorance'].is_clean}")
    try:
        test_j34_maker_no_fill_session()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
