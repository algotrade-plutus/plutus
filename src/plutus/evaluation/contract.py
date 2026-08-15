"""The results contract for performance metrics.

Every metric in :mod:`plutus.evaluation` obeys two rules, defined here so that
they are stated once rather than reimplemented per function.

**Undefined is ``None``, never a number and never an infinity.**

A metric is undefined when its inputs do not determine it: an empty return
series, a single observation where a deviation is needed, or a zero
denominator. Previous behaviour disagreed with itself — on a constant
+0.5%/day series the library reported ``sharpe=0``, ``sortino=Infinity`` and
``calmar=Infinity``, three contradictory verdicts on one input — and ``0`` in
particular is indistinguishable from a strategy that really did trade and
break even.

``Infinity`` also cannot survive the round trip through a results file:
non-finite floats are outside JSON (RFC 8259), so ``json.dumps`` emits a bare
``Infinity`` token that any strict parser rejects. Metrics that feed a
published results artifact must not be able to produce one.

**Impossible is an exception, never a plausible number.**

A return series whose cumulative value falls to or below zero describes an
account that has lost everything. Growth rates over such a series are not
defined. The prior implementation failed at this inconsistently, and the shape
of the failure depended on how many observations there were: when the
annualization factor divided evenly by the series length the exponent was a
whole number and ``cagr`` returned a clean, plausible ``-100%``; otherwise the
same input raised a raw ``decimal.InvalidOperation`` from inside the decimal
module. Both are wrong, and the silent one is the more dangerous.
"""

from decimal import Decimal
from typing import Any, List, Optional

__all__ = [
    "UndefinedMetricError",
    "TotalLossError",
    "is_undefined",
    "json_safe",
]


class UndefinedMetricError(ValueError):
    """A metric was asked for on inputs that do not define it.

    Raised only where returning ``None`` would hide a genuine domain error.
    For ordinarily-undefined cases (empty series, zero variance) metrics
    return ``None`` instead.
    """


class TotalLossError(UndefinedMetricError):
    """The cumulative return path reached or passed total loss.

    Growth-rate metrics (CAGR, and Calmar which is built on it) have no value
    for a series whose compounded equity is zero or negative.
    """

    def __init__(self, cumulative: Decimal, metric: str):
        self.cumulative = cumulative
        self.metric = metric
        super().__init__(
            f"{metric} is undefined: the return series compounds to "
            f"{cumulative}, i.e. total loss of capital. A growth rate over a "
            f"non-positive final equity has no real value. Inspect the return "
            f"series for values at or below -100%."
        )


def is_undefined(value: Any) -> bool:
    """Report whether `value` is this library's 'undefined metric' marker."""
    return value is None


def json_safe(value: Any) -> Any:
    """Recursively convert metric output into strictly JSON-serialisable form.

    ``Decimal`` becomes ``float``, ``None`` is preserved as JSON ``null``, and
    any non-finite float is rejected rather than silently written out as an
    ``Infinity`` token that a strict reader cannot parse.

    Args:
        value: A metric value, or a container of them.

    Returns:
        The same structure with Decimals converted to floats.

    Raises:
        ValueError: If a non-finite float is encountered.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(
                f"Non-finite metric value {value!r} cannot be serialised to "
                f"JSON (RFC 8259 has no infinity or NaN). This indicates a "
                f"metric bypassed the undefined-is-None contract."
            )
        return float(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(
                f"Non-finite metric value {value!r} cannot be serialised to JSON."
            )
        return value
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def guard_cumulative(cumulative: Decimal, metric: str) -> None:
    """Raise :class:`TotalLossError` if `cumulative` is non-positive."""
    if cumulative <= Decimal("0"):
        raise TotalLossError(cumulative, metric)


def require_observations(returns: List[Decimal], minimum: int) -> bool:
    """Return True when `returns` holds at least `minimum` observations."""
    return len(returns) >= minimum


def undefined() -> Optional[Decimal]:
    """The undefined-metric value. Exists so the intent reads at call sites."""
    return None
