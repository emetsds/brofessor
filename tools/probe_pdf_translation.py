"""Run the real queued PDF workflow on the original MIT synthetic PDF fixture.

Calls use the chosen existing bounded runner; no API fallback or extra model is
installed. Use a dedicated ignored output folder. User preferences are isolated.
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

from brofessor.application import service, worker
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import RESUMABLE_JOB_STATUSES, JobKind, JobStatus
from brofessor.contracts.text import DEFAULT_OLLAMA_ADDRESS, TextProvider
from brofessor.infrastructure.formats.pdf import PdfBook
from brofessor.infrastructure.storage.workspace import Workspace, atomic_json
from brofessor.infrastructure.text import runners as executors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--source", type=Path, help="Existing complete PDF; default is the synthetic fixture."
    )
    parser.add_argument(
        "--provider",
        choices=(TextProvider.CODEX, TextProvider.CLAUDE, TextProvider.OLLAMA),
        default="codex",
    )
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--language", choices=(ContentLanguage.RU, ContentLanguage.EN), default=ContentLanguage.RU
    )
    parser.add_argument("--ollama-address", default=DEFAULT_OLLAMA_ADDRESS)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CONFIG_HOME"] = str(folder / "user-config")
    os.environ["XDG_DATA_HOME"] = str(folder / "user-data")
    from tests.helpers.pdf import make_pdf

    source = args.source.resolve() if args.source else folder / "source.pdf"
    if not source.exists() and args.source is None:
        make_pdf(source, pages=1)
    book = PdfBook(source)
    atomic_json(
        folder / "projection.json",
        {
            "blocks": [b.as_dict() for b in book.blocks],
            "preserved": book.preserved,
        },
    )
    workspace = Workspace(folder / "workspace")
    imported = workspace.add_source(source)
    job = service.submit(
        workspace,
        JobKind.TRANSLATE_PDF,
        source_ids=[imported["id"]],
        language=args.language,
        provider=args.provider,
        model=args.model,
        ollama_address=args.ollama_address if args.provider == TextProvider.OLLAMA else None,
        request_key="pdf-probe",
        start_worker=False,
    )
    if job["status"] in RESUMABLE_JOB_STATUSES:
        workspace.resume(job["id"])
    ledger_path = folder / "calls.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    original_generate, original_run = executors.generate, executors._run_process
    reported = {}

    def observe(*call_args, **kwargs):
        stdout, stderr = original_run(*call_args, **kwargs)
        for label in ("model", "reasoning effort"):
            match = re.search(r"^" + label + r":\s*(\S[^\n]*)$", stderr, flags=re.M)
            if match:
                reported[label] = match[1]
        return stdout, stderr

    def measured(prompt, schema, provider, model=None, **kwargs):
        started = time.monotonic()
        row = {
            "schema": schema["title"],
            "provider": provider,
            "requested_model": model,
            "prompt_chars": len(prompt),
            "schema_chars": len(json.dumps(schema)),
        }
        reported.clear()
        try:
            value = original_generate(prompt, schema, provider, model, **kwargs)
            atomic_json(folder / f"returned-{len(ledger):03}-{schema['title']}.json", value)
            row.update(status="returned", output_chars=len(json.dumps(value, ensure_ascii=False)))
            return value
        except Exception as error:
            row.update(status=JobStatus.FAILED, error=str(error))
            raise
        finally:
            row.update(seconds=round(time.monotonic() - started, 3), reported=reported.copy())
            ledger.append(row)
            atomic_json(ledger_path, ledger)

    started = time.monotonic()
    try:
        executors.generate, executors._run_process = measured, observe
        worker.run(workspace, once=True)
    finally:
        executors.generate, executors._run_process = original_generate, original_run
    job = workspace.job(job["id"])
    report = {
        "job": job,
        "seconds": round(time.monotonic() - started, 3),
        "artifacts": workspace.artifacts(job["id"]),
        "calls": len(ledger),
    }
    atomic_json(folder / "result.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if job["status"] == JobStatus.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(main())
