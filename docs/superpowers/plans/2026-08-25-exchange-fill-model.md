# `plutus.market` Exchange Fill Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an executable model of Vietnamese exchange fill rules — order admission for the equity exchanges (HSX/HNX/UPCOM) and position survival for the derivatives exchange (HNXDS) — and measure what ignoring them costs.

**Architecture:** A new `plutus.market` package. One `Exchange` ABC with two method families: `admits(order, state) -> Admissibility` (stateless) and `sustains(position, path) -> Viability` (stateful). Exchanges read a static `ExchangeSpec` rulebook from `plutus.core.constant`. All market data crosses a granularity-agnostic `MarketState` boundary supplied by an adapter, so the same rules run at daily-bar and tick resolution and the package never imports a data vendor.

**Tech Stack:** Python 3.12, `decimal.Decimal` for all prices, `dataclasses` (frozen), `enum.Enum` with `str` mixin, DuckDB via the existing `plutus.datahub`, pytest.

**Source spec:** `docs/superpowers/specs/2026-08-24-exchange-fill-model-design.md`

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Interpreter:** `/Users/nadan/.pyenv/versions/3.12.4/bin/python3`. A bare `python3` resolves to 3.9 and lacks deps. **Never use `cd` in the same shell command as a Python invocation** — it drops PATH to system Python.
- **Test command:** `PYTHONPATH=src PLUTUS_DATA_ROOT=/Users/nadan/algotrade-research/dataset/hermes-parquet /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest -q`
- **Baseline:** 450 tests collected, 450 passed. Every task must leave the suite green and must state the new expected total.
- **Corpora:** Parquet (daily + bands, no ticks) `/Users/nadan/algotrade-research/dataset/hermes-parquet`. Raw CSV archive (ticks + 3-level book) `/Users/nadan/algotrade-research/dataset/hermes-offline-market-data-pre-2023`.
- **Prices are `Decimal`, never `float`.** `DAILY_TRADING_LIMIT` holds floats in source; convert with `Decimal(str(x))`.
- **Every reason enum is `class X(str, Enum)`.** Load-bearing, not style: `evaluation.contract.json_safe` passes plain enums and datetimes through unchanged and `json.dumps` then raises.
- **Do not modify `plutus/evaluation/contract.py`** — 169 tests pin it.
- **Do not import `plutus.core.position`, `transaction`, `portfolio`, `algorithm`, or `bot`** — all five raise `ModuleNotFoundError: No module named 'utils'` (bare `import utils` at `position.py:35`, `transaction.py:74`). Importable and safe: `plutus.core.constant`, `plutus.core.instrument`, `plutus.core.order`.
- **Do not import `plutus.data.datahub`** — raises `ImportError: cannot import name 'QuoteNamedTuple'`.
- **`plutus.market` must not import any WP6/regime module.** `regime_tag` is caller-supplied.
- **Dates are end-exclusive everywhere** (`datahub/utils/date_utils.py:53-69`).
- **No new third-party dependency.** `hypothesis` is not installed and must not be added; property-style tests use deterministic exhaustive sweeps.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/plutus/core/constant.py` | **Modify.** Rename `Exchange` → `ExchangeSpec` (rulebook data only). |
| `src/plutus/market/__init__.py` | Public exports. |
| `src/plutus/market/protocol.py` | Value types: `Side`, `OrderType` re-export, `Order`, `Position`, `BookLevel`, `OrderBook`, `MarketState`, `InstrumentSpec`, `InstrumentKind`, `SessionPhase`, `LockEvidence`, `BandSource`, `Resolution`. |
| `src/plutus/market/verdicts.py` | Outcome types: `Verdict`, `AdmissionRule`, `Admissibility`, `PositionEventKind`, `SettlementSource`, `PositionEvent`, `Viability`, and their `to_dict()`. |
| `src/plutus/market/exchanges/base.py` | `Exchange` ABC. |
| `src/plutus/market/exchanges/equity.py` | `EquityExchange` — one class parameterized by `ExchangeSpec`; HSX/HNX/UPCOM are instances. |
| `src/plutus/market/exchanges/derivatives.py` | `HNXDSExchange` — margin, position limit, expiry. |
| `src/plutus/market/margin.py` | `MarginConfig`, variation-margin arithmetic. |
| `src/plutus/market/expiry.py` | Third-Thursday expiry, contract-code parsing. |
| `src/plutus/market/adapters/base.py` | `MarketDataSource` protocol. |
| `src/plutus/market/adapters/datahub.py` | Daily adapter over `plutus.datahub`, incl. band reconstruction. |
| `src/plutus/market/adapters/tick.py` | Tick/book adapter over the raw CSV archive. |
| `tests/market/…` | Mirrors the above, one test module per source module. |
| `tests/market/conftest.py` | Shared corpus/tick-root gating (the repo has no shared conftest today). |
| `measurements/equity_admission.py` | Blocked-fill measurement, both lag variants. |
| `measurements/grid_conformity.py` | Tick-grid conformity, library rule vs a **defined** naive baseline. |
| `measurements/margin_incidence.py` | Derivatives margin incidence. |
| `measurements/bar_vs_tick.py` | Divergence on one common population. |

---

## Phase A — Foundation and the equity exchanges (Tasks 1–8)

Delivers order admission and the equity headline. This is the minimum viable paper; a slip after Phase A degrades gracefully.

---

### Task 1: Rename `constant.Exchange` → `ExchangeSpec`

Frees the name `Exchange` for the behavioral class. The old class is a static rulebook: name, code, sessions, trading unit, daily limit, tick function.

**Files:**
- Modify: `src/plutus/core/constant.py:1`, `:217`, `:218`, `:304`, `:343`, `:382`, `:413`
- Modify: `src/plutus/core/instrument.py:26`, `:31` (comment text only)
- Test: `tests/market/test_exchange_spec.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `plutus.core.constant.ExchangeSpec` (dataclass, 12 fields); module-level instances `HSX`, `HNX`, `UPCOM`, `DS` unchanged in name and value.

**Why this is safe:** zero importers. Every `from plutus.core.constant import` in the repo imports only `VietnamMarketConstant` (6 sites). `src/plutus/core/__init__.py` is 0 bytes. No `import *` anywhere. No Sphinx autodoc covers `plutus.core`. No test covers `constant.py` beyond one `TRADING_DAYS_PER_YEAR` assertion.

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_exchange_spec.py
"""The renamed rulebook: ExchangeSpec carries published exchange rules as data."""

from decimal import Decimal

import pytest

from plutus.core.constant import DS, HNX, HSX, UPCOM, ExchangeSpec, VietnamMarketConstant


def test_exchange_spec_is_the_rulebook_type():
    assert isinstance(HSX, ExchangeSpec)
    assert isinstance(HNX, ExchangeSpec)
    assert isinstance(UPCOM, ExchangeSpec)
    assert isinstance(DS, ExchangeSpec)


def test_old_name_is_gone():
    """The name Exchange is reserved for the behavioral class in plutus.market."""
    import plutus.core.constant as c

    assert not hasattr(c, 'Exchange')


@pytest.mark.parametrize(
    'spec, code, unit, limit',
    [
        (HSX, 'HSX', 100, Decimal('0.07')),
        (HNX, 'HNX', 100, Decimal('0.1')),
        (UPCOM, 'UPCOM', 100, Decimal('0.15')),
        (DS, 'HNXDS', 1, Decimal('0.07')),
    ],
)
def test_rulebook_values_survive_the_rename(spec, code, unit, limit):
    assert spec.code == code
    assert spec.trading_unit == unit
    # daily_trading_limit is a float in source; compare via Decimal(str(...))
    assert Decimal(str(spec.daily_trading_limit)) == limit


def test_module_docstring_no_longer_has_the_four_quote_typo():
    import plutus.core.constant as c

    assert c.__doc__ is not None
    assert not c.__doc__.startswith('"')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_exchange_spec.py -q`
Expected: FAIL — `ImportError: cannot import name 'ExchangeSpec' from 'plutus.core.constant'`

- [ ] **Step 3: Apply the rename**

In `src/plutus/core/constant.py` make exactly these edits:

Line 1 — fix the 4-quote typo and the class name:
```python
"""Defines the class ExchangeSpec and other related methods."""
```

Line 217:
```python
class ExchangeSpec:
```

Line 218 (first docstring line):
```python
    """The class ExchangeSpec contains the published rules of a specific exchange.
```

Lines 304, 343, 382, 413 — the four instantiations (all keyword-only):
```python
HSX = ExchangeSpec(
HNX = ExchangeSpec(
UPCOM = ExchangeSpec(
DS = ExchangeSpec(
```

Leave `working_day = (List[int],)` at `:229` **exactly as is**. It is an assignment, not an annotation, so it is not a dataclass field (`dataclasses.fields()` returns 12 fields and does not include it). Converting it would change the positional signature of all four instantiations. Add one comment above it:
```python
    # NOTE: not a dataclass field -- this is an assignment, not an annotation, so
    # dataclasses.fields() omits it. Left as-is deliberately; converting it would
    # change the positional signature of the four instantiations below. See
    # docs/superpowers/plans/2026-08-25-exchange-fill-model.md Task 1.
    working_day = (List[int],)
```

In `src/plutus/core/instrument.py`, update the two comments that name the old class:
- `:26` `#  (the class ExchangeSpec where different exchanges are defined as some kind of data).`
- `:31` `#  newly defined ExchangeSpec class because it is somehow still a data container.`

- [ ] **Step 4: Run the new test and the full suite**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_exchange_spec.py -q`
Expected: PASS (5 tests)

Run: `PYTHONPATH=src PLUTUS_DATA_ROOT=/Users/nadan/algotrade-research/dataset/hermes-parquet /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest -q`
Expected: `455 passed` (450 baseline + 5 new)

- [ ] **Step 5: Commit**

```bash
git add src/plutus/core/constant.py src/plutus/core/instrument.py tests/market/test_exchange_spec.py
git commit -m "Rename constant.Exchange to ExchangeSpec, freeing Exchange for the model"
```

---

### Task 2: `protocol.py` — the value types

Every type the exchanges consume. All frozen, all `Decimal` for prices, all reason enums `str`-mixed.

**Files:**
- Create: `src/plutus/market/__init__.py`
- Create: `src/plutus/market/protocol.py`
- Test: `tests/market/test_protocol.py`

**Interfaces:**
- Consumes: `plutus.core.order.Side`, `plutus.core.order.OrderType` (both importable — verified).
- Produces: `Side`, `OrderType`, `Order`, `Position`, `BookLevel`, `OrderBook`, `MarketState`, `InstrumentKind`, `InstrumentSpec`, `SessionPhase`, `LockEvidence`, `BandSource`, `Resolution`.

**Design notes an implementer must not re-litigate:**
- `MarketState.ceiling`/`floor` are **`Decimal | None`** with a `band_source` tag. Only 88.25% of 2021 stock close ticker-days have a ceiling row; 26 dates have a reference and no ceiling; VN30F has 128 closes with no band. A rule that needs an absent band returns `INDETERMINATE`.
- `BookLevel.size` is **always `None` on this machine**. `quote_asksize`, `quote_bidsize`, `quote_totalask`, `quote_totalbid` are 0-row in **both** corpora. The field exists so the type is right; no code may require it.
- `MarketState.session` is **set explicitly by the adapter, never inferred from `ts`**. A daily bar's `ts` is midnight, and `HSX.before_trading_session.is_current(midnight)` is `True` — inferring would mark every daily bar pre-open and reject the entire equity measurement.

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_protocol.py
"""Value types crossing the exchange boundary."""

import dataclasses
from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.protocol import (
    BandSource,
    BookLevel,
    InstrumentKind,
    InstrumentSpec,
    LockEvidence,
    MarketState,
    Order,
    OrderBook,
    Position,
    Resolution,
    SessionPhase,
    Side,
)


def test_all_reason_enums_are_str_mixed():
    """Load-bearing: json_safe passes bare enums through and json.dumps then raises."""
    for enum_cls in (SessionPhase, LockEvidence, BandSource, Resolution, InstrumentKind):
        member = next(iter(enum_cls))
        assert isinstance(member, str), enum_cls.__name__


def test_value_types_are_frozen():
    for cls in (Order, Position, BookLevel, OrderBook, MarketState, InstrumentSpec):
        assert dataclasses.fields(cls) is not None
        params = getattr(cls, '__dataclass_params__')
        assert params.frozen is True, cls.__name__


def test_market_state_bands_are_optional_with_provenance():
    """Bands are missing for a real fraction of ticker-days; absence must be sayable."""
    state = MarketState(
        ticker='FPT',
        ts=datetime(2022, 3, 29),
        reference=Decimal('95.0'),
        ceiling=None,
        floor=None,
        band_source=BandSource.ABSENT,
        session=SessionPhase.CONTINUOUS,
    )
    assert state.ceiling is None
    assert state.band_source is BandSource.ABSENT


def test_market_state_defaults_are_honest_about_absence():
    state = MarketState(ticker='FPT', ts=datetime(2022, 3, 29))
    assert state.ceiling is None
    assert state.floor is None
    assert state.reference is None
    assert state.last is None
    assert state.book is None
    assert state.foreign_room is None
    assert state.locked_side is None
    assert state.lock_evidence is LockEvidence.UNKNOWN
    assert state.band_source is BandSource.ABSENT
    assert state.session is SessionPhase.UNKNOWN


def test_book_level_size_is_optional_because_no_corpus_has_sizes():
    level = BookLevel(price=Decimal('95.5'))
    assert level.size is None


def test_order_book_holds_up_to_three_levels_per_side():
    book = OrderBook(
        asks=(BookLevel(Decimal('95.5')), BookLevel(Decimal('95.6'))),
        bids=(BookLevel(Decimal('95.4')),),
        as_of=datetime(2022, 3, 29, 10, 15),
    )
    assert len(book.asks) == 2
    assert len(book.bids) == 1


def test_order_requires_a_limit_price_only_for_limit_orders():
    o = Order(ticker='FPT', side=Side.BUY, quantity=100, limit_price=Decimal('95.5'))
    assert o.is_foreign is False
    assert o.limit_price == Decimal('95.5')


def test_position_defaults_multiplier_to_one_and_margin_to_none():
    p = Position(
        ticker='VN30F2212',
        exchange_code='HNXDS',
        side=Side.BUY,
        quantity=1,
        entry_price=Decimal('1441.8'),
        entry_ts=datetime(2022, 4, 22),
    )
    assert p.multiplier == Decimal('1')
    assert p.posted_margin is None
    assert p.stop_price is None


def test_instrument_spec_carries_expiry_and_underlying_for_derivatives():
    spec = InstrumentSpec(
        ticker='VN30F2212',
        exchange_code='HNXDS',
        kind=InstrumentKind.FUTURE,
        trading_unit=1,
        daily_trading_limit=Decimal('0.07'),
        multiplier=Decimal('100000'),
        expiry=date(2022, 12, 15),
        underlying='VN30',
    )
    assert spec.kind is InstrumentKind.FUTURE
    assert spec.expiry == date(2022, 12, 15)


def test_resolution_values_are_the_two_the_adapters_support():
    assert Resolution.DAILY.value == '1d'
    assert Resolution.TICK.value == 'tick'
    assert len(list(Resolution)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_protocol.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'plutus.market'`

- [ ] **Step 3: Write the implementation**

```python
# src/plutus/market/__init__.py
"""An executable model of Vietnamese exchange fill rules.

This package models what an **exchange** does to an order and to a position:
the tick-grid, lot, price-band, session and foreign-room checks run before an
order may rest on the book, and the margin, position-limit and expiry logic a
derivatives exchange runs against an open position each day.

It does NOT model the trader's side. There is no strategy, portfolio, cash
balance or P&L here; no order lifecycle, queue-priority matching or
partial-fill sequencing; and no decision about what to do after a margin call
-- only the report that the exchange would issue one. Exchange-side fill
model, not trader-side execution engine.

Market data crosses a single granularity-agnostic boundary (:class:`MarketState`)
supplied by an adapter, so the same rules run on daily bars and on ticks and
this package imports no data vendor.
"""

from plutus.market.protocol import (
    BandSource,
    BookLevel,
    InstrumentKind,
    InstrumentSpec,
    LockEvidence,
    MarketState,
    Order,
    OrderBook,
    OrderType,
    Position,
    Resolution,
    SessionPhase,
    Side,
)

__all__ = [
    'BandSource',
    'BookLevel',
    'InstrumentKind',
    'InstrumentSpec',
    'LockEvidence',
    'MarketState',
    'Order',
    'OrderBook',
    'OrderType',
    'Position',
    'Resolution',
    'SessionPhase',
    'Side',
]
```

```python
# src/plutus/market/protocol.py
"""Value types crossing the exchange boundary.

Every price is a :class:`~decimal.Decimal`. Every reason enum mixes in ``str``:
:func:`plutus.evaluation.contract.json_safe` passes a bare ``Enum`` through
unchanged and ``json.dumps`` then raises, so the mixin is what makes verdicts
serialisable at all.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional, Tuple

# Both are importable and safe (unlike plutus.core.position / transaction /
# portfolio / algorithm / bot, which all raise on a bare `import utils`).
from plutus.core.order import OrderType, Side

__all__ = [
    'BandSource', 'BookLevel', 'InstrumentKind', 'InstrumentSpec',
    'LockEvidence', 'MarketState', 'Order', 'OrderBook', 'OrderType',
    'Position', 'Resolution', 'SessionPhase', 'Side',
]


class SessionPhase(str, Enum):
    """Which phase of the trading day a state belongs to.

    Set explicitly by the adapter. **Never infer this from a timestamp**: a
    daily bar's ``ts`` is midnight, and the coded ``before_trading_session``
    reports ``is_current()`` True at midnight, so inference would mark every
    daily bar pre-open and reject an entire daily measurement.
    """

    PRE_OPEN = 'pre_open'
    OPENING_AUCTION = 'opening_auction'      # ATO -- HSX and HNXDS only
    CONTINUOUS = 'continuous'
    NOON_BREAK = 'noon_break'
    CLOSING_AUCTION = 'closing_auction'      # ATC -- not UPCOM
    POST_CLOSE_PLO = 'post_close_plo'        # PLO -- HNX only
    POST_CLOSE = 'post_close'
    UNKNOWN = 'unknown'


class LockEvidence(str, Enum):
    """How a band lock was established.

    Distinguishing these is what keeps the fillability rule honest: the
    resting-book evidence is authoritative, the bar proxy is an inference, and
    absence must be sayable rather than guessed.
    """

    TICK_BOOK = 'tick_book'   # forward-filled ask/bid ladder: authoritative
    BAR_PROXY = 'bar_proxy'   # last == ceiling (or == floor) on a daily bar
    UNKNOWN = 'unknown'       # -> the lock rule yields INDETERMINATE


