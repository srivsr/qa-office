from fastapi import APIRouter

from app.api.routes.runs import router as runs_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(runs_router)


@api_router.get("/projects")
async def list_projects():
    """Stub — qa-office is single-project; returns empty list so Sidebar doesn't 404."""
    return []
