"""Evacuation replay: the whole night, planned once, as timelines the console can play back.

What it is: the loaded world (homes, census answers, fleet, shelters, fire) run forward from ignition with
the same pieces the live system uses: the batched planner (api/dispatch/batch.py, shelter round trips
included), the same street-grid/road travel times, the same boarding and unloading minutes. Nothing is
written to the database. Every number in the summary is counted from these timelines, so the replay
and its counters can't disagree.

Timeline (minutes from the warning, i.e. when the world was seeded):
- CALL_MIN: every home has been called (the AI calls everyone at once) and the answers are in.
- Homes that can leave on their own drive to the nearest shelter, leaving over the next LEAVE_SPREAD_MIN.
- Riders: the planner gives each vehicle its run; vehicles drive it, drop off at a shelter whenever the
  next rider wouldn't fit, and end at a shelter. A rider is safe at the drop-off.
- The fire: the same simulated detections as the fire replay; its outline every FIRE_FRAME_MIN.

Scenario input, not a forecast. Everything here is simulated.
"""

import asyncio
import math
import random
from collections.abc import Callable
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api.core.util import aware
from api.dispatch import batch, greedy
from api.hazard import fire, spread
from api.sim import world

SAMPLE_M = 250.0  # how finely a path is checked against the fire (the head moves 60 m a minute)
CALL_MIN = 5.0  # every home is called at once; the answers are in by minute 5
LEAVE_SPREAD_MIN = 20.0
FIRE_FRAME_MIN = 5.0
DEADLINE_BUFFER_MIN = 10.0  # same as requests: be gone 10 min before the fire
CHUNK = 60  # riders per planning round (keeps each Hungarian solve small)
FIRE_MARGIN_MIN = 1.0  # boarding must finish at least this long before the fire reaches the home
WEST_DETOUR_LON = -111.93  # North Scottsdale: the grid road west of the zone, upwind of nothing

LonLat = tuple[float, float]


def _r(x: float, n: int = 5) -> float:
    return round(float(x), n)


FireAt = Callable[[LonLat], float]  # minute the fire reaches a point (minutes from the warning)


def _timed(seq: list[LonLat], t: float, total: float) -> list[list[float]]:
    dist = [abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(seq, seq[1:], strict=False)]
    whole = sum(dist) or 1.0
    out, acc = [], 0.0
    for p, d in zip(seq[1:], dist, strict=False):
        acc += d
        out.append([_r(p[0]), _r(p[1]), round(t + total * acc / whole, 2)])
    return out


def _burned_m(seq: list[LonLat], t: float, total: float, fire_at: FireAt | None) -> float:
    """Meters of this path driven where the fire has already arrived (sampled every ~60 m)."""
    if fire_at is None:
        return 0.0
    # Done before the fire has started anywhere: nothing to check (most early trips).
    if t + total < getattr(fire_at, "earliest", -math.inf):
        return 0.0
    from api.sim.geo import meters

    legs = [(p, q, meters(p, q)) for p, q in zip(seq, seq[1:], strict=False)]
    whole = sum(d for _, _, d in legs) or 1.0
    bad, done = 0.0, 0.0
    for p, q, d in legs:
        n = max(1, int(d / SAMPLE_M))
        for i in range(n):
            f = (i + 0.5) / n
            pt = (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f)
            if fire_at(pt) <= t + total * (done + d * f) / whole:
                bad += d / n
        done += d
    return bad


def _leg(net: Any, a: LonLat, b: LonLat, t: float, fire_at: FireAt | None = None) -> tuple[list[list[float]], float]:
    """Waypoints [lon, lat, minute] from a to b starting at minute t, along the network; → (points, arrival).
    On the street grid it keeps out of ground the fire has already reached when the vehicle would be there:
    the two L-shaped paths first, then a detour west of both ends (the fire comes from the east)."""
    path, total, _ = _route(net, a, b, t, fire_at)
    return _timed(path, t, total), t + total


