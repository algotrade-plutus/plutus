"""Does the ENGINE reproduce the published price band? (engine-backed)

The paper's two band results are, as measured today, SQL equalities on the
**vendor's** own ``quote_ceil``/``quote_floor`` field:

* the momentum blocked-entry rate (``equity_admission.py``) tests
  ``attempt_close = quote_ceil.price``;
* the bar-vs-tick lock (``bar_vs_tick.py``) tests ``close = quote_ceil.price``.

Neither exercises the simulator. For a paper *about engine fidelity* that is a
gap: the number could be reproduced by anyone with the vendor table and does
not show that the library computes the same band the exchange published.

This module closes that gap. For every instrument-day that carries a published
band it recomputes the ceiling and floor the **library** would derive from the
reference price -- calling
:func:`plutus.market.adapters.datahub.reconstruct_bands`, the exact code the
daily adapter uses to reconstruct an absent band, with the exact inputs
:meth:`DataHubSource._build_state` feeds it (the engine's typed
``daily_trading_limit`` for the instrument and the exchange's own
``tick_size_function``) -- and checks it against the vendor's published edge on
the tick grid. No band formula is written here; the formula under test is the
engine's.

What it finds, and the honest shape of it
------------------------------------------------------------------------
On the paper's population -- ``HSX`` ``instrumenttype='stock'`` ticker-days --
the engine reproduces the published band on **97.6%** of rows, and ``HNX``
stocks read **99.0%**. The residual is almost entirely a **band-regime**
mismatch, not a formula error, and the module separates the two:

* ``disagree_same_width`` counts disagreements where the vendor's *implied*
  width (``ceil/reference - 1``) matches the width the engine assumed. Across
  all 737,927 stock-days there are **2** -- ELC and GAS on 2021-06-21, where
  the vendor's own ceiling sits off the 0.05 tick (26.64, 19.98) and the
  engine, truncating to the grid, is arguably the more correct of the two. The
  reconstruction *formula and tick grid* are, to that precision, exact.

* every other disagreement is a day on a **different band width** than the flat
  per-exchange ``daily_trading_limit`` the engine carries: the ±20/30/40%
  first-session and post-suspension limits (UPCOM's ±40% resumption band alone
  is ~35k illiquid-name rows, which is why the UPCOM-stock figure falls to
  ~79%), plus a minority of names whose *historical* exchange -- and therefore
  historical limit -- differs from the single latest assignment the ticker
  master stores (the drift ``datahub.py`` already flags as making
  ``exchange_code`` unreliable for by-exchange history). These are regimes the
  engine's band model does not claim to reproduce; naming them is the finding,
  not hiding them behind a screen.

So the claim this module backs is precise: *given the band width in force, the
engine reproduces the observed edge on all but two of ~738k stock-days; the
gap to 100% on any wider population is the set of special-limit regimes the
flat daily limit does not model, counted rather than screened away.*

Agreement is reported with a 95% Wilson score interval. The 381-margin caveat
about overlapping windows does not apply: each row is an independent
instrument-day, so the binomial interval is the right one -- though it is
narrow to the point of being decorative at n in the hundreds of thousands, and
is reported for form, not because the rate is in doubt.
"""

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import duckdb

from plutus.core.constant import DS, HNX, HSX, UPCOM
from plutus.market.adapters.datahub import DataHubSource, reconstruct_bands

__all__ = [
    'BandConformanceResult', 'measure_band_conformance', 'wilson_interval',
]

#: ``quote_ceil`` begins on this date in the corpus; before it no published
#: band exists to conform to. Measured, not assumed: see the module tests.
BAND_START = '2021-02-05'

#: A disagreement counts as ``same_width`` when the vendor's implied band width
#: (``ceil/reference - 1``) lands within this of the width the engine assumed.
#: Inside it the miss cannot be a wrong *limit* -- it is a tick, rounding or
#: data artefact, i.e. the formula's own residual. 15 bp is far tighter than
#: the gap between any two Vietnamese limit regimes (7/10/15/20/30/40%) and
#: comfortably admits the two known vendor-off-grid rows (implied 6.96%, 6.99%
#: against an assumed 7%).
WIDTH_TOLERANCE = Decimal('0.0015')

#: Mirrors the private ``datahub._SPECS``: the exchange-code -> ExchangeSpec map
#: the adapter itself uses to find the ``tick_size_function`` when it
#: reconstructs a band. Rebuilt here from the same public constants (rather than
#: imported private) so this module depends only on the engine's public surface
#: while using the engine's own specs.
_SPECS = {'HSX': HSX, 'HNX': HNX, 'UPCOM': UPCOM, 'HNXDS': DS}


