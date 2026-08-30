# Paper outline

**Status:** outline only. Another session writes the prose. Nothing below is drafted text.

**Companion documents.** `docs/reference/literature-review.md` holds the positioning,
the cited comparison tables and the **narrowed claim sentences that must be used
verbatim**. `docs/reference/citable/vn-exchange-rulebook-2020-2026.md` holds the 400 dated rules
with citations and per-row confidence. `docs/superpowers/specs/2026-08-25-exchange-simulator-design.md`
holds the design, the tradeoff register (§15.1) and the stated assumptions (§16).

**Non-negotiable constraint on the writer.** Three claims were adversarially refuted and
survive only in narrowed form. Use `literature-review.md` §4.1, §4.2 and §4.3 **verbatim**.
The guardrail list in §4.3 is binding: the words "pluggable", "swappable",
"hard/soft/probabilistic family", "the spread is the reported result" and "no prior art for
an indeterminate outcome" must not appear.

**Two further prohibitions, added by the prior-art pass of 2026-08-26.** Neither is
negotiable and both have a named refutation:

- **Never write any form of "first to combine call auctions, price limits and a settlement
  cycle."** EvoMarket (arXiv:2604.18046, April 2026) does exactly that for China A-shares.
- **Never write "first matching-engine simulation of a Vietnamese exchange" unhedged.**
  Lê Đức Hùng's 2013 VNU-UET thesis is an HNX matching-engine test double.

**And the lead claim changed.** `literature-review.md` §4.0 is now the sentence the title,
the abstract's gap move and the conclusion are all built on: **effective-dated rule
editions** — backtesting 2024 and 2026 under the rules that actually applied to each. §4.1
was re-narrowed accordingly; its superseded form is recorded struck-through in that
document and must not be re-derived. Vo & Doan (2023), a difference-in-differences study of
HOSE's real 12 Sep 2016 tick-size change, is the empirical warrant and should appear
wherever the lead claim does.

---

## 1. Title options

Ranked. Each leads with what survived the attacks, not with what was refuted. **The ranking
changed after the prior-art pass: the title must now lead with dated rule editions, because
that is the only claim with no near neighbour.**

1. **Backtesting Under the Rules That Applied: Effective-Dated Exchange Rule Editions in a
   Vietnamese Exchange Simulator** — leads with the strongest claim and states it as a
   capability rather than a priority claim. Preferred.
2. **Effective-Dated Exchange Rules and Indeterminate Fills: A Vietnamese Exchange
   Simulator with a Broker-Facing API** — the previous first choice; still accurate, leads
   with both surviving contributions.
3. **Plutus: A Dated Order-Admission Rulebook for HOSE, HNX, UPCoM and HNXDS** — most
   concrete, least ambitious; good if the venue prefers systems papers.
4. **What the Data Cannot Decide: Per-Order Indeterminacy in a Rule-Dated Simulator of the
   Vietnamese Exchange** — leads with indeterminacy. Demoted because Claeys (2026) is now
   verified prior art on intrabar ambiguity, so this title invites the comparison first.
5. **From Trading Calendar to Settlement Calendar: Modelling Vietnamese T+2, Price Bands
   and Segregated Derivatives Margin** — leads with the one mechanism no other engine wires
   correctly.
6. **An Exchange, Not a Backtester: Simulating Vietnamese Market Rules Behind a Broker
   API** — best for a practitioner audience; weakest for a reviewer looking for novelty.

Avoid: anything containing "high-fidelity" unqualified (EvoMarket's own title is *"A
High-Fidelity and Scalable Financial Market Simulator"*, April 2026 — using the phrase
invites a direct comparison and looks derivative), "data-source agnostic" (refuted),
"pluggable fill model" (refuted), and any "first simulator to…" construction naming
auctions, bands or settlement (refuted by EvoMarket).

## 2. Abstract sketch

Six moves, roughly one sentence each.

