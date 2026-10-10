"""RFB session over noVNC's /websockify, opened from the task payload alone (copied from poc/rfb_poc.py's RFB)."""
import asyncio
import collections
import contextlib
import io
import struct
import time

import numpy as np
from Crypto.Cipher import DES
from PIL import Image as PILImage
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.contracts import Session

KEYS = {"enter": 0xFF0D, "tab": 0xFF09, "backspace": 0xFF08, "esc": 0xFF1B,
        "up": 0xFF52, "down": 0xFF54, "left": 0xFF51, "right": 0xFF53,
        "home": 0xFF50, "end": 0xFF57, "delete": 0xFFFF}
MODIFIERS = {"ctrl": 0xFFE3, "shift": 0xFFE1, "alt": 0xFFE9}
RECONNECT_ATTEMPTS = 2


def ws_url(url: str) -> str:
    url = url.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return url if url.endswith("/websockify") else url + "/websockify"


class RFBSession:
    def __init__(self, keepalive=5.0, backoff=1.0):
        self.keepalive, self.backoff = keepalive, backoff
        self.fb = None
        self._healed = None  # resolves when the socket after the current one is up; fails if reconnect gives up
        self.buf = bytearray()
        self.last_change = 0.0
        self.mark = 0.0  # last input or settle; only updates after it count toward settle's `expect`
        # lazy: >512 rects between an input and its settle drop the oldest; grow maxlen if a hit gets lost
        self.rects = collections.deque(maxlen=512)  # recent updates as (t, x0, y0, x1, y1) inclusive
        self.clipboard = ""
        self.cut_arrived = asyncio.Event()
        self.updated = asyncio.Event()

    async def _read(self, n, ws=None):
        ws = ws or self.ws
        while len(self.buf) < n:
            self.buf += await ws.recv()
        out, self.buf = bytes(self.buf[:n]), self.buf[n:]
        return out

    async def connect(self, url: str, password: str):
        self.url, self.password = url, password
        await self._handshake()
        self.reader = asyncio.create_task(self._run())
        self.pinger = asyncio.create_task(self._keepalive())
        await asyncio.wait_for(self.updated.wait(), 10)  # raise, don't hang, if the socket dies first
        self.mark = time.perf_counter()  # the initial full frame doesn't count as an expected change

    async def _handshake(self):
        """RFB 3.8 + VNC auth on a fresh socket, then a full-frame request. The socket becomes `self.ws`
        only once the handshake is done, so input sent meanwhile fails on the old one and waits."""
        self.buf.clear()
        ws = await connect(ws_url(self.url), subprotocols=["binary"], max_size=None)
        read = lambda n: self._read(n, ws)  # noqa: E731
        await read(12)
        await ws.send(b"RFB 003.008\n")
        n = (await read(1))[0]
        types = await read(n)
        if 2 not in types:
            raise RuntimeError(f"no VNC auth offered: {list(types)}")
        await ws.send(b"\x02")
        challenge = await read(16)
        # VNC auth quirk: DES key is the password with each byte's bits reversed
        key = bytes(int(f"{b:08b}"[::-1], 2) for b in self.password.encode()[:8].ljust(8, b"\0"))
        await ws.send(DES.new(key, DES.MODE_ECB).encrypt(challenge))
        if struct.unpack(">I", await read(4))[0] != 0:
            await ws.close()
            raise RuntimeError("VNC auth failed")
        await ws.send(b"\x01")  # ClientInit shared=1: don't kick other viewers
        self.w, self.h = struct.unpack(">HH", await read(4))
        await read(16)  # server pixel format, overridden below
        await read(struct.unpack(">I", await read(4))[0])  # desktop name, unused

        # 32bpp little-endian true colour -> bytes arrive as B,G,R,X
        await ws.send(b"\x00\0\0\0" + struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        await ws.send(struct.pack(">BxHii", 2, 2, 0, 1))  # SetEncodings: Raw, CopyRect (lossless only)
        if self.fb is None or self.fb.shape[:2] != (self.h, self.w):  # keep the old frame until the new one lands
            self.fb = np.zeros((self.h, self.w, 4), np.uint8)
        self.ws, healed, self._healed = ws, self._healed, asyncio.get_running_loop().create_future()
        if healed:
            healed.set_result(None)
        await self._request(incremental=False)

    async def _run(self):
        """The only task that reads the socket; on a drop it reconnects up to RECONNECT_ATTEMPTS times.
        If it gives up or dies, the pending `_healed` fails so no caller waits forever."""
        try:
            while True:
                with contextlib.suppress(ConnectionClosed):  # close() cancels this task first, so only drops land here
                    await self._loop()
                for i in range(RECONNECT_ATTEMPTS):
                    if i:
                        await asyncio.sleep(self.backoff)
                    try:
                        await asyncio.wait_for(self._handshake(), 5)
                        break
                    except Exception as e:  # refused, dropped mid-handshake, auth, timeout: all count as a failed attempt
                        err = e
                else:
                    raise ConnectionError(f"RFB reconnect failed {RECONNECT_ATTEMPTS}x: {err!r}")
        except Exception as e:
            self._healed.set_exception(e)
            raise

    async def _keepalive(self):
        """Railway closes idle sockets; an incremental request every `keepalive` s keeps bytes flowing."""
        while not self.reader.done():
            await asyncio.sleep(self.keepalive)
            with contextlib.suppress(ConnectionClosed):  # the reader heals drops
                await self._request()

    async def _send(self, data):
        """One client message. On a dropped socket wait for the reader to reconnect, then retry it once."""
        ws, healed = self.ws, self._healed
        try:
            await ws.send(data)
        except ConnectionClosed:
            await healed
            await self.ws.send(data)

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
        await self._send(b"".join(struct.pack(">BBHH", 5, m, x, y) for m in (0, 1, 0)))

    async def _keysym(self, *syms):
        """Press each keysym in order, release in reverse, as one message."""
        self.mark = time.perf_counter()
        await self._send(b"".join(struct.pack(">BBxxI", 4, 1, k) for k in syms)
                         + b"".join(struct.pack(">BBxxI", 4, 0, k) for k in reversed(syms)))

    async def key(self, name):
        """One key or a chord like 'ctrl+shift+end': press each part in order, release in reverse."""
        syms = []
        for part in name.split("+"):
            sym = MODIFIERS.get(part) or KEYS.get(part) or (ord(part) if len(part) == 1 else None)
            if sym is None:
                raise ValueError(f"unknown key {part!r} in {name!r}; modifiers: {', '.join(MODIFIERS)}; "
                                 f"keys: {', '.join(KEYS)} or one character")
            syms.append(sym)
        await self._keysym(*syms)

    async def type(self, text):
        for c in text:  # Latin-1 chars (ñ, á...) map 1:1 to keysyms
            await self._keysym(KEYS["enter"] if c == "\n" else ord(c))

    async def send_clipboard(self, text):
        self.mark = time.perf_counter()
        data = text.encode("latin-1")  # RFB 3.8 cut text is Latin-1 only
        await self._send(struct.pack(">B3xI", 6, len(data)) + data)  # ClientCutText

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
        self.pinger.cancel()
        self._healed.cancel()  # a send racing close() raises instead of waiting forever
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
