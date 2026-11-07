"""Reproducible P1 chapter probe, separate from public CLI/UI and the job queue.

Only the bundled synthetic material is sent through the existing bounded runner.
Model responses and metrics stay in an explicit ignored output directory. A
response is reused only when its complete prompt, schema and provider match.
"""

import argparse
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from pydantic import Field

from brofessor import prompts
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import JobStatus
from brofessor.contracts.text import DEFAULT_OLLAMA_ADDRESS, TextProvider
from brofessor.infrastructure.formats.epub import (
    EpubBook,
    TranslationBatch,
    translation_prompt,
    validate_batch,
)
from brofessor.infrastructure.storage.workspace import atomic_json
from brofessor.infrastructure.text import runners as executors
from brofessor.models import Output
from brofessor.prompts import ids as prompt_ids

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/translation"
# Deliberately hand-written for the feasibility comparison. Automatic glossary
# discovery, editing and selective retranslation are later P1 work.
GLOSSARY = [
    {"term": "write-ahead log", "sense": "database recovery", "translation": "журнал предзаписи"},
    {"term": "log", "sense": "database journal", "translation": "журнал"},
    {"term": "log", "sense": "wood in the river", "translation": "бревно"},
    {"term": "hydraulic head", "sense": "hydraulic height quantity", "translation": "напор"},
    {"term": "head", "sense": "leader of the field team", "translation": "руководитель"},
    {"term": "commit", "sense": "durable database transaction", "translation": "фиксация"},
    {"term": "checkpoint", "sense": "database recovery", "translation": "контрольная точка"},
    {"term": "record", "sense": "stored observation", "translation": "запись"},
]


class Document(Output):
    path: str
    xhtml: str = Field(min_length=1)


class WholeDocuments(Output):
    documents: list[Document] = Field(min_length=1)
    metadata: TranslationBatch


def pack_fixture(output):
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=ZIP_STORED)
        for path in sorted(FIXTURE.rglob("*")):
            if path.is_file() and path.name not in {"README.md", "mimetype"}:
                archive.write(path, path.relative_to(FIXTURE).as_posix())


