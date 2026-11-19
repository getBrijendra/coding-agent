"""Durable SQLite checkpointer lifecycle."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from coding_agent.config import Settings


@contextmanager
def sqlite_checkpointer(
    settings: Settings, *, target_repo: str | Path | None = None
) -> Iterator[SqliteSaver]:
    settings.ensure_data_dir()
    checkpoint_path = settings.checkpoint_path.expanduser().resolve()
    if target_repo is not None:
        repository = Path(target_repo).expanduser().resolve()
        if checkpoint_path == repository or repository in checkpoint_path.parents:
            raise RuntimeError("Checkpoint database must be stored outside the target repository")
    connection = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        yield SqliteSaver(connection)
    finally:
        connection.close()