class BandSource(str, Enum):
    """Where a state's ceiling/floor came from."""

    PUBLISHED = 'published'          # a quote_ceil / quote_floor row
    RECONSTRUCTED = 'reconstructed'  # derived from reference x limit, see adapters
    ABSENT = 'absent'                # no band available -> band rules INDETERMINATE


class Resolution(str, Enum):
    """The granularities an adapter may serve.

    Deliberately NOT ``OHLCQuery.INTERVALS``: its six intraday keys all raise
    ``FileNotFoundError`` eagerly on the Parquet root, which carries no ticks.
    """

    DAILY = '1d'
    TICK = 'tick'


class InstrumentKind(str, Enum):
    STOCK = 'stock'
    WARRANT = 'warrant'
    FUND = 'fund'
    FUTURE = 'future'
    INDEX = 'index'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class BookLevel:
    """One price level of a resting ladder.

    ``size`` is ``None`` on every corpus available here: ``quote_asksize``,
    ``quote_bidsize``, ``quote_totalask`` and ``quote_totalbid`` are all 0-row
    in both roots. The field exists so the type is correct; no rule may
    *require* it.
    """

    price: Decimal
    size: Optional[int] = None


@dataclass(frozen=True)
class OrderBook:
    """Up to three levels per side. Sides are not synchronised in time."""

    bids: Tuple[BookLevel, ...] = ()
    asks: Tuple[BookLevel, ...] = ()
    as_of: Optional[datetime] = None


@dataclass(frozen=True)
class MarketState:
    """Everything an exchange needs to judge one order at one instant.

    Whether this was built from a daily bar, a single tick or a book snapshot
    is the adapter's business. That is what lets one rule set run at both
    resolutions.
    """

    ticker: str
    ts: datetime
    reference: Optional[Decimal] = None
    ceiling: Optional[Decimal] = None
    floor: Optional[Decimal] = None
    band_source: BandSource = BandSource.ABSENT
    last: Optional[Decimal] = None
    book: Optional[OrderBook] = None
    session: SessionPhase = SessionPhase.UNKNOWN
    foreign_room: Optional[int] = None
    locked_side: Optional[Side] = None
    lock_evidence: LockEvidence = LockEvidence.UNKNOWN


@dataclass(frozen=True)
class InstrumentSpec:
    """Per-instrument facts the rulebook alone cannot supply."""

    ticker: str
    exchange_code: str
    kind: InstrumentKind
    trading_unit: int
    daily_trading_limit: Decimal
    multiplier: Decimal = Decimal('1')
    expiry: Optional[date] = None
    underlying: Optional[str] = None


@dataclass(frozen=True)
class Order:
    """An order as presented to an exchange for admission."""

    ticker: str
    side: Side
    quantity: int
    order_type: OrderType = OrderType.LIMIT
    limit_price: Optional[Decimal] = None
    is_foreign: bool = False


@dataclass(frozen=True)
class Position:
    """An open position, for position-survival evaluation.

    Deliberately NOT ``plutus.core.position.Position``: that module is
    unimportable, and it requires ``portfolio_id`` and ``capital`` -- portfolio
    concepts this package excludes by design.
    """

    ticker: str
    exchange_code: str
    side: Side
    quantity: int
    entry_price: Decimal
    entry_ts: datetime
    multiplier: Decimal = Decimal('1')
    posted_margin: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_protocol.py -q`
Expected: PASS (10 tests)

Run the full suite. Expected: `465 passed` (455 + 10).

- [ ] **Step 5: Commit**

```bash
git add src/plutus/market/__init__.py src/plutus/market/protocol.py tests/market/test_protocol.py
git commit -m "Add plutus.market value types with explicit absence and lock provenance"
```

---

### Task 3: `verdicts.py` — outcomes that survive `json.dumps`

**Files:**
- Create: `src/plutus/market/verdicts.py`
- Test: `tests/market/test_verdicts.py`

**Interfaces:**
- Consumes: `plutus.evaluation.contract.json_safe`.
- Produces: `Verdict`, `AdmissionRule`, `Admissibility`, `PositionEventKind`, `SettlementSource`, `PositionEvent`, `Viability`. Each outcome exposes `to_dict() -> dict`.

**Why `to_dict()` and not `json_safe` alone:** `json_safe` (`contract.py:76-112`) branches on `None`/`Decimal`/`float`/`dict`/`list`/`tuple` then passes anything else through. A bare `Enum` and a `datetime` both pass through and `json.dumps` raises `TypeError`. `json_safe` must not be modified — 169 tests pin it. So each outcome stringifies its temporals first, mirroring `audit.CheckResult.to_dict()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_verdicts.py
"""Outcome types, and the JSON contract they must satisfy."""

import json
from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.verdicts import (
    Admissibility,
    AdmissionRule,
    PositionEvent,
    PositionEventKind,
    SettlementSource,
    Verdict,
    Viability,
)


def _reject_non_finite(token):
    raise AssertionError(f'non-finite token {token!r} in verdict JSON')


def test_verdict_has_three_states_not_two():
    """A bool cannot carry INDETERMINATE, which absent data requires."""
    assert {v.value for v in Verdict} == {'admitted', 'rejected', 'indeterminate'}


def test_admission_rules_cover_the_six_checks():
    assert {r.value for r in AdmissionRule} == {
        'tick_grid', 'round_lot', 'band_limit', 'band_lock',
        'foreign_room', 'session_semantics',
    }


def test_band_limit_and_band_lock_are_distinct_rules():
    """One is stateless; the other needs lock provenance. Conflating them makes
    the equity headline unmeasurable at bar resolution."""
    assert AdmissionRule.BAND_LIMIT is not AdmissionRule.BAND_LOCK


def test_admissibility_round_trips_through_strict_json():
    a = Admissibility(
        verdict=Verdict.REJECTED,
        rule=AdmissionRule.TICK_GRID,
        binding_constraint=Decimal('0.05'),
        ts=datetime(2022, 3, 29, 10, 15, 30),
    )
    encoded = json.dumps(a.to_dict())
    decoded = json.loads(encoded, parse_constant=_reject_non_finite)

    assert decoded['verdict'] == 'rejected'
    assert decoded['rule'] == 'tick_grid'
    assert decoded['ts'] == '2022-03-29T10:15:30'
    assert decoded['binding_constraint'] == 0.05


def test_bare_json_safe_is_insufficient_which_is_why_to_dict_exists():
    """Documents the reason for to_dict(): json_safe passes enums/datetimes through."""
    from dataclasses import asdict

    from plutus.evaluation.contract import json_safe

    a = Admissibility(
        verdict=Verdict.ADMITTED, rule=None, binding_constraint=None,
        ts=datetime(2022, 3, 29),
    )
    # str-mixed enums survive; the datetime does not.
    with pytest.raises(TypeError):
        json.dumps(json_safe(asdict(a)))


def test_position_event_records_its_settlement_provenance():
    e = PositionEvent(
        kind=PositionEventKind.MARGIN_CALL,
        ts=datetime(2022, 5, 9),
        settlement=Decimal('1300.0'),
        settlement_source=SettlementSource.CLOSE_PROXY,
        equity=Decimal('10000'),
        notional=Decimal('130000000'),
        margin_ratio=Decimal('0.15'),
    )
    d = e.to_dict()
    assert d['kind'] == 'margin_call'
    assert d['settlement_source'] == 'close_proxy'
    assert json.loads(json.dumps(d))['ts'] == '2022-05-09T00:00:00'


def test_viability_round_trips_with_nested_events():
    v = Viability(
        survived=False,
        events=(
            PositionEvent(
                kind=PositionEventKind.MARGIN_CALL,
                ts=datetime(2022, 5, 9),
                settlement=Decimal('1300.0'),
                settlement_source=SettlementSource.CLOSE_PROXY,
                equity=Decimal('1'), notional=Decimal('2'),
                margin_ratio=Decimal('0.5'),
            ),
        ),
        days_evaluated=100,
        days_indeterminate=3,
    )
    decoded = json.loads(json.dumps(v.to_dict()), parse_constant=_reject_non_finite)
    assert decoded['survived'] is False
    assert len(decoded['events']) == 1
    assert decoded['days_indeterminate'] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_verdicts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'plutus.market.verdicts'`

- [ ] **Step 3: Write the implementation**

```python
# src/plutus/market/verdicts.py
"""What an exchange reports back, and how it serialises.

Each outcome carries a :meth:`to_dict` that stringifies temporals before
handing off to :func:`plutus.evaluation.contract.json_safe`. That function is
deliberately untouched -- 169 tests pin it -- and it passes bare enums and
datetimes through, so ``json.dumps`` would raise without this step.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional, Tuple, Union

from plutus.evaluation.contract import json_safe

__all__ = [
    'Admissibility', 'AdmissionRule', 'PositionEvent', 'PositionEventKind',
    'SettlementSource', 'Verdict', 'Viability',
]


class Verdict(str, Enum):
    """Three states, not two.

    ``INDETERMINATE`` is what makes the model honest: when the data needed to
    judge a rule is absent, saying so is required and guessing is forbidden.
    """

    ADMITTED = 'admitted'
    REJECTED = 'rejected'
    INDETERMINATE = 'indeterminate'


class AdmissionRule(str, Enum):
    """The rule that bound. This enum IS the rejected-order log."""

    TICK_GRID = 'tick_grid'
    ROUND_LOT = 'round_lot'
    BAND_LIMIT = 'band_limit'              # stateless: price outside [floor, ceiling]
    BAND_LOCK = 'band_lock'                # fillability: marketable into a locked band
    FOREIGN_ROOM = 'foreign_room'
    SESSION_SEMANTICS = 'session_semantics'


class SettlementSource(str, Enum):
    """Which settlement tier produced the price behind an event."""

    PUBLISHED = 'published'      # a real quote_settlementprice row
    TWAP_30M = 'twap_30m'        # time-weighted mean of matched price 14:15-14:45
    CLOSE_PROXY = 'close_proxy'  # quote_close -- the only tier on the Parquet root


class PositionEventKind(str, Enum):
    MARGIN_CALL = 'margin_call'
    FORCED_LIQUIDATION = 'forced_liquidation'
    EXIT_BLOCKED = 'exit_blocked'
    POSITION_LIMIT_EXCEEDED = 'position_limit_exceeded'
    EXPIRY_SETTLEMENT = 'expiry_settlement'


def _serialise(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Stringify temporals, then defer to the project's JSON guard."""
    out: Dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif hasattr(value, 'isoformat'):       # date
            out[key] = value.isoformat()
        else:
            out[key] = value
    return json_safe(out)


@dataclass(frozen=True)
class Admissibility:
    """Whether an exchange would accept one order at one instant."""

    verdict: Verdict
    rule: Optional[AdmissionRule]
    binding_constraint: Optional[Union[Decimal, int]]
    ts: datetime
    regime_tag: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def admitted(self) -> bool:
        """Convenience for callers that only care about the happy path.

        Note ``INDETERMINATE`` is not admitted -- absence of evidence is not
        evidence of admissibility.
        """
        return self.verdict is Verdict.ADMITTED

    def to_dict(self) -> Dict[str, Any]:
        return _serialise(asdict(self))


@dataclass(frozen=True)
class PositionEvent:
    """Something the exchange would do to an open position on a given day."""

    kind: PositionEventKind
    ts: datetime
    settlement: Optional[Decimal]
    settlement_source: SettlementSource
    equity: Optional[Decimal]
    notional: Optional[Decimal]
    margin_ratio: Optional[Decimal]
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _serialise(asdict(self))


@dataclass(frozen=True)
class Viability:
    """Whether a position survived a price path, and what happened along it."""

    survived: bool
    events: Tuple[PositionEvent, ...]
    days_evaluated: int
    days_indeterminate: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'survived': self.survived,
            'events': [e.to_dict() for e in self.events],
            'days_evaluated': self.days_evaluated,
            'days_indeterminate': self.days_indeterminate,
        }

    def first(self, kind: PositionEventKind) -> Optional[PositionEvent]:
        """The earliest event of a kind, or None."""
        for event in self.events:
            if event.kind is kind:
                return event
        return None
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_verdicts.py -q`
Expected: PASS (7 tests)

Full suite expected: `472 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/plutus/market/verdicts.py tests/market/test_verdicts.py
git commit -m "Add exchange verdict types with a working JSON contract"
```

---

### Task 4: `Exchange` ABC and `EquityExchange` — tick grid and round lot

**Files:**
- Create: `src/plutus/market/exchanges/__init__.py`
- Create: `src/plutus/market/exchanges/base.py`
- Create: `src/plutus/market/exchanges/equity.py`
- Test: `tests/market/test_equity_admission.py`

**Interfaces:**
- Consumes: `protocol.Order`, `protocol.MarketState`, `protocol.InstrumentSpec`, `verdicts.*`, `plutus.core.constant.ExchangeSpec` (Task 1).
- Produces: `Exchange` (ABC with `admits`/`sustains`), `EquityExchange`, and module-level instances `HSX_EXCHANGE`, `HNX_EXCHANGE`, `UPCOM_EXCHANGE`.

**One class, not three.** HSX/HNX/UPCOM differ only in fields already inside `ExchangeSpec` (`trading_unit`, `daily_trading_limit`, `tick_size_function`), so they are instances of one `EquityExchange`, not three subclasses.

**Two traps, both verified:**
- `get_hsx_tick_size` returns **`None`** for a price no band matches (e.g. negative, or `Infinity`) despite being annotated `-> Decimal`. The predicate must map `None` to `INDETERMINATE`, not assume a `Decimal`.
- Tick bands are **lower-inclusive / upper-exclusive**: `[0,10)`, `[10,50)`, `[50,inf)`. So `get_hsx_tick_size('FPT', Decimal('10'))` is `0.05`, not `0.01`. (`HANDOFF-IMPLEMENTATION-DEPRECATED.md:163` states the opposite; the code is authoritative.)

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_equity_admission.py
"""Equity-exchange admission: tick grid and round lot."""

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.exchanges.equity import HNX_EXCHANGE, HSX_EXCHANGE, UPCOM_EXCHANGE
from plutus.market.protocol import MarketState, Order, SessionPhase, Side
from plutus.market.verdicts import AdmissionRule, Verdict

TS = datetime(2022, 3, 29, 10, 15)


def _state(**kw):
    """A state that passes every rule not under test."""
    base = dict(
        ticker='FPT', ts=TS, session=SessionPhase.CONTINUOUS,
        reference=Decimal('95.0'),
        ceiling=Decimal('101.0'), floor=Decimal('89.0'),
        last=Decimal('95.0'),
    )
    base.update(kw)
    return MarketState(**base)


def _order(**kw):
    base = dict(ticker='FPT', side=Side.BUY, quantity=100,
                limit_price=Decimal('95.5'))
    base.update(kw)
    return Order(**base)


# --- tick grid -------------------------------------------------------------

@pytest.mark.parametrize(
    'price, admitted',
    [
        (Decimal('95.5'), True),    # on the 0.1 grid above 50
        (Decimal('95.55'), False),  # off the 0.1 grid
        (Decimal('9.99'), True),    # 0.01 grid below 10
        (Decimal('9.995'), False),
        (Decimal('25.05'), True),   # 0.05 grid on [10, 50)
        (Decimal('25.03'), False),
    ],
)
def test_hsx_tick_grid(price, admitted):
    state = _state(reference=price, ceiling=price * 2, floor=Decimal('0.01'),
                   last=price)
    result = HSX_EXCHANGE.admits(_order(limit_price=price), state)
    if admitted:
        assert result.verdict is Verdict.ADMITTED
    else:
        assert result.verdict is Verdict.REJECTED
        assert result.rule is AdmissionRule.TICK_GRID


def test_hsx_tick_band_boundary_is_lower_inclusive():
    """At exactly 10.00 the tick is 0.05, not 0.01. The code is authoritative."""
    state = _state(reference=Decimal('10'), ceiling=Decimal('20'),
                   floor=Decimal('1'), last=Decimal('10'))
    on_grid = HSX_EXCHANGE.admits(_order(limit_price=Decimal('10.05')), state)
    off_grid = HSX_EXCHANGE.admits(_order(limit_price=Decimal('10.01')), state)
    assert on_grid.verdict is Verdict.ADMITTED
    assert off_grid.verdict is Verdict.REJECTED
    assert off_grid.rule is AdmissionRule.TICK_GRID


def test_warrant_etf_exception_uses_the_one_cent_grid():
    """8 characters and a leading C/E/F -> 0.01 regardless of price."""
    state = _state(ticker='CFPT2314', reference=Decimal('120.5'),
                   ceiling=Decimal('130'), floor=Decimal('110'),
                   last=Decimal('120.5'))
    result = HSX_EXCHANGE.admits(
        _order(ticker='CFPT2314', limit_price=Decimal('120.51')), state)
    assert result.verdict is Verdict.ADMITTED


def test_eight_chars_without_cef_prefix_falls_through_to_the_bands():
    state = _state(ticker='ABCD1234', reference=Decimal('25'),
                   ceiling=Decimal('30'), floor=Decimal('20'), last=Decimal('25'))
    result = HSX_EXCHANGE.admits(
        _order(ticker='ABCD1234', limit_price=Decimal('25.01')), state)
    assert result.verdict is Verdict.REJECTED
    assert result.rule is AdmissionRule.TICK_GRID


def test_unmatched_price_yields_indeterminate_not_a_crash():
    """get_hsx_tick_size returns None for a price no band matches."""
    state = _state(reference=Decimal('-1'), ceiling=Decimal('0'),
                   floor=Decimal('-100'), last=Decimal('-1'))
    result = HSX_EXCHANGE.admits(_order(limit_price=Decimal('-1')), state)
    assert result.verdict is Verdict.INDETERMINATE
    assert result.rule is AdmissionRule.TICK_GRID


@pytest.mark.parametrize('exchange', [HNX_EXCHANGE, UPCOM_EXCHANGE])
def test_non_hsx_equity_exchanges_use_a_flat_tenth(exchange):
    state = _state(reference=Decimal('25'), ceiling=Decimal('30'),
                   floor=Decimal('20'), last=Decimal('25'))
    assert exchange.admits(_order(limit_price=Decimal('25.1')), state).verdict \
        is Verdict.ADMITTED
    bad = exchange.admits(_order(limit_price=Decimal('25.05')), state)
    assert bad.verdict is Verdict.REJECTED
    assert bad.rule is AdmissionRule.ROUND_LOT or bad.rule is AdmissionRule.TICK_GRID


# --- round lot -------------------------------------------------------------

@pytest.mark.parametrize('qty, admitted', [(100, True), (1000, True),
                                           (150, False), (1, False), (0, False)])
def test_equity_round_lot_is_one_hundred(qty, admitted):
    result = HSX_EXCHANGE.admits(_order(quantity=qty), _state())
    if admitted:
        assert result.verdict is Verdict.ADMITTED
    else:
        assert result.verdict is Verdict.REJECTED
        assert result.rule is AdmissionRule.ROUND_LOT
        assert result.binding_constraint == 100


def test_rule_order_is_tick_then_lot():
    """Both broken: the tick grid is reported, because it is checked first.

    Ordering does not change the equity headline (verified: 0 off-grid closes
    and 0 off-grid ceilings over the headline population) but it does determine
    the per-rule composition of the rejection log, so it is normative.
    """
    result = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('95.55'), quantity=150), _state())
    assert result.rule is AdmissionRule.TICK_GRID
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_equity_admission.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'plutus.market.exchanges'`

