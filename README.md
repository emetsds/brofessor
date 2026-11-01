# brofessor

**Your sources, explained.**

A local research workspace with equal CLI and Streamlit interfaces. Import sources, ask grounded questions, edit a podcast script or slide outline, then render local audio and editable PPTX. Books are the first workflow, not a restriction of the source model.

## Status

The first working implementation is available. It has PDF/EPUB/Markdown/TXT import, SQLite storage, an independent worker, cancellation/resume, editable draft revisions, citations, and Codex/Claude Code/Ollama adapters. Short Russian and English audio and actual PPTX have been generated. Full release acceptance is still in progress.

The measured checks and remaining work are in the [implementation plan](docs/implementation-plan.md) and [media experiment](docs/experiments/media.md). A declared adapter is not automatically a tested account/model combination.

## Install from source

Use Python 3.12, uv, Node.js 20+ and an official stable Codex or Claude Code CLI, or a local Ollama server. Local Qwen3 speech requires Apple Silicon. The reference Mac has 32 GB memory.

```sh
uv sync --locked --extra ui --extra speech
npm ci --ignore-scripts
export HF_HOME="$PWD/.models-cache"
uv run --extra ui --extra speech brofessor -w ./workspaces/demo ui
```

The app listens on `127.0.0.1`. In the UI, import a source, choose a focus and create a draft. Edit the draft, then use the audio/PPTX render button. The first speech run downloads the pinned public Qwen3-TTS model. Subsequent speech runs can use `HF_HUB_OFFLINE=1`.

For text and PPTX only, omit `--extra speech`. Existing agents can use the same CLI. There is no separate skill protocol or agent framework.

## CLI workflow

Commands print JSON. The `--workspace` option goes before the subcommand.

```sh
uv run brofessor -w ./workspaces/demo source add tests/fixtures/chapter.md
uv run brofessor -w ./workspaces/demo doctor --provider codex
uv run brofessor -w ./workspaces/demo ask "What was measured, and what remains unknown?" --wait
uv run brofessor -w ./workspaces/demo podcast --focus "Testing assumptions" --language ru --minutes 3 --wait
uv run brofessor -w ./workspaces/demo slides --focus "Lessons for a team lead" --count 4 --wait
uv run brofessor -w ./workspaces/demo job list
```

Use the returned draft job ID:

```sh
uv run brofessor -w ./workspaces/demo draft show JOB_ID
uv run --extra speech brofessor -w ./workspaces/demo draft render JOB_ID --wait
uv run brofessor -w ./workspaces/demo job show RENDER_JOB_ID
uv run brofessor -w ./workspaces/demo job cancel JOB_ID
uv run brofessor -w ./workspaces/demo job resume JOB_ID
```

`draft save JOB_ID edited.json EXPECTED_REVISION` accepts the draft's `data` object, validates it, and creates a new revision. A render uses the revision selected when it was submitted. Artifacts live in the workspace. Three-minute podcasts are previews; the intended full episodes are 20–60 minutes.

## Execution and data

CLI and UI call one Python service. A detached worker holds an OS lock, writes transactional job state to SQLite and checkpoints accepted model outputs/audio segments. Refreshing the browser does not restart a job. After a worker crash, running jobs become interrupted when the next worker starts and can be resumed explicitly. Files and closed SQLite storage can be copied together without an archive format.

Codex and Claude use their official CLI login. They send selected source text to their providers. brofessor does not extract subscription credentials or silently switch to API billing. If PATH points to the wrong executable, set `BROFESSOR_CODEX_BIN` or `BROFESSOR_CLAUDE_BIN` to the official stable executable. `doctor` reports missing tools/authentication without inference.

For Ollama, start the local server with `OLLAMA_NO_CLOUD=1` and select an installed model. The adapter requires the server's `/api/status` to confirm cloud is disabled, checks installed weights and rejects remote models/aliases. An older server without that capability fails explicitly before receiving source text. No automatic fallback is used.

## Current limits

- Long episodes, series planning and duration correction are not yet accepted. Audio reports measured duration and warns when it misses the target by more than 10%.
- Pronunciation and voice preference still need listening review. Speech supports two preset voices; reference recordings are not required.
- The editor currently exposes structured JSON. PPTX downloads work; portable slide-image previews are not implemented in the app.
- PDF needs a text layer. Failed/empty extraction is explicit. Source files are limited to 100 MiB.
- Search is lexical. Initial questions use the selected corpus, with chapter summaries for large inputs. Oversized synthesis fails explicitly instead of silently dropping text. Long-context and multilingual retrieval acceptance remains open.
- This is a local single-user app. No hosting, accounts, workspace archive format, Google Slides integration or speculative plugin system.

## Development

```sh
uv sync --locked --extra ui
npm ci --ignore-scripts
uv run --extra ui pytest -q
uv run ruff check .
uv run ruff format --check .
```

Offline tests use synthetic fixtures and fake model responses. Speech mocks test cancellation/checkpoints, not voice quality. Real CLI/model checks are documented separately and are not run by public CI. No Codex desktop bundled library is a product dependency.

Detailed planning is in Russian: [requirements](docs/requirements.md), [architecture](docs/architecture.md), [implementation plan](docs/implementation-plan.md), [technical evidence](docs/research.md). Coding agents should read [AGENTS.md](AGENTS.md).

Personal sources, outputs, credentials and model weights stay out of Git. The code license must be chosen before public distribution. No GitHub remote or publication has been created.
