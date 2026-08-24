# Design — `plutus.market`: an executable exchange fill model for Vietnamese markets

**Date:** 2026-08-24 · **Status:** approved for planning · **Supersedes:** the WP3
"VietnamFillModel" sketch in `HANDOFF-IMPLEMENTATION.md`.

---

## 1. Thesis

A backtest is only as faithful as its model of the exchange. Vietnam's four
exchanges — HSX, HNX, UPCOM (cash) and HNXDS (derivatives) — each enforce a
distinct set of **admission** rules (will the exchange accept this order?) and
**position** rules (will the exchange let this position survive?) that no
general-purpose backtester encodes.

**Plutus is an executable model of those exchange rules.** It reproduces what an
exchange does to an order and to a position: the tick-grid, lot, price-band,
session and foreign-room checks an exchange runs before an order can rest on the
book, and the margin, position-limit and expiry-settlement logic a derivatives
exchange runs against an open position each day. Stating it plainly: **this is a
Vietnamese-exchange fill model.** That is the thing the paper contributes and no
one has written.

Because it is a model of exchange *rules* applied to market data — rather than
data itself — it is vendor-independent by construction. It runs on top of
whatever vnstock, a broker feed, or our own datahub provides. The analogy is
NautilusTrader: its value is exchange-faithful execution semantics, not data.
Nobody has written those semantics for Vietnam.

### The central empirical finding, visible in the architecture

The two rule families bind on **different** exchanges:

| Rule | Cash (HSX/HNX/UPCOM) | Derivatives (HNXDS) |
|---|---|---|
| Round lot | 100 shares — **binds** | 1 contract — vanishes |
| Tick grid | price-dependent — **binds** | flat 0.1 — trivial |
| Price band | 7/10/15% | 7% |
| Foreign-ownership cap | **binds** | none |
| Position limit | none | **binds** (VSD cap) |
| Margin (initial + maintenance, daily MTM) | none | **binds** |
| Expiry / forced settlement | none | **binds** |

Order-admission dominates the cash exchanges; position-survival dominates the
derivatives exchange. One exchange is an observation; the pair is the framework.
This asymmetry is why derivatives is a co-equal contribution, not a section — it
exercises the half of the framework the cash exchanges cannot.

## 2. Non-goals — exchange-side, not trader-side (Rule 2)

Plutus models the **exchange's** decisions, not the **trader's**. This is the
boundary that keeps it a fill model rather than a backtesting engine, and it
must be stated in code and paper alike, or a reviewer will ask why this is not
simply a worse backtester.

An `Exchange` models what the exchange does:
- **admission**: is this order acceptable under the exchange's tick/lot/band/
  session/room rules?
- **position management**: given a price path, would the exchange margin-call,
  force-liquidate, block a limit-locked exit, or settle at expiry?

An `Exchange` does NOT model what the trader or a backtester does:
- no strategy, portfolio, cash balance, or P&L;
- no order lifecycle, queue-priority matching, or partial-fill simulation over
  time — it answers whether an order *could* fill against observed market state,
  not how a matching engine would sequence it;
- no decision about what to do after a margin call — it reports that the
  exchange would issue one.

Exchange-side fill model, not trader-side execution engine. `core/bot.py` stays
a raising stub; the ICAIF paper owns the engine-independence story.

## 3. Architecture

New package `plutus.market`, sitting beside `plutus.datahub` (data) and
`plutus.evaluation` (metrics). "market" is the umbrella noun — a market is made
of several exchanges — and the package holds the exchanges plus the data
adapters and margin mechanics they need.

It reads `plutus.core.constant`, which already encodes every rule correctly
(`TRADING_UNIT`, `DAILY_TRADING_LIMIT`, `TICK_SIZE`, `get_hsx_tick_size`, the
session objects, the four exchange spec objects). The gap this closes is that
nothing consumes those constants; today they are correct and unused.

### 3.0 Naming: `ExchangeSpec` (the rulebook) vs `Exchange` (the model)

