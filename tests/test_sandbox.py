from __future__ import annotations

import subprocess

from coding_agent.repository import Repository
from coding_agent.sandbox import DockerSandbox


def test_docker_unavailable_is_not_run(repo_factory, settings, monkeypatch) -> None:
    repository = Repository.open(repo_factory(), settings)
    monkeypatch.setattr("coding_agent.sandbox.shutil.which", lambda _name: None)

    results = DockerSandbox(settings).run(repository)

    assert results[0].status == "not_run"
    assert "host execution is disabled" in results[0].reason


def test_docker_command_is_constrained(repo_factory, settings, monkeypatch) -> None:
    repository = Repository.open(repo_factory(), settings)
    commands: list[list[str]] = []
    monkeypatch.setattr("coding_agent.sandbox.shutil.which", lambda _name: "docker")

    def fake_run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr("coding_agent.sandbox.subprocess.run", fake_run)
    result = DockerSandbox(settings).run(repository)[0]

    assert result.status == "passed"
    run_command = commands[-1]
    assert run_command[
        run_command.index("--network") : run_command.index("--network") + 2
    ] == ["--network", "none"]
    assert "--read-only" in run_command
    assert run_command[run_command.index("--pull") + 1] == "never"
    assert "--cap-drop" in run_command
    assert "no-new-privileges" in run_command
    assert run_command[-4:] == ["python", "-m", "pytest", "-q"]


def test_timeout_and_logs_are_bounded(repo_factory, settings, monkeypatch) -> None:
    repository = Repository.open(repo_factory(), settings)
    monkeypatch.setattr("coding_agent.sandbox.shutil.which", lambda _name: "docker")
    call_count = 0

    def fake_run(command, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise subprocess.TimeoutExpired(command, settings.sandbox_timeout_seconds, output="x" * 100)

    monkeypatch.setattr("coding_agent.sandbox.subprocess.run", fake_run)
    result = DockerSandbox(settings).run(repository)[0]

    assert result.status == "timeout"
    assert "timeout" in result.reason

