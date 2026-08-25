"""How often does each exchange rule actually *bind*?

A simulator that enforces twenty rules none of which ever bind has added
nothing. One whose rules bind on a measurable share of the sample has. This
census says which rules matter and by how much, so the high-fidelity claim is
checkable rather than taken on faith.

Exposure and occupancy are different numbers -- do not blur them
----------------------------------------------------------------
:mod:`measurements.dated_rules` measures **exposure**: the share of the sample
sitting under a superseded rule. Exposure is a **ceiling** on distortion. It
says "this rule *could* have mattered here."

This module measures **occupancy**: how often the constraint is actually at a
level where it changes an outcome. It says "this rule *did* bind here."

The gap between them is large and rule-specific. The round lot is the case
where both are computable and the difference is legible: exposure says 82.2% of
the HSX equity sample predates the 2021-01-04 lot change, while occupancy says
that a date-blind lot of 100 destroys **166,013** specific orders in that window
which the correct lot of 10 would have let through. The first bounds the
problem; the second is the problem.

Report per rule. Never aggregate
--------------------------------
Every figure below is per rule and per venue, and there is deliberately no
grand total. Averaging band lock (a tight, outcome-changing measure) with lot
reshaping (a measure whose value is fixed almost entirely by arithmetic, see
below) produces a number that means nothing. :mod:`measurements.dated_rules`
says this; it is worth saying twice.

What "binds" means is stated per rule
-------------------------------------
There is no single definition. A band binds when a side is unfillable; a tick
binds when the legal price differs from the price a naive model would send; a
lot binds when it reshapes or destroys an order. Each
:class:`RuleOccupancy` carries its own ``definition`` string, because a rate
without its definition is not a measurement.

Two corpus defects that a careless reading turns into fake findings
-------------------------------------------------------------------
**1. Two dates carry corrupted bands and are excluded here.** 2021-02-17 holds
all 1,226 of the corpus's inverted (ceiling <= floor) stock rows and shows only
23.8% of closes inside their own band; 2021-06-21 shows 81.6% in-band with no
inversions at all, the signature of ceiling/floor/reference mis-keyed to the
wrong tickers. Including them inflates band occupancy with rows where the band
itself is wrong. See :data:`BAND_DEFECT_DATES`.

**2. ``quote_totalforeignroom`` reports 0 for names it has no data on.** That
daily table holds 24,416 rows at exactly zero -- 16.5% of it -- which reads as
"foreign room exhausted" and is not. 262 tickers are zero on *every* one of its
83 dates, and those tickers appear in **neither** the intraday room feed nor
``quote_dailyforeignbuy``: zero ticker-days in each. A value present in one
table and absent from both of its corroborators is a placeholder, not an
observation. Room occupancy here is therefore measured on the intraday
``quote_foreignroom`` series, whose minimum is 1 and which has no zeros at all.
:func:`measure_daily_room_placeholder` reproduces the defect so the trap stays
documented rather than merely avoided.

The precedent for this care: a prior session measured 15,504 "off-grid UPCoM
closes" that were 15,504 correctly-gridded HOSE prices wearing the wrong venue
label. An alarming aggregate that a per-unit check dissolves is the recurring
failure mode in this corpus.
"""

from __future__ import annotations

import argparse
import json
import textwrap
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import duckdb

from plutus.core.constant import (
    VietnamMarketConstant, get_hsx_tick_size, get_trading_unit,
)

__all__ = [
    'RuleOccupancy', 'OccupancyCensus',
    'BAND_DEFECT_DATES', 'NAIVE_TICK', 'DEFAULT_MARKETABLE_OFFSET',
    'DEFAULT_PARTICIPATION', 'NOT_MEASURABLE',
    'measure_band_lock', 'measure_tick_grid_displacement',
    'measure_round_lot_reshaping', 'measure_foreign_room_headroom',
    'measure_daily_room_placeholder', 'measure_occupancy',
]

#: Dates whose ceiling/floor rows are corrupted. Excluded from every band
#: measurement. Documented at length in the module docstring; the short version
#: is that a band you cannot trust cannot tell you whether a band bound.
BAND_DEFECT_DATES: Tuple[date, ...] = (date(2021, 2, 17), date(2021, 6, 21))

#: ``quote_ceil`` and ``quote_floor`` begin here. Every band-dependent number
#: in this census is therefore a 2021-2022 number and is labelled as one -- the
#: corpus close series runs to 2022-12-30, so bands cover under a fifth of it.
BAND_WINDOW_START: date = date(2021, 2, 5)

#: What a consumer assumes from a schema quoting prices in thousands of VND to
#: one decimal. Same baseline as :mod:`measurements.grid_conformity`, named
#: here rather than inherited so the two modules cannot silently diverge.
NAIVE_TICK = Decimal('0.1')

