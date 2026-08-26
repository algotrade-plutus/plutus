"""Tests for the broker margin profiles.

Three kinds of test live here and they are doing different jobs.

**Numeric tests** carry their arithmetic in the docstring, so a reader can
check it without running anything. The important ones are in
:func:`test_targeting_closes_sixteen_times_what_clearing_the_rung_closes` and
:func:`test_falling_coverage_reduction_uses_the_reciprocal`, because those are
where axis 1 and axis 3 stop being labels and become money.

**Provenance tests** assert things about the *coverage declaration* rather
than about margin: that a supplied field says who supplied it, that a
delegated ladder refuses to run, that a homonym cannot be read as the wrong
quantity. These are the tests that make the honesty guarantee mechanical
instead of a docstring promise. :func:`test_a_fully_sourced_profile_is_silent`
is the load-bearing one: it pins that silence means *fully sourced* and never
*we did not check*.

**Architectural tests** -- :func:`test_the_module_contains_no_float_literal`,
:func:`test_the_module_imports_neither_margin_engine` and
:func:`test_every_gap_id_cited_in_the_module_is_in_the_register` -- exist
because "Decimal never float", "selects a model, does not compute one" and
"the register cannot fall behind the code" are properties a reviewer cannot
check by reading a long module, and a property nobody can check is a property
that decays.
"""

import ast
import dataclasses
import inspect
import re
import warnings
from datetime import date
from decimal import Decimal

import pytest

from plutus.market.broker import BrokerTerms
from plutus.market.session import broker_profile as bp
from plutus.market.session.broker_profile import (
    Action, AdvisoryCoverageWarning, BrokerProfile, BuyingPowerSpec,
    Cap, CcpBreachTest, Coverage, CoverageError, CureKind, CureSpec,
    DenominatorBasis, DenominatorSpec, Derivation, Direction, FieldCoverage,
    GAP_KINDS, GapKind, HomonymError, LiabilitiesTreatment,
    MINIMUM_MARGIN_FACTOR, MarginLayer, MarginModel, MaterialCoverageWarning,
    NUMERIC_FIELDS, Notice, OPEN_QUESTIONS, PLUTUS_DEFAULT, PROFILE_NAMES,
    PathStep, Regime, Rung, Severity, SourceClass, SynthesisWarning, TargetRef,
    assess, forced_reduction, get_profile, liquidation_path, list_profiles,
    notice_steps_before_liquidation, resolve_target,
)

D = Decimal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _published(quantity):
    """A coverage record with no gap of any kind."""
    return FieldCoverage(status=Coverage.PUBLISHED, quantity=quantity,
                         source_class=SourceClass.SIGNED_TC,
                         source_url='https://example.invalid/terms',
                         effective_from=date(2026, 1, 1),
                         fetched_on=date(2026, 8, 26))


def fully_sourced_profile(**overrides):
    """A profile with every field published and no gap anywhere.

    It exists to pin the one property the whole coverage machinery rests on:
    a profile with nothing missing says nothing.
    """
    ladder = (
        Rung(coverage_key='block_open_level', name='rung 1', level=D('0.80'),
             action=Action.BLOCK_OPENING, target_ref=TargetRef.NONE,
             notice=Notice.REQUIRED, cure=CureSpec(CureKind.IMMEDIATE)),
        Rung(coverage_key='margin_call_level', name='rung 2', level=D('0.90'),
             action=Action.NOTIFY, target_ref=TargetRef.RUNG_1,
             notice=Notice.REQUIRED,
             cure=CureSpec(CureKind.SESSIONS, sessions=1)),
        Rung(coverage_key='forced_close_level', name='rung 3', level=D('0.95'),
             action=Action.LIQUIDATE, target_ref=TargetRef.RUNG_1,
             notice=Notice.REQUIRED, cure=CureSpec(CureKind.IMMEDIATE)),
    )
    coverage = {key: _published(key) for key in (
        'direction', 'denominator', 'liabilities_treatment',
        'margin_model_intraday', 'margin_model_overnight',
        'initial_margin_ratio', 'target', 'notification', 'cure_window',
        'block_open_level', 'margin_call_level', 'forced_close_level')}
    kwargs = dict(
        firm='EXAMPLE', is_synthesis=False, regime=Regime.POST_KRX,
        document_date=date(2026, 1, 1),
        margin_model_intraday=MarginModel.IM_PLUS_VM_PLUS_DM,
        margin_model_overnight=MarginModel.SCENARIO_GRID,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(DenominatorBasis.V_KQ,
                                    LiabilitiesTreatment.IGNORED,
                                    securities_cap_fraction=D('0.20')),
        ladder=ladder, coverage=coverage,
        initial_margin_ratio=D('0.18'),
    )
    kwargs.update(overrides)
    return BrokerProfile(**kwargs)


# ---------------------------------------------------------------------------
# Architectural
# ---------------------------------------------------------------------------


def test_the_module_contains_no_float_literal():
    """House rule: Decimal for money and ratios, never float.

    A single ``0.8`` in a rung level would make one firm's ladder compare
    unequal to another's identical ladder, and would do it silently.
    """
    tree = ast.parse(inspect.getsource(bp))
    floats = [node for node in ast.walk(tree)
              if isinstance(node, ast.Constant) and isinstance(node.value,
                                                               float)]
    assert floats == [], f'float literals at lines ' \
                         f'{[n.lineno for n in floats]}'


def test_the_module_imports_neither_margin_engine():
    """This module **selects** a model; it must not compute one.

    ``MarginModel.engine`` returns a module *name*, deliberately. If this file
    imported ``scenario_margin`` or ``deposit`` to say which engine applies,
    the selection layer would acquire the dependency graph of both engines and
    the profile object could no longer be built without them.
    """
    tree = ast.parse(inspect.getsource(bp))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    plutus_imports = {name for name in imported if name.startswith('plutus')}
    assert plutus_imports == {'plutus.market.broker'}, plutus_imports
    assert MarginModel.SCENARIO_GRID.engine.endswith('scenario_margin')
    assert MarginModel.IM_PLUS_VM_PLUS_DM.engine.endswith('deposit')
    assert MarginModel.UNSTATED.engine is None


def test_every_gap_id_cited_in_the_module_is_in_the_register():
    """The register cannot silently fall behind the code.

    Every ``Gn`` mentioned anywhere in the module -- docstring, note or
    enum -- must have an entry in :data:`GAP_KINDS` explaining what it means
    and which firm and sentence produced it.
    """
    cited = set(re.findall(r'\bG(\d{1,2})\b', inspect.getsource(bp)))
    known = {key[1:] for key in GAP_KINDS}
    assert cited <= known, f'cited but unregistered: {sorted(cited - known)}'
    assert {kind.value for kind in GapKind} == set(GAP_KINDS)


def test_every_gap_kind_names_a_firm():
    """A gap kind with no exemplar is a category we invented.

    Each entry must name at least one surveyed firm, so the taxonomy stays
    grounded in the evidence rather than drifting into what a taxonomy
    designer imagines might exist.
    """
    firms = ('TCBS', 'SSI', 'VNDIRECT', 'FPTS', 'SHS', 'Vietcap', 'HSC',
             'MBS', 'KIS', 'VPS', 'Pinetree', 'DNSE', 'VCBS', 'ACBS')
    for key, meaning in GAP_KINDS.items():
        assert any(firm in meaning for firm in firms) or 'BrokerProfile' in \
            meaning, f'{key} names no firm'


def test_open_questions_are_surfaced_not_resolved():
    """Every open question says what was done meanwhile.

    The house rule is that a silence or a contradiction is surfaced, not
    resolved silently. An entry that poses a question and does not say what
    the code does in the meantime has resolved it silently.
    """
    assert set(OPEN_QUESTIONS) >= {'Q1', 'Q2', 'Q3', 'Q4', 'Q5'}
    for key, text in OPEN_QUESTIONS.items():
        assert 'MEANWHILE' in text, key


# ---------------------------------------------------------------------------
# Axis 1 -- direction
# ---------------------------------------------------------------------------


def test_direction_compares_in_opposite_senses():
    """The whole of axis 1, in one assertion pair.

    Utilisation 0.90 against a 0.90 rung is a breach; coverage 0.90 against a
    0.90 rung is also a breach (equality counts either way), but coverage 0.95
    is *safe* where utilisation 0.95 is not.
    """
    rising, falling = Direction.RISING_UTILISATION, Direction.FALLING_COVERAGE
    assert rising.is_at_or_past(D('0.90'), D('0.90'))
    assert falling.is_at_or_past(D('0.90'), D('0.90'))
    assert rising.is_at_or_past(D('0.95'), D('0.90'))
    assert not falling.is_at_or_past(D('0.95'), D('0.90'))
    assert not rising.is_at_or_past(D('0.85'), D('0.90'))
    assert falling.is_at_or_past(D('0.85'), D('0.90'))


def test_a_ladder_ordered_against_its_direction_raises():
    """A descending rising-utilisation ladder fires its severest rung first."""
    assert Direction.RISING_UTILISATION.ladder_is_ordered(
        [D('0.80'), D('0.90'), D('0.95')])
    assert not Direction.RISING_UTILISATION.ladder_is_ordered(
        [D('1.00'), D('0.80'), D('0.60')])
    assert Direction.FALLING_COVERAGE.ladder_is_ordered(
        [D('1.00'), D('0.80'), D('0.60')])
    with pytest.raises(ValueError, match='mild-to-severe'):
        fully_sourced_profile(direction=Direction.FALLING_COVERAGE)


def test_hsc_is_the_only_falling_coverage_firm():
    profiles = {}
    for name in PROFILE_NAMES:
        try:
            profiles[name] = get_profile(name, warn=False)
        except CoverageError:
            profiles[name] = get_profile(name, fill_from=PLUTUS_DEFAULT,
                                         warn=False)
    falling = [name for name, p in profiles.items()
               if p.direction is Direction.FALLING_COVERAGE]
    assert falling == ['HSC']


