import json
from pathlib import Path

import pytest

from app.memory.appmap import AppMap
from app.memory.planner import compact, route

FIXTURE = Path(__file__).parents[1] / "fixtures" / "maps" / "sigecom_v40.json"

GOLDEN = """\
Nodes:
- Inicio: Pantalla principal con la barra de menús.
- Facturas: Lista de facturas con filtro por estado.
- Clientes: Lista de clientes con búsqueda.
- Cliente nuevo: Formulario para crear un cliente.
Edges:
- Inicio —[click "Cartera › Facturas"]→ Facturas  ok 3 fail 1
- Inicio —[click "Comercial › Clientes"]→ Clientes  ok 2 fail 0
- Clientes —[click "Nuevo"]→ Cliente nuevo  ok 1 fail 0
- Inicio —[click "Ventas › Facturas"]→ Facturas  ok 5 fail 0 (inherited)
- Inicio —[click "Herramientas › Bitácora de cambios"]→ ?  ok 0 fail 0
Procedures:
- "leer facturas pendientes": Inicio —[click "Cartera › Facturas"]→ Facturas"""


@pytest.fixture
def m(tmp_path):
    d = json.loads(FIXTURE.read_text("utf-8"))
    return AppMap(tmp_path, d["app_id"], d["version"], d)


def test_compact_renders_the_map_with_the_inherited_edge_marked(m):
    assert compact(m, "leer las facturas pendientes de octubre") == GOLDEN


def test_route_takes_the_verified_edge_over_the_inherited_one_with_the_better_ratio(m):
    assert route(m, "inicio", "facturas") == ["inicio|click|Cartera › Facturas"]


def test_route_chains_stored_edges_and_is_empty_when_no_path_exists(m):
    assert route(m, "inicio", "cliente-nuevo") == ["inicio|click|Comercial › Clientes", "clientes|click|Nuevo"]
    assert route(m, "facturas", "inicio") == []


def test_route_prefers_a_longer_verified_path_to_a_shorter_inherited_one(m):
    m.edges["inicio|click|Ventas › Cliente nuevo"] = {**m.edges["inicio|click|Ventas › Facturas"], "to": "cliente-nuevo"}
    assert route(m, "inicio", "cliente-nuevo") == ["inicio|click|Comercial › Clientes", "clientes|click|Nuevo"]
    del m.edges["clientes|click|Nuevo"]
    assert route(m, "inicio", "cliente-nuevo") == ["inicio|click|Ventas › Cliente nuevo"]  # the hint, when it's all there is
