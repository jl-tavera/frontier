"""The agent fallback (F §4.1 step 4): a MODEL_PLANNER tool-use loop for when the executor can't replay the task.
It runs the model's tool calls in batches, learns an edge from every verified click, and stores what it did as the
procedure for the task's (op, entity), so the next run replays it."""
import base64
import json

from app.agent.llm import model, openrouter
from app.agent.parse import Plan
from app.memory.appmap import AppMap
from app.memory.fingerprint import fingerprint
from app.memory.planner import compact
from app.perception.ground import elements_text, som_image

BATCH = 8
# lazy: a fixed threshold, blind to how long a turn takes; scale it by the measured turn time if slow models overrun
WRAP_S = 30  # under this many seconds left the model is told to finish with what it has
TOOLS = {  # name -> (description, params); every param is a string
    "click_text": ("Click the button, menu item or link whose text is label.", ["label"]),
    "fill_field": ("Type value into the input paired with the field label.", ["label", "value"]),
    "type": ("Type text where the caret is.", ["text"]),
    "key": ("Press a key: enter, tab, esc, ...", ["name"]),
    "go_to": ("Go to a known screen by its id or title, along the map's edges.", ["screen"]),
    "wait_for": ("Wait until text shows on screen.", ["text"]),
    "done": ("The task is complete; answer is what it asked for, or what was done.", ["answer"]),
}
SCHEMAS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {
    "type": "object", "properties": {p: {"type": "string"} for p in ps}, "required": ps}}} for n, (d, ps) in TOOLS.items()]
SYSTEM = f"""You operate a desktop business app through tools to complete a task. You never see coordinates: name each
target by its visible text.
- Return several tool calls per turn when you can. They run in order, at most {BATCH}, and a batch stops at the first one
  that fails.
- After each batch you get every call's result and the current screen as `id kind "text"` lines; `-> id` marks the
  input a label belongs to. A new or unexpected screen also comes as an image with each element's id marked.
- Call done once the task is complete, with the answer it asked for. Never answer a value you did not read on screen.

The app's map:
"""


def _screen(tools) -> tuple[str | None, list[dict]]:
    """The screen as text: the snapshot on a hit, perception on a miss, plus the SoM image only on a miss."""
    obs = tools._observe()
    parts = [{"type": "text", "text": f"Screen {obs.node or '?'}:\n{elements_text(obs.elements)}"}]
    if obs.source == "perception":
        png = base64.b64encode(som_image(tools.session.fb, obs.elements)).decode()
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}})
    return obs.node, parts


def _clock(ex) -> dict:
    left = ex.deadline - ex.loop.time()
    text = f"{left:.0f} seconds left."
    if left < WRAP_S:
        text += " Time is almost up: call done now with what you have read so far, saying what is missing."
    return {"type": "text", "text": text}


def _pin(tools) -> str | None:
    """A landing D won't confirm (a menu open over its screen) as a node of its own, so go_to can replay through it."""
    fb = tools.session.fb
    els = tools.perceive(fb)
    fp = fingerprint(els, fb.shape[1], fb.shape[0])
    return None if fp.blocker else tools.m.upsert_node(fp, els, fb)


def _store(m: AppMap, plan: Plan, task: str, steps: list[dict]) -> None:
    """The steps as the procedure for the first query's (op, entity), typed values as `$Col` params."""
    if not plan.queries or not steps:
        return
    # lazy: one procedure under the first query; split the steps per query once a hand-off carries several
    q = plan.queries[0]
    params = {str(v): f"${k}" for k, v in {**q.fields, "key": q.key}.items() if v is not None}
    for s in steps:
        if s["tool"] in ("fill_field", "type"):  # only the typed value, never a label that happens to match it
            s["args"][-1] = params.get(s["args"][-1], s["args"][-1])
    m.procedures = [p for p in m.procedures if (p.get("op"), p.get("entity")) != (q.op, q.entity)]
    m.procedures.append({"op": q.op, "entity": q.entity, "task_text": task, "steps": steps})


async def agent_loop(task: str, plan: Plan, ex) -> dict:
    """Turns of batched tool calls until `done`; `ex` is the executor holding the tools, map, client and log."""
    tools, m = ex.tools, ex.m
    here, screen = _screen(tools)
    queries = json.dumps([q.__dict__ for q in plan.queries], ensure_ascii=False, default=str)
    messages = [
        # cached where OpenRouter passes it through: this prompt and the map are the same every turn, the tools until go_to
        # joins them with the first edge
        {"role": "system", "content": [{"type": "text", "text": SYSTEM + compact(m, task),
                                        "cache_control": {"type": "ephemeral"}}]},
        {"role": "user", "content": [{"type": "text", "text": f"Task: {task}\nQueries parsed so far: {queries}"}, _clock(ex),
                                     *screen]}]
    steps: list[dict] = []
    # lazy: no turn cap, run_task's budget guard ends a model that never calls done
    while True:
        resp = await (ex.llm or openrouter()).chat.completions.create(
            # with no edges every go_to fails, so a cold map is navigated by clicking visible text (ex.m: the ladder may swap it)
            model=model("planner"), messages=messages,
            tools=[t for t in SCHEMAS if ex.m.edges or t["function"]["name"] != "go_to"])
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            return {"ok": False, "detail": msg.content or "el agente se detuvo sin terminar la tarea"}
        failed = False
        for i, call in enumerate(msg.tool_calls):
            name = call.function.name
            if failed or i >= BATCH:
                out = "not run: " + ("an earlier call in this batch failed" if failed else f"over {BATCH} calls")
            else:
                try:
                    args = json.loads(call.function.arguments or "{}")
                    values = [str(args[p]) for p in TOOLS[name][1]]
                except (KeyError, TypeError, ValueError):
                    out, failed = f"bad call: {name} {call.function.arguments}", True
                else:
                    if name == "done":
                        _store(m, plan, task, steps)
                        return {"ok": True, "answer": values[0]}
                    tools.last = None
                    e = await ex.step(name, *values)
                    to, failed = e.screen_id, not e.ok
                    clicked = e.ok and name == "click_text" and tools.last and e.changed_bbox
                    if clicked:
                        to = to or _pin(tools)
                        if here and to and to != here:
                            m.upsert_edge(here, "click", *tools.last, to)
                    if e.ok:
                        steps.append({"tool": name, "args": values, **({"expect": to} if clicked and to else {})})
                    if e.changed_bbox:  # a screen nobody identified leaves no source for the next edge
                        here = to
                    out = f"{'ok' if e.ok else 'failed'} screen={e.screen_id} signal={e.signal}: {e.detail}"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": out})
        here, screen = _screen(tools)
        messages.append({"role": "user", "content": [_clock(ex), *screen]})
