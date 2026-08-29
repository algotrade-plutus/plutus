"""Futures expiry, the roll, and overnight holding, against the real corpus.

Every number asserted here came out of ``plutus.market.session``. Where a test
pins behaviour that is *wrong*, it says so in its own docstring and names what
the right behaviour would be, so the pin is a record and not an endorsement.

The scenario module is imported by path because its filename carries a hyphen,
which is the convention this package already uses (``corporate-charges.py``).
"""

import importlib
from datetime import date, datetime, time
from decimal import Decimal

import pytest

from conftest import requires_corpus

from plutus.market.session.rulebook import Rulebook, UnresolvedRule
from plutus.market.session.types import EventKind, MarginStatus, Venue
from validation.logs import CashMovement, SettlementAction

S = importlib.import_module('validation.scenarios.expiry-overnight')


# --------------------------------------------------------------------------
# Fixtures -- each corpus run is expensive, so each runs once per module
# --------------------------------------------------------------------------

@pytest.fixture(scope='module')
def expiry_run():
    return S.run_expiry_and_roll()


@pytest.fixture(scope='module')
def tet_run():
    return S.run_overnight_across_tet()


@pytest.fixture(scope='module')
def overnight_pair():
    return S.run_flat_versus_overnight()


@pytest.fixture(scope='module')
def variation_trail():
    return S.run_variation_settlement_trail()


@pytest.fixture(scope='module')
def cure_run():
    return S.run_cure_across_tet()


@pytest.fixture(scope='module')
def cure_run_default_loop():
    return S.run_cure_across_tet(open_time=time(9, 30))


# --------------------------------------------------------------------------
# Expiry: the last trading day
# --------------------------------------------------------------------------

@requires_corpus
def test_the_expiring_contract_is_still_tradable_on_its_last_trading_day(
        expiry_run):
    """VN30F2210 printed 1058.0 on 2022-10-20; the caller must be able to act.

    The session used to settle every expiring position at the **first advance
    that landed on the expiry date**, which under the loop ``advance_to``
    documents is 09:30. The strategy's own decision point is after that
    advance, so it arrived to find the front month already gone -- and the
    offsetting sell it then submitted was admitted as a *new naked short* in a
    contract that had already cash-settled, filled at the close, and settled a
    second time at 14:45 for a cash flow of ``-0.0``.

    ``_expiry_reached`` now tests the venue's own close, so the whole last
    session is available. Without that change ``seen_on_roll_day`` reads
    ``{'VN30F2211': 1}`` instead of the two front-month lots.
    """
    assert expiry_run.strategy.seen_on_roll_day == {'VN30F2210': 2}


@requires_corpus
def test_the_roll_leaves_the_back_month_and_nothing_else(expiry_run):
    """One lot sold, one lot bought, one lot settled: the book is the back
    month alone from the close of the expiry day."""
    after = [row for row in expiry_run.strategy.marks
             if row['ts'] == datetime(2022, 10, 20, 14, 45)]
    assert after and after[0]['positions'] == {'VN30F2211': 1}

    final = expiry_run.result.snapshots[-1]
    assert final.positions == {}


@requires_corpus
def test_each_contract_settles_exactly_once(expiry_run):
    """Two contracts, two ``EXPIRY_SETTLED`` rows, on the two expiry days.

    The pre-fix run produced **three**: the extra one settled the phantom
    short the expiry-day sell had opened.
    """
    rows = expiry_run.settlements
    assert [(r.ticker, r.ts) for r in rows] == [
        ('VN30F2210', datetime(2022, 10, 20, 14, 45)),
        ('VN30F2211', datetime(2022, 11, 17, 14, 45)),
    ]
    assert [r.quantity for r in rows] == [1, 1]


@requires_corpus
def test_the_settlement_price_records_which_tier_produced_it(expiry_run):
    """A close standing in for a settlement price is a **substitution**.

    The Parquet corpus publishes no ``settlement_price``, so both expiries
    resolve on ``CLOSE_PROXY``. The event says so, and the ``price_basis``
    carries the measured cost of the substitution rather than leaving the
    reader to assume it is nil.
    """
    assert expiry_run.sources == ('close_proxy', 'close_proxy')
    assert expiry_run.substituted == (True, True)
    for row in expiry_run.settlements:
        assert 'trimmed 14:15-14:45 average' in row.detail['price_basis']


@requires_corpus
def test_the_settlement_cash_flow_is_marked_from_the_variation_reference(
        expiry_run):
    """``quantity x multiplier x (settlement - reference)``, to the dong.

    **Resolved, W1 daily cash settlement.** The variation reference now rolls
    every session, so the expiry event pays only the RESIDUAL since the last
    daily settlement price -- the entry-to-settlement move has already been
    settled in cash, day by day. Both VN30F2210 lots opened at 1032.5 and
    settled daily down to a last DSP of 1053.0; the lot settled at 1058.0 pays
    the residual ``1 x 100,000 x 5.0 = 500,000``. The VN30F2211 lot's last DSP
    was 957.6 and it settled at 972.5: ``1 x 100,000 x 14.9 = 1,490,000``.
    """
    front = expiry_run.settlement_for('VN30F2210')
    back = expiry_run.settlement_for('VN30F2211')
    assert front.amount == (Decimal('1') * S.VN30F_MULTIPLIER
                            * (Decimal('1058.0') - Decimal('1053.0')))
    assert front.amount == Decimal('500000.0')
    assert back.amount == (Decimal('1') * S.VN30F_MULTIPLIER
                           * (Decimal('972.5') - Decimal('957.6')))
    assert back.amount == Decimal('1490000.0')


