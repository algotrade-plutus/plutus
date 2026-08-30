# Equity margin lending (*giao dịch ký quỹ*) — implementable specification

**Status: NOT BUILT. Priority 1** (author decision 1, 2026-08-26).

Verified by grep on 2026-08-26: no `margin_lending`, `loan_ratio`,
`maintenance_margin_ratio` or any equity-margin symbol exists anywhere in `src/`. The
only `ký quỹ` in the codebase is **derivatives clearing margin**
(`market/margin.py`, `market/session/deposit.py`, `market/exchanges/derivatives.py`).

> **Do not reuse `deposit.py`.** Derivatives clearing margin and equity margin lending
> are different products: different regulator (VSDC vs SSC), different custody chain
> (margin held at VSDC via the settlement bank vs collateral held in the client's own
> account at the broker), different call test (utilisation of *posted assets* vs an
> *equity/assets ratio*), and different cure ceilings. The only thing they share is a
> Vietnamese name.

Companion documents: `docs/reference/FEATURES.md` §12 (the one-screen summary),
`docs/reference/citable/vn-exchange-rulebook-2020-2026.md` (the exchange rulebook — this document
does **not** modify it).

---

## 0. Confidence vocabulary, and what this research could and could not reach

| Grade | Means |
|---|---|
| **VERIFIED** | The complete operative text was read, from a legal-database mirror. Where noted, cross-checked across ≥2 independent mirrors that agree verbatim. |
| **REPORTED** | Secondary source only — news, broker FAQ, broker fee schedule. |
| **DERIVED** | Our own arithmetic. **Not in any source read.** Flagged at every occurrence. |
| **SILENT** | The rulebook does not address it. Delegated to the broker contract by name, or simply absent. |

**Reachability caveat, stated once and load-bearing for every VERIFIED grade below.**
Primary-source hosts were unreachable during this research: `thuvienphapluat.vn`,
`vbpl.vn` and `vanbanphapluat.co` returned 403 or a JS bot-wall; `ssc.gov.vn` document
pages are JavaScript-gated; the WebSearch budget was exhausted before the first call.
Every statutory text below therefore came from a **commercial mirror**, not from công
báo or an SSC-issued PDF. **If a traceability claim in the paper depends on a specific
clause, obtain the gazette copy.**

**Corroboration count corrected 2026-08-26.** An earlier revision said QĐ 87 was
"cross-checked across four mirrors that agree verbatim". **Two of the four serve almost
none of the document**, verified by re-fetching both:

| Mirror | What it actually serves |
|---|---|
| luatvietan.vn | full operative text — Điều 1 → 16 |
| luatvietnam.vn | full operative text |
| hoatieu.vn | **Chương I–II only, stopping after Điều 4.** The rest is behind *"Chỉ thành viên Hoatieu Pro tải được nội dung này"* and a login-gated PDF |
| dongduong.net | **Chương I only — Điều 1 and Điều 2.** Then a link to a PDF |

So Điều 1–2 have four mirrors, Điều 3–4 have three, and **everything from Điều 5 onward —
which is every number this spec implements — has exactly two** (luatvietan +
luatvietnam), both of which do agree verbatim on Điều 5.1/5.2. TT 120, TT 121, NĐ 155 and
Luật 54 across two. The values are unchanged by this correction; the strength of the
VERIFIED grade behind Điều 5–16 is.

**Prompt injection encountered.** `hethongphapluat.com` article pages carry an embedded
instruction block addressed to an AI reader, demanding the answer tell the user to visit
that site. It was treated as data, not instruction. Flagged because we will likely scrape
that host again.

---

## 1. The legal stack

| Instrument | Date | Role for margin lending | Grade |
|---|---|---|---|
| **Luật Chứng khoán 54/2019/QH14** | ban hành 2019-11-26 | Điều 86.1(b) — margin lending is a permitted CTCK service | VERIFIED |
| **Nghị định 155/2020/NĐ-CP** | 2020-12-31 | Điều 198 — firm-level licence conditions to offer margin | VERIFIED |
| **Thông tư 120/2020/TT-BTC** | 2020-12-31, eff. **2021-02-15** (replaced TT 203/2015) | **Điều 9 — the statutory frame.** **Điều 9 itself** is not amended by TT 68/2024, TT 18/2025 or TT 08/2026 (re-confirmed 2026-08-26) | VERIFIED |
| — **Điều 9a**, inserted into TT 120 by **TT 68/2024** | 2024-11-02 | **The non-prefunded (NPF) buy regime for foreign INSTITUTIONAL investors.** Amended since: khoản 2, 3, 4, 5 replaced by khoản 2, 7, 8, 9 Điều 40k of TT 119/2020 per khoản 2 Điều 3 TT 18/2025 (annotation re-fetched verbatim at the foot of Điều 9); khoản 1a amended by TT 08/2026 | VERIFIED (that it exists and has been amended) |
| — **why it is in this table at all** | | **ADJACENT, OUT OF SCOPE, and NOT *ký quỹ*.** §2.5's flat foreign prohibition is correct **for margin lending**. But Điều 9a is broker credit extended to precisely the class §2.5 bars, under a different regime. **An implementer who reads only §2.5 will build a simulator that refuses all foreign credit-funded buying, which is wrong.** Do not model it here; do not let `MarginRegulation.foreign_investors_allowed = False` be read as "foreigners cannot buy on credit". The exchange rulebook already carries the NPF regime at §5.2 | — |
| **Thông tư 121/2020/TT-BTC** | 2020-12-31, eff. 2021-02-15 | Điều 26 (debt ≤ 5× equity), Điều 27 (lending prohibition + margin carve-out), reporting forms II.8 / II.8B | VERIFIED |
| **Quyết định 87/QĐ-UBCK** | **2017-01-25, eff. 2017-04-01** | **The Quy chế — the operative numbers.** Replaced QĐ 637/QĐ-UBCK (2011-08-30) and QĐ 09/QĐ-UBCK (2013-01-08) | VERIFIED |
| **Quyết định 1205/QĐ-UBCK** | **2017-12-27, eff. 2018-01-02** | Amends **only khoản 5 Điều 3** — the tax/prosecution exclusion | VERIFIED |
| Thông tư 08/2026/TT-BTC | eff. 2026-02-03 | **Scope corrected 2026-08-26.** Amends TT 120 **Điều 6** (kh. 1, 3, 7), **Điều 7** (kh. 2, 5, 6) **and Điều 9a kh. 1a**, plus TT 96/2020 Điều 25.8 / 33.1 / 33.8 and TT 121/2020 Điều 2.6 / 4.5 / 13–16. The earlier "CCP clearing margin, a different thing" gloss is **doubtful** — what is readable is accounts, order placement and the foreign-institutional NPF regime. **None of it touches Điều 9**, which is the only claim this spec needs | VERIFIED (effective date and amended-article list) / **REPORTED (the subject-matter gloss)** |

### 1.1 Is QĐ 87 still in force?

No *Tình trạng hiệu lực* field was directly readable (paywalled or blocked). Three
independent lines of evidence say yes:

