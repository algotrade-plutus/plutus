"""E1 -- population-level fill-policy divergence (the taker panel).

Spec: ``docs/reference/EXPERIMENT-E1-FILL-DIVERGENCE.md``. Replaces the old
three-strategy return sweep, which was sign-confounded (the strategies lose money
*when* they fill), rested on 4-5 fills, and reported P&L -- the one quantity the
library's own :class:`DivergenceReport` forbids.

**Question.** Over a realistic order flow, what share of fill decisions is set by
the *assumption* rather than by the market, and how much executed quantity does
the assumption move?

**Design.** Hold everything fixed except the fill policy. Over HSX equities in
2022 (post the 2021-01-04 lot change, so one undated ``HSX_EXCHANGE`` is correct
and dating is not a second variable), take five order intents per ticker-day --
all priced off the corpus's own on-grid values so tick-grid rejection never
confounds the comparison -- and evaluate every one under ``soft`` / ``hard`` /
``probabilistic`` with :func:`compare_policies`. That is ~hundreds of thousands of
sign-free questions.

**Reported** (all from :class:`DivergenceReport`, none of them P&L): the headline
``agreement_rate`` (its complement is the share of a realistic flow whose outcome
is the assumption's, not the market's); per-policy outcome / indeterminate /
filled-quantity; and the **by-intent** breakdown -- the interpretable result,
which should show market orders diverging ~always and deep passive limits agreeing
~always ("your exposure to this assumption is a function of your order mix").

Requires only the daily Parquet corpus, and (per the spec's blocker, now fixed)
the ``DataHubSource`` that serves the day's high/low. Runs in one batched load
plus one :func:`compare_policies` per ticker, so the ~100k-question population is
minutes, not the half-hour a per-day ``interval()`` would cost.

RUN
    .venv/bin/python -m measurements.fill_divergence \
        --data-root <parquet> --json figures/e1_fill_divergence.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from plutus.core.order import OrderType, Side  # noqa: E402
from plutus.market.protocol import Order  # noqa: E402 (the fill-machinery Order)
from plutus.market.adapters.datahub import DataHubSource  # noqa: E402
from plutus.market.exchanges.equity import HSX_EXCHANGE  # noqa: E402
from plutus.market.session.fills import (FillQuestion, HardFillPolicy,  # noqa: E402
                                         ProbabilisticFillPolicy, SoftFillPolicy,
                                         compare_policies)
from plutus.market.session.types import (DataField, FillOutcome,  # noqa: E402
                                         MarketInterval, OrderRecord, OrderState,
                                         Resolution, TimeInForce, Venue)

DEFAULT_ROOT = "/Users/nadan/algotrade-research/dataset/hermes-parquet"
YEAR = 2022
MIN_SESSIONS = 200
CAP = Decimal("0.10")           # same participation cap as the S7 arms
SEED = 7
QUANTITY = 1_000                # a valid HSX lot (unit 100); the *decision*, not
                                # the size, is the axis -- the cap rarely binds here

#: The five intents, priced off the corpus's own on-grid values. ``price_key`` is
#: read from the built ``MarketState``; ``None`` is a market order (no price).
INTENTS: Tuple[Tuple[str, Side, OrderType, Optional[str]], ...] = (
    ("market_buy", Side.BUY, OrderType.MARKET, None),
    ("limit_buy_at_close", Side.BUY, OrderType.LIMIT, "last"),
    ("limit_sell_at_close", Side.SELL, OrderType.LIMIT, "last"),
    ("limit_buy_at_floor", Side.BUY, OrderType.LIMIT, "floor"),
    ("limit_sell_at_ceil", Side.SELL, OrderType.LIMIT, "ceiling"),
)


def _policies():
    """The three shipped policies, distinct signatures, same cap as S7."""
    return [SoftFillPolicy(CAP), HardFillPolicy(CAP),
            ProbabilisticFillPolicy(SEED, max_participation=CAP)]


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------

@dataclass
class _PolicyAgg:
    outcomes: Counter = field(default_factory=Counter)  # FillOutcome -> n
    filled_quantity: int = 0


@dataclass
class _IntentAgg:
    n: int = 0
    agreed: int = 0
    filled: Counter = field(default_factory=Counter)         # sig -> n FILLED
    indeterminate: Counter = field(default_factory=Counter)  # sig -> n INDETERMINATE


@dataclass(frozen=True)
class FillDivergenceResult:
    population: str
    tickers: int
    ticker_days: int
    questions: int
    signatures: Tuple[str, ...]
    agreed: int
    by_policy: Dict[str, _PolicyAgg]
    by_intent: Dict[str, _IntentAgg]

    @property
    def agreement_rate(self) -> Decimal:
        return (Decimal(self.agreed) / Decimal(self.questions)
                if self.questions else Decimal(0))

    def to_dict(self) -> dict:
        q = self.questions or 1
        return {
            "population": self.population,
            "tickers": self.tickers,
            "ticker_days": self.ticker_days,
            "questions": self.questions,
            "signatures": list(self.signatures),
            "agreement_rate": float(self.agreement_rate),
            "by_policy": {
                sig: {
                    "outcomes": {o.value: agg.outcomes.get(o, 0)
                                 for o in FillOutcome},
                    "indeterminate_rate": agg.outcomes.get(
                        FillOutcome.INDETERMINATE, 0) / q,
                    "filled_quantity": agg.filled_quantity,
                }
                for sig, agg in self.by_policy.items()
            },
            "by_intent": {
                intent: {
                    "n": a.n,
                    "agreement_rate": (a.agreed / a.n) if a.n else 0.0,
                    "divergence_rate": (1 - a.agreed / a.n) if a.n else 0.0,
                    "filled_by_policy": {s: a.filled.get(s, 0)
                                         for s in self.signatures},
                    "indeterminate_by_policy": {s: a.indeterminate.get(s, 0)
                                                for s in self.signatures},
                }
                for intent, a in self.by_intent.items()
            },
            "finding": (
                "Over a realistic HSX order flow the three shipped fill policies "
                "disagree on a material share of decisions, and the disagreement "
                "is concentrated in market and marketable-limit orders; deep "
                "passive limits are decided by the market, not the assumption. "
                "Reported as fills, never P&L (DivergenceReport's contract)."
            ),
        }


# --------------------------------------------------------------------------
# Universe + batched load
# --------------------------------------------------------------------------

def discover_universe(src: DataHubSource, *, year: int = YEAR,
                      min_sessions: int = MIN_SESSIONS,
                      max_tickers: Optional[int] = None) -> List[str]:
    """HSX ``instrumenttype='stock'`` tickers with >= ``min_sessions`` in ``year``."""
    close, tk = src._reader("close_price"), src._reader("ticker_metadata")
    if close is None or tk is None:
        return []
    rows = src._conn.execute(f"""
        SELECT c.tickersymbol, count(DISTINCT c.datetime) AS n
        FROM {close} c JOIN {tk} tk USING (tickersymbol)
        WHERE tk.exchangeid = 'HSX' AND tk.instrumenttype = 'stock'
          AND c.datetime >= '{year}-01-01' AND c.datetime < '{year + 1}-01-01'
        GROUP BY c.tickersymbol HAVING count(DISTINCT c.datetime) >= {min_sessions}
        ORDER BY n DESC, c.tickersymbol
    """).fetchall()
    names = [r[0] for r in rows]
    return names[:max_tickers] if max_tickers else names


def _load_bars(src: DataHubSource, tickers: Sequence[str], year: int
               ) -> Dict[str, List[tuple]]:
    """``ticker -> [(day, close, open, high, low, ceil, floor, ref, volume)]``.

    One batched, LEFT-JOINed query for the whole universe -- the high/low are the
    session extremes ``quote_max``/``quote_min``, exactly what the wired
    ``interval()`` serves, so building the interval from this row is faithful.
    """
    rd = src._reader
    close = rd("close_price")
    parts, joins = [], []
    for f, alias, col in (("open_price", "op", "open"), ("max_price", "mx", "high"),
                          ("min_price", "mn", "low"), ("ceiling_price", "ce", "ceil"),
                          ("floor_price", "fl", "floor"), ("ref_price", "rf", "ref")):
        r = rd(f)
        parts.append(f"{alias}.price AS {col}" if r else f"NULL AS {col}")
        if r:
            joins.append(f"LEFT JOIN {r} {alias} USING (datetime, tickersymbol)")
    vol = rd("daily_volume")
    parts.append("vo.quantity AS volume" if vol else "NULL AS volume")
    if vol:
        joins.append(f"LEFT JOIN {vol} vo USING (datetime, tickersymbol)")
    names = ",".join(f"'{t}'" for t in tickers)
    rows = src._conn.execute(f"""
        SELECT c.tickersymbol, c.datetime, c.price AS close, {', '.join(parts)}
        FROM {close} c {' '.join(joins)}
        WHERE c.tickersymbol IN ({names})
          AND c.datetime >= '{year}-01-01' AND c.datetime < '{year + 1}-01-01'
        ORDER BY c.tickersymbol, c.datetime
    """).fetchall()
    out: Dict[str, List[tuple]] = defaultdict(list)
    for tk, ts, *vals in rows:
        d = ts.date() if isinstance(ts, datetime) else ts
        out[tk].append((d, *vals))
    return out


def _interval(src, ticker, day, spec, close, open_, high, low, ceil, floor,
              ref, volume) -> MarketInterval:
    """Build the OHLC interval from a batched row, via the adapter's own state."""
    def dec(v):
        return None if v is None else Decimal(str(v))
    o, hi, lo = dec(open_), dec(high), dec(low)
    state = src._build_state(ticker, datetime.combine(day, time(15, 0)),
                             close, ceil, floor, ref, spec)
    missing = set(src.WITHHELD)
    if volume is None:
        missing.add(DataField.VOLUME)
    if o is None:
        missing.add(DataField.OPEN)
    if hi is None:
        missing.add(DataField.HIGH)
    if lo is None:
        missing.add(DataField.LOW)
    if state.last is None:
        missing.add(DataField.CLOSE)
        missing.add(DataField.LAST)
    return MarketInterval(
        ticker=ticker, start=datetime.combine(day, time(9, 15)),
        end=datetime.combine(day, time(15, 0)), resolution=Resolution.DAILY,
        state=state, open=o, high=hi, low=lo, close=state.last,
        volume=None if volume is None else int(volume), book=None,
        missing=frozenset(missing))


