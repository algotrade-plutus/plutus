"""Tests for the post-KRX derivatives margin model.

Every component carries a **worked numeric example computed by hand in the
test's own docstring**, so a reader can check the arithmetic without running
anything and without trusting the implementation. Where a number comes out of
a reading the published source does not fully determine, the docstring says
which reading produced it.

Three tests here are architectural rather than numeric --
:func:`test_the_engine_imports_nothing_that_could_reach_a_data_source`,
:func:`test_the_engine_contains_no_float_literal` and
:func:`test_every_inference_id_cited_in_the_module_is_in_the_register`. They
exist because "pure and parameterised" and "Decimal, never float" are
properties a reviewer cannot check by reading a 2,000-line module, and a
property nobody can check is a property that decays.
"""

import ast
import inspect
from datetime import date, time
from decimal import Decimal

import pytest

from plutus.market.session import scenario_margin as sm
from plutus.market.session.scenario_margin import (
    CHECKPOINT_TIME, Checkpoint, ContractLeg, DeliveryPosition, INFERENCES,
    MIN_OBSERVATIONS_1_3_A, MIN_OBSERVATIONS_1_3_B, MarginEventKind,
    MarginInputError, MarginObservation, MarginTimelineError,
    MarginViolationMonitor, MarginViolationState, PercentileMethod,
    SCENARIO_COUNT, SCENARIO_STEPS, SOURCE_DEFECTS, UnderlyingGroup,
    UnderlyingParameters, apply_offsetting_amount, basis_margin,
    delivery_margin, delta_coefficient, group_price_relation_rate,
    is_margin_violation, minimum_margin, minimum_margin_factor,
    offsetting_amount, parametric_var, percentile, price_relation_rate,
    required_margin, risk_margin, scenario_loss, scenario_price,
    scenario_prices, two_day_returns,
)

D = Decimal

#: The VN30F shape used throughout: 100,000 VND per index point.
VN30F_MULTIPLIER = D(100000)


def vn30(
    long_quantity=0,
    short_quantity=0,
    *,
    code='VN30F2312',
    minimum_margin_rate=D('0.0005'),
    is_last_trading_day=False,
):
    """One VN30F leg. Every number is explicit; nothing is defaulted."""
    return ContractLeg(
        contract_code=code,
        underlying='VN30',
        long_quantity=long_quantity,
        short_quantity=short_quantity,
        multiplier=VN30F_MULTIPLIER,
        minimum_margin_rate=minimum_margin_rate,
        is_last_trading_day=is_last_trading_day,
    )


def vn30_parameters(
    close=D(1000), ratio=D('0.17'), sm_rate=D('0.004'), average_price=None
):
    return UnderlyingParameters(
        underlying='VN30',
        closing_price=close,
        initial_margin_ratio=ratio,
        basis_margin_rate=sm_rate,
        average_price=average_price,
    )


# ===========================================================================
# The architecture: pure, parameterised, Decimal-only
# ===========================================================================

#: Everything the engine is permitted to import.
#:
#: No ``duckdb``, no ``pandas``, no ``pathlib``, no ``json``, no ``requests``,
#: and -- importantly -- nothing from ``plutus`` either. A margin engine that
#: imports the session's data layer will eventually be handed a connection.
_ALLOWED_IMPORTS = frozenset({
    '__future__', 'dataclasses', 'datetime', 'decimal', 'enum', 'typing',
})


def _module_ast():
    source = inspect.getsource(sm)
    return ast.parse(source)


def _defined_identifiers():
    """Every name the module's *code* introduces -- prose excluded.

    Used by the "this concept must not exist here" tests. Grepping the raw
    source cannot distinguish an implemented haircut from a docstring
    explaining why haircuts are somebody else's problem, and the docstrings
    are supposed to discuss exactly the things the code must not do.
    """
    names = set()
    for node in ast.walk(_module_ast()):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.AnnAssign) and isinstance(
            node.target, ast.Name
        ):
            names.add(node.target.id)
    return names


def test_the_engine_imports_nothing_that_could_reach_a_data_source():
    """The purity rule, enforced structurally rather than by inspection.

    VSDC computes ``SMrate``, ``MF`` and the initial margin ratio from long
    histories. Those arrive as inputs. Calibrating them from a data source is
    a separate, later component, and this is the module where that boundary
    is easiest to violate: the temptation is one ``import duckdb`` away and
    the resulting engine would silently model one corpus instead of the
    exchange.
    """
    imported = set()
    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                imported.add('<relative import>')
            elif node.module:
                imported.add(node.module.split('.')[0])
    assert imported <= _ALLOWED_IMPORTS, (
        f'scenario_margin.py imports {sorted(imported - _ALLOWED_IMPORTS)}, '
        'which is outside the pure-engine allowlist. It must not read a '
        'database, a file or any market data.'
    )


def test_the_engine_contains_no_float_literal():
    """House rule: Decimal for money and ratios, never float.

    A float that reached a margin number would show up only in the last
    digits of a forced-liquidation amount, which is exactly where nobody
    looks.
    """
    offenders = [
        node.lineno
        for node in ast.walk(_module_ast())
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]
    assert offenders == [], (
        f'float literals at lines {offenders} of scenario_margin.py'
    )


def test_the_engine_defines_no_market_data():
    """No embedded prices, ratios or contract tables.

    The only module-level numeric constants permitted are the ones the
    *source text* states: the scenario range, the two observation-window
    minima, and the small arithmetic helpers. Nothing that could be mistaken
    for a calibrated market quantity lives here.
    """
    assert SCENARIO_STEPS == tuple(range(-10, 11))
    assert SCENARIO_COUNT == 21
    assert MIN_OBSERVATIONS_1_3_A == 120
    assert MIN_OBSERVATIONS_1_3_B == 250
    numeric_names = {
        name for name, value in vars(sm).items()
        if isinstance(value, Decimal) and not name.startswith('_')
    }
    assert numeric_names == set(), (
        f'module-level Decimal constants {sorted(numeric_names)} look like '
        'embedded market data'
    )


def test_every_inference_id_cited_in_the_module_is_in_the_register():
    """A register that falls behind the code is worse than no register.

    Every ``INFERENCES['I..']`` or bare ``I..`` cited in a docstring must
    resolve, and every registered id must actually be cited somewhere --
    otherwise the register grows entries for inferences that were removed.
    """
    source = inspect.getsource(sm)
    body = source.split("SOURCE_DEFECTS: Mapping", 1)[1]
    for key in INFERENCES:
        assert f'``{key}``' in body or f"'{key}'" in body, (
            f'{key} is registered in INFERENCES but never cited in the code'
        )
    for key in SOURCE_DEFECTS:
        assert f"SOURCE_DEFECTS['{key}']" in body or f'``{key}``' in body, (
            f'{key} is registered in SOURCE_DEFECTS but never cited'
        )


def test_the_module_refuses_a_float_at_the_boundary():
    """A float input is refused loudly rather than silently coerced."""
    with pytest.raises(MarginInputError, match='Decimal-only'):
        scenario_price(1000.0, D('0.17'), 0)


# ===========================================================================
# Phu luc 2 section 1.2 -- the 21 scenarios, and the transcription defect
# ===========================================================================


def test_the_scenario_grid_has_the_twenty_one_rows_the_appendix_declares():
    """Section 1.2 says *"21 kich ban"* and the table lists S-10 .. S+10.

    Row 11 is ``k = 0``, the unchanged-price scenario -- a useful landmark
    when checking the reconstruction against the published table by eye.
    """
    prices = scenario_prices(D(1000), D('0.17'))
    assert len(prices) == SCENARIO_COUNT == 21
    assert SCENARIO_STEPS[0] == -10 and SCENARIO_STEPS[-1] == 10
    assert prices[10] == D(1000)


def test_the_scenario_price_reconstructs_the_missing_k():
    """**By hand.** ``S0 = 1000.00``, ``rate = 0.17``.

    The published cell prints ``Sk = S0 x (1 + rate/10)`` with no ``k``,
    which would make every scenario ``1000 x 1.017 = 1017`` -- 21 identical
    rows. The reading adopted here is ``Sk = S0 x (1 + k x rate/10)``::

        k = -10 -> 1000 x (1 - 10 x 0.017) = 1000 x 0.83 =  830.00
        k =  -1 -> 1000 x (1 -  1 x 0.017) = 1000 x 0.983 = 983.00
        k =   0 -> 1000 x  1               =              1000.00
        k =  +1 -> 1000 x (1 +  1 x 0.017) = 1000 x 1.017 = 1017.00
        k = +10 -> 1000 x (1 + 10 x 0.017) = 1000 x 1.17  = 1170.00

    Note ``k = +1`` is the one value where the two readings coincide, which
    is presumably how the ``k`` came to be dropped in typesetting.
    """
    s0, rate = D(1000), D('0.17')
    assert scenario_price(s0, rate, -10) == D('830.00')
    assert scenario_price(s0, rate, -1) == D('983.00')
    assert scenario_price(s0, rate, 0) == D('1000.00')
    assert scenario_price(s0, rate, 1) == D('1017.00')
    assert scenario_price(s0, rate, 10) == D('1170.00')


def test_the_literal_published_formula_would_collapse_the_grid():
    """The defect, stated as a test so it cannot be forgotten.

    Read literally the table gives one price, so ``Lk`` takes one value and
    section 4.3's ``Hp`` and ``Lp`` are equal. Our grid does not do that --
    and *that difference is ours*, not the regulation's. Registered as
    ``SOURCE_DEFECTS['D1']`` / ``INFERENCES['I1']``.
    """
    literal = D(1000) * (D(1) + D('0.17') / D(10))
    prices = scenario_prices(D(1000), D('0.17'))
    assert len(set(prices)) == 21, 'the reconstructed grid must be 21 points'
    assert prices[11] == literal, 'k=+1 is where the two readings coincide'
    assert prices[0] != prices[-1], 'Lp and Hp must differ; under the '\
        'literal text they do not'
    assert 'D1' in SOURCE_DEFECTS and 'I1' in INFERENCES


