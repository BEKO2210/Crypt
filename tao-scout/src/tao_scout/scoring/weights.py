"""Default scoring weights and validation.

Weights are a mapping ``axis_key -> float``. They MUST cover every axis in
:data:`tao_scout.scoring.axes.AXIS_KEYS` and sum to 1.0 (+/- 0.001).
"""

from __future__ import annotations

from typing import Final, Mapping

from tao_scout.scoring.axes import AXIS_KEYS

DEFAULT_WEIGHTS: Final[dict[str, float]] = {
    "developer_fit": 0.20,
    "hardware_fit": 0.20,
    "competition_level": 0.20,
    "repo_quality": 0.10,
    "reward_potential": 0.20,
    "ecosystem_momentum": 0.10,
}

_TOLERANCE: Final[float] = 1e-3


class InvalidWeightsError(ValueError):
    """Raised when a weights dict is missing axes, has extras, or doesn't sum to 1."""


def validate_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """Return a normalized copy after validating coverage and sum."""
    missing = set(AXIS_KEYS) - set(weights)
    extra = set(weights) - set(AXIS_KEYS)
    if missing:
        raise InvalidWeightsError(f"Missing axes: {sorted(missing)}")
    if extra:
        raise InvalidWeightsError(f"Unknown axes: {sorted(extra)}")
    for k, v in weights.items():
        if not isinstance(v, (int, float)):
            raise InvalidWeightsError(f"Weight for {k!r} must be numeric, got {type(v).__name__}")
        if v < 0:
            raise InvalidWeightsError(f"Weight for {k!r} must be non-negative")
    total = float(sum(weights.values()))
    if abs(total - 1.0) > _TOLERANCE:
        raise InvalidWeightsError(f"Weights must sum to 1.0 (got {total:.6f})")
    return {k: float(weights[k]) for k in AXIS_KEYS}


__all__ = ["DEFAULT_WEIGHTS", "InvalidWeightsError", "validate_weights"]
