# Scenario catalogue

Twenty-seven scenarios for the Vietnamese exchange + broker simulator. Status 2026-08-27.
(Twenty-six until an honesty audit found that publish-checklist must-list item 2 was
exhibited by no scenario at all; **J27** was written to close that, and is the only
addition.)

Sources of truth, in precedence order:
`docs/reference/citable/vn-exchange-rulebook-2020-2026.md` (**434 dated rule rows**, plus 175
annotation rows — counted 2026-08-26 by script; this replaces the earlier hand count of
400/133, which the rulebook itself retracts in §1) ·
`docs/reference/equity-margin-spec.md` · `docs/reference/post-krx-margin-spec.md` ·
`docs/reference/FEATURES.md` (what is implemented) ·
`docs/reference/PUBLISH-CHECKLIST.md` (what blocks release).

---

## How to read this catalogue

**Each scenario is simultaneously a demo and a test.** The demo half shows a user what the
library does. The test half is *Broken looks like* — the specific wrong output you would
see if the mechanism underneath were modelled incorrectly. A scenario with no *Broken looks
like* is a feature tour; a scenario with one is a validation.

**The *Governing policy* line is what separates this from a feature tour.** Every mechanism
names the document, the article, the effective dates and a confidence grade — or it is
labelled, in the line itself, one of:

| Label | Meaning |
|---|---|
| **UNSOURCED** | No Vietnamese document states this at any date. We searched and found nothing. |
| **INFERRED** / **DERIVED** | Our arithmetic or our reading, built on top of sourced rows. The rows are cited; the step is ours. |
| **our modelling choice** | A design decision with no counterpart in any rule. |
| **sourced absence** | The document was read and the thing is *not in it*. A finding, not a gap. |
| **UNVERIFIED** | A rule that plausibly exists and that we could not read. Not disproven — unsupported. |
| **kind = *exchange (established empirically)*** | The rulebook is **silent** and the **corpus settles it**. The value is ours; the evidence is the data, not a document; the row prints the measurement that decided it. Distinct from *our modelling choice*, which has no evidence behind it either way, and from *sourced absence*, which is a finding about a document. Used at **J2**'s band-rounding tick key. *(It is **not** the shape the auction-cross substitution takes at **J14** — that is a plain *our modelling choice*, a stated approximation carrying no measurement; see J14.)* |

There is no third option and no unlabelled assertion. **Where it says *our modelling
choice*, that is a declaration, not an omission.** The value travels with the result:
`SessionProvenance` records the resolution, the citation and the confidence for every rule a
run touched, and `Pin` overrides record themselves as overrides (`RuleResolution.pinned =
True`, `citation = None` — because no document says what a counterfactual says).

**Confidence grades.** Two vocabularies appear in this catalogue, because two sources of
truth use different ones. Neither is translated into the other, and no grade is ever
promoted when a row is quoted here.

- **The rulebook's own** (everything except J5): `high` (primary text read), `medium`
  (corroborated but not gazetted-verified), `low` (single or secondary source). The rulebook
  also uses `UNVERIFIED` in the confidence column when the *value* itself is not established.
- **`equity-margin-spec.md`'s own** (J5, and only J5): **VERIFIED** (complete operative text
  read from a legal-database mirror), **REPORTED** (secondary source only — news, broker FAQ,
  fee schedule), **DERIVED** (our arithmetic, in no source read), **SILENT** (the rulebook
  does not address it; delegated to the broker contract or simply absent). *"VERIFIED" is not
  a stronger `high`* — it is a different scale, and it carries that spec's own reachability
  caveat (the primary-source hosts were behind bot-walls during that research).

**Counts.** **27 scenarios: 19 runnable · 6 partial · 2 blocked.** (J27 was added after the
honesty pass found that must-list item 2 was exhibited by no scenario at all — see the
must-list table below.) **The split moved on 2026-08-27 and both moves are recorded rather
than quietly applied:**
- **J21 left `blocked` for `partial`.** The must-list item that blocked it **landed** (see
  the table below). What remains is the two residuals the checklist's own RESOLVED entry
  states — injection-only construction, and depth from a dev extract — which is *exactly*
  the status **J9** already carries. **Two scenarios held back by one identical pair of
  residuals cannot carry two different grades**, and J9's was the right one.
- **J13 left `runnable` for `partial`.** Its *Runnable today* line has always read *"Yes for
  the CONVERSION on the equity venues. No for the SWEEP"*, and **a split answer is not a
  Yes.** This is the identical correction this document already made for **J12** at the
  bottom of this file, applied to the scenario that had the same defect and was missed.

