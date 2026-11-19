from __future__ import annotations

import pytest

from coding_agent.patching import PatchError, apply_validated_patch, validate_patch
from coding_agent.repository import Repository


def test_valid_patch_applies_exact_approved_change(repo_factory, settings, valid_patch) -> None:
    repository = Repository.open(repo_factory(), settings)
    validated = validate_patch(repository, valid_patch, ["hello.py"])

    diff = apply_validated_patch(
        repository,
        validated.text,
        validated.sha256,
        validated.base_hashes,
        list(validated.paths),
    )

    assert (repository.root / "hello.py").read_text(encoding="utf-8") == "new\n"
    assert "+new" in diff


def test_stale_patch_does_not_overwrite_workspace(repo_factory, settings, valid_patch) -> None:
    repository = Repository.open(repo_factory(), settings)
    validated = validate_patch(repository, valid_patch, ["hello.py"])
    (repository.root / "hello.py").write_text("user edit\n", encoding="utf-8")

    with pytest.raises(PatchError, match="stale"):
        apply_validated_patch(
            repository,
            validated.text,
            validated.sha256,
            validated.base_hashes,
            list(validated.paths),
        )
    assert (repository.root / "hello.py").read_text(encoding="utf-8") == "user edit\n"


def test_corrupt_hunk_is_rejected_before_approval(repo_factory, settings) -> None:
    root = repo_factory()
    repository = Repository.open(root, settings)
    corrupt_patch = """diff --git a/hello.py b/hello.py
--- a/hello.py
+++ b/hello.py
@@ -1,11 +1,20 @@
-old
+new
"""

    with pytest.raises(PatchError, match=r"git apply check failed.*corrupt patch"):
        validate_patch(repository, corrupt_patch, ["hello.py"])

    assert (root / "hello.py").read_text(encoding="utf-8") == "old\n"


def test_double_application_is_rejected(repo_factory, settings, valid_patch) -> None:
    repository = Repository.open(repo_factory(), settings)
    validated = validate_patch(repository, valid_patch, ["hello.py"])
    apply_validated_patch(
        repository,
        validated.text,
        validated.sha256,
        validated.base_hashes,
        list(validated.paths),
    )
    with pytest.raises(PatchError, match="stale"):
        apply_validated_patch(
            repository,
            validated.text,
            validated.sha256,
            validated.base_hashes,
            list(validated.paths),
        )


@pytest.mark.parametrize(
    ("patch", "intended"),
    [
        (
            "diff --git a/../../outside b/../../outside\n--- a/../../outside\n"
            "+++ b/../../outside\n@@ -1 +1 @@\n-x\n+y\n",
            ["hello.py"],
        ),
        (
            "diff --git a/.env b/.env\n--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-x\n+y\n",
            [".env"],
        ),
        (
            "diff --git a/hello.py b/other.py\nsimilarity index 100%\n"
            "rename from hello.py\nrename to other.py\n",
            ["hello.py", "other.py"],
        ),
        (
            "diff --git a/hello.py b/hello.py\nGIT binary patch\nliteral 0\n",
            ["hello.py"],
        ),
        (
            "diff --git a/other.py b/other.py\n--- a/other.py\n"
            "+++ b/other.py\n@@ -1 +1 @@\n-x\n+y\n",
            ["hello.py"],
        ),
    ],
)
def test_rejects_malicious_or_out_of_plan_patch(
    repo_factory, settings, patch: str, intended: list[str]
) -> None:
    repository = Repository.open(repo_factory(), settings)
    with pytest.raises(PatchError):
        validate_patch(repository, patch, intended)


def test_new_text_file_is_supported(repo_factory, settings) -> None:
    repository = Repository.open(repo_factory(), settings)
    patch = """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+value = 1
"""
    validated = validate_patch(repository, patch, ["new.py"])
    apply_validated_patch(
        repository, patch, validated.sha256, validated.base_hashes, list(validated.paths)
    )
    assert (repository.root / "new.py").read_text(encoding="utf-8") == "value = 1\n"


def test_patch_containing_credential_is_rejected(repo_factory, settings) -> None:
    repository = Repository.open(repo_factory(), settings)
    patch = """diff --git a/config.py b/config.py
new file mode 100644
--- /dev/null
+++ b/config.py
@@ -0,0 +1 @@
+api_key = "sk-1234567890abcdefghijkl"
"""
    with pytest.raises(PatchError, match="credential"):
        validate_patch(repository, patch, ["config.py"])

