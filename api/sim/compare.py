"""Impact simulation. Analysis, not product: no database, no API.

    uv run --project api python -m api.sim.compare            # → data/sim-results.json

Same homes, same fire, same seed, two ways of getting people out:

- **Today (911 queue):** every rider phones 911 some time after the order. One queue, first come first
  served. No vehicle is dispatched before the 911 delay for that setting. The nearest free unit drives
  out, boards ONE household, takes it to the shelter, then takes the next call. 911 dispatches agency
  vehicles only (neighbors aren't part of 911).
- **RideOut (greedy):** the dialer calls every home at the order, earliest deadline first, 1 call/s. A
  rider's need is known when their call completes, or later through the reach ladder (retry 2 min, retry
  5 min, text, door check). The real dispatcher (api/dispatch/greedy.py) re-plans as needs arrive;
  offers are approved and accepted after a short delay; accepted stops never move.

Metric (docs/simulation.md): share of PEOPLE who needed a ride picked up before their deadline
(deadline = 10 min before the fire reaches the home). Each setting column (low / middle / high) runs
`seeds` worlds. A bar = median of the middle column; its whisker = min..max of the three column medians.
"""

import argparse
import json
import math
import os
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api.dispatch import greedy
from api.sim import data
from api.sim.geo import Road
from api.sim.seed import FALLBACK_IGNITION, SHELTERS, VEHICLES, fire_minutes, place_home, tract

COLUMNS = ("low", "middle", "high")

# docs/simulation.md, column by column. Board minutes: walks / walker / wheelchair / two-person lift.
SETTINGS: dict[str, dict[str, Any]] = {
    "low": {
        "answerShare": 0.40,
        "needRideShare": 0.08,
        "heavyShare": 0.30,
        "fleet": "low",
        "board": {"walks": 2, "walker": 4, "wheelchair": 8, "lift": 12, "stretcher": 12},
        "today911DelayMin": 30,
        "firstArrivalMin": 45,
    },
    "middle": {
        "answerShare": 0.60,
        "needRideShare": 0.12,
        "heavyShare": 0.40,
        "fleet": "middle",
        "board": {"walks": 3, "walker": 6, "wheelchair": 10, "lift": 15, "stretcher": 15},
        "today911DelayMin": 60,
        "firstArrivalMin": 90,
    },
    "high": {
        "answerShare": 0.75,
        "needRideShare": 0.18,
        "heavyShare": 0.50,
        "fleet": "high",
        "board": {"walks": 5, "walker": 8, "wheelchair": 15, "lift": 20, "stretcher": 20},
        "today911DelayMin": 120,
        "firstArrivalMin": 180,
    },
}

# Not on the sheet: assumptions, written into the results file so they can be challenged.
HOMES = 200
CALLS_PER_MIN = 60.0  # one phone number places 1 call/s
CALL_MIN = 2.5  # an answered call until the record (and the request) is complete
RING_MIN = 0.5  # an unanswered ring
LADDER_GAPS_MIN = (2.0, 5.0)  # reach ladder: retry after 2 min, then after 5 min
TEXT_REPLY_MIN = 5.0  # a texted resident who replies does so within 5 min
DOOR_CHECK_MIN = 30.0  # unreached homes go on the door-knock list; a responder gets there 30 min later
DISPATCH_MIN = 2.0  # dispatcher approves + driver accepts
UNLOAD_MIN = greedy.UNLOAD_MIN
TODAY_CALL_WINDOW_MIN = 30.0  # today: riders phone 911 at a random time in the first 30 min after the order
SECOND_PERSON_SHARE = 0.35  # a rider household has 2 people instead of 1
TWO_PERSON_LIFT_SHARE = 0.5  # of heavy riders: two-person lift (else manual wheelchair, one helper)
WALKER_SHARE = 0.4  # of other riders: walker (else walks)

