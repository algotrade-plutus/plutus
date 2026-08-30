# Post-KRX derivatives margin (*ký quỹ*) — implementable specification

**Status: NOT BUILT.** This document specifies the VSDC derivatives clearing-margin model
in force from the KRX go-live (2025-05-05), from the primary text of **Phụ lục 2** of the
Quy chế issued with **QĐ 26/QĐ-HĐTV ngày 16/4/2025**.

**Scope note set by the author:** all government-bond-futures (HĐTL TPCP) work is
**deferred**. §7 (delivery margin) is documented so the model is complete and so nobody
re-derives it later; **it is not for building.**

**We do not measure things.** Nothing below proposes a measurement. §10 states what data
exists and what it would support; that is a capability statement, not a result.

Companion documents: `docs/reference/citable/vn-exchange-rulebook-2020-2026.md` (the exchange
rulebook — this document does **not** modify it, but §12 records what it now contradicts),
`docs/reference/equity-margin-spec.md` (a **different product** — SSC-regulated broker
lending against shares; the only thing it shares with this one is the phrase *ký quỹ*).

---

## 0. Confidence vocabulary

| Grade | Means |
|---|---|
| **VERIFIED** | Read verbatim in the extracted primary text. Line references below are to the two extracted files named in §14. |
| **INFERRED** | Our reading, needed to make the model computable, **not stated in either document**. Every occurrence is flagged inline and repeated in the register at §11. |
| **DERIVED** | Our own arithmetic on VERIFIED formulas. Sound, but it is ours. |
| **SILENT** | The source does not address it. Do not invent a value. |
| **DEFECT** | The published text is internally inconsistent or incomplete. Registered at §12. |

**Reachability.** Both documents came from `thuvienphapluat.vn`'s HTML rendering, extracted
to plain text. **QĐ 26's own operative text is complete and was read end to end** (Điều 1 →
Điều 32). **Phụ lục 2 was obtained separately and is complete as to its six numbered
sections**, but three formulas that the text announces are **absent from the extraction**
(§4.3, §12 D3, §12 D4) — almost certainly because they are images in the source rendering,
the same failure mode recorded at `equity-margin-spec.md` §5 gap 1. **Phụ lục 1, 3–9 were
not obtained.** Phụ lục 8 is load-bearing for §7 and we do not have it.

---

## 1. The regime, and when it starts

| Fact | Value | Source |
|---|---|---|
| Instrument | QĐ 26/QĐ-HĐTV, Hà Nội, **16/4/2025**, signed Nguyễn Sơn, TM. Hội đồng thành viên | qd26 L28, L80–93 |
| What it issues | *"Quy chế bù trừ và thanh toán giao dịch chứng khoán phái sinh tại VSDC"* | qd26 L61–62 |
| Scope | VN30-type **index futures** and **government-bond futures** listed at SGDCK Hà Nội | qd26 L104–107 |
| **Effective from** | *"kể từ ngày Hệ thống công nghệ thông tin của gói thầu … Sở Giao dịch chứng khoán thành phố Hồ Chí Minh chính thức vận hành"* — the KRX go-live, **2025-05-05** | qd26 L63–66 |
| Replaces | **QĐ 12/QĐ-HĐTV ngày 10/8/2023** | qd26 L66–69 |
| Approval chain | Công văn 1058/UBCK-PTTT (2025-04-15); Nghị quyết 84/2025/NQ-HĐTV (2025-04-16), issued expressly *"để chuẩn bị triển khai hệ thống công nghệ thông tin KRX"* | qd26 L53–58 |

All VERIFIED. Note the effective date is **conditional on an event**, not a calendar date
written in the decision — model it as a dated rule whose effective date is supplied
(2025-05-05), with the citation recording that the instrument itself names an event.

**The chain our code relies on ends here.** `QĐ 96/QĐ-VSD → QĐ 61/QĐ-VSD → QĐ 12/QĐ-HĐTV →
QĐ 26/QĐ-HĐTV`. QĐ 26 is now read. See §12.

---

## 2. The top-level requirement: MR is **not** IM + VM

### 2.1 The formula

**Phụ lục 2 §6.1, verbatim** (phuluc2 L127–131):

> **MR = Max (ΣPgm,0)**
> Trong đó:
> MR: Ký quỹ yêu cầu đối với một tài khoản nhà đầu tư, thành viên bù trừ
> Pgm: Giá trị ký quỹ của các nhóm tài sản cơ sở …

**Phụ lục 2 §6.2, verbatim** (phuluc2 L132–138):

> **Pgm = Max ((Rm  + Sm + Dm), MM)**
> Trong đó:
> - Rm: Ký quỹ rủi ro
> - Sm: Ký quỹ song hành
> - Dm: Ký quỹ chuyển giao (giá trị này được tính toán tại ngày giao dịch cuối cùng, ngày
>   làm việc liền sau ngày giao dịch cuối cùng của HĐTL và chỉ áp dụng đối với HĐTL chưa
>   được nộp trái phiếu chuyển giao để thực hiện nghĩa vụ thanh toán).
> - MM: Ký quỹ tối thiểu.

So, in one line:

```
MR(account) = max( Σ_over_underlying_groups  max( Rm + Sm + Dm , MM ) , 0 )
```

**Variation margin is not a component of MR.** VERIFIED by absence from §6.2 and by
positive evidence: QĐ 26 **Điều 20** settles *lãi lỗ vị thế* as a **separate daily cash
settlement**, paid *"bằng tiền vào ngày làm việc liền kề sau ngày VSDC thông báo khoản lãi
lỗ vị thế"* (qd26 L626–629), netted per clearing member (L633–634) and moved between
settlement-bank accounts (L639–643). Daily P&L leaves the system as cash on T+1; it is not
carried as a margin add-on.

### 2.2 Unit of assessment

**QĐ 26 Điều 5.5, verbatim** (qd26 L305–309):

> Ký quỹ yêu cầu là tổng giá trị ký quỹ mà thành viên bù trừ có nghĩa vụ phải nộp cho VSDC
> để duy trì các vị thế đứng tên thành viên bù trừ **được tính toán sau khi kết thúc phiên
> giao dịch** cho danh mục vị thế trên **từng tài khoản giao dịch của nhà đầu tư** và tài
> khoản của chính thành viên bù trừ.

Two facts, both VERIFIED and both load-bearing:

