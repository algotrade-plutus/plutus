"""Outcome types, and the JSON contract they must satisfy."""

import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

import pytest

from plutus.market.verdicts import (
    Admissibility, AdmissionRule, PositionEvent, PositionEventKind,
    SettlementSource, Verdict, Viability,
)


def _reject_non_finite(token):
    raise AssertionError(f'non-finite token {token!r} in verdict JSON')


def test_verdict_has_three_states_not_two():
    assert {v.value for v in Verdict} == {'admitted', 'rejected', 'indeterminate'}


def test_admission_rules_cover_the_six_checks():
    assert {r.value for r in AdmissionRule} == {
        'tick_grid', 'round_lot', 'band_limit', 'band_lock',
        'foreign_room', 'session_semantics',
    }


def test_band_limit_and_band_lock_are_distinct_rules():
    """One is stateless; the other needs lock provenance."""
    assert AdmissionRule.BAND_LIMIT is not AdmissionRule.BAND_LOCK


def test_admissibility_round_trips_through_strict_json():
    a = Admissibility(
        verdict=Verdict.REJECTED, rule=AdmissionRule.TICK_GRID,
        binding_constraint=Decimal('0.05'),
        ts=datetime(2022, 3, 29, 10, 15, 30),
    )
    decoded = json.loads(json.dumps(a.to_dict()),
                         parse_constant=_reject_non_finite)
    assert decoded['verdict'] == 'rejected'
    assert decoded['rule'] == 'tick_grid'
    assert decoded['ts'] == '2022-03-29T10:15:30'
    assert decoded['binding_constraint'] == 0.05


def test_bare_json_safe_is_insufficient_which_is_why_to_dict_exists():
    from plutus.evaluation.contract import json_safe

    a = Admissibility(verdict=Verdict.ADMITTED, rule=None,
                      binding_constraint=None, ts=datetime(2022, 3, 29))
    with pytest.raises(TypeError):
        json.dumps(json_safe(asdict(a)))


def test_indeterminate_is_not_admitted():
    a = Admissibility(verdict=Verdict.INDETERMINATE,
                      rule=AdmissionRule.BAND_LOCK, binding_constraint=None,
                      ts=datetime(2022, 3, 29))
    assert a.admitted is False


def test_position_event_records_its_settlement_provenance():
    e = PositionEvent(
        kind=PositionEventKind.MARGIN_CALL, ts=datetime(2022, 5, 9),
        settlement=Decimal('1300.0'),
        settlement_source=SettlementSource.CLOSE_PROXY,
        equity=Decimal('10000'), notional=Decimal('130000000'),
        margin_ratio=Decimal('0.15'),
    )
    d = e.to_dict()
    assert d['kind'] == 'margin_call'
    assert d['settlement_source'] == 'close_proxy'
    assert json.loads(json.dumps(d))['ts'] == '2022-05-09T00:00:00'


def test_viability_round_trips_with_nested_events():
    v = Viability(
        survived=False,
        events=(PositionEvent(
            kind=PositionEventKind.MARGIN_CALL, ts=datetime(2022, 5, 9),
            settlement=Decimal('1300.0'),
            settlement_source=SettlementSource.CLOSE_PROXY,
            equity=Decimal('1'), notional=Decimal('2'),
            margin_ratio=Decimal('0.5'),
        ),),
        days_evaluated=100, days_indeterminate=3,
    )
    decoded = json.loads(json.dumps(v.to_dict()),
                         parse_constant=_reject_non_finite)
    assert decoded['survived'] is False
    assert len(decoded['events']) == 1
    assert decoded['days_indeterminate'] == 3


def test_first_returns_none_when_no_such_event():
    v = Viability(survived=True, events=(), days_evaluated=1,
                  days_indeterminate=0)
    assert v.first(PositionEventKind.MARGIN_CALL) is None
