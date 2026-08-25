# Paper outline

**Status:** outline only. Another session writes the prose. Nothing below is drafted text.

**Companion documents.** `docs/reference/literature-review.md` holds the positioning,
the cited comparison tables and the **narrowed claim sentences that must be used
verbatim**. `docs/reference/vn-exchange-rulebook-2020-2026.md` holds the 400 dated rules
with citations and per-row confidence. `docs/superpowers/specs/2026-08-25-exchange-simulator-design.md`
holds the design, the tradeoff register (§15.1) and the stated assumptions (§16).

**Non-negotiable constraint on the writer.** Three claims were adversarially refuted and
survive only in narrowed form. Use `literature-review.md` §4.1, §4.2 and §4.3 **verbatim**.
The guardrail list in §4.3 is binding: the words "pluggable", "swappable",
"hard/soft/probabilistic family", "the spread is the reported result" and "no prior art for
an indeterminate outcome" must not appear.

---

## 1. Title options

Ranked. Each leads with what survived the attacks, not with what was refuted.

1. **Effective-Dated Exchange Rules and Indeterminate Fills: A Vietnamese Exchange
   Simulator with a Broker-Facing API** — most accurate; leads with the two surviving
   contributions.
2. **What the Data Cannot Decide: Per-Order Indeterminacy in a Rule-Dated Simulator of the
   Vietnamese Exchange** — leads with the strongest single novelty.
3. **Plutus: A Dated Order-Admission Rulebook for HOSE, HNX, UPCoM and HNXDS** — most
   concrete, least ambitious; good if the venue prefers systems papers.
4. **From Trading Calendar to Settlement Calendar: Modelling Vietnamese T+2, Price Bands
   and Segregated Derivatives Margin** — leads with the one mechanism no other engine wires
   correctly.
5. **An Exchange, Not a Backtester: Simulating Vietnamese Market Rules Behind a Broker
   API** — best for a practitioner audience; weakest for a reviewer looking for novelty.

Avoid: anything containing "high-fidelity" unqualified (EvoMarket used it in April 2026),
"data-source agnostic" (refuted), or "pluggable fill model" (refuted).

## 2. Abstract sketch

Six moves, roughly one sentence each.

1. **Problem.** The gap between a backtest and live trading is dominated by execution
   assumptions, and those assumptions are national and dated — a tick grid, a band, a lot,
   an auction eligibility rule, a settlement cycle, a margin regime. Anchor to Patton &
   Weller's 2.2–8.5% momentum cost range and Menkveld et al.'s finding that non-standard
   errors are "on par with standard errors".
2. **What exists.** Credit generously and specifically: LEAN models T+N and a Reg NMS
   price-dependent tick grid; RQAlpha enforces China's bands, call auction and T+1 with
   segregated stock/future accounts and date-resolved margin ratios; NautilusTrader, LEAN,
   Zipline, RQAlpha and hftbacktest all let the user replace fill determination; Forex
   Strategy Builder reported an ambiguity count in 2011.
3. **The gap.** Dated rule editions exist for calendars and parameters, never for order
   admission; and no engine distinguishes "this order did not fill" from "this data cannot
   establish whether this order filled" at per-order granularity through the order status
   the caller receives.
4. **What we built.** A simulated Vietnamese exchange behind a broker-shaped API, with a
   400-row dated rulebook resolved per simulated instant, a VSDC settlement-business-day
   calendar wired to unsettled cash and unsettled shares, MR = IM + VM tested as
   utilisation in a segregated deposit account, and INDETERMINATE as a per-order status
   attributed to the rule that could not be evaluated.
5. **Results, one line.** The headline numbers from §7 — the blocked-entry rate at the
   tradeable lag, the tick-grid conformity contrast, the bar-vs-tick lock divergence, the
   margin-call incidence — each stated with the assumption it rests on.
6. **Limits, in the abstract itself.** No market impact; domestic investor only; the
   rulebook is 63% high-confidence by row; continuous-session fill determination is
   unvalidated, which is why an ignorance bound is reported rather than a fill rate.

