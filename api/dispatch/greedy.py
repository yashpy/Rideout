"""Greedy dispatcher. Pure: no database, no clock. The loop (api/dispatch/loop.py) does the I/O.

1. Sort open requests: riders being reassigned first, then earliest deadline, then priority.
2. For each, try every compatible vehicle (seats, wheelchair, stretcher, crew, lift). The pickup goes
   AFTER the vehicle's committed stops (accepted + offered); those are never reordered. If the vehicle
   would be over capacity it first drops everyone at the nearest shelter with room.
3. Pick the vehicle that reaches them soonest among those that make the deadline. Requests nobody can
   reach in time wait until everyone reachable is placed, then go to the soonest vehicle, flagged late
   (`unservable`), because a late pickup still beats none and the dispatcher must see it.

Times are minutes from "now". `travel(a, b)` returns minutes or math.inf (road closed).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

LonLat = tuple[float, float]
Travel = Callable[[LonLat, LonLat], float]

UNLOAD_MIN = 5.0
# Boarding minutes, docs/simulation.md middle column: walks 3 / walker 6 / wheelchair 10 / two-person lift 15
BOARD_MIN = {"walks": 3.0, "walker": 6.0, "wheelchair": 10.0, "lift": 15.0, "stretcher": 15.0}


@dataclass
class Need:
    seats: int = 1
    wheelchair: int = 0
    stretcher: int = 0
    crew: int = 1
    lift: bool = False
    board_kind: str | None = None  # override the boarding class (the simulation knows walker vs walks)

    @classmethod
    def of(cls, d: dict[str, Any] | None) -> "Need":
        d = d or {}
        return cls(
            seats=int(d.get("seats") or 1),
            wheelchair=int(d.get("wheelchair") or 0),
            stretcher=int(d.get("stretcher") or 0),
            crew=int(d.get("crew") or 1),
            lift=bool(d.get("lift")),
        )

    def kind(self) -> str:
        """Boarding class: walks | walker | wheelchair | lift | stretcher."""
        if self.board_kind:
            return self.board_kind
        if self.stretcher:
            return "stretcher"
        if self.lift or self.crew >= 2:
            return "lift" if self.wheelchair or self.lift else "walker"
        return "wheelchair" if self.wheelchair else "walks"

    def board_min(self, board: dict[str, float] | None = None) -> float:
        return (board or BOARD_MIN)[self.kind()]

    def weight(self) -> float:
        """Need-weighted waiting: heavier needs count more. People who can't walk out are who this system is
        for: few vehicles can carry them and boarding takes 10-15 min, so each minute they wait costs more."""
        return 1.0 + 2 * self.wheelchair + 4 * self.stretcher + (1.0 if self.lift else 0)

    def mobility(self) -> bool:
        """Can't walk to a car: wheelchair, lift or stretcher."""
        return bool(self.wheelchair or self.stretcher or self.lift)

    def head_start_min(self) -> float:
        """Planned this many minutes earlier than their deadline alone says (see priority_key)."""
        return 45.0 if self.stretcher else 30.0 if (self.wheelchair or self.lift) else 0.0


def priority_key(r: "Rider") -> tuple:
    """Who gets planned first: riders being reassigned, then by deadline, with a head start for people who
    can't walk out (their vehicles are few and boarding is slow, so they must be first in line)."""
    dl = r.deadline_min if r.deadline_min is not None else math.inf
    return (not r.reassigning, dl - r.need.head_start_min(), -r.priority)


@dataclass
class Rider:
    id: str
    loc: LonLat
    need: Need
    deadline_min: float | None = None  # minutes from now; None = no deadline known
    priority: float = 0.0
    reassigning: bool = False


@dataclass
class Vehicle:
    id: str
    loc: LonLat
    seats: int
    wheelchair: int = 0
    stretcher: int = 0
    crew: int = 1
    lift: bool = False
    committed: list[Rider] = field(default_factory=list)  # accepted + offered pickups, in order
    ready_min: float = 0.0  # minutes until it can start from `loc` (busy finishing a trip)
    load: tuple[int, int, int] = (0, 0, 0)  # seats, wheelchair, stretcher already on board at `loc`

    def fits(self, n: Need) -> bool:
        return (
            n.seats <= self.seats
            and n.wheelchair <= self.wheelchair
            and n.stretcher <= self.stretcher
            and n.crew <= self.crew
            and (self.lift or not n.lift)
        )


@dataclass
class Shelter:
    id: str
    loc: LonLat
    room: int


@dataclass
class Proposal:
    request_id: str
    vehicle_id: str
    eta_min: float
    stop_order: int
    late: bool


@dataclass
class Result:
    proposals: list[Proposal]
    unservable: list[str]  # late or unreachable request ids
    unreachable_committed: list[str]  # committed pickups no route reaches anymore (revoke candidates)
    drive_min: float
    weighted_wait: float
    committed_eta: dict[str, float] = field(default_factory=dict)  # committed pickup → minutes (inf = cut off)
    # committed pickups this vehicle now reaches after the deadline, but another vehicle would reach in time
    late_committed_rescuable: list[str] = field(default_factory=list)

    def objective(self) -> tuple[int, float, float]:
        """(late riders, need-weighted waiting, driving): compared in that order."""
        return (len(self.unservable), round(self.weighted_wait, 1), round(self.drive_min, 1))


@dataclass
class _State:
    loc: LonLat
    t: float
    seats: int = 0
    wheelchair: int = 0
    stretcher: int = 0
    stops: int = 0
    drive: float = 0.0


