# Intraday book-walk through the session — design spec

**Status:** design, awaiting author review · 2026-08-28
**Goal it serves:** the intraday user — the stated selling point. Let a strategy submit orders
through the ordinary session and have them fill by **walking the real order book** at each instant,
under a **user-chosen, self-reported queue assumption** (optimistic / conservative / probabilistic),
because the true fill is unknowable from history and we say so.
**Relationship to prior work:** extends `scenarios/` (Jx) and `strategies/` (Sx) with the same
two-tier discipline. This is an **integration**, not a greenfield build — the engine already exists.

---

## 1. What already exists vs. what this builds

The intraday engine is **built and deliberately un-wired**:

| Piece | State | Where |
|---|---|---|
| `BookWalkFillPolicy` (walks a book, honours the passive-price rule, caps, staleness) | ✅ built — a `_CappedFillPolicy`, same base as soft/hard/probabilistic | `session/book_walk.py:1249` |
| Queue policies (`OptimisticQueue` / `ConservativeQueue` / `ProbabilisticQueue`) | ✅ built | `session/book_walk.py:433+` |
| `DepthSource` order-book adapter (`book_at(ticker, ts)`) | ✅ built | `adapters/depth.py:666` |
| `BookProvider` seam (what a policy reads a book from) | ✅ named/built | `session/book_walk.py` (`__all__`) |
| Pluggable fill-policy interface (session takes a `fill_policy`) | ✅ | `exchange.py`, `fills.build_fill_policy` |
| Order-book data (bid/ask **price + size**, both sides) | ✅ on disk (dev extract; production has more) | `dataset/hermes-dev-extract/local_quote_*` |
| **Config selects `book_walk` + a queue mode** | ❌ `BOOK_WALK_KIND='book_walk'` is a reserved token that `build_fill_policy` **refuses on purpose** | `fills.py:196-201` |
| **Session feeds the policy a book at each fill** | ❌ the deferred wiring — "remains deferred… needs no new interface" | `fills.py:242-243` |
| **End-to-end through `submit`/`advance_to` on depth data** | ❌ today only `walk_book` direct (J13/J21, off-session) | — |

So the three things this spec builds are the **config token**, the **session→policy book seam**, and the
**acceptance suite** that proves it end-to-end. The daily path (soft/hard/probabilistic) is untouched.

## 2. The honesty principle this preserves (do not violate)

The session refuses to fake queue position, "by design" (`exchange.py:2953`): it honours
price-then-**receipt-order** priority (the level it *can* observe from its own order sequence) and
treats queue position against *other participants'* resting orders as an **explicit, user-chosen
assumption**. This spec keeps that: the queue policy is a *declared knob*, recorded in provenance,
never a silent default. What IS rule-sourced (the passive-price match, QĐ 352 Điều 6.3) is honoured;
what is not (where you sat in the queue) is chosen and reported.

## 3. The design

### 3.1 Config surface (mirrors the existing `fill_policy` block)

```json
{
  "period": {"start": "...", "end": "..."},
  "resolution": "tick",
  "data": {"adapter": "plutus.market.adapters.depth.DepthSource", "root": "<book-extract>"},
  "fill_policy": {
    "kind": "book_walk",
    "queue": "conservative",        // optimistic | conservative | probabilistic
    "seed": 7,                       // probabilistic only; reproducible
    "max_participation": 0.10,
    "max_staleness": "5s"            // book older than this at an order's instant -> INDETERMINATE
  }
}
```

- `parse_fill_policy_config` learns `kind: "book_walk"` plus `queue`/`seed`/`max_staleness`.
- `build_fill_policy` **stops refusing `book_walk`** and constructs a `BookWalkFillPolicy` with the
  chosen queue policy, cap, staleness, seed. The **`BookProvider` is bound by the session** (§3.2),
  not by config — because it comes from the session's own `DepthSource`.
- `SessionProvenance.fill_policy_kind` records `"book_walk"`, and a new
  `SessionProvenance.queue_policy` records `"conservative"` — the result self-labels its assumption,
  exactly as `fill_policy_kind` already does.

