# Scenario board — the acceptance suite, driven green

The 27 catalogue scenarios (`SCENARIO-CATALOGUE.md`) are our acceptance spec. Each is an
**executable test written as a user would write it** — reproducible code against the public
library surface, the way a `pip install`'d strategy developer interacts with Plutus. This
board is the worksheet we drive down, top to bottom, in **importance-to-users** order.

## How to read it

Two tiers of pass, per the working method:

- **Tier 1 — "it runs":** no crash; every order returns a real answer (filled OR
  rejected-with-a-reason), never an unwarranted INDETERMINATE where a real market would
  answer; the story completes. **Reportable as soon as it holds.**
- **Tier 2 — "it's right":** the outcome matches the scenario's stated intention, **and that
  intention is the documented Vietnamese rule** — the catalogue's citations are the oracle.
  Checked on user-observable outputs where possible; on internals via a privileged
  **evaluator** where the user can't see it. We do not over-expose.

The loop: *write scenario as executable → run → Tier 1 red? fix plumbing → Tier 1 green,
report → Tier 2 red? fix fidelity → Tier 2 green, banked.* **On failure we fix the
simulator, never the scenario.** The public API is **not** pinned up front — it grows
per-scenario, minimally (no more, no less), and the API failing first is the point of TDD.

**"Catalogue status"** is what the catalogue records from privileged test runs. **"User-code
status"** is the real bar — only known once the scenario is run as user-only code, which can
surface surface-gaps the privileged tests hid (J1 already did — see below).

## The board (importance-to-users order)

| # | J# | Mechanism (what a user relies on) | Catalogue status | User-code status | Blocker / note |
|--:|----|-----------------------------------|------------------|------------------|----------------|
| **Core lifecycle — every strategy hits these** |
| 1 | J1 | Settlement T+2: buy, can't sell same day, sell at T+2 13:00 | Yes | **T1 ✅ T2 ✅** | green after 1 fix (adapter root) |
| 2 | J2 | Can't buy *through* a limit-UP ceiling (band lock) | Yes | **T1 ✅ T2 ✅** | BAND_LIMIT vs BAND_LOCK; bar-proxy caveat |
| 3 | J11 | Can't sell into a floor lock (stop-loss that can't fill) | Yes | **T1 ✅ T2 ✅** | mirror of J2, sell side (DIG Oct-2022) |
| 4 | J12 | Order-type semantics: MOK vs MAK, time-in-force | Partial | **T1 ✅ T2 ✅** | core MOK≠MAK holds (SHS/HNX); 2 deviations declared |
| 5 | J17 | Round-lot dated change (2021-01-04): legal before, rejected after | Yes | **T1 ✅ T2 ✅** | round-lot verdict flips by date (FPT) |
| 6 | J9 | Thin name: cap binds, book is stale (tick/lot at the edge) | Partial | **T1 ✅ T2 ✅** | cap binds (300/5000); no-vol day INDETERMINATE; staleness → J13/J21 |
| **Fills & participation — how executable the strategy really is** |
| 7 | J20 | One strategy under hard / soft / probabilistic fill policies | Yes | **T1 ✅ T2 ✅** | spread real: hard 0 / soft 800 / prob 0 (seed 7) |
| 8 | J22 | Participation-cap sweep (1% vs 10% of volume) | Yes | **T1 ✅ T2 ✅** | fills 86.6k/259.8k/866k = cap×volume (SHS) |
| 9 | J13 | MTL sweep + residue → LO one tick beyond last match | Partial | **T1 ✅ T2 ✅** | sweeps 3 levels (73.4/73.5/73.9), 6900 filled, 43100 residue (injected book walk) |
| 10 | J21 | Queue policy: optimistic / conservative / probabilistic | Partial | **T1 ✅ T2 ✅** | queue luck: optimistic 6900 / conservative 0 / prob 5172 (injected) |
| 11 | J14 | ATO vs a marketable LO into the same auction | Blocked | **T1 ✅ T2 ✅** | ATO & LO both cross at published open 73.3 (policy-level, like J13) |
| 12 | J7 | Auction-only strategy (ATO/ATC) | Blocked | **T1 ✅ T2 ✅** | ATO→open 73.3, ATC→close 74.0 (policy-level, like J13) |
| **Margin, leverage, forced close — the dangerous mechanisms** |
| 13 | J3 | Leveraged VN30F into drawdown → call → forced liquidation | Partial | **T1 ✅ T2 ✅** | **MUST #3 BUILT** — forced liq now executes (net→0); MUST #4 (VM daily) declared pending |
| 14 | J5 | Margin-financed equity called → force-sold (bán giải chấp) | Yes | **T1 ✅ T2 ✅** | HPG margin: loan 92M → 5 calls → 21 forced sales, all executed |
| 15 | J26 | Day-trader vs overnight holder: the two margin layers | Yes | **T1 ✅ T2 ✅** | swing IM 12.285M vs day IM 0 (VN30F2212, pre-KRX) |
| 16 | J18 | VSD initial-margin change (2022-12-15): 13% → 17% overnight | Yes | **T1 ✅ T2 ✅** | IM 13.78M→18.02M, ratio 0.13→0.17, +30.8% (VN30F2301) |
| 17 | J19 | KRX cutover (2025-05-05): a different margin MODEL each side | Partial | **T1 ✅ T2 ✅** | dated model: pre_margin resolves, post-KRX raises UnresolvedRule (unsourced) |
| 18 | J6 | Roll a futures position across expiry | Yes | **T1 ✅ T2 ✅** | VN30F2212 expiry_settled → 0; VN30F2301 roll opens |
| **Corporate actions & cross-market** |
| 19 | J8 | Hold across an ex-date (price adjustment) | Partial | **T1 ✅ T2 ✅** | caller-driven CA engine: 1000→1300, ref conserved, gross cash div |
| 20 | J4 | Pair trade: VN30 basket on HSX vs VN30F on HNXDS | Yes | **T1 ✅ T2 ✅** | basket (sec cash) + short future (deposit); pools segregated |
| 21 | J15 | Sell and redeploy on ứng trước tiền bán (sale advance) | Yes | **T1 ✅ T2 ✅** | advance credits proceeds; rebuy ok w/ it, refused w/o |
| 22 | J16 | Capital turnover under T+2 (settlement as a capacity limit) | Yes | **T1 ✅ T2 ✅** | 5 round trips w/o advance → 7 with (FPT Nov-2022) |
| **Robustness, capacity, headline** |
| 23 | J27 | Amend a resting order: up, down, across the price | Yes | **T1 ✅ T2 ✅** | **MUST #2 BUILT** — amend re-runs encumbrance + admission |
| 24 | J23 | A 30-name VN30 basket (multi-ticker at scale) | Yes | **T1 ✅ T2 ✅** | 30/30 filled, per-name holdings, cash = Σ legs |
| 25 | J24 | A strategy that runs out of cash mid-run | Yes | **T1 ✅ T2 ✅** | 3rd buy refused INSUFFICIENT_CASH w/ binding constraint |
| 26 | J25 | A strategy meeting a data gap | Yes | **T1 ✅ T2 ✅** | is_clean=False at indeterminate=0; 4 blind spots named |
| 27 | J10 | Naive fill-at-close backtest vs Plutus — the delta | Yes | **T1 ✅ T2 ✅** | naive exits (holds 0); Plutus BAND_LOCK (holds 1000) |

