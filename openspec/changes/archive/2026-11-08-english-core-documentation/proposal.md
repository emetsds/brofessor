# Proposal

## Why

brofessor's public README is in English while its product specification, historical decision log, evidence reports, and prompt catalogue documentation contain Russian developer prose. The user explicitly chose to translate all repository documentation, including historical reports, in one OpenSpec change while preserving the application's multilingual capabilities.

## What Changes

- Translate the complete current `docs/specification.md` into clear English, preserving requirement IDs R01-R25, their meaning, acceptance conditions, numerical limits, architecture, and support boundaries.
- Translate `docs/decision-log.md` and all 28 reports in `docs/evidence/`, preserving decision IDs, dates, recorded measurements, revisions, sources, and historical support limitations.
- Translate developer prose in `src/brofessor/prompts/README.md` and any remaining project documentation. Review the root README, agent instructions, ADRs, integration guides, font README, fixture README, third-party notices, and project-authored tool documentation for a consistent English documentation experience.
- Update incoming links and heading fragments across the documentation wherever translated headings change their targets. Keep existing file paths and identifiers.
- Preserve literal examples, exact UI labels, source quotations, paths, command names, and identifiers wherever translation would misrepresent the product or break a reference.

The entire documentation translation is one change. Tasks are grouped for review and progress tracking, with no separate later change required for the historical archive or prompt catalogue README. Existing English documentation needs verification and any necessary reference updates, not gratuitous rewriting. The completed tool setup is separate from completion of this translation.

## Capabilities

### New Capabilities

None. This change translates documentation and adds no product capability. Its metadata sets `skip_specs: true`; no delta spec is needed.

### Modified Capabilities

None. Russian and English UI/content support, generation, book translation, speech, and the other existing requirements remain unchanged. `docs/specification.md` remains the owning product baseline after translation.

## Impact

Implementation is confined to repository documentation and Markdown references. The existing tracked documentation inventory has 38 Markdown files, including 28 historical evidence reports. Scope includes root documentation, `docs/**/*.md`, `src/brofessor/prompts/README.md`, `src/brofessor/infrastructure/formats/fonts/README.md`, and `tests/fixtures/translation/README.md`, plus the project-authored OpenSpec and skill-integration documentation introduced during setup.

Runtime code, inline code comments/docstrings, the 53 application prompt templates, prompt catalogue data, localization strings, source and test-fixture content, model and voice settings, dependencies, saved data, and CLI/API contracts are outside the implementation scope. Original license texts and copied third-party skill contents are retained unchanged. Dialogue and coaching with the user remain in Russian. No application model calls or new runtime tests are needed for this documentation-only change.
