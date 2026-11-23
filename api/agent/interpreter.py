"""Interpreter: one resident utterance → structured changes (CONTRACT §5).

Order of attempts:
  1. Gemini (`GEMINI_MODEL`) with a JSON response schema, cut off at 2.5 s.
  2. Claude Sonnet (`CLAUDE_FALLBACK_MODEL`) with the same prompt.
  3. A rule-based parser (no AI). It understands yes/no, counts, and common mobility words,
     so the call still moves forward if both models are down (ARCHITECTURE §14).

The interpreter never chooses the next question and never writes about a ride. Its only
free text is `ack`, which goes through honesty.py before anyone hears it.
"""

import asyncio
import builtins
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from api.core.config import get_settings

log = logging.getLogger(__name__)

GEMINI_TIMEOUT_S = 2.5
CLAUDE_TIMEOUT_S = 4.0

FLAGS = frozenset({"asks_ride", "goodbye", "asks_repeat", "wants_time", "not_to_agent", "asks_what_to_do", "asks_why"})
FIELDS = {
    "canLeave": {"yes", "no", "unsure"},
    "peopleCount": int,
    "mobility": {"walks", "walker", "manual_wheelchair", "power_wheelchair", "bedbound", "wheelchair"},
    "assistance": {"none", "one_person", "two_person_lift"},
    "medical": {"oxygen", "dialysis", "other", "none"},
    "pets": bool,
    "hasCar": bool,
    "olderAdult": bool,
}


@dataclass
class Interp:
    set: dict[str, Any] = field(default_factory=dict)  # parsed and validated field changes
    guessed: list[str] = field(default_factory=list)
    answer: str = "unclear"  # yes | no | unclear
    emergency: str | None = None  # medical | flames
    flags: builtins.set[str] = field(default_factory=builtins.set)  # `set` above shadows the builtin
    neighbors: list[str] = field(default_factory=list)
    language: str | None = None
    ack: str | None = None
    source: str = "none"  # gemini | claude | rules
    fallback: bool = False
    latency_ms: float = 0.0


# ── prompt ────────────────────────────────────────────────────────────────────

PRINCIPLES = """Call-taker principles:
1. Truth over comfort. Say only what the record supports.
2. Promise effort, never outcomes. Never say or imply someone is safe, that help is coming, or when.
3. Calm and short. One idea per sentence, plain words.
4. Show you heard. Reflect their words briefly ("A power chair.").
5. Name a feeling once, then move on. Never scripted sympathy.
6. Say why you ask when they ask.
7. Honest about automation: you are the RideOut automated assistant, working with the dispatchers.
8. Life threats first. Medical emergency or flames: flag immediately.
9. Respect their choice if they won't leave. Don't argue.
10. Adult to adult. Take their word about a disability."""

SYSTEM = f"""You interpret one utterance from a resident during a wildfire evacuation phone call.
You do NOT talk to the resident. Code picks every question and every sentence about rides.
Return only JSON matching the schema.

Fields you may set (use exactly these names and values), as "field=value" strings in "set":
- canLeave = yes | no | unsure   (can everyone in the home leave on their own right now)
- peopleCount = integer          (people at home, including the speaker; "just me" = 1)
- mobility = walks | walker | manual_wheelchair | power_wheelchair | bedbound | wheelchair
  (the MOST limited person; use "wheelchair" if the kind of chair is not said)
- assistance = none | one_person | two_person_lift
- medical = oxygen | dialysis | other | none   (one entry per need)
- pets = true | false
- hasCar = true | false
- olderAdult = true | false   (true if anyone at home is 65 or older: an age of 65+, "elderly", "senior")
Only include facts stated or corrected in THIS utterance. A correction ("no wait, my son is here")
overrides the record: set the new value. Put fields you inferred rather than heard in "guessed".

"answer": yes / no / unclear, the direct answer to the question just asked.
"emergency": "medical" if someone needs medical help now, "flames" if fire is at or on the home. Else omit.
"flags": asks_ride (asks if someone is coming / about their ride), wants_time (asks when / how long),
  asks_what_to_do, asks_why (asks why we need to know), asks_repeat, goodbye (wants to end the call),
  not_to_agent (talking to someone else in the room).
"neighbors": short descriptions of neighbors they say need help.
"language": "es" if they speak Spanish, "en" if English.
"ack": at most 6 words reflecting what they said ("A power chair.", "Two of you, got it.").
  No digits. No promises, no reassurance, no advice, nothing about help, rides, time, safety or the fire.
  Leave it empty if nothing to reflect.

{PRINCIPLES}"""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "set": {"type": "array", "items": {"type": "string"}},
        "guessed": {"type": "array", "items": {"type": "string"}},
        "answer": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "emergency": {"type": "string", "enum": ["medical", "flames", "none"]},
        "flags": {"type": "array", "items": {"type": "string", "enum": sorted(FLAGS)}},
        "neighbors": {"type": "array", "items": {"type": "string"}},
        "language": {"type": "string", "enum": ["en", "es"]},
        "ack": {"type": "string"},
    },
    "required": ["set", "answer", "flags", "ack"],
}


