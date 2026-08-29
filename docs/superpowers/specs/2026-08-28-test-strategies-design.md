# Test strategies — the end-to-end fidelity layer

**Status:** design, awaiting author review · 2026-08-28
**Goal it serves:** *a high-fidelity Vietnamese exchange + broker that others can use to validate their methods.*
**Relationship to prior work:** this is the layer above `scenarios/` (the 27 catalogue scenarios,
`docs/reference/SCENARIO-CATALOGUE.md`, all Tier-2 green). Same two-tier discipline, same
oracle (the catalogue's citations), same rule — *on failure we fix the simulator, never the test.*

---

## 1. Why strategies, when scenarios already pass

A **scenario** stages one rule and pokes it: it sets utilisation to 0.91 and checks that a call
fires. A **strategy** makes the same moment **emerge from P&L against real corpus data**: it holds
a real position that loses real money on a real bad day, and the call fires because the loss
actually crossed the threshold. That is a strictly stronger fidelity claim — the system holds up
when someone *trades* it, not only when we poke each rule in isolation.

Two classes of check exist **only** when something trades for months, and no scenario is long
enough to reach them:

- **Emergence** — the stress event fires at the *right time for the right reason*. The margin call
  lands on the day the corpus says the loss breached the threshold, not on a day we chose.
- **Conservation** — every đồng reconciles across the whole run. Over thousands of steps the books
  must balance: `starting cash = ending cash + position market value + realised P&L − charges −
  interest ± margin flows`. A scenario never runs long enough to break this; a strategy breaks it
  the first time an accounting seam leaks.

If the seven strategies below reach Tier 2, we can say the system is faithful *as a place to
trade*, which is the thing the goal actually promises.

---

## 2. The runtime — a test-side harness (decided)

The strategy "core" (the day-loop that steps `advance_to` and dispatches to a strategy's
signal/entry/exit) lives **test-side**, in `strategies/_harness.py`. It is **not** part of the
shipped library. Rationale: the library is the *market* (the counterparty across the table); a
real user brings their own strategy framework. Shipping a runner would make the library both sides
of the table and quietly turn it into a backtest engine — out of scope for the goal. The harness
stands in for "the user's own framework," exactly as `scenarios/_harness.py`'s `build_session`
stands in for their config loader.

The library surface a strategy uses is exactly what a `pip install`'d user gets (surveyed
2026-08-28, `exchange.py`): `advance_to(ts)` · `submit(order)` · `cancel` · `amend` · `orders()` ·
`poll()` · `cash()` · `positions()` · `holdings(ticker)` · `margin()` · `outstanding_call()` ·
`in_forced_breach()` · `charges()` · `transfer()` · `indeterminate_report()` · `provenance()` ·
`attach_equity_margin()` · `overnight_margin()`. There is **no** `Strategy`/`Portfolio` in the
library (`core/portfolio.py` is a vestigial stub) — the session *is* the source of truth for cash
and positions; the strategy only holds its own intent.

Illustrative shape (the plan phase fills in the real code):

```python
# strategies/_harness.py  — TEST-SIDE, not shipped. This is "their framework".

class Strategy(Protocol):
    def on_start(self, session): ...
    def on_event(self, session, event): ...   # react to fills, calls, forced closes
    def on_day(self, session, day): ...        # end-of-day decision: read truth, submit
    def on_finish(self, session): ...

def run(session, strategy, *, start, end):
    strategy.on_start(session)
    for day in trading_days(start, end):
        for ts in marks_for(day):              # open … past 14:45 determination … close
            for e in session.advance_to(ts):   # events the market emits
                strategy.on_event(session, e)
        strategy.on_day(session, day)          # decide with same-day truth
    strategy.on_finish(session)
    return RunLedger(session)                  # equity curve + the conservation reconciliation
```

Two grounded harness details (from scenario work): the day loop **must advance past the
derivatives determination time** (`DEFAULT_DETERMINATION_TIME = 14:45`) each day or the margin
lifecycle never runs; and `RunLedger` computes the conservation reconciliation and the
privileged-evaluator internal checks **test-side**, reading the session's truth — the same "don't
expose everything through the public API" evaluator pattern the scenarios use.

---

## 3. Two tiers, for strategies

- **Tier 1 — it runs.** The loop completes the whole window without crashing; every order gets a
  real answer (filled or rejected-with-a-reason); no unwarranted INDETERMINATE where a real market
  would answer; the equity curve is produced.
- **Tier 2 — it's right.** Three things hold together:
  1. **Emergence** — the stress event fires on the correct day for the documented reason (the
     catalogue's citations remain the oracle).
  2. **Conservation** — the books reconcile to the đồng across the full run.
  3. **Internal correctness** — the privileged evaluator's internal invariants hold (e.g. the
     forced close priced at the band edge, the VM measured the way the rule says).

On any Tier-2 failure we fix the simulator, never the strategy.

---

## 4. The board — seven strategies

**S1 is the author's worked example.** Ranked by importance to users (S1 the crown jewel).
Each folds in a cluster of scenarios so the whole board covers all 27 (matrix in §5).

