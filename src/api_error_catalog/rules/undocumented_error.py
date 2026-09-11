"""ERROR004 — a 4xx/5xx response exists but no error code could be extracted from it."""

from __future__ import annotations

from ..models import ErrorOccurrence, Issue, Severity

RULE_ID = "ERROR004"
RULE_NAME = "UNDOCUMENTED_ERROR_CODE"


def run(occurrences: list[ErrorOccurrence]) -> list[Issue]:
    issues: list[Issue] = []
    for occ in sorted(
        (o for o in occurrences if o.is_uncategorized),
        key=lambda o: (o.service, o.path, o.method, o.http_status),
    ):
        if occ.schema_ref or not occ.signature.is_empty():
            detail = "the response schema has no error-code field with enum/const/example"
        else:
            detail = "the response has no JSON schema or example"
        issues.append(
            Issue(
                severity=Severity.WARNING,
                rule_id=RULE_ID,
                rule_name=RULE_NAME,
                error_code=None,
                message=(
                    f"{occ.endpoint} {occ.http_status} ({occ.service}): error response exists "
                    f"but no documented error code could be extracted ({detail})."
                ),
                occurrences=[occ],
            )
        )
    return issues