def _questions(ticker, day, interval, spec) -> List[Tuple[str, FillQuestion]]:
    """The five intents for one ticker-day, skipping any whose price is absent."""
    st = interval.state
    prices = {"last": st.last, "floor": st.floor, "ceiling": st.ceiling}
    out = []
    for i, (intent, side, otype, key) in enumerate(INTENTS):
        limit = None if key is None else prices.get(key)
        if key is not None and limit is None:
            continue
        rec = OrderRecord(
            order_id=f"{ticker}-{day.isoformat()}-{i}", venue=Venue.HSX,
            state=OrderState.RESTING, time_in_force=TimeInForce.DAY,
            submitted_at=interval.start, updated_at=interval.start, fills=(),
            order=Order(ticker=ticker, side=side, quantity=QUANTITY,
                        order_type=otype, limit_price=limit))
        out.append((intent, FillQuestion(
            order=rec, interval=interval, rules=HSX_EXCHANGE,
            already_filled=0, instrument=spec, label=intent)))
    return out


# --------------------------------------------------------------------------
# The measurement
# --------------------------------------------------------------------------

def measure_fill_divergence(data_root: str = DEFAULT_ROOT, *, year: int = YEAR,
                            min_sessions: int = MIN_SESSIONS,
                            max_tickers: Optional[int] = None
                            ) -> FillDivergenceResult:
    src = DataHubSource.for_root(data_root)
    tickers = discover_universe(src, year=year, min_sessions=min_sessions,
                                max_tickers=max_tickers)
    bars = _load_bars(src, tickers, year)
    policies = _policies()
    signatures = tuple(p.signature for p in policies)

    agreed = questions = ticker_days = 0
    by_policy: Dict[str, _PolicyAgg] = {s: _PolicyAgg() for s in signatures}
    by_intent: Dict[str, _IntentAgg] = {i[0]: _IntentAgg() for i in INTENTS}

    for ticker in tickers:
        spec = src.instrument(ticker)
        flow: List[Tuple[str, FillQuestion]] = []
        for (day, close, o, hi, lo, ce, fl, rf, vol) in bars.get(ticker, ()):
            iv = _interval(src, ticker, day, spec, close, o, hi, lo, ce, fl, rf, vol)
            qs = _questions(ticker, day, iv, spec)
            if qs:
                ticker_days += 1
                flow.extend(qs)
        if not flow:
            continue
        report = compare_policies(policies, [q for _, q in flow])
        # fold this ticker's report into the running accumulators
        agreed += sum(1 for row in report.rows if row.agreed)
        questions += report.questions
        for sig in signatures:
            for o, k in report.outcomes(sig).items():
                by_policy[sig].outcomes[o] += k
            by_policy[sig].filled_quantity += report.filled_quantity(sig)
        for row in report.rows:
            a = by_intent[row.name]        # row.name == the intent label we set
            a.n += 1
            if row.agreed:
                a.agreed += 1
            for sig, dec in row.decisions.items():
                if dec.outcome is FillOutcome.FILL:
                    a.filled[sig] += 1
                elif dec.outcome is FillOutcome.INDETERMINATE:
                    a.indeterminate[sig] += 1

    lo = min((d for rows in bars.values() for (d, *_) in rows), default=None)
    hi = max((d for rows in bars.values() for (d, *_) in rows), default=None)
    span = f", {lo}..{hi}" if lo else ""
    return FillDivergenceResult(
        population=(f"HSX stock ticker-days, {year}: {len(tickers)} tickers x "
                    f">= {min_sessions} sessions{span}; five on-grid intents each, "
                    f"under soft/hard/probabilistic"),
        tickers=len([t for t in tickers if bars.get(t)]), ticker_days=ticker_days,
        questions=questions, signatures=signatures, agreed=agreed,
        by_policy=by_policy, by_intent=by_intent)