@requires_corpus
def test_a_contract_carried_into_settlement_pays_the_transfer_tax(expiry_run):
    """Rulebook 8.1/12.3: taxable *"when matched, **or at contract
    maturity**"*.

    ``charges.assess_at_maturity`` was implemented, sourced and tested with no
    call site (FEATURES.md s16.3 #16), so every held-to-expiry contract went
    untaxed -- one whole leg of tax that a trader who closed the day before
    pays. The expected figures are rebuilt here from the statute's own
    structure, ``0.001 x notional x IM / 2``, not copied from the run.

    Without ``_maturity_charges`` both of these read ``()`` and ``0``.
    """
    front = expiry_run.settlement_for('VN30F2210')
    back = expiry_run.settlement_for('VN30F2211')
    assert front.detail['charges'] == ('pit_derivatives_transfer',)
    assert back.detail['charges'] == ('pit_derivatives_transfer',)
    assert front.detail['charges_total'] == S.maturity_tax(
        1, Decimal('1058.0'), Decimal('0.13')) == Decimal('6877')
    assert back.detail['charges_total'] == S.maturity_tax(
        1, Decimal('972.5'), Decimal('0.13')) == Decimal('6321')


@requires_corpus
def test_closing_by_trade_costs_more_than_closing_by_settlement(expiry_run):
    """Two identical lots, same price, same day, two different fee bills.

    Both VN30F2210 lots left the book on 2022-10-20 at 1058.0. The one sold
    paid three rows -- HNX's service price 2,700, VSDC's clearing fee 2,550
    and the transfer tax 6,877 -- and the one settled paid the tax alone. The
    5,250 difference is **deliberately not levied**: no source read charges
    either fee on a final cash settlement, and ``assess_at_maturity`` says so
    in its own docstring. This test exists so the omission stays visible; if a
    source is later found, it fails.
    """
    on_expiry_day = [c for c in expiry_run.result.logs.cash.entries
                     if c.ts == datetime(2022, 10, 20, 14, 45)
                     and c.movement is CashMovement.CHARGE_DEBITED]
    traded = [c for c in on_expiry_day if 'FILL-000002' in (c.cause or '')]
    settled = [c for c in on_expiry_day
               if 'final settlement of VN30F2210' in (c.cause or '')]

    assert sorted(-c.amount for c in traded) == [Decimal('2550'),
                                                 Decimal('2700'),
                                                 Decimal('6877')]
    assert [-c.amount for c in settled] == [Decimal('6877')]
    assert (sum(-c.amount for c in traded)
            - sum(-c.amount for c in settled)) == Decimal('5250')


@requires_corpus
def test_the_deposit_reconciles_to_the_dong_over_the_whole_run(expiry_run):
    """Opening balance plus every logged movement equals the closing balance.

    And the same figure rebuilt independently from the trades: two lots long
    VN30F2210 from 1032.5, both out at 1058.0 (+5,100,000); one lot long
    VN30F2211 from 1037.2, out at 972.5 (-6,470,000); five charge occasions.
    """
    rows = [c for c in expiry_run.result.logs.cash.entries
            if c.pool == 'derivatives']
    opening = rows[0].amount
    assert opening == Decimal('200000000')
    assert rows[-1].balance_after == opening + sum(r.amount for r in rows[1:])

    charges = sum(-c.amount for c in rows
                  if c.movement is CashMovement.CHARGE_DEBITED)
    trading = (Decimal('2') * S.VN30F_MULTIPLIER
               * (Decimal('1058.0') - Decimal('1032.5'))
               + Decimal('1') * S.VN30F_MULTIPLIER
               * (Decimal('972.5') - Decimal('1037.2')))
    assert rows[-1].balance_after == opening + trading - charges
    assert rows[-1].balance_after == Decimal('198568760')


@requires_corpus
def test_every_derivatives_charge_row_is_joinable_to_the_charge_that_made_it(
        expiry_run):
    """The derivatives statement names its fees, like the securities one.

    Measured before the fix: ``session.charges()`` returned 11 itemised
    derivatives charges and the cash log carried 11 anonymous debits -- three
    rows reading ``charge_debited -2,700 / -6,877 / -2,550 "charges on
    FILL-000002"`` where a *sao ke phai sinh* names phi giao dich, phi bu tru
    and thue TNCN. ``charge_kind``, ``fill_id`` and ``ticker`` were all
    ``None``, because ``drain_deposit`` builds these rows from
    ``DepositEntry``, which carries none of them.

    That was not only a readability gap: it is what made
    ``deposit_segregation`` vacuous on every derivatives run, since the
    identity joins on ``charge_kind`` and ``fill_id``.
    """
    rows = [c for c in expiry_run.result.logs.cash.entries
            if c.pool == 'derivatives'
            and c.movement is CashMovement.CHARGE_DEBITED]
    assert len(rows) == 11

    # Every row names its levy, its base and the pool that owes it. Before
    # the fix every one of these was None and the assertion below was the
    # difference between an itemised statement and eleven anonymous debits.
    for row in rows:
        assert row.charge_kind is not None, row.cause
        assert row.charge_base is not None
        assert row.charge_base_value is not None
        assert row.detail['pool'] == 'derivatives'
        assert row.detail['venue'] == 'HNXDS'
        assert row.ticker == 'VN30F2210' or row.ticker == 'VN30F2211'

    # And the kinds are the three a derivatives contract note carries.
    assert {r.charge_kind for r in rows} == {
        'exchange_service_index_future', 'pit_derivatives_transfer',
        'vsdc_derivatives_clearing'}
    # The itemisation reconciles to the run's own total, kind by kind.
    by_kind = {}
    for row in rows:
        by_kind[row.charge_kind] = by_kind.get(row.charge_kind,
                                               Decimal('0')) - row.amount
    assert by_kind['exchange_service_index_future'] == Decimal('10800')
    assert by_kind['vsdc_derivatives_clearing'] == Decimal('10200')
    assert by_kind['pit_derivatives_transfer'] == Decimal('40240')
    assert sum(by_kind.values()) == Decimal('61240')


