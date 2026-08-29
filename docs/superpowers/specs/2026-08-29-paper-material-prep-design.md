# Paper-Material Preparation — Design Spec

**Date:** 2026-08-29
**Status:** design, approved in brainstorming; pending spec review before implementation.
**Author session:** derived from the 8-angle paper-readiness review (`wf_523475cc-f84`) and the brainstorming that followed.

## 0. What this is, and what it is not

This session prepares the **material** a writer will later assemble into the RIVF'26 paper:
library code that models correctly, generated **artifacts** (figures, tables, bibliography),
and **gathered numbers** with documented provenance. It does **not** write paper prose and
does **not** stand up the LaTeX manuscript. The deadline is non-binding (working horizon
Sep 2026 – Feb 2027, `paper-outline.md:461`); the constraint is content correctness, not
calendar.

**North star:** this is a *high-fidelity* library. Where a choice exists between a shortcut
and modelling the thing correctly, model it correctly. Every decision below was made on that
basis.

## 1. Framing principles (resolved in brainstorming)

### 1.1 Data posture — we do not claim a corpus
The data shipped **with the library** is only the minimal fixtures needed to reproduce the
Jx scenario and Sx strategy suites. We do **not** position data as a contribution or asset —
it is our weakest link, and third parties (vnstock, brokerages) provide better. The larger
measurement numbers are computed against the **best data we actually have** and are framed as
*demonstrations of library capability*, each tagged with its provenance.

### 1.2 Our data ceiling, stated honestly
The best data we have is **production tick market data plus a reconstructed 3-level book (with
sizes)**. We do **not** have — and must never imply we have — the exchange's **full order
book** (all levels, order IDs, the true queue, deletions). Every figure that reports
indeterminacy labels which part comes from the **resolution limit** (a daily bar cannot see
intraday fill existence — unfixable by any data) versus **our data ceiling** (a reconstructed
3-level book cannot establish queue position or depth past level 3 — we are not the exchange).
We "fetch to drain" only genuinely fetchable gaps (a band missing from a tick row we already
hold); the other two we own and name.

### 1.3 Reproducibility, two tiers
- **Reproducible core (shipped):** the Jx + Sx suites and their in-repo fixtures. `clone →
  pip install → pytest` reproduces them for any third party. This is the library's proof.
- **Provenance-documented demos:** the headline measurement numbers, some computed against
  production data we do not redistribute. `reproduce_measurements.py` regenerates the
  corpus-available ones; a separate, clearly-labelled path regenerates the production-sourced
  ones. The claim narrows from "regenerates *every* number" to the honest two-tier statement.

### 1.4 For our own demonstrations, feed the library the best data we have
Approximations and fallbacks (e.g. close-as-settlement) remain in the library as **graceful-
degradation features** for users who lack data, but our own numbers never lean on them — we
supply the real inputs. Consequence: the settlement-substitution *error measurement* is
dropped (nothing to measure when we always supply the real settlement price); the fallback is
retained and marketed as a feature that flags its own substitution.

**"Best data" means *completeness*, not resolution — read this before touching W2.** "Best
data" is the fullest set of *fields* we hold at whatever resolution a given run uses (real
settlement prices, real bands, book sizes), so leftover indeterminacy is the honest floor
rather than a gap we could have filled. It is a **separate axis from resolution**, and the two
must never be conflated:
- **Real strategy runs** should take the **finest resolution available and fall back to bar
  only where tick is absent** — we always want to give the user the finest resolution possible.
- **F2 (W2) is the deliberate exception.** It runs the *same* population at *both* bar and tick
  precisely to measure how much the answer depends on the rung; the cross-resolution contrast
  *is* the figure. F2 never "picks the best" resolution — that would delete the comparison it
  exists to make.

## 2. Decisions register

| Fork | Decision |
|---|---|
| Reproducibility bar | (B) re-contextualized — §1.1–1.3 above |
| De-emphasized data numbers | Keep dataset-audit (reframed as capability) + reproducibility-reframe; **drop** off-grid UPCoM, corpus-scale boast, and the settlement-error measurement; **retain** the settlement fallback as a marketed feature |
| MUST #4 (daily variation margin) | **Wire it fully** — roll the VM baseline daily *and* move realised P&L in cash to the deposit |
| F2 attribution | **(A)** — name the resolution-intrinsic cause (`FILL_UNOBSERVABLE_AT_RESOLUTION`); axis titled "by cause", not "by rule"; label resolution-limit vs data-ceiling segments |
| F2 data | Best available (production tick + reconstructed 3-level book), so the residual rate is the honest floor, not a data-gap artefact |
| F3 | **Two-panel** — fill axis (soft/hard/probabilistic) and queue axis (optimistic/conservative/probabilistic), each joined to its own indeterminate rate |
| Margin number | **(i) Rebuild from the real model, regime-split** — retire the disavowed maintenance-ratio incidence |

