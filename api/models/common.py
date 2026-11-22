from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Doc(BaseModel):
    """Base for Mongo documents: `_id` in the DB, `id` in Python, camelCase on the wire."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field(alias="_id")

    def to_mongo(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class Point(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]  # [lon, lat]


class LineString(BaseModel):
    type: Literal["LineString"] = "LineString"
    coordinates: list[tuple[float, float]]


class Polygon(BaseModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float]]]


Geometry = Point | LineString | Polygon | dict[str, Any]
ISO = datetime
