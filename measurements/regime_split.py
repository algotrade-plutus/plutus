"""The KRX cutover, on one book: pre-KRX IM+VM vs post-KRX scenario grid.

A dated-rule-editions demonstration, and the derivatives half of the paper's
lead claim. Each front-month VN30F entry in the corpus -- its size and price --
is margined under the rules in force in **each** regime:

* **pre-KRX (<= 2025-05-04):** ``MR = IM + VM``, the initial margin at the
  position's own **dated** VSD rate (10 -> 13 -> 17%), variation margin
  loss-only. At entry ``VM = 0``, so the base requirement is ``IM``.
* **post-KRX (2025-05-05+):** ``MR`` is the scenario grid of QD 26 Phu luc 2,
  ``Max(Rm + Sm + Dm, MM)``, with SSI's published parameter mirror (risk 17%,
  basis 0.87%; ``broker_profile.py``) and TCBS's minimum (5,000d per contract).

The engine **refuses** to apply the post-KRX grid to a pre-KRX date -- the
parameters are not yet effective -- which is the effective-dating machinery
working, and the reason the two regimes must each be resolved under the rules in
force rather than by a naive counterfactual. The **book is held fixed** (size and
price) across the two, so the difference is the rule-edition's alone, not the
market's.

Measured on the corpus front-month series (381 entries): the post-KRX grid
requires about **30% more** than the pre-KRX IM for the same flat book -- the
KRX cutover materially tightened the requirement, holding the position fixed.
This is not the same statistic as the margin-call *incidence*
(``margin_incidence_account``); it is the requirement's regime dependence.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional

from measurements.margin_incidence_account import VN30F_MULTIPLIER, _windows
from plutus.market.margin import vsd_initial_margin
from plutus.market.session.broker_profile import (UnderlyingParameters,
                                                  VsdcParameterSet)
from plutus.market.session.overnight import scenario_grid_requirement

__all__ = ['measure_regime_split']

#: SSI's published post-KRX VN30 parameter mirror (the same values
#: ``broker_profile.py`` records), and TCBS's minimum margin per contract. The
#: ``effective_from`` is the KRX cutover; the engine refuses these parameters at
#: any earlier date, which is what makes the comparison honest rather than a
#: counterfactual applying 2025 rules to a 2022 close.
_SSI_VN30 = UnderlyingParameters(
    underlying='VN30', risk_margin_rate=Decimal('0.17'),
    spread_margin_rate=Decimal('0.0087'), price_scan_range=Decimal('0.85'),
    scale_factor=Decimal('1'))
_POST_KRX_PARAMS = VsdcParameterSet(
    effective_from=date(2025, 5, 5), underlyings=(_SSI_VN30,),
    source='SSI post-KRX mirror (broker_profile)')
_POST_KRX_MF = Decimal('5000')
#: A date at which the post-KRX parameters are in force. The book's own price is
#: used (a single leg has no calendar basis, so the underlying close equals the
#: position price for this purpose); only the rule edition varies.
_POST_KRX_AS_OF = date(2026, 2, 10)


@dataclass(frozen=True)
class _Held:
    net_quantity: int
    multiplier: Decimal = VN30F_MULTIPLIER
    expiry: Optional[date] = None


def measure_regime_split(data_root: str, *, holding_days: int = 10) -> Dict[str, Any]:
    """Margin requirement for each corpus front-month book under both editions.

    Returns the mean requirement under each regime and their ratio, over every
    front-month entry. ``holding_days`` only selects which entries are walked
    (the same population the incidence measurement uses); the requirement is read
    at entry, where the regimes differ by rule and not by an accumulated loss.
    """
    pre_total = post_total = Decimal('0')
    ratios: list = []
    n = refused = 0
    for ticker, window in _windows(data_root, holding_days):
        entry_day, entry_price = window[0]
        pre = vsd_initial_margin(entry_day) * VN30F_MULTIPLIER * entry_price
        grid = scenario_grid_requirement(
            as_of=_POST_KRX_AS_OF, account_id='regime-split',
            positions={ticker: _Held(1)}, parameters=_POST_KRX_PARAMS,
            underlying_closes={'VN30': entry_price},
            minimum_margin_factor=_POST_KRX_MF)
        if not grid.is_determinate or grid.amount is None:
            refused += 1
            continue
        pre_total += pre
        post_total += grid.amount
        ratios.append(grid.amount / pre)
        n += 1
    mean_ratio = (sum(ratios) / len(ratios)) if ratios else Decimal('0')
    return {
        'positions': n,
        'refused': refused,
        'pre_krx_mean_mr': str((pre_total / n).quantize(Decimal('1'))) if n else None,
        'post_krx_mean_mr': str((post_total / n).quantize(Decimal('1'))) if n else None,
        'mean_ratio': str(mean_ratio.quantize(Decimal('0.001'))),
        'note': ('same book, each regime resolved under the rules in force; the '
                 'engine refuses the post-KRX grid at a pre-KRX date (parameters '
                 'not yet effective), so the difference is the rule edition, not '
                 'the market'),
    }