def test_the_same_seventy_percent_is_a_breach_at_hsc_and_safe_elsewhere():
    """Direction is not presentation. It decides who gets called.

    An account with ``required = 100,000`` and ``assets = 70,000``:

    * under HSC, coverage is ``70,000 / 100,000 = 0.70``, which is at or below
      the 0.80 rung -- HSC's *"Yeu cau ky quy"* band, ``60% <= R < 80%``, a
      call;
    * an account with ``required = 70,000`` and ``assets = 100,000`` has
      utilisation ``0.70`` under PLUTUS_DEFAULT, below the 0.80 rung -- safe.

    Same two numbers, opposite verdicts, because the ratio runs the other way.

    The rung *name* is asserted because HSC's table is written as bands and
    the band boundaries are one step out from where a threshold reading puts
    them: ``R = 0.70`` is in *Yeu cau ky quy*, while *Ky quy duy tri* is the
    band above it (``80% <= R < 100%``), where HSC expressly does **not**
    call and only blocks opening.
    """
    hsc = get_profile('HSC', warn=False)
    called = assess(hsc, required=D('100000'), assets=D('70000'),
                    warn_once=False)
    assert called.ratio == D('0.7')
    assert called.rung.name == 'Yeu cau ky quy'
    assert called.action is Action.NOTIFY
    assert hsc.ladder[0].name == 'Ky quy duy tri'
    assert hsc.ladder[0].action is Action.BLOCK_OPENING

    safe = assess(PLUTUS_DEFAULT, required=D('70000'), assets=D('100000'),
                  warn_once=False)
    assert safe.ratio == D('0.7')
    assert safe.rung_index is None
    assert not safe.is_breach


# ---------------------------------------------------------------------------
# Axis 2 -- the denominator
# ---------------------------------------------------------------------------


def test_four_denominator_bases_are_in_the_shipped_set():
    """The brief calls this the single most commonly-missed field."""
    bases = {get_profile(name, warn=False).denominator.basis
             for name in ('VNDIRECT', 'VCBS', 'HSC', 'FPTS', 'TCBS')}
    assert DenominatorBasis.NET_ASSETS in bases       # VNDIRECT
    assert DenominatorBasis.CASH_ONLY in bases        # VCBS as stated
    assert DenominatorBasis.INITIAL_MARGIN in bases   # HSC
    assert DenominatorBasis.V_KQ in bases             # FPTS
    assert DenominatorBasis.UNPUBLISHED in bases      # TCBS


def test_liabilities_treatment_is_three_valued_not_a_boolean():
    """Three conventions are in evidence and two of them are minorities.

    FPTS and VNDIRECT subtract debts from the divisor; SHS adds them to the
    numerator. Both raise utilisation, and by different amounts on the same
    book, so a boolean ``subtracts_liabilities`` would merge two firms that
    disagree.
    """
    seen = {name: get_profile(name, fill_from=PLUTUS_DEFAULT,
                              warn=False).denominator.liabilities
            for name in ('FPTS', 'VNDIRECT', 'SHS', 'MBS')}
    assert seen['FPTS'] is LiabilitiesTreatment.SUBTRACTED_FROM_ASSETS
    assert seen['VNDIRECT'] is LiabilitiesTreatment.SUBTRACTED_FROM_ASSETS
    assert seen['SHS'] is LiabilitiesTreatment.ADDED_TO_NUMERATOR
    assert seen['MBS'] is LiabilitiesTreatment.IGNORED
    assert len(set(seen.values())) == 3


def test_the_securities_cap_is_only_meaningful_on_a_v_kq_basis():
    with pytest.raises(ValueError, match='QD 26 Dieu 8'):
        DenominatorSpec(DenominatorBasis.V_KQ, LiabilitiesTreatment.IGNORED,
                        securities_cap_fraction=D('1.5'))


# ---------------------------------------------------------------------------
# Axis 3 -- fire vs target
# ---------------------------------------------------------------------------


def test_targeting_closes_sixteen_times_what_clearing_the_rung_closes():
    """The quantity axis 3 exists to make measurable.

    Account: ``assets = 1,000,000``, ``required = 960,000``, so utilisation is
    ``0.96`` and PLUTUS_DEFAULT's 0.95 forced-close rung has fired.

    * **Clear the rung** -- get utilisation to 0.95:
      ``960,000 - 0.95 x 1,000,000 = 10,000`` of requirement closed.
    * **Restore to the target**, which PLUTUS_DEFAULT sets to rung 1 (0.80):
      ``960,000 - 0.80 x 1,000,000 = 160,000``.

    Sixteen times the forced selling, from the same three percentages. A
    ``{warn, call, liquidate}`` triple cannot express the difference.
    """
    assets, required = D('1000000'), D('960000')
    state = assess(PLUTUS_DEFAULT, required=required, assets=assets,
                   warn_once=False)
    assert state.ratio == D('0.96')
    assert state.rung.coverage_key == 'forced_close_level'
    assert state.target_level == D('0.80')
    assert forced_reduction(PLUTUS_DEFAULT, required=required,
                            assets=assets) == D('160000')

    fire_once = fully_sourced_profile(
        ladder=tuple(
            rung if rung.coverage_key != 'forced_close_level'
            else Rung(coverage_key='forced_close_level', name='rung 3',
                      level=D('0.95'), action=Action.LIQUIDATE,
                      target_ref=TargetRef.NONE, notice=Notice.REQUIRED,
                      cure=CureSpec(CureKind.IMMEDIATE))
            for rung in fully_sourced_profile().ladder))
    assert forced_reduction(fire_once, required=required,
                            assets=assets) == D('10000')


def test_falling_coverage_reduction_uses_the_reciprocal():
    """Under HSC the algebra flips, and the flip is not cosmetic.

    Account: ``assets = 70,000``, ``required = 100,000``. Coverage is 0.70, at
    or below the 0.80 call rung, and HSC restores to that same rung.
    Coverage ``assets / required >= 0.80`` needs
    ``required <= 70,000 / 0.80 = 87,500``, so ``100,000 - 87,500 = 12,500``
    of requirement must go.

    Applying the rising-utilisation formula here would give
    ``100,000 - 0.80 x 70,000 = 44,000`` -- three and a half times too much
    forced selling, from getting one sign wrong.
    """
    hsc = get_profile('HSC', warn=False)
    assert forced_reduction(hsc, required=D('100000'),
                            assets=D('70000')) == D('12500')


def test_forced_reduction_refuses_where_no_firm_action_is_published():
    """VNDIRECT publishes three thresholds and no action text at any of them.

    Clearing the rung and restoring to a target are different amounts, and
    VNDIRECT says which only by not saying. Guessing would invent the whole of
    the forced sale, so the call raises.
    """
    vnd = get_profile('VNDIRECT', warn=False)
    assert vnd.coverage['target'].gap is GapKind.G5_ACTION_UNKNOWN
    with pytest.raises(CoverageError, match='no action semantics'):
        forced_reduction(vnd, required=D('960000'), assets=D('1000000'))


def test_no_breach_means_no_forced_selling():
    assert forced_reduction(PLUTUS_DEFAULT, required=D('100000'),
                            assets=D('1000000')) == D('0')


def test_the_target_is_a_reference_so_it_moves_with_rung_one():
    """Every firm publishes its target as *"back to the named rung"*.

    Encoding it as a reference rather than a number means that overriding rung
    1 moves the target with it, which is what the firms' own sentences say
    happens.
    """
    moved = fully_sourced_profile(
        ladder=tuple(
            Rung(coverage_key=rung.coverage_key, name=rung.name,
                 level=D('0.70') if rung.coverage_key == 'block_open_level'
                 else rung.level,
                 action=rung.action, target_ref=rung.target_ref,
                 notice=rung.notice, cure=rung.cure)
            for rung in fully_sourced_profile().ladder))
    assert resolve_target(moved, moved.ladder[2]) == D('0.70')
    assert forced_reduction(moved, required=D('960000'),
                            assets=D('1000000')) == D('260000')


def test_vietcap_is_the_one_firm_with_an_absolute_target():
    """Vietcap publishes 90 and 95 and no level 1, so 85 cannot be a reference.

    That absence is itself recorded: reading the 85 as rung 1 would invent a
    threshold Vietcap does not have.
    """
    vc = get_profile('Vietcap', warn=False)
    assert vc.ladder[0].target_ref is TargetRef.ABSOLUTE
    assert resolve_target(vc, vc.ladder[0]) == D('0.85')
    assert vc.coverage['block_open_level'].status is Coverage.UNPUBLISHED


def test_a_target_absolute_without_the_ref_raises():
    with pytest.raises(ValueError, match='target_absolute is set'):
        Rung(coverage_key='x', name='x', level=D('0.9'),
             action=Action.LIQUIDATE, target_ref=TargetRef.RUNG_1,
             target_absolute=D('0.8'))
    with pytest.raises(ValueError, match='needs target_absolute'):
        Rung(coverage_key='x', name='x', level=D('0.9'),
             action=Action.LIQUIDATE, target_ref=TargetRef.ABSOLUTE)


def test_ssi_publishes_a_remedy_ordering_and_it_is_not_liquidation():
    """SSI moves collateral **before** it closes positions.

    Modelling Muc 3 as pure liquidation over-states forced selling at SSI, and
    dropping the second half under-states it, so the ordering is a field.
    """
    ssi = get_profile('SSI', warn=False)
    top = ssi.ladder[2]
    assert top.action is Action.TRANSFER_COLLATERAL
    assert top.follow_on is Action.LIQUIDATE
    state = assess(ssi, required=D('990000'), assets=D('1000000'),
                   warn_once=False)
    assert state.action is Action.TRANSFER_COLLATERAL
    assert state.closes_positions        # the follow-on still closes


# ---------------------------------------------------------------------------
# Axis 4 -- notification and cure
# ---------------------------------------------------------------------------


def test_kis_liquidates_with_no_notice_and_no_cure():
    """Brief test 3, and the measurable consequence of axis 4.

    KIS disclaims notification at level 1 and disclaims *prior* notice at
    level 3, and its cure window is *"trong thoi han theo yeu cau cua KIS"* --
    discretionary, so it cannot be relied on to be non-zero. Its path is one
    step. SSI's is three, one of which is a notice it owes.
    """
    kis = get_profile('KIS', fill_from=PLUTUS_DEFAULT, warn=False)
    ssi = get_profile('SSI', warn=False)
    assert kis.ladder[2].notice is Notice.DISCLAIMED
    assert liquidation_path(kis) == (PathStep.LIQUIDATE,)
    assert notice_steps_before_liquidation(kis) == 0
    assert PathStep.NOTIFY in liquidation_path(ssi)
    assert notice_steps_before_liquidation(ssi) >= 1
    assert notice_steps_before_liquidation(PLUTUS_DEFAULT) == 2


def test_a_right_to_notify_is_not_a_notice_step():
    """MBS and VPS both write *"co quyen nhung khong co nghia vu"*.

    A right the firm need not exercise is not time the account can rely on, so
    it produces no ``NOTIFY`` step. Treating it as one would over-state
    survival at both firms.
    """
    for name in ('MBS', 'VPS'):
        profile = get_profile(name, fill_from=PLUTUS_DEFAULT, warn=False)
        assert profile.ladder[0].notice is Notice.RIGHT_NOT_DUTY
        assert not profile.ladder[0].notice.is_obligation
        assert notice_steps_before_liquidation(profile) == 0


