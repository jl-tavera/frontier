"""D's repair ladder with F's model clients (E §4.5, F §4.3): the callables `Drift` takes.

Rung 1 asks Jev (`decide`) for the target, then the VLM over the SoM image; rung 0 asks the VLM which stale node
the screen is; rung 3 asks the planner for a new route. Each answers "none" instead of raising, so a model that
misbehaves only drops the task to the next rung."""
import asyncio
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from typesafe_sdk import Choice, Noul, Score

from app.agent.llm import chat_json, openrouter
from app.memory.appmap import AppMap
from app.perception.ground import elements_text, som_image

DRIFT = ["the same screen", "moved", "renamed", "redesigned", "gone"]


def _blocking(call, llm):
    """D calls rungs 0 and 1 synchronously from its async step: run `call(client)` on its own loop in a thread."""
    # lazy: blocks the task's loop for one model call; make D's callables async if that wait starts to matter
    async def go():
        # a client of its own: the shared one is bound to the task's loop
        return await call(llm or openrouter.__wrapped__())
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, go()).result()


def _png(data: bytes) -> dict:
    return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}}


def _id(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def jev_target(decide, llm=None):
    """Rung 1's Jev step: `target` over the visible element ids, acted on by D only at ≥ 0.8, and only when
    `effect_ok` agrees the click would do what the old action did."""
    def choose(els, old: dict) -> tuple[int | None, float]:
        questions = {
            "target": Choice(instructions="Which visible element is the old action's target now?",
                             criteria={str(e.id): f"{e.kind} {e.text}" for e in els}),
            "effect_ok": Noul(instructions="Would clicking that element have the old action's effect?"),
            "drift": Score(instructions="How far has the screen drifted from the old action's?", criteria=DRIFT)}
        state = {"elements": elements_text(els), "old_action": old}
        try:
            answers = _blocking(lambda c: decide(state, questions, llm=c), llm)
        except Exception:
            return None, 0.0
        (eid, confidence), (ok, _) = answers.get("target", (None, 0.0)), answers.get("effect_ok", (None, 0.0))
        return (_id(eid), confidence) if ok is not False else (None, 0.0)
    return choose


VLM = """A desktop app changed. Each element on the screenshot is outlined with its id. Name the element that is the
old action's target now. Reply with JSON only: {"id": <element id or null>, "confidence": <0..1>}."""


def vlm_target(llm=None):
    """Rung 1's last step: MODEL_VLM re-grounds the old action on the Set-of-Mark image."""
    def choose(fb, els, old: dict) -> tuple[int | None, float]:
        text = json.dumps({"old_action": old, "elements": elements_text(els)}, ensure_ascii=False)
        messages = [{"role": "system", "content": VLM},
                    {"role": "user", "content": [{"type": "text", "text": text}, _png(som_image(fb, els))]}]
        try:
            out = _blocking(lambda c: chat_json("vlm", messages, c), llm)
            return _id(out["id"]), float(out["confidence"])
        except Exception:
            return None, 0.0
    return choose


WHICH = """A desktop app changed. The first image is the screen now; then each candidate screen as it looked before.
Which candidate is the screen now, if any? Reply with JSON only: {"id": "<candidate id>" | null}."""


def which_node(llm=None):
    """Rung 0's re-identification: MODEL_VLM picks the stale node the screen is, from their ref_png."""
    def pick(fb, candidates: list[dict]) -> str | None:
        content = [{"type": "text", "text": json.dumps([{k: c[k] for k in ("id", "title", "description")}
                                                        for c in candidates], ensure_ascii=False)},
                   _png(som_image(fb, []))]
        for c in candidates:
            if c["ref_png"] and Path(c["ref_png"]).is_file():
                content += [{"type": "text", "text": f"candidate {c['id']}:"}, _png(Path(c["ref_png"]).read_bytes())]
        try:
            return _blocking(lambda cl: chat_json("vlm", [{"role": "system", "content": WHICH},
                                                          {"role": "user", "content": content}], cl), llm).get("id")
        except Exception:
            return None
    return pick


REPLAN = """A step of a desktop app task broke. Find another route from the screen `here` to the screen `goal`
over the known edges (never the broken one). Reply with JSON only: {"edges": ["<edge id>", ...]}, or
{"edges": null} when there is none."""


def replanner(llm=None):
    """Rung 3: MODEL_PLANNER routes around the broken edge over the edges that land somewhere."""
    async def replan(m: AppMap, edge: dict, here: str | None) -> list[str] | None:
        edges = [{"id": k, "from": e["from"], "to": e["to"], "label": e["action"]["target"]["appearances"][0]["label"]}
                 for k, e in m.edges.items() if e["to"] and not e.get("broken")]
        user = json.dumps({"here": here, "goal": edge["to"], "edges": edges}, ensure_ascii=False)
        try:
            ids = (await chat_json("planner", [{"role": "system", "content": REPLAN},
                                               {"role": "user", "content": user}], llm))["edges"]
        except Exception:
            return None
        return ids if isinstance(ids, list) and ids and all(i in m.edges for i in ids) else None
    return replan
