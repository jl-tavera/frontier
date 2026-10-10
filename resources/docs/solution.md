# Frontier Challenge 1 — Solution

**The agent that operates what has no API.** This is the one document: sections 0–11 are the design, and the appendix table at the end points at the brief, the recon and every research doc (kept unchanged in `resources/docs/`). `solution.html` renders this document, the architecture diagram **and all appendixes in full**; `uv run resources/docs/build_html.py` regenerates it.

## 0. One-page summary

**Problem.** A 15-year-old management system with no API, no docs and no vendor. The evaluator sends a natural-language task plus a VNC desktop (URL + password) and expects a result within 5 minutes. Grading runs on an app **we have never seen**, on a clean desktop, and the app **changes at 15:30**.

**Approach.** Our own Python process speaks raw RFB (VNC) over WebSocket to the desktop, turns pixels into a UI tree with CPU-only OCR + classic CV, and lets Claude pick **named elements**, never coordinates. Everything the agent learns about an app (screens, nav graph, procedures, data) is a per-app memory built **at run time**, so the unseen app is handled exactly like SIGECOM. The 15:30 change is detected by expected-edge checks and repaired locally inside the task.

**What makes it work on an unseen app**
1. No hand-coded map: perception + a learned nav graph keyed by the app's title bar.
2. Semantic targets (label + role + grid cell), grounded to pixels at run time, so a moved or renamed button still works.
3. A disposable SQLite read cache with a freshness probe, so lookups answer in seconds instead of OCR-paging every time.
4. A plan → act → verify → replan loop with a 270 s guard that always writes a summary.
5. One JSONL log of every step, which feeds the Challenge 2 spec, the debrief and the eval harness.

**Six decisions** (full table in §4): raw RFB instead of a headless browser · lossless Raw+CopyRect · hybrid OCR+CV perception with Set-of-Mark · learned per-app map instead of a hand map · export/clipboard before OCR for data · online localized repair instead of a full re-learn.

**Measurement.** About 15 NL tasks on SIGECOM (lookup, filter, create, edit, export, multi-screen) with checkable answers. Metrics: success %, time per task, steps per task, click hit rate, drift detected/recovered. Baseline before 15:30, re-run after, plus a map-mutation suite that simulates the change in advance (§6).

---

## 1. Problem and constraints

**Inputs we have.** `challenge.md` (brief and rubric, Appendix A), `page-technical-analysis.md` (noVNC → websockify → RFB → SIGECOM shown only as pixels, Appendix B), and `poc/rfb_poc.py`, which already speaks raw RFB with no browser: VNC auth, Raw+CopyRect frames, click/type/key, quiet-time `settle`, and 4 tool functions (screenshot/click/type/key). See Appendix I.

**The entrypoint contract** (Appendix A): `Authorization: Bearer <token>` on every call; `GET /health` → 200; `POST /tasks` receives the task and the desktop (URL + password) and must answer `{"task_id": …}` in **under 2 s**; `GET /tasks/{task_id}` returns `en_curso` / `terminada` / `fallida` plus a summary; **5 minutes per task**.

**The constraint that shapes everything:** grading runs on an app we have never seen, on a clean desktop, with 5 minutes per task, and the app changes at 15:30. So "mapping" can't be a hand-built coordinate map of SIGECOM. It has to be something the agent learns while it runs. SIGECOM is only for development.

**Rubric weights** (Appendix A): systems design 30 % (design doc + diagram, 12:00), execution 40 % (hidden eval set, incident response, repo, Challenge 2 spec, 20:00), demo 15 %, technical depth 15 %.

## 2. What we operate against

Digest of the recon in Appendix B:

