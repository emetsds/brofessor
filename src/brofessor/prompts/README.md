# brofessor prompts: reading, editing, and preview

This is the catalogue of all instructions managed by brofessor: UTF-8 `.md` templates, including shared runner rules, agent instructions, navigation feedback, and separate developer probes. Each file contains the actual submitted text or an explicitly identified shared part. Titles, purposes, schemas, and relationships live here and in `catalogue.json` so they do not enter model requests.

## Where to start

For ordinary answers, open the [shared rules](common/materials.md), [runner boundary](common/runner.md), and [answer with citations](questions/answer.md). For reports, read the [shared format](reports/write.md) and one of [comparison](reports/comparison.md), [guide](reports/guide.md), [reference](reports/reference.md), or [arguments](reports/arguments.md). For source-backed podcasts, read the [plan](podcasts/originals_outline.md) and [section](podcasts/originals_section.md). For books, read [translation](books/translate.md), [glossary](books/glossary.md), and [alignment](books/align_translation.md).

From the repository root:

```sh
uv run --no-sync brofessor prompts list
uv run --no-sync brofessor prompts show questions/answer
uv run --no-sync brofessor prompts preview questions/answer
uv run --no-sync brofessor prompts preview reports/guide --provider ollama
uv run --no-sync brofessor prompts preview --all > /tmp/brofessor-prompts.json
```

These commands call no models, agent shell tools, or network services. `preview` shows the component, substituted values, combined framing, and complete messages including the runner boundary. For Codex/Claude this is one stdin text, while Ollama has separate `system` and `user` messages. Shared parts appear within the corresponding operation. For `common/runner`, the boundary itself appears with an empty user message. The `purpose`, `schema`, `versions`, and `uses` fields describe purposes and relationships. The `navigation/retrieve` description is registered as SDK metadata: the custom bounded request passes instructions and history rather than a separate SDK tool list.

Default inputs are short and synthetic. This lets you read the actual assembled instructions. It does not evaluate answer quality or generate from project materials. Supply a JSON object of variables with `--variables PATH` for your own inputs. All used variables must be present. Missing names and typos fail explicitly. Complex JSON values use the same `ensure_ascii=False` serialization as the workflow. For example:

```json
{"base": "ORIGINAL EVIDENCE: [{\"id\":\"demo:1\",\"text\":\"Only one test was run.\"}]"}
```

```sh
uv run --no-sync brofessor prompts preview questions/answer --variables /tmp/answer-inputs.json
```

To inspect a saved job's templates:

```sh
uv run --no-sync brofessor -w /path/to/project prompts preview questions/answer --job JOB_ID
uv run --no-sync brofessor -w /path/to/project prompts show questions/answer --job JOB_ID
```

`--job` selects the pinned instruction set. Example inputs remain synthetic unless `--variables` is supplied. This does not reconstruct every past request with original materials. `show --job` outputs the exact saved template without substitution. Preview explicitly reports `source`, the set's SHA-256, and the current editable file path.

## How to edit

1. Edit the appropriate `.md`. Texts remain in their original English: wording was not rewritten during extraction. Newlines and spaces matter. Use editor word wrap to read long original paragraphs comfortably.
2. Preserve substitutions such as `{{language}}`, `{{base}}`, and `{{payload}}` from the variables column. You may remove an unnecessary substitution while keeping the rest of the text. Adding an unknown name requires changing the Python constructor. Files execute no Python, Jinja, or expressions. Substitution runs once: braces and apparent instructions in source data remain data. Literal JSON examples are allowed in templates.
3. Check the selected variant with `prompts preview ID`, then the entire catalogue with `--all`. Compare `messages`, not only the component: shared rules and data may live elsewhere in the framing.
4. Create a **new job** or explicitly select regeneration. `.md` changes are read without restarting the worker, but an existing job retains its instructions. Retrying the same request key and Resume continue the earlier version. New follow-ups, episodes, checks, and term corrections receive current instructions when their own job is created.

