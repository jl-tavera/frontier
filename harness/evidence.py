"""H2: the evidence table for the Challenge 2 spec. Reads only JSONL logs; every behaviour seen is confirmed with the
`file:line` of its first appearance, every designed one never seen is assumed."""
import json

FASTPATH = ("hit", "moved", "repaired", "perceived", "llm")

# What the design claims, from solution.md §7 and Appendix E §6.1, written out by hand and not read from the code.
DESIGNED = [
    "task.start", "task.end: terminada", "task.end: fallida",
    *(f"step: {f}" for f in FASTPATH),  # §7 fastpath breakdown per step
    "sync.probe: changelog hit", "sync.probe: changelog miss", "sync.probe: entity hit", "sync.probe: entity miss",
    "drift: S1 rung 1 via fuzzy",  # renamed label: fuzzy match patches the edge
    "drift: S1 rung 2 via reexplore",  # control removed or menu item moved
    "drift: S3 rung 1 via landing",  # landing mismatch: retarget
    "drift: S4 rung 3 via replan",  # unknown screen
    "rejoin",
    "drift: S1 rung 4 via rank_down",  # persistent break
    "drift: S5 rung 0 via inherit",  # version bump: new epoch inherits the old
    "drift: S5 rung 0 via reidentify",  # redesign: one line per node
    "drift: S7 rung 0 via inherit",  # silent redesign
    "sync.schema_drift",  # redesign: renamed grid headers aligned
    "plan", "handoff",  # §7 escalation rate
]


def behaviour(r: dict) -> str:
    e, out = r.get("event", "?"), r.get("outcome")
    if e == "step" and r.get("detail") in FASTPATH:
        return f"step: {r['detail']}"
    if e == "drift":
        return " ".join([f"drift: {r.get('signal')}", *([f"rung {r['rung']}"] if r.get("rung") is not None else []),
                         *([f"via {r['via']}"] if r.get("via") else [])])
    if e == "sync.probe":
        return f"sync.probe: {r.get('scope')} {out}"
    return f"{e}: {out}" if out else e


def table(paths: list[str]) -> str:
    seen: dict[str, str] = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                try:
                    seen.setdefault(behaviour(json.loads(line)), f"{p}:{n}")
                except (json.JSONDecodeError, AttributeError):
                    continue  # blank or torn line: not evidence
    rows = [f"| {b} | confirmed | `{at}` |" for b, at in seen.items()]
    rows += [f"| {b} | assumed | - |" for b in DESIGNED if b not in seen]
    return "\n".join(["| Behaviour | Status | Evidence |", "|---|---|---|", *rows])
