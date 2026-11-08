# Written reports: comparison and working guide

Historical report. Current requirements and boundaries are in the [specification](../specification.md), and decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state at the time of the experiment.

05.11.2026. Following the user's instruction to continue the plan after the KISS cleanup, P2 was implemented: one editable report with `comparison` and `guide` templates. Inputs are a question or goal with context, the existing sources, language, and text model. No separate model settings, servers, queues, or dependencies were added.

## Implementation

CLI `report` and the “Письменный отчёт” (“Written report”) form use shared `service.submit`. The same Pydantic Agent reads connected directories. The report receives original fragments through the existing `questions.prepare`, with bounded search for large material and a saved coverage report. A summary does not replace primary evidence. The writer receives the actual source selection.

A section has text, an origin label, references, and exact quotes. “По источникам” (“From the sources”) is separated from “Адаптация и выводы brofessor” (“brofessor adaptation and conclusions”). Every quote and the language are checked before checkpointing, and quotes are checked again before an edit is saved. A wrong quote in one section cannot be covered by a correct quote from the same fragment in another section. These checks establish verbatim integrity and reference scope. Meaning and correctness of conclusions are assessed separately.

Each saved revision receives `report-rN.md` with sections, labels, source names, locators, and original quotes. The file is written locally using a temporary path and atomic replacement. No separate model or render job is needed. The UI shows ordinary section fields and section ordering. Advanced JSON permits changing quotes together with references. Shared history, task models, and regeneration retain previous results. Resume uses checkpoints and the current saved revision, preserving user changes.

## Control corpus

Three self-authored synthetic MIT notes in ignored `outputs/report-probe-2026-11-05/sources/`, without a personal vault:

- Alpha and Beta define retry after an explicit temporary failure identically. In Alpha, reliability means retaining an acknowledged record after a process restart. In Beta, it means the proportion of successfully completed requests.
- Both current instructions concern protocol P, one node, and 100 requests with stable request IDs. Alpha requires enabling retries, Beta requires disabling them. Neither has priority. This is a genuine contradiction.
- Both single-node notes report 12 ms as an observation. Cluster reports 35 ms on four nodes. Observations are not stated as mandatory settings. Cluster retry policy is not recorded, and power loss was not tested.
- Alpha requires checking the ID log for duplicates and stopping if an ID is missing. Beta requires saving the configuration and ending the trial if a request is unfinished. These are the original recommendations used to check the guide.

## Real verification

Official Codex CLI **0.162.1**, requested model **`gpt-6.1-sol`**, ordinary ChatGPT authorization. The same worker and production workflow were used, without paid API fallback. Parameters, ledger, and full results are in the ignored QA directory.

Comparison **`459c53831ec94891`** completed in **68,216 s**, **2 NavigationStep + 1 Report**. Three originals were read, and five sections and 16 quotes were saved. Original facts and final sections were checked in full:

| Check | Actual result |
|---|---|
| Shared and differing definitions | The identical retry definition and different meanings of reliability are described explicitly |
| Contradiction | Enable/disable under the same conditions is identified as an unresolved conflict. No winner is invented |
| Different conditions | 12 and 35 ms are not called a conflict. One node versus four is stated |
| Insufficient data | Absence of a power-loss test is not turned into a claim of data durability |
| Authors' recommendations | Checks and stop conditions are restated with their original limitations |

All section texts and quote strings appear in the actual **8 735-byte** Markdown. Hashes of the three source files matched before and after. This is one small annotated corpus. It does not establish quality on arbitrary books.

The first directory-based guide run **`ddf6f67597014f24`** failed: its initial `NavigationStep` did not return from Codex within 600 s. Resuming the same job with the same inputs and a trial limit of 180 s per call also timed out. A control using a shorter wording of the same goal, **`e01b85879a7946f6`**, timed out at the first step after 90,270 s. The reason for the delay was not established. No draft was published, and sources were unchanged. Failures were saved in `guide-timeout.json`, `guide.json`, `guide-catalog-short.json`, and ledgers. They are not counted as successful verification of guide navigation.

**Subsequent continuation on 05–06.11.2026 resolved this observed failure.** A plain-transport control timed out again, while JSONL returned a step for the same request. The production runner received the official `--json` flag while retaining final-JSON reading from `-o`. The earlier `ddf6f67597014f24` completed in **83,021 s / 3 calls** with the same sources/model. All five sections and Markdown were checked. The internal CLI cause was not established. See [diagnostics, ledgers, and conclusion boundaries](2026-11-06-learning-and-audiobook.md#codex-hang-during-p2-navigation).

A separate guide, **`862293dc7d254a08`**, succeeded through ordinary import of the same three files, without directory navigation. The official CLI and model were unchanged. **66,523 s / 1 Report**, five sections and 23 quotes. Every section was checked: author recommendations and adaptation are distinguishable, the retry conflict is retained, and the 12 ms observation is not made a mandatory setting. Additional checks are identified as application suggestions. The guide includes preparation/trial order, diagnosis, stopping, and missing conditions. Reliability definitions are not conflated, and untested power loss is not presented as proven resilience. The model retained a conservative caveat about reading completeness. The application separately shows actual extracted-fragment coverage.

The actual guide Markdown, **16 141 bytes**, contains every section text and quote string. Sources match the saved originals byte for byte. `guide-import.json` and `guide-import-calls.json` record this independent run. This verifies a guide over imported files, without claiming success for the three navigation requests above.

## Checks and limitations

The full offline suite: **605 passed**. Ten report cases were added: both templates, per-section quotes, wrong language and unsupported source labels, an empty directory, recovery after publication failure without repeated inference and with the user's edit preserved, CLI/UI parity, and ordinary-field editing. A controlled fault separately checks that the selected directory-fragment count is not presented as the whole document's size. The total is explicitly unknown for that selection, while ordinary import has the original counts. The real model is replaced only at the `executors.generate` boundary.

Real Streamlit checks covered the report form, reading, origin labels, exact quotes, section editor, and downloadable Markdown. The editor view is saved as `editor.jpg` in the QA directory. AppTest saved a new revision, and CLI read the same data. Duplicate quotes were removed from the shared display while retaining their per-section associations. The full suite passed again after clarifying partial-reading context. Ruff check/format, diff check, and offline wheel build passed. The new module was included in the wheel, and QA data was not. Temporary Streamlit 8563 was stopped.

Real reports through Claude and Ollama were not checked. The standard `doctor` for Claude 2.1.317 still ends with an auth-check diagnostic and exit code 1. No ordinary browser was connected, and the old long download wait was not repeated. The presence of quotes does not establish model conclusions or their applicability, and bounded search does not guarantee completeness. Large corpora and new audio/PPTX were not checked in this stage.
