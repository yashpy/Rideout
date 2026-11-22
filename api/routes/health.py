from typing import Any

from fastapi import APIRouter

from api.core.config import VERSION, get_settings

router = APIRouter(tags=["core"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """Check this before every demo: which env, which build."""
    s = get_settings()
    return {"ok": True, "env": s.env, "version": VERSION, "gitSha": s.git_sha}
