# Implementation handoff — Plutus library, RIVF'26 ecosystem paper

> **⚠️ DEPRECATED / SUPERSEDED — kept for history only.** This is the original
> 15 Aug 2026 work order; it has been overtaken by the exchange fill model, the
> simulator, and everything since. Several of its load-bearing claims failed
> later verification (see the `handoff-doc-corrections` memory). **For the current
> state, start at `docs/reference/PAPER-HANDOFF.md`** (launchpad) →
> `docs/reference/PAPER-COMPENDIUM.md` (full record). Do not treat anything below
> as current.

**Written 15 Aug 2026.** Audience: the Claude Code session (and the user) doing the
actual development. This document is the work order. It assumes no memory of the
sessions that produced `DIRECTION.md`, `IMPROVEMENTS.md`, `ROADMAP_HAH.md`, or
`SCAN-2026-08-15.md`, and it re-verifies its own load-bearing facts against the
code and the corpus on this machine.

**What this is:** the direction in `DIRECTION.md` turned into sequenced,
individually-acceptable work packages with file:line anchors, verified SQL,
acceptance criteria, and a mapping from each package to the paper claim it
supports.

**What this is not:** a rationale document. The *why* lives in `DIRECTION.md` §0
(framing), `ROADMAP_HAH.md` (module recipe + restraint), and `SCAN-2026-08-15.md`
(venue + ICAIF relationship). Read `DIRECTION.md` §0 once before starting; it is
the thesis every package below serves.

---

## 0. Ground rules

**The thesis the code must support.** Backtests of Vietnamese equities are
systematically optimistic because the market's microstructure — hard daily
price-limit bands, price-dependent tick grids, round lots, foreign-ownership caps
— is absent from general-purpose backtesting libraries and from the flat OHLCV
feeds they consume. We quantify how often these constraints bind, and ship a data
layer that makes them first-class.

Every package is judged on: **does it make that claim more defensible, or is it
just tidying?** Both are allowed, but the first gets priority when time runs short.

**Four rules, held throughout.**

1. **Claim only what the artifact does.** The paper is the named, IEEE
   Xplore-indexed, permanent record. Every number in it must come from a script
   that can be re-run. If a package slips, the paper's claim slips with it —
   never the reverse.
2. **No engine.** `core/bot.py` is a non-importable stub and the ICAIF paper now
   owns the engine-independence story empirically (three engines, five
   pipelines). Do not build, fix, or claim a backtester. Plutus contributes a
   *market-faithful data and instrument layer*; execution comes from elsewhere.
3. **Repo is read-only here.** `/Users/nadan/algotrade-research/plutus` is mounted
   **ro**. Development needs a writable checkout — the user's own clone. Nothing
   in this handoff should be attempted against the ro mount.
4. **Naming is unresolved and it touches public API.** The ICAIF artifacts were
   de-branded (`plutus check` → `artifact check`, `plutus-verify` →
   `artifact-verify`), while `plutus-guideline` still says `plutus check`. See
   `SCAN-2026-08-15.md` §2.2. **This does not block any package below** — none of
   them name the verifier — but do not add new cross-references to the verifier
   CLI until the user decides. Noted so we don't drift.

**Deferred, deliberately** (from `SCAN-2026-08-15.md`, per the user): the three
consistency findings — the mixed ICAIF/official artifact naming, the false
"data layer makes the templates reproducible" claim, and the superseded arXiv
argument. They are documentation-level and consolidatable later. Kept visible
here only so no package silently depends on them.

---

## 1. Environment — do this first

```bash
# 1. Work in a WRITABLE clone. The granted mount is read-only.
#    (the ro mount is at /Users/nadan/algotrade-research/plutus)
cd <writable-plutus-clone>

# 2. Data root on THIS machine (moved since SESSION_CONTEXT.md was written):
export PLUTUS_DATA_ROOT=/Users/nadan/algotrade-research/dataset/hermes-parquet
#    35 parquet tables, 555 MB.  CSV twin: .../dataset/hermes-csv, 870 MB.

# 3. Deps not in the base image:
pip install duckdb pytest fastmcp pydantic

# 4. Baseline the suite BEFORE touching anything:
PYTHONPATH=src pytest -q            # expect 251 collected / 250 passed
```

