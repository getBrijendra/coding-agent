"""Explicit LangGraph orchestration for the coding workflow."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from coding_agent.config import Settings
from coding_agent.llm import CodingModel
from coding_agent.nodes import AgentNodes
from coding_agent.sandbox import DockerSandbox
from coding_agent.state import AgentState


def _continue_or_finish(state: AgentState) -> Literal["continue", "finish"]:
    return "finish" if state.get("status") == "failed" else "continue"


def _plan_route(state: AgentState) -> Literal["propose_patch", "finish"]:
    return "propose_patch" if state.get("plan_approval") == "approve" else "finish"


def _proposal_route(state: AgentState) -> Literal["approve_patch", "finish"]:
    return "finish" if state.get("status") == "failed" else "approve_patch"


def _patch_route(state: AgentState) -> Literal["apply_patch", "finish"]:
    return "apply_patch" if state.get("patch_approval") == "approve" else "finish"


def _apply_route(state: AgentState) -> Literal["validate_in_sandbox", "finish"]:
    return "finish" if state.get("status") == "failed" else "validate_in_sandbox"


def _review_route(state: AgentState) -> Literal["propose_patch", "finish"]:
    return "propose_patch" if state.get("next_action") == "repair" else "finish"


def build_graph(
    model: CodingModel,
    settings: Settings,
    *,
    checkpointer: Any,
    sandbox: DockerSandbox | None = None,
) -> Any:
    """Build and compile the graph with injected model and effect boundaries."""

    nodes = AgentNodes(model=model, settings=settings, sandbox=sandbox or DockerSandbox(settings))
    workflow = StateGraph(AgentState)
    workflow.add_node("inspect_repo", nodes.inspect_repo)
    workflow.add_node("research_agent", nodes.research_agent)
    workflow.add_node("create_plan", nodes.create_plan)
    workflow.add_node("approve_plan", nodes.approve_plan)
    workflow.add_node("propose_patch", nodes.propose_patch)
    workflow.add_node("approve_patch", nodes.approve_patch)
    workflow.add_node("apply_patch", nodes.apply_patch)
    workflow.add_node("validate_in_sandbox", nodes.validate_in_sandbox)
    workflow.add_node("review_result", nodes.review_result)
    workflow.add_node("finish", nodes.finish)

    workflow.add_edge(START, "inspect_repo")
    workflow.add_conditional_edges(
        "inspect_repo", _continue_or_finish, {"continue": "research_agent", "finish": "finish"}
    )
    workflow.add_conditional_edges(
        "research_agent", _continue_or_finish, {"continue": "create_plan", "finish": "finish"}
    )
    workflow.add_conditional_edges(
        "create_plan", _continue_or_finish, {"continue": "approve_plan", "finish": "finish"}
    )
    workflow.add_conditional_edges(
        "approve_plan", _plan_route, {"propose_patch": "propose_patch", "finish": "finish"}
    )
    workflow.add_conditional_edges(
        "propose_patch",
        _proposal_route,
        {"approve_patch": "approve_patch", "finish": "finish"},
    )
    workflow.add_conditional_edges(
        "approve_patch", _patch_route, {"apply_patch": "apply_patch", "finish": "finish"}
    )
    workflow.add_conditional_edges(
        "apply_patch",
        _apply_route,
        {"validate_in_sandbox": "validate_in_sandbox", "finish": "finish"},
    )
    workflow.add_edge("validate_in_sandbox", "review_result")
    workflow.add_conditional_edges(
        "review_result", _review_route, {"propose_patch": "propose_patch", "finish": "finish"}
    )
    workflow.add_edge("finish", END)
    return workflow.compile(checkpointer=checkpointer)

