"""FastAPI route registrations."""
from tao_scout.api.routes_export import router as export_router
from tao_scout.api.routes_notes import router as notes_router
from tao_scout.api.routes_scores import router as scores_router
from tao_scout.api.routes_subnets import router as subnets_router

__all__ = ["export_router", "notes_router", "scores_router", "subnets_router"]
