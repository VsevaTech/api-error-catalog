"""Orchestrates loading, extraction, catalog building and rule evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .config import Config
from .extractor import extract
from .loader import LoadedSpec, load_specs
from .models import (
    CatalogEntry,
    ErrorOccurrence,
    Issue,
    LoadWarning,
    ScanResult,
    Severity,
    SpecInfo,
)
from .rules import group_by_code, run_all

REF_RULE_ID = "REF001"
REF_RULE_NAME = "UNRESOLVED_REFERENCE"
SKIP_RULE_ID = "SPEC001"
SKIP_RULE_NAME = "NOT_AN_OPENAPI_DOCUMENT"


def build_catalog(occurrences: list[ErrorOccurrence]) -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    for code, group in group_by_code(occurrences):
        statuses = sorted({o.http_status for o in group})
        services = sorted({o.service for o in group})
        entries.append(
            CatalogEntry(
                error_code=code, http_statuses=statuses, services=services, occurrences=group
            )
        )
    return entries


def analyze_specs(
    specs: list[LoadedSpec], config: Config, skipped: Iterable[Path] = ()
) -> ScanResult:
    infos: list[SpecInfo] = []
    occurrences: list[ErrorOccurrence] = []
    load_warnings: list[LoadWarning] = []
    issues: list[Issue] = []
    for path in skipped:
        warning = LoadWarning(path.name, "skipped: not an OpenAPI 3.x document")
        load_warnings.append(warning)
        issues.append(
            Issue(
                severity=Severity.INFO,
                rule_id=SKIP_RULE_ID,
                rule_name=SKIP_RULE_NAME,
                error_code=None,
                message=f"{warning.source_file}: {warning.message}",
            )
        )
    for spec in specs:
        result = extract(spec, config)
        infos.append(result.spec_info)
        occurrences.extend(result.occurrences)
        load_warnings.extend(result.warnings)
        for warning in result.warnings:
            issues.append(
                Issue(
                    severity=Severity.WARNING,
                    rule_id=REF_RULE_ID,
                    rule_name=REF_RULE_NAME,
                    error_code=None,
                    message=f"{warning.source_file}: {warning.message}",
                )
            )

    issues.extend(run_all(occurrences))
    issues.sort(
        key=lambda i: (_severity_rank(i.severity), i.rule_id, i.error_code or "", i.message)
    )

    return ScanResult(
        specs=infos,
        occurrences=occurrences,
        catalog=build_catalog(occurrences),
        issues=issues,
        load_warnings=load_warnings,
    )


def scan(path: Path, config: Config) -> ScanResult:
    """Load every OpenAPI document under `path` and analyze it. Raises `SpecLoadError`."""
    specs, skipped = load_specs(path, config.include_patterns)
    return analyze_specs(specs, config, skipped)


def _severity_rank(severity: Severity) -> int:
    return {Severity.CONFLICT: 0, Severity.WARNING: 1, Severity.INFO: 2}[severity]
