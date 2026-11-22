"""A grid-city world (the `scottsdale-fire` scenario): one continuous neighborhood area. All simulated.

data/scenario-<name>.json gives the area box, a ragged mountain edge on its east side, a grid of
contiguous zones, shelters, staging points, ignition and wind. Homes fill the area on local streets
(Phoenix-area 1/8-mile grid), denser in a few neighborhood blobs, and stop at the mountain edge, so the
map reads as one city district. Same personas, fire model and request rules as the canyon.

Built for scale: every write is batched (one insert per 2,000 homes, one per collection otherwise).
"""

import math
import random
from datetime import datetime, timedelta
from typing import Any, Literal

from motor.motor_asyncio import AsyncIOMotorDatabase

from api import audit
from api.core.util import new_id
from api.sim import data
from api.sim import seed as base
from api.sim.grid import lonlat, xy

STREET_M = 201.0  # 1/8 mile: local streets
STREETS = [
    "Desert Vista Trl",
    "Saguaro Rd",
    "Ocotillo Dr",
    "Palo Verde Ln",
    "Mesquite St",
    "Jojoba Rd",
    "Cholla Dr",
    "Ironwood Way",
    "Quail Run",
    "Coyote Pass",
    "Sunrise Dr",
    "Brittlebush Ln",
]
NAMED = [  # the demo's drivers keep their names and ids
    ("vh_luis", "paratransit", "Luis", "airpark"),
    ("vh_maria", "paratransit", "Maria", "pima_bell"),
    ("vh_tom", "agency_van", "Tom", "shea_scottsdale"),
    ("vh_ana", "agency_van", "Ana", "thompson_peak"),
]
EXTRA_PARATRANSIT = ["Rosa M.", "Kevin", "Imani", "Grace", "Andre", "Mei", "Victor", "Nadia", "Paul", "Ines", "Tariq"]
EXTRA_VANS = ["Hector", "Beth", "Omar"]
BUSES = [
    ("vh_bus_1", "Bus 1 · Ray", "hayden_shea"),
    ("vh_bus_2", "Bus 2 · Lin", "airpark"),
    ("vh_bus_3", "Bus 3 · Moss", "thompson_peak"),
    ("vh_bus_4", "Bus 4 · Ada", "shea_scottsdale"),
]
# Stretcher patients need an ambulance; without one they could only be escalated, never driven out.
# City scale: mutual-aid strike teams (20 rigs) for the ~90 stretcher patients the census finds.
_MEDICS = ["Kai", "Lucia", "Ortiz", "Bree", "Dan", "Amara", "Jules", "Rafi", "Kim", "Sol", "Tia", "Wes",
           "Abe", "Cara", "Dev", "Esme", "Finn", "Gia", "Hal", "Iris"]  # fmt: skip
_MEDIC_AT = ["shea_scottsdale", "pima_bell", "airpark", "thompson_peak", "hayden_shea"]
AMBULANCES = [
    (f"vh_medic_{k}", f"Medic {k} · {name}", _MEDIC_AT[(k - 1) % len(_MEDIC_AT)]) for k, name in enumerate(_MEDICS, 1)
]
NEIGHBOR_NAMES = [
    "Sam",
    "Priya",
    "Dave",
    "Lena",
    "Marcus",
    "Elena",
    "Noah",
    "Fatima",
    "Chris",
    "Aiko",
    "Diego",
    "Hannah",
    "Raj",
    "Tess",
    "Malik",
    "Sofia",
    "Ben",
    "Yara",
    "Owen",
    "Leah",
    "Mateo",
    "Zoe",
    "Ivan",
    "Nora",
    "Kofi",
    "Ruth",
    "Hugo",
    "Maya",
    "Eli",
    "Ana B.",
    "Tom R.",
    "Lily",
    "Jamal",
    "Sara",
    "Pedro",
    "Ava",
    "Ken",
    "June",
    "Luca",
    "Ines B.",
    "Omar K.",
    "Rhea",
    "Seth",
    "Cleo",
    "Arjun",
    "Beth K.",
    "Gus",
    "Dina",
    "Felix",
    "Mina",
    "Rex",
    "Tara",
    "Vik",
    "Wren",
    "Xavi",
    "Yuki",
    "Zane",
    "Alma",
    "Bo",
    "Cyrus",
    "Iris B.",
    "Joel",
    "Kara",
    "Liam",
    "Mona",
    "Nico",
    "Olga",
    "Pia",
    "Quinn",
    "Ravi",
    "Sana",
    "Teo",
    "Uma",
    "Vera",
    "Wade",
    "Ximena",
    "Yosef",
    "Zara",
    "Abel",
    "Bea",
    "Cal",
    "Dora",
    "Emil",
    "Faye",
    "Gil",
    "Hana",
    "Ike",
    "Jada",
    "Kurt",
    "Lola",
]


def is_grid(sc: dict[str, Any]) -> bool:
    return sc.get("network") == "grid"


