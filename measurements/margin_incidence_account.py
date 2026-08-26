"""The same margin-incidence question, asked of the **account-level** model.

``measurements/margin_incidence.py`` measures how often the exchange would
margin-call a front-month VN30F long, and it does so through
``plutus.market.margin.evaluate_margin`` and
``HNXDSExchange.sustains()`` -- the *legacy per-position* path. That path
compares a position's equity to its own notional against a
``maintenance_rate``, and **Vietnam publishes no maintenance margin ratio at
any date**: the quantity that model tests does not exist (rulebook 6.3,
"The central finding of this domain"; VSDC "Thông tin về ký quỹ" §II.4(b)).

The replacement is ``plutus.market.session.deposit.account_margin_requirement``:
``MR = IM + VM`` over the whole account portfolio with ``VM`` counted only in
loss, tested as ``utilisation = MR / margin assets`` against a broker's
80/90/100 ladder. That shape *is* primary-sourced.

This module exists to answer one question before anything is restated: **can
the account-level model reproduce the published figures?** It does not
migrate the measurement and it does not touch ``margin_incidence.py``. It runs
the account model over the *identical* entry population -- the entries come
from ``margin_incidence``'s own query, not from a second one -- and reports
both answers side by side.

Retracted, 2026-08-26
---------------------

This module used to answer **no**, and to say so in two places that were both
wrong. The adjudication is
``docs/reference/margin-model-adjudication.md``; the short form:

* **The 100% call rate at** :data:`FUNDED_AT_REQUIREMENT` **is an arithmetic
  identity, not a measurement.** Write ``U = MR / IM_at_entry``. Because IM is
  recomputed on the current price and VM is loss-only, ``U >= 1`` at *every*
  price, with equality only when the price has not moved -- on a rally
  ``U = price/entry``, on a loss ``U = 1 + drawdown x (1-r)/r``. Utilisation
  is ``U / k`` for a deposit of ``k`` times the opening requirement, so at
  ``k = 1`` utilisation is at or above 1.00 always and the ladder's top rung
  fires on the first mark, before the holding period can matter. Measured:
  381 of 381 FORCED on bar 1 at 5, 10 **and** 20 sessions. A statistic that
  cannot move with the data it is computed on is not evidence about the data.
  See :data:`DEGENERACY_PROVENANCE` and :func:`degenerate_funding_ceiling`.
* **A funding multiple does reproduce all three published counts.** The old
  sweep missed it twice: its 0.01 grid steps straight over the interval
  ``[1.4110, 1.4136]``, and it compared a path that re-resolves VSDC's ratio
  at every bar against a legacy path that posts an undated 22%. Hold the ratio
  at the entry date and ``funding_multiple = 1.4120`` gives **29 / 48 / 56** --
  the published counts exactly, though not the same *events*: the called sets
  differ by two windows at holds 10 and 20, because the account threshold sits
  just below the legacy one before 2022-12-15 and well above it after. See
  :data:`REPRODUCING_FUNDING` and the ``freeze_initial_rate`` argument.

The stated reason for the residual -- "the two models' call boundaries move
differently in the size of the loss" -- was also wrong. Both models reduce, on
this one-contract experiment, to *max drawdown from entry against a
threshold*: the legacy path calls at ``(initial - maintenance)/(1 -
maintenance)``, which at the shipped rates is ``0.05/0.83 = 6.0241%``, and the
account path calls at ``r(theta k - 1)/(1 - r)``. They are the same functional
form in the loss. They differ on the **gain** -- the legacy model lets profit
relieve the requirement, the account model does not -- and in the rate
schedule, and the 20-session residual was entirely the second: 19 of the 381
twenty-session windows straddle the 2022-12-15 step from 13% to 17%, and eight
of the eight extra calls live there. On this corpus the gain branch cannot
bind at the reproducing multiple either: the largest drawup in any window is
19.47%, and at ``k = 1.4120`` a rally does not reach the call rung until 27.08%.

What to measure instead
-----------------------

Both figures stay reported. Neither should be published **as a call rate**,
for the same reason in two costumes: a call rate is an indicator thresholded
at an unsourced cushion, and it is the cushion, not the market, that sets it.

* The legacy cushion is ``initial_rate - maintenance_rate``. At the shipped
  defaults ``maintenance_rate`` equals VSDC's ratio exactly, so the cushion is
  the **broker buffer** and the published headline is
  ``P(max drawdown > broker_buffer / (1 - vsd_rate))``. Set the buffer to zero
  -- post exactly what VSDC requires -- and the legacy threshold is zero too.
* The account cushion is ``funding_multiple - 1``. Set it to zero and every
  entry is called.

:func:`measure_peak_requirement` reports the quantity underneath both: ``U*``,
the **peak margin requirement over the hold as a multiple of the requirement
at entry**. It has no funding parameter in it, and at ``broker_buffer = 0`` no
unsourced parameter at all -- it is VSDC's own ``MR = IM + VM`` on VSDC's own
dated ratio. Every call rate at every funding level is a survival probability
of that one distribution, ``P(U* >= theta k)``, which
:meth:`PeakRequirementResult.call_rate` computes.

Run it::

    PYTHONPATH=src:. python -m measurements.margin_incidence_account \\
        --data-root /path/to/corpus --sweep
"""

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from measurements.margin_incidence import (
    MarginIncidenceResult, _front_month_series, measure_margin_incidence,
)
from plutus.market.broker import BrokerTerms
from plutus.market.margin import vsd_initial_margin
from plutus.market.session.deposit import ContractLedger, DerivativesAccount
from plutus.market.session.ledgers import EncumbranceLedger
from plutus.market.session.types import (
    AccountRef, Fill, FillEvidence, MarginStatus, Side, Venue,
)

__all__ = [
    'AGREEMENT_TOLERANCE', 'BEST_JOINT_FIT', 'DEGENERACY_PROVENANCE',
    'FUNDED_AT_REQUIREMENT', 'FUNDING_PROVENANCE', 'PUBLISHED_CALLS',
    'REPRODUCING_FUNDING', 'REQUIREMENT_QUANTILES', 'VN30F_MULTIPLIER',
    'AccountIncidenceResult', 'MarginPathComparison', 'PeakRequirementResult',
    'compare_margin_paths', 'degenerate_funding_ceiling',
    'funding_multiple_sweep', 'measure_account_margin_incidence',
    'measure_peak_requirement',
]