**Word budget note.** If the abstract must be short, move (2) is the one to compress —
but it may not be deleted. A reviewer who knows LEAN has `DelayedSettlementModel` and sees
no acknowledgement of it will discard the paper.

---

## 3. Section list

### §1 Introduction

Three paragraphs. (a) The backtest-to-live gap as an assumption problem, not a statistics
problem, with the cost literature cited. (b) Why the missing part is jurisdictional: the
rules that refuse an order are national and dated, and general engines are portable by
design, so they omit them. (c) Contributions, stated as the three narrowed sentences and
nothing wider, with a forward reference to the threats-to-validity section so the scope
cuts arrive in the reader's first impression, not the last.

### §2 Related work

Drawn wholesale from `literature-review.md` §§1–3. Must contain the two comparison tables
with per-cell citations, and must state prior art before novelty in every subsection.
Subsections: (2.1) backtest reliability and cost-assumption sensitivity; (2.2) exchange-rule
enforcement in general-purpose engines; (2.3) emerging-market rule engines, with RQAlpha
and EvoMarket named as the nearest neighbours and vnpy's hard-coded `pre_close * 1.1` as the
cautionary counter-example; (2.4) fill determination as a user-replaceable component, and
the 2011 Forex Strategy Builder ambiguity precedent; (2.5) Vietnam specifically — the
research that describes the constraints and drops them, and the three broker paper-trading
products that enforce the current edition.

### §3 The Vietnamese rule surface

The domain section a non-Vietnamese reviewer needs, and the evidence that these rules are
not decorative. Covers: session structure and the seven order types where the type *is* the
time-in-force; the price-dependent tick grid and its dated revisions; the ±7/10/15% bands
with widened regimes and both degenerate branches; the 10→100 round-lot change on
2021-01-04; T+2 counted in VSDC settlement business days with the 13:00 allocation deadline;
100% pre-funding and Circular 68/2024's non-pre-funding carve-out for foreign institutions
from 2024-11-02; foreign-ownership room and its pre-/post-KRX rejection triggers; and the
derivatives regime — segregated deposit, MR = IM + VM, VM loss-only, utilisation tiers at
80/90/100%, and **no published maintenance ratio**. Each with its dated citation and its
confidence level from the rulebook. Close with the KRX cutover of 2025-05-05 presented as a
dated rule edition rather than a migration.

### §4 Design

The object model and the API surface, in the shape of a broker rather than a backtester:
`submit` / `cancel` / `poll`, `holdings`, `cash`, `positions`, `margin`, `charges`,
`transfer`. The four design decisions a reviewer will interrogate: (a) the rulebook resolves
per event instant, `rulebook.at(ts)`, not once at config load, because a run spans regime
changes; (b) exchange rules and broker terms are separate configuration objects, because one
is gazetted and dated and the other is commercial and firm-specific; (c) the encumbrance
ledger, because resting orders make every affordability test a net-of-live-orders test; (d)
holdings and proceeds are tranche lists keyed by settlement instant, because T+2 leaves two
tranches open at once. Include the order state machine and the explicit statement that
INDETERMINATE is an **event**, not an order state — the order stays resting and is
re-evaluated.

### §5 Indeterminacy as an outcome

The paper's most defensible novelty, and it needs its own section rather than a subsection
of §4. What the data contract requires per field, what each missing field makes
undecidable, and the mapping from missing evidence to the named rule that could not be
evaluated (`BAND_LIMIT` without a reference or band; `SESSION_SEMANTICS` without a phase;
`FOREIGN_ROOM` without room; margin marks without a settlement price). State plainly the
distinction the literature review establishes: prior tooling treats ambiguity as
path-ordering between the trader's own already-triggered orders inside a bar and reports it
as an aggregate bar count, whereas this is per-order ambiguity of fill **existence**
attributed to an exchange rule. Report the indeterminate rate per data resolution and per
rule.

### §6 Implementation and reproducibility

