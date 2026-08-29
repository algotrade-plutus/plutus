# Publish checklist

What must be true before this ships as something a researcher can point an algorithm at
and trust. Kept short on purpose: the full inventory is `FEATURES.md`, and this is only
the subset that blocks a release.

Status as of 2026-08-27. Suite: **2,432 passing, 17 failing** — measured, not quoted. All 17
failures are in `tests/datahub/test_cli.py` and all are the same environment artefact: the
CLI tests spawn `python -m plutus.datahub` as a subprocess and the child cannot import
`plutus` (`ModuleNotFoundError: No module named 'plutus'`). `tests/market` is green. Do not
write "suite green" unqualified while those 17 stand — write the number.

**The MUST numbers below are frozen.** `SCENARIO-CATALOGUE.md` cites "must-list item 3" and
"item 4" by number in eight places, so a landed item keeps its row and its number and gains
a pointer to RESOLVED rather than being deleted and the rest renumbered.

**A number is an identity, not a rank.** Because the numbers are frozen, the rows are ordered
by *fix priority* and the `#` column no longer runs in sequence. Item **5** sits above items 3
and 4 on purpose; the reasoning is stated under the table. Nothing was renumbered.

---

## MUST — blocks publication

| # | Item | Why it blocks | State |
|---|---|---|---|
| 1 | **Order-book walk** | Without it, fills happen at a single price with no depth. The fidelity audit's verdict on that state: *"an excellent accounting engine attached to an execution model that is not a simulation of a market."* A user would be validating their strategy's accounting, not its executability. | **LANDED 2026-08-27, commit `c6b7ef6`.** Number kept, reasoning moved to RESOLVED. Two residuals, both stated there and neither of them "no depth". |
| 2 | **Amendment re-runs encumbrance and admission** | `ExchangeSession.amend` exists. **This row's citation was wrong and is corrected here.** QĐ 352 **Điều 21 is the lunch break** (rulebook `:147`, high); **Điều 21.3 is VNX QĐ 22/2025's** article (rulebook `:223`, high), not QĐ 352's. Three dated rules are actually in play. (a) **Auction lock** — no amend, no cancel of LO/ATO/ATC while an auction runs, unchanged 2020-01-01 → current: QĐ 352 Điều 17.1; VNX QĐ 17 Điều 22; QĐ 22/2025 Điều 21 (rulebook `:216`, **high**). Implemented, in `orders.amend_cancel_lock`. (b) **Priority-preserving amendment begins 2022-03-31**, under VNX QĐ 17 Điều 22.3, and only for a pure quantity *decrease* (rulebook `:221`, **high**). Before that date HOSE had **none at all** — amendment *was* cancel-and-re-enter and time priority always restarted (QĐ 352 Điều **17.1–17.3**, read verbatim, rulebook `:220`, **high**). The rulebook further records an unresolved CONFLICT for HOSE 2022-03-31 → 2025-05-04 and adopts *"permitted by QĐ 17, not implemented by the legacy HOSE engine"* (rulebook `:222`, **medium**). (c) **Price XOR quantity from 2025-05-05** — VNX QĐ 22/2025 Điều 21.3 (rulebook `:223`, **high**). | **LANDED 2026-08-27.** `ExchangeSession.amend` now re-runs admission and funding. Against the amended order it re-checks the dated round-lot and size cap, the dated tick, and the band; then it releases the old reservation and takes a fresh one, so an **amend-up grows the reservation** (measured 70M → 105M in `scenarios/test_j27_amend.py`) or is refused `INSUFFICIENT_CASH`, a **price amendment** is re-admitted against the band, and a **decrease onto an odd lot** (1500 → 50 on HOSE after 2021-01-04) is refused `ROUND_LOT`. Any refusal restores the original reservation and leaves the order unchanged. Gap (ii) is closed too: `_priority_preserving_at(ts, venue)` returns `False` for HOSE before 2022-03-31, so priority no longer survives where the rule withholds it. `orders.py::amend` stores the fresh encumbrance. **1,596 market tests pass**; the obsolete Tier-1 test `test_amending_upward_is_refused_as_a_tier_boundary` was rewritten to the new contract. Derivatives amendment re-funding is explicitly refused (cancel-and-resubmit), not silently skipped. |
| 5 | **The tick path does not implement the stated close-as-ATC approximation** | *Added 2026-08-27, verified in the code this session — not inferred.* The stated model is close-as-ATC: an ATC fills at the day's **published close**, which is our modelling choice — we do not trust the tick data inside the auction window, so we use the published open/close already in the database (see the auction note below). On **any** tick-resolution run that is not what happens: an ATC (or an LO carried into the cross) fills at `state.last`, the last continuous print before 14:30, while `auction_fill_price`'s own docstring promises *"the published open (ATO phase) or close (ATC phase)"*. So the tick path returns a **stale pre-auction print instead of the stated published close**. The fix is design-conformance: make an ATC fill return the published close, or **INDETERMINATE** if the close is absent. This is the only item on the list where a **fill that violates the stated model reaches a user on the tick path**, silently, under a docstring that says otherwise. | **Open, and live.** Mechanism, fix and proof of the fix's shape below the table. |
| 3 | **Forced liquidation must EXECUTE, not just report** | `FORCED_LIQUIDATION` emits an event and closes nothing — `detail['executed']` is `False` on every one. Measured on the Oct-2022 drawdown: **24 forced liquidations across 12 sessions, position intact through all of them**, riding 1102.0 down to a 1058.0 settlement. Cost **17,600,000đ on a 100,000,000đ account — 17.6%**. A strategy that would have been liquidated in reality survives here, which is the permissive direction. | **LANDED 2026-08-27.** `ExchangeSession._execute_forced_close` submits real offsetting orders through the order path (band, tick, lot, fill policy), priced at the band edge — floor for a sell, ceiling for a buy — so the close fills on a tradeable day and is refused `BAND_LOCK` on a locked one, which is the 17.6% cost reported truthfully rather than hidden. `detail['executed']` now reflects reality. The cure window is honoured (QĐ 26 Điều 13.3): the first mark reporting FORCED only reports; the breach persisting past it (gated on `in_forced_breach` latched before the mark) executes. Verified in `scenarios/test_j3_forced_liquidation.py` (leveraged VN30F → call → forced close, net→0). **1,596 market tests pass**; the three tests pinning Tier-1 non-execution pass unchanged (they end on the first, cure-window, forced mark). |
| 4 | **Variation margin must settle in cash daily** | `DerivativesAccount.settle_daily` has no session call site (`FEATURES.md` D1). So the VM baseline never rolls off the entry price and the deposit balance sits unchanged at 99,948,008đ for all 18 sessions before expiry. Vietnamese futures settle P&L in cash every day; here they do not, so **realised P&L never reaches the deposit** and the author's essential — "their PnL of the contracts should be calculated correctly" — is not met. | Not started |

