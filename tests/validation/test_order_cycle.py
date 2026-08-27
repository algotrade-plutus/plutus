"""The order-lifecycle scenario, asserted against the three logs.

Every assertion here reads a row the simulator wrote. Nothing is recomputed:
if a fill price is wrong it is wrong in ``ExchangeSession``, and this file's
job is to make that visible rather than to agree with it.

The whole scenario runs **once** per test session -- twenty-odd runs over the
Parquet corpus -- and every test reads out of that one dictionary. Splitting
it per test would multiply the corpus reads by twenty for no extra coverage.

Four tests deliberately pin behaviour the scenario report calls **defective**:
:func:`test_instrument_expiry_trigger_has_no_producer`,
:func:`test_an_hnx_day_order_is_stamped_at_1500_not_the_atc`,
:func:`test_a_definite_no_fill_leaves_no_row_in_any_log` and
:func:`test_a_cancellation_is_written_to_the_trade_log_twice`. They assert the
behaviour as it is, and each says in its own docstring what the right answer
would be, so that a later fix breaks the test rather than passing unnoticed.
"""

from datetime import date, datetime, time
from decimal import Decimal

import pytest

from conftest import requires_corpus

from plutus.market.protocol import SessionPhase
from plutus.market.session.rulebook import Rulebook
from plutus.market.session.types import (
    DataField, ExpiryTrigger, TERMINAL_TRIGGERS_BY_TIF, TimeInForce, Venue,
)

from validation.logs import CashMovement, SettlementAction, TradeAction
from validation.scenarios import bars as bars_module
from validation.scenarios.order_cycle import (
    DepthProxyFillPolicy, adapter_gap, build_source, combined_identities,
    lock_proxy_divergence, partial_fill_then_cancel, run_all, unterminated,
)

pytestmark = requires_corpus


# --------------------------------------------------------------------------
# One run of everything
# --------------------------------------------------------------------------

@pytest.fixture(scope='module')
def runs():
    return run_all(build_source())


@pytest.fixture(scope='module')
def chained():
    return partial_fill_then_cancel(build_source())


def _one(result, action):
    rows = [e for e in result.logs.trades if e.action is action]
    assert len(rows) == 1, f'expected one {action.value} row, got {len(rows)}'
    return rows[0]


def _by_rule(result):
    return {e.rule: e for e in result.logs.trades
            if e.action is TradeAction.REJECTED}


# --------------------------------------------------------------------------
# The scenario as a whole
# --------------------------------------------------------------------------

def test_every_leg_runs_and_holds_every_identity(runs):
    """No leg raises, and all nine ledger identities hold in all of them."""
    for name, result in runs.items():
        assert result.error is None, f'{name} raised: {result.error!r}'
        assert not result.failed_identities, (
            f'{name}: ' + ', '.join(r.name for r in result.failed_identities))


def test_every_accepted_order_reaches_a_terminal_state(runs):
    """The lifecycle claim. One leg is exempt, and says why in its name."""
    expected_live = {'noon-break-expires-nothing'}
    for name, result in runs.items():
        live = unterminated(result)
        if name in expected_live:
            assert live, (f'{name} exists to show an order surviving a phase '
                          f'boundary, and none survived')
            continue
        assert not live, f'{name} left {live} live at the end of the run'


def test_the_run_covers_every_vietnamese_order_type(runs):
    """All six types are submitted somewhere, and each carries its own TIF."""
    seen = {}
    for result in runs.values():
        for entry in result.logs.trades:
            if entry.action is TradeAction.SUBMITTED:
                seen[entry.order_type] = entry.time_in_force
    assert seen == {
        'LO': 'day',
        'ATO': 'auction_only',
        'ATC': 'auction_only',
        'MOK': 'fill_or_kill',
        'MAK': 'immediate_or_cancel',
        'MTL': 'immediate_then_day',
    }


def test_every_terminal_trigger_the_run_can_reach_is_reached(runs):
    """Which ``ExpiryTrigger`` members the assembled system actually emits."""
    triggers = {e.trigger for result in runs.values()
                for e in result.logs.trades
                if e.action is TradeAction.EXPIRED}
    assert triggers == {
        ExpiryTrigger.SESSION_END.value,
        ExpiryTrigger.AUCTION_CROSS.value,
        ExpiryTrigger.NOT_FILLABLE_IN_FULL.value,
        ExpiryTrigger.IMMEDIATE_REMAINDER.value,
    }


def test_no_leg_leaks_a_reservation(runs):
    """Closing committed cash, resting margin and live orders are all zero.

    ``encumbrance_zero`` reports "not applicable" when an order is still
    live, so on the one leg that ends with a live order it would pass without
    checking anything. This asserts the balances directly, and asserts that
    the one exception holds exactly the reservation its live order took:
    1,000 shares at 12.30 is 12,300,000, plus HOSE's 0.027% exchange service
    charge of 3,321.
    """
    for name, result in runs.items():
        last = result.snapshots[-1]
        if name == 'noon-break-expires-nothing':
            assert last.live_orders == 1
            assert last.committed_cash == Decimal('12303321.00')
            continue
        assert last.live_orders == 0, name
        assert last.committed_cash == Decimal('0'), name
        assert last.resting_order_margin == Decimal('0'), name


def test_no_fill_is_priced_outside_the_days_band(runs):
    """A price the exchange could not have printed is a fidelity failure.

    Checked against the corpus's own published ceiling and floor for the
    ticker-day the fill is stamped with, for every fill in every leg.
    """
    source = build_source()
    for name, result in runs.items():
        for entry in result.logs.trades:
            if entry.fill_price is None or entry.ticker is None:
                continue
            state = source.state_at(entry.ticker, entry.ts)
            assert state is not None, f'{name}: no bar for {entry.ticker}'
            assert state.floor <= entry.fill_price <= state.ceiling, (
                f'{name}: {entry.ticker} filled at {entry.fill_price} '
                f'outside {state.floor}..{state.ceiling}')


