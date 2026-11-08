# Initial technical research and first working slice

Historical information from 01.11.2026, carried over from the research. Links and vendor capabilities were not rechecked here during the reorganization on 07.11.2026. The current architecture is in the [specification](../specification.md#architecture).

Checked 01.11.2026. `read_scope`: targeted sections of official documentation, READMEs/model cards, and help from installed CLIs. Vendor repositories were not audited in full. The initial research did not include model calls, weight downloads, authorization, or audio/slide generation. Subsequent real checks are recorded separately in `evidence/`; this overview does not establish that integrations work.

## Local starting point

The pilot's target setup was Apple M4 with 32 GB unified memory. The initial inventory on 01.11.2026 found Codex CLI 0.162.1, Claude Code 2.1.185, Ollama client 0.40.6, uv 0.11.7, Node 26.0.0, and system Python 3.9.6. This is a historical environment snapshot, not a list of mandatory dependencies. At the time, `ollama --version` reported that it could not connect to a running instance. This does not establish that no service existed outside the accessible environment.

The presence of binaries does not establish a Claude subscription, model availability, sufficient quotas, or a working pipeline. An isolated Python 3.12 environment with uv was selected for development. At the user's request, PPTX rendering was being moved to `python-pptx>=1.0.2,<2`, eliminating the separate JavaScript environment. Global settings and installed software were not changed during the initial inventory.

## Primary sources

| Source | Information at the time of research |
|---|---|
| [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode) | `codex exec`, JSON events, final structured output, and reuse of CLI auth. This supports a bounded runner, not transmission of subscription tokens to a third-party backend |
| [Codex authentication](https://learn.chatgpt.com/docs/auth) | Subscription login and API keys are separate access and usage-accounting paths |
| [Claude Code headless](https://code.claude.com/docs/en/headless) | `claude -p` and structured output. `--bare` does not read subscription OAuth/Keychain credentials. Local `claude --help` also confirmed this |
| [Claude CLI reference](https://code.claude.com/docs/en/cli-reference) | `--safe-mode` disables user extensions while retaining ordinary authorization. Together with restricted tools, it is a runner candidate. The exact combination of flags requires a smoke test |
| [Claude authentication](https://code.claude.com/docs/en/authentication) | The user's existing authorization determines the access mode. ChatGPT Pro does not provide Claude access |
| [Claude subscription usage](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) | The documentation at the time described subscription use of Claude Code/Agent SDK within plan limits. The actual account and launch method still require verification |
| [Claude API key precedence](https://support.claude.com/en/articles/12304248-manage-api-key-environment-variables-in-claude-code) | An API key can change expense accounting. The runner must not silently switch a subscription profile to API access |
| [Claude credential boundaries](https://code.claude.com/docs/en/legal-and-compliance) | An official user CLI and collection/proxying of OAuth credentials by a third-party product are different integration methods |
| [Ollama chat](https://docs.ollama.com/api/chat) and [structured outputs](https://docs.ollama.com/capabilities/structured-outputs) | The local chat API accepts JSON schema. A correct schema does not guarantee factual grounding |
| [Ollama local-only](https://docs.ollama.com/faq) | `OLLAMA_NO_CLOUD=1` is available. A local-only profile must check the actual service configuration, not just a localhost URL |
| [Ollama compatibility](https://docs.ollama.com/api/openai-compatibility) | A subset of the API is supported. Other compatible endpoints are checked by capability |
| [Streamlit Session State](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state) | State is tied to the browser session. Durable workspace/job state must live outside it |
| [Streamlit threading](https://docs.streamlit.io/develop/concepts/design/multithreading) | Custom threads have restrictions, while fragments allow periodic updates. A separate process was chosen for long-running work |
| [Streamlit uploader](https://docs.streamlit.io/develop/api-reference/widgets/st.file_uploader) and [audio](https://docs.streamlit.io/develop/api-reference/media/st.audio) | Source uploads and audio playback are available. Browser filenames cannot be used directly as paths |
| [pypdf extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) | PDF does not provide reliable semantic structure. Scans and complex layouts need separate handling |
| [EPUB spine](https://www.w3.org/TR/epub-33/#sec-spine-elem) | Reading order comes from the spine, not file sorting |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | RU/EN and voice control are supported. Documentation does not establish the quality of an hour-long Russian podcast on the target Mac |
| [Chatterbox](https://github.com/resemble-ai/chatterbox) and [MLX-Audio](https://github.com/Blaizzy/mlx-audio) | An alternative multilingual TTS and an Apple Silicon runtime. Specific weights, versions, and licenses are pinned in the pilot |
| [python-pptx](https://python-pptx.readthedocs.io/en/latest/) and [speaker notes](https://python-pptx.readthedocs.io/en/latest/user/notes.html) | Creates editable text, tables, and shapes in PPTX. The notes API can read and modify speaker notes. The library runs in Python without installed PowerPoint. Visual quality and editability of a particular file require checking |
| [Google Office compatibility](https://support.google.com/docs/answer/6055139?hl=en) | PPTX can be opened/converted in Slides, but embedded charts may become images |
| [Google Drive conversion](https://developers.google.com/workspace/drive/api/guides/manage-uploads#convert_a_file_to_a_different_type) | Programmatic PowerPoint-to-Google Slides conversion is available through a separately authorized API |
| [Pro API credits](https://developers.openai.com/api/docs/guides/chatgpt-api-credits) | Documentation describes separate activation of included credits for eligible Pro subscriptions. This was not checked in the owner's account and is therefore not a mandatory dependency |

## First working slice

Checked 01.11.2026 on Apple M4 / 32 GB. Only the self-authored synthetic chapter `tests/fixtures/chapter.md` was used. No real user books or paid APIs were used.

After this run, the PPTX renderer was replaced with `python-pptx` and Node/npm dependencies were removed. [Verification of the new implementation](2026-11-02-pptx.md#replacing-the-node-renderer) was recorded separately. The first slice's history is retained below.

### Completed

- The official Codex CLI 0.162.1 with ChatGPT login created an answer, a Russian two-voice script, and a four-slide outline from the chapter. Every reference resolves to the saved original chapter.
- Another real call after process-management changes answered that no carbon-footprint data was available. It saved `evidence_status=insufficient_evidence` and stated that the example was fictional.
- PptxGenJS rendered the outline as PPTX. Four pages were inspected after QA conversion: text was neither cut off nor overlapping, and notes and references were present. QA used available LibreOffice; the product does not depend on it.
- A real browser checked sources, job statuses, the editor, and saving a user's slide-title edit. The UI showed the new revision2 and downloadable draft-r2.json. AppTest separately checks retention of unsaved text during concurrent CLI editing.
- The first 398-word script produced 314.97 s of audio in 106.38 s of local synthesis. For a 180 s request, the application correctly reported a mismatch instead of presenting an estimate as measured time.
- After calibration, the script was shortened to 260 words. One turn reached the generation limit. The job failed and the unfinished segment was not published. An edit through the shared service split the turn while preserving text and references. Rebuilding reused four segments and created five new ones: 203.2 s of audio in 35.304 s.
- Cancellation, timeout, and forced worker termination were checked on self-owned test processes. A separate short-lived watcher terminates the CLI-owned process group when the worker dies, without attempting to kill saved PIDs. Job completion transactionally accounts for concurrent cancellation.

### Integrations

| Runner | Actual status |
|---|---|
| Codex | Offline contract tests and real generation through the subscription completed |
| Claude Code | Offline contract tests and the presence of subscription authorization checked; real generation not yet checked |
| Ollama | Offline HTTP contract tests completed. The server was not running during this run, so a real local text model was not checked |
| Qwen3-TTS / MLX | Real RU/EN samples, local assembly, decoding, and resume completed. See the separate media.md |

A broken Codex wrapper appeared first on PATH on the target Mac. Verification used the installed stable binary through `BROFESSOR_CODEX_BIN`. Global PATH was unchanged. Weights and dependencies were installed outside Git, without user secrets.

### Result boundaries

Technical checks do not establish stress placement or voice quality. Even after calibration, 203.2 s exceeded the 180 s request by 12.89%, and the warning remained visible. This first slice did not check a large book, series, or long episodes. Subsequent [whole-EPUB checks](2026-11-01-whole-book.md) and [duration checks](2026-11-01-long-podcasts.md) are described separately.

The first slice provided only a structured JSON editor. It did not include notes, follow-ups, or the full runner matrix. Later checks of those capabilities are in their corresponding reports. UI slide previews remain outside current scope.
