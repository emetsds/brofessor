"""Original context, editorial continuity and immutable public script boundaries."""

import json

import pytest

from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.features.podcasts import episode_writer as writer
from brofessor.models import validate_citations


def units():
    return [
        {
            "id": f"{source}:{index}",
            "source_id": source,
            "locator": f"page {index}",
            "text": text,
            "status": "ready",
        }
        for source in ("a", "b")
        for index, text in enumerate(
            ("First context.", "Eighty under dry conditions.", "Not tested in floods."), 1
        )
    ]


def plan():
    return {
        "title": "Bridge",
        "listener_goal": "Understand the limits",
        "material_sufficient": True,
        "reason": "",
        "source_relationships": [],
        "sections": [
            {"title": "Test", "brief": "Dry conditions", "citations": ["a:2"], "weight": 1},
            {"title": "Limits", "brief": "Flood uncertainty", "citations": ["b:2"], "weight": 1},
        ],
    }


def test_originals_are_whole_scoped_and_missing_neighbours_are_explicit():
    data = units()
    complete = writer.original_pack(["a:2"], data, {"a": "original.txt"}, budget=4000)
    assert {item["id"] for item in complete["originals"]} == {"a:1", "a:2", "a:3"}
    assert all(item["source"] == "original.txt" for item in complete["originals"])
    required = {
        "originals": complete["originals"][:1],
        "additional_context_omitted": ["a:1", "a:3"],
    }
    small = writer.original_pack(
        ["a:2"], data, {"a": "original.txt"}, budget=len(writer.encoded(required))
    )
    assert small["originals"] == complete["originals"][:1]
    assert small["additional_context_omitted"] == ["a:1", "a:3"]
    with pytest.raises(ValueError, match="Required original"):
        writer.original_pack(["a:2"], data, {}, budget=10)
    with pytest.raises(ValueError, match="unavailable"):
        writer.original_pack(["unrelated:1"], data, {}, budget=4000)


def test_writer_passes_actual_handoff_without_leaking_it_into_public_script():
    calls, reports = [], []
    outline = plan()

    def generate(prompt, schema, *, citation_scope, validate):
        index = len(calls)
        calls.append(prompt)
        if index:
            assert "Covered test conditions" in prompt
            assert "Not tested in floods." in prompt
        assert "WHOLE SOURCE NOTES" not in prompt
        value = {
            "title": "Part",
            "language": "en",
            "turns": [
                {
                    "speaker": speaker,
                    "text": " ".join(["word"] * 25),
                    "citations": [f"{'a' if index == 0 else 'b'}:2"],
                }
                for speaker in ("host", "guest")
            ],
            "handoff": {
                "covered_points": ["Covered test conditions"],
                "introduced_terms": [],
                "open_question": "What remains untested?",
            },
        }
        value = schema.model_validate(value).model_dump()
        validate_citations(value, citation_scope)
        validate(value)
        return value

    result = writer.write(
        {
            "instructions": "Use original evidence.",
            "evidence": [{"text": "WHOLE SOURCE NOTES"}],
            "units": units(),
            "names": {"a": "Original", "b": "Review"},
        },
        20,
        "en",
        generate,
        lambda _: None,
        lambda _: None,
        target_words=100,
        plan=outline,
        save_section=lambda n, value: reports.append(value),
    )
    assert set(result) == {"title", "language", "turns"}
    assert reports[1]["input_handoff"]["covered_points"] == ["Covered test conditions"]
    assert reports[0]["required_ids"] == ["a:2"]
    assert json.dumps(outline) == json.dumps(plan())


def test_insufficient_material_is_saved_as_plan_without_padding_or_script_calls():
    insufficient = {
        **plan(),
        "material_sufficient": False,
        "reason": "Only one unsupported estimate.",
        "sections": [],
    }
    saved = []
    with pytest.raises(ValueError, match="Not enough source material"):
        writer.write(
            {"instructions": "", "units": [], "names": {}, "evidence": []},
            20,
            "en",
            lambda *a, **kw: pytest.fail("No writing for insufficient material"),
            lambda _: None,
            saved.append,
            target_words=100,
            plan=insufficient,
        )
    assert saved == [insufficient]


