"""The overnight margin layer: what it computes, and what it refuses to.

Two populations, kept apart on purpose:

* the **adapter** (:mod:`plutus.market.session.overnight`) tested against
  hand-written positions and hand-written parameters, so every number here is
  visible and no test depends on a corpus;
* one **architectural** test, which is the same rule
  ``test_scenario_margin.py`` enforces one level down: the module reads
  nothing.

``scenario_margin`` itself is not re-tested here. It has 1,143 tests of its
own and is not what was broken -- what was broken is that nothing called it.
"""

import ast
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Optional

import pytest

from plutus.market.session.broker_profile import (
    MarginModel, UnderlyingParameters as MirroredParameters, VsdcParameterSet,
    get_profile,
)
from plutus.market.session.overnight import (
    PRE_KRX_CONTINUOUS, OvernightAssumption, OvernightGap,
    OvernightRequirement, overnight_requirement, scenario_grid_requirement,
    underlying_of,
)
from plutus.market.session.scenario_margin import ContractLeg, UnderlyingGroup


MF = Decimal('5000')
"""``MF`` per VN30 contract. ``BrokerProfile.minimum_margin_factor`` publishes
it; repeated here so the arithmetic below reads without opening that module."""


@dataclass(frozen=True)
class Held:
    """The three fields :class:`~...overnight.HeldContract` asks for."""

    net_quantity: int
    multiplier: Decimal = Decimal('100000')
    expiry: Optional[date] = None


def mirror(*rows, effective=date(2025, 9, 11)):
    return VsdcParameterSet(effective_from=effective, underlyings=rows,
                            source='hand-written for this test')


VN30_ROW = MirroredParameters(
    underlying='VN30',
    risk_margin_rate=Decimal('0.17'),
    spread_margin_rate=Decimal('0.0087'),
    price_scan_range=Decimal('0.85'),
    scale_factor=Decimal('1'))

VN100_ROW = MirroredParameters(
    underlying='VN100',
    risk_margin_rate=Decimal('0.17'),
    spread_margin_rate=Decimal('0.0117'),
    price_scan_range=Decimal('0.85'),
    scale_factor=Decimal('1.03'))

AS_OF = date(2026, 2, 10)


_DEFAULT = object()
"""A sentinel, because ``None`` is a *value* for both of these arguments --
"this firm publishes no mirror" is exactly the case under test."""


def grid(positions, *, parameters=_DEFAULT, closes=_DEFAULT, as_of=AS_OF,
         **kw):
    return scenario_grid_requirement(
        as_of=as_of, account_id='ACC', positions=positions,
        parameters=mirror(VN30_ROW) if parameters is _DEFAULT else parameters,
        underlying_closes=({'VN30': Decimal('1200')} if closes is _DEFAULT
                           else closes),
        minimum_margin_factor=MF, **kw)


# --------------------------------------------------------------------------
# The contract-code to underlying map
# --------------------------------------------------------------------------

@pytest.mark.parametrize('code,expected', [
    ('VN30F2602', 'VN30'),
    ('VN100F2602', 'VN100'),
    ('GB05F2603', 'GB05'),
    ('GB10F2603', 'GB10'),
    ('vn30f2602', 'VN30'),
])
def test_a_contract_resolves_to_the_thing_it_is_written_on(code, expected):
    assert underlying_of(code) == expected


@pytest.mark.parametrize('code', ['41I1F6000', 'HPG', '', 'VN30'])
def test_an_unrecognised_code_gets_no_underlying_rather_than_a_guess(code):
    """``Sm`` alone differs by 34% between VN30 and VN100 on one published
    page, so a guessed underlying is a wrong margin number that looks right.
    The nine-character coded format is LOW confidence in the rulebook's own
    reading, with three contradicting entries found in the 2026-08 appendix.
    """
    assert underlying_of(code) is None


def test_the_longer_prefix_wins_so_vn100f_is_not_read_as_vn30f():
    """``VN100F`` starts with neither ``VN30F`` nor a shorter entry, but the
    rule is stated and tested because a prefix table that took the first
    match would be one row away from margining VN100 on VN30's parameters."""
    assert underlying_of('VN100F2602') == 'VN100'
    assert underlying_of('VN30F2602') == 'VN30'


# --------------------------------------------------------------------------
# Flat is a number; undecided is not
# --------------------------------------------------------------------------