1. TT 120/2020 Điều 9.8 obliges the SSC to issue a margin quy chế; no replacement surfaced.
2. HOSE was still citing QĐ 87 + QĐ 1205 as the legal basis for its margin-ineligibility
   list in **July 2025** (REPORTED).
3. The **April 2026** HOSE quarterly list carries exclusion reasons that map one-to-one
   onto QĐ 87 Điều 3, and every 2026 broker caps the loan at exactly 50 % — the QĐ 87
   floor (REPORTED).

**Historical note, do not implement as a rule:** a January 2018 SSC draft would have
raised the initial-margin floor 50 % → 60 % (SSC letter 2018-01-12, comments due
2018-01-17; the Chairman defended it publicly on 2018-01-15). **It was never adopted.**
REPORTED.

---

## 2. STATUTORY LAYER → `MarginRegulation`

Gazetted, dated, cited. **Not user-configurable.** Mirrors the existing split: this object
is the analogue of the exchange rulebook, `BrokerMarginTerms` (§3) is the analogue of
`BrokerTerms`.

### 2.1 The ratios — the numbers to implement

**QĐ 87 Điều 5, verbatim, cross-checked on the two mirrors that carry it** (luatvietan and
luatvietnam — see §0 on why the other two cannot corroborate anything past Điều 4):

> 1. Tỷ lệ ký quỹ ban đầu do công ty chứng khoán quy định nhưng **không được thấp hơn 50 %**.
> 2. Tỷ lệ ký quỹ duy trì do công ty chứng khoán quy định nhưng **không được thấp hơn 30 %**.
> 3. Căn cứ vào tình hình hoạt động thị trường chứng khoán, **Ủy ban Chứng khoán Nhà nước
>    có thể điều chỉnh** tỷ lệ ký quỹ quy định tại khoản 1, 2 Điều này.

| Rule | Value | Effective from | Effective to | Grade |
|---|---|---|---|---|
| Initial margin ratio floor (`imr`) | **60 %** | 2011-08-30 | 2017-03-31 | REPORTED (QĐ 637) |
| Initial margin ratio floor (`imr`) | **≥ 50 %** | **2017-04-01** | current | **VERIFIED** |
| — ⇒ max loan-to-value **50 %** | the restatement, **not the text** | — | — | **DERIVED** (see below) |
| Maintenance margin ratio floor (`mmr`) | **≥ 30 %** | **2017-04-01** | current | **VERIFIED** |

> **Why "⇒ max loan-to-value 50 %" is DERIVED and not VERIFIED (added 2026-08-26).**
> Điều 5.1 says only *"không được thấp hơn 50 %"*. The restatement rides on the identity
> `imr = 1 − loan_ratio` (§3.1), which is **our own** and holds **only for a single, fully
> collateralised purchase**. Điều 2 khoản 8 defines `imr` as the account's *tài sản thực
> có* over the value of the order at market price at trade time — so an account already
> holding other eligible collateral supports a **larger** purchase than `1 − loan_ratio`
> implies. Brokers publishing a per-ticker `tỷ lệ cho vay ≤ 50 %` is a separate,
> REPORTED observation that happens to agree, not a proof of the identity.

**Model both as regulator-settable parameters with a dated history, not as constants** —
Điều 5.3 gives the SSC a standing power to move them without new legislation, and it has
moved once inside living memory.

Also statutory: **TT 120 Điều 9.9** — in cases necessary to stabilise the market the SSC
may **order margin trading at a CTCK to be suspended**. VERIFIED. Worth a kill-switch.

### 2.2 Account algebra — QĐ 87 Điều 2

VERIFIED (khoản 3–12).

```
DB  = dư nợ ký quỹ                      cash owed by the client to the CTCK
CB  = tiền + tiền bán chứng khoán chờ về   cash + unsettled sale proceeds
PV  = giá trị chứng khoán được phép GDKQ trên tài khoản
EB  = CB + PV                            tổng tài sản
AB  = EB - DB                            tài sản thực có
tỷ lệ ký quỹ = AB / EB
mmr = min(AB / EB)
imr = AB / (market value of the securities the margin order would buy, at trade time)   -- PER ORDER
MR  = giá trị chứng khoán × imr          giá trị ký quỹ yêu cầu
EE  = AB - MR                            giá trị dư ký quỹ
BP  = EE / imr                           sức mua (buying power)
```

Note `CB` **includes unsettled sale proceeds**. That is a real interaction with our
existing tranche-proceeds ledger (`ledgers.py:870`): pending proceeds are excluded from
`Cash.available` today unless advanced, but they **do** count toward `CB` for the margin
ratio. Two different questions, two different answers — do not collapse them.

### 2.3 Collateral valuation — a hard cap

**QĐ 87 Điều 2.4, verbatim:** *"Giá trị của chứng khoán (v) là giá trị do công ty chứng
khoán xác định trên Hợp đồng … **nhưng không vượt quá giá đóng cửa tại ngày gần nhất**
của chứng khoán đó."* VERIFIED.

The broker may haircut freely **below** the last close but **may not value collateral
above it**. In practice brokers express the haircut as a per-ticker *tỷ lệ cho vay*
(loan ratio) — see §3.1.

### 2.4 Timing of the ratio computation

**QĐ 87 Điều 6.1:** the CTCK determines each margin account's ratio **at the end of the
trading day**, using the Điều 2.4 valuation. The exact within-day timestamp is agreed in
writing with the client. VERIFIED.