def test_version_four_checks_scoped_sources_and_reuses_plan_on_resume(tmp_path, monkeypatch):
    from brofessor.application import worker
    from brofessor.infrastructure.storage.workspace import Workspace

    w = Workspace(tmp_path / "workspace")
    for name in ("source-a", "source-b"):
        path = tmp_path / (name + ".txt")
        path.write_text(name + ": Floods were not tested.")
        w.add_source(path)
    originals = w.units()
    a, b = originals[0]["id"], originals[1]["id"]
    outline = plan()
    outline["sections"][0]["citations"] = [a]
    outline["sections"][1]["citations"] = [b]
    job = w.submit(
        JobKind.PODCAST,
        {
            "source_ids": [s["id"] for s in w.sources()],
            "focus": "Limits",
            "language": "en",
            "provider": "codex",
            "model": None,
            "minutes": 20,
            "target_words": 100,
            "dialogue_version": 4,
            "reading_version": 3,
        },
    )
    calls = []
    bad = True

    def generate(prompt, schema, *args, **kwargs):
        calls.append(schema["title"])
        if schema["title"] == "EpisodePlan":
            return outline
        first = "Write section 1 of 2" in prompt
        value = {
            "title": "Part",
            "language": "en",
            "turns": [
                {
                    "speaker": speaker,
                    "text": " ".join(["word"] * 25),
                    "citations": [b if bad or not first else a],
                }
                for speaker in ("host", "guest")
            ],
            "handoff": {
                "covered_points": ["Actual covered material"],
                "introduced_terms": [],
                "open_question": "Limits?",
            },
        }
        return value

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    worker.run(w, once=True)
    assert w.job(job["id"])["status"] == "failed"
    assert "Unknown source citations" in w.job(job["id"])["error"]
    assert w.draft(job["id"]) is None
    bad = False
    w.resume(job["id"])
    worker.run(w, once=True)
    assert w.job(job["id"])["status"] == "succeeded"
    assert calls.count("EpisodePlan") == 1
    assert set(w.draft(job["id"])["data"]) == {"title", "language", "turns"}
    report = json.loads((w.path / "jobs" / job["id"] / "writer-section-2.json").read_text())
    assert report["input_handoff"]["covered_points"] == ["Actual covered material"]


def test_source_metadata_survives_note_compression_without_changing_legacy_prompts(tmp_path):
    from brofessor.features.sources import reading

    data = units()
    for item in data:
        item["text"] *= 1200
    names = {"a": "Original report", "b": "Independent review"}
    captured = []

    def generate(prompt, schema, citation_scope, validate):
        captured.append(prompt)
        result = {
            "notes": [
                {"summary": "Conditions and uncertainty.", "citations": [key]}
                for key in sorted(citation_scope)
            ]
        }
        validate(result)
        return result

    # Smaller whole fragments keep batch boundaries below the per-request limit.
    for item in data:
        item["text"] = item["text"][:5000]
    newer = tmp_path / "new"
    newer.mkdir()
    evidence, coverage = reading.prepare(
        data, "Limits", generate, lambda: None, lambda _: None, newer, version=3, names=names
    )
    assert coverage["count"] == len(data)
    assert all(item["origins"][0]["source"] in names.values() for item in evidence)
    assert any("Independent review" in text for text in captured)
    legacy = tmp_path / "old"
    legacy.mkdir()
    older, _ = reading.prepare(
        data, "Limits", generate, lambda: None, lambda _: None, legacy, version=2, names=names
    )
    assert all("origins" not in item for item in older)


def test_long_first_response_can_be_corrected_without_dropping_its_cited_originals():
    data = [
        {
            "id": f"s{n}:{i}",
            "source_id": f"s{n}",
            "locator": f"page {i}",
            "text": "context " * 740,
            "status": "ready",
        }
        for n in range(8)
        for i in range(1, 4)
    ]
    required = [f"s{n}:2" for n in range(8)]
    outline = plan()
    outline["sections"][0]["citations"] = required
    outline["sections"][1]["citations"] = [required[0]]
    prompts = []
    reports = []

    def generate(prompt, schema, citation_scope, validate):
        first = not prompts
        prompts.append(prompt)
        count = 100 if first else 2
        ids = required if "Write section 1 of 2" in prompt else [required[0]]
        value = {
            "title": "Part",
            "language": "en",
            "turns": [
                {
                    "speaker": "host" if i % 2 == 0 else "guest",
                    "text": " ".join(["word"] * (10 if first else 25)),
                    "citations": ids,
                }
                for i in range(count)
            ],
            "handoff": {
                "covered_points": ["x" * 200 for _ in range(24)] if first else ["Covered"],
                "introduced_terms": [],
                "open_question": "",
            },
        }
        value = schema.model_validate(value).model_dump()
        validate_citations(value, citation_scope)
        validate(value)
        return value

    writer.write(
        {"instructions": "Originals only.", "units": data, "names": {}, "evidence": []},
        20,
        "en",
        generate,
        lambda _: None,
        lambda _: None,
        target_words=100,
        plan=outline,
        save_section=lambda n, report: reports.append(report),
    )
    assert len(prompts) == 3 and "First version" in prompts[1]
    assert all(len(prompt) <= writer.PROMPT_BUDGET for prompt in prompts)
    originals = json.loads(prompts[1].split("\nORIGINALS:\n")[1].split("\nCorrect this version")[0])
    assert set(required) <= {item["id"] for item in originals["originals"]}
    assert originals["additional_context_omitted"]
    assert len(reports[0]["prompt_character_counts"]) == 2


