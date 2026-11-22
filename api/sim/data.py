"""Scenario + personas (data/). Read at seed time; missing files fall back to small built-ins."""

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# repo/data locally; /app/data in the image (Dockerfile copies the `data` build context there).
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))

FALLBACK_SCENARIO: dict[str, Any] = {
    "name": "pocket-fire",
    "ignition": [-111.78, 34.97],
    "wind": {"speedMps": 11.2, "fromDeg": 225},
    "zones": [
        {"id": "zone_oak_creek_14", "name": "Oak Creek Canyon (zone 14)", "county": "Coconino"},
        {"id": "zone_oak_creek_15", "name": "Oak Creek Canyon (zone 15)", "county": "Coconino"},
    ],
    "shelter": {"name": "American Red Cross shelter, Sedona Red Rock High School"},
}

FALLBACK_PERSONAS: list[dict[str, Any]] = [
    {
        "id": "fb_ride_chair",
        "language": "en",
        "truth": {
            "canLeave": "no",
            "peopleCount": 2,
            "mobility": "power_wheelchair",
            "assistance": "two_person_lift",
            "hasCar": False,
        },
        "expect": {"role": "needs_ride", "need": {"seats": 2, "wheelchair": 1, "crew": 2, "lift": True}},
    },
    {
        "id": "fb_ride",
        "language": "en",
        "truth": {
            "canLeave": "no",
            "peopleCount": 1,
            "mobility": "walker",
            "assistance": "one_person",
            "hasCar": False,
        },
        "expect": {"role": "needs_ride", "need": {"seats": 1, "wheelchair": 0, "crew": 1, "lift": False}},
    },
    {
        "id": "fb_left",
        "language": "en",
        "truth": {"canLeave": "yes", "peopleCount": 2, "mobility": "walks", "hasCar": True},
        "expect": {"role": "left"},
    },
]


def _load(name: str) -> Any | None:
    path = DATA_DIR / name
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        log.warning("%s not found; using built-in fallback", path)
    except json.JSONDecodeError as e:
        log.error("%s is not valid JSON (%s); using built-in fallback", path, e)
    return None


@lru_cache
def scenario(name: str = "pocket-fire") -> dict[str, Any]:
    """data/scenario.json (the Pocket Fire) or data/scenario-<name>.json (e.g. scottsdale-fire)."""
    for file in ("scenario.json", f"scenario-{name}.json"):
        data = _load(file) if (DATA_DIR / file).exists() else None
        if data and data.get("name") == name:
            return data
    if name != "pocket-fire":
        log.warning("data/scenario-%s.json missing; that scenario needs it", name)
    return {**FALLBACK_SCENARIO, "name": name}


@lru_cache
def personas() -> list[dict[str, Any]]:
    data = _load("personas.json")
    return data if isinstance(data, list) and data else FALLBACK_PERSONAS


def persona_group(p: dict[str, Any]) -> str:
    """ride_chair | ride | other, from the persona's expected outcome (what a correct call produces)."""
    e = p.get("expect") or {}
    if e.get("role") != "needs_ride":
        return "other"
    n = e.get("need") or {}
    heavy = n.get("wheelchair") or n.get("lift") or n.get("stretcher") or (n.get("crew") or 1) > 1
    return "ride_chair" if heavy else "ride"
