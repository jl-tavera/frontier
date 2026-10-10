"""The executor's tools (solution §3.1): plain async Python that names targets, never coordinates, and returns
the observed Effect instead of raising on a miss.

Low: click, type, key, screenshot. Mid: click_text, fill_field, read_region, wait_for. High: go_to.
Mapped edges replay through `replay_edge`; everything else observes through `observe` and grounds through
`replay_target`, perceiving only when the snapshot doesn't hold the target."""
import asyncio
import time
import unicodedata
from collections import deque

from app.contracts import BBox, Effect, Element, Kind, Perceive, Session, Target
from app.memory.appmap import AppMap
from app.memory.drift import Drift
from app.memory.fingerprint import cell
from app.perception.ground import elements_text
from app.perception.ocr import elements as ocr_elements
from app.warm.replay import Observation, observe, replay_edge, replay_target

NO_CELL = (-1, -1)  # the model names a label only, so C4's cell rung never guesses


def _centre(b: BBox) -> tuple[int, int]:
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def _fold(s: str) -> str:
    """Case, accents and runs of whitespace don't count, as in C4's label match."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _changed(a, b) -> BBox | None:
    ys, xs = (a[:, :, :3] != b[:, :, :3]).any(axis=2).nonzero()
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None


def _cut(fb, b: BBox):
    return fb[b[1]:b[3] + 1, b[0]:b[2] + 1]


class Tools:
    def __init__(self, session: Session, m: AppMap, task: str = "", *, perceive: Perceive = ocr_elements):
        self.session, self.m, self.task, self.perceive = session, m, _fold(task), perceive
        self.allow: set[str] = set()  # folded labels a stored procedure for this task may click past the denylist
        self.last: tuple[Target, tuple[int, int]] | None = None  # click_text's grounded target and xy, for F4's edges
        self.drift: Drift | None = None  # D's repair ladder for an edge replay can't land; F5 sets it

    def _observe(self) -> Observation:
        return observe(self.session.fb, self.m, perceive=self.perceive)

    def _perceived(self) -> Observation:
        fb = self.session.fb
        return Observation(None, self.perceive(fb), "perception", (fb.shape[1], fb.shape[0]))

    async def _act(self, act, detail: str) -> Effect:
        """Run the action, settle, and report what changed and where it landed."""
        t0, before = time.monotonic(), self.session.fb.copy()
        await act()
        await self.session.settle()
        return Effect(True, _changed(before, self.session.fb), self._observe().node, None, detail,
                      (time.monotonic() - t0) * 1000)

    def _fail(self, t0: float, detail: str, signal: str | None = None, screen: str | None = None) -> Effect:
        return Effect(False, None, screen, signal, detail, (time.monotonic() - t0) * 1000)

    def _ground(self, label: str, role: Kind) -> tuple[Element | None, Observation]:
        """The element the label names: the observed snapshot first, perception only when that misses it."""
        target, obs = Target(label, role, NO_CELL), self._observe()
        if (bbox := replay_target(target, obs)) is None and obs.source == "snapshot":
            obs = self._perceived()
            bbox = replay_target(target, obs)
        return next((e for e in obs.elements if e.bbox == bbox), None), obs

    def _denied(self, *labels: str) -> bool:
        # lazy: "named" = the label is a substring of the task; ask the parse for the targets once F3 has them
        return any(self.m.denied(x) and _fold(x) not in self.task and _fold(x) not in self.allow for x in labels)

    # low

    async def click(self, x: int, y: int) -> Effect:
        return await self._act(lambda: self.session.click(x, y), f"click {x},{y}")

    async def type(self, text: str) -> Effect:
        return await self._act(lambda: self.session.type(text), "type")

    async def key(self, name: str) -> Effect:
        return await self._act(lambda: self.session.key(name), f"key {name}")

    async def screenshot(self) -> Effect:
        """The screen as text for the planner: its node and element list, no coordinates."""
        t0, obs = time.monotonic(), self._observe()
        return Effect(True, None, obs.node, None, elements_text(obs.elements), (time.monotonic() - t0) * 1000)

    # mid

    async def click_text(self, label: str) -> Effect:
        t0 = time.monotonic()
        if self._denied(label):
            return self._fail(t0, f"denied: {label}")
        e, obs = self._ground(label, "button")
        if e is None:
            return self._fail(t0, f"not found: {label}", "S1", obs.node)
        if self._denied(e.text):  # a fuzzy match may land on a denied label
            return self._fail(t0, f"denied: {e.text}", screen=obs.node)
        self.last = Target(e.text, e.kind, cell(e.bbox, *obs.size)), _centre(e.bbox)
        return await self._act(lambda: self.session.click(*self.last[1]), f"click_text {e.text}")

    async def fill_field(self, label: str, value: str) -> Effect:
        """Click the label's paired input; Tab when no caret or text showed in it; then type."""
        t0 = time.monotonic()
        if self._denied(label):
            return self._fail(t0, f"denied: {label}")
        e, obs = self._ground(label, "text")
        box = next((x for x in obs.elements if e and x.id == e.paired_input), None)
        if box is None:
            return self._fail(t0, f"no input for: {label}", "S1", obs.node)
        if self._denied(e.text):
            return self._fail(t0, f"denied: {e.text}", screen=obs.node)
        before = self.session.fb.copy()
        await self.session.click(*_centre(box.bbox))
        await self.session.settle()
        # lazy: one frame decides, so a caret caught off its blink presses Tab; diff two frames if that bites
        if _changed(_cut(before, box.bbox), _cut(self.session.fb, box.bbox)) is None:
            await self.session.key("tab")
        effect = await self._act(lambda: self.session.type(value), f"fill_field {label}")
        effect.cost_ms = (time.monotonic() - t0) * 1000
        return effect

    async def read_region(self, bbox: BBox) -> Effect:
        """The perceived text inside bbox, one element per line in reading order; the snapshot holds mapping-time data."""
        t0, obs = time.monotonic(), self._perceived()
        inside = [e for e in obs.elements if e.text and bbox[0] <= e.bbox[0] and bbox[1] <= e.bbox[1]
                  and e.bbox[2] <= bbox[2] and e.bbox[3] <= bbox[3]]
        text = "\n".join(e.text for e in sorted(inside, key=lambda e: (e.bbox[1], e.bbox[0])))
        return Effect(True, None, None, None, text, (time.monotonic() - t0) * 1000)

    async def wait_for(self, text: str, timeout: float = 8.0) -> Effect:
        """Perceived, not the snapshot: the text awaited is new on screen (a message, a saved record)."""
        t0, want = time.monotonic(), _fold(text)
        while True:
            await self.session.settle()
            if any(want in _fold(e.text) for e in self._perceived().elements):
                return Effect(True, None, None, None, f"saw {text}", (time.monotonic() - t0) * 1000)
            if time.monotonic() - t0 >= timeout:
                return self._fail(t0, f"timeout waiting for: {text}")
            await asyncio.sleep(0.5)

    # high

    async def go_to(self, screen: str) -> Effect:
        """Follow the map's edges from the current node, each replayed at its stored xy."""
        t0, want = time.monotonic(), _fold(screen)
        goal = (screen if screen in self.m.nodes else None) or next(
            (n for n, node in self.m.nodes.items() if _fold(node["title"]) == want), None)
        here = self._observe().node
        if goal is None or here is None:
            return self._fail(t0, f"unknown screen: {screen if goal is None else 'current'}", screen=here)
        path = self._path(here, goal)
        if path is None:
            return self._fail(t0, f"no path {here} -> {goal}", screen=here)
        effect = Effect(True, None, here, None, "already there", 0.0)
        for edge in path:
            if not (effect := await self._edge(edge)).ok:
                break
        effect.cost_ms = (time.monotonic() - t0) * 1000
        return effect

    async def _edge(self, edge: dict) -> Effect:
        """The stored xy first; the ladder when it misses (or for a menu item, which replay_edge never opens), then
        rung 3's plan if it made one. A failure here is the exhausted ladder: the executor hands off to F4."""
        if self.drift is None or not edge["action"]["params"].get("menu"):
            effect = await replay_edge(edge, self.session.fb, self.session, self.m, perceive=self.perceive)
            if effect.ok or self.drift is None:
                return effect
        effect = await self.drift.step(self.session, edge)
        self.m = self.drift.m  # a rung 0 opened a new epoch
        plan, self.drift.plan = self.drift.plan, None
        if not effect.ok and plan:
            for eid in plan:
                if not (effect := await self.drift.step(self.session, self.m.edges[eid], ladder=False)).ok:
                    break
        return effect

    def _path(self, src: str, goal: str) -> list[dict] | None:
        """BFS over edges that have landed somewhere."""
        prev, todo = {src: None}, deque([src])
        while todo:
            n = todo.popleft()
            if n == goal:
                path = []
                while prev[n]:
                    path.append(prev[n])
                    n = prev[n]["from"]
                return path[::-1]
            for e in self.m.edges.values():
                if e["from"] == n and e["to"] and e["to"] not in prev:
                    prev[e["to"]] = e
                    todo.append(e["to"])
        return None
