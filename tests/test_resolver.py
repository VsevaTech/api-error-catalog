from __future__ import annotations

from api_error_catalog.resolver import RefResolver


def test_local_ref_resolved_recursively():
    doc = {
        "components": {
            "schemas": {
                "Error": {
                    "type": "object",
                    "properties": {"detail": {"$ref": "#/components/schemas/Detail"}},
                },
                "Detail": {"type": "object", "properties": {"field": {"type": "string"}}},
            }
        }
    }
    resolver = RefResolver(doc)
    resolved = resolver.resolve({"$ref": "#/components/schemas/Error"})
    assert resolved["properties"]["detail"]["properties"]["field"] == {"type": "string"}
    assert resolver.remote_refs == []
    assert resolver.missing_refs == []


def test_remote_ref_is_recorded_not_resolved():
    resolver = RefResolver({})
    node = {"$ref": "common/errors.yaml#/components/schemas/Error", "description": "x"}
    resolved = resolver.resolve(node)
    assert resolved == {"description": "x"}
    assert resolver.remote_refs == ["common/errors.yaml#/components/schemas/Error"]


def test_missing_local_ref_is_recorded():
    resolver = RefResolver({"components": {"schemas": {}}})
    resolved = resolver.resolve({"$ref": "#/components/schemas/Nope"})
    assert resolved == {}
    assert resolver.missing_refs == ["#/components/schemas/Nope"]


def test_circular_ref_does_not_recurse_forever():
    doc = {
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {"next": {"$ref": "#/components/schemas/Node"}},
                }
            }
        }
    }
    resolved = RefResolver(doc).resolve({"$ref": "#/components/schemas/Node"})
    assert resolved["properties"]["next"]["x-circular"] is True


def test_json_pointer_escaping():
    doc = {"paths": {"/a/{id}": {"get": {"operationId": "x"}}}}
    resolver = RefResolver(doc)
    assert resolver.lookup("#/paths/~1a~1{id}/get")["operationId"] == "x"


def test_sibling_keys_override_target():
    doc = {"components": {"schemas": {"E": {"type": "object", "description": "base"}}}}
    resolved = RefResolver(doc).resolve({"$ref": "#/components/schemas/E", "description": "own"})
    assert resolved == {"type": "object", "description": "own"}


def test_deref_returns_first_ref_and_target():
    doc = {
        "components": {
            "responses": {"NotFound": {"$ref": "#/components/responses/Base"}},
            "responses2": {},
        }
    }
    doc["components"]["responses"]["Base"] = {"description": "base"}
    ref, target = RefResolver(doc).deref({"$ref": "#/components/responses/NotFound"})
    assert ref == "#/components/responses/NotFound"
    assert target == {"description": "base"}


def test_named_ref_prefers_direct_then_all_of():
    assert RefResolver.named_ref({"$ref": "#/a"}) == "#/a"
    assert RefResolver.named_ref({"allOf": [{"$ref": "#/b"}, {"type": "object"}]}) == "#/b"
    assert RefResolver.named_ref({"type": "object"}) is None
