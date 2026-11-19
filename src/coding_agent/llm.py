"""Injectable model interface and ChatOpenAI implementation."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI

from coding_agent.config import Settings
from coding_agent.prompts import (
    PATCH_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
    RESEARCH_SYSTEM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
)
from coding_agent.state import (
    ImplementationPlan,
    PatchProposal,
    ResearchResponse,
    ReviewDecision,
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "cohere/north-mini-code:free"

RESEARCH_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "List bounded repository files beneath an optional relative directory.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
            "additionalProperties": False,
        },
    },
    {
        "name": "search_text",
        "description": "Search readable repository text for a literal query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string", "default": "."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read one bounded UTF-8 text file using a repository-relative path.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
]


class CodingModel(Protocol):
    def research(self, messages: list[dict[str, Any]]) -> ResearchResponse: ...

    def create_plan(self, payload: dict[str, Any]) -> ImplementationPlan: ...

    def propose_patch(self, payload: dict[str, Any]) -> PatchProposal: ...

    def review(self, payload: dict[str, Any]) -> ReviewDecision: ...


def _to_messages(messages: list[dict[str, Any]]) -> list[Any]:
    converted: list[Any] = [SystemMessage(content=RESEARCH_SYSTEM_PROMPT)]
    for message in messages:
        role = message.get("role")
        content = str(message.get("content", ""))
        if role == "user":
            converted.append(HumanMessage(content=content))
        elif role == "assistant":
            converted.append(AIMessage(content=content, tool_calls=message.get("tool_calls", [])))
        elif role == "tool":
            converted.append(
                ToolMessage(content=content, tool_call_id=str(message.get("tool_call_id", "")))
            )
    return converted


class OpenAICodingModel:
    """Thin adapter so graph tests can replace all network-facing behavior."""

    def __init__(self, model_name: str, api_key: str) -> None:
        self.client = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            temperature=0,
            max_retries=2,
        )

    def research(self, messages: list[dict[str, Any]]) -> ResearchResponse:
        response = self.client.bind_tools(RESEARCH_TOOLS).invoke(_to_messages(messages))
        content = response.content if isinstance(response.content, str) else str(response.content)
        calls = [
            {
                "id": str(call.get("id", "")),
                "name": str(call.get("name", "")),
                "args": dict(call.get("args", {})),
            }
            for call in response.tool_calls
        ]
        return {"content": content, "tool_calls": calls}

    def create_plan(self, payload: dict[str, Any]) -> ImplementationPlan:
        model = self.client.with_structured_output(ImplementationPlan, method="function_calling")
        return model.invoke(
            [SystemMessage(content=PLAN_SYSTEM_PROMPT), HumanMessage(content=json.dumps(payload))]
        )

    def propose_patch(self, payload: dict[str, Any]) -> PatchProposal:
        model = self.client.with_structured_output(PatchProposal, method="function_calling")
        return model.invoke(
            [SystemMessage(content=PATCH_SYSTEM_PROMPT), HumanMessage(content=json.dumps(payload))]
        )

    def review(self, payload: dict[str, Any]) -> ReviewDecision:
        model = self.client.with_structured_output(ReviewDecision, method="function_calling")
        return model.invoke(
            [SystemMessage(content=REVIEW_SYSTEM_PROMPT), HumanMessage(content=json.dumps(payload))]
        )


def create_model(settings: Settings) -> CodingModel:
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for live runs")
    model_name = settings.model_name or OPENROUTER_MODEL
    return OpenAICodingModel(model_name, api_key)
