"""Broker margin profiles -- which firm's rules a simulated account lives under.

`plutus.market.broker.BrokerTerms` answers *"what are the three percentages?"*.
That question is the wrong shape, and the broker survey proves it: a
``{warn, call, liquidate}`` triple silently mis-models at least four of the
fourteen firms surveyed. This module answers the right shape.

**THE FIVE AXES** (``docs/reference/krx-margin-research.md`` section 4.2 -- the
design brief, quoted there as *"Five axes, not one"*):

1. **Direction** -- :class:`Direction`. Thirteen firms run a *rising
   utilisation* ratio (``MR / assets``; higher is worse). HSC runs a *falling
   coverage* ratio (``equity / IM``; lower is worse). Direction is not a
   presentation detail: it is a sign concept applied at **every** point a ratio
   meets a level, which is why it is a method on the enum
   (:meth:`Direction.is_at_or_past`) and not an ``if`` at each call site.
2. **Denominator** -- :class:`DenominatorSpec`. Four bases and three
   liability treatments are in evidence, and they produce materially different
   ratios on identical positions. The brief calls this *"the single most
   commonly-missed field"*.
3. **Action semantics, fire vs target** -- :class:`Action` plus
   :class:`TargetRef`. TCBS, MBS, SSI and Pinetree do not merely *trigger* at a
   rung; they close positions **until a named target level is reached**. That
   is a different quantity of forced selling from clearing the rung, and
   :func:`forced_reduction` computes both so the difference can be measured.
4. **Notification obligation** -- :class:`Notice`. KIS disclaims it in both
   directions; MBS and VPS make it a right, not a duty. A model with a
   mandatory notice step and a cure window **over-states survival** at those
   three firms, so :func:`liquidation_path` drops the step rather than
   assuming it.
5. **Publication status** -- :class:`Coverage`, generalised. "Does the firm
   publish its numbers?" turned out to be ten questions, not one; see
   :data:`GAP_KINDS`.

**THE SIXTH AXIS, WHICH IS THE AUTHOR'S: MARGIN MODEL SELECTION.**
A profile declares *which model computes the number its ladder divides by* --
the scenario grid of :mod:`plutus.market.session.scenario_margin`, or
``IM + VM + DM`` of :mod:`plutus.market.session.deposit`. There is **one
user-facing margin number**; :attr:`BrokerProfile.user_facing_model` says which
layer produces it and :attr:`BrokerProfile.margin_model` returns that model.
The two layers are both carried (:attr:`BrokerProfile.margin_model_intraday`,
:attr:`BrokerProfile.margin_model_overnight`) because the survey found firms
publishing **both, for different purposes** -- see :data:`OPEN_QUESTIONS`
``Q1``. This module selects; it does not compute. Wiring the selection into
``ExchangeSession`` is deliberately not done here.

**THE PARAMETER FEED.** A ladder decides *when* a firm acts; it does not say
what number it acts on. :class:`VsdcParameterSet` carries the rates a firm
mirrors from VSDC -- ``Rm``, ``Sm``, ``Psr``, the size-correlation factor, the
per-contract requirement and the position limits -- so that "SSI is the
parameter feed" is something the code can do rather than something a docstring
asserts. Three properties of the pool make it an object rather than five
fields: the mirrors are **dated** and they **disagree** (SSI publishes
``Sm = 0.87%`` where SHS publishes ``0.42%`` on the same instrument); a firm
may mirror the rates and **not** the offset parameters, which is a real limit
on what its page can produce and not a zero; and the per-contract requirement
is the field gap kind ``G18`` bites on, so it is guarded at construction.

**THE COVERAGE DECLARATION.** Every field of every profile carries a
:class:`FieldCoverage` saying where the value came from, what quantity it
actually is, and -- when we supplied it -- that we supplied it. Using a profile
with gaps warns through :mod:`warnings`, carrying the gap ids and what each
means for the result. A profile with no gaps warns nothing.

    **Silence means "fully sourced". It must never mean "we did not check".**

That guarantee is mechanised, not promised: :meth:`BrokerProfile.published_fields`
and :meth:`BrokerProfile.supplied_fields` partition the coverage map, every
element of the latter carries ``filled_from``, and a construction with an
undeclared field **raises** rather than defaulting.

**PLUTUS_DEFAULT is the default, and it is a synthesis, not a firm.** If a real
firm were the default, a caller who chose no broker would silently inherit one
firm's commercial policy and could mistake it for the Vietnamese standard.
PLUTUS_DEFAULT is honest about its own status: it warns that it is a synthesis,
matches no firm exactly, and every one of its numeric fields records its
:class:`Derivation` -- the rule, the source firms **by name**, and ``n``.
Numeric fields take the **median** of the normalised pool (never a synthetic
midpoint), categorical fields the **modal** value, so every default is a value
some real broker actually applies.

**Named firms keep their real names** so any number can be checked against that
firm's published page, and where a named firm does not publish a required
element we fill it from PLUTUS_DEFAULT and mark it unmissably. A user reading
SSI's page must never be misled by a field we supplied.

**Two notes on conventions in this file.**

*Diacritics.* The rest of this package folds Vietnamese to ASCII. The ``quote``
field of :class:`FieldCoverage` does not, because it is defined as the
decisive sentence **verbatim** and a folded sentence cannot be found on the
firm's page with Ctrl-F, which is the entire point of storing it. Prose and
identifiers stay ASCII.

*The name collision, stated rather than hidden.*
:class:`plutus.market.session.types.BrokerProfile` already exists and is a
**different quantity**: a session-config record (name, ``BrokerTerms``, margin
buffer, commission rows). This class is the margin-policy declaration. That is
gap kind ``G18`` (HOMONYM) occurring in our own code, and it is registered as
such rather than papered over. :data:`MarginBrokerProfile` is an alias for this
one, for any module that must import both.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from enum import Enum, auto
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Sequence, Tuple

from plutus.market.broker import BrokerTerms, CureWindow

__all__ = [
    # -- errors and warnings ----------------------------------------------
    'BrokerProfileError', 'CoverageError', 'HomonymError',
    'BrokerProfileWarning', 'SynthesisWarning', 'MaterialCoverageWarning',
    'AdvisoryCoverageWarning',
    # -- the registers ----------------------------------------------------
    'GAP_KINDS', 'OPEN_QUESTIONS', 'MARGIN_CRITICAL_FIELDS',
    'NUMERIC_FIELDS', 'LEVEL_ALIASES', 'MINIMUM_MARGIN_FACTOR',
    'VSDC_INITIAL_MARGIN_RATIO', 'CCP_TOP_UP_DEADLINE', 'FETCHED',
    # -- axis 1 -----------------------------------------------------------
    'Direction',
    # -- axis 2 -----------------------------------------------------------
    'DenominatorBasis', 'LiabilitiesTreatment', 'DenominatorSpec',
    # -- axis 3 -----------------------------------------------------------
    'Action', 'TargetRef', 'Rung', 'Cap',
    # -- axis 4 -----------------------------------------------------------
    'Notice', 'CureKind', 'CureSpec',
    # -- axis 5 / the coverage declaration --------------------------------
    'Coverage', 'SourceClass', 'GapKind', 'Severity', 'Derivation',
    'FieldCoverage', 'Gap',
    # -- the sixth axis: model selection ----------------------------------
    'MarginModel', 'MarginLayer',
    # -- section 4.3 escape hatches ---------------------------------------
    'NamedRatio', 'BuyingPowerSpec', 'CcpBreachTest',
    # -- the parameter feed -----------------------------------------------
    'PositionLimits', 'UnderlyingParameters', 'VsdcParameterSet',
    # -- the profile ------------------------------------------------------
    'Regime', 'BrokerProfile', 'MarginBrokerProfile',
    # -- the registry -----------------------------------------------------
    'PLUTUS_DEFAULT', 'DEFAULT_PROFILE_NAME', 'PROFILE_NAMES',
    'ENABLED_BY_DEFAULT', 'get_profile', 'list_profiles',
    # -- using a profile --------------------------------------------------
    'PathStep', 'LadderAssessment', 'assess', 'forced_reduction',
    'resolve_target', 'liquidation_path', 'notice_steps_before_liquidation',
]


# ---------------------------------------------------------------------------
# Errors and warnings
# ---------------------------------------------------------------------------


class BrokerProfileError(Exception):
    """Base for every error this module raises."""


class CoverageError(BrokerProfileError, ValueError):
    """A profile cannot produce a number, or a field was never declared.

    Raised rather than defaulted, in both directions:

    * **BLOCKING gap.** MBS, KIS and VPS delegate every ladder level to a
      notice that is not on the public site. Silently substituting somebody
      else's numbers produces confident, wrong margin-call incidence -- the
      failure mode the brief's axis 5 exists to prevent. The caller must
      either supply the numbers or opt in explicitly with
      ``fill_from=PLUTUS_DEFAULT``.
    * **Undeclared field.** A caller-built profile that omits a coverage entry
      is asking us to invent its provenance. Whether that field is sourced is
      the caller's declaration to make; see :meth:`FieldCoverage.undeclared`
      for the explicit way to say "I do not know".
    """


class HomonymError(BrokerProfileError, ValueError):
    """A published number was about to be read as a different quantity.

    Gap kind ``G18``. The live instance is ``Giá trị ký quỹ tối thiểu/1HĐ``,
    which means ``MF = 5,000d`` at TCBS and ``34,520,710d`` at SSI -- three
    orders of magnitude apart under one phrase. See
    :meth:`BrokerProfile.minimum_margin_factor` for why reading SSI's row into
    ``MF`` destroys ``MR = max(Rm + Sm - OA, MM)``.
    """


class BrokerProfileWarning(UserWarning):
    """Base for the coverage warnings. Visible, never fatal."""


class SynthesisWarning(BrokerProfileWarning):
    """The profile in use is a construct of ours, not a firm's policy."""


class MaterialCoverageWarning(BrokerProfileWarning):
    """A gap that changes margin-call incidence.

    The profile runs, but a field that moves the number is not the firm's:
    an unpublished denominator or model, an illustrative rate read as
    operative, a stale parameter mirror, a pre-KRX instrument, a disclaimed
    notice, or a value we filled from PLUTUS_DEFAULT.
    """


class AdvisoryCoverageWarning(BrokerProfileWarning):
    """A gap that affects timing or reporting only, not the number."""


# ---------------------------------------------------------------------------
# Axis 1 -- direction
# ---------------------------------------------------------------------------


class Direction(Enum):
    """Which way the firm's ratio moves as the account gets worse.

    **RISING_UTILISATION** -- ``MR / margin assets``. Higher is worse; the
    rungs ascend; the top rung is the breach. Thirteen of the fourteen
    surveyed firms, and every firm that publishes a formula for the divisor.

    **FALLING_COVERAGE** -- HSC alone: ``R = So du ky quy / IM``. Lower is
    worse; the rungs *descend* (100 / 80 / 60); ``MM = 80% x IM``. HSC's page
    is dated **15.04.2020**, five years before the KRX cutover.

    HSC cannot be pooled with the utilisation firms without a modelling
    choice, which is why PLUTUS_DEFAULT excludes it from every numeric pool
    (gap kind ``G17``): converting HSC to utilisation gives ``U = 1/R`` if
    ``MR == IM`` but ``U = 0.8/R`` if ``MR == MM == 0.8 x IM``, and the two
    conversions disagree by 25 points on the same rung. That is a decision
    about what HSC's ``MR`` *is*, not arithmetic, so it is not made here.
    """

    RISING_UTILISATION = auto()
    FALLING_COVERAGE = auto()

    def is_at_or_past(self, ratio: Decimal, level: Decimal) -> bool:
        """Has ``ratio`` reached the bad side of ``level``?

        The whole content of axis 1 lives in this one method, so that no call
        site anywhere writes a bare ``>=`` against a firm's rung. Rising:
        ``ratio >= level``. Falling: ``ratio <= level``.
        """
        if self is Direction.RISING_UTILISATION:
            return ratio >= level
        return ratio <= level

    def worse_of(self, a: Decimal, b: Decimal) -> Decimal:
        """The worse of two ratios under this direction."""
        if self is Direction.RISING_UTILISATION:
            return max(a, b)
        return min(a, b)

    def ladder_is_ordered(self, levels: Sequence[Decimal]) -> bool:
        """Do these rung levels run from mild to severe in this direction?

        Rising ladders must be non-decreasing (80, 90, 95). Falling ladders
        must be non-increasing (100, 80, 60). A ladder ordered the other way
        would fire its severest rung first, which is how a direction bug
        becomes a silently over-liquidating simulation.
        """
        pairs = zip(levels, levels[1:])
        if self is Direction.RISING_UTILISATION:
            return all(a <= b for a, b in pairs)
        return all(a >= b for a, b in pairs)

    @property
    def ratio_name(self) -> str:
        if self is Direction.RISING_UTILISATION:
            return 'utilisation (MR / margin assets)'
        return 'coverage (margin assets / IM)'


# ---------------------------------------------------------------------------
# Axis 2 -- the denominator
# ---------------------------------------------------------------------------


class DenominatorBasis(Enum):
    """What the firm divides by. Four bases are in evidence, plus two states.

    ``V_KQ`` -- QD 26 Dieu 8: cash plus securities valued at VSD haircuts and
    **capped at ``(1 - 0.80) x MR``**, subtracting no liabilities. MBS
    section 1.24, KIS section 1.8, VPS section 1.12, SHS, FPTS, Vietcap.

    ``NET_ASSETS`` -- VNDIRECT and FPTS: the same assets **minus the client's
    debts**. Same rung numbers, smaller divisor, higher ratio, earlier call.

    ``CASH_ONLY`` -- VCBS as stated (*"Ty le ky quy toi thieu bang tien:
    100%"*), while VCBS as computed adds a DTA-tier securities term. The firm
    contradicts itself; we do not repair a counterparty's contract.

    ``V_KQ_PLUS_DTA_TIER`` -- VCBS as computed.

    ``INITIAL_MARGIN`` -- HSC's divisor is ``IM``, not an asset total. Its
    ratio is therefore **not a utilisation ratio at all**, which is the other
    half of why HSC will not pool.

    ``UNPUBLISHED`` -- SSI names the divisor (*"tong gia tri tai san ky quy
    hop le"*) without composing it; TCBS does not name it. Gap kind ``G3``.
    """

    V_KQ = auto()
    NET_ASSETS = auto()
    CASH_ONLY = auto()
    V_KQ_PLUS_DTA_TIER = auto()
    INITIAL_MARGIN = auto()
    UNPUBLISHED = auto()


class LiabilitiesTreatment(Enum):
    """Where a client's debts land. Three conventions, and they cannot merge.

    ``IGNORED`` -- MBS, KIS, VPS: ``V_KQ`` subtracts nothing.
    ``SUBTRACTED_FROM_ASSETS`` -- VNDIRECT (*"- Nghia vu no"*), FPTS
    (*"sau khi tru di cac nghia vu no phai tra"*).
    ``ADDED_TO_NUMERATOR`` -- SHS (*"va cac khoan no khac cua KH tai SHS
    (phi, thue)"*), a third convention nobody else uses.
    ``UNPUBLISHED`` -- the firm is silent.

    The two minority conventions both **raise** utilisation, but by different
    amounts on the same book, so collapsing them to one flag is the defect
    (gap kind ``G4``). Three values, never a boolean.
    """

    IGNORED = auto()
    SUBTRACTED_FROM_ASSETS = auto()
    ADDED_TO_NUMERATOR = auto()
    UNPUBLISHED = auto()


@dataclass(frozen=True)
class DenominatorSpec:
    """The divisor of one firm's ladder ratio.

    ``securities_cap_fraction`` is QD 26 Dieu 8's ``1 - x`` with ``x = 80%``:
    securities collateral counts only up to ``0.20 x MR``. It is an
    **exchange rule**, restated here because the basis is meaningless without
    it, and it is ``None`` for every basis that is not ``V_KQ``-derived.

    Do not confuse it with two neighbours that wear similar names -- defect
    ``D-28``: VCBS's 100% is a collateral **eligibility** rule and ACBS's 5%
    is a **fee reserve** on buying power. Three concepts, three fields.
    """

    basis: DenominatorBasis
    liabilities: LiabilitiesTreatment
    securities_cap_fraction: Optional[Decimal] = None
    note: str = ''

    def __post_init__(self) -> None:
        if self.securities_cap_fraction is not None:
            if not (Decimal('0') <= self.securities_cap_fraction
                    <= Decimal('1')):
                raise ValueError(
                    'securities_cap_fraction is the (1 - x) of QD 26 Dieu 8 '
                    f'and must be a fraction, got '
                    f'{self.securities_cap_fraction}')


# ---------------------------------------------------------------------------
# Axis 3 -- action semantics
# ---------------------------------------------------------------------------


class Action(Enum):
    """What the firm does at a rung.

    ``NONE`` -- the rung exists and no action is published. VNDIRECT names
    three *"nguong canh bao"* and attaches no action text to any of them
    (gap kind ``G5``).

    ``BLOCK_OPENING`` -- new positions refused, existing ones untouched.
    FPTS at 80, KIS level 1, SHS's *"an toan"* rung.

    ``NOTIFY`` -- the firm tells the client. Whether it is obliged to is
    :class:`Notice`, and the two are independent: KIS's level 2 notifies with
    no obligation to.

    ``TRANSFER_COLLATERAL`` -- **not a synonym for liquidation.** SSI's Muc 3
    reads *"tu dong dieu chuyen tien tu tai khoan cua KH tai SSI len VSD hoac
    nguoc lai ... va/hoac thuc hien dong vi the bat buoc"*: collateral
    movement is attempted first, and only then forced closing. TCBS has the
    same shape twice over -- at its fifth path, disbursing support to 95
    before any T+1 close-out, and on its VM path, *"TCBS se rut tien ky quy tu
    VSD va/hoac dong vi the bat buoc"*. Modelling either as pure liquidation
    **over-states forced selling**. SSI is the only firm that attaches the
    ordering to a **ladder rung**, which is why it is the only profile whose
    :attr:`Rung.follow_on` is set; TCBS's two orderings hang off events
    (a VM shortfall, a VSDC breach) that are not rungs.

    ``LIQUIDATE`` -- the firm closes positions itself.
    """

    NONE = auto()
    BLOCK_OPENING = auto()
    NOTIFY = auto()
    TRANSFER_COLLATERAL = auto()
    LIQUIDATE = auto()

    @property
    def closes_positions(self) -> bool:
        return self is Action.LIQUIDATE


class TargetRef(Enum):
    """Fire, or target -- and if target, *which* level.

    The distinction is the whole of brief axis 3. ``NONE`` means fire-once:
    close just enough to clear the rung. Everything else means close **until
    the ratio reaches a named level**, which is strictly more forced selling
    whenever the target is better than the rung.

    ``RUNG_1`` / ``RUNG_2`` / ``RUNG_3`` -- a reference to another rung of the
    same ladder. This is the form **every firm actually publishes**:
    *"ve Ty le duy tri"* (TCBS), *"ve Muc 1"* (SSI), *"ve muc an toan"* (SHS),
    *"ve duoi muc Canh bao muc do 1"* (KIS), *"de dam bao AR duy tri"* (MBS).
    Not one firm publishes an absolute number, which is why this is a
    reference and not an ``Optional[Decimal]``: when a caller overrides rung
    1, the target moves with it, exactly as the firm's sentence says it
    should.

    ``ABSOLUTE`` -- a literal level, and then ``Rung.target_absolute`` must be
    set. Provided for caller-built profiles; no surveyed firm needs it.

    ``UNRESOLVED`` -- the target cannot be produced, for either of two
    reasons, and the field's coverage entry says which. Gap kind ``G6``:
    level-targeting **is** stated and the level it names is itself delegated
    (MBS's *"AR duy tri"*, KIS's *"muc do 1"*). Gap kind ``G5``: the firm
    publishes a rung and **no action text at all**, so neither fire nor target
    may be assumed (VNDIRECT at all three of its levels, FPTS at 100).
    :func:`forced_reduction` refuses on ``UNRESOLVED`` rather than picking
    one, because the two readings differ by the whole of the forced sale.
    """

    NONE = auto()
    RUNG_1 = auto()
    RUNG_2 = auto()
    RUNG_3 = auto()
    ABSOLUTE = auto()
    UNRESOLVED = auto()

    @property
    def rung_index(self) -> Optional[int]:
        return {TargetRef.RUNG_1: 0,
                TargetRef.RUNG_2: 1,
                TargetRef.RUNG_3: 2}.get(self)


# ---------------------------------------------------------------------------
# Axis 4 -- notification and cure
# ---------------------------------------------------------------------------


class Notice(Enum):
    """Whether the firm owes the client a warning before it acts.

    ``REQUIRED`` -- a duty. SSI, TCBS, Vietcap, HSC (and FPTS, as a display
    duty).

    ``RIGHT_NOT_DUTY`` -- MBS Dieu 4.2a: *"MBS co quyen nhung khong co nghia
    vu gui thong bao"*; VPS 4.4(b) is word-for-word the same.

    ``DISCLAIMED`` -- **affirmatively denied, which is not the same as
    unknown.** KIS 5.1: *"KIS khong co trach nhiem thong bao"*; KIS 5.3:
    *"khong can co bat ky thong bao truoc"*. Gap kind ``G7``.

    ``UNKNOWN`` -- silent. VNDIRECT, SHS, Pinetree. Gap kind ``G8``.

    A simulation that inserts a mandatory notice and a cure window at MBS,
    VPS or KIS **over-states survival**: it gives the account time the
    contract does not. :func:`liquidation_path` therefore drops the step for
    anything that is not ``REQUIRED``.
    """

    REQUIRED = auto()
    RIGHT_NOT_DUTY = auto()
    DISCLAIMED = auto()
    UNKNOWN = auto()

    @property
    def is_obligation(self) -> bool:
        return self is Notice.REQUIRED


class CureKind(Enum):
    """How long the client has, structurally.

    ``IMMEDIATE`` -- none; the firm may act at once. Seven of the eight firms
    that publish anything at the top rung.
    ``SESSIONS`` -- a count of sessions; ``CureSpec.sessions`` carries it.
    ``DEADLINE`` -- a clock time on a named day; ``CureSpec.deadline`` carries
    the description verbatim (HSC: cure to Normal by **11:30 T+1**).
    ``DELEGATED`` -- the window exists and its length is the firm's
    discretion. KIS 5.2: *"trong thoi han theo yeu cau cua KIS tai tung thoi
    diem"*; MBS 4.2(b). Gap kind ``G9``.
    ``UNKNOWN`` -- silent.
    """

    IMMEDIATE = auto()
    SESSIONS = auto()
    DEADLINE = auto()
    DELEGATED = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class CureSpec:
    """One rung's cure window."""

    kind: CureKind
    sessions: Optional[int] = None
    deadline: str = ''

    def __post_init__(self) -> None:
        if self.kind is CureKind.SESSIONS and self.sessions is None:
            raise ValueError('CureKind.SESSIONS needs a session count')
        if self.kind is not CureKind.SESSIONS and self.sessions is not None:
            raise ValueError(
                f'sessions is meaningless for {self.kind}; a cure window that '
                'is not counted in sessions must not carry a session count')
        if self.kind is CureKind.DEADLINE and not self.deadline:
            raise ValueError('CureKind.DEADLINE needs its deadline text')

    @property
    def grants_time(self) -> bool:
        """Does this window actually give the account time to survive in?

        ``DELEGATED`` and ``UNKNOWN`` return ``False``. That is the
        conservative reading and it is deliberate: a window whose length the
        firm sets at its own discretion cannot be relied on to be non-zero,
        and assuming it is non-zero over-states survival.
        """
        return self.kind in (CureKind.SESSIONS, CureKind.DEADLINE)


#: The regulated member-to-VSDC clock, kept here so nobody mistakes a broker's
#: window for it. QD 26 Dieu 13.1: the clearing member tops up before 09h30 the
#: next trading day; Dieu 13.3.b gives 03 working days before VSDC directs
#: another member to close the account. Neither runs broker-to-client.
CCP_TOP_UP_DEADLINE = '09h30 T+1 (QD 26 Dieu 13.1, member to VSDC)'


# ---------------------------------------------------------------------------
# Axis 5 -- the coverage declaration
# ---------------------------------------------------------------------------


class Coverage(Enum):
    """Where one field's value came from. Maps 1:1 onto :data:`GAP_KINDS`.

    ``PUBLISHED`` -- the firm's own operative number, on a retrievable page.
    ``PUBLISHED_ILLUSTRATIVE`` -- a number appears and is a teaching example.
    TCBS's ``Rm 3%`` / ``Sm 1%``. **The most dangerous kind**: it passes any
    naive "is there a number?" test.
    ``PUBLISHED_STALE`` -- genuinely published, and a dated mirror of a VSDC
    table that has since moved.
    ``DELEGATED`` -- the field exists in the firm's own contract and its value
    is deferred to a notice not on the public site.
    ``UNPUBLISHED`` -- we looked and it is not there.
    ``DISCLAIMED`` -- affirmatively denied. Not a hole in our knowledge.
    ``INAPPLICABLE`` -- the firm has **no such concept**. A user warned that
    *"ACBS's forced-close level is unknown"* has been misled; ACBS operates no
    utilisation ladder at all.
    ``CONTRADICTORY`` -- the firm contradicts itself; requires
    ``source_defect``.
    ``INFERRED`` -- ours, from the firm's own arithmetic.
    ``FILLED_FROM_DEFAULT`` -- we supplied it. Must render unmissably.
    """

    PUBLISHED = auto()
    PUBLISHED_ILLUSTRATIVE = auto()
    PUBLISHED_STALE = auto()
    DELEGATED = auto()
    UNPUBLISHED = auto()
    DISCLAIMED = auto()
    INAPPLICABLE = auto()
    CONTRADICTORY = auto()
    INFERRED = auto()
    FILLED_FROM_DEFAULT = auto()

    @property
    def is_firm_operative(self) -> bool:
        """Is this the firm's own operative value, usable without caveat?"""
        return self is Coverage.PUBLISHED

    @property
    def is_supplied_by_us(self) -> bool:
        """We filled this in from another profile, and it says which.

        Narrower than "ours". ``INFERRED`` is also ours, but it is derived
        from the firm's **own** arithmetic -- SSI's parameter set identifies
        the scenario grid whether or not SSI writes the assembly down -- and
        it carries no ``filled_from`` because no other firm supplied it. The
        two are reported separately by
        :meth:`BrokerProfile.supplied_fields` and
        :meth:`BrokerProfile.inferred_fields`, because a reader checking a
        number against SSI's page needs to know which kind it is.
        """
        return self is Coverage.FILLED_FROM_DEFAULT

    @property
    def is_ours(self) -> bool:
        """Not the firm's value, by either route."""
        return self in (Coverage.FILLED_FROM_DEFAULT, Coverage.INFERRED)


class SourceClass(Enum):
    """What kind of document the value came from -- gap kind ``G16``.

    The notification evidence splits along **document class, not firm
    policy**: every firm whose help page promises a notice is a firm whose
    signed terms we do not hold, and every firm whose signed terms we do hold
    disclaims it. A modal count across the two classes measures which
    document we happened to find. Weighting them is the author's call
    (:data:`OPEN_QUESTIONS` ``Q2``); recording the class is not.
    """

    SIGNED_TC = auto()
    PUBLISHED_SCHEDULE = auto()
    HELP_PAGE = auto()
    SECONDARY = auto()
    OURS = auto()

    @property
    def is_contractual(self) -> bool:
        return self is SourceClass.SIGNED_TC


