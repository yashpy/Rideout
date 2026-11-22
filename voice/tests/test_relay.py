"""The relay speaks exactly what the API returns, and starts each call once."""

import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import call_context, create_app  # noqa: E402

PROMPT = (
    "You are RideOut.\nRIDEOUT_CALL conversation=conv_1 caller=+16025550188 "
    "household=hh_1 call=call_9 type=outbound lang=es"
)


class FakeAPI:
    def __init__(self):
        self.sent = []

    async def start(self, household_id, call_type, call_id, *, voice_call_id=None, caller_phone=None):
        self.sent.append(("start", household_id, call_type, call_id, voice_call_id, caller_phone))
        return {"say": ["Hola, soy RideOut."], "callId": "call_9", "householdId": "hh_1"}

    async def turn(self, call_id, household_id, text, language="en"):
        self.sent.append(("turn", call_id, household_id, text, language))
        return {"say": ["Gracias.", "Adiós."], "done": text == "bye"}


def test_reads_dynamic_variables_and_ignores_unfilled_ones():
    ctx = call_context([{"role": "system", "content": PROMPT}])
    assert ctx == {
        "conversation": "conv_1",
        "householdId": "hh_1",
        "callId": "call_9",
        "callType": "outbound",
        "language": "es",
        "callerPhone": "+16025550188",
    }
    blank = call_context([{"role": "system", "content": "RIDEOUT_CALL conversation=c2 household={{householdId}}"}])
    assert blank["householdId"] == "" and blank["callType"] == "inbound" and blank["callId"] == "call_c2"


async def _post(client, messages, stream=False):
    return await client.post("/v1/chat/completions", json={"messages": messages, "stream": stream})


async def test_start_then_turns_then_end_call():
    api = FakeAPI()
    transport = httpx.ASGITransport(app=create_app(api))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        sys_msg = {"role": "system", "content": PROMPT}
        r = await _post(c, [sys_msg, {"role": "user", "content": "¿Hola?"}])
        assert r.json()["choices"][0]["message"]["content"] == "Hola, soy RideOut."
        r = await _post(c, [sys_msg, {"role": "user", "content": "¿Hola?"}, {"role": "user", "content": "sí"}])
        assert r.json()["choices"][0]["message"]["content"] == "Gracias. Adiós."
        r = await _post(c, [sys_msg, {"role": "user", "content": "bye"}], stream=True)
        chunks = [json.loads(x[6:]) for x in r.text.split("\n\n") if x.startswith("data: {")]
        text = "".join(ch["choices"][0]["delta"].get("content", "") for ch in chunks)
        assert text == "Gracias. Adiós."
        assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert [s[0] for s in api.sent] == ["start", "turn", "turn"]
    assert api.sent[0] == ("start", "hh_1", "outbound", "call_9", "conv_1", "+16025550188")
    assert api.sent[1] == ("turn", "call_9", "hh_1", "sí", "es")


async def test_api_down_says_the_fixed_safety_line(monkeypatch):
    class Down(FakeAPI):
        async def start(self, *a, **k):
            raise httpx.ConnectError("down")

    transport = httpx.ASGITransport(app=create_app(Down()))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await _post(c, [{"role": "system", "content": PROMPT}])
    msg = r.json()["choices"][0]["message"]
    assert "911" in msg["content"] and msg["tool_calls"][0]["function"]["name"] == "end_call"