1. **Problem.** The gap between a backtest and live trading is dominated by execution
   assumptions, and those assumptions are national **and dated** — a tick grid, a band, a
   lot, an auction eligibility rule, a settlement cycle, a margin regime, each of which
   changes on a gazetted date. Anchor to Patton & Weller's 2.2–8.5% momentum cost range and
   Menkveld et al.'s finding that non-standard errors are "on par with standard errors",
   then to Vo & Doan (2023), whose difference-in-differences study of HOSE's real 12 Sep
   2016 tick-size change shows that **a dated edition of one rule moves measured trading
   costs on this very market.**
2. **What exists.** Credit generously and specifically, and name the two nearest
   neighbours rather than letting a reviewer find them: LEAN models T+N and a Reg NMS
   price-dependent tick grid; RQAlpha enforces China's bands, call auction and T+1 with
   segregated stock/future accounts and date-resolved margin ratios; **EvoMarket (April
   2026) implements market calendars, opening call auctions, price limits and T+1
   settlement for China A-shares**; MarS ships an MIT-licensed matching engine that omits
   the institutional rules by design; NautilusTrader, LEAN, Zipline, RQAlpha and
   hftbacktest all let the user replace fill determination; Forex Strategy Builder reported
   an ambiguity count in 2011 and **Claeys (2026) reports an 18.47% intrabar-ambiguity rate
   on 2.06 million E-mini bars**.
3. **The gap.** **Rules are carried as constants, not as editions.** Dated editions exist
   for calendars and parameters, never for order admission — including in EvoMarket, whose
   rules are fixed constants with no versioning — so no simulator can answer "what would
   this have done under the rules in force in 2024?" across a real regime change. Secondly,
   no engine distinguishes "this order did not fill" from "this data cannot establish
   whether this order filled" at per-order granularity through the order status the caller
   receives.
4. **What we built.** A simulated Vietnamese exchange behind a broker-shaped API, with a
   400-row **dated** rulebook resolved per simulated instant — spanning the KRX cutover of
   2025-05-05, three equity venues with different bands, a price-dependent tick grid and
   first-day and post-suspension band exceptions — a VSDC settlement-business-day calendar
   wired to unsettled cash and unsettled shares, a segregated derivatives deposit run as **two
   dated margin editions** — `MR = IM + VM` pre-KRX and the QĐ 26 scenario-margin stack
   `MR = Max(ΣPgm, 0)` post-KRX — and INDETERMINATE as a per-order status attributed to the
   rule that could not be evaluated.
5. **Results, one line.** The headline numbers from §7 — the blocked-entry rate at the
   tradeable lag, the tick-grid conformity contrast, the bar-vs-tick lock divergence, the
   margin-call incidence — each stated with the assumption it rests on.
6. **Limits, in the abstract itself.** No market impact; domestic investor only; the
   rulebook is 63% high-confidence by row; continuous-session fill determination is
   unvalidated, which is why an ignorance bound is reported rather than a fill rate.

**Word budget note.** If the abstract must be short, move (2) is the one to compress —
but it may not be deleted, and **EvoMarket may not be the thing cut from it**. A reviewer
who knows LEAN has `DelayedSettlementModel`, or who has seen EvoMarket on arXiv, and finds
no acknowledgement in the abstract will discard the paper. The minimum surviving form of
move (2) is one clause naming LEAN/RQAlpha, one naming EvoMarket, and one naming Claeys.

---

## 3. Section list

### §1 Introduction

Three paragraphs. (a) The backtest-to-live gap as an assumption problem, not a statistics
problem, with the cost literature cited. (b) Why the missing part is jurisdictional: the
rules that refuse an order are national and dated, and general engines are portable by
design, so they omit them — **and, being dated, a portable engine that did encode them
would encode exactly one edition**. (c) Contributions, **led by dated rule editions**, then
the other two narrowed sentences and nothing wider, with a forward reference to the
threats-to-validity section so the scope cuts arrive in the reader's first impression, not
the last. The nearest neighbours (EvoMarket, Claeys) are named in this paragraph, not
deferred to §2 — a reviewer who meets them first in related work has already formed a
worse impression.

### §2 Related work