EXTRA = [  # fleet members added beyond the 8 seeded for the high column
    {
        "_id": "vh_jo",
        "kind": "paratransit",
        "driverName": "Jo",
        "capacity": {"seats": 4, "wheelchair": 2, "stretcher": 0},
        "crew": 2,
        "lift": True,
    },
    {
        "_id": "vh_ray",
        "kind": "agency_van",
        "driverName": "Ray",
        "capacity": {"seats": 8, "wheelchair": 0, "stretcher": 0},
        "crew": 2,
        "lift": False,
    },
    {
        "_id": "vh_nb_5",
        "kind": "neighbor",
        "driverName": "Kim",
        "capacity": {"seats": 3, "wheelchair": 0, "stretcher": 0},
        "crew": 1,
        "lift": False,
    },
    {
        "_id": "vh_nb_6",
        "kind": "neighbor",
        "driverName": "Omar",
        "capacity": {"seats": 3, "wheelchair": 0, "stretcher": 0},
        "crew": 1,
        "lift": False,
    },
]
FLEETS = {
    "low": ["vh_luis", "vh_tom", "vh_nb_1", "vh_nb_2"],  # 4 vehicles, 1 wheelchair van
    "middle": [v["_id"] for v in VEHICLES],  # the 8 /sim/seed vehicles
    "high": [v["_id"] for v in VEHICLES] + [v["_id"] for v in EXTRA],  # 12
}
STARTS = {"uptown": (-111.7615, 34.8705), "west_sedona": (-111.8000, 34.8610), "y": (-111.7650, 34.8635)}


@dataclass
class Home:
    loc: tuple[float, float]
    deadline: float  # minutes after the order
    need: greedy.Need | None  # None = doesn't need a ride


@dataclass
class World:
    homes: list[Home]
    fleet: list[dict[str, Any]]  # vehicle specs with a start location
    shelters: list[greedy.Shelter]


@dataclass
class Unit:
    spec: dict[str, Any]
    loc: tuple[float, float]
    free_at: float = 0.0
    load: tuple[int, int, int] = (0, 0, 0)

    def vehicle(self, now: float, extra_delay: float = 0.0) -> greedy.Vehicle:
        cap = self.spec["capacity"]
        return greedy.Vehicle(
            id=self.spec["_id"],
            loc=self.loc,
            seats=cap["seats"],
            wheelchair=cap["wheelchair"],
            stretcher=cap["stretcher"],
            crew=self.spec["crew"],
            lift=self.spec["lift"],
            ready_min=max(self.free_at - now, extra_delay),
            load=self.load,
        )


def make_world(seed: int, column: str, road: Road) -> World:
    s = SETTINGS[column]
    rng = random.Random(seed)
    sc = data.scenario()
    ignition = tuple(sc.get("ignition", FALLBACK_IGNITION))
    wind_from = float((sc.get("wind") or {}).get("fromDeg", 225))
    t_from, t_to, _ = tract(road)

    raw = []
    for _ in range(HOMES):
        loc = place_home(rng, road, t_from, t_to - t_from)
        need = None
        if rng.random() < s["needRideShare"]:
            seats = 2 if rng.random() < SECOND_PERSON_SHARE else 1
            if rng.random() < s["heavyShare"]:
                if rng.random() < TWO_PERSON_LIFT_SHARE:
                    need = greedy.Need(seats=seats, wheelchair=1, crew=2, lift=True, board_kind="lift")
                else:
                    need = greedy.Need(seats=seats, wheelchair=1, crew=1, board_kind="wheelchair")
            else:
                walker = rng.random() < WALKER_SHARE
                need = greedy.Need(seats=seats, crew=1, board_kind="walker" if walker else "walks")
        raw.append((loc, fire_minutes(loc, ignition, wind_from), need))
    earliest = min(m for _, m, _ in raw)
    homes = [Home(loc, s["firstArrivalMin"] + (m - earliest) - 10.0, need) for loc, m, need in raw]

    # Neighbors start at homes that don't need a ride (they're leaving anyway).
    helpers = [h.loc for h in homes if h.need is None]
    nb = iter(rng.sample(helpers, k=min(6, len(helpers))))
    specs = {v["_id"]: v for v in [*VEHICLES, *EXTRA]}
    fleet = []
    for vid in FLEETS[s["fleet"]]:
        v = specs[vid]
        if v["kind"] == "neighbor":
            loc = next(nb, STARTS["uptown"])
        else:
            loc = STARTS.get(v.get("start", "uptown"), STARTS["uptown"])
        fleet.append({**v, "loc": loc})
    shelters = [greedy.Shelter(x["_id"], x["location"], x["capacity"]) for x in SHELTERS]
    return World(homes, fleet, shelters)


