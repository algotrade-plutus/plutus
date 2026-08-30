# E1 replacement: population-level fill-policy divergence

**Version 1.0 · 2026-08-30.** Cite as *"Plutus E1 Fill-Divergence Specification"*.

Audience: the implementation session. This specifies a replacement for the
paper's E1 experiment, why the current one is unsound, the exact API to build it
on, the one blocker in the way, and the acceptance criteria.

---

## 1. Why the current E1 must be replaced

E1 currently sweeps **three strategies (S1, S2, S5) × three fill policies** and
reports each arm's **return**. Three independent problems, any one of which a
reviewer can raise:

**1a. Sign confound — the strategies lose money when they fill.** S1, S2 and S5
were written to *express a mechanism* (forced liquidation, a stop blocked by
limit-down locks, the sale advance). Negative P&L is by construction. The sweep
therefore reads `fills → loss, no fills → flat`, which invites the inference that
the strict policy is **safer**. It is not safer; it is blinder. What the table
actually shows is a property of strategy selection, not of the fill policy.

**1b. n is too small to carry the claim.** "The fill policy is worth 71.3
points" rests on **4 fills** (S2). S1 rests on 5. That is an anecdote with a
decimal point, not an estimate. S8's maker panel survives this only because it
measures *quantity over many order events* (152.6k shares) rather than P&L over
four trades — which is the clue to what the taker panel should have been.

**1c. The metric is outside the library's own contract.** From
`fills.py::DivergenceReport`:

> **It reports fills, not performance.** No return, no P&L, no Sharpe: this
> package is the exchange, not a backtester […] What is here is what the
> exchange can honestly say — outcome per policy, quantity per policy, where
> they disagree, and how much of the flow each policy could not decide.

The paper's headline experiment currently reports exactly the quantity the
library says the exchange must not report. The replacement below fixes 1a, 1b
and 1c at once, because the fix for all three is the same: **measure fills over a
population, not returns over three strategies.**

---

## 2. The replacement experiment

**Question.** Over a realistic order flow, what share of fill decisions is
determined by the *assumption* rather than by the market — and how much executed
quantity does the assumption move?

**Design.** Hold everything fixed except the fill policy. Evaluate one large flow
of order decisions under all three shipped policies with
`fills.compare_policies`, which is the instrument built for this and already
treats `INDETERMINATE` as a first-class column.

**Population.** HSX equities, 2022 (post the 2021-01-04 lot change, so a single
undated `HSX_EXCHANGE` rules object is correct and dating is not a second
variable). Target ≥ 100 tickers × ≥ 200 sessions. Five order intents per
ticker-day, all priced off the corpus's own on-grid values so tick-grid
rejection never confounds the comparison:

| intent | side | type | price |
|---|---|---|---|
| `market_buy` | BUY | MARKET | — |
| `limit_buy_at_close` | BUY | LIMIT | `state.last` |
| `limit_sell_at_close` | SELL | LIMIT | `state.last` |
| `limit_buy_at_floor` | BUY | LIMIT | `state.floor` |
| `limit_sell_at_ceil` | SELL | LIMIT | `state.ceiling` |

That is ~100k questions — three orders of magnitude more than the current E1,
and every one of them sign-free.

**Reported metrics** (all from `DivergenceReport`, none of them P&L):

- `agreement_rate` — share of decisions all three policies answered identically.
  **The headline.** Its complement is the share of a realistic order flow whose
  outcome is set by the assumption.
- `outcomes(sig)` — FILLED / not / INDETERMINATE counts per policy.
- `indeterminate_rate(sig)` — each policy's bound on its own ignorance.
- `filled_quantity(sig)` — executed shares per policy. The optimistic:strict
  ratio is the taker analogue of S8's 18.9% maker swing, and it is a *quantity*
  spread, exactly as the maker panel is.
