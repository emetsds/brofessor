"""Written reports share source validation, revisions and both public clients."""

import copy
import json

import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from brofessor.application import pipeline, service, tasks, worker
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind
from brofessor.features import reports
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.interfaces.cli.app import app
from tests.helpers.books import translated_book
from tests.helpers.ui import UI_APP, create, new_key


def sources(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    for name, text in [
        ("alpha.txt", "For one node, retries are disabled.\nUse a 12 ms timeout."),
        ("beta.txt", "For one node, retries are enabled.\nUse a 12 ms timeout."),
    ]:
        path = tmp_path / name
        path.write_text(text)
        workspace.add_source(path)
    return workspace


def candidate(units):
    return {
        "title": "Retries in a single-node system",
        "language": "en",
        "evidence_status": "conflicting_evidence",
        "sections": [
            {
                "heading": "Unresolved source disagreement",
                "text": "The sources disagree on retries under the same single-node conditions.",
                "origin": "sources",
                "citations": [u["id"] for u in units],
                "quotes": [{"citation": u["id"], "text": u["text"]} for u in units],
            },
            {
                "heading": "Proposed next action",
                "text": "Ask which retry policy applies before deployment.",
                "origin": "brofessor",
                "citations": [units[0]["id"]],
                "quotes": [{"citation": units[0]["id"], "text": units[0]["text"]}],
            },
        ],
    }


def markdown(workspace, job_id, revision=1):
    artifact = next(
        a
        for a in workspace.artifacts(job_id)
        if a["kind"] == "markdown" and a["metadata"]["revision"] == revision
    )
    return service.artifact_path(workspace, artifact["path"])


@pytest.mark.parametrize("template", reports.TEMPLATES)
def test_templates_read_originals_and_export_section_provenance(tmp_path, monkeypatch, template):
    workspace = sources(tmp_path)
    units = workspace.units()

    def generate(prompt, schema, *a, **kw):
        assert schema["title"] == "Report"
        evidence = json.JSONDecoder().raw_decode(prompt.split("EVIDENCE:\n", 1)[1])[0]
        assert {e["text"] for e in evidence} == {u["text"] for u in units}
        return candidate(units)

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    job = service.submit(
        workspace,
        JobKind.REPORT,
        template=template,
        focus="Compare retry policies",
        language=ContentLanguage.EN,
        request_key="same",
        start_worker=False,
    )
    assert (
        service.submit(
            workspace,
            "report",
            template=template,
            focus="Compare retry policies",
            language="en",
            request_key="same",
            start_worker=False,
        )["id"]
        == job["id"]
    )
    worker.run(workspace, once=True)
    assert workspace.job(job["id"])["status"] == "succeeded"
    text = markdown(workspace, job["id"]).read_text()
    assert "brofessor adaptation" in text and "From sources" in text
    for unit in units:
        assert unit["locator"] in text and unit["text"].splitlines()[0] in text
    assert {e["source"] for e in service.answer_evidence(workspace, job["id"])} == {
        "alpha.txt",
        "beta.txt",
    }
    assert all(
        len(e["quotes"]) == len(set(e["quotes"]))
        for e in service.answer_evidence(workspace, job["id"])
    )
    assert all(u["cited"] for u in service.coverage(workspace, job["id"])["units"])
    assert tasks.list_tasks(workspace)[0]["root_id"] == job["id"]
    regenerated = tasks.regenerate(workspace, job["id"], start_worker=False)
    assert regenerated["params"]["template"] == template


@pytest.mark.parametrize(
    "problem", ["invented_quote", "missing_section_quote", "language", "uncited_source"]
)
def test_each_report_section_is_validated_before_inference_is_cached(
    tmp_path, monkeypatch, problem
):
    workspace = sources(tmp_path)
    good = candidate(workspace.units())
    invalid = copy.deepcopy(good)
    if problem == "invented_quote":
        invalid["sections"][0]["quotes"][0]["text"] = "A fabricated recommendation."
    elif problem == "missing_section_quote":
        repeated = copy.deepcopy(invalid["sections"][0])
        repeated["quotes"] = []
        invalid["sections"].append(repeated)
    elif problem == "language":
        invalid["language"] = "ru"
    else:
        invalid["sections"][0]["citations"] = []
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", lambda *a, **kw: invalid)
    job = service.submit(
        workspace,
        JobKind.REPORT,
        focus="Retry policy",
        language=ContentLanguage.EN,
        start_worker=False,
    )
    with pytest.raises(ValueError, match="quote|Quote|language|citations"):
        pipeline.execute(workspace, job)
    assert workspace.draft(job["id"]) is None
    assert workspace.artifacts(job["id"]) == []
    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", lambda *a, **kw: good)
    pipeline.execute(workspace, job)
    assert markdown(workspace, job["id"]).is_file()
    changed = copy.deepcopy(good)
    changed["sections"][0]["quotes"] = []
    with pytest.raises(ValueError, match="quote"):
        service.edit_draft(workspace, job["id"], changed, 1)
    assert workspace.draft(job["id"])["revision"] == 1


def test_resume_repairs_export_without_overwriting_user_edits_or_repeating_inference(
    tmp_path, monkeypatch
):
    workspace = sources(tmp_path)
    calls = []

    def generate(*a, **kw):
        calls.append(1)
        return candidate(workspace.units())

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    publish = reports.publish

    def fail_export(*args):
        raise OSError("controlled export failure")

    monkeypatch.setattr(reports, "publish", fail_export)
    job = service.submit(
        workspace,
        JobKind.REPORT,
        focus="Retry policy",
        language=ContentLanguage.EN,
        start_worker=False,
    )
    with pytest.raises(OSError, match="controlled"):
        pipeline.execute(workspace, job)
    first = workspace.draft(job["id"])
    monkeypatch.setattr(reports, "publish", publish)
    changed = copy.deepcopy(first["data"])
    changed["sections"][1]["text"] = "My deployment decision is still pending."
    service.edit_draft(workspace, job["id"], changed, 1)
    pipeline.execute(workspace, job)
    assert calls == [1]
    assert "My deployment decision" in markdown(workspace, job["id"], 2).read_text()
    assert workspace.draft(job["id"], 1) == first
    assert workspace.draft(job["id"])["data"] == changed


def test_empty_directory_produces_a_clear_limitation_without_calling_the_writer(
    tmp_path, monkeypatch
):
    workspace = Workspace(tmp_path / "workspace")
    from brofessor.features.sources.collections import connect

    path = tmp_path / "empty"
    path.mkdir()
    connect(workspace, path)

    def finish_empty_catalog(prompt, schema, *a, **kw):
        assert schema["title"] == "NavigationStep", "No evidence for a report writer"
        return {"actions": [{"operation": "finish"}]}

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", finish_empty_catalog)
    job = service.submit(
        workspace, JobKind.REPORT, template="guide", focus="Deployment guide", start_worker=False
    )
    pipeline.execute(workspace, job)
    assert workspace.draft(job["id"])["data"]["evidence_status"] == "insufficient_evidence"
    assert "Недостаточно" in markdown(workspace, job["id"]).read_text()


def test_report_does_not_present_a_directory_excerpt_count_as_the_whole_document(
    tmp_path, monkeypatch
):
    from brofessor.features.sources.collections import connect
    from tests.helpers.collections import navigation_context

    workspace = Workspace(tmp_path / "workspace")
    root = tmp_path / "documents"
    root.mkdir()
    (root / "Long.md").write_text("An original observation with limited conditions.\n" * 200)
    collection = connect(workspace, root)

    def generate(prompt, schema, *a, **kw):
        if schema["title"] == "NavigationStep":
            ctx = navigation_context(prompt)
            return {
                "memory": "read one excerpt",
                "actions": [
                    {"operation": "finish"}
                    if ctx["memory"]
                    else {
                        "operation": "read",
                        "collection_id": collection["id"],
                        "path": "Long.md",
                        "limit": 1,
                    }
                ],
            }
        evidence = json.JSONDecoder().raw_decode(prompt.split("EVIDENCE:\n", 1)[1])[0]
        assert len(workspace.units()) > len(evidence)
        scope = json.JSONDecoder().raw_decode(
            prompt.split("EXCERPT SCOPE:", 1)[1].split("\n", 1)[1]
        )[0]
        assert scope[0]["readable_fragments"] is None
        unit = evidence[0]
        return {
            "title": "A limited reading",
            "language": "en",
            "evidence_status": "supported",
            "sections": [
                {
                    "heading": "Observation",
                    "text": "The source gives a qualified observation.",
                    "origin": "sources",
                    "citations": [unit["id"]],
                    "quotes": [{"citation": unit["id"], "text": unit["text"][:50]}],
                }
            ],
        }

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    job = service.submit(
        workspace,
        JobKind.REPORT,
        focus="Read an excerpt",
        language=ContentLanguage.EN,
        start_worker=False,
    )
    pipeline.execute(workspace, job)
    assert markdown(workspace, job["id"]).is_file()


def test_cli_and_ui_submit_the_same_report_and_allow_structured_edits(tmp_path, monkeypatch):
    workspace = sources(tmp_path)
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda _: None)
    monkeypatch.setattr(
        "brofessor.infrastructure.text.runners.generate",
        lambda *a, **kw: candidate(workspace.units()),
    )
    runner = CliRunner()
    cli = runner.invoke(
        app,
        [
            "-w",
            str(workspace.path),
            "report",
            "Retry policy",
            "--template",
            "guide",
            "--language",
            "en",
        ],
    )
    assert cli.exit_code == 0, cli.output
    cli_job = json.loads(cli.output)
    worker.run(workspace, once=True)
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    create(ui)
    ui.selectbox(key=new_key(ui, "kind")).select("report").run()
    ui.selectbox(key=new_key(ui, "template")).select("guide").run()
    ui.selectbox(key=new_key(ui, "output_language")).select("en").run()
    ui.text_area(key=new_key(ui, "focus")).set_value("Retry policy").run()
    ui.button(key="prepare").click().run()
    assert not ui.exception
    ui_job = workspace.jobs()[0]
    assert ui_job["params"] == cli_job["params"]
    worker.run(workspace, once=True)
    ui.run()
    assert not ui.exception
    ui.button(key=f"edit-{ui_job['id']}").click().run()
    key = f"editor:{workspace.path}:{ui_job['id']}"
    ui.selectbox(key=key + ":item:selected").select(1).run()
    field = next(a for a in ui.text_area if a.key and a.key.endswith(":sections:1:text"))
    field.set_value("My own proposed next step.").run()
    ui.button(key=f"save-{ui_job['id']}").click().run()
    assert not ui.exception
    shown = runner.invoke(app, ["-w", str(workspace.path), "draft", "show", ui_job["id"]])
    saved = json.loads(shown.output)
    assert saved["revision"] == 2 and saved["evidence"]
    assert saved["data"]["sections"][1]["text"] == "My own proposed next step."
    assert "My own proposed next step." in markdown(workspace, ui_job["id"], 2).read_text()


