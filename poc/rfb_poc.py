# /// script
# requires-python = ">=3.12"
# dependencies = ["websockets>=13", "pycryptodome", "numpy", "pillow", "mcp>=1.10,<2"]  # mcp 2.x renamed FastMCP -> MCPServer
# ///
"""POC: talk RFB (VNC) straight to noVNC's /websockify — no browser.

  uv run poc/rfb_poc.py probe          # connect, print ServerInit + timings, save screen.png (no input sent)
  uv run poc/rfb_poc.py click X Y      # click, wait until settled, save before/after
  uv run poc/rfb_poc.py type "texto"   # type text, wait until settled
  uv run poc/rfb_poc.py mcp            # stdio MCP server: screenshot / click / type_text / key
"""
import asyncio
import io
import struct
import sys
import time
from pathlib import Path

import numpy as np
from Crypto.Cipher import DES
from PIL import Image as PILImage
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "out"
KEYS = {"enter": 0xFF0D, "tab": 0xFF09, "backspace": 0xFF08, "esc": 0xFF1B,
        "up": 0xFF52, "down": 0xFF54, "left": 0xFF51, "right": 0xFF53}


def log(*a):
    print(*a, file=sys.stderr, flush=True)  # stdout belongs to MCP in mcp mode


def env():
    return dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l)