#: VN30F1M: 100,000 VND per index point. A *product* fact, not a venue fact --
#: a government-bond future is 10,000 per point on the same exchange.
VN30F_MULTIPLIER = Decimal('100000')

#: Deposit exactly the opening requirement.
#:
#: Described here for two years as "the only funding level that is not fitted
#: to the answer", which is true and beside the point: it is also the funding
#: level at which the answer is a **constant**. Utilisation is ``U / k`` with
#: ``U >= 1`` identically, so at ``k = 1`` every rung of the ladder fires at
#: every price, on the first mark, on any price series whatsoever. It is
#: retained because the degeneracy is itself a finding worth being able to
#: reproduce -- not because it is a baseline. See
#: :data:`DEGENERACY_PROVENANCE`.
#:
#: It is not even an admissible state in the model that produced it:
#: ``DerivativesAccount.reserve_for_order`` admits the opening order at
#: ``k = 1`` only because its free-deposit test is a strict ``>``, and the
#: account is then at utilisation 1.0000 -- level 3 -- with the order merely
#: resting, so rulebook 6.3 §V.4 bars it from opening anything else. The
#: measurement reaches this state only by calling ``apply_fill`` directly.
FUNDED_AT_REQUIREMENT = Decimal('1')

#: The funding multiple that minimises total absolute error against the three
#: published call counts **on the 0.01 grid, with VSDC's ratio re-resolved at
#: every bar**. Both qualifiers matter and both were missing when this
#: constant was read as "even the best fit misses": the grid steps over the
#: interval that reproduces the counts exactly, and the dated ratio adds eight
#: 20-session calls that the legacy path's undated 22% cannot see. See
#: :data:`REPRODUCING_FUNDING`.
#:
#: **Still a fitted parameter with no source and no corpus support.** Nothing
#: below rehabilitates it as a market value; it is reported so the fit can be
#: seen for what it is.
BEST_JOINT_FIT = Decimal('1.42')

#: The quantiles :func:`measure_peak_requirement` reports, label -> probability.
#:
#: Nearest-rank on the sorted sample, no interpolation. An interpolated
#: quantile invents a value between two observations; every value in this
#: sample is a requirement the model actually computed on a real price, and a
#: number that sits between two of them is not one of those.
REQUIREMENT_QUANTILES: Mapping[str, Decimal] = {
    'min': Decimal('0'),
    'p25': Decimal('0.25'),
    'median': Decimal('0.5'),
    'p75': Decimal('0.75'),
    'p90': Decimal('0.90'),
    'p95': Decimal('0.95'),
    'p99': Decimal('0.99'),
    'max': Decimal('1'),
}

#: Published legacy call counts out of 381 entries, by holding period, at the
#: default 22% posted initial rate. Copied here as the comparison target;
#: :func:`compare_margin_paths` re-measures them rather than trusting this.
PUBLISHED_CALLS: Mapping[int, int] = {5: 29, 10: 48, 20: 56}

#: How close the two paths would have to be to count as agreeing, stated
#: before the measurement rather than after it: **one percentage point** of
#: call rate at every holding period measured. One point is roughly a tenth of
#: the published 12.60% headline, which is well inside the width of the
#: assumptions the figure already carries (the broker buffer alone moves it
#: from 26.25% to 6.82% across a 5-point range).
AGREEMENT_TOLERANCE = Decimal('0.01')

#: Where every unsourced input to the account-level path came from. Same
#: pattern as ``BrokerTerms.PROVENANCE``: if it is not sourced, it says so.
FUNDING_PROVENANCE: Mapping[str, str] = {
    'funding_multiple': (
        'ASSUMPTION, and the free parameter that makes this comparison '
        'possible at all. No source states how much collateral a Vietnamese '
        'retail derivatives account posts against an opening position, and '
        'neither corpus on this machine carries margin or account data of '
        'any kind. BEST_JOINT_FIT is fitted to the published figures and must '
        'never be quoted as a market value. FUNDED_AT_REQUIREMENT is the '
        'unfitted choice and it is NOT therefore a neutral one: at or below '
        'degenerate_funding_ceiling(...)["margin_call"] the call rate is 100% '
        'on any price series whatsoever, so "unfitted" and "informative" are '
        'not the same property. The legacy path has the same free parameter '
        'wearing a different name -- its cushion is initial_rate minus '
        'maintenance_rate, which at the shipped defaults is the broker '
        'buffer, and setting THAT to zero degenerates it too.'),
    'broker_buffer': (
        'ASSUMPTION. 5 points of notional above VSDC\'s ratio, carried over '
        'from MarginConfig so the two paths post the same rate. Rulebook 6.3 '
        'records that a percentage-of-notional add-on is a plausible SHAPE '
        'but that "the broker\'s actual lever in Vietnam is its UTILISATION '
        'thresholds".'),
    'utilisation_ladder': (
        'SHAPE sourced, LEVELS assumed. 80/90/100 is Article 13 of the '
        'derivatives clearing rulebook (QD 96/QD-VSD -> QD 61/QD-VSD Art. 13), '
        'confidence high; the levels an individual broker sets are '
        'commercial and unpublished -- see BrokerTerms.PROVENANCE.'),
    'initial_margin_rate': (
        'SOURCED but press-sourced: the 10/13/17% series carries no quyet dinh '
        'number. This path resolves it PER DATE via '
        'plutus.market.margin.vsd_initial_margin, so 97.4% of the corpus '
        'window (371 of 381 entries) is priced at 13% -- while the legacy '
        'measurement applies an undated 17% to all of it. See '
        'MarginPathComparison for what that alone is worth.'),
    'variation_margin_baseline': (
        'DECLARED CHOICE. settle_daily=False keeps the VM baseline at the '
        'entry price for the whole hold, which is what the legacy walk does '
        'and is the only way the two are comparable. The real VSDC mechanism '
        'rebaselines every day and moves the day\'s P&L as cash on T+1; Tier 1 '
        'models the rebaseline and NOT the cash movement, so settle_daily=True '
        'loses the cumulative loss entirely. Measured, that understates the '
        '10-session incidence by 10.2 points. It is offered as a parameter, '
        'and neither setting is the real thing.'),
}

