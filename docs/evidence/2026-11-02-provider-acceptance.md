# M4 acceptance: integrations, installation, and project transfer

Historical report. Current requirements and boundaries are in the [specification](../specification.md). Decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state on the experiment date.

Checked 02.11.2026 on an Apple Silicon Mac with 32 GB memory. This is technical acceptance and checking of a small control material. Publication readiness of arbitrary scripts without an editor has not been established.

## The same scenario with real runners

The source is self-authored synthetic `tests/fixtures/chapter.md`, SHA-256 `114abedf32af830d4c691c8fcf43683043b8ee0aed49b3a09d8a06cf2a0922fe`. All three projects performed import, a Russian answer with exact original quotes, a follow-up question, saving the answer as a note and author editing of that note, three slides, PPTX, a one-minute script, and local two-voice narration after text review.

| Runner | Real setup | Result and limitations |
|---|---|---|
| Codex CLI 0.162.1 | Official stable CLI, existing ChatGPT subscription login, CLI default model | Answer, follow-up, slides/PPTX, and script created. An additional question about an absent carbon footprint was checked with the final prompt. The script was corrected and substantively expanded before re-narration. |
| Claude Code 2.1.185 | Official CLI, existing Claude subscription login, CLI default model | The same scenario and additional question completed. The script and notes were corrected for a claim that volunteers had successfully crossed, an inaccurate conclusion about increasing load, and language errors. |
| Ollama 0.40.6 | Already installed `qwen3.8:27b-q4_K_M`, digest `25b843619e944cd0…`, 17 741 872 132 bytes, context 32768 | Answer, follow-up, and PPTX obtained. The first podcast job timed out. The same job was explicitly resumed after changing thinking, and a script was obtained. Before narration, corrections addressed grammar, the Latin-script `fourth`, the distinction between calculated/measured load, and unsupported pedestrian-test success in notes. |

Codex used `--ignore-user-config`, disabled tools/web, and a read-only sandbox. Claude used `--safe-mode`, an empty tool set, disabled slash commands/MCP, and no persistent session. Neither `--bare`, persistent API billing, nor new authorization was used. Account files were not read, and tokens were not copied. Codex required an explicit `BROFESSOR_CODEX_BIN` pointing to the stable official binary: the first `codex` on PATH was another wrapper.

Failed local attempts were checked and retained:

- `qwen3:4b-instruct-2507-q4_K_M`, digest `0edcdef34593eac1…`, about 2,5 GB: quote objects inside `citations`, followed by concatenation of nonadjacent sentences. Validation rejected responses before saving. After clarifications, two answers passed. A long generation of three slides was cancelled.
- `qwen2.5:7b-instruct-q4_K_M`, digest `845dbda0ea48ed74…`, about 4,7 GB: initially added line numbers inside IDs. After clarification, IDs were correct, but slides and the script mixed Russian, English, and Chinese and included inaccurate conclusions. The structurally valid result was not accepted as usable content. Narration was not performed.

The two downloaded small models remain in the ordinary Ollama cache outside Git. Adapter success does not establish suitability of arbitrary installed weights. On this material, small models did not provide a reliable setup for a Russian script.

## Fixes resulting from the checks

The shared prompt explicitly distinguishes bare fragment IDs, locators, and verbatim quotes. Nonadjacent passages require separate quote objects. The language is spelled out and applies to headings, explanations, and dialogue. Strict reference and original-substring checks remain. Invented IDs/quotes are not corrected automatically.

The unknown-ID error now reports the count and correction method without copying arbitrary model text into the job error/log. This closes the observed case where a string containing quote text arrived instead of an ID. A regression test was added.

