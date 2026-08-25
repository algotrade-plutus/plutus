# Tier 1 interface contract — `plutus.market.session`

**Date:** 2026-08-25 · **Status:** binding for Tier 1 implementation
**Implements:** [`2026-08-25-exchange-simulator-design.md`](2026-08-25-exchange-simulator-design.md) §5–§12, Tier 1 items 1–7
**Rule source:** [`docs/reference/vn-exchange-rulebook-2020-2026.md`](../../reference/vn-exchange-rulebook-2020-2026.md)
**Shared types:** [`src/plutus/market/session/types.py`](../../../src/plutus/market/session/types.py)

---

## 0. What this document is

Seven modules, seven authors, one integration. Each author sees
`session/types.py`, this document, and their own module. Nothing else is
shared, so **a signature written here is a promise** — implement it exactly,
and if it is wrong, change it here first rather than locally.

Rules of engagement:

- Every type named in a signature below is either from `session/types.py` or
  from an existing module (`protocol.py`, `verdicts.py`, `broker.py`,
  `margin.py`, `exchanges/`, `adapters/`, `core/constant.py`). **No module
  defines a type another module needs.** If you find yourself writing a
  dataclass that another module will receive, it belongs in `types.py` and
  the orchestrator adds it there.
- Money and prices are `Decimal`. Quantities are `int`. Settlement instants
  are `datetime`.
- Where a value is an assumption rather than a sourced fact, the docstring
  says so. This codebase's whole claim is traceability.
- The 617 existing tests stay green. Everything here is **additive**.
  `Exchange.admits()` and `Exchange.sustains()` keep their signatures.

---

## 1. Who calls whom

Dependency flows **downward only**. There are no cycles, and the absence of
two particular edges is what keeps it that way.

```
                       session/types.py
        (leaf: imports only protocol, verdicts, broker, core.order)
                              │
        ┌──────────┬──────────┼──────────┬──────────┐
        ▼          ▼          ▼          ▼          ▼
   rulebook.py  calendar.py  orders.py  fills.py   (margin.py, broker.py,
        │          │          │          │           exchanges/, adapters/
        │          │          │          │           — existing, unchanged)
        └────┬─────┘          │          │
             ▼                │          │
        ledgers.py            │          │
        deposit.py            │          │
             └────────────────┴──────────┴──> exchange.py
                                               (ExchangeSession)
```

| Module | May import | Must **not** import |
|---|---|---|
| `types.py` | `protocol`, `verdicts`, `broker`, `core.order` | any session module |
| `rulebook.py` | `types`, `core.constant`, `protocol`, `adapters.base`, `margin` (for `vsd_initial_margin`) | `ledgers`, `orders`, `deposit`, `fills`, `exchange` |
| `calendar.py` | `types` only | every other session module |
| `orders.py` | `types` | `ledgers`, `deposit`, `exchange` |
| `ledgers.py` | `types`, `calendar`, `rulebook` (`RuleSet` as a value) | `orders`, `deposit`, `exchange` |
| `deposit.py` | `types`, `calendar`, `rulebook`, `margin`, `broker` | `orders`, `ledgers`, `exchange` |
| `fills.py` | `types`, `exchanges.base` | every other session module |
| `exchange.py` | all of the above | — |

**The two edges that are deliberately absent, and why.**

1. **`ledgers.py` does not import `orders.py`.** The ledgers take
   `OrderRecord` as a *value* — it is a `types.py` type — and never reach into
   the order book. This is what lets `orders.py` own the state machine
   exclusively.
2. **`orders.py` does not import `ledgers.py`.** Locked shape 4 requires
   per-type terminal edges "sharing the encumbrance-release hook".
   `OrderBookOfRecord` takes that hook as a **callback** at construction
   (`on_terminal`), and `exchange.py` wires it to the ledgers. One callback,
   every terminal edge, no cycle. A terminal transition that forgets to
   release is then impossible by construction rather than by review.

**The call order inside `submit()`**, which is the one sequence everybody
needs to agree on:

```
exchange.submit(order)
  1. router.instrument(ticker, ts)      -> InstrumentSpec as-of ts   [shape 1]
  2. rulebook.at(ts)                    -> RuleSet                   [shape 1]
  3. rules.phase(venue)                 -> SessionPhase (never from ts alone)
  4. Exchange.admits(order, state, instrument=…, regime_tag=…)       [EXISTS]
        REJECTED / INDETERMINATE -> Rejected, stop
  5. account.reserve_for_buy / reserve_for_sell / reserve_for_order  [shape 2]
        short -> Rejected(INSUFFICIENT_CASH | UNSETTLED_HOLDING |
                          INSUFFICIENT_DEPOSIT | POSITION_LIMIT), stop
  6. book.accept(order, venue, ts)      -> OrderRecord(ACCEPTED)
  7. emit Event.ACCEPTED, return Accepted
```

Step 4 before step 5 is normative: an order that breaches the tick grid is a
tick-grid rejection whether or not the caller could have afforded it, and
inverting the order changes the per-rule composition of the rejection log
(the aggregate block rate is unaffected). Step 5 runs **around**
`Exchange.admits()`, never inside it — a stateless affordability check inside
`admits()` is the forbidden build of locked shape 2.

---

## 2. Shared types: the parts you must read before implementing

Full detail is in `session/types.py`; these are the four decisions most
likely to be got wrong by a module author working in isolation.

### 2.1 `StatefulRule` is temporary and must be merged

`verdicts.AdmissionRule` carries six members. Design §5 requires four more —
`UNSETTLED_HOLDING`, `INSUFFICIENT_CASH`, `INSUFFICIENT_DEPOSIT`,
`POSITION_LIMIT` — **added rather than substituted**. Python cannot extend an
`Enum` that already has members, and the task that authored `types.py` could
not modify `verdicts.py`, so they sit in a second enum, `StatefulRule`.

**Orchestrator action, before Tier 1 lands:** add the four members to
`AdmissionRule` with the same values, delete `StatefulRule`, and re-point
`RejectionRule` at `AdmissionRule`. Every call site is typed
`RejectionRule`, so nothing else changes.

Until then: type every `rule` parameter as `RejectionRule`, and never reuse
`SESSION_SEMANTICS` for a funding or settlement refusal. `AdmissionRule` *is*
the rejected-order log, and a log that cannot distinguish "you had no cash"
from "the market was shut" measures nothing.

### 2.2 What `binding_constraint` holds, per rule

`Rejected` carries the **number that bound**, following the convention the
six existing rules already use.

| rule | `binding_constraint` | also set |
|---|---|---|
| `TICK_GRID` | the tick size | — |
| `ROUND_LOT` | the round lot in force | — |
| `BAND_LIMIT` | the ceiling or floor breached | `detail['side']` |
| `BAND_LOCK` | ceiling (buy) / floor (sell) | `detail['lock_evidence']` |
| `FOREIGN_ROOM` | remaining room (`int`) | — |
| `SESSION_SEMANTICS` | `None` | `detail['phase']`, `detail['reason']` |
| `UNSETTLED_HOLDING` | sellable quantity available (`int`) | **`sellable_from`** |
| `INSUFFICIENT_CASH` | `Cash.available` | — |
| `INSUFFICIENT_DEPOSIT` | `free_deposit` | — |
| `POSITION_LIMIT` | the cap, in contracts | `detail['net_quantity']` |

`sellable_from` is a separate field, not the binding constraint, because it
is a different quantity: the constraint is *how many* shares were available,
and `sellable_from` is *when* the requested quantity becomes available. It is
set only for `UNSETTLED_HOLDING`, and it is the Tier 1 demo.

### 2.3 `Rejected.verdict` distinguishes "no" from "cannot tell"

