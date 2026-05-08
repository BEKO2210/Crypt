"""HTMX-driven HTML routes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from tao_scout import services
from tao_scout.api.deps import db_session
from tao_scout.config import get_settings
from tao_scout.scoring.axes import AXES, AXIS_KEYS
from tao_scout.scoring.weights import DEFAULT_WEIGHTS, InvalidWeightsError, validate_weights

TEMPLATES_DIR = Path(__file__).parent / "templates"

router = APIRouter()


def get_templates() -> Jinja2Templates:  # type: ignore[name-defined]
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.globals["AXES"] = AXES
    templates.env.globals["AXIS_KEYS"] = AXIS_KEYS
    templates.env.globals["DEFAULT_WEIGHTS"] = DEFAULT_WEIGHTS
    return templates


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    msg: str | None = None,
    kind: str | None = None,
    session: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    cached = await services.get_cached_subnets(session)
    rail = await services.build_continue_rail(
        session,
        workspace_root=services.workspace_root_default(),
    )
    user = await services.get_or_create_settings(session)
    any_stale = any(c.is_stale for c in cached)
    settings = get_settings()
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "subnet_list.html",
        {
            "cached": cached,
            "rail": rail,
            "user": user,
            "any_stale": any_stale,
            "settings": settings,
            "now": datetime.now(UTC),
            "flash_msg": msg,
            "flash_kind": kind if kind in {"ok", "error"} else None,
        },
    )


@router.get("/subnet/{netuid}", response_class=HTMLResponse)
async def subnet_detail(
    netuid: int, request: Request, session: AsyncSession = Depends(db_session)
) -> HTMLResponse:
    cached = await services.get_cached_subnet(session, netuid)
    if cached is None:
        raise HTTPException(status_code=404, detail="subnet not in cache")
    note = await services.get_note(session, netuid)
    scores = await services.list_scores(session, netuid)
    user = await services.get_or_create_settings(session)
    workspace_root = services.workspace_root_default()
    workspace = services.ensure_workspace(workspace_root, netuid, cached.info.name)
    missing = services.list_missing_stages(workspace_root, netuid)
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "subnet_detail.html",
        {
            "cached": cached,
            "note": note,
            "scores": scores,
            "latest_score": scores[0] if scores else None,
            "user": user,
            "workspace": workspace,
            "missing_stages": missing,
        },
    )


@router.post("/subnet/{netuid}/note", response_class=HTMLResponse)
async def submit_note(
    netuid: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
    task_type: str = Form(""),
    repo_url: str = Form(""),
    repo_quality_notes: str = Form(""),
    hardware_required: str = Form(""),
    entry_difficulty: str = Form(""),
    risk_notes: str = Form(""),
    opportunity_notes: str = Form(""),
    tags: str = Form(""),
) -> HTMLResponse:
    cached = await services.get_cached_subnet(session, netuid)
    if cached is None:
        raise HTTPException(status_code=404, detail="subnet not in cache; refresh first")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    note = await services.upsert_note(
        session,
        services.NoteIn(
            netuid=netuid,
            task_type=task_type or None,
            repo_url=repo_url or None,
            repo_quality_notes=repo_quality_notes or None,
            hardware_required=hardware_required or None,
            entry_difficulty=entry_difficulty or None,
            risk_notes=risk_notes or None,
            opportunity_notes=opportunity_notes or None,
            tags=tag_list,
        ),
    )
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "partials/note_saved.html",
        {"note": note, "saved_at": datetime.now(UTC)},
    )


@router.post("/subnet/{netuid}/score", response_class=HTMLResponse)
async def submit_score(
    netuid: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
    developer_fit: int = Form(...),
    hardware_fit: int = Form(...),
    competition_level: int = Form(...),
    repo_quality: int = Form(...),
    reward_potential: int = Form(...),
    ecosystem_momentum: int = Form(...),
    rationale: str = Form(""),
) -> HTMLResponse:
    try:
        score = await services.append_score(
            session,
            services.ScoreIn(
                netuid=netuid,
                developer_fit=developer_fit,
                hardware_fit=hardware_fit,
                competition_level=competition_level,
                repo_quality=repo_quality,
                reward_potential=reward_potential,
                ecosystem_momentum=ecosystem_momentum,
                rationale=rationale or None,
            ),
        )
    except (InvalidWeightsError, ValueError) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "partials/score_card.html",
        {"score": score, "AXES": AXES},
    )


@router.post("/subnet/{netuid}/refresh", response_class=HTMLResponse)
async def refresh_one_html(
    netuid: int, request: Request, session: AsyncSession = Depends(db_session)
) -> HTMLResponse:
    report = await services.refresh_one(session, netuid)
    cached = await services.get_cached_subnet(session, netuid)
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "partials/chain_card.html",
        {"cached": cached, "report": report},
    )


@router.post("/refresh", response_class=HTMLResponse)
async def refresh_all_html(
    request: Request, session: AsyncSession = Depends(db_session)
) -> RedirectResponse:
    report = await services.refresh_all(session)
    if report.error:
        msg = f"chain unreachable: {report.error}; serving cached data"
        kind = "error"
    else:
        msg = f"refreshed {len(report.refreshed)} subnet(s)"
        kind = "ok"
    from urllib.parse import urlencode

    qs = urlencode({"msg": msg, "kind": kind})
    return RedirectResponse(url=f"/?{qs}", status_code=303)


@router.get("/rank", response_class=HTMLResponse)
async def rank_view(
    request: Request,
    by: str = "total",
    session: AsyncSession = Depends(db_session),
) -> HTMLResponse:
    rows = await services.rank(session, by=by, limit=20)
    templates = get_templates()
    return templates.TemplateResponse(
        request, "rank.html", {"rows": rows, "by": by}
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_view(
    request: Request, session: AsyncSession = Depends(db_session)
) -> HTMLResponse:
    user = await services.get_or_create_settings(session)
    settings = get_settings()
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"user": user, "settings": settings, "saved": False, "error": None},
    )


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(
    request: Request,
    session: AsyncSession = Depends(db_session),
    skill_profile: str = Form(""),
    skill_tags: str = Form(""),
    hardware_profile: str = Form("unknown"),
    rpc_url: str = Form(""),
    cache_ttl_seconds: int = Form(300),
    w_developer_fit: float = Form(0.20),
    w_hardware_fit: float = Form(0.20),
    w_competition_level: float = Form(0.20),
    w_repo_quality: float = Form(0.10),
    w_reward_potential: float = Form(0.20),
    w_ecosystem_momentum: float = Form(0.10),
) -> HTMLResponse:
    weights = {
        "developer_fit": w_developer_fit,
        "hardware_fit": w_hardware_fit,
        "competition_level": w_competition_level,
        "repo_quality": w_repo_quality,
        "reward_potential": w_reward_potential,
        "ecosystem_momentum": w_ecosystem_momentum,
    }
    try:
        validate_weights(weights)
    except InvalidWeightsError as e:
        user = await services.get_or_create_settings(session)
        templates = get_templates()
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "user": user,
                "settings": get_settings(),
                "saved": False,
                "error": str(e),
            },
            status_code=422,
        )
    tag_list = [t.strip() for t in skill_tags.split(",") if t.strip()]
    user = await services.update_settings(
        session,
        services.SettingsIn(
            skill_profile=skill_profile or None,
            skill_tags=tag_list,
            hardware_profile=hardware_profile or None,
            weights=weights,
            rpc_url=rpc_url or None,
            cache_ttl_seconds=cache_ttl_seconds,
        ),
    )
    templates = get_templates()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"user": user, "settings": get_settings(), "saved": True, "error": None},
    )
