# Spec H · Eval harness and evidence

Design: `resources/docs/solution.md` §5 unit 3.6, §6 ("Proving it before 15:30"), §7 (measurement plan), Track 6; Appendix E §6; Appendix A §7 (rubric: Specification criterion). Run book: [README.md](README.md).

## Problem

The success % and the per-task metrics are printed by Spec S's `synth eval` (S3). H must prove the mutation suite (§6) by its expected log lines, before 15:30 and on the real change, and the Challenge 2 spec must cite a log line for every behaviour it claims.

## Owns

`harness/` (package), `tests/harness/`, `tests/fixtures/logs/`. Imports `synth.eval.run` (S3); never edits `synth/`.

## Slices

**H1 · Mutation suite** (§6)

As the team, `uv run -m harness mutate <kind> [--fake] [--tasks ...]` applies one E §6.1 mutation to a copy of the stored map (F5's `mutate`; without it the command prints "not wired" and exits 2), runs the task suite through S3's `synth.eval.run` with one extra evaluator, `ExpectedLogLines(TABLE[kind])`, which asserts the E §6.1 expected log lines for that kind in each task's JSONL (`{event, field: value}` subsets; a line matches when every listed field equals), prints the same table S3 prints, and exits non-zero when any expected line is missing. Seam: `--fake` on a 3-task fixture with a scripted task; done when `--mutate rename --fake` exits 0 with the expected lines, `--mutate shifted_cell --fake` reports 0 drift lines, and `--mutate version_bump --fake` reports a rung 0 line and 0 edge failures. Blocked by **F3 · Replay-first executor, end to end** and **S3 · Eval run with pydantic-evals** (and uses F5's `mutate` when present).

**H2 · Evidence table for the Challenge 2 spec** (Track 6)

As the Challenge 2 author, `uv run -m harness evidence <jsonl...>` emits a markdown table with one row per observed behaviour (event type and outcome) citing `file:line`, marking each confirmed (seen in a log) or assumed (listed in the design, not seen). Seam: `tests/fixtures/logs/sample.jsonl`; done when the markdown has one row per event type with a line citation and the unseen behaviours appear as assumed. Blocked by **A1 · Entrypoint stub and project skeleton** only.

## Decisions already made

Metrics exactly §7, computed by S3's `LogMetrics` evaluator; the runner is S3's `synth.eval.run` and H only adds the `ExpectedLogLines` evaluator to it; the JSONL log is the single source of evidence for the harness, the debrief and the Challenge 2 spec; mutation suite instead of waiting for the real change (§6).

## Assumed

- Task files, their scoring and the live `__reset` / `__check` sequence are S3's; `mutate` only adds the expected-log-line assertions on top.
- The E §6.1 table of expected log lines per mutation kind lives in `harness/` as data, keyed by kind.
- Time per task is `task.end.ts − task.start.ts`.

## Not building

CI gate on every deploy (§10; trigger: any change after the baseline is frozen); dashboards and replay tool (trigger: more than one person debugging).

## Live checks (human)

Mutation suite before 15:30 and on the real change (`uv run -m harness mutate <kind>` per kind); the baseline and after runs are S3's `synth eval --live`; evidence table pasted into the Challenge 2 spec.
