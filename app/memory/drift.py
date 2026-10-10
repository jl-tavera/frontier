"""Drift (Appendix E §4.5): the checks after every step, rung 1 re-grounding in place, rung 4 rank-down; and the
§6.1 mutations that rehearse the 15:30 change offline."""
import time
from dataclasses import replace
from typing import Callable

from app.contracts import Effect, Element, Perceive, Session, Target
from app.log import Log
from app.memory.appmap import AppMap
from app.memory.fingerprint import cell, fingerprint
from app.memory.prewarm import _xy
from app.perception.ground import FUZZY, _fold, _similar, ground

CONFIDENT, MASS_DRIFT, MASS, S4_RUN = 0.8, 0.4, 0.2, 3
# decide(elements, old_action) and vlm(fb, elements, old_action) -> (element id or None, confidence); F wires them
Choice = Callable[..., tuple[int | None, float]]


class Drift:
    """One task's checks over one map. Holds the run of consecutive S4s, the second half of S7."""

    def __init__(self, m: AppMap, log: Log, perceive: Perceive, *, decide: Choice, vlm: Choice):
        self.m, self.log, self.perceive, self.decide, self.vlm = m, log, perceive, decide, vlm
        self.s4 = 0

    def _line(self, t0: float, signal: str, rung: int | None, via=None, confidence=None, before=None, after=None):
        self.log.event("drift", signal=signal, rung=rung, via=via, confidence=confidence, before=before, after=after,
                       cost_ms=(time.monotonic() - t0) * 1000)

    def _effect(self, t0: float, ok: bool, screen: str | None, signal: str | None, detail: str) -> Effect:
        # changed_bbox stays None: S2 is read off the fingerprint, not the pixels
        return Effect(ok, None, screen, signal, detail, (time.monotonic() - t0) * 1000)

    def start(self, elements: list[Element], w: int, h: int) -> str | None:
        """S5 when the title's version is not the map's, else S7 when under 40 % of the root's menu atoms show.
        Rung 0 answers both (D5); here they are only logged."""
        t0, fp = time.monotonic(), fingerprint(elements, w, h)
        ours = None if self.m.version.startswith("epoch-") else self.m.version
        if fp.version != ours:
            self._line(t0, "S5", None, before=ours, after=fp.version)
            return "S5"
        menu = set(self.m.nodes[self.m.root]["appearances"][0]["menu"]) if self.m.root else set()
        if menu and (share := len(menu & fp.menu) / len(menu)) < MASS_DRIFT:
            self._line(t0, "S7", None, before=len(menu), after=round(share, 2))
            return "S7"
        return None

    async def step(self, session: Session, edge: dict) -> Effect:
        """Open the edge's menu, ground its target, act, then check blocker → overlay → data edge → drift."""
        t0, m = time.monotonic(), self.m
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
            hit, via, confidence = self._rung1(session, target, edge, els, hit)
            if hit is None:
                self._line(t0, "S1", 1, confidence=confidence, before=target.label)
                return self._rank_down(t0, edge, "S1", "target not found")
        await session.click(*_xy(hit))
        await session.settle()

        fp = fingerprint(self.perceive(session.fb), session.w, session.h)
        match = m.identify(fp)
        if match.kind in ("blocker", "overlay"):
            if match.kind == "blocker":
                self.log.event("blocker", buttons=match.labels)
            await session.key("esc")
            await session.settle()
            match = m.identify(fp := fingerprint(self.perceive(session.fb), session.w, session.h))
        node = match.node_id if match.kind == "same" else None
        if edge.get("data") and node != edge["to"]:
            return self._effect(t0, False, node, None, "find")
        if fp.band == src.band and fp.atoms == src.atoms and edge["from"] != edge["to"]:
            return self._rank_down(t0, edge, "S2", "no change")
        if node:
            self.s4 = 0
        if node and edge["to"] in (node, None):
            if via:
                look = {"version": m.version, "label": hit.text, "role": hit.kind,
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
            self._line(t0, "S7", None, before=S4_RUN, after=None)
        return self._rank_down(t0, edge, "S4", "unmatched screen")

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

    def _land(self, edge: dict, node: str) -> None:
        """A confirmed landing: `to` is where the action leads now, ok++, and S6 when it leads to two places."""
        edge.update(to=node, inherited=False, ok=edge["ok"] + 1, last_ok=time.time())
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


def _junk(m: AppMap, node_ids) -> None:
    for nid in node_ids:
        for a in m.nodes[nid]["appearances"]:
            a["atoms"], a["menu"] = [f"{x}~" for x in a["atoms"]], [f"{x}~" for x in a["menu"]]


def mutate(m: AppMap, kind: str) -> Callable[[list[Element]], list[Element]]:
    """The E §6.1 change `kind` applied to the golden SIGECOM map in place. Drift is (map, screen), and a version
    bump or a data state can only be shown on the screen side, so it returns the transform for the live elements."""
    edge = m.edges[FACTURAS]
    look = edge["action"]["target"]["appearances"][0]
    if kind == "rename":
        look["label"] = "Facturación"
    elif kind in ("removed", "persistent"):  # persistent: the same break, left unrepaired across tasks
        look["label"] = "Zzzz"
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
        _junk(m, m.nodes)
        if kind == "redesign":
            headers = {"Cliente": "Tercero", "Valor": "Total"}
            return lambda els: [replace(e, text=headers.get(e.text, e.text)) if e.kind == "header" else e
                                for e in _retitle(els)]
    else:
        raise ValueError(f"unknown mutation {kind!r}")
    return lambda els: els
