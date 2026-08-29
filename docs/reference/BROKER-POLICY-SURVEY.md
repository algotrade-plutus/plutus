# Plutus Broker Derivatives-Margin Policy Survey

**Version 1.0 · 2026-08-30.** Cite as *"Plutus Broker Policy Survey, ⟨firm⟩"*.
Encoded in `src/plutus/market/session/broker_profile.py`; design brief in
`krx-margin-research.md §4`.

A structured survey of how **14 Vietnamese securities firms** implement derivatives
clearing-margin policy, read 2026-08-26 from firm help pages, published schedules,
and signed terms. It classifies each firm along **six axes** and carries a
`FieldCoverage` provenance record on **every field of every firm** — so a value's
presence is *not* a claim it is the firm's current operative number; the coverage
status says which. **Silence means "fully sourced," never "we did not check."**

**Scale.** The survey encodes **244 distinct, provenance-tagged policy data points**
across all 18 registry entries (**200** across the 15 base profiles; **183** across
the 14 real firms), plus 69 verbatim Vietnamese quotes and 144 flagged gap
instances. *(There is no structural count equal to 400; if a draft cited "≈400
policy docs," it should read **244** — or "≈200 across 15 profiles" / "183 across 14
firms." As source **documents**, the count is ≈14–18: roughly one dominant document
per firm, plus SSI's dated vintages.)*

**Sourcing caveat (carry into every citation).** No broker value here comes from
*công báo* (the gazette) — the gazette backs only the VSDC/QĐ regulatory layer.
Broker values are from help pages, commercial schedules, secondary readings, or
private signed T&Cs. Notably the evidence **splits by document class, not firm
policy**: every firm that *promises* a margin-call notice does so on a help page;
every firm whose *signed* terms we hold *denies* the duty. A help page is not a
contract.

---

## The six axes

1. **Direction** — which way the ratio moves as the account worsens.
   `RISING_UTILISATION` (MR / margin assets; higher worse; **13 of 14 firms**) vs
   `FALLING_COVERAGE` (equity / IM; lower worse; rungs descend; **HSC alone**).
2. **Denominator** — `DenominatorBasis` (V_KQ · NET_ASSETS · CASH_ONLY ·
   INITIAL_MARGIN · UNPUBLISHED) × `LiabilitiesTreatment` (where client debts land:
   IGNORED · SUBTRACTED_FROM_ASSETS · ADDED_TO_NUMERATOR · UNPUBLISHED). The brief's
   "single most commonly-missed field."
3. **Action** — what happens at a rung (`NONE` · `BLOCK_OPENING` · `NOTIFY` ·
   `TRANSFER_COLLATERAL` · `LIQUIDATE`) × `TargetRef` (fire-once vs close *until* a
   named rung / absolute level / `UNRESOLVED`).
4. **Notice & cure** — `Notice` (`REQUIRED` · `RIGHT_NOT_DUTY` · `DISCLAIMED` ·
   `UNKNOWN`) × `CureKind` (IMMEDIATE · SESSIONS · DEADLINE · DELEGATED · UNKNOWN).
5. **Publication status** (`Coverage`, 10 values) — where a field's value came from:
   PUBLISHED · PUBLISHED_ILLUSTRATIVE · PUBLISHED_STALE · DELEGATED · UNPUBLISHED ·
   DISCLAIMED · INAPPLICABLE · CONTRADICTORY · INFERRED · FILLED_FROM_DEFAULT.
6. **Margin model** (the axis the author added) — `MarginModel` (SCENARIO_GRID ·
   IM_PLUS_VM_PLUS_DM · IM_PLUS_VM · IM_ONLY_WITH_MM · UNSTATED) × `MarginLayer`
   (INTRADAY · OVERNIGHT). **Load-bearing:** all ten firms that state a client-ladder
   formula state IM+VM+DM; **zero state the scenario grid** — and every profile's
   `user_facing_model` is INTRADAY.

The registry also carries 18 gap kinds (`GapKind` G1–G18), a `Severity`
(BLOCKING · MATERIAL · ADVISORY) per gap, and 7 recorded `OPEN_QUESTIONS`.

---

## The registry

18 entries: **14 real firms** + `PLUTUS_DEFAULT` (an honest synthesis, matching no
firm) + 3 dated/segment variants (`SSI_FOREIGN`, `SSI_2025_09`, `Pinetree_2024`).
`get_profile(name)` is the sole access point; it **raises** for the three delegating
firms (MBS, KIS, VPS) unless `fill_from=PLUTUS_DEFAULT` is passed.

| Firm | Direction | Denominator | Ladder rungs | Own IM ratio | Model (intraday/overnight) | Dominant source | Default? |
|---|---|---|---|---|---|---|:--:|
| PLUTUS_DEFAULT | rising | V_KQ / ignored | 80/90/95 util | 17.85% (median) | IM+VM+DM / grid | OURS (synthesis) | ✅ |
| SSI | rising | unpublished | 85/90/95 util | — (not 0.17) | unstated / grid | pub. schedule | ✅ |
| VNDIRECT | rising | **net assets** / subtracted | 80/90/100 util | **17.5%** (pub) | IM+VM+DM / unstated | help page | ✅ |
| FPTS | rising | V_KQ / subtracted | 80/90/100 util | **17.85%** (pub) | IM+VM+DM / grid | pub. schedule | ✅ |
| SHS | rising | V_KQ / **added to numerator** | 75/85/90 util | — (mirrors 17%) | IM+VM+DM / grid | pub. schedule | ✅ |
| Vietcap | rising | unpublished | 90/95 util | **20%** (highest) | IM+VM / unstated | secondary (403) | ✅ |
| **HSC** | **falling** | **initial margin** | **100/80/60 coverage** | **17%** (pub, 2020) | IM_only_with_MM / unstated | help page | ✅ |
| TCBS | rising | unpublished | 85/87/90 util | — (delegated) | unstated / grid | help page | ✅ |
| MBS | rising | V_KQ / ignored | delegated | — (delegated) | IM+VM+DM / unstated | **signed T&C** | ✅ |
| KIS | rising | V_KQ / ignored | delegated | — (delegated) | IM+VM+DM / unstated | **signed T&C** | ✅ |
| VPS | rising (contradictory) | V_KQ / ignored | delegated | — (delegated) | IM+VM+DM / unstated | **signed T&C** | ❌ |
| Pinetree | rising | unpublished | 80/90/95 util | — (unpublished) | unstated / unstated | secondary | ✅ |
| DNSE | rising | unpublished | no ladder | **18.48%** (pub) | unstated / unstated | help page (FAQ) | ✅ |
| VCBS | rising | **cash-only vs V_KQ+DTA (contradictory)** | no ladder | — (unpublished) | unstated / unstated | secondary | ❌ |
| ACBS | rising | unpublished (inapplicable) | no ladder | — (unpublished) | unstated / unstated | secondary | ❌ |

*(Variants omitted from the table: SSI_FOREIGN 75/80/85, SSI_2025_09 80/85/90,
Pinetree_2024 75/85/90.)* **HSC's 100/80/60 are coverage bands, not utilisation and
not IM ratios; SSI's 85/90/95 are utilisation rungs, not IM ratios** — the survey
keeps ladder rungs and IM ratios in separate fields precisely to stop the two being
conflated. `__post_init__` enforces every firm's IM ratio ≥ VSDC's 17%.

**Dispositions.** Publish their own IM ratio (5): VNDIRECT, FPTS, Vietcap, HSC,
DNSE. Delegate to VSDC (5): TCBS, SHS, MBS, KIS, VPS. Unpublished (4): SSI, Pinetree,
VCBS, ACBS. **Structurally refuse a number** (`get_profile` raises without
`fill_from`) — 3: MBS, KIS, VPS. **Ship disabled**, each for a stated reason — 3: VPS
(direction rests on a source defect), VCBS (denominator self-contradicts), ACBS (no
ladder to run). The other 15 entries are enabled by default.

---

## Load-bearing findings (for citation)

1. **Inverted directions — 13 rising-utilisation vs HSC falling-coverage.** Thirteen
   firms run MR/assets (higher worse); **HSC alone** runs equity/IM (lower worse,
   rungs 100/80/60, MM = 80%×IM). Direction is a method on the enum applied wherever
   a ratio meets a level, not an ad-hoc branch. HSC cannot be pooled without a
   modelling choice (U = 1/R vs 0.8/R, 25 points apart on the same rung), so it is
   excluded from every numeric pool.
2. **The 80/90/100 correction.** The received "VSDC ran an 80/90/100 margin ladder
   that QĐ 26 deleted" is true-but-misleading: pre-KRX (QĐ 96/61/12 Điều 13) rungs 1–2
   were **notification-only** (no trading gate, no liquidation); only rung 3 acted.
   Post-KRX (QĐ 26 Điều 13) the top rung is re-expressed as the binary `V_KQ < MR` and
   the two informational rungs are gone — **no 80/90/100 anywhere in Điều 13** (the
   article was even renamed from "…tỷ lệ sử dụng…" to "…giá trị tài sản…"). **The only
   live 80/90/100 is a position-limit monitor** — QĐ 26 **Điều 29.1**, at 80/90/100 of
   the *position limit* counted in **contracts** (Điều 27.2), a different numerator,
   denominator, and units from any margin ratio (and even there, levels 1–2 are
   notice-only). The 80/90/100 that looks "live" for VNDIRECT/FPTS is a **commercial
   broker ladder** on the firm's own denominator (VNDIRECT's is on net assets).