@requires_corpus
def test_every_identity_holds_across_the_expiry_run(expiry_run):
    assert expiry_run.result.failed_identities == ()
    assert expiry_run.result.error is None


@requires_corpus
def test_an_order_in_a_dead_contract_is_refused_for_want_of_data_not_expiry(
        expiry_run):
    """A gap, pinned rather than hidden.

    After 2022-10-20 VN30F2210 no longer exists, and the sell submitted on
    2022-10-21 is indeed refused -- but on ``band_limit`` with verdict
    ``INDETERMINATE`` and ``band_source='absent'``, i.e. *the corpus has no
    row*, not *this contract has expired*. On a source that kept publishing a
    price past the last trading day the same order would be **admitted**, and
    the account would open a position in a contract the exchange has
    delisted. There is no admission rule keyed on ``InstrumentSpec.expiry``;
    ``ExpiryTrigger.INSTRUMENT_EXPIRY`` is declared in ``types.py`` and fired
    nowhere.
    """
    refused = expiry_run.strategy.after_expiry
    assert len(refused) == 1
    assert refused[0].rule.value == 'band_limit'
    assert refused[0].verdict.value == 'indeterminate'
    assert refused[0].detail.get('band_source') == 'absent'


@requires_corpus
def test_every_order_reached_a_terminal_state(expiry_run):
    """Four submissions, three accepted-and-filled, one refused. Nothing live.

    ``order_lifecycle`` checks the join both ways -- every fill has an
    ``ACCEPTED`` row and every accepted order ends live or terminal -- and the
    final snapshot is the other half: no order is still resting after the last
    close.
    """
    actions = [t.action.value for t in expiry_run.result.logs.trades.entries]
    assert actions.count('submitted') == 4
    assert actions.count('accepted') == 3
    assert actions.count('filled') == 3
    assert actions.count('rejected') == 1
    assert expiry_run.result.snapshots[-1].live_orders == 0


@requires_corpus
def test_the_settlement_price_the_run_used_is_the_corpus_close(expiry_run):
    """And what that substitution cost, measured against the published price.

    The Parquet corpus has no ``settlement_price``, so both expiries resolve
    at the futures close. Read read-only from the production
    ``quote.settlementprice``, the real final settlements were **1058.29** and
    **972.78** against the 1058.00 and 972.50 used here -- **-29,000 and
    -28,000 VND per contract**, one-sided, and four times the size of the
    transfer tax the same settlement now pays.

    The published figures are in ``PUBLISHED_SETTLEMENT`` with their
    timestamps. This test asserts only what runs offline: that the price used
    *is* the close, and that it is flagged as a substitution rather than
    passed off as a settlement.
    """
    assert expiry_run.settlement_for('VN30F2210').detail['settlement_source'] \
        == 'close_proxy'
    front = expiry_run.settlements[0]
    back = expiry_run.settlements[1]
    assert 'final settlement at 1058.0' in front.reason
    assert 'final settlement at 972.5' in back.reason

    gap_front = (S.PUBLISHED_SETTLEMENT['VN30F2210'] - Decimal('1058.0')
                 ) * S.VN30F_MULTIPLIER
    gap_back = (S.PUBLISHED_SETTLEMENT['VN30F2211'] - Decimal('972.5')
                ) * S.VN30F_MULTIPLIER
    assert gap_front == Decimal('29000.000')
    assert gap_back == Decimal('28000.000')


@requires_corpus
def test_under_hard_fills_the_whole_scenario_is_undecidable():
    """The calibration for every other number in this file.

    ``soft`` is the optimistic bound and it is what makes these scenarios
    runnable at all. Under ``hard`` -- the policy that refuses to claim a fill
    the bar cannot evidence -- the identical strategy on the identical window
    fills **nothing**: three orders go INDETERMINATE, are swept EXPIRED at the
    close, no position is ever opened and no expiry is ever settled.

    And ``by_field`` is **empty** while it happens, so a caller asking which
    data was missing is told nothing. Every fill in this module is therefore a
    model output.
    """
    run = S.run_expiry_under_hard_fills()
    actions = [t.action.value for t in run.result.logs.trades.entries]
    assert actions.count('filled') == 0
    assert actions.count('indeterminate') == 3
    assert actions.count('expired') == 3
    assert run.settlements == ()
    assert run.result.snapshots[-1].positions == {}
    assert run.result.indeterminate.indeterminate == 3
    assert run.result.indeterminate.by_field == {}
    assert run.result.failed_identities == ()


