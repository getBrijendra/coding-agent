# Repository Guidelines for Codex

## Mission

Build the LangGraph-based coding agent specified in [`CODEX_TASK.md`](./CODEX_TASK.md). Read that entire file before editing. Treat it as the source of truth for scope, architecture, safety controls, milestones, and acceptance criteria.

## How to work

1. Inspect the repository and preserve existing work. If empty, scaffold the specified Python package.
2. Implement milestones in order, as working vertical slices. Do not stop after writing a plan.
3. Keep `CODEX_TASK.md` sections **Progress**, **Decisions**, and **Validation evidence** current.
4. Run `python -m pytest -q` and `ruff check .` after meaningful implementation changes, when available. Report observed results, not assumed success.
5. Do not use deprecated `langgraph.prebuilt.create_react_agent`.
6. Do not expose secrets or implement unrestricted host shell execution. Enforce per-patch approval and use a disposable Docker sandbox for generated-code validation.
7. Document concrete setup and CLI examples in `README.md` and explain limitations.

## Definition of done

A user can install the package, run `coding-agent run --repo ... --task ...`, inspect and approve a plan and patch, safely apply the edit, see sandbox validation results (or an explicit `not_run`), and resume interrupted work with a persistent thread ID. Unit/safety/integration tests cover this workflow using fake model responses without API charges.

## Immediate first action

Read `CODEX_TASK.md`, inspect the current repository, and begin Milestone 1. Continue through all achievable milestones without asking to reconfirm details already specified in the plan.
