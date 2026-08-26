"""The ledger identities.

Every test here has a pair: the identity holds on a real run, **and** it fails
when the thing it checks is broken. A check that only ever passes is worth
nothing -- the suite was green through twelve real defects, which is standing
rule 4 in this repo's own words.
"""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

import pytest

from conftest import D1, stub_scenario
from validation.identities import (
    cash_conservation, deposit_balance_trail, deposit_segregation,
    encumbrance_matches, encumbrance_zero, holdings_conservation,
    no_negative_settled, order_lifecycle, settlement_completeness,
)
from validation.logs import (
    CashLog, CashLogEntry, CashMovement, RunLogs, SettlementAction,
    SettlementLog, SettlementLogEntry, TradeAction, TradeLog, TradeLogEntry,
)
from validation.runner import run_scenario
from validation.strategy import BaseStrategy

TS = datetime(2024, 6, 3, 9, 30)
_ZERO = Decimal('0')


# --------------------------------------------------------------------------
# Stand-ins, exposing only what an identity reads
# --------------------------------------------------------------------------

class FakeHolding:
    def __init__(self, total=0, committed=0):
        self.total = total
        self.committed = committed


class FakeCash:
    def __init__(self, committed=_ZERO, settled=_ZERO):
        self.committed = committed
        self.settled_balance = settled


class FakeMargin:
    def __init__(self, resting=_ZERO, deposit=_ZERO):
        self.resting_order_margin = resting
        self.deposit_balance = deposit


class FakeOrder:
    def __init__(self, ticker='FPT'):
        self.ticker = ticker


class FakeRecord:
    def __init__(self, *, order_id='PLU-00000001', terminal=True, live=False,
                 cash=_ZERO, deposit=_ZERO, quantity=0, ticker='FPT'):
        self.order_id = order_id
        self.is_terminal = terminal
        self.is_live = live
        self.encumbered_cash = cash
        self.encumbered_deposit = deposit
        self.encumbered_quantity = quantity
        self.order = FakeOrder(ticker)


class FakeAccount:
    def __init__(self, entries=(), balance=_ZERO):
        self.entries = tuple(entries)
        self.deposit_balance = balance


class FakePool:
    def __init__(self, value):
        self.value = value


class FakeCharge:
    """Only what ``deposit_segregation`` reads off a ``Charge``."""

    def __init__(self, kind='vsdc_derivatives_clearing', fill_id='FILL-1',
                 ts=None, pool='derivatives', total=Decimal('2550')):
        self.kind = kind
        self.fill_id = fill_id
        self.ts = ts or TS
        self.pool = FakePool(pool)
        self.total = total


class FakeSession:
    """Only the seven reads the identities make."""

    def __init__(self, *, records=(), cash=None, margin=None, holdings=None,
                 positions=None, charges=(), account=None):
        self._records = tuple(records)
        self._cash = cash or FakeCash()
        self._margin = margin or FakeMargin()
        self._holdings = dict(holdings or {})
        self._positions = dict(positions or {})
        self._charges = tuple(charges)
        self._derivatives = account or FakeAccount()

    def orders(self, **_):
        return self._records

    def cash(self):
        return self._cash

    def margin(self):
        return self._margin

    def holdings(self, ticker):
        return self._holdings.get(ticker, FakeHolding())

    def positions(self):
        return self._positions

    def charges(self):
        return self._charges


# --------------------------------------------------------------------------
# A real run
# --------------------------------------------------------------------------

class RoundTrip(BaseStrategy):
    """Buy on D1, try to sell before settlement, sell once settled."""

    name = 'round-trip'

    def on_session(self, ctx):
        holding = ctx.holdings('FPT')
        if ctx.today == D1:
            ctx.buy('FPT', 1000, limit_price=Decimal('95.5'))
        elif holding.total and holding.sellable == 0:
            ctx.sell('FPT', 1000, limit_price=Decimal('95.5'))
        elif holding.sellable >= 1000:
            ctx.sell('FPT', 1000, limit_price=Decimal('95.5'))


