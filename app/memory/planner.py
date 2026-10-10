"""The planner's view of a map (Appendix E §4.4): the map as compact text, and ranked routes over its edges."""
import math
from difflib import SequenceMatcher

from app.memory.appmap import AppMap

HALF_LIFE, SIMILAR = 7 * 86400.0, 0.5


def _rank(e: dict) -> tuple[bool, float]:
    """Verified edges above inherited or unlanded ones, then ok/(ok+fail) × 0.5**(age/HALF_LIFE). Taken in log form,
    log ratio + ln2·last_ok/HALF_LIFE, so the order needs no clock and old timestamps don't underflow to 0."""
    if not e["ok"] or e["last_ok"] is None:
        return False, -math.inf
    return not e.get("inherited") and e["to"] is not None, math.log(e["ok"] / (e["ok"] + e["fail"])) + math.log(2) * e["last_ok"] / HALF_LIFE


def _edge(m: AppMap, eid: str) -> str:
    e, label = m.edges[eid], eid.split("|", 2)[2]  # upsert_edge's id ends in "menu › label"
    to = m.nodes[e["to"]]["title"] if e["to"] else "?"
    return f'{m.nodes[e["from"]]["title"]} —[{e["action"]["kind"]} "{label}"]→ {to}'


def compact(m: AppMap, task_text: str) -> str:
    """Node titles + descriptions, edges best-ranked first with ok/fail (inherited ones marked as hints), and the
    procedures whose task_text is similar to this task."""
    lines = ["Nodes:", *(f'- {n["title"]}: {n["description"]}' for n in m.nodes.values()), "Edges:"]
    for eid, e in sorted(m.edges.items(), key=lambda kv: _rank(kv[1]), reverse=True):
        lines.append(f'- {_edge(m, eid)}  ok {e["ok"]} fail {e["fail"]}' + (" (inherited)" if e.get("inherited") else ""))
    similar = [p for p in m.procedures if SequenceMatcher(None, p["task_text"], task_text).ratio() >= SIMILAR]
    if similar:
        lines.append("Procedures:")
    for p in similar:
        # lazy: a self-loop step renders as its raw dict; give it its own format once F stores one
        steps = " ; ".join(_edge(m, s) if isinstance(s, str) else str(s) for s in p["steps"])
        lines.append(f'- "{p["task_text"]}": {steps}')
    return "\n".join(lines)


def route(m: AppMap, src: str, dst: str) -> list[str]:
    """Edge ids from src to dst over verified edges only, else over any landed edge (inherited hints included):
    fewest hops, each hop the best-ranked edge between its two nodes. [] when there is no path."""
    ranked = sorted(m.edges.items(), key=lambda kv: _rank(kv[1]), reverse=True)
    for edges in ([kv for kv in ranked if _rank(kv[1])[0]], ranked):
        if path := _bfs(m, edges, src, dst):
            return path
    return []


def _bfs(m: AppMap, edges: list[tuple[str, dict]], src: str, dst: str) -> list[str]:
    # lazy: hop count first, rank only among parallel edges, a full edge scan per node; weigh whole paths by rank
    # and index edges by `from` if maps grow alternatives or past a few dozen nodes
    came_by: dict[str, str | None] = {src: None}
    frontier = [src]
    while frontier and dst not in came_by:
        nxt = []
        for node in frontier:
            for eid, e in edges:
                if e["from"] == node and e["to"] is not None and e["to"] not in came_by:
                    came_by[e["to"]] = eid
                    nxt.append(e["to"])
        frontier = nxt
    path, node = [], dst
    while came_by.get(node):
        path.append(came_by[node])
        node = m.edges[came_by[node]]["from"]
    return path[::-1] if node == src else []
