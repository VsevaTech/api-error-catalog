from __future__ import annotations

import pytest
from tests.conftest import error_response_spec

from api_error_catalog.loader import SpecLoadError, discover_spec_files, load_spec, load_specs

PATTERNS = ("*.yaml", "*.yml", "*.json")


def test_yaml_parsing(write_spec):
    path = write_spec("svc.yaml", error_response_spec(title="Svc", path="/x", status="404"))
    spec = load_spec(path)
    assert spec.service == "Svc"
    assert spec.openapi_version == "3.0.3"
    assert "/x" in spec.document["paths"]


def test_json_parsing(write_spec):
    path = write_spec("svc.json", error_response_spec(title="Json Svc", path="/x", status="404"))
    spec = load_spec(path)
    assert spec.service == "Json Svc"
    assert spec.document["openapi"] == "3.0.3"


def test_service_falls_back_to_file_stem(write_spec):
    doc = error_response_spec(title="X", path="/x", status="404")
    doc["info"] = {}
    path = write_spec("billing-api.yaml", doc)
    assert load_spec(path).service == "billing-api"


def test_malformed_yaml_raises(write_spec):
    path = write_spec("broken.yaml", "openapi: 3.0.0\npaths:\n  - : [unclosed\n")
    with pytest.raises(SpecLoadError, match="invalid YAML"):
        load_spec(path)


def test_malformed_json_raises(write_spec):
    path = write_spec("broken.json", '{"openapi": "3.0.0", ')
    with pytest.raises(SpecLoadError, match="invalid JSON"):
        load_spec(path)


def test_non_openapi_document_rejected(write_spec):
    path = write_spec("config.yaml", "error_code_fields: [code]\n")
    with pytest.raises(SpecLoadError, match="not an OpenAPI 3.x"):
        load_spec(path)


def test_load_specs_skips_unrelated_yaml_and_hidden_files(write_spec, tmp_path):
    write_spec("svc.yaml", error_response_spec(title="Svc", path="/x", status="404"))
    write_spec("docker-compose.yml", "services:\n  db:\n    image: postgres\n")
    write_spec(".api-error-catalog.yaml", "error_code_fields: [code]\n")
    specs, skipped = load_specs(tmp_path, PATTERNS)
    assert [s.service for s in specs] == ["Svc"]
    assert [p.name for p in skipped] == ["docker-compose.yml"]


def test_discover_recurses_into_subdirectories(write_spec, tmp_path):
    (tmp_path / "nested").mkdir()
    write_spec("nested/a.yaml", error_response_spec(title="A", path="/a", status="404"))
    write_spec("b.json", error_response_spec(title="B", path="/b", status="404"))
    found = discover_spec_files(tmp_path, PATTERNS)
    assert [p.name for p in found] == ["b.json", "a.yaml"]


def test_missing_directory_raises(tmp_path):
    with pytest.raises(SpecLoadError, match="does not exist"):
        load_specs(tmp_path / "nope", PATTERNS)


def test_empty_directory_raises(tmp_path):
    with pytest.raises(SpecLoadError, match="no specification files"):
        load_specs(tmp_path, PATTERNS)


def test_skipped_files_are_reported_as_info(write_spec, tmp_path):
    from api_error_catalog.analyzer import scan
    from api_error_catalog.config import Config
    from api_error_catalog.models import Severity

    write_spec(
        "svc.yaml", error_response_spec(title="Svc", path="/x", status="404", example_code="nf")
    )
    write_spec("old.yaml", 'swagger: "2.0"\ninfo: {title: Old, version: "1"}\npaths: {}\n')
    result = scan(tmp_path, Config())
    [info] = result.infos
    assert info.rule_id == "SPEC001"
    assert info.severity == Severity.INFO
    assert "old.yaml" in info.message
    assert result.summary()["warnings"] == 0