- [ ] **Step 3: Write the implementation**

```python
# src/plutus/market/exchanges/__init__.py
"""Exchange models: one per Vietnamese exchange."""

from plutus.market.exchanges.base import Exchange
from plutus.market.exchanges.equity import (
    HNX_EXCHANGE,
    HSX_EXCHANGE,
    UPCOM_EXCHANGE,
    EquityExchange,
)

__all__ = ['Exchange', 'EquityExchange', 'HSX_EXCHANGE', 'HNX_EXCHANGE',
           'UPCOM_EXCHANGE']
```

```python
# src/plutus/market/exchanges/base.py
"""The Exchange contract: admission and position survival."""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional, Sequence

from plutus.core.constant import ExchangeSpec
from plutus.market.protocol import InstrumentSpec, MarketState, Order, Position
from plutus.market.verdicts import Admissibility, Viability

__all__ = ['Exchange']


class Exchange(ABC):
    """Models one exchange's decisions about orders and positions.

    Two method families, deliberately separate because they bind on different
    exchanges: :meth:`admits` (stateless order admission) dominates the equity
    exchanges, :meth:`sustains` (stateful position survival) dominates the
    derivatives exchange.
    """

    def __init__(self, spec: ExchangeSpec):
        self.spec = spec

    @property
    def code(self) -> str:
        return self.spec.code

    @abstractmethod
    def admits(
        self,
        order: Order,
        state: MarketState,
        *,
        instrument: Optional[InstrumentSpec] = None,
        regime_tag: Optional[str] = None,
    ) -> Admissibility:
        """Would this exchange accept this order at this instant?"""

    def sustains(
        self,
        position: Position,
        path: Sequence[MarketState],
        **kwargs,
    ) -> Viability:
        """Would this exchange let this position survive this path?

        Equity exchanges impose no margin, no position limit and no expiry, so
        the base implementation reports unconditional survival. The derivatives
        exchange overrides it.
        """
        return Viability(
            survived=True,
            events=(),
            days_evaluated=len(path),
            days_indeterminate=0,
        )

    def __repr__(self) -> str:
        return f'{type(self).__name__}({self.spec.code!r})'
```

```python
# src/plutus/market/exchanges/equity.py
"""The equity exchanges: HSX, HNX, UPCOM.

One class parameterized by :class:`ExchangeSpec`. The three exchanges differ
only in fields the rulebook already carries -- trading unit, daily trading
limit, tick-size function -- so they are instances, not subclasses.
"""

from decimal import Decimal
from typing import Optional

from plutus.core.constant import HNX, HSX, UPCOM
from plutus.market.exchanges.base import Exchange
from plutus.market.protocol import InstrumentSpec, MarketState, Order
from plutus.market.verdicts import Admissibility, AdmissionRule, Verdict

__all__ = ['EquityExchange', 'HSX_EXCHANGE', 'HNX_EXCHANGE', 'UPCOM_EXCHANGE']


class EquityExchange(Exchange):
    """Order admission for a Vietnamese equity exchange."""

    def admits(
        self,
        order: Order,
        state: MarketState,
        *,
        instrument: Optional[InstrumentSpec] = None,
        regime_tag: Optional[str] = None,
    ) -> Admissibility:
        def verdict(v, rule=None, bound=None, **detail) -> Admissibility:
            return Admissibility(
                verdict=v, rule=rule, binding_constraint=bound,
                ts=state.ts, regime_tag=regime_tag, detail=detail,
            )

        # --- 1. tick grid -------------------------------------------------
        price = order.limit_price
        if price is not None:
            tick = self.spec.get_tick_size(order.ticker, price)
            if tick is None:
                # get_hsx_tick_size falls off the end of its band table and
                # returns None despite its Decimal annotation.
                return verdict(
                    Verdict.INDETERMINATE, AdmissionRule.TICK_GRID,
                    reason='no tick band matches this price',
                )
            if (price % tick) != 0:
                return verdict(Verdict.REJECTED, AdmissionRule.TICK_GRID, tick)

        # --- 2. round lot -------------------------------------------------
        unit = instrument.trading_unit if instrument else self.spec.trading_unit
        if order.quantity <= 0 or (order.quantity % unit) != 0:
            return verdict(Verdict.REJECTED, AdmissionRule.ROUND_LOT, unit)

        return verdict(Verdict.ADMITTED)


HSX_EXCHANGE = EquityExchange(HSX)
HNX_EXCHANGE = EquityExchange(HNX)
UPCOM_EXCHANGE = EquityExchange(UPCOM)
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_equity_admission.py -q`
Expected: PASS (all parametrizations)

Full suite expected: `493 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/plutus/market/exchanges tests/market/test_equity_admission.py
git commit -m "Add Exchange ABC and EquityExchange tick-grid and round-lot admission"
```

---

### Task 5: `BAND_LIMIT` and `BAND_LOCK` — the split that makes the headline measurable

**Files:**
- Modify: `src/plutus/market/exchanges/equity.py` (extend `admits`)
- Test: `tests/market/test_band_rules.py`

**Interfaces:**
- Consumes: everything from Task 4, plus `protocol.BandSource`, `protocol.LockEvidence`.
- Produces: no new public names; `EquityExchange.admits` now enforces rules 3 and 4.

**This is the task the whole design turns on.** Two different questions were originally one rule:

- **`BAND_LIMIT`** — is the price inside `[floor, ceiling]`? Stateless, needs no book. An exchange rejects an order priced outside the band outright.
- **`BAND_LOCK`** — is this a *marketable* order into a band that is *locked*? This is fillability, not admissibility. An order priced **at** the ceiling is perfectly admissible; the exchange accepts it and it simply may not fill.

Conflating them made the equity headline unmeasurable: establishing a lock needs the resting book, sizes are 0-row in every corpus, and the spec mandates `INDETERMINATE` when the book is absent — so every bar-resolution evaluation would have returned `INDETERMINATE`.

`MarketState.lock_evidence` resolves it: `BAR_PROXY` (the daily adapter sets it when `last == ceiling`), `TICK_BOOK` (the tick adapter sets it from a forward-filled ladder), `UNKNOWN` → `INDETERMINATE`.

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_band_rules.py
"""BAND_LIMIT (stateless) and BAND_LOCK (fillability) are different questions."""

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.exchanges.equity import HSX_EXCHANGE
from plutus.market.protocol import (
    BandSource, LockEvidence, MarketState, Order, SessionPhase, Side,
)
from plutus.market.verdicts import AdmissionRule, Verdict

TS = datetime(2022, 3, 29, 10, 15)


def _state(**kw):
    base = dict(
        ticker='FPT', ts=TS, session=SessionPhase.CONTINUOUS,
        reference=Decimal('95.0'), ceiling=Decimal('101.6'),
        floor=Decimal('88.4'), band_source=BandSource.PUBLISHED,
        last=Decimal('95.0'),
    )
    base.update(kw)
    return MarketState(**base)


def _order(**kw):
    base = dict(ticker='FPT', side=Side.BUY, quantity=100,
                limit_price=Decimal('95.5'))
    base.update(kw)
    return Order(**base)


# --- BAND_LIMIT: stateless, no book required -------------------------------

def test_price_above_ceiling_is_rejected():
    r = HSX_EXCHANGE.admits(_order(limit_price=Decimal('101.7')), _state())
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.BAND_LIMIT
    assert r.binding_constraint == Decimal('101.6')


def test_price_below_floor_is_rejected():
    r = HSX_EXCHANGE.admits(
        _order(side=Side.SELL, limit_price=Decimal('88.3')), _state())
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.BAND_LIMIT


def test_price_exactly_at_ceiling_is_admissible():
    """The exchange accepts it. Whether it FILLS is BAND_LOCK's question."""
    r = HSX_EXCHANGE.admits(_order(limit_price=Decimal('101.6')), _state())
    assert r.verdict is Verdict.ADMITTED


def test_absent_bands_yield_indeterminate_not_admission():
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('95.5')),
        _state(ceiling=None, floor=None, band_source=BandSource.ABSENT),
    )
    assert r.verdict is Verdict.INDETERMINATE
    assert r.rule is AdmissionRule.BAND_LIMIT


# --- BAND_LOCK: fillability, needs provenance ------------------------------

def test_buy_into_a_locked_ceiling_is_not_fillable():
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('101.6')),
        _state(last=Decimal('101.6'), locked_side=Side.BUY,
               lock_evidence=LockEvidence.BAR_PROXY),
    )
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.BAND_LOCK
    assert r.detail['lock_evidence'] == 'bar_proxy'


def test_sell_into_a_locked_ceiling_is_fine():
    """A lock blocks the side that must cross it, not the side supplying it."""
    r = HSX_EXCHANGE.admits(
        _order(side=Side.SELL, limit_price=Decimal('101.6')),
        _state(last=Decimal('101.6'), locked_side=Side.BUY,
               lock_evidence=LockEvidence.BAR_PROXY),
    )
    assert r.verdict is Verdict.ADMITTED


def test_sell_into_a_locked_floor_is_not_fillable():
    r = HSX_EXCHANGE.admits(
        _order(side=Side.SELL, limit_price=Decimal('88.4')),
        _state(last=Decimal('88.4'), locked_side=Side.SELL,
               lock_evidence=LockEvidence.BAR_PROXY),
    )
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.BAND_LOCK


def test_unknown_lock_evidence_yields_indeterminate():
    """Absence of a book is not evidence of fillability."""
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('101.6')),
        _state(last=Decimal('101.6'), locked_side=Side.BUY,
               lock_evidence=LockEvidence.UNKNOWN),
    )
    assert r.verdict is Verdict.INDETERMINATE
    assert r.rule is AdmissionRule.BAND_LOCK


def test_no_lock_declared_means_no_lock_rule_fires():
    r = HSX_EXCHANGE.admits(_order(limit_price=Decimal('95.5')), _state())
    assert r.verdict is Verdict.ADMITTED
    assert r.rule is None


def test_tick_book_evidence_is_honoured_the_same_way():
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('101.6')),
        _state(last=Decimal('101.6'), locked_side=Side.BUY,
               lock_evidence=LockEvidence.TICK_BOOK),
    )
    assert r.verdict is Verdict.REJECTED
    assert r.detail['lock_evidence'] == 'tick_book'


def test_band_limit_precedes_band_lock():
    """A price outside the band never reaches the lock question."""
    r = HSX_EXCHANGE.admits(
        _order(limit_price=Decimal('101.7')),
        _state(last=Decimal('101.6'), locked_side=Side.BUY,
               lock_evidence=LockEvidence.BAR_PROXY),
    )
    assert r.rule is AdmissionRule.BAND_LIMIT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_band_rules.py -q`
Expected: FAIL — the first band test fails with `Verdict.ADMITTED` because no band rule exists yet.

- [ ] **Step 3: Extend `EquityExchange.admits`**

Insert these two blocks in `src/plutus/market/exchanges/equity.py` **after** the round-lot block and **before** `return verdict(Verdict.ADMITTED)`. Add `BandSource`, `LockEvidence`, `Side` to the imports from `plutus.market.protocol`.

```python
        # --- 3. BAND_LIMIT: stateless, needs no book ----------------------
        if price is not None:
            if state.ceiling is None or state.floor is None:
                return verdict(
                    Verdict.INDETERMINATE, AdmissionRule.BAND_LIMIT,
                    band_source=state.band_source.value,
                    reason='no price band available for this ticker-day',
                )
            if price > state.ceiling:
                return verdict(Verdict.REJECTED, AdmissionRule.BAND_LIMIT,
                               state.ceiling, side='above_ceiling')
            if price < state.floor:
                return verdict(Verdict.REJECTED, AdmissionRule.BAND_LIMIT,
                               state.floor, side='below_floor')

        # --- 4. BAND_LOCK: fillability, needs lock provenance -------------
        # An order priced AT a band is admissible; this asks whether it can
        # fill. Only the side that must cross the lock is blocked.
        if state.locked_side is not None and order.side is state.locked_side:
            marketable = price is None or (
                (order.side is Side.BUY and state.ceiling is not None
                 and price >= state.ceiling)
                or (order.side is Side.SELL and state.floor is not None
                    and price <= state.floor)
            )
            if marketable:
                if state.lock_evidence is LockEvidence.UNKNOWN:
                    return verdict(
                        Verdict.INDETERMINATE, AdmissionRule.BAND_LOCK,
                        lock_evidence=state.lock_evidence.value,
                        reason='lock cannot be established without book or proxy',
                    )
                bound = (state.ceiling if order.side is Side.BUY
                         else state.floor)
                return verdict(Verdict.REJECTED, AdmissionRule.BAND_LOCK, bound,
                               lock_evidence=state.lock_evidence.value)
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_band_rules.py tests/market/test_equity_admission.py -q`
Expected: PASS, both modules.

Full suite expected: `504 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/plutus/market/exchanges/equity.py tests/market/test_band_rules.py
git commit -m "Split band admission from band fillability (BAND_LIMIT vs BAND_LOCK)"
```

---

### Task 6: `FOREIGN_ROOM` and `SESSION_SEMANTICS`

**Files:**
- Modify: `src/plutus/market/exchanges/equity.py`
- Test: `tests/market/test_room_and_session.py`

**Interfaces:**
- Consumes: Task 5 output.
- Produces: rules 5 and 6 on `EquityExchange.admits`.

**Availability warning that must be stated in the docstring:** `has_field('foreign_room')` is **`False`** on the shipped Parquet root. Rule 5 therefore returns `INDETERMINATE` for every state built from that corpus. It is implemented and unit-tested against synthetic states; it is **not** measurable there, and no measurement task may assume it is.

**Session asymmetries, verified from `constant.py:304-450`:** ATO exists only on HSX and HNXDS. ATC exists on HSX/HNX/HNXDS, **not** UPCOM. PLO exists only on HNX. `UPCOM.trading_time_end` raises `AttributeError` — never call it.

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_room_and_session.py
"""Foreign-ownership room, and call-auction session semantics."""

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.exchanges.equity import HSX_EXCHANGE, UPCOM_EXCHANGE
from plutus.market.protocol import (
    BandSource, MarketState, Order, OrderType, SessionPhase, Side,
)
from plutus.market.verdicts import AdmissionRule, Verdict

TS = datetime(2022, 3, 29, 10, 15)


def _state(**kw):
    base = dict(
        ticker='FPT', ts=TS, session=SessionPhase.CONTINUOUS,
        reference=Decimal('95.0'), ceiling=Decimal('101.6'),
        floor=Decimal('88.4'), band_source=BandSource.PUBLISHED,
        last=Decimal('95.0'),
    )
    base.update(kw)
    return MarketState(**base)


def _order(**kw):
    base = dict(ticker='FPT', side=Side.BUY, quantity=100,
                limit_price=Decimal('95.5'))
    base.update(kw)
    return Order(**base)


# --- foreign room ----------------------------------------------------------

def test_domestic_order_ignores_foreign_room():
    r = HSX_EXCHANGE.admits(_order(is_foreign=False), _state(foreign_room=0))
    assert r.verdict is Verdict.ADMITTED


def test_foreign_buy_exceeding_room_is_rejected():
    r = HSX_EXCHANGE.admits(
        _order(is_foreign=True, quantity=1000), _state(foreign_room=500))
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.FOREIGN_ROOM
    assert r.binding_constraint == 500


def test_foreign_buy_within_room_is_admitted():
    r = HSX_EXCHANGE.admits(
        _order(is_foreign=True, quantity=100), _state(foreign_room=500))
    assert r.verdict is Verdict.ADMITTED


def test_foreign_sell_is_not_constrained_by_room():
    """Room limits acquisition, not disposal."""
    r = HSX_EXCHANGE.admits(
        _order(is_foreign=True, side=Side.SELL, quantity=1000,
               limit_price=Decimal('95.5')),
        _state(foreign_room=0),
    )
    assert r.verdict is Verdict.ADMITTED


def test_absent_room_yields_indeterminate_for_a_foreign_buy():
    """This is the state of every ticker-day on the shipped Parquet corpus."""
    r = HSX_EXCHANGE.admits(_order(is_foreign=True), _state(foreign_room=None))
    assert r.verdict is Verdict.INDETERMINATE
    assert r.rule is AdmissionRule.FOREIGN_ROOM


# --- session semantics -----------------------------------------------------

def test_limit_order_in_continuous_session_is_admitted():
    r = HSX_EXCHANGE.admits(_order(), _state(session=SessionPhase.CONTINUOUS))
    assert r.verdict is Verdict.ADMITTED


def test_limit_order_during_the_noon_break_is_rejected():
    r = HSX_EXCHANGE.admits(_order(), _state(session=SessionPhase.NOON_BREAK))
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.SESSION_SEMANTICS


def test_plain_limit_order_in_an_auction_is_rejected():
    """ATO/ATC are call auctions: a continuous-trading limit order has no book
    to rest on. The auction order types are the admissible ones."""
    r = HSX_EXCHANGE.admits(
        _order(order_type=OrderType.LIMIT),
        _state(session=SessionPhase.OPENING_AUCTION),
    )
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.SESSION_SEMANTICS


def test_ato_order_type_is_admissible_in_the_opening_auction():
    r = HSX_EXCHANGE.admits(
        _order(order_type=OrderType.AT_THE_OPENING, limit_price=None),
        _state(session=SessionPhase.OPENING_AUCTION),
    )
    assert r.verdict is Verdict.ADMITTED


def test_atc_order_type_is_admissible_in_the_closing_auction():
    r = HSX_EXCHANGE.admits(
        _order(order_type=OrderType.AT_THE_CLOSE, limit_price=None),
        _state(session=SessionPhase.CLOSING_AUCTION),
    )
    assert r.verdict is Verdict.ADMITTED


def test_upcom_has_no_closing_auction():
    """UPCOM's spec carries atc_session=None. An ATC order there is rejected."""
    r = UPCOM_EXCHANGE.admits(
        _order(order_type=OrderType.AT_THE_CLOSE, limit_price=None),
        _state(session=SessionPhase.CLOSING_AUCTION),
    )
    assert r.verdict is Verdict.REJECTED
    assert r.rule is AdmissionRule.SESSION_SEMANTICS


def test_unknown_session_yields_indeterminate():
    r = HSX_EXCHANGE.admits(_order(), _state(session=SessionPhase.UNKNOWN))
    assert r.verdict is Verdict.INDETERMINATE
    assert r.rule is AdmissionRule.SESSION_SEMANTICS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_room_and_session.py -q`