def build_prompt(text: str, stage: str, goal: str | None, record: dict, recent: list[dict]) -> str:
    convo = "\n".join(f"{t.get('speaker')}: {t.get('text')}" for t in recent[-6:])
    return (
        f"Stage: {stage}\nQuestion just asked is about: {goal or 'nothing specific'}\n"
        f"Record so far: {json.dumps(record, default=str)}\n"
        f"Recent turns:\n{convo or '(none)'}\n\nResident just said: {text!r}"
    )


# ── parsing ───────────────────────────────────────────────────────────────────


def _coerce(name: str, raw: str) -> Any:
    kind = FIELDS.get(name)
    v = raw.strip().strip("\"'").lower()
    if kind is int:
        n = int(float(v))
        if not 0 <= n <= 30:
            raise ValueError(v)
        return n
    if kind is bool:
        if v in ("true", "yes", "1"):
            return True
        if v in ("false", "no", "0"):
            return False
        raise ValueError(v)
    if isinstance(kind, set) and v in kind:
        return v
    raise ValueError(v)


def parse_set(items: list[str]) -> dict[str, Any]:
    """["peopleCount=2", "medical=oxygen"] → {"peopleCount": 2, "medical": ["oxygen"]}. Bad items are dropped."""
    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            continue
        name, raw = item.split("=", 1)
        name = name.strip()
        try:
            val = _coerce(name, raw)
        except (ValueError, TypeError):
            log.info("interpreter: dropped bad field %r", item)
            continue
        if name == "medical":
            if val != "none":
                out.setdefault("medical", [])
                if val not in out["medical"]:
                    out["medical"].append(val)
            else:
                out.setdefault("medical", [])
        else:
            out[name] = val
    return out


def from_json(data: dict[str, Any], source: str) -> Interp:
    emergency = data.get("emergency")
    return Interp(
        set=parse_set(data.get("set") or []),
        guessed=[g for g in data.get("guessed") or [] if g in FIELDS],
        answer=data.get("answer") if data.get("answer") in ("yes", "no", "unclear") else "unclear",
        emergency=emergency if emergency in ("medical", "flames") else None,
        flags={f for f in data.get("flags") or [] if f in FLAGS},
        neighbors=[str(n) for n in data.get("neighbors") or []][:5],
        language=data.get("language") if data.get("language") in ("en", "es") else None,
        ack=(data.get("ack") or "").strip() or None,
        source=source,
    )


# ── model calls ───────────────────────────────────────────────────────────────


async def _gemini(prompt: str, http: httpx.AsyncClient) -> dict[str, Any]:
    s = get_settings()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{s.gemini_model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 300,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
        },
    }
    r = await http.post(url, headers={"x-goog-api-key": s.gemini_api_key}, json=body)  # header: URLs get logged
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


async def _claude(prompt: str, http: httpx.AsyncClient) -> dict[str, Any]:
    s = get_settings()
    body = {
        "model": s.claude_fallback_model,
        "max_tokens": 300,
        "temperature": 0,
        "system": SYSTEM + "\n\nReturn one JSON object with keys: " + ", ".join(SCHEMA["properties"]) + ".",
        "messages": [{"role": "user", "content": prompt}],
    }
    r = await http.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01"},
        json=body,
    )
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in Claude reply")
    return json.loads(m.group(0))


_http: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(CLAUDE_TIMEOUT_S, connect=2.0))
    return _http


