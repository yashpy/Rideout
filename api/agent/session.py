"""One call, turn by turn: database I/O around the pure state machine in flow.py.

start():  create the `calls` doc, pick the opening lines.
turn():   log the resident turn → interpreter → flow.apply → PATCH record → sync request
          → honesty guard → flow.respond → log the agent turn.

Call state lives on the call doc under `agent`, so any API replica can serve the next turn.
"""

import asyncio
import time
from typing import Any

from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from api import audit
from api import requests as rq
from api.agent import dedupe, flow, honesty
from api.agent.interpreter import interpret
from api.core.util import utcnow
from api.models import Record
from api.routes.households import patch_record


async def _household(db: AsyncIOMotorDatabase, household_id: str) -> dict[str, Any]:
    hh = await db.households.find_one({"_id": household_id})
    if hh is None:
        raise HTTPException(404, "household not found")
    return hh


async def open_request(db: AsyncIOMotorDatabase, household_id: str) -> dict[str, Any] | None:
    return await db.requests.find_one({"householdId": household_id, "status": {"$in": list(rq.OPEN_STATUSES)}})


async def ride_info(db: AsyncIOMotorDatabase, request: dict[str, Any] | None) -> dict[str, Any] | None:
    """Driver name, vehicle kind, crew and ETA from the accepted offer. Only code fills these in."""
    if not request or request["status"] not in ("driver_accepted", "en_route", "arrived"):
        return None
    a = await db.assignments.find_one({"requestId": request["_id"], "status": {"$in": ["accepted", "completed"]}})
    if not a:
        return None
    v = await db.vehicles.find_one({"_id": a["vehicleId"]}) or {}
    return {
        "name": v.get("driverName"),
        "vehicleKind": v.get("kind"),
        "crew": v.get("crew"),
        "eta": a.get("etaMinutes"),
    }


async def _push_turn(db: AsyncIOMotorDatabase, call_id: str, turn: dict[str, Any], **set_: Any) -> None:
    update: dict[str, Any] = {"$push": {"turns": turn}, "$set": {"updatedAt": turn["at"], **set_}}
    await db.calls.update_one({"_id": call_id}, update)


# ── start ─────────────────────────────────────────────────────────────────────


async def start(db: AsyncIOMotorDatabase, household_id: str, call_type: str, call_id: str) -> dict[str, Any]:
    hh = await _household(db, household_id)
    state = flow.new_state(call_type, hh.get("language") or "en")
    req = await open_request(db, household_id)
    status = req["status"] if req else None
    say = flow.opening(
        state, hh.get("record") or {}, address=hh.get("address", ""), status=status, ride=await ride_info(db, req)
    )
    now = utcnow()
    await db.calls.update_one(
        {"_id": call_id},
        {
            # The dialer may have created this call doc when it rang; picking up makes it answered.
            "$set": {"agent": state, "language": state["language"], "outcome": "answered"},
            "$setOnInsert": {
                "householdId": household_id,
                "direction": call_type,
                "startedAt": now,
                "simulated": bool(hh.get("simulated")),  # /system splits real-phone vs stand-in latency
                "turns": [],
            },
        },
        upsert=True,
    )
    await _push_turn(db, call_id, {"speaker": "agent", "text": " ".join(say), "at": now, "requestStatus": status})
    if call_type == "callback":
        # The opening lines carry the status, so a picked-up callback has been played.
        await db.callbacks.update_many(
            {"callId": call_id, "state": "placed"}, {"$set": {"state": "played", "playedAt": now, "updatedAt": now}}
        )
    else:
        await db.households.update_one({"_id": household_id}, {"$set": {"reach": "in_call", "updatedAt": now}})
    if call_type == "callback" and req is not None and status in flow.ANNOUNCED:
        await _cancel_queued_callbacks(db, req["_id"], status, call_id)
    return {"say": say, "stage": state["stage"]}


async def _cancel_queued_callbacks(db: AsyncIOMotorDatabase, request_id: str, status: str, call_id: str) -> None:
    """They just heard this status on this call: no separate phone call for the same news."""
    await db.callbacks.update_many(
        {"requestId": request_id, "announcedStatus": status, "state": "queued"},
        {"$set": {"state": "played", "via": "in_call", "callId": call_id, "playedAt": utcnow()}},
    )


# ── turn ──────────────────────────────────────────────────────────────────────


