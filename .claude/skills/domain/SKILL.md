---
name: domain
description: Build and sharpen the project's domain model — the glossary in docs/glossary.md and the decisions in docs/adr/. Use when discussing codebase terminology, writing or editing the glossary, or recording an ADR. /grill and /arch load it and apply it inline.
---

# Domain

Actively build and sharpen the project's domain model as you design: challenge terms, invent edge-case scenarios, and write the glossary and decisions down the moment they crystallise. (Merely *reading* `docs/glossary.md` for vocabulary is not this skill — that's a one-line habit any skill can do. This is for changing the model, not consuming it.)

## Files

```
/
├── docs/glossary.md   the glossary, nothing else — never at the root
└── docs/adr/
    ├── 0001-slug.md
    └── 0002-slug.md
```

Create them lazily: the glossary in `docs/` when the first term is resolved — never at the repo root — and `docs/adr/` when the first ADR is needed. If the contexts ever diverge enough to need separate glossaries, the upgrade path is a context map in `docs/` pointing at one glossary per context — not before.

## During the session

**Challenge against the glossary.** When the user uses a term that conflicts with the glossary (`docs/glossary.md`), call it out immediately: "Your glossary defines 'cancellation' as X, but you seem to mean Y. Which is it?"

**Sharpen fuzzy language.** A vague or overloaded term gets a precise canonical one proposed: "You're saying 'account' — the Customer or the User? Those are different things."

**Discuss concrete scenarios.** Stress-test relationships with specific cases that probe the edges and force precision about where one concept ends and the next begins.

**Cross-reference with code.** When the user states how something works, check whether the code agrees. Surface contradictions: "Your code cancels entire Orders, but you just said partial cancellation is possible. Which is right?"

**Update the glossary inline.** When a term is resolved, write it in `docs/glossary.md` right then — don't batch. Format in [CONTEXT-FORMAT.md](CONTEXT-FORMAT.md). The glossary is devoid of implementation details: not a spec, not a scratch pad, not a home for implementation decisions. A glossary and nothing else.

**Offer ADRs sparingly.** Only when all three hold: **hard to reverse**, **surprising without context**, and **the result of a real trade-off**. If any is missing, skip it. Format in [ADR-FORMAT.md](ADR-FORMAT.md).
