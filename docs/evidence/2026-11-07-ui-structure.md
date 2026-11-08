# brofessor UI section structure

Historical report. Current requirements and boundaries are in the [specification](../specification.md); decisions and cancellations are in the [Decision log](../decision-log.md). References to later stages describe the state at the time of the experiment.

07.11.2026. Implementation of the reopened UI-structure stage accepted in [D028](../decision-log.md#d028-0607112026--consistent-screen-structure-and-repeated-acceptance), after the user's instruction to continue. This is separate structural acceptance, not repetition of previous typography measurements.

## What changed

Shared `ui_layout.section()` styles large native collapsible sections: a 20 px heading with 16 px body text, an arrow, horizontal boundary, and spacing. Nested notes retain a compact role. Small `section_roles.js` adds `role=heading` and `aria-level=3` to native summary headings; the real accessibility tree shows H3. The component does not manage state, inputs, or jobs. User text does not become HTML.

The card separates the finished file, material, domain sources/checks, and a distinct service area at the bottom, “Сведения и настройки задачи” (“Task information and settings”). The JSON editor, source information, history, completed progress, models, and operations sit after this boundary. Errors and controls for unfinished script/answer checks precede the result, so collapsing their contents does not hide Cancel/Resume.

The ordinary and JSON editors use the existing canonical buffer and recovery. JSON occupies its own bottom service area; ordinary edit saving, warnings, and loading the latest version remain outside collapsible material. Initial expansion is fixed when a section first appears: the first file's arrival does not reset the choice on progress updates. Entering edit mode uses a separate expansion key and opens fields, including for notes. The selected audiobook chapter is shared between reading and editing.

EPUB/PDF no longer skip shared information and history. Historical preview receives the real `job_id` separately from its widget key. History has independent selectors: it does not change the current buffer, selected fragment, or file. Study history shows saved answers and expected explanations; series history retains terminology.

All four report types retain “Из источников” / “Адаптация brofessor” (“From sources” / “brofessor adaptation”) labels. Answers and reports have separate source sections. Series separate the plan, glossary, and episode preparation; studies separate questions/answers from review. Audiobook chapter text collapses independently of the player. PDF qualifications and retained objects appear beside their file.

Sources, forms, and notes gained boundaries between major groups. Catalogues and sidebar retain compact rows. In Settings, long content scrolls in its own region with Save/Cancel underneath. Initially adding large dividers pushed Save below the first screen again; browser checking found this, and layout was fixed before stage completion.

Core, SQLite, revision contracts, queue, models, and data-transfer rules did not change in this stage.

## Independent-review fixes

The critic checked current code, a separate synthetic-workspace copy, and screenshots. The defects found were fixed:

- Intermediate JSON `[]` or `{"turns": null}` no longer breaks the podcast heading before Save/Reload appears; invalid input can be fixed or reloaded.
- Queuing a new EPUB/PDF render preserves access to the first automatic export. It is included in the finished-file selector and remains available during queued/failed rendering.
- Closed material expands when entering the editor; the selected chapter does not reset.
- Series/study history retains substantive data, and unfinished-check statuses do not disappear when their review report collapses.
- Service sections were compacted without losing boundaries. Settings Save/Cancel were checked after the layout fix.

The critic's final conclusion: no findings remained that blocked completion of this stage. Review included main and additional pages, final mobile screenshots, and settings with enlarged text.

## Automated checks

Final run after the last changes: **118 passed in 56.04 s**:

```sh
.venv/bin/pytest -q \
  tests/test_translation_interfaces.py tests/test_ui_redesign.py \
  tests/test_studies.py tests/test_reports.py tests/test_ui_followthrough.py \
  tests/test_interfaces.py tests/test_note_interfaces.py tests/test_ui_language.py \
  tests/test_pdf_workflow.py tests/test_audiobooks.py
```

Seven behavioral cases were added: EPUB/PDF history with unsaved current edits; access to the first file during queued/failed rebuilding of both formats; two invalid intermediate podcast JSON values; retention of initial expansion when the first file appears; and an initially closed section in a new session with a finished file. They check revisions, buffers, recovery, no new model calls, and artifact access rather than decorative dimensions.

Existing quotation/locator and language-switching checks were adapted to the new presentation: source names became nested headings, locators stayed captions, and plan titles became summary labels. Content, quotation, revision, and user-input checks were retained; tests were not removed.

Ruff check/format and `git diff --check` passed. The wheel was built offline through standard `hatchling.build.build_wheel` using the existing Hatchling 1.33.0 cache. Ordinary `uv build --offline` could not resolve the build backend using the selected cache's metadata; no downloads or dependency changes were used as a workaround. All `ui*.py` and `section_roles.js` files were checked byte-for-byte against the wheel; UI modules were imported from the extracted package outside checkout. The package contains no QA materials.

## Real browser

Streamlit 1.66.1, IAB, separate temporary XDG settings, and a synthetic project. The presentation was built by the real local renderer. EPUB/PDF and feedback used existing test models at the inference boundary. The player used a synthetic WAV and locally packaged M4B; no speech or new real-model calls were made.

| Slice | Actually checked |
|---|---|
| Main tasks, light RU, 1280×720 | Answer, four reports, series, studies, EPUB, PDF, podcasts and presentations with/without files, audiobook text and player; initial view, expanded/collapsed material, and bottom service area |
| History | History of 12 views read in the browser: presentation, podcast, answer, four reports, series, study, audiobook, EPUB, and PDF; no exceptions |
| Editing | Slide edits survived material collapse and navigation to sources; Save with the plan closed created r3. PPTX r1 remained with an explicit mismatch label. EPUB r1 history opened with unsaved r2 edits, leaving current text unchanged. The second chapter persisted after Edit. Closed note text opened on Edit note |
| Additional pages | All nine creation-form types, sources with connected directory/search/preview, notes, General/Models/Storage, projects, search, catalogue, project/file/folder/delete dialogs. Deletion was cancelled and downloads not started |
| Dark EN, 900×768 and 390×844 | Podcast and presentation, keyboard expansion, script paging, boundary after the third slide, persistently closed script; audiobook and mobile settings. Document width 390 px with a 390 px viewport |
| Text 200%, light EN, 1280×720 | Body text 32 px, actual H1 64 px; material and service sections accessible through vertical scrolling, document width 1280 px. Settings retain accessible Save/Cancel |

In final Settings, the Save button ends at y688 with height 720, y765 with mobile height 844, and y655 with 200% text/height 720. This measures action accessibility, not a replacement for visual inspection. Transitional collapse-animation screenshots were retaken after content was actually hidden.

Screenshots and `browser-checks.json` are outside Git in `outputs/ui-structure-2026-11-07/`; workspace and build are in `/private/tmp/brofessor-structure-2026-11-07/`. Temporary viewport overrides were reset, QA tabs closed, and servers 8570/8571/8572 stopped.

## Result boundaries

This is acceptance of UI structure and data preservation on synthetic materials. Revision conflicts and CLI/UI parity were checked by targeted offline tests. The full product suite and real models were not rerun; no new benchmark, listening acceptance, or ordinary external-browser download is claimed. Previously cancelled user work was not resumed. User projects, settings, and credentials were unchanged.

## Intermediate dimension check

06.11.2026. Following the user's “Делаем” (“Let's do it”), four issues from an independent audit were fixed. Work affected `ui.py`, `ui_content.py`, and `ui_settings.py`; business rules and project data were unchanged. Browser checks used previous synthetic QA projects and a separate `XDG_CONFIG_HOME`. Models, downloads, and ordinary user settings were not used.

