"""The post-KRX derivatives margin model -- QD 26/QD-HDTV, Phu luc 2.

**This engine is pure and parameterised. It reads nothing.** No database, no
file, no network, no embedded market data, no clock. Every quantity VSDC
derives from a long price history -- the initial margin ratio, ``SMrate``,
``R``, ``Psr``, and the underlying-asset groups themselves -- arrives as an
**input**. Calibrating those from a data source is a separate, later
component and it does not live here. The module is data-source-agnostic on
purpose: it is the one place in the derivatives chain where the temptation to
reach for a corpus is strongest, and a margin engine that can only be run
against one corpus is not a margin engine.

``tests/market/session/test_scenario_margin.py`` enforces this structurally --
it walks this module's AST and fails on an import outside a small allowlist
and on any float literal. Both rules are load-bearing, not decoration.

**We do not measure things.** Nothing here counts how often a margin call
happens, on our corpus or on any other. An earlier margin-incidence
measurement was retracted as malformed. This module implements *policy*.

The assembly, from Phu luc 2 section 6 (``phuluc2`` L127-138)::

    MR  = Max(SUM Pgm, 0)              per investor / member account
    Pgm = Max((Rm + Sm + Dm), MM)      per underlying-asset GROUP

with, per underlying:

=========  ==========================================================
``Rm``     *ky quy rui ro* -- scenario risk margin, the absolute value
           of the worst loss over 21 price scenarios (section 1),
           net of the offsetting amount ``OA`` (section 2).
``Sm``     *ky quy song hanh* -- basis margin on the matched part of
           a calendar book (section 3).
``Dm``     *ky quy chuyen giao* -- delivery margin, government-bond
           futures only (section 4). **DEFERRED** -- see below.
``MM``     *ky quy toi thieu* -- the close-out cost floor (section 5).
=========  ==========================================================

**Variation margin is not a component.** QD 26 Dieu 20 settles *lai lo vi
the* as a separate daily cash movement on T+1; Phu luc 2 section 6.2 has no
VM term at all. Do not add one. The pre-KRX ``MR = IM + VM`` shape lives in
``deposit.py`` and is correct only to 2025-05-04.

**The monitoring test is binary, and it is not a ladder.** QD 26 Dieu 13 was
read in full: a violation is ``margin assets < required margin``. There is no
percentage anywhere in it. The 80/90/100 ladder that a reader may be looking
for is **Dieu 29**, and it applies to *gioi han vi the* -- a contract count
against a published position cap, a different quantity with a different
remedy. It is deliberately **not** implemented here.
:class:`MarginViolationMonitor` implements Dieu 13 and only Dieu 13.

**Government-bond futures are deferred by author decision.** Section 4's
arithmetic is implemented so the model is complete and so nobody re-derives
it later, and :func:`delivery_margin` says so in its own docstring. It has
never been checked against a real VSDC number, no GB future exists in any
corpus this project holds, and the CTD-bond method it depends on lives in
**Phu luc 8, which we do not have.**

Confidence vocabulary, matching ``docs/reference/post-krx-margin-spec.md``:
**VERIFIED** read verbatim in the primary text; **INFERRED** our reading,
needed to make the model computable, not stated in either document;
**DERIVED** our own arithmetic on verified formulas; **SILENT** the source
does not address it; **DEFECT** the published text is inconsistent or
incomplete. Every INFERRED site carries its register id in its own docstring
and appears in :data:`INFERENCES`; every defect appears in
:data:`SOURCE_DEFECTS`. Overclaiming is a defect, so a function that returns
a number the source does not fully determine says which part is ours.

Primary sources, both read end to end before this module was written:

* **QD 26/QD-HDTV ngay 16/4/2025** -- *Quy che bu tru va thanh toan giao dich
  chung khoan phai sinh tai VSDC*. Cited below as ``qd26 L<n>``.
* **Phu luc 2** -- *Phuong phap xac dinh cac gia tri ky quy*. Cited as
  ``phuluc2 L<n>``.
* ``docs/reference/post-krx-margin-spec.md`` -- the specification written
  from those two, whose section numbers this module tracks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from enum import Enum
from typing import (
    Callable, Iterable, List, Mapping, Optional, Sequence, Tuple,
)

__all__ = [
    # -- errors -----------------------------------------------------------
    'ScenarioMarginError', 'MarginInputError', 'MarginTimelineError',
    # -- registers --------------------------------------------------------
    'INFERENCES', 'SOURCE_DEFECTS',
    # -- the scenario grid (Phu luc 2 section 1) --------------------------
    'SCENARIO_STEPS', 'SCENARIO_COUNT', 'Scenario', 'scenario_price',
    'scenario_prices', 'scenario_loss', 'risk_margin', 'RiskMargin',
    # -- the initial margin ratio (Phu luc 2 section 1.3) -----------------
    'MIN_OBSERVATIONS_1_3_A', 'MIN_OBSERVATIONS_1_3_B', 'VarEstimate',
    'two_day_returns', 'parametric_var',
    # -- the offsetting amount (Phu luc 2 section 2) ----------------------
    'PercentileMethod', 'percentile', 'price_relation_rate',
    'group_price_relation_rate', 'delta_coefficient', 'StandardisedPosition',
    'OffsettingAmount', 'offsetting_amount', 'apply_offsetting_amount',
    # -- basis margin (Phu luc 2 section 3) -------------------------------
    'BasisMargin', 'basis_margin',
    # -- delivery margin (Phu luc 2 section 4) ----------------------------
    'DeliveryPosition', 'DeliveryMargin', 'delivery_margin',
    # -- minimum margin (Phu luc 2 section 5) -----------------------------
    'MinimumMargin', 'minimum_margin_factor', 'minimum_margin',
    # -- the inputs -------------------------------------------------------
    'ContractLeg', 'UnderlyingParameters', 'UnderlyingGroup',
    # -- assembly (Phu luc 2 section 6) -----------------------------------
    'GroupMargin', 'MarginRequirement', 'group_margin', 'required_margin',
    # -- monitoring (QD 26 Dieu 13) ---------------------------------------
    'Checkpoint', 'CHECKPOINT_TIME', 'MarginViolationState',
    'MarginEventKind', 'MarginEvent', 'MarginObservation',
    'is_margin_violation', 'MarginViolationMonitor',
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ScenarioMarginError(Exception):
    """Base for everything this module raises."""


class MarginInputError(ScenarioMarginError, ValueError):
    """A parameter is missing, inconsistent, or outside its stated domain.

    This module **raises rather than defaults**. A missing ``SMrate`` is not
    zero, a missing ``R`` is not zero, and an underlying with no parameters
    is not an underlying with a flat price. Each of those substitutions
    silently understates ``MR``, which is the one direction a margin engine
    must never fail in.
    """


class MarginTimelineError(ScenarioMarginError, RuntimeError):
    """The monitor was driven out of order.

    Raised when a 09h30 or 14h00 checkpoint is fed before any end-of-day
    determination has notified a requirement -- QD 26 Dieu 13.2.a tests
    against *"muc ky quy yeu cau xac dinh tai ngay lam viec lien truoc"*, the
    requirement determined on the **previous** working day, and there is no
    such thing on the first day.
    """


# ---------------------------------------------------------------------------
# The registers
# ---------------------------------------------------------------------------

#: Every place this module read something the source does not state.
#:
#: Ids match ``docs/reference/post-krx-margin-spec.md`` section 11 so the two
#: can be diffed. A test asserts that every id cited in a docstring in this
#: module appears here, so the register cannot silently fall behind the code.
INFERENCES: Mapping[str, str] = {
    'I1': (
        'Sk = S0 x (1 + k x rate/10). The published scenario table prints '
        'the formula with no k on the right-hand side, in all 21 rows, '
        'which collapses the grid to one point. See SOURCE_DEFECTS["D1"]. '
        'This is the load-bearing reconstruction of the whole model.'
    ),
    'I2': (
        'Rm_gross = max(0, -min_k Lk). Phu luc 2 section 1.1 says Rm is the '
        'absolute value of the largest loss "trong so cac khoan lo"; when no '
        'scenario produces a loss there is no khoan lo to take the absolute '
        'value of, and |max Lk| would charge margin for a profit. DERIVED '
        'and worth knowing: given the SYMMETRIC grid, k = 0 always yields '
        'Lk = 0 exactly, so min_k Lk <= 0 for every possible book and the '
        'floor is provably unreachable. It is kept as a guard on the grid '
        'staying symmetric, not because it fires.'
    ),
    'I3': (
        'An underlying named in no supplied group forms a singleton group '
        'with OA = 0. Phu luc 2 section 2.1 only provides for groups of two '
        'or more; section 6.1 sums Pgm over groups, so an ungrouped '
        'underlying must still produce a Pgm or its risk vanishes from MR.'
    ),
    'I4': (
        'Rm = max(0, Rm_gross - OA), applied at the group level. QD 26 Dieu '
        '5.1.1.a fixes the DIRECTION verbatim ("so tien dieu chinh giam gia '
        'tri ky quy rui ro") and that much is VERIFIED. That the arithmetic '
        'is subtraction, that it lands at the group level, and that the '
        'result is floored at zero are all ours. See apply_offsetting_amount.'
    ),
    'I5': (
        'C compares the ABSOLUTE values of the positive-delta and '
        'negative-delta standardised contract counts. Read literally, "gia '
        'tri nho hon" of a positive and a negative number is always the '
        'negative one, giving C < 0 and an OA that would raise margin.'
    ),
    'I6': (
        'Psr: operator precedence is 1 - A/B, not (1-A)/B; and rx / ry are '
        '2-day RETURNS, not absolute price changes -- two indices at '
        'different levels have non-comparable point moves. Note this is the '
        'opposite reading of the same Vietnamese phrase that section 3.3 '
        'forces. See SOURCE_DEFECTS["D8"].'
    ),
    'I7': (
        'The percentile convention for Max99 is nearest-rank. The appendix '
        'says only "phan vi thu 99" and never names a method; nearest-rank '
        'and linear interpolation disagree on small samples. Both are '
        'implemented; the method is an explicit parameter.'
    ),
    'I8': (
        'P in SMl / SMs is a GROSS count per underlying, summed across '
        'expiry months. Under a net reading one leg is always zero and Sm is '
        'identically zero, which would make the whole component dead.'
    ),
    'I9': (
        'P in MM is a GROSS contract count. A close-out cost scales with the '
        'contracts to be closed, so a net reading under-charges a spread '
        'book that still has two legs to unwind.'
    ),
    'I10': (
        'MM = 0 on the last trading day. Phu luc 2 section 5.1 says MF is '
        '"khong duoc xac dinh tai ngay giao dich cuoi cung"; with MF '
        'undefined, section 6.2s Max((Rm+Sm+Dm), MM) has no second operand. '
        'Note it dovetails with Dm switching ON on that same day.'
    ),
    'I11': (
        'Dm = MTM + DRM. Phu luc 2 section 4.1 says only that delivery '
        'margin "gom hai gia tri thanh phan" -- comprises two component '
        'values -- and never writes the combination.'
    ),
    'I12': (
        'Per-underlying Rm_gross, Sm, Dm and MM SUM to the group level. '
        'Section 6.2 is written with scalar terms but is defined per group, '
        'and a group may hold several underlyings; the roll-up is not stated.'
    ),
    'I13': (
        'rate = VaR at n = 2. Phu luc 2 section 1.3.c announces the formula '
        'converting VaR and n into the published ratio and then omits it '
        '(SOURCE_DEFECTS["D2"]), so this is a guess and a sqrt(n/2) scaling '
        'is equally consistent with the fragment. Use VSDCs published ratio; '
        'parametric_var exists to CHECK a series, not to replace the ratio.'
    ),
    'I14': (
        'r_t = (S_T - S_T-2) / S_T-2, sampled once per trading day '
        '(overlapping). The source fixes the two endpoints and nothing else '
        '-- not arithmetic vs log, not the denominator, not the sampling.'
    ),
    'I17': (
        'B and S -- the risk margin ON ONE standardised contract of each '
        'sign -- are computed as the sign-side total Rm_gross divided by '
        'that sides standardised contract count. Phu luc 2 section 2.2 names '
        'B and S and never says how to obtain them for a group whose sides '
        'hold more than one underlying. LOCAL to offsetting_amount.'
    ),
    'I18': (
        'Where an underlying carries contracts with different multipliers, '
        'Rm, Sm and MM are summed leg by leg rather than evaluated once with '
        'a single M. Each formula is written with one scalar M; summing per '
        'leg reduces to the printed formula when M is constant, which it is '
        'for every VN30F contract.'
    ),
    'I19': (
        'The scale factors average size uses the LARGEST multiplier among '
        'the contracts on that underlying. Section 2.2.b says only "he so '
        'nhan"; section 2.2.a is explicit that delta normalises by "he so '
        'nhan lon nhat trong cac hop dong co cung tai san co so", so the max '
        'is the only choice consistent with the neighbouring sub-section.'
    ),
    'I20': (
        'The 03-working-day close-out clock runs from the day AFTER the '
        'notice and does not restart when a later end-of-day determination '
        'finds the account still short. "Ke tu ngay" admits both an '
        'inclusive and an exclusive reading; a restarting clock would let an '
        'account defer close-out indefinitely. include_notice_day exposes '
        'the other reading.'
    ),
    'I21': (
        'Suspension happens at 09h30 and only at 09h30. Dieu 13.2 gives the '
        'suspend action to the 09h30 checkpoint alone; 14h00 and 16h30 are '
        'given only restore actions. So an account first found short at '
        '16h30 is notified, not suspended.'
    ),
}

#: Properties of the gazetted text, not of our reading of it.
#:
#: Recorded because the next person to fetch these documents will meet them
#: again. Ids match ``post-krx-margin-spec.md`` section 12.
SOURCE_DEFECTS: Mapping[str, str] = {
    'D1': (
        'CRITICAL. Phu luc 2 section 1.2s scenario table prints '
        '"Sk = S0 x (1 + ty le ky quy ban dau/10)" -- WITH NO k -- '
        'identically in all 21 rows, while the same cell declares '
        '-10 <= k <= 10 and the rows are labelled S-10 ... S+10. Read '
        'literally the 21 scenarios are one point, Lk takes one value, and '
        'section 4.3s Hp and Lp are equal. See scenario_price for the '
        'reading we adopt and why.'
    ),
    'D2': (
        'CRITICAL. Phu luc 2 section 1.3.c announces the formula that turns '
        'VaR and n into the published initial margin ratio and is followed '
        'immediately by "Trong do:". The expression is absent from the '
        'extraction. Consequence: n is defined and then never used.'
    ),
    'D3': (
        'HIGH. QD 26 Dieu 8.1s margin-ASSET valuation formula is missing the '
        'same way -- all seven variables (VKQ, C, MR, x = 80%, QKQ, P, H) '
        'are glossed and the expression is absent. This module therefore '
        'takes margin assets as a supplied scalar and does NOT value '
        'collateral; that is the other half of the assets < MR test and it '
        'is not ours to guess.'
    ),
    'D8': (
        'HIGH. "Bien dong gia" must mean a RETURN in section 2.2.e and an '
        'absolute price CHANGE in section 3.3, otherwise one formula is '
        'dimensionally wrong and the other is not comparable across '
        'underlyings. One phrase, two quantities. See INFERENCES["I6"].'
    ),
    'D9': (
        'MEDIUM. SMrate is computed per expiry-month PAIR and then defined '
        'as a single pooled 90th percentile applied per UNDERLYING. The fate '
        'of the per-pair rates is never stated.'
    ),
    'D10': (
        'MEDIUM. The E+2 hole. Dm is stated for the last trading day E and '
        'for E+1; settlement is E+3; and E+2 is a live operational day under '
        'QD 26 Dieu 22.4. The literal reading leaves an undelivered position '
        'unmargined for delivery risk on E+2. Deferred with the rest of the '
        'bond work; not silently patched.'
    ),
    'D12': (
        'MEDIUM. MF is "cho mot thang dao han HDTL" in section 5.1 and "tren '
        'mot hop dong" in section 5.2. Only the per-contract reading balances '
        'MM = P x MF dimensionally, so that is the one implemented.'
    ),
    'D13': (
        'MEDIUM. QD 26 Dieu 13 has TWO khoan numbered 3, and khoan 3.b '
        'cross-refers to "diem a khoan 1 Dieu nay" -- but khoan 1 has no '
        'lettered points. The intended target is almost certainly diem a '
        'khoan 2, the 09h30 checkpoint. MarginViolationMonitor reads it that '
        'way and says so.'
    ),
    'D14': (
        'The two stated observation windows for the initial margin ratio. '
        'Section 1.3.a says "toi thieu 120 ngay giao dich"; section 1.3.b '
        'says "ky quan sat toi thieu la 250 ngay giao dich". Both are '
        'minima, so they are not strictly contradictory -- but they cannot '
        'both be THE stated minimum, and an implementer choosing 120 '
        'complies with (a) and breaches (b). Surfaced as an explicit '
        'parameter, defaulted to the conservative 250.'
    ),
}


# ---------------------------------------------------------------------------
# Shared numeric helpers
# ---------------------------------------------------------------------------

_ZERO = Decimal(0)
_ONE = Decimal(1)
_TEN = Decimal(10)
_THREE = Decimal(3)
_HUNDRED = Decimal(100)


def _as_decimal(value: object, what: str) -> Decimal:
    """Accept a ``Decimal`` or an ``int``; refuse a ``float``.

    House rule: money and ratios are ``Decimal``, never ``float``. A float
    that reached a margin number would be a defect that only shows up in the
    last digits of a forced-liquidation amount, so it is refused loudly at
    the boundary rather than tolerated and rounded away later.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is an int subclass; never a quantity
        raise MarginInputError(f'{what} must be a Decimal, got bool')
    if isinstance(value, int):
        return Decimal(value)
    raise MarginInputError(
        f'{what} must be a Decimal (or int), got {type(value).__name__}. '
        'Floats are refused: this module is Decimal-only.'
    )


