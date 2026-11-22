"""Duplicate requests: two callers for the same home → one request.

When a household's request is created or its needs change, compare it with the other open requests:

  1. Location: the two homes must be within 50 m (rule check, always on).
  2. Identity: the same address once normalized ("1225 N State Route 89A" == "1225 north sr 89a"),
     or, when GEMINI_API_KEY is set, Gemini embeddings of "address + needs" with cosine > 0.9.

The newer request gets `dupOf = <older request id>` (the solver and the console skip it), and its needs
are merged into the older one (the larger value of each field), so nobody's need is lost.

Atlas Vector Search: with a few hundred open requests the 50 m filter leaves a handful of candidates,
so we compare their embeddings in Python. TODO(Atlas): move the comparison to a `$vectorSearch`
index on `requests.embedding` once the Atlas cluster is up; the logic stays the same.
"""

import logging
import math
import re
from typing import Any

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from api import audit
from api import requests as rq
from api.core.config import get_settings
from api.core.util import utcnow

log = logging.getLogger(__name__)

RADIUS_M = 50.0
EMBED_THRESHOLD = 0.9
EMBED_MODEL = "gemini-embedding-001"

_WORDS = {
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "state route": "sr",
    "highway": "hwy",
    "street": "st",
    "road": "rd",
    "avenue": "ave",
    "drive": "dr",
    "lane": "ln",
    "arizona": "az",
}


def normalize_address(addr: str) -> str:
    a = (addr or "").lower()
    a = re.sub(r"[.,#]", " ", a)
    for long, short in _WORDS.items():
        a = re.sub(rf"\b{long}\b", short, a)
    a = re.sub(r"\b\d{5}(-\d{4})?\b", " ", a)  # zip codes vary between callers
    return " ".join(a.split())


def same_address(a: str, b: str) -> bool:
    """Same house number and street; one caller may add the city or state ("... sedona az")."""
    ta, tb = normalize_address(a).split(), normalize_address(b).split()
    if not ta or not tb or not ta[0][:1].isdigit() or ta[0] != tb[0]:
        return False
    short, long = sorted((ta, tb), key=len)
    return len(short) >= 2 and long[: len(short)] == short


def meters(a: list[float] | tuple[float, float], b: list[float] | tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def _coords(hh: dict[str, Any]) -> list[float] | None:
    c = (hh.get("location") or {}).get("coordinates")
    return list(c) if c and len(c) == 2 else None


def describe(hh: dict[str, Any], need: dict[str, Any] | None) -> str:
    """Text we embed: the address and what the home needs (no names: we don't store them)."""
    r = hh.get("record") or {}
    parts = [hh.get("address", ""), f"{r.get('peopleCount') or '?'} people", r.get("mobility") or ""]
    parts += r.get("medical") or []
    if need:
        parts.append(f"wheelchair {need.get('wheelchair', 0)} stretcher {need.get('stretcher', 0)}")
    return " | ".join(p for p in parts if p)


async def embed(texts: list[str]) -> list[list[float]] | None:
    """Gemini embeddings, or None when no key / the call fails (then only the address rule applies)."""
    key = get_settings().gemini_api_key
    if not key or not texts:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{EMBED_MODEL}:batchEmbedContents"
    body = {"requests": [{"model": f"models/{EMBED_MODEL}", "content": {"parts": [{"text": t}]}} for t in texts]}
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            r = await http.post(url, headers={"x-goog-api-key": key}, json=body)  # header: URLs get logged
            r.raise_for_status()
            return [e["values"] for e in r.json()["embeddings"]]
    except Exception as e:
        log.warning("gemini embeddings failed (%s); address rule only", type(e).__name__)
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def merge_need(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for k in ("seats", "wheelchair", "stretcher", "crew"):
        out[k] = max(int(a.get(k) or 0), int(b.get(k) or 0))
    out["lift"] = bool(a.get("lift") or b.get("lift"))
    out["seats"] = max(1, out["seats"])
    out["crew"] = max(1, out["crew"])
    return out


async def check(db: AsyncIOMotorDatabase, request: dict[str, Any]) -> dict[str, Any] | None:
    """If `request` duplicates an older open request, mark it and merge needs. Returns the primary, or None."""
    if request.get("dupOf") or request.get("status") == "closed":
        return None
    hh = await db.households.find_one({"_id": request["householdId"]})
    here = _coords(hh or {})
    if hh is None or here is None:
        return None

    others = [
        r
        async for r in db.requests.find(
            {"_id": {"$ne": request["_id"]}, "status": {"$in": list(rq.OPEN_STATUSES)}, "dupOf": None}
        )
    ]
    if not others:
        return None
    homes = {h["_id"]: h async for h in db.households.find({"_id": {"$in": [r["householdId"] for r in others]}})}
    near = []
    for r in others:
        h = homes.get(r["householdId"])
        if h and h["_id"] != hh["_id"] and (c := _coords(h)) and meters(here, c) <= RADIUS_M:
            near.append((r, h))
    if not near:
        return None

    match: tuple[dict, dict, str] | None = None
    for r, h in near:
        if same_address(hh.get("address", ""), h.get("address", "")):
            match = (r, h, "same address")
            break
    if match is None:
        vecs = await embed([describe(hh, request.get("need"))] + [describe(h, r.get("need")) for r, h in near])
        if vecs:
            best = max(range(len(near)), key=lambda i: cosine(vecs[0], vecs[i + 1]))
            score = cosine(vecs[0], vecs[best + 1])
            if score > EMBED_THRESHOLD:
                match = (near[best][0], near[best][1], f"embedding {score:.2f}")
    if match is None:
        return None

    primary, _, why = match
    # The older request stays; the newer one points at it.
    if (request.get("createdAt") or utcnow()) < (primary.get("createdAt") or utcnow()):
        primary, request = request, primary
    await db.requests.update_one(
        {"_id": request["_id"], "dupOf": None},
        {"$set": {"dupOf": primary["_id"], "updatedAt": utcnow()}, "$inc": {"version": 1}},
    )
    merged = merge_need(primary.get("need") or {}, request.get("need") or {})
    if merged != primary.get("need"):
        primary = await rq.upsert_for_household(db, primary["householdId"], need=merged)
    await audit.log(
        db, "request_duplicate", why, requestId=request["_id"], dupOf=primary["_id"], householdId=request["householdId"]
    )
    return primary
