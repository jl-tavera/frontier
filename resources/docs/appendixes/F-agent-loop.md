# Agent loop — fast plan → act → verify (track 3)

> Appendix F of [solution.md](../solution.md) · Status: adopted as component [C] (solution.md §3.2): parse → executor first, Jev as System 1 on a changed screen, the tool-use loop as the fallback; every model through OpenRouter · Links checked 2026-10-10.

## 1. Summary

**Decision:** the loop runs **in-process** with plain Python tool functions, with no MCP, and every model call goes through OpenRouter (`openai` SDK with `base_url`; the Anthropic SDK is not used). The order on every task, each layer earning its place on the 3.6 harness:
1. **Parse.** One fast-model call turns the natural-language CRUD action into typed queries (op, entity, where, fields, aggregate).
2. **Execute** (L3). A deterministic executor answers reads from the cache behind the change-log probe ([Appendix G §4.2](G-data-sync.md)) and replays stored procedures for writes, clicking stored positions while the pixels match ([Appendix E §4.4](E-mapping-methodology.md)). No further model call and no OCR on a mapped app.
3. **System 1 on a changed screen** (L4). Jev answers the typed per-step questions (which element is the target now, did the action work, is this drift) with a calibrated probability; below the gate, the VLM; still unsure, rungs 2–3 of the ladder.
4. **Fallback** (L1+L2). The tool-use loop with batched actions runs only when a query has no stored procedure (the first task on an unseen app), the parse is unsure, or the ladder is exhausted, and it writes the steps that worked back as the procedure.

> **Terminology.** *System 2* is the slow, deliberate planner (the planner model, through OpenRouter). *System 1* is a fast decision function that answers narrow, typed questions in about 100 ms (Jev). Jev is TypeSafe AI's "System One" model. It does **not** generate text: it returns typed choices or scores, each with a calibrated probability.

---

## 2. Problem and constraints

The time budget. Each task gets 300 s. The guard stops at **270 s** and writes a partial summary.

`step cost = LLM latency + act + settle`

| Component | Typical | Notes |
|---|---|---|
| Planner call (text state, cached prefix) | 2–5 s | grows with image tokens and output length |
| Jev call | 0.07–0.5 s | vendor numbers; users report a median of about 76 ms and 200–300 ms on Reddit |
| Act (RFB click/type) | < 0.1 s | local socket write |
| Settle (quiet-time) | 0.5–1 s | `poc/rfb_poc.py` `settle` |

| Loop style | s per action | Actions in 270 s | Typical task need |
|---|---|---|---|
| L0: parse once, replay stored positions | ~1 (act + settle) | 200+ | the happy path on a mapped app: 2 LLM calls per task |
| L1: 1 planner call per action | 3–6 | 45–90 | 10–30: fits, with little room for recovery |
| L2: about 3 actions per planner call | 1.5–2.5 | 110–180 | comfortable |
| L3: 1 plan + replans | ~1 + replans | 200+ | comfortable if replans stay rare |
| L4: Jev per step + VLM/planner on escalation | ~0.7–1.5 | 180–380 | settle becomes the bottleneck |

**Where the time goes:** LLM round trips first, then settle, then image tokens. Every option below attacks round trips.

---

## 3. Options considered

