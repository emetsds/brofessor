"""Editable package resources isolated from the user's actual prompt files."""

import shutil
from pathlib import Path

import pytest

from brofessor import prompts


@pytest.fixture
def editable_prompts(tmp_path, monkeypatch):
    root = tmp_path / "prompts"
    shutil.copytree(
        Path(prompts.__file__).parent, root, ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.setattr(prompts, "files", lambda _: root)
    return root
