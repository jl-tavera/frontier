# Specs run book: from `solution.md` to tickets autopilot can build

The design is settled in `resources/docs/solution.md` and its appendixes. These briefs cut it into 9 specs, one package each, 33 tickets, so `/spec` → `/issues` → `/autopilot` can build them unattended and in parallel. Each brief is the "discussion" one `/spec` session synthesizes; nothing here re-decides anything the design doc already decided.

## Why the cut looks like this

- `/spec` allows ≤5 slices and each slice is one ticket, so the solution is several specs.
- `/autopilot` runs one headless `/build <n> auto` per ticket in a worktree cut from `origin/main`, up to 4 at once, **lowest issue number first**, skipping tickets with an open native `blocked_by` link. Publish order is priority.
- Worktrees have **no `.env`** and must never touch the shared live desktop. Every ticket's test seam is offline: saved screenshots, a fake session over element JSON, a fake RFB server, a fake OpenRouter client and a fake `decide`, SQLite in a temp dir. The live "Done when" checks in §5 are a human pass after merge.
- `/ship` rebases; a conflict stops the ticket with `needs-human` and halts new starts. So every spec owns one package, and everything shared (dependencies, lockfile, contracts, fakes, stubs) lands once in ticket A1 and is never edited again.
- `/build auto` stops on any decision it cannot default. Every brief lists its thresholds under **Assumed** so the builder never has to ask.
- **The saved map is the happy path; the tool-use loop is the last resort.** A task is a natural-language CRUD action: the first step is one fast-model call that splits it into typed queries (read / create / update / delete over entities), and a deterministic executor runs them (Spec F). Reads go probe → SQLite: on SIGECOM the probe is the app's own change log (`Herramientas › Bitácora de cambios`), one screen that says whether anything changed; no change → SQL answer. Writes replay the stored procedure for that (op, entity). Every click goes through one primitive, `observe` (Spec W), which replays the node's stored bbox when the static pixels match byte-for-byte, finds a target that only moved by template match, and perceives only on a cold screen, a changed interface or a no-effect action. A changed interface is resolved first by Jev (typed System 1 decisions), then by the VLM; the tool-use loop runs only when a query has no stored procedure, the parse is unsure, or the ladder is exhausted, and it stores what it did as the procedure for next time. Every LLM call goes through OpenRouter, never the Anthropic SDK; Jev through its own key. On SIGECOM the map and cache are built up front by `map --visit` and `seed`; on the unseen app the first task perceives and learns, and every later task replays.

## Ownership (binding for every ticket)

| Spec | Brief | Owns |
|---|---|---|
| A | [A-service.md](A-service.md) | `pyproject.toml`, `uv.lock`, `app/main.py`, `app/runner.py`, `app/log.py`, `app/contracts.py`, `tests/conftest.py`, `tests/fakes/fake_app.py`, `Dockerfile`, `railway.json`, `CLAUDE.md`, `README.md` |
| B | [B-rfb.md](B-rfb.md) | `app/rfb/`, `tests/rfb/`, `tests/fakes/rfb_server.py` |
| C | [C-perception.md](C-perception.md) | `app/perception/`, `tests/perception/`, `tests/fixtures/expected/` |
| D | [D-memory.md](D-memory.md) | `app/memory/`, `tests/memory/`, `tests/fixtures/elements/`, `tests/fixtures/maps/` |
| E | [E-sync.md](E-sync.md) | `app/sync/`, `tests/sync/` |
| W | [W-warm.md](W-warm.md) | `app/warm/`, `tests/warm/`, `memory/` (SIGECOM golden map, ref PNGs, crops, `cache.sqlite`) |
| F | [F-agent.md](F-agent.md) | `app/agent/`, `tests/agent/`, `tests/fakes/llm.py` |
| H | [H-harness.md](H-harness.md) | `harness/`, `tests/harness/`, `tests/fixtures/logs/` |
| S | [S-synth.md](S-synth.md) | `synth/` (generator, `templates.yaml`, the committed `tasks/`, `eval.py`, `web.py`, the committed `reports/`), `tests/synth/`, `tests/fixtures/synth/` |

