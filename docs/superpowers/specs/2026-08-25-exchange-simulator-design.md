# Design — `plutus.market`: a high-fidelity Vietnamese exchange simulator

**Date:** 2026-08-25 · **Status:** approved for planning
**Supersedes:** substantial parts of `2026-08-24-exchange-fill-model-design.md` (see §2)

---

## 1. Thesis

A backtest is only as faithful as its model of the exchange. Vietnam's exchanges
enforce rules that general-purpose backtesters do not carry — a price-dependent
tick grid, daily price-limit bands, 100% pre-funding, T+2 settlement with a
13:00 delivery cut, ATO/ATC call auctions, foreign-ownership caps, and a
*segregated* derivatives margin account under VSD rules.

**Plutus is a simulated Vietnamese exchange you point a strategy at.** It exposes
the same shape of interface a live broker does — submit an order, receive its
status, read your holdings and your margin — and it enforces the Vietnamese
rulebook behind that interface. The strategy author does not have to remember
that a share bought today cannot be sold today, or that a futures margin call
cannot be met with equity cash.

The consequence, and the point: **the same strategy code can run against history
and against production.** That is what makes it a pre-live validation tool rather
than another backtester.

### What it is not

It is not a backtesting engine. It does not run strategies, hold a portfolio,
compute returns, value positions, or report performance. The caller does all of
that. Plutus is the **counterparty**.

The commodity parts of a trading stack — event loop, portfolio accounting, data
handling, reporting — already exist in NautilusTrader, Backtrader and vectorbt,
and are not rebuilt here. What does not exist anywhere is the Vietnamese exchange.
That is the whole scope.

## 2. What changed from the previous spec, and why

The 2026-08-24 spec is superseded in four respects. Each change was forced by a
finding, not by preference.

| Previous position | Now | Why |
|---|---|---|
| The exchange is **stateless**: `admits(order, state) -> Verdict` and nothing more | The exchange is a **stateful session**: resting orders, settlement state, margin balances | A real exchange and depository *do* hold this state. Declaring it trader-side was wrong, and it made the T+2 rule unimplementable — which is the single most-wanted feature. |
| The framework claim is the **asymmetry** between admission rules (equity) and position rules (derivatives) | Dropped as an organising claim | The author does not want it, and it does not survive contact with T+2 — a settlement rule that is stateful, equity-side, and exchange-enforced. |
| Non-goal: **no order lifecycle**, no partial fills | Order lifecycle is **in scope** | Without order status there is no API worth using. |
| Reframe to a **backtest auditor** ("feed us your trade log") | Rejected | It requires other researchers to submit their code for inspection. They will not, and "we will tell you your results are wrong" does not sell. |

Two structural insights arrived with those changes and are load-bearing below:

**Exchange rules and broker terms are different objects** (§6). Exchange rules
are gazetted, dated and identical for everyone. Broker terms are commercial,
differ by firm and change at will. `margin.py` already gets the *shape* of this right —
`vsd_initial` and `broker_buffer` are separate fields summing to `initial_rate`. What
is new is applying the same split to settlement, fees, taxes and the sale advance, and
requiring that everything on the exchange side carry a dated citation. (The narrow bug
in the existing code is that `vsd_initial` is `0.175`, which matches no VSD publication,
and `maintenance_rate` is set equal to it — see §7.4 and the rulebook research.)

**Fill determination is a pluggable policy, not a fixed rule** (§8). This is the
useful, but it is standard practice applied to Vietnamese rules -- not a
novel contribution. See the retraction in section 8 before describing it.

## 3. Non-goals

- **No strategy execution.** Plutus never calls user code.
- **No portfolio, P&L, returns, or performance reporting.** The caller owns these.
  Plutus reports positions only to the extent an exchange does — for settlement
  eligibility and for margin.
- **Charges ARE modelled**, because they move cash and therefore change admission
  outcomes. Statutory taxes and exchange/VSD fees are dated `exchange_rules`;
  brokerage commission and the sale-advance rate are `broker_profile`. Each venue has
  its own schedule, so the model is a generic table (§6.1), not a pair of constants.
  Plutus debits them and reports them; it never nets them into a return.
- **No market impact.** Orders fill against observed history; the simulated order
  never moves the market and never induces a counterparty reaction. This is the
  standing limitation of any replay simulator and must be stated in every result.
- **No queue-priority matching against a full book** in this cycle. Fill
  determination is policy-driven (§8), and where the data cannot decide, the
  answer is `INDETERMINATE` rather than a guess.
- **No event-driven callbacks** in this cycle. Synchronous `submit`/`poll` only;
  event-driven is future work (§13).
- **No auto-transfer between accounts.** Vietnam has no such feature; transfers
  are always explicit caller actions (§7.3).

## 4. Object model

```
Session                        the simulation: clock, routing, one Account
  ├── clock                    advances through dates and session phases
  ├── exchanges                {HSX, HNX, UPCOM, HNXDS} — as configured
  │     └── Exchange           rulebook + admits() + sustains()   [EXISTS]
  ├── Account
  │     ├── SecuritiesAccount  CashLedger + HoldingsLedger
  │     └── DerivativesAccount DepositLedger + ContractLedger + margin view
  ├── OrderBookOfRecord        the caller's own resting orders, by id
  ├── FillPolicy               pluggable fill determination
  └── MarketDataSource         supplies MarketState per symbol per instant
```

A `Session` may hold **several exchanges at once**. Symbols route to their
exchange automatically from the ticker master. This is required for pair trading
— a VN30 basket against VN30F is the canonical Vietnamese use case and it spans
HSX and HNXDS.

