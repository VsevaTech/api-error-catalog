from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from api_error_catalog.analyzer import analyze_specs
from api_error_catalog.config import Config
from api_error_catalog.loader import LoadedSpec
from api_error_catalog.models import ScanResult

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = Path(__file__).parent.parent / "examples" / "specs"


def spec_from_yaml(text: str, name: str = "service.yaml") -> LoadedSpec:
    return LoadedSpec(path=Path(name), document=yaml.safe_load(text))


def spec_from_dict(document: dict, name: str = "service.yaml") -> LoadedSpec:
    return LoadedSpec(path=Path(name), document=document)


def analyze_yaml(*docs: tuple[str, str], config: Config | None = None) -> ScanResult:
    specs = [spec_from_yaml(text, name) for name, text in docs]
    return analyze_specs(specs, config or Config())


def error_response_spec(
    *,
    title: str,
    path: str,
    status: str,
    code_field: str = "error_code",
    example_code: str | None = None,
    enum: list[str] | None = None,
    const: str | None = None,
    description: str = "Error",
    extra_props: dict | None = None,
    inline: bool = False,
) -> dict:
    """Build a minimal OpenAPI document with one operation and one error response."""
    prop: dict = {"type": "string"}
    if enum is not None:
        prop["enum"] = enum
    if const is not None:
        prop["const"] = const
    schema = {
        "type": "object",
        "required": [code_field, "message"],
        "properties": {code_field: prop, "message": {"type": "string"}, **(extra_props or {})},
    }
    media: dict = {}
    if inline:
        media["schema"] = schema
    else:
        media["schema"] = {"$ref": "#/components/schemas/ErrorResponse"}
    if example_code is not None:
        media["example"] = {code_field: example_code, "message": "Something happened"}
    return {
        "openapi": "3.0.3",
        "info": {"title": title, "version": "1.0.0"},
        "paths": {
            path: {
                "get": {
                    "operationId": "op",
                    "responses": {
                        "200": {"description": "OK"},
                        status: {
                            "description": description,
                            "content": {"application/json": media},
                        },
                    },
                }
            }
        },
        "components": {"schemas": {"ErrorResponse": schema}},
    }


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES


@pytest.fixture
def write_spec(tmp_path: Path):
    def _write(name: str, document: dict | str) -> Path:
        target = tmp_path / name
        if isinstance(document, str):
            target.write_text(document, encoding="utf-8")
        elif name.endswith(".json"):
            target.write_text(json.dumps(document), encoding="utf-8")
        else:
            target.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return target

    return _write
