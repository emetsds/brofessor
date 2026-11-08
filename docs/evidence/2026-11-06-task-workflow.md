# Task creation, first narration, and durable execution progress

Historical report. Current requirements and boundaries are in the [specification](../specification.md), and decisions and cancellations are in the [Decision log](../decision-log.md). References to subsequent stages describe the state at the time of the experiment.

06.11.2026. Work followed the instruction “Действуй по плану шаг за шагом” (“Follow the plan step by step”).
The initial working copy already contained a large uncommitted slice, whose changes
were preserved. No commit, push, publication, or changes to user defaults were performed.

## User workflow

Successful project creation/opening closes the dialog by refreshing the whole application.
On error, the form and values remain. The open project's header has three buttons:
“Новая задача” (“New task”), “Добавить источник” (“Add source”), and “Удалить проект”
(“Delete project”) with the existing confirmation. A folder name opens its catalogue,
while its arrow expands tasks only. The separate “Открыть проект” (“Open project”) row
inside a folder is gone. Several folders remain independently expanded.

The project header and Sources open the same file/folder dialog. For files, it shows
formats and size limit, selection, one add command, and an outcome for each file.
Partial success and duplicates are retained while fixing errors. Replacing an already
added file with new bytes is not overlooked. Success closes the dialog and refreshes
sources. A folder is connected by path only, without a model call. Obsidian is explained
as a specific kind of folder. The native uploader remains, with its labels translated.

“Создать задачу” (“Create task”) describes the selected result and opens that specific task.
The user-provided task name is separate from the full request and material title. An empty name
receives a short value without a model. Renaming works in CLI/UI without changing
revisions. Global search shares the catalogue's prefix logic and result row, groups
tasks by project, finds empty projects, and does not write MRU while typing.

After the first script is saved, a new podcast automatically continues to narration
in the existing worker. Shared SQLite pins policy, first revision, and speech snapshot.
New episodes copy the series policy and its task's current models. Repeated requests
retain initial inputs. Manual and automatic renders converge on one key.
Speech failure does not undo script readiness. Missing weights/runtime show a reason
and a Settings link, without automatic download. Continuation cancellation survives
reopening and is cleared by explicit Resume.

Edits require saving and explicit “Переозвучить” (“Revoice”). Old audio remains available,
with its revision labeled beside the actions. “Редактировать” (“Edit”) and “Переозвучить”
(“Revoice”) appear in that order on one row. The script starts collapsed. Pagination
has two arrows and a small text field. An invalid number does not change the page.

The main progress panel shows completed, current, and upcoming stages, optional branches,
and stage-local counter units. Timing history persists in `job_stages`, separately
accounting for queue and paused time. During an external call, the worker records an
active interval every second. After a crash, only recorded time counts. An unknown tail
and an older task's prior history are not reconstructed. A long wait is not labeled
a hang. The panel collapses after success.

## Shared-service and interface checks

Contracts check retention of initial revisions, models, and sources; cancellation and
resume; absent model/runtime; simultaneous manual and automatic rendering; recovery
before/after enqueue without a second text or audio result; and inheritance by new
episodes of a future model without changing an earlier episode. CLI `--wait` also
follows first narration, reports its failure, and returns finished-audio artifacts.
It checks a real WAV with PCM frames, not merely the existence of a file.

Controlled clocks check stage boundaries, a stopped worker, current and completed
pauses, repeated passes, omitted summarization, dynamic local scope, and identical
CLI/UI reports. The task name survives before/after generation, edits, renaming, and
reopening the workspace. Search is checked on an empty project, related answer,
original request, deletion, case, and multiple prefixes without changing MRU.

AppTest checks task creation/opening, transition to background work from the new-task
form and Sources without losing an unsubmitted request, script availability when
audio is blocked, Settings navigation without starting a download, and retention of
old revisions/cache. A cancelled audio/file operation in the main panel is checked
with continuation of the same job. Pagination checks manual numbers, errors, both
bounds, arrows, and fewer turns after explicitly loading a new revision. Import
checks partial success, duplicates, retries, replacement content, and retention of
an invalid path.

Earlier manual-render and voice-reference checks use explicit `auto_audio=False`,
preserving their cache and pinned-voice protection. The no-runtime check now expects
a disabled narration button, retaining the earlier protection against launch.
The UI/CLI follow-up check accounts for the new task's separate name.
No decorative tests for exact dimensions or fixed widget counts were added.

## Real process and browser

