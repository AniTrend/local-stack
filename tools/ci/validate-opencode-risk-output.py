#!/usr/bin/env python3
"""Validate OpenCode risk review output against the schema and safety rules.

Layer 1: Structural validation using jsonschema against the JSON Schema file.
Layer 2: Cross-field safety rules that JSON Schema draft-07 cannot express.

All rules are strict — any violation fails the validator.

The approve guards (validate_approve_guards) must stay in sync with the APPROVE
section of .github/prompts/renovate-dependency-risk-review.md. When the prompt
policy changes, update the constants at the top of this file.

Known unenforceable guard:
  "No stateful service migration risk is detected" — this is a semantic
  assessment that cannot be validated programmatically from the JSON output.
  The prompt is the enforcement mechanism for this rule.
"""

import json
import sys
from pathlib import Path

from jsonschema import ValidationError, validate as jsonschema_validate


SCHEMA_FILE = ".github/opencode/risk-output.schema.json"

# --- Approve guard constants (keep in sync with prompt policy) ----------------

APPROVE_REQUIRED_RISK = "low"
APPROVE_ALLOWED_UPDATE_TYPES = frozenset({"semver-patch", "semver-minor", "digest"})
APPROVE_ALLOWED_CONFIDENCE = frozenset({"high", "medium"})

SENSITIVE_FILE_PATTERNS = (
    ".env.enc",
    ".sops.yaml",
    "stackctl.sh",
    "tools/render_compose.py",
    "tools/generate_stacks.py",
)

WORKFLOW_FILE_GLOB = ".github/workflows/"
STACK_FILE_GLOB = "stacks/"


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


# --- Layer 1: Structural validation via jsonschema ----------------------------

def validate_structure(instance: dict, schema: dict) -> list[str]:
    try:
        jsonschema_validate(instance=instance, schema=schema)
        return []
    except ValidationError as e:
        return [e.message]


# --- Layer 2: Cross-field safety rules ----------------------------------------

def validate_automerge_rules(data: dict) -> list[str]:
    """Rules: automerge=true needs decision=approve; semver-major blocks automerge."""
    errors = []

    decision = data.get("decision")
    automerge_allowed = data.get("automerge_allowed")
    update_type = data.get("update_type")

    if automerge_allowed is True and decision != "approve":
        errors.append(
            f"automerge_allowed=true requires decision=approve "
            f"(got decision={decision!r})"
        )

    if update_type == "semver-major" and automerge_allowed is True:
        errors.append("update_type=semver-major cannot allow automerge")

    return errors


def validate_approve_guards(data: dict) -> list[str]:
    """Deterministic safety rules that must pass for decision=approve.

    These guards prevent unsafe model outputs from reaching the apply-decision
    script. Keep in sync with the APPROVE section of the prompt template.
    """
    if data.get("decision") != "approve":
        return []  # Guards only apply to approve decisions

    errors = []
    risk = data.get("risk")
    update_type = data.get("update_type")
    ecosystem = data.get("dependency_ecosystem")
    confidence = data.get("confidence")
    changed_files = data.get("changed_files", [])

    # --- Risk level -----------------------------------------------------------
    if risk != APPROVE_REQUIRED_RISK:
        permitted = {APPROVE_REQUIRED_RISK}
        errors.append(
            f"decision=approve requires risk={APPROVE_REQUIRED_RISK!r} "
            f"(got risk={risk!r})"
        )

    # --- Update type ----------------------------------------------------------
    if update_type not in APPROVE_ALLOWED_UPDATE_TYPES:
        errors.append(
            f"decision=approve requires update_type in "
            f"{sorted(APPROVE_ALLOWED_UPDATE_TYPES)} (got {update_type!r})"
        )

    # --- GitHub Actions major update ------------------------------------------
    if ecosystem == "github-actions" and update_type == "semver-major":
        errors.append(
            "decision=approve rejected: github-actions semver-major update "
            "must be neutral or changes_requested"
        )

    # --- Workflow file changes ------------------------------------------------
    workflow_files = [
        f for f in changed_files if f.startswith(WORKFLOW_FILE_GLOB)
    ]
    if workflow_files:
        errors.append(
            f"decision=approve rejected: changed workflow files "
            f"{workflow_files}"
        )

    # --- Sensitive file changes -----------------------------------------------
    sensitive = [
        f for f in changed_files
        if any(f == p or f.endswith("/" + p) for p in SENSITIVE_FILE_PATTERNS)
    ]
    if sensitive:
        errors.append(
            f"decision=approve rejected: changed sensitive files "
            f"{sensitive}"
        )

    # --- Stack drift (stacks/*.yml without matching source changes) -----------
    stack_files = [f for f in changed_files if f.startswith(STACK_FILE_GLOB)]
    source_files = [
        f for f in changed_files
        if not f.startswith(STACK_FILE_GLOB)
        and not f.startswith(WORKFLOW_FILE_GLOB)
    ]
    if stack_files and not source_files:
        errors.append(
            "decision=approve rejected: generated stacks/*.yml changed "
            "without matching source Compose/fragment changes"
        )

    # --- Confidence -----------------------------------------------------------
    if confidence is not None and confidence not in APPROVE_ALLOWED_CONFIDENCE:
        errors.append(
            f"decision=approve requires confidence in "
            f"{sorted(APPROVE_ALLOWED_CONFIDENCE)} (got {confidence!r})"
        )

    return errors


# --- Orchestrator -------------------------------------------------------------

def validate(output_file: str) -> int:
    schema = load_json(SCHEMA_FILE)
    data = load_json(output_file)

    errors = []
    errors.extend(validate_structure(data, schema))
    errors.extend(validate_automerge_rules(data))
    errors.extend(validate_approve_guards(data))

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
