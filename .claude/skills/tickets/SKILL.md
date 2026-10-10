---
name: tickets
description: >-
  Write high-quality engineering tickets by reading the actual codebase and
  translating technical reality into business-level decisions. Use this whenever
  the user wants to scope a change, write a ticket or ClickUp task, or asks
  "what happens if I change/remove/rename X" — for example "if I delete patients,
  what happens to shifts, billing and payroll?". The user is a product owner who
  does NOT want to read code; this skill reads the repo for them, surfaces the
  ripple effects and the business decisions they need to make, and produces a
  dev-ready ticket. Trigger it for impact analysis, edge-case discovery,
  acceptance criteria, ticket structuring, and creating tickets in ClickUp —
  even when the user doesn't say the word "ticket".
---

# Tickets

## What this skill is for

The user is a product owner. They steer the product but do not read code and do
not want to. When they want to change something, they need to know the *whole-system
consequences* in plain language so they can make business decisions and guide the
developers correctly.

This skill is a **translation layer**. It reads the technical reality from the repo
and emits business-level decisions and a dev-ready ticket. Read code, output decisions.

Two non-negotiable principles shape every output:

1. **Never assume an action is even possible.** "Delete the patient" may be illegal
   (retention/audit rules), technically a soft-delete, or blocked by existing data.
   Surface the *options* as a decision for the user — do not silently pick one.

2. **Stay business-level for the user, but leave technical breadcrumbs for the devs.**
   The user never has to read code. But the ticket must tell developers exactly where
   to look (files, modules, jobs) so "no technical detail for me" never means "no
   direction for them." Every ticket is dual-audience.

## Environment

This runs in **Claude Code, inside the user's repository**, with the **ClickUp MCP**
connected. That means you can grep and read the codebase directly, and create the
ticket in ClickUp once the user approves it.

## Workflow

Follow these steps in order. Each analysis step has a companion file under `subskills/`
— read it when you reach that step rather than all at once.

### 1. Clarify the change

Restate the change in one plain sentence and classify it:
**add / modify / remove (delete) / rename / move / merge / split**.
If the entity or feature is ambiguous, ask one short question before reading code.

### 2. Analyze impact

Read `subskills/impact-analysis.md` and follow it. Output an **Impact Map**: every
place the change ripples to, written as a business consequence, ranked by severity,
each tagged with where it lives in the code.

### 3. Find edge cases

Read `subskills/edge-cases.md` and follow it. These are the *weird states of the
change itself* (a shift already worked, an invoice already sent, payroll mid-run),
not the dependencies from step 2. Each one becomes a question that needs a decision.

### 4. Surface decisions and get answers — do not skip this

Present the business decisions to the user in plain language, with the realistic
options for each (e.g. *soft-delete vs. anonymize vs. archive*) and what each one
does to the rest of the system. **Wait for their answers.** The user is the decision
maker; you are not. This is the heart of the skill — a ticket built on assumptions
is worse than no ticket.

### 5. Draft acceptance criteria

Read `subskills/acceptance-criteria.md` and follow it. Turn the user's decisions,
the impacts that must be handled, and the resolved edge cases into testable
Given/When/Then criteria plus a Definition of Done.

### 6. Assemble the ticket

Read `references/ticket-template.md` and fill it exactly. The template is
dual-audience by design: business sections for the user, an "Affected Areas"
breadcrumb section auto-filled from the Impact Map for the devs.

### 7. Create it in ClickUp — only after approval

Show the assembled ticket to the user first. **Never push to ClickUp before they
approve the content.** When they approve, create it with the ClickUp MCP. If you
don't know the target list, status, assignee, or priority, ask — don't guess. After
creating, give them the ticket link.

## Style of the output

- Plain language for anything the user reads. No jargon in the business sections.
- Be concrete: "deleting a patient cascade-deletes their shift history" beats
  "there are referential integrity concerns."
- When you cite code, cite the real path you actually found (`app/models/shift.rb`),
  never an invented one. If you couldn't verify something, say so plainly and list
  it as an Open Question rather than guessing.
- Severity language stays human: *Breaks / Cascades / Orphans / Silently wrong /
  Compliance risk* (defined in the impact subskill).
