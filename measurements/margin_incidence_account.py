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

**The answer measured on the 2021-06-01..2022-12-29 front-month corpus is
no.** Not "no, by 2%": the two models do not test the same quantity, and the
account model has a free parameter the legacy model does not have -- **the
deposit balance**.

The legacy walk never asks how much collateral the account posted -- it
*derives* posted margin as ``initial_rate x entry_notional`` and then measures
a ratio of that to notional. The account model asks ``MR / assets``, and
``assets`` is whatever the investor actually deposited. Two accounts holding
the same contract at the same price are on different rungs of the ladder if
they funded differently, which is correct, and which means the incidence
figure is partly a statement about retail funding behaviour. **Neither corpus
on this machine carries any margin or account data**, so that quantity is not
merely unknown here, it is unobservable here.

What the sweep in :func:`funding_multiple_sweep` shows is stronger than a
disagreement at one parameterisation:

* At :data:`FUNDED_AT_REQUIREMENT` -- deposit exactly the opening requirement,
  the only funding level that is *not* fitted -- utilisation is exactly 1.00
  the instant the position opens, so **100% of entries are called** at every
  holding period. That is not a bug: an account that posts the minimum is by
  definition fully utilised, and the ladder's top rung is "fully utilised".
* At the best joint fit, :data:`BEST_JOINT_FIT`, the account model reproduces
  the 10-session figure exactly (48 of 381) and still misses the 20-session
  figure by 7 entries (16.54% against the published 14.70%). **No funding
  multiple reproduces all three published holding periods**, because the two
  models' call boundaries move differently in the size of the loss.

So the published figures are **not** restated here. The legacy path stays in
place, ``margin.py`` says loudly what it models, and the decision about which
number the paper prints is left to a human with both numbers in front of them.

Run it::

    PYTHONPATH=src:. python -m measurements.margin_incidence_account \\
        --data-root /path/to/corpus --sweep