class PercentileMethod(str, Enum):
    """How to read *"phan vi thu 99"* -- INFERRED, register id ``I7``.

    The appendix names a percentile and never names a method. On the large
    samples VSDC uses the two agree to well within a tick; on the small
    samples a test can be written by hand they do not, so the choice is an
    explicit parameter rather than a hidden convention.

    ``NEAREST_RANK``
        The smallest observation at or above rank ``ceil(p/100 * n)``. This
        is the classical definition and always returns an observed value.
    ``LINEAR``
        Linear interpolation between the two observations bracketing rank
        ``p/100 * (n - 1)``. This is what ``numpy.percentile`` does by
        default and what a reader reproducing VSDC in a notebook would most
        likely get.
    """

    NEAREST_RANK = 'nearest_rank'
    LINEAR = 'linear'


def percentile(
    values: Sequence[Decimal],
    p: Decimal,
    *,
    method: PercentileMethod = PercentileMethod.NEAREST_RANK,
) -> Decimal:
    """The ``p``-th percentile of ``values``, ``p`` in ``[0, 100]``.

    Used for ``Max99|rx - ry|`` in :func:`price_relation_rate` (Phu luc 2
    section 2.2.e). It is deliberately **not** used for ``SMrate``: that is
    an input here, because VSDC derives it from a DSP series this project
    does not hold in a usable shape.

    The method is INFERRED -- see :class:`PercentileMethod` and
    ``INFERENCES['I7']``.
    """
    if not values:
        raise MarginInputError('percentile of an empty sample is undefined')
    p = _as_decimal(p, 'p')
    if p < _ZERO or p > _HUNDRED:
        raise MarginInputError(f'p must lie in [0, 100], got {p}')
    ordered = sorted(_as_decimal(v, 'value') for v in values)
    n = len(ordered)
    if method is PercentileMethod.NEAREST_RANK:
        rank = (p / _HUNDRED) * Decimal(n)
        whole = rank == rank.to_integral_value()
        index = int(rank) if whole else int(rank) + 1
        index = max(1, min(n, index))
        return ordered[index - 1]
    position = (p / _HUNDRED) * Decimal(n - 1)
    lower = int(position)
    upper = min(lower + 1, n - 1)
    weight = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


# ---------------------------------------------------------------------------
# Phu luc 2 section 1 -- ky quy rui ro (Rm), the 21-scenario grid
# ---------------------------------------------------------------------------

#: ``k``, the scenario index, from Phu luc 2 section 1.2: ``-10 <= k <= 10``.
#:
#: Twenty-one values. ``k = 0`` is the unchanged-price scenario and sits at
#: row 11 of the published table; scenario row ``j = k + 11``.
SCENARIO_STEPS: Tuple[int, ...] = tuple(range(-10, 11))

#: The count the appendix states in words: *"21 kich ban bien dong gia"*.
SCENARIO_COUNT: int = len(SCENARIO_STEPS)


@dataclass(frozen=True)
class Scenario:
    """One of the 21 price scenarios, and the account's P&L in it.

    ``loss`` is **signed P&L**, not a loss magnitude: Phu luc 2 calls it
    *"Khoan lai/lo"*. A negative value is a loss. :attr:`is_loss` exists so
    no caller has to remember the sign.
    """

    k: int
    price: Decimal
    loss: Decimal

    @property
    def row(self) -> int:
        """The published table's row number, 1..21, for cross-checking."""
        return self.k + 11

    @property
    def is_loss(self) -> bool:
        return self.loss < _ZERO


def scenario_price(s0: Decimal, rate: Decimal, k: int) -> Decimal:
    """``Sk = S0 x (1 + k x rate/10)`` -- **a reconstruction**, id ``I1``.

    **The published formula does not contain ``k``.** Phu luc 2 section 1.2's
    table (``phuluc2`` L140-148) prints, identically in all 21 rows::

        Sk = S0 x (1 + ty le ky quy ban dau/10)
        Trong do: S0 : Gia cua tai san co so tai ngay xac dinh
                  Sk : Gia cua tai san co so trong kich ban k
                  -10 <= k <= 10

    Read literally, every scenario evaluates to the same price
    ``S0 x (1 + rate/10)``, ``Lk`` takes one value, and a 21-point grid
    becomes one point. That reading is contradicted four ways by the source
    itself: (i) the same table cell declares ``-10 <= k <= 10`` and defines
    ``Sk`` as the price *in scenario k*, so ``Sk`` must depend on ``k``;
    (ii) the table lists 21 distinct labels ``S-10 ... S+10``; (iii) section
    1.2's own sentence says *"21 kich ban bien dong gia"*; and (iv) section
    4.3 asks for a **highest** and a **lowest** scenario price, which a
    one-point grid does not have.

    **The reading adopted here** inserts the multiplication the surrounding
    definitions require and changes nothing else::

        Sk = S0 x (1 + k x rate/10)     for k = -10, -9, ..., +9, +10

    Two further checks it passes and the literal text fails. It reproduces
    the declared count and labels exactly, ``k = 0`` giving the unchanged
    price at row 11. And it makes ``rate`` mean what it is called: at
    ``k = +-10`` the price is ``S0 x (1 +- rate)``, so for a directional net
    position the worst scenario charges exactly ``rate x notional`` -- which
    is also, numerically, the superseded pre-KRX initial-margin formula, so
    the reform generalises the old closed form rather than replacing it.

    **Flag this at every use.** The corrected formula is not in the gazetted
    appendix as extracted. It is very well supported and it is still a
    reconstruction. If a published claim turns on the scenario spacing,
    obtain the cong bao PDF and read the table cell as typeset.
    Recorded as ``SOURCE_DEFECTS['D1']``.

    **SILENT -- rounding.** The appendix does not say whether ``Sk`` is
    rounded to the underlying's quotation precision before ``Lk`` is
    evaluated. QD 26 Dieu 23.1 fixes rounding for DSP and FSP and says
    nothing about scenario prices. This returns full ``Decimal`` precision
    and rounds nothing; the choice is deliberate and recorded here.
    """
    if k not in SCENARIO_STEPS:
        raise MarginInputError(
            f'k must lie in [-10, 10] per Phu luc 2 section 1.2, got {k}'
        )
    s0 = _as_decimal(s0, 's0')
    rate = _as_decimal(rate, 'rate')
    if s0 <= _ZERO:
        raise MarginInputError(f's0 must be positive, got {s0}')
    if rate < _ZERO:
        raise MarginInputError(f'rate must not be negative, got {rate}')
    return s0 * (_ONE + Decimal(k) * rate / _TEN)


def scenario_prices(s0: Decimal, rate: Decimal) -> Tuple[Decimal, ...]:
    """All 21 scenario prices, in ``k`` order from ``-10`` to ``+10``.

    ``result[0]`` is ``Lp`` and ``result[-1]`` is ``Hp`` for the delivery
    margin of section 4.3 -- which is why that component inherits
    ``SOURCE_DEFECTS['D1']`` in full: under the literal text those two are
    the same number.
    """
    return tuple(scenario_price(s0, rate, k) for k in SCENARIO_STEPS)


def scenario_loss(
    *,
    scenario_price_: Decimal,
    close_price: Decimal,
    long_quantity: int,
    short_quantity: int,
    multiplier: Decimal,
) -> Decimal:
    """``Lk = Pm x (Sk - S) x M + Pb x (S - Sk) x M`` -- section 1.1.

    VERIFIED verbatim (``phuluc2`` L6). ``Pm`` is the gross long balance,
    ``Pb`` the gross short balance, ``S`` the underlying's closing price on
    the calculation date, ``M`` the contract multiplier.

    **DERIVED, and the reason ``Sm`` exists.** The expression factorises to
    ``(Pm - Pb) x (Sk - S) x M``: the two legs cancel algebraically, so a
    fully hedged calendar book has ``Rm = 0``. That is not an oversight. QD
    26 Dieu 5.2 defines *ky quy song hanh* as covering exactly the loss
    *"tang them so voi gia tri ky quy rui ro"* that this netting conceals.
    Implementing ``Rm`` without ``Sm`` under-margins every spread.
    """
    sk = _as_decimal(scenario_price_, 'scenario_price')
    s = _as_decimal(close_price, 'close_price')
    m = _as_decimal(multiplier, 'multiplier')
    pm = Decimal(long_quantity)
    pb = Decimal(short_quantity)
    return pm * (sk - s) * m + pb * (s - sk) * m


