"""Configuration file handling (`.api-error-catalog.yaml`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .models import PolicyException

DEFAULT_CONFIG_FILENAME = ".api-error-catalog.yaml"
DEFAULT_ERROR_CODE_FIELDS = ("error_code", "errorCode", "code")
DEFAULT_EXPIRY_WARNING_DAYS = 14

_KNOWN_KEYS = {
    "error_code_fields",
    "include_patterns",
    "ignore_error_codes",
    "baseline",
    "exceptions",
    "exception_expiry_warning_days",
}
_EXCEPTION_REQUIRED = ("rule", "owner", "reason", "expires_at")
_EXCEPTION_OPTIONAL = ("error_code", "service", "endpoint", "ticket")
_EXCEPTION_MATCHERS = ("error_code", "service", "endpoint")


class ConfigError(Exception):
    """Raised when the configuration file is missing or malformed."""


@dataclass(slots=True)
class Config:
    error_code_fields: tuple[str, ...] = DEFAULT_ERROR_CODE_FIELDS
    include_patterns: tuple[str, ...] = ("*.yaml", "*.yml", "*.json")
    ignore_error_codes: frozenset[str] = field(default_factory=frozenset)
    baseline: Path | None = None
    """Baseline file, resolved relative to the configuration file."""
    exceptions: tuple[PolicyException, ...] = ()
    exception_expiry_warning_days: int = DEFAULT_EXPIRY_WARNING_DAYS

    @classmethod
    def from_dict(
        cls, data: dict, source: str = "<config>", base_dir: Path | None = None
    ) -> Config:
        if not isinstance(data, dict):
            raise ConfigError(f"{source}: configuration root must be a mapping")
        cfg = cls()
        fields = data.get("error_code_fields")
        if fields is not None:
            if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
                raise ConfigError(f"{source}: 'error_code_fields' must be a list of strings")
            if not fields:
                raise ConfigError(f"{source}: 'error_code_fields' must not be empty")
            cfg.error_code_fields = tuple(fields)
        patterns = data.get("include_patterns")
        if patterns is not None:
            if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
                raise ConfigError(f"{source}: 'include_patterns' must be a list of strings")
            cfg.include_patterns = tuple(patterns)
        ignored = data.get("ignore_error_codes")
        if ignored is not None:
            if not isinstance(ignored, list) or not all(isinstance(c, str) for c in ignored):
                raise ConfigError(f"{source}: 'ignore_error_codes' must be a list of strings")
            cfg.ignore_error_codes = frozenset(ignored)
        baseline = data.get("baseline")
        if baseline is not None:
            if not isinstance(baseline, str) or not baseline.strip():
                raise ConfigError(f"{source}: 'baseline' must be a non-empty path string")
            path = Path(baseline)
            cfg.baseline = path if path.is_absolute() or base_dir is None else base_dir / path
        days = data.get("exception_expiry_warning_days")
        if days is not None:
            if isinstance(days, bool) or not isinstance(days, int) or days < 0:
                raise ConfigError(
                    f"{source}: 'exception_expiry_warning_days' must be a non-negative integer"
                )
            cfg.exception_expiry_warning_days = days
        exceptions = data.get("exceptions")
        if exceptions is not None:
            if not isinstance(exceptions, list):
                raise ConfigError(f"{source}: 'exceptions' must be a list")
            cfg.exceptions = tuple(
                _parse_exception(item, index, source) for index, item in enumerate(exceptions)
            )
        unknown = set(data) - _KNOWN_KEYS
        if unknown:
            raise ConfigError(f"{source}: unknown configuration keys: {sorted(unknown)}")
        return cfg


def _parse_exception(item: Any, index: int, source: str) -> PolicyException:
    from .rules import RULE_CATALOG  # local import keeps config importable on its own

    where = f"{source}: exceptions[{index}]"
    if not isinstance(item, dict):
        raise ConfigError(f"{where}: must be a mapping")
    unknown = set(item) - set(_EXCEPTION_REQUIRED) - set(_EXCEPTION_OPTIONAL)
    if unknown:
        raise ConfigError(f"{where}: unknown keys: {sorted(unknown)}")
    missing = [key for key in _EXCEPTION_REQUIRED if item.get(key) in (None, "")]
    if missing:
        raise ConfigError(f"{where}: missing required keys: {missing}")

    strings: dict[str, str | None] = {}
    for key in ("rule", "owner", "reason", *_EXCEPTION_OPTIONAL):
        value = item.get(key)
        if value is None:
            strings[key] = None
            continue
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{where}: '{key}' must be a non-empty string")
        strings[key] = value.strip()

    # Exceptions cover consistency findings; loader findings (REF001, SPEC001) are baselined.
    exceptable = {rid: name for rid, name in RULE_CATALOG.items() if rid.startswith("ERROR")}
    rule = strings["rule"] or ""
    by_name = {name: rule_id for rule_id, name in exceptable.items()}
    rule = by_name.get(rule, rule)
    if rule not in exceptable:
        raise ConfigError(
            f"{where}: rule '{strings['rule']}' cannot be excepted "
            f"(allowed: {', '.join(exceptable)})"
        )
    if not any(strings[key] for key in _EXCEPTION_MATCHERS):
        raise ConfigError(
            f"{where}: blanket exceptions are not allowed — narrow it with at least one of "
            f"{list(_EXCEPTION_MATCHERS)}"
        )

    return PolicyException(
        rule=rule,
        owner=strings["owner"] or "",
        reason=strings["reason"] or "",
        expires_at=_parse_date(item["expires_at"], where),
        error_code=strings["error_code"],
        service=strings["service"],
        endpoint=strings["endpoint"],
        ticket=strings["ticket"],
        index=index,
    )


def _parse_date(value: Any, where: str) -> date:
    # YAML parses an unquoted 2026-12-31 into a `date` already.
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ConfigError(f"{where}: 'expires_at' must be a date in YYYY-MM-DD format, got {value!r}")


def load_config(explicit_path: Path | None, scan_root: Path) -> Config:
    """Load config from an explicit path, else from `<scan_root>/.api-error-catalog.yaml`
    or the current working directory. Fall back to defaults when nothing is found."""
    candidates: list[Path] = []
    if explicit_path is not None:
        if not explicit_path.is_file():
            raise ConfigError(f"config file not found: {explicit_path}")
        candidates.append(explicit_path)
    else:
        root = scan_root if scan_root.is_dir() else scan_root.parent
        candidates.extend([root / DEFAULT_CONFIG_FILENAME, Path.cwd() / DEFAULT_CONFIG_FILENAME])

    for path in candidates:
        if path.is_file():
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
            return Config.from_dict(raw, source=str(path), base_dir=path.parent)
    return Config()