#: Why the funded-at-the-requirement run is arithmetic rather than evidence,
#: and what else about the experiment does not survive contact with it.
#:
#: Machine-readable for the same reason ``FUNDING_PROVENANCE`` is: a caller who
#: lifts a number out of this module and never reads its prose should still be
#: able to find out that the number is a constant.
DEGENERACY_PROVENANCE: Mapping[str, str] = {
    'funded_at_requirement': (
        'ARITHMETIC IDENTITY, NOT A MEASUREMENT. With MR = IM(current price) '
        '+ max(0, loss) and assets frozen at the deposit, U = MR / IM_at_entry '
        'is >= 1 at every price: U = price/entry on a rally and '
        '1 + drawdown x (1-r)/r on a loss, equal to 1 only when the price has '
        'not moved. Utilisation is U/k, so k = 1 is FORCED at every price -- '
        'including a rally, and including no move at all. Measured: 381 of '
        '381 forced on the FIRST marked bar at 5, 10 and 20 sessions, so the '
        'holding period is not an input. The same reading would come back '
        '100% on a constant price series.'),
    'call_rate_as_a_metric': (
        'NOT INFORMATIVE ON ITS OWN. Both models reduce, on this one-contract '
        'experiment, to P(max drawdown from entry > threshold), and in both '
        'the threshold is set by an unsourced cushion: the legacy cushion is '
        'initial_rate - maintenance_rate (which at the shipped defaults IS the '
        'broker buffer, since maintenance_rate equals VSDC\'s ratio), the '
        'account cushion is funding_multiple - 1. Zero cushion degenerates '
        'both. Report the distribution of U* instead -- see '
        'measure_peak_requirement -- and derive any call rate from it.'),
    'rally_peaks': (
        'TIER 1 GAP, MEASURED. Roughly a third of the peak requirements in '
        'this corpus are attained on a RISING price: IM is recomputed on the '
        'higher price while the profit is not credited to assets, because '
        'derivatives P&L moves as cash on T+1 and Tier 1 does not model that '
        'leg (deposit.py, account_margin_requirement, note 3). In the market '
        'a rally cannot cause a call -- assets grow by the P&L while the '
        'requirement grows by only r times it, and r < 1 -- so the loss-branch '
        'series is reported separately and is the one a funding statement may '
        'lean on.'),
    'overlapping_windows': (
        'THE DENOMINATOR IS NOT 381 INDEPENDENT OBSERVATIONS. 381 entries are '
        'overlapping windows on 401 daily observations of 20 contracts, and '
        'at the legacy 6.0241% threshold the 48 ten-session calls and the 56 '
        'twenty-session calls fall on the SAME 19 distinct days. Any interval '
        'computed as if n = 381 is overstated; report event counts or '
        'cluster-robust intervals. Richardson & Stock (1989) is the standard '
        'reference for the overlapping-observations problem.'),
    'holding_period_labels': (
        'THE LABELS ARE NOT THE HORIZONS. _windows truncates a window at the '
        'end of a front-month series rather than dropping it, so the entry '
        'count is the same 381 at every holding period and a "20-session" '
        'hold on a ~21-session front-month series is mostly a hold to expiry. '
        'This is inherited from margin_incidence.py deliberately -- the '
        'comparison must walk the same entries -- and it applies to BOTH '
        'published series, not to one of them.'),
}

#: The funding multiples that reproduce :data:`PUBLISHED_CALLS`, and why the
#: 0.01 sweep could not find them. Measured on the 2021-06-01..2022-12-29
#: front-month corpus at ``broker_buffer = 0.05``, ``margin_call`` rung.
#:
#: These supersede the module's former claim that no funding multiple
#: reproduces the counts jointly. The claim was false for two independent
#: reasons and both are recorded here rather than deleted.
REPRODUCING_FUNDING: Mapping[str, Any] = {
    'frozen_initial_rate': {
        'low': Decimal('1.4110'),
        'high': Decimal('1.4136'),
        'counts': {5: 29, 10: 48, 20: 56},
        'note': ('VSDC\'s ratio held at each entry\'s own date, which is what '
                 'makes the two paths comparable on rate at all. Exact '
                 'reproduction of the published COUNTS at all three holding '
                 'periods -- and exact in count is not exact in event: '
                 'checked entry by entry, the called sets differ by two '
                 'windows at holds 10 and 20 (one in, one out). The account '
                 'threshold is 5.944% of drawdown for the 371 entries priced '
                 'at 13%+5% and 7.638% for the 10 priced at 17%+5%, against '
                 'the legacy path\'s flat 6.024%, and at this multiple the '
                 'two errors cancel in count.'),
    },
    'legacy_undated_rate': {
        'low': Decimal('1.3466'),
        'high': Decimal('1.3485'),
        'counts': {5: 29, 10: 48, 20: 56},
        'note': ('the legacy path\'s own flat 22% applied to every entry. '
                 'Also exact -- a second, independent multiple, because the '
                 'multiple absorbs whatever the rate is.'),
    },
    'dated': {
        'low': Decimal('1.4110'),
        'high': Decimal('1.4136'),
        'counts': {5: 29, 10: 48, 20: 64},
        'note': ('the shipped path, re-resolving the ratio at every bar. Only '
                 'the 20-session count moves, 56 -> 64, and all eight extra '
                 'calls sit in the 19 windows straddling 2022-12-15.'),
    },
    'why_the_sweep_missed_it': (
        'Two reasons, both mechanical. (1) The grid: funding_multiple_sweep '
        'steps in hundredths, and 1.41 and 1.42 straddle [1.4110, 1.4136] '
        'without ever landing in it. (2) The rate: the account path resolves '
        'VSDC\'s dated ratio per bar while the legacy path posts an undated '
        '22%, so windows crossing the 2022-12-15 step from 13% to 17% are '
        'priced on two different rate series. Neither is a difference between '
        'the models.'),
    'what_it_does_not_show': (
        'That 1.41 is what a Vietnamese retail account funds at. It is a '
        'fitted value and the corpus carries no account data. What it shows '
        'is that the two models are the same function of the loss, so the '
        'published figures were never evidence against the sourced model.'),
}


