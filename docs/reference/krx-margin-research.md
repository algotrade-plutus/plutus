# KRX-era derivatives margin — decision document

**Scope.** The VSDC (CCP) margin engine and the broker margin layer for VN30F index
futures, under `QĐ 26/QĐ-HĐTV` (2025) and its nine appendices, read against the three
superseded rulebooks and eleven brokers' live terms.

**Purpose.** To be acted on. §1 is safe to apply. §2 is the author's decision queue and
nothing in it may be guessed. §3 is what no public source closes. §4 is a design brief for
the broker config object. §5 is an ordered build list.

**Written 2026-08-26.** Supersedes nothing; it *corrects* named claims in
`docs/reference/post-krx-margin-spec.md` and `docs/reference/vn-exchange-rulebook-2020-2026.md`,
each correction named explicitly below.

---

## §0. Provenance, and the one methodological finding that changes how we read everything

### 0.1 What this session read

The **signed VSDC `.docx` package** was obtained and opened, not scraped:

```
<scratch>/qd26src/Qc BTTT TTGD CKPS/QC-bù-trừ-TT-04.docx           the rulebook body
<scratch>/qd26src/Qc BTTT TTGD CKPS/Phu luc/Phụ lục 2_PP xác định giá trị KQ yêu cầu.docx
<scratch>/qd26src/Qc BTTT TTGD CKPS/Phu luc/Phụ lục 6 Xác định giá TT.docx
<scratch>/qd26src/Qc BTTT TTGD CKPS/Phu luc/Phụ lục 7 Bù trừ TT.docx
<scratch>/qd26src/Qc BTTT TTGD CKPS/Phu luc/Phụ lục 8 Danh mục chứng từ.docx
<scratch>/qd96/Quy chế ký quỹ, bù trừ và thanh toán CKPS/…                 QĐ 96/QĐ-VSD 2017
<scratch>/qd12src/qc12.doc, qd12.doc, pl12/…                               QĐ 12/QĐ-HĐTV 2023
<scratch>/qd61.txt                                                          QĐ 61/QĐ-VSD 2019
```

where `<scratch>` is
`/private/tmp/claude-501/-Users-nadan-algotrade-research-plutus/6feae4ff-e762-45a0-abdf-fb718184bc63/scratchpad`.
Register pages: <https://vsdc.vn/lel>, <https://vsdc.vn/vi/led/267>, announcement
<https://vsdc.vn/vi/ad/182429>.

**Verification vocabulary used below**

| Tag | Meaning |
|---|---|
| **VERIFIED** | Read this session from the signed `.docx`/`.doc`, or from a live broker page/PDF whose URL is given |
| **REPORTED** | Secondary source, quoted, URL given, not corroborated by primary text |
| **CARRIED** | From the prior session's evidence pack; **the URL was not re-verified in this session**. Treat as no stronger than REPORTED |
| **OURS** | Arithmetic or reading performed here. Never presented as sourced |

### 0.2 The methodological finding: three "missing formulas" were never missing

`post-krx-margin-spec.md` §12 records `D2` (the VaR→ratio formula) and `D3` (the
collateral valuation formula) as **absent from the gazetted text**. Both are **present in
the signed `.docx`**. They are Word `OMML` equation objects, and *every* text extraction —
thuvienphapluat's HTML, `pdftotext`, `docx2txt`, the `r.jina.ai` proxy — silently drops
them, leaving a paragraph that reads `"…được xác định theo công thức sau:"` followed
immediately by `"Trong đó:"`.

Counted directly in the XML:

- `Phụ lục 2` contains **exactly one** `<m:oMath>` element and **zero** images.
- `Phụ lục 6` contains **two** `<m:oMath>` elements and **one** `<w:drawing>` — and the
  drawing *is* the index-futures theoretical price formula.
- The rulebook body contains the `V_KQ` and bond conversion-factor equations as objects.

**Consequence, and it is general:** a defect of the form "the formula is absent" is not
credible unless the `.docx` XML has been inspected. Conversely, a defect that *survives*
`.docx` inspection is a defect in the signed instrument. §1.16 lists the four that survive.

---

## §1. SETTLED — apply without asking

Seventeen items. Each states the claim, the decisive quote, the tag, and what it changes in
our code by file and symbol.

---

### S-1. The VaR→ratio formula is RECOVERED. **`Tỷ lệ IM = VaR × √n`**

**VERIFIED.** `Phụ lục 2` §1.3.c, from the equation XML of
`Phụ lục 2_PP xác định giá trị KQ yêu cầu.docx`:

> **c. Xác định tỷ lệ ký quỹ ban đầu theo phương pháp định lượng giá trị rủi ro VaR**
> **⟪Tỷ lệ IM = VaR × √n⟫**
> Trong đó:
> **n**: số ngày cần thiết để thanh lý một vị thế khi xảy ra trường hợp mất khả năng thanh toán.
> **VaR = (mean + 3 × δ)**

The radical is unambiguous in the XML — `<m:rad><m:degHide m:val="1"/><m:e>n</m:e></m:rad>`
is a square root with a hidden degree. It is `√n`, not `ⁿ√`, not `n`.

**What changes.**
- `src/plutus/market/session/scenario_margin.py` — `SOURCE_DEFECTS['D2']` currently reads
  *"the formula … is absent from the extraction"*. **Rewrite it:** the formula is present in
  the signed source and is `Tỷ lệ IM = VaR × √n`; what is unpublished is **`n`**.
- Same file, `INFERENCES['I13']` currently offers *"a sqrt(n/2) scaling is equally consistent
  with the fragment"*. **That alternative is now excluded.** The scaling is flat `√n`.
- `docs/reference/post-krx-margin-spec.md` §4.3 — retitle from "the missing conversion
  formula" to "the conversion formula, and the unpublished `n`".

