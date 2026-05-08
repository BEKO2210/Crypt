"""Score endpoints (append-only history)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from tao_scout import services
from tao_scout.api.deps import db_session
from tao_scout.api.schemas import ScoreIn, ScoreOut
from tao_scout.scoring.weights import InvalidWeightsError

router = APIRouter(prefix="/api", tags=["scores"])


@router.get("/subnets/{netuid}/scores", response_model=list[ScoreOut])
async def list_scores(
    netuid: int, session: AsyncSession = Depends(db_session)
) -> list[ScoreOut]:
    rows = await services.list_scores(session, netuid)
    return [ScoreOut.model_validate(r) for r in rows]


@router.post("/subnets/{netuid}/scores", response_model=ScoreOut, status_code=201)
async def post_score(
    netuid: int, payload: ScoreIn, session: AsyncSession = Depends(db_session)
) -> ScoreOut:
    cached = await services.get_cached_subnet(session, netuid)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"subnet {netuid} not in cache; refresh first",
        )
    try:
        score = await services.append_score(
            session,
            services.ScoreIn(
                netuid=netuid,
                developer_fit=payload.developer_fit,
                hardware_fit=payload.hardware_fit,
                competition_level=payload.competition_level,
                repo_quality=payload.repo_quality,
                reward_potential=payload.reward_potential,
                ecosystem_momentum=payload.ecosystem_momentum,
                rationale=payload.rationale,
                weights=payload.weights,
            ),
        )
    except InvalidWeightsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return ScoreOut.model_validate(score)


@router.get("/rank")
async def rank(
    by: str = Query("total", pattern="^(total|reward|fit)$"),
    limit: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(db_session),
) -> list[dict]:
    rows = await services.rank(session, by=by, limit=limit)
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "netuid": r.subnet.netuid,
                "name": r.subnet.name,
                "weighted_total": r.score.weighted_total if r.score else None,
                "developer_fit": r.score.developer_fit if r.score else None,
                "hardware_fit": r.score.hardware_fit if r.score else None,
                "competition_level": r.score.competition_level if r.score else None,
                "repo_quality": r.score.repo_quality if r.score else None,
                "reward_potential": r.score.reward_potential if r.score else None,
                "ecosystem_momentum": r.score.ecosystem_momentum if r.score else None,
                "scored_at": r.score.created_at.isoformat() if r.score else None,
            }
        )
    return out