## 5. API surface

Synchronous, call-and-response. Deliberately close in shape to a broker API.

```python
session = Session.from_config("config.json")

# --- clock -----------------------------------------------------------------
session.advance_to(ts)                  # -> list[Event]  (marks, calls, expiries)
session.now()                           # -> Timestamp
session.phase("HSX")                    # -> SessionPhase

# --- orders ----------------------------------------------------------------
ack = session.submit(Order(
    side=Side.BUY, symbol="FPT", quantity=1000,
    order_type=OrderType.LIMIT, limit_price=Decimal("95.5"),
))
# -> Accepted(order_id, ts) | Rejected(rule, binding_constraint, detail)

session.cancel(ack.order_id)            # -> Cancelled | Rejected(rule, ...)
session.amend(ack.order_id, ...)        # Tier 2
session.orders(status=OrderStatus.RESTING)
session.poll()                          # -> list[Event] since last poll

# --- state the exchange legitimately knows ---------------------------------
session.holdings("FPT")
# -> Holding(settled, committed, unsettled=[(qty, settles_at), ...])
#    sellable = settled - committed        (see §7.0)

session.cash()
# -> Cash(available, settled_balance, committed,
#         pending_proceeds=[(amount, settles_at), ...], advanced, interest_accrued)

session.positions()                     # derivatives contract ledger
# -> {contract_code: Position(net_qty_signed, avg_entry, multiplier, expiry)}

session.margin()
# -> MarginView(required, deposit_balance, free_deposit, equity, utilisation,
#               status, cure_by)

session.charges()                       # everything debited so far, itemised
# -> [Charge(kind, venue, base, amount, levied_by, ts), ...]

session.transfer(Pool.SECURITIES, Pool.DERIVATIVES, amount)
# -> Transferred(ts) | Rejected(rule, ...)
```

`MarginView` is the **session-level** aggregate and is deliberately a different type
from the existing per-position `plutus.market.margin.MarginState`
([margin.py:70](../../../src/plutus/market/margin.py)), which it wraps and aggregates.
`Pool` is the transfer target enum, distinct from the `Account` composite in §4.

**Event delivery has one cursor.** `advance_to()` returns the events it generated *and*
consumes them; `poll()` drains anything since the last read of either. The cursor is
destructive and single-consumer — a strategy and a separate logger cannot both drain it,
which is acceptable because §3 puts all reporting on the caller's side. Events carry
`(order_id, transition, ts)`, which is a dedupe key if a caller wants one.

`Rejected` always carries the **rule** that refused the order, not a string. The
existing `AdmissionRule` vocabulary is extended with the new stateful rules:

```
TICK_GRID · ROUND_LOT · BAND_LIMIT · BAND_LOCK · FOREIGN_ROOM · SESSION_SEMANTICS
UNSETTLED_HOLDING · INSUFFICIENT_CASH · INSUFFICIENT_DEPOSIT · POSITION_LIMIT
```

### Events

```
Filled · PartiallyFilled · Cancelled · Expired · Indeterminate
MarginCall · ForcedLiquidation · SettlementCredited · ExpirySettled
```

## 6. Configuration

Two objects, because they are two kinds of fact.

```json
{
  "period": {"start": "2021-06-01", "end": "2022-12-30"},
  "resolution": "tick",

  "exchange_rules": {
    "venues": ["HSX", "HNXDS"],
    "rulebook": "vn-2020-2026"
  },

  "broker_profile": {
    "name": "generic-retail-2022",
    "margin_buffer": 0.05,
    "margin_cure_window": "next_session",
    "advance_sale_proceeds": {"enabled": true, "daily_rate": 0.0004},
    "commission": [
      {"venue": "HSX",   "base": "trade_value", "rate": 0.0015},
      {"venue": "HNXDS", "base": "per_contract", "amount": 2700}
    ]
  },

  "accounts": {
    "securities":  {"initial_cash": 150000000},
    "derivatives": {"initial_deposit": 50000000}
  },

  "fill_policy": {"kind": "hard", "max_participation": 0.10},

  "data": {"adapter": "plutus.datahub", "root": "/path/to/corpus"}
}
```

**The rulebook is resolved per event instant — `rulebook.at(ts)` — not once at config
load.** A `period` spans regime changes (settlement changed inside 2022; KRX changed
HOSE inside 2025), so a single scalar version cannot be right for a multi-month run.
Named values under `exchange_rules` are therefore **counterfactual pins**: legal, but
recorded as overrides in the session's provenance record, which is exactly how a
post-KRX rulebook can be run against pre-KRX data as a control. No pin appears in the
example above, because a pinned `T+2@13:00` against a `period` starting 2021-06-01 would
contradict the in-force regime for most of the run — a bug dressed as a demonstration.

Every value in the rulebook must be traceable to a HOSE/HNX/VSD/MoF document with an
effective date. That traceability is the rulebook's whole claim, and it is why broker
terms must not live here.

### 6.1 Charges — one generic table, per venue

Charges are modelled (§3) and every venue has a different schedule, so they are rows in
a table rather than named constants:

```
Charge = {
  venue, applies_to,        # HSX | HNX | UPCOM | HNXDS ; equity | warrant | etf | future
  base,                     # trade_value | per_contract | per_trade | per_open_contract_per_day
                            # | monthly_per_security
  rate | amount,
  min, max,                 # optional
  side,                     # buy | sell | both
  levied_by,                # state | exchange | vsd | broker
  debited_at,               # fill | daily | monthly
  pool                      # securities | derivatives
}
```

