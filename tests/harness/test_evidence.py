from pathlib import Path

from harness.__main__ import main

SAMPLE = str(Path(__file__).parents[1] / "fixtures" / "logs" / "sample.jsonl")


def rows(out: str) -> dict[str, list[str]]:
    """behaviour -> [status, evidence], from the markdown table's body rows."""
    lines = [ln for ln in out.splitlines() if ln.startswith("|")][2:]
    return {c[0]: c[1:] for c in ([x.strip() for x in ln.strip("|").split("|")] for ln in lines)}


def test_every_behaviour_in_the_sample_is_confirmed_with_its_first_line(capsys):
    main(["evidence", SAMPLE])
    r = rows(capsys.readouterr().out)
    assert r["task.start"] == ["confirmed", f"`{SAMPLE}:1`"]
    assert r["sync.probe: changelog miss"] == ["confirmed", f"`{SAMPLE}:2`"]
    assert r["step: hit"] == ["confirmed", f"`{SAMPLE}:3`"]
    assert r["drift: S1 rung 1 via fuzzy"] == ["confirmed", f"`{SAMPLE}:4`"]
    assert r["step: ok"] == ["confirmed", f"`{SAMPLE}:5`"]
    assert r["step: repaired"] == ["confirmed", f"`{SAMPLE}:6`"]
    assert r["task.end: terminada"] == ["confirmed", f"`{SAMPLE}:7`"]


def test_designed_behaviours_missing_from_the_sample_are_assumed(capsys):
    main(["evidence", SAMPLE])
    r = rows(capsys.readouterr().out)
    for b in ("step: moved", "step: perceived", "step: llm", "sync.probe: entity hit", "drift: S5 rung 0 via inherit",
              "drift: S4 rung 3 via replan", "task.end: fallida", "rejoin", "sync.schema_drift"):
        assert r[b] == ["assumed", "-"], b


def test_two_logs_cite_each_behaviour_from_the_file_it_appears_in_first(capsys, tmp_path):
    other = tmp_path / "b.jsonl"
    other.write_text('{"event": "rejoin", "signal": "S4", "node": "facturas"}\n'
                     '{"event": "step", "outcome": "ok", "detail": "hit"}\n', encoding="utf-8")
    main(["evidence", SAMPLE, str(other)])
    r = rows(capsys.readouterr().out)
    assert r["step: hit"] == ["confirmed", f"`{SAMPLE}:3`"]
    assert r["rejoin"] == ["confirmed", f"`{other}:1`"]
