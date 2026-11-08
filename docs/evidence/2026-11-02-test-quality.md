# Assessing test usefulness

Historical report. Current requirements and boundaries are in the [specification](../specification.md); decisions and cancellations are in the [Decision log](../decision-log.md). References to later stages describe the state at the time of the experiment.

02.11.2026. An independent subagent reviewed the offline suite, then changes were made and checked locally. This check used only synthetic materials and substituted external boundaries; real models, subscription CLIs, and remote Ollama were not run.

## What was removed or rewritten

| Weak check | Protection retained |
|---|---|
| Exactly 20 examples and a fixed status set in the control corpus | Gold quotes really exist in source documents; answer statuses are checked in scenarios |
| Two identical mixed RU/EN PPTX files with different language labels | One real bilingual file, saved and reopened |
| Mandatory RECTANGLE/CHEVRON/DOWN_ARROW shapes, arrow counts, and a complete ban on images | Editable labels and tables, reading order, readable sizes, no label overlaps or page overflow |
| Duplicate native-PPTX test | Checking without an office application/external processes is combined with checking a real PPTX, notes, and OOXML bullets |
| CLI `--wait` calls a particular helper | Actual saved `interrupted` state, JSON, and nonzero exit code |
| Repeating the entire address grammar at every external layer and separately checking a URL string | Full grammar is checked once; service and CLI check refusal before enqueue/connection, and the HTTP contract checks real addresses and boundary ports |
| Separate check of DTO defaults for old bullets | Old drafts go through actual PPTX building |

Exact official CLI flags, external-format rules, provenance, concurrent editing, process termination, recovery, and the absence of unnecessary model calls were retained: these are requirements, not incidental implementation details. This criterion was added to `AGENTS.md` for subsequent changes.

## Important new scenarios

- Queue a PPTX from revision r1, save r2, then execute the job: the text, notes, references, and registered revision of the finished file must remain from r1.
- Encoder failure, timeout, and cancellation after partial MP3 creation: preserve the previous result, remove temporary files, and reuse accepted audio segments on retry.
- HTTP 307 from Ollama: source text is not forwarded to another server.
- Real F5 adapter with a substituted upstream library: separate host/guest voices, exact transcripts, pinned local checkpoint/vocab/Vocos, and settings. Changing the user sample after submit does not replace the saved sample. The test prohibits ASR and network access.
- A voice change between input pinning and enqueue, changes only to transcript or settings, and concurrent retries sharing one explicit key. CLI and UI retries with the same inputs return one job; a new explicit key creates a separate job.

A real defect was found and fixed: the UI calculated the narration key separately from parameter pinning. Another client could change a voice between those actions, causing a job with one set of samples to be stored under another set's key. The service now calculates the key from already pinned inputs. A descriptive catalogue change does not trigger re-narration. An explicit key retains the first accepted snapshot even when the original user sample has been deleted.

## Checking the strength of the new tests

Temporary code mutations were introduced one at a time and reverted after each run. Each of the six defects was detected by the corresponding test:

1. Replacing the pinned PPTX revision with the latest revision.
2. Allowing HTTP redirects carrying source text.
3. Publishing a partial MP3 before validating encoder output.
4. Using the host voice for the guest in F5.
5. Excluding speech settings from render identity.
6. Rereading mutable preferences instead of using the saved snapshot.

Reverse check: replacing rectangular blocks with rounded ones does not break `test_slides.py`. Useful checks remain, while a particular decorative style is not fixed by tests.

## Result and boundaries

Original suite: 362 passing cases. After removing duplicates, reducing repeated matrices, and adding scenarios: **355 passed** in a clean core + UI environment without optional TTS dependencies. Ruff passes. Case counts and line coverage were not goals in themselves. Logs and controlled-mutation results are saved outside Git in `outputs/test-quality/`.

This checks software contracts. It does not establish pronunciation quality, the semantic accuracy of model answers, or presentation appearance in a particular editor; real media and integrations were checked separately in earlier experiments.
