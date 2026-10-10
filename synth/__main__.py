"""`uv run -m synth gen|check`: the synthetic practice-task suite (Spec S)."""
import argparse
import sys

from synth.gen import TODAY, CheckError, check, gen


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="synth")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="write one practice-task JSON per template instance")
    g.add_argument("--out", default="synth/tasks/generated")
    g.add_argument("--per-template", type=int, default=2)
    g.add_argument("--seed", type=int, default=1)
    c = sub.add_parser("check", help="validate every task JSON under a directory against the cache")
    c.add_argument("dir")
    for s in (g, c):
        s.add_argument("--cache", default="memory/cache.sqlite")
        s.add_argument("--today", default=TODAY, help="the app's Hoy: date, ISO")
    a = p.parse_args(argv)
    try:
        if a.cmd == "gen":
            print(f"wrote {len(gen(a.cache, a.out, a.per_template, a.seed, a.today))} tasks to {a.out}")
        else:
            n = check(a.dir, a.cache, a.today)
            print(f"generated: {n['generated']}, explored: {n['explored']}"
                  + (f", official: {n['official']}" if n["official"] else ""))
    except CheckError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