# ---------------------------------------------------------------------------
# The inputs -- positions and the parameters VSDC publishes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractLeg:
    """One futures contract's position on one account, at end of session.

    **Long and short are carried separately and both are non-negative.**
    Phu luc 2 uses a gross pair everywhere -- ``Pm``/``Pb`` in section 1.1,
    ``P`` for each of ``SMl``/``SMs`` in section 3.2, ``P`` in section 5.1 --
    and three of those four uses are destroyed by netting first. ``Rm`` nets
    the pair algebraically whether you intend it or not (see
    :func:`scenario_loss`); ``Sm`` and ``MM`` must not. A signed net field
    here would make ``Sm`` identically zero, which is register ids ``I8``
    and ``I9``.

    ``multiplier`` is the CONTRACT's *he so nhan*, not the venue's and not
    the account's -- 100,000 VND per index point for VN30F and VN100F,
    10,000 for the government-bond futures. It is required, because a
    defaulted multiplier is a wrong margin number that looks right.

    ``minimum_margin_rate`` is ``R`` of section 5.2, per contract and per
    expiry month. VSDC derives it as the **mean** (for a liquid product) or
    the **median** (for an illiquid one) of
    ``(lowest ask - highest bid) / (lowest ask + highest bid)`` taken **per
    matched trade** over at least 252 trading days preceding the calculation
    date. That derivation is documented and **not implemented here** -- it
    needs a tick corpus, and what makes a product "liquid" is SILENT in the
    source, so the mean/median fork has no rule to resolve it. Supply the
    number.

    ``is_last_trading_day`` exists because section 5.1 says ``MF`` is *"khong
    duoc xac dinh tai ngay giao dich cuoi cung"*. When it is set, this leg
    contributes **zero** to ``MM`` -- register id ``I10`` -- and the group
    result records that it did.
    """

    contract_code: str
    underlying: str
    long_quantity: int
    short_quantity: int
    multiplier: Decimal
    minimum_margin_rate: Optional[Decimal] = None
    is_last_trading_day: bool = False

    def __post_init__(self) -> None:
        if not self.contract_code:
            raise MarginInputError('contract_code must not be empty')
        if not self.underlying:
            raise MarginInputError(
                f'{self.contract_code}: underlying must not be empty. The '
                'unit below the account is the underlying-asset group, not '
                'the contract (Phu luc 2 section 6.1).'
            )
        for name in ('long_quantity', 'short_quantity'):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise MarginInputError(
                    f'{self.contract_code}: {name} must be an int contract '
                    f'count, got {type(value).__name__}'
                )
            if value < 0:
                raise MarginInputError(
                    f'{self.contract_code}: {name} is a GROSS balance and '
                    f'must not be negative, got {value}. A short is '
                    'short_quantity, never a negative long_quantity.'
                )
        multiplier = _as_decimal(self.multiplier, 'multiplier')
        if multiplier <= _ZERO:
            raise MarginInputError(
                f'{self.contract_code}: multiplier must be positive, got '
                f'{multiplier}'
            )
        object.__setattr__(self, 'multiplier', multiplier)
        if self.minimum_margin_rate is None:
            if not self.is_last_trading_day:
                raise MarginInputError(
                    f'{self.contract_code}: minimum_margin_rate (R, Phu luc '
                    '2 section 5.2) is required. It is omissible only on the '
                    'last trading day, where section 5.1 says MF is not '
                    'determined. A missing R is not zero -- treating it as '
                    'zero silently removes the MM floor from Pgm.'
                )
        else:
            rate = _as_decimal(self.minimum_margin_rate, 'minimum_margin_rate')
            if rate < _ZERO:
                raise MarginInputError(
                    f'{self.contract_code}: minimum_margin_rate must not be '
                    f'negative, got {rate}. It is a half relative spread.'
                )
            object.__setattr__(self, 'minimum_margin_rate', rate)

    @property
    def gross_quantity(self) -> int:
        """``P`` for ``MM`` -- both legs, because both must be closed out."""
        return self.long_quantity + self.short_quantity

    @property
    def net_quantity(self) -> int:
        """Signed net, used only for the delta coefficient of section 2.2.a."""
        return self.long_quantity - self.short_quantity


@dataclass(frozen=True)
class UnderlyingParameters:
    """Everything VSDC publishes or derives for one underlying asset.

    **All four numeric fields are inputs and none of them is calibrated
    here.** That is the module's central constraint, and this class is where
    it is visible: every one of these is the output of a long-history
    statistical procedure run by VSDC, and a simulator that computed them
    from whatever corpus happened to be mounted would silently become a
    model of that corpus rather than of the exchange.

    ``closing_price``
        ``S`` in section 1.1, ``S0`` in section 1.2, ``St`` in section 5.2 --
        one quantity under three names (a cosmetic defect in the appendix).
        The **underlying's** close on the calculation date, not the futures
        price. For government-bond futures it is the CTD bond's price, whose
        selection method is in **Phu luc 8, which we do not have**.
    ``initial_margin_ratio``
        *ty le ky quy ban dau*. VSDC computes it by parametric VaR and
        publishes it on its website at least 02 working days before it
        applies, re-determining it on the 1st, 10th and 20th of each month
        (QD 26 Dieu 5.1.1.b). Because of that cadence the correct key is
        ``(contract, effective date)`` and never a scalar; supplying it here
        per calculation is how this module stays out of that business.
        :func:`parametric_var` exists so a caller can check that their price
        series reproduces the published number -- not to replace it.
    ``basis_margin_rate``
        ``SMrate`` of section 3.3. VSDC derives it as the **90th percentile**
        of ``|(rt1 - rt2) / St|`` -- the 2-business-day DSP/FSP change of the
        spot expiry month against each paired far month, over the pooled set
        of all pairs and all days in an observation window. The window is
        *"mot khoang thoi gian nhat dinh"* in the rule and **252 days only in
        the worked example**, so 252 is example-sourced, not rule-sourced.
        **Not computed here**, by instruction and because no usable daily DSP
        series exists in this project's corpora.
    ``average_price``
        Optional, and needed **only** when this underlying sits in a group of
        two or more. It is the arithmetic mean of the underlying's price over
        section 2.2.b's *"khoang quan sat nhat dinh"* -- an observation window
        the source never specifies (SILENT). Used only for the scale factor.
    """

    underlying: str
    closing_price: Decimal
    initial_margin_ratio: Decimal
    basis_margin_rate: Decimal
    average_price: Optional[Decimal] = None

    def __post_init__(self) -> None:
        if not self.underlying:
            raise MarginInputError('underlying must not be empty')
        close = _as_decimal(self.closing_price, 'closing_price')
        if close <= _ZERO:
            raise MarginInputError(
                f'{self.underlying}: closing_price must be positive, got '
                f'{close}'
            )
        ratio = _as_decimal(self.initial_margin_ratio, 'initial_margin_ratio')
        if ratio < _ZERO:
            raise MarginInputError(
                f'{self.underlying}: initial_margin_ratio must not be '
                f'negative, got {ratio}'
            )
        sm_rate = _as_decimal(self.basis_margin_rate, 'basis_margin_rate')
        if sm_rate < _ZERO:
            raise MarginInputError(
                f'{self.underlying}: basis_margin_rate (SMrate) must not be '
                f'negative, got {sm_rate}'
            )
        object.__setattr__(self, 'closing_price', close)
        object.__setattr__(self, 'initial_margin_ratio', ratio)
        object.__setattr__(self, 'basis_margin_rate', sm_rate)
        if self.average_price is not None:
            avg = _as_decimal(self.average_price, 'average_price')
            if avg <= _ZERO:
                raise MarginInputError(
                    f'{self.underlying}: average_price must be positive, got '
                    f'{avg}'
                )
            object.__setattr__(self, 'average_price', avg)


@dataclass(frozen=True)
class UnderlyingGroup:
    """A *nhom tai san co so* -- **supplied, never derived here**.

    Group formation is Phu luc 2 section 2.1 and it is **VSDC's,
    discretionary** (*"co the thiet lap"*): underlyings whose **Kendall-tau**
    correlation, computed on **prices** over at least **3 years**, is
    **positive and not below 0.9**, with each underlying in **at most one
    group**. None of that is computed here -- correlating price histories is
    exactly the data-bound calibration this module refuses to do -- and a
    group exists only if VSDC has published one.

    Two rules visible only in the appendix's worked example, both INFERRED
    and both the caller's to honour: admission is **pairwise** across every
    pair in the group, not merely connected; and once an underlying is
    committed, later candidate groups containing it are **foreclosed**, so
    the outcome depends on the order VSDC evaluates candidates. (The example
    also says *"lon hon 0,9"* where the rule says *"khong thap hon 0,9"*; the
    operative clause governs, so the admission bound is inclusive.)

    ``price_relation_rate`` is ``Psr`` -- the group's, i.e. the **minimum**
    over its pairs. Required when the group holds two or more underlyings and
    forbidden when it holds one, because a singleton has no pair and no
    offset. Compute it with :func:`group_price_relation_rate` from supplied
    return series, or supply VSDC's number.
    """

    group_id: str
    underlyings: Tuple[str, ...]
    price_relation_rate: Optional[Decimal] = None

    def __post_init__(self) -> None:
        if not self.group_id:
            raise MarginInputError('group_id must not be empty')
        members = tuple(self.underlyings)
        if not members:
            raise MarginInputError(f'{self.group_id}: group is empty')
        if len(set(members)) != len(members):
            raise MarginInputError(
                f'{self.group_id}: an underlying appears twice in the group'
            )
        object.__setattr__(self, 'underlyings', members)
        if len(members) == 1:
            if self.price_relation_rate is not None:
                raise MarginInputError(
                    f'{self.group_id}: a singleton group has no pair, so it '
                    'has no price relation rate and no offsetting amount. '
                    'Phu luc 2 section 2.2.e defines Psr "theo tung cap tai '
                    'san co so".'
                )
            return
        if self.price_relation_rate is None:
            raise MarginInputError(
                f'{self.group_id}: a group of {len(members)} underlyings '
                'needs price_relation_rate (Psr, Phu luc 2 section 2.2.e). '
                'It is the MINIMUM over the groups pairs; compute it with '
                'group_price_relation_rate() or supply VSDCs number.'
            )
        psr = _as_decimal(self.price_relation_rate, 'price_relation_rate')
        object.__setattr__(self, 'price_relation_rate', psr)

    @property
    def is_singleton(self) -> bool:
        return len(self.underlyings) == 1


# ---------------------------------------------------------------------------
# Phu luc 2 section 1 -- assembling Rm for one underlying
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskMargin:
    """``Rm`` before the offsetting amount, for one underlying.

    All 21 scenarios are kept, not just the worst, because a margin number
    nobody can audit is a margin number nobody should trust: a reader can
    read ``scenarios`` and check the grid spacing against
    :func:`scenario_price`'s reconstruction by hand.
    """

    underlying: str
    close_price: Decimal
    initial_margin_ratio: Decimal
    scenarios: Tuple[Scenario, ...]
    worst: Scenario
    gross: Decimal

    @property
    def is_reconstructed_grid(self) -> bool:
        """Always ``True``, and it is here to be impossible to overlook.

        The 21-scenario spacing is our reading of a published table whose
        formula omits ``k`` -- ``SOURCE_DEFECTS['D1']``,
        ``INFERENCES['I1']``. Any report that quotes ``Rm`` as "what the
        regulation says" is overclaiming.
        """
        return True


def risk_margin(
    underlying: str,
    legs: Sequence[ContractLeg],
    parameters: UnderlyingParameters,
) -> RiskMargin:
    """``Rm`` gross for one underlying -- Phu luc 2 section 1.

    ``Rm`` is *"gia tri tuyet doi cua khoan lo lon nhat trong so cac khoan
    lo"* over the 21 scenarios (section 1.1, VERIFIED). Since ``Lk`` is
    signed P&L, the largest loss is the **most negative** ``Lk``, and::

        Rm_gross = max(0, -min_k Lk)

    The zero floor is INFERRED, register id ``I2``: when no scenario produces
    a loss there is no *khoan lo* whose absolute value to take, and
    ``|max Lk|`` would charge margin for a profit.

    **DERIVED -- and the floor is provably unreachable.** ``k = 0`` is in the
    grid and gives ``S0 = S``, hence ``Lk = 0`` **exactly**, for every book.
    So ``min_k Lk <= 0`` always, ``-min_k Lk >= 0`` always, and ``max(0, ...)``
    can never bind. It is kept as a guard on the grid **staying symmetric**:
    the day someone re-indexes the scenarios ``1..21`` instead of
    ``-10..+10``, the floor is the only thing standing between a profitable
    book and a margin charge. Do not delete it as dead code -- it is dead
    only for as long as :data:`SCENARIO_STEPS` brackets zero, and a test
    pins that property rather than pretending the floor fires.

    Where an underlying carries contracts of different multipliers the losses
    are summed leg by leg (register id ``I18``); with one multiplier -- every
    VN30F contract -- this is identical to the printed scalar formula.
    """
    if parameters.underlying != underlying:
        raise MarginInputError(
            f'parameters are for {parameters.underlying}, not {underlying}'
        )
    mine = [leg for leg in legs if leg.underlying == underlying]
    if not mine:
        raise MarginInputError(f'{underlying}: no legs supplied')
    s = parameters.closing_price
    scenarios: List[Scenario] = []
    for k in SCENARIO_STEPS:
        sk = scenario_price(s, parameters.initial_margin_ratio, k)
        total = _ZERO
        for leg in mine:
            total += scenario_loss(
                scenario_price_=sk,
                close_price=s,
                long_quantity=leg.long_quantity,
                short_quantity=leg.short_quantity,
                multiplier=leg.multiplier,
            )
        scenarios.append(Scenario(k=k, price=sk, loss=total))
    worst = min(scenarios, key=lambda s_: (s_.loss, s_.k))
    gross = max(_ZERO, -worst.loss)
    return RiskMargin(
        underlying=underlying,
        close_price=s,
        initial_margin_ratio=parameters.initial_margin_ratio,
        scenarios=tuple(scenarios),
        worst=worst,
        gross=gross,
    )


