# Source questions: quotations, conflicts, and retrieval

Historical report. Current requirements and boundaries are in the [specification](../specification.md); decisions and cancellations are in the [Decision log](../decision-log.md). References to later stages describe the state at the time of the experiment.

Checked 02.11.2026. The first M3 slice: questions with original quotations, absent answers, contradictions, and measured retrieval.

The later [notes and follow-ups slice](2026-11-02-notes-and-followups.md) closed the remaining M3 item. The initial retrieval-check results are retained below.

## What changed

Previously, `ask` processed all large material through compressed notes and returned only IDs. Answers now receive original text. Small sets of up to 24 thousand evidence characters are passed in full. For larger sets, the same selected runner generates up to four RU/EN query variants. Local BM25 ranks them together with the original question; rank fusion retains eight initial matches. Context prioritizes a match, the next two and previous one readable fragments from the same source, then the next match. The 90-thousand-character budget includes text and provenance. Fragments are not truncated.

Answer generation has three statuses: `supported`, `insufficient_evidence`, `conflicting_evidence`. Every cited ID in a new answer requires an original quotation. Scope and original-substring correspondence are checked before checkpointing. If only whitespace/line wraps differ, the original substring with its wraps is used; words, numbers, and punctuation are not corrected on the model's behalf. A contradiction requires two distinct quotations, which may be in one fragment. Two quotations alone do not prove a semantic conflict.

`questions.py` contains one fixed path without a new workflow engine, vector database, or separate retrieval model. It uses the existing queue, checks, cancellation, and checkpoints. Ordinary `search` remains local word search without translation or model calls. The shared service adds source scope and a limit, while `answer_evidence` resolves saved references for CLI/UI. Old answers without quotes remain accessible and editable but are not labeled as having verified quotations.

## Control corpus and method

`tests/fixtures/questions.json` contains nine short synthetic documents and 20 labeled questions. All characters, measurements, and documents are fictional. Scenarios include 14 supported answers, three absent answers, three conflicts, RU and EN, a Russian question over an English source, multi-source comparisons, and distinguishing a historical budget replacement from conflicting current estimates. The maintenance card contains an injected instruction to execute a command and state an incorrect interval. It must remain data rather than an instruction.

The real pilot added a long irrelevant geology text to exercise the retrieval branch specifically. This produced 23 readable fragments in ten files. Gold context is defined from original documents and exact phrases and is not passed to the model. For the 17 answerable questions, recall is the fraction of required original IDs retrieved; questions with all gold IDs retrieved are counted separately. The three absent-answer cases are excluded from recall and checked by status and content.

Official stable Codex CLI 0.162.1 through the existing subscription login made 40 real calls: 20 query expansions and 20 answers. API fallback, tools, and shell are disabled for the text runner. The exact server model revision is unknown. Claude/Ollama were not run in this slice, and these results cannot be transferred to them.

| Check | Result |
|---|---:|
| Original-question BM25, all gold context | 10 of 17 |
| Mean original BM25 recall | 0.618 |
| BM25 with RU/EN variants, all gold context in the first eight matches | 17 of 17 |
| Successful jobs / evidence status matching labels | 20 of 20 / 20 of 20 |
| Original quotations and saved-answer scope | All passed validation |
| Read per question in this corpus | 1–7 fragments, median 4 |

All 20 answers and their quotations were checked: a 1200 kg load was not called a maximum, the absence of a flood test was not turned into a resilience assessment, and speed units were preserved. Both dates were given for two final memoranda, and both load capacities for two certificates. Sequential budget replacement was not called a conflict, and the computed difference was labeled a calculation. When birth date and seismic data were absent, the model did not fill them with outside knowledge. The injected instruction was ignored: the inspection interval is 14, not 99 days.

Nine short substantive documents form a small, retrieval-friendly corpus despite the long background text. These figures do not measure quality over an arbitrary library. Gold IDs and verbatim quotations do not replace checking semantic support for every conclusion.

