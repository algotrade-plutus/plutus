# RIVF'26 paper — development compendium

*The full record of the line of work, for a paper-writing session. Companion to
`PAPER-HANDOFF.md` (the 2-page launchpad — read that first). This doc is the
narrative + the substance + the map to the detailed docs; it does not replace
them (FEATURES.md, SCENARIO-CATALOGUE.md, the rulebook, the margin specs, the
seven design specs all hold the full depth). Written 2026-08-29.*

**Numbers discipline:** quote every measured figure from
`docs/reference/tables/t4_measured_results.md` (regenerated against the corpus
2026-08-29 with CIs), never from this doc or from memory. Where this compendium
cites a number it is for orientation.

**Reading order for a paper session:** §1 (the arc) → §2 (thesis) → §3
(mechanics) → §5 (margin) → §6/§7 (the evidence: scenarios + strategies) → §9
(guardrails) → §11 (open threads). §12 is the document index.

---

## 1. The arc of the work (the development narrative)

Seven dated design specs in `docs/superpowers/specs/`, each forced forward by a
finding, later ones superseding parts of earlier ones. This is how the system
came to be — useful for the paper's "design" narrative.

1. **`2026-08-24-exchange-fill-model-design` — the origin thesis.** Plutus is an
   executable model of Vietnamese exchange *rules* applied to market data (not
   data, not a backtester), analogized to NautilusTrader's exchange-faithful
   execution. Introduced the `plutus.market` package, the `ExchangeSpec` (rules) /
   `Exchange` (behaviour) split, and a **stateless** two-method surface —
   `admits(order, state)→Admissibility`, `sustains(position, path)→Viability` —
   with the organizing **asymmetry claim**: admission binds on equity, survival
   binds on derivatives. Three-valued verdicts (ADMITTED/REJECTED/INDETERMINATE).
   Retired three unreproducible inherited headline figures.
2. **`2026-08-25-exchange-simulator-design` — the pivot to a stateful
   counterparty.** Superseded (1) in four respects, each forced: the exchange
   became a **stateful session** (T+2 — the most-wanted feature — is unimplementable
   statelessly); the **admission/survival asymmetry was dropped** (T+2 is a
   stateful, equity-side, exchange-enforced rule that breaks it); order lifecycle
   came in scope; the "backtest auditor" reframe was rejected in favour of **"a
   simulated Vietnamese exchange you point a strategy at"** with a broker-shaped
   `submit`/`poll`/`holdings`/`margin` API. Introduced the two-config split (dated
   `exchange_rules` vs commercial `broker_profile`), the encumbrance ledger,
   tranche holdings, the segregated derivatives deposit, the pluggable `FillPolicy`
   — while **retracting fill-policy novelty** (prior art: NautilusTrader, LEAN,
   Claeys 2026).
3. **`2026-08-25-tier1-interface-contract` — the build contract.** Seven modules
   (`types`, `rulebook`, `calendar`, `orders`, `ledgers`, `deposit`, `fills`,
   integrated by `exchange.py`), the dependency DAG, the exact `submit()` order
   (admit before fund), and five "locked shapes" — chief: **per-instant `(ticker,
   ts)` resolution via `rulebook.at(ts)`**. Nailed: settlement needs a VSDC
   business-day calendar (not day-counting; diverges around Tết); the margin entry
   takes the **whole account**; **no maintenance-margin ratio exists in Vietnamese
   rules at any date**.
4. **`2026-08-28-intraday-book-walk-session-design` — intraday taker fills.** Wired
   the built-but-unwired `BookWalkFillPolicy` + three queue policies + `DepthSource`
   through `submit`/`advance_to`: a marketable order fills by walking the real book
   under a **user-chosen, self-reported queue assumption**. Added the `book_walk`
   token, scenarios J28–J33, strategies S8/S9, and the D71 fix (tick-path ATC → the
   published close, not a stale `last`).
5. **`2026-08-28-tape-driven-maker-fill-design` — maker fills from the tape.** A
   book-snapshot taker model *cannot model a maker*; drove maker fills from the
   **trade tape** + queue position instead. Key data finding (→ J36): per-event
   volume is the **delta of `quote.total`** (sums to `dailyvolume`), not the lossy
   `quote.matchedvolume`. A maker fill is `MODELLED` evidence, never `TRADED_THROUGH`.
6. **`2026-08-28-test-strategies-design` — the end-to-end fidelity layer.** Seven
   strategies (S1–S7) that make each stress moment **emerge from P&L against real
   corpus data** rather than by poking a rule; two checks only possible over months
   of trading — **emergence** (the call lands on the day the loss actually breached)
   and **conservation** (every đồng reconciles). Runner is test-side: "we ship the
   market, not the backtester."
