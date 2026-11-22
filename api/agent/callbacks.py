"""Callback worker: phone the resident when their ride status changes.

Core (api/callbacks.py) queues a callback on driver_accepted, reassigning, en_route (each ETA change
> 3 min) and arrived. This worker picks up `state: queued`, calls the household (ElevenLabs for real
phones, a stand-in for simulated homes) and the agent opens the call with the status template.

  queued → placed → played        the resident picked up and heard the status (set by session.start)
                  → queued again  no answer: one retry after RETRY_AFTER_S
                  → unanswered    no answer twice
  queued → skipped                the news is stale: the request moved on, or a newer ETA is queued
  queued → played (via in_call)   the resident was already on a call and heard it there

Every sentence the resident hears still comes from templates.py, using the request's status at the
moment the call connects, so a stale callback can never announce an old ETA.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from api import audit
from api.agent import dialer, standin
from api.core.config import get_settings
from api.core.util import aware, new_id, utcnow

log = logging.getLogger(__name__)

RETRY_AFTER_S = 60
MAX_ATTEMPTS = 2
DEFER_S = 10  # resident is on another call right now; look again shortly
ACTIVE_CALL_S = 120  # a call doc touched this recently and not ended counts as "on a call"

_tasks: dict[str, asyncio.Task] = {}


async def drain() -> None:
    while pending := [t for t in _tasks.values() if not t.done()]:
        await asyncio.gather(*pending, return_exceptions=True)


# ── state changes ─────────────────────────────────────────────────────────────


async def _skip(db: AsyncIOMotorDatabase, cb: dict[str, Any], reason: str, now: datetime) -> str:
    await db.callbacks.update_one(
        {"_id": cb["_id"], "state": "queued"}, {"$set": {"state": "skipped", "reason": reason, "updatedAt": now}}
    )
    await audit.log(db, "callback_skipped", reason, callbackId=cb["_id"], requestId=cb["requestId"])
    return "skipped"


async def _defer(db: AsyncIOMotorDatabase, cb: dict[str, Any], seconds: float, now: datetime) -> str:
    await db.callbacks.update_one(
        {"_id": cb["_id"], "state": "queued"}, {"$set": {"notBefore": now + timedelta(seconds=seconds)}}
    )
    return "deferred"


async def unanswered(db: AsyncIOMotorDatabase, cb_id: str, call_id: str | None, *, now: datetime | None = None) -> str:
    """No answer: retry once, then give up. Returns the new state."""
    now = now or utcnow()
    cb = await db.callbacks.find_one({"_id": cb_id}) or {}
    retry = int(cb.get("attempts") or 1) < MAX_ATTEMPTS
    state = "queued" if retry else "unanswered"
    update: dict[str, Any] = {"state": state, "updatedAt": now}
    if retry:
        update["notBefore"] = now + timedelta(seconds=RETRY_AFTER_S)
    await db.callbacks.update_one({"_id": cb_id, "state": "placed"}, {"$set": update})
    if call_id:
        await db.calls.update_one(
            {"_id": call_id}, {"$set": {"outcome": "no_answer", "endedAt": now, "updatedAt": now}}
        )
    await audit.log(db, "callback_unanswered", "retry" if retry else "gave up", callbackId=cb_id)
    return state


async def mark_played_in_call(db: AsyncIOMotorDatabase, request_id: str, status: str, call_id: str) -> int:
    """The resident heard this status on a call already in progress: don't phone them again for it."""
    res = await db.callbacks.update_many(
        {"requestId": request_id, "announcedStatus": status, "state": "queued"},
        {"$set": {"state": "played", "via": "in_call", "callId": call_id, "playedAt": utcnow()}},
    )
    return res.modified_count


# ── is it still worth saying? ─────────────────────────────────────────────────


async def _stale_reason(db: AsyncIOMotorDatabase, cb: dict[str, Any], req: dict[str, Any] | None) -> str | None:
    if req is None:
        return "request gone"
    status = cb["announcedStatus"]
    if req["status"] != status:
        return f"request is {req['status']} now"
    if status in ("driver_accepted", "en_route", "arrived"):
        a = await db.assignments.find_one({"_id": cb["assignmentId"]}, {"status": 1})
        if not a or a["status"] not in ("accepted", "completed"):
            return "that offer is no longer accepted"
    if status == "en_route":
        newer = await db.callbacks.find_one(
            {
                "assignmentId": cb["assignmentId"],
                "announcedStatus": "en_route",
                "createdAt": {"$gt": cb["createdAt"]},
                "state": {"$in": ["queued", "placed", "played"]},
            }
        )
        if newer:
            return "a newer ETA is queued"
    return None


async def _active_call(db: AsyncIOMotorDatabase, household_id: str, now: datetime) -> dict[str, Any] | None:
    since = now - timedelta(seconds=ACTIVE_CALL_S)
    async for c in db.calls.find({"householdId": household_id, "endedAt": None}):
        if (aware(c.get("updatedAt")) or since) > since and not (c.get("agent") or {}).get("done"):
            return c
    return None


