"""WP4: the dataset audit, with its measured counts pinned.

The exact counts are asserted on purpose. They are quoted in the project's
documentation and in the paper, so a silent change to the corpus or to a
check's definition must fail CI rather than quietly invalidate a published
number.

Tests needing the corpus skip when it is absent, so the suite still runs on a
machine without it.
"""

import json
import os
from pathlib import Path

import pytest

from plutus.data.audit import AuditReport, CheckResult, DataAudit


def _corpus_root():
    candidates = []
    env = os.environ.get('PLUTUS_DATA_ROOT')
    if env:
        candidates.append(Path(env))
    candidates.append(Path('/Users/nadan/algotrade-research/dataset/hermes-parquet'))
    for root in candidates:
        if (root / 'quote_close.parquet').exists() or (root / 'quote_close.csv').exists():
            return root
    return None


CORPUS = _corpus_root()

requires_corpus = pytest.mark.skipif(
    CORPUS is None, reason="No corpus found; set PLUTUS_DATA_ROOT."
)


@pytest.fixture(scope='module')
def report():
    return DataAudit(CORPUS).run()


def _check(report: AuditReport, name: str) -> CheckResult:
    return next(c for c in report.checks if c.name == name)


# --- structure --------------------------------------------------------------

def test_missing_root_is_rejected():
    with pytest.raises(FileNotFoundError):
        DataAudit('/nonexistent/path/to/nowhere')


@requires_corpus
def test_unknown_check_name_is_rejected():
    with pytest.raises(ValueError, match='Unknown check'):
        DataAudit(CORPUS).run(only=['no_such_check'])


@requires_corpus
def test_all_checks_run(report):
    assert len(report.checks) == len(DataAudit.CHECKS)
    assert report.skipped == [], [c.skipped_reason for c in report.skipped]


@requires_corpus
def test_report_is_machine_readable(report):
    """The report must survive a strict JSON round trip."""
    decoded = json.loads(report.to_json())

    assert decoded['summary']['checks_run'] == len(DataAudit.CHECKS)
    assert isinstance(decoded['checks'], list)
    for check in decoded['checks']:
        assert {'name', 'invariant', 'violations', 'total'} <= set(check)


# --- the measured counts ----------------------------------------------------

@requires_corpus
def test_inverted_price_bands(report):
    """1,272 rows across exactly three days."""
    check = _check(report, 'price_band_invariant')

    assert check.violations == 1272
    assert set(check.detail['by_day']) == {'2021-02-08', '2021-02-09', '2021-02-17'}
    assert check.detail['by_day']['2021-02-17'] == 1265


@requires_corpus
def test_ohlc_invariant_violations(report):
    """A defect class independent of the ceiling/floor swap."""
    check = _check(report, 'ohlc_invariants')

    assert check.detail['high_below_open_or_close'] == 327
    assert check.detail['low_above_open_or_close'] == 99
    assert check.total == 3_877_981


@requires_corpus
def test_non_vietnamese_contamination(report):
    """A foreign index series shares tables billed as Vietnamese.

    The count is every row of the offending symbol, not just the rows that
    tripped the test. A date-only rule reported 33,210 here — the pre-2000
    tail — while passing the same instrument's remaining 5,643 rows.
    """
    check = _check(report, 'non_vietnamese_symbols')

    assert check.detail['by_symbol'] == {'SPX': 38853}
    # SPX carries no exchange, so only the calendar signal can catch it.
    assert 'SPX' in check.detail['flagged_by_calendar']


@requires_corpus
def test_foreign_exchange_registration_is_checked(report):
    """Contemporaneous foreign data must be catchable without a date signal.

    The upstream database also carries Taiwanese (TWOTC) instruments spanning
    2019-2024. Those fall entirely inside the Vietnamese date range, so a
    date-based rule cannot see them. This corpus has none, but the check must
    be structured to catch them if a future export includes them.
    """
    check = _check(report, 'non_vietnamese_symbols')

    assert 'flagged_by_exchange' in check.detail
    for symbol, exchange in check.detail['flagged_by_exchange'].items():
        assert exchange not in DataAudit.VIETNAM_EXCHANGES, (symbol, exchange)


@requires_corpus
def test_unregistered_vietnamese_symbols_are_not_called_foreign(report):
    """VNINDEX and the VN30F futures carry no exchange but are Vietnamese."""
    check = _check(report, 'non_vietnamese_symbols')

    flagged = set(check.detail['by_symbol'])
    assert 'VNINDEX' not in flagged
    assert not any(s.startswith('VN30F') for s in flagged)