## 3. Disposition of the de-emphasized data numbers

| Item | Disposition |
|---|---|
| Close-as-settlement error (46 expiries, 0.042% mean-abs) | **Drop the number.** Retain the fallback as a graceful-degradation feature that flags its substitution; reframe outline §5.3 from "measured-cost limitation" to "our results supply real settlement prices, so they never invoke it." |
| Ten-check dataset audit | **Keep, hard-reframe** from "our corpus is characterized" → "the library characterizes whatever feed you point it at." Numbers become examples of the tool working, run on the shipped fixtures. |
| Off-grid UPCoM closes (15,504/30) | **Drop entirely** — pure data property, and the outline itself calls them vendor artefacts. |
| Corpus dimensions (2.5M rows / 1,725 tickers) | **Drop as a headline.** At most a neutral "computed on N instrument-days of sample data." |
| "reproduce regenerates every number" | **Reframe** to the two-tier statement in §1.3. |

## 4. Workstreams

Each workstream is built the way the rest of the project is: TDD, mutation testing where it
applies, numbers wired into `reproduce_measurements.py` where they are corpus-reproducible,
figures rendered to a committed PNG **plus** the underlying data table so every plotted number
is inspectable. Wilson score intervals accompany every headline **proportion**.

### W0 · Doc-truth reconciliation *(doc-only; ~1 day; gates truthful downstream writing)*
**Why:** the writer quotes these documents; a stale or withdrawn claim propagates into the paper.
**Tasks:**
- **B4 — purge "Article 13".** Rewrite `literature-review.md:832-836` and source key `:1163`:
  pre-KRX 80/90/100 tiers → `low`/UNVERIFIED, post-KRX → not a margin rule (the only 80/90/100
  in QĐ 26 is Điều 29 = position limits). Delete every "Article 13" attribution. Reconcile with
  `rulebook:613,:638,:641,:1118`.
- **G3 — date-scope the margin sentence.** In `paper-outline.md` (abstract + §4.1/§4.4 wording
  via `literature-review.md`) restrict `MR = IM + VM` to **pre-KRX (≤2025-05-04)** and *claim*
  the **post-KRX scenario regime** the code implements (`scenario_margin.py`), rather than
  conceding it unmodelled.
- **MUST #5 → RESOLVED** in `PUBLISH-CHECKLIST.md` (still says "Open, and live" at `:29`), citing
  the D71 fix (commit `74e667a`, `exchange.py:2665-2668`, `test_j37_tick_atc_published_close.py`).
- **Suite counts** everywhere: checklist `:7,:28,:30`, `FEATURES.md:29`, `outline:302`, README
  badge → per-suite **market 1628 / scenarios 38 / strategies 11**; drop the "17 failing" datahub
  qualifier (they pass under the venv).
- **§5.4 "sizes not populated"** (`outline:388`) — scope to the sized dev extract; the book-walk/
  S8/S9 read real sizes (`book_walk.py:1134`). `FEATURES.md:443` already corrected it.
- **§9 queue wording** (`outline`) and `exchange-simulator-design.md §16:678-679` — tighten
  "the data cannot support queue matching" to "recovering our own queue *rank* (distinct from
  the *declared* queue axis reported in §7/F3)."
- **FEATURES.md D71 rows** (`:248,:711,:712,:1605`) — past tense; it is FIXED (`:1262`).
- **Spec §6 / S9 guardrail** — extend the `literature-review.md:936-939` internal-consistency
  note to the new maker-fill spec so the binding "the spread is the reported result" guardrail
  (`outline:12-16`) isn't tripped; S9 measures maker *shares*, not P&L.
- **Phụ lục 2** — `literature-review.md §5.5/§9` + `outline:412-413` say portfolio margining is
  unverifiable "in Phụ lục 02, which VSDC does not publish"; superseded — obtained 2026-08-26
  (`rulebook:665`). Narrow to: post-KRX now primary-sourced; only pre-KRX (QĐ 96-era) portfolio
  margining unverifiable.
