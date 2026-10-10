# Platform mapping methodology — initial map + remap, as a graph (track 2)

> Appendix E of [solution.md](../solution.md) · Status: adopted as the track 2 spec (solution.md §5 Track 2, §6) · Links checked 2026-10-10.

## 1. Summary

Distilled from the 12 papers in [Appendix D](D-mapping-papers.md) (PDFs in `../references/papers/`) and filtered through our constraints: an **unseen desktop app**, **pixels only** over VNC/RFB, **5 min per task**, and a **change at 15:30**. Covers sub-problems 2.2–2.6 of [solution.md §5 Track 2](../solution.md); it is the spec for boxes [E] fingerprint and [F] App Memory, and it feeds [C] the agent loop.

Reuses what exists: `poc/rfb_poc.py` → `RFB.fb`, `settle()`, `changed_bbox()`, `click/type/key`; title-bar text for app identity ([Appendix B](B-target-recon.md) §5); perception `elements()` from track 7.

---

## 2. Problem and constraints

### 2.1 Interfaces assumed (M0)

- `elements(fb) → [{id, text, bbox, kind ∈ {title, menu, button, field, link, header, cell, text}, paired_input?}]` from track 7. Timing: known screen < 1 s (7.6 cache), **first sight of a dense screen ≈ 8 s** — budgeted below.
- `settle()`, `changed_bbox(before, after)`, `click/type/key` from `poc/rfb_poc.py`.
- App identity = title-bar text with the version split off: `app_id = "SIGECOM · Distribuidora Andina"`, `version = "v3.9"`. An **epoch** is one `(app_id, version)` and has its own map file (§4.2). A version change is itself a drift signal (S5), and so is mass drift under the same version string (S7).

---

## 3. Options considered

### 3.1 The ten ideas we keep

| # | Idea | Why it matters for us | Source |
|---|---|---|---|
| 1 | **Identify a screen by what it offers, not by its pixels.** Strip dynamic content before comparing. Rules beat LLM/vision matching for this. | A grid full of data changes every second; the labels around it don't. | MobileGPT (3 FP / 0 FN vs 57/28 vision), LLM-Explorer, ActionEngine, UI-KOBE |
| 2 | **Two-stage node matching: cheap retrieval, strict verify.** Only a structural overlap score may merge two screens; a VLM yes/no runs only when ambiguous and may reject all. | Zero LLM calls on the common path; no false merges. | ScreenSearch (Jaccard ≥ 0.93), UI-KOBE, PG-Agent |
| 3 | **Deterministic action signatures. Never store x,y.** *(Superseded: the last-good x,y is now cached beside the signature and rewritten on a miss; see [solution.md §4](../solution.md) Edge target.)* `kind + target label + role + coarse grid cell`. | Raw coordinates are what breaks when a button moves at 15:30. | ScreenSearch, MobileGPT `click(text:…)`; AppAgentX shortcuts as the counter-example |
| 4 | **Every edge stores the screen it should lead to.** | Execution becomes per-step validation; drift is detected for free. | GraphPilot validator, ActionEngine |
| 5 | **Frontier-driven exploration; the LLM only labels.** Pick unexplored actions, shortest known path to them, one action per step. | $0.11/app vs $16.31 with an LLM choosing actions. | LLM-Explorer, UI-KOBE |
| 6 | **Map incrementally from tasks, write back after every task.** | Full exploration costs 10 min–hours; we have 5. Warm start is where the speed comes from: 98.75% vs 82.7%, −62.5% latency. | MobileGPT, AppAgentX |
| 7 | **Plan once over the compact graph, then execute with verification.** Show "this click leads to X" next to candidates. | 1.03 LLM calls/task vs 4.5; 27 s vs 87 s per task. | GraphPilot, ActionEngine, AutoDroid |
| 8 | **Localize a failure to one edge and patch it back into the graph.** Re-derive with the old action as a few-shot example. | The only repair pattern in the literature that writes back; 100% accurate on 16% of actions in MobileGPT. | ActionEngine Patcher, MobileGPT |
| 9 | **Drift has two kinds: appearance (same function, new look/label/place) and workflow (steps reorganised).** Store function → many appearances. | A redesign adds an appearance instead of breaking the memory. Implemented as the `appearances` lists in §4.2. | MAGNET |
| 10 | **Degrade gracefully and rank edges by recency × success.** Cheap signals: no screen change, loops, one action with several outcomes. | Each rung is bounded, so the 5-min budget survives a failure. | LLM-Explorer, UI-KOBE, MAGNET, MobileGPT, ScreenSearch |

