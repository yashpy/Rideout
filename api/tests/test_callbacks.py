"""Callback worker + live status: the resident hears every status change, once, and only the truth."""

from datetime import timedelta

import pytest

from api import assignments
from api.agent import callbacks as worker
from api.agent import dialer, templates
from api.core.config import get_settings
from api.core.util import utcnow
from api.tests.factories import AUTH, make_assignment, make_household, make_vehicle

ROSA = {
    "canLeave": "no",
    "peopleCount": 2,
    "mobility": "power_wheelchair",
    "assistance": "two_person_lift",
    "medical": [],
    "pets": False,
    "hasCar": False,
}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    s = get_settings()
    for k, v in {
        "gemini_api_key": "",
        "anthropic_api_key": "",
        "standin_turn_delay_s": 0.0,
        "standin_rate_per_s": 1e9,
        "dial_rate_per_s": 1e9,
        "elevenlabs_api_key": "",
    }.items():
        monkeypatch.setattr(s, k, v)
    monkeypatch.setattr(dialer, "STANDIN_NO_ANSWER", 0.0)


async def accepted_ride(db, **hh):
    """Rosa's request, offered to Luis's wheelchair van and accepted → driver_accepted callback queued."""
    house = await make_household(db, personaId="p01", record=ROSA, role="needs_ride", reach="answered", **hh)
    from api.requests import upsert_for_household

    req = await upsert_for_household(db, house["_id"], need={"seats": 2, "wheelchair": 1, "crew": 2, "lift": True})
    await db.requests.update_one({"_id": req["_id"]}, {"$set": {"status": "approved"}})
    vh = await make_vehicle(db)
    a = await make_assignment(
        db,
        req["_id"],
        vh["_id"],
        status="offered",
        etaMinutes=7.2,
        offeredAt=utcnow(),
        expiresAt=utcnow() + timedelta(minutes=2),
    )
    assert (await assignments.accept(db, a["_id"]))["result"] == "accepted"
    return house, req, a


async def run_worker(db, now=None) -> dict:
    counts = await worker.tick(db, dialer.Pacer(), now=now)
    await worker.drain()
    return counts


def agent_text(call: dict) -> str:
    return " ".join(t["text"] for t in call["turns"] if t["speaker"] == "agent")


async def test_driver_accepts_resident_hears_name_and_eta(db):
    house, req, a = await accepted_ride(db)
    assert (await run_worker(db)) == {"placed": 1}
    cb = await db.callbacks.find_one({"requestId": req["_id"]})
    assert cb["state"] == "played"
    call = await db.calls.find_one({"_id": cb["callId"]})
    assert call["direction"] == "callback" and call["outcome"] == "answered"
    assert "A wheelchair van with a two-person crew is 7 minutes away. The driver's name is Luis." in agent_text(call)
    assert (await db.calls.find_one({"_id": cb["callId"]}))["agent"]["done"]
    assert (await run_worker(db)) == {}  # nothing is announced twice


async def test_road_closes_resident_hears_the_truth(db):
    house, req, a = await accepted_ride(db)
    await run_worker(db)
    await assignments.revoke(db, a["_id"], reason="no route in time")
    assert (await run_worker(db)) == {"placed": 1}
    cb = await db.callbacks.find_one({"requestId": req["_id"], "announcedStatus": "reassigning"})
    call = await db.calls.find_one({"_id": cb["callId"]})
    text = agent_text(call)
    assert templates.STATUS["en"]["reassigning"] in text
    assert "7 minutes" not in text and "Luis" not in text  # never the old ETA or driver


async def test_stale_news_is_skipped(db):
    house, req, a = await accepted_ride(db)
    await assignments.revoke(db, a["_id"], reason="driver cancels")  # before the first callback went out
    counts = await run_worker(db)
    assert counts == {"skipped": 1, "placed": 1}
    states = {c["announcedStatus"]: c["state"] async for c in db.callbacks.find({"requestId": req["_id"]})}
    assert states == {"driver_accepted": "skipped", "reassigning": "played"}


