# Plutus Scenario Reference (Jx)

**Version 1.0 · 2026-08-30.** Cite as *"Plutus Scenario Reference, J⟨n⟩"*.

The Jx suite is Plutus's **acceptance specification**: 37 files / 38 tests, each an
*executable test written as a user would write it* — reproducible code against the
public library surface. Each scenario is a **demo** (what the library does) paired
with a *Broken looks like* (the wrong output a naive backtest gives). Pass has two
tiers: **T1** "it runs" (no crash; every order a real answer; no unwarranted
INDETERMINATE) and **T2** "it's right" (the outcome matches the documented
Vietnamese rule). **On failure the simulator is fixed, never the scenario.**

**All 38 tests are green (2026-08-30).** The **Path** column records how a scenario
reaches its mechanism on the default config-driven session over the wired corpus —
`session` (the default path), `direct` (driven by injection because the default
path lacks a data source, e.g. an auction phase), or `extract` (needs the
dev-extract book/tape). Path is a *claimability* note, **not** a pass/fail.

**Sourcing labels** (the oracle is the dated rulebook, `vn-exchange-rulebook-2020-2026.md`):
`sourced` (a cited Vietnamese rule), `our-choice` (a modelling decision with no
rule), `sourced-absence` (the document was read and the thing is not in it — itself
a finding). Verbatim article citations and confidence grades live in
`SCENARIO-CATALOGUE.md` (J1–J27) and the intraday design specs (J28–J37); this
reference is the stable index into them.

## Index

