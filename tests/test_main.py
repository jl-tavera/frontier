import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import runner
from app.contracts import Summary
from app.main import app
from tests.fakes.fake_app import FakeSession

AUTH = {"Authorization": "Bearer test-token"}
BODY = {"task": "¿Cuántas facturas hay?", "desktop": {"url": "wss://desktop.example/ws", "password": "x"}}


def _wait(client, task_id):
    deadline = time.time() + 5
    while (s := client.get(f"/tasks/{task_id}", headers=AUTH).json())["status"] == "en_curso" and time.time() < deadline:
        time.sleep(0.05)
    return s


@pytest.fixture
def client(monkeypatch, tmp_path):
    (tmp_path / "blank.json").write_text("[]")

    async def fake_open(url, password):  # the real open_session dials the desktop; tests stay offline
        return FakeSession("blank", {}, tmp_path)

    monkeypatch.setattr(runner, "open_session", fake_open)
    with TestClient(app) as c:
        yield c


def test_health_is_open(client):
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "test-token"}])
def test_task_routes_need_the_team_token(client, headers):
    assert client.post("/tasks", json=BODY, headers=headers).status_code == 401
    assert client.get("/tasks/whatever", headers=headers).status_code == 401


def test_task_runs_from_en_curso_to_terminada(client, monkeypatch):
    async def slow_stub(task, session, log, budget_s):
        await asyncio.sleep(0.3)
        return Summary("terminada", "hecho", {"n": 3})

    monkeypatch.setattr(runner, "run_task", slow_stub)
    t0 = time.perf_counter()
    r = client.post("/tasks", json=BODY, headers=AUTH)
    assert r.status_code == 200 and time.perf_counter() - t0 < 2
    task_id = r.json()["task_id"]

    assert client.get(f"/tasks/{task_id}", headers=AUTH).json()["status"] == "en_curso"
    s = _wait(client, task_id)
    assert s == {"task_id": task_id, "status": "terminada", "summary": "hecho", "data": {"n": 3}}


def test_stub_worker_finishes_terminada(client):
    task_id = client.post("/tasks", json=BODY, headers=AUTH).json()["task_id"]
    s = _wait(client, task_id)
    assert s["status"] == "terminada" and s["summary"].startswith("stub")


def test_unknown_task_is_404(client):
    assert client.get("/tasks/nope", headers=AUTH).status_code == 404


def test_refuses_to_start_without_a_required_var(monkeypatch):
    monkeypatch.delenv("MODEL_VLM")
    with pytest.raises(RuntimeError, match="MODEL_VLM"):
        with TestClient(app):
            pass
