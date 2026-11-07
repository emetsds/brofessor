"""Book translation services and worker stages using the existing workspace/queue."""

import hashlib
import json

from brofessor.contracts.content import ArtifactKind, ContentLanguage
from brofessor.contracts.jobs import TRANSLATION_JOB_KINDS, JobKind, StageId
from brofessor.features.books import terminology
from brofessor.infrastructure.formats.contracts import DocumentExtension, DocumentFormat
from brofessor.infrastructure.formats.epub import EpubBook, validate_batch
from brofessor.infrastructure.storage.workspace import JOBS_DIRECTORY, atomic_json


def kind_for_source(workspace, source_id):
    from pathlib import Path

    source = next((s for s in workspace.sources() if s["id"] == source_id), None)
    suffix = Path(source["original"]).suffix.lower() if source else ""
    if suffix not in (DocumentExtension.EPUB, DocumentExtension.PDF):
        raise ValueError("Select one EPUB or text-layer PDF source for translation")
    return "translate_" + suffix[1:]


def source_book(workspace, params, check=lambda: None):
    from brofessor.application.service import artifact_path

    ids = params["source_ids"]
    if len(ids) != 1:
        raise ValueError("Select one EPUB or PDF source for translation")
    source = next((source for source in workspace.sources() if source["id"] == ids[0]), None)
    if source is None:
        raise ValueError("Unknown translation source")
    path = artifact_path(workspace, source["original"])
    if path.suffix.lower() == DocumentExtension.PDF:
        from pypdf.errors import PdfReadError
        from pypdfium2 import PdfiumError

        from brofessor.infrastructure.formats.pdf import PdfBook

        try:
            book = PdfBook(path, projection_version=params.get("pdf_projection", 1), check=check)
        except (PdfReadError, PdfiumError) as error:
            raise ValueError(f"Cannot translate PDF: {error}") from error
    elif path.suffix.lower() == DocumentExtension.EPUB:
        book = EpubBook(path, projection_version=params.get("epub_projection", 1))
    else:
        raise ValueError("Book translation supports reflowable EPUB 2/3 and text-layer PDF")
    if book.source_hash != source["hash"] or book.source_hash != params.get(
        "source_sha256", source["hash"]
    ):
        raise ValueError("The original book changed; import it as a new source")
    return book


def submit(
    workspace,
    *,
    source_ids,
    language,
    provider,
    model,
    ollama_address=None,
    glossary=None,
    title=None,
    request_key=None,
    start_worker=True,
    kind=JobKind.TRANSLATE_EPUB,
):
    from brofessor.application import service, tasks

    if language not in (ContentLanguage.RU, ContentLanguage.EN):
        raise ValueError("Choose ru or en")
    choices = tasks.initial_models(
        kind,
        {
            "provider": provider,
            "model": model,
            **({"ollama_address": ollama_address} if ollama_address is not None else {}),
        },
    )
    ids = (
        source_ids
        if source_ids is not None
        else [source["id"] for source in workspace.sources() if not source.get("hidden")]
    )
    if len(ids) != 1 or kind_for_source(workspace, ids[0]) != kind:
        raise ValueError("Choose one source matching the translation format")
    params = {
        "source_ids": ids,
        **({"pdf_projection": 2} if kind == JobKind.TRANSLATE_PDF else {"epub_projection": 3}),
    }
    book = source_book(workspace, params)
    params.update(
        source_sha256=book.source_hash,
        language=language,
        focus=next(source["name"] for source in workspace.sources() if source["id"] == ids[0]),
        glossary_seed=[
            {k: term[k] for k in ("term", "sense", "translation")}
            for term in terminology.seeds(glossary)
        ],
        translation_version=4,
    )
    if title is not None:
        params["task_title"] = tasks.initial_title(kind, params["focus"], title)
    params = service._with_models(params, choices)
    job = service._submit_text(workspace, kind, params, request_key, task_models=choices)
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return service._remember_task(workspace, job)


def validate_state(book, state):
    value = terminology.Translation.model_validate(state).model_dump()
    if value["source_sha256"] != book.source_hash:
        raise ValueError("Translation refers to another source snapshot")
    validate_batch(terminology.render_value(value), book.blocks)
    terms = {term["id"]: term for term in value["terms"]}
    occurrences = {item["id"]: item for item in value["occurrences"]}
    if len(terms) != len(value["terms"]) or len(occurrences) != len(value["occurrences"]):
        raise ValueError("Duplicate terminology IDs")
    source = {block.id: terminology.MARKER.sub("", block.text) for block in book.blocks}
    source_spans = {}
    for occurrence in occurrences.values():
        block_id = occurrence["block_id"]
        if block_id not in source or occurrence["term_id"] not in terms:
            raise ValueError("Terminology must resolve to original blocks and meanings")
        if source[block_id][occurrence["start"] : occurrence["end"]] != occurrence["surface"]:
            raise ValueError("Terminology surface no longer matches its original span")
        source_spans.setdefault(block_id, []).append((occurrence["start"], occurrence["end"]))
    for spans in source_spans.values():
        terminology.no_overlaps(spans)
    seen = []
    for block in value["blocks"]:
        spans = []
        for anchor in block["anchors"]:
            occurrence = occurrences.get(anchor["occurrence_id"])
            if occurrence is None or occurrence["block_id"] != block["id"]:
                raise ValueError("Translation anchor refers to another block")
            seen.append(anchor["occurrence_id"])
            if anchor["manual"]:
                if anchor["start"] is not None or anchor["end"] is not None:
                    raise ValueError("Manually changed phrases must not retain automatic anchors")
                continue
            start, end = anchor["start"], anchor["end"]
            if start is None or end is None or not 0 <= start < end <= len(block["text"]):
                raise ValueError("Invalid translation anchor")
            if terminology.MARKER.search(block["text"][start:end]):
                raise ValueError("Translation anchor crosses an inline marker")
            spans.append((start, end))
        terminology.no_overlaps(spans)
    if len(seen) != len(occurrences) or set(seen) != set(occurrences):
        raise ValueError("Every terminology occurrence needs one saved translation anchor")
    if not set(value["retained_manual"]) <= set(occurrences):
        raise ValueError("Unknown retained manual occurrence")
    return value


