# Named values and preservation of string contracts

Historical result. Support for previous internal formats and profiles was removed on 08.11.2026 ([D034](../decision-log.md)); the archives, baselines, and legacy adapters mentioned here were deleted. These instructions are not a current recovery path.

Historical report. Current requirements and boundaries are in the [specification](../specification.md); decisions and cancellations are in the [Decision log](../decision-log.md). References to later stages describe the state at the time of the experiment.

On 07.11.2026, seven steps of stage 3 and the stabilization check from the single plan were completed.
Scope covered the application, both interfaces, tests, and developer tools. Comparison with the working
snapshot before refactoring shows changes in 122 existing Python files, eight new application modules,
one new test module, and two JS resources. Previous uncommitted changes were preserved; the original
snapshot was copied to a separate temporary directory before edits.

## Owners of values and records

| Owner | Defines |
|---|---|
| `contracts/jobs.py` | Job kinds/statuses, independent stage/first-narration/presentation states, active/terminal/resumable status and workflow-kind groups, job/draft/progress/task records |
| `contracts/text.py` | Providers, default address/port, runner-message roles, connection and settings records |
| `contracts/content.py` | Content language and separate interface language, speaker roles, evidence status, extracted-fragment states, artifact kinds, and source records |
| `features/` | Report kinds, section/term provenance, questions and answer assessments, navigation operations, reading states, writing methods, source-relation kinds, and checking results |
| `infrastructure/speech/contracts.py` | Speech engines, model/voice records, and shared lock/catalogue names. Model IDs and revisions remain data |
| `infrastructure/formats/` | Formats, extensions, and MIME; namespace URIs belong to `epub_xml`, shared filenames/suffixes to their renderer |
| `interfaces/web/state_keys.py` | Fixed keys, pages/sections, editor suffixes, construction of existing project keys, and ordinary string values for Streamlit |
| `prompts/` | Catalogue/snapshot types and named recurring references in `ids.py`; `catalogue.json` still defines allowed templates |

Shared `contracts` import only the standard library. SQLite/JSON fields retain plain strings;
reading unknown historical values neither replaces them with defaults nor requires enum conversion.
There are no new tables, workspace version, queue, SDK domain model, or mandatory material migration.

The existing workspace schema is **6**. The README previously described 5; that description was fixed,
while naming changes did not alter the data format.

## Schemas and identity

A direct Pydantic enum field changes the JSON schema used in the checkpoint hash. Named `Literal`
aliases from enum members were used with original order, subsets, and defaults. All **59 original
schemas** matched the working snapshot; independent SHA-256 values and provenance are in
`tests/fixtures/contracts/`. The baseline is not computed from new constants. Checks also cover plain
string values after saving/opening a job and reading unknown historical values.

The bytes of **64 resources** were unchanged: authored Markdown prompts and their catalogue README,
prompt catalogue/archive, speech catalogue, and four font files. All existing test functions were
preserved. Setup uses domain symbols, while independent serialization expectations and vendor
contracts remain strings.

## UI and findings

Streamlit distinguishes enums from plain strings when restoring selections. Conversion in
`widget_options`/`widget_value` keeps old browser/session-state values; typed values are used in logic.
This is checked by the existing first-settings-open scenario and all interface tests.

Python passes the existing closed-field prefix, trigger name, and divider key into JS through the
existing `data`. In a real browser using the installed wheel:

- the divider changed by keyboard from 50 to 20 and remained 20 after reload;
- text was entered into the active note field without blur or saving;
- reload and return to the note showed `Recovered unsaved changes` with the exact text;
- Save persisted revision 2, and a second Python client read the same text bytes.

Running outside the checkout revealed an extra automatic Streamlit menu from the service `pages/`
directory. The standard CLI and local configuration now explicitly set
`client.showSidebarNavigation=false`. Launch arguments and absence of the menu were checked in a
real browser. The application's own navigation was preserved.

