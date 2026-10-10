# Research — Track 3: A fast agent loop

> Appendix F of [solution.md](../solution.md) · Status: adopted as component [C] (solution.md §3.2); Jev stays a gated 1 h spike · Links checked 2026-10-10.

**Decision:** Claude runs the loop **in-process** with plain Python tool functions, with no MCP. We build it in three steps, and each one has to earn its place on the 3.6 harness:
1. A tool-use loop with **batched actions** (L1+L2). This is the first end-to-end path.
2. **Plan-then-execute** with replan when a check fails (L3). This cuts the number of LLM calls.
3. A one-hour spike of **Jev** as the System 1 for per-step decisions, with a confidence gate that escalates to Claude (L4). We keep it only if the numbers prove it.

> **Terminology.** *System 2* is the slow, deliberate planner (Claude). *System 1* is a fast decision function that answers narrow, typed questions in about 100 ms (Jev). Jev is TypeSafe AI's "System One" model. It does **not** generate text: it returns typed choices or scores, each with a calibrated probability.

---

## 1. Time budget
Each task gets 300 s. The guard stops at **270 s** and writes a partial summary.

`step cost = LLM latency + act + settle`

| Component | Typical | Notes |
|---|---|---|
| Claude call (text state, cached prefix) | 2–5 s | grows with image tokens and output length |
| Jev call | 0.07–0.5 s | vendor numbers; users report a median of about 76 ms and 200–300 ms on Reddit |
| Act (RFB click/type) | < 0.1 s | local socket write |
| Settle (quiet-time) | 0.5–1 s | `poc/rfb_poc.py` `settle` |

| Loop style | s per action | Actions in 270 s | Typical task need |
|---|---|---|---|
| L1: 1 Claude call per action | 3–6 | 45–90 | 10–30: fits, with little room for recovery |
| L2: about 3 actions per Claude call | 1.5–2.5 | 110–180 | comfortable |
| L3: 1 plan + replans | ~1 + replans | 200+ | comfortable if replans stay rare |
| L4: Jev per step + Claude on escalation | ~0.7–1.5 | 180–380 | settle becomes the bottleneck |

**Where the time goes:** LLM round trips first, then settle, then image tokens. Every option below attacks round trips.

## 2. Options

| Option | How it works | Pros | Cons | Verdict |
|---|---|---|---|---|
| **L1. Plain tool-use loop** | Each Claude call returns one tool call → execute → result → next call | <ul><li>Simplest; the Anthropic SDK does it natively.</li><li>Easy to log and debug.</li></ul> | <ul><li>Slowest: one round trip per click.</li><li>Little time left for recovery.</li></ul> | **Baseline.** Build first |
| **L2. Batched tool calls** | Claude returns several `tool_use` blocks in one turn (fill 4 fields + click Guardar). We run them in order and stop at the first failed check | <ul><li>2–4× fewer round trips.</li><li>Same code as L1.</li></ul> | <ul><li>A mid-batch failure wastes the rest.</li><li>Needs a verify after each action.</li></ul> | **Adopt** together with L1 |
| **L3. Plan-then-execute** | Claude writes a step list once (`navigate_to Clientes; fill_field RUT=…; click_text Buscar; read_grid`). A deterministic executor runs it with per-step checks, and Claude is called again only when a check fails | <ul><li>The fewest LLM calls.</li><li>The plan doubles as the summary skeleton.</li><li>Pairs with App Memory shortcuts.</li></ul> | <ul><li>On an unseen app the first plan is a guess.</li><li>It only works if replanning is cheap and checks are strict.</li></ul> | **Adopt** after L1+L2 work |
| **L4. System 1 / System 2 with Jev** | Claude plans (as in L3). For each step, Jev answers typed questions over the text state: which element is the target, did it work, is the task done, is there drift. Below the confidence threshold, escalate to Claude | <ul><li>~100 ms per decision.</li><li>Calibrated probabilities give a principled escalation gate.</li><li>Cheap: $0.042/M input, output free.</li><li>Text-only fits our OCR-first perception.</li></ul> | <ul><li>Early access with a waitlist.</li><li>No image input.</li><li>Can't write values.</li><li>Unreliable at counting, arithmetic and dates.</li><li>32k context.</li><li>Unknown out-of-distribution behaviour on an unseen app.</li><li>Benchmarks are vendor-run.</li><li>A second vendor dependency.</li></ul> | **Spike** (1 h), gated by the harness |
| **L5. Code-as-action** | Each turn Claude writes a short Python snippet calling the tool functions (loops, ifs) | <ul><li>Flexible batching.</li><li>Handles repetition (pagination) in one turn.</li></ul> | <ul><li>Needs a sandbox for model-written code.</li><li>Failures happen inside opaque code and are harder to verify and log.</li></ul> | Discarded: L2+L3 give most of the gain without running generated code |
| **L6. Claude computer-use (raw x,y)** | A screenshot every step; the model outputs pixel coordinates | <ul><li>Works out of the box.</li></ul> | <ul><li>An image every step is slow.</li><li>Coordinate misses.</li><li>Breaks when layout shifts.</li></ul> | Discarded (Clicking row in [solution.md §4](../solution.md)) |
| **L7. Agent frameworks** (LangGraph, OpenAI/Claude Agent SDKs) | Orchestration layer over the same calls | <ul><li>Ready-made state and retries.</li></ul> | <ul><li>No latency gain.</li><li>More deps and abstraction to explain in the debrief.</li></ul> | Discarded: the loop is about 100 LOC |
| **MCP** (as tool transport) | Tools served over stdio/HTTP to the loop | <ul><li>Claude Code could drive the tools.</li></ul> | <ul><li>Extra process and hop on every action.</li><li>Nothing outside the service needs it.</li></ul> | Discarded |