The single known failure, `tests/datahub/test_ohlc_query.py::test_init_without_config`,
is a read-only-mount artifact (the test renames `config.cfg`). On a writable
clone expect **251/251**. If you see 250/251 on a writable clone, that is a real
regression — investigate before proceeding.

`reproduce_measurements.py` in this repo regenerates the paper's measurements, but
its `DEFAULT_ROOT` is stale: **always pass `--data-root`**.

```bash
python reproduce_measurements.py --data-root $PLUTUS_DATA_ROOT
```

---

## 2. Corpus facts verified on this machine, 15 Aug

Re-derived directly, not copied from the earlier docs. These are the facts the
packages below depend on.

**Table schemas differ in time granularity — this is the key structural fact.**

| Table | `datetime` type | Span | Rows | Tickers |
|---|---|---|---|---|
| `quote_open` | **DATE** | 1789-05-01 → 2022-12-30 | 3,935,663 | 2,313 |
| `quote_close` | **DATE** | 1789-05-01 → 2022-12-30 | 3,899,486 | 1,988 |
| `quote_max` | **DATE** | 1789-05-01 → 2022-12-30 | 3,877,983 | 1,767 |
| `quote_min` | **DATE** | 1789-05-01 → 2022-12-30 | 3,877,981 | 1,767 |
| `quote_high` | **TIMESTAMP** (intraday) | 2021-01-15 → 2022-12-30 | 2,115,691 | 2,218 |
| `quote_low` | **TIMESTAMP** (intraday) | 2021-01-15 → 2022-12-30 | 2,175,593 | 2,218 |
| `quote_dailyvolume` | DATE | 2000-07-28 → 2022-12-30 | 2,562,664 | 2,273 |
| `quote_ceil` / `quote_floor` | DATE | — | — | — |

**`quote_max`/`quote_min` ARE session high/low — the `IMPROVEMENTS.md` §2 caveat is
now resolved.** Two tests settle it:

- *Not* running historical extremes: `quote_max` decreases day-over-day on
  **1,117,688 of 3,876,216** consecutive pairs. A running max never decreases.
- Consistent with same-day close: `high < close` on only **326** rows and
  `low > close` on **99** of 3,877,981 (0.008% / 0.003%).
- Cross-validated against the intraday tables: aggregating `quote_high` to a daily
  max and joining on date gives **481,020 of 481,891 exact matches (99.82%)**.

So: **`quote_max`/`quote_min` are the correct daily high/low source and cover
23 years**, while `quote_high`/`quote_low` are intraday ticks covering 2021+ only.
Naming them `high`/`low` in a public daily API is defensible. The earlier plan to
"derive high/low from `quote_high`/`quote_low` where available" is **unnecessary
and would silently shorten coverage to 2021+** — do not do it.

**The daily OHLCV join unlocks 2000-07-28 → 2022-12-30: 2,520,463 rows,
1,898 tickers.** That is the "23 years" claim, verified.

**Inverted price bands reproduce exactly:** 1,272 rows across 3 days where
`quote_ceil < quote_floor`. Must be filtered in every band-dependent query.

**Headline blocked-fill rate reproduces:** filtering inverted bands, momentum
entries (close > previous close) landing on a locked ceiling = **12.93%** on
n=210,030 across all instruments. The documented **12.96%** on n=191,454 is the
stocks-only figure (restricted via the ticker master + exchange join). The two are
consistent; the small gap is the instrument filter, not a discrepancy. **The paper
should quote the stocks-only 12.96% and state the filter** — and the audit module
(WP4) is what makes that filter reproducible rather than ad hoc.

**New defect found today, not in any prior doc:** the 326 `high < close` and 99
`low > close` rows are an **OHLC-invariant violation** independent of the
ceiling/floor swap. Add `high >= max(open, close)` and `low <= min(open, close)`
to the audit module's check set (WP4). Cheap, and it is a second independent
demonstration that the audit finds real things.

---

## 3. Code anchors — verified file:line

Every anchor below was read on this machine at `plutus` @ `042acd7`, version
`0.2.5.202510rc`, 63 py files / 13,272 LOC.

**The domain knowledge already exists and is unused by the query layer.** This is
the most important thing to understand before starting: `core/constant.py` encodes
the market correctly, and nothing in `datahub/` reads it.

