# Strategy board — the end-to-end fidelity suite

The worksheet for `strategies/` (design: `docs/superpowers/specs/2026-08-28-test-strategies-design.md`).
Seven **real, documented trading strategies**, each written the way a `pip install`'d user writes
one — a signal, entry/exit rules, position/cash management — run against Plutus as the counterparty.
Where a scenario *stages* a rule, a strategy makes the same moment **emerge from P&L against real
corpus data**. Same two tiers, same oracle (the catalogue citations), same rule: **on failure we
fix the simulator, never the strategy.**

## Two tiers
- **T1 — it runs:** the loop completes the whole window, no crash, every order gets a real answer,
  no unwarranted INDETERMINATE, the equity curve is produced.
- **T2 — it's right:** the stress event fires on the correct day for the documented reason
  (**emergence**), the books reconcile to the đồng across the run (**conservation**), and the
  privileged-evaluator internal invariants hold (**internal correctness**).

## Board

| # | Strategy | Emergent stress | Folds in | T1 | T2 | Library pressure |
|---|---|---|---|:--:|:--:|---|
| **S1** | VN30F front-month mean-reversion | over-levers into a trend → daily cash settlement depletes the deposit past the call rung → forced liquidation (no intermediate call) | J3 J13* J18 J24 J26 · J6 next | ✅ | ✅ | passed on the existing library |
| **S2** | Leveraged equity momentum | stop can't clear a limit-down lock → mmr breach → forced sale | J5 J11 J24 · J1 J16 impl · J2 next | ✅ | ✅ | passed on the existing library |
| **S3** | VN30 basket vs future (index-arb) | carried across a constituent ex-date; two pools at once | J4 J8 J23 · J9 J17 J22 next | ✅ | ✅ | **BUILT** `apply_corporate_action` |
| **S4** | Auction market-on-close rebalancer | ATO@open, ATC@close, through the session; 0 continuous fills | J7 J14 · J12 next | ✅ | ✅ | **BUILT** `AuctionAwareDataHubSource` |
| **S5** | High-turnover advance scalper | throttled by T+2 without the advance; the advance costs a fee | J15 J16 J24 · J1 impl · J25 next | ✅ | ✅ | passed on the existing library |
| **S6** | Regime-straddle across KRX cutover | trades live pre-KRX; refuses post-KRX (model unsourced) | J18 J19 · J27 in scen. | ✅ | ✅ | pre-KRX live; post-KRX at rulebook level |
| **S7** | Fidelity-sensitivity harness | S1's history is −76% or 0% purely by fill policy | J10 J20 · J13 J21 J22 in scen. | ✅ | ✅ | passed on the existing library |

Every one of the 27 scenarios is folded into ≥1 strategy (matrix in the design doc §5).

## Build order (by importance to users)
1. **Harness** (`_harness.py`) — Strategy protocol + `run()` day-loop + `RunLedger`/conservation.
2. **S1** — the crown jewel; the full derivatives margin lifecycle, emergent. It was the MUST #4 forcing function, and **that build has landed** (2026-08-29): under daily cash settlement S1 now reaches a forced close directly, the call rung jumped.
3. **S2** · 4. **S5** · 5. **S3** · 6. **S7** · 7. **S4** (expects the auction build) · 8. **S6**.

## Status log
- **2026-08-28** — Board opened. Design approved. VN30F2212 series pulled from the corpus; a
  mean-reversion contrarian confirmed (offline) to over-lever into the Oct-2022 slide and cross the
  forced-liquidation threshold — the emergent bust is real, not staged.
