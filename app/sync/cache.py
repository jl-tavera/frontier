"""Read cache behind a freshness probe (Appendix G §4.2, §4.3, §4.5).

One Cache per task: the change log is probed at most once per instance.
`probe(entity) -> (row_count, page1_hash)` and every `fetch()` are injected, so nothing here touches the screen.
"""
import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Literal

from app.log import Log

ROWS = """ (
  app_id      TEXT NOT NULL,
  entity      TEXT NOT NULL,
  natural_key TEXT NOT NULL,
  data_json   TEXT NOT NULL,
  row_hash    TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  source      TEXT NOT NULL,
  PRIMARY KEY (app_id, entity, natural_key)
);
"""
# rows_staging is rows column for column, so the swap can INSERT ... SELECT *
SCHEMA = f"CREATE TABLE IF NOT EXISTS rows{ROWS}CREATE TABLE IF NOT EXISTS rows_staging{ROWS}" + """
CREATE TABLE IF NOT EXISTS sync_state (
  app_id      TEXT NOT NULL,
  entity      TEXT NOT NULL,
  header_hash TEXT NOT NULL,
  column_map  TEXT,
  role        TEXT NOT NULL DEFAULT 'entity',
  row_count   INTEGER,
  probe_hash  TEXT,
  status      TEXT NOT NULL CHECK (status IN ('complete','partial','stale')),
  method      TEXT,
  acquired_at TEXT NOT NULL,
  PRIMARY KEY (app_id, entity)
);
"""

Probe = Callable[[str], tuple[int, str]]
Rows = list[dict]
Llm = Callable[[list[str], list[str], Rows], dict]  # (old leftovers, new leftovers, 3 sample rows) -> {old: new | None}


def _sha(obj) -> str:
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _norm(header: str) -> str:
    """Case, accents, whitespace and punctuation don't count."""
    return "".join(c for c in unicodedata.normalize("NFKD", header).lower() if c.isalnum())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Need:
    status: Literal["hit", "miss", "stale"]
    rows: Rows = field(default_factory=list)


