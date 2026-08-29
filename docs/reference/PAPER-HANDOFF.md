# RIVF'26 paper — session handoff

*The single doc to read first when starting a paper-writing session. Written
2026-08-29 at the end of the material-prep + framing-cleanup work. Everything the
engineering side produced is done and verified; the deliverable now is prose.*

Branch `rivf26-wp1-wp2-wp4`, **unmerged and unpushed** — the commits exist only on
this laptop. **Push before anything else.**

---

## 1. How to use this doc

Read §2 (the thesis), §3 (the guardrails — what the paper must NOT overstate),
and §4 (FEL, the new spine). Then §7 for where every number and figure lives, and
§9 for the immediate next steps. §8 is the one genuinely unfinished piece (the F2
reframe) that a paper session should decide on.

Numbers: **quote them from `docs/reference/tables/t4_measured_results.md`, never
from memory or from this doc.** T4 is the verified source; every row was
regenerated against the corpus on 2026-08-29 with CIs and provenance.

---

## 2. The thesis, and where it lives in the code

Plutus is **not a backtester.** It is an executable model of Vietnamese *exchange*
rules — admission and position survival — with no strategy engine, portfolio, or
P&L. The framework claim, verified against the code (§3), is a **two-halves
asymmetry**:

- **`admits()`** — stateless order admission (`Exchange.admits`,
  `exchanges/equity.py`): band / lot / tick-grid / order-type legality. Dominates
  the equity exchanges (HSX/HNX/UPCoM).
- **`sustains()`** — stateful position survival. The *authoritative* implementation
  is the **session margin path** (`session/deposit.py::MarginMonitor` +
  `ExchangeSession._overnight_margin`), not the legacy `Exchange.sustains` (see
  §3, caveat 3). Dominates the derivatives exchange (HNXDS), where admission is
  nearly trivial.

Supporting pillars, all verified in code:
- **Effective-dated rule editions** — `Rulebook.at(ts)` resolves every rule per
  simulated instant and *refuses* out-of-window editions (`RuleStatus.UNKNOWN`,
  raises `UnresolvedRule`; the post-KRX margin model *raises* on a pre-cutover
  date). The KRX cutover is `2025-05-05`. (Table **T3**.)
- **Fill policy × queue assumption** — two independent pluggable Protocol axes
  (`FillPolicy`: soft/hard/probabilistic; `QueuePolicy`: optimistic/conservative/
  probabilistic), each carrying `.signature`/`.assumptions`.
- **Fill Evidence Level (FEL)** — the honest confidence grade on every fill; the
  new §5 spine (§4 below).
- **Broker + exchange as one entity** — `ExchangeSession` is the single
  counterparty; a `BrokerProfile` selects the margin model from a 14-firm registry
  (SSI/HSC/DNSE/TCBS…). Caveat 4 below.
- **BYO-data posture** — the library characterises whatever feed you give it; the
  paper does **not** claim a corpus.

The rare, strong fact from the audit: **the code's own identifiers are the paper's
concepts** (`admits`/`sustains`, `Rulebook.at`, `Verdict.INDETERMINATE`,
`FillPolicy`/`QueuePolicy`, `BrokerProfile`/`MarginModel`). The framework is
legible from the class names, not just the prose.

---

## 3. Framing audit — the five guardrails (paper must not overstate)

An adversarial audit of `src/plutus/` (2026-08-29) confirmed all six framing
claims are genuinely implemented. Five caveats remain — the honesty guardrails so
a reviewer cannot falsify a sentence:

1. **`evaluation.PerformanceEvaluator` is a shipped, functional return/risk
   calculator** (Sharpe, Sortino, VaR…). "Not a backtester / no P&L" is true of
   `market/`+`session/` but **falsifiable for the whole library**. → Scope the
   claim to `market/`+`session/`. *(Done in code: `evaluation/__init__.py` now
   states it is an optional post-hoc metrics helper over a caller-supplied returns
   series — barely mention it.)*
