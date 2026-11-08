# Agent skill sources

## OpenSpec

- Source: https://github.com/Fission-AI/OpenSpec
- Generator: official `@fission-ai/openspec` npm release **1.16.1**.
- Generated with: `openspec init . --tools codex --language en --profile core --no-animation`.
- Installed directories: `openspec-explore`, `openspec-propose`, `openspec-apply-change`, `openspec-update-change`, `openspec-sync-specs`, and `openspec-archive-change` under `skills/`.
- License: [MIT](LICENSES/openspec-MIT.txt).

## Matt Pocock

- Source: https://github.com/mattpocock/skills
- Release: **v1.3.2**.
- Resolved release commit: `d1478fcb140db0b93c0c8df17bcfd311844749d0`.
- Installed with the bundled Codex skill-installer, using its Git method and `--ref v1.3.2 --dest .agents/skills`.
- `skills/engineering/`: `setup-matt-pocock-skills`, `tdd`, `diagnosing-bugs`, `code-review`, and `codebase-design`.
- `skills/productivity/`: `grill-me` and its `grilling` dependency.
- Complete selected skill directories, including their supporting references and scripts, were copied without editing their contents.
- License: [MIT](LICENSES/mattpocock-skills-MIT.txt).

## Project integration and updates

Project-specific integration belongs in `openspec/config.yaml`, `AGENTS.md`, `CLAUDE.md`, and `docs/agents/`, keeping copied skill instructions unchanged.

To update OpenSpec, install the chosen stable CLI release, run `openspec update`, and review the generated skill diff. Record the new generator version here. To update Matt's skills, deliberately select a release, replace the selected complete directories through the skill-installer, and record its tag and resolved commit. Review instruction and dependency changes before using an updated workflow.

Newly installed skills are available to Codex on the next turn. If they do not appear in the skill selector, restart Codex.