**Neither of the two blocked scenarios is blocked by a publish-checklist must-list item.**
J14 and J7 are blocked by the **auction phase-carrying data path** — which **is now tracked
on the checklist as a SHOULD** (the checklist's *"A shipped source that carries an auction
phase"* item, added 2026-08-27).

> *Kept because the causation is the point, not because the defect is live:* when this
> catalogue was written that path was tracked in **no section of that file at all** — not
> MUST, not SHOULD, not DECLARABLE — while two catalogue scenarios named it as their blocker.
> **That finding is what caused the row to be added**, and the checklist records it as the
> third of the three rules it learned that day (*"'Blocked by' needs a row to point at"*).
> The auction path is now tracked on the checklist as a SHOULD; a catalogue that deleted the
> finding would erase the only evidence that the two documents check each other.

**The must-list, spelled out once.** This document says "must-list item 3" and "item 4" in
a dozen places. The numbers are `PUBLISH-CHECKLIST.md`'s, not ours, and they are **frozen** —
a landed item keeps its row and its number. This is what they are:

| # | Item | Checklist state | Exhibited by |
|---|---|---|---|
| **MUST #1** | **Order-book walk.** Without it *"fills happen at a single price with no depth"* | **LANDED 2026-08-27**, commit `c6b7ef6`; reasoning moved to RESOLVED. **Two residuals, and neither of them is "no depth"** — see below | **J13**'s sweep half and **J21**, both now *partial* on those residuals; **J9**'s staleness half |
| **MUST #2** | **Amendment re-runs encumbrance and admission** | Not started. Its citation and its defect statement **were both corrected** on 2026-08-27, in the checklist itself | **J27, and nothing else** |
| **MUST #5** | **The tick path must implement the stated close-as-ATC approximation.** On a tick run an ATC fill (or an LO carried into the cross) returns a stale pre-auction tick (`state.last`) instead of the published close the stated model uses. A **design-conformance** defect, not an error-size one | Not started; **added 2026-08-27**. Placed above #3/#4 on the checklist by fix priority — the number is an identity, not a rank | **J14** and **J7** (blocked); declared in the tick caveats of **J6, J10, J17, J20** |
| **MUST #3** | **Forced liquidation must EXECUTE, not just report** — `detail['executed']` is `False` on every one | Not started | J3, J19, **J4**, J10 |
| **MUST #4** | **Variation margin must settle in cash daily** — `settle_daily` is UNREACHABLE — no caller anywhere in `src/` | Not started | J3, J6, J18, J19, J26, J4, J10 |

**FIVE numbered must-list items, of which #1 has landed and four remain open (#2, #3, #4, #5).**
#5 was added on 2026-08-27, in the same pass as the auction SHOULD, and its rationale is
**design-conformance** — the tick path does not implement the stated close-as-ATC
approximation — not any error size.

**MUST #1's two residuals, because "landed" must not be read as "reachable from a config
file".** Verified against the code, not the commit message. (i) `build_fill_policy`
**refuses** the `book_walk` kind from a config block (`fills.py:2260-2276`) — deliberately,
because `FillPolicyConfig` carries no field for a book provider or a queue assumption and
*"defaulting either would be exactly the silent substitution this function exists to
refuse"*; the supported route is `ExchangeSession.build(..., fill_policy=BookWalkFillPolicy(
DepthSource(root), queue=OptimisticQueue(), ...))`. (ii) The depth data is a **dev extract,
not a shipped corpus** — a **window** limitation, *not* an absence of order-book sizes:
`/Users/nadan/algotrade-research/dataset/hermes-dev-extract` carries **1,390,914 size rows across four Parquet files** with
a `depth` column, and production carries 666M/590M. **Both residuals were already described
correctly in this document, under J21 and J9**; only the *status label* was stale, and it is
fixed here. *(Named by scenario, not by line number — the pointers this pass repaired were
all line numbers into files that had moved.)*

**Two corrections this catalogue owed the checklist — both now PAID, in the checklist, on
2026-08-27.** They are recorded here because the substance is still what J21 and J27 print,
and because a reader who finds the old wording quoted elsewhere needs to know it moved:
- **MUST #2's citation was wrong** — it attributed priority preservation to *"QĐ 352 Điều
  21.3"*, when QĐ 352 Điều 21 is the **lunch break** and "Điều 21.3" belongs to VNX QĐ
  22/2025. The checklist's **MUST #2 row** now opens *"This row's citation was wrong and is
  corrected here"* and prints the three real legs with their rulebook lines. **The three
  legs are also printed under J21**, which is where this catalogue states them.
- **MUST #2's defect statement was wrong at session level** — it said *"an amend-up escapes
  both"*. `ExchangeSession.amend` (`exchange.py:1625-1636`) **refuses** every amendment that
  could raise the requirement. The checklist now says so itself, and adds a **second, dated
  gap** this catalogue had already found independently: the session never passes the dated
  `priority_preserving` flag. **J27 states the corrected version and J21 carries its
  consequence.**

---

# A. Vietnamese mechanics that surprise outsiders

## J1 — Buy FPT, try to sell same day, sell after T+2

*The strategy* — Buy 1,000 FPT on day T. Attempt to sell on T (refused). Attempt again on
T+1 (refused). Sell on the first legal instant and print `sellable_from`.

*Mechanism exercised* — A bought lot is not in the depository account until VSDC settles it,
and the sell-side pre-funding rule obliges the securities company to refuse a sell of
securities not already there. A **broker-enforced statutory duty riding on a depository
clock** — two instruments, not one.

*Governing policy*
- Cycle length **T+2 in VSDC settlement business days** — VSD QĐ 211/QĐ-VSD (2015-12-18);
  QĐ 109/QĐ-VSD Điều 4(4) verbatim · 2016-01-01 → current · **high**
- First sellable instant **open of T+3** — QĐ 211/QĐ-VSD; settlement completes 15:30–16:00,
  after the close · 2016-01-01 → 2022-08-26 · **high**
- First sellable instant **13:00 on T+2**, not the T+2 morning — QĐ 109/QĐ-VSD Điều 4
  (signed 2022-08-19) · 2022-08-29 → current · **high**
- The refusal itself: sell only for securities **already available** in the depository
  account — TT 203/2015 Điều 7 → **TT 120/2020/TT-BTC Điều 7(3)** · 2016-07-01 → current ·
  **high**
- Post-2024 settlement clock **assumed unchanged; operative text unread** — VSDC QĐ
  48/QĐ-HĐTV, QĐ 39/QĐ-HĐTV · **medium**
- **Never "T+1.5" or "T+2.5"** — retail and press shorthand, in no gazetted document
  (**medium** that the shorthand is unsourced).
- The 2022-08-29 change moved the **time of day, not the cycle**. The cycle has been T+2
  since 2016-01-01. Depository settlement is 11:00–11:30 on T+2; the **13:00 deadline is a
  custodian-member obligation**, not the VSDC settlement moment (**high**) — and it is a
  deadline, not a guarantee (allocation ran to ~15:00 on 2026-02-27, **high**).

*Broken looks like* — The strategy sells shares it does not own for one to two days per name
and books a same-day round trip no Vietnamese cash account can execute. Every "buy the dip,
sell the bounce" result becomes unearned. The tell: a fill on T for a lot bought on T.

*Runnable today* — **Yes.** Refusal is `Rejected(UNSETTLED_HOLDING, binding_constraint=0)`
carrying `sellable_from`. Three declarations ride with it:
- A 2020–2022 run takes a **different rule**, not a different clock:
  `delivery_on_next_session_open=True`, first usable session is T+3's *open*.
- **A50** — daily bars are stamped midnight, so a 13:00 threshold is not met by the T+2 bar
  and `T+2 @ 13:00` behaves as **T+3**. Conservative, intended.
- **Doc conflict — SETTLED 2026-08-27, and it went A64's way.** `FEATURES.md` A64 said the
  default settlement calendar is `weekday-only-UNSOURCED` and *"every default run's
  settlement dates are wrong around Tết"*; `PUBLISH-CHECKLIST.md` RESOLVED said no calendar
  need ship because T+N over days-the-data-carries reproduces Announcement 4228/TB-VSDC.
  **The checklist's entry was the wrong one and has been corrected there** — it now opens
  *"This entry overstated its own result and is corrected here — `FEATURES.md` A64 was right
  and this section was wrong."* What survives on each side: a calendar **does not have to
  ship** (T+N over days-the-data-carries lands on the published answer, verified at three
  Tết closures), **and** that is **not resolved for the user**, because the
  days-the-data-carries path is **caller-supplied and is not the default** —
  `exchange.py:1331` returns `weekday_settlement_calendar()` when nothing is named, and a
  2026-02-12 trade then answers **T+2 = 2026-02-16 where VSDC settled 2026-02-23, five
  counted days the depository was shut**. The remaining work is a checklist **SHOULD**
  (*"Make the correct settlement calendar the default, or make the wrong one refuse"*).
  **J1 is the settlement demo and must still state which path it ran** — that requirement is
  unchanged and is the reason this entry stays rather than being deleted.

## J2 — Momentum chaser into a limit-UP lock

*The strategy* — A breakout rule buys strength. The name gaps to the ceiling and locks. The
strategy submits at the ceiling and gets nothing.

*Mechanism exercised* — Two refusals a reader will conflate, and separating them is the
scenario's job. **BAND_LIMIT**: the price is outside the band — illegal, a rule, rejected
regardless of the book. **BAND_LOCK**: the price is legal (at the ceiling) but no ask rests
at or below it — admissible and unfillable, a market fact, not a rule. Two separate ordered
admission rules in `exchanges/equity.py`.

*Governing policy*
- Ordinary band HSX **±7%** — QĐ 352 Điều 9.6 → VNX QĐ 17 Phụ lục III §1.3 → QĐ 22/2025
  §1.3 → QĐ 22/2026 §1.3; corpus-confirmed on 151,005 HOSE name-days · 2021-07-05 → current
  · **high**
- Same band, 2020-01-01 → 2021-07-04 — QĐ 67/QĐ-SGDHCM as amended by QĐ 462 and QĐ 894;
  **the band instrument was amended one day into the window and nobody has read it** · **low**
- HNX **±10%** · 2022-03-31 → current — VNX QĐ 17 Phụ lục III §2.3; QĐ 22/2026 §2.3;
  corpus-confirmed on 144,521/146,102 HNX name-days (98.99%) · **high**
- Same HNX band, **2020-01-01 → 2022-03-30** — HNX QĐ 653/QĐ-SGDHN (2018-10-12, eff.
  2018-11-05); **text never retrieved — the saved fetch is a Cloudflare interstitial, and no
  HNX band value is verified from 653 itself** · **low**
- UPCoM **±15%** · 2022-11-16 → current — VNX QĐ 34 Điều 18.1; QĐ 23/2025 Điều 18.1; QĐ
  23/2026 Điều 19.1 verbatim; corpus-confirmed on 301,732/412,041 UPCoM name-days · **high**
- Same UPCoM band, **2020-01-01 → 2022-11-15** — HNX QĐ 455/QĐ-SGDHN (2017-06-20); **text
  never retrieved** · **low**
- Ceiling arithmetic `ceiling = ref + ref × band`, rounded **DOWN** to the quotation unit —
  QĐ 352 Điều 9.1–9.2; QĐ 17 Điều 31.1–31.2 · **high**
- Which tick selects the rounding: the tick of the **resulting** band price, not the
  reference. **The rulebook is silent; the corpus settles it** — result-keyed 97.60% vs
  reference-keyed 95.06%, and on the 4,605 disagreeing rows 98.8% vs **0.0%** · kind =
  *exchange (established empirically)*
- Order priority: **price then time only. No size priority, no pro-rata** — QĐ 352 Điều 7,
  16; VNX QĐ 22/2025 Điều 20 · **high**
- **INFERRED** — that a limit-UP lock blocks **buys only** (selling at the ceiling is the one
  thing that can fill, because that is where every unfilled bid is queued). Follows from the
  band arithmetic plus price-then-time priority. **No Vietnamese article states it.**
- **UNSOURCED — our modelling choice** — the `LockEvidence` ladder (`TICK_BOOK` authoritative
  / `BAR_PROXY` inferred / `UNKNOWN` → INDETERMINATE). `FEATURES.md`: *"No Vietnamese rule
  governs lock evidence — the LockEvidence ladder is ours."* The marketable-into-a-lock
  question is a market fact; the **grading of the evidence** is a design shape.

*Broken looks like* — The strategy buys at the ceiling on days when nothing was on offer
there: a free fill in exactly the state where a real buyer sits at the back of a queue that
never clears. **The single most flattering error available to a momentum backtest.**

*Runnable today* — **Yes, with a measured over-assertion that must be published with it.** On
the shipped `DataHubSource` — **the adapter, which is outdated and slated for
reimplementation (author's decision, 2026-08-27); this is not a limitation of the design or
the corpus** — the lock is inferred from `close == ceiling` alone, which **over-asserts by
roughly 10×**. Measured, HSX 2022, 91,999 ticker-days with volume: 3,726
days have `close == ceiling`, of which only **365 (9.8%)** have `open == high == low ==
close`; on the 3,361 wrongly called buy-locked the day's low averages **6.87% below the
ceiling** — nearly the whole band. Worked case: **HPG 2022-11-16, close 13.35 = ceiling, low
11.80, 34.9m shares, and a buy at the ceiling refused.** The strict source
(`full_bar_lock`, requiring `open == high == low == close` on the band) lives in
`validation/`, **not in `src/plutus` — it does not ship**, so a library user gets the proxy
unless they supply `quote_open`/`quote_max`/`quote_min` — **fields that are on disk and
withheld by the adapter, not fields the corpus lacks**. One item CLOSED since an earlier
draft: `BAND_LOCK` used to refuse **at entry only** with no fill-time counterpart (a
checklist SHOULD); **that SHOULD was closed on 2026-08-27 by commit `c6b7ef6`**, as a side
effect of the order-book walk — a book locked at the ceiling has no asks below it, so a
marketable buy finds nothing and fills nothing, and the entry/fill asymmetry is gone. **Do
not publish J2 with that asymmetry still listed as open.**

## J11 — Floor-lock on the exit: a stop-loss that cannot fill

*The strategy* — A stop-loss on a name that gaps to the floor and locks. The user wants out;
nobody is bidding.

*Mechanism exercised* — The mirror of J2 with a sharper edge: **there is no order type in
Vietnam that will get you out at any price.**

*Governing policy*
- Floor arithmetic `floor = ref − ref × band`, rounded **UP** — QĐ 352 Điều 9.1–9.2 ·
  2021-07-05 → current · **high**
- Degenerate case: adjusted floor ≤ 0 ⇒ floor **= the reference price**, not zero and not one
  tick — QĐ 352 Điều 9.5; QĐ 17 Điều 31.4; QĐ 22/2025 Điều 30.4; QĐ 34 Điều 18.6 · **high**
- **No synthetic market-at-floor order exists in Vietnam at any date** — negative finding
  across all four rulebooks · **sourced absence**, **high**
- Corollary in our own code: `core/order.py`'s `MARKET = "MKT"` with "sell at floor for
  guaranteed match" semantics **matches no Vietnamese order type at any date** — not HOSE MP,
  not MTL · **high**
- **UPCoM has no escape at all**: LO only, no market order of any kind, no ATO/ATC, no PLO,
  whole window — MBS UPCoM 2024-10-14 §4; ASEANSC UPCoM §3 · **high**
- The nearest legal instrument is MTL/MP, which sweeps and then **rests one tick beyond the
  last match, capped at the floor**, and is **cancelled at entry if no opposite limit order
  exists** — a floor lock is precisely the state where there is no opposite limit order.
  **Dated and graded, because J11 is in the launch subset and this was the only citation
  bullet on the page carrying neither** (the caveat rides with the row wherever it is
  quoted — J13 states it in full):
  - **HSX, 2020-01-01 → 2025-05-04** — MP, the pre-KRX ancestor with identical economics —
    **QĐ 352 Điều 14.2(a)–(đ)** · **high** (`low` for the 2020-01-01 → 2021-07-04 leg,
    where no text of that era has been read)
  - **HNX + HNXDS, 2025-05-05 → current** — **VNX QĐ 22/2025 Điều 17.2(b)** verbatim; QĐ
    22/2026 Điều 19.2 identical · **high**
  - **HNX + HNXDS, 2020-01-01 → 2025-05-04** — **the pre-KRX HNX instrument has never been
    obtained**; carried by continuity and by the secondary **ASEANSC HNX §2.3** sheet. The
    rulebook calls the missing derivatives template *"the single most important missing
    derivatives document"* (`:782`). **Do not quote QĐ 22/2025 for this leg** — it is an
    instrument effective 2025-05-05.
  - **UPCoM: the question does not arise** — UPCoM is LO-only at every date, so there is no
    MTL/MP to reach for at all.
- Same **INFERRED** one-sidedness and same **UNSOURCED** `LockEvidence` ladder as J2.

*Broken looks like* — Stop-losses execute at the floor on locked days. **The most common
Vietnamese backtest error, and it makes risk management look free.**

*Runnable today* — **Yes**, with J2's evidence caveat. `_legal_here` enforces order-type
legality by date and venue, and `OrderBookOfRecord.accept` **raises** on an `MKT` — so an MKT
reaching the book is a caller bug, not a market event.

## J12 — MOK vs MAK on the same signal

*The strategy* — One signal, two submissions on HNX or HNXDS: fill-or-kill against
immediate-or-cancel. Report what each returns.

*Mechanism exercised* — Both are market orders, both continuous-only, neither ever rests.
**MOK** cancels entirely unless fillable in full at entry; **MAK** keeps whatever fills at
entry and kills the remainder at once.

*Governing policy*
- MOK / MAK semantics as above — **ASEANSC HNX §2.3; MBS VN30F §3.2** (broker rule sheets:
  **high confidence, secondary citation, not a gazetted article**) · HNX + HNXDS only ·
  2020-01-01 → current
- Legal types HNX: continuous LO, MTL, MOK, MAK; ATC LO + ATC; post-close PLO; **no ATO** —
  ASEANSC HNX §2.1/§2.3; SHS 2025; SSI · **high**
- Legal types HNXDS: auctions LO + ATO/ATC; continuous LO, MTL, MOK, MAK; **unchanged across
  KRX** — VNX QĐ 20 Điều 22 and QĐ 21 Điều 22 list identically · **high**
- Legal types HSX 2020-01-01 → 2025-05-04: LO, MP, ATO, ATC — **no MTL/MOK/MAK** — QĐ 352
  Điều 14, 15.4 · **high from 2021-07-05 / low for the 2020 leg**
- HSX post-KRX: LO, MTL, ATO, ATC; MP withdrawn, MOK/MAK **not** introduced — HOSE regulation
  2025-04-26 §5.2, but VNX QĐ 22 still defines MP alongside MTL/MOK/MAK and HOSE's Phụ lục III
  order-type list is unobtained · **medium**. Whether MOK/MAK exist on HOSE post-KRX is
  **UNVERIFIED** (**low**).
- Market order with no opposite order: cancelled immediately at entry — MBS VN30F sheets,
  pre- and post-KRX §3 · **high**
- **The venue trap is the scenario's point.** J12 **must run on HNX or HNXDS.** Running it on
  HSX demonstrates an order type that venue has never accepted.

*Broken looks like* — MOK and MAK become indistinguishable, and a fill-or-kill sizing strategy
silently takes partial fills it was designed to refuse: the difference between "the whole
block or nothing" and "whatever is there".

*Runnable today* — **Partial. Two deviations must be declared, not glossed.**
- **Declared deviation, decided one interval late**: `submit()` is synchronous with no
  matching engine behind it, so an MOK is decided at the first interval that evaluates it
  rather than at entry. One of two declared deviations from the interface contract.
- **GAP — the no-opposite-limit-order cancellation is not enforced.**
  `ExpiryTrigger.NO_OPPOSITE_ORDER` exists and is legal in the TIF table, but **nothing in
  `src/plutus` ever raises it**. On a daily bar there is no book to observe, so it cannot be.
  State the clause as **unmodelled**. *(**Restated 2026-08-27**: a book now **does** exist to
  observe — `BookWalkFillPolicy` over `DepthSource`, landed in `c6b7ef6` — so the reason has
  moved from *"no book exists"* to *"no book is on the default path, and nothing raises the
  trigger even when one is injected."* The clause is still unmodelled; the excuse is
  narrower, and a narrower excuse is the honest one.)*
- Built and correct: `TimeInForce.FILL_OR_KILL` / `IMMEDIATE_OR_CANCEL`; a partially filled
  MOK **raises** ("not a partial fill, a contradiction"); `NOT_FILLABLE_IN_FULL` /
  `IMMEDIATE_REMAINDER`; MOK reservations cannot leak overnight.
- Policy note: `hard` **never fills MTL/MOK/MAK** by design. A no-fill under `hard` is the
  policy speaking, not the market.

## J13 — MTL residue conversion

*The strategy* — Submit an MTL larger than the visible opposite side. Watch the remainder
become a resting LO one tick beyond the last matched price. **The conversion is what J13
demonstrates. The sweep is not — see *Runnable today*: on the default path there is no book
to sweep, and the strategy line must not promise one.**

*Mechanism exercised* — MTL walks the book from the best opposite price; the unfilled residue
**converts to a resting LO one tick beyond the last matched price** (buy +1, sell −1),
**capped at ceiling/floor** when the last match was already at the band; **cancelled at entry
if no opposite limit order exists**.

*Governing policy*

**The MTL row is SPLIT BY DATE, and the split is the whole lesson of this scenario.** An
earlier draft graded one row `2020-01-01 → current · high` on an instrument effective
**2025-05-05**, and then thirteen lines later declared the same interval **UNVERIFIED
between two readings**. A row cannot be `high` for 2020-01-01 → current and UNVERIFIED for
2020-01-01 → 2025-05-04 at the same time. **The repair invents nothing** — it is the same
date-split **J2** already applies to the HNX and UPCoM bands, and the open conflict is
attached to the leg it actually lives on.

- **MTL semantics · HNX + HNXDS · 2025-05-05 → current · high** — **VNX QĐ 22/2025 Điều
  17.2(b) verbatim**; **QĐ 22/2026 Điều 19.2 identical** (rulebook `:175`). Residue → LO at
  last matched **±1 tick**, capped at ceiling/floor; cancelled at entry if no opposite limit
  order exists. **Two primary instruments stand behind this leg, not one** — an earlier
  draft called QĐ 22/2025 *"the only primary instrument"* and the rulebook row names QĐ
  22/2026 Điều 19.2 alongside it. Both are post-cutover, which is exactly why they cannot
  carry the leg below.
- **MTL semantics · HNX + HNXDS · 2020-01-01 → 2025-05-04 · the pre-KRX HNX/HNXDS
  instrument has never been obtained** — carried by **continuity** and by the secondary
  **ASEANSC HNX §2.3** broker sheet, not by a gazetted text of that era. The rulebook calls
  the missing document *"the single most important missing derivatives document"* (`:782`).
  **This is the leg the open conflict below sits on**, and the two facts are the same fact:
  the reason we cannot settle the conflict is the reason we cannot grade this leg `high`.
  - **OPEN CONFLICT INSIDE THE RULEBOOK — do not read past it.** The third reading,
    *"exactly the last matched price"*, is **not settled** for this leg. The rulebook
    asserts it in one place and rejects it in another, both at **high**, and this catalogue
    does not pick a side:
    - §2.3 (rulebook `:177`), **high**: *"A third reading ('exactly the last matched price',
      older HNX material) is rejected … QĐ 22/2025 Điều 17.2(b) resolves it"* — i.e. ±1 tick
      for the whole 2020-01-01 → current interval.
    - §10, KRX delta #7 (rulebook `:1158`), **high**: *"Derivatives MTL residual repricing |
      Before (to 2025-05-04): Residual → LO at the **last matched price** | After (from
      2025-05-05): Residual → LO at last matched **±1 tick**, capped at ceiling/floor |
      HNXDS"* — i.e. the "rejected" reading is the pre-KRX rule on derivatives.
    - The two cannot both be right for HNXDS before 2025-05-05. **Settling it needs the
      pre-KRX HNX/HNXDS instrument itself** — QĐ 22/2025 cannot speak for 2020–2025, and
      §2.3's own resolution cites it doing precisely that. Until then, an HNXDS residual
      dated before 2025-05-05 is **UNVERIFIED between the two readings**, and our code takes
      the ±1-tick side by default — a **declared choice**, one tick wide, on every pre-KRX
      derivatives market order.
- HSX post-KRX: same, but *the no-opposite-order cancellation is carried over from the MP rule
  and is **not restated** in HOSE's post-KRX text* · **medium**
- MP, the pre-KRX ancestor with identical economics — **QĐ 352 Điều 14.2(a)–(đ)** · HSX ·
  2020-01-01 → 2025-05-04 · **high from 2021-07-05** (QĐ 352 is effective 2021-07-05,
  rulebook `:857`); **`low` for the 2020-01-01 → 2021-07-04 sub-leg, where no gazetted text
  of that era has been read** — the same date-split **J11, J12 and J2** carry. *(From
  2021-07-05 this is the one leg of the pre-cutover window that **does** have a gazetted text
  of its era — which is why J13's demonstrable half is the equity conversion and not the
  derivatives one; the 2020 sub-leg is carried by continuity like the rest.)*
- **Residual, rival readings**: adopted **last matched ±1 tick, capped at ceiling/floor**.
  Two earlier extractions read "±1 tick" and "at the ceiling/floor" as rival rules; **the
  gazetted sentence contains both clauses** · **high** — *for the leg the gazetted sentence
  governs*, i.e. 2025-05-05 → current.
- **CONFLICT, applied not resolved (A51)** — derivatives residual: the equity rule and MBS say
  last matched ±1 tick; **Vietcap handbook §8 says best bid +1 / best ask −1**. These differ
  whenever the book is not tight, and the difference lands on the resting price after **every**
  derivatives market order · **low** · rulebook Open Question #18
- **MP → MTL is a mnemonic swap, not a semantic one** (KRX delta #6, **medium**). Our code
  holds the line: both mnemonics map to one `OrderType`; only `legal_order_mnemonics`
  distinguishes the eras.

*Broken looks like* — The residue rests at the wrong price after every market order: one
tick, on every sweep, compounding through the run. On HNXDS it could be wrong by the whole
spread.

*Runnable today* — **PARTIAL. Yes for the CONVERSION on the equity venues; the SWEEP is
demonstrable only off the default path.** A split answer is not a Yes, and J13 is **counted
as partial** at the top of this document for exactly that reason — the identical correction
already made for J12. It stays in the launch subset, because the conversion *is* what the
scenario is for and the strategy line says so.

`_residual_price` implements last-matched ±1 tick capped at ceiling/floor, taking
`record.fills[-1].price` else `state.last`. A residue that cannot be priced is **left live
rather than converted at a guess**, and dies at session end as a day order. Four
declarations required:
- **MUST #1 (order-book walk) has LANDED — and the sweep half still does not run on the
  default path.** *(Commit `c6b7ef6`, 2026-08-27; the checklist's old *"fills happen at a
  single price with no depth"* is retired to its RESOLVED section and must not be quoted as
  current.)* The **default** residual pricing is unchanged and is still one point:
  `exchange.py:3357-3359` — `last = record.fills[-1].price if record.fills else None`,
  falling back to `state.last` — **no ladder, no multi-level walk**. An MTL "larger than the
  visible opposite side" still has no visible opposite side to be larger than *there*. What
  changed is that a real sweep now **exists** and is reachable: `BookWalkFillPolicy` fills
  each tranche at the **resting** level's own price, injected via
  `ExchangeSession.build(..., fill_policy=...)` over `DepthSource`. So the honest split is
  now **three-way, not two-way**: J13 demonstrates **where the residue rests** on the wired
  corpus; it demonstrates **what the sweep took on the way there** only in a
  caller-constructed run over dev-extract depth; and it demonstrates neither from a config
  block, because `build_fill_policy` refuses `book_walk` (`fills.py:2260-2276`). **Say which
  of the three produced the number.**
- **A51** — the derivatives residual CONFLICT, applied and declared, not resolved.
- The **same `NO_OPPOSITE_ORDER` gap as J12** — the clause is sourced, its enum exists, and
  nothing raises it.
- Because J13 is in the launch subset and is sold as the clearest demonstration of what
  "dated and cited" buys: **the open rulebook conflict on the pre-KRX derivatives residual
  (§2.3 `:177` vs §10 `:1158`, both `high`), printed on the page, not resolved silently.** A
  scenario whose whole point is citation may not hide a citation that contradicts itself.

## J14 — ATO vs a marketable LO into the same auction

*The strategy* — Two orders into one opening cross: an ATO and a marketable LO. Same
quantity, same side. Report what each has after the cross.

*Mechanism exercised* — Both clear at **one price for everyone**. The difference is the
remainder: the ATO's unfilled remainder is auto-cancelled **at the cross** and never carries;
the LO is a **day order** that survives and carries into continuous. One shot versus a second
chance.

*Governing policy*
- **LO time in force** — day order; may be entered in continuous **and** auction phases; an
  unfilled continuous LO is **carried into the following auction and participates in the
  cross**; dies at the end of the last matching phase — **QĐ 352 Điều 14.1(c), 17.2** ·
  2020-01-01 → current · **high**
- **ATO/ATC time in force** — enterable only inside their own auction window; **unfilled
  remainder auto-cancelled at the cross**; never rest, never carry — **QĐ 352 Điều 14.3(b),
  14.4(b)**; MBS VN30F §3.3–3.4 · **high**
- Type priority: ATO/ATC matched **ahead of all limit orders, unconditionally** — QĐ 352 Điều
  14.3(c), 14.4(c); VNX QĐ 17, **article number disputed** between Điều 17 điểm c/d and Điều
  21 khoản 2(c)/(d) — pin to PDF before publication · **high (rule) / low (article number)**
- At KRX, **narrowly abolished**: an ATO/ATC no longer outranks a **ceiling-buy or floor-sell
  LO entered earlier in time**; it still ranks ahead of limit orders priced **inside** the
  band. The broader gloss is **rejected** — VNX QĐ 22/2026 Điều 22; HOSE 2025-04-26 §5.3–5.4 ·
  2025-05-05 → current · **high**
- Imputed ATO price: for an ATO **buy** the text really does say *"giá bán cao nhất của bên đối
  ứng"* (the **highest** opposite ask) — this is what makes an ATO price-insensitive inside the
  band, and it is **not a transcription error** — QĐ 352 Điều 14.3(a) · **high**
- Auctions are locked: no amend, no cancel while an auction runs. **Unchanged across the whole
  window** — several write-ups present this as a KRX novelty; it is not — QĐ 352 Điều 17.1;
  VNX QĐ 17 Điều 22; QĐ 22/2025 Điều 21 · **high**
- Which types each auction accepts — **each venue with its own instrument, because the grades
  differ by venue and by date**:
  - **HSX** opening LO+ATO, closing LO+ATC — QĐ 352 Điều 14, 15.4 · 2020-01-01 → 2025-05-04 ·
    **high from 2021-07-05 (verbatim) / low for the 2020-01-01 → 2021-07-04 leg (carried by
    continuity, no text of that era read)**. Post-KRX HSX is LO, MTL, ATO, ATC — HOSE
    regulation 2025-04-26 §5.2 · **medium**.
  - **HNX** no ATO at all; ATC auction takes LO + ATC — ASEANSC HNX §2.1, §2.3; SHS 2025;
    SSI · 2020-01-01 → current · **high**
  - **UPCoM** neither auction, LO only, whole window — MBS UPCoM sheet 2024-10-14 §4;
    ASEANSC UPCoM §3 · 2020-01-01 → current · **high**
  - **HNXDS** auctions LO + ATO/ATC — VNX QĐ 20 Điều 22 and QĐ 21 Điều 22, which list
    identically · 2020-01-01 → current · **high**
- **UNVERIFIED — allocation AT the marginal price** for the ATO/ATC cross. Not a sourced
  absence: no rulebook was read to the point of establishing silence. Partly answered for the
  HNX post-close phase only (pro-rata by entered volume, ASEANSC HNX sheet) · **low**

*Broken looks like* — An ATO that "carries" makes the opening auction a free option, and the
LO/ATO distinction — the reason a Vietnamese trader picks one over the other — disappears
entirely.

*Runnable today* — **No. Blocked.** This is the largest gap in Group A. **The blocker is now
tracked on the checklist as a SHOULD** (the checklist's *"A shipped source that carries an
auction phase"* item, added 2026-08-27) — it is **not** a must-list item, and J14 is not
blocked by one. The auction fill is a **deliberate, stated approximation**, and that is all
it needs to be. The statement below is the one every other mention of the auction fill in
this document defers to:

> **The auction fill is BUILT. Its price is a DELIBERATE, STATED APPROXIMATION — our
> modelling choice, not a Vietnamese rule, and it carries NO measurement.**
> `fills.auction_fill_price` returns `interval.open` in an ATO phase and `interval.close`
> in an ATC phase. The justification is one sentence and there is no number in it: **we
> cannot trust the tick data inside the ATO/ATC auction window, so we take the day's
> PUBLISHED CLOSE as the ATC outcome and the day's PUBLISHED OPEN as the ATO outcome — both
> already in the database.** It carries **no Vietnamese citation and never did**. This is
> **design §8, Convention 1**, and it is a **data substitution for the clearing algorithm,
> not an implementation of it** — honestly noted, nothing more.
>
> **Do not cite QĐ 352 Điều 6.2(a) or Điều 6.3 for it.** Both govern something else.
> **Điều 6.2(a)–(d)** is the four-step algorithm that *derives* a cross price from a book
> (maximise executable volume, then full-fill on one side, then nearest to the last match,
> then the reference) — rulebook `:190`, `high`; `fills.py:88-89` cites it for the *fill
> decision* ("a strictly-through order in an auction is a rule-guaranteed full fill"), which
> is a different proposition and is correctly cited there. **Điều 6.3 is the CONTINUOUS
> session rule** — *"trade at the resting (passive) order's price, not the aggressor's"*,
> rulebook `:188`, `high` — and `fills.py:59` and `book_walk.py:31-32` both cite it as
> exactly that. **Nothing in any rulebook states that the published open or close IS the
> auction clearing price.**
>
> **WHAT THE RULEBOOK DOES SAY ABOUT THE CLOSE, VERBATIM — and it is not an auction rule.**
> QĐ 352 **Điều 2.5**: *"Giá đóng cửa là giá thực hiện tại lần khớp lệnh cuối cùng trong
> ngày giao dịch."* The close is the price of the day's **LAST MATCH** — phase-agnostic,
> with no mention of an auction anywhere in the sentence. **The tell is the fallback**: it
> triggers on *no execution all day* (*"không có giá thực hiện trong ngày giao dịch"* →
> previous close carries forward), **not on "no cross"**. A drafter describing an auction
> would have written the no-cross case. Rulebook `:334`, **high**, carried into VNX QĐ 17
> Điều 3.17. From **2025-05-05**, QĐ 22/2025 Điều 3.17 narrows it to the last **round-lot**
> match and changes the fallback to the day's **opening reference** (`:335`, **high**).
>
> **AND NOTHING DEFINES AN OPENING PRICE AT ALL.** *"giá mở cửa"* appears **NOWHERE in the
> rulebook** — no instrument, at any venue, on any date, defines an opening price, and
> nothing consumes one, because **the next-day reference is the *close*** (QĐ 352 Điều
> 10.1). `interval.open` is a **vendor construct** at every venue on every date, not a
> published market fact we are substituting for a computed one. Confidence on this absence:
> **medium** — deliberately *not* `high`, and the reason for the grade is the honest part:
> **it is an absence over our assembled rulebook, not over the gazette.** 434 dated rows are
> a large sample of Vietnamese trading regulation; they are not all of it.
>
> **The substitution is a modelling choice, and its reasonableness is qualitative, not a
> measured result.** On the equity venues the published close is the day's last match (Điều
> 2.5), so it is a fair stand-in for the ATC outcome. **The open is the weaker half** — HNX
> and UPCoM run no opening auction at all, and a thin HOSE name often has none either, so an
> ATO result there can be a price for an auction that did not happen. State that asymmetry in
> words next to any auction result; **do not attach a number to it.**
>
> **The honest one-sentence form, and the one to publish**: *nothing in Vietnamese exchange
> regulation says the published close IS the ATC cross, and nothing defines an opening price
> at all.* We adopt the published open/close as **our modelling choice — a deliberate, stated
> approximation, no number attached** — and the venue/date asymmetry above rides in words
> next to any result that came out of an auction.
>
> **Three venue conditions under which the substitution is wrong**, and
> `auction_fill_price` performs **no venue check** — it keys on the interval's declared
> phase alone:
> 1. **The close is not *defined as* the ATC cross** — it is the last match, per Điều 2.5
>    above, and on a no-trade session the **previous close carries forward** (`:334`,
>    `high`); from 2025-05-05 the last **round-lot** match, else the day's opening reference
>    (`:335`, `high`). **None of those three readings is "the ATC cross price."** The
>    published close *stands in for* the cross; it is not *defined as* it, and that gap is the
>    whole of why this stays a modelling choice.
> 2. **On HNX a closing auction with only ATC orders resting produces NO PRICE AT ALL** —
>    *"Đợt khớp lệnh định kỳ xác định giá đóng cửa sẽ không xác định được giá khớp lệnh nếu
>    chỉ có lệnh ATC trên sổ lệnh"* (rulebook `:201`, `medium`). Substituting `interval.close`
>    there manufactures a print the venue never made.
> 3. **HNX has no opening auction and no ATO at any date**, so `interval.open` on HNX is a
>    **continuous** print. UPCoM has neither auction. This is the same asymmetry the
>    qualitative note above reports from the other side.
>
> What would make this a sourced rule rather than a modelling choice: a rulebook row
> establishing the identity of the published open/close with the auction clearing price per
> venue. There is none, so it stays our modelling choice — a stated approximation, honestly
> noted.

What is missing for J14 is three separate things, and none of them is the fill price:
1. **No shipped data path ever puts the session into an auction phase — on the DAILY path.**
   `ExchangeSession._phase` returns `CONTINUOUS` on every `Resolution.DAILY` bar (a daily bar
   is stamped midnight, so the rulebook would answer `PRE_OPEN` for every bar and reject
   every one), and `_legal_here` then refuses an ATO because
   `legal_order_types(HSX, CONTINUOUS)` does not contain it. **This is an ADAPTER limitation
   and must be attributed to the adapter by name**: `DataHubSource` hardcodes
   `session=SessionPhase.CONTINUOUS` at `datahub.py:436`, and **DataHub is outdated and is
   slated for reimplementation** (author's decision, 2026-08-27). It is not a limitation of
   the design, of the rulebook or of the corpus — the seam works, and the one source that
   stamps a real phase, `validation/scenarios/bars.py::PhasedBarSource`, builds real ATO/ATC
   intervals — it simply **lives in `validation/` and does not ship**. Separately,
   `quote_open` is on disk and `DataHubSource` **declares that it will not serve it**
   (`WITHHELD`), so `auction_fill_price` returns `None` there. **On disk and not served is
   an adapter policy, and it is reversible.**
2. **LIVE DEFECT — the tick path does not implement the stated close-as-ATC approximation.**
   This is not a missing feature; it is a wrong number in front of a user today, and it is
   stated here rather than in a footnote because J14 is the scenario that owns the auction
   fill. It is a **design-conformance** defect: the stated model is close-as-ATC, and on a
   tick run the code returns something else. Found by reading the code on 2026-08-27, not
   inferred:
   - At 14:35 the session **correctly** re-stamps the state with the rulebook phase:
     `exchange.py:2841-2843` computes `phase = self._phase(record.venue,
     observed=state.session)` and passes `replace(state, session=phase)` into
     `_interval_for`. The phase really is `closing_auction`. **That half is right.**
   - `TickSource` is **not** an `IntervalSource`, so `_interval_for` falls through to
     synthesis at **`exchange.py:2442-2451`**. The synthesis sets `close = state.last` and
     adds `DataField.CLOSE` to `missing` **only when `state.last` is `None`**.
   - `auction_fill_price` (`fills.py:608-636`) then returns `interval.close`, under a
     docstring promising *"the published open (ATO phase) or close (ATC phase)"*.
   - Continuous matching stops at **14:30** and the cross publishes at **14:45**, so
     `state.last` at 14:35 is a **pre-auction print**. **So the tick path returns a stale
     pre-auction tick where the stated model says it should return the published close** — it
     does not implement the close-as-ATC approximation at all. The defect is stated as
     design-conformance, not as an error size.
   - **The fix is one condition, and its correctness is proved by the other half of the same
     function.** `DataField.OPEN` is **always** in `missing` at `exchange.py:2442-2443`, so
     the opening-auction branch **already returns INDETERMINATE correctly** — the right
     behaviour is already in the file, applied to the other field. **Make an ATC fill return
     the published close, or INDETERMINATE if the close is absent** — i.e. make `CLOSE` behave
     like `OPEN` when the interval is **synthesised** and the phase is an auction.
   - **The DAILY path never fires this at all**: `DataHubSource` stamps every bar
     `CONTINUOUS` (`datahub.py:436`) and `_auction_phase` requires `phase is
     interval.session`. **This is a tick-run defect specifically**, which is why it survived
     a document that mostly reasons about daily bars.
   - It is carried on the publish checklist as a **MUST** (#5), added in the same 2026-08-27
     pass as this entry; its rationale is design-conformance — the tick path violates the
     stated model — not an error-size percentage. `PUBLISH-CHECKLIST.md` is the authority on
     its number.
3. **Allocation at the marginal price** — **UNVERIFIED** (`low`), which deliberately returns
   `INDETERMINATE` rather than guessing. **Not a sourced absence**: the label table above
   makes the two mutually exclusive, and no rulebook was read to the point of establishing
   that the rule is absent. It is a rule that plausibly exists and that we could not read.

Also **D10**: `expires_at_boundary` documents an ATO dying at "its own cross" but the code
keys on `tif` and fires at the end of **any** auction phase.

## J15 — Sell and redeploy on ứng trước tiền bán

*The strategy* — Sell on T, immediately redeploy the proceeds under the sale-advance product,
carry the daily interest, and let the advance be repaid out of the T+2 settlement.

*Mechanism exercised* — A filled sale on T creates a receivable that does not settle until
T+2. The advance credits that receivable to buying power immediately, charges interest per day
advanced, and is recovered automatically out of the settlement proceeds.

*Governing policy — the statutory half*
- A named, licensable service: a brokerage-licensed securities company may *"cung cấp hoặc phối
  hợp với các tổ chức tín dụng cung cấp dịch vụ ứng trước tiền bán chứng khoán"*, requiring
  **prior written SSC approval** — **Luật Chứng khoán 54/2019/QH14 Điều 86(1)(b), confirmed word
  for word** · 2021-01-01 → current · **high**
- Why it is not a broker loan: a securities company may not lend money or securities except for
  margin lending and error-correction/ETF securities lending, so the advance must sit against
  the client's **own receivable** — TT 121/2020/TT-BTC Điều 27, **read in summary form only,
  not verbatim** · **low**
- The split, stated: **the permission to offer the product is statutory; the price and the cap
  are broker commercial terms** · **high**

*Governing policy — the broker half*
- **Self-priced, no statutory cap** (absent from both TT 128/2018 and TT 102/2021, so it falls
  under self-priced services, Điều 3.5). `fee = amount advanced × days advanced × daily rate` ·
  **high (structure); the numeric range is NOT sourced**
- 2021 snapshot, competitor-published, treat as indicative: Pinetree 0.025%/day · TCBS 0.029 ·
  VSCS 0.0329 (min 30,000đ) · Mirae/VCBS/FPTS 0.033 · SSI 0.0389 (min 50,000đ) · HSC 0.04 ·
  VNDIRECT 0.05 · **medium**. 2024–2026 typically 0.035–0.04%/day · **medium**
- **Cap — UNVERIFIED.** "Up to 100% of net proceeds after fees and PIT" is the common
  description, **not a sourced figure; mark it an assumption** · **low**
- **ANNUALISATION BASIS CONFLICT**, recorded and unresolved: 0.025–0.05%/day annualised as
  "9–18% p.a." is **×360**, while DSC's "0.0356%/day = 13%/yr" is **×365**. *"A sweep configured
  from these rows will be internally inconsistent by ~1.4%. Declare one basis explicitly."*
  The rulebook recommends **365**, recorded in config · **high (that the conflict exists)**.
  Also unresolved: whether the stated minima (30,000đ, 50,000đ) are đồng or thousand-đồng.
- **"T+2.5"** for advance recovery **is not a legal term** · **medium**

*Broken looks like* — Either the advance is free (turnover overstated, and the interest that
eats a high-frequency edge disappears) or it is absent (turnover understated by half). Both
directions are large.

*Runnable today* — **Yes.** `AdvanceTerms`, `CashLedger.request_advance` / `advanceable`,
`SecuritiesAccount.request_advance`, config key `advance_sale_proceeds`; with
`auto_register=True` the standing registration draws on each sale. Declarations that must be
restated on the scenario page:
- **A4** — default `advance_on_sale_daily_rate = 0.00031/day` **matches no observed firm** and
  is not the rulebook's recommended 0.00035/day. **our modelling choice.**
- **A7** — `max_advanceable_fraction = 1` is the unsourced 100%.
- **A8** — `annualisation_basis = 365` is **declared**; never read during accrual
  (`amount × rate × days` over actual calendar days) but is the basis for
  `from_annual_rate` / `annual_rate`, which exist as a round trip so a printed headline rate
  cannot silently sit on a different basis.
- **A12** accrual stops at the tranche's settlement instant; **A13** allocation across tranches
  is settlement-order, cheapest-interest-first — **a declared choice with no source**; **A15**
  headroom floors ROUND_DOWN so a cap is never exceeded by its own rounding.
- **Citation defect to fix before publishing (D28)** — `ledgers.py:628`, `:726` and `:1221`
  cite **"rulebook 8.4"**; **§8 runs 8.1–8.3, so that section does not exist**. All three land
  in **§5.2**: `:628` on Luật Chứng khoán 54/2019 Điều 86(1)(b) (**high**), `:726` and `:1221`
  on TT 121/2020 Điều 27 (**low**, read in summary only). The self-priced / no-statutory-cap
  claim beside it is §8.3 (**high (structure)**) and is already cited correctly at `:630`.
  This is the citation J15 would print.
- **Advance interest is reported and never charged** (see J24) — an advance is free in every
  balance reported.

## J16 — Capital turnover under T+2

*The strategy* — Run one rule for a month and count the round trips. Then run it again with
the advance enabled. Report the turnover of each.

*Mechanism exercised* — What caps turnover is not commission but the settlement cycle, and it
caps the **share** leg and the **cash** leg on two different clocks. The advance relaxes the
cash leg only.

*Governing policy*
- The binding fact: *"Cash and securities settle on the same cycle and at the same instant …
  Sell-then-rebuy on the same day is therefore not possible on settled cash alone"* — DVP at the
  depository plus a single broker allocation deadline; QĐ 109 Điều 4 · 2022-08-29 → current ·
  **high**
- The load-bearing backtest constraint: *"Across the entire window, no short sale and no
  intraday round trip of the same shares is admissible on the cash market … Turnover is capped
  by the settlement cycle unless the advance facility is modelled and charged for."* —
  TT 120/2020 Điều 7(3), Điều 11; TT 203/2015 · 2020-01-01 → current · **high**
- Day trading (T+0) is **legally provided for and never operational** — no VSDC SBL system —
  TT 120/2020 Điều 10, 10(2)(d) · **high**
- Short selling: **not available at any point 2020-01-01 → 2026-08-25.** The framework exists
  (TT 203/2015 Điều 11 → TT 120/2020 Điều 11) and was **never operationalised**. Say that, not
  "prohibited" · **high**
- "Lướt T0" is achieved by selling an existing position and rebuying with an advance —
  economically similar, legally a different thing, **and it costs the advance fee** · **high**
- Round-trip cost — a **worked example, not a floor** (rulebook §12.8): HSX equity, 2023,
  10,000 sh @ 25,500đ (notional 255,000,000đ) ⇒ **≈1,670,400đ = 0.33% of one-way notional**.
  It must be broken into its regulated and its commercial half, because **1,275,000đ of the
  1,670,400đ — 76% — is broker commission and may legally be zero**:
  - Exchange trading fee **0.027%** per leg, 68,850đ × 2 — TT 101/2021/TT-BTC Biểu giá Phần A
    Mục II điểm 4 · 2022-01-01 → 2025-01-09 · **high**
  - **PIT 0.1% of gross proceeds, sell leg only**, 255,000đ — TT 92/2015/TT-BTC Điều 16
    amending TT 111/2013 Điều 11.2(a)(b) · 2015-01-01 → 2026-06-30 · **high (value) / medium
    (citation — the named instruments appear in none of the sources actually opened)**
  - Custody 10,000 × 0.27đ = 2,700đ, if held across a month end — TT 101/2021 Phần A Mục III
    điểm 13 (continuous from TT 14/2020) · 2020-03-19 → current · **high**
  - **Broker commission 2 legs × 0.25% = 1,275,000đ — a BROKER TERM, not a regulated
    amount.** The statute sets only a ceiling, and **there is no floor at any date inside the
    window**: max **0.5%**, *"the floor is REMOVED — a broker may charge anything up to the
    cap, including zero"* — TT 128/2018/TT-BTC Biểu giá Phần A điểm 2a, Điều 3 · 2019-02-15 →
    2021-12-31 · **high**; then max **0.45%**, still no floor — TT 102/2021/TT-BTC ·
    2022-01-01 → current · **medium** (*"DOWNGRADED: TT 102/2021 could not be opened from any
    mirror"* — and 2022-01-01 → current is the leg this 2023 example actually sits on). Floor
    removal is what enabled the 2020–2021 zero-fee war (DNSE, Pinetree). Our 0.25% is the
    sweep default drawn from broker schedules (typical retail 0.10–0.35%, tiered on **daily**
    value per account · **medium**), not a rule.
  - **So the regulated floor of a round trip is 395,400đ = 0.155% of one-way notional**, and
    everything above it is a commercial choice a strategy can shop for. Do not print 0.33%
    as a legal minimum.
  - The shape claim survives either way: **sell-side PIT alone (0.1%) is ~4× the two-sided
    exchange fee (0.054%)**.
- **INFERRED** — the arithmetic that without the advance capital cycles buy T → sellable T+2
  13:00 → cash spendable T+4 13:00, and with it buy T → sellable T+2 13:00 → sell T+2 → cash
  same day. Our derivation from the two sourced legs. **No Vietnamese document states a
  round-trips-per-month figure**; the number is a measurement of our model, not a rule.
- **Unmodelled rule with unresolved scope** — TT 120/2020 Điều 7 also prohibits placing buy and
  sell orders for the same security within the same matching session, and *"whether the ban is
  per matching session or per trading day was not resolved, and it changes admission logic"* ·
  **medium**, carve-outs and clause number **UNVERIFIED**. **No implementation exists anywhere
  in `src/plutus/market/`.** Do not pick a reading.

*Broken looks like* — The strategy compounds at a rate no Vietnamese account can achieve.
**The quietest and most damaging of Group A**, because nothing in the output looks wrong — the
equity curve is simply on a clock that does not exist.

*Runnable today* — **Yes for the mechanism.** The turnover **number** carries three declared
movers: **A4** (the rate matching no observed firm), **A7** (the unsourced 100% cap), and
**A50** (midnight-stamped bars make `T+2 @ 13:00` behave as **T+3**, so a daily run reports
turnover *lower* than reality — the conservative direction, and the reason must be printed
next to the figure).

---

# B. Dated-rule demonstrations — the project's distinctive claim

These three are the reason the rulebook is dated rather than current. Each runs the *same
order* against *two dates* and gets two different answers. Use `Pin` to run the other side's
rulebook as a control: it records itself as an override (`RuleResolution.pinned = True`,
`citation = None`, *"because no document says what a counterfactual says — which is how a
provenance record tells a pinned run from a lie"*). Never edit a table to make the point.

## J17 — Straddle the HOSE round-lot change, 2021-01-04

*The strategy* — Submit an identical 50-share HOSE order on 2020-12-31 and on 2021-01-05.
Legal on the first date, rejected on the second. Then the sharper version: on 2021-01-05 the
50-share order is a legal **odd lot with nowhere to trade**.

*Mechanism exercised* — Order quantity must be an exact multiple of the venue's trading unit,
**resolved at the order's own date**; and the odd-lot range is *derived* from the lot, so it
moves when the lot moves.

*Governing policy*
- Round lot HSX **10** units (shares, closed-end funds, ETFs, covered warrants) · 2020-01-01 →
  2021-01-03 — QĐ 67/QĐ-SGDHCM (2018-03-02) as it stood before QĐ 894, **never read**; the
  10→100 step corroborated by press and broker notices · **medium**. *The corroboration
  attaches to the other instrument*: QĐ 352 Điều 2's repeal clause confirms that **QĐ
  894**/QĐ-SGDHCM of 2020-12-30 exists and amends exactly the đơn vị giao dịch instrument —
  it says nothing about QĐ 67's contents, and nothing confirms the value 10 itself.
- Round lot HSX **100** units, max **500,000** units per round-lot matching order · 2021-01-04
  → current — QĐ 894/QĐ-SGDHCM (2020-12-30), applied 2021-01-04; restated in **QĐ 352 Điều
  8.1**; **QĐ 17 Phụ lục III §1.1** · **high (value) / medium (citation — the cited URL is a
  VnEconomy article, not the decision)**
- **The asymmetry J17 must state**: the "legal before" leg rests on an instrument nobody has
  opened, and the "rejected after" leg has a high-confidence value with a news-sourced decision
  citation. **Neither side is a gazetted read.**
- Odd lot = *"giao dịch có số lượng chứng khoán nhỏ hơn một đơn vị giao dịch"*, a derived range
  — HOSE **1–9** to 2021-01-03, **1–99** from 2021-01-04; HNX/UPCoM 1–99 throughout — QĐ 17
  Điều 3.20; QĐ 22/2025 Điều 3.20; QĐ 34 Điều 16.3 · **high**. *"A simulator that hard-codes
  1–99 gets the pre-2021 HOSE window wrong twice over, in the lot and in the odd-lot range."*
- HOSE had **no on-exchange odd-lot mechanism at all** 2021-01-04 → 2022-03-30 — grepping QĐ
  352 for "lô lẻ" returns **zero hits** · **medium**. **UNVERIFIED**: whether 1–9 odd lots were
  genuinely matchable on HOSE during 2020, and the instrument that suspended odd-lot trading was
  never found.
- **UNVERIFIED** — maximum order size and block threshold for HSX, 2020-01-01 → 2021-01-03.
  **Do not claim the 500,000 cap existed before 2021-01-04.**
- The further raise to **1,000 was proposed in 2021 and never adopted** · **high**
- Round lot and tick grid are **NOT KRX deltas** · **medium**

*Broken looks like* — A date-blind lot: the identical order is accepted on **both** dates or
rejected on **both**. The tell is `AdmissionRule.ROUND_LOT` returning the same `unit` on
2020-12-31 and 2021-01-05.

*Runnable today* — **Yes, cleanly.** `HSX_ROUND_LOT_RAISED = date(2021,1,4)`;
`get_trading_unit(exchange_code, on)`; admission resolved at `state.ts.date()`, with an
instrument spec overriding the venue default. The rulebook's `TRADING_UNIT` row is
citation-only and deliberately **delegates the value** rather than duplicating the table. One
constraint, and it now has two reasons rather than one: **keep the orders in continuous
trading.** An ATO/ATC-routed J17 would (i) run into the auction phase-carrying blocker on a
daily run and demonstrate the wrong thing, and (ii) on a **tick** run hit the live ATC defect
in J14 — the synthesised interval's `close` is a **pre-auction** print served as *"the
published close"*, so the tick path does not implement the stated close-as-ATC approximation
(publish-checklist MUST #5, design-conformance). A round-lot straddle routed through an
auction would report a date-boundary result contaminated by an unrelated auction-fill error
the scenario is not about.

## J18 — Straddle the VSD initial-margin change, 2022-12-15

*The strategy* — Open the same 1-lot VN30F position on 2022-12-14 and on 2022-12-15. Report
the deposit requirement on each side. Same position, more deposit, no price move.

*Mechanism exercised* — The VSDC initial-margin ratio is a **dated series**, and
`IM = ratio × contracts × price × multiplier` is recomputed on the **current** price. It is not
a fixed fraction of the entry notional.

*Governing policy*
- **10%** · 2017-08-10 → 2018-07-17 — Mẫu HĐTL Chỉ số VN30 row 19; Nhân Dân · **high**
- **13%** · 2018-07-18 → 2022-12-14 — VSD announcement dated 2018-07-13, effective 2018-07-18,
  with SSC approval; Nhân Dân; PHS/Vietstock 2019; MBS sheet. **The value in force at the start
  of our window** · **high**
- **17%** · **2022-12-15** → current — VSD notice of 2022-12-12, effective 2022-12-15, unanimous
  SSC agreement, on a periodic VaR recalculation; permissible VaR-derived band on the assessment
  date **8.4%–18.3%** · **high**
- **THE CITATION POINT — no `quyết định` number exists.** The 10→13→17% changes were issued as
  **thông báo** (notices) under a standing delegation in the clearing rulebook. *"Citing
  'Quyết định XX/QĐ-VSD set margin to 17%' would be citing something that does not exist."*
  VSDC announcement 199445 is a notice with an xlsx attachment and no decision number · **high**
- **17.5% matches nothing at any date** — an old `0.175` in our code was a transcription slip for
  `0.17`, now corrected · **high**
- IM formula `IM = ratio × contracts × price × multiplier`, `price` = latest matched price
  in-session or the **DSP** at end of day; no new IM for offsetting trades on the same trading
  account — VSDC "Thông tin về ký quỹ" §II.1(a), §IV.1; QĐ 61 Điều 5 as summarised · 2017-05-01
  → current · **high**
- **Publication is PER CONTRACT**, keyed on (product name, 9-char code, ISIN), with
  time-to-maturity a stated VSD input. *"The correct data structure is
  `(contract_code, effective_date) → ratio`, not a scalar."* Our table is **date-keyed only and
  says so in its own comment** — **our modelling choice**, declared · **high**
- Cadence: re-determined on the **1st, 10th and 20th** of each month, published **≥2 business
  days** ahead — pre-KRX VSDC page §II.1(d)–(h) citing QĐ 96/QĐ-VSD Phụ lục 02; post-KRX **QĐ 26
  Điều 5.1.1(b) verbatim** · **high**. Mechanism carries across the KRX boundary unchanged.
- Observation window: pre-KRX "at least 90 trading days"; post-KRX Phụ lục 2 mục 1.3 conflicts
  **internally, 120 vs 250**, both minima, **UNVERIFIED which binds**. **Do not state a window.**
- **Continuity is verified-at-sampled-dates only** · **medium** — confirmed at effective
  2024-08-16, 2024-11-22, 2024-12-20, 2025-12-19 and 2026-08-21. Notices effective 2026-02-23 /
  03-20 / 04-17 / 05-22 / 06-19 / 07-17 were **not opened**, and nothing between 2022-12-15 and
  2024-08-16 was sampled. Phrase the interval that way.
- **Do not attach a maintenance-margin call level.** Vietnam publishes **no maintenance margin
  ratio at any date 2020–2026**. Post-KRX this is a primary-sourced negative: `ký quỹ duy trì`,
  `ký quỹ biến đổi` and `thời gian thực` occur **zero times** in QĐ 26 and zero times in Phụ lục 2
  · **sourced absence**, **high**

*Broken looks like* — The same position shows the same requirement on 2022-12-14 and
2022-12-15 (date-blind scalar), or shows 17.5% on either side (the transcription slip).
Correct behaviour at VN30 ≈ 1,000 points: **13,000,000đ → 17,000,000đ per contract, +30.8%
deposit requirement with zero price movement.**

*Runnable today* — **Yes, if scoped to the straddle.** The IM leg runs live through
`deposit.py::account_margin_requirement`, and 2022-12-15 sits inside the pre-KRX regime, so
`MR = IM + VM` is the correct composition for it. **Must-list item 4 (VM never settles in
cash) bites if the position is held across sessions** — `settle_daily` is UNREACHABLE — no caller anywhere in `src/` — so VM is measured from `average_entry` for the life of the position (**A60**): VM =
cumulative since-entry unrealised loss, not the day's adverse move. **Enter-and-report on each
side of the boundary and it does not bite; hold and it does.** Items 1, 2 and 3 do not bite.

## J19 — Straddle the KRX cutover, 2025-05-05: a different margin MODEL on each side

*The strategy* — The same VN30F position, the same account, on 2025-05-02 and 2025-05-06.
Report the requirement each regime computes, and print every assumption that separates them.

*Mechanism exercised* — Pre- and post-KRX `MR` are **not the same object**. Composition, unit
of assessment, marking variable, timing and monitoring all change at once.

*Governing policy*
- **The effective date is itself INFERRED. State this first.** QĐ 26 Điều 2 verbatim: effective
  *"kể từ ngày Hệ thống công nghệ thông tin của gói thầu … chính thức vận hành"*. VNX QĐ 21 uses
  the same construction. **Mechanism verbatim; the calendar date 2025-05-05 is INFERRED** —
  **high (instrument) / medium (calendar date)**. J19's entire premise is the date; do not
  present it as gazetted.
- **BEFORE** · 2017-05-01 → 2025-05-04 — `MR = IM + VM` for the portfolio on each **individual
  investor trading account**, computed **in-session** — VSDC "Thông tin về ký quỹ" §II.4(a) ·
  **high (2017-05-01 → 2022-05-31) / medium (2022-06-01 → 2025-05-04)**, because VSDC's page was
  last updated 2021-01-18 and cannot be a reproduction of QĐ 61 (2022-05-16) or QĐ 12 (2023-08-10)
- **AFTER** · 2025-05-05 → current — `MR = Max(ΣPgm, 0)` summed over **underlying-asset groups**,
  `Pgm = Max((Rm + Sm + Dm), MM)` — **Phụ lục 2 mục 6.1/6.2 verbatim**; QĐ 26 Điều 5.5 · **high**
  - **`Dm` is IN the gazetted formula and is ZERO for everything this publication covers.**
    `Dm` is *ký quỹ chuyển giao*, **delivery margin, government-bond futures only** —
    rulebook `:724`, **high**, and that `high` is the **scope** statement (Phụ lục 2 mục
    4.1(a)(b) verbatim, GB-futures-only). **Our own code entry is graded LOW and the pointer
    must carry its own grade, not `:724`'s**: `rulebook.py:1394-1401` is an
    `_unsourced(...)` entry with `confidence=Confidence.LOW`, on
    `document='VSDC margin appendix records the index-future delivery-margin column as "-"'`,
    whose note repeats the scope — *"the index-future series must not be applied to them"* —
    and states outright that the GB **value is not published**. So: **the scope is `high`,
    our GB delivery-margin row is `low`, and a reader following the code pointer must land
    on the `low`.** Neither grade is in doubt for the number J19 reports, because **for VN30F
    and every other index future, `Dm = 0`**, so
    `Pgm = Max((Rm + Sm), MM)` is the whole of what J19 computes. The term is printed verbatim
    because **the formula is the gazetted one and truncating it would be a silent edit of a
    primary source** — not because bonds are in scope. **GB futures are out of scope** and
    make the overnight layer INDETERMINATE by design
    (`OvernightGap.GOVERNMENT_BOND_DEFERRED`); Phụ lục 8 and the cheapest-to-deliver method
    are unobtained and uncited.
  - **`Max(…, MM)` is a FLOOR, not an add-on.**
  - **Variation margin is NOT a component of MR.** Four summands and VM is not among them;
    `ký quỹ biến đổi` occurs **zero times** in both texts. Position P&L is a **separate daily cash
    settlement** under Điều 20.1, *"bằng tiền vào ngày làm việc liền kề sau ngày VSDC thông báo"*,
    netted to one obligation per clearing member (Điều 20.2(b)). **`MR = IM + VM` is a pre-KRX
    statement and must not be applied after 2025-05-04** · **high**
  - **Unit of assessment drops a level**: the account portfolio → the **group within the account**.
  - **`Rm` is marked on the UNDERLYING's close**, not the futures price (`S` = *"Giá đóng cửa của
    tài sản cơ sở tại ngày xác định"*). *"A simulator that scenario-shocks the futures price is
    modelling the wrong variable."* · **high**
- Timing: pre-KRX margin lodged with VSDC **before** an order could be placed and recomputed
  intraday; post-KRX margin held at the clearing member, VSDC computes *"sau khi kết thúc phiên
  giao dịch"* and notifies **"Chậm nhất 16h30 ngày giao dịch"**, member tops up **"trước 09h30
  ngày giao dịch liền kề tiếp theo"** — QĐ 26 Điều 5.5, Điều 13.1 · **high**
- **No intraday recomputation post-KRX** — Điều 13.2(a): the 09h30 / 14h00 checkpoints compare
  live asset balances against *"mức ký quỹ yêu cầu xác định tại **ngày làm việc liền trước**"* ·
  **high**
- **Monitoring goes from a ratio to a binary.** Post-KRX Điều 13 contains **no percentage of any
  kind**: violation is `giá trị tài sản ký quỹ < giá trị ký quỹ yêu cầu`, cure is `≥`. Three
  checkpoints **09h30 / 14h00 / 16h30** (Điều 13.2 a/b/c); 09h30 only **adds** breaches, 14h00
  only **releases** them, so **the post-KRX regime cannot issue an intraday margin call at all**
  · **high**
- **The 80/90/100 ladder is NOT a margin rule. Do not cite Điều 13 for it.** Post-KRX the
  attribution is **definitively wrong**; pre-KRX it is **UNVERIFIED, not disproven** (the chain
  QĐ 96 → QĐ 61 → QĐ 12 → QĐ 26 is broken at its final link and the two middle links have never
  been read) · **low**. The 80/90/100 that **is** in QĐ 26 is **Điều 29, the position limit in
  contracts** (see J3). QĐ 26 does not abolish the concept — *"vi phạm tỷ lệ sử dụng tài sản ký
  quỹ"* appears **exactly once**, at Điều 30 khoản 3, as a named account state, never defined and
  never given a percentage · **high**. **Three distinct 80%s that must not merge**: the level-1
  margin warning (**low**, pre-KRX only); Điều 29's level-1 **position** warning (**high**,
  post-KRX); Điều 8.1's `x` = *"tỷ lệ ký quỹ bằng tiền tối thiểu (80%)"*, the minimum **cash**
  proportion (**high**, continuous across the cutover).
- **INFERRED, low — the scenario price formula.** Phụ lục 2 mục 1.2 prints
  `Sk = S0 x (1 + tỷ lệ ký quỹ ban đầu/10)` in all 21 rows, which is **degenerate** (no `k` on
  the RHS; the grid collapses). Our reconstruction **`Sk = S0 × (1 + k × r/10)`** reproduces the
  S−10…S+10 columns exactly and is almost certainly a PDF-extraction drop — **but it is OURS.**
- **UNVERIFIED, each stated separately**: how `OA` reduces `Rm` (`Rm = |min Lk| − OA` is our
  reading; neither QĐ 26 Điều 5.1.1 nor Phụ lục 2 writes the combining arithmetic or whether it
  floors at zero) · the equation turning VaR into the IM ratio (mục 1.3(c) defines `n` and omits
  the equation; a √n scaling is *the guess we do not record*) · the VaR observation window (120 vs
  250, internally conflicting) · `Psr`'s observation window · which contract supplies `B` and `S`
  for groups of 3+ · whether `MM`'s `P` is net or gross · the liquidity test behind `MM`'s
  mean/median switch · Điều 8.1's collateral valuation **formula** (variables read, equation lost
  in extraction) · group selection order (*"probably unknowable — it is an administrative act"*;
  a simulator must treat groups as an **input table**).
- Haircuts **5% / 30% / 40%** — QĐ 26 Điều 9.1, body not appendix · **high** — apply **post-KRX
  only**. **Pre-KRX values are UNVERIFIED; do not back-date.** *"Not a KRX delta in substance — a
  delta in what we could see. This row must not be read as 'the haircuts changed at the cutover'."*
- **Non-deltas J19 must not claim — each with the rulebook's own grade, because they are not
  all the same strength, and one of them is not a clean non-delta at all**:
  - Settlement cycle — **UNCHANGED at T+2**; launch journalism repeatedly asserted T+0/T+1,
    *"It did not happen"* · **high**
  - Fees and taxes — **no change traceable to KRX**; QĐ 1541/QĐ-BTC (2025-04-29) re-issued
    the existing rates unchanged. What changed is broker *documentation* · **high**
  - Derivatives order **types** — QĐ 20 Điều 22 and QĐ 21 Điều 22 list identically. **The
    *semantics* did change** (KRX deltas #7 and #8) · **high**
  - Session clock times — **UNCHANGED** except inside the after-hours block (HNX PLO split,
    odd-lot window extension) and the restricted-securities regime · **medium**, not high.
    *"Do not trust broker pages here."*
  - Tick grid and lot sizes — **UNCHANGED** · **medium**, not high
  - Price bands — the **values** are unchanged (7/10/15%, widened 20/30/40%) · **medium** —
    **but the *triggers* changed**: the durative *"until a round-lot price exists"* clause and
    the ≥25 harmonisation are both KRX-era. A band non-delta claim that does not say this is
    wrong.
  - **And the standing warning that governs this whole bullet**, rulebook `:336`, **high**:
    *"Any blanket claim that 'nothing in this domain changed at KRX' is false"* — said of the
    closing-price/reference definition, the most consequential missed delta in the research.
    J19 lists non-deltas; it must not generalise them.

*Broken looks like* — **The honest headline is that the number may not move at all.** At
`r = 17%` on a **single-underlying, single-expiry** position the worst `Lk` is always an
endpoint, so `Rm` reduces to `|position| × r × S × M` — numerically identical to a flat initial
margin (**high**, given the reconstruction). J19's real deltas are (a) **VM leaves the
requirement** and becomes a T+1 cash settlement; (b) monitoring goes **binary and once-daily**;
(c) a **calendar spread** flips from whatever QĐ 96/61/12 did (**UNVERIFIED**) to paying `Sm`
with **no `OA` credit** — spreads across underlyings get a credit, spreads across expiries get a
charge. A break shows up as an 80% margin *warning* fired in a post-KRX run (QĐ 26 emits none),
or as the 21-scenario grid run on a 2022 account.

*Runnable today* — **Partial, and the naive version is dishonest.** Both engines exist and are
wired: pre-KRX in `deposit.py::account_margin_requirement`, post-KRX in `scenario_margin.py`
(Phụ lục 2 complete), reached via `overnight.py::overnight_requirement` from
`_overnight_model`, which asks the dated rulebook first so the grid can never run on a 2022
account.
- **The permissive trap.** The post-KRX number is smaller than the pre-KRX one **by exactly the
  account's VM** — measured **49,800,000đ** on a 2-lot VN30F through a limit-down session
  against a **109,844,000đ** intraday requirement. That is only right if the loss is **paid in
  cash** next morning, and **must-list item 4 means we do not pay it**. A naive before/after
  comparison reports the post-KRX side as cheaper by an amount the simulator never collects.
  `OvernightAssumption.variation_margin_unsettled` fires automatically on every grid result over
  a non-zero VM. **J19 must print it, not suppress it.**
- The grid is only **~55% line-covered** and needs `SMrate` and `MF` (SSI/TCBS publish 0.87% and
  5,000đ/VN30 contract) or it returns INDETERMINATE by design. Both are checklist **SHOULD** items.
- The **09h30/14h00/16h30 checkpoints are not applied**, so the detection asymmetry can be
  *described*, not *demonstrated*.
- **Must-list item 3** (forced liquidation reports but never executes) bites if J19 pushes the
  account into breach.

---

# C. How much of a backtest is assumption

This group is deliberately different from the rest: **there is no Vietnamese rule under any of
it.** The fill policies, the queue policies and the participation cap are all **our modelling
choices**, and the scenarios exist to measure how much of a result they are responsible for.
A user who runs these learns the width of their own uncertainty band; a reader of the paper
learns that we know where it comes from.

## J20 — One strategy under hard / soft / probabilistic fill policies

*The strategy* — One rule, one window, three fill policies. Report the spread of the outcome.

*Mechanism exercised* — The fill policy is the largest single assumption in any bar-resolution
backtest, and it is not a rule. `hard` refuses anything it cannot prove, `soft` fills on touch,
`probabilistic` splits the difference.

*Governing policy*
- **UNSOURCED — no Vietnamese document states a fill probability, and none caps a participant's
  share of a print.** This is a **sourced absence**: we looked in all four rulebooks and found
  nothing.
- **A34** `HardFillPolicy.max_participation = 0.10` — **explicitly a modelling convention**,
  carried in the policy signature so it travels with any report. **our modelling choice.**
- **A35** `ProbabilisticFillPolicy.p_touch = 0.5` — *"a stated convention with no empirical
  content"*, the midpoint of the bracket `hard` and `soft` already draw. **No document could
  supply it: the rulebook settles the *rule*; the missing thing is the *data*.**
- What the fill policy may **not** override is **mostly** sourced: band, tick, lot and
  order-type legality are all rules, decided before any policy runs. `hard` **never fills
  MTL/MOK/MAK** by design. **The auction cross price is the exception and must not be listed
  with them**: it is fixed above the policy layer, but by **design §8 Convention 1 — our
  modelling choice**, not by a Vietnamese article. See J14 for the full statement and for
  the three venue conditions under which it is wrong. The short form J20 must carry, because
  a policy-spread scenario that lists a modelling choice as a rule defeats its own purpose:
  **QĐ 352 Điều 2.5 defines the close as *"giá thực hiện tại lần khớp lệnh cuối cùng trong
  ngày giao dịch"* — the day's LAST MATCH, phase-agnostic — and *"giá mở cửa"* appears
  NOWHERE in the rulebook, so no instrument defines an opening price at all.** The
  substitution is a **deliberate, stated approximation**: we do not trust the auction-window
  ticks, so we take the published close (ATC) and published open (ATO) we already store. Điều
  2.5 is *context* for why the published close is a fair stand-in for the ATC outcome; **the
  price rule itself is ours, and it carries no measurement.** The open is the weaker half
  qualitatively — HNX and UPCoM run no opening auction at all — and a policy sweep must state
  that asymmetry in words rather than fold it into one caveat.

*Broken looks like* — A single reported number with no policy named beside it. If swapping the
policy does not move the result, the policy is not on the path — which was true of several
components in this repo before they were wired, and is exactly the failure mode the ignorance
meter now reports (*exercised*, not merely *computed*).

*Runnable today* — **Yes, fully.** *(J20 is in the launch subset as of 2026-08-27 — it is
Group C's representative there, and it was promoted precisely because "Yes, fully" was
already true of it. See the launch-subset section for why the group could not be left out.)*
Four caveats publish with it:
- **At TICK resolution only, the live ATC defect of J14 applies to any arm whose fills reach
  a closing auction**: the synthesised interval's `close` is `state.last`, a **pre-auction**
  print served as the published close, so the tick path does not implement the stated
  close-as-ATC approximation. **On a daily run it cannot fire** (`DataHubSource` stamps every
  bar `CONTINUOUS`, `datahub.py:436`), which is the resolution J20's own A69 caveat assumes —
  so the two caveats are about different runs and must not be merged. Full statement in J14;
  it is publish-checklist MUST #5, on design-conformance grounds.
- **A69 look-ahead** — on a daily run the fill interval is the whole trading day, so an order
  entered at 14:00 is evaluated against the whole day. *"An over-generosity that is a declared
  consequence of the resolution and not something a fill policy may silently correct."* Present
  in **every** daily-resolution fill, including any comparison arm.
- **§16.4 conflicts 3 and 4 exactly cancel on the daily corpus** — a limit order always fills at
  its own limit (conflict 3), and `state_at` returns the whole-day bar at any intraday instant
  (conflict 4), so `limit == close` and a "0 indeterminate" run and a 100% fill rate coexist.
- `compare_policies` **reports fills, not P&L.**

## J21 — One strategy under optimistic / conservative / probabilistic queue policies

*The strategy* — One rule, three queue-position assumptions. Report how much of the result is
queue luck.

*Mechanism exercised* — Where your resting order sits in the time queue at a price level, and
therefore how much of the print at that level is yours.

*Governing policy*
- The **rule** is sourced and is only half the answer: **price then time priority, no size
  priority, no pro-rata** — QĐ 352 Điều 7, 16; VNX QĐ 22/2025 Điều 20 · 2020-01-01 → current ·
  **high**.
- **Priority-preserving amendment is itself dated, and for the first two years of the window
  it does not exist.** *Do not cite "QĐ 352 Điều 21.3" for it — that citation is wrong twice
  over, because **QĐ 352 Điều 21 is the lunch break** (rulebook `:147`, `high`) and "Điều
  21.3" belongs to a different instrument, VNX QĐ 22/2025 (rulebook `:223`, `high`).* **This
  row is the one that caused the fix, and the fix has landed**: `PUBLISH-CHECKLIST.md` MUST
  #2 carried that citation until 2026-08-27 and its row now opens *"This row's citation was
  wrong and is corrected here"*, printing the three legs below with their rulebook lines.
  The checklist also records the general lesson it drew — *"Cite the instrument, not the
  number you remember"* — so the correction is traceable from either document. The three
  real legs:
  - **2020-01-01 → 2022-03-30, HOSE — there is NO priority-preserving amendment.** Amendment
    *is* cancel-and-re-enter; **time priority always restarts** — QĐ 352 **Điều 17.1–17.3**,
    read verbatim · **high**
  - **2022-03-31 → 2025-05-04, HOSE + HNX** — priority **preserved only if quantity is
    reduced**; it restarts on a quantity increase and/or a price change. Price and quantity
    could be changed in one amendment ("và/hoặc") — VNX **QĐ 17 Điều 22.3**, read verbatim ·
    **high**
  - **2025-05-05 → current, HOSE + HNX** — same priority rule, but one amendment may change
    price **or** quantity, never both — VNX **QĐ 22/2025 Điều 21.3** verbatim; retained in QĐ
    22/2026 Điều 23 · **high (HNX/UPCoM/HNXDS) / medium (HOSE)**. The HOSE half is an
    **unresolved CONFLICT** and the split grade must be carried, not flattened to `high`:
    HOSE's own web regulation and investor guide say only that an LO may amend price, quantity
    and be cancelled during trading, **with no simultaneity ban**, so the price-XOR-quantity
    restriction rests on the VNX rulebook (higher rank, verbatim) while **HOSE's own
    publications omit it** (rulebook `:224`; KRX-delta `:1155` grades it *"high (HNX, UPCoM,
    HNXDS) / medium (HOSE — HOSE's own publications omit it)"*). We adopt the VNX rule and
    record that HOSE does not restate it.
  - This is **not** a KRX delta: the priority rule arrived on 2022-03-31; the only 2025 edit
    is "và/hoặc" → "hoặc" · **high**
  - **The first leg is sourced and NOT APPLIED by the session, which moves J21's own
    number.** `OrderBookOfRecord.amend` takes a `priority_preserving` flag and `orders.py:387`
    says `exchange.py` *"resolves [it] from `rulebook.at(ts)`"* — **it does not**.
    `exchange.py:1640-1642` never passes it, so it defaults to `True` (`orders.py:944`), and a
    permitted quantity decrease on a **2020-01-01 → 2022-03-30 HOSE** run reports
    `priority_preserved=True` where QĐ 352 Điều 17.1–17.3 says priority always restarts.
    **Permissive, and it lands on exactly the quantity this scenario is an error bar for.**
    Exhibited by **J27**.
- **UNSOURCED — all three queue policies, and any statement about our position in the time
  queue.** The rule says the queue is time-ordered; **no document tells us where in it we are**,
  and no data in the corpus does either. **our modelling choice**, all three arms.
- **CONFLICT recorded, relevant here**: Vietcap's KRX handbook records pre-KRX HOSE as *"does not
  allow direct order amendments"* with brokers offering cancel-and-replace, while HNX allowed
  simultaneous price and volume modification. We adopt *the rulebook permitted priority-preserving
  amendment from 2022-03-31, but the legacy HOSE engine did not implement it* — **this changes
  queue-position modelling for three years of the sample** · **medium**

*Broken looks like* — A result quoted to three significant figures when the queue assumption
alone moves it by more than that. The scenario's output *is* the error bar.

*Runnable today* — **PARTIAL, not blocked. Not from a config; yes from a caller who
constructs the policy and supplies depth.**

**Status change, 2026-08-27, and the derivation is printed because the conclusion moved.**
J21 was graded `blocked` on **publish-checklist MUST #1, "In progress"**. **MUST #1 has
LANDED** — commit `c6b7ef6`, *"Walk the order book instead of filling at a single price"*;
`src/plutus/market/adapters/depth.py` and `src/plutus/market/session/book_walk.py` are both
present and the checklist has moved its reasoning to RESOLVED. **A scenario cannot be
blocked by an item that does not exist.** What survives is the checklist's own **two
residuals** — and those are precisely what this entry already described correctly, so the
substance below is unchanged and only the *label* moves. They are also **exactly the
residuals J9 carries**, and J9 is graded *partial*; grading two scenarios differently on one
pair of residuals would be incoherent. **J21 is therefore partial, and blocked drops from
three scenarios to two.**

This catalogue uses the phrase *"no session call site"* for genuinely unreachable code, and
**`book_walk.py` is not that**:

- **`book_walk.py` and `adapters/depth.py` are INJECTION-ONLY, not unreachable.**
  `ExchangeSession.build(..., fill_policy=...)` takes a constructed policy
  (`exchange.py:1058`), the config path is only the fallback
  (`exchange.py:1135`: `policy = fill_policy or build_fill_policy(config.fill_policy)`), and
  the session then calls `self._policy.evaluate(...)` — **the call site is
  `exchange.py:2862`**. *(An earlier draft pointed at `exchange.py:1368`; that line is a
  **docstring bullet** describing the loop, not the call. Verified by grep this pass.)*
  `fills.py:2271-2276` documents the exact wiring, in the error message that refuses
  the config route: *"Construct it and hand it over directly — `ExchangeSession.build(...,
  fill_policy=BookWalkFillPolicy(DepthSource(root), queue=OptimisticQueue(), ...))`"*.
- **The two residuals, which are the whole of what remains**: `build_fill_policy` **refuses**
  the `book_walk` kind from a config block (`fills.py:2260-2276`) — deliberately, because
  `FillPolicyConfig` has no field for a book provider or a queue assumption and *"defaulting
  either would be exactly the silent substitution this function exists to refuse"* — and
  **the depth data is a dev extract, not the wired corpus**.
- **What the second residual is NOT.** It is not *"the corpus has no order-book sizes"*.
  `/Users/nadan/algotrade-research/dataset/hermes-dev-extract` carries **1,390,914 size rows across four Parquet files**
  (`quote_asksize` 397,993 · `quote_bidsize` 470,850 · `local_quote_asksize` 233,673 ·
  `local_quote_bidsize` 288,398), every one with a `depth` column, and production carries
  666M/590M. The residual is that this is a **dev extract covering some windows and not
  others** — *"for some windows and not others"* is `depth.py`'s own phrase — and that the
  two sides are never observed together, so a book here is **reconstructed, not observed**.
  **A window question and a fetch, not an absence.** Strike any claim to the contrary.
- **Contrast, and this is why the wording matters.** `settle_daily`, `assess_daily` and
  `OrderBookOfRecord.encumbrance_divergence` have **no caller anywhere** — verified, nothing
  in `src/` reaches them, and no argument a user can pass changes that. Those are
  **unreachable**. `book_walk` is **injection-only**. A reader who sees one phrase for both
  cannot tell a scope cut from dead code, so this document uses **"unreachable — no caller in
  `src/`"** for the first and **"injection-only — reachable via `ExchangeSession.build(...,
  fill_policy=...)`, not from a config"** for the second, and never the bare *"no session call
  site"* for either.

**Demonstrable at module level, and at session level only by a caller who constructs the
policy and supplies depth. Say which one produced the number, and do not present either as a
strategy result over the wired corpus.**

## J22 — Participation-cap sweep

*The strategy* — One rule at 1%, 3% and 10% of session volume. Does the edge survive being a
smaller share of the print?

*Mechanism exercised* — Capacity. How much of the day's volume the model is willing to give you,
and what happens to the edge when it shrinks.

*Governing policy*
- **UNSOURCED — no Vietnamese document caps a participant's share of a print at any date.**
  **sourced absence.** The entire participation-cap concept, and the 0.10 default, are **A34, our
  modelling choice**.
- **INFERRED, not sourced** — "no cap on HNX/UPCoM order size". HOSE's **500,000** units per
  round-lot matching order **is** sourced (QĐ 894 → QĐ 352 Điều 8.1; QĐ 17 Phụ lục III §1.1,
  **high (value) / medium (citation)**), and it is a **HOSE-specific clause**. The maximum order
  size for HNX and UPCoM is **UNVERIFIED — none published in any rulebook read**; the
  999,900-share figure that circulates for HNX was neither confirmed nor refuted.
- HNXDS order limit **500 contracts per order** for every listed futures contract — HNX contract
  templates rows 11, 14; VNX QĐ 20/21 Điều 17 delegates the limit to the template · 2020-01-01 →
  current · **high**

*Broken looks like* — An edge that scales linearly with size, i.e. a strategy that is allowed to
be the entire print. The cap is the only thing standing between a backtest and infinite capacity.

*Runnable today* — **Yes.** Volume coverage is **62.9%**, so `Blindness.CAP_UNCOMPUTABLE` and
`CAP_EXCEEDED` must be reported rather than silently treated as unconstrained. **Not runnable at
tick resolution** — `adapters/tick.py` serves no `MarketInterval` at all, so a tick run has no
volume and every capped policy is INDETERMINATE there.

---

# D. Derivatives

## J3 — Leveraged VN30F long into a real drawdown

*The strategy* — Open a leveraged VN30F long, hold it through the Oct-2022 drawdown, and print
the whole chain: deposit, purchasing power, the utilisation ladder, the margin call, the forced
liquidation, and the daily variation margin.

*Mechanism exercised* — Four layers that a US-trained reader will merge and that Vietnam keeps
separate: the depository's requirement, the depository's **binary** breach test, the depository's
**position-limit** ladder, and the broker's own commercial utilisation ladder.

*Governing policy — VSDC, margin, post-KRX (QĐ 26 read verbatim, `high`)*
- The **binary** violation predicate `assets < MR` and its complement `≥` for cure — Điều 13.1,
  13.2(c). **No warning band, no amber state, no ratio.**
- Three checkpoints **09h30 / 14h00 / 16h30** — Điều 13.2(a)(b)(c).
- Top-up **"trước 09h30 ngày giao dịch liền kề tiếp theo"** — Điều 13.1. *(Broker pages quoting
  "09:30 T+1" were reporting the real VSDC deadline; an earlier row of ours calling it a broker
  term was wrong.)*
- Exactly two permitted remedies: *"a. Nộp bổ sung tài sản ký quỹ; b. Thực hiện giao dịch đối
  ứng"* — Điều 13.3.
- **03 working days**, then **VSDC directs a DIFFERENT clearing member to close the positions**,
  by agreement — Điều 13.3.
- Machine form of the level-3 action: the trading system ingests VSDC's restricted-account list
  and *"chỉ nhận lệnh mới có tham số close-out"* — **VNX QĐ 21 Điều 36**, exchange, **high**,
  **absent from QĐ 20** (a genuine KRX delta).

*Governing policy — VSDC, POSITION LIMITS, not margin (QĐ 26 Điều 29, `high`)*
- *"thiết lập các ngưỡng cảnh báo theo ba (03) cấp độ"*, monitored **during the session**,
  counted in **contracts** against *giới hạn vị thế*: level 1 **80%**, level 2 **90%**, level 3
  **100%**.
- Levels 1 and 2 are **warning only** — *"VSDC sẽ gửi thông tin cảnh báo"*. No suspension, no
  trading restriction.
- Level 3: suspend and reduce within **03 working days**, and *"Các giao dịch đối ứng này sẽ bị
  coi là **không hợp lệ** nếu sau khi khớp lệnh tài khoản vi phạm không giảm xuống dưới ngưỡng
  cảnh báo mức độ 3"* — **a partial reduction that leaves the account at or above 100% is void,
  not partial credit**, and is routed to the error-holding account under Điều 18.
- *"đạt ngưỡng 100%"* = **reaches**, so an account sitting exactly at its limit is already level
  3. It is **post-trade detection, not a pre-trade admission check**: *"A simulator that rejects
  the limit-breaching order at entry is modelling something QĐ 26 does not describe"* · **high**
  on the text / **medium** on the negative.
- Contract count (Điều 27.2): an ordinary account nets opposite positions **within the same
  expiry** then sums across expiries — so **a calendar spread consumes limit**; an omnibus account
  takes the **larger** of long/short per expiry and **cannot net at all**.
- The limit **values** (5,000 / 10,000 / 20,000) remain **low** — the current HNX template no
  longer prints them and no VSDC notice republishing them inside 2020–2026 was located.

*Governing policy — broker-set, `medium`, per-firm (belongs in broker config, never in the
exchange rulebook)*
- The 75 / 85 / 90-style utilisation ladder. Pinetree 2024: **75% safe** (no new positions),
  **85% call**, **90% processing** (force-close part of the position back below 75%). It is a
  market **shape**, not a market constant — but calling it *"one firm's published example"*
  **understates the evidence by ten firms**, and the catalogue owes the reader the subsystem
  that holds them:
  - **`broker_profile.py` ships EIGHTEEN surveyed profiles**, `IMPLEMENTED + SOURCED (per
    firm)` (`FEATURES.md`, the row *"Broker margin profiles wired into the session"* —
    **named rather than line-numbered, because a line pointer into a document another
    agent is editing goes stale the same day, and this one already had**), added
    2026-08-27: `PLUTUS_DEFAULT`, TCBS, SSI (+ two
    vintages/variants), VNDIRECT, FPTS, SHS, Vietcap, HSC, MBS, KIS, VPS, Pinetree (+ its
    2024 vintage), DNSE, VCBS, ACBS. **Ten of the eighteen configure a session**; the other
    eight **refuse with a stated reason** rather than being filled in. Wired through
    `broker_profile: {"firm": "TCBS"}` → `exchange.py::_broker_profile` →
    `BrokerProfile.from_margin_profile` → `ExchangeSession.build`, with the firm, the
    user-facing `margin_model`, its engine and `margin_model_is_assumed` all recorded in
    `SessionProvenance`.
  - Every profile field carries a `Coverage` grade (`PUBLISHED` / `INFERRED` / filled from
    `PLUTUS_DEFAULT` and marked), a named source class and, for every numeric field, a
    `Derivation` recording the rule, the firms **by name** and `n`. **This is the same
    discipline as the rulebook's confidence column, applied to broker terms** — it is not an
    unsourced blob and this catalogue should not have described it as one.
  - **`PLUTUS_DEFAULT` is a synthesis, and it says so.** Its ladder is derived, not chosen:
    block-opening **80%** (median, `n=6`, pool 75/80/80/80/85/85 — FPTS, VNDIRECT, Pinetree
    at 80); call **90%** (median, `n=7`, pool 85/87/90/90/90/90/90 — SSI, Vietcap, FPTS,
    VNDIRECT, Pinetree); forced close **95%** (median, `n=7`, pool
    90/90/95/95/95/100/100 — SSI, Vietcap, Pinetree). HSC is excluded from the numeric pools
    with a reason (gap `G17`, its coverage ratio converts two incompatible ways) and
    VCBS/ACBS because they have no ladder at all. **Exclusions are recorded, not silent.**
- **The cure window for a retail account is a broker commercial term in the account-opening
  agreement, not an exchange or statutory number.** IMPORTANT NEGATIVE FINDING · **high**
- The broker's own IM ratio (must be **≥** VSDC's); the intra-session top-up right (*"tùy vào điều
  kiện thị trường, thành viên bù trừ có quyền yêu cầu nhà đầu tư bổ sung ký quỹ ngay trong phiên
  giao dịch (intra-day margin)"* — VSDC §IV.2/§V.4 verbatim, **high** that the right exists); the
  **08:45** ATC-breach top-up (broker-only, appears **nowhere** in QĐ 26).

*Governing policy — the negatives and the ours*
- **UNVERIFIED, 2017-05-01 → 2025-05-04** — whether a margin-**utilisation** 80/90/100 ladder
  existed at all. **Not disproven; unsupported.**
- **Standing negative, both regimes, `high`** — *"Neither VSDC nor HNX/VNX publishes a maintenance
  margin ratio for VN30 index futures at any date in 2020–2026 … A US-style
  maintenance-margin-as-a-fraction-of-notional test does not exist in Vietnam."*
- **our modelling choice, AND A CORRECTION — there are two different ladders and an earlier
  draft printed only the wrong one.** A bare `BrokerTerms()` defaults to **0.80 / 0.90 /
  1.00**, and of that top rung it is true that it reproduces the regulated binary test
  everywhere **except the boundary `assets == MR`, which Điều 13.2(c) treats as CURED and we
  treat as BREACH**. **But a user who names a firm never gets it.**
  - **Out of the box the ladder IS 80 / 90 / 100. 80 / 90 / 95 is `PLUTUS_DEFAULT`'s, and a
    session that names no firm never sees `PLUTUS_DEFAULT`.** An earlier draft printed *"the
    shipped default ladder is 80/90/95, not 80/90/100"*, which is the sentence a reader
    quotes back and is ambiguous to the point of false. The code path, verified this pass:
    `exchange.py:732-734` returns `BrokerProfile.from_config(payload)` **when no firm is
    given**; `types.py:2517` is `terms: BrokerTerms = BrokerTerms()`; and `BrokerTerms`'
    defaults (`broker.py:136-138`) are `warning_utilisation = 0.80`,
    `margin_call_utilisation = 0.90`, `forced_close_utilisation = 1.00`. **So the unnamed
    path is 80 / 90 / 100.** `PLUTUS_DEFAULT` is reached only by asking for it by name, and
    `broker_profile.py:2205-2212` is describing *that profile's* synthesis: *"The resulting
    ladder is **80 / 90 / 95** … the top rung is **95, not 100** — the broker fires **before**
    the CCP breach at 1.00, which is `CcpBreachTest` and a separate object."*
  - **And "any session built with `broker_profile: {"firm": …}` runs 0.95" is FALSE.** It was
    generalised from one profile. `to_broker_terms()` was executed over **all eighteen**
    profiles this pass; **ten convert and eight refuse**, and the ten do **not** agree on the
    top rung. Measured, as `warning / call / forced_close`:
    - **Top rung 1.00 — the boundary case, and there are two of them**: **VNDIRECT**
      0.80 / 0.90 / **1.00** · **FPTS** 0.80 / 0.90 / **1.00**
    - **Top rung 0.95**: `PLUTUS_DEFAULT` 0.80 / 0.90 / 0.95 · **SSI** 0.85 / 0.90 / 0.95 ·
      **Pinetree** 0.80 / 0.90 / 0.95
    - **Top rung 0.90**: **TCBS** 0.85 / 0.87 / 0.90 · **SHS** 0.75 / 0.85 / 0.90 ·
      **SSI_2025_09** 0.80 / 0.85 / 0.90 · **Pinetree_2024** 0.75 / 0.85 / 0.90
    - **Top rung 0.85**: **SSI_FOREIGN** 0.75 / 0.80 / 0.85
    - **The eight that refuse**, with the reason recorded rather than a number invented:
      **Vietcap** (publishes 2 rungs; `BrokerTerms` needs three) · **HSC** (runs a
      **falling-coverage** ratio, `R = số dư ký quỹ / IM`; `BrokerTerms` holds three
      *rising*-utilisation percentages, so the two are not the same object) · **MBS**,
      **KIS**, **VPS** (delegate their rungs to a notice not on the public site) ·
      **DNSE**, **VCBS**, **ACBS** (publish **0** rungs). **Eight refusals out of eighteen
      is the subsystem working**, not a coverage failure — each raises `CoverageError` with
      the reason, rather than silently inheriting `PLUTUS_DEFAULT`.
  - **So the `assets == MR` boundary DOES arise on the wired path — on VNDIRECT and FPTS,
    exactly there.** The earlier claim that it *"never arises"* on a named-firm session was
    the consequent of the false premise above and falls with it. The correct statement:
    **whether the boundary arises is a per-profile fact, not a property of the wired path.**
    At a top rung **strictly below 1.00** (eight of the ten) the broker fires before the CCP
    breach and the boundary never comes up — the binary test is a *separate object*,
    `CcpBreachTest`, rather than the same rung reinterpreted. At a top rung **of exactly
    1.00** — the unnamed `BrokerTerms()` path, **VNDIRECT and FPTS** — the broker's rung and
    the CCP's coincide, and there **`assets == MR` is treated as BREACH where QĐ 26 Điều
    13.2(c) treats it as CURED.** **Anywhere this catalogue reasons about the 1.00 rung's
    relation to Điều 13.2(c) — J3 here, J26, U14 — it is reasoning about those three
    configurations by name, and must name them.**
  - Also honoured since 2026-08-27: the profile's **block-opening** rung at admission
    (`deposit.py::reserve_for_order`), which is a **refusal**, not a notification — every
    surveyed firm's Mức 1 is *"tối đa để được mở vị thế mới"*, and `BrokerTerms` alone could
    only hold it as `warning_utilisation`. Measured: at 0.9314 utilisation a fifth VN30F2210
    contract was **accepted** before the fix and is now rejected with
    `binding_constraint = 0.80`, while an offsetting sell is still admitted (QĐ 26 Điều
    13.2.a).
- **VM asymmetry, pre-KRX, `high`** — *"Giá trị ký quỹ biến đổi **chỉ được tính vào** giá trị ký
  quỹ duy trì yêu cầu trong trường hợp lãi lỗ vị thế … **ở trạng thái lỗ**."* A favourable move
  gives **zero** relief; an adverse move **adds**. *"A symmetric equity/notional model mis-times
  calls in both directions."*
- **Purchasing power** — the withdrawable amount is **assets − MR at the broker's threshold, not
  assets − IM**. **QĐ 26 Điều 11 khoản 1–3** (read verbatim) bars withdrawal from an account
  suspended for a margin-asset breach, a position-limit breach or insolvency — **the rulebook
  does not resolve which khoản/điểm carries that condition, so neither do we**; our test is
  recorded as **narrower than the source**.

*Broken looks like* — A maintenance-rate call (a US test Vietnam does not run); a call arriving
on a **favourable** move (symmetric VM); an 80% margin *warning* in a post-KRX run (*"a simulator
that keeps the ladder but re-dates it to 2025-05-05 will emit two warnings that the post-KRX
regime never emits"*); or a position-limit order **rejected at entry** rather than detected
post-trade.

*Runnable today* — **Partial: yes up to and including the call, and no further.** Deposit,
purchasing power, ladder and margin call are all live and real. Two must-list items are **the
content of this scenario, not a footnote**:
- **Must-list item 3 — `FORCED_LIQUIDATION` reports and never executes.** `detail['executed']`
  is `False` on every one, with the reason recorded in code: *"Tier 1 reports a forced close and
  does not execute one; the loop is Tier 2."* **Measured on the Oct-2022 drawdown: 24 forced
  liquidations across 12 sessions, position intact through all of them, riding 1102.0 down to a
  1058.0 settlement. Cost 17,600,000đ on a 100,000,000đ account — 17.6%.** Direction:
  **PERMISSIVE** — a strategy that would have been liquidated in reality survives here.
  *(Do not conflate with the **equity** forced sale, which **does** execute — that is J5.)*
- **Must-list item 4 — variation margin never settles in cash.** `settle_daily` is UNREACHABLE — no caller
  anywhere in `src/` (D1) — so **A60**: VM is cumulative since-entry unrealised loss, not the day's adverse
  move. The deposit balance sat unchanged at **99,948,008đ for all 18 sessions before expiry**.
  **"Daily VM" — in J3's own title — is precisely what this simulator does not do.**

## J6 — Roll a futures position across expiry

*The strategy* — Hold VN30F into the last trading day, close it and open the next contract.
Report the settlement, the timing of the cash, and the tax on the leg that was never matched out.

*Mechanism exercised* — Expiry, final settlement price, daily settlement price, and the fact
that a held-to-expiry contract is **never matched out** and so escapes a fill-only charge model.

*Governing policy*
- **Last trading day**: third **Thursday** of the expiry month; if a non-trading day, moved
  **BACKWARD** to the immediately preceding trading day — HNX's own **Mẫu HĐTL Chỉ số VN30**
  (contract template), **no row number** · 2017-08-10 → current · **high**. *(Rows 4/5/10/11/14
  are the tick / multiplier / lot / order-limit set — J4 cites them for that. And row numbers
  are not safe to quote loosely here: rulebook Open Question #7 records that "row N of the
  21-row template" citations match a **superseded edition and are off by one from row 7
  onward**, so "both editions" cannot be asserted of any row number.)* Independently anchored:
  VN30F2206 expired 2022-06-16. *One broker page (Entrade X) says "third Friday" — a broker
  documentation error, definitively refuted.*
- Contract months: four listed at any time — current, next, and the last month of each of the
  next two quarters · template · **high**. Final settlement day: the business day immediately
  following the last trading day (T+1), cash-settled, netted to one obligation per clearing
  member, paid through VietinBank — template + VSDC "Bù trừ và Thanh toán" §II.1(b) · **high**
- **FSP, old** · 2017-08-10 → **2022-06-15** — *"Giá trị đóng cửa của chỉ số cơ sở tại ngày giao
  dịch cuối cùng"*, the single VN30 value from HOSE's closing call auction — Mẫu HĐTL pre-2022
  edition row 16; MBS; BSC · **high**. Last expiry under this rule: **VN30F2205 on 2022-05-19**.
- **FSP, current** · **2022-06-16** → current — simple arithmetic average of the VN30 index over
  the **last 30 minutes** of the last trading day (15 min continuous + the 15-min closing
  auction), **after excluding the 3 highest and 3 lowest index values of the CONTINUOUS session**;
  ATC values are **not** trimmed — **Quyết định 61/QĐ-VSD (2022-05-16), regulation effective
  2022-06-01**; template post-2022 edition row 16; VnEconomy 2022-05-26 · **high**
- Which instrument governs — **RESOLVED, `high`**: VNX QĐ 20/21 **Điều 5(1)(u)** lists *"Phương
  pháp xác định giá thanh toán cuối cùng"* as a template term qualified *"(theo Quy chế nghiệp vụ
  của … VSDC)"*, so **the exchange rulebook expressly delegates the FSP to VSDC**. Same delegation
  for the DSP (Điều 5(1)(t)) and the margin level (Điều 5(1)(v)).
- **⚠ THE DATE TRAP. 2022-08-17 is a corpus observation, not a rule date.** The dated change is
  **regulation effective 2022-06-01** and **behavioural boundary 2022-06-16** (the first contract
  it applied to). 2022-08-17 is where our own `quote_settlementprice` series changes subject —
  the last futures-tracked row is 2022-08-16 and the first `VN30INDEX` row is 2022-08-17.
  **J6 must cite 2022-06-01 / 2022-06-16 for the rule and 2022-08-17 for the data series, and say
  which is which.** Citing 2022-08-17 as the FSP rule change is exactly the claim a Vietnamese
  practitioner would catch. Our own docs record that *which quantity the exchange published
  pre-cutover is unresolved* — "a rulebook question, not a data question".
- **DERIVED, `medium`** — the **14:15–14:45** clock times. Neither the template nor the QĐ 61
  reporting gives clock times; they say *"the last 30 minutes"*. 14:15–14:45 follows from the
  session table, which itself rests on a VNX notice rather than a gazetted rule.
- **UNVERIFIED and load-bearing** — the index **sampling frequency**. The rule averages *"giá trị
  chỉ số"* without stating dissemination frequency, so the sample size — and hence how much the
  6-value trim removes — is unknown. **"The FSP cannot be implemented exactly without it."**
- **DSP** · 2022-06-01 → current — the **closing (ATC) price**; where none can be determined, a
  **VWAP of matched prices**, with **ATO and negotiated (thỏa thuận) prices EXCLUDED**; rounded to
  2 dp — QĐ 61/QĐ-VSD as reported; template row 15. **Article text not read** · **medium**.
  **2020-01-01 → 2022-05-31 UNVERIFIED** (QĐ 96/QĐ-VSD never read; the 2022 rule's explicit
  exclusion of ATO/negotiated *as a change* proves a different earlier rule existed). Fallback when
  a contract has **no matched trades at all**: **UNVERIFIED**. Why it matters (**high**): the DSP is
  the reference for the next day's band **and** the VM mark, and the VN30F reference equals the
  prior close on only **86.5%** of corpus contract-days — substituting the close mis-sets the band
  roughly **one contract-day in 7.4**.
- **The roll is not tax-neutral.** A position carried to expiry is never matched out, so a
  fill-only model under-charges every held-to-expiry contract by exactly one leg — the leg the
  trader who closed the day before pays. `_maturity_charges` levies the derivatives transfer tax at
  maturity per rulebook §8.1/§12.3. **Open, with a 2× cost impact**: whether **QĐ 1541/QĐ-BTC**
  carries **both** the derivatives clearing fee and the position-management fee decides whether an
  intraday round trip costs **2,550đ or 5,100đ per contract** from 2025-04-29. *"Needs one verbatim
  gazette read."*

*Broken looks like* — The roll finds nothing to close on expiry morning and the offsetting order
opens a **brand-new naked position in a contract that has already cash-settled** — the exact bug
`_expiry_reached` was written to fix (*"the last trading day IS a trading day"*, and settlement is
struck at the venue **close**, not at the first advance landing on the expiry date). Other tells:
a third-**Friday** expiry; a pre-2022-06-16 expiry settled on a trimmed 30-minute average; a
post-2022-06-16 expiry settled on the closing index value.

*Runnable today* — **Yes — expiry is wired end to end**, the settlement tier and its substitution
are recorded on the event, and the maturity tax has a call site.
- **What we actually settle at, and the honest error bar**: `_final_settlement` prefers the
  source's `MarketInterval.settlement_price`, else the **close on the expiry day**, recorded as
  `SettlementSource.CLOSE_PROXY` with `substituted=True`. **Measured across all 46 post-cutover
  expiries: +0.024% mean signed, 0.042% mean absolute, 0.333% worst.** Earlier drafts of our own
  documents quoted **~0.4% from VN30F2206 alone (n=1)**, which sits near the **worst** of the
  distribution — **that figure is retracted and J6 must not reuse it.**
- **Must-list item 4 bites, visibly, and J6 is arguably the clearest place to show it**:
  `settle_expiry` marks from `variation_reference`, which never rolls, so **the whole life's P&L
  lands in one cash flow at expiry instead of daily**. The roll's cash is right in total and wrong
  in timing.
- **The auction blocker bites if the roll is placed at the ATC on expiry day. Roll in
  continuous** — and on a **tick** run the reason is sharper than "blocked": the fill would
  **succeed and be wrong**. The session re-stamps the phase to `closing_auction` correctly
  (`exchange.py:2841-2843`), `_interval_for` then **synthesises** the interval
  (`exchange.py:2442-2451`) with `close = state.last`, and `auction_fill_price`
  (`fills.py:608-636`) serves that **pre-auction print** as *"the published close"* — so the
  tick path does not implement the stated close-as-ATC approximation. **A roll is a two-leg
  trade whose whole result is the spread between the legs**, which is the worst possible place
  to serve an auction fill the model did not intend. Full statement in J14; it is a
  publish-checklist MUST (#5), on design-conformance grounds.
- **Latent implementation gap**: `third_thursday()` / `expiry_date()` have **no
  roll-back-if-non-trading-day branch**; the docstring's *"Verified 24/24 in-window"* means no
  third Thursday in the sampled window fell on a holiday, so the gap is **latent, not live**, and
  `instrument.expiry` (the ticker master's published date) takes precedence where it would matter.
  Also `expiry_date` matches `VN30F` **only** — VN100F and GB codes fall through to `None`, and
  *"a position with no expiry never expires"*. Declared, not papered over.

## J26 — Day trader flat by the close vs swing trader overnight

*The strategy* — Two accounts, the same VN30F position intraday. One is flat by 14:45; the other
carries it. Report each one's requirement.

*Mechanism exercised* — The same position faces **two different requirements computed by two
different engines from two different price series**: an intraday one against the futures traded
price, and an overnight one struck once after the close from end-of-day positions and the
**underlying's** close.

*Governing policy*
- **Post-KRX OVERNIGHT — VSDC, primary, `high`.** QĐ 26 **Điều 5 khoản 5** / **Điều 13 khoản 1**
  verbatim: *"Ký quỹ yêu cầu là tổng giá trị ký quỹ mà thành viên bù trừ có nghĩa vụ phải nộp cho
  VSDC để duy trì các vị thế đứng tên thành viên bù trừ được tính toán **sau khi kết thúc phiên
  giao dịch** cho danh mục vị thế trên **từng tài khoản giao dịch của nhà đầu tư**."* Then
  `MR = Max(ΣPgm, 0)`, `Pgm = Max((Rm + Sm + Dm), MM)` (Phụ lục 2 mục 6.1/6.2), marked on the
  **underlying's close**. **`Dm = 0` here and in every number J26 reports**: it is the
  government-bond delivery margin (rulebook `:724`), GB futures are out of scope, and the
  term is printed only because the gazetted formula prints it. J26 is in the launch subset,
  so this must be on the page rather than in a footnote.
- **Post-KRX INTRADAY — NOT a VSDC requirement at all.** Điều 13.2(a) verbatim: the 09h30 and
  14h00 checkpoints test live asset balances against *"mức ký quỹ yêu cầu xác định tại **ngày làm
  việc liền trước**"*. **There is no intraday recomputation of the requirement** (`high`), and with
  09h30-only-adds / 14h00-only-releases the depository **cannot issue an intraday margin call at
  all** (`high`). The intraday layer a day trader actually feels post-KRX is **the clearing
  member's** — VSDC "Thông tin về ký quỹ" §IV.2/§V.4 verbatim, **high** that the right exists;
  the **levels** are per-firm and **medium**.
- **Pre-KRX (2017-05-01 → 2025-05-04) there is only ONE layer.** Margin lodged with VSDC before an
  order could be placed, recomputed against live prices in-session; `MR = IM + VM` over the account
  portfolio; VM counts only in a **loss** state. **No separate end-of-day model exists**, so the
  overnight requirement is the continuous one on the positions still held at the close. **A pre-KRX
  J26 has a day-trader/swing-trader difference in exposure but not in engine — say so rather than
  manufacturing one.** `high`
- **The measurable asymmetry, primary-sourced**: post-KRX the overnight requirement **omits VM
  entirely** (Phụ lục 2 §6.2 has no VM term; Điều 20 settles position P&L as a separate T+1 cash
  movement) while the intraday view carries it. **Measured: 49,800,000đ of VM on a 2-lot VN30F
  through a limit-down session, against a 109,844,000đ intraday requirement.**
- **`no_published_grouping`, our modelling choice, restrictive** — nobody publishes VSDC's
  underlying-asset groups, so every underlying is a **singleton with `OA = 0`**. Measured
  **78,200,000đ ungrouped against 14,668,983đ with the offset**. Recorded **only** when the account
  holds ≥2 underlyings, because on one product the relief is zero **BY THE RULE** — Điều 5.1.1(a)
  conditions it on *"từ hai tài sản cơ sở trở lên"*.
- **`minimum_margin_factor_derived`, DERIVED, restrictive** — no firm publishes `R`, so
  `R = MF / (M × St)` is inverted out of the profile's published `MF` (**5,000đ per VN30 contract**,
  derived as `tick × M / 2` for a one-tick book and corroborated verbatim by TCBS) at raised
  precision so the round trip returns exactly `MF`. **A lower bound**, so `MM` binds slightly less
  often than the truth.
- **`parameter_mirror_undated`** — a `VsdcParameterSet` whose `effective_from` the firm does not
  print cannot be checked against the calculation date; used, with the fact travelling on the
  result. A mirror that **is** dated and post-dates the calculation is **refused**
  (`OvernightGap.PARAMETERS_NOT_YET_EFFECTIVE`).
- **UNSOURCED, and already marked as ours** — TCBS publishes `MR = Max(Rm + Sm + Dm + **FSP** −
  OA, MM)` (TCBS's own line, quoted as published; `Dm` is again **0** for VN30F), a fourth
  term *"Ký quỹ FSP"* with **no VSDC counterpart. Verified by exhaustive
  absence**: *"Ký quỹ FSP"* occurs **zero times** in QĐ 26 and Phụ lục 2; `FSP` occurs only as
  *"giá thanh toán cuối cùng (FSP)"*. Our reading — that *"sản phẩm FSP"* means products whose FSP
  is fixed **after** the last trading day, which VN30F is not — **is OURS and stated as ours**;
  `FSP_MARGIN_INDEX_FUTURES = 0` *"by name, not by ignorance"*.
- **Scope note**: there is **no cash-market counterpart to J26.** *"Across the entire window, no
  short sale and no intraday round trip of the same shares is admissible on the cash market"*
  (statutory, **high**). A day-trader/swing-trader margin contrast is **derivatives-only in
  Vietnam**.

*Broken looks like* — One requirement for both traders: the overnight number quietly replaced by
the intraday one, which is *lower* on any book the grid stresses harder — *"a backtest that
under-states margin lets a strategy hold a position the real account would have been called on."*
Or the reverse date error: the 21-scenario grid run on a 2022 account.

*Runnable today* — **Yes — the best-wired of the derivatives three.**
`overnight.py::overnight_requirement` is the seam; `_overnight_margin` runs it **once per session,
after the close**, per Điều 5.5; `scenario_margin.py` implements Phụ lục 2 completely; the regime
is chosen from the dated rulebook and the rulebook can **veto** the profile.
- **Must-list item 4 is not an obstacle here — it is the finding.** It makes
  `OvernightAssumption.variation_margin_unsettled` fire, *"the one assumption here whose direction
  of error is permissive"*, and **that flag is the honest content of J26. Show it; do not
  suppress it.**
- The grid needs **`SMrate` and `MF`** from a broker profile or it returns INDETERMINATE by design
  — never a silent fall back to the intraday number. Only **~55%** of the grid's lines have executed
  under any test: **wired and running but unproven.**
- The 09h30/14h00/16h30 checkpoints are **not applied**, so J26 can contrast the two **layers** but
  cannot demonstrate the post-KRX **detection timing**.

---

# E. Cross-market and equity finance

## J4 — Pair trade: a VN30 proxy basket on HSX against VN30F on HNXDS

*The strategy* — Long a cash basket on HOSE, short the index future on HNXDS, in one session,
out of one account object. Report both legs' cash, margin and charges.

*Mechanism exercised* — Two venues, two instrument kinds, two settlement clocks and two margin
regimes running simultaneously against a single ledger — and the transfer between the securities
cash ledger and the derivatives deposit.

*Governing policy*
- Legs are governed by their own venue's rules, resolved per order: HSX band ±7%, tick 10/50/100đ,
  lot 100 (QĐ 352 Điều 8.1, 8.4, 9.6 → QĐ 17 Phụ lục III §1.1–1.3) · **high (2021-07-05 onward)**;
  HNXDS tick **0.1 index point** = 10,000đ/contract, multiplier 100,000đ/point, order limit 500
  contracts (HNX Mẫu HĐTL Chỉ số VN30 rows 4/5/10/11/14; VNX QĐ 20/21 Điều 8.1(k)–(l), Điều 17) ·
  2017-08-10 → current · **high**
- **Every tick, lot and band number from 2022-03-31 onward is corroborated from broker sheets and
  HOSE web publications, not from the gazetted Phụ lục III, which nobody has obtained for any
  version** · **medium**
- **A67, our modelling choice** — bands are reconstructed from the **undated, flat**
  `VietnamMarketConstant.DAILY_TRADING_LIMIT`, labelled `RECONSTRUCTED`, never `PUBLISHED`; the
  rulebook's dated bands feed only `InstrumentSpec`, **which no admission rule reads**.
- **UNSOURCED for the futures leg** — the derivatives utilisation ladder 80/90/100 (A1–A3). **QĐ 26
  Điều 13 is a binary test with no percentage of any kind**; the 80/90/100 in QĐ 26 is **Điều 29,
  for POSITION LIMITS**; pre-KRX it is **UNVERIFIED, not disproven**.
- **UNVERIFIED (A14)** — rounding to whole đồng, ROUND_HALF_UP, for **every** charge.
- **Foreign room is not evaluated** — tradeoff **T1** (see the closing section).

*Broken looks like* — One leg's rules leaking onto the other: an HNXDS tick applied to the HOSE
basket, a T+2 clock applied to the futures leg, or one margin regime covering both. In a pair
trade the two legs are supposed to offset, so a rule error shows up as a spurious net exposure
rather than as an obvious rejection.

*Runnable today* — **Yes — already run** (`validation/scenarios/pair-trade.py`). Five
disclosures, and the first is a correction to an earlier draft of this entry:
- **Must-list item 3 is NOT neutral here — it is what carries the position to expiry.** An
  earlier version of this bullet said *"must-list item 3 changes nothing here"*. The run's
  own file says the opposite. `validation/scenarios/pair-trade.py:237-242`: *"Every one of
  the **six** forced events in this run carries `detail['executed'] = False`, so nothing is
  closed, the breach persists and the event repeats at each mark. **The account is still
  short 4 contracts at expiry and settles them in cash.**"* The run table (`:119-124`) shows
  **three FORCED sessions at utilisation 0.9065 / 1.0933 / 1.2021** — 2022-11-14 (uncured
  from the 11-11 call), 2022-11-16 and 2022-11-17 — and the position survives all three.
  Direction: **PERMISSIVE.** It is also what makes the conflict-1 bullet below possible: an
  account *"in `FORCED` breach"* has to still hold the position to be in breach. **J4 is the
  most-cited "already run, every đồng accounted for" scenario, so it is the worst place to
  under-declare the permissive item.**
- **Must-list item 4** affects the futures leg's reported ladder.
- **The corporate-action engine is not wired into `advance_to`** (deliberate — a CA feed is
  exogenous data), and a real ex-dividend sits inside this window: **PLX, ex-date 2022-11-09, a
  1,200đ/share cash dividend, silently missed**. The run happens to be flat that day, so *"every
  đồng accounted for"* is true of that run and **would not be true of the obvious variant**
  (300 × 1,200 = **360,000đ** with no log row and no error).
- **§16.4 conflict 1** — derivatives cash settles **T+0** against the repository's own dated **T+1**
  rule (`settlement_rule(FUTURE)` returns `cycle_days=1`, `Confidence.HIGH`, VSDC-cited, and the
  derivatives branch never calls it). Measured: +28,440,000 on a Tết-2021 expiry made spendable one
  session early on an account in `FORCED` breach. **What must be decided:** whether unsettled
  variation margin still counts as a margin asset in the interim. Not fixed, because deciding it
  without a source would be inventing the margin treatment.
- **D2** — the `free_deposit` docstring is wrong.

## J5 — Margin-financed equity position that gets called and force-sold (bán giải chấp)

*The strategy* — Buy on margin, hold into a decline, receive the call, fail to cure, and get
sold out. Print the ratio at each step and the proceeds after the debt is deducted.

*Mechanism exercised* — Equity margin lending: the statutory ratio floors, the account algebra,
the call, the cure window, and the forced sale — which on the equity side **actually executes**.

*Governing policy — statutory*
- Initial margin ratio floor `imr` **≥ 50%**; maintenance margin ratio floor `mmr` **≥ 30%** —
  **QĐ 87/QĐ-UBCK Điều 5(1),(2), verbatim, cross-checked on two mirrors** · 2017-04-01 → current ·
  **VERIFIED**. (Before that: `imr` **60%** from 2011-08-30 under QĐ 637, **REPORTED**.) Điều 5.3
  gives the SSC a **standing power to move both without new legislation**, so model them as dated
  regulator-settable parameters, not constants.
- **DERIVED, not the text — "`imr ≥ 50%` ⇒ max LTV 50%".** Điều 5.1 says only *"không được thấp hơn
  50%"*. The restatement rides on the identity `imr = 1 − loan_ratio`, which is **ours** and holds
  **only for a single, fully collateralised purchase**; Điều 2 khoản 8 defines `imr` over the
  account's *tài sản thực có*, so an account already holding other eligible collateral supports a
  **larger** purchase.
- Margin call — trigger: the ratio drops **below `mmr`**; the CTCK **issues** a *lệnh gọi ký quỹ bổ
  sung*. **Cure window ceiling: not more than three (03) business days — QĐ 87 Điều 7.1 alone.**
  *(The joint heading "QĐ 87 Điều 7, TT 120 Điều 9.6" is not a joint citation: TT 120 Điều 9.6
  carries the call and the force-sale right but **no day count**.)* · **VERIFIED**
- Forced sale — **QĐ 87 Điều 8, TT 120 Điều 9.6, VERIFIED**: the right arises on failure or partial
  failure to top up within the deadline; part or all of the pledged securities; the CTCK must
  **notify the client before placing the sell order**; where all securities are sold the client may
  withdraw **only the remainder after the margin debt is deducted**.
- **SILENT, and delegated by name** — QĐ 87 Điều 12.2(i) requires only that the *contract* state
  *"phương thức xử lý tài sản thế chấp … và **thứ tự ưu tiên sử dụng tiền bán chứng khoán thế
  chấp**"*. So **both the sale ordering and the proceeds-application ordering are per-broker
  contract terms, not exchange rules. Do not invent a default.** (The exact analogue of
  `LiquidationRule.LARGEST_LOSS_FIRST` on the derivatives side, A54.)
- **TT 120 Điều 9.9** — in cases necessary to stabilise the market the SSC may **order margin
  trading at a CTCK to be suspended** · **VERIFIED**. Worth a kill-switch.

*Governing policy — UNSOURCED, DERIVED, and the gaps*
- **UNSOURCED — equity-margin `call_level` and `force_level` at ANY Vietnamese broker.** No verified
  counterpart was found at any firm. The 0.40 used in the scenario is *"a plausible market value and
  nothing more"*. **our modelling choice.**
- **UNSOURCED** — force-sale execution price; liquidation ordering; proceeds-application ordering.
- **UNSOURCED** — interest day-count, compounding and accrual convention: **QĐ 87 Điều 11.4
  delegates entirely.**
- **DERIVED, because the source is an image** — QĐ 87 Điều 7.2 gives two top-up formulas and **every
  accessible mirror renders them as images and drops them**. Ours: posting eligible securities
  `S ≥ (mmr·EB − AB)/(1 − mmr)`; depositing cash applied to repay debt `C ≥ mmr·EB − AB`. *"Do not
  ship these as 'the regulation says'."*
- **INFERRED, low, and the previously offered reasoning is refuted** — that unsettled purchases are
  excluded as margin collateral. QĐ 87 Điều 13(5)(b) **expressly allows** other securities by
  written agreement.
- **NOT BUILT / NOT WIRED** — per-deal accounting and firm-level caps (QĐ 87 Điều 9).

*Broken looks like* — A call that never arrives, or a forced sale that fills at a price the book
never offered. The load-bearing tell in this repo is the **band lock on the exit**: **HPG
2022-10-31, the *bán giải chấp* the client is legally obliged to suffer is
`Rejected(BAND_LOCK)`.** A fill-at-close backtester sells; this one cannot — and that is the
correct answer.

*Runnable today* — **Yes — and unlike the derivatives side, the forced sale EXECUTES.**
`equity_margin.py::_submit_pending` puts tickets through `session.submit` against band, tick, lot
and fill policy. **Must-list item 3 does not apply to this path.** Three disclosures:
- **Conflict 7 / D53** — the sale fires **inside the statutory cure window on 8 of 9 calls**. The
  ≤3-business-day ceiling is sourced (QĐ 87 Điều 7.1); the specific period is a contract term; ours
  is not modelling one.
- **§16.4 conflict 3** — a limit order always fills at its own limit, which is conservative for a
  strategy backtest and **anti-conservative fed into a margin ladder**: it understates proceeds and
  manufactures calls. **Measured cost in the equity-margin arms: 9,910,000đ**, and on 2022-10-25
  the forced sale made the ratio *worse* (0.3445 with it, 0.3569 without).
- The scenario docstring is stale on `hard`.

---

# F. Coverage, capacity, robustness

## J7 — Auction-only strategy trading ATO/ATC

*The strategy* — Buy at the open cross, sell at the close cross, every day. Never touch
continuous trading.

*Mechanism exercised* — The auction as a first-class venue phase: which order types each auction
accepts, the single clearing price, and what happens to a remainder.

*Governing policy* — as J14, **including its per-venue auction order-type citations and their
per-venue, per-date grades** (HSX QĐ 352 Điều 14, 15.4, `high` from 2021-07-05 / `low` for the
2020 leg; HNX ASEANSC §2.1/§2.3, `high`; UPCoM MBS 2024-10-14 §4, `high`; HNXDS VNX QĐ 20/21
Điều 22, `high`) — plus:
- HNX has **no opening auction and no ATO at all**; UPCoM has **neither auction**; **PLO** exists on
  HNX's post-close phase and is **unexpressible in our order model** — every order in HNX
  `POST_CLOSE_PLO` is rejected (§16.3 #2, a plain NOT BUILT).
- **UNVERIFIED — allocation at the marginal auction price.** **Not a sourced absence** — a rule
  that plausibly exists and that we could not read; partly answered for the HNX post-close phase
  only (pro-rata by entered volume, ASEANSC HNX sheet) · **low**
- **UNSOURCED (A41, A42)** — the `PRE_OPEN` / `POST_CLOSE` phase names, and the amend/cancel lock in
  those phases. *(The auction lock itself is sourced — QĐ 352 Điều 17.1 — and is unchanged across
  the whole window.)*
- **UNVERIFIED** — whether ATO/ATC foreign orders receive any special room treatment, and whether
  room is re-checked at auction matching under KRX.

*Broken looks like* — Two things, and they are different failures. First, an auction that fills at
a price the auction did not print. Second, and worse: **on an HNX ATC-only book the correct answer
is no price at all**, and a shared routine that reaches for a continuous-style fill would
**manufacture phantom prints** on a venue that never crossed.

*Runnable today* — **No for fills. Blocked by the auction data path** (the brief's known-broken
#4). **The blocker is tracked on the checklist as a SHOULD** (the checklist's *"A shipped
source that carries an auction phase"* item), **not a must-list item** — added 2026-08-27
because this catalogue found it tracked in no section of that file at all. Lifecycle is
exercisable at tick resolution only. Precisely:
- **No adapter serves an `OPEN` phase, and this is an ADAPTER limitation — name the adapter.**
  Daily runs hardcode `CONTINUOUS` at **`datahub.py:436`**, in `DataHubSource`, **which is
  outdated and slated for reimplementation** (author's decision, 2026-08-27); `TickSource`
  implements no `interval()` method and is not an `IntervalSource`; `PhasedBarSource` lives
  in `validation/` and does not ship; `quote_open` is **on disk** and `WITHHELD` by
  `DataHubSource`. **None of this is a limitation of the design, the rulebook or the
  corpus** — the seam is proven to work by `PhasedBarSource`, and the withheld fields are an
  adapter policy that is reversible.
- **`fills.auction_fill_price` is BUILT, and its price is OUR MODELLING CHOICE** (design §8,
  Convention 1) — not a Vietnamese rule, and **not citable to QĐ 352 Điều 6.2(a) or 6.3**.
  Do not describe the auction fill as unbuilt, and do not describe it as sourced. Describe
  the **phase-carrying data path** as missing, the **fill price** as a declared substitution
  of the published open/close for a cross we do not compute, and **marginal-price
  allocation** as **UNVERIFIED** (`low`) returning INDETERMINATE by design.
- **The substitution is a deliberate, stated approximation — no measurement rides with it.**
  We do not trust the auction-window ticks, so we take the day's published close as the ATC
  outcome and the day's published open as the ATO outcome, both already in the database. QĐ
  352 **Điều 2.5** defines the close as *"giá thực hiện tại lần khớp lệnh cuối cùng trong ngày
  giao dịch"* — the day's **last match**, phase-agnostic — which is *context* for why the
  published close is a fair stand-in for the ATC outcome, not a rule that the close IS the
  cross; and *"giá mở cửa"* appears **nowhere in the rulebook**, so **no instrument defines an
  opening price at all** and `interval.open` is a vendor construct. **The price rule itself is
  ours.** J7 buys at the open cross and sells at the close cross, so it leans on the weaker
  half of the approximation (the open) as heavily as the stronger (the close): the open half
  is weaker because HNX and UPCoM run no opening auction at all and a thin HOSE name often has
  none either. **State that asymmetry qualitatively next to any auction result; do not attach
  a number to it.**
- **The full statement, with the three venue conditions under which the substitution is
  wrong, is in J14. J7 is where condition 2 bites hardest**, because an HNX ATC-only book is
  precisely the case where the correct answer is **no price at all** and `auction_fill_price`
  does **no venue check**.
- **LIVE DEFECT that J7 must declare even though its fills are blocked, because its lifecycle
  arm runs at exactly the resolution where it fires.** On a **tick** run the session
  correctly re-stamps the phase to `closing_auction` (`exchange.py:2841-2843`) but
  `_interval_for` synthesises the interval (`exchange.py:2442-2451`), setting
  `close = state.last` and marking `CLOSE` missing **only when `state.last` is None**;
  `auction_fill_price` (`fills.py:608-636`) then returns that as *"the published close"*.
  Continuous matching stops at **14:30** and the cross publishes at **14:45**, so it is a
  **pre-auction print labelled as the auction price** — the tick path does not implement the
  stated close-as-ATC approximation. This is a **design-conformance** defect, not an
  error-size one: the stated model is close-as-ATC and the tick path returns a stale
  pre-auction tick instead. The fix is one condition, and the same function already proves it
  correct: `OPEN` is **always** in `missing`, so the opening-auction branch already returns
  INDETERMINATE; make an ATC fill return the published close, or INDETERMINATE if the close is
  absent. Carried on the publish checklist as a **MUST** (#5, added in the same 2026-08-27
  pass; that file is the authority on its number).

## J8 — Hold across an ex-date

*The strategy* — Hold a position through an ex-dividend or ex-rights date. Report the reference
adjustment, the quantity scaling, and what happened to any resting order.

*Mechanism exercised* — The ex-date reference adjustment and the matching quantity rule — **the one
place in this domain where the traceability claim cannot be met.**

*Governing policy*
- The gazetted **principle**: on the ex-rights date the reference is the most recent close *"điều
  chỉnh theo giá trị cổ tức được nhận hoặc giá trị của các quyền kèm theo"* — QĐ 352 Điều 10.3; QĐ
  17 Điều 32.4; QĐ 22/2026 Điều 33.4 · 2021-07-05 → current · **high**. UPCoM identical except the
  base is the round-lot VWAP of the most recent session — QĐ 34 Điều 19.5 · **high**
- **The actual adjustment ARITHMETIC is NOT IN ANY GAZETTED DOCUMENT** (A26).
  `P' = (P + Σᵢ(Paᵢ × aᵢ) − C) / (1 + Σᵢaᵢ + Σⱼbⱼ)`, quantity `qty × (1 + Σa + Σb)`. **Broker and
  market-education sources only** · **medium**. *"MARK THIS CLEARLY IN THE PAPER."* The conservation
  principle it encodes (market cap unchanged across the event) is what the sources agree on.
