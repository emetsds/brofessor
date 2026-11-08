# Issue tracker: OpenSpec

OpenSpec is the local tracker for brofessor. Its standard `spec-driven` schema owns each change's proposal, capability deltas, design, and implementation tasks.

## Resolve a change

Run `openspec list --json`, then `openspec status --change <change> --json`. Read the returned artifact paths rather than assuming a different planning root. In this repository, active changes normally live in `openspec/changes/<change>/`.

- `proposal.md` describes why the change is needed and its scope.
- `specs/<capability>/spec.md` contains the proposed requirements and scenarios.
- `design.md` records the technical approach when one is needed.
- `tasks.md` is the only implementation checklist for that change.

When a Matt Pocock skill asks for a ticket or originating specification, pass the selected change name and these artifact paths. Read the existing product baseline in `docs/specification.md` and the relevant accepted capabilities in `openspec/specs/` as well.

## Keep one tracker

Update the selected OpenSpec task checkboxes as work completes. Do not create parallel `.scratch/` tickets, GitHub Issues, or another plan for the same work. The previous `docs/plan.md` is only a navigation pointer.

The installed Matt skills support diagnosis, public-interface tests, design vocabulary, and review. Their implementation and ticket-generation orchestrators are not installed; OpenSpec owns orchestration.

## Review scope

For `code-review`, provide the originating OpenSpec artifacts and a concrete base commit or branch. The upstream skill's three-dot diff examines committed changes. If the work is uncommitted, explicitly include `git diff <base>` and relevant new files in the review scope; do not treat an empty committed diff as a review of the working tree. Do not create a commit merely to satisfy the review command.

Review implementation against both repository standards and the selected requirements. `openspec validate <change> --strict` is a separate structural check.
