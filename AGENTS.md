# Working on brofessor

- Do not preserve backward compatibility.
- Choose the simplest implementation that fully meets the current requirements.
- Prefer established, well-maintained libraries over custom implementations.
- Fix the cause, not the symptom.
- Suggest best practices, even if they may require refactoring.
- Prefer repository evidence and current documentation over model memory.
- Keep changes focused on the requested task.
- Make behavior-changing assumptions explicit.
- Report what you verified and what you could not verify.

Read [README.md](README.md) for setup and checks and [the product specification](docs/specification.md) for the existing product baseline. Use [OpenSpec](openspec/config.yaml) for change proposals, capability specifications, and implementation tasks. Active work lives in `openspec/changes/<change>/tasks.md`; [the former plan](docs/plan.md) is a navigation pointer. Consult [the decision log](docs/decision-log.md) and relevant [ADRs](docs/adr/) when revisiting a choice. Update the owning document when its contents change; do not maintain a second backlog.

The [skill tracker guide](docs/agents/issue-tracker.md) explains how Matt Pocock's skills consume OpenSpec changes. The [domain guide](docs/agents/domain.md) identifies terminology and decision sources.

Use isolated QA projects, ports, and config/data directories. Preserve the user's running services, settings, materials, and edits. Keep private data and generated files out of Git.

Discuss and explain work in Russian. Write maintained developer documentation, OpenSpec artifacts, and code identifiers in English. Repository documentation language is independent of the application's UI and content languages. Keep runtime prompts, translations, and multilingual test materials in the languages required by their behavior. Always spell **brofessor** in lowercase.
