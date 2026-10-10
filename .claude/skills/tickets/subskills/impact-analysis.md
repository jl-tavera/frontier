# Subskill: Impact Analysis

Goal: starting from a thing the user named in business language ("patients",
"shifts", "the billing flow"), find everywhere in the codebase that a change to it
would ripple, and report each ripple as a **business consequence** with a code
location attached. The user never reads this code — you do, and you translate.

## Step 1 — Map the business word to the code

The user says "patients." The code might call it `Patient`, `patients`, `client`,
`pt`, `member`, `participant`. Find the real name(s):

- Grep for the obvious term and likely synonyms across models/entities, database
  schema, and migrations.
- Identify the canonical data entity: the model/class and its table. Note its
  primary key — that key is the thread you follow everywhere else.

If you genuinely can't find it, stop and ask the user what the feature is called
internally rather than guessing.

## Step 2 — Trace outward in layers

Follow the primary key and the entity name through each layer below. For each hit,
record (a) what it is, (b) the file path, (c) the business consequence of the change.

1. **Data model & relationships.** Foreign keys and relations that point *to* this
   entity, and cascade rules on them. This is where "delete" gets dangerous. Look in
   ORM model definitions, schema/migration files, and relation declarations. Ask:
   what records reference this one, and what is configured to happen when it goes
   away — cascade delete, set-null, restrict, or nothing (orphan)?

2. **Business / service logic.** Functions, services, or domain logic that read or
   write the entity. Search for the model name and the key. These tell you what
   *behaviors* depend on the thing.

3. **Background jobs, schedulers, queues.** Cron jobs, workers, async tasks that
   touch the entity. These break silently in production, so they matter a lot. Search
   the jobs/workers/tasks directories.

4. **Reports, exports, analytics, billing/payroll calculations.** Anything that
   aggregates or derives numbers from the entity. For this user's domain especially:
   payroll is usually *derived* from shifts, and shifts reference patients — so a
   patient change can move a payroll number two hops away. Trace those chains.

5. **APIs & external consumers.** Endpoints, serializers, webhooks, and integrations
   that expose the entity to other systems. A change here can break a partner or a
   mobile app even when the internal code is fine.

6. **UI surfaces.** Screens/components that show or edit the entity. Lowest priority
   for impact, but note them so the ticket lists what users will see change.

## Step 3 — Classify each impact by severity

Use these labels so the user can triage at a glance:

- **Breaks** — the change makes existing code error out or stop working.
- **Cascades** — the change deletes or mutates other records automatically.
- **Orphans** — related records are left pointing at something gone (dangling data).
- **Silently wrong** — nothing errors, but a number or report becomes incorrect
  (the most dangerous, because no one notices). Payroll/billing miscalculations live
  here.
- **Compliance risk** — the change may violate retention, audit, consent, or
  regulatory rules (see below).

## Step 4 — The compliance reality check (do this for deletes/anonymization)

In regulated domains (healthcare, finance, HR/payroll), you often *cannot* hard-delete
a record. Audit trails, retention windows, and already-issued financial documents
frequently make a true delete illegal or impossible. So when the user says "erase X",
don't analyze deletion as if it's allowed — surface the realistic options instead and
let them choose in the decisions step:

- **Soft delete** — flag as deleted, keep the row. Preserves history and references;
  you must then hide it everywhere it currently shows.
- **Anonymize / de-identify** — strip identifying fields, keep the record for billing,
  payroll, and audit math. Common correct answer in healthcare.
- **Archive** — move out of the active set but keep retrievable.
- **Hard delete** — only when nothing references it and no retention rule applies.

For each option, state what it does to shifts, billing, payroll, and reports, so the
user is choosing between *consequences*, not words.

## Output format

Produce an **Impact Map** as a table, ordered by severity (worst first):

| Severity | What happens (plain language) | Where in code |
|---|---|---|
| Cascades | Deleting a patient auto-deletes all their shift records | `app/models/patient.rb` (has_many shifts, dependent: :destroy) |
| Silently wrong | Past payroll totals recompute because they derive from shifts | `services/payroll/calculator.rb` |
| Compliance risk | Billing records are legally retained 7 yrs; can't be deleted | `app/models/invoice.rb` |

Then write a 2–3 sentence plain-language summary the user can read on its own, and a
short list of **Decisions Needed** that feeds step 4 of the main workflow.

## Notes

- Prefer ripgrep (`rg`) for speed; search for both the entity name and its key/id
  column, and follow imports/relations rather than stopping at the first hit.
- A combined "find everything at once" search misses things — trace each layer
  deliberately.
- If you can't confirm a cascade rule from the code, say so and flag it as an Open
  Question. An honest "unverified" beats a confident guess.
