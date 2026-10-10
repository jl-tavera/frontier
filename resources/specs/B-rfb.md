# Spec B · RFB transport

Design: `resources/docs/solution.md` §3.2 row [G], §5 Track 1; Appendix C; Appendix I (`poc/rfb_poc.py`). Run book: [README.md](README.md).

## Problem

The POC speaks raw RFB over WSS but reads the desktop from `.env`, has quiet-time-only settle, no reconnect and no clipboard send. The runner needs a `Session` it can open from the request payload and trust for five minutes.

## Owns

`app/rfb/`, `tests/rfb/`, `tests/fakes/rfb_server.py`. Overwrites the A1 stub `app/rfb/session.py: open_session`. `poc/rfb_poc.py` stays untouched (it is Appendix I); B1 copies the class.

## Slices

**B1 · Session from the request payload, with a fake RFB server for tests** (1.1, 1.5)

As the runner, `open_session(url, password)` connects using only those two values (https → wss, `/websockify`, `binary` subprotocol), does VNC auth type 2, sets 32bpp + Raw/CopyRect, `shared=1`, and exposes the `Session` protocol from `app/contracts.py` (`fb`, `click`, `type`, `key`, `settle`, `png`, `close`). Rides here: `tests/fakes/rfb_server.py`, an in-process `websockets` server on `127.0.0.1` speaking RFB 3.8 + VNC auth, serving a PNG as the framebuffer, recording pointer/key events, scriptable rectangles and clipboard, able to drop the socket. Seam: the fake server; done when `fb` equals the fixture pixels after connect, a click is received as 3 pointer events, a wrong password raises. Blocked by A1.

**B2 · Clipboard both ways** (1.6)

As the agent, `send_clipboard(text)` sends `ClientCutText` and `clipboard` holds the latest `ServerCutText` with an awaitable `wait_clipboard(timeout)`. Seam: the fake server receives the cut text and pushes one back. Blocked by B1.

**B3 · Settle with an expected-change check** (1.3)

As the agent, `settle(quiet, timeout, expect=bbox)` returns once no updates arrived for `quiet` seconds **and** the expected region changed, with the measured time, so a two-phase paint (SIGECOM paints >300 ms apart) never returns early. Seam: the fake server paints two rectangles 300 ms apart; `settle(expect=second bbox)` returns after the second. Blocked by B1.

**B4 · Reconnect and keep-alive** (1.2)

As the agent, a dropped socket mid-task reconnects with the same url/password, re-requests a full frame and restores `fb` in under 5 s; an idle connection sends an incremental request every few seconds so Railway's idle timeout never fires. Seam: the fake server closes the socket, then serves again; `fb` is restored and the next click goes through. Blocked by B1.

## Decisions already made

Raw + CopyRect only, lossless (§4); `shared=1` so the evaluator or a human viewer is never kicked; VNC auth type 2 only; `websockets` ≥13 asyncio client as in the POC; `pycryptodome` DES with bit-reversed key bytes.

## Assumed

- Quiet time 1.0 s, settle timeout 8 s, keep-alive interval 5 s, reconnect attempts 2.
- Framebuffer is BGRX `uint8` like the POC; consumers never see raw messages.

## Not building

Tight/zlib encodings (1.4, measure live first; trigger: bandwidth hurts); auth None/VeNCrypt (trigger: a target offers them); a websocat + asyncvnc fallback (Appendix C A4).

## Live checks (human)

10/10 connects to SIGECOM from the payload only; two clients at once don't break each other (1.5); frame time Raw vs none (1.4).
