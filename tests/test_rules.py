from __future__ import annotations

import yaml
from tests.conftest import analyze_yaml, error_response_spec

from api_error_catalog.models import Severity


def _yaml(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False)


def issues_for(result, rule_id):
    return [i for i in result.issues if i.rule_id == rule_id]


def test_same_code_same_status_is_not_a_conflict():
    a = error_response_spec(title="A", path="/a", status="404", example_code="user_not_found")
    b = error_response_spec(title="B", path="/b", status="404", example_code="user_not_found")
    result = analyze_yaml(("a.yaml", _yaml(a)), ("b.yaml", _yaml(b)))
    assert result.conflicts == []
    [entry] = result.catalog
    assert entry.error_code == "user_not_found"
    assert entry.http_statuses == ["404"]
    assert entry.services == ["A", "B"]


def test_same_code_different_status_is_conflict():
    a = error_response_spec(title="A", path="/a", status="404", example_code="user_not_found")
    b = error_response_spec(title="B", path="/b", status="400", example_code="user_not_found")
    result = analyze_yaml(("a.yaml", _yaml(a)), ("b.yaml", _yaml(b)))
    [issue] = issues_for(result, "ERROR001")
    assert issue.severity == Severity.CONFLICT
    assert issue.error_code == "user_not_found"
    assert "400 (B)" in issue.message and "404 (A)" in issue.message
    assert {o.http_status for o in issue.occurrences} == {"400", "404"}
    assert result.has_conflicts


def test_incompatible_schemas_is_conflict():
    a = error_response_spec(title="A", path="/a", status="429", example_code="rate_limit")
    b = error_response_spec(
        title="B",
        path="/b",
        status="429",
        code_field="code",
        example_code="rate_limit",
        extra_props={"retry_after": {"type": "integer"}},
    )
    result = analyze_yaml(("a.yaml", _yaml(a)), ("b.yaml", _yaml(b)))
    [issue] = issues_for(result, "ERROR002")
    assert issue.severity == Severity.CONFLICT
    assert "retry_after: integer" in issue.message
    assert issues_for(result, "ERROR001") == []


def test_identical_schemas_do_not_conflict():
    a = error_response_spec(title="A", path="/a", status="429", example_code="rate_limit")
    b = error_response_spec(title="B", path="/b", status="429", example_code="rate_limit")
    result = analyze_yaml(("a.yaml", _yaml(a)), ("b.yaml", _yaml(b)))
    assert issues_for(result, "ERROR002") == []


def test_schema_less_responses_do_not_trigger_schema_conflict():
    a = error_response_spec(title="A", path="/a", status="404", example_code="nf")
    b = error_response_spec(title="B", path="/b", status="404")
    del b["paths"]["/b"]["get"]["responses"]["404"]["content"]["application/json"]["schema"]
    b["paths"]["/b"]["get"]["responses"]["404"]["content"]["application/json"]["example"] = {
        "error_code": "nf"
    }
    result = analyze_yaml(("a.yaml", _yaml(a)), ("b.yaml", _yaml(b)))
    assert issues_for(result, "ERROR002") == []


def test_description_mismatch_is_warning_and_ignores_case_and_punctuation():
    a = error_response_spec(
        title="A", path="/a", status="404", example_code="nf", description="User not found."
    )
    b = error_response_spec(
        title="B", path="/b", status="404", example_code="nf", description="user NOT found"
    )
    c = error_response_spec(
        title="C", path="/c", status="404", example_code="nf", description="Unknown user"
    )
    same = analyze_yaml(("a.yaml", _yaml(a)), ("b.yaml", _yaml(b)))
    assert issues_for(same, "ERROR003") == []
    differ = analyze_yaml(("a.yaml", _yaml(a)), ("c.yaml", _yaml(c)))
    [issue] = issues_for(differ, "ERROR003")
    assert issue.severity == Severity.WARNING
    assert not differ.has_conflicts


def test_undocumented_4xx_is_warning():
    a = error_response_spec(title="A", path="/a", status="401")
    a["paths"]["/a"]["get"]["responses"]["401"] = {"description": "Unauthorized"}
    result = analyze_yaml(("a.yaml", _yaml(a)))
    [issue] = issues_for(result, "ERROR004")
    assert issue.severity == Severity.WARNING
    assert issue.error_code is None
    assert "GET /a 401" in issue.message
    assert result.catalog == []
    assert not result.has_conflicts


def test_duplicate_definition_within_service_warning_and_conflict():
    doc = error_response_spec(title="A", path="/a", status="409", example_code="blocked")
    # Second operation: inline copy of the same structure -> WARNING
    doc["paths"]["/b"] = {
        "post": {
            "responses": {
                "409": {
                    "description": "dup",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["error_code", "message"],
                                "properties": {
                                    "error_code": {"type": "string", "enum": ["blocked"]},
                                    "message": {"type": "string"},
                                },
                            }
                        }
                    },
                }
            }
        }
    }
    result = analyze_yaml(("a.yaml", _yaml(doc)))
    [issue] = issues_for(result, "ERROR005")
    assert issue.severity == Severity.WARNING
    assert "identical structure" in issue.message

    # Diverging structure -> CONFLICT
    props = doc["paths"]["/b"]["post"]["responses"]["409"]["content"]["application/json"]["schema"][
        "properties"
    ]
    props["reason"] = {"type": "string"}
    result = analyze_yaml(("a.yaml", _yaml(doc)))
    [issue] = issues_for(result, "ERROR005")
    assert issue.severity == Severity.CONFLICT
    assert "different structures" in issue.message


def test_shared_schema_reused_across_operations_is_not_duplicate():
    doc = error_response_spec(title="A", path="/a", status="404", example_code="nf")
    doc["paths"]["/b"] = {
        "get": {
            "responses": {
                "404": {
                    "description": "nf",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                            "example": {"error_code": "nf"},
                        }
                    },
                }
            }
        }
    }
    result = analyze_yaml(("a.yaml", _yaml(doc)))
    assert issues_for(result, "ERROR005") == []


def test_remote_ref_surfaces_as_ref001_warning():
    text = """
openapi: 3.0.3
info: {title: S, version: '1'}
paths:
  /a:
    get:
      responses:
        '503':
          description: down
          content:
            application/json:
              schema: {$ref: 'https://example.test/errors.yaml#/Err'}
"""
    result = analyze_yaml(("s.yaml", text))
    [issue] = issues_for(result, "REF001")
    assert issue.severity == Severity.WARNING
    assert "remote $ref not resolved" in issue.message


def test_issues_sorted_conflicts_first():
    a = error_response_spec(title="A", path="/a", status="404", example_code="nf")
    b = error_response_spec(title="B", path="/b", status="400", example_code="nf")
    b["paths"]["/b"]["get"]["responses"]["503"] = {"description": "down"}
    result = analyze_yaml(("a.yaml", _yaml(a)), ("b.yaml", _yaml(b)))
    severities = [i.severity for i in result.issues]
    assert severities == sorted(severities, key=lambda s: ["CONFLICT", "WARNING", "INFO"].index(s))
    assert result.summary()["conflicts"] == 1
