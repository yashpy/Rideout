"""Vehicles: list, a driver's run, phone presence, position, safety, Try-it volunteers.

A phone that has the driver app open (presence or position in the last PHONE_FRESH_S) owns its vehicle:
stand-in drivers (api/sim/drivers.py) leave it alone.
"""

import hashlib
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api import audit
from api.core.db import get_db
from api.core.util import new_id, utcnow
from api.routes._util import out, place_visitor
from api.sim import world

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

PHONE_FRESH_S = 120
MAX_VOLUNTEERS = 25  # Try-it volunteer cars at once (a reseed clears them)
MAX_GPS_OFF_ROAD_M = 25_000  # farther than this from the scenario's roads = not in it (demo phone elsewhere)


@router.get("")
async def list_vehicles() -> list[dict]:
    return [out(v) async for v in get_db().vehicles.find({})]


async def _with_home(db, a: dict[str, Any]) -> dict[str, Any]:
    req = await db.requests.find_one({"_id": a["requestId"]}) or {}
    hh = await db.households.find_one({"_id": req.get("householdId")}) or {}
    return {
        **out(a),
        "request": {
            "id": req.get("_id"),
            "status": req.get("status"),
            "need": req.get("need"),
            "deadlineAt": req.get("deadlineAt"),
            "escalation": req.get("escalation"),
        },
        "household": {
            "id": hh.get("_id"),
            "address": hh.get("address"),
            "location": hh.get("location"),
            "language": hh.get("language"),
            "simulated": hh.get("simulated"),
        },
    }


@router.get("/{vehicle_id}/run")
async def run(vehicle_id: str) -> dict:
    """What the driver app shows: live offers (with countdown) and the accepted run, in stop order."""
    db = get_db()
    v = await db.vehicles.find_one({"_id": vehicle_id})
    if v is None:
        raise HTTPException(404, "vehicle not found")
    offers = [
        await _with_home(db, a)
        async for a in db.assignments.find({"vehicleId": vehicle_id, "status": "offered"}).sort("expiresAt", 1)
    ]
    stops = [
        await _with_home(db, a)
        async for a in db.assignments.find({"vehicleId": vehicle_id, "status": "accepted"}).sort("stopOrder", 1)
    ]
    shelters = [out(s) async for s in db.shelters.find({})]
    return {
        "vehicle": out(v),
        "offers": offers,
        "run": stops,
        "shelters": shelters,
        "seats": seats_summary(v, stops, offers),
        "now": utcnow(),
    }


def seats_summary(v: dict, run: list[dict], offers: list[dict]) -> dict:
    """Seats and wheelchair spaces on this trip: taken (on board or still to pick up before the next shelter
    drop-off), held by live offers, and left. `laterTrips` = accepted riders after that drop-off.
    The planner fills a vehicle up to this before giving riders to the next one."""
    cap = v.get("capacity") or {}

    def total(rows: list[dict], key: str, default: int) -> int:
        return sum(int(((r.get("request") or {}).get("need") or {}).get(key) or default) for r in rows)

    seats, wc, st = int(cap.get("seats", 4)), int(cap.get("wheelchair", 0)), int(cap.get("stretcher", 0))

    def need(r: dict, key: str, default: int) -> int:
        return int(((r.get("request") or {}).get("need") or {}).get(key) or default)

    # This trip only: riders on board, then the next pickups in stop order until one no longer fits (the
    # planner sends the vehicle to a shelter there and the rest ride on a later trip).
    onboard = [r for r in run if (r.get("request") or {}).get("status") == "arrived"]
    trip = list(onboard)
    for r in run:
        if r in onboard:
            continue
        rows = [*trip, r]
        if (
            sum(need(x, "seats", 1) for x in rows) > seats
            or sum(need(x, "wheelchair", 0) for x in rows) > wc
            or sum(need(x, "stretcher", 0) for x in rows) > st
        ):
            break
        trip.append(r)
    used, used_wc = total(trip, "seats", 1), total(trip, "wheelchair", 0)
    held, held_wc = total(offers, "seats", 1), total(offers, "wheelchair", 0)
    return {
        "capacity": seats,
        "wheelchair": wc,
        "used": used,
        "usedWheelchair": used_wc,
        "offered": held,
        "offeredWheelchair": held_wc,
        "left": max(0, seats - used),
        "leftWheelchair": max(0, wc - used_wc),
        "leftIfAllAccepted": max(0, seats - used - held),
        "onBoard": total(onboard, "seats", 1),
        "laterTrips": len(run) - len(trip),
    }


@router.post("/{vehicle_id}/presence")
async def presence(vehicle_id: str) -> dict:
    """The driver app is open on a phone (sent every ~20 s). Stand-in drivers skip this vehicle."""
    res = await get_db().vehicles.update_one({"_id": vehicle_id}, {"$set": {"phoneSeenAt": utcnow()}})
    if not res.matched_count:
        raise HTTPException(404, "vehicle not found")
    return {"ok": True}


