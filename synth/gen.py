"""Practice tasks from templates over the seeded cache (S1), and the check that proves them against it.

A template's `params` is a list of steps run in order: a YAML list of choices, or SQL over the entity views bound
with the params so far. A step that returns no rows drops the combination, so "unique", "at least two" and "not in
the cache" are SQL. `respuesta` and `claves` are SQL; `diff` is a literal. `{name}` fills a param into any string,
SQL included (identifiers from choices); SQL values bind as `:name`.

`--paraphrase k` (S2) asks MODEL_FAST, through F1's OpenRouter client, for k rewrites of each instruccion. A rewrite is
kept only when every value the instruccion interpolates still appears in it verbatim; it is written as
`<template>-<nn>-v<i>` with the base task's expectation."""
import asyncio
import json
import os
import random
import re
import sqlite3
import sys
from pathlib import Path

import yaml

from app.agent.llm import chat_json

TEMPLATES = Path(__file__).with_name("templates.yaml")
PRUEBAS = Path(__file__).parents[1] / "resources" / "docs" / "references" / "pruebas"
TODAY = "2026-10-14"  # the app's Hoy: date in every capture so far
KEYS = ["id", "nivel", "instruccion", "estado_esperado", "respuesta_esperada", "claves_razon", "diff_esperado",
        "lista_blanca"]
REQUIRED = {"id", "nivel", "instruccion", "estado_esperado", "diff_esperado", "lista_blanca"}
SECRET = re.compile(r"\bSGC-\w{4}-\w{4}\b|\b(?:contraseña|password|clave)\s*[:=]\s*\S", re.I)
PARAPHRASE = """Reescribe en español la instrucción que recibes, {k} veces, como la escribiría otra persona: cambia el
registro (formal, coloquial, telegráfico) y el orden de las palabras; cada versión puede tener como mucho un error de
tipeo o una tilde de menos. Copia cada valor de "conservar" exactamente igual, carácter por carácter. No cambies lo que
se pide. Responde solo con JSON: {"variantes": ["...", ...]}"""


class CheckError(ValueError):
    pass


def _s(v) -> str:
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def _fill(x, b: dict):
    if isinstance(x, str):
        return re.sub(r"\{(\w+)\}", lambda m: _s(b[m[1]]), x)
    if isinstance(x, list):
        return [_fill(v, b) for v in x]
    if isinstance(x, dict):
        return {k: _fill(v, b) for k, v in x.items()}
    return x


def open_cache(path, entities: dict[str, list[str]]) -> sqlite3.Connection:
    """The cache, read-only, with one TEMP VIEW per entity found by its header set."""
    path = Path(path)
    if not path.is_file():
        raise CheckError(f"no cache at {path}")
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    headers: dict[tuple, set] = {}
    for app, entity, data in db.execute("SELECT app_id, entity, data_json FROM rows"):
        headers.setdefault((app, entity), set()).update(json.loads(data))
    q = lambda s: s.replace("'", "''")
    for name, sig in entities.items():
        hits = [k for k, cols in headers.items() if set(sig) <= cols]
        if len(hits) != 1:
            raise CheckError(f"{len(hits)} entities in the cache carry {sig}; {name} needs exactly one")
        (app, entity), cols = hits[0], sorted(headers[hits[0]] - {"_unparsed"})
        select = ", ".join(f"json_extract(data_json, '$.\"{q(c)}\"') AS \"{c}\"" for c in cols)
        db.execute(f"""CREATE TEMP VIEW "{name}" AS SELECT {select} FROM rows
                       WHERE app_id = '{q(app)}' AND entity = '{q(entity)}'""")
    return db


def _combos(db, steps: list, b: dict):
    if not steps:
        yield b
        return
    rows = steps[0] if isinstance(steps[0], list) else [dict(r) for r in db.execute(_fill(steps[0], b), b)]
    for r in rows:
        yield from _combos(db, steps[1:], b | r)


def _task(db, t: dict, b: dict, task_id: str) -> dict:
    out = {"id": task_id, "nivel": t["nivel"], "instruccion": _fill(t["instruccion"], b), "estado_esperado": t["estado"]}
    if "respuesta" in t:
        out["respuesta_esperada"] = "; ".join(_s(v) for v in db.execute(_fill(t["respuesta"], b), b).fetchone())
    if "claves" in t:
        out["claves_razon"] = [_s(r[0]) for r in db.execute(_fill(t["claves"], b), b)]
    return out | {"diff_esperado": _fill(t.get("diff", []), b), "lista_blanca": []}


def _values(t: dict, b: dict) -> list[str]:
    """The param values the instruccion shows; a variant must keep every one verbatim."""
    return [_s(b[n]) for n in re.findall(r"\{(\w+)\}", t["instruccion"])]


async def _paraphrase(jobs: list[tuple[str, list[str]]], k: int) -> list[list]:
    """One MODEL_FAST call per instruccion, in order. A reply that isn't {"variantes": [...]} yields none."""
    system = PARAPHRASE.replace("{k}", str(k))
    out = []
    for text, keep in jobs:
        user = json.dumps({"instruccion": text, "conservar": keep}, ensure_ascii=False)
        try:
            vs = (await chat_json("fast", [{"role": "system", "content": system}, {"role": "user", "content": user}]))["variantes"]
        except (ValueError, KeyError, TypeError) as e:
            print(f"{text!r}: no variants ({e!r})", file=sys.stderr)
            vs = []
        out.append(vs if isinstance(vs, list) else [])
    return out


