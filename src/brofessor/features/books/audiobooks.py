"""Verbatim narration of one saved text source with reusable speech and chapters."""

import re
from pathlib import Path
from typing import Final

from pydantic import Field, model_validator

from brofessor.contracts.content import ArtifactKind, ContentLanguage, Speaker, UnitStatus
from brofessor.contracts.jobs import TRANSLATION_JOB_KINDS, JobKind, StageId
from brofessor.features.podcasts.writer import split_turns
from brofessor.features.sources import reading
from brofessor.infrastructure.formats import audio as media
from brofessor.infrastructure.formats.contracts import DocumentExtension
from brofessor.infrastructure.speech import catalogue as speech_models
from brofessor.infrastructure.storage.workspace import JOBS_DIRECTORY, atomic_json
from brofessor.models import Output

CHAPTERS_FILENAME: Final = "chapters.json"


class Passage(Output):
    text: str = Field(min_length=1, max_length=1000)
    citations: list[str] = Field(min_length=1)


class Chapter(Output):
    id: str
    title: str = Field(min_length=1, max_length=200)
    passages: list[Passage] = Field(min_length=1)


class Audiobook(Output):
    title: str = Field(min_length=1)
    language: str
    chapters: list[Chapter] = Field(min_length=1)
    user_edited: bool = False

    @model_validator(mode="after")
    def valid_chapters(self):
        if self.language not in (ContentLanguage.RU, ContentLanguage.EN):
            raise ValueError("Choose ru or en as the language of the narrated text")
        ids = [c.id for c in self.chapters]
        if len(ids) != len(set(ids)):
            raise ValueError("Chapter IDs must be unique")
        return self


def submit(
    workspace,
    source_id,
    *,
    language=ContentLanguage.RU,
    speech_model=None,
    translation=None,
    title=None,
    request_key=None,
    start_worker=True,
):
    from brofessor.application import service, tasks
    from brofessor.features.books import translation as book_translation

    source = next((s for s in workspace.sources() if s["id"] == source_id), None)
    if source is None:
        raise ValueError("Choose one imported text source for an audiobook")
    if language not in (ContentLanguage.RU, ContentLanguage.EN):
        raise ValueError("Choose ru or en as the language of the narrated text")
    original_id = source_id
    if translation is not None:
        if (
            set(translation) != {"job_id", "revision"}
            or type(translation["revision"]) is not int
            or translation["revision"] < 1
        ):
            raise ValueError("Pin the translation to a positive saved revision")
        parent = workspace.job(translation["job_id"])
        saved = workspace.draft(parent["id"], translation["revision"])
        if (
            parent["kind"] not in TRANSLATION_JOB_KINDS
            or parent["params"]["source_ids"] != [source_id]
            or saved is None
        ):
            raise ValueError("Choose a saved translation of this source")
        if saved["data"]["language"] != language:
            raise ValueError("The selected translation must match the narration language")
        artifact = book_translation.rendered_artifact(workspace, parent, saved["revision"])
        if artifact is None:
            book = book_translation.source_book(workspace, parent["params"])
            book_translation.export(workspace, parent, book, saved, lambda: None)
            artifact = book_translation.rendered_artifact(workspace, parent, saved["revision"])
        source = workspace.add_source(
            service.artifact_path(workspace, artifact["path"]),
            hidden=True,
            name=f"{source['name']} · {language} r{saved['revision']}",
        )
    params = {"source_ids": [source["id"]], "original_source_id": original_id, "language": language}
    if translation is not None:
        params["translation"] = translation
    if title is not None:
        params["task_title"] = tasks.initial_title(JobKind.AUDIOBOOK, source["name"], title)
    choices = tasks.initial_models(JobKind.AUDIOBOOK, params, speech_model=speech_model)
    result = service._remember_task(
        workspace, workspace.submit(JobKind.AUDIOBOOK, params, request_key, task_models=choices)
    )
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return result