# --------------------------------------------------------------------------
# Overnight holding
# --------------------------------------------------------------------------

@requires_corpus
def test_the_tet_break_is_eight_calendar_days_with_no_mark(tet_run):
    """No mark, no call, no cure, and a 46.3-point gap on the far side.

    2021-02-09 is the last session before Tet 2021 and 2021-02-17 the first
    after it. An account holding six lots is in breach for the whole of it and
    there is no instant at which it could have been marked, called or closed.
    """
    gaps = S.unmarked_gaps(tet_run.result)
    assert (date(2021, 2, 9), date(2021, 2, 17), 8) in gaps

    marks = tet_run.strategy.marks
    inside = [m for m in marks
              if date(2021, 2, 10) <= m['ts'].date() <= date(2021, 2, 16)]
    assert inside == []


@requires_corpus
def test_the_overnight_gap_arrives_as_one_mark(tet_run):
    """1130.3 at the last pre-Tet close; the gap arrives in the single
    2021-02-17 reopen advance -- which is where the forced close finally runs.

    **Resolved, MUST #3 forced-execute.** The requirement no longer steps UP to
    the far side of the gap: the six lots survived Tet only because the forced
    close was blocked by the inverted band (2021-02-08/09), and the reopen mark
    is where that offsetting order is finally admitted. So the one advance that
    carries the gap takes the requirement to ZERO, not to the new mark. Before
    the gap the book still holds six lots and the requirement is the intraday
    ``0.13 x 6 x M x 1130.3``; after it the book is flat.
    """
    before = tet_run.strategy.at(date(2021, 2, 9), 'close')
    after = tet_run.strategy.at(date(2021, 2, 17), 'open')
    assert before['positions'] == {'VN30F2102': 6}
    assert before['initial_margin'] == (Decimal('0.13') * Decimal('6')
                                        * S.VN30F_MULTIPLIER
                                        * Decimal('1130.3'))
    assert after['positions'] == {}
    assert after['initial_margin'] == Decimal('0')


@requires_corpus
def test_the_deposit_moves_with_each_daily_settlement_through_the_breach(
        tet_run):
    """**Resolved, W1 daily cash settlement.** Six lots across Tet 2021.

    The account reports ``FORCED`` on 2021-02-08 and is in breach across the
    Tet break, and over that stretch ``deposit_balance`` now STEPS with each
    session's variation settlement rather than sitting still: 99,939,344 ->
    71,199,344 (the 2021-02-08 mark settles ``6 x M x (1092.0 - 1139.9) =
    -28,740,000``) -> 94,179,344 (the 2021-02-09 mark settles
    ``6 x M x (1130.3 - 1092.0) = +22,980,000``). That is the Vietnamese broker
    statement: the balance moves every session by the day's mark.

    The position is not carried to expiry either. MUST #3 force-closes it at
    the 2021-02-17 reopen (the band valid again), so the remainder is realised
    as cash on the offsetting trade -- there is no ``EXPIRY_SETTLED`` row.
    """
    breach = [m for m in tet_run.strategy.marks
              if m['status'] in (MarginStatus.CALL.value,
                                 MarginStatus.FORCED.value)]
    assert breach, 'the window is sized to breach; it did not'
    balances = {m['deposit_balance'] for m in breach}
    assert balances == {Decimal('99939344'), Decimal('71199344'),
                        Decimal('94179344')}

    settles = [c for c in tet_run.result.logs.cash.entries
               if c.movement is CashMovement.VARIATION_SETTLEMENT]
    assert [c.amount for c in settles] == [
        (Decimal('6') * S.VN30F_MULTIPLIER
         * (Decimal('1092.0') - Decimal('1139.9'))),
        (Decimal('6') * S.VN30F_MULTIPLIER
         * (Decimal('1130.3') - Decimal('1092.0')))]
    assert [c.amount for c in settles] == [Decimal('-28740000.0'),
                                           Decimal('22980000.0')]

    # Force-closed at the reopen, not settled at expiry.
    assert tet_run.settlements == ()
    realised = [c for c in tet_run.result.logs.cash.entries
                if c.movement is CashMovement.REALISED_PNL]
    assert realised, 'the forced close realises the remainder as cash'