def test_a_delegated_cure_window_grants_no_time():
    """The conservative reading, and it is deliberate.

    A window whose length the firm sets at its own discretion cannot be
    assumed non-zero; assuming it is over-states survival.
    """
    assert not CureSpec(CureKind.DELEGATED).grants_time
    assert not CureSpec(CureKind.UNKNOWN).grants_time
    assert CureSpec(CureKind.SESSIONS, sessions=1).grants_time
    assert CureSpec(CureKind.DEADLINE, deadline='11:30 T+1').grants_time


def test_cure_spec_rejects_a_session_count_it_cannot_mean():
    with pytest.raises(ValueError, match='needs a session count'):
        CureSpec(CureKind.SESSIONS)
    with pytest.raises(ValueError, match='meaningless'):
        CureSpec(CureKind.IMMEDIATE, sessions=1)
    with pytest.raises(ValueError, match='needs its deadline text'):
        CureSpec(CureKind.DEADLINE)


def test_hsc_is_the_only_complete_timeline():
    """Notice 16:30 T, cure 11:30 T+1, force-close 13:00 T+1.

    No other surveyed firm publishes all three, which is why HSC ships despite
    a page dated five years before the KRX cutover.
    """
    hsc = get_profile('HSC', warn=False)
    call = hsc.ladder[1]
    assert call.notice is Notice.REQUIRED
    assert call.cure.kind is CureKind.DEADLINE
    assert '11:30 T+1' in call.cure.deadline
    assert '16:30 T' in call.cure.deadline


# ---------------------------------------------------------------------------
# Axis 5 / the coverage declaration
# ---------------------------------------------------------------------------


def test_a_fully_sourced_profile_is_silent():
    """**Silence means fully sourced. It must never mean "we did not check".**

    This is the property the whole coverage machinery exists to deliver, and
    it is the one that would decay first if it were only a docstring.
    """
    profile = fully_sourced_profile()
    assert profile.gaps() == ()
    assert profile.material_caveats() == ()
    assert profile.supplied_fields() == ()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        profile.warn()
    assert caught == []


def test_every_shipped_profile_with_gaps_warns():
    """The converse: nothing ships silently unless it is genuinely sourced."""
    for name in PROFILE_NAMES:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            try:
                profile = get_profile(name)
            except CoverageError:
                profile = get_profile(name, fill_from=PLUTUS_DEFAULT)
        assert profile.gaps(), f'{name} declares no gap at all'
        assert caught, f'{name} has gaps and warned nothing'


def test_material_and_advisory_warnings_are_separable():
    """A caller must be able to filter timing caveats without losing the
    ones that change the number."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        get_profile('SSI')
    classes = {type(record.message) for record in caught}
    assert MaterialCoverageWarning in classes
    assert AdvisoryCoverageWarning in classes


def test_assess_stamps_the_material_caveats_on_every_result():
    """A number cannot be lifted out of a notebook and quoted clean."""
    ssi = get_profile('SSI', warn=False)
    state = assess(ssi, required=D('900000'), assets=D('1000000'),
                   warn_once=False)
    assert state.caveats == ssi.material_caveats()
    assert any('margin_model_intraday' in caveat for caveat in state.caveats)


def test_ssi_publishes_no_model_and_says_so(recwarn):
    """Brief test 1. SSI's page is a parameter table with no formula on it.

    The 17% on that page is *"Ty le ky quy rui ro"* -- the scenario grid's
    risk rate -- and a reader will take it for an IM ratio in an ``IM + VM``
    model. So ``initial_margin_ratio`` is deliberately ``None`` rather than
    0.17, and the model field is UNPUBLISHED rather than guessed.
    """
    ssi = get_profile('SSI', warn=False)
    assert ssi.coverage['margin_model_intraday'].status is Coverage.UNPUBLISHED
    assert ssi.margin_model is MarginModel.UNSTATED
    assert ssi.margin_engine is None
    assert ssi.initial_margin_ratio is None
    assert '17%' in ssi.coverage['initial_margin_ratio'].note

    assess(ssi, required=D('900000'), assets=D('1000000'))
    material = [w for w in recwarn
                if issubclass(w.category, MaterialCoverageWarning)]
    assert any('margin_model_intraday' in str(w.message) for w in material)


def test_a_delegated_ladder_refuses_to_run(recwarn):
    """Brief test 2. Five named ratios, five delegations, and no numbers.

    ``get_profile('MBS')`` raises rather than inheriting somebody else's
    ladder, because a silently-substituted rung produces confident, wrong
    margin-call incidence. With an explicit opt-in it runs, and every filled
    field says who filled it.
    """
    with pytest.raises(CoverageError, match='not on its public site'):
        get_profile('MBS')

    mbs = get_profile('MBS', fill_from=PLUTUS_DEFAULT)
    supplied = mbs.supplied_fields()
    assert set(supplied) == {'margin_call_level', 'forced_close_level',
                             'ccp_processing_level', 'post_open_level',
                             'post_withdrawal_level'}
    for key in supplied:
        assert mbs.coverage[key].status is Coverage.FILLED_FROM_DEFAULT
        assert mbs.coverage[key].filled_from == 'PLUTUS_DEFAULT'
    assert mbs.blocking_fields() == ()
    assert [rung.level for rung in mbs.ladder] == [D('0.90'), D('0.95'),
                                                   D('1.00')]
    assert any('SUPPLIED BY US' in str(w.message) for w in recwarn)


def test_a_supplied_field_renders_unmissably():
    """*A user reading SSI's page must never be misled by a field we
    supplied* -- as a rendered string, not a promise."""
    mbs = get_profile('MBS', fill_from=PLUTUS_DEFAULT, warn=False)
    rendered = mbs.render_coverage()
    assert 'SUPPLIED BY PLUTUS_DEFAULT' in rendered
    assert 'SUPPLIED-BY-US' in repr(mbs)
    assert 'SUPPLIED-BY-US' not in repr(get_profile('SSI', warn=False))


def test_published_supplied_and_inferred_partition_cleanly():
    """Three claims, kept apart, because they are three different claims.

    *Published* is the firm's number. *Supplied* is somebody else's number we
    put in the firm's slot. *Inferred* is our reading of what the firm did
    publish -- SSI's parameter set identifies the scenario grid whether or not
    SSI writes the assembly down. A reader checking a value against SSI's page
    needs to know which of the three they are holding.
    """
    ssi = get_profile('SSI', warn=False)
    assert 'block_open_level' in ssi.published_fields()
    assert ssi.supplied_fields() == ()
    assert ssi.inferred_fields() == ('margin_model_overnight',)
    assert not set(ssi.published_fields()) & set(ssi.inferred_fields())
    assert PLUTUS_DEFAULT.published_fields() == ()
    assert PLUTUS_DEFAULT.supplied_fields() == ()
    assert len(PLUTUS_DEFAULT.inferred_fields()) == len(
        PLUTUS_DEFAULT.coverage)


def test_numbers_published_is_false_exactly_for_the_delegating_firms():
    """Brief axis 5, and it is a real split in the survey."""
    for name in ('SSI', 'TCBS', 'FPTS', 'VNDIRECT', 'SHS'):
        assert get_profile(name, warn=False).numbers_published, name
    for name in ('MBS', 'KIS', 'VPS'):
        profile = get_profile(name, fill_from=PLUTUS_DEFAULT, warn=False)
        assert not profile.numbers_published, name


def test_an_illustrative_number_is_not_a_published_one():
    """TCBS's ``Rm 3%`` / ``Sm 1%`` pass any naive "is there a number?" test.

    They are a teaching example; the operative rates are delegated to a VSD
    table that was never located. ``is_published`` must therefore reject them
    even though a number is printed.
    """
    tcbs = get_profile('TCBS', warn=False)
    rates = tcbs.coverage['vsdc_parameters']
    assert rates.status is Coverage.PUBLISHED_ILLUSTRATIVE
    assert not rates.is_published
    assert rates.gap is GapKind.G2_PUBLISHED_ILLUSTRATIVE
    assert 'vsdc_parameters' not in tcbs.published_fields()


def test_inapplicable_is_not_unknown():
    """Brief test 5. ACBS has no ladder; it does not have an unknown one.

    A user told that ACBS's forced-close level is *unknown* has been misled:
    there is nothing to know.
    """
    acbs = get_profile('ACBS', warn=False)
    assert acbs.coverage['forced_close_level'].status is Coverage.INAPPLICABLE
    assert acbs.coverage['forced_close_level'].gap is GapKind.G15_INAPPLICABLE
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        get_profile('ACBS')
    text = ' '.join(str(record.message) for record in caught)
    assert 'ACBS operates no utilisation ladder' in text
    assert 'forced_close_level: UNPUBLISHED' not in text
    assert acbs.buying_power == BuyingPowerSpec(
        retained_cash_fraction=D('0.05'),
        description=acbs.buying_power.description)


def test_the_acbs_reserve_is_buying_power_not_a_rung():
    """``x (1 + 5%)`` on buying power, never a threshold on a ratio.

    1,050,000d of cash under a 5% retained-cash reserve buys 1,000,000d of
    position. That changes *when* an account would reach a rung without being
    a rung, and merging it with QD 26 Dieu 8's 80% collateral cap or VCBS's
    100% eligibility rule is defect D-28.
    """
    acbs = get_profile('ACBS', warn=False)
    assert acbs.ladder == ()
    assert acbs.buying_power.scale(D('1050000')) == D('1000000')


def test_vps_carries_a_source_defect_and_is_not_enabled_by_default():
    """Brief test 6. We do not repair a counterparty's contract.

    Section 1.13 makes the maintenance ratio a minimum; Part E section 4.4(c)
    requires forcing it below that minimum. Direction is taken from 4.4(c) and
    the disagreement is recorded rather than erased.
    """
    vps = get_profile('VPS', fill_from=PLUTUS_DEFAULT, warn=False)
    defect = vps.coverage['direction'].source_defect
    assert defect
    assert '1.13' in defect and '4.4(c)' in defect
    assert vps.coverage['direction'].status is Coverage.CONTRADICTORY
    assert vps.coverage['direction'].gap is \
        GapKind.G14_SOURCE_SELF_CONTRADICTORY
    assert 'VPS' not in bp.ENABLED_BY_DEFAULT
    assert not vps.enabled_by_default


def test_vps_safety_ratio_lives_outside_the_ladder():
    """Section 4.3's escape hatch. Its numerator is net asset value.

    It is neither a utilisation nor a coverage ratio and its formula is not
    published, so forcing it into the ladder would misrepresent it and
    dropping it would hide a live warning dimension.
    """
    vps = get_profile('VPS', fill_from=PLUTUS_DEFAULT, warn=False)
    assert len(vps.additional_ratios) == 1
    ratio = vps.additional_ratios[0]
    assert ratio.name == 'Ty le an toan'
    assert not ratio.formula_published
    assert 'tai san rong' in ratio.denominator


def test_a_contradiction_must_explain_itself():
    with pytest.raises(ValueError, match='requires source_defect'):
        FieldCoverage(status=Coverage.CONTRADICTORY, quantity='x',
                      source_class=SourceClass.SIGNED_TC)


def test_a_supplied_field_must_name_its_filler():
    with pytest.raises(ValueError, match='requires filled_from'):
        FieldCoverage(status=Coverage.FILLED_FROM_DEFAULT, quantity='x',
                      source_class=SourceClass.OURS)
    with pytest.raises(ValueError, match='only FILLED_FROM_DEFAULT'):
        FieldCoverage(status=Coverage.PUBLISHED, quantity='x',
                      source_class=SourceClass.OURS, filled_from='us')


def test_a_coverage_record_must_say_what_quantity_it_is():
    """Gap kind G18 is why. A record that carries only the number and its
    source cannot tell you the number means something else."""
    with pytest.raises(ValueError, match='quantity is required'):
        FieldCoverage(status=Coverage.PUBLISHED, quantity='',
                      source_class=SourceClass.SIGNED_TC)


def test_every_shipped_contradiction_names_its_clauses():
    for name in PROFILE_NAMES:
        try:
            profile = get_profile(name, warn=False)
        except CoverageError:
            profile = get_profile(name, fill_from=PLUTUS_DEFAULT, warn=False)
        for key, cov in profile.coverage.items():
            if cov.status is Coverage.CONTRADICTORY:
                assert cov.source_defect, f'{name}.{key}'


# ---------------------------------------------------------------------------
# Gap kind G18 -- the homonym, and the F-2 regression
# ---------------------------------------------------------------------------


def test_ssis_per_contract_row_never_becomes_mf():
    """Brief test 4. The single most destructive misreading in the survey.

    SSI publishes *"Gia tri ky quy toi thieu/1HD: 34.520.710 dong"* and TCBS
    publishes 5,000d under the same phrase. Mapping SSI's row into ``MF``
    makes ``MM = P x MF`` bind on every book and destroys
    ``MR = max(Rm + Sm - OA, MM)``.

    ``MF`` is derived, not read: ``MF = tick x M / 2 = 0.1 x 100,000 / 2``
    (research S-11), and it is index-independent.
    """
    ssi = get_profile('SSI', warn=False)
    entry = ssi.coverage['minimum_margin_factor']
    assert entry.quantity == 'total per-contract requirement'
    assert entry.quantity != 'MF'
    assert entry.gap is GapKind.G18_HOMONYM
    assert ssi.minimum_margin_factor == D('5000') == MINIMUM_MARGIN_FACTOR
    assert ssi.published_per_contract_requirement == D('34520710')

    tcbs = get_profile('TCBS', warn=False)
    assert 'MF' in tcbs.coverage['minimum_margin_factor'].quantity
    assert tcbs.minimum_margin_factor == D('5000')


def test_the_implied_index_level_is_what_settles_the_homonym():
    """OURS, and it is exact arithmetic on the firms' own numbers.

    ``34,520,710 / ((0.17 + 0.0087) x 100,000) = 1931.77`` and
    ``22,309,440 / ((0.17 + 0.0042) x 100,000) = 1280.68``. Both are plausible
    VN30 levels of different vintages. A policy constant would not track the
    index; these do, so they are dated snapshots of a total requirement.
    """
    ssi = get_profile('SSI', warn=False)
    shs = get_profile('SHS', warn=False)
    assert round(ssi.implied_index_level(D('0.17'), D('0.0087')), 1) == \
        D('1931.8')
    assert round(shs.implied_index_level(D('0.17'), D('0.0042')), 1) == \
        D('1280.7')


def test_asking_for_an_implied_level_where_none_is_published_raises():
    with pytest.raises(HomonymError, match='different quantities'):
        get_profile('TCBS', warn=False).implied_index_level(D('0.17'),
                                                            D('0.0087'))


def test_the_module_registers_its_own_homonym_with_types_broker_profile():
    """Our own code has a G18: two different classes named ``BrokerProfile``.

    Registered rather than papered over, and :data:`MarginBrokerProfile` is
    the collision-free name for a module that must import both.
    """
    from plutus.market.session import types as session_types
    assert session_types.BrokerProfile is not BrokerProfile
    assert bp.MarginBrokerProfile is BrokerProfile
    assert 'BrokerProfile' in GAP_KINDS['G18']


# ---------------------------------------------------------------------------
# The sixth axis -- margin model selection
# ---------------------------------------------------------------------------


def test_a_profile_selects_which_model_faces_the_user():
    """One user-facing number, and the profile says which layer produces it."""
    assert PLUTUS_DEFAULT.user_facing_model is MarginLayer.INTRADAY
    assert PLUTUS_DEFAULT.margin_model is MarginModel.IM_PLUS_VM_PLUS_DM
    assert PLUTUS_DEFAULT.margin_engine.endswith('deposit')

    overnight = fully_sourced_profile(user_facing_model=MarginLayer.OVERNIGHT)
    assert overnight.margin_model is MarginModel.SCENARIO_GRID
    assert overnight.margin_engine.endswith('scenario_margin')


def test_both_layers_are_carried_because_the_evidence_carries_both():
    """F-1: ten of ten firms that state a client formula state IM+VM+DM, and
    the four that publish scenario-grid material scope it to the CCP.

    So the two models are two layers of one firm's answer, not two firms'
    answers to one question, and a profile that could hold only one would have
    to discard evidence.
    """
    fpts = get_profile('FPTS', warn=False)
    assert fpts.margin_model_intraday is MarginModel.IM_PLUS_VM_PLUS_DM
    assert fpts.margin_model_overnight is MarginModel.SCENARIO_GRID
    assert MarginModel.IM_PLUS_VM_PLUS_DM.is_continuous
    assert not MarginModel.SCENARIO_GRID.is_continuous
    assert 'Q1' in OPEN_QUESTIONS


def test_the_intraday_models_of_the_firms_that_state_one_are_unanimous():
    stated = {}
    for name in ('MBS', 'KIS', 'VPS', 'VNDIRECT', 'FPTS', 'SHS', 'Vietcap'):
        try:
            profile = get_profile(name, warn=False)
        except CoverageError:
            profile = get_profile(name, fill_from=PLUTUS_DEFAULT, warn=False)
        stated[name] = profile.margin_model_intraday
    assert MarginModel.SCENARIO_GRID not in stated.values()
    assert all(model in (MarginModel.IM_PLUS_VM_PLUS_DM,
                         MarginModel.IM_PLUS_VM)
               for model in stated.values()), stated


def test_hsc_is_the_only_im_over_mm_model():
    assert get_profile('HSC', warn=False).margin_model_intraday is \
        MarginModel.IM_ONLY_WITH_MM


# ---------------------------------------------------------------------------
# PLUTUS_DEFAULT
# ---------------------------------------------------------------------------


def test_the_default_is_a_synthesis_and_says_so(recwarn):
    """Brief test 7. If a real firm were the default, a caller who chose no
    broker would silently inherit one firm's commercial policy."""
    assert bp.DEFAULT_PROFILE_NAME == 'PLUTUS_DEFAULT'
    assert PLUTUS_DEFAULT.is_synthesis
    get_profile()
    synthesis = [w for w in recwarn if issubclass(w.category,
                                                  SynthesisWarning)]
    assert synthesis
    assert 'matches no firm exactly' in str(synthesis[0].message)
    for name in PROFILE_NAMES:
        if name != 'PLUTUS_DEFAULT':
            assert not bp._BUILDERS[name]().is_synthesis, name


