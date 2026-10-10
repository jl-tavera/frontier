# Platform mapping as a graph — paper comparison (track 2)

> Appendix D of [solution.md](../solution.md) · Status: research input for track 2, refined by [Appendix E](E-mapping-methodology.md); where they differ, E wins (4-rung repair ladder instead of 5, ≤45 s pre-warm instead of ≤60 s) · Links checked 2026-10-10.

## 1. Summary

Question: how do published GUI agents build an **initial map** of an app as a graph (screens = nodes, actions = edges), and how do they **remap** when the app changes?

Research for track 2 of [solution.md §5](../solution.md) (2.2 exploration → app map, 2.3 fingerprint, 2.4 map storage, 2.5 pre-warm vs cold, 2.6 change detection / remap).

---

## 2. Problem and constraints

Our constraints, which every "steal" below is filtered through:
- The app is unseen.
- We see pixels only, over VNC/RFB. There is no DOM, a11y tree or view hierarchy.
- It is a desktop app.
- Each task has **5 min**.
- The app changes at 15:30.

PDFs are in `../references/papers/`. Every fact here comes from reading the paper; "n/s" means the paper does not say.

---

## 3. Options considered

The twelve papers, compared on what we need from them:

| # | Paper | Platform / input | Node = | Edge = | Screen dedup | Initial mapping (cost) | Remap / drift |
|---|---|---|---|---|---|---|---|
| 1 | **AutoDroid** ([2308.15272](https://arxiv.org/abs/2308.15272), MobiCom'24) | Android / view tree | UI state | UI action | n/s for screens; elements merged if same edge endpoints | Random clicking, 0.5–1 h/app + 5–10 min LLM task synthesis | None. LLM "can identify issues" if a shortcut misleads |
| 2 | **MobileGPT** ([2312.03003](https://arxiv.org/abs/2312.03003), MobiCom'24) | Android / a11y tree | "App page" = **the set of sub-tasks available** on it | Sub-task (parametrised function) | Check for the key UI elements of known sub-tasks, then cosine on the sub-task list. 3 FP / 0 FN on 269 screens, vs 38/14 for Screen2Vec and 57/28 for a vision-based method | Random explorer + LLM lists sub-tasks. 10–15 min, ~50 pages, $10.78 for all apps; unseen screens are explored on demand | **Partial.** If replay fails ("UIs may change… with app updates"), the LLM re-derives the action with the old action as a few-shot example (16% of actions, 100% acc). Detects "no change in screen" and loops. Nodes updated in place |
| 3 | **AppAgentX** ([2503.02268](https://arxiv.org/abs/2503.02268), 2025) | Android / **pixels** (OmniParser) | Page + Element + **Shortcut** nodes (Neo4j) | HAS_ELEMENT, LEADS_TO, COMPOSED_OF | ResNet-50 element embeddings; LLM merges page descriptions | No separate exploration; built from its own task runs | Fallback only: if a shortcut fails, revert to atomic actions. Shortcuts store raw x,y |
| 4 | **GUI-Xplore** ([2503.17709](https://arxiv.org/abs/2503.17709), 2025) | Android / **video (pixels)** | Cluster of screens + functional description | Action between clusters | Luminance-diff keyframes (≈116/app, vs 629 at 1 FPS), then GPT assigns each to a functional cluster | ~22 min of exploration video, ~200 pages/app | n/s |
| 5 | **LLM-Explorer** ([2505.10593](https://arxiv.org/abs/2505.10593), MobiCom'25) | Android / view tree | Abstract state = concrete states with the same function set | Abstract action (type, covered elements, explored/ineffective flag, LLM function label) | **Rules beat the LLM.** Strip dynamic properties (text, selection, scroll) and compare element sets | Random over **unexplored** actions; shortest path to the next one. LLM only to group actions and write input text. 2 h/app, **$0.11/app** vs $16.31 for DroidAgent | **Prune ladder:** if a path fails, try alternatives, then restart the app and retry from home, then **remove the edge** |
| 6 | **PG-Agent** ([2509.03536](https://arxiv.org/abs/2509.03536), ACM MM'25) | Android + web / **pixels only** | MLLM page summary + screenshot pointer | Queue of action summaries + the task served; same-page actions folded into one edge | MLLM "did the page jump?", then BGE-M3 + FAISS top-4, then MLLM picks one, then MLLM visual yes/no | None; built offline from demos (231 episodes → 700 nodes / 940 edges) | n/s |
| 7 | **GraphPilot** ([2601.17418](https://arxiv.org/abs/2601.17418), JICN'26) | Android / HTML from view tree | Page + LLM function description | (page, element, next page) triple | `PAGEID(HTML)`, method n/s | Offline exploration, method n/s | None: "relies on the integrity of the KG". Each plan step is validated against the triples before running |
| 8 | **MAGNET** ([2601.19199](https://arxiv.org/abs/2601.19199), 2026) | Android / pixels (OmniParserV2) | No screen graph. Two memories: **workflows** + **element function → list of icon images** | — | Retrieval; duplicates dropped, and new looks of a known function appended | Demos/datasets or the agent's own runs | **Only paper built around app updates.** Names "appearance drift" (redesign, same function) and "workflow drift" (steps reorganised). No explicit detection: stale entries fade via a recency×use score |
| 9 | **ActionEngine** ([2602.20502](https://arxiv.org/abs/2602.20502), 2026) | Web / DOM + a11y | Page **template** of "atoms" (static vs dynamic regions) | Operation (≥1 actions); data reads are self-loops with an output schema | **Structural signature** of atoms; dynamic content does not change identity | Task-independent DFS crawler (Claude Code + Playwright), 36–260 min, $11.6–37.2/app, 57–219 states | **Yes, the only one that writes repairs back.** The failure is localized to one node; a Patcher re-grounds it and "commits the repair back to the SMG" (91.2% WebArena; 73.1% before patching) |
| 10 | **Executable Agentic Memory** ([2605.12294](https://arxiv.org/abs/2605.12294), 2026) | Android / SoM screenshots from a11y boxes | Alternating state / action nodes (DAG) + BPE-mined **macro actions** | — | Embedding retrieval, then VLM verify; element IoU | Task-oriented DFS with an MLLM (CONTINUE / BACKTRACK / COMPLETE); budget n/s | None. "KG may become outdated" is listed as a limitation |
| 11 | **ScreenSearch** ([2605.16024](https://arxiv.org/abs/2605.16024), Microsoft 2026) | **Windows desktop** / UIA tree (OCR works offline: F1 0.646 vs 0.740) | Merged screen state | (s, **action signature**, s′); clicks quantized to a 30×30 grid | BM25 on spatial cell×role/text atoms + dense embedding → RRF top-200 → **Jaccard ≥ 0.93 is the only thing that can merge** | PUCT graph-bandit; reward = new state + new edge + ambiguity drop. 5,524 VM-hours (huge) | Flags screens where the same action has **different outcomes** (successor entropy) as unreliable, but does not repair |
| 12 | **UI-KOBE** ([2605.29534](https://arxiv.org/abs/2605.29534), 2026) | Android / **pixels** | Semantic state (role + layout, dynamic content allowed) + reference screenshot | Single action (JSON) + NL instruction; self-loops for in-page changes | Description embedding > threshold, then screenshot check; at runtime visual top-k, then the LLM picks or **rejects all** | LLM-guided, one action per step, aimed at unexplored elements. 300 steps, ~54 nodes / 226 edges, $6.2, 3.2–6.4 h/app (paper contradicts itself) | Detects "graph-unmatched" screens, **falls back to a free planner and rejoins the graph** at a known screen. Re-exploration is offline only |

Code available: AutoDroid, MobileGPT, GUI-Xplore, LLM-Explorer and UI-KOBE (GitHub). PG-Agent and AppAgentX are "will be released". GraphPilot is "on request". The rest are n/s.

---

## 4. Chosen design

What we take for each sub-problem:

| Sub-problem | Technique to take | From |
|---|---|---|
| **2.2 Exploration → app map** | Pick **unexplored** actions; shortest path through the known graph to reach the frontier. Use the LLM only to name/group actions (e.g. "these 12 grid rows = one `open row` action"). Denylist destructive labels. One action per step so every edge is clean. | LLM-Explorer, UI-KOBE |
| **2.3 Screen fingerprint** | `fingerprint = title-bar text + set of static OCR labels binned to a coarse grid` (drop numbers, dates, grid-cell contents). Merge on Jaccard ≥ ~0.9. If ambiguous, use a VLM yes/no against a reference screenshot. Coarse grid + text makes it independent of resolution. | ScreenSearch, ActionEngine (static vs dynamic atoms), UI-KOBE |
| **2.4 Map storage** | One JSON per app (keyed by title bar). Nodes: `{id, fingerprint, description, ref_screenshot, affordances[]}`. Edges: `{from, action:{kind, target_label, target_role}, to, desc, success, fail, last_ok}`. Data-reading actions as self-loops. No x,y stored. Neo4j (AppAgentX, EAM) is overkill. | MobileGPT, UI-KOBE, ActionEngine |
| **2.5 Pre-warm vs cold** | **Cold + incremental by default.** At most a ~30–60 s shallow BFS of the top menu bar on first contact (one level, read-only items), then learn on demand. Every task's trace is written back as edges, so the next task on the same app is warm (MobileGPT: warm 98.75% vs cold 82.7%, latency −62.5%). | MobileGPT, AppAgentX |
| **2.6 Change detection (15:30)** | The **expected-edge check**: each edge stores the fingerprint it should lead to. A mismatch is drift. Signals: (a) the target label is not found on the screen, (b) the action caused no screen change, (c) it landed on an unexpected or unmatched fingerprint, (d) the same action now has different outcomes. Repair ladder below. | MobileGPT (no-change), ActionEngine (localize), ScreenSearch (outcome dispersion), UI-KOBE (unmatched) |

### 4.1 Repair ladder for 2.6

Each rung is cheap, and the next one runs only if it fails. Every rung writes to the JSONL log for the Challenge 2 spec.
1. **Re-ground in place.** Find the same function under a new label or position (OCR fuzzy match, then the LLM with the old action as a few-shot example). If found, **patch the edge** and keep the node. (MobileGPT re-derive, ActionEngine Patcher, MAGNET "appearance drift".)
2. **Alternative path.** Search the graph for another route to the target node. (LLM-Explorer.)
3. **Local re-explore.** Mark the node `stale` and explore one hop from it, unexplored actions only, within a budget of about 20 s. (UI-KOBE frontier re-exploration, done online.)
4. **Free-plan fallback.** The LLM acts without the graph and rejoins it once a known fingerprint appears. (UI-KOBE.)
5. **Prune.** If an edge fails N times, delete it. Edges whose success has decayed are ranked down rather than deleted. (LLM-Explorer prune, MAGNET recency×use score.)

---

## 5. Trade-offs

Recommendation, with the discarded alternative:

| Decision | Chosen | Discarded, and why |
|---|---|---|
| Initial mapping | **Task-driven incremental graph** plus a ≤60 s shallow menu pre-warm; traces written back after each task | Full up-front exploration (AutoDroid, LLM-Explorer, UI-KOBE, ActionEngine): 10 min–hours per app, impossible inside a 5 min task on an unseen app |
| Node identity | **OCR static-label set on a coarse grid + Jaccard**, with a VLM verify only when ambiguous | Pure embedding or VLM matching (PG-Agent): ~3 MLLM calls per check and unstable across models (UI-KOBE A.1). Pixel hash: breaks on any data change |
| Edge target | **Semantic target (label + role)**, grounded to pixels at run time | Stored x,y (AppAgentX shortcuts): breaks the moment a button moves, which is exactly the 15:30 scenario |
| Task-time use | Plan a path over the graph in one call, then verify each step against the expected fingerprint | Per-step reactive LLM without a graph: 3–5× more LLM calls (GraphPilot, ActionEngine numbers) |
| Remap | **Online, localized repair** (ladder above), written back into the graph | Full re-learn: too slow. Offline-only repair (UI-KOBE, EAM): it fails at exactly the moment we are graded. Passive memory decay alone (MAGNET): too slow to react within one task |

---

## 6. Evidence and measurement

What the literature tells us:

1. **Nobody does online remapping after an app update.**
   - EAM and UI-KOBE name it as future work.
   - MAGNET handles drift only through slow memory evolution.
   - ActionEngine's Patcher is the closest: it localizes the failure to one node and writes the fix back into the graph.
   - Our 2.6 is therefore a real contribution, and the doc should say so.
2. **Exploring the whole app is too slow for us.**
   - Every full-exploration paper spends 10 min to hours per app; MobileGPT's 10–15 min is the cheapest.
   - Our 5 min task budget rules out exploring the whole app first. Mapping has to be **task-driven and incremental**, as in MobileGPT (on demand) and AppAgentX (memory from its own runs), with only a shallow pre-warm.
3. **Identify a screen by function, not pixels.**
   - MobileGPT (the sub-task set), LLM-Explorer (the function set), ActionEngine (static atoms) and UI-KOBE (role + layout) all strip dynamic content before comparing.
   - LLM-Explorer and MobileGPT both found that **rules or structure beat pure LLM or vision matching** for dedup.
4. **Pixels-only dedup is solved well enough.** The pattern is cheap retrieval followed by a strict verify step:
   - UI-KOBE and PG-Agent: embedding top-k, then VLM yes/no or "reject all".
   - ScreenSearch: spatially binned OCR text + Jaccard ≥ 0.93.
5. **Store targets as function + label, never coordinates.**
   - AppAgentX shortcuts store raw x,y and are fragile.
   - MobileGPT stores attribute-based actions (`click(text:"[contact_name]")`), and MAGNET stores the function plus several appearances. These survive a moved button.
6. **Plan over the graph in one LLM call, then verify each step.** GraphPilot (1.03 queries/task) and ActionEngine (1.5–3.5 calls/task, 27 s) show that a graph cuts LLM calls drastically, which suits our 5 min budget.

---

## 7. Open questions

None recorded in this document. The measurements for track 2 are defined in [Appendix E §6](E-mapping-methodology.md).

---

## 8. Sources

Papers, and what to read first:

| File | Read first if you work on |
|---|---|
| `2312.03003-mobilegpt.pdf` | 2.3, 2.4, 2.5: function-based page identity, on-demand exploration, in-context repair |
| `2602.20502-actionengine.pdf` | 2.4, 2.6: template states, plan-compile, Patcher that writes back |
| `2605.29534-ui-kobe.pdf` | 2.2, 2.3: pixels-only node ID, unmatched → fallback → rejoin |
| `2605.16024-screensearch.pdf` | 2.2, 2.3: the only desktop paper; action signatures, strict merge, ambiguity signal |
| `2505.10593-llm-explorer.pdf` | 2.2, 2.6: cheap rule-based exploration, prune ladder |
| `2601.19199-magnet.pdf` | 2.6: drift taxonomy (appearance vs workflow), function → many appearances |
| `2503.02268-appagentx.pdf` | 2.4: pixels-only Page/Element/Shortcut schema (anti-pattern: stored x,y) |
| `2601.17418-graphpilot.pdf` | Task-time: one-shot planning over the graph + per-step validation |
| `2509.03536-pg-agent.pdf` | 2.3: pixels-only dedup recipe |
| `2503.17709-gui-xplore.pdf` | 2.3: frame-difference keyframes as a "screen changed" signal |
| `2605.12294-executable-agentic-memory.pdf` | Macro actions mined BPE-style from frequent action pairs |
| `2308.15272-autodroid.pdf` | Baseline UTG + "this click leads to X" hints |