def test_the_extreme_scenarios_are_plus_and_minus_the_published_ratio():
    """Why this reading and not another: it makes ``rate`` mean its name.

    At ``k = +-10`` the price is ``S0 x (1 +- rate)``, so for a directional
    book the worst scenario charges exactly ``rate x notional`` -- which is
    also, numerically, the superseded pre-KRX initial-margin formula. Any
    other reading severs the ratio from what it is called.
    """
    s0, rate = D(1000), D('0.17')
    assert scenario_price(s0, rate, -10) == s0 * (D(1) - rate)
    assert scenario_price(s0, rate, 10) == s0 * (D(1) + rate)


def test_the_scenario_index_is_bounded_by_the_published_range():
    with pytest.raises(MarginInputError, match=r'\[-10, 10\]'):
        scenario_price(D(1000), D('0.17'), 11)


def test_the_scenario_price_is_not_rounded():
    """SILENT -- the appendix never says to round ``Sk``.

    QD 26 Dieu 23.1 fixes rounding for DSP and FSP and says nothing about
    scenario prices, so full Decimal precision is kept and the choice is
    recorded rather than hidden. ``1234.56 x (1 - 0.13) = 1074.0672``, four
    decimals, and it survives.
    """
    assert scenario_price(D('1234.56'), D('0.13'), -10) == D('1074.0672')


# ===========================================================================
# Phu luc 2 section 1.1 -- Lk, and Rm
# ===========================================================================


def test_the_loss_function_is_signed_pnl_not_a_loss_magnitude():
    """**By hand.** 3 long, 1 short, ``S = 1000``, ``M = 100,000``.

    ``Lk = Pm x (Sk - S) x M + Pb x (S - Sk) x M``. At ``Sk = 830``::

        3 x (830 - 1000) x 100,000 = -51,000,000
        1 x (1000 - 830) x 100,000 = +17,000,000
                                     -----------
                                     -34,000,000

    Negative, because the appendix calls ``Lk`` *"Khoan lai/lo"* -- signed
    P&L. A profit at ``Sk = 1170`` is ``+34,000,000`` by the same arithmetic.
    """
    loss = scenario_loss(
        scenario_price_=D(830), close_price=D(1000),
        long_quantity=3, short_quantity=1, multiplier=VN30F_MULTIPLIER,
    )
    assert loss == D(-34000000)
    profit = scenario_loss(
        scenario_price_=D(1170), close_price=D(1000),
        long_quantity=3, short_quantity=1, multiplier=VN30F_MULTIPLIER,
    )
    assert profit == D(34000000)


def test_the_loss_function_nets_the_two_legs_algebraically():
    """DERIVED, and the whole reason ``Sm`` exists.

    ``Lk = Pm(Sk-S)M + Pb(S-Sk)M = (Pm - Pb)(Sk-S)M``. A fully hedged
    calendar book -- 5 long, 5 short -- has ``Lk = 0`` in **every** scenario
    and therefore ``Rm = 0``. That is not an oversight in the rule; QD 26
    Dieu 5.2 defines *ky quy song hanh* to charge back exactly this.
    """
    result = risk_margin('VN30', [vn30(5, 5)], vn30_parameters())
    assert all(s.loss == D(0) for s in result.scenarios)
    assert result.gross == D(0)


def test_risk_margin_is_the_worst_loss_and_equals_rate_times_notional():
    """**By hand.** 3 long / 1 short, net 2 long, ``S = 1000``, rate 17%.

    Every ``Lk`` is ``(3 - 1) x (Sk - 1000) x 100,000``, so the worst is at
    ``k = -10``::

        Rm = |2 x (830 - 1000) x 100,000| = |-34,000,000| = 34,000,000

    Cross-check against the closed form the reconstruction predicts::

        rate x notional = 0.17 x 2 x 1000 x 100,000 = 34,000,000

    The two agree, which is the fourth independent check on the missing-``k``
    reading.
    """
    result = risk_margin('VN30', [vn30(3, 1)], vn30_parameters())
    assert result.gross == D(34000000)
    assert result.worst.k == -10
    assert result.worst.price == D('830.00')
    assert result.gross == D('0.17') * D(2) * D(1000) * VN30F_MULTIPLIER


def test_a_net_short_book_takes_its_worst_loss_on_the_upside():
    """**By hand.** 1 long / 4 short, net 3 short, ``S = 1000``, rate 17%.

    ``Lk = (1 - 4)(Sk - 1000) x 100,000``, most negative when ``Sk`` is
    largest, i.e. ``k = +10``, ``Sk = 1170``::

        Rm = |-3 x 170 x 100,000| = 51,000,000
    """
    result = risk_margin('VN30', [vn30(1, 4)], vn30_parameters())
    assert result.worst.k == 10
    assert result.gross == D(51000000)


def test_risk_margin_never_charges_for_a_profit_because_zero_is_in_the_grid():
    """``Rm = max(0, -min_k Lk)`` -- register id ``I2``, told honestly.

    Section 1.1 says *the absolute value of the largest loss among the
    losses*. With no loss there is no *khoan lo* to take the absolute value
    of, and ``|max Lk|`` would charge margin for a profit -- so the floor is
    a real inference.

    **But the floor is provably unreachable, and this test asserts the
    property that makes it so rather than pretending it fires.** ``k = 0`` is
    in the grid and gives ``Sk = S``, hence ``Lk = 0`` **exactly**, for every
    book whatsoever. So ``min_k Lk <= 0`` always and ``Rm >= 0`` follows
    without the floor doing any work. Deleting the floor changes no result
    today -- and the guarantee it guards is *"zero is bracketed by the
    grid"*, which the second half of this test pins. Re-index the scenarios
    ``1..21`` and the floor becomes the only thing between a profitable book
    and a margin charge.

    Checked across a long, a short and a flat book so the claim is about the
    grid and not about one portfolio.
    """
    assert 0 in SCENARIO_STEPS, 'the zero-move scenario must be in the grid'
    params = vn30_parameters()
    for legs in ([vn30(3, 1)], [vn30(1, 4)], [vn30(2, 2)]):
        result = risk_margin('VN30', legs, params)
        unchanged = [s for s in result.scenarios if s.k == 0]
        assert len(unchanged) == 1
        assert unchanged[0].price == params.closing_price
        assert unchanged[0].loss == D(0)
        assert result.worst.loss <= D(0), 'min_k Lk can never exceed zero'
        assert result.gross >= D(0)
    assert 'I2' in INFERENCES


def test_risk_margin_keeps_all_twenty_one_scenarios_for_audit():
    """A margin number nobody can audit is a margin number nobody should
    trust: the grid survives into the result so a reader can re-derive it."""
    result = risk_margin('VN30', [vn30(3, 1)], vn30_parameters())
    assert len(result.scenarios) == 21
    assert [s.k for s in result.scenarios] == list(range(-10, 11))
    assert result.scenarios[0].row == 1 and result.scenarios[-1].row == 21
    assert result.is_reconstructed_grid is True


def test_risk_margin_sums_legs_with_different_multipliers():
    """Register id ``I18``. Two legs, ``M = 100,000`` and ``M = 10,000``.

    **By hand**, ``S = 1000``, rate 10%, so ``Sk`` at ``k = -10`` is 900::

        leg A: 1 long  x (900-1000) x 100,000 = -10,000,000
        leg B: 1 long  x (900-1000) x  10,000 =  -1,000,000
                                                -----------
                                                -11,000,000

    Section 1.1 is written with one scalar ``M``; summing leg by leg reduces
    to it when ``M`` is constant, which it is for every VN30F contract.
    """
    big = ContractLeg('A', 'VN30', 1, 0, D(100000), D(0))
    small = ContractLeg('B', 'VN30', 1, 0, D(10000), D(0))
    params = vn30_parameters(ratio=D('0.10'))
    result = risk_margin('VN30', [big, small], params)
    assert result.gross == D(11000000)


# ===========================================================================
# Phu luc 2 section 1.3 -- the initial margin ratio, as a CHECKING helper
# ===========================================================================


def test_two_day_returns_compare_T_against_T_minus_2():
    """**By hand.** Prices ``[100, 200, 110, 220, 121]``.

    ``r_t = (S_T - S_{T-2}) / S_{T-2}``, sampled once per trading day
    (overlapping), so the alternating series above gives three observations,
    each exactly 10%::

        t=2: (110 - 100) / 100 = 0.1
        t=3: (220 - 200) / 200 = 0.1
        t=4: (121 - 110) / 110 = 0.1

    The alternation is deliberate: a series whose *one-day* returns are wild
    can have perfectly steady two-day returns, and the T/T-2 convention is
    the thing being tested. Register id ``I14`` -- the source fixes the two
    endpoints and nothing else.
    """
    prices = [D(100), D(200), D(110), D(220), D(121)]
    assert two_day_returns(prices) == (D('0.1'), D('0.1'), D('0.1'))


def test_two_day_returns_need_at_least_three_prices():
    with pytest.raises(MarginInputError, match='at least 3 prices'):
        two_day_returns([D(100), D(101)])


