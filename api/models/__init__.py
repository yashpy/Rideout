"""Pydantic models for every collection in CONTRACT §1."""

from api.models.common import Doc, LineString, Point, Polygon
from api.models.household import Correction, Household, Record
from api.models.ride import (
    Assignment,
    AssignmentStatus,
    Callback,
    Capacity,
    Need,
    Plan,
    RequestStatus,
    RideRequest,
    Safety,
    Vehicle,
)
from api.models.world import AuditEntry, Call, Hazard, RoadClosure, Shelter, Turn, Zone

__all__ = [
    "Assignment",
    "AssignmentStatus",
    "AuditEntry",
    "Call",
    "Callback",
    "Capacity",
    "Correction",
    "Doc",
    "Hazard",
    "Household",
    "LineString",
    "Need",
    "Plan",
    "Point",
    "Polygon",
    "Record",
    "RequestStatus",
    "RideRequest",
    "RoadClosure",
    "Safety",
    "Shelter",
    "Turn",
    "Vehicle",
    "Zone",
]
