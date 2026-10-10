# Technical Diagnosis — Frontier / SIGECOM Legacy System

> Appendix B of [solution.md](../solution.md) · Status: read-only recon of the development target, facts only; digested in solution.md §2 · Links checked 2026-10-10.

**Target:** `https://frontier-r1-tm77-production.up.railway.app`
**Date of analysis:** 2026-10-10
**Method:** read-only recon — HTTP requests (curl) + noVNC session inspection (agent-browser). No writes, no changes to the system.
**Scope:** diagnosis only. No solution proposed.

---

## 1. Executive summary

The URL does **not** serve a web application. It serves the **noVNC** web client, which bridges the browser to a **remote VNC desktop** over a WebSocket. The actual business system — **SIGECOM · Distribuidora Andina v3.9** — runs *inside* that remote desktop and is only ever transmitted to the browser as **pixels** (framebuffer images). There is no HTML DOM, no REST/JSON API, and no HTTP endpoint for the business data. Everything the user sees is a screenshot stream; everything the user does is mouse/keyboard events sent back over the VNC protocol.

---

## 2. Delivery / hosting layer

| Property | Value |
|---|---|
| Platform | Railway (PaaS) |
| Edge server banner | `Server: railway-hikari` |
| Edge region | `x-railway-edge: atl1` (Atlanta) |
| Trace header | `x-hikari-trace: atl1.*` |
| Request ID header | `x-railway-request-id: <uuid>` |
| Protocol | HTTP/1.1 over HTTPS (TLS) |
| Transfer | `Transfer-Encoding: chunked`, `Connection: keep-alive` |

### Observed behavior
- **`GET /`** → `200`, `Content-Type: text/html; charset=utf-8` — the noVNC page.
- **`GET /health`** → `200`, `Content-Type: application/json`, body `{"ok":true}`, `Cache-Control: no-store`.
- **Unknown paths** → `404`, `Content-Type: application/json`, body `{"error":"no encontrado"}` (Spanish "not found").
  → The 404 is produced by a **custom application server**, not a dumb static file host. The Spanish error message indicates a bespoke backend.
- **Methods:** `OPTIONS /` → `404`, `POST /` → `404`. Only `GET` (and the WebSocket upgrade) is served.
- **Security headers:** none observed on HTML or JS assets — no `Content-Security-Policy`, `X-Frame-Options`, `Strict-Transport-Security`, CORS, or `Set-Cookie`. Authentication is **not** cookie/session based at the HTTP layer.

### Paths probed
| Path | Result |
|---|---|
| `/` | 200 (noVNC HTML) |
| `/vnc.html` | 200 (noVNC HTML) |
| `/app/ui.js` | 200 (`text/javascript`) |
| `/core/rfb.js` | 200 (`text/javascript`) |
| `/health` | 200 (`{"ok":true}`) |
| `/websockify` | **WebSocket upgrade** (101) with Upgrade headers; plain `GET` → 404 |
| `/api`, `/api/docs`, `/docs`, `/openapi.json`, `/swagger` | 404 |
| `/robots.txt`, `/favicon.ico`, `/package.json` | 404 |

**No business API exists on this host.** The only non-static endpoints are `/health` and the `/websockify` WebSocket.

---

## 3. noVNC client (what the browser actually runs)

- Source: the **noVNC "simple example / default UI"**, header comment *"Copyright (C) 2019 The noVNC Authors … MPL 2.0"*.
- Page `<title>noVNC</title>`, `<html class="noVNC_loading">`.
- Entry script: `<script type="module" crossorigin="anonymous" src="app/ui.js">` + `app/error-handler.js`.
- Stylesheet `app/styles/base.css`; font **Orbitron 700** (`app/styles/Orbitron700.woff`); audio `app/sounds/bell.oga`.
- Full noVNC module tree is served under `/core/` (`rfb.js`, `display.js`, `input/*`, `util/*`, `encodings`, etc.) and `/app/`.
- Standard noVNC control bar present: Fullscreen, Settings, Clipboard, Ctrl, Alt, Tab, Esc, Ctrl-Alt-Del, Power, Connect/Disconnect, plus the drag/extra-keys toolbar (SVG icons under `app/images/`).
- Connect parameters accepted via query string or URL fragment: `host`, `port`, `encrypt`, `path`, `password`, `autoconnect`, `resize` (standard noVNC). Confirmed working: `?autoconnect=1&password=…`.

### Canvas / framebuffer
- Rendered into a single `<canvas>`; observed size **1258 × 566** (CSS size identical → not downscaled in that session).
- Screen updates arrive as **framebuffer rectangles encoded as JPEG** — captured many `data:image/jpeg;base64,…` resources during a session (Tight/JPEG VNC encoding), plus one `data:image/png`. This is the raw proof the content is image data, not markup.

---

## 4. VNC transport & remote server

- **Connection path:** browser → `wss://…/websockify` → **websockify proxy** → raw RFB/VNC (TCP) on the backend.
- noVNC status line after connect: **`Connected (encrypted) to 86a79607eef2:0`**
  - *encrypted* = the WebSocket is TLS (WSS).
  - target host `86a79607eef2` — a **12-hex-char string consistent with a Docker container ID/hostname**.
  - `:0` = VNC display number 0.
