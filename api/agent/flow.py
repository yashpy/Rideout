"""The call state machine. Pure functions: no database, no network, so tests and evals run it directly.

Stages: greet → confirm_address → can_leave → household (people, pets) → needs (mobility, oxygen)
        → chair_kind (if wheelchair) → assistance → readback → neighbor → status/hold → goodbye

Each stage is made of one or more *goals* (one question each). The next goal is always the first
one the record and call state don't answer yet, so a resident who says three things at once skips
three questions, and a correction at any point simply changes the record.

A turn has two halves, because the request status depends on the record:
  1. `apply()`   interpreter output → record changes + call-state changes + escalations
  2. `respond()` (after the service has written the record and upserted the request)
                 → the sentences to speak, chosen by code from templates.py
"""

from dataclasses import dataclass, field
from typing import Any

from api.agent import templates as T
from api.agent.interpreter import Interp

ANNOUNCED = frozenset({"driver_accepted", "en_route", "reassigning", "arrived"})
MAX_READBACKS = 3

STAGE_OF = {
    "address": "confirm_address",
    "can_leave": "can_leave",
    "people": "household",
    "pets": "household",
    "car": "household",
    "mobility": "needs",
    "oxygen": "needs",
    "chair_kind": "chair_kind",
    "assistance": "assistance",
    "readback": "readback",
    "neighbor_rider": "neighbor",
    "neighbor_driver": "neighbor",
    "status": "status",
    "hold": "hold",
    "goodbye": "goodbye",
}

# Escalations that create a request on their own (a life threat needs a dispatcher even if
# we don't know anything else yet), in order of precedence.
ESCALATION_ORDER = ["medical", "flames", "address_unconfirmed", "language"]
LIFE_THREATS = frozenset({"medical", "flames"})


def new_state(mode: str = "outbound", language: str = "en") -> dict[str, Any]:
    return {
        "mode": mode,  # outbound | inbound | callback
        "language": language,
        "stage": "greet",
        "goal": None,  # the goal of the last question we asked
        "reasks": {},  # goal → failed attempts
        "skipped": [],  # goals given up after a re-ask
        "addressConfirmed": None,
        "chairPending": False,
        "readbackDone": False,
        "readbacks": 0,
        "awaitingFix": False,
        "neighborAsked": False,
        "neighbors": [],
        "statusTold": False,
        "holdAsked": False,
        "announcedStatus": None,
        "escalations": [],
        "lastQuestion": None,
        "done": False,
    }


# ── what we still need to know ────────────────────────────────────────────────


def needs_ride(record: dict[str, Any], state: dict[str, Any] | None = None) -> bool:
    """canLeave = no/unsure, or no car. (The personas expect anyone without a car to get a request,
    and silence is never safe, so no car is enough.)"""
    if record.get("canLeave") in ("no", "unsure"):
        return True
    return record.get("hasCar") is False


def _needs_path(record: dict[str, Any]) -> bool:
    return record.get("canLeave") in ("no", "unsure") or record.get("hasCar") is False


def next_goal(state: dict[str, Any], record: dict[str, Any]) -> str:
    """The first thing we don't know yet."""
    skip = set(state.get("skipped") or [])

    def open_(goal: str, missing: bool) -> bool:
        return missing and goal not in skip

    if state.get("mode") == "callback":
        if not state.get("statusTold"):
            return "status"
        return "goodbye" if state.get("holdAsked") else "hold"

    if open_("address", state.get("addressConfirmed") is None):
        return "address"
    if open_("can_leave", record.get("canLeave") is None):
        return "can_leave"
    if open_("people", record.get("peopleCount") is None):
        return "people"
    if open_("pets", record.get("pets") is None):
        return "pets"
    if record.get("canLeave") == "yes" and open_("car", record.get("hasCar") is None):
        return "car"
    if _needs_path(record):
        if open_("mobility", record.get("mobility") is None and not state.get("chairPending")):
            return "mobility"
        if open_("chair_kind", bool(state.get("chairPending"))):
            return "chair_kind"
        if open_("oxygen", record.get("medical") is None):
            return "oxygen"
        limited = record.get("mobility") not in (None, "walks")
        if open_("assistance", limited and record.get("assistance") is None):
            return "assistance"
    rider = needs_ride(record, state)
    if rider and not state.get("readbackDone") and "readback" not in skip:
        return "readback"
    if not state.get("neighborAsked"):
        return "neighbor_rider" if rider else "neighbor_driver"
    if rider and not state.get("statusTold"):
        return "status"
    if not state.get("holdAsked"):
        return "hold"
    return "goodbye"


