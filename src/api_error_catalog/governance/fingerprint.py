"""Stable identity of a finding across scans.

A *fingerprint* says **which** problem a finding is — it does not depend on message wording,
issue ordering, or which endpoints happen to participate:

* ``ERROR001:user_not_found`` — one conflict per error code;
* ``ERROR005:customer_blocked@Customer API`` — per error code and service;
* ``ERROR004:Auth API:POST /v1/auth/token/refresh 401`` — per error response;
* ``REF001:<file>: <message>`` — per unresolved reference.

*Facets* say **how bad** it is: the dimensions along which the problem can grow. A baselined
finding whose facets are a subset of the baseline entry is known debt; a new facet (a third
HTTP status for the same code, another schema variant, one more diverging description) is
new debt and is enforced again. Adding another endpoint that repeats an already-baselined
facet does not change the facets, so it is not reported as new debt.
"""

from __future__ import annotations

from collections.abc import Callable

from ..models import ErrorOccurrence, Issue
from ..rules.description_mismatch import normalize
from ..rules.schema_conflict import describe

GOVERNANCE_RULE_PREFIX = "GOV"


def _status_facet(o: ErrorOccurrence) -> str:
    return f"{o.service} -> {o.http_status}"


def _schema_facet(o: ErrorOccurrence) -> str:
    return f"{o.service} -> {describe(o.signature)}"


def _description_facet(o: ErrorOccurrence) -> str:
    return f'{o.service} -> "{normalize(o.description or "")}"'


def _definition_facet(o: ErrorOccurrence) -> str:
    where = o.schema_ref or f"inline@{o.endpoint} {o.http_status}"
    return f"{where} -> {describe(o.signature)}"


_FACETS: dict[str, Callable[[ErrorOccurrence], str]] = {
    "ERROR001": _status_facet,
    "ERROR002": _schema_facet,
    "ERROR003": _description_facet,
    "ERROR005": _definition_facet,
}


def is_governance_finding(issue: Issue) -> bool:
    return issue.rule_id.startswith(GOVERNANCE_RULE_PREFIX)


def fingerprint(issue: Issue) -> str:
    rule = issue.rule_id
    occs = issue.occurrences
    if rule == "ERROR004" and occs:
        o = occs[0]
        return f"{rule}:{o.service}:{o.endpoint} {o.http_status}"
    if rule == "ERROR005" and occs:
        return f"{rule}:{issue.error_code}@{occs[0].service}"
    if issue.error_code:
        return f"{rule}:{issue.error_code}"
    return f"{rule}:{issue.message}"


def facets(issue: Issue) -> tuple[str, ...]:
    facet = _FACETS.get(issue.rule_id)
    if facet is None:
        return ()
    return tuple(sorted({facet(o) for o in issue.occurrences}))


def annotate(issues: list[Issue]) -> None:
    """Fill in `fingerprint` and `facets` for every analysis finding."""
    for issue in issues:
        if is_governance_finding(issue):
            continue
        issue.fingerprint = fingerprint(issue)
        issue.facets = facets(issue)
