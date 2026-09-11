"""Machine-readable JSON report."""

from __future__ import annotations

import json
from typing import Any

from .. import __version__
from ..models import ScanResult

SCHEMA_VERSION = 1


def to_dict(result: ScanResult) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "api-error-catalog", "version": __version__},
        "summary": result.summary(),
        "specifications": [
            {
                "service": s.service,
                "source_file": s.source_file,
                "title": s.title,
                "version": s.version,
                "openapi": s.openapi_version,
                "operations": s.operations,
            }
            for s in result.specs
        ],
        "catalog": [entry.to_dict() for entry in result.catalog],
        "issues": [issue.to_dict() for issue in result.issues],
        "uncategorized": [o.to_dict() for o in result.occurrences if o.is_uncategorized],
    }


def render_json(result: ScanResult) -> str:
    return json.dumps(to_dict(result), indent=2, ensure_ascii=False) + "\n"