def bounds(sc: dict[str, Any]) -> list[list[float]]:
    return sc.get("bounds") or sc["area"]


def _edge_lon(sc: dict[str, Any], lat: float) -> float:
    """The mountain front: homes stop west of this longitude (a little ragged, like a real foothill line)."""
    (_, s), (_, n) = sc["area"]
    me = sc.get("mountainEdge") or {}
    a, b = me.get("lonAtSouth", sc["area"][1][0]), me.get("lonAtNorth", sc["area"][1][0])
    f = (lat - s) / (n - s) if n != s else 0
    return a + (b - a) * f + 0.0035 * math.sin(lat * 900) + 0.002 * math.sin(lat * 2300)


def place_home(sc: dict[str, Any], rng: random.Random, blobs: list[tuple[float, float, float]]) -> tuple[float, float]:
    """Inside the area and west of the mountain edge, on a local street; 55% in neighborhood blobs."""
    (w, s), (e, n) = sc["area"]
    while True:
        if rng.random() < 0.5:
            cx, cy, r = rng.choice(blobs)
            lon, lat = rng.gauss(cx, r), rng.gauss(cy, r * 0.85)
        else:
            lon, lat = rng.uniform(w, e), rng.uniform(s, n)
        if not (w <= lon <= e and s <= lat <= n) or lon > _edge_lon(sc, lat):
            continue
        x, y = xy((lon, lat))
        if rng.random() < 0.5:
            y = round(y / STREET_M) * STREET_M + rng.uniform(-10, 10)
        else:
            x = round(x / STREET_M) * STREET_M + rng.uniform(-10, 10)
        lon, lat = lonlat((x, y))
        if lon <= _edge_lon(sc, lat):
            return lon, lat


def zone_of(sc: dict[str, Any], p: tuple[float, float]) -> dict[str, Any]:
    for z in sc["zones"]:
        (w, s), (e, n) = z["box"]
        if w <= p[0] <= e and s <= p[1] <= n:
            return z
    return min(sc["zones"], key=lambda z: abs(p[0] - (z["box"][0][0] + z["box"][1][0]) / 2))


def zone_polygon(z: dict[str, Any]) -> list[list[float]]:
    (w, s), (e, n) = z["box"]
    return [[w, s], [e, s], [e, n], [w, n], [w, s]]


# Maricopa County address grid: house numbers count 800 a mile east of Central Ave, so Scottsdale Rd is
# 7200 E. A home's number follows from where it is, and every home on one east-west row is on the same
# street (names cycle through STREETS row by row). Real-looking and consistent; still simulated.
SCOTTSDALE_RD_LON = -111.926
MILE_DEG_LON = 1609.34 / (111_320 * math.cos(math.radians(33.66)))
ROW_DEG_LAT = 201 / 111_320  # the street grid the homes snap to


def _address(rng: random.Random, loc: tuple[float, float] | None = None) -> str:
    if loc is None:
        return f"{rng.randint(70, 140) * 100 + rng.randint(1, 99)} E {rng.choice(STREETS)}, Scottsdale, AZ (simulated)"
    lon, lat = loc
    number = 7200 + round((lon - SCOTTSDALE_RD_LON) / MILE_DEG_LON * 800)
    number = number - number % 2 + (1 if rng.random() < 0.5 else 0)  # odd on the south side, even on the north
    street = STREETS[round(lat / ROW_DEG_LAT) % len(STREETS)]
    return f"{max(100, number)} E {street}, Scottsdale, AZ 85260 (simulated)"


def _vehicle(_id: str, kind: str, name: str, loc: tuple[float, float], now: datetime) -> dict[str, Any]:
    cap = {
        "paratransit": ({"seats": 4, "wheelchair": 2, "stretcher": 0}, 2, True),
        # City agency vans are lift-equipped (two wheelchair positions); the canyon's vans are not.
        "agency_van": ({"seats": 8, "wheelchair": 2, "stretcher": 0}, 2, True),
        "bus": ({"seats": 30, "wheelchair": 1, "stretcher": 0}, 2, True),
        "ambulance": ({"seats": 2, "wheelchair": 1, "stretcher": 1}, 2, True),
        "neighbor": ({"seats": 3, "wheelchair": 0, "stretcher": 0}, 1, False),
    }[kind]
    return {
        "_id": _id,
        "kind": kind,
        "driverName": name,
        "capacity": cap[0],
        "crew": cap[1],
        "lift": cap[2],
        "phone": "",
        "location": base._point(loc),
        "heading": 0,
        "speedMps": 0,
        "status": "idle",
        "safety": {"state": "ok"},
        "simulated": True,
        "lastSeenAt": now,
    }