def test_the_default_ladder_is_eighty_ninety_ninety_five_targeting_eighty():
    levels = [rung.level for rung in PLUTUS_DEFAULT.ladder]
    assert levels == [D('0.80'), D('0.90'), D('0.95')]
    assert PLUTUS_DEFAULT.ladder[2].target_ref is TargetRef.RUNG_1
    assert resolve_target(PLUTUS_DEFAULT, PLUTUS_DEFAULT.ladder[2]) == D('0.80')
    assert PLUTUS_DEFAULT.level_for('post_withdrawal_level') == D('0.80')


def test_every_default_number_is_a_number_some_real_firm_uses():
    """The point of a median over an arithmetic mean.

    80 is FPTS, VNDIRECT and Pinetree; 90 is five firms; 95 is SSI, Vietcap
    and Pinetree; 17.85% is FPTS's actual ratio. Nothing here is a synthetic
    midpoint nobody applies.
    """
    assert PLUTUS_DEFAULT.initial_margin_ratio == D('0.1785')
    assert get_profile('FPTS', warn=False).initial_margin_ratio == D('0.1785')
    assert get_profile('Pinetree', warn=False).ladder[0].level == D('0.80')
    assert get_profile('SSI', warn=False).ladder[2].level == D('0.95')


def test_every_numeric_default_records_rule_sources_and_n():
    """The author's rule 4, made checkable.

    *A field derived from two firms must not look like one derived from five.*
    """
    for key in NUMERIC_FIELDS:
        derivation = PLUTUS_DEFAULT.coverage[key].derivation
        assert derivation is not None, key
        assert derivation.rule, key
        assert derivation.sources, key
        assert derivation.n >= 1, key
        assert derivation.n >= len(derivation.sources), key


def test_an_n_of_one_refuses_to_call_itself_a_median():
    """The post-withdrawal cap, the VM deadline and the late-payment rate are
    all TCBS's, and a table that prints them beside a five-firm median invites
    exactly the mistake rule 4 exists to prevent."""
    for key in ('post_withdrawal_level', 'late_payment_rate'):
        described = PLUTUS_DEFAULT.coverage[key].derivation.describe()
        assert described.startswith("n=1 -- this is TCBS's number, "
                                    'not a median'), key
    minimum_cash = PLUTUS_DEFAULT.coverage['minimum_cash_share'].derivation
    assert minimum_cash.n == 1
    assert "FPTS's number" in minimum_cash.describe()
    assert 'VCBS' in minimum_cash.cross_check


def test_the_median_rule_never_splits_a_difference():
    """Rule 2: on an even count take the more conservative central value.

    The rung-1 pool is 75 / 80 / 80 / 80 / 85 / 85 -- an even count whose two
    central values are both 80, so 80 is a real firm's number either way. The
    derivation records the pool so a reader can check that rather than trust
    it.
    """
    derivation = PLUTUS_DEFAULT.coverage['block_open_level'].derivation
    assert derivation.rule == 'median'
    assert derivation.n == 6
    assert '75 / 80 / 80 / 80 / 85 / 85' in derivation.cross_check


