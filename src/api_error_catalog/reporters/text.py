"""Plain-text console report."""

from __future__ import annotations

from ..models import Issue, ScanResult

RULE_SEPARATOR = "-" * 50


def _format_issue(issue: Issue) -> list[str]:
    lines = [str(issue.severity), f"rule: {issue.rule_id} {issue.rule_name}"]
    if issue.error_code:
        lines.append(f"error_code: {issue.error_code}")
    for occ in issue.occurrences:
        lines.append(f"  {occ.service:<24} {occ.method} {occ.path} {occ.http_status}")
    lines.append(f"Problem: {issue.message}")
    return lines


def render_text(result: ScanResult) -> str:
    s = result.summary()
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
    if result.issues:
        lines.append("")
        blocks = [_format_issue(issue) for issue in result.issues]
        for index, block in enumerate(blocks):
            lines.extend(block)
            if index < len(blocks) - 1:
                lines.append(RULE_SEPARATOR)
    else:
        lines += ["", "No conflicts or warnings found."]
    return "\n".join(lines) + "\n"
