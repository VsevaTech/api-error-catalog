"""Markdown report suitable for GitHub PR comments and `$GITHUB_STEP_SUMMARY`."""

from __future__ import annotations

from ..models import Issue, ScanResult

SEVERITY_ICON = {"CONFLICT": "❌", "WARNING": "⚠️", "INFO": "ℹ️"}


def _code(text: str | None) -> str:
    return f"`{text}`" if text else ""


def _escape(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _issue_block(issue: Issue) -> list[str]:
    icon = SEVERITY_ICON.get(str(issue.severity), "")
    title = f"{icon} **{issue.severity}** · {issue.rule_id} `{issue.rule_name}`"
    if issue.error_code:
        title += f" · {_code(issue.error_code)}"
    lines = [f"#### {title}", "", issue.message, ""]
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

    lines += ["", "## Conflicts & Warnings", ""]
    if not result.issues:
        lines.append("✅ No conflicts or warnings found.")
    else:
        if result.conflicts:
            lines += [f"### Conflicts ({len(result.conflicts)})", ""]
            for issue in result.conflicts:
                lines += _issue_block(issue)
        if result.warnings:
            lines += [f"### Warnings ({len(result.warnings)})", ""]
            for issue in result.warnings:
                lines += _issue_block(issue)
        if result.infos:
            lines += [f"### Info ({len(result.infos)})", ""]
            for issue in result.infos:
                lines += _issue_block(issue)
    return "\n".join(lines).rstrip() + "\n"
