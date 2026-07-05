#!/usr/bin/env python3
"""Validate OpenCode risk review output against the local-stack schema."""

import json
import sys


def validate(output_file: str) -> int:
    try:
        with open(output_file) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {output_file} not found", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"ERROR: {output_file} is not valid JSON: {e}", file=sys.stderr)
        return 2

    required = [
        "schema_version", "decision", "risk",
        "automerge_allowed", "dependency_ecosystem",
        "update_type", "summary"
    ]
    missing = [k for k in required if k not in data]
    if missing:
        print(f"ERROR: missing required fields: {missing}", file=sys.stderr)
        return 1

    if data["schema_version"] != "local-stack.dependabot-risk.v1":
        print(f"ERROR: invalid schema_version: {data['schema_version']}", file=sys.stderr)
        return 1

    valid_decisions = {"approve", "changes_requested", "neutral"}
    if data["decision"] not in valid_decisions:
        print(f"ERROR: invalid decision: {data['decision']}", file=sys.stderr)
        return 1

    valid_risks = {"low", "medium", "high", "unknown"}
    if data["risk"] not in valid_risks:
        print(f"ERROR: invalid risk: {data['risk']}", file=sys.stderr)
        return 1

    if not isinstance(data["automerge_allowed"], bool):
        print(f"ERROR: automerge_allowed must be boolean", file=sys.stderr)
        return 1

    valid_ecosystems = {"docker", "github-actions", "mixed", "unknown"}
    if data["dependency_ecosystem"] not in valid_ecosystems:
        print(f"ERROR: invalid dependency_ecosystem: {data['dependency_ecosystem']}", file=sys.stderr)
        return 1

    valid_update_types = {"semver-patch", "semver-minor", "semver-major", "digest", "non-semver", "unknown"}
    if data["update_type"] not in valid_update_types:
        print(f"ERROR: invalid update_type: {data['update_type']}", file=sys.stderr)
        return 1

    if not isinstance(data["summary"], str) or not data["summary"].strip():
        print(f"ERROR: summary must be a non-empty string", file=sys.stderr)
        return 1

    print(f"OK: {output_file} passed schema validation")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: validate-opencode-risk-output.py <output-file>", file=sys.stderr)
        sys.exit(2)
    sys.exit(validate(sys.argv[1]))