class PositionBody(BaseModel):
    lon: float
    lat: float
    heading: float = 0
    speedMps: float = 0


@router.post("/{vehicle_id}/position")
async def position(vehicle_id: str, body: PositionBody) -> dict:
    """A phone's GPS fix. Fixes far from the scenario's road (a demo phone in Tempe driving "Luis" in Oak
    Creek Canyon) are not applied: they would drag the van 150 km away and the planner would give its
    pickups to someone else. The phone still owns the vehicle (phoneSeenAt)."""
    # TODO: also append to Tiger Data `vehicle_positions`.
    if world.network().off_area_m((body.lon, body.lat)) > MAX_GPS_OFF_ROAD_M:
        res = await get_db().vehicles.update_one({"_id": vehicle_id}, {"$set": {"phoneSeenAt": utcnow()}})
        if not res.matched_count:
            raise HTTPException(404, "vehicle not found")
        return {"ok": True, "applied": False, "reason": "outside the scenario area"}
    res = await get_db().vehicles.update_one(
        {"_id": vehicle_id},
        {
            "$set": {
                "location": {"type": "Point", "coordinates": [body.lon, body.lat]},
                "heading": body.heading,
                "speedMps": body.speedMps,
                "lastSeenAt": utcnow(),
                "phoneSeenAt": utcnow(),  # only phones post positions over HTTP
            }
        },
    )
    if not res.matched_count:
        raise HTTPException(404, "vehicle not found")
    return {"ok": True, "applied": True}


class SafetyBody(BaseModel):
    state: Literal["ok", "check", "man_down", "sos"]
    lon: float | None = None
    lat: float | None = None


@router.post("/{vehicle_id}/safety")
async def safety(vehicle_id: str, body: SafetyBody) -> dict:
    db = get_db()
    doc: dict[str, Any] = {"state": body.state, "at": utcnow()}
    if body.lon is not None and body.lat is not None:
        doc["location"] = {"type": "Point", "coordinates": [body.lon, body.lat]}
    res = await db.vehicles.update_one({"_id": vehicle_id}, {"$set": {"safety": doc}})
    if not res.matched_count:
        raise HTTPException(404, "vehicle not found")
    if body.state in ("man_down", "sos"):
        await audit.log(db, "driver_safety", body.state, vehicleId=vehicle_id)
    return {"ok": True}


class VolunteerBody(BaseModel):
    householdId: str
    phone: str  # E.164, +1XXXXXXXXXX
    name: str | None = None
    address: str | None = Field(default=None, max_length=160)  # the visitor's real address (optional)
    lon: float | None = None
    lat: float | None = None


@router.post("/volunteer")
async def volunteer(body: VolunteerBody) -> dict:
    """Try it → "I can drive": a neighbor car parked at the chosen house, driven from the driver app.

    One car per phone number (asking again moves it to the new house). Real, not simulated: stand-in
    drivers leave it alone, so offers wait for this person (and expire to the next driver if ignored)."""
    db = get_db()
    if not body.phone.startswith("+1") or len(body.phone) != 12 or not body.phone[1:].isdigit():
        raise HTTPException(422, "phone must be a US number (+1 and 10 digits)")
    hh = await db.households.find_one({"_id": body.householdId})
    if hh is None or not (hh.get("location") or {}).get("coordinates"):
        raise HTTPException(404, "household not found")
    typed = bool(body.address)
    hh = await place_visitor(db, hh, body.address, body.lon, body.lat)
    phone_key = hashlib.sha256(body.phone.encode()).hexdigest()[:12]
    now = utcnow()
    name = (body.name or "").strip()[:30] or f"You (…{body.phone[-4:]})"
    mine = await db.vehicles.find_one({"kind": "volunteer", "phoneKey": phone_key})
    if mine is None and await db.vehicles.count_documents({"kind": "volunteer"}) >= MAX_VOLUNTEERS:
        raise HTTPException(429, "enough volunteer drivers for now; try again after the next reseed")
    vid = mine["_id"] if mine else new_id("vh_vol")
    await db.vehicles.update_one(
        {"_id": vid},
        {
            "$set": {
                "kind": "volunteer",
                "driverName": name,
                "phone": body.phone,
                "phoneKey": phone_key,
                "capacity": {"seats": 3, "wheelchair": 0, "stretcher": 0},
                "crew": 1,
                "lift": False,
                "location": hh["location"],
                "homeId": hh["_id"],
                "heading": 0,
                "speedMps": 0,
                "status": "idle",
                "safety": {"state": "ok"},
                "simulated": False,
                "lastSeenAt": now,
            }
        },
        upsert=True,
    )
    where = "their own address" if typed else hh.get("address", hh["_id"])
    await audit.log(db, "volunteer_driver", f"{name} can drive from {where}", vehicleId=vid)
    return {"vehicleId": vid, "driverName": name, "address": hh.get("address"), "driverUrl": f"/driver?v={vid}"}
