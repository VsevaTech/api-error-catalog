"""ERROR001 — the same error code is returned with different HTTP statuses."""

from __future__ import annotations

from ..models import ErrorOccurrence, Issue, Severity
from ._common import group_by_code

RULE_ID = "ERROR001"
RULE_NAME = "SAME_CODE_DIFFERENT_HTTP_STATUS"


def run(occurrences: list[ErrorOccurrence]) -> list[Issue]:
    issues: list[Issue] = []
    for code, group in group_by_code(occurrences):
        statuses = sorted({o.http_status for o in group})
        if len(statuses) <= 1:
            continue
        by_status = ", ".join(
            f"{status} ({', '.join(sorted({o.service for o in group if o.http_status == status}))})"
            for status in statuses
        )
        issues.append(
            Issue(
                severity=Severity.CONFLICT,
                rule_id=RULE_ID,
                rule_name=RULE_NAME,
                error_code=code,
                message=(
                    f"Same error code is associated with different HTTP statuses: {by_status}."
                ),
                occurrences=list(group),
            )
        )
    return issues
