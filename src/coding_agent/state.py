"""Typed graph state and structured model outputs."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

RunStatus = Literal[
    "initializing",
    "planning",
    "awaiting_plan_approval",
    "awaiting_patch_approval",
    "applying",
    "validating",
    "completed",
    "partial",
    "failed",
    "rejected",
    "unverified",
]
ApprovalDecision = Literal["approve", "reject"]
ValidationStatus = Literal["passed", "failed", "timeout", "not_run", "error"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImplementationPlan(StrictModel):
    """Model-generated plan displayed to the user before any write."""

    goal: str = Field(min_length=1, max_length=2_000)
    steps: list[str] = Field(min_length=1, max_length=20)
    intended_files: list[str] = Field(min_length=1, max_length=30)
    verification_steps: list[str] = Field(min_length=1, max_length=10)
    risks: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("steps", "intended_files", "verification_steps", "risks")
    @classmethod
    def non_blank_items(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values]
        if any(not item for item in cleaned):
            raise ValueError("list items cannot be blank")
        return cleaned


class PatchProposal(StrictModel):
    """A single coherent unified diff and its short description."""

    patch: str = Field(min_length=1)
    description: str = Field(min_length=1, max_length=2_000)


class ReviewDecision(StrictModel):
    """Structured assessment of a failed validation run."""

    needs_repair: bool
    findings: list[str] = Field(default_factory=list, max_length=20)
    repair_instructions: str = Field(default="", max_length=4_000)


class ValidationResult(StrictModel):
    command: list[str]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    status: ValidationStatus
    sandbox_type: str = "docker"
    reason: str = ""


class ResearchToolCall(TypedDict):
    id: str
    name: str
    args: dict[str, Any]


class ResearchResponse(TypedDict):
    content: str
    tool_calls: list[ResearchToolCall]


class AgentState(TypedDict, total=False):
    thread_id: str
    repo_root: str
    task: str
    status: RunStatus
    messages: list[dict[str, Any]]
    repo_summary: str
    relevant_files: list[str]
    context_snippets: dict[str, str]
    research_turns: int
    tool_call_count: int
    plan: dict[str, Any]
    plan_approval: ApprovalDecision | None
    proposed_patch: str
    patch_description: str
    changed_files: list[str]
    all_changed_files: list[str]
    patch_sha256: str
    patch_base_hashes: dict[str, str]
    patch_approval: ApprovalDecision | None
    applied_patch_sha256: str
    applied_diff: str
    attempt_number: int
    max_repair_attempts: int
    validation_results: list[dict[str, Any]]
    validation_history: list[list[dict[str, Any]]]
    review_findings: list[str]
    repair_instructions: str
    next_action: Literal["repair", "finish"]
    preexisting_changes: list[str]
    errors: list[str]
    final_summary: dict[str, Any]


def initial_state(
    *, thread_id: str, repo_root: str, task: str, max_repair_attempts: int
) -> AgentState:
    return {
        "thread_id": thread_id,
        "repo_root": repo_root,
        "task": task,
        "status": "initializing",
        "messages": [],
        "relevant_files": [],
        "all_changed_files": [],
        "context_snippets": {},
        "research_turns": 0,
        "tool_call_count": 0,
        "plan_approval": None,
        "patch_approval": None,
        "attempt_number": 0,
        "max_repair_attempts": max_repair_attempts,
        "validation_results": [],
        "validation_history": [],
        "review_findings": [],
        "repair_instructions": "",
        "preexisting_changes": [],
        "errors": [],
    }