def _people(homes: list[Home]) -> int:
    return sum(h.need.seats for h in homes if h.need)


def _nearest_shelter(loc, shelters, travel) -> tuple[tuple[float, float], float] | None:
    best = None
    for s in shelters:
        t = travel(loc, s.loc)
        if math.isfinite(t) and (best is None or t < best[1]):
            best = (s.loc, t)
    return best


def run_today(
    world: World, column: str, seed: int, road: Road, call_share: float = 1.0, neighbors: bool = False
) -> dict[str, float]:
    """One 911 queue, first come first served, nearest free unit, one household per trip."""
    s = SETTINGS[column]
    rng = random.Random(seed * 7919 + 1)
    travel = road.travel_min
    riders = [h for h in world.homes if h.need]
    calls = sorted(
        ((rng.uniform(0, TODAY_CALL_WINDOW_MIN), h) for h in riders if rng.random() < call_share),
        key=lambda c: c[0],
    )
    units = [Unit(v, v["loc"]) for v in world.fleet if neighbors or v["kind"] != "neighbor"]
    on_time = 0
    trace: list[dict[str, float]] = []
    for called_at, h in calls:
        dispatch = max(called_at, s["today911DelayMin"])
        best = None
        for u in units:
            if not u.vehicle(0).fits(h.need):
                continue
            arrive = max(dispatch, u.free_at) + travel(u.loc, h.loc)
            if math.isfinite(arrive) and (best is None or arrive < best[1]):
                best = (u, arrive)
        if best is None:
            continue
        u, pickup = best
        if pickup <= h.deadline:
            on_time += h.need.seats
        trace.append({"calledAt": called_at, "dispatch": dispatch, "pickup": pickup, "deadline": h.deadline})
        done_boarding = pickup + h.need.board_min(s["board"])
        hop = _nearest_shelter(h.loc, world.shelters, travel)
        if hop is None:
            u.free_at, u.loc = math.inf, h.loc
        else:
            u.loc, u.free_at = hop[0], done_boarding + hop[1] + UNLOAD_MIN
    return {"onTime": on_time, "people": _people(world.homes), "trace": trace}


def reveal_times(world: World, column: str, seed: int) -> dict[int, float]:
    """When RideOut learns each rider's need: their call, or a rung of the reach ladder."""
    p = SETTINGS[column]["answerShare"]
    rng = random.Random(seed * 104729 + 3)
    order = sorted(range(len(world.homes)), key=lambda i: world.homes[i].deadline)  # dialer: earliest deadline first
    out: dict[int, float] = {}
    for slot, i in enumerate(order):
        t = slot / CALLS_PER_MIN
        answered = None
        for gap in (0.0, *LADDER_GAPS_MIN):
            t += gap
            if rng.random() < p:
                answered = t + CALL_MIN
                break
            t += RING_MIN
        if answered is None:  # text, then the door-knock list
            answered = t + TEXT_REPLY_MIN if rng.random() < p else t + DOOR_CHECK_MIN
        if world.homes[i].need:
            out[i] = answered
    return out