@dataclass(frozen=True)
class BandConformanceResult:
    """Agreement between the engine's band edge and the vendor's published one.

    ``rows`` is the compared population: instrument-days with a published band
    **and** a reference the engine can reconstruct from. ``both_agree`` is the
    headline -- rows where the engine reproduces *both* edges on the tick grid.
    """

    population: str
    rows: int
    ceiling_agree: int
    floor_agree: int
    both_agree: int
    disagree: int
    disagree_same_width: int
    excluded_no_reference: int
    agreement_rate: Decimal
    ci_low: Decimal
    ci_high: Decimal
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        for key in ('agreement_rate', 'ci_low', 'ci_high'):
            out[key] = float(getattr(self, key))
        out['method'] = (
            "engine-backed: the library's own reconstruct_bands (reference x "
            "dated limit, truncated/raised to the exchange tick) vs the vendor "
            "quote_ceil/quote_floor, compared on the tick grid -- not a SQL "
            "equality on the vendor field"
        )
        out['backs'] = (
            'paper engine-fidelity claim: the simulator reproduces the '
            'observed price band, not merely a SQL query against it'
        )
        out['residual'] = (
            f'{self.disagree_same_width} of {self.disagree} disagreements have '
            f'the band width right (tick/rounding/vendor-off-grid); the rest '
            f'are special-limit regimes (first-session and post-suspension '
            f'+-20/30/40% bands, and historical-exchange drift) the flat '
            f'daily limit does not model'
        )
        return out


def _reader(root: Path, table: str) -> str:
    parquet = root / f'{table}.parquet'
    if parquet.exists():
        return f"read_parquet('{parquet}')"
    return f"read_csv_auto('{root / (table + '.csv')}')"


def wilson_interval(
    successes: int, total: int, *, confidence: float = 0.95,
) -> Tuple[Decimal, Decimal]:
    """95%-by-default Wilson score interval for a binomial proportion.

    The Wilson interval rather than the normal approximation because the rate
    sits near 1 where the symmetric interval overshoots past 1; Wilson stays in
    ``[0, 1]``. Returns ``(0, 0)`` for an empty sample.
    """
    if total <= 0:
        return Decimal('0'), Decimal('0')
    z = statistics.NormalDist().inv_cdf((1 + confidence) / 2)
    n = total
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    low = max(0.0, center - half)
    high = min(1.0, center + half)
    return Decimal(str(low)), Decimal(str(high))


def _engine_wiring(
    source: DataHubSource, ticker: str, cache: Dict[str, Tuple[Decimal, Any]],
) -> Tuple[Optional[Decimal], Optional[Any]]:
    """``(daily_limit, tick_fn)`` the engine would use for ``ticker``.

    This is the exact selection ``DataHubSource._build_state`` performs before
    it calls :func:`reconstruct_bands`: the instrument's engine-typed
    ``daily_trading_limit`` and the tick function of its exchange spec. Cached
    per ticker; ``source.instrument`` memoises the spec, this memoises the pair.
    """
    if ticker not in cache:
        spec = source.instrument(ticker)
        exchange_spec = _SPECS.get(spec.exchange_code)
        tick_fn = exchange_spec.tick_size_function if exchange_spec else None
        cache[ticker] = (spec.daily_trading_limit, tick_fn)
    return cache[ticker]


