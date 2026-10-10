# Spec W · Warm start and replay

Design: `resources/docs/solution.md` §3.3 (per-task flow), §4 rows Node identity / Edge target / Initial mapping; Appendix E §3.1 ideas 3, 6 and 9, §4.2 (appearance fields `ref_png`, `elements_snapshot`; epoch directories), §4.3, §6.1 (golden map); Appendix G §4.2 (probe); Appendix H §4 (lossless frames: the same label always renders to the same bytes). Run book: [README.md](README.md).

Decision taken in this spec series: **replay from the saved map is the happy path on every step; perception is the fallback.** A static region that only moved is found by template match of its stored crop before any OCR. Perception runs only on a cold screen, a static-region mismatch that template matching cannot explain (drift, overlay, dialog), a target missing from the snapshot, or no effect after an action. Data reads follow the same order: change-log probe → cache → clipboard → OCR paging (Appendix G §4.2).

## Problem

On an app we have mapped, running OCR on every step costs about a second a step and adds noise, while the map already knows where every element was. The evaluation app is unseen, so its first task must perceive, but every later task should replay. And the data cache starts empty unless something fills it before the first task.

## Owns

`app/warm/` (`observe`, `replay_target`, the `map` and `seed` commands), `tests/warm/`, and the committed SIGECOM artifacts in `memory/`: golden map JSON, ref PNGs, static-region crops, `cache.sqlite`. Uses D's `AppMap`, fingerprint and pre-warm, C's `elements`, E's acquirers through their public functions; never edits those packages.

## Slices

**W1 · Initial mapping run**

As the team, `uv run -m app.warm map --url … --password … [--visit] [--budget S]` connects, identifies the app, runs D2's pre-warm, and with `--visit` also clicks every non-denylisted menu item, settles, perceives, fingerprints, saves the node's appearance for this version with `elements_snapshot` (all elements with bboxes), `ref_png`, the static-region crops and the confirmed edge, then returns via Esc, else the recorded back edge; writes `memory/<app_id>/<version>/map.json` with the PNGs and crops beside it. It is D2's function with a flag, not a second walker. Seam: `FakeSession` with a scripted 9-item menu tree; done when the map has 9 visited nodes each with a snapshot and crops, denylisted items are never clicked, and the budget stops the walk. Blocked by **D2 · Pre-warm and task-driven write-back**, **C2 · Widget boxes, kinds, UI tree and label↔field pairing**, **B1 · Session from the request payload, with a fake RFB server for tests**.

**W2 · `observe`: replay or perceive**

As the agent, `observe(fb, map) -> Observation(node, elements, source)` compares the static-region crops of the current node's newest appearance byte-for-byte with `fb`; on a match it returns the stored `elements_snapshot` with `source="snapshot"` and runs no OCR. When some crops mismatch it first searches each mismatching crop (cut from the appearance's `ref_png` at the stored bbox) over the whole frame with `cv2.matchTemplate`; if every one is found exactly once at a score ≥ 0.95 it returns the snapshot with those bboxes moved, `source="snapshot"`, logs `fastpath: moved` and appends a new appearance for each moved target; otherwise it calls C's `elements()`, D1's fingerprint, returns `source="perception"` and refreshes the snapshot for write-back. The title-band crop is the app-title element only, never the whole band, so the clock and user label (`Hoy: … · Usuario: operador2`) change without a miss. `replay_target(target, observation) -> bbox` grounds a semantic target against the observation's elements. Every step logs `fastpath: hit`, `fastpath: moved` or `fastpath: miss:<reason>` (`cold`, `static_mismatch`, `target_missing`, `no_effect`). Seam: a fixture PNG and its own snapshot; done when the same PNG gives `source="snapshot"`, `rec_calls == 0` and the stored bbox, a copy with the user label and date repainted still gives `source="snapshot"`, a copy with one button shifted 30 px gives `source="snapshot"`, the shifted bbox, `rec_calls == 0` and a `fastpath: moved` line, a copy with one static label repainted gives `source="perception"`, and a dropdown-open fixture gives a miss that D1 reports as an overlay. Blocked by **D1 · Screen fingerprint and map file**, **C2 · Widget boxes, kinds, UI tree and label↔field pairing**.

**W3 · Cache seed from the map**

As the team, `uv run -m app.warm seed [--entities …]` finds every node whose snapshot has a grid, registers the entity (keyed by the node id, display name from the screen title, header hash from the columns) and acquires it through E's ladder into `memory/cache.sqlite`; the node whose title matches `bitácora|cambios|log|historial|auditor` is registered with `role='changelog'` (an injected tie-break callable decides when several or none match; F wires `MODEL_FAST`), so its page-1 probe is the app-wide probe (Appendix G §4.2, E1); `map --visit` calls it at the end. On a task, `need(entity)` finds the seeded rows and the probe decides freshness, so a stale seed costs one re-acquire, never a wrong answer. Seam: `FakeSession` with a 2-page Facturas grid and SQLite in `tmp_path`; done when `sync_state` shows the entity `complete` with the right count, the Bitácora node is registered with `role='changelog'`, and a changed header hash on the next seed re-acquires it and fills `column_map` (G §4.3.4). Blocked by W1, **E2 · OCR paging acquirer**.

## Decisions already made

- Edges never store x,y (E §3.1 idea 3, solution §4 "Edge target"). Coordinates live only in node snapshots and are used only after the pixel gate passed.
- The gate is byte equality of the static regions, a sufficient condition for "same node, nothing moved". A mismatching crop is searched by template match before anything else: lossless frames make the match exact, so ≥ 0.95 found exactly once means "moved, not changed"; the crop is cut from `ref_png` at the stored bbox at run time, no per-element files. A pixel hash is still rejected for node identity (§4: breaks on data change); a miss falls back to the OCR fingerprint.
- Static regions: the title band plus every stored menu, button, field-label and header bbox padded 2 px. Grid bodies and values are excluded, so a filter, a page change or a selected row still replays.
- Write-back refreshes snapshots and crops on every task (D2), so the unseen app replays from its second task. A new epoch (E §4.5 rung 0) replays from its second task too: each inherited node misses once, perception adds the new appearance, and the old one stays in the old epoch's directory.
- The seed is validated by the probe on use (G §4.2).

## Assumed

- `--visit` budget default 10 min at dev time; the eval-time pre-warm stays menus only, ≤45 s.
- Return path after a visit: Esc, else the recorded back edge, else `navigate_to` the first node.
- `memory/` is committed and the Dockerfile copies the repo, so the image carries the SIGECOM map and cache; regenerate before 15:30 and before the demo.
- Ref PNGs and crops are stored as files next to that epoch's `map.json`, named by node id; an appearance's `version` says which epoch directory holds its files.

## Not building

Scale-tolerant matching (trigger: a resolution change or a lossy encoding enters the pipeline; template match is exact-scale); background re-mapping between tasks (E §4.3 step 6; trigger: a spare session); seeding on the unseen app inside a task (never, G trade-offs).

## Live checks (human)

`map --visit` on SIGECOM gives ≥10 nodes with crops; the same task run twice logs `miss` then `hit` on every step with `rec_calls == 0`; `seed` fills Facturas, Clientes and Pedidos; a lookup task answers under 30 s right after deploy; `--mutate rename` shows one miss, the ladder, then `hit` again on the patched edge; a button nudged by the 15:30 change logs `fastpath: moved` with no OCR.
