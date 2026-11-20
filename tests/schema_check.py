"""A small JSON Schema checker for the subset the repository's schemas use (no extra dependency)."""

from __future__ import annotations

import re
from typing import Any

_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _is(v: Any, t: str) -> bool:
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def validate(inst: Any, schema: dict[str, Any], root: dict[str, Any] | None = None, path: str = "$") -> list[str]:
    """Return a list of violations (empty when ``inst`` conforms)."""
    root = root or schema
    if "$ref" in schema:
        node: Any = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        return validate(inst, node, root, path)
    errs: list[str] = []
    if "oneOf" in schema:
        results = [validate(inst, s, root, path) for s in schema["oneOf"]]
        ok = sum(1 for r in results if not r)
        if ok != 1:
            return [f"{path}: matches {ok} of the oneOf branches; first branch errors: {results[0][:3]}"]
        return []
    if "const" in schema and inst != schema["const"]:
        errs.append(f"{path}: expected {schema['const']!r}, got {inst!r}")
    if "enum" in schema and inst not in schema["enum"]:
        errs.append(f"{path}: {inst!r} not in {schema['enum']}")
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_is(inst, x) for x in types):
            return [*errs, f"{path}: expected {types}, got {type(inst).__name__}"]
    if isinstance(inst, str):
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            errs.append(f"{path}: {inst!r} does not match {schema['pattern']!r}")
        if len(inst) < schema.get("minLength", 0):
            errs.append(f"{path}: shorter than {schema['minLength']}")
    if (
        isinstance(inst, (int, float))
        and not isinstance(inst, bool)
        and "minimum" in schema
        and inst < schema["minimum"]
    ):
        errs.append(f"{path}: {inst} below {schema['minimum']}")
    if isinstance(inst, dict):
        for k in schema.get("required", []):
            if k not in inst:
                errs.append(f"{path}: missing required {k!r}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties")
        for k, v in inst.items():
            if k in props:
                errs += validate(v, props[k], root, f"{path}.{k}")
            elif isinstance(extra, dict):
                errs += validate(v, extra, root, f"{path}.{k}")
    if isinstance(inst, list) and "items" in schema:
        for i, v in enumerate(inst):
            errs += validate(v, schema["items"], root, f"{path}[{i}]")
    return errs