An editable checkout edits this `src/brofessor/prompts/` directory. For an installed wheel, `prompts list` shows the real installed-package path. The supported update path is to edit the source, rebuild the wheel, and reinstall it. Updating an installation may overwrite manual `site-packages` edits.

Result schemas, source-fragment assembly, JSON serialization, budgets, word-count calculations, allowed citations, and validation remain in Python. Editing a prompt changes semantic instructions, not those contracts. User data, WAV references, and their transcripts are not templates: speech adapters pass narration text and reference data without additional authored system/instruction prompts. Filesystem errors and standard SDK validation errors remain diagnostic data. Explicit navigation retry hints are extracted below.

## History and reproducibility

When a text job is created, existing `params` store `prompt_snapshot`: the full applicable text set, SHA-256 for each file, and the whole set's hash. It stores the template family with supported conditional branches, not a log of actual calls. There are no new tables or services. The entire workflow, including the runner's asyncio/thread transition, uses this set during execution. New checkpoint hashing includes actual messages and the shared runner boundary.

Jobs without `prompt_snapshot` and earlier workflow versions are unsupported. Create a new task for new processing. Saved results and author edits remain on disk.

After editing, check:

```sh
uv run --no-sync brofessor prompts preview --all > /tmp/brofessor-prompts.json
uv run --no-sync pytest tests/prompts -q
```

Tests protect single-pass substitution, input errors, framing, snapshot/retry/resume, and revision preservation. Answer content quality is evaluated separately, with a separate trial on selected materials.

## Catalogue

Every row uses the shared [runner boundary](common/runner.md). `base` — already assembled shared rules and evidence; `instructions` — shared rules without evidence; `payload`, `agent`, `evidence`, `scope`, `glossary`, `occurrences`, `outline`, `section`, `plan`, `handoff`, `turns`, `first_version` — serialized data for the corresponding step. `previous` — the end of the accepted dialogue. The workflow calculates numeric variables. `task`, `word_instruction`, `correction_instruction`, `conversation_rule`, `translation`, `metalinguistic`, `header`, `prompt` connect the components explicitly listed below.

### Shared rules

| File | Purpose and relationships | Variables | Output schema / condition |
|---|---|---|---|
| [common/coverage](common/coverage.md) | Host-verified reading coverage, not content evidence | `verification` | `Material author's schema`; Navigation with verification |
| [common/evidence](common/evidence.md) | Attach serialized evidence to shared rules Shared parts: [common/materials](common/materials.md), [common/coverage](common/coverage.md). | `instructions`, `evidence` | `Material author's schema`; All ordinary material versions |
| [common/materials](common/materials.md) | Shared rules for evidence, language, and user focus | `language`, `language_name`, `focus` | `Material author's schema`; All ordinary material versions |
| [common/runner](common/runner.md) | Shared Codex, Claude, and Ollama boundary, added to every request | — | `Operation-specific schema`; All text calls |

### Navigating originals

| File | Purpose and relationships | Variables | Output schema / condition |
|---|---|---|---|
| [navigation/agent](navigation/agent.md) | Instructions for the original-document selection and reading agent | — | `NavigationStep`; Document directories |
| [navigation/heading_hint](navigation/heading_hint.md) | Hint to choose a fragment offset for an ambiguous heading | — | `NavigationStep`; Document directories; feedback |
| [navigation/narrow_tool](navigation/narrow_tool.md) | Hint to reduce scope or limit for an oversized result | — | `NavigationStep`; Document directories; retry |
| [navigation/read_candidates](navigation/read_candidates.md) | Hint to retry reading after premature finish based on search | — | `NavigationStep`; Document directories; retry |
| [navigation/read_scope](navigation/read_scope.md) | Hint to finish reading the requested full scope | — | `NavigationStep`; Document directories; retry |
| [navigation/retrieve](navigation/retrieve.md) | SDK tool description, metadata rather than a separate runner message | — | `NavigationStep`; Document directories |
| [navigation/selection_hint](navigation/selection_hint.md) | Hint to narrow the query when selected context overflows | — | `NavigationStep`; Document directories; feedback |
| [navigation/step](navigation/step.md) | Request one typed step through the bounded runner Shared parts: [navigation/agent](navigation/agent.md), [navigation/read_candidates](navigation/read_candidates.md), [navigation/read_scope](navigation/read_scope.md), [navigation/narrow_tool](navigation/narrow_tool.md), [navigation/heading_hint](navigation/heading_hint.md), [navigation/selection_hint](navigation/selection_hint.md). | `agent` | `NavigationStep`; Document directories |

