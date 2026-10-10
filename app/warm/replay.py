"""Replay from the map, perception as the fallback (solution §3.3): `observe` and `replay_edge`."""
import logging
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image

from app.contracts import BBox, Effect, Element, Perceive, Session, Target
from app.memory.appmap import AppMap, Match
from app.memory.fingerprint import cell, fingerprint
from app.perception.ground import ground
from app.perception.ocr import elements as ocr_elements

log = logging.getLogger("app.warm")
MATCH = 0.95  # template-match score for "the same pixels, moved"


@dataclass
class Observation:
    node: str | None
    elements: list[Element]
    source: Literal["snapshot", "perception"]
    size: tuple[int, int]  # the frame's w, h
    match: Match | None = None  # D1's verdict when perceived, e.g. an overlay of a node


def _rgb(fb: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(fb[:, :, 2::-1])


def _ref(m: AppMap, a: dict) -> np.ndarray:
    return np.asarray(Image.open(m.file(a, a["ref_png"])).convert("RGB"))


def _cut(img: np.ndarray, b) -> np.ndarray:
    return img[b[1]:b[3] + 1, b[0]:b[2] + 1]


def _newest(m: AppMap, node_id: str) -> dict | None:
    return next((a for a in m.nodes[node_id]["appearances"] if a.get("ref_png")), None)


def _snapshot(a: dict) -> list[Element]:
    return [Element(**{**e, "bbox": tuple(e["bbox"])}) for e in a["elements_snapshot"]]


def _find(rgb: np.ndarray, crop: np.ndarray) -> tuple[int, int] | None:
    """Top-left of the one place the crop shows in the frame at a score >= MATCH; None when absent or repeated."""
    h, w = crop.shape[:2]
    if h > rgb.shape[0] or w > rgb.shape[1]:
        return None
    score = np.nan_to_num(cv2.matchTemplate(rgb, crop, cv2.TM_CCOEFF_NORMED), nan=0.0, posinf=0.0, neginf=0.0)
    hits = []
    while len(hits) < 2:
        _, best, _, (x, y) = cv2.minMaxLoc(score)
        if best < MATCH:
            break
        hits.append((x, y))
        score[max(y - h, 0):y + h, max(x - w, 0):x + w] = 0  # one peak per place
    return hits[0] if len(hits) == 1 else None


def _rewrite(m: AppMap, edge: dict, look: dict, xy, **changes) -> None:
    """This version's look of the edge's target with a new xy (and label or cell), newest first."""
    a = {**look, **changes, "version": m.version, "xy": [int(v) for v in xy]}
    looks = edge["action"]["target"]["appearances"]
    edge["action"]["target"]["appearances"] = [a] + [x for x in looks if x["version"] != m.version]


def _shift(e: Element, dx: int, dy: int) -> Element:
    return replace(e, bbox=(e.bbox[0] + dx, e.bbox[1] + dy, e.bbox[2] + dx, e.bbox[3] + dy))


def _refresh(m: AppMap, node_id: str, els: list[Element], fb: np.ndarray) -> None:
    """This version's appearance of the node as it is now (snapshot, ref_png, crops), saved, so the next look hits."""
    m.upsert_node(fingerprint(els, fb.shape[1], fb.shape[0]), els, fb, node_id)
    m.save()


def _inside(xy, b) -> bool:
    return b[0] <= xy[0] <= b[2] and b[1] <= xy[1] <= b[3]


def observe(fb: np.ndarray, m: AppMap, *, node: str | None = None, perceive: Perceive = ocr_elements) -> Observation:
    """The stored snapshot while the node's static crops match the frame byte for byte, or are each found once
    elsewhere (moved); else perception."""
    rgb, best, size = _rgb(fb), None, (fb.shape[1], fb.shape[0])
    # lazy: decodes every node's ref_png when no node is hinted; F passes the expected node
    for nid in [node] if node else m.nodes:
        a = _newest(m, nid) if nid in m.nodes else None
        if a is None or not a["crops"]:
            continue
        ref = _ref(m, a)
        if ref.shape != rgb.shape:
            continue
        bad = [c for c in a["crops"] if not np.array_equal(_cut(ref, c["bbox"]), _cut(rgb, c["bbox"]))]
        if not bad:
            log.info("fastpath: hit node=%s", nid)
            return Observation(nid, _snapshot(a), "snapshot", size)
        if best is None or len(bad) < len(best[0]):
            best = (bad, nid, a, ref)
    if best is None:
        log.info("fastpath: miss:cold")
        return _perceive(fb, m, perceive)
    bad, nid, a, ref = best
    shifts = {}  # element id -> (dx, dy); D1 names each crop file by its element id
    for c in bad:
        if (at := _find(rgb, _cut(ref, c["bbox"]))) is None:
            log.info("fastpath: miss:static_mismatch node=%s crop=%s", nid, c["file"])
            return _perceive(fb, m, perceive)
        shifts[int(Path(c["file"]).stem)] = (at[0] - c["bbox"][0], at[1] - c["bbox"][1])
    els = _snapshot(a)
    for i, e in enumerate(els):
        if (d := shifts.get(e.id)) is not None:
            els[i] = _shift(e, *d)
            for edge in (x for x in m.edges.values() if x["from"] == nid):
                look = edge["action"]["target"]["appearances"][0]
                if _inside(look["xy"], e.bbox):
                    _rewrite(m, edge, look, (look["xy"][0] + d[0], look["xy"][1] + d[1]))
    _refresh(m, nid, els, fb)
    log.info("fastpath: moved node=%s elements=%s", nid, sorted(shifts))
    return Observation(nid, els, "snapshot", size)


def _perceive(fb: np.ndarray, m: AppMap, perceive: Perceive) -> Observation:
    """C's elements and D1's fingerprint; a confirmed node is kept for write-back, a new one created."""
    els = perceive(fb)
    h, w = fb.shape[:2]
    match = m.identify(fingerprint(els, w, h))  # D2's locate drops the Match, which F needs for an overlay
    return Observation(m.locate(els, w, h, fb), els, "perception", (w, h), match)


def replay_target(target: Target, observation: Observation) -> BBox | None:
    """The bbox of the observed element that is this target, grounded by C4 (label, then fuzzy label, then cell)."""
    e = ground(target, observation.elements, *observation.size)
    return e.bbox if e else None


def _centre(b: BBox) -> tuple[int, int]:
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def _pad(b: BBox, w: int, h: int) -> BBox:
    return max(b[0] - 2, 0), max(b[1] - 2, 0), min(b[2] + 2, w - 1), min(b[3] + 2, h - 1)


def _changed(a: np.ndarray, b: np.ndarray) -> BBox | None:
    if a.shape != b.shape:
        return 0, 0, b.shape[1] - 1, b.shape[0] - 1
    ys, xs = np.nonzero((a[:, :, :3] != b[:, :, :3]).any(axis=2))
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None


def _guard(m: AppMap, edge: dict, xy, rgb: np.ndarray) -> tuple[tuple[int, int] | None, str, list[Element] | None]:
    """Where to click: the stored xy while the crop around it is unchanged, else where that crop moved to (with the
    from-node's snapshot, target moved)."""
    a = _newest(m, edge["from"]) if edge["from"] in m.nodes else None
    if a is None:
        return None, "cold", None
    snap = _snapshot(a)
    under = [e for e in snap if _inside(xy, e.bbox)]
    if not under:
        return None, "target_missing", None
    e = min(under, key=lambda e: (e.bbox[2] - e.bbox[0]) * (e.bbox[3] - e.bbox[1]))  # innermost
    ref = _ref(m, a)
    if ref.shape != rgb.shape:
        return None, "cold", None
    box = _pad(e.bbox, rgb.shape[1], rgb.shape[0])
    crop = _cut(ref, box)
    if np.array_equal(crop, _cut(rgb, box)):
        return tuple(xy), "hit", None
    if (at := _find(rgb, crop)) is None:
        return None, "target_missing", None
    dx, dy = at[0] - box[0], at[1] - box[1]
    return (xy[0] + dx, xy[1] + dy), "moved", [_shift(x, dx, dy) if x is e else x for x in snap]


async def replay_edge(edge: dict, fb: np.ndarray, session: Session, m: AppMap, *,
                      perceive: Perceive = ocr_elements) -> Effect:
    """Click the edge's last-good xy behind a crop guard (or where its crop moved), check the landing is `to`;
    on a miss recover, perceive, ground the target, click, verify and rewrite xy."""
    t0, before = time.monotonic(), fb.copy()
    look = edge["action"]["target"]["appearances"][0]
    target = Target(look["label"], look["role"], tuple(look["cell"]))

    def effect(ok: bool, detail: str, screen: str | None) -> Effect:
        return Effect(ok, _changed(before, session.fb), screen, None, detail, (time.monotonic() - t0) * 1000)

    async def land(xy) -> str | None:
        await session.click(*xy)
        await session.settle()
        return observe(session.fb, m, node=edge["to"], perceive=perceive).node

    xy, how, moved = _guard(m, edge, look["xy"], _rgb(before))
    if xy is not None:
        if await land(xy) == edge["to"]:
            if moved:
                _rewrite(m, edge, look, xy)
                _refresh(m, edge["from"], moved, before)
            log.info("fastpath: %s edge=%s xy=%s", how, target.label, xy)
            return effect(True, how, edge["to"])
        how = "no_effect" if _changed(before, session.fb) is None else "static_mismatch"
        if how == "static_mismatch":
            # lazy: Esc only; walk the recorded back edge when Esc leaves a landing open
            await session.key("esc")
            await session.settle()
    log.info("fastpath: miss:%s edge=%s", how, target.label)

    frame = session.fb.copy()
    obs = Observation(edge["from"], perceive(frame), "perception", (frame.shape[1], frame.shape[0]))
    if (bbox := replay_target(target, obs)) is None:
        return effect(False, f"miss:{how}, target not found", obs.node)
    xy = _centre(bbox)
    if await land(xy) != edge["to"]:
        return effect(False, f"miss:{how}, repair landed elsewhere", None)
    label = next(e.text for e in obs.elements if e.bbox == bbox)
    _rewrite(m, edge, look, xy, label=label, cell=list(cell(bbox, *obs.size)))
    if m.identify(fingerprint(obs.elements, *obs.size)).node_id == edge["from"]:  # recovery really got back
        _refresh(m, edge["from"], obs.elements, frame)
    m.save()
    log.info("fastpath: repaired edge=%s xy=%s", label, xy)
    return effect(True, "repaired", edge["to"])