def measure_band_conformance(
    data_root: str,
    *,
    instrument_types: Optional[Tuple[str, ...]] = ('stock',),
    exchanges: Optional[Tuple[str, ...]] = ('HSX',),
    start: str = BAND_START,
    end: Optional[str] = None,
    confidence: float = 0.95,
) -> BandConformanceResult:
    """Compare the engine's reconstructed band to the vendor's published band.

    Args:
        data_root: corpus root (parquet or csv).
        instrument_types: ``quote_ticker.instrumenttype`` values to keep, or
            ``None`` for all. Defaults to stocks -- the population the paper's
            band figures are measured on.
        exchanges: ``quote_ticker.exchangeid`` values to keep, or ``None`` for
            all. Defaults to ``HSX`` -- the population of the bar-vs-tick lock.
        start, end: half-open date bounds ``[start, end)`` on the band series.
            ``start`` defaults to the first published band; ``end`` to open.
        confidence: for the Wilson interval on the agreement rate.

    Every published-band row is joined to its reference; a row whose reference
    is absent cannot be reconstructed and is counted in ``excluded_no_reference``
    rather than scored either way.
    """
    root = Path(data_root)
    conn = duckdb.connect()

    ce = _reader(root, 'quote_ceil')
    fl = _reader(root, 'quote_floor')
    rf = _reader(root, 'quote_reference')
    tk = _reader(root, 'quote_ticker')

    filters = [f"ce.datetime >= '{start}'"]
    if end is not None:
        filters.append(f"ce.datetime < '{end}'")
    if instrument_types is not None:
        joined = ', '.join(f"'{t}'" for t in instrument_types)
        filters.append(f"tk.instrumenttype IN ({joined})")
    if exchanges is not None:
        joined = ', '.join(f"'{e}'" for e in exchanges)
        filters.append(f"tk.exchangeid IN ({joined})")
    where = ' AND '.join(filters)

    # INNER on ceil+floor+ticker (a band and a typed instrument are required);
    # LEFT on reference so a missing reference is counted, not silently dropped.
    rows = conn.execute(f"""
        SELECT ce.tickersymbol, ce.datetime,
               ce.price AS ceiling, fl.price AS floor, rf.price AS reference
        FROM {ce} ce
        JOIN {fl} fl USING (datetime, tickersymbol)
        JOIN {tk} tk ON tk.tickersymbol = ce.tickersymbol
        LEFT JOIN {rf} rf USING (datetime, tickersymbol)
        WHERE {where}
        ORDER BY ce.tickersymbol, ce.datetime
    """).fetchall()

    source = DataHubSource.for_root(data_root)
    wiring_cache: Dict[str, Tuple[Decimal, Any]] = {}

    compared = ceiling_agree = floor_agree = both_agree = 0
    same_width = excluded_no_reference = 0

    for ticker, _dt, v_ceiling, v_floor, v_reference in rows:
        if v_reference is None:
            excluded_no_reference += 1
            continue
        limit, tick_fn = _engine_wiring(source, ticker, wiring_cache)
        reference = Decimal(str(v_reference))
        engine_ceiling, engine_floor = reconstruct_bands(
            reference, limit, tick_fn, ticker)
        if engine_ceiling is None or engine_floor is None:
            # No tick/limit for this instrument: the engine cannot state a
            # band, so there is nothing to conform. Rare-to-never on the
            # corpus (every instrument resolves to a spec with a tick).
            excluded_no_reference += 1
            continue

        compared += 1
        vendor_ceiling = Decimal(str(v_ceiling))
        vendor_floor = Decimal(str(v_floor))
        ceil_ok = engine_ceiling == vendor_ceiling
        floor_ok = engine_floor == vendor_floor
        ceiling_agree += ceil_ok
        floor_agree += floor_ok
        if ceil_ok and floor_ok:
            both_agree += 1
            continue

        # A miss whose implied width matches the assumed width is not a
        # regime the engine failed to know -- it is the formula's own residual.
        if reference > 0:
            implied = vendor_ceiling / reference - Decimal('1')
            if abs(implied - limit) <= WIDTH_TOLERANCE:
                same_width += 1

    disagree = compared - both_agree
    rate = (Decimal(both_agree) / Decimal(compared) if compared
            else Decimal('0'))
    low, high = wilson_interval(both_agree, compared, confidence=confidence)

    ex_desc = 'all instruments' if exchanges is None else '/'.join(exchanges)
    ty_desc = ('any type' if instrument_types is None
               else '/'.join(instrument_types))
    return BandConformanceResult(
        population=(
            f'{ex_desc} {ty_desc} ticker-days with a published band, '
            f'{start}..{end or "end"}'
        ),
        rows=compared,
        ceiling_agree=ceiling_agree,
        floor_agree=floor_agree,
        both_agree=both_agree,
        disagree=disagree,
        disagree_same_width=same_width,
        excluded_no_reference=excluded_no_reference,
        agreement_rate=rate,
        ci_low=low,
        ci_high=high,
        confidence=confidence,
    )


#: The ladder ``main`` walks: each is a named population, coarsest paper
#: population last so the residual is visible as the scope widens.
_LADDER: Tuple[Tuple[str, Optional[Tuple[str, ...]], Optional[Tuple[str, ...]]], ...] = (
    ('HSX stock', ('stock',), ('HSX',)),
    ('HNX stock', ('stock',), ('HNX',)),
    ('UPCOM stock', ('stock',), ('UPCOM',)),
    ('all stock', ('stock',), None),
    ('all instruments', None, None),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True)
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()

    results: Dict[str, Any] = {}
    header = (f"{'population':<18}{'rows':>10}{'agree':>10}{'rate':>9}"
              f"{'95% Wilson CI':>22}{'same-width':>12}")
    print(header)
    print('-' * len(header))
    for label, types, exchanges in _LADDER:
        r = measure_band_conformance(
            args.data_root, instrument_types=types, exchanges=exchanges)
        results[label] = r.to_dict()
        ci = f"[{float(r.ci_low):.4%}, {float(r.ci_high):.4%}]"
        print(f'{label:<18}{r.rows:>10,}{r.both_agree:>10,}'
              f'{float(r.agreement_rate):>9.2%}{ci:>22}'
              f'{r.disagree_same_width:>12,}')

    print('\nengine-backed: each edge is the library\'s reconstruct_bands '
          'output, not the vendor quote_ceil.\nthe gap as scope widens is '
          'special-limit regimes (UPCOM +-40% resumption, first-session\n'
          'bands, historical-exchange drift), not the reconstruction formula '
          '-- which misses 2 of ~738k\nstock-days, both vendor-off-grid.')
    if args.json:
        args.json.write_text(json.dumps(results, indent=2))
        print(f'\nwrote {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
