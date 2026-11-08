# Domain documentation

brofessor is a single-context repository.

## Sources to read

- `docs/specification.md` is the existing product baseline, including requirement IDs R01-R25, architecture, and support limits.
- `openspec/specs/` contains accepted capabilities introduced or migrated through OpenSpec. An active change's delta specs are proposals until accepted and synchronized.
- `docs/decision-log.md` records historical product and technical decisions. Read relevant entries, including their explicit revisions.
- `docs/adr/` records new decisions with lasting tradeoffs. Read the ADRs relevant to the area being changed.
- Read `GLOSSARY.md` if one exists. Do not create an empty glossary or duplicate one preemptively.

Each requirement has one owning specification. A new capability may live in OpenSpec without moving the entire product baseline in the same change. A later migration must replace the old owning text with a reference rather than maintaining two copies.

## Vocabulary

Use the existing specification and code to distinguish a user-facing task, an execution job, a saved draft revision, and a workspace. Do not infer that these are interchangeable from their everyday English meanings. When a term needs an explicit agreed definition, record it in the single root glossary.

## Conflicts

Surface a conflict between a proposed change and an existing requirement or decision. Preserve the historical reason while recording the accepted replacement in the owning document. Historical evidence reports describe checks at their recorded versions and do not create new requirements or unfinished tasks.

Repository documentation language is independent of product language. Russian and English examples, UI messages, model prompts, source quotations, and multilingual fixtures are behavior or data when used by the application.
