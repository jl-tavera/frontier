import time
from itertools import count

from app.memory.appmap import AppMap
from app.perception.grid import Grid
from app.warm.__main__ import main

V39 = "SIGECOM · Distribuidora Andina   v3.9"
MENUS = {"Archivo": "menu-archivo", "Comercial": "menu-comercial", "Cartera": "menu-cartera",
         "Herramientas": "menu-herramientas", "Ayuda": "menu-ayuda"}
# nine items, each landing on its own screen, plus Integraciones (denylisted)
ITEMS = {"Inicio": "inicio", "Maestros": "cliente-nuevo", "Clientes": "clientes", "Ventas": "pedido-detalle",
         "Pedidos": "pedidos", "Facturas": "facturas", "Bitácora de cambios": "bitacora",
         "Reportes generados": "reportes", "Acerca de": "factura-detalle", "Integraciones": "integraciones"}


def menu_tree():
    t = {(s, label): menu for s in ITEMS.values() for label, menu in MENUS.items()}
    for menu in MENUS.values():
        t[(menu, "esc")] = "inicio"
        t |= {(menu, label): screen for label, screen in ITEMS.items()}
    return t


def map_cmd(fake_app, tmp_path, *args, clock=time.monotonic):
    session = fake_app("inicio", menu_tree())

    async def connect(url, password):
        assert (url, password) == ("https://app.example", "pw")
        return session

    async def tiebreak(candidates):
        raise AssertionError(f"tie-break called with {candidates}")

    main(["map", "--url", "https://app.example", "--password", "pw", "--memory", str(tmp_path), *args],
         connect=connect, perceive=lambda fb: session.elements, clock=clock,
         read_grid=lambda fb: Grid([], []), tiebreak=tiebreak)  # --visit then seeds: empty grids keep it off OCR
    return session, AppMap.load(tmp_path, V39)


def test_visit_maps_nine_nodes_with_snapshots_crops_and_clicked_xy(fake_app, tmp_path):
    session, m = map_cmd(fake_app, tmp_path, "--visit")

    assert (tmp_path / "SIGECOM · Distribuidora Andina" / "v3.9" / "map.json").is_file()
    assert len(m.nodes) == 9
    for node in m.nodes.values():
        a = node["appearances"][0]
        assert a["elements_snapshot"] and a["crops"] and m.file(a, a["ref_png"]).is_file()
        assert all(m.file(a, c["file"]).is_file() for c in a["crops"])
    confirmed = [e for e in m.edges.values() if e["to"]]
    assert {e["to"] for e in confirmed} == set(m.nodes)
    assert all(tuple(e["action"]["target"]["appearances"][0]["xy"]) in session.clicks for e in confirmed)
    assert not [xy for xy in session.clicks if 260 <= xy[0] <= 460 and 114 <= xy[1] <= 134]  # Integraciones


def test_budget_stops_the_walk(fake_app, tmp_path):
    ticks = count(0, 20)  # every look at the clock is 20 s later
    session, m = map_cmd(fake_app, tmp_path, "--visit", "--budget", "45", clock=lambda: next(ticks))

    # Archivo opened at 20 s, its item Inicio visited at 40 s, the walk stops at 60 s before Comercial
    assert session.clicks == [(39, 35), (39, 35), (108, 58)] and list(m.nodes) == ["inicio"]
