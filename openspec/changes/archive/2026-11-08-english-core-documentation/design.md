# Design

## Context

See [the proposal](proposal.md) for motivation and scope. The existing tracked documentation inventory contains 38 Markdown files, including the 154-line product specification, the decision log, 28 evidence reports, and developer READMEs. New project-authored setup documentation is already in English and is also reviewed for consistency. Translating headings changes generated fragments used by links throughout these documents.

This design records the documentation-migration decisions: how to translate normative and historical prose, preserve multilingual literals and recorded results, and repair incoming links without changing product behavior. The preceding tool setup is already present in the working tree. The initial clean product baseline was commit `28ab216`.

## Goals / Non-Goals

**Goals:** Make all project-authored repository documentation English in one change, keep requirements and historical records semantically equivalent, retain one owning product baseline, and keep navigation valid after heading translation.

**Non-Goals:** Reorganizing R01-R25 into new OpenSpec capabilities, revising product requirements, re-running historical experiments, changing runtime text or behavior, or rewriting inline code comments/docstrings, legal texts, and copied upstream skills.

## Decisions

### Translate developer prose while preserving meaningful literals

Translate project-authored documentation headings, tables, explanations, and descriptive labels into English. Retain requirement and decision IDs, numbers, units, paths, commands, identifiers, URLs, and exact quoted product labels. Retain Russian where it is literal source content, a language example, an exact historical quotation, or an exact UI label rather than developer prose. Add an English explanation beside a retained quotation when needed for an English reader.

A repository-wide ban on Cyrillic would reject valid multilingual data and encourage accidental changes to prompts or fixtures, so verification is scoped to project-authored documentation prose and explicitly accounts for retained literals.

### Translate historical records without revising history

Translate all 28 evidence reports and the full decision log. Preserve dates, decision IDs, versions, measurements, reported test counts, supersession relationships, evidence paths, and distinctions between observed results and unverified claims. A historical implementation remains historical even when a later decision removed it. Translation does not reopen completed or cancelled tasks, update old measurements, or claim a new model or media acceptance run.

Group report work by their existing dates inside this one change. Review each group's translation against the original before marking its tasks complete. Keep existing file paths; do not create parallel Russian copies.

### Update incoming fragments across the repository

Keep `docs/specification.md`, the decision log, and all report paths where they are. Derive new heading fragments from their translated headings and repair incoming references across root docs, reports, READMEs, and new project-authored ADR/integration documents. Check both translated documents and already-English documents that point into them.

Moving the whole baseline into OpenSpec capability files would combine translation with a requirements migration and make semantic review harder. That migration is outside this change.

### Verify documentation directly

Review the translated specification against the original using all 25 requirement IDs as an index. Check numerical constraints, cancellation/recovery, source integrity, and support limits as well as language-related requirements. In particular, preserve cross-language questions in R04, RU/EN podcasts in R06, and the separation of UI and content languages in R15.

Review the historical translations for semantic fidelity as well as the current specification. Check local Markdown targets and fragments across the complete documentation set. Review remaining Cyrillic in documentation and explain intentional literals rather than removing them mechanically.

Compare runtime paths against the unchanged baseline, including `src/`, `tests/`, `tools/`, `pyproject.toml`, and `uv.lock`. The documentation exceptions under runtime/test directories are `src/brofessor/prompts/README.md`, `src/brofessor/infrastructure/formats/fonts/README.md`, and `tests/fixtures/translation/README.md`. Other content there, including the 53 prompt templates, prompt catalogue JSON, locale strings, and fixture payloads, must remain unchanged. New runtime tests or model calls would not provide evidence of faithful prose translation.

Keep original license texts and vendored skill contents unchanged. Already-English project documentation only needs consistency and reference updates where the translation makes them necessary.

Use Matt Pocock's review discipline with the selected proposal and tasks as the specification source. Include uncommitted documentation and relevant new files in the review scope; the upstream committed three-dot diff alone will not show this work.

### Skip product delta specifications

The change's `skip_specs: true` metadata explicitly records that product behavior is unchanged. No delta files are created. OpenSpec structural validation is reported separately from semantic document review.

## Risks / Trade-offs

- Translation can weaken a requirement or turn an observed result into a guarantee. Mitigation: review against the original by requirement ID and preserve explicit limitations.
- Translation of historical reports can silently change the evidence record. Mitigation: preserve dates, versions, measurements, limitations, and supersession links, and review each report group against the original.
- Heading translation can break navigation across the specification, decision log, reports, and already-English docs. Mitigation: check all documentation links after translations and update affected fragments.
- The phrase "English repository" can be mistaken for English-only product behavior. Mitigation: keep the exact runtime exclusions from the proposal and verify the runtime diff is empty.
- The full archive is larger than the initially proposed core-only slice. Mitigation: keep one change while using reviewable task groups and report progress at each group boundary.

## Migration Plan

Translate the current specification and decision log, then the dated report groups and remaining developer documentation. Update references throughout the documentation, review semantic fidelity and the allowed-file boundary, and complete the change as one unit. No data migration or service restart is involved. If a wording choice is uncertain, resolve it against the original before marking its task complete.
