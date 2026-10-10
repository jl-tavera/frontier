# frontier

An agent that operates a desktop app with no API, over RFB. Design: [solution.md](resources/docs/solution.md).

## Run

Locally:

```bash
cp .env.example .env        # then fill it
uv sync
uv run --env-file .env uvicorn app.main:app
```

The container (Railway) runs the same app with one worker, since task state and RFB sessions live in-process:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

Env vars (`.env.example`). The app refuses to start while a required one is unset.

| Var | Required | What |
|---|---|---|
| `TEAM_TOKEN` | yes | Bearer token the evaluator sends on `/tasks` |
| `OPENROUTER_API_KEY` | yes | every LLM call goes through OpenRouter |
| `MODEL_FAST`, `MODEL_VLM`, `MODEL_PLANNER` | yes | OpenRouter model ids |
| `TYPESAFE_API_KEY` | no | Jev; without it the typed questions go to `MODEL_FAST` |
| `LOG_DIR` | no | one `<task_id>.jsonl` per task, default `logs` |

The desktop URL and password arrive per task in the request body, never from env. Each task ends `terminada` or `fallida` with a summary within the 270 s guard.

Tests: `uv run --with pytest pytest -q` (offline; never reads `.env`).

Smoke test after each deploy:

```bash
curl -s https://<service>.up.railway.app/health
curl -s -X POST https://<service>.up.railway.app/tasks \
  -H "Authorization: Bearer $TEAM_TOKEN" -H "Content-Type: application/json" \
  -d '{"task":"¿Cuántas facturas vencidas hay?","desktop":{"url":"https://…","password":"…"}}'
curl -s https://<service>.up.railway.app/tasks/<task_id> -H "Authorization: Bearer $TEAM_TOKEN"
```
