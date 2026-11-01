import json
from pathlib import Path

import pytest

from brofessor import pipeline, questions, reading, service
from brofessor.workspace import Workspace


def answer(citation, text="An exact fact.", **extra):
    return {
        "answer": "A fact",
        "citations": [citation],
        "quotes": [{"citation": citation, "text": text}],
        **extra,
    }


@pytest.mark.parametrize("problem", ["invented", "unseen", "uncited", "missing", "conflict"])
def test_invalid_quotes_are_not_published(tmp_path, monkeypatch, problem):
    w = Workspace(tmp_path / "workspace")
    path = tmp_path / "source.txt"
    path.write_text("An exact fact.")
    w.add_source(path)
    citation = w.units()[0]["id"]
    value = answer(citation)
    if problem == "invented":
        value["quotes"][0]["text"] = "A plausible but invented fact."
    elif problem == "unseen":
        value["quotes"][0]["citation"] = "other:1"
    elif problem == "uncited":
        value["citations"] = []
        value["evidence_status"] = "insufficient_evidence"
    elif problem == "missing":
        value["quotes"] = []
    else:
        value["evidence_status"] = "conflicting_evidence"
    monkeypatch.setattr("brofessor.executors.generate", lambda *a, **k: value)
    job = service.submit(w, "ask", focus="Fact?", start_worker=False)
    with pytest.raises(ValueError):
        pipeline.execute(w, job)
    assert w.draft(job["id"]) is None
    assert service.coverage(w, job["id"])["count"] == 0
    assert not list((w.path / "jobs" / job["id"]).glob("checkpoints/*.json"))