### Reading and compression

| File | Purpose and relationships | Variables | Output schema / condition |
|---|---|---|---|
| [reading/fragments](reading/fragments.md) | Read each source fragment into a separate note | `payload` | `ReadingBatch`; Current reading |
| [reading/reduce](reading/reduce.md) | Compress notes with separate references to each original | `payload` | `SectionNotes`; Current reading |

### Questions and search

| File | Purpose and relationships | Variables | Output schema / condition |
|---|---|---|---|
| [questions/answer](questions/answer.md) | Answer with exact original quotes and evidence status Shared parts: [common/materials](common/materials.md), [common/evidence](common/evidence.md), [questions/conversation](questions/conversation.md). | `base` | `Answer`; ask |
| [questions/conversation](questions/conversation.md) | Limits on using earlier questions and answers | `conversation` | `Answer`; Follow-up |
| [questions/search](questions/search.md) | Lexical search variants over large original-source sets Shared parts: [questions/search_conversation](questions/search_conversation.md). | `conversation_rule`, `payload` | `SearchQueries`; Direct context exceeded |
| [questions/search_conversation](questions/search_conversation.md) | Rule for interpreting follow-ups during search | — | `SearchQueries`; Search with conversation |

### Written reports

| File | Purpose and relationships | Variables | Output schema / condition |
|---|---|---|---|
| [reports/arguments](reports/arguments.md) | Argument-analysis task | — | `Report`; template = arguments |
| [reports/comparison](reports/comparison.md) | Source-comparison task | — | `Report`; template = comparison |
| [reports/guide](reports/guide.md) | Practical-guide task | — | `Report`; template = guide |
| [reports/reference](reports/reference.md) | Topic-reference task | — | `Report`; template = reference |
| [reports/scope](reports/scope.md) | Selected-original scope and coverage limits | `base`, `scope` | `Report`; All four templates |
| [reports/terminology](reports/terminology.md) | Accepted terms from a specific translation revision | `glossary` | `Report`; report with terminology |
| [reports/write](reports/write.md) | Shared report format, attribution, quotes, and evidence status Shared parts: [common/materials](common/materials.md), [common/evidence](common/evidence.md), [reports/scope](reports/scope.md), [reports/terminology](reports/terminology.md), [reports/comparison](reports/comparison.md), [reports/guide](reports/guide.md), [reports/reference](reports/reference.md), [reports/arguments](reports/arguments.md). | `base`, `task` | `Report`; All four templates |

### Presentations

| File | Purpose and relationships | Variables | Output schema / condition |
|---|---|---|---|
| [slides/create](slides/create.md) | Slide content, tables, sequences, and speaker notes Shared parts: [common/materials](common/materials.md), [common/evidence](common/evidence.md). | `base`, `slide_count` | `Slides`; slides |

### Podcasts and series