## 3. Cross-cutting accelerators (apply to every option)
- **Text over images.** Send the OCR element list by default. Send a screenshot (or a crop) only when the model asks or a check is ambiguous.
- **Prompt caching** on the system prompt, the tool schemas and the app map summary. Steps after the first pay only for the changing state.
- **Model tiering.** Sonnet-class for routine steps; Opus-class only for recovery and replan. Add this only if measurements show we need it.
- **App Memory shortcuts.** `navigate_to(screen)` replaces about 5 menu clicks with one step (see [Appendix D](D-platform-mapping-papers.md) and [Appendix E §6](E-platform-mapping-methodology.md)).
- **Settle.** Quiet-time plus an expected-change check, never fixed sleeps. With L4 this becomes the dominant cost.

## 4. Jev deep dive

**Fit.** Our perception already turns the screen into text (elements with label, kind and bbox). That is exactly the kind of input Jev takes. The per-step decisions in L3 are narrow classifications, which is Jev's sweet spot. Planning, writing field values, the final summary and anything numeric stay in Claude or in code.

**Proposed call per step** (state as text or JSON, a single parallel pass):

| Question | Type | Options | Used for |
|---|---|---|---|
| `target` | Choice | ids of the visible elements (≤255) | ground the plan step ("click Buscar") to an element |
| `effect_ok` | Choice | yes / no | verify after act + settle |
| `done` | Choice | yes / no | stop condition |
| `drift` | Score | 0–1 | screen unlike the map → mark stale (the 15:30 path) |

Gate: act if the top probability ≥ θ (start at 0.8 and tune on the harness), otherwise escalate the step to Claude. Log every decision with its probability. That gives us the escalation rate and the evidence for the Challenge 2 spec.

**Adoption criteria.** On the 3.6 harness, with Jev in place compared to Claude-only:
- success % no more than 5 points lower;
- at least 5× faster per decision;
- escalation rate under 30%.

If it fails any of these, drop it. L3 stays intact because Jev only replaces the per-step checks.

**Risks.**
1. **Access.** It is early access, so we need a key before the hackathon. With no key, L4 is out and nothing else changes.
2. **Out-of-distribution behaviour.** The evaluation app is unseen. The confidence gate is the mitigation.
3. **Unverified claims.** The vendor states 40–200× speedups; users report a median of about 7×.
4. **Wrong-but-valid answers.** Jev can't produce an invalid type, but it can choose the wrong element. The `effect_ok` check after each action catches this.

## 5. Recommendation and order
1. **L1+L2.** A Claude tool-use loop with batched actions. One task working end to end through the entrypoint.
2. **L3.** Add plan-then-execute with strict checks; replan on failure.
3. **L4 spike (~1 h).** Put Jev behind the `effect_ok` and `target` checks and run the harness. Keep it or drop it based on the criteria above.
4. Throughout, apply the accelerators from section 3.

## 6. What to measure
All from the JSONL log [H], for every option:
- seconds per step;
- LLM calls per task;
- steps per task;
- success %;
- recoveries;
- escalation rate (Jev → Claude).

Run the baseline before 15:30 and again after.

## Sources
- TypeSafe AI, "Introducing System One Models & Jev": https://typesafe.ai/blog/introducing-system-one-models-and-jev (local: [../references/jev/typesafe-blog-introducing-jev.html](../references/jev/typesafe-blog-introducing-jev.html))
- InfoQ, "TypeSafe AI Releases Jev" (Oct 2026): https://www.infoq.com/news/2026/10/typesafe-ai-jev-released/ (local: [../references/jev/infoq-typesafe-jev-released.html](../references/jev/infoq-typesafe-jev-released.html))
- Flavio Copes, "A deep dive into Jev": https://flaviocopes.com/jev/ (local: [../references/jev/flaviocopes-jev.html](../references/jev/flaviocopes-jev.html))
- "Jev in the Wild" (arXiv 2609.30216): https://arxiv.org/pdf/2609.30216 (local: [../references/jev/2609.30216-jev-in-the-wild.pdf](../references/jev/2609.30216-jev-in-the-wild.pdf))