# ---------------------------------------------------------------------------
# Phu luc 2 section 1.3 -- the initial margin ratio, as a CHECKING helper
# ---------------------------------------------------------------------------

#: Section 1.3.a: *"trong khoang thoi gian toi thieu 120 ngay giao dich"*.
MIN_OBSERVATIONS_1_3_A: int = 120

#: Section 1.3.b: *"trong ky quan sat toi thieu la 250 ngay giao dich"*.
#:
#: The default, because it is the binding constraint if both clauses are
#: operative. See :func:`parametric_var` and ``SOURCE_DEFECTS['D14']``.
MIN_OBSERVATIONS_1_3_B: int = 250


@dataclass(frozen=True)
class VarEstimate:
    """The parametric VaR statistic of section 1.3.c, and what it is not."""

    observations: int
    minimum_observations: int
    mean: Decimal
    stdev: Decimal
    value_at_risk: Decimal
    sample_stdev: bool

    @property
    def inferred_initial_margin_ratio(self) -> Decimal:
        """``VaR`` itself, read as the ratio at ``n = 2`` -- **a guess**.

        Register id ``I13``, and it is the weakest inference in the model.
        Section 1.3.c defines ``n`` -- *"so ngay can thiet de thanh ly mot vi
        the"* -- announces the formula that turns ``VaR`` and ``n`` into the
        published ratio, and then **omits the expression**
        (``SOURCE_DEFECTS['D2']``), so ``n`` is defined and never used. The
        only self-consistent reading available is ``rate = VaR`` with
        ``n = 2``, since the returns are already 2-day returns and a further
        horizon scaling would double-count -- but a ``sqrt(n/2)`` scaling is
        the textbook move and is equally consistent with the fragment.

        **Use VSDC's published ratio.** This property exists so a caller can
        see how far their series lands from it, which is a diagnostic, not a
        substitute. It is a property rather than a field so that no result
        record can be mistaken for a published ratio.
        """
        return self.value_at_risk


def two_day_returns(prices: Sequence[Decimal]) -> Tuple[Decimal, ...]:
    """2-day price-change rates, ``T`` against ``T-2`` -- INFERRED, ``I14``.

    Section 1.3.c fixes the two **endpoints** and nothing else: *"so sanh
    giua gia tai san co so tai ngay tinh toan (ngay T) voi gia tai san co so
    tai ngay lam viec lien ke thu 2 truoc ngay T (ngay T-2)"*. It does not
    say arithmetic or log, does not fix the denominator, and does not say
    whether sampling overlaps.

    Adopted here, all INFERRED: ``r_t = (S_T - S_{T-2}) / S_{T-2}``, because
    section 1.3.a calls it a *"ty le phan tram bien dong gia"*, a percentage;
    and **overlapping** daily sampling, one observation per trading day,
    because that is the only way a 120- or 250-day window yields that many
    observations.

    ``prices`` must be in ascending date order, with **no gaps** -- this
    function has no calendar and cannot tell a weekend from a suspension.
    Aligning a price series to trading days is the caller's job.
    """
    values = [_as_decimal(p, 'price') for p in prices]
    if len(values) < 3:
        raise MarginInputError(
            f'a 2-day return needs at least 3 prices, got {len(values)}'
        )
    out: List[Decimal] = []
    for index in range(2, len(values)):
        base = values[index - 2]
        if base <= _ZERO:
            raise MarginInputError(
                f'price at index {index - 2} must be positive, got {base}'
            )
        out.append((values[index] - base) / base)
    return tuple(out)


def parametric_var(
    returns: Sequence[Decimal],
    *,
    minimum_observations: int = MIN_OBSERVATIONS_1_3_B,
    sample_stdev: bool = True,
) -> VarEstimate:
    """``VaR = mean + 3 x delta`` on a supplied return series -- section 1.3.

    A **pure, clearly-separated checking helper**, not part of the margin
    computation. The margin computation takes VSDC's published ratio as an
    input (:class:`UnderlyingParameters`). This exists so a caller can feed
    their own 2-day return series and see whether it reproduces the published
    number -- which is a useful thing to be able to do and a dangerous thing
    to do silently, hence :attr:`VarEstimate.inferred_initial_margin_ratio`
    being a property with a warning rather than a field.

    **The window is an explicit parameter because the source states two.**
    Section 1.3.a says *"toi thieu 120 ngay giao dich"*; section 1.3.b says
    *"ky quan sat toi thieu la 250 ngay giao dich"*. Both are minima, so they
    are not strictly contradictory -- any window at or above 250 satisfies
    both -- but they cannot both be **the** stated minimum, and an
    implementer choosing 120 complies with (a) and breaches (b). Neither
    reading is resolved here. The default is
    :data:`MIN_OBSERVATIONS_1_3_B` = 250, the conservative one; pass
    :data:`MIN_OBSERVATIONS_1_3_A` = 120 deliberately to take the other.
    Recorded as ``SOURCE_DEFECTS['D14']``.

    **``mean + 3 x delta`` is asymmetric and the source means it that way.**
    Three sigma one-sided is 99.865%; the **two-sided** 3-sigma interval is
    **99.73%**, which is the confidence section 1.3.a states. So ``VaR`` is
    the upper bound of a 99.73% two-sided interval. If ``mean`` is negative,
    ``mean + 3 delta`` is *smaller* than ``3 delta``. That is what the text
    says. **Do not "fix" it** to ``|mean| + 3 delta`` or ``3 delta - mean``;
    a test pins this.

    **SILENT -- the estimator.** The appendix says *"do lech chuan"* and does
    not say whether the divisor is ``n`` or ``n - 1``. ``sample_stdev``
    defaults to ``True`` (divisor ``n - 1``); on a 250-observation window the
    two differ by about 0.2%, which is below the granularity at which VSDC
    publishes, so this is recorded rather than agonised over.

    ``Decimal.sqrt`` runs in the ambient decimal context (28 significant
    digits by default). No rounding to a currency precision happens here,
    because a ratio is not money.
    """
    values = [_as_decimal(r, 'return') for r in returns]
    n = len(values)
    if minimum_observations < 2:
        raise MarginInputError(
            f'minimum_observations must be at least 2, got '
            f'{minimum_observations}'
        )
    if n < minimum_observations:
        raise MarginInputError(
            f'{n} observations is below the required minimum of '
            f'{minimum_observations}. Phu luc 2 section 1.3.a says at least '
            f'{MIN_OBSERVATIONS_1_3_A} trading days and section 1.3.b says '
            f'at least {MIN_OBSERVATIONS_1_3_B}; the two are not reconciled '
            'in the source, so the window is yours to state explicitly.'
        )
    count = Decimal(n)
    mean = sum(values, _ZERO) / count
    squared = sum(((v - mean) * (v - mean) for v in values), _ZERO)
    divisor = Decimal(n - 1) if sample_stdev else count
    if divisor <= _ZERO:
        raise MarginInputError('a sample standard deviation needs n >= 2')
    stdev = (squared / divisor).sqrt()
    return VarEstimate(
        observations=n,
        minimum_observations=minimum_observations,
        mean=mean,
        stdev=stdev,
        value_at_risk=mean + _THREE * stdev,
        sample_stdev=sample_stdev,
    )


# ---------------------------------------------------------------------------
# Phu luc 2 section 2 -- gia tri giam tru ky quy (OA), the offsetting amount
# ---------------------------------------------------------------------------


def price_relation_rate(
    rx: Sequence[Decimal],
    ry: Sequence[Decimal],
    *,
    method: PercentileMethod = PercentileMethod.NEAREST_RANK,
) -> Decimal:
    """``1 - Max99|rx - ry| / (Max|rx| + Max|ry|)`` -- section 2.2.e.

    VERIFIED as to the formula (``phuluc2`` L56). ``rx`` and ``ry`` are the
    two underlyings' **2-business-day price movements**, paired
    observation-for-observation; ``Max99`` is the 99th percentile of the
    absolute differences; the denominator is the sum of the two series'
    absolute maxima.

    Three readings, all INFERRED and all register id ``I6``:

    1. **Operator precedence is ``1 - A/B``**, not ``(1 - A)/B``. Only the
       former is bounded above by 1 and reduces to 1 when the two series move
       identically, which is what a rate called a *correlation* must do.
    2. **``rx`` and ``ry`` are returns, not absolute price changes.** The
       text says *"bien dong gia"* without *"ty le"* -- but the formula
       differences X against Y directly, and two indices at different levels
       have non-comparable point moves. **This is the opposite reading of the
       same phrase that section 3.3 forces on ``SMrate``**, where dividing by
       ``St`` is dimensionally wrong unless the numerator is in price units.
       One phrase, two quantities: ``SOURCE_DEFECTS['D8']``.
    3. **The percentile convention** -- ``INFERENCES['I7']``.

    **SILENT -- the observation window.** Never specified, so the caller
    supplies the series and owns the window.

    **DERIVED -- ``Psr`` needs no floor, because it cannot go below zero.**
    It is natural to worry that ``1 - A/B`` might go negative and make ``OA``
    negative, *raising* margin. It cannot, and the reason is the triangle
    inequality: every element of the difference set satisfies
    ``|rx - ry| <= |rx| + |ry| <= Max|rx| + Max|ry|``, so **every** element
    is bounded by the denominator, so any percentile of them is too. Hence
    ``0 <= Psr <= 1`` for every possible pair of input series, and the upper
    bound is attained exactly when the two series are identical.

    This is worth stating because it removes a decision rather than making
    one: **no floor is applied here, and none is needed.** A ``Psr`` outside
    ``[0, 1]`` is therefore impossible rather than merely unlikely, which
    makes it a usable assertion about a caller's inputs. (The companion spec
    at ``post-krx-margin-spec.md`` section 5.3(e) speculates that a negative
    value is reachable "in pathological samples"; that speculation is wrong,
    and this is the correction.)

    Not to be confused with section 2.1's *he so tuong quan* -- that is
    **Kendall's tau on prices**, at least 0.9, used to admit an underlying to
    a group. Same name in Vietnamese, different quantity, different use.
    Two distinct fields; do not let one populate the other.
    """
    x = [_as_decimal(v, 'rx') for v in rx]
    y = [_as_decimal(v, 'ry') for v in ry]
    if len(x) != len(y):
        raise MarginInputError(
            f'rx and ry must be paired observation-for-observation, got '
            f'{len(x)} and {len(y)}'
        )
    if not x:
        raise MarginInputError('rx and ry must not be empty')
    differences = [abs(a - b) for a, b in zip(x, y)]
    numerator = percentile(differences, Decimal(99), method=method)
    denominator = max(abs(v) for v in x) + max(abs(v) for v in y)
    if denominator == _ZERO:
        raise MarginInputError(
            'Max|rx| + Max|ry| is zero, so the price relation rate is '
            'undefined: both series are identically flat.'
        )
    return _ONE - numerator / denominator


def group_price_relation_rate(
    series: Mapping[str, Sequence[Decimal]],
    *,
    method: PercentileMethod = PercentileMethod.NEAREST_RANK,
) -> Decimal:
    """``Psr`` for a group: the **minimum** over its pairs -- section 2.2.e.

    VERIFIED verbatim: *"He so tuong quan gia cua nhom tai san co so la gia
    tri nho nhat trong tap hop cac he so tuong quan gia cua tung cap tai san
    co so thuoc cung mot nhom"* (``phuluc2`` L64). Every unordered pair of
    members contributes one rate and the group takes the smallest -- the
    weakest link governs the relief, which is the conservative direction.

    A convenience over :func:`price_relation_rate` for callers who hold the
    series; the group can equally carry VSDC's published ``Psr``.
    """
    names = sorted(series)
    if len(names) < 2:
        raise MarginInputError(
            'a price relation rate needs at least two underlyings; a '
            'singleton group has no pair and no offsetting amount'
        )
    rates = [
        price_relation_rate(series[a], series[b], method=method)
        for i, a in enumerate(names)
        for b in names[i + 1:]
    ]
    return min(rates)


def delta_coefficient(
    net_quantity: int, multiplier: Decimal, max_multiplier: Decimal
) -> Decimal:
    """``he so Delta = position x M / max M on the same underlying``.

    VERIFIED verbatim (``phuluc2`` L42): *"He so Delta = So luong vi the x He
    so nhan / He so nhan lon nhat trong cac hop dong co cung tai san co so"*,
    with *"Doi voi vi the mua he so Delta luon la so duong, doi voi vi the
    ban he so Delta luon la so am"* -- long positive, short negative. So the
    sign is carried by a **signed** net quantity, which is the one place in
    this module a net is the right unit.

    For our corpus this is the identity: every VN30F contract carries
    ``M = 100,000``, so delta is the signed contract count exactly.
    """
    m = _as_decimal(multiplier, 'multiplier')
    max_m = _as_decimal(max_multiplier, 'max_multiplier')
    if max_m <= _ZERO:
        raise MarginInputError(f'max_multiplier must be positive, got {max_m}')
    return Decimal(net_quantity) * m / max_m


