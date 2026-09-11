"""ERROR005 — one service defines the same error code in several, diverging places.

Within a single specification an error code is expected to come from one shared schema
(e.g. `#/components/schemas/ErrorResponse`). When the same code is declared by several
different schema definitions we report it:

* CONFLICT when those definitions have different structures;
* WARNING when the structures match today but are duplicated (drift risk).
"""

from __future__ import annotations

from collections import defaultdict

from ..models import ErrorOccurrence, Issue, Severity
from ._common import group_by_code
from .schema_conflict import describe

RULE_ID = "ERROR005"
RULE_NAME = "DUPLICATE_OR_INCONSISTENT_DEFINITION"


def _definition_key(occ: ErrorOccurrence) -> str:
    if occ.schema_ref:
        return occ.schema_ref
    return f"inline@{occ.method} {occ.path} {occ.http_status}"


def run(occurrences: list[ErrorOccurrence]) -> list[Issue]:
    issues: list[Issue] = []
    for code, group in group_by_code(occurrences):
        per_service: dict[str, list[ErrorOccurrence]] = defaultdict(list)
        for occ in group:
            per_service[occ.service].append(occ)
        for service in sorted(per_service):
            occs = [o for o in per_service[service] if not o.signature.is_empty()]
            definitions = sorted({_definition_key(o) for o in occs})
            if len(definitions) <= 1:
                continue
            signatures = {o.signature for o in occs}
            if len(signatures) > 1:
                severity = Severity.CONFLICT
                detail = "with different structures: " + "; ".join(
                    sorted(describe(sig) for sig in signatures)
                )
            else:
                severity = Severity.WARNING
                detail = "with identical structure (duplicated definition)"
            issues.append(
                Issue(
                    severity=severity,
                    rule_id=RULE_ID,
                    rule_name=RULE_NAME,
                    error_code=code,
                    message=(
                        f"{service} defines '{code}' in {len(definitions)} separate schema "
                        f"definitions ({', '.join(definitions)}) {detail}."
                    ),
                    occurrences=occs,
                )
            )
    return issues