Ollama preflight uses `thinking.values` from `/api/show`. If the particular model explicitly permits boolean `false`, the request receives `think: false`, also visible in doctor. Missing metadata, string levels without `false`, or invalid values retain the model default. Neither model nor provider is substituted. The installed 27B default was `medium`, with `false` supported. After the change, the previously non-completing script was obtained. This selects a mode for a bounded text task, not proof of retained quality on every task. Basis: [thinking documentation](https://docs.ollama.com/capabilities/thinking), [Chat API](https://docs.ollama.com/api/chat).

## Local files and blocked external networking

The user's existing Ollama on 11434 was unchanged: it reported cloud enabled and was rejected by brofessor's check. The experiment used a separate server on a random loopback port with `OLLAMA_NO_CLOUD=1`, context 32768, q8 KV cache, and one concurrently loaded instance. `/api/status` confirmed cloud disabled, and `/api/ps` confirmed context and local model loading. Official settings: [Ollama FAQ](https://docs.ollama.com/faq).

After downloading dependencies/weights, both the brofessor client and separate Ollama server ran under a temporary macOS `sandbox-exec` profile: only localhost was allowed, with other network connections blocked by the OS. A control connection to an external address received EPERM/EACCES, while local status continued to work. Local 27B generation, PPTX assembly, Silero, and full MP3 decoding ran in this profile. For the client process, Codex/Claude binaries pointed to nonexistent paths. TTS used installed weights and offline Hub variables. No hidden cloud/API fallback was used.

The profile is a temporary QA tool, not a product dependency. System settings, user servers, and the UI on 8501 were unchanged. This checks the selected setup, not a sandbox for an arbitrary user application or a promise that all other Mac processes are inactive.

| Result after editorial review | MP3, 60 s target | Check |
|---|---:|---|
| Codex → Silero | 61,15 s | Two fixed voices, full decoding |
| Claude → Silero | 60,05 s | Two fixed voices, full decoding |
| Ollama 27B → Silero | 62,50 s | Two fixed voices, full decoding |

Silero CIS Base: pinned revision `ba41b18f6a707ad93605a162998865e7c087153d2e010a26dd02229dab0e672a`, Torch 2.15.0, CPU, voices `ru_roman` and `ru_zhadyra`. The first short Codex render produced 43,14 s and an explicit duration warning. After adding missing source details, a new revision and separate render were saved. All earlier drafts/files were retained. New one-minute checks do not replace [the four long RU/EN M2 cases](2026-11-01-long-podcasts.md) or listening acceptance.

Nine pages from three PPTX files were converted to PDF/PNG and viewed visually: text was readable, no overlaps or clipping were found, and notes contained original IDs and locators. In one original Codex bullet, the thousands separator allows wrapping between `1` and `200`. This is a visible typographic limitation of the current markup, not loss of the number. Native-object editability was checked earlier in [PPTX acceptance](2026-11-02-pptx.md). Conversion used isolated temporary LibreOfficeDev 26.8.0.0.alpha0 and Poppler from the agent environment. They are not part of the application/installation/CI. PowerPoint and Google Slides were not opened in this run.

## CLI/UI and independent job lifetime

The shared-operation matrix is checked by `test_interfaces`, `test_note_interfaces`, `test_ui_language`, `test_projects`, `test_series`, `test_workspace`, and `test_worker`: projects, import/originals, search/answers/follow-up, notes/draft revisions, models/ports/voices, series, rendering, artifacts, conflicts, and concurrent operations. Real long media and editing were checked in M2/M3 reports. All weights and scripts were not generated again for M4.

A separate Streamlit instance on a temporary port with a separate settings file checked project selection outside the application, local provider/model/port, submitting a question, and resubmitting the same form with the same job ID. CLI cancellation appeared in the UI as Cancelled. Explicit Resume and reload preserved the job and parameters. A failed small-model answer was shown as an error, with no draft published. A finished Codex MP3 from a CLI project is visible with voice model, coverage, player, and actual 1:01 against a 1:00 target. The file was actually downloaded through the browser, rather than merely displaying a button.

A real Ollama job was checked with a separate large synthetic source: CLI cancelled running generation, and no unfinished draft existed. After explicit resume, a search checkpoint was saved. Our worker was forcibly terminated with SIGKILL. A new worker marked the job interrupted, and the UI showed Resume. Resuming from the UI, refresh, and closing the temporary tab did not stop the work: CLI subsequently observed succeeded. The search checkpoint's SHA-256 was preserved. After it, the server recorded only one successful `/api/chat` for the answer, without repeated model search. Checkpoint mtime updates on revalidation and alone is therefore not evidence of repeat generation. The local setup and job parameters survived reload with the sidebar default `codex`.

## Installation, license, and project preservation

A separate Python 3.12.13 environment was created from a shared repository clone using `uv sync --locked --python … --extra ui`. It does not use packages from the original dev-venv. An independent core+UI-only environment and installing the `silero` extra with real narration were also checked. After dependencies had downloaded, the new core+UI environment was reinstalled from cache without networking. F5 and MLX extras were not reinstalled in the new M4 environments. Their earlier checks remain in their own reports.

The final wheel was installed in a third separate environment with exact dependencies exported from the lock. Installing wheel dependencies required PyPI registry metadata. Offline runtime was checked separately. Every wheel module matches the final source bit-for-bit. It contains MIT LICENSE and `License-Expression: MIT`, with no materials, SQLite, audio, or weights.

A closed Codex workspace containing answers, note edits, script revisions, PPTX, and audio was copied and its directory renamed. All 38 files retained SHA-256. Sources, jobs, drafts, notes, and relative artifact paths matched. SQLite integrity_check returned `ok`. The installed wheel opened the transferred project and built a new PPTX from another working directory with an empty PATH and external networking blocked. Old absolute paths in diagnostic audio metadata record the original execution. The UI uses the registered relative artifact path.

At the user's choice, an MIT license was added for source code and package metadata. It does not cover third-party weights, dependencies, or materials. Publication, push, and remote creation were not performed.

## Acceptance boundaries

A clean core+UI environment passes 340 offline tests, Ruff check/format, and `uv lock --check --offline`. Contract checks use substituted responses rather than subscriptions or weights. The first cold AppTest run exceeded the old 10 s limit, while a repeat took about a second. The UI-test allowance was increased to 30 s. One functional subprocess test with a 2 s limit timed out under heavy local load. An isolated repeat and the final complete run passed without changing that limit. These allowances did not change product behavior. CI uses Python 3.12 and DejaVu font installation. Remote GitHub Actions was not run.

The short corpus does not establish whole-book local-processing quality. Every runner's raw drafts needed editing. The local script required substantial rewriting. The proposed limit of at most 5% correctable turns was not confirmed in this short case. Fully accepted generation without an editor is not claimed, and the existence of a quote does not replace fact checking.

Technical operation does not establish script or speech quality. Later substantive checks are described in the [long Qwen check](2026-11-03-qwen-long-dialogues.md). Full personal listening acceptance was subsequently cancelled under D027.

Acceptance artifacts are outside Git in `outputs/v1-acceptance/`: projects and versions, raw JSON of synthetic answers, results/logs, MP3/PPTX, PDF/PNG, and the UI screenshot. Binaries, environments, and weights are not copied into that directory.
