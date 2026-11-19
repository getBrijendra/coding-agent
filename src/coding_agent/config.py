"""Application configuration and enforced resource limits."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path


def _default_data_dir() -> Path:
    configured = os.getenv("CODING_AGENT_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "coding-agent"


def _validation_command() -> tuple[str, ...]:
    raw = os.getenv("CODING_AGENT_VALIDATION_COMMAND", "python -m pytest -q")
    # This argv executes in the Linux Docker sandbox, so POSIX quoting is intentional.
    command = tuple(shlex.split(raw, posix=True))
    if not command:
        raise ValueError("CODING_AGENT_VALIDATION_COMMAND cannot be empty")
    return command


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration; limits are deliberately conservative."""

    data_dir: Path = field(default_factory=_default_data_dir)
    model_name: str | None = field(default_factory=lambda: os.getenv("CODING_AGENT_MODEL"))
    sandbox_image: str = field(
        default_factory=lambda: os.getenv("CODING_AGENT_SANDBOX_IMAGE", "python:3.12-slim")
    )
    validation_commands: tuple[tuple[str, ...], ...] = field(
        default_factory=lambda: (_validation_command(),)
    )
    sandbox_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("CODING_AGENT_SANDBOX_TIMEOUT", "120"))
    )
    max_files: int = 500
    max_file_bytes: int = 128_000
    max_total_context_bytes: int = 512_000
    max_search_results: int = 50
    max_patch_bytes: int = 256_000
    max_patch_files: int = 30
    max_output_bytes: int = 64_000
    max_research_turns: int = 8
    max_tool_calls: int = 20
    max_plan_attempts: int = 2
    max_repair_attempts: int = 2

    @property
    def checkpoint_path(self) -> Path:
        return self.data_dir / "checkpoints.sqlite3"

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

