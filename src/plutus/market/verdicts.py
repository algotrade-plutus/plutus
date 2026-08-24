"""What an exchange reports back, and how it serialises.

Each outcome carries a :meth:`to_dict` that unwraps enums and stringifies
temporals before handing off to
:func:`plutus.evaluation.contract.json_safe`. That function is deliberately
untouched -- 169 tests pin it -- and it passes bare enums and datetimes through
unchanged, so ``json.dumps`` would raise without this step.

The unwrapping is by ``Enum``, not by the specific enums defined here, because
``plutus.core.order.Side`` and ``OrderType`` predate this package and are not
``str``-mixed.
"""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional, Tuple, Union

from plutus.evaluation.contract import json_safe

__all__ = [
    'Admissibility', 'AdmissionRule', 'PositionEvent', 'PositionEventKind',
    'SettlementSource', 'Verdict', 'Viability',
]


class Verdict(str, Enum):
    """Three states, not two.

    ``INDETERMINATE`` is what keeps the model honest: when the data needed to
    judge a rule is absent, saying so is required and guessing is forbidden.
    """

    ADMITTED = 'admitted'
    REJECTED = 'rejected'
    INDETERMINATE = 'indeterminate'


class AdmissionRule(str, Enum):
    """The rule that bound. This enum IS the rejected-order log."""

    TICK_GRID = 'tick_grid'
    ROUND_LOT = 'round_lot'
    BAND_LIMIT = 'band_limit'              # stateless: price outside the band
    BAND_LOCK = 'band_lock'                # fillability: marketable into a lock
    FOREIGN_ROOM = 'foreign_room'
    SESSION_SEMANTICS = 'session_semantics'


class SettlementSource(str, Enum):
    """Which settlement tier produced the price behind an event."""

    PUBLISHED = 'published'      # a real quote_settlementprice row
    TWAP_30M = 'twap_30m'        # time-weighted matched price, 14:15-14:45
    CLOSE_PROXY = 'close_proxy'  # quote_close -- the only tier on Parquet


class PositionEventKind(str, Enum):
    MARGIN_CALL = 'margin_call'
    FORCED_LIQUIDATION = 'forced_liquidation'
    EXIT_BLOCKED = 'exit_blocked'
    POSITION_LIMIT_EXCEEDED = 'position_limit_exceeded'
    EXPIRY_SETTLEMENT = 'expiry_settlement'


def _plain(value: Any) -> Any:
    """Recursively reduce enums and temporals to JSON-native forms."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _serialise(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Unwrap enums and temporals, then defer to the project's JSON guard."""
    return json_safe(_plain(payload))


@dataclass(frozen=True)
class Admissibility:
    """Whether an exchange would accept one order at one instant."""

    verdict: Verdict
    rule: Optional[AdmissionRule]
    binding_constraint: Optional[Union[Decimal, int]]
    ts: datetime
    regime_tag: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def admitted(self) -> bool:
        """Convenience for callers that only care about the happy path.

        ``INDETERMINATE`` is not admitted: absence of evidence is not evidence
        of admissibility.
        """
        return self.verdict is Verdict.ADMITTED

    def to_dict(self) -> Dict[str, Any]:
        return _serialise(asdict(self))


@dataclass(frozen=True)
class PositionEvent:
    """Something the exchange would do to an open position on a given day."""

    kind: PositionEventKind
    ts: datetime
    settlement: Optional[Decimal]
    settlement_source: SettlementSource
    equity: Optional[Decimal]
    notional: Optional[Decimal]
    margin_ratio: Optional[Decimal]
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _serialise(asdict(self))


@dataclass(frozen=True)
class Viability:
    """Whether a position survived a price path, and what happened along it."""

    survived: bool
    events: Tuple[PositionEvent, ...]
    days_evaluated: int
    days_indeterminate: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            'survived': self.survived,
            'events': [e.to_dict() for e in self.events],
            'days_evaluated': self.days_evaluated,
            'days_indeterminate': self.days_indeterminate,
        }

    def first(self, kind: PositionEventKind) -> Optional[PositionEvent]:
        """The earliest event of a kind, or None."""
        for event in self.events:
            if event.kind is kind:
                return event
        return None
