# Data sync and read cache (track 4)

> Appendix G of [solution.md](../solution.md) · Status: adopted as components [S] and [DB] (solution.md §3.2, §4) · Links checked 2026-10-10.

## 1. Summary

**Scope:** an expansion of [solution.md §5 Track 4](../solution.md) (4.1–4.4).
**Decision:** a one-way pull from the screen into a disposable SQLite read cache. Freshness is checked with a probe, cheapest scope first: the app's own change log when it has one (SIGECOM: `Herramientas › Bitácora de cambios`, one screen for every entity), else the entity's grid. The app always wins, and write tasks never read from the cache.

---

## 2. Problem and constraints

What "sync" means here. There is no API, no change feed and no second database to reconcile with. The only source is pixels coming over RFB ([Appendix B](B-target-recon.md)). In this project, "sync" means:

```
 Remote app (source of truth)  ──pixels / clipboard / export──►  Agent cache (SQLite)  ──►  task answer
          ▲                                                              │
          └───────────── writes happen ONLY through the UI ◄─────────────┘ (cache is never pushed back)
```

- **Direction:** one way. Data only flows from the app into the cache.
- **Who wins:** the app, always. The cache is a read copy that can be thrown away. Deleting the file loses nothing except speed.
- **Why it exists:** read tasks such as lookups, filters and counts have to finish well inside the 5-minute budget. The target is a lookup in under 30 s (4.3). Walking and OCR-ing a grid on every task is too slow and too error-prone.
- **What it is not:** it is not the nav map. Screens, paths and procedures stay in the per-app JSON from [Appendix E §4.2](E-mapping-methodology.md). This page covers **business data** only (Clientes, Facturas, Pedidos, or whatever entities the unseen app has).

---

## 3. Options considered

### 3.1 Unit of sync and read methods

| Decision | Chosen | Discarded, and why |
|---|---|---|
| Unit of sync | Per entity, lazy (on first need) | Sync everything at task start: burns the 5-min budget on tables the task never touches |
| Single-record reads | Targeted search → upsert one row | Full sync then SQL: cold cost is 30–120 s for one row |
| Read methods | Ladder: export → clipboard → OCR | OCR only: slow and lossy. Export only: it may not exist in the unseen app |

### 3.2 Freshness strategy

| Strategy | Freshness | Cost per task | Verdict |
|---|---|---|---|
| Push / CDC / webhooks | Real time | — | **Impossible.** No API, only pixels |
| Re-read the full table every task | Perfect | 30–120 s per entity | Discarded: defeats the purpose of a cache |
| Always read live, no cache | Perfect | High; repeated OCR on multi-step tasks | Kept only as the fallback for write tasks (§4.3.3) |
| **Probe + lazy + expiry + write-through** | Good, with one known gap (§4.3.1) | A few seconds on a hit | **Chosen** |

### 3.3 Data cache store

| Decision | Chosen | Discarded, and why |
|---|---|---|
| Data cache store | **SQLite** (Python stdlib `sqlite3`, WAL mode, one file per deployment) | **JSON files:** no queries for filter tasks, and a crash can leave a half-written file. **DuckDB:** an extra dependency, and analytics is overkill for about 1k rows. **Postgres (Railway):** network hop + ops work for a single writer, and no benefit. **Redis:** no ad-hoc filtering or aggregates, and one more service |
| Schema style | **Generic** rows with a JSON payload | Typed tables per entity (`facturas(numero, fecha, total…)`): impossible, because the grading app is unseen and its columns are unknown until runtime |
| Nav map store | Stays as JSON per app ([Appendix E §4.2](E-mapping-methodology.md)) | Putting it in SQLite: it is small, edited as a whole document, and easier to read in debriefs as JSON |
| Durability | No volume. On SIGECOM a dev-time seed (`memory/cache.sqlite`, §4.2 step 4) is committed and ships in the image, and the probe validates it on first use; on the unseen app the cache starts empty and losing it is accepted | A persistent volume: the cache rebuilds itself, and a stale cache surviving a redeploy unprobed is worse than an empty one |

---

## 4. Chosen design