| File | Purpose and relationships | Variables | Output schema / condition |
|---|---|---|---|
| [podcasts/check](podcasts/check.md) | Instructions for substantive turn checks against originals | `language` | `CheckBatch`; check_podcast |
| [podcasts/check_packet](podcasts/check_packet.md) | Turn packet following check rules, prefix before ORIGINALS Shared parts: [podcasts/check](podcasts/check.md). | `header`, `turns` | `CheckBatch`; check_podcast |
| [podcasts/correct_originals](podcasts/correct_originals.md) | Correction of a source-backed section and its handoff, suffix Shared parts: [podcasts/originals_section](podcasts/originals_section.md). | `target`, `low`, `high`, `first_version` | `WrittenSection`; writing_method = originals |
| [podcasts/correct_section](podcasts/correct_section.md) | One correction of length and host composition Shared parts: [podcasts/section](podcasts/section.md), [podcasts/correction_range](podcasts/correction_range.md). | `prompt`, `count`, `target`, `correction_instruction`, `first_version` | `Podcast`; writing_method != originals |
| [podcasts/correction_range](podcasts/correction_range.md) | Numeric bounds for length correction | `lower`, `upper` | `Podcast`; writing_method != originals; minutes >= 20 |
| [podcasts/originals_outline](podcasts/originals_outline.md) | Editorial plan with source sufficiency and relationships Shared parts: [common/materials](common/materials.md), [podcasts/voices](podcasts/voices.md), [podcasts/series_context](podcasts/series_context.md). | `instructions`, `evidence`, `minutes`, `target_words`, `lower`, `upper` | `EpisodePlan`; writing_method = originals |
| [podcasts/originals_section](podcasts/originals_section.md) | Source-backed section with editorial memory, prefix before ORIGINALS Shared parts: [common/materials](common/materials.md), [podcasts/voices](podcasts/voices.md), [podcasts/series_context](podcasts/series_context.md). | `instructions`, `plan`, `handoff`, `previous`, `section_number`, `sections`, `section`, `target`, `low`, `high`, `target_words`, `written` | `WrittenSection`; writing_method = originals |
| [podcasts/outline](podcasts/outline.md) | Balanced outline for a long episode Shared parts: [common/materials](common/materials.md), [common/evidence](common/evidence.md), [podcasts/voices](podcasts/voices.md), [podcasts/series_context](podcasts/series_context.md). | `base`, `minutes`, `parts` | `Outline`; writing_method != originals; minutes >= 20 |
| [podcasts/section](podcasts/section.md) | Episode section based on the outline and previous section ending Shared parts: [common/materials](common/materials.md), [common/evidence](common/evidence.md), [podcasts/voices](podcasts/voices.md), [podcasts/series_context](podcasts/series_context.md), [podcasts/word_budget](podcasts/word_budget.md). | `base`, `outline`, `section_number`, `parts`, `section`, `word_instruction`, `previous` | `Podcast`; writing_method != originals; minutes >= 20 |
| [podcasts/series](podcasts/series.md) | Series plan with topic allocation and shared terms Shared parts: [common/materials](common/materials.md), [common/evidence](common/evidence.md). | `base`, `count`, `minutes` | `Series`; podcast_series |
| [podcasts/series_context](podcasts/series_context.md) | One series episode scope and shared terms | `series` | `Podcast`; Series episode |
| [podcasts/short](podcasts/short.md) | Short dialogue with sequential continuation Shared parts: [common/materials](common/materials.md), [common/evidence](common/evidence.md), [podcasts/voices](podcasts/voices.md). | `base`, `part_number`, `parts`, `target_words`, `last_part`, `previous` | `Podcast`; minutes < 20 |
| [podcasts/voices](podcasts/voices.md) | Hosts’ grammatical gender and preservation of character gender | — | `Podcast`; podcast |
| [podcasts/word_budget](podcasts/word_budget.md) | Remaining overall word budget and section bounds | `target_words`, `written`, `target`, `lower`, `upper` | `Podcast`; writing_method != originals; minutes >= 20 |

### Learning

