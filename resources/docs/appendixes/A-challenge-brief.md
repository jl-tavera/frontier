# Challenge 1 — The agent that operates what has no API

> Appendix A of [solution.md](../solution.md) · Status: the brief as received, verbatim · Links checked 2026-10-10.

An agent that learns to operate systems with no API, through the screen, and executes natural-language tasks in apps it has never seen.

## 1. Brief

We have a management system we've used for 15 years. It has no API, no documentation, and the vendor disappeared. Everything is done by hand: clicks, forms, pop-up windows, reports exported one by one.

We want an agent that learns to use that system the way a new employee would, and that executes tasks we ask for in natural language, even if it has never done them before. We have 5 systems like this, so the agent must be able to adapt to any of them.

## 2. Timeline

| Time | What happens |
| --- | --- |
| 12:00 | Systems design deadline |
| 15:30 | Incident / change in the system |
| 20:00 | Execution deadline; entrypoint must be live from here |
| 20:00–21:00 | Technical depth: 10-min individual debrief |
| Before your slot | Pitch material (optional) |
| 21:15–22:15 | Demo day |

## 3. Deliverables

| Stage | Deadline | Deliverable |
| --- | --- | --- |
| Systems design | 12:00 | Design doc (one page, PDF or link) |
| Systems design | 12:00 | Architecture diagram (image, PDF or link) |
| Execution | 20:00 | Repo (public URL) |
| Execution | 20:00 | Entrypoint (public URL of the deployed service, with `GET /health` and the team token) |
| Execution | 20:00 | 2-minute video (public link, 2 minutes max) |
| Demo day | Before your slot | Pitch material (slides, PDF or link), optional |

## 4. Entrypoint contract

Deployed by your team (anywhere you want), reachable from the internet from 20:00 until demo day ends.

- **Auth**: every call carries `Authorization: Bearer <token>` (team token).
- **`GET /health`** → `200` when the service is ready.
- **`POST /tasks`** → receives the natural-language task and the desktop (URL and password). Responds `{"task_id": "…"}` in **under 2 seconds**.
- **`GET /tasks/{task_id}`** → returns status (`en_curso`, `terminada`, `fallida` — in progress, done, failed) and a summary.
- Each task has **5 minutes**.
- Evaluated on an app your agent has never seen, on a clean evaluation desktop.
- The summary format and evaluation rules are in the README of the provided material.

## 5. Rubric

Scale 1 to 4 per criterion. They evaluate what you deliver, deploy and explain; they don't collect sessions or transcripts from your tools.

| Stage | Weight | Fed by |
| --- | --- | --- |
| 01 · Systems design | 30% | Design doc + diagram |
| 02 · Execution | 40% | Repo, entrypoint, video and hidden evaluation set (+ spec + log from Challenge 2) |
| 03 · Demo day | 15% | Pitch in your slot + optional material |
| 04 · Technical depth | 15% | 10-minute individual debrief |

### 01 · Systems design (30%) — deadline 12:00

| Criterion | What we look for | 1 looks like | 4 looks like |
| --- | --- | --- | --- |
| Problem understanding | What the system must solve, its limits and its assumptions. | Repeats the brief without making decisions. | Names assumptions, hard cases and what it leaves out, with reasons. |
| Architecture and trade-offs | Clear components and justified decisions. | A diagram with no decisions behind it. | Each decision says which alternative it discarded and why. |
| Measurement plan | How you'll know it works before building. | No way to measure the result. | Concrete test cases and metrics from the design. |

### 02 · Execution (40%) — deadline 20:00

| Criterion | What we look for | 1 looks like | 4 looks like |
| --- | --- | --- | --- |
| Result on the hidden evaluation set | What the entrypoint achieves on cases it doesn't know. The final run counts: <25% of cases = 1, up to 50% = 2, up to 75% = 3, more = 4. | The entrypoint doesn't respond or fails almost everything. | Solves most cases, including new ones. |
| Incident response | How you adapt to the 15:30 change. | The system breaks and you don't detect it. | You detect the change, adapt and explain it. |
| Repo quality | That someone else can run and understand it. | Can't be run. | Runs by following the README and the code explains itself. |
| Specification (Challenge 2) | That another engineer can reimplement the service from the spec, and that each behavior cites the log line that proves it. | Describes few behaviors, without evidence or with false claims. | Covers most behaviors, each with its log line, and marks what is confirmed vs. assumed. |

### 03 · Demo day (15%) — 21:15–22:15

| Criterion | What we look for | 1 looks like | 4 looks like |
| --- | --- | --- | --- |
| Clarity | That it's clear what you built and why. | By the end it's unclear what it does. | Within minutes the problem, solution and evidence are clear. |
| Evidence | Results seen working in the demo. | Only claims. | Shows real results, including what didn't work. |

### 04 · Technical depth (15%) — 20:00–21:00

| Criterion | What we look for | 1 looks like | 4 looks like |
| --- | --- | --- | --- |
| Explaining decisions | That each team member can explain how it works and why. | Can't explain key parts of the system. | Explains failures, limits and what they'd do next. |
| Reading results | How you interpret what the evaluation set shows. | Doesn't connect the numbers to the system. | Explains each failure with a concrete cause. |

## 6. Open items

- Summary format and evaluation rules (material README).
- Details of the 15:30 change.
- Access to the test app.
- Team token.