class Severity(Enum):
    """What a gap does to a result.

    ``BLOCKING`` -- the profile cannot produce a number. Construction refuses.
    ``MATERIAL`` -- it runs, but a field that changes margin-call incidence is
    not the firm's. Warned once, and **stamped into every result object**, so
    a number cannot be lifted out of a notebook and quoted clean.
    ``ADVISORY`` -- affects timing or reporting only.
    """

    BLOCKING = auto()
    MATERIAL = auto()
    ADVISORY = auto()

    @property
    def warning_class(self) -> type:
        if self is Severity.ADVISORY:
            return AdvisoryCoverageWarning
        return MaterialCoverageWarning


class GapKind(Enum):
    """The eighteen gap kinds actually observed in the survey.

    Nothing here is invented: each was produced by a firm and a sentence, and
    :data:`GAP_KINDS` carries the meaning and the exemplars. A test asserts
    that every id cited in a docstring in this module is in the register, so
    the register cannot silently fall behind the code.
    """

    G1_DELEGATED = 'G1'
    G2_PUBLISHED_ILLUSTRATIVE = 'G2'
    G3_DENOMINATOR_UNDEFINED = 'G3'
    G4_DENOMINATOR_DIVERGENT = 'G4'
    G5_ACTION_UNKNOWN = 'G5'
    G6_TARGET_UNRESOLVED = 'G6'
    G7_NOTICE_DISCLAIMED = 'G7'
    G8_NOTICE_UNKNOWN = 'G8'
    G9_CURE_DELEGATED = 'G9'
    G10_MODEL_NOT_STATED = 'G10'
    G11_MODEL_SPLIT_UNRESOLVED = 'G11'
    G12_PARAMETER_VINTAGE = 'G12'
    G13_PRE_KRX_DOCUMENT = 'G13'
    G14_SOURCE_SELF_CONTRADICTORY = 'G14'
    G15_INAPPLICABLE = 'G15'
    G16_SOURCE_CLASS_WEAK = 'G16'
    G17_UNIT_MISMATCH = 'G17'
    G18_HOMONYM = 'G18'

    @property
    def meaning(self) -> str:
        return GAP_KINDS[self.value]


#: Every gap kind, its meaning, and the firm and sentence that produced it.
#:
#: Ids match the selection brief section 4.1 so the two can be diffed.
GAP_KINDS: Mapping[str, str] = MappingProxyType({
    'G1': (
        'DELEGATED. The field exists in the firm own contract and its value '
        'is deferred to a notice not on the public site. MBS sections '
        '1.28-1.32, five ratios, all "do MBS quy dinh tung thoi ky"; KIS '
        'Dieu 5 names three levels and prints zero percentages; VPS section '
        '1.19.'
    ),
    'G2': (
        'PUBLISHED_ILLUSTRATIVE. A number appears and is a teaching example, '
        'not the operative value. TCBS Rm 3% / Sm 1% (research S-13); its '
        'operative rates are delegated to "bang VSD cung cap". This kind '
        'passes any naive "is there a number?" test, which is what makes it '
        'the most dangerous one in the register.'
    ),
    'G3': (
        'DENOMINATOR_UNDEFINED. The ratio is published; the divisor is named '
        'but not composed, or not named at all. SSI names it ("tong gia tri '
        'tai san ky quy hop le") without composition, cap or haircut; TCBS '
        'does not name it. Alone among the number-publishing firms TCBS does '
        'not even name its divisor.'
    ),
    'G4': (
        'DENOMINATOR_DIVERGENT. The divisor IS defined and is not V_KQ. '
        'VNDIRECT and FPTS subtract liabilities from assets; SHS adds them to '
        'the numerator; VCBS states cash-100% while computing a DTA tier. '
        'This is not a gap in our knowledge -- it is a gap between firms, and '
        'merging them is the defect.'
    ),
    'G5': (
        'ACTION_UNKNOWN. A rung is published and fire-vs-target is unstated. '
        'VNDIRECT attaches no action text to any of its three levels; FPTS '
        'publishes 100% with no target.'
    ),
    'G6': (
        'TARGET_UNRESOLVED. Level-targeting is stated and the target has no '
        'number, because the level it names is itself delegated. MBS acts '
        '"de dam bao AR duy tri"; KIS restores to "duoi muc Canh bao muc do '
        '1". Both targets are real and both are unpublished.'
    ),
    'G7': (
        'NOTICE_DISCLAIMED. Not unknown -- affirmatively denied. MBS 4.2(a) '
        'and VPS 4.4(b): "co quyen nhung khong co nghia vu gui thong bao"; '
        'KIS 5.1 "khong co trach nhiem thong bao" and 5.3 "khong can co bat '
        'ky thong bao truoc". A model with a mandatory notice step '
        'over-states survival at these three.'
    ),
    'G8': (
        'NOTICE_UNKNOWN. The firm is silent. VNDIRECT, SHS, Pinetree.'
    ),
    'G9': (
        'CURE_DELEGATED. The window exists as a concept and its length is '
        'discretionary. KIS 5.2 "trong thoi han theo yeu cau cua KIS tai tung '
        'thoi diem"; MBS 4.2(b).'
    ),
    'G10': (
        'MODEL_NOT_STATED. Ladder and parameters are published and the '
        'formula behind the numerator never appears. SSI, across its entire '
        'page -- a reader can and will mistake "Ty le ky quy rui ro 17%" for '
        'an IM ratio in an IM+VM model. Vietcap states IM+VM in prose while '
        'tabling the VSD scenario ratio.'
    ),
    'G11': (
        'MODEL_SPLIT_UNRESOLVED. The firm publishes one model for the '
        'overnight number and applies its ladder to an intraday ratio it '
        'never defines. TCBS: the Max(Rm+Sm+Dm+FSP-OA, MM) block is headed '
        '"so tien ky quy ma TCBS can phai nop cuoi ngay", while 85/87/90 run '
        'on "Ty le su dung tai san", whose numerator TCBS never defines. '
        'This is research conflict C-1 occurring inside one firm own '
        'documents.'
    ),
    'G12': (
        'PARAMETER_VINTAGE. Genuinely published, and a snapshot of a VSDC '
        'table that has moved. SHS Sm 0.42% against SSI 0.87%; SHS 22.3M '
        'against SSI 34.5M per contract; SSI own superseded page 80/85/90 '
        'effective 2025-09-11, which prints Sm = 17% -- self-evidently a '
        'placeholder.'
    ),
    'G13': (
        'PRE_KRX_DOCUMENT. The instrument predates the 2025-05-05 cutover and '
        'may describe a superseded regime. HSC page dated 15.04.2020; MBS '
        'terms issued under QD 18/2019/MBS ngay 02/07/2019; KIS derivatives '
        'terms stamped "Ver 2022" inside a file named 1.2026.'
    ),
    'G14': (
        'SOURCE_SELF_CONTRADICTORY. The firm contradicts itself and we are '
        'not repairing a counterparty contract. VPS section 1.13 (a minimum '
        'to maintain) against Part E section 4.4(c) (a maximum to stay '
        'under) -- research conflict C-4, and the bilingual text repeats the '
        'error in English so it is not a translation slip. VCBS cash-100% '
        'against its own DTA tier. Pinetree inverted inequality (C-6). HSC '
        'states its remedy target as the "Ky quy duy tri" band (R >= 80%) in '
        'its rung table and as "trang thai Binh thuong" (R >= 100%) in the '
        'two clauses below it. SSI superseded schedule prints Sm = 17% one '
        'row above a per-contract requirement that implies an index level of '
        '932.7 -- the two rows cannot both hold.'
    ),
    'G15': (
        'INAPPLICABLE. The firm has no such concept, which is categorically '
        'different from not publishing one. ACBS operates no utilisation '
        'ladder: its 5% "ty le tien giu lai toi thieu" is a buying-power '
        'reserve entering as x(1+5%). Telling a user that ACBS forced-close '
        'level is "unknown" misleads them.'
    ),
    'G16': (
        'SOURCE_CLASS_WEAK. The value comes from a help or marketing page '
        'while the same firm signed terms are silent or opposite. Every firm '
        'promising a notice on a help page (SSI, TCBS, Vietcap, HSC, FPTS) is '
        'a firm whose signed terms we do not hold; every firm whose signed '
        'terms we do hold (MBS, VPS, KIS) disclaims it. A help page is not a '
        'contract.'
    ),
    'G17': (
        'UNIT_MISMATCH. Published in a convention that cannot be pooled '
        'without a modelling choice. HSC coverage ratio converts to '
        'utilisation as U = 1/R if MR == IM but U = 0.8/R if MR == MM = 0.8 x '
        'IM -- 25 points apart on the same rung. HSC is therefore excluded '
        'from every PLUTUS_DEFAULT numeric pool rather than converted.'
    ),
    'G18': (
        'HOMONYM. One field name, different quantities across firms. '
        '"Gia tri ky quy toi thieu/1HD" is MF = 5,000d at TCBS and '
        '34,520,710d at SSI, three orders of magnitude apart: SSI number is '
        'the total per-contract requirement at that page index level, a '
        'dated snapshot, not a policy constant. Also QD 26 Dieu 8 x = 80% (a '
        'collateral cap) against VCBS 100% (eligibility) against ACBS 5% (a '
        'fee reserve). And, in our own code, types.BrokerProfile against '
        'this module BrokerProfile.'
    ),
})


#: The fields whose value changes **margin-call incidence**. A gap on one of
#: these is at least MATERIAL; a gap elsewhere is ADVISORY.
MARGIN_CRITICAL_FIELDS: frozenset = frozenset({
    'direction',
    'denominator',
    'liabilities_treatment',
    'margin_model_intraday',
    'margin_model_overnight',
    'user_facing_model',
    'initial_margin_ratio',
    'block_open_level',
    'margin_call_level',
    'forced_close_level',
    'ccp_processing_level',
    'target',
    # The rates the requirement itself is built from. A stale Sm moves MR by
    # the whole difference between 0.42% and 0.87% -- twice the number, on the
    # same instrument, from two firms both presenting theirs as current.
    'vsdc_parameters',
    'maintenance_margin_fraction',
})


@dataclass(frozen=True)
class Derivation:
    """How a PLUTUS_DEFAULT value was derived. The author's rule 4.

    *"Every derived value records its derivation: the rule, the source firms
    by name, and n. A field derived from two firms must not look like one
    derived from five."*

    That is a structured requirement, so this is a structured record rather
    than a prose blob -- the ``n`` of a field must be machine-readable for
    :meth:`describe` to be able to refuse to call an ``n = 1`` field a median.

    ``rule`` is one of ``'median'``, ``'modal'``, ``'sole source'``,
    ``'exchange rule'``. ``sources`` names the firms **by name**. ``excluded``
    names the firms left out of the pool and why, because an exclusion that is
    not recorded is indistinguishable from an oversight.
    """

    rule: str
    sources: Tuple[str, ...]
    n: int
    excluded: Tuple[str, ...] = ()
    cross_check: str = ''
    note: str = ''

    def __post_init__(self) -> None:
        if self.n != len(self.sources) and self.rule in ('median', 'modal'):
            if self.n < len(self.sources):
                raise ValueError(
                    f'n={self.n} is smaller than the {len(self.sources)} '
                    f'source firms named; n is the pool size and cannot be '
                    'less than the firms it is drawn from')

    def describe(self) -> str:
        """The derivation as one sentence, and it refuses to overclaim.

        An ``n = 1`` field renders as *"n=1 -- this is X's number, not a
        median"*, because the post-withdrawal cap, the VM settlement deadline
        and the late-payment rate each rest on TCBS alone and a table that
        prints them beside a five-firm median invites exactly the mistake the
        author's rule 4 exists to prevent.
        """
        who = ', '.join(self.sources) if self.sources else 'no firm'
        if self.n == 1:
            head = (f'n=1 -- this is {who}\'s number, not a median')
        else:
            head = f'{self.rule} of n={self.n} ({who})'
        parts = [head]
        if self.excluded:
            parts.append('excluded: ' + ', '.join(self.excluded))
        if self.cross_check:
            parts.append('cross-check: ' + self.cross_check)
        if self.note:
            parts.append(self.note)
        return '; '.join(parts)

    def __str__(self) -> str:
        return self.describe()


@dataclass(frozen=True)
class FieldCoverage:
    """Where one field's value came from, and what quantity it actually is.

    ``quantity`` is not decoration. It exists because of gap kind ``G18``: a
    loader that maps SSI's *"Gia tri ky quy toi thieu/1HD: 34.520.710 dong"*
    into ``MF`` makes ``MM`` bind on every book and destroys
    ``MR = max(Rm + Sm - OA, MM)``. A coverage record that carries only the
    number and its source cannot catch that; one that carries the **quantity**
    can, and :meth:`BrokerProfile.minimum_margin_factor` does.

    ``effective_from`` is the date **the firm states**, never our fetch date;
    ``fetched_on`` is ours. Keeping them apart is what makes SSI's version
    history datable and HSC's 2020 stamp visible.
    """

    status: Coverage
    quantity: str
    source_class: SourceClass
    source_url: Optional[str] = None
    effective_from: Optional[date] = None
    fetched_on: Optional[date] = None
    quote: Optional[str] = None
    filled_from: Optional[str] = None
    derivation: Optional[Derivation] = None
    source_defect: Optional[str] = None
    gap: Optional[GapKind] = None
    note: str = ''

    def __post_init__(self) -> None:
        if not self.quantity:
            raise ValueError(
                'quantity is required on every FieldCoverage: gap kind G18 is '
                'a homonym problem, and a record that says only "34,520,710, '
                'published by SSI" cannot tell you it is not MF')
        if self.status is Coverage.CONTRADICTORY and not self.source_defect:
            raise ValueError(
                'Coverage.CONTRADICTORY requires source_defect naming the two '
                'clauses that disagree; an unexplained contradiction is '
                'indistinguishable from a typo of ours')
        if self.status is Coverage.FILLED_FROM_DEFAULT and not self.filled_from:
            raise ValueError(
                'Coverage.FILLED_FROM_DEFAULT requires filled_from: a supplied '
                'field that does not say who supplied it is exactly the thing '
                'the honesty guarantee forbids')
        if self.filled_from and self.status is not Coverage.FILLED_FROM_DEFAULT:
            raise ValueError(
                f'filled_from={self.filled_from!r} on status {self.status}; '
                'only FILLED_FROM_DEFAULT may name a filler')

    @property
    def is_published(self) -> bool:
        """The firm's own number, on the firm's own document.

        ``PUBLISHED_ILLUSTRATIVE`` is **excluded** even though a number is
        printed: TCBS's ``3%`` is on TCBS's page and is not TCBS's rate.
        """
        return self.status in (Coverage.PUBLISHED, Coverage.PUBLISHED_STALE)

    @property
    def is_supplied(self) -> bool:
        """We produced this value; the firm did not."""
        return self.status.is_supplied_by_us

    def severity(self, *, critical: bool) -> Optional[Severity]:
        """What this gap does to a result. ``None`` when there is no gap.

        ``DISCLAIMED`` is MATERIAL wherever it appears, including on the
        notification field which is otherwise advisory: a disclaimed notice
        removes a step from the liquidation path, which changes when positions
        are closed and therefore changes the number.

        **A ``PUBLISHED`` field can still carry a gap**, and it is not a
        contradiction. FPTS's notification duty is published *on a help page
        while its signed terms are silent* (``G16``); SSI's per-contract
        requirement is published and means something other than what its label
        says (``G18``). Both are real caveats on a real number. ``G18`` is
        always MATERIAL, critical field or not, because the failure mode is
        reading the number as a different quantity rather than reading it
        imprecisely.
        """
        if self.status is Coverage.PUBLISHED:
            if self.gap is None:
                return None
            if self.gap is GapKind.G18_HOMONYM:
                return Severity.MATERIAL
            return Severity.MATERIAL if critical else Severity.ADVISORY
        if self.status is Coverage.DISCLAIMED:
            return Severity.MATERIAL
        if self.status is Coverage.INAPPLICABLE:
            return Severity.ADVISORY
        if critical:
            return Severity.MATERIAL
        return Severity.ADVISORY

    def render(self) -> str:
        """One line, with supplied fields marked unmissably."""
        head = self.status.name
        if self.status is Coverage.FILLED_FROM_DEFAULT:
            head = f'*** SUPPLIED BY {self.filled_from} -- NOT THE FIRM\'S ***'
        bits = [head, f'quantity={self.quantity}']
        if self.derivation is not None:
            bits.append(self.derivation.describe())
        if self.gap is not None:
            bits.append(self.gap.value)
        if self.source_defect:
            bits.append(f'defect: {self.source_defect}')
        return ' | '.join(bits)

    @classmethod
    def undeclared(cls, quantity: str, *, note: str = '') -> 'FieldCoverage':
        """The explicit way for a caller to say *"I do not know"*.

        A user-defined profile that omits a coverage entry **raises**; it does
        not silently become ``UNPUBLISHED``. This constructor is how the
        caller declares the gap deliberately. It is their declaration to make,
        not ours to invent, and the ``OURS`` source class records that the
        statement is the caller's rather than a firm's.
        """
        return cls(status=Coverage.UNPUBLISHED, quantity=quantity,
                   source_class=SourceClass.OURS,
                   note=note or 'declared unsourced by the caller')


@dataclass(frozen=True)
class Gap:
    """One field's gap, resolved to a severity."""

    field_name: str
    coverage: FieldCoverage
    severity: Severity

    def describe(self) -> str:
        kind = self.coverage.gap.value if self.coverage.gap else '-'
        return (f'{self.field_name}: {self.coverage.status.name} '
                f'[{kind}] {self.coverage.note or self.coverage.quantity}')


# ---------------------------------------------------------------------------
# The sixth axis -- margin model selection
# ---------------------------------------------------------------------------


class MarginModel(Enum):
    """Which model computes the number the ladder divides by.

    ``SCENARIO_GRID`` -- ``Max(Rm + Sm + Dm + FSP - OA, MM)``, QD 26 Phu luc
    2, implemented by :mod:`plutus.market.session.scenario_margin`. Computed
    once, *"sau khi ket thuc phien giao dich"*, on the **underlying's close**.

    ``IM_PLUS_VM_PLUS_DM`` -- ``MR = IM + VM + DM (+ other obligations)``,
    implemented by :mod:`plutus.market.session.deposit`. Updated
    *"lien tuc trong phien"*, on the **futures traded price**.

    ``IM_PLUS_VM`` -- Vietcap's two-term form; the same engine with ``DM``
    absent.

    ``IM_ONLY_WITH_MM`` -- HSC: the divisor is ``IM`` and the floor is
    ``MM = 80% x IM``. The only IM/MM model in the pool.

    ``UNSTATED`` -- the firm publishes a ladder and no formula. **SSI**, whose
    page is a parameter table with no model on it (gap kind ``G10``); TCBS's
    intraday numerator (gap kind ``G11``).

    **All ten firms that state a formula for their client ladder state
    IM+VM+DM. Zero state the scenario grid.** The four firms that publish
    scenario-grid material each label it, where they label it at all, as the
    end-of-day VSDC submission. So the two models are not two firms' answers
    to one question -- they are two layers of one firm's answer, which is
    research conflict C-1 surfacing inside individual firms' own documents.
    That is why a profile carries both and names which one faces the user.
    """

    SCENARIO_GRID = auto()
    IM_PLUS_VM_PLUS_DM = auto()
    IM_PLUS_VM = auto()
    IM_ONLY_WITH_MM = auto()
    UNSTATED = auto()

    @property
    def engine(self) -> Optional[str]:
        """The module that computes this model, or ``None`` if unstated.

        A string, not an import: this module **selects** a model and must not
        acquire a dependency on either engine to say which one was selected.
        """
        if self is MarginModel.SCENARIO_GRID:
            return 'plutus.market.session.scenario_margin'
        if self is MarginModel.UNSTATED:
            return None
        return 'plutus.market.session.deposit'

    @property
    def is_continuous(self) -> bool:
        """Updated in-session, rather than once after the close."""
        return self in (MarginModel.IM_PLUS_VM_PLUS_DM,
                        MarginModel.IM_PLUS_VM,
                        MarginModel.IM_ONLY_WITH_MM)


class MarginLayer(Enum):
    """Which layer's number the user is shown and tested against.

    There is **one user-facing margin number**. A profile carries both models
    because the evidence carries both, and this says which of them is the one.
    ``INTRADAY`` is the broker's continuously-updated number; ``OVERNIGHT`` is
    the CCP submission.
    """

    INTRADAY = auto()
    OVERNIGHT = auto()


# ---------------------------------------------------------------------------
# The ladder, and the two things that are not ladders
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rung:
    """One step of one firm's ladder.

    ``level`` is ``None`` when the firm delegates it. It is **never silently
    defaulted**: a rung with no level is a BLOCKING gap and construction
    refuses unless the caller opts in to filling it.

    ``name`` is the firm's own label for the rung, unfolded, so a reader can
    match it to the page: *"Ty le duy tri"*, *"AR xu ly"*, *"Canh bao muc do
    2"*.
    """

    coverage_key: str
    name: str
    level: Optional[Decimal]
    action: Action
    target_ref: TargetRef = TargetRef.NONE
    target_absolute: Optional[Decimal] = None
    notice: Notice = Notice.UNKNOWN
    cure: CureSpec = field(default_factory=lambda: CureSpec(CureKind.UNKNOWN))
    follow_on: Optional[Action] = None
    """What the firm does **after** ``action``, when it publishes an ordering.

    Only SSI does **at a rung**, at Muc 3: *"tu dong dieu chuyen tien ...
    **va/hoac** thuc hien dong vi the bat buoc"* -- collateral is moved first
    and positions are closed second. TCBS publishes the same shape twice but
    hangs it off events rather than rungs (a missed VM payment, a VSDC
    breach), so it is recorded in TCBS's coverage and not here. Collapsing the
    pair into ``LIQUIDATE`` **over-states forced selling** at both firms;
    dropping the second half under-states it. So the ordering is a field.
    """

    def __post_init__(self) -> None:
        if self.target_ref is TargetRef.ABSOLUTE:
            if self.target_absolute is None:
                raise ValueError(
                    f'{self.coverage_key}: TargetRef.ABSOLUTE needs '
                    'target_absolute')
        elif self.target_absolute is not None:
            raise ValueError(
                f'{self.coverage_key}: target_absolute is set but target_ref '
                f'is {self.target_ref}; a target level that is not declared '
                'absolute must be a reference to a rung, because that is how '
                'every surveyed firm publishes it')
        if self.level is not None and self.level < 0:
            raise ValueError(
                f'{self.coverage_key}: level must not be negative')

    @property
    def is_targeting(self) -> bool:
        """Does this rung close positions *until a named level*?"""
        return self.target_ref is not TargetRef.NONE

    @property
    def level_is_delegated(self) -> bool:
        return self.level is None


@dataclass(frozen=True)
class Cap:
    """A utilisation ceiling on an action, which is not a rung.

    TCBS permits a withdrawal only if the post-withdrawal ratio is at or below
    **80**; MBS names a *"ty le sau mo vi the"* and a *"ty le sau rut"* and
    delegates both. These constrain what an account may *do* at a given ratio;
    they never fire on their own, so putting them in the ladder would invent
    rungs that no firm has.
    """

    coverage_key: str
    name: str
    level: Optional[Decimal]
    description: str = ''


@dataclass(frozen=True)
class NamedRatio:
    """A ratio the ladder cannot hold -- the section 4.3 escape hatch.

    VPS's *"Ty le an toan"* (section 1.14) is *"ty le do VPS xac dinh dua tren
    gia tri tai san rong cua Khach hang"*, and section 1.19 makes it a
    warning-threshold dimension in its own right, alongside utilisation and
    position limits. Its numerator is net asset value, not a margin
    requirement, so it is neither a utilisation nor a coverage ratio, and
    **its formula is not published**. Forcing it into the ladder would
    misrepresent it; dropping it would hide a live warning dimension.
    """

    name: str
    numerator: str
    denominator: str
    formula_published: bool
    thresholds: Tuple[Decimal, ...] = ()
    note: str = ''


@dataclass(frozen=True)
class BuyingPowerSpec:
    """ACBS's retained-cash multiplier, which is not a threshold on anything.

    *"Ty le tien giu lai toi thieu tai ACBS la 5%"*: a fee/tax/VM reserve that
    enters buying power as ``x (1 + 5%)``. It reduces the position a given
    balance can open, which changes **when** an account reaches a rung without
    being a rung. Do not merge it with QD 26 Dieu 8's ``x = 80%`` collateral
    cap or VCBS's 100% eligibility rule -- defect ``D-28``, three concepts
    under similar names.
    """

    retained_cash_fraction: Decimal
    description: str = ''

    def scale(self, cash: Decimal) -> Decimal:
        """Buying power implied by ``cash`` under this reserve."""
        return cash / (Decimal('1') + self.retained_cash_fraction)


# ---------------------------------------------------------------------------
# The parameter feed -- what a firm mirrors from VSDC's table
# ---------------------------------------------------------------------------
#
# The ladder decides *when* a firm acts. These decide *what number* it acts on,
# and without them a profile that calls itself "the parameter feed" cannot feed
# anything. SSI publishes every input the scenario grid needs and no formula;
# TCBS publishes the formula and delegates every input. Neither alone runs a
# margin call, which is the whole of selection-brief section 2, and it is only
# checkable if the parameters are objects rather than prose.


@dataclass(frozen=True)
class PositionLimits:
    """VSDC's per-account contract caps. An **exchange rule**, not a term.

    SSI and TCBS publish the identical triple and both attribute it: SSI's
    schedule prints it beside the margin parameters, TCBS's says *"Theo quy
    dinh tai VSD"*. Selection-brief field 21 therefore classes it with the
    QD 26 Dieu 9 haircuts -- restated law, stored so a reader can see the firm
    restated it, and never stored as if the firm had chosen it.

    The three investor classes are VSDC's, not ours: *"NDT ca nhan"*,
    *"NDT to chuc"*, *"NDT chung khoan chuyen nghiep"*.
    """

    individual: int
    institutional: int
    professional: int
    attribution: str = 'theo quy dinh VSD -- an exchange rule, not a broker term'

    def limit_for(self, investor_class: str) -> int:
        """The cap for one investor class, by VSDC's own name for it."""
        table = {'individual': self.individual,
                 'institutional': self.institutional,
                 'professional': self.professional}
        if investor_class not in table:
            raise KeyError(
                f'{investor_class!r} is not one of VSDC\'s three investor '
                f'classes: {", ".join(sorted(table))}')
        return table[investor_class]


