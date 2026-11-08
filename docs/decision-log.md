# brofessor decision log

History of significant product and technical decisions. Current behavior is described in the [specification](specification.md), and current work is linked from the [Plan](plan.md).

The initial entries were reconstructed on 07.11.2026 from earlier requirements, architecture, research, plan, handover, and reports. Dates refer to the original decisions or documented experiments. “By a date” means the exact day of the original choice was not recorded. A technical implementation choice does not imply separate user approval of every tool or numerical threshold. Run results remain in `evidence/` and apply to the versions recorded there.

Entries are added chronologically with stable IDs. A revision adds a new decision, retaining the earlier entry with a replacement link. Factual corrections are marked explicitly. Ordinary code fixes, completed tasks, and test lists do not constitute separate decisions.

## D001. By 01.11.2026 — local product for working with sources

- **Decision:** brofessor develops as a standalone local project following the NotebookLM model: sources, questions, RU/EN podcasts targeting 20–60 minutes, and editable presentations. Books are the first main scenario. The name is always lowercase.
- **Basis:** the user's personal work with existing subscriptions and local models. Results must remain available after the agent session ends.
- **Boundary:** the first version does not promise full NotebookLM parity. Accounts, collaboration, public hosting, and direct Google Slides export are outside the initial scope.
- **Sources:** initial requirements, [initial technical check](evidence/2026-11-01-technical-baseline.md), and [working-scenario checks](evidence/2026-11-02-provider-acceptance.md). Current requirements: R01–R12.

## D002. By 01.11.2026 — shared core and independent local worker

- **Decision:** Python 3.12/uv, Typer, and Streamlit call the same application services. State is stored in SQLite and project files. Each workspace has one separate worker with an OS-lock and bounded operations.
- **Reason and alternative:** long jobs must survive UI reruns, browser closure, and CLI exit. An external queue, separate API server, leases, and universal host-agent protocol are unnecessary for the current local scenario.
- **Consequences:** rules, snapshots, cancellation, and recovery are shared across clients. Speech and rendering are separate from text models. A closed project transfers as a directory without a custom archive format.
- **Sources:** [worker, CLI/UI, and transfer checks](evidence/2026-11-02-provider-acceptance.md). R08, R10, R12.

## D003. By 01.11.2026 — official text CLIs and explicit network boundaries

- **Decision:** Codex and Claude use official bounded CLIs with the owner's authorization. Ollama uses a selected server with a local-only check. The application does not read subscription tokens or replace subscription access with a paid API.
- **Reason and alternative:** agent independence and control of material transfer and costs are required. A custom OAuth intermediary and embedding subscription credentials in an SDK were rejected. Desktop availability does not establish terminal CLI login.
- **Consequences:** unavailable integrations are reported explicitly. Another subscription or paid fallback is not purchased automatically. An explicit IP:port on another Ollama computer was allowed later. TTS and files remain on the application machine.
- **Sources:** [primary documentation and research boundaries](evidence/2026-11-01-technical-baseline.md), [real runners](evidence/2026-11-02-provider-acceptance.md), and [Claude Desktop and official login on 06.11](evidence/2026-11-06-claude-authentication.md). R09, R11.

## D004. 01.11.2026 — PPTX entirely in Python

- **Decision:** at the user's request, the Node/npm renderer was replaced with `python-pptx>=1.0.2,<2` and Pillow inside the existing Python service.
- **Reason and alternative:** a separate JavaScript runtime and framework complicated installation without being necessary for editable text, tables, and simple diagrams.
- **Consequences:** measure text using an installed font and fail explicitly on overflow. An office suite is used for separate visual QA, not generation. Later checks fixed minimum sizes at 28/20/18 pt. The earlier reduction of tables to 14 pt was revoked.
- **Sources:** [renderer replacement and visual checks](evidence/2026-11-02-pptx.md). R07, R12.

## D005. 01.11.2026 — initial local voice set