Expected: FAIL — foreign/session tests report `ADMITTED`.

- [ ] **Step 3: Extend `EquityExchange.admits`**

Add `OrderType` to the `plutus.market.protocol` import. Insert **after** the `BAND_LOCK` block and **before** `return verdict(Verdict.ADMITTED)`:

```python
        # --- 5. FOREIGN_ROOM ---------------------------------------------
        # Room limits acquisition, not disposal, so only a foreign BUY is
        # constrained. NOTE: has_field('foreign_room') is False on the shipped
        # Parquet corpus, so this rule returns INDETERMINATE for every state
        # built from it. Implemented and unit-tested; not measurable there.
        if order.is_foreign and order.side is Side.BUY:
            if state.foreign_room is None:
                return verdict(
                    Verdict.INDETERMINATE, AdmissionRule.FOREIGN_ROOM,
                    reason='foreign room unavailable in this dataset',
                )
            if order.quantity > state.foreign_room:
                return verdict(Verdict.REJECTED, AdmissionRule.FOREIGN_ROOM,
                               state.foreign_room)

        # --- 6. SESSION_SEMANTICS ----------------------------------------
        # ATO/ATC are call auctions: a continuous-trading order has no resting
        # book to join, and an auction order has no meaning outside its
        # auction. Asymmetries are read from the rulebook, not hard-coded:
        # ATO exists only on HSX/HNXDS, ATC not on UPCOM, PLO only on HNX.
        session_verdict = self._admits_in_session(order, state)
        if session_verdict is not None:
            return session_verdict

        return verdict(Verdict.ADMITTED)

    def _admits_in_session(
        self, order: Order, state: MarketState
    ) -> Optional[Admissibility]:
        """None when the session poses no objection."""

        def reject(**detail) -> Admissibility:
            return Admissibility(
                verdict=Verdict.REJECTED, rule=AdmissionRule.SESSION_SEMANTICS,
                binding_constraint=None, ts=state.ts, detail=detail,
            )

        phase = state.session
        if phase is SessionPhase.UNKNOWN:
            return Admissibility(
                verdict=Verdict.INDETERMINATE,
                rule=AdmissionRule.SESSION_SEMANTICS,
                binding_constraint=None, ts=state.ts,
                detail={'reason': 'session phase not supplied by the adapter'},
            )

        if phase in (SessionPhase.PRE_OPEN, SessionPhase.NOON_BREAK,
                     SessionPhase.POST_CLOSE):
            return reject(phase=phase.value, reason='exchange not matching')

        if phase is SessionPhase.OPENING_AUCTION:
            if self.spec.ato_session is None:
                return reject(phase=phase.value,
                              reason=f'{self.spec.code} has no opening auction')
            if order.order_type is not OrderType.AT_THE_OPENING:
                return reject(phase=phase.value,
                              order_type=str(order.order_type),
                              reason='call auction accepts ATO orders only')
            return None

        if phase is SessionPhase.CLOSING_AUCTION:
            if self.spec.atc_session is None:
                return reject(phase=phase.value,
                              reason=f'{self.spec.code} has no closing auction')
            if order.order_type is not OrderType.AT_THE_CLOSE:
                return reject(phase=phase.value,
                              order_type=str(order.order_type),
                              reason='call auction accepts ATC orders only')
            return None

        if phase is SessionPhase.POST_CLOSE_PLO:
            if self.spec.plo_session is None:
                return reject(phase=phase.value,
                              reason=f'{self.spec.code} has no PLO session')
            return None

        # CONTINUOUS: an auction-only order type has no auction to join.
        if order.order_type in (OrderType.AT_THE_OPENING, OrderType.AT_THE_CLOSE):
            return reject(phase=phase.value, order_type=str(order.order_type),
                          reason='auction order outside its auction')
        return None
```

Also add to the module imports: `from plutus.market.protocol import ... OrderType, SessionPhase, Side` and `from typing import Optional`.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/ -q`
Expected: PASS, all market modules.

Full suite expected: `517 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/plutus/market/exchanges/equity.py tests/market/test_room_and_session.py
git commit -m "Add foreign-room and call-auction session admission rules"
```

---

### Task 7: `MarketDataSource` and the daily adapter

**Files:**
- Create: `src/plutus/market/adapters/__init__.py`
- Create: `src/plutus/market/adapters/base.py`
- Create: `src/plutus/market/adapters/datahub.py`
- Test: `tests/market/conftest.py`
- Test: `tests/market/test_datahub_adapter.py`

**Interfaces:**
- Consumes: `plutus.datahub.DataHubConfig`, `plutus.market.protocol.*`.
- Produces: `MarketDataSource` (Protocol) with `state_at`, `states`, `instrument`; `DataHubSource(config, *, resolution=Resolution.DAILY)`; helpers `reconstruct_bands(reference, limit, tick_fn, ticker)`, `truncate_to_tick`, `round_up_to_tick`.

**Three facts this task must honour, all verified:**

1. **Session must be set explicitly.** A daily bar's `ts` is midnight and `HSX.before_trading_session.is_current(midnight)` is `True`. The adapter sets `SessionPhase.CONTINUOUS` on every daily state and never infers from `ts`. Inferring would reject the entire equity measurement under rule 6.
2. **Band reconstruction rule.** `ceiling = truncate_down_to_tick(reference × (1+L))`, `floor = round_up_to_tick(reference × (1−L))`, with the **tick keyed on the resulting band price, not the reference**. Round-to-nearest is decisively wrong (47.8–58.0% match vs 91.3–93.3% for truncation); reference-keyed ticks score 93.21%/96.70% against 95.72%/99.24% result-keyed on HSX. On ticker-days that actually traded the rule reaches HNX 98.00%/99.70%, HSX 95.96%/99.30%, UPCOM 95.61%/97.77% (2021/2022).
3. **`instrument()` never raises.** 87 tickers appear in `quote_close` for 2021–22 and are absent from `quote_ticker` (31,075 ticker-days); the master's `instrumenttype` vocabulary is only `{stock, warrant, fund}` with no `future` and no `HNXDS`, so derivatives cannot be typed from data. Use the documented fallback chain and return `InstrumentKind.UNKNOWN` rather than raising or dropping.

**Do not hold two live iterators from one query object.** `OHLCQuery` owns a single DuckDB connection and `ResultIterator` executes on it; interleaving two iterators from the same query object silently yields the other query's rows (verified). Materialise one query before starting the next.

- [ ] **Step 1: Write the shared test fixtures**

```python
# tests/market/conftest.py
"""Corpus gating for plutus.market tests.

The repo has no shared conftest; tests/data/test_audit.py and
tests/datahub/test_daily_ohlc.py each carry their own root helper. This module
consolidates the pattern for the market package and adds the raw-archive root,
which nothing resolved before.
"""

import os
from pathlib import Path

import pytest

_PARQUET_DEFAULT = Path('/Users/nadan/algotrade-research/dataset/hermes-parquet')
_ARCHIVE_DEFAULT = Path(
    '/Users/nadan/algotrade-research/dataset/hermes-offline-market-data-pre-2023'
)


def _corpus_root():
    """A root carrying the daily tables, or None."""
    candidates = []
    env = os.environ.get('PLUTUS_DATA_ROOT')
    if env:
        candidates.append(Path(env))
    candidates.append(_PARQUET_DEFAULT)
    for root in candidates:
        if (root / 'quote_close.parquet').exists() or (root / 'quote_close.csv').exists():
            return root
    return None


def _tick_root():
    """A root carrying ticks and the order book, or None."""
    candidates = []
    env = os.environ.get('PLUTUS_TICK_ROOT')
    if env:
        candidates.append(Path(env))
    candidates.append(_ARCHIVE_DEFAULT)
    for root in candidates:
        if (root / 'quote_askprice.csv').exists():
            return root
    return None


CORPUS = _corpus_root()
TICK_ROOT = _tick_root()

requires_corpus = pytest.mark.skipif(
    CORPUS is None, reason='No daily corpus found; set PLUTUS_DATA_ROOT.'
)
requires_ticks = pytest.mark.skipif(
    TICK_ROOT is None,
    reason='No tick archive found; set PLUTUS_TICK_ROOT.',
)


@pytest.fixture(scope='session')
def corpus_root():
    return CORPUS


@pytest.fixture(scope='session')
def tick_root():
    return TICK_ROOT
```

- [ ] **Step 2: Write the failing test**

```python
# tests/market/test_datahub_adapter.py
"""The daily adapter: reconstruction, provenance, and explicit session."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.adapters.datahub import (
    DataHubSource,
    reconstruct_bands,
    round_up_to_tick,
    truncate_to_tick,
)
from plutus.market.protocol import (
    BandSource, InstrumentKind, LockEvidence, Resolution, SessionPhase,
)

from .conftest import requires_corpus


# --- pure helpers, no corpus needed ---------------------------------------

@pytest.mark.parametrize(
    'value, tick, expected',
    [
        (Decimal('51.788'), Decimal('0.1'), Decimal('51.7')),
        (Decimal('51.7'), Decimal('0.1'), Decimal('51.7')),
        (Decimal('9.876'), Decimal('0.01'), Decimal('9.87')),
    ],
)
def test_truncate_to_tick(value, tick, expected):
    assert truncate_to_tick(value, tick) == expected


@pytest.mark.parametrize(
    'value, tick, expected',
    [
        (Decimal('45.012'), Decimal('0.1'), Decimal('45.1')),
        (Decimal('45.1'), Decimal('0.1'), Decimal('45.1')),
        (Decimal('9.871'), Decimal('0.01'), Decimal('9.88')),
    ],
)
def test_round_up_to_tick(value, tick, expected):
    assert round_up_to_tick(value, tick) == expected


def test_reconstruction_keys_the_tick_on_the_result_not_the_reference():
    """DSN 2022-04-25: reference 48.40 sits in the 0.05 band, but 48.40*1.07 =
    51.788 crosses 50 and must be truncated on the 0.1 grid to 51.70."""
    from plutus.core.constant import get_hsx_tick_size

    ceiling, floor = reconstruct_bands(
        reference=Decimal('48.40'), limit=Decimal('0.07'),
        tick_fn=get_hsx_tick_size, ticker='DSN',
    )
    assert ceiling == Decimal('51.7')


def test_reconstruction_returns_none_without_a_reference():
    from plutus.core.constant import get_hsx_tick_size

    assert reconstruct_bands(None, Decimal('0.07'), get_hsx_tick_size, 'FPT') \
        == (None, None)


# --- adapter behaviour, corpus-gated --------------------------------------

@requires_corpus
def test_daily_state_sets_session_explicitly(corpus_root):
    """A daily ts is midnight; inferring the phase would mark it pre-open."""
    source = DataHubSource.for_root(str(corpus_root))
    state = source.state_at('FPT', datetime(2021, 1, 15))

    assert state is not None
    assert state.session is SessionPhase.CONTINUOUS


@requires_corpus
def test_published_bands_are_tagged_as_published(corpus_root):
    source = DataHubSource.for_root(str(corpus_root))
    state = source.state_at('FPT', datetime(2021, 6, 15))

    assert state is not None
    assert state.band_source is BandSource.PUBLISHED
    assert state.ceiling is not None and state.floor is not None
    assert state.floor < state.ceiling


@requires_corpus
def test_a_limit_locked_day_carries_bar_proxy_evidence(corpus_root):
    """When last == ceiling the daily adapter can assert a buy-side lock, and
    must label the evidence as an inference, not a book observation."""
    source = DataHubSource.for_root(str(corpus_root))
    states = [
        s for s in source.states('FPT', date(2021, 1, 1), date(2023, 1, 1),
                                 resolution=Resolution.DAILY)
        if s.ceiling is not None and s.last == s.ceiling
    ]
    assert states, 'expected at least one limit-up day for FPT in 2021-2022'
    for state in states:
        assert state.lock_evidence is LockEvidence.BAR_PROXY
        assert state.locked_side is not None


@requires_corpus
def test_states_is_end_exclusive(corpus_root):
    """validate_date_range makes end exclusive everywhere in this codebase."""
    source = DataHubSource.for_root(str(corpus_root))
    got = list(source.states('FPT', date(2021, 1, 15), date(2021, 1, 16),
                             resolution=Resolution.DAILY))
    assert len(got) == 1
    assert got[0].ts.date() == date(2021, 1, 15)


@requires_corpus
def test_instrument_never_raises_for_an_unlisted_ticker(corpus_root):
    """87 tickers trade in 2021-22 without a ticker-master row."""
    source = DataHubSource.for_root(str(corpus_root))
    spec = source.instrument('VNINDEX')

    assert spec.kind is not None
    assert spec.trading_unit in (1, 100)


@requires_corpus
def test_instrument_types_a_futures_contract_by_prefix(corpus_root):
    """The master has no `future` type and no HNXDS rows, so the code prefix is
    the only available signal."""
    source = DataHubSource.for_root(str(corpus_root))
    spec = source.instrument('VN30F2112')

    assert spec.kind is InstrumentKind.FUTURE
    assert spec.exchange_code == 'HNXDS'
    assert spec.trading_unit == 1
    assert spec.expiry == date(2021, 12, 16)   # third Thursday of Dec 2021
```

- [ ] **Step 3: Run to verify it fails**

Run: `PYTHONPATH=src PLUTUS_DATA_ROOT=/Users/nadan/algotrade-research/dataset/hermes-parquet /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_datahub_adapter.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'plutus.market.adapters'`

- [ ] **Step 4: Write the implementation**

```python
# src/plutus/market/adapters/__init__.py
"""Adapters translating a data source into MarketState."""

from plutus.market.adapters.base import MarketDataSource
from plutus.market.adapters.datahub import DataHubSource

__all__ = ['MarketDataSource', 'DataHubSource']
```

```python
# src/plutus/market/adapters/base.py
"""The narrow boundary between market data and exchange rules.

Keeping this protocol small is what makes the exchange models
vendor-independent: anything that can answer these three questions -- our own
datahub, vnstock, a broker feed -- can drive them.
"""

from datetime import date, datetime
from typing import Iterator, Optional, Protocol, Union, runtime_checkable

from plutus.market.protocol import InstrumentSpec, MarketState, Resolution

__all__ = ['MarketDataSource']


@runtime_checkable
class MarketDataSource(Protocol):
    """Supplies market state to an exchange model."""

    def state_at(self, ticker: str, ts: datetime) -> Optional[MarketState]:
        """The state for one ticker at one instant, or None if absent."""
        ...

    def states(
        self,
        ticker: str,
        start: Union[date, datetime],
        end: Union[date, datetime],
        *,
        resolution: Resolution = Resolution.DAILY,
    ) -> Iterator[MarketState]:
        """States over ``[start, end)``. **End is exclusive.**"""
        ...

    def instrument(self, ticker: str) -> InstrumentSpec:
        """Instrument facts. Never raises: unknown tickers come back as
        ``InstrumentKind.UNKNOWN`` rather than an exception."""
        ...
```

```python
# src/plutus/market/adapters/datahub.py
"""A MarketDataSource backed by plutus.datahub (daily resolution).

Three behaviours are deliberate and load-bearing:

* **Session is set, never inferred.** A daily bar's timestamp is midnight, and
  the coded ``before_trading_session`` reports current at midnight, so
  inferring the phase would mark every bar pre-open and the session rule would
  reject an entire daily measurement.
* **Bands carry provenance.** Only ~88% of 2021 stock ticker-days have a
  published ceiling. Where one is absent and a reference exists, bands are
  reconstructed and tagged ``RECONSTRUCTED``; where neither exists the state is
  tagged ``ABSENT`` and band rules return INDETERMINATE.
* **Lock evidence is labelled an inference.** ``last == ceiling`` on a daily
  bar is a proxy for a locked book, not an observation of one.
