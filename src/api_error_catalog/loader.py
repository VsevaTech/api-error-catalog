"""Discover and parse OpenAPI documents (YAML or JSON)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class SpecLoadError(Exception):
    """Raised when a specification file cannot be parsed or is not an OpenAPI document."""


@dataclass(slots=True)
class LoadedSpec:
    path: Path
    document: dict[str, Any]

    @property
    def service(self) -> str:
        """Service identifier: the spec's `info.title`, falling back to the file stem."""
        info = self.document.get("info")
        if isinstance(info, dict):
            title = info.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()
        return self.path.stem

    @property
    def openapi_version(self) -> str | None:
        version = self.document.get("openapi")
        return str(version) if version is not None else None


def discover_spec_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    """Return all candidate spec files under `root` (or `root` itself when it is a file)."""
    if root.is_file():
        return [root]
    if not root.is_dir():
        raise SpecLoadError(f"path does not exist: {root}")
    files: set[Path] = set()
    for pattern in patterns:
        files.update(p for p in root.rglob(pattern) if p.is_file())
    # Skip our own config file and hidden directories.
    return sorted(
        p
        for p in files
        if not p.name.startswith(".") and not any(part.startswith(".") for part in p.parts)
    )


def parse_document(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecLoadError(f"{path}: invalid JSON: {exc}") from exc
    else:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise SpecLoadError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecLoadError(f"{path}: document root must be a mapping")
    return data


def is_openapi_document(document: dict[str, Any]) -> bool:
    version = document.get("openapi")
    return isinstance(version, str) and version.startswith("3.")


def load_spec(path: Path) -> LoadedSpec:
    document = parse_document(path)
    if not is_openapi_document(document):
        raise SpecLoadError(
            f"{path}: not an OpenAPI 3.x document (missing or unsupported 'openapi' field)"
        )
    return LoadedSpec(path=path, document=document)


def load_specs(root: Path, patterns: tuple[str, ...]) -> tuple[list[LoadedSpec], list[Path]]:
    """Load every OpenAPI document under `root`.

    Files that parse fine but are not OpenAPI documents (e.g. unrelated YAML) are skipped and
    returned in the second list so the caller can report them. Malformed files raise.
    """
    specs: list[LoadedSpec] = []
    skipped: list[Path] = []
    for path in discover_spec_files(root, patterns):
        document = parse_document(path)
        if not is_openapi_document(document):
            skipped.append(path)
            continue
        specs.append(LoadedSpec(path=path, document=document))
    if not specs and not skipped:
        raise SpecLoadError(f"no specification files found under {root}")
    return specs, skipped
