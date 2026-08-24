# Design — `plutus.market`: an executable venue specification for Vietnamese markets

**Date:** 2026-08-24 · **Status:** approved for planning · **Supersedes:** the WP3
"VietnamFillModel" sketch in `HANDOFF-IMPLEMENTATION.md`.

---

## 1. Thesis

A backtest is only as faithful as its venue model. Vietnam's four venues — HSX,
HNX, UPCOM (cash) and HNXDS (derivatives) — each impose a distinct set of
**admissibility** rules (may this order exist?) and **viability** rules (does
this position survive?) that no general-purpose backtester encodes. Plutus
contributes an *executable specification* of those rules for both the cash and
derivatives venues, and quantifies what ignoring them costs.

The analogy is NautilusTrader: its value is venue-faithful execution semantics,
not data. Nobody has written that specification for Vietnam. Because it is a
*specification applied to* market data rather than data itself, it is
vendor-independent by construction — it runs on top of whatever vnstock, a
broker feed, or our own datahub provides.

### The central empirical finding, visible in the architecture

The two constraint families bind on **different** venues:

| Constraint | Cash (HSX/HNX/UPCOM) | Derivatives (HNXDS) |
|---|---|---|
| Round lot | 100 shares — **binds** | 1 contract — vanishes |
| Tick grid | price-dependent — **binds** | flat 0.1 — trivial |
| Price band | 7/10/15% | 7% |
| Foreign-ownership cap | **binds** | none |
| Position limit | none | **binds** (VSD cap) |
| Margin (initial + maintenance, daily MTM) | none | **binds** |
| Expiry / forced settlement | none | **binds** |

Order-admissibility dominates cash; position-viability dominates derivatives.
One venue is an observation; the pair is the framework. This asymmetry is why
derivatives is a co-equal contribution, not a section — it exercises the half
of the framework equity cannot.

## 2. Non-goals (Rule 2 — no engine)

Plutus is a venue **specification**, not a venue **simulator**. This boundary is
load-bearing and must be stated in code and paper alike, or a reviewer will ask
why this is not simply a worse backtester.

A `Venue`:
- **answers questions**: is this order admissible? would this position survive
  this price path?
- emits typed verdicts and events with reasons.

A `Venue` does NOT:
- maintain an order lifecycle or order book;
- match orders or simulate queue position;
- compute P&L, hold cash, or track a portfolio;
- decide what to do about a margin call — it reports that one occurred.

Feasibility oracle, not execution engine. `core/bot.py` stays a raising stub.

## 3. Architecture

New package `plutus.market`, sitting beside `plutus.datahub` (data) and
`plutus.evaluation` (metrics). It reads `plutus.core.constant`, which already
encodes every rule correctly (`TRADING_UNIT`, `DAILY_TRADING_LIMIT`,
`TICK_SIZE`, `get_hsx_tick_size`, the session objects, the four `Exchange`
objects). The gap this closes is that nothing consumes those constants; today
they are correct and unused.

```
plutus/market/
  protocol.py     MarketState, InstrumentSpec, Order, the Venue ABC
  verdicts.py     Admissibility, Viability, PositionEvent (+ reason enums)
  venues/
    base.py       Venue ABC: admits() + sustains()
    cash.py       HSXVenue, HNXVenue, UPCOMVenue
    derivatives.py HNXDSVenue (margin, position limit, expiry)
  adapters/
    base.py       MarketDataSource protocol
    datahub.py    reference adapter over plutus.datahub
  margin.py       parameterized margin mechanics (rate is an input)
```

### 3.1 The data boundary — granularity-agnostic

The unit crossing the boundary is a `MarketState`, not a bar. Whether it was
built from a daily bar, a single tick, or an order-book snapshot is the
adapter's concern; the venue never knows. This is what lets the *same*
`admits()` run at bar and at tick resolution — and yields a free methodological
result: how much bar-resolution analysis mis-states a constraint that tick data
measures directly.

```python
@dataclass(frozen=True)
class MarketState:
    ticker: str
    ts: datetime
    ceiling: Decimal
    floor: Decimal
    reference: Decimal
    last: Decimal | None = None          # matched/close
    book: OrderBook | None = None        # bid/ask depth 1-3, when tick-sourced
    session: SessionPhase = SessionPhase.CONTINUOUS
    foreign_room: int | None = None      # shares, when known
```

`OrderBook` carries up to three levels of (price, size) per side; `None` when
the source is bar-resolution. Availability is explicit — a venue that needs the
book and is handed `None` returns a verdict of `INDETERMINATE`, never a guess.

```python
class MarketDataSource(Protocol):
    def state_at(self, ticker: str, ts: datetime) -> MarketState | None: ...
    def states(self, ticker, start, end, *, resolution) -> Iterator[MarketState]: ...
    def instrument(self, ticker: str) -> InstrumentSpec: ...
```

`plutus.datahub` gets one adapter implementing this. A vnstock adapter is not
built here, but the protocol is proven sufficient by keeping it narrow enough
that one obviously could be — this is what makes vendor-independence
demonstrated, not asserted.

### 3.2 Tier 1 — admissibility (stateless)