#: A 1% marketable limit -- the standard way a daily backtest turns a close
#: into an order price. The tick rule cannot be measured on the close alone,
#: because an observed close is already on the legal grid by construction; it
#: needs a *derived* target price to round.
DEFAULT_MARKETABLE_OFFSET = Decimal('0.01')

#: 1% of the day's volume, the conventional participation cap.
DEFAULT_PARTICIPATION = Decimal('0.01')


@dataclass(frozen=True)
class RuleOccupancy:
    """How often one rule bound, on one venue, under one stated definition.

    ``definition`` is not decoration. Occupancy has no rule-independent
    meaning, so a rate quoted without the predicate that produced it is
    unreadable, and two such rates cannot be compared or averaged.

    ``measurable_in_corpus=False`` entries carry ``binding=None`` and a
    ``reason``. They are in the census precisely so the census is not read as
    exhaustive -- an omitted rule looks like a rule that never binds.
    """

    rule: str
    venue: str
    #: What the denominator is. "HSX stock closes with volume", not "rows".
    universe: str
    definition: str
    window: str
    observations: int
    binding: Optional[int]
    occupancy: Optional[Decimal]
    measurable_in_corpus: bool = True
    reason: str = ''
    caveat: str = ''
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out['occupancy'] = (None if self.occupancy is None
                            else float(self.occupancy))
        out['detail'] = {
            k: (float(v) if isinstance(v, Decimal) else v)
            for k, v in self.detail.items()
        }
        return out


@dataclass
class OccupancyCensus:
    """Every rule measured, plus the rules that could not be.

    There is no aggregate field and there will not be one. See the module
    docstring.
    """

    rules: List[RuleOccupancy] = field(default_factory=list)
    defects: List[RuleOccupancy] = field(default_factory=list)

    def by_rule(self, rule: str, venue: Optional[str] = None) -> RuleOccupancy:
        """The single entry for ``rule`` (and ``venue`` when given)."""
        for r in self.rules + self.defects:
            if r.rule == rule and (venue is None or r.venue == venue):
                return r
        raise KeyError(f'no occupancy entry for {rule!r} venue={venue!r}')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'rules': [r.to_dict() for r in self.rules],
            'defects': [d.to_dict() for d in self.defects],
            'reading_note': (
                'Occupancy is how often a rule BOUND. It is not exposure, '
                'which is how much of the sample sat under a superseded rule '
                'and is measured in measurements/dated_rules.py. Quote each '
                'rule separately; the definitions differ, so no average '
                'across rules is meaningful.'
            ),
        }


def _reader(root: Path, table: str) -> str:
    parquet = root / f'{table}.parquet'
    if parquet.exists():
        return f"read_parquet('{parquet}')"
    return f"read_csv_auto('{root / (table + '.csv')}')"


def _rate(binding: int, observations: int) -> Optional[Decimal]:
    """Occupancy as an exact Decimal, or None on an empty denominator."""
    if not observations:
        return None
    return Decimal(binding) / Decimal(observations)


