from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from api.models.common import ISO, Doc, Point

Mobility = Literal["walks", "walker", "manual_wheelchair", "power_wheelchair", "bedbound"]
Assistance = Literal["none", "one_person", "two_person_lift"]
Reach = Literal[
    "not_called", "ringing", "in_call", "answered", "retry_2", "retry_5", "texted", "door_check", "unreachable"
]
Role = Literal["unknown", "needs_ride", "can_help", "left", "stay"]


class Record(BaseModel):
    """What we learned on the call. Written ONLY by the agent (PATCH /households/{id}/record)."""

    model_config = ConfigDict(extra="forbid")

    canLeave: Literal["yes", "no", "unsure"] | None = None
    peopleCount: int | None = Field(default=None, ge=0, le=30)
    mobility: Mobility | None = None
    assistance: Assistance | None = None
    medical: list[Literal["oxygen", "dialysis", "other"]] | None = None
    pets: bool | None = None
    hasCar: bool | None = None
    confidence: dict[str, float] | None = None


class Correction(BaseModel):
    field: str
    from_: object = Field(alias="from")
    to: object
    at: ISO

    model_config = ConfigDict(populate_by_name=True)


class Household(Doc):
    address: str
    location: Point
    zoneId: str
    phone: str
    language: Literal["en", "es"] = "en"
    simulated: bool = True
    record: Record = Field(default_factory=Record)
    corrections: list[Correction] = Field(default_factory=list)
    reach: Reach = "not_called"
    role: Role = "unknown"
    fireArrivalAt: ISO | None = None
    deadlineAt: ISO | None = None
    doorPriority: float = 0.0
    updatedAt: ISO | None = None