def test_an_account_flat_at_the_close_owes_a_determinate_zero():
    """The whole point of the layer: flat and undecided must not look alike.

    ``required_margin`` refuses an empty leg set outright -- *"do not call
    this with an empty book and read the zero as a margin number"* -- so the
    zero has to be produced here, deliberately, with :attr:`flat` set.
    """
    result = grid({})
    assert result.amount == Decimal('0')
    assert result.flat is True
    assert result.is_determinate is True
    assert result.gaps == ()


def test_a_flat_contract_row_is_not_a_position():
    """``ContractLedger`` removes a flat row rather than storing a zero, but
    a caller's mapping may still carry one. Netting to zero is being flat."""
    assert grid({'VN30F2602': Held(0)}).flat is True


def test_an_undecided_layer_reports_none_and_never_zero():
    """``amount is None`` is the INDETERMINATE answer. A zero here would be
    summed into a margin total by any caller that did not check."""
    result = grid({'VN30F2602': Held(4)}, parameters=None, closes={})
    assert result.amount is None
    assert result.is_determinate is False
    assert result.flat is False


# --------------------------------------------------------------------------
# The gaps, one per input
# --------------------------------------------------------------------------

def test_a_profile_with_no_parameter_mirror_refuses_rather_than_borrowing():
    """``BrokerProfile.parameters_for`` refuses to fall back to another firm
    and so does this: ``Rm`` and ``Sm`` are VSDC's, they move, and the honest
    answer to "what are TCBS's rates?" is that TCBS delegates them."""
    result = grid({'VN30F2602': Held(4)}, parameters=None)
    assert result.amount is None
    assert OvernightGap.NO_PARAMETER_SET.value in result.gaps


def test_a_mirror_published_after_the_calculation_date_is_refused():
    """SSI's mirror is dated 2026-01-16 and its predecessor 2025-09-11. Using
    the later one for a 2025-06 position would margin it on a table that did
    not exist, which is the date-blindness the dated rulebook exists to
    prevent."""
    result = grid({'VN30F2506': Held(4)}, as_of=date(2025, 6, 10),
                  parameters=mirror(VN30_ROW, effective=date(2026, 1, 16)))
    assert result.amount is None
    assert result.subjects == (
        OvernightGap.PARAMETERS_NOT_YET_EFFECTIVE.value,)
    assert '2026-01-16' in result.gaps[0]


def test_an_undated_mirror_is_used_and_the_run_says_it_could_not_date_it():
    """The rates are still the firm's published ones; only the vintage is
    missing. Refusing would discard a real parameter table over a date the
    firm declined to print, so it is used and the assumption travels."""
    result = grid({'VN30F2602': Held(4)},
                  parameters=mirror(VN30_ROW, effective=None))
    assert result.is_determinate
    assert (OvernightAssumption.PARAMETER_MIRROR_UNDATED.value
            in result.assumptions)


def test_a_mirror_with_no_row_for_a_held_underlying_names_that_underlying():
    result = grid({'VN100F2602': Held(4)},
                  closes={'VN100': Decimal('1200')})
    assert result.amount is None
    assert f'{OvernightGap.NO_UNDERLYING_ROW.value}:VN100' in result.gaps


def test_the_futures_price_is_never_substituted_for_the_underlying_close():
    """Phu luc 2 section 1.1's ``S`` is the **underlying's** close.

    The futures price is right there in the session's marks and differs from
    it by the basis -- which is what a calendar spread is made of and what
    section 3's ``Sm`` charges for. Folding it into ``S`` would put the basis
    into all 21 scenarios and then charge for it a second time. So a source
    that carries the future and not the index gets INDETERMINATE.
    """
    result = grid({'VN30F2602': Held(4)}, closes={})
    assert result.amount is None
    assert f'{OvernightGap.UNDERLYING_CLOSE.value}:VN30' in result.gaps


def test_a_government_bond_future_is_refused_rather_than_approximated():
    """``Dm`` is implemented so nobody re-derives it and has never been
    checked against a real VSDC number; ``MM`` switches off on exactly the day
    ``Dm`` switches on, so a GB book at settlement has no validated floor.
    Margining it on the index path would be wrong by the ratio of their
    multipliers before any margin arithmetic ran."""
    result = grid({'GB05F2603': Held(2, Decimal('10000'))},
                  closes={'GB05': Decimal('100')})
    assert result.amount is None
    assert (f'{OvernightGap.GOVERNMENT_BOND_DEFERRED.value}:GB05F2603'
            in result.gaps)