def test_exact_quotes_conflicts_and_edit_history(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    for name, text in [("a.txt", "Capacity is 80 kg."), ("b.txt", "Capacity is 120 kg.")]:
        path = tmp_path / name
        path.write_text(text)
        w.add_source(path)
    units = w.units()
    value = {
        "answer": "The reports disagree.",
        "evidence_status": "conflicting_evidence",
        "citations": [u["id"] for u in units],
        "quotes": [{"citation": u["id"], "text": u["text"]} for u in units],
    }
    monkeypatch.setattr("brofessor.executors.generate", lambda *a, **k: value)
    job = service.submit(w, "ask", focus="Capacity?", start_worker=False)
    pipeline.execute(w, job)
    saved = w.draft(job["id"])
    evidence = service.answer_evidence(w, job["id"])
    assert {e["source"] for e in evidence} == {"a.txt", "b.txt"}
    assert all(e["locator"] == "lines 1-1" and e["quotes"] == [e["text"]] for e in evidence)
    changed = {**saved["data"], "quotes": []}
    with pytest.raises(ValueError, match="quote"):
        service.edit_draft(w, job["id"], changed, 1)
    changed = {**saved["data"], "answer": "My explanation of the disagreement."}
    service.edit_draft(w, job["id"], changed, 1)
    assert w.draft(job["id"], 1)["data"] == saved["data"]


def test_legacy_answer_can_still_be_edited_without_claiming_verified_quotes(tmp_path):
    w = Workspace(tmp_path / "workspace")
    path = tmp_path / "source.txt"
    path.write_text("An exact fact.")
    w.add_source(path)
    job = service.submit(w, "ask", focus="Fact?", start_worker=False)
    old = {"answer": "Old answer", "citations": [w.units()[0]["id"]]}
    w.save_draft(job["id"], old)
    service.edit_draft(w, job["id"], {**old, "answer": "Edited old answer"}, 1)
    assert "quotes" not in w.draft(job["id"])["data"]
    assert service.answer_evidence(w, job["id"])[0]["quotes"] == []


def test_retrieval_reads_originals_and_neighbors_with_honest_coverage(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    path = tmp_path / "long.txt"
    path.write_text(
        "\n".join(
            [
                "Unrelated terrain." * 30,
                "Target beacon is blue.",
                "Its keeper is Mara.",
                "Unrelated weather." * 30,
            ]
        )
    )
    source = w.add_source(path)
    units = w.units([source["id"]])
    monkeypatch.setattr(questions, "EVIDENCE_BUDGET", 450)
    # Importer made one chunk; use deterministic source-sized fragments for this boundary.
    units = [
        {**units[0], "id": f"s:{i}", "text": text, "locator": f"page {i}"}
        for i, text in enumerate(
            [
                "Unrelated terrain." * 30,
                "Target beacon is blue.",
                "Its keeper is Mara.",
                "Unrelated weather." * 30,
            ]
        )
    ]
    calls = []

    def generate(prompt, schema, **kwargs):
        calls.append(schema.__name__)
        assert "Цвет" in prompt
        return {"queries": ["Target beacon blue colour"]}

    evidence, coverage = questions.prepare(
        units, "Цвет маяка?", generate, lambda: None, lambda _: None, tmp_path
    )
    assert calls == ["SearchQueries"]
    assert {e["id"] for e in evidence} == {"s:1", "s:2"}
    assert evidence[0]["text"] == "Target beacon is blue."
    assert len(reading.encoded(evidence)) <= questions.EVIDENCE_BUDGET
    assert coverage["mode"] == "retrieved" and coverage["count"] == 0
    assert {u["status"] for u in coverage["units"]} == {"pending", "not_selected"}


def test_no_matches_do_not_publish_arbitrary_originals(tmp_path, monkeypatch):
    monkeypatch.setattr(questions, "EVIDENCE_BUDGET", 100)
    units = [
        {
            "id": "s:1",
            "source_id": "s",
            "locator": "page 1",
            "text": "A bridge trial. " * 30,
            "status": "ready",
        }
    ]
    evidence, report = questions.prepare(
        units,
        "zirconium",
        lambda *a, **k: {"queries": ["цирконий"]},
        lambda: None,
        lambda _: None,
        tmp_path,
    )
    assert evidence == [] and report["selected_count"] == 0
    assert report["units"][0]["status"] == "not_selected"


def test_scene_continuation_survives_pressure_from_lower_ranked_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(questions, "EVIDENCE_BUDGET", 450)
    texts = [
        "A scene begins.",
        "The account continues.",
        "The decisive alibi is here.",
        *["Unrelated result." for _ in range(8)],
    ]
    units = [
        {"id": f"s:{i}", "source_id": "s", "locator": f"page {i}", "text": text, "status": "ready"}
        for i, text in enumerate(texts)
    ]
    monkeypatch.setattr(
        questions, "search_units", lambda *a, **k: [units[i] for i in (0, 3, 4, 5, 6, 7, 8, 9)]
    )
    evidence, report = questions.prepare(
        units,
        "scene",
        lambda *a, **k: {"queries": ["scene account"]},
        lambda: None,
        lambda _: None,
        tmp_path,
    )
    assert "s:2" in {e["id"] for e in evidence}
    assert len(reading.encoded(evidence)) <= questions.EVIDENCE_BUDGET
    assert any(u["status"] == "not_selected" for u in report["units"])


def test_search_source_scope_is_shared_and_does_not_guess_on_no_match(tmp_path):
    w = Workspace(tmp_path / "workspace")
    for name in ("a", "b"):
        path = tmp_path / f"{name}.txt"
        path.write_text(f"The {name} beacon is blue.")
        w.add_source(path)
    source = next(s for s in w.sources() if s["name"] == "b.txt")
    found = service.search(w, "blue", source_ids=[source["id"]])
    assert len(found) == 1 and found[0]["source"] == "b.txt"
    assert service.search(w, "missing zirconium") == []
    with pytest.raises(ValueError):
        service.search(w, "blue", source_ids=["unknown"])


def test_control_corpus_has_twenty_cases_and_exact_gold_quotes():
    corpus = json.loads((Path(__file__).parent / "fixtures/questions.json").read_text())
    assert len(corpus["cases"]) == 20
    assert {case["status"] for case in corpus["cases"]} == {
        "supported",
        "insufficient_evidence",
        "conflicting_evidence",
    }
    for case in corpus["cases"]:
        for name, quote in case["gold"]:
            assert quote in corpus["documents"][name]


def test_conflicting_positions_may_be_in_the_same_original_fragment():
    unit = {"id": "s:1", "text": "Report A: 80 kg. Report B: 120 kg.", "status": "ready"}
    value = answer("s:1", "Report A: 80 kg.", evidence_status="conflicting_evidence")
    value["quotes"].append({"citation": "s:1", "text": "Report B: 120 kg."})
    questions.validate_answer(value, [unit])


def test_quote_wrapping_is_restored_from_original_without_accepting_word_changes(
    tmp_path, monkeypatch
):
    w = Workspace(tmp_path / "workspace")
    path = tmp_path / "wrapped.txt"
    path.write_text("The capacity is\n80 kilograms. Flood resistance is unknown.")
    w.add_source(path)
    citation = w.units()[0]["id"]
    monkeypatch.setattr(
        "brofessor.executors.generate",
        lambda *a, **kw: answer(citation, "The capacity is 80 kilograms."),
    )
    job = service.submit(w, "ask", focus="Capacity?", start_worker=False)
    pipeline.execute(w, job)
    quote = w.draft(job["id"])["data"]["quotes"][0]["text"]
    assert quote == "The capacity is\n80 kilograms."
    assert quote in w.units()[0]["text"]
    with pytest.raises(ValueError, match="exact substring"):
        questions.validate_answer(answer(citation, "The capacity is 81 kilograms."), w.units())


def test_retrieved_answer_resumes_queries_and_never_cites_unseen_fragments(tmp_path, monkeypatch):
    w = Workspace(tmp_path / "workspace")
    ids = {}
    for name, text in [
        ("target", "A beacon is blue."),
        ("other", "Completely unrelated granite." * 30),
    ]:
        path = tmp_path / f"{name}.txt"
        path.write_text(text)
        ids[name] = w.add_source(path)["id"] + ":1"
    monkeypatch.setattr(questions, "EVIDENCE_BUDGET", 500)
    calls = []

    def generate(prompt, schema, *a, **k):
        calls.append(schema["title"])
        if schema["title"] == "SearchQueries":
            return {"queries": ["beacon colour"]}
        return answer(ids["other"], "Completely unrelated granite.")

    monkeypatch.setattr("brofessor.executors.generate", generate)
    job = service.submit(w, "ask", focus="beacon colour", start_worker=False)
    with pytest.raises(ValueError, match="Unknown source"):
        pipeline.execute(w, job)
    assert calls == ["SearchQueries", "Answer"]
    assert service.coverage(w, job["id"])["count"] == 0
    monkeypatch.setattr(
        "brofessor.executors.generate", lambda *a, **k: answer(ids["target"], "A beacon is blue.")
    )
    pipeline.execute(w, job)
    report = service.coverage(w, job["id"])
    assert report["count"] == 1 and report["cited_count"] == 1
    assert report["mode"] == "retrieved"
    assert any(u["status"] == "not_selected" for u in report["units"])