Drawn wholesale from `literature-review.md` §§1–3. Must contain **all three** comparison
tables with per-cell citations, and must state prior art before novelty in every
subsection. Subsections:

- **(2.1) Backtest reliability and cost-assumption sensitivity.** Unchanged.
- **(2.2) Exchange-rule enforcement in general-purpose engines.** Table T1.
- **(2.3) Emerging-market rule engines and LOB simulators.** Table T2. Open with the Jain
  et al. LOB-simulation survey for framing. **EvoMarket and RQAlpha are the nearest
  neighbours and must be described before any claim of ours is stated**; MarS is the
  MIT-licensed matching engine that omits the institutional rules by design; vnpy's
  hard-coded `pre_close * 1.1` is the cautionary counter-example; ABIDES has no
  price-limit and no call-auction mechanism, only the maintainer comment *"This can
  probably go away once we code the opening cross auction"*. Close with the fact that **no
  ABM has been localised to any emerging market's real rulebook** (India, Brazil,
  Indonesia, Thailand, Korea, Taiwan all empty), which is what makes EvoMarket the
  exception worth naming.
- **(2.4) Fill determination as a user-replaceable component**, the 2011 Forex Strategy
  Builder ambiguity precedent, and **Claeys (2026)** — cited with his numbers, and with the
  concession in `literature-review.md` §4.3 made *before* our own framing is introduced.
- **(2.5) Vietnam specifically.** The research that describes the constraints and drops
  them (Huang/Liu/Shu; Nguyen et al.); **Pham, Luu & Tran (2021)**, the only indexed paper
  using the phrase "Vietnamese stock market simulator", disposed of with their own sentence
  *"We use daily return as input data for training process"*; **Lê Đức Hùng (2013)**, the
  HNX matching-engine test double that predates derivatives, T+2, bands and auctions;
  **Vo & Doan (2023)** as the empirical warrant, given prominence rather than a passing
  cite; the **JICCE 2025 dashboard** as the state of practice; and Table T2b, the
  Vietnamese product landscape — Vietstock Đấu trường (the only one publishing a tick grid,
  bands and a participation cap), vnstockgame, the **defunct** SSI iWin, VPS SmartEasy, and
  the live-money-only broker APIs. Our own arXiv:2505.14050 is cited here as the
  non-overlapping reproducibility self-citation.
- **(2.6) Priority risks and how we position against them.** New, and mandatory — see the
  subsection specified immediately below.

#### §2.6 Priority risks and how we position against them

**Purpose.** Two published works sit closest to this paper, and a reviewer will find both.
This subsection names them, concedes what they establish, and states the residual
difference — before §3 begins. It is written as scope comparison, never as critique.
Roughly half a page.

**Risk 1 — EvoMarket (Zhong, Yang, Liu, Tang & Yang, arXiv:2604.18046, 20 April 2026).**
It is our structural thesis one market over and four months ahead: a discrete-event
multi-agent simulator with *"explicit institutional mechanisms (market calendars, opening
call auctions, price limits, and T+1 settlement)"*, validated on China A-share order-flow
and LOB data. **Concede the combination outright.** The residual differences, all
verifiable and all about the shape of the rulebook rather than about priority:

| What EvoMarket has | What differs here |
|---|---|
| One symmetric ±10% band, uniform ¥0.01 tick, T+1 — the rules China actually has | Three equity venues with different bands, a **price-dependent** tick grid, first-day and post-suspension band exceptions, plus a **separate derivatives venue with a dated margin regime (IM + VM pre-KRX, a scenario-margin stack after 2025-05-05)** |
| Rules as fixed constants | Rules as **effective-dated editions**, spanning a real regime change (KRX, 2025-05-05) |
| No code released | Open source, with `reproduce_measurements.py` regenerating every number |
| Equities only | Equities **and** derivatives, with a segregated margin account |
| An experiment harness for mechanism studies | A **broker-API endpoint a strategy connects to** |