def test_every_missing_input_is_reported_at_once_not_one_per_run():
    """A caller told "no parameter set" and then, next run, "no underlying
    close" has been made to iterate for information the first call had."""
    result = grid({'VN30F2602': Held(4)}, parameters=None, closes={})
    assert set(result.subjects) == {
        OvernightGap.NO_PARAMETER_SET.value,
        OvernightGap.UNDERLYING_CLOSE.value,
    }


# --------------------------------------------------------------------------
# The grid, when every input is there
# --------------------------------------------------------------------------

def test_the_grid_runs_and_the_worst_scenario_is_the_initial_margin_move():
    """``Rm`` is the worst of 21 scenarios and the extreme one is the ratio.

    ``S x (1 - 0.17) = 996`` on a 1200 close, so a 4-lot long loses
    ``0.17 x 4 x 1200 x 100,000 = 81,600,000``. Asserted from the grid's own
    scenario row as well as from the total, because a total that happens to
    match is not evidence that the grid was walked.
    """
    result = grid({'VN30F2602': Held(4)})
    assert result.model == MarginModel.SCENARIO_GRID.name
    assert result.engine == 'plutus.market.session.scenario_margin'
    assert result.amount == Decimal('81600000')

    group = result.detail.groups[0]
    risk = group.risk_margins[0]
    assert len(risk.scenarios) == 21
    assert risk.worst.k == -10
    assert risk.worst.price == Decimal('996.00')
    assert group.risk_margin == Decimal('81600000')
    assert group.basis_margin == Decimal('0')


def test_the_minimum_margin_floor_reproduces_the_published_factor_exactly():
    """``R`` is inverted out of ``MF`` and multiplied straight back.

    ``ContractLeg`` takes ``R``, the half relative spread of section 5.2, and
    no firm publishes one; the profile publishes ``MF``. The inversion
    ``R = MF / (M x St)`` is taken at raised precision so that
    ``minimum_margin_factor``'s ``R x M x St`` comes back to ``MF`` **at the
    default context** -- otherwise a 5,000d floor reads
    ``4999.999999999999999999999999``, which is arithmetically harmless and,
    in a margin report, indistinguishable from a bug.
    """
    assert getcontext().prec == 28
    result = grid({'VN30F2602': Held(4)})
    group = result.detail.groups[0]
    assert group.minimum_margin == Decimal('4') * MF
    assert group.minimum_margin == Decimal('20000')
    assert group.minimum_margin_binds is False
    assert (OvernightAssumption.MINIMUM_MARGIN_FACTOR_DERIVED.value
            in result.assumptions)


def test_the_floor_binds_on_a_book_with_no_risk_and_says_so():
    """``MM`` is a close-out **cost**, not a risk charge, which is why
    section 6.2 applies it with ``Max``. A perfectly offsetting calendar pair
    has an ``Rm`` of zero across the two months and still has to be unwound.
    """
    result = grid({'VN30F2602': Held(1), 'VN30F2603': Held(-1)})
    group = result.detail.groups[0]
    assert group.risk_margin == Decimal('0')
    # Two contracts to close, gross, not a netted zero.
    assert group.minimum_margin == Decimal('2') * MF
    assert group.basis_margin > Decimal('0')
    assert result.amount == max(group.risk_sum, group.minimum_margin)


def test_a_calendar_spread_is_charged_basis_margin_the_intraday_model_has_no_term_for():
    """``Sm`` is the whole reason the two layers cannot be one number.

    ``deposit.py``'s ``MR = IM + VM`` nets a long and a short in the same
    underlying to nothing -- rulebook 6.3, offsetting trades attract no new
    initial margin. Phu luc 2 section 3 charges the matched part of a
    calendar book anyway, because the two months can move apart.
    """
    spread = grid({'VN30F2602': Held(3), 'VN30F2603': Held(-3)})
    group = spread.detail.groups[0]
    assert group.basis_margin > Decimal('0')
    assert spread.amount > Decimal('0')


