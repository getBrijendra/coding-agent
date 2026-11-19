# Harbor and Terminal-Bench Evaluation Plan

> Status: planning document; no Harbor adapter has been implemented yet.  
> Last reviewed: 2026-11-19.  
> Baseline targets: Harbor 0.26.0 and Terminal-Bench 4.1.0.

## Purpose

This document describes how to evaluate the local LangGraph coding agent with the Harbor framework
and Terminal-Bench. The recommended first objective is a constrained compatibility evaluation, not
an immediate leaderboard submission.

The agent is deliberately a Python-focused, Git-based, plan-and-patch assistant. Terminal-Bench
evaluates general terminal agents across tasks that may require shell commands, binary inspection,
services, package installation, compilation, file-mode changes, GPUs, or multi-container systems.
An unqualified aggregate score would therefore measure missing terminal capabilities as much as
planning or coding quality.

## Current compatibility assessment

| Harbor or Terminal-Bench expectation | Current coding agent | Consequence |
| --- | --- | --- |
| Autonomous, headless execution | Separate interactive approval is required for the plan and every patch | Use an explicit evaluation-only approval driver |
| Arbitrary task workspace | The target must be the exact root of a Git working tree | Initialize a temporary Git baseline when a task workspace is not already a repository |
| General terminal work | The model can only list, search, and read bounded repository text, then propose a unified diff | Tasks requiring commands, binaries, services, package installation, or process control are incompatible |
| Execution in Harbor's task container | Generated-code validation expects another disposable Docker environment | Nested validation will generally be `not_run`; do not mount the host Docker socket |
| Diverse task outputs | Writes are text patches; binary patches, renames, copies, and mode changes are rejected | Restrict the initial study to text-editing tasks |
| Harbor-selected model and provider | Live inference currently uses the fixed OpenRouter endpoint and environment-based model setting | The adapter must map credentials and model selection explicitly |
| Standard trajectory and cost reporting | The agent does not produce Harbor ATIF trajectories | Reward can still be measured, but trajectory, token, and cost comparisons will be incomplete |

These are intentional product boundaries. `CODEX_TASK.md` defines a local-first, Python-focused
Git agent and excludes arbitrary shell autonomy and unattended deployments from the MVP.

## Evaluation principles

1. Pin every material version: Harbor, dataset, agent commit, dependencies, model identifier, and
   adapter revision.
2. Keep benchmark-specific behavior outside the production agent where possible.
3. Make automatic approvals explicit in logs and configuration. Never disguise them as human
   approvals.
4. Let Harbor's verifier determine task success. Do not treat the agent's internal `completed` or
   `unverified` status as the benchmark reward.
5. Do not expose the host Docker socket, host credentials, user home directory, or hidden verifier
   files to the agent container.
6. Separate capability-subset results from whole-dataset diagnostic results.
7. Do not claim leaderboard comparability until the integration supports the benchmark's expected
   autonomous terminal workflow and produces adequate execution telemetry.

## Phase 1: Freeze the evaluation contract

Start with:

- Harbor `0.26.0`.
- `terminal-bench/terminal-bench-cpu@4.1.0`.
- One exact coding-agent Git commit.
- One exact OpenRouter model identifier.
- One attempt per task and concurrency of one.
- Network access limited to the required model-provider endpoint.

Terminal-Bench 4.1.0 has 66 tasks in the full dataset and 63 in the CPU-only dataset. The CPU-only
package is the appropriate starting point for local Docker execution. Recheck the official releases
before a future run and update this document if a newer benchmark is intentionally selected.

Record the following in every result set:

- Harbor version and commit, if building from source.
- Dataset name and version.
- Agent and adapter commits.
- Model provider and exact model slug.
- Attempt count and concurrency.
- Environment provider, operating system, CPU/GPU allocation, and network policy.
- All non-default agent settings and resource limits.

## Phase 2: Build a task-compatibility inventory

Classify the CPU tasks before spending model calls. Use task metadata, agent-visible instructions,
and supplied environment characteristics. Do not inspect hidden verifier behavior to tune the agent.

### Compatible

A task is a reasonable candidate when all necessary outcomes can be produced through bounded UTF-8
text edits. Prefer tasks that:

- Have a small, writable work directory.
- Need no terminal exploration or command execution.
- Need no binary input analysis.
- Require no executable-bit, ownership, rename, copy, or deletion operation.
- Fit the agent's file-count, file-size, context, and patch limits.
- Can be solved without installing packages or controlling services.

### Partially compatible

The final artifact is a text edit, but useful exploration, compilation, testing, or repair would
normally require terminal execution. These tasks may be useful for failure analysis but should not
be mixed into the primary compatibility score.

### Incompatible

Classify a task as incompatible when it requires any of the following:

- Binary inspection or generation.
- Package installation or arbitrary command execution.
- Process, service, database, network, or multi-container control.
- File-mode or ownership changes.
- GPU execution.
- Interactive use of compilers, debuggers, CAD tools, theorem provers, or other terminal programs.
- A workspace too large for the agent's enforced repository bounds.

Preserve the inventory with a reason code for every exclusion. This prevents accidental cherry
picking and makes the subset reproducible.

## Phase 3: Implement an out-of-tree Harbor adapter

The preferred integration is a small, separately versioned evaluation package. It should subclass
Harbor's current `BaseInstalledAgent` or `BaseAgent` interface and be supplied through an import
path. It should not require changes to the production CLI for the initial experiment.

The adapter should perform the following work:

1. Install a wheel built from the pinned coding-agent revision into the task container. Avoid
   installing from a moving branch.
2. Discover Harbor's configured work directory instead of assuming `/app`, although `/app` is the
   common default.
3. If the work directory is not a Git root, initialize Git and create a baseline commit. Do this
   only for tasks selected as suitably small; staging a multi-gigabyte workspace would distort the
   trial.
4. Put checkpoints under a trial-local path such as `/tmp/coding-agent-state`, outside the target
   repository.
5. Pass the Harbor instruction to the graph unchanged as the natural-language task.
6. Drive LangGraph directly rather than emulating a terminal with piped input.
7. On plan and patch interrupts, resume with `approve` under an explicitly named policy such as
   `ephemeral_benchmark_auto_approve`.
8. Record the interrupt payload, plan, exact patch, patch hash, decision, final state, and captured
   output under `/logs/agent/`.
9. Return normally when the agent finishes with a task-level failure so Harbor's verifier can award
   zero. Reserve Harbor trial errors for adapter, installation, provider, or infrastructure failure.
10. Redact credentials from commands, logs, checkpoints, exceptions, and saved state.

Direct graph driving is preferable to piping four `approve` lines into the existing CLI. It is
deterministic, exposes every approval event, and avoids depending on terminal prompt formatting.

## Phase 4: Handle validation safely

Do not mount `/var/run/docker.sock` into a Harbor task container. That would weaken the benchmark
isolation boundary and give the nested agent excessive host control.

For the initial adapter, inject an evaluation-only validation implementation that returns an
explicit `not_run` result. Harbor's post-agent verifier remains authoritative. Consequences:

- The initial patch can still be applied and graded.
- The agent's internal result will normally be `unverified`.
- The current repair loop will not run because it receives no failing validation result.
- Harbor's verifier reward, not the internal status, is the evaluation outcome.

If in-container validation is added later, it must be an explicit benchmark mode that executes only
inside the disposable Harbor environment. It must not silently weaken the production agent's
Docker-only validation contract.

## Phase 5: Validate Harbor before evaluating the agent

First install the pinned Harbor release:

```powershell
uv tool install "harbor==0.26.0"
```

Run a small oracle sample to verify dataset download, image startup, task setup, and verification:

```powershell
harbor run `
  -d terminal-bench/terminal-bench-cpu@4.1.0 `
  -a oracle `
  -l 5 `
  -n 1 `
  -k 1
```

The oracle sample must pass before debugging the custom agent. A failure here is a Harbor,
environment, image, or dataset issue rather than evidence about the coding agent.

Then run one hand-selected compatible task:

```powershell
harbor run `
  -d terminal-bench/terminal-bench-cpu@4.1.0 `
  -a your_adapter.harbor_agent:LocalCodingAgent `
  --include-task-name "<task-name>" `
  -n 1 `
  -k 1
```

Supply credentials through Harbor's supported agent-secret or agent-environment mechanism. Never
put a literal key in source control or a reusable command file. The adapter must map the selected
model into `CODING_AGENT_MODEL` and provide the OpenRouter credential expected by the current model
implementation.

### One-task smoke-test checks

- The adapter installs successfully in the task image.
- The resolved work directory is correct.
- Git initialization does not alter task inputs other than adding `.git` metadata.
- The exact instruction reaches the graph.
- Plan and patch interrupts are logged and automatically resumed.
- An approved patch is visible in the Harbor work directory.
- Nested Docker is not exposed or attempted as a host fallback.
- Harbor's verifier runs and records a reward.
- Trial logs contain no API key or other secret.
- Adapter failures and verifier failures are distinguishable.

## Phase 6: Execute in tiers

### Tier 1: Single-task smoke test

Run one compatible task once with concurrency one. Do not proceed until setup, patch persistence,
verification, and logs are correct.

### Tier 2: Small compatibility pilot

Run 5 to 10 compatible tasks once each. Compare their failure modes and inspect every plan, patch,
and verifier result.

