# Source navigation through Pydantic AI

Historical report. Current requirements and boundaries are in the [specification](../specification.md). Decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state on the experiment date.

05.11.2026. After comparison with the working controller, the agent loop was moved to stable `pydantic-ai-slim==2.66.0`. At the user's later explicit direction, the old controller was removed completely. Pydantic is used for every task, including resume. Document operations, originals, citations, worker, SQLite, and model checkpoints remain in brofessor. This replaces the directory-navigation loop rather than rewriting fixed translation, narration, and rendering workflows.

## Implementation and choice

`navigation_harness.py` creates a real `pydantic_ai.Agent` with typed `retrieve` tool and `NavigationStep` output. The SDK performs the call loop, argument validation, and bounded retries. The application checks completion: search previews are not treated as read originals, and full coverage is allowed only after checking every extractable fragment in the scope. A final call cannot be combined with reading in the same model response: the whole package is rejected before execution and checkpoint saving, and resume can receive a corrected response. `NavigationSession` owns document operations for the single runtime.

`NavigationModel` implements the public `Model` contract through existing Codex/Claude/Ollama adapters. The model returns one `NavigationStep`, which the bridge passes to the SDK as a single `retrieve` call or final result. A structurally invalid step is rejected before caching and execution. General-purpose `RunnerCall`/`RunnerTurn` and JSON arguments inside a string were removed after the KISS audit. Built-in Pydantic AI OAuth providers and provider SDK extras are not used. Official CLIs continue to own subscription authorization. There is no reading of `auth.json`, token broker, API fallback, or new application server/queue. Alpha `pydantic-ai-harness` was not added.

The old controller, version-based runtime selection, and compatibility with earlier continuation formats were removed at the user's direction. Initial restoration of legacy memory/observations and special handling of the old version field in request keys were also removed. The current Pydantic loop resumes through its own checkpoints, and completed navigation is reused. There is no separate migration layer or runtime switch.

History is limited to the original task and the last two complete call/result pairs. Transport timestamps/run IDs do not participate in request identity. Tool-call IDs derive from the complete prompt. Initial context is pinned once. A tool result and observation are saved atomically, so a loop repeated after failure takes accepted model responses and tool results from checkpoints. The overall deadline is 600 s, with the remainder passed to each runner. The SDK limit is 24 model requests, and each request produces one call. Existing document and source-text budgets are retained. The existing bounded runner does not measure tokens/cost, and these values are not represented as zero.

The first comparison did not confirm reduced custom code or a speed improvement. A subsequent KISS audit reduced the Pydantic bridge itself from 212 to 163 lines by removing the generic protocol and an unused history copy. This compares two bridge implementations, not a library benchmark against the original controller. Document operations and recovery are still needed. Fixed application workflows were not moved into the SDK.

## Environment and material provenance

