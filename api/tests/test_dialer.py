"""Dialer + reach ladder + stand-ins."""

import json
from datetime import timedelta

import httpx
import pytest

from api.agent import dialer, standin
from api.core.config import get_settings
from api.core.util import utcnow
from api.sim import data as sim_data
from api.tests.factories import make_household

ZONE = "zone_oak_creek_14"


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
    monkeypatch.setattr(dialer, "STANDIN_NEVER", 0.0)


def persona(pid: str) -> dict:
    return next(p for p in sim_data.personas() if p["id"] == pid)


async def zone(db, status: str) -> None:
    await db.zones.update_one({"_id": ZONE}, {"$set": {"status": status}}, upsert=True)


async def voice_standins(db, on: bool = True) -> None:
    await db.simControl.update_one({"_id": "sim"}, {"$set": {"standIns.voice": on}}, upsert=True)


@pytest.mark.parametrize("pid", [p["id"] for p in sim_data.personas()])
async def test_every_persona_completes_a_call(db, pid):
    """The stand-in answers the real agent from the persona's truth; the call ends and the record matches."""
    p = persona(pid)
    hh = await make_household(db, personaId=pid, language=p.get("language", "en"))
    out = await standin.run_call(db, hh["_id"], "call_p")
    assert out["done"], (pid, out)
    stored = await db.households.find_one({"_id": hh["_id"]})
    truth, rec = standin.true_record(p), stored["record"]
    assert rec.get("canLeave") == truth["canLeave"], pid
    assert rec.get("peopleCount") == truth["peopleCount"], pid
    if truth["canLeave"] != "yes":
        assert rec.get("mobility") == truth["mobility"], pid
    if p["expect"].get("role") == "needs_ride":
        req = await db.requests.find_one({"householdId": hh["_id"]})
        assert req is not None and req["status"] == "received", pid
        for k, v in (p["expect"].get("need") or {}).items():
            assert req["need"][k] == v, (pid, k)
    if p["expect"].get("role") == "can_help":
        assert stored["role"] == "can_help", pid


async def test_stand_ins_never_call_a_paid_model(db, monkeypatch):
    """Even with Gemini and Claude keys set, simulated homes use the free rule interpreter."""
    from api.agent import interpreter

    monkeypatch.setattr(get_settings(), "gemini_api_key", "g")
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "a")

    async def paid(*a, **kw):
        raise AssertionError("a stand-in called a paid model")

    monkeypatch.setattr(interpreter, "_gemini", paid)
    monkeypatch.setattr(interpreter, "_claude", paid)
    hh = await make_household(db, personaId="p02")
    out = await standin.run_call(db, hh["_id"], "call_free")
    assert out["done"]
    call = await db.calls.find_one({"_id": "call_free"})
    assert {t.get("interpreter") for t in call["turns"] if t["speaker"] == "agent" and t.get("interpreter")} == {
        "rules"
    }


async def test_rosa_corrects_herself(db):
    hh = await make_household(db, personaId="p01")
    await standin.run_call(db, hh["_id"], "call_rosa")
    stored = await db.households.find_one({"_id": hh["_id"]})
    assert ("peopleCount", 1, 2) in [(c["field"], c["from"], c["to"]) for c in stored["corrections"]]
    call = await db.calls.find_one({"_id": "call_rosa"})
    agent_text = " ".join(t["text"] for t in call["turns"] if t["speaker"] == "agent")
    for word in persona("p01")["expect"]["mustNotSay"]:
        assert word not in agent_text.replace("No driver has accepted yet", ""), word


async def test_set_zone_calls_every_home_highest_priority_first(db):
    soon = await make_household(db, personaId="p02", deadlineAt=utcnow() + timedelta(minutes=10))
    late = await make_household(db, personaId="p18", deadlineAt=utcnow() + timedelta(minutes=80))
    other_zone = await make_household(db, personaId="p02", zoneId="zone_elsewhere")
    await voice_standins(db)
    pacer = dialer.Pacer()

    await zone(db, "ready")
    assert await dialer.tick(db, pacer) == 0  # nothing before SET

    await zone(db, "set")
    order = [h["_id"] for h in await dialer.due(db, utcnow())]
    assert order == [soon["_id"], late["_id"]]
    assert await dialer.tick(db, pacer) == 2
    await dialer.drain()
    for h in (soon, late):
        assert (await db.households.find_one({"_id": h["_id"]}))["reach"] == "answered"
    assert (await db.households.find_one({"_id": other_zone["_id"]}))["reach"] == "not_called"
    assert await dialer.tick(db, pacer) == 0  # nobody is called twice


async def test_standins_wait_for_the_voice_switch(db):
    await make_household(db, personaId="p02")
    await zone(db, "set")
    assert await dialer.tick(db, dialer.Pacer()) == 0
    await voice_standins(db)
    assert await dialer.tick(db, dialer.Pacer()) == 1
    await dialer.drain()


async def test_reach_ladder_ends_on_the_door_knock_list(db, monkeypatch):
    monkeypatch.setattr(dialer, "STANDIN_NEVER", 1.0)
    hh = await make_household(db, personaId="p02")
    await zone(db, "set")
    await voice_standins(db)
    pacer = dialer.Pacer()
    t = utcnow()

    async def reach() -> str:
        return (await db.households.find_one({"_id": hh["_id"]}))["reach"]

    assert await dialer.tick(db, pacer, now=t) == 1
    await dialer.drain()
    assert await reach() == "retry_2"
    assert await dialer.tick(db, pacer, now=t + timedelta(minutes=1)) == 0  # not yet
    assert await dialer.tick(db, pacer, now=t + timedelta(minutes=3)) == 1
    await dialer.drain()
    assert await reach() == "retry_5"
    assert await dialer.tick(db, pacer, now=t + timedelta(minutes=9)) == 1
    await dialer.drain()
    assert await reach() == "texted"
    assert await db.auditLog.count_documents({"kind": "text_sent"}) == 1
    await dialer.tick(db, pacer, now=t + timedelta(minutes=30))
    assert await reach() == "door_check"
    calls = [c async for c in db.calls.find({"householdId": hh["_id"]})]
    assert len(calls) == 3 and all(c["outcome"] == "no_answer" for c in calls)


