"""Shared plumbing for the strategy fidelity suite.

The strategies in this folder are written **as a user writes them** — public
API only, the way a ``pip install``'d developer trades against Plutus. This
module is the little they share, and it is deliberately **test-side**: it is
*not* part of the shipped library. It plays the role of "the user's own
framework" — the event loop that steps the exchange, and the historical data
feed that carries market history alongside (never inside) the broker. Plutus
itself is only the market across the table.

Two pieces:

* :class:`CorpusFeed` — the user's own data feed. A thin, **look-ahead-safe**
  reader over the same public corpus adapter (:class:`DataHubSource`) the
  session reads, so the price a signal sees is the price the exchange fills
  against, with nothing from the future leaking in.
* :func:`run` — the day loop. For each trading day it advances the session to
  a morning mark (surfacing overnight/settlement events), lets the strategy
  decide, then advances **past the 14:45 determination** to a close mark
  (surfacing fills, margin calls, forced closes), and snapshots equity. The
  determination detail is load-bearing: stop the day at 14:00 and the whole
  margin lifecycle never runs.

Reproducibility: point ``PLUTUS_DATA_ROOT`` at your corpus (a directory of
``quote_*.parquet`` files). Unset falls back to the author's machine, so the
suite runs here out of the box and is one env var away from running anywhere.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from plutus.market.session import ExchangeSession
from plutus.market.adapters.datahub import DataHubSource

#: Fallback corpus (author's machine). Override with PLUTUS_DATA_ROOT.
DEFAULT_DATA_ROOT = "/Users/nadan/algotrade-research/dataset/hermes-parquet"

#: The daily-resolution adapter over the corpus.
DEFAULT_ADAPTER = "plutus.market.adapters.datahub.DataHubSource"

#: The two marks each day. CLOSE_MARK is past the 14:45 determination time, so
#: the margin lifecycle (call, cure, forced close) actually runs.
OPEN_MARK = time(10, 0)
CLOSE_MARK = time(15, 0)

#: Corpus equity/index prices are quoted in thousands of đồng (27.0 == 27,000đ),
#: while cash and deposits are in đồng. Multiply a price by this to value shares.
PRICE_SCALE = 1000


# --------------------------------------------------------------------------
# Corpus / session (same path the scenarios use)
# --------------------------------------------------------------------------

def data_root() -> str:
    """The market-data corpus root — ``PLUTUS_DATA_ROOT`` or the fallback."""
    return os.environ.get("PLUTUS_DATA_ROOT", DEFAULT_DATA_ROOT)


def data_available() -> bool:
    """Whether a usable corpus is present, so a strategy can skip cleanly."""
    root = Path(data_root())
    return root.is_dir() and any(root.glob("quote_close*.parquet"))


def build_session(config: dict, *, source=None) -> ExchangeSession:
    """Build a session from a config dict, exactly the user's ``from_config``
    path — the config is written to a file and loaded, no privileged
    injection. ``data.root`` is filled from ``PLUTUS_DATA_ROOT`` so the same
    strategy runs on any machine with the corpus.

    ``source`` lets a strategy hand in a pre-built data source, so the session,
    the signal feed and (for equity margin) the account's ``market_feed`` all
    read the *same* object — the pattern J5 uses so marks cannot diverge.
    """
    cfg = json.loads(json.dumps(config))  # deep copy; never mutate the caller's
    data = cfg.setdefault("data", {})
    data.setdefault("adapter", DEFAULT_ADAPTER)
    data["root"] = data_root()
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(cfg, handle)
        path = handle.name
    if source is not None:
        return ExchangeSession.from_config(path, source=source)
    return ExchangeSession.from_config(path)


# --------------------------------------------------------------------------
# The user's own data feed
# --------------------------------------------------------------------------

class CorpusFeed:
    """The strategy's historical market-data feed — the user's, not Plutus's.

    A real desk runs a data feed *beside* the broker, not through it, and so
    do we: this reads the same corpus the session's adapter reads, so the
    signal and the fill agree on price, but it is the strategy's own object and
    the exchange knows nothing about it.

    Everything here is **look-ahead-safe by construction**: the reader's window
    is half-open ``[start, asof)``, so a bar stamped on ``asof`` is never
    returned to a decision made on ``asof``.
    """

    def __init__(self, root: Optional[str] = None, *, source=None) -> None:
        self._src = source or DataHubSource.for_root(root or data_root())
        self._series_cache: Dict[Tuple[str, date, date], List[Tuple[date, Decimal]]] = {}

    @property
    def source(self):
        """The underlying adapter, e.g. for an ``EquityMarginAccount``'s
        ``market_feed`` — so the account and the signal share one source."""
        return self._src

    def _series(self, ticker: str, start: date, end: date) -> List[Tuple[date, Decimal]]:
        """``(day, close)`` for ``ticker`` over the half-open ``[start, end)``."""
        key = (ticker, start, end)
        if key not in self._series_cache:
            self._series_cache[key] = [
                (s.ts.date(), s.last)
                for s in self._src.states(ticker, start, end)
                if s.last is not None
            ]
        return self._series_cache[key]

    def closes_before(self, ticker: str, asof: date, lookback: int, *,
                      start: date) -> List[Decimal]:
        """The last ``<= lookback`` daily closes **strictly before** ``asof``.

        Returns fewer than ``lookback`` while the window is still warming up;
        the strategy is expected to sit out until it has enough history.
        """
        series = self._series(ticker, start, asof)   # end-exclusive => excludes asof
        return [c for _, c in series][-lookback:]

    def close_on(self, ticker: str, day: date) -> Optional[Decimal]:
        """``ticker``'s close **on** ``day``, or ``None`` if the day is absent
        (a real data gap, which is a strategy's problem to handle, not a crash).
        """
        state = self._src.state_at(ticker, datetime.combine(day, CLOSE_MARK))
        return None if state is None else state.last

    def state_on(self, ticker: str, day: date):
        """The full :class:`MarketState` on ``day`` — carries the legal band
        (``ceiling``/``floor``), a start-of-day fact, for pricing a marketable
        order. ``None`` on an absent day.
        """
        return self._src.state_at(ticker, datetime.combine(day, OPEN_MARK))

    def trading_days(self, tickers: Sequence[str], start: date,
                     end: date) -> List[date]:
        """Every day any of ``tickers`` traded, within ``[start, end)`` — the
        honest set of sessions, learned from the feed rather than a calendar.
        """
        days = set()
        for ticker in tickers:
            for stamp, _ in self._series(ticker, start, end):
                days.add(stamp)
        return sorted(d for d in days if start <= d < end)


# --------------------------------------------------------------------------
# The strategy contract
# --------------------------------------------------------------------------

@dataclass
class Context:
    """Everything a hook needs, in one handle: the market (``session``), the
    feed, today's ``day``, and the ``ledger`` recording the run."""
    session: ExchangeSession
    feed: CorpusFeed
    day: date
    ledger: "RunLedger"


class Strategy:
    """Base strategy. Override the hooks you need; the rest are no-ops.

    * :meth:`on_start` — once, before the first day.
    * :meth:`on_day` — each day, after the morning mark: read truth
      (``session.cash()``/``positions()``/``margin()``) and the feed's
      history, then ``submit`` orders for today.
    * :meth:`on_event` — for every event the market emits (fills, margin
      calls, forced closes), at both marks.
    * :meth:`on_finish` — once, after the last day.
    """

    name: str = "strategy"

    def on_start(self, ctx: Context) -> None: ...
    def on_day(self, ctx: Context) -> None: ...
    def on_event(self, ctx: Context, event) -> None: ...
    def on_finish(self, ctx: Context) -> None: ...


# --------------------------------------------------------------------------
# The run ledger — equity curve, events, conservation
# --------------------------------------------------------------------------

def _kind(event) -> str:
    return getattr(getattr(event, "kind", None), "value", getattr(event, "kind", ""))


@dataclass
class RunLedger:
    """What a run produced, read back through the public surface only.

    Holds the equity curve and every event, and computes the two checks a
    scenario is too short to reach: **economic equity** (mark-to-market, so a
    losing position shows as a falling curve even while the deposit balance is
    unchanged) and **conservation** (money only moves via marks and charges).
    """
    session: ExchangeSession
    feed: CorpusFeed
    universe: Tuple[str, ...] = ()
    equity_curve: List[Tuple[date, Decimal]] = field(default_factory=list)
    events: List[Tuple[date, object]] = field(default_factory=list)
    rejects: List[Tuple[date, object]] = field(default_factory=list)

    # -- recording ---------------------------------------------------------

    def record_event(self, day: date, event) -> None:
        self.events.append((day, event))

    def record_reject(self, day: date, verdict) -> None:
        self.rejects.append((day, verdict))

    def record_equity(self, day: date) -> None:
        self.equity_curve.append((day, self.equity(day)))

    # -- economic equity ---------------------------------------------------

    def equity(self, day: date) -> Decimal:
        """Mark-to-market account equity across both pools at ``day``.

        Securities pool: settled + advanced cash, plus holdings marked at the
        feed's close. Derivatives pool: ``deposit_balance`` plus each open
        contract's unrealised P&L ``(mark - average_entry) * net * multiplier``
        — the piece the deposit does **not** carry (assets = deposit_balance),
        so without this the curve would hide the drawdown that drives the call.
        """
        eq = Decimal(0)
        cash = self.session.cash()
        eq += cash.settled_balance + cash.advanced
        for ticker in self.universe:
            holding = self.session.holdings(ticker)
            qty = int(getattr(holding, "settled", 0) or 0) + sum(
                (t.quantity for t in getattr(holding, "unsettled", ()) or ()), 0)
            if qty:
                price = self.feed.close_on(ticker, day)
                if price is not None:
                    # equity prices are in thousands of đồng; cash is in đồng.
                    eq += Decimal(qty) * price * PRICE_SCALE
        margin = self.session.margin()
        eq += margin.deposit_balance
        for code, pos in self.session.positions().items():
            mark = self.feed.close_on(code, day)
            if mark is not None:
                eq += (mark - pos.average_entry) * pos.net_quantity * pos.multiplier
        return eq

    # -- typed views -------------------------------------------------------

    def of_kind(self, kind: str) -> List[Tuple[date, object]]:
        return [(d, e) for d, e in self.events if _kind(e) == kind]

    def calls(self) -> List[Tuple[date, object]]:
        return self.of_kind("margin_call")

    def forced(self) -> List[Tuple[date, object]]:
        return self.of_kind("forced_liquidation")

    def fills(self) -> List[Tuple[date, object]]:
        return [(d, e) for d, e in self.events
                if _kind(e) in ("filled", "partially_filled")]

    def warnings(self) -> List[Tuple[date, object]]:
        return self.of_kind("margin_warning")

    def executed_forced(self) -> List[Tuple[date, object]]:
        return [(d, e) for d, e in self.forced()
                if getattr(e, "detail", {}).get("executed") is True]

    # -- reporting ---------------------------------------------------------

    def summary(self) -> str:
        first = self.equity_curve[0][1] if self.equity_curve else Decimal(0)
        last = self.equity_curve[-1][1] if self.equity_curve else Decimal(0)
        trough = min((e for _, e in self.equity_curve), default=Decimal(0))
        return (f"days={len(self.equity_curve)}  "
                f"equity {first:,.0f} -> {last:,.0f}  trough {trough:,.0f}  "
                f"fills={len(self.fills())} calls={len(self.calls())} "
                f"forced={len(self.forced())} rejects={len(self.rejects)}")


# --------------------------------------------------------------------------
# The day loop
# --------------------------------------------------------------------------

def run(strategy: Strategy, *, session: ExchangeSession, feed: CorpusFeed,
        start: date, end: date, universe: Sequence[str]) -> RunLedger:
    """Step ``strategy`` through Plutus over the trading days in ``[start, end)``.

    Two marks a day: a morning mark (overnight/settlement events surface, then
    the strategy decides and submits) and a close mark past 14:45 (fills,
    margin calls, forced closes surface). Equity is snapshotted at the close.
    """
    ledger = RunLedger(session=session, feed=feed, universe=tuple(universe))
    days = feed.trading_days(universe, start, end)
    ctx = Context(session=session, feed=feed,
                  day=days[0] if days else start, ledger=ledger)

    strategy.on_start(ctx)
    for day in days:
        ctx.day = day
        for event in session.advance_to(datetime.combine(day, OPEN_MARK)):
            ledger.record_event(day, event)
            strategy.on_event(ctx, event)
        strategy.on_day(ctx)
        for event in session.advance_to(datetime.combine(day, CLOSE_MARK)):
            ledger.record_event(day, event)
            strategy.on_event(ctx, event)
        ledger.record_equity(day)
    strategy.on_finish(ctx)
    return ledger
