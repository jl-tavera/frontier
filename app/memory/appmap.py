"""One learned map per app epoch, `memory/<app_id>/<version>/map.json` (Appendix E §4.2), plus its PNGs and crops."""
import copy
import fnmatch
import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher, get_close_matches
from pathlib import Path
from typing import Callable, Literal

import numpy as np
from PIL import Image

from app.contracts import Element, Target
from app.memory.fingerprint import Fingerprint, fingerprint, jaccard, split_title

DENYLIST = ["Integraciones", "Eliminar", "Anular", "Borrar", "Guardar*", "Enviar", "Configuración"]
SAME, AMBIGUOUS, OVERLAY_AREA, ADOPT, SAME_APP = 0.90, 0.60, 0.25, 0.5, 0.9
BAND = 0.8  # a title band OCR read a few letters off (Inicio / lnicio) is the stored one
CROP_KINDS = {"title", "menu", "button", "header"}


@dataclass
class Match:
    kind: Literal["same", "ambiguous", "new", "overlay", "blocker"]
    node_id: str | None
    sim: float
    labels: list[str] = field(default_factory=list)  # overlay labels, or the blocker's buttons


def _norm(title: str) -> str:
    return " ".join(title.split())


def _dirname(app_id: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", app_id)


def _slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-") or "screen"


def _key(title: str) -> str:
    return _slug(title).replace("-", "")


def _band_names(stored: tuple[str, ...], band: tuple[str, ...]) -> dict[str, str] | None:
    """The stored title for each of this frame's band titles when the two bands are the same up to OCR misreads."""
    # lazy: pairs titles by their sorted keys, so a misread first letter that re-sorts a multi-title band misses;
    # pair by best ratio if it bites
    pairs = list(zip(sorted(stored, key=_key), sorted(band, key=_key)))
    if len(stored) != len(band) or any(SequenceMatcher(None, _key(a), _key(b)).ratio() < BAND for a, b in pairs):
        return None
    return {b: a for a, b in pairs}


def _area(boxes) -> float:
    x0, y0, x1, y1 = zip(*boxes)
    return (max(x1) - min(x0)) * (max(y1) - min(y0))


class AppMap:
    def __init__(self, memory: Path | str, app_id: str, version: str, data: dict | None = None):
        self.memory, self.app_id, self.version = Path(memory), app_id, version
        d = data or {}
        self.titles: list[str] = d.get("titles", [])
        self.root: str | None = d.get("root")
        self.nodes: dict[str, dict] = d.get("nodes", {})
        self.edges: dict[str, dict] = d.get("edges", {})
        self.procedures: list[dict] = d.get("procedures", [])
        self.unexplored: dict[str, list] = d.get("unexplored", {})
        self.denylist: list[str] = d.get("denylist", list(DENYLIST))
        # the last confirmed sight of each known node this task, refreshed at write-back
        self.seen: dict[str, tuple[Fingerprint, list[Element], np.ndarray | None]] = {}

    @property
    def dir(self) -> Path:
        return self.memory / _dirname(self.app_id) / self.version

    def file(self, appearance: dict, name: str) -> Path:
        """A file of an appearance, in the directory of the version that recorded it."""
        return self.memory / _dirname(self.app_id) / appearance["version"] / name

    def data(self) -> dict:
        return {"app_id": self.app_id, "version": self.version, "titles": self.titles, "root": self.root,
                "nodes": self.nodes, "edges": self.edges, "procedures": self.procedures,
                "unexplored": self.unexplored, "denylist": self.denylist}

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "map.json").write_text(json.dumps(self.data(), ensure_ascii=False, indent=1), "utf-8")

    @classmethod
    def _read(cls, memory: Path, path: Path) -> "AppMap":
        d = json.loads(path.read_text("utf-8"))
        return cls(memory, d["app_id"], d["version"], d)

    @staticmethod
    def _epoch(app_dir: Path, version: str | None) -> str:
        if version and not (app_dir / version).exists():
            return version
        n = 1
        while (app_dir / f"epoch-{n}").exists():
            n += 1
        return f"epoch-{n}"

    @classmethod
    def load(cls, memory: Path | str, title: str, elements: list[Element] | None = None, w: int = 0, h: int = 0) -> "AppMap":
        """The epoch for this title bar: one that already saw it, else its app_id's directory named by the version,
        else (given the first screen) an app adopted by its root-node menus, else a cold map."""
        memory, title = Path(memory), _norm(title)
        app_id, version = split_title(title)
        # lazy: reads every stored map per load; index titles in one file if memory/ grows past a handful of epochs
        maps = [cls._read(memory, p) for p in sorted(memory.glob("*/*/map.json"), key=lambda p: (p.stat().st_mtime, p))]
        # OCR reads the same title with other case, spacing and a letter or two off: a stored app that close is this one
        # lazy: names sharing ~90 % of their letters (…Andina vs …Andes) share a map; key on the menus too if that bites
        ids = {_slug(m.app_id).replace("-", ""): m.app_id for m in maps}
        if hit := get_close_matches(_slug(app_id).replace("-", ""), ids, 1, SAME_APP):
            app_id = ids[hit[0]]
        for m in reversed(maps):
            if title in m.titles:
                return m
        if not (memory / _dirname(app_id)).is_dir() and elements is not None:
            menu, best, sim = fingerprint(elements, w, h).menu, None, ADOPT
            for m in maps:
                if m.root and (s := jaccard(m.nodes[m.root]["appearances"][0]["menu"], menu)) >= sim:
                    best, sim = m, s
            if best:
                return best.inherit(title)
        app_dir = memory / _dirname(app_id)
        # a map saved without this title, e.g. committed; its version directory may be cased as OCR first read it
        if version and (same := [m for m in maps if m.app_id == app_id and m.version.lower() == version]):
            m = same[-1]
        else:
            m = cls(memory, app_id, cls._epoch(app_dir, version))
        m.titles.append(title)
        return m

    def inherit(self, title: str) -> "AppMap":
        """A new epoch of this app copying this map: nodes stale, edges inherited, appearances and xy untouched."""
        title = _norm(title)
        new = AppMap(self.memory, self.app_id, self._epoch(self.dir.parent, split_title(title)[1]), copy.deepcopy(self.data()))
        new.titles = [title]
        for n in new.nodes.values():
            n["stale"] = True
        for e in new.edges.values():
            e["inherited"] = True
        new.save()
        return new

    def identify(self, fp: Fingerprint) -> Match:
        """Blocker, then overlay of a node, then Jaccard over atoms (max over appearances) with the title band as hard
        key, up to an OCR misread of a few letters; a misread band only ever matches as an overlay or the same node."""
        if fp.blocker:
            return Match("blocker", None, 0.0, fp.blocker)
        best = Match("new", None, 0.0)
        for nid, node in self.nodes.items():
            for a in node["appearances"]:
                if (names := _band_names(tuple(a["band"]), fp.band)) is None:
                    continue
                # the band's own atoms carry the misread too: read them as the stored titles
                atoms = {pos + "|" + names.get(text, text): v for k, v in fp.atoms.items() for pos, _, text in [k.partition("|")]}
                parent, sim = set(a["atoms"]), jaccard(a["atoms"], atoms)
                extra = [x for x in atoms if x not in parent]
                # lazy: every parent label must stay visible; loosen when OCR noise drops one under a real dropdown
                if extra and parent <= atoms.keys() and _area(atoms[x] for x in extra) < OVERLAY_AREA:
                    return Match("overlay", nid, sim, [x.split("|", 1)[1] for x in extra])
                if sim > best.sim and (sim >= SAME or tuple(a["band"]) == fp.band):  # a near title on other atoms is another screen
                    best = Match("new", nid, sim)
        kind = "same" if best.sim >= SAME else "ambiguous" if best.sim >= AMBIGUOUS else "new"
        return Match(kind, best.node_id if kind != "new" else None, best.sim)

    def upsert_node(self, fp: Fingerprint, elements: list[Element], fb: np.ndarray | None = None, node_id: str | None = None) -> str:
        """Record this version's appearance of a node (a new node when node_id is None), newest first. Given the
        framebuffer, also write its ref_png and static crops into this version's directory."""
        if node_id is None:
            node_id = base = _slug(" ".join(fp.band))
            n = 1
            while node_id in self.nodes:
                n += 1
                node_id = f"{base}-{n}"
        now = time.time()
        node = self.nodes.setdefault(node_id, {"id": node_id, "title": " · ".join(fp.band), "description": "",
                                               "transient": False, "stale": False, "seen": 0, "last_seen": None,
                                               "appearances": []})
        a = {"version": self.version, "band": list(fp.band), "atoms": sorted(fp.atoms), "menu": sorted(fp.menu),
             "ref_png": None, "crops": [], "elements_snapshot": [asdict(e) for e in elements], "last_seen": now}
        if fb is not None:
            self._write_files(node_id, a, elements, fb)
        node["appearances"] = [a] + [x for x in node["appearances"] if x["version"] != self.version]
        node.update(stale=False, seen=node["seen"] + 1, last_seen=now)
        self.root = self.root or node_id
        return node_id

    def _write_files(self, node_id: str, a: dict, elements: list[Element], fb: np.ndarray) -> None:
        """ref_png plus the static crops (title, menu, button, field-label, header bboxes padded 2 px)."""
        h, w = fb.shape[:2]
        rgb = np.ascontiguousarray(fb[:, :, 2::-1])
        (self.dir / node_id).mkdir(parents=True, exist_ok=True)
        a["ref_png"] = f"{node_id}.png"
        Image.fromarray(rgb).save(self.dir / a["ref_png"])
        for e in elements:
            if e.kind in CROP_KINDS or (e.kind == "text" and e.paired_input is not None):
                x0, y0 = max(e.bbox[0] - 2, 0), max(e.bbox[1] - 2, 0)
                x1, y1 = min(e.bbox[2] + 2, w - 1), min(e.bbox[3] + 2, h - 1)
                crop = {"bbox": [x0, y0, x1, y1], "file": f"{node_id}/{e.id}.png"}
                Image.fromarray(rgb[y0:y1 + 1, x0:x1 + 1]).save(self.dir / crop["file"])
                a["crops"].append(crop)

    def denied(self, label: str) -> bool:
        return any(fnmatch.fnmatchcase(_norm(label), pat) for pat in self.denylist)

    def locate(self, elements: list[Element], w: int, h: int, fb: np.ndarray | None = None) -> str | None:
        """The node a confirmed screen is: a known one (kept for write-back) or a new one created now.
        None when it is not confirmed: ambiguous, an overlay or a blocker."""
        fp = fingerprint(elements, w, h)
        match = self.identify(fp)
        if match.kind == "same":
            if any(tuple(a["band"]) == fp.band for a in self.nodes[match.node_id]["appearances"]):
                self.seen[match.node_id] = (fp, elements, fb)  # a misread title is no snapshot to keep
            return match.node_id
        return self.upsert_node(fp, elements, fb) if match.kind == "new" else None

    def upsert_edge(self, src: str, kind: str, target: Target, xy, to: str | None, params: dict | None = None) -> str:
        """Record this version's look of the action's target with the xy that worked. `to` None is a menu item seen
        but never clicked; a landing counts ok, clears `inherited` and adds to `outcomes`."""
        params = params or {}
        eid = f"{src}|{kind}|" + " › ".join([*filter(None, [params.get("menu")]), target.label])
        e = self.edges.setdefault(eid, {"from": src, "action": {"kind": kind, "target": {"appearances": []}, "params": params},
                                        "to": None, "effect": None, "ok": 0, "fail": 0, "last_ok": None, "outcomes": {}})
        a = {"version": self.version, "label": target.label, "role": target.role, "cell": list(target.cell), "xy": list(xy)}
        looks = e["action"]["target"]["appearances"]
        e["action"]["target"]["appearances"] = [a] + [x for x in looks if x["version"] != self.version]
        if to is not None:
            e.update(to=to, inherited=False, ok=e["ok"] + 1, last_ok=time.time())
            e["outcomes"][to] = e["outcomes"].get(to, 0) + 1
        return eid

    def learn(self, src: str, kind: str, target: Target, xy, elements: list[Element], w: int, h: int,
              fb: np.ndarray | None = None, params: dict | None = None) -> str | None:
        """After an action: upsert its edge only once the landing fingerprints as confirmed. Returns the landing node."""
        to = self.locate(elements, w, h, fb)
        if to is not None:
            self.upsert_edge(src, kind, target, xy, to, params)
        return to

    def write_back(self, describe: Callable[[list[dict]], dict[str, str]] | None = None, procedure: dict | None = None) -> None:
        """At task end: refresh this version's appearance (snapshot, ref_png, crops) of every node confirmed this task,
        describe the undescribed nodes in one batched call, keep the procedure (one per task text) and save."""
        for node_id, (fp, elements, fb) in self.seen.items():
            self.upsert_node(fp, elements, fb, node_id)
        self.seen.clear()
        if describe and (todo := [n for n in self.nodes.values() if not n["description"]]):
            for node_id, text in describe(todo).items():
                self.nodes[node_id]["description"] = text
        if procedure:
            # lazy: keyed by task_text; key by (op, entity) once F's parsed queries name them
            self.procedures = [p for p in self.procedures if p["task_text"] != procedure["task_text"]] + [procedure]
        self.save()