- The URL serves the **noVNC** web client, not a web app. The business system, **SIGECOM · Distribuidora Andina v3.9**, runs inside a remote desktop and reaches the browser only as framebuffer pixels. No DOM, no REST, no HTTP login.
- Only two live endpoints: `GET /health` → `{"ok":true}` and the `/websockify` WebSocket upgrade. Everything else is 404.
- Wire: browser → `wss://…/websockify` → websockify proxy → TCP RFB 3.8 → VNC server in a Docker container (`86a79607eef2:0`). Auth is VNC Authentication (DES challenge-response). Native framebuffer is **1280×800**.
- The desktop is **shared**: the user label flipped between `operador` and `operador2`, so a human or another client may be on the same display.
- SIGECOM menu tree: Archivo › Inicio · Comercial › Maestros › Clientes, Ventas › Pedidos · Cartera › Facturas · Herramientas › Bitácora de cambios, Reportes generados, Configuración › Integraciones · Ayuda › Acerca de. Facturas has filters (Cliente, Estado), **Buscar / Limpiar / Exportar**, a grid (Código, Cliente, Fecha, Vence, Valor, Estado) and Anterior · Página 1 · Siguiente.
- **Integraciones** shows an accounting-connector key with "No comparta esta clave": denylisted.

## 3. Architecture

### 3.1 Components

<div id="arch"></div>

```
 Evaluator ──HTTPS+Bearer──► [A] Entrypoint API (FastAPI)
                               │ POST /tasks → task_id (<2s), spawns worker
                               │ GET /tasks/{id} ← status + summary
                               ▼
                         [B] Task Runner (1 asyncio task per job, 4:30 budget guard)
                               │
                               ▼
                         [C] Agent Loop (Claude, tool use)
                     plan → act → verify → replan → summarize
                        │            │              │
                        ▼            ▼              ▼
              [D] Tool Layer   [E] Perception   [F] App Memory
              high: navigate_to,  screenshot →      per-app map: screens,
                    read_grid,    elements(text,     fingerprints, nav graph,
                    export        bbox, kind)        learned procedures,
              mid:  click_text,   OCR + vision       data cache
                    fill_field,   screen fingerprint (JSON/SQLite on disk)
                    wait_for      diff / change det.
              low:  click,type,key,screenshot
                        │            ▲
                        ▼            │ framebuffer
                    [G] RFB Session (poc/rfb_poc.py RFB class, hardened)
                        │  WSS /websockify, VNC auth, settle, clipboard
                        ▼
                  Remote desktop (SIGECOM or the unseen app)

  Cross-cutting: [H] structured JSONL log (every step: tool, args, screen_id,
  diff, outcome) → feeds Challenge 2 spec, debrief, and the eval harness.

  [S] Data Sync Engine (track 4): need(entity) → [DB] SQLite cache hit + probe → SQL answer
      miss / stale → ladder: Exportar → clipboard → OCR paging → staging → atomic swap into [DB]
      one-way pull, app always wins, write tasks never read the cache
```

### 3.2 Tech stack

| Layer | Framework / library | Why (and what it replaced) |
|---|---|---|
| Runtime | Python 3.12, `uv` (PEP 723 inline deps + lockfile), one process | One language for transport, vision and agent, no IPC. Node/Go/Rust rewrite discarded (Appendix C §3) |
| [A] Entrypoint | FastAPI + uvicorn | Async-native next to the asyncio RFB client. `POST /tasks` validates the Bearer, stores `en_curso`, schedules the job and returns in well under 2 s |
| [B] Task runner | `asyncio` task per job, in-process state dict, 270 s guard | No broker to deploy before 20:00 (upgrade path in §10) |
| [C] Agent loop | Anthropic Python SDK. Claude Opus 5.5 (`claude-opus-5-5`) for planning, replanning and recovery; Claude Sonnet 5.5 (`claude-sonnet-5-5`) as the optional cheaper tier for routine steps, only if measurements call for it. Prompt caching on system prompt + tool schemas + map summary. Jev (TypeSafe AI) as an optional System 1 behind a confidence gate | Tool-use loop with batched actions first, then plan-then-execute (Appendix F). Agent frameworks and MCP discarded: no latency gain, more to explain |
| [D] Tools | Plain Python functions in three levels (low: click/type/key/screenshot · mid: click_text, fill_field, read_region, wait_for · high: navigate_to, read_grid, export) | Every tool returns an observed effect (diff bbox, new screen id), never just an image |
| [E] Perception | RapidOCR on ONNX Runtime (Latin PP-OCRv5 rec model, angle classifier off), OpenCV contours + grid lines, numpy, Pillow; Tesseract `spa` cross-check under 0.8 confidence | CPU-only hybrid. Detect once, recognize lazily, cache by line pixels (Appendix H). GPU grounding models discarded for the hackathon |
| [F] App memory | Nav graph: one JSON per app (`memory/<app_id>.json`, Appendix E §4): nodes, edges with semantic targets, procedures, frontier | Small, readable in a debrief, zero extra services. Neo4j + vector DB discarded |
| [S] Data sync engine | Plain Python: `need(entity)` → probe (row count + page-1 hash) → cache hit or acquire through the ladder Exportar → clipboard (`ServerCutText`) → OCR paging; normalise by header text; staging table → one-transaction swap; write-through read-back after our own writes (Appendix G) | Always reading live: 30–120 s per entity. Push/CDC: impossible, there is only pixels |
| [DB] SQLite read cache | stdlib `sqlite3`, WAL, one file, generic JSON rows (`rows`, `sync_state`), `json_extract` queries so filters and sums are SQL, not LLM arithmetic | JSON files: no queries, half-written on crash. DuckDB: extra dep. Postgres/Redis: ops work, no benefit for ~1k rows (§10 for later) |
| [G] RFB session | `websockets` ≥ 13 (asyncio client, `binary` subprotocol), `pycryptodome` (VNC DES auth), numpy framebuffer; Raw + CopyRect only; `shared=1`; `ClientCutText`/`ServerCutText` clipboard | ~200 LOC we own instead of a headless browser (+300 MB, lossy JPEG, canvas offsets) or a TCP-only VNC library (Appendix C §2) |
| [H] Log | JSONL file, one event per step (`tool`, `args`, `screen_id`, `diff`, `outcome`, `signal`, `rung`, `cost_ms`) | Evidence for the Challenge 2 spec, the debrief and the harness |
| Deploy | Railway, Docker, one service, CPU-only | §3.4 |

