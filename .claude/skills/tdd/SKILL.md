---
name: tdd
description: Test-driven development — the red → green loop at the seams the ticket names. Use when building a ticket in /build, when the user wants a behaviour built test-first, or mentions "red-green". Never re-asks which seams to test when a ticket already says.
---

# TDD

TDD is the red → green loop. This skill is the reference that makes the loop produce tests worth keeping: what a good test is, where tests go, the anti-patterns, and the rules of the loop. Consult it before and during the loop, not after.

Read `docs/glossary.md` (if it exists) so test names match the project's domain language, and respect ADRs in the area you're touching.

## What a good test is

Tests verify behaviour through public interfaces, not implementation details. Code can change entirely; tests shouldn't. A good test reads like a specification — "user can checkout with valid cart" says exactly what capability exists, and it survives refactors because it doesn't care about internal structure.

See [tests.md](tests.md) for examples and [mocking.md](mocking.md) for when to mock.

## Seams: where tests go

A **seam** is the public boundary you test at: the interface where you observe behaviour without reaching inside. Tests live at seams, never against internals.

**The seams come from the ticket.** `/spec` states them per slice and `/issues` copies them into each ticket's **Seams under test**. Test there; don't re-ask. No ticket? Propose the seams yourself — the highest existing boundary that reaches the behaviour, ideally one — *state* them in one line and proceed. Ask only when two candidate seams would produce materially different tests and you can't tell which the user wants.

When the shape of the interface is itself in question (how deep the module is, where the seam belongs), call the Skill tool with `deep-modules` for the vocabulary. It is a reference to consult, not a session to run.

## The floor, and the ceiling

**Floor:** one runnable check per non-trivial behaviour — a branch, a loop, a parser, a money/security/compliance path — the smallest thing that fails if the logic breaks. Lazy code without its check is unfinished.

**Ceiling:** only the check command `CLAUDE.md` names. No new frameworks, no fixture farms, no per-function suites, no test for trivial glue or one-liners. A test that would fail on nothing isn't kept.

## Anti-patterns

- **Implementation-coupled**: mocks internal collaborators, tests private methods, or verifies through a side channel (querying the database instead of using the interface). The tell: the test breaks when you refactor but behaviour hasn't changed.
- **Tautological**: the assertion recomputes the expected value the way the code does (`expect(add(a, b)).toBe(a + b)`, a constant asserted equal to itself), so it passes by construction and can never disagree with the code. Expected values come from an independent source of truth: a known-good literal, a worked example, the spec.
- **Horizontal slicing**: writing all tests first, then all implementation. Bulk tests verify *imagined* behaviour — the shape of things rather than user-facing behaviour — and commit you to test structure before you understand the implementation. Work in **vertical slices**: one test → one implementation → repeat, each test a **tracer bullet** that responds to what the last cycle taught you.

## Rules of the loop

- **Red before green.** Write the failing test first, then only enough code to pass it. Don't anticipate future tests or add speculative features.
- **One slice at a time.** One seam, one test, one minimal implementation per cycle.
- **Refactoring is not part of the loop.** It belongs to `/review`, not the red → green cycle.