def test_the_last_trading_day_leg_drops_out_of_the_floor_and_is_named():
    """Section 5.1: ``MF`` is *"khong duoc xac dinh tai ngay giao dich cuoi
    cung"*. The contract contributes zero to ``MM`` and the result records
    which one, rather than absorbing it into a smaller total."""
    result = grid({'VN30F2602': Held(4, expiry=AS_OF)})
    minimum = result.detail.groups[0].minimum_margins[0]
    assert minimum.amount == Decimal('0')
    assert minimum.undetermined_contracts == ('VN30F2602',)
    assert minimum.has_last_trading_day_leg is True


# --------------------------------------------------------------------------
# Groups: not formed here, and the direction of that error is restrictive
# --------------------------------------------------------------------------

def test_two_underlyings_get_singleton_groups_and_the_run_declares_it():
    """Group membership is VSDC's, published and discretionary (Kendall-tau
    >= 0.9 over >= 3 years). No broker in the survey publishes it, so nothing
    is grouped -- which withholds the offset and can only make the
    requirement larger."""
    result = grid({'VN30F2602': Held(2), 'VN100F2602': Held(2)},
                  parameters=mirror(VN30_ROW, VN100_ROW),
                  closes={'VN30': Decimal('1200'), 'VN100': Decimal('1100')})
    assert result.is_determinate
    assert len(result.detail.groups) == 2
    assert all(g.offsetting_amount is None for g in result.detail.groups)
    assert (OvernightAssumption.NO_PUBLISHED_GROUPING.value
            in result.assumptions)


def test_a_single_underlying_book_is_not_told_about_a_grouping_it_cannot_have():
    """QD 26 Dieu 5.1.1.a conditions the relief on *"tu hai tai san co so tro
    len"*, so on a one-product account the offset is zero **by the rule**.
    A standing disclosure there is the line a reader learns to skip."""
    result = grid({'VN30F2602': Held(4)})
    assert (OvernightAssumption.NO_PUBLISHED_GROUPING.value
            not in result.assumptions)


TWO_INDEX_MIRROR = mirror(
    MirroredParameters(underlying='VN30',
                       risk_margin_rate=Decimal('0.17'),
                       spread_margin_rate=Decimal('0.0087')),
    MirroredParameters(underlying='VN100',
                       risk_margin_rate=Decimal('0.17'),
                       spread_margin_rate=Decimal('0.0117')))
TWO_INDEX_BOOK = {'VN30F2602': Held(2), 'VN100F2602': Held(-2)}
TWO_INDEX_CLOSES = {'VN30': Decimal('1200'), 'VN100': Decimal('1100')}
INDEX_GROUP = (UnderlyingGroup(group_id='INDEX',
                               underlyings=('VN30', 'VN100'),
                               price_relation_rate=Decimal('0.85')),)


def test_a_supplied_group_is_honoured_and_produces_an_offset():
    """The relief exists and is reachable -- it just has to be supplied,
    because VSDC publishes the group and nobody mirrors it.

    78,200,000d ungrouped against 14,668,983d with the offset applied, on the
    same offsetting two-index book. That factor of five is why the layer
    declares ``no_published_grouping`` rather than leaving it implicit: the
    restrictive default is a large number, and a reader has to be able to see
    that it is a default rather than a finding.
    """
    alone = grid(TWO_INDEX_BOOK, parameters=TWO_INDEX_MIRROR,
                 closes=TWO_INDEX_CLOSES)
    grouped = grid(TWO_INDEX_BOOK, parameters=TWO_INDEX_MIRROR,
                   closes=TWO_INDEX_CLOSES, groups=INDEX_GROUP,
                   average_prices={'VN30': Decimal('1180'),
                                   'VN100': Decimal('1080')})
    assert grouped.detail.groups[0].offsetting_amount is not None
    assert grouped.amount < alone.amount
    assert alone.amount == Decimal('78200000.0000')
    assert (OvernightAssumption.NO_PUBLISHED_GROUPING.value
            not in grouped.assumptions)


def test_a_group_supplied_without_an_average_price_names_that_input():
    """Section 2.2.b's scale factor is a mean over an observation window the
    source never specifies -- SILENT. It cannot be derived here, so a group
    supplied without it is refused by name rather than approximated with the
    close."""
    result = grid(TWO_INDEX_BOOK, parameters=TWO_INDEX_MIRROR,
                  closes=TWO_INDEX_CLOSES, groups=INDEX_GROUP)
    assert result.amount is None
    assert set(result.gaps) == {'average_price:VN30', 'average_price:VN100'}