- **UNSOURCED (A27)** — the **rounding direction** after adjustment. Rounding *to the tick* is
  gazetted; the direction is stated nowhere. ROUND_HALF_UP chosen because it is the only direction
  with corpus evidence. **our modelling choice.**
- **UNSOURCED (A28) — `RestingOrderPolicy` default `CANCEL`. A CHOICE, NOT A RULE.** *"No Vietnamese
  document addresses what happens to a resting order across an ex-date"*; the day-order rule implies
  cancel. **This is the model documented silence in the repo — imitate its shape.**
- No-adjustment lists **are** sourced and are dated: **9 categories** under QĐ 352 Điều 10.4
  (2021-07-05 → 2022-03-30); **10 categories** under QĐ 17 Điều 32.4 and 32.6 (2022-03-31 →
  current); **8 categories** (a)–(h) on UPCoM under QĐ 34 Điều 19.7 · **high**
- Split and consolidation are framed as a **resumption**, not an ex-date — the stock stops trading
  across the event — QĐ 352 Điều 10.5; QĐ 17 Điều 32.5 · **high**. Corporate-action-driven **halts**
  are sourced: QĐ 17 Điều 40.1 triggers (b) split/consolidation/demerger/charter-capital reduction
  and (c) partial convertible-bond conversion, decision within **5 working days** · **high**. The
  **automatic halt thresholds are UNVERIFIED — never published** (*"cài đặt bằng tham số trên hệ
  thống … sau khi được UBCKNN chấp thuận"*).
- **D27** — the 5% dividend withholding tax is never levied, **and the stated reason in the code is
  false.** But the 5% itself is **not a citable rule as things stand — `low (uncited)`**: it is
  attributed to Luật Thuế TNCN 04/2007/QH12 and TT 111/2013 Điều 10, **neither of which was read**,
  and *"the URL originally attached is a 2018 article about the 0.1% transfer tax that does not
  mention dividends, the 5% rate, or Điều 10 at all"* (rulebook §8.1; `FEATURES.md` A32 repeats
  `low (uncited)`). Almost certainly correct as background law. **Do not state it as fact.** What
  would settle it: the operative text of TT 111/2013 Điều 10.

