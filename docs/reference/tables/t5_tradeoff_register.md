# T5 -- Tradeoff register

Every deliberate simplification the library keeps and discloses: what it buys,
the fidelity it gives up, the measured cost where one has been measured, and the
condition that should make us revisit it. Sourced from
`docs/reference/PUBLISH-CHECKLIST.md` and
`docs/superpowers/specs/2026-08-29-paper-material-prep-design.md`; measured costs
are quoted from those documents and from the committed figure data
(`figures/f3_cross_policy_divergence.json`), never invented.

Two axes run through the table and must not be conflated (design spec §1.2): a
**resolution limit** is what no amount of additional data can fix (a daily bar
cannot see intraday fill existence) and its share *falls* as resolution gets
finer; a **data ceiling** is what a fuller feed would fix (a reconstructed
3-level book cannot see the queue) -- we own it and name it because we are not
the exchange.

| # | Simplification | What it buys | Fidelity given up | Measured cost (where one exists) | Revisit trigger |
|---|---|---|---|---|---|
| 1 | **Auction cross = the published open (ATO) / close (ATC)**, not a cross derived from the book (QĐ 352 Điều 6.2(a)). | Auction-window tick data is untrustworthy and the published open/close are already stored, so the cross is deterministic and defensible without trusting bad intra-auction ticks. | Not the book-derived cross; the published close is *our modelling choice*, not a sourced ATC rule, and Vietnamese regulation defines no opening price at all, so the ATO input is a vendor construct. | **None, deliberately.** A stated approximation, not a rule to validate against ticks -- "there is no auction measurement here and none is owed." | A trustworthy intra-auction feed or a book snapshot at the cross; then derive via Điều 6.2(a). |
| 2 | **Close-as-settlement fallback** -- substitute the day's close for an absent settlement / mark price. | Graceful degradation for users who lack settlement prices; the run proceeds and flags its own substitution via `provenance()`. | Close ≠ settlement price, on expiry *and* on ordinary daily marks. | **46 expiries, 0.042% mean-abs error** -- dropped from the paper: our own runs supply real settlement prices, so they never invoke it. | Never invoked when real settlement prices are supplied; retained only as a self-flagging feature. |
| 3 | **Default weekday-only settlement calendar (UNSOURCED)** when the caller names none -- empty holiday set. | A run needs no calendar input; the correct data-derived calendar is available but caller-supplied, not the default. | Every Tết and every other exchange closure is counted as a settlement day (VSDC works only the days the market trades). | A **2026-02-12 trade answers T+2 = 2026-02-16 where VSDC settled 2026-02-23 -- five counted days the depository was shut.** | Make the data-derived calendar the default, or make an unnamed calendar `raise`; `provenance()` reports `settlement_calendar_id = weekday-only-UNSOURCED`. |
| 4 | **Bar-resolution fill: the order fills at its own limit under a no-impact replay, and fill *existence* is unobservable** (`FILL_UNOBSERVABLE_AT_RESOLUTION`). | The only non-arbitrary fill price when the replay cannot move the market; bar-resolution runs proceed and state the unknowability rather than guessing. | Cannot establish whether *this* order filled -- time priority decides it, there are no order IDs, and 81% of best-quote changes carry no trade. A **resolution limit**, not a missing field. | Reported as the INDETERMINATE-by-cause rate (**F2**); the honest floor a bar run reports, whose share *falls* only as resolution gets finer, never as data gets more complete. | Run at tick resolution -- F2 runs the *same* population at both rungs to measure the dependence. |
| 5 | **Reconstructed 3-level book, not the exchange's full order book** (all levels / order IDs / true queue / deletions). | The best data actually held (production tick + reconstructed 3-level book *with sizes*); enables the order-book walk and maker/taker classification to level 3. | No queue position; no depth past level 3; the two sides are never observed together (reconstructed, not observed); **no deletion record**, so "the book is empty" is inexpressible. A **data ceiling** -- we are not the exchange. | `cross_side_skew` rides every reconstructed book: **FPT median 8.3 s (max 529 s), HTV median 584.9 s (max 3.8 h); 53 of 203 instants coincide** on FPT 2022-11-09. | Obtain a fuller book. The genuine ceiling is **deletions**; sizes are a *fetch*, not a limit (the corpus carries 1,390,914 size rows; production 666M/590M). |
| 6 | **A declared queue assumption (optimistic / conservative / probabilistic)** rather than recovering our own queue *rank*. | The book-walk produces maker fills without the true queue; the assumption is explicit and swept, not hidden. | Our own queue rank is unrecoverable from a reconstructed book (distinct from the *declared* queue axis reported in F3). | **F3 queue axis: maker-share spread ≈19%** across arms (optimistic 152,600 vs conservative 123,700 maker shares), each arm carrying its own indeterminate rate. | A full order book with order IDs. |
| 7 | **The fill-policy family (soft / hard / probabilistic) is a swept axis, not a single truth** -- the spread is the reported result. | The result's sensitivity to the fill assumption is made visible instead of hidden behind one arm. | There is no single "correct" fill at bar/soft resolution; Hard returns INDETERMINATE where Soft fills on a touch. | **F3 fill axis: S1 returns −75.5% under soft vs 0% under hard/probabilistic** (which decline to trade and carry a 0.5 indeterminate rate). | Binding guardrail: always report the spread across arms, **never a single arm's P&L**. |
| 8 | **Daily variation margin is cash-settled for both regimes** (pre- and post-KRX alike). | One consistent daily cash-settlement mechanic across the KRX cutover; realised P&L reaches the deposit every day (MUST #4). | Both regimes are cash-settled by the same rule -- VSDC "index futures daily variation margin T+1" is cited for both and QĐ 26 Điều 20 for post-KRX; an author's decision, not two separately-sourced cadences. | None as an error; the fix **removed the frozen-balance defect** (deposit frozen at 99,948,008đ for 18 sessions). | If the pre-KRX daily cash-settlement cadence is shown to differ from the post-KRX rule. |
| 9 | **Margin modelled with no maintenance ratio, regime-split** -- pre-KRX IM+VM on the dated IM series (10→13→17%), post-KRX scenario margin. | Matches the two *real* Vietnamese regimes instead of a disavowed maintenance-ratio test (no VN regime has a maintenance ratio). | The retired `ratio < 0.17` "utilisation" incidence is gone; the post-KRX scenario margin is wired but cannot compute without broker parameters. | The retired path reported **12.60%** off a maintenance ratio that does not exist in either regime; post-KRX needs **SSI/TCBS SMrate 0.87% and MF 5,000đ/contract** to compute. | Ship `SMrate`/`MF`; exercise the post-KRX scenario margin (only ~55% of its lines run under any test). |
| 10 | **Position-limit ladder (80/90/100) primary-sourced but not applied; individual tier only.** | Avoids enforcing a warning ladder whose broker levels are commercial terms; Tier 1 runs the individual tier without asking the caller. | The 80/90/100 position-limit ladder and the institution / professional tiers (10,000 / 20,000 contracts) are not applied. | None. | Apply the ladder / model institutional accounts. |
| 11 | **Foreign-ownership room absent** (declarable tradeoff T1). | Avoids modelling a foreign-room feed the corpus does not carry. | Foreign-ownership-limit blocks -- a thing a Vietnamese trader would notice -- are not enforced. | None. | Wire a foreign-room feed. |
| 12 | **Data posture: minimal shipped fixtures, not a corpus; headline numbers on best-available production data, provenance-tagged (two-tier reproducibility).** | A third party can `clone → pip install → pytest` the Jx/Sx suites (the reproducible core) with no redistributed data; the library's proof does not rest on data we cannot share. | Data is the weakest link and is *not* claimed as a contribution; the larger measurement numbers run on production data that is not redistributed (regenerated from a documented, provenance-tagged path, not by third parties). | None (a positioning choice): dropped the corpus-scale boast (2.5M rows / 1,725 tickers) and the off-grid-UPCoM headline rather than defend them. | If a shareable higher-fidelity corpus becomes available (vnstock / brokerages already provide better). |

## Other declarable absences (measured cost: none; honest to state)

Config variants and charge line-items a release may declare rather than model
(PUBLISH-CHECKLIST "DECLARABLE"; `FEATURES.md` §16 has the full list with
reasons): short selling (not permitted for Vietnamese equities anyway) · VAT ·
dividend withholding tax · interest-accrual pass · intraday margin checkpoints
(09h30 / 14h00 / 16h30) · VSDC collateral-management fee · government-bond
futures (deferred by author decision) · event-driven callbacks.

## Standing threats to watch (design spec §8)

These are not simplifications but process risks the writer should keep in view:

- **W1 reverses a declared Tier-1 non-goal** (daily cash mark-to-market),
  deliberately, per "model correctly"; the reversal must stay reflected in the
  `deposit.py` docstrings and `FEATURES.md` or the docs contradict the code.
- **The margin population and window shape the incidence** (which VN30F
  contracts, hold length); pick a defensible, documented population, not one
  tuned to a number.
- **Production-data access is read-only** (`algotradeDB`); the post-KRX margin
  and any post-2022 slice regenerate from it but must never write to it.

*Sources: `docs/reference/PUBLISH-CHECKLIST.md` (MUST / RESOLVED / SHOULD /
DECLARABLE / "THE AUCTION FILL"), `docs/superpowers/specs/2026-08-29-paper-material-prep-design.md`
(§1–§3, §8, W0–W7), and `figures/f3_cross_policy_divergence.json` for the F3
divergence figures.*