@dataclass(frozen=True)
class UnderlyingParameters:
    """One underlying's row of the VSDC parameter table, as a firm mirrors it.

    Every field is an input to :mod:`plutus.market.session.scenario_margin`
    and to nothing else, which is why a firm that publishes all five has
    identified the model whether or not it writes the assembly down (SSI's
    ``margin_model_overnight`` is ``INFERRED`` on exactly that ground).

    ``minimum_per_contract_requirement`` is the field gap kind ``G18`` bites
    on. It is **not** ``MF``. SSI prints it as *"Gia tri ky quy toi thieu/1HD:
    34.520.710 dong"* and TCBS prints ``5,000d`` under the same Vietnamese
    phrase; the two differ by three orders of magnitude because they are
    different quantities. :attr:`implied_index_level` is the arithmetic that
    proves it -- a policy constant does not track the index, and this one
    does.
    """

    underlying: str
    risk_margin_rate: Decimal
    """``Ty le ky quy rui ro`` -- the scenario grid's Rm rate. **Not an IM
    ratio**, and reading it as one is research conflict C-1 in miniature."""

    spread_margin_rate: Decimal
    """``Ty le ky quy song hanh`` -- Sm. Dated: SHS mirrors 0.42% where SSI
    mirrors 0.87% on the same instrument (gap kind ``G12``)."""

    price_scan_range: Optional[Decimal] = None
    """``Ty le tuong quan ve gia ... trong cung Product Group`` -- ``Psr``,
    the offsetting factor of QD 26 Phu luc 2 section 2.2.e. SSI moved it from
    ``1`` to ``0.85`` between its two published vintages.

    ``None`` where the firm mirrors the rates and not the offset parameters.
    SHS is the case: it prints Rm, Sm and a per-contract figure and no ``Psr``
    at all, so a group offset cannot be computed from SHS's page. That is a
    real limit on what an SHS-parameterised book can produce, and a zero here
    would hide it behind a number that means *"no offsetting"*.
    """

    scale_factor: Optional[Decimal] = None
    """``He so tuong quan quy mo cua TSCS`` -- the size-correlation factor
    used in the same offset. ``1`` for VN30, ``1.03`` for VN100. ``None`` on
    the same terms as :attr:`price_scan_range`."""

    delivery_margin_rate: Optional[Decimal] = None
    """``Ty le ky quy chuyen giao`` -- ``Dm``. Every firm that prints one
    prints it **for government-bond futures only**; SHS's table attaches
    ``2.5%`` to ``HDTL TPCP`` and leaves the index row blank. So ``None`` here
    on a VN30 row is the firm's answer, not a gap."""

    minimum_per_contract_requirement: Optional[Decimal] = None
    multiplier: Decimal = Decimal('100000')
    note: str = ''

    def __post_init__(self) -> None:
        for name in ('risk_margin_rate', 'spread_margin_rate',
                     'price_scan_range', 'scale_factor',
                     'delivery_margin_rate'):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Decimal):
                raise TypeError(
                    f'{self.underlying}.{name} must be a Decimal, got '
                    f'{type(value).__name__}; a float rate compounds into a '
                    'margin requirement that cannot be reconciled with the '
                    'firm\'s own published example')
        if self.minimum_per_contract_requirement is not None:
            if self.minimum_per_contract_requirement <= MINIMUM_MARGIN_FACTOR:
                raise HomonymError(
                    f'{self.underlying}: minimum_per_contract_requirement is '
                    f'{self.minimum_per_contract_requirement}, at or below MF '
                    f'({MINIMUM_MARGIN_FACTOR}). This field holds the TOTAL '
                    'per-contract requirement at a dated index level, not MF '
                    '-- gap kind G18. If you meant MF, it is a derived '
                    'constant and lives at MINIMUM_MARGIN_FACTOR.')

    @property
    def total_margin_rate(self) -> Decimal:
        """``Rm rate + Sm rate`` -- what a per-contract requirement divides by."""
        return self.risk_margin_rate + self.spread_margin_rate

    @property
    def supports_group_offsetting(self) -> bool:
        """Can a group offset be computed from this firm's published row?

        ``False`` at SHS, which mirrors the rates and not ``Psr``. Asking
        :mod:`plutus.market.session.scenario_margin` for an offset on a row
        that says ``False`` means supplying the missing factor from somewhere
        else, and that somewhere else is another firm.
        """
        return (self.price_scan_range is not None
                and self.scale_factor is not None)

    @property
    def implied_index_level(self) -> Optional[Decimal]:
        """The index level this row's per-contract requirement implies. OURS.

        ``34,520,710 / ((0.17 + 0.0087) x 100,000) = 1931.8`` for SSI's VN30
        row and ``22,309,440 / ((0.17 + 0.0042) x 100,000) = 1280.7`` for
        SHS's. Both are plausible VN30 levels of their own vintage, and that
        is the proof that the published number is a **dated snapshot** rather
        than the policy constant ``MF``.

        Unlike :meth:`BrokerProfile.implied_index_level` this needs no rates
        from the caller: the row carries its own, so the arithmetic cannot be
        run against another firm's parameters by accident.
        """
        if self.minimum_per_contract_requirement is None:
            return None
        rate = self.total_margin_rate
        if rate <= 0:
            return None
        return self.minimum_per_contract_requirement / (rate * self.multiplier)


@dataclass(frozen=True)
class VsdcParameterSet:
    """A firm's **dated mirror** of VSDC's parameter table.

    Dated is the operative word and it is why this is an object rather than
    five loose fields. VSDC's table moves; each firm's page is a snapshot of
    it taken on a day the firm does not always print. Two mirrors held side by
    side are the cleanest available evidence of gap kind ``G12``, and holding
    them as objects is what lets a test assert that they **disagree** rather
    than quietly preferring one.

    ``effective_from`` is the date the firm states. SSI states both of its
    (2026-01-16 and 2025-09-11), which is why SSI is the only firm in the
    survey with a datable version history.
    """

    effective_from: Optional[date]
    underlyings: Tuple[UnderlyingParameters, ...]
    position_limits: Optional[PositionLimits] = None
    source: str = ''

    def __post_init__(self) -> None:
        names = [row.underlying for row in self.underlyings]
        if len(names) != len(set(names)):
            raise ValueError(
                f'duplicate underlying in a parameter set: {names}. Two rows '
                'for one underlying means two vintages, and a vintage is a '
                'whole parameter set -- ship it as a second profile, the way '
                'SSI and Pinetree do.')

    @property
    def names(self) -> Tuple[str, ...]:
        return tuple(row.underlying for row in self.underlyings)

    def for_underlying(self, underlying: str) -> UnderlyingParameters:
        """One underlying's row, or a ``KeyError`` naming what is held."""
        for row in self.underlyings:
            if row.underlying == underlying:
                return row
        raise KeyError(
            f'{underlying!r} is not in this parameter set. Held: '
            f'{", ".join(self.names) or "nothing"}. Do not substitute another '
            'underlying\'s row: Sm alone differs by 34% between VN30 and '
            'VN100 on the same page.')


@dataclass(frozen=True)
class CcpBreachTest:
    """QD 26 Dieu 13's binary test, as a distinct object from the ladder.

    *"Truong hop gia tri tai san ky quy tren tai khoan nha dau tu nho hon gia
    tri ky quy yeu cau"* -- ``assets < MR``, full stop, no percentage
    anywhere in the article.

    **This is the CCP rung, not the broker rung**, and keeping the two apart
    is the whole content of research conflict C-1. ``broker.py``'s docstring
    currently defends ``forced_close_utilisation = 1.00`` on the ground that
    ``MR / assets >= 1.00`` reproduces this test -- which is correct, and is a
    justification for the *CCP* level. The survey puts the broker's own top
    rung at 95, **below** the CCP breach: the broker fires before the CCP
    does, which is exactly what TCBS's fifth path describes when it disburses
    support to 95 after a VSDC breach. Both rungs exist; neither replaces the
    other. Re-labelling the 1.00 in ``broker.py`` is
    :data:`OPEN_QUESTIONS` ``Q5`` and is not done here.

    At 1.00 the test is conservative by one tick: Dieu 13.2.c restores an
    account whose assets are *"bang hoac lon hon"* the requirement, so
    equality is cured there and a breach here.
    """

    level: Decimal = Decimal('1.00')
    top_up_deadline: str = CCP_TOP_UP_DEADLINE
    substitute_close_out_days: int = 3

    def is_breach(self, required: Decimal, assets: Decimal) -> bool:
        """``assets < required``, stated directly rather than as a ratio."""
        return assets < required


# ---------------------------------------------------------------------------
# The profile
# ---------------------------------------------------------------------------


class Regime(Enum):
    """Which regulatory era the firm's document belongs to. Gap kind ``G13``.

    The KRX cutover is 2025-05-05. A profile built from an instrument dated
    before it may describe a superseded regime -- HSC's page is dated
    2020-04-15, MBS's terms were issued under QD 18/2019/MBS of 2019-07-02,
    and KIS's file is named ``1.2026`` while its own text is stamped
    ``Ver 2022``.
    """

    POST_KRX = auto()
    PRE_KRX = auto()
    UNKNOWN = auto()


#: The KRX cutover, restated rather than imported.
#:
#: ``plutus.market.session.rulebook`` holds the same date. Importing it here
#: would pull the dated rulebook -- and everything it reaches -- into what is
#: meant to be a pure declaration of broker policy, and a test pins that this
#: module imports nothing but ``plutus.market.broker``. The duplication is the
#: cheaper of the two costs, and it is recorded so it is not mistaken for an
#: independent source.
KRX_CUTOVER = date(2025, 5, 5)


@dataclass(frozen=True, eq=False)
class BrokerProfile:
    """One firm's margin policy, with its gaps declared.

    Equality is **identity** (``eq=False``). Two profiles that happen to carry
    the same numbers are not the same policy -- SSI's 85/90/95 and a
    caller-built 85/90/95 differ in everything that matters here, which is
    where the numbers came from.

    See the module docstring for the five axes this expresses and the sixth
    the author added.
    """

    firm: str
    is_synthesis: bool
    regime: Regime
    document_date: Optional[date]

    margin_model_intraday: MarginModel
    margin_model_overnight: MarginModel
    user_facing_model: MarginLayer

    direction: Direction
    denominator: DenominatorSpec
    ladder: Tuple[Rung, ...]

    coverage: Mapping[str, FieldCoverage]

    initial_margin_ratio: Optional[Decimal] = None
    caps: Tuple[Cap, ...] = ()
    additional_ratios: Tuple[NamedRatio, ...] = ()
    buying_power: Optional[BuyingPowerSpec] = None
    ccp_breach: CcpBreachTest = field(default_factory=CcpBreachTest)

    published_per_contract_requirement: Optional[Decimal] = None
    vm_settlement_deadline: str = ''
    late_payment_annual_rate: Optional[Decimal] = None
    minimum_cash_share: Optional[Decimal] = None

    vsdc_parameters: Optional['VsdcParameterSet'] = None
    """The firm's dated mirror of VSDC's parameter table, if it publishes one.

    ``None`` is the common case and it is not a defect: TCBS delegates every
    rate to *"bang VSD cung cap"* and MBS, KIS and VPS never print one. It is
    a defect only in the sense that a profile with no parameters cannot feed
    :mod:`plutus.market.session.scenario_margin`, which is exactly why the
    selection brief ships SSI as the parameter feed and TCBS as the reference
    and says neither alone runs a margin call.
    """

    maintenance_margin_fraction: Optional[Decimal] = None
    """HSC's ``Ty le MM`` in ``MM = Ty le MM x IM``. Only an
    ``IM_ONLY_WITH_MM`` firm has one, and HSC's own page delegates it in
    principle -- *"do HSC quy dinh va co the thay doi theo tung thoi ky"* --
    while printing 80% as the current value."""

    support_disbursement_annual_rate: Optional[Decimal] = None
    """TCBS's ``Phi giai ngan ho tro``, 10.5%/yr. A **second** rate, distinct
    from :attr:`late_payment_annual_rate`: this one prices the cash TCBS
    advances to pull a VSDC-breached account back to 95, before any close-out.
    Merging the two would mis-price the fifth path."""

    superseded_by: Optional[str] = None
    supersedes: Optional[str] = None
    enabled_by_default: bool = True
    description: str = ''

    #: Every coverage key a profile must declare, whatever its answer. One per
    #: axis, so that all five are answered rather than merely available: the
    #: direction; the denominator and its liability treatment; the target
    #: (fire-vs-target); the notification obligation and its cure window; and,
    #: through the per-rung keys added below, the publication status of each
    #: number. Plus the two model fields, which are the author's sixth axis.
    #:
    #: A profile that omits one is asking us to invent its provenance, and
    #: :meth:`__post_init__` raises rather than doing so.
    REQUIRED_KEYS = (
        'direction', 'denominator', 'liabilities_treatment',
        'margin_model_intraday', 'margin_model_overnight',
        'initial_margin_ratio', 'target', 'notification', 'cure_window',
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, 'coverage',
                           MappingProxyType(dict(self.coverage)))
        missing = [key for key in self.REQUIRED_KEYS
                   if key not in self.coverage]
        for rung in self.ladder:
            if rung.coverage_key not in self.coverage:
                missing.append(rung.coverage_key)
        for cap in self.caps:
            if cap.coverage_key not in self.coverage:
                missing.append(cap.coverage_key)
        if missing:
            raise CoverageError(
                f'{self.firm}: no coverage declared for '
                f'{", ".join(sorted(set(missing)))}. Declare each one -- '
                'FieldCoverage.undeclared() is the explicit way to say the '
                'value is unsourced. Defaulting it silently would make us the '
                'author of a provenance claim that is yours to make.')
        levels = [r.level for r in self.ladder if r.level is not None]
        if len(levels) > 1 and not self.direction.ladder_is_ordered(levels):
            raise ValueError(
                f'{self.firm}: ladder {levels} does not run mild-to-severe '
                f'under {self.direction.name}. A ladder ordered the other way '
                'fires its severest rung first.')
        for rung in self.ladder:
            index = rung.target_ref.rung_index
            if index is not None and index >= len(self.ladder):
                raise ValueError(
                    f'{self.firm}: {rung.coverage_key} targets '
                    f'{rung.target_ref.name} but the ladder has '
                    f'{len(self.ladder)} rungs')
        if (self.initial_margin_ratio is not None
                and self.initial_margin_ratio < VSDC_INITIAL_MARGIN_RATIO):
            raise ValueError(
                f'{self.firm}: initial_margin_ratio '
                f'{self.initial_margin_ratio} is below VSDC\'s '
                f'{VSDC_INITIAL_MARGIN_RATIO}. Research S-17: brokers set '
                'their ratio at or above VSDC\'s and publish it; a broker '
                'ratio below the CCP\'s would under-margin every account.')

    # -- the sixth axis ---------------------------------------------------

    @property
    def margin_model(self) -> MarginModel:
        """The model that computes the **one user-facing margin number**.

        This is the selection the author asked for. Both layers are carried;
        this names the one the client's ladder is tested against.
        """
        if self.user_facing_model is MarginLayer.INTRADAY:
            return self.margin_model_intraday
        return self.margin_model_overnight

    @property
    def margin_engine(self) -> Optional[str]:
        """Which module computes :attr:`margin_model`, by name."""
        return self.margin_model.engine

    # -- axis 5, mechanised ----------------------------------------------

    def published_fields(self) -> Tuple[str, ...]:
        """Fields carrying the firm's own number, on the firm's own document."""
        return tuple(sorted(k for k, c in self.coverage.items()
                            if c.is_published))

    def supplied_fields(self) -> Tuple[str, ...]:
        """Fields filled in from another profile. Every one carries
        ``filled_from``.

        This is the honesty guarantee, callable: *a user reading SSI's page
        must never be misled by a field we supplied*.
        """
        return tuple(sorted(k for k, c in self.coverage.items()
                            if c.is_supplied))

    def inferred_fields(self) -> Tuple[str, ...]:
        """Fields we derived from the firm's own material.

        Reported apart from :meth:`supplied_fields` because they are a
        different claim: an inference says *this follows from what the firm
        published*, a fill says *the firm published nothing and we used
        somebody else's number*.
        """
        return tuple(sorted(k for k, c in self.coverage.items()
                            if c.status is Coverage.INFERRED))

    @property
    def numbers_published(self) -> bool:
        """Brief axis 5: does the firm publish its own ladder numbers?

        ``False`` for MBS, KIS and VPS, which name their ratios and delegate
        every value.
        """
        return bool(self.ladder) and all(
            self.coverage[r.coverage_key].is_published for r in self.ladder)

    def gaps(self) -> Tuple[Gap, ...]:
        """Every declared gap, severity-resolved, worst first."""
        found = []
        for key, cov in self.coverage.items():
            severity = cov.severity(critical=key in MARGIN_CRITICAL_FIELDS)
            if severity is None:
                continue
            if self._is_blocking(key, cov):
                severity = Severity.BLOCKING
            found.append(Gap(field_name=key, coverage=cov, severity=severity))
        if self.regime is Regime.PRE_KRX:
            found.append(Gap(
                field_name='regime',
                coverage=FieldCoverage(
                    status=Coverage.PUBLISHED_STALE,
                    quantity='the whole instrument',
                    source_class=SourceClass.SECONDARY,
                    gap=GapKind.G13_PRE_KRX_DOCUMENT,
                    effective_from=self.document_date,
                    note=(f'{self.firm}\'s document is dated '
                          f'{self.document_date} -- before the KRX cutover '
                          f'{KRX_CUTOVER}; it may describe a superseded '
                          'regime'),
                ),
                severity=Severity.MATERIAL))
        order = {Severity.BLOCKING: 0, Severity.MATERIAL: 1,
                 Severity.ADVISORY: 2}
        return tuple(sorted(found,
                            key=lambda g: (order[g.severity], g.field_name)))

    def _is_blocking(self, key: str, cov: FieldCoverage) -> bool:
        """A gap blocks when the profile cannot produce a **number** for it.

        Only ladder rungs and caps can block, and only when their level is
        actually missing. A delegated *cure window* does not block: the
        profile still runs, it just cannot say how long the client has.
        """
        if cov.status is not Coverage.DELEGATED:
            return False
        for rung in self.ladder:
            if rung.coverage_key == key:
                return rung.level is None
        for cap in self.caps:
            if cap.coverage_key == key:
                return cap.level is None
        return False

    def blocking_fields(self) -> Tuple[str, ...]:
        return tuple(g.field_name for g in self.gaps()
                     if g.severity is Severity.BLOCKING)

    def material_caveats(self) -> Tuple[str, ...]:
        """The sentences stamped into every result this profile produces."""
        return tuple(g.describe() for g in self.gaps()
                     if g.severity is Severity.MATERIAL)

    # -- filling ----------------------------------------------------------

    def level_for(self, coverage_key: str) -> Optional[Decimal]:
        """This profile's level for a coverage key, from any of its holders.

        Falls back through :data:`LEVEL_ALIASES` only when the key is not one
        of this profile's own. The aliases exist because firms name the same
        *quantity* differently -- MBS's *"ty le sau mo vi the"* is the same
        thing as the maximum utilisation at which a new position may be
        opened -- and a fill that could not cross those names would refuse to
        fill fields we can honestly fill.
        """
        for rung in self.ladder:
            if rung.coverage_key == coverage_key:
                return rung.level
        for cap in self.caps:
            if cap.coverage_key == coverage_key:
                return cap.level
        if coverage_key == 'ccp_processing_level':
            return self.ccp_breach.level
        alias = LEVEL_ALIASES.get(coverage_key)
        if alias is not None and alias != coverage_key:
            return self.level_for(alias)
        return None

    def filled_from(self, source: 'BrokerProfile') -> 'BrokerProfile':
        """A copy with every blocking level supplied from ``source``.

        Every filled field's coverage becomes ``FILLED_FROM_DEFAULT`` and
        carries ``filled_from``, so :meth:`supplied_fields` names it and
        :meth:`render_coverage` marks it unmissably. Nothing else moves: a
        firm whose denominator is unpublished keeps an unpublished
        denominator, because filling a *composition* from another firm would
        be inventing policy rather than borrowing a number.
        """
        keys = set(self.blocking_fields())
        if not keys:
            return self
        cover = dict(self.coverage)
        rungs = []
        for rung in self.ladder:
            if rung.coverage_key in keys:
                level = source.level_for(rung.coverage_key)
                if level is None:
                    raise CoverageError(
                        f'{source.firm} has no level for '
                        f'{rung.coverage_key}; it cannot fill {self.firm}')
                rungs.append(replace(rung, level=level))
                cover[rung.coverage_key] = _filled(
                    cover[rung.coverage_key], source, rung.coverage_key)
            else:
                rungs.append(rung)
        caps = []
        for cap in self.caps:
            if cap.coverage_key in keys:
                level = source.level_for(cap.coverage_key)
                if level is None:
                    raise CoverageError(
                        f'{source.firm} has no level for {cap.coverage_key}; '
                        f'it cannot fill {self.firm}')
                caps.append(replace(cap, level=level))
                cover[cap.coverage_key] = _filled(
                    cover[cap.coverage_key], source, cap.coverage_key)
            else:
                caps.append(cap)
        return replace(self, ladder=tuple(rungs), caps=tuple(caps),
                       coverage=cover)

    # -- gap kind G18, in the one place it bites --------------------------

    @property
    def minimum_margin_factor(self) -> Decimal:
        """``MF`` per VN30 futures contract: **5,000d, always**.

        Research S-11 derives it and it is index-independent:
        ``MF = R x M x S`` with ``R = tick / 2S`` for a one-tick-wide book, so
        ``MF = tick x M / 2 = 0.1 x 100,000 / 2 = 5,000``. ``S`` cancels.
        TCBS corroborates it verbatim (*"Ky quy toi thieu VN30 = 5,000 d"*).

        **It is deliberately not read off any firm's page**, because SSI and
        SHS publish a number under the same phrase that is three orders of
        magnitude larger -- see :attr:`published_per_contract_requirement`.
        That number is the total per-contract requirement at that page's index
        level. A loader that maps it into ``MF`` makes ``MM = P x MF`` bind on
        every book and destroys ``MR = max(Rm + Sm - OA, MM)``.
        """
        return MINIMUM_MARGIN_FACTOR

    def parameters_for(self, underlying: str) -> UnderlyingParameters:
        """This firm's mirrored VSDC parameters for one underlying.

        Raises:
            CoverageError: when the firm publishes no parameter table, naming
                the profile that does. This refuses rather than falling back
                to PLUTUS_DEFAULT because a rate is not a policy choice we can
                synthesise a median of: ``Rm`` and ``Sm`` are VSDC's, they
                move, and the honest answer to *"what are TCBS's rates?"* is
                *"TCBS delegates them and we did not find the table"* -- gap
                kinds ``G1`` and ``G2`` together.
        """
        if self.vsdc_parameters is None:
            raise CoverageError(
                f'{self.firm} publishes no VSDC parameter mirror. Its rates '
                f'are delegated, illustrative, or absent. Use a profile that '
                f'publishes one -- SSI is the parameter feed of the survey '
                f'and SSI_2025_09 is its dated predecessor -- and note that '
                f'doing so means the numbers are SSI\'s, not {self.firm}\'s.')
        return self.vsdc_parameters.for_underlying(underlying)

    def implied_index_level(
        self, risk_rate: Decimal, spread_rate: Decimal,
        multiplier: Decimal = Decimal('100000'),
    ) -> Decimal:
        """The index level a published per-contract requirement implies.

        OURS, and it is the arithmetic that settles gap kind ``G18``: SSI's
        34,520,710 divided by ``(0.17 + 0.0087) x 100,000`` is **1931.8**, a
        plausible VN30 level. SHS's 22,309,440 over ``(0.17 + 0.0042) x
        100,000`` is **1280.7**, a plausible VN30 level of an earlier vintage.
        A policy constant would not track the index; these do, so they are
        dated snapshots.

        Raises:
            HomonymError: if this profile publishes no such number, rather
                than returning something derived from ``MF``.
        """
        if self.published_per_contract_requirement is None:
            raise HomonymError(
                f'{self.firm} publishes no per-contract requirement. Do not '
                f'substitute MF ({MINIMUM_MARGIN_FACTOR}) here: they are '
                'different quantities under one Vietnamese phrase -- gap kind '
                'G18.')
        rate = risk_rate + spread_rate
        if rate <= 0:
            raise ValueError('risk_rate + spread_rate must be positive')
        return self.published_per_contract_requirement / (rate * multiplier)

    # -- bridging to the existing BrokerTerms -----------------------------

    def to_broker_terms(self) -> BrokerTerms:
        """This profile as the legacy three-percentage object.

        Lossy **by construction**, and it refuses rather than lying where the
        loss would change behaviour:

        * a ``FALLING_COVERAGE`` profile has no utilisation ladder to project
          onto ``BrokerTerms``' three fields, and converting HSC would require
          the ``MR == IM`` versus ``MR == MM`` choice that gap kind ``G17``
          says is a modelling decision, not arithmetic;
        * a profile with a delegated level has no number to give.

        Everything the five axes added -- the denominator, fire-vs-target, the
        notice obligation, the model -- is dropped here. Use the profile
        itself wherever those matter.
        """
        if self.direction is not Direction.RISING_UTILISATION:
            raise CoverageError(
                f'{self.firm} runs a {self.direction.name} ratio. BrokerTerms '
                'holds three rising-utilisation percentages and there is no '
                'arithmetic that converts one to the other without choosing '
                'what this firm\'s MR is -- gap kind G17.')
        if len(self.ladder) < 3:
            raise CoverageError(
                f'{self.firm} publishes {len(self.ladder)} rungs; BrokerTerms '
                'needs three (warning, call, forced close)')
        levels = [r.level for r in self.ladder[:3]]
        if any(level is None for level in levels):
            raise CoverageError(
                f'{self.firm} delegates '
                f'{", ".join(self.blocking_fields())}; there is no number to '
                'put in BrokerTerms. Fill it deliberately first.')
        return BrokerTerms(
            warning_utilisation=levels[0],
            margin_call_utilisation=levels[1],
            forced_close_utilisation=levels[2],
            cure_window_sessions=_cure_sessions(self.ladder[1].cure),
        )

    # -- rendering --------------------------------------------------------

    def render_coverage(self) -> str:
        """The coverage table, with supplied fields marked unmissably."""
        lines = [f'{self.firm} -- coverage '
                 f'({"SYNTHESIS" if self.is_synthesis else "named firm"}, '
                 f'{self.regime.name})']
        for key in sorted(self.coverage):
            lines.append(f'  {key:28s} {self.coverage[key].render()}')
        return '\n'.join(lines)

    def __repr__(self) -> str:
        supplied = self.supplied_fields()
        mark = (f' SUPPLIED-BY-US={list(supplied)}' if supplied else '')
        return (f'<BrokerProfile {self.firm} {self.direction.name} '
                f'model={self.margin_model.name} '
                f'rungs={[str(r.level) for r in self.ladder]}{mark}>')

    def warn(self) -> Tuple[str, ...]:
        """Emit this profile's coverage warnings. Returns what was emitted.

        Fires at the point of **use**, not at import: a warning raised while
        this module is being imported carries a stacklevel pointing at our own
        code, which tells the caller nothing and cannot be filtered per call
        site. :func:`get_profile` calls this; so does :func:`assess`, once per
        profile object.

        A profile with no gaps emits nothing. That silence is load-bearing:
        it means fully sourced, never "we did not check".
        """
        emitted = []
        if self.is_synthesis:
            message = (
                f'{self.firm} is a SYNTHESIS, not a broker. It matches no '
                'firm exactly: numeric fields are the median of the '
                'normalised survey pool and categorical fields the modal '
                'value, so every number is one some real firm uses and the '
                'combination is nobody\'s. It is the default precisely so '
                'that a caller who chose no broker does not silently inherit '
                'one firm\'s commercial policy. Name a firm to get that '
                'firm\'s policy; read .render_coverage() for each field\'s '
                'derivation.')
            warnings.warn(message, SynthesisWarning, stacklevel=3)
            emitted.append(message)
        gaps = self.gaps()
        for severity in (Severity.MATERIAL, Severity.ADVISORY):
            selected = [g for g in gaps if g.severity is severity]
            if not selected:
                continue
            message = (
                f'{self.firm}: {len(selected)} {severity.name} coverage '
                f'gap(s) -- ' + '; '.join(g.describe() for g in selected)
                + (' | These change margin-call incidence: a result from this '
                   'profile is not purely this firm\'s policy.'
                   if severity is Severity.MATERIAL
                   else ' | These affect timing or reporting, not the number.')
            )
            warnings.warn(message, severity.warning_class, stacklevel=3)
            emitted.append(message)
        supplied = self.supplied_fields()
        if supplied:
            message = (
                f'{self.firm}: the following fields were SUPPLIED BY US and '
                f'are not {self.firm}\'s published values -- '
                f'{", ".join(supplied)}. Do not quote them against '
                f'{self.firm}\'s page.')
            warnings.warn(message, MaterialCoverageWarning, stacklevel=3)
            emitted.append(message)
        return tuple(emitted)