*Broken looks like* — The position's value jumps discontinuously across the ex-date because the
reference moved and the quantity did not (or vice versa) — a free gain or loss on a day when
nothing happened economically. Or a resting order surviving the event at a pre-adjustment price.

*Runnable today* — **Yes, caller-driven only.** **`CorporateActionEngine` is not wired into
`advance_to`** — `grep -r 'CorporateActionEngine\|apply_due' src/` hits `corporate.py` and nothing
else. This is deliberate (a CA feed is exogenous data), but the consequence must be stated: **a run
that crosses an ex-date applies nothing unless the caller drives the engine.** `CorporateActionAudit`
is opt-in. Related and cheap: `state_at('PLX', 2022-11-09)` returns `reference=29.45` (stale) with
`ceiling=30.20, floor=26.30` — **internally inconsistent by 4.1%**, and `reference == mid(ceiling,
floor)` would be an invariant nobody checks.

## J9 — Thin-name strategy (HTV): the cap binds and the book is stale

*The strategy* — Run a rule on a genuinely illiquid HOSE name. Watch the participation cap bind
and the quoted state go stale.

*Mechanism exercised* — Two halves that must be kept apart, and keeping them apart **is** the
scenario. The **rule** half — band, tick, lot, admission — is sourced and dated. The **data** half —
how much of the print you could have had, and how old the book is — is not a rule at all.

