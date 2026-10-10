import json
import shutil
import sqlite3

import pytest

from app.perception.grid import Grid
from app.warm.__main__ import main
from tests.fakes.fake_app import FakeSession
from tests.warm.test_map import menu_tree

APP = "SIGECOM · Distribuidora Andina"
COLUMNS = ["Código", "Cliente", "Valor", "Estado"]
FACTURAS = [{"Código": f"FV-{i}", "Cliente": "Comercial Ruiz", "Valor": f"{i}.000", "Estado": "Vencida"} for i in range(1, 6)]


@pytest.fixture
def screens(fixtures_dir, tmp_path):
    """The fixture screens plus Facturas' page 2, which Siguiente opens."""
    d = tmp_path / "elements"
    shutil.copytree(fixtures_dir / "elements", d)
    shutil.copy(d / "facturas.json", d / "facturas-p2.json")
    return d


class App:
    """A FakeSession over `screens` whose Facturas grid has 5 rows on 2 pages; `rename` changes a column's header."""

    def __init__(self, screens, rename=None):
        t = menu_tree() | {("facturas", "Siguiente"): "facturas-p2"}
        t |= {("facturas-p2", label): to for (s, label), to in menu_tree().items() if s == "facturas"}
        self.session, self.rename = FakeSession("inicio", t, screens), rename or {}

    def read_grid(self, fb):
        s = self.session
        if s.screen.startswith("facturas"):
            rows = FACTURAS[:3] if s.screen == "facturas" else FACTURAS[3:]
            return Grid([self.rename.get(c, c) for c in COLUMNS], [{self.rename.get(k, k): v for k, v in r.items()} for r in rows])
        return Grid([e.text for e in s.elements if e.kind == "header"], [])

    def run(self, memory, *args, tiebreak=None):
        async def connect(url, password):
            return self.session

        async def no_tiebreak(candidates):
            raise AssertionError(f"tie-break called with {candidates}")

        main([*args, "--url", "https://app.example", "--password", "pw", "--memory", str(memory)], connect=connect,
             perceive=lambda fb: self.session.elements, read_grid=self.read_grid, tiebreak=tiebreak or no_tiebreak)


def state(memory) -> dict[str, dict]:
    db = sqlite3.connect(memory / "cache.sqlite")
    db.row_factory = sqlite3.Row
    return {r["entity"]: dict(r) for r in db.execute("SELECT * FROM sync_state WHERE app_id = ?", (APP,))}


def test_visit_seeds_every_grid_and_registers_the_change_log(screens, tmp_path):
    App(screens).run(tmp_path, "map", "--visit")

    st = state(tmp_path)
    assert (st["facturas"]["status"], st["facturas"]["row_count"]) == ("complete", 5)
    assert st["bitacora-de-cambios"]["role"] == "changelog"
    assert {e for e, s in st.items() if s["role"] == "entity"} == {"facturas", "clientes", "pedidos", "detalle-de-pedido", "reportes-generados"}


def test_a_changed_header_on_the_next_seed_reacquires_and_fills_column_map(screens, tmp_path):
    App(screens).run(tmp_path, "map", "--visit")
    App(screens, rename={"Valor": "Monto"}).run(tmp_path, "seed", "--entities", "facturas")

    st = state(tmp_path)["facturas"]
    assert (st["status"], st["row_count"]) == ("complete", 5)
    assert json.loads(st["column_map"]) == {"Valor": "Monto"}


def test_two_change_log_candidates_ask_the_tie_break_once(screens, tmp_path):
    reportes = json.loads((screens / "reportes.json").read_text("utf-8"))
    next(e for e in reportes if e["text"] == "Reportes generados" and e["kind"] == "title")["text"] = "Historial de reportes"
    (screens / "reportes.json").write_text(json.dumps(reportes, ensure_ascii=False), "utf-8")
    calls = []

    async def tiebreak(candidates):
        calls.append(sorted(c["id"] for c in candidates))
        return calls[-1][1]

    App(screens).run(tmp_path, "map", "--visit", tiebreak=tiebreak)

    st = state(tmp_path)
    assert calls == [["bitacora-de-cambios", "historial-de-reportes"]]
    assert st["historial-de-reportes"]["role"] == "changelog" and st["bitacora-de-cambios"]["role"] == "entity"