Short. The module layout, the test count, and `reproduce_measurements.py` as the single
entry point that regenerates every number the paper states. Name the corpus explicitly
(daily bars 2000-07-28 → 2022-12-30, 2,511,874 rows, 1,725 tickers; tick 2020-12-02 →
2022-12-30) and state that band-dependent results are inherently 2021–2022 because
`quote_ceil` begins 2021-02-05. Include the dataset-defect audit as evidence that the
corpus was characterised rather than assumed clean.

### §7 Results

See §4 of this outline for the placement map. Every result carries its fill policy, its
data resolution and the no-market-impact assumption in the same sentence.

### §8 Threats to validity

Mandatory, and written before the results are polished, not after. See §5 of this outline.

### §9 Related but out of scope / future work

The Calibrator gold-standard validation against the firm's own 2021–2022 order and reject
logs; the post-KRX rulebook population; the corporate-action engine; foreign-room
enforcement with both date-switched branches; portfolio margining, which cannot be
reproduced without Phụ lục 02; event-driven callbacks; and queue-position matching against a
reconstructed book, which the data cannot support because 81% of best-quote changes carry no
trade and no order ids exist.

### §10 Conclusion

Restate the three narrowed contributions and nothing wider. Do not reintroduce a broad
claim in the conclusion — that is where over-claiming usually re-enters.

---

## 4. Where each measured result lands

| Result | Value | Section | What it is evidence *of*, and what it is not |
|---|---|---|---|
| Momentum entries the exchange would not fill, **next session** | **5.84%** (11,543 / 197,521) | §7 headline | Evidence that the band lock binds on tradeable signals. **Not** a strategy result. The `lag=1` variant is the only one quotable as tradeable. |
| Same figure on the **signal** session | 12.90% (25,464 / 197,337) | §7, immediately beside the above | Reported **only** as the look-ahead contrast. The gap between the two is itself the finding: a close-to-close signal cannot be acted on inside the session that produced it. |
| Front-month VN30F longs margin-called, 10-session hold | **12.60%** (48 / 381) | §7 derivatives subsection | Evidence the utilisation test fires at realistic frequency. Carries a **modelling assumption**: no margin data exists in either corpus, so the rate depends on the assumed IM ratio and buffer. Must be restated with the corrected dated series (10 → 13 → 17%), never with the retired 17.5% constant. |
| Tick-grid conformity, library rule vs a flat 0.1 grid | **99.9988%** vs **83.86%** | §3 (rule surface) and §7 | The single cleanest demonstration that a price-dependent grid is not cosmetic: the naive flat grid misclassifies one price in six. |
| Bar-vs-tick lock agreement | **97.56%** on 173,168 ticker-days | §5 (indeterminacy) and §7 | Evidence for the resolution-dependence claim: a bar-inferred lock and a tick-observed lock disagree ~1 day in 41. Report the `locked_at_close` arm as the comparison; the `locked_all_session` arm is contrast only. |
| Off-grid UPCOM closes | 15,504 across 30 tickers | §6 (corpus audit) | Refutes our own earlier claim that a non-HSX tick audit would be vacuous. Report as a corpus finding, and note the follow-up: the exceptions are venue-transfer artefacts, not a tick exception. |
| Foreign room below one 100-share lot | **34,653** observations; FPT 2022-12-30 down to 11 shares | §8 threats (T1) | Evidence that the scope cut is a **choice**, not a discovery that the constraint never binds. Not a modelling result. |
| Close-as-settlement substitution error | 46 expiries 2022-08-18 → 2026-08-20; mean signed **+0.024%**, mean absolute **0.042%**, σ **0.071%**, worst **0.333%** (VN30F2603); 37/46 within 0.05%, 45/46 within 0.20% | §8 threats (T2) | Evidence the fallback is ~4 bp in the typical case. Must be reported with the sample size and with the observation that VN30F2206 — the contract earlier documents leaned on — sits near the **worst** of the distribution, not the middle. |
| Ten-check dataset audit incidences | e.g. inverted bands 1,272 rows on 3 days (0.155%); OHLC-invariant violations 327 + 99 of 3,877,981; HSX tick-grid 13 of 1,101,201 | §6 | Evidence the corpus was characterised, not assumed clean. Two defect classes (inverted bands, OHLC invariants) are independent, so a row can fail one and pass the other. |
| Test count | 630 collected | §6 | Reproducibility, not correctness. Do not present a test count as validation of the rules. |

