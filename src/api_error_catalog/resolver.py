"""Local `$ref` resolution for a single OpenAPI document."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote


class RefResolver:
    """Resolve `#/...` JSON pointers inside one document.

    Remote and file references are not resolved in the MVP: they are recorded in
    `remote_refs` and the referencing node is returned unchanged (minus the `$ref`).
    """

    def __init__(self, document: dict[str, Any]):
        self.document = document
        self.remote_refs: list[str] = []
        self.missing_refs: list[str] = []

    # -- pointer helpers --------------------------------------------------------------

    @staticmethod
    def is_local(ref: str) -> bool:
        return ref.startswith("#/") or ref == "#"

    def lookup(self, ref: str) -> Any:
        if not self.is_local(ref):
            raise KeyError(ref)
        node: Any = self.document
        pointer = ref[1:]
        if pointer in ("", "/"):
            return node
        for raw in pointer.lstrip("/").split("/"):
            token = unquote(raw).replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict):
                if token not in node:
                    raise KeyError(ref)
                node = node[token]
            elif isinstance(node, list):
                try:
                    node = node[int(token)]
                except (ValueError, IndexError):
                    raise KeyError(ref) from None
            else:
                raise KeyError(ref)
        return node

    # -- resolution --------------------------------------------------------------------

    def resolve(self, node: Any, _seen: frozenset[str] = frozenset()) -> Any:
        """Return a deep copy of `node` with local `$ref`s inlined.

        Cycles are cut by leaving a `{"$ref": ...}` stub in place when a reference is
        already on the current resolution path.
        """
        if isinstance(node, list):
            return [self.resolve(item, _seen) for item in node]
        if not isinstance(node, dict):
            return node

        ref = node.get("$ref")
        if isinstance(ref, str):
            if not self.is_local(ref):
                if ref not in self.remote_refs:
                    self.remote_refs.append(ref)
                return {k: self.resolve(v, _seen) for k, v in node.items() if k != "$ref"}
            if ref in _seen:
                return {"$ref": ref, "x-circular": True}
            try:
                target = self.lookup(ref)
            except KeyError:
                if ref not in self.missing_refs:
                    self.missing_refs.append(ref)
                return {k: self.resolve(v, _seen) for k, v in node.items() if k != "$ref"}
            resolved = self.resolve(target, _seen | {ref})
            if isinstance(resolved, dict):
                # Sibling keys next to $ref (allowed in 3.1) override the target.
                merged = dict(resolved)
                for key, value in node.items():
                    if key != "$ref":
                        merged[key] = self.resolve(value, _seen)
                return merged
            return resolved

        return {k: self.resolve(v, _seen) for k, v in node.items()}

    def deref(self, node: Any) -> tuple[str | None, Any]:
        """Follow a chain of local `$ref`s one node deep, without resolving children.

        Returns `(first_ref, target)`. Remote or missing references are recorded and the
        node is returned unchanged.
        """
        first_ref: str | None = None
        seen: set[str] = set()
        while isinstance(node, dict) and isinstance(node.get("$ref"), str):
            ref = node["$ref"]
            if not self.is_local(ref):
                if ref not in self.remote_refs:
                    self.remote_refs.append(ref)
                return first_ref, {k: v for k, v in node.items() if k != "$ref"}
            if ref in seen:
                return first_ref, {}
            seen.add(ref)
            first_ref = first_ref or ref
            try:
                node = self.lookup(ref)
            except KeyError:
                if ref not in self.missing_refs:
                    self.missing_refs.append(ref)
                return first_ref, {}
        return first_ref, node

    @staticmethod
    def direct_ref(node: Any) -> str | None:
        """Return the `$ref` string if `node` is a bare reference object."""
        if isinstance(node, dict) and isinstance(node.get("$ref"), str):
            return node["$ref"]
        return None

    @classmethod
    def named_ref(cls, schema: Any) -> str | None:
        """Best-effort name of the reusable schema a response schema is based on.

        A direct `$ref` wins; otherwise the first `$ref` among `allOf` members is used
        (the common "extend the shared ErrorResponse" pattern).
        """
        direct = cls.direct_ref(schema)
        if direct:
            return direct
        if isinstance(schema, dict):
            for member in schema.get("allOf") or []:
                ref = cls.direct_ref(member)
                if ref:
                    return ref
        return None
