# PLUTUS — A Simulated Vietnamese Exchange, Behind a Broker API

> **Backtest under the rules that actually applied.** An executable,
> *effective-dated* model of the rules HOSE, HNX, UPCoM and the VSDC depository
> apply to an order and to a position — order admission, T+2 settlement, and
> segregated derivatives margin — that you point a strategy at.

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/market%20suite-1646%20passing-brightgreen.svg)]()

Plutus is a library for people who want to validate a trading method against a
**faithful Vietnamese counterparty** rather than a generic backtester. It
resolves every rule *per simulated instant* from a dated rulebook, so a run in
2024 obeys the 2024 rules and a run across the 2025 KRX cutover obeys both
editions in turn. Where the data cannot decide whether an order filled, it says
so — it never guesses.

The market-data layer (DataHub, MCP, the corpus audit) is the substrate that
feeds the simulator; it is documented lower down. Bring your own bars or book
and the same rules apply.

---

## What Plutus is — and is not

**It is** an executable model of an *exchange* and a *broker*, exposed as one
counterparty behind a broker-shaped API: you `submit` an order, `advance_to` a
later instant, and read back `holdings`, `positions`, `margin`, `cash` and the
events the exchange raised. Under that API sit:

- a **dated rulebook** resolved per instant (`Rulebook.at(ts)`), spanning three
  equity venues, a price-dependent tick grid, band regimes, and the pre-/post-KRX
  derivatives-margin editions;
- a **VSDC settlement-business-day calendar** wired to unsettled cash and
  unsettled shares (real T+2, not day-counting — it diverges around Tết);
- a **segregated derivatives deposit** with dated initial margin, daily
  variation-margin cash settlement, position limits and expiry;
- pluggable **fill** and **queue** assumptions, each self-reporting the
  assumption it rests on, so the output carries its own error bar.

**It is not** a strategy library, an alpha source, or a claim about any dataset.
It does not tell you what to trade. It tells you, precisely and with its
provenance, what the Vietnamese market infrastructure would have done to the
orders you sent — including "the available data cannot establish whether this
filled."

> Earlier releases described `plutus.market` as "a fill model, not a backtesting
> engine — no order lifecycle, no P&L." That was the *stateless* first design.
> The system has since become a **stateful session**: order lifecycle,
> settlement, margin accounts and the broker-facing API are all in scope. This
> README describes the current system.

---

## Install

```bash
git clone https://github.com/algotradevn/plutus.git
cd plutus
pip install -e .
```

Requires **Python 3.12+**. Dependencies (DuckDB, PyArrow, FastMCP, …) install
automatically.

---

## Quick start

### 1. Admission in six lines (stateless)

The lightest surface: ask whether an order would be *admitted* against a market
state, no session required.

```python
from datetime import datetime
from decimal import Decimal
from plutus.market.adapters import DataHubSource
from plutus.market.exchanges import HSX_EXCHANGE
from plutus.market.protocol import Order, Side

source = DataHubSource.for_root('/path/to/dataset')
state = source.state_at('FPT', datetime(2021, 6, 15))
order = Order(ticker='FPT', side=Side.BUY, quantity=100, limit_price=Decimal('83.8'))

verdict = HSX_EXCHANGE.admits(order, state)
print(verdict.verdict, verdict.rule)   # Verdict.ADMITTED None
```

### 2. Trade against the session (the broker API)

The full counterparty: submit, let time pass, read your account back. The
session is built from a two-part config — dated `exchange_rules` and a
commercial `broker_profile` — and any `MarketDataSource`.

```python
from datetime import datetime
from decimal import Decimal
from plutus.market.session import ExchangeSession
from plutus.market.adapters import DataHubSource
from plutus.market.protocol import Order, Side, OrderType

session = ExchangeSession.from_config(
    'exchange.json',
    source=DataHubSource.for_root('/path/to/dataset'),
)

session.advance_to(datetime(2022, 11, 9, 9, 30))
accepted = session.submit(Order(
    ticker='FPT', side=Side.BUY, quantity=100,
    order_type=OrderType.LIMIT, limit_price=Decimal('80.0'),
))
print(accepted.order_id, accepted.state)          # a resting order

session.advance_to(datetime(2022, 11, 9, 14, 0))  # time passes; fills happen
held = session.holdings('FPT')
print(held.settled, held.committed, held.unsettled)   # T+2 tranches
print(session.cash().settled_balance)
print(session.margin().deposit_balance)               # derivatives deposit

# What could the data NOT decide this run?
print(session.indeterminate_report())
```

