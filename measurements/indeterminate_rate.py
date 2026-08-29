"""F2 -- the indeterminate rate per (data resolution x cause).

The paper's third contribution, made a figure. One population of HSX
instrument-days is run **twice** -- once at BAR resolution under the ``hard``
fill policy, once at TICK resolution under the ``book_walk`` policy -- against
the *same* probe orders, and each run's :meth:`ExchangeSession.indeterminate_report`
is read back. The finding is not a single number but a **shift in the cause**:

* At **BAR** the dominant cause is
  :attr:`DataField.FILL_UNOBSERVABLE_AT_RESOLUTION` -- the market touched the
  order's limit and a daily bar cannot say whether *this* order was ahead in the
  time-priority queue (no order ids; 81% of best-quote changes carry no trade).
  It is the honest floor of a bar backtest and **no amount of additional data
  lowers it -- only a finer resolution does**. That makes it the one
  *resolution-limit* cause on the :class:`DataField` axis.
* At **TICK** that cause is **structurally absent** (the book-walk never emits
  it): a tick knows the instantaneous book, so the touch is decidable. What is
  left is the *data ceiling* -- ``BOOK`` / ``BOOK_SIZE`` / ``VOLUME``, ordinary
  missing fields (an unsized level, a resting price outside the displayed ladder,
  the sized tape this corpus carries for only one instrument-day). A finer
  resolution does **not** fix these; only more complete data does.

So the same axis carries two kinds of ignorance, and refining the resolution
trades one for the other rather than removing it. F2 is that trade, drawn.

**Population.** HSX instrument-days that have BOTH a daily bar (the Parquet
corpus) AND a reconstructed order book (the ``local_quote_*`` tick extract). It
is derived from the corpus, not assumed: :func:`discover_population` intersects
the extract's book days with the daily-bar days. On the machine this was written
for that is **66 instrument-days** -- FPT, HPG and HTV over 2022-10..2022-11,
the only HSX names in the tick extract's ``local_quote`` book. It is a *narrow*
population and is reported as such; F2 is a methodological contrast, not a
liquidity study, and 66 days x a three-order probe is thousands of fill
evaluations -- ample for the rate, whose 95% Wilson interval is reported for
form.

**The probe** (identical at both resolutions, three resting **buy** limits so no
inventory is needed):

* ``buy @ close`` (small) and ``buy @ close`` (mid) -- *touched at limit*. At BAR
  the day's only observed price is the close (the adapter withholds the daily
  high/low), so a buy at the close reaches ``AT`` -> ``FILL_UNOBSERVABLE``. At
  TICK the mid size also exhausts the displayed depth, which the strict queue
  reports as a data-ceiling cause.
* ``buy @ floor`` (small) -- a resting order **below the displayed ladder**. At
  BAR the close is above it and, with no daily low, the trade cannot be ruled
  in or out -> ``LOW`` (a withheld-field, data-ceiling cause). At TICK the strict
  queue cannot size a price with no displayed depth -> ``BOOK_SIZE``.

**Two tick queue arms, because the tick rate depends on the queue assumption**
(which is exactly what F3 measures). ``optimistic`` assumes first-in-queue and
so *decides* most touches, giving the lower rate the headline reports;
``conservative`` refuses to assume the queue and so names the full data ceiling
(``BOOK_SIZE`` + ``VOLUME``) but leaves the rate near the bar's. Both are
reported; both carry **zero** ``FILL_UNOBSERVABLE`` -- that is the structural
point. The figure draws all three arms.

Reuses the strategy suite's own session builders unchanged -- ``build_session``
(the daily ``DataHubSource`` path) and ``_intraday_mm._session`` (the tick
``BookSessionSource`` path) -- so the fill policies and the meter are the shipped
ones, exercised exactly as a user would. Nothing in ``src/`` is touched.

RUN
    .venv/bin/python measurements/indeterminate_rate.py \
        --data-root <parquet> --tick-root <extract> \
        --json figures/f2_indeterminate_rate.json --png figures/f2_indeterminate_rate.png
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pyarrow.parquet as pq

# The session builders live test-side, in ``strategies/`` -- they are the "user's
# own framework", not part of the shipped library (see strategies/_harness.py).
# F2 reuses them verbatim, so put that directory on the path the way pytest does
# for a strategies test. This is import-time and idempotent.
_REPO = Path(__file__).resolve().parent.parent
_STRATEGIES = _REPO / "strategies"
for _p in (str(_REPO), str(_STRATEGIES)):
    if _p not in sys.path:                       # repo root -> ``measurements``;
        sys.path.insert(0, _p)                   # strategies -> the reused builders

from plutus.core.order import OrderType, Side  # noqa: E402
from plutus.market.adapters.datahub import DataHubSource  # noqa: E402
from plutus.market.protocol import Order  # noqa: E402
from plutus.market.session.types import DataField  # noqa: E402

from measurements.band_conformance import wilson_interval  # noqa: E402

__all__ = [
    "ArmResult", "IndeterminateRateResult", "discover_population",
    "measure_indeterminate_rate", "render", "RESOLUTION_LIMIT", "DATA_CEILING",
]

# -- default corpora (the two roots on the authoring machine) ----------------
DEFAULT_BAR_ROOT = "/Users/nadan/algotrade-research/dataset/hermes-parquet"
DEFAULT_TICK_ROOT = "/Users/nadan/algotrade-research/dataset/hermes-dev-extract"

#: The tick extract's HSX equity book lives under this table prefix (the
#: ``local_quote_*`` family, the same one S8/S9 read for FPT). ``quote_*`` in the
#: same extract is the 2025 depth window and the VN30 future -- not HSX equity.
_BOOK_PREFIX = "local_quote"

#: Marks to advance through per day. Each live order is evaluated once per
#: ``advance_to`` that reaches the fill policy, so more marks means more fill
#: evaluations (a tighter interval) at a linear cost. The tick clock is finer so
#: the queue can bite (the S9 rationale), spread across the continuous session.
BAR_MARKS = (time(9, 30), time(10, 30), time(11, 15), time(13, 30),
             time(14, 0), time(14, 45))
TICK_MARKS = (time(9, 30), time(9, 45), time(10, 15), time(10, 45),
              time(11, 15), time(13, 30), time(13, 45), time(14, 0),
              time(14, 30))

#: The probe: ``(price_key, quantity)``. ``close`` -> the day's close (a touched
#: limit); ``floor`` -> the day's floor (a resting order below the ladder).
PROBE = (("close", 1_000), ("close", 30_000), ("floor", 1_000))

#: Cash floor for the securities account -- enough for the mid-size buy on the
#: priciest name in the population (~30k x ~80 x 1000 = ~2.4bn dong).
INITIAL_CASH = 50_000_000_000

# -- the two kinds of ignorance on the DataField axis ------------------------

#: The **resolution-limit** cause: undecidable at a coarse resolution and fixable
#: *only* by a finer one, never by more complete data. Exactly one member.
RESOLUTION_LIMIT: Tuple[DataField, ...] = (
    DataField.FILL_UNOBSERVABLE_AT_RESOLUTION,
)

#: The **data-ceiling** causes: ordinary missing fields, fixable by more complete
#: data at the *same* resolution. Every other DataField that a fill can name.
DATA_CEILING: Tuple[DataField, ...] = (
    DataField.LOW, DataField.HIGH, DataField.OPEN, DataField.CLOSE,
    DataField.LAST, DataField.BOOK, DataField.BOOK_SIZE, DataField.VOLUME,
    DataField.REFERENCE, DataField.CEILING, DataField.FLOOR,
    DataField.SESSION_PHASE, DataField.FOREIGN_ROOM, DataField.SETTLEMENT_PRICE,
)


def cause_class(field_: str) -> str:
    """``'resolution-limit'`` or ``'data-ceiling'`` for a DataField value."""
    return ("resolution-limit"
            if field_ == DataField.FILL_UNOBSERVABLE_AT_RESOLUTION.value
            else "data-ceiling")


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ArmResult:
    """One resolution/policy arm's aggregate over the whole population.

    ``by_cause`` maps a :class:`DataField` value to how many indeterminate fill
    evaluations named it. ``rate`` is ``indeterminate / evaluations`` with a 95%
    Wilson interval ``[ci_low, ci_high]``.
    """

    label: str
    resolution: str
    policy: str
    evaluations: int
    indeterminate: int
    rate: Decimal
    ci_low: Decimal
    ci_high: Decimal
    by_cause: Dict[str, int] = field(default_factory=dict)

    @property
    def resolution_limit_share(self) -> Decimal:
        """Share of *evaluations* named by the resolution-limit cause."""
        if self.evaluations <= 0:
            return Decimal(0)
        n = sum(v for k, v in self.by_cause.items()
                if cause_class(k) == "resolution-limit")
        return Decimal(n) / Decimal(self.evaluations)

    @property
    def data_ceiling_share(self) -> Decimal:
        if self.evaluations <= 0:
            return Decimal(0)
        n = sum(v for k, v in self.by_cause.items()
                if cause_class(k) == "data-ceiling")
        return Decimal(n) / Decimal(self.evaluations)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for key in ("rate", "ci_low", "ci_high"):
            out[key] = float(getattr(self, key))
        out["resolution_limit_share"] = float(self.resolution_limit_share)
        out["data_ceiling_share"] = float(self.data_ceiling_share)
        out["by_cause"] = {
            k: {"count": v,
                "share": float(Decimal(v) / Decimal(self.evaluations))
                if self.evaluations else 0.0,
                "class": cause_class(k)}
            for k, v in sorted(self.by_cause.items())
        }
        return out


@dataclass(frozen=True)
class IndeterminateRateResult:
    """F2 in full: the population, and one :class:`ArmResult` per arm."""

    population: str
    instrument_days: int
    tickers: Dict[str, int]
    arms: List[ArmResult]

    def arm(self, label: str) -> ArmResult:
        for a in self.arms:
            if a.label == label:
                return a
        raise KeyError(label)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "population": self.population,
            "instrument_days": self.instrument_days,
            "tickers": self.tickers,
            "arms": [a.to_dict() for a in self.arms],
            "finding": (
                "Refining bar->tick does not remove the indeterminacy; it "
                "trades the resolution-limit cause "
                "(fill_unobservable_at_resolution, dominant at BAR, "
                "structurally ZERO at TICK) for data-ceiling causes "
                "(book_size/volume). The tick rate depends on the queue "
                "assumption (F3's axis): optimistic decides most touches so the "
                "rate falls; conservative names the full data ceiling so it does "
                "not -- but neither tick arm carries any resolution-limit cause."
            ),
            "backs": (
                "paper's third contribution: the indeterminate rate is a "
                "property of (resolution x data completeness), not a single "
                "backtest number -- and the bar-resolution floor is intrinsic"
            ),
        }


# --------------------------------------------------------------------------
# Population discovery
# --------------------------------------------------------------------------

def _book_days(tick_root: str) -> Dict[str, List[date]]:
    """``ticker -> sorted distinct days`` present in the extract's book."""
    path = Path(tick_root) / f"{_BOOK_PREFIX}_bidprice.parquet"
    if not path.exists():
        return {}
    table = pq.read_table(path, columns=["datetime", "tickersymbol"])
    days: Dict[str, set] = {}
    tickers = table.column("tickersymbol").to_pylist()
    stamps = table.column("datetime").to_pylist()
    for tk, ts in zip(tickers, stamps):
        days.setdefault(tk, set()).add(
            ts.date() if isinstance(ts, datetime) else ts)
    return {tk: sorted(ds) for tk, ds in days.items()}


