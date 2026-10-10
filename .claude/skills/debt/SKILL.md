---
name: debt
description: Harvest every `lazy:` shortcut comment in the repo into one ledger — what was simplified, its ceiling, and the trigger to revisit — and flag the ones with no trigger. Read-only. Use on "/debt", "what did we defer", "list the shortcuts", "lazy ledger".
disable-model-invocation: true
---

# Debt

`# lazy:` markers are deliberate shortcuts with a known ceiling. This skill keeps them from becoming permanent by accident.

## Scan

```bash
grep -rnE '(#|//|--|<!--) ?(lazy|ponytail):' . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules
```

Each match is one ledger entry.

## Ledger

One line per marker, grouped by file:

`<file>:<line> — <what was simplified>. ceiling: <the limit named>. upgrade: <the trigger to revisit>.`

A marker that names no upgrade path or trigger gets the tag `no-trigger` — those are the ones that decay silently.

End with: `<N> markers, <M> with no trigger.` Nothing found: `No lazy debt. Clean ledger.`

## Boundaries

Read-only: changes nothing. Writes the ledger to `LAZY-DEBT.md` only if the user asks. One-shot.