This shape is required by the rules themselves, not by taste: the **0.1% personal
income tax** is sell-side only and withheld at source, so a sale credits cash net —
without it every sale is wrong by more than most commissions. The **VSD position
maintenance fee** accrues *per open contract per day*, which no per-trade constant can
express. **Custody** is monthly per security. Rows with `levied_by` of `state`,
`exchange` or `vsd` belong in the dated rulebook; `broker` rows belong in
`broker_profile`.

Estimated charges enter the buy encumbrance (§7.0) so `available` stays honest.

## 7. Ledgers and settlement

### 7.0 Encumbrance — accepting an order commits resources

Because orders now **rest**, every ledger check must test a balance *net of live
orders*, not the raw balance. Without this the spec claims 100% pre-funding and T+2
enforcement while describing ledgers that permit two individually-affordable resting
buys to overdraw cash, and 500 settled shares to back 1,000 shares of resting sells —
a short equity position, which Vietnam does not permit at all.

Definitions:

```
Cash.available   = settled_balance + advanced_proceeds - Σ encumbrance(live buys)
Holding.sellable = settled - Σ qty committed to live sells
free_deposit     = deposit_balance - Σ posted margin - Σ margin on resting derivative orders
```

Encumbrance is taken **on accept** and released on **every** terminal transition —
filled at the fill price, cancelled/expired/rejected in full, partial fills pro rata.

Amount encumbered, by order type:

| Order type | Buy encumbers | Rationale |
|---|---|---|
| `LIMIT` (LO) | `qty × limit_price` + estimated charges | Known worst case |
| `MKT`, `MTL`, `MOK`, `MAK` | `qty × ceiling` + estimated charges | Matches the code's own "buy at ceiling" semantics ([order.py:56](../../../src/plutus/core/order.py)) |
| `ATO`, `ATC` | `qty × ceiling` + estimated charges | Fundable before a clearing price exists |

Sells encumber quantity from `settled`, never from `unsettled`.

Transfers are bounded by the *net* figures: out of securities by `Cash.available`, out
of the deposit by `free_deposit`. This is what stops a caller withdrawing the margin
backing an open position.

**Estimated charges are inside the buy encumbrance** (§6.1), so `available` stays
consistent with what a fill will actually cost.

### 7.1 Holdings — equity settlement

Bought quantity is **unsettled** until the settlement instant, and unsettled
quantity is not sellable. The regime is date-dependent, and this is where the
"T+1.5" folk term is resolved: there has never been a T+1.5 cycle in Vietnamese
law. It is a T+2 cycle with delivery before 13:00.

**`unsettled` is a list of tranches, not a scalar.** Under T+2 up to two tranches are
open at once; under the pre-2012 T+4 regime, four. A single `(quantity, sellable_from)`
pair forces a wrong choice — either the earlier tranche's instant frees the later
tranche's shares (permitting exactly the sale this section exists to prevent), or the
later instant blocks the earlier one (a spurious rejection). So `Holding` carries
`unsettled=[(qty, settles_at), ...]`, mirroring the shape `Cash.pending_proceeds`
already uses.

`sellable_from` is therefore **not stored**. It is computed as the earliest instant at
which the *requested* quantity becomes sellable, and attached to the rejection.

**Settlement instants require a VSDC settlement-business-day calendar — this is a Tier 1
data input.** An earlier draft claimed T+N is "holiday-correct by construction" from
counting session dates. That is **wrong** (rulebook §9.5): T+2 is counted in VSDC
*settlement* business days. VSDC works on exactly the days the exchange trades — the two
calendars are separate documents listing the same dates — so what diverges is **weekdays**
versus trading days —
VSDC closed settlement 2026-02-16 to 02-20, so T+2 of a 2026-02-12 trade settled on
02-23. So `settles_at` is a datetime computed by a pluggable `SettlementCalendar`
resolved via `rulebook.at(ts)`, not by counting bars. The tranche/datetime *shape* is
unchanged; only the source of `settles_at` changes.

**On daily bars, `T+2 @ 13:00` behaves as T+3.** A daily bar is stamped midnight
([protocol.py:32](../../../src/plutus/market/protocol.py)), so a 13:00 threshold is not
met by the T+2 bar. This is the conservative direction and is intended, but it is stated
here rather than left to emerge from timestamp arithmetic — it is the difference the
Tier 1 demo turns on.

| Effective | Rule |
|---|---|
| 2002-01-02 → 2012-09-03 | T+4, sellable at session open |
| 2012-09-04 → 2022-08-26 | T+3, sellable at session open |
| 2022-08-29 → | T+2, sellable from 13:00 on T+2 |

> **UNVERIFIED — must be sourced before Tier 1 lands.** These effective dates, the VSD
> margin ratios, the tick and lot tables, the band special cases, the fee and tax
> schedules and the KRX delta all come from secondary research and are not yet traced to
> primary documents. Every one is a dated entry in the versioned rulebook and needs a
> citation to a HOSE / HNX / VSD / MoF decision.
>
> A dedicated rulebook research pass covering **2020–2026** is under way; its output
> lands at `docs/reference/citable/vn-exchange-rulebook-2020-2026.md` and supersedes every
> number in this spec. Do not pin a value into a test until it appears there with a
> citation and a confidence level.

A sell whose settled quantity is insufficient is `Rejected(UNSETTLED_HOLDING)`
carrying `sellable_from`. That rejection is the feature people will notice first.