**Two figures the paper must generate that do not yet exist**, both from spec §11 Tier 3:

- the **indeterminate rate** per data resolution and per named rule (§5's central number);
- the **cross-policy divergence** for one strategy under the shipped fill policies, reported
  jointly with the indeterminate rate (§7).

Without these two, §5 and the third contribution are assertions. They are the gating
deliverable for submission.

---

## 5. Threats to validity — mandatory content

This section is not a disclaimer list. Each entry states the simplification, what it buys,
what fidelity it gives up, the measured cost where one exists, and what would trigger
revisiting it. Four entries are required verbatim in substance.

### 5.1 No market impact, ever

The simulated order fills against observed history and never moves the market or induces a
counterparty reaction. This is the standing limitation of any replay design and it is not
scheduled to be fixed. State it in the abstract, in §4, and beside every result. Two
consequences to spell out rather than leave implied: (a) any participation cap is a cap on
*our* share of observed volume, not a model of what our own order would have done to that
volume; (b) at daily-bar resolution the square-root-law impact literature cannot be
estimated at all, which is an argument *for* reporting indeterminacy rather than against it
— but a reviewer will ask why a square-root impact model is not shipped as a middle policy,
and the paper needs that answer explicitly.

### 5.2 Domestic-investor scope cut — foreign-ownership room is not enforced

The account is never classified as foreign, so every foreign-room check short-circuits and
all trades are valid on that axis. What it buys: an entire date-switched control flow
disappears — pre-KRX *fill-to-room-then-cancel-at-zero* versus post-KRX
*reject-when-room < order quantity* — along with the room time series in the hot path. What
it gives up: a foreign account's orders would in reality be partially filled or rejected on
room; we admit them in full.

**The cost is measured and the constraint is real: 34,653 room observations sit below a
single 100-share lot, and FPT on 2022-12-30 runs down to 11 shares.** Ignoring it is a
choice, not a finding that it never binds. Two aggravating facts belong here: a foreign
round-trip cannot recycle its own room intraday, because the sell side restores room only
at settlement — the main reason a foreign strategy can be room-blocked while flat on net;
and post-KRX the displayed depth on a near-full name is explicitly capped at remaining room,
so a book-based fill model that reads displayed depth as true depth is wrong on exactly the
names where room binds.

**One unresolved data question that must be disclosed, not hidden:** the repo's own
documents disagree on whether `quote_foreignroom` is the cap or the remaining room. The
enforcement work cannot start until that is settled, and any statistic pooled across
2025-05-05 would mix two different quantities if it is remaining room.

Revisit trigger: any result claiming to represent a foreign account, or the post-KRX
rulebook landing, at which point both branches must exist anyway.

### 5.3 Close-as-settlement fallback on expiry

Where the data source supplies a settlement price, the simulator uses it and there is no
approximation to declare. Where it does not, the simulator falls back to the expiring
contract's close on expiry day, and **records that substitution on the result** — a number
computed on the close-proxy says so.

**Measured across all 46 expiries from 2022-08-18 to 2026-08-20: mean signed error
+0.024%, mean absolute error 0.042%, standard deviation 0.071%, worst case 0.333%
(VN30F2603, 2026-03-19); 37/46 within 0.05%, 42/46 within 0.10%, 45/46 within 0.20%.**
About four basis points in the typical case.

Three things this entry must also say. The published settlement is an average over the last
30 minutes (14:15–14:45, including the ATC), not the close. The averaged subject changed
mid-corpus on an exact boundary — the last futures-tracked row is 2022-08-16 and the first
VN30INDEX row is 2022-08-17 — so the settlement basis is itself dated and must be resolved at
the expiry date rather than by one formula for all history. And earlier drafts of our own
documents quoted a ~0.4% figure from a single contract, VN30F2206, which sits near the
**worst** of the distribution; that is the argument against citing an n=1 measurement, made
against our own prior claim, and it belongs in the paper.

Revisit trigger: any result whose P&L is materially sensitive to expiry-day pricing.

### 5.4 Continuous-session fill determination is not empirically validated

Fill determination inside the continuous session is not validated against ground truth, and
no validation is claimed. This is why the indeterminate rate is reported **as a bound on
ignorance rather than as a fill rate**. Three supporting facts that make the limitation
concrete rather than rhetorical: the corpus carries a three-level price ladder but bid/ask
**sizes** are not populated in this release, so depth-of-book liquidity cannot be measured —
only prices; 81% of best-quote changes carry no trade, so order flow cannot be recovered and
queue position cannot be inferred; and timestamps are vendor capture times with a median of
13 captures per ticker-day, so only the top liquidity quintile supports intraday work at
all. Auction fills are the exception and should be stated as such — they fill at the
published open/close, which is cheap and correct.

Planned resolution, deferred and named as deferred: the firm's own 2021–2022 order and
reject logs are the retrospective gold standard and require no live trading; and at least
one non-vendor data source should be obtained for a few hundred ticker-days, because every
series currently arrives through the same pipeline we maintain.

### 5.5 Further threats that must not be omitted

- **Rulebook confidence is not uniform.** 63% of 400 primary rule rows are
  high-confidence. Every tick, lot and band value from 2022-03-31 onward is corroborated
  rather than gazetted-verified, because Phụ lục III of the VNX Quy chế was never obtained;
  22.5% of the coverage window (2020-01-01 → 2021-07-04) has no primary text at any venue;
  UPCoM before 2022-11-16 is effectively uncovered. State the confidence distribution, do
  not average it away.
- **Derivatives margin is weak on values, strong on shape.** The central structural finding
  — no published maintenance ratio, utilisation test instead — is primary-sourced. The
  initial-margin series (10/13/17%) is press-sourced with **no `quyết định` number in
  existence**, and the ratio is published per contract, so the correct data structure is
  `(contract_code, effective_date) → ratio`, not a scalar. Portfolio margining / spread
  credits are **unverifiable**: the formula is in Phụ lục 02, which VSDC does not publish.
- **Landing the session does not retro-validate the published numbers.** Three of the
  headline figures come from SQL that parallels the rules rather than calling them; the
  parallel SQL remains their source until it is replaced by real calls. Say so.
- **No corporate-action engine.** A run spanning an ex-date is wrong for that instrument
  until the adjustment formulas land.
- **Absence claims about other tools are module-scoped.** No repository-wide grep was
  possible during the survey; every "does not have X" in §2 names the modules read.
- **Three external documents are unread and are cited as unverified**: the ResearchGate
  March 2026 HOSE/HNX simulation-platform paper, the Claeys 2026 SSRN working paper, and
  EvoMarket's source. Two of them bear directly on our novelty claims.

---

## 6. Figures and tables

| # | Artefact | Section |
|---|---|---|
| T1 | Capability × tool comparison, general engines (from `literature-review.md` §2.1) | §2 |
| T2 | Capability × tool comparison, specialist systems (§2.2) | §2 |
| T3 | Dated rule editions in force across the simulated window, with effective dates and confidence | §3 |
| F1 | The order state machine, with INDETERMINATE shown as an event on the resting arc, not a leaf | §4 |
| F2 | Indeterminate rate by data resolution and by binding rule | §5 |
| F3 | Cross-policy divergence for one strategy, plotted against the indeterminate rate | §7 |
| T4 | Measured results table, each row carrying its fill policy, resolution and assumption set | §7 |
| T5 | Tradeoff register: simplification, what it buys, fidelity given up, measured cost, revisit trigger | §8 |

## 7. Venue and length notes

- RIVF'26's 31 Aug deadline is explicitly **non-binding** for this work; the working
  horizon is Sep 2026 – Feb 2027. Do not compress §5 or §8 to hit a date.
- If the venue is a systems track, promote §4 and §6 and compress §2 to one page plus T1.
- If the venue is a finance track, promote §1 and §7, and lead the abstract with the
  Menkveld non-standard-errors framing.
- Either way, §8 stays at full length. It is the section that makes the fidelity claim
  credible rather than asserted.