async def interpret(
    text: str,
    *,
    stage: str,
    goal: str | None,
    record: dict,
    recent: list[dict],
    language: str = "en",
    use_models: bool = True,
) -> Interp:
    """Gemini → Claude → rules. Never raises. `use_models=False` goes straight to the free rules
    (stand-in calls and evals, so 200 simulated homes never run up a model bill)."""
    t0 = time.perf_counter()
    if not use_models:
        result = rules(text, goal=goal, language=language)
        result.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return result
    s = get_settings()
    prompt = build_prompt(text, stage, goal, record, recent)
    result: Interp | None = None
    fallback = False
    if s.gemini_api_key:
        try:
            data = await asyncio.wait_for(_gemini(prompt, _client()), timeout=GEMINI_TIMEOUT_S)
            result = from_json(data, "gemini")
        except Exception as e:  # timeout, HTTP error, bad JSON
            log.warning("gemini failed (%s); falling back", type(e).__name__)
            fallback = True
    if result is None and s.anthropic_api_key and s.allow_paid_models:  # Claude bills; off unless approved
        try:
            data = await asyncio.wait_for(_claude(prompt, _client()), timeout=CLAUDE_TIMEOUT_S)
            result = from_json(data, "claude")
            fallback = fallback or bool(s.gemini_api_key)
        except Exception as e:
            log.warning("claude failed (%s); using rules", type(e).__name__)
            fallback = True
    if result is None:
        result = rules(text, goal=goal, language=language)
        fallback = fallback or bool(s.gemini_api_key or (s.anthropic_api_key and s.allow_paid_models))
    result.fallback = fallback
    result.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    return result


# ── rule-based interpreter (no AI) ────────────────────────────────────────────

_YES = r"\b(yes|yeah|yep|yup|sure|correct|right|that's right|ok|okay|of course|uh huh|sí|si|claro|correcto|así es)\b"
_NO = r"\b(no|nope|nah|not really|negative|incorrect|wrong|can't|cannot|don't|doesn't|no puedo|tampoco)\b"
_WORDNUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
}


def _has(pat: str, t: str) -> bool:
    return re.search(pat, t, re.IGNORECASE) is not None


