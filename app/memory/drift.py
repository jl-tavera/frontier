"""Drift (Appendix E §4.5): the checks after every step and the ladder (rung 0 new epoch, 1 re-ground in place,
2 re-explore the node, 3 replan, 4 rank-down, then `rejoin`); and the §6.1 mutations that rehearse the 15:30 change
offline."""
import asyncio
import time
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Awaitable, Callable

import numpy as np

from app.contracts import Effect, Element, Perceive, Session, Target
from app.log import Log
from app.memory.appmap import SAME, AppMap
from app.memory.fingerprint import Fingerprint, cell, fingerprint, jaccard, split_title
from app.memory.prewarm import _xy, prewarm
from app.perception.ground import FUZZY, _fold, _similar, ground

CONFIDENT, MASS_DRIFT, MASS, S4_RUN = 0.8, 0.4, 0.2, 3
REIDENTIFY, CANDIDATES = 0.30, 5
PREWARM_S, REEXPLORE_S, REPLAN_S = 45.0, 30.0, 15.0  # rung 0's pre-warm, rung 2, rung 3
# decide(elements, old_action) and vlm(fb, elements, old_action) -> (element id or None, confidence); F wires them
Choice = Callable[..., tuple[int | None, float]]


class Drift:
    """One task's checks over one map. Holds the run of consecutive S4s (the second half of S7) and whether the
    task is off the graph until it rejoins."""

    def __init__(self, m: AppMap, log: Log, perceive: Perceive, *, decide: Choice, vlm: Choice,
                 which_node: Callable[[np.ndarray, list[dict]], str | None],
                 replan: Callable[[AppMap, dict, str | None], Awaitable[list | None]]):
        self.m, self.log, self.perceive, self.decide, self.vlm = m, log, perceive, decide, vlm
        self.which_node, self.replan = which_node, replan
        self.s4 = 0
        self.epoch: str | None = None  # the signal that opened this task's epoch (rung 0)
        self.lost: str | None = None  # the signal that left the graph, until rejoin
        self.plan: list | None = None  # rung 3's answer, for F to follow

    def _line(self, t0: float, signal: str, rung: int | None, via=None, confidence=None, before=None, after=None):
        self.log.event("drift", signal=signal, rung=rung, via=via, confidence=confidence, before=before, after=after,
                       cost_ms=(time.monotonic() - t0) * 1000)

    def _effect(self, t0: float, ok: bool, screen: str | None, signal: str | None, detail: str) -> Effect:
        # changed_bbox stays None: S2 is read off the fingerprint, not the pixels
        return Effect(ok, None, screen, signal, detail, (time.monotonic() - t0) * 1000)

    async def start(self, session: Session) -> str | None:
        """S5 when the title's version is none the map has seen, else S7 when under 40 % of the root's menu atoms
        show. Either one runs rung 0."""
        t0, fp = time.monotonic(), fingerprint(self.perceive(session.fb), session.w, session.h)
        menu = set(self.m.nodes[self.m.root]["appearances"][0]["menu"]) if self.m.root else set()
        if self.m.titles and fp.version not in {split_title(t)[1] for t in self.m.titles}:
            signal = "S5"
        elif menu and len(menu & fp.menu) / len(menu) < MASS_DRIFT:
            signal = "S7"
        else:
            return None
        await self._rung0(session, t0, signal, fp)
        return signal

    async def _rung0(self, session: Session, t0: float, signal: str, fp: Fingerprint) -> None:
        """A new epoch inheriting this one (nodes stale, edges inherited), the current node found in it, then the
        pre-warm again. `self.m` is the new epoch's map from here on."""
        old, self.epoch, self.s4, self.lost = self.m, signal, 0, signal
        self.m = old.inherit(f"{fp.app_id} {fp.version}" if fp.version else fp.app_id)
        self._line(t0, signal, 0, "inherit", None, old.version, self.m.version)
        if self._known(self.perceive(session.fb), session) is None:
            # no old node is this screen: the new one prewarm creates becomes the root, so S7 next task measures
            # the menu bar as it is now, not the one that just drifted
            self.m.root = None
        await prewarm(session, self.m, self.perceive, budget=PREWARM_S)

    def _known(self, els: list[Element], session: Session, rejoin: bool = True) -> str | None:
        """The known node on screen: a same match, else (in a new epoch) a stale node re-identified. The first one
        after a rung 0 or an S4 logs `rejoin`."""
        fp = fingerprint(els, session.w, session.h)
        match = self.m.identify(fp)
        node = match.node_id if match.kind == "same" else None
        if node is None and match.kind in ("new", "ambiguous"):
            node = self._reidentify(fp, els, session.fb)
        if rejoin:
            self._rejoin(node)
        return node

    def _reidentify(self, fp: Fingerprint, els: list[Element], fb) -> str | None:
        """≤ 5 inherited nodes not yet seen in this epoch at Jaccard 0.30–0.90, closest title first, put to the VLM ("none" allowed). The pick gains
        this version's appearance."""
        t0, title = time.monotonic(), " · ".join(fp.band)
        near = [n for n in self.m.nodes.values() if all(a["version"] != self.m.version for a in n["appearances"])
                and REIDENTIFY <= max(jaccard(a["atoms"], fp.atoms) for a in n["appearances"]) < SAME]
        if not near:
            return None
        near = sorted(near, key=lambda n: SequenceMatcher(None, n["title"], title).ratio(), reverse=True)[:CANDIDATES]
        candidates = [{"id": n["id"], "title": n["title"], "description": n["description"],
                       "ref_png": next((str(self.m.file(a, a["ref_png"])) for a in n["appearances"] if a["ref_png"]), None)}
                      for n in near]
        if (pick := self.which_node(fb, candidates)) not in {n["id"] for n in near}:
            return None
        self.m.upsert_node(fp, els, fb, pick)
        self._line(t0, self.epoch, 0, "reidentify", None, None, pick)
        return pick

    def _rejoin(self, node: str | None) -> None:
        if node and self.lost:
            self.log.event("rejoin", signal=self.lost, node=node)
            self.lost = None

    async def step(self, session: Session, edge: dict, ladder: bool = True) -> Effect:
        """Open the edge's menu, ground its target, act, then check blocker → overlay → data edge → drift.
        A target not found climbs rungs 1 → 2 → 3; `ladder=False` is rung 2's one retry, which climbs none."""
        t0 = time.monotonic()
        old = edge["action"]["target"]["appearances"][0]
        target = Target(old["label"], old["role"], tuple(old["cell"]))
        src = fingerprint(els := self.perceive(session.fb), session.w, session.h)
        if (menu := edge["action"]["params"].get("menu")) and (opener := ground(Target(menu, "menu", (0, 0)), els)):
            await session.click(*_xy(opener))
            await session.settle()
            els = self.perceive(session.fb)

        hit, via, confidence = ground(target, els, session.w, session.h), None, None
        if hit is None or _fold(hit.text) != _fold(target.label):
            if edge.get("data"):
                return self._effect(t0, False, None, None, "find")  # a row, not drift: F runs the find procedure
            if not ladder:
                return self._effect(t0, False, None, "S1", "target not found")
            hit, via, confidence = self._rung1(session, target, edge, els, hit)
            if hit is None:
                self._line(t0, "S1", 1, confidence=confidence, before=target.label)
                if (found := await self.rung2(session, "S1", target.label, edge)) is not None:
                    if (effect := await self.step(session, found, ladder=False)).ok:
                        return replace(effect, signal="S1", detail="rung 2 via reexplore",
                                       cost_ms=(time.monotonic() - t0) * 1000)
                await self._rung3(t0, edge, "S1", edge["from"])
                return self._rank_down(t0, edge, "S1", "target not found")
        await session.click(*_xy(hit))
        await session.settle()

        fp = fingerprint(after := self.perceive(session.fb), session.w, session.h)
        match = self.m.identify(fp)
        if match.kind in ("blocker", "overlay"):
            if match.kind == "blocker":
                self.log.event("blocker", buttons=match.labels)
            await session.key("esc")
            await session.settle()
            fp = fingerprint(after := self.perceive(session.fb), session.w, session.h)
        node = self._known(after, session)
        if edge.get("data") and node != edge["to"]:
            return self._effect(t0, False, node, None, "find")
        if fp.band == src.band and fp.atoms == src.atoms and edge["from"] != edge["to"]:
            return self._rank_down(t0, edge, "S2", "no change")
        if node:
            self.s4 = 0
        if node and edge["to"] in (node, None):
            if via:
                look = {"version": self.m.version, "label": hit.text, "role": hit.kind,
                        "cell": list(cell(hit.bbox, session.w, session.h)), "xy": list(_xy(hit))}
                edge["action"]["target"]["appearances"].insert(0, look)  # the old look stays, even this version's
                self._line(t0, "S1", 1, via, confidence, target.label, hit.text)
            self._land(edge, node)
            return self._effect(t0, True, node, "S1" if via else None, f"rung 1 via {via}" if via else "ok")
        if node:
            self._line(t0, "S3", 1, "landing", None, edge["to"], node)
            self._land(edge, node)
            return self._effect(t0, False, node, "S3", "retargeted")
        self.s4 += 1
        if self.s4 == S4_RUN:
            eid = next(k for k, e in self.m.edges.items() if e is edge)
            await self._rung0(session, t0, "S7", fp)
            return self._rank_down(t0, self.m.edges[eid], "S4", "unmatched screen")  # the old epoch stays frozen
        # lazy: Esc as "back to the previous node"; replay the reverse edge when an app's screens don't close on Esc
        await session.key("esc")
        await session.settle()
        here = self._known(self.perceive(session.fb), session, rejoin=False)
        await self._rung3(t0, edge, "S4", here)
        effect = self._rank_down(t0, edge, "S4", "unmatched screen")
        self.lost = self.lost or "S4"
        self._rejoin(here)
        return effect

    def _rung1(self, session: Session, target: Target, edge: dict, els: list[Element], hit: Element | None):
        """Fuzzy label → same role + cell (C4's ground already tried both) → decide at ≥ 0.8 → the VLM."""
        if hit is not None:
            # lazy: names the via after the fact from C4's one ground call; ground per rung if a log needs both scores
            return hit, "fuzzy" if _similar(_fold(target.label), _fold(hit.text)) >= FUZZY else "cell", None
        by_id = {e.id: e for e in els}
        eid, confidence = self.decide(els, edge["action"])
        if confidence >= CONFIDENT and eid in by_id:
            return by_id[eid], "decide", confidence
        eid, confidence = self.vlm(session.fb, els, edge["action"])
        return (by_id[eid], "vlm", confidence) if eid in by_id else (None, None, confidence)

    async def rung2(self, session: Session, signal: str, label: str, edge: dict | None = None) -> dict | None:
        """Mark the node on screen stale and pre-warm it alone, ≤ 30 s. Returns the edge to try: `edge` when its
        menu path was seen again, else one seen now with `label`. F calls it too when `route` finds no edge."""
        t0 = time.monotonic()
        await session.key("esc")  # the menu rung 1 left open
        await session.settle()
        if node := self._known(self.perceive(session.fb), session):
            self.m.nodes[node]["stale"] = True
        before = {eid: e["action"]["target"]["appearances"][0] for eid, e in self.m.edges.items()}
        await prewarm(session, self.m, self.perceive, budget=REEXPLORE_S)
        seen = [e for eid, e in self.m.edges.items() if e["action"]["target"]["appearances"][0] is not before.get(eid)]
        found = next((e for e in seen if e is edge), None) or next(
            (e for e in seen if _fold(e["action"]["target"]["appearances"][0]["label"]) == _fold(label)), None)
        after = found["action"]["target"]["appearances"][0]["label"] if found else None
        self._line(t0, signal, 2, "reexplore", None, label, after)
        return found

    async def _rung3(self, t0: float, edge: dict, signal: str, here: str | None) -> None:
        """Mark the edge broken and ask for one new plan from `here`, ≤ 15 s; F follows `self.plan`."""
        edge["broken"] = True
        try:
            self.plan = await asyncio.wait_for(self.replan(self.m, edge, here), REPLAN_S)
        except TimeoutError:
            self.plan = None
        self._line(t0, signal, 3, "replan", None, edge["to"], self.plan)

    def _land(self, edge: dict, node: str) -> None:
        """A confirmed landing: `to` is where the action leads now, ok++, and S6 when it leads to two places."""
        edge.update(to=node, inherited=False, broken=False, ok=edge["ok"] + 1, last_ok=time.time())
        edge["outcomes"][node] = edge["outcomes"].get(node, 0) + 1
        total = sum(edge["outcomes"].values())
        if len(heavy := [n for n, c in edge["outcomes"].items() if c / total >= MASS]) > 1:
            self._line(time.monotonic(), "S6", None, after=heavy)

    def _rank_down(self, t0: float, edge: dict, signal: str, detail: str) -> Effect:
        """Rung 4: fail++, never deleted."""
        edge["fail"] += 1
        self._line(t0, signal, 4, "rank_down", None, edge["fail"] - 1, edge["fail"])
        return self._effect(t0, False, None, signal, detail)


