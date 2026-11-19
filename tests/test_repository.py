from __future__ import annotations

import os
from pathlib import Path

import pytest

from coding_agent.repository import Repository, RepositoryError


def test_list_read_search_and_dirty_status(repo_factory, settings) -> None:
    root = repo_factory({"src/app.py": "def greet():\n    return 'hello'\n", "README.md": "Hi\n"})
    repository = Repository.open(root, settings)

    assert repository.list_files() == ["README.md", "src/app.py"]
    assert "return 'hello'" in repository.read_file("src/app.py")
    assert repository.search_text("GREET") == ["src/app.py:1: def greet():"]

    (root / "README.md").write_text("Changed\n", encoding="utf-8")
    assert any("README.md" in item for item in repository.git_status())


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "../../escape",
        "/absolute",
        "C:/Windows/system.ini",
        ".git/config",
        ".env",
        "id_rsa",
        "x\\y",
    ],
)
def test_rejects_unsafe_and_protected_paths(repo_factory, settings, path: str) -> None:
    repository = Repository.open(repo_factory(), settings)
    with pytest.raises(RepositoryError):
        repository.validate_relative_path(path)


def test_rejects_binary_and_oversized_content(repo_factory, settings) -> None:
    root = repo_factory()
    (root / "binary.dat").write_bytes(b"abc\x00def")
    (root / "huge.txt").write_bytes(b"x" * (settings.max_file_bytes + 1))
    repository = Repository.open(root, settings)

    with pytest.raises(RepositoryError, match="Binary"):
        repository.read_file("binary.dat")
    with pytest.raises(RepositoryError, match="exceeds"):
        repository.read_file("huge.txt")


def test_out_of_root_symlink_is_not_listed_or_read(repo_factory, settings, tmp_path: Path) -> None:
    root = repo_factory()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = root / "link.txt"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this platform")
    repository = Repository.open(root, settings)

    assert "link.txt" not in repository.list_files()
    with pytest.raises(RepositoryError, match="escapes"):
        repository.read_file("link.txt")


def test_requires_exact_git_root(repo_factory, settings) -> None:
    root = repo_factory({"src/app.py": "pass\n"})
    with pytest.raises(RepositoryError, match="root"):
        Repository.open(root / "src", settings)


def test_secret_values_are_scrubbed_from_context(repo_factory, settings, monkeypatch) -> None:
    secret = "sk-1234567890abcdefghijkl"
    root = repo_factory({"config.py": f'api_key = "{secret}"\n'})
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    repository = Repository.open(root, settings)

    content = repository.read_file("config.py")
    matches = repository.search_text("api_key")

    assert secret not in content
    assert secret not in "".join(matches)
    assert "[REDACTED]" in content