3. **The MM homonym (gap kind G18).** One phrase, "Giá trị ký quỹ tối thiểu/1HĐ,"
   denotes three quantities orders of magnitude apart: the **policy constant MF =
   5,000đ** (index-independent, corroborated by TCBS); the **per-contract requirement
   at a dated index** SSI publishes under the same phrase (**34,520,710đ** at
   2026-01-16, 31,711,460đ at 2025-09-11; SHS 22,309,440đ, stale); and HSC's
   **fraction** (0.80 in MM = 0.80×IM). Writing SSI's figure into the MF slot "makes
   MM bind on every book and destroys MR = max(Rm + Sm − OA, MM)"; the code raises a
   `HomonymError` if it is attempted.
4. **VNDIRECT's 17.5% IM above VSDC's 17%.** VNDIRECT publishes its **own** IM ratio,
   **17.5%** (asymmetric across products), against VSDC's gazetted 17% — the clean
   exemplar that the broker uplift "is not a modelling convenience; it is visible in
   the tape." VNDIRECT also demonstrates the **net-asset denominator** (subtracting
   client debts) — same rung numbers, earlier call. Higher-uplift outliers: Vietcap
   20%, DNSE 18.48%.
5. **Sourcing splits by document class, not firm.** Every firm that *promises* a
   notice does so on a help page (SSI, TCBS, Vietcap, HSC, FPTS); every firm whose
   *signed* terms we hold *denies* the duty (MBS, VPS "right not duty"; KIS
   "disclaimed"). Several documents are pre-KRX (HSC 2020, MBS 2019, KIS "Ver 2022").
   `PLUTUS_DEFAULT` is honest it is a synthesis and records each field's derivation
   (rule, source firms, n).

**Footnotes.** SSI is the only firm with a **datable version history** (85/90/95 from
2026-01-16 supersedes 80/85/90 from 2025-09-11) — the one policy change in the survey
dated on both sides; Pinetree's two vintages exist with nothing dating the change.
VPS **contradicts itself on its own ratio's direction** in both languages of its
bilingual contract, which is why it ships disabled.

**Coverage histogram (all 244 records):** PUBLISHED 105 · UNPUBLISHED 74 ·
DELEGATED 22 · INFERRED 21 · INAPPLICABLE 8 · CONTRADICTORY 5 · PUBLISHED_STALE 5 ·
DISCLAIMED 3 · PUBLISHED_ILLUSTRATIVE 1.

*Full detail: `broker_profile.py` (the encoded survey) · `krx-margin-research.md §4,
§S-7, §C-3` (the design brief) · `post-krx-margin-spec.md §2.5` (Điều 29 verbatim).*
