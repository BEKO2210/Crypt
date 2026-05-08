"""Scoring engine + weights validation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tao_scout.db.models import Subnet
from tao_scout.scoring.engine import (
    ScoreInput,
    build_rationale_skeleton,
    compute_weighted_total,
)
from tao_scout.scoring.weights import (
    DEFAULT_WEIGHTS,
    InvalidWeightsError,
    validate_weights,
)
from tao_scout.services import ScoreIn, append_score, list_scores


def test_default_weights_sum_to_one() -> None:
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


def test_weights_must_sum_to_one() -> None:
    bad = dict(DEFAULT_WEIGHTS)
    bad["developer_fit"] = 0.5
    with pytest.raises(InvalidWeightsError):
        validate_weights(bad)


def test_weights_missing_axis() -> None:
    bad = {k: v for k, v in DEFAULT_WEIGHTS.items() if k != "developer_fit"}
    with pytest.raises(InvalidWeightsError):
        validate_weights(bad)


def test_weights_extra_axis() -> None:
    bad = dict(DEFAULT_WEIGHTS)
    bad["mystery_axis"] = 0.0
    with pytest.raises(InvalidWeightsError):
        validate_weights(bad)


def test_weights_negative_rejected() -> None:
    bad = dict(DEFAULT_WEIGHTS)
    bad["developer_fit"] = -0.1
    bad["repo_quality"] = 0.20  # keep total = 1.0 to isolate the negative-check
    with pytest.raises(InvalidWeightsError):
        validate_weights(bad)


def test_compute_weighted_total_all_tens() -> None:
    score = ScoreInput(
        developer_fit=10,
        hardware_fit=10,
        competition_level=10,
        repo_quality=10,
        reward_potential=10,
        ecosystem_momentum=10,
    )
    r = compute_weighted_total(score)
    assert r.weighted_total == pytest.approx(10.0)


def test_compute_weighted_total_all_zeros() -> None:
    score = ScoreInput(
        developer_fit=0,
        hardware_fit=0,
        competition_level=0,
        repo_quality=0,
        reward_potential=0,
        ecosystem_momentum=0,
    )
    r = compute_weighted_total(score)
    assert r.weighted_total == pytest.approx(0.0)


def test_compute_with_custom_weights() -> None:
    weights = {
        "developer_fit": 1.0,
        "hardware_fit": 0.0,
        "competition_level": 0.0,
        "repo_quality": 0.0,
        "reward_potential": 0.0,
        "ecosystem_momentum": 0.0,
    }
    score = ScoreInput(
        developer_fit=7,
        hardware_fit=0,
        competition_level=0,
        repo_quality=0,
        reward_potential=0,
        ecosystem_momentum=0,
    )
    r = compute_weighted_total(score, weights)
    assert r.weighted_total == pytest.approx(7.0)


def test_score_input_rejects_out_of_range() -> None:
    with pytest.raises(Exception):
        ScoreInput(
            developer_fit=11,
            hardware_fit=0,
            competition_level=0,
            repo_quality=0,
            reward_potential=0,
            ecosystem_momentum=0,
        )


def test_rationale_skeleton_mentions_dominant_axis() -> None:
    score = ScoreInput(
        developer_fit=10,
        hardware_fit=2,
        competition_level=2,
        repo_quality=2,
        reward_potential=2,
        ecosystem_momentum=2,
    )
    text = build_rationale_skeleton(score)
    assert "Developer Fit" in text
    assert "10/10" in text


@pytest.mark.asyncio
async def test_score_history_is_append_only(db_session) -> None:
    subnet = Subnet(netuid=42, last_refreshed_at=datetime.now(UTC))
    db_session.add(subnet)
    await db_session.commit()

    for i in range(3):
        await append_score(
            db_session,
            ScoreIn(
                netuid=42,
                developer_fit=i,
                hardware_fit=i,
                competition_level=i,
                repo_quality=i,
                reward_potential=i,
                ecosystem_momentum=i,
                rationale=f"round {i}",
            ),
        )

    scores = await list_scores(db_session, 42)
    assert len(scores) == 3
    # Most recent first
    assert scores[0].developer_fit == 2
    assert scores[-1].developer_fit == 0
    # Each row stores its own weights snapshot
    for s in scores:
        assert s.weights_snapshot is not None
        assert "developer_fit" in s.weights_snapshot