**That is the entire must-list.** Five numbered items, of which **#1 has landed**; four
remain open. Nothing else blocks publication — in particular the **adapter half** of the
auction seam (no shipped source stamps an auction phase, so the daily path never reaches the
auction branch at all) stays a SHOULD, and #5 is the **other half of that same seam**: the
tick path *does* reach the branch, and reaches it with the wrong price. The two are read
together in the SHOULD entry, which now says so explicitly.

### MUST #5 — the mechanism, the fix, and why the fix's shape is provable

Every line below was read this session, in this repo, at these lines.

1. **The phase re-stamp is correct, and is not the bug.** `exchange.py:2841-2843` does
   `phase = self._phase(record.venue, observed=state.session)` and then
   `_interval_for(ticker, ts, replace(state, session=phase))`. On a tick run `_phase` skips
   the `self._daily` branch and resolves from the rulebook —
   `resolved = self._rulebook.at(self._now).phase(venue)` (`exchange.py:2099`) — so at 14:35
   HSX the interval's state is correctly stamped `closing_auction`. Good. That correctness is
   precisely what opens the hole.
2. **`TickSource` (`tick.py:39`) is not an `IntervalSource`,** so `_interval_for` falls past
   the `isinstance` at `exchange.py:2437` to **synthesis** at `exchange.py:2442-2451`:
   `missing` is seeded with `{OPEN, HIGH, LOW, VOLUME, BOOK_SIZE}`, `close = state.last`, and
   `LAST`/`CLOSE` join `missing` **only when `state.last` is `None`**.
