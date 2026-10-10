"""In-process task runner: one asyncio task per job, state in a dict, lost on restart."""
import asyncio
import contextlib
import os
import uuid
from pathlib import Path

from app.agent.loop import run_task
from app.contracts import Summary
from app.log import Log
from app.rfb.session import open_session

BUDGET_S = 270.0
tasks: dict[str, dict] = {}
_running: set[asyncio.Task] = set()  # keep a reference so the job isn't garbage-collected mid-run


def start(task: str, url: str, password: str) -> str:
    task_id = str(uuid.uuid4())
    tasks[task_id] = {"task_id": task_id, "status": "en_curso", "summary": None, "data": {}}
    job = asyncio.create_task(_run(task_id, task, url, password))
    _running.add(job)
    job.add_done_callback(_running.discard)
    return task_id


async def _run(task_id: str, task: str, url: str, password: str) -> None:
    log = Log(Path(os.environ.get("LOG_DIR", "logs")) / f"{task_id}.jsonl")
    guard = asyncio.timeout(BUDGET_S)
    try:
        log.event("task.start", task_id=task_id, args={"task": task})
        async with guard:
            summary = await _work(task, url, password, log)
    except Exception as e:  # a worker's own TimeoutError is an error; only the guard's is an overrun
        summary = Summary("fallida", f"presupuesto agotado ({BUDGET_S:g} s): la tarea no terminó a tiempo"
                          if guard.expired() else f"error: {type(e).__name__}: {e}")
    tasks[task_id].update(status=summary.status, summary=summary.text, data=summary.data)
    log.event("task.end", task_id=task_id, outcome=summary.status, args={"summary": summary.text})


async def _work(task: str, url: str, password: str, log: Log) -> Summary:
    deadline = asyncio.get_running_loop().time() + BUDGET_S
    session = await open_session(url, password)
    try:
        # The worker gets what is left after connecting, so its own wrap-up lands before the guard fires.
        return await run_task(task, session, log, deadline - asyncio.get_running_loop().time())
    finally:
        with contextlib.suppress(Exception):  # a dead socket must not hold the task in en_curso or eat its summary
            await asyncio.wait_for(session.close(), 5)