### Changes

Top padding of main content was reduced from 96 to 56px. Project title and navigation occupy one block, catalogue and task models one row with natural widths. Type/status/origin were combined; editing and save state appear together. Result headings have smaller internal padding, while body font and line spacing are preserved. Regeneration is under “Операциях задачи” (“Task operations”) with the existing unsaved-revision protection. Rendering, voice preview, and series launch retain their editor actions. The player, chapter selector, and downloads precede service details/coverage.

Settings retains one localized native heading; two redundant dividers were removed. Save/Cancel and close clear staged fields through the existing callbacks. The sidebar logo's native heading wrapper has its negative margin reset. Recent-task captions target the actual caption `p`, and their wrapper has zero bottom margin: otherwise the standard −16px plus a small gap overlaps neighboring rows. Main button/field dimensions are preserved.

### Browser measurements

IAB, 1280×720, base font 16px. Coordinates refer to the control's top edge on the unscrolled main screen.

| Control | Before | After |
|---|---:|---:|
| Study answer field | y930.27 | y614.91; 100px, fully visible |
| Audiobook player | y684.47 | y407.52; 40px, fully visible |
| M4B/MP3 downloads | Below first screen | y463.52/y519.52; 40px |
| Save/Cancel in Models | y748.38 | y568.79; 40px, entire dialog visible |
| Logo → first button | 10.4px overlap | Positive 5.59px gap |
| Recent-task caption | 14px/22.4px, `small` selector ineffective | 12.8px/16.64px, actual `p`, margin 0 |

Task creation, report reading/editor, sources, and General settings were also inspected. The 900×768 view checked header wrapping, player/downloads, and action labels. Fixed column ratios squeezed “Все задачи проекта” (“All project tasks”) in a narrow window; they were replaced with a horizontal container using the button's natural width. The temporary viewport was reset after checking.