3. **The guard that should have caught it passes.** `MarketInterval.session` delegates to
   `state.session` (`types.py:2119-2129`), so the re-stamped `closing_auction` now *matches*
   `auction_fill_price`'s test `phase is None or phase is not interval.session`
   (`fills.py:631-632`), and the function returns `interval.close` — which step 2 set to
   `state.last`.
4. **`state.last` is by construction pre-auction.** Continuous matching stops at 14:30 and the
   cross publishes at 14:45 (HSX ATC 14:30–14:45, rulebook `:137` — note that schedule row is
   itself **low** confidence, "articles never read"). So the fill is a pre-auction price
   labelled `FillEvidence.AUCTION_PRICE` (`fills.py:1076-1079`).

**The fix is one condition: make `CLOSE` behave the way `OPEN` already does.** In the
synthesis branch `open` is never assigned and `DataField.OPEN` is in `missing`
**unconditionally** (`exchange.py:2442-2443`). Follow that through: `_clearing_price`
(`fills.py:2465-2473`) returns `(None, DataField.OPEN)` for an opening auction, and
`_auction` (`fills.py:1062-1068`) returns **INDETERMINATE** naming the field —
*"no published cross price for this auction, so whether it crossed at all cannot be
established"*. **The ATO half of the identical function is already correct.** That is what
makes the shape of the fix provable rather than proposed: when `_interval_for` synthesises and
`state.session` is `OPENING_AUCTION` or `CLOSING_AUCTION`, `CLOSE` joins `missing` and the ATC
half becomes the ATO half.

**Naming `CLOSE` in `missing` is necessary but not sufficient — a fix that only does that is
still broken.** `MarketInterval.close` is a plain dataclass field (`types.py:2113`) and
`auction_fill_price` reads *the field*, not `lacks()` (`fills.py:636`). So `close` must
actually be left `None` as well; `missing` is what lets the caller *name* the field it is
short of. Nothing else regresses: `_point_price` (`fills.py:2476-2485`) already falls back to
`interval.state.last` when `close` is `None`, and the condition fires only inside an auction
phase, so continuous fills are untouched.

**The DAILY path never fires at all**, and it is worth saying why so nobody "fixes" it there.
`_phase` returns the adapter's observed phase on the daily path whenever it is not `UNKNOWN`
(`exchange.py:2090-2092`), and `DataHubSource` stamps every state `SessionPhase.CONTINUOUS`
(`datahub.py:436`), so `interval.session` is never an auction and `_auction_phase`
(`fills.py:2445-2462`) never matches. That is the SHOULD; this is the MUST.

### Why #5 is placed above #3 and #4, and where that judgement is contestable

They are not commensurable on one axis, so here are both.

**On magnitude, #3 is worse and it is measured.** #3 rides a position through 24 forced
liquidations for **17.6% of a 100,000,000đ account**, and it is *directional* — permissive, in
the strategy's favour. #5's per-fill error is **deliberately not quantified**: the auction fill
is a stated approximation, not a rule to be validated against ticks (see the auction note
below), so there is no auction measurement here and none is owed. The case for ordering #5
first therefore rests on the next two axes, not on magnitude.

**On detectability, #5 is worse and it is not close either.** #3 and #4 announce themselves to
anyone who looks: a `FORCED_LIQUIDATION` event carries `detail['executed'] = False`, and a
deposit balance frozen at 99,948,008đ for 18 sessions is visible in the ledger. Both are
*absences*, and an absence can be found. #5 returns a plausible price, on a real fill, stamped
`AUCTION_PRICE`, under a docstring promising the published close. **There is nothing for a user
to notice.** A silently wrong number is a different category of defect from a missing one.

**On cost to fix, they are orders apart.** #5 is one condition in one branch, with its
correctness demonstrated by the other half of the same function. #3 and #4 are each a call
site plus the execution path behind it.

**The call:** fix #5 first — highest silent-wrongness per unit of work, and the only item that
is wrong *right now* on a run a user could start today — while recording plainly that **#3
remains the largest single error on this list**. Order of *remediation*, not order of severity.
A reader who wants severity should read #3 first.