def degenerate_funding_ceiling(
    terms: BrokerTerms,
) -> Mapping[str, Decimal]:
    """Funding multiples at or below which each rung fires on **every** price.

    ``U = MR / IM_at_entry >= 1`` identically -- see
    :data:`DEGENERACY_PROVENANCE` -- and utilisation is ``U / k``, so rung
    ``theta`` is breached at every price whenever ``k <= 1 / theta``. Below
    that multiple the corresponding rate is a constant and carries no
    information about the price series.

    Derived from the ``terms`` passed in rather than from the 80/90/100
    defaults, because the levels are commercial and per-firm
    (``BrokerTerms.PROVENANCE``): a tighter ladder degenerates over a wider
    range of funding, and a caller who overrides the ladder needs the ceiling
    that goes with theirs.

    Returns:
        ``{'warning': ..., 'margin_call': ..., 'forced_close': ...}``.
    """
    return {
        'warning': Decimal('1') / terms.warning_utilisation,
        'margin_call': Decimal('1') / terms.margin_call_utilisation,
        'forced_close': Decimal('1') / terms.forced_close_utilisation,
    }


class _RateFrozenAtEntry:
    """A ``RuleSetLike`` that answers with one entry date's ratio, always.

    **This is a control, not a rule source, and it must never leave this
    module.** Its whole purpose is to hold VSDC's initial-margin ratio fixed
    across a window so that a *rate* change and a *price* change can be told
    apart: without it, the eight extra 20-session calls that 2022-12-15
    produces are indistinguishable from a difference between the two margin
    models, which is exactly the mistake this module used to make.

    It does not violate locked shape 1. It is not a cache of a resolution and
    not a per-ticker singleton: one instance is built per measured window,
    carrying that window's own entry instant, and it is discarded with the
    window. What it deliberately does *not* do is resolve per instant -- and
    that refusal is the counterfactual being measured, which is why the class
    is private and the parameter that reaches it is named
    ``freeze_initial_rate`` rather than anything that sounds like a default.
    """

    def __init__(self, ts: datetime, rate: Decimal) -> None:
        self.ts = ts
        self._rate = rate

    def initial_margin_rate(self, contract_code: str) -> Decimal:
        return self._rate


@lru_cache(maxsize=4)
def _series(data_root: str):
    """``margin_incidence``'s own front-month query, memoised.

    Imported rather than re-written. The comparison is only meaningful if both
    paths walk the **same entries**, and two copies of a SQL query are two
    chances to disagree about which days a contract was the front month.
    """
    return _front_month_series(Path(data_root))


def _windows(data_root: str, holding_days: int):
    """Every ``(ticker, window)`` the legacy measurement enters on.

    Deliberately the same loop shape as ``measure_margin_incidence``: enter at
    each close of the front-month series, hold ``holding_days`` sessions or to
    the end of the series, and skip a window with nothing to mark.
    """
    for ticker, observations in _series(data_root).items():
        for i in range(len(observations) - 1):
            window = observations[i:i + holding_days + 1]
            if len(window) < 2:
                continue
            yield ticker, window


@dataclass(frozen=True)
class AccountIncidenceResult:
    """Call incidence through the account-level utilisation test.

    ``forced_on_first_mark`` is the degeneracy detector and is why it is a
    field rather than a debugging print. When it equals ``entries`` the
    holding period never entered the answer: every position was closed out on
    bar one, so the 5-, 10- and 20-session figures are the same number three
    times. At :data:`FUNDED_AT_REQUIREMENT` that is exactly what happens.
    """

    entries: int
    warned: int
    called: int
    forced: int
    call_rate: Decimal
    forced_rate: Decimal
    holding_days: int
    funding_multiple: Decimal
    broker_buffer: Decimal
    settle_daily: bool
    contracts: int
    forced_on_first_mark: int = 0
    freeze_initial_rate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for key in ('call_rate', 'forced_rate', 'funding_multiple',
                    'broker_buffer'):
            out[key] = float(getattr(self, key))
        out['model'] = (
            'account-level: MR = IM + VM over the whole portfolio, VM in loss '
            'only, utilisation = MR / deposit against the broker ladder')
        out['entry_policy'] = (
            'long 1 front-month contract at each session close; hold '
            f'{self.holding_days} sessions or to the end of the series')
        out['funding_is_an_assumption'] = FUNDING_PROVENANCE['funding_multiple']
        if self.entries and self.forced_on_first_mark == self.entries:
            out['degenerate'] = DEGENERACY_PROVENANCE['funded_at_requirement']
        return out