### 7.2 Cash — proceeds and the sale advance

Sale proceeds are **pending** until the same T+N instant and are not spendable.
Because equity requires 100% pre-funding, a buy is
`Rejected(INSUFFICIENT_CASH)` when available cash is short — even if pending
proceeds would cover it.

When `advance_sale_proceeds.enabled` is true, pending proceeds become available
immediately and accrue interest at `daily_rate` until they settle. This is the
brokerage product *ứng trước tiền bán*. It is a **broker term**, not an exchange
rule, and it is the reason the two config objects are separate.

Interest is reported in `Cash.interest_accrued`. Plutus does not net it against
anything — the caller decides what to do with it.

### 7.3 The derivatives deposit is a separate account

Vietnamese derivatives margin is posted to a segregated deposit account
("ký quỹ"). It is funded by an explicit transfer out of the securities account,
and the two pools have **independent purchasing power**.

- Equity orders draw on securities cash only.
- Futures margin draws on the deposit only.
- A margin call resolves against the deposit only. If the deposit is short,
  the futures position is force-liquidated and **securities cash is untouched**.
- There is **no auto-transfer**. The caller must call `transfer()`.

**The `ContractLedger`.** A deposit balance with no positions behind it is not a
coherent object, so `DerivativesAccount` also holds
`{contract_code: (net_qty_signed, avg_entry, multiplier, expiry)}`, resolved
open/close/net on each fill and readable via `session.positions()`. Everything the
derivatives half promises depends on it: `POSITION_LIMIT` needs a quantity to compare
against the cap, the daily mark needs a position to mark, `ForcedLiquidation` must name
which contracts closed, and `ExpirySettled` must have a ledger effect.

It is also where **shorts** live. A SELL on an HNXDS symbol opens or increases a short
and is never checked against holdings; a SELL on an equity symbol requires settled
holdings, because Vietnamese cash equity permits no short selling.

Assumptions adopted for this cycle, both deliberately simple and both to be
stated in any published result:

- A transfer arrives **immediately** during trading hours. Intra-day transfer
  timing is not modelled.
- The margin-call cure window is the **next session** (`margin_cure_window`,
  a broker term).

This makes the strategy's *response* to a margin call part of the simulation,
which is the realistic behaviour and the more useful one.

### 7.4 The margin-call state machine

```
day T   mark every open contract to its settlement price
        assets no longer cover the required margin  ->  MarginCall(cure_by = next session)
        caller may transfer cash, reduce the position, or do nothing
day T+1 re-mark
        still short  ->  ForcedLiquidation
        restored     ->  call cleared
```

**The test is account-level, net-risk, and a utilisation test.** Confirmed by the
author: the Vietnamese exchange margins the **whole deposit account on a net-risk
basis**, not each position summed. The requirement is an absolute amount and there is
**no maintenance ratio** in Vietnamese rules (rulebook §6.3, §9.1):

```
MR          = IM + VM        computed over the whole account portfolio
              IM = initial requirement recomputed on the CURRENT price (last match
                   in-session, DSP end of day) — not on entry notional
              VM = variation margin, counted ONLY when the account is in loss;
                   a favourable move contributes zero
assets      = deposit_balance          (cash-settled: daily P&L leaves/enters as cash
                                        on T+1, so the deposit does NOT accumulate MTM)
utilisation = MR / assets    ->  warning ≥ 0.80, call ≥ 0.90, forced ≥ 1.00
```

Three things a naive build gets wrong, all forced by the above:

- **Net-risk, not per-position.** Offsetting positions (long one contract month, short
  another) net down the requirement. So the margin entry point takes the **whole
  `DerivativesAccount`**, never a lone `Position`. The per-position `margin.py`
  primitive is the untouched batch research path (§10), *not* the session input. The
  spread-credit values are Tier 2 and marked UNVERIFIED; building strict
  per-position-and-sum first is the conservative fallback (it over-charges, never
  under-charges) **provided the entry point already takes the account** so the netting
  engine slots in without re-plumbing.
- **VM is loss-only, marked against the previous daily settlement price** — not
  symmetric around entry the way `margin.py:106` currently computes it.
- **The 80/90/100 ladder is three states**, not one call boolean: warning → call →
  forced liquidation, with the cure window between call and forced.

Resting derivative orders must contribute to `MR`, or a caller can rest futures orders
it cannot fund.

> **The trigger's *semantics* must be fixed before its *numbers* are sourced.** The
> existing code sets `maintenance_rate == vsd_initial`
> ([margin.py:40](../../../src/plutus/market/margin.py)), which is the utilisation ≥ 1
> test written differently. A draft of this spec instead paired initial 0.13 with
> maintenance 0.10, which fires at utilisation 1.30 — an 8.89% adverse move, which the
> ±7% VN30F band makes unreachable in a single session. Two correctly-cited numbers can
> still produce a wrong rule if the mechanism between them is wrong.

`ForcedLiquidation` must state its **selection rule** (largest-loss-first, or pro rata),
the price used (the settlement price, or a `FillPolicy` call at the next open), and the
resulting deposit balance. `ExpirySettled` is a cash movement into or out of the deposit
at the index-referenced final settlement, with the contract removed from the ledger.

**What the session uses from existing code.** `margin.py`'s per-position computation is
reused and aggregated. `Exchange.sustains()` is **not** what the session runs per mark —
its signature takes a whole `Sequence[MarketState]` and evaluates it in one batch, with
nowhere to carry an outstanding call across days, and ~20 tests depend on that form. It
stays untouched as the batch research path (§10).

