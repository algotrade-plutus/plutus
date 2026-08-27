# FEATURES — the implemented-feature inventory

**Read this before asking the author anything.** This document exists because a prior
session asked the author to supply the derivatives margin-call thresholds. They were
already implemented, so the question wasted the author's time and signalled that the code
had not been read.

> **The original of that paragraph also said the thresholds were "already sourced at high
> confidence (80 / 90 / 100, Article 13 of QĐ 96/QĐ-VSD → QĐ 61/QĐ-VSD → QĐ 12/QĐ-HĐTV →
> QĐ 26/QĐ-HĐTV)". That half is now withdrawn.** QĐ 26 was obtained and read in full on
> 2026-08-26; **Điều 13 has no percentages**. See §11 and §19. The lesson the anecdote
> teaches is unchanged and now cuts both ways: read the code *and* read the document. A
> citation chain is only as good as its last link, and nobody had followed this one to
> the end.

This file is the substitute for a memory the next session will not have.

- **Repo:** `/Users/nadan/algotrade-research/plutus` · branch `rivf26-wp1-wp2-wp4`
- **Suite:** `python -m pytest -q` → **2308 passed**, 0 failed, 2026-08-27 (2,198 before
  the execution-half repair; +110, of which 66 are new and the rest were corrected —
  several had been *pinning defects as expected behaviour*, and five were pinning
  behaviour the repair deliberately changed). **Note the word "passed", not "collected"**
  — the 47-test collected/passed gap recorded as **D36** was measured on the 1318-test
  tree and has not been re-measured since; do not quote D36's numbers against this one
- **Execution half repaired:** 2026-08-27 (later). The fidelity audit's verdict was
  *"an accounting engine attached to an execution model that is not a simulation of a
  market"*. Volume now reaches the fill policies, the participation cap is live, the
  ignorance meter can see its own blind spots, and **the overnight margin layer has a
  runtime path for the first time**. §19, last entry, has the measurements
- **Validated end to end:** 2026-08-27. Seven scenarios (`deriv-margin`, `equity-margin`,
  `order-cycle`, `settlement`, `expiry-overnight`, `pair-trade`, `corporate-charges`) were
  run against real corpus data and then adversarially audited. **11 defects fixed**
  (D60–D70), **10 conflicts recorded rather than guessed** (§16.4), **1 auditor claim
  refuted with measurement** (§16.4 item 8). Read §16.4 before trusting any derivatives
  settlement or margin-timing number
