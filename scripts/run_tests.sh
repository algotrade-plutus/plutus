#!/usr/bin/env bash
# Run the whole test suite.
#
# The three suites are collected in SEPARATE pytest invocations on purpose.
# `tests/` are unit/integration tests; `scenarios/` (the Jx acceptance
# catalogue) and `strategies/` (the Sx strategies) are each self-contained test
# roots that import a same-named local `_harness` helper. Collected in one
# pytest run those two `_harness` modules would collide in `sys.modules`, so
# each suite gets its own invocation -- which also keeps a failing acceptance
# scenario from aborting the unit run, and lets each be run alone during
# development (`python strategies/test_s8_market_maker.py`, etc.).
#
# Usage:  scripts/run_tests.sh [extra pytest args]
#   e.g.  scripts/run_tests.sh -x -q
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"

echo "== unit / integration (tests/market) =="
"$PY" -m pytest tests/market/ "$@"

echo "== scenarios (Jx acceptance catalogue) =="
"$PY" -m pytest scenarios/ "$@"

echo "== strategies (Sx) =="
"$PY" -m pytest strategies/ "$@"

echo "All suites passed."
