# Spec A · Service skeleton + entrypoint

Design: `resources/docs/solution.md` §1 (entrypoint contract), §3.2 rows Runtime/[A]/[B]/[C]/[H], §3.3, §3.4, §4 row Model access, §5 Track 5; Appendix A §4. Run book: [README.md](README.md).

## Problem

The evaluator reaches the agent only through `GET /health`, `POST /tasks` and `GET /tasks/{id}` with a Bearer token, and nothing else in the system can be built in parallel until the package, dependencies, contracts and test fakes exist once on `main`.

## Owns

`pyproject.toml`, `uv.lock`, `.python-version`, `app/main.py`, `app/runner.py`, `app/log.py`, `app/contracts.py`, every `__init__.py`, the three stub entry points, `tests/conftest.py`, `tests/fakes/fake_app.py`, `Dockerfile`, `railway.json`, `.dockerignore`, `.env.example`, `CLAUDE.md`, `README.md`.

## Slices

**A1 · Entrypoint stub and project skeleton** (the keystone; runs alone, every other ticket is blocked by it)

As the evaluator, I call `GET /health` and get 200, `POST /tasks {task, desktop:{url,password}}` with a valid Bearer and get `{"task_id"}` in under 2 s, and `GET /tasks/{id}` and see `en_curso`; without the token I get 401. The worker behind it is a stub that finishes `terminada` with a fixed summary.

Rides in this slice, written once and never edited again by any later ticket:
- `pyproject.toml` with **every** runtime dependency from §3.2 declared now: fastapi, uvicorn, httpx, websockets ≥13, pycryptodome, numpy, pillow, opencv-python-headless, rapidocr-onnxruntime, onnxruntime, openai (the OpenRouter client), typesafe-sdk (Jev), pyyaml; dev group pytest + pytest-asyncio (`asyncio_mode = "auto"`, `testpaths = ["tests"]`); committed `uv.lock`; `.python-version` 3.12.
- `app/contracts.py`: `Element(id, text, bbox, kind, conf=1.0, paired_input=None)` with kind ∈ {title, menu, button, field, select, link, header, cell, text} (Appendix E §2.1); `Target(label, role, cell)`; `Effect(ok, changed_bbox, screen_id, signal, detail, cost_ms)`; `Summary(status, text, data)`; `Session` Protocol: `fb`, `w`, `h`, `clipboard`, `click(x,y)`, `type(text)`, `key(name)`, `settle(quiet=1.0, timeout=8.0, expect=None)`, `send_clipboard(text)`, `close()`; `Perceive = Callable[[ndarray], list[Element]]`.
- `app/log.py`: `Log(path).event(**fields)` JSONL writer; event keys `ts, task_id, tool, args, screen_id, diff, outcome, signal, rung, cost_ms` (§3.2 [H]); names `task.start`, `task.end`, `step`, `drift`, `sync.*`.
- Packages `app/rfb app/perception app/memory app/sync app/agent harness` with empty `__init__.py`, and three stubs each overwritten later by exactly one ticket: `app/rfb/session.py: open_session(url, password) -> Session` (B1), `app/perception/ocr.py: elements(fb) -> list[Element]` (C1), `app/agent/loop.py: run_task(task, session, log, budget_s) -> Summary` (F3). `main.py`/`runner.py` import these and are never edited again.
- `tests/conftest.py` (fixtures: `fixtures_dir`, `facturas_png`, `facturas_fb` as a BGRX ndarray like `RFB.fb`, `fake_app`, `tmp_db`) and `tests/fakes/fake_app.py`: `FakeSession` implementing `Session` over `list[Element]` screens loaded from `tests/fixtures/elements/<screen>.json`, a `(screen, label) → screen` transition table, recorded clicks/keys/text, `settle()` returning at once. Later tickets construct it with their own screens; they never edit it.
- `CLAUDE.md`: check line becomes `uv run --with pytest pytest -q`; a Layout section with the ownership rules from the run book; "tests never touch the network or `.env`; a ticket needing a new dependency stops `needs-human`".
- `.env.example` (`TEAM_TOKEN`; `OPENROUTER_API_KEY`; `MODEL_FAST`, `MODEL_VLM`, `MODEL_PLANNER` with placeholder OpenRouter model ids the human fills before the first build, the app refusing to start while one is unset; `TYPESAFE_API_KEY` marked optional; `LOG_DIR`; and `URL, PASSWORD` for the POC only), `.gitignore` += `logs/`, `*.sqlite-wal`, `*.sqlite-shm` (`memory/` is committed: it holds the SIGECOM golden map, crops and `cache.sqlite` that Spec W produces).

Seam: FastAPI `TestClient` (httpx). Done when: 401 without token; `task_id` returned; status readable; `uv run --with pytest pytest -q` green from a fresh clone.

**A2 · Task runner with budget guard** (plus deploy files and the README run section)

As the evaluator, a task ends `terminada` or `fallida` with a summary; a task that overruns the guard still ends with a summary and never hangs; a worker exception gives `fallida` with the error in the summary; each task writes `LOG_DIR/<task_id>.jsonl` with `task.start`/`task.end`. The runner is one asyncio task per job, in-process state dict, guard at 270 s (configurable for tests), opens the session via `open_session` and calls `run_task`. Rides here: `Dockerfile` (`python:3.12-slim`, `uv sync --frozen`, `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`), `railway.json` (`DOCKERFILE` builder, `/health` health check, `ON_FAILURE` restart), `.dockerignore`, and a README run section (`uv run uvicorn app.main:app`, env vars, the §3.4 curl smoke test).

Seam: `TestClient` with `run_task` monkeypatched to (a) return fast, (b) raise, (c) sleep past an injected 0.2 s budget; assert statuses, summary text, JSONL events. Blocked by A1.

## Decisions already made

Single process, no broker (§3.2); desktop URL and password arrive per task, never from env (§3.4); no volume, cache and maps rebuilt after redeploy; one uvicorn worker; every LLM call goes through OpenRouter (`openai` SDK with `base_url`), never the Anthropic SDK or API, and Jev through `typesafe-sdk` (§3.2 [C], §4 Model access).

## Assumed

- Summary format: free text plus a `data` dict until the material README is seen.
- Task ids are UUID4 strings; state is lost on restart (§10 lists the upgrade).
- Budget guard 270 s; the summary call gets the last 10 s.

## Not building

Queue/broker (trigger: concurrent tasks across desktops); graceful shutdown marking in-flight tasks `fallida` (trigger: deploys during evaluation); rate limit and body cap (trigger: public exposure beyond the window). Railway deploy itself is a human step with A2's files.

## Live checks (human)

Deploy, run the §3.4 smoke test, confirm `POST /tasks` answers in under 2 s from the internet.