| J# | Name | Validates | Path | T2 |
|----|------|-----------|------|:--:|
| J1 | T+2 settlement | can't sell before T+2 13:00 | session | ✅ |
| J2 | Limit-up lock | BAND_LIMIT (illegal) vs BAND_LOCK (legal, unfillable) | session | ✅ |
| J3 | Leveraged VN30F liquidation | call → forced liquidation executes → daily VM | session | ✅ |
| J4 | Pair trade | basket (T+2 cash) + short future (deposit), pools segregated | session | ✅ |
| J5 | Margin-financed equity | called → forced sale *executes* (bán giải chấp) | session | ✅ |
| J6 | Futures roll | roll across expiry; daily VM (settlement error +0.042%) | session | ✅ |
| J7 | Auction-only | buy the open cross, sell the close cross | direct | ✅ |
| J8 | Ex-date | reference adjustment + quantity scaling | session¹ | ✅ |
| J9 | Thin name | participation cap binds; stale book | extract | ✅ |
| J10 | Naive vs Plutus | the fill-at-close delta (the headline) | session | ✅ |
| J11 | Floor-lock stop | a stop that cannot fill (no market-at-floor order exists) | session | ✅ |
| J12 | MOK vs MAK | fill-or-kill vs immediate-or-cancel | session² | ✅ |
| J13 | MTL residue | market residue rests as an LO one tick beyond last | session² | ✅ |
| J14 | ATO vs marketable LO | both clear at one opening cross | direct | ✅ |
| J15 | Sale advance | redeploy sale proceeds before T+2 (*ứng trước tiền bán*) | session | ✅ |
| J16 | T+2 turnover | settlement caps capital turnover | session | ✅ |
| J17 | Round-lot change | 50 shares legal 2020-12-31, rejected 2021-01-05 | session | ✅ |
| J18 | VSD IM change | 13% → 17% (2022-12-15): +30.8%, zero price move | session | ✅ |
| J19 | KRX cutover | a different margin *model* each side of 2025-05-05 | session² | ✅ |
| J20 | Fill-policy spread | one strategy under soft/hard/probabilistic | session | ✅ |
| J21 | Queue-policy spread | optimistic/conservative/probabilistic | extract | ✅ |
| J22 | Participation sweep | fills scale as cap × volume (1/3/10%) | session | ✅ |
| J23 | 30-name basket | per-name encumbrance/settlement, cash = Σ legs | session | ✅ |
| J24 | Out of cash | 3rd buy refused INSUFFICIENT_CASH, binding constraint | session | ✅ |
| J25 | Ignorance meter | an unknown is reported (`is_clean`), not guessed | session | ✅ |
| J26 | Day vs swing trader | two margin layers/engines/price series | session | ✅ |
| J27 | Amend a resting order | amend re-runs encumbrance + admission (MUST #2) | session | ✅ |
| J28 | Book-walk taker | marketable BUY fills at the resting ask level | extract | ✅ |
| J29 | Queue by config | same order, three fills, each stamped in provenance | extract | ✅ |
| J30 | Book sweep | one fill per ask level at each level's own price | extract | ✅ |
| J31 | Stale book | a staleness budget refuses a fill on an old book | extract | ✅ |
| J32 | Maker fill (tape) | a resting order fills as trades print through it | extract | ✅ |
| J33 | Maker queue spread | optimistic 6000 / conservative 1000 / prob 2500 | extract | ✅ |
| J34 | Maker, no trade | a *definite* no-fill (served-but-empty tape) | extract | ✅ |
| J35 | Maker, unseen tape | INDETERMINATE naming VOLUME (unserved) | extract | ✅ |
| J36 | Tape integrity | sized tape = `quote.total` deltas (matchedvolume is lossy) | extract | ✅ |
| J37 | Tick-path ATC | returns the published close, not a stale last (MUST #5) | extract | ✅ |

¹ J8's corporate-action engine is caller-driven (a CA feed is exogenous), invoked
through `apply_corporate_action`. ² J12 declares two deviations; J13's *sweep* half
and J19's post-KRX grid are demonstrated off the default path / raise
`UnresolvedRule` where unsourced.

## Entries by theme

### Admission — band / lot / grid / order-type / session
- **J1 — T+2 settlement.** Buy, refused same-day sell (`UNSETTLED_HOLDING`, carries
  `sellable_from` = T+2 13:00), legal at T+2. *sourced.*
- **J2 — Limit-up lock.** Distinguishes `BAND_LIMIT` (price above the ceiling —
  illegal, rejected regardless of book) from `BAND_LOCK` (legal at the ceiling, no
  ask below — admissible, unfillable). HPG 2022-11-16. *sourced;* ships a measured
  bar-proxy lock over-assertion.
- **J11 — Floor-lock stop.** A stop-loss that cannot fill: no synthetic
  market-at-floor order exists in Vietnam at any date. *sourced-absence.*
- **J12 — MOK vs MAK.** Fill-or-kill vs immediate-or-cancel on HNX/HNXDS. *sourced;*
  two declared deviations (decided one interval late; `NO_OPPOSITE_ORDER` unraised).
- **J13 — MTL residue.** Market residue converts to an LO one tick beyond the last
  match, capped at the band. *sourced* (conversion, default path); the multi-level
  sweep is `extract`.
- **J14 — ATO vs marketable LO.** Both clear at one opening cross; the ATO remainder
  auto-cancels, the LO carries. *our-choice* (the cross price is the published open).
- **J15 — Sale advance (*ứng trước tiền bán*).** Redeploy sale proceeds before T+2;
  statutory permission (Luật CK 54/2019 Điều 86) split from broker commercial terms.
- **J16 — T+2 turnover.** Settlement, not commission, caps turnover (5 round trips
  without the advance, 7 with).
- **J24 — Out of cash.** The 3rd buy is refused `INSUFFICIENT_CASH` with the binding
  constraint named.

### Dated rule editions (the paper's lead claim — same order, two dates, two answers)
- **J17 — Round-lot change (2021-01-04).** A 50-share order legal on 2020-12-31,
  rejected `ROUND_LOT` on 2021-01-05. *sourced* (QĐ 894). The cleanest demo.
- **J18 — VSD initial-margin change (2022-12-15).** Same 1-lot VN30F, IM 13% → 17%
  (13.78M → 18.02M, **+30.8%**) with zero price move. *sourced* (issued as a *thông
  báo*, no *quyết định* number).
- **J19 — KRX cutover (2025-05-05).** A different margin *model* each side
  (`MR = IM+VM` pre vs `MR = Max(ΣPgm,0)` post). *sourced;* the post-KRX side
  honestly raises `UnresolvedRule` on unsourced params.

### Uncertainty band (no Vietnamese rule underneath — "the output *is* the error bar")
- **J20 — Fill-policy spread.** One strategy under soft/hard/probabilistic; the
  spread is the error bar. *our-choice.*
- **J21 — Queue-policy spread.** Optimistic/conservative/probabilistic. *our-choice.*
- **J22 — Participation sweep.** Fills scale as cap × volume across 1/3/10%.

### Derivatives — margin, leverage, forced close
- **J3 — Leveraged VN30F liquidation.** Into the Oct-2022 drawdown → call → forced
  liquidation (executes, net→0) → daily VM cash settlement. *sourced* (QĐ 26).
- **J5 — Margin-financed equity.** Called → force-sold (*bán giải chấp*); the forced
  sale **executes** (refused `BAND_LOCK` on a locked day, the loss the client is
  obliged to suffer).
- **J6 — Futures roll.** Roll a position across expiry; clearest daily-VM exhibit
  (close-as-settlement error bar +0.042% mean absolute over 46 post-cutover expiries).
- **J26 — Day vs swing trader.** Flat-by-close vs overnight: two margin layers,
  engines, and price series.

### Corporate actions, cross-market, robustness, headline
- **J4 — Pair trade.** VN30 basket on HSX (cash, T+2) vs short VN30F on HNXDS
  (deposit), one ledger, two regimes/clocks, pools segregated.
- **J8 — Ex-date.** Reference adjustment + quantity scaling. The adjustment algebra
  is **market practice, not gazetted** — MARK IN PAPER. *our-choice / caller-driven.*
- **J9 — Thin name.** The participation cap binds (300/5000) and the book goes stale.
- **J23 — 30-name basket.** Per-name encumbrance/settlement; cash = Σ legs; 30/30.
- **J25 — Ignorance meter.** An unknown is reported INDETERMINATE, not guessed; use
  `is_clean`, not the indeterminate count.
- **J27 — Amend a resting order (MUST #2).** Amend re-runs encumbrance + admission
  (re-fund or refuse; band re-check; odd-lot decrease refused; dated priority).
- **J10 — Naive vs Plutus (the headline).** Same window/data/strategy: the naive
  fill-at-close delta is the value proposition, reported as a **lower bound**.

### Intraday extension — book-walk / queue / maker / tape / tick (J28–J37, through the session)
- **J28 — Book-walk taker.** A marketable BUY fills at the resting ask level, not a
  bar close; provenance names `book_walk` + queue. *sourced* (QĐ 352 Điều 6.3).
- **J29 — Queue by config.** Same order, three fills (optimistic/conservative/
  probabilistic), each stamped in `SessionProvenance`.
- **J30 — Book sweep.** One fill per ask level at each level's own resting price;
  cash < worst-price × qty; fills are `MODELLED`.
- **J31 — Stale book.** A staleness budget refuses a fill on a ~30-min-old book
  (stays live, not rejected); removing the budget fills it.
- **J32 — Maker fill (tape).** A resting SELL fills as trades print through at its own
  price (`MODELLED`) while the best bid never reaches it; no double-book across
  advances.
- **J33 — Maker queue spread.** SELL 6000 with 5800 ahead, 6800 printed → optimistic
  6000 / conservative 1000 / probabilistic 2500. The queue assumption *is* the spread.
- **J34 — Maker, no trade.** A definite no-fill (served-but-empty tape = knowledge);
  rests full; ignorance stays clean. *The epistemic opposite of J35.*
- **J35 — Maker, unseen tape.** INDETERMINATE naming VOLUME (unserved tape); stays
  live — same zero fills as J34, opposite epistemic status.
- **J36 — Tape integrity.** The sized tape from `quote.total` deltas sums to the day's
  real volume; `matchedvolume` is lossy (~40% short) and deliberately not used.
- **J37 — Tick-path ATC.** Returns the published close, not the stale pre-auction
  `last` (fixes defect D71 = MUST #5). *sourced.*

## The five MUST items (the publish gate) — all landed
**#1** order-book walk (J13 · J28 · J30) · **#2** amend re-runs encumbrance (J27) ·
**#3** forced liquidation executes (J3 · J5) · **#4** VM settles in cash daily
(J3 · J6 · J26) · **#5** tick-path close-as-ATC (J37).

*Full detail: `SCENARIO-CATALOGUE.md` · worksheet + history: `SCENARIO-BOARD.md` ·
tests: `scenarios/test_j⟨n⟩_*.py`.*