#: Alias, for any module that must import both this and
#: :class:`plutus.market.session.types.BrokerProfile`. Gap kind ``G18``,
#: occurring in our own code and registered rather than hidden.
MarginBrokerProfile = BrokerProfile


def _filled(cov: FieldCoverage, source: 'BrokerProfile',
            key: str) -> FieldCoverage:
    """One coverage record rewritten as supplied-by-us."""
    return FieldCoverage(
        status=Coverage.FILLED_FROM_DEFAULT,
        quantity=cov.quantity,
        source_class=SourceClass.OURS,
        filled_from=source.firm,
        derivation=source.coverage[key].derivation
        if key in source.coverage else None,
        gap=cov.gap,
        note=(f'SUPPLIED FROM {source.firm}. The firm delegates this value: '
              f'{cov.note or cov.quantity}'),
    )


def _cure_sessions(cure: CureSpec) -> int:
    """A cure spec as ``BrokerTerms``' session count. Conservative."""
    if cure.kind is CureKind.SESSIONS and cure.sessions is not None:
        return cure.sessions
    if cure.kind is CureKind.IMMEDIATE:
        return CureWindow.SAME_SESSION
    return CureWindow.NEXT_SESSION


# ---------------------------------------------------------------------------
# Constants that are exchange rules, not commercial terms
# ---------------------------------------------------------------------------

#: ``MF`` for a VN30 index future, derived in research S-11 and independent of
#: the index level. **Not** a broker term and **not** the number SSI and SHS
#: publish under the same Vietnamese phrase -- see
#: :attr:`BrokerProfile.minimum_margin_factor`.
MINIMUM_MARGIN_FACTOR = Decimal('5000')

#: Coverage keys that name the **same quantity** under different firms' words,
#: used only when a delegating profile is filled from another.
#:
#: MBS names a *"ty le sau mo vi the"* -- the ratio permitted after opening a
#: position -- which is the same quantity PLUTUS_DEFAULT calls the maximum
#: utilisation at which a new position may be opened. Crossing the two names is
#: a translation, not an inference. Anything that is *not* the same quantity is
#: deliberately absent here: gap kind ``G18`` is what happens when a mapping
#: like this is built out of labels instead of meanings.
LEVEL_ALIASES: Mapping[str, str] = MappingProxyType({
    'post_open_level': 'block_open_level',
    'maintenance_level': 'block_open_level',
    'safe_level': 'block_open_level',
    'normal_level': 'block_open_level',
})

#: VSDC's published initial margin ratio for index futures across the KRX era.
#: A broker's own ratio sits **at or above** it (research S-17), which
#: :meth:`BrokerProfile.__post_init__` enforces.
VSDC_INITIAL_MARGIN_RATIO = Decimal('0.17')


# ---------------------------------------------------------------------------
# Open questions -- surfaced, not resolved
# ---------------------------------------------------------------------------

#: Decisions this module could not make for the author, and what it did
#: meanwhile. Each says which of the author's own stated rules it applied, so
#: the fallback is traceable rather than invented.
OPEN_QUESTIONS: Mapping[str, str] = MappingProxyType({
    'Q1': (
        'F-1: no surveyed firm runs the scenario grid as its client-facing '
        'intraday number, and all ten firms that state a formula state '
        'IM+VM+DM. Does PLUTUS_DEFAULT carry BOTH models, or select one? '
        'MEANWHILE: both are carried, because the evidence carries both, and '
        'user_facing_model names the one the client is tested against '
        '(INTRADAY). That keeps the author\'s "ONE user-facing margin number" '
        'while not deleting a layer the sources demonstrably have.'
    ),
    'Q2': (
        'F-3 / gap kind G16: notification is modally REQUIRED (5 firms to 3), '
        'but every signed T&C in hand denies it and every help page promises '
        'it, so the modal count may be measuring which document we found. '
        'Adopt the modal, or weight by document class? MEANWHILE: the modal, '
        'per the author\'s own rule 3 for categorical fields, with SourceClass '
        'recorded on every notification coverage entry so a re-weighting is a '
        'query rather than a re-survey.'
    ),
    'Q3': (
        'Field 12, the target level: TargetRef.RUNG_1 (the modal structural '
        'reading, -> 80) or the absolute median of the published target '
        'numbers (-> 85)? MEANWHILE: RUNG_1, because no firm publishes an '
        'absolute target and every one publishes a reference to a named rung, '
        'so the target then moves coherently when a caller overrides rung 1. '
        'The 85 is recorded as Derivation.cross_check on the same field.'
    ),
    'Q4': (
        'Field 19, minimum cash share of margin assets: the median rule\'s own '
        'output is 100%, which is VCBS\'s number, and we ourselves marked VCBS '
        'self-contradictory (gap kind G14). Override to FPTS\'s 80%? '
        'MEANWHILE: 80%, on the same exclusion logic already applied to VCBS '
        'and ACBS in the ladder pools -- a source excluded as contradictory '
        'for one field cannot be the sole basis of another. Labelled n=1. '
        'Impact on a cash VN30F account is zero.'
    ),
    'Q5': (
        'broker.py\'s forced_close_utilisation = 1.00 is defended as '
        'reproducing QD 26 Dieu 13. Under the survey that is the CCP rung, '
        'not the broker rung: the broker fires first, at 95. Both must exist '
        'as distinct objects. MEANWHILE: this module models them separately '
        '(BrokerProfile.ladder against BrokerProfile.ccp_breach) and does NOT '
        'touch broker.py. Re-labelling the 1.00 there is the author\'s call.'
    ),
    'Q6': (
        'TCBS is shipped as the reference profile and SSI as the parameter '
        'feed, per the selection brief section 2: TCBS is the only firm whose '
        'model is complete enough to reproduce arithmetically, and SSI is the '
        'most recent and richest parameter table. Neither alone runs a margin '
        'call. Whether the two should be merged into one shipped profile is '
        'not decided here. MEANWHILE: they ship as separate profiles and '
        'TCBS\'s missing denominator stays missing. The split is now visible '
        'rather than described: TCBS.vsdc_parameters is None and '
        'SSI.margin_model_intraday is UNSTATED, so neither profile can be '
        'mistaken for the complete one.'
    ),
    'Q7': (
        'HSC states its remedy target twice over and the two disagree. Its '
        'rung table says restore to the "Ky quy duy tri" band, R >= 80%; its '
        '"Ky quy bo sung" definition (Muc ky quy ban dau - So du ky quy) and '
        'its "Xu ly cac tai khoan vi pham ky quy" clause both say restore to '
        '"trang thai Binh thuong", R >= 100%. On assets 70,000 against '
        'required 100,000 the two readings close 12,500 and 30,000 '
        'respectively -- two and a half times apart, which makes this a '
        'margin-call-incidence question and not a wording question. Two of '
        'the three sentences say 100 and only the table says 80. MEANWHILE: '
        'the table is operative, because it is the only clause that assigns '
        'actions to bands at all, and the disagreement is recorded as a '
        'source defect on HSC\'s "target" field with the arithmetic in it. '
        'HSC is not the default and its page is pre-KRX, so nothing else '
        'rests on the choice. The author\'s call.'
    ),
})


# ---------------------------------------------------------------------------
# The shipped profiles
# ---------------------------------------------------------------------------
#
# Everything below is data, and it is data of a particular kind: each value is
# accompanied by where it came from and by what it is not. Read the coverage,
# not just the number.
#
# The evidence base is the broker survey of 2026-08-26: fourteen firms with
# retrievable evidence, read from snapshots held in the session scratchpad.
# Where a firm's page carries no URL in the snapshot the ``source_url`` is
# ``None`` and the snapshot filename is in ``note`` -- claiming a URL we did
# not record would be exactly the overclaiming the house rules forbid.

#: The day the survey snapshots were read. Distinct from every firm's own
#: ``effective_from``, and deliberately so.
FETCHED = date(2026, 8, 26)


def _c(status: Coverage, quantity: str, source_class: SourceClass, *,
       url: Optional[str] = None, eff: Optional[date] = None,
       quote: Optional[str] = None, gap: Optional[GapKind] = None,
       note: str = '', deriv: Optional[Derivation] = None,
       defect: Optional[str] = None) -> FieldCoverage:
    """One coverage record, with ``fetched_on`` filled from the survey date."""
    return FieldCoverage(
        status=status, quantity=quantity, source_class=source_class,
        source_url=url, effective_from=eff, fetched_on=FETCHED, quote=quote,
        gap=gap, note=note, derivation=deriv, source_defect=defect)


#: The fields whose PLUTUS_DEFAULT value is a **number** and therefore must
#: carry a :class:`Derivation`. The author's rule 4, made checkable.
NUMERIC_FIELDS: frozenset = frozenset({
    'block_open_level', 'margin_call_level', 'forced_close_level',
    'post_withdrawal_level', 'initial_margin_ratio',
    'late_payment_rate', 'minimum_cash_share',
})

_IMMEDIATE = CureSpec(CureKind.IMMEDIATE)
_UNKNOWN_CURE = CureSpec(CureKind.UNKNOWN)
_NEXT_SESSION = CureSpec(CureKind.SESSIONS, sessions=CureWindow.NEXT_SESSION)

_VKQ_IGNORED = DenominatorSpec(
    basis=DenominatorBasis.V_KQ,
    liabilities=LiabilitiesTreatment.IGNORED,
    securities_cap_fraction=Decimal('0.20'),
    note='QD 26 Dieu 8: cash + securities at VSD haircuts, capped at '
         '(1 - 0.80) x MR, no liabilities subtracted')


# -- PLUTUS_DEFAULT ---------------------------------------------------------

def _plutus_default() -> BrokerProfile:
    """The synthesis. Every number is one some real firm actually applies.

    Derived under the author's four rules: normalise to rising utilisation
    first (so SSI's 85/90/95 and HSC's 100/80/60 are not compared unconverted,
    which would measure the convention rather than the policy); numeric fields
    take the **median** of the normalised pool, the more conservative central
    value on an even count, never a split difference; categorical fields take
    the **modal** value; and every derived value records the rule, the source
    firms by name, and ``n``.

    Two firms are excluded from the numeric pools with reasons, not silently:
    HSC (gap kind ``G17`` -- its coverage ratio converts two incompatible
    ways) and VCBS/ACBS (no ladder exists at all).

    The resulting ladder is **80 / 90 / 95, targeting 80, withdrawal at or
    below 80**, and two things about it are worth saying out loud. Every rung
    is a real firm's number: 80 is FPTS, VNDIRECT and Pinetree; 90 is five
    firms; 95 is SSI, Vietcap and Pinetree. And the top rung is 95, not 100 --
    the broker fires **before** the CCP breach at 1.00, which is
    :class:`CcpBreachTest` and a separate object.
    """
    ladder = (
        Rung(coverage_key='block_open_level',
             name='Muc 1 -- toi da de duoc mo vi the moi',
             level=Decimal('0.80'), action=Action.BLOCK_OPENING,
             target_ref=TargetRef.NONE, notice=Notice.UNKNOWN,
             cure=_UNKNOWN_CURE),
        Rung(coverage_key='margin_call_level',
             name='Muc 2 -- goi ky quy bo sung',
             level=Decimal('0.90'), action=Action.NOTIFY,
             target_ref=TargetRef.RUNG_1, notice=Notice.REQUIRED,
             cure=_NEXT_SESSION),
        Rung(coverage_key='forced_close_level',
             name='Muc 3 -- xu ly, dong vi the bat buoc',
             level=Decimal('0.95'), action=Action.LIQUIDATE,
             target_ref=TargetRef.RUNG_1, notice=Notice.UNKNOWN,
             cure=_IMMEDIATE),
    )
    caps = (
        Cap(coverage_key='post_withdrawal_level',
            name='Ty le sau khi rut tien',
            level=Decimal('0.80'),
            description='a withdrawal is permitted only if the ratio after it '
                        'is at or below this level'),
    )
    coverage = {
        'direction': _c(
            Coverage.INFERRED, 'sign convention of the ladder ratio',
            SourceClass.OURS,
            deriv=Derivation(
                rule='modal', n=11,
                sources=('SSI', 'TCBS', 'SHS', 'Vietcap', 'FPTS', 'VNDIRECT',
                         'Pinetree', 'MBS', 'KIS', 'VPS', 'VCBS'),
                excluded=('HSC (falling coverage; ships as its own profile)',),
                note='VPS taken from its Part E section 4.4(c) rather than '
                     'its section 1.13, which contradicts it -- gap kind G14'),
            note='11 of 12 firms with a direction run rising utilisation'),
        'denominator': _c(
            Coverage.INFERRED, 'composition of the divisor', SourceClass.OURS,
            deriv=Derivation(
                rule='modal', n=7,
                sources=('SHS', 'Vietcap', 'FPTS', 'VNDIRECT', 'MBS', 'KIS',
                         'VPS'),
                cross_check='the conservative alternative is NET assets, used '
                            'by 2 named firms (VNDIRECT, FPTS) -- recorded, '
                            'not adopted'),
            gap=GapKind.G4_DENOMINATOR_DIVERGENT,
            note='V_KQ per QD 26 Dieu 8'),
        'liabilities_treatment': _c(
            Coverage.INFERRED, 'where client debts enter the ratio',
            SourceClass.OURS,
            deriv=Derivation(
                rule='modal', n=6,
                sources=('MBS', 'KIS', 'VPS'),
                cross_check='FPTS and VNDIRECT subtract from assets; SHS adds '
                            'to the numerator. Both minority conventions raise '
                            'utilisation and cannot be merged'),
            gap=GapKind.G4_DENOMINATOR_DIVERGENT,
            note='IGNORED, 3 of 6'),
        'margin_model_intraday': _c(
            Coverage.INFERRED, 'formula for the client-facing MR',
            SourceClass.OURS,
            deriv=Derivation(
                rule='modal', n=8,
                sources=('MBS', 'VNDIRECT', 'KIS', 'VPS', 'FPTS', 'SHS',
                         'Vietcap'),
                excluded=('HSC (IM with MM = 0.8 x IM -- in the pool, not in '
                          'the modal value)',),
                note='unanimous among the firms that state a model at all; '
                     'zero firms state the scenario grid for this quantity'),
            note='MR = IM + VM + DM + other obligations'),
        'margin_model_overnight': _c(
            Coverage.INFERRED, 'formula for the CCP submission',
            SourceClass.OURS,
            deriv=Derivation(
                rule='modal', n=4,
                sources=('TCBS', 'SSI', 'SHS', 'FPTS'),
                note='unanimous; TCBS is the only firm that assembles it '
                     'completely, and it heads the block "so tien ky quy ma '
                     'TCBS can phai nop cuoi ngay"'),
            note='Max(Rm + Sm + Dm - OA, MM), QD 26 Phu luc 2'),
        'initial_margin_ratio': _c(
            Coverage.INFERRED, 'the broker\'s own initial margin ratio',
            SourceClass.OURS,
            deriv=Derivation(
                rule='median', n=5,
                sources=('HSC', 'VNDIRECT', 'FPTS', 'DNSE', 'Vietcap'),
                cross_check='pool 17.00 / 17.50 / 17.85 / 18.48 / 20.00; the '
                            'median 17.85 is FPTS\'s actual number, and it is '
                            'at or above VSDC\'s 17% per research S-17',
                note='the branch own-vs-delegated is itself modal: 5 firms '
                     'set their own ratio, 4 delegate to VSDC'),
            note='17.85%'),
        'block_open_level': _c(
            Coverage.INFERRED, 'max utilisation at which a new position opens',
            SourceClass.OURS,
            deriv=Derivation(
                rule='median', n=6,
                sources=('FPTS', 'VNDIRECT', 'Pinetree'),
                cross_check='pool 75 / 80 / 80 / 80 / 85 / 85; even count, '
                            'both central values are 80',
                note='SSI 85, TCBS 85, SHS 75 complete the pool; Vietcap does '
                     'not publish its level 1'),
            note='80%'),
        'margin_call_level': _c(
            Coverage.INFERRED, 'utilisation at which the firm calls',
            SourceClass.OURS,
            deriv=Derivation(
                rule='median', n=7,
                sources=('SSI', 'Vietcap', 'FPTS', 'VNDIRECT', 'Pinetree'),
                cross_check='pool 85 / 87 / 90 / 90 / 90 / 90 / 90',
                note='TCBS 87 and SHS 85 are the two below the median'),
            note='90%'),
        'forced_close_level': _c(
            Coverage.INFERRED, 'utilisation at which the firm closes for you',
            SourceClass.OURS,
            deriv=Derivation(
                rule='median', n=7,
                sources=('SSI', 'Vietcap', 'Pinetree'),
                cross_check='pool 90 / 90 / 95 / 95 / 95 / 100 / 100',
                note='this is the BROKER rung. The CCP rung is 1.00 and is a '
                     'separate object -- see CcpBreachTest'),
            note='95%'),
        'target': _c(
            Coverage.INFERRED, 'the level a forced close restores the ratio to',
            SourceClass.OURS,
            deriv=Derivation(
                rule='modal', n=5,
                sources=('SSI', 'TCBS', 'Pinetree'),
                cross_check='the median of the five published target NUMBERS '
                            'is 85; the modal structural relation is '
                            'target = rung 1, which is 80',
                note='no firm publishes an absolute target: every one '
                     'publishes a reference to a named rung, so the target '
                     'moves when rung 1 is overridden. SHS targets rung 2; '
                     'Vietcap is unresolvable. See OPEN_QUESTIONS Q3'),
            note='target_ref = RUNG_1, hence 80%'),
        'notification': _c(
            Coverage.INFERRED, 'whether a notice is owed before action',
            SourceClass.OURS,
            deriv=Derivation(
                rule='modal', n=8,
                sources=('SSI', 'TCBS', 'Vietcap', 'HSC', 'FPTS'),
                cross_check='5 duty against 3 denied -- but the split is by '
                            'document class, not by firm policy: every firm '
                            'promising a notice does so on a help page, and '
                            'every signed T&C we hold denies it',
                note='gap kind G16. See OPEN_QUESTIONS Q2'),
            gap=GapKind.G16_SOURCE_CLASS_WEAK,
            note='REQUIRED'),
        'cure_window': _c(
            Coverage.INFERRED, 'time allowed to answer a call',
            SourceClass.OURS,
            deriv=Derivation(
                rule='sole source', n=1, sources=('HSC',),
                cross_check='TCBS publishes 15:30 T, but on its VSDC-breach '
                            'path, which is a different event; the two are '
                            'incomparable',
                note='HSC\'s 11:30 T+1 is from a page dated 2020-04-15, five '
                     'years pre-KRX'),
            gap=GapKind.G13_PRE_KRX_DOCUMENT,
            note='CureWindow.NEXT_SESSION retained; at the top rung the modal '
                 'answer is immediate, 7 of 8'),
        'post_withdrawal_level': _c(
            Coverage.INFERRED, 'max utilisation permitted after a withdrawal',
            SourceClass.OURS,
            deriv=Derivation(rule='sole source', n=1, sources=('TCBS',)),
            note='80%'),
        'vm_settlement_deadline': _c(
            Coverage.INFERRED, 'when the client must pay the variation margin',
            SourceClass.OURS,
            deriv=Derivation(
                rule='sole source', n=1, sources=('TCBS',),
                cross_check='distinct from the regulated 09h30 T+1 top-up, '
                            'which runs member-to-VSDC (QD 26 Dieu 13.1)'),
            note='08:00 T+1'),
        'late_payment_rate': _c(
            Coverage.INFERRED, 'annual interest on a late margin payment',
            SourceClass.OURS,
            deriv=Derivation(
                rule='sole source', n=1, sources=('TCBS',),
                cross_check='Pinetree publishes a formula (150% x margin '
                            'rate) rather than a rate, so it cannot be pooled'),
            note='11.5%/yr'),
        'minimum_cash_share': _c(
            Coverage.INFERRED, 'minimum cash share of margin assets',
            SourceClass.OURS,
            deriv=Derivation(
                rule='sole source', n=1, sources=('FPTS',),
                cross_check='the median rule\'s own output on n=2 is VCBS\'s '
                            '100%, and we marked VCBS self-contradictory (gap '
                            'kind G14); a source excluded as contradictory '
                            'cannot be the sole basis of another field. See '
                            'OPEN_QUESTIONS Q4. Impact on a cash VN30F '
                            'account: zero'),
            note='80%'),
        'minimum_margin_factor': _c(
            Coverage.INFERRED, 'MF -- minimum margin per VN30 contract',
            SourceClass.OURS,
            gap=GapKind.G18_HOMONYM,
            note='5,000d, derived in research S-11 (MF = tick x M / 2) and '
                 'index-independent; corroborated verbatim by TCBS. NOT the '
                 'number SSI and SHS publish under the same phrase'),
    }
    return BrokerProfile(
        firm='PLUTUS_DEFAULT',
        is_synthesis=True,
        regime=Regime.POST_KRX,
        document_date=FETCHED,
        margin_model_intraday=MarginModel.IM_PLUS_VM_PLUS_DM,
        margin_model_overnight=MarginModel.SCENARIO_GRID,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=_VKQ_IGNORED,
        ladder=ladder,
        caps=caps,
        coverage=coverage,
        initial_margin_ratio=Decimal('0.1785'),
        vm_settlement_deadline='08:00 T+1',
        late_payment_annual_rate=Decimal('0.115'),
        minimum_cash_share=Decimal('0.80'),
        description='A synthesis of the 2026-08-26 fourteen-firm survey. '
                    'Matches no firm exactly and warns that it does not.',
    )


# -- TCBS: the reference profile --------------------------------------------

_TCBS_URL = 'https://help.tcbs.com.vn/chinh-sach-ck-phai-sinh-voi-hdtl-chi-so-co-phieu/'