def measure_account_margin_incidence(
    data_root: str,
    *,
    holding_days: int,
    funding_multiple: Decimal = FUNDED_AT_REQUIREMENT,
    broker_buffer: Decimal = Decimal('0.05'),
    terms: Optional[BrokerTerms] = None,
    settle_daily: bool = False,
    freeze_initial_rate: bool = False,
) -> AccountIncidenceResult:
    """Walk every legacy entry through a real :class:`DerivativesAccount`.

    One account per entry, holding one contract, because that is the position
    the legacy measurement walks -- the account model's netting has nothing to
    net here, and using it anyway is what makes the comparison like for like.
    The requirement is still computed by
    :func:`~plutus.market.session.deposit.account_margin_requirement`, which
    refuses anything that is not a whole account (locked shape 5).

    Args:
        holding_days: sessions held, matching the legacy parameter.
        funding_multiple: deposit as a multiple of the opening requirement.
            **The free parameter.** See :data:`FUNDING_PROVENANCE`.
        broker_buffer: points of notional above VSDC's ratio.
        terms: the utilisation ladder. Defaults to ``BrokerTerms.DEFAULT``.
        settle_daily: roll the variation-margin baseline to each day's price.
            ``False`` -- the default -- keeps it at the entry price, which is
            what the legacy walk measures against. See
            :data:`FUNDING_PROVENANCE`.
        freeze_initial_rate: hold VSDC's ratio at each entry's own date
            instead of re-resolving it at every marked bar. **A control, and
            the default is off**, because per-instant resolution is the
            correct behaviour and a regulatory hike really does force real
            margin calls. It exists because the legacy path posts an undated
            22%, so a comparison run without it is comparing two rate series
            as well as two models -- which is where the whole "20-session
            miss" came from. See :data:`REPRODUCING_FUNDING` and
            :class:`_RateFrozenAtEntry`.

    Returns:
        Counts and rates over the same denominator the legacy path reports.
    """
    terms = terms if terms is not None else BrokerTerms.DEFAULT
    entries = warned = called = forced = first_mark_forced = 0

    for ticker, window in _windows(data_root, holding_days):
        entry_day, entry_price = window[0]
        opened_at = datetime.combine(entry_day, datetime.min.time())
        vsd_rate = vsd_initial_margin(entry_day)
        rules = (_RateFrozenAtEntry(opened_at, vsd_rate)
                 if freeze_initial_rate else None)
        rate = vsd_rate + broker_buffer
        deposit = (funding_multiple * rate * VN30F_MULTIPLIER
                   * entry_price).quantize(Decimal('1'))

        account = DerivativesAccount(
            AccountRef.derivatives('account-level-incidence'),
            deposit, terms, EncumbranceLedger(), ContractLedger(),
            margin_buffer=broker_buffer,
            multipliers={ticker: VN30F_MULTIPLIER}, opened_at=opened_at)
        account.apply_fill(
            Fill(fill_id='entry', order_id='entry', ticker=ticker,
                 venue=Venue.HNXDS, side=Side.BUY, quantity=1,
                 price=entry_price, ts=opened_at,
                 evidence=FillEvidence.TRADED_THROUGH),
            rules=rules, ts=opened_at)

        entries += 1
        hit_warning = hit_call = hit_forced = False
        first = True
        for day, price in window[1:]:
            ts = datetime.combine(day, datetime.min.time())
            marks = {ticker: price}
            account.observe_marks(marks, ts)
            status = account.margin(marks, rules, terms, ts).status
            if status is not MarginStatus.OK:
                hit_warning = True
            if status in (MarginStatus.CALL, MarginStatus.FORCED):
                hit_call = True
            if first and status is MarginStatus.FORCED:
                first_mark_forced += 1
            first = False
            if status is MarginStatus.FORCED:
                hit_forced = True
                break
            if settle_daily:
                account.settle_daily(marks, ts)
        warned += hit_warning
        called += hit_call
        forced += hit_forced

    denominator = Decimal(entries) if entries else Decimal('1')
    return AccountIncidenceResult(
        entries=entries, warned=warned, called=called, forced=forced,
        call_rate=Decimal(called) / denominator,
        forced_rate=Decimal(forced) / denominator,
        holding_days=holding_days, funding_multiple=funding_multiple,
        broker_buffer=broker_buffer, settle_daily=settle_daily,
        contracts=len(_series(data_root)),
        forced_on_first_mark=first_mark_forced,
        freeze_initial_rate=freeze_initial_rate)


@dataclass(frozen=True)
class MarginPathComparison:
    """Both answers, the gap between them, and the verdict on the pair.

    ``verdict`` is ``'AGREE'`` only when **every** holding period compared
    lands inside :data:`AGREEMENT_TOLERANCE`. Anything else is ``'DISAGREE'``,
    and a disagreement is a reason to publish both figures rather than to
    quietly replace one with the other.
    """

    holding_days: int
    entries: int
    legacy_called: int
    account_called: int
    legacy_call_rate: Decimal
    account_call_rate: Decimal
    funding_multiple: Decimal
    tolerance: Decimal
    legacy_initial_rate: Decimal
    notes: Tuple[str, ...] = ()

    @property
    def gap(self) -> Decimal:
        """Account minus legacy, in call rate. Signed: positive is stricter."""
        return self.account_call_rate - self.legacy_call_rate

    @property
    def agrees(self) -> bool:
        """Whether the two rates sit inside the stated tolerance."""
        return abs(self.gap) <= self.tolerance

    @property
    def verdict(self) -> str:
        return 'AGREE' if self.agrees else 'DISAGREE'

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for key in ('legacy_call_rate', 'account_call_rate',
                    'funding_multiple', 'tolerance', 'legacy_initial_rate'):
            out[key] = float(getattr(self, key))
        out['gap'] = float(self.gap)
        out['verdict'] = self.verdict
        out['legacy_model'] = (
            'equity / notional against maintenance_rate -- a maintenance '
            'margin ratio Vietnam does not publish at any date')
        out['account_model'] = (
            'MR / deposit against the 80/90/100 utilisation ladder -- the '
            'shape VSDC actually runs')
        return out


def compare_margin_paths(
    data_root: str,
    *,
    holding_days: int,
    funding_multiple: Decimal = FUNDED_AT_REQUIREMENT,
    tolerance: Decimal = AGREEMENT_TOLERANCE,
    broker_buffer: Decimal = Decimal('0.05'),
    settle_daily: bool = False,
    freeze_initial_rate: bool = False,
) -> MarginPathComparison:
    """Run both paths over one holding period and report the pair.

    Both figures are **re-measured here**, including the legacy one: a
    comparison that quoted a remembered number for one side would go stale
    the first time anything under it changed.
    """
    legacy: MarginIncidenceResult = measure_margin_incidence(
        data_root, holding_days=holding_days)
    account = measure_account_margin_incidence(
        data_root, holding_days=holding_days,
        funding_multiple=funding_multiple, broker_buffer=broker_buffer,
        settle_daily=settle_daily, freeze_initial_rate=freeze_initial_rate)

    notes: List[str] = []
    if legacy.entries != account.entries:
        notes.append(
            f'entry populations differ ({legacy.entries} vs '
            f'{account.entries}); the comparison is not like for like')
    if funding_multiple <= degenerate_funding_ceiling(
            BrokerTerms.DEFAULT)['margin_call']:
        notes.append(
            f'funding_multiple={funding_multiple} is at or below '
            f'1/margin_call_utilisation, so EVERY entry is called at EVERY '
            f'price by identity -- the account call rate here is arithmetic, '
            f'not a measurement. See DEGENERACY_PROVENANCE.')
    else:
        notes.append(
            f'funding_multiple={funding_multiple} is an ASSUMPTION and, above '
            f'1, one fitted to the answer. It is not a market value.')
    if account.forced_on_first_mark == account.entries and account.entries:
        notes.append(
            'every entry was forced on its FIRST marked bar, so the holding '
            'period never entered the answer: 5, 10 and 20 sessions read the '
            'same number.')
    if freeze_initial_rate:
        notes.append(
            'VSDC\'s ratio is held at each entry\'s own date, which is what '
            'makes this comparable with the legacy path\'s flat rate. It is a '
            'control: per-instant resolution is the correct behaviour.')
    else:
        notes.append(
            'the legacy path posts an undated 22% while this path resolves '
            'VSDC\'s dated series (13% before 2022-12-15, which is 371 of the '
            '381 entries). Pass freeze_initial_rate=True to take that out of '
            'the comparison.')

    return MarginPathComparison(
        holding_days=holding_days,
        entries=legacy.entries,
        legacy_called=legacy.called,
        account_called=account.called,
        legacy_call_rate=legacy.call_rate,
        account_call_rate=account.call_rate,
        funding_multiple=funding_multiple,
        tolerance=tolerance,
        legacy_initial_rate=legacy.initial_rate,
        notes=tuple(notes),
    )


