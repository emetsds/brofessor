# Organizing brofessor code by responsibility

Historical report. Current requirements and boundaries are in the [specification](../specification.md); decisions and cancellations are in the [Decision log](../decision-log.md). References to later stages describe the state at the time of the experiment.

On 07.11.2026, the first stage of the new plan was completed: the previously flat package was grouped into interfaces, shared operations, domain features, and infrastructure. The `brofessor` command, workspaces, and job processing were preserved. This slice preceded prompt extraction and stabilization; their later completion is recorded separately.

## Actual structure

| Package | Responsibility |
|---|---|
| `interfaces/cli` | Typer assembly and separate command groups; shared options, output, and job waiting in `common.py` |
| `interfaces/web` | Streamlit startup; screens in `pages`, dialogs in `dialogs`, shared editors/navigation/progress in `components`, JS in `assets` |
| `application` | Shared services, pipeline, worker, tasks, projects, progress, initial narration, and maintenance |
| `features/sources` | Collections, reading, and navigation of originals |
| `features/books` | Translation, terminology, and audiobooks |
| `features/podcasts` | Script writer, source-backed writer, series, and checking |
| `features/questions.py`, `reports.py`, `studies.py` | Answers, written reports, and understanding checks |
| `infrastructure/storage` | SQLite workspace, preferences, and OS-locks |
| `infrastructure/text`, `agents` | Three bounded runners, guardian, and the existing Pydantic AI adapter |
| `infrastructure/speech` | Engines, catalogue, references, and Russian speech preparation |
| `infrastructure/formats` | Source import, EPUB/PDF/PPTX, audio assembly, and fonts |
| `models.py` | Shared Pydantic contracts |

52 source modules were moved; large CLI/UI modules were then split along existing responsibilities. `WebContext` explicitly passes the project, translator, and callbacks to screens; screen modules contain no global mutable workspace. Business operations remain in shared services.

Tests are grouped into `tests/application`, `features`, `infrastructure`, and `interfaces`. All previous test functions were retained. Shared synthetic EPUB/PDF builders, fake models, and UI actions were moved to `tests/helpers`. Imports from other `test_*.py` files and `sys.path` insertions are gone. Fixtures and provenance are preserved. Developer tools run from the root as `python -m tools.<module>`; the README provides an example.

## Entry points and resources

- CLI: `brofessor.interfaces.cli.app:app`; the local editable installation was updated.
- UI: installed resource `brofessor/interfaces/web/app.py`, held through `importlib.resources.as_file` while Streamlit runs.
- Worker: `python -m brofessor.application.worker`.
- Guardian: `python -m brofessor.infrastructure.text._runner_guardian`.
- JS, `speech_models.json`, and DejaVu Sans are read through `importlib.resources`; wheel inclusion was checked. Licenses and provenance references were updated.

Old internal Python paths were updated in code, tests, and tools; there are no forwarding modules. External Python clients that imported previous internal modules must use the new paths. CLI commands are preserved.

## Checks and results

Before the move, the current working snapshot was saved in `/private/tmp/brofessor-reorg-2026-11-07/baseline`, without user materials or `.git`. It includes already existing uncommitted changes and is the baseline for checking the reorganization.

| Check | Result |
|---|---|
| Original full offline suite | 674 passed, 81.76 s |
| Infrastructure | 184 passed; an old import was found in an embedded test subprocess, fixed, then rechecked with worker/storage/PDF: 37 passed |
| Domain workflows | 122 passed, 10.77 s |
| Application | 91 passed, 3.08 s |
| Interfaces after path changes | 88 passed, 46.38 s |
| Screen scenarios after UI splitting | 68 passed, 22.33 s; an intermediate navigation-key error was fixed |
| Full suite after test grouping | 674 passed, 54.40 s |
| Installed wheel outside checkout | 141 passed, 31.24 s: worker/recovery, guardian/process cleanup, EPUB/PDF, CLI wait, UI/navigation, and notes |
| Static checks | Ruff check, format, and `git diff --check` passed |

AST comparison against the initial snapshot showed changes limited to imports and launch paths in 38 domain/application/infrastructure modules. Two more modules received explicit speech-catalogue/font loading as package resources. UI strings are preserved; only the resource name `ui.py` was replaced with `app.py` in the CLI. JS, fonts, and the speech catalogue are byte-identical. Prompts and their assembly were not edited; SQLite schema, job kinds, request keys, and checkpoint contracts were preserved.

The wheel was built with ordinary `uv build --offline --wheel`. It was installed into a new temporary Python 3.12.13 environment with UI and dependency versions from the working environment. The initial offline installation stopped because registry metadata for `pydantic-ai-slim` was missing; ordinary installation of the pinned current versions succeeded, downloading public packages. Models and weights were not downloaded. Imports were checked from the temporary environment's `site-packages`; four JS resources are readable, the speech catalogue loads, and four font styles are registered.

A separate real local check queued a synthetic saved slide render from a creator process that then exited. The independent worker from the installed wheel built a PPTX; its text was read through python-pptx, and the public CLI returned `succeeded`. Direct `python -m ...worker --once` was also checked. The temporary worker was stopped. This confirms startup and input/output preservation after moving; PPTX appearance did not undergo repeated visual acceptance.

All checks used synthetic materials and substituted expensive text boundaries. Real Codex/Claude/Ollama and TTS were not called in this stage; new checks of them belong to later stabilization. User data, settings, authorization, and weights were unchanged. No commit, push, or publication was performed.
