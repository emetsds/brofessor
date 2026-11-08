# Tasks

## 1. Translate the current product baseline

- [x] 1.1 Translate the purpose, scenarios, requirements table, and material/result rules in `docs/specification.md`; verify R01-R25 appear exactly once in the table and each requirement retains its original meaning and acceptance conditions.
- [x] 1.2 Translate the specification's quality, architecture, state/recovery, provider, maintenance, and support-limit sections; compare against the original to verify numerical constraints, named versions, exclusions, and evidence links are preserved.
- [x] 1.3 Review language-sensitive wording in R04, R06, R13, R15, and the support matrix; verify Russian/English content and UI capabilities remain described as supported, with UI language separate from output language.

## 2. Translate the historical decision log

- [x] 2.1 Translate the decision-log introduction and entries D001-D017 into English; verify all IDs, dates, decisions, alternatives, consequences, sources, and explicit supersession notes match the original.
- [x] 2.2 Translate entries D018-D034 and their later-revision notes; verify the complete log keeps its historical meaning, measurement claims, and links to the current English ADR.

## 3. Translate all historical evidence reports

- [x] 3.1 Translate the three `docs/evidence/2026-11-01-*.md` reports; review against the originals to verify versions, measurements, source references, and limits of the recorded checks remain equivalent.
- [x] 3.2 Translate the six `docs/evidence/2026-11-02-*.md` reports; review each against the original and verify reported test counts, observed failures, corrections, and acceptance limits are preserved.
- [x] 3.3 Translate the three `docs/evidence/2026-11-03-*.md` reports; verify voice/model identities, license descriptions, durations, measurements, and listening-acceptance limits retain their recorded meaning.
- [x] 3.4 Translate the five `docs/evidence/2026-11-04-*.md` reports; verify EPUB, terminology, and podcast-writing observations, comparisons, and unsupported cases match the originals.
- [x] 3.5 Translate the three `docs/evidence/2026-11-05-*.md` reports; verify PDF, source-navigation, and report results preserve their original inputs, checks, limitations, and data-handling claims.
- [x] 3.6 Translate the three `docs/evidence/2026-11-06-*.md` reports; verify authentication, learning/audiobook, and task-workflow records preserve versions, reproduction details, and the distinction between synthetic and real checks.
- [x] 3.7 Translate the five `docs/evidence/2026-11-07-*.md` reports; verify code-organization, contracts, transport, prompts, and UI records preserve measured results and their later-revision context. Confirm all 28 evidence reports are covered across this group.

## 4. Complete developer documentation across the repository

- [x] 4.1 Translate the full developer catalogue in `src/brofessor/prompts/README.md`; verify prompt IDs, variable names, commands, schema references, and links retain their meaning and none of the 53 runtime prompt templates or catalogue data files change.
- [x] 4.2 Update remaining project-authored developer prose in the root README and review agent instructions, ADRs, integration docs, font/fixture READMEs, third-party notices, and project-authored tool documentation; verify English prose is consistent, required Russian literals are explained, and original legal texts and copied upstream skills are unchanged.

## 5. Keep navigation and language coverage consistent

- [x] 5.1 Repair heading-fragment links across all project documentation, including incoming references from already-English documents; verify local targets and fragments resolve without renaming source files or creating parallel translated copies.
- [x] 5.2 Review the complete documentation inventory for untranslated developer prose; verify each retained Cyrillic occurrence is an intentional quotation, language example, exact product label, path, URL, or other literal rather than missed prose.

## 6. Verify the integrated documentation change

- [x] 6.1 Compare the final diff against the proposal's documentation boundaries and recorded original baseline; allow only the named README documentation exceptions under `src/` and `tests/`, and verify runtime code, prompts, localization, fixture payloads, dependencies, and saved data were not changed.
- [x] 6.2 Review semantic fidelity and repository standards across the full translation using the change artifacts as the specification source; include uncommitted and new files in the review, resolve substantive findings, and report any remaining uncertainty.
- [x] 6.3 Run `openspec validate english-core-documentation --strict --no-interactive` and a documentation-wide check of local Markdown targets and fragments; report these results separately from semantic review and note that runtime/model checks were not needed or performed.

## Workflow follow-up

- After implementation and review, archive the documentation change through the standard OpenSpec archive workflow. With `skip_specs: true`, there are no product delta specs to synchronize.
