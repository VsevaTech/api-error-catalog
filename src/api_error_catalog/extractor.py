"""Extract error occurrences from OpenAPI operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .loader import LoadedSpec
from .models import (
    UNCATEGORIZED,
    ErrorOccurrence,
    LoadWarning,
    Location,
    SchemaSignature,
    SpecInfo,
)
from .resolver import RefResolver

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
MAX_NESTING_DEPTH = 3


@dataclass(slots=True)
class ExtractionResult:
    spec_info: SpecInfo
    occurrences: list[ErrorOccurrence]
    warnings: list[LoadWarning] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def is_error_status(status: str) -> bool:
    status = str(status).upper()
    if len(status) != 3:
        return False
    return status[0] in ("4", "5") and (status[1:].isdigit() or status[1:] == "XX")


def pick_json_media(content: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Prefer `application/json`, then any `*json` media type."""
    if not isinstance(content, dict):
        return None
    if isinstance(content.get("application/json"), dict):
        return "application/json", content["application/json"]
    for media_type, media in content.items():
        if isinstance(media, dict) and media_type.split(";")[0].strip().endswith("json"):
            return media_type, media
    return None


def _find_field(value: Any, fields: tuple[str, ...], depth: int = 0) -> Any:
    """Return the value of the first configured field found in a JSON-like value.

    Top-level keys win; nested mappings are searched breadth-first up to a small depth so
    envelopes like `{"error": {"code": ...}}` are still understood.
    """
    if not isinstance(value, dict):
        return None
    for name in fields:
        if name in value:
            return value[name]
    if depth >= MAX_NESTING_DEPTH:
        return None
    for child in value.values():
        if isinstance(child, dict):
            found = _find_field(child, fields, depth + 1)
            if found is not None:
                return found
    return None


def _as_code(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, int):
        return str(value)
    return None