| What | Where | State |
|---|---|---|
| `VietnamMarketConstant` | `core/constant.py:13` | correct |
| `TRADING_UNIT` = HSX/HNX/UPCOM 100, DS 1 | `core/constant.py:36` | correct, unused by datahub |
| `DAILY_TRADING_LIMIT` = HSX .07, HNX .1, UPCOM .15, DS .07 | `core/constant.py:39` | correct — matches measured half-bands (.0694/.0980/.1480) |
| `TICK_SIZE` incl. HSX bands (0,10]=.01, (10,50]=.05, (50,∞)=.1 | `core/constant.py:43` | correct |
| `get_hsx_tick_size()` — incl. 8-char C/E/F warrant-ETF rule → .01 | `core/constant.py:261` | correct; yields **100.00%** grid conformity vs 91.62% naive |
| `AbstractTradingSession.is_current()` | `core/constant.py:72` | correct |
| ATO/LO/ATC/PLO per exchange, real times | `core/constant.py:144-200` | correct, unused |
| `Exchange` objects HSX/HNX/UPCOM/DS | `core/constant.py:289,328,367,398` | correct |

Defect sites:

| # | Defect | Anchor |
|---|---|---|
| P0-1 | `_validate_dataset()` hard-requires `quote_matched` | `datahub/config.py:236`, critical list at `:246` |
| P0-2 | `1d` built from ticks; no daily path exists | `datahub/ohlc_query.py:139-189` (SQL builder at `:130-190`) |
| P0-3 | non-relative imports | `core/bot.py:3-5` (`from algorithm import Algorithm`) |
| P0-4 | `all = ["plutus[mcp,dev]"]` → unrelated PyPI pkg | `pyproject.toml:52` |
| P1-6 | `annualization_factor: int = 252` default | `evaluation/metrics/returns.py:15,66,117,206,259`; `evaluation/performance.py:83` |
| P1-7 | unparameterized ticker in SQL (5 sites) | `ohlc_query.py:157,184`; `tick_query.py:155,252,269` |
| P1-8 | no `__version__`/`__all__` | `src/plutus/__init__.py` is **0 bytes** |
| P1-8 | version disagreement | `pyproject.toml:7` `0.2.5.202510rc`; `docs/conf.py:19-20` `0.2.5`/`0.2.5.20251022`; `README.md:320` `1.0.0` |
| P1-9 | stale test badge | `README.md:7,22,321` say 205; actual 251/250 |
| P2-12 | no CI, no `py.typed` | **no `.github/`** at all; no `py.typed` anywhere |
| P2-12 | wheel ships dev artifacts | `pyproject.toml:73-74` packages `src/plutus` wholesale, including `experiment/` (13 files) |

Test layout: 16 `test_*.py` under `tests/{datahub,test_evaluation,test_mcp,data}`.
**`core/` and `experiment/` have zero tests** — which is exactly where the new
modules land, so WP3+ must ship their own.

---

## 4. Work packages

Sequenced so each is independently landable, independently testable, and leaves
the library working. **WP1–WP4 are the paper's critical path.** WP5+ is upside.

Effort is in ideal focused days. Every package lists acceptance criteria that are
mechanically checkable — these are the definition of done, not suggestions.

### WP1 — Make the library run on the shipped dataset (P0) · ~1 day

Right now **every documented entry point fails** on a Parquet deployment without
the tick archive: the README 5m example, the README daily example, and the CLI all
raise `FileNotFoundError: quote_matched` — including the 23 years of daily data
that *are* present. Nothing else can be demonstrated until this is fixed.

**1a. Per-field validation, not eager global validation.**
`datahub/config.py:236` requires `quote_matched` before any query runs.
Downgrade the critical set to `quote_ticker` only; validate per-field at query
time (`get_file_path` already resolves per field). When a field is genuinely
missing, raise an error naming **both the field and the query that needed it**.

**1b. A real daily-bar path.** `ohlc_query.py` must read the daily tables for
`1d` instead of re-aggregating ticks. Verified SQL — returns 18 correct FPT bars
for 2021-01-15 → 2021-02-15, and note `?` binding (this also fixes P1-7 at these
sites):