def run_rideout(world: World, column: str, seed: int, road: Road, batch_min: float = 5 / 60) -> dict[str, float]:
    """Needs arrive over time; the real greedy dispatcher re-plans; accepted stops are frozen."""
    s = SETTINGS[column]
    travel = road.travel_min
    revealed = reveal_times(world, column, seed)
    known = sorted(revealed.items(), key=lambda kv: kv[1])
    trace: list[dict[str, float]] = []
    units = {v["_id"]: Unit(v, v["loc"]) for v in world.fleet}
    pending: dict[int, Home] = {}
    on_time = 0
    k = 0
    while k < len(known) or pending:
        if k >= len(known):
            break  # whoever is still pending has no compatible vehicle
        now = known[k][1] + batch_min  # the solve loop picks up everything learned in this window
        while k < len(known) and known[k][1] <= now:
            pending[known[k][0]] = world.homes[known[k][0]]
            k += 1
        riders = [
            greedy.Rider(id=str(i), loc=h.loc, need=h.need, deadline_min=h.deadline - now) for i, h in pending.items()
        ]
        vehicles = [u.vehicle(now, DISPATCH_MIN) for u in units.values()]
        res = greedy.plan(riders, vehicles, world.shelters, travel, s["board"])
        for p in sorted(res.proposals, key=lambda p: (p.vehicle_id, p.stop_order)):
            h = pending.pop(int(p.request_id))
            u = units[p.vehicle_id]
            pickup = now + p.eta_min
            if pickup <= h.deadline:
                on_time += h.need.seats
            trace.append(
                {
                    "known": revealed[int(p.request_id)],
                    "planned": now,
                    "pickup": pickup,
                    "deadline": h.deadline,
                    "vehicle": p.vehicle_id,
                }
            )
            cap = u.spec["capacity"]
            seats, wc, st = u.load
            n = h.need
            if seats and (
                seats + n.seats > cap["seats"]
                or wc + n.wheelchair > cap["wheelchair"]
                or st + n.stretcher > cap["stretcher"]
            ):
                seats = wc = st = 0  # dropped at a shelter on the way (greedy planned it)
            u.load = (seats + n.seats, wc + n.wheelchair, st + n.stretcher)
            u.loc = h.loc
            u.free_at = pickup + n.board_min(s["board"])
    return {"onTime": on_time, "people": _people(world.homes), "trace": trace}


def _pct(on_time: float, people: float) -> float | None:
    return None if people == 0 else 100.0 * on_time / people


def _summary(values: list[float]) -> dict[str, Any]:
    v = sorted(values)
    if not v:
        return {"median": None, "p5": None, "p95": None, "runs": 0}

    def q(x: float) -> float:
        return round(v[min(len(v) - 1, max(0, round(x * (len(v) - 1))))], 1)

    return {"median": round(statistics.median(v), 1), "p5": q(0.05), "p95": q(0.95), "runs": len(v)}