def test_parametric_var_is_mean_plus_three_sigma():
    """**By hand.** Returns ``[0.012, -0.008, 0.012, -0.008, 0.002]``.

    ``mean = (0.012 - 0.008 + 0.012 - 0.008 + 0.002) / 5 = 0.010/5 = 0.002``.
    Deviations from the mean: ``0.01, -0.01, 0.01, -0.01, 0``; squares sum to
    ``4 x 0.0001 = 0.0004``; sample variance ``0.0004 / (5-1) = 0.0001``; so
    ``delta = 0.01``.

    ``VaR = mean + 3 x delta = 0.002 + 0.03 = 0.032``.
    """
    returns = [D('0.012'), D('-0.008'), D('0.012'), D('-0.008'), D('0.002')]
    estimate = parametric_var(returns, minimum_observations=5)
    assert estimate.mean == D('0.002')
    assert estimate.stdev == D('0.010')
    assert estimate.value_at_risk == D('0.032')
    assert estimate.observations == 5


def test_the_var_asymmetry_is_the_source_s_and_is_not_fixed():
    """A negative mean makes ``VaR`` **smaller** than ``3 delta``. Correct.

    Same series with every sign flipped: ``mean = -0.002``, ``delta = 0.01``,
    so ``VaR = -0.002 + 0.03 = 0.028``, which is less than ``3 delta = 0.03``
    and less than ``|mean| + 3 delta = 0.032``.

    Three sigma one-sided is 99.865%; the **two-sided** 3-sigma interval is
    99.73%, the figure section 1.3.a states, so ``VaR`` is the upper bound of
    a two-sided interval and the asymmetry is deliberate drafting. Do not
    "fix" it to ``|mean| + 3 delta`` or ``3 delta - mean``. This test exists
    to make that fix fail.
    """
    returns = [D('-0.012'), D('0.008'), D('-0.012'), D('0.008'), D('-0.002')]
    estimate = parametric_var(returns, minimum_observations=5)
    assert estimate.mean == D('-0.002')
    assert estimate.value_at_risk == D('0.028')
    assert estimate.value_at_risk < D(3) * estimate.stdev


def test_the_observation_window_defaults_to_the_conservative_reading():
    """Section 1.3.a says >=120 days, section 1.3.b says >=250. Both stated.

    They are both minima, so any window at or above 250 satisfies both -- but
    they cannot both be *the* stated minimum, and an implementer choosing 120
    complies with (a) and breaches (b). The default is 250, the binding
    constraint; 120 is reachable only by passing it deliberately. Neither
    reading is resolved. ``SOURCE_DEFECTS['D14']``.
    """
    returns = [D('0.001')] * 200
    with pytest.raises(MarginInputError, match='below the required minimum'):
        parametric_var(returns)
    estimate = parametric_var(
        returns, minimum_observations=MIN_OBSERVATIONS_1_3_A
    )
    assert estimate.minimum_observations == 120
    assert 'D14' in SOURCE_DEFECTS


def test_the_var_result_never_presents_itself_as_the_published_ratio():
    """``SOURCE_DEFECTS['D2']``: the VaR-to-ratio formula is missing.

    Section 1.3.c defines ``n``, announces the conversion and then omits the
    expression, so ``n`` is defined and never used. ``rate = VaR`` at
    ``n = 2`` is the only self-consistent reading available and it is still a
    guess (register id ``I13``) -- which is why it is a **property** with a
    warning rather than a field on the result, so no record can be mistaken
    for a published ratio.
    """
    returns = [D('0.012'), D('-0.008'), D('0.012'), D('-0.008'), D('0.002')]
    estimate = parametric_var(returns, minimum_observations=5)
    fields = {f for f in vars(estimate)}
    assert 'initial_margin_ratio' not in fields
    assert estimate.inferred_initial_margin_ratio == estimate.value_at_risk
    assert 'I13' in INFERENCES and 'D2' in SOURCE_DEFECTS


def test_the_engine_takes_the_published_ratio_and_never_calls_the_helper():
    """The purity rule, at its most concrete.

    ``required_margin`` must not reach for ``parametric_var``: the ratio is
    an input. A grep is the honest test here -- the helper is called from
    nowhere in the module's own body.
    """
    source = inspect.getsource(sm)
    body = source.split('def parametric_var', 1)[1]
    assert 'parametric_var(' not in body


# ===========================================================================
# Phu luc 2 section 2 -- Psr, and the percentile convention
# ===========================================================================


def test_the_percentile_convention_is_explicit_because_the_source_is_silent():
    """**By hand.** Sample ``[0.00, 0.00, 0.01]``, 99th percentile.

    Nearest-rank: ``ceil(0.99 x 3) = 3``, the 3rd smallest, ``0.01``.
    Linear (numpy's default): position ``0.99 x (3-1) = 1.98``, between the
    2nd and 3rd values, ``0.00 + (0.01 - 0.00) x 0.98 = 0.0098``.

    They disagree, which is why the method is a parameter and not a hidden
    convention -- register id ``I7``. On VSDC's sample sizes the difference
    is far below the granularity at which anything is published.
    """
    sample = [D('0.00'), D('0.00'), D('0.01')]
    assert percentile(sample, D(99)) == D('0.01')
    assert percentile(
        sample, D(99), method=PercentileMethod.LINEAR
    ) == D('0.0098')
    assert 'I7' in INFERENCES


def test_price_relation_rate_is_one_minus_a_ratio_not_a_ratio_of_one_minus():
    """**By hand.** ``rx = [0.03, -0.02, 0.01]``, ``ry = [0.02, -0.02, 0.01]``.

    ``|rx - ry| = [0.01, 0.00, 0.00]``; the 99th percentile by nearest rank
    is the largest, ``0.01``. ``Max|rx| = 0.03``, ``Max|ry| = 0.02``, so the
    denominator is ``0.05``::

        Psr = 1 - 0.01 / 0.05 = 1 - 0.2 = 0.8

    Precedence is ``1 - A/B`` and not ``(1-A)/B`` -- register id ``I6``.
    Only the former is bounded above by 1 and reduces to 1 when the two
    series move identically, which is what a rate called a *correlation* must
    do. Under the other reading this would be ``0.99/0.05 = 19.8``, which is
    not a correlation of anything.
    """
    rx = [D('0.03'), D('-0.02'), D('0.01')]
    ry = [D('0.02'), D('-0.02'), D('0.01')]
    assert price_relation_rate(rx, ry) == D('0.8')


def test_identical_series_relate_at_exactly_one():
    """The boundary that fixes the precedence reading: ``Psr = 1``.

    Two underlyings that move identically justify relieving the whole of an
    offsetting pair's risk margin, which is what ``OA = (B+S) x C x 1`` does.
    """
    rx = [D('0.03'), D('-0.02'), D('0.01')]
    assert price_relation_rate(rx, list(rx)) == D(1)


def test_the_group_price_relation_rate_is_the_minimum_over_pairs():
    """**By hand.** Three underlyings; the weakest pair governs.

    ``X = [0.03, -0.02, 0.01]``, ``Y = [0.02, -0.02, 0.01]``,
    ``Z = [0.01, -0.02, 0.01]``. Each pair, by hand::

        X,Y: |diff| = [0.01, 0, 0]     -> Max99 = 0.01
             denominator = 0.03 + 0.02 = 0.05  -> 1 - 0.2  = 0.80
        X,Z: |diff| = [0.02, 0, 0]     -> Max99 = 0.02
             denominator = 0.03 + 0.02 = 0.05  -> 1 - 0.4  = 0.60
        Y,Z: |diff| = [0.01, 0, 0]     -> Max99 = 0.01
             denominator = 0.02 + 0.02 = 0.04  -> 1 - 0.25 = 0.75

    The group takes the smallest, **0.60** -- the ``X,Z`` pair, even though
    ``X,Y`` and ``Y,Z`` are both tighter.

    VERIFIED verbatim: *"He so tuong quan gia cua nhom ... la gia tri nho
    nhat"*. The weakest link governs the relief, which is the conservative
    direction.
    """
    series = {
        'X': [D('0.03'), D('-0.02'), D('0.01')],
        'Y': [D('0.02'), D('-0.02'), D('0.01')],
        'Z': [D('0.01'), D('-0.02'), D('0.01')],
    }
    assert group_price_relation_rate(series) == D('0.6')


def test_psr_cannot_go_negative_so_it_needs_no_floor():
    """DERIVED, and it **corrects the companion spec**.

    ``post-krx-margin-spec.md`` section 5.3(e) records ``Psr`` as SILENT on
    whether it is floored at zero, and speculates that a negative value is
    reachable "only in pathological samples". It is not reachable at all.

    By the triangle inequality, for every observation
    ``|rx - ry| <= |rx| + |ry| <= Max|rx| + Max|ry|`` -- every element of the
    difference set is bounded by the denominator, so any percentile of them
    is too, so ``A/B <= 1`` and ``Psr >= 0`` unconditionally. The upper bound
    ``Psr = 1`` is attained exactly when the two series are identical.

    So ``0 <= Psr <= 1`` always. **No floor is applied and none is needed**,
    which is a decision removed rather than a decision taken.

    **By hand**, the equality case: ``rx = [0.01, -0.01]``,
    ``ry = [-0.01, 0.01]`` -- perfect anti-movement. Differences
    ``[0.02, 0.02]``, ``Max99 = 0.02``; denominator ``0.01 + 0.01 = 0.02``;
    ``Psr = 1 - 1 = 0`` exactly. That is the floor, reached without one.
    """
    assert price_relation_rate(
        [D('0.01'), D('-0.01')], [D('-0.01'), D('0.01')]
    ) == D(0)
    # A deliberately adversarial pair still cannot break the bound.
    adversarial = price_relation_rate(
        [D('0.01'), D('-0.01')], [D('-0.03'), D('0.01')]
    )
    assert D(0) <= adversarial <= D(1)


def test_paired_series_must_be_the_same_length():
    with pytest.raises(MarginInputError, match='paired'):
        price_relation_rate([D('0.01')], [D('0.01'), D('0.02')])