def role_for(record: dict[str, Any], state: dict[str, Any]) -> str | None:
    """Map color. None = leave as is."""
    if needs_ride(record, state):
        return "needs_ride"
    if state.get("canHelp"):
        return "can_help"
    if record.get("canLeave") == "yes" and record.get("hasCar") is not False:
        return "left"  # leaving on their own (we told them to leave now)
    return None


# ── half 1: apply the interpreter output ──────────────────────────────────────


@dataclass
class Applied:
    changes: dict[str, Any] = field(default_factory=dict)  # record fields to PATCH
    new_escalations: list[str] = field(default_factory=list)
    filled: bool = False  # the goal we asked about got an answer
    switched_language: bool = False
    simple: bool = False  # re-ask the same goal with simpler words


ASKED_US = frozenset({"asks_ride", "wants_time", "asks_what_to_do", "asks_why", "asks_repeat"})


def apply(state: dict[str, Any], record: dict[str, Any], it: Interp) -> Applied:
    """Fold one interpreted utterance into the record and call state. Mutates `state`."""
    out = Applied()
    goal = state.get("goal")

    if it.language and it.language != state.get("language") and it.language in T.LINES:
        state["language"] = it.language
        out.switched_language = True

    if it.emergency:
        _escalate(state, out, it.emergency)

    changes = dict(it.set)
    if changes.get("mobility") == "wheelchair":
        changes.pop("mobility")
        if record.get("mobility") not in ("manual_wheelchair", "power_wheelchair"):
            state["chairPending"] = True
    elif changes.get("mobility") in ("manual_wheelchair", "power_wheelchair", "walks", "walker", "bedbound"):
        state["chairPending"] = False
    if "medical" in changes:
        if changes["medical"]:
            changes["medical"] = sorted(set(record.get("medical") or []) | set(changes["medical"]))
        elif record.get("medical"):  # an empty list never wipes a need already heard
            changes.pop("medical")
    changes = {k: v for k, v in changes.items() if record.get(k) != v}
    out.changes = changes

    merged = {**record, **changes}
    if goal == "address":
        if it.answer == "yes":
            state["addressConfirmed"] = True
            out.filled = True
    elif goal == "readback":
        if changes:  # a fix: read back again, unless we've done it enough times
            state["readbacks"] = state.get("readbacks", 0) + 1
            state["readbackDone"] = state["readbacks"] >= MAX_READBACKS
            out.filled = True
        elif it.answer == "yes":
            state["readbackDone"] = True
            out.filled = True
        elif it.answer == "no":
            state["readbacks"] = state.get("readbacks", 0) + 1
            state["awaitingFix"] = True  # ask what to change
            out.filled = True
    elif goal in ("neighbor_rider", "neighbor_driver"):
        if it.answer != "unclear" or it.neighbors:
            state["neighborAsked"] = True
            out.filled = True
            if goal == "neighbor_driver" and it.answer == "yes":
                state["canHelp"] = True
        state["neighbors"] = [*state.get("neighbors", []), *it.neighbors][:10]
    elif goal == "hold":
        state["holdAsked"] = True
        out.filled = True
    elif goal == "status":
        out.filled = True
    elif goal is not None:
        out.filled = _goal_filled(goal, record, merged, state)
    if it.neighbors and goal not in ("neighbor_rider", "neighbor_driver"):
        state["neighbors"] = [*state.get("neighbors", []), *it.neighbors][:10]

    # Not answered (and they didn't ask us something or talk to someone else)? Re-ask once, then give up.
    # A useful answer to a different question (a correction, extra detail) isn't a failure either.
    waiting = "not_to_agent" in it.flags and not changes
    excused = out.filled or bool(changes) or bool(it.flags & ASKED_US) or out.switched_language or waiting
    if goal and goal not in ("status", "goodbye") and "goodbye" not in it.flags and not excused:
        tries = state["reasks"].get(goal, 0) + 1
        state["reasks"][goal] = tries
        if tries >= 2:
            extra = give_up(state, goal, out)
            out.changes.update({k: v for k, v in extra.items() if record.get(k) != v})
        else:
            out.simple = True
    return out