FACTURAS = "inicio|click|Cartera › Facturas"


def _retitle(els: list[Element]) -> list[Element]:
    return [replace(e, text=e.text.replace("v3.9", "v4.0")) if e.kind == "title" else e for e in els]


def _junk(m: AppMap, node_ids, only_menu: bool = False) -> None:
    for nid in node_ids:
        for a in m.nodes[nid]["appearances"]:
            junk = set(a["menu"] if only_menu else a["atoms"])
            a["atoms"], a["menu"] = [f"{x}~" if x in junk else x for x in a["atoms"]], [f"{x}~" for x in a["menu"]]


def mutate(m: AppMap, kind: str) -> Callable[[list[Element]], list[Element]]:
    """The E §6.1 change `kind` applied to the golden SIGECOM map in place. Drift is (map, screen), and a version
    bump or a data state can only be shown on the screen side, so it returns the transform for the live elements."""
    edge = m.edges[FACTURAS]
    look = edge["action"]["target"]["appearances"][0]
    if kind == "rename":
        look["label"] = "Facturación"
    elif kind == "removed":
        look["label"] = "Zzzz"
    elif kind == "persistent":  # the item replaced on the screen too, so no rung repairs it and every task ranks down
        look["label"] = "Zzzz"
        return lambda els: [replace(e, text="Recaudos") if e.kind == "menu" and e.text == "Facturas" else e for e in els]
    elif kind == "landing_mismatch":
        edge["to"] = "clientes"
    elif kind == "menu_moved":
        m.edges = {k: e for k, e in m.edges.items() if e["to"] != "facturas"}
    elif kind == "unknown_screen":
        _junk(m, ["facturas"])
    elif kind == "shifted_cell":
        look["cell"][0] += 3
    elif kind == "data_state":
        def page2(e: Element) -> Element:  # page 2 of the list filtered by Cliente, as operador2
            for old, new in (("FV-10159", "FV-10233"), ("Página 1", "Página 2"), ("operador", "operador2")):
                e = replace(e, text=e.text.replace(old, new))
            return replace(e, text="Ruiz") if e.kind == "field" else e
        return lambda els: [page2(e) for e in els]
    elif kind == "version_bump":
        return _retitle
    elif kind in ("redesign", "redesign_silent"):
        # the menu bar redone, the bodies keep their labels: a junked whole screen is Jaccard 0 against every
        # stale node, and only one that keeps some can be re-identified in the 0.30–0.90 band
        _junk(m, m.nodes, only_menu=True)
        if kind == "redesign":
            headers = {"Cliente": "Tercero", "Valor": "Total"}
            return lambda els: [replace(e, text=headers.get(e.text, e.text)) if e.kind == "header" else e
                                for e in _retitle(els)]
    else:
        raise ValueError(f"unknown mutation {kind!r}")
    return lambda els: els