def test_the_cash_log_balance_trail_is_continuous(runs):
    """Every ``balance_after`` equals the running sum of what came before it.

    ``cash_conservation`` only checks the total, so a row carrying the wrong
    running balance would pass it. This is the securities equivalent of
    ``deposit_balance_trail``, which the deposit already has and the cash
    ledger does not.
    """
    for name, result in runs.items():
        for pool in ('securities', 'derivatives'):
            running = None
            for entry in result.logs.cash:
                if entry.pool != pool or not entry.affects_balance:
                    continue
                running = entry.amount if running is None else (
                    running + entry.amount)
                if entry.balance_after is not None:
                    assert entry.balance_after == running, (
                        f'{name}/{pool} seq {entry.seq} '
                        f'({entry.movement.value}): trail says '
                        f'{entry.balance_after}, sum says {running}')


# --------------------------------------------------------------------------
# LO -- the four terminal edges of a day order
# --------------------------------------------------------------------------

def test_a_day_lo_fills_where_the_market_traded_through_it(runs):
    """HPG 2022-11-09 traded down to 12.95; a buy at 13.50 is unavoidable."""
    row = _one(runs['lo-filled'], TradeAction.FILLED)
    assert row.ticker == 'HPG'
    assert row.order_type == 'LO' and row.time_in_force == 'day'
    assert row.fill_quantity == 1000 and row.remaining == 0
    assert row.fill_price == Decimal('13.50')
    assert row.evidence == 'traded_through'
    assert row.ts == datetime(2022, 11, 9, 9, 25)


def test_a_day_lo_the_market_never_reached_dies_at_the_session_end(runs):
    """12.30 is below HPG's 12.95 low, so this is a definite no-fill.

    The stamp is 14:45 -- HOSE's ATC close, the end of its last matching
    phase -- and not 09:25, the instant the session noticed.
    """
    result = runs['lo-expired-session-end']
    assert not [e for e in result.logs.trades
                if e.action is TradeAction.FILLED]
    row = _one(result, TradeAction.EXPIRED)
    assert row.trigger == ExpiryTrigger.SESSION_END.value
    assert row.ts == datetime(2022, 11, 9, 14, 45)
    assert row.quantity == 1000
    assert result.indeterminate.indeterminate == 0


def test_a_resting_lo_can_be_cancelled_in_the_continuous_session(runs):
    result = runs['lo-cancelled']
    rows = [e for e in result.logs.trades
            if e.action is TradeAction.CANCELLED]
    assert rows, 'no cancellation reached the trade log'
    assert not [e for e in result.logs.trades
                if e.action is TradeAction.CANCEL_REFUSED]


def test_a_cancellation_inside_the_closing_auction_is_refused(runs):
    """The auction lock covers the whole 14:30-14:45 window, not the cross.

    Refused on ``SESSION_SEMANTICS``, and the reason cites VNX QD 22/2025
    Dieu 21.4 and flags the pre-KRX reading as UNVERIFIED.
    """
    result = runs['cancel-refused-in-auction']
    row = _one(result, TradeAction.CANCEL_REFUSED)
    assert row.rule == 'session_semantics'
    assert row.detail['phase'] == 'closing_auction'
    assert 'locked' in row.detail['reason']
    # The order it could not cancel then died as an ordinary day order.
    assert _one(result, TradeAction.EXPIRED).trigger == 'session_end'


# --------------------------------------------------------------------------
# ATO and ATC -- the order type IS the time-in-force
# --------------------------------------------------------------------------

def test_an_ato_fills_at_the_published_open(runs):
    """HPG opened at 13.10 on 2022-11-08. That is the ATO cross on HOSE."""
    row = _one(runs['ato-filled-at-open'], TradeAction.FILLED)
    assert row.order_type == 'ATO' and row.time_in_force == 'auction_only'
    assert row.fill_price == Decimal('13.1')
    assert row.evidence == 'auction_price'
    assert row.ts == datetime(2022, 11, 8, 9, 10)


def test_an_atc_fills_at_the_published_close(runs):
    """HPG closed at 13.15 on 2022-11-08. That is the ATC cross on HOSE."""
    row = _one(runs['atc-filled-at-close'], TradeAction.FILLED)
    assert row.order_type == 'ATC' and row.time_in_force == 'auction_only'
    assert row.fill_price == Decimal('13.15')
    assert row.evidence == 'auction_price'
    assert row.ts == datetime(2022, 11, 8, 14, 40)


@pytest.mark.parametrize('leg,order_type', [
    ('ato-expired-at-cross', 'ATO'),
    ('atc-expired-at-cross', 'ATC'),
])
def test_an_unmatched_auction_order_evaporates_at_its_cross(runs, leg,
                                                            order_type):
    """It never rests and never carries: the trigger is ``AUCTION_CROSS``.

    Under ``hard`` the cross cannot be *sized* -- the corpus publishes no
    per-auction volume -- so the order is INDETERMINATE at the cross and then
    swept at the day's close. Both rows are asserted, because the sweep alone
    would not show that the policy declined to decide rather than deciding no.
    """
    result = runs[leg]
    undecided = _one(result, TradeAction.INDETERMINATE)
    assert undecided.missing_fields == ('volume',)
    row = _one(result, TradeAction.EXPIRED)
    assert row.order_type == order_type
    assert row.trigger == ExpiryTrigger.AUCTION_CROSS.value
    assert row.ts == datetime(2022, 11, 8, 14, 45)
    assert row.quantity == 1000


# --------------------------------------------------------------------------
# MOK, MAK, MTL -- the immediate families
# --------------------------------------------------------------------------

def test_an_mok_inside_the_cap_fills_in_full(runs):
    """PVS traded 7,652,900 shares on 2022-11-08; 1,000 is well inside 10%."""
    row = _one(runs['mok-filled-in-full'], TradeAction.FILLED)
    assert row.order_type == 'MOK' and row.time_in_force == 'fill_or_kill'
    assert row.fill_quantity == 1000 and row.remaining == 0
    assert row.venue == 'HNX'


def test_an_mok_that_cannot_fill_in_full_is_killed_entirely(runs):
    """Fill-or-kill has no partial: 765,200 of 2,000,000 is a kill, not a fill.

    The cap is 10% of the day's 7,652,900 shares. ``_sized_fill`` returns
    ``NO_FILL`` for a fill-or-kill order the cap cannot fill whole, and
    ``_decide_immediates`` then expires it with the only trigger locked
    shape 4 gives this time-in-force.
    """
    result = runs['mok-killed-not-fillable-in-full']
    assert not [e for e in result.logs.trades
                if e.action in (TradeAction.FILLED,
                                TradeAction.PARTIALLY_FILLED)]
    row = _one(result, TradeAction.EXPIRED)
    assert row.trigger == ExpiryTrigger.NOT_FILLABLE_IN_FULL.value
    assert row.quantity == 2_000_000
    assert row.detail['filled_quantity'] == 0


