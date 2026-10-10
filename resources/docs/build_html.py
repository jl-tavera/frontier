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
    "f": ("F-agent-loop", "Executor"),
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


SVG = """<figure class="arch"><svg viewBox="0 0 1180 545" role="img" aria-label="Components and deployment: the evaluator calls one Railway service holding the entrypoint, task runner, executor, data sync engine, perception, tools and replay, SQLite read cache, app memory, RFB session and JSONL log; the executor calls OpenRouter and Jev, and the RFB session talks to the target desktop">
<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker><marker id="af" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--accent)"/></marker></defs>
<g class="rail"><rect x="210" y="20" width="720" height="480" rx="14"/><text x="230" y="46" class="t">Railway service · <tspan class="m">frontier-agent</tspan> · one container, one process</text></g>
<g class="ext"><rect x="16" y="70" width="150" height="56" rx="8"/><text x="28" y="92" class="t">Evaluator</text><text x="28" y="111" class="l">HTTPS + Bearer · 5 min</text></g>
<g class="box"><rect x="230" y="70" width="210" height="56" rx="8"/><text x="242" y="92" class="t">[A] Entrypoint API</text><text x="242" y="111" class="l">FastAPI · Bearer · task_id &lt; 2 s</text></g>
<g class="box"><rect x="465" y="70" width="445" height="56" rx="8"/><text x="477" y="92" class="t">[B] Task runner</text><text x="477" y="111" class="l">asyncio task per job · 270 s guard · always writes a summary</text></g>
<g class="box"><rect x="230" y="160" width="680" height="56" rx="8"/><text x="242" y="182" class="t">[C] Executor</text><text x="242" y="201" class="l">parse → executor (replay + probe) → summarize · fallbacks: Jev → VLM → planner tool-use loop</text></g>
<g class="box hi"><rect x="230" y="250" width="210" height="56" rx="8"/><text x="242" y="272" class="t">[S] Data sync engine</text><text x="242" y="291" class="l">probe, else Exportar → OCR</text></g>
<g class="box"><rect x="465" y="250" width="210" height="56" rx="8"/><text x="477" y="272" class="t">[E] Perception</text><text x="477" y="291" class="l">RapidOCR + OpenCV · on change</text></g>
<g class="box hi"><rect x="700" y="250" width="210" height="56" rx="8"/><text x="712" y="272" class="t">[D] Tools + [W] Replay</text><text x="712" y="291" class="l">stored xy → verify → repair</text></g>
<g class="box hi"><rect x="230" y="340" width="210" height="56" rx="8"/><text x="242" y="362" class="t">[DB] SQLite read cache</text><text x="242" y="381" class="l">SQL answers · app always wins</text></g>
<g class="box"><rect x="465" y="340" width="210" height="56" rx="8"/><text x="477" y="362" class="t">[F] App memory</text><text x="477" y="381" class="l">app map per app epoch (JSON)</text></g>
<g class="box"><rect x="700" y="340" width="210" height="56" rx="8"/><text x="712" y="362" class="t">[G] RFB session</text><text x="712" y="381" class="l">RFB 3.8 over WSS · clipboard</text></g>
<g class="box log"><rect x="230" y="430" width="680" height="48" rx="8"/><text x="242" y="450" class="t">[H] JSONL log</text><text x="242" y="468" class="l">every step: tool · screen · effect · signal · rung · cost → Challenge 2 spec, debrief, eval harness</text></g>
<text x="210" y="527" class="e">One Railway service · Docker python:3.12-slim + uv · uvicorn, 1 worker · no volume · CPU-only · SIGECOM's map and seeded cache ship in the image</text>
<g class="ext"><rect x="985" y="120" width="185" height="56" rx="8"/><text x="997" y="142" class="t">OpenRouter</text><text x="997" y="161" class="l">MODEL_FAST · VLM · PLANNER</text></g>
<g class="ext"><rect x="985" y="200" width="185" height="56" rx="8"/><text x="997" y="222" class="t">Jev (TypeSafe AI)</text><text x="997" y="241" class="l">typed decisions · optional</text></g>
<g class="ext"><rect x="985" y="320" width="185" height="110" rx="8"/><text x="997" y="342" class="t">Target desktop</text><text x="997" y="362" class="l">noVNC → websockify → VNC</text><text x="997" y="380" class="l">SIGECOM v3.9 · unseen app</text><text x="997" y="398" class="l">pixels only · shared login</text></g>
<g class="edge">
<line x1="166" y1="88" x2="230" y2="88"/><line x1="230" y1="110" x2="166" y2="110"/>
<line x1="440" y1="98" x2="465" y2="98"/>
<line x1="690" y1="126" x2="690" y2="160"/><text x="698" y="147" class="e">job</text>
<line x1="335" y1="216" x2="335" y2="250"/><text x="343" y="237" class="e">reads</text>
<line x1="570" y1="250" x2="570" y2="216"/><text x="578" y="237" class="e">elements</text>
<line x1="805" y1="216" x2="805" y2="250"/><text x="813" y="237" class="e">write steps</text>
<line x1="335" y1="306" x2="335" y2="340"/><text x="343" y="327" class="e">swap · SQL</text>
<line x1="805" y1="306" x2="805" y2="340"/><text x="813" y="327" class="e">act</text>
<polyline points="700,368 688,368 688,278 675,278" fill="none"/><text x="698" y="323" class="e" text-anchor="middle" transform="rotate(-90 698 323)">frames</text>
<polyline points="465,368 452,368 452,216" fill="none"/><text x="462" y="290" class="e" text-anchor="middle" transform="rotate(-90 462 290)">map</text>
<line x1="910" y1="168" x2="985" y2="168"/><text x="935" y="161" class="e">LLM calls</text>
<line x1="910" y1="208" x2="985" y2="208"/><text x="935" y="201" class="e">decide</text>
<line x1="910" y1="358" x2="985" y2="358"/><text x="935" y="351" class="e">WSS</text>
<line x1="985" y1="384" x2="910" y2="384"/><text x="935" y="399" class="e">frames</text>
</g>
</svg><figcaption>Figure 1 — Components and deployment. Letters match the tech stack in §3.2; accent borders are the fast path (replay and the read cache). Variables and storage are in §3.4.</figcaption></figure>"""

