# Solution Design — Frontier Challenge 1

> Superseded on 2026-10-10 by [solution.md](../../solution.md), which absorbed every section of this document. Kept for history; not rendered in solution.html.

## Context
What we have: `challenge.md` (the brief and rubric), `page-technical-analysis.md` (noVNC → websockify → RFB → SIGECOM shown only as pixels), and `poc/rfb_poc.py`, which already speaks raw RFB with no browser (VNC auth, Raw+CopyRect frames, click/type/key, quiet-time `settle`, 4 tool functions: screenshot/click/type/key).

The four starting tracks are 1. WebSocket, 2. platform mapping, 3. Agent tools + loop, 4. data sync. Below, each one is split into units that can be owned, built and tested on their own.

**The constraint that shapes everything:** grading runs on an app **we have never seen**, on a clean desktop, with 5 minutes per task, and the app changes at 15:30. So "mapping" can't be a hand-built coordinate map of SIGECOM. It has to be something the agent learns while it runs. SIGECOM is only for development.

---

## 0. Whole architecture

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
```

### Per-task flow
1. `POST /tasks {task, desktop:{url,password}}` → validate Bearer → store `en_curso` → return `task_id`.
2. Runner opens an RFB session [G] with the given URL+password and takes the first screenshot.
3. [E] fingerprints the screen and identifies the app (title bar) → [F] loads its map if one exists, otherwise starts cold.
4. [C] gets the task + current screen elements + map summary and picks tools. Every tool call: act → settle → [E] diff/fingerprint → return the observed effect.
5. Unexpected screen / no effect → [E] flags drift → [F] marks the node stale → [C] re-explores locally (this is the 15:30 path).
6. Finish or 4:30 guard → [C] writes the summary in the README format → status `terminada` / `fallida`. [F] persists anything new it learned.

### Key decisions (the rubric wants the discarded alternative stated)
| Decision | Chosen | Discarded, and why |
|---|---|---|
| Screen access | Raw RFB over WSS, no browser | Headless browser + noVNC: adds a canvas layer, offsets that depend on resolution, slower, more to deploy (see `research-1-transport.md`) |
| Encoding | Raw+CopyRect (lossless) | Tight/JPEG: compression artifacts hurt OCR and pixel diffs; revisit if bandwidth hurts |
| Clicking | Model names the target → grounded by perception | Model outputs raw x,y: not accurate enough and breaks when layout shifts |
| Perception | Hybrid on CPU: OCR (RapidOCR, Latin model) for text+bbox + OpenCV for widget boxes → heuristic UI tree; Claude picks element ids via Set-of-Mark (see `research-7-perception.md`) | Vision alone: imprecise boxes. OCR alone: no notion of widgets. Raw x,y from the model: fallback only. Specialist grounding models (UI-TARS, OmniParser captioner): need a GPU |
| Knowledge | Learned per-app map, built at runtime | Hand-coded SIGECOM map: zero value on the unseen app |
| Settle | Quiet-time + expected-change check | Fixed sleeps: slow and flaky |
| Data reads | Native export / clipboard first, OCR paging as fallback | OCR every page: slow and error-prone |
| Concurrency | One RFB session per task, `shared=1` | Exclusive session: would kick the evaluator/human viewer |
| Change handling | Detect drift with fingerprint + action-effect checks → local re-explore | Full re-learn: too slow inside 5 min |
| Tool exposure | Plain Python functions called by the loop | MCP: an extra process and hop; nothing outside the service needs the tools |
| Agent loop | Plan-then-execute with Claude, batched actions, verify per step; Jev as an optional fast verifier/picker (see `research-3-agent-loop.md`) | Plain one-call-per-step loop: slowest. Raw computer-use x,y: discarded above. Agent frameworks: no speed gain |

### Assumptions / out of scope (stated in the design doc)
- The unseen app is a GUI with readable text (Latin script) and conventional widgets. Canvas-heavy, drawing-style apps are out of scope.
- No CAPTCHA or 2FA inside the remote app.
- Destructive actions (delete, anular, Integraciones) need the task to state them explicitly. Denylist by default.
- One task at a time per desktop. Parallel tasks on the same desktop aren't supported.

### Measurement plan
Eval harness (3.6): about 15 NL tasks × categories (lookup, filter, create, edit, export, multi-screen), each with an expected answer. Metrics: success %, mean time per task, steps per task, click hit rate, drift detected/recovered. Run the baseline before 15:30 and again after.

---

## 1. WebSocket / RFB transport (owner: 1 person, mostly done in the POC)
| # | Sub-problem | Done when | POC status |
|---|---|---|---|
| 1.1 | Connect + VNC auth from a `{url, password}` received **per task** (not from `.env`) | 10/10 connects to SIGECOM using only the request payload | auth works; reads `.env` |
| 1.2 | Reconnect + keep-alive (WS drop, Railway idle timeout) | kill the socket mid-task and the agent recovers in under 5s | missing |
| 1.3 | Settle detection: quiet-time plus a check that an expected region changed | no fixed sleeps; mean settle time measured | quiet-time only (`lazy:` note at line 117) |
| 1.4 | Encodings: bandwidth vs fidelity (Raw/CopyRect lossless vs Tight/JPEG) | frame time measured both ways; pick one | Raw+CopyRect only |
| 1.5 | Shared-session safety (`shared=1`, `operador`/`operador2` collisions) | 2 clients at once don't break each other's tasks | shared=1 is set |
| 1.6 | Clipboard channel (`ClientCutText` for fast text in, `ServerCutText` for text out) | paste a 200-char string; read copied text back | receive works; send missing |

## 2. Platform mapping, done generically (owner: 1–2 people, the core of the score)
| # | Sub-problem | Done when |
|---|---|---|
| 2.1 | **Screen perception**: screenshot → structured elements (text + bbox + kind: menu, button, field, link, grid cell) → UI tree. **Split out into track 7** | ≥90% of the labels on 5 SIGECOM screens found with correct boxes |
| 2.2 | **Exploration**: the agent walks menus by itself and builds a nav graph (screen → action → screen), with a denylist of dangerous actions (Integraciones, delete, anular) | full SIGECOM menu tree in under N minutes with no hand-written coordinates |
| 2.3 | **Screen fingerprint**: recognize "which screen am I on" (title text + layout hash), resolution-independent | the same screen at 2 resolutions → same ID |
| 2.4 | **Map storage**: a per-app memory (screens, fields, paths, learned procedures), keyed by app identity (title bar) | a second task on the same app reuses the map and finishes faster |
| 2.5 | **Pre-warm vs cold start**: is there time to explore inside 5 minutes, or only on demand? Decide what's explored up front and what's learned during the task | decision written in the design doc, with timings |
| 2.6 | **Change detection (the 15:30 incident)**: fingerprint mismatch, element missing, or an action with no effect → mark the map stale and re-explore that screen | simulated change (moved button) gets detected and fixed in the log |

## 3. Agent tools + loop + testing (owner: 1 person)
| # | Sub-problem | Done when |
|---|---|---|
| 3.1 | **Tool set by level**: low (`click`, `type`, `key`, `screenshot`) → mid (`click_text("Buscar")`, `fill_field(label, value)`, `read_region`, `wait_for(text)`) → high (`navigate_to(screen)`, `read_grid()`, `export()`) | each tool has one test against SIGECOM |
| 3.2 | **Coordinate grounding**: the model says a target and the tool resolves it to pixels with 2.1, so the LLM never guesses raw coordinates | ≥95% click hit rate on named targets |
| 3.3 | **Action verification**: every tool returns an observed effect (diff bbox, new screen ID), not just an image | failed actions are reported, not hidden |
| 3.4 | **Token / latency budget**: screenshot size, crops, when to send an image vs text | average step under X s, task under 5 min (options in `research-3-agent-loop.md`) |
| 3.5 | **Agent loop** (strategy in `research-3-agent-loop.md`): plan → act → verify → replan; budget guard that stops at about 4:30 and writes a summary | never times out without a summary |
| 3.6 | **Eval harness**: about 15 written NL tasks on SIGECOM (lookup, filter, create, edit, export, multi-screen) with checkable expected answers → success rate | a single command prints the success % (this is also the measurement plan in the design doc) |
| 3.7 | **Fast loop strategy**: batching, plan-then-execute, Jev System 1 spike (see `research-3-agent-loop.md`) | s/step and steps/task measured on the 3.6 harness; the chosen strategy beats the baseline |

## 4. Data sync for quick wins (owner: shared with 2)
Deep dive (happy path, freshness, conflicts, errors, DB): `data-sync-design.md`.

| # | Sub-problem | Done when |
|---|---|---|
| 4.1 | **Native export**: use `Exportar` / `Reportes generados` to get whole tables instead of paging and OCR-ing | find out where the export goes (download? a screen?) and whether we can read it |
| 4.2 | **Grid reading**: OCR a grid page → rows, with pagination (`Siguiente`) | read all the Facturas into JSON, spot-checked against the screen |
| 4.3 | **Read cache**: snapshot of entities (Clientes, Facturas, Pedidos) so read-only tasks are answered without a slow UI walk, plus a freshness rule (invalidate after any write) | a lookup task in under 30s |
| 4.4 | **Clipboard as a data path**: select-all + copy in a field or grid → `ServerCutText`, as a lossless alternative to OCR | proven to work, or ruled out |

## 7. Screen perception (owner: 1 person; detail in `research-7-perception.md`)
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

---

## Missing tracks (needed for the score, not in the list of 4)
- **5. Entrypoint service**: `GET /health`, `POST /tasks` (returns in under 2s, runs the work in the background), `GET /tasks/{id}` (`en_curso` / `terminada` / `fallida` + summary in the README's format), Bearer auth, deploy (Railway). Small, but **nothing gets scored without it**. Build it first as a stub.
- **6. Deliverables**: design doc + diagram due **12:00** (30% of the grade), README, a 2-minute video, and the Challenge 2 spec + log, where each behavior cites a log line, so **structured logging from the first hour**.

## Order / dependencies
1. **Before 12:00**: design doc + diagram (built from this breakdown), track 5 stub deployed, 3.6 task list written.
2. **Critical path**: 1.1 → 7.1–7.3 → 3.2 → 3.5 → 5 (one task working end to end).
3. **Parallel**: 2.2–2.4 (mapping memory), 4.x (quick wins for read tasks), 1.2–1.6 (hardening).
4. **From 15:30**: 2.6 + the eval harness, re-run to show detect → adapt → explain.

## How to check the split itself
For each unit: one runnable check against SIGECOM (the "Done when" column). The 3.6 harness is the one number that combines them all.