`Exchange.admits()` returns three verdicts. `INDETERMINATE` is not admitted
(absence of evidence is not evidence of admissibility), so it also keeps the
order out of the book — but it is **not** a rule saying no. `Rejected` carries
`verdict` so the two are separable in the log, and `IndeterminateReport`
counts the second kind. Collapsing them would report a data gap as a market
rule and corrupt the rejection-rate figures.

### 2.4 Renames from the design spec, and why

| Design §  | Spec name | This contract | Reason |
|---|---|---|---|
| §8 | `RestingOrder` | **`OrderRecord`** | The same row answers `orders(state=FILLED)`. Calling a filled order a "resting order" is a lie in a type name; the fill policy sees only live rows, which is a filter, not a type. |
| §8 | `Fill` / `NoFill` / `Indeterminate` (3 classes) | **`FillDecision`** (one tagged record, three constructors) | `Fill` is already the execution record, a genuinely different thing. One shape spares every call site an `isinstance` ladder and carries `reason` and `confidence` together. |
| §5 | `Position(net_qty_signed, …)` | **`ContractPosition`** | `protocol.Position` exists and is unsigned-with-a-side. Locked shape 5 forbids reusing it. |
| §5 | `Charge` (read model) + §6.1 `Charge` (config row) | **`Charge`** + **`ChargeRule`** | §5 and §6.1 both say "Charge" for two different objects. `ChargeRule` is "brokers charge 0.15%"; `Charge` is "you were charged 225,000₫ on 2022-03-14". |
| §5 | `session.submit(Order(symbol=…))` | `Order(ticker=…)` | `protocol.Order` is frozen and its field is `ticker`. The spec example is aspirational; the existing type wins. |
| §5/§12 | `OrderStatus.RESTING` | **`OrderState`** (new enum) | `core.order.OrderStatus` has no `RESTING`, carries 18 broker-round-trip states a simulated exchange has no analogue for, and is not `str`-mixed. |
| §5 | `Session` | **`ExchangeSession`** (alias `Session`) | Matches the module name; the alias keeps `Session.from_config` reading as the spec writes it. |
| §5/§7.0 | `Cash.advanced` / `advanced_proceeds` | **`advanced`** | Two names for one quantity. The field name wins; the identity is documented on `Cash`. |

### 2.5 Two upstream landmines every author will hit

- **`Side.CROSS` exists** and `Side.CROSS.sign` returns `None` — verified. Any
  `quantity * side.sign` raises `TypeError` on it. Use
  `types.signed_quantity(side, quantity)`, which refuses `CROSS` loudly.
- **`adapters/tick.py:103` can construct `MarketState(band_source=None)`**, and
  `equity.py` reads `state.band_source.value` unconditionally, so it raises
  `AttributeError` instead of returning `INDETERMINATE`. Any session code
  building a `MarketState` must pass `BandSource.ABSENT`, never `None`.

---

## 3. `session/rulebook.py` — per-instant resolution

**Owns:** the dated rule sets, and the `(ticker, ts) -> venue` seam.
**Locked shape 1.** This is the single most important module: every other
lookup reads it, so it is the one mistake that propagates everywhere.

**Forbidden build:** config-at-load singletons, or a ticker-keyed venue cache.
`datahub.py:225`'s `Dict[str, InstrumentSpec]` — one venue per ticker for the
process lifetime — must **not** be the authoritative router. The four
`ExchangeSpec` module singletons in `core/constant.py` and the three
`EquityExchange` singletons in `exchanges/equity.py` may be *read* for
session boundaries and tick functions, but no dated value may be taken from
them.

```python
class Rulebook:
    """The dated rule sets. Resolves at an instant, never at load."""

    def __init__(self, rulebook_id: str = 'vn-2020-2026',
                 pins: Sequence[Pin] = ()) -> None: ...

    @classmethod
    def load(cls, rulebook_id: str, pins: Sequence[Pin] = ()) -> 'Rulebook':
        """Build a rulebook by id, applying counterfactual pins."""

    def at(self, ts: datetime) -> 'RuleSet':
        """Every rule in force at one instant. THE entry point."""

    @property
    def pins(self) -> Tuple[Pin, ...]:
        """Overrides in force, for the session's provenance record."""

    def edition_at(self, ts: datetime) -> RulebookEdition:
        """PRE_KRX before 2025-05-05, POST_KRX from it. A dated rule set,
        not a migration: both ship, both stay, a run spanning the boundary
        gets each on its own side."""
```

```python
@dataclass(frozen=True)
class RuleSet:
    """Every dated rule at one instant. Obtain only from Rulebook.at(ts)."""

    ts: datetime
    edition: RulebookEdition

    # -- instrument-level facts, all resolved at self.ts ----------------
    def trading_unit(self, venue: Venue, kind: InstrumentKind) -> int:
        """The round lot. HOSE was 10 until 2021-01-03 and 100 from
        2021-01-04; 94,675 HSX stock closes sit in the 10-lot window."""

    def daily_trading_limit(self, venue: Venue, kind: InstrumentKind,
                            ticker: str) -> Optional[Decimal]:
        """The band width. Date-, state- and instrument-dependent: first
        listing 20/30/40%, UPCoM 25-session illiquidity 40% (70,578 of
        412,041 UPCoM name-days = 17.1%), CW derived limits, bond exemption,
        GB futures 3%. Returns None where no band applies (bonds)."""

    def tick_size(self, venue: Venue, kind: InstrumentKind, price: Decimal, *,
                  method: TradingMethod = TradingMethod.ORDER_MATCHING
                  ) -> Optional[Decimal]:
        """The tick grid. `method` is required: put-through is 1đ at all four
        venues, and without it TICK_GRID rejects every legitimate
        put-through price. None means no band matches -> INDETERMINATE."""

    def legal_order_types(self, venue: Venue,
                          phase: SessionPhase) -> FrozenSet[OrderType]:
        """Which types this venue accepts in this phase, at self.ts.
        Dated and venue-specific: HSX is LO/MP/ATO/ATC to 2025-05-04 and
        LO/MTL/ATO/ATC from 2025-05-05; HNX continuous is LO/MTL/MOK/MAK with
        no ATO; UPCoM is LO ONLY at every date; HNXDS auctions take LO+ATO/ATC.
        A limit order IS legal in a call auction — the market family is what
        an auction refuses. OrderType.MARKET ('MKT') is legal nowhere, ever."""

    def phase(self, venue: Venue) -> SessionPhase:
        """The session phase at self.ts. MUST test noon_break BEFORE
        lo_session: `ExchangeSpec.lo_session` spans the break by
        construction. Nothing in the repo does this today — both adapters
        hardcode CONTINUOUS."""

    # -- settlement, margin, limits -------------------------------------
    def settlement_rule(self, kind: InstrumentKind) -> SettlementRule:
        """T+N and the delivery instant. Equities/funds/CWs T+2 since
        2016-01-01; corporate and government bonds T+1; privately placed
        bonds T+0. What changed on 2022-08-29 was the TIME OF DAY, not the
        number of days."""

    def initial_margin_rate(self, contract_code: str) -> Decimal:
        """VSD initial margin. 10% from 2017-08-10, 13% from 2018-07-18,
        17% from 2022-12-15. Delegates to `margin.vsd_initial_margin(date)`,
        which is already dated — do not re-implement the series. 17.5%
        matches no source at any date."""

    def position_limit(self, contract_code: str,
                       investor: InvestorClass) -> Optional[int]:
        """Net position cap: 5,000 / 10,000 / 20,000 contracts by class.
        Individuals may not hold GB futures at all."""

    def charges(self, venue: Venue,
                cls_: ChargeClass) -> Tuple[ChargeRule, ...]:
        """State/exchange/VSD charge rows in force. Refuses to return a row
        with levied_by == BROKER — those live in BrokerProfile."""

    def citation(self, rule_name: str) -> Optional[RuleCitation]:
        """The document behind a value. Traceability is the whole claim."""
```

