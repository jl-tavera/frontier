"""RFB session over noVNC's /websockify, opened from the task payload alone (copied from poc/rfb_poc.py's RFB)."""
import asyncio
import collections
import io
import struct
import time

import numpy as np
from Crypto.Cipher import DES
from PIL import Image as PILImage
from websockets.asyncio.client import connect

from app.contracts import Session

KEYS = {"enter": 0xFF0D, "tab": 0xFF09, "backspace": 0xFF08, "esc": 0xFF1B,
        "up": 0xFF52, "down": 0xFF54, "left": 0xFF51, "right": 0xFF53}


def ws_url(url: str) -> str:
    url = url.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return url if url.endswith("/websockify") else url + "/websockify"


class RFBSession:
    def __init__(self):
        self.buf = bytearray()
        self.last_change = 0.0
        self.mark = 0.0  # last input or settle; only updates after it count toward settle's `expect`
        # lazy: >512 rects between an input and its settle drop the oldest; grow maxlen if a hit gets lost
        self.rects = collections.deque(maxlen=512)  # recent updates as (t, x0, y0, x1, y1) inclusive
        self.clipboard = ""
        self.cut_arrived = asyncio.Event()
        self.updated = asyncio.Event()

    async def _read(self, n):
        while len(self.buf) < n:
            self.buf += await self.ws.recv()
        out, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return out

    async def connect(self, url: str, password: str):
        self.ws = await connect(ws_url(url), subprotocols=["binary"], max_size=None)
        await self._read(12)
        await self.ws.send(b"RFB 003.008\n")
        n = (await self._read(1))[0]
        types = await self._read(n)
        if 2 not in types:
            raise RuntimeError(f"no VNC auth offered: {list(types)}")
        await self.ws.send(b"\x02")
        challenge = await self._read(16)
        # VNC auth quirk: DES key is the password with each byte's bits reversed
        key = bytes(int(f"{b:08b}"[::-1], 2) for b in password.encode()[:8].ljust(8, b"\0"))
        await self.ws.send(DES.new(key, DES.MODE_ECB).encrypt(challenge))
        if struct.unpack(">I", await self._read(4))[0] != 0:
            await self.ws.close()
            raise RuntimeError("VNC auth failed")
        await self.ws.send(b"\x01")  # ClientInit shared=1: don't kick other viewers
        self.w, self.h = struct.unpack(">HH", await self._read(4))
        await self._read(16)  # server pixel format, overridden below
        await self._read(struct.unpack(">I", await self._read(4))[0])  # desktop name, unused

        # 32bpp little-endian true colour -> bytes arrive as B,G,R,X
        await self.ws.send(b"\x00\0\0\0" + struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        await self.ws.send(struct.pack(">BxHii", 2, 2, 0, 1))  # SetEncodings: Raw, CopyRect (lossless only)
        self.fb = np.zeros((self.h, self.w, 4), np.uint8)
        self.reader = asyncio.create_task(self._loop())
        await self._request(incremental=False)
        await asyncio.wait_for(self.updated.wait(), 10)  # raise, don't hang, if the socket dies first
        self.mark = time.perf_counter()  # the initial full frame doesn't count as an expected change

    async def _request(self, incremental=True):
        await self.ws.send(struct.pack(">BBHHHH", 3, int(incremental), 0, 0, self.w, self.h))

    async def _loop(self):
        while True:
            msg = (await self._read(1))[0]
            if msg == 0:  # FramebufferUpdate
                (n,) = struct.unpack(">xH", await self._read(3))
                for _ in range(n):
                    x, y, w, h, enc = struct.unpack(">HHHHi", await self._read(12))
                    self.rects.append((time.perf_counter(), x, y, x + w - 1, y + h - 1))
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
                self.cut_arrived.set()
            else:
                raise RuntimeError(f"unknown server message {msg}")

    def _changed(self, bbox, since):
        x0, y0, x1, y1 = bbox
        return any(t >= since and rx0 <= x1 and x0 <= rx1 and ry0 <= y1 and y0 <= ry1
                   for t, rx0, ry0, rx1, ry1 in self.rects)

    async def settle(self, quiet=1.0, timeout=8.0, expect=None):
        """Return the elapsed time once no update arrived for `quiet` seconds and, given `expect`
        (an inclusive x0, y0, x1, y1 box), an update since the last input or settle intersected it. No fixed
        sleeps per action. On timeout it returns the elapsed time instead of raising."""
        start, since = time.perf_counter(), self.mark
        await asyncio.sleep(quiet)
        while time.perf_counter() - start < timeout:
            if time.perf_counter() - self.last_change >= quiet and (expect is None or self._changed(expect, since)):
                break
            await asyncio.sleep(0.05)
        self.mark = time.perf_counter()
        return self.mark - start

    async def click(self, x, y):
        self.mark = time.perf_counter()
        await self.ws.send(struct.pack(">BBHH", 5, 0, x, y))
        await self.ws.send(struct.pack(">BBHH", 5, 1, x, y))
        await self.ws.send(struct.pack(">BBHH", 5, 0, x, y))

    async def _keysym(self, keysym):
        self.mark = time.perf_counter()
        await self.ws.send(struct.pack(">BBxxI", 4, 1, keysym))
        await self.ws.send(struct.pack(">BBxxI", 4, 0, keysym))

    async def key(self, name):
        await self._keysym(KEYS[name])

    async def type(self, text):
        for c in text:  # Latin-1 chars (ñ, á...) map 1:1 to keysyms
            await self._keysym(KEYS["enter"] if c == "\n" else ord(c))

    async def send_clipboard(self, text):
        self.mark = time.perf_counter()
        data = text.encode("latin-1")  # RFB 3.8 cut text is Latin-1 only
        await self.ws.send(struct.pack(">B3xI", 6, len(data)) + data)  # ClientCutText

    async def wait_clipboard(self, timeout):
        """The next ServerCutText to arrive, or None if none comes within `timeout` seconds.

        Text that arrived before the call is ignored: call it right after sending the copy keys,
        before the desktop's reply can land (a full round trip later)."""
        self.cut_arrived.clear()
        try:
            await asyncio.wait_for(self.cut_arrived.wait(), timeout)
        except TimeoutError:
            return None
        return self.clipboard

    async def close(self):
        self.reader.cancel()
        await self.ws.close()

    def png(self, path=None):
        img = PILImage.fromarray(self.fb[:, :, 2::-1])  # BGRX -> RGB
        if path:
            path.parent.mkdir(exist_ok=True)
            img.save(path)
        b = io.BytesIO()
        img.save(b, "PNG")
        return b.getvalue()


async def open_session(url: str, password: str) -> Session:
    s = RFBSession()
    await s.connect(url, password)
    return s
