from datetime import UTC, datetime
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """IDs look like `rq_3f9a1c0b2d4e` (CONTRACT §1)."""
    return f"{prefix}_{uuid4().hex[:12]}"


def aware(dt: datetime | None) -> datetime | None:
    """Mongo drivers may hand back naive UTC datetimes; make them comparable."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)