## 8. `FillPolicy` — the extension point

A resting order's fate is often genuinely unknowable from historical data: we
have three price levels, sizes only after the pending backfill, and never an
order id or a true queue position. Rather than guess, the policy is explicit and
swappable.

```python
class FillPolicy(Protocol):
    def evaluate(
        self,
        order: RestingOrder,
        interval: MarketInterval,   # prices traded, volume, book if available
        rules: Exchange,
    ) -> FillDecision: ...
```

`FillDecision` is one of `Fill(qty, price, confidence)`,
`NoFill(reason)`, or `Indeterminate(reason)`.

Two conventions must be fixed, because §8's whole value is a *spread across policies*
and a drifting convention would contaminate the comparison:

- **Fill price.** In a call auction, the published open/close (§11 item 10). In
  continuous session under §3's no-impact replay, a limit order fills at its **limit
  price** — the only non-arbitrary choice available.
- **Fill quantity.** A `max_participation`-capped quantity is floored to
  `instrument.trading_unit`. Otherwise the ledger holds an odd lot that `ROUND_LOT`
  ([equity.py:58](../../../src/plutus/market/exchanges/equity.py)) will later refuse to
  sell.
- **`max_participation`** is a fraction of the volume observed in the evaluated
  interval, and it aggregates across all of the caller's own live orders in that
  instrument.

| Policy | Rule | Represents |
|---|---|---|
| `SoftFillPolicy` | Fill if the price traded at or through the limit, full size | What every backtester does today — the baseline arm |
| `HardFillPolicy` | Fill only when the market demonstrably traded *through* the limit; touched-at-limit → `INDETERMINATE`; capped at `max_participation` of observed volume | What is defensible going live |
| `ProbabilisticFillPolicy` | Fill probability from queue estimate and observed volume; seeded | The middle, once sizes land |

Ship `Soft` in Tier 1 (it is trivial, and it is the comparison arm). `Hard` in
Tier 2. `Probabilistic` when sizes are available.

### Why this matters, stated at the width prior art leaves standing

Run one strategy against all three policies and report the spread. *"Sharpe 1.8
under soft fills, 0.4 under hard fills"* is a useful pre-live warning.

**It is not novel, and no document in this repository may say that it is.**
Prior-art verification refuted the claim five times over. NautilusTrader ships
`prob_fill_on_limit` in {0.0, p, 1.0} by default -- that is already a
hard/soft/probabilistic axis. LEAN, Zipline, RQAlpha, hftbacktest and
PyAlgoTrade all expose swappable fill determination. Forex Strategy Builder
shipped `enum BacktestEval {Error, None, Ambiguous, Unknown, Correct}` with a
reported `AmbiguousBars` statistic and a Method Comparator **in 2011**. And
Claeys (SSRN 6240638, 2026) already reports the best-case/worst-case spread as
a headline result, with 18.47% of bars ambiguous over 2,064,460 NQ bars.

What survives is narrower and is the only form to use: our spread is bounded by
**admissibility** -- the exchange's own dated rules decide which orders could
have existed at all -- rather than by OHLC geometry alone. See
`docs/reference/literature-review.md` for the full concession.

The boundary holds: the caller runs their strategy three times against three
configured sessions. Plutus still never executes strategy code.

## 9. Data source contract

A source must supply, per symbol per instant, whatever it can of:

| Field | Required | Absent ⇒ |
|---|---|---|
| `last`, `open/high/low/close` | yes | cannot simulate |
| `reference`, `ceiling`, `floor` | one of | band rules → `INDETERMINATE` |
| `session` phase | derivable from ts | `SESSION_SEMANTICS` → `INDETERMINATE` |
| `volume` | per policy | `Soft` needs none; `Hard`'s participation cap and `Probabilistic` degrade to `INDETERMINATE` |
| `book` (3 levels ± sizes) | no | `Probabilistic` unavailable; `Hard` degrades |
| `foreign_room` | no | `FOREIGN_ROOM` → `INDETERMINATE` |
| `settlement_price` | derivatives | margin marks → `INDETERMINATE` |

**Nothing silently defaults.** A missing field produces `INDETERMINATE` with the
field named, and the session reports the rate. Resolution (`daily` | `tick`) is
declared by the source, and the session states which mode it is running in.

This contract is what makes "arbitrary data source" a checkable claim rather
than an assertion: a source either satisfies it or the session reports exactly
which rules it cannot evaluate.

## 10. What is reused

This is **additive**. Nothing is thrown away and the suite stays green.

- `Exchange.admits()` keeps its signature and becomes the admission gate inside
  `submit()`. The new stateful checks (§7.0, §7.1) run in the session *around* it,
  because they need account state `admits()` does not see.
- `Exchange.sustains()` keeps its signature and is **untouched** — it stays the batch
  research path used by `measurements/margin_incidence.py`. The session does *not* call
  it per mark (§7.4): it takes a whole price path in one call, has nowhere to carry an
  outstanding margin call between days, and ~20 tests in
  `tests/market/test_derivatives_sustains.py` depend on the batch form. The session
  aggregates `margin.py` primitives instead.
- `margin.py`, `expiry.py`, the four rulebooks, tick grids, band reconstruction,
  the three-state `Verdict` and evidence provenance: unchanged.
- The 617 existing tests continue to pass. New stateful rules are new
  `AdmissionRule` members, added rather than substituted.