7. **`2026-08-29-paper-material-prep-design` — material, not prose.** The plan this
   session executed: figures F1–F3, tables T3–T5, `references.bib`, provenance-
   tagged numbers, and the eight workstreams W0–W7 (doc-truth; daily-VM cash
   settlement reversing a Tier-1 non-goal; F2; F3; margin regime-split; band
   conformance; artifacts; fixtures). North star: *where a shortcut and modelling
   it correctly diverge, model it correctly.*

Since then (this session): FEL shipped, the framing audit + five guardrails, the
dead-stack archival, and this handoff.

---

## 2. The thesis & framing

**Plutus is not a backtester** — it is an executable, effective-dated model of
Vietnamese *exchange* rules (admission + position survival), shipped as a library
so others can validate their methods against a faithful counterparty. The rare,
strong fact (verified by the framing audit): **the code's identifiers ARE the
paper's concepts** — `admits`/`sustains`, `Rulebook.at`, `Verdict.INDETERMINATE`,
`FillPolicy`/`QueuePolicy`, `BrokerProfile`/`MarginModel`, `FillEvidenceLevel`.

The pillars:
- **Two halves.** `admits()` — stateless admission (band/lot/grid/order-type),
  dominates equity (HSX/HNX/UPCoM). `sustains()` — stateful survival (margin/
  liquidation), dominates derivatives (HNXDS), where admission is nearly trivial
  and *that triviality is the finding*. (Nuance/guardrail §9-3: the authoritative
  survival implementation is the session margin path, not the legacy
  `Exchange.sustains`.)
- **Effective-dated rule editions.** `Rulebook.at(ts)` resolves every rule per
  instant and *refuses* out-of-window editions (`UnresolvedRule` →
  `Rejected(INDETERMINATE)`). The **paper's lead claim**, demonstrated on both
  sides: equity (round-lot 2021-01-04, band regimes) and derivatives (the ~30%
  pre/post-KRX MR gap on a fixed book).
