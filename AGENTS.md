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

Read [README.md](README.md) for setup and checks, [the specification](docs/specification.md) for current requirements, and [the plan](docs/plan.md) for unfinished work. Consult [the decision log](docs/decision-log.md) when revisiting a choice. Update the relevant document when its contents change; the plan is the only task list.

Use isolated QA projects, ports, and config/data directories. Preserve the user's running services, settings, materials, and edits. Keep private data and generated files out of Git.

Discuss and plan in Russian. Keep the public README and code identifiers in English. Always spell **brofessor** in lowercase.
