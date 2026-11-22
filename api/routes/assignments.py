"""Offer endpoints. Logic (atomic accept, expiry, revoke) lives in api/assignments.py."""

from collections.abc import Awaitable
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api import assignments as asg
from api import requests as rq
from api.core.db import get_db
from api.routes._util import out

router = APIRouter(prefix="/assignments", tags=["assignments"])


async def _run(coro: Awaitable[dict]) -> dict:
    try:
        return out(await coro)
    except asg.AssignmentError as e:
        raise HTTPException(e.status_code, str(e)) from e
    except rq.RequestError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/{assignment_id}/approve")
async def approve(assignment_id: str) -> dict:
    """Dispatcher approves. The resident hears nothing (approval is not a promise)."""
    return await _run(asg.approve(get_db(), assignment_id))


@router.post("/{assignment_id}/accept")
async def accept(assignment_id: str) -> dict:
    """→ {result: accepted | changed}. Exactly one concurrent accept wins."""
    res = await asg.accept(get_db(), assignment_id)
    return {"result": res["result"], "assignment": out(res.get("assignment"))}


@router.post("/{assignment_id}/decline")
async def decline(assignment_id: str) -> dict:
    return await _run(asg.decline(get_db(), assignment_id))


@router.post("/{assignment_id}/cancel")
async def cancel(assignment_id: str) -> dict:
    """Driver can't make it → revoke this one pickup → request reassigning → resident is told."""
    return await _run(asg.revoke(get_db(), assignment_id, reason="driver cancelled"))


class ProgressBody(BaseModel):
    status: Literal["en_route", "arrived", "completed"]
    etaMinutes: float | None = Field(default=None, ge=0)


@router.post("/{assignment_id}/progress")
async def progress(assignment_id: str, body: ProgressBody) -> dict:
    """Driver app / stand-in drivers: en_route (+ETA, repeat to update), arrived ("Picked up"), completed."""
    return await _run(asg.progress(get_db(), assignment_id, body.status, eta_minutes=body.etaMinutes))
