# Literature review and positioning

**Purpose.** This is the prior-art section the paper draws on, and the document a
reviewer checks our novelty claims against. It exists because three of our claims were
attacked adversarially in 2026-08-26 survey passes and **all three had to be narrowed**.
The narrowed forms are recorded here verbatim in §4, and no broader form of any of them
appears anywhere in this document or may appear in the paper.

---

## 0. How to read this document

### Marking

Every factual claim about another tool carries one of these markers.

| Marker | Meaning |
|---|---|
| **[V]** | The named source file or full text was read, on the branch/date stated. |
| **[V-neg]** | An *absence* was verified by reading the named module(s). Scoped to those modules — see the limits below. |
| **[R]** | Secondary source only: docs page, vendor summary, search result, abstract. Not read in the primary. |
| **[U]** | **Unverified.** We could not establish it. It appears as unverified in the text, never as a plausible assertion. |

### Provenance and the limits of the survey

Verification was performed in four survey passes on **2026-08-26**, reading default
branches (`master`/`main`/`develop`) via `raw.githubusercontent.com`, official
documentation sites, and extracted PDF text — not tagged PyPI releases. Three limits
constrain every absence claim below and must be stated if challenged:

1. **No repository-wide grep was possible** in the survey environment (no `gh` CLI;
   grep.app returned HTTP 429; the GitHub code-search API requires auth). Every **[V-neg]**
   is scoped to the modules explicitly named in the Sources table, not to the whole
   repository. A feature could exist in a module we did not open.
2. **Branch, not release.** Behaviour in the current PyPI/NuGet release of any project may
   differ from the branch read. Release recency was not verified for any project. **[U]**
3. **Closed platforms were assessed from documentation only** — JoinQuant, MT5 internals,
   TradeStation, vectorbt.pro, SSI iWin, VPS SmartEasy. We make no claim about their
   source. In particular **no claim whatsoever is made about `vectorbt.pro`**, which was
   not examined.

A fourth caution applies to quotations. During the literature pass, a fetch-summarising
model fabricated an "exact quote" attributed to Balch et al. (2019) that occurs **zero**
times in the extracted PDF. Every verbatim string in this document was re-grepped against
extracted text or raw source. Any quotation added later must be too.

---

## 1. The problem

### 1.1 The gap between a backtest and live trading is first-order, and it is made of assumptions

The finance literature has established, repeatedly and quantitatively, that the
implementation assumption — not the signal — decides whether a strategy result survives.

**Costs eliminate most of the reported profit.** Patton & Weller (JFE 2020) ask directly:
*"Is there a gap between the profitability of a trading strategy 'on paper' and that which
can be achieved in practice?"* Their two independent methods put momentum's annual
implementation cost at **2.2%–8.5%**, *"which eliminates most profits accruing to momentum
during the 1970–2016 period"*, and value at 2.6%–5.0%; the matched-pair estimates are
1.91%–2.23% for UMD against a time-series mean return of 8.75%. They call this *"a stark
departure from the muted effects of trading costs often considered in the academic
literature."* **[V]** `[lit-pw]` Note that their headline is itself reported **as a range
across two methods**, which is precedent for reporting a spread rather than a point
estimate.

**Two competent teams get opposite answers from the same anomalies because they assume
different costs.** Novy-Marx & Velikov (RFS 2016) find execution costs of 20–57 bps for
mid-turnover anomalies and conclude most high-turnover anomalies do not survive **[R]**
`[lit-nmv]`; Frazzini, Israel & Moskowitz, using more than $1 trillion of live trades,
conclude value, size and momentum *are* implementable and scalable to tens or hundreds of
billions **[R]** `[lit-fim]`. The disagreement is entirely about the cost/fill assumption
(TAQ-implied effective spreads versus realised institutional costs), not about the signal.
This pair is the cleanest existing motivation for making the execution assumption a
declared parameter rather than a hidden one.

**The modelling choice is itself a measurable source of dispersion.** Menkveld et al.
(*Journal of Finance* 79(3), 2024) gave **164 research teams** the same Deutsche Börse
EuroStoxx-50 futures sample and the same six hypotheses. Variation in the
evidence-generating process across researchers produced "non-standard errors" that are
**"sizeable, on par with standard errors,"** only weakly related to team merit or
reproducibility, and **underestimated by the participants themselves** **[R]**
`[lit-menkveld]`. This is the strongest available academic hook for our work: an
indeterminate-fill rate and a cross-policy divergence are, in this language, an *in-band
measurement of one component of non-standard error* — made by construction instead of
discovered by running 164 teams.

**The overfitting literature is the established frame, and it does not cover this.**
Bailey, Borwein, López de Prado & Zhu formalise the Probability of Backtest Overfitting
via combinatorially symmetric cross-validation, opening with *"Standard statistical
techniques designed to prevent regression overfitting, such as hold-out, tend to be
unreliable and inaccurate in the context of investment backtests"* **[V]** `[lit-pbo]`;
the Deflated Sharpe Ratio corrects for selection bias under multiple testing, sample
length and non-normality **[V]** `[lit-dsr]`; Minimum Backtest Length shows that with five
years of data, more than ~45 independent configurations near-guarantees an in-sample
annualised Sharpe of 1 with an expected out-of-sample Sharpe of **zero** **[R]**
`[lit-pmfc]`. Harvey, Liu & Zhu propose a t-statistic hurdle of 3.0 across 316 tested
factors **[R]** `[lit-hlz]`; Hou, Xue & Zhang report 64% of 447 anomalies insignificant at
5% **[R]** `[lit-hxz]`. For balance, Jensen, Kelly & Pedersen (JF 2023) dissent: most
factors *do* replicate under a Bayesian hierarchical treatment **[R]** `[lit-jkp]`.

All of that literature attacks **statistical** overfitting. None of it attacks the
**mechanical** question of whether the trade could have been placed at all.

**The one protocol that comes closest asks for robustness, not disclosure.** Arnott,
Harvey & Markowitz (*JFDS* 2019) devote a sub-heading to *"Do Not Ignore Trading Costs and
Fees"*: *"Almost all of the investment research published in academic finance ignores
transactions costs. Even with modest transactions costs, the statistical significance of
many published anomalies essentially vanishes."* On modelling choices they write:
*"Manipulation of the input data … is a choice and is analogous to trying extra variables.
The choices need to be documented and ideally decided in advance. Furthermore, results
need to be robust to minor changes in the transformation."* **[V]** `[lit-ahm]` They frame
this as *robustness to* a choice, not as *publication of the spread across* choices.

### 1.2 Why exchange-side rules are the part general engines leave out

General-purpose engines are jurisdiction-neutral by design. A tick grid, a board lot, a
daily price band, an auction eligibility rule, a settlement cycle and a margin regime are
all **national and dated**; a portable engine either omits them or lets the user supply
them as constants. The consequence, for a market whose rules bind hard, is that a
non-executable price is silently ingested as if it were a fill.

Du (2025) quantifies exactly this for China A-shares: *"daily price-move limits (±10%
main-board, ±20% STAR/ChiNext) render a fraction of closing prices non-executable, yet
standard implementations ingest these values before any row-filtering runs."* The measured
contamination *"inflates apparent information coefficient by 18% while reducing realised
Sharpe by 0.44 points"*, and a tradability mask threaded through every operator recovers
the largest single component (+0.44 Sharpe) **[V]** `[lit-du]`. **Caveat, to be stated
wherever we cite it: single-author arXiv preprint, self-reported numbers, not
peer-reviewed.**

That number is the argument for our whole scope. Vietnam's band is ±7% on HOSE, with
widened regimes, degenerate branches and a price-dependent tick grid on top; and the rules
changed inside our own data window.

---

## 2. What existing tools do

### 2.0 Method, and what these tables are not

Rows are the capabilities Plutus targets. Columns are tools. Each cell carries a source key
resolved in §6. Cells state **what the tool does**, not what it lacks relative to us —
several of these tools do a given capability better than we do, and the paper says so.

**Two definitional cautions built into the rows:**

- *Order-admission gate* means a rule that refuses or alters an order **before** it can
  rest, on grounds of exchange rule (grid, lot, band, session, room), not portfolio
  feasibility (cash, size limits). Several tools have rich feasibility gates and no
  exchange gate; the table distinguishes them.
- *Explicit indeterminacy* means an outcome distinct from "did not fill" that means "the
  data cannot establish whether this filled." This row's history is the most contested in
  the document; see §2.4 and §4.

### 2.1 General-purpose engines

