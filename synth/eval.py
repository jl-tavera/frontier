"""`uv run -m synth eval`: every practice task through `run_task`, scored with pydantic-evals (S3)."""
import asyncio
import contextlib
import json
import os
import tempfile
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, MaxDuration
from pydantic_evals.reporting import EvaluationReport, EvaluationReportAdapter
from rich.console import Console

from app.agent.loop import run_task
from app.contracts import Summary
from app.log import Log
from app.rfb.session import open_session
from synth.gen import PRUEBAS

BUDGET_S = 270.0  # the service's per-task budget (app/runner.py)
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
FASTPATH = {"hit", "moved", "perceived", "llm"}
NODES = {"inherit": "nodes_inherited", "reidentify": "nodes_reidentified"}  # rung 0's two vias


@dataclass
class TaskInput:
    id: str
    text: str
    practice: dict  # the task JSON as written, for POST /__check


@dataclass
class Expected:
    estado: str
    respuesta: str | None = None
    claves_razon: list[str] = field(default_factory=list)


@dataclass
class Output:
    summary: Summary
    log: Path | None = None  # the task's JSONL
    check: dict | None = None  # POST /__check's answer, live only


def category(task_id: str) -> str:
    return "E" if re.fullmatch(r"E\d+", task_id) else task_id.split("-")[0]


def load(trees) -> list[Case]:
    """One case per practice-task JSON under the trees."""
    cases = []
    for tree in trees:
        for p in sorted(Path(tree).rglob("*.json")):
            t = json.loads(p.read_text("utf-8"))
            cases.append(Case(name=t["id"], inputs=TaskInput(t["id"], t["instruccion"], t),
                              expected_output=Expected(t["estado_esperado"], t.get("respuesta_esperada"),
                                                       t.get("claves_razon", [])),
                              metadata={"category": category(t["id"]), "nivel": t["nivel"]}))
    return cases


def _answer(text: str) -> str | None:
    m = re.search(r"^\s*respuesta:\s*(.*?)\s*$", text, re.I | re.M)
    return m and m[1]