def _goal_filled(goal: str, before: dict, after: dict, state: dict) -> bool:
    key = {
        "can_leave": "canLeave",
        "people": "peopleCount",
        "pets": "pets",
        "car": "hasCar",
        "mobility": "mobility",
        "oxygen": "medical",
        "chair_kind": "mobility",
        "assistance": "assistance",
    }[goal]
    if goal == "mobility" and state.get("chairPending"):
        return True
    if goal == "chair_kind":
        return after.get("mobility") in ("manual_wheelchair", "power_wheelchair")
    return after.get(key) is not None


def _escalate(state: dict, out: Applied, reason: str) -> None:
    if reason not in state["escalations"]:
        state["escalations"].append(reason)
        out.new_escalations.append(reason)


def top_escalation(state: dict) -> str | None:
    for r in ESCALATION_ORDER:
        if r in state.get("escalations", []):
            return r
    return None


def give_up(state: dict[str, Any], goal: str, out: Applied) -> dict[str, Any]:
    """Second failure on a goal: escalate or use a safe default, then move on. Returns record changes."""
    state["skipped"] = [*state.get("skipped", []), goal]
    changes: dict[str, Any] = {}
    if goal == "address":
        state["addressConfirmed"] = False
        _escalate(state, out, "address_unconfirmed")
    elif goal == "can_leave":
        changes["canLeave"] = "unsure"  # unsure gets a request: silence is never safe
    elif goal == "chair_kind":
        state["chairPending"] = False
        changes["mobility"] = "power_wheelchair"  # the bigger vehicle fits both kinds
        changes["confidence"] = {"mobility": 0.5}
    if len(state["skipped"]) >= 3:
        _escalate(state, out, "language")  # the resident and the agent aren't understanding each other
    return changes


# ── half 2: what to say ───────────────────────────────────────────────────────


def respond(
    state: dict[str, Any],
    record: dict[str, Any],
    it: Interp,
    applied: Applied,
    *,
    ack: str | None,
    status: str | None,
    ride: dict[str, Any] | None,
    address: str,
) -> list[str]:
    """Pick every sentence for this turn. Mutates `state` (goal, stage, flags told)."""
    lang = state["language"]
    say: list[str] = []
    goal = state.get("goal")

    if applied.switched_language and lang == "es":
        say.append(T.line(lang, "switched"))
    for reason in applied.new_escalations:
        if reason in LIFE_THREATS:
            say.append(T.line(lang, reason))

    if "not_to_agent" in it.flags and not applied.changes and it.answer == "unclear" and not say:
        return []  # they're talking to someone in the room; wait

    status_said = False
    if status in ANNOUNCED and status != state.get("announcedStatus"):
        say.append(T.status_line(lang, status, ride))  # live status change mid-call
        state["announcedStatus"] = status
        status_said = True

    if ack and not applied.switched_language:
        say.insert(0, ack)

    if "wants_time" in it.flags:
        say.append(T.line(lang, "dont_know"))
    if it.flags & {"asks_ride", "wants_time"} and not status_said:
        say.append(_status_for(lang, record, state, status, ride))
        status_said = True
    if "asks_what_to_do" in it.flags:
        say.append(T.line(lang, "advice"))
    if "asks_why" in it.flags and goal in T.QUESTIONS[lang]:
        say.append(T.why(lang, goal))
    if status_said and needs_ride(record, state):
        state["statusTold"] = True

    if "goodbye" in it.flags:
        if needs_ride(record, state) and not state.get("statusTold"):
            say.append(_status_for(lang, record, state, status, ride))
        elif not needs_ride(record, state) and state.get("mode") != "callback":
            say.append(T.line(lang, "leave_now"))
        return _finish(state, say, lang)

    if goal == "hold" and it.answer == "yes" and not it.set and not it.neighbors:
        pass  # "yes" with nothing else: just move on
    elif goal == "hold" and (it.set or it.neighbors or it.answer == "unclear"):
        say.append(T.line(lang, "noted"))

    nxt = next_goal(state, record)
    if "asks_repeat" in it.flags and state.get("lastQuestion") and nxt == goal:
        say.append(state["lastQuestion"])
        return _set_goal(state, nxt, say)

    if goal == "readback" and state.get("awaitingFix") and not state.get("readbackDone"):
        say.append(T.line(lang, "readback_fix"))
        state["awaitingFix"] = False
        state["lastQuestion"] = say[-1]
        return _set_goal(state, "readback", say)

    if nxt == "status":
        if not status_said:
            say.append(_status_for(lang, record, state, status, ride))
            state["announcedStatus"] = status if status in ANNOUNCED else state.get("announcedStatus")
        state["statusTold"] = True
        if state.get("mode") == "callback" and status == "en_route":
            say.append(T.line(lang, "callback_more"))
        nxt = next_goal(state, record)
    if nxt == "goodbye":
        if not needs_ride(record, state) and state.get("mode") != "callback":
            say.append(T.line(lang, "leave_now"))
        return _finish(state, say, lang)

    q = ask(state, record, nxt, address=address, simple=applied.simple and nxt == goal)
    say.append(q)
    return _set_goal(state, nxt, say)


