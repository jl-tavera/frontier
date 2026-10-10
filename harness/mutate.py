"""`uv run -m harness mutate <kind>`: one E §6.1 change on a copy of the stored map, the task suite through S3's
runner, and the change's expected log lines asserted in every task's JSONL (H1)."""
import asyncio
import contextlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from app.agent.loop import run_task
from app.log import Log
from app.memory import drift
from app.rfb.session import open_session
from synth.eval import BUDGET_S, EVALUATORS, Output, TaskInput, load, run, show

APP = "SIGECOM · Distribuidora Andina"
FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"
# E §6.1: per kind, `{event, field: value}` subsets a task's JSONL must hold; `count: 0` means it must hold none
TABLE: dict[str, list[dict]] = {
    "rename": [{"event": "drift", "signal": "S1", "rung": 1, "via": "fuzzy"}],
    "removed": [{"event": "drift", "signal": "S1", "rung": 1},
                {"event": "drift", "signal": "S1", "rung": 2, "via": "reexplore"}],
    "landing_mismatch": [{"event": "drift", "signal": "S3", "rung": 1, "via": "landing"}],
    "menu_moved": [{"event": "drift", "rung": 2, "via": "reexplore"}],
    "unknown_screen": [{"event": "drift", "signal": "S4", "rung": 3, "via": "replan"},
                       {"event": "rejoin", "signal": "S4"}],
    "persistent": [{"event": "drift", "signal": "S1", "rung": 4, "via": "rank_down"}],
    "version_bump": [{"event": "drift", "signal": "S5", "rung": 0, "via": "inherit"},
                     {"event": "step", "outcome": "fail", "count": 0},  # 0 edge failures
                     {"event": "drift", "via": "rank_down", "count": 0}],
    "redesign": [{"event": "drift", "signal": "S5", "rung": 0, "via": "inherit"},
                 {"event": "drift", "signal": "S5", "rung": 0, "via": "reidentify"},
                 {"event": "rejoin", "signal": "S5"}, {"event": "sync.schema_drift"}],
    "redesign_silent": [{"event": "drift", "signal": "S7", "rung": 0, "via": "inherit"},
                        {"event": "drift", "signal": "S7", "rung": 0, "via": "reidentify"},
                        {"event": "rejoin", "signal": "S7"}],
    "shifted_cell": [{"event": "drift", "count": 0}],
    "data_state": [{"event": "drift", "count": 0}],
}


@dataclass
class ExpectedLogLines(Evaluator):
    lines: list[dict]

    def evaluate(self, ctx: EvaluatorContext) -> dict[str, bool]:
        log = ctx.output.log  # every line: S3's `events` drops `rejoin`
        evs = [json.loads(x) for x in Path(log).read_text("utf-8").splitlines() if x.strip()] if log else []
        out = {}
        for want in self.lines:
            none = "count" in want  # every `count` is 0: the line must not appear
            match = {k: v for k, v in want.items() if k != "count"}
            seen = any(all(e.get(k) == v for k, v in match.items()) for e in evs)
            out[" ".join(f"{k}={v}" for k, v in match.items()) + " ×0" * none] = seen != none
        return out


@contextlib.contextmanager
def fresh(stored: Path | str):
    """A copy of the stored memory for one task: a repair it writes back must not hide the change from the next."""
    with tempfile.TemporaryDirectory(prefix="mutate-", ignore_cleanup_errors=True) as d:
        yield Path(shutil.copytree(stored, Path(d) / "memory"))


def fake_task(kind: str):
    """`run_task` over FakeSession on the golden map, Inicio → Cartera › Facturas, every task parsed as the same
    count: no network, no keys."""
    from app.perception.grid import Grid
    from tests.fakes.fake_app import FakeSession
    from tests.fakes.llm import FakeDecide, FakeLLM
    for tier in ("FAST", "VLM", "PLANNER"):  # FakeLLM ignores the id, but the client asks for one
        os.environ.setdefault(f"MODEL_{tier}", f"fake/{tier.lower()}")
    golden = tempfile.TemporaryDirectory(prefix="golden-", ignore_cleanup_errors=True)  # removed with the task
    stored = Path(golden.name) / "memory"
    (stored / APP / "v3.9").mkdir(parents=True)
    shutil.copy(FIXTURES / "maps" / "golden_map.json", stored / APP / "v3.9" / "map.json")
    tree = {("inicio", "Cartera"): "menu-cartera", ("menu-cartera", "Facturas"): "facturas",
            ("menu-cartera", "esc"): "inicio", ("facturas", "esc"): "inicio"}
    # lazy: one scripted parse for every task; script one per task when the fixture grows past counts
    parse = {"queries": [{"op": "read", "entity": "facturas", "where": {"Estado": "Vencida"}, "aggregate": "count"}],
             "confidence": 0.95}

    def read_grid(session):
        def read(fb):  # the fake screen's header and cell elements, as rows under the header left of each cell
            heads = sorted((e for e in session.elements if e.kind == "header"), key=lambda e: e.bbox[0])
            rows: dict[int, dict] = {}
            for e in session.elements:
                if heads and e.kind in ("cell", "link") and e.bbox[1] > heads[0].bbox[3]:
                    rows.setdefault(e.bbox[1], {})[[h for h in heads if h.bbox[0] <= e.bbox[0]][-1].text] = e.text
            return Grid([h.text for h in heads], list(rows.values()))
        return read

    async def task(inputs: TaskInput, log: Log):
        session = FakeSession("inicio", tree, FIXTURES / "elements")
        # the parse, then models that answer nothing useful, then the summary is whatever is left
        llm = FakeLLM(parse, *[{"text": "respuesta: 2", "data": {}}] * 8)
        with fresh(Path(golden.name) / "memory") as memory:
            return await run_task(inputs.text, session, log, 30.0, llm=llm, memory=memory, mutate=kind,
                                  perceive=lambda fb: session.elements, read_grid=read_grid(session),
                                  decide=FakeDecide(*[{}] * 8))
    return task


def live_task(kind: str):
    """S3's live task (`synth.eval.live_task`) on a fresh copy of the stored map per task, with the change applied."""
    url, password = os.environ["URL"], os.environ["PASSWORD"]
    auth = {"Authorization": f"Bearer {os.environ['TEAM_TOKEN']}"}
    async def task(inputs: TaskInput, log: Log) -> Output:
        async with httpx.AsyncClient(base_url=url, headers=auth, timeout=60) as http:
            (await http.post("/__reset")).raise_for_status()
            session = await open_session(url, password)
            try:
                with fresh("memory") as memory:
                    summary = await run_task(inputs.text, session, log, BUDGET_S, memory=memory, mutate=kind)
            finally:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(session.close(), 5)
            check = await http.post("/__check", json=inputs.practice)
            check.raise_for_status()
            return Output(summary, log.path, check.json())
    return task


def suite(kind: str, trees, fake: bool) -> int:
    """S3's table for the run; exits 1 only when an expected line is missing (a persistent break fails its tasks)."""
    if getattr(drift, "mutate", None) is None:
        print("not wired: F5's app.memory.drift.mutate is missing")
        return 2
    task = fake_task(kind) if fake else live_task(kind)
    report = asyncio.run(run(load(trees), task, (*EVALUATORS, ExpectedLogLines(TABLE[kind])), name=f"mutate-{kind}"))
    show(report)
    missing = [c for c in report.cases if any(not a.value and a.source.name == "ExpectedLogLines"
                                              for a in c.assertions.values())]
    return 1 if missing or report.failures else 0
