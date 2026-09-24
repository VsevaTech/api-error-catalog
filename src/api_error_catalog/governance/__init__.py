"""API governance: baseline of known debt and owned, time-boxed exceptions.

Every analysis finding gets a status (see `IssueStatus`):

1. An **active exception** that matches the finding → ``excepted``.
2. Otherwise an **expired exception** that matches → ``expired`` (enforced again), and a
   ``GOV001 EXCEPTION_EXPIRED`` CONFLICT names the owner who missed the deadline.
3. Otherwise a **baseline entry** with the same fingerprint → ``baselined`` — unless the
   finding has facets the entry does not have (the debt grew), then ``new``.
4. Otherwise → ``new``.

Only enforced findings (``new``/``expired``) fail `--fail-on-conflict`.
"""

from __future__ import annotations

from datetime import date
from fnmatch import fnmatchcase
from pathlib import Path

from ..models import (
    ErrorOccurrence,
    ExceptionState,
    ExceptionStatus,
    GovernanceReport,
    Issue,
    IssueStatus,
    PolicyException,
    Severity,
)
from .baseline import (
    DEFAULT_BASELINE_FILENAME,
    Baseline,
    BaselineEntry,
    BaselineError,
    load_baseline,
)
from .fingerprint import annotate, facets, fingerprint, is_governance_finding

EXPIRED_RULE = ("GOV001", "EXCEPTION_EXPIRED")
UNUSED_RULE = ("GOV002", "UNUSED_EXCEPTION")
EXPIRING_RULE = ("GOV003", "EXCEPTION_EXPIRING_SOON")
RESOLVED_RULE = ("GOV004", "BASELINE_DEBT_RESOLVED")

GOVERNANCE_RULES: dict[str, str] = dict([EXPIRED_RULE, UNUSED_RULE, EXPIRING_RULE, RESOLVED_RULE])


def matches(exception: PolicyException, issue: Issue) -> bool:
    """Does `exception` cover `issue`?

    `service` / `endpoint` narrow the exception: *every* occurrence of the finding must be
    in that service / match that endpoint pattern (`fnmatch`, e.g. ``GET /v1/legacy/*``).
    A cross-service conflict can therefore only be excepted by error code, never by
    one of the participating services.
    """
    if issue.rule_id != exception.rule:
        return False
    if exception.error_code and issue.error_code != exception.error_code:
        return False
    if exception.service and (
        not issue.occurrences or any(o.service != exception.service for o in issue.occurrences)
    ):
        return False
    if exception.endpoint:
        pattern = _normalize_endpoint(exception.endpoint)
        if not issue.occurrences or not all(
            fnmatchcase(o.endpoint, pattern) for o in issue.occurrences
        ):
            return False
    return True


def _normalize_endpoint(endpoint: str) -> str:
    method, _, path = endpoint.strip().partition(" ")
    return f"{method.upper()} {path.strip()}" if path else method


def apply_governance(
    issues: list[Issue],
    *,
    exceptions: tuple[PolicyException, ...] | list[PolicyException] = (),
    baseline: Baseline | None = None,
    today: date,
    expiry_warning_days: int = 14,
) -> tuple[GovernanceReport, list[Issue]]:
    """Assign a governance status to every finding (in place).

    Returns the governance report and the additional ``GOV*`` findings to append.
    """
    annotate(issues)
    statuses = [ExceptionStatus(exception=e, state=ExceptionState.ACTIVE) for e in exceptions]

    for issue in issues:
        if is_governance_finding(issue) or issue.fingerprint is None:
            continue
        matching = [st for st in statuses if matches(st.exception, issue)]
        active = [st for st in matching if not st.exception.is_expired(today)]
        expired = [st for st in matching if st.exception.is_expired(today)]
        if active or expired:
            chosen = (active or expired)[0]
            issue.status = IssueStatus.EXCEPTED if active else IssueStatus.EXPIRED
            issue.exception = chosen.exception
            chosen.matched.append(issue.fingerprint)
            continue
        entry = baseline.entries.get(issue.fingerprint) if baseline is not None else None
        if entry is None:
            issue.status = IssueStatus.NEW
            continue
        grown = tuple(f for f in issue.facets if f not in entry.facets)
        issue.status = IssueStatus.NEW if grown else IssueStatus.BASELINED
        issue.new_facets = grown

    for st in statuses:
        exc = st.exception
        if not st.matched:
            st.state = ExceptionState.UNUSED
        elif exc.is_expired(today):
            st.state = ExceptionState.EXPIRED
        elif (exc.expires_at - today).days <= expiry_warning_days:
            st.state = ExceptionState.EXPIRING
        else:
            st.state = ExceptionState.ACTIVE

    resolved: list[str] = []
    if baseline is not None:
        _, resolved = baseline.pruned(issues)

    report = GovernanceReport(
        today=today,
        baseline_path=_display_path(baseline.path) if baseline is not None else None,
        baseline_entries=len(baseline) if baseline is not None else 0,
        resolved_baseline_entries=resolved,
        exceptions=statuses,
    )
    return report, _governance_findings(issues, statuses, resolved, today)