@pytest.fixture(scope='module')
def run():
    return run_scenario(stub_scenario(RoundTrip()))


def test_every_identity_holds_on_a_completed_round_trip(run):
    assert run.error is None
    assert run.failed_identities == (), [
        (r.name, r.detail, r.breaches) for r in run.failed_identities]


def test_the_run_actually_exercised_something(run):
    """Guard against a green run that did nothing.

    A scenario that never filled, never settled and never refused would pass
    every identity vacuously, which is the failure mode this whole harness is
    built to avoid.
    """
    assert run.logs.trades.of(TradeAction.FILLED)
    assert run.logs.settlement.refusals
    assert any(e.movement is CashMovement.SETTLEMENT_CREDIT
               for e in run.logs.cash)


# --------------------------------------------------------------------------
# Cash conservation
# --------------------------------------------------------------------------

def test_cash_conservation_fails_when_a_movement_goes_unrecorded(run):
    """The failure mode the wrapping in ``journal.py`` risks.

    If ``ledgers.py`` grows a sixth way to move cash and the journal does not
    wrap it, the log is short by that movement and this is what catches it.
    """
    kept = CashLog()
    dropped = None
    for entry in run.logs.cash:
        if (dropped is None
                and entry.movement is CashMovement.BUY_CONSIDERATION):
            dropped = entry
            continue
        kept.append(entry)
    assert dropped is not None
    outcome = cash_conservation(kept, 'securities',
                               run.snapshots[-1].settled_cash)
    assert not outcome.passed
    assert outcome.difference == -dropped.amount
    assert outcome.breaches and 'itemised' in outcome.breaches[0]


def test_cash_conservation_fails_when_a_non_moving_row_is_counted(run):
    """A pending sale counted as if it were settled.

    This is the double count a naive cash log makes: the proceeds appear once
    when the sale fills and again when the tranche settles.
    """
    inflated = CashLog()
    for entry in run.logs.cash:
        if entry.movement is CashMovement.SALE_PROCEEDS_PENDING:
            entry = replace(entry, affects_balance=True)
        inflated.append(entry)
    assert not cash_conservation(inflated, 'securities',
                                 run.snapshots[-1].settled_cash).passed


# --------------------------------------------------------------------------
# Holdings
# --------------------------------------------------------------------------

def test_holdings_conservation_fails_when_shares_appear_from_nowhere(run):
    session = FakeSession(holdings={'FPT': FakeHolding(total=0)})
    outcome = holdings_conservation(session, run.logs, {'FPT': 500}, ('FPT',))
    assert not outcome.passed
    assert outcome.breaches[0]['opening'] == 500
    assert outcome.breaches[0]['leg'] == 'settled + unsettled'


def test_holdings_conservation_reads_the_contract_ledger_for_a_future():
    """A futures contract is not a ``Holding``.

    Checking a VN30F code against ``session.holdings()`` compares a contract
    count with an equity parcel and reports a breach on every derivatives run.
    """
    trades = TradeLog()
    trades.append(TradeLogEntry(seq=1, ts=TS, action=TradeAction.FILLED,
                                order_id='PLU-00000001', ticker='VN30F2406',
                                pool='derivatives', side='BUY',
                                fill_quantity=4))
    logs = RunLogs(trades=trades, cash=CashLog(), settlement=SettlementLog())

    class _Position:
        net_quantity = 4

    session = FakeSession(positions={'VN30F2406': _Position()})
    assert holdings_conservation(session, logs, {}, ('VN30F2406',)).passed

    empty = FakeSession(positions={})
    outcome = holdings_conservation(empty, logs, {}, ('VN30F2406',))
    assert not outcome.passed
    assert outcome.breaches[0]['leg'] == 'contract ledger net quantity'


def test_no_negative_settled_fails_on_a_transient_negative(run):
    """A negative that squares up by the close is still a corrupt ledger."""
    assert no_negative_settled(run.snapshots).passed
    broken = list(run.snapshots)
    broken[2] = replace(broken[2],
                        holdings={'FPT': {'settled': -100, 'committed': 0,
                                          'unsettled': 0, 'total': -100}})
    outcome = no_negative_settled(broken)
    assert not outcome.passed
    assert outcome.breaches[0]['settled'] == -100