def rules(text: str, *, goal: str | None = None, language: str = "en") -> Interp:
    """Keyword parser used when no model answers. Conservative: it only sets what it is sure of."""
    t = text.lower().strip()
    it = Interp(source="rules")
    # "no wait, my son is here" is a correction, not a "no" to the question we just asked.
    correcting = _has(r"^(no,? wait|wait|actually|sorry|oh,? (wait|and)|también|espere|perdón)\b", t)
    lead = re.match(r"^\W*([\wáéíóúñ']+)", t)
    lead_word = lead.group(1) if lead else ""
    if not correcting and re.fullmatch(_YES, lead_word, re.IGNORECASE):
        is_yes, is_no = True, False  # "Yes, ... she has no car" is still a yes
    elif not correcting and re.fullmatch(_NO, lead_word, re.IGNORECASE):
        is_yes, is_no = False, True
    else:
        is_no = _has(_NO, t) and not correcting
        is_yes = _has(_YES, t) and not is_no and not correcting
    it.answer = "yes" if is_yes else "no" if is_no else "unclear"
    if _has(r"\b(español|espanol|spanish|hablo español)\b", t) or _has(r"[ñ¿¡áéíóú]", t):
        it.language = "es"
    if _has(r"\b(not breathing|chest pain|heart attack|unconscious|bleeding|stroke|can't breathe|no respira)\b", t):
        it.emergency = "medical"
    elif _has(r"\b(flames|on fire|fire is here|house is burning|fuego aquí|se quema)\b", t):
        it.emergency = "flames"
    if _has(
        r"\b(is (someone|anyone|somebody|help) coming|send (someone|help|a car|a van|a vehicle)|ride|pick me up"
        r"|(find|get|need) (me )?(a |someone |some )?(vehicle|car|van|driver|help)|alguien viene|un carro)\b",
        t,
    ):
        it.flags.add("asks_ride")
    if _has(r"\b(when|how long|how soon|what time|cuándo|cuando)\b", t):
        it.flags.add("wants_time")
    if _has(r"\b(what should i do|what do i do|qué hago|que hago)\b", t):
        it.flags.add("asks_what_to_do")
    if _has(r"\b(why|por qué|porque)\b", t) and "?" in t or _has(r"^(why|por qué)\b", t):
        it.flags.add("asks_why")
    if _has(r"\b(repeat|say that again|pardon|repita|cómo)\b", t) or _has(r"^\W*(what|sorry|huh|excuse me)\W*\?", t):
        it.flags.add("asks_repeat")
    if _has(r"\b(bye|goodbye|hang up|adiós|adios)\b", t):
        it.flags.add("goodbye")

    if goal in ("neighbor_rider", "neighbor_driver"):
        # Whatever they describe here is about someone else's home, never this record.
        # A question back to us ("is someone coming?") is not a neighbor description.
        asking = "?" in t or bool(it.flags & {"asks_ride", "wants_time", "asks_what_to_do", "asks_why", "asks_repeat"})
        if it.answer != "no" and len(t.split()) > 2 and not asking:
            it.neighbors = [text.strip()[:200]]
        return it

    # mobility words apply whatever the question was
    if _has(r"\b(power chair|electric (wheel)?chair|motorized|silla eléctrica)\b", t):
        it.set["mobility"] = "power_wheelchair"
    elif _has(r"\b(manual (wheel)?chair|push chair|silla manual)\b", t):
        it.set["mobility"] = "manual_wheelchair"
    elif _has(r"\b(wheelchair|silla de ruedas)\b", t):
        it.set["mobility"] = "wheelchair"
    elif _has(r"\b(walker|andador)\b", t):
        it.set["mobility"] = "walker"
    elif _has(r"\b(bedbound|bed-bound|in bed|can't get out of bed|en cama)\b", t):
        it.set["mobility"] = "bedbound"
    if _has(r"\b(oxygen|oxígeno|oxigeno)\b", t) and not _has(r"\bno (oxygen|oxígeno)\b", t):
        it.set["medical"] = ["oxygen"]
    if _has(r"\b(dialysis|diálisis)\b", t):
        it.set.setdefault("medical", []).append("dialysis")
    if _has(r"\b(other medical|medical needs?|necesidades médicas|otras necesidades)\b", t) and not is_no:
        it.set.setdefault("medical", []).append("other")

    # Count people only when asked, or when they clearly talk about the household ("two of us").
    # "It takes two people to lift him" is about help, not household size.
    if goal == "people" or _has(r"\b(just me|only me|solo yo|vivo sola?|of us|somos \w+)\b", t):
        n = _count(t)
        if n:
            it.set["peopleCount"] = n
    if goal == "can_leave" and _has(r"\b(not sure|don't know|maybe|i think so|no sé|no se|tal vez)\b", t):
        it.set["canLeave"] = "unsure"
    elif goal == "can_leave" and it.answer != "unclear":
        it.set["canLeave"] = it.answer
    if goal == "pets" and it.answer != "unclear":
        it.set["pets"] = it.answer == "yes"
    elif _has(r"\b(dog|cat|dogs|cats|perro|gato|pets?)\b", t) and not is_no:
        it.set["pets"] = True
    if _older_adult(t):
        it.set["olderAdult"] = True
    if goal == "car" and it.answer != "unclear":
        it.set["hasCar"] = it.answer == "yes"
    if (
        goal == "mobility"
        and "mobility" not in it.set
        and _has(r"\b(no|everyone (can )?walks?|we can walk|todos)\b", t)
    ):
        it.set["mobility"] = "walks"
    if goal == "oxygen" and "medical" not in it.set and it.answer == "no":
        it.set["medical"] = []
    if goal == "chair_kind" and "mobility" not in it.set and it.answer != "unclear":
        it.set["mobility"] = "power_wheelchair" if it.answer == "yes" else "manual_wheelchair"
    if goal == "assistance":
        if _has(r"\b(two|2|both|lift|lifting|dos|levantar\w*)\b", t) and not is_no:
            it.set["assistance"] = "two_person_lift"
        elif _has(r"\b(one|1|someone|a little|una persona|un poco)\b", t):
            it.set["assistance"] = "one_person"
        elif _has(r"\b(none|no help|nothing|ninguna)\b", t):
            it.set["assistance"] = "none"
        elif it.answer == "yes":  # the simple re-ask is "does it take two people to lift?"
            it.set["assistance"] = "two_person_lift"
        elif it.answer == "no":
            it.set["assistance"] = "one_person"
    return it


_AGE = re.compile(
    r"\b(?:i'?m|i am|she'?s|he'?s|is|aged?|tengo|tiene)\s+(\d{2,3})\b|\b(\d{2,3})\s*(?:years? old|yrs? old|años)\b"
)


def _older_adult(t: str) -> bool:
    """Someone at home is 65+: an age they say out loud, or a plain word for it. Never guessed from the voice."""
    if _has(r"\b(elderly|senior citizen|i'?m (a )?senior|anciano|anciana|tercera edad|persona mayor)\b", t):
        return True
    for m in _AGE.finditer(t):
        n = int(m.group(1) or m.group(2))
        if 65 <= n <= 115:
            return True
    return False


def _count(t: str) -> int | None:
    if _has(r"\b(just me|only me|me alone|i live alone|solo yo|vivo sola?)\b", t):
        return 1
    m = re.search(r"\b(\d{1,2})\b", t)
    if m:
        return int(m.group(1))
    for w, n in _WORDNUM.items():
        if re.search(rf"\b{w}\b", t):
            return n
    return None