**Risk 2 — Claeys (2026), SSRN 6240638.** 2,064,460 one-minute E-mini NASDAQ-100 bars,
2020–2025; 18.47% ambiguous for a 10-point stop / 10-point target; best-case/worst-case
spread of 3,695 NQ points ($73,900) per 1,000 trades; five platforms compared, none
provably correct without tick data. **Concede the intrabar-ambiguity framing explicitly.**
Then state the difference in one sentence: we enforce the exchange's rules first, so the
spread is bounded by **admissibility** rather than only by OHLC geometry — an order the
tick grid, lot, band or session would have refused contributes no spread because it never
rested — and his scope is one instrument and one ambiguity where ours is one measurement
among ten. Disclose in the same breath that his full text is unreachable and that we
therefore never name the five platforms.

**Risk 3, social rather than intellectual — the JICCE 2025 platform.** Lee et al.
(UEL/VNU-HCM), *J. Inf. Commun. Converg. Eng.* 23(4):327–335, 31 Dec 2025, is a web
dashboard with ARIMA/RF/LSTM forecasting and no microstructure of any kind. It is **not** a
competitor, and it is a legitimate citation for dashboard-and-backtest-tab tooling being
the state of practice in Vietnam. **This group published at RIVF 2025 and we are submitting
to RIVF'26; assume they are in the reviewer pool.** Describe scope, never quality. Do not
repeat the earlier misreading that their platform uses EUR/USD data — that sentence is in
their literature review, about someone else's work.

### §3 The Vietnamese rule surface

The domain section a non-Vietnamese reviewer needs, and the evidence that these rules are
not decorative. Covers: session structure and the seven order types where the type *is* the
time-in-force; the price-dependent tick grid and its dated revisions; the ±7/10/15% bands
with widened regimes and both degenerate branches; the 10→100 round-lot change on
2021-01-04; T+2 counted in VSDC settlement business days with the 13:00 allocation deadline;
100% pre-funding and Circular 68/2024's non-pre-funding carve-out for foreign institutions
from 2024-11-02; foreign-ownership room and its pre-/post-KRX rejection triggers; and the
derivatives regime as **two dated editions** in a segregated deposit: pre-KRX (≤2025-05-04)
`MR = IM + VM`, VM loss-only, and **no published maintenance ratio** (the 80/90/100
*margin*-utilisation ladder once cited to "Article 13" is **unverified**, `low` — not a
gazetted rule); post-KRX (2025-05-05→) the scenario-margin stack `MR = Max(ΣPgm, 0)` the code
implements (`scenario_margin.py`, QĐ 26 Phụ lục 2), where the only gazetted 80/90/100 is the
**position-limit** monitor (QĐ 26 Điều 29), not a margin trigger. Each with its dated citation
and its confidence level from the rulebook. Close with the KRX cutover of 2025-05-05 presented as a
dated rule edition rather than a migration — **and with Vo & Doan (2023) as the evidence
that a dated edition is not bookkeeping**: their difference-in-differences study of the
12 Sep 2016 HOSE tick-size change finds trading costs fell, and fell non-uniformly across
price bands. This is the section where the lead claim earns its warrant, so the citation
belongs here as well as in §2.

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

Short. The module layout, the per-suite test counts (market 1646 / scenarios 38 / strategies
13), and `reproduce_measurements.py`. **Data posture, stated honestly and up front: we do not
claim a corpus.** The library is **bring-your-own-data** — it characterises whatever feed you
point it at — and reproducibility is **two-tier**: (a) a **reproducible core** shipped in-repo
— the Jx + Sx suites and their fixtures, so `clone → pip install → pytest` reproduces them for
any third party; and (b) **provenance-documented demonstrations** — the headline measurement
numbers, some computed against production data we do not redistribute, each tagged with its
provenance. `reproduce_measurements.py` regenerates the corpus-available ones; a separate,
clearly-labelled path regenerates the production-sourced ones — the honest claim is that
two-tier statement, not "regenerates *every* number". **Our data ceiling, named:** production
tick market data plus a **reconstructed 3-level book (with sizes)** — **not** the exchange's
full order book (all levels, order ids, the true queue, deletions), which we never imply we
have. Band-dependent results are inherently 2021–2022 because `quote_ceil` begins 2021-02-05.
Include the ten-check dataset-defect audit as a **demonstration of a capability** — the library
characterises whatever feed you point it at — run on the shipped fixtures; at most a neutral
"computed on N instrument-days of sample data", never a boast about corpus scale.