def test_experimental_method_is_explicit_in_cli_and_inherited_by_new_series_episodes(
    tmp_path, monkeypatch
):
    from typer.testing import CliRunner

    from brofessor.application import service
    from brofessor.infrastructure.storage.workspace import Workspace
    from brofessor.interfaces.cli.app import app

    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda *_: None)
    w = Workspace(tmp_path / "workspace")
    source = tmp_path / "source.txt"
    source.write_text("Measurements and their limits.")
    w.add_source(source)
    ordinary = service.submit(w, JobKind.PODCAST, start_worker=False)
    assert ordinary["params"]["dialogue_version"] == 3
    assert "writing_method" not in ordinary["params"]
    result = CliRunner().invoke(
        app, ["-w", str(w.path), "podcast", "--writing-method", "originals"]
    )
    assert result.exit_code == 0, result.output
    experimental = json.loads(result.output)
    assert (
        experimental["params"]["dialogue_version"] == 4
        and experimental["params"]["reading_version"] == 3
    )
    for kind, options in (
        ("ask", {"focus": "Limits?"}),
        ("slides", {}),
        ("podcast", {"minutes": 3}),
    ):
        with pytest.raises(ValueError, match="at least twenty"):
            service.submit(w, kind, writing_method="originals", start_worker=False, **options)
    parent = service.submit(
        w, JobKind.PODCAST_SERIES, episode_count=2, writing_method="originals", start_worker=False
    )
    cite = w.units()[0]["id"]
    w.save_draft(
        parent["id"],
        {
            "title": "Series",
            "language": "en",
            "terms": [],
            "topics": [
                {"id": f"t{i}", "title": f"Topic {i}", "brief": f"Scope {i}", "citations": [cite]}
                for i in (1, 2)
            ],
            "episodes": [{"title": f"Episode {i}", "topic_ids": [f"t{i}"]} for i in (1, 2)],
        },
    )
    w.update_job(parent["id"], status=JobStatus.SUCCEEDED)
    episode = service.series_episode(w, parent["id"], 1, start_worker=False)
    assert episode["params"]["writing_method"] == "originals"
    assert episode["params"]["dialogue_version"] == 4 and episode["params"]["language"] == "en"


@pytest.mark.parametrize("minutes,total", [(20, 2415), (60, 8550)])
def test_unequal_sections_compensate_early_overruns_within_total_budget(minutes, total):
    import math
    import re

    outline = plan()
    outline["sections"] = [
        {
            "title": f"Section {i}",
            "brief": f"Purpose {i}",
            "citations": ["a:2"],
            "weight": 5 if i == 0 else 1,
        }
        for i in range(math.ceil(minutes / 10))
    ]
    reports = []

    def generate(prompt, schema, citation_scope, validate):
        number, count = map(int, re.search(r"Write section (\d+) of (\d+)", prompt).groups())
        target, low, high = map(
            int, re.search(r"Write (\d+) spoken words, between (\d+) and (\d+)", prompt).groups()
        )
        count_words = high if number != count else target
        turns = []
        while count_words:
            size = min(40, count_words)
            turns.append(
                {
                    "speaker": "host" if len(turns) % 2 == 0 else "guest",
                    "text": " ".join(["word"] * size),
                    "citations": ["a:2"],
                }
            )
            count_words -= size
        value = {
            "title": "Part",
            "language": "en",
            "turns": turns,
            "handoff": {
                "covered_points": [f"Covered {number}"],
                "introduced_terms": [],
                "open_question": "",
            },
        }
        value = schema.model_validate(value).model_dump()
        validate(value)
        return value

    result = writer.write(
        {"instructions": "Originals only.", "units": units(), "names": {}, "evidence": []},
        minutes,
        "en",
        generate,
        lambda _: None,
        lambda _: None,
        target_words=total,
        plan=outline,
        save_section=lambda n, report: reports.append(report),
    )
    assert abs(sum(len(t["text"].split()) for t in result["turns"]) - total) <= total * 0.02
    assert reports[0]["words"] > reports[-1]["words"]
