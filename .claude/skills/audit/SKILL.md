---
name: audit
description: Whole-repo audit for over-engineering — a ranked list of what to delete, simplify, or replace with stdlib/native equivalents. The Lean axis of /review, but for the entire codebase instead of a diff. One-shot report; applies nothing. Use on "/audit", "find bloat", "what can I delete from this repo".
disable-model-invocation: true
---

# Audit

The Lean review, repo-wide. Scan the tree instead of a diff; rank findings biggest cut first.

Skip generated data, virtualenvs, vendored dependencies and `.git/` — not code. If the user names an area, stay in it.

## Tags

- `delete:` dead code, unused flexibility, speculative feature. Replacement: nothing.
- `stdlib:` a hand-rolled thing the standard library ships. Name the function.
- `native:` a dependency or code doing what the platform already does. Name the feature.
- `yagni:` an abstraction with one implementation, config nobody sets, a layer with one caller.
- `shrink:` same logic, fewer lines. Show the shorter form.

## Hunt

Dependencies the stdlib or platform already covers · single-implementation interfaces · factories with one product · wrappers that only delegate · files exporting one thing · dead flags and config · hand-rolled stdlib.

## Output

One line per finding, ranked: `<tag> <what to cut>. <replacement>. [path:line]`

End with `net: -<N> lines, -<M> deps possible.` Nothing to cut: `Lean already. Ship.`

## Boundaries

Over-engineering and complexity only. Correctness, security and performance are out of scope — route them to `/review`. A single smoke test or assert-based self-check is the minimum, never bloat. Lists findings, applies nothing. One-shot.