def discover_population(
    bar_root: str, tick_root: str,
) -> List[Tuple[str, date]]:
    """The measured population: ``(ticker, day)`` with BOTH a book and a bar.

    The book side is the extract's ``local_quote`` ladder (HSX equity only). The
    bar side is a daily close the ``DataHubSource`` can serve on that day with a
    usable band (a ``floor`` for the resting-order probe). Derived, never
    hard-coded -- so a differently-populated extract yields a different, honest
    population.
    """
    source = DataHubSource.for_root(bar_root)
    out: List[Tuple[str, date]] = []
    for ticker, days in sorted(_book_days(tick_root).items()):
        for day in days:
            state = source.state_at(ticker, datetime.combine(day, time(15, 0)))
            if state is None or state.last is None or state.floor is None:
                continue
            out.append((ticker, day))
    return out


# --------------------------------------------------------------------------
# The probe, and the two runs
# --------------------------------------------------------------------------

def _orders(ticker: str, close: Decimal, floor: Decimal) -> List[Order]:
    prices = {"close": close, "floor": floor}
    return [
        Order(ticker=ticker, side=Side.BUY, quantity=qty,
              order_type=OrderType.LIMIT, limit_price=prices[key])
        for key, qty in PROBE
    ]


def _accumulate(report, evals: List[int], indet: List[int],
                causes: Counter) -> None:
    evals[0] += report.evaluations
    indet[0] += report.indeterminate
    for field_, count in report.by_field.items():
        causes[field_.value] += count


