"""A small validator for the JSON Schema subset used in config/tools.json.

Strict tool use already makes the model's arguments match the schema; this check covers what strict mode cannot:
arguments a person edits on an approval card, and fake clients in tests.
"""

from __future__ import annotations

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value, kind: str) -> bool:
    if kind in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[kind])


def errors(value, schema: dict, path: str = "$") -> list[str]:
    """Return a list of problems; an empty list means the value fits the schema."""
    if "anyOf" in schema:
        if any(not errors(value, option, path) for option in schema["anyOf"]):
            return []
        return [f"{path}: matches no allowed shape"]
    kinds = schema.get("type")
    if kinds is not None:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(_type_ok(value, k) for k in kinds):
            return [f"{path}: expected {'/'.join(kinds)}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: not one of {schema['enum']}"]
    found: list[str] = []
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                found.append(f"{path}.{key}: missing")
        for key, item in value.items():
            if key in props:
                found += errors(item, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                found.append(f"{path}.{key}: not allowed")
    elif isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            found += errors(item, schema["items"], f"{path}[{index}]")
    return found
