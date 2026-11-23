"""Calls, hazards, zones, shelters, road closures, audit log."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from api.models.common import ISO, Doc, Geometry, LineString, Point, Polygon


class Turn(BaseModel):
    speaker: Literal["agent", "resident"]
    text: str
    at: ISO
    latencyMs: float | None = None
    requestStatus: str | None = None
    guardBlocked: bool = False


class Call(Doc):
    householdId: str
    direction: Literal["outbound", "inbound", "callback"]
    voiceCallId: str | None = None
    startedAt: ISO | None = None
    endedAt: ISO | None = None
    outcome: Literal["answered", "no_answer", "voicemail", "failed"] | None = None
    language: Literal["en", "es"] = "en"
    turns: list[Turn] = Field(default_factory=list)


class Hazard(Doc):
    kind: Literal["fire", "flood", "road_blocked"]
    source: Literal["firms", "spread", "photo", "manual", "sim"]
    geometry: Geometry
    detectedAt: ISO
    confidence: float | None = None
    photoUrl: str | None = None


class Zone(Doc):
    name: str
    county: str
    status: Literal["ready", "set", "go", "clear"] = "ready"
    polygon: Polygon | None = None
    source: Literal["county", "manual", "fire"] = "manual"
    sourceUrl: str | None = None
    updatedAt: ISO | None = None


class Shelter(Doc):
    name: str
    location: Point
    capacity: int
    occupied: int = 0


class RoadClosure(Doc):
    geometry: LineString
    source: Literal["hazard", "manual", "sim"] = "manual"
    at: ISO


class AuditEntry(Doc):
    kind: str
    message: str
    refs: dict[str, Any] = Field(default_factory=dict)
    at: ISO