All data is in `/tmp/brofessor-plan-ui`, outside the repository. The source is a
self-authored synthetic bridge-test observation. Real Streamlit, SQLite, OS-lock,
worker, checkpoints, segment cache, and FFmpeg ran. At expensive boundaries, synthetic
answers and sinusoidal PCM replaced text/speech model calls. This checks process and
interface, not writer quality or a real voice.

In the first job, forced `os._exit(75)` occurred after audio enqueue but before saving
its relationship. Starting a new worker recovered the same render. The script and
user-provided name were unchanged. The first turn was then edited in the browser,
r2 saved, and revoicing explicitly launched. Its cancellation/resume preserved the
ID. The text boundary was called once for this task. r1 segments had
`reused=[false,false]`, r2 had `[false,true]`, and previous files remained.
Audio jobs: r1 `0f83c92db082484e`, r2 `4be072442274489b`.

A separate job with a controlled 20-second response wait showed a blue current stage,
its own section counter, heartbeat, and model wait in the browser. After completion,
history retained 20 seconds of execution separately from 13:40 queued while the test
worker was stopped. Names and results survived a UI restart.

Browser checks ran in IAB at 1280×720 and 390×844, in light and dark themes:

- Creating a project closed the window, opened the project, and showed confirmation.
  Connecting a folder and adding a file closed the shared dialog and saved the source.
- Global search updated on “пус”, “пуст”, and “ПОЛ ПУТ” without Enter. It found an
  empty project and a task in another project. Focus stayed in the input, and the
  full-page-run counter stayed at 16 while the query changed.
- Clicking the folder arrow and pressing keyboard Space expanded several folders
  without a full rerun. Dragging the divider changed the proportion from 55% to 44%,
  with the run counter still 9. Home/End checked 15%/85% in the narrow dark sidebar;
  both sections were distinct and scrollable.
- On a 44-turn script, manually entering 6 opened turns 41–44 and disabled “Вперёд”
  (“Next”). 99 retained the last page and showed an explanation. “Назад” (“Previous”)
  returned to 5. The pagination row fit completely at 390 px. Progress polling did
  not reset the number or collapse state.
- A real narrow-screen collapse of sidebar-header columns was found: Streamlit set
  each column to `min-width: calc(100% - 24px)`. Local column sizes were applied to
  brand/search/settings and the Projects row. After the fix, widths were
  156/36/36 px, outer scrollTop was 0, and the logo and both icons shared one row.
- Checked document/viewport widths matched: 390/390 and 1280/1280. Stage time wraps
  below the title on a narrow screen. Header buttons wrap to a new line.

After the final narrow-header edit, 27 UI checks were repeated separately. Tabs were
closed, viewport reset, and test servers 8518/8519/8520 stopped. Test data, logs, and
screenshots remain outside the public repository.

## Boundaries

The gray bar over buttons in the user's original browser was not reproduced.
The checked interface had no horizontal overflow, but that does not establish the
cause of the original screenshot. Investigation of the gray bar's cause was later
cancelled under D027. Ordinary Chrome/another external browser was not connected to
the tools. Repeating the earlier hanging browser-download wait was unnecessary.
Selecting a file through the external filechooser took about 30 minutes for 113 B.
The reason for the tool delay was not established. Import, file content, and the
shared dialog were checked, but that external wait does not measure application speed.

On 06.11.2026, official Claude Code 2.1.317 again returned `loggedIn=false`,
`authMethod=none`, `apiProvider=firstParty`, exit code 1. Real Claude navigation was
not checked in this experiment. Subsequent [official login and real verification](2026-11-06-claude-authentication.md)
are described separately. Real Codex/Ollama/TTS, new weights, full episodes, and
listening acceptance were not run in this work. Personal M4 acceptance was later
removed from current scope under D027.

Screenshots: `/tmp/brofessor-plan-ui/interface-light.jpg`, `progress-dark.jpg`,
`progress-dark-390.jpg`, `sidebar-dark-390.jpg`. Full-suite log:
`/tmp/brofessor-plan-tests.log`. Synthetic voices and answers are not test data for
assessing content or listening quality.

## Final checks

Full offline suite: **659 passed in 74,28 s**. After the final `auto_audio` type check,
**50** first-narration, series, task, and CLI-wait cases passed separately.
Of these, successful `--wait` checks published WAV and readable PCM frames, while
the next series episode uses the currently selected model without changing an
already created episode. After fixing the narrow header, **27** UI checks passed.
A subsequent full run includes that fix.