class RFB:
    def __init__(self):
        self.buf = bytearray()
        self.last_change = 0.0
        self.clipboard = ""
        self.updated = asyncio.Event()

    async def _read(self, n):
        while len(self.buf) < n:
            self.buf += await self.ws.recv()
        out, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return out

    async def connect(self):
        e = env()
        url = e["URL"].replace("https://", "wss://").rstrip("/") + "/websockify"
        t0 = time.perf_counter()
        self.ws = await connect(url, subprotocols=["binary"], max_size=None)
        ver = await self._read(12)
        await self.ws.send(b"RFB 003.008\n")
        n = (await self._read(1))[0]
        types = await self._read(n)
        if 2 not in types:
            raise RuntimeError(f"no VNC auth offered: {list(types)}")
        await self.ws.send(b"\x02")
        challenge = await self._read(16)
        # VNC auth quirk: DES key is the password with each byte's bits reversed
        key = bytes(int(f"{b:08b}"[::-1], 2) for b in e["PASSWORD"].encode()[:8].ljust(8, b"\0"))
        await self.ws.send(DES.new(key, DES.MODE_ECB).encrypt(challenge))
        if struct.unpack(">I", await self._read(4))[0] != 0:
            raise RuntimeError("VNC auth failed")
        await self.ws.send(b"\x01")  # ClientInit shared=1: don't kick other viewers
        self.w, self.h = struct.unpack(">HH", await self._read(4))
        await self._read(16)  # server pixel format, overridden below
        self.name = (await self._read(struct.unpack(">I", await self._read(4))[0])).decode(errors="replace")
        self.t_handshake = time.perf_counter() - t0
        self.server_version = ver.decode().strip()

        # 32bpp little-endian true colour -> bytes arrive as B,G,R,X
        await self.ws.send(b"\x00\0\0\0" + struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        await self.ws.send(struct.pack(">BxHii", 2, 2, 0, 1))  # SetEncodings: Raw, CopyRect (lossless only)
        self.fb = np.zeros((self.h, self.w, 4), np.uint8)
        self.reader = asyncio.create_task(self._loop())
        await self._request(incremental=False)
        await self.updated.wait()
        self.t_first_frame = time.perf_counter() - t0

    async def _request(self, incremental=True):
        await self.ws.send(struct.pack(">BBHHHH", 3, int(incremental), 0, 0, self.w, self.h))

    async def _loop(self):
        while True:
            msg = (await self._read(1))[0]
            if msg == 0:  # FramebufferUpdate
                (n,) = struct.unpack(">xH", await self._read(3))
                for _ in range(n):
                    x, y, w, h, enc = struct.unpack(">HHHHi", await self._read(12))
                    if enc == 0:
                        self.fb[y:y + h, x:x + w] = np.frombuffer(await self._read(w * h * 4), np.uint8).reshape(h, w, 4)
                    elif enc == 1:
                        sx, sy = struct.unpack(">HH", await self._read(4))
                        self.fb[y:y + h, x:x + w] = self.fb[sy:sy + h, sx:sx + w].copy()
                    else:
                        raise RuntimeError(f"unexpected encoding {enc}")
                if n:
                    self.last_change = time.perf_counter()
                self.updated.set()
                await self._request()  # keep a request outstanding, like noVNC does
            elif msg == 1:  # SetColourMapEntries
                _, cnt = struct.unpack(">xHH", await self._read(5))
                await self._read(cnt * 6)
            elif msg == 2:  # Bell
                pass
            elif msg == 3:  # ServerCutText
                (ln,) = struct.unpack(">3xI", await self._read(7))
                self.clipboard = (await self._read(ln)).decode("latin-1")
            else:
                raise RuntimeError(f"unknown server message {msg}")

    # lazy: quiet-time only; SIGECOM paints in two phases (>300ms gap). Real fix = verify a per-screen anchor.
    async def settle(self, quiet=1.0, timeout=8.0):
        """Return once no screen changes arrived for `quiet` seconds. No fixed sleeps per action."""
        start = time.perf_counter()
        await asyncio.sleep(quiet)
        while time.perf_counter() - self.last_change < quiet and time.perf_counter() - start < timeout:
            await asyncio.sleep(0.05)
        return time.perf_counter() - start

    async def click(self, x, y):
        await self.ws.send(struct.pack(">BBHH", 5, 0, x, y))
        await self.ws.send(struct.pack(">BBHH", 5, 1, x, y))
        await self.ws.send(struct.pack(">BBHH", 5, 0, x, y))

    async def key(self, keysym):
        await self.ws.send(struct.pack(">BBxxI", 4, 1, keysym))
        await self.ws.send(struct.pack(">BBxxI", 4, 0, keysym))

    async def type(self, text):
        for c in text:  # Latin-1 chars (ñ, á...) map 1:1 to keysyms
            await self.key(KEYS["enter"] if c == "\n" else ord(c))

    def png(self, path=None):
        img = PILImage.fromarray(self.fb[:, :, 2::-1])  # BGRX -> RGB
        if path:
            path.parent.mkdir(exist_ok=True)
            img.save(path)
        b = io.BytesIO()
        img.save(b, "PNG")
        return b.getvalue()


def changed_bbox(a, b):
    ys, xs = np.nonzero((a != b).any(axis=2))
    return None if not len(xs) else (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


async def cli(cmd, args):
    r = RFB()
    await r.connect()
    log(f"server={r.server_version} desktop={r.name!r} size={r.w}x{r.h}")
    log(f"handshake={r.t_handshake * 1000:.0f}ms first_full_frame={r.t_first_frame * 1000:.0f}ms")
    await r.settle()
    r.png(OUT / "before.png")
    before = r.fb.copy()
    if cmd == "probe":
        log(f"saved {OUT / 'before.png'}")
        return
    t0 = time.perf_counter()
    if cmd == "click":
        await r.click(int(args[0]), int(args[1]))
    elif cmd == "type":
        await r.type(args[0])
    elif cmd == "key":
        await r.key(KEYS[args[0]])
    took = await r.settle()
    r.png(OUT / "after.png")
    log(f"{cmd} -> settled in {took * 1000:.0f}ms (total {(time.perf_counter() - t0) * 1000:.0f}ms), "
        f"changed bbox={changed_bbox(before, r.fb)}, saved {OUT / 'after.png'}")


def mcp_server():
    from mcp.server.fastmcp import FastMCP, Image

    app = FastMCP("sigecom-poc")
    conn = {}

    async def rfb():
        if "r" not in conn:
            conn["r"] = RFB()
            await conn["r"].connect()
        return conn["r"]

    async def shot():
        r = await rfb()
        await r.settle()
        return Image(data=r.png(), format="png")

    @app.tool()
    async def screenshot() -> Image:
        """Screenshot of the SIGECOM legacy app (VNC desktop). Coordinates are image pixels."""
        return await shot()

    @app.tool()
    async def click(x: int, y: int) -> Image:
        """Left-click at pixel (x, y), wait until the screen settles, return the new screenshot.
        Never open Herramientas > Configuración > Integraciones."""
        await (await rfb()).click(x, y)
        return await shot()

    @app.tool()
    async def type_text(text: str) -> Image:
        """Type text into the focused field (use \\n for Enter), then return the new screenshot."""
        await (await rfb()).type(text)
        return await shot()

    @app.tool()
    async def key(name: str) -> Image:
        """Press a special key: enter, tab, backspace, esc, up, down, left, right."""
        await (await rfb()).key(KEYS[name])
        return await shot()

    app.run()


if __name__ == "__main__":
    if sys.argv[1] == "mcp":
        mcp_server()
    else:
        asyncio.run(cli(sys.argv[1], sys.argv[2:]))