def funding_multiple_sweep(
    data_root: str,
    *,
    multiples: Tuple[Decimal, ...],
    holding_periods: Tuple[int, ...] = (5, 10, 20),
    broker_buffer: Decimal = Decimal('0.05'),
    freeze_initial_rate: bool = False,
) -> Tuple[Dict[str, Any], ...]:
    """Which funding levels reproduce the three published figures?

    .. warning::

       **A sweep only rules a value out if it evaluates it.** This function
       used to be read as proving that *no* funding multiple reproduces
       29 / 48 / 56, on a grid of hundredths that steps straight over
       ``[1.4110, 1.4136]`` -- the interval that does. Pass a fine enough
       ``multiples`` and ``freeze_initial_rate=True`` and the rows land on
       zero error. :data:`REPRODUCING_FUNDING` records the intervals.

    Rows below ``degenerate_funding_ceiling(...)['margin_call']`` carry
    ``degenerate=True``: there the call count is ``len(entries)`` by identity
    and the row is arithmetic rather than evidence. They are kept rather than
    skipped, because a sweep whose first quarter is a flat line at 100% is
    itself the clearest statement of what is wrong with the metric.

    Each row carries the total absolute error against :data:`PUBLISHED_CALLS`.
    """
    ceiling = degenerate_funding_ceiling(BrokerTerms.DEFAULT)['margin_call']
    rows: List[Dict[str, Any]] = []
    for multiple in multiples:
        called = {
            hold: measure_account_margin_incidence(
                data_root, holding_days=hold, funding_multiple=multiple,
                broker_buffer=broker_buffer,
                freeze_initial_rate=freeze_initial_rate).called
            for hold in holding_periods
        }
        error = sum(abs(called[h] - PUBLISHED_CALLS[h])
                    for h in holding_periods if h in PUBLISHED_CALLS)
        rows.append({'funding_multiple': float(multiple),
                     'called': called,
                     'absolute_error_vs_published': error,
                     'degenerate': multiple <= ceiling,
                     'freeze_initial_rate': freeze_initial_rate})
    return tuple(rows)


# --------------------------------------------------------------------------
# The replacement statistic: the requirement path, with no funding in it
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PeakRequirementResult:
    """The distribution of peak margin requirement over a holding period.

    ``U* = max over the hold of MR_t / MR_at_entry``. The deposit cancels out
    of it, so **there is no funding parameter in this statistic**, and at
    ``broker_buffer = 0`` there is no unsourced parameter in it at all: the
    numerator and denominator are both VSDC's own ``MR = IM + VM`` computed on
    VSDC's own dated ratio.

    It is the quantity the call rate was thresholding all along. An account
    funded at ``k`` times the opening requirement has ``utilisation = U / k``,
    so ``call rate(k, theta) = P(U* >= theta k)`` exactly -- which is what
    :meth:`call_rate` computes, and what makes the whole funding sweep one
    survival function rather than a hundred separate measurements.

    Two series are reported, not one:

    * ``peak_multiples`` -- over every mark. Faithful to VSDC's *requirement*,
      which really does rise when the price rises, because IM is recomputed on
      the current price.
    * ``loss_peak_multiples`` -- over marks strictly below the entry price
      only, and ``1`` for a window that was never in loss. This is the series
      a statement about **funding** may lean on. On a rally a real account's
      margin assets grow by the whole P&L while its requirement grows by only
      ``r`` times it, so utilisation *falls*; the model's assets are frozen at
      the deposit (the T+1 cash leg is Tier 1's declared gap), so the model
      shows a rise where the market shows a fall. ``peaks_on_a_rally`` counts
      exactly how much of the first series is that artefact.

    Attributes:
        observations: daily closes underlying the windows. With 381 entries
            drawn from this many observations across ``contracts`` contracts,
            the windows overlap heavily -- see
            ``DEGENERACY_PROVENANCE['overlapping_windows']``.
        distinct_peak_days: calendar days on which the 381 peaks occur. The
            gap between this and ``entries`` is the clustering the denominator
            hides.
        peak_session: quantiles of *when* the peak lands, in sessions after
            entry. Reported because it is the horizon statistic the call rate
            cannot express -- time-to-first-*call* is identically 1 for every
            entry at any funding below ``1/rung``, and undefined for an entry
            never called, whereas time-to-peak is defined everywhere and needs
            no funding level.
    """

    entries: int
    contracts: int
    observations: int
    holding_days: int
    broker_buffer: Decimal
    freeze_initial_rate: bool
    peak_multiple: Mapping[str, Decimal]
    loss_peak_multiple: Mapping[str, Decimal]
    peak_session: Mapping[str, Decimal]
    peaks_on_a_rally: int
    windows_never_in_loss: int
    distinct_peak_days: int
    peak_multiples: Tuple[Decimal, ...] = field(repr=False, default=())
    loss_peak_multiples: Tuple[Decimal, ...] = field(repr=False, default=())
    opening_requirements: Tuple[Decimal, ...] = field(repr=False, default=())

    def call_rate(self, funding_multiple: Decimal,
                  rung: Decimal) -> Decimal:
        """``P(U* >= rung x funding_multiple)`` over the stored sample.

        The same number :func:`measure_account_margin_incidence` gets by
        walking the account bar by bar, computed from the distribution
        instead. The deposit is re-quantised to whole dong here exactly as the
        walk does, so the two agree to the last unit rather than to a
        tolerance -- a derived statistic that only *approximately* reproduced
        the thing it derives from would be a second model, not a view.

        Args:
            funding_multiple: deposit as a multiple of the opening
                requirement. Below ``degenerate_funding_ceiling(...)[rung]``
                this returns 1 for every price series ever recorded.
            rung: the utilisation threshold, from
                :class:`~plutus.market.broker.BrokerTerms`.
        """
        if not self.entries:
            return Decimal('0')
        hits = 0
        for peak, opening in zip(self.peak_multiples,
                                 self.opening_requirements):
            deposit = (funding_multiple * opening).quantize(Decimal('1'))
            if peak * opening >= rung * deposit:
                hits += 1
        return Decimal(hits) / Decimal(self.entries)

    def funding_for(self, quantile: str, rung: Decimal) -> Decimal:
        """Deposit multiple that avoids ``rung`` at ``quantile`` of the loss
        series.

        Read off ``loss_peak_multiples`` and not ``peak_multiples``: the
        rally branch cannot produce a call in the market, so including it
        would inflate the funding a real investor needs by the size of a
        modelling gap. Still a *conditional* statement -- it assumes assets
        stay at the deposit, which is true on a losing path only up to the
        T+1 cash leg Tier 1 does not model.
        """
        return self.loss_peak_multiple[quantile] / rung

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            'entries': self.entries,
            'contracts': self.contracts,
            'observations': self.observations,
            'holding_days': self.holding_days,
            'broker_buffer': float(self.broker_buffer),
            'freeze_initial_rate': self.freeze_initial_rate,
            'peaks_on_a_rally': self.peaks_on_a_rally,
            'windows_never_in_loss': self.windows_never_in_loss,
            'distinct_peak_days': self.distinct_peak_days,
            'peak_multiple': {k: float(v)
                              for k, v in self.peak_multiple.items()},
            'loss_peak_multiple': {k: float(v) for k, v
                                   in self.loss_peak_multiple.items()},
            'peak_session': {k: int(v)
                             for k, v in self.peak_session.items()},
            'sample': {
                'peak_multiples': [float(v) for v in self.peak_multiples],
                'loss_peak_multiples': [float(v) for v
                                        in self.loss_peak_multiples],
            },
        }
        out['statistic'] = (
            'U* = peak margin requirement over the hold, as a multiple of the '
            'requirement at entry. MR = IM(current price) + VM(loss only), '
            'VSDC\'s own formula on VSDC\'s own dated ratio. There is no '
            'funding parameter in it; every call rate at every funding level '
            'is P(U* >= rung x multiple) of this one distribution.')
        out['quantile_method'] = (
            'nearest-rank on the sorted sample, no interpolation')
        out['rally_peaks_are_a_modelling_gap'] = (
            DEGENERACY_PROVENANCE['rally_peaks'])
        out['denominator'] = DEGENERACY_PROVENANCE['overlapping_windows']
        return out


