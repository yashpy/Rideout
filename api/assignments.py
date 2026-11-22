"""Offer lifecycle: approve → offered → accept (atomic) | decline | expire; accepted → revoke.

    proposed → offered → accepted → completed
    side exits: declined, expired, replaced (silent), revoked (resident is told)

After accept, the run reports progress (`progress()`): en_route + ETA → arrived → completed.
`close_request()` is the one exit path for a request that ends early (resident left, duplicate).

Only one assignment per request is live (proposed/offered/accepted) at a time.
Request status moves go through api.requests.transition(), never directly.
"""

from datetime import datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from api import audit, callbacks
from api import requests as rq
from api.core.config import get_settings
from api.core.util import utcnow


class AssignmentError(Exception):
    def __init__(self, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


async def _get(db: AsyncIOMotorDatabase, assignment_id: str) -> dict[str, Any]:
    a = await db.assignments.find_one({"_id": assignment_id})
    if a is None:
        raise AssignmentError(f"assignment {assignment_id} not found", status_code=404)
    return a


async def _has_live_offer(db: AsyncIOMotorDatabase, request_id: str) -> bool:
    return await db.assignments.count_documents({"requestId": request_id, "status": "offered"}) > 0


async def _settle_request_after_offer_closed(db: AsyncIOMotorDatabase, request_id: str, reason: str) -> None:
    """approved → received (silently) when no offer is left. A reassigning request stays reassigning."""
    req = await db.requests.find_one({"_id": request_id})
    if req and req["status"] == "approved" and not await _has_live_offer(db, request_id):
        await rq.transition(db, request_id, "received", reason=reason)


async def _vehicle_status(db: AsyncIOMotorDatabase, vehicle_id: str) -> None:
    """Derive the vehicle's status from its assignments."""
    if await db.assignments.count_documents({"vehicleId": vehicle_id, "status": "accepted"}):
        status = "on_run"
    elif await db.assignments.count_documents({"vehicleId": vehicle_id, "status": "offered"}):
        status = "offered"
    else:
        status = "idle"
    await db.vehicles.update_one({"_id": vehicle_id, "status": {"$ne": "offline"}}, {"$set": {"status": status}})


async def approve(db: AsyncIOMotorDatabase, assignment_id: str, *, by: str = "dispatcher") -> dict[str, Any]:
    """Dispatcher approves a proposed assignment. Approval is NOT a promise: no callback."""
    a = await _get(db, assignment_id)
    req = await db.requests.find_one({"_id": a["requestId"]})
    if req is None or req["status"] not in ("received", "approved", "reassigning"):
        raise AssignmentError(f"request is {req and req['status']}, can't offer it")

    now = utcnow()
    ttl = timedelta(seconds=get_settings().offer_ttl_seconds)
    offered = await db.assignments.find_one_and_update(
        {"_id": assignment_id, "status": "proposed"},
        {"$set": {"status": "offered", "offeredAt": now, "expiresAt": now + ttl}},
        return_document=ReturnDocument.AFTER,
    )
    if offered is None:
        raise AssignmentError(f"assignment is {a['status']}, not proposed")

    # One live assignment per request: anything else proposed/offered for it is replaced (silent).
    others = db.assignments.find(
        {"requestId": a["requestId"], "_id": {"$ne": assignment_id}, "status": {"$in": ["proposed", "offered"]}}
    )
    async for other in others:
        await db.assignments.update_one(
            {"_id": other["_id"], "status": other["status"]},
            {"$set": {"status": "replaced", "respondedAt": now}},
        )
        await _vehicle_status(db, other["vehicleId"])

    if req["status"] == "received":
        await rq.transition(db, a["requestId"], "approved", reason="dispatcher approved", by=by)

    await _vehicle_status(db, a["vehicleId"])
    await audit.log(db, "assignment_offered", "approved", assignmentId=assignment_id, by=by)
    return offered


async def accept(db: AsyncIOMotorDatabase, assignment_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Driver taps Accept. Atomic: only an `offered`, unexpired assignment can be accepted.

    Returns {"result": "accepted", "assignment": ...} or {"result": "changed"}.
    """
    now = now or utcnow()
    won = await db.assignments.find_one_and_update(
        {"_id": assignment_id, "status": "offered", "expiresAt": {"$gt": now}},
        {"$set": {"status": "accepted", "respondedAt": now}},
        return_document=ReturnDocument.AFTER,
    )
    if won is None:
        await audit.log(db, "stale_accept_rejected", "assignment changed", assignmentId=assignment_id)
        return {"result": "changed"}

    try:
        await rq.transition(
            db,
            won["requestId"],
            "driver_accepted",
            reason="driver accepted",
            by=won["vehicleId"],
            allowed_from={"approved", "reassigning"},
        )
    except rq.RequestError:
        # The request moved under us (closed, etc.). Undo the accept so nothing is promised.
        await db.assignments.update_one({"_id": assignment_id}, {"$set": {"status": "replaced"}})
        await audit.log(db, "stale_accept_rejected", "request changed", assignmentId=assignment_id)
        return {"result": "changed"}

    await callbacks.enqueue(db, won["requestId"], assignment_id, "driver_accepted")
    await _vehicle_status(db, won["vehicleId"])
    return {"result": "accepted", "assignment": won}


async def decline(db: AsyncIOMotorDatabase, assignment_id: str) -> dict[str, Any]:
    now = utcnow()
    a = await db.assignments.find_one_and_update(
        {"_id": assignment_id, "status": "offered"},
        {"$set": {"status": "declined", "respondedAt": now}},
        return_document=ReturnDocument.AFTER,
    )
    if a is None:
        current = await _get(db, assignment_id)
        raise AssignmentError(f"assignment is {current['status']}, not offered")
    await _settle_request_after_offer_closed(db, a["requestId"], "driver declined")
    await _vehicle_status(db, a["vehicleId"])
    await audit.log(db, "assignment_declined", "declined", assignmentId=assignment_id)
    return a


async def revoke(db: AsyncIOMotorDatabase, assignment_id: str, *, reason: str) -> dict[str, Any]:
    """An accepted pickup can't happen (driver cancels / no route in time). The resident is told.

    Only this pickup is revoked; the driver's other accepted stops stay as they were.
    """
    now = utcnow()
    a = await db.assignments.find_one_and_update(
        {"_id": assignment_id, "status": "accepted"},
        {"$set": {"status": "revoked", "respondedAt": now}},
        return_document=ReturnDocument.AFTER,
    )
    if a is None:
        current = await _get(db, assignment_id)
        raise AssignmentError(f"assignment is {current['status']}, not accepted")

    await rq.transition(db, a["requestId"], "reassigning", reason=reason, allowed_from={"driver_accepted", "en_route"})
    await callbacks.enqueue(db, a["requestId"], assignment_id, "reassigning")
    await _vehicle_status(db, a["vehicleId"])
    await audit.log(db, "assignment_revoked", reason, assignmentId=assignment_id)
    return a


async def withdraw(db: AsyncIOMotorDatabase, assignment_id: str, *, reason: str) -> dict[str, Any]:
    """The plan can't keep an offer the driver hasn't accepted yet (e.g. a closure cut it off).

    Silent, like `replaced`: nothing was promised to the resident. A late Accept tap gets "changed".
    """
    now = utcnow()
    a = await db.assignments.find_one_and_update(
        {"_id": assignment_id, "status": "offered"},
        {"$set": {"status": "replaced", "respondedAt": now}},
        return_document=ReturnDocument.AFTER,
    )
    if a is None:
        current = await _get(db, assignment_id)
        raise AssignmentError(f"assignment is {current['status']}, not offered")
    await _settle_request_after_offer_closed(db, a["requestId"], reason)
    await _vehicle_status(db, a["vehicleId"])
    await audit.log(db, "assignment_withdrawn", reason, assignmentId=assignment_id)
    return a


async def expire_offers(db: AsyncIOMotorDatabase, *, now: datetime | None = None) -> int:
    """Offers expire 2 minutes after offeredAt; the request goes silently back to received."""
    now = now or utcnow()
    n = 0
    async for a in db.assignments.find({"status": "offered", "expiresAt": {"$lte": now}}):
        res = await db.assignments.update_one(
            {"_id": a["_id"], "status": "offered"}, {"$set": {"status": "expired", "respondedAt": now}}
        )
        if res.modified_count:
            n += 1
            await _settle_request_after_offer_closed(db, a["requestId"], "offer expired")
            await _vehicle_status(db, a["vehicleId"])
            await audit.log(db, "assignment_expired", "expired", assignmentId=a["_id"])
    return n


# ── ride progress (after accept) ──────────────────────────────────────────────
PROGRESS_STEPS = ("en_route", "arrived", "completed")


async def progress(
    db: AsyncIOMotorDatabase,
    assignment_id: str,
    step: str,
    *,
    eta_minutes: float | None = None,
    by: str = "driver",
) -> dict[str, Any]:
    """The driver's run moves on. Only an `accepted` assignment reports progress.

    - `en_route` + ETA: this pickup is the driver's next stop. The first report moves the request
      driver_accepted → en_route and queues an en_route callback. Later reports only update the ETA,
      and queue another callback only when it moved by more than 3 minutes since the last one announced.
    - `arrived`: driver is at the door ("Picked up"). Request → arrived, resident is called.
    - `completed`: dropped at the shelter. Request → closed, assignment → completed. No callback.
    """
    if step not in PROGRESS_STEPS:
        raise AssignmentError(f"step must be one of {', '.join(PROGRESS_STEPS)}", status_code=422)
    a = await _get(db, assignment_id)
    if a["status"] != "accepted":
        raise AssignmentError(f"assignment is {a['status']}, not accepted")
    request_id = a["requestId"]

    if step == "en_route":
        if eta_minutes is None or eta_minutes < 0:
            raise AssignmentError("en_route needs etaMinutes ≥ 0", status_code=422)
        req = await db.requests.find_one({"_id": request_id})
        if req is None or req["status"] not in ("driver_accepted", "en_route"):
            raise AssignmentError(f"request is {req and req['status']}, can't be en route")
        if req["status"] == "driver_accepted":
            try:
                await rq.transition(db, request_id, "en_route", reason="driver on the way", by=by)
            except (rq.ConcurrentTransition, rq.IllegalTransition):
                # Two first reports raced. Fine if the other one moved it to en_route.
                if (await db.requests.find_one({"_id": request_id}))["status"] != "en_route":
                    raise
        await _announce_eta(db, a, eta_minutes)

    elif step == "arrived":
        await rq.transition(
            db, request_id, "arrived", reason="driver at the door", by=by, allowed_from={"driver_accepted", "en_route"}
        )
        await callbacks.enqueue(db, request_id, assignment_id, "arrived")

    else:  # completed
        await rq.transition(db, request_id, "closed", reason="dropped at shelter", by=by, allowed_from={"arrived"})
        now = utcnow()
        await db.assignments.update_one(
            {"_id": assignment_id, "status": "accepted"}, {"$set": {"status": "completed", "completedAt": now}}
        )
        # The household is out: the console's "safe" count and the map read this (household.updated).
        req = await db.requests.find_one({"_id": request_id}, {"householdId": 1})
        if req and req.get("householdId"):
            await db.households.update_one({"_id": req["householdId"]}, {"$set": {"safeAt": now}})
        await _vehicle_status(db, a["vehicleId"])

    await audit.log(db, "assignment_progress", step, assignmentId=assignment_id, etaMinutes=eta_minutes, by=by)
    return await _get(db, assignment_id)


async def _announce_eta(db: AsyncIOMotorDatabase, a: dict[str, Any], eta: float) -> None:
    """Store the ETA. Queue an en_route callback if it's the first one or it moved > 3 min.

    The announcement counter moves by compare-and-set, so two racing reports announce once.
    """
    seq = a.get("announcedEtaSeq", 0)
    if not callbacks.eta_worth_announcing(a.get("announcedEtaMinutes"), eta):
        await db.assignments.update_one({"_id": a["_id"]}, {"$set": {"etaMinutes": eta}})
        return
    won = await db.assignments.find_one_and_update(
        {"_id": a["_id"], "status": "accepted", "announcedEtaSeq": seq if seq else {"$in": [0, None]}},
        {"$set": {"etaMinutes": eta, "announcedEtaMinutes": eta, "announcedEtaSeq": seq + 1}},
        return_document=ReturnDocument.AFTER,
    )
    if won is None:  # someone else announced first; just keep the freshest ETA
        await db.assignments.update_one({"_id": a["_id"]}, {"$set": {"etaMinutes": eta}})
        return
    await callbacks.enqueue(db, a["requestId"], a["_id"], "en_route", seq=seq + 1, eta_minutes=eta)


# ── closing a request early ───────────────────────────────────────────────────
async def close_request(
    db: AsyncIOMotorDatabase, request_id: str, *, reason: str, by: str = "dispatcher"
) -> dict[str, Any]:
    """Close an open request that won't need a ride (resident left on their own, duplicate, ...).

    Proposed/offered assignments are replaced (silent). An accepted pickup is revoked so the driver
    drops that stop; the rest of the driver's run stays. The resident is NOT called: they told us,
    or there's no one to tell. Closing an already-closed request is a no-op.
    """
    req = await db.requests.find_one({"_id": request_id})
    if req is None:
        raise rq.RequestNotFound(request_id)
    if req["status"] == "closed":
        return req

    now = utcnow()
    touched: set[str] = set()
    async for a in db.assignments.find(
        {"requestId": request_id, "status": {"$in": ["proposed", "offered", "accepted"]}}
    ):
        new_status = "revoked" if a["status"] == "accepted" else "replaced"
        res = await db.assignments.update_one(
            {"_id": a["_id"], "status": a["status"]}, {"$set": {"status": new_status, "respondedAt": now}}
        )
        if res.modified_count:
            touched.add(a["vehicleId"])
            await audit.log(db, f"assignment_{new_status}", reason, assignmentId=a["_id"], by=by)

    closed = await rq.transition(db, request_id, "closed", reason=reason, by=by)
    for vehicle_id in touched:
        await _vehicle_status(db, vehicle_id)
    return closed
