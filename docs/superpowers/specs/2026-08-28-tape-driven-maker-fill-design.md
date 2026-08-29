# Tape-Driven Maker Fill + Minimal Sized-Tape Export — Design

**Status:** draft for review
**Date:** 2026-08-28
**Follows:** `2026-08-28-intraday-book-walk-session-design.md` (the taker sweep),
`2026-08-28-test-strategies-design.md` (the Sx discipline)

---

## 1. The gap this closes

The intraday fill we shipped (`book_walk`) is a **book-snapshot taker model**: a
*marketable* order crosses the spread and walks the resting depth on the other
side, and the queue policy decides how much of the displayed depth is ours. That
is correct for anything that *takes* liquidity — momentum, execution, a stop.

It cannot model a **maker**. A resting limit that sits *inside or at the touch*
(a SELL above the bid, a BUY below the ask) provides liquidity and fills only
when *someone else's* aggressive order trades through its price. In the current
model such an order fills only when a **later book snapshot** shows the opposite
touch crossing up to it — i.e. only when the market moves adversely through the
resting price. So a passive SELL at 73.40 fills in the simulator **only if the
bid rises to ≥ 73.40**, the one case a market-maker would rather avoid, and never
fills on the many buys that lift the 73.40 offer while the bid stays at 73.30.
The model makes market-making look impossible — the opposite of the truth.

Market-making is the intraday selling point. It needs a fill that is driven by
the **trade tape** (who traded, at what price, how much), by **queue position**,
not by the book snapshot. This spec builds that.

## 2. What already exists to build on

The queue axis was designed with this in mind and the seam is already there:

- **`ConservativeQueue(prints: PrintsThrough)`** — `PrintsThrough` is
  `Callable[[QueueRequest], Optional[int]]`, "the shares that printed at or
  through a level's price **after our arrival**." Its claim is
  `min(displayed, max(0, printed - displayed))`: everything displayed is ahead
  of us, the first `displayed` shares of the prints are not ours, and we never
  claim more than the level showed. **That is exactly the maker mechanic.** The
  corpus we shipped could not supply `prints` (the parquet tape carries no
  quantity column), so the arm returns INDETERMINATE. Supplying a real sized
  tape turns it on.
- **The three queue policies** (`Optimistic` / `Conservative` / `Probabilistic`)
  are the "where in the queue are we" axis, already selected by config
  (`fill_policy.queue`) and stamped in provenance (`SessionProvenance`).
- **`DepthSource`** reconstructs the book at an instant — this gives the
  **queue-ahead at arrival** (the displayed size at our price when we joined).

So the maker fill is not a new subsystem; it is the existing queue axis fed by a
real tape, plus a small refactor to make the axis serve both arms symmetrically.

## 3. The data (extracted and verified on the remote DB, 2026-08-28)

`algotradeDB` (read-only) carries the sized tape the parquet corpus dropped.
Extracted for **FPT (2022-11-09)** and **VN30F2504 (2025-04-08)**:

| table | columns | what it is |
|---|---|---|
| `quote.matched` | datetime, tickersymbol, **price** | the match-price sequence (updates on change; sparse — ~584 rows on FPT's day) |
| `quote.total` | datetime, tickersymbol, **quantity** | running **cumulative** matched volume; the **authoritative** volume — its last intraday value equals `quote.dailyvolume` exactly (FPT 697,700; VN30F 378,696) |
| `quote.matchedvolume` | datetime, tickersymbol, **quantity** | per-event volume, but **lossy — NOT USED** (see the finding) |

**Finding — the volume source is `total`, not `matchedvolume`.** Interleaving the
three streams on FPT 2022-11-09 shows `matchedvolume` undercounts: it omits
events entirely (a match at 09:16:04 has a `total` delta of 100 and *no*
`matchedvolume` row) and understates others (09:15:40 records 100 against a
`total` delta of 900). Its daily sum is 402,300 against the true 697,700. The
**complete** per-event volume is the **consecutive delta of `total`**, which by
construction sums to the day's volume. (This is exactly the kind of naive-source
trap the honesty discipline exists to catch; it becomes scenario **J36**.)