"""

import calendar
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Callable, Dict, Iterator, Optional, Tuple, Union

import duckdb

from plutus.core.constant import DS, HNX, HSX, UPCOM, VietnamMarketConstant
from plutus.datahub.config import DataHubConfig
from plutus.market.protocol import (
    BandSource, InstrumentKind, InstrumentSpec, LockEvidence, MarketState,
    Resolution, SessionPhase, Side,
)

__all__ = ['DataHubSource', 'reconstruct_bands', 'truncate_to_tick',
           'round_up_to_tick', 'third_thursday']

_SPECS = {'HSX': HSX, 'HNX': HNX, 'UPCOM': UPCOM, 'HNXDS': DS}
_FUTURES_RE = re.compile(r'^(VN30F|VN100F|GB\d)')
_CONTRACT_MONTH_RE = re.compile(r'^VN30F(\d{2})(\d{2})$')


def truncate_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    """Largest multiple of ``tick`` at or below ``value``."""
    return (value / tick).to_integral_value(rounding=ROUND_FLOOR) * tick


def round_up_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    """Smallest multiple of ``tick`` at or above ``value``."""
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


def reconstruct_bands(
    reference: Optional[Decimal],
    limit: Decimal,
    tick_fn: Callable[[str, Decimal], Optional[Decimal]],
    ticker: str,
) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """Derive (ceiling, floor) from a reference price and a daily limit.

    The tick is keyed on the **resulting band price**, not the reference. That
    detail is what makes the rule work: DSN on 2022-04-25 has reference 48.40
    (a 0.05-tick price) but its ceiling 51.70 lands above 50 and so sits on the
    0.1 grid. Reference-keyed ticks score 93.2%/96.7% against 95.7%/99.2% for
    result-keyed on HSX.

    Returns ``(None, None)`` when no reference is available.
    """
    if reference is None:
        return None, None

    raw_ceiling = reference * (Decimal('1') + limit)
    raw_floor = reference * (Decimal('1') - limit)

    ceiling_tick = tick_fn(ticker, raw_ceiling)
    floor_tick = tick_fn(ticker, raw_floor)
    if ceiling_tick is None or floor_tick is None:
        return None, None

    return (truncate_to_tick(raw_ceiling, ceiling_tick),
            round_up_to_tick(raw_floor, floor_tick))


def third_thursday(year: int, month: int) -> date:
    """VN30 futures expire on the third Thursday of the contract month."""
    first_thursday = next(
        day for day in range(1, 8)
        if date(year, month, day).weekday() == calendar.THURSDAY
    )
    return date(year, month, first_thursday + 14)


class DataHubSource:
    """Daily-resolution MarketDataSource over the datahub corpus."""

    def __init__(self, config: DataHubConfig,
                 resolution: Resolution = Resolution.DAILY):
        if resolution is not Resolution.DAILY:
            raise ValueError(
                'DataHubSource serves daily resolution only; use '
                'plutus.market.adapters.tick.TickSource for Resolution.TICK'
            )
        self.config = config
        self.resolution = resolution
        self._conn = duckdb.connect()
        self._instruments: Dict[str, InstrumentSpec] = {}

    @classmethod
    def for_root(cls, data_root: str) -> 'DataHubSource':
        return cls(DataHubConfig(data_root=data_root))

    # -- reading -----------------------------------------------------------

    def _reader(self, field: str) -> Optional[str]:
        if not self.config.has_field(field):
            return None
        path = self.config.get_file_path(field)
        fn = 'read_parquet' if path.suffix == '.parquet' else 'read_csv_auto'
        return f"{fn}('{path}')"

    def states(
        self,
        ticker: str,
        start: Union[date, datetime],
        end: Union[date, datetime],
        *,
        resolution: Resolution = Resolution.DAILY,
    ) -> Iterator[MarketState]:
        """States over ``[start, end)``. End is exclusive."""
        if resolution is not Resolution.DAILY:
            raise ValueError('DataHubSource serves Resolution.DAILY only')

        close = self._reader('close_price')
        if close is None:
            return iter(())

        ceil_r = self._reader('ceiling_price')
        floor_r = self._reader('floor_price')
        ref_r = self._reader('ref_price')

        select = ['c.datetime AS ts', 'c.price AS last']
        joins = []
        if ceil_r:
            select.append('ce.price AS ceiling')
            joins.append(f'LEFT JOIN {ceil_r} ce USING (datetime, tickersymbol)')
        else:
            select.append('NULL AS ceiling')
        if floor_r:
            select.append('fl.price AS floor')
            joins.append(f'LEFT JOIN {floor_r} fl USING (datetime, tickersymbol)')
        else:
            select.append('NULL AS floor')
        if ref_r:
            select.append('rf.price AS reference')
            joins.append(f'LEFT JOIN {ref_r} rf USING (datetime, tickersymbol)')
        else:
            select.append('NULL AS reference')

        sql = f"""
            SELECT {', '.join(select)}
            FROM {close} c
            {' '.join(joins)}
            WHERE c.tickersymbol = ?
              AND c.datetime >= ?
              AND c.datetime < ?
            ORDER BY c.datetime
        """
        rows = self._conn.execute(
            sql, [ticker, str(start)[:10], str(end)[:10]]
        ).fetchall()

        spec = self.instrument(ticker)
        for ts, last, ceiling, floor, reference in rows:
            yield self._build_state(ticker, ts, last, ceiling, floor,
                                    reference, spec)

    def state_at(self, ticker: str, ts: datetime) -> Optional[MarketState]:
        day = ts.date() if isinstance(ts, datetime) else ts
        for state in self.states(ticker, day, day + timedelta(days=1)):
            return state
        return None

    # -- assembly ----------------------------------------------------------

    def _build_state(self, ticker, ts, last, ceiling, floor, reference,
                     spec: InstrumentSpec) -> MarketState:
        as_dec = lambda v: None if v is None else Decimal(str(v))
        last_d, ceiling_d = as_dec(last), as_dec(ceiling)
        floor_d, reference_d = as_dec(floor), as_dec(reference)

        if ceiling_d is not None and floor_d is not None:
            band_source = BandSource.PUBLISHED
        else:
            exchange_spec = _SPECS.get(spec.exchange_code)
            tick_fn = (exchange_spec.tick_size_function if exchange_spec
                       else None)
            if reference_d is not None and tick_fn is not None:
                ceiling_d, floor_d = reconstruct_bands(
                    reference_d, spec.daily_trading_limit, tick_fn, ticker)
                band_source = (BandSource.RECONSTRUCTED if ceiling_d is not None
                               else BandSource.ABSENT)
            else:
                band_source = BandSource.ABSENT

        # A daily bar cannot observe a book; last == band is an inference.
        locked_side = None
        lock_evidence = LockEvidence.UNKNOWN
        if last_d is not None and ceiling_d is not None and last_d == ceiling_d:
            locked_side, lock_evidence = Side.BUY, LockEvidence.BAR_PROXY
        elif last_d is not None and floor_d is not None and last_d == floor_d:
            locked_side, lock_evidence = Side.SELL, LockEvidence.BAR_PROXY

        return MarketState(
            ticker=ticker,
            ts=ts if isinstance(ts, datetime) else datetime(ts.year, ts.month, ts.day),
            reference=reference_d,
            ceiling=ceiling_d,
            floor=floor_d,
            band_source=band_source,
            last=last_d,
            book=None,
            # Set, never inferred: a daily ts is midnight.
            session=SessionPhase.CONTINUOUS,
            foreign_room=None,
            locked_side=locked_side,
            lock_evidence=lock_evidence,
        )

    # -- instruments -------------------------------------------------------

    def instrument(self, ticker: str) -> InstrumentSpec:
        """Never raises. Unknown tickers return InstrumentKind.UNKNOWN.

        Fallback chain, in order: futures code prefix, 8-char C/E/F
        warrant/ETF, ticker-master lookup, then UNKNOWN. The master carries no
        `future` type and no HNXDS rows, so derivatives can only be typed by
        prefix; and it stores only the *latest* exchange assignment, so
        `exchange_code` is unreliable for historical by-exchange work.
        """
        if ticker in self._instruments:
            return self._instruments[ticker]

        spec = self._resolve_instrument(ticker)
        self._instruments[ticker] = spec
        return spec

    def _resolve_instrument(self, ticker: str) -> InstrumentSpec:
        limit_of = lambda code: Decimal(
            str(VietnamMarketConstant.DAILY_TRADING_LIMIT[
                DS.code if code == 'HNXDS' else code]))

        if _FUTURES_RE.match(ticker):
            month = _CONTRACT_MONTH_RE.match(ticker)
            expiry = None
            if month:
                yy, mm = int(month.group(1)), int(month.group(2))
                if 1 <= mm <= 12:
                    expiry = third_thursday(2000 + yy, mm)
            return InstrumentSpec(
                ticker=ticker, exchange_code='HNXDS',
                kind=InstrumentKind.FUTURE, trading_unit=1,
                daily_trading_limit=limit_of('HNXDS'),
                expiry=expiry, underlying='VN30',
            )

        if len(ticker) == 8 and ticker[0] in ('C', 'E', 'F'):
            return InstrumentSpec(
                ticker=ticker, exchange_code='HSX',
                kind=InstrumentKind.WARRANT, trading_unit=100,
                daily_trading_limit=limit_of('HSX'),
            )

        master = self._reader('ticker_metadata')
        if master is not None:
            row = self._conn.execute(
                f'SELECT exchangeid, instrumenttype FROM {master} '
                f'WHERE tickersymbol = ? LIMIT 1', [ticker]
            ).fetchone()
            if row and row[0] in _SPECS:
                kinds = {'stock': InstrumentKind.STOCK,
                         'warrant': InstrumentKind.WARRANT,
                         'fund': InstrumentKind.FUND,
                         'index': InstrumentKind.INDEX,
                         'futures': InstrumentKind.FUTURE}
                return InstrumentSpec(
                    ticker=ticker, exchange_code=row[0],
                    kind=kinds.get(row[1], InstrumentKind.UNKNOWN),
                    trading_unit=VietnamMarketConstant.TRADING_UNIT[row[0]],
                    daily_trading_limit=limit_of(row[0]),
                )

        return InstrumentSpec(
            ticker=ticker, exchange_code='HSX',
            kind=InstrumentKind.UNKNOWN, trading_unit=100,
            daily_trading_limit=limit_of('HSX'),
        )
```

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=src PLUTUS_DATA_ROOT=/Users/nadan/algotrade-research/dataset/hermes-parquet /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/ -q`
Expected: PASS.

Full suite expected: `534 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/plutus/market/adapters tests/market/conftest.py tests/market/test_datahub_adapter.py
git commit -m "Add MarketDataSource boundary and the daily datahub adapter"
```

---

### Task 8: The equity headline — both lag variants

**Files:**
- Create: `measurements/__init__.py`
- Create: `measurements/equity_admission.py`
- Test: `tests/market/test_equity_headline.py`

**Interfaces:**
- Consumes: `DataHubSource`, `HSX_EXCHANGE`, `DataAudit.inverted_band_exclusions`.
- Produces: `measure_blocked_entries(data_root, *, lag, stocks_only=True) -> BlockedFillResult` with fields `attempts: int`, `blocked: int`, `rate: Decimal`, `lag: int`, `population: str`, `excluded_inverted: int`.

**This task carries the paper's primary equity number, and it must report two of them.**

The claimed 12.96% reproduces **only** when the ceiling lock is tested on the *same* session the momentum signal fires. That is not a tradeable rule — a close-to-close signal cannot be acted on within the session that produced it. Under the literal next-session reading the figure is less than half:

| Variant | All instruments | Stocks only |
|---|---|---|
| Same-session (`lag=0`) — signal at *t*, lock tested at *t* | 12.93% (n=210,459; 27,216 blocked) | **12.90%** (n=197,337; **25,464 blocked**) |
| Next-session (`lag=1`) — signal at *t*, entry at *t+1* | 5.95% (n=210,563; 12,520 blocked) | **5.84%** (n=197,521; **11,543 blocked**) |

Both are computed. `lag=1` is the honest headline; `lag=0` is reported alongside it as the figure prior work quoted, with the look-ahead stated. The claimed 12.96% on n=191,454 is **not reproducible under any filter tried** (nearest: 12.44% on n=191,780 after excluding calendar gaps and >15% moves) and is superseded.

Exact rule: per-ticker close series from `quote_close`; signal on day *t* where `close_t > close_{t-1}` via `lag() OVER (PARTITION BY tickersymbol ORDER BY datetime)`; join `quote_ceil`/`quote_floor` on the *attempt* day; require `ceil >= floor` (excludes the 1,272 inverted rows, of which **1,226 are equity ticker-days** — this filter is load-bearing, not cosmetic); blocked iff `close == ceiling` on the attempt day. Stocks-only adds `JOIN quote_ticker ON instrumenttype = 'stock'`.

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_equity_headline.py
"""The paper's equity number, pinned as integers.

Both lag variants are asserted. lag=1 is the tradeable rule and the honest
headline; lag=0 is the figure prior work quoted and embeds look-ahead, because
it tests the lock on the same session that produced the signal.
"""

from decimal import Decimal

import pytest

from measurements.equity_admission import measure_blocked_entries

from .conftest import requires_corpus


@pytest.fixture(scope='module')
def same_session(corpus_root):
    return measure_blocked_entries(str(corpus_root), lag=0, stocks_only=True)


@pytest.fixture(scope='module')
def next_session(corpus_root):
    return measure_blocked_entries(str(corpus_root), lag=1, stocks_only=True)


@requires_corpus
def test_same_session_variant_reproduces_exactly(same_session):
    """Integers, not a tolerance: the population is deterministic."""
    assert same_session.attempts == 197_337
    assert same_session.blocked == 25_464
    assert same_session.rate == pytest.approx(Decimal('0.129038'),
                                              abs=Decimal('0.000001'))


@requires_corpus
def test_next_session_variant_reproduces_exactly(next_session):
    assert next_session.attempts == 197_521
    assert next_session.blocked == 11_543
    assert next_session.rate == pytest.approx(Decimal('0.058440'),
                                              abs=Decimal('0.000001'))


@requires_corpus
def test_the_lag_more_than_halves_the_rate(same_session, next_session):
    """The look-ahead in the same-session rule is the whole story."""
    assert same_session.rate > next_session.rate * 2


@requires_corpus
def test_inverted_bands_are_excluded_and_the_count_is_reported(next_session):
    """1,226 of the 1,272 inverted pairs are equity ticker-days."""
    assert next_session.excluded_inverted > 0


@requires_corpus
def test_every_result_is_json_serialisable(next_session):
    import json

    decoded = json.loads(json.dumps(next_session.to_dict()))
    assert decoded['lag'] == 1
    assert decoded['population'] == 'stocks'
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src:. PLUTUS_DATA_ROOT=/Users/nadan/algotrade-research/dataset/hermes-parquet /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_equity_headline.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'measurements'`

- [ ] **Step 3: Write the implementation**

```python
# measurements/__init__.py
"""Scripts that regenerate every quantitative claim the project makes.

Each module here backs a specific number in the paper. Nothing is hard-coded:
if a figure changes, these are what say so.
"""
```

```python
# measurements/equity_admission.py
"""Blocked-entry rate: how often a momentum entry cannot fill.

Two variants, and the difference between them matters more than either number.

``lag=0`` tests the ceiling lock on the **same** session that produced the
momentum signal. That is how the previously-quoted figure was obtained, and it
embeds look-ahead: a close-to-close signal cannot be acted on inside the
session that generated it.

``lag=1`` tests the lock on the **next** session, which is when an entry could
actually be attempted. It is the honest headline and it is less than half the
size.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import duckdb

__all__ = ['BlockedFillResult', 'measure_blocked_entries']


@dataclass(frozen=True)
class BlockedFillResult:
    attempts: int
    blocked: int
    rate: Decimal
    lag: int
    population: str
    excluded_inverted: int

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out['rate'] = float(self.rate)
        out['backs'] = (
            'paper equity headline: share of naive momentum entries the '
            'exchange would not fill'
        )
        return out


def _reader(root: Path, table: str) -> str:
    parquet = root / f'{table}.parquet'
    if parquet.exists():
        return f"read_parquet('{parquet}')"
    return f"read_csv_auto('{root / f'{table}.csv'}')"


def measure_blocked_entries(
    data_root: str,
    *,
    lag: int,
    stocks_only: bool = True,
) -> BlockedFillResult:
    """Measure the blocked-entry rate.

    Args:
        data_root: dataset root.
        lag: 0 tests the lock on the signal session (look-ahead); 1 tests it on
            the next session (tradeable).
        stocks_only: restrict to ``instrumenttype = 'stock'``.
    """
    if lag not in (0, 1):
        raise ValueError('lag must be 0 (same session) or 1 (next session)')

    root = Path(data_root)
    close = _reader(root, 'quote_close')
    ceil_t = _reader(root, 'quote_ceil')
    floor_t = _reader(root, 'quote_floor')
    ticker_t = _reader(root, 'quote_ticker')

    conn = duckdb.connect()

    stock_join = (
        f'JOIN {ticker_t} tk ON tk.tickersymbol = s.tickersymbol '
        f"AND tk.instrumenttype = 'stock'"
        if stocks_only else ''
    )
    # lag=0 -> the attempt day IS the signal day; lag=1 -> the following row.
    attempt_expr = (
        's.datetime' if lag == 0
        else 'lead(s.datetime) OVER (PARTITION BY s.tickersymbol '
             'ORDER BY s.datetime)'
    )
    attempt_close = (
        's.price' if lag == 0
        else 'lead(s.price) OVER (PARTITION BY s.tickersymbol '
             'ORDER BY s.datetime)'
    )

    sql = f"""
        WITH signals AS (
            SELECT c.tickersymbol, c.datetime, c.price,
                   lag(c.price) OVER (PARTITION BY c.tickersymbol
                                      ORDER BY c.datetime) AS prev_price
            FROM {close} c
        ), fired AS (
            SELECT s.tickersymbol,
                   {attempt_expr}  AS attempt_dt,
                   {attempt_close} AS attempt_close
            FROM signals s
            {stock_join}
            WHERE s.prev_price IS NOT NULL
              AND s.price > s.prev_price
        )
        SELECT count(*) AS attempts,
               sum(CASE WHEN f.attempt_close = ce.price THEN 1 ELSE 0 END)
                   AS blocked
        FROM fired f
        JOIN {ceil_t}  ce ON ce.tickersymbol = f.tickersymbol
                          AND ce.datetime = f.attempt_dt
        JOIN {floor_t} fl ON fl.tickersymbol = f.tickersymbol
                          AND fl.datetime = f.attempt_dt
        WHERE f.attempt_dt IS NOT NULL
          AND ce.price >= fl.price
    """
    attempts, blocked = conn.execute(sql).fetchone()
    attempts, blocked = int(attempts or 0), int(blocked or 0)

    excluded = conn.execute(
        f"""SELECT count(*) FROM {ceil_t} ce
            JOIN {floor_t} fl USING (datetime, tickersymbol)
            WHERE ce.price < fl.price"""
    ).fetchone()[0]

    rate = (Decimal(blocked) / Decimal(attempts)) if attempts else Decimal('0')
    return BlockedFillResult(
        attempts=attempts, blocked=blocked, rate=rate, lag=lag,
        population='stocks' if stocks_only else 'all_instruments',
        excluded_inverted=int(excluded),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()

    results = {}
    for population in (True, False):
        for lag in (0, 1):
            r = measure_blocked_entries(args.data_root, lag=lag,
                                        stocks_only=population)
            key = f"{r.population}_lag{lag}"
            results[key] = r.to_dict()
            label = 'same-session (LOOK-AHEAD)' if lag == 0 else 'next-session'
            print(f'{r.population:<16} {label:<26} '
                  f'{r.blocked:>7,} / {r.attempts:>8,} = {float(r.rate):.4%}')

    print('\nThe next-session figure is the tradeable one. The same-session '
          'figure tests the lock on the session that produced the signal.')
    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f'wrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 4: Run the script and confirm the four numbers**

Run:
```bash
PYTHONPATH=src:. /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m measurements.equity_admission --data-root /Users/nadan/algotrade-research/dataset/hermes-parquet
```
Expected, exactly:
```
stocks           same-session (LOOK-AHEAD)   25,464 /  197,337 = 12.9038%
stocks           next-session                11,543 /  197,521 = 5.8440%
all_instruments  same-session (LOOK-AHEAD)   27,216 /  210,459 = 12.9317%
all_instruments  next-session                12,520 /  210,563 = 5.9459%
```
If any integer differs, **stop** — the corpus has changed and the plan's pinned numbers must be re-derived before proceeding.

- [ ] **Step 5: Run tests**

Run: `PYTHONPATH=src:. PLUTUS_DATA_ROOT=/Users/nadan/algotrade-research/dataset/hermes-parquet /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_equity_headline.py -q`
Expected: PASS (5 tests)

Full suite expected: `539 passed`.

- [ ] **Step 6: Commit**

```bash
git add measurements/__init__.py measurements/equity_admission.py tests/market/test_equity_headline.py
git commit -m "Measure blocked entries at both lags; the tradeable rate is 5.84%, not 12.9%"
```

**Phase A is complete here.** The library admits or rejects equity orders under six rules, the boundary is vendor-independent, and the paper's equity number is computed by code and defended by CI.

---

## Phase B — The derivatives exchange (Tasks 9–12)

Delivers position survival: margin, forced liquidation, blocked exits, expiry. This is the co-equal contribution — it exercises the half of the framework the equity exchanges cannot, because the lot and tick rules that bind on equity *vanish* on futures while margin and expiry have no equity analogue.

---

### Task 9: `margin.py` — variation margin, not P&L

**Files:**
- Create: `src/plutus/market/margin.py`
- Test: `tests/market/test_margin.py`

**Interfaces:**
- Consumes: `protocol.Position`, `protocol.Side`.
- Produces: `MarginConfig` (frozen, with `VN30F_DEFAULT`), `MarginState` (frozen: `settlement`, `notional`, `equity`, `ratio`), `evaluate_margin(position, settlement, config) -> MarginState`.

**The distinction that keeps this exchange-side.** *Variation margin* is a quantity the exchange itself computes and collects daily. *Strategy P&L* is trader-side. This module computes the former only, and never nets it against cash, fees, or another position. That resolves the apparent conflict with the "no P&L" non-goal: daily mark-to-market of one position's margin account is the exchange's own arithmetic.

**The mechanic, fully determined — no placeholder anywhere:**

```
q        = +1 long / -1 short, times quantity
S_t      = settlement on day t
N_t      = |q| * multiplier * S_t                    notional
posted   = initial_rate * N_0
equity_t = posted + q * multiplier * (S_t - S_0)      cumulative variation margin
ratio_t  = equity_t / N_t

MARGIN_CALL         first day ratio_t <  maintenance_rate
FORCED_LIQUIDATION  first day ratio_t <= liquidation_rate
```

Defaults: `vsd_initial = 0.175`, `broker_buffer = 0.05` → `initial_rate = 0.225`; `maintenance_rate = 0.175`; `liquidation_rate = 0.00`; `multiplier = 100000` (VND per index point).

`maintenance_rate = 0.175` is **derived, not invented**: posting 22.5% against a 17.5% requirement makes the 5% broker buffer exactly the call-trigger distance. Every threshold is a config field documented as *a modelling assumption with no corpus backing* — no margin, position-limit or account data exists in any of the 80 tables across both corpora.

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_margin.py
"""Variation-margin arithmetic. Exchange-side only: no P&L, no portfolio."""

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.margin import MarginConfig, evaluate_margin
from plutus.market.protocol import Position, Side


def _long(entry=Decimal('1441.8'), qty=1):
    return Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.BUY,
        quantity=qty, entry_price=entry, entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'),
    )