### 3.3 Per-task flow

1. `POST /tasks {task, desktop:{url,password}}` → validate Bearer → store `en_curso` → return `task_id`.
2. Runner opens an RFB session [G] with the given URL+password and takes the first screenshot.
3. [E] fingerprints the screen and identifies the app (title bar) → [F] loads its map if one exists, otherwise starts cold (first task on an app: ≤ 45 s menu pre-warm, Appendix E §5).
4. [C] gets the task + current screen elements + map summary and plans in one call. Every tool call: act → settle → [E] diff/fingerprint → compare with the edge's expected screen → return the observed effect.
5. Unexpected screen / no effect → [E] flags drift → [F] marks the node stale → [C] runs the repair ladder (§6). This is the 15:30 path.
6. Finish or 270 s guard → [C] writes the summary in the README format → status `terminada` / `fallida`. [F] persists anything new it learned.

### 3.4 Deployment on Railway

One Railway service built from the repo with a Dockerfile. Everything runs in a single process, which is why there is no queue, broker or second service to deploy before 20:00.

| Item | Choice |
|---|---|
| Image | `python:3.12-slim` + `uv sync --frozen`; add `tesseract-ocr tesseract-ocr-spa` only if the 7.1 cross-check is kept |
| Process | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`. One worker, because task state and RFB sessions live in-process |
| Health | `GET /health` → 200 when ready, declared as the Railway health check |
| Config | `railway.json`: `build.builder = "DOCKERFILE"`, `deploy.healthcheckPath = "/health"`, `deploy.restartPolicyType = "ON_FAILURE"`. Railway marks config-as-code as deprecated after 2026-12-01; fine for the hackathon |
| Variables | `TEAM_TOKEN` (Bearer check), `ANTHROPIC_API_KEY`, optional `JEV_API_KEY`, `LOG_DIR`. The desktop URL and password arrive **per task** in the request body, never from env (track 1.1) |
| Storage | No volume. The SQLite cache and the per-app JSON maps live on the container disk and are rebuilt after a redeploy; a stale cache surviving a deploy is worse than an empty one (Appendix G §5) |
| Network | Inbound HTTPS from the evaluator. Outbound WSS to the target's `/websockify` and HTTPS to the Anthropic API. Nothing else |
| Resources | CPU-only. The OCR timings in Appendix H were measured on a laptop and must be re-measured on Railway (7.6) |

Smoke test after each deploy:

```bash
curl -s https://<service>.up.railway.app/health
curl -s -X POST https://<service>.up.railway.app/tasks \
  -H "Authorization: Bearer $TEAM_TOKEN" -H "Content-Type: application/json" \
  -d '{"task":"¿Cuántas facturas vencidas hay?","desktop":{"url":"https://…","password":"…"}}'
