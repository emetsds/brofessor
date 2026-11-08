"""Readable prompt resources, one-pass substitution, and frozen job inputs."""

import copy
import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.resources import files
from typing import Final, TypedDict

from brofessor.contracts.jobs import (
    CONSOLIDATION_JOB_KINDS,
    READING_WORKFLOW_JOB_KINDS,
    RETRIEVAL_JOB_KINDS,
    TEXT_JOB_KINDS,
    JobKind,
)
from brofessor.contracts.text import MessageRole, RunnerMessage, TextProvider
from brofessor.prompts import ids as prompt_ids

CATALOGUE_FILENAME: Final = "catalogue.json"
TEMPLATE_SUFFIX: Final = ".md"

SNAPSHOT_KEY: Final = "prompt_snapshot"
SNAPSHOT_VERSION: Final = 1


class PromptSpec(TypedDict):
    variables: list[str]
    source: str
    purpose: str
    schema: str
    versions: str
    uses: list[str]
    path: str


class PromptSnapshot(TypedDict):
    version: int
    templates: dict[str, str]
    hashes: dict[str, str]
    sha256: str


_VARIABLE = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
_ACTIVE: ContextVar[PromptSnapshot | None] = ContextVar("brofessor_prompt_snapshot", default=None)


class PromptError(ValueError):
    """A prompt cannot be assembled safely before inference."""


def catalogue() -> dict[str, PromptSpec]:
    return json.loads(files(__package__).joinpath(CATALOGUE_FILENAME).read_text(encoding="utf-8"))


def location(identifier):
    if identifier not in catalogue():
        raise PromptError(f"Unknown prompt ID: {identifier}")
    return files(__package__).joinpath(identifier + TEMPLATE_SUFFIX)


def available():
    active = _ACTIVE.get()
    return set(catalogue() if active is None else active["templates"])


def snapshot_info():
    active = _ACTIVE.get()
    return (
        {"version": active["version"], "sha256": active["sha256"]} if active is not None else None
    )


def _validate(identifier, text, spec):
    if not isinstance(text, str) or not text:
        raise PromptError(f"Prompt {identifier}: template is empty or is not text")
    variables = set(_VARIABLE.findall(text))
    invalid = variables - set(spec["variables"])
    if invalid:
        raise PromptError(f"Prompt {identifier}: unknown variables: {', '.join(sorted(invalid))}")
    rest = _VARIABLE.sub("", text)
    if "{{" in rest:
        raise PromptError(f"Prompt {identifier}: malformed variable; use {{{{variable_name}}}}")
    return variables


def render(identifier, **values):
    """Substitute named values once; source text is never parsed as a template."""
    specs = catalogue()
    if identifier not in specs:
        raise PromptError(f"Unknown prompt ID: {identifier}")
    active = _ACTIVE.get()
    if active is None:
        try:
            text = location(identifier).read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise PromptError(
                f"Prompt {identifier}: missing template at {location(identifier)}"
            ) from error
    else:
        try:
            text = active["templates"][identifier]
        except KeyError as error:
            raise PromptError(
                f"Prompt {identifier}: absent from the job's frozen inputs"
            ) from error
    variables = _validate(identifier, text, specs[identifier])
    missing = variables - values.keys()
    unknown = values.keys() - set(specs[identifier]["variables"])
    if missing or unknown:
        details = []
        if missing:
            details.append("missing values: " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown values: " + ", ".join(sorted(unknown)))
        raise PromptError(f"Prompt {identifier}: {'; '.join(details)}")
    return _VARIABLE.sub(lambda match: str(values[match[1]]), text)


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _bundle(templates: dict[str, str]) -> PromptSnapshot:
    return {
        "version": SNAPSHOT_VERSION,
        "templates": templates,
        "hashes": {
            key: hashlib.sha256(text.encode("utf-8")).hexdigest() for key, text in templates.items()
        },
        "sha256": _digest(templates),
    }


def snapshot(kind: str, params: dict) -> PromptSnapshot:
    """Freeze the applicable template families, for the selected workflow."""
    if kind not in TEXT_JOB_KINDS:
        raise PromptError(f"No text prompt family for job kind: {kind}")
    ids = {prompt_ids.COMMON_RUNNER}
    if kind == JobKind.REVIEW_STUDY:
        ids.add(prompt_ids.STUDIES_REVIEW)
    if kind == JobKind.CHECK_PODCAST:
        ids.update({prompt_ids.PODCASTS_CHECK, prompt_ids.PODCASTS_CHECK_PACKET})
    prefixes = set()
    if kind in READING_WORKFLOW_JOB_KINDS:
        prefixes.add("common/")
        if params.get("collections") and not params.get("source_snapshot_job"):
            prefixes.add("navigation/")
    if kind in RETRIEVAL_JOB_KINDS:
        prefixes.add("questions/")
    if kind in CONSOLIDATION_JOB_KINDS:
        prefixes.add("reading/")
    families: dict[str, set[str]] = {
        JobKind.REPORT: {"reports/"},
        JobKind.STUDY: {"studies/"},
        JobKind.SLIDES: {"slides/"},
        JobKind.PODCAST: {"podcasts/"},
        JobKind.PODCAST_SERIES: {"podcasts/"},
        JobKind.TRANSLATE_EPUB: {"books/"},
        JobKind.TRANSLATE_PDF: {"books/"},
    }
    prefixes.update(families.get(kind, set()))
    templates = {}
    for identifier, spec in catalogue().items():
        if identifier not in ids and not any(identifier.startswith(p) for p in prefixes):
            continue
        try:
            text = location(identifier).read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise PromptError(
                f"Prompt {identifier}: missing template at {location(identifier)}"
            ) from error
        _validate(identifier, text, spec)
        templates[identifier] = text
    return _bundle(templates)


def _check_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("version") != SNAPSHOT_VERSION:
        raise PromptError("Unsupported prompt snapshot version")
    try:
        expected = _bundle(snapshot["templates"])
        if snapshot != expected:
            raise PromptError("Prompt snapshot hashes do not match its frozen text")
        specs = catalogue()
        for identifier, text in snapshot["templates"].items():
            if identifier not in specs:
                raise PromptError(f"Unknown frozen prompt ID: {identifier}")
            _validate(identifier, text, specs[identifier])
        if prompt_ids.COMMON_RUNNER not in snapshot["templates"]:
            raise PromptError("Prompt snapshot is missing the runner boundary")
    except (KeyError, TypeError, AttributeError) as error:
        raise PromptError("Malformed prompt snapshot") from error


@contextmanager
def use_snapshot(snapshot: PromptSnapshot):
    """Use frozen templates across synchronous code, asyncio, and to_thread calls."""
    selected = copy.deepcopy(snapshot)
    _check_snapshot(selected)
    token = _ACTIVE.set(selected)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def messages(prompt: str, provider: str) -> list[RunnerMessage]:
    """The exact instruction placement used by each bounded text adapter."""
    boundary = render(prompt_ids.COMMON_RUNNER)
    if provider == TextProvider.OLLAMA:
        return [
            {"role": MessageRole.SYSTEM, "content": boundary},
            {"role": MessageRole.USER, "content": prompt},
        ]
    if provider in {TextProvider.CODEX, TextProvider.CLAUDE}:
        return [{"role": MessageRole.USER, "content": boundary + prompt}]
    raise PromptError(f"Unknown text provider: {provider}")