## Infrastructure

- **Venv:** `.venv` (Python 3.12), package installed editable — `.venv/bin/pip install -e
  ".[test]"`. Run scenarios with `.venv/bin/python -m pytest scenarios/`.
- **Scenarios home:** `scenarios/` — one file per scenario as user-code (see
  `scenarios/README.md`). `PLUTUS_DATA_ROOT` points at the corpus. `scenarios/_harness.py`
  holds the shared corpus-discovery + `build_session` plumbing; scenario bodies read as a
  user's own program.

## ✅ COMPLETE — 27 / 27 scenarios Tier 2 (2026-08-28)

Every catalogue scenario runs as user code against the public library surface and its outcome
matches the cited Vietnamese rule. `.venv/bin/python -m pytest scenarios/` → **27 passed**.

**Real library builds this pass (each regression-gated on the 1,596-test market suite):**
- **MUST #2** — `amend` re-runs encumbrance + admission (amend-up re-funds, odd-lot decrease
  refused, dated priority).
- **MUST #3** — derivatives forced liquidation now **executes** (`_execute_forced_close`),
  cure-window gated.
- Adapter fix — `DataHubSource` accepts a root string so the documented `from_config` path
  wires the corpus.

**Still declared (not blockers to the suite, tracked on the checklist):** MUST #4 (VM settles
in cash daily — J3 declares VM cumulative-since-entry, A60); MUST #5 / the auction phase
source (J7/J14 are demonstrated at the policy level, like the injected book walk J13/J21 —
the session-path source that emits an auction phase is the remaining wiring); post-KRX
scenario-margin `SMrate`/`MF` values (J19 shows the model is dated and the post-KRX side
honestly raises `UnresolvedRule`).

## Data sourcing (planned — never a blocker)

The data is owned, redistributable, and ships with the product. `hermes-parquet` is a
**dev snapshot**, not the whole dataset. Where a scenario needs data the snapshot doesn't
carry, the action is to **extract a snapshot from the production or local DB**, not to call
the scenario blocked.

