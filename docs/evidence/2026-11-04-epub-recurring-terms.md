# Full automatic EPUB run and missing terms

Historical report. Current requirements and boundaries are in the [specification](../specification.md). Decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state on the experiment date.

04.11.2026. P1 continuation after [EPUB 2/3 compatibility and the proofread book](2026-11-04-epub-reader.md). Narration and PDF are not performed in this check.

## Full run of rules 3

The same unchanged W. Stanley original, Project Gutenberg 20214, SHA-256 `8fc5977f1b78f7df2cec62fc1fc08826c622c05fab2c066420bffd944e7d7dcc`. New isolated project: `outputs/epub-rules-v3-2026-11-04/workspace`. Public `translate` CLI created job **`13c4df1fd9964b0c`**, workflow 3 / projection 3, Codex CLI **0.162.1**, `gpt-6.1-sol`, subscription authorization.

Fully automatic processing completed **213/213 blocks in 982,587 s (16:23)**, with six accepted calls (two glossary, four translation) and **54 senses / 135 occurrences**. No manual r1 edits. EPUB SHA-256: `1e8ef3366f141aa3ca301c96e9fa22aca4f76dd5a88e4d9a001fabf4f543a892`. EPUBCheck 5.4.0: **0 errors / 0 warnings**. Independent ZIP/XML audit: resources, structure, and 134 local links preserved.

Independent comparison of all reconstructed XHTML confirmed **43 unchanged ASCII function calls**: 15 square, 13 square_root, 15 cube_root. The check does not use model markers. The QA utility now detects a separate controlled defect that renames a function while retaining the old numbers and XML. Original mathematical inaccuracies were preserved.

All 213 blocks were compared with the original and previous proofread r2. After normalizing whitespace only, **132 blocks matched r2**. The 81 changed blocks were checked additionally. No loss of facts, scale directions, numbers, or units was found. The extra sentence from earlier block 117 did not recur. Remaining issues included local grammar (`при 0 градусов C`), punctuation at an original line break, and inconsistent naming of the moving pointer.

The main limitation proved to be glossary extraction: the new automatic selection omitted indicator, runner, slider, and hair-line entirely. Thus workflow 3's fix — supplying the full relevant glossary — cannot help a missing sense. The 54/135 counts describe selected senses and bindings, not terminology completeness. Automatic r1 was preserved as a diagnostic result and was not replaced by a proofread revision.

## Checking recurring terms

Workflow **4** adds a bounded stage after primary glossary extraction or reuse. Local code finds words/phrases repeated in different blocks that are absent from known names and surfaces. These are model candidates, not automatically assigned terms. Up to 32 frequent candidates are examined. Contexts are selected from the beginning, middle, and end of their occurrences. Common function words are excluded. The actual prompt containing accepted senses and occupied source ranges stays within the existing 40 000-character limit.

The model decides which candidates denote professional concepts, distinguishes senses, and links additional occurrences through exact original quotes. Earlier user and automatic senses cannot be overwritten. Overlapping occupied ranges, invented quotes, and references outside the package are rejected. Unexamined word matches are not automatically assigned a sense. This improves the glossary without promising exhaustive anchors or global replacement.

Versions 1/2/3 and their prompts/checkpoints are preserved. New jobs and regenerate use workflow 4. EPUB projection remains 3. Control regenerate **`79210435e5b04f88`** pinned the preceding run's r1 and reused its 54 senses / 135 occurrences, without repeating the first two calls. Its results are recorded separately from the workflow 3 control.

Offline checks include a missing recurring component name, preservation of user translation, rejection of invented quotes/overlaps, and earlier recovery/CLI/UI contracts. A fake replaces the expensive model boundary. Real core code checks source spans and glossary merging. A clear UI stage was added: “Проверяем повторяющиеся термины” (Checking recurring terms).

The real review of 50 original contexts accepted another **22 senses / 160 occurrences**: slider, runner with alias indicator, hair-line, body, indices and scales, roots/powers, the decimal separator, and operations. The previous 54 senses / 135 occurrences were preserved. The total glossary is **76 senses / 295 occurrences**. English power is now represented separately as exponentiation and physical power. This is one additional model call, not a repeat of the first two extractions.

## Recovery and binding checks

Run 4 stopped twice in an unaccepted package after 34 completed blocks: first due to number validation, then due to binding-quote uniqueness validation. No finished file or draft with incorrect bindings was published. Raw responses from rejected calls were not retained. Their specific contents are not reconstructed from the error text alone.

A separate check found a numerical-validator defect: `.34` was interpreted as `34`. The validator could therefore reject equivalent `0,34` and miss a lost decimal point. Leading-separator parsing and normalization of only the optional zero/local separator were fixed. Changes to magnitude or sign and loss of a trailing significant zero remain rejected: `.340` cannot become `0.34`. Generation prompts and accepted revision numbers were unchanged.

One bounded clarification of invalid bindings was added for workflow 4. First, the entire translated text, numbers, markers, and block IDs are validated. Only blocks with unconfirmed links are then identified. A separate schema accepts only IDs/targets, without a translation field. The model receives immutable translated text, original contexts/senses, rejected hints, and the error. After clarification, every link is validated again. Correct blocks and all text wording are preserved. A number change is not sent for “link repair”. A response still unconfirmed after the single clarification stops the package. There are no unlimited retries. The outer checkpoint is accepted only after full validation. An accepted separate correction has its own checkpoint as well.