def _route(net: Any, a: LonLat, b: LonLat, t: float, fire_at: FireAt | None) -> tuple[list[LonLat], float, float]:
    """→ (points a…b, minutes, meters driven inside the fire). Shortest path that stays out of the fire."""
    direct = net.travel_min(a, b)
    if not math.isfinite(direct):
        return [a, b], 0.0, 0.0
    if not hasattr(net, "route_xy"):
        return [a, b], direct, 0.0
    from api.sim.grid import drive_min, lonlat, manhattan_m, xy

    options: list[tuple[list[LonLat], float]] = []
    if not net.barriers:
        for p in net._l_paths(xy(a), xy(b)):
            options.append(([a, lonlat(p[1]), b], direct))
    else:
        p = net.route_xy(xy(a), xy(b)) or [xy(a), xy(b)]
        options.append(([a, *[lonlat(q) for q in p[1:-1]], b], direct))
    scored = [(_burned_m(seq, t, tot, fire_at), tot, seq) for seq, tot in options]
    clear = [x for x in scored if x[0] == 0]
    if clear:  # a direct path that stays out of the fire: done (most trips)
        _, tot, seq = min(clear, key=lambda x: x[1])
        return seq, tot, 0.0
    if fire_at is not None and not net.barriers:  # both L paths cross the fire: try detours west
        for west in (min(a[0], b[0]) - 0.006, min(a[0], b[0]) - 0.02, WEST_DETOUR_LON):
            seq = [a, (west, a[1]), (west, b[1]), b]
            tot = drive_min(sum(manhattan_m(p, q) for p, q in zip(seq, seq[1:], strict=False)))
            scored.append((_burned_m(seq, t, tot, fire_at), tot, seq))
    burned, tot, seq = min(scored, key=lambda x: (x[0] > 0, x[0], x[1]))
    return seq, tot, burned


def _nearest(
    net: Any, here: LonLat, shelters: list[greedy.Shelter], t: float = 0.0, fire_at: FireAt | None = None
) -> greedy.Shelter:
    """Nearest shelter the fire won't reach within an hour of arriving, by a road that stays out of the fire."""
    ok = [s for s in shelters if fire_at is None or fire_at(s.loc) > t + net.travel_min(here, s.loc) + 60]
    if fire_at is None:
        return min(ok or shelters, key=lambda s: net.travel_min(here, s.loc))

    # Nearest first; the first one reachable without crossing the fire wins (no need to route the rest).
    best: tuple[tuple[bool, float], greedy.Shelter] | None = None
    for s in sorted(ok or shelters, key=lambda s: net.travel_min(here, s.loc)):
        _, minutes, burned = _route(net, here, s.loc, t, fire_at)
        if burned == 0:
            return s
        if best is None or (True, minutes) < best[0]:
            best = ((True, minutes), s)
    return best[1] if best else shelters[0]