**The reconstruction.** The sized tape is `(t, price, volume)` where, for each
`total` update at `t`: `volume = total[t] - total[t_prev]`, and `price` is the
most recent `matched` price at or before `t` (forward-filled — `matched` and
`total` run on different tick schedules and do not share datetimes). One cleaning
rule: **drop rows outside the trading session** — FPT's `total` carries a
spurious `00:00:00` row equal to the daily total before the intraday series
begins; the intraday series itself is monotone (VN30F's is clean). The
forward-fill is a **declared modelling step**, the same class as the book's
per-side as-of join (`adapters/depth.py`); where no matched price precedes a
volume event it is **INDETERMINATE for price**, never guessed.

**Extracted files** (in `hermes-dev-extract`, documented in `MANIFEST_TAPE.json`):
`local_quote_total` (FPT) and `quote_total` (VN30F2504) — the volume; the price
is the already-present `local_quote_matched` / `quote_matched`. The book (for
queue-ahead) is the already-present `local_quote_*` sizes (FPT) and `quote_*`
sizes with depth 1–3 (VN30F2504).

## 4. The maker fill mechanic

A resting (non-marketable) limit order at price `P`, side `S`, evaluated over an
interval:

1. **Queue-ahead at arrival** `A` = the displayed size at `P` on our side of the
   book at the instant the order arrived (from `DepthSource`). This is how many
   shares sat in front of us when we joined the queue.
2. **Prints through since arrival** `T` = cumulative shares that traded at or
   through `P` (on the aggressing side that lifts our resting order) between our
   arrival and the interval's end (from the reconstructed tape).
3. **Our entitlement** = the queue policy applied to `(available = T, ahead = A)`:
   - **Optimistic** (front): `ahead = 0` → entitlement `= min(remaining, T)`. We
     fill as the tape trades through us, up to our size.
   - **Conservative** (back): `ahead = A` → entitlement `= max(0, T - A)` (capped
     at our size). The first `A` shares of the tape clear the queue in front of
     us; only the rest is ours.
   - **Probabilistic**: `ahead` drawn uniformly over `{0..A}` (seeded), so the
     fill sits between the two bounds, reproducibly.
4. **This interval's fill** `= entitlement - already_filled_on_this_order`. The
   entitlement is cumulative (a function of cumulative prints), so subtracting
   what the order already filled makes the per-interval increment; the order
   fills progressively as prints accumulate and rests otherwise.
5. **INDETERMINATE** where the tape is absent for the window (no volume stream
   served, or a gap that could hide prints) — honest, exactly like the taker
   refusals. A resting order over a window with **zero** prints through `P` is a
   definite **no-fill** (it stays live), *not* indeterminate: absence of prints
   on an observed tape is knowledge, not ignorance.

This is the user's worked example, exactly: *sell 500 FPT at 73, ask1 = 73×1000.
Optimistic → we sit on top, a 73 print of 500 fills us. Conservative → we sit at
the bottom, the 500 print clears the queue ahead and gives us nothing; a later
700 print clears 200 more and fills us 200, leaving 300. Probabilistic → we sit
somewhere in the middle of the 1000.*

## 5. Architecture

### 5.1 `TapeSource` (new adapter, `adapters/tape.py`)

Reads `<prefix>_matched` (price) + `<prefix>_total` (cumulative volume),
reconstructs the sized tape per §3 (session-filter → `total` deltas →
forward-fill `matched`), and exposes:

```
prints_through(ticker, price, side, since, until) -> Optional[int]
```

= cumulative shares that traded at or through `price` (in the direction that
lifts a resting `side` order) in `[since, until)`, or `None` (unknown) where the
tape is not served for that window. This is the concrete `PrintsThrough` the
queue policies consume. It is a `BookProvider`-style Protocol so a caller can
supply their own.

### 5.2 The queue axis, refactored to serve both arms

Today `QueuePolicy.claim` returns a **quantity** computed against the book's
`displayed`. The maker arm needs the same *position* logic applied against the
tape's `prints`. Rather than duplicate three policies, separate the two concerns:

- A queue policy answers **"how many shares are ahead of us"** — a *position*:
  optimistic `0`, conservative `= ahead`, probabilistic drawn over `{0..ahead}`.
- The **arm** computes `our_fill = clamp(available - ahead)` with
  `available = displayed` (taker, from the book) or `available = prints` (maker,
  from the tape).

This makes taker and maker symmetric, keeps one set of three policies as a pure
position axis, and the provenance string is unchanged. `ConservativeQueue`'s
current `min(displayed, max(0, printed - displayed))` is exactly this with
`ahead = displayed_at_arrival` and `available = printed`. *(This is the one
non-trivial refactor in the plan; §8 (a).)*

### 5.3 The fill policy — one policy, two arms selected by marketability

Extend the book-walk policy (or a sibling that shares its `_CappedFillPolicy`
base) so that, in the continuous session:

- **marketable** order (limit through the touch) → the **taker sweep** (walk the
  book), unchanged.
- **resting** order (limit inside/at the touch) → the **maker fill** (walk the
  tape via §4), new.

This mirrors how `fills.py` already splits auction vs continuous — one policy,
the arm chosen by market state, the assumption stamped either way. The session
constructs the `PrintsThrough` from its `TapeSource` and injects it, exactly as
it injects the `DepthSource` today.

### 5.4 Honesty properties preserved

- The queue assumption is **declared, never defaulted**, and stamped on every
  fill (unchanged).
- A maker fill is `MODELLED` evidence (queue-estimated), never `TRADED_THROUGH`
  (we did not see *our* print, we inferred it from the tape and a position).
- The forward-fill reconstruction and the tape's coverage are recorded; absence
  is INDETERMINATE, presence-with-zero-prints is a definite no-fill.

## 6. Scenarios (Jx) and strategies (Sx) — the acceptance spec

Driven green as TDD on the public surface, same discipline as J28–J31 / S1–S7.

**Scenarios (features):**

- **J32 — a resting order fills from the tape.** A passive SELL at the touch,
  filled by incoming buy prints through its price; quantity `= min(order, prints)`
  front-of-queue. The fill the current model *cannot* produce.
- **J33 — one tape, three fills by queue.** The identical resting order under
  optimistic / conservative / probabilistic, on the same reconstructed tape,
  yields three different fills (the user's 500-at-73 example). Provenance names
  the queue each time.
- **J34 — a resting order that never fills is a no-fill, not an adverse cross.**
  The tape never prints through `P`; the order rests all session and the run is
  clean (no INDETERMINATE, no phantom fill).
- **J35 — absent tape is INDETERMINATE.** With the volume stream unserved for the
  window, the maker fill refuses INDETERMINATE naming the tape, not a no-fill.
- **J36 — the volume source is `total`, and `matchedvolume` is lossy.** The
  reconstructed tape's per-event volumes (from `total` deltas) sum to the day's
  `dailyvolume`; the naive `matchedvolume` stream does not (FPT: 402,300 vs
  697,700). Pins the §3 finding as a data-integrity guard.

**Strategies (real, ranked by importance to the user):**

- **S8 — intraday market-maker (the selling point).** Posts a two-sided quote a
  tick or two off the touch, earns the spread, and manages inventory: as fills
  accumulate on one side it skews its quotes to lean against the position, and
  flattens toward the close. *Emerges:* spread capture on quiet ticks; inventory
  building when flow is one-sided; adverse selection when the market runs through
  a quote. Uses the maker fill + the queue axis. This is the strategy that only
  a maker model can express.
- **S9 — queue-sensitivity study.** The *same* market-maker run under
  optimistic / conservative / probabilistic queue, reporting the P&L spread the
  queue assumption alone produces — the "configurable fidelity" thesis made
  concrete and measurable, and the honest headline for a paper: *the queue
  assumption, not the strategy, moves the maker's P&L by X.*

## 7. Minimal export — DONE (2026-08-28)

Two `total` tables added to `hermes-dev-extract` (zero mutation of the J28–J31
data; `MANIFEST_TAPE.json` records it):

| file | name | day | rows |
|---|---|---|---|
| `local_quote_total` | FPT | 2022-11-09 | 1,570 |
| `quote_total` | VN30F2504 | 2025-04-08 | 4,547 |

The price (`*_matched`) and the book **with sizes** (`local_quote_*` for FPT;
`quote_*` depth 1–3 for VN30F2504) were already present — only the volume was
missing, so the export is two skinny files, well under a megabyte. FPT rides the
equity book of J28–J31 (same session, 2022-11-09); VN30F2504 uses its April-2025
book+matched. The lossy `matchedvolume` extract was removed (§3 finding). VN30F's
Nov-2022 contract (VN30F2211) was rejected because it carries **no book sizes**
in the DB, which would strand the conservative/probabilistic queue; VN30F2504 has
full depth.

## 8. Decisions (resolved 2026-08-28)

- **(a) The queue refactor** (separate "ahead" from "available", §5.2) — **yes**.
  One position axis for both arms, reusing the existing `ConservativeQueue`
  formula. The one change that touches shipped code.
- **(b) S8 scope** — **full two-sided, inventory-managing market-maker**, at
  scenario scale (a real MM core, not a production MM), so the interesting
  moments emerge without a research project.
- **(c) Export breadth** — **FPT and VN30F, both** (2022-11-09), so the maker
  fill is tested on an equity and a derivative from the start.
- **(d) The forward-fill reconstruction** (§3) — **accepted** as a declared
  modelling step, the same class as the book's per-side as-of join. It is the
  honest tape available; the alternative is no maker fill at all.

## 9. What this is not

- Not a change to the taker sweep (J28–J31 stand).
- Not a claim of execution-price fidelity: a maker fill is `MODELLED` from a tape
  and a declared queue position, and the queue position is unobservable in a
  corpus with no order ids — S9 measures exactly how much that assumption is
  worth.
- Not a full order-book matching engine: we infer our fill from the aggregate
  tape and a position, we do not reconstruct every resting order.