- `plutus.core.constant` supplies the session-phase boundaries the clock needs;
  they are already encoded per exchange.

## 11. Build order

### The five shapes to lock before writing code

A policy audit (2026-08-25) separated policies whose *shape* must be right up front from
values a dated lookup swaps in later. These five, if built the obvious way, force
rework. Lock them; forbid the naive alternative. None is an unresolved unknown, so Tier
1 can start.

| # | Lock this shape | The naive build that must be forbidden |
|---|---|---|
| 1 | **Per-instant resolution, venue = `(ticker, ts)`** (Tier 1 item 1) | Config-at-load singletons / a ticker-keyed venue cache — bakes one regime and one venue per ticker |
| 2 | **Encumbrance ledger** — reserve on accept, release on *every* terminal edge, test net of live orders (§7.0) | A stateless affordability check inside `admits()`, or scalar balances mutated only at fill |
| 3 | **Tranche-list holdings/proceeds**, `settles_at` a datetime, `sellable_from` computed (§7.1) | A scalar `(qty, sellable_from)` pair, or date-granularity settlement |
| 4 | **Order-type-is-time-in-force** state machine, per-type terminal edges sharing the encumbrance-release hook (§12) | One `RESTING` state with a single "expire at every phase boundary" rule |
| 5 | **ContractLedger net-signed; margin/reservation entry point takes the whole account** (§7.3, §7.4) | Per-position rows; a margin function taking a lone `Position` |

The single most important is **#1** — every other lookup reads it, so it is the one
mistake that propagates everywhere. Build order below follows this ranking.

### Tier 1 — the walking skeleton

1. `Session`: config load, clock, exchange registry, symbol routing. The rulebook
   resolves **per event instant** — `rulebook.at(ts)` — not once at load. **Symbol
   routing is a per-event `instrument(ticker, ts)` call**, and `InstrumentSpec` is an
   "as-of `ts`" snapshot: `exchange_code` stays scalar but is the venue *as of `ts`*.
   The `datahub.py:225` ticker-keyed "one venue forever" cache must **not** be the
   authoritative router. Within the 2021–22 window nothing varies and no ticker changes
   venue (the HNX→HOSE transfer is 2025-07), so the seam is thin — but it must exist
   from this component, or every band/tick/lot/fee lookup inherits a frozen venue and a
   `ts` axis has to be threaded through every call site later.
2. Order lifecycle: ids and the state machine (§12), including release of encumbrance
   on every terminal transition.
3. `submit` / `cancel` / `poll`
4. `HoldingsLedger`: tranche list keyed by settlement instant (T+N resolved per instant
   by regime); `settled` / `unsettled[]` / `committed` to live sells
5. `CashLedger`: pre-funding via encumbrance at accept and release on terminal, pending
   proceeds, advance-on-proceeds with interest, charge debits (§6.1)
6. `DerivativesAccount`: deposit balance, `ContractLedger`,
   `free_deposit = balance − posted − resting-order margin`, `transfer()` bounded by
   the net figure in both directions
7. `FillPolicy` protocol + `SoftFillPolicy`

Deliverable: a tradeable exchange on daily bars. The demo is one screen — buy
FPT, try to sell it the same session, get `Rejected(UNSETTLED_HOLDING,
sellable_from=...)`.

### Tier 2 — fidelity

8. `HardFillPolicy` and `INDETERMINATE` accounting
9. Session clock driven by real tick timestamps; ATO/ATC/PLO reachable from data
10. Auction orders fill at the **published** open/close (cheap and correct)
11. Margin call state machine, cure window, forced liquidation
12. Foreign room wired from `quote_foreignroom` (the adapter currently hardcodes
    `None`, and the comment claiming the data does not exist is false)
13. Multi-exchange sessions exercised by a VN30/VN30F pair-trade fixture

### Tier 3 — evidence for the paper

14. Auction **clearing price computed by us**, graded against the published
    close. This is evidence, not a feature: if it slips, the simulator still works.
15. Occupancy census: the exchange never displayed a state our rules forbid.
16. The fill-spread experiment (§8).

## 12. Order state machine

```
                 submit()
                    │
        ┌───────────┴───────────┐
     REJECTED                ACCEPTED
   (rule named)                 │
                             RESTING ──────┬──> CANCELLED   (caller)
                                │          └──> EXPIRED     (phase/session end, per type)
                                ▼
                        PARTIALLY_FILLED ──┬──> FILLED
                                           ├──> CANCELLED   (caller)
                                           └──> EXPIRED
```

**`INDETERMINATE` is not an order state.** It is an *event* (§5) meaning the policy
could not decide for that interval; the order is still `RESTING` and is re-evaluated on
the next. Drawing it as a leaf beside `CANCELLED` was wrong — the ledgers in §7 need a
definite answer, and "maybe 1000 shares" is not one. The exits from
`PARTIALLY_FILLED` matter for the same reason: a half-filled resting order is exactly
the one a caller cancels, and `core/order.py:291` already models
`is_partial_filled_and_cancelled`.

**Expiry is per order type**, not per phase boundary for every order. An MOK never
rests; an unmatched ATO dies at the 09:15 cross; the noon break must not expire the
book. In Vietnam the order type *is* the time-in-force, and all seven types already
exist in `core/order.py:47`.

Invariants, asserted:

1. `filled + remaining = original`.
2. A terminal **order** state is never left.
3. Every transition carries a timestamp and a cause.
4. **Σ encumbrance over live orders equals the ledgers' committed totals, and committed
   returns to zero when no order is live.** One test, and it catches the whole leak
   class in §7.0.

