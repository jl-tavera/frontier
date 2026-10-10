---
name: arch
description: Scan the codebase for deepening opportunities, present the top candidates as a visual HTML report, then grill through the one the user picks.
disable-model-invocation: true
---

# Arch

Surface architectural friction and propose **deepening opportunities**: refactors that turn shallow modules into deep ones, for testability and AI-navigability.

Built on a shared vocabulary:

- Call the Skill tool with `deep-modules` for the architecture terms (**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**) and its principles (the deletion test, "the interface is the test surface", "one adapter = hypothetical seam, two = real"). Use these terms exactly; don't drift into "component", "service", "API", or "boundary".
- `docs/glossary.md` names the good seams; ADRs in `docs/adr/` record decisions this skill should not re-litigate.

## Process

### 1. Explore

**Scope before you scan — YAGNI.** Deepening pays off by making *future* changes easier, so weight the parts of the codebase that recently changed:

- If the user named a direction (a module, a subsystem, a pain point), take it and skip the inference below.
- Otherwise walk back a good stretch of the commit history (`git log --oneline`) for the hot spots — the files and areas that keep coming up — and let those paths pull your attention first. Scattered changes with no clear hot spot: widen the net.

Read `docs/glossary.md` and the ADRs for the area first. Then spawn a sub-agent to walk the codebase. Explore organically and note where you experience friction:

- Where does understanding one concept require bouncing between many small modules?
- Where are modules **shallow**, with an interface nearly as complex as the implementation?
- Where have pure functions been extracted for testability while the real bugs hide in how they're called (no **locality**)?
- Where do tightly coupled modules leak across their seams?
- What is untested, or hard to test through its current interface?

Apply the **deletion test** to anything you suspect is shallow: would deleting it concentrate complexity, or just move it? "Yes, concentrates" is the signal you want.

### 2. Present the top candidates as an HTML report

**At most five candidates**, ranked by friction. Each must pass the deletion test *and* name a recent change that hurt because of it (from step 1's history). A candidate with no recent pain is speculative — drop it, or badge it so.

Write a self-contained HTML file to the OS temp directory so nothing lands in the repo: resolve `$TMPDIR` / `%TEMP%`, write `<tmpdir>/architecture-review-<timestamp>.html`, open it for the user (`start <path>` on Windows, `open` on macOS, `xdg-open` on Linux) and tell them the absolute path.

Tailwind via CDN for layout, Mermaid via CDN where relationships are graph-shaped (call graphs, dependencies, sequences), hand-built divs/SVG for the editorial visuals (mass diagrams, cross-sections). **Open with the Top recommendation** — which candidate to tackle first and why — then one card per candidate:

- **Files**: which files/modules are involved
- **Recent pain**: the change(s) that hurt because of the current shape
- **Problem**: why the current architecture causes friction
- **Solution**: plain English, what would change
- **Benefits**: in terms of locality and leverage, and how tests would improve
- **Before / After diagram**: side by side, custom-drawn, showing the shallowness and the deepening
- **Recommendation strength**: `Strong` / `Worth exploring` / `Speculative`, as a badge

Domain words from `docs/glossary.md`, architecture words from `deep-modules`. If `docs/glossary.md` defines "Order", say "the Order intake module", not "the FooBarHandler" and not "the Order service".

**ADR conflicts**: only surface a candidate that contradicts an ADR when the friction is real enough to warrant reopening it, and mark it in the card: *"contradicts ADR-0007, but worth reopening because…"*. Don't list every theoretical refactor an ADR forbids.

See [HTML-REPORT.md](HTML-REPORT.md) for the scaffold, diagram patterns and styling.

Do NOT propose interfaces yet. After the file is written, ask: "Which of these would you like to explore?"

### 3. Grill

Once the user picks a candidate, call the Skill tool with `grill` and walk the decision tree: constraints, dependencies, the shape of the deepened module, what sits behind the seam, which tests survive. `grill` runs `domain` inline, so new terms land in `docs/glossary.md` and a load-bearing rejection can become an ADR — offer it as *"Want me to record this so future reviews don't re-suggest it?"*, and only when a future explorer would need the reason. To explore alternative interfaces for the deepened module, call `deep-modules` and use its design-it-twice parallel sub-agent pattern.
