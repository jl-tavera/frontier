# Spec D · App memory: fingerprint, map, pre-warm, drift ladder

Design: `resources/docs/solution.md` §3.2 row [F], §4 rows Knowledge/Node identity/Edge target/Initial mapping/Change handling, §5 Track 2, §6; Appendix E §2.1 (interfaces, epochs), §4.1–4.6 (appearances, epochs, rung 0 / S7 included), §6.1 (mutation table), §7.1 (build order). Run book: [README.md](README.md).

## Problem

The evaluation app is unseen and changes at 15:30. The agent must learn each app's screens and paths at run time, recognise where it is without pixels or coordinates, and repair a broken edge inside the task.

## Owns

`app/memory/`, `tests/memory/`, `tests/fixtures/elements/` (synthetic element JSON, hand-written from the Appendix B menu tree), `tests/fixtures/maps/`. Pure functions over `list[Element]` from `app/contracts.py`; no dependency on spec C, so D builds in parallel with it.

## Slices

**D1 · Screen fingerprint and map file** (2.3, 2.4; E §4.1, §4.2)

As the agent, I know which screen I am on: `fingerprint(elements, w, h)` keeps static kinds only, bins labels to a 12×8 grid on normalised coordinates, uses the title band as a hard key and Jaccard over atoms, taken as the max over a node's `appearances` (≥0.90 same, 0.60–0.90 ambiguous, <0.60 new); overlays (<25 % changed, parent labels visible) are sub-states; a small centred dialog with ≤3 buttons is a blocker, never drift; `app_id`/`version` split from the title. `AppMap` loads and saves `memory/<app_id>/<version>/map.json` with the E §4.2 schema (node with `appearances [{version, atoms, ref_png, elements_snapshot}]`, edge with `target.appearances [{version, label, role, cell, xy}]` (`xy` = last click point that worked, a cache Spec W tries first and rewrites on a miss), `inherited`, `outcomes`, `ok/fail`; procedure; unexplored; denylist); `load(title)` opens the epoch directory named by the title's version, `inherit(prev)` opens a new one whose `map.json` copies the previous epoch with nodes `stale` and edges `inherited` (appearances keep their `version`, so their files still resolve into the old directory), and a title that matches no stored app adopts, as a new epoch, the app whose root-node menu atoms give Jaccard ≥0.5 against the first screen (E §4.3 step 1). Every appearance stores `elements_snapshot` (all elements with bboxes at last sight), `ref_png` and the static-region crops (title band plus menu, button, field-label and header bboxes padded 2 px) that Spec W compares byte-for-byte to replay without perception, as files in that version's directory; the replay primitive itself is **W2 · `observe`: replay or perceive**. Seam: ~10 synthetic element lists; done when the same screen scaled to 1024×640 gives one id, 10 distinct screens give 10 ids, a dropdown-open variant gives the same node plus `overlay`, a node with two appearances matches either, `inherit()` then `load()` of the old version gives the old map untouched, a rebranded title with the same menus adopts the old app as a new epoch, and the JSON round-trips. Blocked by A1.

**D2 · Pre-warm and task-driven write-back** (2.2; E §4.3)

