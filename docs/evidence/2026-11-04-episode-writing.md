# Podcast writing: originals, coherence, and script checking

Historical report. Current requirements and boundaries are in the [specification](../specification.md). Decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state on the experiment date.

04.11.2026. After reviewing the critic's findings, the user authorized implementation and a limited comparison. The working tree was preserved, and no commit/push was performed. All real calls used stable Codex CLI 0.162.1 with subscription authorization. API billing was not enabled.

## Product decision

The regular writer remains the default: `dialogue_version=3`, `reading_version=2`. The comparison did not show enough improvement in reliability to change the default. The new chain is explicitly available through “Параметры написания → Расширенная работа с источниками (эксперимент)” (Writing options → Extended source work, experimental) or `podcast --writing-method originals`. This choice freezes `dialogue_version=4` and `reading_version=3` and is inherited by new episodes of the corresponding series. Earlier jobs, prompts, checkpoints, and the public Podcast schema are preserved.

Version 4 supplies the section writer with required originals selected by IDs from the plan and available neighboring context from the same source. Names and locators remain in the notes. The plan includes the listener's goal, relative section weights, source differences, and an option to report insufficient material. The same section response returns bounded editorial memory of what has already been said. It is not factual evidence and does not enter the public script.

The complete section prompt is limited to 90 thousand characters. Required originals are not truncated. A required set that does not fit causes an error, and omitted optional neighboring context is listed explicitly. During correction, the package is recalculated using the actual first response. Both the section's original IDs and every ID already used in the response remain required. This fixes the critic's finding that a large first response could get stuck in a checkpoint when correction used a fixed reserve.

A separate “Проверить сценарий по источникам” (Check script against sources) works for any saved podcast. CLI: `draft check ID --revision N --wait`, report reading: `draft check-report CHECK_ID`. The `check_podcast` job uses the existing worker and pins the revision, source IDs, and the task's current text model. It does not rewrite the script or serve as mandatory authorization for narration.

The check returns `supported`, `issue`, or `needs_context`, the exact disputed claim, and verbatim excerpts. Excerpts pass the existing original-substring check. Lack of support in a bounded package does not mean the claim is absent from the whole book. The report lists reviewed, pending, and non-fitting turns, the sources used, and omitted optional context. An empty findings list is not declared a reliability verdict. Accepted packages survive cancellation/error. Resume uses the same revision and model.

## Limited writer comparison

Reproducible corpus generator and protocol: `tools/compare_episode_writers.py`. The material is entirely fictional, created for this experiment, and contains no user sources. The three documents are an original report, a June clarification, and an independent review. Extraction produced 61 980 characters and 15 fragments. 30 propositions were annotated beforehand: measurement conditions, negations, numerical corrections, an unresolved time discrepancy, checks that were not performed, and limits on conclusions.

Shared notes and a four-part plan were pinned once. The two writers were compared with direct and reversed evidence order, in RU, with a target of 2 415 words. The model choice was the Codex runner's default, identical in every call's settings. The adapter did not record the exact model ID, limiting reproducibility in another environment. The new plan format for the product path was also checked through a separate real call. It correctly distinguished the corrected 12→10 / 5→5,4 from the unresolved 08:00/09:00.

Before revealing the mapping, the critic agent read every unique script and checked it against the originals and IDs from SQLite opened read-only. It did not read the mapping, prompts, or comparison code before recording its verdict.

| Blind file | Method / order | Words | Turns | Confirmed errors in the review |
|---|---|---:|---:|---|
| A | Regular / direct | 2 406 | 93 | None found. The English `passages` remained |
| D | Regular / reversed | 2 368 | 83 | None found. `passages` was spoken, followed by self-correction |
| C | Originals and memory / direct | 2 405 | 83 | None found |
| B | Originals and memory / reversed | 2 405 | 83 | Byte-for-byte identical to C |

The control propositions retained their meaning. In B/C, the review's position accepting the correction was conveyed by distinguishing the correction from the dispute, without separately repeating the reviewer's position literally. The critic did not confirm incorrect IDs or clearly incomplete compound references. B/C received a slight editorial preference: cleaner Russian and somewhat fewer repeated explanations. Every variant overuses formulas such as “учебная интерпретация” (educational interpretation).

These are three unique texts, not four independent trials. The new writer builds context from plan IDs, so reordering the shared evidence did not change its prompts. B used C's checkpoints. The comparison evaluates the whole package of changes, not the separate contribution of memory or originals.

Writing inputs averaged 71 928 characters for the regular episode and 116 560 for the new one: **62% more**. This is input size, not monetary cost or a token measurement. Across the four writer requests, the regular writer averaged about 230 seconds and the new one 225 seconds. Such a small measurement does not establish a speedup. The compressed notes in this corpus are short, while the originals contain many repetitions, so there is no input saving here.

## Checking the report with controlled errors

A separate saved revision contained six turns: three correct turns and three with deliberate errors — a flood-time test, replacing observed load with a proven fifty-year lifetime, and retaining the cancelled number twelve. One real `CheckBatch` detected all three errors and raised no findings on the three correct turns. Every returned excerpt passed the verbatim check. This is a small controlled-defect check, not an assessment of audit precision/recall on real books.

The entire experiment stayed within its 30-call limit: **18 successful generations and one technical sandbox rejection before generation**. Accepted calls were three readings, the shared plan, eight regular sections, four new-writer sections, the new plan, and one audit. Narration was not started. Files: `outputs/episode-writing-2026-11-04/{calls.json,summary.json,review-diagnostics.json,source-aware-plan.json,blind/,corpus/,section-reports/}`.

## Checks and boundaries

The full offline snapshot after the public mode and script checking was **468 passed in 39,76 s**. Unequal section weights and compensation for earlier budget overruns at 20/60 minutes were additionally checked afterward: the complete writer set was **9 passed**. Ruff check/format and diff check were clean. Contracts cover legacy prompts, original scope, required IDs during correction, exclusion of working memory from Podcast, material sufficiency, series inheritance, immutable revision/model, quote validation, partial reports and resume without repeating accepted packages, CLI/UI, and rejection of checks on unsaved text.

A real browser used isolated XDG config/data and a control project on port 8948: report viewing, revision numbers, source excerpts, and explicit selection of the experimental writer. At 390 px, main width equals viewport width, with no horizontal overflow. No console errors were found. The temporary server and tab were closed after QA. Report: `outputs/episode-writing-2026-11-04/script-check.jpg`, narrow screen: `outputs/episode-writing-2026-11-04/script-check-narrow.jpg`.

The corpus intentionally repeats facts. Each document's first large fragments already contain its ten main propositions. The experiment provides little coverage of losing a rare qualification during deep compression. Blind checking was performed by an agent rather than an independent human. The result does not establish improved factual quality, quality of an hour-long episode, or quality with other models and arbitrary materials. This is why the default was retained and the new writer marked experimental. A check by the same provider may also repeat the original error, so the report needs editorial assessment. At the experiment date, M4 listening acceptance remained open. Its later cancellation is recorded in D027.
