"""F3 -- cross-policy divergence, joined to the indeterminate rate.

The paper's third contribution, made a figure. The same strategy, run under a
family of shipped policies, gives a *different* history under each -- and each
arm also reports the share of its own flow it could not decide. A backtest that
quotes one policy hides both. Two panels, one per policy axis:

* **fill axis** -- S1 (VN30F mean-reversion) under the three session fill
  policies. ``soft`` fills on the touch and the strategy blows up ~-75%; ``hard``
  and ``probabilistic`` will not fill its market orders so it never trades -- but
  they cannot *decide* half its flow, which the indeterminate rate says out loud.
* **queue axis** -- S8 (intraday maker) under the three book-walk queue
  assumptions. The maker fill moves ~19% across the assumptions, and the
  ``conservative`` arm -- which needs sized subsequent prints this corpus lacks --
  leaves one sixth of its flow indeterminate.

Each arm's ``indeterminate_report().rate`` is read beside its divergence metric,
so the figure carries the divergence and the ignorance together rather than a
single quoted number. Runs on the shipped fixtures (W7), so it reproduces from a
bare clone.

RUN
    .venv/bin/python strategies/test_f3_cross_policy.py   # regenerates data + PNG
    .venv/bin/python -m pytest strategies/test_f3_cross_policy.py -v
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from _harness import data_available
from test_s7_fill_sensitivity import run_s7
from test_s9_queue_sensitivity import run_s9

INITIAL_DEPOSIT = 40_000_000.0
FIGURES = Path(__file__).resolve().parent.parent / "figures"
FILL_ARMS = ("soft", "hard", "probabilistic")
QUEUE_ARMS = ("optimistic", "conservative", "probabilistic")


def _rate(ledger) -> float:
    """The run's indeterminate rate, read back through the public session."""
    session = getattr(ledger, "session", None) or getattr(ledger, "_session", None)
    if session is None:
        return 0.0
    rate = session.indeterminate_report().rate
    return float(rate) if rate is not None else 0.0


def gather() -> Dict[str, Any]:
    """The F3 data: per-arm divergence metric and indeterminate rate."""
    r7 = run_s7()
    fill_axis = {
        name: {
            "end_equity": float(r7[name].equity_curve[-1][1]),
            "return_pct": float(r7[name].equity_curve[-1][1]) / INITIAL_DEPOSIT - 1.0,
            "fills": len(r7[name].fills()),
            "forced": len(r7[name].forced()),
            "indeterminate_rate": _rate(r7[name]),
        }
        for name in FILL_ARMS
    }
    r9 = run_s9()
    queue_axis = {
        name: {
            "maker_shares": r9[name].maker_shares(),
            "taker_shares": r9[name].taker_shares(),
            "indeterminate_rate": _rate(r9[name]),
        }
        for name in QUEUE_ARMS
    }
    return {"fill_axis": fill_axis, "queue_axis": queue_axis}


def render(data: Dict[str, Any], out: Path = None) -> Path:
    """Two-panel F3: the divergence metric as bars, the indeterminate rate on
    each. Written headless (Agg), theme-neutral, with the numbers on the bars so
    the figure is inspectable without the JSON."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = out or (FIGURES / "f3_cross_policy_divergence.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))

    # Panel 1: fill axis -- % return per policy, indeterminate rate annotated.
    fa = data["fill_axis"]
    returns = [fa[n]["return_pct"] * 100 for n in FILL_ARMS]
    bars = ax1.bar(FILL_ARMS, returns, color=["#c0392b", "#2c7fb8", "#7fb800"])
    ax1.axhline(0, color="#888", lw=0.8)
    ax1.set_title("Fill axis: S1 under three fill policies")
    ax1.set_ylabel("strategy return (%)")
    for n, b in zip(FILL_ARMS, bars):
        ax1.annotate(f"indet {fa[n]['indeterminate_rate']:.0%}",
                     (b.get_x() + b.get_width() / 2, b.get_height()),
                     ha="center", va="bottom" if b.get_height() >= 0 else "top",
                     fontsize=9, color="#333")

    # Panel 2: queue axis -- maker shares per queue, indeterminate rate annotated.
    qa = data["queue_axis"]
    shares = [qa[n]["maker_shares"] for n in QUEUE_ARMS]
    bars2 = ax2.bar(QUEUE_ARMS, shares, color=["#7fb800", "#c0392b", "#2c7fb8"])
    ax2.set_title("Queue axis: S8 under three queue assumptions")
    ax2.set_ylabel("maker shares filled")
    for n, b in zip(QUEUE_ARMS, bars2):
        ax2.annotate(f"indet {qa[n]['indeterminate_rate']:.0%}",
                     (b.get_x() + b.get_width() / 2, b.get_height()),
                     ha="center", va="bottom", fontsize=9, color="#333")

    fig.suptitle("F3 -- cross-policy divergence, joined to the indeterminate rate",
                 fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


@pytest.mark.skipif(not data_available(),
                    reason="strategy data not found")
def test_f3_cross_policy_divergence():
    data = gather()
    fa, qa = data["fill_axis"], data["queue_axis"]

    # Fill axis: the policies do NOT agree -- soft trades and blows up, the
    # strict two never trade -- and the strict two say how much they could not
    # decide (a market-order flow they refuse), which soft hides as fills.
    assert fa["soft"]["fills"] > 0 and fa["soft"]["return_pct"] < -0.5
    assert fa["hard"]["fills"] == 0
    assert fa["hard"]["indeterminate_rate"] > 0.3
    assert fa["soft"]["indeterminate_rate"] < fa["hard"]["indeterminate_rate"]

    # Queue axis: the maker fill moves materially across the assumptions, and the
    # conservative arm leaves a real share indeterminate where the others do not.
    spread = (qa["optimistic"]["maker_shares"] - qa["conservative"]["maker_shares"]) \
        / qa["optimistic"]["maker_shares"]
    assert spread > 0.15
    assert qa["conservative"]["indeterminate_rate"] > 0.1
    assert qa["optimistic"]["indeterminate_rate"] == 0.0


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("strategy data not found")
    data = gather()
    (FIGURES).mkdir(parents=True, exist_ok=True)
    (FIGURES / "f3_cross_policy_divergence.json").write_text(json.dumps(data, indent=2))
    png = render(data)
    print("F3 -- cross-policy divergence, joined to the indeterminate rate")
    for name in FILL_ARMS:
        d = data["fill_axis"][name]
        print(f"  fill:{name:14} return={d['return_pct']:+.1%}  fills={d['fills']}"
              f"  indeterminate={d['indeterminate_rate']:.1%}")
    for name in QUEUE_ARMS:
        d = data["queue_axis"][name]
        print(f"  queue:{name:13} maker_shares={d['maker_shares']:>7}"
              f"  indeterminate={d['indeterminate_rate']:.1%}")
    print(f"  -> {png}")