FLOW = """<figure class="arch"><svg viewBox="0 0 1180 520" role="img" aria-label="One task end to end: POST, open RFB, identify the app, load its map, parse into queries; reads probe and answer from the cache, else acquire; writes replay each step and verify, else run the repair ladder and finally the tool-use loop; everything ends in a summary within 270 seconds">
<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker><marker id="af" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--accent)"/></marker></defs>
<g class="box log"><rect x="20" y="14" width="1140" height="30" rx="8"/><text x="34" y="34" class="l"><tspan font-weight="700">270 s guard</tspan> on the whole task: whatever happens below, the runner writes a summary and a status</text></g>
<g class="box"><rect x="20" y="60" width="200" height="44" rx="8"/><text x="32" y="78" class="t">POST /tasks</text><text x="32" y="95" class="l">task_id &lt; 2 s · en_curso</text></g>
<g class="box"><rect x="20" y="120" width="200" height="44" rx="8"/><text x="32" y="138" class="t">Open RFB [G]</text><text x="32" y="155" class="l">url + password from the task</text></g>
<g class="box"><rect x="20" y="180" width="200" height="44" rx="8"/><text x="32" y="198" class="t">Identify app [E]</text><text x="32" y="215" class="l">title bar → app + version</text></g>
<g class="box"><rect x="20" y="240" width="200" height="44" rx="8"/><text x="32" y="258" class="t">Load map [F]</text><text x="32" y="275" class="l">warm · inherit · cold ≤ 45 s</text></g>
<g class="box hi"><rect x="20" y="300" width="200" height="44" rx="8"/><text x="32" y="318" class="t">Parse [C]</text><text x="32" y="335" class="l">fast model → CRUD queries</text></g>
<text x="270" y="86" class="lane">READ · each query</text>
<g class="box hi"><rect x="270" y="100" width="210" height="52" rx="8"/><text x="282" y="121" class="t">Probe [S]</text><text x="282" y="140" class="l">change-log p.1 or count + hash</text></g>
<g class="box hi"><rect x="520" y="100" width="200" height="52" rx="8"/><text x="532" y="121" class="t">SQL on the cache [DB]</text><text x="532" y="140" class="l">answer in seconds</text></g>
<g class="box slow"><rect x="270" y="180" width="250" height="44" rx="8"/><text x="282" y="198" class="t">Acquire [S]</text><text x="282" y="215" class="l">Exportar → clipboard → OCR paging</text></g>
<g class="box slow"><rect x="550" y="180" width="190" height="44" rx="8"/><text x="562" y="198" class="t">Staging → swap</text><text x="562" y="215" class="l">one transaction</text></g>
<text x="270" y="266" class="lane">WRITE · each step of the stored procedure</text>
<g class="box hi"><rect x="270" y="290" width="230" height="62" rx="8"/><text x="282" y="310" class="t">Observe [W]</text><text x="282" y="328" class="l">crops equal → stored snapshot</text><text x="282" y="344" class="l">moved → template · changed → [E]</text></g>
<g class="box hi"><rect x="530" y="290" width="150" height="62" rx="8"/><text x="542" y="310" class="t">Act + settle</text><text x="542" y="328" class="l">click stored xy</text><text x="542" y="344" class="l">wait until quiet</text></g>
<g class="box hi"><rect x="700" y="290" width="150" height="62" rx="8"/><text x="712" y="310" class="t">Verify</text><text x="712" y="328" class="l">effect matches</text><text x="712" y="344" class="l">the stored edge?</text></g>
<g class="box slow"><rect x="270" y="390" width="250" height="52" rx="8"/><text x="282" y="411" class="t">1 · Re-ground</text><text x="282" y="430" class="l">template → fuzzy → Jev ≥ 0.8 → VLM</text></g>
<g class="box slow"><rect x="545" y="390" width="135" height="52" rx="8"/><text x="557" y="411" class="t">2 · Re-explore</text><text x="557" y="430" class="l">this node only</text></g>
<g class="box slow"><rect x="705" y="390" width="125" height="52" rx="8"/><text x="717" y="411" class="t">3 · Replan</text><text x="717" y="430" class="l">one LLM call</text></g>
<g class="box slow"><rect x="855" y="390" width="170" height="52" rx="8"/><text x="867" y="411" class="t">Tool-use loop</text><text x="867" y="430" class="l">MODEL_PLANNER</text></g>
<g class="box hi"><rect x="1020" y="200" width="140" height="60" rx="8"/><text x="1032" y="223" class="t">Summary [C]</text><text x="1032" y="243" class="l">terminada / fallida</text></g>
<g class="edge fast">
<line x1="120" y1="104" x2="120" y2="120"/><line x1="120" y1="164" x2="120" y2="180"/><line x1="120" y1="224" x2="120" y2="240"/><line x1="120" y1="284" x2="120" y2="300"/>
<polyline points="220,310 245,310 245,126 270,126" fill="none"/>
<line x1="220" y1="332" x2="270" y2="332"/>
<line x1="480" y1="126" x2="520" y2="126"/><text x="500" y="118" class="e" text-anchor="middle">fresh</text>
<polyline points="720,126 1095,126 1095,200" fill="none"/><text x="905" y="118" class="e" text-anchor="middle">answer</text>
<line x1="500" y1="321" x2="530" y2="321"/><line x1="680" y1="321" x2="700" y2="321"/>
<polyline points="775,290 775,278 385,278 385,290" fill="none"/><text x="580" y="273" class="e" text-anchor="middle">ok → next step</text>
<polyline points="850,321 1075,321 1075,260" fill="none"/><text x="962" y="313" class="e" text-anchor="middle">all steps done</text>
</g>
<g class="edge slow">
<line x1="330" y1="152" x2="330" y2="180"/><text x="338" y="171" class="e">stale / miss</text>
<line x1="520" y1="202" x2="550" y2="202"/>
<line x1="620" y1="180" x2="620" y2="152"/>
<polyline points="775,352 775,372 395,372 395,390" fill="none"/><text x="585" y="386" class="e" text-anchor="middle">miss or drift (S1–S7)</text>
<line x1="520" y1="416" x2="545" y2="416"/><line x1="680" y1="416" x2="705" y2="416"/><line x1="830" y1="416" x2="855" y2="416"/>
<polyline points="1025,416 1140,416 1140,260" fill="none"/>
<polyline points="120,344 120,476 940,476 940,442" fill="none"/><text x="530" y="470" class="e" text-anchor="middle">no procedure for this query · parse unsure</text>
</g>
<g class="edge fast"><line x1="20" y1="504" x2="60" y2="504"/></g><text x="68" y="508" class="e">fast path</text>
<g class="edge slow"><line x1="150" y1="504" x2="190" y2="504"/></g><text x="198" y="508" class="e">fallback, only when the step before fails</text>
<text x="1160" y="508" class="e" text-anchor="end">[x] = component in Figure 1</text>
</svg><figcaption>Figure 2 — One task, end to end. Reads answer from the cache after a probe; writes replay the stored procedure step by step. A rung that works resumes the step, and the tool-use loop stores what it did as the procedure for next time (full ladder in §6). Write tasks never read the cache; the app always wins.</figcaption></figure>"""

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
figure.arch{margin:1em 0 1.5em}figure.arch svg{width:100%;max-width:1180px;height:auto;display:block;font:12px system-ui,sans-serif}figcaption{color:var(--muted);font-size:13px;margin-top:6px}
.rail rect{fill:var(--rail);stroke:var(--accent);stroke-width:1.5;stroke-dasharray:6 4}.box rect{fill:var(--box);stroke:var(--line);stroke-width:1.2}.box.hi rect{stroke:var(--accent);stroke-width:1.6}.box.log rect{fill:var(--code)}
.ext rect{fill:var(--ext);stroke:var(--muted);stroke-width:1.2}svg text{fill:var(--fg)}svg .t{font-weight:700;font-size:13.5px}svg .m{font-family:ui-monospace,Consolas,monospace;font-weight:400}
svg .l{font-size:11.5px;fill:var(--fg)}svg .e{font-size:10.5px;fill:var(--muted)}svg .lane{font-size:11px;font-weight:700;letter-spacing:.06em;fill:var(--muted)}
.edge line,.edge polyline{stroke:var(--muted);stroke-width:1.5;marker-end:url(#ah)}.edge.fast line,.edge.fast polyline{stroke:var(--accent);stroke-width:2.2;marker-end:url(#af)}.edge.slow line,.edge.slow polyline{stroke-dasharray:5 4}.box.slow rect{stroke-dasharray:5 4;stroke:var(--muted)}
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
    body = body.replace('<div id="flow"></div>', FLOW)
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