@dataclass(frozen=True)
class StandardisedPosition:
    """One underlying's contribution to a group's offset, fully shown.

    Every intermediate of section 2.2.a-c is kept as its own field so a
    reader can check the chain -- delta, average size, scale factor,
    standardised count -- rather than being handed a single number.
    """

    underlying: str
    delta: Decimal
    average_size: Decimal
    scale_factor: Decimal
    standardised: Decimal
    risk_margin_gross: Decimal


@dataclass(frozen=True)
class OffsettingAmount:
    """``OA = (B + S) x C x Psr`` -- section 2.2, with its working shown."""

    group_id: str
    positions: Tuple[StandardisedPosition, ...]
    positive_standardised: Decimal
    negative_standardised: Decimal
    contracts_offset: Decimal
    positive_leg_margin: Decimal
    negative_leg_margin: Decimal
    price_relation_rate: Decimal
    amount: Decimal


def offsetting_amount(
    group: UnderlyingGroup,
    legs: Sequence[ContractLeg],
    parameters: Mapping[str, UnderlyingParameters],
    risk_margins: Mapping[str, RiskMargin],
) -> OffsettingAmount:
    """``OA`` for one group -- Phu luc 2 section 2.2.

    ``OA = (B + S) x C x Psr`` (VERIFIED, ``phuluc2`` L33), where ``B`` and
    ``S`` are the risk margin **on one standardised contract** of positive
    and of negative delta, ``C`` is the number of standardised contracts that
    pair off, and ``Psr`` is the group's price relation rate. Units check:
    ``B + S`` is VND per offsetting pair, ``C`` is a count, ``Psr`` is
    dimensionless, so ``OA`` is VND -- a **margin credit**, which is the
    dimensional argument that it can only be subtracted.

    The chain, section 2.2.a-d::

        delta_u        = signed position x M_u / max M on underlying u
        avg_size_u     = mean price_u over the window x max M on u
        scale_u        = max_j(avg_size_j) / avg_size_u          (>= 1)
        standardised_u = delta_u / scale_u
        C              = min(sum of positive standardised,
                             |sum of negative standardised|)

    Four inferences live here:

    * ``C`` compares **absolute values** (``I5``). Read literally, *"gia tri
      nho hon"* of a positive and a negative number is always the negative
      one, giving ``C < 0`` and an ``OA`` that would *increase* margin. Also
      inferred: ``C = 0`` when the group is one-sided -- no offset, no
      relief, which is the correct risk answer.
    * ``B`` and ``S`` are obtained as each sign side's **total** gross risk
      margin divided by that side's standardised contract count (``I17``).
      The appendix names them per standardised contract and never says how to
      get them when a side holds more than one underlying.
    * The scale factor's average size uses the **largest** multiplier on the
      underlying (``I19``), because that is what the neighbouring delta
      formula normalises by.
    * ``SILENT`` -- section 2.2.b's *"khoang quan sat nhat dinh"*, the window
      the average price is taken over, is never specified. It arrives here
      already averaged, in ``UnderlyingParameters.average_price``.

    **On real data this returns zero, and that is the right answer, not an
    approximation.** Every account this project can represent holds exactly
    one underlying, VN30; QD 26 Dieu 5.1.1.a's own precondition for a
    reduction is *"tu hai tai san co so tro len"*. So ``OA = 0`` **by the
    rule**. This function is exercised only by synthetic multi-underlying
    portfolios, and any test of it must say so.
    """
    if group.is_singleton:
        raise MarginInputError(
            f'{group.group_id}: a singleton group has no offsetting amount. '
            'QD 26 Dieu 5.1.1.a conditions the reduction on positions in '
            '"tu hai tai san co so tro len".'
        )
    positions: List[StandardisedPosition] = []
    sizes: List[Tuple[str, Decimal, Decimal, Decimal]] = []
    for name in group.underlyings:
        params = parameters.get(name)
        if params is None:
            raise MarginInputError(
                f'{group.group_id}: no parameters for underlying {name}'
            )
        mine = [leg for leg in legs if leg.underlying == name]
        if not mine:
            raise MarginInputError(
                f'{group.group_id}: no legs for group member {name}'
            )
        max_multiplier = max(leg.multiplier for leg in mine)
        if params.average_price is None:
            raise MarginInputError(
                f'{name}: average_price is required for a member of a '
                f'multi-underlying group -- Phu luc 2 section 2.2.b needs it '
                'for the scale factor. It is the mean underlying price over '
                'an observation window the source never specifies.'
            )
        delta = sum(
            (
                delta_coefficient(
                    leg.net_quantity, leg.multiplier, max_multiplier
                )
                for leg in mine
            ),
            _ZERO,
        )
        sizes.append(
            (name, delta, params.average_price * max_multiplier,
             risk_margins[name].gross if name in risk_margins else _ZERO)
        )
    largest = max(size for _, _, size, _ in sizes)
    for name, delta, size, gross in sizes:
        scale = largest / size
        positions.append(
            StandardisedPosition(
                underlying=name,
                delta=delta,
                average_size=size,
                scale_factor=scale,
                standardised=delta / scale,
                risk_margin_gross=gross,
            )
        )
    positive = sum(
        (p.standardised for p in positions if p.standardised > _ZERO), _ZERO
    )
    negative = sum(
        (p.standardised for p in positions if p.standardised < _ZERO), _ZERO
    )
    contracts = min(positive, abs(negative))
    positive_margin = _ZERO
    negative_margin = _ZERO
    if positive > _ZERO:
        positive_margin = sum(
            (p.risk_margin_gross for p in positions if p.standardised > _ZERO),
            _ZERO,
        ) / positive
    if negative < _ZERO:
        negative_margin = sum(
            (p.risk_margin_gross for p in positions if p.standardised < _ZERO),
            _ZERO,
        ) / abs(negative)
    psr = group.price_relation_rate
    assert psr is not None  # guaranteed by UnderlyingGroup.__post_init__
    amount = (positive_margin + negative_margin) * contracts * psr
    return OffsettingAmount(
        group_id=group.group_id,
        positions=tuple(positions),
        positive_standardised=positive,
        negative_standardised=negative,
        contracts_offset=contracts,
        positive_leg_margin=positive_margin,
        negative_leg_margin=negative_margin,
        price_relation_rate=psr,
        amount=amount,
    )


def apply_offsetting_amount(
    risk_margin_gross: Decimal, offset: Decimal
) -> Decimal:
    """``Rm = max(0, Rm_gross - OA)`` -- **INFERRED**, register id ``I4``.

    **This one function is the single largest interpretive gap in the model,
    and it is a separate function so that a correction has exactly one place
    to land.** Change it here and every ``Pgm`` in the module changes with
    it; nothing else needs touching.

    **What Phu luc 2 says: nothing.** Sections 6.1 and 6.2 -- the only two
    places ``MR`` is assembled -- never mention ``OA`` or *gia tri giam tru
    ky quy*. Section 2.2 defines ``OA`` and stops.

    **What QD 26 says** (Dieu 5.1.1, ``qd26`` L269-273) is the whole basis
    for connecting them: *"VSDC xac dinh ky quy rui ro can cu vao ty le ky
    quy ban dau VA gia tri giam tru ky quy"*, and diem a: *"Gia tri giam tru
    ky quy la so tien dieu chinh GIAM gia tri ky quy rui ro"*.

    Grade each claim separately, because it is easy to collapse them:

    ==================================================  ==============
    ``OA`` reduces **ky quy rui ro** and not some other  **VERIFIED**
    component -- Dieu 5.1.1.a says so in terms
    The ``Rm`` that enters section 6.2 is already net    **VERIFIED**
    of ``OA``, since it is the only ``Rm`` there is      as to direction
    The arithmetic is **subtraction**                    **INFERRED**
    It applies at the **group** level                    **INFERRED**
    The result is **floored at zero**                    **INFERRED**
    ==================================================  ==============

    *"Dieu chinh giam"* means "adjusts downward", not "subtract" -- a
    multiplicative reduction would satisfy the words equally. Two pieces of
    internal corroboration, both DERIVED and neither dispositive: section
    2.2's units are a VND amount of risk margin to give back and nothing
    else; and section 6.1's outer ``Max(..., 0)`` is dead code under every
    other reading, which is weak evidence that a drafter expected some
    component to be capable of going negative.

    **Do not ship this as "the regulation says".** :class:`GroupMargin`
    reports ``risk_margin_gross``, ``offsetting_amount`` and the netted
    ``risk_margin`` as three separately inspectable values for exactly that
    reason.
    """
    gross = _as_decimal(risk_margin_gross, 'risk_margin_gross')
    credit = _as_decimal(offset, 'offset')
    return max(_ZERO, gross - credit)


# ---------------------------------------------------------------------------
# Phu luc 2 section 3 -- ky quy song hanh (Sm), basis margin
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BasisMargin:
    """``Sm = Min(SMl, SMs)`` for one underlying, both legs shown."""

    underlying: str
    long_quantity: int
    short_quantity: int
    long_margin: Decimal
    short_margin: Decimal
    basis_margin_rate: Decimal
    amount: Decimal


def basis_margin(
    underlying: str,
    legs: Sequence[ContractLeg],
    parameters: UnderlyingParameters,
) -> BasisMargin:
    """``Sm`` for one underlying -- Phu luc 2 section 3.

    VERIFIED verbatim (``phuluc2`` L67, L72)::

        SM    = Min(SMl, SMs)
        SMl/s = P x S x M x SMrate

    ``P`` is the long or the short balance, ``S`` the underlying's closing
    price, ``M`` the multiplier, ``SMrate`` the basis margin rate.

    **This is the exact complement of ``Rm``'s netting.** ``Lk`` factorises
    to ``(Pm - Pb)(Sk - S)M``, so a fully hedged calendar book pays no risk
    margin at all; QD 26 Dieu 5.2 defines *ky quy song hanh* as covering the
    loss *"tang them so voi gia tri ky quy rui ro"* caused by the underlying
    and the futures not moving together. The two components are
    complementary by construction, and shipping one without the other
    under-margins every spread.

    **DERIVED:** since ``S``, ``M`` and ``SMrate`` are common to both legs,
    ``Sm`` reduces to ``min(P_long, P_short) x S x M x SMrate`` -- the
    **matched** portion of the book. A one-sided book has ``min = 0`` and
    pays no basis margin, which is right: there is no spread to mismatch.

    ``P`` is a **gross** balance summed across expiry months, per Dieu 5.2's
    *"ap dung cho mot tai san co so"* -- register id ``I8``. Under a net
    reading one of the two legs is always zero and ``Sm`` is identically
    zero, which would make the whole component dead.

    Where the underlying's contracts carry different multipliers each leg is
    accumulated with its own ``M`` (register id ``I18``); with one multiplier
    this is identical to the printed scalar formula.

    ``SMrate`` is an **input**. VSDC derives it as the 90th percentile of
    ``SPR_t = |(rt1 - rt2)/St|`` over (spot month, far month) pairs across an
    observation window -- ``rt1`` and ``rt2`` being 2-business-day **DSP/FSP
    changes**, absolute and not returns, because dividing by ``St`` is
    dimensionally wrong otherwise. Note that forces the **opposite** reading
    of *"bien dong gia"* from the one section 2.2.e forces
    (``SOURCE_DEFECTS['D8']``). The window is *"mot khoang thoi gian nhat
    dinh"* in the rule and 252 days only in the worked example, so 252 is
    example-sourced. And the per-pair rates' fate is never stated
    (``SOURCE_DEFECTS['D9']``): one pooled percentile is applied per
    underlying. **None of that is computed here.**
    """
    if parameters.underlying != underlying:
        raise MarginInputError(
            f'parameters are for {parameters.underlying}, not {underlying}'
        )
    mine = [leg for leg in legs if leg.underlying == underlying]
    if not mine:
        raise MarginInputError(f'{underlying}: no legs supplied')
    s = parameters.closing_price
    rate = parameters.basis_margin_rate
    long_total = _ZERO
    short_total = _ZERO
    for leg in mine:
        long_total += Decimal(leg.long_quantity) * s * leg.multiplier * rate
        short_total += Decimal(leg.short_quantity) * s * leg.multiplier * rate
    return BasisMargin(
        underlying=underlying,
        long_quantity=sum(leg.long_quantity for leg in mine),
        short_quantity=sum(leg.short_quantity for leg in mine),
        long_margin=long_total,
        short_margin=short_total,
        basis_margin_rate=rate,
        amount=min(long_total, short_total),
    )


