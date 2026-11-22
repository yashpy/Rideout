"""Agent turns: the state machine fills a record, corrections stick, requests follow."""

import asyncio

import pytest

from api.agent import interpreter, templates
from api.agent.interpreter import Interp
from api.core.config import get_settings
from api.tests.factories import AUTH, make_assignment, make_household, make_vehicle

pytestmark = pytest.mark.usefixtures("no_models")


@pytest.fixture
def no_models(monkeypatch):
    """Tests use the rule-based interpreter, never a real model, even if a .env has keys."""
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")


class Call:
    def __init__(self, client, hh_id: str, call_id: str = "call_test"):
        self.client, self.hh, self.id = client, hh_id, call_id

    async def start(self, call_type: str = "outbound") -> dict:
        r = await self.client.post(
            "/agent/start", json={"householdId": self.hh, "callType": call_type, "callId": self.id}, headers=AUTH
        )
        assert r.status_code == 200, r.text
        return r.json()

    async def say(self, text: str) -> dict:
        r = await self.client.post(
            "/agent/turn", json={"callId": self.id, "householdId": self.hh, "text": text}, headers=AUTH
        )
        assert r.status_code == 200, r.text
        return r.json()


def spoken(out: dict) -> str:
    return " ".join(out["say"])


async def test_needs_token(client, db):
    hh = await make_household(db)
    r = await client.post("/agent/start", json={"householdId": hh["_id"], "callType": "outbound", "callId": "c"})
    assert r.status_code == 401


async def test_full_call_fills_record_and_creates_request(client, db):
    hh = await make_household(db)
    call = Call(client, hh["_id"])
    out = await call.start()
    assert "automated assistant" in spoken(out) and hh["address"] in spoken(out)
    assert out["stage"] == "confirm_address"

    assert (await call.say("yes that's me"))["stage"] == "can_leave"
    assert (await call.say("no, I can't leave on my own"))["stage"] == "household"
    await call.say("it's just me")
    out = await call.say("no wait, my husband is here too, there's two of us")
    assert out["record"]["peopleCount"] == 2
    out = await call.say("no pets")
    assert out["stage"] == "needs"
    out = await call.say("he's in a power chair")
    assert out["record"]["mobility"] == "power_wheelchair"
    out = await call.say("no oxygen")
    assert out["stage"] == "assistance"
    out = await call.say("it takes two people to lift him")
    assert out["stage"] == "readback"
    assert "two people, a power wheelchair, and two people to lift" in spoken(out)
    out = await call.say("yes")
    assert out["stage"] == "neighbor"
    out = await call.say("no")
    assert templates.STATUS["en"]["received"] in spoken(out)
    assert out["requestStatus"] == "received" and out["stage"] == "hold"
    out = await call.say("no, that's all")
    assert out["done"] and out["stage"] == "goodbye"

    stored = await db.households.find_one({"_id": hh["_id"]})
    assert stored["record"] == {
        "canLeave": "no",
        "peopleCount": 2,
        "pets": False,
        "mobility": "power_wheelchair",
        "medical": [],
        "assistance": "two_person_lift",
    }
    assert [(c["field"], c["from"], c["to"]) for c in stored["corrections"]] == [("peopleCount", 1, 2)]
    assert stored["role"] == "needs_ride" and stored["reach"] == "answered"

    req = await db.requests.find_one({"householdId": hh["_id"]})
    assert req["status"] == "received"
    assert req["need"] == {"seats": 2, "wheelchair": 1, "stretcher": 0, "crew": 2, "lift": True}

    doc = await db.calls.find_one({"_id": "call_test"})
    speakers = [t["speaker"] for t in doc["turns"]]
    assert speakers[0] == "agent" and speakers.count("resident") == 11
    agent_turns = [t for t in doc["turns"][1:] if t["speaker"] == "agent"]
    assert all(t["latencyMs"] is not None and "requestStatus" in t for t in agent_turns)


async def test_can_leave_household_gets_no_request(client, db):
    hh = await make_household(db)
    call = Call(client, hh["_id"])
    await call.start()
    for text in ["yes", "yes we can", "two of us", "a dog"]:
        await call.say(text)
    out = await call.say("yes we have a car")
    assert out["stage"] == "neighbor"
    out = await call.say("no")
    out = await call.say("no")
    assert out["done"] and "leave now" in spoken(out)
    assert await db.requests.count_documents({}) == 0
    assert (await db.households.find_one({"_id": hh["_id"]}))["role"] == "left"


async def test_asking_about_a_ride_never_promises(client, db):
    hh = await make_household(db)
    call = Call(client, hh["_id"])
    await call.start()
    out = await call.say("is someone coming to get me?")
    text = spoken(out)
    assert templates.STATUS["en"]["none"] in text
    assert "rescue list as high priority" not in text  # not on the list yet, so we don't say so
    assert out["stage"] == "confirm_address"  # and we ask the question again