def title(book, value):
    if getattr(book, "format", DocumentFormat.EPUB) == DocumentFormat.PDF:
        return value["blocks"][0]["text"][:200]
    originals = {block.id: block for block in book.blocks}
    return next(
        (
            block["text"]
            for block in value["blocks"]
            if originals[block["id"]].document == book.package_path
            and originals[block["id"]].text == book.title
        ),
        book.source.stem,
    )


def export(workspace, job, book, saved, check):
    state = validate_state(book, saved["data"])
    folder = workspace.path / JOBS_DIRECTORY / job["id"]
    format = getattr(book, "format", DocumentFormat.EPUB)
    output = folder / f"translation-r{saved['revision']}.{format}"
    check()
    report = book.render(
        terminology.render_value(state),
        output,
        state["language"],
        **({"check": check} if format == DocumentFormat.PDF else {}),
    )
    check()
    metadata = {
        "revision": saved["revision"],
        "source_sha256": book.source_hash,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "retained_manual": state["retained_manual"],
    }
    if format == DocumentFormat.PDF:
        mapping = folder / f"layout-r{saved['revision']}.json"
        atomic_json(mapping, report)
        metadata.update(
            pdf_projection=book.projection_version,
            layout=str(mapping.relative_to(workspace.path)),
            preserved=report["preserved"],
            renderer=report["renderer"],
        )
    else:
        metadata.update(
            epub_projection=book.projection_version, preserved_notices=book.preserved_notices
        )
    workspace.add_artifact(
        job["id"],
        output,
        format,
        metadata,
    )


def run(workspace, job, generate, progress, check):
    params = job["params"]
    if params.get("translation_version") not in (1, 2, 3, 4):
        raise ValueError("Unsupported book translation workflow version")
    book = source_book(workspace, params, check)
    saved = workspace.draft(job["id"])
    if saved is None:
        if params.get("terminology_update"):
            parent = params["regeneration"]
            previous = workspace.draft(parent["job_id"], parent["revision"])
            if previous is None:
                raise ValueError("Choose a saved translation revision")
            state = validate_state(book, previous["data"])
            update = params["terminology_update"]
            state = terminology.revise(
                state, book, update["term_id"], update["translation"], generate, check, progress
            )
        else:
            if params.get("reuse_glossary"):
                parent = params["regeneration"]
                previous = workspace.draft(parent["job_id"], parent["revision"])
                if previous is None:
                    raise ValueError("The saved glossary revision does not exist")
                accepted = validate_state(book, previous["data"])
                terms, occurrences = accepted["terms"], accepted["occurrences"]
                progress(
                    {
                        "stage": StageId.GLOSSARY,
                        "completed": len(book.blocks),
                        "total": len(book.blocks),
                    }
                )
            else:
                terms, occurrences = terminology.discover(
                    book, params["glossary_seed"], params["language"], generate, check, progress
                )
            if params["translation_version"] >= 4:
                terms, occurrences = terminology.review_recurring(
                    book, terms, occurrences, params["language"], generate, check, progress
                )
            blocks = terminology.translate(
                book,
                terms,
                occurrences,
                params["language"],
                generate,
                check,
                progress,
                version=params["translation_version"],
            )
            state = {
                "title": "",
                "language": params["language"],
                "source_id": params["source_ids"][0],
                "source_sha256": book.source_hash,
                "terms": terms,
                "occurrences": occurrences,
                "blocks": blocks,
                "retained_manual": [],
            }
        state["title"] = title(book, state)
        state = validate_state(book, state)
        check()
        saved = workspace.save_draft(job["id"], state)
        path = workspace.path / JOBS_DIRECTORY / job["id"] / f"draft-r{saved['revision']}.json"
        atomic_json(path, state)
        workspace.add_artifact(job["id"], path, ArtifactKind.JSON, {"revision": saved["revision"]})
    progress({"stage": StageId.SAVING})
    export(workspace, job, book, saved, check)
    progress(
        {"stage": StageId.TRANSLATED_BOOK, "completed": len(book.blocks), "total": len(book.blocks)}
    )


