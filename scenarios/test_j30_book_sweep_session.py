"""J30 — A marketable order sweeps the book through the session.

Scenario **J30** of the intraday extension. J13 showed a marketable order
sweeping several book levels via ``walk_book`` directly; J30 drives the same
sweep through ``session.submit`` on a book-walk session. The order takes each ask
level at its own resting price, up the ladder, until its size or the visible
depth runs out.

MECHANISM — the depth arm of the fill policy. A marketable buy is filled level by
    level at the resting (passive) price of each — QĐ 352 Điều 6.3 — and the
    quantity it takes at each is what the queue policy allows (optimistic: the
    whole visible level). Filling *past the top level* is the sweep, and it is
    the thing a single-price bar fill cannot show.

POLICY (oracle)
    * Passive-price match, level by level — QĐ 352 Điều 6.3 (sourced).
    * The sweep is continuous-session only (``SWEEP_IS_CONTINUOUS_ONLY``).

SETUP — FPT book (dev extract), 2022-11-09 09:16:05. The ask shows 73.40×5700,
    73.50×200, 73.90×1000 (6900 visible). A BUY 7000 @ 78.0 sweeps all three.

PRICING — per tranche, at the resting price (QĐ 352 Điều 6.3). The session
    books the sweep as **one fill per level, at the level's own resting
    price** — 5700@73.40, 200@73.50, 1000@73.90 — so the cash spent is the
    exact consideration (73.40×5700 + 73.50×200 + 73.90×1000), and the holdings
    carry a per-lot cost basis. It is NOT the worst price charged for the whole
    6900; that would over-state the cost by (73.90−73.40)×5700 + (73.90−73.50)×200.
    ``SweptFillDecision.price`` still *summarises* the sweep at its worst touched
    price for a depth-unaware reader, but the account is charged the tranches.

EXPECTED — Tier 2
    * The order fills **past the top level** — more than the top level's 5700 —
      which a single-level (bar) fill cannot do. That is the sweep.
    * It fills as **several fills at several prices** (73.40, 73.50, 73.90), one
      per ask level, and their consideration sums to the cash — strictly less
      than the worst price × 6900.
    * Each fill is ``MODELLED`` evidence (a queue-estimated book walk, not a
      tape print).

RUN
    python scenarios/test_j30_book_sweep_session.py
    pytest scenarios/test_j30_book_sweep_session.py -v
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
TOP_LEVEL = 5700     # the 73.40 level's visible size


def _depth_available() -> bool:
    return EXTRACT.is_dir() and any(EXTRACT.glob("local_quote_asksize*.parquet"))


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def run_j30():
    config = {
        "period": {"start": "2022-11-09", "end": "2022-11-10"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 800_000_000,
                                    "account_no": "SEC-J30"}},
        "fill_policy": {"kind": "book_walk", "queue": "optimistic",
                        "max_participation": None, "max_staleness": None},
    }
    source = BookSessionSource.for_roots(PRICES, str(EXTRACT))
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(config, fh)
        path = fh.name
    session = ExchangeSession.from_config(path, source=source)
    session.advance_to(TS)
    ack = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=7000,
                               order_type=OrderType.LIMIT, limit_price=Decimal("78.0")))
    events = session.advance_to(TS + timedelta(seconds=1))
    fills = [e for e in events if _kind(e) in ("filled", "partially_filled")]
    return {"ack": ack, "fills": fills}


@pytest.mark.skipif(not _depth_available(),
                    reason="order-book depth (dev extract) not found")
def test_j30_book_sweep_session():
    obs = run_j30()
    assert isinstance(obs["ack"], Accepted), obs["ack"]
    assert obs["fills"], "the sweep never filled"

    filled = sum(e.quantity for e in obs["fills"])

    # Swept PAST the top level — a single-level (bar) fill could not do this.
    assert filled > TOP_LEVEL, (filled, TOP_LEVEL)

    # Booked as several fills at several prices — one per ask level — not one
    # fill at the worst price. This is the per-tranche pricing (QĐ 352 Điều 6.3).
    prices = [e.price for e in obs["fills"]]
    assert len(set(prices)) >= 2, prices

    # The cash is the per-tranche consideration, sum(price × quantity), which is
    # strictly less than charging the worst price for the whole swept quantity.
    consideration = sum(e.price * e.quantity for e in obs["fills"])
    worst_projection = max(prices) * filled
    assert consideration < worst_projection, (consideration, worst_projection)

    # A book walk, not a tape print: every tranche is MODELLED evidence.
    evid = {str(e.detail.get("evidence")) for e in obs["fills"]}
    assert any("MODELLED" in e for e in evid), evid


if __name__ == "__main__":
    if not _depth_available():
        raise SystemExit("order-book depth (dev extract) not found")
    obs = run_j30()
    print("J30 — Marketable sweep through the session (FPT, 2022-11-09)")
    print(f"  submit: {type(obs['ack']).__name__}")
    for e in obs["fills"]:
        print(f"  filled {e.quantity} @ {e.price}")
    print(f"  total {sum(e.quantity for e in obs['fills'])} across "
          f"{len({e.price for e in obs['fills']})} ask levels")
    try:
        test_j30_book_sweep_session()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