def test_an_mak_keeps_its_fill_and_kills_the_rest_at_once(runs):
    """765,200 filled, 1,234,800 killed, both stamped at the same instant."""
    result = runs['mak-partial-then-remainder-killed']
    part = _one(result, TradeAction.PARTIALLY_FILLED)
    assert part.fill_quantity == 765_200
    assert part.remaining == 1_234_800
    assert part.fill_price == Decimal('23.0')
    row = _one(result, TradeAction.EXPIRED)
    assert row.trigger == ExpiryTrigger.IMMEDIATE_REMAINDER.value
    assert row.quantity == 1_234_800
    assert row.ts == part.ts
    assert 765_200 + 1_234_800 == 2_000_000


def test_an_mtl_residue_converts_to_a_resting_limit_one_tick_beyond(runs):
    """VNX QD 22/2025 Dieu 17.2(b): buy residue rests at last match + 1 tick.

    PVS matched at 23.0 and HNX's stock tick is 0.1, so the residue rests at
    **23.1**. The row's ``order_type`` becomes ``LO`` while its
    ``time_in_force`` stays ``immediate_then_day`` -- which is the whole
    reason that time-in-force exists.
    """
    result = runs['mtl-residue-converts-and-rests']
    part = _one(result, TradeAction.PARTIALLY_FILLED)
    assert part.fill_quantity == 765_200
    assert part.fill_price == Decimal('23.0')
    assert part.order_type == 'LO'
    assert part.time_in_force == 'immediate_then_day'
    assert part.limit_price == Decimal('23.1')
    row = _one(result, TradeAction.EXPIRED)
    assert row.trigger == ExpiryTrigger.SESSION_END.value
    assert row.limit_price == Decimal('23.1')
    assert row.quantity == 1_234_800


def test_hose_takes_the_same_order_under_the_pre_krx_mp_mnemonic(runs):
    """HOSE accepted no MTL before 2025-05-05 and did accept MP.

    The rulebook maps both mnemonics to one ``OrderType`` -- "same economics,
    new mnemonic" -- so the identical submission is legal on HOSE in 2022 and
    the residue rule applies there too, at HOSE's 0.05 tick rather than HNX's
    0.1. NVL traded 29,300 shares on 2022-11-14, so a 10% cap sizes 2,930 and
    the round lot floors it to 2,900.
    """
    result = runs['mp-on-hose-residue-converts']
    part = _one(result, TradeAction.PARTIALLY_FILLED)
    assert part.venue == 'HSX'
    assert part.fill_quantity == 2900
    assert part.fill_price == Decimal('38.95')
    assert part.limit_price == Decimal('39.00')     # 38.95 + one 0.05 tick
    assert part.remaining == 97_100
    row = _one(result, TradeAction.EXPIRED)
    assert row.trigger == ExpiryTrigger.SESSION_END.value
    assert row.ts == datetime(2022, 11, 14, 14, 45)


def test_the_trade_log_names_the_order_type_and_not_the_dated_mnemonic(runs):
    """A 2022 HOSE market order is logged as ``MTL``, a name HOSE did not use.

    ``TradeLogEntry.order_type`` carries ``OrderType.value``, and the
    rulebook's own refusal detail on the same run carries both -- ``accepts:
    ['LO', 'MTL']`` beside ``mnemonics: ['LO', 'MP']``. A confirmation from a
    Vietnamese broker in 2022 would say MP. Cosmetic against the ledger and
    not against a log an auditor reads, so it is recorded here rather than
    corrected in a shared file.
    """
    submitted = [e for e in runs['mp-on-hose-residue-converts'].logs.trades
                 if e.action is TradeAction.SUBMITTED][0]
    assert submitted.order_type == 'MTL'
    refusal = [e for e in runs['phase-refusals-continuous'].logs.trades
               if e.action is TradeAction.REJECTED][0]
    assert refusal.detail['mnemonics'] == ['LO', 'MP']
    assert 'MTL' in refusal.detail['accepts']


def test_upcom_accepts_a_limit_order_and_nothing_else(runs):
    """One rulebook row, every phase, every date: LO only.

    BSR's band on 2022-11-09 is 19.5 / 14.5 about a 17.0 reference -- +/-15%
    on a 0.1 tick, which is UPCoM's and not HOSE's.
    """
    result = runs['upcom-accepts-only-lo']
    filled = _one(result, TradeAction.FILLED)
    assert filled.venue == 'UPCOM' and filled.order_type == 'LO'
    refused = {e.order_type: e for e in result.logs.trades
               if e.action is TradeAction.REJECTED}
    assert set(refused) == {'MTL', 'ATC'}
    for entry in refused.values():
        assert entry.rule == 'session_semantics'
        assert entry.detail['accepts'] == ['LO']
        assert entry.detail['mnemonics'] == ['LO']


# --------------------------------------------------------------------------
# Admission
# --------------------------------------------------------------------------

def test_admission_refuses_each_rule_with_the_number_that_bound(runs):
    """Six refusals, six distinct rules, each carrying its binding constraint.

    HPG on 2022-11-09: reference 13.15, ceiling 14.05, floor 12.25, and the
    HOSE tick at that price is 0.05.
    """
    by_rule = _by_rule(runs['admission-refusals'])
    assert by_rule['tick_grid'].binding_constraint == Decimal('0.05')
    assert by_rule['tick_grid'].limit_price == Decimal('13.02')
    assert by_rule['round_lot'].binding_constraint == 100
    assert by_rule['round_lot'].quantity == 150
    assert by_rule['insufficient_cash'].binding_constraint == Decimal(
        '100000000')

    bands = [e for e in runs['admission-refusals'].logs.trades
             if e.rule == 'band_limit']
    assert {e.detail['side'] for e in bands} == {'above_ceiling',
                                                 'below_floor'}
    assert {e.binding_constraint for e in bands} == {Decimal('14.05'),
                                                     Decimal('12.25')}

    size = [e for e in runs['admission-refusals'].logs.trades
            if e.rule == 'session_semantics'
            and e.detail.get('max_order_size')][0]
    assert size.binding_constraint == 500_000
    assert size.quantity == 600_000