| Option | How it works | Pros | Cons | Verdict |
|---|---|---|---|---|
| **L1. Plain tool-use loop** | Each planner call returns one tool call → execute → result → next call | <ul><li>Simplest; an OpenAI-style tool-call loop is about 50 lines.</li><li>Easy to log and debug.</li></ul> | <ul><li>Slowest: one round trip per click.</li><li>Little time left for recovery.</li></ul> | **Fallback.** The last rung of the ladder, and the first task on an unseen app |
| **L2. Batched tool calls** | The planner returns several tool calls in one turn (fill 4 fields + click Guardar). We run them in order and stop at the first failed check | <ul><li>2–4× fewer round trips.</li><li>Same code as L1.</li></ul> | <ul><li>A mid-batch failure wastes the rest.</li><li>Needs a verify after each action.</li></ul> | **Adopt** inside the fallback |
| **L3. Parse, then execute** | One fast-model call turns the task into typed CRUD queries; a deterministic executor answers reads from the cache behind the probe and replays the stored procedure for writes (`navigate_to Clientes; fill_field RUT=…; click_text Buscar; read_grid`) with per-step checks, and a model is called again only when a check fails | <ul><li>The fewest LLM calls.</li><li>The plan doubles as the summary skeleton.</li><li>Pairs with App Memory shortcuts.</li></ul> | <ul><li>On an unseen app there is nothing to replay yet: the fallback runs once and stores the procedure.</li><li>It only works if replanning is cheap and checks are strict.</li></ul> | **Adopt** as the happy path |
| **L4. System 1 / System 2 with Jev** | On a changed screen (a replay miss), Jev answers typed questions over the text state: which element is the target now, did it work, is the task done, is there drift. Below the confidence threshold, escalate to the VLM, then the planner | <ul><li>~100 ms per decision.</li><li>Calibrated probabilities give a principled escalation gate.</li><li>Cheap: $0.042/M input, output free.</li><li>Text-only fits our OCR-first perception.</li></ul> | <ul><li>Early access (key in hand; keyless fallback to the fast model).</li><li>No image input.</li><li>Can't write values.</li><li>Unreliable at counting, arithmetic and dates.</li><li>32k context.</li><li>Unknown out-of-distribution behaviour on an unseen app.</li><li>Benchmarks are vendor-run.</li><li>A second vendor dependency.</li></ul> | **Adopt** behind `decide`; measured on the harness (§5) |
| **L5. Code-as-action** | Each turn the planner writes a short Python snippet calling the tool functions (loops, ifs) | <ul><li>Flexible batching.</li><li>Handles repetition (pagination) in one turn.</li></ul> | <ul><li>Needs a sandbox for model-written code.</li><li>Failures happen inside opaque code and are harder to verify and log.</li></ul> | Discarded: L2+L3 give most of the gain without running generated code |
| **L6. Claude computer-use (raw x,y)** | A screenshot every step; the model outputs pixel coordinates | <ul><li>Works out of the box.</li></ul> | <ul><li>An image every step is slow.</li><li>Coordinate misses.</li><li>Breaks when layout shifts.</li></ul> | Discarded (Clicking row in [solution.md §4](../solution.md)) |
| **L7. Agent frameworks** (LangGraph, OpenAI/Claude Agent SDKs) | Orchestration layer over the same calls | <ul><li>Ready-made state and retries.</li></ul> | <ul><li>No latency gain.</li><li>More deps and abstraction to explain in the debrief.</li></ul> | Discarded: the loop is about 100 LOC |
| **MCP** (as tool transport) | Tools served over stdio/HTTP to the loop | <ul><li>Claude Code could drive the tools.</li></ul> | <ul><li>Extra process and hop on every action.</li><li>Nothing outside the service needs it.</li></ul> | Discarded |

---

## 4. Chosen design

### 4.1 Recommendation and order

1. **Parse.** One `MODEL_FAST` call turns the natural-language CRUD action into typed queries `(op, entity, where, fields, aggregate)`; confidence under 0.8 hands the task to step 4.
2. **L3.** The executor: reads behind the change-log probe ([Appendix G §4.2](G-data-sync.md)), writes by replaying the stored procedure, stored positions while the pixels match ([Appendix E §4.4](E-mapping-methodology.md)), strict checks per step. No OCR and no further model call on a mapped app.
3. **L4.** On a replay miss, Jev answers `target`, `effect_ok` and `drift` in one call; below the gate the VLM with a Set-of-Mark image; then rungs 2–3 of the ladder ([Appendix E §4.5](E-mapping-methodology.md)).
4. **L1+L2.** The tool-use loop with batched actions, on `MODEL_PLANNER`: the last rung, and the first task on an unseen app. It writes the steps that worked back as the procedure, so the next task runs through step 2.
5. Throughout, apply the accelerators from §4.2.

### 4.2 Cross-cutting accelerators (apply to every option)