# ===========================================================================
# Phu luc 2 section 2.2 -- the offsetting amount. SYNTHETIC BY NECESSITY.
# ===========================================================================
#
# Every portfolio below is synthetic and has to be. In all data available to
# this project only ONE derivatives underlying ever existed: `quote_close`
# carries 28 contract codes, all `VN30F*`, and VN100F is not ingested
# anywhere -- the only `VN100` string in the corpus is `FUEVN100`, an ETF
# fund certificate on HSX, which is not an index and not a futures
# underlying. So on real data OA is structurally ZERO, and that is the
# correct answer rather than an approximation: QD 26 Dieu 5.1.1.a conditions
# the reduction on positions in "tu hai tai san co so tro len".
#
# Testing OA therefore requires inventing a second underlying. These tests
# invent VN100F with a deliberately different average price, so the scale
# factor is not 1 and the standardisation is actually exercised.


def test_delta_is_the_signed_count_when_multipliers_match():
    """Section 2.2.a. For our corpus this is the identity.

    Every VN30F contract carries ``M = 100,000``, so
    ``delta = position x 100,000 / 100,000`` is the signed contract count
    exactly. Long positive, short negative, verbatim from the appendix.
    """
    assert delta_coefficient(10, D(100000), D(100000)) == D(10)
    assert delta_coefficient(-10, D(100000), D(100000)) == D(-10)


def test_delta_normalises_by_the_largest_multiplier_on_the_underlying():
    """**By hand.** A mini contract at ``M = 10,000`` beside a ``100,000``.

    ``delta = 30 x 10,000 / 100,000 = 3`` -- thirty minis are three standard
    contracts' worth of exposure. VERIFIED verbatim: *"He so nhan lon nhat
    trong cac hop dong co cung tai san co so"*.
    """
    assert delta_coefficient(30, D(10000), D(100000)) == D(3)


def _synthetic_two_underlying_book():
    """A synthetic VN30 / VN100 group. **VN100F does not exist in our data.**

    10 VN30 long against 10 VN100 short, both ``M = 100,000``, VN30 at 1000
    index points and VN100 at 500 -- so VN100's average size is half VN30's
    and the scale factor is a clean 2.
    """
    legs = [
        ContractLeg('VN30F2312', 'VN30', 10, 0, D(100000), D(0)),
        ContractLeg('VN100F2312', 'VN100', 0, 10, D(100000), D(0)),
    ]
    parameters = {
        'VN30': UnderlyingParameters(
            'VN30', D(1000), D('0.17'), D(0), average_price=D(1000)
        ),
        'VN100': UnderlyingParameters(
            'VN100', D(500), D('0.17'), D(0), average_price=D(500)
        ),
    }
    group = UnderlyingGroup('G1', ('VN30', 'VN100'), D('0.9'))
    return legs, parameters, group


def test_the_offsetting_amount_worked_end_to_end():
    """**By hand**, on a synthetic two-underlying book (see the note above).

    Positions: 10 VN30 long, 10 VN100 short. Both ``M = 100,000``.
    VN30 closes and averages 1000; VN100 closes and averages 500.
    ``rate = 17%`` for both; ``Psr = 0.9``.

    *Deltas* (2.2.a), each normalised by the largest multiplier on its own
    underlying, which is 100,000 in both cases::

        delta(VN30)  = +10 x 100,000/100,000 = +10
        delta(VN100) = -10 x 100,000/100,000 = -10

    *Scale factors* (2.2.b)::

        avg size(VN30)  = 1000 x 100,000 = 100,000,000
        avg size(VN100) =  500 x 100,000 =  50,000,000
        largest         = 100,000,000
        scale(VN30)     = 100,000,000 / 100,000,000 = 1
        scale(VN100)    = 100,000,000 /  50,000,000 = 2

    *Standardised contracts* (2.2.c)::

        VN30  = +10 / 1 = +10
        VN100 = -10 / 2 =  -5

    *C* (2.2.d), comparing **magnitudes** -- register id ``I5``::

        C = min(10, |-5|) = 5

    *Gross risk margins*, each ``rate x notional``::

        Rm(VN30)  = 0.17 x 10 x 1000 x 100,000 = 170,000,000
        Rm(VN100) = 0.17 x 10 x  500 x 100,000 =  85,000,000
        group gross                             = 255,000,000

    *B and S*, the risk margin **per standardised contract** on each side --
    register id ``I17``::

        B = 170,000,000 / 10 = 17,000,000
        S =  85,000,000 /  5 = 17,000,000

    They agree, which is the check that standardisation worked: both equal
    ``rate x largest average size = 0.17 x 100,000,000``.

    *OA* (2.2)::

        OA = (17,000,000 + 17,000,000) x 5 x 0.9
           = 34,000,000 x 5 x 0.9
           = 153,000,000
    """
    legs, parameters, group = _synthetic_two_underlying_book()
    risks = {
        name: risk_margin(name, legs, parameters[name]) for name in parameters
    }
    result = offsetting_amount(group, legs, parameters, risks)
    by_name = {p.underlying: p for p in result.positions}
    assert by_name['VN30'].delta == D(10)
    assert by_name['VN100'].delta == D(-10)
    assert by_name['VN30'].scale_factor == D(1)
    assert by_name['VN100'].scale_factor == D(2)
    assert by_name['VN30'].standardised == D(10)
    assert by_name['VN100'].standardised == D(-5)
    assert result.contracts_offset == D(5)
    assert result.positive_leg_margin == D(17000000)
    assert result.negative_leg_margin == D(17000000)
    assert result.amount == D(153000000)


def test_the_offsetting_amount_nets_into_the_group_risk_margin():
    """**By hand**, continuing the synthetic book above.

    ``Rm_gross(group) = 170,000,000 + 85,000,000 = 255,000,000``
    ``OA = 153,000,000``
    ``Rm(group) = max(0, 255,000,000 - 153,000,000) = 102,000,000``

    The subtraction, the group level and the floor are all **INFERRED** --
    register id ``I4``. QD 26 Dieu 5.1.1.a fixes only the *direction*
    (*"so tien dieu chinh giam gia tri ky quy rui ro"*). All three of
    ``risk_margin_gross``, ``offsetting_amount`` and ``risk_margin`` survive
    onto the result so a reader can see which number they are quoting.
    """
    legs, parameters, group = _synthetic_two_underlying_book()
    requirement = required_margin(
        legs, parameters.values(), groups=[group]
    )
    computed = requirement.group('G1')
    assert computed.risk_margin_gross == D(255000000)
    assert computed.offsetting_amount.amount == D(153000000)
    assert computed.risk_margin == D(102000000)
    assert requirement.amount == D(102000000)
    assert 'I4' in INFERENCES


def test_c_compares_magnitudes_so_an_offset_can_never_raise_margin():
    """Register id ``I5``, stated as a consequence rather than a rule.

    Read literally, *"gia tri nho hon"* of ``+10`` and ``-5`` is ``-5``,
    giving ``C < 0`` and an ``OA`` of ``-153,000,000`` -- a hedge that
    *increases* the requirement. The only coherent reading compares absolute
    values, and this test pins the sign.
    """
    legs, parameters, group = _synthetic_two_underlying_book()
    risks = {
        name: risk_margin(name, legs, parameters[name]) for name in parameters
    }
    result = offsetting_amount(group, legs, parameters, risks)
    assert result.contracts_offset > D(0)
    assert result.amount > D(0)


def test_a_one_sided_group_offsets_nothing():
    """``C = 0`` when both members are long. No offset, no relief.

    Also INFERRED (``I5``) -- the source never addresses the one-sided case.
    It is the correct risk answer: two correlated longs are not a hedge.
    """
    legs = [
        ContractLeg('VN30F2312', 'VN30', 10, 0, D(100000), D(0)),
        ContractLeg('VN100F2312', 'VN100', 10, 0, D(100000), D(0)),
    ]
    parameters = {
        'VN30': UnderlyingParameters(
            'VN30', D(1000), D('0.17'), D(0), average_price=D(1000)
        ),
        'VN100': UnderlyingParameters(
            'VN100', D(500), D('0.17'), D(0), average_price=D(500)
        ),
    }
    group = UnderlyingGroup('G1', ('VN30', 'VN100'), D('0.9'))
    risks = {
        name: risk_margin(name, legs, parameters[name]) for name in parameters
    }
    result = offsetting_amount(group, legs, parameters, risks)
    assert result.contracts_offset == D(0)
    assert result.amount == D(0)


def test_a_perfect_correlation_relieves_the_whole_offsetting_pair():
    """``Psr = 1`` gives back ``(B + S) x C`` in full.

    **By hand**, same synthetic book with ``Psr = 1``::

        OA = 34,000,000 x 5 x 1 = 170,000,000
        Rm = max(0, 255,000,000 - 170,000,000) = 85,000,000

    The residue is exactly the unmatched half of the VN100 short -- 5 of its
    10 standardised contracts had no partner -- which is the sanity check
    that the relief lands on the matched part only.
    """
    legs, parameters, _ = _synthetic_two_underlying_book()
    group = UnderlyingGroup('G1', ('VN30', 'VN100'), D(1))
    risks = {
        name: risk_margin(name, legs, parameters[name]) for name in parameters
    }
    result = offsetting_amount(group, legs, parameters, risks)
    assert result.amount == D(170000000)
    assert apply_offsetting_amount(D(255000000), result.amount) == D(85000000)


def test_the_offset_floor_at_zero_is_ours():
    """``I4``, the floor half. Nothing in the source prevents ``OA > Rm``."""
    assert apply_offsetting_amount(D(100), D(250)) == D(0)


