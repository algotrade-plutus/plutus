"""J25 — A strategy meeting a data gap: the ignorance meter.

Scenario **J25** of ``docs/reference/SCENARIO-CATALOGUE.md``, as user code.
This is the scenario that demonstrates the project's central discipline: **an
unknown is reported, not resolved by a guess.** A run is honest about what it
could not witness.

MECHANISM
    Every fill on the daily adapter is decided *without* the day's open / high /
    low / book-size — the adapter serves the close and withholds the rest — and
    the ignorance meter records each as a blind spot. So a run can post zero
    INDETERMINATE verdicts and still not be clean: the honest predicate is
    ``is_clean`` (nothing undecided *or* unwitnessed), not ``indeterminate == 0``.

GOVERNING "POLICY" — none of this is a Vietnamese rule, and that is the point.
    ``Blindness`` and the INDETERMINATE verdict are OUR modelling choices: the
    machinery by which an absent datum becomes an output rather than a silent
    default. NOTE: the withheld fields are on disk — ``DataHubSource`` (outdated,
    slated for reimplementation) chooses not to serve them. A blind spot here is
    the *adapter* being honest about what it serves, NOT evidence the data is
    unavailable.

EXPECTED — Tier 2
    * A normal fill posts zero INDETERMINATE verdicts...
    * ...yet the run is NOT clean: it reports blind spots for the fields it did
      not witness (open / high / low / book-size).
    * So ``is_clean`` catches what ``indeterminate == 0`` misses — the exact
      failure mode the meter exists to prevent.

RUN
    python scenarios/test_j25_data_gap.py
    pytest scenarios/test_j25_data_gap.py -v
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.session import ExchangeSession, Accepted  # noqa: F401
from plutus.market.protocol import Order
from plutus.core.order import OrderType, Side

from _harness import build_session, data_available

CONFIG = {
    "period": {"start": "2022-11-09", "end": "2022-11-10"},
    "resolution": "1d",
    "exchange_rules": {"venues": ["HSX"]},
    "accounts": {"securities": {"initial_cash": 200_000_000, "account_no": "SEC-J25"}},
}


def run_j25():
    session = build_session(CONFIG)
    session.submit(Order(ticker="FPT", side=Side.BUY, quantity=1000,
                         order_type=OrderType.LIMIT, limit_price=Decimal("74.0")))
    session.advance_to(datetime(2022, 11, 9, 13, 0))   # fills
    return session, session.indeterminate_report()


@pytest.mark.skipif(not data_available(),
                    reason="market-data corpus not found; set PLUTUS_DATA_ROOT")
def test_j25_data_gap():
    session, report = run_j25()

    # The fill decided — nothing was left INDETERMINATE...
    assert report.indeterminate == 0, report

    # ...but the run is NOT clean: it did not witness the day's open/high/low/
    # book-size, and it says so rather than pretending it did.
    assert not report.is_clean, report
    assert report.silent_total > 0, report
    assert report.blind_spots(), report

    # This is the whole point: is_clean catches what indeterminate == 0 misses.
    assert report.indeterminate == 0 and not report.is_clean


if __name__ == "__main__":
    if not data_available():
        raise SystemExit("market-data corpus not found; set PLUTUS_DATA_ROOT")
    session, report = run_j25()
    print("J25 — Data gap / ignorance meter (FPT, HSX, 2022-11-09)")
    print(f"  indeterminate: {report.indeterminate}")
    print(f"  is_clean:      {report.is_clean}")
    print(f"  silent_total:  {report.silent_total}")
    print(f"  blind spots:   {report.blind_spots()}")
    try:
        test_j25_data_gap()
        print("  TIER 2: PASS")
    except AssertionError as exc:
        print(f"  TIER 2: FAIL — {exc}")