**Items 3 and 4 share a root cause with a defect already fixed once**: a method exists,
is correct, is unit-tested, and has no call site. `scenario_margin.py` was the same —
1,069 of 1,069 lines never executed until it was wired. A component that returns nothing
because nothing called it is indistinguishable from one that correctly returned nothing,
which is why the ignorance meter now reports what was *exercised* rather than only what
was *computed*. Both of these should have been caught by that; check why they were not.

---

## RESOLVED — items that were on this list and are not any more

**MUST #1 — the order-book walk.** Landed 2026-08-27, commit `c6b7ef6` *"Walk the order
book instead of filling at a single price"*. Verified from `git log` and from the code, not
from the commit message alone: `src/plutus/market/adapters/depth.py` (1,002 lines,
`DepthSource` at `:666`) and `src/plutus/market/session/book_walk.py` (1,592 lines,
`BookWalkFillPolicy` at `:1249`) are both present; `pytest tests/market/session/test_book_walk.py
tests/market/test_depth_adapter.py` reports **130 passed**, exactly the 130 new tests the
commit claims; the commit records **35 mutations applied across both modules and all 35
caught**, one of which found a real defect. A marketable limit order now fills each tranche
at the **resting** level's own price and one order produces several fills, which is the
author's correction — *"if the ask 1 get fill all, and it goes to ask 2 to fill, and so on"*.

It also closed a SHOULD as a side effect: **`BAND_LOCK` no longer needs a fill-time
counterpart**, because a book locked at the ceiling has no asks below it, so a marketable
buy finds nothing and fills nothing. That removes the asymmetry where the session refused a
marketable order at entry and filled the identical resting order at the same instant.

**Two residuals, and neither is "fills happen at a single price".** State them; do not let
"landed" read as "reachable from a config file".

**How to tell "landed with residuals" from "not done", in one line each:** the walk *executes*
— 130 tests pass and 35 of 35 mutations are caught — so the mechanic is done. What is not done
is (a) reaching it from a config block and (b) pointing it at more than a dev extract. Neither
residual makes a fill it does produce wrong; both make it harder to get to.

* **Injection-only, by design — and it `raise`s, it does not warn or fall back.**
  `build_fill_policy` **refuses** the `book_walk` kind from a config block
  (`fills.py:2260-2276`, re-read 2026-08-27) with a `ValueError` whose message says why: it
  needs a book provider (a `DepthSource` over a depth root) and a queue assumption
  `FillPolicyConfig` has no field for, and defaulting either would be the silent substitution
  that function exists to refuse. The kind is *registered* only so the refusal can name it
  rather than report a real policy as an unknown one. The supported route is the one the error
  message itself prints: `ExchangeSession.build(..., fill_policy=BookWalkFillPolicy(
  DepthSource(root), queue=OptimisticQueue(), max_participation=None, max_staleness=None))`.
  This is a stated limitation, not a gap — but a reader who sees only "landed" will assume
  `kind: book_walk` works, and it raises.
* **The depth data we have *wired* is a dev extract; the corpus is not the limit.** Attribute
  this to the **adapters**, by name: `DataHubSource` serves a daily bar and `TickSource` serves
  a ladder with `BookLevel.size` permanently `None` (`depth.py:1-9`), so neither can answer
  "how many shares rest at the touch". **The corpus itself does carry order-book sizes** —
  `dataset/hermes-dev-extract` holds **1,390,914 size rows across four Parquet files with a
  `depth` column**, and production carries **666M/590M**. Any claim anywhere that we cannot
  compute our own clearing price for want of sizes is **false**; that is a fetch, not a
  limitation, and it must not be written in this file or any other. What *is* true of the
  extract as currently wired: it covers *"some windows and not others"*; depth is three levels
  and never extrapolated to a fourth; the two sides are never observed together — 53 of 203
  instants coincide on FPT 2022-11-09 — so a book here is **reconstructed, not observed**, and
  `cross_side_skew` rides on every one (FPT median 8.3 s, max 529 s; HTV median 584.9 s, max
  3.8 h). There is **no deletion record**, so *"the book is empty"* is a fact this corpus
  cannot express — and note that one is a genuine corpus limit, about **deletions**, not about
  sizes. Do not let it drift back into a claim about sizes.

