"""POST /plans/solve, GET /plans/latest."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from api.core.db import get_db
from api.dispatch import loop
from api.routes._util import out

router = APIRouter(prefix="/plans", tags=["plans"])


class SolveBody(BaseModel):
    solver: Literal["batched", "greedy", "ortools"] = "batched"


@router.post("/solve")
async def solve(body: SolveBody | None = None) -> dict:
    """Plan once now. `batched` (default): Uber-style batched matching; `greedy`: the old planner.
    OR-Tools isn't built; it runs batched (`requested` says what was asked for)."""
    return await loop.solve_once(get_db(), (body or SolveBody()).solver)


@router.get("/latest")
async def latest() -> dict:
    """The newest plan + every live offer the dispatcher can act on (proposed and offered, any version)."""
    db = get_db()
    plan = await db.plans.find_one(sort=[("version", -1)])
    rows = [a async for a in db.assignments.find({"status": {"$in": ["proposed", "offered"]}}).sort("etaMinutes", 1)]
    # Skip offers left over from a world that was reseeded away (their request is gone or closed).
    open_ids = {
        r["_id"]
        async for r in db.requests.find(
            {"_id": {"$in": list({a["requestId"] for a in rows})}, "status": {"$ne": "closed"}}, {"_id": 1}
        )
    }
    return {"plan": out(plan), "assignments": [out(a) for a in rows if a["requestId"] in open_ids]}