def _tcbs() -> BrokerProfile:
    """TCBS -- the profile the coverage vocabulary is designed against.

    **Not the default.** PLUTUS_DEFAULT is the default. TCBS is the reference
    because it is the only surveyed firm whose model is stated completely
    enough to be **reproduced arithmetically**: research S-12 checks its
    ``Rm = 30,177,000`` exactly and S-11 checks its ``MF = 5,000d``. SSI wins
    recency and the parameter set outright and loses on the one field the
    governing architecture makes definitional -- SSI never states a model at
    all.

    **What TCBS does not cover, stated as flatly as it deserves:**

    1. **Its denominator. At all.** *"Ty le su dung tai san"* is published
       with rungs, deadlines and a support facility and **no formula, no
       divisor, no liability treatment**. Alone among the seven
       number-publishing firms it does not even *name* the divisor.
    2. **The numerator of the ladder ratio.** The model it publishes is
       scoped to the overnight VSDC submission -- *"so tien ky quy ma TCBS can
       phai nop cuoi ngay khi KH mo vi the qua dem"*. The intraday number the
       85/87/90 fires on is undefined. Gap kind ``G11``, and the single most
       instructive gap in the survey.
    3. **Its real Rm/Sm rates.** The 3% / 1% are illustrative (S-13).
    4. **Its IM ratio.** Delegated: *"17% -- Theo quy dinh tai VSD"*.
    5. **The VSDC parameter mirror.** No Psr, no scale factors, no position
       limits of its own. SSI supplies all of these; ship the two together.
    6. **Its nominal date is 2025-04-24, eleven days before the KRX
       cutover.** The content is demonstrably refreshed -- it cites contract
       code 41I1G6000 (June 2026) and a per-contract requirement consistent
       with SSI's January 2026 parameters -- but the stamp is pre-regime.
    """
    ladder = (
        Rung(coverage_key='maintenance_level', name='Ty le duy tri',
             level=Decimal('0.85'), action=Action.BLOCK_OPENING,
             target_ref=TargetRef.NONE, notice=Notice.UNKNOWN,
             cure=_UNKNOWN_CURE),
        Rung(coverage_key='margin_call_level', name='Ty le canh bao',
             level=Decimal('0.87'), action=Action.NOTIFY,
             target_ref=TargetRef.RUNG_1, notice=Notice.REQUIRED,
             cure=CureSpec(CureKind.DEADLINE,
                           deadline='VM by 08:00 T+1; on the VSDC-breach path '
                                    'the top-up is due 15:30 T')),
        Rung(coverage_key='forced_close_level', name='Ty le xu ly',
             level=Decimal('0.90'), action=Action.LIQUIDATE,
             target_ref=TargetRef.RUNG_1, notice=Notice.REQUIRED,
             cure=_IMMEDIATE),
    )
    caps = (
        Cap(coverage_key='post_withdrawal_level', name='Ty le sau khi rut',
            level=Decimal('0.80'),
            description='withdrawal permitted only if the post-withdrawal '
                        'ratio is at or below 80%'),
    )
    cov = {
        'direction': _c(Coverage.PUBLISHED, 'sign of the ladder ratio',
                        SourceClass.HELP_PAGE, url=_TCBS_URL,
                        eff=date(2025, 4, 24)),
        'denominator': _c(
            Coverage.UNPUBLISHED, 'divisor of "Ty le su dung tai san"',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            gap=GapKind.G3_DENOMINATOR_UNDEFINED,
            note='TCBS publishes the ratio with rungs, deadlines and a '
                 'support facility and never names the divisor -- alone among '
                 'the seven number-publishing firms'),
        'liabilities_treatment': _c(
            Coverage.UNPUBLISHED, 'where client debts enter the ratio',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            gap=GapKind.G3_DENOMINATOR_UNDEFINED),
        'margin_model_intraday': _c(
            Coverage.UNPUBLISHED, 'formula behind the ladder numerator',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            gap=GapKind.G11_MODEL_SPLIT_UNRESOLVED,
            note='TCBS states a complete model and scopes it to the overnight '
                 'VSDC submission; the intraday number its 85/87/90 fires on '
                 'is never defined. Research conflict C-1, inside one firm'),
        'margin_model_overnight': _c(
            Coverage.PUBLISHED, 'Max(Rm + Sm + Dm + FSP - OA, MM)',
            SourceClass.HELP_PAGE, url=_TCBS_URL, eff=date(2025, 4, 24),
            quote='Giá trị ký quỹ yêu cầu (MR yêu cầu) ... Là số tiền ký quỹ '
                  'mà TCBS cần phải nộp cuối ngày khi KH mở vị thế qua đêm',
            note='the only firm in the survey that publishes the full '
                 'assembly plus a worked example'),
        'initial_margin_ratio': _c(
            Coverage.DELEGATED, 'the broker initial margin ratio',
            SourceClass.HELP_PAGE, url=_TCBS_URL, gap=GapKind.G1_DELEGATED,
            quote='17% - Theo quy định tại VSD',
            note='TCBS is on the delegating side of the research S-17 split; '
                 'it publishes no uplift of its own'),
        'maintenance_level': _c(
            Coverage.PUBLISHED, 'Ty le duy tri, 85%',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            quote='Là tỷ lệ được giao dịch tối đa khi mở mới vị thế',
            note='TCBS DOES publish an action here, and it is not a warning: '
                 '85% is the maximum ratio at which a new position may be '
                 'opened, so the rung blocks opening. It is also the target '
                 'both higher rungs restore to, which is why the same number '
                 'appears twice'),
        'margin_call_level': _c(
            Coverage.PUBLISHED, 'Ty le canh bao, 87%',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            quote='Khi Tỷ lệ sử dụng tài sản của tài khoản lớn hơn Tỷ lệ cảnh '
                  'báo và nhỏ hơn Tỷ lệ xử lý, Khách hàng cần bổ sung tài sản '
                  'để đưa Tỷ lệ sử dụng tài sản của tài khoản về Tỷ lệ duy trì',
            note='an OPEN interval, "> 87 and < 90". At exactly 87.00 TCBS '
                 'does not act and this module does -- conservative by one '
                 'boundary, and recorded rather than presented as TCBS\'s '
                 'wording'),
        'forced_close_level': _c(
            Coverage.PUBLISHED, 'Ty le xu ly, 90%',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            quote='Khi Tỷ lệ sử dụng tài sản của tài khoản lớn hơn hoặc bằng '
                  'Tỷ lệ xử lý, TCBS sẽ tự động đóng vị thế bắt buộc để đưa '
                  'Tỷ lệ sử dụng tài sản về Tỷ lệ duy trì',
            note='"lon hon hoac bang" -- inclusive here, unlike the 87 rung'),
        'position_limits': _c(
            Coverage.PUBLISHED, 'max contracts per account, by investor class',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            quote='Theo quy định tại VSD',
            note='5,000 / 10,000 / 20,000 -- the identical triple SSI prints, '
                 'and TCBS attributes it to VSD in the same cell. An EXCHANGE '
                 'rule restated, not a term TCBS chose'),
        'support_disbursement': _c(
            Coverage.PUBLISHED, 'the fifth path: cash advanced to reach 95%',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            quote='TCBS hỗ trợ giải ngân tiền mặt vào tài khoản vi phạm để '
                  'đưa Tỷ lệ sử dụng tài sản về 95%',
            note='priced at 10.5%/yr ("Phi giai ngan ho tro"), a SECOND rate '
                 'distinct from the 11.5% VM late-payment rate. This path '
                 'runs only after a VSDC level-3 breach and only if the '
                 'client misses the 15:30 T top-up; TCBS closes on T+1. A '
                 'model that treated the VSDC breach as immediate liquidation '
                 'would over-state forced selling at TCBS by a whole session'),
        'post_withdrawal_level': _c(
            Coverage.PUBLISHED, 'max utilisation after a withdrawal, 80%',
            SourceClass.HELP_PAGE, url=_TCBS_URL),
        'target': _c(
            Coverage.PUBLISHED, 'the rung a forced close restores to',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            quote='để đưa Tỷ lệ sử dụng tài sản về Tỷ lệ duy trì',
            note='both 87 and 90 target the maintenance rung, 85. A fifth '
                 'path disburses support to 95 after a VSDC breach, before '
                 'any close-out'),
        'notification': _c(
            Coverage.PUBLISHED, 'duty to notify before acting',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            gap=GapKind.G16_SOURCE_CLASS_WEAK,
            note='a help page, not a signed contract; TCBS\'s own T&C is not '
                 'in the corpus'),
        'cure_window': _c(
            Coverage.PUBLISHED, 'deadlines to cure',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            quote='Thời hạn thanh toán nghĩa vụ VM lỗ ngày T 8h ngày T+1',
            note='VM by 08:00 T+1 -- the only published client VM deadline in '
                 'the pool, and distinct from the regulated 09h30 T+1 '
                 'member-to-VSDC top-up. VSDC-breach top-up by 15:30 T. TCBS '
                 'also publishes the REMEDY ORDER on the VM path -- "TCBS se '
                 'rut tien ky quy tu VSD va/hoac dong vi the bat buoc": '
                 'collateral is pulled back before positions are closed, the '
                 'same shape SSI publishes at its Muc 3'),
        # Deliberately the same coverage key SSI uses. It is the same
        # quantity -- the firm's mirror of VSDC's parameter table -- and
        # giving one firm's copy of a quantity a different key from another's
        # is gap kind G18 committed in our own register.
        'vsdc_parameters': _c(
            Coverage.PUBLISHED_ILLUSTRATIVE, 'Rm 3% / Sm 1%',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            gap=GapKind.G2_PUBLISHED_ILLUSTRATIVE,
            quote='Tỷ lệ ký quỹ rủi ro: VN30 = 3%',
            note='teaching-example rates, not operative ones (research S-13): '
                 'they appear inside a worked example dated 03/04/2024 with '
                 'VN30 = 1005.9, and TCBS\'s operative rates are delegated to '
                 '"bang VSD cung cap" and were never located. Against SSI\'s '
                 'mirror the gap is enormous -- Sm 1% against 0.87% is close, '
                 'but Rm 3% against 17% is not. This entry passes any naive '
                 '"is there a number?" test, which is what makes it the most '
                 'dangerous kind in the register, and it is why '
                 'TCBS.vsdc_parameters is None: a profile must not be able to '
                 'hand these out as rates'),
        'minimum_margin_factor': _c(
            Coverage.PUBLISHED, 'MF -- minimum margin per VN30 contract',
            SourceClass.HELP_PAGE, url=_TCBS_URL,
            quote='Ký quỹ tối thiểu VN30 = 5,000 đ',
            note='TCBS is the firm that publishes the real MF; research S-11 '
                 'derives the same 5,000 from tick x M / 2 and proves it '
                 'index-independent'),
    }
    return BrokerProfile(
        firm='TCBS', is_synthesis=False, regime=Regime.PRE_KRX,
        document_date=date(2025, 4, 24),
        margin_model_intraday=MarginModel.UNSTATED,
        margin_model_overnight=MarginModel.SCENARIO_GRID,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(DenominatorBasis.UNPUBLISHED,
                                    LiabilitiesTreatment.UNPUBLISHED),
        ladder=ladder, caps=caps, coverage=cov,
        initial_margin_ratio=None,
        vm_settlement_deadline='08:00 T+1',
        late_payment_annual_rate=Decimal('0.115'),
        support_disbursement_annual_rate=Decimal('0.105'),
        description='The reference profile: the only firm whose model can be '
                    'reproduced arithmetically, and whose denominator is '
                    'entirely absent.',
    )


# -- SSI: the parameter feed ------------------------------------------------

_SSI_URL = ('https://www.ssi.com.vn/khach-hang-ca-nhan/'
            'thong-so-quan-ly-tai-khoan-giao-dich-chung-khoan-phai-sinh')
_SSI_OLD_URL = _SSI_URL + '-old'


def _ssi_parameters(*, vintage_2025_09: bool = False) -> VsdcParameterSet:
    """SSI's mirror of VSDC's table -- the reason SSI is the parameter feed.

    Section A of SSI's schedule, transcribed row for row. Every value here is
    an input to the scenario grid and to nothing else, which is what makes
    SSI's ``margin_model_overnight`` an inference from its own page rather
    than a guess: no other model consumes ``Psr`` or a size-correlation
    factor.

    **The two vintages disagree about more than the ladder**, and that is the
    point of keeping both:

    ====================  ==================  ==================
    row                   2025-09-11          2026-01-16
    ====================  ==================  ==================
    Ty le ky quy rui ro   17%                 17%
    Ty le ky quy song     **17%**             0.87% (VN30)
    Psr                   1                   0.85
    per-contract          31,711,460          34,520,710
    ====================  ==================  ==================

    The ``Sm = 17%`` of the older page is **arithmetically impossible against
    its own next row** and is recorded as such, not silently corrected: see
    the ``vsdc_parameters`` coverage entry, which carries the division that
    kills it.

    Source: SSI, *Thong so quan ly tai khoan giao dich chung khoan phai sinh*,
    section A (``brk/ssi_thongso.txt`` and ``brk/ssi_thongso_old.txt`` in the
    survey scratchpad).
    """
    limits = PositionLimits(individual=5000, institutional=10000,
                            professional=20000)
    if vintage_2025_09:
        return VsdcParameterSet(
            effective_from=date(2025, 9, 11),
            position_limits=limits,
            source=_SSI_OLD_URL,
            underlyings=(
                UnderlyingParameters(
                    underlying='VN30',
                    risk_margin_rate=Decimal('0.17'),
                    spread_margin_rate=Decimal('0.17'),
                    price_scan_range=Decimal('1'),
                    scale_factor=Decimal('1'),
                    minimum_per_contract_requirement=Decimal('31711460'),
                    note='Sm = 17% is self-evidently a placeholder: it equals '
                         'Rm to the digit, and against this row\'s own '
                         'per-contract figure it implies an index level of '
                         '932.7, roughly half the VN30 of September 2025'),
            ))
    return VsdcParameterSet(
        effective_from=date(2026, 1, 16),
        position_limits=limits,
        source=_SSI_URL,
        underlyings=(
            UnderlyingParameters(
                underlying='VN30',
                risk_margin_rate=Decimal('0.17'),
                spread_margin_rate=Decimal('0.0087'),
                price_scan_range=Decimal('0.85'),
                scale_factor=Decimal('1'),
                minimum_per_contract_requirement=Decimal('34520710')),
            UnderlyingParameters(
                underlying='VN100',
                risk_margin_rate=Decimal('0.17'),
                spread_margin_rate=Decimal('0.0117'),
                price_scan_range=Decimal('0.85'),
                scale_factor=Decimal('1.03'),
                minimum_per_contract_requirement=Decimal('32606000'),
                note='the scale factor is 1.03 here and 1 for VN30 -- the one '
                     'row where the two index contracts differ structurally '
                     'rather than only in rate'),
        ))


def _ssi(*, foreign: bool = False,
         vintage_2025_09: bool = False) -> BrokerProfile:
    """SSI -- the richest parameter set in the pool, and no model at all.

    SSI publishes ``Rm 17%``, ``Sm 0.87%`` / ``1.17%``, ``Psr 0.85``, scale
    factors ``1 / 1.03``, per-contract requirements, position limits, GB
    futures terms and a **separate foreign-investor ladder** -- and **no MR
    formula anywhere on the page**. That is gap kind ``G10`` and it is the
    reason SSI is the parameter feed rather than the reference profile: a
    reader can and will mistake *"Ty le ky quy rui ro 17%"* for an IM ratio in
    an ``IM + VM`` model, which is exactly the research conflict C-1 confusion
    this design exists to prevent. So :attr:`BrokerProfile.initial_margin_ratio`
    is deliberately ``None`` here, not ``0.17``.

    SSI is also the only firm with a **datable version history**, and both of
    its vintages ship: ``SSI`` (effective 2026-01-16, 85/90/95) and
    ``SSI_2025_09`` (effective 2025-09-11, 80/85/90). Both dates are SSI's own
    words -- *"Ngay hieu luc: Tu 16/01/2026"* and *"Tu 11/09/2025"* -- so the
    loosening is the one policy change in the whole survey we can put a date
    on. Pinetree's two vintages exist and **nothing dates the change**; SSI's
    do and something does. Keeping both distinguishes those two situations.

    Its **foreign-investor ladder did not move**: 75/80/85 on both pages, while
    the domestic one rose by five points. A profile that carried only the
    current numbers would lose that, and it is the single cleanest piece of
    evidence that the foreign ladder is a separate policy rather than a
    derived offset of the domestic one.

    SSI publishes a **remedy ordering** -- *"tu dong dieu chuyen tien ...
    va/hoac thuc hien dong vi the bat buoc"*, collateral transfer before
    liquidation, which is :attr:`Rung.follow_on`. TCBS publishes one too, on
    its VM path; SSI's is the only one attached to a ladder rung.

    ``published_per_contract_requirement`` is 34,520,710d for VN30 and is
    **not** ``MF``. See gap kind ``G18``,
    :meth:`BrokerProfile.implied_index_level`, and
    :attr:`UnderlyingParameters.implied_index_level`, which runs the same
    division against SSI's **own** rates rather than rates a caller supplies.
    """
    if foreign:
        levels = (Decimal('0.75'), Decimal('0.80'), Decimal('0.85'))
    elif vintage_2025_09:
        levels = (Decimal('0.80'), Decimal('0.85'), Decimal('0.90'))
    else:
        levels = (Decimal('0.85'), Decimal('0.90'), Decimal('0.95'))
    who = ('SSI_2025_09' if vintage_2025_09
           else 'SSI_FOREIGN' if foreign else 'SSI')
    effective = date(2025, 9, 11) if vintage_2025_09 else date(2026, 1, 16)
    ladder = (
        Rung(coverage_key='block_open_level', name='Muc 1', level=levels[0],
             action=Action.BLOCK_OPENING, target_ref=TargetRef.NONE,
             notice=Notice.UNKNOWN, cure=_UNKNOWN_CURE),
        Rung(coverage_key='margin_call_level', name='Muc 2', level=levels[1],
             action=Action.NOTIFY, target_ref=TargetRef.RUNG_1,
             notice=Notice.REQUIRED, cure=_UNKNOWN_CURE),
        Rung(coverage_key='forced_close_level', name='Muc 3', level=levels[2],
             action=Action.TRANSFER_COLLATERAL, follow_on=Action.LIQUIDATE,
             target_ref=TargetRef.RUNG_1, notice=Notice.UNKNOWN,
             cure=_IMMEDIATE),
    )
    url = _SSI_OLD_URL if vintage_2025_09 else _SSI_URL
    params = _ssi_parameters(vintage_2025_09=vintage_2025_09)
    src = (f'SSI schedule section C, effective {effective}; snapshot '
           f'brk/ssi_thongso{"_old" if vintage_2025_09 else ""}.txt')
    cov = {
        'direction': _c(Coverage.PUBLISHED, 'sign of the ladder ratio',
                        SourceClass.PUBLISHED_SCHEDULE, url=url,
                        eff=effective, note=src),
        'denominator': _c(
            Coverage.UNPUBLISHED, 'divisor, named but not composed',
            SourceClass.PUBLISHED_SCHEDULE, url=url, eff=effective,
            gap=GapKind.G3_DENOMINATOR_UNDEFINED,
            quote='tổng giá trị tài sản ký quỹ hợp lệ',
            note='named -- SSI calls Muc 1 "Ty le giao dich toi da tren tong '
                 'gia tri tai san ky quy hop le", so the divisor has a name '
                 'and one line of description. Composition, securities cap '
                 'and haircuts are all absent. ' + src),
        'liabilities_treatment': _c(
            Coverage.UNPUBLISHED, 'where client debts enter the ratio',
            SourceClass.PUBLISHED_SCHEDULE, url=url,
            gap=GapKind.G3_DENOMINATOR_UNDEFINED, note=src),
        'margin_model_intraday': _c(
            Coverage.UNPUBLISHED, 'formula behind the ladder numerator',
            SourceClass.PUBLISHED_SCHEDULE, url=url,
            gap=GapKind.G10_MODEL_NOT_STATED,
            note='no MR formula appears anywhere on the page. A reader will '
                 'mistake "Ty le ky quy rui ro 17%" for an IM ratio; it is '
                 'the risk-margin rate of the scenario grid. ' + src),
        'margin_model_overnight': _c(
            Coverage.INFERRED, 'the model SSI\'s parameters belong to',
            SourceClass.OURS, gap=GapKind.G10_MODEL_NOT_STATED,
            note='OURS: Rm, Sm, Psr and the scale factors are scenario-grid '
                 'inputs and nothing else\'s, so the parameters identify the '
                 'model even though SSI never writes the assembly down'),
        'initial_margin_ratio': _c(
            Coverage.UNPUBLISHED, 'the broker initial margin ratio',
            SourceClass.PUBLISHED_SCHEDULE, url=url,
            gap=GapKind.G10_MODEL_NOT_STATED,
            note='deliberately NOT 0.17. The 17% on SSI\'s page is "Ty le ky '
                 'quy rui ro", the scenario grid\'s risk rate. Reading it as '
                 'an IM ratio in an IM+VM model is research conflict C-1 in '
                 'miniature, and it is the mistake this field refuses to make'),
        'block_open_level': _c(
            Coverage.PUBLISHED,
            f'Muc 1 -- ty le giao dich toi da, {levels[0]}',
            SourceClass.PUBLISHED_SCHEDULE, url=url, eff=effective, note=src),
        'margin_call_level': _c(
            Coverage.PUBLISHED, f'Muc 2 -- ty le duy tri, {levels[1]}',
            SourceClass.PUBLISHED_SCHEDULE, url=url, eff=effective,
            quote='Khi tỷ lệ sử dụng tài sản ký quỹ thực tế > Mức 2 và < Mức '
                  '3, Khách hàng sẽ nhận được thông báo khuyến nghị về trạng '
                  'thái cần bổ sung Tài sản ký quỹ',
            note='the notice condition is an OPEN interval, "> Muc 2 and < '
                 'Muc 3". At exactly Muc 2 SSI does not act and this module '
                 'does, because Direction.is_at_or_past is inclusive -- '
                 'conservative by one boundary, recorded so it is not '
                 'mistaken for SSI\'s wording. ' + src),
        'forced_close_level': _c(
            Coverage.PUBLISHED, f'Muc 3 -- ty le xu ly, {levels[2]}',
            SourceClass.PUBLISHED_SCHEDULE, url=url, eff=effective,
            quote='Ngay khi tỷ lệ sử dụng tài sản ký quỹ thực tế ≥Mức 3',
            note='"≥ Muc 3" -- inclusive, and this one matches. ' + src),
        'target': _c(Coverage.PUBLISHED, 'the rung a forced close restores to',
                     SourceClass.PUBLISHED_SCHEDULE, url=url, eff=effective,
                     quote='SSI sẽ tự động điều chuyển tiền từ tài khoản của '
                           'Khách hàng tại SSI lên VSD hoặc ngược lại để bổ '
                           'sung ký quỹ và/hoặc thực hiện đóng vị thế bắt buộc '
                           'để đưa tỷ lệ sử dụng tài sản ký quỹ của tài khoản '
                           'về Mức 1',
                     note='Muc 1, and the sentence carries the REMEDY ORDER in '
                          'the same breath: transfer first, "va/hoac" forced '
                          'closing second -- see Rung.follow_on. ' + src),
        'notification': _c(
            Coverage.UNPUBLISHED, 'channel, timing and cure window of a notice',
            SourceClass.PUBLISHED_SCHEDULE, url=url,
            gap=GapKind.G16_SOURCE_CLASS_WEAK,
            quote='KH sẽ nhận được thông báo khuyến nghị',
            note='the duty is stated at Muc 2 and nothing else is: no channel, '
                 'no timing, no cure window'),
        'cure_window': _c(
            Coverage.UNPUBLISHED, 'time allowed to answer a call',
            SourceClass.PUBLISHED_SCHEDULE, url=url,
            gap=GapKind.G8_NOTICE_UNKNOWN, note=src),
        'minimum_margin_factor': _c(
            Coverage.PUBLISHED, 'total per-contract requirement',
            SourceClass.PUBLISHED_SCHEDULE, url=url, eff=effective,
            gap=GapKind.G18_HOMONYM,
            quote=('Giá trị ký quỹ tối thiểu/1HĐ: 31.711.460 đồng'
                   if vintage_2025_09
                   else 'Giá trị ký quỹ tối thiểu/1HĐ: 34.520.710 đồng'),
            note='THIS IS NOT MF. Same Vietnamese phrase, different quantity: '
                 'TCBS publishes 5,000d under it. 34,520,710 / ((0.17 + '
                 '0.0087) x 100,000) = 1931.8, a plausible VN30 level, so the '
                 'number is a dated snapshot of the total per-contract '
                 'requirement, not a policy constant. Mapping it into MF makes '
                 'MM bind on every book and destroys MR = max(Rm + Sm - OA, '
                 'MM)'),
        'vsdc_parameters': (
            _c(Coverage.CONTRADICTORY,
               'Rm, Sm, Psr, scale factor and the per-contract requirement',
               SourceClass.PUBLISHED_SCHEDULE, url=url, eff=effective,
               gap=GapKind.G14_SOURCE_SELF_CONTRADICTORY,
               quote='Tỷ lệ ký quỹ rủi ro 17% / Tỷ lệ ký quỹ song hành 17%',
               defect='this page prints Sm = 17%, equal to Rm to the digit, '
                      'and the row immediately below it prints a per-contract '
                      'requirement of 31,711,460d. The two cannot both hold: '
                      '31,711,460 / ((0.17 + 0.17) x 100,000) = 932.7, and '
                      'the VN30 traded near 1,700 in September 2025. Under '
                      'the successor page\'s Sm the same figure implies '
                      '1,774.6, which is right. So Sm = 17% is a placeholder '
                      'left in the table, not a rate SSI charged -- but we do '
                      'not know what it replaced, so it is recorded as the '
                      'contradiction it is rather than repaired.',
               note=src)
            if vintage_2025_09 else
            _c(Coverage.PUBLISHED,
               'Rm, Sm, Psr, scale factor and the per-contract requirement',
               SourceClass.PUBLISHED_SCHEDULE, url=url, eff=effective,
               gap=GapKind.G12_PARAMETER_VINTAGE,
               note='the richest parameter mirror in the survey, and still a '
                    'MIRROR: SSI itself says "Cac thong so co the thay doi '
                    'theo quy dinh cua VSD tuy tung thoi diem". SHS publishes '
                    'Sm = 0.42% on the same instrument. ' + src)),
        'position_limits': _c(
            Coverage.PUBLISHED, 'max contracts per account, by investor class',
            SourceClass.PUBLISHED_SCHEDULE, url=url, eff=effective,
            note='5,000 individual / 10,000 institutional / 20,000 '
                 'professional. An EXCHANGE rule -- TCBS prints the identical '
                 'triple and attributes it "Theo quy dinh tai VSD". Held on '
                 'the parameter set, not as a commercial term. ' + src),
        'threshold_stability': _c(
            Coverage.PUBLISHED, 'the firm\'s right to change the thresholds',
            SourceClass.PUBLISHED_SCHEDULE, url=url, eff=effective,
            quote='Các thông số này có thể thay đổi theo quy định của SSI tùy '
                  'từng thời điểm',
            note='SSI reserves the right over its OWN parameters and, in a '
                 'separate line, notes that VSD\'s may move too. The pair is '
                 'why every number here is dated rather than constant. ' + src),
    }
    return BrokerProfile(
        firm=who, is_synthesis=False, regime=Regime.POST_KRX,
        document_date=effective,
        margin_model_intraday=MarginModel.UNSTATED,
        margin_model_overnight=MarginModel.SCENARIO_GRID,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(DenominatorBasis.UNPUBLISHED,
                                    LiabilitiesTreatment.UNPUBLISHED,
                                    note='named "tong gia tri tai san ky quy '
                                         'hop le" and never composed'),
        ladder=ladder, coverage=cov,
        vsdc_parameters=params,
        published_per_contract_requirement=(
            params.for_underlying('VN30').minimum_per_contract_requirement),
        superseded_by=('SSI (85/90/95, effective 2026-01-16)'
                       if vintage_2025_09 else None),
        supersedes=(None if vintage_2025_09 else
                    'SSI_2025_09 -- 80/85/90 effective 2025-09-11. The one '
                    'policy change in the survey that carries a date on both '
                    'sides. The foreign ladder did NOT move: 75/80/85 on both '
                    'pages'),
        description=(
            'SSI\'s superseded vintage: 80/85/90, Psr 1, and an Sm its own '
            'next row disproves.' if vintage_2025_09
            else 'SSI\'s separate ladder for foreign investors -- unchanged '
                 'across both vintages.' if foreign
            else 'The parameter feed: most recent, richest parameters, and no '
                 'margin model at all.'),
    )


# -- VNDIRECT ---------------------------------------------------------------

_VND_URL = 'https://support.vndirect.com.vn/hc/vi/articles/360005953573'


