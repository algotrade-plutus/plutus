"""Behaviour pinned for the segregated deposit and account-level margin.

Each test names the rule it pins. The rules that matter most here are the four
that a naive margin build gets wrong, all of them sourced to rulebook 6.3:

* the unit of assessment is the **account portfolio**, never a position;
* **IM recomputes on the current price**, so the requirement moves with the
  market on a position whose P&L has not moved at all;
* **VM is loss-only** -- a favourable move contributes exactly zero, so the
  test is not symmetric and a symmetric equity/notional model mis-times calls
  in both directions;
* there is **no maintenance ratio**; the trigger is ``MR / margin assets``
  against a broker ladder.

Three collaborators are faked here rather than imported. ``rulebook.py`` and
``calendar.py`` are being built in parallel and ``deposit.py`` may not import
``ledgers.py`` at all, so the fakes below are the structural protocols
``deposit.py`` declares. When the real modules land they satisfy the same
protocols and these fakes stay as the isolation boundary.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Optional, Tuple

import pytest

from plutus.core.order import OrderType, Side
from plutus.market.broker import BrokerTerms, CureWindow
from plutus.market.protocol import Order, Position
from plutus.market.session.deposit import (CONTRACT_MULTIPLIERS,
                                           VN30F_MULTIPLIER, ContractLedger,
                                           DerivativesAccount, MarginMonitor,
                                           UnknownContractMultiplier,
                                           account_margin_requirement,
                                           liquidation_sequence, margin_status,
                                           resolve_contract_multiplier,
                                           resolve_initial_margin_rate)
from plutus.market.session.types import (AccountRef, BrokerProfile, Encumbrance,
                                         Fill, FillEvidence, InvestorClass,
                                         LiquidationRule, MarginStatus, OrderId,
                                         OrderRecord, OrderState, Pool,
                                         Rejected, ResourceKind, StatefulRule,
                                         TimeInForce, Transferred, Venue)
from plutus.market.verdicts import Verdict

VN30F = 'VN30F2212'
OTHER = 'VN30F2303'
#: A five-year government-bond future. Same venue, different contract template:
#: dong quote on a 100,000d face, multiplier 10,000, +/-3% band, 1 VND tick.
GB05 = 'GB05F2306'

#: 2023-01-04, comfortably inside the 17% initial-margin regime that began
#: 2022-12-15. Every arithmetic expectation below is written against 0.17.
TS = datetime(2023, 1, 4, 10, 0)
NEXT = datetime(2023, 1, 5, 9, 0)


# --------------------------------------------------------------------------
# Fakes for the three collaborators deposit.py takes structurally
# --------------------------------------------------------------------------

class FakeEncumbranceLedger:
    """A minimal ``EncumbranceLedger``, keyed ``(order_id, ResourceKind)``.

    Keyed on the pair rather than on a synthetic id for the same reason the
    real one is: an order reserves at most one kind of resource per pool, and a
    private id would let one order hold two cash reservations.
    """

    def __init__(self) -> None:
        self.held: Dict[Tuple[OrderId, ResourceKind], Encumbrance] = {}

    def take(self, order_id, pool, resource, ts, *, amount=Decimal('0'),
             quantity=0, ticker=None, estimated_charges=Decimal('0')):
        key = (order_id, resource)
        if key in self.held:
            raise ValueError(f'{key} already holds an encumbrance')
        enc = Encumbrance.take(order_id, pool, resource, ts, amount=amount,
                               quantity=quantity, ticker=ticker,
                               estimated_charges=estimated_charges)
        self.held[key] = enc
        return enc

    def consume(self, order_id, ts, *, resource, amount=Decimal('0'),
                quantity=0):
        key = (order_id, resource)
        enc = self.held.get(key)
        if enc is None:
            return None
        reduced = enc.reduced_by(ts, amount=amount, quantity=quantity)
        self.held[key] = reduced
        return reduced

    def release(self, order_id, ts, *, resource=None):
        released = []
        for key in list(self.held):
            if key[0] != order_id:
                continue
            if resource is not None and key[1] is not resource:
                continue
            released.append(self.held.pop(key).released(ts))
        return tuple(released)

    def outstanding(self, *, pool=None, resource=None, ticker=None):
        total = Decimal('0')
        for enc in self.held.values():
            if pool is not None and enc.pool is not pool:
                continue
            if resource is not None and enc.resource is not resource:
                continue
            if ticker is not None and enc.ticker != ticker:
                continue
            total += enc.amount
        return total


class FakeRuleSet:
    """The two dated derivatives values, resolved at one instant."""

    def __init__(self, ts: datetime, rate: Decimal = Decimal('0.17'),
                 limits: Optional[Dict[InvestorClass, Optional[int]]] = None):
        self.ts = ts
        self._rate = rate
        # Rulebook 6.4: 5,000 / 10,000 / 20,000 contracts by investor class,
        # confidence LOW -- the current HNX template no longer prints a number
        # and delegates the limit to VSDC, and no VSDC notice republishing it
        # inside 2020-2026 was located.
        self._limits = limits if limits is not None else {
            InvestorClass.INDIVIDUAL: 5000,
            InvestorClass.INSTITUTION: 10000,
            InvestorClass.PROFESSIONAL: 20000,
        }

    def initial_margin_rate(self, contract_code: str) -> Decimal:
        return self._rate

    def position_limit(self, contract_code: str,
                       investor: InvestorClass) -> Optional[int]:
        return self._limits.get(investor)


class FakeTradingCalendar:
    """Weekday sessions opening at 09:00. Enough for a cure window."""

    def next_session_open(self, ts, venue, rules):
        day = ts.date()
        while True:
            day = date.fromordinal(day.toordinal() + 1)
            if day.weekday() < 5:
                return datetime(day.year, day.month, day.day, 9, 0)


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------

def build_account(deposit=Decimal('100000000'), terms=None, buffer_=Decimal('0'),
                  investor=InvestorClass.INDIVIDUAL, multipliers=None):
    ledger = FakeEncumbranceLedger()
    account = DerivativesAccount(
        ref=AccountRef.derivatives('DER-0001'),
        initial_deposit=deposit,
        terms=terms or BrokerTerms(),
        encumbrances=ledger,
        contracts=ContractLedger(),
        investor=investor,
        margin_buffer=buffer_,
        multipliers=multipliers,
    )
    return account, ledger


def fill(code=VN30F, side=Side.BUY, quantity=1, price=Decimal('1000'),
         ts=TS, order_id='O-1', fill_id='F-1'):
    return Fill(fill_id=fill_id, order_id=OrderId(order_id), ticker=code,
                venue=Venue.HNXDS, side=side, quantity=quantity, price=price,
                ts=ts, evidence=FillEvidence.TRADED_THROUGH)


def order(code=VN30F, side=Side.BUY, quantity=1):
    return Order(ticker=code, side=side, quantity=quantity,
                 order_type=OrderType.LIMIT, limit_price=Decimal('1000'))


def resting_record(order_id, enc, code=VN30F, side=Side.BUY, quantity=1):
    """An ``OrderRecord`` in ``RESTING`` holding one deposit encumbrance."""
    return OrderRecord(
        order_id=OrderId(order_id), order=order(code, side, quantity),
        venue=Venue.HNXDS, state=OrderState.RESTING,
        time_in_force=TimeInForce.DAY, submitted_at=TS, updated_at=TS,
        encumbrances=(enc,))


# --------------------------------------------------------------------------
# Locked shape 5: the entry point takes the account
# --------------------------------------------------------------------------

def test_margin_entry_point_refuses_a_lone_position():
    """The regulated unit of assessment is the ACCOUNT PORTFOLIO (rulebook 6.3).

    A two-leg calendar spread on one account is one MR calculation, not two
    independent ones, so a margin function that takes a lone ``Position``
    cannot express the rule at all. Passing one is a ``TypeError`` -- a wrong
    call, not an unsupported-but-plausible path.
    """
    lone = Position(ticker=VN30F, exchange_code='HNXDS', side=Side.BUY,
                    quantity=1, entry_price=Decimal('1000'), entry_ts=TS,
                    multiplier=VN30F_MULTIPLIER)
    with pytest.raises(TypeError, match='whole DerivativesAccount'):
        account_margin_requirement(lone, {}, None, BrokerTerms(), TS)


def test_module_does_not_build_on_the_legacy_maintenance_ratio():
    """Vietnam publishes NO maintenance margin ratio at any date, 2020-2026.

    ``margin.MarginConfig.maintenance_rate`` models a quantity that does not
    exist and is kept only as the batch research path. This pins that the
    session's margin module never reaches for it -- the failure mode is
    somebody copying the legacy shape, and it is cheaper to catch structurally
    than in review.
    """
    import ast

    from plutus.market.session import deposit as module

    tree = ast.parse(open(module.__file__, encoding='utf-8').read())
    # Identifiers as *code*, not as prose: the module docstring names the
    # legacy class precisely so the next author is warned off it, and that
    # warning must not trip the check it exists to make unnecessary.
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    used |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for alias in (a for n in ast.walk(tree)
                  if isinstance(n, (ast.Import, ast.ImportFrom))
                  for a in n.names):
        used.add(alias.asname or alias.name.rsplit('.', 1)[-1])

    assert 'MarginConfig' not in used
    assert 'maintenance_rate' not in used
    assert 'evaluate_margin' not in used
    assert 'MarginState' not in used
    # The one primitive that IS reused, because it is the dated VSDC series.
    assert 'vsd_initial_margin' in used


# --------------------------------------------------------------------------
# The four facts of the margin computation
# --------------------------------------------------------------------------

def test_initial_margin_is_ratio_times_contracts_times_price_times_multiplier():
    """`IM = ratio x contracts x price x multiplier` (VSDC, QD 61 Art. 5).

    17% is the ratio in force from 2022-12-15. Two contracts at 1,000 index
    points on a 100,000d multiplier is a 200,000,000d notional, so IM is
    34,000,000d.
    """
    account, _ = build_account()
    account.apply_fill(fill(quantity=2, price=Decimal('1000')), None)
    view = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    assert view.initial_margin == Decimal('34000000')
    assert view.variation_margin == Decimal('0')
    assert view.required == Decimal('34000000')


def test_initial_margin_recomputes_on_the_current_price():
    """IM moves with the market INDEPENDENTLY of P&L (rulebook 6.3).

    The position's P&L against its variation-margin baseline is zero here --
    the daily settlement rolled the baseline to 1,100 and the mark is 1,100 --
    yet the requirement is 10% higher than it was at 1,000. A model that fixes
    IM on the entry notional cannot produce that, and would under-charge every
    position that has appreciated.
    """
    account, _ = build_account()
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    at_entry = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)

    account.settle_daily({VN30F: Decimal('1100')}, TS)
    later = account.margin({VN30F: Decimal('1100')}, None, BrokerTerms(), NEXT)

    assert later.variation_margin == Decimal('0')          # P&L flat vs baseline
    assert later.initial_margin > at_entry.initial_margin
    assert later.initial_margin == Decimal('0.17') * Decimal('1100') * VN30F_MULTIPLIER


def test_variation_margin_is_loss_only_and_asymmetric():
    """VM enters MR ONLY when the account portfolio is in a LOSS state.

    VSDC verbatim: "Gia tri ky quy bien doi chi duoc tinh vao gia tri ky quy
    duy tri yeu cau trong truong hop lai lo vi the cua danh muc dau tu tren
    tai khoan cua nha dau tu o trang thai lo". A favourable move of exactly
    the same size contributes zero, so the two are NOT mirror images -- which
    is the whole point, and what a symmetric equity/notional model gets wrong.
    """
    account, _ = build_account()
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)

    down = account.margin({VN30F: Decimal('950')}, None, BrokerTerms(), TS)
    up = account.margin({VN30F: Decimal('1050')}, None, BrokerTerms(), TS)

    # 50 points adverse on a 100,000d multiplier.
    assert down.variation_margin == Decimal('5000000')
    assert up.variation_margin == Decimal('0')
    assert up.required < down.required


def test_variation_margin_is_netted_across_the_account_portfolio():
    """MR is computed on the PORTFOLIO of positions on one trading account.

    A long that loses and a short that gains by the same amount leave the
    account portfolio flat, so VM is zero. Summing per-position losses without
    netting the gains would invent a requirement the rule does not impose.
    """
    account, _ = build_account()
    account.apply_fill(fill(code=VN30F, side=Side.BUY, quantity=1,
                            price=Decimal('1000')), None)
    account.apply_fill(fill(code=OTHER, side=Side.SELL, quantity=1,
                            price=Decimal('1000'), order_id='O-2'), None)

    view = account.margin({VN30F: Decimal('950'), OTHER: Decimal('950')},
                          None, BrokerTerms(), TS)
    assert view.variation_margin == Decimal('0')
    # ...but IM is still summed over both legs: Tier 1 takes no spread credit,
    # because the portfolio-margining formula is in a VSDC appendix that is not
    # published and is marked UNVERIFIED.
    assert view.initial_margin == Decimal('0.17') * Decimal('950') * VN30F_MULTIPLIER * 2


def test_margin_assets_are_the_deposit_balance_with_no_mtm_accumulated():
    """Assets = deposit_balance. The deposit does NOT accumulate mark-to-market.

    Derivatives are cash-settled and the daily P&L leaves or enters as cash on
    T+1, a leg Tier 1 does not model; the adverse half is already carried in
    MR as VM. Deducting the loss from assets as well would double-count it.
    """
    account, _ = build_account(deposit=Decimal('50000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    account.settle_daily({VN30F: Decimal('900')}, TS)

    assert account.deposit_balance == Decimal('50000000')
    view = account.margin({VN30F: Decimal('900')}, None, BrokerTerms(), NEXT)
    assert view.deposit_balance == Decimal('50000000')


# --------------------------------------------------------------------------
# The utilisation ladder
# --------------------------------------------------------------------------

def test_utilisation_ladder_has_three_distinct_states_plus_ok():
    """80 / 90 / 100 on `MR / margin assets` -- **our shape, not VSDC's**.

    This docstring used to read "Article 13 of the VSDC clearing rulebook".
    QD 26/QD-HDTV Dieu 13 has since been read in full and has no percentage in
    it; see ``test_the_margin_utilisation_ladder_is_declared_unsourced``. What
    this test pins is unchanged and still worth pinning: three states, not one
    call boolean. Only the top rung carries a suspension, only the top rung has
    a regulated counterpart, and a simulator that collapses them cannot tell a
    warning from a forced close.
    """
    terms = BrokerTerms()
    assets = Decimal('1000')
    assert margin_status(Decimal('799'), assets, terms) is MarginStatus.OK
    assert margin_status(Decimal('800'), assets, terms) is MarginStatus.WARNING
    assert margin_status(Decimal('900'), assets, terms) is MarginStatus.CALL
    assert margin_status(Decimal('1000'), assets, terms) is MarginStatus.FORCED


def test_no_requirement_is_ok_and_a_requirement_with_no_assets_is_forced():
    """`utilisation` is None, never NaN, when there are no margin assets.

    ``None`` must not read as "fine": an account with a requirement and no
    assets is at level 3, not below level 1. And an account with no positions
    is not in breach for holding no deposit.
    """
    terms = BrokerTerms()
    assert margin_status(Decimal('0'), Decimal('0'), terms) is MarginStatus.OK
    assert margin_status(Decimal('1'), Decimal('0'), terms) is MarginStatus.FORCED


def test_the_ladder_levels_come_from_broker_terms_not_from_this_module():
    """Each broker sets its own levels on the SAME utilisation ratio.

    Pinetree's published 2024 example is 75 / 85 / 90, tighter in every rung
    than the 80 / 90 / 100 defaults. The levels are commercial terms, and --
    corrected 2026-08-26 -- **so is the shape**: the sentence that stood here,
    "only the ladder's shape is sourced", was withdrawn when QD 26 Dieu 13 was
    read. Hard-coding 0.80 here would assert one firm's house rule as market
    law; hard-coding it *and* calling it sourced was the actual defect.
    """
    tight = BrokerTerms(warning_utilisation=Decimal('0.75'),
                        margin_call_utilisation=Decimal('0.85'),
                        forced_close_utilisation=Decimal('0.90'))
    assert margin_status(Decimal('860'), Decimal('1000'), tight) is MarginStatus.CALL
    assert margin_status(Decimal('860'), Decimal('1000'),
                         BrokerTerms()) is MarginStatus.WARNING


# --------------------------------------------------------------------------
# Segregation
# --------------------------------------------------------------------------

def test_a_securities_account_ref_cannot_open_a_deposit():
    """The two pools are segregated in law, not merely partitioned here.

    Margin cash is held at VSD via the derivatives settlement bank in the
    clearing member's name; the securities cash account is a different account
    at a different institution. Coercing the ref would be the segregation
    breach this class exists to prevent.
    """
    with pytest.raises(ValueError, match='segregated'):
        DerivativesAccount(ref=AccountRef.securities('SEC-0001'),
                           initial_deposit=Decimal('1'), terms=BrokerTerms(),
                           encumbrances=FakeEncumbranceLedger(),
                           contracts=ContractLedger())


def test_securities_cash_does_not_answer_a_derivatives_margin_call():
    """NO auto-transfer exists in Vietnam; the caller must transfer explicitly.

    The account is short, and stays short, until cash is explicitly moved
    across. There is no path from a securities balance into this object other
    than ``transfer_in`` -- which is the point: a caller that assumes its cash
    covers a futures call gets the forced liquidation it would get in reality.
    """
    account, _ = build_account(deposit=Decimal('10000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)

    short = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    assert short.status is MarginStatus.FORCED           # 17M required, 10M held
    assert account.ref.serves(Venue.HNXDS)
    assert not account.ref.serves(Venue.HSX)

    moved = account.transfer_in(Decimal('40000000'), TS)
    assert isinstance(moved, Transferred)
    assert moved.source is Pool.SECURITIES
    assert moved.destination is Pool.DERIVATIVES
    cured = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    assert cured.status is MarginStatus.OK


def test_transfer_out_cannot_withdraw_the_margin_backing_a_position():
    """The bound is rulebook 6.3's, and the rejection names the rule.

    A flat-marked position: the mark equals the entry, so ``VM`` is zero and
    ``assets - MR`` and ``assets - IM`` coincide at 33,000,000. What this
    fixes in place is the *shape* -- ``INSUFFICIENT_DEPOSIT``, with the
    withdrawable amount as ``binding_constraint`` and never a prose reason,
    because the rule enum *is* the rejection log.
    ``test_withdrawal_is_bounded_by_assets_minus_mr_not_assets_minus_im``
    separates the two figures.

    33,000,000 itself is refused, and that is condition (1) read exactly:
    utilisation *after* the withdrawal must be **below** the level-3
    threshold, and paying out the whole 33m leaves 17,000,000 of assets
    against a 17,000,000 requirement -- a ratio of 1.00, which
    :func:`margin_status` calls ``FORCED``. A withdrawal that suspends the
    account the instant it lands is not a permitted withdrawal.
    """
    account, _ = build_account(deposit=Decimal('50000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)

    view = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    assert view.posted_margin == Decimal('17000000')
    assert view.free_deposit == Decimal('33000000')
    assert view.equity == Decimal('33000000')          # VM is zero here

    refused = account.transfer_out(Decimal('33000001'),
                                   {VN30F: Decimal('1000')}, None, TS)
    assert isinstance(refused, Rejected)
    assert refused.rule is StatefulRule.INSUFFICIENT_DEPOSIT
    assert refused.binding_constraint == Decimal('33000000')
    assert account.deposit_balance == Decimal('50000000')

    on_the_threshold = account.transfer_out(Decimal('33000000'),
                                            {VN30F: Decimal('1000')}, None, TS)
    assert isinstance(on_the_threshold, Rejected)
    assert on_the_threshold.detail['status_after'] is MarginStatus.FORCED
    assert account.deposit_balance == Decimal('50000000')

    allowed = account.transfer_out(Decimal('32999999'),
                                   {VN30F: Decimal('1000')}, None, TS)
    assert isinstance(allowed, Transferred)
    assert account.deposit_balance == Decimal('17000001')


# --------------------------------------------------------------------------
# The contract ledger: net-signed, and where shorts live
# --------------------------------------------------------------------------

def test_a_sell_on_hnxds_opens_a_short():
    """A SELL on a derivatives symbol opens a short and is never checked
    against holdings.

    Cash equity permits no short selling in Vietnam at any date in the window,
    so the equity path demands settled holdings; the derivatives path does not,
    and this ledger is the only place in the package where a negative position
    exists.
    """
    ledger = ContractLedger()
    row = ledger.apply_fill(fill(side=Side.SELL, quantity=3,
                                 price=Decimal('1000')), VN30F_MULTIPLIER)
    assert row.net_quantity == -3
    assert row.is_short
    assert row.abs_quantity == 3


def test_a_flattening_fill_removes_the_row_rather_than_storing_a_zero():
    """`positions()` never shows a contract the account does not hold."""
    ledger = ContractLedger()
    ledger.apply_fill(fill(quantity=2), VN30F_MULTIPLIER)
    assert ledger.apply_fill(fill(side=Side.SELL, quantity=2),
                             VN30F_MULTIPLIER) is None
    assert ledger.positions() == {}
    assert ledger.net_quantity(VN30F) == 0
    assert ledger.total_contracts() == 0


def test_crossing_through_flat_resets_the_average_entry():
    """Long 2, sell 5 -> short 3, priced at the fill.

    The old average belongs to a position that no longer exists; carrying it
    forward would price a short off a long's entry and put the variation-margin
    baseline on a trade the account no longer has.
    """
    ledger = ContractLedger()
    ledger.apply_fill(fill(quantity=2, price=Decimal('1000')), VN30F_MULTIPLIER)
    row = ledger.apply_fill(fill(side=Side.SELL, quantity=5,
                                 price=Decimal('1200')), VN30F_MULTIPLIER)
    assert row.net_quantity == -3
    assert row.average_entry == Decimal('1200')


def test_reducing_without_crossing_leaves_the_average_entry_alone():
    """Closing some contracts does not re-price the ones still held."""
    ledger = ContractLedger()
    ledger.apply_fill(fill(quantity=4, price=Decimal('1000')), VN30F_MULTIPLIER)
    row = ledger.apply_fill(fill(side=Side.SELL, quantity=1,
                                 price=Decimal('1500')), VN30F_MULTIPLIER)
    assert row.net_quantity == 3
    assert row.average_entry == Decimal('1000')


def test_increasing_averages_the_entry_by_quantity():
    """Two long at 1,000 plus two long at 1,200 averages to 1,100."""
    ledger = ContractLedger()
    ledger.apply_fill(fill(quantity=2, price=Decimal('1000')), VN30F_MULTIPLIER)
    row = ledger.apply_fill(fill(quantity=2, price=Decimal('1200')),
                            VN30F_MULTIPLIER)
    assert row.net_quantity == 4
    assert row.average_entry == Decimal('1100')


def test_offsetting_trades_on_the_same_account_attract_no_new_initial_margin():
    """VSDC excepts "giao dich doi ung cua cung mot tai khoan giao dich".

    Netting down halves the requirement rather than doubling it, which is what
    a table of per-position rows -- the forbidden build -- would do.
    """
    account, _ = build_account()
    account.apply_fill(fill(quantity=2, price=Decimal('1000')), None)
    before = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)

    account.apply_fill(fill(side=Side.SELL, quantity=1, price=Decimal('1000'),
                            order_id='O-2', fill_id='F-2'), None)
    after = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)

    assert after.initial_margin == before.initial_margin / 2


# --------------------------------------------------------------------------
# Resting orders and reservations
# --------------------------------------------------------------------------

def test_a_resting_derivative_order_consumes_free_deposit():
    """Resting derivative orders MUST contribute to MR.

    Otherwise a caller rests futures orders it cannot fund and discovers the
    shortfall only when they fill -- which is exactly the leak locked shape 2
    exists to close on the securities side.
    """
    account, ledger = build_account(deposit=Decimal('50000000'))
    enc = account.reserve_for_order(OrderId('O-1'), order(quantity=1),
                                    Decimal('1000'), None, None, TS)
    assert isinstance(enc, Encumbrance)
    assert enc.pool is Pool.DERIVATIVES
    assert enc.resource is ResourceKind.DEPOSIT
    assert enc.amount == Decimal('17000000')

    view = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    assert view.resting_order_margin == Decimal('17000000')
    assert view.posted_margin == Decimal('0')
    assert view.free_deposit == Decimal('33000000')
    assert view.required == Decimal('17000000')


def test_an_order_short_of_free_deposit_is_rejected_naming_the_free_amount():
    """`Rejected(INSUFFICIENT_DEPOSIT, binding_constraint=free_deposit)`.

    The binding constraint is the number that bound, following the convention
    the six pre-existing admission rules already use.
    """
    account, _ = build_account(deposit=Decimal('10000000'))
    refused = account.reserve_for_order(OrderId('O-1'), order(quantity=1),
                                        Decimal('1000'), None, None, TS)
    assert isinstance(refused, Rejected)
    assert refused.rule is StatefulRule.INSUFFICIENT_DEPOSIT
    assert refused.binding_constraint == Decimal('10000000')
    assert refused.order_id == OrderId('O-1')


def test_an_offsetting_resting_order_reserves_nothing():
    """The margin charged is the INCREMENT, not the gross.

    An order that can only reduce the account's worst-case net position adds no
    initial margin, per the same VSDC exception that governs fills. Reserving
    the gross would refuse a close-out the moment an account is tight, which is
    the exact opposite of what the rule intends -- VSDC *requires* the member
    to offset when the account is at level 3.
    """
    account, _ = build_account(deposit=Decimal('20000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    enc = account.reserve_for_order(OrderId('O-9'),
                                    order(side=Side.SELL, quantity=1),
                                    Decimal('1000'), None, None, TS)
    assert isinstance(enc, Encumbrance)
    assert enc.amount == Decimal('0')


def test_level_three_suspends_opening_but_not_offsetting():
    """A breaching account may not OPEN -- offsetting trades excepted.

    **The behaviour is primary-sourced; the trigger is not.** QD 26/QD-HDTV
    Dieu 13.2.a wires the clearing member to *"khong thuc hien giao dich mo moi
    vi the tren tai khoan vi pham, ngoai tru giao dich doi ung de dong vi the"*
    -- exactly this rule. What Dieu 13 does **not** have is a percentage: the
    breach it fires on is the binary ``assets < MR``, which at the default
    ``forced_close_utilisation = 1.00`` is the same event as the rung tested
    here, off by the ``assets == MR`` boundary. "Level 3" below is this
    module's own name for the top rung and is **not** a citation to Dieu 29's
    level 3, which is a position-limit ladder. The machine-level form at the
    KRX cutover is the trading system accepting "only new orders with a
    close-out parameter" for restricted accounts (VNX QD 21 Dieu 36).
    """
    account, _ = build_account(deposit=Decimal('17000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    view = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    assert view.status is MarginStatus.FORCED           # utilisation == 1.00

    opening = account.reserve_for_order(OrderId('O-2'), order(quantity=1),
                                        Decimal('1000'), None, None, TS)
    assert isinstance(opening, Rejected)
    assert opening.rule is StatefulRule.INSUFFICIENT_DEPOSIT
    assert 'level-3' in opening.detail['reason']

    offsetting = account.reserve_for_order(
        OrderId('O-3'), order(side=Side.SELL, quantity=1), Decimal('1000'),
        None, None, TS)
    assert isinstance(offsetting, Encumbrance)


def test_a_new_order_does_not_re_price_the_portfolio_it_joins():
    """`free_deposit` is measured at the market, not at the new order's limit.

    Otherwise a caller manufactures free deposit by resting a buy at an absurd
    limit: the open position would be re-margined at that price and the
    requirement would collapse. The existing position is margined on the
    account's own latest mark, which is what "the latest matched price at the
    moment of calculation" means.
    """
    account, _ = build_account(deposit=Decimal('40000000'))
    account.apply_fill(fill(quantity=2, price=Decimal('1000')), None)
    # Two contracts marked at 1,000 need 34,000,000, leaving 6,000,000 free.
    # Priced at the order's absurd limit of 1 they would need 34,000, leaving
    # 39,966,000 -- so the binding constraint is the whole test.
    refused = account.reserve_for_order(OrderId('O-2'), order(quantity=1000),
                                        Decimal('1'), None, None, TS)
    assert isinstance(refused, Rejected)
    assert refused.binding_constraint == Decimal('6000000')


def test_the_position_limit_is_tested_on_the_worst_case_net():
    """Rulebook 6.4: 5,000 contracts for an individual, on one trading account.

    Tested against the largest ``|net|`` the account could reach if its live
    orders filled, not against their signed sum: a resting sell that never
    fills must not create room for a buy that then breaches the cap. Confidence
    on the number itself is LOW -- HNX's current template delegates the limit to
    VSDC and prints none -- which is precisely why it comes from the RuleSet
    rather than from a constant here.

    **What this test does NOT pin, now that QD 26 Dieu 27.2.a has been read.**
    The regulated count is *"tong so luong vi the cua cac HDTL co cung tai san
    co so, cung he so nhan hop dong nhung khac thang dao han"* -- summed across
    expiry months of one underlying, with same-expiry opposite legs netted
    first. This gate counts per contract code, so 4,000 VN30F2401 plus 4,000
    VN30F2403 passes at 8,000 against a 5,000 cap. Dieu 29.1.c also puts its
    level 3 at *reaching* 100%, where this test admits an order landing exactly
    on the cap. Both are behaviour changes and are the author's call;
    ``FEATURES.md`` §17 carries them.
    """
    account, _ = build_account(deposit=Decimal('10000000000000'))
    rules = FakeRuleSet(TS)
    account.apply_fill(fill(quantity=4900, price=Decimal('1000')), None)

    # A resting sell must not make room for a buy that would breach on fill.
    sell = account.reserve_for_order(OrderId('S-1'),
                                     order(side=Side.SELL, quantity=100),
                                     Decimal('1000'), rules, None, TS)
    assert isinstance(sell, Encumbrance)

    refused = account.reserve_for_order(OrderId('B-1'), order(quantity=200),
                                        Decimal('1000'), rules, None, TS)
    assert isinstance(refused, Rejected)
    assert refused.rule is StatefulRule.POSITION_LIMIT
    assert refused.binding_constraint == 5000
    assert refused.detail['net_quantity'] == 4900
    assert refused.detail['prospective_net'] == 5100


def test_release_returns_the_encumbrance_and_frees_the_deposit():
    """Locked shape 2: release on EVERY terminal transition.

    Wired as ``OrderBookOfRecord(on_terminal=...)`` by ``exchange.py``, so a
    terminal edge that forgets to release is impossible by construction. The
    hook is shared with the equity path, so releasing an order this account
    never reserved for must be a silent no-op.
    """
    account, _ = build_account(deposit=Decimal('50000000'))
    account.reserve_for_order(OrderId('O-1'), order(quantity=1),
                              Decimal('1000'), None, None, TS)
    released = account.release(OrderId('O-1'), TS)
    assert len(released) == 1
    assert released[0].is_released
    assert account.resting_order_margin() == Decimal('0')
    assert account.release(OrderId('never-seen'), TS) == ()


def test_a_fill_converts_order_margin_into_posted_margin():
    """Leaving order margin reserved after the fill would count it twice.

    The filled portion is now an open position carrying posted margin, so the
    reservation must go with it. A partial fill releases pro rata and the final
    fill takes the residue exactly, so repeated division cannot strand a
    rounding crumb reserved forever.
    """
    account, _ = build_account(deposit=Decimal('80000000'))
    account.reserve_for_order(OrderId('O-1'), order(quantity=3),
                              Decimal('1000'), None, None, TS)
    assert account.resting_order_margin() == Decimal('51000000')

    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    assert account.resting_order_margin() == Decimal('34000000')

    account.apply_fill(fill(quantity=2, price=Decimal('1000'), fill_id='F-2'),
                       None)
    assert account.resting_order_margin() == Decimal('0')

    view = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    assert view.posted_margin == Decimal('51000000')
    assert view.resting_order_margin == Decimal('0')


def test_explicit_resting_records_agree_with_the_encumbrance_ledger():
    """Section 12 invariant 4: the two totals are the same number.

    ``account_margin_requirement`` will take either -- the caller's live
    ``OrderRecord``s, or the shared ledger -- and passing the records is how a
    caller checks the invariant instead of trusting it.
    """
    account, _ = build_account(deposit=Decimal('50000000'))
    enc = account.reserve_for_order(OrderId('O-1'), order(quantity=1),
                                    Decimal('1000'), None, None, TS)
    record = resting_record('O-1', enc)
    from_records = account.margin({VN30F: Decimal('1000')}, None,
                                  BrokerTerms(), TS, resting=(record,))
    from_ledger = account.margin({VN30F: Decimal('1000')}, None,
                                 BrokerTerms(), TS)
    assert from_records.resting_order_margin == from_ledger.resting_order_margin


# --------------------------------------------------------------------------
# Realisation: the one place P&L touches the deposit
# --------------------------------------------------------------------------

def test_closing_a_loser_takes_the_loss_out_of_the_deposit():
    """Closing must move the balance, or the account shows assets it lost.

    VM carries the unrealised loss while the position is open. Close it and VM
    vanishes with it; if the balance did not move, margin assets would be
    overstated by exactly the loss and the utilisation test would silently
    pass. Realising against the variation-margin reference is what makes the
    two cancel exactly.
    """
    account, _ = build_account(deposit=Decimal('50000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    marked = account.margin({VN30F: Decimal('900')}, None, BrokerTerms(), TS)
    assert marked.variation_margin == Decimal('10000000')

    effect = account.apply_fill(fill(side=Side.SELL, quantity=1,
                                     price=Decimal('900'), order_id='O-2',
                                     fill_id='F-2'), None)
    assert effect.position is None
    assert effect.realised == Decimal('-10000000')
    assert account.deposit_balance == Decimal('40000000')

    flat = account.margin({}, None, BrokerTerms(), TS)
    assert flat.required == Decimal('0')
    assert flat.status is MarginStatus.OK


def test_closing_a_winner_credits_the_deposit():
    """A short closed below its entry realises a gain into the deposit."""
    account, _ = build_account(deposit=Decimal('50000000'))
    account.apply_fill(fill(side=Side.SELL, quantity=1, price=Decimal('1000')),
                       None)
    effect = account.apply_fill(fill(side=Side.BUY, quantity=1,
                                     price=Decimal('950'), order_id='O-2',
                                     fill_id='F-2'), None)
    assert effect.realised == Decimal('5000000')
    assert account.deposit_balance == Decimal('55000000')


def test_expiry_settles_into_the_deposit_and_removes_the_row():
    """`ExpirySettled` is a cash movement with the contract removed.

    The settlement price used here is Tier 1's declared simplification -- the
    data source's close on the expiry day. The exchange publishes a trimmed
    30-minute average over 14:15-14:45; on VN30F2206's 2022-06-16 expiry the
    window mean was 1281.36 against a close of 1286.00, a 0.36% overstatement
    measured on ONE contract. The settlement basis itself changed on
    2022-08-17, so a pre-2022-08-17 figure must not be reported as
    authoritative.
    """
    account, _ = build_account(deposit=Decimal('50000000'))
    account.apply_fill(fill(quantity=2, price=Decimal('1000')), None)
    cash = account.settle_expiry(VN30F, Decimal('1010'), TS)
    assert cash == Decimal('2000000')
    assert account.deposit_balance == Decimal('52000000')
    assert account.positions() == {}
    assert account.settle_expiry(VN30F, Decimal('1010'), TS) == Decimal('0')


def test_every_balance_movement_is_recorded_with_the_balance_it_produced():
    """A forced liquidation must state "the resulting deposit balance".

    That is not reportable from a scalar mutated in place, so every movement
    keeps its reason and its resulting balance.
    """
    account, _ = build_account(deposit=Decimal('10000000'))
    account.transfer_in(Decimal('5000000'), TS)
    account.debit(Decimal('100000'), TS, 'VSDC collateral management fee')
    assert [e.balance_after for e in account.entries] == [
        Decimal('10000000'), Decimal('15000000'), Decimal('14900000')]
    assert account.entries[-1].reason.startswith('VSDC')


# --------------------------------------------------------------------------
# Baselines, marks and rates
# --------------------------------------------------------------------------

def test_the_variation_baseline_is_the_opening_price_until_the_first_settlement():
    """VSDC gives two baselines and which applies is which day it is.

    Carried positions mark against the previous trading day's DSP; positions
    opened during the day mark against their own opening price. So a position
    opened today and not yet settled marks against its entry, and after
    ``settle_daily`` it marks against the settlement.
    """
    account, _ = build_account()
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    assert account.variation_reference(VN30F) == Decimal('1000')
    account.settle_daily({VN30F: Decimal('1050')}, TS)
    assert account.variation_reference(VN30F) == Decimal('1050')


def test_settle_daily_refuses_a_missing_settlement_price():
    """Nothing silently defaults.

    Falling back would re-baseline the position to its own stale mark and make
    the next day's VM read zero on a day the account actually lost -- the exact
    failure the loss-only rule exists to catch.
    """
    account, _ = build_account()
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    with pytest.raises(KeyError, match=VN30F):
        account.settle_daily({OTHER: Decimal('1000')}, TS)


def test_a_fill_price_becomes_the_contract_mark():
    """In-session IM uses "the latest matched price at the moment of
    calculation", and a fill IS a matched price."""
    account, _ = build_account()
    account.apply_fill(fill(quantity=1, price=Decimal('1234')), None)
    assert account.mark_for(VN30F) == Decimal('1234')
    account.observe_marks({VN30F: Decimal('1240')}, TS)
    assert account.mark_for(VN30F) == Decimal('1240')
    # A supplied mark still wins over the cache.
    assert account.mark_for(VN30F, {VN30F: Decimal('1250')}) == Decimal('1250')