```python
class Venue(ABC):
    def admits(self, order: Order, state: MarketState) -> Admissibility: ...
    def sustains(self, position: Position, path: Sequence[MarketState],
                 *, margin_rate: Decimal) -> Viability: ...
```

`admits` checks, in order, short-circuiting on the first breach:
1. price on the venue tick grid (`get_hsx_tick_size` for HSX; flat 0.1 else);
2. size on the round lot (`TRADING_UNIT`: 100 cash, 1 derivatives);
3. side vs a locked band (no buy at/above a locked ceiling; no sell at/below a
   locked floor);
4. foreign room, when the order is flagged foreign and room is known (cash only);
5. session semantics — ATO/ATC are call auctions; a marketable order there
   participates in price formation rather than crossing a book.

`Admissibility` is structured, never a bool:
`(admitted: bool, rule: AdmissibilityRule | None, binding_constraint, ts,
regime_tag)`. The `rule` enum IS the rejected-order log — every rejection
records which rule, at what timestamp, in what regime.

### 3.3 Tier 2 — viability (stateful, derivatives)

`sustains` walks a position along a price path and emits `PositionEvent`s:
`MARGIN_CALL`, `FORCED_LIQUIDATION`, `EXIT_BLOCKED` (stop level on the wrong
side of a locked band), `POSITION_LIMIT_EXCEEDED`, `EXPIRY_SETTLEMENT`.

Margin is a *rule*, not vendor data. `plutus.market.margin` models the
mechanics — initial vs maintenance, daily mark-to-market against settlement (or
close as proxy where settlement is absent) — and takes the rate as a parameter.
The paper reports margin-call incidence as a **sensitivity sweep** over a
plausible rate range (e.g. 10–20%), which is stronger than a point estimate and
honest about the one input the corpus lacks.

`sustains` emits events; it does not liquidate, re-enter, or compute P&L. What
a caller does with a `MARGIN_CALL` is the caller's business.

## 4. What this reframes in the existing repo

Nothing already landed is discarded; weights change.

| Prior headline | Now |
|---|---|
| Zero-setup data architecture | supporting infrastructure — not claimed |
| 23-year daily coverage | one-sentence context |
| Data-quality audit (WP4) | **minor** contribution (reproducibility) |
| Optimism bias, equity | **primary** — order-admissibility |
| — | **primary** — position-viability under margin (derivatives) |
| — | supporting — vendor-independent boundary, bar+tick |

The audit, metrics contract, daily/tick query layer, CI and 450 tests all
remain and all serve the new claims as reproducible substrate.

## 5. Deliverables

1. `plutus.market` — the five module groups in §3.
2. Measurement scripts extending `reproduce_measurements.py`: blocked-fill rate
   at **bar and tick** resolution (with the divergence between them as its own
   result); grid conformity (target 100% vs ~91.6% naive); margin-call
   incidence swept over rate; position-limit and expiry incidence.
3. Regression tests pinning every headline number, as WP4 does — so CI defends
   the paper.
4. Paper claim↔measurement map updated to the §4 weighting.

## 6. Acceptance criteria (mechanical)

- `admits` unit-tested per rule per venue, including the 8-char C/E/F
  warrant-ETF tick exception and the 1-contract derivatives lot.
- Property test: every price `admits` accepts on HSX lies on the legal grid.
- Replaying the naive momentum rule through `HSXVenue.admits` reproduces the
  measured blocked-entry rate (stocks-only, inverted bands filtered) within
  tolerance — the test that ties code to the paper's equity headline.
- `HNXDSVenue.sustains` on a known 2022 drawdown path emits `MARGIN_CALL` at
  rates where it should and none where it shouldn't; incidence is monotonic in
  the rate.
- Bar-vs-tick divergence is reported with n for each.
- Every verdict/event is machine-readable and JSON-serialisable (reuses the
  WP2 `contract.json_safe` guard).
- `INDETERMINATE` returned, never a guess, when a needed book is absent.
- Full suite green; new numbers reproducible from `reproduce_measurements.py`.

## 7. Open questions carried in (not resolved by this design)

1. **RIVF deadline unconfirmed** — sizes how much of §5 lands. Venue + equity
   admissibility is the minimum viable paper; derivatives viability is the
   elevation. Both are in scope here; sequencing favours equity first so a slip
   degrades gracefully.
2. **17,274 impossible close-to-close moves** (>15%, any band) sit inside the
   momentum rule the equity headline rests on. Adjustment does not clear them
   (§ price-series findings). Must be quantified or filtered before the blocked-
   fill number is final — candidate for a tenth audit check.
3. **Derivatives corpus is thin**: 28 VN30F contracts, 1,996 daily rows,
   2021-01→2022-12; settlement for only 3 contracts (close used as MTM proxy);
   OI 2021+. Bounds the derivatives claims to daily resolution over ~2 years —
   state it explicitly.
4. **Margin-rate range** to sweep — needs one external number (VSD published
   band) to set defensible endpoints; the mechanics don't depend on it.

## 8. Effort

~8–10 focused days before drafting: protocol+verdicts ~1, cash `admits` ~1.5,
derivatives `sustains`+margin ~3, datahub adapter ~1, tick-resolution
measurement ~1.5, derivatives measurement ~1. Reorganizes WP3's scope around
venues rather than adding to it; the protocol removes per-market branching that
a single fill model would have carried.