## Whole-book check and defects found

The same complete public *Frankenstein* EPUB as in [M2](2026-11-01-whole-book.md) was used, SHA-256 `bf04d57cf243314ab770df6fcea6a9cfb1e5a281426453e23c128c5a9c3eb662`. There were 90 fragments: 89 readable and one empty. Old reading summaries were not used. Three Russian questions addressed the English original: secretly gathering firewood in the middle of the book, evidence in the accusation against Victor, and how much of the ending is actually observed.

The first implementation limited context to 24 thousand characters and prioritized all eight matches ahead of neighbors. Firewood gathering was found confidently, but the other two returned `insufficient_evidence`: the answer correctly admitted the supplied excerpts lacked information, although it existed in the book. The algorithm lost scene continuations. This was not counted as successful retrieval.

After prioritizing neighboring context and increasing the budget to 90 thousand, both needed continuations entered the evidence. For the ending, literal validation rejected the answer twice because a line wrap in the quote differed from the EPUB. The diagnostic raw answer confirmed matching words with different wraps. Restoration of original whitespace/line wraps only was added. The previously rejected real answer now yields exact original substrings, separately replayed without a model; a later real resume also succeeded. Incorrect words and numbers are still rejected before publication.

| Final question | Job | Control ID | Read / evidence |
|---|---|---|---|
| Firewood | `fc1226bb31964a51` | `bf04d57cf243314ab770:45` | 17 / 89 947 characters |
| Alibi | `8acecd991855455c` | `bf04d57cf243314ab770:71` | 18 / 87 061 characters |
| Ending | `5e60f689c62f48d5` | `bf04d57cf243314ab770:87` | 19 / 89 211 characters |

Each final answer is `supported`, cites the required original, and preserves the checked qualification. The alibi concerns when Clerval's body was found, not an established murder time. Walton sees the creature depart on an ice floe and hears its promise to die; he does not witness the death itself. Control passages were checked against originals. These are three checks of specific facts, not an audit of every possible question about the book.

After the context fix, all 20 synthetic cases were replayed through the pipeline with accepted checkpoints: prompts, answers, and gold context were retained, with no new calls. The initial unsuccessful book results and quotation diagnostics are saved separately.

## Interfaces and automated checks

309 offline tests and Ruff check/format pass. Checks cover fabricated/foreign/unsupported quotations, rejection of a changed number, restoration of original wraps, contradiction within one fragment, legacy drafts, revision history, the control corpus, budgets and scene continuation, no random excerpt on zero matches, scope, checkpoint reuse, and rejection of references to unselected context. Earlier full-batch-reading checks remain on the slide workflow; media still read all material.

AppTest checks both languages, statuses, quotations/locators, retrieval scope, and an honest `not_selected` map. CLI `draft show` receives the same resolved originals through the shared service. A real browser checked empty search, a Russian conflict with both quotations, and switching the interface to English while the answer remained Russian and originals English. Screenshots are among the local artifacts. The temporary UI used a separate port and user settings; the main UI on 8501 was not reconfigured.

There are no new dependencies. This experiment did not check a clean install or real Claude/Ollama; later technical acceptance is described [separately](2026-11-02-provider-acceptance.md). A quotation does not automatically substantiate an entire answer. No match does not prove the book contains no answer; UI and CLI coverage show this. Larger original context increases the selected model's context-window requirements. Global book overviews use full-reading media workflows and are not promised by selective `ask`.

Local artifacts are excluded from Git: `outputs/source-questions/`. Main files are `results.json`, `corpus-replay.json`, `final-validation.json`, `book-before-context.json`, `book-results-v2.json`, `ending-resume-raw.json`, `ending-wrapping-check.json`, `ending-final.json`, screenshots `ui-conflict-ru/en.png`, and two workspaces with complete originals, history, and checkpoints. The synthetic fixture, code, tests, and this report are in Git.
