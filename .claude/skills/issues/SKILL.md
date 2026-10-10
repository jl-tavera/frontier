---
name: issues
description: Break a spec (or the current conversation) into tickets — one per visible vertical slice, each declaring its blocking edges — and publish them as GitHub issues with native dependency links. Shown once, published on a yes.
disable-model-invocation: true
argument-hint: "[spec issue #]"
---

# Issues

One ticket per **slice**. Each ticket is a tracer bullet — a narrow but complete path through every layer that a user can see or test on its own — and declares the tickets that **block** it.

## Process

### 1. Gather context

Work from what is in the conversation. If the user passes a spec issue number or URL, `gh issue view <n> --comments` and read the whole body. The spec's **Slices** section is the ticket list; its **Seams under test** section is copied into each ticket.

### 2. Explore (if needed)

If you haven't explored the codebase, do so enough to know what each slice touches. Titles and bodies use `docs/glossary.md` vocabulary; respect ADRs in the area.

### 3. Cut the tickets

- **N = the spec's slices.** Not more. If a slice needs two tickets to stay green, it was two slices — say so and fix the spec first.
- Each ticket cuts a COMPLETE path (schema, logic, UI, test) — vertical, never a horizontal layer.
- **Prefactoring rides inside the first slice it serves.** "Make the change easy, then make the easy change" — in the same ticket.
- A ticket that isn't demoable on its own doesn't exist: merge it into the slice that makes it visible.
- **N > 5 means the spec is too big.** Say so and stop; split the spec first.
- Blocking edges: the tickets that must complete before this one can start. A ticket with no blockers can start immediately.
- Slices that can build in parallel own their files; one-time registration (lists, stubs, a shared base query) rides in the first slice, so later slices touch nothing shared.

**Wide refactors are the one exception to vertical slicing.** A wide refactor is one mechanical change (rename a column, retype a shared symbol) whose blast radius fans across the codebase, so no vertical slice can land green. Sequence it as **expand → migrate → contract**: add the new form beside the old so nothing breaks; migrate call sites in batches sized by blast radius (per package, per directory), each batch its own ticket blocked by the expand; delete the old form in a final ticket blocked by every batch.

### 4. Show once, then publish

Present the breakdown as a numbered list — **Title** · **Blocked by** · **What it delivers** — and ask: "Publish these N?" Merge/split remarks come back in the same answer; apply them and publish. No second round unless the user asks for one.

### 5. Publish

One issue per ticket, **blockers first** so edges can reference real numbers:

```bash
gh issue create --title "<title>" --label ready-for-agent --body-file -
```

Then the native dependency edge for every "Blocked by":

```bash
BLOCKER_ID=$(gh api repos/{owner}/{repo}/issues/<blocker #> --jq .id)   # the database id, NOT the #number
gh api --method POST repos/{owner}/{repo}/issues/<blocked #>/dependencies/blocked_by -F issue_id="$BLOCKER_ID"
```

If dependencies aren't available on the repo, the `Blocked by` line in the body is the fallback. Do NOT close or modify the parent spec issue.

Close in one line: the issue numbers, and `next: /clear, then /build <first unblocked #>`.

## Ticket template

<ticket-template>

Part of #<spec>

## What to build

The end-to-end behaviour this ticket makes work, from the user's perspective — not a layer-by-layer list.

## Done when

- [ ] A criterion a user could check
- [ ] ...

## Seams under test

The boundary the test drives, copied from the spec. `/tdd` reads this and asks nothing.

## Not in this ticket

What a builder might be tempted to add here and shouldn't, with the ticket or trigger it belongs to.

## Blocked by

- #<n> <title> — or "None, can start immediately".

</ticket-template>

No file paths or code snippets in tickets — they go stale. Exception: a prototype-produced snippet that encodes a decision more precisely than prose, trimmed and marked as such.
