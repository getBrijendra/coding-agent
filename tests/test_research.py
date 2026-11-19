from conftest import FakeModel

from coding_agent.nodes import AgentNodes
from coding_agent.sandbox import DockerSandbox
from coding_agent.state import initial_state


def test_research_tool_call_budget_is_enforced(repo_factory, settings) -> None:
    root = repo_factory({"one.py": "one\n", "two.py": "two\n"})
    limited = type(settings)(
        data_dir=settings.data_dir,
        max_tool_calls=2,
        max_research_turns=8,
    )
    calls = [
        {"id": f"call-{index}", "name": "read_file", "args": {"path": "one.py"}}
        for index in range(5)
    ]
    model = FakeModel(research_responses=[{"content": "", "tool_calls": calls}])
    nodes = AgentNodes(model=model, settings=limited, sandbox=DockerSandbox(limited))
    state = initial_state(
        thread_id="thread", repo_root=str(root), task="inspect", max_repair_attempts=2
    )
    state["repo_summary"] = "summary"

    result = nodes.research_agent(state)

    assert result["tool_call_count"] == 2
    assert result["research_turns"] == 1