```python
class SymbolRouter:
    """`(ticker, ts) -> venue`. The seam locked shape 1 exists to create."""

    def __init__(self, source: MarketDataSource, rulebook: Rulebook) -> None: ...

    def instrument(self, ticker: str, ts: datetime) -> InstrumentSpec:
        """The instrument AS OF ts. `exchange_code` stays scalar but is the
        venue at that instant, and `trading_unit`/`daily_trading_limit` come
        from `RuleSet`, not from the adapter's frozen spec."""

    def venue(self, ticker: str, ts: datetime) -> Venue: ...

    def exchange(self, ticker: str, ts: datetime) -> Exchange:
        """The `exchanges/` object that judges this ticker at this instant."""
```

**Implementation notes that are not optional.**

- `adapters.base.MarketDataSource.instrument(ticker)` has **no `ts`** — the
  one violation of shape 1 in the codebase. `SymbolRouter` is the seam that
  contains it: call the source for classification, then **overwrite**
  `trading_unit` and `daily_trading_limit` from `RuleSet` before returning.
- There is a precedence trap in `equity.py:58`: `admits()` prefers
  `instrument.trading_unit` when an `InstrumentSpec` is passed and falls back
  to the dated `get_trading_unit()` otherwise. So passing the adapter's spec
  **disables** the dated rule. `SymbolRouter.instrument()` must therefore
  return a spec whose `trading_unit` is already date-correct — that is what
  makes passing it safe.
- `regime_tag` on a `SESSION_SEMANTICS` verdict is always `None`:
  `_admits_in_session` builds its `Admissibility` directly and never receives
  one. `exchange.py` stamps `RulebookEdition.value` itself rather than
  trusting the exchange to.
- Within 2021–22 nothing varies and no ticker changes venue (the HNX→HOSE
  transfer is 2025-07), so the seam is thin — **but it must exist from this
  module**, or every band/tick/lot/fee lookup inherits a frozen venue and a
  `ts` axis has to be threaded through every call site later.

---

## 4. `session/calendar.py` — settlement business days

**Owns:** T+N arithmetic, and the distinction between settlement days and
trading days. **A Tier 1 data input, not a derivation.**

The earlier "T+N is holiday-correct by construction from counting session
dates" claim is **wrong**. T+2 is counted in VSDC *settlement* business days,
published annually as a settlement-holiday calendar **separate** from the
exchange trading calendar, and the two diverge around Tết: VSDC closed
settlement 2026-02-16 → 02-20, so T+2 of a 2026-02-12 trade settled on
02-23. A simulator that adds two exchange trading days is wrong across every
settlement-only holiday.

```python
class SettlementCalendar(Protocol):
    """VSDC settlement business days. Pluggable, resolved via rulebook.at(ts)."""

    calendar_id: str

    def is_settlement_day(self, day: date) -> bool: ...

    def add_business_days(self, start: date, days: int) -> date:
        """`start` + N settlement business days. `days=0` returns the next
        settlement day at or after `start`."""

    def settles_at(self, traded_at: datetime, rule: SettlementRule) -> datetime:
        """THE function. Trade instant + SettlementRule -> settlement instant.
        Returns a datetime, never a date: shape 3 forbids date-granularity
        settlement because the current regime turns on 13:00."""

    def covers(self, day: date) -> bool:
        """Whether the loaded calendar spans `day`."""


class VsdcSettlementCalendar:
    """A loaded VSDC settlement calendar for a stated coverage window."""

    def __init__(self, holidays: FrozenSet[date],
                 coverage: Tuple[date, date],
                 calendar_id: str = 'vsdc') -> None: ...

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> 'VsdcSettlementCalendar': ...

    def assert_covers(self, day: date) -> None:
        """Raise rather than extrapolate past the loaded window. A calendar
        that silently assumes weekdays-only outside its coverage produces a
        settlement instant that looks sourced and is not."""


class TradingCalendar(Protocol):
    """Exchange trading days. Deliberately a DIFFERENT object."""

    def is_trading_day(self, day: date) -> bool: ...

    def next_session_open(self, ts: datetime, venue: Venue,
                          rules: RuleSet) -> datetime:
        """The next session's open on `venue`. This is what a margin call's
        `cure_by` is measured in — sessions, not settlement days."""

    def session_end(self, ts: datetime, venue: Venue,
                    rules: RuleSet) -> datetime:
        """End of the last matching phase of `ts`'s day. Where a DAY order
        expires (ExpiryTrigger.SESSION_END)."""


class VnTradingCalendar:
    """Mon–Fri minus Labour Code holidays, plus SSC-ordered closures."""

    def __init__(self, holidays: FrozenSet[date],
                 coverage: Tuple[date, date]) -> None: ...

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> 'VnTradingCalendar': ...
```

**Behaviour to pin in tests.**

- `settles_at` on a 2026-02-12 trade under `T+2 @ 13:00` returns
  `2026-02-23T13:00`, not `2026-02-16`.
- **On daily bars, `T+2 @ 13:00` behaves as T+3.** A daily bar's `ts` is
  midnight, so a 13:00 threshold is not met by the T+2 bar. This is the
  conservative direction, it is intended, and it must be stated in a
  docstring rather than left to emerge from timestamp arithmetic — it is the
  difference the Tier 1 demo turns on.
- The pre-2022-08-29 regime is expressed with
  `delivery_on_next_session_open=True`, not as 16:00 on T+2. Settlement
  completed 15:30–16:00 on T+2, *after the close*, so the first sellable
  session was the open of T+3. Encoding it as an afternoon time would make a
  T+2 afternoon sale look legal.
- The repo has **no trading calendar and no settlement calendar** today.
  `TRADING_DAYS_PER_YEAR = 250` is an annualisation factor and must not be
  hung off.
- Never call the 2022-08-29 regime "T+1.5". It appears in retail press and
  broker marketing and in no gazetted document.

---

## 5. `session/ledgers.py` — encumbrance, cash tranches, holdings tranches

**Owns:** the securities account. **Locked shapes 2 and 3.**

**Forbidden builds:** a stateless affordability check inside `admits()`;
scalar balances mutated only at fill; a scalar `(qty, sellable_from)` pair;
date-granularity settlement.

Because orders now *rest*, every ledger check tests a balance **net of live
orders**. Without that, two individually-affordable resting buys overdraw
cash and 500 settled shares back 1,000 shares of resting sells — a short
equity position, which Vietnam does not permit at all.

```
Cash.available   = settled_balance + advanced - Σ encumbrance(live buys)
Holding.sellable = settled - Σ qty committed to live sells
```

### 5.1 `EncumbranceLedger`