- **Data-posture reframes** (from §3): rewrite `outline §6` (corpus → BYO-data + two-tier
  reproducibility), §5.3 (settlement → feature), §6 audit (→ capability); delete off-grid UPCoM
  and corpus-scale headlines.
**Acceptance:** every claim in these docs is either code-verified current or explicitly hedged;
no document contradicts another (checklist ↔ FEATURES ↔ outline ↔ rulebook); a re-grep for
"Article 13", "630", "17 failing", "Phụ lục 02 … does not publish" returns only corrected text.

### W1 · Daily variation-margin cash settlement *(library code, TDD + scenario; ~1–2 days; blocks W4)*
**Why:** MUST #4. `DerivativesAccount.settle_daily` (`deposit.py:1259`) has no session call site
(`overnight.py:109`), moves no cash by design (`deposit.py:1268`), and daily cash MTM is a
declared Tier-1 non-goal (`deposit.py:834-838`). Vietnamese futures settle P&L in cash daily;
here they do not, so realised P&L never reaches the deposit and the balance sits frozen. "Model
correctly" → wire it fully.
**Tasks:**
- Add a session call site in the daily mark advance (currently only `observe_marks` is called)
  that runs `settle_daily` per settlement day, rolling the VM baseline off entry.
- Add the cash-moving plumbing so realised daily P&L debits/credits the deposit (this reverses
  the declared non-goal — update the `deposit.py:834-838` and `:1268` docstrings and the
  `FEATURES.md` "Author's call" row in the **same commit**).
- Use the real daily settlement price (production data); the close-as-settlement fallback stays
  only for absence (§1.4).
- **Test:** a new scenario (Jx) — a leveraged VN30F position marked over several sessions —
  asserts the deposit balance tracks cumulative realised P&L day by day (not frozen), and that
  a losing path draws the deposit down toward the margin call W4 will measure.
**Acceptance:** the scenario passes; `market` suite green; the frozen-balance defect
(99,948,008đ for 18 sessions) no longer reproduces; checklist MUST #4 → RESOLVED with the call
site cited.

### W2 · F2 — indeterminate rate by cause and resolution *(~3–4 days)*
**Why:** the paper's third contribution ("§5 is an assertion until F2 exists", `outline:310`).
The per-run meter exists (`session.indeterminate_report()`, `exchange.py:2108`;
`IndeterminateReport`, `types.py:2330`) but nothing aggregates it across a population or by
resolution.
**Tasks:**
- Introduce the resolution-intrinsic **cause** in the library's indeterminacy vocabulary so a
  fill decision that cannot establish fill *existence* at bar resolution names
  `FILL_UNOBSERVABLE_AT_RESOLUTION` rather than reporting an empty `by_field` (today a 1d
  buy-and-hold reports `rate=1, by_field={}`). Locate where the fieldless INDETERMINATE
  originates (soft/hard policy at bar resolution) and name the cause at the source — consistent
  with "nothing silently defaults." This is a small, correct-by-design library change, not a
  measurement-layer guess.
- `measurements/indeterminate_rate.py`: replay the **same** fixed population at **both**
  `Resolution.BAR` and `Resolution.TICK` — the cross-resolution comparison *is* the figure, so
  running both is deliberate, **not** a "pick the finest rung, fall back to bar" selection (see
  §1.4). Feed each run the fullest fields we hold at its resolution. Accumulate
  `indeterminate_report()` into a rate **per (resolution × cause)**, where cause ∈
  {`FILL_UNOBSERVABLE_AT_RESOLUTION`, `BOOK`, `BOOK_SIZE`, `VOLUME`, …}. The comparison
  population is bounded by **tick availability** (the same instrument-days must run at both
  rungs), so reuse the `bar_vs_tick` HSX instrument-day set, which already has both.
- Classify each cause as **resolution-limit** or **data-ceiling** for the figure legend.
- Wilson CIs on each rate. Wire as a new `reproduce_measurements.py` step.
- Render **F2**: one stacked bar per resolution, every segment a named cause, legend marking
  resolution-limit vs data-ceiling. Committed PNG + data table.