`submit` returns `Accepted | Rejected`; a rejection names the rule that bound
and the instant it bound at. `advance_to` and `poll` return the events the
exchange raised (fills, margin calls, settlement, expiry).

---

## The model

### Two halves: admission and survival

| Half | Method | Binds on | The rules |
|---|---|---|---|
| **Admission** — stateless | `admits(order, state)` | **equity** (HSX/HNX/UPCoM) | band / lot / grid / order-type |
| **Survival** — stateful | the session margin path | **derivatives** (HNXDS) | margin / liquidation / expiry |

On equity, admission does the work and survival is nearly trivial. On
derivatives it inverts — admission is almost free, and *that triviality is the
finding*: the constraint that bites is whether the position survives the day's
margin.

### Effective-dated rule editions — the lead capability

Every rule carries the dates it was in force. `Rulebook.at(ts)` resolves the
edition that applied at the simulated instant, and **refuses** an order it can
only judge with an out-of-window edition (`UnresolvedRule` →
`Rejected(INDETERMINATE)`) rather than silently using today's rule for a 2021
order. This is what lets a backtest answer *"what would this have done under the
rules in force then?"* — demonstrated on both sides: equity round-lot change
(2021-01-04), band regimes, and the ~30% pre-/post-KRX margin gap on a fixed
book.

### Order admission — the six rules

| Rule | Question |
|---|---|
| `TICK_GRID` | Is the price on the exchange's price-dependent grid? |
| `ROUND_LOT` | Is the size a multiple of the lot (100 equity, 1 derivative)? |
| `BAND_LIMIT` | Is the price inside `[floor, ceiling]`? Stateless. |
| `BAND_LOCK` | Is this a *marketable* order into a *locked* band? Fillability. |
| `FOREIGN_ROOM` | Does a foreign buy fit the remaining ownership room? |
| `SESSION_SEMANTICS` | Is this order type valid in this session phase? |

`BAND_LIMIT` and `BAND_LOCK` are separate on purpose. An order priced *at* the
ceiling is admissible — the exchange accepts it; it simply may not fill.

### Position survival — the five events

`MARGIN_CALL`, `FORCED_LIQUIDATION`, `EXIT_BLOCKED`, `POSITION_LIMIT_EXCEEDED`,
`EXPIRY_SETTLEMENT`. The session raises these as it advances; you read them from
the event stream, not by asking.

### Dated derivatives margin

The deposit runs under whichever margin edition the date selects:

- **pre-KRX** — `MR = IM + VM`, dated VSD initial margin plus variation margin;
- **post-KRX** (QĐ 26) — the scenario-margin stack `MR = Max(ΣPgm, 0)`.

Daily variation margin settles in cash (QĐ 26 Điều 20). No margin *account* data
exists in the corpus, so the funding level is a **stated assumption** (a fitted
deposit of 1.42× the opening requirement), never a measured fact.

### Three-state verdicts and the Fill Evidence Level

Verdicts are `ADMITTED`, `REJECTED`, `INDETERMINATE`. The third is the honesty
spine: when the data needed to judge a rule is absent, the model reports that
rather than guessing, and attributes it to the rule that could not be evaluated.

Fills carry a **Fill Evidence Level** — `PROVEN` (the tape traded through the
price), `ASSUMED` (a touch or a modelled maker fill), or `UNEVIDENCED`. A fill
policy is, precisely, *a rule for the lowest evidence level it will act on*.

### Fill policy × queue assumption

Two pluggable axes. The **fill policy** (`soft` / `hard` / `probabilistic`)
decides how much evidence a fill needs; the **queue assumption** (optimistic /
conservative / probabilistic) decides where you sit in line. Neither is a
default the library hides — each is chosen by the caller and self-reported on
the result, because the choice moves the answer by a material amount (below).

---

## Measured results

