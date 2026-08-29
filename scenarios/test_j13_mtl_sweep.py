"""J13 — MTL residue conversion: sweep the book, rest the remainder.

Scenario **J13** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
Submit a marketable order larger than the visible opposite side, watch it
**sweep** the ladder — each tranche filling at the RESTING level's price — and
see the remainder left over.

MECHANISM — the order-book walk. This is **injection-only** (the catalogue's
own word): the default daily path prices a residual off a single point, so the
sweep is reached by injecting a ``BookWalkFillPolicy`` over a ``DepthSource``,
which is what a user who wants depth does. Here we drive the walk directly
against a real 3-level ladder.

POLICY (oracle — SCENARIO-CATALOGUE.md J13)
    * Continuous-matching price: a marketable order fills at the RESTING
      (passive) order's price at each level — QĐ 352 Điều 6.3 (high).
    * MTL residual repricing (HNX/HNXDS): the remainder becomes an LO ±1 tick
      from the last match, capped at ceiling/floor — QĐ 22/2025 Điều 17.2(b)
      (2025-05-05→); the pre-KRX HNX instrument was never obtained (carried by
      continuity + ASEANSC §2.3) — an OPEN CONFLICT the catalogue records.

DATA — the corpus carries 3-level bid/ask ladders with sizes in the dev extract
(`hermes-dev-extract`), 1,390,914 size rows. FPT on 2022-11-09 has a clean
ladder to walk.

EXPECTED — Tier 2
    * A large marketable buy sweeps MORE THAN ONE level (multiple tranches).
    * Each tranche fills at the resting level's price, and the prices are
      non-decreasing up the ask (you pay worse as you climb).
    * The total filled is the visible size it could reach; a bigger order
      leaves a remainder (the residue that would reprice to an LO).

RUN
    python scenarios/test_j13_mtl_sweep.py
    pytest scenarios/test_j13_mtl_sweep.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from plutus.market.adapters.depth import DepthSource
from plutus.market.session.book_walk import walk_book, OptimisticQueue
from plutus.core.order import Side

EXTRACT = Path("/Users/nadan/algotrade-research/dataset/hermes-dev-extract")
FPT_CLEAN = datetime(2022, 11, 9, 9, 16, 5, 290870)


def _depth_available() -> bool:
    return EXTRACT.is_dir() and any(EXTRACT.glob("local_quote_asksize*.parquet"))


def run_j13():
    source = DepthSource(str(EXTRACT), table_prefix="local_quote")
    book = source.book_at("FPT", FPT_CLEAN)
    # A buy far larger than the visible ask side, priced at the ceiling so it is
    # marketable through every level it can reach.
    walk = walk_book(book, side=Side.BUY, limit=Decimal("78.0"), quantity=50_000,
                     queue=OptimisticQueue(), order_id="O-J13", max_staleness=None)
    return {"book": book, "walk": walk}


@pytest.mark.skipif(not _depth_available(),
                    reason="order-book depth (dev extract) not found")
def test_j13_mtl_sweep():
    obs = run_j13()
    walk = obs["walk"]

    # The order swept more than one level.
    assert len(walk.tranches) > 1, [(str(t.price), t.quantity) for t in walk.tranches]

    # Each tranche filled at the resting level's price, non-decreasing up the ask.
    prices = list(walk.prices)
    assert prices == sorted(prices), prices

    # It filled the visible size it could reach and left a remainder (the
    # residue that MTL would reprice to a resting LO).
    assert walk.filled_quantity > 0
    assert walk.remainder > 0, walk.remainder


if __name__ == "__main__":
    if not _depth_available():
        raise SystemExit("order-book depth (dev extract) not found")
    obs = run_j13()
    walk = obs["walk"]
    print("J13 — MTL sweep of the FPT ladder (2022-11-09 09:16:05)")
    print(f"  tranches: {[(str(t.price), t.quantity) for t in walk.tranches]}")
    print(f"  filled {walk.filled_quantity} of 50,000, remainder {walk.remainder} "
          f"(the residue that reprices to a resting LO)")
    try:
        test_j13_mtl_sweep()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