Rules: a ticket adds files inside its package only; never edits `pyproject.toml`, `uv.lock`, `app/contracts.py`, any `__init__.py`, or another spec's files; a ticket that needs a new dependency stops with `needs-human` instead of editing the lock; tests never open the network or read `.env`. The three stub entry points in A1 (`app/rfb/session.py: open_session`, `app/perception/ocr.py: elements`, `app/agent/loop.py: run_task`) are each overwritten by exactly one ticket (B1, C1, F3).

## 0. Before any spec (human, ~45 min, needs `.env`)

1. **Fixtures.** `poc/out/` is gitignored. Copy `poc/out/before.png` to `tests/fixtures/screens/facturas.png`, then capture ≥9 more. Each run reconnects, acts, waits for settle and saves `poc/out/after.png`:
   ```bash
   uv run poc/rfb_poc.py probe                       # before.png = current screen
   uv run poc/rfb_poc.py click 180 35 && cp poc/out/after.png tests/fixtures/screens/menu-comercial.png
   uv run poc/rfb_poc.py key esc
   ```
   Read coordinates off the previous PNG. Targets: `inicio`, each top menu open (`menu-archivo`, `menu-comercial`, …), `clientes`, `pedidos`, `bitacora`, `facturas-p2`, `facturas-filtered`, `facturas-dropdown` (a select open), `acerca-de`. Add `tests/fixtures/screens/INDEX.md`: one line per file saying what it shows.
2. **Latin OCR model** (optional). Put the PP-OCRv5 Latin recognition ONNX file at `app/perception/models/latin_rec.onnx` (sources in Appendix H §8). C1 uses it only if the file exists.
3. **Task list.** The suite is Spec S's `synth/tasks`: S1 generates ≈34 tasks from templates over the seeded cache (after §3), and step 7 hand-writes the explored ones. Nothing to write by hand here beyond the five official tasks.
4. **Export probe.** Click `Exportar` on Facturas and watch where the output goes (download, new screen, printer dialog) and whether Ctrl+A / Ctrl+C in the grid yields text. Note it in Appendix G §7. It decides whether E gets a 4th ticket.
5. **Change-log probe.** Open `Herramientas › Bitácora de cambios` (that is the `bitacora.png` capture) and note in Appendix G §7: its columns (timestamp, user, entity or module, action, record code?), sort order, pagination, and whether an edit made elsewhere appears as a row (make one harmless edit only if a task in 3 allows it; otherwise write "unverified"). It decides whether E1's change-log probe can name the entity that changed (v2) or only that something changed (v1, the default).
6. Commit 1–5 and this folder on a branch, open a PR, merge (the hook blocks commits on `main`).
7. **Explorer session** (~60 min, any time, needs `.env` and agent-browser). Open the desktop's noVNC page with agent-browser and click through every screen following the recipe and the question list in [S-synth.md](S-synth.md) § Explorer session: it answers Appendix G §7 (so it replaces steps 4 and 5), fixes the field names, formats and `Hoy:` date in `synth/templates.yaml`, spot-checks three generated expectations on screen, and writes ≥8 hand-made tasks into `synth/tasks/explored/`. Commit its outputs on their own branch.
8. **Eval dependency** (before S3 is built, otherwise S3 stops `needs-human` for it). `uv add pydantic-evals` on a branch, commit `pyproject.toml` and `uv.lock`, merge. After S4 merges, add its one-line `app.include_router(...)` to `app/main.py` (S4 ends `needs-human` with the exact line).

## 1. Specs and tickets

One fresh session per spec. In it, type:

```
Read resources/specs/<X>.md and the doc sections it cites; that is the discussion to synthesize. Do not interview me.
/spec
/issues <spec #>
```

then `gh issue edit <spec #> --remove-label ready-for-agent` (the spec issue gets the label too and a bare `/autopilot` would try to build it).

Order, because issue numbers are priority and cross-spec blockers need real numbers:

1. **A** alone. Its A1 number is every other spec's blocker.
2. **C** and **B**, two parallel windows.
3. **D** and **E**, two parallel windows (E after B's tickets exist, for E3 ← B2).
4. **W**, after C, D and E (W1 ← D2, C2, B1 · W2 ← D1, C2 · W3 ← E2).
5. **F**, then **H** and **S** (F1 ← A1 only; F2 ← W2, C4, D1; S1 ← A1 only, S2 ← F1, S3 ← S1, S4 ← S3; H1 ← F3, S3).

Briefs name cross-spec blockers by ticket title; `/issues` resolves them with `gh issue list --search "<title>"`.

Check after spec A: `gh api repos/jl-tavera/frontier/issues/<A2 #>/dependencies/blocked_by` must list A1. `autopilot.py` treats an API error as *unblocked*; if this errors, run `/autopilot` per wave with explicit numbers.

## 2. Build

```
/autopilot <A1 #>                 # alone: the keystone
git pull && uv sync               # once, so the next worktrees hit uv's cache
/autopilot <A2 #>-<H2 #>          # explicit range, never bare
```

Expected first wave after A1: A2, C1, B1; then F1 (it needs only the fake LLM), D1, E1, C2 as slots free. Critical chain: A1 → C1 → C2 → W2 → F2 → F3 → H1, seven deep, ~30 min each (C4, D1 and F1 run beside W2; F4 and F5 beside H1). B, D2–D5, E, W1, W3, H2, S1 fill the other slots (S2 after F1; S3 and S4 after S1, so the public `/evals` page is live before F3 and every merge after moves its number). If the clock is short, build the chain attended with `/build <n>` in a second window while autopilot takes the rest.

On a `STOPPED` line: read the ticket comment, answer or fix, `gh issue edit <n> --remove-label needs-human --add-label ready-for-agent`, rerun `/autopilot` with the remaining range. `git pull` after each wave; the runner never touches your checkout.

Minimum viable subset (one lookup end to end through the executor, §9 critical path): A1, A2, C1, C2, C3, C4, D1, D2, D3, E1, E2, W2, F1, F2, F3, B1; add F4 for the first task on an unseen app.

## 3. Warm the SIGECOM map (human, after W1 and W3 merge, needs `.env`)

```
uv run -m app.warm map --visit --url "$URL" --password "$PASSWORD"   # map + snapshots + crops, then seeds the cache
uv run -m app.warm seed                                              # re-seed alone when only the data changed
```

Then `uv run -m synth gen && uv run -m synth check synth/tasks` regenerates the task suite from the seeded cache (S1). Commit `memory/` (golden map, ref PNGs, crops, `cache.sqlite`) and `synth/tasks/` on a branch and merge. Regenerate before 15:30 and before the demo. If the title bar's version changes at 15:30, the agent opens a new epoch directory beside the committed one at run time (E §4.5 rung 0); commit it after the live pass so the image carries both. The 15:30 drift detection needs this stored map as its baseline, and the mutation suite mutates a copy of it.

## 4. Live pass (human, after F2 merges)

Run the §5 "Done when" checks against SIGECOM with `.env`: 10/10 connects (B), click hit rate (C4/F1), 9 menu screens in the pre-warm (D2), `read_grid` vs screen (C3), harness success % (H1), the same task run twice logging `fastpath: miss` then `hit` on every step (W2), a lookup logging `sync.probe {scope: changelog, outcome: hit}` with exactly 2 LLM calls (F3), and a button nudged by the 15:30 change logging `fastpath: moved` with no OCR (W2). Then `uv run -m synth eval --live --tasks synth/tasks --publish https://<service>` for the per-category table, the triage lines and the public `/evals` page (S3, S4), `uv run -m harness mutate <kind>` per kind before 15:30, deploy from A2's Dockerfile (§3.4 smoke test), re-run after 15:30 (on the real change: one rung 0 line, nodes re-identified, columns aligned), and H2's evidence table into the Challenge 2 spec.