async def build(db: AsyncIOMotorDatabase, *, rng_seed: int = 42) -> dict[str, Any]:
    net = world.network()
    doc = await db.hazards.find_one({"_id": fire.RUN_ID})
    if doc is None:
        return {"error": "No fire yet. Seed a world first."}
    run = fire.run_from_doc(doc)
    # Minute 0 = when the world was seeded: the warning goes out and the calls start. The fire may ignite
    # before or after that (seed's firstArrivalMin sets how long until it reaches the first home).
    t0: datetime = aware(doc.get("seededAt")) or run.ignited_at

    def minute(dt: Any) -> float | None:
        d = aware(dt)
        return None if d is None else (d - t0).total_seconds() / 60

    homes = [h async for h in db.households.find({}, {"location": 1, "role": 1, "fireArrivalAt": 1, "reach": 1})]
    reqs = {r["householdId"]: r async for r in db.requests.find({}, {"householdId": 1, "need": 1})}
    shelters = []
    async for s in db.shelters.find({}):
        c = (s.get("location") or {}).get("coordinates")
        if c:
            shelters.append(greedy.Shelter(s["_id"], (c[0], c[1]), int(s.get("capacity", 0))))
    fleet = [v async for v in db.vehicles.find({"status": {"$ne": "offline"}})]
    if not shelters or not fleet:
        return {"error": "This world has no shelters or vehicles."}

    rng = random.Random(rng_seed)
    from api.sim.seed import ECCENTRICITY, HEAD_SPREAD_M_PER_MIN, fire_minutes

    ign_min = (run.ignited_at - t0).total_seconds() / 60

    def fire_at_pt(pt: LonLat) -> float:
        return ign_min + fire_minutes(pt, run.ignition, run.wind_from_deg)

    fire_at_pt.earliest = ign_min  # type: ignore[attr-defined]  # nothing burns before ignition

    fire_at: dict[str, float | None] = {h["_id"]: minute(h.get("fireArrivalAt")) for h in homes}
    loc = {h["_id"]: tuple(h["location"]["coordinates"]) for h in homes if h.get("location")}

    # ── riders: everyone who said they need a ride (census answers), planned once at CALL_MIN ──
    rider_homes = [h for h in homes if h.get("role") == "needs_ride" and h["_id"] in loc]
    riders: list[greedy.Rider] = []
    for h in rider_homes:
        fa = fire_at[h["_id"]]
        need = greedy.Need.of((reqs.get(h["_id"]) or {}).get("need"))
        # Picked up AND boarded before the fire (stretcher boarding takes 15 min), with the usual buffer.
        dl = None if fa is None else fa - CALL_MIN - max(DEADLINE_BUFFER_MIN, need.board_min() + FIRE_MARGIN_MIN)
        riders.append(greedy.Rider(id=h["_id"], loc=loc[h["_id"]], need=need, deadline_min=dl))
    rider_by_id = {r.id: r for r in riders}
    mobility = {r.id for r in riders if r.need.mobility()}
    vehicles = []
    for v in fleet:
        c = (v.get("location") or {}).get("coordinates")
        cap = v.get("capacity") or {}
        if not c:
            continue
        vehicles.append(
            greedy.Vehicle(
                id=v["_id"],
                loc=(c[0], c[1]),
                seats=int(cap.get("seats", 4)),
                wheelchair=int(cap.get("wheelchair", 0)),
                stretcher=int(cap.get("stretcher", 0)),
                crew=int(v.get("crew", 1)),
                lift=bool(v.get("lift")),
            )
        )
    # Rolling horizon, like the live loop: the most urgent CHUNK riders at a time, each vehicle keeping
    # the riders it already has (committed stops are never reordered).
    by_vehicle: dict[str, list[greedy.Proposal]] = {}
    queue = sorted(riders, key=greedy.priority_key)
    for k in range(0, len(queue), CHUNK):
        result = batch.plan(queue[k : k + CHUNK], vehicles, shelters, net.travel_min)
        rid = {r.id: r for r in queue[k : k + CHUNK]}
        for p in result.proposals:
            by_vehicle.setdefault(p.vehicle_id, []).append(p)
        for v in vehicles:
            mine = sorted(by_vehicle.get(v.id, []), key=lambda p: p.stop_order)
            v.committed = [rid.get(p.request_id) or rider_by_id[p.request_id] for p in mine]

    # ── drive every run: same rule as the planner (full → nearest shelter first), log each move ──
    out_vehicles, out_riders = [], {}
    fire_first: set[str] = set()
    for vi, v in enumerate(vehicles):
        await asyncio.sleep(0)  # long build: let the API answer other requests between vehicles
        meta = next(x for x in fleet if x["_id"] == v.id)
        here, t = v.loc, CALL_MIN
        path = [[_r(here[0]), _r(here[1]), t]]
        loads: list[list[float]] = [[t, 0]]
        onboard: list[greedy.Rider] = []

        def drop(
            here: LonLat,
            t: float,
            path: list[list[float]] = path,
            onboard: list[greedy.Rider] = onboard,
            loads: list[list[float]] = loads,
        ) -> tuple[LonLat, float]:
            sh = _nearest(net, here, shelters, t, fire_at_pt)
            pts, t = _leg(net, here, sh.loc, t, fire_at_pt)
            path.extend(pts)
            for r in onboard:
                out_riders[r.id]["drop"] = round(t, 2)
                out_riders[r.id]["shelter"] = sh.id
            t += greedy.UNLOAD_MIN
            path.append([_r(sh.loc[0]), _r(sh.loc[1]), round(t, 2)])
            onboard.clear()
            loads.append([round(t, 2), 0])
            return sh.loc, t

        for p in sorted(by_vehicle.get(v.id, []), key=lambda p: p.stop_order):
            r = rider_by_id[p.request_id]
            used = [sum(x.need.seats for x in onboard), sum(x.need.wheelchair for x in onboard),
                    sum(x.need.stretcher for x in onboard)]  # fmt: skip
            if onboard and (
                used[0] + r.need.seats > v.seats
                or used[1] + r.need.wheelchair > v.wheelchair
                or used[2] + r.need.stretcher > v.stretcher
            ):
                here, t = drop(here, t)
            # Never drive into the fire: if it reaches this home before the vehicle could, skip the stop
            # (the rider counts as "fire reached first"; in the live system this goes to 911 / fire crews).
            if net.travel_min(here, r.loc) + t + r.need.board_min() >= fire_at_pt(r.loc) - FIRE_MARGIN_MIN:
                fire_first.add(r.id)
                continue
            pts, t = _leg(net, here, r.loc, t, fire_at_pt)
            path.extend(pts)
            pickup = t
            t += r.need.board_min()
            path.append([_r(r.loc[0]), _r(r.loc[1]), round(t, 2)])
            here = r.loc
            onboard.append(r)
            loads.append([round(pickup, 2), sum(x.need.seats for x in onboard)])
            out_riders[r.id] = {"vehicle": vi, "pickup": round(pickup, 2), "seats": r.need.seats}
        if onboard:
            here, t = drop(here, t)
        out_vehicles.append(
            {
                "id": v.id,
                "name": meta.get("driverName") or v.id,
                "kind": meta.get("kind"),
                "seats": v.seats,
                "path": path,
                "loads": loads,
                "riders": len(by_vehicle.get(v.id, [])),
            }
        )

    # ── homes that leave on their own: to the nearest shelter, spread over LEAVE_SPREAD_MIN ──
    self_evac, stayed, unreached, rider_rows = [], [], [], []
    rider_ids: list[str] = []
    # People driving themselves go to the general shelters; the medical one is kept for riders.
    names = {s["_id"]: str(s.get("name", "")) async for s in db.shelters.find({}, {"name": 1})}
    general = [s for s in shelters if "medical" not in names.get(s.id, "").lower()] or shelters
    for n_home, h in enumerate(homes):
        if n_home % 250 == 0:
            await asyncio.sleep(0)
        hid = h["_id"]
        if hid not in loc:
            continue
        lo, la = loc[hid]
        fa = fire_at[hid]
        role = h.get("role")
        if role == "needs_ride":
            rider_ids.append(hid)
            x = out_riders.get(hid)
            if x is None:  # -2: the fire got there before any vehicle could; -1: no vehicle can carry this need
                rider_rows.append([_r(lo), _r(la), None, None, -2 if hid in fire_first else -1, fa])
            else:
                rider_rows.append([_r(lo), _r(la), x["pickup"], x.get("drop"), x["vehicle"], fa])
        elif role in ("left", "can_help"):
            leave = CALL_MIN + rng.random() * LEAVE_SPREAD_MIN
            sh = _nearest(net, (lo, la), general, leave, fire_at_pt)
            pts, arrive = _leg(net, (lo, la), sh.loc, leave, fire_at_pt)
            self_evac.append([_r(lo), _r(la), round(leave, 2), [p for q in pts for p in q], fa])
        elif role == "stay":
            stayed.append([_r(lo), _r(la), fa])
        else:
            unreached.append([_r(lo), _r(la), fa])

    # ── the fire: the same ellipse that set every home's arrival time, so the map and the dots agree ──
    last_safe = max(
        [r[3] for r in rider_rows if r[3] is not None] + [s[3][-1] for s in self_evac] + [CALL_MIN], default=CALL_MIN
    )
    end = min(spread.REPLAY_HOURS * 60, math.ceil((last_safe + 30) / FIRE_FRAME_MIN) * FIRE_FRAME_MIN)
    frames = []
    k = 0.0
    while k <= end:
        ring = spread.front(run, k - ign_min, points=96)
        frames.append({"t": k, "ring": [[_r(x), _r(y)] for x, y in ring]})
        k += FIRE_FRAME_MIN
    fire_model = {
        "ignition": [run.ignition[0], run.ignition[1]],
        "downwindDeg": run.downwind_deg,
        "headMPerMin": HEAD_SPREAD_M_PER_MIN,
        "eccentricity": ECCENTRICITY,
        "ignitionMin": round(ign_min, 3),
    }

    on_time = sum(1 for r in rider_rows if r[2] is not None and (r[5] is None or r[2] <= r[5]))
    mob_rows = [r for hid, r in zip(rider_ids, rider_rows, strict=True) if hid in mobility]
    mob_on_time = sum(1 for r in mob_rows if r[2] is not None and (r[5] is None or r[2] <= r[5]))
    late = sum(1 for r in rider_rows if r[2] is not None and r[5] is not None and r[2] > r[5])
    no_vehicle = sum(1 for r in rider_rows if r[2] is None and r[4] == -1)
    late += sum(1 for r in rider_rows if r[4] == -2)  # the fire got there first
    self_late = sum(1 for s in self_evac if s[4] is not None and s[2] > s[4])
    fire_first = min((f for f in fire_at.values() if f is not None), default=None)
    return {
        "t0": t0,
        "callMin": CALL_MIN,
        "endMin": end,
        "fire": frames,
        "fireModel": fire_model,  # draw the front at any minute: elliptical spread from the ignition
        "vehicles": out_vehicles,
        "riders": rider_rows,  # [lon, lat, pickupMin, dropMin, vehicle (-1 none can carry, -2 fire first), fireMin]
        "selfEvac": self_evac,  # [lon, lat, leaveMin, [lon, lat, min, …], fireMin]
        "stayed": stayed,  # [lon, lat, fireMin]
        "unreached": unreached,
        "summary": {
            "homes": len(loc),
            "riders": len(rider_rows),
            "ridersOutBeforeFire": on_time,
            "mobilityRiders": len(mob_rows),  # wheelchair, lift or stretcher
            "mobilityOutBeforeFire": mob_on_time,
            "ridersLate": late,
            "ridersNoVehicle": no_vehicle,
            "selfEvac": len(self_evac),
            "selfEvacLate": self_late,
            "stayed": len(stayed),
            "unreached": len(unreached),
            "lastSafeMin": round(last_safe, 1),
            "firstFireMin": None if fire_first is None else round(fire_first, 1),
            "vehicles": len(out_vehicles),
            "maxLoadOverSeats": max(
                (max((ld[1] for ld in v["loads"]), default=0) - v["seats"] for v in out_vehicles), default=0
            ),
        },
        "simulated": True,
    }
