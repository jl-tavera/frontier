"""JSONL event log, each line also printed to stdout so `railway logs` shows it (the file dies with the container).
Keys: ts, task_id, tool, args, screen_id, diff, outcome, signal, rung, cost_ms.
Event names: task.start, task.end, step, drift, sync.*."""
import json
import sys
import time
from pathlib import Path


class Log:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def event(self, event: str, **fields) -> None:
        # task_id defaults to the file's stem (runner names it <task_id>.jsonl) so stdout lines of overlapping tasks
        # stay apart; one write per line so events from worker threads never interleave.
        line = json.dumps({"ts": time.time(), "event": event, "task_id": self.path.stem, **fields},
                          ensure_ascii=False, default=str)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