def candidates(db, t: dict, today: str) -> dict[str, dict]:
    """instruccion -> params, every combination the cache allows, sorted so sampling is stable.
    The official five's instrucciones are left out, so a suite that loads both never runs one twice."""
    official = {json.loads(p.read_text(encoding="utf-8"))["instruccion"] for p in PRUEBAS.glob("*.json")}
    out = {}
    for b in _combos(db, t["params"], {"today": today}):
        if (text := _fill(t["instruccion"], b)) not in official:
            out.setdefault(text, b)
    return dict(sorted(out.items()))


def _catalogue() -> dict:
    return yaml.safe_load(TEMPLATES.read_text(encoding="utf-8"))


def gen(cache, out, per_template: int = 2, seed: int = 1, today: str = TODAY, paraphrase: int = 0) -> list[Path]:
    cat = _catalogue()
    db = open_cache(cache, cat["entities"])
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written, jobs = [], []

    def write(task: dict) -> None:
        written.append(out / f"{task['id']}.json")
        written[-1].write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    for t in cat["templates"]:
        for old in out.glob(f"{t['id']}-[0-9][0-9]*.json"):  # this template's last run, never a hand-written task
            old.unlink()
        cands = candidates(db, t, today)
        if len(cands) < per_template:
            print(f"{t['id']}: {len(cands)} of {per_template} (the cache allows no more)", file=sys.stderr)
        picks = random.Random(f"{seed}:{t['id']}").sample(list(cands.values()), min(per_template, len(cands)))
        for i, b in enumerate(picks, 1):
            task = _task(db, t, b, f"{t['id']}-{i:02}")
            write(task)
            jobs.append((task, _values(t, b)))
    if paraphrase > 0:
        seen = {task["instruccion"] for task, _ in jobs}
        replies = asyncio.run(_paraphrase([(task["instruccion"], keep) for task, keep in jobs], paraphrase))
        for (task, keep), vs in zip(jobs, replies):
            for i, v in enumerate(vs[:paraphrase], 1):
                if isinstance(v, str) and v not in seen and all(x in v for x in keep):
                    seen.add(v)
                    write(task | {"id": f"{task['id']}-v{i}", "instruccion": v})
    return written


def _structural(t) -> None:
    if not isinstance(t, dict):
        raise CheckError("not a JSON object")
    if extra := set(t) - set(KEYS):
        raise CheckError(f"unofficial keys {sorted(extra)}")
    if missing := REQUIRED - set(t):
        raise CheckError(f"missing keys {sorted(missing)}")
    if t["estado_esperado"] not in ("terminada", "fallida"):
        raise CheckError(f"estado_esperado {t['estado_esperado']!r}")
    text = json.dumps(t, ensure_ascii=False)
    envs = [v for k in ("PASSWORD", "TEAM_TOKEN") if (v := os.environ.get(k))]
    if SECRET.search(text) or any(v in text for v in envs):
        raise CheckError("password-like string")


def check(root, cache, today: str = TODAY) -> dict[str, int]:
    """Every task JSON under `root`, against the cache. Raises CheckError on the first violation."""
    cat = _catalogue()
    by_id = {t["id"]: t for t in cat["templates"]}
    db, cands = None, {}
    seen_ids, seen_text = set(), set()
    counts = {"generated": 0, "explored": 0, "official": 0}
    for p in sorted(Path(root).rglob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
            _structural(t)
            if t["id"] in seen_ids:
                raise CheckError(f"repeats id {t['id']!r}")
            if t["instruccion"] in seen_text:
                raise CheckError("repeats another task's instruccion")
            seen_ids.add(t["id"])
            seen_text.add(t["instruccion"])
            m = re.fullmatch(r"(.+)-\d\d(-v\d+)?", t["id"])
            tid = m[1] if m else t["id"]
            if t["id"].startswith("explored-"):
                counts["explored"] += 1
            elif re.fullmatch(r"E\d+", t["id"]):
                counts["official"] += 1
            elif tid in by_id:
                counts["generated"] += 1
                db = db or open_cache(cache, cat["entities"])
                if tid not in cands:
                    cands[tid] = candidates(db, by_id[tid], today)
                # a variant (-v<i>) matches every candidate whose shown values it keeps verbatim; one must agree
                want = None
                for b in cands[tid].values() if m and m[2] else [cands[tid].get(t["instruccion"])]:
                    if b is None or not all(x in t["instruccion"] for x in _values(by_id[tid], b)):
                        continue
                    want = _task(db, by_id[tid], b, t["id"]) | {"instruccion": t["instruccion"]}
                    if all(want.get(k) == t.get(k) for k in KEYS):
                        break
                if want is None:
                    raise CheckError("names a record the cache lacks, or one not unique where the template says so, "
                                     "or a variant drops a value")
                if bad := next((k for k in KEYS if want.get(k) != t.get(k)), None):
                    raise CheckError(f"{bad}: {t.get(bad)!r}, the cache says {want.get(bad)!r}")
            else:
                raise CheckError(f"no template {tid!r}")
        except (CheckError, json.JSONDecodeError) as e:
            raise CheckError(f"{p}: {e}") from None
    return counts
