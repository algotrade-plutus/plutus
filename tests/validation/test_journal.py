"""The recording seam.

The journal wraps ledger methods on one session instance. Two things have to
be true of that, and neither is obvious: it must not change a single number
the session reports, and it must put the ledger back when it detaches.

The third test here is the one that motivates the module: the securities cash
ledger keeps no journal of its own, and the derivatives deposit does. If that
asymmetry is ever removed, this test says so.
"""

from decimal import Decimal

import pytest

from conftest import D1, DAYS, stub_scenario
from validation.journal import LedgerJournal, classify_reason
from validation.logs import CashLog, CashMovement, SettlementLog
from validation.runner import run_scenario
from validation.strategy import BaseStrategy


class BuyOnce(BaseStrategy):
    name = 'buy-once'

    def on_session(self, ctx):
        if ctx.today == D1:
            ctx.buy('FPT', 1000, limit_price=Decimal('95.5'))


def _reported(session):
    """Every figure the session reports, as one comparable tuple."""
    cash = session.cash()
    view = session.margin()
    return (cash.settled_balance, cash.committed, cash.available,
            cash.advanced, cash.pending_total, cash.interest_accrued,
            view.deposit_balance, view.initial_margin, view.variation_margin,
            view.posted_margin, view.resting_order_margin,
            session.holdings('FPT').settled,
            session.holdings('FPT').unsettled_quantity,
            tuple(sorted((c.kind, c.amount) for c in session.charges())))


def test_attaching_the_journal_changes_no_number_the_session_reports():
    """The same run twice, once recorded and once not.

    A recording seam that moved a balance would make every log built through
    it a description of a different run.
    """
    recorded = stub_scenario(BuyOnce())
    result = run_scenario(recorded)
    assert result.error is None

    plain = stub_scenario(BuyOnce())
    session = plain.session
    for day in DAYS:
        from datetime import datetime, time
        session.advance_to(datetime.combine(day, time(9, 30)))
        plain.strategy.on_session(_Ctx(session, day))
        session.advance_to(datetime.combine(day, time(14, 45)))

    assert _reported(recorded.session) == _reported(session)


class _Ctx:
    """The two attributes ``BuyOnce`` uses, without the harness."""

    def __init__(self, session, day):
        self._session = session
        self.today = day

    def buy(self, ticker, quantity, *, limit_price=None):
        from plutus.core.order import OrderType, Side
        from plutus.market.protocol import Order
        return self._session.submit(Order(
            ticker=ticker, side=Side.BUY, quantity=quantity,
            order_type=OrderType.LIMIT, limit_price=limit_price))


def test_detach_puts_every_wrapped_method_back():
    scenario = stub_scenario(BuyOnce())
    ledger = scenario.session._securities.cash_ledger
    before = ledger.debit
    journal = LedgerJournal(scenario.session, CashLog(), SettlementLog(),
                            iter(range(10_000)).__next__).attach()
    assert ledger.debit is not before
    journal.detach()
    assert ledger.debit == before
    assert 'debit' not in ledger.__dict__


def test_attaching_twice_raises_rather_than_double_recording():
    scenario = stub_scenario(BuyOnce())
    journal = LedgerJournal(scenario.session, CashLog(), SettlementLog(),
                            iter(range(10_000)).__next__).attach()
    with pytest.raises(RuntimeError):
        journal.attach()
    journal.detach()


def test_the_securities_pool_has_no_cash_journal_of_its_own():
    """The asymmetry this module exists to compensate for.

    ``DerivativesAccount`` keeps a ``DepositEntry`` per movement, with the
    balance it produced. ``CashLedger`` takes ``ts`` and ``reason`` on every
    debit and credit and stores neither -- it itemises charges and nothing
    else. If a securities-side journal is ever added, delete the wrapping in
    :mod:`validation.journal` and read it instead.
    """
    scenario = stub_scenario(BuyOnce())
    ledger = scenario.session._securities.cash_ledger
    account = scenario.session._derivatives

    assert hasattr(account, 'entries')
    assert [f for f in ('entries', 'movements', 'journal', 'history')
            if hasattr(ledger, f)] == []
    assert set(ledger.charges()) == set()


def test_every_cash_row_of_a_buy_names_its_cause():
    result = run_scenario(stub_scenario(BuyOnce()))
    causes = {e.movement for e in result.logs.cash}
    assert CashMovement.OPENING_BALANCE in causes
    assert CashMovement.BUY_CONSIDERATION in causes
    assert CashMovement.CHARGE_DEBITED in causes
    assert all(e.cause for e in result.logs.cash)
    buy = [e for e in result.logs.cash
           if e.movement is CashMovement.BUY_CONSIDERATION][0]
    assert buy.amount == Decimal('-95500000.0')
    assert buy.cause == 'buy FPT'
    assert buy.balance_after == Decimal('1000000000') + buy.amount


def test_a_charge_row_carries_the_base_it_was_computed_on():
    """An itemised charge that cannot be checked is not itemised."""
    result = run_scenario(stub_scenario(BuyOnce()))
    charges = [e for e in result.logs.cash
               if e.movement is CashMovement.CHARGE_DEBITED]
    assert charges
    for row in charges:
        assert row.charge_kind
        assert row.charge_base
        assert row.charge_base_value is not None
        assert row.fill_id


def test_an_unrecognised_reason_is_reported_as_unrecognised():
    """Classification is a convenience; the verbatim reason is the record.

    A new cash movement in ``ledgers.py`` must not be silently absorbed into
    an existing cause.
    """
    assert classify_reason('buy FPT', Decimal('-1')) is (
        CashMovement.BUY_CONSIDERATION)
    assert classify_reason('some new movement', Decimal('-1')) is (
        CashMovement.OTHER_DEBIT)
    assert classify_reason('some new movement', Decimal('1')) is (
        CashMovement.OTHER_CREDIT)