def test_the_initial_margin_rate_series_is_dated_and_never_seventeen_point_five():
    """10% from 2017-08-10, 13% from 2018-07-18, 17% from 2022-12-15.

    Each step was a *thong bao* under a standing delegation, not a numbered
    *quyet dinh* -- citing "Quyet dinh XX/QD-VSD set margin to 17%" would cite
    a document that does not exist. 17.5% matches no source at any date; it is
    a transcription slip for 0.17.
    """
    assert resolve_initial_margin_rate(None, VN30F, datetime(2018, 1, 2)) == Decimal('0.10')
    assert resolve_initial_margin_rate(None, VN30F, datetime(2020, 1, 2)) == Decimal('0.13')
    assert resolve_initial_margin_rate(None, VN30F, datetime(2023, 1, 4)) == Decimal('0.17')
    # A RuleSet wins when given: it resolves per (contract_code, ts), which is
    # the correct key -- VSDC publishes the ratio per listed contract and one
    # of its stated inputs is time to maturity.
    rules = FakeRuleSet(TS, rate=Decimal('0.20'))
    assert resolve_initial_margin_rate(rules, VN30F, TS) == Decimal('0.20')


def test_the_broker_buffer_is_an_add_on_above_the_vsdc_rate():
    """Clearing members must set their own ratio NO LOWER than VSD's.

    The buffer is a plausible *shape* only: the rulebook records that a
    broker's real lever in Vietnam is its utilisation thresholds, not a
    notional add-on. A profile whose buffer disagrees with the account's is
    refused rather than silently preferred -- one order margined at a different
    rate from the portfolio it joins makes ``free_deposit`` incoherent.
    """
    account, _ = build_account(buffer_=Decimal('0.05'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    view = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    assert view.initial_margin == Decimal('22000000')       # 0.17 + 0.05

    mismatched = BrokerProfile(name='other', margin_buffer=Decimal('0'))
    with pytest.raises(ValueError, match='margin_buffer'):
        account.reserve_for_order(OrderId('O-1'), order(), Decimal('1000'),
                                  None, mismatched, TS)


def test_the_multiplier_is_per_contract_not_per_venue():
    """`CURRENCY_UNIT['HNXDS'] = 1` must never be applied as a multiplier.

    VN30F quotes index points at 100,000d per point; government-bond futures on
    the SAME venue quote dong on a 100,000d face with multiplier 10,000. The
    rulebook flags this as a unit hazard precisely because a per-venue field
    collapses two contracts whose ticks differ 10x and whose bands differ 2.3x.

    Resolved from the dated table, with **no** ``multipliers=`` map supplied:
    an account that has to be told the government-bond multiplier by hand is
    an account that silently uses the index one when nobody remembers to.
    """
    account, _ = build_account()
    assert account.multiplier_for(VN30F, TS) == VN30F_MULTIPLIER
    assert account.multiplier_for(GB05, TS) == Decimal('10000')


def test_a_government_bond_future_reserves_on_the_gb_multiplier():
    """GB05/GB10 margin on 10,000, not on VN30F's 100,000. Rulebook 4.1.

    The rulebook's government-bond futures row is explicit: "1 VND, quoted in
    VND (not index points), on a 100,000d notional face. **Multiplier 10,000**;
    contract size 1 ty dong", confidence HIGH, sourced to HNX's published
    Mau HDTL TPCP 05 nam / 10 nam. 1,000,000,000 / 100,000 = 10,000, so the
    contract size and the multiplier corroborate each other arithmetically.

    ``IM = ratio x contracts x price x multiplier`` = 0.17 x 1 x 100,000 x
    10,000 = 170,000,000d. Borrowing the index multiplier makes that
    1,700,000,000d and the 500m deposit -- which comfortably covers the real
    requirement -- is refused. That is the whole defect: the account cannot
    open a position it can plainly afford.
    """
    account, _ = build_account(deposit=Decimal('500000000'))
    enc = account.reserve_for_order(OrderId('O-GB'),
                                    order(code=GB05, quantity=1),
                                    Decimal('100000'), None, None, TS)
    assert isinstance(enc, Encumbrance)
    assert enc.amount == Decimal('170000000')
    assert enc.amount != Decimal('0.17') * Decimal('100000') * VN30F_MULTIPLIER


def test_an_unrecognised_contract_family_raises_rather_than_borrowing_vn30f():
    """A multiplier the rulebook does not carry is INDETERMINATE, not 100,000.

    IM is *linear* in the multiplier, and so is the derivatives PIT base
    (rulebook 12.3). A guess therefore does not blur the number, it scales it,
    and nothing downstream records that a guess was made. Two codes the table
    genuinely cannot answer: an equity ticker, and HNX's 9-character coded
    futures format, which the rulebook itself records at LOW confidence and
    warns against trusting after finding three contradictory codes in the
    2026-08-21 VSDC appendix.
    """
    account, _ = build_account()
    for code in ('FPT', '41I1F6000'):
        with pytest.raises(UnknownContractMultiplier) as caught:
            account.multiplier_for(code, TS)
        assert caught.value.contract_code == code

    with pytest.raises(UnknownContractMultiplier):
        account.reserve_for_order(OrderId('O-X'), order(code='FPT'),
                                  Decimal('1000'), None, None, TS)


def test_the_multiplier_table_is_keyed_on_contract_and_date():
    """`(contract_code, effective_date) -> multiplier`, not a scalar.

    Rulebook 6.3 makes the point for the margin RATIO -- VSDC publishes it per
    contract, "so the correct key is (contract_code, date), not a scalar" --
    and the multiplier needs the shape more, not less: the ratio has been one
    number across every listed contract since 2022-12-15, whereas VN30F and
    GB05 differ by 10x on the same venue on the same day.

    The date axis is not decoration. GB10 listed 2021-06-28 and VN100F listed
    2025-10-10; before those dates there was no contract of that family, so
    the honest answer is a refusal rather than a value extrapolated backwards.
    """
    assert resolve_contract_multiplier('VN30F2212', date(2023, 1, 4)) == \
        Decimal('100000')
    assert resolve_contract_multiplier(GB05, date(2023, 1, 4)) == \
        Decimal('10000')

    assert resolve_contract_multiplier('GB10F2209', date(2021, 6, 28)) == \
        Decimal('10000')
    with pytest.raises(UnknownContractMultiplier, match='2021-06-28'):
        resolve_contract_multiplier('GB10F2109', date(2021, 6, 27))

    assert resolve_contract_multiplier('VN100F2512', date(2025, 10, 10)) == \
        Decimal('100000')
    with pytest.raises(UnknownContractMultiplier, match='2025-10-10'):
        resolve_contract_multiplier('VN100F2512', date(2025, 10, 9))


def test_a_held_position_keeps_the_multiplier_it_was_opened_on():
    """A position must not be resized mid-life by an edit to the table.

    Every mark, every variation-margin figure and the realised close-out are
    all computed on ``position.multiplier``. If the account re-resolved on
    each mark, amending the table would silently restate the whole life of an
    open position rather than affecting only new ones.
    """
    account, _ = build_account(deposit=Decimal('500000000'))
    account.apply_fill(fill(code=GB05, quantity=1, price=Decimal('100000')),
                       None)
    assert account.position(GB05).multiplier == Decimal('10000')

    account._multiplier_resolver = lambda code, on: Decimal('1')
    assert account.multiplier_for(GB05, TS) == Decimal('10000')


def test_an_explicit_multiplier_overrides_the_table():
    """The override is for what the rulebook does not carry, and only that.

    The rulebook's coverage ends 2026-08-25, so a template listed after it has
    no dated row and a caller must be able to state one. What the override is
    *not* is where the ordinary answer comes from: a caller who has to
    remember GB05's 10,000 by hand margins it at 100,000 on the run they
    forget, which is exactly how this defect was built.
    """
    account, _ = build_account(multipliers={'XX99F2612': Decimal('500')})
    assert account.multiplier_for('XX99F2612', TS) == Decimal('500')
    with pytest.raises(UnknownContractMultiplier):
        account.multiplier_for('XX98F2612', TS)


def test_every_multiplier_row_carries_its_source():
    """An unsourced value must say it is an assumption; these are all sourced.

    Overclaiming is a defect in this codebase, so the table is auditable back
    to a document row by row rather than being four numbers in a dict.
    """
    assert CONTRACT_MULTIPLIERS
    for row in CONTRACT_MULTIPLIERS:
        assert row.document and 'ulebook' in row.document
        assert row.confidence == 'high'
        assert row.note


# --------------------------------------------------------------------------
# The margin call as state
# --------------------------------------------------------------------------

def test_a_margin_call_persists_across_sessions_until_forced():
    """day T call -> day T+1 still short -> forced. Carrying it is the point.

    An outstanding call has to survive to the next mark, which is why this is a
    class and not a function, and why ``Exchange.sustains()`` cannot be reused:
    it takes a whole ``Sequence[MarketState]`` in one batch with nowhere to put
    a call that outlives one element.
    """
    account, _ = build_account(deposit=Decimal('19000000'))
    monitor = MarginMonitor(BrokerTerms(), FakeTradingCalendar())
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)

    # 17,000,000 / 19,000,000 = 0.894... -> below the call level.
    day_t = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    assert day_t.status is MarginStatus.WARNING
    assert monitor.on_mark(account, day_t, None, TS)[0].status is MarginStatus.WARNING

    # A 10-point adverse move adds 1,000,000 of VM and lifts IM: 0.92 -> call.
    call_ts = datetime(2023, 1, 4, 14, 30)
    called = account.margin({VN30F: Decimal('990')}, None, BrokerTerms(), call_ts)
    assert called.status is MarginStatus.CALL
    (opened,) = monitor.on_mark(account, called, None, call_ts)
    assert opened.status is MarginStatus.CALL
    assert opened.cure_by == datetime(2023, 1, 5, 9, 0)
    assert monitor.outstanding_call == datetime(2023, 1, 5, 9, 0)

    # Still inside the window and still short: state, not a repeated event.
    assert monitor.on_mark(account, called, None,
                           datetime(2023, 1, 4, 14, 40)) == ()

    still_short = account.margin({VN30F: Decimal('990')}, None, BrokerTerms(),
                                 NEXT)
    (forced,) = monitor.on_mark(account, still_short, None, NEXT)
    assert forced.status is MarginStatus.FORCED
    assert monitor.outstanding_call is None


def test_a_cured_call_clears_and_does_not_force():
    """The caller may transfer, reduce, or do nothing -- and the first two work.

    Making the strategy's *response* part of the simulation is the whole reason
    the call is modelled as state with a window rather than as an instant
    liquidation.
    """
    account, _ = build_account(deposit=Decimal('19000000'))
    monitor = MarginMonitor(BrokerTerms(), FakeTradingCalendar())
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)

    call_ts = datetime(2023, 1, 4, 14, 30)
    called = account.margin({VN30F: Decimal('990')}, None, BrokerTerms(), call_ts)
    monitor.on_mark(account, called, None, call_ts)
    assert monitor.outstanding_call is not None

    account.transfer_in(Decimal('20000000'), NEXT)
    cured = account.margin({VN30F: Decimal('990')}, None, BrokerTerms(), NEXT)
    (view,) = monitor.on_mark(account, cured, None, NEXT)
    assert view.status is MarginStatus.OK
    assert view.cure_by is None
    assert monitor.outstanding_call is None


