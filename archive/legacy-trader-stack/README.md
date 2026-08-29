# Archived — the pre-exchange-model trader stack

These five modules were `src/plutus/core/{bot,algorithm,portfolio,position,transaction}.py`.
They are the remnant of an earlier, abandoned direction: a strategy/portfolio/
backtest runner. Plutus is **not** that — it is an executable model of Vietnamese
exchange rules (admission + position survival), with no strategy engine, no
portfolio, and no P&L (see `src/plutus/market/session/__init__.py`).

**Why archived rather than deleted.** They are kept for history, but moved out of
the importable package so a reader browsing `src/plutus/` no longer finds a
half-built backtester that contradicts the library's framing.

**Why they are inert.**
- There is **no `__init__.py` here on purpose** — this directory is not a Python
  package, so nothing can `import` these files. They are not shipped in the wheel
  (packaging builds from `src/plutus` only).
- Every one of them was already unimportable in isolation: `position.py` and
  `transaction.py` do a bare `import utils` that only ever resolved by accident
  to an unrelated `utils` module on the test path. `bot.py`'s `run()` raised
  `NotImplementedError` by design ("never fake a backtest").
- They form a closed cluster (`bot → algorithm → portfolio → position →
  transaction`) that no live code imported.

**What stayed live.** `src/plutus/core/order.py`, `constant.py`, and
`instrument.py` are real, heavily-used value types and remain in the package.

If you want any of this behaviour back, it belongs to a *separate* strategy layer
built on top of the exchange model, not inside `plutus.core`.