def _vndirect() -> BrokerProfile:
    """VNDIRECT -- the clean exemplar of the net-asset denominator.

    Its rungs are the very 80/90/100 that QD 26 deleted, and its **divisor is
    not VSDC's**: *"Tien ky quy + Tien gui tai VNDIRECT - Nghia vu no + Gia
    tri chung khoan ky quy hop le"*. Same rung numbers, different ratio, so a
    simulator that reads the numbers and assumes ``V_KQ`` will call at the
    wrong time. That is research conflict C-3 and gap kind ``G4``.

    It also publishes its **own IM ratio, 17.5%** against VSDC's 17% (research
    S-17), and reserves the right to change the thresholds *"vao bat ky thoi
    diem nao"* -- which reads as a live commercial term, not inherited text.

    **No action text at any of its three levels.** They are *"nguong canh
    bao"* and nothing more, so neither fire nor target may be assumed: gap
    kind ``G5``, and :func:`forced_reduction` refuses on this profile.
    """
    ladder = tuple(
        Rung(coverage_key=key, name=f'Nguong canh bao muc do {i}',
             level=level, action=Action.NONE,
             target_ref=TargetRef.UNRESOLVED, notice=Notice.UNKNOWN,
             cure=_UNKNOWN_CURE)
        for i, (key, level) in enumerate(
            (('block_open_level', Decimal('0.80')),
             ('margin_call_level', Decimal('0.90')),
             ('forced_close_level', Decimal('1.00'))), start=1))
    cov = {
        'direction': _c(Coverage.PUBLISHED, 'sign of the ladder ratio',
                        SourceClass.HELP_PAGE, url=_VND_URL),
        'denominator': _c(
            Coverage.PUBLISHED, 'net valid asset value',
            SourceClass.HELP_PAGE, url=_VND_URL,
            gap=GapKind.G4_DENOMINATOR_DIVERGENT,
            quote='Tiền ký quỹ + Tiền gửi tại VNDIRECT – Nghĩa vụ nợ + Giá trị '
                  'chứng khoán ký quỹ hợp lệ tại VNDIRECT',
            note='NOT V_KQ: QD 26 Dieu 8 subtracts no liabilities and caps '
                 'securities at (1 - 0.80) x MR'),
        'liabilities_treatment': _c(
            Coverage.PUBLISHED, 'debts subtracted from the divisor',
            SourceClass.HELP_PAGE, url=_VND_URL,
            gap=GapKind.G4_DENOMINATOR_DIVERGENT),
        'margin_model_intraday': _c(
            Coverage.PUBLISHED, 'MR = IM + VM + DM + other obligations',
            SourceClass.HELP_PAGE, url=_VND_URL,
            quote='Giá trị ký quỹ duy trì yêu cầu (MR) = IM + VM + DM + Các '
                  'nghĩa vụ khác'),
        'margin_model_overnight': _c(
            Coverage.UNPUBLISHED, 'formula for the CCP submission',
            SourceClass.HELP_PAGE, url=_VND_URL,
            gap=GapKind.G10_MODEL_NOT_STATED),
        'initial_margin_ratio': _c(
            Coverage.PUBLISHED, 'the broker\'s own initial margin ratio',
            SourceClass.HELP_PAGE, url=_VND_URL,
            quote='Tỷ lệ ký quỹ ban đầu đối với Hợp đồng tương lai chỉ số '
                  'chứng khoán là 17.5%',
            note='research S-17: an own ratio above VSDC\'s 17%, and '
                 'asymmetric across products (GB futures 2.8% against 2.5%)'),
        'block_open_level': _c(Coverage.PUBLISHED, 'muc do 1, 80%',
                               SourceClass.HELP_PAGE, url=_VND_URL),
        'margin_call_level': _c(Coverage.PUBLISHED, 'muc do 2, 90%',
                                SourceClass.HELP_PAGE, url=_VND_URL),
        'forced_close_level': _c(Coverage.PUBLISHED, 'muc do 3, 100%',
                                 SourceClass.HELP_PAGE, url=_VND_URL),
        'target': _c(
            Coverage.UNPUBLISHED, 'fire-vs-target at every rung',
            SourceClass.HELP_PAGE, url=_VND_URL,
            gap=GapKind.G5_ACTION_UNKNOWN,
            note='three thresholds, and no action text at any of them. '
                 'Whether VNDIRECT clears the rung or restores to a level is '
                 'not published, and the two differ by the whole of the '
                 'forced sale'),
        'notification': _c(Coverage.UNPUBLISHED, 'duty to notify',
                           SourceClass.HELP_PAGE, url=_VND_URL,
                           gap=GapKind.G8_NOTICE_UNKNOWN),
        'cure_window': _c(Coverage.UNPUBLISHED, 'time allowed to answer',
                          SourceClass.HELP_PAGE, url=_VND_URL,
                          gap=GapKind.G8_NOTICE_UNKNOWN,
                          note='"next working day" is stated for VM '
                               'settlement, not for a margin call'),
        'threshold_stability': _c(
            Coverage.PUBLISHED, 'the firm\'s right to change the thresholds',
            SourceClass.HELP_PAGE, url=_VND_URL,
            quote='VNDIRECT được quyền thay đổi các ngưỡng tỷ lệ cảnh báo nêu '
                  'trên vào bất kỳ thời điểm nào'),
    }
    return BrokerProfile(
        firm='VNDIRECT', is_synthesis=False, regime=Regime.POST_KRX,
        document_date=None,
        margin_model_intraday=MarginModel.IM_PLUS_VM_PLUS_DM,
        margin_model_overnight=MarginModel.UNSTATED,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(
            DenominatorBasis.NET_ASSETS,
            LiabilitiesTreatment.SUBTRACTED_FROM_ASSETS),
        ladder=ladder, coverage=cov,
        initial_margin_ratio=Decimal('0.175'),
        description='The net-asset denominator, and an own IM ratio.',
    )


# -- FPTS -------------------------------------------------------------------

def _fpts() -> BrokerProfile:
    """FPTS -- the best collateral coverage in the pool.

    Cash minimum 80% and haircuts 5 / 30 / 40% matching QD 26 Dieu 9
    verbatim. **The haircuts are an exchange rule, not a commercial term** --
    FPTS restates the law, so they are recorded as such and not stored on the
    profile as if FPTS had chosen them.

    FPTS is the firm that states both layers cleanly: ``MR = IM + VM + DM``,
    *"duoc he thong cua FPTS tinh lien tuc trong phien"*, while heading the
    four scenario-grid components separately under *"4 Ky quy tai VSDC"*. That
    separation is the direct evidence for :attr:`MarginLayer`.

    **No target published** at any rung, so gap kind ``G5`` applies here too.
    """
    ladder = (
        Rung(coverage_key='block_open_level', name='Nguong 80% -- chan mo moi',
             level=Decimal('0.80'), action=Action.BLOCK_OPENING,
             target_ref=TargetRef.NONE, notice=Notice.UNKNOWN,
             cure=_UNKNOWN_CURE),
        Rung(coverage_key='margin_call_level', name='Nguong 90% -- hien thi '
                                                    'yeu cau nop bo sung',
             level=Decimal('0.90'), action=Action.NOTIFY,
             target_ref=TargetRef.UNRESOLVED, notice=Notice.REQUIRED,
             cure=_UNKNOWN_CURE),
        Rung(coverage_key='forced_close_level', name='Nguong 100% -- tu dong '
                                                     'dong vi the',
             level=Decimal('1.00'), action=Action.LIQUIDATE,
             target_ref=TargetRef.UNRESOLVED, notice=Notice.UNKNOWN,
             cure=_IMMEDIATE),
    )
    src = 'fpts.txt / fpts_quyche.txt in the survey scratchpad; the page is '\
          'undated and its content is KRX-era'
    cov = {
        'direction': _c(Coverage.PUBLISHED, 'sign of the ladder ratio',
                        SourceClass.PUBLISHED_SCHEDULE, note=src),
        'denominator': _c(
            Coverage.PUBLISHED, 'valid margin assets net of debts',
            SourceClass.PUBLISHED_SCHEDULE,
            gap=GapKind.G4_DENOMINATOR_DIVERGENT,
            quote='sau khi trừ đi các nghĩa vụ nợ phải trả', note=src),
        'liabilities_treatment': _c(
            Coverage.PUBLISHED, 'debts subtracted from the divisor',
            SourceClass.PUBLISHED_SCHEDULE,
            gap=GapKind.G4_DENOMINATOR_DIVERGENT, note=src),
        'margin_model_intraday': _c(
            Coverage.PUBLISHED, 'MR = IM + VM + DM, continuous',
            SourceClass.PUBLISHED_SCHEDULE,
            quote='được hệ thống của FPTS tính liên tục trong phiên', note=src),
        'margin_model_overnight': _c(
            Coverage.PUBLISHED, 'the four VSDC components, named separately',
            SourceClass.PUBLISHED_SCHEDULE,
            quote='4 Ký quỹ tại VSDC',
            note='FPTS heads Rm, Sm, Dm and FSP under a VSDC heading and '
                 'defines its own client number separately. ' + src),
        'initial_margin_ratio': _c(
            Coverage.PUBLISHED, 'the broker\'s own initial margin ratio',
            SourceClass.PUBLISHED_SCHEDULE,
            note='17.85%, above VSDC\'s 17% per research S-17. ' + src),
        'block_open_level': _c(Coverage.PUBLISHED, '80%',
                               SourceClass.PUBLISHED_SCHEDULE, note=src),
        'margin_call_level': _c(Coverage.PUBLISHED, '90%',
                                SourceClass.PUBLISHED_SCHEDULE, note=src),
        'forced_close_level': _c(Coverage.PUBLISHED, '100%',
                                 SourceClass.PUBLISHED_SCHEDULE, note=src),
        'target': _c(Coverage.UNPUBLISHED, 'the level a close-out restores to',
                     SourceClass.PUBLISHED_SCHEDULE,
                     gap=GapKind.G5_ACTION_UNKNOWN,
                     note='FPTS publishes the 100% auto-close and no target'),
        'notification': _c(
            Coverage.PUBLISHED, 'display-only duty at 90%',
            SourceClass.PUBLISHED_SCHEDULE,
            gap=GapKind.G16_SOURCE_CLASS_WEAK,
            note='the duty is to DISPLAY the top-up requirement, which is '
                 'weaker than a duty to notify. ' + src),
        'cure_window': _c(Coverage.UNPUBLISHED, 'time allowed to answer',
                          SourceClass.PUBLISHED_SCHEDULE,
                          gap=GapKind.G8_NOTICE_UNKNOWN, note=src),
        'minimum_cash_share': _c(
            Coverage.PUBLISHED, 'minimum cash share of margin assets, 80%',
            SourceClass.PUBLISHED_SCHEDULE, note=src),
        'collateral_haircuts': _c(
            Coverage.PUBLISHED, 'haircut tiers 5 / 30 / 40%',
            SourceClass.PUBLISHED_SCHEDULE,
            note='these are QD 26 Dieu 9 restated verbatim -- an EXCHANGE '
                 'rule, not a commercial term. Recorded here because FPTS is '
                 'the only firm that prints them, and deliberately NOT stored '
                 'on the profile as if FPTS had chosen them. ' + src),
    }
    return BrokerProfile(
        firm='FPTS', is_synthesis=False, regime=Regime.POST_KRX,
        document_date=None,
        margin_model_intraday=MarginModel.IM_PLUS_VM_PLUS_DM,
        margin_model_overnight=MarginModel.SCENARIO_GRID,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(
            DenominatorBasis.V_KQ,
            LiabilitiesTreatment.SUBTRACTED_FROM_ASSETS,
            securities_cap_fraction=Decimal('0.20')),
        ladder=ladder, coverage=cov,
        initial_margin_ratio=Decimal('0.1785'),
        minimum_cash_share=Decimal('0.80'),
        description='Best collateral coverage; both margin layers stated '
                    'separately; no target at any rung.',
    )


# -- SHS --------------------------------------------------------------------

def _shs() -> BrokerProfile:
    """SHS -- a four-rung ladder and a third liabilities convention.

    SHS puts the client's debts in the **numerator** (*"va cac khoan no khac
    cua KH tai SHS (phi, thue)"*), which nobody else does. It also gives the
    cleanest proof that mirrored VSDC parameters are **dated**: its
    ``Sm = 0.42%`` against SSI's ``0.87%``, and its 22,309,440d per-contract
    figure against SSI's 34,520,710d, with both firms presenting theirs as
    current. Gap kind ``G12``.

    ``22,309,440 / ((0.17 + 0.0042) x 100,000) = 1280.7`` -- again a plausible
    VN30 level, and again therefore a snapshot and not ``MF``.
    """
    ladder = (
        Rung(coverage_key='safe_level', name='Ty le an toan',
             level=Decimal('0.75'), action=Action.BLOCK_OPENING,
             target_ref=TargetRef.NONE, notice=Notice.UNKNOWN,
             cure=_UNKNOWN_CURE),
        Rung(coverage_key='margin_call_level', name='Ty le duy tri',
             level=Decimal('0.85'), action=Action.NOTIFY,
             target_ref=TargetRef.RUNG_2, notice=Notice.UNKNOWN,
             cure=_UNKNOWN_CURE),
        Rung(coverage_key='forced_close_level', name='Ty le xu ly',
             level=Decimal('0.90'), action=Action.LIQUIDATE,
             target_ref=TargetRef.RUNG_2, notice=Notice.UNKNOWN,
             cure=_IMMEDIATE),
    )
    src = 'shs_hcm_hn.pdf in the survey scratchpad; undated, parameters of a '\
          'mid-2025 vintage'
    cov = {
        'direction': _c(Coverage.PUBLISHED, 'sign of the ladder ratio',
                        SourceClass.PUBLISHED_SCHEDULE, note=src),
        'denominator': _c(
            Coverage.PUBLISHED, 'valid margin assets',
            SourceClass.PUBLISHED_SCHEDULE, note=src),
        'liabilities_treatment': _c(
            Coverage.PUBLISHED, 'debts added to the NUMERATOR',
            SourceClass.PUBLISHED_SCHEDULE,
            gap=GapKind.G4_DENOMINATOR_DIVERGENT,
            quote='và các khoản nợ khác của KH tại SHS (phí, thuế)',
            note='a third convention, used by no other surveyed firm. ' + src),
        'margin_model_intraday': _c(
            Coverage.PUBLISHED, 'MR = IM + VM(loss) + other debts, continuous',
            SourceClass.PUBLISHED_SCHEDULE, note=src),
        'margin_model_overnight': _c(
            Coverage.INFERRED, 'the model SHS\'s parameters belong to',
            SourceClass.OURS, gap=GapKind.G10_MODEL_NOT_STATED,
            note='SHS publishes Rm, Sm, Dm and a per-contract figure without '
                 'the assembly, as SSI does'),
        'initial_margin_ratio': _c(
            Coverage.DELEGATED, 'the broker initial margin ratio',
            SourceClass.PUBLISHED_SCHEDULE, gap=GapKind.G1_DELEGATED,
            note='SHS mirrors VSDC\'s 17% and publishes no uplift. ' + src),
        'safe_level': _c(Coverage.PUBLISHED, 'Ty le an toan, 75%',
                         SourceClass.PUBLISHED_SCHEDULE, note=src),
        'margin_call_level': _c(Coverage.PUBLISHED, 'Ty le duy tri, 85%',
                                SourceClass.PUBLISHED_SCHEDULE, note=src),
        'forced_close_level': _c(Coverage.PUBLISHED, 'Ty le xu ly, 90%',
                                 SourceClass.PUBLISHED_SCHEDULE, note=src),
        'target': _c(Coverage.PUBLISHED, 'restore to Ty le duy tri (rung 2)',
                     SourceClass.PUBLISHED_SCHEDULE,
                     note='the only surveyed firm whose target is rung 2 '
                          'rather than rung 1. ' + src),
        'notification': _c(Coverage.UNPUBLISHED, 'duty to notify',
                           SourceClass.PUBLISHED_SCHEDULE,
                           gap=GapKind.G8_NOTICE_UNKNOWN,
                           note='SHS is entirely silent on notification'),
        'cure_window': _c(Coverage.UNPUBLISHED, 'time allowed to answer',
                          SourceClass.PUBLISHED_SCHEDULE,
                          gap=GapKind.G8_NOTICE_UNKNOWN, note=src),
        'vsdc_parameters': _c(
            Coverage.PUBLISHED_STALE, 'Rm 17%, Sm 0.42% for index futures',
            SourceClass.PUBLISHED_SCHEDULE, gap=GapKind.G12_PARAMETER_VINTAGE,
            quote='Tỷ lệ ký quỹ song hành (Sm) − HĐTL chỉ số: 0.42%',
            note='Sm 0.42% against SSI\'s 0.87% on the same instrument -- '
                 'more than double, both firms presenting theirs as current. '
                 'That is the survey\'s cleanest proof that a mirrored '
                 'parameter is dated. SHS also prints Dm 2.5%, but only for '
                 'HDTL TPCP; its index row is blank, so Dm is None here '
                 'rather than 2.5%. And SHS mirrors NO Psr and NO scale '
                 'factor, so no group offset can be computed from SHS\'s '
                 'page at all. ' + src),
        'position_limits': _c(
            Coverage.UNPUBLISHED, 'max contracts per account',
            SourceClass.PUBLISHED_SCHEDULE, gap=GapKind.G1_DELEGATED,
            quote='Theo quy định của VSDC từng thời kỳ',
            note='SHS delegates the whole parameter block to VSDC in one '
                 'line and then prints its own snapshot of part of it. ' + src),
        'minimum_margin_factor': _c(
            Coverage.PUBLISHED_STALE, 'total per-contract requirement',
            SourceClass.PUBLISHED_SCHEDULE, gap=GapKind.G18_HOMONYM,
            quote='Ký quỹ tối thiểu (MM) – HĐTL chỉ số: 22,309,440 VNĐ',
            note='SHS labels it MM. It is NOT MF and it is not a policy '
                 'constant: 22,309,440 / ((0.17 + 0.0042) x 100,000) = 1280.7, '
                 'a VN30 level. ' + src),
    }
    return BrokerProfile(
        firm='SHS', is_synthesis=False, regime=Regime.POST_KRX,
        document_date=None,
        margin_model_intraday=MarginModel.IM_PLUS_VM_PLUS_DM,
        margin_model_overnight=MarginModel.SCENARIO_GRID,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(
            DenominatorBasis.V_KQ, LiabilitiesTreatment.ADDED_TO_NUMERATOR,
            securities_cap_fraction=Decimal('0.20')),
        ladder=ladder, coverage=cov,
        published_per_contract_requirement=Decimal('22309440'),
        vsdc_parameters=VsdcParameterSet(
            effective_from=None,
            source='SHS derivatives account terms, section "Cac thong so ky '
                   'quy" (setB/shs_hd.txt in the survey scratchpad); the '
                   'document carries no date',
            underlyings=(
                UnderlyingParameters(
                    underlying='VN30',
                    risk_margin_rate=Decimal('0.17'),
                    spread_margin_rate=Decimal('0.0042'),
                    minimum_per_contract_requirement=Decimal('22309440'),
                    note='no Psr and no scale factor are published, so '
                         'supports_group_offsetting is False: SHS mirrors the '
                         'rates and not the offset. Dm is None because SHS '
                         'attaches its 2.5% to HDTL TPCP and leaves the index '
                         'row blank'),
            )),
        description='Four rungs, a third liabilities convention, and the '
                    'cleanest proof that mirrored parameters are dated.',
    )


# -- Vietcap ----------------------------------------------------------------

def _vietcap() -> BrokerProfile:
    """Vietcap -- the highest published IM uplift, and only two rungs.

    ``IM = 20%`` against VSDC's 17% is the largest uplift observed (research
    S-17). Vietcap publishes 90 and 95 and **not its level 1**: the 85 that
    appears on the page appears only as the *target*, so this is the one
    profile where :attr:`TargetRef.ABSOLUTE` is the honest encoding -- there is
    no rung 1 for a reference to point at.

    Tagged **REPORTED, not VERIFIED**: the live fetch returned HTTP 403 this
    session, so the content is from a secondary reading.
    """
    ladder = (
        Rung(coverage_key='margin_call_level', name='Muc canh bao 90%',
             level=Decimal('0.90'), action=Action.NOTIFY,
             target_ref=TargetRef.ABSOLUTE, target_absolute=Decimal('0.85'),
             notice=Notice.REQUIRED, cure=_UNKNOWN_CURE),
        Rung(coverage_key='forced_close_level', name='Muc xu ly 95%',
             level=Decimal('0.95'), action=Action.LIQUIDATE,
             target_ref=TargetRef.ABSOLUTE, target_absolute=Decimal('0.85'),
             notice=Notice.REQUIRED, cure=_IMMEDIATE),
    )
    src = 'live page; fetch returned HTTP 403 this session, so the reading is '\
          'secondary -- REPORTED, not VERIFIED'
    cov = {
        'direction': _c(Coverage.PUBLISHED, 'sign of the ladder ratio',
                        SourceClass.SECONDARY, note=src),
        'denominator': _c(
            Coverage.UNPUBLISHED, 'divisor, named but not composed',
            SourceClass.SECONDARY, gap=GapKind.G3_DENOMINATOR_UNDEFINED,
            quote='Giá trị tài sản ký quỹ hợp lệ', note=src),
        'liabilities_treatment': _c(
            Coverage.UNPUBLISHED, 'where client debts enter the ratio',
            SourceClass.SECONDARY, gap=GapKind.G3_DENOMINATOR_UNDEFINED,
            note=src),
        'margin_model_intraday': _c(
            Coverage.PUBLISHED, 'MR = IM + VM', SourceClass.SECONDARY,
            note=src),
        'margin_model_overnight': _c(
            Coverage.UNPUBLISHED, 'formula for the CCP submission',
            SourceClass.SECONDARY, gap=GapKind.G10_MODEL_NOT_STATED,
            note='Vietcap states IM+VM in prose while tabling VSD\'s scenario '
                 'ratio, which is two models on one page without a seam '
                 'between them. ' + src),
        'initial_margin_ratio': _c(
            Coverage.PUBLISHED, 'the broker\'s own initial margin ratio, 20%',
            SourceClass.SECONDARY,
            note='the highest uplift observed in the pool. ' + src),
        'margin_call_level': _c(Coverage.PUBLISHED, '90%',
                                SourceClass.SECONDARY, note=src),
        'forced_close_level': _c(Coverage.PUBLISHED, '95%',
                                 SourceClass.SECONDARY, note=src),
        'block_open_level': _c(
            Coverage.UNPUBLISHED, 'level 1, the max utilisation to open',
            SourceClass.SECONDARY, gap=GapKind.G3_DENOMINATOR_UNDEFINED,
            note='Vietcap does not publish a level 1. The 85 on its page is '
                 'the TARGET, not a rung, and reading it as rung 1 would '
                 'invent a threshold Vietcap does not have. ' + src),
        'target': _c(Coverage.PUBLISHED, 'restore to 85% at both rungs',
                     SourceClass.SECONDARY,
                     note='the 85 is the TARGET and Vietcap publishes no rung '
                          'at it -- see block_open_level, which is why this is '
                          'the one profile encoded with TargetRef.ABSOLUTE. '
                          + src),
        'notification': _c(Coverage.PUBLISHED, 'duty to notify at 90%',
                           SourceClass.SECONDARY,
                           gap=GapKind.G16_SOURCE_CLASS_WEAK,
                           quote='Vietcap sẽ gửi thông báo', note=src),
        'cure_window': _c(Coverage.UNPUBLISHED, 'time allowed to answer',
                          SourceClass.SECONDARY,
                          gap=GapKind.G8_NOTICE_UNKNOWN, note=src),
    }
    return BrokerProfile(
        firm='Vietcap', is_synthesis=False, regime=Regime.POST_KRX,
        document_date=None,
        margin_model_intraday=MarginModel.IM_PLUS_VM,
        margin_model_overnight=MarginModel.UNSTATED,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(DenominatorBasis.UNPUBLISHED,
                                    LiabilitiesTreatment.UNPUBLISHED),
        ladder=ladder, coverage=cov,
        initial_margin_ratio=Decimal('0.20'),
        description='Highest IM uplift in the pool; level 1 not published.',
    )


# -- HSC: the only falling-coverage firm ------------------------------------

_HSC_URL = ('https://hsc.com.vn/moi-gioi-phai-sinh/'
            'quy-dinh-giao-dich-ky-quy-phai-sinh.html')


