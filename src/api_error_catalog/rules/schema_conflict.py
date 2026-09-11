"""ERROR002 — the same error code is returned with incompatible response schemas."""

from __future__ import annotations

from ..models import ErrorOccurrence, Issue, SchemaSignature, Severity
from ._common import group_by_code

RULE_ID = "ERROR002"
RULE_NAME = "SAME_CODE_INCOMPATIBLE_SCHEMA"


def describe(sig: SchemaSignature) -> str:
    if sig.is_empty():
        return "<no schema>"
    parts = []
    for name, type_ in sig.properties:
        marker = "*" if name in sig.required else ""
        parts.append(f"{name}{marker}: {type_}")
    return "{" + ", ".join(parts) + "}"


def run(occurrences: list[ErrorOccurrence]) -> list[Issue]:
    issues: list[Issue] = []
    for code, group in group_by_code(occurrences):
        # Responses without any schema carry no structural information; skip them.
        with_schema = [o for o in group if not o.signature.is_empty()]
        signatures = sorted({o.signature for o in with_schema}, key=describe)
        if len(signatures) <= 1:
            continue
        rendered = "; ".join(
            f"{describe(sig)} in "
            + ", ".join(sorted({o.service for o in with_schema if o.signature == sig}))
            for sig in signatures
        )
        issues.append(
            Issue(
                severity=Severity.CONFLICT,
                rule_id=RULE_ID,
                rule_name=RULE_NAME,
                error_code=code,
                message=f"Same error code is returned with {len(signatures)} different "
                f"response schemas: {rendered}.",
                occurrences=with_schema,
            )
        )
    return issues
