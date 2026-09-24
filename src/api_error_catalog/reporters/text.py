"""Plain-text console report."""

from __future__ import annotations

from ..models import ExceptionState, GovernanceReport, Issue, IssueStatus, ScanResult

RULE_SEPARATOR = "-" * 50


def status_note(issue: Issue) -> str | None:
    """One-line governance note for an issue, or None when there is nothing to say."""
    exc = issue.exception
    if issue.status == IssueStatus.EXPIRED and exc:
        return (
            f"expired exception — exceptions[{exc.index}] owned by {exc.owner} "
            f"expired on {exc.expires_at.isoformat()}"
        )
    if issue.status == IssueStatus.EXCEPTED and exc:
        return f"excepted until {exc.expires_at.isoformat()} — owner {exc.owner}: {exc.reason}"
    if issue.status == IssueStatus.BASELINED:
        return "baselined (known debt)"
    if issue.new_facets:
        return "new — the baselined debt grew"
    return None


def short_status(issue: Issue) -> str:
    exc = issue.exception
    if issue.status in (IssueStatus.EXCEPTED, IssueStatus.EXPIRED) and exc:
        return f"{issue.status} until {exc.expires_at.isoformat()} · {exc.owner}"
    return str(issue.status)


def _format_issue(issue: Issue, governance: bool) -> list[str]:
    lines = [str(issue.severity), f"rule: {issue.rule_id} {issue.rule_name}"]
    if issue.error_code:
        lines.append(f"error_code: {issue.error_code}")
    note = status_note(issue) if governance else None
    if note:
        lines.append(f"status: {note}")
    for occ in issue.occurrences:
        lines.append(f"  {occ.service:<24} {occ.method} {occ.path} {occ.http_status}")
    for facet in issue.new_facets:
        lines.append(f"  + new since baseline: {facet}")
    lines.append(f"Problem: {issue.message}")
    return lines


def governance_lines(gov: GovernanceReport, result: ScanResult) -> list[str]:
    s = result.summary()
    states = {state: 0 for state in ExceptionState}
    for st in gov.exceptions:
        states[st.state] += 1
    lines = [f"Governance (as of {gov.today.isoformat()})"]
    if gov.baseline_path:
        lines.append(f"Baseline: {gov.baseline_path} ({gov.baseline_entries} entries)")
    else:
        lines.append("Baseline: none")
    lines.append(
        f"Exceptions: {len(gov.exceptions)} ("
        + ", ".join(f"{states[state]} {state}" for state in ExceptionState)
        + ")"
    )
    lines.append(
        f"Enforced: {s['enforced_conflicts']} conflicts, {s['enforced_warnings']} warnings"
    )
    lines.append(f"Accepted debt: {s['baselined']} baselined, {s['excepted']} excepted")
    if s["expired"]:
        lines.append(f"Expired exceptions: {s['expired']} finding(s) enforced again")
    return lines


def render_text(result: ScanResult) -> str:
    s = result.summary()
    gov = result.governance
    lines = [
        "API Error Catalog",
        "",
        f"Specifications: {s['specifications']}",
        f"Services: {s['services']}",
        f"Operations scanned: {s['operations_scanned']}",
        f"Error codes: {s['error_codes']}",
        f"Conflicts: {s['conflicts']}",
        f"Warnings: {s['warnings']}",
    ]
    if gov is not None:
        lines += ["", *governance_lines(gov, result)]

    shown = result.enforced if gov is not None else result.issues
    if shown:
        lines.append("")
        blocks = [_format_issue(issue, gov is not None) for issue in shown]
        for index, block in enumerate(blocks):
            lines.extend(block)
            if index < len(blocks) - 1:
                lines.append(RULE_SEPARATOR)
    elif gov is not None and result.issues:
        lines += ["", "No new conflicts or warnings — every finding is accepted debt."]
    else:
        lines += ["", "No conflicts or warnings found."]

    if gov is not None and result.accepted:
        lines += ["", "Accepted debt (not enforced)"]
        for issue in result.accepted:
            lines.append(f"  [{short_status(issue)}] {issue.fingerprint}")
    return "\n".join(lines) + "\n"
