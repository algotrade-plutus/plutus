# Fill Evidence Level (FEL)

*Reference for the paper's §5. Implemented in
`src/plutus/market/session/evidence_level.py`; pinned by
`tests/market/session/test_evidence_level.py`.*

## The idea

A backtest's fills are not all equally trustworthy. Some are *proven* by the tape;
some rest on an assumption the data cannot settle; some the data cannot speak to
at all. A simulator that reports one fill rate hides this. **FEL grades every fill
decision by how much data backs it**, turning the old binary "indeterminate?" flag
into a confidence profile of a run.

This is the neutral home for what was called INDETERMINATE. It is not a failure
state — it is simply the **bottom rung** of an evidence ladder: the fills that
lean entirely on the policy because the data said nothing. Reported as a
distribution ("62% proven, 33% assumed, 5% unevidenced"), it reads as a *quality
profile of the fills*, not a defect count.

FEL **classifies; it does not decide.** The fill policies decide (fill / no-fill /
abstain); FEL reads back what they returned. Every
`FillDecision` already records what it rested on — its `outcome`, its `evidence`,
and, when it abstained, the `missing` fields that defeated it — so FEL names
something the engine already computes rather than inventing a new quantity.

## The scale

Three ordered levels (higher = more data-backed):

| Level | Meaning | Produced by | Assumption |
|---|---|---|---|
| **PROVEN** (2) | the data settles the outcome | a fill that traded strictly *through* the limit (`TRADED_THROUGH`); a fill at a published auction cross (`AUCTION_PRICE`); or a definite `NO_FILL` (never reached) | none — price-then-time priority, a rule-guaranteed cross, or a definite miss |
| **ASSUMED** (1) | a fill the data does not settle, supplied under an assumption | a fill on a bare touch (`TOUCHED_AT_LIMIT`) or an explicitly modelled fill (`MODELLED`) | queue position, or a fill-probability / sweep / maker model |
| **UNEVIDENCED** (0) | INDETERMINATE — the data is silent | `FillOutcome.INDETERMINATE`; `missing` names the cause (`VOLUME`, `BOOK`, `BOOK_SIZE`, …) | the policy would supply the *whole* outcome, so the engine abstains |

`ASSUMED` carries a categorical **assumption kind** (not a degree — the two are
different *kinds* of assumption, so they share one level):

- **TOUCH** — `soft` filling on `TOUCHED_AT_LIMIT`: assumes favourable queue
  position, which no order-id-less corpus can recover.
- **MODELLED** — a probabilistic, optimistic-sweep, or maker-from-tape fill
  (`MODELLED` evidence); `decision.confidence` carries the probability where the
  policy set one.

## The exact code mapping

`fill_evidence_level(decision)` is pure and total — every `FillDecision` maps to
exactly one level:

```
INDETERMINATE                          -> UNEVIDENCED
NO_FILL                                -> PROVEN            (a definite miss is settled data too)
FILL & evidence in {TRADED_THROUGH,
                    AUCTION_PRICE}     -> PROVEN
FILL & evidence in {TOUCHED_AT_LIMIT,
                    MODELLED}          -> ASSUMED
```

`PROVEN` means "the data decided," in *either* direction — a proven fill and a
proven no-fill are both settled; the level is about evidence, not outcome.

## Policies are floors on this scale

A fill policy *is* a rule for the lowest evidence level it will act on — a tidier
definition than three ad-hoc policies:

| Policy | Acts down to | On a bare touch it… |
|---|---|---|
| `hard` | PROVEN | abstains → UNEVIDENCED |
| `soft` | ASSUMED / TOUCH | fills → ASSUMED (touch) |
| `probabilistic`, book-walk | ASSUMED / MODELLED | fills by model → ASSUMED (modelled) |

## The metric: a run is a distribution, not a number

Aggregate FEL over an order flow and you get a **profile**, not a single rate. The
useful headline is the **assumption exposure** — the share of the flow that is not
PROVEN (i.e. ASSUMED + UNEVIDENCED). A high exposure that does not move the P&L is
harmless; the danger is exposure that the result depends on (the F3 / T4
materiality axis).

**Worked example — this is F2, re-read.** The probe of a resting buy at the daily
close, under `hard`:

- *close only* (the current adapter withholds the low): the order can only be
  seen to *touch*, so every decision is UNEVIDENCED. **Proven share 0%.**
- *full daily OHLC* (the low is in the corpus): orders the day traded *through*
  become `TRADED_THROUGH` → PROVEN, orders below the low become definite
  `NO_FILL` → PROVEN, and only the exact touch stays UNEVIDENCED. **Proven share
  ~64%, unevidenced ~36%.**

So F2's "100% → 36% indeterminate" is more honestly stated as **"the proven share
rises from 0% to 64% once the bar is given its own high/low"** — a confidence
profile improving, not a defect count. The residual UNEVIDENCED share is the
intrinsic touch-at-limit, and at tick it is traded for a MODELLED/ASSUMED share
whose size depends on the queue assumption.

## Scope, and what is deferred to the writing

Shipped now: the ordered `FillEvidenceLevel`, the categorical `AssumptionKind`,
and the pure `fill_evidence_level` / `assumption_kind` classifiers, with tests.
Nothing in the engine's decision path changed — FEL is a lens over the record the
engine already produces.

Deferred (paper-session work, deliberately not built ahead of the writing):

- **Report wiring** — have `ExchangeSession` emit a FEL *distribution* per run
  alongside `indeterminate_report()`, so a strategy's confidence profile is one
  call. Today the profile is assembled from `fills()` (their `evidence`) plus the
  indeterminate count.
- **Figure reframe** — redraw F2/T4 around the FEL profile (the reframed-F2 draft
  already prototypes this).
- **A 4-level refinement**, if the paper wants it: split `ASSUMED` into TOUCH and
  MODELLED tiers, and/or carve a `SIZED` tier out of PROVEN for a fill whose
  *price* is proven but whose *quantity* was capped by observed volume. Both are
  derivable from `assumption_kind` and the decision's quantity without disturbing
  the 3-level spine, so the spine can ship and the refinement can wait.
