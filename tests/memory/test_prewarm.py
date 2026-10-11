import asyncio
from dataclasses import replace
from itertools import count

from app.contracts import Target
from app.memory.appmap import AppMap
from app.memory.prewarm import prewarm
from tests.fakes.fake_app import FakeSession

V39 = "SIGECOM · Distribuidora Andina   v3.9"
MENUS = {"Archivo": "menu-archivo", "Comercial": "menu-comercial", "Cartera": "menu-cartera",
         "Herramientas": "menu-herramientas", "Ayuda": "menu-ayuda"}
ITEMS = {"Inicio": "inicio", "Clientes": "clientes", "Pedidos": "pedidos", "Facturas": "facturas",
         "Bitácora de cambios": "bitacora", "Reportes generados": "reportes", "Integraciones": "integraciones",
         "Acerca de": "acerca-de"}
SCREENS = ["inicio", *ITEMS.values()]


def menu_tree():
    """Every top menu opens its dropdown from any screen; Esc closes it, an item opens its screen."""
    t = {(s, label): menu for s in SCREENS for label, menu in MENUS.items()}
    for menu in MENUS.values():
        t[(menu, "esc")] = "inicio"
        t |= {(menu, label): screen for label, screen in ITEMS.items()}
    return t


def run(session, m, **kw):
    return asyncio.run(prewarm(session, m, lambda fb: session.elements, **kw))


def test_prewarm_records_nine_menu_items_with_unknown_landing(fake_app, tmp_path):
    session, m = fake_app("inicio", menu_tree()), AppMap.load(tmp_path, V39)
    run(session, m)

    edges = {(e["action"]["params"]["menu"], e["action"]["target"]["appearances"][0]["label"]): e
             for e in m.edges.values()}
    assert sorted(edges) == sorted([("Archivo", "Inicio"), ("Comercial", "Maestros"), ("Comercial", "Clientes"),
                                    ("Comercial", "Ventas"), ("Comercial", "Pedidos"), ("Cartera", "Facturas"),
                                    ("Herramientas", "Bitácora de cambios"), ("Herramientas", "Reportes generados"),
                                    ("Ayuda", "Acerca de")])
    assert all(e["from"] == "inicio" and e["to"] is None for e in edges.values())
    facturas = edges[("Cartera", "Facturas")]["action"]["target"]["appearances"][0]
    assert (facturas["role"], facturas["xy"], facturas["version"]) == ("menu", [280, 58], "v3.9")
    assert session.screen == "inicio" and session.keys == ["esc"] * 5


def test_prewarm_stops_at_the_budget(fake_app, tmp_path):
    session, m = fake_app("inicio", menu_tree()), AppMap.load(tmp_path, V39)
    ticks = count(0, 20)  # every look at the clock is 20 s later
    run(session, m, clock=lambda: next(ticks), budget=45)

    assert len(session.clicks) == 2  # Archivo at 20 s, Comercial at 40 s, stop at 60 s
    assert {e["action"]["params"]["menu"] for e in m.edges.values()} == {"Archivo", "Comercial"}


def click_facturas(m, session):
    """The task step Cartera › Facturas from Inicio, learnt from wherever the click actually landed."""
    asyncio.run(session.click(215, 35))
    asyncio.run(session.click(280, 58))
    return m.learn("inicio", "click", Target("Facturas", "menu", (2, 1)), (280, 58), session.elements,
                   session.w, session.h, session.fb, {"menu": "Cartera"})


def test_only_a_confirmed_landing_upserts_its_edge(fake_app, tmp_path):
    m = AppMap.load(tmp_path, V39)
    m.locate(fake_app("inicio", {}).elements, 1258, 566)

    blocked = fake_app("inicio", {**menu_tree(), ("menu-cartera", "Facturas"): "facturas-dialog"})
    assert click_facturas(m, blocked) is None and m.edges == {}  # a confirm dialog, not Facturas

    assert click_facturas(m, fake_app("inicio", menu_tree())) == "facturas"
    (e,) = m.edges.values()
    assert (e["from"], e["to"], e["ok"], e["outcomes"]) == ("inicio", "facturas", 1, {"facturas": 1})
    assert e["action"]["target"]["appearances"][0]["xy"] == [280, 58]


