import json
from pathlib import Path

import pytest

from app.memory import drift
from harness import mutate
from harness.__main__ import main

TASKS = str(Path(__file__).parent / "tasks")


def lines(tmp_path) -> list[list[dict]]:
    """Every task's JSONL under LOG_DIR, one list of lines per task."""
    return [[json.loads(x) for x in p.read_text("utf-8").splitlines()]
            for p in sorted((tmp_path / "logs").rglob("*.jsonl"))]


def test_a_rename_is_repaired_by_a_fuzzy_match_in_every_task(tmp_path, capsys):
    assert main(["mutate", "rename", "--fake", "--tasks", TASKS]) == 0
    logs = lines(tmp_path)
    assert len(logs) == 3
    for log in logs:
        drift = next(x for x in log if x["event"] == "drift")
        assert {"signal": "S1", "rung": 1, "via": "fuzzy"}.items() <= drift.items()
    assert "count     3/3" in capsys.readouterr().out


def test_a_shifted_cell_is_not_drift(tmp_path):
    assert main(["mutate", "shifted_cell", "--fake", "--tasks", TASKS]) == 0
    assert [x for log in lines(tmp_path) for x in log if x["event"] == "drift"] == []


def test_a_version_bump_is_rung_0_with_no_failed_step(tmp_path):
    assert main(["mutate", "version_bump", "--fake", "--tasks", TASKS]) == 0
    first = lines(tmp_path)[0]
    assert any(x["event"] == "drift" and x["rung"] == 0 and x["signal"] == "S5" for x in first)
    assert not [x for log in lines(tmp_path) for x in log if x["event"] == "step" and x["outcome"] == "fail"]


def test_a_missing_expected_line_fails_the_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(mutate.TABLE, "rename", [{"event": "drift", "signal": "S1", "rung": 2}])
    assert main(["mutate", "rename", "--fake", "--tasks", TASKS]) != 0
    assert "count     0/3" in capsys.readouterr().out


def test_tasks_that_fail_with_every_expected_line_still_pass_the_suite(tmp_path, capsys):
    assert main(["mutate", "unknown_screen", "--fake", "--tasks", TASKS]) == 0
    assert "count     0/3" in capsys.readouterr().out  # S3's scoring: the replan finds no route


def test_a_line_the_kind_forbids_fails_the_run(tmp_path, monkeypatch):
    monkeypatch.setitem(mutate.TABLE, "shifted_cell", [{"event": "step", "count": 0}])
    assert main(["mutate", "shifted_cell", "--fake", "--tasks", TASKS]) != 0


def test_without_f5s_mutate_it_is_not_wired(monkeypatch, capsys):
    monkeypatch.delattr(drift, "mutate")
    assert main(["mutate", "rename", "--fake", "--tasks", TASKS]) == 2
    assert "not wired" in capsys.readouterr().out
