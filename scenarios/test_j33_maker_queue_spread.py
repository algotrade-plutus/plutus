"""J33 — One tape, three fills: the queue assumption moves the maker.

Scenario **J33** of the intraday extension, and the reason the queue axis
exists. J29 showed the queue policy moving a *taker* sweep. J33 shows it moving
a *maker* fill on the tape — the same resting order, the same prints through its
price, three different fills depending only on **where in the queue we assume we
stand**. This is the knob history cannot resolve (a reconstructed book has no
order ids), so it is declared, stamped in provenance, and — this scenario —
measured.

THE AUTHOR'S EXAMPLE, on real data. FPT, 2022-11-09. A SELL of 6,000 is posted
    at **73.40** at 09:16:05, when **5,800 shares are already displayed** at that
    price (the queue ahead). By 09:20 **6,800 shares have printed** at or through
    73.40 — just past the visible queue. So:

    * **Optimistic** (we are at the front): all 6,800 are ours to take, capped at
      the order — filled **6,000**.
    * **Conservative** (we are at the back): the first 5,800 clear the queue
      ahead, leaving **1,000** — filled 1,000.
    * **Probabilistic** (a seeded draw in between): filled between the two,
      reproducibly.

MECHANISM — the maker arm reads the displayed size at the order's price as of
    arrival (the queue ahead), the tape totals the prints since, and the queue
    policy places the order in that queue. ``maker_fill`` books
    ``clamp(prints − ahead, 0, order)``. The fill price is 73.40 (the posted
    price); the queue is the only thing that changes between the three runs.

POLICY (oracle) — the queue position is UNSOURCED, our modelling choice, named
    in ``fill_policy.queue`` and stamped in ``SessionProvenance``. Optimistic and
    conservative are the bounds; probabilistic interpolates, seeded.

EXPECTED — Tier 2
    * The three queues give **three different fills** — the spread is real.
    * Optimistic (6,000) > conservative (1,000): the front fills more than the
      back, as the axis requires.
    * Probabilistic lies **between** the two and is reproducible under its seed.
    * Each run's provenance names ``book_walk`` and its queue.

RUN
    python scenarios/test_j33_maker_queue_spread.py
    pytest scenarios/test_j33_maker_queue_spread.py -v
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
PRICE = Decimal("73.40")
QUANTITY = 6000
SUBMIT = datetime(2022, 11, 9, 9, 16, 5)     # 5,800 displayed ahead at 73.40
END = datetime(2022, 11, 9, 9, 20, 0)        # 6,800 printed through by here


def _tape_available() -> bool:
    return EXTRACT.is_dir() and (EXTRACT / "local_quote_total.parquet").exists()


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def _filled_under(queue: str, seed=None) -> tuple:
    """Run the identical resting SELL under one queue; return (filled, prov)."""
    fill_policy = {"kind": "book_walk", "queue": queue,
                   "max_participation": None, "max_staleness": None}
    if seed is not None:
        fill_policy["seed"] = seed
    config = parse_config({
        "period": {"start": "2022-11-09", "end": "2022-11-10"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 200_000_000,
                                    "account_no": "SEC-J33"}},
        "fill_policy": fill_policy,
    })
    source = BookSessionSource.for_roots(PRICES, str(EXTRACT))
    session = ExchangeSession.build(config, source=source,
                                    initial_holdings={TICKER: QUANTITY})
    session.advance_to(SUBMIT)
    session.submit(Order(ticker=TICKER, side=Side.SELL, quantity=QUANTITY,
                         order_type=OrderType.LIMIT, limit_price=PRICE))
    events = session.advance_to(END)
    filled = sum(e.quantity for e in events
                 if _kind(e) in ("filled", "partially_filled"))
    return filled, session.provenance().fill_policy_kind


def run_j33() -> dict:
    return {
        "optimistic": _filled_under("optimistic"),
        "conservative": _filled_under("conservative"),
        "probabilistic": _filled_under("probabilistic", seed=7),
        "probabilistic_again": _filled_under("probabilistic", seed=7),
    }


@pytest.mark.skipif(not _tape_available(),
                    reason="sized tape (local_quote_total) not found")
def test_j33_maker_queue_spread():
    obs = run_j33()
    opt = obs["optimistic"][0]
    con = obs["conservative"][0]
    prob = obs["probabilistic"][0]

    # The bounds are the author's example, exactly.
    assert opt == 6000, opt          # front of queue: the whole order
    assert con == 1000, con          # back of queue: only what cleared 5,800

    # Three different fills from one tape -- the queue assumption is the spread.
    assert opt > con, (opt, con)
    assert con <= prob <= opt, (con, prob, opt)

    # Probabilistic interpolates and is reproducible under its seed. The STRICT
    # interior holds for the pinned seed 7 (fill 2,500); ~14% of seeds draw a
    # position that clamps onto a bound, so this inequality is seed-specific by
    # design, not a general guarantee -- the axis property is the range above.
    assert con < prob < opt, (con, prob, opt)
    assert obs["probabilistic"][0] == obs["probabilistic_again"][0]

    # Each run self-reports book_walk + its queue.
    for name in ("optimistic", "conservative", "probabilistic"):
        prov = obs[name][1]
        assert "book_walk" in prov and name in prov, (name, prov)


if __name__ == "__main__":
    if not _tape_available():
        raise SystemExit("sized tape (local_quote_total) not found")
    obs = run_j33()
    print("J33 — Maker queue spread on one tape (FPT, SELL 6000 @ 73.40)")
    print("  5,800 displayed ahead at 09:16:05; 6,800 printed through by 09:20")
    for name in ("optimistic", "conservative", "probabilistic"):
        filled, prov = obs[name]
        print(f"  {name:14} filled {filled:>5} of {QUANTITY}   [{prov}]")
    try:
        test_j33_maker_queue_spread()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
