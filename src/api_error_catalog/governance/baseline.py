"""Baseline file: a reviewed snapshot of known technical debt.

The file is plain, sorted JSON so that `git diff` on it reads as a debt changelog::

    {
      "schema_version": 1,
      "generator": {"name": "api-error-catalog", "version": "0.2.0"},
      "entries": [
        {
          "fingerprint": "ERROR001:user_not_found",
          "rule_id": "ERROR001",
          "rule_name": "SAME_CODE_DIFFERENT_HTTP_STATUS",
          "severity": "CONFLICT",
          "error_code": "user_not_found",
          "facets": ["Auth API -> 404", "Customer API -> 400"]
        }
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__
from ..models import Issue, IssueStatus, Severity
from .fingerprint import is_governance_finding

BASELINE_SCHEMA_VERSION = 1
DEFAULT_BASELINE_FILENAME = "api-error-catalog.baseline.json"


class BaselineError(Exception):
    """Raised when a baseline file is missing or malformed."""


@dataclass(slots=True)
class BaselineEntry:
    fingerprint: str
    rule_id: str
    rule_name: str
    severity: str
    error_code: str | None
    facets: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "error_code": self.error_code,
            "facets": list(self.facets),
        }


@dataclass(slots=True)
class Baseline:
    entries: dict[str, BaselineEntry] = field(default_factory=dict)
    path: Path | None = None

    def __len__(self) -> int:
        return len(self.entries)

    @classmethod
    def from_issues(cls, issues: list[Issue]) -> Baseline:
        """Snapshot every enforceable finding that is not covered by an exception.

        INFO findings never fail a build and are left out. Findings covered by an
        exception (active *or* expired) are left out on purpose: deleting an expired
        exception must not silently turn the finding into baselined debt.
        """
        baseline = cls()
        for issue in issues:
            if is_governance_finding(issue) or issue.fingerprint is None:
                continue
            if issue.severity == Severity.INFO:
                continue
            if issue.status in (IssueStatus.EXCEPTED, IssueStatus.EXPIRED):
                continue
            existing = baseline.entries.get(issue.fingerprint)
            merged = set(issue.facets) | set(existing.facets if existing else ())
            baseline.entries[issue.fingerprint] = BaselineEntry(
                fingerprint=issue.fingerprint,
                rule_id=issue.rule_id,
                rule_name=issue.rule_name,
                severity=str(issue.severity),
                error_code=issue.error_code,
                facets=tuple(sorted(merged)),
            )
        return baseline

    def pruned(self, issues: list[Issue]) -> tuple[Baseline, list[str]]:
        """Ratchet: drop entries and facets that no longer occur. Never adds anything.

        Returns the pruned baseline and human-readable descriptions of what was removed.
        """
        current: dict[str, set[str]] = {}
        for issue in issues:
            if issue.fingerprint and not is_governance_finding(issue):
                current.setdefault(issue.fingerprint, set()).update(issue.facets)
        kept = Baseline(path=self.path)
        removed: list[str] = []
        for fp, entry in self.entries.items():
            if fp not in current:
                removed.append(fp)
                continue
            facets = tuple(f for f in entry.facets if f in current[fp])
            gone = [f for f in entry.facets if f not in current[fp]]
            removed.extend(f"{fp} [{f}]" for f in gone)
            kept.entries[fp] = BaselineEntry(
                fingerprint=entry.fingerprint,
                rule_id=entry.rule_id,
                rule_name=entry.rule_name,
                severity=entry.severity,
                error_code=entry.error_code,
                facets=facets,
            )
        return kept, removed

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BASELINE_SCHEMA_VERSION,
            "generator": {"name": "api-error-catalog", "version": __version__},
            "entries": [self.entries[fp].to_dict() for fp in sorted(self.entries)],
        }

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.dumps(), encoding="utf-8")


def load_baseline(path: Path) -> Baseline:
    if not path.is_file():
        raise BaselineError(
            f"baseline file not found: {path} "
            f"(create it with: api-error-catalog baseline create <specs> --output {path})"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise BaselineError(
            f"{path}: unsupported baseline format (expected schema_version "
            f"{BASELINE_SCHEMA_VERSION})"
        )
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise BaselineError(f"{path}: 'entries' must be a list")
    baseline = Baseline(path=path)
    for index, raw in enumerate(raw_entries):
        where = f"{path}: entries[{index}]"
        if not isinstance(raw, dict) or not isinstance(raw.get("fingerprint"), str):
            raise BaselineError(f"{where}: must be an object with a string 'fingerprint'")
        facets = raw.get("facets", [])
        if not isinstance(facets, list) or not all(isinstance(f, str) for f in facets):
            raise BaselineError(f"{where}: 'facets' must be a list of strings")
        fp = raw["fingerprint"]
        baseline.entries[fp] = BaselineEntry(
            fingerprint=fp,
            rule_id=str(raw.get("rule_id") or fp.split(":", 1)[0]),
            rule_name=str(raw.get("rule_name") or ""),
            severity=str(raw.get("severity") or ""),
            error_code=raw.get("error_code"),
            facets=tuple(facets),
        )
    return baseline
