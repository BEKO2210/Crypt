"""FastAPI application factory.

Hooks the read-only invariants into startup logging:

* Logs a warning if any wallet-related env vars are set.
* Verifies that no wallet/Keypair imports leaked into ``src/``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import structlog
from fastapi import FastAPI

from tao_scout.api.routes_export import router as export_router
from tao_scout.api.routes_notes import router as notes_router
from tao_scout.api.routes_scores import router as scores_router
from tao_scout.api.routes_subnets import router as subnets_router
from tao_scout.config import get_settings
from tao_scout.safety import find_forbidden_wallet_imports, warn_if_wallet_env_present
from tao_scout.web.routes import router as web_router

logger = structlog.get_logger("tao_scout")


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=level)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper())
        ),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


def _self_audit() -> None:
    settings = get_settings()
    if not settings.read_only:  # pragma: no cover - frozen invariant
        raise RuntimeError("settings.read_only must be True; this is a build error")

    suspicious_env = warn_if_wallet_env_present()
    if suspicious_env:
        logger.warning(
            "wallet_env_present",
            vars=suspicious_env,
            note="TAO-Scout never reads wallets, but these env vars are set.",
        )

    # Prefer scanning the whole src/ tree (one level above the package),
    # falling back to the package directory if the layout is non-standard.
    package_dir = Path(__file__).parent
    src_root = package_dir.parent if package_dir.parent.name == "src" else package_dir
    findings = find_forbidden_wallet_imports(src_root)
    if findings:  # pragma: no cover - prevented by tests
        raise RuntimeError(
            f"forbidden wallet/Keypair imports found in src/: {findings}"
        )


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.log_level)
    _self_audit()

    app = FastAPI(
        title="TAO-Scout",
        version="0.1.0",
        description="Strictly local, strictly read-only Bittensor subnet research dashboard.",
    )

    app.include_router(subnets_router)
    app.include_router(notes_router)
    app.include_router(scores_router)
    app.include_router(export_router)
    app.include_router(web_router)

    @app.get("/api", include_in_schema=False)
    async def api_index() -> dict:
        return {"name": "tao-scout", "version": "0.1.0", "read_only": True}

    return app


app = create_app()
