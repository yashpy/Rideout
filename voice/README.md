# voice/ — ElevenLabs Agents relay

ElevenLabs runs the phone call (number, speech-to-text, text-to-speech). The agent uses a **Custom LLM**
that points at this service, so every caller turn lands on `main.py`, which relays it to the API and
returns `say[]` exactly. No LLM runs here; interpretation, the state machine, templates and the honesty
guard all live in `api/agent/`.

| | |
|---|---|
| Endpoint | `POST /v1/chat/completions` (OpenAI-compatible, streaming). `GET /health` |
| Call context | outbound calls pass `householdId`, `callId`, `callType`, `language` as dynamic variables (set by `api/agent/dialer.py` and `callbacks.py`). Inbound calls match the caller's number, then `DEFAULT_HOUSEHOLD_ID` |
| Ending the call | when the API says `done`, the relay calls ElevenLabs' built-in `end_call` tool |
| If the API is down | the agent says a fixed safety line ("If you can leave safely, leave now. If fire reaches your home, call 911.") and hangs up |

## Set up the ElevenLabs agent (once)

1. ElevenLabs → Agents → **Create agent** (blank).
2. **System prompt** — must contain this line exactly (ElevenLabs fills the `{{…}}` variables):
   ```
   RIDEOUT_CALL conversation={{system__conversation_id}} caller={{system__caller_id}} household={{householdId}} call={{callId}} type={{callType}} lang={{language}}
   ```
   Give `householdId`, `callId`, `callType`, `language` empty default values so inbound calls work.
3. **First message**: leave empty (the API's greeting comes from `/agent/start`).
4. **LLM** → *Custom LLM*: server URL `https://<voice host>/v1`, model `rideout-relay`, API key = a
   workspace secret holding the same value as `VOICE_LLM_SECRET`.
5. **Tools** → enable the system tool **End call**.
6. **Phone numbers** → import a Twilio number (or a SIP trunk) and assign the agent.
7. Put the agent id and phone number id in the API env: `ELEVENLABS_AGENT_ID`,
   `ELEVENLABS_PHONE_NUMBER_ID`, plus `ELEVENLABS_API_KEY` (and `ELEVENLABS_TELEPHONY=sip-trunk` for SIP).

## Run

```bash
cd voice && uv sync
PUBLIC_API_URL=http://localhost:8000 INTERNAL_TOKEN=<same as the API> VOICE_LLM_SECRET=<secret> uv run python main.py
uv run --group dev pytest -q
```
