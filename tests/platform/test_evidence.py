from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "tools/platform/evidence.py"
COMMIT = "a" * 40
HOST_STEPS = (
    "validate_inventory_and_trust",
    "bootstrap_automation_account",
    "automation_ssh_reconnect_before_firewall",
    "storage_device_identity_safety_checks",
    "fresh_host_convergence",
    "automation_ssh_reconnect_after_firewall",
    "storage_safety_and_create_only_checks",
    "systemd_firewall_tailscale_mount_reboot_verification",
    "second_host_convergence",
)


@pytest.fixture
def host_manifest():
    return {
        "schema_version": "anitrend.platform.host-verify.v1",
        "run_id": "20261111t000000z-abcdef12",
        "environment": "lab",
        "tier": "vm",
        "result": "pass",
        "tested_commit": COMMIT,
        "inventory": {
            "schema_version": "anitrend.platform.pulumi-inventory.lab-v1",
            "provider": "external-vm",
            "stack_identity": "lab-vm-fixture",
            "host_identity_ref": "console-verified:fixture",
            "architecture": "amd64",
            "os_image": "ubuntu-24.04",
            "image_ref": "ubuntu-24.04-fixture-image",
            "native_execution": True,
            "volume_count": 1,
            "create_only_format": False,
        },
        "steps": [
            {"name": name, "command": "ansible-playbook <sanitized>", "exit_code": 0, "state": "pass"}
            for name in HOST_STEPS
        ],
        "cleanup_status": "pass",
        "tool_versions": {
            "ansible-core": "2.21.5",
            "molecule": "26.10.0",
            "molecule-plugins": "26.10.12",
            "python": "3.14.9",
            "tailscale": "1.104.2",
            "docker-client": "29.9.1",
            "collections": {
                "ansible.posix": "2.2.2",
                "community.docker": "5.0.0",
                "community.general": "13.5.0",
                "community.library_inventory_filtering_v1": "1.1.5",
            },
        },
    }


def run_evidence(tmp_path, value, *, environment="lab", tier="vm", commit=COMMIT):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(CLI), "--manifest", str(manifest), "--environment", environment,
         "--tier", tier, "--commit", commit],
        capture_output=True,
        text=True,
        check=False,
    )


def test_complete_host_evidence_is_scoped_to_host_baseline(tmp_path, host_manifest):
    host_manifest["steps"][-1]["changed_counts"] = [0]
    result = run_evidence(tmp_path, host_manifest)

    assert result.returncode == 0, result.stderr
    assert "scope=host-baseline" in result.stdout
    assert "gate=pass" not in result.stdout


@pytest.mark.parametrize("state", ["fail", "blocked", "skipped"])
def test_nonpassing_host_evidence_cannot_satisfy_acceptance(tmp_path, host_manifest, state):
    host_manifest["result"] = state
    host_manifest["error"] = "Operator prerequisite was not available."
    host_manifest["steps"] = []

    result = run_evidence(tmp_path, host_manifest)

    assert result.returncode != 0
    assert "evidence-validation=pass" not in result.stdout


@pytest.mark.parametrize("missing_step", HOST_STEPS)
def test_missing_host_assertions_are_not_a_pass(tmp_path, host_manifest, missing_step):
    host_manifest["steps"][-1]["changed_counts"] = [0]
    host_manifest["steps"] = [step for step in host_manifest["steps"] if step["name"] != missing_step]

    result = run_evidence(tmp_path, host_manifest)

    assert result.returncode != 0


@pytest.mark.parametrize("changed_counts", [None, [], [1], [0, 2], [True]])
def test_host_idempotence_requires_observed_zero_changes(tmp_path, host_manifest, changed_counts):
    if changed_counts is not None:
        host_manifest["steps"][-1]["changed_counts"] = changed_counts

    result = run_evidence(tmp_path, host_manifest)

    assert result.returncode != 0


@pytest.mark.parametrize("override", [
    {"environment": "production"},
    {"tier": "docker"},
    {"commit": "b" * 40},
    {"commit": "unknown"},
])
def test_evidence_cannot_be_reused_for_another_target(tmp_path, host_manifest, override):
    host_manifest["steps"][-1]["changed_counts"] = [0]

    result = run_evidence(tmp_path, host_manifest, **override)

    assert result.returncode != 0


@pytest.mark.parametrize("field,value", [("exit_code", 1), ("state", "skipped")])
def test_success_label_cannot_hide_a_nonpassing_host_step(tmp_path, host_manifest, field, value):
    host_manifest["steps"][-1]["changed_counts"] = [0]
    host_manifest["steps"][2][field] = value

    result = run_evidence(tmp_path, host_manifest)

    assert result.returncode != 0


def test_duplicate_host_step_cannot_replace_a_missing_check(tmp_path, host_manifest):
    host_manifest["steps"][-1] = copy.deepcopy(host_manifest["steps"][-2])

    result = run_evidence(tmp_path, host_manifest)

    assert result.returncode != 0


@pytest.mark.parametrize("secret", [
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "AGE-SECRET-KEY-1DUMMYCANARY",
    "tskey-auth-dummy-canary",
    "ghp_0123456789dummycanary",
])
def test_secret_patterns_are_rejected_without_echoing_them(tmp_path, host_manifest, secret):
    host_manifest["steps"][-1]["changed_counts"] = [0]
    host_manifest["steps"][0]["command"] = secret

    result = run_evidence(tmp_path, host_manifest)

    assert result.returncode != 0
    assert "sensitive" in result.stderr
    assert secret not in result.stderr + result.stdout


def test_unknown_secret_fields_are_not_echoed(tmp_path, host_manifest):
    host_manifest["api_token"] = "dummy-secret-that-must-not-appear"

    result = run_evidence(tmp_path, host_manifest)

    assert result.returncode != 0
    assert host_manifest["api_token"] not in result.stderr + result.stdout


