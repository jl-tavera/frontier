---
name: guide
description: One-screen map of the idea→ship skills in this repo — which command fits the situation, in what order, and when to detour. The user asks for it; it is not a step in any flow.
disable-model-invocation: true
---

# Guide

Display this card. Don't act on it; the user picks the command.

## The main flow: idea → ship

| Step | Command | What comes out |
|---|---|---|
| 1 | `/grill` | The idea, interviewed in rounds. Only build-changing questions are asked; the rest is defaulted and listed under **Assumed**. Terms land in `docs/glossary.md`, hard-to-reverse choices in `docs/adr/`. |
| 2 | `/spec` | One GitHub issue: Problem · Solution · **Slices** (one per visible vertical slice, 1–3 typical) · Decisions · Seams under test · Assumed · Not building. |
| 3 | `/issues <spec #>` | One issue **per slice**, blockers first, with native dependency edges. Shown once, published on "yes". |
| 4 | `/clear`, then `/build <ticket #>` | Read the ticket → trace the code → the plan, then a **"Go?"** question → branch → `/tdd` at the ticket's seams → checks → `/review` → a **"Ship it?"** question. One ticket per context window. |
| 5 | tap **Ship it**, or type `/ship` | Layered commits that each pass the checks, a PR, a **"Merge?"** question, rebase-merge, what's next. |

Every stop is a tappable question, so it reaches you in the Remote Control app — and answering one never changes the permission mode.

Keep steps 1–3 in one context window; `/clear` before every `/build`.

## Detours

- A question only running code can answer → `/prototype` (throwaway, kept on a `prototype/<name>` branch; the answer folds back into the thread). Crossing a directory or harness? `/handoff` out and back.
- Something's broken → `/diagnose`. Builds a red-capable feedback loop before any theory; hands structural findings to `/arch`.
- A spare moment to keep the codebase good for agents → `/arch`. HTML report of ≤5 deepening candidates, then `/grill` on the one you pick. Vocabulary underneath: `/deep-modules` (module, interface, depth, seam) and `/domain` (glossary, ADRs).

## Lazy, always on

The ladder (needs to exist? → already here? → stdlib? → native? → installed dep? → one line? → minimum) is injected into every session and sub-agent. `/lazy lite|full|ultra|off` sets the intensity. `/review` carries a **Lean** axis (a delete-list ending `net: -N lines`). `/audit` runs it repo-wide. `/debt` lists every `# lazy:` shortcut and whether it has an upgrade trigger.

## At a phase boundary

First yes wins: **continue** (the next phase needs this one verbatim, or there's room left) → `/clear` (nothing here matters next) → `/handoff` (new directory, harness, or person) → **subagent** (tightly scoped, no steering needed) → `/compact <what's next>` (the default, and last).

## Reserved for you

`/spec`, `/issues`, `/build`, `/arch`, `/handoff`, `/debt`, `/audit`, `/guide` run only when you type them. `/ship` runs when you type it or tap **Ship it** — never otherwise (`tap-approval.py`). The model can't invoke the rest, and can't read any of their `SKILL.md` to replay them by hand (`reserved-skills.py`). Commits and pushes on `main` are blocked (`no-commit-on-default.py`).