@requires_corpus
def test_non_session_timestamps(report):
    check = _check(report, 'non_session_timestamps')

    assert check.violations == 3526


@requires_corpus
def test_orphan_symbols(report):
    """87 of 1,988 quoted symbols are absent from the ticker master."""
    check = _check(report, 'orphan_symbols')

    assert check.violations == 87
    assert check.total == 1988
    # Orphans cannot be resolved to an exchange, so their tick size, round lot
    # and price band are all unknown.
    assert len(check.detail['symbols']) == 87


@requires_corpus
def test_empty_tables(report):
    """Present-but-empty tables pass every existence check, then return nothing."""
    check = _check(report, 'empty_tables')

    assert sorted(check.detail['tables']) == [
        'quote_asksize', 'quote_bidsize', 'quote_totalask', 'quote_totalbid',
    ]


@requires_corpus
def test_vn30_survivorship_gap(report):
    """12 snapshots of 30 members, but 53 distinct tickers were ever members."""
    check = _check(report, 'vn30_survivorship')

    assert check.detail['snapshots'] == 12
    assert check.detail['members_per_snapshot'] == 30
    assert check.detail['distinct_members_ever'] == 53
    # Back-projecting one snapshot over all history would omit 23 tickers.
    assert check.violations == 23


@requires_corpus
def test_ragged_coverage_is_reported(report):
    check = _check(report, 'ragged_coverage')

    assert check.violations > 0
    assert 'quote_close' in check.detail['coverage']
    assert check.detail['coverage']['quote_close']['last'].startswith('2022-12-30')


# --- reusable exclusions ----------------------------------------------------

@requires_corpus
def test_inverted_band_exclusions_are_available_as_data():
    """The paper's band filter must be reproducible, not ad hoc."""
    pairs = DataAudit(CORPUS).inverted_band_exclusions()

    assert len(pairs) == 1272
    assert len({str(d)[:10] for d, _ in pairs}) == 3


# --- strict query mode ------------------------------------------------------

@requires_corpus
def test_strict_mode_excludes_pre_exchange_rows():
    """SPX predates the HSX opening; strict mode must drop those rows."""
    from plutus.datahub.config import DataHubConfig
    from plutus.datahub.ohlc_query import OHLCQuery

    query = OHLCQuery(config=DataHubConfig(data_root=str(CORPUS)))

    def count(strict):
        return len(query.fetch(
            'SPX', '1990-01-01', '2023-01-01',
            interval='1d', include_volume=False, strict=strict,
        ).to_dataframe())

    assert count(strict=False) > count(strict=True)


@requires_corpus
def test_strict_mode_excludes_weekend_rows():
    """VTL carries exactly 9 weekend observations."""
    from plutus.datahub.config import DataHubConfig
    from plutus.datahub.ohlc_query import OHLCQuery

    query = OHLCQuery(config=DataHubConfig(data_root=str(CORPUS)))

    def count(strict):
        return len(query.fetch(
            'VTL', '2000-01-01', '2023-01-01',
            interval='1d', include_volume=False, strict=strict,
        ).to_dataframe())

    assert count(strict=False) - count(strict=True) == 9


@requires_corpus
def test_strict_is_the_default_and_leaves_clean_data_alone():
    from plutus.datahub.config import DataHubConfig
    from plutus.datahub.ohlc_query import OHLCQuery

    query = OHLCQuery(config=DataHubConfig(data_root=str(CORPUS)))
    strict = query.fetch('FPT', '2021-01-15', '2021-02-15', interval='1d')
    loose = query.fetch(
        'FPT', '2021-01-15', '2021-02-15', interval='1d', strict=False,
    )

    assert len(strict.to_dataframe()) == len(loose.to_dataframe()) == 18


# --- adjusted-price degeneracy ---------------------------------------------

@requires_corpus
def test_adjusted_prices_retain_raw_variation(report):
    """Adjustment must not round a price series onto a coarse grid.

    Upstream stores adjclose as numeric(11,2). A heavily-adjusted, low-priced
    ticker quantizes onto a 0.01 grid and its series collapses. This corpus is
    clean at a 10% retention floor -- the worst ticker keeps ~38% -- but the
    defect worsens as AdjRatio accumulates, so a later re-export will quantize
    harder. This test is the tripwire for that.
    """
    check = _check(report, 'adjusted_price_degeneracy')

    # No ticker falls below the retention floor.
    assert check.detail['degraded'] == []
    assert check.total > 1000


