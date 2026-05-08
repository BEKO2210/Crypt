"""Subnet read + refresh endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tao_scout import services
from tao_scout.api.deps import db_session
from tao_scout.api.schemas import RefreshOut, RefreshRequest, SubnetOut

router = APIRouter(prefix="/api/subnets", tags=["subnets"])


@router.get("", response_model=list[SubnetOut])
async def list_subnets(session: AsyncSession = Depends(db_session)) -> list[SubnetOut]:
    cached = await services.get_cached_subnets(session)
    return [
        SubnetOut(**c.info.model_dump(exclude={"raw", "fetched_at"}),
                  last_refreshed_at=c.cached_at, is_stale=c.is_stale)
        for c in cached
    ]


@router.get("/{netuid}", response_model=SubnetOut)
async def get_subnet(
    netuid: int, session: AsyncSession = Depends(db_session)
) -> SubnetOut:
    c = await services.get_cached_subnet(session, netuid)
    if c is None:
        raise HTTPException(status_code=404, detail=f"subnet {netuid} not in cache")
    return SubnetOut(
        **c.info.model_dump(exclude={"raw", "fetched_at"}),
        last_refreshed_at=c.cached_at,
        is_stale=c.is_stale,
    )


@router.post("/refresh", response_model=RefreshOut)
async def refresh_subnets(
    payload: RefreshRequest | None = None,
    session: AsyncSession = Depends(db_session),
) -> RefreshOut:
    if payload is not None and payload.netuid is not None:
        report = await services.refresh_one(session, payload.netuid)
    else:
        report = await services.refresh_all(session)
    return RefreshOut(
        refreshed=report.refreshed,
        failed=report.failed,
        error=report.error,
        used_cache=report.used_cache,
    )
