"""Bounded real-model writing pilot on generated, redistributable source material.

Uses the configured official Codex CLI; never renders speech or edits user preferences.
All prompts, checkpoints and the call ledger stay in the explicit output directory.
"""

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

from brofessor import prompts
from brofessor.application import service
from brofessor.contracts.content import ContentLanguage, Speaker, UnitStatus
from brofessor.contracts.jobs import JobKind, JobStatus
from brofessor.contracts.text import TextProvider
from brofessor.features.podcasts import checks as script_checks
from brofessor.features.podcasts import episode_writer
from brofessor.features.podcasts import writer as podcasts
from brofessor.features.sources import reading
from brofessor.infrastructure.storage.workspace import Workspace, atomic_json
from brofessor.infrastructure.text import runners as executors
from brofessor.models import Podcast, validate_citations
from brofessor.prompts import ids as prompt_ids

FACTS = [
    ("report", "The fictional Larkspan prototype was tested indoors in a dry fixture."),
    ("report", "The demonstrated load was eighty kilograms, distributed across the marked tray."),
    ("report", "The test did not establish a collapse load or a safe public operating limit."),
    ("report", "Flood conditions and immersion were not tested."),
    ("report", "The initial report recorded twelve working measurement channels."),
    ("report", "The initial report recorded a peak deflection of five millimetres."),
    (
        "report",
        "Thirty-six records were repeated observations, not thirty-six independent bridges.",
    ),
    (
        "report",
        "The run was paused at the preset wind threshold; the pause was not a structural failure.",
    ),
    (
        "report",
        "One hundred and twenty kilograms was the storage trolley mass, not a tested bridge load.",
    ),
    ("report", "The May log places the start of run DRY-SEVENTEEN at eight in the morning."),
    (
        "amendment",
        "The June amendment explicitly corrects the working-channel count from twelve to ten.",
    ),
    (
        "amendment",
        "The June amendment explicitly corrects the peak deflection from five to five point four millimetres.",
    ),
    (
        "amendment",
        "The two faulty channels were excluded; adding more observations did not repair them.",
    ),
    (
        "amendment",
        "Eighty kilograms remained the demonstrated distributed load after the correction.",
    ),
    (
        "amendment",
        "The tested tray configuration does not establish performance under a concentrated point load.",
    ),
    ("amendment", "A ninety-kilogram follow-up was proposed but had not been performed."),
    ("amendment", "The amendment does not add flood, immersion, fire or long-term fatigue tests."),
    (
        "amendment",
        "The advertised opening date is a planning announcement, not a safety certification.",
    ),
    (
        "amendment",
        "A claimed fifty-year service life is a design aspiration, not an observed result.",
    ),
    (
        "amendment",
        "The amendment supersedes only the stated channel count and deflection, not every May observation.",
    ),
    (
        "review",
        "An independent transcript places the start of the same DRY-SEVENTEEN run at nine in the morning.",
    ),
    (
        "review",
        "The eight-versus-nine start-time discrepancy remains unresolved because the clocks were not cross-checked.",
    ),
    (
        "review",
        "The review accepts the documented ten-channel correction rather than treating twelve and ten as an unresolved dispute.",
    ),
    ("review", "Photographs showing no visible damage do not exclude internal cracks."),
    ("review", "No ultrasonic inspection was conducted."),
    (
        "review",
        "The single-prototype observations do not establish reliability of future production units.",
    ),
    ("review", "Neither the May report nor the June amendment demonstrates safety during a flood."),
    ("review", "Repeated copies of a statement are not independent confirmations."),
    (
        "review",
        "The reviewer does not infer that the structure is unsafe; the supplied evidence cannot establish the broader safety claim.",
    ),
    (
        "review",
        "All people, documents and measurements in this exercise are invented for software evaluation.",
    ),
]


def corpus(folder):
    folder.mkdir(parents=True, exist_ok=True)
    headings = {
        "report": "May test report, fictional Larkspan project",
        "amendment": "June amendment, fictional Larkspan project",
        "review": "Independent review, fictional Larkspan project",
    }
    paths = []
    for kind, heading in headings.items():
        items = [text for source, text in FACTS if source == kind]
        paragraphs = [
            heading,
            "Synthetic fixture: all facts are fabricated; repeated passages refer to the same evidence.",
        ]
        cycle = 0
        while len("\n\n".join(paragraphs)) < 18000:
            for text in items:
                cycle += 1
                paragraphs.append(
                    f"Notebook entry {cycle}. {text} This entry belongs to {heading}. "
                    "When comparing accounts, retain the documented conditions, distinguish an observation "
                    "from a proposal and leave unmeasured properties unknown. Repetition in this notebook "
                    "does not create an additional experiment or strengthen an inference."
                )
        path = folder / (kind + ".txt")
        path.write_text("\n\n".join(paragraphs), encoding="utf-8")
        paths.append(path)
    atomic_json(
        folder / "truth.json",
        [
            {"id": f"F{i + 1:02}", "source": source, "fact": text}
            for i, (source, text) in enumerate(FACTS)
        ],
    )
    return paths


