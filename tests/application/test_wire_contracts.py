"""Named Python values must preserve existing schemas and serialized records."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.contracts.text import TextProvider
from brofessor.infrastructure.storage.workspace import Workspace

_SCHEMAS = json.loads(
    (Path(__file__).parents[1] / "fixtures/contracts/model-schema-hashes.json").read_text()
)["schemas"]


@pytest.mark.parametrize("target,expected", _SCHEMAS.items())
def test_model_schema_keeps_existing_checkpoint_identity(target, expected):
    module, name = target.split(":")
    model = getattr(importlib.import_module(module), name)
    encoded = json.dumps(model.model_json_schema(), sort_keys=True).encode()
    assert hashlib.sha256(encoded).hexdigest() == expected


def test_job_record_exposes_plain_strings_after_named_inputs_and_reopening(tmp_path):
    workspace = Workspace(tmp_path)
    job = workspace.submit(
        JobKind.PODCAST,
        {"language": ContentLanguage.RU, "provider": TextProvider.CODEX},
    )
    workspace.update_job(job["id"], status=JobStatus.RUNNING)
    restored = Workspace(tmp_path).job(job["id"])
    assert restored["kind"] == "podcast"
    assert restored["status"] == "running"
    assert restored["params"] == {"language": "ru", "provider": "codex"}
    assert all(
        type(value) is str
        for value in (restored["kind"], restored["status"], *restored["params"].values())
    )


def test_saved_unknown_values_remain_readable_without_defaulting(tmp_path):
    workspace = Workspace(tmp_path)
    job = workspace.submit("legacy_custom_operation", {})
    workspace.update_job(job["id"], status="legacy_state", progress={"stage": "legacy_stage"})
    restored = Workspace(tmp_path).job(job["id"])
    assert restored["kind"] == "legacy_custom_operation"
    assert restored["status"] == "legacy_state"
    assert restored["progress"] == {"stage": "legacy_stage"}
