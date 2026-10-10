# Spec E · Data sync and read cache

Design: `resources/docs/solution.md` §3.1 [S]/[DB], §3.2 rows [S]/[DB], §4 Data reads row, §5 Track 4; Appendix G §4.1–4.5 (probe, ladder, conflicts, column alignment, errors, schema), §7. Run book: [README.md](README.md).

## Problem

Lookup and aggregate tasks must answer in seconds, but the only source is a paginated grid of pixels. Reads go through a disposable SQLite cache behind a freshness probe (the app's own change log when it has one, so one screen answers for every entity; else the entity's grid), acquired by the cheapest working rung of export → clipboard → OCR paging, and the app always wins.

## Owns

`app/sync/`, `tests/sync/`. Acquirers take injected callables (`read_grid`, `click_text`, clipboard) so nothing here imports C or F.

## Slices

**E1 · SQLite cache with probe and atomic swap** (4.3; G §4.2, §4.3, §4.5)

As the agent, `need(entity)` returns `hit` with rows when the probe (row count + page-1 hash) matches `sync_state`, else `miss`/`stale`; `acquire()` writes to `rows_staging` and swaps in one transaction; a staging count below the probe count is never swapped (`partial`); a changed header hash re-acquires the entity and aligns old → new headers through the G §4.3.4 ladder (normalised exact → `difflib` ≥0.8 → value agreement ≥90 % on shared natural keys → an injected LLM callable for the leftovers) into `sync_state.column_map`; an expiry backstop marks stale; `sync_state.role` is `'entity'` or `'changelog'`, and when a `changelog` entity is registered `need()` probes it first, once per task: page 1 unchanged → every entity of that app is fresh with no per-entity probe; changed → every entity is marked `stale` (re-acquired lazily, only when asked for) and the change-log watermark (its page-1 hash) advances; no `changelog` registered → the per-entity probe; `advance_watermark()` re-probes the change log after a write-through; every probe emits `sync.probe {scope: changelog|entity, outcome: hit|miss}`; `query(sql)` works over `json_extract(data_json, '$.Col')` and translates a column name that only exists in `column_map`. Schema exactly G §4.5 (`rows`, `sync_state` with `column_map`), WAL, one file at `memory/cache.sqlite` by default (the file **W3 · Cache seed from the map** fills and commits for SIGECOM) or a given path. Seam: `sqlite3` in `tmp_path` with an injected fake acquirer; done when 20 rows give the right `SUM(json_extract(...'$.Valor'))`, a registered change-log entity whose page-1 hash matches gives `hit` for another entity with no per-entity probe call, a changed change-log hash marks two entities `stale` and re-acquires only the one asked for, a probe mismatch gives `stale`, a short read keeps the old rows and sets `partial`, renaming 2 of 6 headers in the fake acquirer gives a 2-entry `column_map` and the same `SUM` on `'$.Valor'` still answers through the new header, a header with no counterpart is absent from the map and emits `sync.schema_drift`, and an inconclusive alignment leaves an empty entity with no map. Blocked by A1.

**E2 · OCR paging acquirer** (4.2; G §4.4)

As the agent, `acquire_by_paging(entity, read_grid, click_next, probe)` reads page 1, clicks `Siguiente` until the page fingerprint repeats or the click has no effect, normalises rows by header text, parses dates/money/ints (`1.810.000` → 1810000), derives the natural key (id column if any, else a hash of identifying columns), dedupes, re-probes before the swap, and stores `null` + a flag for unparseable cells. Emits `sync.probe`, `sync.acquire`, `sync.fallback` events. Seam: three fixture pages as `Grid` objects where `Siguiente` has no effect on the last; done when all rows come back once, values are typed, and the loop terminates. Blocked by E1.

**E3 · Clipboard acquirer with fallback** (4.4; G §4.4)

As the agent, `acquire_by_clipboard(entity, select_all_copy, wait_clipboard)` parses tab/newline text into rows keyed by the header line and drops to OCR paging when the clipboard is empty or unstructured, remembering `clipboard=unusable` for that grid. Seam: injected clipboard text, then empty; done when TSV gives rows and empty falls back. Blocked by E1, and by **B2 · Clipboard both ways** (for the real `send_clipboard`/`wait_clipboard`).

**E4 (conditional) · Export acquirer** (4.1)

Written only after the human export probe (run book step 0.4) says where `Exportar` output goes and that it is readable over RFB. Marks `export=unusable` for the app when nothing appears within the settle time.

## Decisions already made

Read priority on a task: change-log probe → cache (E1) → clipboard (E3) → OCR paging (E2), perception last; cache + probe over always-live reads; lazy per-entity sync inside a task; generic JSON rows, `json_extract`; staging → one-transaction swap; app always wins, no merging; ephemeral file, no volume (§3.4); write-through read-back after our own writes (G §4.2 step 1, §4.3.3).

## Assumed

- Expiry 10 min; sync abandoned after 60 s inside a task (G §4.4); page size from page 1.
- Change-log probe v1: any change on its page 1 marks every entity stale; naming the touched entity from the row (v2) waits for the human spike in run book step 0.5.
- Money parsed as Colombian format (dot thousands, comma decimals); dates `dd/mm/yyyy` → ISO.
- Column alignment: `difflib` ratio 0.8, value agreement 90 %; the LLM leftover rung is an injected callable (F wires `MODEL_FAST`); `entity` is an opaque string (F and W3 pass the nav-map node id, G §4.3.4).

## Not building

Postgres/JSONB (trigger: more than one instance or cache must survive redeploys); pre-loading entities inside a task (never, by design; the dev-time seed on SIGECOM is **W3 · Cache seed from the map**); CDC/push (impossible: pixels only).

## Live checks (human)

The Bitácora probe hits twice in a row, then misses after an edit (G §4.2); read all Facturas into JSON and spot-check against the screen (4.2); a lookup task under 30 s (4.3); whether select-all + copy works on a grid (4.4); where `Exportar` goes (4.1).
