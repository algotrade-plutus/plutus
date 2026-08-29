"""J35 — A maker the tape cannot see is INDETERMINATE, not a no-fill.

Scenario **J35** of the intraday extension, and the honesty rule at the heart of
the maker arm. When the sized tape does **not** serve a resting order's window,
whether it would have filled **cannot be established** — so the fill is
INDETERMINATE, naming the missing volume, never a confident no-fill. A confident
no-fill would silently suppress every trade the strategy should have made, which
fails in the opposite (and more dangerous) direction to a confident fill.

SETUP — the exported tape carries volume for **FPT only**; the book, however,
    carries **HPG** too. So a resting **HPG** order on 2022-11-09 has a real
    book and admission but **no tape**: the maker arm cannot say whether it
    filled. (This is the same shape as any ticker/day outside the tape's cover.)

    An HPG BUY of 1,000 at 12.50 is posted at 10:00 (below the ask, so it rests
    rather than crosses) and left to 14:00.

MECHANISM — ``TapeSource.prints_through`` returns ``None`` for HPG (unserved),
    which ``maker_fill`` turns into an INDETERMINATE claim naming ``VOLUME``, and
    the arm into an INDETERMINATE decision. The order stays live; the run counts
    the ignorance and names the field.

CONTRAST with J34: there the tape **served** the window and answered 0 (a
    definite no-fill); here the tape does **not** serve it (INDETERMINATE). Same
    zero fills, opposite epistemic status — which is the whole point of the
    served-vs-unserved distinction.

EXPECTED — Tier 2
    * The order does not fill and is not rejected — it stays live.
    * The run's ignorance is **non-empty** and names ``VOLUME`` (the tape), so
      the missing fill is visible, not buried as a confident no-fill.

RUN
    python scenarios/test_j35_maker_indeterminate_session.py
    pytest scenarios/test_j35_maker_indeterminate_session.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from plutus.market.session import ExchangeSession, Accepted, parse_config
from plutus.market.session.types import DataField
from plutus.market.adapters.book_session import BookSessionSource
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

EXTRACT = Path("/Users/nadan/algotrade-research/dataset/hermes-dev-extract")
PRICES = "/Users/nadan/algotrade-research/dataset/hermes-parquet"
TICKER = "HPG"                       # book present, but the tape carries FPT only
PRICE = Decimal("12.50")             # below the ask -> rests as a maker
SUBMIT = datetime(2022, 11, 9, 10, 0)
END = datetime(2022, 11, 9, 14, 0)


def _tape_available() -> bool:
    return EXTRACT.is_dir() and (EXTRACT / "local_quote_total.parquet").exists()


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def run_j35():
    config = parse_config({
        "period": {"start": "2022-11-09", "end": "2022-11-10"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 200_000_000,
                                    "account_no": "SEC-J35"}},
        "fill_policy": {"kind": "book_walk", "queue": "optimistic",
                        "max_participation": None, "max_staleness": None},
    })
    source = BookSessionSource.for_roots(PRICES, str(EXTRACT))
    session = ExchangeSession.build(config, source=source)
    session.advance_to(SUBMIT)
    ack = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1000,
                               order_type=OrderType.LIMIT, limit_price=PRICE))
    events = session.advance_to(END)
    fills = [e for e in events if _kind(e) in ("filled", "partially_filled")]
    live = [r for r in session.orders() if not r.is_terminal]
    return {"ack": ack, "fills": fills, "live": live,
            "ignorance": session.indeterminate_report()}


@pytest.mark.skipif(not _tape_available(),
                    reason="sized tape (local_quote_total) not found")
def test_j35_maker_indeterminate_session():
    obs = run_j35()
    assert isinstance(obs["ack"], Accepted), obs["ack"]

    # No fill, not rejected -- it stays live.
    assert not obs["fills"], obs["fills"]
    assert obs["live"], "the order should still be live"

    # The run counts the ignorance and names the tape (VOLUME) -- the missing
    # fill is visible, not a confident no-fill.
    report = obs["ignorance"]
    assert not report.is_clean, "an unserved tape left no ignorance trace"
    # Exactly VOLUME -- so the INDETERMINATE is the tape's, not a masked BOOK /
    # band / instrument gap that happened to also fire.
    assert set(report.by_field) == {DataField.VOLUME}, report.by_field


if __name__ == "__main__":
    if not _tape_available():
        raise SystemExit("sized tape (local_quote_total) not found")
    obs = run_j35()
    print("J35 — A maker the tape cannot see is INDETERMINATE (HPG, no tape)")
    print(f"  submit: {type(obs['ack']).__name__}")
    print(f"  fills: {len(obs['fills'])}   live: {len(obs['live'])}   "
          f"ignorance clean: {obs['ignorance'].is_clean}")
    print(f"  by_field: {dict(obs['ignorance'].by_field)}")
    try:
        test_j35_maker_indeterminate_session()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