`ruff check .`, `ruff format --check .` (**165 files**), and `git diff --check` pass.
`uv lock --check --offline` confirmed the lock for 221 packages. The wheel was built
offline. Contents of seven changed modules were compared with the checkout, and
they were imported from an unpacked package outside the checkout. CLI group `task`
is available. `upload_labels.js` is included, while tests/tools/outputs directories
are not in the package. No dependencies were added in this continuation.
These checks do not replace the real model generation and listening acceptance
specified in the boundaries above.

## Repeated screenshot: the sidebar project row

On 06.11.2026, the user showed misaligned arrow, folder, and `demo` name.
The problem was reproduced in isolated UI: the native expander row was 40 px high,
while the overlaid name button was 32 px. Expanded content added a bottom border.
The arrow and name centers differed by 4 px.

A project-row key was extracted in `ui_navigation.py`. Local CSS in `ui.py` sets
a shared 36 px height and one selected-project background across the whole header.
The arrow occupies a separate 36×36 area, and the name takes the remaining space.
The expander label is retained for accessibility. Borders and excess inner padding
were removed. The folder icon does not shrink, and long text is ellipsized.
Main content was unchanged.

Real IAB: light and dark themes at 1280×720 and 390×844, `demo`, a second name, and
a long Russian name. Rows had no overflow, both regions were 36 px high with the
same top. Mouse and Space collapse did not rerun the page. Two folders were expanded
at once with `QA full page runs: 1`. Clicking a name opened the correct project and
updated active highlighting. Synthetic tasks were prepared without generation.
User preferences and materials were untouched.

**27 existing UI checks passed in 19,69 s**. Ruff check/format for two modules and
diff check passed. No new decorative-dimension tests. The full suite and models
were not rerun. Test servers 8522/8523 were stopped, created tabs closed, and the
viewport reset.

Screenshots outside the repository: `/private/tmp/brofessor-sidebar-heading-2026-11-06/` —
`sidebar-light.jpg`, `sidebar-dark.jpg`, `sidebar-light-390.jpg`,
`sidebar-dark-390.jpg`. This project-row defect does not establish the cause of the
earlier gray bar over main-page actions. That investigation was later cancelled
under D027.

## Compact script pagination — 06.11.2026

Following another user screenshot, the “Назад · Страница [номер] из N · Вперёд”
(“Previous · Page [number] of N · Next”) row was replaced with two chevron buttons
and a `1 / N` selector. Arrow labels remain for accessibility, while only icons are
shown visually. The counter allows direct selection of any page. On the first/last
page, the corresponding arrow is disabled. For one page, the control is absent.
Eight turns per page and the initially collapsed script were retained.

The current page is stored separately from the selectbox, so hiding the widget
when navigating to Sources does not lose position. Loading a shorter revision clamps
the number to its new length. The existing manual-input test was adapted to the
selector, retaining direct navigation, both bounds, both arrows, and script shortening,
and adding return through Sources and a recent task. Arbitrary invalid input no
longer needs checking: the selector contains valid pages only.

`tests/test_ui_followthrough.py` and `tests/test_ui_language.py`: **16 passed in 3,21 s**.
Ruff check/format for four affected Python files and `git diff --check` passed.
Real IAB was checked on a synthetic nine-turn script: 1 → 2 → 1 navigation, selecting
the second page from the list, and disabled boundary arrows. At 1280×720 and 390×844,
buttons were 40×40 px and the selector 112 px. The three elements occupied 200 px
on one row, with mobile document width equal to 390 px. Screenshots outside Git:
`outputs/ui-pagination-2026-11-06/desktop.jpg`, `mobile.jpg`, `pager.jpg`.
User data, model calls, and narration were unaffected. The temporary viewport was
reset and the tab closed.

## Download verification after restart

On 06.11.2026, a separate synthetic 35 520 000-byte file was checked through a local
HTTP server, real worker/SQLite, and Streamlit at 1280×720. This is a controlled
transport boundary without a model or external weight download.

The download was started in Models. Progress continued after closing/reopening
Settings. The worker was forcibly terminated, and the UI showed interruption at
24,1 of 35,5 MB. A full test-application restart and new browser session retained
progress, including in General. The first attempt exposed the distinction between
`/var` and `/private/var` on macOS. Canonicalization was fixed and covered by a
separate regression.

Repeated Resume retained the ID and pinned request, sent `Range: bytes=24117248-`,
and downloaded the remaining tail. Two HTTP requests, one job, matching final
SHA-256, and the UI showed installation. Concurrent submit/resume, live/dead workers,
and restarting only one file when a server rejects Range were checked.
Real Hugging Face/Ollama/Qwen weights were not downloaded in this continuation.
Ordinary external-browser speed was not measured. The original report was in the
old plan's downloads section. These results do not imply new acceptance of real weights.