### 3.2 The session → policy book seam (the one real integration point)

`_evaluate_fills` currently fetches a bar `interval` and calls `policy.evaluate(record, interval,
rules)`. For `book_walk`:

- At session build, if the fill policy is `BookWalkFillPolicy` **and** the source is a
  `DepthSource` (a `BookProvider`), bind the source as the policy's book provider.
- At each `advance_to(ts)`, the policy reads the book at each live order's instant via
  `BookProvider` (≈ `DepthSource.book_at(ticker, ts)`), walks it under the queue policy, and returns
  the swept fill — or **INDETERMINATE** when the book is absent or staler than `max_staleness`.
- No new interface: `BookWalkFillPolicy` already subclasses `_CappedFillPolicy`; `_evaluate_fills`
  already dispatches through `policy.evaluate`. The change is *providing the book*, not a new path.

### 3.3 Resolution / source — recommendation

**Use `DepthSource`, not `TickSource`.** The book walk needs actual depth (bid/ask levels with
sizes); `TickSource` synthesises intervals and carries no book (it is not even an `IntervalSource`).
So an intraday book-walk session runs with `DepthSource` as its source and advances through intraday
instants; `book_at(ts)` is the point-in-time book. `TickSource` remains the right choice for a
tick-*price* run without depth (and is where the D71 auction fix lives, §3.4).

### 3.4 Fold in the D71 fix (small, and intraday touches the tick path)

On a tick run an ATC currently fills at `state.last` (a stale pre-auction print), not the published
close (FEATURES §17 D71 — the one live user-visible defect). The one-condition fix (name `CLOSE`
missing during auction synthesis, so ATC → published close or INDETERMINATE, matching the ATO half)
lands here because intraday runs exercise the tick/auction path. Verified by a scenario (J33 below).

### 3.5 Regression safety

`book_walk` is an **additional** kind; soft/hard/probabilistic and the whole daily path are
unchanged. Gate every change on the full market suite (**1596**), the 27 scenarios, and the current
strategies — all must stay green. The book seam only activates when the source is a `DepthSource`.

## 4. Data extraction — minimal, disk-conscious

Extract **only enough to demonstrate and verify**, per the disk constraint. Target a new small
directory `dataset/hermes-book-extract/` (parquet), and stop there.

- **Tables:** `local_quote_bidprice`, `local_quote_bidsize`, `local_quote_askprice`,
  `local_quote_asksize` (the four `DepthSource` reads at `table_prefix='local_quote'`).
- **Names (≈4):** `FPT`, `HPG`, `SSI` (liquid HSX, deep books) + `VN30F2212` (a future, for the
  derivatives intraday demo). Add one deliberately **thin** name only if a thin-book scenario needs it.
- **Window (≈5 consecutive trading days):** extend the dev extract's single 2022-11-09 day to a
  ~one-week window around it, so a multi-day intraday strategy has runway.
- **Source → destination:** the production read-only DB (or the tick archive), filtered to those
  names + window, exported to the four parquet files under `hermes-book-extract/`.
- **Budget check:** estimate before extracting — 4 names × ~5 days × 4 tables of intraday book
  snapshots should be tens of MB, not GB. **If the estimate exceeds ~1 GB, cut names or days first.**
  The extraction is a small query script; it is the one data task, kept minimal on purpose.

## 5. The acceptance suite — new Jx scenarios, then Sx strategies

