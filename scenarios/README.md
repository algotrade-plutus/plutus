# Scenario acceptance suite

These are the catalogue scenarios (`docs/reference/SCENARIO-CATALOGUE.md`) as **runnable,
reproducible code** — each written the way a `pip install`'d user writes a strategy: public
API only, Plutus as the counterparty across the table. Each scenario is both a **demo** (this
is what using the library looks like) and an **acceptance test** (the simulator behaves the
way the Vietnamese market does).

The board of all 27 with their status and build order is `docs/reference/SCENARIO-BOARD.md`.

## Two tiers of pass

- **Tier 1 — "it runs":** no crash; every order returns a real answer (filled OR
  rejected-with-a-reason), never an unwarranted INDETERMINATE where a real market would
  answer; the story completes.
- **Tier 2 — "it's right":** the outcome matches the scenario's stated intention, **and that
  intention is the documented Vietnamese rule** — the catalogue's citations are the oracle.
  Checked on user-observable outputs where possible; on internals via a privileged evaluator
  only where the user genuinely cannot see it.

The loop we drive each scenario through: *run it → Tier 1 red? fix the plumbing → Tier 1
green, report → Tier 2 red? fix the fidelity → Tier 2 green, banked.* **On failure we fix the
simulator, never the scenario.**

## Running

The suite runs against the market-data corpus. Point `PLUTUS_DATA_ROOT` at a directory of
`quote_*.parquet` files (it defaults to the corpus on the author's machine, so it runs here
out of the box):

```bash
# one-time: a venv with the package installed editable + test deps
python3.12 -m venv .venv
.venv/bin/pip install -e ".[test]"

# run every scenario
.venv/bin/python -m pytest scenarios/ -v

# run one
.venv/bin/python -m pytest scenarios/test_j1_settlement.py -v

# run one as a plain program (prints a readable report, no pytest)
.venv/bin/python scenarios/test_j1_settlement.py

# point at a different corpus
PLUTUS_DATA_ROOT=/path/to/corpus .venv/bin/python -m pytest scenarios/ -v
```

Scenarios skip cleanly (not fail) when no corpus is present.

## Adding a scenario

One file per scenario, `test_j<n>_<slug>.py`, with:

1. A module docstring: the **mechanism**, the **policy citations** (copied from the
   catalogue — the oracle), the **expected Tier-2 outcome**, and how to run it.
2. The **config a user would write**, inline as a dict (the harness fills `data.root` from
   `PLUTUS_DATA_ROOT`).
3. A `run_j<n>()` that is the user's program — public API only — returning the outputs a user
   reads off it. Where you are forced past the public surface, that is a finding: fix the
   surface, don't reach in.
4. A `test_j<n>_...()` that asserts Tier 2 on those outputs, `skipif` no corpus.
5. A `__main__` block that runs it and prints a readable report.

Shared plumbing (corpus discovery, `build_session`) lives in `_harness.py`. Keep the
scenario body reading like user code.
