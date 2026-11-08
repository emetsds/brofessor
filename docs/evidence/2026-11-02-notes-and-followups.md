# Notes and follow-up questions

Historical report. Current requirements and boundaries are in the [specification](../specification.md), and decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state at the time of the experiment.

Checked 02.11.2026. The remaining M3 item was closed. This check did not include full acceptance, real Claude/Ollama runs, or a clean installation. Subsequent checks are described [separately](2026-11-02-provider-acceptance.md).

## Behavior

The Notes tab and CLI gained free-form notes, saving an answer as a note, and editing with history. Note data consists of `title`, `text`, and `citations`. Origin is stored separately and pins the answer's job/revision. Saving the same answer again returns the current note and preserves the author's edits. Another answer revision creates another note. A new note needs neither a model nor a worker.

SQLite schema 2 adds an append-only notes table. Existing schemas 0/1 upgrade when opened. An old application supporting only schema 1 can no longer open that project. State remains in one SQLite workspace, without a separate database, ORM, or note-file protocol. Expected revision protects against overwriting concurrent changes. The UI provides ordinary text fields, references, version history, and the original answer with its quotes. CLI uses a JSON envelope and the same service.

A follow-up inherits its parent's sources, runner, model setting, and port. Language is inherited by default and can be changed. Jobs save a list of specific answer revisions, so editing the parent after submission does not alter submitted context. Context includes up to six recent question/answer pairs within 12 thousand serialized characters in total. Earlier pairs remain in history, and their omission is shown in UI/CLI. A single oversized answer is not truncated: it must be shortened or followed by a new standalone question.

History helps resolve “это” (“this”) and “тогда” (“then”), but does not become a primary source. Query expansion receives context, and the answer checks facts again against original fragments. Personal notes are not automatically included in the model prompt. The UI blocks actions on unsaved/stale drafts. CLI `ask --reply-to` rejects provider/model/source/port flags supplied at the same time, preventing a silent switch to another profile. Repeated UI submission uses a stable request key for the question and revision.

## Real Codex and control data

Official stable Codex CLI 0.162.1 with the existing subscription login. No API fallback or new models/weights. The exact server-side text-model revision is unknown. Data was synthetic, from the [control corpus](2026-11-02-source-questions.md): a bridge test report, a harbor manual, and a long irrelevant geological background. The pilot contained three sources and 16 readable fragments. Parent and follow-ups used retrieval rather than passing the entire small set.

| Step | Job | Verified result |
|---|---|---|
| Initial load question | `be9eb765088b480b` | 1200 kg in one test; a maximum was not established |
| “А это точно максимум, и почему?” (“Is that definitely the maximum, and why?”) | `acd74f7e57e54346` | Refutes the incorrect earlier note claiming 1400 kg and an established maximum, citing the original |
| “А какой ветер был тогда?” (“What was the wind then?”) | `c4a5f52c26644f1a` | Resolves the bridge-test context: 18 meters per second |
| “А землетрясение?” (“What about an earthquake?”) | `60c49c1007804d6b` | `insufficient_evidence`; does not invent seismic resistance |
| Flood question from the browser | `9eff7323a7694fbf` | `supported`: the source explicitly says no flood test took place |

A note was created from r1 after the first answer. It was edited separately, and its test private marker was checked for absence from the prompts of all four initial questions. An intentionally incorrect manual note, “1400 кг — максимум” (“1400 kg is the maximum”), was then added to answer r2 while retaining the original quote. The follow-up pinned that exact r2. After its submission, parent r3 was created with different wording. Params and the actually transmitted context were checked: the follow-up continued r2, read the original, and rejected the incorrect note. Quote-verbatim checking alone does not validate every claim in a manually edited answer. This experiment does not hide that limitation.

The first four answers made eight real calls: SearchQueries and Answer for each step. The fifth question was submitted through the ordinary UI button and an independent worker. The browser was closed after submission, and the job completed successfully. Reopening showed the answer, the parent-revision reference, and an exact English quote. Switching the UI to English changed neither the Russian answer nor the original.

During browser verification, the note became r3 with a new title and personal comment. Origin still points to parent r1, while the original answer and previous note revisions remain. Repeated `note from-answer --revision 1` does not replace the author's text. Copying the closed workspace is checked together with all parent-revision and original references.

## Migration and automated checks

A closed copy of the real workspace from the previous M3 experiment was taken at schema 1: 10 sources, 23 fragments, 20 jobs, 20 drafts, 20 artifacts. Opening it with the new version produced schema 2. All these counts and original-file hashes matched. A note was successfully created in the new table. The original copy of the preceding experiment was not changed.

334 offline tests and Ruff check/format pass. New checks cover:

- concurrent migration, existing jobs/drafts, and transferring a closed project;
- note revisions, one winner during simultaneous edits, and preservation of the original version;
- repeated concurrent copying of an answer, immutable origin, and author edits;
- empty/foreign references and invalid note fields;
- inherited local provider/model/port/source scope without a hidden cloud switch;
- pinned parent revision, retrieval with history, originals instead of prior answers, and absence of personal notes from evidence;
- bounded history, explicit omitted count, and rejection of an unpinned/oversized revision;
- CLI/UI parity, languages, unsaved fields, conflict and reload, and display of context and original references.

AppTest found a UI-buffer persistence error: button session state cannot be assigned manually. Only fields/revisions/history selection are now persisted, and ordinary repeated reruns and language changes pass. CLI checks also found different ParameterSource enums in installed Typer and external Click. The public parameter-source name is checked, and errors use public `typer.BadParameter`. Explicit conflicting flags are actually rejected.

No new dependencies. The wheel was built, and its modules match the checked sources bit for bit. The package contains no materials, SQLite, or weights. A clean reinstall of the full environment and real Claude/Ollama runs are not claimed for this slice. This is a bounded follow-up, not unlimited chat memory. Misunderstanding and incorrectly grounding a conclusion in a correct quote remain possible. Five checked answers do not guarantee semantic correctness of every conversation.

Local artifacts are excluded from Git: `outputs/notes-and-followups/`. They retain the main, transferred, and migrated workspaces, `results.json`, `note.json`, `migration.json`, logs, raw JSON from control calls, and screenshots `note-ru.png` and `follow-up-en.png`. Git contains the implementation, tests, and this report.
