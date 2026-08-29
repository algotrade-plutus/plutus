"""J28 — A book-walk fill through the session (the intraday path).

Scenario **J28** of the intraday extension. An order submitted through the
ordinary ``session.submit`` / ``advance_to`` path fills by **walking the
reconstructed order book** at its instant — at the resting ask levels, not at a
bar's close — when the session is configured ``fill_policy.kind = book_walk``
over a :class:`DepthSource`.

MECHANISM — this is the intraday selling point wired to the session. The book
    walk, the queue policies and the ``DepthSource`` already existed (J13/J21
    used them off-session, via ``walk_book`` directly); this drives them through
    the public surface: ``session.submit`` an order, ``advance_to`` an instant,
    and the fill is a walk of the book at that instant. The queue assumption is
    named in config and recorded in the run's provenance signature.

POLICY (oracle)
    * A match trades at the resting (passive) order's price — QĐ 352 Điều 6.3
      (sourced). This is the one book-walk fact that IS a rule.
    * WHERE the order sits in the queue at a price is UNSOURCED — our modelling
      choice, named in config (optimistic here) and self-reported (J29).

SETUP — FPT book (dev extract), 2022-11-09 09:16:05. A BUY 2000 @ 78.0 sweeps the
    ask; under the optimistic queue it takes the whole visible level at 73.40.

EXPECTED — Tier 2
    * The order is admitted and FILLS through the session (not INDETERMINATE,
      not fill-at-close).
    * The fill price is the book's ask level (73.40), i.e. a walk of the book —
      demonstrably not a bar close.
    * The run's fill-policy provenance names ``book_walk`` and the queue.

RUN
    python scenarios/test_j28_book_walk_session.py
    pytest scenarios/test_j28_book_walk_session.py -v
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from plutus.market.session import ExchangeSession, Accepted
from plutus.market.adapters.book_session import BookSessionSource
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

EXTRACT = Path("/Users/nadan/algotrade-research/dataset/hermes-dev-extract")  # the book
PRICES = "/Users/nadan/algotrade-research/dataset/hermes-parquet"             # bands/instrument
TICKER = "FPT"
TS = datetime(2022, 11, 9, 9, 16, 5, 290870)   # a clean book instant
ASK = Decimal("73.400000")                       # the visible ask level


def _depth_available() -> bool:
    return EXTRACT.is_dir() and any(EXTRACT.glob("local_quote_asksize*.parquet"))


def _config(queue: str) -> dict:
    # Price/instrument/band come from the DataHubSource over the extract's
    # quote_* tables; the book-walk fill sweeps the DepthSource the session
    # opens over the same root's local_quote_* tables.
    return {
        "period": {"start": "2022-11-09", "end": "2022-11-10"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 200_000_000,
                                    "account_no": "SEC-J28"}},
        "fill_policy": {"kind": "book_walk", "queue": queue,
                        "max_participation": None, "max_staleness": None},
    }


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def run_j28(queue: str = "optimistic"):
    source = BookSessionSource.for_roots(PRICES, str(EXTRACT))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(_config(queue), fh)
        path = fh.name
    session = ExchangeSession.from_config(path, source=source)

    session.advance_to(TS)
    ack = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=2000,
                               order_type=OrderType.LIMIT,
                               limit_price=Decimal("78.0")))
    events = session.advance_to(TS + timedelta(seconds=1))
    fills = [e for e in events if _kind(e) in ("filled", "partially_filled")]
    return {"ack": ack, "fills": fills, "session": session}


@pytest.mark.skipif(not _depth_available(),
                    reason="order-book depth (dev extract) not found")
def test_j28_book_walk_session():
    obs = run_j28("optimistic")

    # Tier 1 — admitted and it filled through the session path.
    assert isinstance(obs["ack"], Accepted), obs["ack"]
    assert obs["fills"], "the book-walk order never filled through the session"

    # Tier 2 — the fill is a WALK of the book: at the ask level, not a bar close.
    prices = {e.price for e in obs["fills"]}
    assert prices == {ASK}, prices
    assert sum(e.quantity for e in obs["fills"]) == 2000  # optimistic takes the level

    # The run self-reports the assumption: book_walk + the queue, in provenance.
    prov = obs["session"].provenance()
    assert "book_walk" in prov.fill_policy_kind, prov.fill_policy_kind
    assert "optimistic" in prov.fill_policy_kind.lower(), prov.fill_policy_kind


if __name__ == "__main__":
    if not _depth_available():
        raise SystemExit("order-book depth (dev extract) not found")
    obs = run_j28("optimistic")
    print("J28 — Book-walk fill through the session (FPT, 2022-11-09)")
    print(f"  submit: {type(obs['ack']).__name__}")
    for e in obs["fills"]:
        print(f"  filled {e.quantity} @ {e.price}  (book ask level, not a close)")
    print(f"  provenance fill policy: {obs['session'].provenance().fill_policy_kind}")
    try:
        test_j28_book_walk_session()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