async def test_no_answer_retries_once_then_gives_up(db, monkeypatch):
    monkeypatch.setattr(dialer, "STANDIN_NO_ANSWER", 1.0)
    house, req, a = await accepted_ride(db)
    now = utcnow()
    assert (await run_worker(db, now)) == {"placed": 1}
    cb = await db.callbacks.find_one({"requestId": req["_id"]})
    assert cb["state"] == "queued" and cb["attempts"] == 1
    assert (await run_worker(db, now + timedelta(seconds=10))) == {}  # waits before the retry
    assert (await run_worker(db, now + timedelta(seconds=worker.RETRY_AFTER_S + 1))) == {"placed": 1}
    cb = await db.callbacks.find_one({"_id": cb["_id"]})
    assert cb["state"] == "unanswered" and cb["attempts"] == 2


async def test_status_change_is_told_inside_a_live_call(client, db):
    """Resident is on a call when the driver accepts: they hear it at the next sentence, and get no extra call."""
    house = await make_household(db, record={"canLeave": "no"}, simulated=True, personaId="p01")
    r = await client.post(
        "/agent/start", json={"householdId": house["_id"], "callType": "outbound", "callId": "c_live"}, headers=AUTH
    )
    assert r.status_code == 200
    from api.requests import upsert_for_household

    req = await upsert_for_household(db, house["_id"])
    await db.requests.update_one({"_id": req["_id"]}, {"$set": {"status": "approved"}})
    vh = await make_vehicle(db)
    a = await make_assignment(
        db,
        req["_id"],
        vh["_id"],
        status="offered",
        etaMinutes=5,
        offeredAt=utcnow(),
        expiresAt=utcnow() + timedelta(minutes=2),
    )
    await assignments.accept(db, a["_id"])
    assert (await run_worker(db)) == {"deferred": 1}  # don't ring a phone that's already on a call

    r = await client.post(
        "/agent/turn", json={"callId": "c_live", "householdId": house["_id"], "text": "yes"}, headers=AUTH
    )
    assert "The driver's name is Luis." in " ".join(r.json()["say"])
    cb = await db.callbacks.find_one({"requestId": req["_id"]})
    assert cb["state"] == "played" and cb["via"] == "in_call"


async def test_real_phone_callback_waits_for_elevenlabs_then_plays(db, monkeypatch):
    house, req, a = await accepted_ride(db, simulated=False)
    assert (await run_worker(db)) == {"deferred": 1}  # no phone line configured yet

    s = get_settings()
    for k in ("elevenlabs_api_key", "elevenlabs_agent_id", "elevenlabs_phone_number_id"):
        monkeypatch.setattr(s, k, "x")
    sent = {}

    async def fake(hh, call_id, call_type="outbound"):
        sent.update(call=call_id, type=call_type)
        return "ac_1"

    monkeypatch.setattr(dialer, "_elevenlabs_call", fake)
    assert (await run_worker(db, utcnow() + timedelta(seconds=31))) == {"placed": 1}
    cb = await db.callbacks.find_one({"requestId": req["_id"]})
    assert cb["state"] == "placed" and sent == {"call": cb["callId"], "type": "callback"}

    # The Line agent picks up and calls /agent/start with the callId from the dynamic variables.
    from api.agent import session

    out = await session.start(db, house["_id"], "callback", cb["callId"])
    assert "The driver's name is Luis." in " ".join(out["say"])
    assert (await db.callbacks.find_one({"_id": cb["_id"]}))["state"] == "played"


async def test_real_phone_callback_nobody_picks_up(db, monkeypatch):
    house, req, a = await accepted_ride(db, simulated=False)
    s = get_settings()
    for k in ("elevenlabs_api_key", "elevenlabs_agent_id", "elevenlabs_phone_number_id"):
        monkeypatch.setattr(s, k, "x")

    async def fake(hh, call_id, call_type="outbound"):
        return "ac_1"

    monkeypatch.setattr(dialer, "_elevenlabs_call", fake)
    now = utcnow()
    await run_worker(db, now)
    late = now + timedelta(seconds=dialer.RING_TIMEOUT_S + dialer.ANSWER_GRACE_S + 1)
    await worker.sweep(db, late)
    cb = await db.callbacks.find_one({"requestId": req["_id"]})
    assert cb["state"] == "queued" and cb["attempts"] == 1  # one retry left