def _snap(price: Decimal, tick: Decimal) -> Decimal:
    """The nearest price on ``tick``, rounding halves up.

    Half-up rather than Python's default half-even: a broker's order entry
    rounds a tie away from zero, and half-even would shift roughly half the
    exact-tie cases to the other side for no defensible reason.
    """
    return (price / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick


# --------------------------------------------------------------------------
# Band lock
# --------------------------------------------------------------------------

def measure_band_lock(data_root: str) -> List[RuleOccupancy]:
    """How often the daily price band actually locked a side of the book.

    Two definitions are measured because they bracket the truth from opposite
    sides, and neither alone is honest:

    * **closed locked** -- the close sat exactly on the ceiling or the floor.
      A locked side is unfillable, so this is the rule most likely to change a
      real outcome, and it is the *conservative* count: a name that hit the
      ceiling at 10am and retreated by the close is not counted.
    * **touched** -- the session high reached the ceiling or the session low
      reached the floor. This catches the intraday lock the close misses, and
      is the *upper* count for a daily bar.

    The denominator is closes **with recorded volume**, not all rows. That
    matters more than it sounds: 57% of UPCoM band rows have no volume row at
    all, so the untraded rows would otherwise dilute the rate with days on
    which nothing could have bound because nothing traded. The choice is also
    self-validating -- every single band-locked HSX and HNX row turns out to
    carry volume, which is what a genuine limit-lock looks like and not what a
    stale carry-forward would look like.

    Args:
        data_root: the Parquet corpus root.

    Returns:
        One :class:`RuleOccupancy` per venue for the close-lock definition,
        then one per venue for the touch definition.
    """
    root = Path(data_root)
    conn = duckdb.connect()
    excluded = ', '.join(f"DATE '{d}'" for d in BAND_DEFECT_DATES)

    rows = conn.execute(f"""
        SELECT tk.exchangeid,
          count(*) AS traded,
          count(*) FILTER (
            WHERE cast(cl.price AS DECIMAL(18,4))
                = cast(ce.price AS DECIMAL(18,4))) AS close_ceil,
          count(*) FILTER (
            WHERE cast(cl.price AS DECIMAL(18,4))
                = cast(fl.price AS DECIMAL(18,4))) AS close_floor,
          count(*) FILTER (
            WHERE cast(hi.price AS DECIMAL(18,4))
                = cast(ce.price AS DECIMAL(18,4))) AS high_ceil,
          count(*) FILTER (
            WHERE cast(lo.price AS DECIMAL(18,4))
                = cast(fl.price AS DECIMAL(18,4))) AS low_floor,
          count(*) FILTER (
            WHERE cast(hi.price AS DECIMAL(18,4))
                = cast(ce.price AS DECIMAL(18,4))
               OR cast(lo.price AS DECIMAL(18,4))
                = cast(fl.price AS DECIMAL(18,4))) AS touched
        FROM {_reader(root, 'quote_close')} cl
        JOIN {_reader(root, 'quote_ceil')} ce USING (tickersymbol, datetime)
        JOIN {_reader(root, 'quote_floor')} fl USING (tickersymbol, datetime)
        JOIN {_reader(root, 'quote_max')} hi USING (tickersymbol, datetime)
        JOIN {_reader(root, 'quote_min')} lo USING (tickersymbol, datetime)
        JOIN {_reader(root, 'quote_ticker')} tk USING (tickersymbol)
        JOIN {_reader(root, 'quote_dailyvolume')} v
             USING (tickersymbol, datetime)
        WHERE tk.instrumenttype = 'stock'
          AND v.quantity > 0
          AND cl.datetime NOT IN ({excluded})
          AND cast(ce.price AS DECIMAL(18,4))
            > cast(fl.price AS DECIMAL(18,4))
        GROUP BY 1 ORDER BY 1
    """).fetchall()

    window = f'{BAND_WINDOW_START} to 2022-12-30'
    caveat = (
        'quote_ceil starts 2021-02-05, so every band figure here is a '
        '2021-2022 figure and cannot be extended to the rest of the corpus. '
        f'The dates {", ".join(str(d) for d in BAND_DEFECT_DATES)} are '
        'excluded as corrupted, as are rows with ceiling <= floor.'
    )

    closed: List[RuleOccupancy] = []
    touched: List[RuleOccupancy] = []
    for venue, traded, c_ceil, c_floor, h_ceil, l_floor, n_touch in rows:
        closed.append(RuleOccupancy(
            rule='price_band_close_lock', venue=venue,
            universe='stock closes with recorded volume, valid band',
            definition='close sits exactly on the ceiling or the floor, so '
                       'one side of the book was unfillable at the close',
            window=window,
            observations=int(traded), binding=int(c_ceil + c_floor),
            occupancy=_rate(int(c_ceil + c_floor), int(traded)),
            caveat=caveat,
            detail={'at_ceiling': int(c_ceil), 'at_floor': int(c_floor),
                    'ceiling_rate': _rate(int(c_ceil), int(traded)),
                    'floor_rate': _rate(int(c_floor), int(traded))},
        ))
        touched.append(RuleOccupancy(
            rule='price_band_intraday_touch', venue=venue,
            universe='stock closes with recorded volume, valid band',
            definition='session high reached the ceiling or session low '
                       'reached the floor -- the band bound at some point in '
                       'the session even if the close came back inside',
            window=window,
            observations=int(traded), binding=int(n_touch),
            occupancy=_rate(int(n_touch), int(traded)),
            caveat=caveat + ' A daily bar cannot say for how long the lock '
                            'held, only that it happened.',
            detail={'high_at_ceiling': int(h_ceil),
                    'low_at_floor': int(l_floor)},
        ))
    return closed + touched


# --------------------------------------------------------------------------
# Tick grid
# --------------------------------------------------------------------------

def measure_tick_grid_displacement(
    data_root: str,
    *,
    offset: Decimal = DEFAULT_MARKETABLE_OFFSET,
) -> List[RuleOccupancy]:
    """How often the nearest legal price differs from a naive 0.1-tick price.

    This is deliberately **not** grid conformity. Conformity asks whether an
    observed price lies on the grid, and observed prices almost all do, so
    conformity cannot tell you whether the grid rule ever changes an order.
    Occupancy needs a price the model has to *choose*, so the target here is a
    derived one: ``close * (1 + offset)``, a marketable limit, which is how a
    daily backtest actually produces an order price.

    Only HSX is measured, and that is a finding rather than a scoping
    convenience: HNX and UPCoM both carry a flat 0.1 tick
    (:data:`plutus.core.constant.HNX`, :data:`~plutus.core.constant.UPCOM`), so
    on those venues the naive model *is* the legal grid and occupancy is
    exactly zero by rule -- no measurement required, and none is claimed.

    The tick comes from :func:`plutus.core.constant.get_hsx_tick_size`, so this
    measures the shipped rule and not a restatement of it. Prices the band
    table does not resolve are counted separately rather than guessed at.

    Args:
        data_root: the Parquet corpus root.
        offset: the marketable-limit offset applied to the close.

    Returns:
        A single-element list: HSX stocks. Per-tick-band counts are in
        ``detail``, and they are where the result becomes interpretable -- the
        0.1 band contributes zero by construction, so an aggregate rate is
        really a statement about how much of the sample trades cheap.
    """
    root = Path(data_root)
    conn = duckdb.connect()

    rows = conn.execute(f"""
        SELECT cl.tickersymbol, cl.price, count(*) AS n
        FROM {_reader(root, 'quote_close')} cl
        JOIN {_reader(root, 'quote_ticker')} tk USING (tickersymbol)
        WHERE tk.exchangeid = 'HSX'
          AND tk.instrumenttype = 'stock'
          AND cl.price > 0
        GROUP BY 1, 2
    """).fetchall()

    observations = differ = unresolvable = 0
    displacement = Decimal(0)
    per_band: Dict[str, Dict[str, int]] = {}
    for symbol, price, n in rows:
        n = int(n)
        target = Decimal(str(price)) * (Decimal(1) + offset)
        tick = get_hsx_tick_size(symbol, target)
        observations += n
        if tick is None:
            unresolvable += n
            continue
        bucket = per_band.setdefault(str(tick), {'observations': 0,
                                                 'displaced': 0})
        bucket['observations'] += n
        if _snap(target, tick) != _snap(target, NAIVE_TICK):
            differ += n
            bucket['displaced'] += n
            displacement += abs(_snap(target, tick)
                                - _snap(target, NAIVE_TICK)) * n

    mean_gap = (displacement / Decimal(differ)) if differ else None
    return [RuleOccupancy(
        rule='tick_grid_displacement', venue='HSX',
        universe='HSX stock closes, priced as a marketable limit',
        definition=f'nearest legal price for close*(1+{offset}) differs from '
                   f'the nearest price on a flat {NAIVE_TICK} grid',
        window='2000-07-28 to 2022-12-30',
        observations=observations, binding=differ,
        occupancy=_rate(differ, observations),
        caveat='HNX and UPCoM carry a flat 0.1 tick, so the naive model is '
               'the legal grid there and occupancy is 0 by rule, not by '
               'measurement. On HSX the 0.1 band contributes 0 by the same '
               'logic -- read the per-band detail, not the headline alone. '
               'Ties round half-up, matching order entry rather than '
               "Python's default half-even.",
        detail={'per_tick_band': per_band,
                'unresolvable_prices': unresolvable,
                'mean_displacement_thousand_vnd': mean_gap,
                'offset': offset},
    )]


# --------------------------------------------------------------------------
# Round lot
# --------------------------------------------------------------------------

def measure_round_lot_reshaping(
    data_root: str,
    *,
    participation: Decimal = DEFAULT_PARTICIPATION,
) -> List[RuleOccupancy]:
    """How often the round lot reshapes or destroys a volume-scaled order.

    An order sized at ``participation * daily_volume`` meets the lot in force
    on that venue **on that date**
    (:func:`plutus.core.constant.get_trading_unit`): 10 on HSX before
    2021-01-04, 100 from then, 100 on HNX and UPCoM throughout.

    Two counts, and only the second is worth quoting:

    * **reshaped** -- the size is not a whole number of lots. This is reported
      for completeness and should not be cited, because it is fixed by
      arithmetic rather than by the market: a size uniform mod 100 is reshaped
      99% of the time, and the measured HSX post-2021 figure is 99.14%. It
      tells you the lot exists. It does not tell you the lot matters.
    * **annihilated** -- the size is *below* one lot, so the order rounds to
      zero shares and the strategy cannot trade that name that day. This one
      carries information, it varies enormously by venue, and it is the number
      to quote.

    Sizes are computed in exact integer arithmetic from the exact rational form
    of ``participation``; no float touches an order size.

    Args:
        data_root: the Parquet corpus root.
        participation: the fraction of daily volume an order takes.

    Returns:
        One :class:`RuleOccupancy` per (venue, lot-era), so the HSX 10-share
        era and 100-share era are never merged. Merging them would hide the
        very thing the dated lot exists to represent.
    """
    root = Path(data_root)
    conn = duckdb.connect()
    num, den = participation.as_integer_ratio()
    raised = VietnamMarketConstant.HSX_ROUND_LOT_RAISED

    rows = conn.execute(f"""
        WITH sized AS (
            SELECT tk.exchangeid AS venue,
                   (v.datetime < DATE '{raised}') AS before_raise,
                   (v.quantity * {num}) // {den} AS shares,
                   CASE WHEN tk.exchangeid = 'HSX'
                         AND v.datetime < DATE '{raised}'
                        THEN 10 ELSE 100 END AS lot
            FROM {_reader(root, 'quote_dailyvolume')} v
            JOIN {_reader(root, 'quote_ticker')} tk USING (tickersymbol)
            WHERE tk.instrumenttype = 'stock' AND v.quantity > 0
        )
        SELECT venue, lot, count(*) AS n,
               count(*) FILTER (WHERE shares % lot <> 0) AS reshaped,
               count(*) FILTER (WHERE shares < lot) AS annihilated,
               count(*) FILTER (WHERE shares < 100) AS annihilated_blind
        FROM sized GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchall()

    results: List[RuleOccupancy] = []
    for venue, lot, n, reshaped, annihilated, blind in rows:
        n, lot = int(n), int(lot)
        # Cross-check the dated lot against the shipped rulebook function on a
        # date inside this era, so a divergence between census and library is
        # a failure here rather than a silent inconsistency in the paper.
        probe = (raised.replace(year=raised.year - 1) if lot == 10 else raised)
        shipped = get_trading_unit(venue, probe)
        if shipped != lot:
            raise ValueError(
                f'census lot {lot} for {venue} on {probe} disagrees with the '
                f'shipped rulebook ({shipped}); one of the two is wrong and '
                f'the paper must not quote either until it is resolved')

        detail: Dict[str, Any] = {
            'lot': lot,
            'reshaped': int(reshaped),
            'reshaped_rate_IS_COMBINATORIAL_DO_NOT_CITE':
                _rate(int(reshaped), n),
            'participation': participation,
        }
        if lot != 100:
            # The exposure/occupancy bridge, and the reason the lot is dated.
            detail['annihilated_under_date_blind_lot_100'] = int(blind)
            detail['orders_wrongly_destroyed_by_date_blind_lot'] = (
                int(blind) - int(annihilated))
            detail['wrongly_destroyed_rate'] = _rate(
                int(blind) - int(annihilated), n)

        results.append(RuleOccupancy(
            rule='round_lot_annihilation', venue=f'{venue} (lot {lot})',
            universe='stock ticker-days with volume > 0',
            definition=f'an order of {participation} of daily volume is below '
                       f'one {lot}-share lot, so it rounds to zero shares and '
                       f'cannot be placed at all',
            window=('to 2021-01-03' if lot == 10 and venue == 'HSX'
                    else ('2021-01-04 onward' if venue == 'HSX'
                          else '2000-07-28 to 2022-12-30')),
            observations=n, binding=int(annihilated),
            occupancy=_rate(int(annihilated), n),
            caveat='The companion "reshaped" count in detail is fixed by '
                   'arithmetic (99% prior for a 100-share lot) and must not '
                   'be cited as evidence the rule matters. Annihilation is '
                   'the informative measure. Days on which a name did not '
                   'trade carry no volume row and are excluded, so this is a '
                   'rate over tradeable days.',
            detail=detail,
        ))
    return results


# --------------------------------------------------------------------------
# Foreign room
# --------------------------------------------------------------------------

def measure_foreign_room_headroom(
    archive_root: Optional[str],
) -> List[RuleOccupancy]:
    """How often remaining foreign room falls below one round lot.

    Foreign room is **not enforced** by the simulator in this iteration --
    declared tradeoff T1. That is exactly why it is measured: a tradeoff is
    only honest if the thing given up is quantified. This says how much was
    given up.

    The series is the intraday ``quote_foreignroom``, which lives in the raw
    archive and **not** in the Parquet corpus. The corpus's daily
    ``quote_totalforeignroom`` is not a substitute: it covers 83 dates and 16.5%
    of it is a zero placeholder for names it has no data on (see
    :func:`measure_daily_room_placeholder`).

    **The denominator is ticker-days, not rows, and that is load-bearing.**
    ``quote_foreignroom`` changes sampling regime at 2021: before it, one row
    per ticker-day; after, intraday polling at roughly 26 rows per ticker-day.
    A rate computed over rows therefore compares a daily series against an
    intraday one and is meaningless across the boundary. Ticker-days are
    comparable; rows are not.

    A ticker-day counts as binding when the day's **minimum** room is below the
    lot in force -- the room was, at some observed instant, too small for even
    one lot.

    Args:
        archive_root: the raw archive root, or ``None``.

    Returns:
        A row-level reproduction of the prior finding, then one entry per
        (venue, lot-era) on the ticker-day denominator. If ``archive_root`` is
        ``None`` or lacks the file, a single ``measurable_in_corpus=False``
        entry is returned instead -- an absent measurement is stated, never
        omitted.
    """
    unavailable = [RuleOccupancy(
        rule='foreign_room_below_lot', venue='ALL',
        universe='intraday foreign room observations',
        definition='remaining foreign room is below one round lot, so a '
                   'lot-sized foreign buy cannot be filled',
        window='n/a', observations=0, binding=None, occupancy=None,
        measurable_in_corpus=False,
        reason='quote_foreignroom is in the raw archive, not the Parquet '
               'corpus. Pass --archive-root to measure it. The corpus '
               'quote_totalforeignroom is not a substitute: 83 dates, and '
               '16.5% of its rows are zero placeholders.',
    )]
    if archive_root is None:
        return unavailable
    root = Path(archive_root)
    if not (root / 'quote_foreignroom.csv').exists():
        return unavailable

    conn = duckdb.connect()
    room = _reader(root, 'quote_foreignroom')
    raised = VietnamMarketConstant.HSX_ROUND_LOT_RAISED

    n, lt100, lt10, zeros, minimum = conn.execute(f"""
        SELECT count(*), count(*) FILTER (WHERE quantity < 100),
               count(*) FILTER (WHERE quantity < 10),
               count(*) FILTER (WHERE quantity = 0), min(quantity)
        FROM {room}
    """).fetchone()

    results = [RuleOccupancy(
        rule='foreign_room_below_lot', venue='ALL',
        universe='raw intraday foreign-room observations',
        definition='a single observation of remaining room below 100 shares',
        window='2006-12-28 to 2022-12-30',
        observations=int(n), binding=int(lt100),
        occupancy=_rate(int(lt100), int(n)),
        caveat='ROW-LEVEL, and rows are not a valid denominator across the '
               '2021 sampling-regime change -- this entry exists to reproduce '
               'the previously reported 34,653 and to date it. Use the '
               'per-venue ticker-day entries below for any rate. The rule is '
               'not enforced (tradeoff T1); this measures what enforcement '
               'would have caught, and being below a lot is necessary but not '
               'sufficient for a block, since rejected orders are never '
               'observable.',
        detail={'below_100_shares': int(lt100),
                'below_10_shares': int(lt10),
                'exactly_zero': int(zeros),
                'minimum_room_observed': int(minimum)},
    )]

    rows = conn.execute(f"""
        WITH daily AS (
            SELECT tickersymbol, cast(datetime AS DATE) AS dt,
                   min(quantity) AS low_room
            FROM {room} GROUP BY 1, 2
        )
        SELECT tk.exchangeid AS venue,
               CASE WHEN tk.exchangeid = 'HSX' AND d.dt < DATE '{raised}'
                    THEN 10 ELSE 100 END AS lot,
               count(*) AS n,
               count(*) FILTER (
                   WHERE d.low_room < CASE WHEN tk.exchangeid = 'HSX'
                                            AND d.dt < DATE '{raised}'
                                           THEN 10 ELSE 100 END) AS below
        FROM daily d
        JOIN {_reader(root, 'quote_ticker')} tk USING (tickersymbol)
        GROUP BY 1, 2 ORDER BY 1, 2
    """).fetchall()

    for venue, lot, days, below in rows:
        results.append(RuleOccupancy(
            rule='foreign_room_below_lot', venue=f'{venue} (lot {lot})',
            universe='ticker-days with any foreign-room observation',
            definition=f'the day\'s minimum observed room is below one '
                       f'{lot}-share lot',
            window=('to 2021-01-03' if lot == 10 else '2021-01-04 onward'
                    if venue == 'HSX' else '2006-12-28 to 2022-12-30'),
            observations=int(days), binding=int(below),
            occupancy=_rate(int(below), int(days)),
            caveat='Pre-2021 ticker-days carry ONE observation each and '
                   'post-2021 ticker-days carry many, so a pre-2021 day has '
                   'fewer chances to be caught binding. The pre-2021 HSX rate '
                   'is nonetheless the highest here, under a stricter '
                   '10-share threshold -- consistent with the well-documented '
                   'full-room ("het room") names of that era: the sub-lot '
                   'observations concentrate in FPT, MBB, TMS, PNJ, ACB, IMP, '
                   'HCM, DHG, MWG, REE and VNM. Not enforced; tradeoff T1.',
            detail={'lot': lot},
        ))
    return results


def measure_daily_room_placeholder(data_root: str) -> RuleOccupancy:
    """Reproduce the zero-placeholder defect in ``quote_totalforeignroom``.

    Not a rule finding, and filed under ``defects`` rather than ``rules`` for
    that reason. It is carried because the table is the obvious place to look
    for foreign room in the Parquet corpus, and taken at face value it yields a
    fabricated 16.5% "room exhausted" occupancy.

    The disproof is corroboration, not inspection: the always-zero tickers
    appear in neither ``quote_foreignroom`` nor ``quote_dailyforeignbuy`` --
    zero ticker-days in each. A value present in one table and absent from both
    of its corroborators is missing data wearing a number.
    """
    root = Path(data_root)
    conn = duckdb.connect()

    n, zeros, dates = conn.execute(f"""
        SELECT count(*), count(*) FILTER (WHERE quantity = 0),
               count(DISTINCT datetime)
        FROM {_reader(root, 'quote_totalforeignroom')}
    """).fetchone()
    always, sometimes = conn.execute(f"""
        WITH t AS (
            SELECT tickersymbol, count(*) AS n,
                   count(*) FILTER (WHERE quantity = 0) AS z
            FROM {_reader(root, 'quote_totalforeignroom')} GROUP BY 1
        )
        SELECT count(*) FILTER (WHERE z = n), count(*) FILTER (WHERE z > 0
                                                                AND z < n)
        FROM t
    """).fetchone()

    return RuleOccupancy(
        rule='daily_foreign_room_zero_placeholder', venue='ALL',
        universe='quote_totalforeignroom rows',
        definition='rows reporting exactly zero remaining foreign room',
        window='2022-09-07 to 2022-12-30',
        observations=int(n), binding=int(zeros),
        occupancy=_rate(int(zeros), int(n)),
        measurable_in_corpus=True,
        caveat='THIS IS A CORPUS DEFECT, NOT A RULE OCCUPANCY. Reading it as '
               'occupancy reports a fictitious "foreign room exhausted" rate. '
               f'{int(always)} tickers are zero on every one of the '
               f'{int(dates)} dates and appear in neither quote_foreignroom '
               'nor quote_dailyforeignbuy. Use the intraday series, whose '
               'minimum is 1 and which contains no zeros at all.',
        detail={'tickers_always_zero': int(always),
                'tickers_sometimes_zero': int(sometimes),
                'dates': int(dates)},
    )


# --------------------------------------------------------------------------
# What a daily close series cannot speak to
# --------------------------------------------------------------------------

def _absent(rule: str, venue: str, definition: str,
            reason: str) -> RuleOccupancy:
    return RuleOccupancy(
        rule=rule, venue=venue, universe='n/a', definition=definition,
        window='n/a', observations=0, binding=None, occupancy=None,
        measurable_in_corpus=False, reason=reason,
    )


#: Rules the simulator enforces whose occupancy this corpus cannot measure.
#:
#: These are listed, not omitted. An omission implies the census is exhaustive,
#: which would let a reader infer that an unlisted rule never binds -- the
#: opposite of what is true for most of these, since session structure binds on
#: every order ever placed. Following ``dated_rules.measurable_in_corpus``.
NOT_MEASURABLE: Tuple[RuleOccupancy, ...] = (
    _absent(
        'auction_phase_ato_atc', 'HSX/HNX',
        'an order rests in an opening or closing call auction rather than in '
        'continuous matching',
        'A daily close series has no intraday phase, so there is no proxy for '
        'auction participation and none is invented here. The tick archive '
        'cannot rescue it either: quote_bidsize and quote_asksize are 37-byte '
        'header-only files in all three copies on this machine, and the '
        'auction clearing price depends entirely on them. UPCoM has no '
        'auction batch at all.',
    ),
    _absent(
        'plo_post_close_session', 'HNX',
        'an order executes in the 14:45-15:00 post-close session at the '
        'closing price',
        'PLO trades settle at the already-determined closing price, so they '
        'are indistinguishable from continuous-session trades in a daily bar. '
        'Separating them needs a phase-tagged tape, which the corpus lacks.',
    ),
    _absent(
        'noon_break', 'HSX/HNX/UPCOM',
        'an order arriving between 11:30 and 13:00 waits for the resumption',
        'A daily bar has one timestamp per session. Nothing in it distinguishes '
        'a morning fill from an afternoon one.',
    ),
    _absent(
        'order_matching_priority', 'ALL',
        'price-time priority reorders two otherwise identical resting orders',
        'Priority is a property of the order queue, and the queue is not '
        'recoverable: 81.0% of captures where a best quote changed carry no '
        'traded volume and no delete marker, so adds and cancels cannot be '
        'told apart, and up to 27 tickers share a single capture microsecond '
        'so intra-capture ordering is lost.',
    ),
    _absent(
        'settlement_delivery_instant', 'ALL',
        'shares become sellable at 13:00 on T+2 rather than at the next '
        'session open',
        'Changes the first sellable INSTANT, not the cycle length, so it is '
        'invisible in a daily close series -- the same reason '
        'dated_rules.py marks it unmeasurable. Decisive for an intraday sell.',
    ),
    _absent(
        'foreign_room_block_realised', 'ALL',
        'a foreign buy is actually rejected for want of room',
        'Rejected orders are never published by any venue, so the realised '
        'block rate is unobservable in principle, not merely absent here. '
        'measure_foreign_room_headroom bounds it from above by measuring when '
        'room was too small for a lot, which is necessary but not sufficient.',
    ),
)


def measure_occupancy(
    data_root: str,
    *,
    archive_root: Optional[str] = None,
    offset: Decimal = DEFAULT_MARKETABLE_OFFSET,
    participation: Decimal = DEFAULT_PARTICIPATION,
) -> OccupancyCensus:
    """The full occupancy census: every rule measured, and every rule not.

    Args:
        data_root: the Parquet corpus root.
        archive_root: the raw archive root, needed only for foreign room.
        offset: marketable-limit offset for the tick rule.
        participation: fraction of daily volume for the lot rule.

    Returns:
        An :class:`OccupancyCensus`. ``rules`` holds the measured rules first
        and the unmeasurable ones last; ``defects`` holds corpus artefacts that
        masquerade as occupancy.
    """
    rules: List[RuleOccupancy] = []
    rules += measure_band_lock(data_root)
    rules += measure_tick_grid_displacement(data_root, offset=offset)
    rules += measure_round_lot_reshaping(data_root,
                                         participation=participation)
    rules += measure_foreign_room_headroom(archive_root)
    rules += list(NOT_MEASURABLE)
    return OccupancyCensus(
        rules=rules,
        defects=[measure_daily_room_placeholder(data_root)],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument(
        '--archive-root', default=None,
        help='Raw archive root; required for the foreign-room entries, which '
             'are reported as unmeasurable without it.')
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()

    census = measure_occupancy(args.data_root, archive_root=args.archive_root)

    print(f"{'rule':<34}{'venue':<18}{'observations':>14}"
          f"{'binding':>12}{'occupancy':>12}")
    print('-' * 90)
    measured: Sequence[RuleOccupancy] = [r for r in census.rules
                                         if r.measurable_in_corpus]
    for r in measured:
        print(f'{r.rule:<34}{r.venue:<18}{r.observations:>14,}'
              f'{r.binding:>12,}{float(r.occupancy):>11.2%}')

    bridge = next(
        (r for r in measured
         if 'orders_wrongly_destroyed_by_date_blind_lot' in r.detail), None)
    if bridge is not None:
        print(f'\nEXPOSURE -> OCCUPANCY, {bridge.venue}: a date-blind lot of '
              f'100 destroys\n'
              f'  {bridge.detail["orders_wrongly_destroyed_by_date_blind_lot"]:,}'
              f' orders '
              f'({float(bridge.detail["wrongly_destroyed_rate"]):.1%} of the '
              f'era) that the dated lot lets through.')

    print('\nNOT MEASURABLE IN A DAILY CLOSE SERIES (listed so the census is '
          'not read as exhaustive)')
    print('-' * 90)
    for r in census.rules:
        if not r.measurable_in_corpus:
            print(f'  {r.rule}  [{r.venue}]')
            for line in textwrap.wrap(r.reason, 84):
                print(f'      {line}')

    print('\nCORPUS DEFECTS THAT LOOK LIKE OCCUPANCY')
    print('-' * 90)
    for d in census.defects:
        print(f'  {d.rule}: {d.binding:,}/{d.observations:,} '
              f'({float(d.occupancy):.1%})')
        for line in textwrap.wrap(d.caveat, 84):
            print(f'      {line}')

    print('\nOccupancy is how often a rule BOUND. Exposure -- how much of the '
          'sample sat under a\nsuperseded rule -- is a different and looser '
          'number, measured in dated_rules.py.\nQuote each rule separately; '
          'no average across rules is meaningful.')

    if args.json:
        args.json.write_text(json.dumps(census.to_dict(), indent=2))
        print(f'wrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
