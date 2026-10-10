---
name: review
description: "Review the changes since a fixed point along three axes: Standards (this repo's documented coding standards plus a smell baseline), Spec (does the code do what the ticket/spec asked?), and Lean (what can be deleted — reinvented stdlib, unneeded deps, speculative abstractions). Three parallel sub-agents, reported side by side, never merged. Use when the user wants to review a branch, a PR, or work in progress, or asks to \"review since X\"; /build runs it before handing off to /ship."
argument-hint: "[fixed point]"
---

# Review

Three-axis review of the diff between `HEAD` and a fixed point:

- **Standards**: does the code conform to this repo's documented coding standards?
- **Spec**: does the code faithfully implement the originating ticket / spec?
- **Lean**: what in the diff can be deleted, shrunk, or replaced by something that already exists?

The axes run as **parallel sub-agents** so they don't pollute each other's context; this skill aggregates without reranking.

## Process

### 1. Pin the fixed point

The user's argument if given (a SHA, branch, tag, `HEAD~5`). Otherwise **default to the merge-base with the default branch** — `git merge-base HEAD origin/main` — and say so in one line; don't ask.

Capture the diff once: `git diff <fixed-point>...HEAD` (three-dot, so the comparison is against the merge-base) and the commits: `git log <fixed-point>..HEAD --oneline`. Confirm the ref resolves (`git rev-parse <fixed-point>`) and the diff is non-empty before spawning anything — a bad ref or empty diff should fail here, not inside three sub-agents.

### 2. Find the spec

In order: (1) the ticket number in the branch name `<type>/<issue>-<slug>` or in commit messages (`#123`, `Closes #45`) → `gh issue view <n> --comments`, plus its `Part of #<spec>` parent; (2) a path the user passed as an argument; (3) a spec file under `docs/` matching the branch or feature. Nothing found → the Spec sub-agent is skipped and the report says "no spec available".

### 3. Find the standards

What this repo documents about how code is written: `CLAUDE.md`, `docs/`, the ADRs in `docs/adr/`, and anything else that reads like a standard.

On top of that, the Standards axis always carries the **smell baseline** — Fowler's code smells (*Refactoring*, ch. 3) — under two rules: **the repo overrides** (a documented standard wins; where it endorses something the baseline would flag, suppress the smell) and **always a judgement call** (each smell is a labelled heuristic, "possible Feature Envy", never a hard violation; skip anything tooling already enforces).

Each smell reads *what it is* → *how to fix*:

- **Mysterious Name**: a function, variable, or type whose name doesn't reveal what it does or holds. → rename it; if no honest name comes, the design's murky.
- **Duplicated Code**: the same logic shape appears in more than one hunk or file in the change. → extract the shared shape, call it from both.
- **Feature Envy**: a method that reaches into another object's data more than its own. → move the method onto the data it envies.
- **Data Clumps**: the same few fields or params keep travelling together (a type wanting to be born). → bundle them into one type, pass that.
- **Primitive Obsession**: a primitive or string standing in for a domain concept that deserves its own type. → give the concept its own small type.
- **Repeated Switches**: the same `switch`/`if`-cascade on the same type recurs across the change. → replace with polymorphism, or one map both sites share.
- **Shotgun Surgery**: one logical change forces scattered edits across many files in the diff. → gather what changes together into one module.
- **Divergent Change**: one file or module is edited for several unrelated reasons. → split so each module changes for one reason.
- **Speculative Generality**: abstraction, parameters, or hooks added for needs the spec doesn't have. → delete it; inline back until a real need shows.
- **Message Chains**: long `a.b().c().d()` navigation the caller shouldn't depend on. → hide the walk behind one method on the first object.
- **Middle Man**: a class or function that mostly just delegates onward. → cut it, call the real target direct.
- **Refused Bequest**: a subclass or implementer that ignores or overrides most of what it inherits. → drop the inheritance, use composition.

### 4. Spawn the three sub-agents in parallel

**Standards** — give it the diff command and commit list; the standards files found; **the smell baseline pasted in full** (it has no other access to it); and the brief: "Report, per file/hunk where relevant, (a) every place the diff violates a documented standard: cite the standard (file + rule); (b) any baseline smell you spot: name it and quote the hunk. Distinguish hard violations from judgement calls — documented-standard breaches can be hard, baseline smells are always judgement calls, and a documented standard overrides the baseline. Skip anything tooling enforces. Under 400 words."

**Spec** — the diff command and commit list; the fetched ticket and spec; the brief: "Report: (a) requirements the ticket/spec asked for that are missing or partial; (b) behaviour in the diff that wasn't asked for — scope creep; check the ticket's *Not in this ticket*; (c) requirements that look implemented but where the implementation looks wrong. Quote the ticket/spec line for each finding. Under 400 words."

**Lean** — the diff command and commit list, and this brief, verbatim:

> Review this diff for unnecessary complexity only. One line per finding — location, what to cut, what replaces it. Format: `<file>:L<line>: <tag> <what>. <replacement>.` Tags — `delete:` dead code, unused flexibility, speculative feature (replacement: nothing) · `stdlib:` a hand-rolled thing the standard library ships (name the function) · `native:` a dependency or code doing what the platform already does (name the feature) · `yagni:` an abstraction with one implementation, config nobody sets, a layer with one caller · `shrink:` same logic, fewer lines (show the shorter form). Examples: `L12-38: stdlib: 27-line validator class. "@" in email, 1 line; real validation is the confirmation mail.` · `repo.py:L88: yagni: AbstractRepository with one implementation. Inline it until a second exists.` · `L30-44: shrink: manual loop builds dict. dict(zip(keys, values)), 1 line.` End with `net: -<N> lines possible.` — or, if there is nothing to cut, `Lean already. Ship.` and stop. Out of scope: correctness bugs, security, performance — other axes own those. A single smoke test or assert-based self-check is the minimum, not bloat: never flag it. List, don't apply.

If the spec is missing, skip the Spec sub-agent and note it in the final report.

### 5. Aggregate

Present the three reports under `## Standards`, `## Spec`, `## Lean`, verbatim or lightly cleaned. **Do not merge or rerank across axes.** End with one line per axis: the finding count and the worst item *within that axis*. No single winner across axes — that reranking is exactly what the separation prevents.

## Why three axes

A change can pass one axis and fail another: code that follows every standard but implements the wrong thing (Standards pass, Spec fail); code that does exactly what was asked but breaks the project's conventions (Spec pass, Standards fail); code that is correct and conventional and three times longer than it needs to be (both pass, Lean fail). Reporting them separately stops one axis from masking another.