class Calls:
    def __init__(self, folder, allowed):
        self.folder, self.allowed = folder, allowed
        self.ledger = folder / "calls.json"
        self.entries = json.loads(self.ledger.read_text()) if self.ledger.exists() else []

    def __call__(self, prompt, schema, citation_scope=None, validate=None):
        identity = {
            "prompt": prompt,
            "schema": schema.model_json_schema(),
            "provider": TextProvider.CODEX,
            "model": None,
        }
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        path = self.folder / "checkpoints" / (key + ".json")
        if path.exists():
            value = json.loads(path.read_text())
        else:
            if len(self.entries) >= 30:
                raise RuntimeError("Pilot reached its thirty-call limit")
            entry = {
                "number": len(self.entries) + 1,
                "key": key,
                "schema": schema.__name__,
                "prompt_characters": len(prompt),
                "status": "started",
            }
            self.entries.append(entry)
            atomic_json(self.ledger, self.entries)
            atomic_json(self.folder / "prompts" / (key + ".json"), identity)
            started = time.monotonic()
            print(
                f"call {entry['number']}/30: {schema.__name__}, {len(prompt)} input characters",
                flush=True,
            )
            try:
                value = executors.generate(
                    prompt, identity["schema"], TextProvider.CODEX, workdir=self.folder / "runner"
                )
            except Exception as error:
                entry.update(
                    status=JobStatus.FAILED,
                    error=str(error),
                    seconds=round(time.monotonic() - started, 2),
                )
                atomic_json(self.ledger, self.entries)
                raise
            entry.update(status="returned", seconds=round(time.monotonic() - started, 2))
            atomic_json(self.ledger, self.entries)
        value = schema.model_validate(value).model_dump()
        validate_citations(value, self.allowed if citation_scope is None else citation_scope)
        if issubclass(schema, Podcast) and value["language"] != ContentLanguage.RU:
            raise ValueError("Wrong pilot language")
        if validate:
            validate(value)
        atomic_json(path, value)
        return value


def diagnostics(folder, workspace, calls, units, names, evidence, instructions):
    plan_path = folder / "source-aware-plan.json"
    if not plan_path.exists():
        value = episode_writer.make_plan(
            {
                "instructions": instructions,
                "evidence": reading.with_metadata(evidence, units, names),
            },
            20,
            2415,
            calls,
            lambda _: None,
        )
        atomic_json(plan_path, value)

    def citation(text):
        return next(unit["id"] for unit in units if text in unit["text"])

    dry = citation(FACTS[1][1])
    flood = citation(FACTS[3][1])
    amended = citation(FACTS[10][1])
    aspiration = citation(FACTS[18][1])
    test_turns = [
        ("Что именно установила сухая проверка?", [dry], False),
        (
            "В сухом испытании продемонстрировали распределённую нагрузку восемьдесят килограммов.",
            [dry],
            False,
        ),
        ("Мост успешно прошёл испытания при паводке.", [flood], True),
        (
            "Июньское уточнение исправляет число рабочих каналов с двенадцати на десять.",
            [amended],
            False,
        ),
        (
            "Нагрузка восемьдесят килограммов подтверждает безопасную эксплуатацию в течение пятидесяти лет.",
            [dry, aspiration],
            True,
        ),
        ("И после июньского уточнения подтверждены двенадцать исправных каналов.", [amended], True),
    ]
    parent = workspace.submit(
        JobKind.PODCAST,
        {
            "source_ids": [s["id"] for s in workspace.sources()],
            "provider": TextProvider.CODEX,
            "model": None,
            "language": ContentLanguage.RU,
            "minutes": 20,
            "focus": "Controlled review fixture",
        },
        "pilot-review-script",
    )
    if workspace.draft(parent["id"]) is None:
        workspace.save_draft(
            parent["id"],
            {
                "title": "Controlled review fixture",
                "language": ContentLanguage.RU,
                "turns": [
                    {
                        "speaker": Speaker.HOST if i % 2 == 0 else Speaker.GUEST,
                        "text": text,
                        "citations": ids,
                    }
                    for i, (text, ids, _) in enumerate(test_turns)
                ],
            },
        )
    workspace.update_job(parent["id"], status=JobStatus.SUCCEEDED)
    check = service.check_script(
        workspace, parent["id"], request_key="pilot-review-check", start_worker=False
    )
    if workspace.job(check["id"])["status"] != JobStatus.SUCCEEDED:
        workspace.update_job(check["id"], status=JobStatus.RUNNING)
        result = script_checks.run(workspace, check, calls, lambda _: None, lambda: None)
        workspace.update_job(check["id"], status=JobStatus.SUCCEEDED)
    else:
        result = script_checks.report(workspace, check["id"])
    by_turn = {row["turn"]: row for row in result["assessments"]}
    atomic_json(
        folder / "review-diagnostics.json",
        {
            "check_id": check["id"],
            "results": [
                {
                    "turn": i + 1,
                    "expected_issue": expected,
                    "actual": by_turn[i + 1]["status"],
                    "finding_kinds": [f["kind"] for f in by_turn[i + 1]["findings"]],
                }
                for i, (_, _, expected) in enumerate(test_turns)
            ],
        },
    )