def _schema_type(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "unknown"
    if schema.get("x-circular"):
        return "ref"
    type_ = schema.get("type")
    if isinstance(type_, list):
        return "|".join(sorted(str(t) for t in type_))
    if isinstance(type_, str):
        return type_
    if "properties" in schema or "allOf" in schema:
        return "object"
    if "enum" in schema or "const" in schema:
        return "string"
    if "oneOf" in schema or "anyOf" in schema:
        return "union"
    return "any"


def flatten_all_of(schema: dict[str, Any]) -> dict[str, Any]:
    """Merge `allOf` members into a single object schema (shallow merge of properties)."""
    if "allOf" not in schema or not isinstance(schema["allOf"], list):
        return schema
    merged: dict[str, Any] = {k: v for k, v in schema.items() if k != "allOf"}
    props: dict[str, Any] = dict(merged.get("properties") or {})
    required: list[str] = list(merged.get("required") or [])
    for member in schema["allOf"]:
        if not isinstance(member, dict):
            continue
        member = flatten_all_of(member)
        props.update(member.get("properties") or {})
        for name in member.get("required") or []:
            if name not in required:
                required.append(name)
        if "type" not in merged and "type" in member:
            merged["type"] = member["type"]
    if props:
        merged["properties"] = props
    if required:
        merged["required"] = required
    return merged


def expand_variants(schema: Any) -> list[dict[str, Any]]:
    """Return the concrete object schemas a response may take (oneOf/anyOf branches)."""
    if not isinstance(schema, dict):
        return []
    schema = flatten_all_of(schema)
    for keyword in ("oneOf", "anyOf"):
        branches = schema.get(keyword)
        if isinstance(branches, list) and branches:
            variants: list[dict[str, Any]] = []
            for branch in branches:
                variants.extend(expand_variants(branch))
            return variants or [schema]
    return [schema]


def build_signature(schema: dict[str, Any]) -> SchemaSignature:
    schema = flatten_all_of(schema)
    props = schema.get("properties")
    if not isinstance(props, dict):
        return SchemaSignature()
    properties = tuple(sorted((name, _schema_type(sub)) for name, sub in props.items()))
    required = tuple(sorted(str(r) for r in schema.get("required") or [] if r in props))
    return SchemaSignature(properties=properties, required=required)


def _find_property(schema: dict[str, Any], fields: tuple[str, ...], depth: int = 0) -> Any:
    """Locate the schema of the error-code property (top level first, then nested objects)."""
    schema = flatten_all_of(schema)
    props = schema.get("properties")
    if not isinstance(props, dict):
        return None
    for name in fields:
        if name in props and isinstance(props[name], dict):
            return name, props[name]
    if depth >= MAX_NESTING_DEPTH:
        return None
    for sub in props.values():
        if isinstance(sub, dict) and not sub.get("x-circular"):
            for variant in expand_variants(sub):
                found = _find_property(variant, fields, depth + 1)
                if found:
                    return found
    return None


def codes_from_schema(
    schema: dict[str, Any], fields: tuple[str, ...]
) -> list[tuple[str, Location, str]]:
    """Return `(code, location, field_name)` triples found in a schema variant."""
    found = _find_property(schema, fields)
    if not found:
        return []
    field_name, prop = found
    results: list[tuple[str, Location, str]] = []
    const = _as_code(prop.get("const"))
    if const:
        results.append((const, Location.SCHEMA_CONST, field_name))
    enum = prop.get("enum")
    if isinstance(enum, list):
        for item in enum:
            code = _as_code(item)
            if code:
                results.append((code, Location.SCHEMA_ENUM, field_name))
    default = _as_code(prop.get("default"))
    if default:
        results.append((default, Location.SCHEMA_DEFAULT, field_name))
    example = _as_code(prop.get("example"))
    if example:
        results.append((example, Location.SCHEMA_EXAMPLE, field_name))
    examples = prop.get("examples")
    if isinstance(examples, list):
        for item in examples:
            code = _as_code(item)
            if code:
                results.append((code, Location.SCHEMA_EXAMPLE, field_name))
    return results


def codes_from_examples(
    media: dict[str, Any], schema: Any, fields: tuple[str, ...]
) -> list[tuple[str, Location]]:
    results: list[tuple[str, Location]] = []
    if "example" in media:
        code = _as_code(_find_field(media["example"], fields))
        if code:
            results.append((code, Location.EXAMPLE))
    examples = media.get("examples")
    if isinstance(examples, dict):
        for example in examples.values():
            if isinstance(example, dict):
                code = _as_code(_find_field(example.get("value"), fields))
                if code:
                    results.append((code, Location.EXAMPLES))
    # OpenAPI 3.1 allows examples directly on the schema.
    if isinstance(schema, dict):
        for key in ("example", "examples"):
            payloads = schema.get(key)
            payloads = payloads if isinstance(payloads, list) else [payloads]
            for payload in payloads:
                code = _as_code(_find_field(payload, fields))
                if code:
                    results.append((code, Location.SCHEMA_EXAMPLE))
    return results


# --------------------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------------------


def extract(spec: LoadedSpec, config: Config) -> ExtractionResult:
    doc = spec.document
    resolver = RefResolver(doc)
    fields = config.error_code_fields
    service = spec.service
    source_file = spec.path.name
    occurrences: list[ErrorOccurrence] = []
    operations = 0

    paths = doc.get("paths") or {}
    if not isinstance(paths, dict):
        paths = {}

    for path, path_item in sorted(paths.items()):
        _, path_item = resolver.deref(path_item)
        if not isinstance(path_item, dict):
            continue
        for method in HTTP_METHODS:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            operations += 1
            responses = operation.get("responses") or {}
            if not isinstance(responses, dict):
                continue
            for status, raw_response in sorted(responses.items(), key=lambda kv: str(kv[0])):
                status = str(status)
                if not is_error_status(status):
                    continue
                response_ref, response = resolver.deref(raw_response)
                if not isinstance(response, dict):
                    continue
                occurrences.extend(
                    _extract_response(
                        response=response,
                        response_ref=response_ref,
                        resolver=resolver,
                        fields=fields,
                        service=service,
                        source_file=source_file,
                        status=status,
                        method=method,
                        path=path,
                        operation_id=operation.get("operationId"),
                    )
                )

    if config.ignore_error_codes:
        occurrences = [o for o in occurrences if o.error_code not in config.ignore_error_codes]

    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    spec_info = SpecInfo(
        service=service,
        source_file=source_file,
        title=str(info.get("title") or spec.path.stem),
        version=str(info["version"]) if info.get("version") is not None else None,
        openapi_version=spec.openapi_version,
        operations=operations,
    )
    warnings = [
        LoadWarning(source_file, f"remote $ref not resolved: {ref}") for ref in resolver.remote_refs
    ] + [
        LoadWarning(source_file, f"unresolvable local $ref: {ref}") for ref in resolver.missing_refs
    ]
    return ExtractionResult(spec_info=spec_info, occurrences=occurrences, warnings=warnings)


def _extract_response(
    *,
    response: dict[str, Any],
    response_ref: str | None,
    resolver: RefResolver,
    fields: tuple[str, ...],
    service: str,
    source_file: str,
    status: str,
    method: str,
    path: str,
    operation_id: str | None,
) -> list[ErrorOccurrence]:
    description = response.get("description")
    description = description.strip() if isinstance(description, str) else None
    _, content = resolver.deref(response.get("content") or {})
    picked = pick_json_media(content)

    def make(code: str, location: Location, field_name: str | None, sig: SchemaSignature, ref):
        return ErrorOccurrence(
            service=service,
            source_file=source_file,
            error_code=code,
            http_status=status,
            method=method.upper(),
            path=path,
            operation_id=operation_id if isinstance(operation_id, str) else None,
            description=description,
            schema_ref=ref,
            location=location,
            field_name=field_name,
            signature=sig,
        )

    if picked is None:
        return [make(UNCATEGORIZED, Location.NONE, None, SchemaSignature(), None)]

    _, media = picked
    _, media = resolver.deref(media)
    raw_schema = media.get("schema")
    schema_ref = RefResolver.named_ref(raw_schema) or response_ref
    media = resolver.resolve(media)
    schema = resolver.resolve(raw_schema) if raw_schema is not None else None
    variants = expand_variants(schema)

    # Codes contributed by each schema variant, keyed by code -> (location, field, signature).
    seen: dict[str, ErrorOccurrence] = {}
    variant_signatures: list[SchemaSignature] = []
    for variant in variants:
        sig = build_signature(variant)
        variant_signatures.append(sig)
        for code, location, field_name in codes_from_schema(variant, fields):
            if code not in seen:
                seen[code] = make(code, location, field_name, sig, schema_ref)

    default_sig = variant_signatures[0] if variant_signatures else SchemaSignature()
    default_field = next(
        (o.field_name for o in seen.values() if o.field_name), None
    ) or _guess_field_name(variants, fields)

    for code, location in codes_from_examples(media, schema, fields):
        if code not in seen:
            # Attach to the variant that declares this code, else the first one.
            sig = default_sig
            for variant, variant_sig in zip(variants, variant_signatures, strict=True):
                if any(c == code for c, _, _ in codes_from_schema(variant, fields)):
                    sig = variant_sig
                    break
            seen[code] = make(code, location, default_field, sig, schema_ref)

    if not seen:
        return [make(UNCATEGORIZED, Location.NONE, default_field, default_sig, schema_ref)]

    # Preserve a stable order: schema-declared codes first, in declaration order.
    return list(seen.values())


def _guess_field_name(variants: list[dict[str, Any]], fields: tuple[str, ...]) -> str | None:
    for variant in variants:
        found = _find_property(variant, fields)
        if found:
            return found[0]
    return None
