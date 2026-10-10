"""Stub: B1 overwrites this file with the real RFB session."""
import numpy as np

from app.contracts import Session


class _NullSession:
    w, h, clipboard = 1258, 566, ""

    def __init__(self):
        self.fb = np.zeros((self.h, self.w, 4), np.uint8)

    async def click(self, x, y): ...
    async def type(self, text): ...
    async def key(self, name): ...
    async def settle(self, quiet=1.0, timeout=8.0, expect=None): return 0.0
    async def send_clipboard(self, text): self.clipboard = text
    async def close(self): ...


async def open_session(url: str, password: str) -> Session:
    return _NullSession()