Python **3.12.13**, Pydantic **2.14.2**, Pydantic AI Slim / Graph **2.66.0**. Installation and dependency resolution were actually performed through uv, with the version pinned in `pyproject.toml` and `uv.lock`. [Stable package](https://pypi.org/project/pydantic-ai-slim/2.66.0/), [public Model interface](https://pydantic.dev/docs/ai/models/overview/#custom-models), [version policy](https://pydantic.dev/docs/ai/project/version-policy/).

Installed distribution metadata licenses were checked: MIT for Pydantic AI Slim, Pydantic Graph, genai-prices, logfire-api, and truststore; ISC for griffelib; BSD-3-Clause for httpx2/httpcore2. Packages were installed unchanged, with notices retained in their distributions. Attribution was added to `THIRD_PARTY_NOTICES.md`. No upstream code was copied.

The eight synthetic MIT notes from `tools/probe_collection_navigation.py` were used: an index, project River, current/previous runs, learning files, and irrelevant files. The personal vault was not used. QA data, full responses, checkpoints, SDK history, and the ledger are only in ignored `outputs/harness-probe-2026-11-05/`. File hashes before and after all completed runs matched.

## Real checks

| Check | Job | Time | Real calls | Result |
|---|---|---:|---:|---|
| Earlier controller / Codex | `a7742351ae724887` | 41,520 s | 3 navigation + 1 Answer | Correct answer, 3 originals read, exact quotes |
| First Pydantic experiment / Codex | `14643d6c66aa484b` | 55,980 s | 4 navigation + 1 Answer | Same meaning and sources. The model corrected two paths missing `.md` |
| Pydantic / cancellation, SIGKILL, and resume | `8d7a23040ba24d23` | 26,072 s on last resume | 3 navigation + 1 Answer total | First step cancelled after saving. The next saved step survived worker SIGKILL. Task completed without repeating accepted calls |
| Pydantic / full reading of Trials / Codex | `55f8506411314d0b` | 47,253 s | 3 navigation + 1 Answer | Verified coverage of 2 documents / 2 fragments, correct comparison and limitations |
| First Pydantic experiment / Ollama | `144d792761b045dd` | 178,699 s | 3 navigation | Not accepted for content: the model finished after search without reading originals. The application returned insufficient_evidence |
| Next Pydantic experiment / Ollama | `780679f8e93c4fe6` | 303,969 s | 4 navigation + 1 Answer | 3 originals read, correct answer, and 6 exact quotes |

These initial observations preceded simplification of the protocol to one `NavigationStep`. Navigation paths and model-cache state differ. There is no statistical benchmark. The current-protocol check is recorded separately below.

Codex is stable CLI **0.162.1**, `gpt-6.1-sol`, official ChatGPT subscription. The runner reported reasoning effort `none`. Every final-answer claim was checked against originals: 12 ms now, 35 ms previously, 48 requests/one node, no cluster guarantee, and untested power loss. Full-read separately retained host-verified coverage, correctly identified unknown southern-run conditions, and explicitly distinguished the calculated 23 ms difference from the original values.

In the recovery run, marker `fault-cancel.json` records 1 accepted call / 1 step, and `fault-kill.json` records 2 calls / 2 steps. After recovery, the ledger contains **4 calls with 4 distinct prompt SHA-256 hashes**. Total call time is **45,404 s**, not overall wall time including stops between runs. SIGKILL was applied only to this synthetic experiment's process after step saving. Cancellation published no draft, the OS-lock was released, and saved work was reused on resume.

Ollama **0.40.6**, already installed `qwen3.8:27b-q4_K_M`, digest `25b843619e944cd0ae6069f94ff4e5e26a16e109ccbc0a66a0f05979ed70098e`, `think=false`. The user's server reported cloud features enabled and was not used for source transfer. The check started separate temporary `127.0.0.1:11436` with `OLLAMA_NO_CLOUD=1`, context 32768, and one parallel request. Cloud disabling was confirmed before synthetic-text transfer. Weights were not downloaded, and the persistent server was not reconfigured. At completion, the model was unloaded, the temporary server stopped, and the port freed.

The first Ollama run exposed premature finish. A check for candidates without an attempted read was added. Its rejection and subsequent correction were tested offline. In the next real run, the model read originals and prepared a correct answer. One repeat does not establish model robustness or a causal effect of this check: in the second run, the model itself selected read before finish.

Claude Code **2.1.317** was found, but its standard authorization check exits with code 1. The actual cause is unestablished. Real Claude navigation was not checked, no subscription was purchased, and credentials were not read. Offline forwarding of the selected Claude runner is covered by the same contract as Codex/Ollama.

Reproduction:

```sh
uv run --no-sync python tools/probe_collection_navigation.py --output outputs/my-pydantic-check --provider codex --model MODEL
uv run --no-sync python tools/probe_collection_navigation.py --output outputs/my-recovery-check --provider codex --model MODEL --fault-after-tool cancel
uv run --no-sync python tools/probe_collection_navigation.py --output outputs/my-recovery-check --provider codex --model MODEL --fault-after-tool kill
uv run --no-sync python tools/probe_collection_navigation.py --output outputs/my-recovery-check --provider codex --model MODEL
```

The last three commands operate on one job. The `--harness` switch was removed. The original comparison with the old controller above is retained as history. An installed local server supports `--provider ollama --model INSTALLED_MODEL --ollama-address IP:PORT`. Cloud must be disabled by the server itself.

## KISS audit and current-protocol check

At the user's request, an independent subagent audit and another review of the fixes were performed. Removed items were the generic call package, JSON serialization inside a string, unused full history `pydantic-run.json`, legacy memory/initial observations, and special request-key compatibility with the earlier version. One `NavigationStep` is sufficient for one model response. A separate SDK call-count limit was removed because every model request produces exactly one call. Navigation-step, context, and source-fragment limits remain for current tasks and recovery.

The bridge itself decreased from **212 to 163 lines**. The shared external-runner fake and synthetic directory were extracted into `tests/collection_helpers.py`. Navigation/collection check count decreased from **42 to 30**. Useful protection from removed duplicates remains here:

| Removed checks | Where the behavior remains |
|---|---|
| Repeated provider × 3, separate CLI/UI scenarios | `test_collections.py`: three runners, exact quotes, CLI execution and a Streamlit task with result checking |
| Repeated author failure and direct cancel | Collections checks directory removal after author failure. The harness checks cancellation through the real worker and resume |
| Repeated request budget | `test_full_reading_cannot_finish_with_unread_originals` checks SDK request limit and absence of a partial draft |
| Old runtime markers, seeded legacy context, and SDK history file | The corresponding mechanisms were removed. Invalid typed actions and finish combined with read are rejected without execution or cache poisoning |

Recovery was checked after the first and fourth retrieval. The second case replays an accepted request after history contraction, preserving accepted steps and uniqueness of external prompts. Pinning `harness_input`, stable tool-call IDs, atomic tool results, and saved originals remain necessary current-resume contracts.

Real current-protocol check through official Codex CLI 0.162.1 / `gpt-6.1-sol`: job **`e58078f8d63b47e8`**, **44,437 s**, **3 NavigationStep + 1 Answer**. River, North, and South were read. The answer correctly distinguishes 12 and 35 ms, names 48 requests/one node, and identifies untested power loss. Seven exact quotes were checked against three originals, and all eight files remained unchanged. Data and ledger are in ignored `outputs/harness-kiss-2026-11-05/codex/`. This is a one-request smoke check, with no statistical speed comparison. The new format was actually checked through Codex. Ollama was not rerun after simplification. Claude still failed standard authorization.

## Offline checks and boundaries

`tests/test_navigation_harness.py` and `tests/test_collections.py` use the real SDK, replacing only the external runner. Checks remain for selected connections, search/links, exact quotes, original versions, paths/symlinks, formats, full coverage, budgets, recovery, and CLI/UI parity. Correctable premature completion is checked through the SDK's real ModelRetry. A structurally invalid step fails validation, and resume can receive a corrected response. Compatibility with the old controller and its formats is no longer checked.

The full run after cleanup was **595 passed**. The targeted set was **30 passed**. Ruff check/format and `git diff --check` passed. The wheel was built offline. Normal installation uses pinned `pydantic-ai-slim==2.66.0` without the Codex desktop runtime or a separate experimental group. The preceding 607-check set contained removed duplicates and compatibility checks.

New browser/visual PPTX acceptance, listening, the personal vault, and large directories were not checked. Form UI and renderers were unchanged. Retained history does not make a directory an atomic disk snapshot. The library does not guarantee relevance-search completeness, semantic correctness, or robustness of every local model.

## Earlier custom controller

05.11.2026. This report records initial directory registration by a single path and original selection through custom controller version 1. It used the existing Python core, bounded text adapters, SQLite, OS-locked worker, and checkpoints. Pi and a new agent framework were not installed in this experiment. The Pydantic AI Slim experiment had not yet been performed. Subsequent [checking and loop replacement with Pydantic AI](2026-11-05-source-navigation.md) are described separately. Results below apply to the original controller and are retained as its history.

### User workflow

In Sources → Add materials, enter a document-directory or vault path and connect it. Alternatively, use `brofessor source add /path/to/vault`. Connection saves a path/ID, without traversing files, extracting text, or calling a model. The collection is selected by default on a new task. The user supplies a prompt and output format. For example: “Найди результаты текущего эксперимента River, условия и ограничения; отличи предыдущий прогон” (Find the current River experiment's results, conditions, and limitations, distinguishing the earlier run). Files need not be selected manually.

During a task, the model selects structured actions: overview, local BM25 search, source-fragment reading, outgoing/back links, and finish. The application executes them within selected roots. Supported formats are UTF-8 Markdown/TXT, text-layer PDF, and EPUB supported by the existing importer. Obsidian support adds wiki links, inline relative Markdown links, headings, block references, aliases, tags, and backlinks. An ambiguous link is not silently resolved.

Navigation history, selected paths, and originals are available in task details and through `job sources JOB_ID`. Saved quotes/rendering work after directory modification, relocation, and disconnection. A new run traverses current documents. The file inventory is pinned at task startup, and each file's bytes at first access. This is not an overall atomic disk snapshot.

### Real checks

All materials are synthetic MIT content defined in `tools/probe_collection_navigation.py`: 8 notes with an index, current/earlier experiments, headings/links, and irrelevant documents. The user's real vault was not used. All QA files, full responses, ledger, snapshots, and checkpoints are in ignored `outputs/collection-navigation-2026-11-05/`.

Runner: stable Codex CLI **0.162.1**, **gpt-6.1-sol**, official user authorization. Subscription credentials were not read, and there was no API-billing switch. The ledger records reported model and individual-call times. The runner reported reasoning effort `none`. Times below are local observations of one task, not a benchmark.

| Check | Job | Time | Calls | Observed result |
|---|---|---:|---:|---|
| Answer about the current experiment | `c67ddf42cce640ba` | 45,632 s | 3 navigation + 1 Answer | Read 3 originals. Correctly distinguished 12 ms now from 35 ms previously, 48 requests/one node, absence of a cluster guarantee, and untested power loss |
| Three slides for the same question | `4f92df52a29d406a` | 55,860 s | 4 navigation + 1 Slides | Current result, conditions/limitations, earlier/current table, 3 original documents |
| First full reading of Trials | `b6460846569e4048` | 45,463 s | 3 navigation + 1 Answer | Both documents were read and host-verified, but the author did not receive coverage confirmation and incorrectly retained uncertainty about completeness |
| Full reading after the fix | `82490de0388b4428` | 45,015 s | 3 navigation + 1 Answer | Correctly stated coverage of 2 documents / 2 fragments, 12/35 ms and limitations, with 5 exact quotes |

A total of **17** runner calls. For slides, the model first tried reading two wiki paths without `.md`, received clear errors, and corrected the paths on the next step. There were no new calls outside the standard loop. The model did not select real `links/backlinks` in these tasks. Their behavior was checked offline.

Every claim in finished control answers and slides was compared with originals. The final full-read answer is source-supported, and southern-run conditions were not invented. In the first answer version, raw citation IDs appeared in prose. The prompt was corrected, and the new full-read outputs normal text and separate citations/quotes. The first full-read also interpreted South's wording too literally as a mention of another earlier experiment. The final run presents the historical result correctly. These observations do not guarantee semantic accuracy of arbitrary answers. Exact-quote validation alone does not establish it.

The first full-reading check exposed a product defect: the host had already checked the scope, but its result did not reach the author. Verified coverage is now passed as separate process metadata that does not authorize inventing document facts. A repeated control task confirmed the fix, and the earlier revision was retained.

PPTX **`d1dab161d0064bec`** was assembled locally from the accepted revision, with **0 model calls**. Checks covered 3 slides, the 12 ms content, and original paths in speaker notes. The file and `render-proof.json` are saved in the QA folder. This is a smoke check of the connection between originals and rendering. No new visual PPTX-geometry acceptance was performed. The slide draft was read in a real browser.

Real Streamlit was opened in IAB: Sources → Add materials, one path → Connect directory, successful-connection confirmation. Screenshot: `connected-directory.jpg`. The check used isolated XDG config/data, and QA server 8561 was stopped. User settings/services were unchanged.

### Contracts and build

`tests/test_collections.py` checks behavioral boundaries: connecting without reading; navigation through an index and link; exact original quotes; forwarding the selected Codex/Claude/Ollama adapter; a new file version in a new task and earlier quotes; resume after author failure even without the directory; cancellation during navigation without repeating an accepted model turn; symlink/path escapes; aliases/headings/backlinks/ambiguity; ordinary PDF/EPUB/TXT; identical bytes through multiple paths; disconnection and follow-up scope; rejecting false full-read with unread files or inaccessible subdirectories; atomic read failure on budget exhaustion; local slide assembly after directory removal; single-path CLI/UI; and concurrent schema 3 → 4 migration with data retention.

Shared schema 4 added collection registrations and `sources.hidden`. Earlier sources, jobs, and revisions were preserved. Concurrent migration is protected by a transaction. Cached originals are not mixed into new tasks and manual search as independent sources. Explicit reimport makes a source visible.

Full final run: **587 passed**, including **22** collection cases. Ruff check/format and `git diff --check` pass. The wheel was actually built offline and checked as a ZIP: new modules are present, and METADATA pins `PyYAML==6.0.3`. The installed PyYAML version uses MIT according to distribution metadata. Library code/resources were not copied into the repository.

### Boundaries

- Search is lexical, without embeddings. During a task, it locally extracts and caches files in the requested scope. There is no mandatory index/summary on connection.
- At most 100 000 supported files, 32 MiB text in the search scope, 24 model turns, 48k navigation-context characters, and 80k selected-original characters. Exceeding limits requires narrowing the directory/prompt. Checkpoints retain accepted work. This does not promise reading a huge vault in one call.
- For a full-reading request, the model sets `exhaustive` and scope. The host checks every extractable fragment before finish and reports unread ones. An inaccessible subdirectory/original prevents full completion. Selective search has no such guarantee.
- Hidden/system directories, symlinks, and unsupported formats are excluded. Code and Obsidian/Dataview plugins are not executed. External links are not opened. OCR and raster text are absent.
- A document snapshot corresponds to each file's first-reading time. Directory changes during a task do not make the snapshot atomic.
- Real Claude/Ollama navigation checks, a large personal vault, and an overall quality benchmark were not performed. Existing adapter contract tests do not replace that acceptance.
