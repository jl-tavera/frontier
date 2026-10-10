# Subskill: Acceptance Criteria

Turn the user's *decisions* into criteria a developer can build to and a tester can
verify — **without either of them needing to re-derive the analysis.** Every decision
made in the workflow, every impact that must be handled, and every resolved edge case
should map to at least one criterion. If an impact or edge case has no matching
criterion, it will get forgotten in implementation.

## Format: Given / When / Then

Write each criterion so it's verifiable by a tester who can't read code:

```
Given <a starting situation>
When  <the action happens>
Then  <the observable, checkable result>
```

**Example 1:**
Given a patient with 12 past shifts
When an admin removes that patient
Then the patient is soft-deleted (hidden everywhere) and all 12 shifts remain intact
and still appear in past payroll reports

**Example 2 (negative case — just as important):**
Given a patient with an unpaid, already-issued invoice
When an admin tries to remove that patient
Then removal is blocked and the admin sees a message explaining the open invoice must
be resolved first

## Cover three buckets

1. **Happy path** — the clean case works as the user decided.
2. **Each handled impact** — one criterion per significant ripple from the Impact Map
   (e.g. payroll totals must not change, reports must still render).
3. **Each resolved edge case** — one criterion per item the user decided in the
   edge-cases step, including the "should NOT happen" cases.

Negative criteria ("Then X is blocked / Then the total does not change") matter as much
as positive ones — they're how you prove the scary cascades were actually prevented.

## Definition of Done

After the Given/When/Then list, add a **Definition of Done** checklist derived from the
Impact Map — the implementation chores that aren't user-visible behavior but must
happen for the change to be truly complete. Pull these straight from the affected
areas you found. Typical items:

- [ ] Data migration / backfill written and tested (and rollback verified)
- [ ] Every UI surface that showed the entity updated to respect the new behavior
- [ ] Background jobs that touch the entity updated and re-tested
- [ ] Reports / exports / payroll & billing calculations verified against known totals
- [ ] API responses and any external consumers checked for breakage
- [ ] Audit/retention requirements satisfied (record kept where law requires)
- [ ] Permissions enforced (only the right roles can perform the action)

## Output

Two blocks: **Acceptance Criteria** (the Given/When/Then list) and **Definition of
Done** (the checklist). Keep the language plain enough that the product owner can read
the acceptance criteria and confirm "yes, that's the behavior I decided" without help.