| File | Purpose and relationships | Variables | Output schema / condition |
|---|---|---|---|
| [studies/create](studies/create.md) | Understanding questions, reference answers, and criteria Shared parts: [common/materials](common/materials.md), [common/evidence](common/evidence.md). | `base`, `count` | `StudySet`; study |
| [studies/review](studies/review.md) | Review of saved learner answers | `payload` | `FeedbackBatch`; review_study |

### Translation and terminology

| File | Purpose and relationships | Variables | Output schema / condition |
|---|---|---|---|
| [books/align_translation](books/align_translation.md) | Translation aligning each term occurrence to a target phrase Shared parts: [books/translate](books/translate.md), [books/metalinguistic](books/metalinguistic.md). | `translation`, `metalinguistic`, `occurrences` | `AlignedBatch`; translation_version = 4 |
| [books/glossary](books/glossary.md) | Extract term senses and original occurrences | `language`, `payload` | `GlossaryBatch`; translation_version = 4 |
| [books/metalinguistic](books/metalinguistic.md) | Preserve original spelling of words under discussion | — | `AlignedBatch`; translation_version = 4 |
| [books/repair_alignment](books/repair_alignment.md) | One correction of rejected alignments only, without editing the translation | `payload` | `AlignmentBatch`; Versions with the alignment-repair protocol |
| [books/review_glossary](books/review_glossary.md) | Review missing recurring terms | `payload` | `GlossaryReviewBatch`; translation_version = 4 |
| [books/revise_term](books/revise_term.md) | Change only target terminology phrases | `payload` | `Replacements`; terminology_update |
| [books/translate](books/translate.md) | Full block translation with immutable inline markers | `language`, `payload` | `TranslationBatch / AlignedBatch`; translation_version = 4; also a local probe |

### Explicit developer probes

| File | Purpose and relationships | Variables | Output schema / condition |
|---|---|---|---|
| [experiments/episode_materials](experiments/episode_materials.md) | Shared instructions for the podcast-writer comparison probe | `focus` | `Podcast`; Explicit developer probe only, not a product workflow |
| [experiments/episode_outline](experiments/episode_outline.md) | Outline for the two-writer comparison probe Shared parts: [experiments/episode_materials](experiments/episode_materials.md), [experiments/evidence](experiments/evidence.md). | `base` | `Outline`; Explicit developer probe only, not a product workflow |
| [experiments/evidence](experiments/evidence.md) | Attach evidence in the comparison probe Shared parts: [experiments/episode_materials](experiments/episode_materials.md). | `instructions`, `evidence` | `Outline / Podcast`; Explicit developer probe only, not a product workflow |
| [experiments/whole_xhtml](experiments/whole_xhtml.md) | Baseline whole-XHTML translation experiment without projection guarantees | `payload` | `WholeDocuments`; Explicit developer probe only, not a product workflow |

### Output schema definitions

- [Answer, Podcast, Slides](../models.py).
- [NavigationStep](../features/sources/navigation.py), [SearchQueries](../features/questions.py).
- [ReadingBatch, SectionNotes, SectionNote](../features/sources/reading.py).
- [Report](../features/reports.py), [StudySet, FeedbackBatch](../features/studies.py).
- [Outline](../features/podcasts/writer.py), [EpisodePlan, WrittenSection](../features/podcasts/episode_writer.py), [Series](../features/podcasts/series.py), [CheckBatch](../features/podcasts/checks.py).
- [TranslationBatch](../infrastructure/formats/epub.py), [GlossaryBatch, GlossaryReviewBatch, AlignedBatch, AlignmentBatch, Replacements](../features/books/terminology.py).
- `WholeDocuments` — schema for the [local XHTML probe](../../../tools/probe_epub_translation.py) from the checkout. Developer tools are not included in the wheel.

The SDK and adapters still receive these schemas from Python. Codex/Claude additionally apply the existing strict-schema adaptation in the runner. Find conditional file selection and call sites through `prompts.render` in the source and the `source` field in `catalogue.json`.
