import json

from app.log import Log
from app.sync.cache import Cache

HEADERS = ["Numero", "Cliente", "Fecha", "Valor", "Estado", "Vendedor"]
SUM_VALOR = "SELECT SUM(json_extract(data_json, '$.Valor')) FROM rows WHERE entity = ?"


def facturas(n=20, rename=None):
    rename = rename or {}
    return [
        {rename.get(h, h): v for h, v in zip(HEADERS, (f"F-{i:04}", f"Cliente {i}", "2026-10-01", 1000 * i, "Pagada", "Ana"))}
        for i in range(1, n + 1)
    ]


class FakeApp:
    """The remote app as the cache sees it: a probe per entity and a fetch per acquire."""

    def __init__(self):
        self.pages = {}  # entity -> (row_count, page1_hash)
        self.probes = []

    def probe(self, entity):
        self.probes.append(entity)
        return self.pages[entity]


def cache_for(tmp_db, app, **kw):
    return Cache("sigecom", app.probe, path=tmp_db, **kw)


def test_twenty_rows_sum_through_sql(tmp_db):
    app = FakeApp()
    app.pages["facturas"] = (20, "h1")
    cache = cache_for(tmp_db, app)
    cache.acquire("facturas", facturas, key="Numero")
    assert cache.query(SUM_VALOR, ("facturas",)) == [(210_000,)]


def test_short_read_keeps_old_rows_and_marks_partial(tmp_db):
    app = FakeApp()
    app.pages["facturas"] = (20, "h1")
    cache = cache_for(tmp_db, app)
    cache.acquire("facturas", facturas, key="Numero")
    app.pages["facturas"] = (21, "h2")
    assert cache.acquire("facturas", lambda: facturas(15), key="Numero") == "partial"
    assert cache.query(SUM_VALOR, ("facturas",)) == [(210_000,)]
    assert cache.need("facturas").status == "stale"


def test_matching_probe_hits_and_mismatch_is_stale(tmp_db):
    app = FakeApp()
    app.pages["facturas"] = (20, "h1")
    cache = cache_for(tmp_db, app)
    assert cache.need("facturas").status == "miss"
    cache.acquire("facturas", facturas, key="Numero")
    hit = cache.need("facturas")
    assert hit.status == "hit" and len(hit.rows) == 20
    app.pages["facturas"] = (20, "edited")
    assert cache.need("facturas").status == "stale"


def test_unchanged_changelog_answers_for_every_entity_without_entity_probe(tmp_db):
    app = FakeApp()
    app.pages.update(bitacora=(50, "w1"), facturas=(20, "h1"))
    cache_for(tmp_db, app).acquire("facturas", facturas, key="Numero")
    setup = cache_for(tmp_db, app)
    setup.register_changelog("bitacora")

    log = Log(tmp_db.parent / "t.jsonl")
    cache = cache_for(tmp_db, app, log=log)  # a new task
    app.probes.clear()
    assert cache.need("facturas").status == "hit"
    assert cache.need("facturas").status == "hit"
    assert app.probes == ["bitacora"]  # once per task, no per-entity probe
    events = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
    assert [(e["event"], e["scope"], e["outcome"]) for e in events] == [("sync.probe", "changelog", "hit")]


def test_changed_changelog_marks_all_stale_and_reacquires_only_the_one_asked(tmp_db):
    app = FakeApp()
    app.pages.update(bitacora=(50, "w1"), facturas=(20, "h1"), clientes=(20, "c1"))
    cache = cache_for(tmp_db, app)
    cache.acquire("facturas", facturas, key="Numero")
    cache.acquire("clientes", facturas, key="Numero")
    cache.register_changelog("bitacora")

    app.pages["bitacora"] = (51, "w2")
    fetched = []
    task = cache_for(tmp_db, app)
    app.probes.clear()
    assert task.need("facturas").status == "stale"
    assert app.probes == ["bitacora"]  # the watermark is the hash just read, not a second probe
    task.acquire("facturas", lambda: fetched.append("facturas") or facturas(), key="Numero")
    assert fetched == ["facturas"]
    assert task.need("facturas").status == "hit"
    assert task.need("clientes").status == "stale"
    assert cache_for(tmp_db, app).need("facturas").status == "hit"  # the watermark advanced


