# english-core-documentation

Translate all project documentation, including the historical decision log, evidence reports, and developer READMEs, into English in one change without changing UI or content-language behavior.

## Verification

Completed on 2026-11-08:

- Translated the specification, historical decision log, all 28 evidence reports, and the prompt catalogue README. Existing English developer documentation was reviewed for consistency.
- Preserved the ordered R01-R25 requirement IDs and D001-D034 decision IDs, original numerical values, and source literals. Decimal commas in some historical measurements were normalized to decimal points without changing values.
- Repaired 21 heading-fragment references. All 380 local Markdown links resolve across 46 project-authored documentation files. All 95 existing external URL occurrences remain identical; external sites were not revalidated.
- Verified unchanged SHA-256 hashes for 271 protected files and 31 installed upstream skill files. Runtime code, working prompts, localization, fixture payloads, dependencies, and original legal texts were not modified.
- Independent Standards review found no violations. Spec review found one P3 ambiguity in the task-workflow report's translation of the user-provided task name; it was corrected and the fix verified. Independent historical semantic review was selective rather than a line-by-line audit of the full archive.
- Strict OpenSpec validation and `git diff --check` passed. Runtime/model acceptance checks were not needed or run for this documentation-only change.

The implementation is complete. Archival is the next OpenSpec workflow; no product delta specifications need synchronization because this change declares `skip_specs: true`.