def test_defaults_are_the_documented_vietnamese_rates():
    c = MarginConfig.VN30F_DEFAULT
    assert c.vsd_initial == Decimal('0.175')
    assert c.broker_buffer == Decimal('0.05')
    assert c.initial_rate == Decimal('0.225')
    assert c.maintenance_rate == Decimal('0.175')
    assert c.liquidation_rate == Decimal('0')


def test_maintenance_is_derived_so_the_buffer_is_the_call_distance():
    """Posting 22.5% against a 17.5% requirement leaves exactly 5% of headroom."""
    c = MarginConfig.VN30F_DEFAULT
    assert c.initial_rate - c.maintenance_rate == c.broker_buffer


def test_at_entry_the_ratio_is_the_initial_rate():
    state = evaluate_margin(_long(), Decimal('1441.8'),
                            MarginConfig.VN30F_DEFAULT)
    assert state.ratio == pytest.approx(Decimal('0.225'), abs=Decimal('1e-9'))


def test_a_long_loses_equity_as_the_settlement_falls():
    c = MarginConfig.VN30F_DEFAULT
    at_entry = evaluate_margin(_long(), Decimal('1441.8'), c)
    lower = evaluate_margin(_long(), Decimal('1400.0'), c)
    assert lower.equity < at_entry.equity
    assert lower.ratio < at_entry.ratio


def test_a_short_gains_equity_as_the_settlement_falls():
    c = MarginConfig.VN30F_DEFAULT
    short = Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.SELL, quantity=1,
        entry_price=Decimal('1441.8'), entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'),
    )
    assert evaluate_margin(short, Decimal('1400.0'), c).equity > \
        evaluate_margin(short, Decimal('1441.8'), c).equity


def test_quantity_scales_notional_and_equity_but_not_the_ratio():
    c = MarginConfig.VN30F_DEFAULT
    one = evaluate_margin(_long(qty=1), Decimal('1400.0'), c)
    ten = evaluate_margin(_long(qty=10), Decimal('1400.0'), c)
    assert ten.notional == one.notional * 10
    assert ten.ratio == pytest.approx(one.ratio, abs=Decimal('1e-12'))


def test_posted_margin_can_be_supplied_explicitly():
    c = MarginConfig.VN30F_DEFAULT
    p = Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.BUY, quantity=1,
        entry_price=Decimal('1441.8'), entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'), posted_margin=Decimal('50000000'),
    )
    assert evaluate_margin(p, Decimal('1441.8'), c).equity == Decimal('50000000')


def test_a_settlement_of_zero_is_rejected_rather_than_dividing_by_zero():
    with pytest.raises(ValueError, match='settlement'):
        evaluate_margin(_long(), Decimal('0'), MarginConfig.VN30F_DEFAULT)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_margin.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'plutus.market.margin'`

- [ ] **Step 3: Write the implementation**

```python
# src/plutus/market/margin.py
"""Variation-margin arithmetic for a single derivatives position.

**Variation margin is exchange-side.** It is a quantity the exchange itself
computes and collects each day. *Strategy P&L* is trader-side: it nets across
positions, subtracts fees and tracks a cash balance, and none of that happens
here. That is why this module can mark a position to market daily without
becoming a backtester.

Every threshold below is a **modelling assumption with no corpus backing** --
no margin, position-limit or account data exists in any table of either
corpus. The values are the published Vietnamese ones and they are config, so a
caller can sweep them.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from plutus.market.protocol import Position, Side

__all__ = ['MarginConfig', 'MarginState', 'evaluate_margin']


@dataclass(frozen=True)
class MarginConfig:
    """Rates governing a derivatives margin account.

    ``maintenance_rate`` is derived rather than invented: posting
    ``initial_rate`` (22.5%) against a maintenance requirement of 17.5% makes
    the 5% broker buffer exactly the distance to a call.
    """

    vsd_initial: Decimal = Decimal('0.175')
    broker_buffer: Decimal = Decimal('0.05')
    maintenance_rate: Decimal = Decimal('0.175')
    liquidation_rate: Decimal = Decimal('0')
    default_multiplier: Decimal = Decimal('100000')   # VND per index point

    @property
    def initial_rate(self) -> Decimal:
        """Fraction of notional a position must post at entry."""
        return self.vsd_initial + self.broker_buffer

    def with_initial(self, initial_rate: Decimal) -> 'MarginConfig':
        """A copy whose total initial rate is ``initial_rate``.

        Used by the sensitivity sweep. The buffer absorbs the change so the
        VSD component stays at its published value.
        """
        return MarginConfig(
            vsd_initial=self.vsd_initial,
            broker_buffer=initial_rate - self.vsd_initial,
            maintenance_rate=self.maintenance_rate,
            liquidation_rate=self.liquidation_rate,
            default_multiplier=self.default_multiplier,
        )


MarginConfig.VN30F_DEFAULT = MarginConfig()


@dataclass(frozen=True)
class MarginState:
    """The margin account of one position on one day."""

    settlement: Decimal
    notional: Decimal
    equity: Decimal
    ratio: Decimal


def evaluate_margin(
    position: Position,
    settlement: Decimal,
    config: MarginConfig,
) -> MarginState:
    """Mark one position to one settlement price.

    Raises:
        ValueError: if ``settlement`` is not positive -- notional would be zero
            or negative and the ratio undefined. Better to refuse than to
            return a meaningless number.
    """
    if settlement <= 0:
        raise ValueError(
            f'settlement must be positive, got {settlement}; notional and '
            f'margin ratio are undefined otherwise'
        )

    multiplier = position.multiplier or config.default_multiplier
    signed = Decimal(position.quantity) * (
        Decimal('1') if position.side is Side.BUY else Decimal('-1'))

    entry_notional = (Decimal(position.quantity) * multiplier
                      * position.entry_price)
    notional = Decimal(position.quantity) * multiplier * settlement

    posted = (position.posted_margin if position.posted_margin is not None
              else config.initial_rate * entry_notional)
    equity = posted + signed * multiplier * (settlement - position.entry_price)

    return MarginState(
        settlement=settlement,
        notional=notional,
        equity=equity,
        ratio=equity / notional,
    )
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_margin.py -q`
Expected: PASS (8 tests). Full suite: `547 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/plutus/market/margin.py tests/market/test_margin.py
git commit -m "Add variation-margin arithmetic with derived maintenance threshold"
```

---

### Task 10: `expiry.py` — contract months and the settlement chain

**Files:**
- Create: `src/plutus/market/expiry.py`
- Test: `tests/market/test_expiry.py`

**Interfaces:**
- Consumes: `verdicts.SettlementSource`.
- Produces: `parse_contract_month(ticker) -> tuple[int, int] | None`, `expiry_date(ticker) -> date | None`, `SettlementResolver` with `.settlement_for(ticker, day) -> tuple[Decimal | None, SettlementSource]`.

**Three verified facts:**
1. Expiry is the **third Thursday** of the contract month — 24/24 in-window, no holiday shift needed. (The four contracts that don't match are corpus-truncated at 2022-12-30, not expired.)
2. **`quote_reference` is not the settlement.** It equals the previous close on 1,731 of 1,968 VN30F pairs and misses published settlement by up to 5.55 points. It must not appear in the chain.
3. The published settlement is the **14:15–14:45 time-weighted mean of matched price** (mean error 0.74 points vs 2.9 for a 15-minute window and 5.4 for the full day). At expiry the regulation is index-based, so tier 2 substitutes VN30.

Tier order: `PUBLISHED` (5 real pairs, excluding the 11 corrupt 2022-08-16 rows whose price is the `HHMMSS` of their own timestamp) → `TWAP_30M` (raw archive only) → `CLOSE_PROXY` (the only tier available on the Parquet root).

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_expiry.py
"""Contract months, third-Thursday expiry, and settlement provenance."""

from datetime import date
from decimal import Decimal

import pytest

from plutus.market.expiry import SettlementResolver, expiry_date, parse_contract_month
from plutus.market.verdicts import SettlementSource

from .conftest import requires_corpus


@pytest.mark.parametrize(
    'ticker, expected',
    [
        ('VN30F2112', (2021, 12)),
        ('VN30F2206', (2022, 6)),
        ('VN30F2301', (2023, 1)),
        ('FPT', None),
        ('VN30F21XX', None),
        ('VN30F2113', None),      # month 13 is not a month
    ],
)
def test_parse_contract_month(ticker, expected):
    assert parse_contract_month(ticker) == expected


@pytest.mark.parametrize(
    'ticker, expected',
    [
        ('VN30F2112', date(2021, 12, 16)),
        ('VN30F2206', date(2022, 6, 16)),
        ('VN30F2203', date(2022, 3, 17)),
        ('VN30F2211', date(2022, 11, 17)),
    ],
)
def test_expiry_is_the_third_thursday(ticker, expected):
    got = expiry_date(ticker)
    assert got == expected
    assert got.weekday() == 3


def test_expiry_is_none_for_a_non_contract():
    assert expiry_date('FPT') is None


@requires_corpus
def test_close_proxy_is_used_when_no_published_settlement_exists(corpus_root):
    resolver = SettlementResolver.for_root(str(corpus_root))
    price, source = resolver.settlement_for('VN30F2203', date(2022, 1, 10))

    assert price is not None
    assert source is SettlementSource.CLOSE_PROXY


@requires_corpus
def test_published_settlement_wins_where_it_exists(corpus_root):
    """VN30F2206 on 2022-06-13 has a real settlement row: 1265.47."""
    resolver = SettlementResolver.for_root(str(corpus_root))
    price, source = resolver.settlement_for('VN30F2206', date(2022, 6, 13))

    assert source is SettlementSource.PUBLISHED
    assert price == pytest.approx(Decimal('1265.47'), abs=Decimal('0.01'))


@requires_corpus
def test_reference_is_never_used_as_a_settlement(corpus_root):
    """It equals the previous close on 88% of VN30F pairs and is not the
    settlement. Guard against it re-entering the chain."""
    resolver = SettlementResolver.for_root(str(corpus_root))
    for day in (date(2022, 6, 13), date(2022, 1, 10)):
        _, source = resolver.settlement_for('VN30F2206', day)
        assert source in (SettlementSource.PUBLISHED,
                          SettlementSource.CLOSE_PROXY,
                          SettlementSource.TWAP_30M)


@requires_corpus
def test_missing_day_returns_none_not_a_guess(corpus_root):
    resolver = SettlementResolver.for_root(str(corpus_root))
    price, _ = resolver.settlement_for('VN30F2206', date(2019, 1, 2))
    assert price is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src PLUTUS_DATA_ROOT=/Users/nadan/algotrade-research/dataset/hermes-parquet /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_expiry.py -q`
Expected: FAIL — no module `plutus.market.expiry`.

- [ ] **Step 3: Write the implementation**

```python
# src/plutus/market/expiry.py
"""Contract months, expiry dates, and the settlement-price chain.

Settlement has three tiers and every consumer records which one produced a
price, because they are not equally trustworthy:

1. ``PUBLISHED`` -- a real ``quote_settlementprice`` row. Only 5 (date,
   contract) pairs exist, and 11 further rows are corrupt (their price is the
   ``HHMMSS`` of their own timestamp) and are excluded.
2. ``TWAP_30M`` -- the time-weighted mean of matched price over 14:15-14:45,
   recovered empirically against the published rows at a mean error of 0.74
   index points. Requires the raw archive.
3. ``CLOSE_PROXY`` -- ``quote_close``. The only tier available on the Parquet
   root.

``quote_reference`` is deliberately **not** in the chain. It equals the
previous close on 1,731 of 1,968 comparable VN30F pairs and misses published
settlement by up to 5.55 points, so it is not an independent settlement series.
"""

import calendar
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple

import duckdb

from plutus.market.verdicts import SettlementSource

__all__ = ['parse_contract_month', 'expiry_date', 'third_thursday',
           'SettlementResolver']

_CONTRACT_RE = re.compile(r'^VN30F(\d{2})(\d{2})$')


def parse_contract_month(ticker: str) -> Optional[Tuple[int, int]]:
    """``'VN30F2112'`` -> ``(2021, 12)``; anything else -> ``None``."""
    match = _CONTRACT_RE.match(ticker)
    if not match:
        return None
    year, month = 2000 + int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return year, month


def third_thursday(year: int, month: int) -> date:
    first = next(day for day in range(1, 8)
                 if date(year, month, day).weekday() == calendar.THURSDAY)
    return date(year, month, first + 14)


def expiry_date(ticker: str) -> Optional[date]:
    """Third Thursday of the contract month. Verified 24/24 in-window."""
    parsed = parse_contract_month(ticker)
    return third_thursday(*parsed) if parsed else None


class SettlementResolver:
    """Resolves a settlement price and reports which tier supplied it."""

    def __init__(self, data_root: str, tick_root: Optional[str] = None):
        self.root = Path(data_root)
        self.tick_root = Path(tick_root) if tick_root else None
        self._conn = duckdb.connect()

    @classmethod
    def for_root(cls, data_root: str,
                 tick_root: Optional[str] = None) -> 'SettlementResolver':
        return cls(data_root, tick_root)

    def _reader(self, table: str) -> Optional[str]:
        parquet = self.root / f'{table}.parquet'
        if parquet.exists():
            return f"read_parquet('{parquet}')"
        csv = self.root / f'{table}.csv'
        return f"read_csv_auto('{csv}')" if csv.exists() else None

    def settlement_for(
        self, ticker: str, day: date
    ) -> Tuple[Optional[Decimal], SettlementSource]:
        """The settlement for one contract-day, and its provenance."""
        published = self._published(ticker, day)
        if published is not None:
            return published, SettlementSource.PUBLISHED

        twap = self._twap_30m(ticker, day)
        if twap is not None:
            return twap, SettlementSource.TWAP_30M

        return self._close(ticker, day), SettlementSource.CLOSE_PROXY

    def _published(self, ticker: str, day: date) -> Optional[Decimal]:
        table = self._reader('quote_settlementprice')
        if table is None:
            return None
        row = self._conn.execute(
            f"""SELECT price FROM {table}
                WHERE tickersymbol = ? AND CAST(datetime AS DATE) = ?
                  -- exclude the corrupt rows whose price is the HHMMSS of
                  -- their own timestamp
                  AND price < 100000
                ORDER BY datetime DESC LIMIT 1""",
            [ticker, day],
        ).fetchone()
        return Decimal(str(row[0])) if row else None

    def _twap_30m(self, ticker: str, day: date) -> Optional[Decimal]:
        """Time-weighted mean of matched price over 14:15-14:45.

        Requires the raw archive; returns None without it.
        """
        if self.tick_root is None:
            return None
        matched = self.tick_root / 'quote_matched.csv'
        if not matched.exists():
            return None
        row = self._conn.execute(
            f"""SELECT avg(price) FROM read_csv_auto('{matched}')
                WHERE tickersymbol = ?
                  AND datetime >= ? AND datetime < ?""",
            [ticker, f'{day} 14:15:00', f'{day} 14:45:00'],
        ).fetchone()
        return Decimal(str(row[0])) if row and row[0] is not None else None

    def _close(self, ticker: str, day: date) -> Optional[Decimal]:
        table = self._reader('quote_close')
        if table is None:
            return None
        row = self._conn.execute(
            f'SELECT price FROM {table} WHERE tickersymbol = ? '
            f'AND datetime = ? LIMIT 1',
            [ticker, day],
        ).fetchone()
        return Decimal(str(row[0])) if row else None
```

- [ ] **Step 4: Run tests**

Expected: PASS. Full suite: `561 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/plutus/market/expiry.py tests/market/test_expiry.py
git commit -m "Add third-Thursday expiry and the three-tier settlement chain"
```

---

### Task 11: `HNXDSExchange.sustains` — the position-survival result

**Files:**
- Create: `src/plutus/market/exchanges/derivatives.py`
- Modify: `src/plutus/market/exchanges/__init__.py` (export `HNXDSExchange`, `HNXDS_EXCHANGE`)
- Test: `tests/market/test_derivatives_sustains.py`

**Interfaces:**
- Consumes: `Exchange` ABC, `margin.MarginConfig`/`evaluate_margin`, `expiry.expiry_date`, `verdicts.PositionEvent*`, `Viability`.
- Produces: `HNXDSExchange(spec, margin_config=MarginConfig.VN30F_DEFAULT, position_limit=None)`; instance `HNXDS_EXCHANGE`; `sustains(position, path, *, settlements=None, margin_config=None) -> Viability`.

**Admission on HNXDS is nearly trivial and that is the finding.** Round lot is 1 contract, so the lot rule never binds. The tick grid is a flat 0.1, so the grid rule is uninteresting. There is no foreign-ownership cap. What binds instead is everything in `sustains`.

**Event semantics, all normative:**
- `MARGIN_CALL` — first day `ratio < maintenance_rate`. Emitted once, on the first such day.
- `FORCED_LIQUIDATION` — first day `ratio <= liquidation_rate` (default 0, i.e. equity wiped). Terminates the walk. **Invariant:** a forced liquidation implies a margin call on the same or an earlier day; this is tested.
- `EXIT_BLOCKED` — the position's `stop_price` is on the wrong side of a locked band, so the exchange would not fill the exit. Requires `stop_price`; without one the event never fires.
- `POSITION_LIMIT_EXCEEDED` — `quantity > position_limit` when a limit is configured. **No account, member or limit column exists in any of the 80 tables across both corpora**, so this is config-asserted and unit-tested only. The paper must not claim an incidence for it.
- `EXPIRY_SETTLEMENT` — the path reaches the contract's third-Thursday expiry.

**Verified fixtures** (long 1 contract, entry at the contract's first close, settlement proxy = daily close, defaults at 22.5%/17.5%):

| Contract | Entry | First `MARGIN_CALL` | `FORCED_LIQUIDATION` |
|---|---|---|---|
| `VN30F2212` | 2022-04-22 @ 1441.8 | **2022-05-09** | **2022-10-03** |
| `VN30F2211` | — | 2022-09-29 | 2022-10-24 |
| `VN30F2206` | — | 2022-04-25 | **never** — the "none where it shouldn't" case |

`VN30F2203` is the **only** VN30F contract with complete ceil+floor+reference coverage across its whole close path (167/167, 2021-07-16 → 2022-03-17). Use it wherever a test needs a gap-free path.

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_derivatives_sustains.py
"""Position survival on HNXDS: margin, liquidation, blocked exits, expiry."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from plutus.market.adapters.datahub import DataHubSource
from plutus.market.exchanges.derivatives import HNXDS_EXCHANGE
from plutus.market.expiry import SettlementResolver
from plutus.market.margin import MarginConfig
from plutus.market.protocol import (
    BandSource, LockEvidence, MarketState, Position, Resolution, SessionPhase, Side,
)
from plutus.market.verdicts import PositionEventKind

