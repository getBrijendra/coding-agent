from __future__ import annotations

import uuid

from conftest import FakeModel
from langgraph.types import Command
from test_graph import FakeSandbox

from coding_agent.checkpoint import sqlite_checkpointer
from coding_agent.graph import build_graph
from coding_agent.state import initial_state


def test_sqlite_restart_resumes_same_interrupt(repo_factory, settings, valid_patch) -> None:
    root = repo_factory()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    with sqlite_checkpointer(settings, target_repo=root) as checkpointer:
        graph = build_graph(
            FakeModel(), settings, checkpointer=checkpointer, sandbox=FakeSandbox([])
        )
        result = graph.invoke(
            initial_state(
                thread_id=thread_id,
                repo_root=str(root),
                task="Change it",
                max_repair_attempts=2,
            ),
            config,
            durability="sync",
        )
        assert result["__interrupt__"][0].value["kind"] == "plan_approval"

    with sqlite_checkpointer(settings, target_repo=root) as checkpointer:
        rebuilt = build_graph(
            FakeModel(patches=[valid_patch]),
            settings,
            checkpointer=checkpointer,
            sandbox=FakeSandbox([]),
        )
        result = rebuilt.invoke(
            Command(resume={"decision": "approve"}), config, durability="sync"
        )
        assert result["__interrupt__"][0].value["kind"] == "patch_approval"
        assert rebuilt.get_state(config).values["thread_id"] == thread_id


def test_checkpoint_path_inside_target_is_rejected(repo_factory, settings) -> None:
    root = repo_factory()
    unsafe = type(settings)(data_dir=root / ".agent-data")
    try:
        with sqlite_checkpointer(unsafe, target_repo=root):
            raise AssertionError("context should not open")
    except RuntimeError as exc:
        assert "outside" in str(exc)

