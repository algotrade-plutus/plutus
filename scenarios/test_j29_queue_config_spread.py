"""J29 — Queue policy chosen by config: the same order, three fills.

Scenario **J29** of the intraday extension. J21 showed the optimistic /
conservative / probabilistic queue policies move a fill when called through
``walk_book`` directly. J29 shows the same spread **selected by config and driven
through the session** — and, crucially, **recorded in the run's provenance**, so
a result carries its own queue assumption.

MECHANISM — the queue assumption is the one intraday fidelity knob that history
    cannot resolve: where our order sat in the resting queue at a price is not
    recoverable from a reconstructed book. So it is a *declared* modelling
    choice — named in ``fill_policy.queue``, never defaulted — and it is stamped
    on every fill through ``SessionProvenance.fill_policy_kind``. A user who
    changes the queue mode sees the fill move, and the run says which mode it
    was.

GOVERNING "POLICY" — OUR MODELLING CHOICE, not a market rule (UNSOURCED). Price-
    then-time priority is sourced (QĐ 352 Điều 7); the time-rank of *our own*
    order against strangers' resting orders is not.

SETUP — FPT book (dev extract), 2022-11-09 09:16:05, BUY 2000 @ 78.0. Optimistic
    (front of queue) takes the whole visible level; conservative (back) gets
    nothing; probabilistic draws between, reproducibly under a seed.

EXPECTED — Tier 2
    * The three queue policies do NOT agree on the fill — swapping the config
      token moves the outcome.
    * optimistic fills the most; conservative the least (0 here).
    * probabilistic is reproducible under a fixed seed.
    * Each run's provenance names ``book_walk`` and its queue.

RUN
    python scenarios/test_j29_queue_config_spread.py
    pytest scenarios/test_j29_queue_config_spread.py -v
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

EXTRACT = Path("/Users/nadan/algotrade-research/dataset/hermes-dev-extract")
PRICES = "/Users/nadan/algotrade-research/dataset/hermes-parquet"
TICKER = "FPT"
TS = datetime(2022, 11, 9, 9, 16, 5, 290870)


def _depth_available() -> bool:
    return EXTRACT.is_dir() and any(EXTRACT.glob("local_quote_asksize*.parquet"))


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def _filled_under(queue: str, seed=None) -> tuple:
    """Run the identical BUY under one queue config; return (filled, provenance)."""
    fill_policy = {"kind": "book_walk", "queue": queue,
                   "max_participation": None, "max_staleness": None}
    if seed is not None:
        fill_policy["seed"] = seed
    config = {
        "period": {"start": "2022-11-09", "end": "2022-11-10"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 200_000_000,
                                    "account_no": "SEC-J29"}},
        "fill_policy": fill_policy,
    }
    source = BookSessionSource.for_roots(PRICES, str(EXTRACT))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(config, fh)
        path = fh.name
    session = ExchangeSession.from_config(path, source=source)
    session.advance_to(TS)
    session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=2000,
                         order_type=OrderType.LIMIT, limit_price=Decimal("78.0")))
    events = session.advance_to(TS + timedelta(seconds=1))
    filled = sum(e.quantity for e in events
                 if _kind(e) in ("filled", "partially_filled"))
    return filled, session.provenance().fill_policy_kind


def run_j29() -> dict:
    return {
        "optimistic": _filled_under("optimistic"),
        "conservative": _filled_under("conservative"),
        "probabilistic": _filled_under("probabilistic", seed=7),
        "probabilistic_again": _filled_under("probabilistic", seed=7),
    }


@pytest.mark.skipif(not _depth_available(),
                    reason="order-book depth (dev extract) not found")
def test_j29_queue_config_spread():
    obs = run_j29()
    opt, con, prob = obs["optimistic"][0], obs["conservative"][0], obs["probabilistic"][0]

    # The config token moves the fill — the three do not agree.
    assert len({opt, con, prob}) > 1, (opt, con, prob)

    # Optimistic (front of queue) fills at least as much as conservative (back).
    assert opt >= con, (opt, con)
    assert con == 0, con                       # back of the queue, nothing for us

    # Probabilistic is reproducible under a fixed seed.
    assert obs["probabilistic"][0] == obs["probabilistic_again"][0], obs

    # Each run self-reports book_walk + its queue in provenance.
    for name in ("optimistic", "conservative", "probabilistic"):
        prov = obs[name][1]
        assert "book_walk" in prov and name in prov, (name, prov)


if __name__ == "__main__":
    if not _depth_available():
        raise SystemExit("order-book depth (dev extract) not found")
    obs = run_j29()
    print("J29 — Queue policy by config, through the session (FPT, 2022-11-09)")
    for name in ("optimistic", "conservative", "probabilistic"):
        filled, prov = obs[name]
        print(f"  {name:14} filled {filled:>5} of 2000   [{prov}]")
    try:
        test_j29_queue_config_spread()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
