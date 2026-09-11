"""ERROR003 — the same error code is documented with materially different descriptions."""

from __future__ import annotations

import re

from ..models import ErrorOccurrence, Issue, Severity
from ._common import group_by_code

RULE_ID = "ERROR003"
RULE_NAME = "DESCRIPTION_MISMATCH"

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def normalize(text: str) -> str:
    text = _PUNCT.sub("", text.lower())
    return _WS.sub(" ", text).strip()


def run(occurrences: list[ErrorOccurrence]) -> list[Issue]:
    issues: list[Issue] = []
    for code, group in group_by_code(occurrences):
        described = [o for o in group if o.description]
        normalized: dict[str, str] = {}
        for occ in described:
            normalized.setdefault(normalize(occ.description or ""), occ.description or "")
        if len(normalized) <= 1:
            continue
        variants = "; ".join(f'"{d}"' for d in normalized.values())
        issues.append(
            Issue(
                severity=Severity.WARNING,
                rule_id=RULE_ID,
                rule_name=RULE_NAME,
                error_code=code,
                message=f"Error code is described differently across operations: {variants}.",
                occurrences=described,
            )
        )
    return issues