curl -s https://<service>.up.railway.app/tasks/<task_id> -H "Authorization: Bearer $TEAM_TOKEN"
```

## 4. Key decisions (the rubric wants the discarded alternative stated)

| Decision | Chosen | Discarded, and why |
|---|---|---|
| Screen access | Raw RFB over WSS, no browser | Headless browser + noVNC: adds a canvas layer, offsets that depend on resolution, slower, more to deploy (Appendix C) |
| Encoding | Raw+CopyRect (lossless) | Tight/JPEG: compression artifacts hurt OCR and pixel diffs; revisit if bandwidth hurts |
| Clicking | Model names the target → grounded by perception | Model outputs raw x,y: not accurate enough and breaks when layout shifts |
| Perception | Hybrid on CPU: OCR (RapidOCR, Latin model) for text+bbox + OpenCV for widget boxes → heuristic UI tree; Claude picks element ids via Set-of-Mark (Appendix H) | Vision alone: imprecise boxes. OCR alone: no notion of widgets. Raw x,y from the model: fallback only. Specialist grounding models (UI-TARS, OmniParser captioner): need a GPU |
| Knowledge | Learned per-app map, built at runtime | Hand-coded SIGECOM map: zero value on the unseen app |
| Node identity | Title band as hard key + Jaccard over static OCR labels on a coarse grid; VLM only when ambiguous (Appendix E §3) | Pure embedding/VLM matching: ~3 MLLM calls per check. Pixel hash: breaks on any data change |
| Edge target | Semantic target (label + role + cell), grounded at run time | Stored x,y: breaks the moment a button moves, which is exactly 15:30 |
| Initial mapping | Task-driven incremental graph + ≤ 45 s menu pre-warm; traces written back after each task | Full up-front exploration: 10 min to hours per app |
| Settle | Quiet-time + expected-change check | Fixed sleeps: slow and flaky |
| Data reads | Native export / clipboard first, OCR paging as fallback; disposable SQLite cache with a probe (Appendix G) | OCR every page: slow and error-prone. Always-live reads: too slow for lookups |
| Concurrency | One RFB session per task, `shared=1` | Exclusive session: would kick the evaluator/human viewer |
| Change handling | Detect drift with fingerprint + action-effect checks → 4-rung localized repair, written back (§6) | Full re-learn: too slow inside 5 min. Offline-only repair: fails at the moment we are graded |
| Tool exposure | Plain Python functions called by the loop | MCP: an extra process and hop; nothing outside the service needs the tools |
| Agent loop | Plan-then-execute with Claude, batched actions, verify per step; Jev as an optional fast verifier/picker (Appendix F) | Plain one-call-per-step loop: slowest. Raw computer-use x,y: discarded above. Agent frameworks: no speed gain |
| Storage | One JSON per app for the map; one SQLite file for data | Neo4j + vector DB: two services for a 10–20 node graph. Postgres/Redis: ops work with no benefit today (§10 for later) |

Per-track decision tables with more alternatives: transport Appendix C §2–3, mapping Appendix E §10, agent loop Appendix F §2, data sync Appendix G §1/§2/§5, perception Appendix H §2.

## 5. Work breakdown

The four starting tracks are 1. WebSocket, 2. platform mapping, 3. Agent tools + loop, 4. data sync. Each one is split into units that can be owned, built and tested on their own. Tracks 5–7 were added because the score needs them.

### Track 1 — WebSocket / RFB transport (owner: 1 person, mostly done in the POC; Appendix C)

| # | Sub-problem | Done when | POC status |
|---|---|---|---|
| 1.1 | Connect + VNC auth from a `{url, password}` received **per task** (not from `.env`) | 10/10 connects to SIGECOM using only the request payload | auth works; reads `.env` |
| 1.2 | Reconnect + keep-alive (WS drop, Railway idle timeout) | kill the socket mid-task and the agent recovers in under 5s | missing |
| 1.3 | Settle detection: quiet-time plus a check that an expected region changed | no fixed sleeps; mean settle time measured | quiet-time only (`lazy:` note in `rfb_poc.py`) |
| 1.4 | Encodings: bandwidth vs fidelity (Raw/CopyRect lossless vs Tight/JPEG) | frame time measured both ways; pick one | Raw+CopyRect only |
| 1.5 | Shared-session safety (`shared=1`, `operador`/`operador2` collisions) | 2 clients at once don't break each other's tasks | shared=1 is set |
| 1.6 | Clipboard channel (`ClientCutText` for fast text in, `ServerCutText` for text out) | paste a 200-char string; read copied text back | receive works; send missing |

### Track 2 — Platform mapping, done generically (owner: 1–2 people, the core of the score; Appendixes D and E)

| # | Sub-problem | Done when |
|---|---|---|
| 2.1 | **Screen perception**: screenshot → structured elements (text + bbox + kind: menu, button, field, link, grid cell) → UI tree. **Split out into track 7** | ≥90% of the labels on 5 SIGECOM screens found with correct boxes |
| 2.2 | **Exploration**: the agent walks menus by itself and builds a nav graph (screen → action → screen), with a denylist of dangerous actions (Integraciones, delete, anular) | full SIGECOM menu tree in under N minutes with no hand-written coordinates (methodology: the 9 menu screens inside the 45 s pre-warm) |
| 2.3 | **Screen fingerprint**: recognize "which screen am I on" (title text + layout hash), resolution-independent | the same screen at 2 resolutions → same ID; 10 distinct screens → 10 ids; dropdown open/closed → same node |
| 2.4 | **Map storage**: a per-app memory (screens, fields, paths, learned procedures), keyed by app identity (title bar) | a second task on the same app reuses the map and finishes faster |
| 2.5 | **Pre-warm vs cold start**: is there time to explore inside 5 minutes, or only on demand? Decide what's explored up front and what's learned during the task | decision written in the design doc, with timings (decided: cold + incremental, one ≤ 45 s menu pre-warm, Appendix E §5) |
| 2.6 | **Change detection (the 15:30 incident)**: fingerprint mismatch, element missing, or an action with no effect → mark the map stale and re-explore that screen | simulated change (moved button) gets detected and fixed in the log (mutation suite in Appendix E §9) |

### Track 3 — Agent tools + loop + testing (owner: 1 person; Appendix F)

| # | Sub-problem | Done when |
|---|---|---|
| 3.1 | **Tool set by level**: low (`click`, `type`, `key`, `screenshot`) → mid (`click_text("Buscar")`, `fill_field(label, value)`, `read_region`, `wait_for(text)`) → high (`navigate_to(screen)`, `read_grid()`, `export()`) | each tool has one test against SIGECOM |
| 3.2 | **Coordinate grounding**: the model says a target and the tool resolves it to pixels with 2.1, so the LLM never guesses raw coordinates | ≥95% click hit rate on named targets |
| 3.3 | **Action verification**: every tool returns an observed effect (diff bbox, new screen ID), not just an image | failed actions are reported, not hidden |
| 3.4 | **Token / latency budget**: screenshot size, crops, when to send an image vs text | average step under X s, task under 5 min (options in Appendix F) |
| 3.5 | **Agent loop** (strategy in Appendix F): plan → act → verify → replan; budget guard that stops at about 4:30 and writes a summary | never times out without a summary |
| 3.6 | **Eval harness**: about 15 written NL tasks on SIGECOM (lookup, filter, create, edit, export, multi-screen) with checkable expected answers → success rate | a single command prints the success % (this is also the measurement plan in the design doc) |
| 3.7 | **Fast loop strategy**: batching, plan-then-execute, Jev System 1 spike (see Appendix F) | s/step and steps/task measured on the 3.6 harness; the chosen strategy beats the baseline |

### Track 4 — Data sync for quick wins (owner: shared with 2; Appendix G)

| # | Sub-problem | Done when |
|---|---|---|
| 4.1 | **Native export**: use `Exportar` / `Reportes generados` to get whole tables instead of paging and OCR-ing | find out where the export goes (download? a screen?) and whether we can read it |
| 4.2 | **Grid reading**: OCR a grid page → rows, with pagination (`Siguiente`) | read all the Facturas into JSON, spot-checked against the screen |
| 4.3 | **Read cache**: snapshot of entities (Clientes, Facturas, Pedidos) so read-only tasks are answered without a slow UI walk, plus a freshness rule (invalidate after any write) | a lookup task in under 30s |
| 4.4 | **Clipboard as a data path**: select-all + copy in a field or grid → `ServerCutText`, as a lossless alternative to OCR | proven to work, or ruled out |

### Track 5 — Entrypoint service (needed for the score, not in the list of 4)

`GET /health`, `POST /tasks` (returns in under 2s, runs the work in the background), `GET /tasks/{id}` (`en_curso` / `terminada` / `fallida` + summary in the README's format), Bearer auth, deploy (Railway, §3.4). Small, but **nothing gets scored without it**. Build it first as a stub.

### Track 6 — Deliverables

Design doc + diagram due **12:00** (30% of the grade; this document and `solution.html`), README, a 2-minute video, and the Challenge 2 spec + log, where each behavior cites a log line, so **structured logging from the first hour**.

### Track 7 — Screen perception (owner: 1 person; Appendix H)

Measured: OCR detection is ~0.7 s per full screen, but recognition is ~50 ms **per line** (~8 s for the Facturas screen). So the design is detect once, recognize lazily, and cache by line pixels.

| # | Sub-problem | Done when |
|---|---|---|
| 7.1 | **OCR engine + settings**: RapidOCR with the Latin rec model, angle classifier off; Tesseract `spa` cross-check under 0.8 confidence | accents read correctly; recall/CER/ms table on 5 screens |
| 7.2 | **Widget boxes with CV** (OpenCV contours, grid lines): fields, buttons, selects, links | ≥90% of inputs/buttons boxed on 5 screens |
| 7.3 | **UI tree**: containment + Gestalt grouping + label↔field pairing + kind rules | Facturas filters and one form paired correctly |
| 7.4 | **Grid detection** → named columns and rows (feeds 4.2 `read_grid`) | Facturas page 1 → JSON matches the screen |
| 7.5 | **Set-of-Mark prompt**: element list as text, numbered-box image only on new screens; Claude returns an element id | ≥95% hit on named targets (shared with 3.2) |
| 7.6 | **Caches + incremental**: line-pixel-hash cache, per-fingerprint screen cache, re-perceive only `changed_bbox` | known screen <1 s, diff region <300 ms |
| 7.7 | **Fallbacks**: upscale + Tesseract on low confidence; Claude raw x,y for targets with no text and no box | an icon-only button is still clickable |

## 6. Incident response: the 15:30 change

Full spec in Appendix E §7–§9. The short version:

**Signals, any one triggers:** S1 target label not found · S2 no change after the action · S3 landed on a different known node · S4 landed on an unmatched screen · S5 app version string changed · S6 the edge's outcome histogram has more than one node with real mass. On the data side, a changed **header hash** of an entity drops and re-acquires that entity (Appendix G §3.4).

**Order of checks on every step:** blocking dialog? → overlay? → data edge? → only then drift. Each of the first three is a cheap false-positive filter.

**Repair ladder, each rung bounded, next rung only on failure:**

| Rung | What | Budget |
|---|---|---|
| 1 | Re-ground in place: fuzzy label → same role + cell → VLM "which element does what the old one did", old action as few-shot. Patch the edge, keep the node | ≤ 5 s |
| 2 | Local re-explore: mark the node stale, run the pre-warm function on this node only, write the new edges | ≤ 30 s |
| 3 | Re-plan with the edge marked broken: one LLM call, another graph route if one exists, otherwise free plan; rejoin the graph when a known node appears | ≤ 15 s |
| 4 | Rank down, never delete: `fail++`, planner sees `ok/fail` | 0 |

Every rung logs `{signal, rung, before, after, cost_ms}` to the JSONL, which is what the Challenge 2 spec and the debrief cite.

**Proving it before 15:30.** Drift is a function of (stored map, live screen), so we mutate the stored map with a `--mutate <kind>` flag (renamed label, removed control, landing mismatch, moved menu item, unknown screen, persistent break) plus two negative controls, and assert the expected log lines. A framebuffer transform hook (0.8× downscale, +40/+25 px shift) proves nothing depends on raw x,y. Run the suite before 15:30, re-run on the real change, show the delta.

## 7. Measurement plan

Eval harness (3.6): about 15 NL tasks × categories (lookup, filter, create, edit, export, multi-screen), each with an expected answer. Metrics: success %, mean time per task, steps per task, click hit rate, drift detected/recovered. Run the baseline before 15:30 and again after.

Per-unit checks (the "Done when" columns in §5) plus, from the JSONL log, for every loop option: seconds per step, LLM calls per task, steps per task, recoveries, escalation rate (Jev → Claude). Mapping-specific: dedup FP/FN, nodes found / 9 in the pre-warm, cold vs warm time, and for each mutation which signal fired, which rung was reached and the seconds to repair (Appendix E §9).

## 8. Assumptions and out of scope

- The unseen app is a GUI with readable text (Latin script, horizontal) and conventional widgets. Canvas-heavy, drawing-style apps are out of scope.
- No CAPTCHA or 2FA inside the remote app.
- Destructive actions (delete, anular, Integraciones) need the task to state them explicitly. Denylist by default: `Integraciones, Eliminar, Anular, Borrar, Guardar*, Enviar, Configuración`.
- One task at a time per desktop. Parallel tasks on the same desktop aren't supported.
- VNC Authentication (type 2) only; type 1 (None) is trivial to add; VeNCrypt and RA2 are out of scope.
- Icons with no text fall back to Claude raw coordinates. CPU-only deploy, no specialist grounding models.
- The data cache has a known staleness window (an old row edited without changing the count); bounded by an expiry time and the targeted-read path (Appendix G §3.1).

## 9. Order and dependencies

1. **Before 12:00**: design doc + diagram (this document), track 5 stub deployed, 3.6 task list written.
2. **Critical path**: 1.1 → 7.1–7.3 → 3.2 → 3.5 → 5 (one task working end to end).
3. **Parallel**: 2.2–2.4 (mapping memory, build order in Appendix E §11), 4.x (quick wins for read tasks), 1.2–1.6 (hardening).
4. **From 15:30**: 2.6 + the eval harness, re-run to show detect → adapt → explain.

**How to check the split itself.** For each unit: one runnable check against SIGECOM (the "Done when" column). The 3.6 harness is the one number that combines them all.

## 10. Future improvements

Everything below was considered and deliberately left out of the one-day build; each row names the trigger that makes it worth doing.

| Area | Hackathon choice | Upgrade | Trigger |
|---|---|---|---|
| Data cache | Ephemeral SQLite file, generic JSON rows | Postgres on Railway with JSONB (same generic schema, `->>` instead of `json_extract`), persistent and shared across instances. Redis is **not** the cache replacement: no ad-hoc filters or aggregates (Appendix G §5) | More than one service instance, or the cache must survive redeploys |
| Task state and queue | In-process dict + asyncio tasks, one uvicorn worker | Redis-backed job queue (e.g. `arq`) with separate worker processes; retries; zero-downtime deploys that drain in-flight tasks | Concurrent tasks across desktops, horizontal scaling, or a deploy during an evaluation window |
| App memory persistence | One JSON per app on the container disk | Railway volume (`RAILWAY_VOLUME_MOUNT_PATH`) or Postgres; versioned maps with a drift history; shared across instances | Maps must survive a redeploy or be shared by several workers |
| Map growth | Rank down, never delete; whole map in the prompt | Pruning of dead edges, macro-action mining from frequent traces (Executable Agentic Memory), map summary retrieval instead of the whole graph | The map no longer fits comfortably in the planning prompt |
| Perception | CPU OCR + CV heuristics, Set-of-Mark | GPU grounding service (UI-TARS, OmniParser V2, UGround) and a learned icon detector; learned tree models (ScreenAI-style) | Icon-heavy app, or click hit rate below 95 % on the harness |
| Transport | Raw + CopyRect, VNC auth only, quiet-time settle | Tight with JPEG off (lossless zlib), auth types None/VeNCrypt, websocat bridge + asyncvnc as fallback (A4), hardened reconnect and keep-alive | Bandwidth hurts, or a target server offers an unsupported encoding or auth type |
| Agent loop | L1+L2 batched tool use, then L3 plan-then-execute | Jev System 1 gate if it passes the adoption criteria; model tiering (Opus 5.5 plan/recover, Sonnet 5.5 routine); prompt caching verified with `cache_read_input_tokens`; parallel tool calls | Seconds per step or LLM calls per task above the harness targets |
| Mapping across tasks | Learn on the task path, write back at task end | Offline consolidation between tasks (merge traces, dedupe nodes), background frontier exploration on a spare session, transfer of generic procedures (login, search, export) across apps | A spare desktop session exists, or several apps share UI conventions |
| Observability | One JSONL file | OpenTelemetry traces + a log store, a dashboard for the 3.6 metrics, a replay tool that re-renders a task from its JSONL | More than one person debugging, or more than one deployment |
| Evaluation | Manual harness run | CI job that runs the 15-task harness on every deploy with a success-% gate and the mutation suite | Any change after the baseline is frozen |
| Security and ops | `.env` locally, Railway variables in prod | Secret rotation, per-task desktop credentials scrubbed from logs, configurable denylist per app, rate limit and body-size cap on `/tasks`, graceful shutdown that marks in-flight tasks `fallida` with a summary | Public exposure beyond the evaluation window |
| Concurrency | One task per desktop | Per-desktop lock + queue; parallel tasks on different desktops; session pooling per desktop | Several desktops or several evaluators at once |
| Human in the loop | None; destructive actions denylisted | Approval callback before a destructive action; partial results streamed to `GET /tasks/{id}` | Real users with write tasks |

## 11. Known unknowns (consolidated)

From the brief (Appendix A): summary format and evaluation rules (material README), details of the 15:30 change, access to the test app, team token.

From the recon (Appendix B): exact RFB server version and security type; VNC server implementation and what wraps SIGECOM; whether SIGECOM is a web app in an embedded browser or a native toolkit; the true native resolution/DPI (1280×800 measured by the POC); the accounting connector behind the Integraciones key; per-IP / rate / concurrency limits.

From data sync (Appendix G §7): where `Exportar` output goes; whether select-all + copy works on grids; whether grids show a total count; whether entities have a visible unique id; whether grids can sort newest first; probe cost on the unseen app.

From perception (Appendix H §5): Latin model accuracy on accents; CV box recall; label↔field pairing on Facturas plus one form; grid JSON vs screen; `click_text` hit rate; timings on Railway.

From the agent loop (Appendix F §4): Jev access (early access key), out-of-distribution behaviour on the unseen app, vendor-run benchmarks.

---

## Appendixes

The source documents, unchanged, in `resources/docs/`. `solution.html` includes all of them in full after this section.

| Appendix | Document | Source file | Covers |
|---|---|---|---|
| A | Challenge brief | [challenge.md](challenge.md) | brief, timeline, deliverables, entrypoint contract, rubric |
| B | Technical diagnosis of the target | [page-technical-analysis.md](page-technical-analysis.md) | hosting, noVNC, RFB transport, SIGECOM screens and menus |
| C | Track 1 research: transport | [research-1-transport.md](research-1-transport.md) | where the RFB client runs, language and library, measurements |
| D | Track 2 research: platform mapping papers | [platform-mapping-papers.md](platform-mapping-papers.md) | 12 GUI-agent papers compared, what to steal |
| E | Track 2 methodology: initial map + remap | [platform-mapping-methodology.md](platform-mapping-methodology.md) | fingerprint, map schema, pre-warm, planning, repair ladder, budget, tests |
| F | Track 3 research: agent loop | [research-3-agent-loop.md](research-3-agent-loop.md) | time budget, loop options L1–L7, Jev deep dive |
| G | Track 4 design: data sync | [data-sync-design.md](data-sync-design.md) | cache, freshness probe, conflicts, errors, SQLite schema |
| H | Track 7 research: perception | [research-7-perception.md](research-7-perception.md) | OCR/CV options, UI tree, pipeline, measured timings |
| I | POC reference | [../../poc/rfb_poc.py](../../poc/rfb_poc.py) | raw RFB over WSS: VNC auth, Raw+CopyRect, settle, click/type/key, clipboard receive, MCP stub |
