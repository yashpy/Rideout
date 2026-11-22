# api/dispatch/ — solver

| File | What |
|---|---|
| `batch.py` | **Default.** Batched matching, the way ride-hail platforms match: each solve takes every open request and every free vehicle as one batch and pairs them with a minimum-cost bipartite matching (Hungarian algorithm, cost = pickup ETA × need weight), instead of giving each rider the closest driver one at a time. Rounds fill seats: a vehicle keeps taking riders until a seat or wheelchair space runs out, then the rest go to the next vehicle (no shelter round trip while anyone else has room). Pickups must make the rider's deadline; riders being reassigned go first. Vehicles in or near the fire get no new pickups (`unsafe`). |
| `greedy.py` | Earliest-deadline-first, soonest compatible vehicle. Kept for comparison (`POST /plans/solve {solver: "greedy"}`) and the impact simulation. Also holds the shared pieces: `Need`, `Rider`, `Vehicle`, `play_committed()`. |
| `loop.py` | Re-plan every 5 s while open, 30 s otherwise, immediately on closure. Marks vehicles the fire front reaches within `FIRE_BUFFER_MIN` (10 min, same spread model as the map) as unsafe. Started from `api/workers.py` |

Planned, not built: an OR-Tools pickup-and-delivery VRP (time windows, 3 s limit, warm start). `POST /plans/solve`
accepts `solver: ortools` but runs batched until then.

Write `plans` + `proposed` assignments only. Approve/accept/revoke go through `api/assignments.py`.
Accepted stops are frozen; to drop one that can no longer be reached, call `api.assignments.revoke()`.
