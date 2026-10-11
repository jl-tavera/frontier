# Frontier Challenge 1 — Solution

**The agent that operates what has no API.** This is the one document: sections 0–11 are the design, §12 is what was built against it, and the appendix table at the end points at the brief, the recon and every research doc, kept in full in `resources/docs/appendixes/`. `solution.html` renders this document, the architecture diagram **and all appendixes in full**; `uv run resources/docs/build_html.py` regenerates it; [slides.html](slides.html) is the demo deck, built on the same two figures.

## 0. One-page summary

**Problem.** A 15-year-old management system with no API, no docs and no vendor. The evaluator sends a natural-language task plus a VNC desktop (URL + password) and expects a result within 5 minutes. Evaluation runs on an app **we have never seen**, on a clean desktop, and the app **changes at 15:30**.

**Approach.** Our own Python process speaks raw RFB (VNC) over WebSocket to the desktop. A task is a natural-language CRUD action: one fast-model call splits it into typed queries, and a deterministic executor answers reads from a SQLite cache behind a freshness probe and replays learned procedures for writes, clicking stored positions as long as the pixels still match. Perception (CPU-only OCR + classic CV) runs only when something changed, Jev answers the typed questions a changed screen raises, and the tool-use loop, which picks **named elements**, never coordinates, is the last resort. Everything the agent learns about an app (screens, app map, procedures, data) is a per-app memory built **at run time**, so the unseen app is handled exactly like SIGECOM: its first task perceives and learns, every later task replays. For SIGECOM the map is learned ahead of time on the live desktop (`map --visit`) and ships in the image; the data cache is seeded by the first lookup. The 15:30 change is detected by expected-edge checks and repaired locally inside the task.

**What makes it work on an unseen app**
1. No hand-coded map: perception + a learned app map keyed by the app's title bar.
2. Semantic targets (label + role + grid cell) with the last click point that worked cached beside them: replay clicks it while the pixels match, finds a moved target by template match, and re-grounds by perception only on a miss, so a moved or renamed button still works. Each screen and target keeps one **appearance** per app version, and the map is frozen per **epoch**, so a redesign adds a version instead of breaking memory.
3. A disposable SQLite read cache behind a freshness probe (the app's own change log when it has one, like SIGECOM's Bitácora de cambios), so lookups answer in seconds instead of OCR-paging every time.
4. A parse → replay → verify executor with a 270 s guard that always writes a summary; the tool-use loop runs only when there is nothing to replay.
5. One JSONL log of every step, mirrored to stdout, which feeds the Challenge 2 spec, the debrief, the mutation suite and the eval suite (§7).

**Eight decisions** (full table in §4): raw RFB instead of a headless browser · lossless Raw+CopyRect · hybrid OCR+CV perception with Set-of-Mark · learned per-app map instead of a hand map · export/clipboard before OCR for data · online localized repair instead of a full re-learn · replay and probe first, perception on change, the tool-use loop last · every model through OpenRouter, Jev for typed decisions.

**Measurement.** The organizers' 5 practice tasks E1–E5 plus a synthetic suite in the same JSON (Spec S): 16 templates instantiated from the seeded cache (`synth gen`) and 79 tasks read off the live screens, run by `synth eval` on pydantic-evals and scored by the desktop's own `POST /__check` oracle plus checks on status, the `respuesta:` line, the reason keys on a failure and no secret in the summary. Metrics come from the JSONL: steps, click hit rate, fastpath hit / moved / perceived / llm, probe outcome, drift detected / recovered. One report per run, diffed against the previous one on `/evals`; the 15:30 change is rehearsed in advance by `harness mutate <kind>` (§6).

---

## 1. Problem and constraints

**Inputs we have.** The brief ([Appendix A](appendixes/A-challenge-brief.md)), the recon of the target ([Appendix B](appendixes/B-target-recon.md): noVNC → websockify → RFB → SIGECOM shown only as pixels), and `poc/rfb_poc.py`, which already speaks raw RFB with no browser: VNC auth, Raw+CopyRect frames, click/type/key, quiet-time `settle`, and 4 tool functions (screenshot/click/type/key). See Appendix I.

**The entrypoint contract** (Appendix A): `Authorization: Bearer <token>` on every call; `GET /health` → 200; `POST /tasks` receives the task and the desktop (URL + password) and must answer `{"task_id": …}` in **under 2 s**; `GET /tasks/{task_id}` returns `en_curso` / `terminada` / `fallida` plus a summary; **5 minutes per task**. The summary carries one `respuesta: <value>` line for a question (a number first, two values joined by `;`, no line when unanswerable), names the data behind a `fallida`, and never repeats the desktop password or any other secret. After the final status the agent stops acting: anything later lands in the next task as an out-of-task change. Full rules in Appendix A §6.

**The constraint that shapes everything:** evaluation runs on an app we have never seen, on a clean desktop, with 5 minutes per task, and the app changes at 15:30. So "mapping" can't be a hand-built coordinate map of SIGECOM. It has to be something the agent learns while it runs. SIGECOM is only for development.

**Deliverables and timeline** (Appendix A): design doc + diagram at 12:00, the change in the system at 15:30, deployed entrypoint, repo and 2-minute video at 20:00, individual debrief 20:00–21:00, demo 21:15–22:15.

## 2. What we operate against

Digest of the recon in Appendix B:

