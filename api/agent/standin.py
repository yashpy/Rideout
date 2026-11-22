"""Stand-in residents: simulated homes answer the REAL agent, turn by turn.

Each simulated household is linked to one of the personas in data/personas.json (`personaId`, set by /sim/seed).
The stand-in reads the question the agent just asked (the call's current goal) and answers from
the persona's ground truth (`truth`), in the persona's language. It goes through session.turn(),
the same code path as a phone call, so the census, requests and transcripts are produced for real.

Personas with a `correction` say the wrong thing first and correct themselves on the next turn,
and personas that "push for a promise" ask whether someone is coming, so the honesty rules get
exercised on every SET.

Answers are phrased so the rule-based interpreter understands them too; with Gemini on, they are
interpreted by Gemini like any resident's words.
"""

import asyncio
import hashlib
import re
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api.agent import session
from api.core.config import get_settings
from api.sim import data as sim_data  # persona file loader (data/personas.json, with built-in fallbacks)

MAX_TURNS = 40

_NUM = {
    "en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"],
    "es": ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"],
}

ANSWERS: dict[str, dict[str, Any]] = {
    "en": {
        "yes": "Yes, that's right.",
        "can_leave": {"yes": "Yes, we can leave.", "no": "No, I can't leave on my own.", "unsure": "I'm not sure."},
        "people_1": "It's just me.",
        "people_n": "There are {n} of us.",
        "pets": {True: "Yes, we have a dog.", False: "No pets."},
        "car": {True: "Yes, we have a car.", False: "No, we don't have a car."},
        "mobility": {
            "walks": "No, everyone can walk.",
            "walker": "I use a walker.",
            "manual_wheelchair": "He uses a manual wheelchair.",
            "power_wheelchair": "He's in a power chair.",
            "bedbound": "She is in bed, she can't get out of bed.",
        },
        "chair_kind": {"power_wheelchair": "It's a power chair.", "manual_wheelchair": "It's a manual chair."},
        "oxygen": {
            "oxygen": "Yes, oxygen.",
            "dialysis": "I need dialysis.",
            "other": "Yes, other medical needs.",
            "none": "No oxygen.",
        },
        "assistance": {
            "none": "No help needed.",
            "one_person": "One person to help.",
            "two_person_lift": "It takes two people to lift him.",
        },
        "neighbor_no": "No.",
        "room": "Yes, we have room.",
        "promise": "Is someone coming to get me?",
        "hold_no": "No, that's all.",
        "correction_people": "Oh wait, sorry. Someone else is here too. There are {n} of us.",
        "fallback": "Okay.",
    },
    "es": {
        "yes": "Sí, correcto.",
        "can_leave": {"yes": "Sí, podemos salir.", "no": "No, no puedo salir sola.", "unsure": "No sé."},
        "people_1": "Vivo sola.",
        "people_n": "Somos {n} personas.",
        "pets": {True: "Sí, tengo un perro.", False: "No, no tengo mascotas."},
        "car": {True: "Sí, tengo carro.", False: "No, no tengo carro."},
        "mobility": {
            "walks": "No, todos caminan.",
            "walker": "Uso andador.",
            "manual_wheelchair": "Usa una silla manual.",
            "power_wheelchair": "Usa una silla eléctrica.",
            "bedbound": "Está en cama.",
        },
        "chair_kind": {"power_wheelchair": "Es una silla eléctrica.", "manual_wheelchair": "Es una silla manual."},
        "oxygen": {
            "oxygen": "Sí, uso oxígeno.",
            "dialysis": "Necesito diálisis.",
            "other": "Sí, otras necesidades médicas.",
            "none": "No, nada de eso.",
        },
        "assistance": {
            "none": "Ninguna.",
            "one_person": "Una persona para ayudar.",
            "two_person_lift": "Se necesitan dos personas para levantarlo.",
        },
        "neighbor_no": "No.",
        "room": "Sí, tengo espacio.",
        "promise": "¿Alguien viene por mí?",
        "hold_no": "No, es todo.",
        "correction_people": "Espere, perdón. Hay alguien más aquí. Somos {n} personas.",
        "fallback": "Está bien.",
    },
}


def persona_for(hh: dict[str, Any]) -> dict[str, Any]:
    pid = hh.get("personaId")
    personas = sim_data.personas()
    for p in personas:
        if p.get("id") == pid:
            return p
    # No persona link (e.g. a home added by hand): pick one deterministically from the household id.
    h = int(hashlib.sha1(hh["_id"].encode()).hexdigest(), 16)
    return personas[h % len(personas)]