**Deliberately skipped** (none fits a one-day build; `lazy:` notes say when to revisit): macro/shortcut mining (EAM, AppAgentX), embeddings + vector DB, Neo4j, offline crawls, trained Q-model/MCTS (EAM), distributed exploration (ScreenSearch).

---

## 4. Chosen design

### 4.1 Screen fingerprint (M1 → sub-problem 2.3)

1. **Keep static elements only:** kind ∈ {title, menu, button, field label, link label, header}. Drop numbers, dates, codes (`FV-#####`), currency, grid body cells, and anything inside a region track 7 flags as data.
2. **Bin each kept label** to a 12×8 grid on **normalized** coordinates → atom `cell|text`. Resolution-independent by construction.
3. **`fingerprint = (title_band, atoms)`.**
   - The title band (top ~15 %) is a **hard key**: it must match before anything else, so Clientes and Proveedores with identical toolbars never merge.
   - Then `sim = Jaccard(atoms)`: **≥ 0.90 same node · 0.60–0.90 ambiguous · < 0.60 new node.**
   - Ambiguous: tie-break by the inbound edge label first; only then pay for one VLM yes/no against the node's reference screenshot, with "none of them" allowed.
   - A node keeps one `(atoms, ref_png)` pair per app version (its **appearances**, §4.2); `sim` is the max over them. In a new epoch (§4.5 rung 0) the inherited stale nodes use a wider ambiguous band, **0.30–0.90**, with at most 5 candidates ranked by title similarity, so a redesigned screen is re-identified as the old node (and gains an appearance) before a new node is created.
4. **Overlays are sub-states, not nodes.** If `changed_bbox` covers < ~25 % of the screen and the parent's labels are still visible (dropdown, combo list, tooltip): `overlay = parent_id + overlay labels`. Close with `Esc`, re-verify the parent. Prevents spurious nodes, `Esc` edges to nowhere, and VLM calls at 0.7–0.9.
5. **Blocking dialogs are checked before drift.** Small centered rectangle with ≤ 3 buttons → OCR its text into the log → `Esc` or the non-destructive button → re-fingerprint. A dialog never counts as drift and never starts the ladder.
6. **In-page state does not change the node.** Filter text, pagination, selected row, scroll are **self-loop edges** with an `effect` field.

**Done when:** the same screen at two resolutions → one id; 10 distinct SIGECOM screens → 10 ids; a dropdown open/closed → same node.

### 4.2 Map schema (M2 → sub-problem 2.4)

One directory per app epoch: `memory/<app_id>/<version>/` holds `map.json` and that version's reference PNGs and static crops, named by node id (`epoch-<n>` when the title bar carries no version). No database. The live epoch is the directory named after the title bar's version; once a newer one exists the old directory is never written again, which is what makes it a frozen version. §4.5 rung 0 says when a new one is opened.

```jsonc
node      = {id, title, description, transient, stale, seen, last_seen,
             appearances: [{version, atoms[], ref_png, elements_snapshot, last_seen}]}   // one per app version, newest first; crops as files
edge      = {from, action: {kind, target: {appearances: [{version, label, role, cell}]}, params},
             to, effect, data?, scroll?, inherited?, ok, fail, last_ok, outcomes: {node_id: count}}
procedure = {task_text, steps: [edge_id | self_loop + params], ok, last_ok}
unexplored[node_id] = [action signatures not yet tried]       // the frontier
denylist  = ["Integraciones", "Eliminar", "Anular", "Borrar", "Guardar*", "Enviar", "Configuración"]
```