- **Last surveyed:** 2026-08-26, by five readers of the actual code (not of docstrings)
- **Adversarially audited:** 2026-08-26 by four independent auditors; corrections applied
  and every count re-derived. **Read the [verification log](#19-verification-log) at the
  foot of this file before trusting any single row.**
- **Primary sources obtained 2026-08-26:** QĐ 26/QĐ-HĐTV (2025-04-16) and its **Phụ lục
  2**. These were the two highest-value missing documents in the derivatives domain and
  they invalidate several rows this file previously graded HIGH. Every affected row is
  marked below and the whole correction is logged in §19.

---

## 0. Index

| § | Domain | Jump |
|---|---|---|
| 1 | **Already answered — do not ask these again** | [§1](#1-already-answered--do-not-ask-these-again) |
| 2 | Status vocabulary | [§2](#2-status-vocabulary) |
| 3 | **THE ASSUMED-VALUE REGISTER** — consult before asking the author for a number | [§3](#3-the-assumed-value-register) |
| 4 | Rule resolution — the dated rulebook | [§4](#4-rule-resolution--the-dated-rulebook) |
| 5 | Order admission | [§5](#5-order-admission) |
| 6 | Order lifecycle | [§6](#6-order-lifecycle) |
| 7 | Fills | [§7](#7-fills) |
| 8 | Settlement and cash | [§8](#8-settlement-and-cash) |
| 9 | Charges and taxes | [§9](#9-charges-and-taxes) |
| 10 | Corporate actions | [§10](#10-corporate-actions) |
| 11 | Derivatives and margin | [§11](#11-derivatives-and-margin) |
| 12 | **Equity margin lending — NOT BUILT, priority 1** | [§12](#12-equity-margin-lending--not-built-priority-1) |
| 13 | Session API | [§13](#13-session-api) |
| 14 | Data contract and adapters | [§14](#14-data-contract-and-adapters) |
| 15 | Calendars | [§15](#15-calendars) |
| 16 | **DEFERRED / FUTURE WORK** — author decisions 1–5 | [§16](#16-deferred--future-work) |
| 16.4 | **CONFLICTS RECORDED RATHER THAN RESOLVED** — the 2026-08-27 validation pass | [§16.4](#164-conflicts-recorded-rather-than-resolved--validation-pass-2026-08-27) |
| 17 | Known defects and docstring mismatches (**D60–D70 = the validation pass**) | [§17](#17-known-defects-and-docstring-mismatches) |
| 18 | How to keep this document true | [§18](#18-how-to-keep-this-document-true) |
| 19 | **Verification log** — what was audited, what was found | [§19](#19-verification-log) |

Companion documents, unchanged by this file:

- `docs/superpowers/specs/2026-08-25-exchange-simulator-design.md` — the design
- `docs/superpowers/specs/2026-08-25-tier1-interface-contract.md` — module contracts
- `docs/reference/vn-exchange-rulebook-2020-2026.md` — 400 dated rules (**grep it, do not read it whole**)
- `docs/reference/margin-model-adjudication.md` — why margin incidence was retracted
- `docs/reference/equity-margin-spec.md` — the spec for §12, written but not built
- `docs/reference/post-krx-margin-spec.md` — **new, 2026-08-26.** The post-KRX MR
  assembly read out of QĐ 26 Phụ lục 2, with an inference register and a source-defect
  register. **Specification only; nothing in it is built** (§11)

---

## 1. Already answered — do not ask these again

Each of these is in the code today with a dated citation. The file:line is where to look.

| Question a session might wrongly ask | The answer already in the code | Where |
|---|---|---|
| "What are the derivatives margin-call thresholds?" | **80 / 90 / 100 %** of utilisation is what we compute, unchanged. **The sourcing is withdrawn as of 2026-08-26** — applying a ladder to *margin* is now **UNSOURCED**, post-KRX definitively (QĐ 26 Điều 13 read in full, binary `assets < MR`, no percentage) and pre-KRX **UNVERIFIED not disproven** (QĐ 61 and QĐ 12 never read). 80/90/100 *is* primary-sourced — to **QĐ 26 Điều 29, for POSITION LIMITS**. Defaults deliberately unchanged | `broker.py:PROVENANCE`, `deposit.py:margin_status` |
| "Then does anything in the primary text back the 1.00 forced level?" | **Yes, the top rung only.** `MR / assets ≥ 1.00` ≡ `assets ≤ MR`, and `assets < MR` is the entire QĐ 26 Điều 13 test. The two coincide except at `assets == MR`, which Điều 13.2.c treats as cured and we treat as breach — one tick, conservative, pinned by test | `deposit.py:margin_status`; `test_deposit.py::test_the_forced_rung_is_qd26_dieu_13s_binary_test_off_by_equality` |
| "What is the initial margin ratio?" | **0.10 @ 2017-08-10, 0.13 @ 2018-07-18, 0.17 @ 2022-12-15**, still 0.17 at 2026-08-21. Press-sourced; **no quyết định number exists** | `margin.py:129`, `rulebook.py:1355` |
| "What is the VN30F contract multiplier?" | **100,000 VND/point** from 2017-08-10; VN100F same from 2025-10-10; **GB05/GB10 10,000** | `deposit.py:495-530` |
| "What are the position limits?" | INDEX 5,000 / 10,000 / 20,000 (**LOW** confidence values); GB 0 / 5,000 / 10,000 (HIGH). QĐ 26 Điều 27.1 confirms the *mechanism* — VSDC sets them per account type and per futures type and publishes ≥ 02 working days ahead — and **prints no number**, which is why the values stay LOW | `rulebook.py:1431` |
| "Is there a warning ladder on the position limits?" | **In the rulebook yes, in the code no.** QĐ 26 Điều 29 sets warning levels 1/2/3 at **80 / 90 / 100 % of the position limit**; level 3 suspends the account and allows only offsetting trades. **NOT BUILT** — see §11 for the three reasons, the first of which is that we do not compute the quantity the percentages apply to | §11, §16.3 |
| "What is the settlement cycle?" | **T+2 since 2016-01-01** — not 2022. What changed on 2022-08-29 is the *time of day* (13:00). Never call it "T+1.5" | `rulebook.py:1266` |
| "What is the trading unit?" | HOSE **10 → 100 @ 2021-01-04** (QĐ 894); resolved per instant | `core/constant.py:315`, `rulebook.py:633` |
| "What are the exchange fees?" | **10 charge ids over 17 dated intervals**: HSX equity 0.0003 → **0.00027 @ 2020-03-19**, PIT sell-side 0.001, derivatives PIT `0.0005 × IM`, VSDC clearing 2,550/contract. (Count: `len(_charge_table())` = 10, `sum(len(v) …)` = 17 — §9 lists all ten) | `rulebook.py:1549-1795` |
| "What is the daily price band?" | HSX .07 / HNX .10 / UPCoM .15 / HNXDS index .07 / GB .03, all dated. **Confidence differs by venue** — HIGH only from 2021-07-05 (HSX), 2022-03-31 (HNX), 2022-11-16 (UPCoM); **LOW before each**, text never retrieved. See §4 | `rulebook.py:672` |
| "Can a covered warrant be traded?" | **No — not at any date.** A CW has no percentage band; the row is `_unsourced` **as sourced data**, `daily_trading_limit(HSX, WARRANT)` raises `UnresolvedRule`, and `exchange.py` turns that into `Rejected(INDETERMINATE)`. The formula that *would* apply is recorded. See §5 and §16.3 | `rulebook.py:763-777`, `:2717-2727` |
| "What is the cure window?" | **Next session** is our default and an *assumed broker term* — unchanged. The regulated deadlines are now **primary-sourced and definite**, and all are **clearing-member-to-VSDC**, not investor cure windows: top-up **before 09h30 on T+1** (QĐ 26 Điều 13.1) and **03 working days** before VSDC directs *another clearing member* to close you out (Điều 13.3.b; identically Điều 29.5 for a position-limit breach). **The "5 business days" figure is refuted for post-KRX** — it came from a LuatVietnam summary of the superseded edition. See §16 decision 5 | `broker.py:CureWindow`, `deposit.py:MarginMonitor` |
| "Does Vietnam publish a maintenance margin ratio **for derivatives**?" | **No — at no date, 2020–2026, and this is now primary-sourced rather than reported.** QĐ 26 Điều 13 is a comparison of two absolute values, `assets` vs `MR`; no fraction of notional appears in it. `margin.py`'s `maintenance_rate` models a quantity that does not exist. **The qualifier is load-bearing:** for *equity margin lending* a maintenance ratio floor of **30 %** is published and read verbatim (QĐ 87 Điều 5.2) — see §12. Two different products, two different answers | `margin.py:71-110`; §12 |
| "Is `MR = IM + VM` still right?" | **Only to 2025-05-04.** QĐ 26 Điều 20 settles position P&L as a separate daily cash movement and Phụ lục 2 §6 assembles MR with **no VM term at all**: `MR = Max(Σ Pgm, 0)`, `Pgm = Max((Rm + Sm + Dm), MM)`. The code implements the pre-KRX shape at every date and says so. **The post-KRX model is specified and NOT BUILT** | `deposit.py` module docstring; `post-krx-margin-spec.md`; §11 |
| "How is VM computed?" | **Loss-only**, netted account-wide, VSDC verbatim. Gains never relieve the requirement | `deposit.py:729-734` |
| "What is the max order size?" | HOSE **500,000 from 2021-01-04**; HNXDS 500 contracts; **HNX and UPCoM publish none at any date** | `rulebook.py:1489` |
| "What price does a match trade at?" | The **resting (passive) order's price**, not the aggressor's — QĐ 352 Điều 6.3, HIGH | `fills.py:48-73` |
| "When may an order be amended?" | Price *and* quantity together allowed to 2025-05-04, **forbidden from 2025-05-05** (VNX QĐ 22/2025 Điều 21.3) | `exchange.py:1306` |

**If a value you need is not in this table, check §3 (assumed) and §4–§15 before asking.**

---

## 2. Status vocabulary

Fixed, five values. Collapsing the first two is what caused the bad questions.

| Status | Means |
|---|---|
| **IMPLEMENTED + SOURCED** | Built, and the value carries a dated citation with a confidence grade. Do not ask the author for it. |
| **IMPLEMENTED + ASSUMED** | Built, but the value is **our assumption**. Every one is listed in §3. Ask the author only if the run's result is sensitive to it. |
| **PARTIAL** | Built with a stated limitation. The limitation is in the note. |
| **DEFERRED** | Deliberately not built. The reason and the decision are recorded in §16. |
| **NOT BUILT** | Absent, and no decision is recorded. These are the real gaps. |

Two conventions inside the tables:

- `[design]` in the source column means the source is our own design spec, not a
  Vietnamese document — an internal shape decision, not market law. It is still
  *sourced* in the sense that it is written down and dated; it is **not** gazetted.
- Confidence grades (HIGH / MEDIUM / LOW / UNVERIFIED) are the rulebook's own and are
  reproduced verbatim. A HIGH-confidence row can still be wrong; it means the primary
  text was read.

---

## 3. THE ASSUMED-VALUE REGISTER

**This is the list to consult before asking the author for any number.** Every entry is
already labelled as an assumption in its own docstring or `PROVENANCE` dict — house rule
1. Nothing here needs the author's permission to keep using; it needs the author only if
a published result turns on it.

### 3A. Broker commercial terms — `market/broker.py`, `BrokerTerms.PROVENANCE`

> **A1–A3 were re-graded on 2026-08-26.** They previously read "Ladder **shape** is
> VSDC-sourced; the **levels** are per-firm and unpublished … the defaults are numerically
> VSDC's own, so a default run reproduces the depository ladder". **The whole of that is
> withdrawn except the last clause about the levels.** QĐ 26 Điều 13 was read in full and
> publishes no ladder for margin; a default run therefore reproduces *our* ladder, not
> VSDC's. The values did not change — only the claim. Pinned by
> `test_deposit.py::test_the_margin_utilisation_ladder_is_declared_unsourced`.

| # | Value | Default | Why assumed |
|---|---|---|---|
| A1 | `warning_utilisation` | `0.80` | **UNSOURCED, and with no counterpart of any kind in the read text** — QĐ 26 Điều 13 has one state, not three. A real broker example is Pinetree 75/85/90, which is evidence that brokers *do* run ladders, not evidence of these levels |
| A2 | `margin_call_utilisation` | `0.90` | **UNSOURCED.** Applying a utilisation ladder to margin is our shape. 80/90/100 is primary-sourced at **QĐ 26 Điều 29 for POSITION LIMITS** — a different rule on a different quantity (contracts held vs the published cap), NOT BUILT (§11). Pre-KRX the margin thresholds are **UNVERIFIED, not disproven**: QĐ 61 and QĐ 12 have never been read |
| A3 | `forced_close_utilisation` | `1.00` | **UNSOURCED as a rung**, but the *only* one with a regulated counterpart: at 1.00 the test `MR / assets ≥ 1` is `assets ≤ MR`, and `assets < MR` is the whole of QĐ 26 Điều 13. Discrepancy is the single boundary `assets == MR` — cured under Điều 13.2.c, breach here. This is why changing the default is a decision, not a cleanup |
| A4 | `advance_on_sale_daily_rate` | `0.00031` | Inside the 0.025–0.05 %/day band brokers quote for the **advance**. Two things to know: (i) 0.031 %/day matches **no observed firm** in the rulebook's own 2021 snapshot (§8.3:840 — 0.025 / 0.029 / 0.0329 / 0.033 ×3 / 0.0389 / 0.04 / 0.05) **and is not the rulebook's recommended default of 0.00035/day** (§12.7:1194); (ii) the "margin lending" mis-attribution flagged as D3 is **fixed** — `PROVENANCE` now says *the sale advance itself* |
| A5 | `cure_window_sessions` | `1` (NEXT_SESSION) | Author decision 5, unchanged. **Assumed for the broker→investor window only; the member→VSDC deadlines are now regulated and sourced** (QĐ 26 Điều 13.1 top-up before 09h30 T+1; Điều 13.3.b 03 working days to substitute-member close-out). Corroboration, not a source: HNXDS opens 08:45, so the default deadline sits 45 minutes *inside* the regulated 09h30 — the direction a broker term may move in |
| A6 | `BrokerProfile.margin_buffer` | `0` | A percentage-of-notional add-on is a plausible **shape** only; the rulebook records that the broker's real lever is its utilisation thresholds |

### 3B. Sale advance — `session/ledgers.py`, `AdvanceTerms.PROVENANCE:690`

| # | Value | Default | Why assumed |
|---|---|---|---|
| A7 | `max_advanceable_fraction` | `1` (100 %) | "Up to 100 % of net proceeds" is a description, not a figure. No statutory cap located |
| A8 | `annualisation_basis` | `365` | **DECLARED.** Sources mix ×360 and ×365; ~1.4 % systematic gap. **Never read during accrual** — which is `amount × rate × days` over actual calendar days and never touches a year length. **It is not inert, though:** it is the basis for the constructor `AdvanceTerms.from_annual_rate` (`ledgers.py:744-763`) and for the reporter `annual_rate` (`:767-776`), which exist as a round trip precisely so a printed headline rate cannot silently be on a different basis from the terms it was built from. DSC's ×365 against the industry's ×360 *is* the 1.4 % gap |
| A9 | `minimum_charge` | `None` | Unsourced in **value and unit** — VN fee tables often quote thousand-đồng, so 30,000 may be 1000× out. Left off rather than guessed |
| A10 | `auto_register` | `True` | Market practice, rulebook 8.3, LOW |
| A11 | Interest day-count | calendar days | Source gives `amount × days × rate` with no day-count basis |
| A12 | Accrual horizon | stops at the tranche's settlement instant | Declared |
| A13 | Allocation across tranches | settlement order, cheapest-interest-first | Declared choice, no source |

### 3C. Charges and commission — `session/charges.py`

| # | Value | Where | Why assumed |
|---|---|---|---|
| A14 | Rounding to whole đồng, **ROUND_HALF_UP** | `charges.py:169` | **UNVERIFIED for every charge.** No VN source states a rounding rule for any fee or tax |
| A15 | Advance headroom floors **ROUND_DOWN** | `ledgers.py:145` | Deliberately the opposite direction from A14 so a cap is never exceeded by its own rounding |
| A16 | Commission tier rates | `CommissionSchedule.PROVENANCE:600` | 0.10–0.35 % typical, 0 % at entrants. Tier **shape** is sourced; values are not |
| A17 | `minimum_per_order` | same | Unsourced in value **and** unit |
| A18 | Day's tier picked once, applied to the whole day | same | Modelling choice — the tier variable is not knowable at fill time |
| A19 | Minimum clamped **per order**, fills merged at VWAP | `charges.py:1266` | Modelling choice |
| A20 | Anonymous contexts each form their own group | `charges.py:1242` | Modelling choice |
| A21 | Charges stamped at the day's last trade absent a calendar | `charges.py:1184` | Modelling choice |
| A22 | Derivatives commission caps → **5,000/8,000 VND** (2022-01-01 →) | `charges.py:733-760` | MEDIUM — TT 102/2021 could not be opened from any mirror, and SSI charges 5,000 on **bond** futures, exactly the claimed *index* cap, so the two may be transposed. **Scope correction:** the earlier **15,000/25,000** pair (2019-02-15 → 2021-12-31) is **NOT assumed** — it is TT 128/2018 Biểu giá Phần B at `high` (rulebook §8.3:832). Only the 2022 pair is downgraded (:833). `charges.py:743-746` makes the same over-broad statement and should be narrowed too |
| A23 | Minimum-commission shortfall collected out of T+2 settlement | `ledgers.py:1891` | Rulebook records only that "some firms impose a minimum per order"; *when* it is collected is ours |
| A24 | Every securities-pool charge on a **sale** is withheld at source | `ledgers.py:1973` | Sourced only for the 0.1 % PIT; extended to commission and exchange fee by assumption |
| A25 | HSX/HNX/UPCoM service price unchanged 2025-01-10 → 2025-04-28 | `rulebook.py:1623` | No gazetted source for that gap; flagged in the row |

### 3D. Corporate actions — `session/corporate.py`, `PROVENANCE:263`

| # | Value | Why assumed |
|---|---|---|
| A26 | The adjustment algebra `P' = (P + ΣPa·a − C)/(1+Σa+Σb)` | **MARKET PRACTICE, NOT GAZETTED** — rulebook 3.6, MEDIUM. The *principle* (market cap conserved, adjust by the value of the distribution) is gazetted; the arithmetic is not. This is the one place in the domain where the traceability claim cannot be met |
| A27 | Rounding direction of the adjusted reference = ROUND_HALF_UP | Rounding **to the tick** is gazetted; the **direction** is stated nowhere. Half-up chosen because it is the only direction with corpus evidence |
| A28 | `RestingOrderPolicy` default `CANCEL` | **A CHOICE, NOT A RULE.** No VN document addresses what happens to a resting order across an ex-date; the day-order rule implies cancel |
| A29 | Fractional residue reported, never priced | Unsourced how a residue is bought out, or at what price |
| A30 | Per-parcel flooring of the quantity factor | Modelling choice; VSDC allocates on the registered total |
| A31 | Partial rights take-up not modelled | Nothing sourced says how a partly funded subscription is allotted |
| A32 | 5 % dividend withholding **NOT applied** — cash leg credited **gross** | **Premise corrected.** The rulebook *does* carry the row: §12.3:1112 `Cash dividend tax \| gross cash dividend \| 0.05 \| 2009-01-01 → 2026-06-30 \| low (uncited)`, and §8.1:768–769 says the 5 % must be netted before crediting. The **true** statement is that `rulebook.py::_charge_table` has no dividend row (verified: 10 ids, none dividend), so the engine has nothing to levy. The decision may still be right; the reason was wrong. `corporate.py`'s `PROVENANCE['dividend_withholding_tax']` repeats the false premise and needs the same fix (D27). `cash_leg_is_gross` is a field so a report cannot omit it |
| A33 | Dividend credited at the **ex-date**, not the real payment date | Declared simplification; the credit deliberately may not fund the same event's subscription |

### 3E. Fill policies — `session/fills.py`

| # | Value | Default | Why assumed |
|---|---|---|---|
| A34 | `HardFillPolicy.max_participation` | `0.10` | **Explicitly a modelling convention.** No Vietnamese document caps a participant's share of a print. Carried in the policy signature so it travels with any report |
| A35 | `ProbabilisticFillPolicy.p_touch` | `0.5` | **A stated convention with no empirical content** — the midpoint of the bracket `hard` and `soft` already draw. No document could supply it: the rulebook settles the *rule*; the missing thing is the *data* |
| A36 | `p_auction_margin` | `None` = do not model | Opt-in only, because allocation at the marginal price is **UNVERIFIED** in rulebook 2.4 |
| A37 | `NO_MARKET_IMPACT` | always | Standing limitation, design §16.1, returned from every policy's `assumptions` |
| A38 | An interval does not straddle a lot change | `fills.py:508` | Declared, explicitly not verified |
| A69 | On a daily run the fill interval is `[ts, ts + 1 day)` — the **whole trading day** | `exchange.py:1545-1550` | **Declared look-ahead.** An order entered at 14:00 is evaluated against the whole day. "An over-generosity that is a declared consequence of the resolution and not something a fill policy may silently correct." Present in **every** daily-resolution fill |
| A72 | An unset `fill_policy.max_participation` means **uncapped** for `soft`, `HardFillPolicy`'s own default for `hard`, and a **refusal** for `probabilistic` | `fills.py::build_fill_policy` | **Resolved 2026-08-27; this row used to record an ambiguity that no longer exists.** `FillPolicyConfig.max_participation` was a non-optional `Decimal` defaulting to `0.10`, so no reader could tell *"the caller wrote 0.10"* from *"the caller wrote nothing"* — the value 0.10 literally meant *uncapped*, and every `fill_policy='soft'` scenario in `validation/`, which wrote that value through `runner.build_session`, ran with no size bound while its own config said 10%. The field is `Optional[Decimal] = None`; `None` is the only unset and every written value including 0.10 is honoured. What `None` *means* is each kind's own answer: `soft` uncapped (its documented optimistic arm — capping it by default was measured and turns every source serving no volume into a run where nothing fills at all), `hard` its constructor default with the signature naming the number it ran at, `probabilistic` a `ValueError` because it has no default cap and reading an absent one as uncapped would *loosen* the run |
| A73 | The overnight layer's `R` (Phụ lục 2 §5.2 half relative spread) is **inverted out of the profile's published `MF`** | `overnight.py::_implied_minimum_margin_rate` | No firm publishes `R`; what they publish is `MF` (5,000đ per VN30 contract — S-11's `MF = tick × M / 2`, corroborated verbatim by TCBS). `R = MF / (M × St)` returns exactly `MF` through `minimum_margin_factor`. What is ours is S-11's first-order step, so this `MF` is a **lower bound** on a real book's — `MM` binds slightly less often than the truth, and only on a nearly flat book. Declared on every result as `minimum_margin_factor_derived` |
| A74 | The overnight layer forms **no underlying-asset groups**, so `OA = 0` unless one is supplied | `overnight.py::OvernightAssumption.NO_PUBLISHED_GROUPING` | Group membership is VSDC's, published and discretionary (Kendall-tau ≥ 0.9 over ≥ 3 years) and no broker in the survey mirrors it. Withholding the offset is the **restrictive** direction: measured 78,200,000đ ungrouped against 14,668,983đ with the offset applied on the same two-index book. Declared only on a book holding two or more underlyings, because on one product the relief is zero **by the rule** (Điều 5.1.1.a) |

### 3F. Session and admission — `session/exchange.py`, `session/orders.py`

| # | Behaviour | Why assumed |
|---|---|---|
| A39 | An **UNKNOWN max-order-size cap refuses nothing** | Declared one-directional scope cut. HNX/UPCoM at every date and HOSE before 2021-01-04 are UNKNOWN, so a 600,000-share 2020 HOSE order is admitted |
| A40 | Daily-bar session phase = `CONTINUOUS` | **Scoped to `Resolution.DAILY` only.** Declared deviation from the interface contract; both shipped adapters hardcode it, and on a daily run `_phase` (`exchange.py:1279-1300`) prefers that adapter value. **On any other resolution the rulebook wins outright** and the adapter is only the `UNKNOWN` fallback — so ATO/ATC/PLO *are* reachable on a tick run. Also: on a daily run a non-trading day resolves `POST_CLOSE`, which `equity.py:183-185` refuses with `SESSION_SEMANTICS` |
| A41 | `PRE_OPEN` / `POST_CLOSE` phases | **ADOPTED, not sourced** — no document names them |
| A42 | Amend/cancel locked in PRE_OPEN, POST_CLOSE and UNKNOWN | **ADOPTED, self-declared unsourced** — "the question is a broker-channel one" |
| A43 | `amend()` refuses a non-resting TIF | **ADOPTED** — every amendment row in the rulebook names the LO; the rulebook is silent on amending an ATO/MOK/MAK |
| A44 | `amend()` refuses `new_quantity < filled_quantity` | **ADOPTED** — no Vietnamese document addresses it |
| A45 | `ExpiryTrigger.INSTRUMENT_EXPIRY` | **ADOPTED, not sourced** |
| A46 | Unknown phase at a boundary expires nothing | Adopted reasoning, and a **declared asymmetry**: at admission absent data keeps the order out, here it keeps the order alive |
| A47 | Order-state set and transition graph | `[design]` §12 — a design shape, not a gazetted rule |
| A48 | Encumbrance key `(order_id, ResourceKind)`; pro-rata partial release of the **original reservation** | `[design]` §7.0 — no Vietnamese rule governs reservation arithmetic |
| A49 | Market-family buys funded at the **ceiling** | `[design]` §7.0 |
| A50 | `<=` on settlement instants ⇒ midnight-stamped daily bars behave as **T+3** under the 13:00 regime | Declared, intended, conservative |
| A51 | MTL residual price: the **equity** rule applied to HNXDS too | Recorded CONFLICT (rulebook OQ #18): last matched ±1 tick vs best bid/ask ±1 tick. Applied and declared, not resolved |
| A52 | `charge_class_for`: `FUND → ETF` | Declared simplification; rulebook 12.2 gives closed-end funds their own row |

### 3G. Derivatives and margin — `session/deposit.py`, `market/margin.py`

| # | Behaviour | Why assumed |
|---|---|---|
| A53 | `MarginView.equity = balance − required` | **Adopted definition, not sourced** |
| A54 | `LiquidationRule.LARGEST_LOSS_FIRST` | **Adopted.** No Vietnamese document prescribes a selection order. Pinetree prioritises the nearest expiry |
| A55 | Transfers to the deposit arrive **immediately** | **Adopted assumption**, design §16.2 |
| A56 | Final settlement = expiry-day **close** when no published price, **skipping the `TWAP_30M` tier** | Declared simplification (tradeoff T2), cost measured: +0.024 % mean signed, 0.042 % mean absolute, 0.333 % worst across 46 expiries. Never silent — the event carries `substituted=True`. **The chain has three tiers, not two**: the skipped middle one is `expiry.SettlementResolver._twap_30m` (14:15–14:45, mean error 0.74 index points), which needs the raw tick archive the session does not have. See §11 |
| A57 | **Cash-only margin assets** | Author decision 2 — MVP scope. Securities collateral, VSDC haircuts and the ≥80 % cash floor are not modelled |
| A58 | `InvestorClass.INDIVIDUAL` for every session | Hardwired; `AccountsConfig` carries no investor field |
| A59 | Marks are current **per session day**, not per instant | A 09:30 price is still current at 14:45 |
| A60 | VM measured from `average_entry` for the life of a position | Consequence of `settle_daily` having no session call site — see D1. Effectively **VM = cumulative since-entry unrealised loss**, not the day's adverse move |
| A61 | `margin.MarginConfig.maintenance_rate = 0.17` | **MODELS A QUANTITY THAT DOES NOT EXIST.** Legacy batch path only; retained because published figures were computed on it |
| A62 | `margin.MarginConfig.broker_buffer = 0.05` | Assumed, legacy path only |
| A63 | `margin.MarginConfig.default_multiplier = 100000` | The account-wide fallback that `deposit.py` exists to have removed. Legacy path only. **The *value* is sourced** (rulebook 4.1, HIGH); what is assumed is the account-wide fallback *shape*. **House-rule breach:** unlike every other entry here it is **not** in `margin.py`'s `PROVENANCE` and `margin.py:202` carries only `# VND per index point` — logged as D26 |
| A70 | Derivatives position limit tested against the **worst-case net** `max(\|net + all buys\|, \|net − all sells\|)` (`deposit.py:1229-1235`) | **A declared conservative modelling convention**, not a rule: "a resting sell that never fills must not create room for a buy that then breaches the cap" |
| A71 | Derivatives order margin = the **increment**, not the gross (`deposit.py:1243-1253`) | Offsetting-attracts-no-IM is sourced (rulebook 6.3); charging only the increment is the implementation of it, and its declared consequence is that **incremental margining is order-dependent — of two orders that together breach nothing, the first to arrive pays**. A closing order reserves zero and gets a zero-amount encumbrance |

### 3H. Calendars and data

| # | Behaviour | Why assumed |
|---|---|---|
| A64 | Default settlement calendar `weekday-only-UNSOURCED` | **No calendar data ships.** Every default run's settlement dates are wrong around Tết. Visible only via `provenance().settlement_calendar_id` |
| A65 | Default trading calendar `weekday_trading_calendar()` | Same shape, same problem |
| A66 | `VnTradingCalendar` clock times fall back to the **undated** `core/constant.py` specs **only when the caller passes no `RuleSet`** | **Corrected — the earlier wording was wrong.** `calendar.py:720-731` / `:733-743` **prefer** `rules.session_open(venue)` / `rules.session_close(venue)`, and both instants the session actually stamps pass a real `RuleSet`: DAY-order expiry (`exchange.py:1792`) and a margin call's `cure_by` (`exchange.py:2366` → `MarginMonitor.on_mark` → `deposit.py:1767`). `rulebook.py:2102-2130` says outright that `session_open` "exists because `calendar.py` was looking for it". So the undated map is a **fallback for a rules-less caller**, not the live path |
| A67 | Band reconstruction from the **undated, flat** `VietnamMarketConstant.DAILY_TRADING_LIMIT` | `adapters/datahub.py:190`. Tick keyed on the resulting band price; truncate for the ceiling, round-up for the floor. The rulebook's dated bands feed only `InstrumentSpec`, which no admission rule reads |
| A68 | `foreign_room` is never populated by either adapter | **Claim narrowed.** Only `datahub.py:212` sets `foreign_room=None` explicitly; `grep -n foreign_room src/plutus/market/adapters/tick.py` returns **nothing** — `TickSource` simply never sets the field and inherits `MarketState`'s default `None` (`protocol.py:132`). Same effect, different mechanism. Consequence: every `is_foreign=True` **BUY** is INDETERMINATE (`equity.py:140-144`), unavoidable on today's corpora |

**Register total: 74 assumed values (A1–A74).** *(A72–A74 added 2026-08-27 with the execution-half repair: the `soft` cap ambiguity, and the overnight layer's two.)* Every one says so in its own docstring or
`PROVENANCE` dict, with one logged exception: **A63**, which is missing from
`margin.py`'s `PROVENANCE` (D26).

**One `PROVENANCE` key deliberately has no row here.**
`corporate.PROVENANCE['combined_events_not_composable']` (`corporate.py:310`) self-describes
as "A CONSEQUENCE OF THE ALGEBRA, not a choice", so it is not an assumed *value*. The same
treatment is given to `charges.PROVENANCE`'s `tier_variable` / `debited_at` and
`margin.PROVENANCE`'s `vsd_initial` / `shape` / `kept_because` / `replacement` /
`reproduction`. **Keys that disclaim being assumptions are excluded from §3 on purpose** —
stated here so §18 rule 1 ("the two must agree") is not read as broken. Cross-check
performed: 5 dicts, 30 keys, all accounted for.

---

## 4. Rule resolution — the dated rulebook

`src/plutus/market/session/rulebook.py` (2,786 lines). 12 `RuleName` members. Resolution
is total three-state — `KNOWN` / `NOT_APPLICABLE` / `UNKNOWN` — never a guess.

| Feature | Where | Status | Source / note |
|---|---|---|---|
| Per-instant resolution `Rulebook.at(ts) → RuleSet` | `rulebook.py:2414` | IMPLEMENTED + SOURCED | `[design]` §11 — the first locked shape. Forbidden: config-at-load singletons |
| Three-state `RuleResolution`, typed accessors raise `UnresolvedRule` | `:176-232` | IMPLEMENTED + SOURCED | `[design]` — `resolve()` never raises; typed accessors do |
| `_unsourced()` — asserts an absence **as data** | `:319` | IMPLEMENTED + SOURCED | `[design]`. **11** such rows exist — `rulebook.py:747, 764, 836, 976, 982, 1254, 1394, 1414, 1501, 1513, 1519`. (Count: `grep -n "_unsourced(" rulebook.py` gives 13 matches; subtract the `def` at `:319` and the docstring mention at `:478`) |
| Half-open intervals; inclusive `effective_to` converted once | `:286` | IMPLEMENTED + SOURCED | `[design]` |
| Counterfactual `Pin`s; a pinned resolution self-reports | `:2393-2494` | IMPLEMENTED + SOURCED | `[design]`. `provenance()` always reports pins |
| `TRADING_UNIT` | `:633` | IMPLEMENTED + SOURCED | QĐ 894/QĐ-SGDHCM applied 2021-01-04; QĐ 352 Điều 8.1 — the row is graded HIGH, **but carries its own caveat: "the 2020 HOSE lot of 10 is medium-confidence (QĐ 67 was never read)"** (`:655-658`), corroborated by 94,675 HSX closes. The rulebook grades the 100-lot row `high (value) / medium (citation)` (§4:403) and the 10-lot row `medium` (:401) |
| `DAILY_TRADING_LIMIT` | `:672` | IMPLEMENTED + SOURCED | QĐ 352 Điều 9.6 → VNX QĐ 17 Phụ lục III S1.3. **Confidence is per venue, and only HSX flips at 2021-07-05:** HSX `LOW` 2020-01-01→2021-07-04 (`:690-696`); **HNX `LOW` 2020-01-01→2022-03-30** (`:701-707`, "Text never retrieved; the saved fetch is a Cloudflare interstitial"); **UPCoM `LOW` 2020-01-01→2022-11-15** (`:714-720`, "Text never retrieved"). HNXDS INDEX/GB are HIGH throughout. **Ask about a 2021–2022 HNX or UPCoM band — it is corroborated only by corpus fit** |
| `TICK_SIZE` | `:866` | IMPLEMENTED + SOURCED | VNX QĐ 17 Phụ lục III; HNX contract templates. HOSE banded grid delegated to `get_hsx_tick_size`. **Three MEDIUM legs, none of them HIGH:** HOSE banded pre-2021-07-05 (`:879-885`, "Never read; corpus-inferred"), HNX pre-2022-03-31 (`:911-914`, "Never read"), HNX ETF 0.001 (`:922-929`, "No corpus support — the corpus has no HNX fund rows"). §5 gate 4 cites the last of these without its grade |
| `SESSION_SCHEDULE` | `:990` | IMPLEMENTED + SOURCED | HOSE HIGH from 2021-07-05 (QĐ 352 Điều 4.2 verbatim); **LOW** before. HNX/HNXDS MEDIUM |
| `LEGAL_ORDER_TYPES` | `:1116` | IMPLEMENTED + SOURCED | Stored as **mnemonics**. HSX `{LO,MP}`→`{LO,MTL}` at KRX |
| `SETTLEMENT` | `:1266` | IMPLEMENTED + SOURCED | VSD QĐ 211 (T+2 from 2016-01-01), QĐ 109 Art. 4 (13:00 from 2022-08-29) — HIGH. **Only QĐ 109 Art. 4(4) was read verbatim.** QĐ 211's "existence, date and supersession [were] confirmed from Decision 109's own preamble" (`rulebook.py:1293-1294`; rulebook §5.1:458) — it was **not** read |
| `SETTLEMENT`, pre-2022-08-29 branch — `delivery_on_next_session_open=True` | `:1295-1305`, `types.py:2193`, `calendar.py:425-479` | IMPLEMENTED + SOURCED | **A different rule, not just a different clock.** 2016-01-01→2022-08-26 settlement completed 15:30–16:00, *after* the close, so the first usable session is the **open of T+3**. `settles_at` **raises `CalendarError`** rather than guessing when no `TradingCalendar` was supplied. Wired at `exchange.py:2203-2215`. A run over 2020–2022 uses this branch, not the 13:00 one (A50 covers only the post-2022 branch) |
| `SETTLEMENT`, futures | `:1329-1346` | IMPLEMENTED + SOURCED | `(InstrumentKind.FUTURE,)` → T+1, HIGH, VSDC *"Bù trừ và Thanh toán"*. The row's own note: this is **daily variation margin settling T+1, not the contract cash-settling T+1** — "the deposit does not accumulate mark-to-market". That is the sourced counterpart to D1 |
| `INITIAL_MARGIN_RATE` | `:1355` | IMPLEMENTED + SOURCED | Delegates to `vsd_initial_margin`. Press-sourced, **no quyết định number** |
| `MARGIN_MODEL` | `:1403` | PARTIAL | `'pre_margin'` to the KRX cutover (HIGH); **`_unsourced` after** — `margin_model()` raises rather than extending the pre-KRX shape |
| `POSITION_LIMIT` | `:1431` | PARTIAL | INDEX values **LOW**; GB values HIGH. Declared axis gap: GB10's professional-*individual* tier of 3,000 is inexpressible and over-permits by 7,000 |
| `MAX_ORDER_SIZE` | `:1489` | PARTIAL | HOSE 500,000 from 2021-01-04, HNXDS 500 — HIGH. HNX, UPCoM and HOSE-2020 are `_unsourced`, and an UNKNOWN cap refuses nothing (A39) |
| `CHARGE` — **10 ids, 17 dated intervals** | `:1549-1795` | IMPLEMENTED + SOURCED | See §9, which lists all ten. Count reproducible with `python -c "from plutus.market.session.rulebook import _charge_table as t; print(len(t()), sum(len(v) for v in t().values()))"` → `10 17` |
| Covered-warrant band — `_unsourced` **as an assertion of absence** | `:763-777` | IMPLEMENTED + SOURCED | Asserted as an **absence**, which is what `_unsourced` is for. QĐ 352 Điều 9.3; QĐ 17 Điều 31.2(b), HIGH. A CW has **no percentage band**: `ceiling_CW = ref_CW + (ceiling_und − ref_und)/CR`, floor likewise, floor clamped at the 10đ quotation unit. The formula is **sourced but not built** — see §5 and §16.3 #15 |
| `RuleSet.phase` / `session_open` / `session_close` / `SessionSchedule.phase_at` | `:2148`, `:2102`, `:2132`, `:504` | IMPLEMENTED + SOURCED | The dated clock, replacing a module-level `ExchangeSpec` singleton. Three sub-rules worth knowing: **weekends are tested before the clock table** (`_TRADING_WEEKDAYS`, QĐ 352 Điều 4.1) and return `POST_CLOSE`; the **noon break is tested before the continuous window** because `SessionSchedule.continuous` spans it by construction (QĐ 352 Điều 21 is a hard shutdown); **holidays are deliberately not known here** — that is the trading calendar's job |
| `WIDENED_TRADING_LIMIT` | `:781` | PARTIAL | Values sourced; **no non-test caller** — nothing decides which case applies |
| `SymbolRouter` — `(ticker, ts) → Venue` | `:2550-2786` | PARTIAL | Dated `VenueListing` → futures code shape → source's static `exchange_code`; raises rather than defaulting. **`VenueListing` ships empty**, so an HNX→HOSE transfer resolves to the wrong venue unless the caller supplies listings. **Date label corrected:** 2025-07-01 is when HNX stopped *accepting new listing applications* (rulebook:730); the ticker **migration** deadlines are 2025-12-31 / 2026-12-31, and the extension instrument (TT 139/2025) "could not be verified at all" (:732). The hazard is real; do not quote "the 2025-07 transfers" as a dated fact |
| Coverage window enforcement (2020-01-01 … 2026-08-25) | `:136-142`, `:2463` | NOT BUILT | The constants appear only in an error *message*. Verified live: `Rulebook.load('vn-2020-2026').at(2027-06-03).daily_trading_limit(HSX)` returns `Decimal('0.07')` with a HIGH citation |

**Confidence census in code:** 66 HIGH, 11 MEDIUM, 7 LOW, 1 UNVERIFIED, **11**
`_unsourced` rows. (Reproduce with `grep -c "Confidence\.HIGH" rulebook.py` etc.; for
`_unsourced` see the row above — 13 grep matches, minus the `def` and one docstring
mention.)

---

## 5. Order admission

Pipeline is `ExchangeSession.submit` (`exchange.py:811`), fixed order, short-circuit on
first refusal. Only gates 5–10 are inside `Exchange.admits()`.

| Gate | Feature | Where | Status | Source / note |
|---|---|---|---|---|
| 0 | Venue + instrument routing | `exchange.py:1237`, `rulebook.py:2585` | PARTIAL | Routing failures land on `SESSION_SEMANTICS` — **no `ROUTING` rule member exists**. This gate is also where a session with neither `listings=` nor a `source` stops: verified live, `submit()` returns `Rejected(SESSION_SEMANTICS, INDETERMINATE)` with `unresolved_rule='trading_unit'` before any band is consulted |
| 0 | **Covered warrants are unroutable** | `rulebook.py:2717-2727`, `:763` | NOT BUILT | `SymbolRouter.instrument` calls `rules.daily_trading_limit(venue, WARRANT)`, which **raises `UnresolvedRule`** (verified: `at(2024-03-06).daily_trading_limit(HSX, WARRANT)` raises), and `exchange.py` converts that to `Rejected(INDETERMINATE)`. **Consequence: no covered warrant can be admitted through the session at any date.** The doc elsewhere carries an HSX ETF-CW charge row (§9), a `WARRANT` charge class, a warrant tick row and A52 — none of that makes a CW tradeable. §16.3 #15 |
| 1 | Venue configured for this session | `exchange.py:859` | IMPLEMENTED + SOURCED | `[design]` — config, not a market rule |
| 2 | Dated order-type legality | `exchange.py:1317` | IMPLEMENTED + SOURCED | `rules.legal_order_types(venue, phase)`. HIGH except HOSE post-KRX MEDIUM |
| 3 | Dated per-order size cap | `exchange.py:1356` | PARTIAL | A39 — an UNKNOWN cap refuses nothing |
| 4 | Dated tick resolution, pinned into a per-submission judge | `exchange.py:1405`, `rulebook.py:2623` | IMPLEMENTED + SOURCED | HNXDS 1 VND on 100,000đ face (HIGH); HNX ETF 0.001 from 2022-03-31 |
| 5 | `TICK_GRID` | `exchanges/equity.py:62` | IMPLEMENTED + SOURCED | Tick is sourced when injected from the rulebook; the raw `ExchangeSpec` tick is UNDATED |
| 6 | `ROUND_LOT` | `equity.py:75` | IMPLEMENTED + SOURCED | `get_trading_unit(code, date)` — HOSE 10→100 @ 2021-01-04 |
| 7 | `BAND_LIMIT` | `equity.py:89` | PARTIAL | Band comes from `MarketState`, **not from the rulebook** — see A67. INDETERMINATE when either bound is absent |
| 8 | `BAND_LOCK` | `equity.py:104` | IMPLEMENTED + SOURCED | `[design]` — **No Vietnamese rule governs lock evidence** — the `LockEvidence` ladder is ours: `TICK_BOOK` authoritative, `BAR_PROXY` inferred, `UNKNOWN` → INDETERMINATE. The *marketable-into-a-lock* question is a market fact; the evidence grading is a design shape |
| 9 | `FOREIGN_ROOM` | `equity.py:125-148` | DEFERRED | Tradeoff T1. **Fires only for a foreign BUY, and then returns INDETERMINATE**, never REJECTED, because `foreign_room` is `None` on both corpora (A68). It does **not** "never fire" — an earlier wording said so and contradicted A68. A domestic order short-circuits at `order.is_foreign` (defaults False) |
| 10 | `SESSION_SEMANTICS` | `equity.py:150-222` | PARTIAL | Venue asymmetries read from the **UNDATED** `ExchangeSpec`, not the dated schedule |
| 11 | Reservation (`_reserve`) — runs **around** `admits()`, never inside | `exchange.py:1572` | IMPLEMENTED + SOURCED | `[design]` §7.0 |
| — | Derivatives admission: tick, lot-of-one, band **only** | `exchanges/derivatives.py:54-92` | PARTIAL | **No `BAND_LOCK`, no `FOREIGN_ROOM`, no `SESSION_SEMANTICS`.** An ATO in CONTINUOUS is caught only upstream by `_legal_here` |
| — | `Verdict` separates `REJECTED` (a rule said no) from `INDETERMINATE` (data gap) | `market/verdicts.py:28` | IMPLEMENTED + SOURCED | `[design]`. `indeterminate_report()` counts them apart |
| — | Stateful refusals: `UNSETTLED_HOLDING`, `INSUFFICIENT_CASH`, `POSITION_LIMIT`, `INSUFFICIENT_DEPOSIT` | `types.py:524` | PARTIAL | A **second** rejection enum the code itself says must be merged into `AdmissionRule`; consumers must read the `RejectionRule` union |
| — | Segregation annotation on funding refusals | `exchange.py:1707` | IMPLEMENTED + SOURCED | Rulebook 6.3, HIGH. Carries `funded_in_aggregate`, `auto_transfer=False` |
| — | Odd-lot board | — | NOT BUILT | `ROUND_LOT` rejects any non-multiple. HNX and UPCoM ran odd-lot matching for the whole window |
| — | An **LO is legal in both auctions** | `equity.py:25-40` | IMPLEMENTED + SOURCED | `_OPENING_AUCTION_TYPES = {ATO, LO}`, `_CLOSING_AUCTION_TYPES = {ATC, LO}` — enforced here independently of the rulebook table, with a recorded prior defect: the module "previously admitted only the matching auction type and rejected every LO". What a call auction genuinely refuses is the continuous market family (MTL/MOK/MAK/MKT) |
| — | PLO orders | `core/order.py:47` | NOT BUILT | `OrderType` has no PLO member; `_ORDER_TYPE_BY_MNEMONIC` at **`rulebook.py:571-580`** maps `'PLO' → None` (entry at `:579`), so **every** order in HNX `POST_CLOSE_PLO` is rejected. (`rulebook.py:1196` is the legal-order-types row that *stores* `'PLO'` as a mnemonic, not the map) |
| — | Put-through (`Side.CROSS`) | `exchange.py:1630` | DEFERRED | Raises `ValueError`. The `PUT_THROUGH` tick axis exists but no admission path uses it |
| — | Simultaneous opposite-side order ban (TT 120/2020 Art. 7) | — | NOT BUILT | Rulebook OQ #22: unresolved whether the ban is per matching session or per trading day |

### Legal order types, **as stored (mnemonics)**

| Venue | OPENING_AUCTION | CONTINUOUS | CLOSING_AUCTION | POST_CLOSE_PLO |
|---|---|---|---|---|
| HSX pre-KRX | LO, ATO | LO, **MP** | LO, ATC | ∅ |
| HSX ≥ 2025-05-05 | LO, ATO | LO, **MTL** | LO, ATC | ∅ |
| HNX | ∅ | LO, MTL, MOK, MAK | LO, ATC | {PLO} as a mnemonic, **∅ as an `OrderType`** |
| UPCOM | ∅ | **LO only** | ∅ | ∅ |
| HNXDS | LO, ATO | LO, MTL, MOK, MAK | LO, ATC | ∅ |

PRE_OPEN / NOON_BREAK / POST_CLOSE are ∅ at every venue as **explicit sourced rows**.

**The MP/MTL split survives only in the mnemonics.** `_ORDER_TYPE_BY_MNEMONIC`
(`rulebook.py:575-576`) maps both `'MP'` and `'MTL'` to
`OrderType.MARKET_WITH_LEFTOVER_AS_LIMIT`, so `legal_order_types(HSX, CONTINUOUS)`
returns the same `{LIMIT, MARKET_WITH_LEFTOVER_AS_LIMIT}` set at 2023-06-01 and at
2025-06-01. Only `legal_order_mnemonics` distinguishes the two eras. §6's "MP → MTL is a
mnemonic swap, not a semantic one" is the same fact stated from the other side.

---

## 6. Order lifecycle

`session/orders.py` (1,332 lines). The graph, TIF map and terminal triggers are **data**
in `types.py`; `orders.py` holds no second copy.

| Feature | Where | Status | Source / note |
|---|---|---|---|
| 7 states, 4 terminal, single enforcement point | `types.py:273-375`, `orders.py:267` | IMPLEMENTED + SOURCED | `[design]` §12. No `PARTIALLY_FILLED → RESTING` edge, deliberately |
| **The order type IS the time-in-force** | `types.py:445` | IMPLEMENTED + SOURCED | LO/day QĐ 352 Điều 14.1(c),17.2 · ATO/ATC Điều 14.3(b)/14.4(b) · MOK/MAK ASEANSC HNX 2.3 · MTL VNX QĐ 22/2025 Điều 17.2(b) — all HIGH |
| MP → MTL is a **mnemonic** swap at 2025-05-05, not a semantic one | `orders.py:116` | IMPLEMENTED + SOURCED | The map is undated because *legality* moves, not semantics |
| `MKT` matches no Vietnamese order type at any date | `orders.py:177` | IMPLEMENTED + SOURCED | Flat negative finding, rulebook 2.2, HIGH. `accept()` raises on it |
| Terminal triggers per TIF | `types.py:500` | PARTIAL | `NO_OPPOSITE_ORDER` (sourced) and `INSTRUMENT_EXPIRY` (adopted) are **declared but never fired anywhere in `src/`** |
| Single terminal funnel `_terminate` → release hook fires exactly once | `orders.py:550` | IMPLEMENTED + SOURCED | `[design]`. Reservations are still on the record when the hook fires |
| `convert_residue` — MTL leftover becomes a LIMIT | `orders.py:719` | PARTIAL | The **price is the caller's**; the module stays neutral because the derivatives residual price is a recorded CONFLICT (A51) |
| `cancel(order_id, ts, phase=)` | `orders.py:838` | PARTIAL | `phase=None` means the lock is **not evaluated at all**. **No `tif.rests` guard** — an `ACCEPTED` MOK is cancellable |
| Amend/cancel phase locks | `orders.py:220-264` | PARTIAL | Every phase locked **except CONTINUOUS**. PRE_OPEN/POST_CLOSE/UNKNOWN are ADOPTED (A42) |
| `amend()` — quantity **decrease** only at Tier 1 | `exchange.py:938`, `orders.py:893` | PARTIAL | Price amends and amend-ups refused. Stated reason: re-taking a reservation on the same key is refused by design, and release-then-retake can leave a live order unfunded |
| Price+quantity-together ban, dated | `exchange.py:1306` | IMPLEMENTED + SOURCED | Allowed to 2025-05-04 (QĐ 17 Điều 22.3); barred from 2025-05-05 (VNX QĐ 22/2025 Điều 21.3, verbatim) |
| Priority survives a **pure quantity decrease** and nothing else | `orders.py:357` | IMPLEMENTED + SOURCED | VNX QĐ 17 Điều 22.3 read verbatim, effective 2022-03-31. Vietnam has exactly two priority levels: price then time |
| `expire_due` at session boundaries | `orders.py:1038` | PARTIAL | Immediate families deliberately **not swept in this module** — a live MOK at a boundary is left visible rather than killed by an invented rule. **True of `orders.py` in isolation, false of the session:** `ExchangeSession._sweep_non_resting` (`exchange.py:1796-1840`, called from `:1773`) expires every non-resting type at the day's close with its **own** trigger via `_CLOSE_TRIGGER_BY_TIF` (`exchange.py:261-264`) — ATO/ATC → `AUCTION_CROSS`, MOK → `NOT_FILLABLE_IN_FULL`, MAK → `IMMEDIATE_REMAINDER` — explicitly so a reservation is not held for the rest of the run. **MOK reservations do not leak overnight** |
| Order ids `PLU-%08d`, lexical order = issue order | `orders.py:399` | IMPLEMENTED + SOURCED | Justified by rulebook 2.4. Breaks silently past 99,999,999 |
| Amendment does **not** update encumbrances or re-run admission | `orders.py:893` | NOT BUILT | Undocumented in `orders.py`; `exchange.py` wraps it, but the module in isolation permits an under-reserved amended order |

---

## 7. Fills

`session/fills.py` (2,624 lines). Three shipped policies behind one seam.

| Feature | Where | Status | Source / note |
|---|---|---|---|
| `FillPolicy` protocol + `BaseFillPolicy` template that **stamps the signature** on every decision | `fills.py:193-330` | IMPLEMENTED + SOURCED | `[design]` §8. A subclass cannot return an unstamped decision |
| Fill price — auction: published open/close; continuous: the order's **own limit** | `fills.py:48-73`, `:581` | IMPLEMENTED + SOURCED | **The strongest citation in the module**: Vietnamese matching trades at the **resting** order's price — QĐ 352 Điều 6.3, HIGH |
| Fill quantity floored to the **dated** trading unit | `fills.py:465-548` | IMPLEMENTED + SOURCED | Documents a reproduced defect: reading the undated spec sized every pre-2021 HOSE fill at 100, and 82.2 % of the HSX sample predates the change |
| `max_participation` aggregates across the caller's own live orders | `fills.py:551` | IMPLEMENTED + ASSUMED | A34. Explicitly **a bound on our claimed share of observed liquidity, not a model of impact** |
| `SoftFillPolicy` | `fills.py::SoftFillPolicy` | PARTIAL | Self-described comparison arm, "not the recommended policy". **Changed 2026-08-27:** it is now a `_CappedFillPolicy` taking an optional `max_participation`, so it obeys the lot floor and the cap **when one is supplied**; `SoftFillPolicy()` with no argument is byte-for-byte the old uncapped baseline, which is what `compare_policies` runs. Its signature is now `soft(max_participation=0.25)` / `soft(max_participation=uncapped)` and **the bare token `soft` is no longer produced by anything**, deliberately, so a repaired uncapped run cannot be confused with a record written while the configured cap was being discarded. Measured live: HPG buy 1,000 at a cap of 0.00001 fills **300** where the uncapped arm fills 1,000, and `hard` at the same cap fills the identical 300 — the arms differ on *whether*, never on *how much* |
| `HardFillPolicy` | `fills.py::HardFillPolicy` | IMPLEMENTED + SOURCED | Fills a strictly-through auction order (QĐ 352 Điều 6.2(a), HIGH) but returns INDETERMINATE at a continuous **touch** — time priority is unrecoverable, 81 % of best-quote changes carry no trade. **No longer vacuous on the shipped corpus (2026-08-27):** `DataHubSource` serves `quote_dailyvolume`, so the participation cap is computable and `hard` now decides. Measured — `order_cycle`'s HPG buy fills where it used to be INDETERMINATE, and `equity-margin`'s hard arm goes from **0 fills, no debt, ratio 1.000 for 31 sessions and no call** to **3 fills, 69,079,147đ of margin debt carried, and 6 margin calls**. It still cannot return a definite `NO_FILL` for a limit the day's low never reached, because `quote_open`/`quote_max`/`quote_min` are on disk and **not served**, and every fill it takes that way is counted `fill.decided_without.{open,high,low}` |
| `ProbabilisticFillPolicy` — seeded, counter-based BLAKE2b draw | `fills.py:1256`, `:1205` | IMPLEMENTED + ASSUMED | A35/A36. `draw_key` deliberately excludes `remaining_quantity` and the policy's own parameters, so a partial fill elsewhere cannot re-roll a decision. Prior art cited, not claimed as novel |
| **18** distinct `INDETERMINATE` return sites | `fills.py:406, 721, 733, 754, 897, 907, 925, 1088, 1104, 1117, 1142, 1568, 1581, 1591, 1618, 2235, 2245, 2263` | IMPLEMENTED + SOURCED | `[design]` §8 — returning INDETERMINATE rather than guessing is the design decision; **the count itself is a code fact with no source, and must be re-derived, not cited.** **There is no catalogue.** An earlier revision of this row cited an artefact "F-I1…F-I20" that has never existed anywhere in the repo (`grep -r "F-I" src/ tests/ docs/` hits only this file) and gave the count as 20. Re-derive with `grep -n "FillDecision\.indeterminate(" src/plutus/market/session/fills.py`. **Four name no `DataField`** — `:925, :1142, :1618, :2263` pass a literal `()`, because the missing thing is a rulebook fact or an unrecoverable queue position. Three more (`:754, :1104, :1581`) pass `[field] if field is not None else ()`, i.e. empty only when the interval carries no price field at all |
| `probabilistic_sweep` — one policy per `p_touch`, all sharing a seed | `fills.py:1641-1675` | IMPLEMENTED + SOURCED | `[design]` — its own docstring calls this **"the intended use"** of the probabilistic policy: a nested family whose range is interpretable. Given A35 (`p_touch` "has no empirical content"), **this is the mitigation** — a run should report the sweep, not a single draw |
| `build_fill_policy(config)` + **`parse_fill_policy_config(payload)`** | `fills.py::build_fill_policy`, `::parse_fill_policy_config`, `::HONOURED_CONFIG_FIELDS` | PARTIAL | Refuses to default the seed. **Stated config limitation:** `FillPolicyConfig` carries only `kind` / `max_participation` / `seed`, so a config-built `probabilistic` policy **can never set `p_touch` or `p_auction_margin`**. **Silent-drop sweep added 2026-08-27:** two guards, because a field nobody reads is a run under a configuration that was never applied. (a) any field on the `FillPolicyConfig` dataclass outside `HONOURED_CONFIG_FIELDS` **raises** — a tripwire, so adding `p_touch` upstream breaks the builder until somebody wires it; (b) a field set but unusable by the selected kind raises — `{kind: soft, seed: 7}` and `{kind: hard, seed: 7}` used to run with the seed read by nothing. `parse_fill_policy_config` additionally refuses unknown **YAML keys**. **Wired 2026-08-27:** `exchange.py::parse_config` now routes its whole `fill_policy` block through it instead of reading three keys with `.get()`, so an unknown key is refused on the session's own path and an absent `max_participation` becomes `None` rather than a re-supplied `'0.10'` |
| `compare_policies` / `DivergenceReport` | `fills.py:1870`, `:1747` | IMPLEMENTED + SOURCED | `[design]` — our own comparison instrument, no Vietnamese source. `agreement_rate` returns `None` on an empty flow — 0/0 is not 100 % |
| ATO/ATC matched **ahead of all limit orders** at every level | `fills.py:1123` | IMPLEMENTED + SOURCED | QĐ 352 Điều 14.3-14.4 — unconditional to 2025-05-04, still ahead of in-band limits after |
| Allocation **at** the marginal auction price | `fills.py:1141` | DEFERRED | Sourced as an **absence** — rulebook 2.4 records it UNVERIFIED. Returns INDETERMINATE rather than guessing |
| Queue-position matching against a reconstructed book | — | DEFERRED | §16. No order ids exist in the corpus; `probabilistic` is the honest ceiling |
| The interval a policy is handed on a daily run is the **whole day** | `exchange.py:1545-1550` | IMPLEMENTED + ASSUMED | **A69 — declared look-ahead.** Not a fills.py behaviour, but it conditions every daily-resolution decision this table describes |

---

## 8. Settlement and cash

`session/ledgers.py` (2,019 lines).

| Feature | Where | Status | Source / note |
|---|---|---|---|
| Encumbrance ledger — reserve on accept, release on **every** terminal edge | `ledgers.py:176-388` | IMPLEMENTED + SOURCED | `[design]` §7.0, the second locked shape. One ledger serves both pools |
| Pro-rata partial-fill release of the **original reservation** | `ledgers.py:297` | IMPLEMENTED + ASSUMED | A48 |
| **Tranche-list** holdings; parcels never merged, even at identical instants | `ledgers.py:394-593` | IMPLEMENTED + SOURCED | `[design]` §7.1, the third locked shape. Forbidden: scalar pairs |
| T+2 settlement, dated, with the 13:00 delivery regime | `rulebook.py:1266`, `exchange.py:2203` | IMPLEMENTED + SOURCED | **T+2 since 2016-01-01.** HIGH. **Only QĐ 109 Art. 4(4) was read verbatim**; QĐ 211 is known from Decision 109's own preamble (`rulebook.py:1293-1294`) |
| **Pre-2022-08-29 regime: delivery at the next session's open** | `rulebook.py:1295-1305`, `calendar.py:425-479`, `exchange.py:2203-2215` | IMPLEMENTED + SOURCED | Settlement completed 15:30–16:00, after the close, so T+3's open is the first usable session. `settles_at` **raises `CalendarError`** rather than guessing when the caller supplied no `TradingCalendar`. **Any run over 2020–2022 is on this branch**, which A50 does not cover |
| `sellable = settled − committed`; pending proceeds excluded unless advanced | `types.py:1420`, `:1485` | IMPLEMENTED + SOURCED | 100 % pre-funding — rulebook **§5.2:489-490** (TT 120/2020 Art. 7(1)(a), verbatim, HIGH). §5.1 supports the pending-proceeds half only |
| The headline behaviour: buy at T0, sell same day → **refused**; accepted once the tranche settles | `ledgers.py:1809` | IMPLEMENTED + SOURCED | The rule is rulebook §5.2:492 (sell-side pre-funding) — **a test is not a source**, and the mirror test pins the behaviour rather than sourcing it |
| Buy reservations are **grossed up by worst-case charges** | `ledgers.py:1492-1545`, called at `:1749`; `types.py:923` | IMPLEMENTED + SOURCED | `[design]` — Design §7.0 puts estimated charges **inside** the encumbrance so `available` stays consistent with what a fill costs. Three declared choices ride on it: the reservation price is the limit for an LO and the **ceiling** for market/auction families (A49); `DAILY`-debited rows are included although `assess_charges` never levies them; and the commission tier is taken at the **dearest** band (`charges.py:686` `worst_case_tier`) because the day has not happened yet (A16/A18). Over-reserving is the conservative direction |
| DVP — both legs driven from one `settle_due` call | `ledgers.py:1987` | IMPLEMENTED + SOURCED | Rulebook 5.1, one allocation event |
| Short equity position impossible — `debit_settled` overdraw raises | `ledgers.py:488` | IMPLEMENTED + SOURCED | Rulebook 5.2 |
| Sale advance (*ứng trước tiền bán*) — legal status and formula | `ledgers.py:596-1401` | PARTIAL | Luật CK 54/2019 Art. 86(1)(b); cap ≤ 1 because a securities company may not lend (TT 121/2020 Art. 27). **Grade the second half `low`:** rulebook **§5.2:511** is the row, and it says the article was *"read in summary form only, not verbatim"*. **`ledgers.py:628, :726, :1209` all cite "rulebook 8.4", which does not exist** — §8 runs 8.1 Taxes / 8.2 Exchange and depository prices / 8.3 Brokerage commissions and stops (D28) |
| Sale advance — **rate, cap, day-count, minimum** | same | IMPLEMENTED + ASSUMED | A4, A7–A13 |
| **Advance interest is reported but never charged** | `ledgers.py:1369-1379` | PARTIAL | No code path debits it. Not in `charges()` either — `ChargeBase` has no financing member. An advance is free in every balance the simulator reports |
| Negative net proceeds accepted (broker minimum > gross on a penny stock) | `ledgers.py:1093` | IMPLEMENTED + SOURCED | `[design]` — No Vietnamese rule addresses it. Our reason: refusing it destroyed shares |
| Settlement calendar as a **caller-supplied data input** | `calendar.py:140` | PARTIAL | Mechanism reproduces the rulebook's Tết-2026 worked example; **no calendar data ships** (A64) |
| Short selling | — | NOT BUILT | Rulebook §5.2:513-514. Use the rulebook's own instructed phrasing: *"framework exists since 2016 (TT 203/2015 Art. 11), re-enacted in 2020 (TT 120/2020 Art. 11), **never operationalised**"* — **not "prohibited"**, which the rulebook says is legally imprecise. The load-bearing consequence is unchanged: no short sale is admissible anywhere in 2020-01-01 → 2026-08-25 |

---

## 9. Charges and taxes

`session/charges.py` (1,283 lines) does the arithmetic; the rows live in `rulebook.py`.

| Charge | Value and dates | Where | Status | Source |
|---|---|---|---|---|
| PIT, securities transfer | **0.001**, SELL only, from 2015-01-01 | `rulebook.py:1583` | PARTIAL | HIGH confidence but **the row names no decree** — the only state row whose `document` is a description |
| PIT, derivatives transfer | `0.0005 × IM ratio` of notional ≡ 0.001 × margined value. Effective 0.000085 from 2022-12-15 | `rulebook.py:1599` | IMPLEMENTED + SOURCED | Công văn 11133/BTC-CST (2017-08-21), restated by TT 87/2026 Điều 5.1. MEDIUM — for 2017–2026 the rule rested on a **letter**, not a gazetted document |
| HSX equity service price | 0.0003 → **0.00027 @ 2020-03-19** | `rulebook.py:1623` | IMPLEMENTED + SOURCED | TT 127/2018; QĐ 1541/QĐ-BTC. HIGH. See A25 for the 2025 gap |
| HNX equity / HSX ETF-CW / UPCoM equity | same step at 2020-03-19 | `:1646`, `:1665`, `:1688` | IMPLEMENTED + SOURCED | HIGH |
| Index-futures exchange fee | 3,000 → **2,700 VND/contract @ 2020-03-19** | `:1707` | PARTIAL | HIGH. **Declared gap: GB futures' 4,500 VND is not carried** — `ChargeRule` has no product-family axis within a venue |
| VSDC custody, equity | 0.3 → **0.27 VND/unit/month** | `:1732` | PARTIAL | HIGH, but **never levied** — `assess` and `estimate` both skip MONTHLY rows |
| VSDC derivatives position management | 3,000 → 2,550/contract/day, row **ends 2022-01-01** | `:1752` | PARTIAL | HIGH. Note records brokers demonstrably billed it through ≥2024-07-11 — gazetted-schedule runs and actual-cost runs disagree for ~3 years. Never levied |
| VSDC derivatives clearing | **2,550 VND per novated contract, both legs**, from 2022-01-01 | `:1781` | IMPLEMENTED + SOURCED | HIGH |
| Broker commission — flat | per-venue rows from `BrokerProfile` | `types.py:2488` | IMPLEMENTED + ASSUMED | Per firm, unsourced by nature |
| Broker commission — **tiered** | `CommissionSchedule` + `assess_daily` | `charges.py:560-1239` | PARTIAL | Tier **shape** sourced (SSI/VPS wording); **arithmetic landed, never wired** — **no session call site supplies a `CommissionSchedule`**. (`commission=` *is* passed internally at `charges.py:1110`, `:1136`, `ledgers.py:1544`, `:1579` — plumbing, not a caller. The session calls `assess_charges` without it at `exchange.py:2014` and `estimate_charges` without it at `ledgers.py:1749`; `assess_daily` has only test callers) |
| Derivatives PIT **at contract maturity** | only the tax, HNXDS only | `charges.py:1145-1181`, wired at `exchange.py::_maturity_charges` | IMPLEMENTED + SOURCED | Rulebook 8.1 / 12.3: derivatives PIT is due when the order is matched **or at contract maturity**, and a held-to-expiry contract is never matched out, so a fill-only model under-charges by one leg. Refuses non-HNXDS venues with `ValueError`; deliberately levies *only* the tax (exchange and clearing fees are not sourced for a final cash settlement). **Wired 2026-08-27** — `_mark_derivatives` calls `_maturity_charges` on every settled expiry, debits the deposit through `_debit_charges` and reports `charges` / `charges_total` on the `EXPIRY_SETTLED` event. Measured: one VN30F2211 lot settling at 972.5 on 2022-11-17 pays **6,321 VND** that it previously paid nothing for. The 5,250 of exchange + clearing fee that a *traded* close pays is still not levied here, on purpose and for want of a source. Closed §16.3 #16 |
| `ChargeBasis` — the finer, seven-member basis vocabulary | 7 members, 5 of them fill bases | `charges.py:268-291`, `FILL_BASES:297`, `basis_for:339` | IMPLEMENTED + SOURCED | Refines `types.ChargeBase` because "two rows share `ChargeBase.TRADE_VALUE` and do not share a basis": the exchange service price is a fraction of cash trade value on HSX and of futures **notional** on HNXDS, and the derivatives PIT is a fraction of the **margined** value. `CONTRACT_DAYS` / `SECURITY_MONTHS` are listed to make the map total and are **skipped rather than approximated** by every per-fill function (rulebook 12.2) |
| `margined_value = notional × IM / 2` | the derivatives PIT base | `charges.py:228` | IMPLEMENTED + SOURCED | The `/2` **is in the published source** |
| `_pit_rate_check` — refuses if the two statements of the derivatives PIT drift | a guard, not a rate | `charges.py:950` | IMPLEMENTED + SOURCED | A live detector, so the VSD ratio cannot fork between `margin.py` and the tax model |
| Statutory commission cap | 0.5 % → 0.45 % @ 2022-01-01; **no floor since 2019-02-15** | `charges.py:733` | PARTIAL | Reported, **never enforced**. Derivatives caps are A22 |
| VAT | `vat_applies` default False | `types.py:2347-2348`, `charges.py:935-947`, `:1018`, `:512`, `exchange.py:2191-2200` | PARTIAL | **Status corrected from NOT BUILT — the arithmetic is implemented in three places** (`vat_on`, `Charge.vat`/`LeviedCharge.total`, and `exchange.py` computes and stamps VAT on derivative charges). What is missing is the *input*: **no rulebook row and no config path ever sets `vat_applies=True`**, so the documented 2025-04-29 VAT-exclusive regime is representable but unreachable — the same shape as tiered commission, not an absence |
| VSDC collateral-management fee | 0.0024 %/account/month, min 100,000đ / max 1,600,000đ (min 320,000đ before 2022-01-01) | — | NOT BUILT | Dated rows are at rulebook **§8.2:816-817** and **§12.5:1161**; §9.1:870 carries it as a code *correction*. `_charge_table` has no such row, so a margined account is charged nothing for holding collateral |
| Settlement-bank charge | 0.0001 of net settlement value, min 5,000 / max 300,000 VND per member per day | — | NOT BUILT | Rulebook §12.6:1179-1180 — and note the rulebook itself says it is "not attributable to individual fills" and should be an optional member-level cost, off by default for a single-account backtest |
| Monthly / daily accrual pass | — | — | NOT BUILT | Nothing ever levies a MONTHLY or PER_OPEN_CONTRACT_PER_DAY row. A buy-and-hold run pays no custody at all |
| Rounding to whole đồng | ROUND_HALF_UP | `charges.py:169` | IMPLEMENTED + ASSUMED | A14 — **UNVERIFIED for every charge** |

---

## 10. Corporate actions

`session/corporate.py` (2,158 lines). **Caller-driven — not wired into `advance_to`.**

| Feature | Where | Status | Source / note |
|---|---|---|---|
| Ex-date reference principle | `corporate.py:119` | IMPLEMENTED + SOURCED | QĐ 352 Điều 10.3; VNX QĐ 17 Điều 32.4; QĐ 22/2026 Điều 33.4 — from 2021-07-05, **HIGH**. UPCoM carries the identical clause with round-lot VWAP |
| The adjustment **algebra** | `corporate.py:131` | IMPLEMENTED + ASSUMED | A26 — **NOT IN ANY GAZETTED DOCUMENT**, MEDIUM |
| Cash dividend, stock dividend, bonus, rights, combined, split, consolidation | `:661-885` | IMPLEMENTED + SOURCED | Principle gazetted, arithmetic per A26 |
| Split/consolidation is a **resumption**, not an ex-date | `:146` | IMPLEMENTED + SOURCED | QĐ 352 Đ10.5; halt trigger QĐ 17 Đ40.1(b) — HIGH |
| Reference rounded to the quotation unit | `:160`, `:720` | PARTIAL | Rounding **to the tick** gazetted (QĐ 22/2026 Đ33.8, HIGH); **direction** is A27 |
| HOSE ex-rights codes 01–07, 16 | `:245` | IMPLEMENTED + SOURCED | Gazetted from 2025-05-05; XD/XR/XA/XI before |
| Two sourced **no-adjustment** cases (treasury-share distribution; cash dividend ≥ base price), dated per venue | `:896-973` | PARTIAL | Band is widened instead — but `RuleSet.widened_trading_limit` carries no row for either, so the band value is named in citations only, never returned. Before the dated start, the module **raises** rather than clamping |
| Unit discipline — every money field is VND **per share**, divided by `CURRENCY_UNIT` before entering the formula | `:837` | IMPLEMENTED + SOURCED | Rulebook §12.1 ("declare these once, in code") is the source for stating the unit convention explicitly. Skipping it turns a 2,000đ dividend on a 25.5 close into −1974.5 |
| Entitlement counts **unsettled** parcels | `ledgers.py:551` | IMPLEMENTED + SOURCED | The record date is one settlement cycle after the ex-date exactly so the last cum-rights buyer is on the register |
| Rights subscription priced and funded **before** anything moves | `:1379-1575` | IMPLEMENTED + SOURCED | Shortfall raises with the account untouched. `take_up` has **no default** — a portfolio decision the engine refuses to make |
| **The record and the ledger agree across an ex-date** (§12 invariant 4), and a **per-order** meter for it | `corporate.py::_scale`, `orders.py::OrderBookOfRecord.encumbrance_divergence`, `::EncumbranceDivergence` | IMPLEMENTED + SOURCED (`[design]`) | Added 2026-08-27. `_scale` released and re-took the ledger reservation and then rebuilt the **record's** tuple separately, so the two drifted: measured on a live reproduction, a BUY's record said 95,500,000 where the ledger held 95,485,000, and — worse, because it under-reports a commitment — a SELL's record said 1,000 shares where the ledger held 2,000, so a caller summing records would think it could sell the parcel twice. **Fix:** the record is now *read back* from the ledger (`book.set_encumbrances(id, account.encumbrances.of(id))`), so one place does the arithmetic and a rounding cannot separate them. Every other ledger-mutating site in `src/` was swept and already updated the record; this was the one instance. **The meter is the general fix:** `validation/identities.py::encumbrance_matches` compares two *totals* and a run samples it where nothing is live and both sides are zero, which is why a 2,034,329đ divergence lasting the whole life of a resting order read as clean. `encumbrance_divergence` is the per-order, any-instant form — it names order, state, resource, ticker and **both** numbers, and sweeps terminal orders too. ⚠️ **Nothing calls it yet**: wiring it into `identities.py` as a tenth breach source is the follow-up that turns the meter on |
| `RestingOrderPolicy` — CANCEL / SCALE | `:1071`, `:1612` | IMPLEMENTED + ASSUMED | A28. `SCALE` scales the limit by `ReferenceAdjustment.ratio` — the one ratio with a gazetted precedent (QĐ 22/2026 Điều 36 adjusts a warrant's strike by exactly it) |
| Fractional residue | `:1539` | PARTIAL | A29 — computed and reported, never priced |
| Dividend withholding tax | — | NOT BUILT | A32 — cash leg credited **gross**, and `cash_leg_is_gross` is a field so a report cannot omit it. **The reason stated in A32 and in `corporate.py`'s `PROVENANCE` is false** (the rulebook does carry a 5 % row at §12.3:1112, `low (uncited)`); the true reason is that `rulebook.py::_charge_table` has no dividend row. See D27 |
| `CorporateActionSchedule` + `CorporateActionEngine.due` / `apply_due` | `:980-1055`, `:1316`, `:1334` | IMPLEMENTED + SOURCED | `[design]` — the exogenous-feed shape: a caller hands in a dated schedule and asks what is due at an instant. No Vietnamese rule governs it |
| **The corporate-action audit subsystem** — `SessionView` protocol, `UnhandledCorporateAction`, `CorporateActionReport`, `CorporateActionAudit` | `:1804`, `:1828`, `:1849-1917`, `:1920-2007`, error at `:350` | IMPLEMENTED + SOURCED | `[design]` — ~200 lines answering "did this run cross an ex-date with nothing applied, and which instruments are therefore wrong?". `is_clean` / `affected_tickers` / **`exposed_tickers`** / `raise_if_unhandled`, where `exposed_tickers` is what distinguishes *clean because nothing happened* from *clean because we looked at nothing*. **Opt-in** — it is the defence for the DEFERRED row below, and it does nothing unless the caller runs it |
| Engine wired into `advance_to` | — | DEFERRED | Deliberate: a CA feed is exogenous data, and a session that invented an ex-date would be worse than one that says it does not know. `CorporateActionAudit` (above) is the defence |

---

## 11. Derivatives and margin

`session/deposit.py` (2,063 lines) is the **intraday** layer and is what the client ladder
is tested against. `session/scenario_margin.py` (2,989 lines) is the **overnight** one and
`session/overnight.py` is the seam that reaches it — both wired 2026-08-27; before that the
second existed with no call site anywhere. `market/margin.py` is a retained batch-research
path whose central quantity **does not exist** — do not extend it.

> **Regime notice, 2026-08-26.** QĐ 26/QĐ-HĐTV and its Phụ lục 2 were obtained and read.
> Everything in this table implements the **pre-KRX** margin regime and is correct for
> dates to **2025-05-04**. From **2025-05-05** the requirement is assembled differently —
> `MR = Max(Σ Pgm, 0)`, `Pgm = Max((Rm + Sm + Dm), MM)`, **no variation-margin term** —
> and none of it is built. The full reading is
> `docs/reference/post-krx-margin-spec.md`. Two rows below changed *status*, one was
> withdrawn as a citation, and three new NOT BUILT rows were added.

| Feature | Where | Status | Source / note |
|---|---|---|---|
| **`MR = IM + VM`**, computed on the whole account portfolio | `deposit.py::account_margin_requirement` | PARTIAL | VSDC "Thông tin về ký quỹ" §II.4(a), HIGH — **and correct only to 2025-05-04.** QĐ 26 Điều 20 settles position P&L as a separate daily cash movement and Phụ lục 2 §6 has no VM term at all, so from the cutover this shape is wrong and is applied anyway, at every date, with the divergence stated in the module docstring. `account_margin_requirement(Position(...))` raises `TypeError` by design — the fifth locked shape, and QĐ 26 Điều 5.5 now sources the per-investor-account unit it enforces (*"cho danh mục vị thế trên từng tài khoản giao dịch của nhà đầu tư"*) |
| IM recomputed on the **current** price, never entry notional | `:726` | IMPLEMENTED + SOURCED | Rulebook 6.3, HIGH |
| **VM loss-only**, netted account-wide before the sign test | `:729-734` | IMPLEMENTED + SOURCED | VSDC verbatim: *"chỉ được tính vào … ở trạng thái lỗ"*. A symmetric model mis-times calls in both directions |
| Offsetting trades attract **no new IM** | `:1351`, `:1514` | IMPLEMENTED + SOURCED | *"giao dịch đối ứng của cùng một tài khoản giao dịch"* |
| Utilisation ladder 80 / 90 / 100 **applied to margin** | `deposit.py::margin_status`, `broker.py` | IMPLEMENTED + **ASSUMED (shape *and* levels)** | **Re-graded 2026-08-26; this row previously read SOURCED (shape).** The chain Art. 13, QĐ 96 → QĐ 61 → QĐ 12 → QĐ 26 was followed to its end: **QĐ 26 Điều 13 contains no percentage.** Post-KRX the attribution is definitively dead; pre-KRX it is **UNVERIFIED, not disproven** — QĐ 61 and QĐ 12 have never been read, so this is a collapsed citation, not a demonstrated error. Numeric defaults unchanged on purpose. **A1–A3.** One older MBS PDF misprints level 3 as 90 % — do not cite it either |
| — the one rung that *is* sourced: `forced_close_utilisation = 1.00` | `deposit.py::margin_status` | IMPLEMENTED + SOURCED | `MR / assets ≥ 1` ≡ `assets ≤ MR`; QĐ 26 Điều 13 tests `assets < MR`. Coincide except at `assets == MR`, cured under Điều 13.2.c and a breach here |
| Warning ladder 80 / 90 / 100 **on POSITION LIMITS** — where the primary text actually puts it | — | **NOT BUILT** | **QĐ 26 Điều 29**, HIGH, read verbatim: level 1 at 80 %, level 2 at 90 %, level 3 at 100 % of *giới hạn vị thế*; 1 and 2 are notices to the clearing member (Điều 29.2); level 3 suspends the account, permits **only** offsetting trades, gives **03 working days**, and **invalidates an offsetting trade that fails to bring the account below level 3** (Điều 29.3.b), routing it to the error-handling account (Điều 29.4). **Three reasons it is not a small addition:** (1) we do not compute the quantity the percentages apply to — Điều 27.2.a counts across expiry months, we count per contract code (D33); (2) `DerivativesAccount` has **no account-level suspension state**, only per-order gates, so a level-3 suspension has nowhere to live; (3) Điều 29.3.b is a **post-match invalidation**, and nothing in the session models reversing a matched trade. Levels 1 and 2 would also need event vocabulary in `types.py`/`exchange.py`, outside this module |
| Level 3 = suspension from **opening** new positions, offsetting excepted | `deposit.py::reserve_for_order` | IMPLEMENTED + SOURCED (behaviour) / ASSUMED (trigger) | **Behaviour upgraded to primary-sourced:** QĐ 26 Điều 13.2.a wires the member to *"không thực hiện giao dịch mở mới vị thế trên tài khoản vi phạm, ngoại trừ giao dịch đối ứng để đóng vị thế"*. The **trigger** is ours: Điều 13 fires on `assets < MR`, not on a 100 % rung. "Level 3" is the code's name for the top rung and is **not** a citation to Điều 29's level 3 |
| IM ratio series, dated | `margin.py:129`, `rulebook.py:1355` | IMPLEMENTED + SOURCED | 0.10 / 0.13 / 0.17. Press-sourced, **no quyết định number exists**; 0.175 matches nothing at any date |
| Contract multipliers, dated and cited | `deposit.py:495-587` | PARTIAL | VN30F 100,000 (2017-08-10), VN100F 100,000 (2025-10-10), GB05 10,000 (2019-07-04), GB10 10,000 (2021-06-28) — all HIGH, and `deposit.multiplier_for` **raises** on a missing one, so **margin is always right**. **"Never defaulted" is false through the adapter path:** `adapters/datahub.py:38` matches `^(VN30F\|VN100F\|GB\d)` and `:239-248` stamps `multiplier=100000` on **every** match; `SymbolRouter.instrument` (`rulebook.py:2732-2733`) takes `base.multiplier` from the source when one exists and only falls back to `_default_multiplier` (`:2774-2786`, correctly GB → 10,000) when there is none. Verified live: no-source `GB05F2312` → 10,000; DataHub-shaped `GB05F2312` → 100,000. `session.instrument()` therefore returns the wrong number to the caller (D25) |
| Position limits | `deposit.py::reserve_for_order` | PARTIAL | See §4. Enforced at exactly one site and only when `rules is not None`; `InvestorClass` is never asked of the caller (A58). Three declared conventions ride here: the cap is tested against the **worst-case net** (A70), margin charged is the **increment** and therefore order-dependent (A71), and a `BrokerProfile.margin_buffer` disagreeing with the account's **raises** rather than picking one. **Two new sourced divergences, 2026-08-26:** the count is per expiry where Điều 27.2.a sums across expiries (**D33**), and the cap is exclusive where Điều 29.1.c is inclusive (**D34**). QĐ 26 Điều 27.1 confirms the mechanism and publishes no number, so the LOW grade on the values stands |
| Margin withdrawal bound = `balance − MR / forced_close_utilisation` | `deposit.py::transfer_out` | IMPLEMENTED + SOURCED | Rulebook line 602, VSDC §VI and §IV.3, HIGH — **and now primary-sourced: QĐ 26 Điều 11.1 states the same three conditions verbatim.** Condition (2) — securities withdrawn ≤ posted — has no representation because collateral is cash-only. Condition (3) is **narrower than the source**: Điều 11.1.c bars withdrawal from an account suspended for margin breach, position-limit breach *or* payment default; we test only the first (**D35**) |
| Segregated deposit; **no auto-transfer** | `:762-846` | IMPLEMENTED + SOURCED | Rulebook 6.3, HIGH. Segregation is an import boundary: the module cannot reach securities cash |
| `DepositEntry` / `DerivativesAccount.entries` — a full audit trail of every deposit movement | `:231-246`, `:906-908` | IMPLEMENTED + SOURCED | `[design]` §7.4 — a `ForcedLiquidation` must state "the resulting deposit balance", which is not reportable from a scalar mutated in place. `amount` is signed; every entry carries `balance_after` |
| `MarginMonitor` — carries a call across days, cure measured in **sessions** | `deposit.py::MarginMonitor` | IMPLEMENTED + ASSUMED | A5. `INDETERMINATE` advances **no state**: a deadline that passes during a blind stretch survives it. The docstring's old hedge (*"do not hard-code either number"*, resting on a LuatVietnam summary) is replaced by the sourced member-side deadlines — 16h30 wire, 09h30 T+1 top-up, 03 working days to substitute-member close-out. **A forced close now LATCHES until the account clears back to `WARNING`/`OK`** (added 2026-08-27, `validation/scenarios/deriv-margin.py` finding F1): the machine used to drop its call state on escalation, so an account force-closed at the 09:30 mark and still at 0.9335 at 14:45 the *same session* was handed a fresh call with a fresh next-session deadline — a de-escalating event sequence and an unearned second grace period. Measured on VN30F2210 from 2022-09-26. `MarginMonitor.in_forced_breach` reports the latch; it releases on a genuine return to the warning rung, so a later call still fires |
| **Broker margin profiles wired into the session** — `broker_profile.firm` in the config | `exchange.py::parse_config`/`_broker_profile`, `types.BrokerProfile.from_margin_profile`, `ExchangeSession.build` | IMPLEMENTED + SOURCED (per firm) | Added 2026-08-27. `broker_profile: {"firm": "TCBS"}` resolves a shipped profile, converts it with `to_broker_terms()` and records the firm, the user-facing `margin_model`, its engine and `margin_model_is_assumed` in `SessionProvenance`. **Three refusals rather than a guess:** a profile whose `user_facing_model` is `OVERNIGHT` raises `NotImplementedError` — **narrowed 2026-08-27**, and it no longer says the engine is unwired. `scenario_margin.py` **is** wired now (see the overnight layer row below) and the grid's number is computed for every profile; what cannot be done is put it on the utilisation **ladder**, because `MarginView.required` is the property `initial_margin + variation_margin` and Phụ lục 2 produces neither term. Writing it into `initial_margin` and zeroing `variation_margin` would report a decomposition that did not happen and corrupt `free_deposit` and `posted_margin` with it. All twelve shipped profiles name `INTRADAY`, so nothing shipped is refused here; naming a firm *and* a utilisation level in one payload raises; and a ladder whose first **closing** rung is not the third is refused — MBS's is `AR duy tri`(NOTIFY)/`AR xu ly`(LIQUIDATE)/`Nguong xu ly tai VSDC`, so the positional read in `to_broker_terms` would report its liquidation level (0.95 filled) as a `MARGIN_CALL`. Ten of the eighteen shipped profiles configure a session; the other eight refuse with a stated reason. **NOT mapped:** the profiles' own `initial_margin_ratio` (PLUTUS_DEFAULT 0.1785) — it is an absolute ratio and `margin_buffer` is an add-on above the *dated* VSD rate, so no date-free arithmetic connects them |
| — the profile's **block-opening** rung, honoured at admission | `deposit.py::reserve_for_order`, `types.BrokerProfile.block_opening_utilisation` | IMPLEMENTED + SOURCED (behaviour) | Added 2026-08-27, finding F2. Every surveyed firm's Mức 1 is *"tối đa để được mở vị thế mới"* — a block on **opening** — and `BrokerTerms` can only hold it as `warning_utilisation`, turning a refusal into a notification. Measured: at 0.9314 utilisation, past PLUTUS_DEFAULT's own 0.80 block *and* its 0.90 call, a fifth VN30F2210 contract was **accepted**; it is now rejected with `binding_constraint = 0.80` while an offsetting sell is still admitted (QĐ 26 Điều 13.2.a). `None` for a session with no firm named, so behaviour without a profile is unchanged |
| Intraday margin checkpoints **09h30 / 14h00 / 16h30** | — | **NOT BUILT** | Author decision 4 says MUST HAVE. The times are now primary-sourced (QĐ 26 Điều 13.2), superseding the "09:30 and 14:30" broker figure. `MarginMonitor.on_mark` is driven by whatever instants the caller marks at; there is no checkpoint schedule. Implementation shape unchanged from §16.1: **exchange/depository config keyed by date**, pre-KRX continuous / post-KRX three checkpoints |
| Realised close-out into the deposit, measured from the VM reference | `:1392-1466` | IMPLEMENTED + SOURCED | `[design]` — No Vietnamese rule states it; the design property is that the deposit movement exactly cancels the VM being charged, so no double count is possible |
| Expiry settlement | `:1468`, `exchange.py::_mark_derivatives`, `_expiry_reached`, `_expiry_instant` | PARTIAL | Prefers a published settlement price; falls back to the expiry-day close with `substituted=True` (A56). **A56 names two tiers; there are three** — see the next row. **Timing corrected 2026-08-27:** the trigger was `ts.date() >= expiry`, so under the documented two-advance loop a position was extinguished at **09:30 on its own last trading day**, before the caller's decision point. A roll submitted that morning found nothing to close and its offsetting order was admitted as a **new naked position in a contract that had already cash-settled**, which then settled a second time at 14:45 for a cash flow of `-0.0`. `_expiry_reached` now tests the venue's own `session_close` (HNXDS 14:45), falling back to the date when the schedule is unresolvable, and `_expiry_instant` pins the price read to the expiry **date** whatever instant the advance noticed it at — the latter matters because an advance that first crossed the expiry on a later date read that later date's row, found none, and silently downgraded a settlement to INDETERMINATE. Pinned by `tests/validation/test_expiry-overnight.py::test_the_expiring_contract_is_still_tradable_on_its_last_trading_day` and `::test_each_contract_settles_exactly_once` |
| **`SettlementResolver` — the three-tier settlement chain** | `expiry.py:1-18`, `:58`, `:78`, `:92`, `:106`; `verdicts.py:51-56` | PARTIAL | (1) `PUBLISHED` — real `quote_settlementprice` rows, with corrupt rows excluded (`price < 100000`, because their price is the HHMMSS of their own timestamp); (2) **`TWAP_30M`** — time-weighted mean of matched price 14:15–14:45, recovered empirically at a mean error of **0.74 index points**, and it **requires the raw tick archive**; (3) `CLOSE_PROXY` — `quote_close`, the only tier on Parquet. Carries a sourced **negative** finding: `quote_reference` is deliberately excluded because it equals the previous close on **1,731 of 1,968** VN30F pairs. **The session cannot distinguish an adapter-computed TWAP from a published row** (`exchange.py:2447` says so), and every expiry settles on `CLOSE_PROXY` without the archive |
| **`Exchange.sustains()` — half the `Exchange` ABC contract** — `Viability`, `PositionEvent`, 5 `PositionEventKind` members | `exchanges/base.py:41-56`, `exchanges/derivatives.py:96-228`, `verdicts.py:59-64`, `:110-125`, `:127-147` | DEFERRED | `base.py:18` calls the admits/sustains asymmetry "the central empirical finding, visible here in the architecture". `sustains()` walks a position along a price path and reports `MARGIN_CALL`, `FORCED_LIQUIDATION`, `EXIT_BLOCKED`, `POSITION_LIMIT_EXCEEDED`, `EXPIRY_SETTLEMENT`. **Same adjudication as `margin.py`** — legacy batch path, tests a maintenance ratio that does not exist, retained because published figures were computed on it; the base implementation reports unconditional survival for equities. All four types are in `plutus.market.__all__` |
| — **`EXIT_BLOCKED`**: the exchange refuses a stop-loss exit because the band is locked against it | `derivatives.py:194-198`, `:209-219` | DEFERRED | A long exits by selling, so a locked **floor** blocks it; a short by buying, so a locked **ceiling** blocks it. **This is the only band-lock-blocks-exit model in the repo** — the session path has no equivalent, and a session asking "do we model a trader trapped by a floor lock?" must be told: only here, only in the legacy batch path |
| Forced liquidation | `exchange.py:2326-2404` | PARTIAL | **Reports only.** `FORCED_LIQUIDATION` carries `detail['executed'] = False`, the selection rule and the sequence. Nothing is closed |
| `LARGEST_LOSS_FIRST` ordering | `deposit.py:1580` | IMPLEMENTED + ASSUMED | A54. `PRO_RATA` raises `NotImplementedError` — it is an allocation, not an ordering |
| Daily settlement rebaseline (`settle_daily`) | `:1190-1217` | PARTIAL | Exists and is tested, but **no session path calls it** — see D1 |
| Cross-contract spread credit / portfolio margining | — | DEFERRED | **The reason has changed: the formula is no longer unobtainable.** Phụ lục 2 §2 gives it in full — `OA = (B + S) × C × Psr`, over underlying-asset groups formed on Kendall-tau ≥ 0.9 across ≥ 3 years. It is **correctly zero on our corpus anyway**: there is exactly one derivatives underlying in it, so no group can form. Strict per-contract sum over-charges, never under-charges |
| Post-KRX margin model | `rulebook.py:1403` | DEFERRED | `margin_model()` **raises** rather than extending the pre-KRX shape. The refusal is still right and is now better justified: the post-KRX shape is not an extension of the pre-KRX one, it is a different assembly |
| **Post-KRX scenario margin** — `Rm` (21-scenario grid), `Sm` (basis), `Dm` (delivery), `MM` (minimum), and the `MR = Max(Σ Pgm, 0)` assembly | `session/scenario_margin.py` (2,989 lines) | IMPLEMENTED + SOURCED, **and wired 2026-08-27** | Spec: **`docs/reference/post-krx-margin-spec.md`**, read out of QĐ 26 Phụ lục 2 (§1–§6) with every formula quoted verbatim. **Status corrected 2026-08-27.** This row read NOT BUILT long after the module landed, and then read *built but unreachable*: `scenario_margin.py` had **zero call sites anywhere in `src/` or `validation/`**, 1,069 of 1,069 executable lines never executed under any scenario, and `indeterminate_report()` answered `indeterminate=0` throughout — a layer nobody calls has no evaluation to be undecided about. It is now reached through `session/overnight.py` from `ExchangeSession._overnight_margin`; see the next row. `Rm` and the MR assembly run on the corpus today. What is *not* implementable: **`Sm`** — `quote_settlementprice` holds 18 distinct dates of intraday tick samples, not a daily DSP series, so it is the wrong shape and not merely short; **`Dm`** — fails on every input independently, and GB futures are out of scope by decision 3. **The two "missing" formulas were recovered** and the claim withdrawn: both are Word `<m:oMath>` objects that every text extractor this project has used silently drops — §1.3.c says `Tỷ lệ IM = VaR × √n`, and QĐ 26 Điều 8.1's collateral valuation is `VKQ = C + min((1 − x) × MR ; Σ QKQ × P × (100 % − H))`. What survives as a real defect in the signed instrument is the scenario table printing `Sk = S0 × (1 + rate/10)` with **no `k` on the right-hand side** in all 21 rows, which is why `RiskMargin.is_reconstructed_grid` is always `True` and says so |
| **THE OVERNIGHT MARGIN LAYER — the CCP requirement an account carries past the close** | `session/overnight.py` (new), `exchange.py::_overnight_margin`, `::_overnight_model`, `::overnight_margin()`, `::overnight_margins()` | IMPLEMENTED + SOURCED (assembly) / ASSUMED (three inputs, each declared on the result) | **Added 2026-08-27, and it is the biggest gap the fidelity audit found.** Survey finding F-1: the margin model is chosen **per layer**, not per profile. The **intraday** ladder stays `deposit.py`'s `MR = IM + resting + VM` on the futures traded price, untouched. The **overnight** requirement is computed **once per session after the venue's own close** (QĐ 26 Điều 5.5, *"sau khi kết thúc phiên giao dịch"*) from the end-of-day book and the **underlying's** close. Which model serves it is decided in two steps: the **dated rulebook** first — `RuleName.MARGIN_MODEL` records `'pre_margin'` to 2025-05-04 at HIGH confidence, one continuously-recomputed mechanism with **no separate end-of-day model**, so in that regime the overnight requirement is the continuous one on the held book (no resting-order margin: the day's orders are gone) — and only past the cutover, where the rulebook refuses, does the **broker profile**'s `margin_model_overnight` decide. Running QĐ 26's grid on a 2022 account would report a number under a regulation that did not exist. **An account flat at the close gets a determinate zero with `flat=True`, which is a different fact from `amount is None`.** Measured: `deriv-margin` produces 19 requirements over 19 sessions, the last (the expiry) a real zero; post-KRX under SSI with the index served, **60,044,000đ overnight against 109,844,000đ intraday** on one 2-lot position. `overnight.py` is pure — one AST test pins stdlib-plus-two imports and no float literal, the same rule `scenario_margin.py` enforces on itself |
| — where a parameter is unavailable it is **INDETERMINATE and counted**, never the intraday number | `overnight.py::OvernightGap`, `exchange.py::Blindness.OVERNIGHT_UNCOMPUTED` | IMPLEMENTED + SOURCED | Nine named gaps, one per **input** rather than per symptom, because the remedies differ: `margin_model_overnight.unstated` (no firm named, or a firm that publishes a ladder and no formula), `vsdc_parameters.absent` (PLUTUS_DEFAULT carries no mirror and `parameters_for` refuses to borrow SSI's), `vsdc_parameters.not_yet_effective` (SSI's mirror is dated 2026-01-16 and will not margin a 2025-06 position), `vsdc_parameters.underlying_row`, `contract.underlying`, `underlying_close` (Phụ lục 2 §1.1's `S` is the **index level**; the futures price differs by the basis, which §3's `Sm` charges for separately, so it is not substituted), `average_price` (§2.2.b's window is SILENT), `delivery_margin.deferred` (a GB future refuses outright), `intraday.indeterminate`. Every gap moves `indeterminate` **and** writes `margin.overnight.uncomputed.<gap>` into `silent_ignorance`, because the scalar cannot say which input to go and get. Gaps are collected **all at once**, not one per run |
| — three assumptions of ours, and one of them is **permissive** | `overnight.py::OvernightAssumption` | IMPLEMENTED + ASSUMED | `no_published_grouping` — nobody publishes VSDC's underlying-asset groups, so every underlying is a singleton with `OA = 0`; **restrictive** (measured: 78,200,000đ ungrouped against 14,668,983đ with the offset), and recorded only on a book holding two or more underlyings because on one product the relief is zero **by the rule** (Điều 5.1.1.a). `minimum_margin_factor_derived` — `ContractLeg` takes `R` and no firm publishes one, so `R = MF / (M × St)` is inverted out of the profile's published `MF` (5,000đ, S-11 + TCBS verbatim) at raised precision so the round trip returns exactly `MF`; **lower bound**, S-11's one-tick book. `variation_margin_unsettled` — **the permissive one.** Phụ lục 2 §6.2 has no `VM` term because Điều 20 settles position P&L as a separate T+1 cash movement, and `settle_daily` has no session call site (**D1**), so a grid number quoted against a loss-carrying account under-states what it owes by exactly that loss — **49,800,000đ** in the measured case. Raised on every grid result computed over a non-zero `VM` |
| Securities as margin collateral | — | DEFERRED | Author decision 2 — cash only for the MVP. **The haircuts are now primary-sourced** and no longer UNVERIFIED: QĐ 26 **Điều 9**, in the body and not an appendix — **5 %** government and government-guaranteed bonds, **30 %** VN30/HNX30 constituents, **40 %** everything else, changeable by VSDC on **01 working day's** notice. Eligibility is Điều 6 (ETF units excluded); the list and its haircuts are republished every 6 months. **What is still missing is the arithmetic, not the rate:** Điều 8.1's valuation formula did not survive extraction — the variable list is there (`VKQ`, `C`, `MR`, `x = 80 %` minimum cash margin ratio, `QKQ`, `P`, `H`) and the equation is not, so the 80 % is confirmed as *a rate named "tỷ lệ ký quỹ bằng tiền tối thiểu"* and **not** confirmed as "80 % of MR" |
| Government bond futures as a product | — | DEFERRED | Author decision 3. The multiplier exists and is sourced; the product is out of scope |
| Legacy `margin.py` per-position model | `margin.py:249` | DEFERRED | Wrong shape (per-position, symmetric, requirement frozen at entry) and models a non-existent maintenance ratio. Retained only because published figures were computed on it. See `margin-model-adjudication.md` |

---

## 12. Equity margin lending — BUILT and WIRED

**Status corrected 2026-08-27. The "NOT BUILT / verified by grep" claim below was true
when written and is now wrong twice over:** `session/margin_lending.py` (9,273 lines) is the
policy — the two config objects, QĐ 87 Điều 2's algebra, the call and forced-sale state
machine — and `session/equity_margin.py` is the wiring that joins it to `ExchangeSession`.
The only `ký quỹ` that must still not be reused for it is derivatives clearing margin
(`src/plutus/market/margin.py`, `src/plutus/market/session/deposit.py`,
`src/plutus/market/exchanges/derivatives.py`) — a **different product**, different
regulator, different custody chain, different call test.

| Feature | Where | Status | Source / note |
|---|---|---|---|
| The policy: `MarginRegulation` / `BrokerMarginTerms`, Điều 2 algebra, `MarginCallMonitor`, `assess_margin_order`, forced-sale planning and proceeds | `margin_lending.py` | IMPLEMENTED + SOURCED (statutory half) / IMPLEMENTED + ASSUMED (commercial half) | Its own `PROVENANCE` tables grade every field. Nothing in it computes a session |
| **The wiring** — funding a margin buy, the Điều 6.1 determination, executing the *bán giải chấp*, applying proceeds on settlement, interest accrual | `equity_margin.py::EquityMarginAccount` | IMPLEMENTED + ASSUMED | Nine choices in `WIRING_PROVENANCE`, each graded. Attached with `ExchangeSession.attach_equity_margin` or `build(equity_margin=…)` |
| `Order.on_margin` — the distinguishable ticket | `protocol.py:152` | PARTIAL | QĐ 87 Điều 13.5(e) requires the ticket to be **distinguishable**; `assess_margin_order`'s docstring reads that as "must add a type". It is a **flag**, not an `OrderType` member. Declared in `WIRING_PROVENANCE::margin_order_flag` |
| `StatefulRule.MARGIN_LENDING` — the credit refusal, kept apart from `INSUFFICIENT_CASH` | `types.py:552` | IMPLEMENTED + SOURCED | `[design]` — a client refused for buying power has cash and is refused credit; one member for both would make a funding-bound run and a lending-bound run indistinguishable |
| **The forced sale EXECUTES** | `equity_margin.py::_submit_pending` | IMPLEMENTED + ASSUMED | Unlike the derivatives side (`detail['executed'] = False`), the tickets go through `session.submit` and face the band, the tick grid, the lot and the fill policy. Measured on the corpus: HPG 2022-10-31 is floor-locked and the *bán giải chấp* is `Rejected(BAND_LOCK)` — the Điều 8 right exists and cannot be exercised |
| **Proceeds are applied on settlement, not on execution** | `equity_margin.py::_apply_settled_proceeds` | IMPLEMENTED + ASSUMED | Điều 8 is SILENT on timing. `value_to_restore` warns that a sale not applied to the debt moves the ratio by **nothing**; on T+2 that is a two-session hole where a liquidated account is still in breach. Measured: sale 2022-10-25 at 0.3313→0.3445, cured 2022-10-27 at 0.4198 |
| Per-deal (`AccountingUnit.DEAL`), `ForcedSaleScope.BREACHING_POSITION`, `LiquidationOrder.BREACHING_FIRST` | — | NOT BUILT | The wiring **raises at construction** rather than running an account-level ratio and labelling it per-deal |
| Firm-level Điều 9 caps, extensions, overdue-loan liquidation, securities as collateral | `margin_lending.py` (policy exists) | NOT WIRED | `firm=` is opt-in and the wiring never supplies one; no extension is granted; `LOAN_OVERDUE` is reachable only if a run outlives `base_term_days` (90). Author decision 2: securities-as-collateral is future work |

Scenario and assertions: `validation/scenarios/equity-margin.py`,
`tests/validation/test_equity-margin.py` (50 tests, 4 arms over HPG 2022-09-23 → 2022-11-04).

The implementable specification —
rules, dated, cited, graded, with statutory and broker terms separated into two config
objects — is **`docs/reference/equity-margin-spec.md`**. Headline facts so a reader does
not have to open it:

> **`VERIFIED` below is `equity-margin-spec.md`'s own grade, not §2's vocabulary and not
> the exchange rulebook's.** It means the complete operative text was read. **The spec's
> load-bearing caveat travels with this table** (spec §0): *every* VERIFIED grade came
> from a **commercial mirror** — thuvienphapluat.vn, vbpl.vn, vanbanphapluat.co and
> ssc.gov.vn were all unreachable — not from công báo or an SSC PDF. **If a traceability
> claim in the paper depends on a specific clause, obtain the gazette copy.**

| Fact | Value | Source | Confidence |
|---|---|---|---|
| Initial margin ratio floor | **≥ 50 %** | QĐ 87/QĐ-UBCK Điều 5.1 | VERIFIED |
| — ⇒ max loan-to-value 50 % | this restatement **is not in the text** | our arithmetic via `imr = 1 − loan_ratio` (spec §3.1) | **DERIVED.** Điều 5.1 says only *"không được thấp hơn 50 %"*, and khoản 8 defines `imr` on **account** *tài sản thực có* over the order's value — so an account holding other collateral supports a larger purchase than `1 − loan_ratio` implies. The identity holds only for a single fully-collateralised purchase |
| Maintenance margin ratio floor | **≥ 30 %** | QĐ 87 Điều 5.2 | VERIFIED. **Note this is the answer §1 refuses for *derivatives*** — the two products differ |
| Cure window ceiling | **≤ 3 business days** | QĐ 87 Điều 7.1 **alone** | VERIFIED. TT 120 Điều 9.6 carries the call and the force-sale right but **no day count** |
| Loan term | **≤ 3 months**, extensions ≤ 3 months each, count uncapped | QĐ 87 Điều 11.1–11.2 | VERIFIED |
| Foreign investors | **may not margin trade** (*ký quỹ*) | TT 120/2020 Điều 9.2; QĐ 87 Điều 10.1(đ) | VERIFIED |
| — **but see TT 120 Điều 9a** | the **non-prefunded buy regime for foreign institutional investors**, inserted by TT 68/2024, amended by TT 18/2025 and TT 08/2026 | luatvietnam's consolidated TT 120 (fetched and confirmed 2026-08-26; the amendment annotation at the foot of Điều 9 is verbatim) | **ADJACENT, OUT OF SCOPE, and NOT *ký quỹ*.** Recorded because an implementer reading only the row above will build a simulator that refuses **all** foreign credit-funded buying, which is wrong |
| Collateral valuation | **may not exceed the last close** | QĐ 87 Điều 2.4 | VERIFIED |
| Ratio determination | **end of day** (brokers run it intraday — a broker option) | QĐ 87 Điều 6.1 | VERIFIED |
| Firm limits | book ≤ 200 % equity · one client ≤ 3 % · one security ≤ 10 % · one issuer ≤ 5 % of that issuer's listed shares | QĐ 87 Điều 9.1–9.4 | VERIFIED |
| Liquidation order and proceeds-application order | **the rulebook is silent** — delegated to the broker contract | QĐ 87 Điều 12.2.i | VERIFIED (that it delegates) |
| Interest **rate**, and the only cap | **no statutory rate; the Civil Code's general ceiling is the only limit** | QĐ 87 Điều **11.3** — *"Lãi suất cho vay … theo quy định của Bộ Luật Dân sự"* (re-fetched verbatim 2026-08-26) | VERIFIED |
| Interest **calculation method**, day-count, compounding | **delegated entirely to written agreement** | QĐ 87 Điều **11.4** — *"Cách tính tiền lãi vay được xác định trên cơ sở thỏa thuận bằng văn bản"* | VERIFIED |
| **Call / force-sell threshold values at any broker** | **none verified** | — | **NOT AVAILABLE.** The one published ladder (DNSE) is a *giao dịch tiền mặt* cash-product table, not a margin ladder — see spec §3.2 and §5 gap 5 |

---

## 13. Session API

`session/exchange.py` (3,866 lines). `ExchangeSession`, aliased `Session`.

| Feature | Where | Status | Source / note |
|---|---|---|---|
| `submit` / `cancel` / `amend` / `orders` / `poll` | `:811`, `:909`, `:938`, `:986`, `:998` | PARTIAL | `amend` is decrease-only (§6). `cancel` on an unknown id raises `KeyError`, not `Rejected` |
| `advance_to(ts)` — monotone clock, fixed internal order | `:750` | IMPLEMENTED + SOURCED | `[design]` — no Vietnamese document orders a simulator's internal passes. Ours: expire → fill → decide immediates → settle → accrue → mark derivatives → **overnight margin** → equity margin → drain. The overnight step runs **after** the mark and after expiry settlement, and the order is load-bearing: a contract that cash-settled today is not carried past tonight's close, so the end-of-day book has to be the post-expiry one |
| `holdings` / `cash` / `positions` / `margin` / `charges` | `:1018-1058` | IMPLEMENTED + SOURCED | `[design]` — a scope decision, not a market rule. Read models only. No P&L, no portfolio — that is the caller's |
| `transfer(source, destination, amount)` | `:1074` | PARTIAL | Arrival immediate (A55). Refusals are counted but **emit no event** |
| **Equity margin lending hooks** — `attach_equity_margin`, `securities_cash_ledger`, `_margin_gate`, `_run_equity_margin`, `build(equity_margin=…)` | `exchange.py::attach_equity_margin`, `::_margin_gate`, `::_run_equity_margin` | IMPLEMENTED + ASSUMED | §12. Four seams, and no more: the gate runs **after** `admits()` and **before** the reservation (an order off the tick grid is a tick-grid rejection whether or not the client could borrow); `_run_equity_margin` runs **after** `_settle` and `_mark_derivatives`, because `CB` includes settled cash and a tranche settling this instant must be in it before the account is graded. A session with **no** equity margin account **refuses** an `on_margin` order rather than treating it as a cash buy |
| `provenance()` — rulebook id, fill-policy signature, pins, calendar id, liquidation rule | `:1123` | IMPLEMENTED + SOURCED | `[design]`. Pins are always reported, so a counterfactual run self-declares |
| `indeterminate_report()` — evaluations, by field, by rule, **plus `silent_ignorance` / `exercised` / `unexercised`** | `exchange.py::indeterminate_report`, `::RunIgnorance` | PARTIAL | `evaluations` mixes **four** populations under one denominator — fill decisions, derivatives marks, unpriced expiries and **overnight requirements** — so the rate moves with the caller's sampling rate; `by_rule` counts **only INDETERMINATE** rejections. **`indeterminate == 0` is not the honest predicate and never was**: it answered zero on every failure the fidelity audit found. Read `is_clean`, which is `indeterminate == 0 and silent_total == 0 and not unexercised`. `silent_ignorance` counts acts taken without a fact (a fill decided without the day's extremes, a cap the running policy could not honour, an order the loop never routed, an unsourced size cap or margin mechanism, an overnight layer refused or assumed); `exercised`/`unexercised` count **which session seams actually ran**, which is the failure mode a margin layer with no call site had |
| 12 `EventKind` members, all reachable; monotone `seq`; destructive single-consumer cursor | `types.py:779`, `exchange.py:998` | PARTIAL | No `RESTING` event and no margin-**clearance** event, both deliberate. Amend, cancel and transfer refusals **never reach the cursor** |
| Multi-venue in one session; `pool_for_venue` segregation | `:503`, `types.py:180`, `AccountRef` at `types.py:1663-1699` | IMPLEMENTED + SOURCED | Segregation itself is rulebook 6.3, HIGH. **`AccountRef` is the object that *carries* it** — `venue_scope: FrozenSet[Venue]` and `serves(venue)` (`:1697-1699`) — so the sell path can ask which pool an instrument belongs to rather than re-deriving it. The two-leg HSX + VN30F case is pinned by a **test**, which is not a source |
| `to_dict()` — a JSON surface on every verdict and event | `verdicts.py:105`, `:122`, `:135`; `types.py:1799`, `:1902` | IMPLEMENTED + SOURCED | `[design]` — `Admissibility`, `PositionEvent`, `Viability`, `Rejected`, `Event` all serialise, with enums and temporals reduced by `_plain` → `json_safe`. This is what a caller logging rejections should use |
| **Three documented subsystems are not on the package's public API** | `session/__init__.py:103-146` | PARTIAL | `hasattr(plutus.market.session, …)` is **False** for `CorporateActionEngine`, `CorporateAction`, `CorporateActionAudit`, `CommissionSchedule`, `assess_daily`, `assess_at_maturity`, `DailyTurnover`, `ChargeContext`, `LeviedCharge`, `ProbabilisticFillPolicy`, `compare_policies`, `probabilistic_sweep`, `DivergenceReport`, `FillQuestion`, `SettlementResolver`, `ChargeBasis`. **Import them from the submodule**, e.g. `from plutus.market.session.fills import ProbabilisticFillPolicy`. (`build_fill_policy` **is** exported) |
| `from_config` / `from_mapping` / `build` | `:534`, `:558`, `:572` | PARTIAL | `build` wires `on_terminal` for **both** pools; a hand-assembled book that omits it leaks reservations |
| `load_data_source` from a dotted config path | `:390` | NOT BUILT (broken) | **Neither shipped adapter can be constructed from a config**, and the `DataHubSource` case fails *silently* at construction. No test covers it |
| `source=None` "admission-only study" | `:394-399` | NOT BUILT (broken) | Admits **zero** orders — but at **gate 0, not gate 7**. On the ship default (`source=None, listings=()`) `SymbolRouter.venue()` (`rulebook.py:2585`) cannot classify the ticker, so `submit()` returns `Rejected(SESSION_SEMANTICS, INDETERMINATE)` with `reason="no venue for 'FPT' … no dated listing, not a futures code, and no data source"` and the fabricated state at `exchange.py:1516-1529` is never reached. `BAND_LIMIT`/INDETERMINATE is what you get **only after** supplying `listings=` — both cases re-run and confirmed |
| Event-driven callbacks | — | DEFERRED | §16. Synchronous is simpler to test and reason about |
| Immediate families decided **one interval late** | `:2217` | PARTIAL | Declared Tier-1 deviation — `submit()` is synchronous with no matching engine behind it |

---

## 14. Data contract and adapters

`market/adapters/` (701 lines). Protocol has three methods; the session uses two -- **plus the optional `IntervalSource` seam**, which `DataHubSource` implements as of 2026-08-27 and `TickSource` does not.

| Feature | Where | Status | Source / note |
|---|---|---|---|
| `MarketDataSource` protocol — `state_at`, `states`, `instrument` | `adapters/base.py:17` | PARTIAL | `states()` has **zero session callers** — dead surface from the session's point of view |
| `DataHubSource` — daily, DuckDB/Parquet, **and now an `IntervalSource`** | `datahub.py::DataHubSource`, `::interval` | PARTIAL | Only `for_root(data_root)` constructs correctly from a string. `state_at` returns the **first** row of the day, ignoring the time. **Added 2026-08-27:** `interval()` serves `quote_dailyvolume` by LEFT JOIN alongside close/ceiling/floor/reference, and the interval's `MarketState` comes from the *same* `_build_state` as `state_at`, so admission and fills cannot disagree about the band, lock or phase. The contract is class data — `SERVES` / `WITHHELD` — and `WITHHELD` is stamped into `interval.missing` on **every** bar, plus `VOLUME` per bar where the corpus has no row. **Nothing defaults to zero**: an absent row is our ignorance, a zero would be a market fact, and there are zero `quantity = 0` rows in the table at any date. Non-daily resolution or a multi-day span **raises** rather than attributing a day's liquidity to a shorter window. **Coverage, measured 2021-01-01..2022-12-31: 523,619 of 832,752 ticker-days carrying a close also carry a volume row (62.9 %)** — the gap is concentrated in instruments with no volume to publish (every index is 0/499) and every liquid name checked (ACB, FPT, HPG, MWG, SSI, VIC, VN30F2211/2212, E1VFVN30) is 499/499. `quote_open`, `quote_max` and `quote_min` are still **withheld**, deliberately: wiring the extremes moves decisions in *both* directions and deserves its own measurement |
| `TickSource` — tick, 3-level book ladder | `tick.py:40` | PARTIAL | `MAX_DEPTH = 3`; **`BookLevel.size` is always `None`** — the size tables are 0-row on every corpus. `DataField.BOOK_SIZE` exists to name exactly this |
| Band reconstruction when the reader is absent | `datahub.py:52` | IMPLEMENTED + ASSUMED | A67. Labelled `RECONSTRUCTED`, never `PUBLISHED` |
| Lock inference | `datahub.py:190`, `tick.py:140` | PARTIAL | `BAR_PROXY` from the daily bar is **labelled an inference, not an observation**; `TICK_BOOK` from the ladder is authoritative. Overclaim: `tick.py:157` returns `TICK_BOOK` "not locked" when the band it would test against is `None` |
| `MarketInterval` synthesis when no `IntervalSource` exists | `exchange.py::_interval_for` | PARTIAL | Volume, open, high, low, book and settlement price are always `None`, so `hard` is INDETERMINATE wherever it would fill and every expiry settles on `CLOSE_PROXY`. **Scope this to sources that are not `IntervalSource`** — `DataHubSource` now is one (next row) |
| Session phase from data | `datahub.py:210`, `tick.py:109` | NOT BUILT | Both adapters **hardcode `CONTINUOUS`** (A40). **Scope this claim to the adapters** — it is accurate about them, and it does *not* mean ATO/ATC/PLO are unreachable: on any non-daily resolution `exchange.py:1279-1300` takes the phase from `RuleSet.phase` and the adapter is only the `UNKNOWN` fallback. Executed at tick resolution: 09:05 HSX `opening_auction` / HNX `continuous`; 12:00 both `noon_break`; 14:35 both `closing_auction`; 14:50 HSX `post_close` / HNX `post_close_plo`; Saturday → `post_close` |
| `instrument()` — the classification chain | `datahub.py:218-286` | PARTIAL | Futures prefix (`^(VN30F\|VN100F\|GB\d)`) → CW/ETF predicate → ticker master → `UNKNOWN`. **Two declared limits:** the ticker master carries **no `future` type and no HNXDS rows at all**, and it stores only the **latest** exchange assignment, so `exchange_code` is unreliable historically — which is exactly why `SymbolRouter` overwrites every dated field |
| Intraday `[start, end)` widened to whole days | `datahub.py:163`, `tick.py:82` | PARTIAL | Silent in both adapters |

---

## 15. Calendars

| Feature | Where | Status | Source / note |
|---|---|---|---|
| `VsdcSettlementCalendar` — dates are a **caller-supplied data input**, no hardcoded holidays | `calendar.py:140` | IMPLEMENTED + SOURCED | Reproduces the rulebook's Announcement 4228/TB-VSDC Tết-2026 worked example. Queries outside coverage **raise** |
| `VnTradingCalendar` — a deliberately different object | `calendar.py:560`, `:720-743` | IMPLEMENTED + SOURCED (when given rules) / ASSUMED (fallback) | A66 — it **prefers** `rules.session_open` / `rules.session_close` and only falls back to the undated `core/constant.py` map when the caller passes no `RuleSet`. Both instants the session stamps (DAY-order expiry, a call's `cure_by`) pass real rules |
| Shipped calendar **data** | — | NOT BUILT | A64. `find . -name "*.json"` returns only an MCP config and a test fixture |
| Dated `SESSION_SCHEDULE` in the rulebook | `rulebook.py:990` | PARTIAL | Resolvable and cited, and **`RuleSet.phase` reads it** (`:2148`). The adapter wins **only on `Resolution.DAILY`** (`exchange.py:1279-1300`), where both adapters say CONTINUOUS; on a daily run a non-trading day resolves `POST_CLOSE` and `equity.py:183-185` refuses it with `SESSION_SEMANTICS`, so the trading calendar gates admission |

---

## 16. DEFERRED / FUTURE WORK

### 16.1 Author decisions, 2026-08-26 — recorded verbatim

> 1. **Equity margin lending is PRIORITY 1.** Not built at all today. Must be built.
> 2. **Securities as margin collateral: CASH ONLY for the MVP.** Note clearly as future work.
> 3. **Government bond futures: ALL bond features are FUTURE WORK.** Very few users of this
>    repo will touch bonds. Note clearly. (The GB contract multiplier was fixed recently --
>    record that it exists but that the bond product as a whole is out of scope for now.)
> 4. **Intraday margin checkpoints: MUST HAVE.** Check the policy very carefully before
>    implementing -- times, what is checked, and whether the KRX cutover changed them.
> 5. **Cure window: default to next session** (our default, stated in the implementation).
>    Making it user-configurable is future work.

**What each decision means for the code.**

**Decision 1 — equity margin lending.** Greenfield; see §12 and
`docs/reference/equity-margin-spec.md`. Two config objects, `MarginRegulation` (gazetted,
dated, not user-configurable) and `BrokerMarginTerms` (commercial, per-firm, assumed).
Do not reuse `deposit.py` — derivatives clearing margin is a different product with a
different regulator, a different custody chain and a different call test.

**Decision 2 — cash-only collateral (A57).** Already how `deposit.py` behaves: assets are
`deposit_balance` alone. Future work is the securities leg: the eligible-collateral list,
the VSDC haircuts, and the ≥80 % minimum cash share. For equity margin lending the
analogue is the per-ticker `loan_ratio` haircut.

> **Resolved 2026-08-26 — QĐ 26 obtained and read.** The audit box that stood here asked
> for the document before believing the haircuts. The document is now in hand and the
> percentages are **VERIFIED**, not merely reported: QĐ 26 **Điều 9.1** — 5 % government
> and government-guaranteed bonds, 30 % VN30/HNX30 constituents, 40 % all other
> securities, with Điều 9.2 letting VSDC change them on **01 working day's** written
> notice. The **structural** claim the audit correctly identified as load-bearing is also
> confirmed: they are in the **body**, at an article, not in an unpublished appendix — so
> rulebook §6.3:600's `UNVERIFIED` row (*"Valuation percentages … are in rulebook
> appendices VSDC does not publish"*) is **overturned for post-KRX**. It stands for
> pre-KRX, where QĐ 61 and QĐ 12 remain unread.
>
> **One half of the old text did NOT survive and has been deleted.** It claimed "post-KRX
> TT 58 Điều 13.4 and QĐ 26 Điều 8 make it **80 % of MR**". QĐ 26 Điều 8.1 defines
> `x = tỷ lệ ký quỹ bằng tiền tối thiểu (80 %)` in its variable list and then **the
> equation itself does not survive extraction** — the line reads *"Giá trị tài sản ký quỹ
> hợp lệ được xác định theo công thức sau:"* followed directly by *"Trong đó:"*. So the
> rate is confirmed and its **denominator is not**. The variable list contains `MR`, which
> is consistent with "80 % of MR" and does not establish it. Do not restate the
> denominator as sourced.

**Decision 3 — government bond futures out of scope.** What exists and stays: the
multipliers `GB05 = GB10 = 10,000` (rulebook 4.1, HIGH, corroborated arithmetically —
a 1 tỷ đồng contract quoted per 100,000đ face is 10,000 faces), the ±3 % band, position
limits 0 / 5,000 / 10,000, and the `_unsourced` IM row that **raises** rather than
applying the index ratio. What is out of scope: delivery margin (no published ratio was
located at any date), the physical-delivery leg, the 4,500 VND exchange fee that
`ChargeRule` cannot express, the GB expiry calendar (`expiry.py` matches `VN30F` only, so
a GB position **never expires**), and the professional-individual position tier of 3,000
that `InvestorClass` cannot represent. Also: GB futures are unreachable end-to-end today
because every session runs `InvestorClass.INDIVIDUAL`, whose GB cap is 0.

**Decision 4 — intraday margin checkpoints. Answering the policy question before building.**
The cutover **did** change them, and the value currently in our rulebook is wrong.

> **The caveat that stood here is DISCHARGED, 2026-08-26.** It read: *"Everything in this
> sub-section rests on VSDC QĐ 26/QĐ-HĐTV (2025-04-16), which our own rulebook grades
> `medium (never read)` … no copy of QĐ 26 exists in this repository, so nothing here can
> be corroborated or refuted … obtain QĐ 26 first."* **QĐ 26 and its Phụ lục 2 have now
> been obtained and read in full.** Every article-level reading below has been checked
> against the primary text; six of the seven corrections are confirmed, one is refuted,
> and the grades are restated accordingly. The one thing that did **not** survive
> unchanged is row 5. Provenance of the copy: thuvienphapluat.vn is Cloudflare-blocked to
> automated fetching, so the documents came from the author directly.

| | Pre-KRX (2022-06-01 → 2025-05-04, QĐ 61 → QĐ 12) | Post-KRX (2025-05-05 →, QĐ 26) |
|---|---|---|
| Who computes | VSD, **in-session, in real time** | VSDC, **after the close** — Điều 5.5, *"tính toán sau khi kết thúc phiên giao dịch"* |
| What is tested | `utilisation = MR / valid margin assets` against **80 / 90 / 100** — **UNVERIFIED, see below** | **Binary**: `assets < MR` (Điều 13.1). No percentage appears in Điều 13. 80/90/100 survives at Điều 29, **on position limits** |
| Checkpoints | none fixed — continuous monitoring | **09h30** (suspend newly violating accounts; no new positions, offsetting only) · **14h00** (restore those now compliant) · **≤ 16h30** (recompute MR and assets; restore) — Điều 13.2.a/b/c |
| Top-up deadline | intraday, at the member's demand | member must top up **before 09h30 on T+1** after the ≤16h30 T notice — Điều 13.1 |
| Member cure | 3 business days at margin level 3; ~~5 business days at position-limit level 3~~ | **03 working days for both** — Điều 13.3.b (margin) and Điều 29.5 (position limit), same window, same substitute-clearing-member mechanism |

> **Do not read the pre-KRX column as verified.** QĐ 61 and QĐ 12 have **never been read**.
> The 80/90/100 margin ladder in that column is **UNVERIFIED, not disproven** — QĐ 26
> removing a ladder that QĐ 61 had is entirely consistent with everything now in hand, and
> so is QĐ 61 never having had one. Nobody has checked. The citation chain broke at its
> last link; it has not been shown to be false at the others.

Corrections to `docs/reference/vn-exchange-rulebook-2020-2026.md` §6.3 that this
establishes. **The rulebook was updated on 2026-08-26 and its §9.6 logs the same
corrections**; the grades below are restated against the primary text:

| # | Row it overturns | That row's grade | Verdict against the primary text |
|---|---|---|---|
| 1 | rulebook:596 intraday checkpoints "09:30 and 14:30" | `low` (Pinetree) | **CONFIRMED and extended.** Điều 13.2 gives **09h30 / 14h00 / 16h30** — three, not two, and 14h00 not 14h30 |
| 2 | rulebook:597 "Freeze and restore … kind: broker term" | `low` | **CONFIRMED.** Điều 13.2.a/b is a depository rule: VSDC wires HNX to suspend, then to restore |
| 3 | rulebook:595 "no post-KRX IM percentage published … Pinetree explicitly confirms" | ungraded prose | **REFUTED by the primary text**, which is stronger than the internal argument that stood here. Điều 5.1.1.b **requires** VSDC to compute the ratio, re-determine it on the 1st / 10th / 20th of each month, and publish it on its website **≥ 02 working days before it applies** |
| 4 | rulebook:593 "Post-margin model (COMS)" | `medium` | **CONFIRMED on both halves.** Điều 10.1.a keeps cash at NHTT in an account in VSDC's name; Điều 5.5 computes MR after the close. Điều 5 names the four Vietnamese components (ký quỹ rủi ro / song hành / chuyển giao / tối thiểu) and no "COMS formula" |
| 5 | rulebook:592 the "3 vs 5 business day" CONFLICT | `low` | **PARTLY REFUTED — the one correction that did not survive.** The reconciliation's *shape* was right (both are member-to-VSDC deadlines, neither is an investor cure window), but the **numbers are not 3 and 5**: QĐ 26 gives **03 working days for both** paths (Điều 13.3.b, Điều 29.5). The 5-day figure came from a LuatVietnam summary of the superseded edition and has no post-KRX counterpart |
| 6 | rulebook:588 "at 90 % warns positions will be closed" | **`high`** | **CONFIRMED, and more strongly than claimed.** It is not that Điều 13 makes 90 % a mere notice — **Điều 13 has no percentages at all**. What levels 1 and 2 describe is Điều 29's position-limit ladder, where 29.2 makes them notices to the clearing member |
| 7 | rulebook:579 "(c) other factors VSD considers necessary" | **`high`** | **CONFIRMED with a qualification.** Điều 5.1.1 gives the risk margin **two** inputs — tỷ lệ ký quỹ ban đầu and giá trị giảm trừ ký quỹ — so "two, not three" holds. But Điều 5.1.1.b does reserve a discretion: *"Trường hợp cần thiết, VSDC có quyền đánh giá lại tỷ lệ ký quỹ ban đầu căn cứ vào biến động thực tế của thị trường"*, effective the working day after publication. That is discretion over **the ratio**, not a third input to the computation. Do not restate it as absent |

**Obtained since, and what it changed.** **Phụ lục 2 of QĐ 26** — previously described
here as "still unobtainable … the highest-value remaining document in the derivatives
domain" — was obtained on 2026-08-26 and read in full. It gives the scenario set and the
formulas for risk margin, the margin offset, spread margin, minimum margin and the MR
assembly. The reading is `docs/reference/post-krx-margin-spec.md`; the consequence for
this inventory is a new **NOT BUILT** row in §11, not a build.

**Still missing, and now precisely bounded:**

1. **QĐ 26 Điều 8.1's collateral-valuation equation.** The variable list survives (`VKQ`,
   `C`, `MR`, `x = 80 %`, `QKQ`, `P`, `H`); the formula line does not. So the haircut has
   a confirmed *rate* (Điều 9) and an unconfirmed *application*.
2. **Phụ lục 2 §1.3.c's initial-margin-ratio expression.** The heading is there, `n` is
   defined, and the formula is absent — so `VaR = mean + 3δ` is computable and the ratio
   it feeds is not. **Nobody guessed √n.**
3. **Điều 7.3's bond conversion factors** — same failure mode, GB-only, out of scope by
   decision 3.
4. **QĐ 61/QĐ-VSD and QĐ 12/QĐ-HĐTV**, still never read. This is now the highest-value
   gap in the domain, because the pre-KRX regime is what the code actually implements and
   what every corpus date falls in.
5. The whole 2020-01-01 → 2022-05-31 regime (QĐ 96/QĐ-VSD, ~40 % of the window, never
   read — **do not use the stale VSDC web page as a proxy for it**, it demonstrably
   differs from QĐ 61 in at least two places).
6. Any published GB delivery-margin *ratio* at any date. Note the *formulas* for `Dm` are
   now in hand (Phụ lục 2 §4); it is the inputs that are missing.

**Implementation shape when this is built:** unchanged, and now confirmed by the primary
text. The checkpoint times are **exchange/depository config keyed by date**, not broker
terms; the pre-KRX branch is a continuous test and the post-KRX branch is a
three-checkpoint schedule at **09h30 / 14h00 / 16h30**; and the two branches must both
exist because the rulebook edition switches at 2025-05-05. What the primary text adds is
that the post-KRX checkpoints are not merely times to re-test at — each does a *different*
thing (suspend new violators / restore the cured / recompute), so a single "re-mark at
these three instants" loop does not express Điều 13.2.

**Decision 5 — cure window defaults to next session (A5).** Already the implementation:
`BrokerTerms.cure_window_sessions = CureWindow.NEXT_SESSION = 1`, advanced through
`TradingCalendar.next_session_open`, i.e. **sessions, not settlement business days** (the
two diverge around Tết). Stated as an assumption in `BrokerTerms.PROVENANCE`.

> **Re-scoped 2026-08-26. The default is unchanged; what changed is what it is a default
> *for*.** The old text called the cure window a broker term full stop. It is **partly
> regulated**, and the regulated half is now primary-sourced to QĐ 26 Điều 13: MR wired to
> the member by **16h30**; top-up due **before 09h30 the next trading day**; **03 working
> days** from the wire before VSDC directs *another clearing member* to place the
> offsetting trades (Điều 13.3.b — and Điều 29.5 for a position-limit breach, the same
> window). All three run **clearing member ↔ VSDC**. None is a broker's deadline to a
> retail client, and nothing anyone on this project has read sets that one — so `A5`
> stays an assumption and the number stays in `BrokerTerms`, not in the dated rulebook.
>
> One corroboration worth having, and it is *not* a source: HNXDS opens at **08:45**, so
> the default `NEXT_SESSION` deadline lands 45 minutes **inside** the regulated 09h30 T+1
> top-up. A broker term may be tighter than the rule it sits under; it may not be looser.

**It is already user-configurable — an earlier revision of this paragraph was wrong.**
`BrokerProfile.from_config` (`types.py:2449-2484`) accepts `margin_cure_window` as either
the string form (`_CURE_WINDOWS` at `:2422`, `'same_session'` / `'next_session'`) or an
integer session count, **raises** `ValueError` on an unknown string rather than
defaulting, documents both forms in its own docstring (`:2452-2456`), and lists the key in
`BROKER_CONFIG_KEYS` (`:2412`). The three utilisation levels are configurable through the
same method (`:2476-2479`). **The only thing genuinely outstanding is the broker survey**
that would replace the assumed default — see §16.2.

### 16.2 Standing deferrals, with the reason each was recorded

| Item | Reason recorded | Where the reason lives |
|---|---|---|
| **The live Calibrator** | Deferred at design time; validation is how the paper shows §5–§8 are correct, not a shipped deliverable | design §13, §14 |
| **Post-KRX rulebook *values*** | The versioning **mechanism** is built; populating the KRX edition is later work. `MARGIN_MODEL` raises rather than extrapolating | design §13; `rulebook.py:1414` |
| **Foreign-ownership room enforcement** | Tradeoff **T1** — removes an entire date-switched control flow (pre-KRX fill-to-room-then-cancel vs post-KRX reject-at-entry). Not vacuous: 34,653 room observations sit below a single 100-share lot | design §15.1, `equity.py:129` |
| **A broker survey** to replace the assumed commercial defaults | The commercial counterpart to the exchange-rulebook research; would retire most of §3 | handoff |
| **Event-driven callbacks** | Synchronous is simpler to test and reason about | design §13 |
| **Queue-position matching** against a reconstructed book | 81 % of best-quote changes carry no trade and there are no order ids, so order flow cannot be recovered. `Probabilistic` is the honest ceiling | design §13, `fills.py:225` |
| **Continuous-session matching validated empirically** | Report the INDETERMINATE rate as a bound on ignorance instead | design §13 |
| **Corporate-action engine wired into `advance_to`** | A CA feed is exogenous data; a session that invented an ex-date would be worse than one that says it does not know | `corporate.py:18` |
| **Put-through trading** | Out of scope; `Side.CROSS` raises rather than being silently mis-modelled | `exchange.py:1630` |
| **Auction allocation at the marginal price** | Sourced as an **absence** — UNVERIFIED in rulebook 2.4. Drawing a number for an unwritten rule is treated as worse than drawing one for an unobservable queue position | `fills.py:1141` |
| **Portfolio margining / spread credits** | ~~The formula is in VSDC's unpublished Phụ lục 02~~ — **the reason is spent.** Phụ lục 2 was obtained 2026-08-26 and §2 gives `OA = (B + S) × C × Psr` in full. It is now deferred for a different and better reason: it is **correctly zero on our corpus**, which holds exactly one derivatives underlying, so no Kendall-tau ≥ 0.9 group can form | `deposit.py::account_margin_requirement`; `post-krx-margin-spec.md` §5 |
| ~~**Post-KRX scenario margin**~~ | **BUILT and, since 2026-08-27, WIRED.** `session/scenario_margin.py` implements `Rm` / `Sm` / `Dm` / `MM` and the `MR = Max(Σ Pgm, 0)` assembly, and `session/overnight.py` is the call site — see §11. The two formulas thought missing from the gazetted text were recovered (they are `<m:oMath>` objects every text extractor drops); `Sm`'s data-shape block stands, but it bites on **calibrating `SMrate` from a corpus**, not on computing `Sm`, which takes `SMrate` as a parameter from the broker profile's published mirror | `session/overnight.py`; §11 |
| **Amend price / amend-up** | Re-taking a reservation on the same key is refused by design, and release-then-retake can fail after the release and leave a live order unfunded | `exchange.py:938` |

### 16.3 NOT BUILT with no decision recorded — the real gaps

These are not deferrals. Nobody decided them.

1. Odd-lot board (HNX and UPCoM ran odd-lot matching for the whole window).
2. PLO orders — unexpressible; every order in HNX `POST_CLOSE_PLO` is rejected.
3. `load_data_source` cannot construct either shipped adapter, with no test coverage.
4. `source=None` admits nothing, contradicting its own docstring.
5. Monthly/daily charge accrual — custody and position-management fees are never levied.
6. VAT is unreachable — no row and no config key sets it.
7. VSDC collateral-management fee and settlement-bank charge have no rows.
8. Rulebook coverage window is not enforced — 2027 dates resolve with HIGH citations.
9. `expiry_date` matches `VN30F` only; VN100F, GB05, GB10 never expire.
10. `WIDENED_TRADING_LIMIT` is tabulated with no non-test caller.
11. Bands are never computed by the simulator from the dated rulebook (A67).
12. Tiered broker commission is implemented and unwired.
13. Simultaneous opposite-side order ban.
14. `StatefulRule` / `AdmissionRule` still unmerged (§17 D6).
15. **Covered warrants are unroutable at every date.** The band formula
    (`ceiling_CW = ref_CW + (ceiling_und − ref_und)/CR`, floor likewise, floor clamped at
    the 10đ quotation unit) is **sourced** at `rulebook.py:763-777` and the absence is
    asserted as data — but nothing derives it, so `daily_trading_limit(HSX, WARRANT)`
    raises and every CW order becomes INDETERMINATE. The rulebook records that the
    floor-at-10đ branch alone fires on **16,275 of 46,090** warrant name-days, so this is
    not a corner case.
16. ~~**`charges.assess_at_maturity` is implemented, sourced, tested and never called.**~~
    **CLOSED 2026-08-27.** `ExchangeSession._maturity_charges` is the call site;
    `_mark_derivatives` levies it on every settled expiry. Pinned by
    `tests/validation/test_expiry-overnight.py::test_a_contract_carried_into_settlement_pays_the_transfer_tax`
    and by the updated
    `tests/market/session/test_exchange.py::test_the_position_settles_on_its_expiry_day_and_leaves_the_ledger`.
17. **`FillPolicyConfig` cannot express the probabilistic policy's own parameters.** It
    carries only `kind` / `max_participation` / `seed` (`types.py:2545-2556`), so a
    config-built `probabilistic` policy can never set `p_touch` or `p_auction_margin`.
    `build_fill_policy`'s docstring names this as an orchestrator request.
18. **Sixteen documented objects are absent from `plutus.market.session`'s public API**
    (§13). Not a defect in behaviour; a documented feature whose import path the doc
    previously did not state.
19. **`src/plutus/core/{position,portfolio,transaction,algorithm,bot}.py` do not import
    outside a pytest run** (D31). They are a legacy portfolio/P&L layer, out of scope by
    the project goal — the caller owns P&L — so the honest options are "delete" or "fix
    the import", and nobody has decided which.
20. **The Điều 29 position-limit warning ladder.** 80 / 90 / 100 % of *giới hạn vị thế*,
    three levels, level 3 suspending the account and permitting only offsetting trades,
    with an offsetting trade **invalidated** if it fails to bring the account below level
    3 (QĐ 26 Điều 29.1–29.5, read verbatim). This is where the primary text actually puts
    the 80/90/100 ladder, and it is the rule we spent years mis-citing at Điều 13. Not
    built; §11 gives the three reasons, of which the binding one is D33 — we do not
    compute the quantity the percentages apply to.
21. **Account-level suspension state.** `DerivativesAccount` has per-order gates and no
    suspended/not-suspended flag, so QĐ 26's three grounds for suspension (margin breach
    Điều 13.2.a, position-limit breach Điều 29.3.a, payment default Điều 26.3) collapse
    into one implicit condition, `MarginStatus.FORCED`. This is the prerequisite for #20
    and for D35, and nobody has decided to add it.
22. ~~**Post-KRX margin (`Rm` / `Sm` / `Dm` / `MM`).**~~ **CLOSED 2026-08-27.** Built
    (`session/scenario_margin.py`) and now wired (`session/overnight.py`,
    `ExchangeSession._overnight_margin`). See §11 and `post-krx-margin-spec.md`.
23. **`CorporateActionEngine` is not wired into `ExchangeSession`.** Found 2026-08-27 and
    recorded nowhere before. `grep -r 'CorporateActionEngine\|apply_due' src/` hits
    **`corporate.py` and nothing else** — there is no `advance_to` call site, so a run
    that crosses an ex-date applies nothing unless the caller drives the engine itself.
    Measured consequence: a real ex-dividend (PLX, ex-date 2022-11-09, a 1,200đ/share
    cash dividend implied by the published band) sits inside the `pair-trade` window and
    is silently missed; a position held continuously across it would lose
    300 × 1,200 = 360,000đ with no log row and no error. The run happens to be flat that
    day, so "every đồng accounted for" is true of that run and would not be true of the
    obvious variant. This is also why D65's band guard only helps a caller that supplies
    a band. **Related, and cheap:** `state_at('PLX', 2022-11-09)` returns
    `reference=29.45` (stale) with `ceiling=30.20, floor=26.30` — internally inconsistent
    by 4.1%, and `reference == mid(ceiling, floor)` would be a cheap invariant nobody
    checks.
24. **`exchange.parse_config` does not call `fills.parse_fill_policy_config`.** The
    builder-level guards added 2026-08-27 refuse a `FillPolicyConfig` field no policy can
    honour, but `parse_config` reads the YAML with three `.get()` calls, so an unknown key
    — `p_touch`, a misspelled `participation` — is dropped before the builder can see it.
    A guard that is not on the path is not a guard, and `parse_fill_policy_config`'s own
    docstring says so. One line, and nobody has taken it.
25. **`OrderBookOfRecord.encumbrance_divergence` has no caller.** *(It is exported from `plutus.market.session` as of 2026-08-27; what is missing is a **call site**, not an import path.)* The per-order form of
    §12 invariant 4 exists because the totals form in `validation/identities.py` is
    sampled where nothing is live and both sides are zero — which is why a 2,034,329đ
    divergence lasting the whole life of a resting order read as clean. Wiring it in as a
    tenth breach source, and/or into the snapshot step, is what turns the meter on. Until
    then the harness still cannot see that class of defect and this file does not claim it
    can.
26. **`adapters/tick.py` serves no `MarketInterval` at all.** `DataHubSource` gained the
    `IntervalSource` seam; the tick adapter did not, so a tick-resolution run has no
    volume and every capped policy is INDETERMINATE there. It is also the only adapter
    that can reach the 3-level book ladder, so this is where a depth-aware policy would
    have to start.
27. **`quote_open` / `quote_max` / `quote_min` are on disk and not served.** Verified as
    the daily bar (`max ≥ close ≥ min` in 818,365 of 818,413 ticker-days from 2021). With
    them, `HardFillPolicy` could return a definite `NO_FILL` for a limit the day's low
    never reached and could decide the continuous touch that currently makes
    `pair-trade`'s hard arm 2-of-3 INDETERMINATE. Deliberately left out of the volume
    change because wiring the extremes moves decisions in **both** directions
    (unproven→filled and unproven→definitely-not-filled) and deserves its own
    measurement. Named in `DataHubSource.WITHHELD` and counted on every fill as
    `fill.decided_without.{open,high,low}`.

---

## 16.4 CONFLICTS RECORDED RATHER THAN RESOLVED — validation pass, 2026-08-27

Every item here is a defect a scenario audit found and this session **deliberately did not
fix**, because the fix would require choosing between readings the sources do not settle.
Standing rule 3. Each names what would have to be decided.

1. **Derivatives cash settles T+0 against the repository's own dated T+1 rule.**
   `RuleSet.settlement_rule(InstrumentKind.FUTURE)` returns `cycle_days=1,
   delivery_on_next_session_open=True`, `Confidence.HIGH`, VSDC-cited
   (`rulebook.py:1329`). Its only consumer, `exchange.py::_settles_at`, is called
   **once**, inside the *securities* branch of `_apply_fill`. The derivatives branch never
   calls it, and neither does `settle_expiry`. Measured across three scenarios: realised
   close-outs and final settlements credit the deposit at the trade/expiry instant —
   +28,440,000 on a Tết-2021 expiry made spendable one session early on an account in
   `FORCED` breach; −6,470,000, +2,550,000, −1,250,000 elsewhere. **What must be decided:**
   whether unsettled variation margin still counts as a margin asset in the interim. It
   changes every derivatives utilisation number in the repository, and no source read here
   settles it. Building the pending-deposit tranche without that answer would be inventing
   the margin treatment, not implementing the settlement rule.
2. **`settle_daily` has no session call site, so VM is cumulative rather than daily** (D1,
   restated with the new measurement). `deposit.py`'s own docstring says **no cash moves**
   in `settle_daily` — it only re-baselines `_settlement_reference` — so wiring the call
   site fixes the cumulative-vs-daily half and **nothing else**; there is no code anywhere
   in `src/` that pays daily VM cash. Direction is now measured and is one-sided: at one
   corpus mark the model reports utilisation 1.2099 where VSDC's actual daily cash
   settlement gives 1.371. **The simulator is consistently later to call than a real
   clearing member.** Author's call, unchanged.
3. **A limit order always fills at its own limit, never at the market.**
   `fills.py:748` returns `FillDecision.fill(..., limit, ...)` even when `reach > 0`
   (`TRADED_THROUGH`); `HardFillPolicy` does the same. Measured: a BUY 300 ACB @ 22.00 on
   2022-10-21 filled at 22.00 when ACB's maximum matched price that day was **21.40**. The
   module's own docstring cites QĐ 352 Điều 6.3 (*trade at the resting order's price*) in
   defence — and Điều 6.3 makes the **resting** side set the price, so for an *aggressor*
   the citation says the opposite of what the code does. Filling at the limit is
   conservative for a strategy backtest and **anti**-conservative fed into a margin ladder:
   it understates proceeds and manufactures calls. Measured cost in the equity-margin arms:
   9,910,000đ, and on 2022-10-25 the forced sale made the ratio *worse* (0.3445 with it,
   0.3569 without). **What must be decided:** what price to use given only a bar. The
   sources are silent, and the honest answer may be `INDETERMINATE` over `[limit, extreme]`
   rather than a number.
4. **Every price in every corpus scenario is same-session look-ahead.**
   `adapters/datahub.py::state_at` returns the whole-day bar for `ts.date()` at any
   intraday instant, so `ctx.price()` at the 09:30 step hands the strategy that day's
   **close**, and `_marks()` prices the 09:30 margin mark with it. Consequences measured:
   every one of `pair-trade`'s 93 fills is `limit == fill_price == that session's close`
   with `evidence=touched_at_limit`, which is why a "0/112 indeterminate" run and a 100%
   fill rate coexist — and it exactly cancels conflict 3, since limit == close. Against the
   tick archive the daily-close mark produces a **missed forced close** (2022-11-11 14:00,
   true utilisation 1.0284), a **missed warning** (2022-11-15 09:30, 0.8445) and **two
   forced-liquidation reports at instants when the account was `ok`** (2022-11-14 and
   11-16 09:30). **The fix is not a margin-model change:** `quote_open`, `quote_high`,
   `quote_low` and `quote_dailyvolume` are on disk and complete over the window (620 rows
   each for open and volume across 31 names × 20 sessions) and `DataHubSource` reads none
   of them. `exchange.py:1790` unconditionally declares them missing, which is an adapter
   gap misattributed to the corpus. This is the single highest-value remaining fix and it
   is an adapter change that moves every number in every scenario, so it wants its own
   pass and the author's sign-off.
5. **`DebitedAt.MONTHLY` and `DebitedAt.DAILY` charges are never levied** (§16.3 #5,
   now quantified). `assess_daily` has **zero call sites in `src/`** and `charges.assess`
   filters every non-`FILL` row out. Two dated, `Confidence.HIGH` rows are affected:
   `vsdc_custody_equity` (0.27đ/share/month, from 2020-03-19, no end date) and
   `vsdc_derivatives_position_management` (2,550đ/open contract/day, 2020-03-19 →
   2022-01-01). For the Tết-2021 window the per-day fee is the **entire** VSDC leg — there
   is no `vsdc_derivatives_clearing` row before 2022-01-01 — and 6 lots held 2021-02-05 →
   2021-02-18 cost **76,500đ** on trading days or **198,900đ** on calendar days against a
   levied **0**. **What must be decided:** the rulebook is silent on trading-vs-calendar
   days for the per-day fee, and on proration for the monthly one. `rulebook.py:1772` also
   records that brokers demonstrably billed the per-day fee through at least 2024-07-11
   while the gazetted schedule ends it at 2022-01-01, so a run reproducing actual retail
   costs and one applying the gazette disagree for three years — and the scenario named
   `overnight` currently takes the gazetted branch with no annotation.
6. **The 5% dividend withholding is never levied.** `corporate.py:1556` credits the cash
   leg with a reason string saying it is GROSS of the withholding "which is a charge row
   the rulebook does not carry". Rulebook §12.3:1112 **does** carry a `Cash dividend tax …
   0.05` row, graded `low (uncited)` (this is D27). Measured: the applied ex-date run's
   headline `net_pnl` is **62,500đ too high**. Implementing it means asserting an uncited
   rate as a levied charge. **What must be decided:** obtain a citation, or grade the row
   and levy it as LOW.
7. **A forced sale is executed inside the client's statutory cure window**, 8 of the 9
   escalated calls (D53, sharpened). `_breach_days` increments on the observation that
   *issues* the call, so three breaches land on the third observation while three business
   days elapse on the fourth. Exactly: `call:3` issued 2022-10-20 14:45 with deadline
   2022-10-25 14:45; `CONSECUTIVE_BREACH_DAYS` fires 2022-10-24 14:45 and the ticket is
   submitted 2022-10-25 09:30. `BrokerMarginTerms.__post_init__`'s
   `consecutive ≤ max_cure_business_days` guard does not catch it because the error is in
   the **counting**, not the parameter — it refuses `10 > 3` and permits `3 == 3` to fire a
   day early. **What must be decided:** whether the unsourced broker term
   (`consecutive_breach_days_before_sale`, which a broker could legitimately read as "three
   consecutive closes in breach") is subordinate to the QĐ 87 Điều 7.1 window, i.e. whether
   the sale must be blocked while an outstanding call is still inside its deadline. Two
   clocks, one sourced and one not; picking would be choosing a reading.
8. **`quote_settlementprice` is not usable as published by `expiry.py`.** Half of one
   auditor's finding survives and half does not. **Does not survive:** the claim that the
   table is a raw tick series whose last entry is the window maximum, so that
   `PUBLISHED_FINAL_SETTLEMENT = 972.78` over-books by ~447,560đ. Re-measured across all
   18 days in the corpus, the series' tick-to-tick increments **decay** through the window
   (first-quarter mean |Δp| 0.032 → last-quarter 0.013 on 2022-11-17, and 14 of 16 clean
   days show the same shape) and the implied underlying reconstructed under the
   running-mean hypothesis is smooth and in range. That is the running-mean signature, and
   D23 and the handoff stand: the last entry **is** the settlement. **Does survive:** the
   table is keyed `VN30INDEX` on 14 of its 18 days and by contract code on only 4, so
   `expiry.py::_published`'s `WHERE tickersymbol = ?` **misses every index-keyed expiry**,
   including VN30F2211's on 2022-11-17. It also holds one corrupt day (2022-08-16,
   VN30F2208, prices ~142,243 mixed with ~1,295 — the existing `price < 100000` filter
   catches these) and only 18 days in total. **What must be decided:** whether a
   `VN30INDEX`-keyed row *is* the settlement source for a VN30F contract. It probably is —
   the VN30 futures final settlement is defined off the index — but the corpus is
   inconsistent about what it keys, and mapping contract → underlying without a stated rule
   risks silently substituting an index value for a futures settlement. **Not in the
   session's path:** `DataHubSource` never populates `settlement_price` at all, so every
   corpus expiry correctly takes the `CLOSE_PROXY` tier with `substituted=True` on the
   event.
9. **`FORCED_LIQUIDATION` collects nothing and the shortfall is never recovered.**
   Declared as the Tier 1 / Tier 2 boundary (`detail['executed'] = False`, with its own
   stated reason), so this is working as designed — but the cost is now measured and worth
   recording beside the declaration: on 2021-02-08 an account required 113,916,000 against
   a deposit of 99,939,344, short **13,976,656đ**; `FORCED_LIQUIDATION` fired at six
   consecutive marks, the deposit did not move by one đồng at any of them, and the position
   ran to expiry unfunded. A forced liquidation that changes nothing is a call effectively
   missed. Two arms of `expiry-overnight` that differ only in trading calendar produce
   **byte-identical** logs and snapshots and differ by exactly one event, for this reason.
10. **The cure window cannot be exercised under the documented loop** (D40, reconfirmed).
    `_cure_deadline` returns HNXDS 08:45 and the documented two-advance day puts the
    caller's first decision point at 09:30, so the mark escalates before `on_session` is
    called. A trader who pays on the morning of T+1 — which is what QĐ 26 Điều 13.1
    requires — is force-closed first. The regulated deadline is **09h30 T+1**, so the
    direction to move the default is later, not earlier; that is a broker-terms change and
    the author's call.
11. **The dated rulebook says the post-KRX margin mechanism could not be obtained;
    `scenario_margin.py` implements it from the signed instrument.** Both cannot be true.
    `rulebook.py`'s `RuleName.MARGIN_MODEL` row from `KRX_CUTOVER` is `_unsourced`, cites
    *"VSDC QĐ 26/QĐ-HĐTV (2025-04-16) — **never read**; the COMS formula could not be
    obtained"*, and therefore **raises** at every post-cutover date. QĐ 26 and its Phụ lục 2
    were subsequently obtained and read end to end (§19, 2026-08-26), and the resulting
    2,989-line engine is now wired as the overnight layer. **What must be decided:** whether
    that row becomes a sourced `'post_krx_scenario_grid'` value citing QĐ 26 + Phụ lục 2.
    Not taken here for two reasons. Re-dating a row of the gazetted rulebook is a sourcing
    decision about a legal instrument, not a code change, and the two statements are not
    quite about the same thing — Phụ lục 2 is the **CCP's end-of-day submission**, and what
    the intraday broker ladder computes after the cutover is a separate question no source
    read here answers. The consequence of leaving it is visible rather than silent: a
    post-cutover run records `rule.margin_model.unsourced` on every intraday mark **and**
    computes a sourced overnight requirement in the same advance, which reads as a
    contradiction until this paragraph is read.
12. **Post-KRX `MR` is smaller than pre-KRX `MR` by exactly the variation margin, and this
    simulator never pays that variation margin in cash.** Measured: 60,044,000đ against
    109,844,000đ on one 2-lot VN30F position. Phụ lục 2 §6.2 has no `VM` term because Điều
    20 settles position P&L as a separate T+1 cash movement; conflict 2 above is that we do
    not make that movement. Each mechanism is internally consistent and the **mixture is
    permissive** — a run quoting the grid's number while carrying the loss in nothing at all
    reports an account owing less than it does. Counted as
    `margin.overnight.assumed.variation_margin_unsettled` on every affected result rather
    than resolved, because resolving it *is* conflict 2.

---

## 17. Known defects and docstring mismatches

Found by adversarial reading. The suite was green through all of them — **green tests
prove very little on their own** (standing rule 4).

| # | Defect | Where |
|---|---|---|
| D1 | `settle_daily` is documented as the DSP rebaseline but **no session path calls it**, so VM is measured from `average_entry` for the life of every position (A60) | `deposit.py:1190` vs `exchange.py` |
| D2 | `ExchangeSession.transfer`'s docstring says the deposit withdrawal is bounded by `free_deposit`; it is bounded by `balance − MR/threshold`, which `deposit.py` explicitly says is **not** `free_deposit` | `exchange.py:1083` vs `deposit.py:1113` |
| D4 | `MarginView.initial_margin` is populated as IM + resting-order margin while its own docstring defines it as IM alone (`posted_margin` is the real IM). No double count; the **name** is wrong | `deposit.py:745` vs `types.py:1568` |
| D5 | `_session_refusal` stamps `INDETERMINATE` purely on `phase is UNKNOWN`, mislabelling three **definite** refusals (already-terminal, non-amendable type, quantity-below-filled) as ignorance | `orders.py:1130` |
| D6 | `StatefulRule` is a second rejection enum the code itself says must be merged into `verdicts.AdmissionRule`; a rejection-log consumer must read the `RejectionRule` union | `types.py:524` |
| D7 | A **third** charge engine (`exchange.py:_derivative_charges`) duplicates `ledgers.assess_charges`, and its stated reason is now stale — `assess_charges` grew the `multiplier` parameter it asked for, and returns identical amounts. A live drift risk | `exchange.py:2118` |
| D8 | `fills.py` module docstring claims every shipped policy obeys the three conventions; `soft` obeys neither the lot floor nor the cap, and claims `confidence = 1` on every definite decision while `NO_FILL` carries 0 | `fills.py:52`, `:110` |
| D9 | `ProbabilisticFillPolicy` docstring says it keeps **seven** INDETERMINATE cases; there are **ten** reachable | `fills.py:1327` |
| D10 | `expires_at_boundary` docstring says an ATO dies at "its own cross"; the code keys on `tif` and fires at the end of **any** auction phase | `orders.py:296` |
| D11 | `amend()`'s defaults `allow_price_and_quantity=True` / `priority_preserving=True` encode the pre-2025-05-05 regime and the **rejected** side of a recorded CONFLICT | `orders.py:901` |
| D12 | `reject()`'s docstring claims the terminal hook may have "something to release"; the record it builds can never carry an encumbrance | `orders.py:653` |
| D13 | Amend, cancel and transfer refusals **never reach the event cursor** and are counted only when INDETERMINATE | `exchange.py:930`, `:1102`, `:2574` |
| D14 | `BROKER_CONFIG_KEYS` is exported, documented as the single mapping layer, and **read by nothing** | `types.py:2412` |
| D15 | ~~`fill_policy.max_participation` is silently discarded on the default `soft` policy, and the discard is invisible in `provenance()`~~ **CLOSED 2026-08-27.** Two repairs: `soft` became a `_CappedFillPolicy` that carries the cap, and `FillPolicyConfig.max_participation` became `Optional[Decimal] = None` so a written 0.10 is no longer indistinguishable from an unwritten one. `parse_config` routes the block through `parse_fill_policy_config` and no longer invents a `'0.10'`. Pinned by `test_exchange.py::test_a_fill_policy_block_naming_one_tenth_reaches_the_session_capped` | `exchange.py::parse_config` |
| D16 | Struck figures still live in two docstrings: design §15.2 says 1281.36 and 0.36 % "should be struck wherever they appear"; they remain at `deposit.py:1481` and `types.py:2039`, so the codebase states **two different costs for the same substitution** | as listed |
| D17 | `README.md:359` still labels `FOREIGN_ROOM` as "cap, not remaining room" — verified wrong (it is remaining room, confirmed on HPG 2022-11-15 tick-by-tick); `tests/sample_data/README.md:345` says the opposite | `README.md:359` |
| D18 | `market/__init__.py` advertises the foreign-room check as running before an order rests, and claims the package has "no order lifecycle" — both stale | `market/__init__.py:5-10` |
| D19 | `equity.py:8` retains a **measurement claim** ("does not change the measured blocked-entry rate") inside a module docstring. Measurements are retracted; this should go | `equity.py:8` |
| D20 | `RuleSet.charges` hardcodes `'VN30F'` when folding the derivatives PIT rate while `charges._with_margin_rate` resolves the actual ticker — for any family whose ratio differs, `_pit_rate_check` raises for what is really a hardcoded lookup key | `rulebook.py:2324` |
| D21 | `daily_trading_limit(HSX, INDEX)` returns 0.07; the bond `NOT_APPLICABLE` row is unreachable because `InstrumentKind` has no BOND member | `rulebook.py:672`, `protocol.py:82` |
| D22 | `core/constant.py`: `trading_time_end` raises `AttributeError` on UPCoM (worked around in `calendar.py:508`); `TICK_SIZE` is a second copy of HOSE's band table; `DAILY_TRADING_LIMIT` is four flat undated scalars | `core/constant.py` |
| D23 | `expiry.py`'s `_twap_30m` averages raw `quote_matched` trades, but the corrected finding is that `quote.settlementprice` is an **already-computed running mean** whose last entry *is* the settlement | `expiry.py:107` |
| D24 | `_apply_pins` documents "the most specific matching pin wins" but uses `>=`, so equally specific pins resolve by **last-declared** | `rulebook.py:2494` |
| D25 | **Two divergent multiplier paths.** `deposit.multiplier_for` (`:918`) reads the dated table and never `InstrumentSpec`, so margin is right; but `adapters/datahub.py:239-248` stamps `multiplier=100000` on every futures-prefix match, and `SymbolRouter.instrument` prefers the source's value over `_default_multiplier`. Verified: `session.instrument('GB05F2312')` returns **100,000** with a DataHub source and **10,000** without one. §16.1 Decision 3's "GB05 = GB10 = 10,000 … stays" is half true | `adapters/datahub.py:239`, `rulebook.py:2732`, `exchange.py:1193` |
| D26 | **`margin.MarginConfig.default_multiplier` (A63) is in §3 but not in `margin.py`'s `PROVENANCE`**, and `margin.py:202` carries only `# VND per index point`. That breaks §18 rule 1 ("the two must agree") and §3's own opening sentence. Add the `PROVENANCE` entry | `margin.py:71-108`, `:202` |
| D27 | **`corporate.PROVENANCE['dividend_withholding_tax']` states a false premise** — "not in the rulebook … the rulebook carries none for it". Rulebook §12.3:1112 carries a `Cash dividend tax … 0.05 … low (uncited)` row and §8.1:768-769 says it must be netted. The true statement is that `rulebook.py::_charge_table` has no dividend row | `corporate.py:263` |
| D28 | **A dangling citation repeated three times.** `ledgers.py:628`, `:726`, `:1209` all cite **"rulebook 8.4"**, which does not exist — §8 is 8.1 Taxes / 8.2 Exchange and depository prices / 8.3 Brokerage commissions. The content cited (TT 121/2020 Art. 27, the lending prohibition) is at rulebook **§5.2:511**, graded **`low`** ("read in summary form only, not verbatim") | `ledgers.py:628`, `:726`, `:1209` |
| D29 | **`third_thursday` exists twice** — `expiry.py:46` and `adapters/datahub.py:84` — and the adapter carries its own `_CONTRACT_MONTH_RE` (`:39`, `^VN30F(\d{2})(\d{2})$`) which is **narrower** than its own `_FUTURES_RE` (`^(VN30F\|VN100F\|GB\d)`), so a VN100F or GB contract matched as a future gets `expiry=None`. Same drift risk as D7 | `expiry.py:46`, `adapters/datahub.py:84`, `:39` |
| D30 | **A dead branch documented as live.** `SymbolRouter.instrument`'s `if limit is None` (`rulebook.py:2721-2727`) can never run: `daily_trading_limit` **raises** for a warrant, and the only `None`-valued band row is `(None, 'BOND')`, unreachable because `InstrumentKind` has no BOND member (D21). Behaviour is unchanged; the docstring describes a path that does not execute | `rulebook.py:2721` |
| D31 | **Five `core/` modules cannot be imported outside pytest.** `core/position.py:35` and `core/transaction.py:74` do `import utils`, which resolves to **`tests/utils.py`** only because pytest's prepend import mode puts it on `sys.path`. Verified: `PYTHONPATH=src:. python -c "import plutus.core.bot"` → `ModuleNotFoundError: No module named 'utils'`, and the same for `position`, `portfolio`, `transaction`, `algorithm`. **The suite is green because `tests/utils.py` shadows the gap** — a textbook standing-rule-4 case. `protocol.py:20-21` already records the fact in a comment; it had never reached this inventory. Note `market.protocol.Position` (`protocol.py:164`) is a **different class** and is the live one | `core/position.py:35`, `core/transaction.py:74` |
| D32 | **The withdrawn Article-13 attribution survives in three modules this correction did not own.** `broker.py` and `deposit.py` were corrected on 2026-08-26; the identical claim is still live at `margin.py:12-14` (*"an 80/90/100 ladder … Article 13 of QĐ 96/QĐ-VSD → QĐ 61/QĐ-VSD, **confidence high**"* — note this one stops the chain at QĐ 61 and grades it HIGH anyway), `margin.py:75` (`PROVENANCE`, *"the actual call test is utilisation = MR / margin assets against an 80/90/100 ladder"*), `exchanges/derivatives.py:115`, and — the one most likely to be copied — **`types.py:643-649`, `MarginStatus`'s own docstring**, which still says *"the shape of the ladder is VSDC-sourced (rulebook 6.3, Article 13: levels 1/2/3 at 80/90/100 per investor account)"*. Behaviour is unaffected in all four; the **claim** is dead. Reword to match `BrokerTerms.PROVENANCE` | `types.py:643`, `margin.py:12`, `:75`, `exchanges/derivatives.py:115` |
| D33 | **The position-limit gate counts the wrong quantity, and QĐ 26 Điều 27.2.a now says so in primary text.** The regulated count is *"tổng số lượng vị thế của các HĐTL có cùng tài sản cơ sở, cùng hệ số nhân hợp đồng nhưng khác tháng đáo hạn"* — summed **across expiry months** of one underlying, same-expiry opposite legs netted first — and `rulebook._position_limit_table` is correctly keyed on the contract *family*. But `reserve_for_order` tests `_worst_case_net(contract_code)`, i.e. **one expiry**. An account holding 4,000 VN30F2401 and 4,000 VN30F2403 counts 8,000 under Điều 27.2.a and passes both tests at 4,000 each against a 5,000 cap. This is the ordinary shape of a rolled futures position, not a corner case. **Fix changes behaviour — author's call** | `deposit.py::reserve_for_order`, `_worst_case_net` |
| D34 | **The position cap is exclusive; Điều 29.1.c is inclusive.** We reject on `after > cap`. Điều 29.1.c fires level 3 when the count *"đạt ngưỡng 100% giới hạn vị thế"* — **reaches** the cap — and Điều 29.3.b requires the account back *below* it, so an account resting exactly on the limit is suspended there and admitted here. One contract, in the permissive direction. Behaviour change; author's call | `deposit.py::reserve_for_order` |
| D35 | **`transfer_out`'s suspension test is narrower than its source.** QĐ 26 Điều 11.1.c bars withdrawal from an account suspended for a margin breach, **a position-limit breach, or a payment default** — three grounds. We test only `status is FORCED`. Not fixable in isolation: the other two states do not exist anywhere in `deposit.py`, which has no account-level suspension flag at all, only per-order gates | `deposit.py::transfer_out` |
| D36 | **The suite's own total is not stable across invocations: 1318 vs 1365, a gap of 47. Observation, not a diagnosis — do not repeat it as one.** Everything below was run from the repo root on 2026-08-26 and is reproducible. (a) `pytest tests -q` → **`1318 passed`**, exit 0, and the summary line names **no** skipped, deselected, xfailed or errored tests. Run twice, same number. (b) `pytest tests --collect-only` → **1365 collected**, twice, once with `-p no:cacheprovider`; the 1365 node ids are unique (`sort \| uniq -d` is empty). (c) `pytest tests -rs -q` prints **`collected 1365 items`** in its own header and is observed executing files that the 1318 runs did not reach. (d) Same split one level down: `pytest tests/market` → **863 passed**, `pytest tests/market --collect-only` → **910**. (e) The 47 are individually healthy: `pytest tests/market/test_margin_incidence.py tests/market/test_margin_incidence_account.py tests/market/test_equity_headline.py` → **47 passed** standalone. That triple summing to exactly 47 is suggestive and may be coincidence — **nobody has diffed the two node-id sets**. **Why it matters more than a bookkeeping slip:** a run that silently drops 47 tests and a run that keeps them print the same word, *passed*, and differ only in a number nobody checks. Standing rule 4, in its purest form. **Pre-existing** — the four tests added this session live in `test_deposit.py`, which runs in every variant, so the same split sat under the 1314 baseline (inferred; no baseline `--collect-only` was ever recorded). **The obvious candidate does not fit:** the corpus/tick `skipif` gates in `tests/market/conftest.py` would surface as *skipped*, both corpus roots resolve on this machine, and skips do not change a collected count. **How to settle it:** dump collected node ids (`pytest tests --collect-only -q -q`, keep `::` lines, sort) and executed node ids (`pytest tests -v`, extract `^tests/…::…`, sort), then `diff`. The 47 names are the answer. Until someone does, the header and §19 counts say "passed", never "collected" | `tests/market/conftest.py`; `tests/market/test_margin_incidence.py`, `test_margin_incidence_account.py`, `test_equity_headline.py` |
| D40 | **A margin call cannot be cured under the loop `advance_to` documents.** `MarginMonitor._cure_deadline` returns `calendar.next_session_open(...)` — HNXDS **08:45** — and the documented two-advance day puts the caller's first decision point at 09:30. So the 09:30 advance marks, finds the deadline past, and escalates to `FORCED` **before `on_session` is called**. Measured on the corpus (`validation/scenarios/expiry-overnight.py::run_cure_across_tet`): five VN30F2202 lots called at the close of 2022-01-28 are force-closed at 2022-02-07 09:30 under *both* trading calendars, and a 30,000,000 VND payment made that session arrives after the event. Stepping at 08:00 instead cures it. The regulated top-up deadline is **09h30 T+1** (QĐ 26 Điều 13.1), so the direction to move the default in is later, not earlier | `deposit.py::MarginMonitor._cure_deadline`, `validation/runner.py::DEFAULT_OPEN` |
| D41 | ~~**`ExchangeSession` exposes no path to `MarginMonitor.outstanding_call`.**~~ **CLOSED 2026-08-27.** `ExchangeSession.outstanding_call()` and `ExchangeSession.in_forced_breach()` are the accessors. Pinned by `test_exchange.py::test_a_cured_margin_call_is_closed_out_in_the_event_log`. Original text below | `exchange.py::outstanding_call` |
| D41-orig | **`ExchangeSession` exposed no path to `MarginMonitor.outstanding_call`.** `account_margin_requirement` returns `cure_by=None` deliberately and correctly (a deadline is state across days, not a property of one mark), and `MarginMonitor.outstanding_call` holds the real value — but the string `outstanding_call` does not occur in `exchange.py`. The deadline is therefore stamped on the `MARGIN_CALL` event and **nowhere else**, so a caller that reads its state rather than its event stream, or that restarted, cannot find out when it has to pay | `exchange.py`, `deposit.py::MarginMonitor.outstanding_call` |
| D42 | ~~**The session never asks the rulebook which margin model applies.**~~ **FIXED 2026-08-27, in two places.** `RuleSet.margin_model()` **raises** `UnresolvedRule` at every date from `KRX_CUTOVER` (*"POST-KRX VALUE NOT SOURCED"*), and it has **no caller anywhere in `src/`**. A VN30F2603 long carried through the real 2026-03-09 limit-down is margined `IM + VM` at 0.17 — the pre-KRX broker shape, ten months past the cutover — the run completes, nothing raises, and `indeterminate_report` counts **zero**. A run that cannot resolve a *band* answers INDETERMINATE and counts it; a run that cannot resolve the *margin model* answers with last year's. **Fix:** `_mark_derivatives` now *asks* — the mark still runs on `IM + VM`, because refusing to margin an open position is not the safer answer, and each such mark records `rule.margin_model.unsourced` in `silent_ignorance` while `Component.MARGIN_MODEL` records the answered case. And the rulebook's refusal is now the **signal to ask the profile instead**: `_overnight_margin` takes it as "we are past the cutover" and dispatches on `margin_model_overnight`, so finding F-1's other half — *there is no overnight margin layer at any date* — is closed too. Pinned by `test_exchange.py::test_the_margin_model_is_asked_and_an_unsourced_answer_is_counted` (both arms) and by five tests in `test_expiry-overnight.py`. **What remains, as a conflict and not a defect:** see C-13 | `rulebook.py::margin_model`, `exchange.py::_mark_derivatives`, `exchange.py::_overnight_margin`, `session/overnight.py` |
| D43 | **No admission rule is keyed on `InstrumentSpec.expiry`.** An order in a contract whose last trading day has passed is refused only when the *data* runs out — on the corpus it comes back `band_limit` / `INDETERMINATE` / `band_source='absent'`, i.e. "no row", not "delisted". A source that kept publishing a price past the expiry would have the order **admitted** and a position opened in a contract the exchange has removed. `ExpiryTrigger.INSTRUMENT_EXPIRY` is declared in `types.py:500` and fired nowhere (already noted there as a partial); this is the admission half of it | `exchange.py::submit`, `types.py:500` |
| D44 | **`MarginView.initial_margin` already contains `resting_order_margin`.** `account_margin_requirement` sets `initial_margin = initial + resting_margin` and `posted_margin = initial`. A reader who computes `initial_margin + variation_margin + resting_order_margin` double-counts every resting order; the true identity is `required == posted_margin + resting_order_margin + variation_margin`. Naming only — no behaviour is wrong — but it is a trap that costs a wrong number rather than an error | `deposit.py::account_margin_requirement` |
| D45 | **The corpus inverts `ceil`/`floor` on the two VN30F sessions either side of Tết 2021.** VN30F2102 on **2021-02-08** publishes `ceiling 1060.2 / floor 1219.6` and on **2021-02-09** `1015.6 / 1168.4`, so every order on the last two sessions before the break is refused on `band_limit`. This is the swapped-band defect reaching the derivatives rows, and the rejection carries `detail == {'band_source': 'published'}` with no hint that the published band is impossible. A **data** defect, but it means any scenario placed on those dates measures the corpus and not the rulebook, and the simulator could reasonably refuse an inverted band under a rule of its own | `adapters/datahub.py::_build_state`; corpus `quote_ceil` / `quote_floor` |
| D50 | **`margin_lending.py` labels no price with a currency unit, and the three cash venues quote in thousands of đồng.** `CollateralLot.last_close`, `assess_margin_order(price=…)` and `MarginCollateralPosition.price` are unlabelled `Decimal`s, while `MarginAccountState.cash` comes off a ledger denominated in đồng. `charges.trade_value` is the **only** place `CURRENCY_UNIT` is applied, and it is on the order path, not the margin path. Passing an HSX quote of `22.70` straight through makes `PV` one thousandth of `CB`: an account that borrowed 92 m and holds 181.6 m of stock reports `EB` = 100,181,600, a ratio of **0.0999 instead of 0.5146**, and on the way *down* the ratio **rises**, because the only term moving is the one that is right. Nothing raises; `CollateralLot` accepts any positive `Decimal`. Fixed **at the wiring boundary** (`equity_margin.py::EquityMarginAccount._dong`, which resolves the venue per ticker and returns `None` — hence UNPRICED, hence INDETERMINATE — when it cannot); the underlying type contract is still unit-free and the next caller will hit it. Pinned by `test_equity-margin.py::test_pv_is_in_dong_not_in_the_quoted_thousands` (24 of 50 tests fail without the fix) | `margin_lending.py`; `equity_margin.py::_dong` |
| D51 | **A forced-sale ticket is not a board lot, and `plan_forced_sale` says so on purpose.** *"Quantities are in whole shares and are not rounded to a board lot. Lot sizes are the exchange's and belong to the order layer that submits these tickets."* Until `equity_margin.py::_to_lot` existed, that order layer did not, and **every** *bán giải chấp* on the corpus — 1,459, 913, 1,070, 1,633, 1,762 shares — came back `Rejected(ROUND_LOT)` while the margin event log said a sale had been instructed and the account went on breaching. Rounded **up** now, because `value_to_restore` is a minimum, capped at the sellable quantity floored to a lot. Pinned by `test_every_forced_sale_ticket_is_a_whole_board_lot` (7 tests fail without it) | `margin_lending.py::plan_forced_sale`; `equity_margin.py::_to_lot` |
| D52 | ~~**The harness trade log has no `ACCEPTED` row for any order the *session* places.**~~ **CLOSED 2026-08-27.** `_translate_events` now skips `ACCEPTED`/`REJECTED` only when the log already holds that order's row, so a strategy's orders are logged exactly once and a broker's are logged at all. It was worse than the original text: `REJECTED` was skipped too, so a *bán giải chấp* the exchange refused at the floor lock had **zero** rows of any kind. `order_lifecycle` now holds on every equity-margin arm. Pinned by `test_equity-margin.py::test_a_broker_initiated_order_reaches_the_trade_log` and `::test_a_forced_sale_into_a_floor_locked_market_does_not_execute`. Original text below | `validation/runner.py::_translate_events` |
| D52-orig | **The harness trade log had no `ACCEPTED` row for any order the *session* places.** `validation/runner.py:381` skips `ACCEPTED`/`REJECTED` events because `StrategyContext` has already logged them from `submit()`'s return value — true for every order a **strategy** places, false for every order the **broker** places, and a *bán giải chấp* is the first of those in this simulator. The fill rows then join to nothing and `validation/identities.py:332` reports `order_lifecycle` broken on every equity-margin arm (the orders themselves are fine; the log is incomplete). One condition in `_translate_events` fixes it; the file belongs to the harness. Asserted rather than worked around by `test_equity-margin.py::test_a_broker_initiated_order_is_missing_from_the_trade_log` | `validation/runner.py:381`, `validation/identities.py:332` |
| D53 | **`CURE_WINDOW_EXPIRED` — the only *statutory* forced-sale trigger — is unreachable at a firm whose cure target equals its call level.** `BrokerMarginTerms` correctly refuses `consecutive_breach_days_before_sale` above the QĐ 87 Điều 7.1 ceiling, so the consecutive clock is capped at 3; and the breach counter increments on the observation that **issues** the call, so three breaches land on the third observation while three business days elapse on the fourth. The broker term therefore fires one session earlier, every time, whenever the breach is uninterrupted. Not a bug in either object — an interaction — but a run that reported "no cure window ever expired" would be reporting two broker terms as if they were the law. The one lawful configuration that reaches it is `cure_target_ratio > maintenance_margin_ratio`: a ratio landing between the two resets the counter without curing the call. Both arms are run and asserted | `margin_lending.py::MarginCallMonitor.observe`, `::BrokerMarginTerms.__post_init__` |
| D54 | **An equity margin account whose `determination_time` sits after the caller's last advance is silently inert.** It lends, never computes a ratio, never calls, never sells — with nothing raised and every identity holding. Reportable through `EquityMarginAccount.missed_determinations`, which is a property and not an exception because the account cannot know the run has ended. A scenario that does not check it can publish a clean run that graded nothing | `equity_margin.py::on_advance` |
| D55 | **`MarginEventKind` has 18 members and `types.EventKind` has 3 margin members, so the session cursor is lossy for equity margin.** `LOAN_DISBURSED`, `LOAN_REPAID`, `INTEREST_ACCRUED`, `FORCED_SALE_NOTICED` and `FORCED_SALE_RESULT_SENT` reach `EquityMarginAccount.events` and **not** the session's event stream; the rest arrive under `MARGIN_CALL` / `MARGIN_WARNING` / `FORCED_LIQUIDATION` with `pool=SECURITIES` and `detail['equity_margin_event']` naming the real kind. `MarginEvent`'s own docstring says the two streams merge as new members; until they do, a caller polling only the session cursor cannot see a disbursement or an accrual | `equity_margin.py::EQUITY_MARGIN_EVENT_KIND`, `types.py::EventKind` |
| D56 | **A margin loan is drawn at accept and reconciled at the order's terminal state, so an unfilled order carries a real `DB` for at least one determination.** QĐ 87 Điều 2 khoản 8 values the order at market price **at trade time**, and a limit order has no trade price when it is funded — so the draw is sized on the reservation price. Measured under `hard` on the corpus: the 2022-09-23 determination reports `DB = 92,000,000` against `PV = 0` for an order that never filled, and the draw is repaid in full at the next advance. The ratio is still right (`AB` is the client's own money either way) and the encumbrance makes the cash unspendable, but the loan book shows a loan against no collateral for a session. Declared in `WIRING_PROVENANCE::loan_sized_on_reserve_price` | `equity_margin.py::gate`, `::_reconcile` |

**Found by the seven-scenario validation pass, 2026-08-27.** D60–D69 were found by running real
algorithms against the assembled simulator and auditing the result adversarially. D60–D66 are
**fixed**, each with a regression test that fails without the fix; D67–D69 are recorded and NOT
fixed, with the reason.

| # | Defect | Where |
|---|---|---|
| D60 | ~~**The derivatives funding gate admitted an order that breached on arrival.**~~ **FIXED 2026-08-27.** `reserve_for_order` tested `required > free_deposit` alone, and `free_deposit = balance − posted − resting` **excludes VM by construction**. So an account at utilisation 0.8876 with 11,237,608 of equity was admitted an order requiring 14,497,600 — more than its entire equity — and stood at 1.0326 and `FORCED` in the same instant, on a mark that had not moved. The gate a few lines above *refuses to open a position on a FORCED account*, so the method forbade a state and permitted the one action that creates it. The contradiction was visible inside one module at one instant: `transfer_out` refused to pay out 11,237,608 while this admitted a commitment of 14,497,600. **Fix:** the order must also clear `openable = balance × forced_close_utilisation − required`, the mirror of `transfer_out`'s bound, which includes VM. With VM zero and the threshold 1.00 the two bounds are arithmetically identical, so a well-funded account sees no change. Pinned by `test_deposit.py::test_an_opening_order_may_not_commit_what_a_withdrawal_may_not_pay_out` (+ an over-tightening guard). `test_deriv-margin.py::test_the_firms_first_rung_refuses_a_new_position_and_admits_an_offset` **had pinned the defect as expected behaviour** and is corrected | `deposit.py::reserve_for_order` |
| D61 | ~~**A margin call was opened in the event log and never closed.**~~ **FIXED 2026-08-27.** `_EVENT_FOR_MARGIN_STATUS` had no `OK` member, so `MarginMonitor.on_mark`'s clearance view — which it computes and returns — was dropped by `continue`. Found independently by `deriv-margin`, `expiry-overnight` and `order-cycle`. On the corpus a call fired 2022-10-03, was cured the same session, and the next thing the stream said was a *warning* three sessions later: a reader saw an unanswered call with an expired deadline followed by a de-escalation, and the `transfer_in` that paid for it carried no link back. **Fix:** `EventKind.MARGIN_CALL_CLEARED`, emitted with the discharged call's `cure_by` and `cured_at` so it joins to the `MARGIN_CALL` that opened it. Pinned by `test_exchange.py::test_a_cured_margin_call_is_closed_out_in_the_event_log` | `exchange.py::_mark_derivatives`, `types.py::EventKind` |
| D62 | ~~**`deposit_segregation` was structurally vacuous on every derivatives run.**~~ **FIXED 2026-08-27.** Found by four scenarios. Two independent causes: `journal.drain_deposit` built derivatives cash rows from `DepositEntry`, which carries no `charge_kind` and no `fill_id`, so the identity's join **matched nothing, ever**; and `_on_levy` never wrote `detail['pool']`, so the third clause was unreachable. One auditor proved it by relabelling all three of a run's derivatives charge rows `pool='securities'` and re-running — `passed=True, breaches=()`. The identity reported a pass having evaluated **0 of its 3 clauses**. **Fix:** `drain_deposit` re-attaches the itemisation from `session.charges()` by `(ts, total)`, consumed one-for-one; `_on_levy` writes the charge's own pool; a fourth clause reports a charge with no cash row at all, scoped by `RunLogs.charge_baseline` so a chained pair does not false-positive. Pinned by three tests in `test_identities.py` and by `test_expiry-overnight.py::test_every_derivatives_charge_row_is_joinable_to_the_charge_that_made_it`. `test_pair-trade.py::test_one_identity_passes_because_it_found_nothing_to_check` asked to be inverted when the join reached `[13, 13]`; it has been | `validation/journal.py`, `validation/identities.py` |
| D63 | ~~**No identity checked settlement completeness, and `unsettled_at_end()` under-reported.**~~ **FIXED 2026-08-27.** Two scenarios showed the cost: 46,072,026đ created as an obligation and never delivered, with the audit reporting *nine of nine held*; and a futures position carried past its last trading day with margin posted and 2,500,000đ owed, every identity passing. Separately `SettlementLog.unsettled_at_end()` keyed on a **set**, so two identical tranches from one order collapsed and one settlement discharged both — created 2, settled 1, reported **0**. **Fix:** a tenth identity `settlement_completeness` (due-and-undelivered, plus settled-before-DVP), and the key counts with multiplicity. On joining the suite it immediately found D64. Pinned by four tests in `test_identities.py` and two in `test_logs.py` | `validation/identities.py::settlement_completeness`, `validation/logs.py::unsettled_at_end` |
| D64 | ~~**A corporate action left one orphan and one ghost in the settlement log.**~~ **FIXED 2026-08-27.** `HoldingsLedger.apply_corporate_action` rescales an unsettled parcel in place and correctly preserves its `settles_at` — but the settlement log's economic key includes the quantity, so a parcel rescaled 1,500 → 2,025 produced a **creation row that never settled** and a **settlement row that was never created**. Found by D63's new identity on a run the scenario calls correct. **Fix:** `SettlementAction.TRANCHE_ADJUSTED`, written by a new journal wrapper, carrying the post-event quantity and `detail['quantity_before']` so it bridges the two keys. Pinned by `test_logs.py::test_a_rescaled_tranche_is_not_reported_as_an_orphan` and by the corporate-charges suite | `validation/journal.py::_on_corporate_action` |
| D65 | ~~**A fill was booked 8.31 units below the published floor, at a price off the quotation grid.**~~ **FIXED 2026-08-27.** `RestingOrderPolicy.SCALE` scaled a VIB sell resting at the published ceiling of 53.40 to `38.14285714285714285714285714` — 26 significant digits, off the 0.05 grid, and below the published floor of 46.45 — and the fill pass matched it, levying 14,418 exchange fee and 53,400 PIT on a 53,400,000 trade value the exchange could not have printed. `book.amend` deliberately does not re-run admission, so nothing downstream re-checked band, tick or lot. **Fix:** `order_tick` (separate from the reference's `tick`, resolving the scenario's own finding F-10 that one parameter served two incompatible roundings) and an optional `band`; a scaled price outside a supplied band falls back to `_cancel`, the idiom this branch already uses for a degenerate quantity. **A guard that could not be run is now NAMED in `RestingOrderOutcome.reason` rather than skipped silently.** Pinned by two tests in `test_corporate.py`. ⚠️ **The hole is only closed for a caller that supplies a band** — the engine cannot resolve one for itself, and `CorporateActionEngine` has no call site in `exchange.py` at all (see §16.3 #23) | `corporate.py::_scale` |
| D66 | ~~**One day of interest was forgiven on every equity-margin repayment.**~~ **FIXED 2026-08-27.** `_accrue` multiplies elapsed days by the loan's *current* principal, and it ran inside step 4 of `on_advance` — after step 2 had applied that day's settled proceeds. So a repayment landing earlier in the same pass retroactively cut the interest for a day the money had already been borrowed for. Measured: 2022-10-27 accrued 25,549 on a post-sweep principal of 69,079,147 for a day on which 92,000,000 was owed; correct ACT/365 is 34,027. Forgiven 8,478 / 11,119 / 9,032 across the three live arms. Trivial in đồng, but silent, systematic and always in the broker's disfavour. **Fix:** accrual is step 0, before anything in the pass can repay. Pinned by `test_equity-margin.py::test_the_debt_falls_by_exactly_the_settled_tranche`, which had asserted the defect (`principal < 70,000,000`) | `equity_margin.py::on_advance` |
| D67 | ~~**The cash log reported zero financing cost on a financed run.**~~ **FIXED 2026-08-27.** `CashLedger._repay` trues an advance up to its final interest at the settlement instant by writing straight to `_interest_accrued`, bypassing `accrue_interest` — the method the journal wraps. On a clock coarser than one day that top-up is the *whole* charge: a two-step run reported `by_movement()['advance_interest_accrued'] == 0` against a ledger carrying **143,503.39146**. `CashLog.by_movement()` calls itself "the itemisation an audit reads first", and it lied. Unreachable in the shipped arms because the runner steps twice a day; any weekly or event-driven clock hits it. **Fix:** `_on_cash_settle_due` diffs `Cash.interest_accrued` across the call and emits the residue. Pinned by `test_settlement.py::test_the_financing_cost_reaches_the_cash_log_on_a_coarse_clock` | `validation/journal.py::_on_cash_settle_due` |
| D68 | ~~**The derivatives final settlement was dated by when the caller polled.**~~ **FIXED 2026-08-27.** `_expiry_instant` exists specifically to pin the settlement **price** read to the expiry date and its docstring says so; the cash movement, the maturity tax and the `EXPIRY_SETTLED` event all used `ts`, the observing advance. One contract, one code, one price, two settlement *dates*: `2022-11-17T14:45` for a run that stepped to 14:50 on the expiry day, `2022-11-18T09:20` for the same position in a run whose next step was the next morning. A settlement log dated by observation cannot answer "was this settled on time". **Fix:** one `struck` instant for price, cash, charges and event; the same-date branch returns the venue close rather than `ts`, clamped to `ts` on an unresolved clock. Pinned by `test_exchange.py::test_the_settlement_is_dated_by_the_expiry_not_by_when_the_caller_polled` | `exchange.py::_expiry_instant`, `::_mark_derivatives` |
| D69 | ~~**A skipped identity was indistinguishable from a passing one.**~~ **FIXED 2026-08-27.** `encumbrance_zero` returns `passed=True, detail='not applicable'` whenever live orders exist. A measured run ending with one order live and **47,233,456đ of committed cash** printed `identities 9/9 held`. **Fix:** `IdentityResult.skipped`, counted separately by `ScenarioResult.summary()` and exposed as `skipped_identities`. `passed` stays `True` so a live order at the end does not fail an otherwise sound run; the headline no longer claims the check was made. Pinned by `test_identities.py::test_a_skipped_encumbrance_check_is_marked_skipped_not_merely_passed` | `validation/identities.py`, `validation/runner.py` |
| D70 | **Sub-đồng money in a rescaled reservation.** `corporate._scale` re-took a cash reservation at `enc.amount × qty_ratio × price_ratio` with no quantize; both ratios are exact Decimal quotients, so a measured run reported `committed_cash 43978090.45206159960258320914` and an available balance with 20 decimal places, on a currency with **no subunit**. `encumbrance_matches` held throughout because it compares the reservation to itself and both sides were equally fractional. **FIXED 2026-08-27**, rounded up (never under-reserve). Pinned by `test_corporate-charges.py::test_the_scaled_cash_reservation_grows_with_the_order` | `corporate.py::_scale` |

---

## 18. How to keep this document true

**Update this file in the same commit as any feature change.** An inventory that drifts
is worse than none, because it will be trusted — and the whole point of this document is
that the next session trusts it instead of asking.

Concretely:

1. **Adding a feature** — add a row to the right domain table with its file:line, a
   status from §2, and the citation. If the value is ours, add it to §3 *and* to the
   object's own `PROVENANCE` dict. The two must agree.
2. **Sourcing a previously assumed value** — move it out of §3, change the status from
   IMPLEMENTED + ASSUMED to IMPLEMENTED + SOURCED, and delete the `PROVENANCE` entry.
   Never leave a stale assumption note next to a now-sourced value.
3. **Fixing a defect in §17** — delete the row. Do not mark it fixed; the register is
   for live defects only.
4. **Deferring something** — it goes in §16 with the reason, in the same commit as the
   decision. A deferral without a recorded reason is a §16.3 gap, not a deferral.
5. **Before asking the author for any number** — grep §1, then §3, then the domain table.
   If it is in §1 the answer exists. If it is in §3 the answer is "we assumed it, and
   here is why"; ask only if the result turns on it.
6. **Line numbers drift.** They are a navigation aid, not a contract. If a `file:line`
   no longer points at what the row says, fix the line number — do not delete the row.
7. Keep the §3 count line at the bottom of §3 accurate; it is the fastest check that this
   file has been maintained.
8. **Every count in this file must state how it was counted.** A count with no command
   next to it cannot be re-verified and will be trusted anyway. The audit below found
   three wrong counts, two of them in §1.
9. **Never cite a traceability artefact that does not exist in the code.** The audit found
   one invented catalogue. A row that names an artefact must be greppable.
10. **A citation chain is worth only its last link.** The 80/90/100 margin ladder was
    graded HIGH here, in four modules and in the rulebook, on the chain QĐ 96 → QĐ 61 →
    QĐ 12 → QĐ 26. Nobody had read *any* of them; the chain was a chain of secondary
    summaries. When the final document was obtained it did not contain the rule. **Cite
    the article you read, name the edition you read it in, and if you have not read it,
    grade it UNVERIFIED and say which document would settle it.**
11. **Withdrawing a citation is not the same as disproving a rule.** When QĐ 26 turned out
    not to contain the ladder, the correct post-KRX statement became "misattributed" and
    the correct pre-KRX statement became "**UNVERIFIED, not disproven**" — because QĐ 61
    and QĐ 12 are still unread. Do not let the first conclusion contaminate the second.
    Overclaiming a *refutation* is as much a defect as overclaiming a source.

---

## 19. Verification log

### 2026-08-26 (later the same day) — QĐ 26/QĐ-HĐTV and Phụ lục 2 obtained and read

The two documents the audit above named as the reason to distrust §16.1 were obtained
from the author (thuvienphapluat.vn is Cloudflare-blocked to automated fetching) and read
in full: **QĐ 26/QĐ-HĐTV of 2025-04-16**, the derivatives clearing rulebook in force from
the KRX cutover and replacing QĐ 12/QĐ-HĐTV of 2023-08-10, and its **Phụ lục 2**, the
margin calculation methods.

**The one finding that changes what this file claims.**

| | Before | After |
|---|---|---|
| 80 / 90 / 100 applied to **margin** | IMPLEMENTED + SOURCED (shape), HIGH, "Article 13" | **IMPLEMENTED + ASSUMED.** Post-KRX **misattributed** — Điều 13 is binary `assets < MR` and carries no percentage. Pre-KRX **UNVERIFIED, not disproven** — QĐ 61 and QĐ 12 remain unread |
| 80 / 90 / 100 applied to **position limits** | not in this file | **Primary-sourced, QĐ 26 Điều 29**, and **NOT BUILT** (§11, §16.3 #20) |

Rows corrected as a consequence, all in this file: §1's headline anecdote (which *itself*
rested on the dead citation), §1's threshold / cure-window / maintenance-ratio / position-
limit rows plus three new §1 rows; §3A's A1–A3 and A5; §11's `MR = IM + VM`, ladder,
level-3, position-limit, withdrawal, `MarginMonitor`, portfolio-margining and post-KRX
rows, plus four new rows; §16.1 decisions 2, 4 and 5 in full; §16.2's portfolio-margining
reason; §16.3 #20–#22; §17 (D3 deleted as fixed, **D32–D35 added**); §18 rules 10–11.

**Rows that got *stronger*, not weaker** — the primary text confirms them:

- **Haircuts 5 / 30 / 40 %** move UNVERIFIED → sourced (Điều 9.1), including the
  structural claim that they are in the body rather than an unpublished appendix, and the
  01-working-day change notice (Điều 9.2). §6.3:600 of the rulebook is overturned for
  post-KRX only.
- **No maintenance margin ratio for derivatives** moves from reported to primary-sourced.
- **The withdrawal conditions** (§11) are QĐ 26 Điều 11.1 verbatim, all three.
- **The per-investor-account unit of assessment** that `account_margin_requirement`'s
  `TypeError` enforces is Điều 5.5 verbatim.
- **Level 3's behaviour** — no new positions, offsetting excepted — is Điều 13.2.a
  verbatim. Only its *trigger* is ours.
- **Intraday checkpoints 09h30 / 14h00 / 16h30** confirmed, and the "09:30 and 14:30"
  broker figure retired.

**What was refuted, beyond the ladder.** §16.1 decision 4's row 5 claimed the "3 vs 5
business day" conflict resolved as 3 days for margin and **5** for position limits. QĐ 26
gives **03 working days for both** (Điều 13.3.b, Điều 29.5). The 5-day figure came from a
LuatVietnam summary of the superseded edition and has no post-KRX counterpart.

**What was NOT done, deliberately.** No numeric default changed. `BrokerTerms`'
80/90/100 and the `NEXT_SESSION` cure window are exactly as they were; only the claims
around them moved. The post-KRX margin model was **not built** — that is an author
decision not yet taken — and no measurement was added. Three sourced divergences found
during the read (**D33** per-expiry position counting, **D34** exclusive-vs-inclusive cap,
**D35** narrow suspension test) were recorded rather than fixed, because each changes
behaviour.

**What this correction did not reach.** `types.py`, `margin.py` and
`exchanges/derivatives.py` still carry the withdrawn Article-13 attribution in prose —
logged as **D32** with exact anchors. No behaviour depends on it in any of the three.

**Suite:** `python -m pytest tests -q` → **1318 passed** (1314 before; four tests added,
all in `tests/market/session/test_deposit.py`, pinning the corrected `BrokerTerms.
PROVENANCE` text, the field/provenance cover, the regulated-vs-commercial cure-window
split, and the `assets == MR` boundary).

### 2026-08-26 — adversarially audited by four independent auditors

Briefed to break this
document rather than confirm it. One read the research behind §12 and
`equity-margin-spec.md` against primary mirrors; one hunted **false negatives** (features
in the code with no row here); one audited the **SOURCED vs ASSUMED** classification
against the rulebook and the five `PROVENANCE` dicts; one hunted **false positives**,
resolving every `file:line` in the file against live code and running the suite (1314
passed).

**Classes of error found and corrected:**

| Class | Examples corrected |
|---|---|
| **A fabricated traceability artefact** | §7 cited a catalogue "F-I1…F-I20" of INDETERMINATE sites in `fills.py`. **It has never existed** (`grep -r "F-I" src/ tests/ docs/` hits only this file) and the count was wrong. Restated with the true count (**18**) and the line numbers themselves |
| **Wrong counts, two of them in §1** | "12 dated charge rows" → **10 ids / 17 intervals**; "12 `_unsourced` rows" (twice) → **11**. Every count in this file now carries the command that reproduces it |
| **Confidence overstated** | `DAILY_TRADING_LIMIT` implied HIGH everywhere but one HSX window; in fact **HNX is LOW to 2022-03-30 and UPCoM to 2022-11-15**, both "text never retrieved". Also `TRADING_UNIT` and `TICK_SIZE`, which carried no caveat at all |
| **Uncited corrections overturning graded rows** | §16.1 Decisions 2 and 4 asserted article-level readings of **QĐ 26**, which the rulebook grades `medium (never read)`, against rows graded `high`. Each correction is now graded individually |
| **Claims about what the rulebook does or does not contain** | A32's "no dividend charge row exists anywhere in rulebook §12" (it does, §12.3:1112); §9's "Rulebook 9.1 has it" for the collateral fee (the dated rows are §8.2:816-817 and §12.5:1161); §8's "rulebook 5.1" for pre-funding (it is §5.2:489-490) |
| **Rows scoped too narrowly or too widely** | A66 (the calendar **prefers** the dated rulebook), A40/§15 (the adapter wins **only** on `Resolution.DAILY`), A68 ("both adapters" — only one), §5 gate 9 ("never fires" — it does), §6 `expire_due` (the session *does* sweep immediates) |
| **Missing capabilities, ~20 of them** | `Exchange.sustains` / `Viability` / `EXIT_BLOCKED`; **covered warrants are unroutable**; `SettlementResolver`'s three-tier chain; `assess_at_maturity`; `probabilistic_sweep`; `ChargeBasis`; the corporate-action audit subsystem; the pre-2022 settlement regime; buy-reservation gross-up; `_sweep_non_resting`; `AccountRef`; the `to_dict()` surface; **five `core/` modules that do not import** |

**What was re-derived rather than trusted:** every count in §1, §4 and §7; every
confidence grade quoted in §4; the `_charge_table` census (imported and counted); the
`_unsourced` census (grepped, with the `def` and one docstring mention excluded); the
five-`PROVENANCE`-dict cross-check against §3; and the specific runtime behaviours now
stated as verified — warrant band raises, coverage window not enforced at 2027,
`source=None` fails at gate 0, `GB05F2312` multiplier diverges by path, and the five
`core/` import failures. Four primary-source claims in §12 were re-fetched independently
(QĐ 87 Điều 11.3/11.4 and Điều 9.4; TT 120 Điều 9a's amendment annotation; the DNSE
ladder's `Gói` header; hoatieu.vn and dongduong.net truncation).

**What was checked and found already correct — do not re-audit these:** §9's ten charge
rows, value by value; ~~§11's `MR = IM + VM` chain and the Art. 13 80/90/100 provenance~~
— **struck the same day: both were wrong and four auditors passed them.** The auditor who
graded SOURCED vs ASSUMED checked the provenance *against the rulebook*, and the rulebook
carried the same unread citation chain, so the two agreed and neither was true. **This is
the single most instructive failure in this log**: internal consistency between two
documents that share a source is not corroboration. See the QĐ 26 entry above and §18
rules 10–11. §4's coverage-window row; the nine module line counts; the enum censuses (12 `RuleName`,
12 `EventKind`, 7 `OrderState`, 6 `AdmissionRule`, 4 `StatefulRule`); §12's greenfield
grep; and the assumed side of §3, which survived the adversarial test almost everywhere.

**One auditor finding was rejected.** It was reported that QĐ 87 Điều 9.4 lacks the
"one issuer" qualifier, making §12's *"≤ 5 % of that issuer's total listed shares"* a
reader's inference. Re-fetching the spec's own primary mirror on 2026-08-26 returns
*"…không được vượt quá 5% tổng số chứng khoán niêm yết **của một tổ chức niêm yết**"* —
the qualifier is in the text. §12 and the spec are left as written. Two auditors also
disagreed on the count of INDETERMINATE sites passing no `DataField` (four vs seven); both
were counting real things, and the row now states the distinction explicitly.

**How much to trust this file after the audit.** The `file:line` anchors and the counts
are the strongest part — every one has now been resolved or re-derived at least once. The
weakest parts are the ones that depend on documents nobody in this repository has read.
At the time of the audit those were **§16.1 Decisions 2 and 4** (QĐ 26) and **§12**
(commercial mirrors only); the QĐ 26 half was closed later the same day, and the audit's
instinct was right — that is exactly where the false HIGH grade was hiding. **What
remains unread, and is therefore where the next false grade will be:** QĐ 61/QĐ-VSD and
QĐ 12/QĐ-HĐTV (the *pre-KRX* regime, which is what the code implements and what every
corpus date falls in), QĐ 96/QĐ-VSD, and §12's commercial mirrors. If a row here disagrees
with the code, the code wins and §18 rule 6 applies.

---

### 2026-08-27 (later) — the execution-half repair

**The verdict this answers**, from an independent fidelity audit: *"An excellent Vietnamese
broker/clearing ACCOUNTING engine attached to an execution model that is not a simulation of
a market."* The accounting half was left alone. Four repairs landed, in this order, and the
suite went **2,198 → 2,308 passing, 0 failing** (the intermediate state was 2,242 passing / 5
failing while the four were mid-flight).

**The property that had to be restored, and how it was tested.** `indeterminate_report()`
returned `indeterminate = 0` on **every one** of the audited failures. An ignorance meter that
reads zero during known ignorance is worse than no meter, because a user trusts it. Every fix
below was checked against the question *would the meter have caught this?* — and where it
would not, the meter was changed. The honest predicate is now `RunIgnorance.is_clean`;
`indeterminate == 0` is documented as the one a reader reaches for and the one that was wrong.

| Repair | What it changed, measured |
|---|---|
| **Volume from the corpus** | `DataHubSource` became an `IntervalSource` serving `quote_dailyvolume`. `hard` stops being vacuous on the shipped adapter: `equity-margin`'s hard arm goes from 0 fills / no debt / ratio 1.000 for 31 sessions / no call, to **3 fills, 69,079,147đ of debt carried and 6 calls**. `soft` became a capped policy whose signature names the cap in force |
| **The encumbrance record could diverge from the ledger** | `corporate._scale` rebuilt the record instead of reading the ledger back. Measured 95,500,000 vs 95,485,000 on a cash leg and **1,000 vs 2,000 shares** on a share leg — the record *under*-reporting a commitment. The harness could not see it, because the totals-form identity is sampled where nothing is live; `OrderBookOfRecord.encumbrance_divergence` is the per-order form |
| **The meter's own blind spots** | `Component` (13 session seams) and `Blindness` (11 kinds), an exercise ledger, and `RunIgnorance`/`RunProvenance`. Six audited runs that all read `indeterminate=0, by_field={}` now read `is_clean=False` with the finding named |
| **The overnight margin layer** | `scenario_margin.py` — 2,989 lines, unit-tested, checked against TCBS's own worked example — had **zero call sites**. It is now `session/overnight.py`, called once per session after the close. See §11 |

**Task 2 — every scenario re-run.** All seven run to completion and the whole suite is green.
Three answers, and one of them is a finding:

1. *Does the derivatives-margin scenario show a different overnight requirement?* **It shows
   one at all**, which it never did: 19 requirements over 19 sessions, the last a determinate
   **zero** with `flat=True` because the contract cash-settled in the same advance. On that
   window the model is the pre-KRX continuous one and that is the **rulebook's** answer, not a
   fallback. Past the cutover the grid runs and the layers differ by 49,800,000đ.
2. *Do `hard` and `probabilistic` trade rather than returning INDETERMINATE everywhere?*
   **Where the close traded through the limit, yes** — that is the `equity-margin` and
   `order-cycle` result above. **Where the limit sits AT the close, no, and that is the
   finding**: `pair-trade`'s hard arm is unchanged at 2 of 3 evaluations INDETERMINATE, and
   the cause is not volume — it is `HardFillPolicy` refusing a continuous touch, which needs
   `quote_max`/`quote_min` to decide. Those are on disk and still not served. **The remaining
   fill gap is the day's extremes, and it is now the only one.**
3. *Does the capped `soft` fill less than the uncapped one did?* **Yes, and identically to
   `hard` at the same cap.** HPG buy 1,000: uncapped 1,000; at `max_participation=0.00001`
   both arms fill **300** (a `PARTIALLY_FILLED` row); at 0.000001 the cap floors below the lot
   and neither fills. The arms differ on *whether* an order filled and never on *how much*,
   which is the invariant `_CappedFillPolicy` exists to hold.

**Two conflicts handed back rather than resolved**, C-11 and C-12 in §16.4: the rulebook's
post-KRX row says the COMS formula could not be obtained while `scenario_margin.py`
implements it from the signed instrument; and the post-KRX requirement is smaller than the
pre-KRX one by exactly a variation margin this simulator never settles in cash.

---

### 2026-08-27 — the end-to-end validation pass

**What was done.** Seven scenarios were written and run against the real corpus, each
exercising something the simulator claims to do, and each was then handed to an
adversarial auditor briefed to break it rather than confirm it: `deriv-margin` (a
derivatives margin call and its cure), `equity-margin` (*ký quỹ* lending, calls and *bán
giải chấp*), `order-cycle` (29 lifecycle legs), `settlement` (T+2 across Tết and the
2022-08-29 regime change), `expiry-overnight` (futures expiry and overnight holding),
`pair-trade` (equity against derivatives in one session), `corporate-charges` (ex-dates,
rights, and the charge table).

**The headline, stated plainly.** The **money is right**. Across all seven scenarios the
cash conserves to the đồng in both pools, every movement traces to a logged cause,
encumbrance returns to exactly zero, and the two pools never touch except through matched
transfers. Six auditors rebuilt the balances independently of the identity suite — from
causes, not from the ledgers the logs are built from — and none found a đồng that appeared
or vanished without a row. **No accounting hole was found.**

**What was wrong was the audit trail and the timing**, and that is the more useful result:

- a margin call was opened and **never closed** in any log (D61);
- the identity that guards **segregation** passed on every derivatives run having
  evaluated **zero of its three clauses** (D62);
- there was **no settlement-completeness identity at all**, so 46m đồng of undelivered
  obligation and a futures position carried past its expiry both passed nine of nine
  (D63);
- a **corporate action** left an orphan and a ghost in the settlement log (D64);
- an opening order was admitted that put the account **past its own forced-close level in
  the same instant**, on a mark that had not moved (D60);
- the derivatives final settlement was **dated by when the caller polled** (D68).

**The pattern worth carrying forward.** Six of the eleven fixed defects were invisible to
a green suite *and* invisible to the identity suite, because the check that would have
caught them either did not exist, could not fire, or reported a skip as a pass. Three
tests were found **pinning defects as expected behaviour** and are corrected:
`test_deriv-margin.py::test_the_firms_first_rung…` asserted the admission hole was
`Accepted`; `test_pair-trade.py::test_one_identity_passes_because_it_found_nothing_to_check`
asserted the vacuous join and asked in its own words to be inverted when it was fixed;
`test_equity-margin.py::test_the_debt_falls_by_exactly_the_settled_tranche` asserted the
forgiven interest day. Standing rule 4 in its sharpest form: **a test can be worse than no
test**, because it makes the defect look decided.

**One auditor claim was refuted with measurement.** It was reported that
`quote_settlementprice` is a raw VN30 index tick series whose last entry is the window
maximum, and therefore that the scenario's `PUBLISHED_FINAL_SETTLEMENT = 972.78`
over-books by ~447,560đ with the wrong sign. Re-measured across all 18 days in the corpus:
the series' tick-to-tick increments **decay** through the window — first-quarter mean |Δp|
0.032 against last-quarter 0.013 on 2022-11-17, and 14 of 16 uncorrupted days show the
same shape — and the implied underlying reconstructed under the running-mean hypothesis is
smooth and in range. That is the running-mean signature. D23 and the handoff stand. The
*other* half of the same finding does survive and is now §16.4 item 8: the table is keyed
`VN30INDEX` on 14 of 18 days, so `expiry.py::_published`'s contract-code lookup misses
every index-keyed expiry.

**What was deliberately not fixed, and why.** Ten items, all in §16.4. The binding reason
in every case is the same: the fix would require choosing between readings the sources do
not settle — whether unsettled VM is a margin asset (T+1 derivatives settlement); what
price a marketable order gets given only a bar; trading days or calendar days for a
per-day fee; whether an unsourced broker term is subordinate to a sourced statutory
window. **The highest-value one is §16.4 item 4**: `quote_open`, `quote_high`, `quote_low`
and `quote_dailyvolume` are on disk and complete, `DataHubSource` reads none of them, and
`exchange.py:1790` declares them missing — an adapter gap misattributed to the corpus.
Closing it would fix the look-ahead in every scenario *and* the margin-timing errors
measured against the tick archive, and it moves every number in the repository, so it
wants its own pass.
