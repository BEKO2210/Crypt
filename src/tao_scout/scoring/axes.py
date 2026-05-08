"""The 6 scoring axes.

Each axis is integer 0-10. ``competition_level`` is INVERTED: 10 = low
competition (good), 0 = saturated (bad). Inversion is documented here and
referenced in tooltips on the scoring form.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class AxisDefinition:
    key: str
    label: str
    description: str
    zero_means: str
    ten_means: str
    inverted: bool = False
    icm_stage: str = ""


AXES: Final[tuple[AxisDefinition, ...]] = (
    AxisDefinition(
        key="developer_fit",
        label="Developer Fit",
        description="Match between the subnet's task and your declared skill set.",
        zero_means="Alien stack: no relevant skill or experience.",
        ten_means="Native fit: subnet's stack matches your skill profile.",
        icm_stage="03-research",
    ),
    AxisDefinition(
        key="hardware_fit",
        label="Hardware Fit",
        description="Can you run a competitive miner on your declared hardware?",
        zero_means="Requires a multi-GPU cluster you do not have.",
        ten_means="Runs comfortably on your declared hardware.",
        icm_stage="02-repo",
    ),
    AxisDefinition(
        key="competition_level",
        label="Competition (inverted)",
        description="Saturation of validator/miner slots and emission concentration. INVERTED.",
        zero_means="Fully saturated, top-tier incumbents capture all emission.",
        ten_means="Wide open: slots free, emission spread, room for new entrants.",
        inverted=True,
        icm_stage="01-chain",
    ),
    AxisDefinition(
        key="repo_quality",
        label="Repo Quality",
        description="Quality of the reference miner/validator codebase.",
        zero_means="No repo or abandoned.",
        ten_means="Active, documented, tested, recent commits.",
        icm_stage="02-repo",
    ),
    AxisDefinition(
        key="reward_potential",
        label="Reward Potential",
        description="Emission share x realistic capture probability for a new entrant.",
        zero_means="Negligible: even peak performance pays little.",
        ten_means="High and accessible to a new entrant.",
        icm_stage="01-chain",
    ),
    AxisDefinition(
        key="ecosystem_momentum",
        label="Ecosystem Momentum",
        description="Subnet growth signals: commit cadence, new joins, registrations, community.",
        zero_means="Stagnant or shrinking.",
        ten_means="Clear upward trajectory.",
        icm_stage="03-research",
    ),
)

AXIS_KEYS: Final[tuple[str, ...]] = tuple(a.key for a in AXES)


def get_axis(key: str) -> AxisDefinition:
    for a in AXES:
        if a.key == key:
            return a
    raise KeyError(f"Unknown scoring axis: {key!r}")


__all__ = ["AXES", "AXIS_KEYS", "AxisDefinition", "get_axis"]
