"""Derivatives headline: how often the exchange would call a front-month long.

Pinned as integers. The entry policy is part of the result: long one
front-month contract at each session close, held H sessions or to expiry.
"""

from decimal import Decimal

import pytest

from measurements.margin_incidence import measure_margin_incidence

from .conftest import requires_corpus


@requires_corpus
@pytest.mark.parametrize(
    'holding_days, entries, called',
    [(5, 381, 29), (10, 381, 48), (20, 381, 56)],
)
def test_incidence_reproduces_exactly(corpus_root, holding_days, entries, called):
    r = measure_margin_incidence(str(corpus_root), holding_days=holding_days)
    assert r.entries == entries
    assert r.called == called


@requires_corpus
def test_the_published_rate_gives_a_non_degenerate_headline(corpus_root):
    """12.60% at a 10-session hold: neither saturated nor empty."""
    r = measure_margin_incidence(str(corpus_root), holding_days=10)
    assert r.call_rate == pytest.approx(Decimal('0.126'), abs=Decimal('0.001'))
    assert r.initial_rate == Decimal('0.22')


@requires_corpus
def test_longer_holds_are_at_least_as_risky(corpus_root):
    rates = [measure_margin_incidence(str(corpus_root), holding_days=h).call_rate
             for h in (5, 10, 20)]
    assert rates == sorted(rates)


@requires_corpus
def test_call_rate_is_monotone_non_increasing_in_the_initial_rate(corpus_root):
    """Posting more collateral cannot make a call more likely."""
    observed = [
        measure_margin_incidence(str(corpus_root), holding_days=10,
                                 initial_rate=Decimal(r)).call_rate
        for r in ('0.150', '0.175', '0.200', '0.225', '0.250', '0.300')
    ]
    assert observed == sorted(observed, reverse=True)


@requires_corpus
def test_liquidation_never_exceeds_calls(corpus_root):
    r = measure_margin_incidence(str(corpus_root), holding_days=20)
    assert r.liquidated <= r.called


@requires_corpus
def test_result_is_json_serialisable_and_states_its_entry_policy(corpus_root):
    import json

    r = measure_margin_incidence(str(corpus_root), holding_days=10)
    decoded = json.loads(json.dumps(r.to_dict()))
    assert decoded['holding_days'] == 10
    assert 'front-month' in decoded['entry_policy']