class Cache:
    def __init__(self, app_id: str, probe: Probe, path: Path | str = "memory/cache.sqlite", log: Log | None = None,
                 expiry_s: float = 600, llm: Llm | None = None):
        self.app_id, self.probe, self.log, self.expiry_s, self.llm = app_id, probe, log, expiry_s, llm
        self._changelog_probed = False
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def acquire(self, entity: str, fetch: Callable[[], Rows], key: str | None = None, source: str = "ocr") -> str:
        """Fetch, re-probe, stage, and swap in one transaction. Returns the new status."""
        rows = fetch()
        count, page_hash = self.probe(entity)
        keyed = {self._natural_key(r, key): r for r in rows}
        header_hash = _sha(sorted({h for r in rows for h in r}))
        old = self._state(entity)
        column_map = old and old["column_map"]
        now = _now()
        with self.db:
            self.db.execute("DELETE FROM rows_staging WHERE app_id=? AND entity=?", (self.app_id, entity))
            self.db.executemany(
                "INSERT OR REPLACE INTO rows_staging VALUES (?,?,?,?,?,?,?)",
                [(self.app_id, entity, nk, json.dumps(r, ensure_ascii=False, default=str), _sha(r), now, source)
                 for nk, r in keyed.items()],
            )
            (staged,) = self.db.execute(
                "SELECT COUNT(*) FROM rows_staging WHERE app_id=? AND entity=?", (self.app_id, entity)).fetchone()
            if staged < count:  # a short read never replaces good rows
                self.db.execute(
                    "INSERT INTO sync_state (app_id, entity, header_hash, status, method, acquired_at) VALUES (?,?,?,'partial',?,?)"
                    " ON CONFLICT DO UPDATE SET status='partial'",
                    (self.app_id, entity, header_hash, source, now),
                )
                self.db.execute("DELETE FROM rows_staging WHERE app_id=? AND entity=?", (self.app_id, entity))
                self._event("sync.acquire", entity=entity, method=source, rows=staged, probe_count=count, outcome="partial")
                return "partial"
            if old and old["header_hash"] != header_hash:  # the 15:30 change: re-acquire is the migration
                old_rows = {nk: json.loads(d) for nk, d in self.db.execute(
                    "SELECT natural_key, data_json FROM rows WHERE app_id=? AND entity=?", (self.app_id, entity))}
                aligned = self._align(entity, old_rows, keyed, json.loads(column_map or "{}"))
                column_map = json.dumps(aligned, ensure_ascii=False) if aligned else None
            self.db.execute("DELETE FROM rows WHERE app_id=? AND entity=?", (self.app_id, entity))
            self.db.execute("INSERT INTO rows SELECT * FROM rows_staging WHERE app_id=? AND entity=?", (self.app_id, entity))
            self.db.execute("DELETE FROM rows_staging WHERE app_id=? AND entity=?", (self.app_id, entity))
            self.db.execute(
                "INSERT OR REPLACE INTO sync_state"
                " (app_id, entity, header_hash, column_map, role, row_count, probe_hash, status, method, acquired_at)"
                " VALUES (?,?,?,?,'entity',?,?,'complete',?,?)",
                (self.app_id, entity, header_hash, column_map, count, page_hash, source, now),
            )
        self._event("sync.acquire", entity=entity, method=source, rows=staged, probe_count=count, outcome="complete")
        return "complete"

    def need(self, entity: str) -> Need:
        """`hit` with rows when the cache can answer, else `miss` (never acquired) or `stale`."""
        st = self._state(entity)
        if st is None:
            return Need("miss")
        changelog = self._changelog()
        if changelog and not self._changelog_probed:
            self._changelog_probed = True
            probed = self.probe(changelog["entity"])
            hit = probed[1] == changelog["probe_hash"]
            self._event("sync.probe", scope="changelog", entity=changelog["entity"], outcome="hit" if hit else "miss")
            if not hit:  # v1: any change on page 1 marks every entity stale; re-acquired lazily
                self._mark_stale("role = 'entity'")
                self._watermark(changelog["entity"], probed)
            st = self._state(entity)
        if st["status"] != "complete":
            return Need("stale")
        if datetime.now(timezone.utc) - datetime.fromisoformat(st["acquired_at"]) > timedelta(seconds=self.expiry_s):
            self._mark_stale("entity = ?", entity)  # expiry backstop (G §4.2 step 3)
            return Need("stale")
        if changelog:
            return Need("hit", self._rows(entity))
        count, page_hash = self.probe(entity)
        hit = (count, page_hash) == (st["row_count"], st["probe_hash"])
        self._event("sync.probe", scope="entity", entity=entity, outcome="hit" if hit else "miss")
        if not hit:
            self._mark_stale("entity = ?", entity)
            return Need("stale")
        return Need("hit", self._rows(entity))

    def register_changelog(self, entity: str) -> None:
        """The app's change log: one probe answers for every entity (G §4.2 step 2)."""
        self._watermark(entity)

    def advance_watermark(self) -> None:
        """Re-probe the change log after our own write-through, so our entry is not read as a change."""
        if changelog := self._changelog():
            self._watermark(changelog["entity"])

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        """SQL over `json_extract(data_json, '$.Col')`; a retired header is translated through `column_map`."""
        renamed = {}
        for (m,) in self.db.execute("SELECT column_map FROM sync_state WHERE app_id=? AND column_map IS NOT NULL", (self.app_id,)):
            renamed.update(json.loads(m))
        live = {h for (h,) in self.db.execute(
            "SELECT DISTINCT j.key FROM rows, json_each(rows.data_json) AS j WHERE app_id=?", (self.app_id,))}
        renamed = {old: new for old, new in renamed.items() if old not in live}  # only a name no grid shows any more
        sql = re.sub(r"'\$\.([^'.\[]+)'", lambda m: f"'$.{renamed.get(m[1], m[1])}'", sql)
        return [tuple(r) for r in self.db.execute(sql, params)]

    def _align(self, entity: str, old: dict[str, dict], new: dict[str, dict], prior: dict) -> dict | None:
        """Old header -> new header (G §4.3.4), chained onto `prior`. None when the alignment is inconclusive."""
        old_h = sorted({h for r in old.values() for h in r})
        new_h = sorted({h for r in new.values() for h in r})
        left_old = [h for h in old_h if h not in new_h]
        left_new = [h for h in new_h if h not in old_h]
        pairs = {}

        def pair(score, threshold):
            for o in list(left_old):
                best = max(left_new, key=lambda n: score(o, n), default=None)
                if best is not None and score(o, best) >= threshold:
                    pairs[o] = best
                    left_old.remove(o)
                    left_new.remove(best)

        shared = old.keys() & new.keys()
        pair(lambda o, n: float(_norm(o) == _norm(n)), 1.0)
        pair(lambda o, n: SequenceMatcher(None, o, n).ratio(), 0.8)
        if shared:
            pair(lambda o, n: sum(old[k].get(o) == new[k].get(n) for k in shared) / len(shared), 0.9)
        if left_old and left_new and self.llm:
            try:
                answer = self.llm(list(left_old), list(left_new), list(new.values())[:3])
                if not isinstance(answer, dict):
                    raise TypeError(f"llm returned {type(answer).__name__}")
            except Exception as e:
                self._event("sync.schema_drift", entity=entity, old=old_h, new=new_h, aligned={}, unaligned=old_h,
                            outcome="inconclusive", detail=repr(e))
                return None
            for o, n in answer.items():
                if o in left_old and n in left_new:
                    pairs[o] = n
                    left_old.remove(o)
                    left_new.remove(n)
        self._event("sync.schema_drift", entity=entity, old=old_h, new=new_h, aligned=pairs, unaligned=left_old)
        chained = {a: pairs.get(b, b) for a, b in prior.items() if b in pairs or b in new_h}
        return {**chained, **pairs}

    def _state(self, entity: str) -> dict | None:
        return self._one("SELECT * FROM sync_state WHERE app_id=? AND entity=?", entity)

    def _changelog(self) -> dict | None:
        return self._one("SELECT * FROM sync_state WHERE app_id=? AND role='changelog'")

    def _one(self, sql: str, *params) -> dict | None:
        row = self.db.execute(sql, (self.app_id, *params)).fetchone()
        return dict(row) if row else None

    def _watermark(self, entity: str, probed: tuple[int, str] | None = None) -> None:
        count, page_hash = probed or self.probe(entity)
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO sync_state (app_id, entity, header_hash, role, row_count, probe_hash, status, acquired_at)"
                " VALUES (?,?,'','changelog',?,?,'complete',?)",
                (self.app_id, entity, count, page_hash, _now()),
            )

    def _rows(self, entity: str) -> Rows:
        cur = self.db.execute("SELECT data_json FROM rows WHERE app_id=? AND entity=?", (self.app_id, entity))
        return [json.loads(d) for (d,) in cur]

    def _mark_stale(self, where: str, *params) -> None:
        with self.db:
            self.db.execute(f"UPDATE sync_state SET status='stale' WHERE app_id=? AND {where}", (self.app_id, *params))

    def _event(self, name: str, **fields) -> None:
        if self.log:
            self.log.event(name, app_id=self.app_id, **fields)

    @staticmethod
    def _natural_key(row: dict, key: str | None) -> str:
        if key and key in row:
            return str(row[key])
        return _sha(sorted(map(str, row.values())))  # values only, so a header rename keeps the key