def run(folder):
    folder.mkdir(parents=True, exist_ok=True)
    w = Workspace(folder / "workspace")
    for path in corpus(folder / "corpus"):
        w.add_source(path)
    units = w.units()
    names = {item["id"]: item["name"] for item in w.sources()}
    calls = Calls(folder, {item["id"] for item in units if item["status"] == UnitStatus.READY})
    focus = (
        "Объясни на вымышленном примере Larkspan, как читать испытания и сопоставлять несколько "
        "документов. Различай наблюдение, исправление ошибки, нерешённое расхождение и "
        "непроверенное свойство. Сохрани числа, отрицания и границы вывода; избегай повторов."
    )
    evidence_file = folder / "evidence.json"
    if evidence_file.exists():
        evidence = json.loads(evidence_file.read_text())
    else:
        evidence, _ = reading.prepare(units, focus, calls, lambda: None, lambda _: None, folder)
        atomic_json(evidence_file, evidence)
    instructions = prompts.render(prompt_ids.EXPERIMENTS_EPISODE_MATERIALS, focus=focus)
    base = prompts.render(
        prompt_ids.EXPERIMENTS_EVIDENCE,
        instructions=instructions,
        evidence=json.dumps(evidence, ensure_ascii=False),
    )
    outline_file = folder / "outline.json"
    if outline_file.exists():
        outline = json.loads(outline_file.read_text())
    else:
        outline = calls(
            prompts.render(prompt_ids.EXPERIMENTS_EPISODE_OUTLINE, base=base),
            podcasts.Outline,
        )
        atomic_json(outline_file, outline)
    extended_plan = {
        "title": outline["title"],
        "listener_goal": focus,
        "material_sufficient": True,
        "reason": "Pilot fixes one common plan for both writers",
        "source_relationships": [],
        "sections": [{**item, "weight": 1} for item in outline["sections"]],
    }
    variants = [
        (writer, order) for order in ("forward", "reverse") for writer in ("classic", "originals")
    ]
    identifiers = list("ABCD")
    random.Random(20261104).shuffle(identifiers)
    atomic_json(folder / "mapping.json", dict(zip(identifiers, variants)))
    for blind_id, (method, order) in zip(identifiers, variants):
        output = folder / "blind" / (blind_id + ".json")
        if output.exists():
            continue
        selected = evidence if order == "forward" else list(reversed(evidence))
        print(f"Writing blind sample {blind_id}", flush=True)
        if method == "classic":

            def generate(prompt, schema, **kwargs):
                return outline if schema is podcasts.Outline else calls(prompt, schema, **kwargs)

            result = podcasts.write(
                prompts.render(
                    prompt_ids.EXPERIMENTS_EVIDENCE,
                    instructions=instructions,
                    evidence=json.dumps(selected, ensure_ascii=False),
                ),
                20,
                ContentLanguage.RU,
                generate,
                lambda _: None,
                lambda _: None,
                target_words=2415,
            )
        else:
            ordered_units = (
                units
                if order == "forward"
                else sorted(units, key=lambda u: (u["source_id"], units.index(u)), reverse=True)
            )
            # Preserve internal document order; reverse source order only.
            if order == "reverse":
                ordered_units = [
                    u
                    for sid in reversed(list(dict.fromkeys(u["source_id"] for u in units)))
                    for u in units
                    if u["source_id"] == sid
                ]
            result = episode_writer.write(
                {
                    "instructions": instructions,
                    "units": ordered_units,
                    "names": names,
                    "evidence": selected,
                },
                20,
                ContentLanguage.RU,
                calls,
                lambda _: None,
                lambda _: None,
                target_words=2415,
                plan=extended_plan,
                save_section=lambda n, report: atomic_json(
                    folder / "section-reports" / blind_id / f"{n}.json", report
                ),
            )
        atomic_json(output, result)
    diagnostics(folder, w, calls, units, names, evidence, instructions)
    atomic_json(
        folder / "summary.json",
        {
            "calls": len(calls.entries),
            "source_characters": sum(len(u["text"]) for u in units),
            "source_units": len(units),
            "language": ContentLanguage.RU,
            "target_words": 2415,
            "provider": TextProvider.CODEX,
            "model": "provider default",
            "cli": "0.162.1",
            "samples": {
                p.stem: {
                    "words": podcasts.word_count(json.loads(p.read_text())["turns"]),
                    "turns": len(json.loads(p.read_text())["turns"]),
                }
                for p in (folder / "blind").glob("*.json")
            },
        },
    )
    print(f"Pilot finished with {len(calls.entries)} real calls", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    run(parser.parse_args().directory.resolve())
