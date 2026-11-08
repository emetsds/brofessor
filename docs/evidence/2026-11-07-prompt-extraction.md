# Readable prompts and preservation of brofessor requests

Historical result. Support for earlier internal formats and profiles was cancelled on 08.11.2026 ([D034](../decision-log.md)). The mentioned archives, reference fixtures, and legacy adapters were removed. These instructions are not the current recovery path.

Historical report. Current requirements and boundaries are in the [specification](../specification.md). Decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state on the experiment date.

On 07.11.2026, stage 2 of the shared plan was completed: all authored instructions were extracted to `src/brofessor/prompts/`. The primary user entry point is the [prompt catalogue](../../src/brofessor/prompts/README.md). Wording quality was not edited during extraction.

## What users can access

**56 UTF-8 `.md` templates** are grouped into `common`, `navigation`, `reading`, `questions`, `reports`, `slides`, `podcasts`, `studies`, `books`, and `experiments`. They include the shared Codex/Claude/Ollama boundary, navigation-agent instructions, SDK tool description, explicit rereading/scope-narrowing hints, four report types, older reading/dialogue branches, translation, and terminology work. Four developer-experiment instructions are marked separately. They are not included in regular jobs.

Each `.md` file's text is an instruction or an explicitly identified component. The catalogue and `catalogue.json` provide purpose, input variables, shared parts, output schema, condition/version, and call site. Metadata does not enter model messages. Schemas, JSON serialization, budgets, source-data retrieval, validation, and length calculation remain in Python.

Commands `brofessor prompts list`, `show ID`, `preview ID`, and `preview --all` work without a model, network, or project. Preview shows substitutions, the component, and complete messages with the runner boundary: one stdin text for Codex/Claude and separate `system`/`user` messages for Ollama. JSON variables can be supplied, a provider selected, or a saved job's set chosen through `-w PATH ... --job ID`. In the last case, pinned instructions are shown with sample inputs. This does not replay earlier project materials. `show --job` outputs the exact saved template. Output identifies the actual editable-package path.

The loader uses the standard library: package resources, one-time named substitution, JSON, and contextvars. Template expressions and code are not executed. Unknown IDs/variables, missing files, and unfilled inputs produce a specific error before the corresponding inference. Literal JSON examples are allowed, and substitution-like strings inside source data are not interpreted again. The shared runner boundary counts toward the existing 8 MiB message limit.

No additional authored system/instruction prompts were found in speech adapters. They receive narration text and WAV-reference data with its transcript. User requests, materials, reference answers, standard SDK errors, and filesystem errors are data/contracts, not separate editable instructions.

## Preserving earlier and new jobs

New jobs from shared CLI/UI services receive `prompt_snapshot` in existing `params`: the applicable template family, full text, and SHA-256 for each template and the whole set. There is no new table, dependency, queue, or service. Set context spans the entire pipeline, including asyncio and runner/agent `to_thread`. A `.md` edit is visible to a new job, regeneration, and new child operations. Explicit retry and resume use the saved set. New checkpoint identity includes actual messages together with runner instructions.

An immutable `legacy.json` containing the exact extracted set was added for jobs without snapshots. The earlier checkpoint-key algorithm is preserved. The archive contains earlier reading/script variants. New Markdown edits do not change it. Its integrity and text are checked by hash and a historical synthetic reference fixture. Existing job rows are not rewritten. User revisions remain available.

Before the changes, source code, tests, and tools were saved in `/private/tmp/brofessor-prompts-2026-11-07/baseline`, without user materials or `.git`. Texts and substitutions were extracted from original expressions with order, spaces, separators, and serialization preserved. Every component was confirmed to match on synthetic inputs. Historical `tests/fixtures/prompts/README.md` (a historical fixture) protects the archive specifically, so ordinary editing of current `.md` files does not require rewriting that reference.

## Actual checks

| Check | Result |
|---|---|
| Initial text extraction | 256 passed, 16,03 s |
| Services and workflow after input pinning | 282 passed, 16,32 s |
| Intermediate full offline set | 743 passed, 57,68 s |
| After adding explicit navigation hints | 186 targeted checks, 10,73 s |
| Final full offline set | **747 passed, 54,95 s** |
| Ruff check/format and `git diff --check` | Passed |

New checks protect exact historical texts, one-time source-text insertion, literal JSON, unknown/missing templates, framing, and the complete input budget. Real application services checked: file changes between enqueue and execute; a new job and regeneration with a new set; explicit retry with the old set; repeating a term correction while current editing is invalid; runner-boundary hashing; rejection of a corrupted snapshot before inference; an earlier checkpoint after a controlled publication failure; and retaining the author's r2 on resume.

The wheel was built through standard `uv build --offline --wheel` and installed with the existing dependencies in a separate temporary Python 3.12.13 environment with UI. Outside the checkout, checks covered all `.md` files, the catalogue overview, catalogue data, archive, provider framing, and preview of each applicable frozen family. Imports come from `site-packages`, not the source checkout. An additional targeted installed-wheel run was **114 passed / 2,21 s**, including prompts, agent navigation, and pipeline.

A separate local check of the installed worker created two `ask` jobs in a synthetic workspace, before and after changing only the temporary installed template copy. Each `python -m brofessor.application.worker ... --once` run passed its own instructions through a real bounded subprocess/guardian to a **controlled synthetic executable** instead of a vendor CLI. Both jobs saved answers and completed as `succeeded`. Repeating an empty queue did not call the runner again. The original version did not receive new text. The new version received changes to the shared boundary and operation. Temporary templates were restored and processes terminated. QA: `/private/tmp/brofessor-prompts-2026-11-07/worker-check-tlip6hpl/`.

These are offline checks with a controlled external boundary. Real Codex/Claude/Ollama and TTS were not called in this stage. There is no new substantive answer acceptance, visual render acceptance, or listening acceptance. User materials, settings, authorization, and weights were unchanged. No commit, push, or publication was performed. Subsequent stabilization and earlier-job checking are recorded in the [named-value report](2026-11-07-named-values.md).