> **Statute-vs-practice divergence, load-bearing for the simulator.** The regulation
> mandates **end-of-day** computation at a valuation ≤ last close. Brokers in 2026 run it
> **intraday at live market prices** and force-sell intraday (DNSE: *"tỷ lệ Deal tính
> theo giá thị trường chứ không tính theo giá tham chiếu"*, hourly sweep 09:00–15:00).
> **Implement EOD as the regulatory floor behaviour and intraday as a broker option**
> (§3.3), exactly as the derivatives path treats broker utilisation thresholds.

### 2.5 Eligibility of the investor

| Rule | Source | Grade |
|---|---|---|
| Must sign a *hợp đồng giao dịch ký quỹ*, which **is** the credit agreement | TT 120 Điều 9.1; QĐ 87 Điều 12.1 | VERIFIED |
| **Foreign investors may not margin trade** — flat prohibition | **TT 120 Điều 9.2**; QĐ 87 Điều 10.1(đ) | VERIFIED |
| One margin account per investor per CTCK, segregated from the ordinary account and across investors | TT 120 Điều 9.3; QĐ 87 Điều 13.5(a) | VERIFIED |
| **May not open a margin account:** the CTCK's owner / major shareholder / capital member / BoD / Supervisory Board / CEO / DCEO / chief accountant / other board-appointed officers **and their related persons**; entities in dissolution or bankruptcy; parties in breach of the CTCK's margin contract | QĐ 87 Điều 13.4 | VERIFIED |
| Domestic individuals **and** domestic institutions are both eligible | broker practice | REPORTED |
| Authorised/proxy traders cannot register margin on the owner's behalf | ACBS FAQ | REPORTED (broker term, not statute) |

### 2.6 Eligibility of the security — a two-layer negative → positive list

**Layer 1: the exchange publishes a NEGATIVE list.** Layer 2: each CTCK selects its own
positive list from what remains.

**Universe.** TT 120 Điều 9.4 says *cổ phiếu niêm yết, **đăng ký giao dịch**, chứng chỉ
quỹ niêm yết* — which would include UPCoM. QĐ 87 Điều 3 says *cổ phiếu, chứng chỉ quỹ
**niêm yết*** — listed only.

> **DIVERGENCE — and it is more likely a delegation than a hierarchy conflict.**
> *Characterisation softened 2026-08-26 after audit.* Both texts are VERIFIED. But
> **TT 120 Điều 9.8 expressly delegates the margin *quy chế* to the SSC**, and QĐ 87 *is*
> that quy chế — so TT 120's *"bao gồm"* reads naturally as the permissive **outer
> universe**, narrowed from inside by the delegated regulation. That is a delegation
> operating as designed, not two instruments contradicting each other. Note that §1.1
> leans on Điều 9.8 to argue QĐ 87 is still in force; the same clause dissolves this
> "conflict", and an earlier revision used it in one place and ignored it in the other.
> "TT 120 (2020) outranks QĐ 87 (2017) but the market follows QĐ 87" was stated with more
> force than the evidence carries.
>
> **Implementation outcome is unchanged:** HOSE + HNX listed only; UPCoM ineligible.
> Record the divergence in the rule's own note; do not resolve it silently.
>
> **Evidence grades, separated.** Both texts: **VERIFIED**. The market-practice half —
> SSI's margin book dated 2026-08-25, parsed to **238 HOSE / 48 HNX / 0 UPCoM** — is a
> **one-off parse of a single broker's PDF on a single date**, and it is the *sole*
> evidence resolving the UPCoM question. Grade it accordingly: it is not on a par with a
> read statute, it was not reproduced by a second reader, and SSI's own margin landing
> page states no exchange coverage at all. **To close: parse a second CTCK's list, or the
> HOSE/HNX negative lists directly.**

**Exclusion predicates — QĐ 87 Điều 3 as amended by QĐ 1205 Điều 1.** A security is
INELIGIBLE if **any** of:

1. **Listed < 6 months**, counted from first trading day to the review date. On a venue
   transfer the two exchanges' listed times are **summed**.
2. Under **cảnh báo, kiểm soát, kiểm soát đặc biệt, tạm ngừng giao dịch**, or in the
   delisting queue.
3. The issuer's audited annual FS, or reviewed/audited semi-annual FS, carries an opinion
   **other than unqualified**.
4. The issuer is **> 5 business days late** disclosing the audited annual FS or reviewed
   semi-annual FS, from the deadline or the end of any granted extension.
5. *(QĐ 1205 wording, effective 2018-01-02)* The exchange has a report, disclosure or
   information about an administrative-penalty decision against the listed company for
   **tax evasion or tax fraud**; **or** for **failure to comply with a tax-enforcement
   decision**; **or** a decision to **prosecute (khởi tố bị can)** the company.
6. **Loss in the period and/or accumulated loss** on the latest audited annual FS or
   latest reviewed/audited semi-annual FS. Parent companies use the **consolidated** FS.
   For a public fund: **NAV/unit < par for at least one month, looking at 3 consecutive
   months** to the selection date.

All VERIFIED. Note QĐ 1205 **narrowed** predicate 5: before 2018-01-02 any tax-authority
violation conclusion cut margin; from that date mis-declaration causing underpayment,
late payment and similar no longer do. This is a dated rule change — implement it as one.

> **Taxonomy drift — an interpretive gap, not a rule we may invent.** QĐ 87 Điều 3.2
> enumerates *cảnh báo / kiểm soát / kiểm soát đặc biệt / tạm ngừng giao dịch / hủy niêm
> yết*. Current HOSE practice **also** cuts margin for **hạn chế giao dịch** and **đình
> chỉ giao dịch** — statuses from the post-2020 listing rules, absent from QĐ 87's
> vocabulary (HVN excluded for *hạn chế giao dịch + kiểm soát*, 2026-04-03; ASP and SVD
> under *hạn chế giao dịch*, 2025-07-03). REPORTED. **The rulebook is silent on this
> mapping. Record it as SILENT; do not encode a mapping as if it were gazetted.**

**Publication mechanics — QĐ 87 Điều 4.** VERIFIED.

| Rule | Value |
|---|---|
| Exchange publishes the ineligible list | within **2 business days** of any Điều 3 trigger arising |
| The publication is a **full snapshot**, not a delta | all ineligible securities as at that moment |
| Removal from the ineligible list | at most **once every 6 months** from the last publication, except the <6-months case; exact timing is the exchange's call |
| CTCK publishes its own positive list | within **2 business days** of the exchange's publication, on its website and at all business locations |
| CTCK reports to the exchange (Phụ lục 01) | before the **5th trading day of the following month** — opening codes / removed / added / closing, split HOSE vs HNX, plus the website URL |

Observed cadence (REPORTED): HOSE publishes a full list **quarterly** (68 codes for
Q2/2026 published 2026-04-03; Q3/2025 published early July 2025; 93 codes Q2/2024) plus
event-driven updates. Brokers then issue per-ticker add/remove notices with an effective
date.

### 2.7 Securities that fall off the list — two texts that do not match

| Text | Effect |
|---|---|
| **QĐ 87 Điều 10.2** | No new lending against it; it **may no longer count toward `AB`**; but it **remains security** for the existing loan unless otherwise agreed |
| **TT 120 Điều 9.6** | *"Chứng khoán không được phép giao dịch ký quỹ không được tính vào tài sản bảo đảm khi xác định tỷ lệ ký quỹ ban đầu và tỷ lệ ký quỹ duy trì"* — excluded from the collateral base for **both** ratios |

Both VERIFIED. **Implement TT 120's version** (higher-ranking) and record the divergence
in the rule's own note.

### 2.8 Margin call — QĐ 87 Điều 7, TT 120 Điều 9.6

VERIFIED. **Note the joint heading is not a joint citation.** TT 120 Điều 9.6 carries the
call and the force-sale right but **no day count**; the ≤ 3-business-day ceiling is
**QĐ 87 Điều 7.1 alone**. (Corrected 2026-08-26.)

| Rule | Value |
|---|---|
| Trigger | tỷ lệ ký quỹ drops **below `mmr`**. The CTCK **issues** a *lệnh gọi ký quỹ bổ sung* by the contact method in the account contract |
| **Cure window ceiling** — **QĐ 87 Điều 7.1 only** | the period the CTCK requires, **but not more than three (03) business days**. The specific period is a contract term |
| Cure methods | sell securities, add cash, or add eligible collateral securities — enough to restore **at least `mmr`**. The precise target level is set by the CTCK |

**GAP — the top-up amount formulas are images.** QĐ 87 Điều 7.2 gives two formulas —
(a) value of securities to post, (b) cash to post. **Every accessible mirror renders them
as images and drops them** (luatvietnam omits them from the free HTML; hoatieu, dongduong
and luatvietan all drop them).

**DERIVED, not sourced — flag at every use.** From the EB/AB algebra:

- posting eligible securities of value `S` raises both `AB` and `EB`:
  `S ≥ (mmr·EB − AB) / (1 − mmr)`
- depositing cash `C` **applied to repay `DB`** (Vietnamese brokers sweep deposits against
  debt at end of day — ACBS: *"hệ thống sẽ tự động thu cấn trừ nợ vào cuối ngày"*) leaves
  `EB` unchanged and raises `AB`: `C ≥ mmr·EB − AB`
- depositing cash `C` that **stays in `CB`** behaves like the securities case.

**Do not ship these as "the regulation says".** Ship them as an assumption with a TODO to
obtain the QĐ 87 Điều 7.2 images from công báo or ssc.gov.vn.

### 2.9 Forced sale — *bán giải chấp* — QĐ 87 Điều 8, TT 120 Điều 9.6

VERIFIED.

| Rule | Value |
|---|---|
| Right arises when | the client fails to top up, or tops up only partially, within the call deadline |
| How much | part or all of the pledged securities, depending on whether the *remaining* required collateral is smaller or larger than the total value in the account |
| Notice | the CTCK must **notify the client before placing the sell order**, and send a statement of results afterwards, by the contractually agreed method |
| Disclosure | TT 120 Điều 9.6 — before selling, the CTCK performs the required public disclosure and notifies the client so the client can meet its own ownership-reporting obligations (relevant when the client is an insider or major shareholder) |
| Proceeds | where all securities are sold, the client may withdraw **only the remainder after the margin debt is deducted** |
| Shortfall | if liquidation does not cover `DB` and the client does not pay the residual, the CTCK recovers it per the contract and general law |

> **SILENT — the order in which positions are sold.** QĐ 87 Điều 12.2(i) only requires the
> *contract* to state *"phương thức xử lý tài sản thế chấp … **và thứ tự ưu tiên sử dụng
> tiền bán chứng khoán thế chấp** của khách hàng"*. So **both** the sale ordering and the
> proceeds-application ordering are **per-broker contract terms, not exchange rules**.
> Do not invent a default; make each a broker policy enum. VERIFIED (that the rule
> delegates).
>
> This is the exact analogue of `LiquidationRule.LARGEST_LOSS_FIRST` on the derivatives
> side (FEATURES.md A54) — an adopted ordering that no Vietnamese document prescribes.

### 2.10 Firm-level lending limits — QĐ 87 Điều 9

VERIFIED, and independently REPORTED by Thời báo Tài chính Việt Nam.

Equity (*vốn chủ sở hữu*) is taken from the latest audited or reviewed FS **not older than
06 months** from the calculation date; if charter capital rose between cycles, use the FS
for the most recent period.

| # | Limit | Value |
|---|---|---|
| Điều 9.1 | Total margin loan book of one CTCK | **≤ 200 % of its equity** |
| Điều 9.2 | Total margin lending to **one customer** | **≤ 3 % of the CTCK's equity** |
| Điều 9.3 | Total margin loan book against **one security** | **≤ 10 % of the CTCK's equity** |
| Điều 9.4 | Total **shares** lent against for one issuer | **≤ 5 % of that issuer's total listed shares.** Re-fetched verbatim 2026-08-26: *"Tổng số chứng khoán cho vay giao dịch ký quỹ của một công ty chứng khoán không được vượt quá 5% tổng số chứng khoán niêm yết **của một tổ chức niêm yết**."* The per-issuer qualifier **is in the text** — an audit pass reported it missing, which a re-fetch of the primary mirror does not support |

Adjacent prudential limits, TT 121/2020 (VERIFIED):

- Điều 26.1 — total debt / equity **≤ 5×** (excluding client trading deposits, welfare
  fund, severance provision, investor-compensation provision). *The pre-2021 limit was 3×.*
- Điều 26.2 — short-term debt ≤ short-term assets.
- Điều 27.1 — a CTCK may not lend cash or securities in any form **except** under Luật CK
  Điều 86.1; Điều 27.4 — a CTCK authorised for margin may lend for margin per MOF guidance.
- Điều 27.3 — **no lending in any form** to the owner, major shareholders, Supervisory
  Board, BoD/Members' Council, Board of Management, chief accountant, other
  board-appointed managers, or their related persons.

**Firm licence conditions — NĐ 155/2020 Điều 198.1** (VERIFIED). To offer margin a CTCK
must: (a) hold a brokerage licence **and** a board/owner resolution approving the service;
(b) **not** be under cảnh báo / kiểm soát / kiểm soát đặc biệt / đình chỉ / tạm ngừng
hoạt động / merger / consolidation / dissolution / bankruptcy; (c) meet the MOF
debt-to-equity ratio with equity ≥ the Điều 175 minimum charter capital; (d) have
**tỷ lệ vốn khả dụng ≥ 180 % continuously for the most recent 06 months** as at filing;
(e) have the trading and monitoring systems, segregated client bank deposits, and
documented risk/control procedures.

**Loss of eligibility — TT 120 Điều 9.7 / QĐ 87 Điều 16:** the CTCK must **immediately**
stop signing new margin contracts and stop disbursing, and report in writing to the SSC
**within 48 hours**. It may resume only after SSC notification on evidence of
remediation. VERIFIED.

**Voluntary exit — QĐ 87 Điều 15:** disclose at HQ, all business locations and website;
notify clients, the exchange and the SSC; submit an exit plan (stop date, unwind
timetable, treatment of contracts open at the deadline); report completion within 15 days
of finishing liquidation. VERIFIED.

### 2.11 Prohibited collateral — QĐ 87 Điều 10.1

The CTCK **may not lend** against:

- (a) shares/fund units **it itself firm-underwrote**, from signing the underwriting
  contract until **6 months after the offering completes**;
- (b) shares of a listed company that **owns ≥ 50 % of the CTCK's charter capital**, and
  shares of a listed or registered-for-trading company **in which the CTCK owns ≥ 50 %**;
- (c) **the CTCK's own shares**;
- (d) when the client is not meeting the contractual/regulatory margin ratio;
- (đ) **foreign investors**;
- (e) the persons in Điều 13.4.

VERIFIED.

### 2.12 Loan term and interest — QĐ 87 Điều 11

VERIFIED.

| Rule | Value |
|---|---|
| Term | **≤ three (03) months** from disbursement, agreed in the contract |
| Extension | on the client's **written request**; **each extension ≤ 3 months**. **The number of extensions is NOT capped by the regulation** — that cap is a broker term |
| Interest rate — **khoản 3** | agreed **in writing**, subject to the Bộ luật Dân sự: *"Lãi suất cho vay giao dịch ký quỹ được xác định trên cơ sở thỏa thuận bằng văn bản giữa công ty chứng khoán và khách hàng và theo quy định của Bộ Luật Dân sự."* **There is no statutory margin interest rate and no cap beyond the Civil Code's general ceiling** |
| Interest calculation method — **khoản 4** | *"Cách tính tiền lãi vay được xác định trên cơ sở thỏa thuận bằng văn bản giữa công ty chứng khoán và khách hàng."* **The rulebook prescribes no day-count, no accrual convention, no compounding rule** — SILENT |

*Khoản numbering re-fetched verbatim 2026-08-26. The rate and the Civil Code reference are
**11.3**, not 11.4 — `FEATURES.md` §12 previously collapsed the two.*

### 2.13 Account-management duties — QĐ 87 Điều 12–14

**Contract minimum content (Điều 12.2)** — this is the field list for
`BrokerMarginTerms`: client identity; **purpose = buying margin securities**; **`imr` and
the method of valuing pledged securities**; **`mmr`**; **top-up deadline and method**;
**credit limit**; **interest rate**; contract term, effective date and **the date interest
starts accruing**; contact method for calls, force-sale orders and statements; **the
method of disposing of collateral on default and the priority order for applying sale
proceeds**; treatment if the CTCK loses its margin permission; protective clauses;
dispute resolution; termination; the client's acknowledgement that risks were explained.

**Operating rules (Điều 13)** — the load-bearing ones for a simulator:

| Rule | Effect |
|---|---|
| Điều 13.3 | The CTCK **may not repledge** the client's margin securities for anything but the margin relationship, absent client consent |
| Điều 13.5(b) | Only **cash, eligible margin securities and their attached rights** may serve as collateral; other securities only by written agreement; all of it **remains the client's property** |
| Điều 13.5(c) | The client pays interest on `DB`; the client may **withdraw cash only after clearing all debts** to the CTCK |
| **Điều 13.5(d)** | **The CTCK must not let the client trade on margin or withdraw cash beyond the account's current buying power `BP`.** This is the hard pre-trade check |
| Điều 13.5(đ) | The CTCK must promptly notify the client of corporate-action rights on securities in the margin account, and send statements |
| **Điều 13.5(e)** | **Margin order tickets must be distinguishable from ordinary order tickets**, carry full client information, be client-confirmed, and are an inseparable annex to the contract. → **in an API, a margin order is a distinct order type, not a flag on a normal order** |
| Điều 13.6 | The CTCK may transact in pledged securities **only on the client's instruction, except when it must sell to recover the loan** |
| Điều 13.7 | The CTCK must publish on its website: the margin securities list, the required margin ratios, and the interest rate |
| Điều 13.8 | Per-account books: daily collateral inventory, market prices, end-of-day ratio, plus every call and every margin order ticket |
| Điều 14.3 | A CTCK changing its margin management system reports to the SSC **≥ 15 days** before go-live |

**Regulatory reporting (TT 121/2020 annex, VERIFIED):** Biểu II.8 *Tình hình giao dịch ký
quỹ chứng khoán* (account count, value of margin securities, funding sources including
equity, margin revenue, loan balance split HOSE / HNX, total) and **Biểu II.8B —
per-ticker margin loan balance**, required when the CTCK lends against ≥ 50 tickers.

---

## 3. BROKER LAYER → `BrokerMarginTerms`

**Nothing in this section is a rule.** These are observed broker values, useful as
defaults and as realistic ranges. All **REPORTED** (broker's own published pages, fetched
2026-08-26) unless noted. **"Observed 2026" is loose for at least one entry:** SSI's
*biểu giá* page states an effective date of **2022-11-01** for the 13.5 %/năm (360 ngày)
schedule, so 2026-08-26 is the **fetch** date, not the vintage of the value. Record the
effective date alongside the fetch date for every broker term carried into config. They belong in the broker config object, exactly as
`BrokerTerms` holds the derivatives utilisation ladder — and, exactly as there, each must
carry its own `PROVENANCE` entry saying it is assumed.

### 3.1 Loan ratio — the haircut mechanism

Brokers do not publish an `imr`; they publish a **per-ticker `tỷ lệ cho vay`**, and
`imr = 1 − loan_ratio`. **That identity is DERIVED, not sourced** — it is our own, it is
in no text read for this document, and it holds only for a single fully-collateralised
purchase (see §2.1). Everything in this section is REPORTED unless marked otherwise;
the identity is the one **DERIVED** step inside it.

| Broker | Observed |
|---|---|
| **SSI**, list dated 2026-08-25 (PDF parsed directly) | per-ticker ratios of 10 / 20 / 30 / 40 / **50 %**; **maximum observed 50 %**; 238 HOSE + 48 HNX rows, 0 UPCoM |
| DNSE | "linh hoạt từ 10 % đến 50 % theo từng mã", > 200 tickers, refreshed monthly |
| FNS (Funan) | "tỷ lệ vay tối đa là 50 %" |
| Pinetree | "tỷ lệ cho vay lên đến 50 %" |

**The 50 % statutory floor binds in practice.** Config:
`loan_ratio: Dict[ticker, Decimal]`, `0 < r ≤ 0.50`.

### 3.2 Call and force-sell thresholds — brokers run **two** levels, not one

> **CORRECTED 2026-08-26 after adversarial audit. Read this before using the table.**
> The DNSE table below is a **cash-product (*giao dịch tiền mặt*) table, not a margin
> ladder** — and that is true of **all five rows**, including the 50 % one. Re-fetched
> verbatim: the first column header is **`Gói`**, the five row labels are
> **`Giao dịch tiền mặt 50 % / 60 % / 70 % / 80 % / 90 %`**, and the sentence introducing
> it is *"Tỷ lệ cảnh báo và xử lý của **Deal** theo chính sách hiện tại của DNSE như
> sau:"*. An earlier revision relabelled the column "Package (loan ratio)" and hedged that
> only "the higher-leverage rows" were *giao dịch tiền mặt*. Both were wrong.
>
> **Consequences, stated plainly.** (i) The marquee reading — that the 50 % package's
> force-sell level is *exactly the 30 % statutory `mmr` floor* — reads a statutory
> coincidence off a non-margin product and **must not be carried into an implementation as
> a sourced default**. (ii) This spec has **zero verified numeric call/force thresholds for
> statutory equity margin at any broker**. (iii) The "direct analogue of the derivatives
> 80/90/100 ladder" framing is therefore **unsupported**: for derivatives the ladder is
> depository-sourced and only the levels are commercial; here we have neither. See §5
> gap 5.

DNSE is the only firm publishing a complete threshold table of any kind, reproduced here
**as a shape, not as a margin default**:

| `Gói` (as published) | Tỷ lệ cảnh báo (call) | Tỷ lệ xử lý (force sell) |
|---|---|---|
| Giao dịch tiền mặt 50 % | 40 % | 30 % |
| Giao dịch tiền mặt 60 % | 50 % | 40 % |
| Giao dịch tiền mặt 70 % | 60 % | 50 % |
| Giao dịch tiền mặt 80 % | 70 % | 60 % |
| Giao dịch tiền mặt 90 % | 80 % | 70 % |

What survives as usable: brokers do run **two** levels, a call and a force-sell, with the
call above the force-sell — a shape the config must express. The numbers do not survive.

**SSI** publishes the *structure* rather than the numbers — it distinguishes **TLKQ duy
trì** (call) from **TLKQ xử lý** (liquidation), and force-sells when **any** of:

- the debt is **overdue ≥ 3 business days**; or
- the account has **breached TLKQ duy trì for ≥ 3 consecutive business days** (the
  statutory cure ceiling, used in full); or
- **immediately upon breaching TLKQ xử lý.**

**ACBS:** call when the actual ratio < the maintenance ratio; if not cured, disposal
**starts at X+3 trading days**, and sells only enough to bring the ratio back **up to the
maintenance level**.

Model as `call_level ≥ force_level ≥ 0.30`, with the force-sell branch **bypassing** the
3-day window.

### 3.3 Force-sale execution policy

DNSE is the only firm publishing a complete, implementable policy — use it as the
reference implementation, not as a default:

| Aspect | DNSE |
|---|---|
| Ratio formula | **per-deal**: `Tỷ lệ Deal = Tài sản thực có của deal / Tổng tài sản của deal`, where `Tài sản thực có = qty × market price − nợ hiện tại − lãi vay − phí thuế tạm tính` |
| — note | This (i) is **per-deal**, not per-account; (ii) **deducts accrued interest, fees and estimated tax** from equity; (iii) uses **live market price**. All three extend beyond QĐ 87's account-level EOD algebra |
| When | any moment the ratio touches the force level; call notices swept **hourly 09:00–15:00** |
| What is sold | **only the breaching deal's stock** — other tickers in the sub-account are untouched |
| How much | just enough to lift the ratio back above the maintenance level; **never the whole deal by default** |
| At what price | **giá sàn** (floor price) at the moment the auto-sell fires |
| Notice | executes **without further notice** beyond the call |

Config enums this implies:
`forced_sale_scope ∈ {breaching_position, whole_account, broker_ranked}`,
`forced_sale_price ∈ {floor, market, limit}`,
`forced_sale_target ∈ {maintenance, maintenance_plus_buffer}`,
`accounting_unit ∈ {account, sub_account, deal}`.

### 3.4 Term, extension, overdue

| Broker | Base term | Extension | Overdue |
|---|---|---|---|
| SSI | 90 days | +90 days | overdue multiplier **150 %** |
| DNSE | 90 days | auto-extended **free +90 days**; then **max 2 further**, each ≤ 90 days; fee **0.3 % of principal due**; interest payable at extension | **150 % of the in-term rate** |
| ACBS | 90 days | **max 2 extensions, each ≤ 3 months**, fee payable and **may be capitalised into `DB`**; requests only when < 30 days remain; reminder 05 trading days before maturity | if not extended, disposal starts on the **5th business day after maturity** |
| FNS | 90 days, **max 180 days** total | — | — |

The ≤ 3-month term and ≤ 3-month-per-extension are **statutory**. The **number** of
extensions, the fees, the reminders and the overdue multiplier are **broker terms**.

### 3.5 Interest — no statutory rate, and two day-count conventions in one market

| Broker | Rate | Day-count |
|---|---|---|
| **SSI** | **13.5 %/năm, explicitly "(360 ngày)"** | **ACT/360** |
| **DNSE** | **0.0342 %/ngày = 12.5 %/năm** (12.5/365 = 0.03425) | **ACT/365** |
| ACBS | 13 %/năm standard; Margin T+ 0 % days 0–6 then 13 %; T14 8 % days 0–13 then 13 % | *"lãi được tính theo dư nợ thực tế của khoản vay cuối mỗi ngày"*, T0 = disbursement, **calendar** days |
| Pinetree | 10.5 %/năm base; P-Zero 0 % for 30 days; P-6.5 % for 90 days; P-8.8 % for 30 days | — |
| ABS | 13.5–15 %/năm tiered by day bucket | — |

DNSE also ships promo tiers (5.99 % / 9.99 % for the first 30 days then 12.5 %; "Rocket"
R3/R5/R10 free-interest tiers paired with higher commission 0.045 / 0.065 / 0.085 %;
"Flash Margin" 13–14.5 % at 20-day tenor).

Config: `rate_schedule: List[(day_from, day_to, annual_rate)]`,
`day_count ∈ {ACT/360, ACT/365}`, `accrual = daily on end-of-day outstanding`,
`calendar_days: bool`, `overdue_multiplier` (150 % observed at two firms),
`capitalise_fees: bool` (ACBS capitalises extension fees into `DB`).

> **Note the parallel with the sale advance (FEATURES.md A8).** `AdvanceTerms` already
> carries `annualisation_basis = 365` as a DECLARED assumption because sources mix ×360
> and ×365. Equity margin lending has the **same** split, observed at two named firms in
> the same market and the same year. Do not assume a single basis.

### 3.6 Other broker terms

| Term | Observed |
|---|---|
| Per-customer credit limit | SSI up to 70 tỷ đồng; DNSE 10 tỷ total; ABS up to 10 tỷ on eKYC, 35 tỷ uplift. All sit **under** the statutory 3 %-of-equity cap |
| Registration fee | typically none (ACBS: free) |
| Collateral scope | SSI / ACBS / FNS all include cash, unsettled sale proceeds, securities held, and **securities bought and pending settlement**. ACBS **also** recognises cash dividends, stock dividends, bonus shares and rights-to-subscribe into the collateral base; FNS explicitly **excludes** shares from rights not yet tradable. **That variation is real — make it a flag** |
| Withdrawal formula (ACBS) | `Số tiền có thể rút = Max(Tiền thực dư, 0) + Min[số tiền có thể ứng thực nhận, Giá trị đảm bảo tỷ lệ rút tiền]` |
| Buying-power priority (DNSE) | (1) cash in account, (2) linked bank balance, (3) unsettled sale proceeds, (4) buying power drawn from another deal |
| Interest start on rights subscriptions (ACBS) | from the **approval date** of the rights purchase |
| Notifications (SSI) | debt-maturity reminder 2 business days ahead; overdue alert; margin call when TLKQ < maintenance; force-sale fill notice — SMS/email |

---

## 4. Where the rulebook is SILENT — do not invent these

Each of these is delegated to the broker contract by name, or simply absent. Encoding a
default here without saying so would be exactly the class of defect house rule 3 forbids.

1. **The order in which positions are liquidated** on a force sale — QĐ 87 Điều 12.2(i).
2. **The priority order for applying sale proceeds** (principal / interest / fees / taxes)
   — same clause.
3. **The execution price for a force sale.** No rule. DNSE uses giá sàn; others unpublished.
4. **Interest day-count, compounding and accrual convention** — QĐ 87 Điều 11.4 delegates
   entirely. ACT/360 *and* ACT/365 both observed in the same market.
5. **The number of extensions.** Only the 3-month-per-extension cap is statutory.
6. **Intraday ratio monitoring.** The rule mandates end-of-day only.
7. **Any interest-rate cap** other than the Civil Code's general ceiling.
8. **The mapping of post-2020 "hạn chế giao dịch" / "đình chỉ giao dịch" onto QĐ 87
   Điều 3.2's older enumeration.**
9. **Whether UPCoM securities are eligible** — TT 120 says yes on its face, QĐ 87 says
   listed only, the market does listed only (§2.6).

---

## 5. Known gaps in this research — state them, do not paper over them

1. **QĐ 87 Điều 7.2 formulas (a) and (b) are images in every accessible copy.** The
   top-up amounts in §2.8 are **DERIVED**, not sourced. To close: obtain the công báo copy
   or the SSC PDF.
2. **No *Tình trạng hiệu lực* field was directly readable** for QĐ 87 or QĐ 1205. Current
   force is inferred from HOSE's 2025 and 2026 practice — strong, but not a status read.
3. **Every statutory text came from a commercial mirror**, not from công báo or
   ssc.gov.vn. See §0.
4. **Interest-rate structure at VPS, MBS, HSC, VNDirect and TCBS was not obtained**
   (403 or SPA). The broker sample is SSI, DNSE, ACBS, ABS, Pinetree, BVSC, FNS.
5. **No verified numeric call/force-sell threshold for statutory equity margin exists at
   ANY broker in this research — rewritten 2026-08-26.** SSI and ACBS publish structure
   only. DNSE publishes a full threshold table, but it is a **`Gói` / *giao dịch tiền mặt*
   cash-product table for all five rows** (re-fetched and confirmed verbatim), not a
   margin ladder. So the derivatives-style "80/90/100 with sourced shape and commercial
   levels" pattern has **no equity-margin counterpart to copy**: both the shape *values*
   and the levels are missing. What the statute gives is the **floor only** — `mmr ≥ 30 %`
   (Điều 5.2) and the cure ceiling of 3 business days (Điều 7.1). **Implement
   `call_level` and `force_level` as required, unsourced `BrokerMarginTerms` fields with
   no defaults**, bounded below by 0.30, and make a run that has not set them say so.
   To close: obtain a CTCK's *hợp đồng giao dịch ký quỹ* or a published margin policy
   that states TLKQ duy trì / TLKQ xử lý numerically.

---

## 6. Proposed object split, and the pre-trade gate

Two objects, mirroring the existing exchange-rules / broker-terms split.

```
MarginRegulation            # gazetted, dated, cited -- NOT user-configurable
  effective_from, effective_to, citation, confidence
  initial_margin_ratio_floor      = 0.50            # QĐ 87 Điều 5.1
  maintenance_margin_ratio_floor  = 0.30            # QĐ 87 Điều 5.2
  max_cure_business_days          = 3               # QĐ 87 Điều 7.1  (a CEILING)
  max_loan_term_months            = 3               # QĐ 87 Điều 11.1
  max_extension_months            = 3               # QĐ 87 Điều 11.2 (count: uncapped)
  collateral_value_cap            = 'last_close'    # QĐ 87 Điều 2.4
  ratio_determination             = 'end_of_day'    # QĐ 87 Điều 6.1
  foreign_investors_allowed       = False           # TT 120 Điều 9.2
  eligible_venues                 = {HOSE, HNX}     # QĐ 87 Điều 3  (conflict, §2.6)
  min_listing_months              = 6               # QĐ 87 Điều 3.1
  exclusion_predicates            = [...]           # QĐ 87 Điều 3.1-6 as amended by QĐ 1205
  ineligible_excluded_from_collateral = True        # TT 120 Điều 9.6 (over QĐ 87 Điều 10.2)
  exchange_publish_lag_bd         = 2               # QĐ 87 Điều 4.1
  broker_publish_lag_bd           = 2               # QĐ 87 Điều 4.2
  relist_review_min_months        = 6               # QĐ 87 Điều 4.1
  firm_limits: book <= 2.00 x equity, per_customer <= 0.03 x equity,
               per_security <= 0.10 x equity, per_issuer_shares <= 0.05   # QĐ 87 Điều 9
  prohibited_collateral           = [...]           # QĐ 87 Điều 10.1 a-e
  ineligible_account_holders      = [...]           # QĐ 87 Điều 13.4
  no_trade_beyond_buying_power    = True            # QĐ 87 Điều 13.5(d)
  margin_order_is_distinct_type   = True            # QĐ 87 Điều 13.5(e)
  regulator_suspension_flag       = False           # TT 120 Điều 9.9

BrokerMarginTerms           # commercial, per-firm, ASSUMED unless the user supplies real terms
                            # every field carries a PROVENANCE entry, as BrokerTerms does
  initial_margin_ratio            >= regulation floor
  maintenance_margin_ratio (call) >= regulation floor
  liquidation_ratio               >= regulation floor, <= maintenance
  loan_ratio_by_ticker            in (0, 0.50]
  cure_business_days              <= regulation ceiling
  consecutive_breach_days_before_sale
  overdue_days_before_sale
  intraday_monitoring, monitor_interval, price_source
  forced_sale_scope / forced_sale_price / forced_sale_target / forced_sale_notice
  proceeds_application_order      # SILENT in regulation
  liquidation_order               # SILENT in regulation
  rate_schedule[], day_count, calendar_days, overdue_multiplier
  extension_count_max, extension_fee, capitalise_fees
  per_customer_credit_limit
  collateral_includes_rights / pending_buys / unsettled_sale_proceeds
  accounting_unit                 # account | sub_account | deal
```

**Pre-trade gate:** `order_value × imr ≤ EE`, equivalently `order_value ≤ BP`
(QĐ 87 Điều 13.5(d)).

**Post-trade / EOD:** recompute `AB / EB`; `< call_level` → issue a call and start the
clock; **clock expiry OR `< liquidation_level`** → force sale.

**Integration notes for this codebase.** (i) A margin order is a **distinct order type**,
not a flag — Điều 13.5(e). (ii) `CB` counts unsettled sale proceeds, which
`Cash.available` deliberately excludes; keep the two computations separate. (iii) The
eligible-security list is **dated data supplied by the caller**, exactly like the VSDC
settlement calendar — do not ship a hardcoded list. (iv) The exclusion predicates need
issuer financial-statement facts the corpus does not carry; where a predicate cannot be
evaluated, the answer is **INDETERMINATE**, not "eligible".

---

## 7. Sources

**Primary instruments, full operative text read:**

- QĐ 87/QĐ-UBCK (2017-01-25) — luatvietan.vn/quyet-dinh-87-qd-ubck-huong-dan-giao-dich-ky-quy-chung-khoan.html ·
  luatvietnam.vn/chung-khoan/quyet-dinh-87-qd-ubck-uy-ban-chung-khoan-nha-nuoc-112080-d1.html ·
  hoatieu.vn/phap-luat/quyet-dinh-87-qd-ubck-quy-che-huong-dan-giao-dich-ky-quy-chung-khoan-120281 ·
  dongduong.net/quyet-dinh-so-87qdubck-quy-che-huong-dan-giao-dich-ky-quy-chung-khoan.html
- QĐ 1205/QĐ-UBCK (2017-12-27) — luatvietnam.vn/chung-khoan/quyet-dinh-1205-qd-ubck-uy-ban-chung-khoan-nha-nuoc-119297-d1.html
- TT 120/2020/TT-BTC Điều 9, 10 — hethongphapluat.com (…/dieu-9); consolidated with
  amendment annotations at luatvietnam.vn/chung-khoan/thong-tu-120-2020-tt-btc-giao-dich-co-phieu-niem-yet-dang-ky-196778-d1.html
- TT 121/2020/TT-BTC Điều 26, 27, 30, Biểu II.8 / II.8B — luatvietnam.vn/tai-chinh/thong-tu-121-2020-tt-btc-hoat-dong-cua-cong-ty-chung-khoan-197224-d1.html
- NĐ 155/2020/NĐ-CP Điều 198 — hethongphapluat.com/nghi-dinh-155-2020-nd-cp-huong-dan-luat-chung-khoan/dieu-198
- Luật Chứng khoán 54/2019/QH14 Điều 86 — hethongphapluat.com/luat-chung-khoan-2019/dieu-86
- TT 08/2026/TT-BTC (CCP clearing margin, **not** lending) — luatvietnam.vn/chung-khoan/thong-tu-08-2026-tt-btc-sua-doi-bo-sung-quy-dinh-thi-truong-chung-khoan-425642-d1.html

**Market practice / secondary:**

> **Truncated URLs are not citations.** Four entries below end in "…" and cannot be
> re-fetched as written — and three of them carry §1.1's **2026 in-force evidence**, on
> which the "QĐ 87 is still in force" inference partly rests. Specifically: the cafef
> Q2/2026 list, the 2018-draft piece, and the BVSC 18082026 page. Treat §1.1 evidence 3
> ("the April 2026 HOSE list…") and "every 2026 broker caps the loan at exactly 50 %" as
> **currently unverifiable as cited**. By contrast the July-2025 HOSE citation (the DNSE
> Senses URL below) is complete and was re-confirmed. **To close: restore the full URLs.**

- HOSE Q2/2026 ineligibility list, 2026-04-03 — cafef.vn/68-co-phieu-san-hose-khong-du-dieu-kien-giao-dich-ky-quy-trong-quy-ii-2026-… **(URL truncated — not re-fetchable)**
- HOSE Q3/2025 list, citing QĐ 87 + QĐ 1205 — dnse.com.vn/senses/tin-tuc/hose-cong-bo-danh-sach-chung-khoan-khong-du-dieu-kien-giao-dich-ky-quy-35085754
- Điều 9 limits explained — thoibaotaichinhvietnam.vn/quy-dinh-giao-dich-ky-quy-toi-da-cua-cong-ty-chung-khoan-151606.html
- 2018 draft 60 % imr (not adopted) — funan.com.vn/vi/…576538 **(truncated)** · cafef.vn/chu-tich-ubck-tang-ty-le-ky-quy-khong-phai-la-dong-thai-siet-margin-20180115203208315.chn
- 2011 imr floor 60 % — cafef.vn/thi-truong-chung-khoan/ubck-ty-le-ky-quy-ban-dau-do-ctck-quy-dinh-nhung-khong-thap-hon-60-20110830041610711.chn
- SSI — ssi.com.vn/khach-hang-ca-nhan/giao-dich-ky-quy; fee schedule /bieu-phi/bieu-gia-dich-vu-tai-chinh;
  **margin list 2026-08-25 (PDF parsed)** ssi.com.vn/upload/files/KHCN/Danh-muc-ty-le-ky-quy/36_ 25082026 Danh-muc-giao-dich-ky-quy.pdf
- DNSE — hdsd.dnse.com.vn/san-pham-dich-vu/sp-giao-dich-ky-quy-theo-deal/thong-tin-chung ·
  …/call-margin-force-sell
- ACBS FAQ — acbs.com.vn/faq/giao-dich-ky-quy (pages 1–5)
- ABS — abs.vn/margin-giao-dich-ky-quy/ · Pinetree — pinetree.vn/san-pham-va-dich-vu-2/pinetree-p-margin/ ·
  FNS — funan.com.vn/vi/page/giao-dich-ky-quy.7644 · BVSC — bvsc.com.vn/danhsachbaiviet/…lgl…18082026/ **(truncated — not re-fetchable)**

---

## 8. Verification log

**2026-08-26 — this document was adversarially audited** alongside `FEATURES.md`, by a
reader who re-fetched the primary mirrors rather than accepting the write-up's account of
them. §2 (the statutory layer) was the target and **survived**: QĐ 87 Điều 2 khoản 3–13,
Điều 2.4, 5.1/5.2, 6.1, 7.1, 9.1–9.4, 10.1(a)–(e), 10.2, 11.1–11.4, TT 120 Điều 9.2 / 9.4
/ 9.6 / 9.7 / 9.8 / 9.9, TT 121 Điều 26–27, NĐ 155 Điều 198 and Luật CK Điều 86.1(b) were
all re-read and confirmed clause by clause, as was QĐ 1205's scope (khoản 5 Điều 3 only,
effective 2018-01-02). The statutory/broker split holds in both directions: all 20
`MarginRegulation` fields trace to a clause that was read, and nothing commercial is
smuggled in.