### S1 — Front-month VN30F mean-reversion that over-levers into a call
- **Core.** z-score of VN30F front-month around a rolling mean; enter when |z| > k, **size scales
  with conviction** so inventory accumulates; exit on reversion or a stop; **roll** at expiry.
- **Emergent stress.** On a trending day the strategy is positioned the wrong way; VM losses
  compound day over day; deposit utilisation climbs → warning → **margin call** → cure window
  lapses → **forced liquidation at the band edge**, filled same-determination.
- **Folds in.** J3 (forced liquidation), J6 (roll), J13 (MTL entry sweep), J18 (margin change),
  J24 (deposit out-of-cash), J26 (margin layers).
- **Tier 2.** The call fires the day cumulative VM crosses the threshold in the corpus; the forced
  close executes at `state.floor`/`state.ceiling`; deposit + VM + realised P&L reconcile.
- **Library pressure.** Exercises the just-built MUST #3 (forced close executes) under a real P&L
  path; pressures **MUST #4** (VM should settle in cash daily, currently cumulative-since-entry, A60).

### S2 — Equity trend-follow on a large-cap, on margin, locked out then called
- **Core.** Breakout/trend entry on a liquid large-cap with add-on-strength; funded by **equity
  margin lending** (imr 50% / mmr 30%); exit on trend break.
