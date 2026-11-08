# Contextual glossary and EPUB translation correction

Historical report. Current requirements and boundaries are in the [specification](../specification.md). Decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state on the experiment date.

04.11.2026. The next P1 step after the [EPUB experiment](2026-11-04-epub-approaches.md). Automatic terminology and the first user-accessible EPUB path were implemented through shared services, the worker, CLI, and Streamlit. This early check did not include a whole book or PDF. Later results are in the [full EPUB check](2026-11-04-epub-recurring-terms.md) and [PDF check](2026-11-05-pdf-translation.md). Narration was neither checked nor generated.

## Implementation

`terminology.py` stores a **term's sense**, its chosen translation, and specific occurrences separately. The same English word may have several senses. The model supplies exact quotes and word surfaces. Code resolves them to original-text ranges, checks package membership, quote uniqueness, and absence of overlaps. User terms are optional. An accepted sense translation is not overwritten while extracting the next package. The glossary is not built from a retelling of the book.

During translation, a translated-phrase range is saved for each source occurrence. Correcting a sense asks the model for contextual forms of those phrases only. Code applies bounded substitutions at saved ranges without regenerating paragraphs or the book. Other senses and text outside those ranges remain byte-for-byte unchanged. A manually edited phrase loses its automatic binding and stays in the text. UI/CLI explicitly report these retained occurrences. These are controlled edits through semantic links, not global word replacement.

`book_translation.py` uses the existing SQLite `jobs`, `drafts`, `artifacts`, and `task_models`. There is no database migration, new queue, or external server. `translate_epub` performs glossary collection → bounded-package translation → revision saving → local EPUB assembly. `render_epub` pins a saved revision and makes no model call. Source SHA-256, language, user glossary, text connection, and workflow version are pinned at submission. Original replacement is detected before inference. Checkpoints belong to the existing pipeline, are validated, and are written only after accepting the response.

Correction is a related run with a pinned parent revision. Earlier files and revisions are not replaced. `Regenerate text` retains the previous run and reuses accepted senses/occurrences. The model does not rebuild the glossary. Task-model settings apply to new operations, while resume retains its own parameters. The editor uses the existing recovery copies and revision-conflict protection. There are no new dependencies or changes to the global profile.

## Real check

The existing self-authored MIT chapter **Reliable sensor ingestion**, with 43 translatable blocks, was used. Source SHA-256: `e757b7f39db454309d3dc24d73a2520dd17da80c594f62af048df52678c0fdb8`. User books and audio were not used. Stable Codex CLI **0.162.1**, explicitly selected model **`gpt-6.1-sol`**, and standard subscription authorization. There was no paid API, provider switching, or weight download.

One user term was supplied: `write-ahead log` → **журнал упреждающей записи** (write-ahead log), with database-recovery context. It was retained and applied. Other senses were determined automatically. The result contained **32 senses and 79 source occurrences**. In particular, `log` as a journal versus a timber log, and `hydraulic head` as pressure head versus `head` as a manager, have different bindings. All supplied quotes/ranges resolved to the original. This does not establish that automatic extraction found every useful term.

| Run | Actual work | Accepted executor calls | Time from submission to completion |
|---|---|---:|---:|
| `fa5367f4d81148ee` | Automatic glossary and initial translation, workflow 1 | 2 | 257,544 s |
| `c78497ab99d34003` | Corrected translation with the existing glossary, workflow 2 | 1 | 127,624 s |
| `7a6037c3ddfa407b` | Editing one sense from the UI using saved r2 | 1 | 11,207 s |

These are four application calls and four accepted checkpoints. Time includes queuing, worker startup, and standard authorization checking. Tokens, cost, and the provider's internal retries were not measured. Whole-book speed cannot be inferred from this short experiment.