| Capability | LEAN | NautilusTrader | Zipline-reloaded | Backtrader | vectorbt (OSS) | Qlib | RQAlpha | hftbacktest |
|---|---|---|---|---|---|---|---|---|
| **Order-admission gate (exchange rules)** | Per-brokerage `IBrokerageModel.CanSubmitOrder`; min-lot rejection `OrderQuantityLessThanLotSize`; market-hours check `[V]` `[L-adm]` | `OrderMatchingEngine::process_order` rejects on market status, instrument activity, **price/size decimal precision**, short-sell on non-margin acct, reduce-only, contingency `[V]` `[N-adm]` | Richest **feasibility** gate of the set: `MaxOrderCount`, `MaxOrderSize`, `MaxPositionSize`, `LongOnly`, `RestrictedListOrder`, `AssetDateBounds` — none is an exchange rule `[V]` `[Z-ctl]` | Cash/margin pre-check `checksubmit`; distinct `Margin` order status `[V]` `[B-sub]` | Inline reject taxonomy (`NoCashLong`, `MinSizeNotReached`, `MaxSizeExceeded`, …) — all portfolio feasibility `[V]` `[VB-enum]` | `check_stock_limit` / `check_stock_suspended` boolean tradability `[V]` `[Q-exch]` | Pre-trade validators: price band, cash, is-trading, self-trade, position `[V]` `[RQ-val]` | None; latency/queue only `[V-neg]` `[H-tree]` |
| **Dated rule editions** | Dated **parameters** as data: `Data/future/cme/margins/ES.csv` `date,initial,maintenance` `[V]` `[L-cme]`. No dated admission rules `[V-neg]` | None found `[V-neg]` `[N-adm]` | None found `[V-neg]` `[Z-ctl]` | None `[V-neg]` `[B-cal]` | None `[V-neg]` `[VB-enum]` | None; `trade_unit` is a global scalar `[V]` `[Q-exch]` | `Instrument.get_long_margin_ratio(date)`; `market_tplus` per instrument `[V]` `[RQ-pos]`. Auction windows hard-coded to China clock times `[V]` `[RQ-match]` | None `[V-neg]` `[H-tree]` |
| **Settlement cycle (T+N)** | **Yes** — `ISettlementModel`, `DelayedSettlementModel`, `UnsettledCashBook`; equity default `DefaultSettlementDays = 1`; applies only when `AccountType == Cash` `[V]` `[L-settle]`. Settlement days counted on the security's **trading** calendar (`security.Exchange.Hours.IsDateOpen`) `[V]` `[L-settle]` | No T+N cash settlement; `matching_engine/settlement.rs` is option expiry `[V-neg]` `[N-settle]` | None; `Ledger.process_transaction` moves cash immediately; no settlement module in `finance/` `[V-neg]` `[Z-ledger]` | None `[V-neg]` `[B-sub]` | None `[V-neg]` `[VB-nb]` | One-**step** cash delay only: `ST_CASH` / `cash_delay`, *"The cash you get can't be used in current step"*, with `# TODO: other assets` — no calendar, no security leg `[V]` `[Q-pos]` | T+1 on **shares** via `_non_closable`; cash from a sale is available immediately; no T+N cash cycle `[V]` `[RQ-pos]` | None `[V-neg]` `[H-tree]` |
| **Settlement calendar distinct from trading calendar** | No — see above `[V]` `[L-settle]` | n/a | n/a | `TradingCalendar` covers sessions and holidays only `[V]` `[B-cal]` | n/a | No `[V]` `[Q-pos]` | `market_tplus` counts **trading** days `[V]` `[RQ-pos]` | n/a |
| **Tick grid** | **Yes, price-dependent**: `IPriceVariationModel` / `EquityPriceVariationModel` implements Reg NMS Rule 612 (`< $1 → 0.0001`) `[V]` `[L-tick]`. Enforced by **rounding, not rejection** — `BrokerageTransactionHandler.RoundOrderPrices` `[V]` `[L-round]` | Decimal **precision** and min/max size enforced at submission; `price_matches_tick` exists but its only caller is `drop_incompatible_core_orders` from `update_instrument`, not a submission check `[V]` `[N-tick]` | **Yes, constant per asset**: `Asset.tick_size` (0.01; `Future` 0.001) with directional `asymmetric_round_price` `[V]` `[Z-tick]` | None in the commission-info layer where a contract spec would live `[V-neg]` `[B-comm]` | None; `size_granularity` is a **quantity** grid, per order `[V]` `[VB-enum]` | None — no price-increment concept `[V-neg]` `[Q-exch]` | `data_proxy.get_tick_size`; used in the band tolerance `[V]` `[RQ-lim]` | None `[V-neg]` `[H-tree]` |
| **Lot / board-lot grid** | Minimum only (`SymbolProperties.LotSize`), not divisibility `[V]` `[L-adm]` | `min_size_increment_precision()` is a decimal-places count: with `size_increment=100`, a quantity of 150 passes `[V]` `[N-tick]` | Integer shares (`round_order`); no board lot `[V]` / `[V-neg]` `[Z-tick]` | None `[V-neg]` `[B-comm]` | `size_granularity` (generic) `[V]` `[VB-enum]` | `round_amount_by_trade_unit`, global `trade_unit` (100 for A-shares) `[V]` `[Q-exch]` | `min_order_quantity`, `order_step_size`, `round_order_quantity` `[V]` `[RQ-match]` | None `[V-neg]` `[H-tree]` |
| **Daily price limits** | **None anywhere in LEAN** — path-grep of the 6,851-path tree for `circuit\|limitup\|limit_up\|priceband\|halt\|auction` returns only indicators and a sample algorithm; `ZerodhaBrokerageModel.CanSubmitOrder` does **not** implement India's circuit limits `[V-neg]` `[L-band]` | None; only `MarketStatusAction::Halt` `[V-neg]` `[N-adm]` | None `[V-neg]` `[Z-slip]` | None `[V-neg]` `[B-sub]` | None `[V-neg]` `[VB-nb]` | Boolean tradability flag from `$change` vs a threshold, or user expressions — never derives a band from a reference price; **default is off**, with `logger.warning("limit_threshold not set…")` `[V]` `[Q-exch]` | **Yes, twice**: pre-trade `PriceValidator` against `get_limit_up`/`get_limit_down`, and at match time `reaches_limit` with a one-tick tolerance. **Band comes from a vendor data field, not from reference price + rounding rule** `[V]` `[RQ-lim]` | None `[V-neg]` `[H-tree]` |
| **Call auctions** | `MarketOnOpenOrder` / `MarketOnCloseOrder` fill at next open / close. No auction phase, no price discovery, **no phase in which a limit order is legal** `[V-neg]` `[L-fill]` | `MarketStatusAction::PreOpen` maps **to `MarketStatus::Open`**; orders rejected whenever status ≠ Open `[V]` `[N-adm]` | None; only Market/Limit/Stop/StopLimit `[V-neg]` `[Z-exec]` | `coc`/`coo` are documented **cheating** flags, not auctions `[V]` `[B-coc]` | None `[V-neg]` `[VB-nb]` | None `[V-neg]` `[Q-exch]` | **Yes**: `_during_call_auction`, `_open_auction_deal_price_decider`, `get_open_auction_bar/volume`; auction fills bypass slippage `[V]` `[RQ-match]` | None `[V-neg]` `[H-tree]` |
| **Segregated derivatives margin account** | One `CashBook` + one `UnsettledCashBook` per algorithm, one `AccountType`. `DefaultMarginCallModel` is a **utilisation test**: warn at 5% margin remaining, call when `totalMarginUsed > totalPortfolioValue × (1 + marginBuffer)`, `marginBuffer = 0.10` `[V]` `[L-mcm]`. Numerator is **maintenance** margin `[V]` `[L-spm]`. `FutureSettlementModel.Scan` is real daily variation margin `[V]` `[L-fut]` | `MarginAccount` with per-instrument initial **and maintenance** margin, per-instrument leverage, `MarginModel` trait. **One account per venue**, type `CASH \| MARGIN \| BETTING` `[V]` `[N-margin]` | `account.initial_margin_requirement = 0.0`, `account.maintenance_margin_requirement = 0.0`, `buying_power = np.inf` — **fields exist, hard-coded to zero, never enforced** `[V]` `[Z-ledger]` | Flat per-contract `margin`; no IM/MM split; failure surfaces as order status `Margin` `[V]` `[B-comm]` | `lock_cash` only `[V]` `[VB-enum]` | None `[V-neg]` `[Q-exch]` | **Yes**: `Portfolio._accounts` with `stock_account` / `future_account`, each with own `_total_cash`, `frozen_cash`, `margin` `[V]` `[RQ-port]`. No utilisation test, no VM as a separate flow, no MR = IM + VM `[V-neg]` | None `[V-neg]` `[H-tree]` |
| **User-replaceable fill determination** | **Yes** — `IFillModel.Fill(FillModelParameters)`, `Security.SetFillModel(IFillModel)` **and** `SetFillModel(PyObject)`, per security `[V]` `[L-fill]` | **Yes** — `trait FillModel` / `cdef class FillModel`, 11 shipped models, `set_fill_model` on the venue. `prob_fill_on_limit` (default 1.0) is itself a hard/probabilistic/soft axis with `random_seed` `[V]` `[N-fill]` | **Yes** — `SlippageModel` ABC whose `process_order` may return `(None, None)` to decline; the whole `Blotter` is `@extensible` `[V]` `[Z-slip]` | Partially — `filler` sizes an already-determined fill; `slip_match`/`slip_out` modulate a fixed algorithm `[V]` `[B-fill]` | **No** — fill logic is `@njit`-compiled and fixed. `reject_prob` is a documented Bernoulli rejection with status `RandomEvent`, applied after order logic, independent of price/volume/queue `[V]` `[VB-enum]` | Only by subclassing `Exchange` wholesale via `init_instance_by_config` `[V]` `[Q-exch]` | **Yes** — `AbstractMatcher.match` + seven config-selectable `MATCHING_TYPE` values; three-way `OrderNotMatchable` / `OrderRejected` / `OrderCancelled` `[V]` `[RQ-match]` | **Yes** — `trait QueueModel` with `RiskAdverseQueueModel` and `ProbQueueModel` over five probability functions; two exchange models (partial / no-partial) `[V]` `[H-queue]` |
| **Explicit indeterminacy** | No. `// assume the order completely filled` appears at six sites in `EquityFillModel.cs` `[V]` `[L-eqfill]`. One near miss: `GetBestEffortAskPrice` throws `InvalidOperationException` naming the subscribed types when **no** market data exists — an exception that aborts the run, not a recorded outcome, and never fired on the ambiguity case `[V]` `[L-eqfill]` | No; grep for `indeterm` returns zero. Bar execution *"simulates a plausible intrabar path rather than reconstructing the original trades"*; the adaptive path is *"a deterministic heuristic, not a reconstruction"* `[V]` `[N-bar]` | No `[V-neg]` `[Z-slip]` | No `[V-neg]` `[B-fill]` | No `[V-neg]` `[VB-enum]` | NaN close ⇒ untradable ⇒ `deal_amount = 0`, price `nan` — untradable, not unknowable `[V]` `[Q-exch]` | `OrderNotMatchable(_("Current bar missing market data."))` leaves the order **Active**: missing data and unfilled are the same state `[V]` `[RQ-match]` | Resolves uncertainty by **assuming a queue model**; never abstains `[V]` `[H-queue]` |