@dataclass
class StatusMatches(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output.summary.status == ctx.expected_output.estado


@dataclass
class AnswerMatches(Evaluator):
    """The first number on the `respuesta:` line when the expectation is a number, else the whole line."""
    def evaluate(self, ctx: EvaluatorContext):
        want = ctx.expected_output.respuesta
        if want is None:
            return {}
        got = _answer(ctx.output.summary.text)
        if got is None:
            return False
        if NUMBER.fullmatch(str(want)):
            return bool(n := NUMBER.search(got)) and float(n[0]) == float(want)
        return got == str(want)


@dataclass
class ReasonKeysNamed(Evaluator):
    def evaluate(self, ctx: EvaluatorContext):
        keys = ctx.expected_output.claves_razon
        return all(k in ctx.output.summary.text for k in keys) if keys else {}


@dataclass
class NoSecret(Evaluator):
    """Neither the desktop password nor the team token is in the summary."""
    def evaluate(self, ctx: EvaluatorContext):
        secrets = [s for s in (os.environ.get("PASSWORD"), os.environ.get("TEAM_TOKEN")) if s]
        text = ctx.output.summary.text + json.dumps(ctx.output.summary.data, ensure_ascii=False, default=str)
        return not any(s in text for s in secrets) if secrets else {}


@dataclass
class OracleCheck(Evaluator):
    def evaluate(self, ctx: EvaluatorContext):
        return {} if ctx.output.check is None else bool(ctx.output.check.get("pass"))


def events(log: Path | None) -> list[dict]:
    """The JSONL's lines whose event name app/log.py documents (task.*, step, drift, sync.*)."""
    if log is None or not Path(log).is_file():
        return []
    lines = (json.loads(l) for l in Path(log).read_text("utf-8").splitlines() if l.strip())
    return [e for e in lines if e.get("event") in ("step", "drift") or e.get("event", "").startswith(("task.", "sync."))]


def metrics(evs: list[dict]) -> dict[str, float]:
    """§7's per-task metrics. A field that never appears yields no key."""
    # lazy: no LLM calls per tier until app/log.py documents F's `llm` event; count it here then
    by = lambda name: [e for e in evs if e["event"] == name]
    out: Counter = Counter()
    steps = by("step")
    drifted = [s for s in steps if s.get("signal")]  # one step per incident, however many rungs it climbed
    # rung 1 logs a confidence only once Jev was asked: fuzzy/cell need none; a VLM pick or a miss carries the VLM's
    jev = [e for e in by("drift") if e.get("rung") == 1 and e.get("confidence") is not None]
    clicks = [s for s in steps if s.get("tool", "").startswith("click")]
    if steps:
        out["steps"] = len(steps)
    if clicks:
        out["click_hit_rate"] = sum(s.get("outcome") == "ok" for s in clicks) / len(clicks)
    out.update(f"fastpath_{s['detail']}" for s in steps if s.get("detail") in FASTPATH)
    out.update(f"probe_{e.get('scope')}_{e.get('outcome')}" for e in by("sync.probe"))
    if drifted:
        out["drift_detected"] = len(drifted)
        out["drift_recovered"] = sum(s.get("outcome") == "ok" for s in drifted)
    if jev:
        out["jev_decisions"] = len(jev)
        out["escalation_rate"] = sum(e.get("via") != "decide" for e in jev) / len(jev)  # past Jev: VLM or worse
    if epoch := [e for e in by("drift") if e.get("rung") == 0]:
        out["epoch_s"] = sum(e.get("cost_ms") or 0 for e in epoch) / 1000
        out.update(NODES[e["via"]] for e in epoch if e.get("via") in NODES)
    for e in by("sync.schema_drift"):
        out["columns_aligned"] += len(e.get("aligned") or {})
        out["columns_total"] += len(e.get("old") or [])
    return dict(out)


@dataclass
class LogMetrics(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> dict:
        return metrics(events(ctx.output.log))


EVALUATORS = (StatusMatches(), AnswerMatches(), ReasonKeysNamed(), NoSecret(), OracleCheck(), LogMetrics(),
              MaxDuration(300))


async def run(cases: list[Case], task, evaluators=EVALUATORS, *, name: str = "eval",
              repeat: int = 1) -> EvaluationReport:
    """Each case through `task(inputs, log) -> Summary | Output`, one at a time, scored by the evaluators."""
    logs = Path(os.environ.get("LOG_DIR", "logs")) / f"eval-{name}"
    logs.mkdir(parents=True, exist_ok=True)

    async def episode(inputs: TaskInput) -> Output:
        log = Log(logs / f"{inputs.id}-{uuid.uuid4().hex[:6]}.jsonl")
        out = await task(inputs, log)
        return out if isinstance(out, Output) else Output(out, log.path)

    return await Dataset(name="synth", cases=cases, evaluators=list(evaluators)).evaluate(
        episode, name=name, max_concurrency=1, repeat=repeat, progress=False)


def _passed(case) -> bool:
    return all(a.value for a in case.assertions.values())


def _first_trouble(log: Path | None) -> str:
    """The first failed step, else the first drift line."""
    evs = events(log)
    for e in evs:
        if e["event"] == "step" and e.get("outcome") != "ok":
            return f"step {e.get('tool')} {e.get('args')} {e.get('outcome')}: {e.get('detail')}"
    for e in evs:
        if e["event"] == "drift":
            return f"drift {e.get('signal')} rung {e.get('rung')} via {e.get('via')}: {e.get('before')} -> {e.get('after')}"
    return "no failed step or drift in the log"


def _triage(case) -> str:
    want, got = case.expected_output, case.output
    expected = want.estado + (f" respuesta: {want.respuesta}" if want.respuesta is not None else "")
    return (f"{case.name}: expected {expected}, got {got.summary.status} {got.summary.text!r} | "
            + _first_trouble(got.log))


def _only_wrong_changes(case) -> bool:
    failed = {k for k, a in case.assertions.items() if not a.value}
    bad = {c["nombre"] for c in (case.output.check or {}).get("checks", []) if not c.get("ok")}
    return failed == {"OracleCheck"} and bad == {"cambios esperados"}


def show(report: EvaluationReport, baseline: Path | str | None = None) -> int:
    """The table (diffed against the baseline), one success line per category, one triage line per failed case.
    Returns the exit code: 1 when any assertion failed or any case raised."""
    if baseline:
        baseline = EvaluationReportAdapter.validate_json(Path(baseline).read_text(encoding="utf-8"))
    console = Console(width=200)
    report.print(baseline=baseline, console=console, include_averages=True)
    by: dict[str, list[bool]] = {"all": []}
    for c, ok in [(c, _passed(c)) for c in report.cases] + [(f, False) for f in report.failures]:
        by["all"].append(ok)
        by.setdefault(c.metadata["category"], []).append(ok)
    for cat, ok in by.items():
        console.print(f"{cat:<9} {sum(ok)}/{len(ok)}  {round(100 * sum(ok) / len(ok)) if ok else 0}%")
    failed = [c for c in report.cases if not _passed(c)]
    for c in failed:
        console.print(_triage(c), highlight=False, markup=False, soft_wrap=True)
    for f in report.failures:
        console.print(f"{f.name}: error {f.error_message}", highlight=False, markup=False, soft_wrap=True)
    updates = [c for c in failed if c.metadata["category"] == "update"]
    if updates and all(map(_only_wrong_changes, updates)):
        console.print("every failed update fails only 'cambios esperados': id format, not the agent")
    return 1 if failed or report.failures else 0


def save(report: EvaluationReport) -> Path:
    path = Path(os.environ.get("EVALS_DIR", "synth/reports")) / f"{report.name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(EvaluationReportAdapter.dump_json(report, indent=2))
    return path


def publish(path: Path | str, url: str, client=httpx) -> None:
    """POST the stored report to the service's `/evals`, bearer TEAM_TOKEN."""
    r = client.post(f"{url.rstrip('/')}/evals", content=Path(path).read_bytes(),
                    headers={"Authorization": f"Bearer {os.environ['TEAM_TOKEN']}",
                             "Content-Type": "application/json"})
    r.raise_for_status()


def live_task():
    """POST /__reset → open_session → run_task → POST /__check, on the desktop in URL / PASSWORD / TEAM_TOKEN."""
    url, password = os.environ["URL"], os.environ["PASSWORD"]
    auth = {"Authorization": f"Bearer {os.environ['TEAM_TOKEN']}"}

    async def task(inputs: TaskInput, log: Log) -> Output:
        async with httpx.AsyncClient(base_url=url, headers=auth, timeout=60) as http:
            (await http.post("/__reset")).raise_for_status()
            session = await open_session(url, password)
            try:
                summary = await run_task(inputs.text, session, log, BUDGET_S)
            finally:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(session.close(), 5)
            check = await http.post("/__check", json=inputs.practice)
            check.raise_for_status()
            return Output(summary, log.path, check.json())
    return task


def fake_task():
    """`run_task` over FakeSession on tests/fixtures/elements/ and an unscripted FakeLLM: no network, no keys."""
    from tests.fakes.fake_app import FakeSession
    from tests.fakes.llm import FakeLLM
    elements = Path(__file__).parents[1] / "tests" / "fixtures" / "elements"
    for tier in ("FAST", "VLM", "PLANNER"):  # FakeLLM ignores the id, but the client asks for one
        os.environ.setdefault(f"MODEL_{tier}", f"fake/{tier.lower()}")

    async def task(inputs: TaskInput, log: Log) -> Summary:
        session = FakeSession("inicio", {}, elements)
        with tempfile.TemporaryDirectory() as memory:
            return await run_task(inputs.text, session, log, 30.0, llm=FakeLLM(), memory=memory,
                                  perceive=lambda fb: session.elements)
    return task