2. **~~`core/` dead vocabulary~~ — RESOLVED.** The pre-exchange-model trader stack
   (`bot`/`algorithm`/`portfolio`/`position`/`transaction`) was archived to
   `archive/legacy-trader-stack/` (§6). No longer a contradiction a reader sees.
3. **`Exchange.sustains` (HNXDS) is self-labeled legacy** — it uses a
   maintenance-margin ratio "Vietnam does not publish." Point "the survival half"
   at the **session margin path**, not `Exchange.sustains`.
4. **Broker-profile selection never switches the *running* engine for any shipped
   firm** — all shipped profiles are intraday → `deposit.py` (IM+VM); the scenario
   grid is computed only as an *overnight report*; an overnight-facing profile is
   refused at build. So SSI-vs-HSC changes ladder levels/denominator/provenance,
   **not** a different running engine. Don't claim the profile "swaps the margin
   model" for shipped firms. (Also: a homonym `BrokerProfile` pair, self-registered
   as gap G18.)
5. **The queue axis and the probabilistic fill arm aren't in the session package's
   public `__all__`** — first-class in code, reachable by submodule import. Fine to
   say they exist and are pluggable; don't imply they're front-and-center.

---

## 4. FEL — the new spine for §5

Full reference: **`docs/reference/fill-evidence-levels.md`**. Implemented in
`src/plutus/market/session/evidence_level.py`, exported from the session package,
8 tests. **The user has approved this model.**

FEL grades every `FillDecision` by how much data backs it, replacing the scary
binary "indeterminate?" with a confidence profile:

- **PROVEN** — the data settles it (traded-through, auction cross, or definite
  no-fill).
- **ASSUMED** — a fill supplied under an assumption, with a categorical
  `AssumptionKind`: **TOUCH** (soft on a bare touch) or **MODELLED** (probabilistic/
  sweep/maker).
- **UNEVIDENCED** — INDETERMINATE; the data is silent. The **bottom rung**, not a
  failure.

Design decisions already made (do not relitigate without reason): **3 ordered
levels + a categorical kind**, not 4 ordered tiers — keeps the four-way
distinction without forcing an indefensible ordering between touch and modelled.
A policy = a rule for the lowest level it acts on (hard=PROVEN, soft=ASSUMED/touch,
probabilistic & book-walk=ASSUMED/modelled).

**Deferred to the writing (deliberately not built ahead):** (a) wire the FEL
*distribution* into `ExchangeSession` alongside `indeterminate_report()`; (b)
reframe F2/T4 figures around the FEL profile.

### The rename resolution
"Indeterminate" was too obscure/scary. Resolution: the reader-facing vocabulary is
**FEL** — an INDETERMINATE fill is **UNEVIDENCED**; the neutral phrase for a fill
that rests on an assumption is **assumed** and the metric is the **assumption rate**
(share not PROVEN). The **API keeps `indeterminate_report()` / `FillOutcome.
INDETERMINATE`** for now — renaming it is a mechanical but wide change deferred to
the writing (or skipped; the paper can introduce the reader-facing word while the
code keeps its identifier).

---

## 5. Artifacts — figures and tables

All committed, all render from committed/verified data (generators noted):

| Artifact | What | Generator / location |
|---|---|---|
| **F1** | order state machine (INDETERMINATE as an event on the resting arc) | `figures/f1_state_machine.py` → `figures/f1_order_state_machine.png` |
| **F2** | indeterminate rate by (resolution × cause) — **but see §8, this is being reframed** | `measurements/indeterminate_rate.py`, `strategies/test_f2_resolution_indeterminacy.py`, `figures/f2_indeterminate_rate.{png,json}` |
| **F3** | cross-policy divergence joined to the indeterminate rate | `strategies/test_f3_cross_policy.py`, `figures/f3_cross_policy_divergence.{png,json}` |
| **T3** | dated rule editions | `docs/reference/tables/t3_dated_rule_editions.{md,png}` (data: `measurements/dated_rules.py`) |
| **T4** | measured results — **the verified numbers source** | `docs/reference/tables/t4_measured_results.md` |
| **T5** | tradeoff register | `docs/reference/tables/t5_tradeoff_register.md` |
| bib | citations | `docs/reference/references.bib` |

