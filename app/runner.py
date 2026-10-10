"""In-process task runner: one asyncio task per job, state in a dict, lost on restart."""
import asyncio
import os
import uuid
from pathlib import Path

from app.agent.loop import run_task
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
    session = await open_session(url, password)
    try:
        summary = await run_task(task, session, log, BUDGET_S)
    finally:
        await session.close()
    tasks[task_id].update(status=summary.status, summary=summary.text, data=summary.data)
