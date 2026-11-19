"""Docker-only validation with no host execution fallback."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path

from coding_agent.config import Settings
from coding_agent.repository import IGNORED_DIRS, Repository, _is_sensitive, scrub_text
from coding_agent.state import ValidationResult


def _bounded(text: str, maximum: int) -> str:
    text = scrub_text(text)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= maximum:
        return text
    suffix = b"\n...[truncated by coding-agent]"
    return (encoded[: maximum - len(suffix)] + suffix).decode("utf-8", errors="replace")


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in IGNORED_DIRS or _is_sensitive((name,)):
            ignored.add(name)
    return ignored


class DockerSandbox:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _unavailable_reason(self) -> str | None:
        if shutil.which("docker") is None:
            return "Docker executable was not found; host execution is disabled"
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", self.settings.sandbox_image],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"Docker is unavailable: {type(exc).__name__}"
        if result.returncode != 0:
            return (
                f"Sandbox image {self.settings.sandbox_image!r} is not available locally; "
                "automatic image pulls are disabled"
            )
        return None

    def run(self, repository: Repository) -> list[ValidationResult]:
        reason = self._unavailable_reason()
        if reason:
            return [
                ValidationResult(
                    command=list(command), status="not_run", reason=reason, sandbox_type="docker"
                )
                for command in self.settings.validation_commands
            ]
        results: list[ValidationResult] = []
        with tempfile.TemporaryDirectory(prefix="coding-agent-sandbox-") as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            shutil.copytree(
                repository.root,
                workspace,
                symlinks=True,
                ignore=_copy_ignore,
            )
            if os.name != "nt":
                for directory, _subdirs, files in os.walk(workspace):
                    os.chmod(directory, 0o777)
                    for filename in files:
                        target = Path(directory, filename)
                        if not target.is_symlink():
                            os.chmod(target, target.stat().st_mode | 0o666)
            for command in self.settings.validation_commands:
                result = self._run_command(workspace, command)
                results.append(result)
                if result.status != "passed":
                    break
        return results

    def _run_command(self, workspace: Path, command: tuple[str, ...]) -> ValidationResult:
        container_name = f"coding-agent-{uuid.uuid4().hex}"
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--name",
            container_name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "128",
            "--cpus",
            "1.0",
            "--memory",
            "512m",
            "--user",
            "65534:65534",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            f"type=bind,source={workspace.resolve()},target=/workspace",
            "--workdir",
            "/workspace",
            self.settings.sandbox_image,
            *command,
        ]
        started = time.monotonic()
        try:
            process = subprocess.run(
                docker_command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.sandbox_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - started
            with suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    check=False,
                    capture_output=True,
                    timeout=10,
                )
            return ValidationResult(
                command=list(command),
                status="timeout",
                stdout=_bounded(exc.stdout or "", self.settings.max_output_bytes),
                stderr=_bounded(exc.stderr or "", self.settings.max_output_bytes),
                duration_seconds=duration,
                reason=f"Exceeded {self.settings.sandbox_timeout_seconds}s timeout",
            )
        except OSError as exc:
            return ValidationResult(
                command=list(command),
                status="error",
                duration_seconds=time.monotonic() - started,
                reason=f"Docker execution failed: {type(exc).__name__}",
            )
        return ValidationResult(
            command=list(command),
            exit_code=process.returncode,
            stdout=_bounded(process.stdout, self.settings.max_output_bytes),
            stderr=_bounded(process.stderr, self.settings.max_output_bytes),
            duration_seconds=time.monotonic() - started,
            status="passed" if process.returncode == 0 else "failed",
        )
