"""A prompt edit belongs to a new run; accepted legacy checkpoints stay reusable."""

import hashlib
import json

import pytest
from typer.testing import CliRunner

from brofessor import prompts
from brofessor.application import pipeline, service, tasks
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind
from brofessor.contracts.text import TextProvider
from brofessor.features.books import translation
from brofessor.infrastructure.storage.workspace import Workspace
from brofessor.infrastructure.text import runners
from brofessor.interfaces.cli.app import app
from tests.helpers.books import translated_book


@pytest.fixture
def workspace(tmp_path):
    store = Workspace(tmp_path / "workspace")
    source = tmp_path / "original.md"
    source.write_text("A synthetic bridge carried 1200 kilograms. Flood resistance is unknown.")
    store.add_source(source)
    return store


@pytest.fixture
def model(workspace, monkeypatch):
    unit = workspace.units()[0]
    calls = []

    def generate(prompt, schema, provider, model=None, **kwargs):
        calls.append(
            {
                "prompt": prompt,
                "schema": schema,
                "provider": provider,
                "model": model,
                "boundary": prompts.render("common/runner"),
            }
        )
        return {
            "answer": "1200 kilograms; flood resistance is unknown.",
            "citations": [unit["id"]],
            "quotes": [{"citation": unit["id"], "text": "1200 kilograms"}],
        }

    monkeypatch.setattr(runners, "generate", generate)
    return calls


def ask(workspace, key=None):
    return service.submit(
        workspace,
        JobKind.ASK,
        focus="What was tested?",
        language=ContentLanguage.EN,
        provider=TextProvider.CODEX,
        model=None,
        request_key=key,
        start_worker=False,
    )


def test_new_runs_see_edits_but_retry_and_resume_keep_frozen_inputs(
    workspace, model, editable_prompts
):
    original = ask(workspace, "same-request")
    frozen = original["params"][prompts.SNAPSHOT_KEY]
    for name in ["questions/answer", "common/runner"]:
        path = editable_prompts / (name + ".md")
        path.write_text("New editorial requirement.\n" + path.read_text())
    retry = ask(workspace, "same-request")
    assert retry["id"] == original["id"] and retry["params"][prompts.SNAPSHOT_KEY] == frozen
    fresh = ask(workspace)
    pipeline.execute(workspace, original)
    pipeline.execute(workspace, fresh)
    assert not model[0]["prompt"].startswith("New editorial")
    assert not model[0]["boundary"].startswith("New editorial")
    assert model[1]["prompt"].startswith("New editorial")
    assert model[1]["boundary"].startswith("New editorial")
    pipeline.execute(workspace, original)
    pipeline.execute(workspace, fresh)
    assert len(model) == 2
    assert workspace.job(original["id"])["params"][prompts.SNAPSHOT_KEY] == frozen
    regenerated = tasks.regenerate(workspace, original["id"], start_worker=False)
    assert regenerated["params"][prompts.SNAPSHOT_KEY] == fresh["params"][prompts.SNAPSHOT_KEY]


def test_term_retry_keeps_its_first_templates_even_if_current_edit_is_invalid(
    tmp_path, monkeypatch, editable_prompts
):
    workspace, _, job, _ = translated_book(tmp_path, monkeypatch)
    term = workspace.draft(job["id"])["data"]["terms"][0]
    first = translation.revise_term(
        workspace,
        job["id"],
        term["id"],
        "журнал событий",
        request_key="same-term",
        start_worker=False,
    )
    (editable_prompts / "books/revise_term.md").write_text("{{invalid_current_template}}")
    retry = translation.revise_term(
        workspace,
        job["id"],
        term["id"],
        "журнал событий",
        request_key="same-term",
        start_worker=False,
    )
    assert retry["id"] == first["id"]
    assert retry["params"][prompts.SNAPSHOT_KEY] == first["params"][prompts.SNAPSHOT_KEY]


def test_runner_instructions_participate_in_new_checkpoint_identity(
    workspace, model, editable_prompts
):
    first = ask(workspace)
    boundary = editable_prompts / "common/runner.md"
    boundary.write_text("Changed runner instruction.\n" + boundary.read_text())
    second = ask(workspace)
    pipeline.execute(workspace, first)
    pipeline.execute(workspace, second)
    assert model[0]["prompt"] == model[1]["prompt"]
    assert model[0]["boundary"] != model[1]["boundary"]

    def fingerprint(job):
        return {
            p.name for p in (workspace.path / "jobs" / job["id"] / "checkpoints").glob("*.json")
        }

    assert fingerprint(first) != fingerprint(second)


def test_legacy_checkpoint_and_user_revision_survive_current_template_edits(
    workspace, model, editable_prompts, monkeypatch
):
    legacy = workspace.submit(
        JobKind.ASK,
        {
            "source_ids": [s["id"] for s in workspace.sources()],
            "focus": "What was tested?",
            "language": "en",
            "provider": "codex",
            "model": None,
        },
    )
    original_write = pipeline.atomic_json

    def fail_publication(path, value):
        if path.name.startswith("draft-r"):
            raise OSError("Controlled publication failure after checkpoint")
        return original_write(path, value)

    monkeypatch.setattr(pipeline, "atomic_json", fail_publication)
    with pytest.raises(OSError, match="Controlled"):
        pipeline.execute(workspace, legacy)
    # Exact historical identity, before runner messages were added to new runs.
    identity = {key: model[0][key] for key in ("prompt", "schema", "provider", "model")}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    checkpoint = workspace.path / "jobs" / legacy["id"] / "checkpoints" / (digest + ".json")
    accepted = checkpoint.read_bytes()
    current = workspace.draft(legacy["id"])
    workspace.save_draft(legacy["id"], {**current["data"], "answer": "My saved revision"}, 1)
    for name in ["questions/answer", "common/materials", "common/runner"]:
        (editable_prompts / (name + ".md")).write_text("{{invalid_current_template}}")
    monkeypatch.setattr(pipeline, "atomic_json", original_write)
    pipeline.execute(workspace, legacy)
    assert len(model) == 1 and checkpoint.read_bytes() == accepted
    assert workspace.draft(legacy["id"])["data"]["answer"] == "My saved revision"
    assert prompts.SNAPSHOT_KEY not in workspace.job(legacy["id"])["params"]


def test_invalid_template_prevents_new_job_and_inference(workspace, model, editable_prompts):
    (editable_prompts / "questions/answer.md").write_text("Use {{unknown_input}}")
    with pytest.raises(prompts.PromptError, match="unknown variables: unknown_input"):
        ask(workspace)
    assert workspace.jobs() == [] and model == []


def test_changed_snapshot_is_rejected_before_inference(workspace, model):
    job = ask(workspace)
    job["params"][prompts.SNAPSHOT_KEY]["templates"]["common/runner"] += " changed"
    with pytest.raises(prompts.PromptError, match="hashes do not match"):
        pipeline.execute(workspace, job)
    assert model == [] and workspace.draft(job["id"]) is None


def test_job_preview_reads_frozen_templates_and_legacy_without_inference(
    workspace, model, editable_prompts
):
    job = ask(workspace)
    path = editable_prompts / "questions/answer.md"
    path.write_text("New wording\n" + path.read_text())
    result = CliRunner().invoke(
        app,
        ["-w", str(workspace.path), "prompts", "preview", "questions/answer", "--job", job["id"]],
    )
    assert result.exit_code == 0, result.output
    preview = json.loads(result.output)
    assert preview["source"] == "frozen" and "New wording" not in preview["component"]
    assert preview["snapshot"]["sha256"] == job["params"][prompts.SNAPSHOT_KEY]["sha256"]
    assert model == []
