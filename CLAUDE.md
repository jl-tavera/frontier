# frontier — Challenge 1: the agent that operates what has no API

Hackathon project. Brief, rubric and evaluation rules: `resources/docs/appendixes/A-challenge-brief.md`; the official practice tasks E1–E5: `resources/docs/references/pruebas/`. Design doc: `resources/docs/solution.md`, rendered to `resources/docs/solution.html` and published at https://jl-tavera.github.io/frontier/resources/docs/solution.html (that path must not change).

## Run

`uv run poc/rfb_poc.py probe` talks RFB straight to the remote desktop, no browser. It needs `.env` at the root with `URL` and `PASSWORD`. `.env` is gitignored; never commit it.

## Docs

- "A doc" means a markdown file at `resources/docs/<name>.md`. Not a Claude Doc, not an artifact.
- Appendixes (brief, recon, research) live in `resources/docs/appendixes/`, letter-prefixed in appendix order; the research appendixes C–H share one skeleton (Summary, Problem, Options, Chosen design, Trade-offs, Evidence, Open questions, Sources). `uv run resources/docs/build_html.py` regenerates `solution.html` (main doc + all appendixes inline) and one standalone page per appendix (`appendixes/<stem>.html`); commit the HTML.
- The glossary and ADRs the skills write live at `docs/glossary.md` and `docs/adr/`.

## Layout

- `app/` is the service (`app.main:app`); `app/{rfb,perception,memory,sync,agent,warm}` and `harness/` are one spec's package each (W creates `app/warm/` with its own `__init__.py`). Ownership table: `resources/specs/README.md`.
- A ticket adds files only inside its own package. It never edits `pyproject.toml`, `uv.lock`, `app/contracts.py`, any `__init__.py`, or another spec's files.
- The three stubs `app/rfb/session.py: open_session`, `app/perception/ocr.py: elements` and `app/agent/loop.py: run_task` are each overwritten by exactly one ticket (B1, C1, F3).
- Tests never touch the network or `.env`; `tests/conftest.py` sets fake env vars. Use `FakeSession` (`tests/fakes/fake_app.py`, or the `fake_app` fixture) over element JSON screens.
- A ticket that needs a new dependency stops `needs-human` instead of editing the lock.

## Agent skills

Checks. Run them for the areas touched; every commit must pass them:

- `uv run --with pytest pytest -q`

`.claude/skills/` is vendored from https://github.com/jl-tavera/dotagents on 2026-10-10. Refresh: re-copy `dotagents/skills/` over it, excluding `__pycache__`. The gate hooks (`tap-approval`, `reserved-skills`, `no-commit-on-default`, `lazy-activate`) are not vendored; run dotagents' `python install.py` to get them.
