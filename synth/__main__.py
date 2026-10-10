"""`uv run -m synth gen|check|eval`: the synthetic practice-task suite (Spec S)."""
import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from synth.gen import TODAY, CheckError, check, gen


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="synth")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="write one practice-task JSON per template instance")
    g.add_argument("--out", default="synth/tasks/generated")
    g.add_argument("--per-template", type=int, default=2)
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--paraphrase", type=int, default=0, metavar="K", help="K fast-model rewrites of each instruccion")
    c = sub.add_parser("check", help="validate every task JSON under a directory against the cache")
    c.add_argument("dir")
    e = sub.add_parser("eval", help="run every task JSON plus the official five through run_task and score them")
    mode = e.add_mutually_exclusive_group()
    mode.add_argument("--fake", dest="mode", action="store_const", const="fake", default="fake")
    mode.add_argument("--live", dest="mode", action="store_const", const="live")
    e.add_argument("--tasks", nargs="+", default=["synth/tasks"])
    e.add_argument("--repeat", type=int, default=1)
    e.add_argument("--baseline")
    e.add_argument("--publish", metavar="SERVICE_URL")
    e.add_argument("--name")
    for s in (g, c):
        s.add_argument("--cache", default="memory/cache.sqlite")
        s.add_argument("--today", default=TODAY, help="the app's Hoy: date, ISO")
    a = p.parse_args(argv)
    if a.cmd == "eval":
        return _eval(a)
    try:
        if a.cmd == "gen":
            print(f"wrote {len(gen(a.cache, a.out, a.per_template, a.seed, a.today, a.paraphrase))} tasks to {a.out}")
        else:
            n = check(a.dir, a.cache, a.today)
            print(f"generated: {n['generated']}, explored: {n['explored']}"
                  + (f", official: {n['official']}" if n["official"] else ""))
    except CheckError as e:
        print(e, file=sys.stderr)
        return 1
    return 0



def _eval(a: argparse.Namespace) -> int:
    from synth import eval as ev
    for t in a.tasks:
        if not Path(t).exists():
            print(f"no tasks at {t}, skipped", file=sys.stderr)
    trees = dict.fromkeys(Path(t).resolve() for t in [*a.tasks, ev.PRUEBAS] if Path(t).exists())
    task = ev.live_task() if a.mode == "live" else ev.fake_task()
    name = a.name or f"{a.mode}-{datetime.now():%Y%m%d-%H%M}"
    report = asyncio.run(ev.run(ev.load(trees), task, name=name, repeat=a.repeat))
    code = ev.show(report, a.baseline)
    path = ev.save(report)
    print(f"wrote {path}")
    if a.publish:
        ev.publish(path, a.publish)
        print(f"published to {a.publish.rstrip('/')}/evals")
    return code


if __name__ == "__main__":
    sys.exit(main())