---

**A shipped VSDC settlement calendar.** Removed 2026-08-27. **This entry overstated its own
result and is corrected here** — `FEATURES.md` A64 was right and this section was wrong, a
contradiction two independent audits flagged.

What survives: a settlement calendar **does not have to ship**. VSDC works exactly the days
the exchange trades, so T+N counted over days-the-data-carries lands on the published
answer — verified at three Tết closures, and a 2026-02-12 trade gives **2026-02-23**,
matching Announcement 4228/TB-VSDC. Deriving it is also the better engineering: a shipped
calendar goes stale the moment VSDC publishes a new year, whereas a derived one is correct
for whatever window the user has and fails loudly (no data) rather than silently (wrong
holiday).

What does **not** survive: that this is therefore resolved for the user. **The
days-the-data-carries path is caller-supplied, and it is not the default.**
`ExchangeSession.build` ends its calendar resolution at `exchange.py:1331` —
`return supplied if supplied is not None else weekday_settlement_calendar()` — and nothing
in `src/` derives settlement days from a data source automatically. `from_settlement_days`
(`calendar.py:233`) is a constructor the caller must feed. So a user who names no calendar
gets `weekday-only-UNSOURCED` (`calendar.py:779`), whose `is_settlement_day` is
`day.weekday() < 5 and day not in self._holidays` over an **empty** holiday set
(`calendar.py:390`) — every Tết, and every other closure the exchange takes, counted as a
settlement day. The size of the error is in our own code: `exchange.py:1306-1307` says a
2026-02-12 trade answers **T+2 = 2026-02-16 where VSDC settled 2026-02-23 — five counted
days the depository was shut**.

It is not hidden: `provenance()` reports `settlement_calendar_id`, and its docstring
(`exchange.py:1816-1819`) says outright that *"the default weekday-only calendar is wrong
around every Tet in the period and its id says UNSOURCED, so a published result cannot hide
behind it."* That is why this stays off the MUST list rather than going back on it. The
remaining work is a SHOULD, below.

Futures expiry needs no calendar either — `quote.ticker.expdate` is populated for all 73
contracts.

---

## THE AUCTION FILL — a stated approximation, and a corrected citation

Not a gate. This section exists because the auction cross model spent a release cycle carrying
a **fabricated citation**. The citation is corrected here, and what replaces it is not another
number — it is a plain statement that the auction fill is a **deliberate approximation**. There
is no auction measurement, and none is owed.

### The auction cross price: what we do, what we cited, and what is our choice

**What we do — and why, stated plainly.** `fills.auction_fill_price` (`fills.py:608-636`) fills
auction orders at the published open (ATO) or published close (ATC). **This is our modelling
choice: we do not trust the tick data inside the ATO/ATC auction window, so we take the day's
published close as the ATC outcome and the day's published open as the ATO outcome — both
already in the database.** It is an approximation, honestly noted, and nothing more. No number
justifies it and none is needed.

**The citation was fiction, and is already relabelled.** We had sourced that to **QĐ 352 Điều
6.2(a) / 6.3**. Both are the wrong article. **6.2(a)–(d) is the four-step algorithm that
DERIVES a cross from a book** — it is the thing we are *not* doing — and **6.3 is the
continuous-session resting-price rule**, a different phase entirely. Neither says a word about
the published close being an auction price. Never invent a replacement; this one was downgraded
to what it is. **The price rule is OUR choice, not a rule** — do not re-cite 6.2(a) or 6.3, or
any article, as its source.

**Context, not justification — why the close is a fair stand-in.** QĐ 352 **Điều 2.5**, verbatim
(rulebook `:334`, confidence **high**):

> *"Giá đóng cửa là giá thực hiện tại lần khớp lệnh cuối cùng trong ngày giao dịch."*

