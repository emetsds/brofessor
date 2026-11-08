# Practice questions, reference, argument analysis, and audiobook

Historical report. Current requirements and boundaries are in the [specification](../specification.md), and decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state at the time of the experiment.

On 05.11.2026, the user instructed that the entire remaining plan be completed except for their personal acceptance. Implementation and final checks on 05–06.11.2026 completed P3 and resolved the observed P2 navigation hang. There are no new dependencies, SQLite schema, queue, provider, or process protocol. QA uses only self-authored synthetic MIT materials, not the user's personal vault.

## Shared workflow

The `reference` and `arguments` formats are templates of the existing `report`. Their sections retain `origin=sources|brofessor`, exact quotes, and Markdown for each revision. A reference can pin `{job_id, revision}` of an accepted translation in the same language. Its `term/sense/translation` entries are passed in the prompt as editorial preferences, while facts come from originals. Markdown includes a projection of that same glossary. There is no second mutable glossary.

`study` creates 2–12 scenario and open questions with expected explanations, criteria, and original quotes. Saved answers belong to the same revision. `review_study` pins questions/answers, model, and original snapshot, providing `supported|partial|needs_work|insufficient_context` explanations. There are no numerical grades. Exactly one finding is required per answered question, and its quote scope is restricted to that question. Bounded batches use existing checkpoints, so late failure does not repeat accepted calls. CLI and the UI editor use the same saved data, and reviews remain in the same task's history.

`audiobook` prepares all extracted ready fragments of one original in order, without an LLM. For a translation, its exact saved revision is resolved/assembled locally, and the derived source is hidden from ordinary selection. EPUB follows the spine, PDF follows extracted pages, and Markdown follows headings. Footnotes and cells follow extraction order. Omitted/empty units are visible in coverage. Saved chapters and passages can be edited; `user_edited` then distinguishes the corrected narration revision from the original. `render_audiobook` uses existing voices, PCM segments, cancellation, and recovery. FFmpeg creates MP3 and chaptered M4B, with timestamps based on actual frames and pauses. Packaging uses the existing lifeline supervisor and atomic publication.

## Codex hang during P2 navigation

Earlier, `ddf6f67597014f24` received no first `NavigationStep` within 600 s, or within 180 s on resume. A control with shorter wording also failed. The CLI's JSONL mode was checked using the [official non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode). In an isolated trial, the same original prompt/schema received a response in **10,799 s** with `--json`. Only event types and diagnostic flags were retained, without credentials.

Production plain transport timed out again: **90,408 s** overall, **90,192 s** for the call. One official flag, `--json`, was added. The application still reads terminal JSON from `-o` and does not implement its own event runtime. Then **the same job** completed in **83,021 s**, with calls: NavigationStep **10,156 s**, NavigationStep **14,468 s**, Report **57,914 s**. Sources, subscription login, and model were unchanged. Five sections and final Markdown were checked: the instruction conflict is retained, 12 ms is not made a mandatory setting, stop conditions come from originals, and the proposed adaptation is labeled separately.

The internal cause of CLI behavior was not established. The check confirms resolution of this request's observed hang. It does not establish a general speed advantage or absence of all timeouts. Ledgers and results: `outputs/whole-plan-2026-11-05/diagnostics/`, with the final result in the earlier workspace `outputs/report-probe-2026-11-05/workspace/jobs/ddf6f67597014f24/`.

## Real text checks

Stable official Codex CLI **0.162.1**, requested model **gpt-6.1-sol**, existing worker and subscription authorization. No paid API fallback. The corpus `outputs/whole-plan-2026-11-05/cache-notes.epub` contains self-authored notes on two senses of log, the hit-ratio formula, a single-node measurement, and an unsupported power-loss claim. The EPUB container uses the existing synthetic fixture. Its metadata/navigation labels are also included in the translation and glossary.

| Result | Job | Working-run time | Accepted calls |
|---|---|---:|---:|
| Translation with accepted glossary | `917a1dc7c3ef4d22` | 119,001 s | 3 |
| Reference | `f374fd95682f4b7a` | 27,732 s | 1 |
| Argument analysis | `97d1d998f8c5423d` | 37,574 s | 1 |
| Four questions | `e0f78c6fa89a4a9e` | 34,506 s after the fix | 1 |
| Review of four r2 answers | `2e493db52e5d4241` | 20,436 s | 1 |

Repeating the probe reused the first three results without model calls. Their JSON records the repeated pass's time specifically. The initial times above were recorded in stdout of the working run, with individual call times separately saved in `calls.json`. The source EPUB matched byte for byte before and after. All reference/argument-analysis texts, questions, explanations, findings, and quotes were checked against the original five paragraphs.

The reference retained both senses **журнал/бревно** (record log/timber log), accepted hit-ratio terminology, `H = hits / requests`, its dimensionless nature, 30/100 = 0,30, and undefinedness at zero requests. The average 12 ms is separated from a timeout setting, and one-node results are not extrapolated to four. The application added all 18 accepted senses from the existing glossary revision without treating them as independent factual evidence.

