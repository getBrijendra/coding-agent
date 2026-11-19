"""Create the disposable Git repository used by the VS Code launch profiles."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SOURCE = WORKSPACE / "examples" / "calculator_repo"
DEBUG_ROOT = WORKSPACE / ".debug"
DESTINATION = DEBUG_ROOT / "calculator_repo"


def _git(*args: str) -> None:
    subprocess.run(
        ["git", "-C", str(DESTINATION), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _remove_destination() -> None:
    resolved_root = DEBUG_ROOT.resolve()
    resolved_destination = DESTINATION.resolve()
    if (
        resolved_destination.parent != resolved_root
        or resolved_destination.name != "calculator_repo"
    ):
        raise RuntimeError(f"Refusing to remove unexpected debug path: {resolved_destination}")
    shutil.rmtree(resolved_destination)


def prepare(*, reset: bool) -> Path:
    if not SOURCE.is_dir():
        raise RuntimeError(f"Example repository source is missing: {SOURCE}")
    DEBUG_ROOT.mkdir(parents=True, exist_ok=True)
    if reset and DESTINATION.exists():
        _remove_destination()
    if DESTINATION.exists():
        try:
            _git("rev-parse", "--show-toplevel")
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Debug target exists but is not a Git repository; run with --reset: {DESTINATION}"
            ) from exc
        print(f"Reusing disposable debug repository: {DESTINATION}")
        return DESTINATION

    shutil.copytree(
        SOURCE,
        DESTINATION,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", ".pytest_cache", ".pytest-tmp", "*.pyc"
        ),
    )
    _git("init", "-q")
    _git("config", "user.email", "debug@example.invalid")
    _git("config", "user.name", "Coding Agent Debug")
    _git("config", "core.autocrlf", "false")
    _git("add", ".")
    _git("commit", "-q", "-m", "debug baseline")
    print(f"Prepared disposable debug repository: {DESTINATION}")
    return DESTINATION


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate only .debug/calculator_repo.",
    )
    arguments = parser.parse_args()
    prepare(reset=arguments.reset)


if __name__ == "__main__":
    main()