### 2.2 Specialist and adjacent systems

| Capability | ABIDES | EvoMarket (2026) | vnpy (`alpha`) | Hummingbot | PyAlgoTrade | bt / QSTrader | Forex Strategy Builder (2011) |
|---|---|---|---|---|---|---|---|
| **Order-admission gate** | Market open/close only; orders after `mkt_close` refused `[V]` `[A-ex]` | Band-based rejection or truncation of out-of-band orders `[R]` `[E-paper]` | None `[V-neg]` `[VN-alpha]` | `TradingRule` quantisation at submission: `min_price_increment`, `min_base_amount_increment`, `min_notional_size` `[V]` `[HB-rule]` | No cash check at `submitOrder()`; checked at `commitOrderExecution()` and **retried on later bars** `[V]` `[PA-bt]` | bt: no order object at all `[V]` `[BT-core]`; QSTrader: none, warns and proceeds with negative cash `[V]` `[QS-port]` | n/a (retail FX) |
| **Dated rule editions** | None `[V-neg]` `[A-ord]` | Not described `[R]` `[E-paper]` | **Hard-coded** `pre_close * 1.1` / `* 0.9`, ±10% only, no ChiNext/STAR/ST/BSE variants, no effective date `[V]` `[VN-alpha]` | None `[V-neg]` `[HB-rule]` | None `[V-neg]` `[PA-bt]` | None `[V-neg]` | None |
| **Settlement cycle** | None `[V-neg]` `[A-ord]` | **T+1**, available/pending share decomposition `[R]` `[E-paper]` | None `[V-neg]` `[VN-alpha]` | None `[V-neg]` `[HB-pt]` | None `[V-neg]` `[PA-bt]` | None `[V-neg]` | n/a |
| **Tick / lot grid** | `tick_size` appears **only** inside `adaptive_market_maker_agent.py`, never as an exchange-enforced grid `[V]` `[A-ord]` | Flat RMB 0.01 tick `[R]` `[E-paper]` | `pricetick` used in the band rounding `[V]` `[VN-alpha]` | Per-pair constant increment `[V]` `[HB-rule]` | None `[V-neg]` `[PA-bt]` | bt `integer_positions=True` `[V]` `[BT-core]` | n/a |
| **Price limits** | None; zero hits for `price_limit\|limit_up\|limit_down\|circuit` in the markets package `[V-neg]` `[A-ord]` | **Yes**: `p_min = (1−η)p_ref`, `p_max = (1+η)p_ref` `[R]` `[E-paper]` | **Yes**, undated ±10% `[V]` `[VN-alpha]` | None `[V-neg]` `[HB-pt]` | None `[V-neg]` `[PA-bt]` | None `[V-neg]` | n/a |
| **Call auctions** | **Not implemented**; `exchange_agent.py:219` carries *"This can probably go away once we code the opening cross auction"* `[V]` `[A-ex]` | **Yes**, opening call auction `[R]` `[E-paper]` | None `[V-neg]` `[VN-alpha]` | None `[V-neg]` `[HB-pt]` | None `[V-neg]` `[PA-bt]` | None `[V-neg]` | n/a |
| **Segregated margin** | None; holdings are `Dict[str, int]` with a `"CASH"` key `[V]` `[A-ord]` | None `[R]` `[E-paper]` | None `[V-neg]` `[VN-alpha]` | `PerpetualBudgetChecker` leverage, no IM+VM account `[R]` `[HB-pt]` | `__allowNegativeCash` flag only `[V]` `[PA-bt]` | None `[V-neg]` | n/a |
| **User-replaceable fill determination** | No — you change *who trades* (agent population), not how fills are decided `[V]` `[A-ob]` | No; deterministic CDA `[R]` `[E-paper]` | No `[V-neg]` `[VN-alpha]` | **No** — hard-coded in Cython `cdef` methods, not overridable from Python `[V]` `[HB-pt]` | **Yes** — `FillStrategy` ABC with `fillMarketOrder`/`fillLimitOrder`/`fillStopOrder`/`fillStopLimitOrder`, installed via `setFillStrategy()`, each returning `FillInfo` **or `None`** `[V]` `[PA-fill]` | bt: cost only (`set_commissions`) `[V]` `[BT-core]`; QSTrader: `slippage_model`/`market_impact_model` are `None` with `# TODO: Implement` `[V]` `[QS-broker]` | **Yes** — `enum InterpolationMethod { Pessimistic, Optimistic, Shortest, Nearest, Random }` `[V]` `[FSB-cmp]` |
| **Explicit indeterminacy** | No `[V-neg]` `[A-ob]` | No `[R]` `[E-paper]` | No `[V-neg]` `[VN-alpha]` | No `[V-neg]` `[HB-pt]` | No — `FillStrategy` returns fill-or-no-fill `[V]` `[PA-fill]` | No `[V-neg]` | **Yes** — `enum BacktestEval { Error, None, Ambiguous, Unknown, Correct }`, set at 8 sites each commented *"Ambiguous - two orders or order and bar closing"* `[V]` `[FSB-eval]` |

### 2.3 Where prior art is strongest — credit stated plainly

These are the findings that would sink an over-broad claim, and the paper states each of
them before making any claim of its own.

1. **LEAN models T+N settlement.** `ISettlementModel` with `ApplyFunds`/`Scan`/
   `GetUnsettledCash`, `DelayedSettlementModel`, `ImmediateSettlementModel`,
   `FutureSettlementModel`, and a real `UnsettledCashBook`. Equity default is
   `DefaultSettlementDays = 1`, `DefaultSettlementTime = 06:00`, applied only for cash
   accounts **[V]** `[L-settle]`. We claim **no novelty for T+N**.
2. **Price-dependent tick grids are precedented.** `EquityPriceVariationModel` implements
   Reg NMS Rule 612 **[V]** `[L-tick]`. We claim the Vietnamese grid and its dated
   2016-09-12 revision, **not the concept**.