Every headline number is a **function of the modelling choices**, so it is
quoted with the policy, resolution and assumption it was measured under. Quote
the conditional value — never a group's spread as if it were one number.

| Result | Under this assumption | Value |
|---|---|---|
| Momentum entries the exchange would not fill, **next tradeable session** | lag 1 (honest, no look-ahead) | **5.84%** (11,543 / 197,521) |
| — same, tested on the *signal* session | lag 0 (embeds look-ahead) | 12.90% |
| Fill-policy **disagreement** over realistic order flow | 385 tickers × 5 intents, 2022; 477,537 questions | **31.6% of decisions** disagree |
| Executed shares, `soft` vs `hard` fill | same flow, all intents | **245.8M vs 128.5M (1.91×)** |
| Derivatives margin, **dated regime** | same 381-position book, pre- vs post-KRX | **+30.0%** (17.69M → 23.00Mđ) |
| Margin-call incidence | 10-session hold, funding 1.42× | **11.55%** [8.72, 15.15] |
| Maker fill, **queue swing** | optimistic vs conservative | 152,600 vs 123,700 shares (**−18.9%**) |
| Tick-grid conformity | library rule vs naive 0.1 grid | **99.999%** vs 84.51% |
| Band agreement | engine `reconstruct_bands` vs vendor band | **97.59%** (4,324 / 179,784 disagree) |

Reproduce all of them:

```bash
python reproduce_measurements.py --data-root /path/to/dataset
```

The full, CI-annotated table — every row with its fill policy, resolution and
assumption set — is
[`docs/reference/tables/t4_measured_results.md`](docs/reference/tables/t4_measured_results.md).
Confidence intervals bound *sampling* noise only; the regime-split and
maker-fill swings are the *assumption*-error axis, and they dwarf the intervals.

---

## Validation: scenarios and strategies

The rules are pinned two ways, TDD-style, on the public API a user actually
touches:

- **Scenarios (Jx)** — 38 scenarios that each drive one mechanism through the
  session and assert the exchange's response (round-lot change, floor-lock exit,
  MOK vs MAK, margin layers, fill-policy spread, the book walk, …).
- **Strategies (Sx)** — 14 end-to-end strategies where each stress moment
  *emerges* from P&L against real corpus data, with two checks a single rule
  poke cannot give: **emergence** (the margin call lands on the day the loss
  actually breached) and **conservation** (every đồng reconciles).

```bash
pytest scenarios/    # 38 — the Jx acceptance suite
pytest strategies/   # 14 — the Sx end-to-end suite
pytest tests/market  # 1,646 — the library unit + property suite
```

*(Run `scenarios/` and `strategies/` in separate invocations — both define a
top-level `_harness`.)*

---

## Reference artifacts (for citation)

The sourced rule material is gathered as standalone, dated documents so a paper
or audit can cite one folder — [`docs/reference/citable/`](docs/reference/citable/):

| Work | File |
|---|---|
| Vietnamese Exchange Rulebook 2020–2026 | `vn-exchange-rulebook-2020-2026.md` |
| Broker Derivatives-Margin Policy Survey | `BROKER-POLICY-SURVEY.md` |
| Scenario Reference (Jx) | `SCENARIO-REFERENCE.md` |
| Strategy Reference (Sx) | `STRATEGY-REFERENCE.md` |

Plain and BibTeX citations are in
[`docs/reference/citable/CITATIONS.md`](docs/reference/citable/CITATIONS.md).
Every policy fact carries provenance — a citation and confidence grade, or an
explicit *unsourced* marker. The combined model spans the exchanges (HSX/HNX/
UPCoM), the VSDC depository and 14 surveyed brokers.

Broader development record: [`docs/reference/PAPER-COMPENDIUM.md`](docs/reference/PAPER-COMPENDIUM.md)
(the narrative + the map) and [`docs/reference/PAPER-HANDOFF.md`](docs/reference/PAPER-HANDOFF.md)
(the two-page launchpad).

---

## Bring your own data

The simulator consumes any object implementing the narrow
`plutus.market.adapters.base.MarketDataSource` protocol — a handful of questions
about a ticker at an instant. `DataHubSource` is the corpus-backed
implementation; point the session at your own bars or book and the same dated
rules apply. **Plutus does not claim a dataset** — it claims the rules.

