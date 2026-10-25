from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "infra" / "pulumi" / "shared" / "platform-lab.schema.json"
RUN_ID = "20261025T000000Z-a1b2c3d4"
IMAGE_DIGEST = "sha256:" + "a" * 64
IMAGE_REF = "lscr.io/linuxserver/openssh-server@" + IMAGE_DIGEST


def _validator(definition: str) -> jsonschema.Draft202012Validator:
    assert SCHEMA_PATH.is_file(), "the versioned platform lab artifact schema must exist"
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/" + definition})


def _lab_outputs() -> dict[str, object]:
    return {
        "schema_version": "anitrend.platform.lab-output.v1",
        "environment": "lab",
        "run_id": RUN_ID,
        "network_name": f"anitrend-platform-lab-{RUN_ID}-network",
        "volume_name": f"anitrend-platform-lab-{RUN_ID}-config",
        "container_name": f"anitrend-platform-lab-{RUN_ID}-ssh",
        "ssh_host_port": 43210,
        "image_ref": IMAGE_REF,
        "image_digest": IMAGE_DIGEST,
        "image_id": "sha256:" + "b" * 64,
        "image_platform": "linux/amd64",
        "host_os": "Linux",
        "host_architecture": "x86_64",
        "docker_os": "Docker Engine",
        "docker_architecture": "x86_64",
        "execution_mode": "native",
    }


def _tool_versions() -> dict[str, str]:
    return {
        "node": "24.22.1",
        "npm": "11.19.1",
        "pulumi": "3.272.0",
        "python": "3.14.9",
        "ansible-core": "2.21.5",
        "molecule": "26.10.0",
        "molecule-plugins": "26.10.12",
        "jsonschema": "4.25.1",
    }


def _lab_manifest() -> dict[str, object]:
    facts = {
        "docker_context": "fixture-local",
        "docker_endpoint_kind": "local_unix",
        "host_os": "Linux",
        "host_architecture": "x86_64",
        "docker_os": "Docker Engine",
        "docker_architecture": "x86_64",
        "image_ref": IMAGE_REF,
        "image_digest": IMAGE_DIGEST,
        "image_platform": "linux/amd64",
        "execution_mode": "native",
        "ssh_container_port": 2222,
        "ssh_host_port": 43210,
        "tool_versions": _tool_versions(),
        "report": ["platform-doctor=pass"],
    }
    return {
        "schema_version": "anitrend.platform.lab-run.v1",
        "environment": "lab",
        "run_id": RUN_ID,
        "stack_name": "platform-lab-" + RUN_ID,
        "created_at": "2026-10-25T12:00:00Z",
        "source": {"commit": "a" * 40, "worktree_clean": False},
        "environment_facts": facts,
        "image_ref": IMAGE_REF,
        "image_digest": IMAGE_DIGEST,
        "image_platform": "linux/amd64",
        "execution_mode": "native",
        "tool_versions": _tool_versions(),
        "pulumi_stack_created": True,
        "ssh_host_port": 43210,
        "revision": 1,
        "pulumi_preview": "pass",
        "pulumi_up": "pass",
        "pulumi_noop_up": "pending",
        "ssh_validation": "pending",
        "controlled_update": "pending",
        "cleanup_status": "pending",
        "outputs": _lab_outputs(),
    }


def test_lab_output_schema_rejects_invalid_digest_and_unreserved_port():
    validator = _validator("labOutput")
    valid = _lab_outputs()
    validator.validate(valid)

    invalid_port = dict(valid)
    invalid_port["ssh_host_port"] = 0
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(invalid_port)

    invalid_digest = dict(valid)
    invalid_digest["image_digest"] = "not-a-digest"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(invalid_digest)


def test_run_manifest_schema_rejects_local_endpoints_and_secrets():
    validator = _validator("labRun")
    valid = _lab_manifest()
    validator.validate(valid)

    leaked_endpoint = _lab_manifest()
    leaked_endpoint["environment_facts"]["docker_host"] = "unix:///var/run/docker.sock"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(leaked_endpoint)

    leaked_secret = _lab_manifest()
    leaked_secret["private_key"] = "fixture-secret"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(leaked_secret)
