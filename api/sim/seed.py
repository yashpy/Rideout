"""POST /sim/seed: the simulated world for a scenario. Everything written here has `simulated: true`.

- ~200 households along SR 89A between Midgley Bridge and Pine Flat (Census tract 16.02 covers this
  stretch), each linked to one of the personas in data/personas.json so stand-in calls have a script and a ground truth.
- The mix follows the middle column of docs/simulation.md: 12% need a ride, 40% of those need a
  wheelchair space or a lift. Homes get a placeholder fire arrival time until api/hazard/.
- 8 vehicles (2 paratransit, 2 agency vans, 4 neighbors), 2 shelters, 2 zones (status `ready`).
- `census="instant"` skips the calls: every home is "answered" with its persona's expected outcome and
  ride requests are created through api.requests. Handy for dispatch work before the dialer exists.
"""

import math
import random
from datetime import timedelta
from typing import Any, Literal

from motor.motor_asyncio import AsyncIOMotorDatabase

from api import audit
from api import requests as rq
from api.core.util import new_id, utcnow
from api.sim import data
from api.sim.geo import Road, meters

# docs/simulation.md, middle column
NEED_RIDE_SHARE = 0.12
HEAVY_SHARE_OF_RIDERS = 0.40

# Homes sit between Midgley Bridge and Pine Flat, denser around the canyon's clusters.
CLUSTERS = [  # (fraction along the tract, weight) Indian Gardens, Slide Rock, West Fork, Pine Flat
    (0.18, 3),
    (0.45, 4),
    (0.75, 3),
    (0.97, 2),
]

FALLBACK_IGNITION = (-111.78, 34.97)

# Fire placeholder: elliptical spread downwind from the ignition point.
HEAD_SPREAD_M_PER_MIN = 60.0
ECCENTRICITY = 0.7

VEHICLES: list[dict[str, Any]] = [
    {
        "_id": "vh_luis",
        "kind": "paratransit",
        "driverName": "Luis",
        "start": "uptown",
        "capacity": {"seats": 4, "wheelchair": 2, "stretcher": 0},
        "crew": 2,
        "lift": True,
    },
    {
        "_id": "vh_maria",
        "kind": "paratransit",
        "driverName": "Maria",
        "start": "west_sedona",
        "capacity": {"seats": 4, "wheelchair": 2, "stretcher": 0},
        "crew": 2,
        "lift": True,
    },
    {
        "_id": "vh_tom",
        "kind": "agency_van",
        "driverName": "Tom",
        "start": "uptown_north",
        "capacity": {"seats": 8, "wheelchair": 0, "stretcher": 0},
        "crew": 2,
        "lift": False,
    },
    {
        "_id": "vh_ana",
        "kind": "agency_van",
        "driverName": "Ana",
        "start": "y",
        "capacity": {"seats": 8, "wheelchair": 0, "stretcher": 0},
        "crew": 2,
        "lift": False,
    },
    *[
        {
            "_id": f"vh_nb_{i}",
            "kind": "neighbor",
            "driverName": name,
            "start": "neighbor",
            "capacity": {"seats": 3, "wheelchair": 0, "stretcher": 0},
            "crew": 1,
            "lift": False,
        }
        for i, name in enumerate(["Sam", "Priya", "Dave", "Lena"], start=1)
    ],
]

SHELTERS = [
    # Sourced (scenario.json shelter, S-05). Capacity is an assumption.
    {
        "_id": "sh_red_rock_hs",
        "name": "Red Cross shelter, Sedona Red Rock High School",
        "location": (-111.8243, 34.8517),
        "capacity": 150,
    },
    # Assumption: a north-side shelter, reachable only while SR 89A north of Pine Flat is open.
    {
        "_id": "sh_fort_tuthill",
        "name": "Fort Tuthill County Park (assumption)",
        "location": (-111.6950, 35.1390),
        "capacity": 100,
    },
]


def _point(c: tuple[float, float]) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [round(c[0], 6), round(c[1], 6)]}


def _bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    dlon = math.radians(b[0] - a[0])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def fire_minutes(home: tuple[float, float], ignition: tuple[float, float], wind_from_deg: float) -> float:
    """Minutes for the front to reach `home`: fastest downwind, slowest upwind (elliptical spread)."""
    downwind = (wind_from_deg + 180) % 360
    theta = math.radians(_bearing_deg(ignition, home) - downwind)
    speed = HEAD_SPREAD_M_PER_MIN * (1 - ECCENTRICITY) / (1 - ECCENTRICITY * math.cos(theta))
    return meters(ignition, home) / speed


