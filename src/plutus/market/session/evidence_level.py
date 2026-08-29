"""Fill Evidence Level (FEL) -- grade a fill decision by how much data backs it.

Every :class:`~plutus.market.session.types.FillDecision` the engine produces
already records *what it rested on*: its ``outcome`` (FILL / NO_FILL /
INDETERMINATE), its ``evidence`` (traded-through / touched-at-limit /
auction-cross / modelled), and, for the indeterminate case, the ``missing``
fields that defeated it. FEL reads those fields back and places the decision on a
single ordered scale, from *the data settled it* down to *the policy supplied the
whole outcome*. It classifies; it does not decide -- the fill policies decide, and
FEL grades what they returned.

This turns the old binary "indeterminate?" flag into a **confidence profile**: an
order flow is a distribution over levels ("62% proven, 33% assumed, 5%
unevidenced"), which says far more than a single indeterminate rate and reads as
a quality profile of the fills rather than a defect count. INDETERMINATE is not a
failure here -- it is simply :attr:`~FillEvidenceLevel.UNEVIDENCED`, the bottom
rung, the fills that lean entirely on the policy because the data said nothing.

**The three levels** (higher = more data-backed):

* :attr:`~FillEvidenceLevel.PROVEN` -- the data settles the outcome. A fill the
  market traded strictly *through* (price-then-time priority proves it), a fill
  at a published auction cross (a rule-guaranteed execution), or a definite
  NO_FILL (the market never reached the limit). No fill-capability assumption.
* :attr:`~FillEvidenceLevel.ASSUMED` -- a fill the data does not settle, supplied
  by the policy under an assumption. Its :class:`AssumptionKind` says which:
  ``TOUCH`` (soft filling on a bare touch -- assumes favourable queue position)
  or ``MODELLED`` (a probabilistic, optimistic-sweep, or maker-from-tape fill --
  ``confidence`` carries the probability). The two are different *kinds* of
  assumption, not degrees, so they share one level.
* :attr:`~FillEvidenceLevel.UNEVIDENCED` -- INDETERMINATE. The data is silent
  (no traded price, no book, no volume); ``decision.missing`` names the cause.
  The policy would have to supply the entire outcome, so the engine abstains.

**Policies read as a floor on this scale.** ``hard`` acts only on PROVEN (returns
INDETERMINATE on a touch); ``soft`` acts down to ASSUMED/TOUCH; the probabilistic
and book-walk arms act on ASSUMED/MODELLED. A fill policy *is* a rule for the
lowest evidence level it is willing to act on -- which is a tidier definition
than three ad-hoc policies.

A 4-level refinement (splitting ASSUMED's TOUCH and MODELLED into their own tiers,
or splitting a volume-capped PROVEN fill into a SIZED tier) is a paper-side
choice; this module ships the defensible 3-level ordered spine plus the
categorical :class:`AssumptionKind`, and the finer split is derivable from
:func:`assumption_kind` and the decision's quantity without changing the scale.
"""
from __future__ import annotations

from enum import Enum, IntEnum

from plutus.market.session.types import (FillDecision, FillEvidence,
                                         FillOutcome)

__all__ = ["FillEvidenceLevel", "AssumptionKind", "fill_evidence_level",
           "assumption_kind"]


class FillEvidenceLevel(IntEnum):
    """How much data backs a fill decision. Ordered: higher is more evidenced.

    An :class:`~enum.IntEnum` so the ordering is usable directly --
    ``level >= FillEvidenceLevel.PROVEN`` is "the data settled it", and
    ``level <= FillEvidenceLevel.ASSUMED`` is "this rests on an assumption".
    """

    UNEVIDENCED = 0
    """INDETERMINATE -- the data is silent and the policy abstained."""
    ASSUMED = 1
    """A fill the data does not settle, supplied under an assumption
    (see :func:`assumption_kind`)."""
    PROVEN = 2
    """The data settles the outcome: traded-through, auction cross, or a
    definite no-fill."""


class AssumptionKind(Enum):
    """For an :attr:`~FillEvidenceLevel.ASSUMED` fill, which assumption it rests
    on. ``NONE`` for any decision that is not an assumed fill."""

    NONE = "none"
    TOUCH = "touch"
    """Filled on a bare touch (``soft`` on ``TOUCHED_AT_LIMIT``): assumes the
    order held favourable queue position, which the data cannot recover."""
    MODELLED = "modelled"
    """Filled by an explicit model -- probabilistic, optimistic sweep, or
    maker-from-tape (``MODELLED`` evidence). ``confidence`` carries the
    probability where the policy set one."""


def fill_evidence_level(decision: FillDecision) -> FillEvidenceLevel:
    """Place ``decision`` on the FEL scale from its recorded outcome/evidence.

    Pure and total: every :class:`FillDecision` maps to exactly one level.

    * INDETERMINATE -> :attr:`~FillEvidenceLevel.UNEVIDENCED`.
    * NO_FILL -> :attr:`~FillEvidenceLevel.PROVEN` (a definite miss is settled by
      the data just as a definite fill is; PROVEN means "the data decided",
      either direction).
    * FILL -> :attr:`~FillEvidenceLevel.PROVEN` when it traded through or cleared
      at a published auction cross, else :attr:`~FillEvidenceLevel.ASSUMED`.
    """
    if decision.outcome is FillOutcome.INDETERMINATE:
        return FillEvidenceLevel.UNEVIDENCED
    if decision.outcome is FillOutcome.NO_FILL:
        return FillEvidenceLevel.PROVEN
    # FILL: PROVEN only where the data settles it.
    if decision.evidence in (FillEvidence.TRADED_THROUGH,
                             FillEvidence.AUCTION_PRICE):
        return FillEvidenceLevel.PROVEN
    return FillEvidenceLevel.ASSUMED


def assumption_kind(decision: FillDecision) -> AssumptionKind:
    """Which assumption an :attr:`~FillEvidenceLevel.ASSUMED` fill rests on.

    ``NONE`` for anything that is not an assumed fill (a proven decision or an
    unevidenced abstention rests on no fill-capability assumption).
    """
    if fill_evidence_level(decision) is not FillEvidenceLevel.ASSUMED:
        return AssumptionKind.NONE
    if decision.evidence is FillEvidence.TOUCHED_AT_LIMIT:
        return AssumptionKind.TOUCH
    return AssumptionKind.MODELLED