### Tier 3: Repeated compatibility evaluation

Run the compatible subset five times per task to measure variance. Keep provider, model, prompt,
resource, and network settings fixed.

### Tier 4: Whole CPU diagnostic pass

Optionally run all 63 CPU tasks once. Treat this as a diagnostic floor, not the primary score. The
result will include tasks known to require capabilities outside the current product scope.

### Tier 5: Full Terminal-Bench

Run the complete 66-task dataset, including GPU and multi-container tasks, only after the agent has
first-class terminal-environment support. A five-attempt full run is 330 trials and should not be
undertaken merely to reconfirm known compatibility limitations.

Start with `-n 1`. Increase concurrency only after confirming that provider rate limits, adapter
installation, task resources, checkpoint paths, and log collection remain isolated per trial.

## Phase 7: Baselines and controls

Use at least these controls:

1. **Oracle:** confirms that task setup and verification are functional.
2. **No-op agent:** provides a negative control where useful.
3. **Established Harbor agent:** run an agent such as `mini-swe-agent` with the same model when the
   provider and model are supported. This helps distinguish model limitations from agent-architecture
   limitations.
4. **Repeat attempts:** separate deterministic adapter failures from stochastic model behavior.

Do not compare agents using different models, network policies, attempt counts, timeouts, or task
subsets without prominently documenting the differences.

## Results and metrics

Report at least:

- Harbor verifier reward and mean reward.
- Pass count and attempt count.
- Compatible, partial, and incompatible task counts.
- Agent setup-error rate.
- Provider/API-error rate.
- Agent timeout rate.
- Plan-generation failure rate.
- Patch-generation and patch-policy rejection rates.
- Patch-application failure rate.
- Internal validation `not_run` count.
- Harbor verifier failure count.
- Runtime distribution.
- Token and cost totals when reliable telemetry becomes available.

Maintain two separate headline results:

1. **Compatible-subset reward:** measures the current plan-and-patch workflow on tasks it can
   reasonably express.
2. **All-CPU diagnostic reward:** measures current coverage of general terminal tasks.

Never blend these into one number. Publish the compatibility inventory alongside the subset result.

## Failure taxonomy

Classify every zero reward or errored trial into one primary category:

- Harbor or environment setup failure.
- Adapter installation/configuration failure.
- Model authentication, rate-limit, or provider failure.
- Workspace rejected because it was not a usable Git root.
- Repository/context budget exhausted.
- Plan generation failed.
- Patch generation failed.
- Patch rejected by path, secret, size, operation, or applicability policy.
- Patch applied but verifier failed.
- Required terminal capability unavailable.
- Required binary, service, GPU, or multi-container capability unavailable.
- Agent timeout.
- Verifier or dataset defect.

This taxonomy is more useful for product development than a single aggregate score.

## Requirements for a leaderboard-comparable integration

Before describing a result as comparable to general Terminal-Bench agents, the coding agent would
need additional capabilities:

- A first-class, auditable headless evaluation policy.
- Support for non-Git task workspaces or a safe workspace-snapshot abstraction.
- A terminal tool that operates only inside Harbor's disposable sandbox.
- In-container testing and command execution instead of nested Docker.
- Support for non-Python projects and tool-driven workflows.
- Safe handling of executable modes and other required filesystem operations.
- Harbor model, base-URL, API-format, and credential integration.
- Cancellation and timeout handling aligned with Harbor's trial lifecycle.
- Valid ATIF `trajectory.json` output.
- Token, cached-token, output-token, and cost accounting.

Those changes would constitute a new benchmark execution mode and a meaningful expansion beyond the
current MVP. They should be designed explicitly rather than introduced through unsafe exceptions to
the existing safety contract.

## Recommended immediate stopping point

Implement the external adapter, pass the one-task smoke test, and complete the 5-to-10-task
compatibility pilot. Review the failure taxonomy and cost before approving a whole-CPU diagnostic
run. Do not begin a repeated full-suite run until the results would answer a question that the known
capability analysis has not already answered.

## Official references

- [Harbor repository and installation](https://github.com/harbor-framework/harbor)
- [Harbor 0.26.0 release](https://github.com/harbor-framework/harbor/releases/tag/v0.26.0)
- [Harbor custom-agent base interface](https://github.com/harbor-framework/harbor/blob/main/src/harbor/agents/base.py)
- [Harbor ATIF documentation](https://github.com/harbor-framework/harbor/blob/main/docs-mintlify/agents/atif.mdx)
- [Terminal-Bench repository](https://github.com/harbor-framework/terminal-bench)
- [Terminal-Bench 4.1.0 release](https://github.com/harbor-framework/terminal-bench/releases/tag/v4.1.0)
- [Terminal-Bench dataset on Harbor Hub](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench/latest)