# ── one callback ──────────────────────────────────────────────────────────────


async def handle(db: AsyncIOMotorDatabase, cb: dict[str, Any], pacer: dialer.Pacer, now: datetime) -> str:
    s = get_settings()
    req = await db.requests.find_one({"_id": cb["requestId"]})
    reason = await _stale_reason(db, cb, req)
    if reason:
        return await _skip(db, cb, reason, now)
    hh = await db.households.find_one({"_id": req["householdId"]})
    if hh is None:
        return await _skip(db, cb, "household gone", now)

    live = await _active_call(db, hh["_id"], now)
    if live:
        if (live.get("agent") or {}).get("announcedStatus") == cb["announcedStatus"]:
            await mark_played_in_call(db, req["_id"], cb["announcedStatus"], live["_id"])
            return "played"
        return await _defer(db, cb, DEFER_S, now)  # the in-call agent announces it at the next sentence

    sim = bool(hh.get("simulated"))
    if not sim and not await dialer.real_calls_on(db):
        return await _skip(db, cb, "real phone calls are off", now)
    if not sim and not dialer._elevenlabs_ready():
        return await _defer(db, cb, 30, now)
    if sim and sum(1 for t in _tasks.values() if not t.done()) >= s.standin_concurrency:
        return "busy"
    if not pacer.allow(sim, s.standin_rate_per_s if sim else s.dial_rate_per_s):
        return "busy"

    call_id = new_id("call")
    claimed = await db.callbacks.find_one_and_update(
        {"_id": cb["_id"], "state": "queued"},
        {"$set": {"state": "placed", "placedAt": now, "callId": call_id, "updatedAt": now}, "$inc": {"attempts": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if claimed is None:
        return "taken"
    await db.calls.insert_one(
        {
            "_id": call_id,
            "householdId": hh["_id"],
            "direction": "callback",
            "callbackId": cb["_id"],
            "language": hh.get("language", "en"),
            "startedAt": now,
            "updatedAt": now,
            "endedAt": None,
            "outcome": None,
            "simulated": sim,
            "turns": [],
        }
    )
    await audit.log(db, "callback_placed", cb["announcedStatus"], callbackId=cb["_id"], callId=call_id)
    if sim:
        _tasks[cb["_id"]] = asyncio.create_task(_standin(db, claimed, hh, call_id), name=f"callback-{cb['_id']}")
    else:
        try:
            conversation_id = await dialer._elevenlabs_call(hh, call_id, "callback")
            await db.calls.update_one({"_id": call_id}, {"$set": {"voiceCallId": conversation_id}})
        except dialer.DialError as e:
            log.warning("callback %s: %s", cb["_id"], e)
            return await unanswered(db, cb["_id"], call_id, now=now)
    return "placed"


async def _standin(db: AsyncIOMotorDatabase, cb: dict[str, Any], hh: dict[str, Any], call_id: str) -> None:
    s = get_settings()
    try:
        if dialer._roll(hh["_id"], f"cb:{cb['_id']}:{cb.get('attempts')}") < dialer.STANDIN_NO_ANSWER:
            await asyncio.sleep(min(2.0, s.standin_turn_delay_s * 3))
            await unanswered(db, cb["_id"], call_id)
            return
        await standin.run_call(db, hh["_id"], call_id, turn_delay_s=s.standin_turn_delay_s, call_type="callback")
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("stand-in callback %s failed", cb["_id"])
        await unanswered(db, cb["_id"], call_id)


# ── the loop ──────────────────────────────────────────────────────────────────


async def sweep(db: AsyncIOMotorDatabase, now: datetime) -> None:
    """Real callbacks nobody picked up (the Line agent never called /agent/start) → unanswered."""
    stale = now - timedelta(seconds=dialer.RING_TIMEOUT_S + dialer.ANSWER_GRACE_S)
    async for cb in db.callbacks.find({"state": "placed"}):
        if (aware(cb.get("placedAt")) or now) < stale and cb["_id"] not in _tasks:
            await unanswered(db, cb["_id"], cb.get("callId"), now=now)


async def tick(db: AsyncIOMotorDatabase, pacer: dialer.Pacer, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    await sweep(db, now)
    counts: dict[str, int] = {}
    async for cb in db.callbacks.find({"state": "queued"}).sort("createdAt", 1).limit(100):
        not_before = aware(cb.get("notBefore"))
        if not_before and not_before > now:
            continue
        result = await handle(db, cb, pacer, now)
        counts[result] = counts.get(result, 0) + 1
    return counts


async def run(db: AsyncIOMotorDatabase, every_s: float = 0.5) -> None:
    pacer = dialer.Pacer()
    while True:
        try:
            await tick(db, pacer)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("callback tick failed")
        await asyncio.sleep(every_s)