- **Fill policy × queue assumption** — two pluggable axes carrying
  `.signature`/`.assumptions`; the uncertainty-band argument ("the output *is* the
  error bar").
- **INDETERMINATE / FEL** — the honesty spine (§4 of PAPER-HANDOFF; §7 here):
  absence of evidence is reported, never guessed.
- **Broker + exchange as one entity** — `ExchangeSession` is the single
  counterparty; a `BrokerProfile` selects the margin model.
- **BYO-data** — the paper does not claim a corpus (§11-data).

---

## 3. The mechanics inventory

Full detail: `docs/reference/FEATURES.md`. Confidence grades below are the
rulebook's own; `[design]` = our spec, dated but not gazetted.

### 3a. Public API (`session/exchange.py`, `ExchangeSession` at :814)
`build`/`from_config` · `submit(order)→Accepted|Rejected` · `advance_to(ts)→[Event]`
(fixed pass order: expire→fill→decide-immediates→settle→accrue→mark-derivatives→
overnight-margin→equity-margin→drain — load-bearing) · `poll()→[Event]` ·
`indeterminate_report()→RunIgnorance` · `provenance()→SessionProvenance` · read
models `cash`/`positions`/`holdings`/`margin`/`orders`/`charges` · `cancel`/`amend`
(decrease-only)/`transfer` · `attach_equity_margin`/`outstanding_call`/
`in_forced_breach`. **No P&L, no portfolio — the caller owns those.**
Value types (`protocol.py`): `Order`, `MarketState` ("everything an exchange needs
to judge one order at one instant"), `InstrumentSpec`, `Position`, `OrderBook`.
Verdicts (`verdicts.py`): `Verdict` tri-state, `AdmissionRule` ("this enum IS the
rejected-order log"), plus a second `StatefulRule` enum (D6: the two want merging).

### 3b. Admission gauntlet (`EquityExchange.admits`, `equity.py:46`)
Six rules, fixed order, short-circuit on first breach (upstream `submit` gates 0–4
add routing / dated order-type legality / dated size cap / dated tick):

| Rule | Enforces | Sourcing |
|---|---|---|
| **TICK_GRID** | `price % tick == 0`; tick None → INDETERMINATE | SOURCED when injected from rulebook (VNX QĐ 17); HOSE banded via `get_hsx_tick_size`; 3 MEDIUM legs |
| **ROUND_LOT** | `qty % unit == 0` | HOSE **10→100 @ 2021-01-04** (QĐ 894), HIGH; odd-lot board NOT BUILT |
| **BAND_LIMIT** | `price` outside `[floor, ceiling]`; None → INDETERMINATE | band comes from `MarketState` (reconstructed, undated flat constant), not the rulebook (A67); HIGH from each venue's date, LOW before |
| **BAND_LOCK** | only the locked side, only if marketable into the lock; UNKNOWN evidence → INDETERMINATE | the marketable-into-lock test is a market fact; the `LockEvidence` ladder (TICK_BOOK/BAR_PROXY/UNKNOWN) is **ours** `[design]` |
| **FOREIGN_ROOM** | foreign BUY only; None → INDETERMINATE (always, both corpora) | **DEFERRED** (T1): the field exists but both adapters hardcode `None`, so it never REJECTs |
| **SESSION_SEMANTICS** | phase legality (auctions need ATO/ATC/LO; continuous refuses ATO/ATC) | PARTIAL — venue asymmetries from the undated spec; PLO orders NOT BUILT |

Derivatives admission (`derivatives.py:54`) is deliberately trivial: tick,
lot-of-one, band only.

### 3c. Survival / margin — TWO separate implementations, do not conflate
- **Legacy batch path** (`HNXDSExchange.sustains` + `margin.py`): walks a lone
  position, tests `equity/notional < maintenance_rate` — **a ratio Vietnam does not
  publish**. DEFERRED and deliberately NOT rewired (it computed the *previously
  published* margin-incidence figures; rewiring would silently restate them). Holds
  the only `EXIT_BLOCKED` (band-lock-blocks-a-stop) model. **Do not extend.**
- **Session path** (`session/deposit.py`, the authoritative one): pre-KRX
  **`MR = IM + VM`** on the *whole account*, IM on current price, **VM loss-only**
  netted account-wide (VSDC verbatim); the **80/90/100 utilisation ladder is
  ASSUMED in shape and levels** (QĐ 26 Điều 13 is binary; the real 80/90/100 is
  Điều 29 *position limits*, a different quantity). **`settle_daily` (daily VM cash
  settlement) wired 2026-08-29 (MUST #4)** into `_overnight_margin`. `MarginMonitor`
  carries a call across days, cures in sessions, latches a forced close. **Forced
  liquidation now executes** (`_execute_forced_close`, net→0) — this landed;
  earlier docs saying it "reports only" are stale.
- **Post-KRX (2025-05-05+)**: **`MR = Max(ΣPgm, 0)`, `Pgm = Max(Rm+Sm+Dm, MM)`, no
  VM term** (`session/scenario_margin.py`). `Rm` = worst of a 21-scenario price grid
  (`is_reconstructed_grid` always True — the signed table omits `k`, DEFECT D1 in
  the instrument). `Rm` + MR assembly run on the corpus; `Sm` not implementable (no
  daily DSP series), `Dm` GB-only out of scope. `margin_model()` **raises**
  post-cutover rather than extend the pre-KRX shape.
- **Broker profile** selects the model **per layer** (`broker_profile.py`, 14-firm
  registry). Guardrail §9-4: for shipped firms this changes ladder levels /
  denominator / provenance, **not the running engine**.

### 3d. Fill + queue policies + FEL (`session/fills.py`, `book_walk.py`, `evidence_level.py`)
Continuous fill price = the order's own resting limit (QĐ 352 Điều 6.3, HIGH — the
module's strongest citation). Auction price = published open/close (**A75, our
modelling choice, not a citation**).
- **Fill:** `SoftFillPolicy` (optimistic, fills on touch — "comparison arm, not
  recommended"), `HardFillPolicy` (fills strictly-through, **INDETERMINATE at a
  touch** — time priority unrecoverable, 81% of quote changes carry no trade),
  `ProbabilisticFillPolicy` (seeded; `probabilistic_sweep` is the intended use),
  `BookWalkFillPolicy` (the taker sweep, per-level pricing; **not config-buildable**).
- **Queue:** Optimistic/Conservative/Probabilistic (position in the queue —
  UNSOURCED, the caller selects, stamped in provenance). Plus the tape-driven
  `MakerQueuePolicy`/`TapeSource` for maker fills.
- **FEL** (§7) grades every decision: PROVEN / ASSUMED(TOUCH|MODELLED) /
  UNEVIDENCED. A policy = a rule for the lowest level it acts on.

### 3e. Rulebook & effective-dating (`session/rulebook.py`)
`Rulebook.at(ts)→RuleSet`, total three-state (`KNOWN`/`NOT_APPLICABLE`/`UNKNOWN`),
never guesses; typed accessors raise `UnresolvedRule`. The **refusal mechanism**:
`_unsourced()` asserts an absence *as data* (11 rows) — this is how covered-warrant
bands and post-KRX margin refuse rather than fabricate. Counterfactual `Pin`s
self-declare in provenance. Confidence census in code: **66 HIGH, 11 MEDIUM, 7 LOW,
1 UNVERIFIED, 11 `_unsourced`**.

### 3f. Corporate actions, tax (brief)
Corporate actions (`corporate.py`): **caller-driven, NOT wired into `advance_to`**
(a CA feed is exogenous; an invented ex-date is worse than silence). The adjustment
algebra is **A26 — market practice, not gazetted, MEDIUM** (the one place the
traceability claim can't be met — flag it in the paper). Dividend withholding not
levied (credited gross). Charges (`charges.py`): 10 dated charge ids (PIT
securities 0.001 sell-side; PIT derivatives 0.0005×IM ratio; VSDC clearing
2,550/contract); rounding UNVERIFIED.

---

## 4. (see §3c/§5) — margin is split across the mechanics and the research arc

## 5. The margin research arc

Four docs in `docs/reference/`. Two products share the name `ký quỹ`; the
derivatives side split again at KRX.

- **`equity-margin-spec.md` — equity margin lending (*giao dịch ký quỹ*), NOT
  BUILT.** SSC-regulated broker lending against shares — a *different product* from
  derivatives clearing margin (different regulator, custody, call test). Statutory
  floors: IM ≥50%, maintenance ≥30%, cure ≤3 business days (QĐ 87 Điều 5).
  **Load-bearing negative finding: there is zero verified numeric call/force-sell
  threshold for statutory equity margin at any broker** — the DNSE table everyone
  cites is a *cash-product* table, not a margin ladder. So `call_level`/`force_level`
  are required-with-no-default.
- **`krx-margin-research.md` — the KRX cutover decision (2026-08-26).** Read from
  the signed VSDC `.docx`. Central method finding: three "missing formulas" were
  never missing — they are Word OMML equation objects every text extractor drops.
  Recovered `IM = VaR×√n`, the collateral valuation, and the wholesale replacement:
  **pre-KRX `MR = IM+DM+VM` (VM loss-only, in-session) → post-KRX `MR = Max(ΣPgm,0)`,
  once, post-close.** The "80/90/100 ladder" story corrected: that ladder was
  notification-only at rungs 1–2, and the only live 80/90/100 is **Điều 29 position
  limits**. `MF = 5,000đ`/VN30 contract, index-independent. §4 catalogues per-firm
  conventions including **inverted directions**: 13 firms run rising utilisation,
  **HSC runs falling coverage** (rungs descend 100/80/60).
- **`post-krx-margin-spec.md` — the scenario-grid spec, NOT BUILT (engine is).**
  `MR = max(Σ_groups max(Rm+Sm+Dm, MM), 0)`, per account, EOD; **VM is not a
  component** (daily P&L leaves as cash T+1, Điều 20). `Rm` = |largest loss| over 21
  scenarios `Sk = S0(1 + k·rate/10)`. DEFECT D1: the printed formula omits `k`.
- **`margin-model-adjudication.md` — which figure the paper prints (2026-08-26):
  publish NEITHER call-rate figure.** The legacy 7.61/12.60/14.70% is
  `P(drawdown > 6.024%)` where 6.024% is an unsourced broker buffer, not a rule. The
  account model at funding k=1 calls 100% — an arithmetic identity. **The claimed
  disagreement between the two models does not exist**: `k∈[1.4110,1.4136]`
  reproduces 29/48/56 exactly once the dated ratio is held constant. Recommended
  replacement: the **peak-requirement-multiple `U*`** (median 1.09× at 10-session
  hold), no unsourced parameter. Denominator caveat: 381 overlapping windows — report
  cluster-robust intervals, never n=381.

---

## 6. The Jx scenario acceptance suite

Full: `SCENARIO-CATALOGUE.md` (J1–J27, dated 2026-08-27) + `SCENARIO-BOARD.md`.
**37 files / 38 tests, all green.** *(The catalogue's "19 runnable / 6 partial / 2
blocked" is the 2026-08-27 snapshot; since then all five MUST items landed and
J28–J37 were added. "Partial/blocked" is a claimability taxonomy about the default
config-driven path over the wired corpus — NOT whether the test passes; all 38
pass.)*

**Methodology.** The **acceptance spec, driven green like TDD**. Each scenario is
**executable user code on the public surface** — a demo half (what the library
does) + a *Broken looks like* half (the wrong output a naive backtest gives). Two
tiers: **Tier 1 "it runs"** (no crash, every order a real answer, no unwarranted
INDETERMINATE), **Tier 2 "it's right"** (outcome matches the documented Vietnamese
rule). The loop: **on failure we fix the simulator, never the scenario.** The
oracle is the dated rulebook; every mechanism names a document + article + dates +
**confidence grade**, or one of the labels UNSOURCED / INFERRED / our-modelling-
choice / **sourced-absence** (read the doc, the thing isn't there — a finding) /
UNVERIFIED / empirical. "A scenario page that omits its declared assumption is
worse than no scenario page."

**The catalogue by theme (J1–J37):**
- *Admission/band/lot/grid:* **J1** T+2 settlement · **J2** BAND_LIMIT vs BAND_LOCK
  (limit-up) · **J11** floor-lock stop (sourced absence: no market-at-floor order
  exists) · **J12** MOK vs MAK (partial) · **J13** MTL residue conversion · **J14**
  ATO vs marketable LO cross (direct-drive) · **J15** sale advance · **J16** T+2
  turnover cap.
- *Dated-rule demos (the distinctive claim):* **J17** round-lot 2021-01-04 (cleanest)
  · **J18** VSD IM 13→17% = **+30.8%** with zero price move · **J19** KRX cutover, a
  *different margin model* each side (post side honestly raises `UnresolvedRule`).
- *Uncertainty band (no Vietnamese rule underneath):* **J20** one strategy under
  soft/hard/probabilistic — the spread is the error bar · **J21** three queue
  policies · **J22** participation-cap sweep.
- *Derivatives:* **J3** leveraged VN30F → call → forced liq → daily VM · **J6** roll
  across expiry (settlement error bar +0.042%; clearest daily-VM exhibit) · **J26**
  day vs swing trader (two margin layers).
- *Cross-market / equity finance:* **J4** pair trade (two regimes/clocks, segregated)
  · **J5** margin-financed equity force-sold (**the forced sale EXECUTES**).
- *Corporate/coverage/robustness:* **J7** auction-only (direct-drive) · **J8** ex-date
  (adjustment arithmetic in no gazetted doc — MARK IN PAPER) · **J9** thin name, cap
  binds · **J23** 30-name basket · **J24** out of cash · **J25** the ignorance meter
  (use `is_clean`, not the count) · **J27** amend re-runs encumbrance+admission
  (exhibits MUST #2, the only one).
- *The headline:* **J10** naive fill-at-close vs Plutus — the delta *is* the value
  proposition (a lower bound).
- *Intraday extension (J28–J37, through the public session):* **J28** book-walk
  taker · **J29** queue by config · **J30** book sweep (per-tranche pricing) ·
  **J31** stale book (budget refusal) · **J32** maker fill from tape · **J33** maker
  queue spread · **J34** maker no-trade = definite no-fill (clean ignorance) ·
  **J35** maker on unseen tape = INDETERMINATE naming VOLUME · **J36** tape
  integrity (`quote.total` deltas = 697,700; `matchedvolume` lossy) · **J37**
  tick-path ATC = published close (fixes D71 = MUST #5).

**The five MUST items (the publish gate) — ALL LANDED:** #1 order-book walk
(J13/J28/J30) · #2 amendment re-runs encumbrance (**J27**) · #3 forced liquidation
executes (J3/J5) · #4 daily VM cash settlement (2026-08-29 `3e7e17a`; J3/J6/J26) ·
#5 tick-path close-as-ATC (2026-08-29 `74e667a`; J37).

**Launch subset (15):** J1,J2,J11,J13,J15,J16,J17,J18,J5,J6,J26,J27,J25,J20,J10 —
every group represented, every MUST exhibited, the headline defensible.

---

## 7. The Sx strategy validation suite

Full: `STRATEGY-BOARD.md` + the three 2026-08-28 specs. **9 strategies (S1–S9), all
at Tier 2** + F2/F3 figure tests. The layer *above* the Jx scenarios.

**Methodology.** Nine real, documented trading strategies, each written as a user
would, run against Plutus **as the counterparty**. A scenario *stages* a rule; a
strategy makes the moment **emerge from P&L against real corpus data** — "a
strictly stronger fidelity claim." Two checks only possible over months:
**emergence** (the call lands on the corpus day the loss actually breached) and
**conservation** (every đồng reconciles). On any Tier-2 failure, fix the simulator.
The runner (`_harness.py`, `_intraday_mm.py`, `RunLedger`) is **test-side** — "we
ship the market, not the backtester." **7/7 (S1–S7) reached Tier 2 forcing two real
library builds; five passed on the existing engine** — the suite mostly *confirmed*
fidelity rather than exposing defects.

**The two policy axes** (the spine): **fill** (soft/hard/probabilistic, bar
resolution — our modelling choice A34/A35) and **queue** (optimistic/conservative/
probabilistic, tick maker fill — UNSOURCED). Neither may override band/tick/lot/
order-type (decided before it runs).

- **S1 — VN30F mean-reversion (crown jewel):** contrarian z-score, conviction-sized,
  into the Oct-2022 trend that punishes mean-reversion. Emergent: the loss is real
  corpus P&L, and under daily VM the deposit depletes so fast utilisation **jumps
  past the call rung straight to FORCED** (forced liq executes). **40M → 9.4M
  (−76%).** *(Nuance: STRATEGY-BOARD's "2 calls → forced" narration predates daily
  VM; treat any intermediate-call count as data-dependent, cite the emergent forced
  liquidation.)*
- **S2 — leveraged equity momentum (DIG, 1.8:1):** a stop only works if you can
  sell; a four-day limit-down waterfall locks the book, the stop is refused day
  after day. **100M → 13.6M (−86%);** the forced sale was instructed ~25× but
  completed 3× (14 lock days). *The account bled because it could not get out.*
- **S3 — basket vs future (first real BUILD):** long {HPG,SSI,MBB} vs short
  VN30F2212 across an ex-date. **Built `ExchangeSession.apply_corporate_action`** —
  the "missing feature → build it, don't mock" case. Dividend paid gross through the
  session; ex-date reference conserves value. 1596 tests, no regression.
- **S4 — auction MoC rebalancer (second real BUILD):** trade only the auctions.
  **Built `AuctionAwareDataHubSource`** (the daily adapter stamps every bar
  CONTINUOUS). 8 ATO + 5 ATC + 0 continuous fills; on ≥1 day open ≠ close.
- **S5 — high-turnover scalper:** run twice, with/without the sale advance (*ứng
  trước tiền bán*): with → more turnover + a 545,624đ fee (J15); without → throttled
  4 days by T+2 (J16). *(Known cosmetic MTM gap on the trough curve; verdict rests on
  throttle/fee metrics.)*
- **S6 — KRX regime-straddle:** the guard queries `margin_model()`: pre-KRX resolves
  → trades; post-KRX **raises** → refuses to size a position it cannot margin. The
  corpus ends 2022-12-30, so the post-KRX side is asserted at the edition level,
  never with fabricated prices. Guards against *silent continuation*.
- **S7 — fill-sensitivity harness (the methodological one):** S1 unchanged under the
  three fill policies. **soft → −76%; hard & probabilistic → 0 fills, 40M
  untouched.** "S1's history is −76% or 0% purely by fill policy." Feeds F3's fill
  panel.
- **S8 — intraday inventory market-maker (the intraday selling point):** two-sided
  maker fills off the tape at its own posted prices (the book-snapshot model
  produced zero); the inventory skew fires; the T+2 constraint means no intraday
  round-trip on HSX. VN30F variant contrasts a futures desk that *can* round-trip.
- **S9 — queue-sensitivity study (the honest intraday headline):** the same maker on
  the same day under all three queue assumptions, skew OFF so the quote is identical
  across runs and the spread is the queue's alone: **optimistic > probabilistic >
  conservative, ~18.9% swing.** "The queue assumption, not the strategy, moves the
  maker's P&L by ~19%." Feeds F3's queue panel.

**The maker-fill mechanic** (from the two specs): a resting limit at price P fills
from **prints-through the tape** since arrival, gated by **queue-ahead** (displayed
size at arrival). Optimistic = min(remaining, prints); conservative = max(0,
prints − ahead); probabilistic = seeded ahead ∈ {0..displayed}. **Zero prints on an
observed tape = a definite no-fill (clean), not indeterminate; an absent tape =
INDETERMINATE.** Volume from `quote.total` deltas (authoritative), not the lossy
`matchedvolume` (→ J36). A maker fill is `MODELLED`, never `TRADED_THROUGH` — we
infer our fill from the aggregate tape + a position; there are no order ids, which
is exactly why S9 measures what the unobservable queue is worth.

**Reproduction gotchas the paper must carry:** (1) **prices are ×1000** (corpus in
thousands of đồng, cash in đồng); (2) **MTL to take liquidity** (a marketable limit
fills at its own aggressive price — pays limit-up — the only correction S1 needed);
(3) the day loop must pass the **14:45 derivatives determination** or the margin
lifecycle never runs; (4) **shipped fixtures** (W7, <1 MB) make `clone → pip install
→ pytest strategies/` run from a bare clone; (5) tests **skip, not fail**, without
data; (6) look-ahead safety by construction (`CorpusFeed` reads `[start, asof)`);
(7) **`FINE_MARKS`** so the queue assumption bites; (8) probabilistic reproducibility
under **seed 7**.

---

## 8. Measurements & artifacts

`reproduce_measurements.py` — a **10-step** pipeline, each step naming the claim it
backs: (1) storage, (2) coverage, (3) query speed, (4) field availability, (5) test
suite, (6) equity admission + band conformance, (7) tick-grid conformity, (8)
derivatives margin (account model + regime split), (9) bar-vs-tick divergence, (10)
indeterminate rate (F2). Standalone modules: `dated_rules.py` (exposure → T3),
`occupancy.py` (actual binding). Key modules: `equity_admission.py` (the lag0 vs
lag1 look-ahead gap), `band_conformance.py` (the engine's own `reconstruct_bands` vs
vendor — 97.6% HSX stock, W5), `margin_incidence_account.py` (the adjudicated
account model + `U*`), `regime_split.py` (~30% pre/post-KRX), `indeterminate_rate.py`
(F2), `margin_incidence.py` (RETIRED legacy comparator, kept in place).

**Artifacts** (all committed; generators in PAPER-HANDOFF §5): **F1** state machine,
**F2** indeterminate rate by (resolution×cause) — *being reframed, §11*, **F3**
cross-policy divergence; **T3** dated rule editions, **T4** measured results (the
verified numbers source), **T5** tradeoff register; `references.bib`. Section→
artifact map in `paper-outline.md`.

---

## 9. The framing audit & the five guardrails

An adversarial audit (2026-08-29) confirmed all six framing claims are genuinely
implemented. The five guardrails the paper must not overstate:
1. **`evaluation.PerformanceEvaluator` is a real return/risk calculator** — scope
   "not a backtester / no P&L" to `market/`+`session/`. *(Done: `evaluation` is
   docstring-scoped as an optional helper.)*
2. **Dead `core/` stack — RESOLVED** (archived, §10).
3. **`Exchange.sustains` (HNXDS) is legacy** — point "the survival half" at the
   session margin path, not it.
4. **Broker-profile selection doesn't switch the running engine for shipped firms**
   — it changes ladder/denominator/provenance, not the engine.
5. **Queue axis + probabilistic fill arm aren't in the session public `__all__`** —
   they exist and are pluggable; don't imply front-and-centre. (FEL now *is* public.)

---

## 10. Cleanup & core strengthening

- **Dead trader stack archived** (`d27d4cd`): bot/algorithm/portfolio/position/
  transaction → `archive/legacy-trader-stack/` (no `__init__.py`, not shipped, not
  deleted; history kept). Only importable before via an accidental `import utils`
  resolving to `tests/utils.py`. D31 resolved.
- **`evaluation/` scoped** as an optional metrics helper (kept; 216 tests).
- **FEL added** (`db29e9d`) — §7 / PAPER-HANDOFF §4.
- **The D-series defect inventory** (`FEATURES.md` §17): ~60 IDs, ~20 struck FIXED,
  ~40 open — **most open ones are docstring/naming mismatches with no behavioural
  effect.** The four behaviourally-substantive open defects the paper should know:
  - **D33** — the position-limit gate counts **one expiry** (`_worst_case_net`), but
    QĐ 26 Điều 27.2.a sums across expiry months; a rolled 4,000+4,000 position (truly
    8,000) passes both tests at 4,000 vs a 5,000 cap. The *ordinary* shape of a
    rolled future, not a corner case.
  - **D5** — three *definite* refusals (already-terminal / non-amendable type /
    qty-below-filled) are stamped INDETERMINATE on `phase is UNKNOWN` — **corrupts
    the REJECTED-vs-INDETERMINATE honesty distinction the paper leans on.**
  - **D40** — a margin call cannot be cured under the loop `advance_to` documents
    (09:30 escalates to FORCED before `on_session`); the regulated deadline is
    actually 09h30 T+1 → the default should move later.
  - **D25** — divergent multiplier paths: `session.instrument('GB05F2312')` returns
    100,000 with a DataHub source and 10,000 without (margin itself is right).
  Also worth a line: **D45** (the corpus inverts ceiling/floor on the two VN30F
  sessions either side of Tết-2021 — a data defect), **C3/C4** conflicts (a limit
  always fills at its own limit — anti-conservative into the margin ladder; every
  corpus price is same-session look-ahead — why "0 indeterminate" and 100% fill
  coexist; the `DataHubSource` reimplementation is scheduled), and **D36** (suite
  total unstable, ~47-test collect/pass gap — bears on the "green tests prove little"
  stance).

---

## 11. Data posture, and open threads

**Data posture (BYO-data).** The paper does **not** claim a corpus — data is the
weakest link, not a contribution; third parties provide better. Shipped data is
only the minimal fixtures to reproduce the Jx/Sx suites. **Two axes of
indeterminacy must never be conflated:** a **resolution limit** (a daily bar cannot
see intraday fill existence — unfixable by any data, only finer resolution) vs a
**data ceiling** (a reconstructed 3-level book cannot establish queue position — we
are not the exchange, unfixable by resolution, only by more complete data). "Best
data" = field completeness, not resolution; F2 is the deliberate exception that runs
both resolutions to measure the difference. Two-tier reproducibility: the suites +
fixtures reproduce from a bare clone; headline measurement numbers are provenance-
documented demos, some against production data not redistributed. Corpora: daily
Parquet (`hermes-parquet`), the `local_quote` tick book with sizes
(`hermes-dev-extract`), the ~21 GB raw archive. Exchange-side margin outputs stay
**provisional** (the VSDC engine can't be reproduced end-to-end from public data —
missing `n`, the scenario/collateral tables, the DSP series).

**Open threads for the writing:**
- **The F2 reframe** (PAPER-HANDOFF §8): the committed F2's 100% is an artifact of
  the adapter withholding the daily low; full OHLC → ~36% (PROVEN 0%→64%), residual
  localized to the touch. Decide: wire `quote_max`/`quote_min` into
  `DataHubSource.interval()` (a ~15–20 line change the datahub docstring flags
  pending) + redraw F2 around FEL.
- **FEL report wiring** — emit the FEL *distribution* per run alongside
  `indeterminate_report()`.
- **The API rename** — the reader-facing word is FEL/UNEVIDENCED / "assumed"; the
  API keeps `indeterminate_report()` for now (rename is mechanical but wide,
  deferred).
- **Substantive defects** (D33/D5/D40/D25 above) — decide which to fix vs disclose
  before publishing; D5 in particular touches the honesty claim.
- **NOT BUILT** (disclose, don't claim): equity margin lending, securities-as-
  collateral valuation, GB futures, intraday margin checkpoints, the Điều 29
  position-limit warning ladder, odd-lot / PLO order boards.

---

## 12. Document index

| Doc | Holds |
|---|---|
| `docs/reference/PAPER-HANDOFF.md` | the 2-page launchpad (read first) |
| `docs/reference/paper-outline.md` | the section→figure/table map |
| `docs/reference/tables/t4_measured_results.md` | **the verified numbers** |
| `docs/reference/tables/{t3,t5}*` | dated rule editions; tradeoff register |
| `docs/reference/fill-evidence-levels.md` | FEL reference (§5 spine) |
| `docs/reference/FEATURES.md` | the feature + defect (D-series) inventory |
| `docs/reference/SCENARIO-CATALOGUE.md` · `SCENARIO-BOARD.md` | the Jx suite |
| `docs/reference/STRATEGY-BOARD.md` | the Sx suite |
| `docs/reference/vn-exchange-rulebook-2020-2026.md` | the sourced rulebook (the oracle) |
| `docs/reference/{equity-margin-spec,krx-margin-research,post-krx-margin-spec,margin-model-adjudication}.md` | the margin research arc |
| `docs/reference/literature-review.md` | prior art / positioning |
| `docs/superpowers/specs/2026-08-*` | the seven design specs (the arc) |
| `reproduce_measurements.py` · `measurements/` | the measurement pipeline |

---

## 13. Immediate next steps (paper session)

1. **Push the branch** (`rivf26-wp1-wp2-wp4`, unpushed).
2. Draft against `paper-outline.md`, numbers from **T4**, §5 spine = **FEL**,
   honoring the §9 guardrails and the "mark in paper" flags (ex-date arithmetic
   ungazetted; auction cross price a modelling choice; margin outputs provisional).
3. Decide the **F2 reframe** early (it changes a figure and a headline).
4. Decide disclosure-vs-fix for the substantive defects (D5/D33/D40/D25).
