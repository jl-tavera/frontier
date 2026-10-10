import asyncio
import json
import os
from pathlib import Path

import pytest

from app import runner
from app.contracts import Summary
from tests.test_main import AUTH, BODY, _wait, client  # noqa: F401  (client is a fixture)


def _post(client):
    return client.post("/tasks", json=BODY, headers=AUTH).json()["task_id"]


def test_fast_worker_ends_terminada_with_its_summary(client, monkeypatch):
    async def fast(task, session, log, budget_s):
        return Summary("terminada", "hay 12 facturas", {"n": 12})

    monkeypatch.setattr(runner, "run_task", fast)
    s = _wait(client, _post(client))
    assert (s["status"], s["summary"], s["data"]) == ("terminada", "hay 12 facturas", {"n": 12})


def test_raising_worker_ends_fallida_with_the_error(client, monkeypatch):
    async def boom(task, session, log, budget_s):
        raise ValueError("grilla vacía")

    monkeypatch.setattr(runner, "run_task", boom)
    s = _wait(client, _post(client))
    assert s["status"] == "fallida" and "grilla vacía" in s["summary"]


def test_failing_open_session_ends_fallida(client, monkeypatch):
    async def no_desktop(url, password):
        raise ConnectionError("VNC auth failed")

    monkeypatch.setattr(runner, "open_session", no_desktop)
    s = _wait(client, _post(client))
    assert s["status"] == "fallida" and "VNC auth failed" in s["summary"]


def test_overrunning_worker_is_cut_at_the_budget_and_still_summarised(client, monkeypatch):
    async def sleepy(task, session, log, budget_s):
        await asyncio.sleep(30)

    monkeypatch.setattr(runner, "BUDGET_S", 0.2)
    monkeypatch.setattr(runner, "run_task", sleepy)
    s = _wait(client, _post(client))
    assert s["status"] == "fallida" and "presupuesto" in s["summary"]


def test_each_task_logs_start_and_end_to_its_jsonl(client):
    task_id = _post(client)
    _wait(client, task_id)
    lines = (Path(os.environ["LOG_DIR"]) / f"{task_id}.jsonl").read_text("utf-8").splitlines()
    events = [json.loads(l) for l in lines]
    assert [e["event"] for e in events] == ["task.start", "task.end"]
    assert all(e["task_id"] == task_id for e in events)
    assert events[-1]["outcome"] == "terminada"


def test_a_workers_own_timeout_is_an_error_not_an_overrun(client, monkeypatch):
    async def settle_timed_out(task, session, log, budget_s):
        raise TimeoutError("settle no se estabilizó")

    monkeypatch.setattr(runner, "run_task", settle_timed_out)
    s = _wait(client, _post(client))
    assert s["status"] == "fallida" and "settle no se estabilizó" in s["summary"]