## Checks

| Check | Actual result |
|---|---|
| Original full offline suite | 753 passed / 58.31 s |
| Final full offline suite | **814 passed / 58.46 s** |
| Final wheel in a clean environment outside checkout | **444 passed / 25.69 s**, including worker/guardian, CLI/UI, sources/formats, frozen prompts, and new wire contracts |
| mypy 2.4.1 | 22 shared-contract and annotated-boundary modules; no errors. This is a scoped check, not strict typing of the entire application |
| Static checks | Ruff check/format passed; staged diff checked with four original-resource exceptions listed below |
| Installation | Standard `uv build --offline --wheel`; Python 3.12.13, UI and dev dependencies from lock in a separate venv. Public packages downloaded for the clean install; no weights downloaded |
| Package resources | Contents of 180 wheel files matched the source package; CLI and UI launched outside checkout |
| Dependencies | Only mypy 2.4.1 and its four dependencies were added; existing package versions retained |

Additional targeted runs after migration groups: 158 lifecycle checks, 250 domain/prompts/pipeline,
119 interface/speech, and 145 wire/prompts/progress. They do not replace the final full suite.

When previous untracked files were included in the commit, `git diff --cached --check` reported
original whitespace in `prompts/common/runner.md`, `prompts/podcasts/word_budget.md`,
`prompts/podcasts/word_budget_v1.md`, and `LICENSES/DejaVu.txt`. All four are byte-identical to the
original snapshot and retained for prompt and third-party-license fidelity. Staged diff checking
excluding those four paths passes; there are no new findings.

### Transition from old code

A separate process on the original package prepared two jobs: legacy without a snapshot and new with
frozen prompts. A controlled failure occurred after checkpoint acceptance; both jobs contain manual
r2. Another process from the newly installed wheel resumed the same workspace with inference
prohibited. Both jobs completed, with **0** additional model calls and matching params, manual
revisions, names, and checkpoint bytes.

### Real Codex

Stable **Codex CLI 0.162.1**, standard ChatGPT subscription authentication. An independent installed
worker completed a synthetic `ask` after its submitting process exited. The correct answer about
three Alpha/Beta/Gamma routers was obtained with two exact quotations. Original source bytes were
preserved. After editing, r2 was saved; replay with inference prohibited reused the accepted
checkpoint and preserved the manual text.

Outside the checkout, PATH initially selected a broken Homebrew launcher with ENOENT. The experiment
used existing `BROFESSOR_CODEX_BIN` with the explicit installed stable-CLI path. System PATH, CLI
installation, credentials, provider, and payment were unchanged. Early launch failures are not
presented as generation or model refusal.

## Literals deliberately retained and verification boundaries

- JSON/Pydantic keys and editor JSON paths, including `slides`, remain field names. They do not
  become `JobKind` merely because they have the same spelling.
- Known external CLI flags, SDK fields, XML/DOM/ARIA attributes, and localization messages were
  retained where an extra name would not make the code clearer.
- Catalogue IDs/revisions, prompt/source content, snapshots, and negative or independent checking
  data remain data. There is no complete second registry of allowed prompts.
- Encodings, file modes, separators, and obvious local literals were not automatically extracted.
  Phonetic tables from the adapted G2P and two unchanged DOM components were reviewed without
  rewriting standard values.
- Real Claude/Ollama/TTS and new PPTX/PDF visual acceptance were not run in this refactor. A short
  synthetic question is not acceptance of a book or narration quality; cancelled M4 was not resumed.

QA is outside the repository: `/private/tmp/brofessor-string-contracts-z3ct8l6e/`. It contains the
baseline snapshot, logs, wheel/venv, compatibility manifests, synthetic workspaces, `real-proof.json`,
and `browser-recovery.png`. Test UI/worker processes were stopped. User materials and settings were
unchanged; no push or publication was performed.

## Naming review — 07.11.2026