def prepare(workspace, job, check, progress):
    params = job["params"]
    units = workspace.units(params["source_ids"])
    source = next(s for s in workspace.sources() if s["id"] == params["source_ids"][0])
    folder = workspace.path / JOBS_DIRECTORY / job["id"]
    saved = workspace.draft(job["id"])
    if saved is None:
        chapters = []
        current = None
        previous = None
        markdown = Path(source["original"]).suffix.lower() == DocumentExtension.MARKDOWN

        def chapter(title):
            value = {"id": f"c{len(chapters) + 1}", "title": title[:200], "passages": []}
            chapters.append(value)
            return value

        for unit in units:
            check()
            if unit["status"] != UnitStatus.READY:
                continue
            locator = unit["locator"].split(", chars ", 1)[0]
            if current is None or (not markdown and locator != previous):
                title = next(
                    (line.strip() for line in unit["text"].splitlines() if line.strip()), locator
                )
                current = chapter(title if len(title) <= 120 else locator)
                previous = locator
            pending = []

            def flush():
                text = "".join(pending)
                current["passages"].extend(
                    split_turns(
                        [{"text": text, "citations": [unit["id"]]}],
                        300 if params["language"] == ContentLanguage.RU else 400,
                    )
                )
                pending.clear()

            for line in unit["text"].splitlines(keepends=True):
                heading = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line.strip()) if markdown else None
                if heading:
                    flush()
                    if current["passages"]:
                        current = chapter(heading[1])
                    else:
                        current["title"] = heading[1][:200]
                    pending.append(heading[1] + "\n")
                else:
                    pending.append(line)
            flush()
        chapters = [c for c in chapters if c["passages"]]
        value = Audiobook.model_validate(
            {"title": source["name"], "language": params["language"], "chapters": chapters}
        ).model_dump()
        check()
        saved = workspace.save_draft(job["id"], value)
    output = folder / f"draft-r{saved['revision']}.json"
    atomic_json(output, saved["data"])
    workspace.add_artifact(job["id"], output, ArtifactKind.JSON, {"revision": saved["revision"]})
    coverage = {
        "mode": "narration",
        "excluded": [u["id"] for u in units if u["status"] != UnitStatus.READY],
        "units": [
            {
                "id": u["id"],
                "source_id": u["source_id"],
                "locator": u["locator"],
                "status": "read" if u["status"] == UnitStatus.READY else "excluded",
                "reason": "" if u["status"] == UnitStatus.READY else u["status"],
            }
            for u in units
        ],
    }
    reading.save_coverage(folder, coverage)
    progress({"stage": StageId.DRAFT_READY, "read_units": coverage["count"]})


def turns(value):
    return [
        {**p, "speaker": Speaker.HOST} for chapter in value["chapters"] for p in chapter["passages"]
    ]


def render(workspace, job, cancelled, progress, check):
    from brofessor.infrastructure.speech.references import resolve
    from brofessor.infrastructure.text.runners import _run_process

    params = job["params"]
    saved = workspace.draft(params["draft_job_id"], params["revision"])
    value = Audiobook.model_validate(saved["data"]).model_dump()
    ffmpeg = media._ffmpeg()
    if ffmpeg is None:
        raise ValueError("Install FFmpeg to create an audiobook with chapters")
    folder = workspace.path / JOBS_DIRECTORY / job["id"]
    spec = speech_models.get(params["model_spec"])
    if spec.get("references"):
        spec["references"] = resolve(workspace.path, spec["references"])
    audio = media.render_audio(
        {"language": value["language"], "turns": turns(value)},
        folder / "audiobook.mp3",
        segment_dir=workspace.path / "audio-segments",
        model_spec=spec,
        cancelled=cancelled,
        progress=progress,
    )
    rate = audio["sample_rate"]
    pause = int(rate * 0.25)
    cursor, index = 0, 0
    chapters = []
    for chapter in value["chapters"]:
        start = cursor
        for _ in chapter["passages"]:
            segment = audio["segments"][index]
            cursor += segment["frames"]
            index += 1
            if index < len(audio["segments"]):
                cursor += pause
        chapters.append(
            {
                "id": chapter["id"],
                "title": chapter["title"],
                "start_seconds": start / rate,
                "end_seconds": cursor / rate,
            }
        )

    def escape(text):
        return re.sub(r"([\\=;#\n])", r"\\\1", text)

    metadata = [";FFMETADATA1", "title=" + escape(value["title"])]
    for chapter in chapters:
        metadata.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={round(chapter['start_seconds'] * 1000)}",
                f"END={round(chapter['end_seconds'] * 1000)}",
                "title=" + escape(chapter["title"]),
            ]
        )
    meta_path = folder / "chapters.ffmeta"
    meta_path.write_text("\n".join(metadata) + "\n", encoding="utf-8")
    target, temporary = folder / "audiobook.m4b", folder / ".audiobook.tmp.m4b"
    check()
    progress({"stage": StageId.AUDIO_PACKAGING})
    try:
        # Reuse the existing lifeline supervisor, so FFmpeg cannot outlive a killed worker.
        _run_process(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                audio["wav_path"],
                "-f",
                "ffmetadata",
                "-i",
                str(meta_path),
                "-map",
                "0:a",
                "-map_metadata",
                "1",
                "-map_chapters",
                "1",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-f",
                "ipod",
                str(temporary),
            ],
            cwd=folder,
            timeout=300,
            cancelled=cancelled,
        )
        check()
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    result = {
        "revision": saved["revision"],
        "chapters": chapters,
        "duration_seconds": audio["duration_seconds"],
        "user_edited": value["user_edited"],
        "model": audio["model"],
        "voices": audio["voices"],
        "reused_segments": sum(s["reused"] for s in audio["segments"]),
        "segments": len(audio["segments"]),
    }
    atomic_json(folder / CHAPTERS_FILENAME, result)
    workspace.add_artifact(job["id"], target, ArtifactKind.AUDIOBOOK, result)
    workspace.add_artifact(job["id"], Path(audio["path"]), ArtifactKind.AUDIO, result)
    workspace.add_artifact(job["id"], folder / CHAPTERS_FILENAME, ArtifactKind.JSON, result)