```sql
SELECT o.datetime AS bar_time, o.tickersymbol,
       o.price AS open, h.price AS high, l.price AS low,
       c.price AS close, v.quantity AS volume
FROM read_parquet('{root}/quote_open.parquet')        o
JOIN read_parquet('{root}/quote_max.parquet')         h USING (datetime, tickersymbol)
JOIN read_parquet('{root}/quote_min.parquet')         l USING (datetime, tickersymbol)
JOIN read_parquet('{root}/quote_close.parquet')       c USING (datetime, tickersymbol)
JOIN read_parquet('{root}/quote_dailyvolume.parquet') v USING (datetime, tickersymbol)
WHERE o.tickersymbol = ? AND o.datetime >= ? AND o.datetime < ?
ORDER BY bar_time
```

Use `quote_max`/`quote_min` for high/low — semantics verified in §2, 23-year
coverage. Do **not** route through `quote_high`/`quote_low` (intraday, 2021+ only).
`datetime` is `DATE` in all five tables, so bind dates, not timestamps.

**1c. Fix the `all` extra.** `pyproject.toml:52` →
`all = ["algotrade-plutus[mcp,dev]"]`. Live defect in the published rc: today
`pip install algotrade-plutus[all]` installs an unrelated `plutus` package from
PyPI and neither fastmcp nor pytest.

**1d. Decide `core/bot.py`** — user's call, two options: (i) fix the three
non-relative imports, mark the module explicitly experimental, keep it out of the
public API surface; or (ii) exclude it from the wheel until it works. Rule 2 says
either way we do not claim a backtester.

**Acceptance.**
- README headline (5m) and daily examples both run against `$PLUTUS_DATA_ROOT`, or
  fail with an error naming the missing field and the query.
- `python -m plutus.datahub` daily query returns bars.
- `get_ohlc(ticker='FPT', interval='1d', ...)` returns **18** rows for
  2021-01-15 → 2021-02-15, matching the table in §2 to the cent.
- A daily query spanning 2005 returns data (proves the 23 years, not just 2021+).
- Parametrized-query test: a ticker containing `'` does not break the SQL.
- 251/251 tests still pass.

### WP2 — Claim integrity (P1) · ~1 day

The paper's credibility rests on these. Do them **before drafting**, so the paper
quotes true figures the first time.

**2a. One metric convention for undefined values.** On a constant +0.5%/day series
the library currently reports `sharpe=0`, `sortino=Infinity`, `calmar=Infinity` —
three mutually contradictory verdicts on one input. Worse, **`Infinity` is not
valid JSON** (RFC 8259), so any strict re-parse of a results file fails. I checked
the verifier: it rejects a `percent` unit (`artifact_verify/sdk/run.py:125`) but
has **no non-finite guard**, so this is a live threat to the results contract, not
a theoretical one.

Adopt `None` for undefined, never `±inf`, uniformly across all 22 metrics. Also:
`[]` (no trades) currently returns `0.0` everywhere — indistinguishable from a
strategy that traded and broke even; return `None` or raise. Returns below −100%
raise raw `decimal.InvalidOperation` from `calmar`/`cagr` — convert to a domain
error. Ship an edge-case test matrix: empty, single point, constant, zero-vol,
all-negative, < −100%.

*The 22 metrics are otherwise numerically correct* — verified against independent
NumPy references (Sharpe 0.179537 both ways, max-DD −0.258121 both, ann-vol
0.188440 both). VaR/CVaR differ only in interpolation and tail-boundary choice.
This package is about edge cases and the contract, not about fixing arithmetic.

**2b. 250-day default.** The measured Vietnamese calendar is **median 250 trading
days/year** (2010–2022, range 247–252). 252 is the NYSE convention and overstates
every annualized metric by ~0.40%. Add
`VietnamMarketConstant.TRADING_DAYS_PER_YEAR = 250`, make it the default at the
six sites listed in §3, keep the parameter overridable, and document the
measurement. In a paper claiming domain fidelity, shipping the NYSE constant is
precisely the detail the argument turns on.

While here, document the other defaults: `risk_free_return` 3% vs the ICAIF Smart
Beta's 6%, `minimal_acceptable_return` 7%. Undocumented mismatched defaults
produce metrics that silently differ from published ones.