```python
class EncumbranceLedger:
    """Reservations held by live orders. Keyed (order_id, ResourceKind)."""

    def __init__(self) -> None: ...

    def take(self, order_id: OrderId, pool: Pool, resource: ResourceKind,
             ts: datetime, *, amount: Decimal = Decimal('0'),
             quantity: int = 0, ticker: Optional[str] = None,
             estimated_charges: Decimal = Decimal('0')) -> Encumbrance:
        """Reserve on accept. Raises if this key already holds one."""

    def consume(self, order_id: OrderId, ts: datetime, *,
                resource: ResourceKind, amount: Decimal = Decimal('0'),
                quantity: int = 0) -> Optional[Encumbrance]:
        """Pro-rata release at a fill. Reduces by what the fill actually
        consumed, AT THE FILL PRICE — not at the encumbered price. A limit buy
        reserved at 95.5 that fills at 95.0 must release the 0.5 difference or
        `available` leaks 0.5 per share, permanently."""

    def release(self, order_id: OrderId, ts: datetime, *,
                resource: Optional[ResourceKind] = None
                ) -> Tuple[Encumbrance, ...]:
        """Full release. Called on EVERY terminal transition — cancelled,
        expired, rejected, and the residue of a partially-filled order that
        then terminates. `resource=None` releases all of the order's."""

    def outstanding(self, *, pool: Optional[Pool] = None,
                    resource: Optional[ResourceKind] = None,
                    ticker: Optional[str] = None) -> Decimal:
        """Σ reserved amount over live orders. `Cash.committed` is
        `outstanding(pool=SECURITIES, resource=CASH)`."""

    def outstanding_quantity(self, ticker: str) -> int:
        """Σ shares committed to live sells. `Holding.committed`."""

    def of(self, order_id: OrderId) -> Tuple[Encumbrance, ...]: ...

    def live_order_ids(self) -> FrozenSet[OrderId]: ...
```

**Section 12 invariant 4, and it is one test:** Σ encumbrance over live orders
equals the ledgers' committed totals, and committed returns to **zero** when
no order is live. That single test catches the whole leak class.

### 5.2 `HoldingsLedger`

```python
class HoldingsLedger:
    """Tranche-list holdings. Shape 3."""

    def __init__(self, encumbrances: EncumbranceLedger) -> None: ...

    def credit_unsettled(self, ticker: str, quantity: int,
                         settles_at: datetime, ts: datetime,
                         order_id: Optional[OrderId] = None) -> HoldingTranche:
        """A buy filled. Appends a tranche — never merges into an existing
        one, even at the same instant, because a merge loses the audit trail
        and the corporate-action hook needs per-parcel granularity."""

    def settle_due(self, now: datetime) -> Tuple[HoldingTranche, ...]:
        """Move every tranche whose `settles_at <= now` into `settled`.
        Returns what moved so the caller can emit SettlementCredited.
        Comparison is `<=` on datetimes, which is what makes T+2@13:00
        behave as T+3 on midnight-stamped daily bars."""

    def debit_settled(self, ticker: str, quantity: int, ts: datetime) -> None:
        """A sell filled. Draws from `settled` ONLY, never from unsettled.
        Raises if short — the encumbrance should have prevented it, and a
        silent overdraw is a short equity position."""

    def holding(self, ticker: str) -> Holding:
        """The read model, with `committed` from the encumbrance ledger."""

    def tickers(self) -> FrozenSet[str]: ...

    def apply_corporate_action(self, ticker: str, factor: Decimal,
                               cash_per_share: Decimal, ts: datetime
                               ) -> Tuple[Decimal, Tuple[HoldingTranche, ...]]:
        """Additive hook over the tranche list. Scales every open tranche and
        `settled`, returns the cash leg and the new tranches.

        There is NO corporate-action engine in Tier 1 — a run spanning an
        ex-date is wrong for that instrument, and that is a declared
        limitation. This exists so the engine is not retrofitted into a
        scalar. OPEN, and not settled by this contract: whether a resting
        order survives the ex-date with quantity scaled, or is cancelled."""
```

### 5.3 `CashLedger`

```python
class CashLedger:
    """Settled cash, pending proceeds, the sale advance, and charge debits."""

    def __init__(self, initial_cash: Decimal, terms: BrokerTerms,
                 encumbrances: EncumbranceLedger) -> None: ...

    def cash(self) -> Cash:
        """The read model. `available` is derived, never stored."""

    def credit_pending(self, amount: Decimal, settles_at: datetime,
                       ts: datetime,
                       order_id: Optional[OrderId] = None) -> ProceedsTranche:
        """A sell filled. `amount` must ALREADY be net of sell-side charges
        withheld at source — the 0.1% PIT is deducted by the broker on the
        sale, so a sale credits net. If `terms.advance_on_sale_enabled`, the
        tranche is marked advanced and its amount enters `Cash.advanced`
        immediately."""

    def settle_due(self, now: datetime) -> Tuple[ProceedsTranche, ...]:
        """Move matured proceeds into `settled_balance`, clearing any advance
        against them. Same `<=` comparison as holdings, and the same instant:
        cash and securities settle by DVP and are allocated in ONE event."""

    def accrue_interest(self, now: datetime) -> Decimal:
        """One period's interest on advanced proceeds, at
        `terms.advance_on_sale_daily_rate`. Reported in
        `Cash.interest_accrued` and NEVER netted against anything — the
        caller decides what to do with it."""

    def debit(self, amount: Decimal, ts: datetime, reason: str) -> None: ...
    def credit(self, amount: Decimal, ts: datetime, reason: str) -> None: ...

    def levy(self, charge: Charge) -> None:
        """Record and debit one charge. Honours `charge.pool`."""

    def charges(self) -> Tuple[Charge, ...]:
        """Everything debited so far, itemised. `session.charges()`."""
```

### 5.4 Charge helpers and the securities account

```python
def estimate_charges(rules: RuleSet, order: Order, venue: Venue,
                     cls_: ChargeClass, price: Decimal) -> Decimal:
    """Worst-case charges on a hypothetical fill, for the buy encumbrance.
    Estimated charges are INSIDE the encumbrance so `available` stays
    consistent with what a fill will actually cost."""


def assess_charges(rules: RuleSet, profile: BrokerProfile, fill: Fill,
                   cls_: ChargeClass) -> Tuple[Charge, ...]:
    """Charges actually levied on a fill (`debited_at == FILL` rows only).
    Rounding to whole đồng is a MODELLING CHOICE — no source states a
    rounding rule for any Vietnamese fee or tax — and must be reported."""


class SecuritiesAccount:
    """CashLedger + HoldingsLedger + the shared EncumbranceLedger.

    This is where the stateful admission checks live, so that they run AROUND
    `Exchange.admits()` and not inside it.
    """

    def __init__(self, ref: AccountRef, cash: CashLedger,
                 holdings: HoldingsLedger,
                 encumbrances: EncumbranceLedger) -> None: ...

    def reserve_for_buy(self, order_id: OrderId, order: Order, venue: Venue,
                        state: MarketState, rules: RuleSet, ts: datetime
                        ) -> Union[Encumbrance, Rejected]:
        """100% pre-funding. Rejected(INSUFFICIENT_CASH) when `available` is
        short EVEN IF pending proceeds would cover it.

        Amount encumbered, by order type:
          LIMIT (LO)              qty × limit_price  + estimated charges
          MKT, MTL, MOK, MAK      qty × ceiling      + estimated charges
          ATO, ATC                qty × ceiling      + estimated charges

        `qty × ceiling` needs `state.ceiling`. When the band is absent the
        order is Rejected with verdict=INDETERMINATE and rule=BAND_LIMIT —
        never funded at a guessed price."""

    def reserve_for_sell(self, order_id: OrderId, order: Order, venue: Venue,
                         ts: datetime) -> Union[Encumbrance, Rejected]:
        """Sells encumber quantity from `settled`, NEVER from `unsettled`.
        Short -> Rejected(UNSETTLED_HOLDING, binding_constraint=sellable,
        sellable_from=holding.sellable_from(order.quantity)).

        THIS IS THE TIER 1 DEMO. Buy FPT, sell it the same session, get this
        object back."""

    def apply_fill(self, fill: Fill, settles_at: datetime,
                   charges: Sequence[Charge]) -> None:
        """Consume the encumbrance at the fill price, move the tranche, levy
        the fill charges. The one place a fill touches the securities pool."""

    def release(self, order_id: OrderId, ts: datetime) -> None:
        """The terminal hook. Wired to `OrderBookOfRecord.on_terminal`."""
```