def _quantiles(sample: Sequence[Decimal]) -> Dict[str, Decimal]:
    """:data:`REQUIREMENT_QUANTILES` of ``sample``, nearest-rank."""
    if not sample:
        return {label: Decimal('0') for label in REQUIREMENT_QUANTILES}
    ordered = sorted(sample)
    last = Decimal(len(ordered) - 1)
    out: Dict[str, Decimal] = {}
    for label, probability in REQUIREMENT_QUANTILES.items():
        index = int((probability * last).to_integral_value())
        out[label] = ordered[index]
    return out


def measure_peak_requirement(
    data_root: str,
    *,
    holding_days: int,
    broker_buffer: Decimal = Decimal('0'),
    terms: Optional[BrokerTerms] = None,
    freeze_initial_rate: bool = False,
) -> PeakRequirementResult:
    """The requirement path of every legacy entry, with no funding assumed.

    Walks the **same** entries as :func:`measure_account_margin_incidence`
    through the **same** :func:`account_margin_requirement`, and reads
    ``MarginView.required`` instead of ``MarginView.status``. That is the
    whole change: the requirement is the sourced half of the model, and the
    status is the half that needs a deposit balance neither corpus records.

    ``broker_buffer`` defaults to **zero here and to 0.05 elsewhere in this
    module**, and the difference is deliberate rather than an oversight. The
    incidence functions carry 0.05 because they must post the same rate as the
    legacy path they are compared against. This function is not comparing
    itself to anything, so it can afford the honest default: at zero, ``MR``
    is exactly what VSDC requires, and the result contains no assumed number
    at all. The buffer moves the answer -- it enters ``U*`` through
    ``(1 - r)/r`` on the loss branch -- so a caller wanting the broker-inclusive
    figure must ask for it.

    Args:
        holding_days: sessions held, matching the legacy parameter.
        broker_buffer: points of notional above VSDC's ratio. Zero is the
            sourced setting.
        terms: only used to build the account; the statistic does not consult
            the ladder. Defaults to ``BrokerTerms.DEFAULT``.
        freeze_initial_rate: hold VSDC's ratio at the entry date. See
            :func:`measure_account_margin_incidence`.

    Returns:
        A :class:`PeakRequirementResult` carrying the whole sample, not only
        its quantiles -- a distribution reported as five numbers cannot be
        re-cut by a reader who wants a different threshold.
    """
    terms = terms if terms is not None else BrokerTerms.DEFAULT
    peaks: List[Decimal] = []
    loss_peaks: List[Decimal] = []
    openings: List[Decimal] = []
    peak_days: List[date] = []
    peak_sessions: List[Decimal] = []
    on_rally = never_in_loss = 0

    for ticker, window in _windows(data_root, holding_days):
        entry_day, entry_price = window[0]
        opened_at = datetime.combine(entry_day, datetime.min.time())
        vsd_rate = vsd_initial_margin(entry_day)
        rules = (_RateFrozenAtEntry(opened_at, vsd_rate)
                 if freeze_initial_rate else None)
        deposit = ((vsd_rate + broker_buffer) * VN30F_MULTIPLIER
                   * entry_price).quantize(Decimal('1'))

        account = DerivativesAccount(
            AccountRef.derivatives('requirement-path'),
            deposit, terms, EncumbranceLedger(), ContractLedger(),
            margin_buffer=broker_buffer,
            multipliers={ticker: VN30F_MULTIPLIER}, opened_at=opened_at)
        account.apply_fill(
            Fill(fill_id='entry', order_id='entry', ticker=ticker,
                 venue=Venue.HNXDS, side=Side.BUY, quantity=1,
                 price=entry_price, ts=opened_at,
                 evidence=FillEvidence.TRADED_THROUGH),
            rules=rules, ts=opened_at)

        # The denominator: IM at the entry price, with VM zero because the
        # variation reference IS the entry price. Read off the model rather
        # than multiplied out here, so the two can never drift apart.
        opening = account.margin({ticker: entry_price}, rules, terms,
                                 opened_at).required

        peak: Optional[Decimal] = None
        peak_day = entry_day
        peak_session = 0
        peak_on_rally = False
        loss_peak = Decimal('1')
        saw_loss = False
        for session, (day, price) in enumerate(window[1:], start=1):
            ts = datetime.combine(day, datetime.min.time())
            marks = {ticker: price}
            account.observe_marks(marks, ts)
            required = account.margin(marks, rules, terms, ts).required
            multiple = required / opening
            if peak is None or multiple > peak:
                peak, peak_day, peak_session = multiple, day, session
                peak_on_rally = price > entry_price
            if price < entry_price:
                saw_loss = True
                if multiple > loss_peak:
                    loss_peak = multiple

        peaks.append(peak)
        loss_peaks.append(loss_peak)
        openings.append(opening)
        peak_days.append(peak_day)
        peak_sessions.append(Decimal(peak_session))
        on_rally += peak_on_rally
        never_in_loss += not saw_loss

    series = _series(data_root)
    return PeakRequirementResult(
        entries=len(peaks),
        contracts=len(series),
        observations=sum(len(rows) for rows in series.values()),
        holding_days=holding_days,
        broker_buffer=broker_buffer,
        freeze_initial_rate=freeze_initial_rate,
        peak_multiple=_quantiles(peaks),
        loss_peak_multiple=_quantiles(loss_peaks),
        peak_session=_quantiles(peak_sessions),
        peaks_on_a_rally=on_rally,
        windows_never_in_loss=never_in_loss,
        distinct_peak_days=len(set(peak_days)),
        peak_multiples=tuple(peaks),
        loss_peak_multiples=tuple(loss_peaks),
        opening_requirements=tuple(openings),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--json', type=Path, default=None)
    parser.add_argument('--funding-multiple', type=Decimal,
                        default=FUNDED_AT_REQUIREMENT)
    parser.add_argument('--sweep', action='store_true',
                        help='sweep the funding multiple and score every row '
                             'against the published counts')
    parser.add_argument('--freeze-initial-rate', action='store_true',
                        help='hold VSDC\'s ratio at each entry\'s own date, '
                             'so the 2022-12-15 step is out of the comparison')
    args = parser.parse_args()

    results: Dict[str, Any] = {}
    print('peak margin requirement over the hold, as a multiple of the '
          'requirement at entry -- no funding parameter in it')
    print(f"{'hold':>5} {'entries':>8} {'median':>8} {'p90':>8} {'p95':>8} "
          f"{'max':>8}  {'rally-peaks':>12}  {'days':>5}")
    for hold in (5, 10, 20):
        r = measure_peak_requirement(args.data_root, holding_days=hold)
        results[f'requirement_hold_{hold}'] = r.to_dict()
        q = r.peak_multiple
        print(f'{hold:>5} {r.entries:>8,} {float(q["median"]):>8.4f} '
              f'{float(q["p90"]):>8.4f} {float(q["p95"]):>8.4f} '
              f'{float(q["max"]):>8.4f}  {r.peaks_on_a_rally:>12,}  '
              f'{r.distinct_peak_days:>5,}')
    print('  broker_buffer = 0: MR is exactly VSDC\'s IM + VM on VSDC\'s own '
          'dated ratio, so no value above is an assumption.')
    print(f'  {DEGENERACY_PROVENANCE["overlapping_windows"]}')
    print(f'  {DEGENERACY_PROVENANCE["rally_peaks"]}')

    ceiling = degenerate_funding_ceiling(BrokerTerms.DEFAULT)
    print('\nfunding multiples at or below which a rung fires at EVERY price:')
    for rung, value in ceiling.items():
        print(f'  {rung:>13}  {float(value):.4f}')

    print('\nlegacy (per-position, maintenance ratio Vietnam does not publish) '
          'vs account (MR / deposit utilisation)')
    print(f"{'hold':>5} {'entries':>8} {'legacy':>8} {'account':>8} "
          f"{'gap':>9}  verdict")
    for hold in (5, 10, 20):
        c = compare_margin_paths(
            args.data_root, holding_days=hold,
            funding_multiple=args.funding_multiple,
            freeze_initial_rate=args.freeze_initial_rate)
        results[f'hold_{hold}'] = c.to_dict()
        print(f'{hold:>5} {c.entries:>8,} '
              f'{float(c.legacy_call_rate):>7.2%} '
              f'{float(c.account_call_rate):>7.2%} '
              f'{float(c.gap):>+8.2%}  {c.verdict}')
    print(f'\nfunding_multiple = {args.funding_multiple} -- '
          f'{FUNDING_PROVENANCE["funding_multiple"].splitlines()[0]}')
    if args.funding_multiple <= ceiling['margin_call']:
        print(f'  {DEGENERACY_PROVENANCE["funded_at_requirement"]}')

    if args.sweep:
        # 0.01 steps, matching the grid the published comparison ran on. It is
        # kept, and it is also the grid that steps over [1.4110, 1.4136]:
        # printing the interval next to the sweep is the point.
        multiples = tuple(Decimal(x) / Decimal('100')
                          for x in range(100, 201))
        rows = funding_multiple_sweep(
            args.data_root, multiples=multiples,
            freeze_initial_rate=args.freeze_initial_rate)
        results['sweep'] = list(rows)
        print('\nfunding multiple vs the published 29 / 48 / 56:')
        for row in rows:
            flag = ('  (degenerate: 100% by identity)'
                    if row['degenerate'] else '')
            print(f'  {row["funding_multiple"]:.2f}  '
                  f'called={row["called"]}  '
                  f'|error|={row["absolute_error_vs_published"]}{flag}')
        best = min(rows, key=lambda r: r['absolute_error_vs_published'])
        print(f'  best on this grid: {best["funding_multiple"]:.2f}, error '
              f'{best["absolute_error_vs_published"]} entries')
        print(f'  {REPRODUCING_FUNDING["why_the_sweep_missed_it"]}')
        for key in ('frozen_initial_rate', 'legacy_undated_rate', 'dated'):
            row = REPRODUCING_FUNDING[key]
            print(f'  {key}: k in [{row["low"]}, {row["high"]}] -> '
                  f'{row["counts"]}')

    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f'\nwrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