**2c. Single version source.** `pyproject.toml` is truth; derive via
`importlib.metadata.version`; expose `plutus.__version__` and `__all__` in the
currently-empty `src/plutus/__init__.py`; fix `docs/conf.py` and the README.

**2d. Correct every documented number.** README/docstrings currently claim: 21GB
(actual 555 MB parquet + 870 MB CSV — **open question, see §6**), 205 tests
(actual 251/250 — the badge *undersells*), 10–100× (honest: 9.4× full scan, 28.5×
filter, 13.3× group-by; the 111–213× figures come from queries Parquet answers
from footer statistics without reading data — keep that caveat), 60% smaller
(actual 81.8%). Mark order-book fields **unavailable** in the MCP surface: the
tool docstring advertises `bid_price_1..10`/`ask_size_1..10` but
`quote_asksize`/`bidsize`/`totalask`/`totalbid` are 0 rows and
`quote_bidprice`/`askprice` are absent — an LLM reading `get_available_fields()`
will confidently request unservable fields. Drive availability from the metadata
cache.

**Acceptance.** No metric returns `±inf` on any edge case in the matrix;
`json.loads(json.dumps(results))` round-trips for every one. `import plutus;
plutus.__version__` works and matches `pyproject.toml`. Every number in
README/docstrings traces to a line in `reproduce_measurements.py`. `grep -r 21GB`
returns nothing unresolved.

### WP3 — `VietnamFillModel` + rejected-order logging · ~2 days · **core contribution**

The library-side counterpart to the paper's empirical result, and the thing no
competitor has. `constant.py` already holds all the rules correctly (§3) — this is
mostly wiring plus a clean verdict API.

```python
class VietnamFillModel:
    def can_fill(self, side, price, ceiling, floor, volume, *,
                 ticker=None, session=None, foreign_room=None) -> FillVerdict
```

Enforces, in order: (a) no buy at/above a locked ceiling; (b) no sell at/below a
locked floor; (c) price on the HSX price-dependent tick grid via
`get_hsx_tick_size` (`constant.py:261`); (d) size on the 100-share round lot
(1 for derivatives) via `TRADING_UNIT`; (e) foreign-room check when the buyer is
flagged foreign; (f) session awareness — ATO/ATC are **call auctions**, not
continuous trading, so a market order at 09:05 participates in price formation
rather than crossing a book.

`FillVerdict` must be a structured object, not a bool: `(allowed, rule_violated,
binding_constraint, timestamp, regime_tag)`. **This is the rejected-order logging**
— every rejection records rule, timestamp, and regime. Per `ROADMAP_HAH.md`, it is
also the substrate the HAH agenda needs later, and it is useful for ordinary
backtesting regardless. One clause in the paper, no HAH claim.

Justifying measurements, in hand: **12.96%** of naive momentum entries and
**8.25%** of stop-loss exits are structurally unfillable; **100.00%** grid
conformity under the library's rule vs **91.62%** naive; **16.54%** of
foreign-room ticker-days are exhausted.

**Acceptance.** Unit tests for each of (a)–(f), including the 8-char C/E/F
warrant-ETF tick exception. A property test: every price the model accepts for
HSX lies on the legal grid. Replaying the momentum rule through the model rejects
a share of entries matching the measured 12.96% (stocks-only, inverted bands
filtered) within tolerance — **this is the test that ties the code to the paper's
headline number.** Rejections are machine-readable.

### WP4 — `plutus.data.audit` + `strict=True` query mode · ~1.5 days · **contribution #3**

Framed as *documented dataset characterization with a machine-checkable audit*
this is a research artifact; framed as "known issues" it is a bug list. Frame it
the first way — and it is what makes the paper's own filters reproducible instead
of ad hoc.

Checks to ship, all measured and reproducible:

| Check | Measured incidence |
|---|---|
| `ceiling > floor` invariant | **1,272 rows / 3 days** (2021-02-08, 02-09, and 1,265 of 1,790 rows on 02-17) — corpus-wide 0.155% |
| **OHLC invariants** `high >= max(o,c)`, `low <= min(o,c)` | **326** high<close, **99** low>close — *found today, new* |
| non-VN contamination | **33,066 pre-2000 `SPX` rows** (S&P 500, back to 1789) inside tables billed as Vietnamese |
| non-session timestamps | **3,526** Saturday/Sunday rows in `quote_close` |
| orphan symbols | **87 of 1,988** absent from `quote_ticker` master, incl. futures `VN30F2112`, `VN30F2306` |
| empty tables | 4 (`asksize`, `bidsize`, `totalask`, `totalbid`) |
| ragged coverage | 17 of 30 tables start only in 2021 |
| VN30 survivorship | 12 snapshots × 30 members, **53 distinct tickers** ever a member |

Emit a machine-readable report. Add `strict=True` (**default on** for new APIs)
filtering non-VN symbols, non-session timestamps, and inverted bands.

The ceiling/floor swap made 2021-02-17 appear to have simultaneous 80% limit-up
and 76% limit-down. Headline results re-run with those rows excluded are
**unchanged to two decimals** — the finding is robust, but the filter must be
applied and disclosed.

**Acceptance.** `python -m plutus.data.audit --data-root $PLUTUS_DATA_ROOT`
reproduces every count above exactly. `strict=True` excludes the inverted-band
rows. A regression test asserts the 12.96%/8.25% headline figures under the strict
path, so the paper's numbers are defended by CI.

### WP5 — `SurvivorshipCorrectUniverse` + Sharpe-gap experiment · ~1 day · standalone result

Cheapest module, largest silent error. `universe_asof(date)` from the 12 `quote_vn30`
snapshots (~40 lines); make the *incorrect* path require an explicit opt-in flag.

Then run the experiment: same factor screen on (a) today's 30 names
back-projected vs (b) point-in-time membership, and report the Sharpe gap. **That
number is a publishable result on its own** and costs one afternoon. It was
offered but never approved — worth doing if WP1–WP4 land on time.

### WP6 — regime labels as a first-class query column · ~0.5 day

Already built and validated: VNINDEX realized-vol terciles, 2015–2022 (1,997
days), calm/normal/stressed. Expose as a query-result column. Enables Fig. 2, and
per `ROADMAP_HAH.md` seeds the later agenda at near-zero cost. Supporting
measurement: limit-down pressure **1.13% calm → 2.74% stressed = 2.4×**,
Mann–Whitney p = 3.74e-09, Spearman ρ = +0.308 vs 21-day realized vol.

### WP7 — CI and hygiene · ~1 day · do early, protects everything

A paper about mechanical verification whose library has **no CI at all** (no
`.github/`, no pre-commit, no linter config) is an easy reviewer jab. Add a
workflow running the suite on 3.12/3.13. Add `py.typed` (one empty file — the
annotations are already thorough, downstream users just get nothing today).
Exclude `experiment/` (13 dev files, incl. `slots_visual_demo.py`) from the wheel.
Deprecate or document the two parallel data stacks (legacy `data/` needing
redis/ujson vs current `datahub/`; only `data/model/` is used by the modern path).
Pin a `test` extra with `pytest-cov`.

**Do WP7's CI step first if there is any chance of it slipping** — it protects
WP1–WP4 from regression, and it is the cheapest reviewer-jab removal available.

### Upside, only if WP1–WP6 land (see `ROADMAP_HAH.md` Part A for full rationale)

