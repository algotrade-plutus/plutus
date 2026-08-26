"""The three log containers, in isolation.

These pin the shapes an audit reads: that a Decimal survives rendering, that
the conservation term is the one the identity uses, and that a tranche created
and never settled is reported as such rather than assumed settled.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from validation.logs import (
    CashLog, CashLogEntry, CashMovement, RunLogs, SettlementAction,
    SettlementLog, SettlementLogEntry, TradeAction, TradeLog, TradeLogEntry,
    json_safe,
)

TS = datetime(2024, 6, 3, 9, 30)


def cash_row(seq, movement, amount, *, affects=True, pool='securities'):
    return CashLogEntry(seq=seq, ts=TS, pool=pool, movement=movement,
                        amount=Decimal(amount), cause='test',
                        affects_balance=affects)


def test_a_decimal_is_rendered_as_a_string_not_a_float():
    """A rounded price in an audit log is a defect.

    ``Event.to_dict`` deliberately renders ``Decimal`` as ``float`` and says
    so; that is right for a debug dump and wrong here, so this module does not
    reuse it. 0.1 is the standard witness: ``float(Decimal('0.1'))`` is not
    0.1.
    """
    row = cash_row(1, CashMovement.BUY_CONSIDERATION, '-0.1').to_row()
    assert row['amount'] == '-0.1'
    assert not isinstance(row['amount'], float)


def test_json_safe_leaves_no_decimal_enum_or_datetime_behind():
    payload = json_safe({'a': Decimal('1.5'), 'b': TS,
                         'c': [CashMovement.CHARGE_DEBITED],
                         'd': {'e': Decimal('2')}})
    assert payload == {'a': '1.5', 'b': TS.isoformat(),
                       'c': ['charge_debited'], 'd': {'e': '2'}}


def test_net_excludes_the_rows_that_do_not_move_a_settled_balance():
    """The conservation term is balance-moving rows only.

    Pending sale proceeds, a charge withheld at source, an advance drawn and
    interest accrued are real cash events that do not move a settled balance.
    Counting them would make the identity fail on every sale.
    """
    log = CashLog()
    log.append(cash_row(1, CashMovement.OPENING_BALANCE, '1000'))
    log.append(cash_row(2, CashMovement.SALE_PROCEEDS_PENDING, '500',
                        affects=False))
    log.append(cash_row(3, CashMovement.CHARGE_WITHHELD, '-5', affects=False))
    log.append(cash_row(4, CashMovement.BUY_CONSIDERATION, '-200'))
    assert log.net('securities') == Decimal('800')
    assert log.net('securities', only_effective=False) == Decimal('1295')


def test_by_movement_itemises_every_cause():
    log = CashLog()
    log.append(cash_row(1, CashMovement.CHARGE_DEBITED, '-10'))
    log.append(cash_row(2, CashMovement.CHARGE_DEBITED, '-15'))
    log.append(cash_row(3, CashMovement.SETTLEMENT_CREDIT, '100'))
    assert log.by_movement('securities') == {
        CashMovement.CHARGE_DEBITED: Decimal('-25'),
        CashMovement.SETTLEMENT_CREDIT: Decimal('100'),
    }


def test_a_tranche_created_and_never_settled_is_reported():
    """Matched on the tranche's economic identity, not on object identity.

    A settlement log that assumed every created tranche settled would hide the
    one failure it exists to catch.
    """
    log = SettlementLog()
    log.append(SettlementLogEntry(
        seq=1, ts=TS, action=SettlementAction.TRANCHE_CREATED,
        leg='securities', pool='securities', ticker='FPT', quantity=1000,
        settles_at=datetime(2024, 6, 5, 13, 0)))
    log.append(SettlementLogEntry(
        seq=2, ts=TS, action=SettlementAction.TRANCHE_CREATED,
        leg='securities', pool='securities', ticker='HPG', quantity=500,
        settles_at=datetime(2024, 6, 6, 13, 0)))
    log.append(SettlementLogEntry(
        seq=3, ts=datetime(2024, 6, 5, 13, 0),
        action=SettlementAction.TRANCHE_SETTLED, leg='securities',
        pool='securities', ticker='FPT', quantity=1000,
        settles_at=datetime(2024, 6, 5, 13, 0),
        settled_at=datetime(2024, 6, 5, 13, 0)))
    outstanding = log.unsettled_at_end()
    assert [e.ticker for e in outstanding] == ['HPG']


def test_two_identical_tranches_are_not_discharged_by_one_settlement():
    """The key was a set, so one settlement closed two obligations.

    Not hypothetical: ``order_cycle``'s ``partial_fill_then_cancel`` creates
    exactly this pair -- two ``HoldingTranche(65000, settles 2022-11-14 13:00,
    PLU-00000001)`` from one order. With 2 created and 1 settled,
    ``unsettled_at_end()`` returned **0**, so the one tool an auditor reaches
    for to answer "was a tranche created and never settled" answered "no" over
    a log that said "yes".
    """
    log = SettlementLog()
    due = datetime(2024, 6, 5, 13, 0)
    for seq in (1, 2):
        log.append(SettlementLogEntry(
            seq=seq, ts=TS, action=SettlementAction.TRANCHE_CREATED,
            leg='securities', pool='securities', ticker='HPG', quantity=65000,
            settles_at=due, order_id='PLU-00000001'))
    log.append(SettlementLogEntry(
        seq=3, ts=due, action=SettlementAction.TRANCHE_SETTLED,
        leg='securities', pool='securities', ticker='HPG', quantity=65000,
        settles_at=due, settled_at=due, order_id='PLU-00000001'))

    outstanding = log.unsettled_at_end()
    assert len(outstanding) == 1, 'one of the two pairs is still owed'
    assert outstanding[0].quantity == 65000


def test_a_rescaled_tranche_is_not_reported_as_an_orphan():
    """A corporate action changes the quantity the key is built on.

    ``HoldingsLedger.apply_corporate_action`` rescales a parcel in place and
    preserves its ``settles_at``. Measured on the corporate-charges run: 1,500
    created, 2,025 settled, and the log therefore showed one tranche created
    and never settled **and** one settled that was never created -- an orphan
    and a ghost, on a run the scenario calls correct. The ``TRANCHE_ADJUSTED``
    row is the bridge between the two keys.
    """
    log = SettlementLog()
    due = datetime(2021, 6, 2, 9, 0)
    log.append(SettlementLogEntry(
        seq=1, ts=TS, action=SettlementAction.TRANCHE_CREATED,
        leg='securities', pool='securities', ticker='HPG', quantity=1500,
        settles_at=due))
    log.append(SettlementLogEntry(
        seq=2, ts=TS, action=SettlementAction.TRANCHE_ADJUSTED,
        leg='securities', pool='securities', ticker='HPG', quantity=2025,
        settles_at=due, detail={'quantity_before': 1500,
                                'factor': Decimal('1.35')}))
    log.append(SettlementLogEntry(
        seq=3, ts=due, action=SettlementAction.TRANCHE_SETTLED,
        leg='securities', pool='securities', ticker='HPG', quantity=2025,
        settles_at=due, settled_at=due))

    assert log.unsettled_at_end() == ()

    # Without the bridging row both halves are reported, which is what the
    # log actually said before it existed.
    naive = SettlementLog()
    for entry in (log.entries[0], log.entries[2]):
        naive.append(entry)
    assert [e.quantity for e in naive.unsettled_at_end()] == [1500]


def test_a_log_refuses_the_wrong_entry_type():
    """Three logs, three row types. A mixed log cannot be reconciled."""
    with pytest.raises(TypeError):
        TradeLog().append(cash_row(1, CashMovement.CHARGE_DEBITED, '-1'))


def test_for_order_returns_one_order_s_whole_history():
    log = TradeLog()
    for seq, (action, oid) in enumerate([
            (TradeAction.SUBMITTED, None),
            (TradeAction.ACCEPTED, 'PLU-00000001'),
            (TradeAction.FILLED, 'PLU-00000001'),
            (TradeAction.ACCEPTED, 'PLU-00000002')], start=1):
        log.append(TradeLogEntry(seq=seq, ts=TS, action=action, order_id=oid))
    assert [e.action for e in log.for_order('PLU-00000001')] == [
        TradeAction.ACCEPTED, TradeAction.FILLED]
    assert log.order_ids == ('PLU-00000001', 'PLU-00000002')


def test_run_logs_render_all_three_under_stable_keys():
    logs = RunLogs(trades=TradeLog(), cash=CashLog(),
                   settlement=SettlementLog())
    assert set(logs.to_dict()) == {'trade_log', 'cash_log', 'settlement_log'}
    assert logs.counts() == {'trade_log': 0, 'cash_log': 0,
                             'settlement_log': 0, 'events': 0}
