"""Pre-warm (Appendix E §4.3 step 2): open each top menu once and record its items as edges, menus only."""
import time
from typing import Callable

from app.contracts import Element, Perceive, Session, Target
from app.memory.appmap import AppMap
from app.memory.fingerprint import cell


def _xy(e: Element) -> tuple[int, int]:
    return (e.bbox[0] + e.bbox[2]) // 2, (e.bbox[1] + e.bbox[3]) // 2


async def prewarm(session: Session, m: AppMap, perceive: Perceive, *, clock: Callable[[], float] = time.monotonic,
                  budget: float = 45.0, visit: bool = False) -> None:
    """Click → settle → elements → Esc on every top menu not denylisted, recording `menu → item` edges with
    `to` unknown (None) from the screen it started on. No menu is opened once `budget` seconds have passed.

    `visit` is W1's dev-time full mapping run: it also clicks every item that is not denylisted and records its
    landing node (snapshot, ref_png, crops) and the confirmed edge, pressing Esc when the landing is unconfirmed
    and walking back to the start screen along a confirmed edge into it otherwise."""
    t0 = clock()
    elements = perceive(session.fb)
    if (src := m.locate(elements, session.w, session.h, session.fb)) is None:
        return  # a dialog or an ambiguous screen: no node to hang the edges on
    top = {e.text for e in elements if e.kind == "menu"}
    for menu in [e for e in elements if e.kind == "menu" and not m.denied(e.text)]:
        if clock() - t0 >= budget:
            break
        await session.click(*_xy(menu))
        await session.settle()
        # lazy: a cascade item's path keeps only its top menu; record the submenu header when cascades open on hover
        items = [(_xy(e), Target(e.text, e.kind, cell(e.bbox, session.w, session.h))) for e in perceive(session.fb)
                 if e.kind == "menu" and e.text not in top and not m.denied(e.text)]
        for xy, target in items:
            m.upsert_edge(src, "click", target, xy, None, {"menu": menu.text})
        await session.key("esc")
        await session.settle()
        if not visit:
            continue
        for xy, target in items:
            if clock() - t0 >= budget:
                return
            to = await _click_item(session, m, perceive, src, menu.text, target, xy)
            if to is None:
                await session.key("esc")
                await session.settle()
            elif to != src and (back := next((e for e in m.edges.values() if e["to"] == src), None)):
                # lazy: walks back along any confirmed menu edge into src, as SIGECOM's menu bar is on every screen;
                # go_to src when an app's menus are per screen
                look = back["action"]["target"]["appearances"][0]
                await _click_item(session, m, perceive, to, back["action"]["params"]["menu"],
                                  Target(look["label"], look["role"], tuple(look["cell"])), look["xy"])


async def _click_item(session: Session, m: AppMap, perceive: Perceive, src: str, menu: str, target: Target, xy) -> str | None:
    """Open the menu by its label, click the item and learn the landing."""
    found = [e for e in perceive(session.fb) if e.kind == "menu" and e.text == menu]
    if not found:
        return None
    await session.click(*_xy(found[0]))
    await session.settle()
    await session.click(*xy)
    await session.settle()
    return m.learn(src, "click", target, xy, perceive(session.fb), session.w, session.h, session.fb, {"menu": menu})