- **Divergence by intent** — the `by_intent` breakdown is the interpretable
  result: it should show market orders diverging ~always and deep passive limits
  agreeing ~always. That is the finding a researcher can act on ("your exposure
  to this assumption is a function of your order mix"), and it is what the
  current E1 cannot say at all.

---

## 3. Blocker: the daily interval carries close only

**This must be fixed first or the experiment is meaningless.** Verified on this
machine, 2026-08-30:

```python
iv = DataHubSource.for_root(BAR).interval(
        "FPT", datetime(2022,3,15,0,0), datetime(2022,3,16,0,0))
iv.missing  # frozenset({DataField.OPEN, DataField.HIGH,
            #            DataField.LOW,  DataField.BOOK_SIZE})
```

The daily bar the adapter serves has **no open, high or low**. Consequences:

- Any policy needing intrabar extent answers `INDETERMINATE` on essentially
  every limit order. All three arms then agree — *for the wrong reason* — and
  `agreement_rate` becomes a measurement of the adapter's poverty rather than of
  the assumption's weight.
- This is the same defect behind the paper's 100.0% bar-resolution indeterminate
  rate, already flagged as pending in `PAPER-HANDOFF.md` §8.

**The fix is available and cheap.** `quote_max` / `quote_min` in the corpus are
**session high/low** — established three ways earlier in this project
(non-monotone day-over-day; `high < close` on 326 of 3.88M rows; 99.82% exact
agreement with a daily aggregation of the intraday `quote_high`) — and they cover
2000-07-28 → 2022-12-30, not just the 2021+ intraday window. Enrich
`DataHubSource.interval` to populate `high`/`low` from them (and `open` from
`quote_open`), and drop those fields from `missing`.

Landing this fixes two things at once: it makes the population experiment
meaningful, **and** it collapses the 100.0% bar-resolution figure into an honest
one, which is the single highest-value outstanding improvement to §VII.

---

## 4. API notes, and the pitfalls already hit

Everything needed ships. Imports:

```python
from plutus.market.adapters.datahub import DataHubSource
from plutus.market.exchanges.equity import HSX_EXCHANGE
from plutus.market.session.fills import (SoftFillPolicy, HardFillPolicy,
                                         ProbabilisticFillPolicy,
                                         FillQuestion, compare_policies)
from plutus.market.session.types import (OrderRecord, Order, Side, OrderType,
                                         OrderState, TimeInForce, Venue)
```

- **`InstrumentSpec` has `exchange_code` (str `'HSX'`), NOT `.venue`.** A pilot
  filtered the universe with `spec.venue is Venue.HSX` inside a bare `except`,
  which swallowed the `AttributeError`, returned an empty universe, and produced
  an empty flow — `agreement_rate` then returns `None` (correctly: 0/0 is not
  100% agreement). Filter on `spec.exchange_code == 'HSX'`, and **never** wrap
  universe selection in a bare `except`.
- **A `FillQuestion` needs an `OrderRecord`, not an `Order`.** Build it as
  `tests/market/session/test_fills.py::_order` does: `OrderRecord(order_id=…,
  venue=Venue.HSX, state=OrderState.RESTING, time_in_force=TimeInForce.DAY,
  submitted_at=…, updated_at=…, fills=(), order=Order(…))`.
- **Pass `instrument=` and `already_filled=`.** `FillQuestion`'s own docstring
  says these are the two arguments callers forget and that forgetting either
  changes the answer — no `already_filled` evades the participation cap, no
  `instrument` falls back to the venue-and-date lot.
- **Policies must have distinct signatures** or `compare_policies` raises. Use
  the same cap the strategy arms use (`max_participation = 0.10`) so the result
  is comparable to S7: `SoftFillPolicy(Decimal('0.10'))`,
  `HardFillPolicy(Decimal('0.10'))`,
  `ProbabilisticFillPolicy(7, max_participation=Decimal('0.10'))`.
- **Run from a Python 3.12+ interpreter.** `margin_lending.py` uses a
  `mappingproxy` dataclass default that is a `ValueError` on 3.11. The repo's own
  `.venv` may be unusable from a sandboxed session (its pyenv `libpython` can sit
  outside granted paths); a plain 3.12 env with `duckdb pandas pyarrow pytz
  pytest` is sufficient. `pytest` is needed because the strategy modules import
  it at module scope.

A working-but-blocked pilot exists as `fill_divergence.py` — universe query, flow
builder and reporting are written; it needs the `exchange_code` fix plus §3 to
produce a real result. It is **not committed to this repo**: it lives in the paper
session's artifacts, and should be placed under `measurements/` only once it
actually runs, so that nothing under `measurements/` is a script that cannot
produce its output.

---

## 5. What NOT to change

- **The maker/queue panel (S8/S9) stays as it is.** It already measures quantity
  over many order events and carries its undecided share per arm; it is the one
  half of E1 that was never confounded.
- **Do not delete the Sx strategies from the paper.** They belong in §V as the
  fidelity-evidence suite, where "the rule emerges from P&L" is the claim and the
  small trade counts do not matter. They are only unsound as the *headline
  sensitivity measurement*.
- **Do not report P&L in the new experiment**, even if asked. §1c.

---

## 6. Acceptance criteria

1. `interval()` on a 2022 HSX ticker-day returns `high`/`low`/`open` populated
   and `missing` no longer containing `OPEN`, `HIGH`, `LOW`; existing tests green
   (1,646 unit + 38 scenario + 13 strategy).
2. The F2 bar-resolution indeterminate rate regenerates to a value **below
   100.0%**, and `t4_measured_results.md` is updated.
3. `fill_divergence.py` runs over ≥ 100 HSX tickers × ≥ 200 sessions and emits
   `agreement_rate`, per-policy outcomes / indeterminate rate / filled quantity,
   and the by-intent divergence breakdown, into a committed JSON.
4. The by-intent breakdown separates market orders from deep passive limits —
   i.e. divergence is **not** uniform across intents. If it is uniform, the
   population or the pricing is wrong; investigate before reporting.
5. Numbers land in `t4_measured_results.md` so the paper can quote T4 as its
   single source, per the standing discipline.

---

## 7. What the paper does with it

Replace E1's taker panel. The figure becomes: a divergence-by-intent bar or dot
plot (share of decisions where the policies disagree, per order intent) beside
the existing maker panel. The sentence it supports:

> Over N order decisions across the HSX universe in 2022, the three shipped fill
> policies disagree on X% — and the disagreement is concentrated in market and
> marketable-limit orders, where it approaches Y%, while deep passive limits are
> decided by the market rather than the assumption.

That claim is large-n, sign-free, generalizes beyond three hand-written
strategies, and stays inside what the library says an exchange may report. The
current E1 has none of those four properties.