from .conftest import requires_corpus


def _path(prices, start=date(2022, 4, 22)):
    """A synthetic daily path with no bands."""
    from datetime import timedelta
    return [
        MarketState(
            ticker='VN30F2212',
            ts=datetime.combine(start + timedelta(days=i), datetime.min.time()),
            last=Decimal(str(p)), session=SessionPhase.CONTINUOUS,
        )
        for i, p in enumerate(prices)
    ]


def _long(entry=Decimal('1441.8'), qty=1, stop=None):
    return Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.BUY, quantity=qty,
        entry_price=entry, entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'), stop_price=stop,
    )


# --- synthetic, no corpus -------------------------------------------------

def test_a_flat_path_survives_with_no_events():
    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8] * 5))
    assert v.survived is True
    assert v.events == ()
    assert v.days_evaluated == 5


def test_a_five_percent_adverse_move_fires_a_margin_call():
    """22.5% posted, 17.5% maintenance -> the 5% buffer is the call distance."""
    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8, 1400.0, 1360.0]))
    call = v.first(PositionEventKind.MARGIN_CALL)
    assert call is not None
    assert call.margin_ratio < MarginConfig.VN30F_DEFAULT.maintenance_rate


def test_margin_call_is_emitted_once_not_daily():
    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8] + [1300.0] * 5))
    calls = [e for e in v.events if e.kind is PositionEventKind.MARGIN_CALL]
    assert len(calls) == 1


def test_equity_wipeout_forces_liquidation_and_ends_the_walk():
    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8, 1100.0, 1000.0, 900.0]))
    liq = v.first(PositionEventKind.FORCED_LIQUIDATION)
    assert liq is not None
    assert v.survived is False


def test_forced_liquidation_implies_an_earlier_or_same_day_call():
    """Normative invariant."""
    v = HNXDS_EXCHANGE.sustains(_long(), _path([1441.8, 1200.0, 1050.0]))
    liq = v.first(PositionEventKind.FORCED_LIQUIDATION)
    call = v.first(PositionEventKind.MARGIN_CALL)
    if liq is not None:
        assert call is not None
        assert call.ts <= liq.ts


def test_a_short_is_called_by_a_rising_market():
    short = Position(
        ticker='VN30F2212', exchange_code='HNXDS', side=Side.SELL, quantity=1,
        entry_price=Decimal('1441.8'), entry_ts=datetime(2022, 4, 22),
        multiplier=Decimal('100000'),
    )
    v = HNXDS_EXCHANGE.sustains(short, _path([1441.8, 1500.0, 1560.0]))
    assert v.first(PositionEventKind.MARGIN_CALL) is not None


def test_call_incidence_is_monotone_in_the_initial_rate():
    """Posting more collateral cannot make a call more likely."""
    path = _path([1441.8, 1380.0, 1340.0, 1300.0])
    called = []
    for rate in ('0.100', '0.175', '0.225', '0.300', '0.350'):
        cfg = MarginConfig.VN30F_DEFAULT.with_initial(Decimal(rate))
        v = HNXDS_EXCHANGE.sustains(_long(), path, margin_config=cfg)
        called.append(v.first(PositionEventKind.MARGIN_CALL) is not None)
    # once False, never True again
    assert called == sorted(called, reverse=True)


def test_exit_blocked_fires_when_the_stop_sits_under_a_locked_floor():
    state = MarketState(
        ticker='VN30F2212', ts=datetime(2022, 5, 9), last=Decimal('1340.0'),
        ceiling=Decimal('1434.0'), floor=Decimal('1340.0'),
        band_source=BandSource.PUBLISHED, session=SessionPhase.CONTINUOUS,
        locked_side=Side.SELL, lock_evidence=LockEvidence.BAR_PROXY,
    )
    v = HNXDS_EXCHANGE.sustains(_long(stop=Decimal('1340.0')), [state])
    assert v.first(PositionEventKind.EXIT_BLOCKED) is not None


def test_no_stop_price_means_no_exit_blocked_event():
    state = MarketState(
        ticker='VN30F2212', ts=datetime(2022, 5, 9), last=Decimal('1340.0'),
        ceiling=Decimal('1434.0'), floor=Decimal('1340.0'),
        band_source=BandSource.PUBLISHED, session=SessionPhase.CONTINUOUS,
        locked_side=Side.SELL, lock_evidence=LockEvidence.BAR_PROXY,
    )
    v = HNXDS_EXCHANGE.sustains(_long(stop=None), [state])
    assert v.first(PositionEventKind.EXIT_BLOCKED) is None


def test_position_limit_is_config_asserted_only():
    """No corpus carries account or limit data, so this is a unit test only and
    the paper claims no incidence for it."""
    from plutus.core.constant import DS
    from plutus.market.exchanges.derivatives import HNXDSExchange

    limited = HNXDSExchange(DS, position_limit=5)
    v = limited.sustains(_long(qty=10), _path([1441.8]))
    assert v.first(PositionEventKind.POSITION_LIMIT_EXCEEDED) is not None


def test_indeterminate_days_are_counted_not_silently_skipped():
    """A state with no usable settlement cannot be judged; say so."""
    path = [MarketState(ticker='VN30F2212', ts=datetime(2022, 5, 9),
                        last=None, session=SessionPhase.CONTINUOUS)]
    v = HNXDS_EXCHANGE.sustains(_long(), path)
    assert v.days_indeterminate == 1


# --- against the corpus ---------------------------------------------------

@requires_corpus
def test_vn30f2212_matches_its_pinned_fixture(corpus_root):
    """Entry 2022-04-22 @1441.8: first call 2022-05-09, liquidated 2022-10-03."""
    source = DataHubSource.for_root(str(corpus_root))
    path = list(source.states('VN30F2212', date(2022, 4, 22), date(2023, 1, 1),
                              resolution=Resolution.DAILY))
    assert path, 'VN30F2212 must have a close path in the corpus'

    v = HNXDS_EXCHANGE.sustains(_long(entry=path[0].last), path)
    call = v.first(PositionEventKind.MARGIN_CALL)
    liq = v.first(PositionEventKind.FORCED_LIQUIDATION)

    assert call is not None and call.ts.date() == date(2022, 5, 9)
    assert liq is not None and liq.ts.date() == date(2022, 10, 3)


@requires_corpus
def test_vn30f2206_is_called_but_never_liquidated(corpus_root):
    """The 'none where it shouldn't' half of the acceptance criterion."""
    source = DataHubSource.for_root(str(corpus_root))
    path = list(source.states('VN30F2206', date(2021, 1, 1), date(2023, 1, 1),
                              resolution=Resolution.DAILY))
    assert path

    position = Position(
        ticker='VN30F2206', exchange_code='HNXDS', side=Side.BUY, quantity=1,
        entry_price=path[0].last, entry_ts=path[0].ts,
        multiplier=Decimal('100000'),
    )
    v = HNXDS_EXCHANGE.sustains(position, path)
    assert v.first(PositionEventKind.MARGIN_CALL) is not None
    assert v.first(PositionEventKind.FORCED_LIQUIDATION) is None


@requires_corpus
def test_expiry_settlement_fires_on_the_third_thursday(corpus_root):
    source = DataHubSource.for_root(str(corpus_root))
    path = list(source.states('VN30F2203', date(2021, 7, 16), date(2022, 3, 18),
                              resolution=Resolution.DAILY))
    position = Position(
        ticker='VN30F2203', exchange_code='HNXDS', side=Side.BUY, quantity=1,
        entry_price=path[0].last, entry_ts=path[0].ts,
        multiplier=Decimal('100000'),
    )
    v = HNXDS_EXCHANGE.sustains(position, path)
    expiry_event = v.first(PositionEventKind.EXPIRY_SETTLEMENT)
    assert expiry_event is not None
    assert expiry_event.ts.date() == date(2022, 3, 17)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=src PLUTUS_DATA_ROOT=/Users/nadan/algotrade-research/dataset/hermes-parquet /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m pytest tests/market/test_derivatives_sustains.py -q`
Expected: FAIL — no module `plutus.market.exchanges.derivatives`.

- [ ] **Step 3: Write the implementation**

```python
# src/plutus/market/exchanges/derivatives.py
"""HNXDS: the derivatives exchange.

Admission here is nearly trivial and that is the point. The round lot is one
contract so the lot rule never binds; the tick grid is a flat 0.1 so the grid
rule is uninteresting; there is no foreign-ownership cap at all. What binds
instead is position survival -- margin, forced liquidation, blocked exits,
position limits and expiry -- none of which has a equity analogue.

Everything here reports what the **exchange** would do. It does not liquidate
on the trader's behalf, re-enter, roll, or compute strategy P&L.
"""

from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from plutus.core.constant import DS, ExchangeSpec
from plutus.market.exchanges.base import Exchange
from plutus.market.expiry import expiry_date
from plutus.market.margin import MarginConfig, evaluate_margin
from plutus.market.protocol import (
    InstrumentSpec, LockEvidence, MarketState, Order, Position, Side,
)
from plutus.market.verdicts import (
    Admissibility, AdmissionRule, PositionEvent, PositionEventKind,
    SettlementSource, Verdict, Viability,
)

__all__ = ['HNXDSExchange', 'HNXDS_EXCHANGE']


class HNXDSExchange(Exchange):
    """Order admission and position survival for VN30 futures."""

    def __init__(
        self,
        spec: ExchangeSpec = DS,
        margin_config: Optional[MarginConfig] = None,
        position_limit: Optional[int] = None,
    ):
        super().__init__(spec)
        self.margin_config = margin_config or MarginConfig.VN30F_DEFAULT
        self.position_limit = position_limit

    # -- admission ---------------------------------------------------------

    def admits(
        self,
        order: Order,
        state: MarketState,
        *,
        instrument: Optional[InstrumentSpec] = None,
        regime_tag: Optional[str] = None,
    ) -> Admissibility:
        """Tick grid, lot of one, and the band rules. No foreign-room rule."""

        def verdict(v, rule=None, bound=None, **detail) -> Admissibility:
            return Admissibility(verdict=v, rule=rule, binding_constraint=bound,
                                 ts=state.ts, regime_tag=regime_tag,
                                 detail=detail)

        price = order.limit_price
        if price is not None:
            tick = self.spec.get_tick_size(order.ticker, price)
            if tick is None:
                return verdict(Verdict.INDETERMINATE, AdmissionRule.TICK_GRID)
            if (price % tick) != 0:
                return verdict(Verdict.REJECTED, AdmissionRule.TICK_GRID, tick)

        unit = instrument.trading_unit if instrument else self.spec.trading_unit
        if order.quantity <= 0 or (order.quantity % unit) != 0:
            return verdict(Verdict.REJECTED, AdmissionRule.ROUND_LOT, unit)

        if price is not None:
            if state.ceiling is None or state.floor is None:
                return verdict(Verdict.INDETERMINATE, AdmissionRule.BAND_LIMIT,
                               band_source=state.band_source.value)
            if price > state.ceiling:
                return verdict(Verdict.REJECTED, AdmissionRule.BAND_LIMIT,
                               state.ceiling)
            if price < state.floor:
                return verdict(Verdict.REJECTED, AdmissionRule.BAND_LIMIT,
                               state.floor)

        return verdict(Verdict.ADMITTED)

    # -- position survival -------------------------------------------------

    def sustains(
        self,
        position: Position,
        path: Sequence[MarketState],
        *,
        settlements: Optional[Dict[object, Decimal]] = None,
        settlement_source: SettlementSource = SettlementSource.CLOSE_PROXY,
        margin_config: Optional[MarginConfig] = None,
    ) -> Viability:
        """Walk a position along a price path and report what the exchange would do.

        Args:
            position: the open position.
            path: daily states in ascending time order.
            settlements: optional ``{date: settlement}`` overriding the
                close proxy. Supply this from
                :class:`plutus.market.expiry.SettlementResolver` to use the
                published or TWAP tiers.
            settlement_source: provenance recorded on each event; must match
                whatever ``settlements`` came from.
            margin_config: overrides the exchange default (used by the sweep).
        """
        config = margin_config or self.margin_config
        events: List[PositionEvent] = []
        indeterminate = 0
        called = False
        expiry = expiry_date(position.ticker)

        if self.position_limit is not None \
                and position.quantity > self.position_limit:
            first_ts = path[0].ts if path else position.entry_ts
            events.append(PositionEvent(
                kind=PositionEventKind.POSITION_LIMIT_EXCEEDED,
                ts=first_ts, settlement=None,
                settlement_source=settlement_source, equity=None,
                notional=None, margin_ratio=None,
                detail={'quantity': position.quantity,
                        'limit': self.position_limit,
                        'note': 'config-asserted; no corpus carries account data'},
            ))

        for state in path:
            day = state.ts.date()
            settlement = (settlements or {}).get(day, state.last)
            if settlement is None or settlement <= 0:
                indeterminate += 1
                continue

            margin = evaluate_margin(position, Decimal(str(settlement)), config)

            if not called and margin.ratio < config.maintenance_rate:
                called = True
                events.append(self._event(
                    PositionEventKind.MARGIN_CALL, state, margin,
                    settlement_source, maintenance=str(config.maintenance_rate)))

            if margin.ratio <= config.liquidation_rate:
                events.append(self._event(
                    PositionEventKind.FORCED_LIQUIDATION, state, margin,
                    settlement_source))
                return Viability(False, tuple(events), len(path), indeterminate)

            if position.stop_price is not None \
                    and self._exit_blocked(position, state):
                events.append(self._event(
                    PositionEventKind.EXIT_BLOCKED, state, margin,
                    settlement_source,
                    stop_price=str(position.stop_price),
                    lock_evidence=state.lock_evidence.value))

            if expiry is not None and day >= expiry:
                events.append(self._event(
                    PositionEventKind.EXPIRY_SETTLEMENT, state, margin,
                    settlement_source, expiry=expiry.isoformat()))
                return Viability(True, tuple(events), len(path), indeterminate)

        return Viability(True, tuple(events), len(path), indeterminate)

    @staticmethod
    def _exit_blocked(position: Position, state: MarketState) -> bool:
        """Would the exchange refuse the exit because the band is locked?"""
        if state.lock_evidence is LockEvidence.UNKNOWN \
                or state.locked_side is None:
            return False
        # A long exits by selling: a locked floor blocks it.
        if position.side is Side.BUY:
            return (state.locked_side is Side.SELL and state.floor is not None
                    and position.stop_price <= state.floor)
        return (state.locked_side is Side.BUY and state.ceiling is not None
                and position.stop_price >= state.ceiling)

    @staticmethod
    def _event(kind, state, margin, source, **detail) -> PositionEvent:
        return PositionEvent(
            kind=kind, ts=state.ts, settlement=margin.settlement,
            settlement_source=source, equity=margin.equity,
            notional=margin.notional, margin_ratio=margin.ratio,
            detail=detail,
        )


HNXDS_EXCHANGE = HNXDSExchange(DS)
```

Then extend `src/plutus/market/exchanges/__init__.py`:
```python
from plutus.market.exchanges.derivatives import HNXDS_EXCHANGE, HNXDSExchange