- **Emergent stress.** A **limit-up day locks the book** so the add can't fill (`BAND_LOCK`); a run
  of down days breaches mmr → **forced sale executes**, which itself lands on a **floor-lock** day
  (can't exit into the lock); **T+2 settlement** gates re-entry with the proceeds.
- **Folds in.** J1 (settlement), J2 (limit-up lock), J5 (equity margin), J11 (floor-lock exit),
  J16 (capital turnover), J24 (out of cash).
- **Tier 2.** The margin call fires on the corpus day equity/mmr breaches; the forced sale is
  refused on the lock day and completes when the lock clears; cash + holdings + margin debt balance.

### S3 — VN30 basket vs future (index-arb) tripped by an ex-date and thin legs
- **Core.** Basket fair value vs VN30F; on divergence, long the 30-stock basket / short the future
  (or vice versa); rebalance; unwind on convergence.
- **Emergent stress.** A constituent goes **ex-dividend/ex-rights** mid-hold (reference adjusts,
  basket mark jumps, resting-order fate across the ex-date); a **round-lot change** un-rounds the
  basket; **thin constituents hit the participation cap** so the basket can't be assembled at once;
  equity-T+2 vs futures-T+1 opens a financing gap.
- **Folds in.** J4 (pair), J8 (ex-date), J9 (thin name), J17 (round-lot change), J22 (participation
  cap), J23 (VN30 basket).
- **Tier 2.** The ex-date adjustment moves the mark by the A26 arithmetic; the un-round leg is
  refused `ROUND_LOT`; the capped leg fills partially; both legs' cash and the futures VM reconcile.

### S4 — Auction market-on-close rebalancer
- **Core.** Trade only the auctions: accumulate a target book via **ATO**, liquidate via **ATC**,
  **MOK/MAK** top-ups in continuous.
- **Emergent stress.** To run on the *session path* this needs a source that **emits an auction
  phase** — currently absent (the daily adapter stamps every bar CONTINUOUS). And a real
  close-trader is **wrong under D71** (on a tick run an ATC fills at a stale `state.last`, not the
  published close). S4 is the forcing function that makes both user-visible.
- **Folds in.** J7 (auction-only), J12 (MOK vs MAK), J14 (auction cross).
- **Tier 2.** ATO fills at the published open, ATC at the published close, on the session path.
- **Library pressure.** Expects a **new build**: the auction-phase source (MUST #5) and the D71
  one-condition fix (ATC returns the published close, or INDETERMINATE when absent).

### S5 — High-turnover intraday scalper recycling sale proceeds
- **Core.** Reversal signal on a liquid name; each sale's proceeds are **advanced** (ứng trước tiền
  bán) and immediately redeployed, turning capital over many times per day.
- **Emergent stress.** Turnover butts against **T+2** (unsettled cash unusable without the advance);
  the **advance accrues interest** (a real cost drag on the equity curve); a **data gap** forces
  INDETERMINATE mid-day; advance headroom exhausts → **out of cash**.
- **Folds in.** J1 (settlement), J15 (sale advance), J16 (capital turnover), J24 (out of cash),
  J25 (data gap).
- **Tier 2.** Redeployed proceeds trace to advanced tranches; accrued interest appears in the P&L;
  the gap day is INDETERMINATE not a crash; end-of-run cash reconciles including interest paid.

### S6 — The regime-straddle across the KRX cutover (2025-05-05)
- **Core.** S1's futures core, but the window **crosses 2025-05-05**, so the same position is
  margined by two different **models**, order-amend rules flip, order types change (LO/MP →
  LO/MTL).
- **Emergent stress.** The strategy hits the **dated rulebook**: pre-KRX `MR = IM + VM` resolves;
  post-KRX the margin model honestly **raises `UnresolvedRule`** (unsourced) rather than pretending
  to be pre-KRX; an amend is **forbidden** post-KRX. The system must not silently claim nothing
  changed.
- **Folds in.** J18 (margin change), J19 (KRX cutover), J27 (amend).
- **Tier 2.** Pre-KRX side runs live and reconciles; the boundary behaviour (edition flip, honest
  raise, amend refusal) is asserted through the public surface.
- **Open item.** Corpus coverage past 2025-05-05 is unconfirmed — see §6. If absent, S6 runs the
  pre-KRX side live and asserts the post-KRX behaviour at the rulebook/edition level (as J19 does),
  without fabricating post-cutover prices.

### S7 — Fidelity-sensitivity harness (one strategy, many policies)
- **Core.** Run S1 or S5 **unchanged**, swept across fill policy (naive/soft/hard/probabilistic) ×
  queue policy (optimistic/conservative/probabilistic) × participation cap.
- **Emergent stress.** Not a market stress — a **methodological** one: how much of the equity curve
  is microstructure luck versus signal. This is the value proposition of a high-fidelity sim made
  measurable ("naive fills lied to you").
- **Folds in.** J10 (naive vs plutus), J13 (MTL sweep), J20 (fill-policy spread), J21 (queue
  policy), J22 (participation cap).
- **Tier 2.** The policies disagree on P&L in the documented direction (naive ≥ hard ≥
  conservative); probabilistic is reproducible under a fixed seed; the spread is reported, not
  hidden.

---

## 5. Coverage matrix — all 27 scenarios folded in

| Scenario | S1 | S2 | S3 | S4 | S5 | S6 | S7 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| J1 settlement | | ● | | | ● | | |
| J2 limit-up lock | | ● | | | | | |
| J3 forced liquidation | ● | | | | | | |
| J4 pair trade | | | ● | | | | |
| J5 equity margin | | ● | | | | | |
| J6 futures roll | ● | | | | | | |
| J7 auction-only | | | | ● | | | |
| J8 ex-date | | | ● | | | | |
| J9 thin name | | | ● | | | | |
| J10 naive vs plutus | | | | | | | ● |
| J11 floor-lock exit | | ● | | | | | |
| J12 MOK vs MAK | | | | ● | | | |
| J13 MTL sweep | ● | | | | | | ● |
| J14 auction cross | | | | ● | | | |
| J15 sale advance | | | | | ● | | |
| J16 capital turnover | | ● | | | ● | | |
| J17 round-lot change | | | ● | | | | |
| J18 margin change | ● | | | | | ● | |
| J19 KRX cutover | | | | | | ● | |
| J20 fill-policy spread | | | | | | | ● |
| J21 queue policy | | | | | | | ● |
| J22 participation cap | | | ● | | | | ● |
| J23 VN30 basket | | | ● | | | | |
| J24 out of cash | ● | ● | | | ● | | |
| J25 data gap | | | | | ● | | |
| J26 margin layers | ● | | | | | | |
| J27 amend | | | | | | ● | |

Every scenario is folded into at least one strategy; the heavily-loaded ones (J13, J16, J18, J22,
J24) into two, so a regression shows up in more than one place.

---

## 6. Open items to resolve at implementation (not now)

1. **Pin instruments + windows from the corpus.** VN30F front-month + FPT are confirmed present
   (scenario work). The basket-of-30 (S3), a genuinely thin name (S3, its J9 leg), a data-gap window (S5),
   and the KRX-cutover window (S6) must be **located in the corpus, not invented**. "Run the thing
   before declaring a gap" applies.
2. **S6 post-KRX coverage.** Confirm whether corpus data extends past 2025-05-05. If not, S6's
   post-KRX side is asserted at the rulebook/edition level (§4, S6 open item) — never with fabricated
   prices.
3. **Exact conservation invariant.** Nail the precise reconciliation identity per instrument class
   (equity T+2 vs futures daily VM vs advance interest) so `RunLedger` checks the right equation.
4. **Durable artifacts.** At build time, mirror the scenario docs: a `STRATEGY-BOARD.md`
   (worksheet: status, build order, T1/T2 per strategy) and per-strategy files `strategies/test_s<n>_<slug>.py`,
   each runnable standalone and under pytest, skipping cleanly without the corpus.

---

## 7. Build order

By importance to users, and so each build unblocks the next check:

1. **Harness** (`_harness.py` + `RunLedger` + conservation reconciliation) — nothing runs without it.
2. **S1** — the crown jewel; the full derivatives margin lifecycle, emergent. Also the MUST #4 forcing function.
3. **S2** — equity margin + bands + settlement.
4. **S5** — cash/settlement/advance subsystem.
5. **S3** — multi-leg coherence + corporate actions (the hardest).
6. **S7** — execution-realism made measurable (reuses S1/S5, no new market mechanics).
7. **S4** — expects the new auction-phase source + D71 fix; sequenced where a real build is in scope.
8. **S6** — the regime straddle; depends on S1 and on the §6 coverage answer.
