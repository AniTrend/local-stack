#!/usr/bin/env python3
"""Validate OpenCode risk review output against the schema and safety rules.

Layer 1: Structural validation using the JSON Schema file (stdlib only).
Layer 2: Cross-field safety rules that JSON Schema draft-07 cannot express.

All rules are strict — any violation fails the validator.
"""

import json
import sys
from pathlib import Path


SCHEMA_FILE = ".github/opencode/risk-output.schema.json"


def load_json(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"ERROR: {path} is not valid JSON: {e}", file=sys.stderr)
        sys.exit(2)


def validate_required(instance: dict, schema: dict) -> list[str]:
    errors = []
    for field in schema.get("required", []):
        if field not in instance:
            errors.append(f"missing required field: {field!r}")
    return errors


def validate_types(instance: dict, schema: dict) -> list[str]:
    errors = []
    for field, prop_schema in schema.get("properties", {}).items():
        if field not in instance:
            continue
        expected = prop_schema.get("type")
        value = instance[field]
        if expected == "string" and not isinstance(value, str):
            errors.append(f"{field!r}: expected string, got {type(value).__name__}")
        elif expected == "boolean" and not isinstance(value, bool):
            errors.append(f"{field!r}: expected boolean, got {type(value).__name__}")
        elif expected == "array" and not isinstance(value, list):
            errors.append(f"{field!r}: expected array, got {type(value).__name__}")
        elif expected == "object" and not isinstance(value, dict):
            errors.append(f"{field!r}: expected object, got {type(value).__name__}")
    return errors


def validate_enums(instance: dict, schema: dict) -> list[str]:
    errors = []
    for field, prop_schema in schema.get("properties", {}).items():
        if field not in instance:
            continue
        valid = prop_schema.get("enum")
        if valid and instance[field] not in valid:
            errors.append(
                f"{field!r}: {instance[field]!r} not in {valid}"
            )
    return errors


def validate_const(instance: dict, schema: dict) -> list[str]:
    errors = []
    for field, prop_schema in schema.get("properties", {}).items():
        if field not in instance:
            continue
        if "const" in prop_schema and instance[field] != prop_schema["const"]:
            errors.append(
                f"{field!r}: expected {prop_schema['const']!r}, "
                f"got {instance[field]!r}"
            )
    return errors


def validate_min_length(instance: dict, schema: dict) -> list[str]:
    errors = []
    for field, prop_schema in schema.get("properties", {}).items():
        if field not in instance:
            continue
        min_len = prop_schema.get("minLength")
        if min_len is not None and isinstance(instance[field], str):
            if len(instance[field]) < min_len:
                errors.append(
                    f"{field!r}: must be at least {min_len} character(s)"
                )
    return errors


# --- Cross-field rules (cannot be expressed in JSON Schema draft-07) ----------

def validate_cross_field_rules(instance: dict) -> list[str]:
    errors = []

    decision = instance.get("decision")
    automerge = instance.get("automerge_allowed")
    update_type = instance.get("update_type")
    confidence = instance.get("confidence")

    # automerge_allowed requires decision=approve
    if automerge is True and decision != "approve":
        errors.append(
            f"automerge_allowed=true requires decision=approve "
            f"(got decision={decision!r})"
        )

    # semver-major cannot be auto-merged
    if update_type == "semver-major" and automerge is True:
        errors.append("update_type=semver-major cannot allow automerge")

    # confidence must be a recognized value when present
    valid_confidence = {"high", "medium", "low"}
    if confidence is not None and confidence not in valid_confidence:
        errors.append(
            f"confidence: {confidence!r} not in {sorted(valid_confidence)}"
        )

    return errors


def validate(output_file: str) -> int:
    schema = load_json(SCHEMA_FILE)
    data = load_json(output_file)

    errors = []
    errors.extend(validate_required(data, schema))
    errors.extend(validate_types(data, schema))
    errors.extend(validate_enums(data, schema))
    errors.extend(validate_const(data, schema))
    errors.extend(validate_min_length(data, schema))
    errors.extend(validate_cross_field_rules(data))

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"OK: {output_file} passed schema and safety validation")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            f"Usage: {Path(sys.argv[0]).name} <output-file>",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(validate(sys.argv[1]))
