# /// script
# requires-python = ">=3.12"
# dependencies = ["markdown>=3.7"]
# ///
"""Render the design doc and its appendixes to HTML.

  uv run resources/docs/build_html.py

Writes resources/docs/solution.html (main doc + every appendix inline; this path is the published URL)
and resources/docs/appendixes/<stem>.html (one standalone page per appendix).
"""
import html
import re
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent
APP_DIR = DOCS / "appendixes"
POC = DOCS.parent.parent / "poc" / "rfb_poc.py"
TOP = "#frontier-challenge-1-solution"

# letter -> (file stem under appendixes/, title)
APPENDIXES = {
    "a": ("A-challenge-brief", "Challenge brief"),
    "b": ("B-target-recon", "Target recon (SIGECOM over noVNC)"),
    "c": ("C-transport-rfb", "Transport: raw RFB over WebSocket"),
    "d": ("D-mapping-papers", "Platform mapping: paper comparison"),
    "e": ("E-mapping-methodology", "Platform mapping: methodology"),
    "f": ("F-agent-loop", "Agent loop"),
    "g": ("G-data-sync", "Data sync and read cache"),
    "h": ("H-perception", "Screen perception"),
    "i": ("I-poc-reference", "POC reference"),
}
LETTERS = list(APPENDIXES)
POC_RE = re.compile(r"`(poc/rfb_poc\.py)(:[\d\-]+)?`")
EXTENSIONS = ["tables", "fenced_code", "toc", "attr_list", "md_in_html", "sane_lists"]


def read_appendix(letter: str) -> str:
    return (APP_DIR / f"{APPENDIXES[letter][0]}.md").read_text(encoding="utf-8")


def poc_md(standalone: bool) -> str:
    code = POC.read_text(encoding="utf-8")
    doc = code.split('"""')[1].strip()
    title = "# POC reference: `poc/rfb_poc.py`" if standalone else "## Appendix I — POC reference: `poc/rfb_poc.py` {: #appendix-i }"
    return "\n".join([
        title, "",
        "> Appendix I of [solution.md](../solution.md) · Status: proof of concept, the base of component [G]; track 1.1 moves the credentials from `.env` to the request." if standalone
        else "> Appendix I · Status: proof of concept, the base of component [G]; track 1.1 moves the credentials from `.env` to the request.", "",
        "_What the proof of concept already implements: the RFB handshake and VNC auth over WSS, Raw + CopyRect framebuffer, "
        "`shared=1`, quiet-time `settle`, `click` / `type` / `key`, `changed_bbox`, `ServerCutText` receive, and a stdio MCP stub._", "",
        "```", doc, "```", "", "```python", code, "```",
    ])


def inline_md(letter: str) -> str:
    """Appendix text for solution.html: title -> 'Appendix X' heading, headings one level down, POC refs -> anchor."""
    if letter == "i":
        return poc_md(standalone=False)
    stem, title = APPENDIXES[letter]
    out = [f"## Appendix {letter.upper()} — {title} {{: #appendix-{letter} }}", "",
           f"_Source: `resources/docs/appendixes/{stem}.md` · [open as its own page](appendixes/{stem}.html)_", ""]
    fence = False
    for line in read_appendix(letter).splitlines():
        if line.startswith("```"):
            fence = not fence
        if not fence:
            if line.startswith("# "):
                out.append(f"**{line[2:].strip()}**")
                continue
            if line.startswith("#"):
                line = "#" + line
            line = POC_RE.sub(lambda m: f"[`{m.group(1)}{m.group(2) or ''}`](#appendix-i)", line)
        out.append(line)
    return "\n".join(out)


def standalone_md(letter: str) -> str:
    if letter == "i":
        return poc_md(standalone=True)
    out, fence = [], False
    for line in read_appendix(letter).splitlines():
        if line.startswith("```"):
            fence = not fence
        if not fence:
            line = POC_RE.sub(lambda m: f"[`{m.group(1)}{m.group(2) or ''}`](../solution.html#appendix-i)", line)
        out.append(line)
    return "\n".join(out)


def render(md_text: str) -> tuple[str, str]:
    md = markdown.Markdown(extensions=EXTENSIONS, extension_configs={"toc": {"toc_depth": "2-3", "permalink": "¶"}})
    body = md.convert(md_text)
    body = body.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    return body, md.toc


