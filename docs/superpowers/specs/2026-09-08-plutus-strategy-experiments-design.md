# Strategy-driven experiments for the RIVF'26 paper — design

**Date:** 2026-09-08 · **Status:** design approved, pre-implementation ·
**Spans repos:** `plutus` (hub) + `proto/ProtoSmartBeta`, `proto/ProtoMarketMaker`,
`proto/ProtoGrid` (new), `proto/ProtoPair` (new).

Companion to the existing paper material: `docs/reference/PAPER-COMPENDIUM.md`
(development record), `docs/reference/paper-outline.md` (section map),
`docs/reference/tables/t4_measured_results.md` (the verified-numbers store), and
`docs/reference/EXPERIMENT-E1-FILL-DIVERGENCE.md` (the prior E1 this work
generalises).

---

## 1. Motivation

The paper "Closing the Gap Between Backtest and Market" (`plutus-rivf26.pdf`) is
sound but its experiment section (§VI) rests on **synthetic probes**: E1 is a
5-intent-per-ticker-day population, E2 re-dates a fixed 381-position book, and the
`equity_admission` result is SQL over a constructed order set. Each is honest but
mechanical, and the most-attackable sentence in the paper is "31.6% of a *realistic*
order flow" resting on an equal-weight synthetic mix.

**Goal:** give the experiment section a stronger methodological and rhetorical pose by
measuring the same phenomena (flow → E1, capital → E2, admission) as they emerge from
**real, alpha-seeking trading strategies executed against the faithful Plutus market**,
contrasted with each strategy's own naive backtest. This is design for scientific
validity, explicitly *not* bounded by the 6-page limit; prose selection into the paper
is a downstream step.

**State note (post-2026-09 disk failure):** the RIVF paper's LaTeX source is lost (only
the PDF survives; `references.bib` survives in-repo). The code repo and the data corpus
survived. See the `rivf26-paper-state` memory.

## 2. Thesis

> The naive execution assumptions a developer defaults to — because they lack a faithful
> simulator — do not merely change fills; they propagate into sizing and capital
> decisions and compound into reported performance (P&L, Sharpe, MDD). Plutus makes that
> distortion visible on real strategies. And the value of a faithful simulator **scales
> with a strategy's execution intensity** — we run the spectrum and measure the gradient,
> including where fidelity does *not* matter.

- **P&L is a consequence, never the headline.** It is computed by the caller's harness
  (Plutus reports only fills/cash/margin), reported truthfully, and framed as the
  downstream effect of named mechanisms.
- **The contrast is the persuasive core:** naive default vs faithful Plutus, same signals.
- **Execution-intensity spectrum:** SB (null anchor, naive≈faithful) → Grid → MM → Pair
  (rising divergence). This pre-empts the "you cherry-picked strategies that need your
  tool" objection with a measured gradient that includes a near-null point.

## 3. Escaping the prior strategy-E1 refutation

`EXPERIMENT-E1-FILL-DIVERGENCE.md` killed an earlier strategy-based E1 for three reasons.
This design escapes each **by construction**:

| Prior failure | Escape |
|---|---|
| **Sign-confound** (S1/S2/S5 lose *when* they fill) | The proto strategies are alpha-seeking, not loss-by-construction (SB +105% IS, MM +30% IS). The measured object is the naive-vs-faithful *delta of the same signals*, sign-neutral in spirit. |
| **Tiny n** (claims on 4–5 fills) | Lead with **large-n sign-free intermediates** (orders refused, quantity divergence, contracts, margin events). Grid/MM generate thousands of order events; the synthetic 477k population is retained as a corroborating backbone. |
| **Reporting P&L** (outside Plutus's contract) | P&L stays in the **caller's harness**; Plutus reports only fills/cash/margin. P&L is Tier-2 consequence, not the headline. |

## 4. The experiment unit: one signal source, two backends

A small `ExecutionBackend` interface, which maps ~1:1 onto Plutus's broker-shaped
`ExchangeSession`:

```
ExecutionBackend:
    submit(order) -> Ack          # accepted | rejected | filled | partial | indeterminate
    cancel(id) / amend(id, ...)
    poll() -> [Event]             # fills, expiries, margin calls since last poll
    advance_to(ts) -> [Event]
    cash() / positions() / holdings()   # holdings tranche-aware for T+2
    margin() -> MarginState
    charges()
```

- **`NaiveBackend`** wraps each proto repo's existing engine (fill-at-close/on-touch, no
  admission, static costs, unlimited liquidity). It *is* the developer default and must
  reproduce the published metrics.
