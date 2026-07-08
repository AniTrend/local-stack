#!/usr/bin/env python3
"""Extract a valid risk classification JSON from OpenCode raw output.

Reads raw model output, strips ANSI, locates the first valid JSON object
with the correct schema_version, and writes it to the output file. If no
valid object is found, writes a neutral fallback. Always exits 0 so the
workflow never fails on extraction alone — validation handles rejection.

Exit codes:
  0 — Successfully extracted JSON OR wrote neutral fallback.
       Extraction failure is NOT distinguishable by exit code. The downstream
       validator (validate-opencode-risk-output.py) is expected to accept the
       neutral fallback and enforce correctness via schema + safety rules.
  2 — Usage error (wrong number of arguments).
"""

import json
import re
import sys


EXPECTED_SCHEMA = "local-stack.dependabot-risk.v1"

NEUTRAL_FALLBACK = {
    "schema_version": EXPECTED_SCHEMA,
    "decision": "neutral",
    "risk": "unknown",
    "automerge_allowed": False,
    "dependency_ecosystem": "unknown",
    "update_type": "unknown",
    "changed_images": [],
    "changed_files": [],
    "summary": (
        "OpenCode did not produce a valid risk classification. "
        "Manual review required."
    ),
    "breaking_change_assessment": (
        "Not assessed because the OpenCode output was missing or invalid."
    ),
    "runtime_impact": "Unknown.",
    "required_checks": [],
    "manual_follow_up": [
        "Review the dependency PR manually.",
        "Inspect the workflow logs for OpenCode output or parsing failure.",
    ],
    "sources_checked": [
        "PR diff",
        "PR metadata",
    ],
    "confidence": "low",
}


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (color codes, cursor movements)."""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def extract_json_objects(text: str) -> list[dict]:
    """Find all balanced JSON objects in text that contain schema_version."""
    candidates = []
    depth = 0
    start = None

    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                fragment = text[start : i + 1]
                try:
                    obj = json.loads(fragment)
                    if isinstance(obj, dict) and "schema_version" in obj:
                        candidates.append(obj)
                except (json.JSONDecodeError, ValueError):
                    pass
                start = None

    return candidates


def extract(input_path: str, output_path: str) -> None:
    try:
        with open(input_path) as f:
            raw = f.read()
    except FileNotFoundError:
        print(f"WARNING: {input_path} not found, writing neutral fallback", file=sys.stderr)
        write_fallback(output_path, "Input file not found")
        return

    cleaned = strip_ansi(raw)
    candidates = extract_json_objects(cleaned)

    if not candidates:
        print("WARNING: no JSON objects with schema_version found, writing neutral fallback", file=sys.stderr)
        write_fallback(output_path, "No valid JSON object in OpenCode output")
        return

    # Prefer objects matching the expected schema version
    matched = [c for c in candidates if c.get("schema_version") == EXPECTED_SCHEMA]

    if matched:
        chosen = matched[0]
        if len(matched) > 1:
            print(f"INFO: found {len(matched)} objects with expected schema, using first", file=sys.stderr)
    else:
        print(
            f"WARNING: found {len(candidates)} object(s) but none with "
            f"schema_version={EXPECTED_SCHEMA!r}, writing neutral fallback",
            file=sys.stderr,
        )
        write_fallback(output_path, "No object with expected schema_version")
        return

    with open(output_path, "w") as f:
        json.dump(chosen, f, indent=2)
        f.write("\n")

    print(f"Extracted risk JSON to {output_path}", file=sys.stderr)


def write_fallback(output_path: str, reason: str) -> None:
    fallback = dict(NEUTRAL_FALLBACK)
    fallback["summary"] = f"{NEUTRAL_FALLBACK['summary']} Reason: {reason}."

    with open(output_path, "w") as f:
        json.dump(fallback, f, indent=2)
        f.write("\n")

    print(f"Neutral fallback written to {output_path}: {reason}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: extract-risk-json.py <raw-output> <result-json>", file=sys.stderr)
        sys.exit(2)
    extract(sys.argv[1], sys.argv[2])
