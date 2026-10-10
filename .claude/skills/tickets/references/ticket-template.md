# Reference: Ticket Template

This is the output structure — the "structure" piece. Fill it exactly. It is
**dual-audience on purpose**: the top sections are for the product owner (plain
language, decisions), and "Affected Areas" near the bottom is the technical breadcrumb
trail for the developers, auto-filled from the Impact Map. The user never writes the
technical part — you generate it from what you found.

When creating the ticket in ClickUp, this becomes the description body. Keep the
section headers so tickets stay consistent and skimmable.

---

## [Title]

A short, action-oriented title. *Example: "Remove a patient without breaking shift
history, billing, or payroll."*

## Summary

Two or three plain-language sentences: what is changing, and why. No jargon.

## Business Decisions

The choices the product owner made, each with a one-line rationale. This is the record
of *what was decided and why*, so no one re-litigates it later.
*Example: "Patients are soft-deleted, not erased — billing law requires 7-year
retention, and payroll is derived from their shifts."*

## Impact Map

The ripple effects, worst first. This bridges both audiences.

| Severity | What happens (plain language) | Where in code |
|---|---|---|
| | | |

## Edge Cases & Handling

Each weird state and the decision made for it.
*Example: "Patient with an unpaid invoice → removal is blocked until the invoice is
resolved."*

## Acceptance Criteria

The Given/When/Then list, including negative cases. A tester should be able to verify
each one without reading code.

## Affected Areas (for developers)

The technical breadcrumb trail — the files, models, jobs, and reports the impact
analysis actually touched, so devs know exactly where to start. List real paths only.
*Example:*
- `app/models/patient.rb` — relationship/cascade config to change
- `services/payroll/calculator.rb` — verify totals unaffected
- `jobs/nightly_billing_job.rb` — confirm it skips soft-deleted patients

## Definition of Done

The implementation checklist from the acceptance-criteria step.

## Open Questions

Anything you could not verify in the code, or decisions still pending. Be honest here —
an explicit unknown is far safer than a confident guess buried in the ticket.
