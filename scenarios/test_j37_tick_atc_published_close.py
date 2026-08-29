"""J37 — A tick-path closing auction returns the published close, never the last.

Scenario **J37** of the intraday extension, and the fix for defect **D71**. A
call auction crosses at **one published price for everyone** (design A75): the
ATO at the day's published open, the ATC at its published close. On a **tick**
run the session has no bar to read, so it synthesises the interval from a
snapshot — and a snapshot has no published open OR close. The opening auction
was already honest about this (it returns INDETERMINATE, naming OPEN). The
closing auction was not: it filled at ``state.last``, a **pre-auction print**,
wearing the published close's name — a price the market never closed at. D71.

THE FIX (one condition, in ``exchange._interval_for``). When the interval is
    synthesised and the phase is an auction, the close is dropped and named
    missing, exactly as the open already is. So the ATC now returns the
    **published close where a source supplies one**, and **INDETERMINATE**
    on a bare snapshot -- symmetric with the ATO, and never the stale last.

TWO SOURCES, one order, 14:35 (HOSE's closing auction is 14:30-14:45):
    * a **snapshot** source (no intervals) synthesises the interval -> no
      published close -> the ATC is INDETERMINATE naming CLOSE (it does NOT
      fill at the 100.0 last);
    * an **interval** source that carries the day's close (98.0) -> the ATC
      fills at 98.0, the published close, NOT the 100.0 last.

EXPECTED — Tier 2
    * Snapshot: the order does not fill; the run's ignorance names CLOSE. **This
      is the case that pins the fix** -- before it, this order filled at 100.0,
      the stale last (see ``test_d71_...`` for the pre/post regression guard).
    * Interval: the order fills at the published close (98.0), distinct from the
      stale last (100.0). This is the *other half* -- the ATC crossing on a
      real published close -- and a check that the synthesis-branch change did
      not leak into the IntervalSource path; it is not itself the regression
      guard (an IntervalSource never reaches the synthesis branch).

RUN
    python scenarios/test_j37_tick_atc_published_close.py
    pytest scenarios/test_j37_tick_atc_published_close.py -v
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from plutus.core.order import OrderType, Side
from plutus.market.protocol import (BandSource, InstrumentKind, InstrumentSpec,
                                     MarketState, Order, Resolution, SessionPhase)
from plutus.market.session import (Accepted, EventKind, ExchangeSession,
                                    MarketInterval, parse_config)
from plutus.market.session.types import DataField

TICKER = "FPT"
DAY = date(2024, 6, 3)                 # a Monday, so T+2 is clean
LAST = Decimal("100.0")                # the pre-auction print
PUBLISHED_CLOSE = Decimal("98.0")      # what the day actually closed at
ATC = datetime(2024, 6, 3, 14, 35)     # inside HOSE's 14:30-14:45 close


def _state(session: SessionPhase = SessionPhase.UNKNOWN) -> MarketState:
    return MarketState(
        ticker=TICKER, ts=datetime.combine(DAY, datetime.min.time()),
        reference=LAST, ceiling=LAST * Decimal("1.07"),
        floor=LAST * Decimal("0.93"), band_source=BandSource.PUBLISHED,
        last=LAST, session=session)


class _SnapshotSource:
    """Serves snapshots only -- NOT an IntervalSource, so the session must
    synthesise the interval (the tick path where D71 lives). The rulebook
    re-stamps the closing-auction phase onto the snapshot at 14:35."""

    def __init__(self, session: SessionPhase = SessionPhase.UNKNOWN):
        self._state = _state(session)

    def state_at(self, ticker, ts):
        return self._state if ticker == TICKER else None

    def states(self, ticker, start, end, *, resolution=Resolution.DAILY):
        if ticker == TICKER:
            yield self._state

    def instrument(self, ticker):
        return InstrumentSpec(ticker=ticker, exchange_code="HOSE",
                              kind=InstrumentKind.STOCK, trading_unit=100,
                              daily_trading_limit=Decimal("0.07"),
                              multiplier=Decimal("1"))


class _IntervalSource(_SnapshotSource):
    """Also serves whole intervals, so the bar can carry the published close."""

    def interval(self, ticker, start, end, *, resolution):
        if ticker != TICKER:
            return None
        return MarketInterval(
            ticker=ticker, start=start, end=end, resolution=resolution,
            state=self._state, close=PUBLISHED_CLOSE)


def _run(source):
    config = parse_config({
        "period": {"start": "2024-06-03", "end": "2024-06-04"},
        "resolution": "tick",
        "exchange_rules": {"venues": ["HSX"]},
        "accounts": {"securities": {"initial_cash": 200_000_000,
                                    "account_no": "SEC-J37"}},
        "fill_policy": {"kind": "soft"},
    })
    session = ExchangeSession.build(config, source=source)
    session.advance_to(datetime(2024, 6, 3, 9, 30))
    ack = session.submit(Order(ticker=TICKER, side=Side.BUY, quantity=1000,
                               order_type=OrderType.LIMIT, limit_price=LAST))
    events = session.advance_to(ATC)
    fills = [e for e in events if e.kind in (EventKind.FILLED,
                                             EventKind.PARTIALLY_FILLED)]
    return {"ack": ack, "fills": fills,
            "ignorance": session.indeterminate_report()}


def run_j37():
    # The interval source stamps the closing-auction phase on its own bar (an
    # auction-aware source does); the snapshot source relies on the rulebook
    # re-stamp at 14:35.
    return {"snapshot": _run(_SnapshotSource()),
            "interval": _run(_IntervalSource(SessionPhase.CLOSING_AUCTION))}


def test_j37_tick_atc_published_close():
    obs = run_j37()

    # Snapshot: no published close -> the ATC is INDETERMINATE naming CLOSE, and
    # it does NOT fill at the stale last.
    snap = obs["snapshot"]
    assert isinstance(snap["ack"], Accepted), snap["ack"]
    assert not snap["fills"], f'D71: filled at the stale last {snap["fills"]}'
    assert DataField.CLOSE in snap["ignorance"].by_field, snap["ignorance"]

    # Interval: the other half -- the ATC crosses on the PUBLISHED CLOSE (98.0),
    # distinct from the stale last (100.0). (The snapshot case above is the one
    # that pins the fix; this shows a real close still crosses and the change
    # did not leak into the IntervalSource path.)
    inter = obs["interval"]
    assert inter["fills"], "the ATC never crossed on the published close"
    assert {e.price for e in inter["fills"]} == {PUBLISHED_CLOSE}, inter["fills"]
    assert PUBLISHED_CLOSE != LAST


if __name__ == "__main__":
    obs = run_j37()
    print("J37 — Tick-path ATC returns the published close, not the last (D71)")
    snap, inter = obs["snapshot"], obs["interval"]
    print(f"  snapshot source: fills={len(snap['fills'])}  "
          f"ignorance names CLOSE={DataField.CLOSE in snap['ignorance'].by_field}")
    print(f"  interval source: fills at "
          f"{[str(e.price) for e in inter['fills']]}  (published close "
          f"{PUBLISHED_CLOSE}, stale last {LAST})")
    try:
        test_j37_tick_atc_published_close()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