1. **The unit is the individual investor trading account** (plus the member's own account)
   — the same unit our `account_margin_requirement` already takes. Locked shape 5 survives
   the regime change unchanged.
2. **MR is computed after the session closes.** Post-KRX MR is an **end-of-day** quantity.
   The pre-KRX depository page described VSD determining and monitoring utilisation
   *"theo thời gian thực"*; QĐ 26 replaces that with an EOD computation plus **three fixed
   checkpoints** (§2.4). This is a real change in the shape of the model, not a rewording.

**Below the account, the unit is the underlying-asset group** (*nhóm tài sản cơ sở*), not
the contract: `Pgm` is defined per group and MR sums groups.

> **INFERRED — the singleton group.** Phụ lục 2 §2.1 only provides for groups formed from
> **two or more** correlated underlyings. It never says what happens to an underlying in no
> group — which is the ordinary case and the only case our corpus contains. §6.1 sums
> `Pgm` over *"các nhóm tài sản cơ sở"*, so an ungrouped underlying must still produce a
> `Pgm` or its risk vanishes from MR. **We adopt: every underlying not placed in a
> multi-underlying group forms a singleton group with `OA = 0`.** This is the only reading
> under which MR is well-defined for a single-product account. It is not in the text.

### 2.3 Margin assets, and the test against them

The other half of the system — what MR is compared against.

| Rule | Value | Grade | Source |
|---|---|---|---|
| Acceptable margin securities | (a) government bonds and government-guaranteed bonds, **excluding treasury bills** (*tín phiếu Kho bạc*); (b) securities listed on an exchange — shares and fund certificates, **excluding ETF certificates** | VERIFIED | qd26 Điều 6.1, L312–315 |
| Eligible-list mechanics | VSDC publishes the accepted list **with its haircuts**, **every 6 months**, unchanged until the next publication; a security failing the criteria may be removed mid-cycle | VERIFIED | qd26 Điều 6.3, L328–332 |
| **Haircut — government / government-guaranteed bonds** | **5%** | VERIFIED | qd26 Điều 9.1.a, L389 |
| **Haircut — VN30 / HNX30 constituents** | **30%** | VERIFIED | qd26 Điều 9.1.b, L390–391 |
| **Haircut — all other securities** | **40%** | VERIFIED | qd26 Điều 9.1.c, L392 |
| Haircut changes | VSDC may change them on liquidity/risk grounds, with written notice **at least 01 working day** before the effective date | VERIFIED | qd26 Điều 9.2, L393–396 |
| **Minimum cash proportion** | **`x` = tỷ lệ ký quỹ bằng tiền tối thiểu (80%)** — now primary-sourced, previously depository-page-sourced | VERIFIED | qd26 Điều 8.1, L372 |
| Collateral price `P` | Government bonds: priced off **HNX's government-bond yield curve**. Listed securities: **the reference price for the next trading day**. Refreshed daily after the close | VERIFIED | qd26 Điều 8.2, L376–386 |

> **DEFECT D3 — the margin-asset valuation formula is missing.** Điều 8.1 says *"Giá trị
> tài sản ký quỹ hợp lệ được xác định theo công thức sau:"* and the next line is
> *"Trong đó:"* (qd26 L367–368). **The formula itself is absent from the extraction.** We
> therefore have every input — `VKQ`, `C`, `MR`, `x = 80%`, `QKQ`, `P`, `H` — and the
> haircut values, but **not the expression combining them**. Do not guess it. The natural
> reading (`VKQ = C + Σ QKQ·P·(1−H)`, capped so that securities cover at most `(1−x)·MR`)
> is **INFERRED and unverified**; it is consistent with `x` being described as a *minimum
> cash ratio* against `MR`, but that is reasoning from a variable's name.

### 2.4 The margin-monitoring test — **Điều 13 contains no percentages**

This is the article our code cites for an 80/90/100 ladder. It was read in full
(qd26 L494–536). **It is a binary test.**

| Rule | Value | Grade |
|---|---|---|
| EOD determination | **By 16h30 each trading day**, VSDC determines MR per clearing member, **per investor margin account**, and notifies the member | VERIFIED (Điều 13.1, L495–497) |
| **The violation test** | *"Trường hợp giá trị tài sản ký quỹ trên tài khoản nhà đầu tư **nhỏ hơn** giá trị ký quỹ yêu cầu"* — **margin assets < MR. That is the whole test.** No ratio, no threshold, no ladder | VERIFIED (Điều 13.1, L497–498) |
| Top-up deadline | **before 09h30 the next trading day** | VERIFIED (Điều 13.1, L498–499) |
| **Checkpoint 09h30** | Against the requirement **determined on the previous working day**, VSDC identifies **newly** violating accounts (excluding those already in violation) → asks HNX to suspend trading on them, and tells the member **no new opening trades, offsetting closes only** | VERIFIED (Điều 13.2.a, L502–508) |
| **Checkpoint 14h00** | VSDC re-checks **all** violating accounts; those that have cured are restored to trading | VERIFIED (Điều 13.2.b, L509–512) |
| **Checkpoint 16h30** | VSDC recomputes MR and assets per account; a suspended account whose assets are **equal to or greater than** MR is restored | VERIFIED (Điều 13.2.c, L513–518) |
| Cure methods | (a) post more margin assets; (b) trade offsetting to reduce the position | VERIFIED (Điều 13.3, L519–522) |
| **Uncured after 03 working days** | VSDC **directs another clearing member** to close the violating account's positions; the offsetting positions are then transferred to the violating member to net off; done on a VSDC-member agreement basis | VERIFIED (Điều 13.3.b, L522–533) |

So the post-KRX monitoring model is:

```
violation  :=  margin_assets < MR            # binary, per investor account
checkpoints:  09h30 (suspend new violators), 14h00 (restore cured), 16h30 (recompute, restore)
cure due   :  before 09h30 of the next trading day
escalation :  uncured for 03 working days -> another clearing member closes the positions
```

**There is no 80%, no 90% and no 100% anywhere in Điều 13.** The `Max(…, 0)` in §6.1 and
the `Max(…, MM)` in §6.2 are the only thresholds in the whole margin chapter.

### 2.5 Where 80/90/100 actually lives: **position limits, Điều 29**

**QĐ 26 Điều 29.1, verbatim** (qd26 L954–962):

> 1. VSDC thiết lập các ngưỡng các cảnh báo theo ba (03) cấp độ dưới đây để thực hiện giám
>    sát **giới hạn vị thế** trên từng tài khoản giao dịch của nhà đầu tư trong phiên giao
>    dịch:
> a. Cảnh báo mức độ 1: khi **số lượng hợp đồng** … đạt ngưỡng **80% giới hạn vị thế**;
> b. Cảnh báo mức độ 2: … đạt ngưỡng **90% giới hạn vị thế**;
> c. Cảnh báo mức độ 3: … đạt ngưỡng **100% giới hạn vị thế**.

| Rule | Value | Grade |
|---|---|---|
| What is measured | **A contract count**, per Điều 27.2: for an ordinary account, the total positions across contracts with the **same underlying and same multiplier but different expiry months**, with same-month opposing positions netted off first | VERIFIED (Điều 27.2.a, L927–935) |
| — omnibus accounts | For a *tài khoản giao dịch tổng*, each expiry month contributes **max(long count, short count)**, not the net | VERIFIED (Điều 27.2.b, L936–939) |
| Levels 1 and 2 | **Notice only** — VSDC warns the clearing member to control the investor's positions | VERIFIED (Điều 29.2, L963–965) |
| Level 3 | (a) VSDC asks HNX to **suspend** the account; (b) the member must reduce the position by offsetting trades **within 03 working days** | VERIFIED (Điều 29.3, L966–973) |
| **The invalid-trade rule** | *"Các giao dịch đối ứng này sẽ bị coi là **không hợp lệ** nếu sau khi khớp lệnh tài khoản vi phạm không giảm xuống dưới ngưỡng cảnh báo mức độ 3."* Invalid trades are routed to the error-holding account under Điều 18 | VERIFIED (Điều 29.3.b, L971–973; Điều 29.4, L974–975) |
| Uncured after 03 working days | Another clearing member is directed to close the positions | VERIFIED (Điều 29.5, L976–986) |
| Restoration | Once the count is back below level 3, VSDC asks HNX to restore trading | VERIFIED (Điều 29.6, L987–989) |
| **Margin still owed throughout** | *"Trong thời gian xử lý vượt giới hạn vị thế, thành viên bù trừ **vẫn phải đảm bảo nghĩa vụ ký quỹ**, thanh toán cho số vị thế … kể cả đó là tài khoản của nhà đầu tư"* | VERIFIED (Điều 29.7, L990–992) |

**The ladder is real, the numbers are right, and the denominator is a position limit
measured in contracts — not a margin utilisation ratio.** The two are not
interchangeable: one is `contracts / position_limit`, the other would be
`MR / margin_assets`. Different numerator, different denominator, different units,
different remedy.

---

## 3. Ký quỹ rủi ro (`Rm`) — scenario risk margin

### 3.1 The loss function

**Phụ lục 2 §1.1, verbatim** (phuluc2 L4–13):

> 1.1. Ký quỹ rủi ro là **giá trị tuyệt đối của khoản lỗ lớn nhất** trong số các khoản lỗ
> (Lk) xác định theo các kịch bản biến động giá của tài sản cơ sở.
> Lk được xác định theo ông thức sau:
> **Lk = Pm x (Sk – S) x M + Pb x (S – Sk) x M**
> Trong đó:
> Lk: Khoản lãi/lỗ
> Pm: Số dư vị thế mua
> Pb: Số dư vị thế bán
> Sk: Giá của tài sản cơ sở trong kịch bản k
> S: Giá đóng cửa của tài sản cơ sở tại ngày xác định
> M: Hệ số nhân hợp đồng

*(`ông thức` is a typo for `công thức` in the published text — DEFECT D5, cosmetic.)*

**Inputs:** `Pm` gross long balance, `Pb` gross short balance, both per underlying;
`S` the underlying's **closing price** on the calculation date; `M` the contract
multiplier; and the 21 scenario prices `Sk`.

**Sign convention, DERIVED:** `Lk` is signed P&L — for a long (`Pm>0`) a scenario with
`Sk<S` gives `Lk<0`. So a *loss* is a **negative** `Lk`, and "the largest loss" is the
**most negative** `Lk`.

```
Rm_gross = max( 0 , − min_{k∈[−10,10]} Lk )          # DERIVED, see below
```

> **INFERRED — the zero floor.** §1.1 says `Rm` is *the absolute value of the largest loss
> among the losses*. If **no** scenario produces a loss there is no *"khoản lỗ"* to take
> the absolute value of, and `|max Lk|` would charge margin for a *profit*. We adopt
> `max(0, −min_k Lk)`. The text does not state the floor. This only binds for a perfectly
> flat book (`Pm = Pb`), where every `Lk` is exactly 0 and both readings give 0 — so the
> choice is safe, but it must be a deliberate one.

> **DERIVED — the formula nets across expiry months, and that is why `Sm` exists.**
> `Lk = Pm(Sk−S)M + Pb(S−Sk)M = (Pm − Pb)(Sk−S)M`. `Pm` and `Pb` cancel algebraically:
> a fully hedged calendar book (long Jun, short Sep, equal size) has `Rm = 0`. That is not
> an oversight — it is precisely the gap that **ký quỹ song hành** (§6) is defined to
> charge back. QĐ 26 Điều 5.2 says so in terms: `Sm` covers *"mức lỗ tiềm tàng **tăng thêm
> so với giá trị ký quỹ rủi ro** do sự khác biệt về biến động giá của tài sản cơ sở và biến
> động giá của hợp đồng tương lai"* (qd26 L286–289). The two components are complementary
> by construction; implementing `Rm` without `Sm` under-margins every spread.

### 3.2 The 21 scenarios — **a transcription defect in the published appendix**

**Phụ lục 2 §1.2, verbatim** (phuluc2 L14–15):

> 1.2. Kịch bản biến động giá
> VSDC xác định **21 kịch bản** biến động giá của tài sản cơ sở có thể xảy ra trong tương
> lai dựa trên **tỷ lệ ký quỹ ban đầu** đã được VSDC xác định và công bố, cụ thể như sau:

The table that follows (phuluc2 L140–148) has three columns — *Kịch bản* / *Giá của tài
sản cơ sở trong từng kịch bản* / *Công thức* — with rows numbered **1 → 21** whose price
labels run **S-10, S-9, S-8, …, S+8, S+9, S+10**, and a formula cell **repeated
identically in every row**:

> Sk = S0 x (1 + **tỷ lệ ký quỹ ban đầu/10**)
> Trong đó: S0 : Giá của tài sản cơ sở tại ngày xác định
> Sk : Giá của tài sản cơ sở trong kịch bản k
> **−10 ≤ k ≤ 10**

#### The defect

**The formula as printed contains no `k`.** Read literally, all 21 scenarios evaluate to
the same price `S0 × (1 + rate/10)`, `Lk` takes one value, and the scenario grid collapses
to a single point. That is:

- **self-contradictory** — the same cell declares `−10 ≤ k ≤ 10` and defines `Sk` as *"giá
  … trong kịch bản k"*, so `Sk` must depend on `k`;
- **contradicted by the table's own rows** — 21 distinct labels `S-10 … S+10`;
- **contradicted by §1.2's own sentence** — *"21 kịch bản biến động giá"*, twenty-one
  price-movement scenarios;
- **contradicted by §4.3**, which asks for *"Giá cao nhất (Hp), giá thấp nhất (Lp) … xác
  định dựa trên kịch bản biến động giá theo hướng dẫn tại mục 1.2 và 1.3"* (phuluc2 L110).
  A one-point grid has no distinct highest and lowest price.

#### The reading we adopt

```
Sk = S0 × (1 + k × rate/10)          for k = −10, −9, …, +9, +10
```

where `rate` is the initial margin ratio of §4 and `S0 ≡ S` (§3.1's `S`; the appendix uses
both names for the same quantity — DEFECT D6).

#### Why this reading and not another

Four independent checks, all of which the literal text fails and this reading passes:

1. **It restores the missing `k`** with the minimum possible edit — inserting the
   multiplication the surrounding definitions require. No term is added or removed.
2. **It reproduces the declared count and labels exactly.** `k ∈ {−10…+10}` is 21 values;
   `k = −10` ↦ row 1 (`S-10`), `k = 0` ↦ row 11 (the unchanged-price scenario),
   `k = +10` ↦ row 21 (`S+10`). Scenario index `j = k + 11`.
3. **It makes `rate` mean what it is called.** At `k = ±10`, `Sk = S0 × (1 ± rate)`. For a
   directional net position of `N` contracts the worst case is
   `|Lk| = N × S0 × rate × M` — i.e. **`Rm = rate × notional`**, exactly. So the grid
   spans ±(initial margin ratio) in ten steps each way, and the ratio VSDC publishes is
   the fraction of notional the worst scenario charges. Any other reading severs the
   ratio from its name.
4. **It reproduces the pre-KRX formula as a special case.** The rulebook records the
   pre-KRX initial margin as `IM = ratio × contracts × price × multiplier`
   (`docs/reference/citable/vn-exchange-rulebook-2020-2026.md`, "Initial margin (IM) — definition and formula").
   Under this reading `Rm` for a one-sided book is *numerically identical* to that. A
   scenario grid that reproduces the superseded closed form for the simple case, and
   generalises it for spreads and groups, is the expected shape of such a reform.

**Flag this at every use.** The corrected formula is **not** in the gazetted appendix as
extracted. It is a reconstruction — very well supported, but a reconstruction. If a
published claim turns on the scenario spacing, obtain the công báo PDF or VSDC's own copy
and read the table cell as typeset. Recorded as **DEFECT D1** at §12.

> **SILENT — rounding.** The appendix does not say whether `Sk` is rounded to the
> underlying's tick or quotation precision before `Lk` is evaluated. QĐ 26 Điều 23.1 fixes
> rounding for **DSP/FSP** (index futures to 2 decimals, GB futures to integers,
> qd26 L734–735) but says nothing about scenario prices. Compute `Sk` in full `Decimal`
> precision and do not round; record the choice.

### 3.3 Assembling `Rm`

```
Rm(group) = max( 0 , Rm_gross(group) − OA(group) )     # INFERRED — see §5.4
```

Per-underlying `Rm_gross` values within a group must be combined before `OA` is applied;
§5.4 covers the direction, the level and the floor, all three of which are INFERRED.

---

## 4. Tỷ lệ ký quỹ ban đầu — the initial margin ratio

`rate` is the single parameter driving the §3 scenario grid, and (via §7.3) the delivery
margin's price bounds. VSDC computes and publishes it; a clearing member consumes it.

### 4.1 Publication mechanics — VERIFIED, and directly implementable

**QĐ 26 Điều 5.1.1.b** (qd26 L274–283):

| Rule | Value |
|---|---|
| Who computes it | **VSDC**, for index futures **and** GB futures |
| What members do with it | *"Thành viên bù trừ **căn cứ** tỷ lệ ký quỹ ban đầu do VSDC công bố để xác định giá trị ký quỹ ban đầu nhà đầu tư phải nộp"* — the member sets the investor's requirement **on the basis of** VSDC's published ratio |
| Re-determination cadence | *"Định kỳ vào **ngày 01, 10 và 20 hàng tháng**"*; if that lands on a holiday, the next working day |
| Publication lead time | On VSDC's website **at least 02 working days before** it applies |
| Emergency re-assessment | VSDC may re-assess on actual market movements; effective **the working day after publication** |

All VERIFIED. This is unchanged in substance from the pre-KRX cadence already in the
rulebook, and it is why the correct data structure is `(contract_code, effective_date) →
Decimal`, never a scalar. Our `VSD_INITIAL_MARGIN` in `market/margin.py` is date-keyed
only, which the rulebook already flags as insufficient.

### 4.2 The method — and **a tension the source does not resolve**

Phụ lục 2 §1.3 gives the method in three lettered paragraphs. **Two of them state
different observation windows.**

**§1.3.a, verbatim** (phuluc2 L17):

> a. Tỷ lệ ký quỹ ban đầu được tính toán theo phương pháp định lượng rủi ro VaR (**phương
> pháp tham số**) dựa trên **tỷ lệ phần trăm biến động giá 2 ngày (2 days return)** của tài
> sản cơ sở và **độ tin cậy là 99.73%** trong khoảng thời gian **tối thiểu 120 ngày giao
> dịch** liền trước ngày tính toán.

**§1.3.b, verbatim** (phuluc2 L18):

> b. VSDC xác định tỷ lệ ký quỹ ban đầu cho HĐTL chỉ số và HĐTL TPCP dựa trên biến động giá
> của tài sản cơ sở HĐTL chỉ số, giá trái phiếu Chính phủ/chỉ số trái phiếu Chính phủ (áp
> dụng đối với HĐTL TPCP) trong **kỳ quan sát tối thiểu là 250 ngày giao dịch** được đánh
> giá theo phương pháp định lượng rủi ro VaR;

| | §1.3.a | §1.3.b |
|---|---|---|
| Window | **≥ 120 trading days** | **≥ 250 trading days** |
| Wording | *"trong khoảng thời gian tối thiểu … liền trước ngày tính toán"* | *"trong kỳ quan sát tối thiểu là …"* |
| Also specifies | parametric VaR, 2-day returns, 99.73% | which price series feeds which product |

**Both are minima, so they are not strictly contradictory** — any window ≥ 250 satisfies
both. But they cannot both be *the* stated minimum, and an implementer choosing 120 would
comply with (a) and breach (b).

**Report both. Do not silently pick one.** Implement the window as a **required
parameter** with no default, admissible values ≥ 250 (the binding constraint if both
clauses are operative), and make the parameter's provenance note carry this tension
verbatim. A run that has not set it should say so.

**For context, not as a resolution:** the pre-KRX regime used *"at least 90 trading days"*
(VSDC's "Thông tin về ký quỹ" citing QĐ 96 Phụ lục 02, recorded in the rulebook). So the
window has moved 90 → 120/250 under KRX. That the number went **up** is consistent with
either reading and settles nothing.

### 4.3 The VaR statistic — and **the missing conversion formula**

**§1.3.c, verbatim and complete** (phuluc2 L19–26):

> c. Xác định tỷ lệ ký quỹ ban đầu theo phương pháp định lượng giá trị rủi ro VaR
> **Trong đó:**
> **n** : số ngày cần thiết để thanh lý một vị thế khi xảy ra trường hợp mất khả năng thanh
> toán.
> VaR: Giá trị rủi ro tính theo phương pháp luận về VaR tham số với công thức như sau:
> **VaR = (mean + 3 x δ)**
> Trong đó:
> **δ** : độ lệch chuẩn của tập hợp tỷ lệ biến động giá của tài sản cơ sở trong 01 chu kỳ
> quan sát. Tỷ lệ biến động giá được xác định trên cơ sở so sánh giữa giá tài sản cơ sở tại
> ngày tính toán (ngày T) với giá tài sản cơ sở tại **ngày làm việc liền kề thứ 2 trước
> ngày T (ngày T-2)**.
> **Mean**: Giá trị bình quân số học của tập hợp dữ liệu tỷ lệ biến động giá … [same T/T-2
> definition]

> **DEFECT D2 — §1.3.c announces a formula and does not give one.** The heading *"Xác định
> tỷ lệ ký quỹ ban đầu theo phương pháp định lượng giá trị rủi ro VaR"* is followed
> **immediately** by *"Trong đó:"*. The expression that would define **tỷ lệ ký quỹ ban
> đầu** in terms of `VaR` and `n` is **absent from the extraction** — an image, on the
> pattern of §12 D3/D4. Consequence: **`n` is defined and then never used.** We can compute
> `VaR`; we cannot know how VSDC turns `VaR` and `n` into the published ratio.

**What is computable, VERIFIED:**

```
r_t   = 2-day price-change rate of the underlying, T vs T−2
δ     = stdev( {r_t} over the observation window )
mean  = arithmetic mean( {r_t} )
VaR   = mean + 3·δ
```

**What is not, and must not be invented:**

> **INFERRED, and weakly — the ratio itself.** The only self-consistent reading available
> is `rate = VaR` where `n = 2`, since the returns are **already** 2-day returns and a
> further horizon scaling would double-count. A `√(n/2)` scaling is the textbook move and
> is equally consistent with the fragment. **Both are guesses.** Until the formula is
> obtained, **use VSDC's published ratio** (§4.1) and treat §4.3 as a documented but
> unimplementable derivation. Recorded at §12 D2.

**Three further reading notes, all needed before anyone codes this:**

1. **`mean + 3·δ` is asymmetric and the source means it that way.** Three sigma one-sided
   is 99.865%; the **two-sided** 3σ interval is **99.73%**, the figure §1.3.a states. So
   `VaR` is the upper bound of a 99.73% two-sided interval on the return distribution. If
   `mean < 0`, `mean + 3δ` is *smaller* than `3δ`, and the resulting symmetric ±rate grid
   charges less for downside than a downside-only statistic would. **That is what the text
   says. Do not "fix" it to `|mean| + 3δ` or `3δ − mean`.**
2. **The return convention is SILENT.** *"So sánh giữa giá … ngày T với giá … ngày T-2"*
   fixes the **two endpoints** and nothing else: not arithmetic vs log, not the
   denominator (`S_{T-2}` vs `S_T` vs the mean), not overlapping vs non-overlapping
   sampling. §1.3.a's *"tỷ lệ phần trăm biến động giá 2 ngày (2 days return)"* implies a
   percentage, so we read `r_t = (S_T − S_{T−2}) / S_{T−2}`. **INFERRED.** Overlapping
   daily sampling (one observation per trading day) is the only way a 120- or 250-day
   window yields that many observations, so we adopt it — also INFERRED.
3. **Which price series.** §1.3.b names *"biến động giá của tài sản cơ sở"* for index
   futures — the **index**, not the futures price. For an index level this sidesteps the
   corpus's raw-close/adjclose problem (see `price-series-conventions` — that concerns
   *share* prices under splits and dividends; an index level is neither). Confirm the
   `VN30` row in `quote_close` is an index level and not a vendor-adjusted series before
   relying on it.

---

## 5. Giá trị giảm trừ ký quỹ (`OA`) — the offsetting amount

The published heading is *"Giá trị giảm trừ ký quỹ (**offseting** amount)"* — the English
gloss is misspelled in the source (phuluc2 L27, DEFECT D5, cosmetic).

### 5.1 Group formation — the precondition

**Phụ lục 2 §2.1, verbatim** (phuluc2 L28):

> Căn cứ thực tế tình hình thị trường và yêu cầu quản lý rủi ro …, VSDC **có thể** thiết lập
> trên hệ thống nhóm tài sản cơ sở căn cứ vào đặc tính của tài sản cơ sở và kết quả tính
> toán mức độ tương quan (**tương quan Kendall-tau**) giữa các tài sản cơ sở với mẫu dữ liệu
> là giá của tài sản cơ sở trong khoảng thời gian **tối thiểu là 3 năm** liền trước thời
> điểm xác định. Các tài sản cơ sở trong nhóm tài sản cơ sở phải có **tương quan dương** với
> hệ số tương quan **không thấp hơn 0,9** và **một tài sản cơ sở chỉ thuộc một nhóm** tài
> sản cơ sở.

| Rule | Value | Grade |
|---|---|---|
| Statistic | **Kendall's tau**, on underlying **prices** (not returns — the text says *"mẫu dữ liệu là giá của tài sản cơ sở"*) | VERIFIED |
| Sample | **≥ 3 years** immediately preceding the determination date | VERIFIED |
| Admission | **positive** correlation, coefficient **≥ 0.9** | VERIFIED |
| Exclusivity | **each underlying in at most one group** | VERIFIED |
| Who decides | **VSDC**, discretionary (*"có thể thiết lập"*) — groups exist only if VSDC publishes them | VERIFIED |

**The worked example is normative on the exclusivity rule** and worth reproducing, because
it shows the rule is *order-dependent* and not a clustering algorithm
(phuluc2 L29–30). Investor A holds VN30, VN100 and HNX30 index futures;
τ(VN30,VN100)=0.95, τ(VN30,HNX30)=0.91, τ(VN100,HNX30)=0.89. VSDC groups **VN30+VN100**
and excludes HNX30 — because HNX30 clears 0.9 against VN30 but not against VN100. Then:

> VN30 và HNX30 có hệ số tương quan 0,91, đáp ứng điều kiện lớn hơn 0,9 nhưng **do VN30 đã
> được lựa chọn thiết lập nhóm với VN100 nên không thể sử dụng** để thiết lập nhóm VN30 và
> HNX30.

Two rules are visible in the example that §2.1's prose does not state outright, both
**INFERRED**: (i) a group must be **pairwise** ≥ 0.9 across *every* pair in it, not merely
connected; (ii) once an underlying is committed to a group, later candidate groups
containing it are **foreclosed**, so the outcome depends on the order VSDC evaluates
candidates. Note also the example's own text says *"lớn hơn 0,9"* (strictly greater) where
§2.1 says *"không thấp hơn 0,9"* (≥). **We adopt ≥ 0.9, the operative clause.** DEFECT D7.

### 5.2 The formula

**Phụ lục 2 §2.2, verbatim** (phuluc2 L32–39):

> **OA = (B + S) x C x Psr**
> Trong đó:
> OA: Giá trị giảm trừ ký quỹ
> **B**: Giá trị ký quỹ rủi ro trên **một hợp đồng quy chuẩn** có hệ số delta **dương**
> **S**: Giá trị ký quỹ rủi ro trên **một hợp đồng quy chuẩn** có hệ số delta **âm**
> **C**: Số lượng hợp đồng quy chuẩn **được giảm trừ ký quỹ**
> **Psr**: Hệ số tương quan giá (Price relation rate) giữa các tài sản cơ sở

Note `B` and `S` are **per-standardised-contract risk margin values** (VND per contract),
`C` is a **count**, `Psr` is dimensionless — so `OA` is in VND. **DERIVED:** `B + S` is
the combined risk margin of one offsetting long/short standardised pair, and `Psr ∈ [0,1]`
is the fraction of that pair's margin the correlation justifies relieving. At `Psr = 1`
(perfectly co-moving underlyings) the entire pair's risk margin is relieved. **That
arithmetic only makes sense if `OA` is subtracted from risk margin** — see §5.4.

### 5.3 The four sub-quantities

**(a) Hệ số Delta** (phuluc2 L40–43):

> **Hệ số Delta = Số lượng vị thế x Hệ số nhân / Hệ số nhân lớn nhất trong các hợp đồng có
> cùng tài sản cơ sở.**
> Đối với vị thế mua hệ số Delta luôn là **số dương**, đối với vị thế bán hệ số Delta luôn
> là **số âm**.

Normalises position size by the **largest multiplier among contracts on the same
underlying**. VN30F contracts all carry `M = 100,000`, so for our corpus
**delta = signed contract count** exactly.

**(b) Hệ số quy mô — the scale factor** (phuluc2 L44–49):

> - Tính toán trung bình cộng giá của tài sản cơ sở trong khoảng quan sát nhất định
> - Xác định quy mô trung bình cho từng tài sản cơ sở bằng cách nhân giá trị trung bình cộng
>   với hệ số nhân
> - Xác định quy mô trung bình lớn nhất
> - **Hệ số quy mô của tài sản cơ sở = Quy mô trung bình lớn nhất / Quy mô trung bình của
>   tài sản cơ sở**

```
avg_size_i   = mean(price_i over window) × M_i
scale_i      = max_j(avg_size_j) / avg_size_i          # ≥ 1, equals 1 for the largest
```

> **SILENT — the observation window.** *"trong khoảng quan sát nhất định"* — "a certain
> observation period", never specified. §2.1 says ≥3 years for grouping; §5.4's `Psr` gives
> no window either; §6.3's `SMrate` says *"một khoảng thời gian nhất định"* with 252 days
> only in a worked example. **Make it a required parameter with no default.**

**(c) Số lượng hợp đồng quy chuẩn** (phuluc2 L50–51):

> **Số lượng hợp đồng quy chuẩn = Hệ số Delta / Hệ số quy mô**

Since `scale_i ≥ 1`, standardising **shrinks** positions in small-notional underlyings into
units of the largest one. Sign is inherited from delta.

**(d) `C` — how many pair off** (phuluc2 L52–53):

> Số lượng hợp đồng quy chuẩn được giảm trừ ký quỹ là **giá trị nhỏ hơn** khi so sánh số
> lượng hợp đồng quy chuẩn có hệ số Delta **dương** và số lượng hợp đồng quy chuẩn có hệ số
> Delta **âm**.

```
C = min( Σ standardised_i where delta>0 , | Σ standardised_i where delta<0 | )
```

> **INFERRED — the comparison is on magnitudes.** Read literally, *"giá trị nhỏ hơn"* of a
> positive number and a negative number is always the negative one, giving `C < 0` and a
> negative `OA` that would *increase* margin. The only coherent reading compares
> **absolute values**. Also INFERRED: `C = 0` when the group is one-sided — no offset, no
> relief, which is the correct risk answer.

**(e) `Psr` — hệ số tương quan giá** (phuluc2 L54–64):

> Hệ số tương quan giá được xác định theo **từng cặp** tài sản cơ sở thuộc cùng một nhóm …
> **Hệ số tương quan = 1 – Max99|rx – ry| / (Max|rx| + Max|ry|)**
> Trong đó:
> rx: **Biến động giá** của tài sản cơ sở X **sau 2 ngày làm việc**
> ry: … tài sản cơ sở Y sau 2 ngày làm việc
> Max99|rx – ry|: **Phân vị thứ 99** trong tập hợp các giá trị tuyệt đối nêu trên
> Max|rx|: Giá trị lớn nhất của giá trị tuyệt đối biến động giá của tài sản cơ sở X
> …
> Hệ số tương quan giá của **nhóm** tài sản cơ sở là **giá trị nhỏ nhất** trong tập hợp các
> hệ số tương quan giá của từng cặp …

```
Psr(X,Y)  = 1 − P99(|r_X − r_Y|) / ( max|r_X| + max|r_Y| )
Psr(group) = min over all pairs in the group
```

Three readings, all **INFERRED**:

1. **Operator precedence.** `1 − A/B`, not `(1−A)/B`. Only the former is bounded above by
   1 and reduces to 1 when the two series move identically, which is what a
   "correlation rate" must do.
2. **`rx`/`ry` are 2-day *returns*, not absolute price changes.** The text says *"biến động
   giá"* without *"tỷ lệ"* — but the formula differences X against Y directly, and two
   indices at different levels have non-comparable point moves. Returns are the only unit
   under which `|r_X − r_Y|` is meaningful across underlyings. **Note this reading is the
   opposite of the one §6.3 forces**, where the same phrase must mean an absolute change;
   the appendix uses one term for two quantities (DEFECT D8).
3. **Naming collision.** §2.1's *"hệ số tương quan"* is **Kendall's tau on prices, ≥ 0.9,
   used to admit an underlying to a group**. §2.2.e's *"hệ số tương quan"* is **this
   quantity, used to scale the relief**. They share a name, share a symbol-free
   presentation, and are computed completely differently. **Two distinct fields. Do not
   let one populate the other.**

> **SILENT — `Psr`'s observation window**, and **SILENT — whether `Psr` is floored at 0.**
> The expression can go negative if `P99(|r_X − r_Y|)` exceeds `max|r_X| + max|r_Y|`
> (possible only in pathological samples, since a 99th percentile of a difference can
> exceed the sum of maxima only under heavy sampling asymmetry). A negative `Psr` would
> make `OA` negative and *raise* margin.

### 5.4 **Where `OA` enters `MR` — INFERRED, not stated**

**This is the single largest interpretive gap in the model, and it must be flagged at every
use.**

**What Phụ lục 2 says: nothing.** §6.1 and §6.2 — the only two places `MR` is assembled —
never mention `OA` or *giá trị giảm trừ ký quỹ*. §2.2 defines `OA` and stops.

**What QĐ 26 says, verbatim** (Điều 5.1.1, qd26 L269–273):

> 1.1. VSDC xác định **ký quỹ rủi ro** căn cứ vào **tỷ lệ ký quỹ ban đầu VÀ giá trị giảm
> trừ ký quỹ**, trong đó:
> a. **Giá trị giảm trừ ký quỹ là số tiền điều chỉnh GIẢM giá trị ký quỹ rủi ro** trong
> trường hợp các vị thế trên một tài khoản nhà đầu tư có **từ hai tài sản cơ sở trở lên** và
> thuộc một nhóm tài sản cơ sở được VSDC thiết lập …

Separate the grades carefully — an earlier framing collapsed them:

| Claim | Grade |
|---|---|
| `OA` reduces **ký quỹ rủi ro** (`Rm`), and not some other component | **VERIFIED** — Điều 5.1.1.a says *"số tiền điều chỉnh giảm giá trị ký quỹ rủi ro"* in terms |
| `Rm` is *"căn cứ vào"* both the initial margin ratio and `OA` — i.e. `Rm` as it enters §6.2 is already net of `OA` | **VERIFIED as to direction**, since §6.2's `Rm` is the only `Rm` there is |
| The arithmetic is **subtraction**: `Rm = Rm_gross − OA` | **INFERRED** — *"điều chỉnh giảm"* means "adjusts downward", not "subtract". A multiplicative reduction would also satisfy the words |
| It applies **at the group level** | **INFERRED** — `OA` is defined per group (§2.2, §5.1) and `Pgm` is per group, so group level is the natural join, but no clause states it |
| `Rm` is **floored at 0** after the reduction | **INFERRED** — nothing prevents `OA > Rm_gross` |

**We adopt:**

```
Rm(group) = max( 0 , Rm_gross(group) − OA(group) )
```

**Two pieces of internal corroboration, both DERIVED and neither dispositive:**

1. **`MR = Max(ΣPgm, 0)`'s outer `Max` would otherwise be dead code.** Every component in
   §6.2 is non-negative on its face (`Rm` an absolute value, `Sm` a product of
   non-negatives, `MM` a product of non-negatives, `Dm` — see §7.2 — signed but paired with
   a non-negative `DRM`), and `Pgm` is a `Max` against `MM ≥ 0`. So `ΣPgm ≥ 0` always, and
   `Max(…, 0)` never binds. The clause exists, which is weak evidence that a drafter
   expected a component to be capable of going negative — and `Rm_gross − OA` is the
   obvious candidate.
2. **§5.2's units only work as a subtraction.** `(B+S)·C·Psr` is "risk margin per
   offsetting standardised pair × number of pairs × correlation fraction" — a **VND
   amount of risk margin to give back**. It is dimensionally a margin credit and nothing
   else.

**Do not ship this as "the regulation says".** Ship `Rm_gross`, `OA` and the netted `Rm`
as three separately-inspectable values, with the combination step carrying its own
provenance string naming Điều 5.1.1.a and the word INFERRED. **For a single-underlying
account the question is moot: Điều 5.1.1.a's own precondition is *"từ hai tài sản cơ sở
trở lên"*, so `OA = 0` and `Rm = Rm_gross`.** That is every account our corpus can
represent (§10).

---

## 6. Ký quỹ song hành (`Sm`) — basis / calendar-spread margin

### 6.1 What it is for

**QĐ 26 Điều 5.2, verbatim** (qd26 L286–294):

> Ký quỹ song hành hợp đồng tương lai là giá trị ký quỹ … phải nộp để bù đắp **mức lỗ tiềm
> tàng tăng thêm so với giá trị ký quỹ rủi ro** do sự khác biệt về biến động giá của tài sản
> cơ sở và biến động giá của hợp đồng tương lai.
> Ký quỹ song hành áp dụng cho **một tài sản cơ sở** là giá trị nhỏ nhất trong số hai giá
> trị sau:
> (i) Ký quỹ song hành tính toán cho **số dư vị thế mua** và
> (ii) Ký quỹ song hành tính toán cho **số dư vị thế bán** của tài sản cơ sở đó.

This is the exact complement of the §3.1 netting result: `Rm` collapses `Pm` and `Pb` into
a net, `Sm` charges for the basis risk that netting concealed.

### 6.2 The formulas

**Phụ lục 2 §3.1–3.2, verbatim** (phuluc2 L66–77):

> **SM = Min (SMl, SMs)**
> - SMl: Giá trị ký quỹ song hành của số dư vị thế mua
> - SMs: Giá trị ký quỹ song hành của số dư vị thế bán
> **SMl/s = P x S x M x SMrate**
> P: Số dư vị thế mua hoặc bán
> S: Giá đóng cửa của tài sản cơ sở tại ngày tính toán
> M: Hệ số nhân hợp đồng
> SMrate: Tỷ lệ ký quỹ song hành

```
SMl = P_long  × S × M × SMrate
SMs = P_short × S × M × SMrate
Sm  = min(SMl, SMs)  =  min(P_long, P_short) × S × M × SMrate
```

**DERIVED:** since `S`, `M` and `SMrate` are common to both legs, `Sm` reduces to
`min(P_long, P_short) × S × M × SMrate` — the **matched** portion of the book. A one-sided
book has `min = 0` and pays no basis margin, which is correct: there is no spread to
mismatch. `P_long`/`P_short` are gross balances **per underlying, summed across expiry
months** (Điều 5.2's *"áp dụng cho một tài sản cơ sở"*).

> **INFERRED — `P` is a gross count, not a net.** §3.2 says only *"Số dư vị thế mua hoặc
> bán"*. Under a net reading one of the two legs is always 0 and `Sm` is identically 0,
> which would make the whole component dead. Gross is the only reading that gives `Sm` a
> purpose. Note this differs from §3.1's `Pm`/`Pb`, which *algebraically* net whether you
> intend it or not.

> **DEFECT D9 — `Sm` is one number per underlying but `SMrate` is per expiry-month pair.**
> §3.3 (below) computes a rate *"theo từng cặp sản phẩm hợp đồng tương lai có cùng tài sản
> cơ sở"* and then defines `SMrate` as **one** 90th-percentile drawn from the pooled set
> across all pairs. So the per-pair computation exists only to feed the pool; the applied
> rate is a single per-underlying scalar. This reading is forced by §3.2's single `SMrate`
> term, but the appendix never says the per-pair rates are discarded.

### 6.3 `SMrate` — the basis rate

**Phụ lục 2 §3.3, verbatim** (phuluc2 L78–87):

> Tỷ lệ ký quỹ song hành được xác định theo **từng cặp sản phẩm hợp đồng tương lai có cùng
> tài sản cơ sở** dựa trên dữ liệu giá đóng cửa của tài sản cơ sở và **biến động DSP/FSP**
> (trong một khoảng thời gian nhất định). Biến động DSP/FSP được xác định trên cơ sở so sánh
> giữa DSP/FSP tại ngày tính toán (ngày T) với DSP/FSP tại **ngày làm việc liền kề thứ 2
> trước ngày T (ngày T-2)**.
> **SPRt = |(rt1 - rt2)/St|**
> Trong đó:
> δSPRt: Tỷ lệ ký quỹ song hành tại ngày t
> **rt1**: Biến động DSP/FSP của hợp đồng tương lai **tháng đáo hạn hiện tại (spot month)**
> sau 2 ngày làm việc
> Mrt2: Biến động DSP/FSP của hợp đồng tương lai **các tháng đáo hạn xa được ghép cặp** sau
> 2 ngày làm việc
> **St**: Giá của tài sản cơ sở tại ngày t
> Tỷ lệ ký quỹ song hành áp dụng cho các tháng đáo hạn của một tài sản cơ sở (SMrate) được
> xác định là **phân vị thứ 90** trong tập hợp các tỷ lệ ký quỹ song hành của các tháng đáo
> hạn hợp đồng tương lai có cùng tài sản cơ sở được tính toán trong một khoảng thời gian
> nhất định.

```
r1_t   = DSP_spot(t)  − DSP_spot(t−2)          # 2-business-day DSP change, spot month
r2_t   = DSP_far(t)   − DSP_far(t−2)           # same, for each paired far month
SPR_t  = | (r1_t − r2_t) / S_t |               # S_t = underlying price on day t
SMrate = P90( { SPR_t : all pairs × all days in the window } )
```

**The worked example** (phuluc2 L87): VN30 index futures with expiry months
VN302403, VN302404, VN302406, VN302409 → compute `SPR_t` for the pairs
(2403,2404), (2403,2406), (2403,2409) **for each day over 252 trading days**, and take the
90th percentile of the pooled set.

Reading notes:

1. **`rt1`/`rt2` are absolute DSP *changes*, not returns — INFERRED, but forced.** Dividing
   by `S_t` produces a dimensionless rate **only if** the numerator is in price units. If
   `r` were already a return, `(r1−r2)/S_t` would be dimensionally wrong by one factor of
   price. Note the text writes *"Biến động DSP/FSP"* here versus §1.3's *"**tỷ lệ** biến
   động giá"* — the presence of *tỷ lệ* there and its absence here supports the reading.
   **But §5.3(e) requires the opposite reading of the same phrase.** DEFECT D8.
2. **The spot month is always one leg.** Every pair is (spot month, some far month); far
   months are never paired with each other. VERIFIED from *"hợp đồng tương lai tháng đáo hạn
   hiện tại (spot month)"* and the example.
3. **252 is EXAMPLE-sourced, not RULE-sourced.** The operative sentence says *"trong một
   khoảng thời gian nhất định"* — unspecified — **twice**. Only the *Ví dụ* names 252 days.
   Contrast §8.2, where **≥252** is in the rule text itself. **Do not present 252 as the
   prescribed `SMrate` window.** Make it a required parameter; if 252 is used, its
   provenance string must say "from the worked example in Phụ lục 2 §3.3, not from the
   rule".
4. **Symbol drift.** The formula line names the quantity `SPRt`; the definition list names
   it `δSPRt`; the far-month term is printed `Mrt2` with a stray leading `M`. All three are
   transcription noise (DEFECT D5) — the arithmetic is unambiguous.

> **SILENT — DSP on days a far month did not trade.** `SPR_t` needs both legs' DSP at `t`
> and `t−2`. Deferred expiries are frequently untraded. QĐ 26 Điều 23.2 lets VSDC
> substitute a **theoretical price** when trade prices *"không đáp ứng yêu cầu tính toán"*
> (qd26 L736–739), with the method in **Phụ lục 6 — which we do not have.** So the gap-fill
> rule exists, is delegated, and is unobtained.

---

## 7. Ký quỹ chuyển giao (`Dm`) — delivery margin

> **SCOPE: DOCUMENTED, NOT FOR BUILDING.** All GB-futures work is deferred by author
> decision. This section exists so the model is complete and so the Phụ lục 8 dependency is
> on record. It applies **only** to HĐTL TPCP.

### 7.1 When it applies

| Rule | Value | Grade |
|---|---|---|
| Purpose | Cover the loss if the investor lacks **cash to pay** or **bonds to deliver** at physical settlement | VERIFIED (qd26 Điều 5.3, L295–299) |
| Applies on | *"tại **ngày giao dịch cuối cùng**, **ngày làm việc liền sau** ngày giao dịch cuối cùng"* — the last trading day **E** and **E+1** | VERIFIED (phuluc2 §6.2, L137) |
| Applies to | Only contracts *"**chưa được nộp** trái phiếu chuyển giao để thực hiện nghĩa vụ thanh toán"* — those for which the delivery bond has not yet been posted | VERIFIED (same) |
| Settlement date | **E+3** (*"ngày làm việc thứ ba sau ngày giao dịch cuối cùng"*) | VERIFIED (qd26 Điều 22.1, L654–656) |

> **DEFECT D10 — the E+2 hole.** `Dm` is stated for **E** and **E+1**; settlement is
> **E+3**; and E+2 is a live operational day (Điều 22.4 requires the seller to confirm the
> delivery bond list by 15h30 on E+2, qd26 L681–688). The literal reading leaves an
> undelivered position unmargined for delivery risk on E+2. Do not silently extend the
> window; record the reading and the gap.

### 7.2 The two components

**Phụ lục 2 §4.1.a — mark-to-market, verbatim** (phuluc2 L90–98):

> **MTM = (Aq x (FSP – Cp) x m) + ((Tq x (Cp – FSP)x m))**
> MTM: Ký quỹ do định giá lại theo giá thị trường
> Aq: Số lượng HĐTL **mua** trái phiếu
> Tq: Số lượng HĐTL **chuyển giao** trái phiếu
> FSP: Giá thanh toán cuối cùng
> Cp: Giá đóng cửa của tài sản cơ sở tại ngày giao dịch cuối cùng
> m: Hệ số nhân HĐTL TPCP

**Phụ lục 2 §4.1.b — delivery risk, verbatim** (phuluc2 L99–108):

> **DRM = (Aq x (Cp – Lp) x m) + ((Tq x (Hp – Cp)x m))**
> DRM: Ký quỹ rủi ro chuyển giao
> Lp: Giá **thấp nhất** theo kịch bản biến động giá
> Hp: Giá **cao nhất** theo kịch bản biến động giá
> [Aq, Tq, Cp, m as above]

**Reading:** `Aq` is the long/buy side (receives bonds, pays cash), `Tq` the delivering
short side. `MTM` charges each side the FSP-vs-close basis in its adverse direction and is
**signed** — it can be negative. `DRM` charges the buyer for a fall to `Lp` and the seller
for a rise to `Hp`, so `DRM ≥ 0` always (DERIVED).

> **INFERRED — `Dm = MTM + DRM`.** §4.1 says only *"Ký quỹ chuyển giao **gồm hai giá trị
> thành phần** như sau"* — comprises two component values. It never writes the combination.
> Addition is the obvious reading and the only one consistent with `Dm` appearing as a
> single additive term in §6.2. Not stated.

**§4.3 (phuluc2 L110):** `Hp` and `Lp` come *"dựa trên kịch bản biến động giá theo hướng
dẫn tại mục 1.2 và 1.3"* — i.e. the §3.2 scenario grid. Under our adopted reading,
`Lp = S0×(1−rate)` (scenario `k=−10`) and `Hp = S0×(1+rate)` (scenario `k=+10`).
**This inherits DEFECT D1 in full**: `Hp` and `Lp` are only distinct because we
reconstructed the missing `k`. Under the literal text they are equal.

### 7.3 The underlying is the CTD bond — **and Phụ lục 8 is missing**

**Phụ lục 2 §4.2, verbatim** (phuluc2 L109):

> Tài sản cơ sở sử dụng để xác định các giá trị **ký quỹ rủi ro, ký quỹ song hành và ký quỹ
> chuyển giao** là **trái phiếu rẻ nhất để chuyển giao (CTD)** trong danh sách các trái
> phiếu có thể chuyển giao của HĐTL TPCP **tháng đáo hạn gần nhất (spot month)** tại thời
> điểm xác định. **Phương pháp xác định trái phiếu rẻ nhất để chuyển giao theo hướng dẫn tại
> Phụ lục 8 Quy chế này.**

**This makes Phụ lục 8 load-bearing for all three of `Rm`, `Sm` and `Dm` on GB futures** —
not just the delivery component. Without it, no GB-futures margin number can be produced at
all, because the price series `S` itself is undefined.

> **DEFECT D11 — QĐ 26 cites Phụ lục 8 for two unrelated subjects.** Điều 24.1 says *"Các
> **chứng từ điện tử** trong Quy chế này được quy định chi tiết tại **Phụ lục 8**"*
> (qd26 L753–754). Phụ lục 2 §4.2 says the **CTD method** is *"tại Phụ lục 8"*. Those are
> two different appendices' worth of content under one number. Since Điều 30.4 cites
> **Phụ lục 9** for position transfers (qd26 L1069–1070), the numbering runs to at least 9
> and one of the two Phụ lục 8 references is wrong. **Anyone retrieving "Phụ lục 8" must
> check which content they actually got.**

**Also needed and also absent from our holdings:** the deliverable-bond list and per-bond
conversion factors, which VSDC publishes 3 trading days before a contract's first trading
day and freezes ≥30 working days before the last trading day (qd26 Điều 7.2, L341–351).
The conversion-factor formula is at Điều 7.3 (L352–365) and **its two expressions are
images — only the variable glossary survives** (`CF`, `Lc`, `r`, `k`, `n`, `E`, `Dn`).
DEFECT D4.

---

## 8. Ký quỹ tối thiểu (`MM`) — minimum margin

### 8.1 What it is for, and the formula

**QĐ 26 Điều 5.4, verbatim** (qd26 L300–304):

> Ký quỹ tối thiểu là giá trị ký quỹ nhằm **bù đắp chi phí có thể phát sinh** trong trường
> hợp thành viên bù trừ mất khả năng thanh toán bao gồm **giá dịch vụ giao dịch đóng vị thế
> bắt buộc, chi phí hành chính** và chi phí liên quan khác (nếu có).

So `MM` is a **close-out cost floor**, not a risk charge — which is why §6.2 applies it as
`Max((Rm+Sm+Dm), MM)` rather than adding it.

**Phụ lục 2 §5.1, verbatim** (phuluc2 L112–117):

> **MM = P x MF**
> MM: Ký quỹ tối thiểu
> P: **Số dư vị thế HĐTL cuối ngày**
> MF: Giá trị ký quỹ tối thiểu xác định cho **một tháng đáo hạn HĐTL** (giá trị này **không
> được xác định tại ngày giao dịch cuối cùng**)

**Phụ lục 2 §5.2, verbatim** (phuluc2 L118–125):

> **Giá trị ký quỹ tối thiểu trên một hợp đồng = R x M x St**
> R: **Trung bình cộng** (đối với sản phẩm có thanh khoản) hoặc **trung vị** (sản phẩm không
> có tính thanh khoản) của tập hợp các giá trị được xác định theo công thức:
> **(Giá chào bán thấp nhất – Giá chào mua cao nhất)/(Giá chào bán thấp nhất + Giá chào mua
> cao nhất)**
> Giá chào bán thấp nhất và giá chào mua cao nhất **của từng giao dịch được khớp lệnh** được
> xác định **theo từng giao dịch** trong khoảng thời gian **tối thiểu 252 ngày giao dịch**
> liền trước ngày tính toán.
> M: Hệ số nhân hợp đồng
> St: Giá của tài sản cơ sở tại ngày tính toán

```
spread_i = (lowest_ask_i − highest_bid_i) / (lowest_ask_i + highest_bid_i)   # per matched trade
R        = mean(spread_i)     if the product is liquid
         = median(spread_i)   if the product is illiquid
MF       = R × M × St
MM       = P × MF
```

**DERIVED:** `(ask−bid)/(ask+bid) = (ask−bid)/(2·mid)` — the **half relative spread**. So
`MF = half_spread × notional_per_contract`, i.e. one contract's expected cost of crossing
the book once. That is exactly the "forced close-out service cost" Điều 5.4 describes, and
it is a good independent check that the formula has been read correctly.

### 8.2 The five things this needs that the text does not give

1. **`R` is a spread on PRICES, not sizes.** *Giá chào bán thấp nhất* / *giá chào mua cao
   nhất* are the **lowest ask price** and **highest bid price** — top of book. No quantity
   appears anywhere in §5.2. This matters for feasibility; see §10.5, which corrects a
   premise.
2. **≥252 trading days is in the RULE**, unlike §6.3's 252. VERIFIED, and it is a minimum,
   so a longer window complies.
3. **SILENT — what makes a product "liquid".** The mean/median switch is a real fork
   (median is materially lower on a right-skewed spread distribution) and **the criterion
   is not given**. Điều 6.2.a mentions a liquidity-based eligible-collateral list *"theo
   phương thức quy định tại Phụ lục 3"* (qd26 L323–325), but that is a different list for a
   different purpose, and **Phụ lục 3 is unobtained**. Make the classification a required
   input; do not derive one.
4. **INFERRED — `P` is a gross contract count.** §5.1 says *"Số dư vị thế HĐTL cuối ngày"*.
   A close-out cost must scale with contracts to be *closed*, so a net reading would
   under-charge a spread book that still has two legs to unwind. Not stated.
5. **INFERRED — `MM = 0` on the last trading day.** §5.1 says `MF` *"không được xác định tại
   ngày giao dịch cuối cùng"*. With `MF` undefined, §6.2's `Max((Rm+Sm+Dm), MM)` has no
   second operand. Treating `MM` as 0 makes `Pgm = Rm+Sm+Dm`, which is coherent — and note
   it dovetails exactly with `Dm` **switching on** on that same day (§7.1). The two
   components hand over. Neither document says so.

> **DEFECT D12 — `MF`'s unit is stated twice, differently.** §5.1 calls `MF` *"Giá trị ký
> quỹ tối thiểu xác định cho **một tháng đáo hạn HĐTL**"* (per expiry month); §5.2's formula
> is headed *"Giá trị ký quỹ tối thiểu **trên một hợp đồng**"* (per contract). `MM = P × MF`
> only balances dimensionally if `MF` is **per contract**. **We adopt per contract**, with
> §5.1's phrase read as "determined per expiry month" (i.e. the rate is computed separately
> for each expiry month), not "the total for an expiry month".

---

## 9. Assembly — the order of operations

Everything above, in the order an implementation must execute it. Grades carry through.

```
per underlying u, at end of session on date d:
  1.  rate_u      = VSDC published initial margin ratio for u on d           [VERIFIED §4.1]
  2.  S_u         = closing price of the underlying on d                     [VERIFIED §3.1]
  3.  Sk_u        = S_u × (1 + k × rate_u/10),  k = −10 … +10                [RECONSTRUCTED §3.2 — D1]
  4.  Lk_u        = (Pm_u − Pb_u) × (Sk_u − S_u) × M_u                       [VERIFIED §3.1]
  5.  Rm_gross_u  = max(0, −min_k Lk_u)                                      [INFERRED floor §3.1]
  6.  Sm_u        = min(P_long_u, P_short_u) × S_u × M_u × SMrate_u          [VERIFIED §6.2; P gross INFERRED]
  7.  MM_u        = P_gross_u × (R_u × M_u × S_u)                            [VERIFIED §8.1; P gross INFERRED]
  8.  Dm_u        = MTM_u + DRM_u  if GB future and d ∈ {E, E+1} and undelivered, else 0
                                                                             [INFERRED sum §7.2; DEFERRED]

per group g (a VSDC-published group, or a singleton — INFERRED §2.2):
  9.  Rm_gross_g  = Σ_{u ∈ g} Rm_gross_u                                     [INFERRED aggregation]
  10. OA_g        = (B_g + S_g) × C_g × Psr_g,   0 if |g| = 1                [VERIFIED §5.2]
  11. Rm_g        = max(0, Rm_gross_g − OA_g)                                [INFERRED §5.4]
  12. Pgm_g       = max( Rm_g + Σ Sm_u + Σ Dm_u , Σ MM_u )                   [VERIFIED §2.1]

per account:
  13. MR          = max( Σ_g Pgm_g , 0 )                                     [VERIFIED §2.1]

monitoring (NOT a ladder):
  14. violation   := margin_assets < MR                                      [VERIFIED §2.4]
  15. checkpoints := 09h30 / 14h00 / 16h30; cure before 09h30 next trading day
  16. escalation  := uncured 03 working days -> another member closes out
```

**Steps 9 and 12 need care.** §6.2's `Pgm` is written with scalar `Rm`, `Sm`, `Dm`, `MM`
but is defined **per group**, and a group may hold several underlyings. How the
per-underlying `Sm`, `Dm` and `MM` roll up to the group is **not stated**; summation is
INFERRED and is the conservative direction. Steps 9–12 are the least sourced part of the
whole model and should be implemented as separately-inspectable intermediate values.

**Object placement, per house rule.** **Everything in §§2–9 is a depository rule** —
gazetted, dated, cited — and belongs in the rules object alongside `initial_margin_rate`
and `position_limit`, never in `BrokerTerms`. The only genuinely commercial quantities in
the derivatives margin chain are (i) the clearing member's own requirement on the investor,
which Điều 5.1.1.b lets the member set *"căn cứ"* VSDC's ratio, and (ii) any tighter
in-house monitoring the member runs. Those stay in `BrokerTerms`, and they must **not** be
described as an 80/90/100 utilisation ladder (§12).

---

## 10. FEASIBILITY — what our data contract can actually supply

Measured against the corpora on this machine on 2026-08-26, not assumed. Two sources:
`hermes-parquet/` (554.6 MB, the usual `PLUTUS_DATA_ROOT`) and
`hermes-offline-market-data-pre-2023/` (21 GB, the raw tick archive).

### 10.0 The verdict table

| Component | Status | Blocker |
|---|---|---|
| **`Rm` scenario grid** (§3) | **IMPLEMENTABLE TODAY** | none — needs only VN30 close, `M`, positions, and VSDC's published rate |
| **`MR` / `Pgm` assembly** (§2, §9) | **IMPLEMENTABLE TODAY** | none, for a single-underlying account |
| **Monitoring test** (§2.4) | **IMPLEMENTABLE TODAY** | none — it is `assets < MR` plus a clock |
| **`rate` from VaR** (§4) | **VaR computable; the ratio is NOT** | §1.3.c's conversion formula is missing from the source (D2). Use VSDC's published series |
| **`Sm`** (§6) | **NOT as specified.** Possible only under a declared close-for-DSP substitution | no usable DSP series exists in either corpus |
| **`MM`** (§8) | **Computable for VN30F** — this corrects the brief | needs a 41M×97M as-of join; and the liquid/illiquid rule is SILENT |
| **`OA`** (§5) | **NOT IMPLEMENTABLE, and structurally unnecessary** | corpus has exactly one derivatives underlying; and VSDC must publish a group first |
| **`Dm`** (§7) | **NOT IMPLEMENTABLE** | no GB futures in the corpus at all; needs Phụ lục 8, deliverable list, conversion factors |

### 10.1 `Rm` — implementable today, no new data

| Input | Have it? | Evidence |
|---|---|---|
| `S` — VN30 index daily close | **YES** | `quote_close`, ticker `VN30`: **2,725 rows, 2012-02-06 → 2022-12-30** |
| `M` — contract multiplier | **YES** | `RuleSet`, 100,000đ per index point for VN30F/VN100F |
| `Pm`, `Pb` | **YES** | from the simulated account; not market data |
| `rate` | **YES, with a caveat** | `VSD_INITIAL_MARGIN` = 10% / 13% / 17% by effective date. **Press-sourced, no quyết định number**, and date-keyed where `(contract_code, date)` is correct |

**This is the whole of `Rm`.** The scenario grid adds no data requirement beyond the ratio,
because `Sk` is generated arithmetically from `S` and `rate`. The one genuine caveat is
**D1** — the reconstructed `k`.

A live wrinkle for any historical walk: the corpus window is **2021–2022**, where the ratio
was **13%** (to 2022-12-14) then **17%**. `MarginConfig`'s undated `0.17` default is wrong
for most of it — a defect `market/margin.py` already documents.

### 10.2 `rate` from VaR — the statistic is reachable, the ratio is not

**The observation window is comfortably satisfied.** VN30 has 2,725 daily closes; even
§1.3.b's ≥250 leaves a decade of history. §4.2's 120-vs-250 tension is therefore **not a
data problem for us** — both windows are available, and the question is purely which the
rule prescribes.

**What blocks it is the source, not the corpus:** §1.3.c's expression converting `VaR` and
`n` into the ratio is missing (D2). We can compute `mean + 3δ` on 2-day VN30 returns; we
cannot know what VSDC does with it. **Use the published ratio and treat §4.3 as
documentation.**

Two secondary cautions:

- **Check what the `VN30` row in `quote_close` actually is** before computing returns on
  it. The share-price columns have a known convention trap (`quote_close` unadjusted,
  `quote_adjclose` total-return); an index level should be neither, but that is an
  assumption until verified.
- **GB futures have no underlying series here at all** — no government-bond price index, no
  yield curve. §1.3.b's GB branch is unreachable regardless.

### 10.3 `OA` — not implementable, and correctly zero anyway

**The corpus contains exactly one derivatives underlying.** Measured:

- `quote_close` futures rows: **28 contract codes, all `VN30F*`**, 2021-01-04 → 2022-12-30.
- **No VN100 index and no VN100F contracts.** The only `VN100` string in the corpus is
  `FUEVN100`, an **ETF fund certificate** on HSX — not an index, not a futures underlying.
- **No GB futures, no TPCP tickers** in `quote_ticker.csv`.

So there is no second underlying to correlate, no Kendall-tau to compute, and no group to
form. **This is not a gap to close — it is the right answer.** Điều 5.1.1.a's own
precondition is *"từ hai tài sản cơ sở trở lên"*, so for every account our corpus can
represent, `OA = 0` and `Rm = Rm_gross`, **by the rule and not by a shortcut**. The §5.4
inference, which is the model's weakest link, therefore **does not bind on anything we can
build today**. Implement `OA` as a stub that returns zero for a single-underlying account
and raises on a multi-underlying one, rather than silently computing an inferred number.

Two further blockers, both upstream of data:

1. **VSDC must publish a group before one exists.** §2.1 is discretionary (*"có thể thiết
   lập"*). Whether any group has ever been published is **unknown to this document**.
2. **≥3 years of prices** would be needed per underlying. VN30 has it (2012→2022); a
   hypothetical second underlying would need its own.

### 10.4 `Sm` — the DSP series does not exist

**This is the hard blocker, and it is worse than it looks.**

`quote_settlementprice` — the only table that could carry DSP — measures:

- **3,223 rows** across **18 distinct dates**, 2022-06-13 → 2022-12-15
- **3 symbols only**: `VN30F2206`, `VN30F2208`, `VN30INDEX`
- up to **261 observations per symbol per day**

That last figure is decisive: **this is an intraday tick sample, not a daily settlement
series.** A DSP is one value per contract per day. Whatever this table is, it is not the
DSP series `SMrate` needs, and no amount of processing turns 18 days into 252.

**The substitution, and its cost.** Futures **closing prices** do exist —
`quote_close` carries 28 VN30F codes over **2021-01-04 → 2022-12-30** (~490 trading days),
with 40–170 rows per contract depending on whether it was a serial or quarterly month.
Substituting close for DSP would make `SPR_t` computable. But:

- **DSP ≠ close.** QĐ 26 Điều 23.2 defines DSP from HNX-supplied trade data with VSDC
  entitled to substitute a theoretical price, method in **Phụ lục 6 — unobtained**
  (qd26 L736–739, L747–748). The relationship between DSP and the day's close is exactly
  the thing we cannot check.
- **It changes what `SMrate` measures.** `SPR_t` is a *basis* statistic; substituting a
  different price definition into both legs changes the quantity, not just its noise.
- **Pair identity rotates monthly.** Every pair is (spot month, far month) and the spot
  month rolls, so a 252-day series must be chained by **relative maturity**, not by
  contract code. Per-contract row counts (serial months ~40 days) make this mandatory, not
  optional.

**Verdict: `Sm` is not implementable as specified.** It is implementable under a
**declared substitution** that must be labelled as one at every use — the same discipline
`equity-margin-spec.md` §2.8 applies to its DERIVED top-up formulas. Do not present a
close-derived `SMrate` as the rule's `SMrate`.

### 10.5 `MM` — **the brief's premise is wrong, and this is computable**

**The task brief states that `MM` "needs 252 days of bid/ask, and our `quote_bidsize`/
`asksize` Parquet files are 152-byte header-only stubs". The second half is true. The first
half does not follow, and the conclusion is wrong.**

**`R` needs bid/ask PRICES, not sizes.** §8.1's formula is
`(giá chào bán thấp nhất − giá chào mua cao nhất)/(giá chào bán thấp nhất + giá chào mua
cao nhất)` — lowest **ask price**, highest **bid price**. **No quantity term appears
anywhere in Phụ lục 2 §5.2.** The empty size tables do not block `MM`.

**And we have the prices, for futures specifically.** Measured in the raw tick archive:

| Table | Size | Rows | Span | Schema |
|---|---|---|---|---|
| `quote_bidprice.csv` | 3.9 GB | 97,062,986 | 2021-01-15 → 2022-12-30 | `datetime, tickersymbol, price, depth`, `depth ∈ {1,2,3}` |
| `quote_askprice.csv` | 3.8 GB | 95,055,009 | same | same |
| `quote_matched.csv` | 1.5 GB | 41.3M | 2020-12-02 → 2022-12-30 | the matched trades `R` is defined per |
| `quote_bidsize` / `asksize` | **37 bytes CSV / 152 bytes Parquet** | **0** | — | header only: `datetime, tickersymbol, quantity, depth` |

**VN30F is in the book tables.** Scanning the first 40M lines of `quote_bidprice.csv`
alone: **2,981,240 VN30F rows**, of which **920,699 at `depth = 1`** — top of book, which
is exactly and only what `R` needs — across **17 VN30F contract codes**, 2021-01-15 →
2022-02-15 within that slice (the file continues to 2022-12-30).

**So `MM` is computable for VN30F.** Three real costs, none of them fatal:

1. **The join is expensive.** `R` is defined *"của từng giao dịch được khớp lệnh … theo
   từng giao dịch"* — **per matched trade**. That requires an as-of join of each
   `quote_matched` row to the prevailing `depth=1` bid and ask at that microsecond,
   over 41.3M trades against ~64M top-of-book price updates. Feasible, not cheap, and it
   is the one place in this document where a real engineering task exists.
2. **The window is adequate but not generous.** Book data starts **2021-01-15** and ends
   2022-12-30 — about **485 trading days**. §8.2's **≥252** is satisfied, with roughly one
   window's worth of slack. Any date before 2021-01-15 has no `R` at all.
3. **The liquid/illiquid switch is SILENT** (§8.2 item 3) and changes the answer. It must
   be a supplied input.

**The size tables still matter — for other things.** Depth-of-book liquidity, queue
position and realistic partial fills all need them, and they are absent. That is a real and
recorded gap. It is simply not this gap.

### 10.6 `Dm` — not implementable, and out of scope

Every input is missing, independently:

- **No GB futures in the corpus.** No TPCP tickers in `quote_ticker.csv`.
- **Phụ lục 8** (CTD selection) — not held, and its identity is ambiguous (D11).
- **Deliverable-bond list and conversion factors** — VSDC-published, not in the corpus; and
  the Điều 7.3 conversion-factor formulas are images (D4).
- **`Cp`** — the CTD bond's closing price — undefined until CTD selection exists.
- **`FSP`** for GB futures is the last trading day's DSP (Điều 23.3.b) — and §10.4 shows we
  have no DSP series.
- **HNX government-bond yield curve** (Điều 8.2.a) — needed even to *value* bond
  collateral, let alone margin a bond future.

**Consistent with the author's scope decision. Do not start here.**

### 10.7 What is missing that no data acquisition can fix

Retrieval tasks, in descending value:

| # | Missing | Blocks | Where to get it |
|---|---|---|---|
| 1 | **Phụ lục 2 §1.3.c's ratio formula** (D2) | computing `rate` ourselves at all | công báo PDF or VSDC's own copy |
| 2 | **The Phụ lục 2 §1.2 scenario table as typeset** (D1) | confirming the reconstructed `k` | same |
| 3 | **Phụ lục 6** (DSP method) | `Sm` honestly; every settlement price | QĐ 26 appendices |
| 4 | **Điều 8.1's `VKQ` formula** (D3) | valuing margin assets — the other half of the test | same |
| 5 | **Phụ lục 8** (CTD) | all GB-futures margin | same — but check D11 first |
| 6 | **Phụ lục 3** (collateral liquidity method) | possibly §8.2's liquid/illiquid switch | same |
| 7 | Whether VSDC has ever **published an underlying-asset group** | whether `OA` is ever non-zero in reality | VSDC website |

Items 1, 2 and 4 are the same retrieval: **a copy of QĐ 26 whose formulas are text rather
than images.** That single fetch closes three of the seven.

---

## 11. Register of everything INFERRED

Consolidated so an implementer can find them without reading the prose. **Each of these is
a place where a reasonable reader could have chosen differently.** Every one must carry its
own provenance string in code, on the `BrokerTerms.PROVENANCE` pattern.

| # | § | The inference | Why it was unavoidable | Binds on VN30F-only work? |
|---|---|---|---|---|
| I1 | 3.2 | **`Sk = S0 × (1 + k × rate/10)`** — the missing `k` | The printed formula has no `k` and collapses 21 scenarios to one point, contradicting the same cell's `−10 ≤ k ≤ 10` | **YES — this is the load-bearing one** |
| I2 | 3.1 | `Rm = max(0, −min_k Lk)` — the zero floor | *"absolute value of the largest loss"* is undefined when there is no loss | only for a perfectly flat book (both readings give 0) |
| I3 | 2.2 | An ungrouped underlying forms a **singleton group** with `OA = 0` | §6.1 sums over groups; otherwise a lone underlying's risk vanishes from MR | **YES** |
| I4 | 5.4 | `Rm = max(0, Rm_gross − OA)` — the arithmetic, the level, the floor | Điều 5.1.1.a fixes the **direction** (VERIFIED); subtraction, group-level application and the floor are ours | no — `OA = 0` by the rule for one underlying |
| I5 | 5.3(d) | `C` compares **absolute values** | the literal reading gives `C < 0` and margin that *increases* on an offset | no |
| I6 | 5.3(e) | `Psr`: precedence is `1 − A/B`; `rx`/`ry` are **returns** | only reading bounded by 1; only unit comparable across underlyings | no |
| I7 | 6.3 | `rt1`/`rt2` are **absolute DSP changes** | division by `S_t` is dimensionally wrong otherwise. **Opposite of I6 for the same Vietnamese phrase** — see D8 | yes, if `Sm` is built |
| I8 | 6.2 | `P` in `SMl`/`SMs` is a **gross** count | a net reading makes one leg 0 and `Sm` identically 0 | yes, if `Sm` is built |
| I9 | 8.2 | `P` in `MM` is a **gross** count | close-out cost scales with contracts to be closed | yes, if `MM` is built |
| I10 | 8.2 | **`MM = 0` on the last trading day** | `MF` is expressly not determined then; `Max(·, MM)` needs an operand | yes, on expiry days |
| I11 | 7.2 | `Dm = MTM + DRM` | *"gồm hai giá trị thành phần"* never states the combination | no — GB futures deferred |
| I12 | 9 (steps 9, 12) | Per-underlying `Rm`, `Sm`, `Dm`, `MM` **sum** to the group level | §6.2 is written with scalars but defined per group | no — singleton groups |
| I13 | 4.3 | `rate = VaR` at `n = 2` | the conversion formula is missing; returns are already 2-day | **avoided in practice** — use the published ratio |
| I14 | 4.3 | `r_t = (S_T − S_{T−2})/S_{T−2}`, overlapping daily sampling | *"so sánh"* fixes only the endpoints; §1.3.a says *tỷ lệ phần trăm* | only if computing `rate` ourselves |
| I15 | 5.1 | Grouping is **pairwise** ≥0.9 and **order-dependent/foreclosing** | visible only in the worked example, not in §2.1's prose | no |
| I16 | 2.3 | `VKQ = C + Σ QKQ·P·(1−H)` with an `x`-driven cash floor | the formula is missing (D3); the inputs are all named | yes, if asset valuation is built |

**Two of these — I1 and I3 — bind on the simplest thing we could build.** Everything else
is either avoidable (use VSDC's published ratio; `OA = 0` by the rule) or belongs to a
component that is already blocked on data.

---

## 12. Register of DEFECTS in the published source

Recorded because they are properties of the gazetted text, not of our reading, and the next
person to fetch these documents will meet them again.

| # | Where | Defect | Severity |
|---|---|---|---|
| **D1** | Phụ lục 2 §1.2 table | **The scenario price formula omits `k`.** Printed as `Sk = S0 x (1 + tỷ lệ ký quỹ ban đầu/10)` in all 21 rows, while the same cell declares `−10 ≤ k ≤ 10` and the rows are labelled `S-10 … S+10`. Read literally, the 21-scenario grid is one point and §4.3's `Hp`/`Lp` are equal | **CRITICAL** — the risk margin is undefined without the fix |
| **D2** | Phụ lục 2 §1.3.c | **Announces the initial-margin-ratio formula and does not give one.** The heading is followed immediately by *"Trong đó:"*. Consequence: `n` is defined and never used | **CRITICAL** — the ratio cannot be derived |
| **D3** | QĐ 26 Điều 8.1 | **The margin-asset valuation formula is missing.** *"…được xác định theo công thức sau:"* → *"Trong đó:"*. All seven variables are glossed; the expression is absent | **HIGH** — this is the other side of the `assets < MR` test |
| **D4** | QĐ 26 Điều 7.3 | **Both conversion-factor expressions are missing.** Only the glossary (`CF`, `Lc`, `r`, `k`, `n`, `E`, `Dn`) survives | HIGH for GB futures (deferred) |
| **D5** | Phụ lục 2, several | Transcription noise: `ông thức` for `công thức` (L5); `offseting` for `offsetting` (L27); `Thiết lập nhóm tài sản cơ sởCăn cứ` missing a space (L28); `SPRt` vs `δSPRt` for one quantity (L80/L82); stray leading `M` in `Mrt2` (L84) | cosmetic |
| **D6** | Phụ lục 2 §1.1 vs §1.2 | The underlying's price on the calculation date is `S` in §1.1 and `S0` in §1.2. Same quantity, two names | low |
| **D7** | Phụ lục 2 §2.1 | The rule says *"không thấp hơn 0,9"* (**≥**); its own worked example says *"lớn hơn 0,9"* (**>**). We adopt ≥, the operative clause | low |
| **D8** | Phụ lục 2 §2.2.e vs §3.3 | ***"Biến động giá"* must mean a return in §2.2.e and an absolute price change in §3.3** — otherwise one formula is dimensionally wrong and the other is not comparable across underlyings. One phrase, two quantities | **HIGH** — silently picking one breaks the other |
| **D9** | Phụ lục 2 §3.2 vs §3.3 | `SMrate` is computed per expiry-month **pair**, then defined as a single pooled 90th percentile applied per **underlying**. The per-pair rates' fate is never stated | medium |
| **D10** | Phụ lục 2 §6.2 vs QĐ 26 Điều 22 | **The E+2 hole.** `Dm` applies on **E** and **E+1**; settlement is **E+3**; E+2 is an operational day under Điều 22.4 | medium (deferred) |
| **D11** | QĐ 26 Điều 24.1 vs Phụ lục 2 §4.2 | **Phụ lục 8 is cited for two unrelated subjects** — electronic documents, and the CTD method. Điều 30.4 cites Phụ lục 9, so the numbering runs to ≥9 and one reference is wrong | **HIGH** — a retrieval trap |
| **D12** | Phụ lục 2 §5.1 vs §5.2 | `MF` is *"cho một tháng đáo hạn"* in §5.1 and *"trên một hợp đồng"* in §5.2. Only per-contract balances `MM = P × MF` | medium |
| **D13** | QĐ 26 Điều 13 | **Two khoản numbered 3** (L519 and L534). And **khoản 3.b cross-refers to *"điểm a khoản 1 Điều này"*, but khoản 1 has no lettered points** — it is a single paragraph. The intended target is almost certainly điểm a **khoản 2** (the 09h30 checkpoint) | medium |

---

## 13. What this breaks in our code

**Not this document's to fix — recorded so the owner of those files has the citation.**
Concretely: `src/plutus/market/broker.py` (`BrokerTerms.margin_call_utilisation`,
`forced_close_utilisation`, `warning_utilisation`),
`src/plutus/market/session/deposit.py` (`margin_status`, and the `account_margin_requirement`
docstring), `src/plutus/market/margin.py` (`PROVENANCE`), and
`docs/reference/citable/vn-exchange-rulebook-2020-2026.md` (the "Warning thresholds" row).

### 13.1 The 80/90/100 margin ladder is misattributed for the post-KRX regime

`margin_status`'s docstring says:

> rulebook 6.3, Article 13 of the clearing rulebook, sets level 1 = 80%, level 2 = 90%,
> level 3 = 100% **on utilisation**

and the rulebook sources that to `QĐ 96 → QĐ 61 → QĐ 12 → QĐ 26`, Article 13.

**QĐ 26 Điều 13 has been read in full. It contains no percentages** (§2.4). The test is
binary: `margin_assets < MR`. The 80/90/100 ladder is in **Điều 29**, on **giới hạn vị
thế** — a **contract count against a position limit** (§2.5).

**For the post-KRX regime the margin ladder is definitively misattributed.** Not "unproven"
— the cited article was read and does not say it.

### 13.2 For the PRE-KRX regime it is **UNVERIFIED, not disproven**

State this precisely, because the two are not the same claim:

- **QĐ 61/QĐ-VSD and QĐ 12/QĐ-HĐTV have never been read.** The rulebook's own source note
  for that row says it was *"Confirmed on the LuatVietnam record of QĐ 61 Art. 13"* — a
  **database record**, not the article text — and corroborated by a broker guide.
- **The citation chain is broken at its final link.** The chain was offered as continuity:
  each instrument replaces the last, so Article 13 carries through. QĐ 26's Article 13 does
  **not** carry it, which removes the chain's endpoint and with it the argument that the
  earlier links must have said it.
- **That is not evidence the earlier links said something else.** QĐ 26 is a KRX-driven
  rewrite that changed the margin model's shape substantially (MR is no longer IM + VM; MR
  is now EOD rather than real-time). A ladder that existed under QĐ 61 and was **removed**
  by QĐ 26 is entirely consistent with everything read.

**So: the pre-KRX ladder's SOURCING has collapsed. Its CONTENT is untested.** Do not
restate it as wrong. Downgrade the rulebook row's confidence from `high` to `UNVERIFIED`
and change its source note to say the chain terminates at QĐ 26, which does not carry it.
**To close: read QĐ 61 Điều 13 and QĐ 12 Điều 13 as text.**

### 13.3 Two things that survive intact, and one that needs re-labelling

**Survives — the unit of assessment.** Điều 5.5 confirms the whole-account,
per-investor-trading-account portfolio unit (§2.2). `account_margin_requirement`'s
`TypeError` on a lone `Position` is right for the post-KRX regime too.

**Survives — VM is not additive to MR.** `margin.py`'s warning that the per-position
maintenance-ratio model has the wrong shape is, if anything, understated: post-KRX, `MR`
does not contain VM **at all**.

**Needs re-labelling — `BrokerTerms`' three fields.** They remain legitimate **broker
terms**: Điều 5.1.1.b lets a clearing member set the investor's requirement *"căn cứ"*
VSDC's ratio, so a member running tighter in-house monitoring is real. What is no longer
supportable is `PROVENANCE`'s claim that *"the ladder shape is VSDC-sourced"*. For the
post-KRX regime the VSDC-sourced shape is **binary**. The levels were always assumed; now
the shape is too.

---

## 14. Sources

**Primary, read in full for this document** (extracted plain text, `thuvienphapluat.vn`
HTML rendering, retrieved 2026-08-26):

- **QĐ 26/QĐ-HĐTV ngày 16/4/2025** — *Quy chế bù trừ và thanh toán giao dịch chứng khoán
  phái sinh tại VSDC*. Điều 1 → Điều 32, complete. Cited above as `qd26 L<n>`, `<n>` a line
  number in the extraction (1,167 lines).
  Articles load-bearing here: **5** (margin types), **6–9** (collateral, haircuts), **8**
  (valuation — formula missing, D3), **7** (deliverable bonds, conversion factor — formulas
  missing, D4), **13** (margin monitoring), **20** (P&L settlement), **22** (GB futures
  delivery), **23** (DSP/FSP), **27–29** (position limits and the 80/90/100 ladder).
- **Phụ lục 2** — *Phương pháp xác định các giá trị ký quỹ*. §§1–6 plus the scenario table,
  complete as to its numbered sections. Cited as `phuluc2 L<n>` (148 lines).

**Primary, NOT obtained and load-bearing:**

| Appendix | Needed for | Noted at |
|---|---|---|
| **Phụ lục 3** | collateral liquidity method; possibly §8.2's liquid/illiquid switch | qd26 L323–325 |
| **Phụ lục 6** | the DSP determination method | qd26 L747–748 |
| **Phụ lục 8** | CTD bond selection — **or** electronic documents; the citation is ambiguous (D11) | phuluc2 L109; qd26 L753–754 |

**Superseded instruments in the chain, none of them read:** QĐ 96/QĐ-VSD (2017-03-23),
QĐ 61/QĐ-VSD (2022-05-16), QĐ 12/QĐ-HĐTV (2023-08-10). See §13.2 — reading QĐ 61 Điều 13
and QĐ 12 Điều 13 is the single retrieval that would settle the pre-KRX ladder question.

**Corpus measurements** (this machine, 2026-08-26; every figure in §10 was measured, none
assumed):
`/Users/nadan/algotrade-research/dataset/hermes-parquet/` and
`/Users/nadan/algotrade-research/dataset/hermes-offline-market-data-pre-2023/`.

---

## 15. Verification log

**2026-08-26 — document created.** Both primary documents read end to end before any
drafting. Every formula in §§2–8 was transcribed from the extraction and quoted verbatim
in Vietnamese where a formula or a threshold is at stake, per house rule.

**Three things this document asserts that a reader should check hardest:**

1. **§3.2's reconstruction of `Sk`** (D1/I1). Four independent consistency checks support
   it and the literal text fails all four — but it is a reconstruction of gazetted text,
   which is the strongest claim in this document and the one most worth attacking.
2. **§10.5's correction of the brief.** `MM` needs bid/ask **prices**, which the tick
   archive has for VN30F at `depth = 1`; the empty **size** tables are a real gap but a
   different one. Verified by reading §5.2's formula (no quantity term appears) and by
   counting 920,699 `depth=1` VN30F bid rows in the first 40M lines of
   `quote_bidprice.csv`.
3. **§10.4's finding that no DSP series exists.** `quote_settlementprice` has **18 distinct
   dates** and up to **261 observations per symbol per day** — an intraday sample, not a
   daily settlement series. This is the blocker for `Sm`, and it is stated more strongly
   than "the data is thin" because the table is the wrong *shape*, not merely short.

**Deliberately not done:** no measurement is proposed anywhere in this document, per the
standing instruction and the retracted margin-incidence precedent. §10 states what the data
would support; it computes nothing about the market.

**Not modified:** `broker.py`, `deposit.py`, `margin.py`,
`docs/reference/citable/vn-exchange-rulebook-2020-2026.md`. §13 records what they now need, with citations, for
whoever owns them.
