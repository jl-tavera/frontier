# Transport: raw RFB over WebSocket (track 1)

> Appendix C of [solution.md](../solution.md) · Status: adopted as component [G] (solution.md §3.2, §4) · Links checked 2026-10-10.

## 1. Summary

**Decision:** our own Python process speaks **raw RFB (VNC) over WSS** to the target's `/websockify` endpoint, using the `websockets` library. No browser is involved. Implementation: `poc/rfb_poc.py`.

> **Terminology.** *websockify* is the **server-side** proxy the target already runs: it accepts a WebSocket and forwards the bytes over TCP to the VNC server. We didn't choose it and can't change it. On our side the client library is **`websockets`** (Python). People mix the two up, so expect the question in the debrief.

---

## 2. Problem and constraints

Source: [Appendix B](B-target-recon.md).

```
our process ──WSS /websockify──► websockify ──TCP──► VNC server (Docker 86a79607eef2:0) ──► SIGECOM
```

- Protocol: RFB 3.8 with VNC Authentication (DES challenge-response). There's no HTTP auth and no cookies.
- The app has no DOM and no API. The host exposes only `/health` and `/websockify`.
- noVNC in a browser is **just one RFB client**. Anything that speaks RFB through a WebSocket can take its place.

The decision therefore has two layers:
- **A. Where the RFB client runs:** inside a browser (noVNC) or inside our own process.
- **B. If it runs in our process:** which language, which WebSocket library, and whether we write the RFB code ourselves or use a VNC library.

---

## 3. Options considered

### 3.1 Layer A — where the RFB client runs

| Option | How it works | Pros | Cons | Verdict |
|---|---|---|---|---|
| **A1. Raw RFB client over WSS** | Our process opens the WSS connection, does the RFB handshake, keeps the framebuffer as a numpy array, and sends pointer and key events | <ul><li>Pixels are lossless because we choose the encodings (Raw and CopyRect).</li><li>The framebuffer lives in memory, so a screenshot needs no network call.</li><li>Click coordinates are framebuffer coordinates: no canvas offset, no scaling.</li><li>Every `FramebufferUpdate` reaches us, which gives the settle and change-detection signal for free.</li><li>We can use the clipboard channel (`ClientCutText` / `ServerCutText`) directly.</li><li>One process and no Chromium, so the Railway deploy stays small.</li><li>Per-task `{url, password}` are plain constructor arguments.</li><li>About 200 lines of code, already working.</li></ul> | <ul><li>We own the protocol code: handshake, encodings, reconnect.</li><li>Only VNC auth is implemented.</li></ul> | **Chosen** |
| A2. Playwright/Chromium + the noVNC page | A headless browser loads `/vnc.html?autoconnect=1&password=…`. We screenshot the canvas and click with `page.mouse` | <ul><li>No protocol code to write.</li><li>noVNC already handles every encoding and auth type.</li><li>We see exactly what a human sees.</li></ul> | <ul><li>Frames arrive as **Tight/JPEG** (observed in the analysis), and the artifacts hurt OCR and pixel diffs. `?quality=9` helps, but the default stays lossy.</li><li>Canvas offset and scaling: changing the viewport shifted the image by +160 x / +100 y in the analysis, so every click needs a coordinate translation.</li><li>Each screenshot is a canvas-to-PNG encode plus a CDP round trip (tens to hundreds of ms), compared with reading an in-memory array.</li><li>Settle has to be inferred by polling the DOM or canvas, or by hooking noVNC's JS.</li><li>Chromium adds about 300 MB to the image, more RAM and a slower cold start, all inside a 5-minute task budget.</li><li>Two layers can fail: the browser and VNC.</li></ul> | Discarded: it costs fidelity, latency and deploy size and gives the agent nothing it needs |
| A3. Playwright driving noVNC's JS API | `page.evaluate(...)` calls `rfb.sendKey` and reads `canvas.getImageData` | <ul><li>Lossless reads and exact coordinates.</li></ul> | <ul><li>Every browser cost of A2, plus a JS bridge to maintain.</li><li>In effect it's A1 with a browser wrapped around it.</li></ul> | Discarded: strictly worse than A1 |
| A4. Local bridge + an off-the-shelf TCP VNC client | `websocat --binary tcp-l:127.0.0.1:5900 wss://host/websockify`, then asyncvnc, vncdotool or TigerVNC connects to localhost | <ul><li>Mature VNC libraries. asyncvnc gives numpy frames, the clipboard and many encodings.</li></ul> | <ul><li>An extra binary and process to deploy and supervise for each task.</li><li>Two sockets to reconnect.</li><li>The libraries hide the update stream (vncdotool is Twisted-based and polls), so we lose the per-update settle signal.</li></ul> | **Fallback**, if the unseen app's server needs an encoding or auth type our code lacks |
| A5. Computer-use VM (Anthropic reference container with xdotool) | Run a desktop locally and open the noVNC page in it | <ul><li>Works with Claude's computer-use tool out of the box.</li></ul> | <ul><li>It's A2 with a full desktop on top: the heaviest option.</li></ul> | Discarded |
| A6. Another protocol (RDP, SSH, an app API) | — | — | Not exposed: the host serves only `/health` and `/websockify`, and the unseen app is delivered the same way | N/A |

### 3.2 Layer B — language

