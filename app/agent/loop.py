"""Replay-first executor (F §4.1, E §4.4, G §4.2): parse the task into queries, answer reads from the cache behind the
change-log probe, replay the stored procedure for writes, verify them on screen, write through, summarise.

The tool-use loop (`fallback`, F4) runs at most once per task: an unsure parse, an `explore`, a write with no stored
procedure for its (op, entity), or a step that failed."""
import asyncio
import contextlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Awaitable, Callable

from numpy import ndarray

from app.agent.llm import chat_json
from app.agent.parse import Plan, Query, parse_task
from app.agent.tools import Tools, _fold
from app.contracts import Effect, Perceive, Session, Summary
from app.log import Log
from app.memory.appmap import AppMap
from app.perception.grid import Grid
from app.perception.grid import read_grid as ocr_grid
from app.perception.ocr import elements as ocr_elements
# lazy: E has no public row write or cell typing; these privates go once E grows put_row / delete_row / parse_cell
from app.sync.cache import Cache, _norm, _now, _sha
from app.sync.paging import ID_HEADERS, _parse, _typed_rows, acquire_by_paging
from app.warm.replay import observe

CONFIDENT, SUMMARY_S = 0.8, 10.0
AGGREGATES = {"sum", "avg", "min", "max"}
COLUMN = re.compile(r"[^'\".\[\]]+")  # a column name that can't step out of its json path
Fallback = Callable[[str, Plan, Tools, AppMap], Awaitable[dict]]
ReadGrid = Callable[[ndarray], Grid]


async def no_fallback(task: str, plan: Plan, tools: Tools, m: AppMap) -> dict:
    """Stand-in until F4's tool-use loop."""
    return {"ok": False, "detail": "sin procedimiento conocido: el bucle de agente (F4) aún no existe"}


def page_probe(grid: Grid) -> tuple[int, str]:
    """The cache's probe value for a grid's page 1: (row count, hash)."""
    # lazy: the count is page 1's, not the total, so E's short-read guard only catches a read shorter than one page;
    # read the grid's total when the app shows one
    return len(grid.rows), _sha(grid.rows)


class _NeedsPerception(Exception):
    pass


def _no_perception(fb):
    raise _NeedsPerception


