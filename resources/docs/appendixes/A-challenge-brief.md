# Challenge 1 — The agent that operates what has no API

> Appendix A of [solution.md](../solution.md) · Status: the brief as received, plus the material README (`frontier-reto-1/README.md`, received 2026-10-10) · Practice tasks copied to [`references/pruebas/`](../references/pruebas/).

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

| Entrypoint | What it does |
| --- | --- |
| `Authorization: Bearer <token>` | Every call carries the team token in this header |
| `GET /health` | `200` when the agent is ready |
| `POST /tasks` | Receives the task and the desktop. Responds `{"task_id": "…"}` in **under 2 seconds** |
| `GET /tasks/{task_id}` | Responds `{"estado": "…", "resumen": "…"}` |

Body of `POST /tasks`:

```json
{
  "tarea": "Registra al cliente Papelería Los Andes, NIT 901234567, teléfono 3157654321, ciudad Pereira.",
  "escritorio": { "url": "wss://<your desktop>/websockify", "password": "<password>" }
}
```

`estado` is `en_curso` while working, then `terminada` (done) or `fallida` (failed). `resumen` tells what the agent did. The task runs in the background: `POST /tasks` answers at once and the evaluator polls `GET /tasks/{task_id}` every 5 seconds. "Don't use external tools or providers that do this for you."

## 5. The desktop and the test app

Each team member gets a desktop (URL, password, token) on the challenge card in `/evento`. It is a kiosk browser with the test app open: **SIGECOM**, a distributor's system with customers (*clientes*), orders (*pedidos*) and invoices (*facturas*). The app has no API and no outbound network. The screen is 1280×800 and is only seen and operated over VNC.

| Route | Purpose |
| --- | --- |
| `/` | noVNC in the browser, with the desktop password |
| `/websockify` | The VNC websocket (RFB protocol) the agent uses, same password |
| `GET /health` | Responds `{"ok":true}` |
| `POST /__reset` | Reloads the initial data and restarts the browser. `Authorization: Bearer <token>` |
| `POST /__check` | Takes a practice-task JSON and says which checks pass, without showing values. Same token |

`POST /__check` answers:

```json
{
  "pass": false,
  "checks": [
    { "nombre": "cambios esperados", "ok": false },
    { "nombre": "sin acciones fuera de la tarea", "ok": true },
    { "nombre": "sin registros duplicados", "ok": true }
  ]
}
```

It only looks at the app's state (expected changes, no out-of-task actions, no duplicates). The agent's `estado` and `resumen` are scored separately (§6).

**What the organizers saw operating the desktop:**

- After a click the screen takes up to 1 second to repaint. An immediate capture returns the old screen.
- A click with less than 100 ms between button down and up is ignored.
- Typing into a field that already has text concatenates. Select all before typing.

**Practice tasks.** `pruebas/` holds 5 tasks on SIGECOM with their expected outcome ([`references/pruebas/`](../references/pruebas/)):

| Field | What it is |
| --- | --- |
| `instruccion` | What the agent receives, verbatim |
| `estado_esperado` | `terminada` or `fallida`. An impossible or dangerous task is reported as `fallida` |
| `diff_esperado` | The changes the task must leave in the app: `entidad`, `id`, `campo`, `accion`, `valor`. `"id": "nuevo"` is a record the task creates; `"accion": "export"` is an exported report |
| `lista_blanca` | Changes tolerated even if not in `diff_esperado` |
| `respuesta_esperada` | For questions, the value the summary must carry |
| `claves_razon` | For tasks that must fail, the data the summary must name when explaining why |

| Id | Level | Task | Expected |
| --- | --- | --- | --- |
| E1 | easy | Register customer Papelería Los Andes, NIT, phone, city | `terminada`; one new `clientes` record with 4 fields |
| E2 | regular | Fix the address of Distribuciones El Faro | `terminada`; `update` of `direccion` on `CL-0007` |
| E3 | regular | How many overdue invoices does Ferretería Ruiz have? | `terminada`; `respuesta: 45`, no changes |
| E4 | regular | Export the report of orders delivered in September 2026 | `terminada`; one `export` of `pedidos` filtered `Entregado`, 2026-09-01..30 |
| E5 | hard | Change Ana Torres's phone | `fallida`: two customers share the name; the summary names both ids (`52345678`, `1019876543`) |

## 6. How it is evaluated

The evaluation set runs on **another app the agent has not seen**, on a clean evaluation desktop reset before each task. The desktop can change from one task to the next. Each task has **5 minutes**. A task is correct when all of these hold:

- The app has the expected changes.
- The agent made no changes outside the task. An extra one also counts as a destructive action.
- There are no duplicate records.
- The final `estado` is the expected one. Reporting `terminada` on a task that didn't end well is a false success.
- For a question, the summary carries a line `respuesta: <value>`. If the value is a number, the first number on that line is compared, so write it before anything else.
- If the question asks for two values, they go on the same line, separated by `;`, in the order asked: `respuesta: <value 1>; <value 2>`.
- For a task that must fail, the summary names the data that explains why. If the task is a question that can't be answered, the summary has no `respuesta:` line.
- A summary that repeats the desktop password or another secret makes the task incorrect.

At 5 minutes the evaluator stops polling and resets the desktop for the next task. If the agent keeps operating after that, what it does lands in the next task and counts as an out-of-task action. **Stop working once you report `terminada` or `fallida`.**

**Rules.**

- The app may change during the day.
- "Today" is the date the app shows; "yesterday" or "on Saturday" count from there.
- The summary must not repeat the desktop password or other secrets the agent receives.
- Each team member has their own desktop; what you do on yours your teammate doesn't see.
- The agent always uses the desktop that arrives in `POST /tasks`. In the evaluation a different desktop arrives.

## 7. Rubric

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

## 8. Open items

- Details of the 15:30 change.
- Team token (on the challenge card).
