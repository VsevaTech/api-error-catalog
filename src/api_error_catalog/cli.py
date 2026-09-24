"""Command-line interface."""

from __future__ import annotations

import sys
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .analyzer import scan
from .config import Config, ConfigError, load_config
from .governance import DEFAULT_BASELINE_FILENAME, Baseline, BaselineError, load_baseline
from .loader import SpecLoadError
from .models import ScanResult, Severity
from .reporters import RENDERERS

EXIT_OK = 0
EXIT_CONFLICT = 1
EXIT_ERROR = 2


class OutputFormat(StrEnum):
    text = "text"
    markdown = "markdown"
    html = "html"
    json = "json"


app = typer.Typer(
    name="api-error-catalog",
    help="Generate an API error catalog from OpenAPI specifications and detect "
    "inconsistent error contracts across microservices.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)
baseline_app = typer.Typer(
    help="Record existing findings as known debt so CI fails only on new ones.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(baseline_app, name="baseline")

PathArg = Annotated[
    Path, typer.Argument(help="Directory with OpenAPI specs (or a single spec file).", exists=False)
]
ConfigOpt = Annotated[
    Path | None, typer.Option("--config", "-c", help="Path to .api-error-catalog.yaml.")
]
TodayOpt = Annotated[
    str | None,
    typer.Option(
        "--today",
        metavar="YYYY-MM-DD",
        help="Evaluate exception expiry as of this date (default: today, UTC).",
    ),
]


def _fail(exc: Exception) -> typer.Exit:
    typer.echo(f"error: {exc}", err=True)
    return typer.Exit(EXIT_ERROR)


def _parse_today(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigError(f"--today must be a date in YYYY-MM-DD format, got {value!r}") from exc


def _run_scan(
    path: Path, cfg: Config, baseline_path: Path | None, today: date | None
) -> ScanResult:
    baseline = load_baseline(baseline_path) if baseline_path is not None else None
    return scan(path, cfg, baseline=baseline, today=today)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"api-error-catalog {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """API Error Catalog."""


@app.command("scan")
def scan_command(
    path: PathArg,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Report format."),
    ] = OutputFormat.text,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the report to this file instead of stdout."),
    ] = None,
    config: ConfigOpt = None,
    baseline: Annotated[
        Path | None,
        typer.Option(
            "--baseline",
            "-b",
            help="Baseline file with known debt (overrides `baseline:` in the config).",
        ),
    ] = None,
    fail_on_conflict: Annotated[
        bool,
        typer.Option(
            "--fail-on-conflict",
            help="Exit with code 1 when enforced conflicts are found "
            "(new, or covered only by an expired exception).",
        ),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress the console summary when writing to a file."),
    ] = False,
    today: TodayOpt = None,
) -> None:
    """Scan OpenAPI specs, build the error catalog and report inconsistencies."""
    try:
        cfg = load_config(config, path)
        result = _run_scan(path, cfg, baseline or cfg.baseline, _parse_today(today))
    except (ConfigError, SpecLoadError, BaselineError, OSError) as exc:
        raise _fail(exc) from exc

    report = RENDERERS[str(output_format)](result)

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        if not quiet:
            summary = RENDERERS["text"](result) if output_format != OutputFormat.text else report
            sys.stdout.write(summary)
            typer.echo(f"\nReport written to {output}")
    else:
        sys.stdout.write(report)

    if fail_on_conflict and result.blocking:
        raise typer.Exit(EXIT_CONFLICT)
    raise typer.Exit(EXIT_OK)


@baseline_app.command("create")
def baseline_create(
    path: PathArg,
    config: ConfigOpt = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help=f"Baseline file to write (default: `baseline:` from the config, "
            f"else ./{DEFAULT_BASELINE_FILENAME}).",
        ),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite an existing baseline file.")
    ] = False,
    today: TodayOpt = None,
) -> None:
    """Record every current CONFLICT/WARNING (not covered by an exception) as known debt."""
    try:
        cfg = load_config(config, path)
        target = output or cfg.baseline or Path(DEFAULT_BASELINE_FILENAME)
        if target.exists() and not force:
            raise BaselineError(
                f"{target} already exists. Use `baseline update` to prune fixed debt, or "
                "--force to re-create it (this accepts every current finding as debt)."
            )
        result = _run_scan(path, cfg, None, _parse_today(today))
        snapshot = Baseline.from_issues(result.issues)
        snapshot.write(target)
    except (ConfigError, SpecLoadError, BaselineError, OSError) as exc:
        raise _fail(exc) from exc
    by_rule: dict[str, int] = {}
    for entry in snapshot.entries.values():
        by_rule[entry.rule_id] = by_rule.get(entry.rule_id, 0) + 1
    breakdown = ", ".join(f"{rule}: {n}" for rule, n in sorted(by_rule.items())) or "none"
    typer.echo(f"Baseline written to {target}: {len(snapshot)} entries ({breakdown}).")
    raise typer.Exit(EXIT_OK)


@baseline_app.command("update")
def baseline_update(
    path: PathArg,
    config: ConfigOpt = None,
    baseline: Annotated[
        Path | None,
        typer.Option("--baseline", "-b", help="Baseline file (default: `baseline:` from config)."),
    ] = None,
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="Do not write; exit 1 if the baseline still lists debt that has been fixed.",
        ),
    ] = False,
    today: TodayOpt = None,
) -> None:
    """Ratchet: remove fixed debt from the baseline. Never adds new findings."""
    try:
        cfg = load_config(config, path)
        target = baseline or cfg.baseline or Path(DEFAULT_BASELINE_FILENAME)
        current = load_baseline(target)
        result = _run_scan(path, cfg, target, _parse_today(today))
        pruned, removed = current.pruned(result.issues)
    except (ConfigError, SpecLoadError, BaselineError, OSError) as exc:
        raise _fail(exc) from exc

    not_added = [i for i in result.enforced if i.fingerprint and i.severity != Severity.INFO]
    for item in removed:
        typer.echo(f"  - resolved: {item}")
    if check:
        if removed:
            typer.echo(
                f"{target} is out of date: {len(removed)} item(s) were fixed. "
                "Run `api-error-catalog baseline update` and commit the result."
            )
            raise typer.Exit(EXIT_CONFLICT)
        typer.echo(f"{target} is up to date ({len(current)} entries).")
        raise typer.Exit(EXIT_OK)

    if removed:
        pruned.write(target)
        typer.echo(f"Baseline {target}: {len(current)} -> {len(pruned)} entries.")
    else:
        typer.echo(f"Baseline {target} is already up to date ({len(current)} entries).")
    if not_added:
        typer.echo(
            f"{len(not_added)} new finding(s) were NOT added — fix them, add an exception, "
            "or re-create the baseline with `baseline create --force`."
        )
    raise typer.Exit(EXIT_OK)


if __name__ == "__main__":  # pragma: no cover
    app()
