"""Consistency rules. Each rule is a callable `(occurrences) -> list[Issue]`."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ..models import ErrorOccurrence, Issue
from . import (
    description_mismatch,
    inconsistent_definition,
    schema_conflict,
    status_conflict,
    undocumented_error,
)
from ._common import group_by_code

Rule = Callable[[list[ErrorOccurrence]], list[Issue]]

ALL_RULES: tuple[Rule, ...] = (
    status_conflict.run,
    schema_conflict.run,
    description_mismatch.run,
    undocumented_error.run,
    inconsistent_definition.run,
)

RULE_CATALOG: dict[str, str] = {
    status_conflict.RULE_ID: status_conflict.RULE_NAME,
    schema_conflict.RULE_ID: schema_conflict.RULE_NAME,
    description_mismatch.RULE_ID: description_mismatch.RULE_NAME,
    undocumented_error.RULE_ID: undocumented_error.RULE_NAME,
    inconsistent_definition.RULE_ID: inconsistent_definition.RULE_NAME,
}


def run_all(occurrences: list[ErrorOccurrence], rules: Iterable[Rule] = ALL_RULES) -> list[Issue]:
    issues: list[Issue] = []
    for rule in rules:
        issues.extend(rule(occurrences))
    return issues


__all__ = ["ALL_RULES", "RULE_CATALOG", "Rule", "group_by_code", "run_all"]