def test_a_singleton_group_is_never_asked_for_an_average_price():
    """It has no pair, so it has no ``Psr`` and no scale factor. Requiring an
    input a one-product account can never use is how a layer becomes
    unusable for the ordinary case."""
    result = grid({'VN30F2602': Held(4)},
                  groups=(UnderlyingGroup(group_id='VN30',
                                          underlyings=('VN30',)),))
    assert result.is_determinate


# --------------------------------------------------------------------------
# The permissive one
# --------------------------------------------------------------------------

def test_a_grid_number_computed_over_an_unsettled_loss_says_so():
    """The only flag here whose direction of error is permissive.

    Section 6.2 has no ``VM`` term because Dieu 20 settles position P&L in
    cash on T+1. This simulator never pays that cash (``settle_daily`` has no
    session call site), so a grid number quoted against an account carrying a
    loss under-states what the account owes by exactly that loss.
    """
    result = grid({'VN30F2602': Held(4)},
                  unsettled_variation_margin=Decimal('12000000'))
    assert result.is_determinate
    assert (OvernightAssumption.VARIATION_MARGIN_UNSETTLED.value
            in result.assumptions)


def test_a_flat_account_is_not_told_about_a_loss_it_no_longer_carries():
    assert (OvernightAssumption.VARIATION_MARGIN_UNSETTLED.value
            not in grid({}, unsettled_variation_margin=Decimal('1')).assumptions)


# --------------------------------------------------------------------------
# Dispatch: three models, and the one that must not be substituted
# --------------------------------------------------------------------------

def test_an_unstated_overnight_model_is_indeterminate_not_the_intraday_one():
    """A firm that publishes a ladder and no overnight formula has not said
    "the intraday one". The two are computed from different price series by
    different engines."""
    result = overnight_requirement(
        as_of=AS_OF, account_id='ACC',
        positions={'VN30F2602': Held(4)},
        model=MarginModel.UNSTATED.name,
        intraday_amount=Decimal('99999999'))
    assert result.amount is None
    assert result.engine is None
    assert result.gaps == (OvernightGap.MODEL_UNSTATED.value,)


def test_the_pre_krx_regime_carries_the_continuous_number_over_the_close():
    """The dated rulebook records one mechanism to 2025-05-04 and no separate
    end-of-day model, so the overnight requirement in that regime *is* the
    continuous one -- on held positions only, with the day's orders gone."""
    result = overnight_requirement(
        as_of=date(2022, 10, 3), account_id='ACC',
        positions={'VN30F2210': Held(4)},
        model=PRE_KRX_CONTINUOUS,
        intraday_amount=Decimal('93095200'))
    assert result.amount == Decimal('93095200')
    assert result.engine == 'plutus.market.session.deposit'
    assert result.gaps == ()


def test_the_pre_krx_regime_reports_zero_for_a_book_it_no_longer_holds():
    result = overnight_requirement(
        as_of=date(2022, 10, 20), account_id='ACC', positions={},
        model=PRE_KRX_CONTINUOUS, intraday_amount=Decimal('7'))
    assert result.amount == Decimal('0')
    assert result.flat is True


def test_a_stale_intraday_mark_makes_the_overnight_layer_undecided_too():
    """A requirement computed from a price observed in another session is
    arithmetic on a price the run did not see, and the layer that borrows it
    inherits that."""
    result = overnight_requirement(
        as_of=date(2022, 10, 3), account_id='ACC',
        positions={'VN30F2210': Held(4)},
        model=PRE_KRX_CONTINUOUS,
        intraday_amount=Decimal('93095200'),
        intraday_is_determinate=False)
    assert result.amount is None
    assert result.gaps == (OvernightGap.INTRADAY_INDETERMINATE.value,)


def test_the_grid_needs_a_minimum_margin_factor_and_will_not_default_one():
    """A defaulted ``MF`` is a wrong ``MM`` floor that looks right, and the
    two numbers Vietnamese firms publish under the same phrase differ by three
    orders of magnitude (gap kind ``G18``)."""
    with pytest.raises(ValueError, match='minimum margin factor'):
        overnight_requirement(
            as_of=AS_OF, account_id='ACC',
            positions={'VN30F2602': Held(4)},
            model=MarginModel.SCENARIO_GRID.name,
            parameters=mirror(VN30_ROW),
            underlying_closes={'VN30': Decimal('1200')})


# --------------------------------------------------------------------------
# The shipped profiles, as the layer sees them
# --------------------------------------------------------------------------

