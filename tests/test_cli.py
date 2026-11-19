from typer.testing import CliRunner

from coding_agent.cli import app


def test_help_lists_run_and_resume_without_unattended_flag() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "resume" in result.stdout
    assert "--yes" not in result.stdout


def test_run_help_requires_repo_and_task() -> None:
    result = CliRunner().invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    assert "--repo" in result.stdout
    assert "--task" in result.stdout