## 13. Deferred, with reasons

- **Event-driven callbacks.** Synchronous is simpler to test and reason about.
- **Recovering our own queue *rank* against a full reconstructed book.** 81% of
  best-quote changes carry no trade, and there are no order ids, so order flow
  cannot be recovered and our actual position in the queue cannot be established.
  This is distinct from the **declared** queue-policy axis (optimistic /
  conservative / probabilistic) the book-walk maker fill exercises and the paper
  reports as F3 — that axis is built; what stays deferred is recovering the *true*
  rank the data cannot show.
- **The live Calibrator.** Deferred — but see §14.
- **Continuous-session matching validated empirically.** Report the
  `INDETERMINATE` rate as a bound on ignorance instead.
- **Post-KRX (May 2025) rulebook.** The versioning mechanism is built in Tier 1;
  populating the KRX rulebook is later work.

## 14. Validation, in one paragraph

Validation is **not a deliverable** — it is how the paper shows §5–§8 are
correct. Three strands, in cost order: the occupancy census (needs no simulator,
already has a working pilot); the chained test where our own computed close feeds
next-day reference and band, graded against published values; and the firm's own
2021–2022 order and reject logs, which are the gold standard retrospectively and
require no live trading. One non-vendor data source should be obtained for a few
hundred ticker-days, because every series currently arrives through the same
pipeline we maintain.

## 15. Declared limitations

Omissions listed here are deliberate. An omission that is *declared* is not a defect;
a silent one is.

Two of them — items 3 and 4 — are a distinct category. They are not gaps waiting to be
filled but **fidelity traded for scope in this iteration**, chosen with the cost known.
They carry their own register in §15.1, which is the text the paper draws on. Anything
future work adds to that register must state what it buys, what it gives up, and what
would trigger revisiting it.

