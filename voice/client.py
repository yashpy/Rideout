"""RideOut API client used by the voice relay. All call logic lives in the API, not here.

The relay (main.py):
  1. on pickup:          say(await client.start(household_id, call_type, call_id))
  2. on each utterance:  say(await client.turn(call_id, household_id, text, language))
  3. hang up when the turn result has done=True
"""

import os
from typing import Any, Literal

import httpx

API_URL = os.environ.get("PUBLIC_API_URL", "http://localhost:8000")
TOKEN = os.environ.get("INTERNAL_TOKEN", "")


class AgentClient:
    def __init__(self, base_url: str = API_URL, token: str = TOKEN, timeout: float = 4.0):
        self._http = httpx.AsyncClient(base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)

    async def start(
        self,
        household_id: str,
        call_type: Literal["outbound", "callback", "inbound"],
        call_id: str,
        *,
        voice_call_id: str | None = None,
        caller_phone: str | None = None,
    ) -> dict[str, Any]:
        r = await self._http.post(
            "/agent/start",
            json={
                "householdId": household_id or None,
                "callType": call_type,
                "callId": call_id,
                "voiceCallId": voice_call_id,
                "callerPhone": caller_phone,
            },
        )
        r.raise_for_status()
        return r.json()  # {say: [str], stage, callId?, householdId?, callType?}

    async def turn(self, call_id: str, household_id: str, text: str, language: str = "en") -> dict[str, Any]:
        r = await self._http.post(
            "/agent/turn",
            json={"callId": call_id, "householdId": household_id, "text": text, "language": language},
        )
        r.raise_for_status()
        return r.json()  # {say: [str], stage, done, record, requestStatus}

    async def aclose(self) -> None:
        await self._http.aclose()