def test_duplicate_json_keys_are_rejected(tmp_path, host_manifest):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"environment":"production","environment":"lab"}', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(CLI), "--manifest", str(manifest), "--environment", "lab",
         "--tier", "vm", "--commit", COMMIT],
        capture_output=True, text=True, check=False,
    )

    assert result.returncode != 0
    assert "duplicate" in result.stderr


@pytest.fixture
def lab_manifest():
    run_id = "20261111T000000Z-abcdef12"
    digest = "sha256:" + "a" * 64
    image_ref = "lscr.io/linuxserver/openssh-server@" + digest
    versions = {
        "node": "24.22.1", "npm": "11.19.1", "pulumi": "3.272.0", "python": "3.14.9",
        "ansible-core": "2.21.5", "molecule": "26.10.0", "molecule-plugins": "26.10.12",
        "jsonschema": "4.25.1",
    }
    runtime = {
        "image_ref": image_ref, "image_digest": digest, "image_platform": "linux/amd64",
        "execution_mode": "native", "ssh_host_port": 43210,
    }
    outputs = {
        **runtime, "schema_version": "anitrend.platform.lab-output.v1", "environment": "lab",
        "run_id": run_id, "network_name": f"anitrend-platform-lab-{run_id}-network",
        "volume_name": f"anitrend-platform-lab-{run_id}-config",
        "container_name": f"anitrend-platform-lab-{run_id}-ssh", "image_id": "sha256:" + "b" * 64,
        "host_os": "Linux", "host_architecture": "x86_64",
        "docker_os": "Linux", "docker_architecture": "x86_64",
    }
    return {
        **runtime, "schema_version": "anitrend.platform.lab-run.v1", "environment": "lab",
        "run_id": run_id, "stack_name": "platform-lab-" + run_id,
        "created_at": "2026-11-11T00:00:00Z", "source": {
            "commit": COMMIT, "worktree_clean": True, "worktree_sha256": "b" * 64,
        },
        "environment_facts": {
            **runtime, "docker_context": "fixture-local", "docker_endpoint_kind": "local_unix",
            "host_os": "Linux", "host_architecture": "x86_64",
            "docker_os": "Linux", "docker_architecture": "x86_64",
            "ssh_container_port": 2222, "tool_versions": versions, "report": ["platform-doctor=pass"],
        },
        "tool_versions": versions, "pulumi_stack_created": False, "revision": 2,
        "pulumi_preview": "pass", "pulumi_up": "pass", "pulumi_noop_up": "pass",
        "ssh_validation": "pass", "controlled_update": "pass", "cleanup_status": "pass",
        "outputs": outputs, "last_operation": "down", "test_stage": "complete",
        "resource_evidence": {
            "container_id": "fixture-container", "image_id": "sha256:" + "b" * 64,
            "architecture": "x86_64",
        },
    }


def test_completed_lab_lifecycle_cannot_claim_vm_acceptance(tmp_path, lab_manifest):
    result = run_evidence(tmp_path, lab_manifest, tier="docker")
    assert result.returncode == 0, result.stderr
    assert "scope=docker-lab-lifecycle" in result.stdout

    rejected = run_evidence(tmp_path, lab_manifest, tier="vm")
    assert rejected.returncode != 0


@pytest.mark.parametrize("field,value", [
    ("cleanup_status", "pending"), ("pulumi_noop_up", "failed"),
    ("test_stage", "controlled-update"), ("pending_revision", 3),
    ("outputs", None),
])
def test_incomplete_lab_work_cannot_be_presented_as_completed(tmp_path, lab_manifest, field, value):
    lab_manifest[field] = value
    result = run_evidence(tmp_path, lab_manifest, tier="docker")
    assert result.returncode != 0


def test_lab_output_from_a_different_run_is_rejected(tmp_path, lab_manifest):
    lab_manifest["outputs"]["run_id"] = "20261112T000000Z-abcdef12"
    result = run_evidence(tmp_path, lab_manifest, tier="docker")
    assert result.returncode != 0


def test_lab_resource_inspection_must_match_the_deployed_image(tmp_path, lab_manifest):
    lab_manifest["resource_evidence"]["image_id"] = "sha256:" + "c" * 64
    result = run_evidence(tmp_path, lab_manifest, tier="docker")
    assert result.returncode != 0


def test_lab_source_fingerprint_is_required_for_exact_candidate_evidence(tmp_path, lab_manifest):
    del lab_manifest["source"]["worktree_sha256"]
    result = run_evidence(tmp_path, lab_manifest, tier="docker")
    assert result.returncode != 0


def test_unrecognized_future_gate_evidence_fails_closed(tmp_path):
    result = run_evidence(
        tmp_path, {"schema_version": "anitrend.platform.production.v99", "environment": "lab"}
    )
    assert result.returncode != 0
    assert "unsupported" in result.stderr


def test_inspected_lab_architecture_must_match_the_image_platform(tmp_path, lab_manifest):
    lab_manifest["resource_evidence"]["architecture"] = "arm64"
    result = run_evidence(tmp_path, lab_manifest, tier="docker")
    assert result.returncode != 0


def test_completed_lab_evidence_requires_the_controlled_revision(tmp_path, lab_manifest):
    lab_manifest["revision"] = 1
    result = run_evidence(tmp_path, lab_manifest, tier="docker")
    assert result.returncode != 0


def test_host_storage_evidence_requires_a_declared_volume(tmp_path, host_manifest):
    host_manifest["steps"][-1]["changed_counts"] = [0]
    host_manifest["inventory"]["volume_count"] = 0
    result = run_evidence(tmp_path, host_manifest)
    assert result.returncode != 0
