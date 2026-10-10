"""`uv run -m harness evidence <jsonl...>`: the markdown evidence table (H2)."""
import argparse

from harness.evidence import table


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="harness")
    sub = p.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser("evidence", help="markdown table: each behaviour confirmed with file:line, or assumed")
    ev.add_argument("logs", nargs="+")
    a = p.parse_args(argv)
    print(table(a.logs))


if __name__ == "__main__":
    main()