- **Text over images.** Send the OCR element list by default. Send a screenshot (or a crop) only when the model asks or a check is ambiguous.
- **Prompt caching** on the system prompt, the tool schemas and the app map summary. Steps after the first pay only for the changing state.
- **Model tiering.** Three OpenRouter tiers from env: `MODEL_FAST` (parse, summary, Jev's keyless fallback), `MODEL_VLM` (image questions), `MODEL_PLANNER` (fallback loop, replan). Tune the ids on the harness, never in code; the Anthropic SDK is not used anywhere.
- **App Memory shortcuts.** `navigate_to(screen)` replaces about 5 menu clicks with one step (see [Appendix D](D-mapping-papers.md) and [Appendix E §4.4](E-mapping-methodology.md)).
- **Settle.** Quiet-time plus an expected-change check, never fixed sleeps. With L4 this becomes the dominant cost.

### 4.3 Jev as System 1 (L4)

**Fit.** Our perception already turns the screen into text (elements with label, kind and bbox). That is exactly the kind of input Jev takes. The per-step decisions in L3 are narrow classifications, which is Jev's sweet spot. Planning, writing field values, the final summary and anything numeric stay in the OpenRouter models or in code.

**Call per step** (state as text or JSON, every question in one pass; `typesafe-sdk`, model `jev-latest`):

| Question | Type | Options | Used for |
|---|---|---|---|
| `target` | Choice | ids of the visible elements (≤255) | ground the plan step ("click Buscar") to an element |
| `effect_ok` | Choice | yes / no | verify after act + settle |
| `done` | Choice | yes / no | stop condition |
| `drift` | Score | 0–1 | screen unlike the map → mark stale (the 15:30 path) |

```python
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score   # pip: typesafe-sdk

r = await AsyncTypeSafeClient().system_one(
    state={"elements": elements_text, "old_action": "click 'Facturas' (menu, cell 2,1) → Facturas"},
    questions={
        "target": Choice(instructions="Which element does what `old_action` did?", criteria={e.id: e.text for e in elements}),
        "effect_ok": Noul(instructions="Did the last action produce the expected screen?"),
        "drift": Score(instructions="How unlike the stored map is this screen?", criteria=["same", "moved", "redesigned"]),
    })
# r.answers["target"].choice and .confidence; exact signatures per the SDK docs
```

Gate: act if the top probability ≥ θ (start at 0.8 and tune on the harness), otherwise escalate the step to the VLM, then the planner. Ask everything at once: one call per step, never one per question. All of it sits behind one function, `decide(state, questions)`; with no `TYPESAFE_API_KEY` the same questions go to `MODEL_FAST` in JSON mode, whose confidences are not calibrated, so that path is compared on accuracy and latency only. Log every decision with its probability. That gives us the escalation rate and the evidence for the Challenge 2 spec.

---

## 5. Trade-offs

**What the harness must show** for Jev, compared to the keyless `MODEL_FAST` fallback and to the VLM-only ladder:
- success % no more than 5 points lower;
- at least 5× faster per decision;
- escalation rate under 30%.

If it fails, `decide` points at `MODEL_FAST` and nothing else changes: Jev only answers the per-step questions; the executor and the fallback loop stay intact.

---

## 6. Evidence and measurement

All from the JSONL log [H], for every option:
- seconds per step;
- LLM calls per task;
- steps per task;
- success %;
- recoveries;
- escalation rate (Jev → VLM → planner);
- fastpath breakdown per step (hit / moved / perceived / llm) and probe outcome.

Run the baseline before 15:30 and again after.

---

## 7. Open questions

**Risks** of Jev as System 1.
1. **Access.** Key in hand. If it stops working, `decide` falls back to `MODEL_FAST` and nothing else changes.
2. **Out-of-distribution behaviour.** The evaluation app is unseen. The confidence gate is the mitigation.
3. **Unverified claims.** The vendor states 40–200× speedups; users report a median of about 7×.
4. **Wrong-but-valid answers.** Jev can't produce an invalid type, but it can choose the wrong element. The `effect_ok` check after each action catches this.
5. **Model ids.** The three OpenRouter tiers are placeholders in `.env.example` until filled by hand; the fakes keep the tests independent of them.

---

## 8. Sources

- TypeSafe AI, "Introducing System One Models & Jev": https://typesafe.ai/blog/introducing-system-one-models-and-jev (local: [../references/jev/typesafe-blog-introducing-jev.html](../references/jev/typesafe-blog-introducing-jev.html))
- InfoQ, "TypeSafe AI Releases Jev" (Oct 2026): https://www.infoq.com/news/2026/10/typesafe-ai-jev-released/ (local: [../references/jev/infoq-typesafe-jev-released.html](../references/jev/infoq-typesafe-jev-released.html))
- Flavio Copes, "A deep dive into Jev": https://flaviocopes.com/jev/ (local: [../references/jev/flaviocopes-jev.html](../references/jev/flaviocopes-jev.html))
- "Jev in the Wild" (arXiv 2609.30216): https://arxiv.org/pdf/2609.30216 (local: [../references/jev/2609.30216-jev-in-the-wild.pdf](../references/jev/2609.30216-jev-in-the-wild.pdf))