def test_every_admission_refusal_is_a_rejected_verdict_not_a_data_gap(runs):
    """A rule saying no and the data not deciding must not be conflated."""
    for entry in runs['admission-refusals'].logs.trades:
        if entry.action is TradeAction.REJECTED:
            assert entry.verdict == 'rejected'


def test_the_dated_order_type_table_refuses_by_phase_and_by_venue(runs):
    """HOSE accepts LO and MP only, in the continuous session, pre-KRX."""
    refused = {e.order_type: e for e in runs['phase-refusals-continuous']
               .logs.trades if e.action is TradeAction.REJECTED}
    assert set(refused) == {'ATO', 'ATC', 'MOK', 'MAK'}
    for entry in refused.values():
        assert entry.rule == 'session_semantics'
        assert entry.detail['phase'] == 'continuous'
        assert entry.detail['accepts'] == ['LO', 'MTL']
        assert entry.detail['mnemonics'] == ['LO', 'MP']


@pytest.mark.parametrize('leg,phase', [
    ('phase-refusals-noon', 'noon_break'),
    ('phase-refusals-pre-open', 'pre_open'),
])
def test_a_phase_that_does_not_match_accepts_nothing(runs, leg, phase):
    row = _one(runs[leg], TradeAction.REJECTED)
    assert row.rule == 'session_semantics'
    assert row.detail['phase'] == phase
    assert row.detail['accepts'] == []


def test_the_noon_break_expires_nothing(runs):
    """11:30-13:00 stops instructions, not the book.

    The order is submitted at 11:00, the clock crosses into the break, and
    the order is still live at 12:00. This is the one leg that is *supposed*
    to end with a live order.
    """
    result = runs['noon-break-expires-nothing']
    assert not [e for e in result.logs.trades
                if e.action is TradeAction.EXPIRED]
    close = [s for s in result.snapshots if s.phase == 'close'][-1]
    assert close.ts == datetime(2022, 11, 9, 12, 0)
    assert close.live_orders == 1


def test_only_the_locked_side_of_a_locked_band_is_refused(runs):
    """NVL 2022-11-14: open == high == low == close == floor == 38.95.

    A sale at the floor cannot cross a floor lock and is refused
    ``BAND_LOCK``; a purchase at the same price is the unlocked side and is
    admitted. The refusal carries ``lock_evidence='bar_proxy'`` -- the lock is
    an inference from the bar, and the log says so.
    """
    result = runs['band-lock-refuses-the-locked-side']
    refusal = _one(result, TradeAction.REJECTED)
    assert refusal.rule == 'band_lock'
    assert refusal.side == 'SELL'
    assert refusal.binding_constraint == Decimal('38.95')
    assert refusal.detail['lock_evidence'] == 'bar_proxy'
    accepted = _one(result, TradeAction.ACCEPTED)
    assert accepted.side == 'BUY' and accepted.limit_price == Decimal('38.95')


def test_a_cap_below_one_round_lot_is_a_definite_no_fill(runs):
    """HPX traded 100 shares on 2022-11-14; 10% of that is 10, under a lot.

    The decision is definite -- one evaluation, zero indeterminate -- so the
    order was answered, not skipped. It then died as an ordinary day order.
    """
    result = runs['participation-cap-below-one-lot']
    assert result.indeterminate.evaluations == 1
    assert result.indeterminate.indeterminate == 0
    assert not [e for e in result.logs.trades
                if e.action is TradeAction.FILLED]
    assert _one(result, TradeAction.EXPIRED).trigger == 'session_end'


def test_a_ticker_that_did_not_trade_yields_indeterminate_not_a_no_fill(runs):
    """TDW is quoted every day of the window and matched on none of them.

    The corpus stamps ``open == close == reference`` on a no-trade day; the
    source suppresses those synthetic prints, so the interval carries no
    price and the policy names the three fields it needed.
    """
    result = runs['indeterminate-no-trade']
    row = _one(result, TradeAction.INDETERMINATE)
    assert set(row.missing_fields) == {'close', 'last', 'low'}
    assert result.indeterminate.rate == Decimal('1')


# --------------------------------------------------------------------------
# T+2, and the 13:00 allocation cut
# --------------------------------------------------------------------------

def test_an_unsettled_sale_is_refused_and_says_when_it_becomes_sellable(runs):
    """Buy on 2022-11-08; the shares are not sellable until 11-10 13:00.

    Three refusals: on T before the buy has even filled (nothing held at
    all), on T+1, and on the **morning** of T+2. The second and third carry
    ``sellable_from = 2022-11-10 13:00`` -- the Decision 109 allocation
    deadline, not an end-of-day.
    """
    result = runs['settlement-t2-morning']
    refusals = [e for e in result.logs.trades
                if e.rule == 'unsettled_holding']
    assert [e.ts.date() for e in refusals] == [
        date(2022, 11, 8), date(2022, 11, 9), date(2022, 11, 10)]
    assert refusals[0].detail == {'requested': 1000, 'settled': 0,
                                  'committed': 0, 'unsettled': 0}
    for entry in refusals[1:]:
        assert entry.sellable_from == datetime(2022, 11, 10, 13, 0)
        assert entry.binding_constraint == 0
        assert entry.detail['unsettled'] == 1000

    # ... and the same log carries them in the settlement log too.
    rows = [e for e in result.logs.settlement
            if e.action is SettlementAction.SELL_REFUSED_UNSETTLED]
    assert len(rows) == 3
    assert {e.settlement_rule for e in rows} == {'T+2 at 13:00:00'}

    # The sale finally admitted, and filled.
    sold = _one(result, TradeAction.FILLED) if False else [
        e for e in result.logs.trades
        if e.action is TradeAction.FILLED and e.side == 'SELL']
    assert len(sold) == 1 and sold[0].ts.date() == date(2022, 11, 11)