| | **Python (chosen)** | Node/TS | Go | Rust |
|---|---|---|---|---|
| WebSocket client | `websockets` (asyncio, mature) | `ws` | `coder/websocket`, `gorilla` | `tokio-tungstenite` |
| RFB reuse | our own ~200 LOC, or asyncvnc | could run noVNC's own `core/rfb.js` headless, but it's coupled to the DOM and canvas (Display, Keyboard) and would need shims | `go-vnc` (unmaintained) | `vnc-rs` |
| Image and vision stack | numpy, Pillow, OpenCV, Tesseract / EasyOCR / PaddleOCR | weak (sharp, tesseract.js) | weak | weak |
| Agent and service | Anthropic SDK, FastAPI, all in one process | good SDKs | OK | thin |
| Team speed | POC already works | rewrite | rewrite | rewrite, slower iteration |

### 3.3 Layer B — WebSocket library within Python

| Library | Model | Notes | Verdict |
|---|---|---|---|
| **`websockets` ≥13** | asyncio-native (`websockets.asyncio.client`) | <ul><li>Binary frames.</li><li>The `binary` subprotocol that websockify expects.</li><li>`max_size=None` allows large Raw frames.</li><li>Built-in ping and keepalive (`ping_interval`), useful for reconnect (1.2).</li></ul> | **Chosen**: fits the asyncio agent loop and FastAPI |
| `aiohttp` | asyncio client and server | Works, but heavier. Only worth it if we already used aiohttp elsewhere | Equivalent, no gain |
| `websocket-client` | sync, needs threads | Blocking reads would need a thread per session next to async FastAPI | Discarded |
| `wsproto` | sans-IO | We'd have to write our own IO loop | Discarded: more code |
| websockify's `WebSocket` client class | sync | The maintainer mentions it can act as a client, but it has no asyncio API | Discarded |

### 3.4 Layer B — VNC libraries instead of our own RFB code

- **asyncvnc / asyncvnc2:** asyncio-based, numpy frames, clipboard support. But they connect over TCP through asyncio streams, so we'd need A4's bridge or a patched stream. They also hide `FramebufferUpdate` timing (our settle signal) and the choice of encoding.
- **vncdotool:** Twisted-based and CLI-oriented. It's TCP-only; the noVNC maintainer confirms it can't connect to a WebSocket-only endpoint.

---

## 4. Chosen design

A raw RFB client in our own process (A1), in Python, on `websockets`, with our own protocol code. The verdict column in §3 gives the reason for each.

**Why Python.** The transport is the smallest part of the system. Perception (track 2), the agent loop and tools (track 3), and the entrypoint (track 5) all depend on Python's image and ML ecosystem. Keeping everything in one language and one process means no IPC. Raw speed doesn't matter here: the native framebuffer is 1280×800 (measured), so a full Raw frame is about 4.1 MB, incremental updates are small, and numpy slicing is far cheaper than the network. Node's one real advantage, reusing noVNC's `rfb.js`, is cancelled out by that code's DOM coupling.

- **Our own code:** about 150 lines of protocol. We control the encodings (lossless) and see every update, so nothing hides inside the 5-minute budget.
  - Risk: the unseen app's server may use an encoding or auth type we don't handle.
  - Mitigation: we only *request* Raw and CopyRect, and every RFB server must support Raw. A4 stays as the fallback.

---

## 5. Trade-offs we accept (say these in the debrief)

- **Bandwidth.** Raw is the most expensive encoding. SIGECOM's UI is mostly static, so this is fine for now. Measure it in 1.4. If it hurts, add Tight with JPEG turned off (lossless zlib) rather than JPEG.
- **We own reconnect (1.2), settle (1.3) and clipboard send (1.6).** Each is a small, listed unit.
- **Auth.** We support VNC auth (type 2). Adding type 1 (None) is trivial. VeNCrypt and RA2 are out of scope, and the design doc states that as an assumption.

---

## 6. Evidence and measurement

| # | Measurement | Command | Result |
|---|---|---|---|
| 1 | Handshake and first full frame, 10 runs | `uv run poc/rfb_poc.py probe` | 10 runs: handshake 1104–1667 ms (mean ~1.42 s); first full frame 2826–5992 ms (mean ~3.65 s). Server `RFB 003.008`, desktop `86a79607eef2:0`, **1280×800** |
| 2 | Settle time after a click | `uv run poc/rfb_poc.py click X Y` (prints `settled in`) | _TODO_ |
| 3 | (optional) A2 baseline: Playwright time to first canvas and `page.screenshot()` latency | a ~20-line script against `/vnc.html?autoconnect=1&password=…` | _TODO_ |
| 4 | (optional) Fidelity: an A1 PNG vs an A2 canvas capture of the same screen, counting differing pixels | numpy diff | _TODO_ |

### 6.1 Reading the numbers

- Connecting costs **about 4 s, up to 6 s** per task, which is 1–2% of the 5-minute budget. Open the connection once per task and reuse it; never reconnect per action.
- About 2.2 s of that is the first **4.1 MB Raw full frame**. This is the bandwidth cost of lossless pixels. Incremental updates after that are small. If cold start matters, try Tight with JPEG off (lossless zlib) in 1.4.
- The native resolution is **1280×800**, not the 1258×566 canvas noVNC showed. A2's browser view was scaled or cropped, which is one more argument for A1's exact coordinates.

---

## 7. Open questions

- Still to measure (rows 2–4 of the table in §6): settle time after a click, the A2 Playwright baseline, and the A1 vs A2 fidelity diff.
- Whether the unseen app's server offers an encoding or auth type our code lacks (§4). A4 is the fallback if it does.

---

## 8. Sources

- websockify direction; vncdotool has no WebSocket support: https://groups.google.com/g/novnc/c/r4UrX1ryOro
- asyncvnc: https://asyncvnc.readthedocs.io/ · asyncvnc2: https://asyncvnc2.readthedocs.io
- websocat (TCP↔WS bridge): https://github.com/vi/websocat