`reproduce_measurements.py` regenerates all 10 measurement families end-to-end
(F2 is step `[10/10]`, needs `--tick-root` for the local_quote book).

The section→artifact map is in **`docs/reference/paper-outline.md`** (every §
already points at its figure/table).

---

## 6. Cleanup done (framing hygiene)

- Dead trader stack archived to `archive/legacy-trader-stack/` (no `__init__.py`,
  not importable, not shipped; history kept via `git mv`). Live value types
  (`core/order.py`, `constant.py`, `instrument.py`) stayed. FEATURES.md D31 marked
  resolved.
- `evaluation/` kept (216 passing tests, functional) but scoped in its docstring as
  an optional post-hoc metrics helper, not part of the exchange model.

---

## 7. Suite state

Green, each suite in its own process (they must run separately — `scenarios/` and
`strategies/` both define a top-level `_harness`, so one pytest invocation over
both shadows one):

- `tests/market` **1646** (1638 + 8 new FEL tests), `tests/datahub` 89,
  `tests/test_evaluation` 216, `scenarios` 38, `strategies` 13.
- The paper's canonical badge (market + scenarios + strategies) is **1697**.
- `measure_test_suite` collects the three canonically and `--ignore`s
  `tests/test_mcp` (needs the optional `fastmcp` extra). The badge citations in
  FEATURES.md, PUBLISH-CHECKLIST.md, and paper-outline.md are **current at market
  1646 / scenarios 38 / strategies 13** as of this handoff.

---

## 8. The one unfinished piece — the F2 reframe (decide in a paper session)

F2 as committed says "100% indeterminate at daily bar." **This overstates the
floor and is an artifact of the adapter withholding the daily low.** Verified this
session:

- The daily extremes (`quote_max`/`quote_min`) are **already in the corpus** but
  **not wired into `DataHubSource.interval()`** (the datahub docstring flags this
  as the pending change "in the same change as volume").
- Enriching the bar interval with the real low/high collapses the rate: **close
  only 100% → full OHLC ~36%**, and the residual is *entirely* the intrinsic
  touch-at-limit (the `low` data-ceiling cause vanishes). In FEL terms: **the
  PROVEN share rises 0% → ~64%.**
- An aggressiveness sweep (bar, full OHLC) shows the residual is **localized**:
  ~0% indeterminate when the buy rests below the close (decidable no-fill) or above
  it (decidable fill), spiking to ~33% only *at* the touch.

**Two decisions for the paper session:**
1. **Wire `quote_max`/`quote_min` into `DataHubSource.interval()`** (a ~15–20 line
   `src/` change the docstring already calls pending; also gives the engine a real
   capability: definite `NO_FILL` on a limit the day's low never reached). This
   makes the honest ~36% a real engine output rather than a measurement-side patch.
   Watch for tests asserting the current close-only behaviour.
2. **Reframe F2 around FEL** — the reframed-F2 draft (a 2×2: data-richness ladder,
   aggressiveness curve, and F3-style materiality) was prototyped in the scratchpad
   (ephemeral — regenerate from the numbers above and `measurements/
   indeterminate_rate.py`). The user liked options "aggressiveness curve" and
   "real-strategy materiality"; dropped the "demote it" option.

The user's framing to preserve: the indeterminacy is **small, intrinsic, and
localized; and it moves real results** — not a scary/trivial 100%.

---

## 9. Immediate next steps

1. **Push the branch.**
2. Draft the paper against `docs/reference/paper-outline.md`, pulling every number
   from T4. Lead §5 with FEL (`fill-evidence-levels.md`). Honor the §3 guardrails.
3. Decide the F2 reframe (§8) — probably early, since it changes a figure and a
   headline.
4. Optionally: wire the FEL distribution into the session report, and/or the
   daily-OHLC extremes into the adapter (both improve the story; neither blocks the
   writing).

See also the `rivf26-work-status` auto-memory for the same state in brief.