async def test_unanswered_real_call_moves_down_the_ladder(db):
    hh = await make_household(db, simulated=False, reach="ringing", dialAttempts=1, lastDialAt=utcnow())
    await db.calls.insert_one({"_id": "call_r", "householdId": hh["_id"], "outcome": None, "startedAt": utcnow()})
    await dialer.sweep(db, utcnow() + timedelta(seconds=dialer.RING_TIMEOUT_S + dialer.ANSWER_GRACE_S + 5))
    assert (await db.households.find_one({"_id": hh["_id"]}))["reach"] == "retry_2"
    assert (await db.calls.find_one({"_id": "call_r"}))["outcome"] == "no_answer"


async def test_calls_that_never_connected_are_closed(db):
    """A call record with no pickup stops showing as live on /calls; a call still ringing is left alone."""
    old = utcnow() - timedelta(minutes=10)
    await db.calls.insert_one({"_id": "c_dead", "householdId": "h1", "outcome": None, "startedAt": old})
    await db.calls.insert_one({"_id": "c_ringing", "householdId": "h2", "outcome": None, "startedAt": utcnow()})
    await db.calls.insert_one({"_id": "c_talking", "householdId": "h3", "outcome": "answered", "startedAt": old})
    await dialer.sweep(db, utcnow())
    assert (await db.calls.find_one({"_id": "c_dead"}))["outcome"] == "no_answer"
    assert (await db.calls.find_one({"_id": "c_ringing"}))["outcome"] is None
    assert (await db.calls.find_one({"_id": "c_talking"}))["outcome"] == "answered"


async def test_dial_endpoint(client, db):
    sim = await make_household(db, personaId="p18")
    res = await client.post("/calls/dial", json={"householdId": sim["_id"]})
    assert res.status_code == 200 and res.json()["callId"].startswith("call_")
    assert (await client.post("/calls/dial", json={"householdId": sim["_id"]})).status_code in (200, 409)
    await dialer.drain()
    assert (await db.households.find_one({"_id": sim["_id"]}))["reach"] == "answered"

    real = await make_household(db, simulated=False)
    res = await client.post("/calls/dial", json={"householdId": real["_id"]})
    assert res.status_code == 503 and "ElevenLabs" in res.json()["detail"]
    assert (await db.households.find_one({"_id": real["_id"]}))["reach"] == "not_called"
    assert (await client.post("/calls/dial", json={"householdId": "hh_nope"})).status_code == 404


async def test_real_dial_sends_ids_to_elevenlabs(db, monkeypatch):
    s = get_settings()
    for k in ("elevenlabs_api_key", "elevenlabs_agent_id", "elevenlabs_phone_number_id"):
        monkeypatch.setattr(s, k, "x")
    sent = {}

    async def fake(hh, call_id):
        sent.update(hh=hh["_id"], call=call_id)
        return "ac_123"

    monkeypatch.setattr(dialer, "_elevenlabs_call", fake)
    hh = await make_household(db, simulated=False)
    call_id = await dialer.dial(db, hh["_id"])
    assert sent == {"hh": hh["_id"], "call": call_id}
    assert (await db.calls.find_one({"_id": call_id}))["voiceCallId"] == "ac_123"
    assert (await db.households.find_one({"_id": hh["_id"]}))["reach"] == "ringing"


async def test_elevenlabs_request_carries_our_ids(monkeypatch):
    s = get_settings()
    for k, v in (
        ("elevenlabs_api_key", "xi"),
        ("elevenlabs_agent_id", "agent_1"),
        ("elevenlabs_phone_number_id", "pn_1"),
    ):
        monkeypatch.setattr(s, k, v)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(url=str(request.url), key=request.headers["xi-api-key"], body=json.loads(request.content))
        return httpx.Response(200, json={"success": True, "conversation_id": "conv_9", "callSid": "CA1"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(dialer.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    hh = {"_id": "hh_1", "phone": "+14805551234", "language": "es"}
    assert await dialer._elevenlabs_call(hh, "call_1", "callback") == "conv_9"
    assert seen["url"] == "https://api.elevenlabs.io/v1/convai/twilio/outbound-call" and seen["key"] == "xi"
    assert seen["body"]["agent_id"] == "agent_1" and seen["body"]["agent_phone_number_id"] == "pn_1"
    assert seen["body"]["to_number"] == "+14805551234"
    dyn = seen["body"]["conversation_initiation_client_data"]["dynamic_variables"]
    assert dyn == {"householdId": "hh_1", "callId": "call_1", "callType": "callback", "language": "es"}


async def test_elevenlabs_refusal_is_a_dial_error(monkeypatch):
    s = get_settings()
    for k in ("elevenlabs_api_key", "elevenlabs_agent_id", "elevenlabs_phone_number_id"):
        monkeypatch.setattr(s, k, "x")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "message": "number not verified"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(dialer.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    with pytest.raises(dialer.DialError, match="number not verified"):
        await dialer._elevenlabs_call({"_id": "hh_1", "phone": "+1"}, "call_1")