**Status:** regular profile selection was replaced by [D011](#d011-03112026--qwen-base-with-exnihilus-by-default) and [D012](#d012-03112026--one-supported-narration-method).

- **Decision:** initial runs used Qwen CustomVoice and subsequently added Silero CIS Base and F5/ESpeech. The catalogue separated engine, language, voices, weights, and assembly.
- **Reason:** this was a technically available starting point on the Mac, not a proven selection of the best Russian TTS. Actual duration and resumption were checked separately from listening quality.
- **Consequences:** successful synthesis did not justify accepting Russian speech. The user rejected Silero stress and the theatrical delivery of some Qwen/F5 samples, requiring another selection process.
- **Sources:** [selection history and user assessments](evidence/2026-11-03-speech-selection.md), [long runs with earlier voices](evidence/2026-11-01-long-podcasts.md).

## D006. 02.11.2026 — answers from originals, bounded search, and conversation versions

- **Decision:** questions use original fragments, exact quotes, and explicit insufficient/conflicting evidence states. Large sets retain BM25, query variants, and neighboring fragments. Notes and follow-ups use existing revisions and jobs.
- **Reason and alternative:** measured search failures were addressed by expanding neighboring-fragment context. There is not yet evidence that a separate embedding model or service is necessary. An earlier answer does not become the next answer's primary source.
- **Consequences:** full coverage and relevant selection are distinguished. Conversations are bounded in size and pin specific parent revisions. Saving the same answer as a note again retains the author's edits.
- **Sources:** [20 control questions](evidence/2026-11-02-source-questions.md), [notes and follow-ups](evidence/2026-11-02-notes-and-followups.md), and [whole book](evidence/2026-11-01-whole-book.md). R03–R05.

## D007. 02.11.2026 — Kokoro RU and main Russian Silero branch trials

**Status:** the regular catalogue was later simplified under D012.

- **Decision:** following a negative Silero CIS assessment, Silero RU, Kokoro RU, and RUAccent preparation were checked, followed by identical book material with manual stress marks.
- **Reason:** the initial MIT Silero CIS branch lacked the main Russian branch's auto-stress/homograph handling. Repeating technical tests did not address the audible problem.
- **Consequences:** in the direct comparison, the user preferred Silero but did not accept overall quality. The branches' different licenses were retained. These runs do not establish the best model on the market.
- **Sources:** [TTS history and assessment limits](evidence/2026-11-03-speech-selection.md).

## D008. 02.11.2026 — ready-made voices without user preparation

**Status:** the absolute prohibition on any references was refined by [D009](#d009-02112026--experiments-with-ready-made-licensed-references-allowed). The ready-to-use user workflow remains required.

- **Decision:** the user required stable voices out of the box. Fish without a reference was not accepted: its first voice sounded female even though the request specified a male role.
- **Reason:** description and seed did not establish a stable pair. Model labels do not prove actual timbre. A new user should not have to record or manually design voices.
- **Consequences:** the proposed synthetic Eugene reference was cancelled before synthesis. Researching open audio corpora did not itself authorize connecting them.
- **Sources:** [unsuccessful options and requirement revision](evidence/2026-11-03-speech-selection.md). R13.

## D009. 02.11.2026 — experiments with ready-made licensed references allowed

- **Decision:** the user explicitly allowed personal noncommercial experiments with published references and preferred Dialogs. Short Fish/Dialogs samples of Dima and Sveta received positive feedback. Fish, OmniVoice, and VoxCPM2 were compared using the same references.
- **Reason and alternative:** preselected permitted recordings preserve a workflow without audio preparation by a new user. The former absolute prohibition in D008 no longer describes this option.
- **Consequences:** similar sound in three recordings did not identify a winner. Parallel measurements did not rank speed. Engine, weight, codec, and reference licenses are considered separately. Dialogs was not designated the product default.
- **Sources:** [comparison conditions, models, results, and licenses](evidence/2026-11-03-speech-selection.md).

## D010. 03.11.2026 — quality and free licenses for supplied voices

- **Decision:** pleasant timbre and free code, weight, and sample licenses take priority for distribution. The user rejected the Dmitri/OHF and Natalia/SOVA pair. ExNihilus, Vosk, and other options were then auditioned.
- **Reason:** subjective suitability and permission to use cannot be inferred from one benchmark, ASR, or a license label. The permitted personal experiment in D009 does not make its entire stack freely redistributable.
- **Consequences:** model and voice are evaluated separately. Synthetic CC0 ExNihilus recordings became a suitable reference for the next trial. Unverified candidates did not become promised integrations.
- **Sources:** [timbre selection and recording provenance](evidence/2026-11-03-speech-selection.md).

## D011. 03.11.2026 — Qwen Base with ExNihilus by default

- **Decision:** following positive user feedback on a five-minute Russian dialogue, `qwen3-base` was selected: Qwen3-TTS Base 1.7B 4-bit with separate ready-made ExNihilus pairs for RU/EN.
- **Reason and alternative:** accepted Russian delivery, no user reference preparation, Apache-2.0 for Qwen, and CC0 samples. Earlier CustomVoice and other candidates did not produce the same accepted result.
- **Consequences:** the model downloads with the voice package. WAVs and transcripts are pinned in the project. The cache accounts for each speaker's sample. The short Russian sample was accepted. Subjective acceptance of English and all long episodes is not implied.
- **Sources:** [sample, pinned revisions, and integration](evidence/2026-11-03-speech-default.md), [subsequent long checks](evidence/2026-11-03-qwen-long-dialogues.md). R06, R13.

## D012. 03.11.2026 — one supported narration method

**Revised by D034:** support for earlier internal formats and profiles was revoked. Other current requirements remain in force.

- **Decision:** the KISS audit retained only `qwen3-base` in regular selection. The previous eight profiles were marked legacy and remained available by exact ID to restore historical jobs.
- **Reason and alternative:** a large catalogue of technically available options created a false impression of equal support and complicated the primary workflow.
- **Consequences:** the shared service and adapters were retained. New voice-selection interfaces and a reference builder were not developed. Saved specifications and renders were unchanged. Restoration instructions were in the README.
- **Sources:** [audit and rationale](evidence/2026-11-03-speech-selection.md#catalogue-simplification), former README restoration instructions (removed by D034).

## D013. 03.11.2026 — tasks, settings, and models replace a flat run list

- **Decision:** related script/audio, series/episodes, answer/follow-ups, and regenerations appear as one task. Shared settings are separate from the project. Models are copied into a task on creation.
- **Reason and alternative:** listing every technical job made it hard to return to the user's result. No entirely new domain platform was needed for grouping: existing relationships were used.
- **Consequences:** changing a default does not rewrite history. Resume retains original models. Settings work without a project. Save applies preferences atomically, while Cancel/close discards them.
- **Sources:** [interface history and structure checks](evidence/2026-11-07-ui-structure.md), [durable user workflow](evidence/2026-11-06-task-workflow.md). R14–R17.

## D014. 04.11.2026 — new podcast writer remains experimental

- **Decision:** an explicit mode revisiting originals section by section with working memory and a separate script check were implemented. The regular writer remains the default.
- **Reason and alternative:** a limited comparison showed a small editorial preference for the new writer but did not establish improved factual quality. Inputs increased by 62%. Some variants reused checkpoints.
- **Consequences:** structural references and exact quotes do not replace semantic review. Script checking retains partial results, pins revision/model, allows insufficient context, and does not become mandatory permission to narrate.
- **Sources:** [corpus, comparison, controlled errors, and limitations](evidence/2026-11-04-episode-writing.md).

## D015. 04.11.2026 — EPUB assembled locally from protected blocks

- **Decision:** EPUB was implemented first for the request to translate books while preserving formatting. Comparing full XHTML and protected text blocks led to selecting the latter. The model does not control the final archive's structure.
- **Reason and alternative:** both short outputs passed checks, but local reconstruction preserves markup, CSS, links, and resources independently of model output, at the cost of more input context.
- **Consequences:** source, projection, and workflow are pinned. Translation and rendering are separate. Resource, code/math, and notice preservation are checked separately from translation meaning. Fixed layout and other unsupported classes are rejected.
- **Sources:** [direct approach comparison](evidence/2026-11-04-epub-approaches.md). R24.

## D016. 04.11.2026 — term senses, manual exceptions, and EPUB compatibility

**Revised by D034:** support for earlier internal formats and profiles was revoked. Other current requirements remain in force.

- **Decision:** terminology stores senses and exact occurrences. Correction changes only linked phrases and retains manual edits. Namespace scopes and NCX were retained so EPUB opens in a reader. Discovered omissions led to a bounded frequent-term review and one correction of incorrect anchors without rewriting the translation.
- **Reason and alternative:** global word replacement mixes senses and damages author edits. Valid EPUB did not guarantee opening in EPUB.js. Passing a glossary did not correct terms missing from it.
- **Consequences:** glossaries and revisions are reused. Earlier workflows retain their prompts/checkpoints. Frequency review does not establish completeness. The first whole book required 44 editorial corrections. Later automatic checks do not replace that history.
- **Sources:** [targeted correction](evidence/2026-11-04-book-terminology.md), [reader](evidence/2026-11-04-epub-reader.md), [full automatic check](evidence/2026-11-04-epub-recurring-terms.md). R05, R24.

## D017. 05.11.2026 — bounded local PDF translation

- **Decision:** text-layer PDF uses the same translation, glossary, revisions, and worker. Assembly is local with PDFium/pypdf, ReportLab, DejaVu, and Pyphen. BabelDOC was studied as a candidate but neither installed nor included in the product.
- **Reason and alternative:** the verified class requires preservation of original graphics and precise region control. Initial PDFium regeneration changed encodings and did not update nested Forms. The new projection replaces only selected text strings and preserves cursor movement.
- **Consequences:** overflow and unsupported geometry cause rejection. The earlier projection was retained for old jobs. A 31-page book check establishes a limited class, not arbitrary publisher layouts or OCR.
- **Sources:** [real book, first projection, licenses, and boundaries](evidence/2026-11-05-pdf-translation.md). R24.

## D018. 05.11.2026 — connect directories by path and read them during tasks

**Status:** the custom navigation loop was replaced by D019, and its compatibility removed by D020. The user-facing connection method remains in force.

- **Decision:** connect a directory, including Obsidian, without preliminary selection, indexing, summaries, or model calls. During a task, a bounded controller searches, reads originals, and follows links.
- **Reason and alternative:** access to changing materials and exact versions is needed without mandatory full import. Pi was considered, but a separate TypeScript runtime was not selected for the existing Python application.
- **Consequences:** the application checks full coverage, path roots, budgets, and document trust boundaries. Code/Dataview is not executed. A completed task retains read originals after the directory changes.
- **Sources:** [initial implementation and subsequent replacement](evidence/2026-11-05-source-navigation.md). R25.

## D019. 05.11.2026 — stable Pydantic AI Slim for navigation

- **Decision:** the recommendation to write a custom loop was reconsidered, a trial was run, and `pydantic-ai-slim==2.66.0` was selected. The standard Agent uses a custom Model over the previous bounded CLI/Ollama adapters.
- **Reason and alternative:** a ready-made Python loop fits the stack and typed tools. The Alpha Harness and a built-in provider reading CLI credentials were not selected. The comparison did not establish a speedup or a reduction in all custom code.
- **Consequences:** document operations, budgets, snapshots, citations, worker, and checkpoints remain in brofessor. The resume v1 branch was initially retained, then revised by D020.
- **Sources:** [comparison, real Codex/Ollama, and fault/resume](evidence/2026-11-05-source-navigation.md).

## D020. 05.11.2026 — remove the old controller and unnecessary compatibility

- **Decision:** at the user's direct instruction, the old loop, runtime selection, and compatibility with v1 intermediate formats were removed. All tasks use one Pydantic path with a typed `NavigationStep`.
- **Reason and alternative:** maintaining two implementations and generic string-based JSON calls complicated maintenance without current user benefit.
- **Consequences:** completed sources, quotes, and results are retained, but resuming the old controller is not promised. The current path recovers from its own checkpoints and atomic tool results. Useful protection from removed tests was transferred to the real SDK.
- **Sources:** [KISS audit, new protocol, and Codex check](evidence/2026-11-05-source-navigation.md#kiss-audit-and-current-protocol-check).

## D021. 05.11.2026 — written formats as templates for one report

- **Decision:** source comparison and working guides use one editable `report`. Reference and argument analysis were subsequently added as its templates.
- **Reason and alternative:** these formats share inputs, original evidence, revisions, and Markdown publication. New queue kinds, a server, and an independent terminology system are unnecessary.
- **Consequences:** source and adaptation are distinguished by section. Markdown is created locally on every save without another model call. A reference uses a pinned translation glossary.
- **Sources:** [comparison and guide](evidence/2026-11-05-written-reports.md), [additional templates](evidence/2026-11-06-learning-and-audiobook.md). R18.

## D022. 05–06.11.2026 — learning and audiobooks included in the current product

- **Decision:** following the instruction to complete the remaining plan except personal acceptance, application questions, saved answers, and review were implemented, together with sequential narration of originals/saved translations with chapters.
- **Reason:** these are independent workflows with distinct inputs and outputs, using the existing core, sources, worker, models, and versions.
- **Consequences:** reviews pin specific questions, answers, and originals. There are no numerical grades. Audiobooks require no text inference, and narration-text edits are explicit. A short two-chapter trial does not establish full-book acceptance.
- **Sources:** [content and functional checks](evidence/2026-11-06-learning-and-audiobook.md). R19, R20.

## D023. 05–06.11.2026 — JSONL transport for the official Codex runner

- **Decision:** the bounded runner uses standard `codex exec --json`, still reading the final result from a separate `-o` file.
- **Reason and alternative:** the previous plain transport repeatedly hung on NavigationStep. A controlled repeat of the same request in JSONL returned, after which the previous job completed without changing model, credentials, or sources.
- **Consequences:** this addresses an observed hang. The internal CLI cause was not established, and freedom from all timeouts is not promised. No separate event runtime was added.
- **Sources:** [timeouts](evidence/2026-11-05-written-reports.md), [transport comparison and completion](evidence/2026-11-06-learning-and-audiobook.md).

## D024. 06.11.2026 — navigation, names, and reversible deletion

- **Decision:** a project opens through its folder name, with a separate arrow expanding tasks. Global search and the catalogue filter word prefixes on each keystroke. A task name is separate from its request and material title. Deleting a project/entire related task is reversible.
- **Reason:** search, technical statuses, and an incidental latest run must not obstruct returning to a result. Removing an item through the interface must not destroy materials.
- **Consequences:** only explicit opening updates MRU. Search/polling does not. Active work must be cancelled before deletion. Tombstones hide related runs, while originals, revisions, and recovery remain on disk.
- **Sources:** [user workflow](evidence/2026-11-06-task-workflow.md), [interface history](evidence/2026-11-07-ui-structure.md). R14, R21.

## D025. 06.11.2026 — downloads only in shared settings

- **Decision:** the user starts UI downloads only in Settings. In a project, they select a model and receive a settings link when files are missing. Downloads and cleanup use the same local worker in a separate workspace.
- **Reason and alternative:** settings, model installation, and tasks had mixed lifecycles. Closing a dialog or switching projects must neither stop nor duplicate a download.
- **Consequences:** pinned manifests, progress, cancellation, resume of the same job, and busy-resource protection are retained. Attempt history is not a list of installed models. No external queue or leases were added.
- **Sources:** [real worker, Range, and UI restart](evidence/2026-11-06-task-workflow.md#download-verification-after-restart). R13, R15, R17.

## D026. 06.11.2026 — first narration and durable execution progress

- **Decision:** a new podcast automatically continues with narration after its first saved revision. Stages, actual execution intervals, queue time, and pauses persist in the existing SQLite database.
- **Reason and alternative:** the user expects a finished episode and an understandable process. Requiring a separate manual render after first generation and losing progress on restart broke that workflow.
- **Consequences:** manual and automatic requests converge on one render job. Audio failure preserves the script, and narration after edits starts explicitly. Measurements do not invent historical timing or count worker downtime as computation. Schema 6 preserves earlier data.
- **Sources:** [fault/recovery, workflow, and browser](evidence/2026-11-06-task-workflow.md). R13, R22.

## D027. 06.11.2026 — personal M4 and two separate investigations cancelled

- **Decision:** at the user's direct instruction, full personal listening acceptance M4, investigation of an unreproduced gray bar, and checking download speed in an ordinary external browser were removed from current scope.
- **Reason:** the user cancelled these tasks. Historical references to open M4 are not current instructions.
- **Consequences:** earlier records, measurements, and limitations remain. Cancellation does not mean successful listening or revoke product quality requirements. New UI changes and documentation moves do not restart this work. Repeating all generation without an identified defect is unnecessary.
- **Sources:** cancellation in the previous plan and handover, [finished episodes and verification limits](evidence/2026-11-03-qwen-long-dialogues.md#full-substantive-review-of-finished-episodes), [UI checks](evidence/2026-11-06-task-workflow.md).

## D028. 06–07.11.2026 — consistent screen structure and repeated acceptance

- **Decision:** large materials, sources/checks, and service details are separated with headings, boundaries, and independent collapse controls across all task kinds and their history.
- **Reason and alternative:** the initial completion claim after typography changes was incorrect. Repeated screenshots revealed missing collapse controls, settings boundaries, and translation history. The stage was reopened.
- **Consequences:** finished files and save actions stay accessible, history does not change the current buffer, and Cancel/Resume are not hidden with the report. The stage was closed after structural implementation and a browser matrix rather than font replacement alone.
- **Sources:** [correction of the earlier assessment and final matrix](evidence/2026-11-07-ui-structure.md).

## D029. 07.11.2026 — code structure follows existing responsibilities

- **Decision:** retain one `src` package grouped into `interfaces`, `application`, `features`, `infrastructure`, shared contracts, and resources. Tests follow the same areas, with shared builders in `tests/helpers`.
- **Reason and alternative:** the flat package and large CLI/UI modules hindered navigation. New frameworks, a DI container, redirect modules, and `sys.path` changes are unnecessary.
- **Consequences:** internal Python paths changed, while user commands, SQLite, snapshots, request keys, and revisions were preserved. Resources are read from the installed package. Worker and guardian launch independently of cwd.
- **Sources:** [move verification and wheel outside the checkout](evidence/2026-11-07-code-organization.md).

## D030. 07.11.2026 — readable prompts and pinned instructions

**Revised by D034:** support for earlier internal formats and profiles was revoked. Other current requirements remain in force.

- **Decision:** authored instructions were extracted into separate UTF-8 Markdown templates with a catalogue, variables, and local preview. The loader uses the standard library, without a new template/prompt framework.
- **Reason and alternative:** the user should find and edit instructions without searching Python strings. Extraction was separate from editorial wording changes so regression causes remain distinguishable.
- **Consequences:** new jobs pin texts and hashes, while retry/resume retains earlier instructions. An immutable archive and previous checkpoint keys were retained for older jobs. Input materials are substituted once and are not executed as templates.
- **Sources:** [preservation and installed-worker checks](evidence/2026-11-07-prompt-extraction.md), [catalogue](../src/brofessor/prompts/README.md). R23.

## D031. 07.11.2026 — ready-made Ollama transport replaces the custom parser

- **Decision:** at the user's request, the custom NDJSON parser was replaced by stable Pydantic AI 2.66.0 `OllamaModel`/`OllamaProvider` through Direct API and `/v1/chat/completions` on the selected server.
- **Reason:** a ready-made client reduces custom transport code without changing the semantic pipeline. An OpenAI-compatible SDK does not imply using the OpenAI API or its credentials.
- **Consequences:** previous schema/messages/checkpoints were preserved, with the schema transformer disabled. SDK retries are zero. Proxies/redirects and telemetry are disabled. Local-only preflight, stream limits, deadline, cancellation, and final-response validation remain in the application.
- **Sources:** [real short question and replay without inference](evidence/2026-11-07-ollama-transport.md).

## D032. 07.11.2026 — named values with preserved external contracts

**Revised by D034:** support for earlier internal formats and profiles was revoked. Other current requirements remain in force.

- **Decision:** repeated domain values use explicit StrEnum, owner-defined constants, and immutable groups, with TypedDict for records shared across modules. Common definitions live in `contracts/`, and application-specific definitions stay with their owner.
- **Reason and alternative:** the goal is shared meaning and navigable usages. Mechanically naming every string, merging different concepts, and widening types for a common enum were rejected. A local trial showed a JSON-schema change from a direct enum field, so existing schemas retained Literal aliases.
- **Consequences:** SQLite/JSON preserve plain strings and historical unknown values. Snapshots/checkpoints and manual edits remain compatible. Streamlit receives plain strings through a widget adapter. Scoped mypy checks selected boundaries without claiming strict typing of the entire application.
- **Sources:** [59 original schemas, old jobs, review, and verified wheel](evidence/2026-11-07-named-values.md). Stabilization and review are complete, not open work.

## D033. 07.11.2026 — three main project documents

**Revised for work tracking by [ADR-0001](adr/0001-openspec-and-matt-pocock-skills.md):** OpenSpec changes now own implementation task lists. This entry preserves the earlier decision and its rationale.

- **Decision:** the user agreed to `specification.md`, `decision-log.md`, `plan.md`, and selective `evidence/` appendices. A separate continuously updated handover was removed. Operating instructions remain in README, and working rules in AGENTS.md.
- **Reason and alternative:** earlier documents duplicated requirements, current work, reports, and history, and their copies diverged. Simply renaming or moving all accumulated reports did not address the cause.
- **Consequences:** the specification contains current agreements and limitations, the log retains significant choices, and the plan contains only unfinished logical blocks. A completed block is removed after verification and documentation updates. Cancelled work does not return from historical reports. Accepted but unimplemented features are marked explicitly. Proposals do not become requirements merely because an old text mentions them.
- **Basis:** structure discussion and the user's “Делаем” (“Let's do it”) instruction on 07.11.2026. Development rules are in [AGENTS.md](../AGENTS.md), shortened by D034.


## D034. 08.11.2026 — short instructions without backward compatibility

**Revised for developer-documentation language by [ADR-0001](adr/0001-openspec-and-matt-pocock-skills.md):** maintained developer documentation is written in English. Product languages and the other principles below are unaffected.

- **Decision:** at the user's direct instruction, AGENTS.md contains nine general principles, a short reading route, QA isolation, and language rules. Backward compatibility is not preserved: this new experimental project does not carry discarded hypotheses into later implementations. Code and current documentation take precedence over model memory.
- **Reason and alternative:** long repetitive instructions and immutable historical schemas constrained simplification. Moving all of AGENTS.md into another mandatory document was rejected. Useful information already belongs in README, the specification, plan, and log.
- **Consequences:** the prompt archive and old checkpoint identities, earlier reading/script/translation workflows and EPUB/PDF projections, hidden CustomVoice/F5/Silero/Kokoro profiles with their adapters and extras, earlier settings/Ollama-address formats, and SQLite 0–5 migrations were removed. External EPUB 2/3 support remains required. Current snapshot/retry/resume, exact quotes, project portability, and preservation of manual edits remain in force. Finished user files are unchanged. Incompatible old computation must be recreated.
- **Verification:** 644 offline tests, Ruff, scoped mypy (22 files), `uv lock --check --offline`, and the wheel outside the checkout passed. The lock lost 128 packages (229 → 101), without changing retained versions. The wheel verified 53 prompts for three providers and a synthetic task replay without repeated inference. Historical schema/request baselines and tests for removed adapters were removed with their support. Current boundaries remain protected in `tests/prompts`, `tests/features`, `tests/infrastructure/formats`, `tests/infrastructure/speech/test_qwen_base.py`, lifecycle/storage, and CLI/UI tests. A controlled publication failure still checks checkpoint reuse and author-revision preservation. Real-model checks and speech-quality assessment are not claimed by this change.
- **Supersedes:** D012 for legacy profiles, D016/D030 for earlier workflows and the archive, and D032 for mandatory historical-schema preservation. D033's document structure remains in force.