# ---------------------------------------------------------------------------
# Phu luc 2 section 4 -- ky quy chuyen giao (Dm), delivery margin. DEFERRED.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeliveryPosition:
    """A government-bond futures position at physical settlement. DEFERRED.

    ``buy_contracts`` is ``Aq``, *"So luong HDTL mua trai phieu"*, the side
    that receives bonds and pays cash; ``deliver_contracts`` is ``Tq``, *"So
    luong HDTL chuyen giao trai phieu"*, the delivering short side.

    ``highest_price`` and ``lowest_price`` are ``Hp`` and ``Lp``. Section 4.3
    says they come from the section 1.2 scenario grid, so they default to the
    ``k = +10`` and ``k = -10`` prices computed from the underlying's
    parameters -- **which inherits ``SOURCE_DEFECTS['D1']`` in full**: under
    the literal published text those two prices are equal and ``DRM``
    collapses. Supply them explicitly to use VSDC's own numbers.
    """

    contract_code: str
    underlying: str
    buy_contracts: int
    deliver_contracts: int
    final_settlement_price: Decimal
    close_price: Decimal
    multiplier: Decimal
    highest_price: Optional[Decimal] = None
    lowest_price: Optional[Decimal] = None

    def __post_init__(self) -> None:
        for name in ('buy_contracts', 'deliver_contracts'):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise MarginInputError(
                    f'{self.contract_code}: {name} must be an int'
                )
            if value < 0:
                raise MarginInputError(
                    f'{self.contract_code}: {name} must not be negative'
                )
        for name in ('final_settlement_price', 'close_price', 'multiplier'):
            object.__setattr__(
                self, name, _as_decimal(getattr(self, name), name)
            )
        for name in ('highest_price', 'lowest_price'):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _as_decimal(value, name))


@dataclass(frozen=True)
class DeliveryMargin:
    """``Dm``, its two components, and the price bounds ``DRM`` used."""

    contract_code: str
    mark_to_market: Decimal
    delivery_risk: Decimal
    highest_price: Decimal
    lowest_price: Decimal
    amount: Decimal


def delivery_margin(
    position: DeliveryPosition,
    parameters: Optional[UnderlyingParameters] = None,
) -> DeliveryMargin:
    """``Dm = MTM + DRM`` -- section 4. **DEFERRED. NOT FOR BUILDING ON.**

    **Read this before using the number.** Government-bond futures work is
    deferred by author decision. The arithmetic below is implemented so the
    model is complete and so nobody re-derives it later, and it carries three
    disclaimers that no test can discharge:

    1. **It has never been checked against reality.** No GB future exists in
       any corpus this project holds -- no TPCP tickers, no bond price index,
       no HNX government-bond yield curve -- so every test of this function
       is a test of its arithmetic against a hand computation, and nothing
       more. It is untested against a real VSDC delivery margin.
    2. **Its underlying is undefined without Phu luc 8, which we do not
       have.** Section 4.2 says the underlying for ``Rm``, ``Sm`` **and**
       ``Dm`` on a GB future is the **cheapest-to-deliver** bond of the spot
       month, *"theo huong dan tai Phu luc 8 Quy che nay"*. Without it the
       price series ``S`` itself is undefined, so no GB-futures margin number
       can be produced at all. Worse, QD 26 Dieu 24.1 cites Phu luc 8 for a
       completely different subject (electronic documents) while Dieu 30.4
       cites Phu luc 9, so one of the two references is wrong -- anyone
       retrieving "Phu luc 8" must check what they actually got
       (``SOURCE_DEFECTS['D11']`` in the spec).
    3. **``Dm = MTM + DRM`` is INFERRED** (register id ``I11``). Section 4.1
       says only that delivery margin *"gom hai gia tri thanh phan"* and
       never writes the combination. Addition is the obvious reading and the
       only one consistent with ``Dm`` appearing as a single additive term in
       section 6.2.

    The two components, VERIFIED verbatim (``phuluc2`` L91, L100)::

        MTM = Aq x (FSP - Cp) x m  +  Tq x (Cp - FSP) x m
        DRM = Aq x (Cp - Lp) x m  +  Tq x (Hp - Cp) x m

    ``MTM`` charges each side the FSP-against-close basis in its adverse
    direction and is **signed** -- it can be negative. ``DRM`` charges the
    buyer for a fall to ``Lp`` and the seller for a rise to ``Hp``, so it is
    non-negative whenever ``Lp <= Cp <= Hp`` (DERIVED).

    **When it applies, and the hole in that.** Section 6.2 says ``Dm`` is
    computed on the **last trading day E** and on **E+1**, and only for
    contracts *"chua duoc nop trai phieu chuyen giao"*. Settlement is
    **E+3**, and E+2 is a live operational day under QD 26 Dieu 22.4, so the
    literal reading leaves an undelivered position unmargined for delivery
    risk on E+2 -- ``SOURCE_DEFECTS['D10']``. **The window is not silently
    extended here.** This function does not decide the date at all: it has no
    calendar, and passing a :class:`DeliveryPosition` to
    :func:`required_margin` *is* the caller asserting that today is E or E+1
    and that the bond has not been delivered.
    """
    hp = position.highest_price
    lp = position.lowest_price
    if hp is None or lp is None:
        if parameters is None:
            raise MarginInputError(
                f'{position.contract_code}: supply highest_price and '
                'lowest_price, or the underlyings parameters so they can be '
                'read off the section 1.2 scenario grid'
            )
        if parameters.underlying != position.underlying:
            raise MarginInputError(
                f'parameters are for {parameters.underlying}, not '
                f'{position.underlying}'
            )
        grid = scenario_prices(
            parameters.closing_price, parameters.initial_margin_ratio
        )
        lp = grid[0] if lp is None else lp
        hp = grid[-1] if hp is None else hp
    aq = Decimal(position.buy_contracts)
    tq = Decimal(position.deliver_contracts)
    fsp = position.final_settlement_price
    cp = position.close_price
    m = position.multiplier
    mtm = aq * (fsp - cp) * m + tq * (cp - fsp) * m
    drm = aq * (cp - lp) * m + tq * (hp - cp) * m
    return DeliveryMargin(
        contract_code=position.contract_code,
        mark_to_market=mtm,
        delivery_risk=drm,
        highest_price=hp,
        lowest_price=lp,
        amount=mtm + drm,
    )


# ---------------------------------------------------------------------------
# Phu luc 2 section 5 -- ky quy toi thieu (MM), minimum margin
# ---------------------------------------------------------------------------


def minimum_margin_factor(
    minimum_margin_rate: Decimal, multiplier: Decimal, close_price: Decimal
) -> Decimal:
    """``MF = R x M x St`` -- one contract's close-out cost, section 5.2.

    VERIFIED verbatim (``phuluc2`` L119). ``R`` is the mean (liquid product)
    or median (illiquid) of
    ``(lowest ask - highest bid) / (lowest ask + highest bid)`` taken per
    matched trade over at least 252 trading days -- and **252 is in the rule
    here**, unlike section 3.3's, where it is only in the worked example.

    **DERIVED, and a good check that the formula was read right:**
    ``(ask - bid)/(ask + bid) = (ask - bid)/(2 x mid)`` is the **half
    relative spread**, so ``MF`` is one contract's expected cost of crossing
    the book once. That is exactly the *"gia dich vu giao dich dong vi the
    bat buoc"* -- forced close-out service cost -- that QD 26 Dieu 5.4 says
    ``MM`` exists to cover. ``MM`` is a **cost floor, not a risk charge**,
    which is why section 6.2 applies it with ``Max`` rather than adding it.

    **``MF`` is per CONTRACT.** Section 5.1 calls it *"cho mot thang dao
    han"* (per expiry month) and section 5.2's own heading says *"tren mot
    hop dong"* (per contract). Only the per-contract reading balances
    ``MM = P x MF`` dimensionally, so section 5.1's phrase is read as "the
    rate is determined separately for each expiry month".
    ``SOURCE_DEFECTS['D12']``.

    **SILENT -- what makes a product liquid.** The mean/median switch is a
    real fork -- the median is materially lower on a right-skewed spread
    distribution -- and the criterion is not given anywhere in either
    document. That is one more reason ``R`` is an input.
    """
    r = _as_decimal(minimum_margin_rate, 'minimum_margin_rate')
    m = _as_decimal(multiplier, 'multiplier')
    st = _as_decimal(close_price, 'close_price')
    return r * m * st


@dataclass(frozen=True)
class MinimumMargin:
    """``MM = P x MF`` for one underlying, summed over its contracts."""

    underlying: str
    gross_quantity: int
    amount: Decimal
    undetermined_contracts: Tuple[str, ...] = ()

    @property
    def has_last_trading_day_leg(self) -> bool:
        """Whether some leg contributed zero because ``MF`` is undetermined.

        Register id ``I10``. Worth surfacing on the result rather than only
        in a docstring, because it changes ``Pgm``'s second operand and it
        is invisible in the total.
        """
        return bool(self.undetermined_contracts)


def minimum_margin(
    underlying: str,
    legs: Sequence[ContractLeg],
    parameters: UnderlyingParameters,
) -> MinimumMargin:
    """``MM`` for one underlying -- Phu luc 2 section 5.1.

    ``MM = P x MF``, VERIFIED verbatim, with ``P`` the end-of-day futures
    position balance.

    ``P`` is a **gross** contract count -- register id ``I9``. Section 5.1
    says only *"So du vi the HDTL cuoi ngay"*; a close-out cost must scale
    with the contracts that have to be *closed*, so a net reading
    under-charges a spread book that still has two legs to unwind.

    On the **last trading day** a leg contributes zero, because section 5.1
    says ``MF`` is *"khong duoc xac dinh tai ngay giao dich cuoi cung"* and
    ``Max((Rm+Sm+Dm), MM)`` then has no second operand -- register id
    ``I10``. Note how neatly it dovetails: ``MM`` switches **off** on exactly
    the day ``Dm`` switches **on**. The two components hand over. Neither
    document says so, which is why the affected contract codes are reported
    in :attr:`MinimumMargin.undetermined_contracts` rather than absorbed.
    """
    if parameters.underlying != underlying:
        raise MarginInputError(
            f'parameters are for {parameters.underlying}, not {underlying}'
        )
    mine = [leg for leg in legs if leg.underlying == underlying]
    if not mine:
        raise MarginInputError(f'{underlying}: no legs supplied')
    total = _ZERO
    undetermined: List[str] = []
    for leg in mine:
        if leg.is_last_trading_day:
            undetermined.append(leg.contract_code)
            continue
        rate = leg.minimum_margin_rate
        assert rate is not None  # guaranteed by ContractLeg.__post_init__
        factor = minimum_margin_factor(
            rate, leg.multiplier, parameters.closing_price
        )
        total += Decimal(leg.gross_quantity) * factor
    return MinimumMargin(
        underlying=underlying,
        gross_quantity=sum(leg.gross_quantity for leg in mine),
        amount=total,
        undetermined_contracts=tuple(undetermined),
    )


# ---------------------------------------------------------------------------
# Phu luc 2 section 6 -- assembly: Pgm per group, MR per account
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupMargin:
    """``Pgm = Max((Rm + Sm + Dm), MM)`` for one underlying-asset group.

    Every intermediate is a field, and the three ``risk_margin*`` fields are
    deliberately separate: ``risk_margin_gross`` is computed from a
    reconstructed scenario grid (``I1``) and ``risk_margin`` additionally
    applies an inferred subtraction (``I4``). A caller reporting a number
    should know which of the two they are quoting.
    """

    group_id: str
    underlyings: Tuple[str, ...]
    risk_margins: Tuple[RiskMargin, ...]
    basis_margins: Tuple[BasisMargin, ...]
    minimum_margins: Tuple[MinimumMargin, ...]
    delivery_margins: Tuple[DeliveryMargin, ...]
    risk_margin_gross: Decimal
    offsetting_amount: Optional[OffsettingAmount]
    risk_margin: Decimal
    basis_margin: Decimal
    delivery_margin: Decimal
    minimum_margin: Decimal
    risk_sum: Decimal
    amount: Decimal

    @property
    def minimum_margin_binds(self) -> bool:
        """Whether the ``MM`` floor, not the risk sum, set ``Pgm``.

        The floor binding is normal for a nearly flat book and is the single
        most useful thing to know when a ``Pgm`` looks too small to be a risk
        number: it is not a risk number, it is a close-out cost.
        """
        return self.minimum_margin > self.risk_sum


@dataclass(frozen=True)
class MarginRequirement:
    """``MR = Max(SUM Pgm, 0)`` for one investor or member account."""

    account_id: str
    groups: Tuple[GroupMargin, ...]
    amount: Decimal

    def group(self, group_id: str) -> GroupMargin:
        for item in self.groups:
            if item.group_id == group_id:
                return item
        raise KeyError(group_id)

    @property
    def outer_floor_binds(self) -> bool:
        """Whether ``Max(SUM Pgm, 0)`` actually did anything. **DERIVED.**

        It never does, and that is worth being able to assert. Every
        component of section 6.2 is non-negative on its face and ``Pgm`` is a
        ``Max`` against ``MM >= 0``, so ``Pgm >= 0`` and the sum with it.
        The clause exists in the gazetted text anyway, which is weak evidence
        that a drafter expected some component to be capable of going
        negative -- and ``Rm_gross - OA`` is the obvious candidate, which is
        one of the two internal corroborations for
        :func:`apply_offsetting_amount`.
        """
        return sum((g.amount for g in self.groups), _ZERO) < _ZERO


