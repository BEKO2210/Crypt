"""Export / import endpoints + settings + health."""

from __future__ import annotations

import csv
import io
import json
import platform
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tao_scout import services
from tao_scout.api.deps import db_session
from tao_scout.api.schemas import HealthOut, SettingsIn, SettingsOut
from tao_scout.chain.client import ReadOnlyChainClient
from tao_scout.config import get_settings
from tao_scout.db.models import Note, Score, Subnet
from tao_scout.scoring.weights import InvalidWeightsError

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/health", response_model=HealthOut)
async def health(session: AsyncSession = Depends(db_session)) -> HealthOut:
    s = get_settings()
    sdk_version: str | None
    try:
        import bittensor  # type: ignore[import-not-found]

        sdk_version = getattr(bittensor, "__version__", None)
    except Exception:
        sdk_version = None

    db_ok = True
    try:
        await session.execute(select(Subnet).limit(1))
    except Exception:
        db_ok = False

    rpc_ok = False
    err: str | None = None
    try:
        async with ReadOnlyChainClient() as c:
            status = await c.status()
            rpc_ok = status.reachable
            err = status.error
    except Exception as e:
        err = str(e)

    return HealthOut(
        sdk_version=sdk_version,
        rpc_reachable=rpc_ok,
        rpc_url=s.rpc_url,
        network=s.network,
        db_ok=db_ok,
        error=err,
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings_endpoint(
    session: AsyncSession = Depends(db_session),
) -> SettingsOut:
    row = await services.get_or_create_settings(session)
    return SettingsOut.model_validate(row)


@router.put("/settings", response_model=SettingsOut)
async def put_settings(
    payload: SettingsIn, session: AsyncSession = Depends(db_session)
) -> SettingsOut:
    try:
        row = await services.update_settings(
            session,
            services.SettingsIn(
                skill_profile=payload.skill_profile,
                skill_tags=payload.skill_tags,
                hardware_profile=payload.hardware_profile,
                weights=payload.weights,
                rpc_url=payload.rpc_url,
                cache_ttl_seconds=payload.cache_ttl_seconds,
            ),
        )
    except InvalidWeightsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return SettingsOut.model_validate(row)


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


def _serialize_note(n: Note) -> dict[str, Any]:
    return {
        "netuid": n.netuid,
        "task_type": n.task_type,
        "repo_url": n.repo_url,
        "repo_quality_notes": n.repo_quality_notes,
        "hardware_required": n.hardware_required,
        "entry_difficulty": n.entry_difficulty,
        "risk_notes": n.risk_notes,
        "opportunity_notes": n.opportunity_notes,
        "tags": list(n.tags or []),
        "last_reviewed_at": n.last_reviewed_at.isoformat() if n.last_reviewed_at else None,
    }


def _serialize_score(s: Score) -> dict[str, Any]:
    return {
        "netuid": s.netuid,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "developer_fit": s.developer_fit,
        "hardware_fit": s.hardware_fit,
        "competition_level": s.competition_level,
        "repo_quality": s.repo_quality,
        "reward_potential": s.reward_potential,
        "ecosystem_momentum": s.ecosystem_momentum,
        "weighted_total": s.weighted_total,
        "weights_snapshot": dict(s.weights_snapshot or {}),
        "rationale": s.rationale,
    }


@router.post("/export")
async def export(
    format: str = Query("json", pattern="^(json|csv)$"),
    session: AsyncSession = Depends(db_session),
) -> Response:
    notes = list((await session.execute(select(Note))).scalars().all())
    scores = list((await session.execute(select(Score))).scalars().all())

    if format == "json":
        body = {
            "version": 1,
            "exported_at": datetime.now(UTC).isoformat(),
            "platform": platform.platform(),
            "notes": [_serialize_note(n) for n in notes],
            "scores": [_serialize_score(s) for s in scores],
        }
        return Response(
            content=json.dumps(body, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="tao-scout-export.json"'},
        )

    # CSV: two-section file (notes block, then scores block).
    out = io.StringIO()
    out.write("# notes\n")
    note_writer = csv.DictWriter(
        out,
        fieldnames=[
            "netuid", "task_type", "repo_url", "repo_quality_notes",
            "hardware_required", "entry_difficulty", "risk_notes",
            "opportunity_notes", "tags", "last_reviewed_at",
        ],
    )
    note_writer.writeheader()
    for n in notes:
        d = _serialize_note(n)
        d["tags"] = ";".join(d["tags"])
        note_writer.writerow(d)
    out.write("\n# scores\n")
    score_writer = csv.DictWriter(
        out,
        fieldnames=[
            "netuid", "created_at", "developer_fit", "hardware_fit",
            "competition_level", "repo_quality", "reward_potential",
            "ecosystem_momentum", "weighted_total", "weights_snapshot",
            "rationale",
        ],
    )
    score_writer.writeheader()
    for s in scores:
        d = _serialize_score(s)
        d["weights_snapshot"] = json.dumps(d["weights_snapshot"])
        score_writer.writerow(d)
    return PlainTextResponse(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tao-scout-export.csv"'},
    )


@router.post("/import")
async def import_endpoint(
    file: UploadFile, session: AsyncSession = Depends(db_session)
) -> dict[str, int]:
    raw = await file.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"invalid JSON: {e}") from e
    if not isinstance(data, dict) or data.get("version") != 1:
        raise HTTPException(status_code=422, detail="unsupported export version")

    note_count = 0
    for nd in data.get("notes", []):
        await services.upsert_note(
            session,
            services.NoteIn(
                netuid=int(nd["netuid"]),
                task_type=nd.get("task_type"),
                repo_url=nd.get("repo_url"),
                repo_quality_notes=nd.get("repo_quality_notes"),
                hardware_required=nd.get("hardware_required"),
                entry_difficulty=nd.get("entry_difficulty"),
                risk_notes=nd.get("risk_notes"),
                opportunity_notes=nd.get("opportunity_notes"),
                tags=list(nd.get("tags", [])),
            ),
        )
        note_count += 1

    score_count = 0
    for sd in data.get("scores", []):
        await services.append_score(
            session,
            services.ScoreIn(
                netuid=int(sd["netuid"]),
                developer_fit=int(sd["developer_fit"]),
                hardware_fit=int(sd["hardware_fit"]),
                competition_level=int(sd["competition_level"]),
                repo_quality=int(sd["repo_quality"]),
                reward_potential=int(sd["reward_potential"]),
                ecosystem_momentum=int(sd["ecosystem_momentum"]),
                rationale=sd.get("rationale"),
                weights=sd.get("weights_snapshot"),
            ),
        )
        score_count += 1

    return {"notes": note_count, "scores": score_count}