The analysis separated the author's claim from the actual experiment with retries disabled. Reconstructed assumptions and the proposed test are labeled `brofessor`. Unproven safety is not declared proven unsafety, and absence of a mechanism's description does not become a claim that no mechanism exists in the system. No explanation for 99 completions out of 100 was invented.

Questions check calculation/units, a zero denominator, the distinction between completions and hits, and limits on power-loss conclusions. Verification used **synthetic agent answers**, not the user's: a correct calculation, an incorrect zero, a partial explanation, and an incorrect conclusion that data loss is inevitable. Results were respectively `supported`, `needs_work`, `partial`, and `needs_work`, with specific explanations and appropriate quotes.

The first StudySet request was rejected by the server: `schema.properties.answers.properties is required for object schemas`. Diagnostics repeated the same error. Explicit `properties={}` was added for an empty object in the existing `_strict_schema`, without a new contract or workaround runtime. After the fix, **the same job, prompt, and model** completed. Accepted translation and report calls were not repeated. The first CLI launch attempt in the restricted environment also failed its auth check. Working trials used the existing official authorization outside that restriction. Credentials were unchanged. Failed calls are saved separately from accepted ones.

## Real local audiobook

Already installed **Qwen3-TTS Base 1.7B 4-bit**, revision `37e955a1deb861c088ae5f3a67043185f3d1a60c`, and the ready-made ExNihilus EN host. No new weights were downloaded. Source `narration.md` has two short self-authored chapters, 35 words including headings. Draft **`d79079eddaf04feb`**, render **`cc901288c2a645d1`**: **14,290 s** processing, **14,25 s** finished audio, two accepted PCM segments, mono/24 kHz/16-bit. FFmpeg actually reread the M4B: chapters **Reading evidence 0,000–6,490 s** and **Keeping the original 6,490–14,250 s**, with names and timestamps matching the manifest. Text/order and original hash were retained.

File: `outputs/whole-plan-2026-11-05/audio-workspace/jobs/cc901288c2a645d1/audiobook.m4b`, with MP3/WAV and `chapters.json` alongside. Preparation of real Russian translation r1 **`08cb5bd818f44b16`** also passed: all extracted words in original order, one chapter/six bounded passages, without new model text or repeated narration. Later translation edits do not affect an already pinned job. That boundary is separately checked offline.

This is a functional check of synthesis, packaging, and navigation for a short EN text. It does not accept pronunciation, stress placement, long-form listening comfort, or the semantic accuracy of the text actually spoken. Personal listening acceptance of full RU/EN podcasts was not performed in this experiment and was later cancelled under D027. Quality of a full new audiobook is not claimed. Tables/footnotes are read in extracted order, complex PDF layout may need editing, and images and raster text are not narrated.

## Interface checks and limitations

Real Streamlit was opened in IAB. Checks covered the reference, saved r2 answers, review with exact original quotes, MP3 player, and chapter selection. Selecting chapter two loaded the 14,25 s file and set `currentTime=6`, according to the UI's second-level precision. The exact M4B chapter boundary is 6,490 s. Screenshots `audiobook-ui.jpg`, `study-ui.jpg`, and `feedback-ui.jpg` are in the QA directory. AppTest additionally creates every new type, saves answers/fields, and reads the same revisions through CLI. Temporary server 8564 was stopped.

Offline checks of the new logic detect real regressions: model substitution of learner answers, invalid quotes before caching, foreign question references, lost pinned revision/model, repeated accepted batches after a late failure, a second glossary, wrong terminology language, missing words/table/footnote, wrong spine order, unmarked empty chapter, missing M4B chapters, repeated synthesis of unchanged text, and cache loss on cancellation. Expensive text/speech calls are substituted at the external boundary. Real FFmpeg assembles and reads M4B. The vendor-schema test retains nullable/default protection and adds a real empty-object case.

Final checking fixed extra chapters at the technical boundary of every 100 Markdown lines: continuation of the same chapter is now retained until a genuine heading. A separate check compares an entire long chapter and its final section with the original. Answer review also pins the language of the saved revision itself, including manual JSON changes, rather than substituting the job's original language. The full final suite: **622 passed**. Ruff check/format, diff check, and offline wheel build passed. New modules were actually imported from an unpacked wheel outside the checkout, its strict schema was checked, and the package contains neither `outputs/` nor test materials.

Claude 2.1.317: official `auth status --json` returned `loggedIn=false`, `authMethod=none`, exit code 1. The real Claude path was not considered verified in this experiment. Subsequent [ordinary login and real checks](2026-11-06-claude-authentication.md) are described separately. New P3 was not actually run through Ollama. Only IAB and MCP Apps were available; ordinary Chrome/another browser was not connected. The conditional check of ordinary download time remained in the plan, and the earlier hanging download wait was not repeated. Semantic results from one short synthetic corpus do not guarantee quality on arbitrary books.