def test_a_same_session_cure_window_forces_on_the_next_mark():
    """`CureWindow.SAME_SESSION` means the broker may force-close the same day.

    The cure window is a BROKER term -- the rulebook records this as an
    important negative finding, because its length is a commercial term in the
    account-opening agreement and not an exchange or statutory number. It must
    never live in the rulebook.
    """
    terms = BrokerTerms(cure_window_sessions=CureWindow.SAME_SESSION)
    account, _ = build_account(deposit=Decimal('19000000'), terms=terms)
    monitor = MarginMonitor(terms, FakeTradingCalendar())
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)

    call_ts = datetime(2023, 1, 4, 14, 30)
    called = account.margin({VN30F: Decimal('990')}, None, terms, call_ts)
    (opened,) = monitor.on_mark(account, called, None, call_ts)
    assert opened.cure_by == call_ts

    later = datetime(2023, 1, 4, 14, 40)
    (forced,) = monitor.on_mark(account, called, None, later)
    assert forced.status is MarginStatus.FORCED


def test_a_jump_past_the_call_level_forces_without_inventing_a_call():
    """A mark reports at most one step, and only steps that happened."""
    account, _ = build_account(deposit=Decimal('10000000'))
    monitor = MarginMonitor(BrokerTerms(), FakeTradingCalendar())
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    view = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    (only,) = monitor.on_mark(account, view, None, TS)
    assert only.status is MarginStatus.FORCED
    assert monitor.outstanding_call is None