def edit(workspace, job_id, data, expected_revision):
    job = workspace.job(job_id)
    previous = workspace.draft(job_id)
    if previous is None or previous["revision"] != expected_revision:
        raise ValueError("Draft changed. Reload it before saving your edits.")
    requested = terminology.Translation.model_validate(data).model_dump()
    old = terminology.Translation.model_validate(previous["data"]).model_dump()
    if {k: v for k, v in requested.items() if k != "blocks"} != {
        k: v for k, v in old.items() if k != "blocks"
    }:
        raise ValueError(
            "Edit translation text only; use the terminology operation to change a meaning"
        )
    old_blocks = {block["id"]: block for block in old["blocks"]}
    for block in requested["blocks"]:
        if block["id"] not in old_blocks or block["anchors"] != old_blocks[block["id"]]["anchors"]:
            raise ValueError("Editing must preserve source IDs and terminology provenance")
    texts = {block["id"]: block["text"] for block in requested["blocks"]}
    if len(texts) != len(requested["blocks"]):
        raise ValueError("Duplicate translation block")
    book = source_book(workspace, job["params"])
    state = terminology.edit_blocks(old, texts)
    state["title"] = title(book, state)
    state = validate_state(book, state)
    saved = workspace.save_draft(job_id, state, expected_revision)
    path = workspace.path / JOBS_DIRECTORY / job_id / f"draft-r{saved['revision']}.json"
    atomic_json(path, state)
    workspace.add_artifact(job_id, path, ArtifactKind.JSON, {"revision": saved["revision"]})
    return saved


def revise_term(
    workspace, job_id, term_id, translation, *, revision=None, request_key=None, start_worker=True
):
    from brofessor.application import service, tasks

    job = workspace.job(job_id)
    if job["kind"] not in TRANSLATION_JOB_KINDS:
        raise ValueError("Choose a book translation")
    saved = workspace.draft(job_id, revision)
    if saved is None:
        raise ValueError("Choose a saved translation revision")
    book = source_book(workspace, job["params"])
    state = validate_state(book, saved["data"])
    term = next((term for term in state["terms"] if term["id"] == term_id), None)
    if term is None:
        raise ValueError("Unknown glossary meaning")
    target = terminology.Seed(
        term=term["term"], sense=term["sense"], translation=translation
    ).translation
    choices = tasks.models(workspace, job_id)["data"]
    params = {
        k: v for k, v in job["params"].items() if k not in ("regeneration", "terminology_update")
    }
    params = service._with_models(params, choices)
    params.update(
        regeneration={"job_id": job_id, "revision": saved["revision"]},
        terminology_update={"term_id": term_id, "translation": target},
        focus=state["title"],
    )
    if request_key and workspace.job_by_request_key(request_key):
        result = service._submit_text(workspace, job["kind"], params, request_key)
    else:
        params = service._text_params(job["kind"], params)
        key = (
            request_key
            or "book-term:"
            + hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        )
        result = service._submit_text(workspace, job["kind"], params, key)
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return service._remember_task(workspace, result)


def render(workspace, job_id, *, revision=None, request_key=None, start_worker=True):
    job = workspace.job(job_id)
    saved = workspace.draft(job_id, revision)
    if job["kind"] not in TRANSLATION_JOB_KINDS or saved is None:
        raise ValueError("Choose a saved book translation")
    params = {
        "draft_job_id": job_id,
        "revision": saved["revision"],
        "source_ids": job["params"]["source_ids"],
        "source_sha256": job["params"]["source_sha256"],
        **(
            {"pdf_projection": job["params"]["pdf_projection"]}
            if job["kind"] == JobKind.TRANSLATE_PDF
            else {"epub_projection": job["params"].get("epub_projection", 1)}
        ),
    }
    validate_state(source_book(workspace, params), saved["data"])
    format = DocumentFormat.PDF if job["kind"] == JobKind.TRANSLATE_PDF else DocumentFormat.EPUB
    key = (
        request_key
        or f"render-{format}:"
        + hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    )
    result = workspace.submit("render_" + format, params, key)
    if start_worker:
        from brofessor.application.worker import ensure_worker

        ensure_worker(workspace)
    return result


def rendered_artifact(workspace, job, revision):
    """Prefer the latest available local export of the selected saved revision."""
    format = DocumentFormat.PDF if job["kind"] == JobKind.TRANSLATE_PDF else DocumentFormat.EPUB
    candidates = [
        job,
        *[
            item
            for item in workspace.jobs()
            if item["kind"] == "render_" + format and item["params"]["draft_job_id"] == job["id"]
        ],
    ]
    from brofessor.application.service import artifact_path

    for candidate in sorted(
        candidates, key=lambda item: (item["created"], item["id"]), reverse=True
    ):
        for artifact in workspace.artifacts(candidate["id"]):
            if (
                artifact["kind"] == format
                and artifact["metadata"]["revision"] == revision
                and artifact_path(workspace, artifact["path"]).is_file()
            ):
                return artifact
    return None