3. **Settlement calendars distinct from trading calendars are two decades old.** QuantLib's
   `UnitedKingdom::Market` enumerates `Settlement`, `Exchange`, `Metals`; `unitedstates.cpp`
   implements seven separate calendar impls (`Settlement`, `NYSE`, `GovernmentBond`, `SOFR`,
   `FederalReserve`, `NERC`, `LiborImpact`), and `Bond::settlementDate` advances over
   whichever calendar is supplied: `Date settlement = calendar_.advance(d, settlementDays_, Days);`
   **[V]** `[QL-uk]` `[QL-us]` `[QL-bond]`. The split is a standard vendor product (Copp
   Clark's "Exchange Settlement" category) **[R]** `[cc]`, and NSE India publishes Trading
   Holidays and Clearing Holidays as separate lists **[R]** `[nse]`. **Neither QuantLib (54
   country calendars) nor `exchange_calendars` (74 exchange calendars) contains Vietnam**
   **[V-neg]** `[QL-cal]` `[XC-list]`.
4. **Dated rule editions exist in open source — for calendars and parameters.** QuantLib's
   `unitedstates.cpp` is a dated national rulebook (`if (y >= 1971)` Uniform Monday Holiday
   Act; `y <= 1970 || y >= 1978` Veterans Day gap; `m == June && y >= 2022` Juneteenth; MLK
   from 1998; ~30 one-off dated closings) **[V]** `[QL-us]`. `exchange_calendars` XKRX
   encodes dated session-time editions (`open_times` 1978-04-01 → 1998-12-07;
   `close_times` 2016-08-01; lunch break abolished 2000-05-22) **[V]** `[XC-xkrx]`. LEAN
   ships dated CME margin tables as data **[V]** `[L-cme]`. RQAlpha resolves margin ratio
   by date **[V]** `[RQ-pos]`.
5. **Utilisation-tested margin with warning tiers is precedented.** LEAN's
   `DefaultMarginCallModel` warns at 5% margin remaining and calls when total margin used
   exceeds portfolio value × (1 + buffer) **[V]** `[L-mcm]`. TqSdk computes
   `self._account["risk_ratio"] = self._account["margin"] / self._account["balance"]` at
   three sites including `_on_settle` **[V]** `[TQ-trade]`. A regime with no published
   maintenance ratio, IM plus daily variation collection, tested as utilisation, is also
   China futures (风险度) and broadly India (SPAN + exposure + daily MTM) **[R]** —
   **Vietnam's regime is not structurally unique.**
6. **Fill determination is already user-replaceable in at least five systems**: LEAN
   `[V]` `[L-fill]`, NautilusTrader `[V]` `[N-fill]`, Zipline-reloaded `[V]` `[Z-slip]`,
   RQAlpha `[V]` `[RQ-match]`, hftbacktest `[V]` `[H-queue]`, plus PyAlgoTrade `[V]`
   `[PA-fill]` and, for model-based RL, mbt_gym's `FillProbabilityModel` with
   `ExponentialFillFunction` / `TriangularFillFunction` / `PowerFillFunction` `[V]`
   `[MG-fill]`. NautilusTrader documents the motivation in almost our own words:
   *"Historical data cannot show how a simulated order would have interacted with other
   market participants."* **[V]** `[N-filldoc]`
7. **A hard / probabilistic / soft axis ships by default in NautilusTrader.**
   `prob_fill_on_limit` (default `1.0`): *"`0.0`: Never fill on touch. `0.5`: Fill on half
   of eligible touches on average. `1.0`: Always fill on touch."* **[V]** `[N-fill]`
8. **RQAlpha is the most complete emerging-market rule engine that exists** and must be
   cited, not worked around: price limits enforced pre-trade and at match with a one-tick
   tolerance; call auction as a modelled phase; `market_tplus` as per-instrument data;
   dated margin ratios; segregated stock/future accounts; a 25%-of-bar-volume liquidity
   cap with explicit cancellation reasons **[V]** `[RQ-lim]` `[RQ-match]` `[RQ-pos]`
   `[RQ-port]`.
9. **A Chinese A-share simulator with the institutional rule surface was published in
   April 2026.** EvoMarket implements market calendars, opening call auctions, daily price
   limits, T+1 settlement and a tick size **[R]** `[E-paper]`. **We could not read its
   source and read only fetched HTML of the paper — treat as [R] and obtain the PDF before
   submission.** After EvoMarket, "nobody models an Asian emerging market's institutional
   rule surface" is false.
10. **Vietnamese brokers already ship rule-enforcing simulators.** vnstockgame's published
    rules enforce T+2 (*"Tất cả các giao dịch được khớp sẽ được thanh toán theo luật T+2"*),
    the band (*"Giá đặt mua/bán phải nằm giữa giá trần và giá sàn"*), a lot multiple and a
    19,990-share cap, ATO/ATC call-auction phases, LO/MP/ATO/ATC order types and a 0.2%
    fee, matched against real market prices and volumes **[V]** `[vsg]`. SSI iWin markets
    itself as the first Vietnamese simulated-trading platform covering both cash and
    derivatives, matching against real market price and volume **[V]** `[iwin]`; VPS
    SmartEasy markets derivatives simulation **[R]** `[smarteasy]`. All three are
    live-forward paper trading against today's feed, proprietary, single-edition, with no
    historical replay and no published rule set — but a Vietnamese reviewer will know them,
    so the paper names and distinguishes them rather than claiming empty ground.
    **Caution: vnstockgame's "multiple of 10" lot is that product's own rule and may be a
    simplification of HOSE's 100-share lot. Cite it as evidence of existence, never as
    evidence of correct VN rules.**

### 2.4 The indeterminacy row, in full — because this is where we were most wrong

Our earliest framing asserted that no engine has any concept of an indeterminate fill and
that no prior art reports an ignorance bound. **Both statements are false**, and the
refutation is old and open-source.

**Forex Strategy Builder** (Miroslav Popov / Forex Software Ltd., ©2006–2011; open-source
mirror `nuggett11/Forex-Strategy-Builder`, created 2011-04-27; shipped `ReadMe.html` reads
*"Version: 2.57.21.0 - Beta / Release date: March 21, 2011"*) implements, in 2011:

- a non-binary evaluation status, `Backtester/Backtester Publics.cs` line 25:
  `public enum BacktestEval { Error, None, Ambiguous, Unknown, Correct }` **[V]** `[FSB-eval]`;
- **the ambiguity count as a reported headline statistic** — `static int ambiguousBars` →
  `public static int AmbiguousBars`, surfaced in the account-statistics panel under
  `Language.T("Ambiguous bars")` with a warning flag, and available as an **optimizer
  constraint** ("Maximum number of ambiguous bars") **[V]** `[FSB-stat]`;
- a coordinated family of determination policies —
  `enum InterpolationMethod { Pessimistic, Optimistic, Shortest, Nearest, Random }`, documented as
  *"Those bars for which we cannot tell for sure the correct sequence of order execution, are
  called Ambiguous Bars"* **[V]** `[FSB-cmp]`;
- and a **multi-policy comparator that plots the divergence** — `Dialogs/Comparator.cs`
  (809 lines) with a checkbox per method, `numRandom` iterations (default 25), min/max
  arrays and a dedicated random-band pen; documented as *"The Method Comparator calculates
  a strategy by using different interpolation methods and shows calculated balance lines on
  a common chart"* and *"When there are no ambiguous bars, all interpolation methods show
  the same result"* **[V]** `[FSB-cmp]`.

That last sentence is our own thesis, published in 2011.

**Claeys (2026)** reportedly repeats the move on modern data: SSRN 6240638, *"When
Backtests Guess: How Trading Platforms Silently Fabricate Results,"* 14 Feb 2026 —
reported as 2,064,460 one-minute E-mini NASDAQ-100 bars 2020–2025, **18.47%** of bars
ambiguous for a 10-point stop / 10-point target setup, and a best-case/worst-case gap of
**3,695 NQ points ($73,900) per 1,000 trades**. **[U] — SSRN returned ECONNRESET on two
attempts; title, author, ID and URL are confirmed from two independent search hits, but the
numbers come from search-engine summaries of the abstract page and were not read in the
PDF. Obtain and verify before citing.** `[claeys]`

**Yin, Miki, Lesnichenko & Gural (arXiv:2603.20319, 19 Mar 2026)** run 15 strategies
through 5 engines × 30 asset buckets × 4 cost regimes and propose engine spread (ES),
implementation uncertainty interval (IUI), divergence amplification factor (DAF) and
conclusion sensitivity indicator (CSI), borrowing the move from climate science's
*"multi-model spread"* **[V]** `[lit-ir]`. Grepping their extracted text for
`fill|limit order|execution assumption|intrabar|indetermin|slippage` returns **zero hits**
— they vary the engine and a proportional cost, never the fill rule.

**The nearest reported-ignorance metric in retail tooling** is MT4's `Modelling quality`
percentage in the standard tester report (90% from M1 data, 99% from real ticks), and
MT5's five declared tick-generation modes (*"Every tick based on real ticks … No simulation
is performed"*; *"1 minute OHLC … only 4 prices … are emulated"*; *"Open prices only"*)
**[R]** `[mt5]`. Modelling quality measures **input data completeness**, computed before
the run; it says nothing about how many of *this strategy's* orders were affected.
NinjaTrader 8's `Order Fill Resolution = Standard | High`, TradingView's Bar Magnifier and
TradeStation's Look-Inside-Bar Backtesting are the same class of declared-fidelity switch
**[R]** `[nt8]`.

**Consequences we accept.** After this, none of the following may be written anywhere:
"no engine has any concept of an indeterminate fill"; "no prior art for an ignorance
bound"; "nobody runs a strategy under several fill policies and shows the divergence".

---

## 3. Emerging-market constraints in the literature

### 3.1 Vietnam: the constraints are described and then not applied

**The leading factor study states the price limits and applies no tradability filter.**
Huang, Liu & Shu (*Pacific-Basin Finance Journal* 82:102176, 2023) write in their
institutional background: *"On HOSE, newly listed stocks have a 40% price limit on the
first trading day and a daily price limit of 7% on subsequent trading days. On HNX, there
is no price limit on the first trading day and a daily price limit of 10% on subsequent
trading days,"* and *"Vietnam's stock market does not allow short sales."* Their data
section takes Datastream return indices for HOSE and HNX common stocks, July 2007 – June
2022. A word-frequency check over the full extracted text returns **"ceiling" 0, "floor"
0, "foreign ownership" 0, "T+2" 0, "settlement" 0, "suspension" 0, "tick" 0, "transaction
cost" 0, "exclude" 0, "tradable" 0, "implementable" 0** **[V]** `[vn-hls]`. This is our
single most useful citation: the most comprehensive published factor study of Vietnam
treats the constraints as narrative colour, not as a property of the return-generating
process.

**The leading technical-trading study models costs but no exchange rules.** Nguyen,
Sensoy, Vo & von Mettenheim (*Borsa Istanbul Review*, 2020) handle constraints by
restricting the universe — *"the most liquid 27 stocks"* in VN30 — and assume *"transaction
costs of around 25 bps (0.25%) … for a single trade"*, stating *"In the rest of this
paper, all results include transaction costs."* Market impact is acknowledged
qualitatively only. Grep of the full text: **"price limit" 0, "ceiling" 0, "floor" 0,
"settle" 0, "T+" 0, "tick size" 0** **[V]** `[vn-nsvm]`.

**The one Vietnamese paper that encodes settlement encodes only settlement.** Pham, Luu &
Tran (*Soft Computing* 25(12), 2021) build a simulator over 10 HOSE stocks plus VN30F1M
including *"transaction fee, tax, and settlement date of transactions"*, and state
*"Stocks are only sold after T+2 settlement"* while the futures agent *"can trade
continuously as it is T+0 settlement market."* No price limits, no matching model, no
auction, and the fee/tax rates are never quantified **[V]** `[vn-pham]`.

**"Bias-free" in this literature means survivorship bias.** Do & Luong (SoICT '23) address
survivorship bias on VN100 exclusively; no mention of price limits, settlement or fill
assumptions **[V, abstract only — ACM full text returned 403]** `[vn-doluong]`.

**Vietnam-specific microstructure evidence worth citing as ground truth.** Vo & Doan
(*PLOS ONE* 18(5):e0285821, 2023) study the 12 Sep 2016 HOSE tick-size change on full
intraday TAQ and find trading cost fell overall but **not uniformly across price bands** —
larger trades executing in a larger-tick band did not benefit **[R]** `[vn-tick]`. This is
direct, Vietnam-specific empirical support for the price-dependent tick grid mattering
economically. An earlier GARCH study of the 2007–2009 band reductions (1/2/3% on HOSE,
2/3/4/7% on HNX) confirms the bands were **time-varying policy instruments** **[R]**
`[vn-band]`. **We found no Vietnam-specific magnet-effect or limit-hit microstructure
study; searches returned Taiwan, China and Korea only.**

**Vietnamese tooling is data access, not simulation.** The community index's entire
"Backtesting & Quant Tools" section is three bullets, of which one is "Add your tool";
all eight listed Python libraries are data access **[V]** `[vn-awesome]`. A GitHub search
across five phrasings returned nothing implementing matching rules; the most substantive
find runs VN30F1M *on NautilusTrader* with vnstock data **[V]** `[vn-github]`. DNSE's own
explainer lists required data as OHLC + volume and disclaims *"kết quả backtest chỉ mang
tính tham khảo"* **[V]** `[vn-dnse]`. ALGOTRADE's own Knowledge Hub article frames the
right problem — a paper-trading broker that *"can receive orders, cancel orders, return
order matches, and account status via API"* and *"determine whether an order can match, and
in how much volume based on information obtained from market data"* — but does not mention
T+2, tick size, lot size or ATO/ATC **[V]** `[vn-algotrade]`.

**Our own prior paper does not cover this ground**, and the paper should say so to
pre-empt a self-plagiarism concern: PLUTUS Open Source (arXiv:2505.14050) is a
reproducibility standard, project template and reference strategies; its execution detail
is *"A transaction fee of 0.035% is applied on each buy and sell"* and *"Each trade incurs
a fee of 0.2 points"*, with no price limits, T+2, tick size, lot size, auctions or
matching mechanics **[V]** `[vn-plutus]`.

**One priority risk we could not close. [U]** "Design and Implementation of an AI-Driven
Algorithmic Trading Simulation Platform for Strategy Backtesting and Forecasting"
(ResearchGate 399252297, dated March 2026), explicitly HOSE/HNX. **ResearchGate returned
403; we could not read it.** The reported summary describes data ingestion, backtesting
and forecasting with no mention of market rules. **This must be obtained and read before
submission.** `[vn-rg]`

### 3.2 China A-shares: the closest analogue

**The constraint changes behaviour, so it cannot be a post-hoc filter.** Chen, Gao, He,
Jiang & Xiong (*Journal of Econometrics*) show with account-level Shenzhen data that
*"large investors tend to buy on the day when a stock hits the 10% upper price limit and
then sell on the next day; and their net buying on the limit-hitting day predicts stronger
long-run price reversal"*, and summarise the standing critique that price limits *"may
impede the price discovery process, interfere with trading, and induce order imbalance and
volatility spillover"* **[V]** `[cn-chen]`.

**The magnitude of ignoring it is published.** Du (2025): +18% spurious IC, −0.44 realised
Sharpe, with a load-time tradability mask the largest single remedy **[V]** `[lit-du]`.
Note the same author's arXiv:2506.06356 does **not** discuss price limits, T+1 or
tradability at all, excluding only ST and suspended names **[V-neg]** `[cn-du2]` — the
field is inconsistent even within one author's work.

**Natural experiments on the band.** ChiNext's 10%→20% widening on 24 Aug 2020 confirms
delayed price discovery, volatility spillover and trading interference, and finds **no**
magnet effect (*PLOS ONE* 2023) **[R]** `[cn-chinext]`; a 2024 *RQFA* study finds widening
the **upper** band alleviates delayed discovery while an equal lower widening worsens it
**[R]** `[cn-asym]`. A 2025 paper argues daily momentum in China is dominated by the
next-day abnormal returns of limit-hitting stocks — the signal *is* the constraint **[R]**
`[cn-mom]`.

**T+1 is priced, not bookkeeping.** A *Journal of Banking & Finance* treatment of the
"T+1 trading rule" gives theory and evidence, with more recent work tying T+1 to the
overnight-return puzzle and put–call disparity **[R]** `[cn-t1]`.

**And the tooling shows what an undated rule looks like.** vnpy's newer A-share alpha
engine hard-codes `limit_up = round_to(pre_close * 1.1, pricetick)` with the fill test
`bar.low_price < limit_up` — ±10% only, no ChiNext/STAR ±20%, no ST ±5%, no BSE ±30%, no
effective dates, and no T+1 (`grep settle|tplus` returns nothing in that file) **[V]** /
**[V-neg]** `[VN-alpha]`. Its older CTA backtester has zero hits for
`limit_up|limit_down|涨跌停|t+1|tplus|settle|price_limit` **[V-neg]** `[VN-cta]`. This is
the cautionary counter-example the paper cites for what *not* to do.

### 3.3 Other emerging and frontier markets

- **Indonesia (IDX)** — Auto-Rejection (ARA/ARB) is a genuine dated, asymmetric, tiered
  band: symmetric pre-COVID; ARB tightened to 7% on 13 Mar 2020 (asymmetric regime);
  re-symmetrised effective 4 Sep 2023 at up to 35% **[R]** `[id-ara]`. **This is the best
  comparative case for "a price band is a dated rule edition, not a constant" — and we
  found no simulator that implements it.**
- **Taiwan** — the densest price-limit literature: magnet effect on TWSE high-frequency
  data (Cho, Russell, Tiao & Tsay, *JEF* 2003) **[R]** `[tw-magnet]`; limit moves followed
  by overnight continuation then reversal **[R]**; and a value premium *"stronger among
  stocks with lower limit-hit frequency"* **[R]** `[tw-value]` — a factor premium
  mechanically entangled with band-hit frequency.
- **Korea** — the 2015 band relaxation raised volatility **[R]** `[kr-band]`.
- **Thailand (SET)** — ceiling/floor plus circuit breakers, adjusted during COVID
  (reported ±15%, down from ±30%). **[U] — we could not verify the current level from an
  official SET source. Do not state a number without checking set.or.th.** `[th-band]`
- **Philippines (PSE)** — static/dynamic thresholds exist; we found no academic study and
  no simulator. **Treat as unexamined.** **[U]**
- **Agent-based simulators that do implement bands** are studying the rule, not evaluating
  a strategy: Mizuta & Yagi's artificial exchange *changes* out-of-band order prices to the
  band (with a cancelling variant) and halts on a circuit breaker **[V]** `[abm-mizuta]`;
  there is an agent-based magnet-effect paper in *EMFT* 61(7) **[R]** `[abm-magnet]`. The
  distinction between a synthetic-market simulator for studying a rule and a
  historical-replay simulator for evaluating a strategy must be made explicitly, or a
  reviewer will say "ABMs already do this."

### 3.4 What the emerging-market literature does not do

Across everything read: researchers either **describe** the constraint and drop it
(Huang/Liu/Shu), **exclude** it by universe choice (Nguyen et al.), **encode one** of it
(Pham et al.), or **mask** it at load time (Du). Nobody reports what fraction of their
signals the constraint would have refused, and nobody reports what fraction was
undecidable. Foreign ownership in particular: **no academic study we found models FOL as a
hard order-rejection constraint** — genuinely open ground **[R]** `[vn-fol]`.

---

## 4. The gap, at exactly the width the attacks leave standing

Each claim below is the **narrowed** form produced by an adversarial refutation pass on
2026-08-26. The wording is verbatim. No broader form may appear anywhere.

### 4.1 Fidelity — narrowed

> Plutus is, to our knowledge, the first open, historically-replayable exchange simulator
> to represent a national **order-admission** rulebook — price-dependent tick grid, daily
> price-limit band, board lot, ATO/ATC auction eligibility, per-order-type time-in-force,
> and the pre-funding regime — as **effective-dated rule editions resolved per simulated
> date**, and the first to implement Vietnam's at all. Effective-dated rule editions
> already exist in open source for *calendars and parameters* — QuantLib's year-conditional
> national holiday rules and its per-market `Settlement` vs `Exchange` calendars,
> `exchange_calendars`' dated session-time editions (XKRX 1978–2016), LEAN's dated CME
> `date,initial,maintenance` margin tables, RQAlpha's `get_long_margin_ratio(date)` — but
> in no engine do they govern whether an order is admitted. Separately, Vietnamese brokers
> ship proprietary live-forward paper-trading simulators (SSI iWin, VPS SmartEasy,
> vnstockgame) that enforce the *current* edition of these rules; none replays a historical
> date under the edition then in force, and none publishes its rule set.

Three supporting sentences, also verbatim, that pre-empt the specific refutations:

> **On settlement.** We claim no novelty for T+N over a settlement calendar distinct from a
> trading calendar: QuantLib has shipped per-market `Settlement`/`Exchange`/`GovernmentBond`
> calendars for two decades and advances settlement as
> `calendar_.advance(d, settlementDays_, Days)`; the split is a standard vendor product
> (Copp Clark's "Exchange Settlement" category) and NSE India publishes trading and
> clearing holidays separately. Our narrower claim is that no order-driven backtester wires
> such a calendar to an unsettled-cash and unsettled-share pool — LEAN's
> `DelayedSettlementModel`, the only T+N model in a major open-source backtester, counts
> settlement days on the security's *trading* calendar, and neither QuantLib (54 country
> calendars) nor `exchange_calendars` (74 exchange calendars) contains Vietnam.

> **On margin.** We claim no novelty for utilisation-tested margin with warning tiers:
> LEAN's `DefaultMarginCallModel` warns at 5% margin remaining and calls when total margin
> used exceeds portfolio value × (1 + buffer), and TqSdk computes
> `risk_ratio = margin / balance` at daily settlement. Nor is the absence of a published
> maintenance ratio unique to Vietnam — Chinese futures (风险度) and Indian SPAN-plus-exposure
> share the structure. Our narrower claim is the specific composition: MR = IM + VM with VM
> accruing only on losing positions, in a derivatives account segregated from the equity
> account under VSD/VSDC rules, tested at the published utilisation tiers.

> **On tick grids.** Already conceded in your prior survey — LEAN's
> `EquityPriceVariationModel` implements Reg NMS Rule 612, so *price-dependent* tick grids
> are precedented; claim the Vietnamese grid and its dated 2016-09-12 revision, not the
> concept.

**Two items to verify before publication, flagged by the attack itself. [U]** (i) The VSD
80/90/100% utilisation tiers are load-bearing for the margin sentence. *Status in this
repo: the rulebook §6.3 now sources them to Article 13 of the derivatives margin rulebook
chain (QĐ 96/QĐ-VSD → QĐ 61/QĐ-VSD Art. 13 → QĐ 12/QĐ-HĐTV → QĐ 26/QĐ-HĐTV) at
confidence `high`, with the note that one older MBS PDF misprints level 3 as 90%* `[rb]`.
(ii) vnstockgame's lot rule — see §2.3 item 10.

### 4.2 Data-source degradation and indeterminacy — narrowed twice

The first pass narrowed this to the sentence below. **Its final clause has been struck**,
because a later pass refuted it (§2.4): Forex Strategy Builder reported an ambiguity count
in 2011, and Claeys (2026) reportedly reports an ambiguity rate. The surviving text is
quoted verbatim with the struck clause shown as struck.

> Publishing a data contract in which the source declares its capability, and tying
> execution fidelity to that declaration, is established practice: LEAN's `BaseData`
> contract has each dataset declare `SupportedResolutions()`, `DefaultResolution()` and
> `IsSparseData()`, and its `EquityFillModel` cascades over the subscribed data types
> (quote tick → quote bar → trade tick → trade bar), attaching a per-fill warning that
> names the degradation; NautilusTrader publishes a fidelity ladder from L3 order book down
> to bars, makes the venue's `book_type` the declared capability, and states that bar data
> "cannot establish intrabar price order, spread, depth, or queue position." What none of
> them does is distinguish *"this order did not fill"* from *"this data cannot establish
> whether this order filled."* Every engine we examined collapses the second case into the
> first — by assumption (LEAN's `// assume the order completely filled`; TradeStation's
> target-hit-first rule), by heuristic path (NautilusTrader's `Open→High→Low→Close` intrabar
> walk, which its own documentation calls "a deterministic heuristic, not a reconstruction"),
> or by silence (a skipped bar, a still-resting order, a NaN price). Plutus returns
> INDETERMINATE as a distinct outcome delivered to the caller alongside accepted, rejected,
> filled and cancelled, and reports the INDETERMINATE rate for a run as a bound on what the
> data could not decide. ~~We found no backtester and no paper that does either.~~

The struck clause is replaced by §4.3, which states the residue that survives both attacks.

**Sentences that may no longer be written**, per the refutation: "data-source agnostic" as
a novelty claim (LEAN, NautilusTrader and at least one small GitHub project use the
phrase); "accepts any source meeting a published data contract" (LEAN's `BaseData` is
exactly this); "degrades explicitly where the data is weaker" (LEAN emits *"Warning: No
quote information available at …"* on the fill event itself); "adapts fidelity to the
resolution of the data" (MT5's five tick-generation modes have done this since 2010;
NinjaTrader, TradingView and TradeStation all ship a fidelity switch); and anything
implying nobody documents what bar data cannot support (NautilusTrader documents it in
almost our exact words).

**Unverified, and material to the first half of that paragraph. [U]** We could not locate
the call site that enforces LEAN's `SupportedResolutions()` at subscription time — it is
absent from `SecurityService.cs`, `QCAlgorithm.cs`, `SubscriptionManager.cs` and
`Messages.Algorithm.cs`. **Do not assert that LEAN rejects an unsupported resolution;
assert only that the contract declares it.** `[L-basedata]`

**One term collision to defuse in a footnote:** Basel's 1996 traffic-light backtesting
framework has a yellow zone (5–9 exceptions) that is an explicitly inconclusive verdict.
Different sense of "backtesting" (VaR model validation), but a risk reviewer may raise it
**[R]** `[basel]`.

### 4.3 Fill determination — narrowed

> Fill determination is already a swappable policy in several engines (LEAN's `IFillModel`,
> NautilusTrader's `FillModel` — whose `prob_fill_on_limit ∈ {0.0, p, 1.0}` is itself a
> hard/probabilistic/soft axis — RQAlpha's `AbstractMatcher`, hftbacktest's `QueueModel`),
> and running one strategy under a pessimistic/optimistic/random family and displaying the
> divergence has prior art in retail tooling since 2011 (Forex Strategy Builder's
> `InterpolationMethod` enum, `BacktestEval.Ambiguous`, reported `AmbiguousBars` statistic
> and Method Comparator) and, for intrabar stop/target ordering, in a 2026 working paper
> that reports the best-case/worst-case gap as its headline result. **Plutus's contribution
> is narrower: prior work treats ambiguity as a path-ordering question between two of the
> trader's own already-triggered orders within a bar and resolves it as an aggregate
> bar-level diagnostic, whereas we return INDETERMINATE as a per-order status through a
> broker-facing API for ambiguity of fill *existence* — a resting limit order whose fill
> depends on unobserved queue, volume, auction matching or a price-band lock — and report
> the indeterminate rate and the cross-policy spread jointly, per data resolution and per
> exchange rule, rather than collapsing them to the conservative or averaged point estimate
> that every prior tool recommends.**

**Guardrails, verbatim from the refutation.** Do not write "pluggable," "swappable,"
"hard/soft/probabilistic family," "the spread is the reported result," or "no prior art for
an indeterminate outcome" — all four are refuted. Do write: per-order INDETERMINATE status
across a broker API; ambiguity of fill *existence* rather than fill *ordering*; ambiguity
generated by *exchange rules* (ATO/ATC, band lock, tick/lot grid) rather than by OHLC path
alone; and refusal to collapse the spread. Cite FSB, Claeys 2026 and arXiv:2603.20319
explicitly and early — a reviewer who finds any of them un-cited will assume we did not
look.

**Note on internal consistency.** Our own design document (`spec §8`) still contains the
sentence *"Run one strategy against all three policies and report the spread… This is the
selling point"* and the phrase "pluggable policy". That is design-internal vocabulary. It
must not be carried into the paper in that form; §4.3 above is the publishable form.

### 4.4 What is left, in one place

| Component | Status after attacks |
|---|---|
| National **order-admission** rulebook as effective-dated rule editions resolved per simulated date | **Survives.** Dated editions exist for calendars and parameters, never for admission. |
| Vietnam's rulebook at all, in an open historically-replayable simulator | **Survives**, subject to naming the three broker paper-trading products and the unread ResearchGate 2026 paper. |
| Settlement-business-day calendar wired to unsettled cash **and** unsettled shares in an order-driven engine | **Survives.** T+N and settlement-vs-trading calendars are both precedented; the wiring is not. |
| MR = IM + VM, VM loss-only, segregated derivatives account, published utilisation tiers | **Survives as a composition only.** Utilisation tests, warning tiers and no-published-maintenance-ratio regimes are all precedented. |
| Per-order INDETERMINATE for ambiguity of fill **existence**, through a broker-facing API, attributed to a named exchange rule | **Survives.** Bar-level path-ordering ambiguity with an aggregate count is prior art from 2011. |
| Joint reporting of indeterminate rate and cross-policy divergence, per data resolution and per exchange rule | **Survives.** Reporting a divergence across execution conventions is routine practice; the joint, rule-attributed, per-resolution form is not. |
| "Data-source agnostic"; "published data contract"; "explicit degradation"; "fidelity adapts to resolution" | **Dropped as novelty.** Established practice in LEAN, NautilusTrader, MT5, NinjaTrader, TradingView, TradeStation. |
| "Pluggable / swappable fill determination" | **Dropped as novelty.** Refuted five times over. |
| "Nobody models exchange microstructure rules"; "nobody models settlement"; "nobody has an indeterminate outcome" | **Dropped entirely.** Each is false. |

---

## 5. Positioning

Plutus is a simulated Vietnamese exchange a strategy connects to the way it connects to a
broker: submit an order, receive accepted / rejected / partially filled / cancelled /
expired / indeterminate, and read holdings, cash and margin — with the exchange, not the
strategy author, remembering the settlement cycle, the margin regime and the rulebook. Its
contribution is threefold and narrow. First, it represents a **national order-admission
rulebook as effective-dated rule editions resolved per simulated date** — the price-dependent
tick grid, the daily band, the board lot, ATO/ATC auction eligibility, per-order-type
time-in-force and the pre-funding regime — where prior engines carry dated *calendars* and
dated *parameters* but never dated *admission* rules, and it is the first to implement
Vietnam's at all. Second, it wires a **VSDC settlement-business-day calendar** (which
diverges from the exchange trading calendar around Tết) to both an unsettled-cash pool and
an unsettled-share pool, and runs Vietnamese derivatives margin as MR = IM + VM with VM
accruing only on losing positions in a segregated deposit account tested at published
utilisation tiers. Third, it returns **INDETERMINATE as a per-order status through the
broker-facing API for ambiguity of fill *existence*, attributed to the exchange rule that
could not be evaluated**, and reports that rate jointly with the divergence across fill
policies, per data resolution and per rule. **In the same breath, the scope limits:** there
is no market impact and never will be in a replay design, so every result is conditional on
the simulated order not moving the market; this iteration assumes a **domestic** investor
and does not enforce foreign-ownership room, a deliberate cut whose cost is measurable —
34,653 room observations in our corpus sit below a single 100-share lot, so the constraint
binds and ignoring it is a choice rather than a discovery that it never binds; final
settlement falls back to the data source's close where no settlement price is supplied,
which across all 46 expiries from 2022-08-18 to 2026-08-20 costs a mean absolute error of
0.042% and a worst case of 0.333%; continuous-session fill determination is **not
empirically validated**, which is precisely why the indeterminate rate is reported as a
bound on ignorance rather than a fill rate; the rulebook behind all of this is 63%
high-confidence by row, with every tick, lot and band value after 2022-03-31 corroborated
rather than gazetted-verified because Phụ lục III of the VNX Quy chế has never been
obtained; and landing the session does not retro-validate our published measurements, three
of which still come from SQL that parallels the rules rather than calling them.

---

## 6. Sources

Format: `key` — what it is · read as · locator.

### Engine source and documentation

| Key | Source | Read as |
|---|---|---|
| `L-adm` | LEAN `Algorithm/QCAlgorithm.Trading.cs` L1071 (`OrderQuantityLessThanLotSize`); `Common/Brokerages/IBrokerageModel.cs` (`CanSubmitOrder`) | [V] `master`, 2026-08-26 |
| `L-settle` | LEAN `Common/Securities/ISettlementModel.cs`, `DelayedSettlementModel.cs`, `Common/Securities/Equity/Equity.cs`, `Common/Brokerages/DefaultBrokerageModel.cs` L291 | [V] |
| `L-tick` | LEAN `Common/Securities/IPriceVariationModel.cs`, `EquityPriceVariationModel.cs` | [V] |
| `L-round` | LEAN `Engine/TransactionHandlers/BrokerageTransactionHandler.cs` L1797/L1811/L1899 | [V] |
| `L-band` | LEAN path-grep of the 6,851-path tree for `circuit\|limitup\|limit_up\|priceband\|halt\|auction`; `Data/market-hours/market-hours-database.json` grep for `vietnam\|hose\|hnx`; `Common/Market.cs` | [V-neg] |
| `L-fill` | LEAN `Common/Orders/Fills/IFillModel.cs`, `FillModel.cs`, `Common/Securities/Security.cs` (`SetFillModel(IFillModel)` / `SetFillModel(PyObject)`) | [V] |
| `L-eqfill` | LEAN `Common/Orders/Fills/EquityFillModel.cs` (1,100 lines), `Common/Messages/Messages.Orders.Fills.cs` | [V] |
| `L-basedata` | LEAN `Common/Data/BaseData.cs` (434 lines); QuantConnect dataset-contribution docs | [V] source, [R] docs; enforcement call site **[U]** |
| `L-mcm` | LEAN `Common/Securities/DefaultMarginCallModel.cs` L60, L77–L101 | [V] |
| `L-spm` | LEAN `Common/Securities/SecurityPortfolioManager.cs` (`TotalMarginUsed`) | [V] |
| `L-fut` | LEAN `Common/Securities/Future/FutureSettlementModel.cs` | [V] |
| `L-cme` | LEAN `Data/future/cme/margins/ES.csv` | [V] |
| `N-adm` | NautilusTrader `crates/execution/src/matching_engine/mod.rs` L2697+, L2289 (`process_status`); `crates/risk/src/engine/mod.rs` | [V] `develop`, 2026-08-26 |
| `N-tick` | NautilusTrader `matching_engine/mod.rs` L1329 (`price_matches_tick`) and its caller; `crates/model/src/instruments/mod.rs` L428–448 | [V] |
| `N-settle` | NautilusTrader v1.231.0 tree grep for `settle`; `crates/execution/src/matching_engine/settlement.rs` | [V-neg] |
| `N-margin` | NautilusTrader `crates/model/src/accounts/margin.rs`, `margin_model.rs`; `docs/concepts/backtesting/accounts-and-margin.md` | [V] |
| `N-fill` | NautilusTrader `crates/execution/src/models/fill.rs`; `nautilus_trader/backtest/models/fill.pyx` @ v1.231.0; `docs/concepts/backtesting/fill-models.md` (153 lines) | [V] |
| `N-filldoc` | NautilusTrader `docs/concepts/backtesting/fill-models.md` | [V] |
| `N-bar` | NautilusTrader `docs/concepts/backtesting/bar-execution.md`, `data-and-venues.md`, `fill-prices-and-matching.md` | [V] |
| `Z-ctl` | zipline-reloaded `src/zipline/finance/controls.py`; `src/zipline/algorithm.py` | [V] `main` |
| `Z-tick` | zipline-reloaded `src/zipline/assets/_assets.pyx`, `src/zipline/finance/execution.py` | [V] |
| `Z-exec` | zipline-reloaded `src/zipline/finance/execution.py` | [V] |
| `Z-ledger` | zipline-reloaded `src/zipline/finance/ledger.py` (the three `account.*_margin_requirement = 0.0` lines); `src/zipline/finance/` directory listing | [V] — flagged for re-check before publication |
| `Z-slip` | zipline-reloaded `src/zipline/finance/slippage.py`, `blotter/blotter.py`, `blotter/simulation_blotter.py`, `cancel_policy.py` | [V] |
| `B-sub` | Backtrader `backtrader/brokers/bbroker.py` (`check_submitted`), `backtrader/order.py` | [V] — flagged for re-check before publication |
| `B-comm` | Backtrader `backtrader/comminfo.py` | [V] |
| `B-fill` | Backtrader `backtrader/fillers.py`; broker docs | [V] |
| `B-coc` | backtrader.com/docu/broker (the `coc` "cheating" definition) | [V] |
| `B-cal` | Backtrader `backtrader/tradingcal.py` | [V] |
| `VB-enum` | vectorbt `vectorbt/portfolio/enums.py` | [V] `master` |
| `VB-nb` | vectorbt `vectorbt/portfolio/nb.py`; vectorbt.dev Portfolio API docs | [V] source, [R] docs |
| `Q-exch` | Qlib `qlib/backtest/exchange.py` (958 lines) incl. L152 warning; `qlib/backtest/decision.py`; `qlib/backtest/__init__.py` | [V] `main` |
| `Q-pos` | Qlib `qlib/backtest/position.py` (`ST_CASH`, `cash_delay`), `qlib/backtest/executor.py` L270/L298 | [V] |
| `RQ-match` | RQAlpha `rqalpha/mod/rqalpha_mod_sys_simulation/matcher/base.py`, `bar_matcher.py`, `tick_matcher.py`, `signal_matcher.py`, `mod.py` (`parse_matching_type`) | [V] `master` |
| `RQ-lim` | RQAlpha `rqalpha/utils/price_limits.py`; `rqalpha/mod/rqalpha_mod_sys_risk/validators/price_validator.py` | [V] |
| `RQ-val` | RQAlpha `rqalpha_mod_sys_risk/validators/` (`cash_validator.py`, `is_trading_validator.py`, `self_trade_validator.py`), `sys_accounts/position_validator.py` | [V] |
| `RQ-pos` | RQAlpha `rqalpha/mod/rqalpha_mod_sys_accounts/position_model.py`; `rqalpha/model/instrument.py` (`market_tplus`, `get_long_margin_ratio`) | [V] |
| `RQ-port` | RQAlpha `rqalpha/portfolio/__init__.py`, `rqalpha/portfolio/account.py` | [V] |
| `H-queue` | hftbacktest `hftbacktest/src/backtest/models/queue.rs`; docs `order_fill.html` @ py-v2.1.0; Probability Queue Models tutorial | [V] |
| `H-tree` | hftbacktest path-grep for `settle\|margin\|tick_size\|lot` — zero matches | [V-neg] |
| `A-ex` | ABIDES `abides-markets/abides_markets/agents/exchange_agent.py` (incl. L219 comment) | [V] @ `f9cbe51342b7dedd9587e4e069040d68a5c6477f`, 2023-12-13 |
| `A-ord` | ABIDES `abides_markets/orders.py`; package grep for `price_limit\|limit_up\|limit_down\|circuit\|settlement\|T+2\|margin\|lot_size\|board_lot` | [V-neg] |
| `A-ob` | ABIDES `abides-markets/abides_markets/order_book.py`, `price_level.py` | [V] |
| `E-paper` | Zhong, Yang, Liu, Tang & Yang, "EvoMarket: A High-Fidelity and Scalable Financial Market Simulator," arXiv:2604.18046 (20 Apr 2026) | **[R]** — HTML fetch-summarised twice, consistently; source not inspected; **obtain PDF** |
| `VN-alpha` | vnpy `vnpy/alpha/strategy/backtesting.py` L619+ (`cross_order`) | [V] / [V-neg] `master` |
| `VN-cta` | vnpy_ctastrategy `backtesting.py` (1,269 lines) grep for `limit_up\|limit_down\|涨跌停\|t+1\|tplus\|settle\|price_limit` | [V-neg] |
| `HB-rule` | Hummingbot `hummingbot/connector/trading_rule.pyx`, `exchange_py_base.py` | [V] `master` |
| `HB-pt` | Hummingbot `connector/exchange/paper_trade/paper_trade_exchange.pyx` (1,139 lines); `strategy_v2/backtesting/` | [V] |
| `PA-bt` | PyAlgoTrade `pyalgotrade/broker/backtesting.py` | [V] — repo **archived: true**, last push 2023-11-13 |
| `PA-fill` | PyAlgoTrade `pyalgotrade/broker/fillstrategy.py` | [V] |
| `BT-core` | bt `bt/core.py`, `bt/backtest.py` | [V] `master` |
| `QS-broker` | QSTrader `qstrader/broker/simulated_broker.py` | [V] `master` |
| `QS-port` | QSTrader `qstrader/broker/portfolio/portfolio.py`, `qstrader/execution/order.py` | [V] |
| `MG-fill` | mbt_gym `mbt_gym/stochastic_processes/fill_probability_models.py`; ICAIF '23 paper | [V] |
| `QL-uk` | QuantLib `ql/time/calendars/unitedkingdom.hpp` (`enum Market { Settlement, Exchange, Metals }`) | [V] `master` |
| `QL-us` | QuantLib `ql/time/calendars/unitedstates.cpp` (seven impls; year-conditional rules at L36/L47, L69/L80, L92, L213, L224, L298) | [V] |
| `QL-bond` | QuantLib `ql/instruments/bond.cpp` (`Bond::settlementDate`) | [V] |
| `QL-cal` | QuantLib `ql/time/calendars/` enumeration — 54 country calendars, **no Vietnam** | [V-neg] |
| `XC-xkrx` | `exchange_calendars` `exchange_calendar_xkrx.py` (dated `open_times`, `close_times`, `break_start_times`) | [V] |
| `XC-list` | `exchange_calendars` — 74 `exchange_calendar_x*.py` files, **no XSTC/Vietnam** | [V-neg] |
| `TQ-trade` | TqSdk `tqsdk/sim/trade.py` (`risk_ratio`, `_on_settle`, `_get_future_margin`) | [V] |
| `FSB-eval` | Forex Strategy Builder `Backtester/Backtester Publics.cs` L25; `Backtester/Backtester Interpolation.cs` (8 `Ambiguous` sites) | [V] mirror `nuggett11/Forex-Strategy-Builder`, created 2011-04-27 |
| `FSB-stat` | FSB `Backtester/Backtester Statistics.cs` (`ambiguousBars` → `AmbiguousBars`); shipped `ReadMe.html` (v2.57.21.0, 2011-03-21); changelog | [V] |
| `FSB-cmp` | FSB `Dialogs/Comparator.cs` (809 lines); forexsb.com wiki pages on interpolation methods, the Comparator and reliable backtesting | [V] |
| `mt5` | MetaTrader 5 Strategy Tester help (five tick-generation modes); MT4 `Modelling quality` report field | [R] |
| `nt8` | NinjaTrader 8 `Order Fill Resolution`; TradingView Bar Magnifier; TradeStation Look-Inside-Bar Backtesting | [R] |
| `cc` | Copp Clark "Exchange Settlement (S)" holiday category | [R] |
| `nse` | NSE India Trading Holidays vs Clearing Holidays | [R] |

### Literature

| Key | Source | Read as |
|---|---|---|
| `lit-pw` | Patton & Weller, "What You See Is Not What You Get: The Costs of Trading Market Anomalies," *JFE* 137(2), 2020; SSRN 3034796 | [V] full text extracted |
| `lit-nmv` | Novy-Marx & Velikov, "A Taxonomy of Anomalies and Their Trading Costs," *RFS* 29(1), 2016; NBER w20721 | [R] |
| `lit-fim` | Frazzini, Israel & Moskowitz, trading-costs evidence from >$1tn of live trades | [R] |
| `lit-menkveld` | Menkveld et al., "Nonstandard Errors," *Journal of Finance* 79(3), 2024, 2339–2390; SSRN 3961574 | [R] |
| `lit-pbo` | Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest Overfitting," *JCF* 20(4), 2016; SSRN 2326253 | [V] |
| `lit-dsr` | Bailey & López de Prado, "The Deflated Sharpe Ratio," *JPM*, 2014; SSRN 2460551 | [V] |
| `lit-pmfc` | Bailey, Borwein, López de Prado & Zhu, "Pseudo-Mathematics and Financial Charlatanism," *Notices of the AMS* 61(5), 2014 | [R] |
| `lit-ahm` | Arnott, Harvey & Markowitz, "A Backtesting Protocol in the Era of Machine Learning," *JFDS* 1(1), 2019; SSRN 3275654 | [V] full text extracted |
| `lit-hlz` | Harvey, Liu & Zhu, "…and the Cross-Section of Expected Returns," *RFS* 29(1), 2016; NBER w20592 | [R] |
| `lit-hxz` | Hou, Xue & Zhang, "Replicating Anomalies," *RFS* 33(5), 2020; NBER w23394 | [R] |
| `lit-jkp` | Jensen, Kelly & Pedersen, "Is There a Replication Crisis in Finance?", *JF* 78(5), 2023 | [R] |
| `lit-du` | Du, "Machine Learning Enhanced Multi-Factor Quantitative Trading," arXiv:2507.07107 | [V] — **single-author preprint, self-reported, not peer-reviewed** |
| `lit-ir` | Yin, Miki, Lesnichenko & Gural, "Implementation Risk in Portfolio Backtesting," arXiv:2603.20319, 19 Mar 2026 | [V] full HTML extracted and grepped |
| `claeys` | Claeys, "When Backtests Guess: How Trading Platforms Silently Fabricate Results," SSRN 6240638, 14 Feb 2026 | **[U]** — SSRN ECONNRESET ×2; **obtain and verify the 18.47% and $73,900 figures** |
| `basel` | Basel Committee 1996 traffic-light backtesting framework (VaR model validation) | [R] |
| `vn-hls` | Huang, Liu & Shu, "Factors and anomalies in the Vietnamese stock market," *PBFJ* 82:102176, 2023 | [V] full text extracted and word-counted |
| `vn-nsvm` | Nguyen, Sensoy, Vo & von Mettenheim, "Does short-term technical trading exist in the Vietnamese stock market?", *Borsa Istanbul Review*, 2020 | [V] full text extracted |
| `vn-pham` | Pham, Luu & Tran, "Multi-agent reinforcement learning approach for hedging portfolio problem," *Soft Computing* 25(12), 2021, DOI 10.1007/s00500-021-05801-6 | [V] |
| `vn-doluong` | Do & Luong, "Bias-free Trading Algorithms with Momentum Scores for the Vietnamese Stock Market," SoICT '23, DOI 10.1145/3628797.3628993 | [V] abstract only — ACM full text 403 |
| `vn-tick` | Vo & Doan, "Minimum tick size, market quality and costs of trade execution in Vietnam," *PLOS ONE* 18(5):e0285821, 2023 | [R] |
| `vn-band` | GARCH study of the 2007–2009 HOSE/HNX fluctuation-limit reductions | [R] |
| `vn-fol` | VinaCapital FOL primer; ASEAN Briefing on the 2025 decree | [R] |
| `vn-awesome` | `DataCore-VietNam/awesome-vietnam-finance-data`; `thinh-vu/vnstock` README | [V] / [V-neg] |
| `vn-github` | GitHub repo search across five phrasings; `frydaiii/trading-research` | [V] |
| `vn-dnse` | dnse.com.vn/hoc/backtest-la-gi | [V-neg] |
| `vn-algotrade` | hub.algotrade.vn "Specialized backtesting module: benefits and development" | [V-neg] |
| `vn-plutus` | Nguyen, Ta & Vo, "PLUTUS Open Source," arXiv:2505.14050 | [V] |
| `vn-rg` | "Design and Implementation of an AI-Driven Algorithmic Trading Simulation Platform…", ResearchGate 399252297, March 2026 | **[U]** — 403; **must be read before submission** |
| `vsg` | vnstockgame.com/luat-choi.html | [V] |
| `iwin` | SSI iWin product description | [V] — rule completeness beyond the marketing text is **[U]** |
| `smarteasy` | VPS SmartEasy derivatives simulation | [R] |
| `cn-chen` | Chen, Gao, He, Jiang & Xiong, "Daily Price Limits and Destructive Market Behavior," *Journal of Econometrics* | [V] |
| `cn-du2` | Du, arXiv:2506.06356 | [V-neg] |
| `cn-chinext` | "Effectiveness of price limits: Evidence from China's ChiNext market," *PLOS ONE* 2023, DOI 10.1371/journal.pone.0287548 | [R] |
| `cn-asym` | "Asymmetric effectiveness of price limits," *RQFA* 2024, DOI 10.1007/s11156-024-01333-w | [R] |
| `cn-mom` | "Price Limit Dominates Daily Momentum Effect in the Chinese Stock Market," 2025 | [R] |
| `cn-t1` | "A unique 'T+1 trading rule' in China: Theory and evidence," *JBF* | [R] |
| `id-ara` | AEI Indonesia auto-rejection explainer; Kompas 2023-08-31 on symmetric ARA/ARB at 35% | [R] |
| `tw-magnet` | Cho, Russell, Tiao & Tsay, *Journal of Empirical Finance*, 2003 | [R] |
| `tw-value` | Taiwan value-premium / limit-hit-frequency study, *PBFJ* | [R] |
| `kr-band` | Korea 2015 band relaxation; arXiv:1805.04728 | [R] |
| `th-band` | Thailand SET band level post-COVID | **[U]** — verify at set.or.th |
| `abm-mizuta` | Mizuta & Yagi, arXiv:2309.10220 | [V] |
| `abm-magnet` | "The Magnet Effect of Price Limits: An Agent-Based Approach," *EMFT* 61(7), DOI 10.1080/1540496X.2024.2434042 | [R] |
| `rb` | `docs/reference/vn-exchange-rulebook-2020-2026.md` §6.3 (VSD utilisation tiers, Art. 13 chain) | [V] this repo |

---

## 7. Must be closed before submission

| # | Item | Why it is load-bearing |
|---|---|---|
| 1 | **Obtain and read ResearchGate 399252297** (HOSE/HNX AI trading simulation platform, March 2026) `[vn-rg]` | The only priority risk found on "Vietnamese trading simulation platform". |
| 2 | **Obtain the Claeys SSRN PDF** and verify 18.47% and $73,900 verbatim `[claeys]` | It is cited as refuting our own earlier indeterminacy claim; citing an unread abstract for that is worse than not citing it. |
| 3 | **Obtain the EvoMarket PDF** `[E-paper]` | It is the nearest neighbour on Claim 1 and is currently [R] from fetch-summarised HTML. |
| 4 | **Re-open zipline `ledger.py` and backtrader `bbroker.py`** `[Z-ledger]` `[B-sub]` | Both carry load-bearing weight and were read via a fetch summariser rather than byte-for-byte. |
| 5 | **Verify the SET band level from an official source** `[th-band]` | The ±15% figure is COVID-era news. |
| 6 | **Verify the KRX ATO/ATC priority change against the HOSE/BVSC handbook**, not news | Rulebook §10 row 2 states the narrow form (priority abolished only against earlier ceiling-buy / floor-sell LOs); news coverage states a broader one. |
| 7 | **Do not describe LEAN as rejecting an unsupported resolution** `[L-basedata]` | The enforcement call site was not found. |
| 8 | **Obtain Phụ lục III of the VNX Quy chế** | Every tick, lot and band value from 2022-03-31 onward is corroborated, not gazetted-verified. Highest-value single retrieval outstanding. |
