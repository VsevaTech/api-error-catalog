from __future__ import annotations

from tests.conftest import error_response_spec, spec_from_dict, spec_from_yaml

from api_error_catalog.config import Config
from api_error_catalog.extractor import extract, is_error_status
from api_error_catalog.models import UNCATEGORIZED, Location


def codes(result):
    return sorted(o.error_code for o in result.occurrences)


def test_is_error_status():
    assert is_error_status("400")
    assert is_error_status("503")
    assert is_error_status("4XX")
    assert is_error_status("5xx")
    assert not is_error_status("200")
    assert not is_error_status("3XX")
    assert not is_error_status("default")


def test_error_code_from_example():
    spec = spec_from_dict(
        error_response_spec(title="S", path="/x", status="400", example_code="invalid_otp")
    )
    result = extract(spec, Config())
    [occ] = result.occurrences
    assert occ.error_code == "invalid_otp"
    assert occ.location == Location.EXAMPLE
    assert occ.http_status == "400"
    assert occ.method == "GET"
    assert occ.path == "/x"
    assert occ.operation_id == "op"
    assert occ.schema_ref == "#/components/schemas/ErrorResponse"
    assert occ.field_name == "error_code"
    assert occ.signature.properties == (("error_code", "string"), ("message", "string"))
    assert occ.signature.required == ("error_code", "message")


def test_error_code_from_examples_map():
    doc = error_response_spec(title="S", path="/x", status="404")
    media = doc["paths"]["/x"]["get"]["responses"]["404"]["content"]["application/json"]
    media["examples"] = {
        "a": {"value": {"error_code": "user_not_found", "message": "m"}},
        "b": {"value": {"error_code": "company_not_found", "message": "m"}},
    }
    result = extract(spec_from_dict(doc), Config())
    assert codes(result) == ["company_not_found", "user_not_found"]
    assert all(o.location == Location.EXAMPLES for o in result.occurrences)


def test_error_code_from_enum_yields_multiple_codes():
    spec = spec_from_dict(
        error_response_spec(title="S", path="/x", status="400", enum=["invalid_otp", "otp_expired"])
    )
    result = extract(spec, Config())
    assert codes(result) == ["invalid_otp", "otp_expired"]
    assert {o.location for o in result.occurrences} == {Location.SCHEMA_ENUM}


def test_error_code_from_const():
    spec = spec_from_dict(
        error_response_spec(title="S", path="/x", status="402", const="payment_declined")
    )
    [occ] = extract(spec, Config()).occurrences
    assert occ.error_code == "payment_declined"
    assert occ.location == Location.SCHEMA_CONST


def test_error_code_from_property_default_and_example():
    doc = error_response_spec(title="S", path="/x", status="400", inline=True)
    prop = doc["paths"]["/x"]["get"]["responses"]["400"]["content"]["application/json"]["schema"][
        "properties"
    ]["error_code"]
    prop["default"] = "bad_request"
    result = extract(spec_from_dict(doc), Config())
    assert codes(result) == ["bad_request"]
    assert result.occurrences[0].location == Location.SCHEMA_DEFAULT

    del prop["default"]
    prop["example"] = "bad_request_example"
    result = extract(spec_from_dict(doc), Config())
    assert codes(result) == ["bad_request_example"]
    assert result.occurrences[0].location == Location.SCHEMA_EXAMPLE


def test_schema_and_example_codes_are_merged_without_duplicates():
    doc = error_response_spec(title="S", path="/x", status="400", enum=["a", "b"], example_code="a")
    result = extract(spec_from_dict(doc), Config())
    assert codes(result) == ["a", "b"]


def test_undocumented_error_without_json_content():
    doc = error_response_spec(title="S", path="/x", status="503")
    doc["paths"]["/x"]["get"]["responses"]["503"] = {"description": "Unavailable"}
    [occ] = extract(spec_from_dict(doc), Config()).occurrences
    assert occ.error_code == UNCATEGORIZED
    assert occ.is_uncategorized
    assert occ.location == Location.NONE
    assert occ.signature.is_empty()


def test_undocumented_error_with_schema_but_no_code():
    doc = error_response_spec(title="S", path="/x", status="401", inline=True)
    schema = doc["paths"]["/x"]["get"]["responses"]["401"]["content"]["application/json"]["schema"]
    schema["properties"] = {"message": {"type": "string"}}
    schema["required"] = ["message"]
    [occ] = extract(spec_from_dict(doc), Config()).occurrences
    assert occ.is_uncategorized
    assert occ.signature.properties == (("message", "string"),)


