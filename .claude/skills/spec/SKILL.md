---
name: spec
description: "Turn the current conversation into a spec and publish it as a GitHub issue: no interview, just synthesis of what was discussed. One user story per visible vertical slice; seams stated, assumptions disclosed."
disable-model-invocation: true
---

# Spec

Take the current conversation and codebase understanding and produce a spec. **Do NOT interview the user** — synthesize what you already know. Anything still open gets a default and a line under **Assumed**.

## Process

1. **Explore** the repo if you haven't, so the spec fits the current state of the code. Use `docs/glossary.md` vocabulary throughout; respect ADRs in the area you're touching.

2. **Decide the slices**: the smallest set of end-to-end changes each of which a user can see or test on its own. A small feature is 1–3 slices. Prefactoring rides inside the first slice it serves — it is not a slice. Each slice becomes exactly one ticket in `/issues`, so the count here *is* the ticket count.

3. **Decide the seams under test**, per slice: the public boundary a test drives. Prefer existing seams; take the highest one that reaches the behaviour; the ideal number is one. State them — don't ask.

4. **Write and publish.** Use the template below. Make sure the label exists — `gh label list --json name --jq '.[].name' | grep -qx ready-for-agent || gh label create ready-for-agent --color 0E8A16 --description "Agent-buildable spec or ticket"` — then `gh issue create --title "<feature>" --label ready-for-agent --body-file -` with the body as a heredoc. Close in three lines: the issue link · the slice count · "Assumed and Seams are in the issue — strike anything and I'll `gh issue edit` it."

## Template

<spec-template>

## Problem

The problem the user is facing, from the user's perspective. 2–4 sentences.

## Solution

What the user will see once this is built. 2–6 sentences.

## Slices

One numbered user story per visible vertical slice — `As a <actor>, I want <capability>, so that <benefit>` — each demoable on its own. Typically 1–3. Nothing here that a user can't see or test.

## Decisions

Implementation decisions made in the conversation: modules built or modified, interfaces that change, schema/API contracts, architectural choices. Where it isn't obvious, the ladder rung each landed on (reused X · stdlib · native · one line · minimum). No file paths or code snippets — they go stale fast. Exception: a prototype-produced snippet that encodes a decision more precisely than prose (state machine, reducer, schema, type shape), trimmed to the decision-rich part and marked as from the prototype.

## Seams under test

Per slice: the boundary the test drives, and the prior art in this repo for that kind of test. Tests verify external behaviour, never implementation details.

## Assumed

Defaults applied during /grill or here, one line each. Strike any.

## Not building

Out of scope, and every YAGNI cut — each with the trigger that would bring it back ("add pagination when a list passes 200 rows").

</spec-template>