Same rule as before: each scenario is a demo **and** a test with a *Broken looks like*; each strategy
is user code driving the feature the way a real intraday developer would. `Jx` first (feature by
feature), then `Sx` (a user's strategy over them).

### 5.1 New scenarios (feature demonstrations, now through the SESSION)

| # | Demonstrates | Broken looks like | Oracle |
|---|---|---|---|
| **J28** | An order fills by **walking the book** through `session.submit`/`advance_to` (not fill-at-close), at the resting levels' prices | it falls back to the close, or `book_walk` is refused in config | passive-price match — QĐ 352 Điều 6.3 (**sourced**) |
| **J29** | The queue mode is **chosen by config** and the same order fills differently under optimistic/conservative/probabilistic — recorded in provenance | the three agree, or the mode isn't reported | queue position is **UNSOURCED — our modelling choice** (the honesty story) |
| **J30** | A marketable order **sweeps multiple levels** at their prices, remainder reprices (MTL) — through the session | it fills one price, or ignores depth | sweep + passive price (rulebook 2.4) |
| **J31** | A book **absent or staler than `max_staleness`** at the instant → **INDETERMINATE**, naming the missing book | it fills on a stale book, silently | our epistemic rule (the ignorance meter) |
| **J32** *(opt.)* | Participation cap against **book depth** (fraction of visible size); INDETERMINATE without size | the cap uses a bar's volume, or over-fills | cap is **our modelling choice** (book version of J22) |
| **J33** | **D71 fix:** a tick-path ATC returns the **published close** (or INDETERMINATE), not the stale last | ATC fills at a pre-auction print | A75 close-as-cross; the fix makes ATC == ATO half |

### 5.2 New strategies (a user's intraday code)

- **S8 — Intraday passive market-maker.** The canonical queue-sensitive strategy: posts a bid and
  an ask around the touch, and its **fill rate is governed by queue position** — optimistic fills
  often (assumed front-of-queue), conservative rarely (only demonstrable). Run through the session on
  the book extract, driven to Tier 2. This is the intraday selling point made concrete: a real
  strategy whose executability *emerges* from the order book, not a bar proxy.
- **S9 — Intraday queue-sensitivity study (the S7 analog).** Run S8 **unchanged** under the three
  queue policies and report how much of the fill rate / P&L is the **queue assumption** vs. the
  signal — self-reported via provenance. This is the intraday headline for the paper: *"how much of
  your order-book backtest is the queue model,"* the exact counterpart to S7's fill-policy result.

*(Optional S10 — a marketable-taker scalper measuring realistic sweep slippage — only if S8/S9 leave
the taker path unexercised.)*

### 5.3 Harness note (test-side, unchanged boundary)

`strategies/_harness.py` grows an **intraday** driver alongside the daily one: advance through
intraday book instants (a `BookFeed` over `DepthSource`) instead of OPEN/CLOSE marks. It stays
test-side — the user still brings their own loop; we ship the market, not the backtester.

## 6. Build order

1. **Data extract** (§4) — a few names / one week of book depth; verify the size budget first.
2. **Config + seam** (§3.1–3.2): accept `book_walk` in `build_fill_policy`; bind the `DepthSource`
   as the policy's `BookProvider`; add `queue_policy` to provenance. Gate on 1596 + 27 + Sx green.
3. **Scenarios J28–J31** (+ J32 optional): drive each feature end-to-end through the session; Tier 2.
4. **D71 fix + J33.**
5. **S8** (market-maker) to Tier 2, then **S9** (queue-sensitivity study).
6. Update `SCENARIO-BOARD.md` / `STRATEGY-BOARD.md`; note honestly which scenarios are now
   session-end-to-end (J13/J21 can be *re-pointed* at the session path once J28–J30 land).

## 7. Open items to resolve during the build (not now)

1. **Exact `BookProvider` binding** — whether the policy pulls the book (holds the provider) or
   `_evaluate_fills` pushes it in the interval. §3.2 leans "policy holds the provider"; confirm
   against `book_walk.py`'s current `_continuous`/`_bounded` signature.
2. **Intraday advance cadence** — a fixed grid (e.g., every book snapshot, or every N seconds) vs.
   event-driven. Pick the smallest cadence that exercises queue differences without exploding runtime.
3. **`max_staleness` default and units** — string (`"5s"`) vs. seconds; and the default when omitted.
4. **Book-extract schema parity** — confirm the production/​archive book tables match the dev
   extract's `local_quote_*` columns so `DepthSource` reads them unchanged.