def _run_bar(build_session, ticker: str, day: date, close: Decimal,
             floor: Decimal):
    """A daily session under the ``hard`` fill policy -- the DataHubSource path
    from ``strategies/_harness.build_session``, driven directly."""
    cfg = {
        "period": {"start": day.isoformat(),
                   "end": date.fromordinal(day.toordinal() + 1).isoformat()},
        "resolution": "1d",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": INITIAL_CASH,
                                    "account_no": "SEC-F2"}},
        "fill_policy": {"kind": "hard", "max_participation": 0.10},
    }
    session = build_session(cfg)
    session.advance_to(datetime.combine(day, BAR_MARKS[0]))
    for order in _orders(ticker, close, floor):
        session.submit(order)
    for mark in BAR_MARKS[1:]:
        session.advance_to(datetime.combine(day, mark))
    return session.indeterminate_report()


def _run_tick(mm, ticker: str, day: date, close: Decimal, floor: Decimal,
              queue: str):
    """A tick session under the ``book_walk`` policy -- the BookSessionSource
    path from ``strategies/_intraday_mm._session``, driven directly."""
    session, _source = mm._session(
        queue, None, ticker=ticker, venue="HSX", table_prefix=_BOOK_PREFIX,
        initial_cash=INITIAL_CASH, initial_holdings={ticker: 0},
        day=day.isoformat())
    session.advance_to(datetime.combine(day, TICK_MARKS[0]))
    for order in _orders(ticker, close, floor):
        session.submit(order)
    for mark in TICK_MARKS[1:]:
        session.advance_to(datetime.combine(day, mark))
    return session.indeterminate_report()