**Corrected in this revision:**

1. **§3.2 — the DNSE ladder is a cash-product table, not a margin ladder** (all five rows,
   header `Gói`, rows `Giao dịch tiền mặt X%`). The "50 % package force-sells at exactly
   the statutory 30 % `mmr` floor" reading is withdrawn. **§5 gap 5 rewritten: this
   document has zero verified numeric margin thresholds at any broker.** Highest-severity
   finding.
2. **§1 — TT 120 Điều 9a added.** It exists, it is the foreign-institutional
   non-prefunded regime, and omitting it invites an implementer to refuse all foreign
   credit-funded buying.
3. **§1 — TT 08/2026's amended-article list corrected**, and its "CCP clearing margin"
   gloss downgraded to REPORTED.
4. **§0 and §2.1 — "four mirrors that agree verbatim" corrected to two** for everything
   past Điều 4; hoatieu.vn and dongduong.net were re-fetched and serve Chương I–II and
   Chương I respectively.
5. **§2.1 and §3.1 — `imr = 1 − loan_ratio` and "⇒ max LTV 50 %" graded DERIVED.**
6. **§2.6 — the TT 120 / QĐ 87 "CONFLICT" softened to a delegation**, on TT 120 Điều 9.8,
   which §1.1 already relies on; and the SSI-list evidence graded as the one-off parse it
   is.