def test_the_same_sale_is_admitted_after_1300_on_the_settlement_day(runs):
    """The discriminating pair. 09:20 refused, 13:30 admitted, same day.

    An implementation that settled at the close, or at midnight, or ignored
    the time of day, would give the same answer at both instants.
    """
    morning = [e for e in runs['settlement-t2-morning'].logs.trades
               if e.rule == 'unsettled_holding'
               and e.ts.date() == date(2022, 11, 10)]
    assert len(morning) == 1 and morning[0].ts.time() == time(9, 20)

    result = runs['settlement-t2-afternoon']
    assert not [e for e in result.logs.trades
                if e.rule == 'unsettled_holding']
    sells = [e for e in result.logs.trades
             if e.action is TradeAction.ACCEPTED and e.side == 'SELL']
    assert len(sells) == 1
    assert sells[0].ts == datetime(2022, 11, 10, 13, 30)

    settled = [e for e in result.logs.settlement
               if e.action is SettlementAction.TRANCHE_SETTLED
               and e.leg == 'securities']
    assert len(settled) == 1
    assert settled[0].settles_at == datetime(2022, 11, 10, 13, 0)
    assert settled[0].settled_at == datetime(2022, 11, 10, 13, 30)


def test_the_settlement_log_carries_both_dvp_legs_and_the_calendar_id(runs):
    result = runs['settlement-t2-afternoon']
    actions = [(e.action.value, e.leg) for e in result.logs.settlement]
    assert actions == [
        ('tranche_created', 'securities'),
        ('tranche_settled', 'securities'),
        ('tranche_created', 'cash'),
        ('tranche_settled', 'cash'),
    ]
    assert {e.settlement_calendar_id for e in result.logs.settlement} == {
        'weekday-only-UNSOURCED'}


# --------------------------------------------------------------------------
# The derivatives pool
# --------------------------------------------------------------------------

def test_a_futures_order_draws_on_the_segregated_deposit(runs):
    """IM = 0.13 x 2 lots x 960.0 points x 100,000 VND = 24,960,000."""
    accepted = [e for e in runs['futures-lifecycle-to-expiry'].logs.trades
                if e.action is TradeAction.ACCEPTED]
    first = accepted[0]
    assert first.venue == 'HNXDS' and first.pool == 'derivatives'
    reserved = first.detail['encumbrances'][0]
    assert reserved['resource'] == 'deposit'
    assert reserved['pool'] == 'derivatives'
    assert Decimal(reserved['amount']) == Decimal('24960000.000')


def test_a_futures_position_cash_settles_at_expiry_for_the_right_amount(runs):
    """2 lots at 960.0 and 1 at 900.0, settled against a 972.5 close.

    2 x (972.5 - 960.0) x 100,000 + 1 x (972.5 - 900.0) x 100,000
      = 2,500,000 + 7,250,000 = 9,750,000 VND.
    """
    result = runs['futures-lifecycle-to-expiry']
    rows = [e for e in result.logs.settlement
            if e.action is SettlementAction.EXPIRY_SETTLED]
    assert len(rows) == 1
    row = rows[0]
    assert row.ticker == 'VN30F2211'
    assert row.quantity == 3
    assert row.amount == Decimal('9750000.0')
    assert row.detail['settlement_source'] == 'close_proxy'
    assert row.detail['substituted'] is True


def test_a_futures_order_is_refused_on_the_deposit_and_told_how_to_cure_it(
        runs):
    """The pools are segregated, so aggregate funding is not funding.

    The account holds 200,000,000,000 of securities cash and 1,000,000 of
    deposit; the order needs 12,480,000 of deposit. It is refused, and the
    refusal names the shortfall, says the account is funded in aggregate,
    says there is no auto-transfer, and gives the transfer that would cure it.
    """
    row = _one(runs['futures-insufficient-deposit'], TradeAction.REJECTED)
    assert row.rule == 'insufficient_deposit'
    assert row.binding_constraint == Decimal('1000000')
    assert Decimal(row.detail['required']) == Decimal('12480000.000')
    assert Decimal(row.detail['shortfall']) == Decimal('11480000.000')
    assert row.detail['funded_in_aggregate'] is True
    assert row.detail['auto_transfer'] is False
    assert row.detail['short_pool'] == 'derivatives'
    assert 'transfer(securities -> derivatives' in row.detail['cure']


def test_foreign_room_cannot_be_decided_from_this_corpus(runs):
    """A foreign buy is INDETERMINATE, not admitted and not refused.

    Room binds in reality. ``adapters/datahub.py`` hardcodes
    ``foreign_room=None`` and this scenario's source does the same, and the
    reason is a data fact rather than laziness: the Parquet corpus carries
    ``quote_totalforeignroom``, which is the room **limit** (HPG:
    2,849,244,993 shares, constant across all nine sessions), not the
    remaining room. Remaining room is limit minus foreign holding, and the
    corpus has daily foreign *flows* only -- no holding series and no opening
    holding -- so it cannot be reconstructed. Supplying the limit as if it
    were headroom would admit every foreign buy ever submitted.
    """
    row = _one(runs['foreign-room-is-not-in-this-corpus'],
               TradeAction.REJECTED)
    assert row.rule == 'foreign_room'
    assert row.verdict == 'indeterminate'
    assert row.detail['reason'] == 'foreign room unavailable in this dataset'


def test_the_futures_expiry_credit_reaches_the_deposit_cash_log(runs):
    """The settlement is not only an event: it moves the deposit balance."""
    result = runs['futures-lifecycle-to-expiry']
    rows = [e for e in result.logs.cash
            if e.movement is CashMovement.EXPIRY_SETTLEMENT]
    assert rows, 'the expiry settlement never reached the cash log'
    assert sum(e.amount for e in rows) == Decimal('9750000.0')
    assert {e.pool for e in rows} == {'derivatives'}


# --------------------------------------------------------------------------
# Amendment
# --------------------------------------------------------------------------