def _hsc() -> BrokerProfile:
    """HSC -- the sole falling-coverage exemplar, on a pre-KRX page.

    ``R = So du ky quy / IM``: **lower is worse**, the rungs descend
    100 / 80 / 60, and ``MM = 80% x IM``. Its divisor is ``IM``, not an asset
    total, so its ratio is not a utilisation ratio at all and cannot be
    compared with any other firm's rung without a modelling choice.

    That choice is gap kind ``G17`` and it is why HSC is excluded from every
    PLUTUS_DEFAULT numeric pool: converting to utilisation gives ``U = 1/R``
    if ``MR == IM`` (100 / 125 / 167%) but ``U = 0.8/R`` if
    ``MR == MM == 0.8 x IM``, and the two disagree by 25 points on the same
    rung. Not arithmetic -- a decision about what HSC's ``MR`` is.

    HSC is also the **only firm in the survey publishing a complete
    notice-to-liquidation timeline**: notice from 16:30 on T by SMS and email,
    cure by 11:30 T+1, force-close 13:00 T+1. And its page is dated
    **15.04.2020**, five years before the KRX cutover, so everything on it is
    gap kind ``G13``.

    **The rung names are HSC's bands, and getting them right matters.** HSC's
    table is written as *bands*, not thresholds, and the band an account is in
    at ``R = 0.80`` is not the band it is in at ``R = 0.79``:

    ========================  ==================  ==========================
    band                      HSC's range         what HSC does
    ========================  ==================  ==========================
    Binh thuong (Normal)      ``R > 100%``        may open, may withdraw
    Ky quy duy tri            ``80% <= R < 100%`` **may not open or withdraw**
    Yeu cau ky quy            ``60% <= R < 80%``  margin call
    Dong vi the               ``R < 60%``         HSC closes immediately
    ========================  ==================  ==========================

    So the rung at ``1.00`` is *Ky quy duy tri* and it **blocks opening**; the
    rung at ``0.80`` is the *margin call*. HSC's own table also leaves
    ``R = 100%`` in a row of its own belonging to neither band, and this
    module resolves that inclusively -- ``R = 1.00`` is treated as blocked --
    which is conservative and is not HSC's words.

    **And HSC states its own target three times, in two different places.**
    The band table says restore *"toi thieu ve nguong Ky quy duy tri"* -- to
    ``R >= 80%``. Two paragraphs below, *"Ky quy bo sung"* is defined as
    ``IM - So du ky quy``, which is a top-up to ``R = 100%``, and *"Xu ly cac
    tai khoan vi pham ky quy"* requires the account *"toi thieu ve trang thai
    Binh thuong (Normal) truoc 11:30 ngay T+1"* -- again ``R >= 100%``. Two of
    the three say 100 and the band table says 80. The difference is the whole
    of the forced sale, so it is recorded as a source defect on the ``target``
    field and **not resolved**; the band table is taken as operative because
    it is the clause that assigns actions to bands at all.
    """
    ladder = (
        Rung(coverage_key='maintenance_level', name='Ky quy duy tri',
             level=Decimal('1.00'), action=Action.BLOCK_OPENING,
             target_ref=TargetRef.NONE, notice=Notice.UNKNOWN,
             cure=_UNKNOWN_CURE),
        Rung(coverage_key='margin_call_level', name='Yeu cau ky quy',
             level=Decimal('0.80'), action=Action.NOTIFY,
             target_ref=TargetRef.RUNG_2, notice=Notice.REQUIRED,
             cure=CureSpec(CureKind.DEADLINE,
                           deadline='11:30 T+1; notice from 16:30 T by SMS '
                                    'and email')),
        Rung(coverage_key='forced_close_level', name='Dong vi the',
             level=Decimal('0.60'), action=Action.LIQUIDATE,
             target_ref=TargetRef.RUNG_2, notice=Notice.REQUIRED,
             cure=_IMMEDIATE),
    )
    src = ('HSC, "Quy dinh ky quy", '
           'https://hsc.com.vn/moi-gioi-phai-sinh/'
           'quy-dinh-giao-dich-ky-quy-phai-sinh.html, page dated 15.04.2020 '
           '-- PRE-KRX by five years')
    cov = {
        'direction': _c(Coverage.PUBLISHED, 'FALLING coverage, not utilisation',
                        SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
                        gap=GapKind.G17_UNIT_MISMATCH,
                        note='R = So du ky quy / IM. The only firm running '
                             'this direction. ' + src),
        'denominator': _c(Coverage.PUBLISHED, 'IM, not an asset total',
                          SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
                          gap=GapKind.G17_UNIT_MISMATCH, note=src),
        'liabilities_treatment': _c(
            Coverage.INAPPLICABLE, 'liabilities in a coverage ratio',
            SourceClass.HELP_PAGE, url=_HSC_URL, gap=GapKind.G15_INAPPLICABLE,
            note='HSC divides by IM. There is no asset denominator for a '
                 'liability to be subtracted from, so the question does not '
                 'arise -- which is different from HSC not answering it'),
        'margin_model_intraday': _c(
            Coverage.PUBLISHED, 'IM, with MM = 80% x IM',
            SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
            note='the only IM/MM model in the pool. ' + src),
        'margin_model_overnight': _c(
            Coverage.UNPUBLISHED, 'formula for the CCP submission',
            SourceClass.HELP_PAGE, url=_HSC_URL, gap=GapKind.G10_MODEL_NOT_STATED, note=src),
        'initial_margin_ratio': _c(
            Coverage.PUBLISHED, 'the broker\'s own initial margin ratio, 17%',
            SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
            note='equal to VSDC\'s, on a page five years older than the '
                 'current VSDC ratio. ' + src),
        'maintenance_level': _c(
            Coverage.PUBLISHED, 'coverage 100% -- Ky quy duy tri begins',
            SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
            quote='TK không được mở vị thế mới và rút tiền',
            note='HSC publishes an action at this band and it is NOT a '
                 'warning: below 100% coverage the account may neither open a '
                 'new position nor withdraw, and it is expressly "khong bi '
                 'yeu cau ky quy bo sung" -- no call. HSC leaves R = 100% in '
                 'a row of its own, in neither band; treated inclusively '
                 'here, which is ours and conservative. ' + src),
        'margin_call_level': _c(
            Coverage.PUBLISHED, 'coverage 80% -- Yeu cau ky quy begins',
            SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
            quote='Khi Số dư ký quỹ giảm xuống dưới mức Ký quỹ duy trì, Khách '
                  'hàng sẽ nhận được thông báo nộp bổ sung ký quỹ (Margin '
                  'Call)',
            note='the call fires below MM = 0.80 x IM, i.e. below R = 80%. '
                 'This is the same 80% as the maintenance_margin_fraction, '
                 'and that is not a coincidence: R = balance/IM, so balance = '
                 'MM = 0.80 x IM is exactly R = 0.80. ' + src),
        'forced_close_level': _c(
            Coverage.PUBLISHED, 'coverage 60% -- Dong vi the',
            SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
            quote='ngay khi TK có trạng thái này, HSC sẽ tiến hành đóng trạng '
                  'thái ngay lập tức tại bất kỳ thời điểm nào',
            note=src),
        'maintenance_margin_fraction': _c(
            Coverage.PUBLISHED, 'Ty le MM in MM = Ty le MM x IM',
            SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
            gap=GapKind.G1_DELEGATED,
            quote='tỷ lệ MM do HSC quy định và có thể thay đổi theo từng thời '
                  'kỳ. Hiện tại HSC áp dụng tỷ lệ MM = 80%',
            note='published AND delegated in one sentence: 80% is the current '
                 'value and HSC reserves the right to move it. The IM ratio '
                 'is worded identically. ' + src),
        'target': _c(
            Coverage.CONTRADICTORY, 'the coverage a remedy restores to',
            SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
            gap=GapKind.G14_SOURCE_SELF_CONTRADICTORY,
            quote='phải ký quỹ bổ sung hoặc đóng bớt vị thế để đưa trạng tài '
                  'khoản tối thiểu về ngưỡng “Ký quỹ duy trì”',
            defect='HSC states its own target three times and two of the '
                   'three disagree with the band table. The table (quoted) '
                   'says restore to the "Ky quy duy tri" band, R >= 80%. But '
                   '"Ky quy bo sung" is defined as "Muc ky quy ban dau - So '
                   'du ky quy", a top-up to R = 100%; and "Xu ly cac tai '
                   'khoan vi pham ky quy" requires the account "toi thieu ve '
                   'trang thai Binh thuong (Normal) truoc 11:30 ngay T+1", '
                   'again R >= 100%. On an account at R = 0.70 with 70,000 of '
                   'assets the two readings differ by 17,500 of requirement '
                   '-- 12,500 against 30,000, well over twice. The band table '
                   'is taken as operative because it is the only clause that '
                   'assigns actions to bands; the 100% reading is recorded '
                   'here and NOT applied.',
            note=src),
        'notification': _c(
            Coverage.PUBLISHED, 'duty to notify, with channel and time',
            SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
            gap=GapKind.G16_SOURCE_CLASS_WEAK,
            note='notice from 16:30 T by SMS and email -- the only complete '
                 'channel-and-time statement in the survey. ' + src),
        'cure_window': _c(
            Coverage.PUBLISHED, 'cure to Normal by 11:30 T+1',
            SourceClass.HELP_PAGE, url=_HSC_URL, eff=date(2020, 4, 15),
            quote='Khách hàng cần nộp Ký quỹ bổ sung vào tài khoản hoặc đóng '
                  'bớt vị thế để đưa tài khoản tối thiểu về trạng thái Bình '
                  'thường (Normal) trước 11:30 ngày T+1',
            note='the only complete notice-cure-liquidate timeline in the '
                 'pool: 16:30 T / 11:30 T+1 / 13:00 T+1. Note that this '
                 'sentence is ALSO the second of the two clauses that put '
                 'HSC\'s target at Normal (R >= 100%) rather than at the '
                 'maintenance band -- see the "target" entry\'s source '
                 'defect. The contradiction is not confined to one field. '
                 + src),
    }
    return BrokerProfile(
        firm='HSC', is_synthesis=False, regime=Regime.PRE_KRX,
        document_date=date(2020, 4, 15),
        margin_model_intraday=MarginModel.IM_ONLY_WITH_MM,
        margin_model_overnight=MarginModel.UNSTATED,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.FALLING_COVERAGE,
        denominator=DenominatorSpec(DenominatorBasis.INITIAL_MARGIN,
                                    LiabilitiesTreatment.UNPUBLISHED),
        ladder=ladder, coverage=cov,
        initial_margin_ratio=Decimal('0.17'),
        maintenance_margin_fraction=Decimal('0.80'),
        description='The only falling-coverage firm, the only IM/MM model, '
                    'the only complete timeline -- on a 2020 page.',
    )


# -- Tier B: structure-only profiles ----------------------------------------
#
# These ship because they are the exemplars of the gap kinds. Their numbers
# are absent by the firm's own choice, and this module refuses to invent them:
# constructing one without ``fill_from`` raises.

_MBS_URL = 'https://mbs.com.vn/files/uploads/2026/06/TC-phai-sinh_2025-2.pdf'


def _mbs() -> BrokerProfile:
    """MBS -- five named ratios, five delegations, and notice as a right.

    *"AR = (MR / V_KQ) x 100%"* with ``V_KQ`` composed per its own section
    1.24, ``MR = IM + VM + DM`` *"cap nhat lien tuc trong phien"*, and every
    one of its five ratios deferred: *"do MBS quy dinh tung thoi ky"*. It is
    the cleanest possible statement of ``numbers_published = False``.

    Its notification clause is the other exemplar: Dieu 4.2(a), *"MBS co quyen
    nhung khong co nghia vu gui thong bao"* -- a right, not a duty. A model
    that inserts a mandatory notice here gives the account time the contract
    does not.

    The instrument was **issued under QD 18/2019/MBS ngay 02/07/2019**, six
    years before the KRX cutover, and republished at a 2026/06 URL. The URL is
    not the date.
    """
    delegated = _c(Coverage.DELEGATED, 'a named ratio with no value',
                   SourceClass.SIGNED_TC, url=_MBS_URL,
                   gap=GapKind.G1_DELEGATED,
                   quote='do MBS quy định từng thời kỳ',
                   note='MBS sections 1.28-1.32')
    ladder = (
        Rung(coverage_key='margin_call_level', name='AR duy tri', level=None,
             action=Action.NOTIFY, target_ref=TargetRef.UNRESOLVED,
             notice=Notice.RIGHT_NOT_DUTY,
             cure=CureSpec(CureKind.DELEGATED)),
        Rung(coverage_key='forced_close_level', name='AR xu ly', level=None,
             action=Action.LIQUIDATE, target_ref=TargetRef.RUNG_1,
             notice=Notice.RIGHT_NOT_DUTY, cure=_IMMEDIATE),
        Rung(coverage_key='ccp_processing_level',
             name='Nguong xu ly tai VSDC', level=None, action=Action.LIQUIDATE,
             target_ref=TargetRef.UNRESOLVED, notice=Notice.RIGHT_NOT_DUTY,
             cure=_IMMEDIATE),
    )
    caps = (
        Cap(coverage_key='post_open_level', name='Ty le sau mo vi the',
            level=None, description='max AR permitted after opening'),
        Cap(coverage_key='post_withdrawal_level', name='Ty le sau rut',
            level=None, description='max AR permitted after a withdrawal'),
    )
    cov = {
        'direction': _c(Coverage.PUBLISHED, 'AR = (MR / V_KQ) x 100%, rising',
                        SourceClass.SIGNED_TC, url=_MBS_URL),
        'denominator': _c(Coverage.PUBLISHED, 'V_KQ per MBS section 1.24',
                          SourceClass.SIGNED_TC, url=_MBS_URL,
                          note='cash + securities at VSD haircuts'),
        'liabilities_treatment': _c(
            Coverage.PUBLISHED, 'debts not subtracted', SourceClass.SIGNED_TC,
            url=_MBS_URL),
        'margin_model_intraday': _c(
            Coverage.PUBLISHED, 'MR = IM + VM + DM, continuous',
            SourceClass.SIGNED_TC, url=_MBS_URL,
            quote='Công thức tính MR = IM + VM + DM',
            note='MBS sections 1.22-1.23; "được cập nhật liên tục trong phiên '
                 'giao dịch"'),
        'margin_model_overnight': _c(
            Coverage.UNPUBLISHED, 'formula for the CCP submission',
            SourceClass.SIGNED_TC, url=_MBS_URL,
            gap=GapKind.G10_MODEL_NOT_STATED,
            note='section 1.30 forward-references a VSDC threshold "theo cong '
                 'bo cua VSDC tung thoi ky", which QD 26 Dieu 13 satisfies '
                 'with no ladder at all -- research conflict C-3'),
        'initial_margin_ratio': _c(
            Coverage.DELEGATED, 'the broker initial margin ratio',
            SourceClass.SIGNED_TC, url=_MBS_URL, gap=GapKind.G1_DELEGATED),
        'margin_call_level': delegated,
        'forced_close_level': delegated,
        'ccp_processing_level': delegated,
        'post_open_level': delegated,
        'post_withdrawal_level': delegated,
        'target': _c(Coverage.DELEGATED, 'restore to AR duy tri',
                     SourceClass.SIGNED_TC, url=_MBS_URL,
                     gap=GapKind.G6_TARGET_UNRESOLVED,
                     quote='để đảm bảo AR duy trì',
                     note='level-targeting IS stated; the level it names is '
                          'itself delegated'),
        'notification': _c(
            Coverage.DISCLAIMED, 'duty to notify', SourceClass.SIGNED_TC,
            url=_MBS_URL, gap=GapKind.G7_NOTICE_DISCLAIMED,
            quote='MBS có quyền nhưng không có nghĩa vụ gửi thông báo',
            note='Dieu 4.2(a). A right, not a duty: a mandatory notice step '
                 'here over-states survival'),
        'cure_window': _c(Coverage.DELEGATED, 'time allowed to answer',
                          SourceClass.SIGNED_TC, url=_MBS_URL,
                          gap=GapKind.G9_CURE_DELEGATED,
                          note='Dieu 4.2(b)'),
    }
    return BrokerProfile(
        firm='MBS', is_synthesis=False, regime=Regime.PRE_KRX,
        document_date=date(2019, 7, 2),
        margin_model_intraday=MarginModel.IM_PLUS_VM_PLUS_DM,
        margin_model_overnight=MarginModel.UNSTATED,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=_VKQ_IGNORED, ladder=ladder, caps=caps, coverage=cov,
        description='Exemplar of numbers_published = False, and of notice as '
                    'a right rather than a duty.',
    )


_KIS_SRC = ('KIS, Bo dieu khoan va dieu kien cua Hop dong mo tai khoan, '
            'snapshot kis_1.2026_Dieu-khoan-va-dieu-kien-Final-1.pdf; the file '
            'is named 1.2026 and its own header reads "KIS_HDMTK_Ver 2022"')


def _kis() -> BrokerProfile:
    """KIS -- notification disclaimed in both directions.

    Dieu 5.1: *"KIS khong co trach nhiem thong bao"* at level 1. Dieu 5.3:
    *"khong can co bat ky thong bao truoc"* at level 3. Between them, Dieu
    5.2's cure window is *"trong thoi han theo yeu cau cua KIS tai tung thoi
    diem"* -- the window exists and its length is KIS's discretion.

    So KIS's liquidation path has **no notice step and no cure step**, and
    :func:`notice_steps_before_liquidation` returns 0 for it against at least
    1 for SSI. That difference is measurable in a survival rate and is the
    reason axis 4 is a field rather than an assumption.

    The file is named ``1.2026`` and its own text is stamped
    ``KIS_HDMTK_Ver 2022``. Gap kind ``G13``.
    """
    delegated = _c(Coverage.DELEGATED, 'a named level with no percentage',
                   SourceClass.SIGNED_TC, gap=GapKind.G1_DELEGATED,
                   note='KIS Dieu 5 names three levels and prints zero '
                        'percentages; snapshot kis_1.2026_Dieu-khoan-va-dieu-'
                        'kien-Final-1.pdf')
    ladder = (
        Rung(coverage_key='block_open_level', name='Canh bao muc do 1',
             level=None, action=Action.BLOCK_OPENING,
             target_ref=TargetRef.NONE, notice=Notice.DISCLAIMED,
             cure=_UNKNOWN_CURE),
        Rung(coverage_key='margin_call_level', name='Canh bao muc do 2',
             level=None, action=Action.NOTIFY, target_ref=TargetRef.RUNG_1,
             notice=Notice.DISCLAIMED, cure=CureSpec(CureKind.DELEGATED)),
        Rung(coverage_key='forced_close_level', name='Canh bao muc do 3',
             level=None, action=Action.LIQUIDATE,
             target_ref=TargetRef.UNRESOLVED, notice=Notice.DISCLAIMED,
             cure=_IMMEDIATE),
    )
    cov = {
        'direction': _c(Coverage.PUBLISHED,
                        'Ty le su dung tai san ky quy, rising',
                        SourceClass.SIGNED_TC, note='KIS section 1.9'),
        'denominator': _c(
            Coverage.PUBLISHED, 'V_KQ per KIS section 1.8',
            SourceClass.SIGNED_TC, note=_KIS_SRC,
            quote='số dư tiền gửi ký quỹ + danh mục CKKQ theo giá thị trường '
                  'và tỷ lệ chiết khấu theo quy chế VSD và quy định KIS'),
        'liabilities_treatment': _c(Coverage.PUBLISHED, 'debts not subtracted',
                                    SourceClass.SIGNED_TC, note=_KIS_SRC),
        'margin_model_intraday': _c(Coverage.PUBLISHED,
                                    'MR = IM + VM + DM, per KIS section 1.7',
                                    SourceClass.SIGNED_TC, note=_KIS_SRC),
        'margin_model_overnight': _c(
            Coverage.UNPUBLISHED, 'formula for the CCP submission',
            SourceClass.SIGNED_TC, gap=GapKind.G10_MODEL_NOT_STATED,
            note='section 1.7 says "VSD and/or KIS" without separating them'),
        'initial_margin_ratio': _c(
            Coverage.DELEGATED, 'the broker initial margin ratio',
            SourceClass.SIGNED_TC, gap=GapKind.G1_DELEGATED, note=_KIS_SRC),
        'block_open_level': delegated,
        'margin_call_level': delegated,
        'forced_close_level': delegated,
        'target': _c(Coverage.DELEGATED, 'restore below level 1',
                     SourceClass.SIGNED_TC, gap=GapKind.G6_TARGET_UNRESOLVED,
                     quote='về dưới mức Cảnh báo mức độ 1', note=_KIS_SRC),
        'notification': _c(
            Coverage.DISCLAIMED, 'duty to notify', SourceClass.SIGNED_TC,
            gap=GapKind.G7_NOTICE_DISCLAIMED,
            quote='KIS không có trách nhiệm thông báo',
            note='Dieu 5.1 disclaims it at level 1; Dieu 5.3 disclaims prior '
                 'notice at level 3 ("khong can co bat ky thong bao truoc"). '
                 'Disclaimed in both directions, which no other firm does'),
        'cure_window': _c(
            Coverage.DELEGATED, 'time allowed to answer',
            SourceClass.SIGNED_TC, gap=GapKind.G9_CURE_DELEGATED,
            quote='trong thời hạn theo yêu cầu của KIS tại từng thời điểm',
            note='Dieu 5.2. ' + _KIS_SRC),
    }
    return BrokerProfile(
        firm='KIS', is_synthesis=False, regime=Regime.PRE_KRX,
        document_date=date(2022, 1, 1),
        margin_model_intraday=MarginModel.IM_PLUS_VM_PLUS_DM,
        margin_model_overnight=MarginModel.UNSTATED,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=_VKQ_IGNORED, ladder=ladder, coverage=cov,
        description='Exemplar of notification disclaimed in both directions '
                    'and of a delegated cure window.',
    )


_VPS_SRC = ('VPS, Bo dieu khoan va dieu kien cua Hop dong mo tai khoan chung '
            'khoan, edition 05/2025, snapshot vps_bo-dieu-khoan-va-dieu-kien-'
            'cua-hop-dong-mo-tai-khoan-chung-khoan-viet-nam-052025-30f5.pdf')


def _vps() -> BrokerProfile:
    """VPS -- a firm that contradicts itself about its own ratio's direction.

    Section 1.13 calls *"Ty le su dung tai san ky quy duy tri"* a **minimum**
    the client must maintain; Part E section 4.4(c) requires remedies that
    force the ratio **below** it. If 1.13 were operative, 4.4(c)'s remedy
    would itself be a breach. The bilingual text repeats the error in English,
    so it is not a translation slip. Research conflict C-4, gap kind ``G14``.

    The direction is set from 4.4(c) because that is the operative remedy
    clause and because every other firm treats utilisation as a ceiling --
    **but that is our reading of a defective contract, and it is recorded as
    a source defect rather than silently repaired.** VPS therefore ships
    ``enabled_by_default = False``.

    VPS also carries a ratio no ladder shape can hold: *"Ty le an toan"*
    (section 1.14), *"ty le do VPS xac dinh dua tren gia tri tai san rong"*,
    made a warning dimension in its own right by section 1.19, with **its
    formula unpublished**. It lives in :attr:`BrokerProfile.additional_ratios`
    rather than being forced into the ladder.
    """
    delegated = _c(Coverage.DELEGATED, 'a named ratio with no value',
                   SourceClass.SIGNED_TC, gap=GapKind.G1_DELEGATED,
                   note='VPS section 1.19; T&C edition 05/2025')
    ladder = (
        Rung(coverage_key='block_open_level', name='Nguong canh bao 1',
             level=None, action=Action.BLOCK_OPENING,
             target_ref=TargetRef.NONE, notice=Notice.RIGHT_NOT_DUTY,
             cure=_UNKNOWN_CURE),
        Rung(coverage_key='margin_call_level',
             name='Ty le su dung tai san ky quy duy tri', level=None,
             action=Action.NOTIFY, target_ref=TargetRef.RUNG_2,
             notice=Notice.RIGHT_NOT_DUTY, cure=CureSpec(CureKind.DELEGATED)),
        Rung(coverage_key='forced_close_level', name='Nguong xu ly',
             level=None, action=Action.LIQUIDATE, target_ref=TargetRef.RUNG_2,
             notice=Notice.RIGHT_NOT_DUTY, cure=_IMMEDIATE),
    )
    cov = {
        'direction': _c(
            Coverage.CONTRADICTORY, 'sign of the maintenance ratio',
            SourceClass.SIGNED_TC, gap=GapKind.G14_SOURCE_SELF_CONTRADICTORY,
            quote='tất cả các biện pháp cần thiết khác để đảm bảo tỷ lệ sử '
                  'dụng tài sản ký quỹ thấp hơn tỷ lệ ký quỹ duy trì',
            defect='VPS section 1.13 calls the maintenance utilisation ratio '
                   'a MINIMUM the client must maintain ("ty le toi thieu ... '
                   'ma Khach hang can duy tri"); Part E section 4.4(c) '
                   'requires remedies that force it BELOW that ratio. Under '
                   '1.13 the 4.4(c) remedy would itself be a breach. The '
                   'bilingual text repeats the error in English. Direction is '
                   'taken from 4.4(c) -- OURS, and it is a reading of a '
                   'defective contract, not a repair of it.',
            note=_VPS_SRC),
        'denominator': _c(
            Coverage.PUBLISHED, 'MR / tong gia tri tai san ky quy hop le',
            SourceClass.SIGNED_TC, note='VPS section 1.12'),
        'liabilities_treatment': _c(Coverage.PUBLISHED, 'debts not subtracted',
                                    SourceClass.SIGNED_TC, note=_VPS_SRC),
        'margin_model_intraday': _c(Coverage.PUBLISHED,
                                    'MR per VPS section 1.12',
                                    SourceClass.SIGNED_TC, note=_VPS_SRC),
        'margin_model_overnight': _c(
            Coverage.UNPUBLISHED, 'formula for the CCP submission',
            SourceClass.SIGNED_TC, gap=GapKind.G10_MODEL_NOT_STATED,
            note=_VPS_SRC),
        'initial_margin_ratio': _c(
            Coverage.DELEGATED, 'the broker initial margin ratio',
            SourceClass.SIGNED_TC, gap=GapKind.G1_DELEGATED, note=_VPS_SRC),
        'block_open_level': delegated,
        'margin_call_level': delegated,
        'forced_close_level': delegated,
        'target': _c(Coverage.DELEGATED, 'restore below the maintenance ratio',
                     SourceClass.SIGNED_TC, gap=GapKind.G6_TARGET_UNRESOLVED,
                     note='per section 4.4(c) only'),
        'notification': _c(
            Coverage.DISCLAIMED, 'duty to notify', SourceClass.SIGNED_TC,
            gap=GapKind.G7_NOTICE_DISCLAIMED,
            quote='VPS có quyền (nhưng không có nghĩa vụ) gửi thông báo lệnh '
                  'gọi ký quỹ bổ sung',
            note='Part E section 4.4(b)'),
        'cure_window': _c(Coverage.DELEGATED, 'time allowed to answer',
                          SourceClass.SIGNED_TC,
                          gap=GapKind.G9_CURE_DELEGATED, note=_VPS_SRC),
        'safety_ratio': _c(
            Coverage.UNPUBLISHED, 'Ty le an toan -- formula',
            SourceClass.SIGNED_TC, gap=GapKind.G10_MODEL_NOT_STATED,
            quote='là tỷ lệ do VPS xác định dựa trên giá trị tài sản ròng của '
                  'Khách hàng',
            note='section 1.14 defines it and section 1.19 makes it a warning '
                 'dimension in its own right; its formula is not published. '
                 'Neither a utilisation nor a coverage ratio -- see '
                 'additional_ratios'),
    }
    return BrokerProfile(
        firm='VPS', is_synthesis=False, regime=Regime.POST_KRX,
        document_date=date(2025, 5, 1),
        margin_model_intraday=MarginModel.IM_PLUS_VM_PLUS_DM,
        margin_model_overnight=MarginModel.UNSTATED,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=_VKQ_IGNORED, ladder=ladder, coverage=cov,
        additional_ratios=(
            NamedRatio(name='Ty le an toan', numerator='unpublished',
                       denominator='gia tri tai san rong cua Khach hang',
                       formula_published=False,
                       note='VPS section 1.14, made a warning-threshold '
                            'dimension by section 1.19. A config expressing '
                            'only rising utilisation and falling coverage '
                            'cannot represent it, so it is not forced into '
                            'the ladder'),),
        enabled_by_default=False,
        description='Exemplar of a source defect on the direction axis, and '
                    'of a ratio no ladder shape can hold. Disabled by '
                    'default.',
    )


def _pinetree(*, vintage_2024: bool = False) -> BrokerProfile:
    """Pinetree -- two undated vintages, shipped as two rows.

    The live page gives 80 / 90 / 95 targeting at-or-below 80; a page dated
    2024-07-11 gives 75 / 85 / 90 targeting below 75. **No source dates the
    change**, so the older row is marked superseded and kept rather than
    overwritten -- the repo action recorded at section 4.4 of the research.

    Pinetree also inverts its own inequality (research conflict C-6) and
    publishes a *buying-power* formula, ``IM = (Ty le IM / Ty le an toan) x M
    x n x P``, which is not an ``MR`` at all. Both are recorded; neither is
    repaired.

    Tagged CARRIED: the live page was Cloudflare-blocked this session.
    """
    levels = ((Decimal('0.75'), Decimal('0.85'), Decimal('0.90'))
              if vintage_2024
              else (Decimal('0.80'), Decimal('0.90'), Decimal('0.95')))
    who = 'Pinetree_2024' if vintage_2024 else 'Pinetree'
    eff = date(2024, 7, 11) if vintage_2024 else None
    src = ('page dated 2024-07-11, superseded by the live page on an unknown '
           'date' if vintage_2024
           else 'live page; Cloudflare-blocked this session, so CARRIED')
    ladder = (
        Rung(coverage_key='block_open_level', name='Muc 1', level=levels[0],
             action=Action.BLOCK_OPENING, target_ref=TargetRef.NONE,
             notice=Notice.UNKNOWN, cure=_UNKNOWN_CURE),
        Rung(coverage_key='margin_call_level', name='Muc 2', level=levels[1],
             action=Action.NOTIFY, target_ref=TargetRef.RUNG_1,
             notice=Notice.UNKNOWN, cure=_UNKNOWN_CURE),
        Rung(coverage_key='forced_close_level', name='Muc 3', level=levels[2],
             action=Action.LIQUIDATE, target_ref=TargetRef.RUNG_1,
             notice=Notice.UNKNOWN, cure=_IMMEDIATE),
    )
    stale = Coverage.PUBLISHED_STALE if vintage_2024 else Coverage.PUBLISHED
    gap = GapKind.G12_PARAMETER_VINTAGE if vintage_2024 else None
    cov = {
        'direction': _c(Coverage.PUBLISHED, 'sign of the ladder ratio',
                        SourceClass.SECONDARY, eff=eff, note=src),
        'denominator': _c(Coverage.UNPUBLISHED, 'divisor of the ratio',
                          SourceClass.SECONDARY,
                          gap=GapKind.G3_DENOMINATOR_UNDEFINED, note=src),
        'liabilities_treatment': _c(
            Coverage.UNPUBLISHED, 'where client debts enter the ratio',
            SourceClass.SECONDARY, gap=GapKind.G3_DENOMINATOR_UNDEFINED,
            note=src),
        'margin_model_intraday': _c(
            Coverage.UNPUBLISHED, 'formula behind the ladder numerator',
            SourceClass.SECONDARY, gap=GapKind.G10_MODEL_NOT_STATED,
            note='Pinetree publishes IM = (Ty le IM / Ty le an toan) x M x n '
                 'x P, which is a BUYING-POWER formula, not an MR. ' + src),
        'margin_model_overnight': _c(
            Coverage.UNPUBLISHED, 'formula for the CCP submission',
            SourceClass.SECONDARY, gap=GapKind.G10_MODEL_NOT_STATED, note=src),
        'initial_margin_ratio': _c(
            Coverage.UNPUBLISHED, 'the broker initial margin ratio',
            SourceClass.SECONDARY, gap=GapKind.G10_MODEL_NOT_STATED, note=src),
        'block_open_level': _c(stale, f'Muc 1, {levels[0]}',
                               SourceClass.SECONDARY, eff=eff, gap=gap,
                               note=src),
        'margin_call_level': _c(stale, f'Muc 2, {levels[1]}',
                                SourceClass.SECONDARY, eff=eff, gap=gap,
                                note=src),
        'forced_close_level': _c(
            stale, f'Muc 3, {levels[2]}', SourceClass.SECONDARY, eff=eff,
            gap=gap,
            note='Pinetree inverts its own inequality when stating this rung '
                 '-- research conflict C-6, recorded not repaired. ' + src),
        'target': _c(Coverage.PUBLISHED, 'restore to rung 1',
                     SourceClass.SECONDARY, eff=eff, note=src),
        'notification': _c(Coverage.UNPUBLISHED, 'duty to notify',
                           SourceClass.SECONDARY,
                           gap=GapKind.G8_NOTICE_UNKNOWN, note=src),
        'cure_window': _c(Coverage.UNPUBLISHED, 'time allowed to answer',
                          SourceClass.SECONDARY,
                          gap=GapKind.G8_NOTICE_UNKNOWN, note=src),
    }
    return BrokerProfile(
        firm=who, is_synthesis=False,
        regime=Regime.PRE_KRX if vintage_2024 else Regime.UNKNOWN,
        document_date=eff,
        margin_model_intraday=MarginModel.UNSTATED,
        margin_model_overnight=MarginModel.UNSTATED,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(DenominatorBasis.UNPUBLISHED,
                                    LiabilitiesTreatment.UNPUBLISHED),
        ladder=ladder, coverage=cov,
        superseded_by='Pinetree' if vintage_2024 else None,
        supersedes='Pinetree_2024' if not vintage_2024 else None,
        description='Exemplar of two undated vintages, shipped as two rows.',
    )