- **Futures (VN30F) — J3, J4, J6, J18, J19, J26 — NOT blocked, no extract needed.**
  Corrected 2026-08-27 (an earlier note here wrongly said futures needed a data extract —
  an untested assumption). `DataHubSource._resolve_instrument` resolves any `VN30F…`
  contract by prefix (kind=FUTURE, multiplier 100,000, HNXDS, third-Thursday expiry) with no
  ticker master, and the corpus **already carries** VN30F close/reference/ceil/floor/volume/
  OI/open/max/min. Verified: `BUY VN30F2212` is Accepted at HNXDS with IM reserved
  `0.13 × price × 100,000`. The only gap is `quote_settlementprice` (empty in the snapshot),
  so the daily settlement/VM uses **close as settlement** — a documented approximation, not a
  blocker. These scenarios need *building*, not data.
- **Pre-2023 order-book depth** — for the book-walk scenarios (J13 sweep, J21) — lives in
  the local `quote` DB (render `Europe/Helsinki`). `hermes-dev-extract` already carries a
  slice; widen it as needed.

Credential + DB details are in memory (`production-db-access`, `local-quote-db-timezone`,
`data-is-available-and-shareable`).

## Status

- **J3 — DONE, Tier 1 + Tier 2 green, via a real library build (MUST #3).** The derivatives
  forced liquidation now **executes**: `exchange.py::_execute_forced_close` submits real
  offsetting orders through the order path (band/tick/lot/fill policy), priced at the band
  edge so they fill on a tradeable day and are refused `BAND_LOCK` on a locked one — the
  measured 17.6% permissive cost the report alone hid. The cure window is honoured (QĐ 26
  Điều 13.3): the first mark that reports FORCED only reports; the breach persisting past it
  executes (gated on `in_forced_breach` latched before the mark). Verified: leveraged VN30F
  long → margin call → forced liquidation `executed=True`, position net→0. **1,596 market
  tests pass**; the three tests that pinned the Tier-1 non-execution pass unchanged because
  they end on the first (cure-window) forced mark. **MUST #4** (VM settles in cash daily,
  A60) is a separate semantic change that ripples through the derivatives tests — declared
  pending, VM is reported cumulative-since-entry. `scenarios/test_j3_forced_liquidation.py`.
- **J27 — DONE, Tier 1 + Tier 2 green, via a real library build (MUST #2).** `amend` now
  re-runs the encumbrance and admission: an amend-up grows the reservation (70M → 105M) or is
  refused `INSUFFICIENT_CASH`; a price amendment is re-checked against the band; a decrease
  onto an odd lot is refused `ROUND_LOT`; priority follows the dated rule. Built in
  `exchange.py::amend` (re-admission + reservation swap with rollback) + `orders.py::amend`
  (stores the fresh encumbrance) + `_priority_preserving_at`. **1,596 market tests pass**;
  the one obsolete Tier-1 test (`test_amending_upward_is_refused_as_a_tier_boundary`) was
  updated to the new contract. `scenarios/test_j27_amend.py`.
- **J1 — DONE, Tier 1 + Tier 2 green.** `scenarios/test_j1_settlement.py`. Run as pure user
  code (`from plutus.market.session import ExchangeSession`; `from_config`; `submit`;
  `advance_to`). Same-day sell refused with `UNSETTLED_HOLDING`, `sellable_from = T+2 13:00`;
  T+2 sell accepted. Passes standalone and under pytest. Every check was user-observable — no
  evaluator needed.
- **J2 — DONE, Tier 1 + Tier 2 green.** `scenarios/test_j2_limit_up_lock.py`. HPG 2022-11-16
  limit-up lock: a buy *above* the ceiling → `Rejected(BAND_LIMIT)` (illegal price), a buy
  *at* the ceiling → `Rejected(BAND_LOCK)` with `lock_evidence='bar_proxy'` (legal price,
  locked book). The two distinct refusals are the teaching point. **No simulator change** —
  the shipped model already matched the rule; the scenario's first assertion was my wrong
  guess (accept-then-no-fill), corrected to the documented entry refusal. Bar-proxy
  over-assertion is declared in the scenario docstring.
  - **One plumbing fix it forced:** the shipped daily adapter (`DataHubSource`) could not be
    wired from a config file — `load_data_source` hands the class the `data.root` string, but
    the class wanted a `DataHubConfig` and `for_root` (the string-taking constructor) can't be
    named by a dotted path. Fixed by letting `DataHubSource.__init__` accept a root string.
    35 adapter tests still pass. This is the kind of surface-gap only *user-code* runs find.

## The five MUST items, as scenario failures

The publish checklist's MUST list is just "which scenarios are red," and the board shows it:
MUST #1 (order-book walk) gates the **sweep** half of J13 and J21; MUST #2 (amend re-runs
encumbrance/admission) is J27; MUST #3/#4 (forced liquidation executes / VM settles) are J3;
the auction phase data path is J14 and J7. Driving those scenarios green *is* clearing the
release gate.
