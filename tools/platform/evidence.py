#!/usr/bin/env python3
"""Validate completed local lab or VM host evidence, without asserting a platform gate."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = REPO_ROOT / "infra" / "pulumi" / "shared"
MAX_MANIFEST_BYTES = 1024 * 1024
SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:password|passphrase|secret|private_key|auth_key|authkey|api_key|api_token|access_token|token)(?:$|_)",
    re.IGNORECASE,
)
SENSITIVE_TEXT = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----|AGE-SECRET-KEY-|"
    r"tskey-(?:auth|api|client)-|gh[pousr]_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+|"
    r"https?://[^/\s:@]+:[^/\s@]+@"
)
LAB_ASSERTIONS = (
    "pulumi_preview", "pulumi_up", "pulumi_noop_up", "ssh_validation", "controlled_update", "cleanup_status",
)


class EvidenceError(Exception):
    """An incomplete, mismatched or unsafe evidence record with a non-secret message."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("manifest contains duplicate JSON keys")
        result[key] = value
    return result


def _read_json(path: Path):
    try:
        with path.open("rb") as source:
            content = source.read(MAX_MANIFEST_BYTES + 1)
        if len(content) > MAX_MANIFEST_BYTES:
            raise EvidenceError("manifest exceeds the supported size")
        return json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise EvidenceError("cannot read a valid JSON evidence document") from error


def _reject_sensitive_content(value) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SENSITIVE_KEY.search(key) or SENSITIVE_TEXT.search(key):
                raise EvidenceError("manifest contains potentially sensitive content; do not publish it")
            _reject_sensitive_content(child)
    elif isinstance(value, list):
        for child in value:
            _reject_sensitive_content(child)
    elif isinstance(value, str) and SENSITIVE_TEXT.search(value):
        raise EvidenceError("manifest contains potentially sensitive content; do not publish it")


def _validate_schema(value: dict, filename: str, definition: str | None = None) -> None:
    schema = _read_json(SCHEMA_ROOT / filename)
    if definition is not None:
        schema = {"$defs": schema["$defs"], "$ref": "#/$defs/" + definition}
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        if not validator.is_valid(value):
            raise EvidenceError("manifest does not match its versioned evidence schema")
    except jsonschema.SchemaError as error:
        raise EvidenceError("the repository evidence schema is invalid") from error


def validate_evidence(value: object, environment: str, tier: str, commit: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise EvidenceError("an exact full candidate commit is required")
    if not isinstance(value, dict):
        raise EvidenceError("manifest must be a JSON object")
    _reject_sensitive_content(value)
    if value.get("environment") != environment:
        raise EvidenceError("evidence environment does not match the requested target")

    schema_version = value.get("schema_version")
    if schema_version == "anitrend.platform.lab-run.v1":
        if tier != "docker":
            raise EvidenceError("Docker lab evidence cannot satisfy a different tier")
        _validate_schema(value, "platform-lab.schema.json", "labRun")
        source = value["source"]
        if source["commit"] != commit:
            raise EvidenceError("evidence commit does not match the candidate")
        if not isinstance(source.get("worktree_sha256"), str):
            raise EvidenceError("lab source fingerprint is missing; older records require a new validation run")
        if any(value[name] != "pass" for name in LAB_ASSERTIONS):
            raise EvidenceError("lab lifecycle evidence is incomplete or not passing, including cleanup")
        if value.get("test_stage") != "complete" or value.get("pending_revision") is not None:
            raise EvidenceError("lab update verification did not finish")
        if value["revision"] != 2:
            raise EvidenceError("lab controlled update did not reach the v1 completed revision")
        if value.get("last_operation") != "down" or value["pulumi_stack_created"]:
            raise EvidenceError("lab cleanup has not completed")
        outputs = value["outputs"]
        if not isinstance(outputs, dict) or not isinstance(value.get("resource_evidence"), dict):
            raise EvidenceError("completed lab resource evidence is missing")
        if value["resource_evidence"]["image_id"] != outputs["image_id"]:
            raise EvidenceError("lab inspected image identity does not match the deployed resource")
        inspected_architecture = value["resource_evidence"]["architecture"]
        inspected_architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(
            inspected_architecture, inspected_architecture
        )
        if inspected_architecture != value["image_platform"].split("/")[-1]:
            raise EvidenceError("lab inspected architecture does not match the declared image platform")
        run_id = value["run_id"]
        if value["stack_name"] != "platform-lab-" + run_id or outputs["run_id"] != run_id:
            raise EvidenceError("lab resource identities do not match the evidence run")
        for suffix, key in (("network", "network_name"), ("config", "volume_name"), ("ssh", "container_name")):
            if outputs[key] != f"anitrend-platform-lab-{run_id}-{suffix}":
                raise EvidenceError("lab resource identities do not match the evidence run")
        facts = value["environment_facts"]
        for key in ("image_ref", "image_digest", "image_platform", "execution_mode", "ssh_host_port"):
            if value[key] != outputs[key] or value[key] != facts[key]:
                raise EvidenceError("lab image or runtime identity is inconsistent")
        if value["tool_versions"] != facts["tool_versions"]:
            raise EvidenceError("lab tool version evidence is inconsistent")
        if not value["image_ref"].endswith("@" + value["image_digest"]):
            raise EvidenceError("lab image reference does not match its digest")
        return "docker-lab-lifecycle"

    if schema_version == "anitrend.platform.host-verify.v1":
        if tier != "vm":
            raise EvidenceError("host evidence cannot satisfy a different tier")
        _validate_schema(value, "host-verify-evidence.schema.json")
        if value["tested_commit"] != commit:
            raise EvidenceError("evidence commit does not match the candidate")
        if value["result"] != "pass":
            raise EvidenceError("host verification evidence is not passing")
        return "host-baseline"

    raise EvidenceError("unsupported evidence schema; later platform gates are not implemented here")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--environment", choices=("lab", "rehearsal", "production"), required=True)
    parser.add_argument("--tier", choices=("docker", "vm"), required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    try:
        scope = validate_evidence(_read_json(args.manifest), args.environment, args.tier, args.commit)
    except (EvidenceError, RecursionError) as error:
        message = str(error) if isinstance(error, EvidenceError) else "manifest nesting exceeds the supported depth"
        print("evidence-validation=fail: " + message, file=sys.stderr)
        return 2
    print(f"evidence-validation=pass scope={scope} environment={args.environment} tier={args.tier}")
    print("This checks recorded evidence only, not authenticity, arbitrary secrets, current host state, or G0-G6 acceptance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