- **2026-08-28** — **Harness landed** (`_harness.py`: `CorpusFeed`, `Strategy`, `run`, `RunLedger`).
  **S1 Tier 2 GREEN**, and — notably — **on the existing library, no `src/` change needed**. A real
  10-day mean-reversion contrarian on VN30F2210 (40M deposit) built a long from the signal,
  over-levered to 2 lots into the Oct-2022 slide, and the margin lifecycle fired *emergently*:
  `warning` → `margin_call` (Sep 21, util 0.922) → de-levered/cleared → `call` again (Oct 7) →
  **`forced_liquidation`** (Oct 10, uncured), closing the position. Equity 40M → 9.4M (−76%). The
  only correction was in the *strategy's own* execution — a marketable limit fills at its aggressive
  price (paid limit-up); a real taker sends a market order (MTL), which fills at the print. That is
  the fidelity lesson S1 exists to teach, not a library defect.
  * `J13*` — the market-order *take* is exercised; the multi-level book *sweep* is S7's job (no book
    depth on daily bars). `J6` (the front-month roll) is S1's next movement, not yet built.
  * Deeper conservation — VM settling in cash daily, **MUST #4** — was a refinement then and
    **has since landed (2026-08-29)**: `settle_daily` is wired into `exchange._overnight_margin`,
    so the deposit now moves by realised P&L every settlement day. Under it, S1 no longer takes
    the Oct-7 second call shown above — the daily cash depletion carries utilisation **straight
    past the call rung to a forced close** (deposit.py's MarginMonitor: "a jump straight past the
    call level reports FORCED without inventing an intermediate call"). S1 stays GREEN. S1's
    Tier-2 conservation check (deposit never impossible, drawdown real) holds.
- **2026-08-28** — **S2 Tier 2 GREEN**, again **on the existing library**. A leveraged (1.8:1)
  momentum strategy on DIG (HSX) using the real `EquityMarginAccount`: the breakout signal drew a
  loan, DIG's −71% slide eroded the maintenance ratio, **10 margin calls** issued, and the broker
  force-sold — equity 100M → 13.6M (−86%). The J11 finding, investigated and **confirmed correct**:
  the forced sale was **instructed 25× but completed only 3×**, because DIG's **14 limit-down-lock
  days** repeatedly refused the sale (`lock_evidence='bar_proxy'`) — the account bled *because it
  could not get out*. Proven directly by `test_s2_forced_sale_is_blocked_by_a_downlock` (a sale into
  a DN-LOCK is refused, the same sale on a tradeable day accepted — the sell-side symmetry of J2).
  Two units fixes learned (corpus prices are ×1000 đồng; a market order MTL takes liquidity at the
  print). `J2` (a *buy* refused on a limit-up lock) is a quick companion to add next.
- **2026-08-28** — **S5 Tier 2 GREEN**, again **on the existing library**. The same high-turnover
  rotation strategy on FPT run twice, with and without the sale advance (*ứng trước tiền bán*):
  **with** it the book turns over more and accrues a **545,624đ fee** (J15 — the price of the
  advance); **without** it the strategy is **throttled 4 days** by proceeds frozen under T+2, unable
  to redeploy (J16/J24), and carries no fee. The advance's economic effect emerges from a running
  strategy, not a staged rebuy. Fixed a harness `equity()` bug (count unsettled shares; scale equity
  MV ×1000). Known rough-MTM gap: `equity()` doesn't net the advance/pending-proceeds receivable, so
  the reported trough on a selling strategy is cosmetic — the Tier-2 verdict rests on the
  throttle/fee metrics, not the curve. `J25` (a data gap → INDETERMINATE) not exercised (FPT is
  gap-free in-window); a follow-up.
- **2026-08-28** — **S3 Tier 2 GREEN — the first strategy to force a real library BUILD.** A
  market-neutral basket-vs-future (HPG/SSI/MBB long + VN30F2212 short) carried across an HPG
  ex-dividend. The session had **no** corporate-action entry point (the engine only reached a raw
  `SecuritiesAccount`), so a strategy holding a basket in a *session* could not apply an ex-date at
  all — the exact "missing feature → build it, don't mock" case. Built
  **`ExchangeSession.apply_corporate_action(action, ts=...)`** (new import of the corporate module;
  a thin session hook onto the caller-driven engine). Smoke-tested (0.3 stock div 1000→1300; 2000đ
  cash div credits gross), then the **full market suite: 1596 passed, no regression**. S3 then shows
  the two segregated pools coexisting (basket in securities, short in the deposit) and the held HPG
  paid 3000×1500 = 4,500,000đ gross through the session, value conserved. `J9`/`J17`/`J22` (thin
  leg, round-lot change, participation cap) are follow-ups — S3 used liquid, stable legs.
- **2026-08-28** — **S7 Tier 2 GREEN. Goal "all strategies through S7 to Tier 2" is COMPLETE
  (S1, S2, S3, S5, S7 — 6 test functions, all pass).** S7 runs S1 *unchanged* under the three fill
  policies: `soft` → 5 fills, 2 calls, forced, end equity 9.4M (−76%); `hard` and `probabilistic` →
  0 fills, end equity 40M (untouched) — S1's market orders never fill under the strict policies, so
  the whole blow-up history was the fill assumption (J10/J20). Probabilistic reproducible under seed
  7. `J13`/`J21` (queue policy) and `J22` (participation cap) live on the depth extract in the
  scenario suite; S7 measures the session-level fill assumption. **Scorecard: 5/7 strategies Tier 2 —
  one real library build (`apply_corporate_action`, regression-free at 1596 market tests), otherwise
  all green on the existing engine.** Remaining: **S4** (auction — the expected auction-phase-source +
  D71 build) and **S6** (KRX regime-straddle), both deferred beyond this goal.
- **2026-08-28** — **S4 Tier 2 GREEN — the second real library BUILD, the one predicted from the
  start.** On the daily corpus the session never entered an auction phase (the base adapter stamps
  every bar `CONTINUOUS` — a daily bar's ts is midnight), so ATO/ATC orders were refused
  *illegal-in-continuous* and J7/J14 could only be shown off the session path. Built
  **`AuctionAwareDataHubSource`** (`adapters/auction_daily.py`): a subclass that reads the phase off
  the request *instant* (the advance time, via the dated schedule) and wires the published open
  (`quote_open`, on disk but unwired in the base). Overrides `state_at` (so admission sees the auction
  phase) and `interval` (so the fill does), reading the open separately so the base adapter — and its
  1596 tests — are **untouched**. S4 (auction-only rebalancer on FPT) then crosses **8 ATO at the
  published open, 5 ATC at the published close, 0 continuous fills**, all through the ordinary session.
  `J12` (MOK/MAK top-ups) is a follow-up; `D71` (the tick-path ATC-at-stale-last one-condition fix)
  remains documented but is not on S4's daily path.
- **Scorecard: 6/7 strategies Tier 2. Two real builds** (`apply_corporate_action`,
  `AuctionAwareDataHubSource`), both regression-safe; the other four green on the existing engine.
  **Only S6 (KRX regime-straddle) remains.**
- **2026-08-28 — S6 Tier 2 GREEN. ALL SEVEN STRATEGIES ARE TIER 2. Goal complete.** S6 is a
  regime-aware VN30F strategy: the corpus ends 2022-12-30, so it trades **live pre-KRX** (a real
  VN30F2210 long, IM 14,333,800 under `pre_margin`) and asserts the post-KRX side at the rulebook
  level (no fabricated prices). Its guard queries `margin_model()`: **pre-KRX it resolves → the
  strategy trades; post-KRX it RAISES `UnresolvedRule` → the strategy refuses to size a position it
  cannot margin.** Editions flip `pre_krx`→`post_krx`. No library change (the dated rulebook already
  models this); `J27` (amend flip) and the LO/MP→LO/MTL type flip are covered in the scenario suite
  (the enum shows `MTL` both sides — MP and MTL are one member — so the type-flip isn't strategy-
  assertable here).

## FINAL — 7 / 7 strategies Tier 2 (2026-08-28)

| Strategy | Emergent finding | Build |
|---|---|---|
| S1 VN30F mean-reversion | over-lever → 2 calls → forced liquidation, −76% | existing lib |
| S2 leveraged equity momentum | stop gapped through 14 limit-down locks → forced sale, −86% | existing lib |
| S3 basket vs future + ex-date | two pools; held HPG paid 4.5M gross through the session | **`apply_corporate_action`** |
| S4 auction-only rebalancer | 8 ATO@open, 5 ATC@close, 0 continuous fills, via the session | **`AuctionAwareDataHubSource`** |
| S5 advance-turnover scalper | throttled 4 days by T+2 without the advance; advance fee 545k | existing lib |
| S6 KRX regime-straddle | trades live pre-KRX; refuses post-KRX (model unsourced) | existing lib |
| S7 fill sensitivity | S1's history is −76% or 0% purely by fill policy | existing lib |

**Two real library builds** (`ExchangeSession.apply_corporate_action`,
`adapters/auction_daily.AuctionAwareDataHubSource`), each smoke-tested and regression-verified at
**1596 market tests, twice**. Five of seven passed on the existing engine — the sim was faithful
enough that the strategy suite mostly *confirmed* fidelity (forced liquidation executes; a sale into
a limit-down lock is refused) rather than forcing fixes. Follow-ups, none blocking: `J9`/`J17`/`J22`
thin-leg/round-lot/cap in S3; `J12` MOK/MAK in S4; the `D71` tick-path ATC one-condition fix;
`RunLedger.equity()` netting the advance/pending receivable; `J25` a data-gap run.

## Running
```bash
.venv/bin/python -m pytest strategies/ -v          # every strategy
.venv/bin/python strategies/test_s1_vn30f_meanrev.py   # one, as a readable report
```
Strategies skip cleanly (not fail) when no corpus is present.
