"""Service layer: shared business logic for CLI and HTTP routes.

Both ``cli/main.py`` and ``api/*`` thin-wrap functions here. Tests target
this module directly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from tao_scout.chain.cache import (
    CachedSubnet,
    RefreshReport,
    get_cached_subnet,
    get_cached_subnets,
    refresh_all,
    refresh_one,
)
from tao_scout.db.models import Note, Score, Snapshot, Subnet, UserSettings
from tao_scout.scoring.engine import ScoreInput, build_rationale_skeleton, compute_weighted_total
from tao_scout.scoring.weights import DEFAULT_WEIGHTS, validate_weights

# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------


@dataclass
class NoteIn:
    netuid: int
    task_type: str | None = None
    repo_url: str | None = None
    repo_quality_notes: str | None = None
    hardware_required: str | None = None
    entry_difficulty: str | None = None
    risk_notes: str | None = None
    opportunity_notes: str | None = None
    tags: list[str] | None = None


async def get_note(session: AsyncSession, netuid: int) -> Note | None:
    res = await session.execute(select(Note).where(Note.netuid == netuid))
    return res.scalar_one_or_none()


async def upsert_note(session: AsyncSession, payload: NoteIn) -> Note:
    note = await get_note(session, payload.netuid)
    if note is None:
        note = Note(netuid=payload.netuid, tags=payload.tags or [])
        session.add(note)
    note.task_type = payload.task_type
    note.repo_url = payload.repo_url
    note.repo_quality_notes = payload.repo_quality_notes
    note.hardware_required = payload.hardware_required
    note.entry_difficulty = payload.entry_difficulty
    note.risk_notes = payload.risk_notes
    note.opportunity_notes = payload.opportunity_notes
    if payload.tags is not None:
        note.tags = list(payload.tags)
    note.last_reviewed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(note)
    return note


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class ScoreIn:
    netuid: int
    developer_fit: int
    hardware_fit: int
    competition_level: int
    repo_quality: int
    reward_potential: int
    ecosystem_momentum: int
    rationale: str | None = None
    weights: Mapping[str, float] | None = None


async def append_score(session: AsyncSession, payload: ScoreIn) -> Score:
    if payload.weights is not None:
        weights: Mapping[str, float] = payload.weights
    else:
        # Read user settings if they exist; fall back to defaults without
        # creating a settings row as a side-effect of scoring.
        existing = await session.get(UserSettings, 1)
        weights = existing.weights if existing is not None else DEFAULT_WEIGHTS
    norm_weights = validate_weights(weights)

    score_input = ScoreInput(
        developer_fit=payload.developer_fit,
        hardware_fit=payload.hardware_fit,
        competition_level=payload.competition_level,
        repo_quality=payload.repo_quality,
        reward_potential=payload.reward_potential,
        ecosystem_momentum=payload.ecosystem_momentum,
    )
    result = compute_weighted_total(score_input, norm_weights)

    rationale = payload.rationale
    if not rationale:
        rationale = build_rationale_skeleton(score_input, norm_weights)

    score = Score(
        netuid=payload.netuid,
        developer_fit=score_input.developer_fit,
        hardware_fit=score_input.hardware_fit,
        competition_level=score_input.competition_level,
        repo_quality=score_input.repo_quality,
        reward_potential=score_input.reward_potential,
        ecosystem_momentum=score_input.ecosystem_momentum,
        weighted_total=result.weighted_total,
        weights_snapshot=norm_weights,
        rationale=rationale,
    )
    session.add(score)
    await session.commit()
    await session.refresh(score)
    return score


async def list_scores(session: AsyncSession, netuid: int) -> list[Score]:
    res = await session.execute(
        select(Score).where(Score.netuid == netuid).order_by(desc(Score.created_at))
    )
    return list(res.scalars().all())


async def latest_score(session: AsyncSession, netuid: int) -> Score | None:
    res = await session.execute(
        select(Score).where(Score.netuid == netuid).order_by(desc(Score.created_at)).limit(1)
    )
    return res.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Rank
# ---------------------------------------------------------------------------


@dataclass
class RankRow:
    subnet: Subnet
    note: Note | None
    score: Score | None


async def rank(session: AsyncSession, *, by: str = "total", limit: int = 20) -> list[RankRow]:
    rows = (
        (await session.execute(select(Subnet).order_by(Subnet.netuid))).scalars().all()
    )
    out: list[RankRow] = []
    for s in rows:
        note = await get_note(session, s.netuid)
        latest = await latest_score(session, s.netuid)
        out.append(RankRow(subnet=s, note=note, score=latest))

    if by == "total":
        out.sort(
            key=lambda r: (r.score.weighted_total if r.score else -1.0),
            reverse=True,
        )
    elif by == "reward":
        out.sort(
            key=lambda r: (r.score.reward_potential if r.score else -1),
            reverse=True,
        )
    elif by == "fit":
        out.sort(
            key=lambda r: (
                ((r.score.developer_fit + r.score.hardware_fit) / 2.0)
                if r.score
                else -1.0
            ),
            reverse=True,
        )
    else:
        raise ValueError(f"unknown rank order: {by!r}")
    return out[:limit]


# ---------------------------------------------------------------------------
# Settings (singleton)
# ---------------------------------------------------------------------------


async def get_or_create_settings(session: AsyncSession) -> UserSettings:
    row = await session.get(UserSettings, 1)
    if row is None:
        row = UserSettings(
            id=1,
            skill_profile=None,
            skill_tags=[],
            hardware_profile="unknown",
            weights=dict(DEFAULT_WEIGHTS),
            rpc_url=None,
            cache_ttl_seconds=None,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


@dataclass
class SettingsIn:
    skill_profile: str | None = None
    skill_tags: list[str] | None = None
    hardware_profile: str | None = None
    weights: Mapping[str, float] | None = None
    rpc_url: str | None = None
    cache_ttl_seconds: int | None = None


async def update_settings(session: AsyncSession, payload: SettingsIn) -> UserSettings:
    row = await get_or_create_settings(session)
    if payload.skill_profile is not None:
        row.skill_profile = payload.skill_profile
    if payload.skill_tags is not None:
        row.skill_tags = list(payload.skill_tags)
    if payload.hardware_profile is not None:
        row.hardware_profile = payload.hardware_profile
    if payload.weights is not None:
        row.weights = validate_weights(payload.weights)
    if payload.rpc_url is not None:
        row.rpc_url = payload.rpc_url
    if payload.cache_ttl_seconds is not None:
        row.cache_ttl_seconds = int(payload.cache_ttl_seconds)
    await session.commit()
    await session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# "Continue" home rail
# ---------------------------------------------------------------------------


@dataclass
class ContinueRail:
    last_reviewed: list[Subnet]
    oldest_scored: list[Subnet]
    stale_data: list[Subnet]
    unfinished_workspaces: list[tuple[int, list[str]]]
    """List of (netuid, missing_stage_names)."""


async def build_continue_rail(
    session: AsyncSession,
    *,
    workspace_root: Path,
    stale_after_seconds: int = 3600,
    limit: int = 5,
) -> ContinueRail:
    rows: Sequence[Subnet] = (
        (await session.execute(select(Subnet))).scalars().all()
    )
    now = datetime.now(UTC)

    def _aware(d: datetime | None) -> datetime | None:
        if d is None:
            return None
        return d if d.tzinfo else d.replace(tzinfo=UTC)

    last_reviewed: list[tuple[datetime, Subnet]] = []
    oldest: list[tuple[datetime, Subnet]] = []
    stale: list[Subnet] = []
    unfinished: list[tuple[int, list[str]]] = []

    for s in rows:
        note = await get_note(session, s.netuid)
        nlr = _aware(note.last_reviewed_at) if note else None
        if nlr is not None:
            last_reviewed.append((nlr, s))
        score = await latest_score(session, s.netuid)
        sca = _aware(score.created_at) if score else None
        if sca is not None:
            oldest.append((sca, s))
        last_ref = _aware(s.last_refreshed_at)
        if last_ref is None or (now - last_ref > timedelta(seconds=stale_after_seconds)):
            stale.append(s)
        missing = list_missing_stages(workspace_root, s.netuid)
        if missing:
            unfinished.append((s.netuid, missing))

    last_reviewed.sort(key=lambda t: t[0], reverse=True)
    oldest.sort(key=lambda t: t[0])  # ascending = oldest first

    return ContinueRail(
        last_reviewed=[s for _, s in last_reviewed[:limit]],
        oldest_scored=[s for _, s in oldest[:limit]],
        stale_data=stale[:limit],
        unfinished_workspaces=unfinished[:limit],
    )


# ---------------------------------------------------------------------------
# ICM workspace helpers (M2)
# ---------------------------------------------------------------------------

ICM_STAGES: tuple[str, ...] = (
    "01-chain",
    "02-repo",
    "03-research",
    "04-scoring",
    "05-rationale",
)


def workspace_root_default() -> Path:
    return Path("./data/workspaces").resolve()


def workspace_dir(root: Path, netuid: int) -> Path:
    return root / f"netuid-{netuid:03d}"


def list_missing_stages(root: Path, netuid: int) -> list[str]:
    """Return ICM stage names whose CONTEXT.adoc is missing or empty."""
    base = workspace_dir(root, netuid)
    if not base.exists():
        return list(ICM_STAGES)
    missing: list[str] = []
    for stage in ICM_STAGES:
        ctx = base / stage / "CONTEXT.adoc"
        if not ctx.exists() or ctx.stat().st_size == 0:
            missing.append(stage)
    return missing


def ensure_workspace(root: Path, netuid: int, subnet_name: str | None = None) -> Path:
    """Create the per-subnet ICM workspace if missing. Returns the workspace dir."""
    base = workspace_dir(root, netuid)
    base.mkdir(parents=True, exist_ok=True)
    title = subnet_name or f"Subnet {netuid}"

    layer1 = base / "CONTEXT.adoc"
    if not layer1.exists():
        layer1.write_text(_layer1_template(netuid, title), encoding="utf-8")

    for stage in ICM_STAGES:
        sd = base / stage
        sd.mkdir(exist_ok=True)
        ctx = sd / "CONTEXT.adoc"
        if not ctx.exists():
            ctx.write_text(_stage_template(netuid, title, stage), encoding="utf-8")
    return base


def _layer1_template(netuid: int, title: str) -> str:
    return (
        f"= Subnet {netuid} -- {title}\n"
        f":icm-version: 1\n"
        f":netuid: {netuid}\n"
        f":generated: {datetime.now(UTC).isoformat()}\n\n"
        "== Purpose\n\n"
        "Single-subnet research workspace following the Interpreted Context Methodology.\n"
        "Each numbered stage folder contains a CONTEXT.adoc declaring its Inputs, Process,\n"
        "and Outputs. Stages flow:\n\n"
        ". 01-chain     -- objective on-chain data snapshot\n"
        ". 02-repo      -- reference miner/validator codebase review\n"
        ". 03-research  -- ecosystem signals, community, momentum\n"
        ". 04-scoring   -- the six axis scores (0-10)\n"
        ". 05-rationale -- weighted total + dominant-axis explanation\n\n"
        "Outputs of each stage become inputs to the next.\n"
    )


def _stage_template(netuid: int, title: str, stage: str) -> str:
    inputs, process, outputs = _stage_blueprint(stage)
    return (
        f"= {stage} -- Subnet {netuid} ({title})\n\n"
        "== Inputs\n\n"
        + "\n".join(f"* {x}" for x in inputs)
        + "\n\n== Process\n\n"
        + "\n".join(f". {x}" for x in process)
        + "\n\n== Outputs\n\n"
        + "\n".join(f"* {x}" for x in outputs)
        + "\n\n== Notes\n\n"
        "// Replace this comment with your findings.\n"
    )


def _stage_blueprint(stage: str) -> tuple[list[str], list[str], list[str]]:
    if stage == "01-chain":
        return (
            ["Cached chain row from tao_scout.db (subnets table)"],
            ["Inspect emission, burn, n_validators, n_miners, max_n.",
             "Run `tao-scout refresh --netuid N` if data is stale."],
            ["Snapshot of objective metrics (will inform competition_level + reward_potential)."],
        )
    if stage == "02-repo":
        return (
            ["Reference miner/validator repo URL (filled into Notes)."],
            ["Clone or browse repo on GitHub.",
             "Assess: README quality, tests, recent commits, dependency hygiene.",
             "Decide: hardware required (CPU / 8GB / 24GB / multi-GPU / cluster)."],
            ["repo_quality axis (0-10) draft.", "hardware_fit axis (0-10) draft."],
        )
    if stage == "03-research":
        return (
            ["Discord / X / forum links for the subnet's team and validators."],
            ["Skim community discussion for last 30 days.",
             "Note momentum (growing / steady / shrinking).",
             "Match subnet's task to your skill profile."],
            ["ecosystem_momentum axis draft.", "developer_fit axis draft."],
        )
    if stage == "04-scoring":
        return (
            ["Drafts from stages 01-03."],
            ["Open the subnet detail page and submit the scoring form,",
             "or run `tao-scout score <netuid>` from the CLI."],
            ["Append-only Score row in the database; weighted_total is computed."],
        )
    if stage == "05-rationale":
        return (
            ["Latest Score row + weights snapshot."],
            ["Read the auto-generated rationale skeleton and edit it.",
             "Save to overwrite the rationale field on the latest Score (re-score)."],
            ["Final, human-curated rationale string."],
        )
    return (["..."], ["..."], ["..."])


# ---------------------------------------------------------------------------
# Snapshots (M3)
# ---------------------------------------------------------------------------


@dataclass
class SnapshotOut:
    id: int
    netuid: int
    captured_at: datetime
    payload: dict[str, Any]


def _snapshot_payload(cached: CachedSubnet, note: Note | None, score: Score | None) -> dict[str, Any]:
    return {
        "captured_at": datetime.now(UTC).isoformat(),
        "is_stale": cached.is_stale,
        "subnet": cached.info.model_dump(mode="json"),
        "note": (
            {
                "task_type": note.task_type,
                "repo_url": note.repo_url,
                "repo_quality_notes": note.repo_quality_notes,
                "hardware_required": note.hardware_required,
                "entry_difficulty": note.entry_difficulty,
                "risk_notes": note.risk_notes,
                "opportunity_notes": note.opportunity_notes,
                "tags": list(note.tags or []),
                "last_reviewed_at": note.last_reviewed_at.isoformat() if note.last_reviewed_at else None,
            }
            if note is not None
            else None
        ),
        "latest_score": (
            {
                "developer_fit": score.developer_fit,
                "hardware_fit": score.hardware_fit,
                "competition_level": score.competition_level,
                "repo_quality": score.repo_quality,
                "reward_potential": score.reward_potential,
                "ecosystem_momentum": score.ecosystem_momentum,
                "weighted_total": score.weighted_total,
                "weights_snapshot": dict(score.weights_snapshot or {}),
                "rationale": score.rationale,
                "created_at": score.created_at.isoformat() if score.created_at else None,
            }
            if score is not None
            else None
        ),
    }


async def capture_snapshot(session: AsyncSession, netuid: int) -> Snapshot:
    """Append a Snapshot row capturing the current cached + note + latest score state.

    Raises ``LookupError`` if the subnet is not in the cache; nothing is written
    in that case so the caller can surface a clear "refresh first" message.
    """
    cached = await get_cached_subnet(session, netuid)
    if cached is None:
        raise LookupError(f"subnet {netuid} not in cache; refresh first")
    note = await get_note(session, netuid)
    score = await latest_score(session, netuid)
    payload = _snapshot_payload(cached, note, score)
    snap = Snapshot(netuid=netuid, payload_json=payload)
    session.add(snap)
    await session.commit()
    await session.refresh(snap)
    return snap


async def list_snapshots(session: AsyncSession, netuid: int) -> list[Snapshot]:
    res = await session.execute(
        select(Snapshot).where(Snapshot.netuid == netuid).order_by(desc(Snapshot.captured_at))
    )
    return list(res.scalars().all())


# ---------------------------------------------------------------------------
# Re-exported chain helpers
# ---------------------------------------------------------------------------


__all__ = [
    "ICM_STAGES",
    "CachedSubnet",
    "ContinueRail",
    "NoteIn",
    "RankRow",
    "RefreshReport",
    "ScoreIn",
    "SettingsIn",
    "SnapshotOut",
    "append_score",
    "build_continue_rail",
    "capture_snapshot",
    "ensure_workspace",
    "get_cached_subnet",
    "get_cached_subnets",
    "get_note",
    "get_or_create_settings",
    "latest_score",
    "list_missing_stages",
    "list_scores",
    "list_snapshots",
    "rank",
    "refresh_all",
    "refresh_one",
    "update_settings",
    "upsert_note",
    "workspace_dir",
    "workspace_root_default",
]