def group_margin(
    group: UnderlyingGroup,
    legs: Sequence[ContractLeg],
    parameters: Mapping[str, UnderlyingParameters],
    delivery: Sequence[DeliveryPosition] = (),
) -> GroupMargin:
    """``Pgm`` for one group -- Phu luc 2 section 6.2.

    VERIFIED verbatim (``phuluc2`` L133): ``Pgm = Max((Rm + Sm + Dm), MM)``.

    **The roll-up from underlying to group is INFERRED** -- register id
    ``I12``. Section 6.2 is written with scalar ``Rm``, ``Sm``, ``Dm`` and
    ``MM`` but is defined **per group**, and a group may hold several
    underlyings. How the per-underlying values combine is not stated;
    summation is adopted, and it is the conservative direction. This and
    :func:`apply_offsetting_amount` are the least-sourced part of the whole
    model, which is why every intermediate survives into
    :class:`GroupMargin`.

    ``OA`` is computed only for a group of two or more; a singleton group has
    ``offsetting_amount is None`` and ``risk_margin == risk_margin_gross``.
    That is not a shortcut -- QD 26 Dieu 5.1.1.a conditions the reduction on
    *"tu hai tai san co so tro len"*, so for a single-underlying account the
    relief is zero **by the rule**.
    """
    members = group.underlyings
    for name in members:
        if name not in parameters:
            raise MarginInputError(
                f'{group.group_id}: no UnderlyingParameters for {name}'
            )
    risks = tuple(
        risk_margin(name, legs, parameters[name]) for name in members
    )
    bases = tuple(
        basis_margin(name, legs, parameters[name]) for name in members
    )
    minimums = tuple(
        minimum_margin(name, legs, parameters[name]) for name in members
    )
    deliveries: List[DeliveryMargin] = []
    for position in delivery:
        if position.underlying not in members:
            continue
        deliveries.append(
            delivery_margin(position, parameters[position.underlying])
        )
    by_underlying = {risk.underlying: risk for risk in risks}
    gross = sum((risk.gross for risk in risks), _ZERO)
    offset: Optional[OffsettingAmount] = None
    if not group.is_singleton:
        offset = offsetting_amount(group, legs, parameters, by_underlying)
    credit = offset.amount if offset is not None else _ZERO
    net_risk = apply_offsetting_amount(gross, credit)
    basis_total = sum((b.amount for b in bases), _ZERO)
    delivery_total = sum((d.amount for d in deliveries), _ZERO)
    minimum_total = sum((m.amount for m in minimums), _ZERO)
    risk_sum = net_risk + basis_total + delivery_total
    return GroupMargin(
        group_id=group.group_id,
        underlyings=members,
        risk_margins=risks,
        basis_margins=bases,
        minimum_margins=minimums,
        delivery_margins=tuple(deliveries),
        risk_margin_gross=gross,
        offsetting_amount=offset,
        risk_margin=net_risk,
        basis_margin=basis_total,
        delivery_margin=delivery_total,
        minimum_margin=minimum_total,
        risk_sum=risk_sum,
        amount=max(risk_sum, minimum_total),
    )


def required_margin(
    legs: Sequence[ContractLeg],
    parameters: Iterable[UnderlyingParameters],
    *,
    account_id: str = '',
    groups: Sequence[UnderlyingGroup] = (),
    delivery: Sequence[DeliveryPosition] = (),
) -> MarginRequirement:
    """``MR = Max(SUM Pgm, 0)`` -- Phu luc 2 section 6.1, VERIFIED verbatim.

    **The unit of assessment is the whole account.** QD 26 Dieu 5.5:
    ``MR`` is computed *"sau khi ket thuc phien giao dich"* -- after the
    session closes -- *"cho danh muc vi the tren tung tai khoan giao dich cua
    nha dau tu va tai khoan cua chinh thanh vien bu tru"*. Per investor
    trading account, plus the member's own. Not per position: a two-leg
    calendar spread on one account is one ``MR`` calculation, not two.

    **Below the account the unit is the underlying-asset GROUP, not the
    contract.** Any underlying not named in ``groups`` forms a **singleton
    group** with ``OA = 0`` -- register id ``I3``. Section 2.1 only provides
    for groups of two or more and never says what happens to an underlying in
    no group, which is the ordinary case and the only case this project's
    corpora contain; section 6.1 sums ``Pgm`` over *"cac nhom tai san co so"*
    so an ungrouped underlying must still produce a ``Pgm``, or its risk
    vanishes from ``MR`` entirely. That is the only reading under which
    ``MR`` is well-defined for a single-product account, and it is not in the
    text.

    Group **exclusivity** is enforced: section 2.1 says *"mot tai san co so
    chi thuoc mot nhom tai san co so"*, so an underlying named in two
    supplied groups raises rather than being double-counted.

    ``delivery`` carries government-bond futures positions at physical
    settlement and is **deferred work** -- see :func:`delivery_margin` before
    passing anything.
    """
    legs = tuple(legs)
    if not legs:
        raise MarginInputError(
            'no legs: an account with no derivatives position has no MR to '
            'compute. Do not call this with an empty book and read the zero '
            'as a margin number.'
        )
    by_name: dict = {}
    for params in parameters:
        if params.underlying in by_name:
            raise MarginInputError(
                f'duplicate UnderlyingParameters for {params.underlying}'
            )
        by_name[params.underlying] = params
    ordered: List[str] = []
    for leg in legs:
        if leg.underlying not in ordered:
            ordered.append(leg.underlying)
    missing = [name for name in ordered if name not in by_name]
    if missing:
        raise MarginInputError(
            f'no UnderlyingParameters for {", ".join(sorted(missing))}. A '
            'missing underlying is not a flat one -- supply its closing '
            'price, initial margin ratio and SMrate.'
        )
    seen: dict = {}
    for group in groups:
        for name in group.underlyings:
            if name in seen:
                raise MarginInputError(
                    f'{name} is in both group {seen[name]} and group '
                    f'{group.group_id}. Phu luc 2 section 2.1: "mot tai san '
                    'co so chi thuoc mot nhom tai san co so".'
                )
            seen[name] = group.group_id
    resolved: List[UnderlyingGroup] = []
    for group in groups:
        held = [name for name in group.underlyings if name in ordered]
        if not held:
            continue
        if len(held) != len(group.underlyings):
            raise MarginInputError(
                f'{group.group_id}: the account holds {held} but the group '
                f'is {list(group.underlyings)}. A partially held group has '
                'no offsetting amount defined in the source; drop the '
                'unheld members from the group you supply, deliberately.'
            )
        resolved.append(group)
    for name in ordered:
        if name not in seen:
            resolved.append(
                UnderlyingGroup(group_id=name, underlyings=(name,))
            )
    computed = tuple(
        group_margin(group, legs, by_name, delivery) for group in resolved
    )
    total = sum((item.amount for item in computed), _ZERO)
    return MarginRequirement(
        account_id=account_id,
        groups=computed,
        amount=max(total, _ZERO),
    )


# ---------------------------------------------------------------------------
# QD 26 Dieu 13 -- the violation test, and the timeline it drives
# ---------------------------------------------------------------------------


class Checkpoint(str, Enum):
    """The three fixed instants of QD 26 Dieu 13.2 -- VERIFIED.

    Post-KRX margin monitoring is **not continuous**. ``MR`` is an
    end-of-day quantity (Dieu 5.5) and it is policed at three named clock
    times, each with a different action:

    ``OPEN_0930``
        Dieu 13.2.a. Against the requirement determined **on the previous
        working day**, VSDC identifies accounts **newly** in violation --
        expressly *"khong bao gom cac tai khoan dang vi pham"* -- asks HNX to
        suspend them, and tells the clearing member: no opening trades, only
        *"giao dich doi ung de dong vi the"*.
    ``MIDDAY_1400``
        Dieu 13.2.b. VSDC re-checks **all** violating accounts; those that
        have met the requirement as notified on the previous trading day are
        restored to trading.
    ``CLOSE_1630``
        Dieu 13.1 and 13.2.c. VSDC determines ``MR`` afresh per account and
        notifies the member; a suspended account whose assets are **equal to
        or greater than** ``MR`` is restored; and a shortfall must be topped
        up **before 09h30 the next trading day**.
    """

    OPEN_0930 = 'open_0930'
    MIDDAY_1400 = 'midday_1400'
    CLOSE_1630 = 'close_1630'


#: The wall-clock time of each checkpoint, VERIFIED from QD 26 Dieu 13.2.
#:
#: These are Hanoi local times as printed. No timezone is attached, because
#: attaching one would be this module reaching for a fact it was not given.
CHECKPOINT_TIME: Mapping[Checkpoint, time] = {
    Checkpoint.OPEN_0930: time(9, 30),
    Checkpoint.MIDDAY_1400: time(14, 0),
    Checkpoint.CLOSE_1630: time(16, 30),
}


class MarginViolationState(str, Enum):
    """Where an account stands under Dieu 13. **State, not an event.**

    A margin violation persists across sessions until it is cured or the
    positions are closed out by another clearing member. Modelling it as a
    one-shot event loses the two things the article is actually about: that
    a suspended account keeps its suspension overnight, and that the
    03-working-day close-out clock is running the whole time.

    ``COMPLIANT``
        Margin assets are at or above the requirement.
    ``NOTIFIED``
        An end-of-day determination found assets below ``MR`` and VSDC
        notified the member. Trading is **not yet** suspended -- the
        suspension is the 09h30 checkpoint's action and only that
        checkpoint's (register id ``I21``) -- and the top-up is due before
        09h30 on the next trading day.
    ``SUSPENDED``
        The 09h30 checkpoint confirmed the shortfall. HNX has been asked to
        suspend the account: no opening new positions, offsetting trades to
        close only.
    ``CLOSED_OUT``
        Uncured for 03 working days after VSDC's notice. Another clearing
        member has been directed to close the positions. Terminal.
    """

    COMPLIANT = 'compliant'
    NOTIFIED = 'notified'
    SUSPENDED = 'suspended'
    CLOSED_OUT = 'closed_out'

    @property
    def permits_opening(self) -> bool:
        """Whether an order that would OPEN or increase a position is allowed.

        Dieu 13.2.a, verbatim: *"yeu cau khong thuc hien giao dich mo moi vi
        the tren tai khoan vi pham, ngoai tru giao dich doi ung de dong vi
        the"*. A notified-but-not-yet-suspended account may still trade
        freely: the article gives the restriction to the suspension, not to
        the notice.
        """
        return self in (
            MarginViolationState.COMPLIANT, MarginViolationState.NOTIFIED
        )

    @property
    def permits_closing(self) -> bool:
        """Always ``True``. Closing is the cure Dieu 13.3.b prescribes."""
        return True

    @property
    def is_violation(self) -> bool:
        """Whether VSDC counts this among *"tai khoan vi pham"*."""
        return self in (
            MarginViolationState.NOTIFIED,
            MarginViolationState.SUSPENDED,
            MarginViolationState.CLOSED_OUT,
        )


class MarginEventKind(str, Enum):
    """One per state transition. Every transition emits exactly one."""

    SHORTFALL_NOTIFIED = 'shortfall_notified'
    SUSPENDED = 'suspended'
    CURED = 'cured'
    RESTORED = 'restored'
    CLOSE_OUT_DIRECTED = 'close_out_directed'


@dataclass(frozen=True)
class MarginEvent:
    """What changed, when, against which requirement, and by how much."""

    kind: MarginEventKind
    checkpoint: Checkpoint
    on: date
    at: time
    previous_state: MarginViolationState
    state: MarginViolationState
    margin_assets: Decimal
    required_margin: Decimal
    shortfall: Decimal
    notice_date: Optional[date] = None
    cure_by_date: Optional[date] = None
    cure_by_time: time = time(9, 30)
    working_days_elapsed: int = 0
    detail: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MarginObservation:
    """One checkpoint reading fed to :class:`MarginViolationMonitor`.

    ``required_margin`` is supplied **only** at :attr:`Checkpoint.CLOSE_1630`,
    because only the 16h30 checkpoint recomputes it (Dieu 13.2.c). The 09h30
    and 14h00 checkpoints test against the requirement VSDC **notified on the
    previous working day**, which the monitor is already carrying; supplying
    one there is refused rather than quietly ignored, since a caller who
    passes a fresh number there has misread the article.

    ``margin_assets`` is *gia tri tai san ky quy hop le* -- the valid margin
    asset value. It is a supplied scalar and this module does **not** value
    collateral: QD 26 Dieu 8.1 announces the valuation formula and the
    expression is missing from the source (``SOURCE_DEFECTS['D3']``), so the
    haircuts (5% / 30% / 40%, Dieu 9.1) and the 80% minimum cash ratio are
    known while the expression combining them is not. Guessing it here would
    put an invented number on the other side of the only test that matters.
    """

    checkpoint: Checkpoint
    on: date
    margin_assets: Decimal
    required_margin: Optional[Decimal] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, 'margin_assets',
            _as_decimal(self.margin_assets, 'margin_assets'),
        )
        if self.checkpoint is Checkpoint.CLOSE_1630:
            if self.required_margin is None:
                raise MarginInputError(
                    'the 16h30 checkpoint determines MR afresh (QD 26 Dieu '
                    '13.2.c) -- supply required_margin'
                )
            object.__setattr__(
                self, 'required_margin',
                _as_decimal(self.required_margin, 'required_margin'),
            )
        elif self.required_margin is not None:
            raise MarginInputError(
                f'the {CHECKPOINT_TIME[self.checkpoint]:%H:%M} checkpoint '
                'tests against the requirement determined on the PREVIOUS '
                'working day (QD 26 Dieu 13.2.a, 13.2.b), which the monitor '
                'already carries. Do not supply a fresh required_margin.'
            )

    @property
    def at(self) -> time:
        return CHECKPOINT_TIME[self.checkpoint]