def test_amendment_refuses_upward_and_price_changes_and_admits_a_decrease(
        runs):
    """Tier 1's stated boundary, read back out of the log.

    An amend-up must re-run the encumbrance and a price amend needs a
    release-and-retake that can fail after the release; both are refused. A
    pure decrease is admitted and keeps time priority (rulebook 2.5).
    """
    result = runs['amend-tier-boundaries']
    refused = [e for e in result.logs.trades
               if e.action is TradeAction.AMEND_REFUSED]
    assert len(refused) == 2
    assert {e.rule for e in refused} == {'session_semantics'}
    assert refused[0].quantity == 1500
    assert refused[1].limit_price == Decimal('12.35')

    amended = _one(result, TradeAction.AMENDED)
    assert amended.quantity == 400
    assert 'priority_preserved=True' in amended.reason
    # The reservation is deliberately NOT reduced -- it over-reserves, which
    # is the conservative direction -- and the encumbrance identity still
    # holds, which is what makes that safe.
    assert not result.failed_identities


# --------------------------------------------------------------------------
# The edge two advances a day cannot reach
# --------------------------------------------------------------------------

def test_a_partially_filled_order_can_be_cancelled(chained):
    """65,000 filled of 200,000, then 135,000 cancelled.

    Two ``run_scenario`` calls over one session clock; see
    ``partial_fill_then_cancel``. **This used to assert a second fill of
    65,000 on the 09:30 advance**, and called it a property of sampling one
    day at two instants. It was a property of the session throwing its
    filled-quantity counter away at the end of every ``advance_to``: the same
    650,600-share day was re-offered to the same order, and the run booked
    130,000 -- 20% of everything that traded -- under
    ``hard(max_participation=0.10)``. The counter is carried per
    ``(ticker, bar)`` now, so the day's allowance is spent once.

    The edge the scenario exists for is untouched: cancelling an order that
    has *already* partially filled is a state the two-advance loop cannot
    otherwise reach, and it is still reached here.
    """
    first, second, _ = chained
    part_one = _one(first, TradeAction.PARTIALLY_FILLED)
    assert part_one.fill_quantity == 65_000
    assert part_one.remaining == 135_000

    assert [e for e in second.logs.trades
            if e.action is TradeAction.PARTIALLY_FILLED] == [], (
        'the second advance is inside the same bar, whose 10% is already '
        'spent; a fill here would be the same shares claimed twice')

    cancels = [e for e in second.logs.trades
               if e.action is TradeAction.CANCELLED]
    assert any(e.quantity == 65_000 for e in cancels), (
        'the cancel outcome should report 65,000 filled')
    assert any(e.quantity == 135_000 for e in cancels), (
        'the cancel event should report 135,000 cancelled')


def test_the_chained_pair_conserves_cash_and_shares_across_both_runs(chained):
    """Every identity holds on the union of the two logs.

    Each ``run_scenario`` checks its own log, so the second run reports
    ``order_lifecycle`` and ``holdings_conservation`` broken -- it holds a
    fill whose ACCEPTED row is in the first log. Showing that is a scoping
    artefact means re-running the checks on the merge, not asserting them
    away.
    """
    first, second, session = chained
    # ``order_lifecycle`` used to be here too, because the second run held a
    # fill whose ACCEPTED row was in the first log. The second run no longer
    # fills -- the bar's allowance was spent by the first -- so only the
    # holding it inherited is out of scope for its own log.
    assert {r.name for r in second.failed_identities} == {
        'holdings_conservation'}
    merged = combined_identities(first, second, session)
    assert not [r for r in merged if not r.passed], (
        [r.detail for r in merged if not r.passed])


def test_every_dong_of_the_chained_run_is_accounted_for(chained):
    """65,000 HPX at 21.50 plus the 0.027% HOSE exchange service charge.

    Half of what this asserted before, and the half that was removed is the
    second claim on the same day's liquidity. The accounting identity is the
    same one either way -- consideration plus charges out of settled cash,
    shares in -- which is the point: it held on the wrong quantity too, so it
    was never going to be the thing that caught the cap.
    """
    _, _, session = chained
    consideration = Decimal('65000') * Decimal('21.50') * Decimal('1000')
    assert consideration == Decimal('1397500000')
    charges = sum(c.amount for c in session.charges())
    assert charges == Decimal('377325')
    assert charges == (consideration * Decimal('0.00027')).quantize(
        Decimal('1'))
    assert session.cash().settled_balance == (
        Decimal('200000000000') - consideration - charges)
    holding = session.holdings('HPX')
    assert holding.total == 65_000
    assert holding.settled == 0
    assert all(t.settles_at == datetime(2022, 11, 14, 13, 0)
               for t in holding.unsettled)


# --------------------------------------------------------------------------
# What the shipped adapter costs
# --------------------------------------------------------------------------

def test_the_shipped_adapter_now_decides_the_fill_the_corpus_can(runs):
    """The same order, the same day, the same policy, two sources: they agree.

    **What this used to assert:** ``thin['fills'] == 0``,
    ``thin['indeterminate'] == 1`` and ``thin['by_field'] == {'volume': 1}``.
    ``DataHubSource`` selected four columns -- ``quote_close``,
    ``quote_ceil``, ``quote_floor``, ``quote_reference`` -- and the session
    synthesised an interval with ``VOLUME`` missing, so ``HardFillPolicy``
    could not compute a participation cap and refused to decide an order the
    corpus had the evidence for.

    It now implements the ``IntervalSource`` seam and serves
    ``quote_dailyvolume`` alongside them, so the two sources reach the same
    verdict on the same bar. ``quote_open``, ``quote_max`` and ``quote_min``
    are still dropped, which is why the phased source remains the richer one
    and why this window is still worth running on both.
    """
    gap = adapter_gap(build_source())
    rich = gap['phased_bar_source']
    thin = gap['shipped_datahub_source']
    assert rich['fills'] == 1 and rich['indeterminate'] == 0
    assert thin['fills'] == 1 and thin['indeterminate'] == 0
    assert thin['by_field'] == {}
    assert rich['fill_policy'] == thin['fill_policy']
    assert 'quote_dailyvolume' not in gap['corpus_columns_dropped_by_datahub']


