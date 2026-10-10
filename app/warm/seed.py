"""Cache seed from the map (W3): every node whose snapshot has a grid is acquired into `memory/cache.sqlite`, and the
change-log node is registered as the app-wide probe (Appendix G §4.2), so the first lookup after deploy answers from SQL.

The seed is checked by the probe when it is used, so a stale seed costs one re-acquire, never a wrong answer."""
import json
import re
from pathlib import Path
from typing import Awaitable, Callable

from app.agent.llm import chat_json
from app.agent.loop import Executor, ReadGrid, page_probe
from app.contracts import Perceive, Session
from app.log import Log
from app.sync.cache import _sha
from app.sync.paging import acquire_by_paging

# over node ids, the screen titles as ASCII slugs; "catalogo", "logistica" and "login" are no log
CHANGELOG = re.compile(r"\b(bitacora|cambios|log\b|historial|auditor)")


async def ask_changelog(candidates: list[dict]) -> str | None:
    """One MODEL_FAST call: which of these grid screens is the app's change log, if any."""
    out = await chat_json("fast", [
        {"role": "system", "content": "These are the grid screens of a desktop business app. Which one is its change "
                                      "log (who changed what, when)? Reply with JSON only: {\"id\": \"<id>\" | null}."},
        {"role": "user", "content": json.dumps(candidates, ensure_ascii=False)}])
    pick = out.get("id") if isinstance(out, dict) else None
    return pick if pick in {c["id"] for c in candidates} else None


class _Seeder(Executor):
    """F's executor, with the probe of an entity it has just paged reading what it paged: (rows, page-1 hash)."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.paged: dict[str, dict] = {}  # entity -> {page hash: Grid}, in page order

    def _probe(self, entity: str) -> tuple[int, str]:
        # lazy: the count is every page's while F's page_probe counts page 1, so on an app with no change log a
        # seeded multi-page entity probes stale once and is re-acquired; SIGECOM has one, so need() never compares
        if pages := self.paged.get(entity):
            return sum(len(g.rows) for g in pages.values()), page_probe(next(iter(pages.values())))[1]
        return super()._probe(entity)

    async def acquire(self, entity: str) -> str:
        if not (await self.step("go_to", entity)).ok:
            return "unreachable"
        pages = self.paged[entity] = {}

        def read():
            grid = self.read_grid(self.session.fb)
            pages.setdefault(_sha(grid.rows), grid)
            return grid

        return await self.db(acquire_by_paging, entity, read, self._next_page, self.cache)


async def seed(session: Session, memory: Path | str, log: Log, *, perceive: Perceive, read_grid: ReadGrid,
               tiebreak: Callable[[list[dict]], Awaitable[str | None]], entities: list[str] | None = None) -> dict[str, str]:
    """Acquire every grid node of the stored map (or just `entities`) and register the change log.
    Returns entity -> status (`complete`, `partial`, `unreachable`)."""
    ex = _Seeder(session, log, llm=None, memory=Path(memory), perceive=perceive, read_grid=read_grid)
    try:
        await ex.open("")
        grids = ex.entities()
        hits = [g for g in grids if CHANGELOG.search(g["id"])]
        changelog = None
        if len(hits) == 1:
            changelog = hits[0]["id"]
        elif grids:
            changelog = await tiebreak(hits or grids)
        out = {g["id"]: await ex.acquire(g["id"]) for g in grids
               if g["id"] != changelog and (not entities or g["id"] in entities)}
        if changelog:
            await ex.db(ex.cache.register_changelog, changelog)
        return out
    finally:
        await ex.close()