---

## 6. `session/orders.py` — the order state machine

**Owns:** order ids, `OrderRecord` transitions, per-type expiry.
**Locked shape 4.**

**Forbidden build:** one `RESTING` state with a single "expire at every phase
boundary" rule. In Vietnam the order type **is** the time-in-force.

The graph, the legal edges, the time-in-force map and the per-type terminal
triggers are all **data in `types.py`** — `LEGAL_TRANSITIONS`,
`TIME_IN_FORCE`, `TERMINAL_TRIGGERS_BY_TIF`, `EVENT_FOR_TRANSITION`. This
module reads them and must not hard-code a second copy.

```python
class OrderIdFactory:
    """Mints exchange-assigned ids. Strings, because a broker id is a string."""

    def __init__(self, prefix: str = 'PLU', start: int = new_order_id_seed
                 ) -> None: ...
    def next(self) -> OrderId: ...


class OrderBookOfRecord:
    """The caller's own orders, by id. The mutable half; OrderRecord is frozen."""

    def __init__(self, ids: OrderIdFactory, *,
                 on_terminal: Callable[[OrderRecord, OrderTransition,
                                        datetime], None]) -> None:
        """`on_terminal` is the shared encumbrance-release hook. It fires on
        every edge into FILLED, CANCELLED, EXPIRED and REJECTED, exactly once
        per order. Wiring it here — rather than at each call site — is what
        makes "released on EVERY terminal transition" structural."""

    # -- entry ----------------------------------------------------------
    def accept(self, order: Order, venue: Venue, ts: datetime, *,
               regime_tag: Optional[str] = None,
               encumbrances: Sequence[Encumbrance] = ()) -> OrderRecord:
        """Mint an id and admit the order in ACCEPTED. `time_in_force` comes
        from `TIME_IN_FORCE[order.order_type]`."""

    def reject(self, order: Order, venue: Venue,
               rejection: Rejected) -> OrderRecord:
        """Mint an id and record a REJECTED row. A rejected order still gets
        an id, so the rejection log joins to the submission."""

    # -- transitions ----------------------------------------------------
    def rest(self, order_id: OrderId, ts: datetime) -> OrderRecord:
        """ACCEPTED -> RESTING. Emits NO event: resting is a state, not news.
        Raises if `record.time_in_force.rests` is False — an MOK never rests,
        and putting one on the book is the shape-4 failure."""

    def apply_fill(self, order_id: OrderId,
                   fill: Fill) -> Tuple[OrderRecord, EventKind]:
        """Record a fill. The resulting state is COMPUTED from what remains,
        never passed in: a fill exhausting the remainder is FILLED whatever
        its size. Raises if it would break `filled + remaining == original`."""

    def cancel(self, order_id: OrderId,
               ts: datetime) -> Union[OrderRecord, Rejected]:
        """Caller cancellation. Legal from ACCEPTED, RESTING and
        PARTIALLY_FILLED — a half-filled resting order is exactly the one a
        caller cancels. Rejected(SESSION_SEMANTICS) when the order is already
        terminal, or when the phase forbids it: auctions are locked for their
        whole duration, including LOs carried in from the continuous session,
        and the HNX post-close session is locked too."""

    def expire(self, order_id: OrderId, ts: datetime,
               trigger: ExpiryTrigger) -> OrderRecord:
        """Expire one order. Raises if `trigger` is not in
        `TERMINAL_TRIGGERS_BY_TIF[record.time_in_force]` — that table is the
        per-type terminal edge, and an out-of-table trigger means the caller
        has invented a rule."""

    def expire_due(self, ts: datetime, venue: Venue, ending: SessionPhase,
                   beginning: SessionPhase) -> Tuple[OrderRecord, ...]:
        """Expire everything the phase change kills, per type. See
        `expires_at_boundary` for the rule."""

    # -- queries --------------------------------------------------------
    def get(self, order_id: OrderId) -> Optional[OrderRecord]: ...
    def orders(self, *, state: Optional[OrderState] = None,
               ticker: Optional[str] = None,
               venue: Optional[Venue] = None) -> Tuple[OrderRecord, ...]: ...
    def live(self, *, ticker: Optional[str] = None) -> Tuple[OrderRecord, ...]:
        """Orders in ACCEPTED, RESTING or PARTIALLY_FILLED. What the fill
        policy is offered and what the net-of-live-orders figures sum over."""


def is_legal_transition(frm: OrderState, to: OrderState) -> bool:
    """Reads `LEGAL_TRANSITIONS`. The single enforcement point for
    invariant 2 — a terminal order state is never left."""


def expires_at_boundary(tif: TimeInForce, ending: SessionPhase,
                        beginning: SessionPhase) -> Optional[ExpiryTrigger]:
    """The trigger a phase change fires for this time-in-force, or None.

    The three cases to pin as tests, all from §12:
      * an unmatched ATO dies at the 09:15 cross    -> AUCTION_CROSS
      * the NOON BREAK expires NOTHING              -> None, always
      * a DAY order dies at the end of the last matching phase
                                                    -> SESSION_END

    There is no NOON_BREAK member of ExpiryTrigger. 11:30–13:00 is a hard
    shutdown for entry, amendment and cancellation, but resting orders survive
    it; a simulator that expires at every boundary destroys the afternoon
    book."""
```

---

## 7. `session/deposit.py` — segregated deposit and account-level margin

**Owns:** the derivatives account. **Locked shape 5.**

**Forbidden builds:** per-position rows; a margin function taking a lone
`Position`.

