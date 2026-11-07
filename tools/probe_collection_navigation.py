"""Exercise prompt-driven directory navigation with the existing real runner.

The original synthetic notes are MIT fixtures. No user vault is read or uploaded.
Connection itself performs no extraction or model calls. Outputs stay ignored.
"""

import argparse
import hashlib
import json
import os
import re
import signal
import time
from pathlib import Path

from brofessor.application import service, worker
from brofessor.contracts.content import ContentLanguage
from brofessor.contracts.jobs import RESUMABLE_JOB_STATUSES, JobKind, JobStatus
from brofessor.contracts.text import DEFAULT_OLLAMA_ADDRESS, TextProvider
from brofessor.features.sources import collections
from brofessor.features.sources import navigation as source_navigation
from brofessor.infrastructure.storage.workspace import Workspace, atomic_json
from brofessor.infrastructure.text import runners as executors


def fixture(root):
    files = {
        "Главная.md": "# Главная\n\nПроекты: [[Projects/River]].\nУчёба: [[Studies/README]].\n",
        "Projects/River.md": "# River\n\nРезультаты текущего эксперимента находятся в [[Trials/North#Результат]]. Ограничения: [[Trials/North#Условия]].\nПредыдущий эксперимент: [[Trials/South]]. Его настройки больше не действуют.\n",
        "Trials/North.md": "---\naliases: [Северный прогон]\ntags: [experiment]\n---\n# Северный прогон\n\n## Результат\nИзмеренный таймаут составил 12 мс.\nЭто результат для одного узла, а не гарантия для кластера.\n\n## Условия\nПроверено 48 запросов на одном узле. Поведение при потере питания не проверялось.\n",
        "Trials/South.md": "# Южный прогон\n\nВ предыдущем эксперименте таймаут составлял 35 мс. Этот прогон предшествовал северному.\n",
        "Studies/README.md": "# Учёба\n\n[[Studies/Graphs]]\n",
        "Studies/Graphs.md": "# Графы\n\nПоиск в ширину использует очередь. Это учебный материал, измерений River здесь нет.\n",
        "Garden.md": "# Сад\n\nВесной посажены три куста роз.\n",
        "Templates/Experiment.md": "# Шаблон\n\nТаймаут: неизвестно. Число запросов: неизвестно. Это незаполненный шаблон.\n",
    }
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(text)
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--provider",
        choices=(TextProvider.CODEX, TextProvider.CLAUDE, TextProvider.OLLAMA),
        default="codex",
    )
    parser.add_argument("--ollama-address", default=DEFAULT_OLLAMA_ADDRESS)
    parser.add_argument("--fault-after-tool", choices=("cancel", "kill"))
    parser.add_argument("--kind", choices=(JobKind.ASK, JobKind.SLIDES), default="ask")
    parser.add_argument("--prompt", help="Alternative task prompt for a separate controlled run")
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    os.environ["XDG_CONFIG_HOME"] = str(folder / "user-config")
    os.environ["XDG_DATA_HOME"] = str(folder / "user-data")
    os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
    root = folder / "vault"
    before = fixture(root)
    workspace = Workspace(folder / "workspace")
    if not worker.is_running(workspace):
        workspace.recover()
    connected = collections.connect(workspace, root)
    prompt = (
        args.prompt
        or "Что измерено в текущем эксперименте River? Укажи таймаут, условия и ограничения. Отличи текущий результат от предыдущего эксперимента."
    )
    job = service.submit(
        workspace,
        args.kind,
        focus=prompt,
        provider=args.provider,
        model=args.model,
        ollama_address=args.ollama_address if args.provider == TextProvider.OLLAMA else None,
        language=ContentLanguage.RU,
        slide_count=3 if args.kind == JobKind.SLIDES else None,
        request_key="directory-probe-pydantic-"
        + args.provider
        + "-"
        + args.kind
        + (":" + hashlib.sha256(prompt.encode()).hexdigest()[:12] if args.prompt else ""),
        start_worker=False,
    )
    if job["status"] in RESUMABLE_JOB_STATUSES:
        workspace.resume(job["id"])
    calls_path = folder / "calls.json"
    calls = json.loads(calls_path.read_text()) if calls_path.exists() else []
    generate, run = executors.generate, executors._run_process
    save = source_navigation.NavigationSession.save
    reported = {}

    def observe(*a, **kw):
        stdout, stderr = run(*a, **kw)
        for label in ("model", "reasoning effort"):
            found = re.search(r"^" + label + r":\s*(\S[^\n]*)$", stderr, re.M)
            if found:
                reported[label] = found[1]
        return stdout, stderr

    def measured(prompt, schema, provider, model=None, **kwargs):
        start = time.monotonic()
        row = {
            "schema": schema["title"],
            "prompt_chars": len(prompt),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "provider": provider,
            "model": model,
        }
        reported.clear()
        try:
            value = generate(prompt, schema, provider, model, **kwargs)
            atomic_json(folder / f"returned-{len(calls):03}-{schema['title']}.json", value)
            row["status"] = "returned"
            return value
        except Exception as error:
            row.update(status=JobStatus.FAILED, error=str(error))
            raise
        finally:
            row.update(seconds=round(time.monotonic() - start, 3), reported=reported.copy())
            calls.append(row)
            atomic_json(calls_path, calls)

    start = time.monotonic()

    def settled(session):
        save(session)
        marker = folder / f"fault-{args.fault_after_tool}.json"
        if (
            args.fault_after_tool
            and session.state["steps"]
            and session.state["status"] == JobStatus.RUNNING
            and not marker.exists()
        ):
            atomic_json(
                marker,
                {
                    "fault": args.fault_after_tool,
                    "job": job["id"],
                    "calls": len(calls),
                    "steps": len(session.state["steps"]),
                },
            )
            if args.fault_after_tool == "kill":
                os.kill(os.getpid(), signal.SIGKILL)
            workspace.cancel(job["id"])
            session.check()

    try:
        executors.generate, executors._run_process = measured, observe
        source_navigation.NavigationSession.save = settled
        worker.run(workspace, once=True)
    finally:
        executors.generate, executors._run_process = generate, run
        source_navigation.NavigationSession.save = save
    job = workspace.job(job["id"])
    result = {
        "job": job,
        "harness": "pydantic",
        "seconds": round(time.monotonic() - start, 3),
        "calls": len(calls),
        "collection": connected,
        "source_files_unchanged": all(
            (root / path).is_file()
            and hashlib.sha256((root / path).read_bytes()).hexdigest() == digest
            for path, digest in before.items()
        ),
        "navigation": source_navigation.report(workspace, job),
        "draft": workspace.draft(job["id"]),
        "evidence": service.answer_evidence(workspace, job["id"])
        if args.kind == JobKind.ASK
        else [],
    }
    atomic_json(
        folder
        / (
            "result-"
            + args.kind
            + ("-" + hashlib.sha256(prompt.encode()).hexdigest()[:12] if args.prompt else "")
            + ".json"
        ),
        result,
    )
    print(
        json.dumps(
            {
                "job": job["id"],
                "harness": "pydantic",
                "provider": args.provider,
                "status": job["status"],
                "error": job["error"],
                "seconds": result["seconds"],
                "calls": len(calls),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if job["status"] == JobStatus.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(main())
