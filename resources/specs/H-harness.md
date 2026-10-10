# Spec H · Eval harness and evidence

Design: `resources/docs/solution.md` §5 unit 3.6, §6 ("Proving it before 15:30"), §7 (measurement plan), Track 6; Appendix E §6; Appendix A §7 (rubric: Specification criterion). Run book: [README.md](README.md).

## Problem

One command must print the success % and the per-task metrics the design promised, before and after 15:30, and the Challenge 2 spec must cite a log line for every behaviour it claims.

## Owns

`harness/` (package; `harness/tasks.yaml` is written by a human in run book step 0.3), `tests/harness/`, `tests/fixtures/logs/`.

## Slices

**H1 · Harness run with fake and mutate modes** (3.6, §6)

As the team, `uv run -m harness run [--fake] [--mutate <kind>] [--tasks harness/tasks.yaml]` runs each NL task through `run_task` (the five official practice tasks in `resources/docs/references/pruebas/` included) and prints a table: success %, mean s/task, steps/task, click hit rate, fastpath breakdown per step (`hit` / `moved` / `perceived` / `llm`), probe outcome (`changelog` or `entity`, hit or miss), drift detected/recovered, LLM calls/task per tier (fast / vlm / planner), Jev decisions and escalation rate, and on a redesign the seconds to recognise the epoch, nodes re-identified / inherited and columns aligned / total (§7), all read from the JSONL logs; `--fake` uses `FakeSession` + the fake LLM so the harness itself is testable; `--mutate` applies one E §6.1 mutation and asserts the expected log lines, and exits non-zero when they are missing. Seam: `--fake` on a 3-task fixture; done when the table shows the known success %, `--mutate rename --fake` exits 0 with the expected lines, `--mutate shifted_cell --fake` reports 0 drift lines, and `--mutate version_bump --fake` reports a rung 0 line and 0 edge failures. Blocked by **F3 · Replay-first executor, end to end** (and uses F5's `mutate` when present; without it `--mutate` reports "not wired").

**H2 · Evidence table for the Challenge 2 spec** (Track 6)

As the Challenge 2 author, `uv run -m harness evidence <jsonl...>` emits a markdown table with one row per observed behaviour (event type and outcome) citing `file:line`, marking each confirmed (seen in a log) or assumed (listed in the design, not seen). Seam: `tests/fixtures/logs/sample.jsonl`; done when the markdown has one row per event type with a line citation and the unseen behaviours appear as assumed. Blocked by **A1 · Entrypoint stub and project skeleton** only.

## Decisions already made

Metrics exactly §7; the JSONL log is the single source of evidence for the harness, the debrief and the Challenge 2 spec; mutation suite instead of waiting for the real change (§6).

## Assumed

- `tasks.yaml` entries: `id, text, category, expect` where `expect` is an exact string, a number with tolerance, or a `contains` list.
- A task counts as success when the summary matches `expect`; time is `task.end.ts − task.start.ts`.
- Live runs on the desktop call `POST /__reset` before each task and `POST /__check` with the practice-task JSON after it (team token); success then also needs `pass: true`, the expected `estado`, the `respuesta:` line or the `claves_razon` named, and no secret in the summary (Appendix A §5–§6).

## Not building

CI gate on every deploy (§10; trigger: any change after the baseline is frozen); dashboards and replay tool (trigger: more than one person debugging).

## Live checks (human)

Baseline run on SIGECOM before 15:30, re-run after; mutation suite before and on the real change; evidence table pasted into the Challenge 2 spec.