Vietnamese derivatives margin sits in a segregated deposit account ("ký
quỹ"), funded by an explicit transfer, with **independent purchasing power**.
Equity orders draw on securities cash only; futures margin draws on the
deposit only; a margin call resolves against the deposit only, and if the
deposit is short the position is force-liquidated and **securities cash is
untouched**. **There is no auto-transfer** — the caller must call
`transfer()`.

```python
class ContractLedger:
    """{contract_code: ContractPosition}, net-signed. Where shorts live."""

    def __init__(self) -> None: ...

    def apply_fill(self, fill: Fill, multiplier: Decimal,
                   expiry: Optional[date]) -> Optional[ContractPosition]:
        """Resolve open/close/net on one fill. Uses
        `types.signed_quantity(fill.side, fill.quantity)` — never
        `side.sign`, which returns None on Side.CROSS.

        A fill that flattens a position REMOVES the row and returns None, so
        `positions()` never shows a contract the account does not hold. A fill
        that crosses through flat (long 2, sell 5 -> short 3) resets
        `average_entry` to the fill price: the old average belongs to a
        position that no longer exists."""

    def position(self, contract_code: str) -> Optional[ContractPosition]: ...
    def positions(self) -> Dict[str, ContractPosition]:
        """`session.positions()`. Flat contracts are absent, not zero."""

    def net_quantity(self, contract_code: str) -> int:
        """Signed. What POSITION_LIMIT is tested against, via abs()."""

    def remove(self, contract_code: str) -> Optional[ContractPosition]:
        """Expiry settlement removes the contract from the ledger."""

    def total_contracts(self) -> int:
        """Σ |net| over all contracts."""


class DerivativesAccount:
    """DepositLedger + ContractLedger + the margin view."""

    def __init__(self, ref: AccountRef, initial_deposit: Decimal,
                 terms: BrokerTerms, encumbrances: EncumbranceLedger,
                 contracts: ContractLedger) -> None: ...

    @property
    def deposit_balance(self) -> Decimal:
        """Margin ASSETS. Cash-settled: daily P&L leaves or enters as cash on
        T+1, so the deposit does NOT accumulate mark-to-market."""

    def credit(self, amount: Decimal, ts: datetime, reason: str) -> None: ...
    def debit(self, amount: Decimal, ts: datetime, reason: str) -> None: ...

    def reserve_for_order(self, order_id: OrderId, order: Order,
                          price: Decimal, rules: RuleSet, profile: BrokerProfile,
                          ts: datetime) -> Union[Encumbrance, Rejected]:
        """Margin for a resting derivative order. Resting orders MUST
        contribute to MR, or a caller can rest futures orders it cannot fund.
        Short -> Rejected(INSUFFICIENT_DEPOSIT, binding_constraint=free).
        Over the cap -> Rejected(POSITION_LIMIT, binding_constraint=cap)."""

    def release(self, order_id: OrderId, ts: datetime) -> None:
        """The terminal hook, derivatives side."""

    def apply_fill(self, fill: Fill, rules: RuleSet, ts: datetime) -> None:
        """Net the contract ledger and convert order margin into posted."""

    def margin(self, marks: Mapping[str, Decimal], rules: RuleSet,
               terms: BrokerTerms, ts: datetime, *,
               resting: Sequence[OrderRecord] = ()) -> MarginView:
        """Delegates to `account_margin_requirement`. `session.margin()`."""


def account_margin_requirement(account: DerivativesAccount,
                               marks: Mapping[str, Decimal],
                               rules: RuleSet, terms: BrokerTerms,
                               ts: datetime, *,
                               resting: Sequence[OrderRecord] = ()
                               ) -> MarginView:
    """THE margin entry point. Takes the WHOLE ACCOUNT, never a lone Position.

        MR          = IM + VM        over the whole account portfolio
                      IM = initial requirement recomputed on the CURRENT
                           price (last match in-session, DSP end of day) —
                           NOT on entry notional
                      VM = variation margin, counted ONLY when the account is
                           in loss; a favourable move contributes zero
        assets      = deposit_balance
        utilisation = MR / assets -> warning ≥ 0.80, call ≥ 0.90, forced ≥ 1.00

    Four separately testable facts in that block: IM on the CURRENT price; VM
    loss-only, marked against the PREVIOUS daily settlement price and not
    symmetric around entry the way `margin.py:106` computes it; assets =
    deposit_balance with no MTM accumulation; thresholds from `BrokerTerms`.

    **Tier 1 may sum strict per-position IM and skip spread credits.** That
    over-charges and never under-charges, which is the conservative direction,
    and the spread-credit values are UNVERIFIED. What is NOT optional is that
    this function takes the account — so the netting engine slots in without
    re-plumbing every call site.

    Reuses and aggregates `margin.py` primitives. It must NOT call
    `Exchange.sustains()`: that takes a whole `Sequence[MarketState]` in one
    batch, has nowhere to carry an outstanding call between days, and ~20
    tests pin the batch form. `sustains()` stays untouched as the batch
    research path.

    There is NO maintenance margin ratio in Vietnamese rules at any date.
    `margin.MarginConfig.maintenance_rate` models a quantity that does not
    exist; do not build on it.
    """


class MarginMonitor:
    """The day-loop state machine. Tier 2 BUILD; the shape is fixed here.

        day T   mark -> assets no longer cover MR -> MarginCall(cure_by)
                caller may transfer, reduce, or do nothing
        day T+1 re-mark -> still short -> ForcedLiquidation
                        -> restored   -> call cleared

    Carrying an outstanding call ACROSS DAYS is the whole reason this is a
    class and not a function, and the reason `sustains()` cannot be reused.
    """

    def __init__(self, terms: BrokerTerms, calendar: TradingCalendar, *,
                 liquidation: LiquidationRule = LiquidationRule.LARGEST_LOSS_FIRST
                 ) -> None: ...

    def on_mark(self, account: DerivativesAccount, view: MarginView,
                rules: RuleSet, ts: datetime) -> Tuple[MarginView, ...]:
        """One daily mark. Advances warning -> call -> forced, sets
        `cure_by = calendar.next_session_open(...)` when a call opens, and
        clears the call when utilisation recovers below the call level."""

    @property
    def outstanding_call(self) -> Optional[datetime]:
        """`cure_by` of an unanswered call, else None."""
```

**Adopted, and to be stated in any published result:**

- A transfer arrives **immediately** during trading hours. Intra-day transfer
  timing is not modelled.
- The margin-call cure window is the **next session**. This is a **broker
  term**, confirmed by the rulebook as an important negative finding: the
  cure window's length is a commercial term in the account-opening agreement,
  not an exchange or statutory number. It must live in `BrokerTerms`, never
  in the rulebook.
- `LiquidationRule.LARGEST_LOSS_FIRST` is a **modelling choice, not a sourced
  rule**. No Vietnamese document prescribes a selection order for a broker's
  forced close. `ForcedLiquidation` must state its selection rule, the
  contracts closed, the price used and the resulting deposit balance —
  `Event.margin(...)` carries all four in `detail`.
- `ExpirySettled` is a cash movement into or out of the deposit at the
  index-referenced final settlement, **with the contract removed from the
  ledger**. Tier 1 reads the data source's `close` on the expiry day as the
  settlement price — a declared simplification measured at 0.36% against the
  true 14:15–14:45 window mean on one contract (n=1), and the settlement
  *basis* itself changed on 2022-08-17. **Do not report a pre-2022-08-17
  settlement figure as authoritative.**

---

## 8. `session/fills.py` — the fill policy extension point

**Owns:** fill determination. Standard practice applied to Vietnamese rules --
refuted as a novelty claim, see the design spec section 8. It is useful, not
a workaround for missing depth.

Three conventions are fixed here because §8's whole value is a *spread across
policies*, and a drifting convention contaminates the comparison:

1. **Fill price.** Call auction: the published open/close. Continuous session
   under no-impact replay: a limit order fills at **its own limit price** —
   the only non-arbitrary choice available.
2. **Fill quantity.** A `max_participation`-capped quantity is **floored to
   `instrument.trading_unit`**. Otherwise the ledger holds an odd lot that
   `ROUND_LOT` will later refuse to sell.
3. **`max_participation`** is a fraction of the volume observed in the
   evaluated interval, and it **aggregates across all of the caller's own
   live orders in that instrument** — not per order, or a caller splits one
   order into ten and evades the cap.

```python
class FillPolicy(Protocol):
    """Swappable fill determination."""

    kind: str

    def evaluate(self, order: OrderRecord, interval: MarketInterval,
                 rules: Exchange, *,
                 already_filled: int = 0) -> FillDecision:
        """Decide this order's fate over this interval.

        `rules` is the existing `exchanges.base.Exchange` object — the policy
        may consult `admits()` and the venue spec but never account state.
        `already_filled` is the caller's own aggregated fill quantity in this
        instrument over this interval, for the participation cap.

        Renamed from §8's `RestingOrder` to `OrderRecord`; see §2.4."""


class SoftFillPolicy:
    """Fill if the price traded at or through the limit, full size.

    What every backtester does today — the baseline arm, and the reason the
    spread is meaningful. Trivial, and shipped in TIER 1.
    """

    kind = 'soft'
    def __init__(self) -> None: ...
    def evaluate(self, order, interval, rules, *, already_filled=0
                 ) -> FillDecision: ...


class HardFillPolicy:
    """Fill only when the market demonstrably traded THROUGH the limit.

    Touched-at-limit -> `FillDecision.indeterminate(...)`, not a fill and not
    a no-fill: the queue position that would decide it is unrecoverable, and
    81% of best-quote changes carry no trade. Capped at `max_participation`
    of observed volume; where `interval.volume` is absent the cap cannot be
    computed and the decision degrades to INDETERMINATE naming
    `DataField.VOLUME`.

    What is defensible going live. Design §8 tiers this as Tier 2; the task
    that authored this contract scopes it into `fills.py` alongside Soft.
    Both ship; the comparison needs both anyway.
    """

    kind = 'hard'
    def __init__(self, max_participation: Decimal = Decimal('0.10')) -> None: ...
    def evaluate(self, order, interval, rules, *, already_filled=0
                 ) -> FillDecision: ...


def floor_to_lot(quantity: int, trading_unit: int) -> int:
    """Floor to a whole round lot. Convention 2 above."""


def participation_cap(interval: MarketInterval, max_participation: Decimal,
                      already_filled: int) -> Optional[int]:
    """Remaining quantity this instrument may take, or None when
    `interval.volume` is absent."""


def auction_fill_price(order: OrderRecord,
                       interval: MarketInterval) -> Optional[Decimal]:
    """The published open (ATO) or close (ATC). Convention 1 above."""
```

`ProbabilisticFillPolicy` is **not** in scope: it needs book sizes, and
`BookLevel.size` is `None` on every corpus here (`quote_asksize`,
`quote_bidsize`, `quote_totalask`, `quote_totalbid` are all 0-row in both
roots). A policy needing them names `DataField.BOOK_SIZE`.

`INDETERMINATE` is **not an order state**. The order stays `RESTING` and is
re-evaluated on the next interval; the event is recorded and counted.

---

## 9. `session/exchange.py` — `ExchangeSession`

**Owns:** the clock, the exchange registry, symbol routing, the event cursor,
and the caller-facing API. The only module that may import the other six.

Synchronous, call-and-response, deliberately close in shape to a broker API.
**Plutus never calls user code** — there is no strategy execution, no
portfolio, no P&L, no returns.

```python
class ExchangeSession:
    """A simulated Vietnamese exchange you point a strategy at."""

    @classmethod
    def from_config(cls, path: Union[str, Path]) -> 'ExchangeSession':
        """Build from the §6 config file. Parses into SessionConfig, builds
        the Rulebook with its pins, loads both calendars, constructs the two
        accounts, and selects the fill policy by `fill_policy.kind`."""

    def __init__(self, config: SessionConfig, source: MarketDataSource,
                 rulebook: Rulebook, router: SymbolRouter,
                 settlement: SettlementCalendar, trading: TradingCalendar,
                 fill_policy: FillPolicy, securities: SecuritiesAccount,
                 derivatives: DerivativesAccount, orders: OrderBookOfRecord,
                 monitor: Optional[MarginMonitor] = None) -> None: ...

    # -- clock ----------------------------------------------------------
    def now(self) -> datetime: ...

    def advance_to(self, ts: datetime) -> List[Event]:
        """Advance the clock and return the events generated — marks,
        settlement credits, fills, expiries, calls.

        Per advance, in order:
          1. for each phase boundary crossed: orders.expire_due(...)
          2. for each live order: fill_policy.evaluate(record, interval, rules)
          3. apply fills to both accounts; emit Filled / PartiallyFilled
          4. holdings.settle_due(now) and cash.settle_due(now)
                                          -> SettlementCredited
          5. cash.accrue_interest(now)
          6. derivatives daily mark -> MarginWarning / MarginCall /
             ForcedLiquidation; expiries -> ExpirySettled
          7. drain the cursor and return

        Expiry runs BEFORE fills, or an order that died at the cross can
        still fill in the phase that killed it."""

    def phase(self, venue: Union[Venue, str]) -> SessionPhase:
        """The phase at `now()` on that venue, from `rules.phase(venue)`.
        NEVER inferred from the timestamp alone."""

    # -- orders ---------------------------------------------------------
    def submit(self, order: Order) -> Union[Accepted, Rejected]:
        """Submit for admission and funding. See §1 for the exact call order.

        Takes `protocol.Order`, whose field is `ticker` — §5's example writes
        `symbol=`, and the existing frozen type wins."""

    def cancel(self, order_id: OrderId) -> Union[Cancelled, Rejected]: ...

    def amend(self, order_id: OrderId, *, quantity: Optional[int] = None,
              limit_price: Optional[Decimal] = None
              ) -> Union[Amended, Rejected]:
        """TIER 2. Shape fixed here so it is not retrofitted. Priority is
        preserved only on a pure quantity DECREASE; from 2025-05-05 one
        amendment may change price OR quantity, never both — a dated rule, so
        `rulebook.at(ts)` decides, not a constant. Amending must re-run the
        encumbrance so an amend-up cannot escape funding."""

    def orders(self, *, state: Optional[OrderState] = None,
               ticker: Optional[str] = None) -> Tuple[OrderRecord, ...]:
        """§5 writes `orders(status=OrderStatus.RESTING)`. The parameter is
        `state` and the enum is `OrderState`; see §2.4."""

    def poll(self) -> List[Event]:
        """Drain events since the last read of `poll()` or `advance_to()`.

        ONE CURSOR, DESTRUCTIVE, SINGLE-CONSUMER. `advance_to()` returns the
        events it generated AND consumes them. A strategy and a separate
        logger cannot both drain it, which is acceptable because all reporting
        is on the caller's side. `Event.dedupe_key` is `(order_id, kind, ts)`
        for a caller that wants one; `Event.seq` gives a total order."""

    # -- state the exchange legitimately knows --------------------------
    def holdings(self, ticker: str) -> Holding: ...
    def cash(self) -> Cash: ...
    def positions(self) -> Dict[str, ContractPosition]: ...
    def margin(self) -> MarginView: ...
    def charges(self) -> Tuple[Charge, ...]: ...

    def transfer(self, source: Pool, destination: Pool,
                 amount: Decimal) -> Union[Transferred, Rejected]:
        """Move cash between the two pools. Bounded by the NET figures in
        BOTH directions: out of securities by `Cash.available`, out of the
        deposit by `MarginView.free_deposit`. That bound is what stops a
        caller withdrawing the margin backing an open position.

        Short -> Rejected(INSUFFICIENT_CASH) or
        Rejected(INSUFFICIENT_DEPOSIT). Arrives immediately during trading
        hours — an adopted assumption. There is no auto-transfer anywhere."""

    # -- provenance, per §6.3 and §9.2 ----------------------------------
    def provenance(self) -> SessionProvenance:
        """What this run was configured with, including every pin recorded as
        an override. A pinned run reports that it was pinned — that is the
        difference between a counterfactual and a lie."""

    def indeterminate_report(self) -> IndeterminateReport:
        """How much of the run the data could not decide, counted by
        DataField and by rule. §9.2 requires the session to report this
        rate, and §8 makes it the honest headline: a bound on ignorance,
        not a fill rate."""

    def instrument(self, ticker: str,
                   ts: Optional[datetime] = None) -> InstrumentSpec:
        """The instrument as of `ts` (default `now()`). Delegates to
        SymbolRouter — a per-event call, never a cached lookup."""


#: §5 writes `Session.from_config`. The module name is `exchange.py`, so the
#: class is `ExchangeSession` and this alias keeps the spec's example valid.
Session = ExchangeSession
```

**The Tier 1 deliverable is one screen:**

```python
session = ExchangeSession.from_config('config.json')
ack = session.submit(Order(ticker='FPT', side=Side.BUY, quantity=1000,
                           order_type=OrderType.LIMIT,
                           limit_price=Decimal('95.5')))
session.advance_to(same_day_afternoon)
rej = session.submit(Order(ticker='FPT', side=Side.SELL, quantity=1000,
                           order_type=OrderType.LIMIT,
                           limit_price=Decimal('96.0')))
# Rejected(rule=UNSETTLED_HOLDING, binding_constraint=0,
#          sellable_from=datetime(..., 13, 0))
```

---

## 10. Build order and what each module needs from the one before it

| # | Module | Blocked on | Blocks |
|---|---|---|---|
| 1 | `rulebook.py` | `types.py` | everything — it is the one mistake that propagates everywhere |
| 2 | `calendar.py` | `types.py` | `ledgers` (settlement instants), `deposit` (cure window) |
| 3 | `orders.py` | `types.py` | `exchange` |
| 4 | `ledgers.py` | `calendar`, `rulebook` | `exchange`; the Tier 1 demo |
| 5 | `deposit.py` | `calendar`, `rulebook` | `exchange` |
| 6 | `fills.py` | `types.py` | `exchange` |
| 7 | `exchange.py` | all six | the deliverable |

1–3 and 6 are independent of each other and can be written in parallel.

---

## 11. Tests each module owes

Pin **behaviour and the reasoning behind it**, with a docstring naming the
rule. Do not pin a number until it appears in the rulebook with a citation
and a confidence level.

**`rulebook.py`**
- HOSE round lot is 10 on 2020-06-15 and 100 on 2021-06-15.
- UPCoM `legal_order_types` is `{LO}` at every date and phase; an MTL on
  UPCoM is refused. (It is currently admitted.)
- HSX continuous accepts MP and not MTL on 2024-01-02, and MTL and not MP on
  2025-06-02. Same call, same venue, two dated answers — this is shape 1.
- `OrderType.MARKET` ('MKT') is legal at no venue on any date.
- LO **is** legal in a call auction; the market family is not.
- `edition_at` returns PRE_KRX on 2025-05-04 and POST_KRX on 2025-05-05.
- `rules.phase(HSX)` at 12:00 is `NOON_BREAK`, not `CONTINUOUS` — the
  noon-break-before-lo_session ordering.

**`calendar.py`**
- 2026-02-12 + T+2 settles 2026-02-23, not 2026-02-16 (VSDC closed
  02-16→02-20). Adding two *trading* days gives the wrong answer.
- Under `T+2 @ 13:00` on midnight-stamped daily bars, the T+2 bar does not
  clear the threshold and the T+3 bar does.
- The pre-2022-08-29 regime makes shares sellable at the T+3 open and not in
  the T+2 afternoon.
- Asking for a day outside the loaded coverage raises.

**`ledgers.py`**
- **Invariant 4, the one test that catches the leak class:** Σ encumbrance
  over live orders equals `Cash.committed` + `Holding.committed` +
  `posted/resting` deposit margin, and all fall to zero when no order is live.
- Two individually-affordable resting buys cannot both be accepted when their
  sum exceeds `available`.
- 500 settled shares cannot back 1,000 shares of resting sells.
- A limit buy reserved at 95.5 that fills at 95.0 releases the difference —
  `available` does not leak.
- A sell whose settled quantity is short returns
  `Rejected(UNSETTLED_HOLDING)` carrying a `sellable_from` that matches the
  covering tranche's instant.
- A buy is `Rejected(INSUFFICIENT_CASH)` when available is short **even
  though pending proceeds would cover it**.
- Two open tranches with different instants: the earlier one's settlement
  does not free the later one's shares (the shape-3 failure), and the later
  one does not block the earlier one.
- A sale credits **net** of the 0.1% sell-side PIT.

**`orders.py`**
- `filled + remaining == original` after every partial fill.
- No transition out of any terminal state.
- An MOK never occupies `RESTING`.
- An unmatched ATO expires at the 09:15 cross with
  `ExpiryTrigger.AUCTION_CROSS`.
- **The noon break expires nothing.** Resting orders survive 11:30→13:00.
- A partially-filled resting order can be cancelled, and the residue's
  encumbrance is released.
- `on_terminal` fires exactly once per order, on all four terminal edges.

**`deposit.py`**
- The margin entry point takes the account: calling it with one position is
  a type error, not a supported path.
- A favourable move contributes **zero** VM; an adverse move of the same size
  adds to MR. (Not symmetric.)
- IM recomputes on the current price, so MR moves with the market on a
  position whose P&L is flat.
- Utilisation crosses 0.80 / 0.90 / 1.00 into three distinct statuses.
- A securities-cash balance does not answer a derivatives margin call.
- A transfer out of the deposit is refused when it would drop `free_deposit`
  below zero with a position open.
- A SELL on HNXDS opens a short; a SELL on HSX with no holdings is
  `Rejected(UNSETTLED_HOLDING)`.

**`fills.py`**
- Touched-at-limit: Soft fills, Hard returns INDETERMINATE.
- A participation-capped quantity is a whole round lot.
- Absent `interval.volume`, Hard returns INDETERMINATE naming
  `DataField.VOLUME`.
- An INDETERMINATE leaves the order `RESTING`, and the next interval
  re-evaluates it.

**`exchange.py`**
- The Tier 1 demo end to end.
- `advance_to()` consumes what it returns; a following `poll()` is empty.
- A run spanning 2025-05-05 gets pre-KRX rules on one side and post-KRX on
  the other, in one session.
- `provenance()` lists every pin.

---

## 12. Open decisions, and how this contract settles them

| # | Question | Settled as | Status |
|---|---|---|---|
| 1 | `Order.symbol` vs `.ticker` | `ticker` — the existing frozen type wins | settled |
| 2 | `OrderStatus.RESTING` missing | new `OrderState` enum | settled |
| 3 | `positions()` return type | `ContractPosition`, net-signed | settled |
| 4 | `Cash.advanced` vs `advanced_proceeds` | `advanced` | settled |
| 5 | config keys vs `BrokerTerms` fields | `BROKER_CONFIG_KEYS` + `BrokerProfile.from_config`; `margin_buffer` lives on `BrokerProfile` | settled |
| 6 | session phase "derivable from ts" vs "never infer" | **never infer** — `protocol.py` wins; the adapter/rulebook sets it | settled |
| 7 | `ForcedLiquidation` selection rule and price | `LARGEST_LOSS_FIRST`, at the settlement price; **a modelling choice**, stated in `detail` | settled, declared unsourced |
| 8 | Resting order across an ex-date: scaled or cancelled? | **OPEN.** The hook exists (`apply_corporate_action`); Tier 1 has no CA engine and a run spanning an ex-date is wrong for that instrument | open |
| 9 | UNVERIFIED settlement dates / margin ratios / tick and lot tables | mostly discharged by the rulebook; take every value from there with its citation and confidence | settled |
| 10 | `INDETERMINATE` at admission — reject or refuse? | `Rejected` with `verdict=INDETERMINATE`; keeps §12's graph unchanged and keeps the two countable apart | settled |
| 11 | `AdmissionRule` has no funding/settlement member | `StatefulRule`, to be **merged into** `AdmissionRule`; see §2.1 | settled, action required |
| 12 | Foreign room | out of scope: the account is never classified as foreign, `is_foreign` defaults False, the rule short-circuits. Declared limitation T1. Note `quote_foreignroom` **does** exist and is the REMAINING room, not the cap — the README is wrong | declared |

---

## 13. What is explicitly out of Tier 1

`amend()` implementation · `ProbabilisticFillPolicy` · tick-driven clock with
ATO/ATC/PLO reachable from data · auction fills at the published open/close ·
the margin-call state machine, cure window and forced liquidation as a *built*
loop (`MarginMonitor`'s shape is fixed, its behaviour is Tier 2) ·
foreign-room enforcement · corporate actions · post-KRX rule *values* (the
resolution *mechanism* is Tier 1) · tiered broker commissions · put-through
trading.

An omission that is **declared** is not a defect; a silent one is.
