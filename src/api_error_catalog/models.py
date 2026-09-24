"""Core data model shared by the extractor, rules and reporters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

UNCATEGORIZED = "UNCATEGORIZED"
"""Pseudo error code assigned to 4xx/5xx responses whose code could not be extracted."""


class Severity(StrEnum):
    CONFLICT = "CONFLICT"
    WARNING = "WARNING"
    INFO = "INFO"


class IssueStatus(StrEnum):
    """Governance status of a finding.

    * ``new`` — not covered by the baseline or an exception; enforced.
    * ``baselined`` — known technical debt recorded in the baseline file; not enforced.
    * ``excepted`` — covered by an active, owned, time-boxed exception; not enforced.
    * ``expired`` — covered only by an exception whose ``expires_at`` has passed; enforced.
    """

    NEW = "new"
    BASELINED = "baselined"
    EXCEPTED = "excepted"
    EXPIRED = "expired"

    @property
    def is_enforced(self) -> bool:
        return self in (IssueStatus.NEW, IssueStatus.EXPIRED)


class Location(StrEnum):
    """Where in the response definition an error code was found."""

    EXAMPLE = "example"
    EXAMPLES = "examples"
    SCHEMA_ENUM = "schema.enum"
    SCHEMA_CONST = "schema.const"
    SCHEMA_DEFAULT = "schema.default"
    SCHEMA_EXAMPLE = "schema.example"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class SchemaSignature:
    """Stable, comparable summary of an error response schema.

    Intentionally shallow: property names, their types, and required flags.
    """

    properties: tuple[tuple[str, str], ...] = ()
    required: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not self.properties and not self.required

    def to_dict(self) -> dict[str, Any]:
        return {
            "properties": {name: type_ for name, type_ in self.properties},
            "required": list(self.required),
        }


@dataclass(slots=True)
class ErrorOccurrence:
    service: str
    source_file: str
    error_code: str
    http_status: str
    method: str
    path: str
    operation_id: str | None
    description: str | None
    schema_ref: str | None
    location: Location
    field_name: str | None = None
    signature: SchemaSignature = field(default_factory=SchemaSignature)

    @property
    def endpoint(self) -> str:
        return f"{self.method.upper()} {self.path}"

    @property
    def is_uncategorized(self) -> bool:
        return self.error_code == UNCATEGORIZED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["location"] = str(self.location)
        data["signature"] = self.signature.to_dict()
        return data


@dataclass(slots=True)
class PolicyException:
    """An owned, time-boxed acceptance of a finding, declared in `.api-error-catalog.yaml`."""

    rule: str
    owner: str
    reason: str
    expires_at: date
    error_code: str | None = None
    service: str | None = None
    endpoint: str | None = None
    ticket: str | None = None
    index: int = 0
    """Position in the `exceptions` list, used in messages (`exceptions[3]`)."""

    @property
    def label(self) -> str:
        target = [self.rule]
        if self.error_code:
            target.append(f"`{self.error_code}`")
        if self.service:
            target.append(f"service={self.service}")
        if self.endpoint:
            target.append(f"endpoint={self.endpoint}")
        return " ".join(target)

    def is_expired(self, today: date) -> bool:
        """`expires_at` is inclusive: the exception is valid through that whole day."""
        return today > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "rule": self.rule,
            "error_code": self.error_code,
            "service": self.service,
            "endpoint": self.endpoint,
            "owner": self.owner,
            "reason": self.reason,
            "ticket": self.ticket,
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass(slots=True)
class Issue:
    severity: Severity
    rule_id: str
    rule_name: str
    error_code: str | None
    message: str
    occurrences: list[ErrorOccurrence] = field(default_factory=list)
    fingerprint: str | None = None
    """Stable identity of the finding across scans (see `governance.fingerprint`)."""
    facets: tuple[str, ...] = ()
    """What makes this finding worse when it grows (statuses, schema variants, …)."""
    status: IssueStatus = IssueStatus.NEW
    exception: PolicyException | None = None
    new_facets: tuple[str, ...] = ()
    """Facets absent from the baseline entry: the debt grew since the baseline was taken."""

    @property
    def is_enforced(self) -> bool:
        return self.status.is_enforced

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": str(self.severity),
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "error_code": self.error_code,
            "message": self.message,
            "fingerprint": self.fingerprint,
            "status": str(self.status),
            "exception": self.exception.to_dict() if self.exception else None,
            "new_facets": list(self.new_facets),
            "occurrences": [o.to_dict() for o in self.occurrences],
        }


@dataclass(slots=True)
class SpecInfo:
    service: str
    source_file: str
    title: str
    version: str | None
    openapi_version: str | None
    operations: int


@dataclass(slots=True)
class LoadWarning:
    """Non-fatal problem discovered while loading or resolving a spec."""

    source_file: str
    message: str


@dataclass(slots=True)
class CatalogEntry:
    """Aggregated view of one error code across all scanned specifications."""

    error_code: str
    http_statuses: list[str]
    services: list[str]
    occurrences: list[ErrorOccurrence]

    @property
    def descriptions(self) -> list[str]:
        seen: list[str] = []
        for occ in self.occurrences:
            if occ.description and occ.description not in seen:
                seen.append(occ.description)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "http_statuses": self.http_statuses,
            "services": self.services,
            "descriptions": self.descriptions,
            "occurrences": [o.to_dict() for o in self.occurrences],
        }


class ExceptionState(StrEnum):
    ACTIVE = "active"
    EXPIRING = "expiring"
    """Active, but expires within `exception_expiry_warning_days`."""
    EXPIRED = "expired"
    UNUSED = "unused"
    """Matches no current finding (fixed, or the matcher is wrong)."""


@dataclass(slots=True)
class ExceptionStatus:
    exception: PolicyException
    state: ExceptionState
    matched: list[str] = field(default_factory=list)
    """Fingerprints of the findings this exception decided the status of."""

    def to_dict(self) -> dict[str, Any]:
        return {**self.exception.to_dict(), "state": str(self.state), "matched": self.matched}


@dataclass(slots=True)
class GovernanceReport:
    today: date
    baseline_path: str | None = None
    baseline_entries: int = 0
    resolved_baseline_entries: list[str] = field(default_factory=list)
    """Baseline fingerprints (or facets of them) that no longer occur — ready to be pruned."""
    exceptions: list[ExceptionStatus] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "today": self.today.isoformat(),
            "baseline": {
                "path": self.baseline_path,
                "entries": self.baseline_entries,
                "resolved": self.resolved_baseline_entries,
            },
            "exceptions": [e.to_dict() for e in self.exceptions],
        }


@dataclass(slots=True)
class ScanResult:
    specs: list[SpecInfo]
    occurrences: list[ErrorOccurrence]
    catalog: list[CatalogEntry]
    issues: list[Issue]
    load_warnings: list[LoadWarning] = field(default_factory=list)
    governance: GovernanceReport | None = None

    @property
    def operations_scanned(self) -> int:
        return sum(s.operations for s in self.specs)

    @property
    def services(self) -> list[str]:
        return sorted({s.service for s in self.specs})

    @property
    def conflicts(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == Severity.CONFLICT]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def infos(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == Severity.INFO]

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    @property
    def enforced(self) -> list[Issue]:
        """Findings that are neither baselined nor covered by an active exception."""
        return [i for i in self.issues if i.is_enforced]

    @property
    def accepted(self) -> list[Issue]:
        """Known debt: baselined or covered by an active exception."""
        return [i for i in self.issues if not i.is_enforced]

    @property
    def blocking(self) -> list[Issue]:
        """Enforced CONFLICTs — what `--fail-on-conflict` fails on."""
        return [i for i in self.enforced if i.severity == Severity.CONFLICT]

    def summary(self) -> dict[str, int]:
        data = {
            "specifications": len(self.specs),
            "services": len(self.services),
            "operations_scanned": self.operations_scanned,
            "error_codes": len(self.catalog),
            "conflicts": len(self.conflicts),
            "warnings": len(self.warnings),
            "info": len(self.infos),
        }
        if self.governance is not None:
            by_status = {status: 0 for status in IssueStatus}
            for issue in self.issues:
                if issue.severity != Severity.INFO:
                    by_status[issue.status] += 1
            data |= {
                "enforced_conflicts": len(self.blocking),
                "enforced_warnings": sum(
                    1 for i in self.enforced if i.severity == Severity.WARNING
                ),
                "baselined": by_status[IssueStatus.BASELINED],
                "excepted": by_status[IssueStatus.EXCEPTED],
                "expired": by_status[IssueStatus.EXPIRED],
            }
        return data