def true_record(persona: dict[str, Any]) -> dict[str, Any]:
    """The persona's ground truth, with `correction` ("peopleCount 1 -> 2") applied: the value
    after the correction is the true one. Some personas only record it in the correction."""
    truth = dict(persona.get("truth") or {})
    m = re.search(r"peopleCount\s+(\d+)\s*->\s*(\d+)", persona.get("correction") or "")
    if m:
        truth["peopleCount"] = int(m.group(2))
    return truth


class Resident:
    """Answers one question at a time from a persona's ground truth."""

    def __init__(self, persona: dict[str, Any]):
        self.p = persona
        self.truth: dict[str, Any] = true_record(persona)
        self.lang = persona.get("language") if persona.get("language") in ANSWERS else "en"
        self.corrects_people = "peopleCount" in (persona.get("correction") or "")
        self.pushes = "promise" in (persona.get("tricky") or "")
        self._pending_correction = False
        self._asked_promise = False

    def _n(self, n: int) -> str:
        words = _NUM[self.lang]
        return words[n] if 0 <= n < len(words) else str(n)

    def answer(self, goal: str | None) -> str:
        a = ANSWERS[self.lang]
        t = self.truth
        if self._pending_correction:
            self._pending_correction = False
            return a["correction_people"].format(n=self._n(int(t.get("peopleCount") or 2)))
        if goal in ("address", "readback"):
            return a["yes"]
        if goal == "can_leave":
            return a["can_leave"].get(t.get("canLeave") or "yes", a["yes"])
        if goal == "people":
            n = int(t.get("peopleCount") or 1)
            if self.corrects_people and n > 1:
                self._pending_correction = True  # say "just me" now, correct on the next turn
                return a["people_1"]
            return a["people_1"] if n == 1 else a["people_n"].format(n=self._n(n))
        if goal == "pets":
            return a["pets"][bool(t.get("pets"))]
        if goal == "car":
            return a["car"][t.get("hasCar") is not False]
        if goal == "mobility":
            return a["mobility"].get(t.get("mobility") or "walks", a["mobility"]["walks"])
        if goal == "chair_kind":
            return a["chair_kind"].get(t.get("mobility"), a["chair_kind"]["manual_wheelchair"])
        if goal == "oxygen":
            med = t.get("medical") or []
            key = next((m for m in ("oxygen", "dialysis", "other") if m in med), "none")
            return a["oxygen"][key]
        if goal == "assistance":
            return a["assistance"].get(t.get("assistance") or "one_person", a["assistance"]["one_person"])
        if goal == "neighbor_rider":
            return self.p.get("neighbor") or a["neighbor_no"]
        if goal == "neighbor_driver":
            if (self.p.get("expect") or {}).get("role") == "can_help":
                return f"{a['room']} {self.p['neighbor']}" if self.p.get("neighbor") else a["room"]
            return a["neighbor_no"]
        if goal == "hold":
            if self.pushes and not self._asked_promise:
                self._asked_promise = True
                return a["promise"]
            return a["hold_no"]
        return a["fallback"]


async def run_call(
    db: AsyncIOMotorDatabase,
    household_id: str,
    call_id: str,
    *,
    turn_delay_s: float = 0.0,
    call_type: str = "outbound",
) -> dict[str, Any]:
    """Play one full stand-in call through the real agent. Returns the last turn result."""
    hh = await db.households.find_one({"_id": household_id})
    if hh is None:
        raise ValueError(f"household {household_id} not found")
    resident = Resident(persona_for(hh))
    await session.start(db, household_id, call_type, call_id)
    out: dict[str, Any] = {"done": False}
    for _ in range(MAX_TURNS):
        call = await db.calls.find_one({"_id": call_id}, {"agent.goal": 1, "agent.done": 1})
        agent = (call or {}).get("agent") or {}
        if agent.get("done"):
            break
        if turn_delay_s:
            await asyncio.sleep(turn_delay_s)
        out = await session.turn(
            db,
            call_id,
            household_id,
            resident.answer(agent.get("goal")),
            resident.lang,
            use_models=get_settings().standin_use_models,  # off by default: no model bill for 200 homes
        )
        if out.get("done"):
            break
    return out
