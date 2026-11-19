"""Bounded, read-only repository operations and workspace preconditions."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from coding_agent.config import Settings


class RepositoryError(RuntimeError):
    """Raised when a repository or requested path violates policy."""


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".pytest-tmp",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    ".tox",
    ".nox",
    "coverage",
    "htmlcov",
}

_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"(?i)(\b[\w.-]*(?:api[_-]?key|token|password|secret)[\w.-]*\b"
        r"\s*[:=]\s*)([\"'])([^\"'\r\n]{8,})([\"'])"
    ),
)


def scrub_text(text: str) -> str:
    """Remove common credential forms and any configured process secrets from model/log text."""

    scrubbed = text
    for variable in ("OPENAI_API_KEY", "LANGSMITH_API_KEY"):
        value = os.getenv(variable)
        if value:
            scrubbed = scrubbed.replace(value, "[REDACTED]")
    scrubbed = _SECRET_PATTERNS[0].sub("[REDACTED]", scrubbed)
    scrubbed = _SECRET_PATTERNS[1].sub("[REDACTED]", scrubbed)
    scrubbed = _SECRET_PATTERNS[2].sub(r"\1\2[REDACTED]\4", scrubbed)
    return scrubbed


def contains_secret(text: str) -> bool:
    return scrub_text(text) != text


def _is_sensitive(parts: tuple[str, ...]) -> bool:
    lowered = tuple(part.casefold() for part in parts)
    if any(part in {".git", ".ssh", ".aws", ".gnupg"} for part in lowered):
        return True
    name = lowered[-1] if lowered else ""
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if name in {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "credentials",
        "credentials.json",
        "secrets.json",
        "token.json",
        ".netrc",
        ".npmrc",
        ".pypirc",
    }:
        return True
    if name in {"secret", "secrets", "token", "tokens"} or name.startswith(
        ("secrets.", "credentials.", "tokens.")
    ):
        return True
    return name.endswith((".pem", ".key", ".p12", ".pfx"))


def _run_git(root: Path, *args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RepositoryError("Git is required but was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RepositoryError("Git operation timed out") from exc


@dataclass(slots=True)
class Repository:
    root: Path
    settings: Settings

    @classmethod
    def open(cls, path: str | Path, settings: Settings) -> Repository:
        requested = Path(path).expanduser().resolve(strict=True)
        if not requested.is_dir():
            raise RepositoryError(f"Repository path is not a directory: {requested}")
        result = _run_git(requested, "rev-parse", "--show-toplevel")
        if result.returncode != 0:
            raise RepositoryError(f"Not a Git working tree: {requested}")
        git_root = Path(result.stdout.strip()).resolve(strict=True)
        if git_root != requested:
            raise RepositoryError(
                f"Pass the Git working-tree root, not a subdirectory (expected {git_root})"
            )
        return cls(root=requested, settings=settings)

    def validate_relative_path(self, raw_path: str, *, must_exist: bool = False) -> Path:
        if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
            raise RepositoryError("Path must be a non-empty string")
        if "\\" in raw_path:
            raise RepositoryError("Paths must use forward slashes")
        pure = PurePosixPath(raw_path)
        if any(":" in part for part in pure.parts):
            raise RepositoryError(f"Drive-qualified or colon paths are denied: {raw_path}")
        if (
            pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts)
        ) and raw_path != ".":
            raise RepositoryError(f"Unsafe repository path: {raw_path}")
        parts = tuple(part for part in pure.parts if part != ".")
        if _is_sensitive(parts):
            raise RepositoryError(f"Access to protected path is denied: {raw_path}")
        candidate = self.root.joinpath(*parts)
        try:
            resolved = candidate.resolve(strict=must_exist)
        except FileNotFoundError as exc:
            raise RepositoryError(f"Path does not exist: {raw_path}") from exc
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise RepositoryError(f"Path escapes repository root: {raw_path}") from exc
        if must_exist and not resolved.exists():
            raise RepositoryError(f"Path does not exist: {raw_path}")
        return resolved

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def list_files(self, path: str = ".") -> list[str]:
        base = self.validate_relative_path(path, must_exist=True)
        if not base.is_dir():
            raise RepositoryError(f"Not a directory: {path}")
        files: list[str] = []
        for current, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in IGNORED_DIRS and not Path(current, name).is_symlink()
            )
            for filename in sorted(filenames):
                candidate = Path(current, filename)
                rel = self.relative(candidate)
                try:
                    safe = self.validate_relative_path(rel, must_exist=True)
                except RepositoryError:
                    continue
                if safe.is_file() and not safe.is_symlink():
                    files.append(rel)
                if len(files) >= self.settings.max_files:
                    return files
        return files

    def read_file(self, path: str) -> str:
        candidate = self.validate_relative_path(path, must_exist=True)
        if not candidate.is_file() or candidate.is_symlink():
            raise RepositoryError(f"Not a regular file: {path}")
        size = candidate.stat().st_size
        if size > self.settings.max_file_bytes:
            raise RepositoryError(
                f"File exceeds {self.settings.max_file_bytes} byte read limit: {path}"
            )
        data = candidate.read_bytes()
        if b"\x00" in data[:8_192]:
            raise RepositoryError(f"Binary files cannot be read: {path}")
        try:
            return scrub_text(data.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise RepositoryError(f"File is not valid UTF-8 text: {path}") from exc

    def search_text(self, query: str, path: str = ".") -> list[str]:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise RepositoryError("Search query must contain 1 to 500 characters")
        base = self.validate_relative_path(path, must_exist=True)
        candidates = [self.relative(base)] if base.is_file() else self.list_files(path)
        needle = query.casefold()
        results: list[str] = []
        for rel in candidates:
            try:
                content = self.read_file(rel)
            except RepositoryError:
                continue
            for line_number, line in enumerate(content.splitlines(), 1):
                if needle in line.casefold():
                    excerpt = line.strip()[:300]
                    results.append(f"{rel}:{line_number}: {excerpt}")
                    if len(results) >= self.settings.max_search_results:
                        return results
        return results

    def git_status(self) -> list[str]:
        result = _run_git(self.root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        if result.returncode != 0:
            raise RepositoryError(result.stderr.strip() or "Unable to read Git status")
        records = result.stdout.split("\x00")
        changes: list[str] = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            status = record[:2]
            path = record[3:]
            if status[0] in {"R", "C"} and index < len(records):
                destination = records[index]
                index += 1
                changes.append(f"{status} {path} -> {destination}")
            else:
                changes.append(f"{status} {path}")
        return changes

    def summary(self) -> str:
        files = self.list_files()
        status = self.git_status()
        configs = [
            path
            for path in files
            if Path(path).name
            in {"pyproject.toml", "setup.cfg", "tox.ini", "package.json", "Cargo.toml"}
        ]
        lines = [
            f"Git root: {self.root}",
            f"Visible files: {len(files)} (bounded at {self.settings.max_files})",
            f"Tool/config files: {', '.join(configs) if configs else 'none detected'}",
            f"Pre-existing changes: {len(status)}",
            "Files:",
            *files,
        ]
        return "\n".join(lines)

    def file_hashes(self, paths: list[str]) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for path in paths:
            candidate = self.validate_relative_path(path, must_exist=False)
            if not candidate.exists():
                hashes[path] = "<absent>"
                continue
            if not candidate.is_file() or candidate.is_symlink():
                raise RepositoryError(f"Patch target is not a regular file: {path}")
            if candidate.stat().st_size > self.settings.max_file_bytes:
                raise RepositoryError(f"Patch target exceeds file size limit: {path}")
            hashes[path] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        return hashes