@requires_corpus
def test_the_ladder_is_walked_in_order_and_the_forced_close_executes(tet_run):
    """Six lots: WARNING at 0.8897 on the entry mark, FORCED next.

    The ``CALL`` rung is never reported and that is correct -- ``on_mark``
    reports **at most one step** and a jump straight past the call level
    reports ``FORCED`` without inventing an intermediate call that never
    happened. **Resolved, MUST #3 forced-execute:** ``FORCED_LIQUIDATION`` now
    submits a real offsetting order. Through the two inverted-band sessions
    (2021-02-08/09, ``ceiling < floor`` in the corpus) that order is REJECTED,
    so the position survives and the forced repeats; at the 2021-02-17 reopen
    the band is valid again, the offsetting order is ACCEPTED, and the book
    goes flat. Count distinct sessions, never events.
    """
    kinds = [(e.ts, e.kind) for e in S.margin_events(tet_run.result)]
    assert kinds[0] == (datetime(2021, 2, 5, 14, 45),
                        EventKind.MARGIN_WARNING)
    assert kinds[1] == (datetime(2021, 2, 8, 9, 30),
                        EventKind.FORCED_LIQUIDATION)
    assert all(k is EventKind.FORCED_LIQUIDATION for _, k in kinds[1:])
    assert EventKind.MARGIN_CALL not in {k for _, k in kinds}

    forced = S.margin_events(tet_run.result, EventKind.FORCED_LIQUIDATION)
    # The forced close executes now; it is rejected while the band is inverted
    # and accepted once it is valid again at the reopen.
    assert any(e.detail['executed'] is True for e in forced)
    last = forced[-1]
    assert last.ts == datetime(2021, 2, 17, 9, 30)
    assert dict(last.detail['closed']) == {'VN30F2102': 'Accepted'}
    assert tet_run.result.snapshots[-1].positions == {}
    assert len(forced) > len({e.ts.date() for e in forced})


@requires_corpus
def test_the_derivatives_settlement_log_carries_expiries_and_nothing_else(
        tet_run, expiry_run):
    """What a Vietnamese futures statement is mostly made of is not here.

    A derivatives account statement is a daily list of *lai lo vi the*
    settling T+1 -- one line per session for as long as the position is open.
    The settlement log's derivatives leg carries ``EXPIRY_SETTLED`` rows only:
    no daily variation settlement (it does not happen, D1) and no row for the
    P&L realised by an offsetting trade, which lands in the **cash** log as
    ``realised_pnl`` on trade date rather than in the settlement log on T+1.

    So the three logs are complete for what the simulator models, and the
    simulator does not model the leg that dominates a real statement.
    """
    for run in (tet_run.result, expiry_run.result):
        legs = {r.leg for r in run.logs.settlement.entries}
        assert legs <= {'derivatives'}
        assert all(r.action is SettlementAction.EXPIRY_SETTLED
                   for r in run.logs.settlement.entries)

    realised = [c for c in expiry_run.result.logs.cash.entries
                if c.movement is CashMovement.REALISED_PNL]
    assert realised, 'the roll realised a close-out'
    assert realised[0].ts == datetime(2022, 10, 20, 14, 45)   # trade date
    assert not [r for r in expiry_run.result.logs.settlement.entries
                if r.ticker == 'VN30F2210'
                and r.action is not SettlementAction.EXPIRY_SETTLED]


@requires_corpus
def test_the_corpus_inverts_the_futures_band_around_tet_2021():
    """A data defect that reaches the derivatives rows, pinned here.

    ``quote_ceil`` and ``quote_floor`` are swapped for VN30F2102 on
    **2021-02-08** and **2021-02-09** -- the two sessions either side of the
    Tet break -- so ``ceiling < floor`` and every order on them is refused on
    ``band_limit``. The session is right to refuse; the point of the test is
    that a scenario placed on those two dates measures the corpus, not the
    rulebook.
    """
    source = S.datahub_source()
    for day in (date(2021, 2, 8), date(2021, 2, 9)):
        state = source.state_at('VN30F2102',
                                datetime.combine(day, time(9, 30)))
        assert state is not None
        assert state.ceiling < state.floor, day


# --------------------------------------------------------------------------
# Flat by close versus holding overnight
# --------------------------------------------------------------------------

@requires_corpus
def test_flat_by_close_carries_no_overnight_requirement(overnight_pair):
    """The day-trader's requirement at 14:45 is zero; the holder's is not.

    Both accounts bought two VN30F2211 lots at 942.0 on 2022-10-24; the
    day-trader also sold two, at the same price, in the same session. At the
    close one carries 24,492,000 VND of requirement into the night and the
    other carries none.
    """
    assert overnight_pair.requirement(flat=True) == Decimal('0')
    assert overnight_pair.requirement(flat=False) == (
        Decimal('0.13') * Decimal('2') * S.VN30F_MULTIPLIER
        * Decimal('942.0'))
    assert overnight_pair.requirement(flat=False) == Decimal('24492000.000')
    assert overnight_pair.day_trader.snapshots[-1].positions == {}
    assert overnight_pair.holder.snapshots[-1].positions == {'VN30F2211': 2}


@requires_corpus
def test_the_overnight_requirement_is_the_intraday_formula(overnight_pair):
    """Finding F-1 says the overnight layer is the scenario grid. It is not.

    At every step of the holder's run the requirement is exactly
    ``posted_margin + resting_order_margin + variation_margin`` -- the
    continuously updated broker number ``MR = IM + VM`` that ``deposit.py``
    computes -- and the 14:45 figure is produced by the same call, on the same
    basis, as the 09:30 one. There is no post-close recomputation, no
    underlying-close basis and no scenario-grid term anywhere in the run.

    ``broker_profile.MarginModel.SCENARIO_GRID`` and
    ``MarginLayer.OVERNIGHT`` exist and name
    ``plutus.market.session.scenario_margin`` as the engine; no module under
    ``session/`` imports it.

    A naming trap found on the way, worth knowing before reading any margin
    number off a snapshot: ``MarginView.initial_margin`` is
    ``initial + resting_order_margin``, so it already contains the resting
    leg. ``posted_margin`` is the open-position half alone. Adding
    ``initial_margin`` and ``resting_order_margin`` double-counts a resting
    order, which is what the first version of this test did.
    """
    for snapshot in overnight_pair.holder.snapshots:
        assert snapshot.margin_required == (snapshot.posted_margin
                                            + snapshot.resting_order_margin
                                            + snapshot.variation_margin)
        assert snapshot.initial_margin == (snapshot.posted_margin
                                           + snapshot.resting_order_margin)

    rules = Rulebook.load('vn-2020-2026')
    for stamp in (datetime(2022, 10, 24, 9, 30),
                  datetime(2022, 10, 24, 14, 45)):
        assert rules.at(stamp).margin_model() == 'pre_margin'


