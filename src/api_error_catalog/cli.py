"""Command-line interface."""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .analyzer import scan
from .config import ConfigError, load_config
from .loader import SpecLoadError
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
    path: Annotated[
        Path,
        typer.Argument(help="Directory with OpenAPI specs (or a single spec file).", exists=False),
    ],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Report format."),
    ] = OutputFormat.text,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the report to this file instead of stdout."),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to .api-error-catalog.yaml."),
    ] = None,
    fail_on_conflict: Annotated[
        bool,
        typer.Option("--fail-on-conflict", help="Exit with code 1 when conflicts are found."),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress the console summary when writing to a file."),
    ] = False,
) -> None:
    """Scan OpenAPI specs, build the error catalog and report inconsistencies."""
    try:
        cfg = load_config(config, path)
        result = scan(path, cfg)
    except (ConfigError, SpecLoadError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc
    except OSError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc

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

    if fail_on_conflict and result.has_conflicts:
        raise typer.Exit(EXIT_CONFLICT)
    raise typer.Exit(EXIT_OK)


if __name__ == "__main__":  # pragma: no cover
    app()