`plutus.core.constant` already defines a class named `Exchange` — but it is a
static data holder: name, code, sessions, trading unit, daily limit, tick
function. It is the exchange's *published rulebook*, and it is instantiated
exactly four times (HSX/HNX/UPCOM/DS) and used nowhere else.

To free the name for the behavioral class, **rename `constant.Exchange` →
`ExchangeSpec`**. It is a spec, and the rename is a mechanical, low-risk change
confined to `constant.py` (four instantiations, no external importers). The new
`plutus.market.Exchange` then *reads* an `ExchangeSpec` and answers `admits` /
`sustains` — rulebook (data) and exchange (behavior) cleanly separated, with no
constant duplicated between them.

```
plutus/market/
  protocol.py     MarketState, InstrumentSpec, Order, the Exchange ABC
  verdicts.py     Admissibility, Viability, PositionEvent (+ reason enums)
  exchanges/
    base.py       Exchange ABC: admits() + sustains()
    cash.py       CashExchange (one class, parameterized by ExchangeSpec;
                  HSX/HNX/UPCOM are instances, not subclasses)
    derivatives.py HNXDSExchange (margin, position limit, expiry)
  adapters/
    base.py       MarketDataSource protocol
    datahub.py    reference adapter over plutus.datahub
  margin.py       parameterized margin mechanics (rate is an input)
```

### 3.1 The data boundary — granularity-agnostic

The unit crossing the boundary is a `MarketState`, not a bar. Whether it was
built from a daily bar, a single tick, or an order-book snapshot is the
adapter's concern; the exchange never knows. This is what lets the *same*
`admits()` run at bar and at tick resolution — and yields a free methodological
result: how much bar-resolution analysis mis-states a rule that tick data
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
the source is bar-resolution. Availability is explicit — an exchange that needs
the book and is handed `None` returns a verdict of `INDETERMINATE`, never a
guess.

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

### 3.2 Admission (stateless)

```python
class Exchange(ABC):
    spec: ExchangeSpec
    def admits(self, order: Order, state: MarketState) -> Admissibility: ...
    def sustains(self, position: Position, path: Sequence[MarketState],
                 *, margin_rate: Decimal) -> Viability: ...
```

`admits` checks, in order, short-circuiting on the first breach:
1. price on the exchange tick grid (`get_hsx_tick_size` for HSX; flat 0.1 else);
2. size on the round lot (`TRADING_UNIT`: 100 cash, 1 derivatives);
3. **BAND_LIMIT** (stateless) — price outside `[floor, ceiling]`. Needs no book.
4. **BAND_LOCK** (fillability) — a marketable order on the locked side of a band.
   Requires lock provenance: `MarketState.locked_side` plus `lock_evidence`
   (`TICK_BOOK` from a forward-filled ladder, `BAR_PROXY` when `last == ceiling`,
   or `UNKNOWN` → `INDETERMINATE`). An order priced *at* the ceiling is
   admissible — the exchange accepts it; it simply may not fill. Conflating the
   two would make the equity headline unmeasurable at bar resolution;
5. foreign room, when the order is flagged foreign and room is known (cash only);
6. session semantics — ATO/ATC are call auctions; a marketable order there
   participates in price formation rather than crossing a book.

`Admissibility` is structured, never a bool:
`(verdict: Verdict, rule: AdmissionRule | None, binding_constraint, ts,
regime_tag, detail)`. `Verdict` is `ADMITTED | REJECTED | INDETERMINATE` — a
bool cannot carry the `INDETERMINATE` that honest handling of absent data
requires. The `rule` enum IS the rejected-order log — every rejection records
which rule, at what timestamp, in what regime. `regime_tag` is **supplied by
the caller**, never computed inside `plutus.market` (WP6 is not landed).

All reason enums are declared `class X(str, Enum)`: this is load-bearing, not
style. `evaluation.contract.json_safe` passes enums and datetimes through
unchanged and `json.dumps` then raises, so every verdict carries a `to_dict()`
that isoformats temporals before handing off — mirroring
`audit.CheckResult.to_dict()`. `json_safe` itself is not modified; 169 tests
pin it.