def simulate(seeds: int = 50, first_seed: int = 1) -> dict[str, Any]:
    road = Road()
    models = {
        "today": lambda w, c, sd: run_today(w, c, sd, road),
        "greedy": lambda w, c, sd: run_rideout(w, c, sd, road),
        "today55": lambda w, c, sd: run_today(w, c, sd, road, call_share=0.55),
        "todayWithNeighbors": lambda w, c, sd: run_today(w, c, sd, road, neighbors=True),
    }
    per: dict[str, dict[str, list[float]]] = {m: {c: [] for c in COLUMNS} for m in models}
    riders: dict[str, list[int]] = {c: [] for c in COLUMNS}
    for c in COLUMNS:
        for sd in range(first_seed, first_seed + seeds):
            world = make_world(sd, c, road)
            people = _people(world.homes)
            if people == 0:
                continue
            riders[c].append(people)
            for m, fn in models.items():
                r = fn(world, c, sd)
                per[m][c].append(_pct(r["onTime"], r["people"]))

    def bar(key: str, label: str, color: str) -> dict[str, Any]:
        cols = {c: _summary(per[key][c]) for c in COLUMNS}
        meds = [cols[c]["median"] for c in COLUMNS if cols[c]["median"] is not None]
        return {
            "key": key,
            "label": label,
            "available": True,
            "color": color,
            "median": cols["middle"]["median"],
            "min": min(meds),
            "max": max(meds),
            "columns": cols,
        }

    today = bar("today", "Today (911 queue)", "orange")
    ours = bar("greedy", "RideOut (greedy dispatch)", "blue")
    runs = sum(len(per["greedy"][c]) for c in COLUMNS)
    return {
        "schema": 1,
        "simulated": True,
        "label": f"Simulated: {HOMES} homes, Oak Creek Canyon scenario",
        "metric": "Share of people who needed a ride picked up before their deadline "
        "(10 min before the fire reaches the home). Not lives saved; not a forecast.",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gitSha": _git_sha(),
        "seedsPerColumn": seeds,
        "runs": runs,
        "bars": [
            today,
            ours,
            {
                "key": "ortools",
                "label": "RideOut (OR-Tools)",
                "available": False,
                "color": "blue",
                "note": "Not built.",
            },
        ],
        "headline": {
            "rideOutPct": ours["median"],
            "todayPct": today["median"],
            "rideOutRange": [ours["min"], ours["max"]],
            "todayRange": [today["min"], today["max"]],
            "runsPerColumn": seeds,
            "text": f"In simulation, {ours['median']:.0f}% of people who needed a ride were picked up before "
            f"their deadline with RideOut, vs {today['median']:.0f}% with today's 911 queue "
            f"(median of {seeds} runs; range {ours['min']:.0f}–{ours['max']:.0f}% vs "
            f"{today['min']:.0f}–{today['max']:.0f}% across low/middle/high settings).",
        },
        "sensitivity": {
            "today55": {
                "label": "Today, only 55% of riders call 911",
                "columns": {c: _summary(per["today55"][c]) for c in COLUMNS},
            },
            "todayWithNeighbors": {
                "label": "Today, 911 also dispatches the neighbor cars",
                "columns": {c: _summary(per["todayWithNeighbors"][c]) for c in COLUMNS},
            },
        },
        "ridersPerRun": {c: _summary([float(x) for x in riders[c]]) for c in COLUMNS},
        "settings": SETTINGS,
        "fleets": {k: len(v) for k, v in FLEETS.items()},
        "assumptions": {
            "source": "docs/simulation.md (settings columns); the rest below are modeling assumptions",
            "homes": HOMES,
            "callsPerMin": CALLS_PER_MIN,
            "answeredCallMin": CALL_MIN,
            "unansweredRingMin": RING_MIN,
            "reachLadderGapsMin": list(LADDER_GAPS_MIN),
            "textReplyMin": TEXT_REPLY_MIN,
            "doorCheckMin": DOOR_CHECK_MIN,
            "dispatchApproveAcceptMin": DISPATCH_MIN,
            "unloadMin": UNLOAD_MIN,
            "today911CallWindowMin": TODAY_CALL_WINDOW_MIN,
            "todayCallShare": 1.0,
            "today911FleetExcludesNeighbors": True,
            "secondPersonShare": SECOND_PERSON_SHARE,
            "twoPersonLiftShareOfHeavy": TWO_PERSON_LIFT_SHARE,
            "walkerShareOfOther": WALKER_SHARE,
            "bothStartAtTheOrder": True,
            "roadModel": "SR 89A as one polyline (api/sim/geo.py), 35 km/h + side streets at 15 km/h",
            "fireModel": "elliptical spread from the scenario ignition + wind (api/sim/seed.py), scenario input",
        },
        "notClaimed": ["lives saved", "that the fire model is a forecast", "numbers not in this file or on /system"],
    }


def _git_sha() -> str:
    sha = os.environ.get("GIT_SHA")
    if sha:
        return sha
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parent,
        ).stdout.strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=50, help="worlds per setting column (≥ 20)")
    ap.add_argument("--out", type=Path, default=data.DATA_DIR / "sim-results.json")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    result = simulate(seeds=args.seeds)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(result["headline"]["text"])
    print(f"wrote {args.out} in {time.perf_counter() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