def test_the_offsetting_amount_is_refused_for_a_singleton_group():
    """QD 26 Dieu 5.1.1.a: *"tu hai tai san co so tro len"*.

    A single-underlying account gets ``OA = 0`` **by the rule**, so asking
    for one is a category error and raises rather than returning a zero that
    could be mistaken for a computation.
    """
    group = UnderlyingGroup('VN30', ('VN30',))
    with pytest.raises(MarginInputError, match='tu hai tai san co so'):
        offsetting_amount(group, [vn30(1)], {}, {})


def test_a_group_member_without_an_average_price_is_refused():
    """SILENT -- section 2.2.b's observation window is never specified.

    So the average price is an input, and a missing one raises rather than
    silently becoming the closing price.
    """
    legs, parameters, group = _synthetic_two_underlying_book()
    parameters['VN100'] = UnderlyingParameters(
        'VN100', D(500), D('0.17'), D(0)
    )
    with pytest.raises(MarginInputError, match='average_price is required'):
        required_margin(legs, parameters.values(), groups=[group])


def test_a_multi_underlying_group_must_carry_a_price_relation_rate():
    with pytest.raises(MarginInputError, match='price_relation_rate'):
        UnderlyingGroup('G1', ('VN30', 'VN100'))


def test_a_singleton_group_must_not_carry_a_price_relation_rate():
    """A singleton has no pair, so it has no ``Psr`` and no ``OA``."""
    with pytest.raises(MarginInputError, match='singleton'):
        UnderlyingGroup('VN30', ('VN30',), D('0.9'))


# ===========================================================================
# Phu luc 2 section 3 -- ky quy song hanh (Sm)
# ===========================================================================


def test_basis_margin_is_the_smaller_leg():
    """**By hand.** 3 long / 1 short, ``S = 1000``, ``M = 100,000``,
    ``SMrate = 0.004``.

    ``SMl/s = P x S x M x SMrate``::

        SMl = 3 x 1000 x 100,000 x 0.004 = 1,200,000
        SMs = 1 x 1000 x 100,000 x 0.004 =   400,000
        Sm  = Min(1,200,000, 400,000)    =   400,000

    **DERIVED:** ``S``, ``M`` and ``SMrate`` are common to both legs, so
    ``Sm`` reduces to ``min(P_long, P_short) x S x M x SMrate`` -- the
    *matched* portion of the book, which is the only part with a spread to
    mismatch.
    """
    result = basis_margin('VN30', [vn30(3, 1)], vn30_parameters())
    assert result.long_margin == D(1200000)
    assert result.short_margin == D(400000)
    assert result.amount == D(400000)


def test_basis_margin_charges_the_spread_that_risk_margin_netted_away():
    """The complementarity, as one test.

    A perfectly hedged calendar book -- 5 long Jun, 5 short Sep -- pays
    ``Rm = 0``, because ``Lk`` factorises to ``(Pm - Pb)(Sk - S)M``. It pays
    ``Sm = 5 x 1000 x 100,000 x 0.004 = 2,000,000``. QD 26 Dieu 5.2 defines
    *ky quy song hanh* as covering the loss *"tang them so voi gia tri ky quy
    rui ro"*, so the two components hand the spread between them and
    shipping ``Rm`` alone would margin this book at zero.
    """
    legs = [vn30(5, 0, code='VN30F2306'), vn30(0, 5, code='VN30F2309')]
    params = vn30_parameters()
    assert risk_margin('VN30', legs, params).gross == D(0)
    assert basis_margin('VN30', legs, params).amount == D(2000000)


def test_a_one_sided_book_pays_no_basis_margin():
    """``min(P_long, 0) = 0``. Correct: there is no spread to mismatch."""
    result = basis_margin('VN30', [vn30(7, 0)], vn30_parameters())
    assert result.short_margin == D(0)
    assert result.amount == D(0)


def test_the_basis_leg_balances_are_gross_and_summed_across_expiries():
    """Register id ``I8`` -- and the reason a signed net field is refused.

    Two expiry months, 5 long Jun and 5 short Sep. Under a **net** reading
    the account is flat, one leg is zero, and ``Sm`` is identically zero --
    which would make the whole component dead code. Dieu 5.2 applies ``Sm``
    *"cho mot tai san co so"*, so the legs sum across expiry months.
    """
    legs = [vn30(5, 0, code='VN30F2306'), vn30(0, 5, code='VN30F2309')]
    result = basis_margin('VN30', legs, vn30_parameters())
    assert result.long_quantity == 5 and result.short_quantity == 5
    assert result.amount > D(0)
    assert 'I8' in INFERENCES


def test_a_leg_cannot_carry_a_negative_quantity():
    """A short is ``short_quantity``, never a negative ``long_quantity``."""
    with pytest.raises(MarginInputError, match='GROSS balance'):
        ContractLeg('VN30F2312', 'VN30', -3, 0, D(100000), D(0))


def test_the_basis_margin_rate_is_an_input_and_is_never_derived():
    """``SMrate`` is not computed here, by instruction and by data.

    VSDC derives it as the 90th percentile of ``|(rt1 - rt2)/St|`` over
    (spot month, far month) DSP pairs. This project holds no usable daily
    DSP series -- ``quote_settlementprice`` has 18 distinct dates and up to
    261 observations per symbol per day, an intraday tick sample of the wrong
    *shape*, not merely a short one. The module exposes no function that
    would compute it, which is the point.
    """
    assert not [n for n in dir(sm) if 'basis_margin_rate_from' in n]
    assert not [n for n in dir(sm) if n.endswith('_from_series')]


def test_a_missing_basis_margin_rate_is_refused_rather_than_zeroed():
    with pytest.raises(MarginInputError, match='must be a Decimal'):
        UnderlyingParameters('VN30', D(1000), D('0.17'), None)


# ===========================================================================
# Phu luc 2 section 5 -- ky quy toi thieu (MM)
# ===========================================================================


def test_the_minimum_margin_factor_is_a_half_spread_times_notional():
    """**By hand.** ``R = 0.0005``, ``M = 100,000``, ``St = 1000``.

    ``MF = R x M x St = 0.0005 x 100,000 x 1000 = 50,000`` per contract.

    **DERIVED, and the check that the formula was read right:**
    ``(ask - bid)/(ask + bid) = (ask - bid)/(2 x mid)`` is the **half
    relative spread**, so ``MF`` is one contract's cost of crossing the book
    once -- exactly the *"gia dich vu giao dich dong vi the bat buoc"* that
    QD 26 Dieu 5.4 says ``MM`` covers. Sanity: 0.0005 of a 100,000,000 VND
    notional is 50,000 VND, a plausible round-trip cost and nothing like a
    risk charge.
    """
    assert minimum_margin_factor(D('0.0005'), D(100000), D(1000)) == D(50000)


def test_minimum_margin_multiplies_the_gross_position():
    """**By hand.** 3 long / 1 short, ``MF = 50,000``.

    ``P`` is **gross** -- register id ``I9``::

        MM = (3 + 1) x 50,000 = 200,000

    A close-out cost scales with the contracts that have to be *closed*. A
    net reading would give ``2 x 50,000 = 100,000`` and under-charge a
    spread book that still has two legs to unwind.
    """
    result = minimum_margin('VN30', [vn30(3, 1)], vn30_parameters())
    assert result.gross_quantity == 4
    assert result.amount == D(200000)
    assert 'I9' in INFERENCES


def test_the_minimum_margin_is_a_floor_not_an_addend():
    """**By hand.** A flat 2/2 book with ``SMrate = 0``.

    ``Rm = 0`` (perfectly hedged), ``Sm = 0`` (rate zero), ``Dm = 0``, so::

        Pgm = Max(0 + 0 + 0, MM) = Max(0, 200,000) = 200,000
        MR  = Max(200,000, 0)    = 200,000

    ``MM`` is a **cost floor**, which is why section 6.2 applies it with
    ``Max`` and not by addition -- QD 26 Dieu 5.4 calls it *"gia tri ky quy
    nham bu dap chi phi"*, a cost, not a risk. If it were added, this book
    would be margined at 200,000 either way; the difference shows up on the
    3/1 book below, where the floor must **not** add to a 34.4m requirement.
    """
    flat = required_margin([vn30(2, 2)], [vn30_parameters(sm_rate=D(0))])
    assert flat.amount == D(200000)
    assert flat.groups[0].minimum_margin_binds is True
    directional = required_margin([vn30(3, 1)], [vn30_parameters()])
    assert directional.groups[0].minimum_margin_binds is False
    assert directional.amount == D('34400000')


def test_the_minimum_margin_is_zero_on_the_last_trading_day():
    """Register id ``I10``, and the hand-over it implies.

    Section 5.1 says ``MF`` is *"khong duoc xac dinh tai ngay giao dich cuoi
    cung"*. With ``MF`` undefined, ``Max((Rm+Sm+Dm), MM)`` has no second
    operand, so ``MM`` is treated as zero -- which dovetails exactly with
    ``Dm`` switching **on** on that same day. The two components hand over.
    Neither document says so, which is why the affected contract codes are
    reported rather than absorbed into a silent zero.
    """
    leg = vn30(3, 1, minimum_margin_rate=None, is_last_trading_day=True)
    result = minimum_margin('VN30', [leg], vn30_parameters())
    assert result.amount == D(0)
    assert result.undetermined_contracts == ('VN30F2312',)
    assert result.has_last_trading_day_leg is True


def test_a_missing_minimum_margin_rate_off_the_last_trading_day_is_refused():
    """A missing ``R`` is not zero -- zeroing it drops ``Pgm``'s floor."""
    with pytest.raises(MarginInputError, match='minimum_margin_rate'):
        ContractLeg('VN30F2312', 'VN30', 1, 0, D(100000), None)


# ===========================================================================
# Phu luc 2 section 4 -- ky quy chuyen giao (Dm). DEFERRED, bonds only.
# ===========================================================================