As the agent, on the first task on an epoch (a new app, or a new version right after rung 0) I open each top menu (click → settle → elements → Esc), ≤45 s, menus only, never a denylisted label, recording `menu → item` edges with `to = unknown`; during a task every verified action upserts an edge only once its landing fingerprint is confirmed; write-back at task end persists nodes (with refreshed `elements_snapshot` and static crops on the current version's appearance), edges and the procedure, with node descriptions in one batched call through an injected callable. The same function with a `visit` flag is W1's dev-time full mapping run. Seam: `FakeSession` with menu overlays and an injected clock; done when the map has 9 `menu → item` edges, Integraciones is never clicked, and the pre-warm stops at the budget. Blocked by D1.

**D3 · Planner view and routes** (2.4; E §4.4 input)

As the planner, `compact(map)` renders node titles + descriptions and edges as `Inicio —[click "Cartera › Facturas"]→ Facturas` plus procedures similar to the task text, with `inherited` edges marked `(inherited)` as hints, and `route(map, from, to)` returns the edge list ranked by `ok/(ok+fail)` × recency with inherited edges below every verified one. Seam: a saved map fixture with one inherited edge; done when the text matches a golden and the route from Inicio to Facturas is the stored edges. Blocked by D1.

**D4 · Drift signals, rung 1, rank-down, mutations** (2.6; E §4.5, §6.1)

As the agent, after every step the checks run in order blocker → overlay → data edge → drift, signals S1–S7 fire as specified (S7: under 40 % of the map's menu atoms on screen at task start, or 3 consecutive S4), rung 1 re-grounds in place (fuzzy label → same role + cell → an injected typed-choice callable `decide` over the element list with the old action as few-shot, acted on only at confidence ≥ 0.8 → an injected VLM callable) and appends the new look to `target.appearances`, never overwriting the old one, rung 4 always `fail++`; every rung logs `{signal, rung, via, confidence, before, after, cost_ms}`. `mutate(map, kind)` implements the E §6.1 table, `version_bump`, `redesign` and `redesign_silent` included. Seam: `tests/fixtures/maps/golden_map.json` + `FakeSession`; done when `rename` (Facturas → Facturación) gives S1 → rung 1 and leaves the edge with two target appearances, a rename to an unrelated label resolves through `decide` with `via: "decide"` when it answers at 0.9 and through the VLM callable when it answers at 0.5, `landing_mismatch` gives S3 → rung 1 retarget, `persistent` gives a rank-down line after 3 tasks, and the two negative controls (`shifted_cell`, `data_state`) give 0 drift lines. Blocked by D2.

**D5 · Rungs 2–3 and rejoin** (2.6; E §4.5)

As the agent, rung 0 (S5/S7 only) opens the new epoch with `inherit()` (nodes `stale`, edges `inherited`) and re-runs the D2 pre-warm (≤10 s + pre-warm); in a new epoch an unmatched screen is re-identified against ≤5 inherited stale nodes with the ambiguous band widened to 0.30–0.90 through the injected VLM callable (`ref_png` + `description`, "none" allowed) before a new node is created; rung 2 marks the node stale and runs the pre-warm function on that node only (≤30 s), rung 3 marks the edge broken and asks an injected replan callable once (≤15 s), and the moment a known node is fingerprinted the loop logs `rejoin`; entry rung follows the signal (S5/S7 → 0, then S1 → 1 → 2 → 3; S1 → 1 → 2 → 3; S3/S4 → Esc → 3). Seam: same fixtures; done when `removed` reaches rung 2 and finds the real item, `menu_moved` is re-added by rung 2, `unknown_screen` gives S4 → rung 3 → `rejoin`, `version_bump` gives a `{signal: S5, rung: 0}` line, a new `v4.0/map.json` beside the untouched `v3.9/` and 0 edge failures, `redesign` gives S5 → rung 0 → a re-identified Facturas node with a second appearance → `rejoin`, and `redesign_silent` gives the same through S7. Blocked by D4, D3.

## Decisions already made

Learned per-app map, never a hand map (§4); semantic targets with the last-good `xy` as a cache, rewritten by perception on a miss; one `map.json` per app epoch, no database; cold + incremental with one ≤45 s pre-warm (2.5 decided); rank down, never delete.

## Assumed

- Thresholds exactly as E §4.1/§4.5: 0.90/0.60 Jaccard, 12×8 grid, overlay <25 %, pre-warm 45 s, frontier episode 40 s, rung budgets 5/30/15 s.
- Denylist: `Integraciones, Eliminar, Anular, Borrar, Guardar*, Enviar, Configuración`.
- The typed-choice `decide`, the VLM tie-break and the replan are injected callables here; F wires Jev and the OpenRouter models.
- Epochs and appearances exactly as E §4.1–4.5: mass-drift threshold 40 % of menu atoms or 3 consecutive S4; re-identify band 0.30–0.90, ≤5 candidates; rung 0 budget 10 s + one pre-warm; epoch directory named by the version string, else `epoch-<n>`.

## Not building

Pruning (trigger: map no longer fits the prompt); background frontier exploration (trigger: a spare session); macro mining, embeddings, Neo4j (E §3.1 skipped list).

## Live checks (human)

9 menu screens recorded in the pre-warm on SIGECOM; a second task on the same app finishes faster; the framebuffer transform hook (0.8×, +40/+25 px) produces 0 drift lines; on the real 15:30 change, one rung 0 line and the number of nodes re-identified.