async def turn(
    db: AsyncIOMotorDatabase,
    call_id: str,
    household_id: str,
    text: str,
    language: str = "en",
    *,
    use_models: bool = True,
) -> dict[str, Any]:
    """One resident turn. `use_models=False` (stand-ins, free evals) skips Gemini/Claude entirely."""
    t0 = time.perf_counter()
    hh = await _household(db, household_id)
    call = await db.calls.find_one({"_id": call_id})
    if call is None:  # the Line agent skipped /agent/start; recover instead of failing the call
        await start(db, household_id, "inbound", call_id)
        call = await db.calls.find_one({"_id": call_id})
    state: dict[str, Any] = call.get("agent") or flow.new_state("inbound", language)
    if state.get("done"):
        return {"say": [], "stage": "goodbye", "done": True, "record": hh.get("record") or {}, "requestStatus": None}
    record: dict[str, Any] = dict(hh.get("record") or {})

    # Log what they said while the interpreter thinks.
    log_task = asyncio.create_task(_push_turn(db, call_id, {"speaker": "resident", "text": text, "at": utcnow()}))
    it = await interpret(
        text,
        stage=state.get("stage", "greet"),
        goal=state.get("goal"),
        record=record,
        recent=(call.get("turns") or [])[-6:],
        language=state.get("language", language),
        use_models=use_models,
    )
    await log_task

    applied = flow.apply(state, record, it)
    if applied.changes:
        updated = await patch_record(household_id, Record(**applied.changes))
        record = updated.get("record") or {}
    req = await sync_request(db, hh, record, state, applied)
    status = req["status"] if req else None

    verdict = honesty.check(it.ack, status)
    if verdict.blocked:
        await audit.log(db, "ack_blocked", verdict.reason or "", callId=call_id, ack=it.ack)
    announced_before = state.get("announcedStatus")
    say = flow.respond(
        state,
        record,
        it,
        applied,
        ack=verdict.ack,
        status=status,
        ride=await ride_info(db, req),
        address=hh.get("address", ""),
    )

    if req is not None and status in flow.ANNOUNCED and state.get("announcedStatus") != announced_before:
        await _cancel_queued_callbacks(db, req["_id"], status, call_id)  # announced mid-call

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    now = utcnow()
    extra: dict[str, Any] = {"agent": state, "language": state["language"]}
    if state["done"]:
        extra["endedAt"] = now
    agent_turn = {
        "speaker": "agent",
        "text": " ".join(say),
        "at": now,
        "latencyMs": latency_ms,
        "interpreterMs": it.latency_ms,
        "interpreter": it.source,
        "fallback": it.fallback,
        "requestStatus": status,
        "guardBlocked": verdict.blocked,
        "stage": state["stage"],
        # The only AI-written words in the turn (evals, /system): what it proposed, and what was spoken.
        "ackProposed": it.ack,
        "ack": verdict.ack,
        "guardReason": verdict.reason,
    }
    hh_set: dict[str, Any] = {}
    role = flow.role_for(record, state)
    if role and role != hh.get("role"):
        hh_set["role"] = role
    if state["done"] and hh.get("reach") in (None, "in_call", "ringing", "not_called"):
        hh_set["reach"] = "answered"
    if state["language"] != hh.get("language"):
        hh_set["language"] = state["language"]
    await asyncio.gather(
        _push_turn(db, call_id, agent_turn, **extra),
        db.households.update_one({"_id": household_id}, {"$set": {**hh_set, "updatedAt": now}})
        if hh_set
        else asyncio.sleep(0),
    )
    return {"say": say, "stage": state["stage"], "done": state["done"], "record": record, "requestStatus": status}


# ── record → request ──────────────────────────────────────────────────


async def sync_request(
    db: AsyncIOMotorDatabase,
    hh: dict[str, Any],
    record: dict[str, Any],
    state: dict[str, Any],
    applied: flow.Applied,
) -> dict[str, Any] | None:
    """Create/update the household's request when they need a ride or there's a life threat."""
    req = await open_request(db, hh["_id"])
    escalation = flow.top_escalation(state)
    wants = flow.needs_ride(record, state) or bool(set(state.get("escalations", [])) & flow.LIFE_THREATS)

    if wants:
        need = flow.compute_need(record, state)
        priority = flow.compute_priority(record, escalation)
        if req is None or req.get("need") != need or req.get("priority") != priority:
            req = await rq.upsert_for_household(
                db, hh["_id"], need=need, deadline_at=hh.get("deadlineAt"), priority=priority
            )
            if await dedupe.check(db, req):  # same home already has a request
                req = await db.requests.find_one({"_id": req["_id"]})
    elif req is not None and req["status"] == "received" and record.get("canLeave") == "yes":
        # A correction: they can leave after all. Nobody has been offered this ride yet.
        req = await rq.transition(db, req["_id"], "closed", reason="resident can leave", by="agent")
        return None

    if req is not None and escalation and req.get("escalation") != escalation:
        await db.requests.update_one(
            {"_id": req["_id"]}, {"$set": {"escalation": escalation, "updatedAt": utcnow()}, "$inc": {"version": 1}}
        )
        await audit.log(db, "request_escalated", escalation, requestId=req["_id"], by="agent")
        req = await db.requests.find_one({"_id": req["_id"]})
    for reason in applied.new_escalations:
        if req is None:  # e.g. address unclear for someone who can leave: still leave a trace
            await audit.log(db, "call_escalation", reason, householdId=hh["_id"])
    if state.get("neighbors") and applied.filled and state.get("goal") in ("neighbor_rider", "neighbor_driver"):
        await audit.log(db, "neighbor_reported", "; ".join(state["neighbors"]), householdId=hh["_id"])
    return req
