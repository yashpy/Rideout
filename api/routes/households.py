"""GET /households (core) and PATCH /households/{id}/record (agent only)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.core.auth import require_internal_token
from api.core.db import get_db
from api.core.util import utcnow
from api.models import Record
from api.routes._util import out

router = APIRouter(tags=["households"])


@router.get("/households")
async def list_households(zoneId: str | None = Query(default=None)) -> list[dict]:
    q = {"zoneId": zoneId} if zoneId else {}
    return [out(d) async for d in get_db().households.find(q)]


@router.patch("/households/{household_id}/record", dependencies=[Depends(require_internal_token)])
async def patch_record(household_id: str, patch: Record) -> dict:
    """Merge a partial record. A changed (non-empty) value is logged as a correction."""
    db = get_db()
    hh = await db.households.find_one({"_id": household_id})
    if hh is None:
        raise HTTPException(404, "household not found")

    now = utcnow()
    current = hh.get("record") or {}
    changes = patch.model_dump(exclude_none=True)
    update: dict[str, Any] = {"$set": {**{f"record.{k}": v for k, v in changes.items()}, "updatedAt": now}}
    corrections = [
        {"field": k, "from": current[k], "to": v, "at": now}
        for k, v in changes.items()
        if k != "confidence" and current.get(k) is not None and current[k] != v
    ]
    if corrections:
        update["$push"] = {"corrections": {"$each": corrections}}
    await db.households.update_one({"_id": household_id}, update)
    return out(await db.households.find_one({"_id": household_id}))
