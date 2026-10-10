"""`uv run -m harness evidence <jsonl...>`: the markdown evidence table (H2).
`uv run -m harness mutate <kind> [--fake] [--tasks ...]`: the mutation suite (H1)."""
import argparse
import sys
from pathlib import Path

from harness.evidence import table


def main(argv=None) -> int:
    from harness import mutate
    p = argparse.ArgumentParser(prog="harness")
    sub = p.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser("evidence", help="markdown table: each behaviour confirmed with file:line, or assumed")
    ev.add_argument("logs", nargs="+")
    mu = sub.add_parser("mutate", help="one E §6.1 change, the task suite, and its expected log lines")
    mu.add_argument("kind", choices=sorted(mutate.TABLE))
    mu.add_argument("--fake", action="store_true", help="the golden map on the fake app, scripted models")
    mu.add_argument("--tasks", nargs="+", help="task trees (default: synth/tasks and the official five; "
                                               "tests/harness/tasks with --fake)")
    a = p.parse_args(argv)
    if a.cmd == "evidence":
        print(table(a.logs))
        return 0
    from synth.gen import PRUEBAS
    tasks = a.tasks or ([Path(__file__).parents[1] / "tests" / "harness" / "tasks"] if a.fake
                        else ["synth/tasks", PRUEBAS])
    return mutate.suite(a.kind, [t for t in tasks if Path(t).exists()], a.fake)


if __name__ == "__main__":
    sys.exit(main())
