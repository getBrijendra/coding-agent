from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from coding_agent.config import Settings
from coding_agent.state import ImplementationPlan, PatchProposal, ReviewDecision


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture
def repo_factory(tmp_path: Path) -> Callable[[dict[str, str] | None], Path]:
    count = 0

    def make(files: dict[str, str] | None = None) -> Path:
        nonlocal count
        count += 1
        root = tmp_path / f"repo-{count}"
        root.mkdir()
        git(root, "init", "-q")
        git(root, "config", "user.email", "tests@example.invalid")
        git(root, "config", "user.name", "Tests")
        git(root, "config", "core.autocrlf", "false")
        for relative, content in (files or {"hello.py": "old\n"}).items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        git(root, "add", ".")
        git(root, "commit", "-q", "-m", "baseline")
        return root

    return make


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "agent-data",
        validation_commands=(("python", "-m", "pytest", "-q"),),
        sandbox_timeout_seconds=5,
    )


class FakeModel:
    def __init__(
        self,
        *,
        patches: list[str] | None = None,
        intended_files: list[str] | None = None,
        reviews: list[ReviewDecision] | None = None,
        research_responses: list[dict[str, Any]] | None = None,
    ) -> None:
        self.patches = list(patches or [])
        self.intended_files = intended_files or ["hello.py"]
        self.reviews = list(reviews or [])
        self.research_responses = list(research_responses or [])
        self.payloads: list[dict[str, Any]] = []

    def research(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self.research_responses:
            return self.research_responses.pop(0)
        return {"content": "Enough context.", "tool_calls": []}

    def create_plan(self, payload: dict[str, Any]) -> ImplementationPlan:
        self.payloads.append(payload)
        return ImplementationPlan(
            goal="Make the requested change",
            steps=["Update the implementation", "Run tests"],
            intended_files=self.intended_files,
            verification_steps=["Run pytest"],
            risks=["Sandbox dependencies may be unavailable"],
        )

    def propose_patch(self, payload: dict[str, Any]) -> PatchProposal:
        self.payloads.append(payload)
        if not self.patches:
            raise AssertionError("No fake patch remains")
        return PatchProposal(patch=self.patches.pop(0), description="Update implementation")

    def review(self, payload: dict[str, Any]) -> ReviewDecision:
        self.payloads.append(payload)
        if self.reviews:
            return self.reviews.pop(0)
        return ReviewDecision(needs_repair=False, findings=["Validation failed"])


@pytest.fixture
def valid_patch() -> str:
    return """diff --git a/hello.py b/hello.py
--- a/hello.py
+++ b/hello.py
@@ -1 +1 @@
-old
+new
"""