The close is the price of the day's **last match** — **phase-agnostic**. That is offered only as
*context* for why the published close is a reasonable stand-in for the ATC outcome; it is **not**
the source of our price rule, which remains our own modelling choice. Carried unchanged into VNX
QĐ 17 Điều 3.17. From **2025-05-05**, QĐ 22/2025 Điều 3.17 narrows it to the last **round-lot**
match and changes the fallback to the day's **opening reference** (rulebook `:335`, **high**).

**And there is no opening price in Vietnamese regulation at all.** `grep -i "mở cửa"` over the
434-row rulebook returns **one** row, and it is the derivatives contract template's *relative
hours* — *"mở cửa trước thị trường cơ sở 15 phút"* (rulebook `:146`) — not a price.
**`"giá mở cửa"` returns nothing.** No instrument defines an opening price, and nothing consumes
one, because the next-day reference is the **close** (QĐ 352 Điều 10.1, rulebook `:333`,
**high**). `interval.open` is therefore a **vendor construct**, at every venue, on every date —
which is exactly why using the published open for ATO is a modelling choice too, not a sourced
rule. Confidence on this absence: **medium** — it is an absence over *our assembled rulebook*,
not over the gazette, and it must be stated that way.

**The honest statement, which is what should appear in the paper and the docs.** *Nothing in
Vietnamese exchange regulation says the published close is the ATC cross, and nothing defines an
opening price at all.* Filling at the published open/close is **our modelling choice**, adopted
because auction-window tick data is untrustworthy and the published open/close are already
stored — not a sourced rule, and not backed by a number. Tag it that way wherever it appears.

**Why this sits next to MUST #5.** #5 is not a dispute about the approximation above; the model
is a stated approximation and is sound as such. #5 is that on a tick run we do not actually
*use* it — we use `state.last` from before the auction and call it the published close. The
approximation is right and the plumbing does not reach it.

---

## SHOULD — ship better with these, but declarable without