- **`PlutusBackend`** is a thin adapter over `ExchangeSession` (admission, fills under a
  chosen policy, dated margin, T+2 settlement).

The strategy's signal/sizing/rebalance logic is extracted to run **once**, against the
interface; swapping the backend gives naive vs faithful on the *same live signals*.

**Two invariants:**

1. **Behaviour-preserving refactor.** After extraction, running with `NaiveBackend` must
   still reproduce each repo's committed `.plutus/expected/` baseline — `plutus check`
   stays green on the `rivf-2026` branch. This is the regression gate proving the strategy
   was re-plumbed, not changed; the naive number stays a real, verified anchor.
2. **Identical frozen data slice.** Both backends read the *same* frozen **parquet** file
   (§7) directly — each proto naive engine's data loader is refactored to read parquet, so
   there is no CSV/parquet seam between naive and faithful. The guarantee is *identical file
   in*, so the naive-vs-faithful delta is purely execution, never a data mismatch.

**Live run + frozen diagnostic.** Two lenses per strategy:
- **Live faithful run** (`PlutusBackend`): the true counterfactual trajectory — what the
  strategy would actually have done against a faithful market (adapting to refusals /
  partial fills / margin calls). The headline.
- **Frozen diagnostic:** the exact order stream the strategy emitted under `NaiveBackend`,
  replayed through Plutus's *existing* per-order instruments — `fills.compare_policies`
  (E1), `admits` (equity_admission), the margin evaluators (E2) — for clean per-mechanism
  attribution. This is how E1/E2/admission "follow the same improvement": the synthetic
  probe is replaced by a real strategy's order stream through the same code.

Each strategy yields three artefacts: **naive result** (published anchor), **faithful live
result** (counterfactual + FEL profile + margin events), **frozen attribution** (admission
rate, fill-policy divergence, indeterminate rate, margin-driven sizing gap).

## 5. The four strategies (execution-intensity spectrum)