def _known_map(memory: Path, fb: ndarray) -> AppMap | None:
    """The stored map one of whose snapshots is on screen, found with no perception."""
    # lazy: reads D's map.json itself, as AppMap.load needs the title perception would give
    for p in sorted(memory.glob("*/*/map.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        d = json.loads(p.read_text("utf-8"))
        m = AppMap(memory, d["app_id"], d["version"], d)
        try:
            observe(fb, m, perceive=_no_perception)
            return m
        except _NeedsPerception:
            continue
    return None


def _sql(q: Query, app_id: str) -> tuple[str, tuple]:
    if not all(COLUMN.fullmatch(c) for c in q.where):
        raise ValueError(f"columna inválida en {q.where}")
    select = "data_json"
    if q.aggregate == "count":
        select = "COUNT(*)"
    elif q.aggregate:
        fn, _, col = q.aggregate.partition(":")
        if fn not in AGGREGATES or not COLUMN.fullmatch(col):
            raise ValueError(f"agregado inválido: {q.aggregate}")
        select = f"{fn.upper()}(json_extract(data_json, '$.{col}'))"
    where = "".join(f" AND json_extract(data_json, '$.{c}') = ?" for c in q.where)
    # values typed like the cached cells, so "1.000" matches 1000 and "14/10/2026" its ISO date
    values = (_parse(str(v).strip())[1] for v in q.where.values())
    return f"SELECT {select} FROM rows WHERE app_id = ? AND entity = ?{where}", (app_id, q.entity, *values)


def _shows(row: dict, q: Query) -> bool:
    """The grid row is the query's record: it carries the key and every field value as written."""
    values = {_fold(str(v)) for v in row.values()}
    return ((not q.key or _fold(str(q.key)) in values)
            and all(_fold(str(row.get(c, ""))) == _fold(str(v)) for c, v in q.fields.items()))


class _HandOff(Exception):
    pass


class Executor:
    def __init__(self, session: Session, log: Log, *, llm, memory: Path, perceive: Perceive, read_grid: ReadGrid):
        self.session, self.log, self.llm, self.memory = session, log, llm, Path(memory)
        self.perceive, self.read_grid = perceive, read_grid
        self.loop = asyncio.get_running_loop()
        # E's cache is sync (probe, click_next, align) and sqlite keeps to its thread: one thread holds the cache and
        # calls back into the event loop for the screen work.
        self.pool = ThreadPoolExecutor(1)
        self.m: AppMap | None = None
        self.tools: Tools | None = None
        self.cache: Cache | None = None
        self.closed = False

    async def db(self, fn, *args):
        return await self.loop.run_in_executor(self.pool, fn, *args)

    def _wait(self, coro) -> Any:
        """From the cache thread: run `coro` on the event loop and block for its result."""
        if self.closed:  # the task is over (budget cut): a stray cache job must not drive the screen
            coro.close()
            raise RuntimeError("task closed")
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    async def step(self, tool: str, *args) -> Effect:
        """One tool call, one `step` line."""
        e = await getattr(self.tools, tool)(*args)
        self.log.event("step", tool=tool, args=list(args), screen_id=e.screen_id, diff=e.changed_bbox,
                       outcome="ok" if e.ok else "fail", signal=e.signal, detail=e.detail, cost_ms=e.cost_ms)
        return e

    async def open(self, task: str) -> None:
        self.m = _known_map(self.memory, self.session.fb)
        if self.m is None:
            els = self.perceive(self.session.fb)
            titles = sorted((e for e in els if e.kind == "title"), key=lambda e: e.bbox[1])
            if not titles:
                raise RuntimeError("no hay título en pantalla: no se sabe qué aplicación es")
            self.m = AppMap.load(self.memory, titles[0].text, els, self.session.w, self.session.h)
        self.tools = Tools(self.session, self.m, task, perceive=self.perceive)
        self.cache = await self.db(lambda: Cache(self.m.app_id, self._probe, self.memory / "cache.sqlite", self.log,
                                                 llm=self._align))

    def _probe(self, entity: str) -> tuple[int, str]:
        # lazy: reads the page it lands on; after paging that is the last page, so the next probe misses and re-acquires
        self._wait(self.step("go_to", entity))
        return page_probe(self.read_grid(self.session.fb))

    def _align(self, old: list[str], new: list[str], sample: list[dict]) -> dict:
        """E's column-alignment leftovers, one MODEL_FAST call."""
        msg = json.dumps({"old": old, "new": new, "sample_rows": sample}, ensure_ascii=False, default=str)
        return self._wait(chat_json("fast", [
            {"role": "system", "content": "A grid's columns were renamed. Map each old column to its new name, or "
                                          "null when none fits. Reply with JSON only: {\"<old>\": \"<new>\" | null}."},
            {"role": "user", "content": msg}], self.llm))

    def entities(self) -> list[dict]:
        """Map nodes that show a grid, with its headers as columns."""
        out = []
        for nid, node in self.m.nodes.items():
            snap = node["appearances"][0]["elements_snapshot"] if node["appearances"] else []
            if cols := [e["text"] for e in snap if e["kind"] == "header"]:
                out.append({"id": nid, "name": node["title"], "columns": cols})
        return out

    async def read(self, q: Query, deadline: float) -> dict:
        need = await self.db(self.cache.need, q.entity)
        if need.status != "hit":
            if not (await self.step("go_to", q.entity)).ok:
                raise _HandOff(f"sin ruta a {q.entity}")
            status = await self.db(acquire_by_paging, q.entity, lambda: self.read_grid(self.session.fb),
                                   self._next_page, self.cache, deadline - self.loop.time())
            if status != "complete":
                return {"ok": False, "detail": f"lectura incompleta de {q.entity} ({status})"}
        sql, params = _sql(q, self.m.app_id)
        rows = await self.db(self.cache.query, sql, params)
        answer = rows[0][0] if q.aggregate else [json.loads(d) for (d,) in rows]
        return {"ok": True, "answer": answer}

    def _next_page(self) -> bool:
        return self._wait(self.step("click_text", "Siguiente")).changed_bbox is not None

    async def write(self, q: Query) -> dict:
        proc = next((p for p in self.m.procedures if (p.get("op"), p.get("entity")) == (q.op, q.entity)), None)
        if proc is None:
            raise _HandOff(f"sin procedimiento para ({q.op}, {q.entity})")
        # The parse asked for this write and the stored procedure is what it takes, Guardar included; only while it
        # replays, so the fallback never inherits the pass.
        self.tools.allow = {_fold(s["args"][0]) for s in proc["steps"] if s["tool"] == "click_text"}
        try:
            await self._replay(proc, {**q.fields, "key": q.key})
        finally:
            self.tools.allow = set()
        await self.step("go_to", q.entity)
        grid = self.read_grid(self.session.fb)
        # lazy: page 1 only; search the grid by key when records land past it
        row = next((r for r in grid.rows if _shows(r, q)), None)
        if (row is None) != (q.op == "delete"):
            return {"ok": False, "detail": f"{q.op} en {q.entity} no se ve en la lista tras guardar"}
        if not await self.db(self._write_through, q, grid.columns, row):
            return {"ok": False, "detail": f"{q.op} en {q.entity} no aparece en la bitácora de cambios"}
        return {"ok": True, "answer": row or q.key}

    async def _replay(self, proc: dict, params: dict) -> None:
        """The procedure's steps with `$Col` args from the query; `expect` is the screen a step must change to."""
        for s in proc["steps"]:
            try:
                args = [params[a[1:]] if isinstance(a, str) and a.startswith("$") else a for a in s["args"]]
            except KeyError as e:
                raise _HandOff(f"falta el dato {e} para el procedimiento") from None
            e = await self.step(s["tool"], *args)
            if not e.ok or (s.get("expect") and (e.screen_id != s["expect"] or e.changed_bbox is None)):
                # lazy: no repair ladder yet (F5); a failed step is an exhausted ladder
                raise _HandOff(f"falló el paso {s['tool']} {args}: {e.detail}")

    def _write_through(self, q: Query, columns: list[str], row: dict | None) -> bool:
        """The app's own row into the cache, then change-log page 1 re-read (G §4.2 step 1). False when the change
        log has one and it didn't move."""
        c = self.cache
        with c.db:
            if row is None:
                c.db.execute("DELETE FROM rows WHERE app_id=? AND entity=? AND EXISTS "
                             "(SELECT 1 FROM json_each(data_json) WHERE value = ?)", (c.app_id, q.entity, q.key))
            else:
                typed = _typed_rows(columns, [row])[0]
                key = next((h for h in columns if _norm(h) in ID_HEADERS), None)
                c.db.execute("INSERT OR REPLACE INTO rows VALUES (?,?,?,?,?,?,?)",
                             (c.app_id, q.entity, Cache._natural_key(typed, key),
                              json.dumps(typed, ensure_ascii=False, default=str), _sha(typed), _now(), "write-through"))
        watermark = "SELECT probe_hash FROM sync_state WHERE app_id = ? AND role = 'changelog'"
        before = c.query(watermark, (c.app_id,))
        c.advance_watermark()
        return not before or c.query(watermark, (c.app_id,)) != before

    async def close(self) -> None:
        self.closed = True
        if self.cache:
            # a cache job cut by the budget may still hold the thread: don't wait on it past a second
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.db(self.cache.db.close), 1)
        self.pool.shutdown(wait=False, cancel_futures=True)


SUMMARY = """You write the closing summary of a task an agent ran on a desktop business app. Reply with JSON only:
{"text": "<summary in Spanish>", "data": {<the values the task asked for>}}.
- A question gets one line `respuesta: <value>`: a number first, two values joined by "; " in the order asked.
  No `respuesta:` line when it could not be answered.
- When the status is fallida, name the data that explains why; never guess a value."""


async def summarize(task: str, status: str, results: list[dict], llm, timeout: float) -> Summary:
    """One MODEL_FAST call; a plain summary from the results when it fails or runs out of time."""
    user = json.dumps({"task": task, "status": status, "results": results}, ensure_ascii=False, default=str)
    try:
        out = await asyncio.wait_for(chat_json("fast", [{"role": "system", "content": SUMMARY},
                                                        {"role": "user", "content": user}], llm), timeout)
        return Summary(status, str(out["text"]), out.get("data") or {})
    except Exception:
        if status == "terminada":
            text = "respuesta: " + "; ".join(str(r["answer"]) for r in results if "answer" in r)
        else:
            text = "; ".join(r.get("detail") or r.get("reason", "") for r in results) or status
        return Summary(status, text, {"results": results})


async def run_task(task: str, session: Session, log: Log, budget_s: float, *, llm=None, memory: Path | str = "memory",
                   perceive: Perceive = ocr_elements, read_grid: ReadGrid = ocr_grid,
                   fallback: Fallback = no_fallback) -> Summary:
    ex = Executor(session, log, llm=llm, memory=Path(memory), perceive=perceive, read_grid=read_grid)
    reserve = min(SUMMARY_S, budget_s / 3)
    results: list[dict] = []
    deadline = asyncio.get_running_loop().time() + budget_s - reserve
    guard = asyncio.timeout_at(deadline)
    try:
        async with guard:
            await ex.open(task)
            plan = await parse_task(task, ex.entities(), [(p["op"], p["entity"]) for p in ex.m.procedures if "op" in p], llm)
            log.event("plan", args={"queries": [q.__dict__ for q in plan.queries], "confidence": plan.confidence})
            try:
                if plan.confidence < CONFIDENT:
                    raise _HandOff(f"parse inseguro ({plan.confidence:.2f})")
                for q in plan.queries:
                    if q.op == "explore":
                        raise _HandOff("la tarea pide explorar")
                    results.append({"op": q.op, "entity": q.entity,
                                    **await (ex.read(q, deadline) if q.op == "read" else ex.write(q))})
            except _HandOff as why:
                log.event("handoff", args={"reason": str(why)})
                rest = Plan(plan.queries[len(results):], plan.confidence)  # what is done stays done
                results.append({"op": "fallback", "reason": str(why), **await fallback(task, rest, ex.tools, ex.m)})
    except Exception as e:
        results.append({"ok": False, "detail": f"tiempo agotado: quedaban {reserve:.1f} s para el resumen" if guard.expired()
                        else f"error: {type(e).__name__}: {e}"})
    finally:
        if ex.m:
            ex.m.write_back()
        await ex.close()
    status = "terminada" if results and all(r.get("ok") for r in results) else "fallida"
    return await summarize(task, status, results, llm, reserve)