"""

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

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
    'AGREEMENT_TOLERANCE', 'BEST_JOINT_FIT', 'FUNDED_AT_REQUIREMENT',
    'FUNDING_PROVENANCE', 'PUBLISHED_CALLS', 'AccountIncidenceResult',
    'MarginPathComparison', 'compare_margin_paths', 'funding_multiple_sweep',
    'measure_account_margin_incidence',
]

#: VN30F1M: 100,000 VND per index point. A *product* fact, not a venue fact --
#: a government-bond future is 10,000 per point on the same exchange.
VN30F_MULTIPLIER = Decimal('100000')

#: Deposit exactly the opening requirement. **The only funding level in this
#: module that is not fitted to the answer**, and the one a reader should
#: judge the comparison on: it is what "post the margin" means with no further
#: assumption. It puts utilisation at exactly 1.00 on day one.
FUNDED_AT_REQUIREMENT = Decimal('1')

#: The funding multiple that minimises total absolute error against the three
#: published call counts. **This is a fitted parameter with no source and no
#: corpus support**, reported so the reader can see that even the best fit
#: does not reproduce them -- not offered as a value to use.
BEST_JOINT_FIT = Decimal('1.42')

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
        'any kind. FUNDED_AT_REQUIREMENT is the unfitted choice; '
        'BEST_JOINT_FIT is fitted to the published figures and must never be '
        'quoted as a market value.'),
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
    """Call incidence through the account-level utilisation test."""

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
        return out


def measure_account_margin_incidence(
    data_root: str,
    *,
    holding_days: int,
    funding_multiple: Decimal = FUNDED_AT_REQUIREMENT,
    broker_buffer: Decimal = Decimal('0.05'),
    terms: Optional[BrokerTerms] = None,
    settle_daily: bool = False,
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

    Returns:
        Counts and rates over the same denominator the legacy path reports.
    """
    terms = terms if terms is not None else BrokerTerms.DEFAULT
    entries = warned = called = forced = 0

    for ticker, window in _windows(data_root, holding_days):
        entry_day, entry_price = window[0]
        opened_at = datetime.combine(entry_day, datetime.min.time())
        rate = vsd_initial_margin(entry_day) + broker_buffer
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
            rules=None, ts=opened_at)

        entries += 1
        hit_warning = hit_call = hit_forced = False
        for day, price in window[1:]:
            ts = datetime.combine(day, datetime.min.time())
            marks = {ticker: price}
            account.observe_marks(marks, ts)
            status = account.margin(marks, None, terms, ts).status
            if status is not MarginStatus.OK:
                hit_warning = True
            if status in (MarginStatus.CALL, MarginStatus.FORCED):
                hit_call = True
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
        contracts=len(_series(data_root)))


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
        settle_daily=settle_daily)

    notes: List[str] = []
    if legacy.entries != account.entries:
        notes.append(
            f'entry populations differ ({legacy.entries} vs '
            f'{account.entries}); the comparison is not like for like')
    if funding_multiple == FUNDED_AT_REQUIREMENT:
        notes.append(
            'deposit = the opening requirement, so utilisation is exactly '
            '1.00 on entry: the account is on the top rung before the market '
            'has moved. This is the unfitted funding level.')
    else:
        notes.append(
            f'funding_multiple={funding_multiple} is an ASSUMPTION and, above '
            f'1, one fitted to the answer. It is not a market value.')
    notes.append(
        'the legacy path posts an undated 22% while this path resolves '
        'VSDC\'s dated series (13% before 2022-12-15, which is 371 of the '
        '381 entries).')

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
) -> Tuple[Dict[str, Any], ...]:
    """Is there **any** funding level that reproduces all three figures?

    The sweep is the honest form of the question. A single comparison at a
    single funding multiple can always be dismissed as the wrong parameter;
    a sweep that never lands on all three published counts at once cannot.
    Each row carries the total absolute error against
    :data:`PUBLISHED_CALLS`, so the best fit is visible and so is its miss.
    """
    rows: List[Dict[str, Any]] = []
    for multiple in multiples:
        called = {
            hold: measure_account_margin_incidence(
                data_root, holding_days=hold, funding_multiple=multiple,
                broker_buffer=broker_buffer).called
            for hold in holding_periods
        }
        error = sum(abs(called[h] - PUBLISHED_CALLS[h])
                    for h in holding_periods if h in PUBLISHED_CALLS)
        rows.append({'funding_multiple': float(multiple),
                     'called': called,
                     'absolute_error_vs_published': error})
    return tuple(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--json', type=Path, default=None)
    parser.add_argument('--funding-multiple', type=Decimal,
                        default=FUNDED_AT_REQUIREMENT)
    parser.add_argument('--sweep', action='store_true',
                        help='sweep the funding multiple and score every row '
                             'against the published counts')
    args = parser.parse_args()

    results: Dict[str, Any] = {}
    print('legacy (per-position, maintenance ratio Vietnam does not publish) '
          'vs account (MR / deposit utilisation)')
    print(f"{'hold':>5} {'entries':>8} {'legacy':>8} {'account':>8} "
          f"{'gap':>9}  verdict")
    for hold in (5, 10, 20):
        c = compare_margin_paths(args.data_root, holding_days=hold,
                                 funding_multiple=args.funding_multiple)
        results[f'hold_{hold}'] = c.to_dict()
        print(f'{hold:>5} {c.entries:>8,} '
              f'{float(c.legacy_call_rate):>7.2%} '
              f'{float(c.account_call_rate):>7.2%} '
              f'{float(c.gap):>+8.2%}  {c.verdict}')
    print(f'\nfunding_multiple = {args.funding_multiple} -- '
          f'{FUNDING_PROVENANCE["funding_multiple"].splitlines()[0]}')

    if args.sweep:
        # 0.01 steps, because 0.05 steps miss BEST_JOINT_FIT and would let
        # main() name a different "best" from the constant this module ships.
        multiples = tuple(Decimal(x) / Decimal('100')
                          for x in range(100, 201))
        rows = funding_multiple_sweep(args.data_root, multiples=multiples)
        results['sweep'] = list(rows)
        print('\nis there ANY funding multiple reproducing 29 / 48 / 56?')
        for row in rows:
            print(f'  {row["funding_multiple"]:.2f}  '
                  f'called={row["called"]}  '
                  f'|error|={row["absolute_error_vs_published"]}')
        best = min(rows, key=lambda r: r['absolute_error_vs_published'])
        print(f'  best fit {best["funding_multiple"]:.2f} still misses by '
              f'{best["absolute_error_vs_published"]} entries')

    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f'\nwrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