def test_hsc_is_excluded_from_the_pools_with_a_stated_reason():
    """Gap kind G17. Converting HSC needs a modelling choice, not arithmetic.

    ``U = 1/R`` if ``MR == IM`` but ``U = 0.8/R`` if ``MR == MM``, and the two
    disagree by 25 points on the same rung.
    """
    excluded = PLUTUS_DEFAULT.coverage['direction'].derivation.excluded
    assert any('HSC' in reason for reason in excluded)
    assert 'U = 1/R' in GAP_KINDS['G17']


def test_the_default_target_records_the_cross_check_it_did_not_adopt():
    """Field 12. Two derivations disagree and the disagreement is recorded.

    Median of the five published target *numbers* is 85; the modal structural
    relation is target = rung 1, which is 80. RUNG_1 is adopted because that
    is how every firm writes it; 85 survives as the cross-check.
    """
    derivation = PLUTUS_DEFAULT.coverage['target'].derivation
    assert '85' in derivation.cross_check
    assert 'Q3' in OPEN_QUESTIONS


def test_notification_records_that_the_split_is_by_document_class():
    """F-3 / gap kind G16. A help page is not a contract.

    Every firm promising a notice does so on a help page; every signed T&C we
    hold denies it. The modal value is adopted per the author's own rule 3,
    and ``SourceClass`` is recorded on every notification entry so a
    re-weighting is a query rather than a re-survey.
    """
    assert PLUTUS_DEFAULT.coverage['notification'].gap is \
        GapKind.G16_SOURCE_CLASS_WEAK
    for name in ('MBS', 'KIS', 'VPS'):
        entry = get_profile(name, fill_from=PLUTUS_DEFAULT,
                            warn=False).coverage['notification']
        assert entry.status is Coverage.DISCLAIMED
        assert entry.source_class.is_contractual
    for name in ('TCBS', 'HSC'):
        entry = get_profile(name, warn=False).coverage['notification']
        assert entry.source_class is SourceClass.HELP_PAGE
        assert not entry.source_class.is_contractual
    vietcap = get_profile('Vietcap', warn=False).coverage['notification']
    assert not vietcap.source_class.is_contractual


# ---------------------------------------------------------------------------
# The CCP rung is not the broker rung
# ---------------------------------------------------------------------------


def test_the_broker_fires_before_the_ccp_does():
    """Section 3b consequence 2, as two distinct objects.

    ``broker.py`` defends ``forced_close_utilisation = 1.00`` on the ground
    that ``MR / assets >= 1.00`` reproduces QD 26 Dieu 13. That is correct --
    for the **CCP** rung. The survey puts the broker's top rung at 0.95.

    An account at 0.97 utilisation has breached its broker's ladder and has
    **not** breached the CCP: assets 1,000,000 against required 970,000 is
    ``assets > required``, which is not Dieu 13's test.
    """
    assert PLUTUS_DEFAULT.ladder[2].level == D('0.95')
    assert PLUTUS_DEFAULT.ccp_breach.level == D('1.00')
    state = assess(PLUTUS_DEFAULT, required=D('970000'), assets=D('1000000'),
                   warn_once=False)
    assert state.rung.coverage_key == 'forced_close_level'
    assert not state.ccp_breach

    breached = assess(PLUTUS_DEFAULT, required=D('1000001'),
                      assets=D('1000000'), warn_once=False)
    assert breached.ccp_breach


def test_the_ccp_test_is_binary_and_carries_no_percentage():
    """QD 26 Dieu 13: *assets < MR*, full stop.

    Equality is cured under Dieu 13.2.c *"bang hoac lon hon"*, so the boundary
    is not a breach.
    """
    test = CcpBreachTest()
    assert not test.is_breach(D('100'), D('100'))
    assert test.is_breach(D('100'), D('99.99'))
    assert test.substitute_close_out_days == 3
    assert '09h30' in test.top_up_deadline


# ---------------------------------------------------------------------------
# Boundaries, and agreement with the existing margin test
# ---------------------------------------------------------------------------


def test_no_requirement_is_not_a_breach_and_no_assets_is_the_worst_rung():
    """Both boundaries decided, and matching ``deposit.margin_status``.

    ``ratio`` is ``None`` in both cases because neither has a finite ratio.
    ``None`` is not "fine" and not "doomed"; ``is_breach`` is the answer.
    """
    flat = assess(PLUTUS_DEFAULT, required=D('0'), assets=D('0'),
                  warn_once=False)
    assert flat.ratio is None
    assert not flat.is_breach
    assert not flat.ccp_breach

    broke = assess(PLUTUS_DEFAULT, required=D('100'), assets=D('0'),
                   warn_once=False)
    assert broke.ratio is None
    assert broke.is_breach
    assert broke.rung.coverage_key == 'forced_close_level'
    assert broke.ccp_breach


def test_the_default_projects_onto_broker_terms_without_surprise():
    terms = PLUTUS_DEFAULT.to_broker_terms()
    assert isinstance(terms, BrokerTerms)
    assert terms.warning_utilisation == D('0.80')
    assert terms.margin_call_utilisation == D('0.90')
    assert terms.forced_close_utilisation == D('0.95')


def test_broker_terms_refuses_where_the_projection_would_lie():
    """Lossy by construction, and it says so rather than guessing.

    HSC would need the ``MR == IM`` versus ``MR == MM`` choice that gap kind
    G17 says is a modelling decision; Vietcap has only two rungs; an unfilled
    MBS has no numbers at all.
    """
    with pytest.raises(CoverageError, match='G17'):
        get_profile('HSC', warn=False).to_broker_terms()
    with pytest.raises(CoverageError, match='needs three'):
        get_profile('Vietcap', warn=False).to_broker_terms()
    with pytest.raises(CoverageError, match='delegates'):
        bp._BUILDERS['MBS']().to_broker_terms()


def test_a_broker_ratio_below_the_vsdc_ratio_raises():
    """Research S-17: brokers set their ratio at or above VSDC's."""
    with pytest.raises(ValueError, match='S-17'):
        fully_sourced_profile(initial_margin_ratio=D('0.10'))
    assert fully_sourced_profile(initial_margin_ratio=D('0.17'))


# ---------------------------------------------------------------------------
# User-defined profiles
# ---------------------------------------------------------------------------


def test_an_undeclared_field_raises_rather_than_defaulting():
    """*If they leave a field unsourced it is their declaration to make, not
    ours to invent.*"""
    coverage = dict(fully_sourced_profile().coverage)
    coverage.pop('denominator')
    with pytest.raises(CoverageError, match='denominator'):
        fully_sourced_profile(coverage=coverage)


def test_a_caller_can_declare_a_field_unsourced_deliberately():
    coverage = dict(fully_sourced_profile().coverage)
    coverage['denominator'] = FieldCoverage.undeclared(
        'divisor of my broker\'s ratio', note='I have not asked them yet')
    profile = fully_sourced_profile(coverage=coverage)
    entry = profile.coverage['denominator']
    assert entry.status is Coverage.UNPUBLISHED
    assert entry.source_class is SourceClass.OURS
    assert 'not asked them' in entry.note
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        profile.warn()
    assert caught, 'a declared gap must still warn'


def test_a_rung_needs_its_own_coverage_entry():
    extra = fully_sourced_profile().ladder + (
        Rung(coverage_key='fourth_level', name='rung 4', level=D('0.99'),
             action=Action.LIQUIDATE),)
    with pytest.raises(CoverageError, match='fourth_level'):
        fully_sourced_profile(ladder=extra)


def test_a_cap_needs_its_own_coverage_entry():
    with pytest.raises(CoverageError, match='post_withdrawal_level'):
        fully_sourced_profile(caps=(
            Cap(coverage_key='post_withdrawal_level', name='after withdrawal',
                level=D('0.80')),))


def test_two_profiles_with_the_same_numbers_are_not_the_same_policy():
    """Equality is identity: what matters here is where the numbers came
    from, and two profiles carrying 85/90/95 can differ in all of it."""
    assert fully_sourced_profile() != fully_sourced_profile()
    assert PLUTUS_DEFAULT == PLUTUS_DEFAULT


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_registry_lists_fourteen_firms_plus_the_synthesis_and_vintages():
    """Fourteen surveyed firms, plus the synthesis and three extra rows.

    The extra rows are SSI's foreign ladder, SSI's superseded 2025-09-11
    schedule and Pinetree's superseded page. A vintage is a **whole parameter
    set**, not a field, so it ships as its own row rather than as a note on
    the current one.
    """
    assert len(PROFILE_NAMES) == 18
    assert PROFILE_NAMES[0] == 'PLUTUS_DEFAULT'
    firms = set(PROFILE_NAMES) - {'PLUTUS_DEFAULT', 'SSI_FOREIGN',
                                  'SSI_2025_09', 'Pinetree_2024'}
    assert len(firms) == 14
    listed = {name for name, _, _ in list_profiles()}
    assert listed == set(PROFILE_NAMES)
    for name, _, description in list_profiles():
        assert description, name


def test_an_unknown_firm_names_what_is_available():
    with pytest.raises(KeyError, match='PLUTUS_DEFAULT'):
        get_profile('NOT_A_BROKER')


def test_the_disabled_profiles_are_disabled_for_stated_reasons():
    """VPS's direction rests on a source defect; VCBS's denominator
    contradicts itself; ACBS has no ladder to run."""
    assert set(PROFILE_NAMES) - bp.ENABLED_BY_DEFAULT == {'VPS', 'VCBS',
                                                          'ACBS'}


def test_pinetrees_two_vintages_ship_as_two_dated_rows():
    """*Date the row and mark it superseded; do not overwrite* -- no source
    establishes when the change happened."""
    live = get_profile('Pinetree', warn=False)
    old = get_profile('Pinetree_2024', warn=False)
    assert [rung.level for rung in live.ladder] == [D('0.80'), D('0.90'),
                                                    D('0.95')]
    assert [rung.level for rung in old.ladder] == [D('0.75'), D('0.85'),
                                                   D('0.90')]
    assert old.superseded_by == 'Pinetree'
    assert live.supersedes == 'Pinetree_2024'
    assert old.document_date == date(2024, 7, 11)
    assert old.coverage['block_open_level'].status is Coverage.PUBLISHED_STALE


def test_ssis_foreign_ladder_is_its_own_profile():
    domestic = get_profile('SSI', warn=False)
    foreign = get_profile('SSI_FOREIGN', warn=False)
    assert [r.level for r in domestic.ladder] == [D('0.85'), D('0.90'),
                                                  D('0.95')]
    assert [r.level for r in foreign.ladder] == [D('0.75'), D('0.80'),
                                                D('0.85')]