| Strategy | Role | Window | Primary axes / bindings Plutus surfaces |
|---|---|---|---|
| **SB** (ProtoSmartBeta; equity, monthly rebalance, close-price) | **Null anchor** — naive≈faithful, kept as-is | 2021–2024 (data-covered; 2019–20 IS optional via DB) | Calibration point; small T+2 (monthly liquidate-then-buy can't self-fund same-day) + admission residual. Its window spans the **2021-01-04 lot change** (equity dated edition). |
| **ProtoGrid** (equity, wide logical ladder, 1–2 B VND, 1–5 VN30 tickers) — **new 9-step** | Equity demonstrator | 2021–2024, tick resolution | **Admission** (sliding band window over a fixed ladder as reference drifts; tick grid; 100-lot; lock-freeze on limit days) + **fill/queue** (resting rungs on the real tape/book) + **T+2 recycling** (sell proceeds locked 2 days → buy-back rungs can't self-fund). |
| **MM** (ProtoMarketMaker; VN30F futures, 15s quoting, overnight) | Derivatives demonstrator | 2022–2025 | **Capital/margin (E2)** — contract sizing is margin-bound; naive static margin vs **dated IM (13→17% @ 2022-12-15)** and **pre/post-KRX regime (2025-05-05)** afford *different contract counts* → different inventory capacity → different spread capture; daily-VM triggers **calls/forced liquidation**. + **maker/queue** (~19% fill swing). Run extended past native OOS (2025-04-29) to **cross KRX** — the live lead-claim demo. |
| **ProtoPair** (VN30F1M vs VN30 basket) — **new 9-step** | Cross-market capstone | 2022–2025 (across KRX) | **All axes + settlement asymmetry:** equity leg T+2 vs futures leg daily-VM → a "market-neutral" pair is *not* capital-neutral in time; **segregated pools** (equity profit can't meet a futures VM call until settled); **no equity short-sale** → only the "future-rich → short future / long basket" side is executable, the mirror side is refused (a rule shaping the opportunity set); band lock on the equity leg **breaks the hedge**. |

**New-strategy 9-step designs** (each its own repo, scaffolded via the `9-step:*` skills,
shipping its own naive engine + IS/OOS split + Plutus manifest):

- **ProtoGrid.** Thesis: liquid VN equities oscillate in a range; a buy-low/sell-high limit
  ladder harvests it, and the band/tick/T+2 decide how much a real account keeps. Naive
  engine: fills the full ladder on any touch, no band clip / lock / tick / queue / T+2.
- **ProtoPair.** Thesis: VN30F1M and the VN30 basket are cointegrated; the basis
  mean-reverts; trade the spread on the executable (no-short) side. Naive engine: both legs
  frictionless, shorting allowed, static margin, no settlement asymmetry.

## 6. Metric taxonomy (all strategies)

- **Tier 1 — sign-free intermediates (headline).** Orders refused by cause (band/lot/tick/
  session/no-short), executed-quantity divergence across fill policies, fill-policy
  agreement rate, indeterminate/FEL profile, contracts-affordable & margin-required,
  margin-call/forced-close incidence, settlement-throttle magnitude. Large-n; exactly what
  Plutus is licensed to report.
- **Tier 2 — downstream consequence (punchline).** Realized P&L / Sharpe / MDD, faithful vs
  naive, computed by the caller's harness. Truthful, framed as consequence.
- **Attribution.** From the frozen diagnostic + Plutus provenance: which named mechanism
  (admission / fill policy / queue / dated margin / settlement) drove the gap.
- **Spectrum figure.** x = execution intensity (turnover / order frequency / leverage /
  resting-order reliance), y = naive→faithful divergence; SB≈0 to Pair at the top.

## 7. Data pipeline (two-phase, reproducible)

**Sources, priority order (reuse first, DB last):**

| Source | Holds | Used for |
|---|---|---|
| `stock_quote_12.2020-09.2024/` (48 GB CSV) | full equity tick+daily+bands+foreign-room, Dec 2020–Sep 2024 | SB, ProtoGrid, ProtoPair equity leg (≤09.2024) |
| `hermes-parquet/` | already-converted slices | anything already covered |
| **algotradeDB** (remote, read-only) | VN30F1M/F2M futures, margin params, post-09.2024 equity, post-KRX | MM, ProtoPair futures leg, KRX-crossing runs |

**Phase A — Extraction (one-time, needs sources).** Per-strategy required-data manifest
`{fields, tickers, date-range, resolution}`. Resolve per slice: (a) existing parquet →
use; (b) equity CSV → convert just that slice; (c) else → algotradeDB → parquet. Reuse
plutus's `parquet_converter` + the proto repos' `database/query.py`. Convert **selectively**
(fields × tickers × dates), never the whole 48 GB. Read-only creds in gitignored `.env`.

**Phase B — Experiment (reproducible, ships with code).** Every downstream consumer —
naive engine (its data loader refactored to read parquet), `PlutusBackend`, measurements —
reads **only** the frozen **parquet** slice — one shared format, no CSV seam. No live source
needed to reproduce. Large slices via Drive (proto pattern); small committed in-repo.

**Invariant:** one frozen slice per strategy is the *sole* input to *both* backends (§4).

## 8. Results registry

All results — the four strategies' Tier-1/Tier-2/attribution and the retained synthetic
E1/E2/admission — recorded in a single referenceable store (extend the
`t4_measured_results.md` discipline, or a sibling table), each with provenance and
regenerating module. Nothing discarded. Paper prose selects what fits page room; synthetic
rows are retained as corroborating large-n backbone and appear when room allows.

## 9. Repo / branch layout

| Repo | Action |
|---|---|
| `proto/ProtoSmartBeta` | branch `rivf-2026`: `ExecutionBackend` seam + `PlutusBackend`; **data loader refactored to read the frozen parquet**; `plutus check` green under `NaiveBackend` |
| `proto/ProtoMarketMaker` | branch `rivf-2026`: same |
| `proto/ProtoGrid` | **new** 9-step repo; own naive engine + `PlutusBackend` |
| `proto/ProtoPair` | **new** 9-step repo; same |
| `plutus` (working branch) | shared `ExecutionBackend`/`PlutusBackend` adapter (proto repos add `plutus` as a path/git dep — literally the paper's "pair Plutus with your own tooling"); analysis + frozen-diagnostic reuse under `measurements/`; results registry under `docs/reference/tables/` |

## 10. How it maps into the paper

- **§VI (Results)** rebuilt around the four-strategy intensity spectrum: headline spectrum
  figure + per-strategy Tier-1 tables + Tier-2 punchlines + the two dated-edition demos
  (SB 2021-01-04; MM 2022-12-15 & 2025-05-05).
- **§V (37 Jx scenarios + 9 Sx strategies)** unchanged as the fidelity-evidence layer.
- **Synthetic E1/E2/admission** retained as corroborating backbone rows (page-room gated).
- Bonus: foreign-room enforcement is now possible (data exists) → may *remove* a
  threat-to-validity; treated as optional.

## 11. Build order (increment of rising complexity)

0. **Seam + adapter on SB** (simplest, already built): `ExecutionBackend`, `PlutusBackend`,
   refactor SB, prove `plutus check` green under `NaiveBackend`, run naive-vs-faithful →
   the null-anchor result + the data-slice + registry plumbing.
1. **ProtoGrid** (new 9-step) — equity demonstrator (admission + fill/queue + T+2).
2. **MM** (refactor + backend) — derivatives + KRX dated editions.
3. **ProtoPair** (new 9-step) — cross-market capstone.

Each phase ships: frozen data slice, both-backend runs, results into the registry.

## 12. Open items / risks

- **algotradeDB credentials** — read-only; confirm/obtain (ProtoMarketMaker `.env` may
  carry them). Never commit.
- **`plutus` importability into proto envs** — packaging is currently rough
  (`algotrade-plutus` vs `plutus` on PyPI); use a path/git dependency, not PyPI.
- **MM native OOS ends 2025-04-29, 6 days short of KRX** — the cutover demo is a labelled
  extension into May 2025 with post-KRX margin params (SMrate ≈ 0.87%, MF 5,000đ).
- **SB 2019–2020 IS gap** — the equity CSV starts 12.2020; either backfill from DB or run
  SB on the covered window (acceptable — it is only the null anchor).
- **ProtoGrid tick-run cost** — daily is the fallback if the tick run is too heavy.
- **Behaviour-preserving refactor** must be verified per repo (the regression gate), or the
  naive anchor loses its credibility.
- **CSV→parquet conversion must be value-lossless** (Decimal price precision preserved), or
  the naive engine's parquet-read numbers drift from its published CSV baseline and the
  behaviour-preserving gate fails — verify each repo's metrics still reproduce after the
  loader switch.

## 13. Acceptance criteria

1. `ExecutionBackend` + `PlutusBackend` land in `plutus`; SB refactored on `rivf-2026`;
   `plutus check` green under `NaiveBackend`.
2. Each strategy runs both backends over one identical frozen **parquet** slice, read
   directly by both (naive loader refactored to parquet); naive reproduces its published
   metrics within `plutus check` tolerance.
3. Tier-1 sign-free measures + Tier-2 P&L + frozen attribution emit into the results
   registry per strategy, with provenance and a regenerating module.
4. ProtoGrid and ProtoPair exist as 9-step repos (own naive engine, IS/OOS, manifest).
5. The intensity-spectrum figure regenerates from the registry.
6. Every experiment reproduces from its shipped frozen slice with no live source.