### 4.1 Happy path

#### 4.1.1 Read task, full entity

```
 Agent Loop            Cache (SQLite)            Sync Engine                 Remote app (RFB)
     │  need(Facturas)      │                         │                              │
     │─────────────────────►│ sync_state = complete?  │                              │
     │                      │── yes ─────────────────►│ probe()                      │
     │                      │                         │ change log registered? once: │
     │                      │                         │── navigate + read page 1 ───►│  (Bitácora)
     │                      │                         │◄─ page-1 hash ───────────────│
     │                      │                         │ == watermark? ── yes: all fresh
     │                      │                         │ (no change log, or changed:) │
     │                      │                         │── navigate + read footer ───►│
     │                      │                         │◄─ count=812, page1 hash ─────│
     │                      │                         │ matches sync_state? ── yes   │
     │◄──── SQL result ─────│◄────── fresh ───────────│                              │
     │                      │                         │                              │
     │        (miss / stale / probe mismatch)          │                              │
     │                      │── no ──────────────────►│ acquire() via ladder:        │
     │                      │                         │  1. Exportar (4.1) ─────────►│
     │                      │                         │  2. clipboard (4.4) ────────►│
     │                      │                         │  3. OCR paging (4.2) ───────►│
     │                      │                         │ normalise → staging table    │
     │                      │                         │ re-probe: count unchanged?   │
     │                      │◄── atomic swap ─────────│ BEGIN; DELETE; INSERT; COMMIT│
     │◄──── SQL result ─────│                         │                              │
```

The steps:
1. The agent asks for an entity, not for a screen. The sync engine keeps navigation and reading out of the LLM's context.
2. **Cache hit + probe matches:** answer from SQL. Cost: one navigation to the change log per task (or one per entity when the app has no change log) plus one first-page read, a few seconds.
3. **Miss or mismatch:** acquire the data through the ladder, cheapest and most reliable method first. Each step either returns complete rows or hands off to the next.
   - **Export (4.1):** the whole table in one action. Lossless if the file or screen it produces can be read.
   - **Clipboard (4.4):** select-all + copy → `ServerCutText`. Lossless text, usually tab-separated.
   - **OCR paging (4.2):** read a page, press `Siguiente`, repeat. Always available, but it is the slowest and least accurate.
4. **Normalise:** match columns by **header text**, never by position. Parse types (dates, money, ints). Compute the natural key and `row_hash`.
5. Write everything to a **staging** table. Only a complete read is swapped in, in one transaction. Readers never see half a table.
6. Record `sync_state` (count, probe hash, header hash, method, time). Log every step to the JSONL log [H].

#### 4.1.2 Read task, one record (targeted path)

When the task names a single record ("total of factura F-0042"), do **not** sync the whole table. Use the app's own search or filter field instead, read the one row, and upsert it into the cache with `source = targeted`. This takes seconds instead of minutes and usually beats a cold full sync.

### 4.2 Keeping it in sync

Nothing pushes changes to us. Freshness has to be **detected** by looking at the screen. In order of use:

1. **Our own writes → write-through read-back.** After the agent saves a record through the UI, it reads that record back off the screen and upserts just that row. This upgrades the original "invalidate after any write" (4.3) because it keeps the rest of the table warm. Then re-read change-log page 1 so the watermark includes our own entry; that entry is also the proof of the write for the summary. If the read-back fails, fall back to marking the whole entity `stale`.
2. **Probe before trusting the cache.** A probe is the cheapest signal that "something changed", cheapest scope first:
   - **The app's change log**, when it has one (SIGECOM: `Herramientas › Bitácora de cambios`). It is registered as an entity with `role = 'changelog'` and probed once per task: its page-1 hash equals the stored watermark → every entity is fresh, no per-entity navigation. It differs → every entity is marked `stale`, re-acquired lazily only when a query needs it, and the watermark advances. v1 marks everything; naming the touched entity from the row waits until the screen's columns are known (§7). An app with no change log skips this scope.
   - **The entity's own grid**: the **total count** (footer, "Mostrando 1-20 de 812", or the page count × page size) and a **hash of page 1**, sorted newest first if the grid can sort. Together these catch inserts, deletes and edits to recent records. A probe costs one navigation plus one OCR region.