async def seed(
    db: AsyncIOMotorDatabase,
    sc: dict[str, Any],
    *,
    homes: int | None,
    rng: random.Random,
    now: datetime,
    census: Literal["none", "instant"],
    first_arrival_min: float,
) -> dict[str, Any]:
    homes = homes or int(sc.get("defaultHomes", 6000))
    removed = await base.reset(db)

    zones = sc["zones"]
    await db.zones.delete_many({"simulated": True})
    await db.zones.insert_many(
        [
            {
                "_id": z["id"],
                "name": z["name"],
                "county": z.get("county", "Maricopa"),
                "status": "ready",
                "polygon": {"type": "Polygon", "coordinates": [zone_polygon(z)]},
                "source": "manual",
                "simulated": True,
                "updatedAt": now,
            }
            for z in zones
        ]
    )

    groups: dict[str, list[dict[str, Any]]] = {"ride_chair": [], "ride": [], "other": []}
    for p in data.personas():
        groups[data.persona_group(p)].append(p)

    # One neighborhood blob per zone (east ones pulled west of the mountain edge), so every tile is lived in.
    blobs = []
    for z in zones:
        (zw, zs), (ze, zn) = z["box"]
        cy = (zs + zn) / 2 + rng.uniform(-0.004, 0.004)
        cx = min((zw + ze) / 2, _edge_lon(sc, cy) - 0.008) + rng.uniform(-0.004, 0.004)
        blobs.append((cx, cy, rng.uniform(0.006, 0.009)))
    ignition = (float(sc["ignition"][0]), float(sc["ignition"][1]))
    wind_from = float(sc["wind"]["fromDeg"])
    raw = []
    for _ in range(homes):
        loc = place_home(sc, rng, blobs)
        raw.append((base.fire_minutes(loc, ignition, wind_from), base._pick_persona(rng, groups), loc))

    earliest = min(m for m, _, _ in raw)
    ignited_at = now + timedelta(minutes=first_arrival_min - earliest)
    taken = {h["_id"] async for h in db.households.find({"_id": {"$regex": "^hh_sim_"}}, {"_id": 1})}
    docs: list[dict[str, Any]] = []
    for i, (fire_min, persona, loc) in enumerate(sorted(raw, key=lambda r: r[0])):
        arrival = now + timedelta(minutes=first_arrival_min + (fire_min - earliest))
        docs.append(
            {
                "_id": base._free_id(f"hh_sim_{i:05d}", taken),
                "address": _address(rng, loc),
                "location": base._point(loc),
                "zoneId": zone_of(sc, loc)["id"],
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
    for k in range(0, len(docs), 2000):
        await db.households.insert_many(docs[k : k + 2000], ordered=False)

    from api.hazard import fire
    from api.hazard.spread import FireRun

    run = FireRun(new_id("fire"), sc["name"], ignition, wind_from, ignited_at)
    # seededAt = when the warning went out (the evacuation replay's minute 0)
    await db.hazards.replace_one({"_id": fire.RUN_ID}, {**fire.run_doc(run), "seededAt": now}, upsert=True)

    # ── vehicles: vans and buses at staging points on the south and west edges, neighbors at home ──
    stage = {k: tuple(v) for k, v in sc["staging"].items()}
    spots = list(stage.values())
    vehicles = [_vehicle(i, kind, name, stage[at], now) for i, kind, name, at in NAMED]
    vehicles += [
        _vehicle(f"vh_para_{k}", "paratransit", name, spots[k % len(spots)], now)
        for k, name in enumerate(EXTRA_PARATRANSIT, start=1)
    ]
    vehicles += [
        _vehicle(f"vh_van_{k}", "agency_van", name, spots[(k + 2) % len(spots)], now)
        for k, name in enumerate(EXTRA_VANS, start=1)
    ]
    vehicles += [_vehicle(i, "bus", name, stage[at], now) for i, name, at in BUSES]
    vehicles += [_vehicle(i, "ambulance", name, stage[at], now) for i, name, at in AMBULANCES]
    helpers = [d for d in docs if data.persona_group(base._persona(d["personaId"])) == "other"]
    for k, (name, home) in enumerate(
        zip(
            NEIGHBOR_NAMES, rng.sample(helpers or docs, k=min(len(NEIGHBOR_NAMES), len(helpers or docs))), strict=False
        ),
        start=1,
    ):
        vehicles.append(_vehicle(f"vh_nb_{k}", "neighbor", name, tuple(home["location"]["coordinates"]), now))
    await db.vehicles.insert_many(vehicles)

    shelters = sc["shelters"]
    await db.shelters.insert_many(
        [{**s, "location": base._point(tuple(s["location"])), "occupied": 0, "simulated": True} for s in shelters]
    )

    requests = await base.instant_census(db) if census == "instant" else 0
    await audit.log(db, "sim_seeded", sc["name"], homes=len(docs), vehicles=len(vehicles), census=census)
    return {
        "scenario": sc["name"],
        "households": len(docs),
        "vehicles": len(vehicles),
        "shelters": len(shelters),
        "fire": {"runId": run.run_id, "ignitedAt": ignited_at},
        "zones": [z["id"] for z in zones],
        "requests": requests,
        "removed": removed,
        "simulated": True,
    }