@requires_corpus
def test_daily_variation_margin_settles_in_cash(variation_trail):
    """One lot, twenty sessions, a cash movement (nearly) every session.

    **Resolved, W1 daily cash settlement.** VSDC settles *lai lo vi the* on
    T+1 (Phu luc 7 section C.I: reported by 16h50, cash moves the next day) and
    every Vietnamese broker statement shows the deposit moving each session.
    It now does: ``settle_daily`` is wired into the overnight layer, the
    deposit steps between the entry fill and the final settlement, and the
    largest single day's mark over the hold is **6,260,000 VND**, on
    2022-11-16.

    The total P&L is conserved -- this was never a conservation break -- but it
    is now settled *when* a real statement settles it: eighteen daily variation
    settlements plus the expiry residual sum to the same whole-hold mark trail,
    ``-1,250,000``, that a single close-out movement used to carry alone.
    """
    assert variation_trail.deposit_moved_between_entry_and_close_out is True
    assert variation_trail.largest_unsettled_daily_move == Decimal('6260000.0')

    settles = [c for c in variation_trail.result.logs.cash.entries
               if c.movement is CashMovement.VARIATION_SETTLEMENT]
    assert len(settles) == 18
    # Daily settlements + the expiry residual reconcile to the mark trail.
    assert (sum(c.amount for c in settles)
            + variation_trail.realised_at_close_out
            == sum(move for _, _, move in variation_trail.daily)
            == Decimal('-1250000.0'))
    assert variation_trail.realised_at_close_out == Decimal('1490000.0')
    assert variation_trail.result.failed_identities == ()


# --------------------------------------------------------------------------
# The cure window, and the calendar nobody shipped
# --------------------------------------------------------------------------

@requires_corpus
def test_the_shipped_calendar_puts_the_cure_deadline_inside_tet(cure_run):
    """A margin call whose deadline is a day the market is shut.

    The call is raised at the close of 2022-01-28, the last session before Tet
    2022. ``cure_by`` is the next session's open, and the shipped
    ``weekday_trading_calendar`` -- which is what every default run gets,
    because this repository ships no calendar data at all -- says that is
    **2022-01-31**. The market, the depository and the broker were all closed
    from 2022-01-31 to 2022-02-04.
    """
    arm = cure_run.arm('weekday-only')
    assert arm.call_ts == datetime(2022, 1, 28, 14, 45)
    assert arm.cure_by == datetime(2022, 1, 31, 8, 45)
    assert arm.cure_deadline_is_a_trading_day is False
    assert date(2022, 1, 31) in S.TET_2022_CLOSURE


@requires_corpus
def test_the_same_account_is_cured_or_forced_by_the_calendar_alone(cure_run):
    """Same trades, same prices, same broker terms: two different outcomes.

    Under the shipped weekday-only calendar the deadline had passed while the
    market was closed, so the first mark after the reopen escalates to
    ``FORCED`` -- and it does so **even though the trader paid 30,000,000 VND
    into the segregated deposit on that same session**, which the log shows
    accepted. Under a calendar that knows Tet, the deadline is the reopen
    itself, the payment lands inside it, and no forced liquidation is ever
    emitted.

    Nothing about the market differed. The difference is entirely
    ``settlement_calendar_id == 'weekday-only-UNSOURCED'``.
    """
    weekday = cure_run.arm('weekday-only')
    measured = cure_run.arm('measured')

    assert weekday.was_forced is True
    assert weekday.forced_ts == datetime(2022, 2, 7, 8, 0)
    assert type(weekday.strategy.transfer).__name__ == 'Transferred'

    assert measured.was_forced is False
    assert measured.cure_by == datetime(2022, 2, 7, 8, 45)
    assert measured.cure_deadline_is_a_trading_day is True
    assert type(measured.strategy.transfer).__name__ == 'Transferred'

    # The cure worked in both arms: the account is OK by the close of the
    # reopening session either way. Only one of them was force-closed first.
    for arm in (weekday, measured):
        row = arm.strategy.at(date(2022, 2, 7), 'close')
        assert row['status'] == MarginStatus.OK.value


@requires_corpus
def test_the_documented_loop_cannot_cure_a_margin_call(cure_run_default_loop):
    """``cure_by`` lands between the two advances the loop is built from.

    ``advance_to`` documents a two-advance day and the runner implements it:
    09:30 then 14:45. ``_cure_deadline`` returns the **next session's open**,
    HNXDS 08:45. So the 09:30 advance marks, finds the deadline already past,
    and escalates -- before ``on_session`` is called and before the caller can
    submit anything. Under that loop the cure window is wall-clock non-empty
    and decision-point empty, and **both** calendars force.

    This is not a defect in the state machine. It is what "the deadline is the
    open of the next session" means when the caller's first look at the market
    is 45 minutes later, and it is why :func:`run_cure_across_tet` steps at
    08:00. The regulated top-up deadline is 09h30 T+1 (QD 26 Dieu 13.1), so
    the direction to move in is later, not earlier.
    """
    for arm in cure_run_default_loop.arms:
        assert arm.was_forced is True
        assert arm.forced_ts == datetime(2022, 2, 7, 9, 30)