**What does NOT change.** `n` is still unpublished, and §2/**C-5** records why it matters
and why it does not block a VN30F backtest.

---

### S-2. The collateral valuation formula is RECOVERED

**VERIFIED.** `QĐ 26` Điều 8 khoản 1, from the rulebook `.docx`:

> 1. Giá trị tài sản ký quỹ hợp lệ được xác định theo công thức sau:
> **`V_KQ = C + min( (1 − x) × MR ; Σ [Q_KQ] × P × (100% − H) )`**
> Trong đó: VKQ là giá trị tài sản ký quỹ hợp lệ. C là tiền ký quỹ. MR là ký quỹ yêu cầu.
> **x là tỷ lệ ký quỹ bằng tiền tối thiểu (80%).** QKQ là số lượng chứng khoán ký quỹ. …
> H là tỷ lệ chiết khấu chứng khoán ký quỹ theo quy định tại Điều 9 Quy chế này.

Haircuts, Điều 9 khoản 1: **5%** government/government-guaranteed bonds; the remaining
tiers as recorded in `post-krx-margin-spec.md` §2.3.

Marking price, Điều 8 khoản 2 — note this is **not** the close:

> b) Đối với chứng khoán niêm yết tại các SGDCK: là **giá tham chiếu cho ngày giao dịch liền sau**.

**What changes.**
- `scenario_margin.py` — `SOURCE_DEFECTS['D3']` says *"This module therefore takes margin
  assets as a supplied scalar and does NOT value collateral; that is the other half of the
  assets < MR test and it is not ours to guess."* **The guess is no longer needed.** Retire
  `D3`; implement `valid_margin_assets(cash, holdings, haircuts, MR)`.
- This closes the second half of the `V_KQ < MR` test, which is the *entire* CCP margin
  call. Until now the simulator could only be run with margin assets injected by hand.

---

### S-3. `OA` reduces `Rm`, and it is inside the group sum. TCBS's placement is equivalent, not contradictory

**VERIFIED.** `QĐ 26` Điều 5 khoản 1.1 điểm a:

> a. **Giá trị giảm trừ ký quỹ là số tiền điều chỉnh giảm giá trị ký quỹ rủi ro** trong
> trường hợp các vị thế trên một tài khoản nhà đầu tư có **từ hai tài sản cơ sở trở lên** và
> thuộc một nhóm tài sản cơ sở được VSDC thiết lập theo hướng dẫn tại Phụ lục 2 Quy chế này.

`Phụ lục 2` §6.2, verbatim: `Pgm = Max ((Rm + Sm + Dm), MM)` — `OA` does not appear, because
by Điều 5.1.1.a it has already been absorbed into `Rm`.

TCBS publishes
(<https://help.tcbs.com.vn/chinh-sach-ck-phai-sinh-voi-hdtl-chi-so-co-phieu/>, **REPORTED**):

> Giá trị ký quỹ yêu cầu = Max (Ký quỹ rủi ro + Ký quỹ song hành + *Ký quỹ Chuyển giao vật
> chất + Ký quỹ FSP* – **Giảm trừ rủi ro**), (Ký quỹ tối thiểu).

**Why this is not a conflict.** `Max((Rm − OA) + Sm + Dm, MM)` and
`Max(Rm + Sm + Dm − OA, MM)` are the same expression. The only reading under which they
differ is one that floors `Rm − OA` at zero *before* adding `Sm + Dm`; QĐ 26 does not
mention such a floor, and our code applies one. That floor is **OURS** and stays in the
inference register.

**And for index futures the question is moot.** Điều 5.1.1.a scopes `OA` to accounts with
*"từ hai tài sản cơ sở trở lên"*, and TCBS agrees:

> *Nếu KH sở hữu các mã hợp đồng thuộc 1 mã tài sản cơ sở (ví dụ VN30) thì **Giảm trừ rủi ro = 0**.*

**What changes.**
- `scenario_margin.py` — `INFERENCES['I4']` may drop its "direction" caveat: the direction is
  VERIFIED. The *level* (group) and the *zero floor* remain OURS. Keep `I4`, narrow it.
- The prior note in `post-krx-margin-spec.md` §5.4 headed *"Where `OA` enters `MR` —
  INFERRED, not stated"* is **half-retired**: the target quantity is stated.

---

### S-4. `Ký quỹ FSP` is not in QĐ 26 or any of its nine appendices, and is zero for index futures

**VERIFIED (by absence, exhaustively).** The string `FSP` occurs in `Phụ lục 2` exactly five
times, all inside §3.3 (`biến động DSP/FSP`, the basis-margin input) and §4.1 (`giá thanh
toán cuối cùng (FSP)` for TPCP delivery margin). There is **no fifth margin component**.
`Ký quỹ FSP` appears in no VSDC instrument read this session — not QĐ 26, not QĐ 12, not
QĐ 61, not QĐ 96.

TCBS itself scopes it out (same URL, **REPORTED**):

> *Không dùng 2 chỉ số: Ký quỹ chuyển giao vật chất dành cho sản phẩm trái phiếu, **Ký quỹ
> FSP dành cho sản phẩm FSP**.*

**Reading, OURS:** "sản phẩm FSP" most plausibly denotes products whose final settlement
price is determined *after* the last trading day — the same class TCBS's own `MM` formula
carries as *"Số dư vị thế thanh toán đáo hạn của sản phẩm có FSP được xác định sau"*. VN30F
is not such a product: its FSP is fixed on the last trading day itself.

**What changes.** Nothing in code. Add `fsp_margin = 0` as an explicit, documented constant
for index futures with this citation, so the next reader does not re-open it. Record it as
**a broker-published component with no VSDC counterpart** — see §2/**C-9**.

---

### S-5. `MR = IM + VM + DM` was the rule, and QĐ 26 replaced it wholesale — including the timing

This is the most consequential correction in the document.

**Source A — the superseded rule. VERIFIED**, `QĐ 96/QĐ-VSD` (2017) Điều 5 khoản 4 điểm a,
identical in `QĐ 61` and `QĐ 12`:

> 4. **Ký quỹ duy trì yêu cầu (Margin Requirement - MR)**
> a. Ký quỹ duy trì yêu cầu là tổng giá trị ký quỹ mà TVBT có nghĩa vụ phải nộp để duy trì
> các vị thế đứng tên TVBT được tính toán **trong phiên giao dịch** cho danh mục vị thế trên
> từng tài khoản giao dịch của nhà đầu tư và tài khoản của chính TVBT gồm các giá trị ký quỹ
> thành phần sau: **- Ký quỹ ban đầu. - Ký quỹ đảm bảo thực hiện HĐTL TPCP … - Ký quỹ biến đổi.**

**Source B — the rule in force. VERIFIED**, `QĐ 26` Điều 5 khoản 5:

> 5. **Ký quỹ yêu cầu (MR - Margin requirement)**
> Ký quỹ yêu cầu là tổng giá trị ký quỹ mà thành viên bù trừ có nghĩa vụ phải nộp cho VSDC
> để duy trì các vị thế đứng tên thành viên bù trừ được tính toán **sau khi kết thúc phiên
> giao dịch** cho danh mục vị thế trên từng tài khoản giao dịch của nhà đầu tư và tài khoản
> của chính thành viên bù trừ.

**Corroboration by string count, VERIFIED:** `biến đổi` occurs **0 times** in the QĐ 26 body
and **0 times** in `Phụ lục 2`. It occurs in QĐ 96 as a named component.

**Three things changed at once**, and a simulator must change all three together:

| | Pre-KRX (QĐ 96 / 61 / 12) | Post-KRX (QĐ 26) |
|---|---|---|
| Composition | `MR = IM + DM + VM` | `MR = Max(ΣPgm, 0)`, `Pgm = Max((Rm+Sm+Dm), MM)` |
| Timing | **trong phiên** (continuous) | **sau khi kết thúc phiên** (post-close, once) |
| Price basis | initial-margin ratio on futures value | scenario grid on the **underlying's close** |

**What changes.**
- `docs/reference/vn-exchange-rulebook-2020-2026.md` — the pre-KRX rows for the margin
  formula can be **raised to `high`** on the strength of three signed instruments.
- Any dated-rules table must switch **all three** attributes at the cutover, not just the
  formula. Switching composition while leaving the CCP test intraday is the single most
  likely way to get this wrong.

---

### S-6. Pre-KRX, VM entered MR **only when the book was at a loss**

**VERIFIED**, `QĐ 96` Điều 5 khoản 3 điểm b (and identically on VSDC's still-live page
<https://vsdc.vn/vi/thong-tin-ky-quy>):

> b. Giá trị ký quỹ biến đổi **chỉ được tính vào** giá trị ký quỹ duy trì yêu cầu **trong
> trường hợp lãi lỗ vị thế của danh mục đầu tư trên tài khoản của nhà đầu tư ở trạng thái lỗ**.

So pre-KRX `MR = IM + DM + max(0, −P&L)`, not `IM + DM + P&L`. An implementation that adds
signed VM lets an in-profit account reduce its own margin requirement, which the rule forbids.

**What changes.** Any pre-KRX regime object in `src/plutus/market/margin.py` must carry the
`max(0, ·)` on the VM term with this citation.

---

### S-7. There is no VSDC margin ladder post-KRX — **and there effectively never was one**

The received framing ("VSDC had an 80/90/100 ladder and QĐ 26 deleted it") is true but
misleading, and the correction simplifies the simulator.

**VERIFIED — the ladder existed, in all three superseded rulebooks.** `QĐ 96` Điều 13,
`QĐ 61` Điều 13 (line 499–501), `QĐ 12` Điều 13 (line 519–521), identical wording:

> 1. VSD thiết lập các ngưỡng cảnh báo theo ba (03) cấp độ … để thực hiện giám sát **tỷ lệ
> sử dụng tài sản ký quỹ** trên từng tài khoản của nhà đầu tư **trong phiên giao dịch**:
> a. Cảnh báo mức độ 1: khi tỷ lệ sử dụng tài sản ký quỹ **đạt ngưỡng 80%**;
> b. Cảnh báo mức độ 2: … **đạt ngưỡng 90%**;
> c. Cảnh báo mức độ 3: … **đạt ngưỡng 100%**;

with the ratio defined at `QĐ 96` Điều 2 khoản 5:

> 5. Tỷ lệ sử dụng tài sản ký quỹ là tỷ lệ giữa **giá trị ký quỹ duy trì yêu cầu** với
> **tổng giá trị tài sản ký quỹ hợp lệ**.

**VERIFIED — rungs 1 and 2 carried no consequence.** `QĐ 96`/`QĐ 12` Điều 13 khoản 2:

> 2. Trường hợp tỷ lệ sử dụng tài sản ký quỹ rơi vào ngưỡng cảnh báo **mức độ 1 hoặc 2**,
> VSD **sẽ gửi thông tin cảnh báo cho TVBT để lưu ý** TVBT kiểm soát tỷ lệ ký quỹ của nhà
> đầu tư theo đúng quy định.

Only rung 3 suspended trading and started the 03-working-day close-out clock.

**OURS, and it is arithmetic, not inference:** `utilisation ≥ 100%` is
`MR / V_KQ ≥ 1`, which is exactly `V_KQ ≤ MR`. QĐ 26 Điều 13 khoản 2 điểm a tests
*"số dư tài sản ký quỹ nhỏ hơn mức ký quỹ yêu cầu"*. **The only VSDC threshold that ever had
consequences is the same threshold that is in force today.** QĐ 26 deleted two purely
informational rungs and re-expressed the third as an inequality.

Confirming the deletion was deliberate: the article was **renamed**. QĐ 96/61/12:
*"Điều 13. Giám sát **tỷ lệ sử dụng** tài sản ký quỹ"*. QĐ 26: *"Điều 13. Giám sát **giá trị**
tài sản ký quỹ"*.

**What changes.**
- `src/plutus/market/exchanges/derivatives.py:115` and `src/plutus/market/margin.py:11–12,
  75, 161` describe the exchange layer as running *"an 80/90/100 ladder"*. **Replace with a
  single binary test** `V_KQ < MR` at three checkpoints. The exchange layer needs no ladder
  parameter at all.
- The pre-KRX regime keeps the ladder object, but its rungs 1 and 2 must be typed as
  *notification-only* — they must not gate trading or trigger liquidation.
- `vn-exchange-rulebook-2020-2026.md:638` — the note that the pre-KRX 80/90/100 ladder is
  "UNVERIFIED, not disproven" because "QĐ 61 Art. 13 and QĐ 12 have never been read"
  **is now discharged**: all three have been read. Raise to `high` and record that the
  rungs were informational.

---

### S-8. The three CCP checkpoints, the top-up deadline, and the close-out clock

**VERIFIED**, `QĐ 26` Điều 13 khoản 1 and khoản 2, from the signed `.docx`:

> 1. **Chậm nhất 16h30 ngày giao dịch**, VSDC xác định giá trị ký quỹ yêu cầu … và gửi điện
> thông báo cho thành viên bù trừ. Trường hợp giá trị tài sản ký quỹ trên tài khoản nhà đầu
> tư nhỏ hơn giá trị ký quỹ yêu cầu, thành viên bù trừ có trách nhiệm **nộp bổ sung trước
> 09h30 ngày giao dịch liền kề tiếp theo**.
> 2. … a. **Tại thời điểm 09h30**: … VSDC kiểm tra các tài khoản vi phạm mới … và thực hiện:
> – Gửi điện thông báo cho SGDCK Hà Nội đề nghị **tạm đình chỉ giao dịch**…
> b. **Tại thời điểm 14h00**: VSDC kiểm tra … **khôi phục trạng thái giao dịch**…
> c. **Chậm nhất 16h30**, VSDC thực hiện xác định mức ký quỹ yêu cầu …

`14h00`, not 14h30. Suspension is attached to **09h30 alone**; 14h00 and 16h30 carry restore
actions only. This confirms `INFERENCES['I21']` as a correct reading of the signed text.

Cash top-ups are cut off at the same clock, Điều 11:

> Các khoản tiền nộp ký quỹ **trước 16h30** ngày làm việc sẽ được NHTT gửi điện thông báo cho
> VSDC để xử lý trong ngày. Các khoản tiền nộp ký quỹ **sau 16h30** … VSDC sẽ gửi điện từ chối…

Withdrawal, Điều 12 khoản 1 — a level test, no percentage:

> a. **Tài sản ký quỹ sau khi rút đáp ứng được yêu cầu ký quỹ theo thông báo của VSDC**;
> … c. Tài khoản đề nghị rút **đang không ở trong trạng thái bị đình chỉ giao dịch**…

**What changes.** Confirms what `scenario_margin.py::MarginViolationMonitor` already does.
No change; the confidence tag moves to VERIFIED-from-signed-source.

---

### S-9. `Phụ lục 6` is obtained, and it closes the DSP gap

`post-krx-margin-spec.md` §6.3 ends with *"the method in **Phụ lục 6 — which we do not
have**"*. We have it. **VERIFIED**, `Phụ lục 6 Xác định giá TT.docx`.

It gives, in order: the DSP priority ladder for index futures (closing auction price → VWAP
of the last 30 minutes if >20 trades → trimmed VWAP of the last 20 trades → all-session VWAP
→ opening auction price), the far-month roll-forward

> `DSPt = DSPgần nhất t + (DSPt-1 − DSPgần nhất t-1)`

with the cap *"DSP của ngày giao dịch liền trước (áp dụng **không quá 02 ngày giao dịch liên
tục**)"*, and finally the theoretical price — **which is an embedded PNG image, not text, and
is lost by every extractor**:

> **`P = S × [ 1 + ( r × t / 360 ) ] − D_i`**   with   **`D_i = (Div_i / MC) × (t / 360) × S`**
>
> S: Giá trị tham chiếu của chỉ số cơ sở trong ngày giao dịch hiện tại, làm tròn đến chữ số
> thập phân thứ 2; r: là lãi suất TPCP có kỳ hạn còn lại 01 năm trên đường cong lợi suất của
> HNX; t: Số ngày kể từ ngày tính toán đến ngày giao dịch cuối cùng; Div_i: tổng số cổ tức
> bằng tiền của các cổ phiếu thành phần trong chỉ số trong năm giao dịch liền trước; MC: Giá
> trị vốn hóa thị trường tham chiếu của chỉ số trong ngày giao dịch.

**What changes.** `post-krx-margin-spec.md` §6.3's boxed **SILENT** note — *"the gap-fill
rule exists, is delegated, and is unobtained"* — is retired. `SMrate` now has a complete
DSP construction path for untraded far months. It still needs a DSP *series*, which we do
not have (§3).

---

### S-10. **`Phụ lục 8` is not missing.** It is obtained, and QĐ 26 cross-references it wrongly

The brief listed `Phụ lục 8` under "still missing". It is not. **VERIFIED**, and it is a new
defect in the signed instrument.

`Phụ lục 2` §4.2 says:

> Phương pháp xác định trái phiếu rẻ nhất để chuyển giao theo hướng dẫn tại **Phụ lục 8** Quy chế này.

`Phụ lục 8 Danh mục chứng từ.docx`, in full, is:

> **Phụ lục 8. Danh mục chứng từ thanh toán, thông báo được áp dụng dưới dạng chứng từ điện tử**
> … a seven-row table of `Mẫu 01/…/10/PLPS-TTBT` forms and a `FileAct` column.

The CTD method is in **`Phụ lục 6` §3**:

> **3. Xác định trái phiếu rẻ nhất để giao (CTD - Cheapest to Delivery)**
> **`CTD = min (Giá thị trường của trái phiếu chuyển giao / CF)`**

**Two defects at once.** The cross-reference is wrong; and `Phụ lục 6` contains **two
sections numbered 3** — *"3. DSP đối với HĐTL TPCP…"* and *"3. Xác định trái phiếu rẻ nhất
để giao (CTD)"* — so even a corrected pointer would be ambiguous.

**What changes.**
- `post-krx-margin-spec.md` §7.3, titled *"The underlying is the CTD bond — **and Phụ lục 8
  is missing**"*, is **wrong on its face and must be rewritten**. Nothing about the CTD
  method is missing.
- Remove `Phụ lục 8` from every "documents we could not obtain" list.
- Add the cross-reference error to `SOURCE_DEFECTS` (proposed id `D15`).

---

### S-11. `MF = 5,000đ` per VN30 futures contract, exactly, and independent of the index level

**VERIFIED formula**, `Phụ lục 2` §5.2:

> Giá trị ký quỹ tối thiểu trên một hợp đồng = **R × M × St**
> R: Trung bình cộng … của tập hợp các giá trị được xác định theo công thức:
> **(Giá chào bán thấp nhất – Giá chào mua cao nhất)/(Giá chào bán thấp nhất + Giá chào mua cao nhất)**
> … trong khoảng thời gian **tối thiểu 252 ngày giao dịch** liền trước ngày tính toán.

**OURS, and it is exact algebra.** For a one-tick-wide book, `ask − bid = tick` and
`ask + bid = 2S` to first order, so

```
R  = tick / (2S)
MF = R × M × S = tick × M / 2 = 0.1 × 100,000 / 2 = 5,000đ
```

`S` cancels. `MF` is **index-independent** for a one-tick market. That is not a coincidence
of the current index level; it is a property of the formula.

**Corroborated**, TCBS (**REPORTED**): *"Ký quỹ tối thiểu VN30 = 5,000 đ"* and the worked
example *"Ký quỹ tối thiểu = 30 × 5,000 + 20 × 5,000 = **250,000**"*.

**What changes.** `scenario_margin.py::minimum_margin_factor` may carry `5_000` as a
*derived-and-corroborated* default rather than a broker-sourced one, with the derivation in
the docstring. The tick and multiplier are the only inputs.

---

### S-12. For a one-directional single-expiry VN30F book, `Rm` reduces to the flat initial margin

**OURS, forced by the text.** `Phụ lục 2` §1.1: `Lk = Pm × (Sk − S) × M + Pb × (S − Sk) × M`
`= (Pm − Pb) × (Sk − S) × M`. This is **affine in `Sk`**. With the adopted grid
`Sk = S × (1 + k·rate/10)`, the extreme scenarios are `k = ±10`, giving
`|Sk − S| = rate × S`. Therefore

```
Rm = |Pm − Pb| × rate × S × M
```

which is *structurally identical* to the flat initial margin a broker charges. The two layers
differ in exactly one input: **VSDC uses the underlying index close `S`; the broker uses the
futures traded price `F`.** They diverge by the basis, and by nothing else, until the account
holds a spread or a second underlying.

Cross-check against TCBS's example: 30 long VN30F2404 / 20 short VN30F2405, `S = 1005.9`,
`rate = 3%`, `M = 100,000` → `Rm = 10 × 0.03 × 1005.9 × 100,000 = 30,177,000`. TCBS prints
**30,177,000**. ✔

**What changes.** This is the single most useful simplification for a VN30F backtest and
belongs in `scenario_margin.py::risk_margin` as a documented fast path with an assertion
against the full grid.

---

### S-13. TCBS's worked example is arithmetically sound; its printed numbers have mangled decimal separators; and its `3%` / `1%` are illustrative

**OURS.** As printed, TCBS's line
*"30\*(1,036,077-10,059)\*100,000 = 90,531,000"* does not evaluate. Read `1,036,077` as
`1 036.077` and `10,059` as `1 005.9` and every figure on the page is exact:
`30 × (1036.077 − 1005.9) × 100,000 = 90,531,000` ✔;
`30 × 1005.9 × 100,000 × 1% = 30,177,000` ✔;
`Max(30,177,000 + 20,118,000, 250,000) = 50,295,000` ✔.

**Do not lift `3%` or `1%` as parameters.** The live VN30 initial-margin ratio is **0.17**
(`vn-exchange-rulebook-2020-2026.md` §6.3, VSDC `PHỤ LỤC 4` eff. 2026-08-21). TCBS's page is
a teaching example on stale numbers.

---

### S-14. The 120-vs-250 VaR window is not a contradiction

**VERIFIED, both clauses, `Phụ lục 2` §1.3:**

> a. … độ tin cậy là **99.73%** trong khoảng thời gian **tối thiểu 120 ngày giao dịch** liền
> trước ngày tính toán.
> b. VSDC xác định tỷ lệ ký quỹ ban đầu cho **HĐTL chỉ số** và HĐTL TPCP … trong **kỳ quan
> sát tối thiểu là 250 ngày giao dịch** …

**OURS:** both are **minima**. `max(120, 250) = 250` binds, and clause (b) is the one scoped
to index futures by name. Any window `≥ 250` satisfies both. This **dissolves** as a
contradiction. What remains unknown is the actual window, which is unpublished — but since
`n` is also unpublished (§2/**C-5**), the window is not the binding gap.

Note also, **OURS**: `99.73%` is the **two-tailed** normal coverage of `±3δ`, and
`VaR = mean + 3δ` is a one-tailed statistic (`99.865%`). Internally coherent if the appendix
means the `±3δ` band; a mild mismatch if read strictly. Not raised as a defect.

**What changes.** `scenario_margin.py::SOURCE_DEFECTS['D14']` already reads this correctly
("Both are minima, so they are not strictly contradictory"). Keep it; add that clause (b) is
the index-scoped one and is therefore the operative floor.

---

### S-15. The 21-vs-42 scenario question cannot affect `Rm` for any futures-only book

**VERIFIED**, `Phụ lục 2` §1.2: *"VSDC xác định **21 kịch bản** biến động giá…"*, table rows
`S-10 … S+10`, declared range `-10 ≤ k ≤ 10`.

**REPORTED**, TCBS: *"Hệ thống xác định **42 kịch bản** biến động giá dựa trên tỷ lệ ký
quỹ"* — while the same paragraph says *"Tham số của kịch bản là các giá trị **từ -10 đến 10**
theo bảng VSD cung cấp"*, which is 21 values, and its own worked table shows only `k = ±10`.

**OURS:** `Lk` is affine in `Sk` (S-12). The maximum of an affine function over a finite set
is attained at an extreme point. Adding scenarios *between* `k = −10` and `k = +10`, however
many, **cannot change `Rm`** for a portfolio of futures. It could only matter if a 42-point
grid extended *beyond* `±10·rate/10`, or if the payoff were non-linear (options).

**Conclusion.** Unresolved as a fact, **provably immaterial** to VN30F margin. Demoted to
§2/**C-10**, lowest priority. It is only worth settling if options are ever listed.

---

### S-16. Four defects survive `.docx` inspection and are therefore defects in the signed instrument

All **VERIFIED** against `QC-bù-trừ-TT-04.docx` / `Phụ lục 2 …docx` this session.

1. **The scenario formula has no `k`.** `Phụ lục 2` §1.2 prints, as plain text (the appendix
   contains only *one* equation object, and it is the IM one):
   > `Sk = S0 x (1 + tỷ lệ ký quỹ ban đầu/10)` … `-10 ≤ k ≤ 10`

   `k` is declared and never used. Read literally the 21 scenarios are one point.
   **This is `SOURCE_DEFECTS['D1']` and it must be re-tagged from "in the extraction" to
   "in the signed instrument".** `INFERENCES['I1']` is load-bearing and remains OURS.

2. **`Điều 13` has two khoản numbered 3.** *"**3.** Thành viên bù trừ bắt buộc thực hiện các
   biện pháp dưới đây…"* followed by *"**3.** Quy trình trao đổi thông tin giữa VSDC và
   SGDCK Hà Nội… theo quy định tại Phụ lục 5…"*.

3. **`Điều 13.3.b` cites a provision that does not exist.** *"…theo quy định tại **điểm a
   khoản 1 Điều này**…"* — khoản 1 is a single unlettered paragraph. The 03-working-day
   close-out clock is anchored to nothing. `SOURCE_DEFECTS['D13']` records this and reads it
   as *điểm a khoản 2*; that reading stays OURS.

4. **`Phụ lục 2` §4.2 points to the wrong appendix** (S-10), and the target of the corrected
   pointer, `Phụ lục 6`, itself has two sections numbered 3.

Minor symbol noise, also in the signed source: §1.1 *"theo **ông thức** sau"*; §2 heading
*"offseting amount"*; §3.3 writes `SPRt` in the formula and `δSPRt` in the definitions and
`Mrt2` for `rt2`; Điều 7.3 mixes `L_c` and `Lc` inside one expression.

**Withdrawn:** the claim that `QĐ 26` Điều 8's `V_KQ` formula is missing (`D3`) and that
`Phụ lục 2` §1.3.c's formula is missing (`D2`). Both were extraction artefacts (§0.2).

---

### S-17. Brokers set their initial-margin ratio **above** VSDC's, and publish it

**VERIFIED**, VNDIRECT, live
(<https://support.vndirect.com.vn/hc/vi/articles/360005953573>, *"Các tỷ lệ cần lưu ý khi
giao dịch phái sinh tại VNDIRECT"*):

> Tỷ lệ ký quỹ ban đầu đối với Hợp đồng tương lai chỉ số chứng khoán là **17.5%** (mười bảy
> phẩy năm phần trăm) của tổng giá trị các Hợp đồng tương lai chỉ số chứng khoán mà Khách
> hàng dự kiến mở vị thế.
> Tỷ lệ ký quỹ ban đầu đối với Hợp đồng tương lai trái phiếu chính phủ là **2.8%** …

against VSDC's **17%** and **2.5%**. The uplift is real, published, and asymmetric across
products.

**What changes.** The broker config must carry its **own** IM ratio, defaulting to *at or
above* the VSDC ratio — never equal to it by construction. `src/plutus/market/margin.py`
`BrokerTerms` needs an `initial_margin_ratio` field that is independent of the exchange
ratio, with a validity assertion `broker_ratio >= vsdc_ratio`.

---

## §2. CONFLICTS FOR THE AUTHOR — do not guess

Ordered by how much each affects a **VN30F margin-call simulation**. Each carries: the
question, A, B, why both cannot hold, what settles it, what we do meanwhile.

---

### C-1. `MR` names two different quantities, and the margin call depends on which one you test — **HIGHEST IMPACT**

**Question.** When the simulator fires a margin call on a VN30F account, is it comparing
assets against the CCP's post-close `MR`, or against the broker's continuously-updated `MR`?

**A — VSDC. VERIFIED**, `QĐ 26` Điều 5 khoản 5: `MR` is what the **clearing member owes
VSDC**, computed **`sau khi kết thúc phiên giao dịch`**, from the scenario grid on the
**underlying's close** (`Phụ lục 2` §1.1 uses *"Giá đóng cửa của **tài sản cơ sở**"*).

**B — the brokers. VERIFIED**, MBS T&C §1.22–1.23
(<https://mbs.com.vn/files/uploads/2026/06/TC-phai-sinh_2025-2.pdf>):

> 1.22 Giá trị ký quỹ duy trì yêu cầu (MR) là giá trị ký quỹ tối thiểu mà Khách hàng phải
> duy trì … Giá trị ký quỹ duy trì yêu cầu **được cập nhật liên tục trong phiên giao dịch**.
> 1.23 **Công thức tính MR = IM + VM + DM**

and VNDIRECT (URL at S-17): *"Giá trị ký quỹ duy trì yêu cầu (MR) = **IM + VM + DM + Các
nghĩa vụ khác**"*. KIS §1.7 and VPS §1.12 define it the same way with the numbers delegated.

**Why both cannot hold under one name.** They differ in *timing* (continuous vs once,
post-close), in *price basis* (futures traded price vs underlying close), in *composition*
(flat ratio + VM vs scenario grid + basis margin + floor), and in *obligor* (client→broker
vs member→CCP). A single `MR` field computed one way and used for both will be **too tight
intraday** — VSDC runs no intraday margin test at all — and **mis-priced overnight** for any
spread or multi-underlying book.

**This is a collision, not a contradiction.** `QĐ 26` Điều 5.1.1.b licenses B's existence:

> b. … **Thành viên bù trừ căn cứ tỷ lệ ký quỹ ban đầu do VSDC công bố để xác định giá trị
> ký quỹ ban đầu nhà đầu tư phải nộp** khi thực hiện giao dịch chứng khoán phái sinh.

It licenses the *quantity*. It does not license the *name*, and it says nothing about VM.

**What would settle it.** Nothing needs settling as to the rule — it needs settling as to
**our design**, and that is the author's call:

- **(i)** Model both layers, broker-first, and let the CCP layer only produce the overnight
  top-up obligation and the suspend/restore state. (This is what the primary text describes.)
- **(ii)** Model the broker layer only, and treat the CCP as a constraint the broker
  internalises.

**Meanwhile.** Two distinct fields, always: `mr_ccp` and `mr_broker`. Never one. This is a
naming decision that must be made before any further margin code is written, because it
propagates into every test fixture.

---

### C-2. Does VM belong in the *maintenance* number, or only in settlement? — **HIGH IMPACT**

**Question.** For a VN30F account whose position moved against it during the session, does
the loss raise the number it is tested against *now*, or only become cash owed at 09h30 T+1?

**A — QĐ 26 says settlement. VERIFIED.** `biến đổi` occurs **0 times** in the QĐ 26 body and
**0 times** in `Phụ lục 2`. `Phụ lục 7` §C.I makes the daily P&L a settlement obligation:
report by **16h50**, `MT103` instructions, cash moving on **T+1**:

> Chậm nhất **16h50**, VSDC thực hiện: … – Điện **MT103** – Yêu cầu thu thanh toán của thành
> viên bù trừ lỗ, **thanh toán vào ngày T+1**…

**B — every broker says margin. VERIFIED** (MBS §1.23, VNDIRECT, and CARRIED for Pinetree,
FPTS, VCAP, SHS, VCBS): VM is an additive term in `MR`, updated in-session.

**Why both cannot hold as stated.** Under A the loss is not margin until it is cash; under B
it is margin the moment it accrues. The gap is one overnight, and in that gap the account's
tested ratio differs by the whole day's loss. For a leveraged VN30F account this is the
difference between being called and not.

**A reconciliation exists but no source states it.** Between the close and the T+1 transfer
the loss is an *unpaid receivable* of the clearing member against the client — exactly the
thing a broker would capitalise into its own maintenance numerator. VNDIRECT's *"+ **Các
nghĩa vụ khác**"* is consistent with that reading. **Registering as: not necessarily
contradictory; the label is shared and the timing is not. Do not merge.**

**What would settle it.** A broker's operational manual that states whether its intraday VM
term is reversed when the T+1 cash settles, or a VSDC member circular on the treatment of
the unpaid VM receivable.

**Meanwhile.** `mr_broker` carries a VM term with an explicit `vm_in_maintenance: bool` and
an explicit sign convention (`max(0, −pnl)` pre-KRX per S-6; **unknown** post-KRX — brokers
do not restate the loss-only condition). `mr_ccp` carries none. Both behaviours must be
runnable, because the difference is measurable and worth measuring.

---

### C-3. Are the broker ladders live rules or dead inheritance? — **HIGH IMPACT**

**Question.** VNDIRECT publishes exactly the 80/90/100 rungs QĐ 26 deleted. Is that a live
broker policy, or is it QĐ 96 text that nobody removed?

**A — the numbers are VNDIRECT's own. VERIFIED**, same URL as S-17:

> b. Các ngưỡng cảnh báo để thực hiện giám sát Tỷ lệ sử dụng Tài khoản phái sinh của Khách
> hàng **trong phiên giao dịch** như sau: Ngưỡng cảnh báo mức độ 1: **80%**; mức độ 2: **90%**;
> mức độ 3: **100%**. VNDIRECT được quyền thay đổi các ngưỡng tỷ lệ cảnh báo nêu trên vào
> **bất kỳ thời điểm nào**…

The reservation of the right to change them reads as a live commercial term.

**B — but the denominator is not VSDC's.** VNDIRECT defines the divisor as

> Tổng giá trị tài sản ròng hợp lệ = Tiền ký quỹ + Tiền gửi tại VNDIRECT – **Nghĩa vụ nợ** +
> Giá trị chứng khoán ký quỹ hợp lệ tại VNDIRECT

which is a **net-asset** measure. `QĐ 26` Điều 8's `V_KQ` is not: it adds cash to securities
**capped at `(1−0.80)×MR`** and subtracts no liabilities. Same rung numbers, different ratio.

**And a live counter-assertion that VSDC still publishes a ladder. VERIFIED**, MBS §1.30:

> 1.30 **Ngưỡng xử lý tại VSDC** là tỷ lệ cảnh báo ở cấp độ cao nhất **theo công bố của VSDC
> từng thời kỳ**. Tài khoản vi phạm tỷ lệ này sẽ bị tạm ngừng giao dịch (suspend).

**Why this may dissolve, OURS:** MBS's clause is a *forward reference* ("từng thời kỳ"), not
an assertion that a ladder exists today; and by S-7 the highest rung is arithmetically the
binary test. So MBS 1.30 is satisfiable by QĐ 26 Điều 13 with no ladder at all.
**Offered as a reconciliation, not asserted** — MBS names it a *tỷ lệ*, and QĐ 26 has none.

**What would settle it.** A VSDC operational notice post-2025-05-05 that either publishes a
`tỷ lệ sử dụng tài sản ký quỹ` threshold or states that none exists. A full-site search
returned nothing either way.

**Meanwhile.** Exchange layer: binary test only (S-7). Broker layer: ladders are config,
per firm, **with their own denominator definition** (§4).

---

### C-4. VPS contradicts VPS on the direction of its own maintenance ratio — **MEDIUM-HIGH IMPACT** *(new this session)*

**Question.** Is VPS's *"Tỷ lệ sử dụng tài sản ký quỹ duy trì"* a floor the client must stay
**above**, or a ceiling the client must stay **below**?

**A — a minimum to maintain. VERIFIED**, VPS Bộ T&C §1.13
(<https://www.vps.com.vn/> → *Bộ điều khoản và điều kiện của hợp đồng mở tài khoản chứng
khoán*, 05/2025 edition, local copy
`vps_bo-dieu-khoan-va-dieu-kien-cua-hop-dong-mo-tai-khoan-chung-khoan-viet-nam-052025-30f5.pdf`):

> 1.13 "Tỷ lệ sử dụng tài sản ký quỹ duy trì": Là **tỷ lệ tối thiểu** giữa Giá trị ký quỹ
> duy trì yêu cầu với Tổng giá trị tài sản ký quỹ hợp lệ **mà Khách hàng cần duy trì** trên
> tài khoản phái sinh.
> "Maintenance margin utilization ratio": means the **minimum ratio** … that Customer needs
> to maintain…

**B — a maximum to stay under. VERIFIED**, same document, Part E §4.4(c):

> … tất cả các biện pháp cần thiết khác để đảm bảo **tỷ lệ sử dụng tài sản ký quỹ thấp hơn
> tỷ lệ ký quỹ duy trì**.
> … to ensure that the margin utilization rate is **lower than** the maintenance margin rate.

**Why both cannot hold.** If §1.13's "minimum to maintain" were operative, §4.4(c)'s remedy
— forcing the ratio *below* it — would itself be a breach. One of the two is a drafting
error, and the bilingual text repeats the error in English, so it is not a translation slip.

**Which is almost certainly meant, OURS:** B. Utilisation is `MR / assets`; it rises with
risk; every other firm treats it as a ceiling. **But we are not repairing a counterparty's
contract.** Reported.

**What would settle it.** VPS's own margin-call notification template, or the numeric
threshold notice §1.13 delegates to (which is itself unpublished — see §3).

**Meanwhile.** VPS is not modelled. If it is added, the ladder direction must be set from
§4.4(c), and the config entry must carry a `source_defect` note.

---

### C-5. `n` in `Tỷ lệ IM = VaR × √n` is unpublished — **BLOCKS COUNTERFACTUALS, NOT BACKTESTS**

**Question.** How many days is `n`, and is `VaR` already a 2-day statistic when it is
multiplied by `√n`?

**The formula is VERIFIED** (S-1). The problem is now sharper than "the formula is missing".

**The tension, OURS.** `Phụ lục 2` §1.3.a defines `VaR` on *"tỷ lệ phần trăm biến động giá
**2 ngày** (2 days return)"* and §1.3.c defines `n` as *"số ngày cần thiết để thanh lý một
vị thế"*. If `n` is in **days** and the liquidation horizon is 2 days, then
`VaR₂ × √2` scales a 2-day statistic by another √2 — a 2-day risk charged as 4-day. If `n`
is in **2-day periods**, `n = 1` returns `VaR` unchanged. The source gives no unit.

**Order-of-magnitude check, OURS and explicitly not a claim.** `vn-exchange-rulebook-2020-2026.md`
records that at the 2022-12 recalculation *"the permissible VaR-derived band was 8.4% –
18.3%"* and the ratio was set to **17%**. `17 / 8.4 = 2.02`, i.e. `√n ≈ 2`, `n ≈ 4`. That is
suggestive and **must not be shipped as a value.** It is, however, a testable hypothesis —
see §5/**W-3**.

**What would settle it.** A VSDC methodology note, an SSC approval document for a ratio
revision (these exist — the 2022-12-12 notice cites SSC agreement), or a member circular.

**Meanwhile.** **Do not derive the ratio.** VSDC publishes it (0.17 for VN30/VN100 across
the entire KRX era, 18 revisions sampled). `scenario_margin.py::parametric_var` exists to
*check* a series, not to replace the published ratio, and its docstring says so. The gap
blocks only stress scenarios in which we ask "what ratio would this regime have produced".

---

### C-6. Which afternoon checkpoint: 14h00 or 14h30? — **LOW-MEDIUM IMPACT**

**A. VERIFIED**, `QĐ 26` Điều 13.2.b: *"**Tại thời điểm 14h00**: VSDC kiểm tra giá trị tài
sản ký quỹ trên tất cả các tài khoản vi phạm…"*

**B. CARRIED**, Pinetree (a KRX-native broker), 2025: *"VSDC kiểm sát trị ký quỹ vào thời
điểm 09h30 và **14h30**"*.

**Why B is weak.** The same Pinetree page inverts an inequality — *"Nếu TK đủ ký quỹ (MR >
hoặc = tài sản ký quỹ)"* — which is backwards. Its reliability on this point is low.
**We are not repairing it.**

**Impact.** This is the *restore* checkpoint. It changes only how long a suspended account
stays suspended after it has already paid. It cannot change whether a call fires.

**What would settle it.** A second broker or a VSDC operational notice naming the afternoon
sweep.

**Meanwhile.** `14h00`, from the signed instrument. Already implemented that way.

---

### C-7. Margin-requirement notification: 16h30 or 17h00? — **LOW IMPACT**

**A. VERIFIED**, `QĐ 26` Điều 13.1: *"**Chậm nhất 16h30** ngày giao dịch, VSDC xác định giá
trị ký quỹ yêu cầu … và **gửi điện thông báo** cho thành viên bù trừ."*

**B. VERIFIED**, `Phụ lục 7` mục A.3: *"**Chậm nhất 17h00**, VSDC sẽ lập và gửi thành viên
bù trừ **Báo cáo giá trị ký quỹ yêu cầu (Mẫu 04/PLPS-TTBT)** dưới dạng FileAct kèm với **điện
MT598** mô tả báo cáo."*

**Why not simply both.** They may be two artefacts — an MT598 wire at 16h30 and a FileAct
report at 17h00. But A's text explicitly includes *"gửi điện thông báo"* at 16h30 and B's
explicitly includes *"điện MT598"* at 17h00, and **the rulebook never distinguishes them**.
Same wire, two deadlines, as written.

**What would settle it.** The `Mẫu 04/PLPS-TTBT` specification, or a member operations
manual. `Phụ lục 8` confirms `Mẫu 04` is a FileAct artefact but says nothing about timing.

**Meanwhile.** Model the broker as learning `MR` at **17h00** (the later of the two), which
is conservative for any "did the broker have time to call the client" question. The top-up
deadline (09h30 T+1) is unaffected.

---

### C-8. Is `P` in `MM = P × MF` gross or net, and does it net within an expiry month? — **LOW IMPACT for VN30F**

**A. VERIFIED**, `Phụ lục 2` §5.1: *"P: **Số dư vị thế HĐTL cuối ngày**"* — no gross/net
qualifier.

**B. REPORTED**, TCBS's worked example computes `250,000` on 30 long + 20 short = **50
contracts, gross**, across two expiry months.

**Unsettled sub-question.** TCBS's legs are in *different* months, so the example does not
test whether a long and a short in the **same** month net. `Phụ lục 2` §5.2 scopes `MF`
*"cho một tháng đáo hạn"*, so the correct assembly is a sum over expiry months each with its
own `MF` — but within a month the reading is open.

**Why impact is low, OURS.** At `S = 1300`, `MF = 5,000đ` versus `Rm` per contract of
`0.17 × 1300 × 100,000 = 22,100,000đ` — a factor of **4,420**. `MM` binds only when
`Rm + Sm < MM`, i.e. only for a book that is simultaneously delta-flat *and* spread-flat.
It is a rounding term for any live VN30F position.

**What would settle it.** A second broker's worked example with same-month offsetting legs.

**Meanwhile.** Gross, per `INFERENCES['I9']`, with the rationale that a close-out cost scales
with the legs to unwind. Unchanged.

---

### C-9. `Ký quỹ FSP` — a broker-published component with no VSDC counterpart — **ZERO IMPACT for VN30F**

Settled as to index futures (S-4): TCBS scopes it out itself, and QĐ 26 does not contain it.

**Open as to what it is.** Two brokers independently list four components where the appendix
lists three. Whether `Ký quỹ FSP` is a KRX system field with no rulebook basis, or a
component of a VSDC parameter table we have never seen (§3), is unknown.

**What would settle it.** The scenario/parameter table TCBS defers to (*"theo bảng VSD cung
cấp"*), or a VSDC member circular on KRX-era margin fields.

**Meanwhile.** `fsp_margin = 0`, documented, non-blocking. **Flagged** because a component
appearing in broker systems but in no rulebook is exactly the shape of a rule we have missed.

---

### C-10. 21 scenarios or 42? — **PROVABLY ZERO IMPACT for futures**

Fully stated at S-15. Restated here so the conflict register is complete: `Phụ lục 2` says
**21**, TCBS says **42** while its own parameter range and its own worked table say **21**.
TCBS is self-inconsistent, so this is not even a clean A-vs-B.

**Why it cannot matter, OURS.** `Lk` is affine in `Sk`; the max of an affine function on a
finite set is at an extreme point; intermediate scenarios cannot bind.

**What would settle it.** The VSD parameter table TCBS cites. It is not published.

**Meanwhile.** 21, with `INFERENCES['I1']` (the `k` reconstruction) doing the load-bearing
work. Revisit only if listed options ever appear.

---

### Conflicts confirmed DISSOLVED this session

Recorded so they are not re-opened:

| Was | Now |
|---|---|
| OA placement — inside or outside the sum | **Dissolved.** Algebraically identical; and `OA = 0` for index futures by primary text (S-3) |
| 120 vs 250 day VaR window | **Dissolved.** Both minima; 250 binds and is the index-scoped clause (S-14) |
| Was `MR = IM + VM` replaced or does it coexist | **Settled.** Replaced wholesale — composition, timing and price basis all changed (S-5). What coexists is a *broker* quantity sharing the name (C-1) |
| Is there a VSDC ladder | **Settled and reframed.** There was; its top rung survives as the binary test; its lower rungs were informational and are gone (S-7) |
| `Phụ lục 8` missing | **Dissolved.** Obtained; it is the wrong document and the cross-reference is a defect (S-10) |
| `Phụ lục 2` §1.3.c formula missing | **Dissolved.** Extraction artefact; formula recovered (S-1) |
| `QĐ 26` Điều 8 `V_KQ` formula missing | **Dissolved.** Extraction artefact; formula recovered (S-2) |
| `Phụ lục 6` unobtained | **Dissolved.** Obtained (S-9) |

---

## §3. STILL MISSING

Seven items. `Phụ lục 8` is **not** among them and has been removed (S-10).

| # | Document / datum | What it would settle | How close we got |
|---|---|---|---|
| M-1 | **`n`**, the liquidation-day count | Closes `Tỷ lệ IM = VaR × √n` and makes the IM ratio reproducible from index history — the last piece of the CCP engine (C-5) | The formula is now in hand; `n` appears in no VSDC decision, notice or appendix. Empirically recoverable — §5/**W-3** |
| M-2 | **The VSDC scenario / margin parameter table** ("bảng VSD cung cấp", TCBS) | Would settle 21-vs-42 (C-10) and probably explain `Ký quỹ FSP` (C-9) | Cited by name by a clearing member; never located on vsdc.vn |
| M-3 | **`SMrate` time series**, and `MF` as VSDC actually applies it | `Sm` is currently unimplementable against real data; `MF` is derived (S-11), not observed | The *method* is fully in hand (`Phụ lục 2` §3.3 + `Phụ lục 6` for the DSP inputs). What is missing is a **DSP series by expiry month**, which is a data-acquisition problem, not a documentation one |
| M-4 | **The eligible-collateral list with per-name haircuts** | The second operand of `V_KQ` (S-2). Without it, securities collateral cannot be valued for any specific holding | `QĐ 26` Điều 6 khoản 3 **requires** publication *"định kỳ 6 tháng/lần"*; a full-site VSDC search returns zero such articles. This is a compliance gap at VSDC, not a search failure |
| M-5 | **`Psr` and the underlying-asset group definitions** | `OA` for a VN30 + VN100 book. Irrelevant while only VN30F is traded | One broker snapshot (CARRIED: `Psr = 0.85`, scale factors 1 / 1.03 for {VN30, VN100} from 10/10/2025). No VSDC publication found |
| M-6 | **Broker threshold notices** at MBS, VPS, KIS, BSC, Mirae | The actual ladder numbers for five clearing members | **This is worse than "not found".** The contracts *structurally delegate* the numbers. KIS Điều 5 names three warning levels and gives no percentages; MBS §1.28–1.32 defines five named ratios each *"do MBS quy định từng thời kỳ"*; VPS §1.19 makes the thresholds *"được VPS quy định trong từng thời kỳ"*. The numbers live in a separate notice that is not on the public site |
| M-7 | **A VSDC operational notice on the afternoon sweep** and on the 16h30/17h00 wire | C-6 and C-7 | Neither found |

**The standing constraint is unchanged, and this session strengthened it in one direction
and weakened it in another.** Two of the four "cannot reproduce" formulas turned out to be
in hand all along (S-1, S-2), and `Phụ lục 6` closed a third gap (S-9). What remains
irreducible is **`n`**, the **parameter tables**, and the **DSP/collateral series** — the
last two being data, not text. **The VSDC margin engine still cannot be reproduced end to
end from public data**, and the exchange-side margin outputs must stay labelled provisional.

---

## §4. THE LADDER SHAPES — design brief for the broker config

Every convention found, and what the config object must be able to express.

### 4.1 The conventions

| Firm | Ratio | Direction | Rungs | Action semantics | Tag |
|---|---|---|---|---|---|
| **VSDC (QĐ 26)** | `V_KQ` vs `MR` — a **level test, not a ratio** | n/a | one: `V_KQ < MR` | suspend at 09h30; restore at 14h00 / 16h30; 03 working days to substitute-member close-out | VERIFIED |
| **VSDC (QĐ 96/61/12)** | `MR / V_KQ` | rising | 80 / 90 / 100 | 1–2 **notification only**; 3 suspend + close-out | VERIFIED |
| **TCBS** | `Tỷ lệ sử dụng tài sản` | rising | duy trì **85**, cảnh báo **87**, xử lý **90**; withdrawal only if post-withdrawal ≤ **80** | **level-targeting**: both 87 and 90 act *"để đưa Tỷ lệ sử dụng tài sản về Tỷ lệ duy trì"* (85). Post-VSDC-breach support disburses to **95** | REPORTED |
| **VNDIRECT** | `MR / **net** assets` | rising | 80 / 90 / 100 | thresholds changeable *"vào bất kỳ thời điểm nào"*. IM ratio **17.5%** | VERIFIED |
| **MBS** | `AR = (MR / V_KQ) × 100%` | rising | **five named ratios**, all numerically delegated: `AR duy trì`, `AR xử lý`, `Ngưỡng xử lý tại VSDC`, `tỷ lệ sau mở vị thế`, `tỷ lệ sau rút` | `AR xử lý` acts *"để đảm bảo AR duy trì"* — **level-targeting** | VERIFIED (structure), numbers missing |
| **KIS** | `Tỷ lệ sử dụng tài sản ký quỹ` (§1.9) | rising | three levels, **no numbers** | 1: no new positions, *no notification obligation*; 2: restore to below level 1 within a deadline KIS sets; 3: immediate partial/full close-out **without prior notice** | VERIFIED (structure) |
| **VPS** | `MR / V_KQ` (§1.12) | **contradicts itself** (C-4) | delegated | margin call is a **right, not a duty**: *"VPS có quyền (nhưng không có nghĩa vụ) gửi thông báo lệnh gọi ký quỹ bổ sung"* | VERIFIED |
| **HSC** | coverage ratio | **falling** | 100 / 80 / 60; and `MM = Tỷ lệ MM × IM`, `tỷ lệ MM = 80%` | inverted: lower is worse | CARRIED |
| **SSI** | utilisation | rising | 85 / 90 / 95; **75 / 80 / 85 for foreign investors** | — | CARRIED |
| **Pinetree** | utilisation | rising | live page 80 / 90 / 95 targeting ≤80; 2024-07-11 page 75 / 85 / 90 targeting <75 | level-targeting | CARRIED |
| **VCBS** | utilisation | rising | — | *"Tỷ lệ ký quỹ tối thiểu bằng tiền: **100%**"*, yet its own ratio formula adds *"Giá trị CKKQ hợp lệ tầng DTA"* to the denominator — **self-contradictory** | CARRIED |
| **ACBS** | — | — | — | *"Tỷ lệ tiền giữ lại tối thiểu tại ACBS là **5%**"* — a fee/tax/VM reserve entering buying power as `×(1+5%)`. **Not a ladder at all** | CARRIED |

### 4.2 What the config object must express

Five axes, not one. A `{warn, call, liquidate}` triple of percentages is **insufficient** and
will silently mis-model at least four of the firms above.

1. **Direction.** `rising_utilisation` (`MR/assets`, higher is worse) **and**
   `falling_coverage` (HSC, lower is worse). A sign flag, applied everywhere the ratio is
   compared.

2. **Denominator definition — per firm, not global.** At least four in evidence:
   - `V_KQ` per `QĐ 26` Điều 8 (cash + securities capped at `(1−0.80)×MR`) — MBS;
   - **net assets** `cash + deposits − liabilities + securities` — VNDIRECT;
   - **cash only** (`tỷ lệ ký quỹ bằng tiền = 100%`) — VCBS as stated;
   - `V_KQ` with an additional **DTA-tier** securities term — VCBS as computed.
   These produce materially different ratios on identical positions. **This is the single
   most commonly-missed field.**

3. **Action semantics — fire vs target.** TCBS, MBS and Pinetree do not merely *trigger* at
   a rung; they liquidate **until the ratio reaches a named target level** (85 for TCBS, `AR
   duy trì` for MBS). A boolean trigger cannot express this. The config needs
   `action: {none, block_opening, notify, liquidate}` plus `target_ratio: Optional[Decimal]`.
   With `target_ratio` set, the liquidation loop is "close positions until ratio ≤ target",
   which is a *different quantity of forced selling* from "close enough to clear the rung".

4. **Notification obligation.** KIS §5.1 disclaims it (*"KIS không có trách nhiệm thông báo"*),
   KIS §5.3 disclaims it for liquidation (*"không cần có bất kỳ thông báo trước"*), VPS makes
   it a right not a duty. A model with a mandatory client-notice step and a cure window will
   over-state survival at these firms. Needs `notice_required: bool`, `cure_window`.

5. **Publication status.** `numbers_published: bool`. Five clearing members structurally
   delegate their numbers (M-6). A config that silently defaults them to someone else's
   values will produce confident, wrong margin-call incidence.

### 4.3 Conventions that none of the three shapes covers — stated plainly, as asked

Two, and they are real.

- **VPS's `Tỷ lệ an toàn` (§1.14):** *"là tỷ lệ do VPS xác định dựa trên **giá trị tài sản
  ròng** của Khách hàng nhằm đánh giá mức độ an toàn của tài khoản CKPS."* §1.19 makes it a
  **warning-threshold dimension in its own right**, alongside utilisation and position limits.
  It is neither a utilisation ratio nor a coverage ratio: its numerator is net asset value,
  not a margin requirement. **Its formula is not published.** A config expressing only
  rising-utilisation and falling-coverage cannot represent it. Recommend a
  `additional_ratios: list[NamedRatio]` escape hatch rather than forcing it into the ladder.

- **ACBS's retained-cash multiplier:** a `×(1 + 5%)` reserve on buying power, not a threshold
  on any ratio. It reduces the position a given balance can open, which changes *when* the
  account reaches a rung without being a rung. Belongs in a `buying_power` model, not the
  ladder.

Also flag, per §2/**C-8** of the prior evidence pack (**D-28**): `QĐ 26` Điều 8's `x = 80%`
(a **cap on securities collateral**), VCBS's 100% (a **collateral-eligibility rule**), and
ACBS's 5% (a **fee reserve**) are three different concepts under similar names. **Do not
merge them into one field.**

### 4.4 Repo actions

- `docs/reference/vn-exchange-rulebook-2020-2026.md:667` records Pinetree as 75/85/90
  targeting "below 75%", dated 2024-07-11. Pinetree's live page gives 80/90/95 targeting
  ≤80%. **Date the row and mark it superseded; do not overwrite** — no source establishes
  when the change happened.
- Same file, line 1405 (`Broker margin utilisation thresholds — derivatives`) lists Pinetree
  as the exemplar with `medium` confidence. Add VNDIRECT's 80/90/100 with its **net-asset
  denominator** as a second row, `high`, since it is VERIFIED and it demonstrates that the
  denominator varies.
- `src/plutus/market/margin.py::BrokerTerms` needs the five fields of §4.2 plus the
  independent `initial_margin_ratio` of S-17.

---

## §5. WHAT TO IMPLEMENT NEXT

Ordered. Each states why it is safe to build **now**.

---

### W-1. Implement `V_KQ` — the collateral valuation formula

`V_KQ = C + min((1 − 0.80) × MR ; Σ Q × P × (1 − H))`, `H ∈ {5%, 30%, 40%}`, `P` = *giá tham
chiếu cho ngày giao dịch liền sau*.

**Safe because** the formula is VERIFIED from the signed source (S-2), every variable is
glossed in the same article, and the haircut tiers are in Điều 9. It is the **other half of
the only CCP margin test there is**, and it is currently a hand-supplied scalar.

**Caveat to encode, not to resolve:** the per-name eligible-collateral list is unpublished
(M-4). Implement the formula; take the eligible set and per-name haircut as required inputs
with no default. A cash-only account (the VN30F base case) needs neither.

**File:** `src/plutus/market/session/scenario_margin.py`, new `valid_margin_assets`. Retire
`SOURCE_DEFECTS['D3']`.

---

### W-2. Split `MR` into `mr_ccp` and `mr_broker` throughout

**Safe because** it is a pure renaming plus a type split; it commits to no numbers; and it is
a **precondition** for C-1 and C-2, both of which change behaviour. Doing it after any
further margin code is written costs more.

Encode alongside it, from primary text: `mr_ccp` is post-close and priced on the **index
close**; `mr_broker` is intraday and priced on the **futures price**; they coincide in form
for a one-directional single-expiry book and differ by the basis (S-12).

**Files:** `src/plutus/market/margin.py`, `src/plutus/market/exchanges/derivatives.py`,
`src/plutus/market/session/scenario_margin.py`, and their tests.

---

### W-3. Back `n` out empirically from the published ratio series

A **measurement**, not an assumption, and therefore safe.

We have: the VN30 index history in the corpus; VSDC's published ratio and its effective
dates (recalculated on the 1st, 10th and 20th, published ≥2 working days ahead — `QĐ 26`
Điều 5.1.1.b, VERIFIED); and now the exact formula `Tỷ lệ IM = VaR × √n` with
`VaR = mean + 3δ` on overlapping 2-day returns over a window `≥ 250` days (S-1, S-14).

For each recalculation date, compute `VaR` and solve `√n = ratio / VaR`.

- If `n` lands on a **stable integer**, we have recovered an unpublished CCP parameter from
  public data. That is a publishable result in its own right.
- If it does **not**, we have shown the published ratio is not the formula's raw output —
  which is already suggested by the ratio sitting at **0.17 unchanged across 18 revisions**
  while the index vol certainly moved. In that case the deliverable is the *band* the ratio
  is administratively held within, which is exactly what the 2022-12 record hints at
  (`8.4% – 18.3%`).

Either outcome is a finding. **Neither licenses shipping a value for `n`.**

**Files:** a measurement under `measurements/`, using
`scenario_margin.py::parametric_var` and `two_day_returns`, which already exist for exactly
this purpose.

---

### W-4. Re-tag the defect and inference registers against the signed source

**Safe because** it is documentation of what was read, with no behavioural change.

| Id | Action |
|---|---|
| `D1` (missing `k`) | Re-tag: **defect in the signed instrument**, not the extraction. Raises the stakes on `I1` |
| `D2` (VaR→ratio absent) | **Retire.** Replace with: formula is `Tỷ lệ IM = VaR × √n`; `n` unpublished |
| `D3` (`V_KQ` absent) | **Retire.** Formula recovered |
| `D13` (two khoản 3, dangling `điểm a khoản 1`) | Re-tag: **confirmed in the signed instrument** |
| `D14` (120 vs 250) | Keep; add that (b) is the index-scoped clause and therefore operative |
| `D15` **(new)** | `Phụ lục 2` §4.2 cross-refers to `Phụ lục 8` for the CTD method; `Phụ lục 8` is the electronic-document register; the method is in `Phụ lục 6` §3, which itself has two sections numbered 3 |
| `I4` (OA) | Narrow: direction is now VERIFIED (`QĐ 26` Điều 5.1.1.a). Level and zero-floor remain OURS |
| `I13` (`n`) | Rewrite: the `√(n/2)` alternative is excluded; the open question is the **unit** of `n` (days vs 2-day periods), per C-5 |
| `I21` (suspend at 09h30 only) | Confirmed against the signed `.docx`. Keep as an inference — it is still a reading of which action attaches to which checkpoint |

Also correct the three prose claims: `post-krx-margin-spec.md` §4.3 title, §6.3's boxed
SILENT note (retire — `Phụ lục 6` obtained), and §7.3's title (`Phụ lục 8` is not missing).

---

### W-5. Replace the exchange-layer ladder with the binary test

`src/plutus/market/exchanges/derivatives.py:115` and `src/plutus/market/margin.py:11–12, 75,
161` describe the exchange as running an 80/90/100 ladder. **It does not, and it never
usefully did** (S-7).

Post-KRX: one test, `V_KQ < MR`, at 09h30 (suspend) / 14h00 (restore) / 16h30 (restore),
top-up by 09h30 T+1, 03 working days to substitute-member close-out.

Pre-KRX: keep the ladder object, but type rungs 1 and 2 as **notification-only** — they must
not gate trading or trigger liquidation, because `QĐ 96`/`61`/`12` Điều 13 khoản 2 gives them
no consequence.

**Safe because** both regimes are now VERIFIED from signed instruments, and the change makes
the exchange layer *simpler*, removing two parameters rather than adding any.

---

### W-6. Build the broker ladder config to the five-axis shape of §4.2

**Safe because** it is a schema, and a schema that refuses to default missing numbers cannot
produce a confident wrong answer. Populate only the firms whose numbers are VERIFIED or
REPORTED with a URL — VNDIRECT and TCBS today. Leave MBS, VPS, KIS, BSC and Mirae as
structure-only entries with `numbers_published = False`, so any run that selects them fails
loudly rather than borrowing someone else's ladder.

---

### W-7. Do **not** yet build: `Sm`, `OA`, `Dm`

- `Sm` — the method is complete (`Phụ lục 2` §3.3 + `Phụ lục 6` DSP construction) but needs a
  **DSP series by expiry month** we do not have (M-3). Building the code before the data
  produces an untestable component.
- `OA` — correctly **zero** for any VN30-only account by primary text (S-3). Building it
  cannot change a VN30F result.
- `Dm` — TPCP only. `Phụ lục 6` §3 now supplies the CTD method that was thought missing, so
  it is *unblocked* — but it is out of scope for index futures and the `E+2` hole
  (`SOURCE_DEFECTS['D10']`) remains open.

**Stated explicitly because** the temptation after recovering `Phụ lục 6` is to build the
delivery-margin chain. It is unblocked and still not worth building.

---

## §6. What surprised us

Recorded because it changes how the next document should be researched.

1. **Two of the four "missing formula" defects were never missing.** They are Word equation
   objects. Every text pipeline drops them silently, leaving a paragraph that *reads* as
   complete. `Phụ lục 6`'s theoretical-price formula is worse still — it is a **PNG image**.
   Anyone sourcing QĐ 26 from a text scrape loses three formulas and does not notice.

2. **`Phụ lục 8` was never missing either; the rulebook simply points at the wrong appendix.**
   A whole section of `post-krx-margin-spec.md` was built on a documented absence that was
   actually a cross-reference error.

3. **The 80/90/100 ladder never did anything at rungs 1 and 2.** The received story — a
   three-level CCP ladder that QĐ 26 abolished — is wrong in both directions: the lower rungs
   were pure notifications, and the top rung survives verbatim as the binary test. Nothing
   substantive changed at the cutover in this respect.

4. **VNDIRECT charges a *higher* initial-margin ratio than VSDC and publishes it** (17.5% vs
   17%, 2.8% vs 2.5%), and computes its ladder on a **net-asset denominator** that is not
   `V_KQ`. The two-layer model is not a modelling convenience; it is visible in the tape.

5. **Five clearing members structurally delegate their thresholds.** KIS's contract names
   three warning levels and states no percentage anywhere; MBS defines five ratios each *"do
   MBS quy định từng thời kỳ"*. The numbers are not hidden — they are contractually
   elsewhere. No amount of searching the public site will produce them.

6. **VPS's own bilingual contract contradicts itself on whether its maintenance utilisation
   ratio is a floor or a ceiling**, in both languages. New, and not repaired here.

7. **The `k`-less scenario formula is in the signed instrument.** It was worth checking: three
   sibling defects dissolved on inspection and this one did not. The whole scenario model
   rests on a reconstruction of a defective line in a signed rulebook, and that fact should
   be stated wherever `Rm` is reported.