def test_a_warning_is_not_re_reported_on_every_mark():
    """A warning is a state change, not a per-bar reminder.

    Re-emitting it each mark would flood the caller's single destructive event
    cursor and drown the transitions that matter.
    """
    account, _ = build_account(deposit=Decimal('20000000'))
    monitor = MarginMonitor(BrokerTerms(), FakeTradingCalendar())
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    view = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(), TS)
    assert view.status is MarginStatus.WARNING
    assert len(monitor.on_mark(account, view, None, TS)) == 1
    assert monitor.on_mark(account, view, None, TS) == ()


def test_liquidation_selection_states_its_rule_and_refuses_pro_rata():
    """No Vietnamese document prescribes a forced-close selection order.

    ``LARGEST_LOSS_FIRST`` is a modelling choice and must be stated in the
    event, alongside the contracts closed, the price used and the resulting
    deposit balance. One broker's published behaviour prioritises the nearest
    expiry instead, which is a different answer to the same question -- so the
    rule has to travel with the result. ``PRO_RATA`` is a proportional
    allocation, not an ordering, and answering it with an ordering would be
    answering a different question.
    """
    account, _ = build_account()
    account.apply_fill(fill(code=VN30F, quantity=1, price=Decimal('1000')), None)
    account.apply_fill(fill(code=OTHER, quantity=1, price=Decimal('1000'),
                            order_id='O-2'), None)
    order_ = liquidation_sequence(account, {VN30F: Decimal('900'),
                                            OTHER: Decimal('1010')})
    assert order_ == (VN30F, OTHER)

    with pytest.raises(NotImplementedError, match='PRO_RATA'):
        liquidation_sequence(account, {}, LiquidationRule.PRO_RATA)