# --------------------------------------------------------------------------
# The measurement
# --------------------------------------------------------------------------

def measure_indeterminate_rate(
    bar_root: str = DEFAULT_BAR_ROOT,
    tick_root: str = DEFAULT_TICK_ROOT,
    *,
    queues: Sequence[str] = ("optimistic", "conservative"),
    population: Optional[Sequence[Tuple[str, date]]] = None,
    confidence: float = 0.95,
) -> IndeterminateRateResult:
    """Run the same probe at BAR and TICK over the population and aggregate.

    ``queues`` selects which book-walk queue arms to compute at TICK (both, by
    default). ``population`` overrides the discovered set (used by the test to
    run a fast subset). The env vars the reused builders read
    (``PLUTUS_DATA_ROOT`` for the daily band, ``PLUTUS_DEPTH_ROOT`` for the book)
    are pointed at ``bar_root``/``tick_root`` here.
    """
    os.environ["PLUTUS_DATA_ROOT"] = bar_root
    os.environ["PLUTUS_DEPTH_ROOT"] = tick_root

    # Imported here, after the env is set, so the builders bind the right roots.
    from _harness import build_session          # noqa: WPS433 (test-side reuse)
    import _intraday_mm as mm                    # noqa: WPS433

    if population is None:
        population = discover_population(bar_root, tick_root)
    source = DataHubSource.for_root(bar_root)

    bar = ([0], [0], Counter())
    tick = {q: ([0], [0], Counter()) for q in queues}
    per_ticker: Counter = Counter()

    for ticker, day in population:
        state = source.state_at(ticker, datetime.combine(day, time(15, 0)))
        if state is None or state.last is None or state.floor is None:
            continue
        close, floor = state.last, state.floor
        _accumulate(_run_bar(build_session, ticker, day, close, floor), *bar)
        for q in queues:
            _accumulate(_run_tick(mm, ticker, day, close, floor, q),
                        *tick[q])
        per_ticker[ticker] += 1

    def arm(label, resolution, policy, acc) -> ArmResult:
        ev, ind, causes = acc[0][0], acc[1][0], acc[2]
        lo, hi = wilson_interval(ind, ev, confidence=confidence)
        rate = Decimal(ind) / Decimal(ev) if ev else Decimal(0)
        return ArmResult(label=label, resolution=resolution, policy=policy,
                         evaluations=ev, indeterminate=ind, rate=rate,
                         ci_low=lo, ci_high=hi, by_cause=dict(causes))

    arms = [arm("BAR / hard", "bar", "hard", bar)]
    for q in queues:
        arms.append(arm(f"TICK / book-walk ({q})", "tick", f"book_walk:{q}",
                        tick[q]))

    n = sum(per_ticker.values())
    span = ""
    if population:
        lo = min(d for _, d in population)
        hi = max(d for _, d in population)
        span = f", {lo.isoformat()}..{hi.isoformat()}"
    return IndeterminateRateResult(
        population=(
            f"HSX instrument-days with BOTH a daily bar and a reconstructed "
            f"order book (the extract's local_quote ladder -- its only HSX "
            f"equity names): {n} days across {len(per_ticker)} tickers"
            f"{span}. A narrow population by design; F2 is a methodological "
            f"contrast, and {n} days x a three-order probe is thousands of "
            f"fill evaluations"
        ),
        instrument_days=n, tickers=dict(sorted(per_ticker.items())), arms=arms)