def column_map(cache, entity):
    (m,) = cache.query("SELECT column_map FROM sync_state WHERE entity = ?", (entity,))[0]
    return m and json.loads(m)


def reacquire_renamed(tmp_db, rows, **kw):
    app = FakeApp()
    app.pages["facturas"] = (20, "h1")
    cache = cache_for(tmp_db, app, **kw)
    cache.acquire("facturas", facturas, key="Numero")
    app.pages["facturas"] = (20, "h2")
    assert cache.need("facturas").status == "stale"
    cache.acquire("facturas", lambda: rows, key="Numero")
    return cache


def test_two_renamed_headers_align_and_old_sql_still_answers(tmp_db):
    # "Clientes" aligns by difflib; "Valor total" only by value agreement on the shared Numero keys
    cache = reacquire_renamed(tmp_db, facturas(rename={"Cliente": "Clientes", "Valor": "Valor total"}))
    assert column_map(cache, "facturas") == {"Cliente": "Clientes", "Valor": "Valor total"}
    assert cache.query(SUM_VALOR, ("facturas",)) == [(210_000,)]

    cache.probe = lambda entity: (2, "p1")
    cache.acquire("pagos", lambda: facturas(2), key="Numero")  # another grid that still shows "Valor"
    assert cache.query(SUM_VALOR, ("pagos",)) == [(3_000,)]


def test_header_without_counterpart_is_left_out_and_logged_as_drift(tmp_db):
    rows = facturas(rename={"Estado": "Situación", "Vendedor": "Asesor"})
    for r in rows:
        r["Situación"], r["Asesor"] = "PAID", "Luis"
    asked = []

    def llm(old, new, samples):
        asked.append((old, new))
        return {"Estado": "Situación", "Vendedor": None}

    log = Log(tmp_db.parent / "t.jsonl")
    cache = reacquire_renamed(tmp_db, rows, llm=llm, log=log)
    assert asked == [(["Estado", "Vendedor"], ["Asesor", "Situación"])]
    assert column_map(cache, "facturas") == {"Estado": "Situación"}
    drift = [e for e in map(json.loads, log.path.read_text(encoding="utf-8").splitlines()) if e["event"] == "sync.schema_drift"]
    assert [d["unaligned"] for d in drift] == [["Vendedor"]]


def test_inconclusive_alignment_leaves_no_map_and_nothing_from_the_old_epoch(tmp_db):
    def llm(old, new, samples):
        raise TimeoutError

    rows = facturas(rename={"Valor": "Importe"})
    for r in rows:
        r["Importe"] += 1  # values disagree, so only the LLM could pair it
    cache = reacquire_renamed(tmp_db, rows, llm=llm)
    assert column_map(cache, "facturas") is None
    assert cache.query(SUM_VALOR, ("facturas",)) == [(None,)]


def test_expired_snapshot_is_stale_even_when_the_probe_matches(tmp_db):
    app = FakeApp()
    app.pages["facturas"] = (20, "h1")
    cache = cache_for(tmp_db, app, expiry_s=0)
    cache.acquire("facturas", facturas, key="Numero")
    assert cache.need("facturas").status == "stale"


def test_our_own_write_advances_the_watermark(tmp_db):
    app = FakeApp()
    app.pages.update(bitacora=(50, "w1"), facturas=(20, "h1"))
    cache = cache_for(tmp_db, app)
    cache.acquire("facturas", facturas, key="Numero")
    cache.register_changelog("bitacora")
    app.pages["bitacora"] = (51, "our entry")
    cache.advance_watermark()
    assert cache_for(tmp_db, app).need("facturas").status == "hit"
