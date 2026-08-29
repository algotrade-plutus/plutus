"""S4 — Auction-only rebalancer: accumulate at the open, distribute at the close.

Strategy **S4** of ``docs/reference/STRATEGY-BOARD.md``, written as a user writes
it. A strategy that trades **only the auctions**: each day it buys at the
opening cross (ATO) and sells settled inventory into the closing cross (ATC),
never touching the continuous session. It is the auction counterpart of a
market-on-close desk, and it is the strategy that forced the auction build.

THE FEATURE THIS BUILT
    On the daily corpus the session **never entered an auction phase** — the
    base adapter stamps every bar ``CONTINUOUS`` (a daily bar's ts is midnight),
    so an ATO/ATC order was refused *illegal-in-continuous* and never reached a
    cross. J7/J14 could only demonstrate the fill by calling ``auction_fill_price``
    directly, off the session path. This adds
    ``AuctionAwareDataHubSource`` (``adapters/auction_daily.py``): it reads the
    phase off the request *instant* (the session's advance time, a real intraday
    time — not the bar's midnight) via the dated schedule, and wires the
    published **open** (``quote_open``, on disk but unwired in the base source).
    Now an ATO crosses at the published open and an ATC at the published close,
    **through the ordinary session** — admission, book, settlement and all. Built,
    not mocked. The base adapter is untouched, so the rest of the suite is too.

MECHANISM / POLICY (oracle — SCENARIO-CATALOGUE.md, folded scenarios)
    * The auction crosses at one price for everyone, taken to be the published
      open (ATO) / close (ATC). This is OUR MODELLING CHOICE (A75), not a rule:
      we do not trust tick data inside the auction window, so we use the stored
      published values. QĐ 352 Điều 2.5 (close = the day's last match) is context
      for why the close is a fair stand-in (J7/J14).
    * An ATO/ATC is legal only in its auction phase; a cross fills everyone at
      one price (J12/J14).

SETUP — FPT (HSX), 2022-11-08 → 2022-11-18. Buy 500 at each ATO; sell settled
    inventory at each ATC. T+2 means the open buys settle two sessions later, so
    the ATC distributes a rolling, already-settled book.

EXPECTED — Tier 2
    * Through the session path, ATO orders cross at the **published open** and
      ATC orders at the **published close** (verified against ``quote_open`` /
      ``quote_close`` independently).
    * On at least one day the two auctions cross at **different** prices — the
      open is not the close.
    * The strategy trades *only* in the auctions (no continuous fills).

RUN
    .venv/bin/python strategies/test_s4_auction_rebalancer.py
    .venv/bin/python -m pytest strategies/test_s4_auction_rebalancer.py -v
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.adapters.auction_daily import AuctionAwareDataHubSource
from plutus.market.session.rulebook import Rulebook
from plutus.market.session.types import Venue
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available, data_root, CorpusFeed

TICKER = "FPT"
START = date(2022, 11, 8)
END = date(2022, 11, 18)
ATO_QTY = 500

ATO_SUBMIT = time(9, 5)     # opening-auction window (HSX 09:00–09:15)
ATO_CROSS = time(9, 12)
ATC_SUBMIT = time(14, 35)   # closing-auction window (HSX 14:30–14:45)
ATC_CROSS = time(14, 44)

CONFIG = {
    "period": {"start": "2022-11-08", "end": "2022-11-18"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HSX"]},
    "accounts": {"securities": {"initial_cash": 500_000_000, "account_no": "SEC-S4"}},
}


def _kind(e):
    return getattr(e.kind, "value", e.kind)


def _sellable(session: ExchangeSession) -> int:
    h = session.holdings(TICKER)
    return max(0, int(getattr(h, "settled", 0) or 0)
               - int(getattr(h, "committed", 0) or 0))


class MarketOnAuction:
    """Accumulate at the opening cross, distribute settled stock at the close."""

    name = "auction-only rebalancer"

    def decide_ato(self, session):
        return Order(ticker=TICKER, side=Side.BUY, quantity=ATO_QTY,
                     order_type=OrderType.AT_THE_OPENING)

    def decide_atc(self, session):
        sellable = _sellable(session)
        if sellable <= 0:
            return None
        return Order(ticker=TICKER, side=Side.SELL, quantity=sellable,
                     order_type=OrderType.AT_THE_CLOSE)


def run_s4():
    rulebook = Rulebook()
    source = AuctionAwareDataHubSource.for_root(
        data_root(), phase_for=lambda ts: rulebook.at(ts).phase(Venue.HSX))
    session = build_session(CONFIG, source=source)
    feed = CorpusFeed()
    strategy = MarketOnAuction()
    days = feed.trading_days([TICKER], START, END)

    ato_fills, atc_fills, other_fills = [], [], []

    def _collect(day, events, bucket):
        for e in events:
            if _kind(e) in ("filled", "partially_filled"):
                bucket.append((day, e.price))

    for day in days:
        # Opening cross.
        session.advance_to(datetime.combine(day, ATO_SUBMIT))
        ato = strategy.decide_ato(session)
        if ato is not None:
            v = session.submit(ato)
            if isinstance(v, Accepted):
                _collect(day, session.advance_to(datetime.combine(day, ATO_CROSS)),
                         ato_fills)
        # Anything filling outside the two crosses would show up here.
        _collect(day, session.advance_to(datetime.combine(day, ATC_SUBMIT)),
                 other_fills)
        # Closing cross.
        atc = strategy.decide_atc(session)
        if atc is not None:
            v = session.submit(atc)
            if isinstance(v, Accepted):
                _collect(day, session.advance_to(datetime.combine(day, ATC_CROSS)),
                         atc_fills)

    return {"session": session, "source": source, "days": days,
            "ato_fills": ato_fills, "atc_fills": atc_fills,
            "other_fills": other_fills, "strategy": strategy}


def _published_open(source, day) -> Decimal:
    return source._open_at(TICKER, datetime.combine(day, ATO_SUBMIT))


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_s4_auction_rebalancer():
    obs = run_s4()
    feed = CorpusFeed()

    # It traded in both auctions.
    assert obs["ato_fills"], "no ATO ever crossed"
    assert obs["atc_fills"], "no ATC ever crossed (nothing settled to distribute?)"

    # Every ATO crossed at the published open, every ATC at the published close —
    # through the session path, not a direct call to auction_fill_price.
    for day, price in obs["ato_fills"]:
        assert price == _published_open(obs["source"], day), \
            (day, price, _published_open(obs["source"], day))
    for day, price in obs["atc_fills"]:
        assert price == feed.close_on(TICKER, day), \
            (day, price, feed.close_on(TICKER, day))

    # On at least one day the two crosses disagree — the open is not the close.
    ato_by_day = dict(obs["ato_fills"])
    atc_by_day = dict(obs["atc_fills"])
    both = set(ato_by_day) & set(atc_by_day)
    assert any(ato_by_day[d] != atc_by_day[d] for d in both), \
        {d: (ato_by_day[d], atc_by_day[d]) for d in both}

    # The strategy traded ONLY in the auctions — nothing filled in continuous.
    assert not obs["other_fills"], obs["other_fills"]


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    obs = run_s4()
    print("S4 — Auction-only rebalancer (FPT, Nov 2022)")
    print(f"  ATO crosses: {len(obs['ato_fills'])}   ATC crosses: {len(obs['atc_fills'])}"
          f"   continuous fills: {len(obs['other_fills'])}")
    for day, px in obs["ato_fills"][:3]:
        print(f"    ATO {day}: crossed {px}  (published open {_published_open(obs['source'], day)})")
    for day, px in obs["atc_fills"][:3]:
        print(f"    ATC {day}: crossed {px}")
    try:
        test_s4_auction_rebalancer()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
