"""In-process fake RFB server for Spec B tests: RFB 3.8 + VNC auth over websockets on 127.0.0.1.

  async with FakeRFBServer(png, "secret") as srv:
      s = await open_session(srv.url, "secret")
      srv.events      # [("pointer", mask, x, y), ("key", down, keysym), ...]
      srv.shared, srv.encodings, srv.cut_texts, srv.requests
      await srv.paint(x, y, rgb)        # push a Raw rectangle (h × w × 3 RGB uint8)
      await srv.push_clipboard("text")  # push ServerCutText
      await srv.drop()                  # close the client socket
"""
import asyncio
import os
import struct
from pathlib import Path

import numpy as np
from Crypto.Cipher import DES
from PIL import Image
from websockets.asyncio.server import serve


def vnc_response(password: str, challenge: bytes) -> bytes:
    key = bytes(int(f"{b:08b}"[::-1], 2) for b in password.encode()[:8].ljust(8, b"\0"))
    return DES.new(key, DES.MODE_ECB).encrypt(challenge)


def _bgrx(rgb: np.ndarray) -> np.ndarray:
    """RGB -> BGRX, matching the 32bpp little-endian format the client asks for."""
    out = np.zeros((*rgb.shape[:2], 4), np.uint8)
    out[:, :, 2::-1] = rgb
    return out


class FakeRFBServer:
    def __init__(self, png: Path, password: str):
        self.fb = _bgrx(np.asarray(Image.open(png).convert("RGB")))
        self.h, self.w = self.fb.shape[:2]
        self.password = password
        self.events: list[tuple] = []
        self.requests: list[tuple] = []  # (incremental, x, y, w, h)
        self.cut_texts: list[str] = []
        self.shared: int | None = None
        self.encodings: list[int] | None = None
        self.ws = None

    async def __aenter__(self):
        self._server = await serve(self._handle, "127.0.0.1", 0, subprotocols=["binary"], max_size=None)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *exc):
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, ws):
        if ws.request.path != "/websockify":
            await ws.close()
            return
        self.ws, buf = ws, bytearray()

        async def read(n):
            nonlocal buf
            while len(buf) < n:
                buf += await ws.recv()
            out, buf = bytes(buf[:n]), buf[n:]
            return out

        await ws.send(b"RFB 003.008\n")
        await read(12)
        await ws.send(b"\x01\x02")  # one security type: VNC auth
        if (await read(1)) != b"\x02":
            return await ws.close()
        challenge = os.urandom(16)
        await ws.send(challenge)
        if await read(16) != vnc_response(self.password, challenge):
            reason = b"Authentication failed"
            await ws.send(struct.pack(">II", 1, len(reason)) + reason)
            return await ws.close()
        await ws.send(struct.pack(">I", 0))
        self.shared = (await read(1))[0]
        name = b"fake"
        pixel_format = struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0)
        await ws.send(struct.pack(">HH", self.w, self.h) + pixel_format + struct.pack(">I", len(name)) + name)
        try:
            while True:
                msg = (await read(1))[0]
                if msg == 0:  # SetPixelFormat
                    await read(19)
                elif msg == 2:  # SetEncodings
                    (n,) = struct.unpack(">xH", await read(3))
                    self.encodings = list(struct.unpack(f">{n}i", await read(4 * n)))
                elif msg == 3:  # FramebufferUpdateRequest
                    inc, x, y, w, h = struct.unpack(">BHHHH", await read(9))
                    self.requests.append((inc, x, y, w, h))
                    if not inc:
                        await self._send_rect(0, 0, self.fb)
                elif msg == 4:  # KeyEvent
                    down, keysym = struct.unpack(">B2xI", await read(7))
                    self.events.append(("key", down, keysym))
                elif msg == 5:  # PointerEvent
                    self.events.append(("pointer", *struct.unpack(">BHH", await read(5))))
                elif msg == 6:  # ClientCutText
                    (ln,) = struct.unpack(">3xI", await read(7))
                    self.cut_texts.append((await read(ln)).decode("latin-1"))
                else:
                    raise RuntimeError(f"fake server: unknown client message {msg}")
        except Exception:
            await ws.close()

    async def _send_rect(self, x, y, bgrx):
        h, w = bgrx.shape[:2]
        await self.ws.send(struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", x, y, w, h, 0) + bgrx.tobytes())

    async def paint(self, x: int, y: int, rgb: np.ndarray):
        bgrx = _bgrx(rgb)
        self.fb[y:y + rgb.shape[0], x:x + rgb.shape[1]] = bgrx
        await self._send_rect(x, y, bgrx)

    async def push_clipboard(self, text: str):
        data = text.encode("latin-1")
        await self.ws.send(struct.pack(">B3xI", 3, len(data)) + data)

    async def drop(self):
        await self.ws.close()