def mini_tocs(body: str) -> str:
    """solution.html: after each appendix's status blockquote, list that appendix's sections."""
    def add(m):
        letter, section = m.group(1), m.group(0)
        items = []
        for hid, inner in re.findall(r'<h3 id="([^"]+)">(.*?)</h3>', section, flags=re.S):
            text = re.sub(r"<[^>]+>", "", inner).replace("¶", "").strip()
            items.append(f'<li><a href="#{hid}">{text}</a></li>')
        if not items:
            return section
        stem = APPENDIXES[letter][0]
        nav = (f'<nav class="mini-toc"><strong>In this appendix</strong> · <a href="appendixes/{stem}.html">open as its own page →</a>'
               f'<ol>{"".join(items)}</ol></nav>')
        # insert after the first blockquote (the status line); fall back to after the heading
        if "</blockquote>" in section:
            return section.replace("</blockquote>", "</blockquote>" + nav, 1)
        return re.sub(r"(</h2>)", r"\1" + nav.replace("\\", "\\\\"), section, count=1)
    return re.sub(r'<h2 id="appendix-([a-i])".*?(?=<h2 id="appendix-|\Z)', add, body, flags=re.S)


SVG = """<figure class="arch"><svg viewBox="0 0 1180 880" role="img" aria-label="Architecture: evaluator calls the Railway service; inside it the entrypoint, task runner, agent loop, tools, perception, data sync engine, RFB session, app memory, SQLite read cache and JSONL log; the agent loop calls the Anthropic API and the RFB session talks to the target desktop">
<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker></defs>
<g class="rail"><rect x="230" y="20" width="640" height="840" rx="14"/><text x="250" y="46" class="t">Railway service · <tspan class="m">frontier-agent</tspan> · one container, one process</text></g>
<g class="ext"><rect x="20" y="70" width="170" height="90" rx="8"/><text x="32" y="92" class="t">Evaluator</text><text x="32" y="112" class="l">hidden eval set</text><text x="32" y="128" class="l">task + {url, password}</text><text x="32" y="144" class="l">5 min per task</text></g>
<g class="box"><rect x="260" y="70" width="270" height="80" rx="8"/><text x="272" y="92" class="t">[A] Entrypoint API</text><text x="272" y="110" class="l">FastAPI + uvicorn · Bearer auth</text><text x="272" y="125" class="l">POST /tasks → task_id &lt; 2 s</text><text x="272" y="140" class="l">GET /tasks/{id} · GET /health</text></g>
<g class="box"><rect x="560" y="70" width="280" height="80" rx="8"/><text x="572" y="92" class="t">[B] Task Runner</text><text x="572" y="110" class="l">asyncio task per job</text><text x="572" y="125" class="l">270 s budget guard · in-process state</text><text x="572" y="140" class="l">always writes a summary</text></g>
<g class="box hi"><rect x="260" y="190" width="580" height="90" rx="8"/><text x="272" y="212" class="t">[C] Agent Loop — plan → act → verify → replan → summarize</text><text x="272" y="232" class="l">Anthropic Python SDK · claude-opus-5-5 (plan, replan, recover) · claude-sonnet-5-5 optional routine tier</text><text x="272" y="248" class="l">batched tool use → plan-then-execute · prompt caching · optional Jev System 1 gate</text><text x="272" y="264" class="l">picks element ids (Set-of-Mark), never x,y</text></g>
<g class="box"><rect x="260" y="320" width="270" height="100" rx="8"/><text x="272" y="342" class="t">[D] Tool Layer</text><text x="272" y="360" class="l">plain Python functions, no MCP</text><text x="272" y="375" class="l">low: click · type · key · screenshot</text><text x="272" y="390" class="l">mid: click_text · fill_field · wait_for</text><text x="272" y="405" class="l">high: navigate_to, read_grid, export</text></g>
<g class="box"><rect x="560" y="320" width="280" height="100" rx="8"/><text x="572" y="342" class="t">[E] Perception</text><text x="572" y="360" class="l">RapidOCR (ONNX, Latin PP-OCRv5)</text><text x="572" y="375" class="l">OpenCV boxes + grid lines · numpy</text><text x="572" y="390" class="l">UI tree · fingerprint · changed_bbox</text><text x="572" y="405" class="l">Tesseract fallback · line-pixel cache</text></g>
<g class="box hi"><rect x="260" y="460" width="270" height="100" rx="8"/><text x="272" y="482" class="t">[S] Data Sync Engine (track 4)</text><text x="272" y="500" class="l">need(entity), not screens · lazy</text><text x="272" y="515" class="l">ladder: Exportar → clipboard → OCR</text><text x="272" y="530" class="l">probe: count + page-1 hash · expiry</text><text x="272" y="545" class="l">staging → atomic swap · app wins</text></g>
<g class="box"><rect x="260" y="600" width="270" height="100" rx="8"/><text x="272" y="622" class="t">[F] App Memory (nav map)</text><text x="272" y="640" class="l">one JSON per app, keyed by title</text><text x="272" y="655" class="l">nodes · edges · procedures · frontier</text><text x="272" y="670" class="l">semantic targets, never x,y</text><text x="272" y="685" class="l">written back after every task</text></g>
<g class="box hi"><rect x="560" y="600" width="280" height="100" rx="8"/><text x="572" y="622" class="t">[DB] SQLite read cache</text><text x="572" y="640" class="l">stdlib sqlite3 · WAL · one file</text><text x="572" y="655" class="l">rows(app, entity, key, data_json)</text><text x="572" y="670" class="l">sync_state(count, hash, status)</text><text x="572" y="685" class="l">json_extract → SQL filters · ephemeral</text></g>
<g class="box"><rect x="560" y="460" width="280" height="100" rx="8"/><text x="572" y="482" class="t">[G] RFB Session</text><text x="572" y="500" class="l">websockets ≥13 · pycryptodome (DES)</text><text x="572" y="515" class="l">Raw + CopyRect (lossless) · shared=1</text><text x="572" y="530" class="l">settle (quiet-time) · clipboard</text><text x="572" y="545" class="l">numpy framebuffer 1280×800</text></g>
<g class="box log"><rect x="260" y="730" width="580" height="60" rx="8"/><text x="272" y="750" class="t">[H] JSONL structured log</text><text x="272" y="767" class="l">every step: tool · args · screen_id · diff · outcome · signal · rung · cost_ms · sync.probe/acquire/fallback</text><text x="272" y="782" class="l">→ Challenge 2 spec · debrief · eval harness · mutation suite</text></g>
<text x="250" y="822" class="l">Deploy: one Railway service · Docker python:3.12-slim + uv · uvicorn, 1 worker on $PORT</text>
<text x="250" y="838" class="l">GET /health check · env TEAM_TOKEN, ANTHROPIC_API_KEY · no volume · CPU-only</text>
<g class="ext"><rect x="910" y="190" width="250" height="90" rx="8"/><text x="922" y="212" class="t">Anthropic API</text><text x="922" y="232" class="l">Messages API · tool use</text><text x="922" y="248" class="l">prompt caching</text><text x="922" y="264" class="l">claude-opus-5-5 / sonnet-5-5</text></g>
<g class="ext"><rect x="910" y="430" width="250" height="170" rx="8"/><text x="922" y="452" class="t">Target desktop (Railway)</text><text x="922" y="472" class="l">noVNC page · /health</text><text x="922" y="488" class="l">websockify → VNC server</text><text x="922" y="504" class="l">(Docker 86a79607eef2:0)</text><text x="922" y="520" class="l">SIGECOM v3.9 · unseen app</text><text x="922" y="536" class="l">pixels only · no DOM, no API</text><text x="922" y="552" class="l">shared: operador / operador2</text></g>
<g class="edge">
<line x1="190" y1="100" x2="260" y2="100"/><text x="225" y="92" class="e" text-anchor="middle">HTTPS + Bearer</text>
<line x1="260" y1="125" x2="190" y2="125"/><text x="225" y="142" class="e" text-anchor="middle">task_id · status</text>
<line x1="530" y1="110" x2="560" y2="110"/>
<line x1="700" y1="150" x2="700" y2="190"/><text x="708" y="175" class="e">asyncio task</text>
<line x1="395" y1="280" x2="395" y2="320"/><text x="403" y="305" class="e">tool calls</text>
<line x1="700" y1="320" x2="700" y2="280"/><text x="708" y="305" class="e">elements · effects</text>
<polyline points="530,370 545,370 545,485 560,485" fill="none"/><text x="552" y="455" class="e" text-anchor="end">act</text>
<line x1="395" y1="420" x2="395" y2="460"/><text x="403" y="445" class="e">read_grid · export</text>
<line x1="530" y1="535" x2="560" y2="535"/><text x="545" y="575" class="e" text-anchor="middle">navigate · clipboard · OCR</text>
<line x1="700" y1="460" x2="700" y2="420"/><text x="708" y="445" class="e">framebuffer</text>
<polyline points="260,650 245,650 245,235 260,235" fill="none"/><text x="240" y="440" class="e" text-anchor="middle" transform="rotate(-90 240 440)">nav map</text>
<polyline points="500,560 500,580 700,580 700,600" fill="none"/><text x="610" y="575" class="e" text-anchor="middle">staging → atomic swap · SQL answers back</text>
<line x1="840" y1="225" x2="910" y2="225"/><text x="875" y="215" class="e" text-anchor="middle">Messages API</text>
<line x1="910" y1="250" x2="840" y2="250"/><text x="875" y="266" class="e" text-anchor="middle">tool_use</text>
<line x1="840" y1="500" x2="910" y2="500"/><text x="875" y="490" class="e" text-anchor="middle">WSS /websockify</text>
<line x1="910" y1="525" x2="840" y2="525"/><text x="875" y="541" class="e" text-anchor="middle">RFB 3.8 frames</text>
</g>
</svg><figcaption>Architecture and deployment. Letters match §3.1 and the tech stack in §3.2; [S] and [DB] are the data sync design (track 4, Appendix G).</figcaption></figure>"""

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>
:root{--bg:#fbfbfa;--fg:#1c1c1c;--muted:#5f6368;--line:#dcdcd7;--accent:#2563eb;--box:#fff;--rail:#eef3ff;--ext:#f4f4f1;--code:#f1f1ee;--side:#f4f4f1}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111214;--fg:#e8e8e6;--muted:#a0a3aa;--line:#2c2e33;--accent:#7aa2ff;--box:#1b1d22;--rail:#161b2a;--ext:#17181c;--code:#1a1b1f;--side:#141518}}
:root[data-theme="dark"]{--bg:#111214;--fg:#e8e8e6;--muted:#a0a3aa;--line:#2c2e33;--accent:#7aa2ff;--box:#1b1d22;--rail:#161b2a;--ext:#17181c;--code:#1a1b1f;--side:#141518}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:16px}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{display:grid;grid-template-columns:290px minmax(0,1fr)}
nav.side{position:sticky;top:0;height:100vh;overflow:auto;background:var(--side);border-right:1px solid var(--line);padding:16px;font-size:13px}
nav.side .brand{font-weight:700;font-size:14px;margin-bottom:8px}nav.side .brand a{color:var(--fg);text-decoration:none}nav.side ul{list-style:none;margin:0;padding-left:0}nav.side ul ul{padding-left:12px;border-left:1px solid var(--line);margin-left:4px}
nav.side li{margin:2px 0}nav.side a{color:var(--fg);text-decoration:none;display:block;padding:2px 6px;border-radius:4px}nav.side a:hover{background:var(--box);color:var(--accent)}
main{padding:24px 32px 80px;max-width:1080px;min-width:0}
.crumbs{font-size:13px;color:var(--muted);margin:0 0 14px;display:flex;flex-wrap:wrap;gap:4px 10px}.crumbs a{color:var(--accent);text-decoration:none}.crumbs a:hover{text-decoration:underline}
h1{font-size:30px;margin:.2em 0 .5em}h2{font-size:22px;margin-top:2.2em;padding-bottom:.25em;border-bottom:1px solid var(--line)}h3{font-size:17px;margin-top:1.8em}h4{font-size:15.5px}h5{font-size:14.5px}
h2[id^="appendix-"]{margin-top:3em;border-bottom:3px solid var(--accent)}
a{color:var(--accent)}.headerlink{opacity:0;margin-left:.3em;text-decoration:none;font-size:.8em}h1:hover .headerlink,h2:hover .headerlink,h3:hover .headerlink,h4:hover .headerlink{opacity:.6}
.mini-toc{background:var(--side);border:1px solid var(--line);border-radius:6px;padding:8px 14px;font-size:13.5px;margin:12px 0 20px}.mini-toc ol{margin:6px 0 2px;padding-left:20px;columns:2;column-gap:28px}.mini-toc li{break-inside:avoid}.mini-toc a{text-decoration:none}.mini-toc a:hover{text-decoration:underline}
.tw{overflow-x:auto;margin:1em 0}table{border-collapse:collapse;font-size:13.5px;min-width:100%}th,td{border:1px solid var(--line);padding:6px 10px;vertical-align:top;text-align:left}th{background:var(--side)}
td ul{margin:0;padding-left:18px}td p{margin:0}
pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:12px 14px;overflow:auto;font-size:12.5px;line-height:1.4}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--code);padding:1px 4px;border-radius:3px;font-size:.92em}pre code{background:none;padding:0;font-size:inherit}
blockquote{border-left:3px solid var(--accent);margin:1em 0;padding:.2em 1em;color:var(--muted)}hr{border:0;border-top:1px solid var(--line);margin:2.5em 0}
figure.arch{margin:1em 0 1.5em}figure.arch svg{width:100%;height:auto;display:block;font:12px system-ui,sans-serif}figcaption{color:var(--muted);font-size:13px;margin-top:6px}
.rail rect{fill:var(--rail);stroke:var(--accent);stroke-width:1.5;stroke-dasharray:6 4}.box rect{fill:var(--box);stroke:var(--line);stroke-width:1.2}.box.hi rect{stroke:var(--accent);stroke-width:1.6}.box.log rect{fill:var(--code)}
.ext rect{fill:var(--ext);stroke:var(--muted);stroke-width:1.2}svg text{fill:var(--fg)}svg .t{font-weight:700;font-size:13.5px}svg .m{font-family:ui-monospace,Consolas,monospace;font-weight:400}
svg .l{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:10.5px;fill:var(--fg)}svg .e{font-size:10.5px;fill:var(--muted)}
.edge line,.edge polyline{stroke:var(--muted);stroke-width:1.5;marker-end:url(#ah)}
@media (max-width:900px){.wrap{display:block}nav.side{position:static;height:auto;max-height:40vh;border-right:0;border-bottom:1px solid var(--line)}main{padding:16px}h1{font-size:24px}}
@media (max-width:700px){.mini-toc ol{columns:1}}
@media print{nav.side,.crumbs,.mini-toc{display:none}.wrap{display:block}main{max-width:none;padding:0}h2[id^="appendix-"]{break-before:page}pre{white-space:pre-wrap}a{color:inherit}}
</style></head><body><div class="wrap">
<nav class="side"><div class="brand">%(brand)s</div>%(toc)s</nav>
<main>%(crumbs)s%(body)s</main>
</div></body></html>"""


def page(title, brand, toc, body, crumbs=""):
    return (TEMPLATE.replace("%(title)s", html.escape(title)).replace("%(brand)s", brand)
            .replace("%(toc)s", toc).replace("%(crumbs)s", crumbs).replace("%(body)s", body))


def build_solution():
    md_src = (DOCS / "solution.md").read_text(encoding="utf-8")
    body, toc = render("\n\n".join([md_src] + [inline_md(k) for k in LETTERS]))
    body = body.replace('<div id="arch"></div>', SVG)
    for k, (stem, _) in APPENDIXES.items():  # .md links from solution.md and from inside the appendixes -> anchors
        body = body.replace(f'href="appendixes/{stem}.md"', f'href="#appendix-{k}"').replace(f'href="{stem}.md"', f'href="#appendix-{k}"')
    body = body.replace('href="../solution.md"', f'href="{TOP}"').replace('href="../references/', 'href="references/')
    body = mini_tocs(body)
    out = DOCS / "solution.html"
    out.write_text(page("Frontier Challenge 1 — Solution", "Frontier Challenge 1", toc, body), encoding="utf-8")
    return out


def build_appendix(letter: str):
    stem, title = APPENDIXES[letter]
    body, toc = render(standalone_md(letter))
    for k, (s, _) in APPENDIXES.items():  # sibling .md links -> sibling pages
        body = body.replace(f'href="{s}.md"', f'href="{s}.html"')
    body = body.replace('href="../solution.md"', 'href="../solution.html"')
    i = LETTERS.index(letter)
    prev_ = f'<a href="{APPENDIXES[LETTERS[i-1]][0]}.html">← Appendix {LETTERS[i-1].upper()}</a>' if i else ""
    next_ = f'<a href="{APPENDIXES[LETTERS[i+1]][0]}.html">Appendix {LETTERS[i+1].upper()} →</a>' if i + 1 < len(LETTERS) else ""
    crumbs = (f'<div class="crumbs"><a href="../solution.html">← Solution design</a><span>Appendix {letter.upper()} of {LETTERS[-1].upper()}</span>'
              f'<a href="../solution.html#appendix-{letter}">inline version</a>{prev_}{next_}</div>')
    out = APP_DIR / f"{stem}.html"
    out.write_text(page(f"Appendix {letter.upper()} — {title}", f'<a href="../solution.html">Frontier Challenge 1</a> · Appendix {letter.upper()}', toc, body, crumbs), encoding="utf-8")
    return out


def main():
    outs = [build_solution()] + [build_appendix(k) for k in LETTERS]
    for o in outs:
        print(f"wrote {o.relative_to(DOCS.parent.parent)} ({o.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
