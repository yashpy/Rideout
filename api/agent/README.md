# api/agent/ — resident side

| File | What |
|---|---|
| `flow.py` | Call state machine: `greet → confirm_address → can_leave → household → needs → chair_kind → assistance → readback → neighbor → status/hold → goodbye` |
| `templates.py` | Every sentence about ride status (CONTRACT §4), en + es. The AI never writes these |
| `interpreter.py` | Gemini JSON (CONTRACT §5); Claude Sonnet fallback after 2.5 s |
| `honesty.py` | Drop acks with digits or promise language while no driver has accepted |
| `dialer.py` | Priority queue at SET, 1 call/s, reach ladder |
| `callbacks.py` | Worker: `callbacks` with `state: queued` → place call → `played` / `unanswered` |
| `dedupe.py` | Gemini embeddings + Atlas Vector Search + 50 m rule |
| `zonewatch.py` | Reads county / drill Ready-Set-Go pages through TinyFish and starts dialing at SET |
| `standin.py` | Simulated residents: answer the agent from their persona |
| `session.py` | DB side of a call: loads/saves call state on `calls.agent`, PATCHes the record, syncs the request, logs turns |
| `chat.py` | Text CLI: `uv run --project api python -m api.agent.chat` (from repo root). In-memory DB by default; `--url` to hit a running API; `-v` shows stage/status/record |

Without `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` the interpreter falls back to a rule-based parser, so
the CLI and tests work offline.

Use the core helpers, don't reimplement them:
- `api.requests.upsert_for_household()` to create/update a ride request
- `api.requests.transition()` for any status change (you'll rarely need it from here)
- `api.callbacks.enqueue()` is already called by accept / revoke
