"""Weighted-aggregation engine and explainability helper."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator

from tao_scout.scoring.axes import AXIS_KEYS, get_axis
from tao_scout.scoring.weights import DEFAULT_WEIGHTS, validate_weights


class ScoreInput(BaseModel):
    """User-supplied axis scores (each 0-10 integer)."""

    developer_fit: int = Field(ge=0, le=10)
    hardware_fit: int = Field(ge=0, le=10)
    competition_level: int = Field(ge=0, le=10)
    repo_quality: int = Field(ge=0, le=10)
    reward_potential: int = Field(ge=0, le=10)
    ecosystem_momentum: int = Field(ge=0, le=10)

    @field_validator("*")
    @classmethod
    def _ensure_int(cls, v: int) -> int:
        if isinstance(v, bool):
            raise ValueError("axis scores must be int, not bool")
        return int(v)

    def as_dict(self) -> dict[str, int]:
        return self.model_dump()


@dataclass(frozen=True)
class AxisContribution:
    key: str
    score: int
    weight: float
    contribution: float


@dataclass(frozen=True)
class ScoringResult:
    weighted_total: float
    contributions: tuple[AxisContribution, ...]

    def top_contribution(self) -> AxisContribution:
        return max(self.contributions, key=lambda c: c.contribution)


def compute_weighted_total(
    scores: ScoreInput | Mapping[str, int],
    weights: Mapping[str, float] | None = None,
) -> ScoringResult:
    """Compute weighted total + per-axis contributions.

    The result range is 0.0..10.0 because axis scores are already 0..10 and
    weights sum to 1.0.
    """
    if isinstance(scores, ScoreInput):
        score_map: dict[str, int] = scores.as_dict()
    else:
        score_map = dict(scores)
        ScoreInput(**score_map)  # validate range

    norm_weights = validate_weights(weights if weights is not None else DEFAULT_WEIGHTS)

    contributions: list[AxisContribution] = []
    total = 0.0
    for key in AXIS_KEYS:
        raw = score_map[key]
        w = norm_weights[key]
        contrib = raw * w
        contributions.append(AxisContribution(key=key, score=raw, weight=w, contribution=contrib))
        total += contrib

    return ScoringResult(
        weighted_total=round(total, 4), contributions=tuple(contributions)
    )


def build_rationale_skeleton(
    scores: ScoreInput | Mapping[str, int],
    weights: Mapping[str, float] | None = None,
) -> str:
    """Return a human-editable rationale stub that surfaces the dominant axis."""
    result = compute_weighted_total(scores, weights)
    top = result.top_contribution()
    axis = get_axis(top.key)
    lines = [
        f"Score {result.weighted_total:.2f} / 10.",
        f"Dominant axis: {axis.label} (score {top.score}/10, weight {top.weight:.2f}, "
        f"contribution {top.contribution:.2f}).",
        "",
        "Per-axis breakdown:",
    ]
    for c in result.contributions:
        a = get_axis(c.key)
        lines.append(
            f"  - {a.label}: {c.score}/10 x {c.weight:.2f} = {c.contribution:.2f}"
        )
    return "\n".join(lines)


__all__ = [
    "AxisContribution",
    "ScoreInput",
    "ScoringResult",
    "build_rationale_skeleton",
    "compute_weighted_total",
]