- `description` is written by the LLM **lazily**, in one batched call at write-back, never per node.
- `appearances` is MAGNET's "function → many appearances" (§3.1 idea 9): the node id and its description are the stable function; each app version adds a look: its atoms, `ref_png`, `elements_snapshot` and the static crops the replay fast path compares, stored as files in that version's directory. Fingerprint matching and target grounding take the newest appearance first and fall back through the older ones. Rung 1 appends an appearance; it never overwrites one.
- `inherited: true` marks an edge copied from the previous epoch and not yet verified in this one. The planner sees it as a hint, ranked below any verified edge; the first confirmed landing clears the flag.
- `data: true` when the target is not in the static set (a grid row, a record code). A miss on a data edge runs the **find procedure** (search field → type → Enter → `Siguiente` ≤ N pages), never the repair ladder. We store the procedure, not the row click.
- `scroll: true` when the target was only found after one PageDown. "Not found" is declared only after that re-OCR.
- `outcomes` is the histogram of where this action actually led. More than one node with real mass = an unreliable edge (S6).
- Edge rank = `ok / (ok + fail)` × recency decay. The planner sees edges with their `ok/fail`; nothing is deleted (see §4.5, rung 4).
- Denylist labels are never clicked unless the task names them.

**Done when:** a second task on the same app loads the map and finishes faster than the first.

### 4.3 Initial mapping (M3 → sub-problems 2.2 and 2.5)

Decision for 2.5: **cold + incremental**, with one bounded pre-warm. No app-wide exploration ever.

1. **Connect → identify app → load the epoch or start cold.** ~5 s. `(app_id, version)` matches a frozen epoch (the app flipped back): load it. Same `app_id`, new version: §4.5 rung 0 (inherit, pre-warm). No `app_id` at all (the title bar was rebranded): Jaccard of the first screen's menu atoms against every stored app's root node; ≥ 0.5 adopts that app as a new epoch, else cold.
2. **Pre-warm, first task on an epoch only, ≤ 45 s.** Open each top menu: click → `settle` → OCR → `Esc` ≈ 4 s × ≤ 8 menus. Menus whose label matches a task keyword go first. **Open menus only, never click items.** Record `menu → item` edges with `to = unknown`. Skip entirely when the first screen already shows a task keyword. Denylist applied. Result: the planner sees the whole menu tree without visiting a single screen.
3. **Task-driven mapping.** Every action during a task: act → `settle` → `elements` → fingerprint → create/match node → upsert edge with the observed `to`. **An edge is persisted only once its landing fingerprint is confirmed.** Nothing is learned off the task path unless the planner is stuck.
4. **Frontier mode (planner stuck).** Take the unexplored actions on the current node, ranked by label similarity to the task text; one action per step; back out via `Esc` or the recorded return edge. ≤ 40 s per episode.
5. **Write-back at task end.** Nodes, edges, procedure persisted; new nodes described in one batched LLM call.
6. `lazy:` background frontier exploration between tasks, only if a spare session exists. Shared session risk: `operador`/`operador2` collisions.

**Done when:** the first task on SIGECOM records the 9 menu screens as edges within the 45 s pre-warm, with no hand-written coordinates.

### 4.4 Task-time use (M4 → feeds 3.5)

