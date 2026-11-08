# ADR-0001: OpenSpec with selected Matt Pocock skills

Date: 2026-11-08

Status: Accepted

## Context

The user wants to learn OpenSpec and Matt Pocock's skills through real brofessor changes. Preserving the previous documentation layout is secondary to learning the tools. The previous plan had no unfinished work at the start of this setup.

## Decision

Use the stable OpenSpec 1.16.1 CLI, its standard `spec-driven` schema, and the core Codex workflows. Keep its generated skills in the repository. Install selected, unchanged Matt Pocock skills from v1.3.2 for diagnosis, TDD, design vocabulary, and review, plus the shared interview and setup skills they use.

OpenSpec owns change artifacts and implementation task lists. `docs/plan.md` becomes a navigation pointer. The existing product baseline remains in `docs/specification.md`; accepted capabilities captured with OpenSpec live in `openspec/specs/`. Do not duplicate the same requirements in both locations. Record new lasting decisions in `docs/adr/` and retain `docs/decision-log.md` as historical context.

Write maintained developer documentation and OpenSpec artifacts in English, while coaching the user in Russian. Documentation translation must not change UI locales, output-language options, runtime prompts, source content, or multilingual test fixtures.

## Consequences

The user can learn the standard proposal, apply, synchronization, and archive cycle without a custom schema or a second task tracker. Matt's skills consume OpenSpec artifacts through `docs/agents/issue-tracker.md`.

The first documentation change exercises specification, scope, and review. It does not introduce artificial runtime tests just to exercise TDD. Behavior changes can introduce that skill later at agreed public interfaces.

The CLI is a developer installation outside the Python runtime. Copied skills retain their upstream licenses and a pinned source revision in `.agents/UPSTREAM.md`.

This supersedes [D033](../decision-log.md#d033-07112026--three-main-project-documents) for task tracking and the developer-documentation language portion of D034. Other product requirements and development principles remain in force.
