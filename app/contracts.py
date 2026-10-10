"""Shared contracts (Appendix E §2.1). Written once by A1; no later ticket edits this file."""
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from numpy import ndarray

Kind = Literal["title", "menu", "button", "field", "select", "link", "header", "cell", "text"]
BBox = tuple[int, int, int, int]  # x0, y0, x1, y1 inclusive, like the POC's changed_bbox


@dataclass
class Element:
    id: int
    text: str
    bbox: BBox
    kind: Kind
    conf: float = 1.0
    paired_input: int | None = None  # id of the field this label belongs to


@dataclass
class Target:
    label: str
    role: Kind
    cell: tuple[int, int]  # coarse grid cell (col, row)


@dataclass
class Effect:
    ok: bool
    changed_bbox: BBox | None
    screen_id: str | None
    signal: str | None  # drift signal S1–S7, None when the action did what it should
    detail: str
    cost_ms: float


@dataclass
class Summary:
    status: Literal["terminada", "fallida"]
    text: str
    data: dict[str, Any] = field(default_factory=dict)


class Session(Protocol):
    fb: ndarray  # h × w × 4, BGRX like the POC's RFB.fb
    w: int
    h: int
    clipboard: str

    async def click(self, x: int, y: int) -> None: ...
    async def type(self, text: str) -> None: ...
    async def key(self, name: str) -> None: ...
    async def settle(self, quiet: float = 1.0, timeout: float = 8.0, expect: Any = None) -> float: ...
    async def send_clipboard(self, text: str) -> None: ...
    async def close(self) -> None: ...


Perceive = Callable[[ndarray], list[Element]]
