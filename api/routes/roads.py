"""POST /roads/closures."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from api import audit
from api.core.db import get_db
from api.core.util import new_id, utcnow
from api.dispatch.loop import request_replan
from api.models import LineString
from api.routes._util import out

router = APIRouter(prefix="/roads", tags=["roads"])


class ClosureBody(BaseModel):
    geometry: LineString
    source: Literal["hazard", "manual", "sim"] = "manual"


@router.post("/closures")
async def add_closure(body: ClosureBody) -> dict:
    """Stores the closure and re-plans now. The solver stops routing through it (api/sim/geo.py) and takes
    back only the pickups no route reaches anymore: accepted → revoked (the resident is told), offered →
    withdrawn (silent). Each is re-offered to a vehicle that can make it (api/dispatch/loop.py)."""
    db = get_db()
    doc = {"_id": new_id("rc"), "geometry": body.geometry.model_dump(), "source": body.source, "at": utcnow()}
    await db.roadClosures.insert_one(doc)
    await audit.log(db, "road_closed", body.source, closureId=doc["_id"])
    request_replan()
    return out(doc)