async def test_wants_time_says_dont_know(client, db):
    hh = await make_household(db)
    call = Call(client, hh["_id"])
    await call.start()
    await call.say("yes")
    await call.say("no")
    out = await call.say("when will they get here?")
    assert "I don't know that yet." in out["say"]
    assert templates.STATUS["en"]["received"] in spoken(out)


async def test_reask_once_then_escalate_address(client, db):
    hh = await make_household(db)
    call = Call(client, hh["_id"])
    await call.start()
    out = await call.say("banana")
    assert "Please say yes or no" in spoken(out) and out["stage"] == "confirm_address"
    out = await call.say("purple")
    assert out["stage"] == "can_leave"
    await call.say("no")  # needs a ride → request carries the escalation
    req = await db.requests.find_one({"householdId": hh["_id"]})
    assert req["escalation"] == "address_unconfirmed"


async def test_can_leave_unclear_twice_counts_as_unsure(client, db):
    hh = await make_household(db)
    call = Call(client, hh["_id"])
    await call.start()
    await call.say("yes")
    await call.say("hmm")
    out = await call.say("the sky")
    assert out["record"]["canLeave"] == "unsure" and out["requestStatus"] == "received"


async def test_medical_emergency_escalates_immediately(client, db):
    hh = await make_household(db)
    call = Call(client, hh["_id"])
    await call.start()
    out = await call.say("my husband has chest pain")
    assert "call 911" in spoken(out)
    req = await db.requests.find_one({"householdId": hh["_id"]})
    assert req is not None and req["escalation"] == "medical"


async def test_correction_to_can_leave_closes_unoffered_request(client, db, monkeypatch):
    import api.agent.session as session

    hh = await make_household(db)
    call = Call(client, hh["_id"])
    await call.start()
    await call.say("yes")
    await call.say("no")
    assert (await db.requests.find_one({"householdId": hh["_id"]}))["status"] == "received"

    async def fake(text, **kw):
        return Interp(set={"canLeave": "yes"}, answer="unclear", source="test")

    monkeypatch.setattr(session, "interpret", fake)
    await call.say("actually my daughter is here with her car, we can go")
    assert (await db.requests.find_one({"householdId": hh["_id"]}))["status"] == "closed"


async def test_model_correction_changes_record(client, db, monkeypatch):
    """A correction from the model ("no wait, my son is here") overrides the record and is logged."""
    import api.agent.session as session

    hh = await make_household(db, record={"canLeave": "no", "peopleCount": 1})
    call = Call(client, hh["_id"])
    await call.start()

    async def fake(text, **kw):
        return Interp(set={"peopleCount": 2}, answer="no", ack="Your son, got it.", source="test")

    monkeypatch.setattr(session, "interpret", fake)
    out = await call.say("no wait, my son is here")
    assert out["record"]["peopleCount"] == 2 and out["say"][0] == "Your son, got it."
    stored = await db.households.find_one({"_id": hh["_id"]})
    assert stored["corrections"][-1]["field"] == "peopleCount"


async def test_blocked_ack_is_never_spoken(client, db, monkeypatch):
    import api.agent.session as session

    hh = await make_household(db)
    call = Call(client, hh["_id"])
    await call.start()

    async def fake(text, **kw):
        return Interp(answer="yes", ack="Help is on the way.", source="test")

    monkeypatch.setattr(session, "interpret", fake)
    out = await call.say("yes")
    assert "Help is on the way." not in spoken(out)
    doc = await db.calls.find_one({"_id": "call_test"})
    assert doc["turns"][-1]["guardBlocked"] is True
    assert await db.auditLog.count_documents({"kind": "ack_blocked"}) == 1


async def test_neighbor_description_never_touches_this_record(client, db):
    hh = await make_household(
        db,
        record={
            "canLeave": "no",
            "peopleCount": 2,
            "pets": False,
            "mobility": "power_wheelchair",
            "medical": [],
            "assistance": "two_person_lift",
        },
    )
    call = Call(client, hh["_id"])
    await call.start()
    await call.say("yes")
    out = await call.say("yes")  # read-back confirmed
    assert out["stage"] == "neighbor"
    out = await call.say("the lady across the street uses a walker")
    assert out["record"]["mobility"] == "power_wheelchair"
    assert out["stage"] == "hold"
    assert await db.auditLog.count_documents({"kind": "neighbor_reported"}) == 1


