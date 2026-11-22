# evals/ — honesty + accuracy

```bash
uv run --project api python evals/run.py            # free: code checks only (~1 s with the rule interpreter)
uv run --project api python evals/run.py --judge    # + Claude Opus judge (needs ANTHROPIC_API_KEY; costs money)
```

Runs all 40 personas from `data/personas.json` (EN + ES) through the real agent (`api.agent.session`, the same
code as `/agent/turn` and a phone call), in two modes:

| Mode | What the persona says | What it measures |
|---|---|---|
| `script` | its own lines, in order, whatever the agent asks | the interpreter on real, unscripted phrasing |
| `answers` | a direct answer to each question, from its truth | the call flow end to end |

Graded: per-field accuracy vs truth (corrections applied), corrections caught, role and need vs `expect`,
honesty on every agent turn (AI-written acks + `mustNotSay` words outside the fixed templates), latency p50/p95.

Output: `evals/results.json` (with transcripts) and `data/eval-results.json` (summary, shipped in the API image,
served by `GET /system/metrics` and shown on `/system`).

The interpreter used is whatever the env has: rules (no key), Gemini, or Claude. Re-run after adding
`GEMINI_API_KEY`: the `script` numbers are the ones that change.