The accepted glossary and first text package survived both stops. The first resume was initiated through the real UI. Closing the tab and server left the independent worker running. This exposed and fixed navigation from MRU to a CLI project outside the catalogue: the UI now opens an existing valid workspace by path, preserving its tasks, instead of reporting Unknown project. The check creates no empty folder for an inaccessible path.

Controlled tests check absence of repeat inference for accepted review/translation packages under fault/resume, unchanged text after link repair, no publication after failed clarification, and prohibition on using clarification to change numbers. Real pre-resume checkpoints were recorded in `resume-qa.json`. Interface: `ui-resume.jpg`.

## Workflow 4 result

Job **`79210435e5b04f88`** completed: **213/213 blocks**, r1 without manual edits, **76 senses / 295 occurrences**. Final file: `outputs/epub-rules-v3-2026-11-04/stanley-ru-automatic.epub`, SHA-256 **`c68b546f1480211fa98f19b0aaf81e4059b1ad125c5e23e79dfcbcc32d71b34b`**. Six checkpoints were accepted: one additional glossary review and five text packages. Including the two rejected responses, this makes eight application-to-runner calls. **1767,433 s (29:27)** includes errors, stops, code fixes, and resume. It is not a measurement of continuous model performance.

After the last resume, all fresh hints were valid. Binding clarification was not needed within the final run. To check the real runner, a copy of accepted block 97 with one deliberately corrupted quote was used separately. One schema `AlignmentBatch` call in **12,435 s** restored six verifiable bindings while preserving translated text byte-for-byte. Data: `alignment-probe.json`. This check did not change the job, its checkpoints, or EPUB. The continuation had 15 application-to-runner calls in total: six workflow 3, eight workflow 4, and one controlled clarification. This is the call count at the application boundary, not a report of internal CLI execution or billing.

Hashes of the two checkpoints accepted before the stops matched after resume. The background task completed after the real UI tab and server were closed. Rewriting a checkpoint file's service timestamp while reading the cache is not repeat inference. Preservation was confirmed by content and an offline controlled-failure test.

EPUBCheck 5.4.0: **0 errors / 0 warnings**. Independent reconstructed-XHTML check: **43 original ASCII functions, 789 numerical values, 134 internal links**, 66 unchanged resources, including **62 images and 2 CSS files**, with no findings. The utility separately detects a controlled lost decimal point and renamed function. Formal validity, numerical checking, and semantic proofreading are tracked separately.

All 213 blocks were checked. After normalizing whitespace and decimal-separator notation, 139 matched workflow 3, and the other 72 were additionally reviewed. Component vocabulary was made consistent throughout: runner/indicator — “бегунок”, slider — “движок”, hair-line — “визирная линия”. Example meanings, scale directions, negations, numbers, and units were checked against the original, with no losses found. The author's original arithmetic/dimensional inaccuracies were not corrected. Some grammatical roughness remains: “при 0 градусов C”, compound-unit declension, and punctuation at an original line break. Automatic r1 was preserved without editorial polish as a quality control result, not publisher-level proofreading.

The final ZIP itself was opened in EPUB.js: descriptions and calculation examples, the middle and end of the book, and NCX navigation to the retained license were viewed. Main-text illustrations: **61/61 loaded**, none broken. The separate cover image was also retained according to the ZIP audit. In a narrow **370 px** book area, text can be paged through and read, and illustration width does not exceed **340 px**. Screenshots: `reader-consistent-terms.jpg`, `reader-end.jpg`, `reader-narrow.jpg`. Source context in the editor now displays protected functions/code while preserving earlier serialized blocks.

A selection of **221 offline tests** passed for EPUB, terminology, recovery, worker, and CLI/UI. Two independent-audit tests and five translation-interface tests passed separately afterward, including two new regressions: loss of a leading decimal separator and visibility of mathematics in the original quote. This totals **223 unique cases**, accounting for overlapping selections. Ruff check/format and diff check passed. No new dependencies, models, global settings, or database migrations. Both jobs completed, and temporary QA servers and the worker were stopped.

One short but complete technical book was checked, not large textbooks or every language pair. Frequency review and anchors remain sample-bounded. Their counts do not establish completeness or correctness of every professional sense. PDF is not yet implemented, and listening acceptance was not resumed.

## Download: application and browser tool

Finished download buttons pass `on_click="ignore"`: downloading a saved file does not require a page rerun. All 52 targeted UI/interface checks passed. This prevents unnecessary UI reruns but is not declared the cause of the earlier delay.

Another real download through the in-app browser, with explicit 10 000 ms timeouts for event/path and 25 000 ms for the tool call, returned only after **1152,053 s**. It produced `translation (1).epub`, 3 654 693 bytes, with the source proofread r2 SHA. The path stage after the event itself took about 6 ms. Thus the tool's wait limit did not actually work. The earlier standard media endpoint served the same bytes in 0,075 s. Browser-stage delay is kept separate from worker time. The exact external cause is unestablished.

This wait should not be repeated in QA. Only the in-app browser and MCP Apps are available. Chrome/another ordinary browser is not connected. File receipt and integrity are confirmed, while normal user download time remains unverified. Tool report: `download-instrument-qa.json`. Global settings, the main project, speech models, and Ollama were unchanged.