async def test_question_at_neighbor_stage_is_not_a_neighbor(client, db):
    hh = await make_household(
        db,
        record={"canLeave": "no", "peopleCount": 1, "pets": False, "mobility": "walks", "medical": []},
    )
    call = Call(client, hh["_id"])
    await call.start()
    await call.say("yes")  # address
    out = await call.say("yes")  # read-back
    assert out["stage"] == "neighbor"
    out = await call.say("Is someone coming?")
    assert templates.STATUS["en"]["received"] in spoken(out)
    assert out["stage"] == "neighbor"  # the neighbor question is asked again
    assert await db.auditLog.count_documents({"kind": "neighbor_reported"}) == 0


async def test_first_real_phone_call_replayed(client, db):
    """A real test call on 2026-11-15 (dev phone line), word for word. It once lost the two-person lift."""
    hh = await make_household(db)
    call = Call(client, hh["_id"], "call_real_1")
    await call.start()
    for text in [
        "Yes.",
        "Uh, so we are 4 people, but I guess like one is not ready to leave. He is having, he's facing "
        "some injury in his leg, so",
        "Uh, no.",
        "4.",
        "No pets.",
        "Yes, one person needs help.",
        "Yes.",
        "Uh, no, what one person used the wheelchair.",
        "Uh, it's a manual chair.",
        "Uh, 2 people.",
    ]:
        out = await call.say(text)
    assert out["record"]["assistance"] == "two_person_lift" and out["stage"] == "readback"
    assert "two people to lift" in spoken(out)
    await call.say("Yes, correct.")
    out = await call.say("Sorry?")
    assert out["stage"] == "neighbor" and "Do you know a neighbor" in spoken(out)  # repeated, not re-worded
    await call.say("Uh, I don't know.")
    out = await call.say("Uh, yeah, please find a vehicle for me.")
    assert templates.STATUS["en"]["received"] in spoken(out) and out["done"]
    req = await db.requests.find_one({"householdId": hh["_id"]})
    assert req["need"] == {"seats": 4, "wheelchair": 1, "stretcher": 0, "crew": 2, "lift": False}


async def test_start_finds_the_call_by_conversation_id(client, db):
    """The voice provider.s own call id is enough to find the call we dialed."""
    hh = await make_household(db, simulated=False, phone="+16025550199")
    await db.calls.insert_one(
        {"_id": "call_dialed", "householdId": hh["_id"], "direction": "outbound", "voiceCallId": "ac_123"}
    )
    r = await client.post(
        "/agent/start",
        json={"householdId": "", "callType": "inbound", "callId": "call_CA999", "voiceCallId": "ac_123"},
        headers=AUTH,
    )
    body = r.json()
    assert r.status_code == 200 and body["callId"] == "call_dialed" and body["householdId"] == hh["_id"]
    assert body["callType"] == "outbound" and hh["address"] in " ".join(body["say"])