def test_delivery_margin_arithmetic_is_implemented_for_completeness_only():
    """**By hand.** ``Aq = 2``, ``Tq = 3``, ``FSP = 101``, ``Cp = 100``,
    ``m = 10,000``; scenario grid from ``S0 = 100`` at ``rate = 5%``.

    ``Lp`` is the ``k = -10`` price and ``Hp`` the ``k = +10`` price::

        Lp = 100 x (1 - 0.05) =  95
        Hp = 100 x (1 + 0.05) = 105

    ``MTM = Aq(FSP - Cp)m + Tq(Cp - FSP)m``::

        2 x (101 - 100) x 10,000 = +20,000
        3 x (100 - 101) x 10,000 = -30,000
                                   -------
                                   -10,000     (signed; it can be negative)

    ``DRM = Aq(Cp - Lp)m + Tq(Hp - Cp)m``::

        2 x (100 -  95) x 10,000 = 100,000
        3 x (105 - 100) x 10,000 = 150,000
                                   -------
                                   250,000     (non-negative when Lp<=Cp<=Hp)

    ``Dm = MTM + DRM = 240,000`` -- and that sum is **INFERRED**, register id
    ``I11``: section 4.1 says only *"gom hai gia tri thanh phan"* and never
    writes the combination.

    **This test verifies arithmetic and nothing else.** Government-bond
    futures are deferred by author decision; there is no GB future in any
    corpus this project holds, so this number has never been checked against
    a real VSDC delivery margin, and the CTD-bond method the whole component
    depends on is in **Phu luc 8, which we do not have**.
    """
    position = DeliveryPosition(
        'GB05F2312', 'GB05', 2, 3, D(101), D(100), D(10000)
    )
    params = UnderlyingParameters('GB05', D(100), D('0.05'), D(0))
    result = delivery_margin(position, params)
    assert result.lowest_price == D(95) and result.highest_price == D(105)
    assert result.mark_to_market == D(-10000)
    assert result.delivery_risk == D(250000)
    assert result.amount == D(240000)
    assert 'I11' in INFERENCES


def test_the_delivery_price_bounds_inherit_the_scenario_defect():
    """``SOURCE_DEFECTS['D1']``, propagated.

    Section 4.3 takes ``Hp`` and ``Lp`` from the section 1.2 grid. Under the
    literal published formula that grid is one point, so ``Hp == Lp``, and
    ``DRM`` collapses to ``Aq x 0 + Tq x 0 = 0``. Our ``DRM`` is non-zero
    only because of the reconstruction, so the deferred component is no more
    sourced than the grid it rests on.
    """
    position = DeliveryPosition(
        'GB05F2312', 'GB05', 2, 3, D(101), D(100), D(10000)
    )
    params = UnderlyingParameters('GB05', D(100), D('0.05'), D(0))
    result = delivery_margin(position, params)
    assert result.highest_price != result.lowest_price
    literal = D(100) * (D(1) + D('0.05') / D(10))
    assert delivery_margin(
        DeliveryPosition(
            'GB05F2312', 'GB05', 2, 3, D(101), D(100), D(10000),
            highest_price=literal, lowest_price=literal,
        )
    ).delivery_risk != result.delivery_risk


def test_delivery_margin_has_no_calendar_and_refuses_to_date_itself():
    """``SOURCE_DEFECTS['D10']`` -- the E+2 hole -- is not silently patched.

    ``Dm`` is stated for the last trading day **E** and **E+1**; settlement
    is **E+3**; and E+2 is a live operational day under QD 26 Dieu 22.4, so
    the literal reading leaves an undelivered position unmargined for
    delivery risk on E+2. This module does not decide the date at all: it
    holds no calendar, and passing a ``DeliveryPosition`` *is* the caller
    asserting that today is a day on which ``Dm`` applies.
    """
    assert 'D10' in SOURCE_DEFECTS
    position = DeliveryPosition(
        'GB05F2312', 'GB05', 2, 3, D(101), D(100), D(10000)
    )
    with pytest.raises(MarginInputError, match='scenario grid'):
        delivery_margin(position)


# ===========================================================================
# Phu luc 2 section 6 -- assembly
# ===========================================================================


def test_the_full_assembly_worked_end_to_end():
    """**By hand**, the whole chain on one VN30F book.

    3 long / 1 short VN30F2312, ``S = 1000``, ``M = 100,000``,
    ``rate = 17%``, ``SMrate = 0.004``, ``R = 0.0005``, no bond delivery.

    ``Rm``  worst scenario ``k = -10``, ``Sk = 830``::

        (3-1) x (830 - 1000) x 100,000 = -34,000,000  ->  Rm = 34,000,000

    ``OA``  zero: one underlying, so QD 26 Dieu 5.1.1.a's precondition of
    *"tu hai tai san co so tro len"* is not met. **By the rule, not by a
    shortcut.**

    ``Sm``  ``min(3, 1) x 1000 x 100,000 x 0.004 = 400,000``

    ``Dm``  zero: index futures, not government bonds.

    ``MM``  ``(3+1) x (0.0005 x 100,000 x 1000) = 4 x 50,000 = 200,000``

    ``Pgm = Max(34,000,000 + 400,000 + 0, 200,000) = 34,400,000``
    ``MR  = Max(34,400,000, 0) = 34,400,000``
    """
    requirement = required_margin(
        [vn30(3, 1)], [vn30_parameters()], account_id='INV-1'
    )
    group = requirement.groups[0]
    assert group.risk_margin_gross == D(34000000)
    assert group.offsetting_amount is None
    assert group.risk_margin == D(34000000)
    assert group.basis_margin == D(400000)
    assert group.delivery_margin == D(0)
    assert group.minimum_margin == D(200000)
    assert group.amount == D(34400000)
    assert requirement.amount == D(34400000)
    assert requirement.account_id == 'INV-1'


def test_an_ungrouped_underlying_forms_a_singleton_group():
    """Register id ``I3`` -- and it binds on the simplest thing we can build.

    Section 2.1 only provides for groups of two or more and never says what
    happens to an underlying in no group, which is the ordinary case and the
    only case this project's corpora contain. Section 6.1 sums ``Pgm`` over
    *"cac nhom tai san co so"*, so an ungrouped underlying must still produce
    a ``Pgm`` -- otherwise its risk vanishes from ``MR`` entirely. That is
    the only reading under which ``MR`` is well-defined for a
    single-product account, and it is not in the text.
    """
    requirement = required_margin([vn30(3, 1)], [vn30_parameters()])
    assert [g.group_id for g in requirement.groups] == ['VN30']
    assert requirement.groups[0].underlyings == ('VN30',)
    assert requirement.groups[0].offsetting_amount is None
    assert 'I3' in INFERENCES


def test_groups_sum_and_are_mutually_exclusive():
    """Section 2.1: *"mot tai san co so chi thuoc mot nhom"*.

    An underlying named in two supplied groups raises rather than being
    counted twice -- silently double-counting would inflate ``MR``, which is
    the safe direction and still wrong.
    """
    group_a = UnderlyingGroup('A', ('VN30', 'VN100'), D('0.9'))
    group_b = UnderlyingGroup('B', ('VN100', 'HNX30'), D('0.9'))
    with pytest.raises(MarginInputError, match='chi thuoc mot nhom'):
        required_margin(
            [vn30(1)], [vn30_parameters()], groups=[group_a, group_b]
        )


def test_two_singleton_groups_add():
    """**By hand.** VN30 and a synthetic second underlying, ungrouped.

    Two directional books, 1 long each, both ``M = 100,000``, ``rate = 10%``,
    ``SMrate = 0``, ``R = 0``. VN30 at 1000, the other at 500::

        Pgm(VN30)  = 0.10 x 1 x 1000 x 100,000 = 10,000,000
        Pgm(OTHER) = 0.10 x 1 x  500 x 100,000 =  5,000,000
        MR                                     = 15,000,000

    With no group, no relief: strict per-underlying summation over-charges a
    correlated pair and never under-charges it, which is the right default
    when VSDC has published no group.
    """
    legs = [
        ContractLeg('VN30F2312', 'VN30', 1, 0, D(100000), D(0)),
        ContractLeg('OTHERF2312', 'OTHER', 1, 0, D(100000), D(0)),
    ]
    parameters = [
        UnderlyingParameters('VN30', D(1000), D('0.10'), D(0)),
        UnderlyingParameters('OTHER', D(500), D('0.10'), D(0)),
    ]
    requirement = required_margin(legs, parameters)
    assert len(requirement.groups) == 2
    assert requirement.amount == D(15000000)


def test_the_outer_max_against_zero_is_dead_code_and_that_is_the_point():
    """DERIVED, and it is one of the two props under ``INFERENCES['I4']``.

    Every component of section 6.2 is non-negative on its face and ``Pgm`` is
    a ``Max`` against ``MM >= 0``, so ``Pgm >= 0`` and ``Sum Pgm >= 0``. The
    outer ``Max(..., 0)`` of section 6.1 can therefore never bind. The clause
    exists in the gazetted text anyway, which is weak evidence that a drafter
    expected some component to be capable of going negative -- and
    ``Rm_gross - OA`` is the obvious candidate.
    """
    requirement = required_margin([vn30(3, 1)], [vn30_parameters()])
    assert requirement.outer_floor_binds is False
    flat = required_margin([vn30(2, 2)], [vn30_parameters(sm_rate=D(0))])
    assert flat.outer_floor_binds is False