def test_the_daily_lock_proxy_refuses_an_order_the_bar_proves_was_fillable():
    """``last == ceiling`` is what a close can support, and it over-asserts.

    HPG 2022-11-16: ceiling 13.35, close 13.35, **low 11.80**, 34,902,600
    shares. ``adapters/datahub.py`` infers ``locked_side=BUY`` from the close
    alone, and ``exchanges/equity.py``'s ``BAND_LOCK`` rule then refuses a buy
    at the ceiling -- on a day the market demonstrably traded 11.6% below it.

    Corpus-wide, HSX stocks in 2022, 91,999 ticker-days with volume: the
    proxy calls **3,726** of them buy-side locked and only **365** have
    ``open == high == low == close`` at the ceiling. On the 3,361 it
    over-asserts, the day's low is on average **6.87% below the ceiling** --
    very nearly the whole band.

    The rule is not the problem; the evidence behind it is. With the open,
    high and low the corpus already carries, the question is decidable.
    """
    divergence = lock_proxy_divergence(build_source())
    assert divergence['shipped_datahub_source'] == {
        'action': 'rejected', 'rule': 'band_lock',
        'binding_constraint': Decimal('13.35'), 'fills': 0}
    assert divergence['phased_bar_source'] == {
        'action': 'accepted', 'rule': None, 'binding_constraint': None,
        'fills': 1}


def test_the_depth_proxy_policy_is_the_only_way_to_decide_a_market_order():
    """Neither shipped evidential policy will ever decide an MTL/MOK/MAK.

    Not a preference: ``HardFillPolicy._continuous`` and
    ``ProbabilisticFillPolicy._continuous`` both route a limit-less order to
    ``_market_family_undecidable``, and ``SoftFillPolicy`` decides it but is
    **uncapped by default** and therefore cannot partially fill anything.
    Three terminal edges would have no reachable path end to end. This test
    states the reason so a later fill policy that models depth breaks it.

    ``soft`` is now a capped policy that carries ``max_participation=None``
    unless a caller names one, so the claim "cannot partially fill anything"
    is conditional where it used to be structural. The default is what the
    ``compare_policies`` baseline runs on and it is byte-for-byte the old
    uncapped behaviour, which is why the conclusion above still holds.
    """
    from plutus.market.session.fills import (
        HardFillPolicy, ProbabilisticFillPolicy, SoftFillPolicy)

    assert hasattr(HardFillPolicy, '_market_family_undecidable')
    assert hasattr(ProbabilisticFillPolicy, '_market_family_undecidable')
    assert not isinstance(SoftFillPolicy(), HardFillPolicy)
    # It has the attribute now; what matters is that it is unset by default.
    assert SoftFillPolicy().max_participation is None
    assert SoftFillPolicy(Decimal('0.25')).max_participation == Decimal('0.25')
    assert issubclass(DepthProxyFillPolicy, HardFillPolicy)
    assert DepthProxyFillPolicy(Decimal('0.10')).max_participation == Decimal(
        '0.10')
    assert any('depth assumption' in a
               for a in DepthProxyFillPolicy(Decimal('0.10')).assumptions)


# --------------------------------------------------------------------------
# The source's own claims about the rulebook
# --------------------------------------------------------------------------

@pytest.mark.parametrize('venue,schedule', [
    (Venue.HSX, bars_module.HSX_SCHEDULE),
    (Venue.HNX, bars_module.HNX_SCHEDULE),
    (Venue.HNXDS, bars_module.HNXDS_SCHEDULE),
    (Venue.UPCOM, bars_module.UPCOM_SCHEDULE),
])
def test_the_sources_session_table_matches_the_rulebooks(venue, schedule):
    """``bars.phase_at`` must not become a second, drifting rulebook.

    ``ExchangeSession._interval_for`` returns a served interval verbatim, so
    the phase a fill policy reads comes from the source while the phase
    ``submit()`` judged on comes from the rulebook. If the two tables drift,
    admission and fills judge in different phases and nothing says so.
    """
    rules = Rulebook('vn-2020-2026').at(datetime(2022, 11, 9, 10, 0))
    published = rules.session_schedule(venue)
    for phase, start, end in schedule:
        attribute = {
            SessionPhase.NOON_BREAK: 'noon_break',
            SessionPhase.OPENING_AUCTION: 'opening_auction',
            SessionPhase.CLOSING_AUCTION: 'closing_auction',
            SessionPhase.POST_CLOSE_PLO: 'post_close_plo',
            SessionPhase.CONTINUOUS: 'continuous',
        }[phase]
        assert getattr(published, attribute) == (start, end), (
            f'{venue.value} {attribute} drifted from the rulebook')


@pytest.mark.parametrize('clock,phase', [
    (time(8, 30), SessionPhase.PRE_OPEN),
    (time(9, 5), SessionPhase.OPENING_AUCTION),
    (time(9, 20), SessionPhase.CONTINUOUS),
    (time(12, 0), SessionPhase.NOON_BREAK),
    (time(14, 0), SessionPhase.CONTINUOUS),
    (time(14, 35), SessionPhase.CLOSING_AUCTION),
    (time(14, 50), SessionPhase.POST_CLOSE),
])
def test_the_instants_the_legs_step_to_are_the_phases_they_claim(clock, phase):
    assert bars_module.phase_at(Venue.HSX, clock) is phase


# --------------------------------------------------------------------------
# Pinned defects -- these assert the behaviour as it IS
# --------------------------------------------------------------------------

def test_instrument_expiry_trigger_has_no_producer(runs):
    """``ExpiryTrigger.INSTRUMENT_EXPIRY`` is declared and never emitted.

    It is listed in ``TERMINAL_TRIGGERS_BY_TIF`` against ``DAY`` and
    ``IMMEDIATE_THEN_DAY``, so a caller reading that table expects a resting
    order on an expiring contract to carry it. Nothing in the package ever
    calls ``expire(..., INSTRUMENT_EXPIRY)``: a resting LO on VN30F2211 on
    its last trading day dies with ``SESSION_END`` like any other day order.

    That is not currently a leak -- a day order cannot outlive its session,
    so it cannot outlive its instrument either -- but the table advertises a
    trigger the system does not produce, and a longer-dated time-in-force
    would need it. When it is wired, this test must fail.
    """
    assert ExpiryTrigger.INSTRUMENT_EXPIRY in TERMINAL_TRIGGERS_BY_TIF[
        TimeInForce.DAY]
    row = _one(runs['futures-order-on-the-last-trading-day'],
               TradeAction.EXPIRED)
    assert row.ticker == 'VN30F2211'
    assert row.ts.date() == date(2022, 11, 17)   # the last trading day
    assert row.trigger == ExpiryTrigger.SESSION_END.value
    assert row.trigger != ExpiryTrigger.INSTRUMENT_EXPIRY.value

    emitted = {e.trigger for result in runs.values()
               for e in result.logs.trades
               if e.action is TradeAction.EXPIRED}
    assert ExpiryTrigger.INSTRUMENT_EXPIRY.value not in emitted


