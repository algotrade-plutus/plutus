"""Generate F1 -- the order state machine, paper-clean.

Sourced from ``src/plutus/market/session/types.py`` (``OrderState``,
``LEGAL_TRANSITIONS``, ``INITIAL_STATES``, ``TERMINAL_STATES``). Drawn for a
reader, not exhaustively: the happy path runs left to right, the terminal exits
are consolidated to one pair of arrows off the live states ("any live order ->
cancelled / expired") rather than one arrow per state, and INDETERMINATE is
shown once -- an event on RESTING, not a leaf. The consolidation is a drawing
choice, not a claim: every live state does carry both exits in
``LEGAL_TRANSITIONS`` (asserted below, so the figure cannot drift from the code).

    .venv/bin/python figures/f1_state_machine.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

from plutus.market.session.types import (INITIAL_STATES, LEGAL_TRANSITIONS,
                                         LIVE_STATES, TERMINAL_STATES, OrderState)

OUT = Path(__file__).resolve().parent / "f1_order_state_machine.png"

LIVE_FC, LIVE_EC = "#cfe3f7", "#2c7fb8"
TERM_FC, TERM_EC = "#ececec", "#8a8a8a"
INDET = "#6a3d9a"
MAIN = "#333333"
EXIT = "#c0392b"

# The figure asserts these against the code so a transition change breaks the
# render rather than silently producing a stale figure.
assert INITIAL_STATES == {OrderState.ACCEPTED, OrderState.REJECTED}
assert LIVE_STATES == {OrderState.ACCEPTED, OrderState.RESTING,
                       OrderState.PARTIALLY_FILLED}
for _s in (OrderState.ACCEPTED, OrderState.RESTING, OrderState.PARTIALLY_FILLED):
    assert {OrderState.CANCELLED, OrderState.EXPIRED} <= LEGAL_TRANSITIONS[_s], _s
assert OrderState.RESTING in LEGAL_TRANSITIONS[OrderState.ACCEPTED]
assert OrderState.PARTIALLY_FILLED in LEGAL_TRANSITIONS[OrderState.RESTING]
assert OrderState.FILLED in LEGAL_TRANSITIONS[OrderState.PARTIALLY_FILLED]

#: (x, y) centres. Happy path along the top; the two forks/exits below it.
POS = {
    "submit": (0.55, 3.15),
    "ACCEPTED": (2.1, 3.15), "RESTING": (4.35, 3.15),
    "PARTIALLY_FILLED": (6.9, 3.15), "FILLED": (9.25, 3.15),
    "REJECTED": (2.1, 1.35),
    "CANCELLED": (4.35, 1.35), "EXPIRED": (6.9, 1.35),
}


def _box(ax, key, label, live, w=1.55, h=0.66):
    x, y = POS[key]
    fc, ec = (LIVE_FC, LIVE_EC) if live else (TERM_FC, TERM_EC)
    if not live:  # double ring: terminal states are never left
        ax.add_patch(FancyBboxPatch(
            (x - w / 2 - 0.07, y - h / 2 - 0.07), w + 0.14, h + 0.14,
            boxstyle="round,pad=0.02,rounding_size=0.10", fc="none", ec=ec,
            lw=1.0, zorder=2))
    ax.add_patch(FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.10", fc=fc, ec=ec, lw=1.7,
        zorder=3))
    ax.text(x, y, label, ha="center", va="center", fontsize=10.5,
            fontweight="bold", zorder=4)


def _arrow(ax, a, b, *, color=MAIN, lw=1.8, ls="-", rad=0.0, label=None,
           lx=0.0, ly=0.18, fs=9):
    ax.add_patch(FancyArrowPatch(
        a, b, arrowstyle="-|>", mutation_scale=15, color=color, lw=lw,
        linestyle=ls, connectionstyle=f"arc3,rad={rad}", zorder=2,
        shrinkA=2, shrinkB=2))
    if label:
        mx, my = (a[0] + b[0]) / 2 + lx, (a[1] + b[1]) / 2 + ly
        ax.text(mx, my, label, ha="center", va="center", fontsize=fs,
                color=color, style="italic", zorder=5)


def render(out: Path = OUT) -> Path:
    fig, ax = plt.subplots(figsize=(10.5, 4.6))
    ax.set_xlim(-0.2, 10.4)
    ax.set_ylim(0.3, 4.5)
    ax.axis("off")

    # submit fork
    ax.plot(*POS["submit"], "o", color=MAIN, ms=11, zorder=4)
    ax.text(POS["submit"][0], POS["submit"][1] + 0.5, "submit()", ha="center",
            fontsize=10, fontweight="bold")

    for key, label, live in [
        ("ACCEPTED", "ACCEPTED", True), ("RESTING", "RESTING", True),
        ("PARTIALLY_FILLED", "PARTIALLY_FILLED", True), ("FILLED", "FILLED", False),
        ("REJECTED", "REJECTED", False), ("CANCELLED", "CANCELLED", False),
        ("EXPIRED", "EXPIRED", False)]:
        _box(ax, key, label, live)

    E = lambda k: POS[k]
    # happy path
    _arrow(ax, (E("submit")[0] + 0.14, E("submit")[1]), (E("ACCEPTED")[0] - 0.8, E("ACCEPTED")[1]), label="accept")
    _arrow(ax, (E("ACCEPTED")[0] + 0.8, E("ACCEPTED")[1]), (E("RESTING")[0] - 0.8, E("RESTING")[1]), label="rest")
    _arrow(ax, (E("RESTING")[0] + 0.8, E("RESTING")[1]), (E("PARTIALLY_FILLED")[0] - 0.9, E("PARTIALLY_FILLED")[1]), label="partial\nfill", ly=0.28)
    _arrow(ax, (E("PARTIALLY_FILLED")[0] + 0.9, E("PARTIALLY_FILLED")[1]), (E("FILLED")[0] - 0.8, E("FILLED")[1]), color="#1a7a1a", label="fill")
    # a full fill skips PARTIALLY_FILLED -- one light arc, so the path is honest
    _arrow(ax, (E("RESTING")[0] + 0.5, E("RESTING")[1] + 0.33), (E("FILLED")[0] - 0.4, E("FILLED")[1] + 0.35),
           color="#1a7a1a", lw=1.1, rad=-0.28, label="full fill (skips partial)", ly=0.34, fs=8)
    # submit -> rejected fork
    _arrow(ax, (E("submit")[0] + 0.05, E("submit")[1] - 0.1), (E("REJECTED")[0] - 0.75, E("REJECTED")[1] + 0.2), label="reject", lx=-0.15, ly=0.0)

    # consolidated terminal exits off the live band
    band_l, band_r, band_b = E("ACCEPTED")[0] - 0.9, E("PARTIALLY_FILLED")[0] + 0.9, 2.6
    ax.add_patch(Rectangle((band_l, band_b), band_r - band_l, 0.98, fc="none",
                           ec="#b0b0b0", ls=(0, (4, 3)), lw=1.0, zorder=1))
    ax.text(band_l + 0.08, band_b + 0.86, "live", ha="left", va="top",
            fontsize=8.5, color="#888", style="italic")
    _arrow(ax, (E("CANCELLED")[0], band_b), (E("CANCELLED")[0], E("CANCELLED")[1] + 0.4), color=EXIT, lw=1.5, label="cancel", lx=-0.62, ly=0.0)
    _arrow(ax, (E("EXPIRED")[0], band_b), (E("EXPIRED")[0], E("EXPIRED")[1] + 0.4), color=EXIT, lw=1.5, label="expire", lx=0.6, ly=0.0)
    ax.text((band_l + band_r) / 2, band_b - 0.02, "any live order",
            ha="center", va="top", fontsize=8, color=EXIT, style="italic")

    # INDETERMINATE -- the one event that is not a state
    rx, ry = E("RESTING")
    ax.add_patch(FancyArrowPatch((rx - 0.25, ry + 0.34), (rx + 0.25, ry + 0.34),
                                 arrowstyle="-|>", mutation_scale=13, color=INDET,
                                 lw=1.7, linestyle=(0, (3, 2)),
                                 connectionstyle="arc3,rad=-1.7", zorder=4))
    ax.text(rx, ry + 1.02, "INDETERMINATE", ha="center", fontsize=9.5,
            color=INDET, fontweight="bold")
    ax.text(rx, ry + 0.74, "an event, not a leaf:\nthe order stays RESTING",
            ha="center", va="center", fontsize=8, color=INDET, style="italic")

    ax.set_title("Plutus order state machine  --  INDETERMINATE is an event, not a state",
                 fontsize=12, fontweight="bold", pad=10)
    ax.text(5.1, 0.42,
            "live states (blue) hold the encumbrance; terminal states (double ring) are never left.  "
            "Source: session/types.py.",
            ha="center", fontsize=7.6, color="#777")
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


if __name__ == "__main__":
    print("F1 ->", render())