### 3.3 Position management (stateful, derivatives)

`sustains` walks a position along a price path and emits `PositionEvent`s:
`MARGIN_CALL`, `FORCED_LIQUIDATION`, `EXIT_BLOCKED` (stop level on the wrong
side of a locked band), `POSITION_LIMIT_EXCEEDED`, `EXPIRY_SETTLEMENT`.

Margin is a *rule*, not vendor data. The distinction that keeps this
exchange-side: **variation margin** is a quantity the exchange itself computes
and collects daily; **strategy P&L** is trader-side. `sustains` computes the
former only, and never nets it against cash, fees, or other positions. That
resolves the apparent contradiction with §2 ("does not compute P&L") — daily
mark-to-market of a single position's margin account is the exchange's own
arithmetic, not the trader's.

The mechanic, fully determined:

```
q        = +1 long / -1 short, times quantity
S_t      = settlement on day t (see tiers below)
N_t      = |q| * multiplier * S_t                        notional
posted   = initial_rate * N_0    initial_rate = 0.175 (VSD) + 0.05 (broker) = 0.225
equity_t = posted + q * multiplier * (S_t - S_0)         cumulative variation margin
ratio_t  = equity_t / N_t

MARGIN_CALL         first day ratio_t <  maintenance_rate   (default 0.175)
FORCED_LIQUIDATION  first day ratio_t <= liquidation_rate   (default 0.00)
```

`maintenance_rate = 0.175` is derived, not invented: it is set to the VSD
initial requirement, so the broker buffer is what stands between posting and a
call. Note the trigger is **not** a 5% adverse move -- notional is marked to
market alongside equity, so the ratio falls more slowly than the price. The
exact threshold for a long is `(1 - initial) / (1 - maintenance)` =
0.775/0.825 = 0.9394, i.e. a **6.06%** fall. Verified by test.
Both thresholds are config keys documented as *modelling assumptions with no
corpus backing*. Invariant to test: `FORCED_LIQUIDATION` implies a
`MARGIN_CALL` on the same or an earlier day.

**Settlement has three tiers, and every event records which it used**
(`settlement_source`): `PUBLISHED` (the 5 real `quote_settlementprice` pairs,
excluding 11 corrupt rows), `TWAP_30M` (time-weighted mean of matched price
over 14:15–14:45 — recovered empirically, mean error 0.74 index points, raw
archive only), `CLOSE_PROXY` (`quote_close`, the only tier on the Parquet
root). **`quote_reference` is NOT in the chain**: it equals the previous close
on 1,731 of 1,968 VN30F pairs and misses published settlement by up to 5.55
points, so it is not an independent settlement series.

`EXPIRY_SETTLEMENT` fires on the third Thursday of the contract month (verified
24/24 in-window) and uses the same tiers with the VN30 index substituted at
tier 2 — the regulation is index-based. The futures close is *not* the final
settlement on any of the 28 expiries (basis −27.79…+8.43).

The paper reports incidence at the real rates; a sweep over neighbouring rates
is a robustness panel, not a substitute for the number we have.

`sustains` reports what the exchange would do; it does not liquidate on the
trader's behalf, re-enter, or compute P&L.

## 4. What this reframes in the existing repo

Nothing already landed is discarded; weights change.

| Prior headline | Now |
|---|---|
| Zero-setup data architecture | supporting infrastructure — not claimed |
| 23-year daily coverage | one-sentence context |
| Data-quality audit (WP4) | **minor** contribution (reproducibility) |
| Optimism bias, equity | **primary** — order admission |
| — | **primary** — position survival under margin (derivatives) |
| — | supporting — vendor-independent boundary, bar+tick |

The audit, metrics contract, daily/tick query layer, CI and 450 tests all
remain and all serve the new claims as reproducible substrate.

## 5. Deliverables

1. `plutus.market` — the module groups in §3, and the `ExchangeSpec` rename in
   `constant.py` (§3.0).
