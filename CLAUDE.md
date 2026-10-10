# frontier — Challenge 1: the agent that operates what has no API

Hackathon project. Brief and rubric: `resources/docs/challenge.md`. Architecture: `resources/docs/solution-design.md`.

## Run

`uv run poc/rfb_poc.py probe` talks RFB straight to the remote desktop, no browser. It needs `.env` at the root with `URL` and `PASSWORD`. `.env` is gitignored; never commit it.

## Docs

- "A doc" means a markdown file at `resources/docs/<name>.md`. Not a Claude Doc, not an artifact.
- The glossary and ADRs the skills write live at `docs/glossary.md` and `docs/adr/`.

## Agent skills

Checks. Run them for the areas touched; every commit must pass them:

- `python -m compileall -q poc` — syntax only, until there are tests.
- `uv run --with pytest pytest -q` — once `tests/` exists; then drop the line above.

`.claude/skills/` is vendored from https://github.com/jl-tavera/dotagents on 2026-10-10. Refresh: re-copy `dotagents/skills/` over it, excluding `__pycache__`. The gate hooks (`tap-approval`, `reserved-skills`, `no-commit-on-default`, `lazy-activate`) are not vendored; run dotagents' `python install.py` to get them.