def _nearest_shelter(loc: LonLat, shelters: list[Shelter], riders: int, travel: Travel) -> tuple[Shelter, float] | None:
    best = None
    for s in shelters:
        if s.room < riders:
            continue
        t = travel(loc, s.loc)
        if math.isfinite(t) and (best is None or t < best[1]):
            best = (s, t)
    return best


def _visit(
    v: Vehicle,
    st: _State,
    r: Rider,
    shelters: list[Shelter],
    travel: Travel,
    board: dict[str, float] | None = None,
    *,
    allow_hop: bool = True,
) -> tuple[_State, float] | None:
    """Drive to `r` (dropping off first if full). → (new state, pickup time) or None if unreachable.
    `allow_hop=False`: a full vehicle can't take `r` (no shelter round trip first)."""
    n = r.need
    s = _State(**st.__dict__)
    full = (
        s.seats + n.seats > v.seats
        or s.wheelchair + n.wheelchair > v.wheelchair
        or (s.stretcher + n.stretcher > v.stretcher)
    )
    if full and not allow_hop:
        return None
    if full and s.seats:
        hop = _nearest_shelter(s.loc, shelters, s.seats, travel)
        if hop is None:
            return None
        sh, t = hop
        s.t += t + UNLOAD_MIN
        s.drive += t
        s.loc = sh.loc
        s.seats = s.wheelchair = s.stretcher = 0
    t = travel(s.loc, r.loc)
    if not math.isfinite(t):
        return None
    s.t += t
    s.drive += t
    pickup = s.t
    s.t += n.board_min(board)
    s.loc = r.loc
    s.seats += n.seats
    s.wheelchair += n.wheelchair
    s.stretcher += n.stretcher
    s.stops += 1
    return s, pickup


@dataclass
class Committed:
    """Every vehicle's committed run played out: where each one is free to take new pickups."""

    states: dict[str, "_State"]
    committed_eta: dict[str, float]
    unreachable: list[str]
    rescuable: list[str]


def play_committed(
    vehicles: list[Vehicle], shelters: list[Shelter], travel: Travel, board: dict[str, float] | None = None
) -> Committed:
    """Play out the accepted + offered runs (never reordered). Also finds committed pickups that are now
    late but another vehicle (after its own run) would make in time: candidates to move."""
    unreachable: list[str] = []
    committed_eta: dict[str, float] = {}
    late: list[tuple[Rider, str]] = []
    states: dict[str, _State] = {}
    for v in vehicles:  # play out the committed run first; it never changes here
        st = _State(loc=v.loc, t=v.ready_min, seats=v.load[0], wheelchair=v.load[1], stretcher=v.load[2])
        for r in v.committed:
            nxt = _visit(v, st, r, shelters, travel, board)
            if nxt is None:  # a closure cut it off: skip it, the rest of the run goes on as accepted
                unreachable.append(r.id)
                committed_eta[r.id] = math.inf
                continue
            st, pickup = nxt
            committed_eta[r.id] = round(pickup, 1)
            if r.deadline_min is not None and pickup > r.deadline_min:
                late.append((r, v.id))
        states[v.id] = st

    # A late committed pickup moves only if another vehicle (after its own committed run) makes the deadline.
    rescuable = []
    for r, owner in late:
        for w in vehicles:
            if w.id == owner or not w.fits(r.need):
                continue
            nxt = _visit(w, states[w.id], r, shelters, travel, board)
            if nxt is not None and r.deadline_min is not None and nxt[1] <= r.deadline_min:
                rescuable.append(r.id)
                break
    return Committed(states, committed_eta, unreachable, rescuable)


def plan(
    riders: list[Rider],
    vehicles: list[Vehicle],
    shelters: list[Shelter],
    travel: Travel,
    board: dict[str, float] | None = None,
) -> Result:
    """`board` overrides the boarding minutes (the impact simulation runs low/middle/high)."""
    # v0: a shelter is usable while it has room for the load; room isn't drawn down within one plan.
    base = play_committed(vehicles, shelters, travel, board)
    states, committed_eta, unreachable, rescuable = base.states, base.committed_eta, base.unreachable, base.rescuable

    order = sorted(
        riders,
        key=priority_key,
    )
    proposals: list[Proposal] = []
    deferred: list[Rider] = []
    unservable: list[str] = []
    wait = 0.0

    def best_for(r: Rider, must_make_deadline: bool) -> tuple[Vehicle, _State, float] | None:
        best = None
        for v in vehicles:
            if not v.fits(r.need):
                continue
            nxt = _visit(v, states[v.id], r, shelters, travel, board)
            if nxt is None:
                continue
            st, pickup = nxt
            if must_make_deadline and r.deadline_min is not None and pickup > r.deadline_min:
                continue
            if best is None or pickup < best[2]:
                best = (v, st, pickup)
        return best

    for r in order:
        hit = best_for(r, must_make_deadline=True)
        if hit is None:
            deferred.append(r)
            continue
        v, st, pickup = hit
        states[v.id] = st
        proposals.append(Proposal(r.id, v.id, round(pickup, 1), st.stops, late=False))
        wait += pickup * r.need.weight()

    for r in deferred:  # nobody makes the deadline: soonest vehicle anyway, flagged
        hit = best_for(r, must_make_deadline=False)
        unservable.append(r.id)
        if hit is None:
            continue
        v, st, pickup = hit
        states[v.id] = st
        proposals.append(Proposal(r.id, v.id, round(pickup, 1), st.stops, late=True))
        wait += pickup * r.need.weight()

    return Result(
        proposals=proposals,
        unservable=unservable,
        unreachable_committed=unreachable,
        committed_eta=committed_eta,
        late_committed_rescuable=rescuable,
        drive_min=sum(s.drive for s in states.values()),
        weighted_wait=wait,
    )
