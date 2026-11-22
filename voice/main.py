"""RideOut voice relay for ElevenLabs Agents: a thin client. Our API chooses every sentence; this
file only relays.

ElevenLabs runs the phone call (telephony, speech-to-text, text-to-speech). The agent is configured
with a *Custom LLM* that points here, so each time the caller finishes speaking ElevenLabs POSTs an
OpenAI-style chat completion request to /v1/chat/completions. We answer with our API's words:

  first request of a call   → POST /agent/start  → speak say[]
  every later request       → POST /agent/turn   → speak say[] (exactly as returned), end the call when done

No LLM runs here. The API does interpretation, the state machine, templates and the honesty guard,
so what a resident hears on the phone is exactly what the tests and evals check.

Call context: the agent's system prompt (set in the ElevenLabs dashboard, see README) carries one line
with ElevenLabs dynamic variables, which ElevenLabs fills in before each request:

  RIDEOUT_CALL conversation={{system__conversation_id}} caller={{system__caller_id}}
  household={{householdId}} call={{callId}} type={{callType}} lang={{language}}

The dialer sets householdId/callId/callType/language on outbound calls; inbound calls fall back to the
caller's number, then DEFAULT_HOUSEHOLD_ID.

Env: PUBLIC_API_URL, INTERNAL_TOKEN, VOICE_LLM_SECRET (the secret ElevenLabs sends as a bearer token),
DEFAULT_HOUSEHOLD_ID (optional), PORT (default 8080).
"""

import json
import logging
import os
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from client import AgentClient

log = logging.getLogger("rideout.voice")

# Said only if our API can't be reached. Fixed text, same safety advice as the status templates.
FALLBACK = {
    "en": "I'm sorry, I'm having trouble on my end. If you can leave safely, leave now. "
    "If fire reaches your home, call 911.",
    "es": "Lo siento, tengo un problema técnico. Si puede salir de forma segura, salga ahora. "
    "Si el fuego llega a su casa, llame al 911.",
}

CALL_LINE = re.compile(r"RIDEOUT_CALL\b(?P<rest>[^\n]*)")
FIELD = re.compile(r"(\w+)=(\S*)")
UNFILLED = re.compile(r"^\{\{.*\}\}$")  # a dynamic variable ElevenLabs had no value for


def call_context(messages: list[dict[str, Any]]) -> dict[str, str]:
    """What we know about the call, read from the RIDEOUT_CALL line in the system prompt."""
    system = "\n".join(_text(m) for m in messages if m.get("role") == "system")
    found = CALL_LINE.search(system)
    raw = dict(FIELD.findall(found.group("rest"))) if found else {}
    f = {k: ("" if UNFILLED.match(v) else v) for k, v in raw.items()}
    conversation = f.get("conversation") or ""
    return {
        "conversation": conversation,
        "householdId": f.get("household") or os.environ.get("DEFAULT_HOUSEHOLD_ID", ""),
        "callId": f.get("call") or f"call_{conversation or uuid.uuid4().hex[:12]}",
        "callType": f.get("type") or "inbound",
        "language": f.get("lang") if f.get("lang") in FALLBACK else "en",
        "callerPhone": f.get("caller") or "",
    }


def _text(m: dict[str, Any]) -> str:
    c = m.get("content")
    if isinstance(c, list):  # OpenAI content parts
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


class Calls:
    """Calls in progress, by ElevenLabs conversation id (what /agent/start told us). Bounded."""

    def __init__(self, cap: int = 2000):
        self._d: OrderedDict[str, dict[str, str]] = OrderedDict()
        self._cap = cap

    def get(self, key: str) -> dict[str, str] | None:
        return self._d.get(key)

    def put(self, key: str, ctx: dict[str, str]) -> None:
        self._d[key] = ctx
        self._d.move_to_end(key)
        while len(self._d) > self._cap:
            self._d.popitem(last=False)


async def reply(client: AgentClient, calls: Calls, messages: list[dict[str, Any]]) -> tuple[list[str], bool]:
    """→ (sentences to speak, end the call)."""
    ctx = call_context(messages)
    key = ctx["conversation"] or ctx["callId"]
    known = calls.get(key)
    lang = (known or ctx)["language"]

    if known is None:
        # First request of this call. People often say "Hello?" the moment they pick up; that turn
        # starts the call, like the greeting would.
        try:
            out = await client.start(
                ctx["householdId"],
                ctx["callType"],  # type: ignore[arg-type]
                ctx["callId"],
                voice_call_id=ctx["conversation"] or None,
                caller_phone=ctx["callerPhone"] or None,
            )
        except Exception:
            log.exception("agent/start failed")
            return [FALLBACK[lang]], True
        # The API tells us which call and household this really is; use those from now on.
        for k in ("callId", "householdId", "callType"):
            if out.get(k):
                ctx[k] = out[k]
        calls.put(key, ctx)
        return list(out.get("say", [])), False

    text = next((_text(m) for m in reversed(messages) if m.get("role") == "user"), "").strip()
    if not text:
        return [], False
    try:
        out = await client.turn(known["callId"], known["householdId"], text, lang)
    except Exception:
        log.exception("agent/turn failed")
        return [FALLBACK[lang]], False
    return list(out.get("say", [])), bool(out.get("done"))


# ── OpenAI-compatible endpoint for the ElevenLabs Custom LLM ─────────────────


def _chunk(cid: str, delta: dict[str, Any], finish: str | None = None) -> str:
    body = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "rideout-relay",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(body)}\n\n"


END_CALL = {"index": 0, "id": "end", "type": "function", "function": {"name": "end_call", "arguments": "{}"}}


async def _stream(cid: str, say: list[str], done: bool) -> AsyncIterator[str]:
    yield _chunk(cid, {"role": "assistant", "content": ""})
    if say:
        yield _chunk(cid, {"content": " ".join(say)})
    if done:  # ElevenLabs' built-in end_call system tool must be enabled on the agent
        yield _chunk(cid, {"tool_calls": [END_CALL]})
        yield _chunk(cid, {}, "tool_calls")
    else:
        yield _chunk(cid, {}, "stop")
    yield "data: [DONE]\n\n"


def create_app(client: AgentClient | None = None) -> FastAPI:
    app = FastAPI(title="RideOut voice relay")
    calls = Calls()
    api = client or AgentClient()
    secret = os.environ.get("VOICE_LLM_SECRET", "")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.post("/v1/chat/completions")
    async def chat(request: Request, authorization: str = Header(default="")) -> Any:
        if secret and authorization != f"Bearer {secret}":
            raise HTTPException(401, "bad token")
        body = await request.json()
        say, done = await reply(api, calls, body.get("messages") or [])
        cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        if body.get("stream", True):
            return StreamingResponse(_stream(cid, say, done), media_type="text/event-stream")
        message: dict[str, Any] = {"role": "assistant", "content": " ".join(say)}
        if done:
            message["tool_calls"] = [{k: v for k, v in END_CALL.items() if k != "index"}]
        return JSONResponse(
            {
                "id": cid,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "rideout-relay",
                "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if done else "stop"}],
            }
        )

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