- **A shipped source that carries an auction phase.** *Added 2026-08-27; this path was
  tracked in no section of this file — not MUST, not SHOULD, not DECLARABLE — while
  `SCENARIO-CATALOGUE.md` named it as the blocker for two scenarios (J7 auction-only, J14
  ATO-vs-marketable-LO). That omission is the defect being fixed here.*

  **Read this together with MUST #5. They are one seam seen from two ends, and neither entry
  makes sense alone.** The auction fill has two ways to be unreachable-or-wrong, one per
  resolution. **Daily:** `DataHubSource` stamps every state `CONTINUOUS` (`datahub.py:436`),
  `_phase` passes an observed non-`UNKNOWN` phase straight through on the daily path
  (`exchange.py:2090-2092`), so `interval.session` is never an auction and the branch is
  **never reached** — this SHOULD. **Tick:** `_phase` resolves from the rulebook
  (`exchange.py:2099`) and the state *is* re-stamped, so the branch **is** reached — and gets
  handed a pre-auction `state.last` as the cross price — MUST #5. Same seam. One end is an
  absence you can declare; the other is a wrong number you cannot. Do not fix one and record
  the seam as closed.

  **DataHub is outdated and is slated for reimplementation** (author's decision, 2026-08-27).
  Everything below that is charged to `DataHubSource` is a limitation of **that adapter, named**
  — not of the design, not of the rulebook, not of the corpus. A reimplementation is free to
  stamp a real phase and this entry mostly evaporates.

  **What it is — and the claim is narrower than "auctions are not built".** The auction fill
  **exists**: `fills.auction_fill_price` (`fills.py:608-636`) returns the published open in
  an `OPENING_AUCTION` and the published close in a `CLOSING_AUCTION`. It is gated on
  `phase is not interval.session` (`fills.py:632`) and `MarketInterval.session` delegates to
  `state.session` (`types.py:2119-2129`); both shipped adapters hardcode that field —
  `DataHubSource` at **`datahub.py:436`** (`session=SessionPhase.CONTINUOUS`) and `TickSource`
  at **`tick.py:109`**, which in any case has no `interval()` method at all. **On the daily
  path that hardcoding survives** — `_phase` passes an observed non-`UNKNOWN` phase through
  (`exchange.py:2090-2092`) — so `interval.session` is `CONTINUOUS` for all of every day and no
  ATO or ATC has ever crossed there. **On the tick path it does not survive**: the fill loop
  re-stamps the state from the rulebook before building the interval
  (`exchange.py:2841-2843`), the branch is reached, and it misprices. That half is MUST #5.
  This SHOULD is now specifically the **daily** half. The seam is proven to work: the one
  source that *does* stamp a phase, `PhasedBarSource` (`validation/scenarios/bars.py:310`,
  `session=phase_at(venue, ts.time())` at `:438`), builds real ATO/ATC intervals at
  `:387-407` — but it lives in `validation/`, not `src/`, and is a scenario harness.

  **Why it does not block — and the declarable sentence has been narrowed.** No number a
  daily-resolution run reports is wrong because of it; a run that never submits an ATO or ATC
  is unaffected; and the remedy is one field on the adapter, not a subsystem. The old
  declarable sentence — *"no auction execution on the shipped adapters"* — is **retired as
  inaccurate**: the tick path executes auctions, it just prices them wrong. What is honestly
  declarable now is *"no auction execution on the daily path"*, and the tick path is not
  declarable at all until MUST #5 lands.

  **The one sharp edge, which is not declarable and should be fixed regardless** (daily path;
  on a tick run a cross *is* evaluated, so this one does not arise there). An ATO or
  ATC that never crosses is swept at the day's close with the trigger
  `_CLOSE_TRIGGER_BY_TIF[AUCTION_ONLY] = ExpiryTrigger.AUCTION_CROSS`
  (`exchange.py:272-276`). The event therefore asserts the order died *at an auction cross*,
  when no cross was ever evaluated — an absence dressed as an event. A user reading the log
  concludes their order lost the auction; in fact the auction did not happen.

  **CORRECTION, same day, from reading the code rather than reasoning about it.** An earlier
  version of this bullet said that on a **tick** run admission and the fill *"read different
  fields"* — `_phase` reporting `opening_auction` while the fill *"compares against
  `interval.session` and sees `CONTINUOUS`"*. **That is false, and the truth is worse.**
  `exchange.py:2841-2843` calls `_interval_for(ticker, ts, replace(state, session=phase))`, so
  the synthesised interval carries the **rulebook** phase, not the adapter's hardcoded one.
  Admission and the fill therefore *agree* — and the fill, now correctly believing it is in a
  closing auction, returns `state.last`. The divergence was never between the two phases; it is
  between the phase and the **price**. A predicted-but-benign mismatch turned out to be a live
  wrong number, which is why it moved to MUST #5. `validation/scenarios/bars.py:375-381` warned
  about the constant-phase hazard in advance — *"a real seam hazard for any adapter that stamps
  a constant phase, because admission would then judge in one phase and the fill in another"* —
  and that warning is exactly right about `DataHubSource` on the daily path; it simply is not
  the tick failure. Note the futures-settlement call at `exchange.py:3916` passes an
  **un-restamped** state, so it never sees an auction phase and MUST #5's fix does not touch it
  (and it falls back to `state.last` at `exchange.py:3923-3924` regardless).

  **Current state.** `auction_fill_price` built and tested; **unreachable on the daily path,
  reachable-but-mispriced on the tick path.** Neither shipped adapter carries a phase of its
  own. `FEATURES.md` **A40** and the §-table row at `FEATURES.md:648` both record the adapter
  half and both were corrected on 2026-08-27: their reassurance that *"ATO/ATC/PLO are
  reachable on a tick run"* is true of **admission** and false of **fills**, and neither
  document said so before.

- **Make the correct settlement calendar the default, or make the wrong one refuse.** Follows
  from the corrected RESOLVED entry above. Today a caller who names nothing silently gets
  `weekday-only-UNSOURCED` and a Tết-2026 T+2 five settlement days early. Two options, both
  small: derive the calendar from the days the configured source carries (the RESOLVED
  entry's own argument, currently unimplemented in `src/`), or make an unnamed calendar
  **raise** the way `_settlement_calendar` already raises for a named-but-unloadable one
  (`exchange.py:1296-1331`). Declarable without, because `provenance()` reports the id — but
  only a reader who checks it learns anything.
- **Ship `SMrate` and `MF` values** for the post-KRX scenario margin. SSI and TCBS publish
  theirs (0.87% basis rate; 5,000đ minimum margin per VN30 contract). Without them the
  model is wired but cannot compute.
- **Exercise the post-KRX scenario margin further** — wired and running, but only ~55% of
  its lines have executed under any test. Untested is not wrong, but it is unproven.
- ~~**Close the remaining permissive paths** — `BAND_LOCK` having no fill-time counterpart.~~
  **Closed 2026-08-27 by commit `c6b7ef6`**, as a side effect of the book walk: a locked book
  has no levels to sweep. Kept struck rather than deleted, per this file's own rule.

---

## DECLARABLE — absent, and honest to say so

These do not block a release provided the limitation is stated. Roughly eight are things a
Vietnamese trader would actually notice; the rest are config variants and charge
line-items. See `FEATURES.md` §16 for the full list with reasons.

Short selling (not permitted for Vietnamese equities anyway) · VAT · dividend withholding
tax · interest accrual pass · position-limit warning ladder (80/90/100, primary-sourced,
just not applied) · intraday margin checkpoints (09h30/14h00/16h30) · VSDC
collateral-management fee · government bond futures (deferred by author decision) ·
foreign-ownership room (tradeoff T1) · event-driven callbacks.

---

## How to keep this file honest

Update it in the same commit as any change to its items. A checklist that drifts is worse
than none, because it will be trusted. If an item moves off the MUST list, say **why** in
the RESOLVED section rather than deleting the row — the reasoning is what a later reader
needs, and in the calendar case the reasoning was itself a correction to a mistake we had
made.

Five rules this file learned on 2026-08-27, each from a defect an audit or a code read found
in it:

1. **Cite the instrument, not the number you remember.** MUST #2 carried
   *"QĐ 352 Điều 21.3"* for priority-preserving amendment. Điều 21 of QĐ 352 is the lunch
   break; 21.3 belongs to a different decision entirely; and the instrument this file named
   is the one that says priority-preserving amendment **does not exist**. The catalogue
   inherited the error verbatim. Every citation added here now carries the rulebook line it
   was read from, so the next reader can check it in one grep.
2. **A claim about another document's contents is a claim.** RESOLVED asserted the
   settlement calendar was settled while `FEATURES.md` A64 asserted the opposite; both
   shipped for a day. When an entry here contradicts `FEATURES.md`, one of them is wrong —
   settle it from the **code**, edit both in the same change, and say in each which way it
   went.
3. **"Blocked by" needs a row to point at.** Two catalogue scenarios named the auction
   phase-carrying data path as their blocker while `grep -i auction` over this file returned
   nothing. If something blocks a scenario, it belongs in MUST, SHOULD or DECLARABLE — the
   decision of *which* is the useful work, and "in no section" is not one of the three.
4. **Charge a limitation to the thing that has it — and name that thing.** Two standing
   corrections, both of which had already leaked into this file once:
   * **`DataHubSource` is outdated and slated for reimplementation** (author's decision,
     2026-08-27). Every limitation that traces to it is a limitation of **that adapter, by
     name** — never of the design, the rulebook or the corpus. Write "`DataHubSource` stamps
     every state `CONTINUOUS` (`datahub.py:436`)", not "the simulator has no auction phase".
   * **The corpus carries order-book sizes.** 1,390,914 size rows with a `depth` column in
     `dataset/hermes-dev-extract`; 666M/590M in production. "We cannot compute our own clearing
     price because we have no sizes" is **false wherever it appears** — it is a fetch, not a
     limitation. The real corpus limit next door is that there is **no deletion record**, which
     is about *deletions*; do not let it drift back into a claim about sizes.
5. **A phase re-stamp can turn "unreachable" into "reachable and wrong", and those need
   different sections.** The tick auction fill was written down here as a benign
   admission-vs-fill phase mismatch. Reading `exchange.py:2841-2843` showed the phases in fact
   *agree* and the price is what is wrong — a MUST, not a SHOULD. **When an entry says a path
   is never reached, go and confirm that at the call site**, because the same seam can be an
   absence at one resolution and a wrong number at another (this one is: SHOULD for daily,
   MUST #5 for tick).