def ask(state: dict, record: dict, goal: str, *, address: str, simple: bool = False) -> str:
    lang = state["language"]
    fmt: dict[str, Any] = {"address": address}
    if goal == "readback":
        fmt["summary"] = T.summary(lang, record, chair_pending=state.get("chairPending", False))
    q = T.question(lang, goal, simple=simple, **fmt)
    state["lastQuestion"] = q
    return q


def opening(
    state: dict[str, Any], record: dict[str, Any], *, address: str, status: str | None, ride: dict | None
) -> list[str]:
    """What the agent says when the call connects."""
    lang = state["language"]
    if state["mode"] == "callback":
        say = [T.line(lang, "greet_callback"), T.status_line(lang, status, ride)]
        if status == "en_route":  # the other status lines already say when we'll call again
            say.append(T.line(lang, "callback_more"))
        state["statusTold"] = True
        state["announcedStatus"] = status
        nxt = next_goal(state, record)
        say.append(ask(state, record, nxt, address=address))
        return _set_goal(state, nxt, say)
    say = [T.line(lang, "greet")]
    if lang == "en" and T.line(lang, "spanish_offer"):
        say.append(T.line(lang, "spanish_offer"))
    nxt = next_goal(state, record)
    if nxt == "goodbye":
        return _finish(state, say, lang)
    say.append(ask(state, record, nxt, address=address))
    return _set_goal(state, nxt, say)


def _status_for(lang: str, record: dict, state: dict, status: str | None, ride: dict | None) -> str:
    if status is None and record.get("canLeave") == "yes" and not needs_ride(record, state):
        return T.STATUS[lang]["not_needed"]
    return T.status_line(lang, status, ride)


def _set_goal(state: dict, goal: str, say: list[str]) -> list[str]:
    state["goal"] = goal
    state["stage"] = STAGE_OF.get(goal, goal)
    return say


def _finish(state: dict, say: list[str], lang: str) -> list[str]:
    say.append(T.line(lang, "goodbye"))
    state["goal"] = "goodbye"
    state["stage"] = "goodbye"
    state["done"] = True
    return say


# ── record → request need ─────────────────────────────────────────────


def compute_need(record: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Seats, wheelchair spaces, stretcher, crew and lift from what we heard."""
    mob = record.get("mobility")
    chair = mob in ("manual_wheelchair", "power_wheelchair") or bool(state and state.get("chairPending"))
    bed = mob == "bedbound"
    lift_help = record.get("assistance") == "two_person_lift"
    return {
        "seats": max(1, int(record.get("peopleCount") or 1)),
        "wheelchair": 1 if chair else 0,
        "stretcher": 1 if bed else 0,
        "crew": 2 if (lift_help or bed) else 1,
        "lift": bool(mob == "power_wheelchair" or bed or (state and state.get("chairPending"))),
    }


def compute_priority(record: dict[str, Any], escalation: str | None = None) -> float:
    """Transparent score: higher = sooner. Deadlines come from the hazard service, not from here."""
    score = 1.0
    score += {"bedbound": 3, "power_wheelchair": 2, "manual_wheelchair": 2, "walker": 1}.get(
        record.get("mobility") or "", 0
    )
    score += 1.5 * len(record.get("medical") or [])
    if record.get("assistance") == "two_person_lift":
        score += 1
    if escalation in LIFE_THREATS:
        score += 5
    return score
