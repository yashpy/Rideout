"""GET /requests/open, POST /requests/{id}/escalate, POST /requests/{id}/close.

Status itself only changes in api/requests.py (close goes through api.assignments.close_request).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api import assignments as asg
from api import audit
from api import requests as rq
from api.core.db import get_db
from api.core.util import utcnow
from api.routes._util import out

router = APIRouter(tags=["requests"])


@router.get("/requests/open")
async def open_requests() -> list[dict]:
    """Open requests + household. Riders being reassigned first, then earliest deadline."""
    db = get_db()
    reqs = [d async for d in db.requests.find({"status": {"$in": list(rq.OPEN_STATUSES)}, "dupOf": None})]
    hh_ids = list({r["householdId"] for r in reqs})
    households = {h["_id"]: out(h) async for h in db.households.find({"_id": {"$in": hh_ids}})}

    def sort_key(r: dict) -> tuple:
        d = r.get("deadlineAt")
        return (r["status"] != "reassigning", d is None, d.timestamp() if d else 0.0)

    return [{**out(r), "household": households.get(r["householdId"])} for r in sorted(reqs, key=sort_key)]


class EscalateBody(BaseModel):
    reason: str  # medical | flames | address_unconfirmed | unservable | language


@router.post("/requests/{request_id}/escalate")
async def escalate(request_id: str, body: EscalateBody) -> dict:
    db = get_db()
    res = await db.requests.update_one(
        {"_id": request_id},
        {"$set": {"escalation": body.reason, "updatedAt": utcnow()}, "$inc": {"version": 1}},
    )
    if not res.matched_count:
        raise HTTPException(404, "request not found")
    await audit.log(db, "request_escalated", body.reason, requestId=request_id)
    return out(await db.requests.find_one({"_id": request_id}))


class CloseBody(BaseModel):
    reason: str  # resident_left | duplicate | dispatcher


@router.post("/requests/{request_id}/close")
async def close(request_id: str, body: CloseBody) -> dict:
    """No ride needed any more. Live offers are withdrawn, an accepted pickup is dropped. No callback."""
    try:
        return out(await asg.close_request(get_db(), request_id, reason=body.reason))
    except rq.RequestNotFound as e:
        raise HTTPException(404, "request not found") from e
    except rq.RequestError as e:
        raise HTTPException(409, str(e)) from e
