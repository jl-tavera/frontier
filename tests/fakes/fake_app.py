"""FakeSession: a Session over element-JSON screens. Written once by A1; later tickets build it with their own
screens and transitions and never edit it.

A screen is `<elements_dir>/<name>.json`, a list of Element dicts. `transitions[(screen, label)] -> screen` fires on
a click inside an element whose text is `label`, or on `key(label)` (e.g. ("menu-comercial", "esc") -> "inicio")."""
import json
from pathlib import Path

import numpy as np

from app.contracts import Element


class FakeSession:
    def __init__(self, start: str, transitions: dict[tuple[str, str], str], elements_dir: Path, w: int = 1258, h: int = 566):
        self.transitions, self.elements_dir, self.w, self.h = transitions, Path(elements_dir), w, h
        self.clipboard = ""
        self.clicks: list[tuple[int, int]] = []
        self.keys: list[str] = []
        self.typed: list[str] = []
        self._go(start)

    def _go(self, screen: str) -> None:
        self.screen = screen
        raw = json.loads((self.elements_dir / f"{screen}.json").read_text("utf-8"))
        self.elements = [Element(**{**e, "bbox": tuple(e["bbox"])}) for e in raw]
        # Paint each box with a per-screen shade so a screen change shows up in changed_bbox(before, after).
        self.fb = np.zeros((self.h, self.w, 4), np.uint8)
        shade = 1 + sum(screen.encode()) % 254
        for e in self.elements:
            x0, y0, x1, y1 = e.bbox
            self.fb[y0:y1 + 1, x0:x1 + 1, :3] = shade

    def _fire(self, label: str) -> None:
        if (nxt := self.transitions.get((self.screen, label))) is not None:
            self._go(nxt)

    async def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))
        hit = [e for e in self.elements if e.bbox[0] <= x <= e.bbox[2] and e.bbox[1] <= y <= e.bbox[3]]
        if hit:
            self._fire(min(hit, key=lambda e: (e.bbox[2] - e.bbox[0]) * (e.bbox[3] - e.bbox[1])).text)  # innermost

    async def type(self, text: str) -> None:
        self.typed.append(text)

    async def key(self, name: str) -> None:
        self.keys.append(name)
        self._fire(name)

    async def settle(self, quiet: float = 1.0, timeout: float = 8.0, expect=None) -> float:
        return 0.0

    async def send_clipboard(self, text: str) -> None:
        self.clipboard = text

    async def close(self) -> None:
        pass