1. **Plan.** On a mapped app the plan is the parsed queries plus the stored procedure for each `(op, entity)` ([Appendix F §4.1](F-agent-loop.md)); the graph planner call below runs only in the fallback loop and at §4.5 rung 3. Input: task + compact graph (node titles + descriptions; edges as `Inicio —[click "Cartera › Facturas"]→ Facturas`; procedures whose `task_text` is similar). Output: ordered steps, each an edge, a self-loop with params, or `explore`.
2. **Execute a step.** Cheapest grounding first: the stored bbox while the node's static crops match byte-for-byte (Spec W `observe`); a target that only moved, by template match of its stored crop over the frame (≥ 0.95, logged `fastpath: moved`); only then perception: ground `target.label` on the current `elements` (exact → fuzzy → same role in the same cell). Then act → `settle` → fingerprint → **compare with `edge.to`**. Match: `ok++`, next step. Mismatch: §4.5.
   - `fill_field`: click the **paired input box** (7.3), confirm a caret or text appeared inside that bbox, else `Tab`. Keyboard focus is invisible to the fingerprint.
3. **Verify completion** against the last screen's elements; write the summary in the README format.
4. **Targets per step:** act + settle ≤ 2 s, OCR ≤ 1 s when it runs, fingerprint in ms. **LLM calls per task: 2 on a warm map (parse, summary), ≤ 3 with one replan.**

### 4.5 Change detection and repair (M5 → sub-problem 2.6, the 15:30 path)

**Signals** (any one triggers):

| | Signal |
|---|---|
| S1 | target label not found on the screen |
| S2 | no change after the action (`changed_bbox is None`, or the same fingerprint on a non-self-loop edge) |
| S3 | landed on a different known node |
| S4 | landed on an unmatched screen |
| S5 | app version string changed |
| S6 | the edge's `outcomes` histogram has > 1 node with real mass |
| S7 | mass drift: at task start fewer than 40 % of the map's menu atoms are on screen, or 3 consecutive S4 inside one task (threshold tunable) |

**Order of checks on every step: blocker dialog? → overlay? → data edge? → only then drift.** Each of the first three is a cheap false-positive filter.

**Ladder** — four rungs, each bounded, next rung only on failure. Every rung logs `{signal, rung, before, after, cost_ms}` to the JSONL (this is the evidence the Challenge 2 spec cites).

| Rung | What | Budget | When it fires |
|---|---|---|---|
| 0 | **Re-identify the epoch.** Open `memory/<app_id>/<new version>/` with a `map.json` copied from the previous epoch, every node `stale` and every edge `inherited`; appearances keep their `version`, so their crops and `ref_png` still resolve into the old directory; run the §4.3 step 2 pre-warm again. From here each inherited edge goes through rungs 1–3 with its old appearance as the few-shot, and unmatched screens are re-identified against inherited nodes before becoming new ones (§4.1). | ≤ 10 s + one pre-warm | S5 or S7 only: a version bump or a redesign. |
| 1 | **Re-ground in place.** Template match of the old crop (moved only, no OCR) → fuzzy label → same role + cell → Jev typed choice over the element list, "which element does what the old one did", with the old action as a few-shot example, acted on at confidence ≥ 0.8 → VLM with the Set-of-Mark image. Append the new look to `target.appearances`, keep the node. | ≤ 5 s | Most of 15:30: a renamed label, a moved item, a new field or confirm dialog. |
| 2 | **Local re-explore.** Mark the node `stale`, run §4.3 step 4 on this node only, write the new edges. It is the pre-warm function applied to one node: no new code. | ≤ 30 s | An item moved to another menu. |
| 3 | **Re-plan with the edge marked `broken`.** One LLM call: the planner takes another graph route if one exists, otherwise plans freely. Every step still fingerprints, so the moment a known node appears we **rejoin the graph.** | ≤ 15 s | Workflow drift. |
| 4 | **Rank down, never delete.** `fail++`; the planner prompt shows the edge with its `ok/fail`. | 0 | Always, after any failure. |

Entry rung depends on the signal: **S5/S7 → 0, then every inherited edge follows S1 → 1 → 2 → 3. S1 → 1 → 2 → 3. S3/S4 → `Esc`/back to the previous node (2 s) → 3.** After rung 3 the tool-use loop takes the step ([Appendix F §4.1](F-agent-loop.md)) and writes what worked back as the procedure.

