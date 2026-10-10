"""`uv run -m app.warm map --url … --password … [--visit] [--budget S]`: build the app's map up front (W1);
with `--visit` it then seeds the cache. `uv run -m app.warm seed --url … --password … [--entities …]`: seed only (W3)."""
import argparse
import asyncio
import os
import time
from pathlib import Path

from app.log import Log
from app.memory.appmap import AppMap
from app.memory.prewarm import prewarm
from app.perception.grid import read_grid as ocr_grid
from app.perception.ocr import elements
from app.rfb.session import open_session
from app.warm.seed import ask_changelog, seed


def main(argv=None, *, connect=open_session, perceive=elements, clock=time.monotonic, read_grid=ocr_grid,
         tiebreak=ask_changelog) -> None:
    p = argparse.ArgumentParser(prog="app.warm")
    sub = p.add_subparsers(dest="cmd", required=True)
    cmd = sub.add_parser("map", help="pre-warm, or with --visit map every item and seed the cache")
    cmd.add_argument("--visit", action="store_true", help="also click every non-denylisted menu item")
    cmd.add_argument("--budget", type=float, help="seconds; default 600 with --visit, else 45")
    sd = sub.add_parser("seed", help="acquire every grid the map knows into <memory>/cache.sqlite")
    sd.add_argument("--entities", nargs="+", help="node ids; default every grid node")
    for c in (cmd, sd):
        c.add_argument("--url", required=True)
        c.add_argument("--password", required=True)
        c.add_argument("--memory", type=Path, default=Path("memory"))
    a = p.parse_args(argv)

    async def run():
        session = await connect(a.url, a.password)
        try:
            await session.settle()
            if a.cmd == "map":
                await map_app(session, a)
            if a.cmd == "seed" or a.visit:
                log = Log(Path(os.environ.get("LOG_DIR", "logs")) / "seed.jsonl")
                done = await seed(session, a.memory, log, perceive=perceive, read_grid=read_grid, tiebreak=tiebreak,
                                  entities=a.entities if a.cmd == "seed" else None)
                print(f"{a.memory / 'cache.sqlite'}: " + ", ".join(f"{e} {s}" for e, s in done.items()))
        finally:
            await session.close()

    async def map_app(session, a):
        budget = a.budget if a.budget is not None else 600.0 if a.visit else 45.0
        els = perceive(session.fb)
        titles = sorted((e for e in els if e.kind == "title"), key=lambda e: e.bbox[1])
        if not titles:
            raise SystemExit("no title on screen: cannot tell which app this is")
        m = AppMap.load(a.memory, titles[0].text, els, session.w, session.h)
        await prewarm(session, m, perceive, clock=clock, budget=budget, visit=a.visit)
        m.write_back()  # flushes the nodes seen again (snapshot, ref_png, crops) and writes map.json
        confirmed = sum(e["to"] is not None for e in m.edges.values())
        print(f"{m.dir / 'map.json'}: {len(m.nodes)} nodes, {confirmed} confirmed edges")

    asyncio.run(run())


if __name__ == "__main__":
    main()
