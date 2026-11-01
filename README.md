# brofessor

**Your sources, explained.**

brofessor is a planned open-source research workspace for exploring sources, asking grounded questions, and creating podcasts and presentations. The product goal is to become a practical alternative to NotebookLM.

Books are the first reference workflow. The architecture also accommodates documents, articles, notes, and other source types as importers are added.

## Current status

Planning repository, created on 2026-11-01. There is no runnable application, CLI, UI, or installed skill yet. The commands and layouts in the design documents are proposed interfaces.

## Product commitments

- **Equal CLI and UI:** a local Streamlit application and a CLI use the same application services, workspace, jobs, and artifacts.
- **Agent agnostic:** support Codex, Claude Code, and direct local inference through Ollama. Portable Agent Skills provide an additional entry point from existing agents.
- **Model choice:** model and speech backends are replaceable. Supported open-weight models are identified by tested capabilities and licenses, not by a blanket compatibility claim.
- **Grounded work:** preserve original sources, locators, coverage, and the evidence behind answers and generated materials.
- **Editable outputs:** Russian and English podcasts with multiple voices and editable PPTX presentations, with Google Slides integration planned after local exports.
- **Resumable work:** a local worker persists progress independently of the browser and supports cancellation and resumption.
- **No new paid service required for the reference workflow:** an existing ChatGPT subscription or local inference can be used. Claude access belongs to the user configuring that integration. No automatic paid fallback.

Local storage does not imply local inference: Codex and Claude runners can send selected source material to their respective providers. A separate local-only profile uses local text and speech models.

## Planning documents

The detailed plan is currently in Russian.

- [Requirements and release scope](docs/requirements.md)
- [Architecture and interface parity](docs/architecture.md)
- [Implementation plan and acceptance gates](docs/implementation-plan.md)
- [Technical evidence and remaining uncertainties](docs/research.md)
- [Guidance for coding agents](AGENTS.md)

## Intended shape

```text
CLI -----------+
Streamlit UI --+--> application services --> workspace + job queue
Agent skills --+              |
                             worker
                               |
                 Codex / Claude Code / Ollama
                               |
                      evidence + drafts
                               |
                   local speech + PPTX renderers
```

The UI is a local single-user interface in the first release. Public hosting, accounts, and collaboration are outside that release.

## Publication

The repository contains the product and its documentation. Personal sources, generated materials, credentials, and model weights belong outside version control. A code license and third-party attribution must be finalized before a public release. No GitHub remote or public release is implied by this local planning repository.
