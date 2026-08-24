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
    cash.py       HSXExchange, HNXExchange, UPCOMExchange
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
3. side vs a locked band (no buy at/above a locked ceiling; no sell at/below a
   locked floor);
4. foreign room, when the order is flagged foreign and room is known (cash only);
5. session semantics — ATO/ATC are call auctions; a marketable order there
   participates in price formation rather than crossing a book.

`Admissibility` is structured, never a bool:
`(admitted: bool, rule: AdmissionRule | None, binding_constraint, ts,
regime_tag)`. The `rule` enum IS the rejected-order log — every rejection
records which rule, at what timestamp, in what regime.

### 3.3 Position management (stateful, derivatives)

`sustains` walks a position along a price path and emits `PositionEvent`s:
`MARGIN_CALL`, `FORCED_LIQUIDATION`, `EXIT_BLOCKED` (stop level on the wrong
side of a locked band), `POSITION_LIMIT_EXCEEDED`, `EXPIRY_SETTLEMENT`.

Margin is a *rule*, not vendor data. `plutus.market.margin` models the
mechanics — initial vs maintenance, daily mark-to-market against settlement (or
close as proxy where settlement is absent) — and reads the rate from config.
Defaults are the known Vietnamese figures: **17.5% VSD initial margin, plus a
5% broker cash buffer** (so a position must post ~22.5% of notional). The
margin call fires on the maintenance threshold. The paper reports incidence at
these real rates; a sensitivity sweep over neighbouring rates is retained as an
optional robustness panel, not a substitute for a number we now have.

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
- Replaying the naive momentum rule through `HSXExchange.admits` reproduces the
  measured blocked-entry rate (stocks-only, inverted bands filtered) within
  tolerance — the test that ties code to the paper's equity headline.
- `HNXDSExchange.sustains` on a known 2022 drawdown path emits `MARGIN_CALL` at
  rates where it should and none where it shouldn't; incidence is monotonic in
  the rate.
- Bar-vs-tick divergence is reported with n for each.
- Every verdict/event is machine-readable and JSON-serialisable (reuses the
  WP2 `contract.json_safe` guard).
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
   2021-01→2022-12; settlement for only 3 contracts (close used as MTM proxy);
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