@requires_corpus
def test_the_margin_view_never_reports_the_cure_deadline(cure_run):
    """``session.margin().cure_by`` is ``None`` even at the instant of a call.

    ``account_margin_requirement`` returns ``cure_by=None`` deliberately and
    says why -- a deadline is state carried across days by
    ``MarginMonitor``, not a property of one mark -- and that is right. The
    gap is one level up: ``MarginMonitor.outstanding_call`` exists, is
    correct, and **``ExchangeSession`` exposes no path to it**; the string
    ``outstanding_call`` does not appear in ``exchange.py``. So the deadline
    is stamped on the ``MARGIN_CALL`` event and nowhere else, and a strategy
    that reads its state rather than its event stream -- which is how a broker
    API is normally used, and the only thing available to a caller that
    restarted -- cannot find out when it has to pay.
    """
    arm = cure_run.arm('measured')
    assert arm.cure_by is not None
    at_call = [m for m in arm.strategy.marks
               if m['ts'] == arm.call_ts]
    assert at_call and at_call[0]['status'] == MarginStatus.CALL.value
    assert all(m['cure_by'] is None for m in arm.strategy.marks)


# --------------------------------------------------------------------------
# After the KRX cutover
# --------------------------------------------------------------------------

def test_the_session_now_asks_which_margin_model_applies_and_counts_the_answer():
    """A 2026 position is still margined ``IM + VM`` intraday -- and it says so.

    **What this used to assert, under the name
    ``test_the_session_never_asks_which_margin_model_applies``:**
    ``indeterminate == 0``. ``RuleSet.margin_model()`` raises from the KRX
    cutover -- the post-KRX mechanism is not sourced in the rulebook -- and
    the session never called it, so a VN30F2603 long carried through the real
    2026-03-09 limit-down was margined on the pre-KRX broker shape ten months
    past the cutover with nothing in any published number saying so.

    The session asks now. The intraday mark still runs on ``IM + VM``,
    because refusing to margin an open position is not a safer answer than
    margining it on last year's mechanism, and every mark it takes that way
    is counted under ``rule.margin_model.unsourced``. The **overnight** layer
    is where the refusal bites: with no firm named there is no
    ``margin_model_overnight`` to ask, so the end-of-day requirement is
    INDETERMINATE and moves the scalar.

    The intraday close mark below now reflects W1 daily cash settlement: the
    day's variation margin is settled to cash at the close and the baseline
    rolls, so the requirement at the close is ``IM`` alone. The margin-model
    refusal this test is really about -- the overnight layer going
    INDETERMINATE -- is orthogonal to that and asserted unchanged.
    """
    result, strategy, model, raised = S.run_post_krx_margin_model()

    assert model is None
    assert isinstance(raised, UnresolvedRule)
    assert 'POST-KRX VALUE NOT SOURCED' in str(raised)

    assert result.error is None
    assert result.failed_identities == ()

    report = result.indeterminate
    silent = getattr(report, 'silent_ignorance', {})
    assert silent.get('rule.margin_model.unsourced', 0) > 0
    assert report.indeterminate == len(result.overnight) > 0
    assert all(r.amount is None for r in result.overnight)
    assert {g for r in result.overnight for g in r.gaps} == {
        'margin_model_overnight.unstated'}
    assert getattr(report, 'is_clean', False) is False

    crash = strategy.at(date(2026, 3, 9), 'close')
    assert crash['initial_margin'] == (Decimal('0.17') * Decimal('2')
                                       * S.VN30F_MULTIPLIER
                                       * Decimal('1766.0'))
    # W1: the day's variation margin has settled to cash at the close and the
    # baseline has rolled, so the close mark carries VM == 0 and the
    # requirement is IM alone (the 09:30 mark still showed the unsettled VM).
    assert crash['variation_margin'] == Decimal('0')
    assert crash['required'] == crash['initial_margin']
    assert crash['required'] == Decimal('60044000.000')


@pytest.fixture(scope='module')
def overnight_layer():
    return S.run_post_krx_overnight_layer()


def test_the_overnight_layer_names_the_one_input_each_arm_is_missing(
        overnight_layer):
    """Three arms, one varied input each, and none of them guesses.

    This is the engine the fidelity audit found unreachable:
    ``scenario_margin.py``, 1,069 executable lines, **zero call sites** in
    ``src/`` or ``validation/``. Every arm here is post-KRX, so the rulebook
    has stopped answering and the *profile* decides -- which is survey
    finding F-1 made operational.

    A caller told only "indeterminate" cannot act. Each arm's ``gaps`` names
    the input, and the remedy is different in each case: name a firm, serve
    the index, or nothing.
    """
    no_firm, withheld, served = overnight_layer

    assert no_firm.model == 'UNSTATED'
    assert no_firm.overnight is None
    assert no_firm.gaps == ('margin_model_overnight.unstated',)

    assert withheld.model == 'SCENARIO_GRID'
    assert withheld.overnight is None
    assert withheld.gaps == ('underlying_close:VN30',)

    assert served.model == 'SCENARIO_GRID'
    assert served.overnight is not None
    assert served.gaps == ()