def is_margin_violation(
    margin_assets: Decimal, required_margin: Decimal
) -> bool:
    """``margin assets < required margin``. **The whole test.** VERIFIED.

    QD 26 Dieu 13.1, verbatim (``qd26`` L497-498): *"Truong hop gia tri tai
    san ky quy tren tai khoan nha dau tu **nho hon** gia tri ky quy yeu cau,
    thanh vien bu tru co trach nhiem nop bo sung truoc 09h30 ngay giao dich
    lien ke tiep theo"*.

    **There is no ratio, no threshold and no ladder in Dieu 13.** Not 80%,
    not 90%, not 100%. The article was read in full. The 80/90/100 ladder a
    reader may be looking for is **Dieu 29** and it applies to *gioi han vi
    the* -- a count of contracts against a published position cap. Different
    numerator, different denominator, different units, different remedy. It
    is not implemented in this module and must not be added to it.

    **Equality is cured, not breached.** Dieu 13.2.c restores an account
    whose assets are *"bang hoac lon hon muc ky quy yeu cau"* -- equal to or
    greater than. So the comparison is strict ``<``, and ``assets == MR`` is
    compliant. This differs by one tick from the pre-KRX path in
    ``deposit.py``, which treats equality as a breach; that difference is
    deliberate on both sides and pinned by a test on each.
    """
    assets = _as_decimal(margin_assets, 'margin_assets')
    required = _as_decimal(required_margin, 'required_margin')
    return assets < required


class MarginViolationMonitor:
    """QD 26 Dieu 13, as a state machine that persists across sessions.

    **The violation is state, not an event.** The account carries it from one
    session to the next until it is cured or another clearing member closes
    the positions, and the 03-working-day clock runs the whole time. A
    one-shot "margin call happened" boolean cannot express a suspension that
    survives overnight, and cannot express the difference between an account
    that cured at 09h30 and one that cured at 14h00.

    Drive it by feeding :class:`MarginObservation` at the three checkpoints.
    Each call returns the events the transition emitted -- **exactly one per
    transition, zero when nothing changed** -- and they also accumulate on
    :attr:`events`.

    The transitions, each sourced::

        COMPLIANT  --16h30, assets < MR-->            NOTIFIED
            Dieu 13.1: VSDC determines MR by 16h30 and notifies the member;
            the top-up is due before 09h30 the next trading day.

        NOTIFIED   --09h30, still short-->            SUSPENDED
            Dieu 13.2.a: a NEW violation, suspended, opening trades barred
            and only offsetting closes permitted.

        NOTIFIED   --09h30 or later, assets >= MR-->  COMPLIANT
            Topped up before the deadline; never suspended.

        SUSPENDED  --14h00 or 16h30, assets >= MR-->  COMPLIANT
            Dieu 13.2.b restores at 14h00; Dieu 13.2.c restores at 16h30 on
            "bang hoac lon hon" -- equality restores.

        NOTIFIED or SUSPENDED --03 working days-->    CLOSED_OUT
            Dieu 13.3.b: VSDC directs ANOTHER clearing member to place the
            offsetting trades; the resulting positions are then transferred
            to the violating member to net off.

    **Cure is evaluated before escalation** at every checkpoint, so an
    account that tops up on the morning of the third day is restored rather
    than closed out. The source does not order them; this order is the only
    one that does not close out an account that has just complied.

    **A skipped checkpoint advances nothing.** If the caller does not feed an
    observation, no state changes and no working day is counted. This mirrors
    ``deposit.py``'s ``MarginMonitor``, where an ``INDETERMINATE`` mark
    advances no state: a deadline that passes during a blind stretch survives
    it, rather than being silently deemed to have expired.

    Parameters
    ----------
    account_id:
        Carried onto nothing; kept for the caller's own reporting.
    cure_working_days:
        Dieu 13.3.b's *"trong thoi han 03 ngay lam viec"*. A parameter and
        not a constant because the article's own cross-reference is broken
        (``SOURCE_DEFECTS['D13']``: khoan 3.b points at *"diem a khoan 1"*
        and khoan 1 has no lettered points; the intended target is almost
        certainly diem a khoan **2**, the 09h30 checkpoint, which is how it
        is read here -- the clock starts at the notice, and the notice is the
        16h30 determination that the 09h30 check then acts on).
    include_notice_day:
        Whether the notice day itself counts toward the 03 days. *"Ke tu
        ngay"* admits both readings and the source does not resolve it --
        register id ``I20``. Default ``False``: the count runs over working
        days strictly after the notice.
    next_trading_day:
        Optional ``date -> date``. Supplied, it fills
        :attr:`MarginEvent.cure_by_date` with the 09h30 deadline's date.
        Omitted, the deadline is still expressed -- ``cure_by_time`` is
        always 09h30 -- and the date is left ``None`` rather than guessed,
        because this module has no calendar and will not acquire one.

    Working days are counted as **distinct observation dates after the
    notice**. Each observed date is a working day by construction, which is
    what makes this pure: the alternative is a calendar, and a calendar is a
    data source.
    """

    def __init__(
        self,
        *,
        account_id: str = '',
        cure_working_days: int = 3,
        include_notice_day: bool = False,
        next_trading_day: Optional[Callable[[date], date]] = None,
    ) -> None:
        if cure_working_days < 1:
            raise MarginInputError(
                f'cure_working_days must be at least 1, got '
                f'{cure_working_days}'
            )
        self.account_id = account_id
        self.cure_working_days = cure_working_days
        self.include_notice_day = include_notice_day
        self._next_trading_day = next_trading_day
        self._state = MarginViolationState.COMPLIANT
        self._required: Optional[Decimal] = None
        self._notice_date: Optional[date] = None
        self._observed_dates: List[date] = []
        self._events: List[MarginEvent] = []

    # -- read-only view ---------------------------------------------------

    @property
    def state(self) -> MarginViolationState:
        return self._state

    @property
    def notified_requirement(self) -> Optional[Decimal]:
        """The last ``MR`` notified -- what 09h30 and 14h00 test against."""
        return self._required

    @property
    def notice_date(self) -> Optional[date]:
        """The date of the notice the close-out clock runs from."""
        return self._notice_date

    @property
    def events(self) -> Tuple[MarginEvent, ...]:
        return tuple(self._events)

    @property
    def permits_opening(self) -> bool:
        return self._state.permits_opening

    def working_days_since_notice(self, on: Optional[date] = None) -> int:
        """Working days elapsed, counted as distinct observed dates.

        Each observed date is a working day by construction -- which is what
        keeps this pure. The alternative is a calendar, and a calendar is a
        data source.

        Register id ``I20`` for the inclusive/exclusive reading of *"ke tu
        ngay"*: with ``include_notice_day`` false, the notice day itself is
        not counted and an account notified at 16h30 on D0 is closed out at
        the first checkpoint of D3.
        """
        if self._notice_date is None:
            return 0
        days = set(self._observed_dates)
        if on is not None:
            days.add(on)
        if self.include_notice_day:
            return len([d for d in days if d >= self._notice_date])
        return len([d for d in days if d > self._notice_date])

    # -- the machine ------------------------------------------------------

    def observe(
        self, observation: MarginObservation
    ) -> Tuple[MarginEvent, ...]:
        """Feed one checkpoint. Returns the events this transition emitted."""
        if self._observed_dates and observation.on < self._observed_dates[-1]:
            raise MarginTimelineError(
                f'observations must not go backwards: {observation.on} '
                f'after {self._observed_dates[-1]}'
            )
        required = observation.required_margin
        if required is None:
            if self._required is None:
                raise MarginTimelineError(
                    f'the {observation.at:%H:%M} checkpoint tests against '
                    '"muc ky quy yeu cau xac dinh tai ngay lam viec lien '
                    'truoc" (QD 26 Dieu 13.2.a) and no end-of-day '
                    'determination has been fed yet. Feed a CLOSE_1630 '
                    'observation first.'
                )
            required = self._required
        elapsed = self.working_days_since_notice(observation.on)
        if observation.on not in self._observed_dates:
            self._observed_dates.append(observation.on)
        emitted: List[MarginEvent] = []
        previous = self._state
        short = is_margin_violation(observation.margin_assets, required)
        shortfall = max(_ZERO, required - observation.margin_assets)

        if self._state is MarginViolationState.CLOSED_OUT:
            self._remember(observation, required)
            return ()

        if not short and self._state.is_violation:
            kind = (
                MarginEventKind.RESTORED
                if self._state is MarginViolationState.SUSPENDED
                else MarginEventKind.CURED
            )
            self._state = MarginViolationState.COMPLIANT
            emitted.append(
                self._event(
                    kind, observation, previous, required, shortfall, elapsed,
                    detail={
                        'cited': 'QD 26 Dieu 13.2.b' if observation.checkpoint
                        is Checkpoint.MIDDAY_1400 else 'QD 26 Dieu 13.2.c',
                        'equality_is_cured': 'assets >= MR, Dieu 13.2.c',
                    },
                )
            )
            self._notice_date = None
            self._remember(observation, required)
            return tuple(emitted)

        if short and self._state.is_violation:
            if elapsed >= self.cure_working_days:
                self._state = MarginViolationState.CLOSED_OUT
                emitted.append(
                    self._event(
                        MarginEventKind.CLOSE_OUT_DIRECTED, observation,
                        previous, required, shortfall, elapsed,
                        detail={
                            'cited': 'QD 26 Dieu 13.3.b',
                            'action': (
                                'VSDC directs another clearing member to '
                                'place the offsetting trades; the resulting '
                                'positions transfer to the violating member '
                                'to net off'
                            ),
                        },
                    )
                )
                self._remember(observation, required)
                return tuple(emitted)
            if (
                self._state is MarginViolationState.NOTIFIED
                and observation.checkpoint is Checkpoint.OPEN_0930
            ):
                self._state = MarginViolationState.SUSPENDED
                emitted.append(
                    self._event(
                        MarginEventKind.SUSPENDED, observation, previous,
                        required, shortfall, elapsed,
                        detail={
                            'cited': 'QD 26 Dieu 13.2.a',
                            'restriction': (
                                'no opening new positions; offsetting '
                                'trades to close only'
                            ),
                        },
                    )
                )
            self._remember(observation, required)
            return tuple(emitted)

        if short and self._state is MarginViolationState.COMPLIANT:
            if observation.checkpoint is Checkpoint.CLOSE_1630:
                self._state = MarginViolationState.NOTIFIED
                self._notice_date = observation.on
                emitted.append(
                    self._event(
                        MarginEventKind.SHORTFALL_NOTIFIED, observation,
                        previous, required, shortfall, elapsed,
                        detail={
                            'cited': 'QD 26 Dieu 13.1',
                            'top_up_due': (
                                'before 09h30 on the next trading day'
                            ),
                        },
                    )
                )
            elif observation.checkpoint is Checkpoint.OPEN_0930:
                # Dieu 13.2.a's "tai khoan vi pham moi": an account that was
                # compliant at yesterday's 16h30 can still be short at 09h30
                # against that same requirement, because assets can leave.
                self._state = MarginViolationState.SUSPENDED
                self._notice_date = observation.on
                emitted.append(
                    self._event(
                        MarginEventKind.SUSPENDED, observation, previous,
                        required, shortfall, elapsed,
                        detail={
                            'cited': 'QD 26 Dieu 13.2.a',
                            'restriction': (
                                'no opening new positions; offsetting '
                                'trades to close only'
                            ),
                        },
                    )
                )
            # At 14h00 nothing happens to a COMPLIANT account, however short
            # it looks: Dieu 13.2.b examines "tat ca cac tai khoan vi pham"
            # -- the accounts already in violation -- and its only action is
            # restoration. Suspension belongs to 09h30 and to 09h30 alone,
            # register id I21. Reading 13.2.b as a second suspension gate
            # would invent an enforcement action the article does not give.
        self._remember(observation, required)
        return tuple(emitted)

    # -- internals --------------------------------------------------------

    def _remember(
        self, observation: MarginObservation, required: Decimal
    ) -> None:
        if observation.checkpoint is Checkpoint.CLOSE_1630:
            self._required = required

    def _event(
        self,
        kind: MarginEventKind,
        observation: MarginObservation,
        previous: MarginViolationState,
        required: Decimal,
        shortfall: Decimal,
        elapsed: int,
        *,
        detail: Mapping[str, str],
    ) -> MarginEvent:
        cure_by = None
        if self._next_trading_day is not None:
            cure_by = self._next_trading_day(observation.on)
        event = MarginEvent(
            kind=kind,
            checkpoint=observation.checkpoint,
            on=observation.on,
            at=observation.at,
            previous_state=previous,
            state=self._state,
            margin_assets=observation.margin_assets,
            required_margin=required,
            shortfall=shortfall,
            notice_date=self._notice_date,
            cure_by_date=cure_by,
            cure_by_time=CHECKPOINT_TIME[Checkpoint.OPEN_0930],
            working_days_elapsed=elapsed,
            detail=dict(detail),
        )
        self._events.append(event)
        return event
