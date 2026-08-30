# Plutus Strategy Reference (Sx)

**Version 1.0 · 2026-08-30.** Cite as *"Plutus Strategy Reference, S⟨n⟩"*.

The Sx suite is Plutus's **end-to-end fidelity layer** — nine real, documented
trading strategies (S1–S9), each written the way a `pip install`'d user writes one
(a signal, entry/exit, position/cash management), run against Plutus **as the
counterparty**. Where a Jx *scenario* stages a rule, an Sx *strategy* makes the
same moment **emerge from P&L against real corpus data** — a strictly stronger
fidelity claim. Two checks exist only when something trades for months:
**emergence** (the stress event fires on the corpus day the loss actually breached,
for the documented reason) and **conservation** (every đồng reconciles across the
run). The runner is **test-side** ("we ship the market, not the backtester"); the
strategies use only the public session surface.

**All nine are at Tier 2 (2026-08-30).** Two strategies forced a real, regression-
safe library **build**; the rest passed on the existing engine — the suite mostly
*confirmed* fidelity rather than exposing defects.

## The two policy axes (the spine)
- **Fill policy** (bar resolution, S1/S7): `soft` (fills on a touch) / `hard`
  (fills only what traded strictly through; never fills a market order) /
  `probabilistic` (seeded). Our modelling choice, **not** a rule.
- **Queue policy** (tick resolution, maker fill, S8/S9): `optimistic` (front of
  queue) / `conservative` (behind the displayed queue) / `probabilistic` (seeded
  between). Queue position is **unsourced** — the caller selects, stamped in
  provenance.
Neither may override band / tick / lot / order-type (decided before it runs).

## Index

| S# | Name | Emergent finding | Build | Folds in Jx |
|----|------|------------------|-------|-------------|
| S1 | VN30F mean-reversion | over-levers into a trend → daily VM depletes the deposit **past the call rung → forced liquidation**, −76% | existing lib | J3 J6 J13 J18 J24 J26 |
| S2 | Leveraged equity momentum | stop can't clear a limit-down lock → forced sale, −86% (instructed ~25×, completed 3×) | existing lib | J1 J2 J5 J11 J16 J24 |
| S3 | Basket vs future + ex-date | two segregated pools; held HPG paid gross through the session | **`apply_corporate_action`** | J4 J8 J23 |
| S4 | Auction MoC rebalancer | 8 ATO@open, 5 ATC@close, 0 continuous fills, via the session | **`AuctionAwareDataHubSource`** | J7 J14 |
| S5 | Advance-turnover scalper | throttled 4 days by T+2 without the advance; the advance costs a 545,624đ fee | existing lib | J15 J16 J24 J25 |
| S6 | KRX regime-straddle | trades live pre-KRX; **refuses post-KRX** (model unsourced → `UnresolvedRule`) | existing lib | J18 J19 J27 |
| S7 | Fill-sensitivity harness | S1's history is **−76% or 0% purely by fill policy** | existing lib | J10 J20 J13 J21 J22 |
| S8 | Intraday market-maker | two-sided **maker** fills off the tape; inventory skew fires; no intraday round-trip (T+2) | **tape-driven maker fill** | J28 J30 J32 |
| S9 | Queue-sensitivity study | the queue assumption alone moves the maker fill **~18.9%** | on the maker build | J29 J33 |

Every one of the 27 catalogue scenarios folds into ≥1 strategy; the J28–J37
intraday extension is exercised by S8/S9.

## Entries

- **S1 — VN30F front-month mean-reversion (the crown jewel).** A trailing z-score
  contrarian, conviction-sized (up to 4 lots), into the Oct-2022 VN30 slide that
  punishes mean-reversion. The position is built by the signal, the loss is real
  corpus P&L, and under daily VM cash settlement the deposit depletes fast enough
  that utilisation jumps **past the call rung straight to a FORCED close** (forced
  liquidation executes, net→0). **40M → 9.4M (−76%).** The one strategy-side lesson:
  a taker must send a market order (MTL), which fills at the print; a marketable
  *limit* fills at its own aggressive price (pays limit-up).
