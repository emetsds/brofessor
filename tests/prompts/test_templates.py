"""Preserve historical requests while making current instruction files editable."""

import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from brofessor import prompts
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.text import runners
from brofessor.interfaces.cli.app import app
from brofessor.prompts import examples
from tests.helpers.paths import FIXTURES

CASES = json.loads((FIXTURES / "prompts/extracted-2026-11-07.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_original_requests_survive_in_the_legacy_set(case):
    with prompts.use_snapshot(None):
        assert prompts.render(case["id"], **case["variables"]) == case["expected"]


def test_values_are_inserted_once_and_literal_json_can_be_added(editable_prompts):
    path = editable_prompts / "common/materials.md"
    path.write_text(path.read_text() + '\nExample JSON: {"outer":{"inner":1}}')
    value = '{{not_a_template_variable}}\n$(do not execute) {"text":"данные"}'
    result = prompts.render(
        "common/materials", language=ContentLanguage.RU, language_name="Russian", focus=value
    )
    assert value in result
    assert result.endswith('Example JSON: {"outer":{"inner":1}}')


@pytest.mark.parametrize(
    "identifier,values,message",
    [
        ("missing/prompt", {}, "Unknown prompt ID"),
        ("questions/answer", {}, "missing values: base"),
        ("common/runner", {"typo": "value"}, "unknown values: typo"),
    ],
)
def test_bad_ids_and_inputs_have_specific_errors(identifier, values, message):
    with pytest.raises(prompts.PromptError, match=message):
        prompts.render(identifier, **values)


def test_missing_file_and_malformed_variable_are_diagnosed(editable_prompts):
    path = editable_prompts / "questions/answer.md"
    path.unlink()
    with pytest.raises(prompts.PromptError, match="questions/answer: missing template"):
        prompts.render("questions/answer", base="Originals")
    path.write_text("{{ base }}")
    with pytest.raises(prompts.PromptError, match="malformed variable"):
        prompts.snapshot("ask", {})


def test_async_runner_inherits_the_frozen_boundary(editable_prompts):
    frozen = prompts.snapshot("ask", {})
    boundary = frozen["templates"]["common/runner"]
    (editable_prompts / "common/runner.md").write_text("New runner instructions\n")

    async def collect():
        return await asyncio.to_thread(prompts.messages, "Synthetic request", "ollama")

    with prompts.use_snapshot(frozen):
        assert asyncio.run(collect()) == [
            {"role": "system", "content": boundary},
            {"role": "user", "content": "Synthetic request"},
        ]
    assert prompts.messages("Synthetic request", "codex")[0]["content"].startswith("New runner")


def test_all_previews_include_the_actual_runner_frame_without_inference(monkeypatch):
    monkeypatch.setattr(runners, "generate", lambda *a, **k: pytest.fail("Preview ran a model"))
    for provider in ("codex", "claude", "ollama"):
        result = CliRunner().invoke(app, ["prompts", "preview", "--all", "--provider", provider])
        assert result.exit_code == 0, result.output
        for item in json.loads(result.output):
            assert item["synthetic_example"]
            assert Path(item["path"]).is_file()
            boundary = prompts.render("common/runner")
            if provider == "ollama":
                assert [message["role"] for message in item["messages"]] == ["system", "user"]
                assert item["messages"][0]["content"] == boundary
            else:
                assert [message["role"] for message in item["messages"]] == ["user"]
                assert item["messages"][0]["content"].startswith(boundary)


def test_preview_and_codex_transport_use_the_same_bytes(tmp_path, monkeypatch):
    result = CliRunner().invoke(app, ["prompts", "preview", "questions/answer"])
    assert result.exit_code == 0, result.output
    preview = json.loads(result.output)
    transmitted = []

    def run(args, **kwargs):
        transmitted.append(kwargs["prompt"])
        Path(args[args.index("-o") + 1]).write_text('{"answer":"ok"}')
        return "", ""

    for name in runners._BILLING_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runners, "_binary", lambda _: "/fake/codex")
    monkeypatch.setattr(runners, "_auth_mode", lambda *a, **k: None)
    monkeypatch.setattr(runners, "_run_process", run)
    runners.generate(preview["component"], {"type": "object"}, TextProvider.CODEX, workdir=tmp_path)
    assert transmitted == [preview["messages"][0]["content"]]


def test_custom_preview_inputs_are_not_interpreted_as_templates():
    value = "{{focus}} is original data, not another substitution."
    preview = examples.preview("questions/answer", variables={"base": value})
    assert preview["component"].startswith(value)
    assert not preview["synthetic_example"]


def test_input_budget_includes_the_editable_runner_boundary(tmp_path, monkeypatch):
    boundary_size = len(prompts.render("common/runner").encode("utf-8"))
    monkeypatch.setattr(runners, "_MAX_BYTES", boundary_size + 5)
    monkeypatch.setattr(
        runners, "_binary", lambda _: pytest.fail("Oversized instructions reached runner setup")
    )
    with pytest.raises(RuntimeError, match="Assembled messages exceed"):
        runners.generate("ten bytes!", {"type": "object"}, TextProvider.CODEX, workdir=tmp_path)
