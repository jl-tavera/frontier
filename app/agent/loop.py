"""Stub: F3 overwrites this file with the real executor."""
from app.contracts import Session, Summary
from app.log import Log


async def run_task(task: str, session: Session, log: Log, budget_s: float) -> Summary:
    return Summary("terminada", "stub: tarea recibida, sin ejecutar", {"task": task})