- **S2 — Leveraged equity momentum.** Breakout entry on DIG (HSX) at 1.8:1 on the
  real `EquityMarginAccount`. A stop only works if you can sell: a four-day
  limit-down waterfall locks the book, the stop is refused day after day, leverage
  runs in reverse. **100M → 13.6M (−86%);** the forced sale was instructed ~25× but
  completed 3× (DIG's 14 limit-down-lock days). *The account bled because it could
  not get out.*
- **S3 — Basket vs future (index-arb / dividend carry) — first real build.** Long a
  VN30 basket {HPG, SSI, MBB}, short VN30F2212, carried across a constituent
  ex-date; two segregated pools at once. Forced
  **`ExchangeSession.apply_corporate_action`** — the "missing feature → build it,
  don't mock" case. The held HPG is paid its dividend gross through the session; the
  ex-date reference conserves value.
- **S4 — Auction market-on-close rebalancer — second real build.** Trade only the
  auctions (buy each ATO, sell at each ATC), never continuous. The daily adapter
  stamps every bar CONTINUOUS, so this forced **`AuctionAwareDataHubSource`** (reads
  the phase off the request instant, wires the published open). **8 ATO / 5 ATC / 0
  continuous;** on ≥1 day open ≠ close. The auction cross-at-published-price is *our
  modelling choice*.
- **S5 — High-turnover advance scalper.** A reversal swing on FPT, run twice — with
  and without the sale advance (*ứng trước tiền bán*). **With** it, more turnover and
  a **545,624đ fee**; **without** it, throttled 4 days by proceeds frozen under T+2.
  The advance's economic effect emerges from a running strategy.
- **S6 — KRX regime-straddle.** S1's futures core reasoning across the KRX cutover.
  The corpus ends 2022-12-30, so it trades **live pre-KRX** (a real VN30F2210 long,
  IM 14,333,800) and asserts the post-KRX side at the rulebook level. Its guard
  queries `margin_model()`: pre-KRX resolves → it trades; post-KRX **raises
  `UnresolvedRule`** → it refuses to size a position it cannot margin. Guards against
  *silent continuation* of 2022's mechanism into a 2025 position.
- **S7 — Fill-sensitivity harness (the methodological strategy).** Runs S1 unchanged
  under the three bar-resolution fill policies. **`soft` → −76%; `hard` and
  `probabilistic` → 0 fills, deposit untouched** — S1's market orders never fill
  under the strict policies, so the entire blow-up was the fill assumption.
  Reproducible under seed 7. Feeds **F3**'s fill-axis panel.
- **S8 — Intraday inventory market-maker (the intraday selling point).** Posts a
  two-sided quote at the touch, sees what the tape lifted, re-quotes, skews to pull
  inventory to target. Produces **genuine two-sided maker fills off the tape** at its
  own posted prices (the old book-snapshot model produced zero); the inventory skew
  fires; the **T+2 constraint** means no intraday round-trip on HSX. A VN30F variant
  contrasts a futures desk that *can* round-trip (no inventory, no T+2).
- **S9 — Queue-sensitivity study (the honest intraday headline).** The same S8 maker
  on the same day under all three queue assumptions, with skew OFF and inventory
  ample so the quote is identical across runs — the spread is the queue's alone.
  Optimistic > probabilistic > conservative, a **~18.9% maker-fill swing**. "The
  queue assumption, not the strategy, moves the maker's P&L by ~19%." Measured
  because the queue position is genuinely unobservable in an id-less corpus. Feeds
  **F3**'s queue-axis panel.

## The maker-fill mechanic (S8/S9)
A resting limit at price P fills from the **prints-through the trade tape** since
arrival, gated by **queue-ahead** (displayed size at P at arrival): optimistic =
min(remaining, prints); conservative = max(0, prints − ahead); probabilistic =
seeded ahead ∈ {0..displayed}. **Zero prints on an *observed* tape is a definite
no-fill (clean), not indeterminate; an *absent* tape is INDETERMINATE.** Volume is
the delta of `quote.total` (authoritative), not the lossy `matchedvolume`. A maker
fill is `MODELLED` evidence, never `TRADED_THROUGH`.

## Reproduction notes
Prices are ×1000 (corpus thousands-of-đồng vs cash in đồng); a taker sends MTL; the
day loop must pass the 14:45 derivatives determination; shipped fixtures (<1 MB) run
the suite from a bare clone; tests **skip** (not fail) without data; look-ahead-safe
by construction; `FINE_MARKS` so the queue bites; probabilistic reproducibility
under seed 7.

## Companion figure tests
`strategies/test_f2_resolution_indeterminacy.py` and `test_f3_cross_policy.py` are
not strategies but pin the paper's figures: **F2** (indeterminate rate by resolution
× cause) and **F3** (cross-policy divergence, joining S1's fill axis and S8's queue
axis to the indeterminate rate).

*Full detail: `STRATEGY-BOARD.md` (worksheet + history) and the design specs
`docs/superpowers/specs/2026-08-28-*`. Tests: `strategies/test_s⟨n⟩_*.py`.*