### §7 Results

See §4 of this outline for the placement map. Every result carries its fill policy, its
data resolution and the no-market-impact assumption in the same sentence.

### §8 Threats to validity

Mandatory, and written before the results are polished, not after. See §5 of this outline.

### §9 Related but out of scope / future work

The Calibrator gold-standard validation against the firm's own 2021–2022 order and reject
logs; the post-KRX rulebook population; the corporate-action engine; foreign-room
enforcement with both date-switched branches; **pre-KRX (QĐ 96-era)** portfolio margining,
which cannot be reproduced without the QĐ 96-era appendix VSDC does not publish (the post-KRX
offsets are now primary-sourced from QĐ 26 Phụ lục 2 and modelled); event-driven callbacks;
and **recovering our own queue *rank*** against a reconstructed book — distinct from the
**declared** queue axis reported in §7/F3, which is built — which the data cannot support
because 81% of best-quote changes carry no trade and no order ids exist.

### §10 Conclusion

Restate the three narrowed contributions, **leading with dated rule editions**, and nothing
wider. Do not reintroduce a broad claim in the conclusion — that is where over-claiming
usually re-enters, and the two phrases most likely to re-enter here are "first to combine
call auctions, price limits and settlement" and "first Vietnamese matching engine". Both
are prohibited; see the header of this outline.

---

## 4. Where each measured result lands

| Result | Value | Section | What it is evidence *of*, and what it is not |
|---|---|---|---|
| Momentum entries the exchange would not fill, **next session** | **5.84%** (11,543 / 197,521) | §7 headline | Evidence that the band lock binds on tradeable signals. **Not** a strategy result. The `lag=1` variant is the only one quotable as tradeable. |
| Same figure on the **signal** session | 12.90% (25,464 / 197,337) | §7, immediately beside the above | Reported **only** as the look-ahead contrast. The gap between the two is itself the finding: a close-to-close signal cannot be acted on inside the session that produced it. |
| Front-month VN30F longs margin-called, 10-session hold | **12.60%** (48 / 381) | §7 derivatives subsection | Evidence the utilisation test fires at realistic frequency. Carries a **modelling assumption**: no margin data exists in either corpus, so the rate depends on the assumed IM ratio and buffer. Must be restated with the corrected dated series (10 → 13 → 17%), never with the retired 17.5% constant. |
| Tick-grid conformity, library rule vs a flat 0.1 grid | **99.9988%** vs **83.86%** | §3 (rule surface) and §7 | The single cleanest demonstration that a price-dependent grid is not cosmetic: the naive flat grid misclassifies one price in six. |
| Bar-vs-tick lock agreement | **97.56%** on 173,168 ticker-days | §5 (indeterminacy) and §7 | Evidence for the resolution-dependence claim: a bar-inferred lock and a tick-observed lock disagree ~1 day in 41. Report the `locked_at_close` arm as the comparison; the `locked_all_session` arm is contrast only. |
| Foreign room below one 100-share lot | **34,653** observations; FPT 2022-12-30 down to 11 shares | §8 threats (T1) | Evidence that the scope cut is a **choice**, not a discovery that the constraint never binds. Not a modelling result. |
| Ten-check dataset audit incidences | e.g. inverted bands 1,272 rows on 3 days (0.155%); OHLC-invariant violations 327 + 99 of 3,877,981; HSX tick-grid 13 of 1,101,201 | §6 | Evidence the corpus was characterised, not assumed clean. Two defect classes (inverted bands, OHLC invariants) are independent, so a row can fail one and pass the other. |
| Test count | market 1646 / scenarios 38 / strategies 13 | §6 | Reproducibility, not correctness. Do not present a test count as validation of the rules. |

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

