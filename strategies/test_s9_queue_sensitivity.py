"""S9 — What the queue assumption is worth: the same maker, three fidelities.

Strategy **S9**, and the honest headline of the whole intraday effort. A maker
fill depends on **where in the queue** we assume the order stood — a fact a
reconstructed book cannot recover (no order ids). So we do not pick one; we
declare it, and S9 measures what the choice is worth by running the S8
market-maker, on the same FPT day, under all three queue assumptions and reading
the spread in the **maker** fills.

**A controlled experiment.** A market-maker's *decisions* normally depend on its
own fills (it skews its quotes as inventory moves), and its fills depend on the
queue — so naively re-running it would let the queue change the decisions too,
confounding the measurement. S9 removes that feedback: it runs the maker with the
inventory skew **off** and enough inventory that the T+2 ask-guard never bites,
so the quote is a pure function of the market and is **identical** across the
three runs. The only thing that differs is the queue assumption — so the spread
in the fills is what the queue assumption alone is worth.

**Only the maker fills count.** A quote the market happens to cross fills as a
taker sweep, which the queue axis does not govern; S9 measures ``maker_shares``
(fills at the order's own posted price) so the number is the maker queue effect,
not a taker artifact.

THE AXIS (measured, 2022-11-09, ~15-minute cadence so per-interval prints are
    comparable to the depth queued ahead):
    * **optimistic** — front of the queue — fills the **most**;
    * **conservative** — behind the whole displayed queue — the **least**;
    * **probabilistic** — a seeded draw — **between**, reproducibly.

Each run still **conserves đồng** independently.

EXPECTED — Tier 2
    * The three queues fill **different** maker amounts: the assumption alone
      moves the result.
    * optimistic > conservative (front fills more than back), probabilistic
      between; the spread is **material** (> 15% of the optimistic maker fill).
    * The decisions were queue-independent (the ask-guard never fired), so the
      spread is the queue's, not the strategy's.
    * Every run conserves đồng and self-reports its queue.

RUN
    python strategies/test_s9_queue_sensitivity.py
    pytest strategies/test_s9_queue_sensitivity.py -v
"""
from __future__ import annotations

import pytest

from _intraday_mm import InventoryMarketMaker, run_market_maker, tape_available, FINE_MARKS

TARGET = 400000        # ample inventory: the T+2 ask-guard never bites
SIZE = 20000           # sized so the queue-ahead bites hard -> a wide spread


def _run(queue: str, seed=None):
    # skew OFF + ample inventory -> the quote is a pure function of the market,
    # identical across queues; only the fill differs.
    mm = InventoryMarketMaker(ticker="FPT", target=TARGET, band=10 ** 9,
                              size=SIZE, skew=False)
    return run_market_maker(mm, queue=queue, seed=seed, marks=FINE_MARKS)


def run_s9() -> dict:
    return {
        "optimistic": _run("optimistic"),
        "conservative": _run("conservative"),
        "probabilistic": _run("probabilistic", seed=7),
    }


@pytest.mark.skipif(not tape_available(),
                    reason="sized tape (local_quote_total) not found")
def test_s9_queue_sensitivity():
    runs = run_s9()
    opt = runs["optimistic"].maker_shares()
    con = runs["conservative"].maker_shares()
    prob = runs["probabilistic"].maker_shares()

    # The queue assumption alone moves the MAKER fill -- same strategy, same
    # data, decisions held fixed.
    assert len({opt, con, prob}) > 1, (opt, con, prob)

    # Front of queue fills the most, the back the least, the draw between.
    assert opt > con, (opt, con)
    assert con <= prob <= opt, (con, prob, opt)

    # The spread is material -- the number a backtester hides by picking one arm.
    # opt/con are deterministic (neither uses the seed), so this measures ~18.9%
    # on the pinned 2022-11-09 tape; the 0.15 floor leaves ~4 points of margin so
    # incidental upstream drift can't silently erode it, while anything that moves
    # it below 15% is a real regression worth failing on.
    assert (opt - con) / opt > 0.15, (opt, con)

    for name, led in runs.items():
        # The decisions were queue-independent: the ask-guard never fired, so
        # the quote never depended on the (queue-dependent) fills. This is what
        # makes the spread attributable to the queue and nothing else.
        settled_floor = min(row["settled"] for row in led.inventory)
        assert settled_floor > SIZE, (name, settled_floor)
        # And each run conserves đồng and names its queue.
        change, identity, _ = led.conservation()
        assert change == identity, (name, change, identity)
        assert "book_walk" in led.provenance and name in led.provenance


if __name__ == "__main__":
    if not tape_available():
        raise SystemExit("sized tape not found")
    runs = run_s9()
    print("S9 — What the queue assumption is worth (FPT maker, 2022-11-09)")
    for name in ("optimistic", "conservative", "probabilistic"):
        led = runs[name]
        print(f"  {name:14} maker filled {led.maker_shares():>6} shares"
              f"   (taker, incidental: {led.taker_shares()})")
    opt = runs["optimistic"].maker_shares()
    con = runs["conservative"].maker_shares()
    print(f"  the queue assumption alone moves the maker fill by "
          f"{(opt - con) / opt:.0%} (optimistic vs conservative)")
    try:
        test_s9_queue_sensitivity()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