- **RFB protocol:** noVNC client advertises max version **3.8** (`core/rfb.js`: `_rfbMaxVersion = 3.8`). Server version is negotiated on the wire (client supports 3.3 / 3.7 / 3.8).
- **Authentication:** VNC-level. On connect the client shows *"Credentials are required"* → a password field → *"Send Credentials"*. This is classic **VNC Authentication** (RFB security type, DES challenge-response). The password is supplied out-of-band (stored in the project `.env`). There is **no HTTP login**; auth happens entirely inside the VNC handshake.
- **Clipboard channel:** noVNC exposes a clipboard control, implying the RFB `ServerCutText` / `ClientCutText` channel may be available for text transfer in/out of the remote session.

---

## 5. Inner application — SIGECOM · Distribuidora Andina v3.9

Everything below was read **from pixels** (screenshots). There is no inspectable markup for any of it.

### Identity / chrome
- Title bar: **"SIGECOM · Distribuidora Andina   v3.9"**.
- Right of title bar: **"Hoy: 14/10/2026 · Usuario: operador"**.
  - The date shown inside the remote system is **14/10/2026** while the real analysis date was 10/10/2026 → the remote host clock is set in the future (or a fixed demo clock).
  - The user label was observed as **`operador`** and in a later session as **`operador2`** → the VNC session/user is **not pinned per client; it may be shared** or round-robined.
- Visual style: a flat, light-theme, **web-looking UI** (hyperlinked record codes, form controls) presented full-screen — i.e. a kiosk/web-style front end running inside the remote desktop.

### Menu structure (fully enumerated)
```
Archivo
  └─ Inicio
Comercial
  ├─ Maestros ▸ Clientes
  └─ Ventas   ▸ Pedidos
Cartera
  └─ Facturas
Herramientas
  ├─ Bitácora de cambios
  ├─ Reportes generados
  └─ Configuración ▸ Integraciones
Ayuda
  └─ Acerca de
```

### Screens observed
- **Inicio / Bienvenida:** welcome text ("Sistema de g… use el menú superior para acceder a los módulos") and *"Soporte: extensión 214 (fuera de servicio)."*
- **Cartera ▸ Facturas** (default landing grid):
  - Filters: `Cliente` (text), `Estado` (dropdown, default **Todos**), buttons **Buscar** / **Limpiar**.
  - Action button: **Exportar** (top-right of the grid) — a built-in bulk-export affordance.
  - Grid columns: **Código, Cliente, Fecha, Vence, Valor, Estado**.
  - Record code format: `FV-#####` (e.g. `FV-10159`). The code cells render as hyperlinks (underlined/blue).
  - `Estado` values seen: **Vencida, Pendiente, Pagada, Anulada**.
  - Pagination footer: **Anterior · Página 1 · Siguiente**.
- **Comercial ▸ Maestros ▸ Clientes** — client master data (submenu confirmed; screen not opened).
- **Comercial ▸ Ventas ▸ Pedidos** — sales orders (submenu confirmed; screen not opened).
- **Herramientas ▸ Bitácora de cambios** — change log / audit trail (menu item confirmed).
- **Herramientas ▸ Reportes generados** — generated reports (menu item confirmed).
- **Herramientas ▸ Configuración ▸ Integraciones:**
  - Text: *"Conector con el sistema contable."* (connector to the accounting system).
  - *"Clave de integración: `SGC-…` "* — an integration key is displayed (prefix `SGC-`, format `SGC-XXXX-XXXX`). The screen explicitly warns **"No comparta esta clave."** (do not share this key). *Full value intentionally omitted from this document; read it directly on that screen.*
  - Implication: a separate accounting-system connector/integration exists somewhere, but **no endpoint, host, or documentation for it is exposed on this URL**.
- **Ayuda ▸ Acerca de** — about dialog (menu item confirmed).

---

## 6. Automation-relevant characteristics (observations, not a plan)

- **No DOM for the business app.** Only the noVNC page has a DOM; the SIGECOM UI is a canvas pixel stream. DOM scraping is impossible.
- **Input is coordinate-based.** Interaction = mouse move/click + key events over RFB. There are no selectors, labels, or roles.
- **Coordinates are resolution-dependent.** Changing the browser viewport shifted the entire remote image by a fixed offset (observed +160 x / +100 y). Any coordinate map is only valid for a fixed framebuffer size and a known anchor (e.g. the blue title bar).
- **Screen-change signal exists at the network layer.** Framebuffer updates are discrete `data:image/jpeg` rects; their arrival marks that the screen changed (usable as a "page settled" signal instead of fixed sleeps).
- **Text I/O:** reading values requires OCR of image regions; the RFB clipboard channel is a possible alternative path for text in/out.
- **Built-in bulk data path:** the **Exportar** button and **Reportes generados** are the system's own export mechanisms (observed, not exercised).
- **Session sharing risk:** the logged-in user varied between sessions (`operador` → `operador2`); concurrent automation could collide with a human or another client on the same display.
- **Integration key present but opaque:** an accounting-connector key is shown in Integraciones, hinting at an external API that is **not** reachable from this host.

---

## 7. Known unknowns / not yet determined

- Exact RFB **server** version string and the precise VNC security type (only client max 3.8 and "credentials required" confirmed).
- The VNC server implementation (e.g. x11vnc / TigerVNC / a bundled server) and what desktop/kiosk wraps SIGECOM.
- Whether SIGECOM itself is a web app in an embedded browser or a native GUI toolkit (visually web-styled; not confirmed at the process level).
- The true native framebuffer resolution (1258×566 was the delivered canvas; the remote desktop's own resolution/DPI not confirmed).
- Behavior and reachability of the **accounting-system connector** referenced by the integration key.
- Whether the backend applies any per-IP / rate / concurrency limits (not tested).