def test_a_pre_krx_document_is_flagged_as_one():
    """Gap kind G13. The URL is not the date: MBS's terms sit at a 2026/06
    URL and were issued under a 2019 decision."""
    for name, expected in (('HSC', date(2020, 4, 15)),
                           ('MBS', date(2019, 7, 2)),
                           ('KIS', date(2022, 1, 1)),
                           ('TCBS', date(2025, 4, 24))):
        try:
            profile = get_profile(name, warn=False)
        except CoverageError:
            profile = get_profile(name, fill_from=PLUTUS_DEFAULT, warn=False)
        assert profile.regime is Regime.PRE_KRX, name
        assert profile.document_date == expected, name
        regime_gaps = [g for g in profile.gaps() if g.field_name == 'regime']
        assert regime_gaps and regime_gaps[0].severity is Severity.MATERIAL


def test_suppressing_the_warning_does_not_suppress_the_gap():
    """``warn=False`` is for a caller who has surfaced the coverage some other
    way. It must not become a way to make a profile look clean."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        quiet = get_profile('SSI', warn=False)
    assert caught == []
    assert quiet.gaps()
    assert quiet.material_caveats()
    state = assess(quiet, required=D('900000'), assets=D('1000000'),
                   warn_once=False)
    assert state.caveats


def test_every_shipped_profile_declares_every_required_key():
    for name in PROFILE_NAMES:
        try:
            profile = get_profile(name, warn=False)
        except CoverageError:
            profile = get_profile(name, fill_from=PLUTUS_DEFAULT, warn=False)
        for key in BrokerProfile.REQUIRED_KEYS:
            assert key in profile.coverage, f'{name} is missing {key}'
        for rung in profile.ladder:
            assert rung.coverage_key in profile.coverage


def test_every_stored_quote_is_a_real_sentence():
    """A ``quote`` is defined as the decisive sentence verbatim. An empty or
    truncated one would be worse than none, because it looks like evidence."""
    for name in PROFILE_NAMES:
        try:
            profile = get_profile(name, warn=False)
        except CoverageError:
            profile = get_profile(name, fill_from=PLUTUS_DEFAULT, warn=False)
        for key, cov in profile.coverage.items():
            if cov.quote is not None:
                assert len(cov.quote.strip()) > 5, f'{name}.{key}'


def test_derivation_refuses_an_n_smaller_than_its_own_sources():
    with pytest.raises(ValueError, match='pool size'):
        Derivation(rule='median', n=1, sources=('A', 'B', 'C'))


def test_the_duplicated_krx_cutover_cannot_drift():
    """This module restates the cutover rather than importing the rulebook.

    That keeps the selection layer free of the dated rulebook's dependency
    graph, at the cost of two copies of one date. The cost is paid here: if
    either copy moves, this fails.
    """
    from plutus.market.session.rulebook import KRX_CUTOVER as rulebook_cutover
    assert bp.KRX_CUTOVER == rulebook_cutover


def test_level_aliases_map_quantities_not_labels():
    """Gap kind G18 is what happens when a mapping like this is built out of
    labels. Every alias must name the same *quantity* on both sides.

    MBS's *"ty le sau mo vi the"* is the ratio permitted after opening a
    position, which is the quantity PLUTUS_DEFAULT calls the maximum
    utilisation at which a new position may be opened. Every alias resolves to
    a level PLUTUS_DEFAULT actually holds, so a fill can never silently
    produce ``None``.
    """
    for alias, canonical in bp.LEVEL_ALIASES.items():
        assert canonical in {rung.coverage_key
                             for rung in PLUTUS_DEFAULT.ladder}, alias
        assert PLUTUS_DEFAULT.level_for(alias) is not None, alias
    assert PLUTUS_DEFAULT.level_for('ccp_processing_level') == D('1.00')


def test_a_fill_source_without_the_level_refuses_rather_than_guessing():
    """``filled_from`` will not invent a level the source does not hold."""
    thin = fully_sourced_profile(firm='THIN')
    mbs = bp._BUILDERS['MBS']()
    with pytest.raises(CoverageError, match='cannot fill MBS'):
        mbs.filled_from(thin)


# ---------------------------------------------------------------------------
# The default is the default, and every shipped profile stands up
# ---------------------------------------------------------------------------


def test_the_default_profile_is_the_one_a_caller_gets_for_free():
    """``get_profile()`` with no argument is PLUTUS_DEFAULT, by identity.

    Not "a profile with the same numbers" -- the object itself. Profiles
    compare by identity here precisely so that this assertion means what it
    looks like it means, and so that a future registry change that rebuilt the
    default on every call would fail rather than pass by coincidence.
    """
    assert bp.DEFAULT_PROFILE_NAME == 'PLUTUS_DEFAULT'
    assert get_profile(warn=False) is PLUTUS_DEFAULT
    assert get_profile('PLUTUS_DEFAULT', warn=False) is PLUTUS_DEFAULT
    assert PLUTUS_DEFAULT.is_synthesis
    assert PLUTUS_DEFAULT.firm == 'PLUTUS_DEFAULT'


def _all_profiles():
    """Every shipped profile, filling the delegating ones deliberately."""
    out = {}
    for name in PROFILE_NAMES:
        try:
            out[name] = get_profile(name, warn=False)
        except CoverageError:
            out[name] = get_profile(name, fill_from=PLUTUS_DEFAULT, warn=False)
    return out


def test_every_shipped_profile_validates():
    """Construct all of them and exercise every derived view.

    ``__post_init__`` is where a profile's internal contradictions surface --
    a ladder ordered against its direction, a rung with no coverage entry, a
    target pointing off the end of the ladder, a broker IM ratio under
    VSDC's. Building each profile runs all of that. The rest of this test
    walks the views a caller actually reaches for, because a profile that
    constructs and then raises on ``render_coverage()`` is not shipped, it is
    merely present.
    """
    profiles = _all_profiles()
    assert set(profiles) == set(PROFILE_NAMES)
    for name, profile in profiles.items():
        assert profile.firm, name
        assert profile.description, name
        levels = [r.level for r in profile.ladder if r.level is not None]
        assert profile.direction.ladder_is_ordered(levels), name
        for key in BrokerProfile.REQUIRED_KEYS:
            assert key in profile.coverage, f'{name} lacks {key}'
        for rung in profile.ladder:
            assert rung.coverage_key in profile.coverage, name
            if rung.target_ref is TargetRef.ABSOLUTE:
                assert rung.target_absolute is not None, name
        assert isinstance(profile.gaps(), tuple), name
        assert isinstance(profile.material_caveats(), tuple), name
        assert profile.render_coverage().startswith(profile.firm), name
        assert profile.firm in repr(profile), name
        assert profile.margin_model in MarginModel, name
        assert profile.minimum_margin_factor == MINIMUM_MARGIN_FACTOR, name
        # Every profile must be assessable, whatever its gaps.
        state = assess(profile, required=D('900000'), assets=D('1000000'),
                       warn_once=False)
        assert state.firm == profile.firm
        assert state.caveats == profile.material_caveats()


def test_every_shipped_coverage_entry_is_internally_consistent():
    """The provenance invariants, on real data rather than a fixture.

    ``FieldCoverage.__post_init__`` enforces these one record at a time; this
    asserts they hold across all eighteen profiles at once, which is the only
    way to catch a record that was written by hand and never constructed in a
    test.
    """
    for name, profile in _all_profiles().items():
        for key, cov in profile.coverage.items():
            where = f'{name}.{key}'
            assert cov.quantity, where
            if cov.status is Coverage.CONTRADICTORY:
                assert cov.source_defect, where
            if cov.status is Coverage.FILLED_FROM_DEFAULT:
                assert cov.filled_from, where
            if cov.filled_from:
                assert cov.status is Coverage.FILLED_FROM_DEFAULT, where
            if cov.status is not Coverage.FILLED_FROM_DEFAULT:
                assert cov.fetched_on == bp.FETCHED, where


def test_a_gap_warning_names_the_fields_it_is_about():
    """*"Names them"* is the requirement, not merely *"warns"*.

    A warning that says "this profile has gaps" is unactionable: the caller
    cannot tell whether the missing field is the denominator or the notice
    channel, and those differ by whether the number is wrong or merely the
    timing is. Every gap's field name must appear in the emitted text.
    """
    for name, profile in _all_profiles().items():
        gaps = profile.gaps()
        if not gaps:
            continue
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            emitted = profile.warn()
        assert caught, name
        blob = ' '.join(emitted)
        for gap in gaps:
            assert gap.field_name in blob, f'{name}: {gap.field_name} unnamed'


# ---------------------------------------------------------------------------
# Axis 1 again -- HSC against SSI, the two real firms that run opposite ratios
# ---------------------------------------------------------------------------


def test_hsc_and_ssi_classify_the_same_account_oppositely():
    """The direction axis, on two **named firms** rather than a synthesis.

    One account: ``required = 850,000``, ``assets = 1,000,000``.

    * SSI runs utilisation, ``850,000 / 1,000,000 = 0.85``. Its Muc 1 is 0.85,
      so the account is **at the rung** -- blocked from opening.
    * HSC runs coverage, ``1,000,000 / 850,000 = 1.176``. Its worst rung is
      1.00 and 1.176 is *above* it, so under HSC the same account is
      **entirely clear** -- not merely at a milder rung, at no rung at all.

    The two firms look at one book and one is restricting it while the other
    sees nothing. That is not a presentation difference, and it is why
    :meth:`Direction.is_at_or_past` exists rather than a ``>=`` at each call
    site: with the comparison written out longhand, the HSC ladder would read
    ``1.176 >= 1.00`` and fire.
    """
    ssi = get_profile('SSI', warn=False)
    hsc = get_profile('HSC', warn=False)
    required, assets = D('850000'), D('1000000')

    at_ssi = assess(ssi, required=required, assets=assets, warn_once=False)
    assert at_ssi.ratio == D('0.85')
    assert at_ssi.is_breach
    assert at_ssi.rung.name.startswith('Muc 1')
    assert at_ssi.action is Action.BLOCK_OPENING

    at_hsc = assess(hsc, required=required, assets=assets, warn_once=False)
    assert at_hsc.ratio > D('1.17')
    assert not at_hsc.is_breach
    assert at_hsc.rung_index is None

    # The naive comparison, spelled out, gets HSC exactly backwards.
    assert at_hsc.ratio >= hsc.ladder[0].level
    assert not hsc.direction.is_at_or_past(at_hsc.ratio, hsc.ladder[0].level)


def test_hsc_bands_are_bands_not_thresholds():
    """HSC's own table assigns different actions to adjacent bands.

    ``80% <= R < 100%`` is *"Ky quy duy tri"*: blocked from opening and
    withdrawing, and expressly *"khong bi yeu cau ky quy bo sung"* -- no call.
    ``60% <= R < 80%`` is *"Yeu cau ky quy"*: the call. Reading 80% as "the
    margin-call level" and 100% as "normal" inverts which band each action
    belongs to.
    """
    hsc = get_profile('HSC', warn=False)
    names = [rung.name for rung in hsc.ladder]
    assert names == ['Ky quy duy tri', 'Yeu cau ky quy', 'Dong vi the']
    assert [r.level for r in hsc.ladder] == [D('1.00'), D('0.80'), D('0.60')]
    assert [r.action for r in hsc.ladder] == [Action.BLOCK_OPENING,
                                              Action.NOTIFY, Action.LIQUIDATE]

    # Coverage 0.90 is inside the maintenance band: blocked, not called.
    blocked = assess(hsc, required=D('100000'), assets=D('90000'),
                     warn_once=False)
    assert blocked.rung.name == 'Ky quy duy tri'
    assert blocked.action is Action.BLOCK_OPENING
    assert blocked.notice is Notice.UNKNOWN

    # Coverage 0.70 is one band down: the call, with its published timeline.
    called = assess(hsc, required=D('100000'), assets=D('70000'),
                    warn_once=False)
    assert called.action is Action.NOTIFY
    assert called.notice is Notice.REQUIRED


def test_hscs_mm_fraction_and_its_call_rung_are_the_same_number_by_algebra():
    """``MM = 0.80 x IM`` and ``R = balance / IM`` make the 80s identical.

    HSC calls when *"So du ky quy giam xuong duoi muc Ky quy duy tri"*, i.e.
    ``balance < MM = 0.80 x IM``. Dividing through by ``IM`` gives
    ``R < 0.80``. So the maintenance-margin fraction and the call rung are the
    same 80% wearing two names, and a profile that stored them independently
    could drift them apart.
    """
    hsc = get_profile('HSC', warn=False)
    assert hsc.maintenance_margin_fraction == D('0.80')
    assert hsc.ladder[1].level == hsc.maintenance_margin_fraction
    assert hsc.margin_model is MarginModel.IM_ONLY_WITH_MM

    im = D('100000')
    mm = hsc.maintenance_margin_fraction * im
    assert assess(hsc, required=im, assets=mm - D('1'),
                  warn_once=False).action is Action.NOTIFY
    assert assess(hsc, required=im, assets=mm + D('1'),
                  warn_once=False).action is Action.BLOCK_OPENING


def test_hsc_states_two_targets_and_the_difference_is_the_forced_sale():
    """Gap kind G14, and it is worth 17,500d on one small account.

    HSC's rung table says restore to the *"Ky quy duy tri"* band, ``R >= 80%``.
    Its *"Ky quy bo sung"* definition (``IM - So du ky quy``) and its
    *"Xu ly cac tai khoan vi pham"* clause both say restore to *"trang thai
    Binh thuong"*, ``R >= 100%``.

    On ``assets = 70,000`` against ``required = 100,000``:

    * to ``R = 0.80``: ``required <= 70,000 / 0.80 = 87,500`` -- close 12,500;
    * to ``R = 1.00``: ``required <= 70,000 / 1.00 = 70,000`` -- close 30,000.

    Two and a half times the forced selling, from one firm's own page. The
    table is taken as operative and the disagreement is declared, not
    resolved.
    """
    hsc = get_profile('HSC', warn=False)
    assert hsc.coverage['target'].status is Coverage.CONTRADICTORY
    defect = hsc.coverage['target'].source_defect
    assert 'Ky quy bo sung' in defect
    assert 'Binh thuong' in defect

    operative = forced_reduction(hsc, required=D('100000'), assets=D('70000'))
    assert operative == D('12500')

    to_normal = tuple(
        r if i != 1 else dataclasses.replace(r, target_ref=TargetRef.RUNG_1)
        for i, r in enumerate(hsc.ladder))
    other_reading = dataclasses.replace(hsc, ladder=to_normal)
    assert forced_reduction(other_reading, required=D('100000'),
                            assets=D('70000')) == D('30000')


# ---------------------------------------------------------------------------
# The parameter feed
# ---------------------------------------------------------------------------


def test_ssi_is_the_parameter_feed_and_can_now_actually_feed():
    """The selection brief ships SSI *as the parameter feed*. Feed it.

    Every value here is transcribed from section A of SSI's schedule and
    every one is an input to the scenario grid: ``Rm``, ``Sm``, ``Psr``, the
    size-correlation factor, and the per-contract requirement. A profile that
    described itself as the parameter feed while holding no parameters could
    not be used for the job the brief assigns it.
    """
    ssi = get_profile('SSI', warn=False)
    params = ssi.vsdc_parameters
    assert params.effective_from == date(2026, 1, 16)
    assert params.names == ('VN30', 'VN100')

    vn30 = ssi.parameters_for('VN30')
    assert vn30.risk_margin_rate == D('0.17')
    assert vn30.spread_margin_rate == D('0.0087')
    assert vn30.price_scan_range == D('0.85')
    assert vn30.scale_factor == D('1')
    assert vn30.total_margin_rate == D('0.1787')
    assert vn30.supports_group_offsetting

    vn100 = ssi.parameters_for('VN100')
    assert vn100.spread_margin_rate == D('0.0117')
    assert vn100.scale_factor == D('1.03')
    # The two index contracts differ structurally, not only in rate.
    assert vn30.scale_factor != vn100.scale_factor


def test_the_implied_index_level_uses_the_firms_own_rates():
    """Gap kind G18, settled without the caller supplying anything.

    ``34,520,710 / ((0.17 + 0.0087) x 100,000) = 1931.77`` and
    ``32,606,000 / ((0.17 + 0.0117) x 100,000) = 1794.50``. Both are plausible
    VN30 and VN100 levels, so both published figures track the index and are
    therefore dated snapshots rather than the policy constant ``MF``.

    :meth:`BrokerProfile.implied_index_level` needs the rates from the caller
    and so can be run against the wrong firm's parameters by accident. This
    one cannot: the row carries its own.
    """
    ssi = get_profile('SSI', warn=False)
    vn30 = ssi.parameters_for('VN30').implied_index_level
    vn100 = ssi.parameters_for('VN100').implied_index_level
    assert D('1931') < vn30 < D('1932')
    assert D('1794') < vn100 < D('1795')

    shs = get_profile('SHS', warn=False)
    assert D('1280') < shs.parameters_for('VN30').implied_index_level < D('1281')

    # And MF is untouched by any of it -- three orders of magnitude away.
    assert ssi.minimum_margin_factor == D('5000')
    assert shs.minimum_margin_factor == D('5000')


def test_a_per_contract_requirement_at_or_below_mf_is_refused():
    """The homonym, guarded at construction rather than at read time.

    Somebody transcribing TCBS's ``5,000d`` into this field has confused the
    two quantities the phrase *"Gia tri ky quy toi thieu/1HD"* covers, and the
    failure is silent afterwards: ``MM`` binds on every book and
    ``MR = max(Rm + Sm - OA, MM)`` stops meaning anything.
    """
    with pytest.raises(HomonymError, match='G18'):
        bp.UnderlyingParameters(
            underlying='VN30', risk_margin_rate=D('0.17'),
            spread_margin_rate=D('0.0087'),
            minimum_per_contract_requirement=D('5000'))


def test_ssis_two_vintages_disagree_about_more_than_the_ladder():
    """A vintage is a whole parameter set, which is why it ships as a row.

    Between 2025-09-11 and 2026-01-16 SSI moved its ladder **and** ``Psr``
    (1 -> 0.85), ``Sm`` (17% -> 0.87%) and the per-contract requirement. A
    field-level "superseded" note on the current profile would have carried
    the ladder change and lost the other three.
    """
    now = get_profile('SSI', warn=False)
    then = get_profile('SSI_2025_09', warn=False)

    assert [r.level for r in then.ladder] == [D('0.80'), D('0.85'), D('0.90')]
    assert [r.level for r in now.ladder] == [D('0.85'), D('0.90'), D('0.95')]
    assert then.superseded_by.startswith('SSI (85/90/95')
    assert 'SSI_2025_09' in now.supersedes
    assert then.document_date == date(2025, 9, 11)

    old, new = then.parameters_for('VN30'), now.parameters_for('VN30')
    assert old.price_scan_range == D('1') != new.price_scan_range
    assert old.spread_margin_rate == D('0.17') != new.spread_margin_rate
    assert old.minimum_per_contract_requirement != \
        new.minimum_per_contract_requirement
    # Rm is the one row that did not move.
    assert old.risk_margin_rate == new.risk_margin_rate == D('0.17')


def test_ssis_foreign_ladder_did_not_move_across_the_vintages():
    """The domestic ladder loosened by five points; the foreign one did not.

    Both pages print 75/80/85 for foreign investors. That is the evidence that
    the foreign ladder is a **separate policy** rather than a fixed offset of
    the domestic one, and a profile carrying only the current numbers could
    not show it.
    """
    foreign = get_profile('SSI_FOREIGN', warn=False)
    assert [r.level for r in foreign.ladder] == [D('0.75'), D('0.80'),
                                                 D('0.85')]
    domestic_now = get_profile('SSI', warn=False)
    domestic_then = get_profile('SSI_2025_09', warn=False)
    moved = [r.level for r in domestic_now.ladder] != \
            [r.level for r in domestic_then.ladder]
    assert moved


def test_the_superseded_sm_is_disproved_by_its_own_next_row():
    """SSI's 2025 page prints ``Sm = 17%``. Its next row disproves it.

    ``31,711,460 / ((0.17 + 0.17) x 100,000) = 932.7``. The VN30 traded near
    1,700 in September 2025, so the two rows cannot both hold. Under the
    successor page's ``Sm = 0.87%`` the same figure gives 1,774.6, which is
    right.

    This is recorded as ``CONTRADICTORY`` rather than corrected: we know the
    17% is wrong, we do not know what it replaced, and inventing the
    replacement would be worse than declaring the defect.
    """
    then = get_profile('SSI_2025_09', warn=False)
    row = then.parameters_for('VN30')
    assert row.implied_index_level == D('932.69')

    cov = then.coverage['vsdc_parameters']
    assert cov.status is Coverage.CONTRADICTORY
    assert cov.gap is GapKind.G14_SOURCE_SELF_CONTRADICTORY
    assert '932.7' in cov.source_defect

    plausible = (row.minimum_per_contract_requirement
                 / ((D('0.17') + D('0.0087')) * D('100000')))
    assert D('1774') < plausible < D('1775')


def test_shs_and_ssi_mirror_the_same_vsdc_row_and_disagree():
    """Gap kind G12, as an assertion rather than a note.

    ``Sm`` for VN30 index futures is 0.87% at SSI and 0.42% at SHS -- more
    than double -- and both firms present theirs as current. Neither is
    "wrong": they are snapshots of a moving VSDC table taken on different
    days. Merging them, or preferring one silently, is what the gap kind
    exists to prevent.
    """
    ssi = get_profile('SSI', warn=False).parameters_for('VN30')
    shs = get_profile('SHS', warn=False).parameters_for('VN30')
    assert ssi.risk_margin_rate == shs.risk_margin_rate == D('0.17')
    assert ssi.spread_margin_rate == D('0.0087')
    assert shs.spread_margin_rate == D('0.0042')
    assert ssi.spread_margin_rate > shs.spread_margin_rate * 2

    shs_profile = get_profile('SHS', warn=False)
    cov = shs_profile.coverage['vsdc_parameters']
    assert cov.status is Coverage.PUBLISHED_STALE
    assert cov.gap is GapKind.G12_PARAMETER_VINTAGE
    # A stale rate moves the requirement, so it is MATERIAL, not advisory.
    assert 'vsdc_parameters' in bp.MARGIN_CRITICAL_FIELDS
    assert any('vsdc_parameters' in caveat
               for caveat in shs_profile.material_caveats())


def test_shs_publishes_no_offset_parameters_so_none_can_be_computed():
    """A missing ``Psr`` is not a ``Psr`` of zero.

    Zero would mean *"no offsetting is allowed"*, which is a policy. SHS
    states no policy: it mirrors the rates and not the offset, so a group
    offset simply cannot be produced from SHS's page.
    """
    shs = get_profile('SHS', warn=False).parameters_for('VN30')
    assert shs.price_scan_range is None
    assert shs.scale_factor is None
    assert not shs.supports_group_offsetting
    # Dm is None because SHS attaches its 2.5% to bond futures only.
    assert shs.delivery_margin_rate is None

    ssi = get_profile('SSI', warn=False).parameters_for('VN30')
    assert ssi.supports_group_offsetting


def test_a_firm_that_delegates_its_rates_refuses_to_produce_them():
    """TCBS's ``3%`` / ``1%`` are a worked example, so TCBS has no rates.

    The refusal names SSI rather than falling back to it, because ``Rm`` and
    ``Sm`` are not policy choices a median can be taken of: they are VSDC's,
    they move, and the honest answer to *"what are TCBS's rates?"* is that
    TCBS delegates them and the table was never located.
    """
    tcbs = get_profile('TCBS', warn=False)
    assert tcbs.vsdc_parameters is None
    with pytest.raises(CoverageError, match='SSI'):
        tcbs.parameters_for('VN30')
    assert tcbs.coverage['vsdc_parameters'].status is \
        Coverage.PUBLISHED_ILLUSTRATIVE


def test_position_limits_are_an_exchange_rule_that_two_firms_restate():
    """Selection-brief field 21. Both firms print it; neither chose it.

    SSI and TCBS publish the identical 5,000 / 10,000 / 20,000 triple and TCBS
    attributes it in the same cell -- *"Theo quy dinh tai VSD"*. It is stored
    on the parameter set, beside the VSDC rates, and never on the profile as
    if it were a commercial term.
    """
    limits = get_profile('SSI', warn=False).vsdc_parameters.position_limits
    assert (limits.individual, limits.institutional, limits.professional) == \
        (5000, 10000, 20000)
    assert 'VSD' in limits.attribution
    assert limits.limit_for('individual') == 5000
    assert limits.limit_for('professional') == 20000
    with pytest.raises(KeyError, match='investor class'):
        limits.limit_for('retail')

    tcbs = get_profile('TCBS', warn=False)
    assert 'VSD' in tcbs.coverage['position_limits'].quote


def test_a_parameter_set_refuses_two_rows_for_one_underlying():
    """Two rows for one underlying means two vintages, and a vintage is a
    whole set -- SSI and Pinetree both ship theirs as separate profiles."""
    row = bp.UnderlyingParameters(
        underlying='VN30', risk_margin_rate=D('0.17'),
        spread_margin_rate=D('0.0087'))
    with pytest.raises(ValueError, match='two vintages'):
        bp.VsdcParameterSet(effective_from=None, underlyings=(row, row))


def test_asking_for_an_underlying_a_firm_does_not_mirror_names_what_it_holds():
    """And says why substituting the other row is not available.

    ``Sm`` alone differs by 34% between VN30 and VN100 on SSI's own page, so
    a silent fallback to "the other index contract" would be a real error
    dressed as a convenience.
    """
    shs = get_profile('SHS', warn=False)
    with pytest.raises(KeyError, match='VN30'):
        shs.parameters_for('VN100')


# ---------------------------------------------------------------------------
# TCBS -- corrections read back off its page
# ---------------------------------------------------------------------------


def test_tcbs_publishes_an_action_at_its_maintenance_rung():
    """85% is not a bare warning: it is the ceiling on opening a position.

    *"Ty le su dung tai san duy tri (Ty le duy tri) 85% -- La ty le duoc giao
    dich toi da khi mo moi vi the."* The same 85 is also the target both
    higher rungs restore to, which is why it appears twice and must not be
    modelled once.
    """
    tcbs = get_profile('TCBS', warn=False)
    duy_tri = tcbs.ladder[0]
    assert duy_tri.level == D('0.85')
    assert duy_tri.action is Action.BLOCK_OPENING
    assert 'giao dịch tối đa' in tcbs.coverage['maintenance_level'].quote
    assert resolve_target(tcbs, tcbs.ladder[1]) == D('0.85')
    assert resolve_target(tcbs, tcbs.ladder[2]) == D('0.85')


def test_tcbs_carries_two_rates_and_they_price_different_events():
    """11.5%/yr on a late VM payment; 10.5%/yr on support cash advanced.

    Merging them would mis-price the fifth path, which is the one place a
    surveyed firm lends the client money to avoid closing them out.
    """
    tcbs = get_profile('TCBS', warn=False)
    assert tcbs.late_payment_annual_rate == D('0.115')
    assert tcbs.support_disbursement_annual_rate == D('0.105')
    assert tcbs.late_payment_annual_rate != tcbs.support_disbursement_annual_rate
    support = tcbs.coverage['support_disbursement']
    assert '95%' in support.quote
    assert '10.5%/yr' in support.note
    # No other shipped firm publishes a support facility at all.
    others = [p for name, p in _all_profiles().items() if name != 'TCBS']
    assert not any('support_disbursement' in p.coverage for p in others)


def test_tcbs_and_ssi_are_complete_only_together():
    """Selection brief section 2: neither alone runs a margin call.

    TCBS publishes the model and no parameters; SSI publishes the parameters
    and no model. The profiles say so rather than papering over it, and
    saying so is what stops a caller reaching for one and believing they have
    both.
    """
    tcbs = get_profile('TCBS', warn=False)
    ssi = get_profile('SSI', warn=False)

    assert tcbs.coverage['margin_model_overnight'].status is Coverage.PUBLISHED
    assert tcbs.vsdc_parameters is None

    assert ssi.margin_model_intraday is MarginModel.UNSTATED
    assert ssi.coverage['margin_model_intraday'].gap is \
        GapKind.G10_MODEL_NOT_STATED
    assert ssi.vsdc_parameters is not None

    # And the reference profile's denominator is still entirely absent.
    assert tcbs.denominator.basis is DenominatorBasis.UNPUBLISHED
    assert tcbs.coverage['denominator'].gap is \
        GapKind.G3_DENOMINATOR_UNDEFINED


def test_a_firms_number_is_either_a_url_or_an_admission():
    """*"Every number carries its source URL"* -- or says why it does not.

    Four firms' snapshots recorded no URL at all (FPTS's schedule, SHS's
    account terms, Vietcap's 403, Pinetree's Cloudflare block). Inventing a
    plausible URL for those would be exactly the overclaiming the house rules
    forbid, so the rule this pins is the weaker true one: a coverage record
    that is the *firm's own* must carry either a ``source_url`` or a ``note``
    naming the snapshot it was read from. Never neither.
    """
    for name, profile in _all_profiles().items():
        for key, cov in profile.coverage.items():
            if cov.source_class in (SourceClass.OURS,):
                continue
            if cov.status is Coverage.FILLED_FROM_DEFAULT:
                continue
            assert cov.source_url or cov.note, f'{name}.{key} cites nothing'


def test_the_two_firms_with_a_retrievable_url_carry_it_on_every_field():
    """SSI and TCBS and HSC were read from URL-bearing snapshots.

    Where we have the URL there is no excuse for not storing it: the whole
    point of a named-firm profile is that a user can open the firm's page and
    check the number against it.
    """
    for name in ('SSI', 'SSI_2025_09', 'TCBS', 'HSC'):
        profile = get_profile(name, warn=False)
        firm_fields = [key for key, cov in profile.coverage.items()
                       if cov.source_class is not SourceClass.OURS]
        assert firm_fields, name
        for key in firm_fields:
            url = profile.coverage[key].source_url
            assert url and url.startswith('https://'), f'{name}.{key}'
    assert get_profile('SSI', warn=False).coverage['direction'].source_url != \
        get_profile('SSI_2025_09', warn=False).coverage['direction'].source_url


def test_one_quantity_never_wears_two_coverage_keys():
    """Gap kind G18, applied to our own register rather than to a firm's page.

    A firm's mirror of VSDC's parameter table is one quantity. TCBS's copy is
    illustrative, SSI's is operative, SHS's is stale -- three statuses, one
    quantity, and therefore one key. Filing TCBS's under ``risk_margin_rates``
    and SSI's under ``vsdc_parameters`` would mean a caller asking *"does this
    firm publish its rates?"* had to know which firm they were asking about
    before they could ask, which is exactly the failure G18 describes.

    The consequence is not cosmetic: ``vsdc_parameters`` is in
    ``MARGIN_CRITICAL_FIELDS``, so TCBS's illustrative rates are now MATERIAL
    rather than advisory -- which is right, because a 3% read as operative
    against a true 17% is a five-fold error in the requirement.
    """
    statuses = {}
    for name in ('TCBS', 'SSI', 'SSI_2025_09', 'SHS'):
        cov = get_profile(name, warn=False).coverage['vsdc_parameters']
        statuses[name] = cov.status
    assert statuses['TCBS'] is Coverage.PUBLISHED_ILLUSTRATIVE
    assert statuses['SSI'] is Coverage.PUBLISHED
    assert statuses['SSI_2025_09'] is Coverage.CONTRADICTORY
    assert statuses['SHS'] is Coverage.PUBLISHED_STALE
    assert len(set(statuses.values())) == 4

    tcbs = get_profile('TCBS', warn=False)
    assert any(gap.field_name == 'vsdc_parameters'
               and gap.severity is Severity.MATERIAL
               for gap in tcbs.gaps())
    # A profile whose rates are illustrative must not be able to hand them out.
    assert tcbs.vsdc_parameters is None