2. Measurement scripts extending `reproduce_measurements.py`: blocked-fill rate
   at **bar and tick** resolution (with the divergence between them as its own
   result); grid conformity (target 100% vs ~91.6% naive); margin-call
   incidence swept over rate; position-limit and expiry incidence.
3. Regression tests pinning every headline number, as WP4 does — so CI defends
   the paper.
4. Paper claim↔measurement map updated to the §4 weighting.

## 6. Acceptance criteria (mechanical)

- `admits` unit-tested per rule per exchange, including the 8-char C/E/F
  warrant-ETF tick exception and the 1-contract derivatives lot.
- Property test: every price `admits` accepts on HSX lies on the legal grid.
- Replaying the naive momentum rule through the HSX `CashExchange` reproduces
  the measured blocked-entry rate exactly — **25,464 blocked of 197,337
  attempts (12.9038%)**, stocks-only, inverted bands filtered. Asserted as
  integers, not a tolerance. This is the test that ties code to the paper's
  equity headline, and it supersedes the handoff's unreproduced 12.96%/191,454.
- `HNXDSExchange.sustains` on `VN30F2212` (entry 2022-04-22 @1441.8; first call
  2022-05-09; liquidated 2022-10-03) emits `MARGIN_CALL` at
  rates where it should and none where it shouldn't; incidence is monotonic in
  the rate.
- Bar-vs-tick divergence is reported with n for each.
- Every verdict/event round-trips through `json.dumps` under the strict
  `parse_constant` idiom, via its own `to_dict()` (str-mixin enums + isoformat
  temporals, then `json_safe`). `json_safe` alone is insufficient — it passes
  enums and datetimes through and `dumps` raises.
- `INDETERMINATE` returned, never a guess, when a needed book is absent.
- `ExchangeSpec` rename leaves the full suite green.
- New numbers reproducible from `reproduce_measurements.py`.

## 7. Open questions carried in (not resolved by this design)

1. **RIVF deadline ~31 Aug — best-effort accepted.** Not treated as a hard
   gate; we ship the best version we have by then. The cash exchanges plus
   order admission are the minimum viable paper; derivatives position survival
   is the elevation. Sequencing favours the cash exchanges first so a slip
   degrades gracefully.
2. **17,274 impossible close-to-close moves** (>15%, any band) — a robustness
   check on the equity headline, NOT a contribution and NOT a data fix. A naive
   momentum rule reads a suspension-resumption or listing debut as a huge buy
   signal that was never tradeable; if such day-pairs inflate the blocked-fill
   rate, the headline overstates. Handled at measurement time by excluding
   day-pairs that span a trading gap, then confirming the rate barely moves.
   The data is left untouched. Verified only that these are NOT corporate
   actions (adjustment does not remove them); the suspension/listing/bad-print
   split is unknown and does not need resolving for the paper. Not a blocker;
   revisit when the equity headline is computed.
3. **Derivatives corpus is thin**: 28 VN30F contracts, 1,996 daily rows,
   2021-01→2022-12; published settlement for only 2 contracts + VN30INDEX
   (5 (date, contract) pairs, 11 corrupt rows), so TWAP_30M or close proxies it;
   OI 2021+. Bounds the derivatives claims to daily resolution over ~2 years —
   state it explicitly.
4. **Margin rate — RESOLVED.** 17.5% VSD initial + 5% broker cash buffer,
   carried in config (§3.3). No external lookup needed; the sweep is now
   optional robustness rather than a stand-in for a missing number.

## 8. Effort

~8–10 focused days before drafting: protocol+verdicts ~1, cash `admits` ~1.5,
derivatives `sustains`+margin ~3, datahub adapter ~1, tick-resolution
measurement ~1.5, derivatives measurement ~1. The `ExchangeSpec` rename is
hours, not days. Reorganizes WP3's scope around exchanges rather than adding to
it; the exchange abstraction removes per-market branching that a single fill
model would have carried.
