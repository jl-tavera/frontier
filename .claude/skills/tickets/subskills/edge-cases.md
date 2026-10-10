# Subskill: Edge Cases

Impact analysis answers "what else touches this thing." Edge cases answer a different
question: **"what about the weird states of the change itself?"** A change that works
for the clean, simple case often falls apart on records that are mid-process,
historical, or at a boundary. Each edge case you find becomes a question the user must
answer — surface it, don't resolve it for them.

Walk this checklist and keep only the ones that genuinely apply. For each kept item,
write it as a plain-language question.

## In-flight / partial states

A record that is currently mid-process when the change hits.
*Examples:* a shift in progress right now; a payroll run that's halfway calculated;
an invoice in draft; a booking not yet confirmed.
*Question form:* "What should happen to a shift that's currently being worked when its
patient is removed?"

## Historical / immutable records

Things that already happened and arguably should never change retroactively.
*Examples:* a payroll period already paid out; an invoice already sent to the client;
a closed accounting month; audit log entries.
*Question form:* "Should already-sent invoices for this patient stay exactly as they
are, even after the patient is gone?"

## Empty and maximum boundaries

The zero case and the huge case.
*Examples:* a patient with no shifts at all; a patient with thousands of shifts; the
last remaining record of its kind.
*Question form:* "If a patient has thousands of linked records, is a slow bulk
operation acceptable, or does this need to run in the background?"

## Reversibility

Can this be undone, and how?
*Examples:* is there a backup/restore path; can a migration roll back; is a soft-delete
recoverable by support, or gone forever?
*Question form:* "If we remove a patient by mistake, how do we get them back — and who
is allowed to do that?"

## Data integrity after the change

What does the data look like the moment after?
*Examples:* orphaned rows pointing at nothing; a required field now empty; a count or
total that no longer adds up; a unique constraint freed up and reusable.
*Question form:* "After removal, should the freed-up patient ID/number ever be reused,
or retired permanently?"

## Permissions and visibility

Who can do this, and who sees the result?
*Examples:* should only an admin trigger it; does the change alter what other users
can see; does it expose or hide data.

## Timing / concurrency

Two things happening at once. Keep this light unless the domain is clearly sensitive.
*Examples:* the change runs while payroll is calculating; two users edit the same
record at once.

## Compliance / legal states

Regional and regulatory conditions on the change itself.
*Examples:* retention windows that forbid deletion; consent that must exist or be
withdrawn; differences by region/jurisdiction; data-subject (GDPR-style) requests.
*Question form:* "Does the retention rule differ by state/country for these records?"

## Output

A short list titled **Edge Cases to Decide**, each phrased as a question with the
realistic options where they're obvious. Order by how likely each is to cause real harm
if missed. Pass this list into the decisions step so the user resolves them before
acceptance criteria are written.