Why rung 0 exists: without it a redesign is discovered one edge at a time, at up to 50 s per edge, and the budget is gone after three. Recognising the epoch once turns it into a first task on a new app with the old map as hints: one pre-warm, and the old version stays loadable for a flip-back and for the before/after diff in the debrief.

Why four and not five: a task-driven graph of 10–20 nodes almost never has an alternative route, so the papers' "alternative path" rung would not fire; it is folded into rung 3. Deletion risks losing a good edge to three unlucky failures, so pruning is replaced by ranking. `lazy:` add pruning when the map grows past what fits in the prompt.

**Done when:** every mutation in §6.1 is detected, the expected rung is reached, and the recovery is visible in the log before 15:30.

### 4.6 Time budget per task (M6)

300 s total, hard stop at 270 s.

| t (s) | Step | When |
|---|---|---|
| 0–2 | connect + first frame | every task |
| 2–10 | static-crop gate or OCR, fingerprint, title → load map or cold (under 1 s on a replay hit; 8 s on first sight of a dense screen) | every task |
| → 45 | pre-warm (§4.3 step 2) | first task on an epoch only (also right after rung 0); cap 45 s |
| + 3 | parse: one fast-model call (the 15 s graph planner call only in the fallback loop) | every task |
| → 230 | execute: replay ≈ 1–2 s per step (act + settle, no OCR) on a mapped app; ground + act + settle + incremental OCR ≈ 3–4 s per step when perceiving → ~45 steps; + 0.1 s per Jev call, + 3 s only when a VLM verify fires | every task |
| 230–270 | reserve: one re-plan (15 s) + one local re-explore (20 s); execution flows into it if unused | on drift |
| 270 | summary call (~10 s) → persist map → status | never dropped |

What the 4:30 guard drops, in order: an in-flight repair at rung ≥ 2; unverified edges (never persisted anyway); VLM verifies (ambiguous → new node). The summary, the persist and the JSONL always run.

---

## 5. Trade-offs

Decisions for the design doc, with the discarded alternative:

| Decision | Chosen | Discarded, and why |
|---|---|---|
| Initial mapping | Task-driven incremental graph + a ≤ 45 s menu pre-warm; traces written back after each task | Full up-front exploration (AutoDroid, LLM-Explorer, UI-KOBE, ActionEngine): 10 min–hours per app, impossible inside a 5 min task on an unseen app |
| Node identity | Title band as hard key + Jaccard over static OCR labels on a coarse grid; VLM only when ambiguous | Pure embedding/VLM matching (PG-Agent): ~3 MLLM calls per check, unstable across models (UI-KOBE A.1). Pixel hash: breaks on any data change |
| Overlays and dialogs | Sub-states of the parent node; dialogs handled before drift | Every popup as a node: spurious nodes, dead `Esc` edges, false drift |
| Edge target | Semantic target (label + role + cell), grounded to pixels at run time | Stored x,y (AppAgentX shortcuts): breaks the moment a button moves, which is exactly 15:30 |
| Data targets | `data` edges → find procedure | Storing the row click: fails on any other data state, triggers the ladder for nothing |
| Task-time use | One planning call over the graph, then per-step verification against `edge.to` | Reactive per-step LLM without a graph: 3–5× more calls (GraphPilot, ActionEngine) |
| Remap | Online, localized, 4-rung ladder written back into the graph; rank down, never delete | Full re-learn: too slow. Offline-only repair (UI-KOBE, EAM): fails at the moment we are graded. Passive decay alone (MAGNET): too slow within one task. Pruning: loses good edges to unlucky failures |
| Redesign | Epoch per `(app_id, version)`, inherited as hints; one appearance per version on nodes and targets | A single mutable map: pollutes on a redesign and cannot flip back. Full re-learn on a version bump: throws away procedures that still hold. Treating a redesign as independent edge failures: ≈ 50 s each |
| Change test | Mutate the stored map + framebuffer transform hook | Waiting for the real 15:30 change: no baseline, nothing measurable in advance |
| Storage | One JSON per app | Neo4j + vector DB (AppAgentX, EAM): two services for a graph of 10–20 nodes |

