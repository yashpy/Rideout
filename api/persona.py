"""The real person behind an address: who's attached to a house, and taking them off it.

A house becomes "real" when someone claims it on Try it (POST /calls/kiosk): it gets their phone number and
`simulated: false`, and it survives reseeds. `release()` undoes that: the house goes back to a simulated
stand-in, its open ride request is closed, live offers are withdrawn and queued callbacks are dropped, so
nobody calls that number about this house again.
"""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api import audit
from api import requests as rq
from api.core.util import utcnow

US_PHONE_LEN = 12  # +1 and 10 digits


def valid_phone(phone: str) -> bool:
    return phone.startswith("+1") and len(phone) == US_PHONE_LEN and phone[1:].isdigit()


def view(hh: dict[str, Any]) -> dict[str, Any]:
    return {
        "householdId": hh["_id"],
        "address": hh.get("address"),
        "phone": hh.get("phone"),
        "simulated": bool(hh.get("simulated")),
        "zoneId": hh.get("zoneId"),
        "role": hh.get("role"),
        "reach": hh.get("reach"),
        "language": hh.get("language"),
        "claimedAt": hh.get("kioskClaimedAt"),
        "location": hh.get("location"),
    }


async def release(db: AsyncIOMotorDatabase, household_id: str, *, reason: str) -> dict[str, Any] | None:
    """Take the person off this house. → the house as it is now, or None if there's no such house."""
    hh = await db.households.find_one({"_id": household_id})
    if hh is None:
        return None
    now = utcnow()
    closed = 0
    async for r in db.requests.find({"householdId": household_id, "status": {"$in": list(rq.OPEN_STATUSES)}}):
        # Offers and accepted runs for this person end quietly: there's nobody left to pick up.
        await db.assignments.update_many(
            {"requestId": r["_id"], "status": "proposed"}, {"$set": {"status": "replaced", "respondedAt": now}}
        )
        await db.assignments.update_many(
            {"requestId": r["_id"], "status": {"$in": ["offered", "accepted"]}},
            {"$set": {"status": "withdrawn", "reason": reason, "respondedAt": now}},
        )
        await rq.transition(db, r["_id"], "closed", reason=reason, by="persona")
        closed += 1
    skipped = await db.callbacks.update_many(
        {"householdId": household_id, "state": "queued"},
        {"$set": {"state": "skipped", "reason": reason, "updatedAt": now}},
    )
    # Callbacks may be keyed by request only: drop those too.
    req_ids = [r["_id"] async for r in db.requests.find({"householdId": household_id}, {"_id": 1})]
    skipped2 = await db.callbacks.update_many(
        {"requestId": {"$in": req_ids}, "state": "queued"},
        {"$set": {"state": "skipped", "reason": reason, "updatedAt": now}},
    )
    if hh.get("simulated") is False:
        await db.households.update_one(
            {"_id": household_id},
            {
                "$set": {
                    "simulated": True,
                    "phone": hh.get("standInPhone") or "",
                    "reach": "not_called",
                    "role": "unknown",
                    "record": {},
                    "corrections": [],
                    "dialAttempts": 0,
                    "nextAttemptAt": None,
                    "updatedAt": now,
                },
                "$unset": {"kioskClaimedAt": ""},
            },
        )
    await audit.log(
        db,
        "persona_released",
        f"{hh.get('address', household_id)}: {reason}",  # never the phone number
        householdId=household_id,
        requestsClosed=closed,
        callbacksSkipped=skipped.modified_count + skipped2.modified_count,
    )
    return await db.households.find_one({"_id": household_id})


async def release_other_houses(db: AsyncIOMotorDatabase, phone: str, keep: str) -> list[str]:
    """One house per phone number: when a number claims a new house, its earlier houses go back to stand-ins."""
    ids = [
        h["_id"]
        async for h in db.households.find({"phone": phone, "simulated": False, "_id": {"$ne": keep}}, {"_id": 1})
    ]
    for hid in ids:
        await release(db, hid, reason="this phone number moved to another house")
    return ids
