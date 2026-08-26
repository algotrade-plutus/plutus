"""Variation-margin arithmetic for a single derivatives position.

.. warning::

   **THIS MODULE MODELS A QUANTITY THAT DOES NOT EXIST.**

   :attr:`MarginConfig.maintenance_rate` is a *maintenance margin ratio* --
   a fraction of notional below which a position is called. **Vietnam
   publishes no such ratio at any date in 2020-2026, and no Vietnamese rule
   runs that test.** VSDC computes ``MR = IM + VM`` over the whole account
   portfolio and monitors ``utilisation = MR / valid margin assets`` in real
   time against an 80/90/100 ladder (rulebook 6.3, "The central finding of
   this domain"; VSDC "Thông tin về ký quỹ" §II.4(b), §V.4; Article 13 of
   QĐ 96/QĐ-VSD → QĐ 61/QĐ-VSD, confidence high). A
   maintenance-margin-as-a-fraction-of-notional test is a US convention that
   was imported into this file, not a Vietnamese rule that was cited into it.

   The module is kept, unchanged in behaviour, for exactly one reason: it is
   the batch research path the **published margin-incidence figures** were
   computed on (``measurements/margin_incidence.py``), and deleting or
   silently re-pointing it would restate those numbers without saying so.

   **The account-level model does not reproduce them.** Measured over the
   identical 381 front-month entries by
   ``measurements/margin_incidence_account.py``: funded at exactly the
   opening requirement -- the only unfitted funding level -- the account
   model calls 100% of entries at every holding period, and *no* funding
   multiple reproduces the published 29 / 48 / 56 counts jointly (the best
   fit, 1.42, still misses the 20-session count by 7). So the two are not
   two estimates of one quantity and the gap is not a tolerance. See
   :data:`PROVENANCE` and that module's docstring.

   **Do not build anything new on this module.** The session's entry point is
   :func:`plutus.market.session.deposit.account_margin_requirement`, which
   takes the whole account and raises ``TypeError`` on a lone
   :class:`~plutus.market.protocol.Position` by design.

**Variation margin is exchange-side.** It is a quantity the exchange itself
computes and collects each day. *Strategy P&L* is trader-side: it nets across
positions, subtracts fees and tracks a cash balance, and none of that happens
here. That distinction is what lets this module mark a position to market
daily without becoming a backtester.

Every threshold below is a **modelling assumption with no corpus backing** --
no margin, position-limit or account data exists in any table of either
corpus. :data:`VSD_INITIAL_MARGIN` is the published Vietnamese series (press-
sourced, no ``quyết định`` number); ``maintenance_rate`` is published nowhere,
because it is not a thing. They are config, so a caller can sweep them.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from plutus.market.protocol import Position, Side

__all__ = ['MarginConfig', 'MarginState', 'PROVENANCE', 'evaluate_margin',
           'VSD_INITIAL_MARGIN', 'vsd_initial_margin']


#: What each value in this module is, and what it is not. Same pattern as
#: ``BrokerTerms.PROVENANCE``: if it is not sourced, it says so here in
#: machine-readable form rather than only in prose a caller may not read.
#:
#: This is the module's own deprecation notice. It is a dict rather than a
#: ``DeprecationWarning`` on purpose -- warning at runtime would fire inside
#: the very measurement whose figures are still published, and a path we still
#: depend on cannot honestly warn that it is going away. Retirement is
#: **pending a decision**, and the evidence for that decision is
#: ``measurements/margin_incidence_account.py``.
PROVENANCE = {
    'maintenance_rate': (
        'MODELS A QUANTITY THAT DOES NOT EXIST. No Vietnamese rule states a '
        'maintenance margin ratio at any date; the actual call test is '
        'utilisation = MR / margin assets against an 80/90/100 ladder '
        '(rulebook 6.3). The "6.06% call distance" this file once derived '
        'from the field is an artefact of the invention, not a market fact.'),
    'shape': (
        'WRONG SHAPE. Vietnam margins the WHOLE ACCOUNT on a net-risk basis, '
        'not each position summed. Locked shape 5.'),
    'vsd_initial': (
        'SOURCED but press-sourced. The 10/13/17% series carries no quyet dinh '
        'number, and the previous 0.175 constant matched no source at any '
        'date. This class holds it UNDATED, which is wrong for any run '
        'crossing 2018-07-18 or 2022-12-15; vsd_initial_margin() is the dated '
        'reader.'),
    'broker_buffer': (
        'ASSUMPTION. A percentage-of-notional add-on is a plausible SHAPE; '
        'rulebook 6.3 records that the broker\'s actual lever in Vietnam is '
        'its utilisation thresholds.'),
    'kept_because': (
        'It is the batch research path the published margin-incidence figures '
        'were computed on. Removing it would silently restate them.'),
    'replacement': (
        'plutus.market.session.deposit.account_margin_requirement -- takes the '
        'whole DerivativesAccount, computes MR = IM + VM with VM loss-only, '
        'and tests utilisation against BrokerTerms.'),
    'reproduction': (
        'measurements.margin_incidence_account. SUPERSEDED VERDICT -- an '
        'earlier revision recorded DISAGREE and "no funding multiple '
        'reproduces all three counts". BOTH CLAIMS ARE FALSE. With the VSD '
        'ratio frozen at the entry date, funding_multiple in [1.4110, 1.4136] '
        'reproduces 29/48/56 EXACTLY; the earlier search stepped over that '
        'interval on a 0.01 grid. The two models are the same functional form. '
        'What is actually wrong is the EXPERIMENT: at funding_multiple=1 the '
        '100% call rate is an arithmetic identity (U >= 1 at every price), and '
        'the legacy series is a drawdown quantile at a threshold set by an '
        'unsourced 5-point buffer. See docs/reference/'
        'margin-model-adjudication.md.'),
}


#: VSD/VSDC's initial margin ratio for VN30 index futures, by effective date.
#:
#: Each step was issued as a *thông báo* (notice) under a standing delegation
#: in the clearing rulebook, **not** as a numbered quyết định -- citing
#: "Quyết định XX/QĐ-VSD set margin to 17%" would be citing a document that
#: does not exist.
#:
#: 17.5% -- this module's previous constant -- appears in no source at any
#: date. It is a transcription slip for 0.17.
#:
#: VSD re-determines the ratio on the 1st, 10th and 20th of each month from a
#: VaR assessment over at least 90 trading days, and publishes it **per listed
#: contract**, so the fully correct key is ``(contract_code, date)`` rather
#: than date alone. Every contract has carried the same ratio since
#: 2022-12-15, which is why a date-keyed schedule is sufficient today and will
#: not be sufficient forever.
VSD_INITIAL_MARGIN = (
    (date(2017, 8, 10), Decimal('0.10')),
    (date(2018, 7, 18), Decimal('0.13')),
    (date(2022, 12, 15), Decimal('0.17')),
)


def vsd_initial_margin(on: date) -> Decimal:
    """The VSD initial margin ratio in force on ``on``.

    Raises:
        ValueError: for a date before the derivatives market opened, where no
            ratio existed to look up.
    """
    for effective, rate in reversed(VSD_INITIAL_MARGIN):
        if on >= effective:
            return rate
    raise ValueError(
        f'no VSD initial margin ratio in force on {on}; the Vietnamese '
        f'derivatives market opened {VSD_INITIAL_MARGIN[0][0]}'
    )


@dataclass(frozen=True)
class MarginConfig:
    """Rates governing a derivatives margin account.

    .. warning::

       **This is the legacy per-position model and its shape is wrong.**
       Vietnam margins the whole account, not each position: the requirement
       is ``MR = IM + VM`` computed over the account's entire portfolio and
       tested as a *utilisation* ratio, ``MR / margin assets``, against a
       broker's threshold ladder. There is **no published maintenance margin
       ratio** in Vietnam, so ``maintenance_rate`` below models a quantity
       that does not exist, and the "6.06% call threshold" this docstring
       previously derived from it is an artefact of that invention rather
       than a market fact.

       It is kept, unchanged, as the batch research path that the published
       margin-incidence figures were computed on -- removing it would silently
       restate those numbers. Do not build anything new on this class.

       **The account-level replacement is built and it does not agree with
       this one.** ``plutus.market.session.deposit.account_margin_requirement``
       ships; ``measurements/margin_incidence_account.py`` runs it over the
       identical 381 entries and reports both answers. **An earlier revision
       of this docstring said the verdict was DISAGREE and structural. That
       was wrong** -- see :data:`PROVENANCE` and the adjudication document.
       The residual sensitivity is real, though, and it is this: the
       utilisation test divides by the **deposit balance**, a quantity this
       class does not have and neither corpus records, so the account model's
       incidence is partly a statement about how much collateral an investor
       posted. Funded at exactly the requirement -- the only unfitted choice
       -- utilisation is 1.00 on entry and 100% of entries are called. See
       :data:`PROVENANCE` for the measured numbers.

    ``vsd_initial`` defaults to the ratio in force **today**. Anything walking
    a historical path must resolve it per date with
    :func:`vsd_initial_margin`; the derivatives tax base is linear in this
    same ratio, so one dated series has to feed both or the two disagree.
    Holding it undated here is itself a live defect for any historical run:
    the front-month corpus window is 2021-06-01..2022-12-29, and VSDC's ratio
    was **0.13** for 371 of its 381 measured entries, not the 0.17 this
    default posts.
    """

    vsd_initial: Decimal = Decimal('0.17')
    broker_buffer: Decimal = Decimal('0.05')
    #: Models a ratio Vietnam does not publish -- see the class warning. Kept
    #: only so the legacy walk in `exchanges/derivatives.py` still runs.
    maintenance_rate: Decimal = Decimal('0.17')
    liquidation_rate: Decimal = Decimal('0')
    default_multiplier: Decimal = Decimal('100000')   # VND per index point

    @property
    def initial_rate(self) -> Decimal:
        """Fraction of notional a position must post at entry."""
        return self.vsd_initial + self.broker_buffer

    def with_initial(self, initial_rate: Decimal) -> 'MarginConfig':
        """A copy whose total initial rate is ``initial_rate``.

        Used by the sensitivity sweep. The buffer absorbs the change so the
        VSD component stays at its published value.
        """
        return MarginConfig(
            vsd_initial=self.vsd_initial,
            broker_buffer=initial_rate - self.vsd_initial,
            maintenance_rate=self.maintenance_rate,
            liquidation_rate=self.liquidation_rate,
            default_multiplier=self.default_multiplier,
        )


MarginConfig.VN30F_DEFAULT = MarginConfig()

#: Reachable from the class the way ``BrokerTerms.PROVENANCE`` is, so a caller
#: holding a ``MarginConfig`` and no import of this module can still read what
#: its fields are worth.
MarginConfig.PROVENANCE = PROVENANCE


@dataclass(frozen=True)
class MarginState:
    """The margin account of one position on one day.

    ``ratio`` is ``equity / notional``. **Nothing in Vietnam compares that
    number to anything**: the regulated ratio is ``MR / margin assets``, whose
    denominator is the deposit balance and not the position's notional. See
    the module warning; :class:`~plutus.market.session.types.MarginView` is
    the view that reports the ratio the market actually tests.
    """

    settlement: Decimal
    notional: Decimal
    equity: Decimal
    ratio: Decimal


def evaluate_margin(
    position: Position,
    settlement: Decimal,
    config: MarginConfig,
) -> MarginState:
    """Mark **one position** to one settlement price. The legacy path.

    .. warning::

       This function is the per-position half of a model whose test quantity
       -- a maintenance margin ratio -- **does not exist in Vietnamese rules**.
       See the module warning and :data:`PROVENANCE`. It is kept because the
       published margin-incidence figures were computed through it and
       restating them silently would be worse than keeping a wrong shape
       labelled as one.

       Two specific ways its arithmetic differs from the sourced model, both
       measured rather than asserted:

       * ``equity`` moves **symmetrically** around the entry price, so a
         favourable move *relieves* the requirement. VSDC's variation margin
         is loss-only: "giá trị ký quỹ biến đổi **chỉ được tính vào** giá trị
         ký quỹ duy trì yêu cầu trong trường hợp lãi lỗ vị thế ... ở trạng
         thái lỗ". An account in profit posts the same MR as one exactly flat.
       * ``posted`` is derived from **entry** notional, so the requirement is
         frozen at the entry price. VSDC recomputes IM on the current price,
         which is why the sourced requirement can rise on a day the position's
         notional falls.

       New code wants
       :func:`plutus.market.session.deposit.account_margin_requirement`.

    Raises:
        ValueError: if ``settlement`` is not positive -- notional would be zero
            or negative and the ratio undefined. Refusing beats returning a
            meaningless number.
    """
    if settlement <= 0:
        raise ValueError(
            f'settlement must be positive, got {settlement}; notional and '
            f'margin ratio are undefined otherwise'
        )

    multiplier = position.multiplier or config.default_multiplier
    signed = Decimal(position.quantity) * (
        Decimal('1') if position.side is Side.BUY else Decimal('-1'))

    entry_notional = Decimal(position.quantity) * multiplier * position.entry_price
    notional = Decimal(position.quantity) * multiplier * settlement

    posted = (position.posted_margin if position.posted_margin is not None
              else config.initial_rate * entry_notional)
    equity = posted + signed * multiplier * (settlement - position.entry_price)

    return MarginState(settlement=settlement, notional=notional,
                       equity=equity, ratio=equity / notional)