def test_an_hnx_day_order_is_stamped_at_1500_not_the_atc(runs):
    """Two modules of this package disagree about when an HNX LO dies.

    ``orders._MATCHING_PHASES`` excludes ``POST_CLOSE_PLO`` and says why:
    *"Treating it as a matching phase would carry a day order past the ATC on
    HNX, which is where a day order actually dies."* ``RuleSet.session_close``
    (``rulebook.py:2132``) says the opposite -- *"the end of the last matching
    phase, which is why it is HNX 15:00 (after the PLO)"* -- and
    ``VnTradingCalendar.session_end`` (``calendar.py:692``) repeats it.

    ``ExchangeSession._session_close`` stamps the expiry from the calendar, so
    the **trigger** follows ``orders.py`` and the **timestamp** follows the
    other two: the MTL residue below is reported alive for the fifteen
    minutes of the PLO session, in which no LO can match.

    PLO has no ``OrderType`` member, so no order this package can create is
    able to match after 14:45 on HNX; ``orders.py`` is the one that is right.
    Not fixed here: ``session_close`` is shared, three docstrings assert the
    15:00 reading, and changing it moves the stamp on every HNX day-order
    expiry. Pinned instead, so a fix breaks this test.
    """
    hnx = _one(runs['mtl-residue-converts-and-rests'], TradeAction.EXPIRED)
    assert hnx.venue == 'HNX'
    assert hnx.ts == datetime(2022, 11, 8, 15, 0)

    hsx = _one(runs['lo-expired-session-end'], TradeAction.EXPIRED)
    assert hsx.venue == 'HSX'
    assert hsx.ts == datetime(2022, 11, 9, 14, 45)

    rules = Rulebook('vn-2020-2026').at(datetime(2022, 11, 8, 10, 0))
    assert rules.session_close(Venue.HNX) == time(15, 0)
    assert rules.session_schedule(Venue.HNX).closing_auction == (
        time(14, 30), time(14, 45))


def test_a_definite_no_fill_leaves_no_row_in_any_log(runs):
    """"Why did my order not fill?" is unanswerable from the three logs.

    ``_evaluate_fills`` emits an event for ``INDETERMINATE`` and nothing for
    ``NO_FILL``, so an order the market never reached, an order the
    participation cap sized below a round lot, and an order that was never
    evaluated at all end in the identical ``expired(session_end)`` row. The
    distinction survives only as a counter on ``indeterminate_report()``.

    A real broker's order log carries the reason. When ``NO_FILL`` gains an
    event, this test must fail.
    """
    cap = runs['participation-cap-below-one-lot']
    reached = runs['lo-expired-session-end']
    for result in (cap, reached):
        assert result.indeterminate.evaluations == 1
        assert result.indeterminate.indeterminate == 0
        row = _one(result, TradeAction.EXPIRED)
        assert row.trigger == 'session_end'
        assert row.reason is None
    # Same terminal row, two entirely different causes.
    assert (_one(cap, TradeAction.EXPIRED).trigger
            == _one(reached, TradeAction.EXPIRED).trigger)


def test_the_indeterminate_rate_mixes_fill_decisions_with_margin_marks(runs):
    """``indeterminate_report()`` counts three populations in one denominator.

    Its own docstring says *"``by_field`` counts fill evaluations the policy
    could not decide"* and *"``evaluations`` counts only the first"*. It does
    not: ``_mark_derivatives`` does ``self._evaluations += 1`` once per mark
    (``exchange.py:2688``) and the expiry-settlement path does it again
    (``exchange.py:2730``).

    In this leg two orders were evaluated for a fill and the reported
    denominator is 18 -- the other 16 are daily margin marks. So the
    published "share of the run the data could not decide" is a function of
    how often the caller sampled the clock: the same scenario at four steps a
    day would report half the rate without a single fill changing.
    """
    result = runs['futures-lifecycle-to-expiry']
    fill_decisions = len([e for e in result.logs.trades
                          if e.action in (TradeAction.FILLED,
                                          TradeAction.PARTIALLY_FILLED,
                                          TradeAction.INDETERMINATE)])
    assert fill_decisions == 2
    assert result.indeterminate.evaluations == 18
    assert result.indeterminate.indeterminate == 1
    # The one undecided item is not a fill at all: it is the missing
    # published settlement price, which the close proxy then stood in for.
    assert result.indeterminate.by_field == {DataField.SETTLEMENT_PRICE: 1}
    settled = [e for e in result.logs.settlement
               if e.action is SettlementAction.EXPIRY_SETTLED][0]
    assert settled.detail['settlement_source'] == 'close_proxy'
    # An equity-only leg has no marks, so there the denominator is honest.
    assert runs['lo-filled'].indeterminate.evaluations == 1


def test_a_cancellation_is_written_to_the_trade_log_twice(runs):
    """One cancellation, two ``CANCELLED`` rows, with different quantities.

    ``StrategyContext.cancel`` writes a row from ``cancel()``'s return value
    -- where ``quantity`` is the **filled** quantity -- and
    ``runner._translate_events`` writes a second from the ``CANCELLED`` event
    -- where ``quantity`` is the **cancelled** quantity. ``_ALREADY_LOGGED``
    covers ``ACCEPTED`` and ``REJECTED`` and not ``CANCELLED``.

    Harmless for a cancel of an untouched order, where both are readable, and
    actively misleading for a partial: the pair reads as two cancellations of
    65,000 and 135,000. This is in the harness, not the session.
    """
    rows = [e for e in runs['lo-cancelled'].logs.trades
            if e.action is TradeAction.CANCELLED]
    assert len(rows) == 2
    assert rows[0].order_id == rows[1].order_id
    assert rows[0].quantity == 0        # filled quantity, from the return
    assert rows[1].quantity == 1000     # cancelled quantity, from the event