def test_write_back_refreshes_snapshots_and_describes_new_nodes_in_one_call(fake_app, tmp_path):
    session, m = fake_app("inicio", menu_tree()), AppMap.load(tmp_path, V39)
    run(session, m)
    click_facturas(m, session)
    asyncio.run(session.click(39, 35))  # Archivo › Inicio, with the clock moved on
    asyncio.run(session.click(108, 58))
    later = [replace(e, text="Hoy: 15/10/2026 · Usuario: operador2") if e.id == 1 else e for e in session.elements]
    assert m.learn("facturas", "click", Target("Inicio", "menu", (0, 1)), (108, 58), later, session.w, session.h,
                   session.fb, {"menu": "Archivo"}) == "inicio"

    calls = []
    describe = lambda nodes: calls.append([n["id"] for n in nodes]) or {n["id"]: f"{n['title']} screen" for n in nodes}
    m.write_back(describe, {"task_text": "leer facturas", "steps": list(m.edges)[-2:], "ok": 1, "last_ok": 1.0})

    assert calls == [["inicio", "facturas"]]
    back = AppMap.load(tmp_path, V39)
    inicio = back.nodes["inicio"]["appearances"][0]
    assert inicio["elements_snapshot"][1]["text"] == "Hoy: 15/10/2026 · Usuario: operador2"
    assert back.file(inicio, inicio["ref_png"]).is_file() and inicio["crops"]
    assert back.nodes["facturas"]["description"] == "Facturas screen"
    assert [p["task_text"] for p in back.procedures] == ["leer facturas"]

    m.write_back(describe, {"task_text": "leer facturas", "steps": [], "ok": 2, "last_ok": 2.0})
    assert len(calls) == 1 and [p["ok"] for p in AppMap.load(tmp_path, V39).procedures] == [2]


def test_visit_lands_every_item_but_never_clicks_integraciones(fake_app, tmp_path):
    session, m = fake_app("inicio", menu_tree()), AppMap.load(tmp_path, V39)
    run(session, m, visit=True)

    assert not [xy for xy in session.clicks if 260 <= xy[0] <= 460 and 114 <= xy[1] <= 134]  # Integraciones
    landed = {e["action"]["target"]["appearances"][0]["label"]: e["to"] for e in m.edges.values()}
    assert landed == {"Inicio": "inicio", "Maestros": None, "Clientes": "clientes", "Ventas": None,
                      "Pedidos": "pedidos", "Facturas": "facturas", "Bitácora de cambios": "bitacora-de-cambios",
                      "Reportes generados": "reportes-generados", "Acerca de": None}  # submenu headers, a dialog
    a = m.nodes["facturas"]["appearances"][0]
    assert m.file(a, a["ref_png"]).is_file()
    assert {e["from"] for e in m.edges.values() if e["to"] == "inicio"} == {"inicio", "clientes", "pedidos", "facturas",
                                                                   "bitacora-de-cambios", "reportes-generados"}


def test_prewarm_takes_items_ocr_reads_as_buttons_under_a_garbled_bar_label(fake_app, tmp_path):
    """Real SIGECOM: dropdown items OCR as buttons, the cursor on the clicked label garbles it (Cartera → Carjera), and
    the screen under the dropdown re-reads a pixel off."""
    session, m = fake_app("inicio", menu_tree()), AppMap.load(tmp_path, V39)

    def seen(fb):
        if not session.screen.startswith("menu-"):
            return session.elements
        return [replace(e, text=e.text[:3] + "j" + e.text[4:]) if e.kind == "menu" and e.bbox[1] < 40
                else replace(e, kind="button") if e.kind == "menu"
                else replace(e, bbox=tuple(v + 1 for v in e.bbox)) for e in session.elements]
    asyncio.run(prewarm(session, m, seen))

    labels = {(e["action"]["params"]["menu"], e["action"]["target"]["appearances"][0]["label"]) for e in m.edges.values()}
    assert ("Cartera", "Facturas") in labels and len(labels) == 9


class Laggy(FakeSession):
    """Live SIGECOM: after an item click the dropdown stays painted over the new screen through one settle."""
    held, wait = None, 0

    async def click(self, x, y):
        before = self.screen
        await super().click(x, y)
        if before.startswith("menu-") and self.screen != before:
            self.held, self.wait = self.screen, 1
            self._go(before)

    async def settle(self, *a, **kw):
        if self.held and self.wait:
            self.wait -= 1
        elif self.held:
            self._go(self.held)
            self.held = None
        return 0.0


def test_visit_after_a_reset_maps_one_home_and_every_list_screen_with_its_grid(fixtures_dir, tmp_path):
    t = menu_tree() | {("inicio-aviso", "Entendido"): "inicio", ("menu-archivo", "Inicio"): "inicio-garbled"}
    t |= {("inicio-garbled", label): menu for label, menu in MENUS.items()}
    session, m = Laggy("inicio-aviso", t, fixtures_dir / "elements"), AppMap.load(tmp_path, V39)
    run(session, m, visit=True)

    assert session.clicks[0] == (630, 311)  # Entendido, before anything else
    assert sorted(m.nodes) == ["bitacora-de-cambios", "clientes", "facturas", "inicio", "pedidos", "reportes-generados"]
    for nid in ("clientes", "pedidos", "facturas"):
        snap = m.nodes[nid]["appearances"][0]["elements_snapshot"]
        assert [e["text"] for e in snap if e["kind"] == "title"][1] == nid.capitalize()
        assert any(e["kind"] == "header" for e in snap) and not any(e["text"] == "Maestros" for e in snap)


def test_a_dialog_with_more_than_one_button_still_stops_the_prewarm(fake_app, tmp_path):
    session, m = fake_app("facturas-dialog", menu_tree()), AppMap.load(tmp_path, V39)
    run(session, m)

    assert session.clicks == [] and m.nodes == {}