- The URL serves the **noVNC** web client, not a web app. The business system, **SIGECOM · Distribuidora Andina** (v3.9 at recon time, **V4.2** since the 15:30 change), runs inside a remote desktop and reaches the browser only as framebuffer pixels. No DOM, no REST, no HTTP login.
- Only two live endpoints: `GET /health` → `{"ok":true}` and the `/websockify` WebSocket upgrade. Everything else is 404.
- Wire: browser → `wss://…/websockify` → websockify proxy → TCP RFB 3.8 → VNC server in a Docker container (`86a79607eef2:0`). Auth is VNC Authentication (DES challenge-response). Native framebuffer is **1280×800**.
- The desktop is **shared**: the user label flipped between `operador` and `operador2`, so a human or another client may be on the same display.
- SIGECOM menu tree: Archivo › Inicio · Comercial › Maestros › Clientes, Ventas › Pedidos · Cartera › Facturas · Herramientas › Bitácora de cambios, Reportes generados, Configuración › Integraciones · Ayuda › Acerca de. Facturas has filters (Cliente, Estado), **Buscar / Limpiar / Exportar**, a grid (Código, Cliente, Fecha, Vence, Valor, Estado) and Anterior · Página 1 · Siguiente. Every entity shows a visible code (`CL-0121`, `PD-0143`, `FV-10047`); grids page 20 rows with no total; the Bitácora lists Hora, Usuario, Pantalla, Registro, Campo, Antes, Después, Acción, newest first (Appendix G §7).
- From the organizers (Appendix A §5): a screen repaints up to 1 s after a click, a click held under 100 ms is ignored, and typing into a non-empty field concatenates, so every fill selects all first. The desktop also exposes `POST /__reset` (reload the seed data) and `POST /__check` (score a practice task against the app's state).
- **Integraciones** shows an accounting-connector key with "No comparta esta clave": denylisted.

## 3. Architecture

### 3.1 Components

<div id="arch"></div>

### 3.2 Tech stack

| Layer | Framework / library | Why (and what it replaced) |
|---|---|---|
| Runtime | Python 3.12, `uv` (PEP 723 inline deps + lockfile), one process | One language for transport, vision and agent, no IPC. Node/Go/Rust rewrite discarded (Appendix C §3.2) |
| [A] Entrypoint | FastAPI + uvicorn | Async-native next to the asyncio RFB client. `POST /tasks` validates the Bearer, stores `en_curso`, schedules the job and returns in well under 2 s; the service refuses to start while a required variable is unset |
| [B] Task runner | `asyncio` task per job, in-process state dict, 270 s guard | No broker to deploy before 20:00 (upgrade path in §10) |
| [C] Executor | `openai` SDK pointed at OpenRouter, three model tiers from env: `MODEL_FAST` (task → typed CRUD queries, summary), `MODEL_VLM` (re-ground and re-identify with a Set-of-Mark image), `MODEL_PLANNER` (the tool-use fallback loop, replans). Jev (TypeSafe AI, `typesafe-sdk`) as System 1 for the typed per-step questions behind a 0.8 confidence gate, with `MODEL_FAST` as its keyless fallback. Prompt caching where OpenRouter passes it through | Parse → deterministic executor first, tool-use loop last (Appendix F). Anthropic SDK discarded: one vendor door for every model. Agent frameworks and MCP discarded: no latency gain, more to explain |
| [D] Tools | Plain Python functions: click/type/key over the session; the tool-use loop sees `click_text`, `fill_field`, `type`, `key`, `go_to`, `wait_for`, `done` (≤ 8 calls per turn, the batch stops at the first failure); `read_grid` belongs to the executor, never to the model | Every tool returns an observed effect (diff bbox, new screen id), never just an image |
| [W] Replay | Plain Python over [F]'s stored appearances: `observe` compares the node's static-region crops byte-for-byte with the frame and returns the stored element snapshot on a match; `cv2.matchTemplate` (≥ 0.95, found once) for a target that only moved; `replay_edge` clicks the edge's last-good `xy`, verifies the destination and on a miss perceives, re-grounds and rewrites `xy`. Logs `fastpath: hit / moved / repaired / miss:<reason>` | OCR on every step: about a second per step and more noise on a screen the map already knows. Lossless frames make byte equality and exact template match safe (Appendix H §4) |
| [E] Perception | RapidOCR on ONNX Runtime (angle classifier off, line images cached by hash, threads from `OMP_NUM_THREADS`; the Latin PP-OCRv5 rec model is used when `app/perception/models/latin_rec.onnx` exists, and the file is not in the repo, so the default model runs today), OpenCV Canny + containment → typed tree, re-OCR of the changed bbox only, grounding exact → fuzzy ≥ 0.8 → the only element of that role in the cell | CPU-only hybrid. Detect once, recognize lazily, cache by line pixels (Appendix H). GPU grounding models discarded for the hackathon |
| [F] App memory | App map: one per app epoch (`memory/<app_id>/<version>/map.json`, next to that version's reference PNGs and crops, Appendix E §4.2): nodes and targets with one appearance per version, edges, procedures, frontier | Small, readable in a debrief, zero extra services. Neo4j + vector DB discarded |
| [S] Data sync engine | Plain Python: `need(entity)` → probe: the app's change-log page 1 when one is registered (once per task, one screen for every entity), else the entity's row count + page-1 hash → cache hit or acquire by OCR paging (typed cells: date, Colombian number, text); the clipboard acquirer in `app/sync/clipboard.py` is written but not wired, and `Exportar` output is readable only from the supervisor's seat (Appendix G §7); staging table → swap only on a complete read; 600 s expiry; write-through read-back after our own writes; on a header change, align old → new columns into `column_map` (Appendix G) | Always reading live: 30–120 s per entity. Push/CDC: impossible, there is only pixels |
| [DB] SQLite read cache | stdlib `sqlite3`, WAL, one file, generic JSON rows (`rows`, `rows_staging`, `sync_state`, `unusable`), `json_extract` queries so filters and sums are SQL, not LLM arithmetic | JSON files: no queries, half-written on crash. DuckDB: extra dep. Postgres/Redis: ops work, no benefit for ~1k rows (§10 for later) |
| [G] RFB session | `websockets` ≥ 13 (asyncio client, `binary` subprotocol), `pycryptodome` (VNC DES auth), numpy framebuffer; Raw + CopyRect only; `shared=1`; reconnect (2 attempts, 1 s back-off, handshake redone, full frame re-requested), keep-alive every 5 s; key chords pressed in order and released in reverse; `ClientCutText`/`ServerCutText` clipboard | ~200 LOC we own instead of a headless browser (+300 MB, lossy JPEG, canvas offsets) or a TCP-only VNC library (Appendix C §3.1) |
| [H] Log | One JSONL file per task, every line also written to stdout so `railway logs` shows it; events `task.start`, `task.end`, `plan`, `handoff`, `step`, `drift`, `rejoin`, `blocker`, `sync.probe`, `sync.acquire`, `sync.fallback`, `sync.schema_drift` with `tool`, `args`, `screen_id`, `outcome`, `signal`, `rung`, `cost_ms` | Evidence for the Challenge 2 spec, the debrief, the mutation suite (`ExpectedLogLines`) and `LogMetrics` in the eval (§7) |
| Eval | `synth/` + `harness/`: pydantic-evals (`Dataset`, `Case`, `Evaluator`, `MaxDuration`, baseline diff), Rich for the table and the `/evals` page, pyyaml templates | One command prints the success % per category, offline with `--fake`, live with `--live` (§7); no server, no account, the JSONL stays the single source of evidence |
| Deploy | Railway, Docker, one service, CPU-only | §3.4 |

### 3.3 Per-task flow

<div id="flow"></div>

1. `POST /tasks {task, desktop:{url,password}}` → validate Bearer → store `en_curso` → return `task_id`.
2. Runner opens an RFB session [G] with the given URL+password and takes the first screenshot.
3. A stored snapshot that matches the frame skips OCR; otherwise [E] reads the title band and the app name is fuzzy-matched (0.9) so an OCR misread still finds the map → [F] loads the map for that app and version if one exists, inherits the previous version's map as hints if only the version is new, otherwise starts cold (first task on an app or on a new version: ≤ 45 s menu pre-warm, Appendix E §4.3).
4. [C] splits the task into typed CRUD queries with one fast-model call. The executor runs them on the one screen in schedule order: cache-answerable reads first, then one visit per screen grouped by entity, keeping the parsed order of a write and any query on its entity; answers are reported in the order asked. Reads go change-log probe → [DB] cache → SQL (on a miss, the [S] ladder); writes replay the stored procedure for that (op, entity) with the query's fields, read page 1 back and check that the change log moved. Every step: `observe` replays the stored bbox while the static pixels match (a target that only moved is found by template match) → act → settle → compare with the edge's expected effect → return the observed effect. Perception runs only on a changed screen.
5. Unexpected screen / no effect → [E] flags drift → [F] marks the node stale → [C] runs the repair ladder (§6): Jev picks the new target from the element list, the VLM when Jev is unsure, local re-explore, replan. The tool-use loop with `MODEL_PLANNER` takes over once per task, only when a query has no procedure, the parse is unsure or the ladder is exhausted, and it stores what it did as the procedure for next time. This is the 15:30 path and the unseen-app path.
6. Finish or the guard (270 s, with min(10 s, budget/3) held back from the start for the summary) → [C] writes the summary with one `MODEL_FAST` call inside that reserve (`respuesta:` line, the reason's data on `fallida`, secrets scrubbed); if the call fails, a plain summary built from the results → status `terminada` / `fallida` → the session stops acting. [F] persists anything new it learned (`write_back` in a `finally`, so a crash still saves the map).

### 3.4 Deployment on Railway

One Railway service built from the repo with a Dockerfile. Everything runs in a single process, which is why there is no queue, broker or second service to deploy before 20:00.

| Item | Choice |
|---|---|
| Image | `python:3.12-slim` + `uv sync --frozen --no-dev`; the repo copy (minus `tests/`, `resources/`, `logs/`, `poc/out/` and `.env`, per `.dockerignore`) includes the committed `memory/` (the SIGECOM V4.2 map, ref PNGs, crops). No `cache.sqlite` is committed today, so the first lookup after a deploy pages the grid live and seeds the cache on the container disk. No Tesseract until the deferred 7.1 cross-check is needed |
| Process | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`. One worker, because task state and RFB sessions live in-process |
| Health | `GET /health` → 200 when ready, declared as the Railway health check |
| Config | `railway.json`: `build.builder = "DOCKERFILE"`, `deploy.healthcheckPath = "/health"`, `deploy.restartPolicyType = "ON_FAILURE"`. Railway marks config-as-code as deprecated after 2026-12-01; fine for the hackathon |
| Variables | `TEAM_TOKEN` (Bearer check), `OPENROUTER_API_KEY`, `MODEL_FAST`, `MODEL_VLM`, `MODEL_PLANNER` (OpenRouter model ids, filled by hand before the first build), optional `TYPESAFE_API_KEY` (Jev; without it the typed questions go to `MODEL_FAST`), `LOG_DIR`, `EVALS_DIR` (the `/evals` reports, default `synth/reports`), `OMP_NUM_THREADS` and `OPENBLAS_NUM_THREADS` (the Dockerfile sets both to 4: the container sees 48 host CPUs and uncapped OCR spawned a thread per CPU). No model id is hard-coded. The desktop URL and password arrive **per task** in the request body, never from env (track 1.1) |
| Storage | No volume. SIGECOM's V4.2 map ships in the image, learned on the live desktop after the 15:30 change; the cache is seeded in the container on first use and the probe validates it from then on. Whatever the agent learns at run time, the unseen app's map and cache included, lives on the container disk and is relearned after a redeploy; an unprobed stale cache is worse than an empty one (Appendix G §3.3) |
| Network | Inbound HTTPS from the evaluator. Outbound WSS to the target's `/websockify`, HTTPS to OpenRouter and to the Jev endpoint. Nothing else |
| Resources | CPU-only; OCR and BLAS capped at 4 threads so a deployed step runs at laptop speed (Appendix H timings) |

Smoke test after each deploy:

```bash
curl -s https://<service>.up.railway.app/health
curl -s -X POST https://<service>.up.railway.app/tasks \
  -H "Authorization: Bearer $TEAM_TOKEN" -H "Content-Type: application/json" \
  -d '{"task":"¿Cuántas facturas vencidas hay?","desktop":{"url":"https://…","password":"…"}}'
curl -s https://<service>.up.railway.app/tasks/<task_id> -H "Authorization: Bearer $TEAM_TOKEN"
```

## 4. Key decisions and the alternatives we discarded

| Decision | Chosen | Discarded, and why |
|---|---|---|
| Screen access | Raw RFB over WSS, no browser | Headless browser + noVNC: adds a canvas layer, offsets that depend on resolution, slower, more to deploy (Appendix C) |
| Encoding | Raw+CopyRect (lossless) | Tight/JPEG: compression artifacts hurt OCR and pixel diffs; revisit if bandwidth hurts |
| Clicking | Click the edge's stored last-good `xy` and verify the destination; replay the stored bbox while the static pixels match; a target that only moved by template match of its crop; only then the model names the target and perception grounds it | Model outputs raw x,y: not accurate enough and breaks when layout shifts. OCR on every step: a second per step for nothing on a mapped app |
| Perception | Hybrid on CPU: OCR (RapidOCR; default model, the Latin model when its file is present) for text+bbox + OpenCV for widget boxes → heuristic UI tree; the model picks element ids via Set-of-Mark (Appendix H) | Vision alone: imprecise boxes. OCR alone: no notion of widgets. Raw x,y from the model: fallback only. Specialist grounding models (UI-TARS, OmniParser captioner): need a GPU |
| Knowledge | Learned per-app map, built at runtime | Hand-coded SIGECOM map: zero value on the unseen app |
| Node identity | Title band as hard key + Jaccard over static OCR labels on a coarse grid; VLM only when ambiguous (Appendix E §4.1) | Pure embedding/VLM matching: ~3 MLLM calls per check. Pixel hash: breaks on any data change |
| Edge target | Semantic target (label + role + cell) plus the last-good `xy` as a cache: tried first, verified by the destination, re-grounded by perception and rewritten on a miss | Stored x,y alone: breaks the moment a button moves, which is exactly 15:30, with nothing to repair it. Semantic target only: perception on every replay |
| Initial mapping | Task-driven incremental graph + ≤ 45 s menu pre-warm; traces written back after each task, so the unseen app replays from its second task. SIGECOM only: a dev-time `map --visit` (the same pre-warm function with a flag) and a cache `seed`, committed (Appendix E §4.3) | Full up-front exploration at task time: 10 min to hours per app |
| Settle | Quiet-time + expected-change check | Fixed sleeps: slow and flaky |
| Data reads | Disposable SQLite cache behind a probe: the app's change log when it has one, else the entity's grid; on a miss native export / clipboard first, OCR paging last (Appendix G; built: OCR paging, since the export is unreadable for the operator role and the clipboard acquirer is unwired) | OCR every page: slow and error-prone. Always-live reads: too slow for lookups. Per-entity probe only: one route replay per entity per task |
| Concurrency | One RFB session per task, `shared=1` | Exclusive session: would kick the evaluator/human viewer |
| Change handling | Detect drift with fingerprint + action-effect checks → 4-rung localized repair, written back (§6) | Full re-learn: too slow inside 5 min. Offline-only repair: fails exactly when the change hits |
| Redesign-scale change | Rung 0: open a new epoch that inherits the old map as hints, re-run the pre-warm; screens and targets keep one appearance per version; data columns aligned old → new (§6) | Treating it as N independent edge failures: ≈ 50 s each, budget gone after 3. Deleting the old map: loses the flip-back and the before/after diff |
| Tool exposure | Plain Python functions called by the loop | MCP: an extra process and hop; nothing outside the service needs the tools |
| Executor | One fast-model call parses the task into typed CRUD queries; a deterministic executor replays and verifies; Jev answers the typed questions a changed screen raises; the tool-use loop with batched actions runs only as the fallback and learns the procedure (Appendix F) | Tool-use loop on every task: 3–5× the LLM calls and a second of OCR per step. Plain one-call-per-step loop: slowest. Raw computer-use x,y: discarded above. Agent frameworks: no speed gain |
| Model access | Every LLM through OpenRouter (`openai` SDK with `base_url`), three tiers from env; Jev through `typesafe-sdk` with a keyless fallback behind the same `decide` | Anthropic SDK: a second vendor door and a second fake to maintain; one API shape for every tier is less to build and easier to swap |
| Storage | One JSON per app for the map; one SQLite file for data | Neo4j + vector DB: two services for a 10–20 node graph. Postgres/Redis: ops work with no benefit today (§10 for later) |

Per-track decision tables with more alternatives: transport Appendix C §3, mapping Appendix E §5, executor Appendix F §3, data sync Appendix G §3, perception Appendix H §3.

## 5. Work breakdown

The four starting tracks are 1. WebSocket, 2. platform mapping, 3. Agent tools + loop, 4. data sync. Each one is split into units that can be owned, built and tested on their own. Tracks 5–7 were added because nothing works end to end without them.

**How the tracks are built.** The units below are cut into 9 specs, one package each, 34 tickets (A2 B4 C5 D5 E3 W3 F6 H2 S4), in `resources/specs/` (run book: `resources/specs/README.md`). Spec letters are not the component letters of §3.2. Every ticket cites the unit numbers used here.

| Spec | Package | Units |
|---|---|---|
| A · Service skeleton | `app/main.py`, runner, contracts, log, deploy files | Track 5, 3.5 guard, [H] log |
| B · RFB transport | `app/rfb/` | 1.1–1.3, 1.5, 1.6 (1.4 measured live) |
| C · Perception | `app/perception/` | 7.1–7.6 (7.7 split: VLM x,y in F, Tesseract deferred) |
| D · App memory | `app/memory/` | 2.2–2.6, §6 rungs 0–4, mutations |
| E · Data sync | `app/sync/` | 4.2–4.4, 4.1 once the export probe says where `Exportar` goes |
| W · Warm start and replay | `app/warm/`, committed `memory/` | `observe` / `replay_edge` fast path, `map --visit`, cache `seed` |
| F · Agent | `app/agent/` | 3.1–3.3, 3.5, 3.7, model clients, §6 wired end to end |
| H · Harness | `harness/` | §6 mutation runs (`harness mutate`), Challenge 2 evidence table (`harness evidence`) |
| S · Synthetic tasks and eval | `synth/` | 3.6, §7 metrics, the `/evals` page |

### Track 1 — WebSocket / RFB transport (owner: 1 person, mostly done in the POC; Appendix C)

| # | Sub-problem | Done when | POC status |
|---|---|---|---|
| 1.1 | Connect + VNC auth from a `{url, password}` received **per task** (not from `.env`) | 10/10 connects to SIGECOM using only the request payload | auth works; reads `.env` |
| 1.2 | Reconnect + keep-alive (WS drop, Railway idle timeout) | kill the socket mid-task and the agent recovers in under 5s | missing |
| 1.3 | Settle detection: quiet-time plus a check that an expected region changed | no fixed sleeps; mean settle time measured | quiet-time only (`lazy:` note in `rfb_poc.py`) |
| 1.4 | Encodings: bandwidth vs fidelity (Raw/CopyRect lossless vs Tight/JPEG) | frame time measured both ways; pick one | Raw+CopyRect only |
| 1.5 | Shared-session safety (`shared=1`, `operador`/`operador2` collisions) | 2 clients at once don't break each other's tasks | shared=1 is set |
| 1.6 | Clipboard channel (`ClientCutText` for fast text in, `ServerCutText` for text out) | paste a 200-char string; read copied text back | receive works; send missing |

### Track 2 — Platform mapping, done generically (owner: 1–2 people, the core of the system; Appendixes D and E)

| # | Sub-problem | Done when |
|---|---|---|
| 2.1 | **Screen perception**: screenshot → structured elements (text + bbox + kind: menu, button, field, link, grid cell) → UI tree. **Split out into track 7** | ≥90% of the labels on 5 SIGECOM screens found with correct boxes |
| 2.2 | **Exploration**: the agent walks menus by itself and builds the app map (screen → action → screen), with a denylist of dangerous actions (Integraciones, delete, anular) | full SIGECOM menu tree in under N minutes with no hand-written coordinates (methodology: the 9 menu screens inside the 45 s pre-warm) |
| 2.3 | **Screen fingerprint**: recognize "which screen am I on" (title text + layout hash), resolution-independent | the same screen at 2 resolutions → same ID; 10 distinct screens → 10 ids; dropdown open/closed → same node |
| 2.4 | **Map storage**: a per-app memory (screens, fields, paths, learned procedures), keyed by app identity (title bar) | a second task on the same app reuses the map and finishes faster |
| 2.5 | **Pre-warm vs cold start**: is there time to explore inside 5 minutes, or only on demand? Decide what's explored up front and what's learned during the task | decision written in the design doc, with timings (decided: cold + incremental, one ≤ 45 s menu pre-warm, Appendix E §4.3) |
| 2.6 | **Change detection (the 15:30 incident)**: fingerprint mismatch, element missing, or an action with no effect → mark the map stale and re-explore that screen | simulated change (moved button) gets detected and fixed in the log (mutation suite in Appendix E §6.1) |

### Track 3 — Agent tools + loop + testing (owner: 1 person; Appendix F)

| # | Sub-problem | Done when |
|---|---|---|
| 3.1 | **Tool set by level**: low (`click`, `type`, `key`, `screenshot`) → mid (`click_text("Buscar")`, `fill_field(label, value)`, `read_region`, `wait_for(text)`) → high (`go_to(screen)` replays the stored route, `read_grid()`, `export()`) | each tool has one test against SIGECOM |
| 3.2 | **Coordinate grounding**: the model says a target and the tool resolves it to pixels with 2.1, so the LLM never guesses raw coordinates | ≥95% click hit rate on named targets |
| 3.3 | **Action verification**: every tool returns an observed effect (diff bbox, new screen ID), not just an image | failed actions are reported, not hidden |
| 3.4 | **Token / latency budget**: screenshot size, crops, when to send an image vs text | average step under X s, task under 5 min (options in Appendix F) |
| 3.5 | **Executor + fallback loop** (strategy in Appendix F): parse → replay → verify, the tool-use loop as the last resort; budget guard that stops at about 4:30 and writes a summary | never times out without a summary; a mapped lookup runs with 2 LLM calls |
| 3.6 | **Eval suite** (Spec S): the 5 official practice tasks (`resources/docs/references/pruebas/`) plus 16 YAML templates instantiated from the seeded cache (`synth gen`) and 79 explored tasks read off the live screens (`synth/tasks/explored/`), all in the organizers' JSON with checkable expectations, scored with pydantic-evals → success rate per category | `uv run -m synth eval` prints the success % per category (this is also the measurement plan, §7) |
| 3.7 | **Fast loop strategy**: replay before perception, Jev System 1 on a changed screen, batching inside the fallback (see Appendix F) | s/step and steps/task measured on the 3.6 harness; the chosen strategy beats the baseline |

### Track 4 — Data sync for quick wins (owner: shared with 2; Appendix G)

| # | Sub-problem | Done when |
|---|---|---|
| 4.1 | **Native export**: use `Exportar` / `Reportes generados` to get whole tables instead of paging and OCR-ing | answered: a Reportes generados row; the download is enabled only from the supervisor's seat, so an export is verified by its row (Appendix G §7) |
| 4.2 | **Grid reading**: OCR a grid page → rows, with pagination (`Siguiente`) | read all the Facturas into JSON, spot-checked against the screen |
| 4.3 | **Read cache**: snapshot of entities (Clientes, Facturas, Pedidos) so read-only tasks are answered without a slow UI walk, plus a freshness probe: the app's change log when it has one (SIGECOM: Bitácora de cambios), else the entity's grid; our own writes read back and advance the watermark | a lookup task in under 30s |
| 4.4 | **Clipboard as a data path**: select-all + copy in a field or grid → `ServerCutText`, as a lossless alternative to OCR | proven to work, or ruled out |

### Track 5 — Entrypoint service (not in the list of 4)

`GET /health`, `POST /tasks` (returns in under 2s, runs the work in the background), `GET /tasks/{id}` (`en_curso` / `terminada` / `fallida` + summary in the README's format), Bearer auth, deploy (Railway, §3.4). Small, but **without it the evaluator cannot reach the agent**. Build it first as a stub.

### Track 6 — Deliverables

Design doc + diagram due **12:00** (this document and `solution.html`), README, a 2-minute video, and the Challenge 2 spec + log, where each behavior cites a log line, so **structured logging from the first hour**.

### Track 7 — Screen perception (owner: 1 person; Appendix H)

Measured: OCR detection is ~0.7 s per full screen, but recognition is ~50 ms **per line** (~8 s for the Facturas screen). So the design is detect once, recognize lazily, and cache by line pixels.

| # | Sub-problem | Done when |
|---|---|---|
| 7.1 | **OCR engine + settings**: RapidOCR with the Latin rec model, angle classifier off; lines under 0.8 confidence flagged (Tesseract `spa` cross-check deferred) | accents read correctly; recall/CER/ms table on 5 screens |
| 7.2 | **Widget boxes with CV** (OpenCV contours, grid lines): fields, buttons, selects, links | ≥90% of inputs/buttons boxed on 5 screens |
| 7.3 | **UI tree**: containment + Gestalt grouping + label↔field pairing + kind rules | Facturas filters and one form paired correctly |
| 7.4 | **Grid detection** → named columns and rows (feeds 4.2 `read_grid`) | Facturas page 1 → JSON matches the screen |
| 7.5 | **Set-of-Mark prompt**: element list as text, numbered-box image only on new screens; the model returns an element id | ≥95% hit on named targets (shared with 3.2) |
| 7.6 | **Caches + incremental**: line-pixel-hash cache, per-fingerprint screen cache, re-perceive only `changed_bbox` | known screen <1 s, diff region <300 ms |
| 7.7 | **Fallbacks**: VLM raw x,y for targets with no text and no box (in the agent, Spec F); upscale + Tesseract on low confidence deferred until accents fail or the hit rate drops below 95 % live | an icon-only button is still clickable |

## 6. Incident response: the 15:30 change

Full spec in Appendix E §4.5–§6. The short version:

**Signals, any one triggers:** S1 target label not found · S2 no change after the action · S3 landed on a different known node · S4 landed on an unmatched screen · S5 app version string changed · S6 the edge's outcome histogram has more than one node with real mass · S7 mass drift: under 40 % of the map's menu atoms on screen at task start, or 3 unmatched screens in a row. On the data side, a changed **header hash** of an entity re-acquires that entity and aligns its old columns to the new ones (Appendix G §4.3.4).

**Order of checks on every step:** blocking dialog? → overlay? → data edge? → only then drift. Each of the first three is a cheap false-positive filter.

**Repair ladder, each rung bounded, next rung only on failure:**

| Rung | What | Budget |
|---|---|---|
| 0 | Re-identify the epoch (S5 or S7 only): open a new epoch directory whose map inherits every node as stale and every edge as a hint, re-run the menu pre-warm; the old epoch is never written again. A redesign costs one pre-warm; a known epoch (the app flipped back) loads for free | ≤ 10 s + pre-warm |
| 1 | Re-ground in place: template match of the old crop (moved only, no OCR) → fuzzy label → same role + cell → Jev typed choice over the element list, "which element does what the old one did", old action as few-shot, acted on at ≥ 0.8 → VLM with the Set-of-Mark image. Append the new appearance to the target, keep the node | ≤ 5 s |
| 2 | Local re-explore: mark the node stale, run the pre-warm function on this node only, write the new edges | ≤ 30 s |
| 3 | Re-plan with the edge marked broken: one LLM call, another graph route if one exists, otherwise free plan; rejoin the graph when a known node appears | ≤ 15 s |
| 4 | Rank down, never delete: `fail++`, planner sees `ok/fail` | 0 |

After rung 3 the tool-use loop takes the step with the planner model and writes what worked back as the procedure. Every rung logs `{signal, rung, via, confidence, before, after, cost_ms}` to the JSONL, which is what the Challenge 2 spec and the debrief cite.

**Proving it.** Drift is a function of (stored map, live screen), so `uv run -m harness mutate <kind> [--fake]` applies one change to a copy of the stored map (`run_task(mutate=…)`), runs the task suite through the §7 runner and asserts the kind's expected log lines (`ExpectedLogLines`, the table in `harness/mutate.py`): `rename`, `removed`, `landing_mismatch`, `menu_moved`, `unknown_screen`, `persistent`, `version_bump`, `redesign`, `redesign_silent`, plus two negative controls, `shifted_cell` and `data_state`, that must log no drift. `--fake` runs it offline on the golden v3.9 test map with scripted models, which is what the test suite exercises; the kinds are keyed to that map's edges, so against the shipped V4.2 map it is a rehearsal, not a live proof. The real change bumped SIGECOM from v3.9 to V4.2; the V4.2 map was learned on the live desktop afterwards and is the one that ships (§3.4).

## 7. Measurement plan

Eval suite (3.6, Spec S). Tasks are the organizers' practice-task JSON (`id, nivel, instruccion, estado_esperado, diff_esperado, lista_blanca, respuesta_esperada, claves_razon`), so `POST /__check` takes them as-is. Three sources: the 5 official tasks E1–E5 ([`references/pruebas/`](references/pruebas/)); 16 templates in `synth/templates.yaml` (`lookup-count`, `-value`, `-sum`, `-two`, `-date`, `-zero`, `multi-join`, `create-cliente`, `update-field`, `update-noop`, `export-filtered`, `fail-homonym`, `-missing`, `-duplicate`, `-dangerous`, `-secret`) that `uv run -m synth gen [--per-template 2 --seed 1 --today … --paraphrase K]` instantiates from the seeded cache, each expectation computed by SQL over it, byte-identical per seed, `--paraphrase K` asking `MODEL_FAST` for K rewrites that keep every parameter verbatim; and 79 explored tasks in `synth/tasks/explored/`, read off the live screens during the explorer session. `uv run -m synth check <dir>` validates a tree (official keys only, every expectation recomputed, unique ids and texts, no password-like string). The templates cover every condition in Appendix A §6; the category is the id's first segment (`lookup`, `multi`, `create`, `update`, `export`, `fail`, `explored`, `E` for the official five).

Runner. `uv run -m synth eval [--fake | --live] [--tasks …] [--repeat N] [--baseline <report>] [--publish <url>] [--name <run>]` loads every JSON plus the official five into a pydantic-evals `Dataset`, runs each case through `run_task` one at a time and scores it with `StatusMatches`, `AnswerMatches` (the first number on the `respuesta:` line when the expectation is numeric, else exact), `ReasonKeysNamed`, `NoSecret`, `OracleCheck` (`/__check`, live only), `MaxDuration(300)` and `LogMetrics`. `--fake` runs the real executor over `FakeSession` with scripted models: no network, no keys, the path the test suite exercises. `--live` does `POST /__reset` → `open_session` → `run_task` → `POST /__check` per case with `URL`, `PASSWORD` and `TEAM_TOKEN` from the environment. It prints the pydantic-evals table (diffed against `--baseline`), one success line per category, one triage line per failure (expected vs got, then the first failed `step` or the first `drift` line) and the hint "id format, not the agent" when every failed update fails only `cambios esperados`. The report goes to `EVALS_DIR` (default `synth/reports/`) and, with `--publish`, to the service's `/evals`; exit 1 when any assertion failed.

Metrics (`LogMetrics`, from the task's JSONL): steps, click hit rate, fastpath hit / moved / perceived / llm, probe scope and outcome, drift detected / recovered, Jev decisions and escalation rate, and on a rung 0 the seconds to recognise the epoch, nodes inherited / re-identified and columns aligned / total. A field that never appears yields no key. Not measured yet: LLM calls per tier (the loop emits no `llm` event), seconds per step as a distribution, and the unseen-app path (there is no second app).

Results page. `GET /evals` (`synth/web.py`) lists every report in `EVALS_DIR` newest first with its per-category %, the latest run diffed against the previous one, rendered by Rich; `GET /evals/{run}.json` returns a report; `POST /evals` (bearer) stores one. The router is mounted in `app/main.py`, so one Railway deploy serves the agent and the page; no report is committed yet, so the first live run is the baseline. Mutation runs (§6) go through the same runner with one extra evaluator, so the before/after comparison is two reports on the same page.

## 8. Assumptions and out of scope

- The unseen app is a GUI with readable text (Latin script, horizontal) and conventional widgets. Canvas-heavy, drawing-style apps are out of scope.
- No CAPTCHA or 2FA inside the remote app.
- Destructive actions (delete, anular, Integraciones) need the task to state them explicitly. Denylist by default: `Integraciones, Eliminar, Anular, Borrar, Guardar*, Enviar, Configuración`.
- "Today" is the date the app shows, not the server clock; relative dates in a task are resolved from it.
- An ambiguous target (two customers with the same name, practice task E5) is never guessed: the task ends `fallida` and the summary names the candidates' ids.
- The evaluation desktop can differ from one task to the next; nothing is tied to a URL, the map is keyed by the app's title bar.
- One task at a time per desktop. Parallel tasks on the same desktop aren't supported.
- VNC Authentication (type 2) only; type 1 (None) is trivial to add; VeNCrypt and RA2 are out of scope.
- Icons with no text fall back to the VLM's raw coordinates. CPU-only deploy, no specialist grounding models.
- The change-log probe trusts the app's own log. An edit the app does not log is caught only by the expiry backstop, or by the per-entity probe on a miss.
- The data cache has a known staleness window (an old row edited without changing the count); bounded by an expiry time and the targeted-read path (Appendix G §4.3.1).
- Data acquisition is OCR paging only today, 20 rows a page: `Exportar` output is downloadable only from the supervisor's seat (Appendix G §7) and the clipboard acquirer is written but not wired, so the export → clipboard rungs of the ladder stay design.

## 9. Order and dependencies

1. **Before 12:00**: design doc + diagram (this document), track 5 stub deployed (ticket A1); the task suite is generated, not written (Spec S).
2. **Before any spec (human, needs `.env`)**: capture the screen fixtures, `uv add pydantic-evals`, and the explorer session (agent-browser over the noVNC page, Spec S) that answers Appendix G §7, fixes `synth/templates.yaml` and hand-writes `synth/tasks/explored/`.
3. **Keystone**: A1 alone (package, dependencies, contracts, test fakes, stub entry points); every other ticket is blocked by it.
4. **Critical path**: A1 → C1 → C2 → W2 → F2 → F3 → S3, i.e. 7.1 → 7.2–7.3 → replay fast path → 3.1–3.3 → 3.5 → 3.6: one lookup end to end through the executor with 2 LLM calls.
5. **Parallel**: B (1.x hardening), D1–D5 (mapping memory, build order in Appendix E §7.1), E1–E3 (data sync), C3–C5, W1 and W3, F1 (needs only the fake LLM), F4–F6 beside H1, H2; S1 needs only A1, S2 after F1, S3–S4 after S1.
6. **Warm SIGECOM** after W1 and W3: `map --visit` (600 s, clicks every menu item), commit `memory/`; after 15:30 the V4.2 map was learned the same way and replaced the v3.9 one. `seed` and `synth gen` need the live desktop and run before a live eval; their outputs are not committed.
7. **From 15:30**: `synth eval --live --publish` before and after, `harness mutate <kind>` per kind, `harness evidence <jsonl…>` for the Challenge 2 table: detect → adapt → explain.

Minimum viable subset: A1, A2, B1, C1–C4, D1–D3, E1, E2, W2, F1–F3; add F4 for the first task on an unseen app.

**How to check the split itself.** For each unit: one runnable check against SIGECOM (the "Done when" column). The 3.6 harness is the one number that combines them all.

## 10. Future improvements

Everything below was considered and deliberately left out of the one-day build; each row names the trigger that makes it worth doing.

| Area | Hackathon choice | Upgrade | Trigger |
|---|---|---|---|
| Data cache | Ephemeral SQLite file, generic JSON rows | Postgres on Railway with JSONB (same generic schema, `->>` instead of `json_extract`), persistent and shared across instances. Redis is **not** the cache replacement: no ad-hoc filters or aggregates (Appendix G §3.3) | More than one service instance, or the cache must survive redeploys |
| Task state and queue | In-process dict + asyncio tasks, one uvicorn worker | Redis-backed job queue (e.g. `arq`) with separate worker processes; retries; zero-downtime deploys that drain in-flight tasks | Concurrent tasks across desktops, horizontal scaling, or a deploy during an evaluation window |
| App memory persistence | One JSON per app epoch on the container disk; SIGECOM's committed in the image | Railway volume (`RAILWAY_VOLUME_MOUNT_PATH`) or Postgres; shared across instances | Maps must survive a redeploy or be shared by several workers |
| Map growth | Rank down, never delete; whole map in the prompt | Pruning of dead edges, macro-action mining from frequent traces (Executable Agentic Memory), map summary retrieval instead of the whole graph | The map no longer fits comfortably in the planning prompt |
| Perception | CPU OCR + CV heuristics, Set-of-Mark, exact-scale template match | Upscale + Tesseract `spa` re-OCR of low-confidence lines; scale-tolerant matching; GPU grounding service (UI-TARS, OmniParser V2, UGround) and a learned icon detector; learned tree models (ScreenAI-style) | Accent errors, a resolution change or lossy encoding, an icon-heavy app, or click hit rate below 95 % on the harness |
| Transport | Raw + CopyRect, VNC auth only, quiet-time settle | Tight with JPEG off (lossless zlib), auth types None/VeNCrypt, websocat bridge + asyncvnc as fallback (A4) | Bandwidth hurts, or a target server offers an unsupported encoding or auth type |
| Executor | Parse → executor, Jev on a changed screen, the tool-use loop as the fallback | Jev for `effect_ok` and `done` on every step, not only on a miss; per-tier model ids tuned on the harness; prompt caching verified through OpenRouter's usage fields; parallel tool calls | Seconds per step or LLM calls per task above the harness targets |
| Freshness probe | Change-log page 1 marks every entity stale | Parse the change-log rows to invalidate only the entities they name | Re-acquires cost more than the parse (SIGECOM's Bitácora already names the entity in its Pantalla column, Appendix G §7) |
| Mapping across tasks | Learn on the task path, write back at task end | Offline consolidation between tasks (merge traces, dedupe nodes), background frontier exploration on a spare session, transfer of generic procedures (login, search, export) across apps | A spare desktop session exists, or several apps share UI conventions |
| Observability | One JSONL file | OpenTelemetry traces + a log store, a replay tool that re-renders a task from its JSONL, a Railway volume on `EVALS_DIR` so published reports survive a redeploy | More than one person debugging, or more than one deployment |
| Evaluation | `synth eval --live --publish` by hand, reports on `/evals` | CI job that runs `synth eval --fake` on every push, and the live suite plus `harness mutate` on every deploy with a success-% gate | Any change after the baseline is frozen |
| Security and ops | `.env` locally, Railway variables in prod | Secret rotation, per-task desktop credentials scrubbed from logs, configurable denylist per app, rate limit and body-size cap on `/tasks`, graceful shutdown that marks in-flight tasks `fallida` with a summary | Public exposure beyond the evaluation window |
| Concurrency | One task per desktop | Per-desktop lock + queue; parallel tasks on different desktops; session pooling per desktop | Several desktops or several evaluators at once |
| Human in the loop | None; destructive actions denylisted | Approval callback before a destructive action; partial results streamed to `GET /tasks/{id}` | Real users with write tasks |

## 11. Known unknowns (consolidated)

From the brief (Appendix A): the 15:30 change, answered: SIGECOM went from v3.9 to V4.2 and its map was learned live (§6).

From the recon (Appendix B): exact RFB server version and security type; VNC server implementation and what wraps SIGECOM; whether SIGECOM is a web app in an embedded browser or a native toolkit; the true native resolution/DPI (1280×800 measured by the POC); the accounting connector behind the Integraciones key; per-IP / rate / concurrency limits.

From data sync (Appendix G §7), answered by the explorer session: the Bitácora lists Hora, Usuario, Pantalla, Registro, Campo, Antes, Después, Acción, newest first, and it is the probe; every entity has a visible code; grids show 20 rows and no total; `Exportar` output is downloadable only from the supervisor's seat, so an export is verified by its Reportes generados row. Still open: whether select-all + copy works on grids (the acquirer is unwired); probe cost on the unseen app.

From perception (Appendix H §7): the default OCR model's accuracy on accents (the Latin model file is not deployed); CV box recall; label↔field pairing on Facturas plus one form; grid JSON vs screen; `click_text` hit rate; timings on Railway.

From the executor (Appendix F §7): Jev's out-of-distribution behaviour on the unseen app, vendor-run benchmarks, which OpenRouter models fill the three tiers.

## 12. What was built

One row per spec (`resources/specs/`); "evidence" is what a reader can run or grep today. The letters are spec letters, not the component letters of §3.2.

| Spec | Package | Ships | Evidence | Pending |
|---|---|---|---|---|
| A · Service | `app/main.py`, `runner.py`, `log.py`, `contracts.py`, `Dockerfile`, `railway.json` | `GET /health`, `POST /tasks`, `GET /tasks/{id}` behind the Bearer; refuses to start without the five required variables; 270 s guard with the summary reserve; one JSONL per task mirrored to stdout | `tests/test_main.py`, `test_runner.py`, `test_log.py`; the §3.4 smoke test | — |
| B · RFB | `app/rfb/` | RFB 3.8, DES auth, `shared=1`, Raw + CopyRect; reconnect (2 attempts, 1 s, handshake redone); keep-alive every 5 s; key chords; clipboard send and wait | `tests/rfb/` over `FakeRFBServer` | clipboard used only by tests |
| C · Perception | `app/perception/` | RapidOCR (default model, classifier off, line cache by hash, threads from `OMP_NUM_THREADS`); OpenCV → typed tree; re-OCR of the changed bbox only; grounding exact → fuzzy ≥ 0.8 → cell; `settle(quiet=1.0, timeout=8.0, expect=bbox)` | `tests/perception/` on `tests/fixtures/screens/` | the Latin rec model file is absent |
| D · Memory | `app/memory/` | map per epoch, one appearance per version, edges with `xy` and outcomes; identify dialog → overlay → Jaccard (≥ 0.90 same, ≥ 0.60 ambiguous) with the title band as key; pre-warm ≤ 45 s, `--visit` 600 s; signals S1–S7, rungs 0–4; app name fuzzy-matched at 0.9, a map adopted by menu Jaccard ≥ 0.5 | `tests/memory/`; `drift` and `rejoin` lines | `drift.mutate` is keyed to the golden v3.9 test map |
| E · Sync | `app/sync/` | SQLite `rows`, `rows_staging`, `sync_state`, `unusable`; change-log probe once per task; 600 s expiry; swap only on a complete read; `_align` normalised → fuzzy → shared values → LLM; typed cells | `tests/sync/`; `sync.probe`, `sync.acquire`, `sync.schema_drift` lines | clipboard acquirer unwired; no `cache.sqlite` committed |
| W · Warm | `app/warm/`, `memory/` | `warm map [--visit]`, `warm seed`; `observe` (byte-equal crops → stored snapshot, moved → template ≥ 0.95), `replay_edge` (click the stored xy → verify → repair) | `tests/warm/`; the V4.2 map: 6 nodes, 5 confirmed edges, a reference PNG per node | 0 procedures in the V4.2 map; one OCR-duplicate node |
| F · Agent | `app/agent/` | parse (one `MODEL_FAST` call, 0.8 gate), `schedule`, reads cache → paging → SQL, writes replay + read-back + change-log check, one handoff to the tool loop (7 tools, ≤ 8 calls per turn, the marked image only on perceived screens, prompt caching, seconds left each turn), procedure stored with `$Col` placeholders, summary with a plain fallback, `write_back` in a `finally` | `tests/agent/`; `plan`, `handoff`, `step`, `task.end` lines | no `llm` event, so LLM calls per tier are unmeasured |
| H · Harness | `harness/` | `harness mutate <kind> [--fake]`, 11 kinds with `ExpectedLogLines`; `harness evidence <jsonl…>` confirmed / assumed table | `tests/harness/` | a live `mutate` needs a map whose edges match the table |
| S · Synth | `synth/` | 16 templates, `synth gen / check / eval`, 79 explored tasks, 6 evaluators + `MaxDuration`, baseline diff, reports, the `/evals` page mounted in `app/main.py` | `tests/synth/`, `tests/test_main.py` | no committed report; the generated set needs the cache, so it is not committed |

Totals: 238 tests (`uv run --with pytest pytest -q`, offline), about 90 commits, about 4,350 lines of Python across `app/`, `harness/`, `synth/` and `poc/`; no `TODO` or `NotImplementedError` left.

---

## Appendixes

The source documents live in `resources/docs/appendixes/`, letter-prefixed in this order. Every research appendix (C–H) follows the same structure: 1 Summary · 2 Problem and constraints · 3 Options considered · 4 Chosen design · 5 Trade-offs · 6 Evidence and measurement · 7 Open questions · 8 Sources. Each one opens with a status line saying how the final design uses it. `solution.html` includes all of them in full after this section, and each one is also published as its own page.

| Appendix | Document | Source | Page | Covers |
|---|---|---|---|---|
| A | Challenge brief | [A-challenge-brief.md](appendixes/A-challenge-brief.md) | [open](appendixes/A-challenge-brief.html) | brief, timeline, deliverables, entrypoint contract, evaluation rules |
| B | Target recon (SIGECOM over noVNC) | [B-target-recon.md](appendixes/B-target-recon.md) | [open](appendixes/B-target-recon.html) | hosting, noVNC, RFB transport, SIGECOM screens and menus |
| C | Transport: raw RFB over WebSocket | [C-transport-rfb.md](appendixes/C-transport-rfb.md) | [open](appendixes/C-transport-rfb.html) | where the RFB client runs, language and library, measurements |
| D | Platform mapping: paper comparison | [D-mapping-papers.md](appendixes/D-mapping-papers.md) | [open](appendixes/D-mapping-papers.html) | 12 GUI-agent papers compared, what to take from each |
| E | Platform mapping: methodology | [E-mapping-methodology.md](appendixes/E-mapping-methodology.md) | [open](appendixes/E-mapping-methodology.html) | fingerprint, map schema, appearances and epochs, pre-warm, planning, repair ladder, budget, tests |
| F | Executor | [F-agent-loop.md](appendixes/F-agent-loop.md) | [open](appendixes/F-agent-loop.html) | time budget, loop options L1–L7, Jev System 1 |
| G | Data sync and read cache | [G-data-sync.md](appendixes/G-data-sync.md) | [open](appendixes/G-data-sync.html) | cache, freshness probe, conflicts, column alignment, errors, SQLite schema |
| H | Screen perception | [H-perception.md](appendixes/H-perception.md) | [open](appendixes/H-perception.html) | OCR/CV options, UI tree, pipeline, measured timings |
| I | POC reference | [../../poc/rfb_poc.py](../../poc/rfb_poc.py) | [open](appendixes/I-poc-reference.html) | raw RFB over WSS: VNC auth, Raw+CopyRect, settle, click/type/key, clipboard receive, MCP stub |

Papers and saved articles the research cites are in `resources/docs/references/` (`papers/` for the 12 GUI-agent PDFs, `jev/` for the Jev sources).
