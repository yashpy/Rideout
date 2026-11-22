"""The callback queue: phone calls we owe a resident because their ride status changed.

Core rules only. The worker that actually places the calls is `api/agent/callbacks.py`:
it picks up `state: queued` documents and marks them `placed → played | unanswered`.

`key = requestId:assignmentId:announcedStatus` has a unique index, so enqueueing twice is a no-op.
`en_route` can be announced more than once per assignment (each ETA change > 3 min), so its key ends
with the announcement number: `requestId:assignmentId:en_route:<n>`. A counter, not the ETA minute,
because an ETA that goes 10 → 14 → 10 would otherwise collide with its own first announcement.
Approval NEVER triggers a callback (CONTRACT §1). Only the statuses below do.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from api import audit
from api.core.util import new_id, utcnow

ANNOUNCED_STATUSES = frozenset({"driver_accepted", "reassigning", "en_route", "arrived"})

# An en_route ETA is re-announced only when it moved by more than this many minutes.
ETA_ANNOUNCE_DELTA_MIN = 3.0


def eta_worth_announcing(last_announced: float | None, new_eta: float) -> bool:
    return last_announced is None or abs(new_eta - last_announced) > ETA_ANNOUNCE_DELTA_MIN


def callback_key(request_id: str, assignment_id: str, status: str, seq: int | None = None) -> str:
    key = f"{request_id}:{assignment_id}:{status}"
    return f"{key}:{seq}" if status == "en_route" and seq is not None else key


async def enqueue(
    db: AsyncIOMotorDatabase,
    request_id: str,
    assignment_id: str,
    status: str,
    *,
    seq: int | None = None,
    eta_minutes: float | None = None,
) -> dict[str, Any] | None:
    """Queue a callback. Returns the new doc, or None if this exact callback was already queued.

    `seq` is the en_route announcement number (required for en_route). `eta_minutes` is the ETA
    that triggered it, for the log; the worker reads the live ETA from the assignment when it dials.
    """
    if status not in ANNOUNCED_STATUSES:
        raise ValueError(f"status {status!r} never triggers a callback")
    if status == "en_route" and seq is None:
        raise ValueError("en_route callbacks need seq (the announcement number)")

    key = callback_key(request_id, assignment_id, status, seq)
    doc = {
        "_id": new_id("cb"),
        "requestId": request_id,
        "assignmentId": assignment_id,
        "announcedStatus": status,
        "etaMinutes": eta_minutes,
        "state": "queued",
        "key": key,
        "createdAt": utcnow(),
    }
    try:
        await db.callbacks.insert_one(doc)
    except DuplicateKeyError:
        await audit.log(db, "duplicate_callback_ignored", key, requestId=request_id, assignmentId=assignment_id)
        return None
    await audit.log(db, "callback_queued", key, requestId=request_id, assignmentId=assignment_id)
    return doc
