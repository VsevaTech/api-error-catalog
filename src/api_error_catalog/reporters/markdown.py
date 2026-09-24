"""Markdown report suitable for GitHub PR comments and `$GITHUB_STEP_SUMMARY`."""

from __future__ import annotations

from ..models import ExceptionState, Issue, IssueStatus, ScanResult
from .text import status_note

SEVERITY_ICON = {"CONFLICT": "❌", "WARNING": "⚠️", "INFO": "ℹ️"}
EXCEPTION_ICON = {
    ExceptionState.ACTIVE: "🟢",
    ExceptionState.EXPIRING: "🟡",
    ExceptionState.EXPIRED: "🔴",
    ExceptionState.UNUSED: "⚪",
}


def _code(text: str | None) -> str:
    return f"`{text}`" if text else ""


def _escape(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _issue_block(issue: Issue, governance: bool = False) -> list[str]:
    icon = SEVERITY_ICON.get(str(issue.severity), "")
    title = f"{icon} **{issue.severity}** · {issue.rule_id} `{issue.rule_name}`"
    if issue.error_code:
        title += f" · {_code(issue.error_code)}"
    lines = [f"#### {title}", ""]
    note = status_note(issue) if governance else None
    if note:
        lines += [f"> **Status:** {_escape(note)}", ""]
    lines += [issue.message, ""]
    if issue.new_facets:
        lines += ["New since baseline:", ""]
        lines += [f"- `{facet}`" for facet in issue.new_facets]
        lines.append("")
    if issue.occurrences:
        lines += ["| Service | Endpoint | Status | Source |", "|---|---|---|---|"]
        for occ in issue.occurrences:
            lines.append(
                f"| {_escape(occ.service)} | `{occ.endpoint}` | {occ.http_status} | "
                f"`{occ.source_file}` |"
            )
        lines.append("")
    return lines


def render_markdown(result: ScanResult) -> str:
    s = result.summary()
    lines = [
        "# API Error Catalog",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Specifications | {s['specifications']} |",
        f"| Services | {s['services']} |",
        f"| Operations scanned | {s['operations_scanned']} |",
        f"| Unique error codes | {s['error_codes']} |",
        f"| Conflicts | {s['conflicts']} |",
        f"| Warnings | {s['warnings']} |",
    ]
    if result.governance is not None:
        lines += [
            f"| Enforced conflicts | {s['enforced_conflicts']} |",
            f"| Enforced warnings | {s['enforced_warnings']} |",
            f"| Baselined | {s['baselined']} |",
            f"| Excepted | {s['excepted']} |",
            f"| Expired exceptions | {s['expired']} |",
        ]
    lines += [
        "",
        "## Specifications",
        "",
        "| Service | File | Version | OpenAPI | Operations |",
        "|---|---|---|---|---:|",
    ]
    for spec in result.specs:
        lines.append(
            f"| {_escape(spec.service)} | `{spec.source_file}` | {spec.version or '-'} | "
            f"{spec.openapi_version or '-'} | {spec.operations} |"
        )

    lines += ["", "## Error Catalog", ""]
    if not result.catalog:
        lines.append("_No error codes were extracted._")
    lines += [
        "| Error code | HTTP status | Services | Used by | Description |",
        "|---|---|---|---|---|",
    ]
    for entry in result.catalog:
        used_by = "<br>".join(sorted({f"`{o.endpoint}`" for o in entry.occurrences}))
        descriptions = "<br>".join(_escape(d) for d in entry.descriptions) or "-"
        lines.append(
            f"| `{entry.error_code}` | {', '.join(entry.http_statuses)} | "
            f"{', '.join(_escape(x) for x in entry.services)} | {used_by} | {descriptions} |"
        )

    if result.governance is not None:
        lines += _governance_section(result)

    governed = result.governance is not None
    shown = result.enforced if governed else result.issues
    lines += ["", "## Conflicts & Warnings", ""]
    if not result.issues:
        lines.append("✅ No conflicts or warnings found.")
    elif not shown:
        lines.append("✅ No new conflicts or warnings — every finding is accepted debt.")
    else:
        for title, severity in (
            ("Conflicts", "CONFLICT"),
            ("Warnings", "WARNING"),
            ("Info", "INFO"),
        ):
            group = [i for i in shown if i.severity == severity]
            if group:
                lines += [f"### {title} ({len(group)})", ""]
                for issue in group:
                    lines += _issue_block(issue, governed)
    if governed and result.accepted:
        lines += [
            "",
            "<details>",
            f"<summary>Accepted debt ({len(result.accepted)}) — baselined or excepted, "
            "not enforced</summary>",
            "",
            "| Status | Severity | Finding | Owner | Expires | Reason |",
            "|---|---|---|---|---|---|",
        ]
        for issue in result.accepted:
            exc = issue.exception
            lines.append(
                f"| {issue.status} | {issue.severity} | `{_escape(issue.fingerprint)}` | "
                f"{_escape(exc.owner) if exc else '-'} | "
                f"{exc.expires_at.isoformat() if exc else '-'} | "
                f"{_escape(exc.reason) if exc else '-'} |"
            )
        lines += ["", "</details>"]
    return "\n".join(lines).rstrip() + "\n"


def _governance_section(result: ScanResult) -> list[str]:
    gov = result.governance
    assert gov is not None
    lines = ["", "## Governance", "", f"Evaluated as of **{gov.today.isoformat()}**.", ""]
    if gov.baseline_path:
        lines.append(f"- Baseline: `{gov.baseline_path}` — {gov.baseline_entries} entries.")
    else:
        lines.append("- Baseline: none.")
    if gov.resolved_baseline_entries:
        lines.append(
            f"- 🎉 {len(gov.resolved_baseline_entries)} baseline item(s) fixed — run "
            "`api-error-catalog baseline update` to lock in the progress."
        )
    expired = sum(1 for i in result.issues if i.status == IssueStatus.EXPIRED)
    if expired:
        lines.append(f"- 🔴 {expired} finding(s) are enforced again: their exception expired.")
    if not gov.exceptions:
        lines.append("- Exceptions: none.")
        return lines
    lines += [
        "",
        f"### Exceptions ({len(gov.exceptions)})",
        "",
        "| State | Rule | Error code | Scope | Owner | Expires | Reason | Ticket |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for st in gov.exceptions:
        exc = st.exception
        scope = "; ".join(
            part
            for part in (
                f"service: {exc.service}" if exc.service else "",
                f"endpoint: `{exc.endpoint}`" if exc.endpoint else "",
            )
            if part
        )
        lines.append(
            f"| {EXCEPTION_ICON[st.state]} {st.state} | {exc.rule} | {_code(exc.error_code)} | "
            f"{_escape(scope) or '-'} | {_escape(exc.owner)} | {exc.expires_at.isoformat()} | "
            f"{_escape(exc.reason)} | {_escape(exc.ticket) or '-'} |"
        )
    return lines
