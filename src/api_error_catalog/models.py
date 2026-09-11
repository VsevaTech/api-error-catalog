"""Core data model shared by the extractor, rules and reporters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

UNCATEGORIZED = "UNCATEGORIZED"
"""Pseudo error code assigned to 4xx/5xx responses whose code could not be extracted."""


class Severity(StrEnum):
    CONFLICT = "CONFLICT"
    WARNING = "WARNING"
    INFO = "INFO"


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
class Issue:
    severity: Severity
    rule_id: str
    rule_name: str
    error_code: str | None
    message: str
    occurrences: list[ErrorOccurrence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": str(self.severity),
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "error_code": self.error_code,
            "message": self.message,
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


@dataclass(slots=True)
class ScanResult:
    specs: list[SpecInfo]
    occurrences: list[ErrorOccurrence]
    catalog: list[CatalogEntry]
    issues: list[Issue]
    load_warnings: list[LoadWarning] = field(default_factory=list)

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

    def summary(self) -> dict[str, int]:
        return {
            "specifications": len(self.specs),
            "services": len(self.services),
            "operations_scanned": self.operations_scanned,
            "error_codes": len(self.catalog),
            "conflicts": len(self.conflicts),
            "warnings": len(self.warnings),
            "info": len(self.infos),
        }
