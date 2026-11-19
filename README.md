# Local Coding Agent

A local-first, Python-focused coding assistant built as an explicit LangGraph `StateGraph`. It
inspects a Git repository with bounded read-only tools, asks an OpenRouter model for a structured plan
and unified diff, pauses for separate human approval of each, safely applies the exact approved
patch, and attempts validation only in a disposable Docker container.

The project deliberately does **not** expose a shell tool to the model, auto-install packages,
commit or push changes, or execute generated code directly on the host.

## Requirements and installation

- Python 3.11 or newer
- Git on `PATH`
- An OpenRouter API key
- Docker plus a locally available sandbox image for validation (optional but recommended)

Install for use:

```console
python -m pip install -e .
```

Install the development tools and run the offline test suite:

```console
python -m pip install -e ".[dev]"
python -m pytest -q
ruff check .
```

Set live-run configuration in the process environment. `.env.example` is a reference template, but
the CLI deliberately does not auto-load `.env` files because its working directory may be an
untrusted target repository:

```console
set OPENROUTER_API_KEY=your-key
set CODING_AGENT_MODEL=cohere/north-mini-code:free
```

PowerShell uses `$env:OPENROUTER_API_KEY = "your-key"`; POSIX shells use
`export OPENROUTER_API_KEY=your-key`. `CODING_AGENT_MODEL` is optional and defaults to Cohere North
Mini Code (free). `OPENAI_API_KEY` remains accepted as a compatibility alias for existing setups.

## CLI workflow

The target must be the root of an existing Git working tree. Start a new thread:

```console
coding-agent run --repo /path/to/python-repo --task "Add input validation and tests"
```

The CLI prints a plan and accepts only the explicit words `approve` or `reject`. Plan approval does
not approve a write. It next shows the exact unified diff, its SHA-256, and affected files, then asks
again. Any repair patch after failed validation gets its own patch approval.

The thread UUID is printed immediately. Resume an interrupted process, even after restart, with:

```console
coding-agent resume --repo /path/to/python-repo --thread-id <uuid>
```

Checkpoints default to the user's application-data directory, outside the target repository. Set
`CODING_AGENT_DATA_DIR` to change it; paths inside the target repository are rejected.

## Docker validation

Validation never falls back to host execution. The default command and image are:

```text
python -m pytest -q
python:3.12-slim
```

The agent does not pull images or install dependencies. Prepare a trusted local image containing
your project's test dependencies, then configure it, for example:

```console
docker build -t my-project-test-image -f Dockerfile.test .
set CODING_AGENT_SANDBOX_IMAGE=my-project-test-image
set CODING_AGENT_VALIDATION_COMMAND=python -m pytest -q
```

Docker runs with no network, a read-only container filesystem, a temporary repository copy, a
non-root user, dropped Linux capabilities, `no-new-privileges`, and CPU, memory, process, log, and
time limits. If Docker or the configured local image is unavailable, the final status is
`unverified` and validation is `not_run`.

## Example repository

The files under `examples/calculator_repo` form a tiny example. Make it a disposable Git repository
before pointing the agent at it:

```console
cd examples/calculator_repo
git init
git add .
git commit -m "example baseline"
python -m pytest -q
```

Then try the documented `coding-agent run` command against that directory. Do not use a valuable
dirty repository for a first live-model smoke test.

## Debug the whole flow in VS Code

The checked-in `.vscode` profiles let you follow the workflow without modifying the source example.
First select a Python interpreter in VS Code and install the development dependencies:

```console
python -m pip install -e ".[dev]"
```

Open **Run and Debug** and choose one of these profiles:

- **Coding Agent: fake full flow + repair** runs the deterministic repair-loop integration test.
  It needs no API key, model request, or Docker image, so it is the quickest way to step through
  graph routing and repeated patch approval.
- **Coding Agent: interactive example (new thread)** recreates `.debug/calculator_repo` as a clean
  Git repository, prompts for a coding problem (default: add subtraction), then runs the real CLI in
  the integrated terminal. Put `OPENROUTER_API_KEY` in the root `.env` or the
  VS Code process environment. The launch profile deliberately loads that root developer `.env`;
  the application itself still never discovers or loads target-repository `.env` files.
- **Coding Agent: resume interactive thread** preserves the disposable repository and prompts for
  the thread UUID printed by the first launch. Use it to observe SQLite restart/resume behavior.
- **Python: debug current test file** runs whichever test file is active in the editor.

A useful breakpoint sequence is:

1. `graph.py` in `build_graph` to see the explicit topology.
2. `nodes.py` in `inspect_repo`, `research_agent`, and `create_plan`.
3. `nodes.py` in `approve_plan` and `approve_patch`; inspect the value returned by `interrupt()`.
4. `patching.py` in `validate_patch` and `apply_validated_patch`.
5. `sandbox.py` in `DockerSandbox.run` and `_run_command`.
6. `nodes.py` in `review_result` and `finish` to see repair routing and the final status.

Type exactly `approve` or `reject` at each interactive prompt. Inspect the evolving target under
`.debug/calculator_repo` and checkpoints under `.debug/agent-data`. The new-thread launch deletes
and rebuilds only the disposable calculator target; the resume launch never resets it. You can also
run **Tasks: Run Task → Debug: reset example repository**, **Quality: pytest**, or **Quality: Ruff**.
If the configured Docker image is absent, stopping at the sandbox node and observing `not_run` is the
expected fail-closed path.

## Safety contract

- Reads reject absolute paths, traversal, out-of-root symlinks, binary/oversized files, Git internals,
  and common credential/key files.
- Common credential forms and configured API keys are redacted from model context, sandbox logs,
  persisted errors, and terminal diagnostics; patches containing credential material are rejected.
- Exploration stops after eight model turns or twenty tool calls and caps files, matches, bytes, and
  stored context.
- Diff policy rejects binary patches, path mismatches, renames/copies, mode changes, symlinks,
  protected paths, files outside the approved plan, oversized patches, and too many files.
- A read-only `git apply --check` rejects malformed or non-applicable model patches before they are
  shown for approval; proposal generation gets one bounded retry with the exact failure reason.
- File hashes captured with the preview must still match immediately before `git apply --check` and
  `git apply`; otherwise the patch is stale and no write occurs.
- Existing working-tree changes are surfaced and preserved. The tool never resets, cleans, commits,
  pushes, edits Git configuration, or infers approval from model output or a `--yes` flag.
- Repair is capped at two attempts after the initial patch. Every repair is separately approved.

## Known limitations

This MVP is single-user and Python-focused. It has no web UI, browser, remote Git hosting, semantic
index, multi-agent delegation, arbitrary command selection, dependency installation, or unattended
mode. Diff parsing intentionally rejects renames and exotic Git patch features. The default Docker
image does not include pytest, so meaningful validation normally requires a prebuilt project image.
SQLite is appropriate for a local CLI, not concurrent multi-user service operation. Repository
prompt injection is treated as untrusted data, but users must still inspect every proposed plan and
patch carefully.

See [docs/architecture.md](docs/architecture.md) for component and state-flow details.

