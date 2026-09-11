"""Shared helpers for rules."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import groupby

from ..models import ErrorOccurrence


def group_by_code(
    occurrences: Iterable[ErrorOccurrence],
) -> list[tuple[str, list[ErrorOccurrence]]]:
    """Group categorized occurrences by error code, sorted by code."""
    categorized = sorted(
        (o for o in occurrences if not o.is_uncategorized),
        key=lambda o: (o.error_code, o.service, o.path, o.method, o.http_status),
    )
    return [(code, list(group)) for code, group in groupby(categorized, key=lambda o: o.error_code)]