---

## Data access (the substrate)

The bundled market-data layer that feeds the simulator, and stands alone for
analytics. It offers three interfaces over the **hermes-offline-market-data-pre-2023**
corpus: daily bars **2000-07-28 → 2022-12-30** (2,511,874 rows, 1,725 tickers)
and tick data **2020-12 → 2022-12** (41.3M matched trades, plus a 3-level price
book from 2021-01-15; bid/ask *sizes* are not populated in this release).

📧 **Contact [ALGOTRADE](https://algotrade.vn) for dataset access.**

### DataHub — Python API & CLI

```python
from plutus.datahub import query_historical

ohlc = query_historical(ticker_symbol='FPT', begin='2021-01-15', end='2021-01-16',
                        type='ohlc', interval='5m')
for bar in ohlc:
    print(bar['bar_time'], bar['open'], bar['high'], bar['low'], bar['close'])
```

```bash
python -m plutus.datahub --ticker FPT --begin 2021-01-15 --end 2021-01-16 \
  --type ohlc --interval 5m --output fpt.csv
```

40+ fields, 7 OHLC intervals (1m…1d), lazy iteration, `to_dataframe()`.
📖 [CLI Guide](src/plutus/datahub/docs/CLI_USAGE_GUIDE.md) ·
[Python examples](examples/)

### MCP server — natural-language access

Query the corpus in plain language from Claude Desktop, Claude Code or Gemini
CLI. 4 tools, 4 resources, 5 prompts.

```bash
python -m plutus.mcp
```

📖 [Quick Start](src/plutus/mcp/docs/MCP_QUICKSTART.md) ·
[Client Setup](src/plutus/mcp/docs/MCP_CLIENT_SETUP.md) ·
[Tools Reference](src/plutus/mcp/docs/MCP_TOOLS_REFERENCE.md)

### Corpus audit — defects as data

Real market data carries defects; Plutus characterizes them rather than leaving
each analysis to rediscover them. Ten checks, each with its measured incidence:

```bash
python -m plutus.data.audit --data-root /path/to/dataset --json report.json
```

Queries apply the two row-level exclusions (pre-exchange, weekend) by default via
`strict=True`; the inverted price bands (1,272 rows on 3 days) are exposed as
data because OHLC queries do not join the band tables.

### Performance — optional Parquet

```bash
python -m plutus.datahub.cli_optimize optimize --data-root /path/to/dataset
```

**10–30×** on queries that read data; **81.8% smaller** on disk (912 MB → 166 MB
across the 29 shared tables). 📖 [Performance Guide](src/plutus/datahub/docs/DATA_OPTIMIZATION_GUIDE.md)

---

## Requirements

- **Python** 3.12+
- **Dataset** (optional, for corpus-backed runs): hermes-offline-market-data-pre-2023
  (21 GB raw CSV) — or any `MarketDataSource` of your own
- **Dependencies**: DuckDB, PyArrow, FastMCP, … (installed via pip; see `pyproject.toml`)

A daily-bars-only deployment works: the session validates each table at query
time, so an absent tick archive only affects tick-resolution runs.

---

## Project status

- **Version**: `plutus.__version__` (single source: `pyproject.toml`)
- **Tests**: market 1,646 · datahub 89 · scenarios 38 · strategies 14 — all passing ✅
- **Exchange session** (`plutus.market`): the current line of work — dated
  rulebook, T+2 settlement, derivatives margin, broker API, fill/queue policies
- **Data access** (DataHub · MCP · audit · Parquet): stable

---

## Contributing

A research project. Questions and collaboration welcome:
- **GitHub Issues**: https://github.com/algotradevn/plutus/issues
- **Email**: andan@algotrade.vn

## License

MIT — see [LICENSE](LICENSE).

## Author

**Dan** (andan@algotrade.vn) · [ALGOTRADE](https://algotrade.vn) — Algorithmic
Trading Education & Research.

## Acknowledgments

Built on the [ALGOTRADE 9-step methodology](https://hub.algotrade.vn/knowledge-hub/steps-to-develop-a-trading-algorithm/)
for systematic algorithmic trading development.
