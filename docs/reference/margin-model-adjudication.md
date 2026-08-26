# Margin model adjudication — which figure, if any, the paper prints

**Status:** decided. **Date:** 2026-08-26. **Scope:** the two Vietnamese derivatives margin
models in this repository and the three call-rate figures computed from them.

**Verdict in one line: neither figure should be published as a call rate.** The two models
do not disagree — they are the same functional form, and once a rate confound is removed a
funding multiple reproduces all three published counts exactly. What disagrees is two
unsourced cushions wearing different names, and at each cushion's own zero point the metric
is a constant. `measurements/margin_incidence_account.py` now computes the replacement
statistic; both legacy figures stay measured and reported, and nothing here restates them.

Every number below was executed against
`/Users/nadan/algotrade-research/dataset/hermes-parquet` (381 entries, 20 front-month
contracts, 401 daily observations, 2021-06-01..2022-12-29) and is reproducible from
`measurements/margin_incidence.py` and `measurements/margin_incidence_account.py`.

---

## 1. The question

Two models of Vietnamese derivatives margin ship in this repository and were reported as
disagreeing. Before either number goes into a paper, which is right?

- **Legacy, per-position** (`src/plutus/market/margin.py`, `HNXDSExchange.sustains`). Marks
  one position to each settlement price and calls when `equity / notional` falls below a
  `maintenance_rate`. Over 381 front-month VN30F longs it reports **29 / 48 / 56** calls —
  **7.61% / 12.60% / 14.70%** — at 5 / 10 / 20 sessions held. These are the *published*
  figures.
- **Account-level** (`src/plutus/market/session/deposit.py`,
  `account_margin_requirement`). `MR = IM + VM` over the whole account portfolio, `IM`
  recomputed on the **current** price, `VM` counted **only** when the account is in net
  loss, monitored as `utilisation = MR / margin assets` against a warning/call/forced
  ladder.

The reported disagreement: funded at exactly the opening requirement — "the only unfitted
funding level" — the account model calls **100%** of entries at every holding period, and
*no* funding multiple was said to reproduce 29 / 48 / 56 jointly.

The hypothesis this adjudication was asked to test, not assume: that the 100% is
arithmetically inevitable, and that the defect is in the **experiment**, not in either
model.

---

## 2. Which model is right about the *rule*

Not in dispute, and not what the disagreement was about. **The account model is right about
the rule.** Vietnam publishes no maintenance margin ratio at any date; the regulated test is
a utilisation ratio against a three-level ladder.

Sourcing, with confidence stated rather than implied. **The status labels below are the
research pass's, not mine** — I ran no web access in this session and re-verified none of
them. Read them as "a reader reported reading the primary document", which is weaker than
"verified" normally means in this repository:

| Fact | Status | Source |
|---|---|---|
| `MR = IM + VM (+ SM + DM)`, VM **loss-only**, netted across the portfolio | **VERIFIED, primary** | SSI investor-education deck, `ftp2.ssi.com.vn/Customers/GDDT/CKPS/14.TyLeSuDungTSKQBienDongTrongGioGiaoDich.pdf` — verbatim `VM chỉ tính trong trường hợp lỗ ròng. Nếu lãi ròng, VM = 0`; IM worked on the *current* price; SM `tạm thời chưa áp dụng`, DM physical-delivery only, so IM+VM is the whole of it for VN30F |
| `Tỷ lệ sử dụng tài sản ký quỹ = Giá trị ký quỹ yêu cầu / Giá trị tài sản ký quỹ hợp lệ` | **VERIFIED, primary** | same deck; Pinetree uses the identical formula |
| No maintenance margin ratio is published anywhere | **VERIFIED as a negative** | VSDC's published margin tables list only `Tỷ lệ ký quỹ ban đầu` (e.g. `vsdc.vn/vi/ad/176840`, 17% across VN30F2412/2501/2503/2506) |
| IM ratio series 10% → 13% (2018-07-18) → 17% (2022-12-15), issued as *thông báo* with no `quyết định` number | **VERIFIED** | government source for the 2022 step: `xaydungchinhsach.chinhphu.vn/tu-15-12-dieu-chinh-ty-le-ky-quy-chung-khoan-phai-sinh-119221212230618064.htm`; the notice-not-decision publication pattern re-confirmed at `vsdc.vn/vi/ad/199445` and `vsdc.vn/vi/ad/198157`, neither carrying a decision number |
| The **80 / 90 / 100** utilisation ladder | **REPORTED, not verified — downgrade from `high`** | The rulebook cites Article 13 of the derivatives clearing rulebook (QĐ 96/QĐ-VSD → QĐ 61 → QĐ 12 → QĐ 26/QĐ-HĐTV 2025-04-16). **The article text was never obtained.** Corroboration is two secondary reproductions (LuatVietnam's record; a newer MBS guide) against one older MBS PDF that misprints level 3 as 90%. `vsdc.vn` today has no "Thông tin về ký quỹ" page in navigation in either language, and no repo citation carries a URL |
| Broker ladders are **tighter** than 80/90/100 and are commercial | **VERIFIED for two firms** | Pinetree 75/85/90; VFS 85/87/90 (`vfs.com.vn/cach-dau-tu-chung-khoan-phai-sinh`). SSI treats 90.67% as `Ngưỡng Cảnh báo 1`. So `BrokerTerms.DEFAULT` is the VSD-level shape, not a broker's |

**Caveat, stated because it is load-bearing.** The web research above was carried out by
subagents in a session whose search budget was exhausted; the ladder row in particular could
not be re-verified from primary text, and I did not re-verify any of it myself. Nothing in
the algebra below depends on the ladder *levels* — it depends only on (a) IM being
proportional to the current price and (b) VM being non-negative and zero in profit. Both of
those are primary-sourced above. If either is misread, the degeneracy changes; if both hold,
it is forced.

**Nothing here rehabilitates `maintenance_rate`.** It models a quantity Vietnam does not
publish, and that remains true after everything below.

---

## 3. The algebra

One long contract, multiplier `M`, entry price `P₀`, current price `P`, initial-margin rate
`r` (VSDC's ratio plus whatever broker buffer is assumed), deposit `A = k · r · M · P₀`.

Define the **peak requirement multiple**

```
U(P) = MR(P) / MR(P₀)          where MR(P) = r·M·P + M·max(0, P₀ − P)
```

`MR(P₀) = r·M·P₀`, because VM is zero at the variation-margin reference. So

```
P ≥ P₀ :  U = P / P₀                                  ≥ 1
P < P₀ :  U = 1 + d · (1 − r) / r      (d = drawdown)  > 1
```

`U` is a convex V in the price with its vertex **exactly at the entry price** and vertex
value **exactly 1**. Utilisation is `U / k`. Three consequences, none of which needs data:

1. **`min U = 1`, attained only when the price has not moved.** So at `k = 1` utilisation is
   `≥ 1` at every possible price. `margin_status` (`deposit.py:590`) tests
   `utilisation >= terms.forced_close_utilisation` and `forced_close_utilisation` is
   `Decimal('1.00')` (`broker.py:67`) — an inclusive comparison. **Every price is FORCED,
   including no move at all.**
2. **A rung `θ` is certain for any `k ≤ 1/θ`.** With `BrokerTerms.DEFAULT`: warning certain
   below **1.25**, call certain below **1.1111**, forced certain at **1.00**.
   `degenerate_funding_ceiling()` now computes this from whatever terms a caller passes.
3. **It is not "any adverse tick" — it is any tick.** On the upside `U = P/P₀`, so a *rally*
   raises utilisation too: IM is recomputed on the higher price while the profit is not
   credited to assets.

Executed at `r = 0.18`, `P₀ = 1280`, `k = 1`:

| price | move | `MR / assets` | status |
|---|---|---|---|
| 1280.0 | 0.0000% | **1.00000000** | FORCED |
| 1280.1 | +0.0078% | 1.00007812 | FORCED |
| 1279.9 | −0.0078% | 1.00035590 | FORCED |
| 1369.6 | +7% (limit up) | 1.07000000 | FORCED |
| 1190.4 | −7% (limit down) | 1.31888889 | FORCED |

### The legacy model has the same shape and the same degeneracy

`evaluate_margin` posts `R · M · P₀` and `sustains` calls when `equity / notional < m`:

```
R·P₀ + (P − P₀) < m·P   ⟺   P < P₀·(1 − R)/(1 − m)   ⟺   d > (R − m)/(1 − m)
```

A single drawdown threshold. And at the shipped defaults `maintenance_rate == vsd_initial`,
so `R − m` **is the broker buffer** and

```
legacy call distance  =  broker_buffer / (1 − vsd_initial)  =  0.05 / 0.83  =  6.024096%
```

Verified two ways: the trivial rule *"call if the close ever falls more than 6.024096% below
entry"* reproduces **29 / 48 / 56 exactly** at all three holding periods, and the previous
configuration gives `0.05/0.825 = 6.060606%`, which reproduces **28 / 48 / 56** — the exact
28 → 29 move the correction produced.

`maintenance_rate` has been equal to `vsd_initial` in every version of this file. Git
confirms it: the correction changed `vsd_initial: Decimal = Decimal('0.175')` **and**
`maintenance_rate: Decimal = Decimal('0.175')` to `0.17` in the same diff, and the original
introduction set both to `0.175`. So the "6.06% call distance" `margin.PROVENANCE` records
as *"an artefact of the invention"* is more precisely an artefact of the **broker buffer** —
the maintenance ratio never contributed a cushion of its own.

**So the legacy figure is not driven by the maintenance ratio at all. It is driven by the
broker buffer, which `FUNDING_PROVENANCE` and `margin.PROVENANCE` both already label an
ASSUMPTION.** Set the buffer to zero — post exactly what VSDC requires, maintain exactly
what VSDC requires — and the legacy threshold is zero too:

| posted initial rate | implied buffer | call distance | hold-10 calls | hold-10 rate |
|---|---|---|---|---|
| 0.170 | 0.000 | 0.0000% | 283 | **74.28%** |
| 0.175 | 0.005 | 0.6024% | 239 | 62.73% |
| 0.180 | 0.010 | 1.2048% | 192 | 50.39% |
| 0.200 | 0.030 | 3.6145% | 100 | 26.25% |
| **0.220** | **0.050** | **6.0241%** | **48** | **12.60% ← published** |
| 0.225 | 0.055 | 6.6265% | 43 | 11.29% |
| 0.250 | 0.080 | 9.6386% | 26 | 6.82% |
| 0.300 | 0.130 | 15.6627% | 1 | 0.26% |

**The two models have the same free parameter under two names.** The legacy cushion is
`initial_rate − maintenance_rate`; the account cushion is `funding_multiple − 1`. Both
degenerate at zero — the account model to 100%, the legacy model to "the price ever closed
below entry" (68.50% / 74.28% / 78.22%). Neither cushion is sourced.

---

## 4. Question 1 — is the 100% arithmetically forced?

**Yes, and more strongly than the hypothesis stated.** Confirmed both in closed form (§3) and
by instrumented walk of the shipped model over all 381 entries:

| `k = 1` | entries | warned | called | forced | forced on the **first** mark | min utilisation |
|---|---|---|---|---|---|---|
| hold 5 | 381 | 381 | 381 | 381 | **381** | 1.000 |
| hold 10 | 381 | 381 | 381 | 381 | **381** | 1.000 |
| hold 20 | 381 | 381 | 381 | 381 | **381** | 1.000 |

Every entry terminates on bar 1, so **the holding period is never an input** — which is why
5, 10 and 20 sessions all read 100%. Of the 381 first marks, **200 were up, 176 down, 5
exactly flat**; all 381 forced, including all 200 favourable ones and all 5 unchanged ones.

The state is not merely unrealistic; it is **not admissible in the model that produced it**.
Executed against `DerivativesAccount.reserve_for_order`:

| `k` | opening order | utilisation with the order merely resting | status |
|---|---|---|---|
| 0.9999 | **REJECTED** (`INSUFFICIENT_DEPOSIT`) | — | — |
| 1.0000 | admitted (the free-deposit test is a strict `>`) | 1.000000 | **FORCED** |
| 1.0001 | admitted | 0.999900 | CALL |
| 1.4200 | admitted | 0.704225 | OK |

`k = 1` is the *infimum* of the admissible funding set, and at it the account is in level-3
breach before any fill and before the market moves — so rulebook 6.3 §V.4 bars it from
opening anything further. The measurement reaches this state only because it calls
`apply_fill` directly, bypassing `reserve_for_order`.

**So: the experiment is malformed, and both published figures are suspect — for different
reasons.** The account figure is a constant misread as a measurement. The legacy figure is a
drawdown quantile at a threshold set by an assumed broker buffer, misread as a margin-call
rate.

---

## 5. Question 2 — is the legacy 7.61 / 12.60 / 14.70% series measuring anything real?

**It is measuring something real and it is not what it says it is.** Precisely:

> 7.61% / 12.60% / 14.70% is `P(max drawdown from entry over H sessions > 6.024096%)` on the
> front-month VN30F close series, and nothing else.

That is a genuine, correctly computed property of the price series — the walk is sound, the
entry population is sound, and I reproduced it to the entry with a four-line drawdown rule.
Three things about it are not sound as published:

1. **The label.** No Vietnamese rule performs an `equity/notional` versus `maintenance_rate`
   test, so calling the number a margin-call rate asserts a rule that does not exist.
2. **The threshold.** 6.024096% is `broker_buffer / (1 − vsd_initial)`. The buffer is an
   assumption; across its plausible range the same series reads anywhere from 74.28% to
   0.26% (§3). A headline that moves by 74 points on an unsourced input is not a finding
   about VN30F.
3. **The denominator.** 381 entries are overlapping windows on 401 daily observations of 20
   contracts. At the 6.024096% threshold the first breaches fall on **16 / 19 / 19 distinct
   days**, and the 10-session and 20-session day sets are **identical** — checked, symmetric
   difference zero. The step from 48 to 56 is not eight new events; it is the same nineteen
   days catching eight more overlapping windows. Any interval computed as if `n = 381` is
   badly overstated.

The `0.175 → 0.17` correction is a symptom, not the disease. It moved the threshold by 0.036
percentage points (6.0606% → 6.0241%) and flipped exactly one entry at the 5-session hold.
The series is that sensitive because it is an indicator function of a threshold that nothing
pins down.

One further defect that applies to **both** series equally, and is inherited from
`margin_incidence.py`: `_windows` **truncates** a window at the end of a front-month series
rather than dropping it, so the entry count is the same 381 at every holding period. The 20
front-month series run 11 to 25 sessions, mean 20.05, so a "20-session hold" is largely a
hold to expiry — and `margin_incidence.py`'s own docstring already refuses to publish a
buy-and-hold-to-expiry figure as an incidence, for exactly this reason. The three horizons
are not three horizons.

---

## 6. The disagreement does not exist

This is the finding that most changes what the paper can say, and it overturns two
statements this repository shipped.

### 6.1 A funding multiple *does* reproduce 29 / 48 / 56

The old sweep missed it for two mechanical reasons, neither of which is a difference between
the models.

- **The grid.** `funding_multiple_sweep` stepped in hundredths. The interval that reproduces
  the counts is `[1.4110, 1.4136]` — strictly between 1.41 and 1.42. The sweep could not
  land on it by construction.
- **The rate confound.** The account path re-resolves VSDC's dated ratio at **every marked
  bar** (correctly — `resolve_initial_margin_rate`), while the legacy path posts an undated
  22% to all 381 entries. Windows crossing the 2022-12-15 step from 13% to 17% are therefore
  priced on two different rate series.

Measured, over a 0.0001 grid, by two independent routes (a deposit-quantised walk of the
model, and the peak-requirement statistic of §7 — they agree exactly):

| initial-margin rate treatment | reproducing interval | counts at 5 / 10 / 20 | exact? |
|---|---|---|---|
| **frozen at each entry's date** | **k ∈ [1.4110, 1.4136]** | **29 / 48 / 56** | **yes** |
| the legacy path's own flat 22% | k ∈ [1.3466, 1.3485] | 29 / 48 / 56 | yes |
| re-resolved per bar (shipped) | best k = 1.411 | 29 / 48 / **64** | no, error 8 |

Verified at `k = 1.4120` through the real `DerivativesAccount`:
`freeze_initial_rate=True` → **29 / 48 / 56**; dated → 29 / 48 / 64.

### 6.2 The residual was a regulatory event, not a model difference

The shipped module said the miss was "because the two models' call boundaries move
differently in the size of the loss." **That is false.** Decomposed at `k = 1.4120`:

| hold | windows straddling 2022-12-15 | called, dated | called, frozen |
|---|---|---|---|
| 5 | 5 | 0 | 0 |
| 10 | 10 | 2 | 2 |
| 20 | **19** | **10** | **2** |

All eight extra 20-session calls live in the nineteen windows at the very end of the corpus
that straddle the ratio hike. Nothing about the size of a loss is involved.

Both models are **the same functional form** — first passage of the drawdown from entry
through a threshold:

```
legacy   :  d > (R − m)/(1 − m)                  = 6.0241%, flat, all 381 entries
account  :  d > r(θk − 1)/(1 − r)                = a function of the dated rate r
```

They differ only on the **gain** — the legacy model lets profit relieve the requirement, the
account model does not — and on this corpus that difference cannot bind at the reproducing
multiple: the largest drawup in any window is **19.47%**, while at `k = 1.4120` the rally
branch does not reach the call rung until a **27.08%** rise.

### 6.3 The reproduction is exact in count, not in event — and that is worth saying

Checked entry by entry rather than only in aggregate. At `k = 1.4120` with the rate frozen,
the account threshold is **5.944%** for the 371 entries priced at 13% + 5% and **7.638%** for
the 10 priced at 17% + 5%, against the legacy's flat 6.024%:

| hold | legacy called | account called | symmetric difference |
|---|---|---|---|
| 5 | 29 | 29 | **0** |
| 10 | 48 | 48 | **2** (one in, one out) |
| 20 | 56 | 56 | **2** (one in, one out) |

So the account model is marginally *looser* on 97% of entries and markedly *stricter* on the
3% after the ratio hike, and at this multiple the two errors cancel in count. Setting the
thresholds exactly equal instead — `k = 1.41603`, the root of
`r(0.9k − 1)/(1 − r) = 6.0241%` at `r = 0.18` — gives **29 / 47 / 55** and a symmetric
difference of 1, which is the same 3% of entries showing up as an undercount.

Do not overclaim this as "the same events". It is: the same functional form, the same
population, thresholds within 0.08 percentage points on 97% of entries, and identical counts
over a 0.0026-wide band of `k`.

**Conclusion: the published figures were never evidence against the sourced model.** The
honest statement is not "our account model contradicts the published figures" but "the
account model reproduces the published counts at an assumed funding level of about 1.41×
once VSDC's dated ratio is held constant across each hold, and the apparent residual was the
legacy path applying an undated 22% where VSDC's dated series gives 13% for 371 of 381
entries."

### 6.4 What that does *not* license

`k ≈ 1.41` is a fitted parameter. It is not evidence about Vietnamese retail funding. Two
independent things are worth recording beside it, both **REPORTED** and neither re-verified
by me:

- Every published Vietnamese broker worked example funds **above** the minimum, in a narrow
  band: VSD's own 2017 explainer 1.429×, Pinetree 2024 1.379×, SSI's deck 1.364×, DNSE
  guidance 1.23–1.47×. DNSE states the norm explicitly — brokers routinely require more than
  the minimum. These are *illustrative* accounts, not a survey of live balances.
- The band is not arbitrary: VN30F's daily band is ±7%, and at `r = 0.17` the multiple that
  survives a full limit-down day without forced closure is **1.342×**.

That the fitted 1.41 lands just above a cluster of illustrative values is worth one sentence
in a paper and no more. It is not a measurement of anything.

---

## 7. Question 3 — what funding level and what statistic

### 7.1 No single funding level is defensible

Neither corpus on this machine carries account or margin data, so `k` is unobservable here.
Any headline that depends on one value of it is a headline about an assumption. Three hard
constraints on the region, if a curve is reported:

- **`k > 1.25` strictly.** Below it even the warning rung is certain (`k ≤ 1/0.80`).
- **`k > 1.3274` on this corpus**, if the model's frozen-assets simplification is not to
  contaminate the answer: below that a *rally* can trigger a call in the model
  (`θk ≤ 1 + 19.47%`) that cannot happen in the market.
- Do not report `k ≤ 1.1111` at all except as a demonstration of the degeneracy.

### 7.2 The statistic: peak requirement multiple, `U*`

**Report the distribution, not the indicator.** Define, per entry,

```
U*  =  max over the hold of  MR_t / MR_at_entry
```

Properties that make it the right headline:

- **No funding parameter.** The deposit cancels. At `broker_buffer = 0` there is no unsourced
  parameter in it *at all*: numerator and denominator are both VSDC's own `MR = IM + VM`
  computed on VSDC's own dated ratio.
- **It is the quantity the call rate was thresholding.** An account funded at `k` has
  `utilisation = U / k`, so `call rate(k, θ) = P(U* ≥ θk)` exactly. The entire funding sweep
  is the survival function of one distribution. This is checked in the test suite: the
  derived rate equals the walked model's rate to the last unit at six multiples.
- **It explains the degeneracy rather than hiding it.** `U* ≥ 1` identically, so
  `P(U* ≥ 1) = 1` — the 100% figure *is* this distribution collapsed to a constant. The fix
  is not to change the model; it is to stop throwing the distribution away.

Measured at `broker_buffer = 0` (nearest-rank, no interpolation), 381 entries:

| hold | min | p25 | median | p75 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|---|
| 5 | 1.0003 | 1.0277 | **1.0666** | 1.1627 | 1.3369 | 1.4589 | 1.6323 | 1.7573 |
| 10 | 1.0003 | 1.0401 | **1.0939** | 1.2657 | 1.5159 | 1.7093 | 1.9357 | 2.1069 |
| 20 | 1.0003 | 1.0503 | **1.1342** | 1.3242 | 1.5449 | 1.8275 | 2.2654 | 2.3417 |

Loss branch only — marks strictly below entry, `1` for a window never in loss:

| hold | p25 | median | p75 | p90 | p95 | max | windows never in loss |
|---|---|---|---|---|---|---|---|
| 5 | 1.0000 | 1.0535 | 1.1541 | 1.3346 | 1.4589 | 1.7573 | 120 |
| 10 | 1.0000 | 1.0830 | 1.2482 | 1.5159 | 1.7093 | 2.1069 | 98 |
| 20 | 1.0137 | 1.1224 | 1.2913 | 1.5449 | 1.8275 | 2.3417 | 83 |

**Two series, not one, and the reason is a Tier 1 gap that must be disclosed.**
`peaks_on_a_rally` is **139 / 126 / 112** of 381 — roughly a third of the peaks are attained
on a *rising* price. In the model that raises utilisation because IM is recomputed on the
higher price while the profit is not credited to assets (`deposit.py`,
`account_margin_requirement`, note 3: the daily P&L moves as cash on T+1, which Tier 1 does
not model). **In the market it cannot**: on a rally a real account's assets grow by the whole
P&L while its requirement grows by only `r` times it, and `r < 1`, so real utilisation
*falls*. Any statement about **funding** must therefore lean on the loss branch. The
requirement series itself is faithful on both branches — VSDC's requirement really does rise
when the price rises — which is exactly why `U*` is reported on the requirement side and the
funding reading is derived separately and labelled.

### 7.3 The sentence a paper can defend

> Over 2021-06 to 2022-12, a front-month VN30F long faced a peak VSDC margin requirement of
> **1.09× its opening requirement at the median 10-session hold** and **1.71× at the 95th
> percentile**, computed as `MR = IM + VM` on VSDC's dated initial-margin ratio with no
> assumption about how the account was funded. An account holding assets at `X×` the opening
> requirement would have been called at its broker's 90% rung whenever the peak exceeded
> `0.90X`.

Two things must travel with it or the sentence is not defensible.

- **The denominator.** 381 overlapping windows on 401 daily observations of 20 contracts,
  peaks falling on **180 / 116 / 64 distinct days** at 5 / 10 / 20 sessions. Report event
  counts or cluster-robust intervals, never `n = 381`.
- **The buffer.** The 1.09 / 1.71 above are at `broker_buffer = 0`; the `k ≈ 1.41`
  reproduction of the legacy counts is at `broker_buffer = 0.05`, because that is the rate
  the legacy path posts. They are the same statistic at two rates, not one number quoted
  twice — `U*` moves with the buffer through `(1 − r)/r` on the loss branch. Say which rate
  any quoted figure used.

### 7.4 What not to report

- **Not a call rate at a single funding level.** Either figure. The account one is a constant
  at the level it was run; the legacy one is a drawdown quantile at an assumed threshold.
- **Not time-to-first-call as a headline.** It is identically 1 for every entry at any
  `k ≤ 1/θ`, and is defined only conditional on a call. Time-to-*peak* is well defined
  everywhere and needs no funding level — `PeakRequirementResult.peak_session`: median
  session **3 / 5 / 6** at holds 5 / 10 / 20, 90th percentile 5 / 10 / 15. Note the median at
  20 sessions is 6 — the requirement peaks early and the second fortnight adds little, which
  is a real finding about VN30F and one no call rate can express.
- **Not the 5 / 10 / 20 monotonicity as a result.** For fixed entry the 5-session window is a
  prefix of the 10 is a prefix of the 20, so `29 ≤ 48 ≤ 56` is forced by nesting.

---

## 8. Question 4 — can the legacy path be retired?

**Not yet, and the reason has changed.** The reason on file — "the account-level model does
not reproduce the published figures" — is refuted above. Three live dependencies remain, none
of them about the disagreement:

1. **`reproduce_measurements.py`** step 8 of 9 (`measure_exchange_margin`) calls
   `measure_margin_incidence`, which calls `HNXDSExchange.sustains` → `evaluate_margin`. The
   reproduction script is how a reader re-derives every published number; it cannot lose a
   step while a figure computed by that step is in circulation.
2. **`HNXDSExchange.sustains` is a protocol method whose margin state is load-bearing for
   its non-margin half.** It overrides `ExchangeBase.sustains`, is the sole producer of
   `POSITION_LIMIT_EXCEEDED`, `EXIT_BLOCKED` and `EXPIRY_SETTLEMENT`, counts indeterminate
   days — and passes the `MarginState` it computed into **every one** of those events'
   payloads (`derivatives.py`, four `self._event(...)` calls). Removing `evaluate_margin`
   therefore does not remove a margin test, it empties four event payloads pinned by
   `tests/market/test_derivatives_sustains.py`. Replacing it wholesale needs a batch path
   the account model does not have: it has nowhere to carry an outstanding call across days
   — that is what `MarginMonitor` is for — and it refuses a lone `Position` by design
   (locked shape 5).
3. **Reproducibility of a circulated number.** The figures were computed on this path.
   Silently re-pointing it restates them.

What *can* be retired immediately is the **claim**, not the code: `maintenance_rate` should
never again be described as a margin rule, and 7.61 / 12.60 / 14.70% should not be printed
as call rates. Once the paper stops printing a call rate, dependency 3 lapses and the path
becomes ordinary legacy code.

---

## 9. Recommendation

1. **Publish neither figure as a call rate.** A retracted number is cheaper than a defended
   wrong one. Both stay in the repository, both stay measured, both stay reported in
   `to_dict()` output — as what they are.
2. **Publish the `U*` distribution** from `measure_peak_requirement`, at
   `broker_buffer = 0`, with `peaks_on_a_rally`, `distinct_peak_days` and `peak_session`
   beside it. It has no unsourced parameter, it is VSDC's own formula, and every call rate
   anyone wants is a survival probability of it. The whole 381-value sample is in
   `to_dict()['sample']`, so a reader who wants a different threshold does not need the
   corpus.
3. **If a funding-conditional number is wanted, publish the curve over `k`, never a point.**
   Shade `k ≤ 1.25` as degenerate. Mark 1.3274 (below which the model's rally branch
   contaminates the answer on this corpus) and the 1.36–1.43 band of published broker worked
   examples. That turns "no multiple reproduces the figures" from a failure into a
   sensitivity result — and the correct statement is now that a multiple **does**.
4. **State the reproduction, in the paper, as agreement — and say what kind.** "The
   account-level model reproduces the published per-position **counts** at all three holding
   periods, at an assumed funding multiple of 1.411–1.414×, once VSDC's dated ratio is held
   constant across each hold; the apparent disagreement was the legacy path's undated 22%
   against a dated 13%. The called *sets* differ by two of 381 windows at 10 and 20 sessions,
   because the two thresholds straddle across the 2022-12-15 ratio step." That is a stronger
   and more honest result than a contradiction, and the caveat costs one clause.
5. **Fix the denominator wherever either figure appears.** 401 observations, 20 contracts,
   19 distinct breach days at 10 and 20 sessions. Overlapping-observations inference
   (Richardson & Stock 1989, `10.1016/0304-405x(89)90086-x` — REPORTED, metadata only).
6. **Downgrade the 80/90/100 rulebook row from `high` to `medium`** and label it "as
   reproduced by broker documentation from Article 13 of VSDC's derivatives clearing
   rulebook; article text not obtained", noting the conflicting MBS PDF. Attach URLs: no repo
   citation currently carries one, and the keystone source is unreachable on `vsdc.vn` today.
7. **Two cheap follow-ups nobody has done**: open VSDC's annual reports by hand (all exceed
   the 10 MB fetch limit; the only plausible home for a published breach count), and obtain
   Article 13 of QĐ 61/QĐ-VSD or QĐ 26/QĐ-HĐTV. Note also that **no broker or regulator
   publishes a margin-call incidence rate** — there is no external benchmark to validate any
   call rate against. The nearest datum found is a 2017 CafeF report that VNDIRECT recorded 5
   and SSI 6 utilisation breaches in October 2017 and both were reprimanded by VSD, which
   says only that breaches are rare enough to be national news.

---

## 10. What this repository still says that is wrong

I own `docs/reference/margin-model-adjudication.md`,
`measurements/margin_incidence_account.py` and `tests/market/test_margin_incidence_account.py`
and have corrected all three. The following are outside that scope and **still carry the
refuted claims**; each needs its owner:

| File | What it says | What is wrong |
|---|---|---|
| `src/plutus/market/margin.py` — `PROVENANCE['reproduction']` | "MEASURED VERDICT: DISAGREE … no funding multiple reproduces all three counts" | Both clauses refuted, §6. The verdict is agreement at `k ∈ [1.4110, 1.4136]` with the rate held at entry |
| `src/plutus/market/margin.py` — module and `MarginConfig` docstrings | "the account model calls 100% … the best fit, 1.42, still misses the 20-session count by 7" | The 100% is an identity (§4); the miss is the 2022-12-15 ratio step (§6.2), and 1.42 is a grid artefact |
| `src/plutus/market/exchanges/derivatives.py` — `sustains` docstring | "it does not [reproduce them], at any funding level, and the disagreement is structural" | Same refutation. The three real reasons to keep the method are in §8 |
| `docs/HANDOFF-2026-08-26.md` § "Results worth not re-deriving" | "The two margin paths disagree … no funding multiple reproduces all three counts jointly" | Same. Retirement is still pending, but for the reasons in §8, not this one |
| `docs/reference/vn-exchange-rulebook-2020-2026.md` line 587 | 80/90/100 at confidence `high` | Article text unread; two secondary reproductions against one conflicting one. §2 |

Until those are corrected, a reader who reaches them first will draw the superseded
conclusion.
