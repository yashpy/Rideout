"""The ride-request status machine. THE ONLY place a request's status changes.

Legal moves (CONTRACT §1, ARCHITECTURE §7.1):

    received ──approve──► approved ──driver accepts──► driver_accepted ──► en_route ──► arrived ──► closed
       ▲                     │                                │    └────────(at the door)───►┘
       └ decline / expire / ─┘                 no route in time / driver cancels
         replaced (silent)                                    ▼
                                                 reassigning ──new accept──► driver_accepted

    Any open status ──► closed  (resident left on their own, duplicate, or dispatcher closes).
    Only api.assignments.close_request() takes that exit: it also settles the request's offers.

Anything else raises IllegalTransition. Every move (and every rejected move) goes to the audit log.
Moves are compare-and-set on (status, version), so two writers can't both win.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from api import audit
from api.core.util import new_id, utcnow
from api.models import Need, RequestStatus

LEGAL: dict[str, frozenset[str]] = {
    "received": frozenset({"approved", "closed"}),
    "approved": frozenset({"received", "driver_accepted", "closed"}),
    "driver_accepted": frozenset({"en_route", "reassigning", "arrived", "closed"}),
    "en_route": frozenset({"reassigning", "arrived", "closed"}),
    "reassigning": frozenset({"driver_accepted", "closed"}),
    "arrived": frozenset({"closed"}),
    "closed": frozenset(),
}

OPEN_STATUSES = frozenset(LEGAL) - {"closed"}


class RequestError(Exception):
    pass


class RequestNotFound(RequestError):
    pass


class IllegalTransition(RequestError):
    def __init__(self, request_id: str, frm: str, to: str):
        super().__init__(f"{request_id}: {frm} → {to} is not a legal move")
        self.request_id, self.frm, self.to = request_id, frm, to


class ConcurrentTransition(RequestError):
    """Someone else moved the request between our read and our write. Re-read and decide again."""


def is_legal(frm: str, to: str) -> bool:
    return to in LEGAL.get(frm, frozenset())


async def transition(
    db: AsyncIOMotorDatabase,
    request_id: str,
    to: RequestStatus,
    *,
    reason: str = "",
    by: str = "system",
    allowed_from: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Move a request to `to`. Optionally require the current status to be in `allowed_from`."""
    doc = await db.requests.find_one({"_id": request_id})
    if doc is None:
        raise RequestNotFound(request_id)
    frm = doc["status"]

    if not is_legal(frm, to) or (allowed_from is not None and frm not in allowed_from):
        await audit.log(db, "illegal_transition", f"{frm} → {to} rejected", requestId=request_id, by=by, reason=reason)
        raise IllegalTransition(request_id, frm, to)

    now = utcnow()
    updated = await db.requests.find_one_and_update(
        {"_id": request_id, "status": frm, "version": doc.get("version", 1)},
        {"$set": {"status": to, "updatedAt": now}, "$inc": {"version": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise ConcurrentTransition(request_id)

    await audit.log(
        db, "request_transition", f"{frm} → {to}", requestId=request_id, frm=frm, to=to, by=by, reason=reason
    )
    return updated


async def upsert_for_household(
    db: AsyncIOMotorDatabase,
    household_id: str,
    *,
    need: Need | dict | None = None,
    deadline_at=None,
    priority: float | None = None,
) -> dict[str, Any]:
    """Create the household's open request, or update its need/deadline/priority. Never touches status."""
    now = utcnow()
    fields: dict[str, Any] = {"updatedAt": now}
    if need is not None:
        fields["need"] = need.model_dump() if isinstance(need, Need) else Need(**need).model_dump()
    if deadline_at is not None:
        fields["deadlineAt"] = deadline_at
    if priority is not None:
        fields["priority"] = priority

    existing = await db.requests.find_one({"householdId": household_id, "status": {"$in": list(OPEN_STATUSES)}})
    if existing:
        return await db.requests.find_one_and_update(
            {"_id": existing["_id"]},
            {"$set": fields, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
        )

    doc = {
        "_id": new_id("rq"),
        "householdId": household_id,
        "status": "received",
        "need": fields.get("need", Need().model_dump()),
        "deadlineAt": fields.get("deadlineAt"),
        "priority": fields.get("priority", 0.0),
        "escalation": None,
        "dupOf": None,
        "version": 1,
        "createdAt": now,
        "updatedAt": now,
    }
    await db.requests.insert_one(doc)
    await audit.log(db, "request_created", "received", requestId=doc["_id"], householdId=household_id)
    return doc


async def bulk_create_received(db: AsyncIOMotorDatabase, items: list[dict[str, Any]]) -> int:
    """Create many households' first requests in one write (the simulated census at city scale).

    `items`: {householdId, need, deadlineAt, priority}. Households that already have an open request are
    skipped (the per-household path, `upsert_for_household`, updates those). New requests start `received`,
    like any other; one audit entry per batch. → requests created."""
    if not items:
        return 0
    open_for = {
        r["householdId"]
        async for r in db.requests.find(
            {"householdId": {"$in": [i["householdId"] for i in items]}, "status": {"$in": list(OPEN_STATUSES)}},
            {"householdId": 1},
        )
    }
    now = utcnow()
    docs = [
        {
            "_id": new_id("rq"),
            "householdId": i["householdId"],
            "status": "received",
            "need": Need(**(i.get("need") or {})).model_dump(),
            "deadlineAt": i.get("deadlineAt"),
            "priority": float(i.get("priority") or 0.0),
            "escalation": None,
            "dupOf": None,
            "version": 1,
            "createdAt": now,
            "updatedAt": now,
        }
        for i in items
        if i["householdId"] not in open_for
    ]
    if docs:
        await db.requests.insert_many(docs, ordered=False)
        await audit.log(db, "requests_created", "received", count=len(docs), source="census")
    return len(docs)
