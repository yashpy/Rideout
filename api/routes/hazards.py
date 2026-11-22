"""GET /hazards, GET /hazards/fire, POST /hazards/photo."""

import time
from datetime import datetime

from fastapi import APIRouter, Query

from api.core.db import get_db
from api.core.util import utcnow
from api.hazard import fire
from api.hazard import zones as fire_zones
from api.routes._util import not_yet, out

_FIRE_CACHE: dict[tuple, tuple[float, dict]] = {}

router = APIRouter(prefix="/hazards", tags=["hazards"])


@router.get("")
async def list_hazards() -> dict:
    """Static layers. The fire replay is GET /hazards/fire."""
    db = get_db()
    return {
        "hazards": [out(h) async for h in db.hazards.find({})],
        "closures": [out(c) async for c in db.roadClosures.find({})],
        "shelters": [out(x) async for x in db.shelters.find({})],
        # zone outlines (GET /zones leaves the polygon out); live status still comes from zone.updated
        "zones": [out(z) async for z in db.zones.find({}, {"name": 1, "status": 1, "polygon": 1})],
    }


@router.get("/fire")
async def fire_view(
    at: datetime | None = Query(default=None, description="ISO time to replay to; default now"),
) -> dict:
    """The simulated fire as of `at`: burned area, active edge (last 30 min), 15-minute activity, homes
    reached. Detections come from Tiger Data (`fire_detections` hypertable) when TIGER_DATABASE_URL is set,
    otherwise from the same model in memory (`source` says which). Scenario input, not a forecast."""
    when = at or utcnow()
    # Every open console asks every 5 s; the answer only moves with the clock. One computation per 10 s of
    # replay time, kept for 8 s, serves them all (it was ~10 s of work per call at city scale).
    run = await get_db().hazards.find_one({"_id": fire.RUN_ID}, {"runId": 1, "store": 1})
    run = run or {}
    key = (run.get("runId"), run.get("store"), int(when.timestamp() // 10))
    hit = _FIRE_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < 8:
        return hit[1]
    view = await fire.view(get_db(), when)
    if view["fire"] is not None:
        # What the fire alone says each zone should be at `when` (SET 60 min out, GO 20 min out).
        view["fire"]["zones"] = await fire_zones.levels_at(get_db(), when)
    if len(_FIRE_CACHE) > 256:
        _FIRE_CACHE.clear()
    _FIRE_CACHE[key] = (time.monotonic(), view)
    return view


@router.post("/photo")
async def photo() -> dict:
    """multipart image + lon/lat → Gemini vision → hazard."""
    raise not_yet("photo hazard reports")
