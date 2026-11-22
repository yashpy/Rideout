"""Test data factories."""

from datetime import timedelta

from api.core.util import new_id, utcnow

AUTH = {"Authorization": "Bearer test-token"}


# ── factories ─────────────────────────────────────────────────────────────────
async def make_household(db, **kw) -> dict:
    doc = {
        "_id": new_id("hh"),
        "address": "1225 N SR 89A, Sedona, AZ",
        "location": {"type": "Point", "coordinates": [-111.73, 34.93]},
        "zoneId": "zone_oak_creek_14",
        "phone": "+15550000000",
        "language": "en",
        "simulated": True,
        "record": {},
        "corrections": [],
        "reach": "not_called",
        "role": "unknown",
        **kw,
    }
    await db.households.insert_one(doc)
    return doc


async def make_request(db, status="received", **kw) -> dict:
    hh = await make_household(db)
    doc = {
        "_id": new_id("rq"),
        "householdId": hh["_id"],
        "status": status,
        "need": {"seats": 2, "wheelchair": 1, "stretcher": 0, "crew": 2, "lift": True},
        "deadlineAt": utcnow() + timedelta(minutes=30),
        "priority": 1.0,
        "escalation": None,
        "dupOf": None,
        "version": 1,
        "createdAt": utcnow(),
        "updatedAt": utcnow(),
        **kw,
    }
    await db.requests.insert_one(doc)
    return doc


async def make_vehicle(db, **kw) -> dict:
    doc = {
        "_id": new_id("vh"),
        "kind": "paratransit",
        "driverName": "Luis",
        "phone": "+15550000001",
        "capacity": {"seats": 4, "wheelchair": 1, "stretcher": 0},
        "crew": 2,
        "lift": True,
        "location": {"type": "Point", "coordinates": [-111.76, 34.87]},
        "status": "idle",
        "safety": {"state": "ok"},
        "simulated": True,
        **kw,
    }
    await db.vehicles.insert_one(doc)
    return doc


async def make_assignment(db, request_id, vehicle_id, status="proposed", **kw) -> dict:
    doc = {
        "_id": new_id("as"),
        "requestId": request_id,
        "vehicleId": vehicle_id,
        "planVersion": 1,
        "stopOrder": 0,
        "etaMinutes": 7.0,
        "status": status,
        **kw,
    }
    await db.assignments.insert_one(doc)
    return doc
