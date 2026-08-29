"""The OVERNIGHT margin layer: the requirement an account faces past the close.

**Why this module exists.** :mod:`plutus.market.session.scenario_margin`
implements QD 26 Phu luc 2 completely -- 21-scenario risk margin, basis
margin, delivery margin, the minimum-margin floor and the ``MR = Max(SUM Pgm,
0)`` assembly -- and until this module was written it had **zero call sites**
anywhere in ``src/`` or ``validation/``. A fidelity audit found the whole
engine unreachable: 1,069 of 1,069 executable lines never executed under any
scenario, and ``indeterminate_report()`` said ``indeterminate=0`` throughout,
because a layer nobody calls produces no evaluations to be undecided about.
This is the seam that calls it.

**The model is chosen per LAYER, not per profile** (survey finding F-1).
:class:`plutus.market.session.broker_profile.BrokerProfile` carries
``margin_model_intraday`` **and** ``margin_model_overnight`` because the
evidence carries both: all ten firms that state a formula for their *client*
ladder state ``IM + VM + DM``, and the four that publish scenario-grid
material label it, where they label it at all, as the end-of-day VSDC
submission. Two layers of one firm's answer, not two firms' answers. So:

* the **intraday** ladder is ``deposit.py``'s ``MR = IM + resting + VM``,
  recomputed continuously against the futures traded price. Untouched by this
  module;
* the **overnight** requirement is computed once *"sau khi ket thuc phien
  giao dich"* (QD 26 Dieu 5.5) from the account's end-of-day open positions
  and the **underlying's** close. That is what this module computes.

An account flat at the close and one holding the same book overnight
therefore face genuinely different requirements, and the difference is not a
scaling of one number by another -- post-KRX they are computed by different
engines from different price series.

**Dated, like everything else here.** The scenario grid is QD 26, in force
from the KRX cutover. Before it, the mechanism the dated rulebook records
(``RuleName.MARGIN_MODEL`` -> ``'pre_margin'``, confidence HIGH) is margin
lodged with VSDC *before* an order could be placed and recomputed against
live prices in-session: there is **no separate end-of-day model** in that
regime, so the overnight requirement is the same ``MR = IM + VM`` on the
positions still held at the close. Running the 21-scenario grid on a 2022
account would report a number under a regulation that did not exist, which is
the exact failure the dated rulebook exists to prevent. The caller
(:class:`plutus.market.session.exchange.ExchangeSession`) selects the regime
from the rulebook and passes the model in; this module never dates anything
itself.

**Nothing is guessed.** Every input the grid needs is a VSDC statistic that
somebody publishes. Where it is not available the answer is
:attr:`OvernightRequirement.amount` ``is None`` -- INDETERMINATE, with
:attr:`OvernightRequirement.gaps` naming exactly which input was missing --
and **never** a silent fall back to the intraday number. That direction
matters: an overnight requirement quietly replaced by an intraday one is
lower than the truth on any book the grid stresses harder, and a backtest
that under-states margin lets a strategy hold a position the real account
would have been called on.

Purity
------
This module reads nothing: no database, no file, no clock, no market data. It
takes positions, parameters and prices and returns arithmetic.
``scenario_margin`` is stricter still (stdlib-only imports, no float
literals, no module-level ``Decimal`` constants, enforced structurally by
``tests/market/session/test_scenario_margin.py``) and this module does not
weaken that: it imports it, it does not modify it, and it passes it only
values its caller supplied.

What is ours rather than the source's
-------------------------------------
Three places, all recorded on the result as
:class:`OvernightAssumption` rather than left in prose:

``no_published_grouping``
    Phu luc 2 section 2.1 makes underlying-asset **groups** VSDC's, published
    and discretionary (*"co the thiet lap"*, Kendall-tau >= 0.9 on >= 3 years
    of prices). No broker in the survey publishes group membership, so every
    underlying held is treated as a **singleton group** with ``OA = 0`` --
    ``scenario_margin``'s own register id ``I3``. That is the restrictive
    direction: an offset we do not apply can only make the requirement
    larger. Recorded only when the account actually holds two or more
    underlyings, because on a single-product book the relief is zero **by the
    rule** (QD 26 Dieu 5.1.1.a conditions it on *"tu hai tai san co so tro
    len"*) and there is nothing to disclose.

``minimum_margin_factor_derived``
    ``ContractLeg`` takes ``R``, the half relative spread of Phu luc 2
    section 5.2, and no firm publishes one. What the profile publishes is
    ``MF`` itself --
    :attr:`~plutus.market.session.broker_profile.BrokerProfile.minimum_margin_factor`,
    5,000d per VN30 contract, derived in research S-11 as ``tick x M / 2``
    for a one-tick-wide book and corroborated verbatim by TCBS. So ``R`` is
    inverted out of it: ``R = MF / (M x St)``, which
    :func:`~plutus.market.session.scenario_margin.minimum_margin_factor`
    then multiplies straight back to ``MF``. The inversion is done at raised
    precision so the round trip is exact at the module's default context --
    see :func:`_implied_minimum_margin_rate`. **What is ours** is S-11's
    first-order step: ``MF`` from a one-tick book is a *lower* bound on a real
    one, so ``MM`` here is a floor that binds slightly less often than the
    truth. It is a floor on a nearly-flat book and is dominated by ``Rm + Sm``
    on any book carrying risk.

``variation_margin_unsettled``
    Phu luc 2 section 6.2 has no ``VM`` term at all: QD 26 Dieu 20 settles
    *lai lo vi the* as a separate daily cash movement on T+1, so the post-KRX
    requirement is smaller than the pre-KRX ``IM + VM`` by exactly the
    account's variation margin -- measured at **49,800,000d** on a 2-lot
    VN30F position through a limit-down session, against a 109,844,000d
    intraday requirement. That is only the right answer if the loss is
    actually **paid in cash**, and this simulator now pays it:
    ``DerivativesAccount.settle_daily`` is wired into the overnight layer
    (``exchange._overnight_margin``), which settles the day's position P&L in
    cash and rolls the variation baseline **before** the requirement is read,
    so the view it reads carries ``VM == 0`` and this flag does not fire on an
    ordinary run. It remains -- and stays **permissive** in direction -- only
    for the residual the settlement cannot cover: a held contract with no
    settlement price this session, where the cash cannot be moved and the loss
    is left in the intraday view. The flag is raised on any grid result still
    computed while that view carries a non-zero ``VM``.

``parameter_mirror_undated``
    A :class:`~plutus.market.session.broker_profile.VsdcParameterSet` whose
    ``effective_from`` the firm does not print cannot be checked against the
    calculation date. The rates are still the firm's published ones, so they
    are used -- and the fact that we could not date them travels on the
    result. A mirror that *is* dated and post-dates the calculation is a
    different matter and is refused: see
    :attr:`OvernightGap.PARAMETERS_NOT_YET_EFFECTIVE`.

Deferred, and refused rather than approximated
----------------------------------------------
Government-bond futures. ``scenario_margin.delivery_margin`` implements
section 4 so nobody re-derives it, and says in its own docstring that it has
never been checked against a real VSDC number. ``Dm`` switches on exactly
where ``MM`` switches off, so a GB book at physical settlement has no
validated floor at all. A GB position therefore makes the whole layer
INDETERMINATE (:attr:`OvernightGap.GOVERNMENT_BOND_DEFERRED`) rather than
being margined on the index-future path, which would be wrong by the ratio of
their multipliers before any margin arithmetic ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from enum import Enum
from typing import (Dict, FrozenSet, List, Mapping, Optional, Protocol,
                    Sequence, Tuple, runtime_checkable)

from plutus.market.session.broker_profile import (
    MarginModel, UnderlyingParameters as MirroredParameters,
    VsdcParameterSet,
)
from plutus.market.session.scenario_margin import (
    ContractLeg, MarginInputError, MarginRequirement, UnderlyingGroup,
    UnderlyingParameters, required_margin,
)

__all__ = [
    'OvernightGap', 'OvernightAssumption', 'OvernightRequirement',
    'HeldContract', 'UNDERLYING_PREFIXES', 'underlying_of',
    'PRE_KRX_CONTINUOUS', 'SCENARIO_GRID_MODEL', 'UNSTATED_MODEL',
    'is_continuous_model', 'overnight_requirement',
    'scenario_grid_requirement',
]

_ZERO = Decimal('0')

#: The model name used for the pre-KRX regime, where the dated rulebook
#: records one continuously-recomputed mechanism and no end-of-day model.
#:
#: Deliberately **not** a :class:`MarginModel` member: ``MarginModel`` is the
#: vocabulary of what *firms publish about their own ladders*, and this is a
#: statement about what the **regulation** was, taken from
#: ``rulebook.RuleName.MARGIN_MODEL``'s ``'pre_margin'`` row (VSDC "Thong tin
#: ve ky quy" S II / S IV, confidence HIGH). Adding a member to the firm
#: vocabulary to hold a regulatory fact is how the two get confused.
PRE_KRX_CONTINUOUS = 'PRE_KRX_CONTINUOUS'

#: The two model names the dispatcher special-cases, as names rather than
#: literals at the call site. A typo in a string comparison is a silent
#: fall-through to the wrong engine, which is the failure class this whole
#: repair exists to remove -- see ``exchange.Component``'s docstring on why
#: its keys are an enum.
SCENARIO_GRID_MODEL = MarginModel.SCENARIO_GRID.name
UNSTATED_MODEL = MarginModel.UNSTATED.name


def is_continuous_model(model: str) -> bool:
    """Whether ``model`` is answered by the continuous engine, not the grid.

    One reader, so :func:`overnight_requirement` and its caller cannot
    disagree about which arm a run is on. ``True`` for
    :data:`PRE_KRX_CONTINUOUS` and for the ``IM + VM`` family a firm may name
    for its own overnight layer; ``False`` for the grid and for ``UNSTATED``,
    which is not a model at all.
    """
    return model not in (SCENARIO_GRID_MODEL, UNSTATED_MODEL)


#: ``contract-code prefix -> underlying asset``. Longest prefix wins.
#:
#: The same shape as ``deposit.CONTRACT_MULTIPLIERS`` and for the same reason:
#: the contract template is what identifies the underlying, and every VN30F
#: expiry shares one template. Rulebook 6.1 rows "VN30F contract size and
#: multiplier" and "VN100 index futures" are what make VN30F a future *on the
#: VN30 index*; the government-bond rows are rulebook 4.1.
#:
#: The names on the right are the ones VSDC's parameter table uses, and are
#: what :meth:`VsdcParameterSet.for_underlying` is keyed on -- ``'VN30'`` and
#: ``'VN100'`` appear verbatim in SSI's mirrored section A. **This is not a
#: dated table**: it maps a code to the thing it is written on, which does not
#: change with the date the way a multiplier or a margin ratio does.
UNDERLYING_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ('VN30F', 'VN30'),
    ('VN100F', 'VN100'),
    ('GB05', 'GB05'),
    ('GB10', 'GB10'),
)

#: Contract prefixes whose margin needs the deferred delivery-margin path.
_GOVERNMENT_BOND_PREFIXES: Tuple[str, ...] = ('GB05', 'GB10')


def underlying_of(contract_code: str) -> Optional[str]:
    """The underlying asset one contract is written on, or ``None``.

    ``None`` rather than a guess for an unrecognised code -- including the
    nine-character coded contract format (``41I1F6000``) that the rulebook
    records at LOW confidence and warns "do not trust the VSDC code column"
    about. An underlying guessed wrong selects another product's ``Rm`` and
    ``Sm``, and ``Sm`` alone differs by 34% between VN30 and VN100 on the same
    published page.
    """
    code = (contract_code or '').strip().upper()
    best: Optional[str] = None
    best_len = 0
    for prefix, name in UNDERLYING_PREFIXES:
        if code.startswith(prefix) and len(prefix) > best_len:
            best, best_len = name, len(prefix)
    return best


class OvernightGap(str, Enum):
    """Why an overnight requirement could not be computed. INDETERMINATE.

    Every member names **one input** rather than a symptom, because the
    remedies differ and a reader who is told only "indeterminate" cannot act.
    A gap always means the layer produced no number: there is no member here
    for something that changed a number, which is
    :class:`OvernightAssumption`'s job.
    """

    #: The profile names no overnight model at all (``MarginModel.UNSTATED``).
    #: Five of the shipped profiles are in this position: they publish a
    #: ladder and no formula for the CCP layer.
    MODEL_UNSTATED = 'margin_model_overnight.unstated'
    #: The profile selects the scenario grid and publishes no VSDC parameter
    #: mirror. ``BrokerProfile.parameters_for`` refuses rather than falling
    #: back to another firm's rates, and so does this.
    NO_PARAMETER_SET = 'vsdc_parameters.absent'
    #: The mirror is dated **after** the calculation date. Using it would
    #: margin a 2025 position on a table published in 2026.
    PARAMETERS_NOT_YET_EFFECTIVE = 'vsdc_parameters.not_yet_effective'
    #: The mirror carries no row for an underlying the account holds.
    NO_UNDERLYING_ROW = 'vsdc_parameters.underlying_row'
    #: The contract code maps to no known underlying.
    UNKNOWN_UNDERLYING = 'contract.underlying'
    #: No close for the underlying **asset** at this date. The grid's ``S`` is
    #: the index level, not the futures price, and substituting the futures
    #: price would fold the basis into every scenario.
    UNDERLYING_CLOSE = 'underlying_close'
    #: A group of two or more was supplied and this member has no average
    #: price. Section 2.2.b's scale factor needs it, and the observation
    #: window it is a mean over is SILENT in the source -- so it cannot be
    #: derived here and the offset cannot be computed without it.
    AVERAGE_PRICE = 'average_price'
    #: A government-bond futures position. ``Dm`` is implemented and never
    #: validated; see the module docstring.
    GOVERNMENT_BOND_DEFERRED = 'delivery_margin.deferred'
    #: The intraday engine could not decide either -- a stale mark on the
    #: pre-KRX path, where the overnight requirement *is* the continuous one.
    INTRADAY_INDETERMINATE = 'intraday.indeterminate'
    #: ``scenario_margin`` refused the inputs. Carried through rather than
    #: swallowed, because its refusals are specific and worth reading.
    ENGINE_REFUSED = 'engine.refused'


class OvernightAssumption(str, Enum):
    """Something ours that entered the number. It still produced a number.

    Distinct from :class:`OvernightGap` because the reader's question is
    different: a gap asks *what do I have to supply*, an assumption asks *how
    far do I trust this*. Both travel on the result; neither is prose.
    """

    #: Every underlying held was treated as a singleton group, so no
    #: offsetting amount was applied. Restrictive. Recorded only on a book
    #: holding two or more underlyings.
    NO_PUBLISHED_GROUPING = 'no_published_grouping'
    #: ``R`` was inverted out of the profile's published ``MF``.
    MINIMUM_MARGIN_FACTOR_DERIVED = 'minimum_margin_factor_derived'
    #: The parameter mirror carries no ``effective_from``, so it could not be
    #: checked against the calculation date.
    PARAMETER_MIRROR_UNDATED = 'parameter_mirror_undated'
    #: The grid's requirement excludes a variation margin the run never
    #: settled in cash. The **only permissive** flag here -- see the module
    #: docstring.
    VARIATION_MARGIN_UNSETTLED = 'variation_margin_unsettled'


@runtime_checkable
class HeldContract(Protocol):
    """What the layer needs to know about one open position.

    A structural protocol and not an import of
    :class:`~plutus.market.session.types.ContractPosition`, so this module
    stays free of the session's record types and can be exercised with three
    fields. ``ContractPosition`` satisfies it as written.

    ``net_quantity`` is **signed** -- positive long, negative short -- which
    is the shape the ledger stores, and it is the right one here: VSDC nets
    offsetting trades on one trading account (rulebook 6.3), so per contract
    code there is one balance and not a gross pair. The gross pair
    ``ContractLeg`` carries is across *expiry months*, which the ledger does
    keep apart, and that is what ``Sm`` needs.
    """

    @property
    def net_quantity(self) -> int: ...

    @property
    def multiplier(self) -> Decimal: ...

    @property
    def expiry(self) -> Optional[date]: ...


@dataclass(frozen=True)
class OvernightRequirement:
    """One account's end-of-day requirement, or a statement of what was missing.

    ``amount is None`` **is** the INDETERMINATE answer, and it is not the same
    fact as ``amount == 0``: a flat account genuinely owes nothing overnight,
    and that is a determinate zero with :attr:`flat` set. Keeping the two
    apart is the whole point -- ``0`` and "we could not tell" read identically
    in every summary statistic that does not.
    """

    as_of: date
    """The calculation date. Phu luc 2's ``S`` and ``St`` are this day's."""

    model: str
    """:class:`MarginModel` name, or :data:`PRE_KRX_CONTINUOUS`."""

    engine: Optional[str]
    """The module that produced the number, by name."""

    amount: Optional[Decimal]
    """``MR`` in dong, or ``None`` when the layer could not be computed."""

    flat: bool = False
    """The account held nothing at the close. ``amount`` is then a real zero."""

    detail: Optional[MarginRequirement] = None
    """``scenario_margin``'s own record, with every intermediate, when the
    grid ran. ``None`` on the pre-KRX path and on an indeterminate one."""

    legs: Tuple[ContractLeg, ...] = ()
    """The legs as the grid saw them. Empty on the pre-KRX path."""

    gaps: Tuple[str, ...] = ()
    """:class:`OvernightGap` values, qualified where they name a subject --
    ``'vsdc_parameters.underlying_row:VN100'``. Sorted, deduplicated."""

    assumptions: Tuple[str, ...] = ()
    """:class:`OvernightAssumption` values that entered the number."""

    note: str = ''
    """One sentence a report can print without re-deriving the above."""

    @property
    def is_determinate(self) -> bool:
        """Whether the layer produced a number at all."""
        return self.amount is not None

    @property
    def subjects(self) -> Tuple[str, ...]:
        """The gap kinds, unqualified -- what a counter should be keyed on."""
        return tuple(sorted({g.split(':', 1)[0] for g in self.gaps}))


def _qualified(gap: OvernightGap, subject: str = '') -> str:
    return gap.value if not subject else f'{gap.value}:{subject}'


def _grouped_underlyings(groups: Sequence[UnderlyingGroup]) -> FrozenSet[str]:
    """Members of a supplied group of two or more -- the ones needing ``Psr``.

    A singleton group has no pair, so it has no offsetting amount and no
    scale factor, and section 2.2.e defines ``Psr`` *"theo tung cap tai san
    co so"*. Asking a one-product account for an average price it will never
    use is how a layer acquires a required input nobody needs.
    """
    return frozenset(name for group in groups if not group.is_singleton
                     for name in group.underlyings)


def _implied_minimum_margin_rate(minimum_margin_factor: Decimal,
                                 multiplier: Decimal,
                                 close_price: Decimal) -> Decimal:
    """``R = MF / (M x St)`` -- the inversion of Phu luc 2 section 5.2.

    Computed at raised precision **on purpose**. ``scenario_margin`` will
    immediately compute ``R x M x St`` to get ``MF`` back, and a division
    taken at the default 28-digit context loses the last digit of the round
    trip: a 5,000d floor comes back as ``4999.999999999999999999999999``,
    which is arithmetically harmless and reads, in a margin report, like a
    bug. Fifty digits puts the residual below ``1e-40`` dong, and the
    re-multiplication at the default context then rounds to exactly ``MF``.

    This function is the *only* place ``R`` is produced, so the assumption it
    carries -- see :attr:`OvernightAssumption.MINIMUM_MARGIN_FACTOR_DERIVED`
    -- has one site to audit.
    """
    with localcontext() as ctx:
        ctx.prec = 50
        return minimum_margin_factor / (multiplier * close_price)


def scenario_grid_requirement(
    *,
    as_of: date,
    account_id: str,
    positions: Mapping[str, HeldContract],
    parameters: Optional[VsdcParameterSet],
    underlying_closes: Mapping[str, Decimal],
    minimum_margin_factor: Decimal,
    groups: Sequence[UnderlyingGroup] = (),
    average_prices: Optional[Mapping[str, Decimal]] = None,
    unsettled_variation_margin: Decimal = _ZERO,
) -> OvernightRequirement:
    """QD 26 Phu luc 2's ``MR``, or the list of inputs that were missing.

    Every refusal below is an input the caller can go and get, which is why
    they are collected rather than raised on the first one: a caller told
    "no parameter set" and then, on the next run, "no underlying close" has
    been made to iterate for information this function already had.

    Args:
        as_of: the calculation date. Checked against the parameter mirror's
            ``effective_from`` -- a mirror published later than this date is
            refused, not used.
        positions: ``contract_code -> position``, flat contracts absent.
        parameters: the firm's dated mirror of VSDC's table, or ``None``.
        underlying_closes: ``underlying -> close``. The **underlying asset's**
            close (the index level), never the futures price.
        minimum_margin_factor: ``MF`` per contract, from the broker profile.
        groups: VSDC's published underlying-asset groups. Empty is the
            ordinary case and means singleton groups with no offset.
        average_prices: ``underlying -> mean price``, needed **only** for a
            member of a supplied group of two or more (section 2.2.b's scale
            factor). The observation window it averages over is SILENT in the
            source, which is why it is an input and why a group supplied
            without it is refused rather than approximated.
        unsettled_variation_margin: the intraday view's ``VM`` at this
            instant. Non-zero raises
            :attr:`OvernightAssumption.VARIATION_MARGIN_UNSETTLED` on the
            result, because the grid has no ``VM`` term and this run does not
            settle one in cash either.
    """
    gaps: List[str] = []
    assumptions: List[str] = []

    held = {code: row for code, row in positions.items()
            if row.net_quantity != 0}
    if not held:
        return OvernightRequirement(
            as_of=as_of, model=MarginModel.SCENARIO_GRID.name,
            engine=MarginModel.SCENARIO_GRID.engine,
            amount=_ZERO, flat=True,
            note='flat at the close: no open position, so no end-of-day '
                 'requirement. QD 26 Dieu 5.5 computes MR for the position '
                 'portfolio on the account, and there is none.')

    bonds = sorted(code for code in held
                   if code.strip().upper().startswith(_GOVERNMENT_BOND_PREFIXES))
    for code in bonds:
        gaps.append(_qualified(OvernightGap.GOVERNMENT_BOND_DEFERRED, code))

    if parameters is None:
        gaps.append(_qualified(OvernightGap.NO_PARAMETER_SET))
    elif parameters.effective_from is None:
        assumptions.append(OvernightAssumption.PARAMETER_MIRROR_UNDATED.value)
    elif parameters.effective_from > as_of:
        gaps.append(_qualified(
            OvernightGap.PARAMETERS_NOT_YET_EFFECTIVE,
            parameters.effective_from.isoformat()))

    legs: List[ContractLeg] = []
    wanted: List[str] = []
    for code in sorted(held):
        name = underlying_of(code)
        if name is None:
            gaps.append(_qualified(OvernightGap.UNKNOWN_UNDERLYING, code))
            continue
        if name not in wanted:
            wanted.append(name)

    paired = _grouped_underlyings(groups)
    mirrored: Dict[str, MirroredParameters] = {}
    closes: Dict[str, Decimal] = {}
    for name in wanted:
        if parameters is not None:
            try:
                mirrored[name] = parameters.for_underlying(name)
            except KeyError:
                gaps.append(_qualified(OvernightGap.NO_UNDERLYING_ROW, name))
        close = underlying_closes.get(name)
        if close is None:
            gaps.append(_qualified(OvernightGap.UNDERLYING_CLOSE, name))
        else:
            closes[name] = Decimal(close)
        if name in paired and not (average_prices or {}).get(name):
            gaps.append(_qualified(OvernightGap.AVERAGE_PRICE, name))

    if gaps:
        return OvernightRequirement(
            as_of=as_of, model=MarginModel.SCENARIO_GRID.name,
            engine=MarginModel.SCENARIO_GRID.engine,
            amount=None, gaps=tuple(sorted(set(gaps))),
            assumptions=tuple(sorted(set(assumptions))),
            note='the post-KRX overnight requirement could not be computed; '
                 'the intraday number is NOT a substitute for it')

    # Every input is present. Build the legs.
    for code in sorted(held):
        row = held[code]
        name = underlying_of(code)
        assert name is not None  # gaps would have been non-empty
        net = row.net_quantity
        multiplier = Decimal(row.multiplier)
        last_day = row.expiry is not None and row.expiry <= as_of
        rate: Optional[Decimal] = None
        if not last_day:
            rate = _implied_minimum_margin_rate(
                Decimal(minimum_margin_factor), multiplier, closes[name])
            if (OvernightAssumption.MINIMUM_MARGIN_FACTOR_DERIVED.value
                    not in assumptions):
                assumptions.append(
                    OvernightAssumption.MINIMUM_MARGIN_FACTOR_DERIVED.value)
        legs.append(ContractLeg(
            contract_code=code,
            underlying=name,
            long_quantity=max(net, 0),
            short_quantity=max(-net, 0),
            multiplier=multiplier,
            minimum_margin_rate=rate,
            is_last_trading_day=last_day))

    averages = average_prices or {}
    grid_parameters = tuple(
        UnderlyingParameters(
            underlying=name,
            closing_price=closes[name],
            initial_margin_ratio=mirrored[name].risk_margin_rate,
            basis_margin_rate=mirrored[name].spread_margin_rate,
            average_price=(Decimal(averages[name]) if name in averages
                           else None),
        )
        for name in wanted)

    if len(wanted) > 1 and not groups:
        assumptions.append(OvernightAssumption.NO_PUBLISHED_GROUPING.value)
    if unsettled_variation_margin != _ZERO:
        assumptions.append(
            OvernightAssumption.VARIATION_MARGIN_UNSETTLED.value)

    try:
        requirement = required_margin(
            legs, grid_parameters, account_id=account_id, groups=groups)
    except MarginInputError as exc:
        return OvernightRequirement(
            as_of=as_of, model=MarginModel.SCENARIO_GRID.name,
            engine=MarginModel.SCENARIO_GRID.engine,
            amount=None, legs=tuple(legs),
            gaps=(_qualified(OvernightGap.ENGINE_REFUSED, str(exc)),),
            assumptions=tuple(sorted(set(assumptions))),
            note='scenario_margin refused these inputs')

    return OvernightRequirement(
        as_of=as_of, model=MarginModel.SCENARIO_GRID.name,
        engine=MarginModel.SCENARIO_GRID.engine,
        amount=requirement.amount, detail=requirement, legs=tuple(legs),
        assumptions=tuple(sorted(set(assumptions))),
        note=f'QD 26 Phu luc 2 section 6: MR = Max(SUM Pgm, 0) over '
             f'{len(requirement.groups)} underlying-asset group(s), on the '
             f'underlying close of {as_of.isoformat()}')


def overnight_requirement(
    *,
    as_of: date,
    account_id: str,
    positions: Mapping[str, HeldContract],
    model: str,
    parameters: Optional[VsdcParameterSet] = None,
    underlying_closes: Optional[Mapping[str, Decimal]] = None,
    minimum_margin_factor: Optional[Decimal] = None,
    intraday_amount: Optional[Decimal] = None,
    intraday_is_determinate: bool = True,
    unsettled_variation_margin: Decimal = _ZERO,
    groups: Sequence[UnderlyingGroup] = (),
    average_prices: Optional[Mapping[str, Decimal]] = None,
) -> OvernightRequirement:
    """Dispatch the overnight layer to the model in force, and never past it.

    ``model`` is a :class:`MarginModel` name or :data:`PRE_KRX_CONTINUOUS`,
    and the caller has already decided which -- from the **dated rulebook**
    for the regime and from the **broker profile** for the firm's own answer
    within it. This function does not date anything; it dispatches.

    The three answers:

    * :data:`PRE_KRX_CONTINUOUS`, and the continuous ``IM + VM`` family --
      the overnight requirement is the intraday engine's number recomputed on
      the positions still held at the close. ``intraday_amount`` carries it.
      This is not a fallback: in the pre-KRX regime the dated rulebook records
      one mechanism and no end-of-day model, and in the ``IM + VM`` family it
      is the model the firm itself names for the layer.
    * ``SCENARIO_GRID`` -- :func:`scenario_grid_requirement`.
    * ``UNSTATED`` -- the firm publishes no overnight model. INDETERMINATE.
      Not the intraday number wearing a different label: the two are computed
      from different price series by different engines, and a firm that
      declines to say which one applies has not said "the intraday one".
    """
    if model == SCENARIO_GRID_MODEL:
        if minimum_margin_factor is None:
            raise ValueError(
                'the scenario grid needs a minimum margin factor (MF); '
                'BrokerProfile.minimum_margin_factor publishes it')
        return scenario_grid_requirement(
            as_of=as_of, account_id=account_id, positions=positions,
            parameters=parameters,
            underlying_closes=underlying_closes or {},
            minimum_margin_factor=minimum_margin_factor, groups=groups,
            average_prices=average_prices,
            unsettled_variation_margin=unsettled_variation_margin)

    if model == UNSTATED_MODEL:
        return OvernightRequirement(
            as_of=as_of, model=model, engine=None, amount=None,
            gaps=(_qualified(OvernightGap.MODEL_UNSTATED),),
            note='the firm publishes a ladder and no overnight model, so the '
                 'end-of-day requirement is undetermined. The intraday number '
                 'is a different quantity and is not reported as this one')

    held = {code: row for code, row in positions.items()
            if row.net_quantity != 0}
    engine = 'plutus.market.session.deposit'
    if not intraday_is_determinate:
        return OvernightRequirement(
            as_of=as_of, model=model, engine=engine, amount=None,
            gaps=(_qualified(OvernightGap.INTRADAY_INDETERMINATE),),
            note='this regime computes the overnight requirement with the '
                 'continuous engine, and that engine could not decide -- a '
                 'position with no mark in this session')
    return OvernightRequirement(
        as_of=as_of, model=model, engine=engine,
        amount=_ZERO if not held else intraday_amount,
        flat=not held,
        note=('flat at the close: no open position, so nothing is carried '
              'and nothing is required'
              if not held else
              'the regime records one continuously-recomputed mechanism and '
              'no separate end-of-day model, so the overnight requirement is '
              'MR = IM + VM on the positions still held at the close, with '
              'no resting-order margin (the day\'s orders are gone)'))