# --------------------------------------------------------------------------
# View identities
# --------------------------------------------------------------------------

def test_the_view_identities_hold():
    """`IM = posted + resting`, `free = balance - IM`, `MR = IM + VM`.

    Every one of ``required``, ``free_deposit``, ``utilisation`` and ``equity``
    is derived on ``MarginView`` rather than stored, so a caller assembling the
    record by hand cannot violate them -- but the terms this module *puts in*
    still have to add up, and this is where that is checked.
    """
    account, _ = build_account(deposit=Decimal('60000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)
    account.reserve_for_order(OrderId('O-2'), order(quantity=1),
                              Decimal('1000'), None, None, TS)
    view = account.margin({VN30F: Decimal('900')}, None, BrokerTerms(), TS)

    assert view.initial_margin == view.posted_margin + view.resting_order_margin
    assert view.required == view.initial_margin + view.variation_margin
    assert view.free_deposit == view.deposit_balance - view.initial_margin
    assert view.equity == view.deposit_balance - view.required
    assert view.utilisation == view.required / view.deposit_balance
    assert view.cure_by is None       # a deadline is the monitor's state


# --------------------------------------------------------------------------
# Margin withdrawal -- rulebook 6.3, VSDC SVI and SIV.3
# --------------------------------------------------------------------------

def test_a_suspended_account_cannot_withdraw_the_margin_it_is_short_of():
    """Rulebook 6.3 condition (3): not while suspended for a utilisation breach.

    The account is 110m against a 117m requirement -- utilisation 1.0636,
    status ``FORCED``, equity **negative** 7m. ``free_deposit`` still reads
    93m, because it subtracts only IM and this account's whole problem is VM.
    Paying out that 93m is the failure this test exists to stop: the money
    leaves the segregated pool at the exact instant VSDC has the account
    suspended, and utilisation goes to 6.88.
    """
    account, _ = build_account(deposit=Decimal('110000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('2000')), None)
    marks = {VN30F: Decimal('1000')}

    view = account.margin(marks, None, BrokerTerms(), TS)
    assert view.status is MarginStatus.FORCED
    assert view.required == Decimal('117000000')     # IM 17m + VM 100m
    assert view.free_deposit == Decimal('93000000')  # the loose figure
    assert view.equity == Decimal('-7000000')        # the true one

    refused = account.transfer_out(Decimal('93000000'), marks, None, TS,
                                   terms=BrokerTerms())
    assert isinstance(refused, Rejected)
    assert refused.rule is StatefulRule.INSUFFICIENT_DEPOSIT
    assert refused.binding_constraint == Decimal('0')
    assert refused.detail['status'] is MarginStatus.FORCED
    assert account.deposit_balance == Decimal('110000000')


def test_withdrawal_is_bounded_by_assets_minus_mr_not_assets_minus_im():
    """"The withdrawable amount is assets minus MR at the broker's threshold".

    A losing but un-called account: 110m of assets, IM 17m, VM 20m, MR 37m.
    ``free_deposit`` says 93m is withdrawable and it is wrong by exactly the
    unrealised loss. The bound is condition (1) -- utilisation *after* the
    withdrawal below the level-3 threshold -- so the supremum is
    ``110m - 37m/1.00 = 73m`` and 73m itself is refused, because landing on
    the threshold is landing in breach.
    """
    account, _ = build_account(deposit=Decimal('110000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1200')), None)
    marks = {VN30F: Decimal('1000')}

    view = account.margin(marks, None, BrokerTerms(), TS)
    assert view.status is MarginStatus.OK
    assert view.free_deposit == Decimal('93000000')
    assert view.required == Decimal('37000000')

    too_much = account.transfer_out(Decimal('93000000'), marks, None, TS,
                                    terms=BrokerTerms())
    assert isinstance(too_much, Rejected)
    assert too_much.binding_constraint == Decimal('73000000')

    on_the_line = account.transfer_out(Decimal('73000000'), marks, None, TS,
                                       terms=BrokerTerms())
    assert isinstance(on_the_line, Rejected)
    assert on_the_line.detail['status_after'] is MarginStatus.FORCED

    allowed = account.transfer_out(Decimal('72999999'), marks, None, TS,
                                   terms=BrokerTerms())
    assert isinstance(allowed, Transferred)
    assert account.deposit_balance == Decimal('37000001')


def test_a_flat_account_may_still_be_emptied():
    """No requirement, no bound. The withdrawal test is a utilisation test.

    Guards the fix against over-tightening: with ``MR == 0`` the post-
    withdrawal ratio is not 1.0 but undefined-and-fine, and
    :func:`margin_status` already says a requirement of zero is ``OK`` at any
    assets. An account holding nothing must be able to take everything back.
    """
    account, _ = build_account(deposit=Decimal('50000000'))
    emptied = account.transfer_out(Decimal('50000000'), {}, None, TS,
                                   terms=BrokerTerms())
    assert isinstance(emptied, Transferred)
    assert account.deposit_balance == Decimal('0')


# --------------------------------------------------------------------------
# Stale marks -- design section 9, "settlement_price absent => INDETERMINATE"
# --------------------------------------------------------------------------

def test_a_mark_from_a_previous_session_makes_the_status_indeterminate():
    """A held contract with no price this session is not an ``OK`` account.

    ``average_entry`` is the latest matched price for an account that has
    traded and *not yet been marked*; a session later it is a stale price and
    a definite ladder status computed from it is a claim the data does not
    support. Design section 9: ``settlement_price`` absent -> margin marks
    ``INDETERMINATE``.
    """
    account, _ = build_account(deposit=Decimal('100000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)

    same_session = account.margin({}, None, BrokerTerms(), TS)
    assert same_session.status is MarginStatus.OK
    assert same_session.stale_marks == ()

    next_session = account.margin({}, None, BrokerTerms(), NEXT)
    assert next_session.status is MarginStatus.INDETERMINATE
    assert next_session.stale_marks == (VN30F,)
    assert next_session.is_indeterminate

    # A price for the session cures it without any other change.
    marked = account.margin({VN30F: Decimal('1000')}, None, BrokerTerms(),
                            NEXT)
    assert marked.status is MarginStatus.OK
    assert marked.stale_marks == ()


def test_an_indeterminate_mark_does_not_advance_the_call_machine():
    """Ignorance is not news, and it is not a cure either.

    An outstanding call must survive a blind session: clearing it would report
    a cure that never happened, and forcing on it would liquidate on a price
    nobody observed.
    """
    terms = BrokerTerms()
    monitor = MarginMonitor(terms, FakeTradingCalendar())
    account, _ = build_account(deposit=Decimal('19000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)

    # MR = IM 16,830,000 + VM 1,000,000 on 19,000,000 of assets: 0.938.
    call_ts = datetime(2023, 1, 4, 14, 0)
    called = account.margin({VN30F: Decimal('990')}, None, terms, call_ts)
    assert called.status is MarginStatus.CALL
    assert len(monitor.on_mark(account, called, None, call_ts)) == 1
    assert monitor.outstanding_call is not None

    blind = account.margin({}, None, terms, datetime(2023, 1, 6, 14, 0))
    assert blind.status is MarginStatus.INDETERMINATE
    assert monitor.on_mark(account, blind, None,
                           datetime(2023, 1, 6, 14, 0)) == ()
    assert monitor.outstanding_call is not None
    assert monitor.last_status is MarginStatus.CALL


def test_a_stale_account_may_not_open_a_new_position():
    """Level 3 cannot be certified away by a mark nobody took.

    ``reserve_for_order`` gates opening on ``status is FORCED``. Once a stale
    mark can make the status neither FORCED nor definite, an account actually
    in breach would be admitted on a blind session -- so the gate refuses on
    ignorance too, and says so with an ``INDETERMINATE`` verdict rather than
    reporting a market rule.
    """
    account, _ = build_account(deposit=Decimal('100000000'))
    account.apply_fill(fill(quantity=1, price=Decimal('1000')), None)

    refused = account.reserve_for_order(OrderId('O-2'), order(quantity=1),
                                        Decimal('1000'), None, None, NEXT)
    assert isinstance(refused, Rejected)
    assert refused.rule is StatefulRule.INSUFFICIENT_DEPOSIT
    assert refused.verdict is Verdict.INDETERMINATE
    assert refused.detail['stale_marks'] == (VN30F,)

    account.observe_marks({VN30F: Decimal('1000')}, NEXT)
    allowed = account.reserve_for_order(OrderId('O-3'), order(quantity=1),
                                        Decimal('1000'), None, None, NEXT)
    assert isinstance(allowed, Encumbrance)


# --------------------------------------------------------------------------
# Provenance of the utilisation ladder, pinned after QD 26 was read
# --------------------------------------------------------------------------

def test_the_margin_utilisation_ladder_is_declared_unsourced():
    """The ladder we apply to MARGIN is ours. Pinned so it cannot drift back.

    Until 2026-08-26 ``BrokerTerms.PROVENANCE`` said the 80/90/100 shape was
    "VSDC-sourced", citing Article 13 of the clearing rulebook through the
    chain QD 96 -> QD 61 -> QD 12 -> QD 26. The chain's last link was then read
    in full: **QD 26/QD-HDTV Dieu 13 contains no percentage.** It is binary --
    margin assets below required margin is the violation -- checked at 09h30,
    14h00 and 16h30.

    This test exists because the wrong claim was load-bearing in four places
    at once (``broker.py``, ``deposit.py``, ``types.MarginStatus``,
    ``margin.py``) and was quoted back by ``FEATURES.md`` as settled. A
    docstring cannot be regression-tested; a ``PROVENANCE`` string can.
    """
    p = BrokerTerms.PROVENANCE

    # The claim that was withdrawn must not reappear in any entry.
    for key, text in p.items():
        assert 'Article 13' not in text, key
        assert 'VSDC-sourced' not in text, key

    for key in ('warning_utilisation', 'margin_call_utilisation',
                'forced_close_utilisation'):
        assert p[key].startswith('UNSOURCED'), key

    # 80/90/100 IS primary-sourced -- to a different rule, on a different
    # quantity, which this object does not implement.
    call = p['margin_call_utilisation']
    assert 'Dieu 29' in call
    assert 'POSITION LIMIT' in call

    # Pre-KRX is UNVERIFIED, not disproven: QD 61 and QD 12 are unread.
    assert 'UNVERIFIED, not disproven' in call
    assert 'QD 61 and QD 12 have never been read' in call


def test_provenance_covers_every_assumed_field_and_no_others():
    """House rule 1: every non-sourced default is labelled on its own object.

    The counterpart of ``AdvanceTerms.PROVENANCE`` and
    ``CommissionSchedule.PROVENANCE``. ``advance_on_sale_enabled`` is a
    behaviour switch rather than a market value, so it is the one field that
    needs no provenance entry.
    """
    from dataclasses import fields

    documented = set(BrokerTerms.PROVENANCE)
    declared = {f.name for f in fields(BrokerTerms)}
    assert documented <= declared
    assert declared - documented == {'advance_on_sale_enabled'}


def test_cure_window_separates_the_regulated_deadline_from_the_broker_term():
    """QD 26 Dieu 13 regulates member->VSDC. The investor window is commercial.

    Both halves have to be visible, because the previous text hedged ("do not
    hard-code either number") on the strength of a LuatVietnam *summary*, and
    the summary was wrong about one of them: the position-limit escalation at
    Dieu 29.5 is **03 working days**, not five.
    """
    text = BrokerTerms.PROVENANCE['cure_window_sessions']
    assert 'assumed' in text
    assert 'PARTLY REGULATED' in text
    assert '09h30' in text          # Dieu 13.1 top-up, next trading day
    assert '03 working days' in text  # Dieu 13.3.b, Dieu 29.5
    assert 'Dieu 29.5' in text
    # The five-business-day figure came from a summary of the superseded
    # edition and must not survive anywhere in this dict.
    assert '05 working days' not in text
    assert 'five' not in text.lower()

    # And the default is unchanged: the author's decision stands.
    assert BrokerTerms().cure_window_sessions == CureWindow.NEXT_SESSION
    assert CureWindow.NEXT_SESSION == 1


def test_the_forced_rung_is_qd26_dieu_13s_binary_test_off_by_equality():
    """The one rung with a regulated counterpart, and its exact discrepancy.

    ``MR / assets >= 1.00`` is ``assets <= MR``; Dieu 13's violation is
    ``assets < MR``. So the default top rung reproduces the regulated test
    everywhere except ``assets == MR``, where Dieu 13.2.c restores the account
    (*"bang hoac lon hon muc ky quy yeu cau"*) and we hold it in breach. One
    tick, conservative, and stated rather than hidden -- which is the whole
    reason the numeric default was left alone when the citation was withdrawn.
    """
    terms = BrokerTerms()
    assert terms.forced_close_utilisation == Decimal('1.00')

    required = Decimal('100')
    assert margin_status(required, required - 1, terms) is MarginStatus.FORCED
    assert margin_status(required, required, terms) is MarginStatus.FORCED
    assert (margin_status(required, required + 1, terms)
            is not MarginStatus.FORCED)

    assert 'assets == ' in BrokerTerms.PROVENANCE['forced_close_utilisation']
