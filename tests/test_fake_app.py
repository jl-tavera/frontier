import json

from app.log import Log
from tests.fakes.fake_app import FakeSession


def _screens(tmp_path):
    (tmp_path / "inicio.json").write_text(json.dumps([
        {"id": 0, "text": "SIGECOM", "bbox": [0, 0, 300, 20], "kind": "title"},
        {"id": 1, "text": "Facturas", "bbox": [10, 30, 90, 50], "kind": "menu"},
    ]))
    (tmp_path / "facturas.json").write_text(json.dumps([
        {"id": 0, "text": "Facturas", "bbox": [0, 0, 300, 20], "kind": "title"},
        {"id": 1, "text": "Cliente", "bbox": [10, 40, 60, 55], "kind": "text", "paired_input": 2},
        {"id": 2, "text": "", "bbox": [70, 40, 200, 55], "kind": "field"},
    ]))
    return tmp_path


async def test_click_by_label_moves_screen_and_is_recorded(tmp_path):
    s = FakeSession("inicio", {("inicio", "Facturas"): "facturas", ("facturas", "esc"): "inicio"}, elements_dir=_screens(tmp_path))
    before = s.fb.copy()

    await s.click(50, 40)  # inside "Facturas"
    await s.settle()

    assert s.screen == "facturas" and s.clicks == [(50, 40)]
    assert s.elements[1].paired_input == 2 and s.elements[1].bbox == (10, 40, 60, 55)
    assert (s.fb != before).any()  # a screen change shows up in changed_bbox

    await s.click(500, 500)  # on nothing: stays put
    await s.type("Ruiz")
    await s.key("esc")
    await s.send_clipboard("hola")
    assert s.screen == "inicio" and s.clicks[-1] == (500, 500) and s.typed == ["Ruiz"] and s.keys == ["esc"]
    assert s.clipboard == "hola"


def test_log_appends_jsonl(tmp_path):
    log = Log(tmp_path / "logs" / "t1.jsonl")
    log.event("task.start", task_id="t1")
    log.event("step", task_id="t1", tool="click", args={"x": 1}, outcome="ok")
    lines = [json.loads(l) for l in (tmp_path / "logs" / "t1.jsonl").read_text("utf-8").splitlines()]
    assert [l["event"] for l in lines] == ["task.start", "step"] and lines[1]["args"] == {"x": 1}
    assert all(isinstance(l["ts"], float) for l in lines)
