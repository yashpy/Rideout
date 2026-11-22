"""Calls: the call floor reads and POST /calls/dial."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import DESCENDING

from api import audit, persona
from api import requests as rq
from api.agent import dialer
from api.core.db import get_db
from api.core.util import utcnow
from api.routes._util import out, place_visitor

router = APIRouter(prefix="/calls", tags=["calls"])

UNANSWERED = ("no_answer", "voicemail", "failed")
HOUSEHOLD_FIELDS = ("address", "simulated", "reach", "role", "record", "corrections", "language", "zoneId")


def _summary(call: dict[str, Any], hh: dict[str, Any] | None) -> dict[str, Any]:
    turns = call.get("turns") or []
    agent = call.get("agent") or {}
    last = turns[-1] if turns else {}
    return {
        "id": call["_id"],
        "householdId": call.get("householdId"),
        "direction": call.get("direction"),
        "language": call.get("language"),
        "startedAt": call.get("startedAt"),
        "endedAt": call.get("endedAt"),
        "updatedAt": call.get("updatedAt") or call.get("startedAt"),
        "outcome": call.get("outcome"),
        "stage": agent.get("stage"),
        "done": bool(agent.get("done") or call.get("endedAt") or call.get("outcome") in UNANSWERED),
        "escalations": agent.get("escalations") or [],
        "turnCount": len(turns),
        "lastText": last.get("text"),
        "lastSpeaker": last.get("speaker"),
        "household": {"id": hh["_id"], **{k: hh.get(k) for k in HOUSEHOLD_FIELDS}} if hh else None,
    }


@router.get("")
async def list_calls(limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    """Most recently active calls first, with a household summary. For the /calls list."""
    db = get_db()
    calls = [c async for c in db.calls.find({}).sort("updatedAt", DESCENDING).limit(limit)]
    ids = list({c.get("householdId") for c in calls})
    hhs = {h["_id"]: h async for h in db.households.find({"_id": {"$in": ids}})}
    return [_summary(c, hhs.get(c.get("householdId"))) for c in calls]


@router.get("/{call_id}")
async def get_call(call_id: str) -> dict:
    """One call: summary + every turn + the household's open request."""
    db = get_db()
    call = await db.calls.find_one({"_id": call_id})
    if call is None:
        raise HTTPException(404, "call not found")
    hh = await db.households.find_one({"_id": call.get("householdId")})
    req = await db.requests.find_one(
        {"householdId": call.get("householdId"), "status": {"$in": list(rq.OPEN_STATUSES)}}
    )
    return {**_summary(call, hh), "turns": call.get("turns") or [], "request": out(req)}


class KioskBody(BaseModel):
    householdId: str
    phone: str = Field(pattern=r"^\+1\d{10}$", description="US number in E.164, e.g. +14805551234")
    # Optional: the visitor's real address (geocoded in the browser); the house moves there.
    address: str | None = Field(default=None, max_length=160)
    lon: float | None = None
    lat: float | None = None


KIOSK_PER_MINUTE = 6  # the kiosk is open to anyone; don't let it become a dialer for strangers


@router.post("/kiosk")
async def kiosk(body: KioskBody) -> dict:
    """Kiosk: this house becomes the visitor's real-phone household, then we call them.

    The house starts fresh (no record, not reached) so the visitor's own answers fill it. Its stand-in
    request, if any, is closed while nobody has accepted it. → {callId, householdId, address}
    """
    db = get_db()
    now = utcnow()
    try:
        dialer._check_elevenlabs()  # fail before touching the house if there's no phone line
    except dialer.DialError as e:
        raise HTTPException(e.status, str(e)) from e
    recent = await db.auditLog.count_documents({"kind": "kiosk_claim", "at": {"$gt": now - timedelta(minutes=1)}})
    if recent >= KIOSK_PER_MINUTE:
        raise HTTPException(429, "the kiosk is busy; try again in a minute")
    hh = await db.households.find_one({"_id": body.householdId})
    if hh is None:
        raise HTTPException(404, "household not found")
    if hh.get("reach") in dialer.BUSY:
        raise HTTPException(409, "this house is on a call right now; pick another one")
    typed = bool(body.address)
    hh = await place_visitor(db, hh, body.address, body.lon, body.lat)
    req = await db.requests.find_one({"householdId": hh["_id"], "status": {"$in": list(rq.OPEN_STATUSES)}})
    if req is not None:
        if req["status"] != "received":
            raise HTTPException(409, "this house already has a driver on the way; pick another one")
        await rq.transition(db, req["_id"], "closed", reason="kiosk: a visitor plays this home", by="kiosk")
    await db.households.update_one(
        {"_id": hh["_id"]},
        {
            "$set": {
                "phone": body.phone,
                "simulated": False,
                "record": {},
                "corrections": [],
                "reach": "not_called",
                "role": "unknown",
                "dialAttempts": 0,
                "nextAttemptAt": None,
                "kioskClaimedAt": now,
                "updatedAt": now,
            }
        },
    )
    if hh.get("simulated") and "standInPhone" not in hh:
        await db.households.update_one({"_id": hh["_id"]}, {"$set": {"standInPhone": hh.get("phone")}})
    # No phone number in logs, and no typed (real) address either.
    await audit.log(db, "kiosk_claim", "visitor address" if typed else hh.get("address", ""), householdId=hh["_id"])
    # One house per phone number: earlier houses this number claimed go back to stand-ins (no more calls).
    await persona.release_other_houses(db, body.phone, keep=hh["_id"])
    # The visitor asked to be called: real calls on again (a drive test turns them off).
    await db.simControl.update_one({"_id": "sim"}, {"$set": {"standIns.realCalls": True}}, upsert=True)
    try:
        call_id = await dialer.dial(db, hh["_id"])
    except dialer.DialError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"callId": call_id, "householdId": hh["_id"], "address": hh.get("address")}


class DialBody(BaseModel):
    householdId: str


@router.post("/dial")
async def dial(body: DialBody) -> dict:
    """→ {callId}. Real call via ElevenLabs for real phones, stand-in for simulated homes.
    404 unknown household · 409 already ringing / in a call · 503 ElevenLabs not configured · 502 ElevenLabs refused."""
    try:
        call_id = await dialer.dial(get_db(), body.householdId)
    except dialer.DialError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"callId": call_id}
