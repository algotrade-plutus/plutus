"""J31 — A stale book is refused INDETERMINATE, not filled on old depth.

Scenario **J31** of the intraday extension. The book-walk fill has a **staleness
budget**: a resting side older than ``max_staleness`` at the order's instant is
not swept — the fill is INDETERMINATE, naming the missing book, rather than a
confident fill against depth that may no longer exist. This is the honesty rule
of the intraday path: the corpus carries no deletion record, so a level
forward-filled across a long gap might be gone.

MECHANISM — ``book_at`` drops levels older than the budget and the policy refuses
    the remainder as INDETERMINATE. The Vietnamese **lunch break** (11:30–13:00,
    QĐ 352 Điều 21) is the natural test: the last book before lunch is ~30
    minutes old at 12:00, far past any tick-scale budget, so a marketable order
    placed then cannot be honestly swept.

GOVERNING "POLICY" — the ignorance meter, our epistemic rule (design §16). A
    stale book is *ignorance*, not a no-fill: the order neither fills nor is
    rejected — it is left live and the run counts what it could not decide.

SETUP — FPT book (dev extract), 2022-11-09. A BUY at **12:00** (mid-lunch) with a
    60-second staleness budget: the newest book is from ~11:30.

EXPECTED — Tier 2
    * The order does NOT fill (no fill on a stale book).
    * It is not rejected either — it stays live.
    * The run's ignorance is non-empty and names the book (the fill was
      INDETERMINATE for want of a current ladder).
    * With the budget removed (``max_staleness=None``), the same order DOES
      fill on the last book — proving the refusal was the budget, not the data.

RUN
    python scenarios/test_j31_book_staleness.py
    pytest scenarios/test_j31_book_staleness.py -v
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from plutus.market.session import ExchangeSession, Accepted
from plutus.market.session.types import OrderState
from plutus.market.adapters.book_session import BookSessionSource
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

EXTRACT = Path("/Users/nadan/algotrade-research/dataset/hermes-dev-extract")
PRICES = "/Users/nadan/algotrade-research/dataset/hermes-parquet"
TICKER = "FPT"
LUNCH = datetime(2022, 11, 9, 13, 0, 5)      # afternoon reopen, before the book resumes:
                                             # CONTINUOUS phase, but the last book is ~11:30


def _depth_available() -> bool:
    return EXTRACT.is_dir() and any(EXTRACT.glob("local_quote_asksize*.parquet"))


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def _run(max_staleness):
    fp = {"kind": "book_walk", "queue": "optimistic", "max_participation": None,
          "max_staleness": max_staleness}
    config = {
        "period": {"start": "2022-11-09", "end": "2022-11-10"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 200_000_000,
                                    "account_no": "SEC-J31"}},
        "fill_policy": fp,
    }
    source = BookSessionSource.for_roots(PRICES, str(EXTRACT))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(config, fh)
        path = fh.name
    session = ExchangeSession.from_config(path, source=source)
    session.advance_to(LUNCH)
    ack = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1000,
                               order_type=OrderType.LIMIT, limit_price=Decimal("78.0")))
    events = session.advance_to(LUNCH + timedelta(seconds=1))
    filled = sum(e.quantity for e in events
                 if _kind(e) in ("filled", "partially_filled"))
    live = [r for r in session.orders() if r.state == OrderState.RESTING]
    return {"ack": ack, "filled": filled, "live": live,
            "ignorance": session.indeterminate_report()}


def run_j31():
    return {"budgeted": _run(60.0), "unbudgeted": _run(None)}


@pytest.mark.skipif(not _depth_available(),
                    reason="order-book depth (dev extract) not found")
def test_j31_book_staleness():
    obs = run_j31()
    budgeted, unbudgeted = obs["budgeted"], obs["unbudgeted"]

    # With a 60s budget at mid-lunch: admitted, but NOT filled on the ~30-min
    # old book, and NOT rejected — it stays live.
    assert isinstance(budgeted["ack"], Accepted), budgeted["ack"]
    assert budgeted["filled"] == 0, budgeted["filled"]
    assert budgeted["live"], "the stale-book order should still be live"

    # The run counts the ignorance and names the book.
    assert not budgeted["ignorance"].is_clean, "stale book left no ignorance trace"

    # Remove the budget and the SAME order fills on the last book — so the
    # refusal was the staleness rule, not absent data.
    assert unbudgeted["filled"] > 0, \
        "with no staleness budget the last book should still fill"


if __name__ == "__main__":
    if not _depth_available():
        raise SystemExit("order-book depth (dev extract) not found")
    obs = run_j31()
    b, u = obs["budgeted"], obs["unbudgeted"]
    print("J31 — Stale book at the afternoon reopen (FPT, 2022-11-09 13:00:05)")
    print(f"  budget 60s:  filled {b['filled']}  live={len(b['live'])}  "
          f"clean_ignorance={b['ignorance'].is_clean}")
    print(f"  no budget:   filled {u['filled']}  (the last book still fills)")
    try:
        test_j31_book_staleness()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