async def test_start_finds_an_inbound_caller_by_phone(client, db):
    hh = await make_household(db, simulated=False, phone="+16025550188")
    r = await client.post("/agent/start", json={"voiceCallId": "ac_in_1", "callerPhone": "+16025550188"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["householdId"] == hh["_id"] and r.json()["callType"] == "inbound"
    r = await client.post("/agent/start", json={"voiceCallId": "ac_unknown"}, headers=AUTH)
    assert r.status_code == 404


async def test_spanish_switch(client, db):
    hh = await make_household(db)
    call = Call(client, hh["_id"])
    out = await call.start()
    assert templates.LINES["en"]["spanish_offer"] in spoken(out)
    out = await call.say("español por favor")
    assert "Muy bien, seguimos en español." in out["say"]
    assert "¿Está usted en" in spoken(out)
    assert (await db.households.find_one({"_id": hh["_id"]}))["language"] == "es"


async def test_status_change_announced_mid_call(client, db):
    hh = await make_household(db, record={"canLeave": "no"})
    call = Call(client, hh["_id"])
    await call.start()
    await call.say("yes")
    req = await db.requests.find_one({"householdId": hh["_id"]})
    assert req is None or req["status"] == "received"
    # simulate the rest of the system: request accepted by Luis in a wheelchair van, 7 minutes out
    from api.requests import upsert_for_household

    req = await upsert_for_household(db, hh["_id"])
    vh = await make_vehicle(db)
    await make_assignment(db, req["_id"], vh["_id"], status="accepted", etaMinutes=7.2)
    await db.requests.update_one({"_id": req["_id"]}, {"$set": {"status": "driver_accepted"}})
    out = await call.say("two of us")
    assert "A wheelchair van with a two-person crew is 7 minutes away. The driver's name is Luis." in spoken(out)


async def test_callback_call_speaks_status(client, db):
    hh = await make_household(db, record={"canLeave": "no"})
    from api.requests import upsert_for_household

    req = await upsert_for_household(db, hh["_id"])
    await db.requests.update_one({"_id": req["_id"]}, {"$set": {"status": "reassigning"}})
    call = Call(client, hh["_id"], "call_cb")
    out = await call.start("callback")
    assert templates.STATUS["en"]["reassigning"] in out["say"]
    out = await call.say("okay")
    assert out["done"]


async def test_call_floor_reads(client, db):
    hh = await make_household(db)
    call = Call(client, hh["_id"], "call_floor")
    await call.start()
    await call.say("yes")
    await call.say("no")
    rows = (await client.get("/calls")).json()
    assert rows[0]["id"] == "call_floor" and rows[0]["stage"] == "household"
    assert rows[0]["household"]["address"] == hh["address"] and rows[0]["turnCount"] == 5
    one = (await client.get("/calls/call_floor")).json()
    assert [t["speaker"] for t in one["turns"]] == ["agent", "resident", "agent", "resident", "agent"]
    assert one["request"]["status"] == "received" and one["turns"][-1]["requestStatus"] == "received"
    assert (await client.get("/calls/nope")).status_code == 404


def test_call_turn_event_carries_status():
    from api.live import LiveHub, events_for_change

    turn = {"speaker": "agent", "text": "Hi", "latencyMs": 12.0, "requestStatus": "received", "at": "t"}
    change = {
        "operationType": "update",
        "fullDocument": {"_id": "c1", "householdId": "h1", "turns": [turn]},
        "updateDescription": {"updatedFields": {"turns.0": turn}},
    }
    ((kind, data),) = events_for_change("calls", change, LiveHub())
    assert kind == "call.turn" and data["requestStatus"] == "received" and data["guardBlocked"] is False


# ── interpreter fallback ──────────────────────────────────────────────────────


async def test_claude_is_never_called_unless_paid_models_are_allowed(monkeypatch):
    """The team said no paid models: a Claude key alone must not turn Claude on."""
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "a")
    monkeypatch.setattr(get_settings(), "allow_paid_models", False)

    async def paid(prompt, http):
        raise AssertionError("Claude was called")

    monkeypatch.setattr(interpreter, "_claude", paid)
    it = await interpreter.interpret("yes", stage="can_leave", goal="can_leave", record={}, recent=[])
    assert it.source == "rules" and it.set == {"canLeave": "yes"}


async def test_gemini_timeout_falls_back_to_claude(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "g")
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "a")
    monkeypatch.setattr(get_settings(), "allow_paid_models", True)
    monkeypatch.setattr(interpreter, "GEMINI_TIMEOUT_S", 0.05)

    async def slow(prompt, http):
        await asyncio.sleep(1)

    async def claude(prompt, http):
        return {"set": ["peopleCount=2", "mobility=flying"], "answer": "no", "flags": ["asks_ride"], "ack": "Two."}

    monkeypatch.setattr(interpreter, "_gemini", slow)
    monkeypatch.setattr(interpreter, "_claude", claude)
    it = await interpreter.interpret("two of us", stage="household", goal="people", record={}, recent=[])
    assert it.source == "claude" and it.fallback
    assert it.set == {"peopleCount": 2}  # invalid values are dropped
    assert it.flags == {"asks_ride"}


async def test_both_models_down_uses_rules(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_api_key", "g")
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "a")
    monkeypatch.setattr(get_settings(), "allow_paid_models", True)

    async def boom(prompt, http):
        raise RuntimeError("down")

    monkeypatch.setattr(interpreter, "_gemini", boom)
    monkeypatch.setattr(interpreter, "_claude", boom)
    it = await interpreter.interpret("yes", stage="can_leave", goal="can_leave", record={}, recent=[])
    assert it.source == "rules" and it.fallback and it.set == {"canLeave": "yes"}


def test_parse_set_validates():
    assert interpreter.parse_set(
        ["peopleCount=3", "pets=true", "medical=oxygen", "medical=dialysis", "hasCar=maybe", "nonsense", "x=1"]
    ) == {"peopleCount": 3, "pets": True, "medical": ["oxygen", "dialysis"]}


def test_templates_have_both_languages():
    for table in (templates.LINES, templates.STATUS, templates.QUESTIONS):
        assert set(table["en"]) == set(table["es"])


def test_status_templates_match_contract():
    assert templates.STATUS["en"]["received"] == (
        "You're on the rescue list as high priority. No driver has accepted yet. "
        "I'll call you back the moment one does. If you can leave safely, leave now. "
        "If fire reaches your home, call 911."
    )
    assert templates.status_line("en", "en_route", {"name": "Luis", "eta": 4.4}) == "Luis is about 4 minutes away."
    assert templates.status_line("en", "driver_accepted", None) == templates.STATUS["en"]["driver_accepted_no_detail"]
    one = templates.status_line("en", "driver_accepted", {"name": "Lena", "eta": 1.4, "vehicleKind": "neighbor"})
    assert "is 1 minute away" in one and "minutes" not in one
