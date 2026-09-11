from __future__ import annotations

import json
import subprocess
import sys

import yaml
from tests.conftest import error_response_spec
from typer.testing import CliRunner

from api_error_catalog.cli import app

runner = CliRunner()


def test_exit_code_0_without_conflicts(fixtures_dir):
    result = runner.invoke(app, ["scan", str(fixtures_dir / "clean"), "--fail-on-conflict"])
    assert result.exit_code == 0, result.output
    assert "Conflicts: 0" in result.output


def test_exit_code_0_with_conflicts_when_flag_not_set(examples_dir):
    result = runner.invoke(app, ["scan", str(examples_dir)])
    assert result.exit_code == 0, result.output
    assert "Conflicts: 2" in result.output


def test_exit_code_1_with_conflicts_and_fail_on_conflict(examples_dir):
    result = runner.invoke(app, ["scan", str(examples_dir), "--fail-on-conflict"])
    assert result.exit_code == 1, result.output
    assert "CONFLICT" in result.output


def test_warnings_alone_do_not_fail(write_spec, tmp_path):
    doc = error_response_spec(title="A", path="/a", status="401")
    doc["paths"]["/a"]["get"]["responses"]["401"] = {"description": "no code here"}
    write_spec("a.yaml", doc)
    result = runner.invoke(app, ["scan", str(tmp_path), "--fail-on-conflict"])
    assert result.exit_code == 0, result.output
    assert "Warnings: 1" in result.output


def test_exit_code_2_on_invalid_yaml(fixtures_dir):
    result = runner.invoke(app, ["scan", str(fixtures_dir / "invalid")])
    assert result.exit_code == 2, result.output
    assert "invalid YAML" in result.output


def test_exit_code_2_on_missing_path(tmp_path):
    result = runner.invoke(app, ["scan", str(tmp_path / "missing")])
    assert result.exit_code == 2


def test_exit_code_2_on_bad_config(examples_dir, tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("error_code_fields: not-a-list\n")
    result = runner.invoke(app, ["scan", str(examples_dir), "--config", str(cfg)])
    assert result.exit_code == 2
    assert "error_code_fields" in result.output


def test_config_file_is_picked_up_from_scan_root(write_spec, tmp_path):
    doc = error_response_spec(
        title="A", path="/a", status="400", code_field="errorId", example_code="custom"
    )
    write_spec("a.yaml", doc)
    (tmp_path / ".api-error-catalog.yaml").write_text("error_code_fields: [errorId]\n")
    result = runner.invoke(app, ["scan", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert [c["error_code"] for c in data["catalog"]] == ["custom"]


def test_output_file_written_for_each_format(examples_dir, tmp_path):
    for fmt, suffix in (("markdown", "md"), ("html", "html"), ("json", "json")):
        target = tmp_path / f"catalog.{suffix}"
        result = runner.invoke(
            app, ["scan", str(examples_dir), "--format", fmt, "--output", str(target)]
        )
        assert result.exit_code == 0, result.output
        assert target.exists() and target.stat().st_size > 0
        assert "Report written to" in result.output
    assert json.loads((tmp_path / "catalog.json").read_text())["summary"]["conflicts"] == 2
    assert (tmp_path / "catalog.md").read_text().startswith("# API Error Catalog")
    assert (tmp_path / "catalog.html").read_text().startswith("<!DOCTYPE html>")


def test_quiet_suppresses_console_summary(examples_dir, tmp_path):
    target = tmp_path / "c.md"
    result = runner.invoke(
        app, ["scan", str(examples_dir), "-f", "markdown", "-o", str(target), "-q"]
    )
    assert result.exit_code == 0
    assert result.output == ""


def test_scan_single_file(examples_dir):
    result = runner.invoke(app, ["scan", str(examples_dir / "auth-api.yaml"), "-f", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["summary"]["specifications"] == 1


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "api-error-catalog 0.1.0" in result.output


def test_console_script_entry_point(examples_dir):
    """The installed `api-error-catalog` command must work as a subprocess (exit code 1)."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "api_error_catalog.cli",
            "scan",
            str(examples_dir),
            "--fail-on-conflict",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, proc.stderr
    assert "Conflicts: 2" in proc.stdout


def test_fixture_specs_are_valid_yaml(fixtures_dir):
    for path in (fixtures_dir / "clean").glob("*.yaml"):
        yaml.safe_load(path.read_text())