def _free_id(want: str, taken: set[str]) -> str:
    """`want`, or `want_r1`, `want_r2`, … if a real household still holds it."""
    out, n = want, 0
    while out in taken:
        n += 1
        out = f"{want}_r{n}"
    taken.add(out)
    return out


def tract(road: Road) -> tuple[float, float, float]:
    """Chainages of the census tract: (Midgley Bridge, Pine Flat, Slide Rock = zone 14/15 split)."""
    return (
        road.project((-111.7497, 34.8875))[0],
        road.project((-111.7383, 35.0122))[0],
        road.project((-111.7529, 34.9437))[0],
    )


def place_home(rng: random.Random, road: Road, tract_from: float, span: float) -> tuple[float, float]:
    """A home along SR 89A in the tract, denser around the canyon's clusters, 40–300 m off the road."""
    if rng.random() < 0.6:
        frac = rng.choices(CLUSTERS, weights=[w for _, w in CLUSTERS])[0][0]
        frac = min(1.0, max(0.0, rng.gauss(frac, 0.05)))
    else:
        frac = rng.random()
    offset = rng.choice((-1, 1)) * rng.uniform(40, 300)
    return road.point_at(tract_from + frac * span, offset)


def _pick_persona(rng: random.Random, groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    r = rng.random()
    if r < NEED_RIDE_SHARE * HEAVY_SHARE_OF_RIDERS and groups["ride_chair"]:
        g = "ride_chair"
    elif r < NEED_RIDE_SHARE and groups["ride"]:
        g = "ride"
    else:
        g = "other" if groups["other"] else "ride"
    return rng.choice(groups[g])


def _priority(record: dict[str, Any], need: dict[str, Any]) -> float:
    """Same spirit as the agent's transparent score: heavier needs and medical needs go first."""
    return (
        1.0
        + 2 * (need.get("wheelchair") or 0)
        + 3 * (need.get("stretcher") or 0)
        + (1 if need.get("lift") else 0)
        + 1.5 * len(record.get("medical") or [])
    )


async def reset(db: AsyncIOMotorDatabase) -> dict[str, int]:
    """Delete the simulated world. Real households (simulated: false, e.g. a kiosk visitor's phone) stay."""
    sim_hh = [h["_id"] async for h in db.households.find({"simulated": True}, {"_id": 1})]
    sim_rq = [r["_id"] async for r in db.requests.find({"householdId": {"$in": sim_hh}}, {"_id": 1})]
    sim_vh = [v["_id"] async for v in db.vehicles.find({"simulated": True}, {"_id": 1})]
    out = {
        "assignments": (
            await db.assignments.delete_many({"$or": [{"requestId": {"$in": sim_rq}}, {"vehicleId": {"$in": sim_vh}}]})
        ).deleted_count,
        "callbacks": (await db.callbacks.delete_many({"requestId": {"$in": sim_rq}})).deleted_count,
        "calls": (await db.calls.delete_many({"householdId": {"$in": sim_hh}})).deleted_count,
        "requests": (await db.requests.delete_many({"_id": {"$in": sim_rq}})).deleted_count,
        "households": (await db.households.delete_many({"_id": {"$in": sim_hh}})).deleted_count,
        "vehicles": (await db.vehicles.delete_many({"_id": {"$in": sim_vh}})).deleted_count,
    }
    for coll in ("shelters", "plans", "roadClosures", "hazards"):
        out[coll] = (await db[coll].delete_many({})).deleted_count
    return out


async def seed(
    db: AsyncIOMotorDatabase,
    *,
    scenario: str = "pocket-fire",
    homes: int | None = None,
    rng_seed: int = 42,
    census: Literal["none", "instant"] = "none",
    first_arrival_min: float = 90.0,
) -> dict[str, Any]:
    rng = random.Random(rng_seed)
    sc = data.scenario(scenario)
    now = utcnow()
    from api.sim import world  # here: world imports geo, which this module also imports

    await world.save(db, scenario)
    await db.simControl.update_one({"_id": "sim"}, {"$unset": {"world": ""}})  # an older build kept it here
    if scenario in world.GRID_SCENARIOS:
        from api.sim import metro

        return await metro.seed(
            db, sc, homes=homes, rng=rng, now=now, census=census, first_arrival_min=first_arrival_min
        )
    homes = homes or 200
    road = Road()

    removed = await reset(db)

    # ── zones: south half (14) and north half (15) of the tract ──────────────
    tract_from, tract_to, split = tract(road)
    zone_meta = {z["id"]: z for z in sc.get("zones", [])}
    zone_ids = list(zone_meta) or ["zone_oak_creek_14", "zone_oak_creek_15"]
    zone_south, zone_north = zone_ids[0], zone_ids[-1]
    for zid, (c1, c2) in ((zone_south, (tract_from, split)), (zone_north, (split, tract_to))):
        z = zone_meta.get(zid, {})
        await db.zones.update_one(
            {"_id": zid},
            {
                "$set": {
                    "name": z.get("name", zid),
                    "county": z.get("county", "Coconino"),
                    "status": "ready",
                    "polygon": {"type": "Polygon", "coordinates": [road.corridor(c1, c2, 600)]},
                    "source": "manual",
                    "simulated": True,
                    "updatedAt": now,
                }
            },
            upsert=True,
        )

    # the Phoenix scenario's zones go when the canyon comes back
    await db.zones.delete_many({"_id": {"$nin": [zone_south, zone_north]}, "simulated": True})

    # ── households ──────────────────────────────────────────────────────────
    groups: dict[str, list[dict[str, Any]]] = {"ride_chair": [], "ride": [], "other": []}
    for p in data.personas():
        groups[data.persona_group(p)].append(p)

    ignition = tuple(sc.get("ignition", FALLBACK_IGNITION))
    wind_from = float((sc.get("wind") or {}).get("fromDeg", 225))
    span = tract_to - tract_from
    raw: list[tuple[float, dict[str, Any], tuple[float, float]]] = []
    for _ in range(homes):
        loc = place_home(rng, road, tract_from, span)
        raw.append((fire_minutes(loc, ignition, wind_from), _pick_persona(rng, groups), loc))

    earliest = min(m for m, _, _ in raw)
    # The fire replay (api/hazard/fire.py) starts at this ignition time, so its front reaches each home
    # exactly at that home's fireArrivalAt below.
    ignited_at = now + timedelta(minutes=first_arrival_min - earliest)
    # A home the kiosk handed to a visitor keeps its hh_sim_ id but is real now (simulated: false), so the
    # reset above leaves it alone. Never reuse an id that's still taken.
    taken = {h["_id"] async for h in db.households.find({"_id": {"$regex": "^hh_sim_"}}, {"_id": 1})}
    docs: list[dict[str, Any]] = []
    for i, (fire_min, persona, loc) in enumerate(sorted(raw, key=lambda r: road.project(r[2])[0])):
        ch = road.project(loc)[0]
        arrival = now + timedelta(minutes=first_arrival_min + (fire_min - earliest))
        docs.append(
            {
                "_id": _free_id(f"hh_sim_{i:03d}", taken),
                "address": f"{1000 + int(ch / 8)} N State Route 89A, Sedona, AZ 86336",
                "location": _point(loc),
                "zoneId": zone_south if ch < split else zone_north,
                "phone": f"+1555{i:07d}",  # fictional
                "language": persona.get("language", "en"),
                "simulated": True,
                "personaId": persona["id"],
                "record": {},
                "corrections": [],
                "reach": "not_called",
                "role": "unknown",
                "fireArrivalAt": arrival,
                "deadlineAt": arrival - timedelta(minutes=10),
                "doorPriority": 0.0,
                "updatedAt": now,
            }
        )
    await db.households.insert_many(docs)

    from api.hazard import fire  # here, not at the top: api.hazard.spread imports this module
    from api.hazard.spread import FireRun

    run = FireRun(new_id("fire"), scenario, (float(ignition[0]), float(ignition[1])), wind_from, ignited_at)
    # seededAt = when the warning went out (the evacuation replay's minute 0)
    await db.hazards.replace_one({"_id": fire.RUN_ID}, {**fire.run_doc(run), "seededAt": now}, upsert=True)

    # ── vehicles ────────────────────────────────────────────────────────────
    starts = {
        "uptown": (-111.7615, 34.8705),
        # On SR 89A ~850 m north of Uptown, so Tom's van doesn't sit on top of Luis's on the console map.
        "uptown_north": (-111.7568, 34.8773),
        "west_sedona": (-111.8000, 34.8610),
        "y": (-111.7650, 34.8635),
    }
    helpers = [d for d in docs if data.persona_group(_persona(d["personaId"])) == "other"]
    neighbor_homes = rng.sample(helpers or docs, k=min(4, len(helpers or docs)))
    nb = iter(neighbor_homes)
    vehicles = []
    for v in VEHICLES:
        if v["start"] == "neighbor":
            home = next(nb, None)
            loc = tuple(home["location"]["coordinates"]) if home else starts["uptown"]
        else:
            loc = starts[v["start"]]
        vehicles.append(
            {
                **{k: val for k, val in v.items() if k != "start"},
                "phone": "",
                "location": _point(loc),
                "heading": 0,
                "speedMps": 0,
                "status": "idle",
                "safety": {"state": "ok"},
                "simulated": True,
                "lastSeenAt": now,
            }
        )
    await db.vehicles.insert_many(vehicles)

    await db.shelters.insert_many(
        [{**s, "location": _point(s["location"]), "occupied": 0, "simulated": True} for s in SHELTERS]
    )

    requests = await instant_census(db) if census == "instant" else 0
    await audit.log(db, "sim_seeded", scenario, homes=len(docs), vehicles=len(vehicles), census=census)
    return {
        "scenario": scenario,
        "households": len(docs),
        "vehicles": len(vehicles),
        "shelters": len(SHELTERS),
        "fire": {"runId": run.run_id, "ignitedAt": ignited_at},
        "zones": [zone_south, zone_north],
        "requests": requests,
        "removed": removed,
        "simulated": True,
    }


def _persona(pid: str) -> dict[str, Any]:
    for p in data.personas():
        if p["id"] == pid:
            return p
    return {}


async def instant_census(
    db: AsyncIOMotorDatabase,
    *,
    limit: int | None = None,
    zone_ids: list[str] | None = None,
    return_answered: bool = False,
) -> int:
    """Answer simulated, not-yet-reached homes with their persona's expected outcome. → requests made.

    Homes the fire reaches first go first. `limit` answers only that many (the progressive census calls
    this in waves so the map lights up like a real call-out); `zone_ids` keeps it to those zones.
    Household writes are batched (thousands of homes in the Phoenix scenario)."""
    q: dict[str, Any] = {"simulated": True, "reach": "not_called"}
    if zone_ids:
        q["zoneId"] = {"$in": zone_ids}
    cursor = db.households.find(q).sort("fireArrivalAt", 1)
    if limit:
        cursor = cursor.limit(limit)
    homes = [hh async for hh in cursor]
    now = utcnow()
    by_persona: dict[str, list[str]] = {}
    riders = []
    for hh in homes:
        pid = hh.get("personaId", "")
        by_persona.setdefault(pid, []).append(hh["_id"])
        expect = _persona(pid).get("expect") or {}
        if expect.get("role") == "needs_ride":
            truth = {k: v for k, v in (_persona(pid).get("truth") or {}).items() if v is not None}
            riders.append((hh, truth, expect))
    for pid, ids in by_persona.items():  # one write per persona, not per home
        p = _persona(pid)
        truth = {k: v for k, v in (p.get("truth") or {}).items() if v is not None}
        role = (p.get("expect") or {}).get("role") or "unknown"
        await db.households.update_many(
            {"_id": {"$in": ids}, "reach": "not_called"},
            {"$set": {"record": truth, "reach": "answered", "role": role, "updatedAt": now}},
        )
    items = []
    for hh, truth, expect in riders:
        need = {
            "seats": max(1, int(truth.get("peopleCount") or 1)),
            "wheelchair": 0,
            "stretcher": 0,
            "crew": 1,
            "lift": False,
            **(expect.get("need") or {}),
        }
        items.append(
            {
                "householdId": hh["_id"],
                "need": need,
                "deadlineAt": hh.get("deadlineAt"),
                "priority": _priority(truth, need),
            }
        )
    await rq.bulk_create_received(db, items)  # one write for the whole wave, not three per rider
    return len(homes) if return_answered else len(items)