# --------------------------------------------------------------------------
# Encumbrance
# --------------------------------------------------------------------------

def test_encumbrance_zero_fails_when_a_reservation_outlives_its_order():
    """The leak the single terminal hook exists to prevent."""
    session = FakeSession(records=(FakeRecord(terminal=True),),
                          cash=FakeCash(committed=Decimal('123')))
    outcome = encumbrance_zero(session, ('FPT',))
    assert not outcome.passed
    assert outcome.breaches[0]['what'] == 'cash.committed'


def test_encumbrance_zero_is_not_applicable_while_orders_are_live():
    """Reported as inapplicable, never as a pass that means something.

    A resting order legitimately holds a reservation; asserting zero there
    would be asserting that no order was ever left open.
    """
    session = FakeSession(records=(FakeRecord(terminal=False, live=True),),
                          cash=FakeCash(committed=Decimal('999')))
    outcome = encumbrance_zero(session, ('FPT',))
    assert outcome.passed
    assert 'not applicable' in outcome.detail


def test_encumbrance_matches_fails_when_records_and_ledgers_disagree():
    """Design section 12 invariant 4.

    The record total and the ledger total live in different objects updated by
    different code paths, which is exactly why they can drift.
    """
    session = FakeSession(
        records=(FakeRecord(terminal=False, cash=Decimal('500')),),
        cash=FakeCash(committed=Decimal('400')))
    outcome = encumbrance_matches(session, ('FPT',))
    assert not outcome.passed
    assert outcome.breaches[0] == {'what': 'cash', 'records': Decimal('500'),
                                  'ledger': Decimal('400')}


# --------------------------------------------------------------------------
# Order lifecycle
# --------------------------------------------------------------------------

def test_order_lifecycle_fails_on_a_fill_with_no_accepted_order():
    trades = TradeLog()
    trades.append(TradeLogEntry(seq=1, ts=TS, action=TradeAction.FILLED,
                                order_id='PLU-00000009', ticker='FPT',
                                fill_quantity=100))
    logs = RunLogs(trades=trades, cash=CashLog(), settlement=SettlementLog())
    outcome = order_lifecycle(FakeSession(), logs)
    assert not outcome.passed
    assert outcome.breaches[0]['order_id'] == 'PLU-00000009'


def test_order_lifecycle_fails_on_an_accepted_order_the_book_forgot():
    trades = TradeLog()
    trades.append(TradeLogEntry(seq=1, ts=TS, action=TradeAction.ACCEPTED,
                                order_id='PLU-00000001', ticker='FPT'))
    logs = RunLogs(trades=trades, cash=CashLog(), settlement=SettlementLog())
    outcome = order_lifecycle(FakeSession(), logs)
    assert not outcome.passed
    assert outcome.breaches[0]['what'] == 'accepted order absent from the book'


# --------------------------------------------------------------------------
# Segregation and the deposit trail
# --------------------------------------------------------------------------

def test_deposit_segregation_fails_on_a_transfer_that_lands_nowhere():
    """One pool debited, the other not credited.

    There is no auto-transfer in Vietnam, so the pair must be explicit and
    must balance.
    """
    cash = CashLog()
    cash.append(CashLogEntry(seq=1, ts=TS, pool='securities',
                             movement=CashMovement.TRANSFER_OUT,
                             amount=Decimal('-1000'), cause='transfer'))
    logs = RunLogs(trades=TradeLog(), cash=cash, settlement=SettlementLog())
    outcome = deposit_segregation(FakeSession(), logs)
    assert not outcome.passed
    assert outcome.breaches[0]['what'] == 'unmatched transfer'


