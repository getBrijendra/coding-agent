# Architecture

The application uses an explicit `langgraph.graph.StateGraph`; it does not use a prebuilt ReAct
agent. Model calls are injected behind `CodingModel`, allowing deterministic offline tests.

```text
START -> inspect_repo -> research_agent -> create_plan -> approve_plan (interrupt)
                                                      reject -> finish
approve -> propose_patch -> approve_patch (interrupt) -> apply_patch -> Docker validation
                         reject -> finish                                |
                               finish <- review_result <- validation ----+
                                            |
                                            +-- repair budget -> propose_patch
```

## Boundaries

- `repository.py` implements workspace confinement and the bounded read-only operations.
- `llm.py` owns tool calling and structured model output; prompts live in `prompts.py`.
- `patching.py` treats model output only as data, parses and validates it, captures base hashes, then
  uses argument-vector Git subprocesses for dry-run and application.
- `sandbox.py` is the only generated-code execution path. It copies the repository to a temporary
  directory and invokes a fixed command in a constrained, network-disabled Docker container.
- `checkpoint.py` owns a SQLite connection outside the target repository.
- `nodes.py` keeps reasoning and deterministic effects in separate graph nodes. Interrupts occur
  before all writes, and approved patch hashes are persisted in graph state.

Checkpoint state contains strings, lists, dictionaries, numbers, and approval/result records. It
does not contain API keys, model clients, file handles, database connections, or live processes.
The UUID `thread_id` is always supplied through `configurable.thread_id`.

## Failure semantics

`completed` means all configured Docker commands exited zero. `unverified` means a patch was applied
but secure validation did not run. `partial` means the workspace changed but validation still fails,
timed out, errored, or exhausted the repair budget. `failed` means planning/application could not
complete safely. `rejected` means the user declined a plan or patch. The final report never upgrades
`not_run` to success.

