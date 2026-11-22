"""Batched dispatcher (the default). Pure: no database, no clock. The loop (api/dispatch/loop.py) does the I/O.

Ride-hail platforms stopped matching each request to the closest free driver the moment it arrived: they
collect the requests of the last few seconds and pair the whole batch with the free drivers at once, so the
average wait across everyone goes down, not just the closest pair's. That pairing is a minimum-cost
bipartite matching (rows = riders, columns = drivers, cost = pickup ETA), solved here with the Hungarian
algorithm. The solve loop already runs every 5 s, so each solve is one batch.

Evacuation changes three things:

1. **Seats fill up.** A van takes several households. Matching runs in rounds: each round gives every
   vehicle at most one more rider, starting from where its run now ends. A vehicle keeps taking riders
   until a seat, wheelchair space or stretcher is missing; then it drops out of the rounds and the
   rest go to the next vehicle (no shelter round trip while anyone else has room).
2. **Deadlines.** A pair only counts if the pickup makes the rider's deadline (10 min before the fire).
   Riders being reassigned go first; people who can't walk out (wheelchair, lift, stretcher) get a head
   start in the order and a heavier weight, and ambulances / lift vans are reserved for them while any wait.
   Riders nobody reaches in time, or who only fit after a shelter
   drop-off, are placed afterwards like the greedy planner does: soonest vehicle, flagged late.
3. **No rescuers in the fire.** Vehicles listed in `unsafe` (inside or about to be inside the fire
   front) get no new pickups. Their committed run is left alone; the loop decides about that.

Committed stops (accepted + offered) are never reordered, same as greedy.
"""

import math

from api.dispatch.greedy import (
    Proposal,
    Result,
    Rider,
    Shelter,
    Travel,
    Vehicle,
    _State,
    _visit,
    play_committed,
    priority_key,
)

BIG = 1e9  # "no pair" in the cost matrix
REASSIGN_BONUS_MIN = 60.0  # a rider being reassigned beats a fresh one when both want the same van
# Keep scarce vehicles for the riders only they can carry: an ambulance (stretcher) or a lift van
# (wheelchair) picking up someone who walks costs this many extra minutes in the matching.
SPECIALIST_PENALTY_MIN = 30.0


def _waste(v: Vehicle, r: Rider) -> float:
    if v.stretcher and not r.need.stretcher:
        return SPECIALIST_PENALTY_MIN
    if v.wheelchair and not (r.need.wheelchair or r.need.stretcher or r.need.lift) and v.seats <= 4:
        return SPECIALIST_PENALTY_MIN / 2
    return 0.0


def _ambulance(v: Vehicle) -> bool:
    return v.stretcher > 0


def _lift_van(v: Vehicle) -> bool:
    """A small vehicle that carries wheelchairs (paratransit): few of them, so they're kept for those riders."""
    return v.wheelchair > 0 and v.seats <= 4 and not v.stretcher


def _reserved(v: Vehicle, r: Rider, waiting: list[Rider], st: _State | None = None) -> bool:
    """Hard reservation: while someone who needs this kind of vehicle is still waiting, it doesn't take a
    rider who could go in any car. Ambulances: stretcher riders first, then wheelchair riders (a wheelchair
    rider can share the trip once the stretcher is taken). Lift vans: wheelchair / lift / stretcher only."""
    n = r.need
    if _ambulance(v):
        stretcher_full = st is not None and st.stretcher >= v.stretcher
        if (
            not n.stretcher
            and not (stretcher_full and n.mobility())
            and any(w.need.stretcher and v.fits(w.need) for w in waiting)
        ):
            return True
        return not n.mobility() and any(w.need.mobility() and v.fits(w.need) for w in waiting)
    if _lift_van(v):
        return not n.mobility() and any(w.need.mobility() and v.fits(w.need) for w in waiting)
    return False