This checks the listed desktop dimensions, not identical first-screen contents for every title, question length, or zoom level. Long forms, expanded options, and material can scroll. For example, the new-podcast form's submit after compaction is at y778 rather than y905; this does not claim every field fits in720px. Textarea height and material content were not reduced for this measurement.

Original audit: `outputs/ui-spacing-audit-2026-11-06/audit.md`, with screenshots and JSON beside it. Final evidence: `outputs/ui-spacing-fix-2026-11-06/` — `study`, `audiobook`, `settings-general`, `settings-models`, `report`, `report-editor`, `new-task`, `sources`, `result-900`, `audiobook-900`, `sidebar.json`. An independent repeat source/screenshot review confirmed closure of 4/4; its conclusion is `review.md` in the same directory. These files are ignored by Git.

### Behavior checks

First, 96 targeted UI/interface checks passed: revision saving/conflicts, recovery, navigation/languages, settings Save/Cancel, task models, regeneration, series, translation, study/report, and rendering. An early local run caught a lost render/series-action placeholder; it was restored for relevant kinds before accepting results.

After final layout, the full suite was **622 passed**. Ruff check/format and diff check pass. No new fixed-spacing/decorative-size tests were added: geometry was checked in a real browser and existing behavior checks were preserved. Temporary server 8566 was stopped. Real text/speech calls were unnecessary for this UI edit and were not performed.

### Recent-task heading overlap — 06.11.2026

A new screenshot reproduced “Недавние задачи” (“Recent tasks”) overlapping the first list row. This is a separate Markdown defect, not a repetition of the earlier caption defect: the heading's `stMarkdownContainer` has computed `margin-bottom` of −16 px, and with text height 25.59 px its outer element occupies only 9.59 px. At the original 1280×720 viewport, the text's bottom edge is y461.78 and the first task starts at y448.98: an overlap of 12.80 px.

In `ui_navigation.py`, the heading received its own `sidebar-recents-heading` container. In `ui.py` CSS, only this Markdown has its negative margin reset and bottom padding of 4 px added. Existing row dimensions, captions, task highlighting, and divider are preserved. After the fix, the gap between heading text and the first button is 7.20 px.

Real Streamlit 1.66.1 was checked in IAB with separate temporary XDG settings and a synthetic project containing 18 finished tasks. Light/dark themes were checked at 1280×720 and 390×844; panel shares 15%/85% were changed with Home/End, and the ordinary 50% share restored with arrows. At mobile width, the sidebar was expanded before measurement. A normal 600×795 viewport was also checked. All recorded measurements show a 7.20 px gap and no horizontal document overflow. PageDown scrolls the recent list (confirmed `scrollTop=139`) without changing project scrolling (`scrollTop=0`). At minimum panel height, the list is accessible by scrolling; simultaneous display of all tasks is not claimed. The temporary viewport was reset.

`uv run --no-sync pytest -q tests/test_ui_redesign.py tests/test_ui_followthrough.py`: **27 passed in 21.55 s**. Ruff check/format of the two changed UI modules and `git diff --check` passed. No new decorative-size tests were added; existing checks of recent-task navigation, independent drafts, settings, and editing were preserved. The full product suite and real models were not run for this fix.

Screenshots and geometry are outside Git: `outputs/ui-hierarchy-2026-11-06/measurements.json`, `workspace-light.jpg`, `sidebar-light-mobile.jpg`, `sidebar-dark-mobile.jpg`. Temporary servers 8567/8568 were stopped. The user project and settings were unchanged. This intermediate slice did not establish completion of all typography and structure; later final checks appear at the beginning of the report.

## Interface-check history

- 02.11: a UX audit found mixing of material and service information, a flat technical-job list, and overloaded forms. After user approval, the interface was rebuilt around tasks, sources, and notes, with ordinary editors and additional JSON.
- 03.11: related runs were grouped into tasks; shared settings, task models, and storage maintenance were separated from results. Checks used synthetic projects and did not establish model quality.
- 06.11: a separate density audit found results below the first screen, inaccessible Save/Cancel, and sidebar overlap. Measurements and behavior checks for that slice appear above.
- 06.11: typographic hierarchy was incorrectly announced as completion of the entire structure. Repeat screenshots found missing outer collapse controls for slides, reports, series, and audiobook chapters, a boundary before settings, and shared translation history. D028 retains this clarification; the earlier completion mark is not evidence of readiness.
- 07.11: structural fixes and a separate browser matrix of all task types, history, and additional screens were completed. The final checks in this report close the reopened stage; earlier intermediate screenshots do not replace them.

Local original audits, measurements, and screenshots are not in the public repository. Installation and current operations are described in the README; this is UI-decision history, not a separate plan.
