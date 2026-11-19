"""Unified-diff parsing, policy enforcement, stale checks, and guarded application."""

from __future__ import annotations

import hashlib
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

from coding_agent.repository import Repository, RepositoryError, _run_git, contains_secret


class PatchError(RuntimeError):
    """Raised before a patch can write when it violates a safety precondition."""


@dataclass(frozen=True, slots=True)
class ValidatedPatch:
    text: str
    paths: tuple[str, ...]
    sha256: str
    base_hashes: dict[str, str]


def _parse_diff_path(token: str) -> str | None:
    if token == "/dev/null":
        return None
    if not token.startswith(("a/", "b/")):
        raise PatchError(f"Patch path lacks a/ or b/ prefix: {token}")
    path = token[2:]
    if not path:
        raise PatchError("Patch contains an empty path")
    return path


def _header_tokens(line: str, prefix: str) -> list[str]:
    try:
        values = shlex.split(line[len(prefix) :].strip(), posix=True)
    except ValueError as exc:
        raise PatchError(f"Malformed patch header: {line[:200]}") from exc
    return values


def parse_patch_paths(patch: str) -> tuple[str, ...]:
    if not patch.strip():
        raise PatchError("Patch is empty")
    if contains_secret(patch):
        raise PatchError("Patch appears to contain credential material")
    forbidden = (
        "GIT binary patch",
        "Binary files ",
        "rename from ",
        "rename to ",
        "copy from ",
        "copy to ",
        "old mode ",
        "new mode ",
        "similarity index ",
        "dissimilarity index ",
    )
    paths: list[str] = []
    current_pair: tuple[str, str] | None = None
    seen_old = False
    seen_new = False
    seen_hunk = False
    diff_count = 0
    for line in patch.splitlines():
        if current_pair is None and line.strip() and not line.startswith("diff --git "):
            raise PatchError("Patch contains content before its first diff header")
        if line.startswith(forbidden):
            raise PatchError(f"Unsupported patch operation: {line[:100]}")
        if line.startswith(("new file mode ", "deleted file mode ")) and line.rsplit(
            " ", 1
        )[-1] != "100644":
            raise PatchError(f"Unsupported file mode: {line}")
        if line.startswith("diff --git "):
            if current_pair is not None and not (seen_old and seen_new and seen_hunk):
                raise PatchError("Each diff must include ---, +++, and at least one hunk")
            tokens = _header_tokens(line, "diff --git ")
            if len(tokens) != 2:
                raise PatchError("Malformed diff --git header")
            old_path = _parse_diff_path(tokens[0])
            new_path = _parse_diff_path(tokens[1])
            if old_path is None or new_path is None or old_path != new_path:
                raise PatchError("Renames and mismatched diff paths are not supported")
            current_pair = (old_path, new_path)
            paths.append(new_path)
            diff_count += 1
            seen_old = seen_new = seen_hunk = False
        elif line.startswith("--- "):
            if current_pair is None:
                raise PatchError("--- header appeared before diff --git")
            tokens = _header_tokens(line, "--- ")
            if len(tokens) != 1:
                raise PatchError("Malformed --- header")
            old_path = _parse_diff_path(tokens[0])
            if old_path is not None and old_path != current_pair[0]:
                raise PatchError("Old-file header does not match diff path")
            seen_old = True
        elif line.startswith("+++ "):
            if current_pair is None:
                raise PatchError("+++ header appeared before diff --git")
            tokens = _header_tokens(line, "+++ ")
            if len(tokens) != 1:
                raise PatchError("Malformed +++ header")
            new_path = _parse_diff_path(tokens[0])
            if new_path is not None and new_path != current_pair[1]:
                raise PatchError("New-file header does not match diff path")
            seen_new = True
        elif line.startswith("@@ "):
            if current_pair is None or not (seen_old and seen_new):
                raise PatchError("Patch hunk appeared before file headers")
            seen_hunk = True
    if diff_count == 0:
        raise PatchError("Patch contains no diff --git entries")
    if not (seen_old and seen_new and seen_hunk):
        raise PatchError("Each diff must include ---, +++, and at least one hunk")
    if len(set(paths)) != len(paths):
        raise PatchError("A patch may contain only one diff per path")
    return tuple(paths)


def validate_patch(
    repository: Repository, patch: str, intended_files: list[str]
) -> ValidatedPatch:
    size = len(patch.encode("utf-8"))
    if size > repository.settings.max_patch_bytes:
        raise PatchError(f"Patch exceeds {repository.settings.max_patch_bytes} byte limit")
    paths = parse_patch_paths(patch)
    if len(paths) > repository.settings.max_patch_files:
        raise PatchError(f"Patch changes more than {repository.settings.max_patch_files} files")
    try:
        normalized_intended = {
            repository.relative(repository.validate_relative_path(path, must_exist=False))
            for path in intended_files
        }
        for path in paths:
            repository.validate_relative_path(path, must_exist=False)
    except RepositoryError as exc:
        raise PatchError(str(exc)) from exc
    unexpected = sorted(set(paths) - normalized_intended)
    if unexpected:
        raise PatchError(f"Patch changes files outside the approved plan: {', '.join(unexpected)}")
    try:
        hashes = repository.file_hashes(list(paths))
    except RepositoryError as exc:
        raise PatchError(str(exc)) from exc
    return ValidatedPatch(
        text=patch,
        paths=paths,
        sha256=hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        base_hashes=hashes,
    )


def _git_apply(repository: Repository, patch_path: Path, *, check: bool) -> None:
    args = ["apply", "--whitespace=nowarn"]
    if check:
        args.append("--check")
    args.append(str(patch_path))
    result = _run_git(repository.root, *args)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        action = "check" if check else "application"
        raise PatchError(f"git apply {action} failed: {detail[:2_000]}")


def apply_validated_patch(
    repository: Repository,
    patch: str,
    expected_sha256: str,
    expected_hashes: dict[str, str],
    paths: list[str],
) -> str:
    actual_sha = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    if actual_sha != expected_sha256:
        raise PatchError("Patch content changed after approval")
    try:
        current_hashes = repository.file_hashes(paths)
    except RepositoryError as exc:
        raise PatchError(str(exc)) from exc
    if current_hashes != expected_hashes:
        raise PatchError("Workspace changed after patch preview; refusing stale patch")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".patch", encoding="utf-8", newline="\n", delete=False
    ) as handle:
        handle.write(patch)
        patch_path = Path(handle.name)
    try:
        _git_apply(repository, patch_path, check=True)
        _git_apply(repository, patch_path, check=False)
    finally:
        patch_path.unlink(missing_ok=True)
    result = _run_git(repository.root, "diff", "--no-ext-diff", "--", *paths)
    if result.returncode != 0:
        raise PatchError(result.stderr.strip() or "Unable to capture applied diff")
    return result.stdout