# --------------------------------------------------------------------------
# Render + CLI
# --------------------------------------------------------------------------

#: Order intents collapsed into three reader-facing categories, aggressive ->
#: passive (buy and sell behave the same, so they are pooled).
_CATEGORIES = (
    ("Market order\n(take liquidity)", ("market_buy",)),
    ("Limit at the\nmarket price", ("limit_buy_at_close", "limit_sell_at_close")),
    ("Limit far from\nmarket", ("limit_buy_at_floor", "limit_sell_at_ceil")),
)
_COLOUR = {"soft": "#c0392b", "hard": "#2c7fb8", "probabilistic": "#7fb800"}


def render(result: FillDivergenceResult, out: Path) -> Path:
    """Two panels, the three fill policies shown explicitly. Left: the share of
    each order type that FILLS under each policy (solid), with the abstained
    share stacked on as a hatch so ``INDETERMINATE`` is honest rather than read
    as a no-fill. Right: the total quantity each policy fills. Same colour per
    policy across both panels."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    out.parent.mkdir(parents=True, exist_ok=True)
    sigs = result.signatures
    short = {s: s.split("(")[0] for s in sigs}

    def _rate(keys, get) -> Dict[str, float]:
        tot = sum(result.by_intent[k].n for k in keys) or 1
        return {s: 100 * sum(get(result.by_intent[k], s) for k in keys) / tot
                for s in sigs}

    filled = [_rate(ks, lambda a, s: a.filled.get(s, 0)) for _, ks in _CATEGORIES]
    indet = [_rate(ks, lambda a, s: a.indeterminate.get(s, 0))
             for _, ks in _CATEGORIES]

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(12.5, 5.0),
                                   gridspec_kw={"width_ratios": [1.7, 1]})
    x, w = np.arange(len(_CATEGORIES)), 0.26
    for i, s in enumerate(sigs):
        col = _COLOUR.get(short[s], "#888")
        f = [filled[c][s] for c in range(len(_CATEGORIES))]
        a = [indet[c][s] for c in range(len(_CATEGORIES))]
        off = (i - 1) * w
        axL.bar(x + off, f, w, color=col, label=short[s])
        axL.bar(x + off, a, w, bottom=f, color=col, alpha=0.30, hatch="////",
                linewidth=0)
        for xi, (fv, av) in enumerate(zip(f, a)):
            if fv > 3:
                axL.text(xi + off, fv / 2, f"{fv:.0f}", ha="center", va="center",
                         fontsize=8, color="white", fontweight="bold")
            if av > 12:
                axL.text(xi + off, fv + av / 2, "can't\ndecide", ha="center",
                         va="center", fontsize=6.5, color=col)
    axL.set_xticks(x)
    axL.set_xticklabels([c for c, _ in _CATEGORIES], fontsize=9)
    axL.set_ylabel("orders filled  (%)")
    axL.set_ylim(0, 105)
    axL.set_title("Does it fill?", fontsize=12, fontweight="bold")
    axL.legend(title="fill policy", loc="upper right", fontsize=9)

    qty = [result.by_policy[s].filled_quantity / 1e6 for s in sigs]
    axR.bar([short[s] for s in sigs], qty,
            color=[_COLOUR.get(short[s], "#888") for s in sigs])
    for i, q in enumerate(qty):
        axR.text(i, q, f"{q:.0f}M", ha="center", va="bottom", fontsize=9)
    axR.set_ylabel("shares filled  (millions)")
    axR.set_ylim(0, max(qty) * 1.15 if qty else 1)
    axR.set_title("How much fills?", fontsize=12, fontweight="bold")

    fig.suptitle("The fill policy changes the outcome", fontsize=13.5,
                 fontweight="bold")
    fig.text(0.5, 0.015,
             f"{result.questions // 1000}k HSX orders (2022)  ·  the three agree "
             f"on {float(result.agreement_rate):.0%}  ·  hatched = abstained "
             "(INDETERMINATE)", ha="center", fontsize=8, color="#555")
    fig.subplots_adjust(left=0.08, right=0.97, top=0.87, bottom=0.16, wspace=0.28)
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", default=DEFAULT_ROOT)
    p.add_argument("--max-tickers", type=int, default=None,
                   help="cap the universe (default: all qualifying tickers)")
    p.add_argument("--json", type=Path,
                   default=_REPO / "figures" / "e1_fill_divergence.json")
    p.add_argument("--png", type=Path,
                   default=_REPO / "figures" / "e1_fill_divergence.png")
    args = p.parse_args()

    r = measure_fill_divergence(args.data_root, max_tickers=args.max_tickers)
    print(f"population : {r.population}")
    print(f"questions  : {r.questions:,} over {r.ticker_days:,} ticker-days")
    print(f"agreement  : {float(r.agreement_rate):.1%}  "
          f"(divergence {1 - float(r.agreement_rate):.1%})")
    print("by policy  :")
    for s in r.signatures:
        a = r.by_policy[s]
        q = r.questions or 1
        print(f"  {s:28} filled={a.outcomes.get(FillOutcome.FILL,0):>7,}  "
              f"indet={a.outcomes.get(FillOutcome.INDETERMINATE,0):>7,}  "
              f"({a.outcomes.get(FillOutcome.INDETERMINATE,0)/q:.1%})  "
              f"qty={a.filled_quantity:>10,}")
    print("by intent  :")
    for i in (x[0] for x in INTENTS):
        a = r.by_intent[i]
        if a.n:
            print(f"  {i:22} n={a.n:>7,}  divergence={1 - a.agreed/a.n:.1%}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(r.to_dict(), indent=2, cls=_Enc))
        print(f"\nwrote {args.json}")
    if args.png:
        render(r, args.png)
        print(f"wrote {args.png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
