# Local Coding Agent

A local-first, Python-focused coding assistant built as an explicit LangGraph `StateGraph`. It
inspects a Git repository with bounded read-only tools, asks an OpenAI model for a structured plan
and unified diff, pauses for separate human approval of each, safely applies the exact approved
patch, and attempts validation only in a disposable Docker container.

The project deliberately does **not** expose a shell tool to the model, auto-install packages,
commit or push changes, or execute generated code directly on the host.

## Requirements and installation

- Python 3.11 or newer
- Git on `PATH`
- An OpenAI API key and a model that supports tool calling and structured output
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
set OPENAI_API_KEY=your-key
set CODING_AGENT_MODEL=your-structured-output-model
```

PowerShell uses `$env:OPENAI_API_KEY = "your-key"`; POSIX shells use
`export OPENAI_API_KEY=your-key`. The model ID is intentionally not hard-coded.

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

## Safety contract

- Reads reject absolute paths, traversal, out-of-root symlinks, binary/oversized files, Git internals,
  and common credential/key files.
- Common credential forms and configured API keys are redacted from model context, sandbox logs,
  persisted errors, and terminal diagnostics; patches containing credential material are rejected.
- Exploration stops after eight model turns or twenty tool calls and caps files, matches, bytes, and
  stored context.
- Diff policy rejects binary patches, path mismatches, renames/copies, mode changes, symlinks,
  protected paths, files outside the approved plan, oversized patches, and too many files.
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

