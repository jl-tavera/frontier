import json

from app.log import Log


def test_an_event_lands_in_the_file_and_on_stdout(tmp_path, capsys):
    path = tmp_path / "t1.jsonl"
    Log(path).event("step", tool="click", cost_ms=612)

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    on_stdout = json.loads(capsys.readouterr().out)
    assert on_disk == on_stdout
    assert on_disk["event"] == "step" and on_disk["task_id"] == "t1" and on_disk["cost_ms"] == 612
