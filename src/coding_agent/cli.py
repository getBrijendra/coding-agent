"""Interactive terminal interface for new and resumed coding-agent runs."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Annotated, Any

import typer
from langgraph.types import Command
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from coding_agent.checkpoint import sqlite_checkpointer
from coding_agent.config import Settings
from coding_agent.graph import build_graph
from coding_agent.llm import create_model
from coding_agent.state import AgentState, initial_state

app = typer.Typer(
    name="coding-agent",
    help="Inspect, plan, patch, and Docker-validate a Git repository with explicit approvals.",
    no_args_is_help=True,
)
console = Console()


def _redact(text: str) -> str:
    for name in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "LANGSMITH_API_KEY"):
        secret = os.getenv(name)
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def _interrupt_payloads(result: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for item in result.get("__interrupt__", ()):
        value = getattr(item, "value", item)
        if isinstance(value, dict):
            values.append(value)
    return values


def _snapshot_interrupts(snapshot: Any) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for task in snapshot.tasks:
        for item in task.interrupts:
            value = getattr(item, "value", item)
            if isinstance(value, dict):
                values.append(value)
    return values


def _show_approval(payload: dict[str, Any]) -> None:
    kind = payload.get("kind")
    if kind == "plan_approval":
        plan = payload.get("plan", {})
        console.print(Panel(str(plan.get("goal", "")), title="Implementation plan"))
        console.print("Steps:")
        for number, step in enumerate(plan.get("steps", []), 1):
            console.print(f"  {number}. {step}")
        console.print("Intended files: " + ", ".join(plan.get("intended_files", [])))
        console.print("Verification: " + "; ".join(plan.get("verification_steps", [])))
        if plan.get("risks"):
            console.print("Risks: " + "; ".join(plan["risks"]))
        if payload.get("preexisting_changes"):
            console.print("[yellow]Pre-existing working-tree changes:[/yellow]")
            for change in payload["preexisting_changes"]:
                console.print(f"  {change}")
    elif kind == "patch_approval":
        attempt = int(payload.get("attempt_number", 0))
        title = "Repair patch" if attempt else "Proposed patch"
        console.print(Panel(str(payload.get("description", "")), title=title))
        console.print(Syntax(str(payload.get("patch", "")), "diff", line_numbers=False))
        console.print("Files: " + ", ".join(payload.get("changed_files", [])))
        console.print(f"Patch SHA-256: {payload.get('patch_sha256', '')}")
    console.print(str(payload.get("prompt", "")))


def _ask_decision() -> str:
    while True:
        decision = typer.prompt("Decision", default="reject").strip().casefold()
        if decision in {"approve", "reject"}:
            return decision
        console.print("Enter exactly 'approve' or 'reject'.")


def _show_final(state: AgentState) -> None:
    summary = state.get("final_summary", {})
    table = Table(title="Coding agent result", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Thread", str(summary.get("thread_id", state.get("thread_id", ""))))
    table.add_row("Final status", str(summary.get("status", state.get("status", "unknown"))))
    table.add_row("Plan", str(summary.get("plan_approval") or "not approved"))
    patch_status = "applied" if summary.get("patch_applied") else str(
        summary.get("patch_approval") or "not applied"
    )
    table.add_row("Patch", patch_status)
    table.add_row("Files changed", ", ".join(summary.get("files_changed", [])) or "none")
    validations = summary.get("validation_results", [])
    validation_text = "; ".join(
        f"{' '.join(item.get('command', [])) or '(none)'}: {item.get('status')}"
        for item in validations
    ) or "not run"
    table.add_row("Validation", validation_text)
    if len(summary.get("validation_history", [])) > 1:
        table.add_row("Validation runs", str(len(summary["validation_history"])))
    table.add_row("Repair attempts", str(summary.get("repair_attempts", 0)))
    console.print(table)
    risks = summary.get("unresolved_risks", [])
    if risks:
        console.print("[yellow]Unresolved risks / notes:[/yellow]")
        for risk in risks:
            console.print(f"  - {_redact(str(risk))}")


def _drive(graph: Any, result: dict[str, Any], config: dict[str, Any]) -> AgentState:
    while True:
        payloads = _interrupt_payloads(result)
        if not payloads:
            _show_final(result)
            return result
        payload = payloads[-1]
        _show_approval(payload)
        decision = _ask_decision()
        result = graph.invoke(
            Command(resume={"decision": decision}), config=config, durability="sync"
        )


@app.command("run")
def run_command(
    repo: Annotated[
        Path, typer.Option("--repo", exists=True, file_okay=False, resolve_path=True)
    ],
    task: Annotated[str, typer.Option("--task", help="Natural-language software task.")],
) -> None:
    """Start a new coding-agent thread."""

    settings = Settings()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    try:
        model = create_model(settings)
        with sqlite_checkpointer(settings, target_repo=repo) as checkpointer:
            graph = build_graph(model, settings, checkpointer=checkpointer)
            console.print(f"Thread: [bold]{thread_id}[/bold]")
            result = graph.invoke(
                initial_state(
                    thread_id=thread_id,
                    repo_root=str(repo),
                    task=task,
                    max_repair_attempts=settings.max_repair_attempts,
                ),
                config=config,
                durability="sync",
            )
            _drive(graph, result, config)
    except Exception as exc:
        console.print(f"[red]Run failed safely:[/red] {_redact(str(exc))}")
        raise typer.Exit(code=1) from exc


@app.command("resume")
def resume_command(
    repo: Annotated[
        Path, typer.Option("--repo", exists=True, file_okay=False, resolve_path=True)
    ],
    thread_id: Annotated[
        str, typer.Option("--thread-id", help="Existing persistent thread UUID.")
    ],
) -> None:
    """Resume an interrupted or failed thread from SQLite."""

    settings = Settings()
    config = {"configurable": {"thread_id": thread_id}}
    try:
        uuid.UUID(thread_id)
        model = create_model(settings)
        with sqlite_checkpointer(settings, target_repo=repo) as checkpointer:
            graph = build_graph(model, settings, checkpointer=checkpointer)
            snapshot = graph.get_state(config)
            if not snapshot.values:
                raise RuntimeError(f"No checkpoint found for thread {thread_id}")
            saved_repo = Path(snapshot.values.get("repo_root", "")).resolve()
            if saved_repo != repo.resolve():
                raise RuntimeError(f"Thread belongs to a different repository: {saved_repo}")
            interrupts = _snapshot_interrupts(snapshot)
            if interrupts:
                _show_approval(interrupts[-1])
                result = graph.invoke(
                    Command(resume={"decision": _ask_decision()}),
                    config=config,
                    durability="sync",
                )
            elif snapshot.next:
                result = graph.invoke(None, config=config, durability="sync")
            else:
                result = dict(snapshot.values)
            _drive(graph, result, config)
    except Exception as exc:
        console.print(f"[red]Resume failed safely:[/red] {_redact(str(exc))}")
        raise typer.Exit(code=1) from exc


@app.command("inspect-state", hidden=True)
def inspect_state(thread_id: str, data_dir: Path | None = None) -> None:
    """Print a redacted checkpoint summary for local troubleshooting."""

    settings = Settings(data_dir=data_dir) if data_dir else Settings()
    config = {"configurable": {"thread_id": thread_id}}
    with sqlite_checkpointer(settings) as checkpointer:
        rows = list(checkpointer.list(config, limit=1))
    payload = {"thread_id": thread_id, "checkpoint_found": bool(rows)}
    console.print_json(json.dumps(payload))


if __name__ == "__main__":
    app()