*Governing policy*
- Rule half, all sourced: HSX tick tiers 10 / 50 / 100đ with the boundary at **exactly 50,000 →
  100đ** (QĐ 352 Điều 8.4, *"≥ 50.000"*, and **the primary text wins** over MBS's *"> 50.000"*) ·
  **high**; lot 100 and odd lot 1–99 (dated per J17); band ±7% · **high**
- **REJECTED phantom rules that a thin-name scenario invites**: the **500đ tier** (FPTS is wrong —
  QĐ 352 Điều 8.4, Phụ lục III of every VNX rulebook and a 99.997% corpus fit all give **three**
  tiers) and the **flat 1đ HOSE tick** (a TCBS page misreading the *negotiated-trading* row as the
  general rule) · **high**
- **UNSOURCED — the participation cap is ours, not a rule** (A34). No Vietnamese document caps a
  participant's share of a print. **our modelling choice.**
- **UNSOURCED — queue position** (as J21).
- **UNSOURCED — the staleness budget (U18), and it is half of this scenario's own title.**
  *"The book is stale"* is not a rule and has no default: `book_walk.py:1258-1261` requires
  `max_staleness` from the caller alongside the queue policy and the participation cap,
  *"because each one changes which orders are answerable and a default would make that choice
  invisible"*. **The choice is decision-changing**: the largest per-level gap in the corpus is
  **5,412 s** — the lunch break, 11:30:01 to 13:00:13 — so *"a budget picked off the 35 s
  median discards the entire book on the first tick after lunch"* (`book_walk.py:1293-1297`).
  **Size it against the lunch break, publish the number next to the result, and treat a
  staleness sweep the way J20 treats a fill-policy sweep — as the error bar, not a setting.**
  **our modelling choice.**
- **Overclaim to fix**: `tick.py:157` labels evidence `TICK_BOOK` "not locked" where it has not
  established that.

*Broken looks like* — A thin name behaving like a liquid one: full fills at the quote on days with
almost no volume. The correct output on a thin name is **more INDETERMINATE, not more fills** —
`Blindness.CAP_UNCOMPUTABLE` where volume is unknown, `CAP_EXCEEDED` where it binds.

*Runnable today* — **Partial. The rule half runs; the staleness half is not reachable from a
config.** **MUST #1 has LANDED** (commit `c6b7ef6`, 2026-08-27), so J9 is no longer *blocked
by a must-list item* — it carries the same **two residuals** J21 does: `book_walk.py` /
`adapters/depth.py` are **injection-only** (reachable via `ExchangeSession.build(...,
fill_policy=...)`, refused by `build_fill_policy` from a config block, `fills.py:2260-2276`)
and the depth data is a **dev extract**, not the wired corpus. **Not the same thing as
unreachable** — see J21 for the distinction this document now keeps, and for why J21 moved
to *partial* on the same evidence that has always kept J9 there. Volume coverage is
**62.9%**. And the staleness budget itself is a required, unsourced caller choice: **U18**.
- **"Dev extract" is a WINDOW limitation, not a missing-data one.** The corpus **does** carry
  order-book sizes: `/Users/nadan/algotrade-research/dataset/hermes-dev-extract` holds **1,390,914 size rows across four
  Parquet files**, each with a `depth` column, and production carries 666M/590M. What
  `depth.py:1-10` actually says is that the extract answers *"for some windows and not
  others"* and that the two sides are never observed together, so a book here is
  **reconstructed, not observed**. **Never write that we lack sizes** — it is a fetch, and
  HTV's own staleness numbers were measured off these files.

## J23 — A 30-name VN30 basket

*The strategy* — Trade a 30-name basket in one session, out of one account. Multi-ticker at scale.

*Mechanism exercised* — Mostly a system property rather than a Vietnamese rule: per-name
encumbrance, per-name settlement clocks, and one cash ledger serving thirty of them.

*Governing policy*
- The per-name rules are J1's and J2's, resolved independently per order. Nothing about a basket
  changes them.
- **SOURCED AND NOT BUILT — the simultaneous opposite-side order ban.** TT 120/2020 Điều 7 prohibits
  placing buy and sell orders for the same security within the same matching session, with limited
  carve-outs · 2021-02-15 → current · **medium**; predecessor TT 203/2015 Điều 7 from 2016-07-01;
  **carve-outs and exact clause number UNVERIFIED**, and *"whether the ban is per matching session or
  per trading day was not resolved, and it changes admission logic"*. **No implementation exists.
  State it as an unmodelled rule with an unresolved scope; do not pick a reading.**
- **The self-crossing ban — and the word "sourced" was doing work here with nothing behind
  it.** An earlier draft read, in full: *"The self-crossing ban is likewise sourced and NOT
  BUILT (§16.3 #13)"* — no instrument, no venue, no dates, no grade, the only such bullet in
  a launch-adjacent scenario. **What the rulebook actually has is one row and it does not
  cover J23.** Rulebook `:208`: *"Self-crossing in continuous trading"* — **HNX**,
  **2025-05-05 → current**, **medium**, `kind = exchange`, sourced to an **ASEANSC broker
  sheet, not a gazetted article**. The rule as stated: while your buy or sell rests or is
  partly filled you may not enter a sell priced at or below your resting buy, or a buy at or
  above your resting sell.
  - **J23 is a 30-name VN30 basket, i.e. HOSE.** No HOSE self-crossing row exists in the
    rulebook at any date. So for this scenario the honest label is **UNVERIFIED** — a rule
    that plausibly exists on HOSE and that we have not read — **not "sourced"**.
  - **Do not extend `:208` to HOSE by analogy**, and do not extend it before 2025-05-05 on
    any venue. It is a one-venue, one-interval, secondary-sourced `medium` row.
  - **NOT BUILT** either way (§16.3 #13) — which is the same repair already made at J14 for
    the auction fill and missed here.

*Broken looks like* — Per-name state bleeding between names: one ticker's settlement clock or
encumbrance applied to another, or a basket-level cash figure that does not equal the sum of its
legs. At three names this is invisible; at thirty it is not.

*Runnable today* — **Yes — already run at 30 names.** One disclosure:
**`OrderBookOfRecord.encumbrance_divergence` is UNREACHABLE — no caller in `src/`**, so per-name drift is **invisible**
— the per-order form of the encumbrance invariant exists precisely because the totals form is
sampled where nothing is live and both sides are zero, *"which is why a 2,034,329đ divergence
lasting the whole life of a resting order read as clean."* Until it is wired in as a breach source,
**the harness cannot see that class of defect and must not claim it can.**

## J24 — A strategy that runs out of cash mid-run

*The strategy* — Size aggressively until the account cannot fund the next order. Report the
refusal, the binding constraint, and the advance headroom if any.

*Mechanism exercised* — Funding admission: pre-funding, encumbrance, and the sale advance as
the only route to spending unsettled money **on a domestic retail cash account**. The scope
clause is load-bearing and is not decoration: **"the only legal way" without it is false**, and
it is refuted by the same statute this scenario cites (see the carve-outs below).

*Governing policy*
- **The exclusivity is scoped, not absolute.** Two carve-outs sit in the operative text and a
  third route sits outside the cash-account regime entirely:
  - **Margin trading (Điều 9) and day trading (Điều 10)** — *"ngoài trừ giao dịch ký quỹ, giao
    dịch trong ngày theo quy định tại Điều 9, Điều 10 … nhà đầu tư chỉ được đặt lệnh mua khi
    đã ký quỹ đủ tiền"*, TT 203/2015 Điều 7(2) verbatim; repeated as "exceptions Art. 9
    (margin) and Art. 10 (day trading)" in TT 120/2020 Điều 7(1)(a) · **high**. *(Day trading
    is legally provided for and **never operational** for want of a VSDC SBL system — a
    different fact from its not being a carve-out.)*
  - **Non-pre-funding for foreign institutions** — a foreign **institutional** investor may
    place **share** buy orders without full cash at entry; cash must reach the depository
    member's account at the settlement bank by **10:15 on T+2** — TT 68/2024/TT-BTC ·
    2024-11-02 → current · **medium**. Does not extend to foreign individuals or to any
    domestic investor.
  - So J24 must say **domestic retail cash account**, or drop the word "only".
- **Buy-side pre-funding** — an investor may place a buy order only with sufficient cash
  **already** in the trading account; the duty is on the securities company to refuse
  uncovered orders. **Two instruments, and TT 120/2020 did not exist in 2016**:
  - **TT 203/2015/TT-BTC Điều 7(2)** (signed 2015-12-21, effective **2016-07-01**) ·
    2016-07-01 → 2021-02-14 · **high**
  - **TT 120/2020/TT-BTC Điều 7(1)(a)** (signed 2020-12-31, effective **2021-02-15**) ·
    2021-02-15 → current · **high** (rulebook `:521`, verbatim: *"Nhà đầu tư chỉ được đặt
    lệnh mua chứng khoán khi có đủ tiền trên tài khoản giao dịch"*)
  - **The RULE is `high`; the BOUNDARY DATE is softer than the row it sits in.** *"TT 120's
    own commencement article was not read; 2021-02-15 is the conventionally cited date"* —
    rulebook `:249`, which grades the row carrying that date **medium**, and Open Question
    **#26** still lists TT 120's full text as unobtained. So carrying `:521`'s `high` for
    *what the rule says* is right; **do not print 2021-02-15 bold as though the boundary
    itself were gazetted-verified.** Nothing in J24 turns on it — both sides of the boundary
    impose the same 100%-at-entry duty, and the predecessor for 2020-01-01 → 2021-02-14
    (believed TT 203/2015) is itself unverified at `:249` — which is exactly why the softness
    is cheap to state and would be embarrassing to omit.
- **Sell-side availability duty** — sell only for securities already available in the
  depository account — TT 203/2015 Điều 7 → **TT 120/2020 Điều 7(3)** · 2016-07-01 → current ·
  **high**. *Điều 7(3) is the sell side; it is not the buy-side pre-funding article.*
- The advance: statutory permission **Luật Chứng khoán 54/2019/QH14 Điều 86(1)(b)** with prior
  written SSC approval · **high**; price, cap and day-count are **broker commercial terms** (J15).
- **UNSOURCED / assumed — A4** (rate 0.00031/day, matching **no observed firm** and not the
  rulebook's recommended 0.00035/day), **A7** (the unsourced 100% cap), **A8–A13** (basis, accrual
  stop, tranche allocation cheapest-interest-first — *a declared choice with no source*), **A15**
  (headroom floors ROUND_DOWN). All **our modelling choices**.
- **D28** — `ledgers.py:628`, `:726`, `:1221` cite **"rulebook 8.4"**; **§8 runs 8.1–8.3, so
  that section does not exist.** The content is §5.2: Luật Chứng khoán 54/2019 Điều 86(1)(b)
  (`:628`, **high**) and TT 121/2020 Điều 27 (`:726`, `:1221`, **low**).

*Broken looks like* — A strategy that keeps trading after the money runs out — the classic silent
backtest failure, because a nonexistent order has no fill and therefore no trace.

*Runnable today* — **Yes.** Two disclosures that materially change the numbers:
- **Advance interest is reported and never charged.** *An advance is free in every balance
  reported.* Direction: permissive, and it is exactly the cost that J15 and J16 exist to make
  visible.
- **D13** — funding refusals never reach the event cursor, so a caller polling events does not see
  them.

## J27 — Amend a resting order: up, down, and across the price

*The strategy* — Rest a buy LO. Then try three amendments on it, in this order: **raise the
quantity** (an amend-up), **change the price**, and **lower the quantity**. Print what each
one returns, what the encumbrance ledger holds after each, and whether queue priority
survived. **This scenario exists because must-list item 2 was exhibited by no other scenario
in this catalogue** — `grep -i amend` over the earlier draft returned only the Vietnamese
amendment *rules*, never the defect they sit on.

*Mechanism exercised* — Amendment is the one instruction that can change an order's
**funding requirement** and its **admissibility** after admission has already run. Vietnam
dates all three of the rules that govern it — whether priority survives, whether price and
quantity may move together, and whether the phase permits an amendment at all — and none of
those rules says anything about re-checking money or lot size, because that is the
**broker's** duty, not the exchange's. So this scenario runs a sourced rule and an unsourced
duty against each other, and the gap between them is publish-checklist **MUST #2**.

*Governing policy*
- **Priority-preserving amendment is dated, and for the first two years of the window it
  does not exist.** The three legs are printed in full under **J21** and are not restated
  here: QĐ 352 **Điều 17.1–17.3** (2020-01-01 → 2022-03-30, HOSE, amendment *is*
  cancel-and-re-enter and time priority **always** restarts) · **high**; VNX **QĐ 17 Điều
  22.3** (2022-03-31 → 2025-05-04, preserved **only** on a quantity reduction) · **high**;
  VNX **QĐ 22/2025 Điều 21.3** (2025-05-05 → current, one amendment may change price **or**
  quantity, never both) · **high (HNX/UPCoM/HNXDS) / medium (HOSE)** — the HOSE half is an
  unresolved CONFLICT, because HOSE's own publications omit the simultaneity ban (rulebook
  `:224`; KRX-delta `:1155`), and J21 carries the split grade in full. *Do not cite "QĐ 352
  Điều 21.3" for any of this — Điều 21 is the lunch break.* **`PUBLISH-CHECKLIST.md` MUST #2 carried that error and no longer
  does**: it was corrected there on 2026-08-27, and its row now opens *"This row's citation
  was wrong and is corrected here."* The error is recorded rather than deleted because the
  checklist's own first rule was learned from it — *"Cite the instrument, not the number you
  remember"* — and because this catalogue **inherited it verbatim**, which is the more
  useful warning to a reader than the fact that it is fixed.
- Amend/cancel are **locked for the whole duration of an auction** — QĐ 352 Điều 17.1; VNX
  QĐ 17 Điều 22; QĐ 22/2025 Điều 21 · 2020-01-01 → current · **high**. Unchanged across KRX;
  several write-ups present it as a KRX novelty and it is not.
- **Buy-side pre-funding is what an amend-up would escape** — an investor may place a buy
  order only with sufficient cash **already** in the trading account, and the duty to refuse
  an uncovered order is the securities company's: TT 203/2015 Điều 7(2) · 2016-07-01 →
  2021-02-14 · **high**; TT 120/2020 Điều 7(1)(a) · 2021-02-15 → current · **high** (see
  J24 for the carve-outs, which do not reach a domestic retail cash account).
- **Round lot is what a quantity amendment can violate — and it is TWO rows, not one.** An
  earlier draft graded the whole span `high (value) / medium (citation)` and attached **QĐ
  894 to a period QĐ 894 did not govern**. QĐ 894/QĐ-SGDHCM is dated 2020-12-30 and applied
  **2021-01-04**; it cannot be the citation for the leg that ends 2021-01-03. **J17 gets
  this right and this is J17's split, copied:**
  - **HSX 10 units · 2020-01-01 → 2021-01-03 · medium** — QĐ 67/QĐ-SGDHCM (2018-03-02) **as
    it stood before QĐ 894 — never read** (rulebook `:432`). The 10→100 step and its date
    are corroborated by press and broker notices; **nothing confirms the value 10 itself**.
  - **HSX 100 units · 2021-01-04 → current · high (value) / medium (citation)** — QĐ 894,
    applied 2021-01-04; restated in QĐ 352 Điều 8.1; QĐ 17 Phụ lục III §1.1 (rulebook
    `:434`). The `high (value)` grade is **this row's and belongs only to this leg**; the
    `medium (citation)` is because the cited URL is a VnEconomy article, not the decision.
  - **This split is load-bearing for J27, not decorative**: the live defect below is that a
    permitted quantity decrease is never re-checked against `ROUND_LOT`, and *whether*
    100 → 50 is illegal depends entirely on which side of 2021-01-04 the amendment sits.
    Before it, 50 is a legal round lot; after it, 50 is an odd lot with nowhere to trade.
- **sourced absence — no Vietnamese document requires an exchange to re-run funding or
  admission on an amendment.** It could not: pre-funding is a duty on the securities
  company, and the round-lot rule binds the order, not the amendment. **So MUST #2 is a
  defect against OUR OWN design section 5, not against a Vietnamese rule** — design §5:
  *"amending must re-run the encumbrance so an amend-up cannot escape funding"*. Saying this
  plainly matters: a reader must not come away thinking a gazetted article was broken.
- **our modelling choice, recorded as ADOPTED in `detail['adopted']`** — two refusals the
  rulebook does not settle, both in `orders.py::amend`: amending a **non-resting** type is
  refused (*"every amendment rule in rulebook 2.5 names the LO"*, and there is no window in
  which an ATO, MOK or MAK could receive one), and amending quantity **below what is already
  filled** is refused (*"No Vietnamese document addresses it. ADOPTED, because the
  alternative breaks `filled + remaining == original`"*).
- **UNSOURCED — no event.** `EventKind` carries no `AMENDED` member, so an amendment reaches
  a caller only through the returned `Amended` and never through the cursor. A design choice
  (*"an amendment is not a state transition, the state is unchanged"*), not a rule.

*Broken looks like* — Four failures, and they are the reason to run this rather than read
about it. **(1)** An amend-up is accepted and the reservation does not grow, so the account
holds a live order it cannot fund and the shortfall never appears in any balance — the same
silent class as J24's "keeps trading after the money runs out", except that here the order
*was* funded once. **(2)** A quantity amendment lands on an illegal size and the order rests
anyway: 100 → 50 on HOSE after 2021-01-04 is an **odd lot with nowhere to trade** (J17), and
nothing rejects it. **(3)** A pre-2022-03-31 HOSE amendment reports `priority_preserved=True`
when the instrument in force says priority **always** restarts — queue position invented in
the strategy's favour. **(4)** An amendment succeeds mid-auction, in the phase every rulebook
in the window locks.

*Runnable today* — **Yes — and every one of the four amendments is worth printing, because
two are sourced refusals, one is a declared scope cut and one is the live defect.** What the
shipped session actually does:
- **The amend-up is REFUSED, and MUST #2's own wording is wrong about this.** The checklist
  says *"an amend-up escapes both"*. At session level it does not:
  `exchange.py:1632-1636` refuses any `quantity >= record.original_quantity` with
  *"Tier 1 amends only downward: an amend-up must re-run the encumbrance so it cannot escape
  funding, which is Tier 2"*, and `exchange.py:1625-1631` refuses **any** price amendment for
  the same reason (*"the reservation was taken at the old price, and re-running it needs a
  release-and-retake that can fail after the release and leave a live order unfunded"*).
  Both come back as `Rejected` with `detail['adopted'] = True`, marked a tier boundary.
  **Direction: RESTRICTIVE.** This is a scope cut that refuses, not a hole that leaks — and
  it is the honest headline of J27.
- **The escape is real one layer down.** `OrderBookOfRecord.amend` (`orders.py:935-1040`) is
  a public object a caller can reach directly, and it **does** accept a price change and a
  quantity increase. It runs the phase lock, the both-fields dated flag and the
  already-filled check, then `_store(replace(...))` — **no admission re-check and no
  encumbrance re-take at either layer.** A caller driving the book instead of the session
  gets exactly the defect the checklist describes.
- **The permitted amendment is the quantity decrease, and it over-reserves.** The original,
  larger reservation stays in place (`exchange.py:1618-1621`) and is released whole at the
  terminal edge. **Direction: CONSERVATIVE**, and declared.
- **LIVE DEFECT, and it is the admission half of MUST #2: the permitted decrease is never
  re-checked against `ROUND_LOT`.** No amend path in `exchange.py` or `orders.py` reaches an
  admission rule — `grep -n "ROUND_LOT" src/plutus/market/session/orders.py` returns nothing
  in `amend`. **Amending 100 → 50 on HOSE after 2021-01-04 leaves a resting order for an
  illegal quantity**, and J17 is the scenario that says an odd lot there has nowhere to
  trade. Note the direction: it is *not* symmetric with the funding half. Funding is refused
  outright; **admission is silently skipped.**
- **LIVE DEFECT, newly found by this pass and load-bearing for J21: the session never passes
  the dated `priority_preserving` flag.** `orders.py:387` states that the flag is *"resolved
  from `rulebook.at(ts)`"* by `exchange.py`. It is not. `exchange.py:1640-1642` passes
  `quantity`, `phase` and `allow_price_and_quantity` — and **not** `priority_preserving`,
  which therefore takes its signature default `True` (`orders.py:944`). The only caller in
  `src/` that passes it at all is `corporate.py:1853`, and it passes `False`. Consequence:
  on a **2020-01-01 → 2022-03-30 HOSE** run a permitted quantity decrease reports
  `priority_preserved=True`, while QĐ 352 Điều 17.1–17.3 (`high`, read verbatim) says
  priority **always** restarts in that interval. **Two years and three months of the sample
  window get a queue position the rulebook denies them, in the permissive direction** — and
  it is the same quantity J21 exists to put an error bar around. `allow_price_and_quantity`
  is resolved correctly (`exchange.py:2108-2115`), so the miss is one flag, not the pattern.
- **Not demonstrable: the auction lock.** The lock is sourced and implemented
  (`orders.py::amend_cancel_lock`), but no shipped adapter ever puts the session into an
  auction phase — the same blocker as J14 and J7 — so the phase-refusal branch cannot be
  reached over the wired corpus. **Exercisable at module level only, and say so.**
  **Attribute it to the adapter by name**: `DataHubSource` hardcodes
  `session=SessionPhase.CONTINUOUS` (`datahub.py:436`), and **DataHub is outdated and is
  slated for reimplementation** (author's decision, 2026-08-27). This is not a limitation of
  the design, the rulebook or the corpus — `PhasedBarSource` builds real ATO/ATC intervals
  and proves the seam works; it lives in `validation/`. *(J27's amendments are refused
  before any fill, so the live tick ATC defect in J14 does not reach this scenario — the
  auction issue here is admission, not price.)*

## J25 — A strategy meeting a data gap

*The strategy* — Point a strategy at a window where the data is incomplete, and read what the
simulator says about what it could not know.

*Mechanism exercised* — The ignorance meter. **This is the scenario that demonstrates the project's
central discipline: an unknown is reported as INDETERMINATE, not resolved by a guess.**

*Governing policy*
- Nothing here is a Vietnamese rule, and that is the point. `Blindness`, `decided_without` and the
  INDETERMINATE verdict are **our modelling choices** — the machinery by which an absent source or
  an absent datum becomes an output rather than a silent default.
- The **absences the meter reports** are named per scenario above, and they are **not all the
  same kind** — the label table at the top of this document makes *sourced absence* and
  *UNVERIFIED* mutually exclusive, so each is carried with the one label it earns:
  - **sourced absences** (the documents were read and the thing is not in them): no maintenance
    margin ratio at any date; no document caps a participant's share of a print; no document
    states a fill probability; no Vietnamese document addresses a resting order across an
    ex-date.
  - **UNVERIFIED** (a rule that plausibly exists and that we could not read): **allocation at
    the marginal auction price** · **low**. This is the one J7 and J14 are blocked by, so the
    label has to be right — it is *not* a sourced absence, and claiming it as one would assert
    that all four rulebooks were read on the point.
- `DataHubSource.SERVES` / `WITHHELD` is the honest declaration of the data contract: **`quote_open`,
  `quote_max`, `quote_min` are on disk and deliberately not served**, and every fill counts them as
  `fill.decided_without.{open,high,low}`. **Two things this scenario must not let a reader
  conclude.** (i) *"Not served" is an ADAPTER policy, not an absence* — the fields are on
  disk, `DataHubSource` is **outdated and slated for reimplementation** (author's decision,
  2026-08-27), and the declaration is reversible. **Never attribute a DataHub limitation to
  the design, the rulebook or the corpus.** (ii) **`BOOK_SIZE` is withheld and order-book
  sizes EXIST**: `/Users/nadan/algotrade-research/dataset/hermes-dev-extract` carries **1,390,914 size rows across four
  Parquet files** with a `depth` column, and production carries 666M/590M. The ignorance
  meter reporting `decided_without.book_size` is the adapter being honest about what *it*
  serves — **it is not evidence that the data is unavailable**, and any claim that we cannot
  compute our own clearing price for want of sizes is false. It is a fetch.

*Broken looks like* — A clean-looking run over data that could not support it. Specifically:
**`indeterminate == 0` is NOT the predicate** — use `is_clean`. And `evaluations` **mixes four
populations**, so a ratio computed off it is not a rate of anything.

*Runnable today* — **Yes — the highest-value scenario in Group F.** One caution: the 18
INDETERMINATE sites are **a code fact to re-derive at publication time, not a citable catalogue**.

---

# G. The headline

## J10 — A strategy that passes a naive fill-at-close backtest and fails here

*The strategy* — One strategy, two runs over the same window and the same data. Arm A fills every
signal at that session's close. Arm B runs through the exchange: admission, band, tick, lot,
settlement, charges, margin. **The gap is the whole value proposition.**

*Mechanism exercised* — Everything above, composed. The point is not any single rule; it is that
the assumptions a naive backtest makes silently are, individually, each traceable to a document —
and collectively worth a measurable amount of money.

*Governing policy* — every citation in this catalogue, resolved by date. The four that carry the
delta:
- **Settlement as a capacity constraint** — TT 120/2020 Điều 7(3) and the T+2 cycle (**high**). Sale
  proceeds appear in the T+2 afternoon, not at the print, **so a naive run's turnover is
  unachievable — and achieving it costs the advance fee, which this simulator reports and does not
  charge.**
- **The band lock, which no naive backtester has at all** — QĐ 352 Điều 9.1–9.6 arithmetic plus
  price-then-time priority (**high**), with the one-sidedness **INFERRED** and the evidence ladder
  **UNSOURCED**.
- **Margin is a leverage multiplier — no.** Two products, two regimes: equity `imr ≥ 50% / mmr ≥ 30%`
  (QĐ 87 Điều 5(1),(2), **high**) versus derivatives IM 0.10 / 0.13 / **0.17 @ 2022-12-15** with **no
  maintenance ratio published at any date** — and **the IM values have no gazetted citation**, only
  thông báo.
- **A backtest that crosses an ex-date is fine — no.** The reference is adjusted and the quantity is
  scaled, and **the arithmetic is NOT IN ANY GAZETTED DOCUMENT** (A26) · **medium**. *The one place
  the traceability claim cannot be met.*

*Broken looks like* — **The delta is zero.** If the two arms agree, either the exchange layer is not
on the path or the naive arm is not naive. The delta is already measured in two places, so this
scenario can be quoted rather than argued:
- **`equity-margin`, same window, same strategy, same 31 sessions**: **0 fills / no debt / ratio
  1.000 / no margin call** under one set of assumptions, against **3 fills / 69,079,147đ of margin
  debt carried / 6 margin calls** under the other.
- **`pair-trade`**: BUY 300 ACB @ 22.00 on 2022-10-21 fills at 22.00 when ACB's maximum matched price
  that day was **21.40**.
- **HPG 2022-10-31**: the forced sale is `Rejected(BAND_LOCK)`. **A fill-at-close backtester sells;
  this one cannot.**

*Runnable today* — **Yes — the most runnable of the twenty-seven.** It needs only two arms over
the wired Parquet corpus and the existing charge engine. **Five disclosures must ride with it,
and the first two are the ones that would embarrass us if a reader found them first:**
1. **§16.4 conflicts 3 and 4 exactly cancel on the daily corpus.** A limit order always fills at its
   own limit (conflict 3) **and** `state_at` returns the whole-day bar at any intraday instant
   (conflict 4), so `limit == fill_price == that session's close` on **every one of `pair-trade`'s
   93 fills**, which is why a naive-looking result and an honest-looking meter coexist. **J10 must
   disclose this or it will overclaim its own headline.**
2. **Conflict 4 is the single highest-value remaining fix and it wants the author's sign-off.**
   `quote_open/high/low/dailyvolume` are on disk (620 rows each for open and volume across 31 names
   × 20 sessions) and the adapter reads none of the extremes. **The conclusion — an adapter gap
   misattributed to the corpus — is right, and both evidence pointers an earlier draft gave were
   wrong.** Corrected:
   - **Not `exchange.py:1790`**, which is an `INSUFFICIENT_CASH` rejection on a pool transfer and
     has nothing to do with this.
   - The synthesis site is **`exchange.py:2442`**, and it is **CONDITIONAL, not
     unconditional**: it is reached only after `if isinstance(source, IntervalSource): served =
     source.interval(...); if served is not None: return served` fails to produce an interval.
     `DataHubSource` **does** serve intervals (`datahub.py:305`), so the shipped adapter never
     reaches line 2442 at all.
   - **The actual mechanism is one line of adapter policy**:
     `DataHubSource.WITHHELD = {OPEN, HIGH, LOW, BOOK_SIZE}` (`datahub.py:196-198`). The fields
     are on disk and the adapter declares that it will not serve them. That declaration is
     honest — it is why every fill counts them in `fill.decided_without` — but it is **ours,
     and reversible**, which is exactly what makes this the highest-value fix rather than a
     corpus limitation. **Attribute it to the adapter by name and say the rest**:
     `DataHubSource` is **outdated and slated for reimplementation** (author's decision,
     2026-08-27), so this is a fix that is already scheduled, not a standing constraint. And
     the fourth withheld field is the sharpest case: **`BOOK_SIZE` is withheld while
     1,390,914 order-book size rows sit in `/Users/nadan/algotrade-research/dataset/hermes-dev-extract`** across four Parquet
     files with a `depth` column, with 666M/590M in production. **Never write that this repo
     lacks order-book sizes.**

   Fixing it moves **every number in every scenario** in both directions. Against the tick
   archive the daily-close mark already produces a **missed forced close** (2022-11-11 14:00,
   true utilisation 1.0284), a **missed warning** (2022-11-15 09:30) and **two
   forced-liquidation reports at instants when the account was `ok`**. **Read those three
   phrases with disclosure 5**: they are mis-timings of a *report*, and no forced close in
   this simulator closes anything at any instant.

   **And if J10's honest arm is ever run at TICK resolution, it inherits the live ATC
   defect** — any fill landing in a closing-auction phase gets `state.last`, a **pre-auction**
   print, served as *"the published close"* the stated model does not intend: the tick path
   does not implement the close-as-ATC approximation. J10's whole claim is a *delta between
   two arms*, so an auction fill the model did not intend contaminates exactly the spread the
   headline turns on. Full statement in J14; it is a publish-checklist MUST (#5), on
   design-conformance grounds. **On a daily run it cannot fire** (`DataHubSource` stamps every
   bar `CONTINUOUS`, `datahub.py:436`), so the currently-measured deltas are unaffected.
3. **The naive arm must be built in this repo**, not imported, or the delta is confounded with two
   different charge engines. `compare_policies` will not do it — it reports fills, not P&L.
4. **The honest arm also omits charges, so the delta is a LOWER BOUND** on the true cost gap: no
   MONTHLY/DAILY accrual (**custody 0.27đ/unit/month** from 2020-03-19 — TT 14/2020, continuous
   into TT 101/2021 Phần A Mục III điểm 13 · **high**; **derivatives position management
   2,550đ/open contract/account/day, 2020-03-19 → 2021-12-31** — TT 14/2020, end date corrected
   by the rulebook from 2025-04-28 because *"giá dịch vụ quản lý vị thế does not appear in TT
   101/2021 Phần B Mục III"* · **high**; the catalogue uses **inclusive** end dates, so the last
   chargeable day is 2021-12-31, not 2022-01-01 — from 2022-01-01 the same 2,550đ appears only as
   a per-contract **clearing** fee in broker schedules, and *"do not merge them"* · **medium**;
   all never levied because `assess_daily` has **zero call sites in `src/`**), no VSDC collateral-management
   fee, no settlement-bank charge, no VAT, no dividend withholding, and tiered commission implemented
   and unwired. **A69** applies to both arms, so it does not inflate the delta — but a reader will ask.
5. **Both derivatives must-list items are on J10's path and both were missing from this list.**
   Disclosure 2 prints *"missed forced close"*, *"missed warning"* and *"two forced-liquidation
   reports at instants when the account was `ok`"* — every one of those is on the derivatives
   margin path, and neither item 3 nor item 4 appeared anywhere in J10's disclosures before this
   pass. The honest form:
   - **Must-list item 3 — no forced close in this simulator closes anything.** `detail['executed']`
     is `False` on every `FORCED_LIQUIDATION`. So *"missed forced close"* means **a report that
     did not fire**, not **a liquidation that did not happen** — the unmissed one would not have
     closed a position either. Measured on the same family of runs: 24 forced liquidations across
     12 sessions with the position intact through all of them, **17.6% of a 100,000,000đ account**.
     Direction: **PERMISSIVE**, and it is the same direction as the naive arm's error, so it
     **shrinks the headline delta** rather than inflating it.
   - **Must-list item 4 — variation margin never settles in cash**, so the deposit balance J10's
     honest arm reports never moves with the day's P&L (`settle_daily` is UNREACHABLE, no caller in `src/`;
     **A60**: VM is cumulative since-entry unrealised loss, not the day's adverse move).
   - **Consequence for the headline**: J10's measured delta is a **lower bound on two independent
     axes** — omitted charges (disclosure 4) *and* the two permissive margin items. Say lower
     bound; do not say measured cost gap.

---

# The unsourced register

Every mechanism a scenario exercises for which no Vietnamese document exists, or for which the
document exists and we could not read it. **Nothing here may be stated as a Vietnamese rule.**
This is the list to check a scenario page against before publishing it.

**UNSOURCED — no document, at any date**

| # | Mechanism | Scenarios |
|---|---|---|
| U1 | `HardFillPolicy.max_participation = 0.10`, and the entire participation-cap concept (A34) | J20, J22, J9, J4 |
| U2 | `ProbabilisticFillPolicy.p_touch = 0.5` (A35) | J20 |
| U3 | All three queue policies, and any statement about our position in the time queue | J21, J9 |
| U4 | The `LockEvidence` ladder (`TICK_BOOK` / `BAR_PROXY` / `UNKNOWN`) | J2, J11, J10 |
| U5 | Equity-margin `call_level` / `force_level` at **any** Vietnamese broker — no verified counterpart at any firm | J5 |
| U6 | Force-sale execution price; liquidation ordering; proceeds-application ordering (QĐ 87 Điều 12.2(i) delegates both orderings **by name**) | J5 |
| U7 | Interest day-count, compounding and accrual convention (QĐ 87 Điều 11.4 delegates entirely) | J5, J24 |
| U8 | `RestingOrderPolicy` default `CANCEL` (A28) — *the model documented silence* | J8 |
| U9 | Rounding direction after a corporate-action adjustment (A27) | J8 |
| U10 | Rounding to whole đồng, ROUND_HALF_UP — **UNVERIFIED for every charge** (A14) | J4, J10 |
| U11 | Sale-advance rate, cap, day-count and minimum (A4, A7–A13) | J15, J16, J24 |
| U12 | `PRE_OPEN` / `POST_CLOSE` phase names (A41); the amend/cancel lock in those phases (A42) | J7, J25 |
| U13 | Derivatives utilisation ladder 80/90/100 (A1–A3) — **the REGULATORY half only, and this row was over-broad before.** No Vietnamese document sets a margin-utilisation ladder: **QĐ 26 Điều 13 is a binary test with no percentage of any kind**; the 80/90/100 in QĐ 26 is **Điều 29, position limits**; pre-KRX it is **UNVERIFIED, not disproven** (see the UNVERIFIED section). **The BROKER half is NOT unsourced** and does not belong in this table — `broker_profile.py` derives its ladder from a named-firm survey with per-rung `n`, pool and exclusions recorded (`broker_profile.py:2302-2330`), and `FEATURES.md`'s *"Broker margin profiles wired into the session"* row grades the subsystem `IMPLEMENTED + SOURCED (per firm)`. **UNSOURCED means no Vietnamese *document*, not no evidence.** **And the ladder is per-firm, not one number**: `to_broker_terms()` run over all 18 profiles gives ten ladders and eight stated refusals, with top rungs from 0.85 to **1.00** — see J3 for the table. | J3, J4, J19 |
| U14 | A **bare** `BrokerTerms()`' defaults **0.80 / 0.90 / 1.00** (`broker.py:136-138`), and treating `assets == MR` as BREACH where QĐ 26 Điều 13.2(c) treats it as CURED. **This IS the out-of-the-box ladder**: `exchange.py:732-734` returns `BrokerProfile.from_config(payload)` when no firm is named and `types.py:2517` gives it a bare `BrokerTerms()`. **Scope corrected twice, and the second correction reverses part of the first.** Naming a firm runs `to_broker_terms()`, which produces a **derived** ladder rather than this unsourced one — but **not always 0.95, and not always below 1.00**. Executed over all 18 profiles: 10 convert, 8 refuse with a stated reason; the top rung is 0.95 for `PLUTUS_DEFAULT`, SSI and Pinetree, 0.90 for TCBS/SHS/SSI_2025_09/Pinetree_2024, 0.85 for SSI_FOREIGN — and **1.00 for VNDIRECT and FPTS**. So the `assets == MR` boundary arises on **three** configurations, not zero: the unnamed path, VNDIRECT and FPTS. The claim that naming a firm makes it *"never arise"* is withdrawn | J3, J26 |
| U15 | TCBS's fourth margin term *"Ký quỹ FSP"* — **verified by exhaustive absence** in QĐ 26 and Phụ lục 2; our reading that VN30F is not an FSP product is **ours** | J26 |
| U16 | Date-keyed (not contract-keyed) VSDC initial-margin table, where publication is **per contract** | J18 |
| U17 | `no_published_grouping` — every underlying a singleton with `OA = 0`, because nobody publishes VSDC's groups | J26, J19 |
| U18 | **The staleness budget, `BookWalkFillPolicy.max_staleness`** — how old a quoted level may be before it stops answering. No Vietnamese document addresses it, and no default exists: `book_walk.py:1258-1261` names it as **one of three** assumptions that must be caller-supplied, *"because each one changes which orders are answerable and a default would make that choice invisible"* — the other two are the queue policy (U3) and the participation cap (U1), both already registered, and this one was missing. **Decision-changing, not cosmetic**: `book_walk.py:1293-1297` measures the largest per-level gap in the corpus at **5,412 s** (11:30:01 → 13:00:13, the lunch break), so *"a budget picked off the 35 s median discards the entire book on the first tick after lunch"*. Carried in `signature` and stamped on every decision. **our modelling choice**, and it is J9's headline — *"the book is stale"* | J9, J21 |
| U19 | **The two ADOPTED amendment refusals** in `orders.py::amend` — refusing to amend a **non-resting** order type, and refusing to amend quantity **below what is already filled**. Every amendment row in the rulebook names the LO and *"no document had reason to address"* the rest; on the second the code says outright *"No Vietnamese document addresses it. ADOPTED, because the alternative breaks `filled + remaining == original`"*. Both record themselves in `detail['adopted']`. Also here: **no `AMENDED` event exists** — `EventKind` has no such member, so an amendment never reaches the cursor | J27 |

**INFERRED / DERIVED — our arithmetic or our reading, on top of sourced rows**

| # | Step | Scenarios |
|---|---|---|
| I1 | A limit-UP/DOWN lock is **one-sided** — from band arithmetic + price-then-time priority. No Vietnamese article states it | J2, J11 |
| I2 | Capital-cycle arithmetic under T+2 with and without the advance; **no document states a round-trips-per-month figure** | J16 |
| I3 | `imr ≥ 50%` ⇒ max LTV 50%, via `imr = 1 − loan_ratio` — holds only for a single fully collateralised purchase | J5 |
| I4 | QĐ 87 Điều 7.2 top-up amounts — the formulas are **images in every accessible mirror** | J5 |
| I5 | "No cap on HNX/UPCoM order size" — an inference; HOSE's 500,000 is a HOSE-specific clause | J22 |
| I6 | Unsettled purchases excluded as margin collateral — **and the previously offered reasoning is refuted** by QĐ 87 Điều 13(5)(b) | J5 |
| I7 | The post-KRX scenario price formula `Sk = S0 × (1 + k × r/10)` — Phụ lục 2's printed form is degenerate; ours reproduces the columns exactly and is **ours** | J19, J26 |
| I8 | `Rm = \|min Lk\| − OA` — the combining arithmetic is written nowhere, nor whether it floors at zero | J19, J26 |
| I9 | `R = MF / (M × St)` inverted out of a published `MF` — a **lower bound** | J26 |
| I10 | The FSP's **14:15–14:45** clock times — derived from a session table that itself rests on a VNX notice | J6 |
| I11 | The KRX cutover **calendar date 2025-05-05** — QĐ 26 Điều 2 keys effectiveness to system go-live, not to a date | J19 |
| I12 | A51 — the **equity** MTL residual rule applied to HNXDS, a recorded **CONFLICT** (last matched ±1 tick vs best bid/ask ±1 tick), applied and declared, not resolved | J13, J3, J6 |
| I13 | A67 — bands **RECONSTRUCTED** from an undated flat constant, never `PUBLISHED`; the rulebook's dated bands feed only `InstrumentSpec`, which no admission rule reads | J2, J4, J9, J10 |
| I14 | The ex-date adjustment **algebra** (A26) — market practice, **not in any gazetted document** | J8, J10 |
| I15 | Every tick, lot and band from **2022-03-31 onward** is corroborated from broker sheets and HOSE web pages, **not** from Phụ lục III, which nobody has obtained for any version | J4, J9, J10 |

**UNVERIFIED — plausibly exists, could not be read. Not disproven; unsupported**

HSX band instrument 2020-01-01 → 2021-07-04 (QĐ 67 as amended by QĐ 462, QĐ 894) · HSX maximum order
size and block threshold before 2021-01-04 · whether 1–9 odd lots were matchable on HOSE in 2020 ·
MOK/MAK on HOSE post-KRX · maximum order size on HNX and UPCoM · **allocation at the marginal auction
price** · the DSP rule 2020-01-01 → 2022-05-31 and the no-matched-trades fallback · the FSP's index
**sampling frequency** (*"the FSP cannot be implemented exactly without it"*) · the post-KRX VaR
observation window (120 vs 250, internally conflicting) · the VaR→IM equation · `Psr`'s window ·
which contract supplies `B` and `S` for groups of 3+ · whether `MM`'s `P` is net or gross · the
liquidity test behind `MM`'s mean/median switch · Điều 8.1's collateral valuation formula · VSDC group
selection order · pre-KRX haircuts (**do not back-date the 5/30/40%**) · whether a margin-utilisation
ladder existed pre-KRX at all · the scope of the simultaneous opposite-side ban (per session or per
day) and its carve-outs · post-2024 VSDC settlement-clock instruments · automatic trading-halt
thresholds (*"never published"*).

**Sourced ABSENCES — state as findings, not gaps**

No document caps a participant's share of a print · no document states a fill probability ·
**Vietnam publishes no derivatives maintenance margin ratio at any date** (`ký quỹ duy trì`,
`ký quỹ biến đổi`, `thời gian thực` occur **zero times** in QĐ 26 and Phụ lục 2) · **no synthetic
market-at-floor order exists in Vietnam at any date** · no Vietnamese document addresses a resting
order across an ex-date · no separate exchange price for put-through trades · no state-set odd-lot
fee found in any price schedule (**low** — *do not let "no fee found" harden into "no fee exists"*) ·
**short selling was never operationalised** — say that, not "prohibited" · **no `quyết định` number
exists** for the 10→13→17% initial-margin series.

**Live citation defects to fix before any scenario prints them**

- **Two files still cite QĐ 96/61 Article 13** for an 80/90/100 margin ladder — `margin.py:13`
  (*"Article 13 of QĐ 96/QĐ-VSD → QĐ 61/QĐ-VSD, confidence high"*) and `session/types.py:657`
  (*"rulebook 6.3, Article 13: levels 1/2/3 at 80/90/100"*). **The citation is withdrawn.** QĐ
  26 Điều 13 contains no percentage of any kind; the only 80/90/100 in QĐ 26 is Điều 29, the
  **position limit**; the deadline is *"Chậm nhất 16h30 ngày giao dịch"*. The rulebook grades
  what survives **`low` (downgraded from `high`)** — rulebook `:638`.
- **`session/rulebook.py:1403-1427` is a THIRD defect and it is not the same one.** An earlier
  draft filed it under the bullet above; that is wrong and a reader following the pointer
  finds nothing — `grep -n "Article 13\|QD 96\|QD 61" src/plutus/market/session/rulebook.py`
  returns **no hit anywhere in the file**. What is actually there is arguably worse, and both
  halves are live:
  - **`rulebook.py:1404-1413`** asserts *"the test is utilisation = MR / valid margin assets
    against **0.80 / 0.90 / 1.00**"* at **`confidence=Confidence.HIGH`**, on
    `document='VSDC "Thong tin ve ky quy" S II, S IV'`. **That is the citation the rulebook
    withdrew and downgraded to `low`** (`:638`: *"the citation chain for this row has
    collapsed … **low** (downgraded from `high`)"*). A `high` in the code against a `low` in
    the source of truth, on the ladder three scenarios depend on.
  - **`rulebook.py:1416`** describes QĐ 26 as *"never read; the COMS formula could not be
    obtained"*. **QĐ 26 was READ IN FULL on 2026-08-26**, together with Phụ lục 2 — rulebook
    `:780`, which lists its 32 articles in 7 chapters, its signatory and its SSC approval
    number. The COMS half of the note is still right (**`COMS` appears nowhere in QĐ 26 or
    Phụ lục 2** — do not cite a COMS formula to QĐ 26); the "never read" half is stale and
    understates our own research.
  - *(The post-KRX row being `_unsourced` is functionally correct — `_overnight_model` relies
    on it raising `UnresolvedRule`. **Fix the prose and the confidence grade, not the
    resolution behaviour.**)*
- `ledgers.py:628`, `:726`, **`:1221`** cite **"rulebook 8.4"**, a section that does not exist —
  **§8 runs 8.1 / 8.2 / 8.3 and stops** (D28; `FEATURES.md`'s copy of this row names `:1209` and
  is equally stale). The three tags do not all point at the same content, and the replacement
  differs per site — all three land in **§5.2**, not §8:
  - `:628` tags **Luật Chứng khoán 54/2019 Điều 86(1)(b)** (the advance is a licensable service
    requiring prior written SSC approval) → rulebook **§5.2**, **high**.
  - `:726` and `:1221` tag **TT 121/2020 Điều 27** ("Hạn chế cho vay" — a securities company may
    not lend) → rulebook **§5.2**, **low**, *"read in summary form only, not verbatim"*.
  - The **§8.3** material — the advance is **self-priced with no statutory cap**, **high
    (structure)** — is a different claim, and `ledgers.py:630` already cites it correctly as
    "rulebook 8.3". Do not move the §8.3 grade onto the §5.2 sites: it would promote a `low`.
- ~~`FEATURES.md` A64 versus `PUBLISH-CHECKLIST.md` RESOLVED on the settlement calendar.~~
  **SETTLED 2026-08-27, in A64's favour, in the checklist itself** — its RESOLVED entry now
  opens *"This entry overstated its own result and is corrected here."* Struck rather than
  deleted, because the residue is real and J1 carries it: **the correct path is
  caller-supplied and is not the default**, so an unnamed calendar still gets
  `weekday-only-UNSOURCED` and a Tết-2026 T+2 five settlement days early. That is now a
  checklist **SHOULD**, not a contradiction between two documents.

---

# What this catalogue does NOT cover

**Bonds and covered warrants — out of scope for this publication, by author decision.** Scope is
**equity and futures only**, and nothing bond-related or CW-related is **claimed, validated or
counted against the model**. Two precisions, because the earlier wording of this paragraph
refuted itself twice:

- **`Dm` is printed at THREE sites in this document and that is correct.** The three are
  **J19** (`Pgm = Max((Rm + Sm + Dm), MM)`), **J26** (the same formula), and **J26 again**,
  in TCBS's published `MR = Max(Rm + Sm + Dm + FSP − OA, MM)`. An earlier draft said
  *"nothing bond-related is cited"* while two of those sites printed it. The resolution is
  not to delete the term. **`Dm` is part
  of the gazetted post-KRX formula** (Phụ lục 2 mục 6.2), it is *ký quỹ chuyển giao* —
  **delivery margin, government-bond futures only** (rulebook `:724`, `high`) — and **it is
  ZERO for VN30 index futures**, which is the only product either scenario computes.
  Truncating a primary formula to make a scope sentence come out clean would be a silent
  edit of a source. So: the formula is printed whole, **`Dm = 0` is stated at all three
  sites** — an earlier draft said *"both sites"* in the sentence directly under the one that
  correctly counted three — and
  **GB futures remain out of scope** — Phụ lục 8 and the cheapest-to-deliver method are
  unobtained and uncited, and a GB future makes the overnight layer INDETERMINATE **by
  design** (`OvernightGap.GOVERNMENT_BOND_DEFERRED`). Nothing bond-specific is *validated*;
  one bond-specific symbol is *quoted*, at zero.
- **Covered warrants are out of scope, and an out-of-scope instrument is not a gap.** An
  earlier draft called the CW state *"a real gap"* inside the paragraph that disclaims
  listing gaps — a deduction taken against ourselves for not delivering something never
  promised. The behaviour is worth recording as a **fact about the code**, not as a debt:
  the CW band formula is *sourced* in the rulebook and nothing derives it, so
  `daily_trading_limit(HSX, WARRANT)` **raises** and every CW order becomes INDETERMINATE.
  **That is the correct behaviour for an unsupported instrument** — it refuses rather than
  guessing — and it is the same discipline J25 exists to demonstrate. If CW ever comes into
  scope, the band derivation is the work; today it is not work owed.
  *(**J17**'s `"(shares, closed-end funds, ETFs, covered warrants)"` stays as written: that
  is QĐ 894's own subject list for the round lot, quoted, not a CW claim of ours. Pointed at
  by scenario rather than by line number, because the line number was already stale once —
  it read "L450" and the string had moved to L617, and it will move again with the next
  edit. **Line-number pointers into this file are a defect; name the scenario.**)*

**Foreign-ownership room — declared tradeoff T1.** The room rules are researched and dated, and
the dates and grades belong on the page because **the four are not equally strong**:
- Room meters **acquisition only** — no rule conditions a foreign SELL on remaining room; a
  foreign investor may always sell, including at room = 0 — structure of QĐ 352 Điều 23, QĐ 17
  Điều 27, QĐ 22/2025 Điều 26 · 2020-01-01 → current · **high**
- Decrement **at MATCH** — *"được trừ … ngay sau khi lệnh mua được thực hiện"* — QĐ 352 Điều
  23(1)(a) verbatim; QĐ 17 Điều 27(2)(a) verbatim · 2021-06-30 → 2025-05-04 · **high**
- Decrement **at ORDER ENTRY** — *"tính vào ngay khi lệnh nhập"* — VNX QĐ 22/2025 Điều 26
  verbatim; QĐ 22/2026 Điều 28 · 2025-05-05 → current · **high**
- The actual KRX delta is a change in the **rejection trigger**, from `room == 0` to
  `room < order quantity` — *"a third distinct behaviour, not either of the two commonly
  described"* · **high**
- **Sell side restores room only at SETTLEMENT — and this one is not high on both sides of the
  cutover.** Pre-KRX it is verbatim (*"được cộng vào … ngay sau khi kết thúc việc thanh toán
  giao dịch"*, QĐ 352 Điều 23(1)(a) 2nd bullet; QĐ 17 Điều 27(2)(a)) · 2021-06-30 → 2025-05-04 ·
  **high**. From **2025-05-05 it is `medium` and assumed to continue**: *"the sell-side clause
  is ABSENT from HOSE's post-KRX regulation and guidance PDF (checked in Vietnamese and
  English)"* — it rests on **Vietcap's handbook and FPTS**, and *"the clause's disappearance
  from the rulebook text is unexplained"*. What would settle it: the post-KRX HOSE trading
  regulation's own room article, or VNX QĐ 22/2025 Điều 26 read in full.

The enforcement is
**deliberately not built**, because it removes an entire date-switched control flow. `FOREIGN_ROOM`
fires only for a foreign BUY and then returns **INDETERMINATE, never REJECTED**, because
`foreign_room` is `None` on both corpora (A68); a domestic order short-circuits at
`order.is_foreign`, which defaults False. **This is not vacuous — 34,653 room observations sit below
a single 100-share lot.** A foreign-flow strategy is outside what this release validates. There is
also an unresolved corpus question: the repo's own documents disagree on whether
`quote_foreignroom` is the **cap** or **remaining room**, and the 2025-05-05 semantics break depends
on which. Resolve before publishing any claim about that series.

**Any mechanism the tracing pass could not source.** Everything in the register above. Three deserve
naming here because a reader will otherwise assume we simply did not think about them:
- **Allocation at the marginal auction price** returns INDETERMINATE **by design**, not by omission.
- **The `NO_OPPOSITE_ORDER` cancellation** for market orders is sourced, its enum exists, its TIF
  table permits it, and **nothing raises it** — on a daily bar there is no book to observe, so it
  cannot be. Unmodelled, stated.
- **The simultaneous opposite-side order ban** is sourced (TT 120/2020 Điều 7) and **not built**,
  with its scope unresolved. We do not pick a reading.

**Also out of scope by decision or absence, and honest to say so**: VAT · dividend withholding tax ·
the monthly/daily charge accrual pass · the VSDC collateral-management fee and settlement-bank
charge · the Điều 29 position-limit warning ladder (primary-sourced, just not applied — the binding
reason is that we do not compute the quantity the percentages apply to) · the 09h30/14h00/16h30
intraday margin checkpoints · PLO orders · the odd-lot board · event-driven callbacks.

---

# The launch subset

**Two scenarios cannot ship as claimed, and NEITHER is blocked by a publish-checklist
must-list item.** This is the second correction to this paragraph. The first was that *three*
were blocked and only one by a must-list item; **J21 has since left the blocked set** because
the item that blocked it landed, and what remains for it is the pair of residuals **J9**
already carries — so J21 is *partial*, like J9, and the blocked set is J14 and J7.

- **J14 and J7 are blocked by the auction phase-carrying data path, which is tracked on the
  checklist as a SHOULD** (the checklist's *"A shipped source that carries an auction phase"*
  item, added 2026-08-27) — **not** MUST, and deliberately so: *"No number a non-auction run
  reports is wrong because of it … and the remedy is one field on two adapters, not a
  subsystem."*
  > *The finding that put it there, kept because the causation is the point:* when this
  > catalogue was written, `PUBLISH-CHECKLIST.md`'s must-list did **not track the auction
  > phase-carrying path at all** — it was in no section of that file, not MUST, not SHOULD,
  > not DECLARABLE — while two catalogue scenarios named that path as their blocker. **The
  > checklist did not track the thing that blocked two of our twenty-seven scenarios.** It
  > now does, as the SHOULD above, and it records the general rule it learned: *"'Blocked by'
  > needs a row to point at."*
- **J21 is no longer here.** See the *partial* set below.

| Scenario | Blocker | What can still ship |
|---|---|---|
| **J14** ATO vs marketable LO | The auction **phase-carrying data path** — the checklist's *"A shipped source that carries an auction phase"* SHOULD, not a must-list item. No shipped adapter puts the session into an auction phase: `DataHubSource` hardcodes `CONTINUOUS` (`datahub.py:436`) and **DataHub is outdated and slated for reimplementation** — an *adapter* limitation, not a design or corpus one; `PhasedBarSource` proves the seam works and lives in `validation/`. *(The auction fill itself is **built**; its price is a **deliberate, stated approximation — our modelling choice**, design §8 Convention 1: we do not trust the auction-window ticks, so we use the published close/open we already store. It carries no measurement. Do not describe it as unbuilt, and do not describe it as sourced.)* **Plus one LIVE defect that reaches users today**: on a tick run the synthesised interval's `close` is a pre-auction print served as *"the published close"* — the tick path does not implement the stated close-as-ATC approximation (publish-checklist MUST #5, design-conformance). | Nothing as a library demo. Hold it. |
| **J7** Auction-only strategy | Same blocker and the same live tick defect; additionally **marginal-price allocation is UNVERIFIED (`low`)** — not a sourced absence — and returns INDETERMINATE by design. **J7 leans on both halves of the approximation in one trade**: it buys at the open cross and sells at the close cross, and the open half is the weaker (HNX and UPCoM run no opening auction at all, and a thin HOSE name often has none either). | Lifecycle at tick resolution only, clearly labelled as lifecycle and not fills — **and the tick defect declared on that page**, because the lifecycle arm runs at exactly the resolution where it fires |

**The six PARTIAL scenarios, and why none of them is blocked**: **J3** and **J19** (must-list
items 3 and 4 bite), **J9** and **J21** (MUST #1's two residuals: injection-only construction,
dev-extract depth), **J12** (MOK decided one interval late; `NO_OPPOSITE_ORDER` never raised),
**J13** (conversion yes, sweep only off the default path). **J13 is partial AND in the launch
subset** — those are different questions, and the subset is chosen on what a page can honestly
claim, not on a status label.

**The launch subset — FIFTEEN scenarios that must exist for the first release.** Chosen so
that every group A–G is represented, every one of the five must-list items is *exhibited
rather than hidden*, and the headline is defensible.

**Group C was missing, and it has been fixed by promotion rather than by weakening the
claim.** The A–G sentence above was **false** as written: Group C — *"How much of a backtest
is assumption"*, J20/J21/J22 — had **no representative at all**. J21 is partial and
second-wave; J20 and J22 were both in the held-back set. That group carries **the paper's
uncertainty-band argument**, which is not an optional flourish: without it the other fourteen
read as point estimates. **J20 is promoted into the launch subset.** It costs nothing — its
own *Runnable today* line already reads *"Yes, fully"* — and it is the right one of the three,
because the fill policy is *"the largest single assumption in any bar-resolution backtest"*
and J20's output **is** the error bar. J22 and J21 stay out: J22 is a second cut at the same
argument, and J21 cannot produce a strategy-level number over the wired corpus.

**The must-list-coverage claim was false when this document had thirteen, and it is stated
here with the receipts rather than asserted.** Before this pass the launch subset exhibited
**item 4 only** (J6, J18, J26). Item 1 was named in no launch scenario; item 2 was named in
**no scenario in the entire catalogue**; item 3's only launch-subset appearance was J5's
*"Must-list item 3 does not apply to this path"* — a **non**-exhibition. What makes the claim
true now:

| Must-list item | Exhibited in the launch subset by |
|---|---|
| **#1** order-book walk — **LANDED 2026-08-27** | **J13**, whose *Runnable today* separates the demonstrable **conversion** from the sweep, and now names **the item's two residuals** — injection-only construction, dev-extract depth — rather than the retired *"In progress"*. **A landed item still needs an exhibit**, because "landed" and "reachable from a config" are not the same claim, and J13 is where a reader sees the difference. **J20**, newly promoted, shows the other side of the same seam: what a fill assumption is worth once you can vary it. |
| **#2** amendment re-runs encumbrance and admission | **J27** — added for this purpose, and the only scenario that exhibits it |
| **#3** forced liquidation must execute | **J10** disclosure 5 — and J4 in the second tier |
| **#4** variation margin must settle in cash | **J6**, **J18**, **J26**, and J10 disclosure 5 |
| **#5** tick path must implement close-as-ATC — **added 2026-08-27** | **J6**, **J10**, **J17** and **J20** each declare the tick-path ATC defect in their *Runnable today* caveats; **J14** and **J7** own it but are blocked, so the launch exhibit is those four declarations |

| Ship | Why it is in the launch set |
|---|---|
| **J1** Buy, refused, sell after T+2 | The single most recognisable Vietnamese mechanic, fully sourced, no blocker. The A64-vs-checklist calendar conflict is **settled** (2026-08-27, in A64's favour); what J1 must still do is **state which calendar path it ran**, because the correct one is caller-supplied and the default is `weekday-only-UNSOURCED`. |
| **J2** Limit-UP lock | The most flattering error a momentum backtest can make. **Ships with the measured ~10× lock over-assertion**, not without it. |
| **J11** Floor-lock on the exit | The mirror, and the sourced negative that **no market-at-floor order exists in Vietnam at any date**. |
| **J13** MTL residue | A gazetted sentence, verbatim — the clearest demonstration of what "dated and cited" buys, **including what it costs**. **Ships as PARTIAL, and the split is the exhibit**: the MTL row is **split by date** (2025-05-05 → current on QĐ 22/2025 Điều 17.2(b) + QĐ 22/2026 Điều 19.2, `high`; 2020-01-01 → 2025-05-04 carried by continuity and ASEANSC §2.3, the pre-KRX HNX instrument never obtained), with the rulebook's own **OPEN CONFLICT** (§2.3 `:177` vs §10 `:1158`, both `high`) attached to the second leg where it belongs rather than to a row graded `high` for the whole window. Plus the **sweep/conversion split** that makes MUST #1's residuals visible. Do not describe the third reading as "rejected", and **do not call QĐ 22/2025 "the only primary instrument"** — `:175` names two. |
| **J15** Ứng trước tiền bán | The product that makes Vietnamese turnover possible, with its statutory/commercial split stated. Fix **D28** first. |
| **J16** Turnover under T+2 | Converts a compliance detail into a capacity constraint. The quietest error class we correct. |
| **J17** Round-lot straddle | The cheapest, cleanest dated-rule demo. Untouched by every open must-list item and by the auction SHOULD — **provided it is kept in continuous trading**, which its own entry requires for exactly that reason. |
| **J18** Initial-margin straddle | +30.8% deposit with zero price movement, and **the citation lesson**: no `quyết định` number exists. Enter-and-report on each side, do not hold. |
| **J5** Margin call and bán giải chấp | The forced sale that **executes**, plus the band lock refusing a legally obliged sale. |
| **J6** Roll across expiry | Expiry wired end to end, a measured **0.042% mean absolute** settlement error bar, and the clearest exhibit of must-list item 4. |
| **J26** Day trader vs swing trader | Best-wired derivatives scenario, and `variation_margin_unsettled` **is** its content. |
| **J27** Amend up, across, down | **The only scenario that exhibits must-list item 2**, which is why it exists. Also the cheapest place to show that a refusal can be the honest answer: two of its four amendments are declined by design and say so. Ships with both live defects named — the skipped `ROUND_LOT` re-check and the unpassed `priority_preserving` flag. |
| **J25** Meeting a data gap | The discipline scenario. Without it the others read as claims rather than as measurements. |
| **J20** Fill-policy spread | **Group C's representative, promoted 2026-08-27 to make the A–G claim true rather than to make it sound true.** The fill policy is the largest single assumption in any bar-resolution backtest and it is **not a rule** — a sourced absence in all four rulebooks. **J20's output IS the uncertainty band the other fourteen implicitly assume.** Ships with A69, the conflicts-3-and-4 cancellation, and `compare_policies` reporting fills rather than P&L. |
| **J10** The headline | The whole value proposition, already measured in two places. **Ships only with the conflicts-3-and-4 disclosure.** |

**"SECOND WAVE" HAD TWO MEMBERSHIPS IN THIS DOCUMENT — seven in one paragraph and four in
the next. One term, one meaning, defined here:**

> **Second wave = the scenarios that CANNOT ship as claimed today.** Seven: the **2 blocked**
> (J14, J7) plus the **5 partial that are outside the launch subset** (J3, J19, J9, J12,
> J21). This is *not* the same set as "partial" — **J13** is partial and ships in the launch
> subset — and it is *not* the same set as "held back", which is about release size and not
> about honesty.

What each of the seven waits on: **J3** and **J19** become honest the moment forced
liquidation executes (MUST #3) and variation margin settles in cash (MUST #4). **J14** and
**J7** become possible the moment a shipped adapter carries a phase — the checklist SHOULD —
**and the tick path is made to implement the stated close-as-ATC approximation**, which is
the separate MUST (#5, design-conformance). **J21** and the
staleness half of **J9** become strategy-level results the moment the order-book walk is
reachable **from a config over the wired corpus** — note that this is no longer "the moment
MUST #1 lands"; it landed, and what remains is its two residuals. **J12** completes on the
same fix: its open half is the `NO_OPPOSITE_ORDER` cancellation, and *"on a daily bar there
is no book to observe, so it cannot be"* — **a book now exists to observe, by injection over
dev depth, so J12's blocker moved from "unbuilt" to "not on the default path" with everything
else in this class.**

**The partition, so that every one of the twenty-seven is accounted for exactly once**:
**15 launch** + **7 second wave** (J14, J7 blocked; J3, J19, J9, J12, J21 partial) + **5
runnable-but-held-back** (J4, J22, J23, J24, J8) = **27**.

**Cross-check against the 19/6/2 status split at the top of this document**, because two
partitions that do not reconcile are worse than one:
- **19 runnable** = 14 of the launch 15 (all but J13) + the 5 held back.
- **6 partial** = J13 (launch) + J3, J19, J9, J12, J21 (second wave).
- **2 blocked** = J14, J7.

**Runnable now, held back only to keep the first release small enough that every caveat on
every page is actually read: J4, J22, J23, J24 and J8** — **five**, down from six because
**J20 was promoted** to carry Group C. Two prior corrections to this list stand: **J12 is NOT
on it** — its *Runnable today* reads *"Partial. Two deviations must be declared, not
glossed"*, so it belongs with the partial set (fixed by moving J12, not by softening its
entry, because the entry was right) — and **J13 is not on it either**, for the same reason
and by the same test, which is the correction this pass adds.

**One rule for all of them.** A scenario page that omits its declared assumption is worse than no
scenario page, because it will be trusted. **Overclaiming is a defect.**