**Acceptance:** F2 regenerates from the shipped/available data; every indeterminate order in the
population maps to a named cause (no unlabeled remainder); the daily bar shows the
resolution-intrinsic cause as its visual majority; tick shows the data-ceiling causes;
`reproduce` runs the step clean.

### W3 · F3 — cross-policy divergence, two-panel *(~2 days; needs W2's rate primitive)*
**Why:** the second half of the gating deliverable; "reported jointly with the indeterminate
rate" (`outline:307-311`).
**Tasks:**
- **Panel 1 — fill axis.** Reuse S7 (`test_s7_fill_sensitivity.py`, S1 under soft/hard/
  probabilistic). For each arm emit the divergence metric **and** that arm's
  `ledger._session.indeterminate_report().rate`. `compare_policies()` /
  `DivergenceReport.indeterminate_rate` (`fills.py:1942`) already produces the joint shape —
  promote it out of tests.
- **Panel 2 — queue axis.** Reuse S9 (`test_s9_queue_sensitivity.py`, S8 under optimistic/
  conservative/probabilistic), same joint emission (queue spread ≈19% beside each arm's rate).
- `measurements/cross_policy_divergence.py`: assemble both panels; Wilson CIs; wire into
  `reproduce`.
- Render **F3**: two panels, divergence-vs-policy with the indeterminate rate overlaid/annotated
  per arm. Committed PNG + data table.
**Acceptance:** F3 regenerates; each arm carries both its metric and its indeterminate rate; the
two panels are labelled as the two distinct policy families (they are not one strategy — see
§5 default 1).

### W4 · Margin, rebuilt regime-split *(~2–3 days; needs W1)*
**Why:** the current 12.60% headline fires on a maintenance ratio the code disavows
(`margin.py:162-166`, `derivatives.py:180`, flat `vsd_initial=0.17` at `:196`) and is mislabeled
"the utilisation test." There is no maintenance ratio in either Vietnamese regime.
**Tasks:**
- Retire `margin_incidence.py`'s maintenance-ratio incidence from the paper set (remove from
  `reproduce`'s margin step, or keep only as an explicitly-labelled naive contrast); fix its
  `:12-14` "17.5%" docstring regardless.
- Drive the **real** `DerivativesAccount` (with W1's daily VM settlement) over a VN30F population
  and report a **well-defined breach incidence, split by regime**:
  - **pre-KRX (≤2025-05-04, IM+VM):** a call = VM losses deplete the deposit below **IM** on the
    dated IM series (10 → 13 → 17%). No maintenance ratio, no reliance on the collapsed 80/90/100
    tiers.
  - **post-KRX (2025-05-05+, scenario margin):** a breach = scenario **MR > available deposit**,
    via the wired `scenario_margin.py` (`overnight.py:151`).
- The **same position, two regimes, two incidences** is the concrete demonstration of the *dated
  rule editions* lead claim — assemble it as such.
- Provenance-tag (production data, incl. post-2022 for the post-KRX regime); Wilson CIs.
**Acceptance:** the 12.60%/`ratio<0.17` path no longer sources any paper number; both regime
incidences compute from the real account model on the dated IM series; the regime contrast is a
named result; margin numbers carry provenance + CIs.

### W5 · Band-conformance *(~1–2 days; corpus-reproducible, no production data)*
**Why:** the momentum blocked-entry (5.84%) and bar-vs-tick lock (97.56%) families are SQL
equality on the vendor `quote_ceil` field (`equity_admission.py:118`, `bar_vs_tick.py:109`) —
for a paper about engine fidelity. The engine computes its own ceiling (`datahub.py:128`).
**Tasks:**
- `measurements/band_conformance.py`: per row, assert the engine's BAND_LIMIT/BAND_LOCK verdict
  == the vendor-ceiling proxy; report the agreement rate and the disagreement count.
- Wire into `reproduce`.
**Acceptance:** the band-family results are engine-backed ("the engine reproduces the observed
lock, N disagreements") rather than "a query anyone could write"; regenerates from the shipped
corpus.

### W6 · Artifacts *(~1–2 days)*
**Tasks:**
- **F1** — order state machine, drawn from `src` (the order-state enum + transitions), with
  INDETERMINATE shown as an event on the resting arc, not a leaf. No data dependency.
- **T3** — dated rule editions across the simulated window with effective dates + confidence;
  `dated_rules.py` already assembles the structured data — render it.
- **T4** — measured-results table, each row carrying fill policy, resolution, assumption set,
  provenance, CI.
- **T5** — tradeoff register (simplification, what it buys, fidelity given up, measured cost,
  revisit trigger).
- **`references.bib`** — from the `literature-review.md` citation table.
- **G6 fix** — `measure_test_suite` returns `None` (root-level `--collect-only` aborts on
  `fastmcp`, `tests/test_mcp/conftest.py:7`; `testpaths` excludes scenarios/strategies). Collect
  the three suites separately and sum, or `--ignore=tests/test_mcp` / make `fastmcp` an extra.
**Acceptance:** F1 renders from src; T3/T4/T5 render from committed data; `references.bib` covers
every citation the outline uses; `measure_test_suite` returns the correct total.

### W7 · Shipped fixtures *(~0.5–1 day; can run early, independent)*
**Why:** §1.3's reproducible core is only real if a third party can run the Sx suites. S8/S9
currently read the external dev extract; some Sx read production/extract.
**Tasks:**
- Audit each Sx (and any Jx that isn't fully synthetic) for its data dependency.
- Curate the **minimal** instrument-day slices (e.g. FPT + VN30F tape for 2022-11-09) into a
  versioned in-repo fixtures directory (target a few MB); repoint the suites via an env/default
  path that prefers the shipped fixture.
- Document the provenance + how to regenerate a fixture from production (read-only).
**Acceptance:** `clone → pip install → pytest strategies/` passes with no external dataset
mounted; fixtures are small and versioned; provenance documented.

## 5. Proposed defaults (flagged for veto during spec review)

1. **F3 pairing** = S1 (fill axis) + S8 (queue axis), two panels — the two axes are different
   policy families (soft/hard/probabilistic vs the book-walk queue), so "one strategy for both"
   would be dishonest.
2. **Fixtures** = small curated real slices committed in-repo (~few MB), not a fetch script —
   cleanest third-party reproducibility.
3. **Rigor** = Wilson score intervals on the headline **proportions** (F2 rate, F3 divergence,
   margin incidence); defer heavier robustness (2021-vs-2022 sub-period) to nice-to-have.
4. **Figures** = matplotlib → committed **PNG + underlying data table**, so every plotted number
   is inspectable and regenerable.

## 6. Sequencing & critical path

```
W0 doc-truth ───────────────────────────────► (parallel throughout; gates truthful docs)
W7 fixtures ────────────────────────────────► (independent; do early)
W1 daily VM ──► W4 margin
           └──► W2 F2 ──► W3 F3
W5 band-conformance ────────────────────────► (independent of the spine)
W6 artifacts ───────────────────────────────► (last; consumes W2–W5 outputs for T4)
```
Critical path: **W1 → W2 → W3 → W4**. W0 and W7 start immediately; W5 slots in any time; W6 last.

## 7. Definition of done (this session's deliverable)

- All four blockers closed: F2 (W2), F3 (W3), MUST #4 (W1), Article-13 (W0).
- Margin rebuilt correctly (W4); band results engine-backed (W5).
- Docs internally consistent and current (W0).
- Figures F1/F2/F3 and tables T3/T4/T5 rendered as committed artifacts; `references.bib` built.
- `reproduce_measurements.py` regenerates every corpus-reproducible number; production-sourced
  numbers regenerate from a documented, provenance-tagged path.
- Sx suites reproducible from shipped fixtures.
- All three suites green.
- **Not** done here (by design): paper prose, LaTeX skeleton.

## 8. Risks & open questions

- **W1 reverses a declared Tier-1 non-goal** (daily cash MTM). Deliberate, per "model correctly";
  must be reflected in docstrings + FEATURES in the same commit, or the docs will contradict the
  code again.
- **W2 cause-naming site.** The exact place the fieldless bar-resolution INDETERMINATE originates
  must be found and named; if it turns out to span several policies, the cause is added once in
  the shared decision path, not per-policy.
- **W4 population + window** (which VN30F contracts, hold length) are parameters that shape the
  incidence; pick a defensible, documented population, not one tuned to a number.
- **Production-data access** is assumed available and read-only for the post-KRX margin and any
  post-2022 slice. `algotradeDB` is **read-only** — never write.
- **Fixture size** (W7): if a genuinely-needed slice is large, prefer down-sampling the
  instrument-day set over shipping a heavy fixture; log what was reduced.
```
