"""Orchestrates loading, extraction, catalog building and rule evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from .config import Config
from .extractor import extract
from .governance import Baseline, annotate, apply_governance
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
from .rules import (
    REF_RULE_ID,
    REF_RULE_NAME,
    SKIP_RULE_ID,
    SKIP_RULE_NAME,
    group_by_code,
    run_all,
)


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
    specs: list[LoadedSpec],
    config: Config,
    skipped: Iterable[Path] = (),
    *,
    baseline: Baseline | None = None,
    today: date | None = None,
) -> ScanResult:
    """Analyze loaded specs. Governance (baseline + `config.exceptions`) is applied when
    either is present; `today` defaults to the current UTC date."""
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
    governance = None
    if baseline is not None or config.exceptions:
        governance, extra = apply_governance(
            issues,
            exceptions=config.exceptions,
            baseline=baseline,
            today=today or datetime.now(UTC).date(),
            expiry_warning_days=config.exception_expiry_warning_days,
        )
        issues.extend(extra)
    else:
        annotate(issues)
    issues.sort(
        key=lambda i: (_severity_rank(i.severity), i.rule_id, i.error_code or "", i.message)
    )

    return ScanResult(
        specs=infos,
        occurrences=occurrences,
        catalog=build_catalog(occurrences),
        issues=issues,
        load_warnings=load_warnings,
        governance=governance,
    )


def scan(
    path: Path,
    config: Config,
    *,
    baseline: Baseline | None = None,
    today: date | None = None,
) -> ScanResult:
    """Load every OpenAPI document under `path` and analyze it. Raises `SpecLoadError`."""
    specs, skipped = load_specs(path, config.include_patterns)
    return analyze_specs(specs, config, skipped, baseline=baseline, today=today)


def _severity_rank(severity: Severity) -> int:
    return {Severity.CONFLICT: 0, Severity.WARNING: 1, Severity.INFO: 2}[severity]
