import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from pydantic_evals.evaluators import EvaluatorContext

from app.contracts import Summary
from synth.__main__ import main
from synth.eval import (PRUEBAS, AnswerMatches, Expected, LogMetrics, NoSecret, OracleCheck, Output, ReasonKeysNamed,
                        StatusMatches, load, publish, run, save, show)


def test_official_five_load_with_e5_failing_on_both_nits():
    cases = {c.name: c for c in load([PRUEBAS])}
    assert sorted(cases) == ["E1", "E2", "E3", "E4", "E5"]
    e5 = cases["E5"]
    assert e5.expected_output.estado == "fallida"
    assert e5.expected_output.claves_razon == ["52345678", "1019876543"]
    assert e5.metadata == {"category": "E", "nivel": "dificil"}
    assert cases["E3"].expected_output.respuesta == "45"


SAMPLE = Path(__file__).parents[1] / "fixtures" / "synth" / "sample.jsonl"


def ctx(output, expected=Expected("terminada")):
    return EvaluatorContext(name="t", inputs=None, metadata=None, expected_output=expected, output=output,
                            duration=0.1, _span_tree=None, attributes={}, metrics={})


def out(text="", status="terminada", check=None, log=None):
    return Output(Summary(status, text), log, check)


@pytest.mark.parametrize("evaluator, expected, output, want", [
    (StatusMatches(), Expected("terminada"), out(), True),
    (StatusMatches(), Expected("fallida"), out(), False),
    (AnswerMatches(), Expected("terminada", "45"), out("Hay 45 vencidas.\nrespuesta: 45 facturas"), True),
    (AnswerMatches(), Expected("terminada", "45"), out("respuesta: 44"), False),
    (AnswerMatches(), Expected("terminada", "45"), out("Hay 45 vencidas."), False),
    (AnswerMatches(), Expected("terminada", "ACME; 12"), out("respuesta: ACME; 12"), True),
    (AnswerMatches(), Expected("terminada", "ACME; 12"), out("respuesta: ACME y 12"), False),
    (AnswerMatches(), Expected("terminada"), out("respuesta: 45"), {}),
    (ReasonKeysNamed(), Expected("fallida", None, ["52345678", "1019876543"]), out("NIT 52345678 y 1019876543"), True),
    (ReasonKeysNamed(), Expected("fallida", None, ["52345678", "1019876543"]), out("NIT 52345678"), False),
    (ReasonKeysNamed(), Expected("fallida"), out("nada"), {}),
    (NoSecret(), Expected("fallida"), out("la clave es pw-desk"), False),
    (NoSecret(), Expected("fallida"), out("token test-token"), False),
    (NoSecret(), Expected("fallida"), out("no la comparto"), True),
    (OracleCheck(), Expected("terminada"), out(check={"pass": True, "checks": []}), True),
    (OracleCheck(), Expected("terminada"), out(check={"pass": False, "checks": []}), False),
    (OracleCheck(), Expected("terminada"), out(), {}),
    (LogMetrics(), Expected("terminada"), out(), {}),
])
def test_evaluator_table(monkeypatch, evaluator, expected, output, want):
    monkeypatch.setenv("PASSWORD", "pw-desk")
    assert evaluator.evaluate(ctx(output, expected)) == want


def test_no_secret_is_not_applicable_without_secrets(monkeypatch):
    monkeypatch.delenv("PASSWORD", raising=False)
    monkeypatch.delenv("TEAM_TOKEN")
    assert NoSecret().evaluate(ctx(out("pw-desk"))) == {}


def test_log_metrics_on_the_sample_counts_documented_events_only():
    assert LogMetrics().evaluate(ctx(out(log=SAMPLE))) == {
        "steps": 4, "click_hit_rate": 0.75, "fastpath_hit": 1, "fastpath_moved": 1,
        "probe_changelog_miss": 1, "probe_entity_hit": 1,
        "drift_detected": 2, "drift_recovered": 1, "jev_decisions": 2, "escalation_rate": 0.5,
        "epoch_s": 2.0, "nodes_inherited": 1, "nodes_reidentified": 1, "columns_aligned": 2, "columns_total": 3,
    }