def _dnse() -> BrokerProfile:
    """DNSE -- one real number and nothing else.

    ``IM = 18.48%`` appears inside a worked example on its KRX FAQ. There is
    **no ladder, no model, no denominator and no action semantics**, so DNSE
    is the exemplar of partial coverage: a profile that is genuinely sourced
    on exactly one field and unpublished on every other.
    """
    src = 'DNSE KRX FAQ (dnse_llms.txt in the survey scratchpad)'
    unpub = lambda q: _c(Coverage.UNPUBLISHED, q, SourceClass.HELP_PAGE,
                         note=src)
    cov = {
        'direction': unpub('sign of the ladder ratio'),
        'denominator': _c(Coverage.UNPUBLISHED, 'divisor of the ratio',
                          SourceClass.HELP_PAGE,
                          gap=GapKind.G3_DENOMINATOR_UNDEFINED, note=src),
        'liabilities_treatment': _c(
            Coverage.UNPUBLISHED, 'where client debts enter the ratio',
            SourceClass.HELP_PAGE, gap=GapKind.G3_DENOMINATOR_UNDEFINED,
            note=src),
        'margin_model_intraday': _c(
            Coverage.UNPUBLISHED, 'formula behind the client MR',
            SourceClass.HELP_PAGE, gap=GapKind.G10_MODEL_NOT_STATED, note=src),
        'margin_model_overnight': _c(
            Coverage.UNPUBLISHED, 'formula for the CCP submission',
            SourceClass.HELP_PAGE, gap=GapKind.G10_MODEL_NOT_STATED, note=src),
        'initial_margin_ratio': _c(
            Coverage.PUBLISHED, 'the broker\'s own initial margin ratio',
            SourceClass.HELP_PAGE,
            note='18.48%, published inside a worked example -- the one real '
                 'number DNSE gives. ' + src),
        'forced_close_level': _c(
            Coverage.UNPUBLISHED, 'the level at which DNSE closes for you',
            SourceClass.HELP_PAGE, gap=GapKind.G5_ACTION_UNKNOWN,
            note='DNSE publishes no ladder at all. This is UNPUBLISHED, not '
                 'INAPPLICABLE: unlike ACBS, nothing says DNSE has no ladder. '
                 + src),
        'target': _c(Coverage.UNPUBLISHED, 'fire-vs-target',
                     SourceClass.HELP_PAGE, gap=GapKind.G5_ACTION_UNKNOWN,
                     note=src),
        'notification': _c(Coverage.UNPUBLISHED, 'duty to notify',
                           SourceClass.HELP_PAGE,
                           gap=GapKind.G8_NOTICE_UNKNOWN, note=src),
        'cure_window': _c(Coverage.UNPUBLISHED, 'time allowed to answer',
                          SourceClass.HELP_PAGE,
                          gap=GapKind.G8_NOTICE_UNKNOWN, note=src),
    }
    return BrokerProfile(
        firm='DNSE', is_synthesis=False, regime=Regime.POST_KRX,
        document_date=None,
        margin_model_intraday=MarginModel.UNSTATED,
        margin_model_overnight=MarginModel.UNSTATED,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(DenominatorBasis.UNPUBLISHED,
                                    LiabilitiesTreatment.UNPUBLISHED),
        ladder=(), coverage=cov,
        initial_margin_ratio=Decimal('0.1848'),
        description='Exemplar of partial coverage: one sourced number, '
                    'nothing else.',
    )


_VCBS_URL = ('https://www.vcbs.com.vn/chi-tiet-cong-bo-thong-tin/'
             'thong-bao-thay-doi-quy-dinh-san-pham-chung-khoan-phai-sinh-tai-vcbs')


def _vcbs() -> BrokerProfile:
    """VCBS -- shipped, and **not** as a ladder profile.

    *"Ty le ky quy toi thieu bang tien: 100%"*, while its own ratio formula
    adds a *"Gia tri CKKQ hop le tang DTA"* term to the denominator. Cash-only
    and cash-plus-securities cannot both be the divisor. VCBS publishes **no
    rungs**, so shipping it as a ladder would mean shipping a contradiction as
    a policy.

    Its 100% is a collateral **eligibility** rule and must not be merged with
    QD 26 Dieu 8's ``x = 80%`` cap or ACBS's 5% reserve -- defect ``D-28``,
    gap kind ``G18``.
    """
    cov = {
        'direction': _c(Coverage.PUBLISHED, 'rising utilisation',
                        SourceClass.SECONDARY, url=_VCBS_URL),
        'denominator': _c(
            Coverage.CONTRADICTORY, 'divisor of the ratio',
            SourceClass.SECONDARY, url=_VCBS_URL,
            gap=GapKind.G14_SOURCE_SELF_CONTRADICTORY,
            quote='Tỷ lệ ký quỹ tối thiểu bằng tiền: 100%',
            defect='VCBS states a 100% cash minimum for margin assets while '
                   'its own ratio formula adds a DTA-tier securities term to '
                   'the same denominator. Cash-only and cash-plus-securities '
                   'cannot both be the divisor. Not repaired: we do not fix a '
                   'counterparty\'s contract.'),
        'liabilities_treatment': _c(
            Coverage.UNPUBLISHED, 'where client debts enter the ratio',
            SourceClass.SECONDARY, url=_VCBS_URL, gap=GapKind.G3_DENOMINATOR_UNDEFINED),
        'margin_model_intraday': _c(
            Coverage.UNPUBLISHED, 'formula behind the client MR',
            SourceClass.SECONDARY, url=_VCBS_URL, gap=GapKind.G10_MODEL_NOT_STATED),
        'margin_model_overnight': _c(
            Coverage.UNPUBLISHED, 'formula for the CCP submission',
            SourceClass.SECONDARY, url=_VCBS_URL, gap=GapKind.G10_MODEL_NOT_STATED),
        'initial_margin_ratio': _c(
            Coverage.UNPUBLISHED, 'the broker initial margin ratio',
            SourceClass.SECONDARY, url=_VCBS_URL, gap=GapKind.G10_MODEL_NOT_STATED),
        'forced_close_level': _c(
            Coverage.UNPUBLISHED, 'the level at which VCBS closes for you',
            SourceClass.SECONDARY, url=_VCBS_URL, gap=GapKind.G5_ACTION_UNKNOWN,
            note='VCBS publishes no rungs'),
        'target': _c(Coverage.UNPUBLISHED, 'fire-vs-target',
                     SourceClass.SECONDARY, url=_VCBS_URL, gap=GapKind.G5_ACTION_UNKNOWN),
        'notification': _c(Coverage.UNPUBLISHED, 'duty to notify',
                           SourceClass.SECONDARY, url=_VCBS_URL,
                           gap=GapKind.G8_NOTICE_UNKNOWN),
        'cure_window': _c(Coverage.UNPUBLISHED, 'time allowed to answer',
                          SourceClass.SECONDARY, url=_VCBS_URL,
                          gap=GapKind.G8_NOTICE_UNKNOWN),
        'minimum_cash_share': _c(
            Coverage.CONTRADICTORY, 'minimum cash share of margin assets',
            SourceClass.SECONDARY, url=_VCBS_URL,
            gap=GapKind.G18_HOMONYM,
            defect='the 100% is a collateral ELIGIBILITY rule and is '
                   'contradicted by VCBS\'s own DTA-tier term. It is not QD '
                   '26 Dieu 8\'s x = 80% collateral cap and not ACBS\'s 5% '
                   'fee reserve -- three concepts under similar names, defect '
                   'D-28.'),
    }
    return BrokerProfile(
        firm='VCBS', is_synthesis=False, regime=Regime.UNKNOWN,
        document_date=None,
        margin_model_intraday=MarginModel.UNSTATED,
        margin_model_overnight=MarginModel.UNSTATED,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(DenominatorBasis.CASH_ONLY,
                                    LiabilitiesTreatment.UNPUBLISHED,
                                    note='as STATED. As COMPUTED it is '
                                         'V_KQ_PLUS_DTA_TIER -- the two are '
                                         'the contradiction'),
        ladder=(), coverage=cov, enabled_by_default=False,
        description='No rungs, and a denominator that contradicts itself. '
                    'Shipped as a non-ladder profile so the contradiction is '
                    'representable without being applied.',
    )


_ACBS_SRC = ('ACBS, "Quy dinh giao dich Phai sinh", snapshot '
             'setB/acbs_qd.txt in the survey scratchpad; the snapshot '
             'recorded no URL, so none is claimed here')


def _acbs() -> BrokerProfile:
    """ACBS -- **no ladder exists**, and that is not the same as unknown.

    *"Ty le tien giu lai toi thieu tai ACBS la 5%"* is a fee/tax/VM reserve
    that enters buying power as ``x (1 + 5%)``. It reduces the position a
    given balance can open, which changes **when** an account would reach a
    rung, without being a rung.

    Every ladder field is therefore ``INAPPLICABLE``, not ``UNPUBLISHED``. A
    user told that *"ACBS's forced-close level is unknown"* has been misled:
    there is nothing to know. Gap kind ``G15``, and it is the reason
    :class:`Coverage` needs a tenth value.
    """
    na = lambda q: _c(Coverage.INAPPLICABLE, q, SourceClass.SECONDARY,
                      gap=GapKind.G15_INAPPLICABLE,
                      note='ACBS operates no utilisation ladder. ' + _ACBS_SRC)
    cov = {
        'direction': na('sign of a ladder ratio'),
        'denominator': na('divisor of a ladder ratio'),
        'liabilities_treatment': na('liabilities in a ladder ratio'),
        'margin_model_intraday': _c(
            Coverage.UNPUBLISHED, 'formula behind the client MR',
            SourceClass.SECONDARY, gap=GapKind.G10_MODEL_NOT_STATED, note=_ACBS_SRC),
        'margin_model_overnight': _c(
            Coverage.UNPUBLISHED, 'formula for the CCP submission',
            SourceClass.SECONDARY, gap=GapKind.G10_MODEL_NOT_STATED, note=_ACBS_SRC),
        'initial_margin_ratio': _c(
            Coverage.UNPUBLISHED, 'the broker initial margin ratio',
            SourceClass.SECONDARY, gap=GapKind.G10_MODEL_NOT_STATED, note=_ACBS_SRC),
        'forced_close_level': na('the level at which ACBS closes for you'),
        'target': na('fire-vs-target'),
        'notification': na('duty to notify at a rung'),
        'cure_window': na('time allowed to answer a rung'),
        'retained_cash_fraction': _c(
            Coverage.PUBLISHED, 'minimum retained cash, a buying-power reserve',
            SourceClass.SECONDARY,
            gap=GapKind.G18_HOMONYM,
            quote='Tỷ lệ tiền giữ lại tối thiểu tại ACBS là 5%',
            note='NOT a rung and NOT a collateral cap. It multiplies buying '
                 'power by 1/(1 + 5%). Merging it with QD 26 Dieu 8\'s x = '
                 '80% or VCBS\'s 100% is defect D-28. ' + _ACBS_SRC),
    }
    return BrokerProfile(
        firm='ACBS', is_synthesis=False, regime=Regime.UNKNOWN,
        document_date=None,
        margin_model_intraday=MarginModel.UNSTATED,
        margin_model_overnight=MarginModel.UNSTATED,
        user_facing_model=MarginLayer.INTRADAY,
        direction=Direction.RISING_UTILISATION,
        denominator=DenominatorSpec(DenominatorBasis.UNPUBLISHED,
                                    LiabilitiesTreatment.UNPUBLISHED),
        ladder=(), coverage=cov,
        buying_power=BuyingPowerSpec(
            retained_cash_fraction=Decimal('0.05'),
            description='fee/tax/VM reserve; buying power is cash / (1 + 5%)'),
        enabled_by_default=False,
        description='No ladder at all. The exemplar of INAPPLICABLE.',
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

#: The default profile. A synthesis, and it says so on every use.
#:
#: Built at import time because it is the source every ``fill_from`` reads.
#: It does **not** warn here: a warning raised during import carries a
#: stacklevel pointing at this module, which tells a caller nothing and cannot
#: be filtered per call site. :func:`get_profile` warns instead, where the
#: caller is.
PLUTUS_DEFAULT = _plutus_default()

DEFAULT_PROFILE_NAME = 'PLUTUS_DEFAULT'

_BUILDERS: Mapping[str, Callable[[], BrokerProfile]] = MappingProxyType({
    'PLUTUS_DEFAULT': lambda: PLUTUS_DEFAULT,
    'TCBS': _tcbs,
    'SSI': _ssi,
    'SSI_FOREIGN': lambda: _ssi(foreign=True),
    'SSI_2025_09': lambda: _ssi(vintage_2025_09=True),
    'VNDIRECT': _vndirect,
    'FPTS': _fpts,
    'SHS': _shs,
    'Vietcap': _vietcap,
    'HSC': _hsc,
    'MBS': _mbs,
    'KIS': _kis,
    'VPS': _vps,
    'Pinetree': _pinetree,
    'Pinetree_2024': lambda: _pinetree(vintage_2024=True),
    'DNSE': _dnse,
    'VCBS': _vcbs,
    'ACBS': _acbs,
})

#: Every shipped profile name, in survey order.
PROFILE_NAMES: Tuple[str, ...] = tuple(_BUILDERS)

#: Profiles safe to reach for without a deliberate decision. VPS is excluded
#: because its direction rests on a source defect; VCBS because its
#: denominator contradicts itself; ACBS because it has no ladder to run.
ENABLED_BY_DEFAULT: frozenset = frozenset(
    name for name in _BUILDERS
    if _BUILDERS[name]().enabled_by_default)


def list_profiles() -> Tuple[Tuple[str, bool, str], ...]:
    """``(firm, enabled_by_default, description)`` for every shipped profile."""
    out = []
    for name in PROFILE_NAMES:
        profile = _BUILDERS[name]()
        out.append((name, profile.enabled_by_default, profile.description))
    return tuple(out)


def get_profile(firm: str = DEFAULT_PROFILE_NAME, *,
                fill_from: Optional[BrokerProfile] = None,
                warn: bool = True) -> BrokerProfile:
    """The one way to reach a shipped profile, and the point where it warns.

    Args:
        firm: a name from :data:`PROFILE_NAMES`. Defaults to
            ``PLUTUS_DEFAULT`` -- the *default* default, an explicit construct
            that warns it is one, rather than one firm's commercial policy
            quietly standing in for the Vietnamese standard.
        fill_from: a profile to supply blocking levels from, normally
            :data:`PLUTUS_DEFAULT`. **Must be passed deliberately.** Without
            it, a firm that delegates its ladder raises rather than silently
            inheriting somebody else's numbers.
        warn: set ``False`` only when the caller has already surfaced the
            coverage some other way. It suppresses the warnings, never the
            gaps: :meth:`BrokerProfile.gaps` and
            :meth:`BrokerProfile.material_caveats` are unaffected, and the
            caveats still land on every :class:`LadderAssessment`.

    Raises:
        KeyError: on an unknown firm, listing what is available.
        CoverageError: when the profile has a BLOCKING gap and ``fill_from``
            was not supplied.

    A profile with no gaps emits nothing at all. That silence is the
    guarantee: it means fully sourced, never "we did not check".
    """
    if firm not in _BUILDERS:
        raise KeyError(
            f'unknown broker profile {firm!r}. Available: '
            f'{", ".join(PROFILE_NAMES)}. Build your own with BrokerProfile '
            'if none of these is the firm you trade through -- an undeclared '
            'field will raise, so the provenance stays yours.')
    profile = _BUILDERS[firm]()
    blocking = profile.blocking_fields()
    if blocking:
        if fill_from is None:
            raise CoverageError(
                f'{firm} delegates {", ".join(blocking)} to a notice that is '
                f'not on its public site, so it cannot produce a number. '
                f'Supply the values yourself, or opt in explicitly with '
                f'get_profile({firm!r}, fill_from=PLUTUS_DEFAULT) -- which '
                f'will mark every filled field as ours, not {firm}\'s. '
                'Defaulting them silently would produce confident, wrong '
                'margin-call incidence.')
        profile = profile.filled_from(fill_from)
    if warn:
        profile.warn()
    return profile


# ---------------------------------------------------------------------------
# Using a profile
# ---------------------------------------------------------------------------


class PathStep(Enum):
    """One step of the route from a breached rung to a closed position."""

    NOTIFY = auto()
    CURE = auto()
    TRANSFER_COLLATERAL = auto()
    LIQUIDATE = auto()


@dataclass(frozen=True)
class LadderAssessment:
    """Where an account sits on one firm's ladder, and what that is worth.

    ``caveats`` is the point of the object. Every MATERIAL gap on the profile
    is stamped here, so a number cannot be lifted out of a notebook and quoted
    clean: the reason it might be wrong travels with it.
    """

    firm: str
    direction: Direction
    ratio: Optional[Decimal]
    rung_index: Optional[int]
    rung: Optional[Rung]
    action: Action
    target_level: Optional[Decimal]
    notice: Notice
    cure: CureSpec
    ccp_breach: bool
    caveats: Tuple[str, ...]

    @property
    def is_breach(self) -> bool:
        """Has any rung been reached?"""
        return self.rung_index is not None

    @property
    def closes_positions(self) -> bool:
        return (self.action.closes_positions
                or (self.rung is not None
                    and self.rung.follow_on is not None
                    and self.rung.follow_on.closes_positions))


def resolve_target(profile: BrokerProfile, rung: Rung) -> Optional[Decimal]:
    """The level ``rung`` restores the ratio to, or ``None``.

    ``None`` means one of two different things and the caller must not merge
    them: ``TargetRef.NONE`` is *fire-once* -- close only enough to clear the
    rung -- while ``TargetRef.UNRESOLVED`` is *we cannot say*.
    :func:`forced_reduction` distinguishes them; this returns the level only.
    """
    if rung.target_ref is TargetRef.ABSOLUTE:
        return rung.target_absolute
    index = rung.target_ref.rung_index
    if index is None:
        return None
    return profile.ladder[index].level


_WARNED: set = set()


def assess(profile: BrokerProfile, *, required: Decimal,
           assets: Decimal, warn_once: bool = True) -> LadderAssessment:
    """Where ``required`` against ``assets`` sits on this firm's ladder.

    Direction is applied through :meth:`Direction.is_at_or_past` at every
    comparison, so a falling-coverage firm needs no special-casing here and a
    caller cannot accidentally test HSC's 60% rung with ``>=``.

    Two boundary cases, decided rather than left to arithmetic and matching
    :func:`plutus.market.session.deposit.margin_status` so the two never
    disagree:

    * **no requirement is not a breach**, whatever the assets;
    * **a requirement with no assets is the severest rung**, not an undefined
      ratio.

    ``ratio`` is ``None`` in both of those cases, because in neither is there
    a finite ratio to report -- ``assets = 0`` makes utilisation unbounded and
    ``required = 0`` makes coverage unbounded. **Never read the severity off
    ``ratio``**: ``None`` is not "fine" and not "doomed", it is "no number".
    :attr:`LadderAssessment.is_breach` and ``rung_index`` are the answer.

    ``warn_once`` emits the profile's coverage warnings the first time this
    process assesses with that profile object, so a caller who built a profile
    directly rather than through :func:`get_profile` still gets them. The
    caveats are stamped on the result either way.
    """
    if warn_once and profile not in _WARNED:
        _WARNED.add(profile)
        profile.warn()
    caveats = profile.material_caveats()
    ccp = profile.ccp_breach.is_breach(required, assets)
    if required <= 0:
        return LadderAssessment(
            firm=profile.firm, direction=profile.direction, ratio=None,
            rung_index=None, rung=None, action=Action.NONE,
            target_level=None, notice=Notice.UNKNOWN,
            cure=_UNKNOWN_CURE, ccp_breach=False, caveats=caveats)
    if assets <= 0:
        worst = len(profile.ladder) - 1 if profile.ladder else None
        rung = profile.ladder[worst] if worst is not None else None
        return LadderAssessment(
            firm=profile.firm, direction=profile.direction, ratio=None,
            rung_index=worst, rung=rung,
            action=rung.action if rung else Action.NONE,
            target_level=resolve_target(profile, rung) if rung else None,
            notice=rung.notice if rung else Notice.UNKNOWN,
            cure=rung.cure if rung else _UNKNOWN_CURE,
            ccp_breach=ccp, caveats=caveats)
    if profile.direction is Direction.RISING_UTILISATION:
        ratio = required / assets
    else:
        ratio = assets / required
    hit = None
    for index, rung in enumerate(profile.ladder):
        if rung.level is None:
            continue
        if profile.direction.is_at_or_past(ratio, rung.level):
            hit = index
    rung = profile.ladder[hit] if hit is not None else None
    return LadderAssessment(
        firm=profile.firm, direction=profile.direction, ratio=ratio,
        rung_index=hit, rung=rung,
        action=rung.action if rung else Action.NONE,
        target_level=resolve_target(profile, rung) if rung else None,
        notice=rung.notice if rung else Notice.UNKNOWN,
        cure=rung.cure if rung else _UNKNOWN_CURE,
        ccp_breach=ccp, caveats=caveats)


def forced_reduction(profile: BrokerProfile, *, required: Decimal,
                     assets: Decimal) -> Decimal:
    """How much requirement must be closed out, in currency. **Axis 3.**

    This is where fire-versus-target stops being a label and becomes a
    quantity. Under rising utilisation with assets held fixed, closing
    positions reduces ``required``:

    * **fire-once** (``TargetRef.NONE``) -- close until the ratio clears the
      rung that fired: ``max(0, required - level x assets)``;
    * **level-targeting** -- close until the ratio reaches the *target*:
      ``max(0, required - target x assets)``.

    With a target better than the rung, the second is strictly larger. On an
    account at 96% utilisation under PLUTUS_DEFAULT (rung 95, target 80) with
    1,000,000d of assets, clearing the rung closes 10,000d of requirement and
    targeting rung 1 closes 160,000d -- sixteen times as much forced selling
    from the same ladder numbers. A ``{warn, call, liquidate}`` triple cannot
    tell those apart, which is why the brief calls a triple insufficient.

    Under falling coverage the algebra flips: coverage is ``assets /
    required``, so restoring it to ``t`` needs ``required <= assets / t``.

    Raises:
        CoverageError: when the firm publishes a rung and no action semantics
            (``TargetRef.UNRESOLVED``). VNDIRECT is the exemplar: guessing
            between fire and target there would invent the whole of the
            forced sale.
    """
    state = assess(profile, required=required, assets=assets, warn_once=False)
    if state.rung is None or state.rung_index is None:
        return Decimal('0')
    rung = state.rung
    if rung.target_ref is TargetRef.UNRESOLVED:
        raise CoverageError(
            f'{profile.firm} publishes the {rung.name} rung and no action '
            'semantics for it, so the quantity of forced selling is not '
            'derivable: clearing the rung and restoring to a target are '
            'different amounts and the firm says which only by not saying. '
            'Supply a target_ref deliberately, or use a profile that '
            'publishes one.')
    if rung.target_ref is TargetRef.NONE:
        level = rung.level
    else:
        level = state.target_level
    if level is None or assets <= 0:
        raise CoverageError(
            f'{profile.firm}: no level to close back to at {rung.name}')
    if profile.direction is Direction.RISING_UTILISATION:
        return max(Decimal('0'), required - level * assets)
    return max(Decimal('0'), required - assets / level)


def liquidation_path(profile: BrokerProfile) -> Tuple[PathStep, ...]:
    """The published route from the first rung to a closed position. **Axis 4.**

    Walks the ladder in order and emits only steps the firm's own documents
    support:

    * a ``NOTIFY`` step **only** where the rung's notice is
      :attr:`Notice.REQUIRED` -- a right that need not be exercised is not a
      step the account can rely on;
    * a ``CURE`` step only where the window actually grants time
      (:attr:`CureSpec.grants_time`), which excludes ``DELEGATED``;
    * ``TRANSFER_COLLATERAL`` before ``LIQUIDATE`` where the firm publishes
      that ordering, which only SSI does.

    So KIS's path is ``(LIQUIDATE,)`` -- notice disclaimed at every rung, cure
    window delegated -- while SSI's is
    ``(NOTIFY, TRANSFER_COLLATERAL, LIQUIDATE)``: SSI owes a notice at Muc 2
    and publishes a collateral transfer before liquidation at Muc 3, but
    publishes **no cure window at all**, so no ``CURE`` step is invented for
    it. PLUTUS_DEFAULT, which does carry a cure window, gets
    ``(NOTIFY, CURE, LIQUIDATE)``.

    Every step that is not there is a step the account cannot rely on, and a
    model that gave KIS SSI's path would over-state survival at KIS. That is
    the axis, measured.
    """
    steps = []
    for rung in profile.ladder:
        if rung.notice.is_obligation and rung.action in (
                Action.NOTIFY, Action.LIQUIDATE, Action.TRANSFER_COLLATERAL):
            steps.append(PathStep.NOTIFY)
            if rung.cure.grants_time:
                steps.append(PathStep.CURE)
        if rung.action is Action.TRANSFER_COLLATERAL:
            steps.append(PathStep.TRANSFER_COLLATERAL)
        follow = rung.follow_on
        if rung.action is Action.LIQUIDATE or (
                follow is not None and follow.closes_positions):
            steps.append(PathStep.LIQUIDATE)
            break
    return tuple(steps)


def notice_steps_before_liquidation(profile: BrokerProfile) -> int:
    """How many notice-or-cure steps stand between a breach and a close-out.

    Zero at KIS, MBS and VPS. A survival rate computed with this at 0 differs
    measurably from one computed with it at 2, and the difference is the
    firm's contract, not a modelling parameter.
    """
    path = liquidation_path(profile)
    return sum(1 for step in path
               if step in (PathStep.NOTIFY, PathStep.CURE))
