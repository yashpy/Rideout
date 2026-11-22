"""Append-only audit log. Every status move and every rejected action is written here."""

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api.core.util import new_id, utcnow


async def log(db: AsyncIOMotorDatabase, kind: str, message: str, **refs: Any) -> None:
    await db.auditLog.insert_one({"_id": new_id("au"), "kind": kind, "message": message, "refs": refs, "at": utcnow()})