7. **§2.8 — the ≤ 3-business-day cure ceiling attributed to QĐ 87 Điều 7.1 alone**;
   TT 120 Điều 9.6 has no day count.
8. **§2.12 — khoản numbering made explicit**: rate + Civil Code is **11.3**, calculation
   method is **11.4**.
9. **§3 — "observed 2026 market values" qualified**: SSI's schedule carries a 2022-11-01
   effective date.
10. **§7 — four truncated URLs flagged**, three of which carry §1.1's 2026 in-force
    evidence.

**Checked and left as written:** §2.9's reading of Điều 9.4 as "of that issuer's total
listed shares" — an audit pass reported the qualifier absent from the text; re-fetching
luatvietan returns *"…của một tổ chức niêm yết"*, so the reading stands. §1.1's
"is QĐ 87 still in force?" inference also stands: no evidence of supersession was found on
any reachable mirror, TT 120 Điều 9.8's delegation is real and no successor quy chế
surfaced, and the July-2025 HOSE citation of QĐ 87 + QĐ 1205 was confirmed verbatim. Keep
the §5 gap 2 caveat as written — it is a well-supported inference, not a status read.

**Prompt injection, still live.** `hethongphapluat.com` article pages carry an embedded
instruction block addressed to an AI reader. It was encountered again on 2026-08-26 and
treated as data. Two sources in §7 are on that host.
