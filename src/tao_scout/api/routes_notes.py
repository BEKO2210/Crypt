"""Notes endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tao_scout import services
from tao_scout.api.deps import db_session
from tao_scout.api.schemas import NoteIn, NoteOut

router = APIRouter(prefix="/api/subnets", tags=["notes"])


@router.get("/{netuid}/notes", response_model=NoteOut | None)
async def get_note(
    netuid: int, session: AsyncSession = Depends(db_session)
) -> NoteOut | None:
    note = await services.get_note(session, netuid)
    if note is None:
        return None
    return NoteOut.model_validate(note)


@router.put("/{netuid}/notes", response_model=NoteOut)
async def put_note(
    netuid: int, payload: NoteIn, session: AsyncSession = Depends(db_session)
) -> NoteOut:
    cached = await services.get_cached_subnet(session, netuid)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"subnet {netuid} not in cache; refresh first",
        )
    note = await services.upsert_note(
        session,
        services.NoteIn(
            netuid=netuid,
            task_type=payload.task_type,
            repo_url=payload.repo_url,
            repo_quality_notes=payload.repo_quality_notes,
            hardware_required=payload.hardware_required,
            entry_difficulty=payload.entry_difficulty,
            risk_notes=payload.risk_notes,
            opportunity_notes=payload.opportunity_notes,
            tags=list(payload.tags),
        ),
    )
    return NoteOut.model_validate(note)