# --------------------------------------------------------------------------
# The figure
# --------------------------------------------------------------------------

#: Named, stable colours per cause. The single resolution-limit cause is warm
#: (red); the data-ceiling causes are cool. So the legend's split reads off the
#: colours: warm == "only a finer resolution fixes it", cool == "more data does".
_CAUSE_STYLE = {
    "fill_unobservable_at_resolution": ("#c0392b", "fill unobservable at resolution"),
    "low": ("#2c7fb8", "daily low withheld"),
    "high": ("#3690c0", "daily high withheld"),
    "book": ("#41b6c4", "book absent"),
    "book_size": ("#41b6c4", "book sizes absent"),
    "volume": ("#7fcdbb", "sized tape absent (volume)"),
}
_FALLBACK = ("#bdbdbd", None)


def render(result: IndeterminateRateResult, out: Path) -> Path:
    """One stacked bar per arm; each segment a named cause, its height the cause's
    share of evaluations (so the stack's height is the arm's indeterminate rate).
    Warm = resolution-limit, cool = data-ceiling; the rate and 95% Wilson band
    are annotated. Legends sit outside the plot so nothing is occluded. Headless
    (Agg), theme-neutral."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    out.parent.mkdir(parents=True, exist_ok=True)
    arms = result.arms
    x = range(len(arms))

    fig, ax = plt.subplots(figsize=(max(8.5, 2.6 * len(arms)), 5.6))
    seen: List[Tuple[str, str, str]] = []   # (label, colour, class) in draw order
    for i, a in enumerate(arms):
        bottom = 0.0
        # resolution-limit segment(s) first (bottom, warm), then data-ceiling.
        ordered = sorted(a.by_cause.items(),
                         key=lambda kv: (cause_class(kv[0]) != "resolution-limit",
                                         kv[0]))
        for cause, count in ordered:
            share = count / a.evaluations if a.evaluations else 0.0
            colour, label = _CAUSE_STYLE.get(cause, _FALLBACK)
            label = label or cause
            ax.bar(i, share, bottom=bottom, color=colour, width=0.6,
                   edgecolor="white", linewidth=0.8)
            if share > 0.04:                    # percentage only; names -> legend
                ax.text(i, bottom + share / 2, f"{share:.0%}",
                        ha="center", va="center", fontsize=9, color="white",
                        fontweight="bold")
            if (label, colour) not in {(l, c) for l, c, _ in seen}:
                seen.append((label, colour, cause_class(cause)))
            bottom += share
        # rate + Wilson band above the stack
        ax.annotate(
            f"rate {float(a.rate):.1%}\n[{float(a.ci_low):.0%}, {float(a.ci_high):.0%}]",
            (i, bottom), ha="center", va="bottom", fontsize=9,
            xytext=(0, 5), textcoords="offset points",
            color="#111", fontweight="bold")

    ax.set_xticks(list(x))
    ax.set_xticklabels([a.label.replace(" / ", "\n") for a in arms], fontsize=9)
    ax.set_ylabel("indeterminate share of fill evaluations")
    ax.set_ylim(0, 1.2)
    ax.axhline(1.0, color="#bbb", lw=0.8, ls=":")
    ax.margins(x=0.12)
    ax.set_title(
        "F2 -- indeterminate rate per (resolution x cause)\n"
        f"same {result.instrument_days} HSX instrument-days, one probe, two resolutions",
        fontsize=12)

    # Two legends, both OUTSIDE the axes on the right so bars stay clear. Top:
    # the cause of each segment. Bottom: the class key the whole figure turns on.
    cause_handles = [Patch(facecolor=c, label=l) for l, c, _ in seen]
    class_handles = [
        Patch(facecolor="#c0392b",
              label="resolution-limit\n(only finer resolution fixes)"),
        Patch(facecolor="#41b6c4",
              label="data-ceiling\n(only more data fixes)"),
    ]
    leg1 = ax.legend(handles=cause_handles, title="cause",
                     loc="upper left", bbox_to_anchor=(1.01, 1.0),
                     fontsize=8, title_fontsize=9, framealpha=0.95,
                     borderaxespad=0.0)
    ax.add_artist(leg1)
    ax.legend(handles=class_handles, title="kind of ignorance",
              loc="lower left", bbox_to_anchor=(1.01, 0.0),
              fontsize=8, title_fontsize=9, framealpha=0.95, borderaxespad=0.0)

    fig.subplots_adjust(right=0.72)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=DEFAULT_BAR_ROOT)
    parser.add_argument("--tick-root", default=DEFAULT_TICK_ROOT)
    parser.add_argument("--json", type=Path,
                        default=_REPO / "figures" / "f2_indeterminate_rate.json")
    parser.add_argument("--png", type=Path,
                        default=_REPO / "figures" / "f2_indeterminate_rate.png")
    args = parser.parse_args()

    result = measure_indeterminate_rate(args.data_root, args.tick_root)
    print(f"population : {result.population}")
    print(f"tickers    : {result.tickers}")
    for a in result.arms:
        causes = ", ".join(f"{k}={v}" for k, v in sorted(a.by_cause.items()))
        print(f"\n{a.label}")
        print(f"  evaluations {a.evaluations:,}  indeterminate {a.indeterminate:,}")
        print(f"  rate {float(a.rate):.1%}  95% Wilson "
              f"[{float(a.ci_low):.1%}, {float(a.ci_high):.1%}]")
        print(f"  resolution-limit share {float(a.resolution_limit_share):.1%}  "
              f"data-ceiling share {float(a.data_ceiling_share):.1%}")
        print(f"  by cause: {causes or '(none)'}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result.to_dict(), indent=2))
        print(f"\nwrote {args.json}")
    if args.png:
        render(result, args.png)
        print(f"wrote {args.png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