def hungarian(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment for an n×m matrix (n ≤ m). → for each row, its column.

    Classic O(n²·m) Kuhn–Munkres with potentials (Jonker–Volgenant style shortest augmenting paths)."""
    n, m = len(cost), len(cost[0]) if cost else 0
    if n == 0:
        return []
    assert n <= m, "more rows than columns: transpose first"
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)  # p[j] = row matched to column j (1-based, 0 = free)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [math.inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], math.inf, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j], way[j] = cur, j0
                if minv[j] < delta:
                    delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    rows = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            rows[p[j] - 1] = j - 1
    return rows


def match(cost: list[list[float]]) -> list[tuple[int, int]]:
    """Minimum-cost matching for any n×m matrix; pairs whose cost is BIG are dropped."""
    if not cost or not cost[0]:
        return []
    n, m = len(cost), len(cost[0])
    if n <= m:
        pairs = list(enumerate(hungarian(cost)))
    else:
        t = [[cost[i][j] for i in range(n)] for j in range(m)]
        pairs = [(i, j) for j, i in enumerate(hungarian(t))]
    return [(i, j) for i, j in pairs if j >= 0 and cost[i][j] < BIG]


def plan(
    riders: list[Rider],
    vehicles: list[Vehicle],
    shelters: list[Shelter],
    travel: Travel,
    board: dict[str, float] | None = None,
    *,
    unsafe: set[str] | frozenset[str] = frozenset(),
) -> Result:
    base = play_committed(vehicles, shelters, travel, board)
    states: dict[str, _State] = base.states
    free = [v for v in vehicles if v.id not in unsafe]
    proposals: list[Proposal] = []
    wait = 0.0

    def place(r: Rider, v: Vehicle, st: _State, pickup: float, late: bool) -> None:
        nonlocal wait
        states[v.id] = st
        proposals.append(Proposal(r.id, v.id, round(pickup, 1), st.stops, late=late))
        wait += pickup * r.need.weight()

    # ── batched rounds: no shelter hops, deadlines must hold ─────────────
    pending = sorted(riders, key=priority_key)
    while pending and free:
        cost = [[BIG] * len(free) for _ in pending]
        moves: dict[tuple[int, int], tuple[_State, float]] = {}
        for i, r in enumerate(pending):
            for j, v in enumerate(free):
                if not v.fits(r.need) or _reserved(v, r, pending, states[v.id]):
                    continue
                nxt = _visit(v, states[v.id], r, shelters, travel, board, allow_hop=False)
                if nxt is None:
                    continue
                st, pickup = nxt
                if r.deadline_min is not None and pickup > r.deadline_min:
                    continue
                cost[i][j] = pickup * r.need.weight() + _waste(v, r) - (REASSIGN_BONUS_MIN if r.reassigning else 0.0)
                moves[(i, j)] = nxt
        pairs = match(cost)
        if not pairs:
            break
        for i, j in pairs:
            st, pickup = moves[(i, j)]
            place(pending[i], free[j], st, pickup, late=False)
        done = {i for i, _ in pairs}
        pending = [r for i, r in enumerate(pending) if i not in done]

    # ── leftovers: in time with a shelter drop-off first, else soonest anyway (flagged late) ──
    unservable: list[str] = []
    for must_make in (True, False):
        rest = []
        for k, r in enumerate(pending):
            best = None
            waiting = rest + pending[k + 1 :]
            for v in free:
                if not v.fits(r.need) or _reserved(v, r, waiting, states[v.id]):
                    continue
                nxt = _visit(v, states[v.id], r, shelters, travel, board)
                if nxt is None:
                    continue
                st, pickup = nxt
                if must_make and r.deadline_min is not None and pickup > r.deadline_min:
                    continue
                if best is None or pickup + _waste(v, r) < best[2] + _waste(best[0], r):
                    best = (v, st, pickup)
            if best is None:
                rest.append(r)
                continue
            if not must_make:
                unservable.append(r.id)
            place(r, best[0], best[1], best[2], late=not must_make)
        pending = rest
    unservable += [r.id for r in pending]  # nobody can reach them at all

    return Result(
        proposals=proposals,
        unservable=unservable,
        unreachable_committed=base.unreachable,
        committed_eta=base.committed_eta,
        late_committed_rescuable=base.rescuable,
        drive_min=sum(s.drive for s in states.values()),
        weighted_wait=wait,
    )