def test_deposit_segregation_passes_on_a_matched_pair():
    cash = CashLog()
    cash.append(CashLogEntry(seq=1, ts=TS, pool='securities',
                             movement=CashMovement.TRANSFER_OUT,
                             amount=Decimal('-1000'), cause='out'))
    cash.append(CashLogEntry(seq=2, ts=TS, pool='derivatives',
                             movement=CashMovement.TRANSFER_IN,
                             amount=Decimal('1000'), cause='in'))
    logs = RunLogs(trades=TradeLog(), cash=cash, settlement=SettlementLog())
    assert deposit_segregation(FakeSession(), logs).passed


def test_deposit_segregation_catches_a_derivatives_charge_on_the_wrong_pool():
    """The auditor's own experiment, which this identity used to survive.

    Four validation scenarios reported ``deposit_segregation`` passing on
    derivatives runs. One of them proved it vacuous by relabelling all three
    of a run's derivatives charge rows ``pool='securities'`` and re-running:
    ``passed=True, breaches=()``. The join needs ``charge_kind`` and
    ``fill_id``, and ``drain_deposit`` wrote neither, so the loop body had
    never executed on a derivatives charge in the history of the suite.

    Both halves are pinned here: the row is found (so the join works) and the
    mismatch is reported (so the clause bites).
    """
    charge = FakeCharge()
    cash = CashLog()
    cash.append(CashLogEntry(
        seq=1, ts=TS, pool='securities',            # <- the relabelling
        movement=CashMovement.CHARGE_DEBITED, amount=Decimal('-2550'),
        cause='charges on FILL-1: vsdc_derivatives_clearing',
        charge_kind=charge.kind, fill_id=charge.fill_id,
        detail={'pool': 'derivatives'}))
    logs = RunLogs(trades=TradeLog(), cash=cash, settlement=SettlementLog())

    outcome = deposit_segregation(FakeSession(charges=(charge,)), logs)
    assert not outcome.passed
    what = {b['what'] for b in outcome.breaches}
    assert 'charge logged against the wrong pool' in what
    assert 'derivatives charge paid from securities cash' in what


def test_deposit_segregation_catches_a_charge_with_no_cash_row_at_all():
    """An unmatched charge used to be indistinguishable from a matched one.

    The old loop iterated the rows a charge joined to and reported nothing
    when there were none, so a charge that moved money and produced no cash
    row -- the shape a broken journal actually has -- passed silently.
    """
    logs = RunLogs(trades=TradeLog(), cash=CashLog(), settlement=SettlementLog())
    outcome = deposit_segregation(FakeSession(charges=(FakeCharge(),)), logs)
    assert not outcome.passed
    assert outcome.breaches[0]['what'] == 'charge with no cash row'
    assert outcome.breaches[0]['kind'] == 'vsdc_derivatives_clearing'


def test_deposit_segregation_passes_when_the_charge_is_on_its_own_pool():
    """The control: a correctly logged derivatives charge is not a breach."""
    charge = FakeCharge()
    cash = CashLog()
    cash.append(CashLogEntry(
        seq=1, ts=TS, pool='derivatives',
        movement=CashMovement.CHARGE_DEBITED, amount=Decimal('-2550'),
        cause='charges on FILL-1: vsdc_derivatives_clearing',
        charge_kind=charge.kind, fill_id=charge.fill_id,
        detail={'pool': 'derivatives'}))
    logs = RunLogs(trades=TradeLog(), cash=cash, settlement=SettlementLog())
    assert deposit_segregation(FakeSession(charges=(charge,)), logs).passed


# --------------------------------------------------------------------------
# Settlement completeness -- the identity that did not exist
# --------------------------------------------------------------------------

def _settlement_log(*entries):
    log = SettlementLog()
    for entry in entries:
        log.append(entry)
    return RunLogs(trades=TradeLog(), cash=CashLog(), settlement=log)