1. **The KRX cutover is a dated rule set, not a migration** (author's decision).
   Both rule sets ship and both stay. The rulebook resolves at the instant being
   simulated: a run dated before 2025-05-05 gets pre-KRX rules, a run dated on or after
   gets post-KRX, and a run spanning the boundary gets each on its own side. This is
   not a special case — it is the same `rulebook.at(ts)` mechanism the round lot and the
   margin ratio already use, with a larger delta hanging off one date. Populating the
   post-KRX values is Tier 2 work; the resolution mechanism is Tier 1.

   The **foreign-ownership** half of the KRX delta stays deferred with T1: the cutover
   changed room enforcement from fill-to-room-then-cancel to reject-at-entry, and since
   this iteration never classifies an account as foreign, neither branch is reachable.
2. **Landing Tier 1 does not retro-validate the published numbers.** `admits()` has zero
   non-test callers today, and three of the project's five headline figures come from
   DuckDB SQL that parallels the rules rather than calling them. §10 makes `admits()`
   the gate inside `submit()`, but the parallel SQL remains the source of those figures
   until it is replaced by real calls.
3. **This iteration assumes a domestic investor; foreign-ownership limits are not
   enforced.** The account is never classified as foreign, so every foreign-room check
   is vacuous and all trades are valid on that axis. This is a deliberate scope cut
   (author's decision): it removes an entire date-switched control flow (pre-KRX
   fill-to-room-then-cancel vs post-KRX reject-at-entry). The `is_foreign` flag stays on
   the order, defaults false, and the rule short-circuits. Enforcement is future work.
   *(For that future work: `quote_foreignroom` is the REMAINING room, not the cap —
   verified, HPG on 2022-11-15 decrements tick-by-tick within the session. Our
   `README.md` calls it the cap and is wrong.)* **Tradeoff T1 in §15.1.**
4. **Final settlement uses the data source's close price, by design.** Rather than
   compute the index-referenced trimmed mean, the simulator reads the expiring
   contract's `close` on its expiry day as the settlement price (author's decision — the
   exchange publishes essentially this). Verified: the data source carries a close on
   expiry day (VN30F2206, 2022-06-16 = 1286.0). It approximates the true index-based
   final settlement to ~0.4% (that day's index-window mean was 1281.4). This collapses
   the settlement-price computation to a data read; `expiry.py`'s `TWAP_30M` tier is
   retained only as the batch research path. **Tradeoff T2 in §15.1** — the 0.4% figure
   rests on one contract and must be widened before the paper cites it.
5. **No corporate-action engine in Tier 1.** Dividends, splits, bonus and rights issues
   change both the reference price and the holdings quantity. Until §6's rulebook
   carries the adjustment formulas, a run spanning an ex-date is wrong for that
   instrument. Tier 2 at the latest; the rulebook research is sourcing the formulas. The
   holdings ledger exposes an additive `apply_corporate_action(factor, cash_per_share)`
   hook over the tranche list so this is not retrofitted. **Open:** whether a resting
   order survives the ex-date (quantity scaled) or is cancelled — decides whether the CA
   engine mutates live orders or cancels them.
6. **A VSDC settlement-business-day calendar is a required Tier 1 data input** (§7.1).
   The earlier "holiday-correct by construction" claim was wrong; settlement days
   diverge from WEEKDAYS around Tết. They do NOT diverge from trading days: measured at
   three Tết closures, the trading gap and the settlement gap coincide exactly, so the
   calendar can be derived from the data source rather than supplied.
7. **Continuous-session fills are not empirically validated.** Report the
   `INDETERMINATE` rate as a bound on ignorance rather than a fill rate (§13).

### 15.1 Tradeoff register — fidelity deliberately traded for scope

A high-fidelity claim survives contact with reviewers only if the places where fidelity
was *bought down on purpose* are named, priced and dated. This register is that record.
Both entries are scoped to **this iteration** and are scheduled work, not permanent
design.

| # | The simplification | What it buys | Fidelity given up | Revisit trigger |
|---|---|---|---|---|
| T1 | Domestic investor only; foreign-ownership room is never enforced (§15.3) | Removes an entire date-switched control flow — pre-KRX *fill-to-room-then-cancel* vs post-KRX *reject-at-entry* — plus the room time series from the hot path | A foreign account's orders would, in reality, be partially filled or rejected on room. We admit them in full. Verified as a real constraint, not a vacuous one: **34,653 room observations sit below a single 100-share lot**; FPT on 2022-12-30 runs down to 11 shares | Any strategy or paper result that claims to represent a foreign account; or the post-KRX rulebook landing, which is when the two branches must both exist anyway |
| T2 | Final settlement price = the data source's `close` on expiry day (§15.4) | Collapses the index-referenced averaging computation to a single data read | The published settlement is an average over the last 30 minutes, not the close. **Measured across all 46 expiries from 2022-08-18 to 2026-08-20**: mean signed error **+0.024%**, mean absolute error **0.042%**, σ **0.071%**, worst case **0.333%** (VN30F2603). 37/46 land within 0.05%, 45/46 within 0.20% | Any result whose P&L is materially sensitive to expiry-day pricing. Otherwise **largely retired** — see §15.2, the simulator now prefers a real settlement price where the data source carries one |

**How these are reported.** Each is stated in the paper as a scoped simplification with
its measured cost attached — T2 with the 0.4% figure and the sample size (n=1, a stated
weakness), T1 with the 34,653-observation count that shows the constraint is real and
that ignoring it is a choice rather than a discovery that it never binds. Neither is
described as a modelling result. Reporting them this way is worth more than hiding
them: it is direct evidence that the fidelity claim elsewhere is audited rather than
asserted.

### 15.2 The settlement series, and how T2 was retired

**`quote.settlementprice` carries the already-computed settlement value at each
timestamp, not the raw observations feeding it.** The series tracks the running
calculated figure as the averaging window accumulates, so the **last entry on an expiry
day (~14:45) is the final settlement price** — read it, do not average it. Confirmed by
the pipeline owner and corroborated in the data: the mean absolute step between
consecutive values collapses from 0.035 early in the window to 0.005 in the middle, the
signature of a running mean becoming progressively less sensitive to each new
observation. Raw samples would not converge like that.

*This document twice got that wrong before getting it right.* It first read the last
entry as the settlement (correct), then "corrected" itself to the window mean
(**wrong** — that averages an already-averaged series), and is now back to the last
entry, this time verified rather than assumed. The intermediate figures 1281.36 and
0.36% should be struck wherever they appear.

**Window shape**, consistent across 2022, 2024, 2025 and 2026: **14:15 → 14:45**, the
last 30 minutes including the ATC. Thirty minutes, not fifteen. ~180–260 rows per
expiry day, and expiry days only — 55 days across four years.

**The averaged subject changed mid-corpus, and the boundary is exact.** The last
futures-tracked row is dated **2022-08-16**; the first `VN30INDEX` row is **2022-08-17**.
Before the cutover the series tracked the expiring contract's own price; after, it
tracks the VN30 index. So the settlement basis is **dated**, like the round lot and the
margin ratio, and `SettlementResolver` must resolve it at the expiry date rather than
applying one formula to all history. Which quantity the exchange published *pre*-cutover
is still unresolved and needs the HNX/VSD decision behind the change — a rulebook
question, not a data question.

#### The measurement, across every post-cutover expiry

Reading the last entry per expiry day and joining to the expiring contract's close
(`quote.ticker.expdate` is populated for all 73 futures, so the join is exact):

| | |
|---|---|
| Expiries measured | **46**, 2022-08-18 → 2026-08-20 |
| Mean signed error | **+0.024%** — the close sits marginally above settlement, effectively unbiased |
| Mean absolute error | **0.042%** |
| Standard deviation | **0.071%** |
| Worst case | **0.333%** (VN30F2603, 2026-03-19) |
| Within 0.05% | 37 / 46 |
| Within 0.10% | 42 / 46 |
| Within 0.20% | 45 / 46 |

Two things follow. First, the substitution is **about four basis points** in the typical
case — an order of magnitude better than the single-contract figures previously quoted.
Second, VN30F2206, the one contract this document leaned on for weeks, sits near the
**worst** of the distribution rather than the middle. That is the argument against
citing an n=1 measurement in general form, made against our own claim.

#### The design consequence

T2 is retired as a *design* limitation and demoted to a *data-availability* one. The
data source contract (§9) carries an **optional settlement price**:

- **Where the source supplies one, the simulator uses it.** Exact, no approximation,
  no tradeoff to declare.
- **Where it does not, the simulator falls back to the close** and records that
  substitution on the result, with the error distribution above as its declared cost.

The fallback is never silent: a result computed on the close-proxy says so, so a reader
can see which of the two paths produced the number.

## 16. Stated assumptions

To be repeated in any published result:

1. No market impact; no counterparty reaction.
2. Transfers to the derivatives deposit arrive immediately during trading hours.
3. The margin-call cure window is the next session.
4. There is no auto-transfer between accounts.
5. Fill determination is policy-dependent, and the policy must be reported
   alongside any result derived from it.
