import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from synth.web import router

REPORTS = Path(__file__).parents[1] / "fixtures" / "synth" / "reports"
AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    for i, name in enumerate(["before", "after"]):  # `after` is the newer run
        shutil.copy(REPORTS / f"{name}.json", tmp_path)
        os.utime(tmp_path / f"{name}.json", (1_700_000_000 + i, 1_700_000_000 + i))
    monkeypatch.setenv("EVALS_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def body(r) -> str:
    return r.text.split("<pre", 1)[1]  # past Rich's stylesheet


def test_page_names_both_runs_newest_first_with_their_success(client):
    r = client.get("/evals")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = body(r)
    assert "after" in page and "67%" in page and "before" in page and "100%" in page
    assert page.index("after") < page.index("before")
    assert "Evaluation Diff: before" in page  # the latest run against the previous one


def test_posting_a_report_needs_the_token_then_shows_it(client):
    report = json.loads((REPORTS / "after.json").read_text("utf-8")) | {"name": "live-20261014-1530"}
    assert client.post("/evals", json=report).status_code == 401
    assert client.post("/evals", json=report, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert "live-20261014-1530" not in client.get("/evals").text
    assert client.post("/evals", json=report, headers=AUTH).status_code == 201
    page = body(client.get("/evals"))
    assert page.index("live-20261014-1530") < page.index("before")


@pytest.mark.parametrize("name", ["../escape", ".hidden", "a/b"])
def test_a_run_name_cannot_leave_the_reports_dir(client, tmp_path, name):
    report = json.loads((REPORTS / "after.json").read_text("utf-8")) | {"name": name}
    assert client.post("/evals", json=report, headers=AUTH).status_code == 422
    assert sorted(p.name for p in tmp_path.iterdir()) == ["after.json", "before.json"]


def test_a_stored_report_comes_back_as_json(client):
    assert client.get("/evals/before.json").json() == json.loads((REPORTS / "before.json").read_text("utf-8"))
    assert client.get("/evals/nope.json").status_code == 404


def test_a_stamped_run_name_orders_the_page_over_file_times(client, tmp_path):
    for name, stamp in [("live-20261014-1530", "after"), ("live-20261014-1200", "before")]:
        report = json.loads((REPORTS / f"{stamp}.json").read_text("utf-8")) | {"name": name}
        (tmp_path / f"{name}.json").write_text(json.dumps(report), "utf-8")  # written newest-run first
    page = body(client.get("/evals"))
    assert page.index("live-20261014-1530") < page.index("live-20261014-1200") < page.index("after")
    assert "Evaluation Diff: live-20261014-1200" in page
