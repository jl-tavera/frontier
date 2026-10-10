import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from app.agent import llm as llm_mod
from synth.__main__ import main
from synth.gen import gen as gen_tasks
from tests.fakes.llm import FakeLLM
from tests.fixtures.synth.build import build


@pytest.fixture
def cache(tmp_path):
    return build(tmp_path / "cache.sqlite")


def gen(cache, out, *args):
    assert main(["gen", "--cache", str(cache), "--out", str(out), *args]) == 0
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*.json"))}


def test_count_answer_is_the_sql_count(cache, tmp_path):
    tasks = gen(cache, tmp_path / "out")
    db = sqlite3.connect(cache)
    for t in (t for k, t in tasks.items() if k.startswith("lookup-count-")):
        estado = "Vencida" if "vencidas" in t["instruccion"] else "Pagada"
        cliente = t["instruccion"].split(" tiene ")[1].rstrip("?")
        (n,), = db.execute("SELECT COUNT(*) FROM rows WHERE json_extract(data_json, '$.Cliente') = ? "
                           "AND json_extract(data_json, '$.Estado') = ? AND json_extract(data_json, '$.Vence') IS NOT NULL",
                           (cliente, estado))
        assert t["respuesta_esperada"] == str(n)


def test_every_template_yields_per_template_instances(cache, tmp_path):
    tasks = gen(cache, tmp_path / "out")
    by_template = {}
    for k in tasks:
        by_template.setdefault(k.rsplit("-", 1)[0], []).append(k)
    assert len(by_template) == 16
    assert all(len(v) == 2 for v in by_template.values()), by_template
    official = {"id", "nivel", "instruccion", "estado_esperado", "diff_esperado", "lista_blanca",
                "respuesta_esperada", "claves_razon"}
    assert all(set(t) <= official for t in tasks.values())


def test_homonym_fails_naming_both_nits(cache, tmp_path):
    t = gen(cache, tmp_path / "out")["fail-homonym-01"]
    assert "Ana Torres" in t["instruccion"]
    assert t["estado_esperado"] == "fallida"
    assert sorted(t["claves_razon"]) == ["1019876543", "52345678"]


def test_noop_update_expects_no_diff(cache, tmp_path):
    t = gen(cache, tmp_path / "out")["update-noop-01"]
    assert (t["estado_esperado"], t["diff_esperado"]) == ("terminada", [])


@pytest.mark.parametrize("today, n", [("2026-10-14", "2"), ("2026-10-11", "1")])
def test_ayer_counts_from_today(cache, tmp_path, today, n):
    tasks = gen(cache, tmp_path / "out", "--per-template", "3", "--today", today)
    (ayer,) = [t for t in tasks.values() if t["instruccion"] == "¿Cuántas facturas vencieron ayer?"]
    assert ayer["respuesta_esperada"] == n


def test_same_seed_is_byte_identical(cache, tmp_path):
    gen(cache, tmp_path / "a")
    gen(cache, tmp_path / "b")
    a, b = sorted((tmp_path / "a").glob("*.json")), sorted((tmp_path / "b").glob("*.json"))
    assert [p.name for p in a] == [p.name for p in b]
    assert all(x.read_bytes() == y.read_bytes() for x, y in zip(a, b))


PRUEBAS = Path(__file__).parents[2] / "resources" / "docs" / "references" / "pruebas"
EXPLORED = Path(__file__).parents[1] / "fixtures" / "synth" / "explored"


def check(cache, root):
    return main(["check", str(root), "--cache", str(cache)])


def test_check_passes_on_generated_official_and_mixed_trees(cache, tmp_path, capsys):
    gen(cache, tmp_path / "tree" / "generated")
    assert check(cache, tmp_path / "tree" / "generated") == 0
    assert check(cache, PRUEBAS) == 0
    shutil.copytree(EXPLORED, tmp_path / "tree" / "explored")
    assert check(cache, tmp_path / "tree") == 0
    assert capsys.readouterr().out.splitlines()[-1] == "generated: 32, explored: 2"


def _broken(cache, tmp_path, edit):
    out = tmp_path / "out"
    gen(cache, out)
    edit(out)
    return check(cache, out)


def _rewrite(p: Path, change):
    t = json.loads(p.read_text(encoding="utf-8"))
    change(t)
    p.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")


def test_check_fails_on_a_count_off_by_one(cache, tmp_path, capsys):
    bump = lambda t: t.update(respuesta_esperada=str(int(t["respuesta_esperada"]) + 1))
    assert _broken(cache, tmp_path, lambda out: _rewrite(out / "lookup-count-01.json", bump)) == 1
    assert "respuesta_esperada" in capsys.readouterr().err


