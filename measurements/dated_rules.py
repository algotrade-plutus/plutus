"""How much of the corpus a date-blind rulebook would judge under the wrong rule.

The claim this measures is the paper's lead claim: that an exchange rulebook has
to be represented as **effective-dated editions resolved per simulated instant**,
because a simulator that resolves rules once at load time judges most of its own
sample under rules that were not in force.

That is easy to assert and easy to wave away as a corner case. It is neither. The
census below counts, for each sourced dated rule change inside the corpus window,
how many observations sit on the *far* side of it -- the rows a date-blind
simulator gets wrong.

**What this is not.** It is not a claim that every one of these rows produces a
different backtest result. Whether a rule *binds* on a given row is a separate
question, measured by the occupancy census. This measures **exposure**: the share
of the sample sitting under a superseded rule, which is a **ceiling** on how much
a date-blind resolution could distort, not an estimate of how much it does.

The two are far apart for some rules and close for others, and the difference
matters when quoting a figure. The round lot is the tight case: a lot of 100
applied before 2021-01-04 rejects every legal 10-to-90 share order, so exposure
is close to the real effect. The UPCoM band is the loose case, and its entry
below says so and points at the tighter number instead. **Quote the per-rule
figure, never the aggregate**, because averaging a tight exposure with a loose
one produces a number that means nothing.

A discarded experiment, recorded so nobody repeats it
----------------------------------------------------
The intuitive demonstration is the tick grid: apply today's grid to old prices and
count the misclassifications. **It does not work, and the reason is worth
knowing.** The HOSE matched-order tick has carried the same three tiers -- 10d
below 10,000d, 50d to 49,950d, 100d at or above 50,000d -- across the entire
2020-2026 rulebook window (QD 66+67, QD 352 Dieu 8.4(a), QD 17 Phu luc III,
QD 22/2025, QD 22/2026, all agreeing). There is no in-window tick change to
demonstrate with.

An earlier attempt reconstructed a *pre-2016* HOSE grid and measured a large
divergence against it. That reconstruction was invented, not sourced, so the
number it produced is not evidence of anything and is not reported here. The
sourced 2016-09-12 tick change is real -- Vo & Doan (2023) study it -- but it
predates the rulebook window, so we cite their result rather than manufacturing
our own.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

__all__ = ['DatedRuleChange', 'ExposureResult', 'DATED_CHANGES',
           'measure_dated_rule_exposure']


@dataclass(frozen=True)
class DatedRuleChange:
    """One sourced change to a rule, and what it changed from and to.

    ``citation`` and ``confidence`` are carried so a reader can check the date
    rather than take it on trust. A change we cannot date is not in this table:
    an undated change cannot demonstrate the value of dating.
    """

    rule: str
    venue: str
    effective: date
    before: str
    after: str
    citation: str
    confidence: str
    #: Whether corpus rows can be counted on each side of the change. Some
    #: changes are real and sourced but leave no trace in a close-price series
    #: -- margin ratios, settlement times -- so their exposure is not
    #: measurable here even though it is real.
    measurable_in_corpus: bool = True
    note: str = ''


#: Rule changes inside the corpus window, each sourced to a dated instrument.
DATED_CHANGES: Tuple[DatedRuleChange, ...] = (
    DatedRuleChange(
        rule='round_lot', venue='HSX', effective=date(2021, 1, 4),
        before='10 shares', after='100 shares',
        citation='HOSE minimum trading unit raised; rulebook s4.2',
        confidence='high',
        note='The cleanest case. A date-blind lot of 100 rejects every legal '
             '10-to-90 share HOSE order placed before this date.',
    ),
    DatedRuleChange(
        rule='price_band_wide_regime', venue='UPCOM', effective=date(2022, 11, 16),
        before='+/-15% ordinary', after='+/-40% after >25 sessions untraded',
        citation='rulebook s3, corpus-measured, high',
        confidence='high',
        note='READ THE EXPOSURE FIGURE FOR THIS ROW WITH CARE. The +/-15% '
             'ordinary band existed before this date; what 2022-11-16 added was '
             'the wide regime for names untraded >25 sessions. So the ~98% '
             'exposure below says only that most rows predate the addition, not '
             'that most rows are misjudged. The tighter and more honest figure '
             'is the rulebook\'s own corpus measurement: 70,578 of 412,041 '
             'UPCoM name-days (17.1%) actually carry the wide band, and '
             'separation from the ordinary band was total in an 8,000-row '
             'sample. Cite 17.1%, not the exposure.',
    ),
    DatedRuleChange(
        rule='settlement_delivery_time', venue='ALL', effective=date(2022, 8, 29),
        before='T+2 at next session open', after='T+2 at 13:00',
        citation='VSD decision; rulebook s5.1', confidence='high',
        measurable_in_corpus=False,
        note='Changes the first sellable INSTANT, not the cycle length. Invisible '
             'in a daily close series but decisive for an intraday sell.',
    ),
    DatedRuleChange(
        rule='vsd_initial_margin', venue='HNXDS', effective=date(2022, 12, 15),
        before='13%', after='17%',
        citation='VSD notice 2022-12-12; rulebook s6.3', confidence='high',
        measurable_in_corpus=False,
        note='A 31% relative increase in the requirement. The derivatives PIT '
             'base is LINEAR in this ratio, so a date-blind value corrupts the '
             'tax model and the margin model together.',
    ),
    DatedRuleChange(
        rule='krx_cutover', venue='HSX', effective=date(2025, 5, 5),
        before='pre-KRX order types, matching priority, closing price',
        after='post-KRX equivalents',
        citation='rulebook, THE KRX DELTA', confidence='high',
        measurable_in_corpus=False,
        note='Outside the corpus window (which ends 2022-12-30), so exposure is '
             'zero HERE and total for anyone simulating 2025 onward. The reason '
             'the mechanism must exist before the data does.',
    ),
)


@dataclass
class ExposureResult:
    """Corpus exposure to one dated rule change."""

    rule: str
    venue: str
    effective: str
    before: str
    after: str
    citation: str
    confidence: str
    measurable: bool
    observations: int = 0
    before_side: int = 0
    after_side: int = 0
    exposure: Optional[float] = None
    note: str = ''
    by_venue: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _reader(root: Path, table: str) -> str:
    return f"read_parquet('{root / (table + '.parquet')}')"


def measure_dated_rule_exposure(
    data_root: str,
    *,
    changes: Tuple[DatedRuleChange, ...] = DATED_CHANGES,
) -> List[ExposureResult]:
    """Count corpus observations on each side of every sourced rule change.

    Args:
        data_root: the Parquet corpus root.
        changes: the dated changes to measure. Defaults to
            :data:`DATED_CHANGES`.

    Returns:
        One :class:`ExposureResult` per change, in the order given. Changes
        marked ``measurable_in_corpus=False`` are returned with counts of zero
        and ``exposure=None`` -- they are real, and reporting them as
        unmeasurable is more honest than omitting them and implying the list is
        exhaustive.
    """
    root = Path(data_root)
    conn = duckdb.connect()

    results: List[ExposureResult] = []
    for change in changes:
        result = ExposureResult(
            rule=change.rule, venue=change.venue,
            effective=change.effective.isoformat(),
            before=change.before, after=change.after,
            citation=change.citation, confidence=change.confidence,
            measurable=change.measurable_in_corpus, note=change.note,
        )
        if not change.measurable_in_corpus:
            results.append(result)
            continue

        where_venue = ('' if change.venue == 'ALL'
                       else f"AND tk.exchangeid = '{change.venue}'")
        rows = conn.execute(f"""
            SELECT tk.exchangeid,
                   count(*) AS n,
                   count(*) FILTER (
                       WHERE c.datetime < DATE '{change.effective}') AS before_n
            FROM {_reader(root, 'quote_close')} c
            JOIN {_reader(root, 'quote_ticker')} tk USING (tickersymbol)
            WHERE tk.exchangeid IS NOT NULL
              AND tk.instrumenttype = 'stock'
              {where_venue}
            GROUP BY 1 ORDER BY 1
        """).fetchall()

        for venue, n, before_n in rows:
            result.by_venue[venue] = {'observations': int(n),
                                      'before': int(before_n),
                                      'after': int(n - before_n)}
            result.observations += int(n)
            result.before_side += int(before_n)
            result.after_side += int(n - before_n)

        if result.observations:
            # Exposure is the share sitting on the side a date-blind simulator
            # gets wrong -- i.e. under the OLD rule, since a date-blind build
            # applies today's value everywhere.
            result.exposure = result.before_side / result.observations
        results.append(result)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()

    results = measure_dated_rule_exposure(args.data_root)

    print(f"{'rule':<26}{'venue':<8}{'effective':<12}"
          f"{'observations':>13}{'under old rule':>16}{'exposure':>10}")
    print('-' * 85)
    for r in results:
        if not r.measurable:
            print(f'{r.rule:<26}{r.venue:<8}{r.effective:<12}'
                  f"{'--':>13}{'not measurable in a close series':>49}")
            continue
        print(f'{r.rule:<26}{r.venue:<8}{r.effective:<12}'
              f'{r.observations:>13,}{r.before_side:>16,}'
              f'{r.exposure:>10.1%}')

    print('\nExposure is the share of the sample a date-blind rulebook judges '
          'under a rule\nthat was not in force. It bounds the distortion; it '
          'does not assert it.')

    if args.json:
        args.json.write_text(json.dumps([r.to_dict() for r in results], indent=2))
        print(f'wrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