def test_variation_margin_is_not_a_component_of_mr():
    """Post-KRX, ``MR`` is not ``IM + VM``. Verified by absence and by text.

    QD 26 Dieu 20 settles *lai lo vi the* as a **separate** cash movement on
    the working day after VSDC notifies it, netted per clearing member. Daily
    P&L leaves the system as cash; it is not carried as a margin add-on. This
    module has no field, parameter or code path for it, and this test is what
    stops one being added by analogy with the pre-KRX ``deposit.py``.
    """
    identifiers = _defined_identifiers()
    for banned in ('variation', 'unrealised', 'unrealized', 'pnl'):
        assert not [n for n in identifiers if banned in n.lower()], (
            f'{banned} appears as an identifier: MR has no VM term'
        )


def test_the_account_is_the_unit_and_an_empty_book_is_refused():
    """QD 26 Dieu 5.5: MR is computed for the position portfolio on each
    investor trading account, so an account with no positions has no ``MR``
    to compute -- and a zero returned for one could be read as a margin
    number."""
    with pytest.raises(MarginInputError, match='no legs'):
        required_margin([], [vn30_parameters()])


def test_an_underlying_without_parameters_is_refused():
    """A missing underlying is not a flat one."""
    leg = ContractLeg('XF2312', 'X', 1, 0, D(100000), D(0))
    with pytest.raises(MarginInputError, match='no UnderlyingParameters'):
        required_margin([leg], [vn30_parameters()])


def test_a_partially_held_group_is_refused_rather_than_guessed():
    """The source defines ``OA`` for a group, not for part of one.

    An account holding VN30 but not VN100 out of a published VN30+VN100
    group has no defined offsetting amount. Rather than silently dropping the
    absent member -- which would change ``C`` and the scale factors -- this
    raises and tells the caller to state what they mean.
    """
    group = UnderlyingGroup('G1', ('VN30', 'VN100'), D('0.9'))
    with pytest.raises(MarginInputError, match='partially held'):
        required_margin([vn30(1)], [vn30_parameters()], groups=[group])


# ===========================================================================
# QD 26 Dieu 13 -- the violation test and the timeline. The author's goal.
# ===========================================================================

D0 = date(2025, 6, 2)   # Monday
D1 = date(2025, 6, 3)
D2 = date(2025, 6, 4)
D3 = date(2025, 6, 5)


def close(on, assets, required):
    return MarginObservation(Checkpoint.CLOSE_1630, on, assets, required)


def open_0930(on, assets):
    return MarginObservation(Checkpoint.OPEN_0930, on, assets)


def midday(on, assets):
    return MarginObservation(Checkpoint.MIDDAY_1400, on, assets)


def test_the_violation_test_is_binary_with_no_ladder_anywhere():
    """QD 26 Dieu 13.1: *"tai san ky quy ... nho hon ... ky quy yeu cau"*.

    **That is the whole test.** No ratio, no threshold, no 80/90/100. The
    article was read in full. The ladder a reader may be looking for is
    **Dieu 29** and applies to *gioi han vi the* -- a contract count against
    a published position cap. Different numerator, different denominator,
    different units, different remedy.

    This test also asserts the module contains no such ladder, which is what
    stops one arriving later by analogy with the pre-KRX ``deposit.py``.
    """
    assert is_margin_violation(D(999), D(1000)) is True
    assert is_margin_violation(D(1001), D(1000)) is False
    source = inspect.getsource(sm)
    for banned in (
        'warning_utilisation', 'margin_call_utilisation',
        'forced_close_utilisation', 'utilisation',
    ):
        assert banned not in source
    assert "D('0.8')" not in source and "D('0.9')" not in source


def test_equality_is_cured_not_breached():
    """Dieu 13.2.c restores on *"bang hoac lon hon muc ky quy yeu cau"*.

    Equal to **or greater than**. So the comparison is a strict ``<`` and
    ``assets == MR`` is compliant. This differs by exactly one tick from the
    pre-KRX path in ``deposit.py``, which treats ``assets == MR`` as a
    breach; both sides are deliberate and each is pinned by its own test.
    """
    assert is_margin_violation(D(1000), D(1000)) is False
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    monitor.observe(open_0930(D1, D(900)))
    assert monitor.state is MarginViolationState.SUSPENDED
    events = monitor.observe(midday(D1, D(1000)))
    assert monitor.state is MarginViolationState.COMPLIANT
    assert [e.kind for e in events] == [MarginEventKind.RESTORED]


def test_the_checkpoints_are_the_three_the_article_names():
    """09h30, 14h00, 16h30 -- VERIFIED from Dieu 13.2, and only these.

    Post-KRX monitoring is **not continuous**. The pre-KRX depository page
    described VSD monitoring *"theo thoi gian thuc"*; QD 26 replaces that
    with an end-of-day MR plus three fixed checkpoints, which is a change in
    the shape of the model rather than a rewording.
    """
    assert set(Checkpoint) == {
        Checkpoint.OPEN_0930, Checkpoint.MIDDAY_1400, Checkpoint.CLOSE_1630
    }
    assert CHECKPOINT_TIME[Checkpoint.OPEN_0930] == time(9, 30)
    assert CHECKPOINT_TIME[Checkpoint.MIDDAY_1400] == time(14, 0)
    assert CHECKPOINT_TIME[Checkpoint.CLOSE_1630] == time(16, 30)


def test_the_end_of_day_shortfall_notifies_and_sets_a_0930_deadline():
    """Dieu 13.1. **By hand:** assets 900 against MR 1,000, shortfall 100.

    By 16h30 VSDC determines MR per account and notifies the member; the
    top-up is due *"truoc 09h30 ngay giao dich lien ke tiep theo"*. The
    account is **notified, not yet suspended** -- register id ``I21``, since
    Dieu 13.2 gives the suspension to the 09h30 checkpoint alone.
    """
    monitor = MarginViolationMonitor(next_trading_day=lambda d: D1)
    events = monitor.observe(close(D0, D(900), D(1000)))
    assert len(events) == 1
    event = events[0]
    assert event.kind is MarginEventKind.SHORTFALL_NOTIFIED
    assert event.state is MarginViolationState.NOTIFIED
    assert event.shortfall == D(100)
    assert event.cure_by_time == time(9, 30)
    assert event.cure_by_date == D1
    assert event.detail['cited'] == 'QD 26 Dieu 13.1'
    assert monitor.state.permits_opening is True


def test_0930_suspends_a_new_violation_and_bars_opening_trades():
    """Dieu 13.2.a, the article's operative sanction.

    Against the requirement determined on the **previous** working day, VSDC
    identifies newly violating accounts, asks HNX to suspend them, and tells
    the member *"khong thuc hien giao dich mo moi vi the ... ngoai tru giao
    dich doi ung de dong vi the"* -- no opening trades, offsetting closes
    only. The suspension is the thing the author's simulation needs, so both
    halves of that gate are asserted.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    events = monitor.observe(open_0930(D1, D(900)))
    assert [e.kind for e in events] == [MarginEventKind.SUSPENDED]
    assert monitor.state is MarginViolationState.SUSPENDED
    assert monitor.permits_opening is False
    assert monitor.state.permits_closing is True
    assert 'offsetting' in events[0].detail['restriction']


def test_0930_tests_against_the_previous_days_notified_requirement():
    """Dieu 13.2.a: *"muc ky quy yeu cau xac dinh tai ngay lam viec lien
    truoc"*.

    The 09h30 and 14h00 checkpoints do **not** recompute MR -- only 16h30
    does (Dieu 13.2.c). Supplying a fresh requirement at 09h30 is refused
    rather than quietly ignored, because a caller who passes one there has
    misread the article.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    assert monitor.notified_requirement == D(1000)
    with pytest.raises(MarginInputError, match='PREVIOUS'):
        MarginObservation(Checkpoint.OPEN_0930, D1, D(900), D(500))


def test_a_0930_check_before_any_determination_is_refused():
    """There is no *"ngay lam viec lien truoc"* on the first day."""
    monitor = MarginViolationMonitor()
    with pytest.raises(MarginTimelineError, match='CLOSE_1630'):
        monitor.observe(open_0930(D0, D(900)))


def test_topping_up_before_0930_cures_without_a_suspension():
    """Dieu 13.1's deadline, met. The account is never suspended.

    **By hand:** notified short 100 at 16h30 on D0; assets raised to 1,000 by
    09h30 on D1; ``assets >= MR``, so the violation is cured and trading was
    never restricted.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    events = monitor.observe(open_0930(D1, D(1000)))
    assert [e.kind for e in events] == [MarginEventKind.CURED]
    assert monitor.state is MarginViolationState.COMPLIANT
    assert monitor.permits_opening is True
    assert monitor.notice_date is None


def test_1400_restores_an_account_that_has_cured():
    """Dieu 13.2.b: VSDC re-checks all violating accounts and restores the
    ones that have met the requirement."""
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    monitor.observe(open_0930(D1, D(900)))
    events = monitor.observe(midday(D1, D(1200)))
    assert [e.kind for e in events] == [MarginEventKind.RESTORED]
    assert events[0].detail['cited'] == 'QD 26 Dieu 13.2.b'
    assert monitor.state is MarginViolationState.COMPLIANT


def test_1630_recomputes_and_restores_a_suspended_account():
    """Dieu 13.2.c. The requirement is fresh here, unlike at 09h30 / 14h00.

    **By hand:** suspended against MR 1,000 with assets 900. At 16h30 the
    position has been partly closed, so MR falls to 800 while assets stay at
    900: ``900 >= 800``, restored. Note the cure came from **reducing the
    position** -- Dieu 13.3.b's second remedy -- not from posting cash.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    monitor.observe(open_0930(D1, D(900)))
    assert monitor.state is MarginViolationState.SUSPENDED
    events = monitor.observe(close(D1, D(900), D(800)))
    assert [e.kind for e in events] == [MarginEventKind.RESTORED]
    assert events[0].detail['cited'] == 'QD 26 Dieu 13.2.c'
    assert monitor.state is MarginViolationState.COMPLIANT
    assert monitor.notified_requirement == D(800)