### 5.3 Close-as-settlement fallback on expiry — a graceful-degradation feature, not a cost our results invoke

Where the data source supplies a settlement price, the simulator uses it — and **our own
results always supply the real settlement price, so they never invoke the fallback**. The
close-as-settlement substitution is retained as a **graceful-degradation feature** for users
who lack a settlement series: where none is supplied, the simulator falls back to the
expiring contract's close on expiry day and **flags that substitution on the result** — a
number computed on the close-proxy says so, rather than passing silently as if it were
gazetted. Because our results never lean on it, **there is no substitution-error measurement
to report here**; the feature's contract is that it announces its own substitution, not that
it is accurate.

One dated subtlety the feature must still respect when it does fire: the published settlement
is an average over the last 30 minutes (14:15–14:45, including the ATC), not the close, and
the averaged subject changed mid-corpus on an exact boundary — the last futures-tracked row
is 2022-08-16 and the first VN30INDEX row is 2022-08-17 — so the settlement basis is itself
**dated** and is resolved at the expiry date rather than by one formula for all history.

Revisit trigger: any result whose P&L is materially sensitive to expiry-day pricing and that
cannot supply a real settlement series.

### 5.4 Continuous-session fill determination is not empirically validated

Fill determination inside the continuous session is not validated against ground truth, and
no validation is claimed. This is why the indeterminate rate is reported **as a bound on
ignorance rather than as a fill rate**. Three supporting facts that make the limitation
concrete rather than rhetorical: **sizes are available where the sized feed is wired** — the sized dev extract
(`dataset/hermes-dev-extract`, 1,390,914 size rows; production carries far more) populates
the three-level book, and the book-walk maker fill (S8/S9) reads real sizes; it is the
size-less **default** adapters that serve prices only, so on those feeds depth-of-book
liquidity cannot be measured. What no feed can recover is our **own queue rank**: 81% of
best-quote changes carry no trade and there are no order ids, so order flow cannot be
reconstructed; and timestamps are vendor capture times with a median of 13 captures per
ticker-day, so only the top liquidity quintile supports intraday work at all. Auction fills are the exception and should be stated as such — they fill at the
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
- **Derivatives margin is weak on values, strong on shape, and now split by regime.** The
  central structural finding — **no published maintenance ratio** — is primary-sourced.
  Pre-KRX (≤2025-05-04) `MR = IM + VM`; the 80/90/100 *margin*-utilisation ladder once cited
  to "Article 13" is now **unverified** (`low`) — the citation chain collapsed at QĐ 26,
  whose Điều 13 carries no percentage — so it is stated as an assumption, not a sourced rule.
  Post-KRX (2025-05-05→) the scenario-margin stack `MR = Max(ΣPgm, 0)` is **primary-sourced**
  from QĐ 26 and its Phụ lục 2 (obtained 2026-08-26) and implemented in `scenario_margin.py`.
  The initial-margin series (10/13/17%) is press-sourced with **no `quyết định` number in
  existence**, and the ratio is published per contract, so the correct data structure is
  `(contract_code, effective_date) → ratio`, not a scalar. **Post-KRX** portfolio margining /
  spread credits are now **primary-sourced** from Phụ lục 2 (the cross-underlying offsetting
  amount `OA` within a Kendall-tau ≥ 0.9 underlying-asset group, and the calendar basis-margin
  add-on `Sm`); only **pre-KRX (QĐ 96-era)** portfolio margining remains unverifiable — the
  QĐ 96-era "Phụ lục 02" on VSDC's page is a different appendix of a different instrument and
  must not be back-dated from the one now in hand.
- **Landing the session does not retro-validate the published numbers.** Three of the
  headline figures come from SQL that parallels the rules rather than calling them; the
  parallel SQL remains their source until it is replaced by real calls. Say so.
- **No corporate-action engine.** A run spanning an ex-date is wrong for that instrument
  until the adjustment formulas land.