`VietnamCostModel` (~0.5d; 0.1% sale tax, brokerage 0.15–0.35% — the ICAIF Smart
Beta's 0.035%/trade is institutional and low for retail) · `ForeignRoomModel`
(~1d; most differentiated vs `vnstock`, but disclose the 83-day coverage window
honestly) · `PriceLimitAwareRisk` (~1–2d; drawdown conditional on exit
feasibility — best novelty-per-day, and the A→B bridge) · `plutus.conformance`
harness (~2d; the strategic reframe from "another VN library" to "the reference
implementation of VN market fidelity" — a comparison we define rather than lose).

---

## 5. Sequencing and division of labour

```
WP7-CI ──┐
WP1 ─────┼──> WP2 ──┐
         │          ├──> WP3 (fill model) ──┐
WP4 ─────┴──────────┘                       ├──> paper draft
                     WP6 ──────────────────┘
                     WP5 (optional, parallel)
```

WP1 and WP4 are independent and can go in parallel. WP3 depends on WP1 (needs a
working daily path to replay the momentum rule) and reads WP4's strict filters.
WP2 is independent of everything but must precede drafting.

**Suggested split.** The Claude Code session is well suited to WP1, WP2, WP4, WP7
— they are mechanical, heavily test-covered, and every acceptance criterion above
is machine-checkable. WP3 and WP5 involve API design judgment (what `FillVerdict`
carries, how strict the default is, whether the incorrect universe path is
reachable at all) and benefit from the user in the loop. WP6 is trivial either way.

**Minimum viable paper: WP1 + WP2 + WP3 + WP4.** That yields a working library, a
defensible claim set, the fill model as the core contribution, and the audit as
contribution #3. WP5–WP7 strengthen it; the upside list is genuinely optional and
each item is independently publishable later as an extension.

---

## 6. Decisions needed from the user

Blocking or near-blocking, in rough priority:

1. **Is the full tick archive reachable?** `quote_matched`,
   `quote_matchedvolume`, `quote_bidprice`, `quote_askprice`, `quote_total`,
   `quote_change`, `quote_foreignroom` are declared in
   `DataHubConfig.FIELD_MAPPINGS` (`config.py:40`) and present in **neither**
   local format. This caps the paper: no spread, order-book, or trade-level
   microstructure claim is evidenceable from this machine. Everything in §2 comes
   from daily bars + limit tables + foreign flows, which *are* present. If the
   archive is unreachable, scope to daily+limit data and say so explicitly.
2. **Is "21GB" real or stale?** One number, used in the README and the
   `datahub/__init__` docstring. Local corpus is 555 MB parquet + 870 MB CSV.
   WP2d cannot close without an answer.
3. **`core/bot.py`: fix imports and mark experimental, or drop from the wheel?**
   (WP1d.)
4. **Run the survivorship Sharpe-gap experiment?** (WP5.) One afternoon, produces
   a standalone publishable number. Offered previously, never approved.
5. **RIVF logistics** — deadline, blind-vs-named, EDAS all unconfirmed; the
   "31 Aug" date in the older docs is **not** on the CFP page retrieved. If the
   deadline really is 31 Aug, that is ~2 weeks out and only WP1–WP4 fit. Vendor
   the RIVF CFP into the repo the way `plutus-paper/policy/` holds ICAIF's.
6. **Public naming** (`plutus check` vs `artifact check`) — see §0 rule 4. Does
   not block WP1–WP7.

---

## 7. Paper-claim ↔ package map

The check before drafting: every claim traces to a package and a measurement.

| Paper claim | Package | Evidence |
|---|---|---|
| Market-faithful schema for a limit-band frontier market | WP3, WP1 | `constant.py` rules wired into the query layer; 100.00% vs 91.62% grid conformity |
| Quantified optimism bias (**the empirical core**) | WP3 | 12.96% entries / 8.25% exits unfillable; 16.54% foreign-room-exhausted ticker-days |
| Reusable data-quality audit | WP4 | 8 checks, all counts reproducible; 2 defect classes found by this work |
| Zero-setup architecture, honest performance envelope (~0.75 pp) | WP1, WP2d | 9.4× / 28.5× / 13.3×, 81.8% storage, footer-statistics caveat stated |
| 23 years of daily coverage | WP1b | 2000-07-28 → 2022-12-30, 2,520,463 rows, 1,898 tickers |
| Constraint is regime-dependent (Fig. 2; one measurement, stated as such) | WP6 | 2.4×, p=3.74e-09, ρ=+0.308 |
| Survivorship correctness | WP5 | 53 distinct VN30 members vs 12×30 snapshots; Sharpe gap if run |
| Rules generalize beyond Vietnam (one sentence) | WP3 | limit bands / lots / ownership caps recur in KR, TW, TH, CN A-shares — the *contract* generalizes, the constants do not |

**Claims to avoid, restated:** no working backtester (Rule 2); no HAH in title or
abstract and no human-factors claim (`ROADMAP_HAH.md` Part B — one motivation
sentence, one ~120-word Future Work paragraph, nothing more); no "the data layer
makes the ICAIF templates reproducible" (they commit their data in-repo and import
nothing from Plutus — `SCAN-2026-08-15.md` §2.3); no order-book depth claim
(tables are empty).
