"""`uv run -m app.warm map --url … --password … [--visit] [--budget S]`: build the app's map up front (W1)."""
import argparse
import asyncio
import time
from pathlib import Path

from app.memory.appmap import AppMap
from app.memory.prewarm import prewarm
from app.perception.ocr import elements
from app.rfb.session import open_session


def main(argv=None, *, connect=open_session, perceive=elements, clock=time.monotonic) -> None:
    p = argparse.ArgumentParser(prog="app.warm")
    cmd = p.add_subparsers(dest="cmd", required=True).add_parser("map", help="pre-warm, or with --visit map every item")
    cmd.add_argument("--url", required=True)
    cmd.add_argument("--password", required=True)
    cmd.add_argument("--visit", action="store_true", help="also click every non-denylisted menu item")
    cmd.add_argument("--budget", type=float, help="seconds; default 600 with --visit, else 45")
    cmd.add_argument("--memory", type=Path, default=Path("memory"))
    a = p.parse_args(argv)
    budget = a.budget if a.budget is not None else 600.0 if a.visit else 45.0

    async def run():
        session = await connect(a.url, a.password)
        try:
            await session.settle()
            els = perceive(session.fb)
            titles = sorted((e for e in els if e.kind == "title"), key=lambda e: e.bbox[1])
            if not titles:
                raise SystemExit("no title on screen: cannot tell which app this is")
            m = AppMap.load(a.memory, titles[0].text, els, session.w, session.h)
            await prewarm(session, m, perceive, clock=clock, budget=budget, visit=a.visit)
            m.write_back()  # flushes the nodes seen again (snapshot, ref_png, crops) and writes map.json
        finally:
            await session.close()
        confirmed = sum(e["to"] is not None for e in m.edges.values())
        print(f"{m.dir / 'map.json'}: {len(m.nodes)} nodes, {confirmed} confirmed edges")

    asyncio.run(run())


if __name__ == "__main__":
    main()