def _display_path(path: Path | None) -> str | None:
    """Relative to the working directory when possible — reports must not leak runner paths."""
    if path is None:
        return None
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _governance_findings(
    issues: list[Issue], statuses: list[ExceptionStatus], resolved: list[str], today: date
) -> list[Issue]:
    by_fp: dict[str, list[Issue]] = {}
    for issue in issues:
        if issue.fingerprint:
            by_fp.setdefault(issue.fingerprint, []).append(issue)

    findings: list[Issue] = []
    for st in statuses:
        exc = st.exception
        ref = f"exceptions[{exc.index}] {exc.label} (owner: {exc.owner}"
        ref += f", ticket: {exc.ticket})" if exc.ticket else ")"
        if st.state == ExceptionState.EXPIRED:
            occurrences: list[ErrorOccurrence] = []
            for fp in st.matched:
                for issue in by_fp.get(fp, []):
                    occurrences.extend(issue.occurrences)
            days = (today - exc.expires_at).days
            findings.append(
                _gov(
                    EXPIRED_RULE,
                    Severity.CONFLICT,
                    exc.error_code,
                    f"Exception {ref} expired on {exc.expires_at.isoformat()} "
                    f"({days} day{'s' if days != 1 else ''} ago) and no longer covers "
                    f"{', '.join(st.matched)}. Fix the finding or renew the exception with a new "
                    f"expires_at. Reason given: {exc.reason}",
                    occurrences,
                )
            )
        elif st.state == ExceptionState.UNUSED:
            tail = (
                " It has also expired." if exc.is_expired(today) else ""
            ) + " Remove it from the configuration."
            findings.append(
                _gov(
                    UNUSED_RULE,
                    Severity.WARNING,
                    exc.error_code,
                    f"Exception {ref} does not match any current finding — the problem was "
                    f"fixed or the matcher is wrong.{tail}",
                )
            )
        elif st.state == ExceptionState.EXPIRING:
            days = (exc.expires_at - today).days
            findings.append(
                _gov(
                    EXPIRING_RULE,
                    Severity.INFO,
                    exc.error_code,
                    f"Exception {ref} expires on {exc.expires_at.isoformat()} "
                    f"(in {days} day{'s' if days != 1 else ''}); after that "
                    f"{', '.join(st.matched)} will fail the build again.",
                )
            )
    if resolved:
        findings.append(
            _gov(
                RESOLVED_RULE,
                Severity.INFO,
                None,
                f"{len(resolved)} baseline item(s) no longer occur: {', '.join(resolved)}. "
                "Lock in the progress with `api-error-catalog baseline update`.",
            )
        )
    return findings


def _gov(
    rule: tuple[str, str],
    severity: Severity,
    error_code: str | None,
    message: str,
    occurrences: list[ErrorOccurrence] | None = None,
) -> Issue:
    return Issue(
        severity=severity,
        rule_id=rule[0],
        rule_name=rule[1],
        error_code=error_code,
        message=message,
        occurrences=occurrences or [],
    )


__all__ = [
    "DEFAULT_BASELINE_FILENAME",
    "GOVERNANCE_RULES",
    "Baseline",
    "BaselineEntry",
    "BaselineError",
    "annotate",
    "apply_governance",
    "facets",
    "fingerprint",
    "load_baseline",
    "matches",
]