def test_reference_uses_one_pinned_accepted_glossary_in_cli_ui_prompt_and_export(
    tmp_path, monkeypatch
):
    workspace, source, translation, _ = translated_book(tmp_path, monkeypatch)
    accepted = workspace.draft(translation["id"], 1)
    seeds = reports.accepted_terminology(
        workspace, {"job_id": translation["id"], "revision": 1}, "ru"
    )
    unit = workspace.units([source["id"]])[0]

    def generate(prompt, schema, *args, **kwargs):
        for term in seeds:
            assert all(term[key] in prompt for key in ("term", "sense", "translation"))
        return {
            "title": "Два значения log",
            "language": "ru",
            "evidence_status": "supported",
            "sections": [
                {
                    "heading": "Журнал и бревно",
                    "text": "В тексте различаются журнал базы данных и деревянное бревно.",
                    "origin": "sources",
                    "citations": [unit["id"]],
                    "quotes": [{"citation": unit["id"], "text": unit["text"]}],
                }
            ],
        }

    monkeypatch.setattr("brofessor.infrastructure.text.runners.generate", generate)
    monkeypatch.setattr("brofessor.application.worker.ensure_worker", lambda _: None)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "-w",
            str(workspace.path),
            "report",
            "Два значения log",
            "--template",
            "reference",
            "--terminology-job",
            translation["id"],
            "--terminology-revision",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    cli_job = json.loads(result.output)
    worker.run(workspace, once=True)
    assert workspace.job(cli_job["id"])["status"] == "succeeded"
    exported = markdown(workspace, cli_job["id"]).read_text()
    for term in seeds:
        assert f"{term['term']} ({term['sense']}): {term['translation']}" in exported
    assert workspace.draft(translation["id"], 1) == accepted
    wrong_language = copy.deepcopy(workspace.draft(cli_job["id"])["data"])
    wrong_language["language"] = "en"
    with pytest.raises(ValueError, match="report language"):
        service.edit_draft(workspace, cli_job["id"], wrong_language, 1)
    assert workspace.draft(cli_job["id"])["revision"] == 1
    monkeypatch.setattr("sys.argv", ["ui.py", "--workspace", str(workspace.path)])
    ui = AppTest.from_file(UI_APP, default_timeout=30).run()
    create(ui)
    ui.selectbox(key=new_key(ui, "kind")).select("report").run()
    ui.selectbox(key=new_key(ui, "template")).select("reference").run()
    ui.selectbox(key=new_key(ui, "terminology")).select(translation["id"]).run()
    ui.text_area(key=new_key(ui, "focus")).set_value("Два значения log").run()
    ui.button(key="prepare").click().run()
    assert not ui.exception
    assert workspace.jobs()[0]["params"] == cli_job["params"]