def test_settlement_completeness_catches_a_tranche_due_and_never_delivered():
    """46,072,026d created as an obligation and never delivered.

    The measured case: sell 1,000 HPG on 2022-02-14 with the cash tranche
    promised for 2022-02-17 09:00, stop the run on 2022-02-15. The money is
    owed, it never arrives, ``session.cash().pending_total`` reads
    46,072,026 -- and the audit reported **nine of nine held**, because none
    of the nine identities read ``unsettled_at_end()`` or compared
    ``settled_at`` to ``settles_at``.
    """
    due = datetime(2022, 2, 17, 9, 0)
    logs = _settlement_log(SettlementLogEntry(
        seq=1, ts=datetime(2022, 2, 14, 14, 45),
        action=SettlementAction.TRANCHE_CREATED, leg='cash', pool='securities',
        amount=Decimal('46072026'), settles_at=due))

    late = settlement_completeness(logs, datetime(2022, 2, 18, 14, 45))
    assert not late.passed
    assert late.breaches[0]['what'] == 'tranche due and never settled'
    assert late.breaches[0]['amount'] == Decimal('46072026')

    # Stopping the run BEFORE the promised instant is not a breach: the run
    # ended first, and the tranche is correctly still open.
    early = settlement_completeness(logs, datetime(2022, 2, 15, 14, 45))
    assert early.passed


def test_settlement_completeness_catches_a_tranche_delivered_early():
    """Money spendable before DVP is the direction that flatters a backtest."""
    due = datetime(2022, 2, 17, 9, 0)
    logs = _settlement_log(
        SettlementLogEntry(
            seq=1, ts=datetime(2022, 2, 14, 14, 45),
            action=SettlementAction.TRANCHE_CREATED, leg='cash',
            pool='securities', amount=Decimal('100'), settles_at=due),
        SettlementLogEntry(
            seq=2, ts=datetime(2022, 2, 16, 9, 0),
            action=SettlementAction.TRANCHE_SETTLED, leg='cash',
            pool='securities', amount=Decimal('100'), settles_at=due,
            settled_at=datetime(2022, 2, 16, 9, 0)))     # a day early

    outcome = settlement_completeness(logs, datetime(2022, 2, 18, 14, 45))
    assert not outcome.passed
    assert outcome.breaches[0]['what'] == 'tranche settled before its DVP instant'


def test_settlement_completeness_passes_on_a_clean_cycle():
    """The control: created, then settled on its own instant."""
    due = datetime(2022, 2, 17, 9, 0)
    logs = _settlement_log(
        SettlementLogEntry(
            seq=1, ts=datetime(2022, 2, 14, 14, 45),
            action=SettlementAction.TRANCHE_CREATED, leg='cash',
            pool='securities', amount=Decimal('100'), settles_at=due),
        SettlementLogEntry(
            seq=2, ts=due, action=SettlementAction.TRANCHE_SETTLED,
            leg='cash', pool='securities', amount=Decimal('100'),
            settles_at=due, settled_at=due))
    assert settlement_completeness(logs, datetime(2022, 2, 18, 14, 45)).passed


def test_a_skipped_encumbrance_check_is_marked_skipped_not_merely_passed():
    """A skip and a pass used to be indistinguishable in the headline.

    Measured: a run ending with one order live and 47,233,456d of committed
    cash printed ``identities 9/9 held``, because ``encumbrance_zero``
    returned ``passed=True, detail='not applicable'``. ``passed`` stays True
    so a skip cannot fail an otherwise sound run; ``skipped`` is what makes
    the difference visible.
    """
    live = FakeRecord(order_id='PLU-1', terminal=False)
    session = FakeSession(records=(live,),
                          cash=FakeCash(committed=Decimal('47233456')))
    outcome = encumbrance_zero(session)
    assert outcome.passed
    assert outcome.skipped
    assert 'not applicable' in outcome.detail

    # And a run with nothing live really is checked.
    checked = encumbrance_zero(FakeSession(cash=FakeCash()))
    assert checked.passed and not checked.skipped


def test_deposit_balance_trail_fails_when_a_movement_bypassed_the_trail():
    """The balance is right and the audit trail is short.

    That is the one failure a deposit journal cannot survive, because the
    trail is the only record of *why* the balance moved.
    """
    session = FakeSession(account=FakeAccount(entries=(),
                                              balance=Decimal('100')))
    outcome = deposit_balance_trail(session)
    assert not outcome.passed
    assert outcome.difference == Decimal('-100')