def test_check_fails_on_an_extra_key(cache, tmp_path, capsys):
    assert _broken(cache, tmp_path, lambda out: _rewrite(out / "update-noop-01.json", lambda t: t.update(categoria="update"))) == 1
    assert "categoria" in capsys.readouterr().err


def test_check_fails_on_a_repeated_id(cache, tmp_path, capsys):
    def dup(out):
        (out / "copy").mkdir()
        shutil.copy(out / "lookup-sum-01.json", out / "copy" / "x.json")
    assert _broken(cache, tmp_path, dup) == 1
    assert "repeats id" in capsys.readouterr().err


def test_check_fails_on_a_password_like_string(cache, tmp_path):
    leak = lambda t: t.update(claves_razon=["contraseña: hunter22"])
    assert _broken(cache, tmp_path, lambda out: _rewrite(out / "fail-secret-01.json", leak)) == 1


def test_gen_never_repeats_an_official_task_or_deletes_a_hand_written_one(cache, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    shutil.copy(EXPLORED / "explored-01.json", out)
    tasks = gen(cache, out, "--per-template", "99")
    official = {json.loads(p.read_text(encoding="utf-8"))["instruccion"] for p in PRUEBAS.glob("*.json")}
    assert "explored-01" in tasks
    assert not official & {t["instruccion"] for t in tasks.values()}



def _scripted(monkeypatch, cache, tmp_path, rewrite):
    """A FakeLLM with one reply per base task, built from what a plain run writes, wired in as F1's client."""
    bases = [json.loads(p.read_text(encoding="utf-8")) for p in gen_tasks(cache, tmp_path / "base", 1)]
    fake = FakeLLM(*({"variantes": rewrite(t)} for t in bases))
    monkeypatch.setattr(llm_mod, "openrouter", lambda: fake)
    return fake, bases


def test_paraphrase_writes_k_variants_per_task_with_the_same_expectation(cache, tmp_path, monkeypatch):
    fake, bases = _scripted(monkeypatch, cache, tmp_path, lambda t: [f"Oye, {t['instruccion']}", f"{t['instruccion']} Gracias."])
    tasks = gen(cache, tmp_path / "out", "--per-template", "1", "--paraphrase", "2")
    assert len(fake.calls) == len(bases) and fake.calls[0]["model"] == "test/fast"
    for b in bases:
        v1, v2 = tasks[f"{b['id']}-v1"], tasks[f"{b['id']}-v2"]
        assert v1 == b | {"id": f"{b['id']}-v1", "instruccion": f"Oye, {b['instruccion']}"}
        assert v2["instruccion"] == f"{b['instruccion']} Gracias."
    assert len(tasks) == 3 * len(bases)
    assert check(cache, tmp_path / "out") == 0


def test_a_variant_that_drops_the_nit_is_not_written(cache, tmp_path, monkeypatch):
    def rewrite(t):
        nit = re.search(r"NIT (\S+?)[?.,]", t["instruccion"])
        return [f"Oye, {t['instruccion']}", t["instruccion"].replace(nit[1], "su NIT") if nit else f"Hola: {t['instruccion']}"]
    _scripted(monkeypatch, cache, tmp_path, rewrite)
    tasks = gen(cache, tmp_path / "out", "--per-template", "1", "--paraphrase", "2")
    assert "multi-join-01-v1" in tasks and "multi-join-01-v2" not in tasks
    assert "lookup-sum-01-v2" in tasks


def test_paraphrase_0_is_the_default_and_calls_no_model(cache, tmp_path, monkeypatch):
    def boom():
        raise AssertionError("no model call expected")
    monkeypatch.setattr(llm_mod, "openrouter", boom)
    tasks = gen(cache, tmp_path / "out", "--per-template", "1")
    assert not any(re.search(r"-v\d+$", k) for k in tasks)


def test_paraphrase_is_deterministic_with_a_scripted_client(cache, tmp_path, monkeypatch):
    rewrite = lambda t: [f"Oye, {t['instruccion']}"]
    for run in ("a", "b"):
        _scripted(monkeypatch, cache, tmp_path, rewrite)
        gen(cache, tmp_path / run, "--per-template", "1", "--paraphrase", "1")
    a, b = sorted((tmp_path / "a").glob("*.json")), sorted((tmp_path / "b").glob("*.json"))
    assert [p.name for p in a] == [p.name for p in b] and any("-v1" in p.name for p in a)
    assert all(x.read_bytes() == y.read_bytes() for x, y in zip(a, b))