def test_the_violation_persists_across_sessions_until_cured():
    """**The point of modelling this as state.**

    A one-shot "margin call happened" boolean cannot express a suspension
    that survives overnight. Here the account is short at 16h30 on D0 and
    stays short through every checkpoint of D1 and D2: the suspension
    persists, no duplicate event is emitted, and the close-out clock keeps
    running underneath.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    monitor.observe(open_0930(D1, D(900)))
    assert monitor.state is MarginViolationState.SUSPENDED
    for observation in (
        midday(D1, D(900)), close(D1, D(900), D(1000)),
        open_0930(D2, D(900)), midday(D2, D(900)),
    ):
        assert monitor.observe(observation) == ()
        assert monitor.state is MarginViolationState.SUSPENDED
    assert len(monitor.events) == 2
    assert monitor.notice_date == D0


def test_uncured_for_three_working_days_directs_a_close_out():
    """Dieu 13.3.b -- the escalation the author's simulation is aiming at.

    *"Trong thoi han 03 ngay lam viec ke tu ngay VSDC gui dien thong bao vi
    pham ... ma thanh vien bu tru van khong khac phuc duoc vi pham, VSDC se
    yeu cau thanh vien bu tru khac thuc hien dong vi the"* -- another
    clearing member is directed to place the offsetting trades, and the
    resulting positions transfer to the violating member to net off.

    **The timeline, by hand.** Notice at 16h30 on D0. Working days are
    counted strictly after the notice (register id ``I20``), so D1 is day 1,
    D2 is day 2, and at the first checkpoint of D3 the count reaches 3 and
    the close-out is directed.

    Note Dieu 13.3.b's own cross-reference is broken -- it points at *"diem a
    khoan 1 Dieu nay"* and khoan 1 has no lettered points
    (``SOURCE_DEFECTS['D13']``); the intended target is almost certainly
    diem a khoan **2**, the 09h30 checkpoint.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    monitor.observe(open_0930(D1, D(900)))
    assert monitor.working_days_since_notice(D1) == 1
    monitor.observe(open_0930(D2, D(900)))
    assert monitor.working_days_since_notice(D2) == 2
    events = monitor.observe(open_0930(D3, D(900)))
    assert [e.kind for e in events] == [MarginEventKind.CLOSE_OUT_DIRECTED]
    assert events[0].working_days_elapsed == 3
    assert events[0].detail['cited'] == 'QD 26 Dieu 13.3.b'
    assert 'another clearing member' in events[0].detail['action']
    assert monitor.state is MarginViolationState.CLOSED_OUT
    assert monitor.state.permits_opening is False


def test_a_cure_on_the_final_morning_beats_the_close_out():
    """Cure is evaluated before escalation, and the order matters.

    An account that tops up on the morning of the third day is **restored**,
    not closed out. The source does not state the order; this is the only
    order that does not close out an account which has just complied.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    monitor.observe(open_0930(D1, D(900)))
    monitor.observe(open_0930(D2, D(900)))
    events = monitor.observe(open_0930(D3, D(1000)))
    assert [e.kind for e in events] == [MarginEventKind.RESTORED]
    assert monitor.state is MarginViolationState.COMPLIANT


def test_the_close_out_clock_does_not_restart_on_a_later_shortfall():
    """Register id ``I20``. A restarting clock defers close-out forever.

    The account is re-determined short at 16h30 on D1 and D2 -- Dieu 13.2.a
    expressly excludes accounts *"dang vi pham"* from the new-violation check
    -- and the notice date stays at D0, so the close-out still lands on D3.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    monitor.observe(open_0930(D1, D(900)))
    monitor.observe(close(D1, D(850), D(1000)))
    monitor.observe(close(D2, D(800), D(1000)))
    assert monitor.notice_date == D0
    events = monitor.observe(open_0930(D3, D(800)))
    assert [e.kind for e in events] == [MarginEventKind.CLOSE_OUT_DIRECTED]


def test_the_inclusive_reading_of_ke_tu_ngay_is_reachable():
    """The other reading of *"ke tu ngay"*, one day tighter.

    Counting the notice day itself, D0 is day 1, D1 day 2 and D2 day 3, so
    the close-out lands a day earlier. The source resolves neither reading,
    so both are reachable and the default is stated rather than hidden.
    """
    monitor = MarginViolationMonitor(include_notice_day=True)
    monitor.observe(close(D0, D(900), D(1000)))
    monitor.observe(open_0930(D1, D(900)))
    events = monitor.observe(open_0930(D2, D(900)))
    assert [e.kind for e in events] == [MarginEventKind.CLOSE_OUT_DIRECTED]


def test_close_out_is_terminal():
    """The positions are gone: another member closed them. No further
    transitions, and no event on a later observation."""
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    monitor.observe(open_0930(D1, D(900)))
    monitor.observe(open_0930(D2, D(900)))
    monitor.observe(open_0930(D3, D(900)))
    assert monitor.state is MarginViolationState.CLOSED_OUT
    assert monitor.observe(close(D3, D(5000), D(1000))) == ()
    assert monitor.state is MarginViolationState.CLOSED_OUT


def test_a_skipped_checkpoint_advances_no_state():
    """A blind stretch does not expire a deadline.

    If the caller feeds no observation, nothing moves and no working day is
    counted -- the same discipline ``deposit.py``'s ``MarginMonitor`` applies
    to an ``INDETERMINATE`` mark. Here D1 and D2 are never observed, so on D3
    only one working day has elapsed and the account is suspended rather than
    closed out.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(900), D(1000)))
    events = monitor.observe(open_0930(D3, D(900)))
    assert [e.kind for e in events] == [MarginEventKind.SUSPENDED]
    assert monitor.working_days_since_notice(D3) == 1


def test_1400_never_suspends_a_compliant_account():
    """Register id ``I21``. Dieu 13.2.b examines only accounts already in
    violation and its only action is restoration.

    Reading it as a second suspension gate would invent an enforcement action
    the article does not give. An account that was compliant at yesterday's
    close and looks short at 14h00 is left alone until 16h30 re-determines.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(1200), D(1000)))
    assert monitor.observe(midday(D1, D(500))) == ()
    assert monitor.state is MarginViolationState.COMPLIANT


def test_0930_suspends_an_account_that_was_compliant_at_the_last_close():
    """Dieu 13.2.a's *"tai khoan vi pham moi"*, the intraday-withdrawal case.

    The requirement is fixed at yesterday's number but assets can leave, so
    an account compliant at 16h30 can be short at 09h30 against that same
    requirement. That is exactly what "newly violating" means.
    """
    monitor = MarginViolationMonitor()
    monitor.observe(close(D0, D(1200), D(1000)))
    events = monitor.observe(open_0930(D1, D(500)))
    assert [e.kind for e in events] == [MarginEventKind.SUSPENDED]
    assert monitor.state is MarginViolationState.SUSPENDED


def test_every_transition_emits_exactly_one_event_and_nothing_else_does():
    """The event log reconstructs the whole history, with no duplicates.

    Notified on D0, suspended on D1, restored at 14h00 on D1: three
    transitions, three events, and every checkpoint in between silent.
    """
    monitor = MarginViolationMonitor()
    observations = [
        close(D0, D(900), D(1000)),
        open_0930(D1, D(900)),
        midday(D1, D(1500)),
        close(D1, D(1500), D(1000)),
        open_0930(D2, D(1500)),
    ]
    emitted = [monitor.observe(o) for o in observations]
    assert [len(e) for e in emitted] == [1, 1, 1, 0, 0]
    assert [e.kind for e in monitor.events] == [
        MarginEventKind.SHORTFALL_NOTIFIED,
        MarginEventKind.SUSPENDED,
        MarginEventKind.RESTORED,
    ]
    assert [e.previous_state for e in monitor.events] == [
        MarginViolationState.COMPLIANT,
        MarginViolationState.NOTIFIED,
        MarginViolationState.SUSPENDED,
    ]


def test_observations_may_not_go_backwards():
    monitor = MarginViolationMonitor()
    monitor.observe(close(D2, D(900), D(1000)))
    with pytest.raises(MarginTimelineError, match='backwards'):
        monitor.observe(open_0930(D0, D(900)))


def test_the_monitor_holds_no_calendar_and_says_so():
    """Purity, at the one place a clock would have crept in.

    Without a supplied ``next_trading_day`` the 09h30 deadline is still
    expressed -- ``cure_by_time`` is always 09h30 -- and the **date** is left
    ``None`` rather than guessed. A calendar is a data source, and the
    engine does not acquire one.
    """
    monitor = MarginViolationMonitor()
    event = monitor.observe(close(D0, D(900), D(1000)))[0]
    assert event.cure_by_time == time(9, 30)
    assert event.cure_by_date is None


def test_the_margin_asset_side_is_supplied_and_never_valued_here():
    """``SOURCE_DEFECTS['D3']`` -- Dieu 8.1's valuation formula is missing.

    All seven variables are glossed (``VKQ``, ``C``, ``MR``, ``x = 80%``,
    ``QKQ``, ``P``, ``H``) and the expression combining them is absent from
    the extraction. The haircuts are known -- 5% / 30% / 40% at Dieu 9.1 --
    and the arithmetic is not. Guessing it would put an invented number on
    the other side of the only test that matters, so margin assets arrive as
    a scalar and this module values no collateral.
    """
    identifiers = _defined_identifiers()
    for banned in ('haircut', 'collateral', 'vkq', 'discount_rate'):
        assert not [n for n in identifiers if banned in n.lower()], (
            f'{banned} appears as an identifier: the engine is valuing '
            'collateral, which Dieu 8.1 does not give us the formula for'
        )
    assert 'margin_assets' in identifiers
    assert 'D3' in SOURCE_DEFECTS
