"""JSONL event log. Keys: ts, task_id, tool, args, screen_id, diff, outcome, signal, rung, cost_ms.
Event names: task.start, task.end, step, drift, sync.*."""
import json
import time
from pathlib import Path


class Log:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def event(self, event: str, **fields) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "event": event, **fields}, ensure_ascii=False, default=str) + "\n")