3. **Expiry time as a backstop.** Even if the probe matches, a snapshot older than N minutes (start with 10 and tune it) is re-acquired the next time it's needed. This bounds the blind spot described in §4.3.1.
4. **Dev-time seed (SIGECOM only).** After `map --visit` ([Appendix E §4.3](E-mapping-methodology.md) step 6), `seed` finds every mapped node whose snapshot has a grid, registers it as an entity (keyed by the node id, header hash from its columns) and acquires it through the §4.4 ladder into `memory/cache.sqlite`; the node whose title matches `bitácora|cambios|log|historial|auditor` is registered with `role = 'changelog'` (a fast-model tie-break when several or none match). The file is committed, so a lookup right after deploy hits the cache; a stale seed costs one re-acquire, never a wrong answer, because the probe runs first. Never seed inside a task, and never on the unseen app: there, entities are acquired lazily the first time a query needs them, and the in-task pre-warm stays menus only.

### 4.3 What if something changes before or during a sync?

Who can change data behind our back:
- **another operator** on the same desktop: `shared=1`, `operador` and `operador2` (1.5)
- **the evaluator** setting up test data between tasks
- **the 15:30 change**: this one changes the **UI or structure**, not just the data

#### 4.3.1 External edit after our snapshot

| Change | Caught by | Result |
|---|---|---|
| Row inserted or deleted | Probe count | Re-acquire |
| Recent row edited | Probe page-1 hash (newest first) | Re-acquire |
| **Old row edited, count unchanged** | **Not caught by the probe** | Served stale until the expiry time or a targeted read |

The last row is the **known staleness window**, and we accept it. When the app has a change log that records edits, the change-log probe closes it: an old-row edit is a new log entry. Mitigations when it has none:
- the expiry time puts an upper bound on it
- any answer that depends on one specific record goes through the targeted path (§4.1.2), which always reads live
- the task summary states when an answer came from the cache and how old that cache was

#### 4.3.2 Edit while we are paging

Paging is not a snapshot. An insert shifts rows down, which makes a row appear twice. A delete shifts rows up, which makes one get skipped.

- **Remove duplicates** by natural key while staging.
- **Probe at the start and at the end.** If the count or page-1 hash changed during the read, discard the staging table and retry **once**.
- If it changes a second time, the table is "hot". Don't swap it in. Mark the entity `stale` and answer through the targeted path or live reading.
- Export and clipboard are near-atomic (one action), so this risk exists almost entirely on the OCR-paging step. That is another reason the ladder puts them first.

#### 4.3.3 Write tasks never trust the cache

Before the agent edits or creates anything:
1. **Read before write:** open the actual record on screen.
2. **Check expectations:** if the task implies a current state ("change the status of the pending order X"), confirm that state on screen. This is optimistic concurrency done by hand. The screen is the version check.
3. If it doesn't match, **don't overwrite**. Report the conflict in the summary ("expected pending, found shipped by another user") and end as `fallida` or partial. Never guess.
4. Save → **read back** → verify the new values are on screen → write-through to the cache (§4.2, step 1).

Two agents editing the same record at the same time is ruled out by the assumption "one task at a time per desktop" ([solution.md §8](../solution.md)). A human `operador2` is not ruled out, and steps 2 and 4 are what protect us from them.

#### 4.3.4 Schema or UI drift (the 15:30 change)

- Each entity stores a **header hash** (its sorted column labels). If a column is renamed, added or removed, the hash changes. When it does, **re-acquire the entity's rows** (they are disposable, so re-acquire is the migration) and then **align the old headers to the new ones**, cheapest rung first:
  1. normalised exact match (case, accents, whitespace, punctuation);
  2. `difflib.SequenceMatcher` ratio ≥ 0.8 (stdlib);
  3. value match: join old rows to new rows on the natural key, when the key column aligned in 1–2, and pair the columns whose parsed values agree on ≥ 90 % of the shared keys;
  4. leftovers: one LLM call with the old headers, the new headers and 3 sample rows, "no counterpart" allowed.