__all__ = ['Exchange', 'EquityExchange', 'HSX_EXCHANGE', 'HNX_EXCHANGE',
           'UPCOM_EXCHANGE', 'HNXDSExchange', 'HNXDS_EXCHANGE']
```

- [ ] **Step 4: Run tests**

Expected: PASS. Full suite: `575 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/plutus/market/exchanges tests/market/test_derivatives_sustains.py
git commit -m "Add HNXDS position survival: margin, liquidation, blocked exits, expiry"
```

---

### Task 12: Margin incidence — the derivatives headline

**Files:**
- Create: `measurements/margin_incidence.py`
- Test: `tests/market/test_margin_incidence.py`

**Interfaces:**
- Consumes: `DataHubSource`, `HNXDS_EXCHANGE`, `MarginConfig`, `SettlementResolver`.
- Produces: `measure_margin_incidence(data_root, *, holding_days, initial_rate=None) -> MarginIncidenceResult` with `entries`, `called`, `liquidated`, `call_rate`, `liquidation_rate`, `holding_days`, `initial_rate`, `contracts`.

**The entry policy is pinned here, because without one this measurement has no meaning.** Front-month series (`quote_futurecontractcode = 'VN30F1M'`, 414 dates from **2021-06-01** — `VN30F2101`–`VN30F2105` are absent entirely, so a front-month series cannot start earlier). Enter long 1 contract at each session close; hold H ∈ {5, 10, 20} sessions or to expiry, whichever comes first; report incidence per H.

Sanity envelope, already measured: worst 1-day −6.90%, 3-day −10.54%, 10-day −16.54%, 20-day −22.25%. At 22.5% posted with a 5%-of-notional trigger, H=5 and H=10 both produce non-trivial, non-saturated incidence.

**Do not report the buy-and-hold-to-expiry figure as an incidence.** Holding every contract from first close to last calls 28/28 at 17.5% — that is a monotonicity fixture, not a publishable rate.

- [ ] **Step 1: Write the failing test**

```python
# tests/market/test_margin_incidence.py
"""Derivatives headline: how often the exchange would call a front-month long."""

from decimal import Decimal

import pytest

from measurements.margin_incidence import measure_margin_incidence
from plutus.market.margin import MarginConfig

from .conftest import requires_corpus


@requires_corpus
@pytest.mark.parametrize('holding_days', [5, 10, 20])
def test_incidence_is_computed_and_non_degenerate(corpus_root, holding_days):
    r = measure_margin_incidence(str(corpus_root), holding_days=holding_days)
    assert r.entries > 100
    assert 0 < r.call_rate < 1, 'saturated or empty incidence is not a result'


@requires_corpus
def test_longer_holds_are_at_least_as_risky(corpus_root):
    short = measure_margin_incidence(str(corpus_root), holding_days=5)
    long_ = measure_margin_incidence(str(corpus_root), holding_days=20)
    assert long_.call_rate >= short.call_rate


@requires_corpus
def test_call_rate_is_monotone_non_increasing_in_the_initial_rate(corpus_root):
    rates = [Decimal('0.150'), Decimal('0.225'), Decimal('0.300')]
    observed = [
        measure_margin_incidence(str(corpus_root), holding_days=10,
                                 initial_rate=r).call_rate
        for r in rates
    ]
    assert observed == sorted(observed, reverse=True)


@requires_corpus
def test_liquidation_never_exceeds_calls(corpus_root):
    r = measure_margin_incidence(str(corpus_root), holding_days=20)
    assert r.liquidated <= r.called


@requires_corpus
def test_result_is_json_serialisable(corpus_root):
    import json

    r = measure_margin_incidence(str(corpus_root), holding_days=10)
    decoded = json.loads(json.dumps(r.to_dict()))
    assert decoded['holding_days'] == 10
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — no module `measurements.margin_incidence`.

- [ ] **Step 3: Write the implementation**

```python
# measurements/margin_incidence.py
"""How often would the exchange call a front-month VN30F long?

The entry policy is part of the result and is stated in the output: enter long
one contract at each session close of the front-month series, hold H sessions
or to expiry, whichever comes first.

The margin rate is a **modelling assumption** (17.5% VSD + 5% broker buffer,
sweepable) because no margin data exists in either corpus. Reporting incidence
across a range of rates is therefore part of the deliverable, not a fallback.
"""

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

from plutus.market.exchanges.derivatives import HNXDSExchange
from plutus.market.margin import MarginConfig
from plutus.market.protocol import (
    MarketState, Position, SessionPhase, Side,
)
from plutus.market.verdicts import PositionEventKind

__all__ = ['MarginIncidenceResult', 'measure_margin_incidence']

FRONT_MONTH_START = date(2021, 6, 1)   # VN30F2101-2105 are absent entirely


@dataclass(frozen=True)
class MarginIncidenceResult:
    entries: int
    called: int
    liquidated: int
    call_rate: Decimal
    liquidation_rate: Decimal
    holding_days: int
    initial_rate: Decimal
    contracts: int

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for key in ('call_rate', 'liquidation_rate', 'initial_rate'):
            out[key] = float(getattr(self, key))
        out['entry_policy'] = (
            'long 1 front-month contract at each session close; hold '
            f'{self.holding_days} sessions or to expiry'
        )
        out['backs'] = (
            'paper derivatives headline: share of front-month longs the '
            'exchange would margin-call'
        )
        return out


def _reader(root: Path, table: str) -> str:
    parquet = root / f'{table}.parquet'
    if parquet.exists():
        return f"read_parquet('{parquet}')"
    return f"read_csv_auto('{root / f'{table}.csv'}')"


def measure_margin_incidence(
    data_root: str,
    *,
    holding_days: int,
    initial_rate: Optional[Decimal] = None,
) -> MarginIncidenceResult:
    root = Path(data_root)
    conn = duckdb.connect()

    rows = conn.execute(
        f"""SELECT tickersymbol, datetime, price
            FROM {_reader(root, 'quote_close')}
            WHERE tickersymbol LIKE 'VN30F%' AND datetime >= ?
            ORDER BY tickersymbol, datetime""",
        [FRONT_MONTH_START],
    ).fetchall()

    by_contract: Dict[str, List[tuple]] = {}
    for ticker, day, price in rows:
        by_contract.setdefault(ticker, []).append((day, Decimal(str(price))))

    config = MarginConfig.VN30F_DEFAULT
    if initial_rate is not None:
        config = config.with_initial(initial_rate)
    exchange = HNXDSExchange(margin_config=config)

    entries = called = liquidated = 0
    for ticker, series in by_contract.items():
        for i in range(len(series) - 1):
            window = series[i:i + holding_days + 1]
            if len(window) < 2:
                continue
            entry_day, entry_price = window[0]
            path = [
                MarketState(
                    ticker=ticker,
                    ts=__import__('datetime').datetime.combine(
                        day, __import__('datetime').time()),
                    last=price, session=SessionPhase.CONTINUOUS,
                )
                for day, price in window[1:]
            ]
            position = Position(
                ticker=ticker, exchange_code='HNXDS', side=Side.BUY,
                quantity=1, entry_price=entry_price,
                entry_ts=__import__('datetime').datetime.combine(
                    entry_day, __import__('datetime').time()),
                multiplier=config.default_multiplier,
            )
            viability = exchange.sustains(position, path)
            entries += 1
            if viability.first(PositionEventKind.MARGIN_CALL) is not None:
                called += 1
            if viability.first(PositionEventKind.FORCED_LIQUIDATION) is not None:
                liquidated += 1

    denom = Decimal(entries) if entries else Decimal('1')
    return MarginIncidenceResult(
        entries=entries, called=called, liquidated=liquidated,
        call_rate=Decimal(called) / denom,
        liquidation_rate=Decimal(liquidated) / denom,
        holding_days=holding_days, initial_rate=config.initial_rate,
        contracts=len(by_contract),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--json', type=Path, default=None)
    parser.add_argument(
        '--sweep', action='store_true',
        help='also report incidence across a range of initial rates',
    )
    args = parser.parse_args()

    results: Dict[str, Any] = {}
    print(f"{'hold':>5} {'entries':>8} {'called':>7} {'call%':>8} "
          f"{'liq':>5} {'liq%':>7}")
    for hold in (5, 10, 20):
        r = measure_margin_incidence(args.data_root, holding_days=hold)
        results[f'hold_{hold}'] = r.to_dict()
        print(f'{hold:>5} {r.entries:>8,} {r.called:>7,} '
              f'{float(r.call_rate):>7.2%} {r.liquidated:>5,} '
              f'{float(r.liquidation_rate):>6.2%}')

    if args.sweep:
        print('\nsensitivity to the posted initial rate (hold=10):')
        for rate in ('0.150', '0.175', '0.200', '0.225', '0.250', '0.300'):
            r = measure_margin_incidence(args.data_root, holding_days=10,
                                         initial_rate=Decimal(rate))
            results[f'sweep_{rate}'] = r.to_dict()
            marker = '  <- published' if rate == '0.225' else ''
            print(f'  {rate}  call {float(r.call_rate):>7.2%}  '
                  f'liq {float(r.liquidation_rate):>6.2%}{marker}')

    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f'\nwrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 4: Run it and record the numbers in the plan**

Run:
```bash
PYTHONPATH=src:. /Users/nadan/.pyenv/versions/3.12.4/bin/python3 -m measurements.margin_incidence --data-root /Users/nadan/algotrade-research/dataset/hermes-parquet --sweep
```
Expected: three holding-period rows with `0 < call% < 100`, and a sweep whose `call%` is monotone non-increasing as the rate rises. **Paste the actual output into this task as the pinned baseline before committing**, then tighten `tests/market/test_margin_incidence.py` to assert those integers rather than the loose bounds it ships with.

- [ ] **Step 5: Run tests and commit**

Full suite expected: `580 passed`.

```bash
git add measurements/margin_incidence.py tests/market/test_margin_incidence.py
git commit -m "Measure front-month margin-call incidence with a stated entry policy"
```

**Phase B is complete here.** Both halves of the framework are implemented and measured: order admission on the equity exchanges, position survival on the derivatives exchange.

---

## Phase C — Tick resolution and the remaining measurements (Tasks 13–16)

---

### Task 13: The tick adapter

**Files:** Create `src/plutus/market/adapters/tick.py`; Test `tests/market/test_tick_adapter.py`

**Interfaces:**
- Produces: `TickSource(archive_root, band_source)` implementing `MarketDataSource` at `Resolution.TICK`; `forward_fill_book(rows, ts) -> OrderBook`.

**Why the book matters:** at bar resolution a lock is inferred from `last == ceiling`. At tick resolution it is *observed* — there is no ask below the ceiling in the ladder. That upgrades `lock_evidence` from `BAR_PROXY` to `TICK_BOOK`.

`quote_bidprice`/`quote_askprice` carry depth 1–3 from 2021-01-15. **Sizes are 0-row in every corpus**, so `BookLevel.size` stays `None` and no rule may require it. The two sides are not synchronised in time; forward-fill each independently and record `as_of`.

- [ ] **Step 1:** Write `tests/market/test_tick_adapter.py` asserting: (a) `TickSource` yields states with `lock_evidence is LockEvidence.TICK_BOOK` when the ask ladder has no level below the ceiling; (b) `BookLevel.size is None` for every level; (c) `states(..., resolution=Resolution.DAILY)` raises `ValueError`; (d) a ticker-date with no ask rows yields `lock_evidence is LockEvidence.UNKNOWN`, never a guess. Gate every test with `requires_ticks`.
- [ ] **Step 2:** Run — expect `ModuleNotFoundError`.
- [ ] **Step 3:** Implement `TickSource`. Read `quote_askprice.csv`/`quote_bidprice.csv` filtered to one ticker-date, forward-fill each side to the evaluation instant, build `OrderBook(bids, asks, as_of)`, and set `locked_side=Side.BUY, lock_evidence=TICK_BOOK` when the best ask is `>= ceiling` (no offer below the cap). Bands come from the daily source passed in as `band_source`.
- [ ] **Step 4:** Run tests; full suite green.
- [ ] **Step 5:** `git commit -m "Add tick adapter with observed book locks"`

---

### Task 14: Bar-vs-tick divergence

**Files:** Create `measurements/bar_vs_tick.py`; Test `tests/market/test_bar_vs_tick.py`

**One population for both arms, or the divergence is undefined.** Use HSX `instrumenttype='stock'` ticker-days in 2021-02-17…2022-12-30 that (a) have `askprice` rows that date and (b) pass the band-consistency screen `abs(ceil/ref − 1.07) < 0.004`. Report bar-blocked, tick-blocked and `n` **on that identical set**.

Do **not** reuse the 25,894 bar figure or the 7,170 tick-pool figure from recon as the denominators — they are different populations, and the recon's own duration histogram sums to 7,449 against a stated pool of 7,170. Recompute.

The ask-only tick pipeline runs in ~12 s over the raw archive, so this is a script stage, not a research project.

- [ ] **Step 1:** Write the test: `n` is identical for both arms; both counts are ≤ `n`; the result is JSON-serialisable; gated `requires_ticks and requires_corpus`.
- [ ] **Step 2:** Run — expect failure.
- [ ] **Step 3:** Implement `measure_bar_vs_tick(data_root, tick_root)` returning `n`, `bar_blocked`, `tick_blocked`, `agreement`, `population` (a human-readable description of the screen).
- [ ] **Step 4:** Run it, paste the output into this task as the pinned baseline, tighten the test to those integers.
- [ ] **Step 5:** `git commit -m "Measure bar-vs-tick lock divergence on one common population"`

---

### Task 15: Grid conformity, with a naive baseline we define

**Files:** Create `measurements/grid_conformity.py`; Test `tests/market/test_grid_conformity.py`

**The claimed 91.62% naive baseline is unreproducible** — six candidate grids × eight universes, nearest 91.53%, and the figure appears nowhere in code. It must be **defined by us and stated**, not inherited.

Define the naive baseline explicitly as **a flat 0.1 grid over HSX closes** (83.86% measured) and report the library rule against it: **100.00%** (n=1,101,201 HSX closes; HSX-stock n=1,086,518 also 100.00%). Report the C/E/F warrant exception's contribution separately — without it, HSX all-types conformity is 99.84%, so the exception is load-bearing for exactly the warrant/ETF slice and worth 0.16 pp overall.

- [ ] **Step 1:** Write the test: library rule is exactly `1.0` on HSX closes; the named naive baseline is strictly below it; the chosen baseline is recorded in the result dict; assert the n values above as integers.
- [ ] **Step 2:** Run — expect failure.
- [ ] **Step 3:** Implement using `plutus.core.constant.get_hsx_tick_size`, handling its `None` return for unmatched prices as "not conformant" and counting those separately.
- [ ] **Step 4:** Run; confirm 100.00% and the baseline.
- [ ] **Step 5:** `git commit -m "Measure tick-grid conformity against an explicitly defined naive baseline"`

---

### Task 16: Wire the measurements in and update the claim map

**Files:** Modify `reproduce_measurements.py`; Modify `README.md`; Modify `docs/superpowers/specs/2026-08-24-exchange-fill-model-design.md` (§4 claim table)

- [ ] **Step 1:** Add four stages to `reproduce_measurements.py` — equity admission (both lags), margin incidence, grid conformity, bar-vs-tick. Hang the tick stage off the **existing** `--raw-root` flag, skipping with a stated reason when absent (matching the `--csv-root` convention). Renumber the `[N/5]` progress prints to `[N/9]`. Give each new result dict the file's `"backs": "<claim it defends>"` key.
- [ ] **Step 2:** Run `reproduce_measurements.py` end to end with all three roots; confirm every stage reports.
- [ ] **Step 3:** Update `README.md`: add a `plutus.market` section stating the exchange-side/trader-side boundary, the six admission rules, the five position events, and the availability matrix (which rules are measurable on which corpus at which resolution). Update the test-count badge to the final number.
- [ ] **Step 4:** Update the spec's §4 claim table with the measured figures, replacing the handoff's unreproduced 12.96%/8.25%/91.62%/16.54% with what the code computes.
- [ ] **Step 5:** Full suite green; `git commit -m "Wire exchange measurements into reproduce_measurements and update claims"`

---

## Availability matrix — which rules are measurable where

| Rule | Parquet corpus | Raw archive | Note |
|---|---|---|---|
| `TICK_GRID` | ✅ | ✅ | Rule-only; needs no market data beyond a price |
| `ROUND_LOT` | ✅ | ✅ | Rule-only |
| `BAND_LIMIT` | ✅ 2021-02-05+ | ✅ | Bands start 2021-02-05; reconstruct from reference where absent |
| `BAND_LOCK` (bar proxy) | ✅ | ✅ | `last == ceiling` |
| `BAND_LOCK` (book) | ❌ | ✅ 2021-01-15+ | Ask/bid **prices** only; sizes are 0-row everywhere |
| `FOREIGN_ROOM` | ❌ | ⚠️ | `has_field('foreign_room')` is False on Parquet; the archive's table is the *cap*, not remaining room. **Returns INDETERMINATE in practice** |
| `SESSION_SEMANTICS` | ⚠️ | ✅ | Daily states are forced to `CONTINUOUS`; only tick states carry a real phase |
| `MARGIN_CALL` / `FORCED_LIQUIDATION` | ✅ | ✅ | Rate is a modelling assumption; close is the MTM proxy |
| `EXIT_BLOCKED` | ✅ | ✅ | Needs a `stop_price` from the caller |
| `POSITION_LIMIT_EXCEEDED` | ❌ | ❌ | No account/limit data in any of 80 tables. Config-asserted, unit-tested, **no incidence claimed** |
| `EXPIRY_SETTLEMENT` | ✅ | ✅ | Third Thursday, verified 24/24 |

## Known corpus defects the implementer will meet

| Defect | Where | Consequence |
|---|---|---|
| `UPCOM.trading_time_end` raises `AttributeError` | `constant.py:250-253` | Never loop `trading_time_end` over all four specs |
| `get_hsx_tick_size` returns `None` | `constant.py:299-301` | Handle `None`; it is annotated `-> Decimal` and lies |
| Tick bands are lower-inclusive | `constant.py:293-301` | `10.00` → `0.05`, not `0.01`. `HANDOFF:163` is wrong |
| 5 of 8 `core/*.py` unimportable | bare `import utils` | Only `constant`, `instrument`, `order` are safe |
| Shared DuckDB connection | `ohlc_query.py:54` | Never hold two live iterators from one query object |
| 87 tickers absent from the master | `quote_ticker` | `instrument()` must never raise |
| 1,272 inverted bands, 1,226 of them equities | `quote_ceil`/`quote_floor` | The `ceil >= floor` filter is load-bearing on the equity headline |
