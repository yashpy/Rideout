"""/persona: the real person attached to an address (phone number), for operators only.

Phone numbers are private, so every route needs the internal token (Authorization: Bearer $INTERNAL_TOKEN)
and nothing here is shown in the web app.

GET    /persona                     real people: houses claimed on Try it + volunteer drivers
GET    /persona/{householdId}       the person and phone attached to one address (simulated or real)
PATCH  /persona/{householdId}       change the address and/or the phone number
DELETE /persona/{householdId}       take the person off the house: it goes back to a simulated stand-in,
                                    their ride request closes, offers end, queued callbacks are dropped
DELETE /persona/volunteers/{vehicleId}   remove a Try-it volunteer car (and any offers to it)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api import audit, persona
from api.core.auth import require_internal_token
from api.core.db import get_db
from api.core.util import utcnow

router = APIRouter(prefix="/persona", tags=["persona"], dependencies=[Depends(require_internal_token)])


@router.get("")
async def list_people(
    address: str | None = Query(default=None, description="case-insensitive part of the address"),
    phone: str | None = Query(default=None, description="exact E.164 number, e.g. +14805551234"),
    includeSimulated: bool = Query(default=False),
) -> dict:
    db = get_db()
    q: dict = {} if includeSimulated else {"simulated": False}
    if phone:
        q["phone"] = phone
    if address:
        q["address"] = {"$regex": address.replace("\\", "\\\\").replace(".", "\\."), "$options": "i"}
    people = [persona.view(h) async for h in db.households.find(q).sort("address", 1).limit(500)]
    vq: dict = {"kind": "volunteer"}
    if phone:
        vq["phone"] = phone
    volunteers = [
        {
            "vehicleId": v["_id"],
            "driverName": v.get("driverName"),
            "phone": v.get("phone"),
            "homeId": v.get("homeId"),
            "location": v.get("location"),
        }
        async for v in db.vehicles.find(vq)
    ]
    return {"people": people, "volunteers": volunteers}


@router.get("/{household_id}")
async def get_person(household_id: str) -> dict:
    hh = await get_db().households.find_one({"_id": household_id})
    if hh is None:
        raise HTTPException(404, "household not found")
    return persona.view(hh)


class PersonaPatch(BaseModel):
    address: str | None = None
    phone: str | None = None


@router.patch("/{household_id}")
async def edit_person(household_id: str, body: PersonaPatch) -> dict:
    db = get_db()
    hh = await db.households.find_one({"_id": household_id})
    if hh is None:
        raise HTTPException(404, "household not found")
    changes: dict = {}
    if body.address is not None:
        addr = body.address.strip()
        if not addr or len(addr) > 200:
            raise HTTPException(422, "address must be 1–200 characters")
        changes["address"] = addr
    if body.phone is not None:
        if not persona.valid_phone(body.phone):
            raise HTTPException(422, "phone must be a US number in E.164 (+1 and 10 digits)")
        changes["phone"] = body.phone
        if hh.get("simulated") is not False:
            raise HTTPException(409, "this house is simulated; claim it on Try it before giving it a real phone")
    if not changes:
        raise HTTPException(422, "nothing to change: send address and/or phone")
    await db.households.update_one({"_id": household_id}, {"$set": {**changes, "updatedAt": utcnow()}})
    if "phone" in changes:
        await persona.release_other_houses(db, changes["phone"], keep=household_id)
    await audit.log(db, "persona_edited", ", ".join(sorted(changes)), householdId=household_id)  # no values
    return persona.view(await db.households.find_one({"_id": household_id}))


@router.delete("/{household_id}")
async def remove_person(household_id: str) -> dict:
    hh = await persona.release(get_db(), household_id, reason="person removed by an operator")
    if hh is None:
        raise HTTPException(404, "household not found")
    return {"removed": True, **persona.view(hh)}


@router.delete("/volunteers/{vehicle_id}")
async def remove_volunteer(vehicle_id: str) -> dict:
    db = get_db()
    v = await db.vehicles.find_one({"_id": vehicle_id, "kind": "volunteer"})
    if v is None:
        raise HTTPException(404, "volunteer car not found")
    now = utcnow()
    await db.assignments.update_many(
        {"vehicleId": vehicle_id, "status": "proposed"}, {"$set": {"status": "replaced", "respondedAt": now}}
    )
    await db.assignments.update_many(
        {"vehicleId": vehicle_id, "status": "offered"},
        {"$set": {"status": "withdrawn", "reason": "volunteer removed", "respondedAt": now}},
    )
    accepted = [a async for a in db.assignments.find({"vehicleId": vehicle_id, "status": "accepted"})]
    from api import assignments as asg  # the rider is told and gets another driver

    for a in accepted:
        try:
            await asg.revoke(db, a["_id"], reason="volunteer driver removed")
        except Exception:  # already moved on
            pass
    await db.vehicles.delete_one({"_id": vehicle_id})
    await audit.log(db, "volunteer_removed", str(v.get("driverName", vehicle_id)), vehicleId=vehicle_id)
    return {"removed": True, "vehicleId": vehicle_id, "revoked": len(accepted)}