**Semantic defect found:** the first translation replaced the English words themselves in a paragraph explaining their different meanings. For example, the explanation of translating `log` became partly tautological in Russian. The format and terminology anchors were nevertheless correct. Workflow 2 added a rule to retain the original spelling when discussing a word's meaning/translation, with its target equivalent beside it. The new run reused the glossary. The initial version and its prompts/checkpoints were preserved. New and earlier jobs are explicitly distinguished by version. Resuming an old job does not silently supply the new prompt.

The corrected text retains `head`, `record`, `log`, `hydraulic head`, and `team head` as the source words being discussed, with Russian senses alongside them. An agent checked both complete translations against the original. No independent professional editor participated. No new semantic omissions, altered numbers, or lost key negations were found in the corrected version. An automatic choice such as `durability` → “долговечность” remains an editorial decision rather than a mandatory industry standard.

Before targeted correction, controlled manual edits were made to `c78497ab99d34003` r2: one head phrase was changed to **“контрольный напор”** (control head), and **“в этом примере”** (in this example) was added outside the term. The `hydraulic head` sense and new translation **“напор”** (head) were selected in the UI. **7 automatic occurrences in 6 blocks** were corrected, and **1 manual occurrence** was retained and shown in the UI. A separate comparison removed only the selected ranges from both versions: the remaining text matched byte-for-byte. The manager sense of `head`, other terms, manual wording, and earlier revisions were preserved. One new call returned only short term forms. Neither the glossary nor the full translation was rerun.

## Structure, interfaces, and offline checks

Original CSS/SVG, code and MathML, resource inventory, XHTML tree, non-translatable attributes, and local links were compared with the original for all three EPUB files: no issues. **EPUBCheck 5.4.0: 0 errors / 0 warnings** for each. The final XHTML was viewed in a browser at 1280 and 390 px: Cyrillic, the table, illustration, MathML, and code were readable, with no horizontal overflow at 390 px. This viewing is separate from the still-unperformed EPUB acceptance in the target reader.

Real Streamlit checks covered glossary viewing with original quotes, sense selection, changing a preference, queuing correction in an independent worker, the finished EPUB, and the retained-manual-edit message. Wide and 390 px areas were checked. AppTest/CLI additionally check the same creation contract, a single idempotent correction from two interfaces, editing, recovery, and retention of an earlier revision. QA fixed read-only widget-state behavior for the table/download and unstable labels for related runs. New translation labels no longer change when a title appears.

**167 targeted offline checks passed**: new terminology/translation, source/revision retention, checkpoints under controlled failure, no repeat inference for accepted packages, exact-quote and binding protection, actual-prompt bounds, local rendering, worker, task models, CLI, and UI. Ruff check/format and diff check also pass. Other product scenarios were not rerun in full. Real Claude/Ollama translations were not checked with this chapter.

Local artifacts are in `outputs/book-terminology-2026-11-04/` and excluded from Git: the test workspace with all revisions/EPUB files/checkpoints, `correction-qa.json`, `structure-qa.json`, UI screenshots, and `reader-preview/`. The source fixture remains in the public tree under MIT. Model responses and generated EPUB files are not added there. All processes use separate `XDG_CONFIG_HOME`/`XDG_DATA_HOME`. The main project, speech models, and Ollama were unchanged.

## Boundaries

The earlier narrow class of reflowable EPUB 3 with XHTML navigation is supported. EPUB 2/NCX, fixed layout, encryption/obfuscation, scripted content, media overlays, and DTD/entities are still explicitly rejected. This experiment did not accept a whole book or the target reader. PDF is not implemented. Labels inside raster illustrations are not translated.

Automatic sense extraction/separation and translation quality remain model decisions. Structural and exact-quote checks do not establish their correctness. Correction is limited to aligned phrases: a grammatical-gender change requiring neighboring words to be rewritten is not guaranteed. Manual exceptions require explicit review rather than a hidden declaration of complete terminology consistency. An oversized indivisible block/context fails with an error. Text is not truncated to obtain a successful status.