def test_the_two_layers_coincide_because_the_vm_is_settled(overnight_layer):
    """``IM`` 60,044,000d intraday against ``Max(Rm+Sm-OA, MM)`` 60,044,000d
    overnight, on the same account at the same close -- the two now agree.

    **Resolved, W1 daily cash settlement.** Phu luc 2 section 6.2 has no ``VM``
    term because QD 26 Dieu 20 settles *lai lo vi the* as a separate daily cash
    movement on T+1 -- and this simulator now MAKES that movement:
    ``settle_daily`` is wired into the overnight layer, so at the close the
    day's VM has left the deposit as cash and the continuous ``IM + VM`` view
    carries ``VM == 0``. With the VM settled rather than carried, the grid's
    VM-free requirement and the (now VM-free) intraday requirement coincide;
    the difference is zero, not the variation margin. The one *permissive*
    assumption this layer used to count -- ``variation_margin_unsettled`` -- is
    gone, because the cash is paid rather than carried.
    """
    _, _, served = overnight_layer
    assert served.intraday == Decimal('60044000.000')
    assert served.overnight == Decimal('60044000.00000')
    assert served.difference == Decimal('0')

    crash = served.strategy.at(served.close_day, 'close')
    assert crash['variation_margin'] == Decimal('0')
    assert served.difference == -crash['variation_margin']

    assert 'variation_margin_unsettled' not in served.assumptions
    assert 'minimum_margin_factor_derived' in served.assumptions
    silent = getattr(served.result.indeterminate, 'silent_ignorance', {})
    assert not silent.get('margin.overnight.assumed.variation_margin_unsettled')


def test_an_uncomputable_overnight_layer_is_counted_not_substituted(
        overnight_layer):
    """The requirement the run could not compute never becomes the other one.

    Both refusing arms hold the same position at the same price as the arm
    that computes, and their intraday number is available and identical. It
    is not reported as the overnight one. ``indeterminate`` moves by one per
    session and the gap key says which input to go and get.
    """
    no_firm, withheld, served = overnight_layer
    assert no_firm.intraday == withheld.intraday == served.intraday

    for arm, key in ((no_firm, 'margin_model_overnight.unstated'),
                     (withheld, 'underlying_close')):
        report = arm.result.indeterminate
        assert report.indeterminate == len(arm.result.overnight)
        silent = getattr(report, 'silent_ignorance', {})
        assert silent[f'margin.overnight.uncomputed.{key}'] == report.indeterminate
        assert arm.result.provenance.overnight_determinate == 0
        assert arm.result.provenance.overnight_indeterminate > 0

    assert served.result.indeterminate.indeterminate == 0
    assert served.result.provenance.overnight_determinate > 0


def test_the_grids_minimum_margin_floor_reproduces_the_published_factor(
        overnight_layer):
    """``MM = P x MF`` with ``MF`` = 5,000d per VN30 contract, to the dong.

    ``ContractLeg`` takes ``R``, the half relative spread, and no firm
    publishes one; what the profile publishes is ``MF`` itself. The layer
    inverts ``R = MF / (M x St)`` and ``scenario_margin`` multiplies it
    straight back, so the round trip has to be exact or a 5,000d floor comes
    back as 4999.999999999999999999999999 -- arithmetically harmless and, in
    a margin report, indistinguishable from a bug. Two contracts, 10,000d,
    and the floor does not bind against a 60,044,000d risk margin.
    """
    _, _, served = overnight_layer
    row = [r for r in served.result.overnight
           if r.as_of == served.close_day][-1]
    group = row.detail.groups[0]
    assert group.minimum_margin == Decimal('10000')
    assert group.minimum_margin_binds is False
    assert group.basis_margin == Decimal('0')
    assert group.offsetting_amount is None
    assert row.amount == group.risk_margin


def test_the_maturity_tax_helper_matches_the_statutory_structure():
    """``0.001 x (contracts x multiplier x price x IM / 2)``, whole dong.

    Written out so the expiry tests derive their expectation from the statute
    rather than from the run they are checking.
    """
    assert S.maturity_tax(1, Decimal('1300'), Decimal('0.17')) == Decimal(
        '11050')
    assert S.maturity_tax(2, Decimal('1058.0'), Decimal('0.13')) == Decimal(
        '13754')
    # The row is two-sided: a short pays it too, on the same absolute size.
    assert S.maturity_tax(-1, Decimal('972.5'),
                          Decimal('0.13')) == Decimal('6321')


def test_the_expiry_settlement_waits_for_the_venue_close():
    """The rule the timing fix implements, stated against the rulebook.

    HNXDS closes at 14:45. An advance to 09:30 on the expiry date is inside
    the last trading session and must not settle; an advance to 14:45 is at
    the close and must.
    """
    rules = Rulebook.load('vn-2020-2026').at(datetime(2022, 10, 20, 9, 30))
    assert rules.session_close(Venue.HNXDS) == time(14, 45)
    assert time(9, 30) < rules.session_close(Venue.HNXDS)