def test_ssi_is_the_profile_that_can_actually_serve_the_grid():
    """SSI publishes ``Rm``, ``Sm``, ``Psr`` and the scale factors and no MR
    formula at all, which is why its ``margin_model_overnight`` is INFERRED
    from the parameters rather than read off the page."""
    ssi = get_profile('SSI', warn=False)
    assert ssi.margin_model_overnight is MarginModel.SCENARIO_GRID
    result = scenario_grid_requirement(
        as_of=date(2026, 2, 10), account_id='ACC',
        positions={'VN30F2602': Held(4)},
        parameters=ssi.vsdc_parameters,
        underlying_closes={'VN30': Decimal('1200')},
        minimum_margin_factor=ssi.minimum_margin_factor)
    assert result.is_determinate
    assert result.amount == Decimal('81600000')


def test_the_synthesis_profile_names_the_grid_and_cannot_feed_it():
    """PLUTUS_DEFAULT's ``margin_model_overnight`` is the grid and it carries
    no parameter mirror, because a rate is not a policy choice a median can
    be taken of. So the honest answer under it is INDETERMINATE naming the
    parameter set -- not a number borrowed from SSI under our own label."""
    default = get_profile('PLUTUS_DEFAULT', warn=False)
    assert default.margin_model_overnight is MarginModel.SCENARIO_GRID
    assert default.vsdc_parameters is None
    result = scenario_grid_requirement(
        as_of=date(2026, 2, 10), account_id='ACC',
        positions={'VN30F2602': Held(4)},
        parameters=default.vsdc_parameters,
        underlying_closes={'VN30': Decimal('1200')},
        minimum_margin_factor=default.minimum_margin_factor)
    assert result.amount is None
    assert OvernightGap.NO_PARAMETER_SET.value in result.gaps


# --------------------------------------------------------------------------
# Purity
# --------------------------------------------------------------------------

_ALLOWED_IMPORTS = {
    '__future__', 'dataclasses', 'datetime', 'decimal', 'enum', 'typing',
    'plutus.market.session.broker_profile',
    'plutus.market.session.scenario_margin',
}


def test_the_layer_reads_nothing():
    """The same structural rule ``scenario_margin`` enforces on itself.

    This module sits between a pure engine and a session that owns a data
    source, and it is exactly the place a corpus read would arrive: the
    underlying's close has to come from *somewhere*, and reaching for it here
    would make the margin model a model of whatever corpus was mounted. It is
    a parameter instead, and this test is what keeps it one.
    """
    path = (Path(__file__).resolve().parents[3] / 'src' / 'plutus' / 'market'
            / 'session' / 'overnight.py')
    tree = ast.parse(path.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported <= _ALLOWED_IMPORTS, (
        f'overnight.py imports {sorted(imported - _ALLOWED_IMPORTS)}; the '
        f'layer must stay parameterised')


def test_the_layer_carries_no_float_literal():
    """Money is ``Decimal`` here as everywhere, and a float rate compounds
    into a margin requirement that cannot be reconciled with a firm's own
    published example."""
    path = (Path(__file__).resolve().parents[3] / 'src' / 'plutus' / 'market'
            / 'session' / 'overnight.py')
    floats = [node for node in ast.walk(ast.parse(path.read_text()))
              if isinstance(node, ast.Constant) and isinstance(node.value,
                                                               float)]
    assert floats == []


def test_the_result_is_frozen_so_a_reader_cannot_edit_the_finding():
    result = grid({'VN30F2602': Held(4)})
    assert isinstance(result, OvernightRequirement)
    with pytest.raises(Exception):
        result.amount = Decimal('0')


def test_the_legs_the_grid_saw_survive_onto_the_result():
    """A margin number nobody can audit is a margin number nobody should
    trust: the legs are kept so a reader can check the gross/short split that
    ``Sm`` and ``MM`` depend on."""
    result = grid({'VN30F2602': Held(3), 'VN30F2603': Held(-2)})
    legs = {leg.contract_code: leg for leg in result.legs}
    assert isinstance(legs['VN30F2602'], ContractLeg)
    assert (legs['VN30F2602'].long_quantity,
            legs['VN30F2602'].short_quantity) == (3, 0)
    assert (legs['VN30F2603'].long_quantity,
            legs['VN30F2603'].short_quantity) == (0, 2)