def structural_check(original, translated):
    """Report structure, immutable contents, resources and local link integrity."""
    with ZipFile(original) as source, ZipFile(translated) as target:
        issues = []
        if set(source.namelist()) != set(target.namelist()):
            issues.append("archive resource set changed")
        for name in source.namelist():
            if name.endswith((".css", ".svg")) and source.read(name) != target.read(name):
                issues.append(f"resource changed: {name}")
            if not name.endswith(".xhtml"):
                continue
            before, after = ET.fromstring(source.read(name)), ET.fromstring(target.read(name))

            def shape(root):
                return [
                    (
                        element.tag,
                        {
                            key: value
                            for key, value in element.attrib.items()
                            if key
                            not in {
                                "lang",
                                "{http://www.w3.org/XML/1998/namespace}lang",
                                "alt",
                                "title",
                                "aria-label",
                            }
                        },
                    )
                    for element in root.iter()
                ]

            if shape(before) != shape(after):
                issues.append(f"XML structure/attributes changed: {name}")
            for tag in ("pre", "code", "math"):

                def frozen(root):
                    return [
                        (element.tag, "".join(element.itertext()))
                        for element in root.iter()
                        if element.tag.rsplit("}", 1)[-1] == tag
                    ]

                if frozen(before) != frozen(after):
                    issues.append(f"protected {tag} changed: {name}")
            from urllib.parse import unquote, urlsplit

            from brofessor.infrastructure.formats.ingestion import _href_path

            for element in after.iter():
                href = element.get("href")
                if href is None:
                    continue
                uri = urlsplit(href)
                if uri.scheme or uri.netloc:
                    continue
                path = _href_path(uri.path, str(Path(name).parent)) if uri.path else name
                if path not in target.namelist():
                    issues.append(f"broken link: {name}: {href}")
                elif uri.fragment:
                    ids = {node.get("id") for node in ET.fromstring(target.read(path)).iter()}
                    if unquote(uri.fragment) not in ids:
                        issues.append(f"broken anchor: {name}: {href}")
        return {"issues": issues, "passed": not issues}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--provider",
        choices=(TextProvider.CODEX, TextProvider.CLAUDE, TextProvider.OLLAMA),
        default="codex",
    )
    parser.add_argument("--model", required=True, help="Pin the text model for the comparison")
    parser.add_argument("--ollama-address", default=DEFAULT_OLLAMA_ADDRESS)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    original = folder / "original.epub"
    if not original.exists():
        pack_fixture(original)
    book = EpubBook(original)
    ledger_path = folder / "calls.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    metadata = [block for block in book.blocks if block.document == book.package_path]

    def call(name, prompt, schema):
        request = {
            "prompt": prompt,
            "schema": schema,
            "provider": args.provider,
            "model": args.model,
            "ollama_address": args.ollama_address,
        }
        key = hashlib.sha256(
            json.dumps(request, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        cache = folder / f"{name}-{key[:16]}.json"
        if cache.exists():
            return json.loads(cache.read_text())
        atomic_json(folder / f"{name}-request.json", request)
        timing = time.monotonic()
        reported = {}
        run = executors._run_process

        def observe(*call_args, **kwargs):
            out, err = run(*call_args, **kwargs)
            for label in ("model", "reasoning effort"):
                match = re.search(r"^" + label + r":\s*(\S[^\n]*)$", err, flags=re.M)
                if match:
                    reported[label] = match.group(1)
            return out, err

        row = {
            "method": name,
            "key": key,
            "provider": args.provider,
            "requested_model": args.model,
            "prompt_chars": len(prompt),
            "prompt_bytes": len(prompt.encode()),
            "schema_chars": len(json.dumps(schema)),
        }
        try:
            executors._run_process = observe
            value = executors.generate(
                prompt,
                schema,
                args.provider,
                args.model,
                ollama_address=args.ollama_address,
                workdir=folder / "runner",
                timeout=args.timeout,
            )
            row.update(status="returned", output_chars=len(json.dumps(value, ensure_ascii=False)))
            atomic_json(cache, value)
            return value
        except Exception as error:
            row.update(status=JobStatus.FAILED, error=str(error))
            raise
        finally:
            executors._run_process = run
            row.update(seconds=round(time.monotonic() - timing, 3), reported=reported)
            ledger.append(row)
            atomic_json(ledger_path, ledger)

    # Baseline: let the same model rewrite whole XHTML documents, with the same
    # hand-written terminology. The projection's guarantees are not applied here.
    prompt = prompts.render(
        prompt_ids.EXPERIMENTS_WHOLE_XHTML,
        payload=json.dumps(
            {
                "glossary": GLOSSARY,
                "metadata": [block.as_dict() for block in metadata],
                "documents": [
                    {"path": path, "xhtml": book.entries[path].decode()}
                    for path in book.document_paths
                ],
            },
            ensure_ascii=False,
        ),
    )
    baseline = WholeDocuments.model_validate(
        call("whole-xhtml", prompt, WholeDocuments.model_json_schema())
    )
    paths = [document.path for document in baseline.documents]
    if len(set(paths)) != len(paths) or set(paths) != set(book.document_paths):
        raise ValueError("Baseline changed the document set")
    meta = validate_batch(baseline.metadata.model_dump(), metadata)
    identity = {
        "blocks": [
            {"id": block.id, "text": meta.get(block.id, block.text)} for block in book.blocks
        ]
    }
    baseline_path = folder / "whole-xhtml.epub"
    book.render(identity, baseline_path, ContentLanguage.RU)
    with ZipFile(baseline_path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    contents.update({document.path: document.xhtml.encode() for document in baseline.documents})
    with ZipFile(baseline_path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in contents.items():
            archive.writestr(
                name, content, compress_type=ZIP_STORED if name == "mimetype" else ZIP_DEFLATED
            )
    atomic_json(folder / "whole-xhtml-structure.json", structural_check(original, baseline_path))

    prompt = translation_prompt(book.blocks, "Russian", GLOSSARY)
    value = call("protected-blocks", prompt, TranslationBatch.model_json_schema())
    translated = book.render(value, folder / "protected-blocks.epub", ContentLanguage.RU)
    atomic_json(folder / "protected-blocks-structure.json", structural_check(original, translated))
    translations = validate_batch(value, book.blocks)
    atomic_json(
        folder / "alignment.json",
        {
            "source_sha256": book.source_hash,
            "source_language": book.language,
            "target_language": ContentLanguage.RU,
            "provider": args.provider,
            "model": args.model,
            "glossary": GLOSSARY,
            "blocks": [
                {**block.as_dict(), "translation": translations[block.id]} for block in book.blocks
            ],
        },
    )
    print(
        json.dumps(
            {"output": str(folder), "blocks": len(book.blocks), "calls": ledger}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