- The result is `sync_state.column_map`, `{"old header": "new header"}`, chained across epochs so the oldest name stays usable. `data_json` is always keyed by the **live** header; a query written against an older name is translated through the map. This is what keeps learned procedures and the planner's "Valor is the amount" valid across a rename. Headers with no counterpart are left out of the map and logged (`sync.schema_drift {old, new, aligned, unaligned}`). If the alignment is inconclusive, the behaviour is the old one: an empty entity, no map.
- Columns are mapped by header text, so a column that only **moves** doesn't break anything.
- The entity key is the nav map's **node id** for the grid screen, not the screen title; the title is one of that node's appearances ([Appendix E §4.2](E-mapping-methodology.md)). A renamed screen is still the same entity. The sync engine stores the id it is given and never reads the map itself.
- If a screen or grid can't be found, that's the nav map's job: drift detection (2.6) and the repair ladder in [Appendix E §4.5](E-mapping-methodology.md). The sync engine marks the entity `stale` and waits for navigation to recover.

#### 4.3.5 Conflict policy, in one line

**The app always wins.** We do no merging and no last-write-wins on our side, and the cache never overwrites the app.

### 4.4 Error handling

| Failure | How we detect it | Response |
|---|---|---|
| OCR misreads a cell | Type parse fails (date, money, int), a totals or count check fails, or OCR disagrees with the clipboard | Re-OCR that region with a tighter crop; if that still fails, store `null` + flag the row, and never invent values |
| Export goes nowhere readable (download we can't reach, PDF) | Nothing appears on screen or clipboard within the settle time | Mark `export=unusable` for this app in memory and drop to the clipboard step |
| Clipboard returns nothing or garbage | Empty `ServerCutText`, or no tab/newline structure | Drop to OCR paging and remember that clipboard doesn't work for this grid |
| Paging gets stuck in a loop | The page fingerprint was already seen, or `Siguiente` has no effect (action verification, design 3.3) | Stop and treat what we have as the end; check it against the probe count |
| Empty grid vs failed load | Zero rows **and** no "no results" text or footer | Retry the navigation once; if still unclear, mark `stale`, not `complete` with 0 rows |
| WebSocket drop mid-sync | RFB exception (1.2) | Reconnect, navigate back, resume from page N (stored in staging); after 2 failures, give up and mark `partial` |
| Partial read (time ran out or errors) | Staging count < probe count | **Never swapped in.** The old snapshot stays and the entity is marked `partial`, so answers say so |
| Time budget | Sync running longer than about 60 s inside one task | Stop syncing and use the targeted path; the 4:30 guard (design 3.5) still writes a summary |
| Destructive control near a grid (Eliminar, Anular, Integraciones) | Denylist | The sync engine never clicks it; read-only actions only |
| Header hash changed (a column renamed, added or removed) | `sync_state.header_hash` differs from the live header row | Re-acquire, then the §4.3.4 alignment ladder → `column_map`; inconclusive → empty entity, no map; log `sync.schema_drift` |
| Cache file lost (Railway redeploy, corruption) | Missing file or `PRAGMA integrity_check` fails | Delete it and start cold; correctness is unaffected |

Every row above writes a JSONL event (`sync.probe`, `sync.acquire`, `sync.fallback`, `sync.conflict`, …) with the entity, method, counts and duration. These events feed the Challenge 2 spec and debrief.

### 4.5 Database schema

```sql
CREATE TABLE rows (
  app_id      TEXT NOT NULL,          -- app identity (title bar), same key as the nav map
  entity      TEXT NOT NULL,          -- nav-map node id of the grid screen; its title is an appearance (E §4.2)
  natural_key TEXT NOT NULL,          -- id column if found, else hash of identifying columns
  data_json   TEXT NOT NULL,          -- {"Numero": "F-0042", "Total": 1520.00, ...}, keyed by header text
  row_hash    TEXT NOT NULL,          -- detects row-level change on re-acquire
  acquired_at TEXT NOT NULL,
  source      TEXT NOT NULL,          -- export | clipboard | ocr | targeted | writeback
  PRIMARY KEY (app_id, entity, natural_key)
);

CREATE TABLE sync_state (
  app_id      TEXT NOT NULL,
  entity      TEXT NOT NULL,
  header_hash TEXT NOT NULL,          -- §4.3.4 schema drift
  column_map  TEXT,                   -- §4.3.4 {"old header": "new header"}, chained across epochs
  role        TEXT NOT NULL DEFAULT 'entity',  -- §4.2: 'entity' | 'changelog' (the app-wide probe)
  row_count   INTEGER,                -- §4.2 probe
  probe_hash  TEXT,                   -- §4.2 probe (page 1)
  status      TEXT NOT NULL CHECK (status IN ('complete','partial','stale')),
  method      TEXT,                   -- which rung of the ladder worked
  acquired_at TEXT NOT NULL,
  PRIMARY KEY (app_id, entity)
);
```

Queries use `json_extract(data_json, '$.Total')`, which is built into SQLite, so filter and sum tasks become SQL instead of LLM arithmetic. The swap works like this: rows are written into `rows_staging`, then `BEGIN; DELETE FROM rows WHERE app_id=? AND entity=?; INSERT … SELECT FROM rows_staging; UPDATE sync_state …; COMMIT;`

---

## 5. Trade-offs

| We chose | Over | We pay | We get |
|---|---|---|---|
| A cache + probe | Always reading live | A small staleness window (§4.3.1) | Lookups under 30 s; repeated reads cost almost nothing |
| The change log as the first probe | Per-entity probes only | Trusts the app's own log; an unlogged edit waits for the expiry backstop | One navigation per task instead of one per entity; edits to old rows are caught |
| Lazy per-entity sync | Pre-loading everything | The first read of each entity is slow | No budget spent on tables the task doesn't touch |
| Targeted reads for single records | One sync path for everything | Two code paths | A one-record answer in seconds, and it is always live |
| A generic JSON-row schema | Typed tables | Weaker typing; `json_extract` in queries | Works on an app we have never seen |
| Align columns on a header change | Drop and forget | One LLM call on the headers the cheap rungs miss | Procedures and queries survive a rename; the planner keeps knowing which column is the amount |
| App-always-wins, read-before-write | Merge or last-write-wins logic | Some write tasks fail with a reported conflict | Never corrupts data another user changed |
| An ephemeral SQLite file | A managed database | A cold start after a redeploy | Zero ops, stdlib only, no stale data surviving a deploy |

---

## 6. Evidence and measurement

Nothing measured yet. Probe cost and the ladder's success rate are measured in the eval harness (3.6, [solution.md §7](../solution.md)) before and after 15:30.

---

## 7. Open questions

- **4.3 / run book step 0.5:** what `Bitácora de cambios` lists (timestamp, user, entity or module, action, record code), its sort order and pagination, and whether every data edit appears as a row. v1 of the probe needs only its page 1 to change; naming the touched entity (v2) needs an entity column.
- **4.1:** where `Exportar` output goes (a download, a new screen, a printer dialog), and whether we can read it over RFB.
- **4.4:** whether select-all + copy works on grids or only on text fields, and what format it produces.
- Whether grids show a total count. If they don't, the probe falls back to page count × page size, or to the page-1 hash alone.
- Whether each entity has a visible unique id column. If not, the natural key is a hash of the identifying columns, and duplicate removal gets weaker.
- Whether grids can sort newest first. Without it, the page-1 hash misses recent edits, so the expiry time should be shorter.
- Probe cost on the unseen app. Measure it in the eval harness (3.6) before and after 15:30.
- Whether the natural-key column survives the 15:30 change. If it doesn't, the value-match rung of §4.3.4 is off, the leftovers go to the LLM rung, and the entity simply restarts.

---

## 8. Sources

[Appendix B](B-target-recon.md) for the transport facts, [Appendix E](E-mapping-methodology.md) for the nav map this cache sits beside, and [solution.md §5 Track 4](../solution.md) for units 4.1–4.4.