Following the user's next request, a self-review and independent review by a separate critic were
performed. To isolate the string refactor, the original working snapshot before stage 3 was used:
commit `68ce29f` also includes previously uncommitted product work. Functions, SQL, schemas,
serialized values, operation parameters, and dynamic UI keys were compared; literal searches were
checked semantically.

The self-review fixed these unfinished details:

- Named shared coverage modes, model-settings provenance, and navigation states. Navigation states
  are separate from job states; historical values are read without forced enum conversion.
- Reused name owners for audio-segments, collection ID prefixes, the directory marker, Qwen family,
  stages, question/artifact kinds, namespaces, and UI keys.
- Fixed use of `StageState.COMPLETED` instead of the field name `completed`, `JobKind`/`DocumentFormat`
  instead of artifact kind, and `JobStatus` instead of a stage default. Their spellings matched, so
  these concept-binding errors did not change existing branches but hindered later refactoring.
- Removed unused `EPUB_MIME`, `CONTAINER`, and `MAIN_PAGES`. Removed 39 `widget_options` calls for
  ordinary numbers and IDs, unnecessary address conversion, and recursive arbitrary-structure
  processing in `widget_value`. Scalar enum conversion remains where Streamlit needs it; key formats
  and trailing colons are preserved.

The critic independently confirmed five P3 omissions: audiobook coverage, FINISH dispatch in the
adapter, remaining JSON/EMPTY kinds in UI, remaining Page values, and the local collection-link
protocol. Producer/consumer `ReadingStatus` and `ReadingMode.NARRATION`, `NavigationOperation.FINISH`,
`ArtifactKind`, `UnitStatus`, and `Page` were fixed. `LinkSyntax` and `LinkStatus` belong only to
`collections`, independent of artifact format. The critic found no functional regressions. After
fixes, repeated review concluded with no findings or merge blockers.

| Post-review check | Result |
|---|---|
| Targeted self-check | 254 passed / 30.93 s |
| Independent critic check | 298 passed / 33.08 s; rechecking fixes — 40 passed |
| Final full suite from checkout | **814 passed / 56.91 s** |
| Final full suite from installed wheel outside checkout | **814 passed / 49.95 s**, without skips |
| Static checks | mypy — 22 modules; Ruff check/format and diff check passed |
| Build | Standard offline wheel build; all 180 package files matched source code and resources |
| Unchanged materials | All 59 original schemas and 65 prompt/catalogue/font resources, including the font README, preserved |
| Transition from old package | Legacy/frozen jobs, accepted checkpoints, and manual r2 after a controlled failure; the newly installed package resumed both, **0** new calls, unchanged params/revisions/checkpoint bytes |

The clean environment used Python 3.12.13 and pinned UI/dev dependencies. The first complete test
copy omitted `tools/`: four audit checks failed because developer scripts were absent, and two M4B
checks skipped without FFmpeg. QA setup was fixed: tools were copied alongside tests, and
`imageio-ffmpeg==0.7.0`, already pinned in lock, was installed. The repeated full run above passed;
the product and lock were not changed for these environment errors. This is test audio, not voice
acceptance.

Tests were not removed or added for naming: existing behavioral checks protect affected boundaries.
External field/flag names, original text, localization messages, obvious local literals, and
independent serialization expectations were deliberately retained. There are no new global
registries, constant containers, services, or data migrations. Real models and the browser were not
run in this additional review; previous-stage results are not presented as repeated verification.

Additional-review QA: `/private/tmp/brofessor-named-values-review-wL23oX/` — diff/AST probes, logs of
two full runs, clean venv/wheel, separate synthetic workspaces, and a transition manifest. User
materials and global settings were unchanged.

Review fixes were committed in `bfd722b`; after all checks, branch `codex/named-values` was
fast-forward merged into local `main` from `726c87c` without conflicts. Code did not change during
the merge. Final completion was recorded in the stage documents at merge time; no push or
publication was performed.