@requires_corpus
def test_zero_adjusted_prices_are_disclosed_but_screened_by_liquidity(report):
    """A zero adjusted price is invalid -- but only matters if tradeable.

    PTG carries 891 zero rows (2010-2013) in every adj* table while its raw
    series has none, so the adjustment produces them. It also traded on 39
    sessions out of 3,243 observations, at a median 300 shares: a delisted
    shell, not a usable series. Its zeros are disclosed rather than counted.

    Price variation is not liquidity. A shell carries its last price forward
    for years, which looks like collapsed variation and is nothing of the
    kind -- VTM and CMP hold 1,755 and 1,727 observations against zero
    sessions traded.
    """
    check = _check(report, 'adjusted_price_degeneracy')

    assert check.detail['zero_valued_below_liquidity_screen'] == {'PTG': 891}
    assert check.detail['zero_valued'] == {}
    assert check.violations == 0


@requires_corpus
def test_audited_population_is_liquidity_screened(report):
    """Only tickers that actually traded are audited."""
    check = _check(report, 'adjusted_price_degeneracy')

    assert check.detail['liquidity_screen'] == 'sessions_traded >= 250'
    for symbol, stats in check.detail['worst'].items():
        assert stats['sessions_traded'] >= 250, (symbol, stats)


@requires_corpus
def test_adjusted_degeneracy_is_measured_against_the_raw_series(report):
    """The test must be relative, not an absolute distinct-price count.

    Counting distinct adjusted prices alone flags illiquid tickers whose raw
    prices barely move either -- a property of the stock, not a data defect.
    """
    check = _check(report, 'adjusted_price_degeneracy')

    for symbol, stats in check.detail['worst'].items():
        assert stats['raw_distinct'] > 20, symbol
        assert 0 <= stats['retained'] <= 1.0, symbol


# --- tick-grid conformity ---------------------------------------------------

@requires_corpus
def test_tick_grid_conformity_finds_thirteen_off_grid_closes(report):
    """A third defect class, independent of the band swap and the OHLC
    invariants, and found by wiring the exchange model to the corpus.

    A price off the grid could not have traded: the matching engine would never
    have accepted the order that produced it.
    """
    check = _check(report, 'tick_grid_conformity')

    # The check now covers every Vietnamese venue, not HSX alone.
    assert check.total == 3_709_950
    assert check.violations == 13
    assert set(check.detail['offenders']) == {
        'DAG', 'C47', 'SVI', 'NLG', 'CCI', 'MCP'}


@requires_corpus
def test_hnx_is_genuinely_vacuous_but_upcom_is_not(report):
    """The old HSX-only scope was argued from "the flat-tick venues would be
    vacuous". Half right: HNX is spotless, UPCoM is not.
    """
    by_venue = _check(report, 'tick_grid_conformity').detail['by_venue']

    assert by_venue['HNX']['rows'] == 904_819
    assert by_venue['HNX']['off_grid'] == 0
    assert by_venue['UPCOM']['off_grid'] == 15_504


@requires_corpus
def test_every_off_grid_upcom_close_is_a_mislabelled_hose_price(report):
    """The load-bearing result: those 15,504 rows are not bad prices.

    All 15,504 lie exactly on HOSE's price-banded grid -- no counterexample --
    so they are HOSE prices carrying a UPCoM label. `quote_ticker.exchangeid`
    is a CURRENT attribute, and these are HOSE-delisted names that later moved
    to UPCoM.

    This corroborates, by tick grids, what the rulebook research concluded by
    fitting price bands. Two unrelated methods, the same tickers.
    """
    check = _check(report, 'tick_grid_conformity')
    by_venue = check.detail['by_venue']

    assert by_venue['UPCOM']['misattributed'] == 15_504
    assert by_venue['UPCOM']['off_grid'] == by_venue['UPCOM']['misattributed']
    assert check.detail['venue_misattribution'] == 15_504

    # The band-fitting research named these; the tick grid finds them again.
    assert {'LCM', 'PXI', 'ATG', 'PXS', 'CLG', 'PXT', 'TS4', 'RIC'} <= set(
        check.detail['mislabelled_symbols'])


@requires_corpus
def test_the_thirteen_real_violations_fit_no_venue_grid(report):
    """A genuine defect is one no Vietnamese venue's grid explains.

    If any of the 13 fitted another venue exactly it would be a mislabel, not
    a bad price, and would have been counted in the other bucket.
    """
    check = _check(report, 'tick_grid_conformity')

    assert check.detail['by_venue']['HSX']['misattributed'] == 0
    assert sum(check.detail['offenders'].values()) == check.violations == 13


@requires_corpus
def test_off_grid_closes_all_predate_2016(report):
    check = _check(report, 'tick_grid_conformity')

    for days in check.detail['dates'].values():
        for day in days:
            assert day < '2016'
