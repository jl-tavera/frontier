---
name: grill
description: Interview the user about a plan, decision, or idea until the build-changing questions are settled. Use when the user says "grill me", "grill", "stress-test this", "interview me about", or wants to sharpen an idea before /spec; /arch runs it on the candidate the user picks. Asks only what changes the build; defaults and discloses the rest.
---

# Grill

Interview the user until you share an understanding of what gets built. Map it as a **design tree**: every decision branches into the decisions that hang off it. Work the tree in **rounds**.

When a repo is present, call the Skill tool with `domain` first and apply it inline as decisions crystallise (below). Outside a repo the interview is the same; there is just nothing to write to.

## What gets asked

A question earns its place only if the answer **changes what gets built**. In the body, name the two outcomes it decides between ("A: one page with tabs — B: three routes") and give your recommended answer. If you can't name two materially different outcomes, it isn't a question — it's a default.

Everything else gets the recommended answer applied silently and one line under **Assumed** at the end of the round, so the user can strike it. A struck default comes back as a question next round. Never stall on an answer you can default.

**Facts are your job, never the user's.** When a question needs a fact from the environment (filesystem, code, tools), dispatch a sub-agent or look it up; don't ask the user anything you could find. Don't block on it: only the questions downstream of a running lookup wait; ask the rest of the frontier now. **Decisions are the user's**: put each to them and wait.

## Rounds

The **frontier** is every decision whose prerequisites are settled — what you can ask *now* without guessing at answers you haven't heard. Ask the whole build-changing frontier in one round, numbered, each with a recommended answer. A question whose answer depends on another still open in this round belongs to a later round.

```
❓ **Q1** - **<title>**: <what it decides — outcome A vs outcome B>

➡️ <your recommended answer>

---

❓ **Q2** - **<title>**: ...

➡️ ...

**Assumed** (strike any):
- <decision>: <default applied>
```

Each answer reshapes the tree: settled decisions push the frontier outward and unblock what depended on them. Recompute the frontier and ask the next round.

## Done

The session is done when the **build-changing frontier is empty** — not when every branch has been visited. Close with the consolidated **Assumed** list and `next: /spec` (or whatever the user was grilling toward). The user's go-ahead is the confirmation; don't add a "do we share an understanding?" round.

## Paper trail

With `domain` loaded: challenge a term that conflicts with `docs/glossary.md` the moment it's used; sharpen a fuzzy one and record it there right away; offer an ADR only for a decision that is hard to reverse, surprising without context, and the result of a real trade-off. Create the files lazily.