---

## 6. Evidence and measurement (M7 → feeds the 3.6 harness)

| Unit | Check | Metric |
|---|---|---|
| §4.1 fingerprint | same screen at 2 resolutions → one id; 10 distinct SIGECOM screens → 10 ids; dropdown open/closed → same node | dedup FP / FN |
| §4.3 mapping | first task on SIGECOM records the 9 menu screens | nodes found / 9; pre-warm seconds |
| §4.4 warm start | the same task cold then warm | time, steps, LLM calls |
| §4.5 remap | the mutation set below | detected (which signal), rung reached, seconds to repair, task success after repair |

### 6.1 Simulating the 15:30 change without touching SIGECOM

Drift is a function of (stored map, live screen). We can't change the screen, so we mutate the map: the detect → repair → log code path is identical. Freeze a golden `map.json` once warm tasks pass. Per test: fresh copy → `--mutate <kind>` → run 3–4 tasks → assert the JSONL lines. The same flag is the demo script.

| Mutation | Simulates | Expected log |
|---|---|---|
| `target.label` Facturas → Facturación | renamed label | S1 → rung 1 fuzzy match patches the edge |
| `target.label` → "Zzzz" | control removed | rung 1 fails → rung 2 re-explore finds the real item |
| `edge.to` → another node's fingerprint | landing mismatch | S3 → rung 1 retargets |
| delete all edges into a node | menu item moved | rung 2 re-adds it |
| node atoms → junk | unknown screen | S4 → rung 3 → `rejoin` line |
| "Zzzz" repeated across 3 tasks | persistent break | rank-down line |
| `version` → v4.0, atoms unchanged (`version_bump`) | version bump, same screens | S5 → rung 0 opens `v4.0/` inheriting `v3.9/`; **negative control: 0 edge failures** |
| `version` → v4.0, every node's atoms replaced, two grid headers renamed (`redesign`) | redesign | S5 → rung 0 → one re-identify line per node → `rejoin`; sync logs `schema_drift` with a 2-entry `column_map` (Appendix G §4.3.4) |
| same as above, `version` unchanged (`redesign_silent`) | redesign without a version bump | S7 → rung 0, then as above |
| grid cell shifted by 3 | moved button | **negative control: 0 drift lines** |
| page 2 · filter applied · `operador2` | data state, not drift | **negative control: 0 drift lines** |

Real-pixel drift with no app change: a transform hook in [E] that downscales the framebuffer 0.8× or translates it +40/+25 px before OCR (coordinates mapped back) proves resolution independence and that nothing uses raw x,y. If the SIGECOM window isn't locked maximized, un-maximizing it is a genuine layout shift. Run the set before 15:30, re-run on the real change, show the delta.

---

## 7. Open questions and build order

### 7.1 Build order inside track 2

1. §4.1 fingerprint + §4.2 schema (one module, pure functions over `elements()` output; the one runnable check is the 10-screen dedup test).
2. §4.3 step 3 task-driven write-back inside the agent loop; §4.3 step 2 pre-warm.
3. §4.4 planner prompt with the compact graph.
4. §4.5 signals + rung 1, then rungs 2–3; `--mutate` flag and the §6.1 table.
5. Epochs and appearances: a new epoch is a directory with a copied `map.json`, an appearance is a list where there was one value; rung 0 and S7; the three redesign mutations in §6.1.
6. Baseline numbers before 15:30; re-run after.

### 7.2 Deferred (`lazy:` notes)

- Background frontier exploration between tasks, only if a spare session exists (§4.3, step 6).
- Pruning, once the map grows past what fits in the prompt (§4.5).
- The techniques skipped on purpose for a one-day build (§3.1, "Deliberately skipped").

---

## 8. Sources

The twelve papers compared in [Appendix D](D-mapping-papers.md); PDFs in `../references/papers/`.