def test_success_responses_are_ignored():
    doc = error_response_spec(title="S", path="/x", status="404", example_code="nf")
    doc["paths"]["/x"]["get"]["responses"]["200"] = {
        "description": "ok",
        "content": {"application/json": {"example": {"error_code": "should_not_appear"}}},
    }
    assert codes(extract(spec_from_dict(doc), Config())) == ["nf"]


def test_configurable_error_code_fields():
    doc = error_response_spec(
        title="S", path="/x", status="400", code_field="errorId", example_code="oops"
    )
    default = extract(spec_from_dict(doc), Config())
    assert codes(default) == [UNCATEGORIZED]
    custom = extract(spec_from_dict(doc), Config(error_code_fields=("errorId",)))
    assert codes(custom) == ["oops"]
    assert custom.occurrences[0].field_name == "errorId"


def test_nested_envelope_example_is_understood():
    doc = error_response_spec(title="S", path="/x", status="400")
    media = doc["paths"]["/x"]["get"]["responses"]["400"]["content"]["application/json"]
    media["example"] = {"error": {"code": "nested_code", "message": "m"}}
    assert codes(extract(spec_from_dict(doc), Config())) == ["nested_code"]


def test_all_of_extension_keeps_base_ref_and_merges_properties():
    text = """
openapi: 3.0.3
info: {title: S, version: '1'}
paths:
  /otp:
    post:
      responses:
        '400':
          description: bad
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/ErrorResponse'
                  - properties:
                      error_code:
                        enum: [invalid_otp]
components:
  schemas:
    ErrorResponse:
      type: object
      required: [error_code]
      properties:
        error_code: {type: string}
        message: {type: string}
"""
    [occ] = extract(spec_from_yaml(text), Config()).occurrences
    assert occ.error_code == "invalid_otp"
    assert occ.schema_ref == "#/components/schemas/ErrorResponse"
    assert occ.signature.properties == (("error_code", "string"), ("message", "string"))
    assert occ.signature.required == ("error_code",)


def test_one_of_variants_each_contribute_codes_with_own_signature():
    text = """
openapi: 3.1.0
info: {title: S, version: '1'}
paths:
  /pay:
    post:
      responses:
        '400':
          description: bad
          content:
            application/json:
              schema:
                oneOf:
                  - type: object
                    properties:
                      code: {const: a}
                      message: {type: string}
                  - type: object
                    properties:
                      code: {const: b}
                      message: {type: string}
                      field: {type: string}
"""
    result = extract(spec_from_yaml(text), Config())
    by_code = {o.error_code: o for o in result.occurrences}
    assert set(by_code) == {"a", "b"}
    assert ("field", "string") not in by_code["a"].signature.properties
    assert ("field", "string") in by_code["b"].signature.properties


def test_shared_response_component_is_followed_and_ref_recorded():
    text = """
openapi: 3.0.3
info: {title: S, version: '1'}
paths:
  /a:
    get:
      responses:
        '500': {$ref: '#/components/responses/Internal'}
components:
  responses:
    Internal:
      description: boom
      content:
        application/json:
          schema: {$ref: '#/components/schemas/Err'}
          example: {error_code: internal_error}
  schemas:
    Err:
      type: object
      properties:
        error_code: {type: string}
"""
    [occ] = extract(spec_from_yaml(text), Config()).occurrences
    assert occ.error_code == "internal_error"
    assert occ.description == "boom"
    assert occ.schema_ref == "#/components/schemas/Err"


def test_remote_ref_produces_warning_and_uncategorized():
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
              schema: {$ref: 'shared.yaml#/components/schemas/Err'}
"""
    result = extract(spec_from_yaml(text), Config())
    assert [w.message for w in result.warnings] == [
        "remote $ref not resolved: shared.yaml#/components/schemas/Err"
    ]
    assert codes(result) == [UNCATEGORIZED]


def test_ignore_error_codes_config():
    doc = error_response_spec(title="S", path="/x", status="400", enum=["keep", "drop"])
    result = extract(spec_from_dict(doc), Config(ignore_error_codes=frozenset({"drop"})))
    assert codes(result) == ["keep"]


def test_operation_count_and_spec_info():
    doc = error_response_spec(title="Svc", path="/x", status="400")
    doc["paths"]["/y"] = {"post": {"responses": {"201": {"description": "created"}}}}
    result = extract(spec_from_dict(doc), Config())
    assert result.spec_info.operations == 2
    assert result.spec_info.service == "Svc"
    assert result.spec_info.version == "1.0.0"
    assert result.spec_info.openapi_version == "3.0.3"
