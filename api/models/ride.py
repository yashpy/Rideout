"""Requests, vehicles, assignments (offers), callbacks, plans."""

from typing import Literal

from pydantic import BaseModel, Field

from api.models.common import ISO, Doc, Point

RequestStatus = Literal["received", "approved", "driver_accepted", "en_route", "arrived", "closed", "reassigning"]
Escalation = Literal["medical", "flames", "address_unconfirmed", "unservable", "language"]
AssignmentStatus = Literal["proposed", "offered", "accepted", "declined", "expired", "replaced", "revoked", "completed"]


class Need(BaseModel):
    seats: int = 1
    wheelchair: int = 0
    stretcher: int = 0
    crew: int = 1
    lift: bool = False


class RideRequest(Doc):
    householdId: str
    status: RequestStatus = "received"
    need: Need = Field(default_factory=Need)
    deadlineAt: ISO | None = None
    priority: float = 0.0
    escalation: Escalation | None = None
    dupOf: str | None = None
    version: int = 1
    createdAt: ISO | None = None
    updatedAt: ISO | None = None


class Capacity(BaseModel):
    seats: int = 4
    wheelchair: int = 0
    stretcher: int = 0


class Safety(BaseModel):
    state: Literal["ok", "check", "man_down", "sos"] = "ok"
    at: ISO | None = None
    location: Point | None = None


class Vehicle(Doc):
    kind: Literal["agency_van", "paratransit", "neighbor"]
    driverName: str
    phone: str = ""
    capacity: Capacity = Field(default_factory=Capacity)
    crew: int = 1
    lift: bool = False
    location: Point | None = None
    heading: float = 0
    speedMps: float = 0
    status: Literal["idle", "offered", "on_run", "offline"] = "idle"
    safety: Safety = Field(default_factory=Safety)
    simulated: bool = True
    lastSeenAt: ISO | None = None


class Assignment(Doc):
    requestId: str
    vehicleId: str
    planVersion: int
    stopOrder: int = 0
    etaMinutes: float | None = None
    announcedEtaMinutes: float | None = None  # last ETA the resident was told
    announcedEtaSeq: int = 0  # en_route announcements so far (callback key suffix)
    status: AssignmentStatus = "proposed"
    offeredAt: ISO | None = None
    expiresAt: ISO | None = None
    respondedAt: ISO | None = None
    completedAt: ISO | None = None


class Callback(Doc):
    requestId: str
    assignmentId: str
    announcedStatus: RequestStatus
    etaMinutes: float | None = None  # ETA that triggered an en_route callback (worker re-reads the live one)
    state: Literal["queued", "placed", "played", "unanswered"] = "queued"
    key: str
    createdAt: ISO | None = None


class Plan(Doc):
    version: int
    solver: Literal["batched", "greedy", "ortools"]
    solveMs: float = 0
    objective: float | None = None
    changedOffers: int = 0
    createdAt: ISO | None = None
