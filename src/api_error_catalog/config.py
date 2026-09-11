"""Configuration file handling (`.api-error-catalog.yaml`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_FILENAME = ".api-error-catalog.yaml"
DEFAULT_ERROR_CODE_FIELDS = ("error_code", "errorCode", "code")


class ConfigError(Exception):
    """Raised when the configuration file is missing or malformed."""


@dataclass(slots=True)
class Config:
    error_code_fields: tuple[str, ...] = DEFAULT_ERROR_CODE_FIELDS
    include_patterns: tuple[str, ...] = ("*.yaml", "*.yml", "*.json")
    ignore_error_codes: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_dict(cls, data: dict, source: str = "<config>") -> Config:
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
        unknown = set(data) - {"error_code_fields", "include_patterns", "ignore_error_codes"}
        if unknown:
            raise ConfigError(f"{source}: unknown configuration keys: {sorted(unknown)}")
        return cfg


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
            return Config.from_dict(raw, source=str(path))
    return Config()