- **Absence claims about other tools are module-scoped.** No repository-wide grep was
  possible during the engine survey; every "does not have X" in §2 names the modules read.
  Where an absence rests on a GitHub *repository-search* query — as with "no open-source
  Vietnamese exchange simulator exists" — say so, and state the weaker thing it proves: no
  repository is named or described as such a tool, not that no such code exists.
- **The novelty claim is scoped by a preprint we cannot inspect.** EvoMarket **releases no
  code**, so every statement we make about it is read from its paper. If its
  implementation turns out to carry dated rule editions, the lead claim narrows further.
  Disclose this rather than let it be discovered.
- **One external document remains unread and is cited as unverified**: the full text of
  Claeys (2026), which is Cloudflare-blocked. Its abstract is verified from the Crossref
  deposit and its four headline numbers are safe to cite; **the five platforms he compares
  are unknown to us and are never named.**
- **Two documents previously listed here as unread are now closed.** The item recorded as
  "the ResearchGate March 2026 HOSE/HNX simulation-platform paper" was identified as the
  JICCE 2025 dashboard, read in full, and found to contain no microstructure — it was a
  false alarm, and the earlier claim that it uses EUR/USD data was a misreading of *their*
  literature review. EvoMarket's paper has been read in full, including appendix and
  acknowledgments; only its source is unavailable, because none exists publicly.
- **Vietstock Đấu trường's current rules are unverifiable.** Our rule model for it is the
  2022 Wayback capture; the Dec 2025 relaunch added derivatives and put the rules behind a
  login. Any statement about its present rule set is unverified and must be marked so.

---

## 6. Figures and tables

| # | Artefact | Section |
|---|---|---|
| T1 | Capability × tool comparison, general engines (from `literature-review.md` §2.1) | §2 |
| T2 | Capability × tool comparison, specialist systems incl. **EvoMarket and MarS** (§2.2) | §2 |
| T2b | Capability × product comparison, **the Vietnamese landscape** (§2.5) — Vietstock Đấu trường, vnstockgame, SSI iWin (defunct), VPS SmartEasy, DNSE/SSI live APIs, the JICCE 2025 dashboard | §2 |
| T2c | **EvoMarket vs Plutus**, rule-surface differences only (from §2.6 of this outline) | §2.6 |
| T3 | Dated rule editions in force across the simulated window, with effective dates and confidence | §3 |
| F1 | The order state machine, with INDETERMINATE shown as an event on the resting arc, not a leaf | §4 |
| F2 | Indeterminate rate by data resolution and by cause (resolution-limit vs data-ceiling): the bar floor is intrinsic, the tick remainder is a data ceiling | §5 |
| F3 | Cross-policy divergence for one strategy, plotted against the indeterminate rate | §7 |
| E1 | Population fill-policy divergence (table): fill rate by order intent × policy, data-proven vs assumption, over 477k HSX orders — the headline fill-sensitivity result; replaces the old strategy taker panel | §7 |
| T4 | Measured results table, each row carrying its fill policy, resolution and assumption set | §7 |
| T5 | Tradeoff register: simplification, what it buys, fidelity given up, measured cost, revisit trigger | §8 |

## 7. Venue and length notes

- RIVF'26's 31 Aug deadline is explicitly **non-binding** for this work; the working
  horizon is Sep 2026 – Feb 2027. Do not compress §5 or §8 to hit a date.
- **If the venue is RIVF, the reviewer pool probably includes the JICCE 2025 authors**
  (same group, RIVF 2025). That does not change what we claim; it changes how their work is
  described. State scope, cite the DOI, and use no evaluative adjective about their paper
  anywhere in the submission.
- If the venue is a systems track, promote §4 and §6 and compress §2 to one page plus T1.
  **§2.6 is not compressible** — it is half a page that pre-empts the two strongest
  reviewer objections, and cutting it saves less than it costs.
- If the venue is a finance track, promote §1 and §7, and lead the abstract with the
  Menkveld non-standard-errors framing.
- Either way, §8 stays at full length. It is the section that makes the fidelity claim
  credible rather than asserted.