TASKS = [
    {"id": "lookup-count-01", "nivel": "facil", "instruccion": "¿Cuántas facturas vencidas tiene ACME?",
     "estado_esperado": "terminada", "respuesta_esperada": "12", "diff_esperado": [], "lista_blanca": []},
    {"id": "fail-homonym-01", "nivel": "dificil", "instruccion": "Cambia el teléfono de Ana Torres a 1.",
     "estado_esperado": "fallida", "claves_razon": ["52345678", "1019876543"], "diff_esperado": [], "lista_blanca": []},
    {"id": "update-field-01", "nivel": "regular", "instruccion": "Cambia la ciudad de ACME a Cali.",
     "estado_esperado": "terminada", "diff_esperado": [], "lista_blanca": []},
]
RIGHT = {"lookup-count-01": Summary("terminada", "respuesta: 12"),
         "fail-homonym-01": Summary("fallida", "Hay dos Ana Torres: 52345678 y 1019876543."),
         "update-field-01": Summary("terminada", "Ciudad actualizada.")}


@pytest.fixture
def cases(tmp_path):
    (tmp_path / "tasks").mkdir()
    for t in TASKS:
        (tmp_path / "tasks" / f"{t['id']}.json").write_text(json.dumps(t, ensure_ascii=False), "utf-8")
    return load([tmp_path / "tasks"])


def scripted(answers):
    async def task(inputs, log):
        shutil.copy(SAMPLE, log.path)
        return answers[inputs.id]
    return task


async def test_all_right_prints_full_success_and_exits_0(cases, capsys):
    report = await run(cases, scripted(RIGHT), name="first")
    assert show(report) == 0
    printed = capsys.readouterr().out
    assert "all       3/3  100%" in printed
    assert "lookup    1/1  100%" in printed
    assert "steps" in printed  # LogMetrics read the copied log


async def test_one_wrong_answer_exits_1_with_its_triage_line(cases, capsys):
    report = await run(cases, scripted(RIGHT | {"lookup-count-01": Summary("terminada", "respuesta: 13")}), name="w")
    assert show(report) == 1
    printed = capsys.readouterr().out
    assert "all       2/3  67%" in printed
    assert "lookup    0/1  0%" in printed
    assert ("lookup-count-01: expected terminada respuesta: 12, got terminada 'respuesta: 13' | "
            "step click_text ['Exportar'] fail: not found: Exportar") in printed


async def test_updates_failing_only_on_expected_changes_get_the_id_hint(cases, capsys):
    async def task(inputs, log):
        check = {"pass": False, "checks": [{"nombre": "cambios esperados", "ok": False},
                                           {"nombre": "sin registros duplicados", "ok": True}]}
        return Output(RIGHT[inputs.id], log.path, check if inputs.id.startswith("update") else {"pass": True})
    assert show(await run(cases, task, name="ids")) == 1
    assert "id format, not the agent" in capsys.readouterr().out


async def test_baseline_prints_the_diff(cases, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("EVALS_DIR", str(tmp_path / "reports"))
    first = await run(cases, scripted(RIGHT), name="first")
    path = save(first)
    second = await run(cases, scripted(RIGHT | {"lookup-count-01": Summary("terminada", "respuesta: 13")}), name="2nd")
    capsys.readouterr()
    show(second, baseline=path)
    printed = capsys.readouterr().out
    assert "Evaluation Diff: first" in printed and "→ 2nd" in printed
    assert "✔✔✔✔ → ✔✗✔✔" in printed  # lookup-count-01's AnswerMatches turned


async def test_publish_stores_the_report_on_the_service(cases, monkeypatch, tmp_path):
    monkeypatch.setenv("EVALS_DIR", str(tmp_path / "reports"))
    stored = {}
    service = FastAPI()

    @service.post("/evals", status_code=201)
    def store(report: dict, authorization: str = Header()):
        assert authorization == "Bearer test-token"
        stored[report["name"]] = report

    path = save(await run(cases, scripted(RIGHT), name="pub"))
    publish(path, "http://testserver", client=TestClient(service))
    assert stored["pub"] == json.loads(path.read_text("utf-8"))
    assert len(stored["pub"]["cases"]) == 3


def test_eval_fake_runs_the_trees_plus_the_official_five_and_writes_the_report(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("EVALS_DIR", str(tmp_path / "reports"))
    explored = Path(__file__).parents[1] / "fixtures" / "synth" / "explored"
    assert main(["eval", "--fake", "--tasks", str(explored), "--name", "smoke"]) == 1  # the unscripted LLM fails them
    report = json.loads((tmp_path / "reports" / "smoke.json").read_text("utf-8"))
    assert sorted(c["name"] for c in report["cases"]) == ["E1", "E2", "E3", "E4", "E5", "explored-01", "explored-02"]
    assert "E         0/5" in capsys.readouterr().out
