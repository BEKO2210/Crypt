"""Service layer: notes, scoring, rank, settings, ICM workspace scaffold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from tao_scout.db.models import Subnet, UserSettings
from tao_scout.scoring.weights import DEFAULT_WEIGHTS
from tao_scout.services import (
    ICM_STAGES,
    NoteIn,
    ScoreIn,
    SettingsIn,
    append_score,
    build_continue_rail,
    capture_snapshot,
    ensure_workspace,
    get_note,
    get_or_create_settings,
    list_missing_stages,
    list_snapshots,
    rank,
    update_settings,
    upsert_note,
)


@pytest.mark.asyncio
async def test_upsert_note_idempotent(db_session) -> None:
    db_session.add(Subnet(netuid=3, last_refreshed_at=datetime.now(UTC)))
    await db_session.commit()

    payload = NoteIn(netuid=3, task_type="text-gen", repo_url="https://example.com",
                     tags=["llm", "infer"])
    n1 = await upsert_note(db_session, payload)
    n2 = await upsert_note(db_session, NoteIn(netuid=3, task_type="audio"))
    assert n1.id == n2.id  # one row per netuid
    note = await get_note(db_session, 3)
    assert note is not None
    assert note.task_type == "audio"


@pytest.mark.asyncio
async def test_settings_defaults_then_update(db_session) -> None:
    s = await get_or_create_settings(db_session)
    assert s.weights == DEFAULT_WEIGHTS

    new_weights = {
        "developer_fit": 0.25,
        "hardware_fit": 0.25,
        "competition_level": 0.20,
        "repo_quality": 0.10,
        "reward_potential": 0.10,
        "ecosystem_momentum": 0.10,
    }
    s2 = await update_settings(
        db_session,
        SettingsIn(
            skill_profile="python, pytorch",
            skill_tags=["llm", "diffusion"],
            hardware_profile="single-gpu-24gb",
            weights=new_weights,
        ),
    )
    assert s2.skill_profile == "python, pytorch"
    assert s2.weights == new_weights


@pytest.mark.asyncio
async def test_rank_orders_by_total(db_session) -> None:
    for netuid, scores in [
        (1, dict(developer_fit=8, hardware_fit=8, competition_level=8,
                 repo_quality=8, reward_potential=8, ecosystem_momentum=8)),
        (2, dict(developer_fit=2, hardware_fit=2, competition_level=2,
                 repo_quality=2, reward_potential=2, ecosystem_momentum=2)),
        (3, dict(developer_fit=5, hardware_fit=5, competition_level=5,
                 repo_quality=5, reward_potential=5, ecosystem_momentum=5)),
    ]:
        db_session.add(Subnet(netuid=netuid, last_refreshed_at=datetime.now(UTC)))
        await db_session.commit()
        await append_score(db_session, ScoreIn(netuid=netuid, **scores))

    rows = await rank(db_session, by="total")
    assert [r.subnet.netuid for r in rows] == [1, 3, 2]


@pytest.mark.asyncio
async def test_continue_rail_picks_up_stale_and_missing_workspaces(
    db_session, tmp_path
) -> None:
    db_session.add(
        Subnet(
            netuid=99,
            name="never-refreshed",
            last_refreshed_at=datetime.now(UTC) - timedelta(hours=24),
        )
    )
    await db_session.commit()
    rail = await build_continue_rail(
        db_session, workspace_root=tmp_path, stale_after_seconds=3600
    )
    assert any(s.netuid == 99 for s in rail.stale_data)
    # No workspace exists → all stages reported missing
    missing = [m for nu, m in rail.unfinished_workspaces if nu == 99]
    assert missing and missing[0] == list(ICM_STAGES)


def test_ensure_workspace_creates_stages(tmp_path: Path) -> None:
    base = ensure_workspace(tmp_path, 17, "myname")
    for stage in ICM_STAGES:
        ctx = base / stage / "CONTEXT.adoc"
        assert ctx.exists()
        body = ctx.read_text(encoding="utf-8")
        assert "= " in body  # AsciiDoc title
    assert list_missing_stages(tmp_path, 17) == []


@pytest.mark.asyncio
async def test_append_score_does_not_create_settings_row(db_session) -> None:
    """Scoring must not have settings-creation as a write side-effect."""
    db_session.add(Subnet(netuid=55, last_refreshed_at=datetime.now(UTC)))
    await db_session.commit()
    await append_score(
        db_session,
        ScoreIn(
            netuid=55,
            developer_fit=5, hardware_fit=5, competition_level=5,
            repo_quality=5, reward_potential=5, ecosystem_momentum=5,
        ),
    )
    rows = (await db_session.execute(select(UserSettings))).scalars().all()
    assert list(rows) == []


@pytest.mark.asyncio
async def test_capture_snapshot_round_trips_state(db_session) -> None:
    db_session.add(
        Subnet(
            netuid=12,
            name="snap-target",
            emission=0.05,
            last_refreshed_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    await upsert_note(db_session, NoteIn(netuid=12, task_type="text-gen", tags=["llm"]))
    await append_score(
        db_session,
        ScoreIn(
            netuid=12,
            developer_fit=7, hardware_fit=6, competition_level=4,
            repo_quality=8, reward_potential=5, ecosystem_momentum=6,
        ),
    )
    snap = await capture_snapshot(db_session, 12)
    assert snap.id is not None
    assert snap.netuid == 12
    payload = snap.payload_json
    assert payload["subnet"]["netuid"] == 12
    assert payload["subnet"]["name"] == "snap-target"
    assert payload["note"]["task_type"] == "text-gen"
    assert payload["latest_score"]["developer_fit"] == 7

    rows = await list_snapshots(db_session, 12)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_capture_snapshot_requires_cache(db_session) -> None:
    with pytest.raises(LookupError):
        await capture_snapshot(db_session, 404)
