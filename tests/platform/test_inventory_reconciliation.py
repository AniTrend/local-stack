from __future__ import annotations

import copy
import json

import pytest

from tools.platform import inventory


@pytest.fixture
def reconciled():
    # Only the fields consumed by the post-schema semantic validator are included.
    # This fixture exercises semantic reconciliation after structural validation.
    inputs = {
        name: {"status": "confirmed", "value": "evidence-backed-value", "evidence_ref": "restricted://decision"}
        for name in (
            "provider", "hetzner_project_ref", "source_host_identity_ref", "region", "architecture",
            "server_type", "os_image", "writer_job_map_ref", "maintenance_window_ref", "rollback_thresholds",
        )
    }
    inputs["provider"]["value"] = "hcloud"
    inputs["allowed_docker_contexts"] = {
        "status": "confirmed", "value": ["approved-production"], "evidence_ref": "restricted://context",
    }
    inputs["rollback_thresholds"]["value"] = ["approved error/latency limits"]
    inputs["safety_policy"] = {
        "status": "confirmed", "evidence_ref": "restricted://safety",
        "value": {"protect_resources": True, "allow_destroy": False,
                  "require_environment_approval": True, "deny_pull_request_mutations": True},
    }
    service_id = "postgres/docker-compose.yaml:postgres"
    matched = {"id": "a" * 64, "name": "postgres", "compose_project": "database", "compose_service": "postgres",
               "source_service_id": service_id}
    unmatched = {"id": "b" * 64, "name": "external-app", "compose_project": "external", "compose_service": "app",
                 "source_service_id": None}
    return {
        "environment": "production", "collector_commit": "c" * 40, "collector_worktree_clean": True,
        "collection_issues": [], "reconciliation": {"decision": "pass", "blocked_reasons": []},
        "environment_contract": {"inputs": inputs},
        "docker": {"context_name": "approved-production", "volume_inventory_status": "collected",
                   "resource_usage_status": "collected", "running_count": 2, "containers": [matched, unmatched]},
        "repository_services": [{
            "id": service_id, "runtime_container_ids": [matched["id"]],
            "disposition": "migrate", "data_classification": "durable", "runtime_match_status": "matched",
            "current_deployment_owner": "legacy-operations", "target_deployment_owner": "dokploy-operations",
            "ingress_class": "internal", "health_contract": {"status": "confirmed", "evidence_ref": "restricted://health"},
            "database_runtime": {"status": "confirmed", "server_version": "18.4", "topology_ref": "restricted://db",
                                 "data_paths": ["/var/lib/postgresql/18/docker"]},
            "writer_job_map_ref": "restricted://writers", "external_provider_map_ref": "restricted://providers",
            "backup_restore_method_ref": "restricted://restore", "evidence_refs": ["restricted://observations"],
        }],
        "unmatched_containers": [{
            "container_id": unmatched["id"], "name": unmatched["name"], "compose_project": "external", "compose_service": "app",
            "disposition": "retain", "deployment_owner": "external-operations", "evidence_ref": "restricted://owner",
        }],
    }


def test_complete_reconciliation_semantics_are_accepted(reconciled):
    assert inventory._reconciliation_validation_error(reconciled) is None


@pytest.mark.parametrize("name", ["hetzner_project_ref", "source_host_identity_ref", "architecture", "writer_job_map_ref", "maintenance_window_ref", "rollback_thresholds"])
def test_required_production_inputs_cannot_be_waived(reconciled, name):
    reconciled["environment_contract"]["inputs"][name] = {
        "status": "not_applicable", "value": None, "evidence_ref": "restricted://attempted-waiver",
    }
    assert inventory._reconciliation_validation_error(reconciled) is not None


def test_unapproved_observed_context_cannot_pass(reconciled):
    reconciled["docker"]["context_name"] = "unapproved-source"
    assert inventory._reconciliation_validation_error(reconciled) is not None


@pytest.mark.parametrize("change", ["missing", "duplicate", "inconsistent"])
def test_every_unmatched_container_requires_exact_reconciliation(reconciled, change):
    if change == "missing":
        reconciled["unmatched_containers"] = []
    elif change == "duplicate":
        reconciled["unmatched_containers"].append(copy.deepcopy(reconciled["unmatched_containers"][0]))
    else:
        reconciled["unmatched_containers"][0]["compose_project"] = "another-project"
    assert inventory._reconciliation_validation_error(reconciled) is not None


@pytest.mark.parametrize("location,owner", [("current", ""), ("target", "  "), ("unmatched", "unresolved"), ("unmatched", "pending")])
def test_deployment_owners_must_be_resolved(reconciled, location, owner):
    if location == "unmatched":
        reconciled["unmatched_containers"][0]["deployment_owner"] = owner
    else:
        reconciled["repository_services"][0][location + "_deployment_owner"] = owner
    assert inventory._reconciliation_validation_error(reconciled) is not None


@pytest.mark.parametrize("field,value", [("server_version", None), ("topology_ref", None), ("data_paths", [])])
def test_confirmed_database_requires_observed_facts(reconciled, field, value):
    reconciled["repository_services"][0]["database_runtime"][field] = value
    assert inventory._reconciliation_validation_error(reconciled) is not None


def test_confirmed_health_requires_evidence(reconciled):
    reconciled["repository_services"][0]["health_contract"]["evidence_ref"] = None
    assert inventory._reconciliation_validation_error(reconciled) is not None


def test_forged_service_match_cannot_remove_an_unowned_container(reconciled):
    reconciled["docker"]["containers"][1]["source_service_id"] = "nonexistent-service"
    reconciled["unmatched_containers"] = []
    assert inventory._reconciliation_validation_error(reconciled) is not None


def test_service_runtime_mapping_must_match_observed_containers(reconciled):
    reconciled["repository_services"][0]["runtime_container_ids"] = []
    assert inventory._reconciliation_validation_error(reconciled) is not None


def test_real_systemd_microsecond_timestamps_are_preserved(monkeypatch):
    monkeypatch.setattr(inventory.sys, "platform", "linux")
    monkeypatch.setattr(inventory.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(inventory, "_run_command", lambda *args, **kwargs: json.dumps([
        {"unit": "backup.timer", "activates": "backup.service", "next": 1700000000123456, "last": 0},
    ]))
    timers = inventory._collect_timers("local_unix")
    assert timers["units"][0]["next"] == "2023-11-14T22:13:20.123456Z"
    assert timers["units"][0]["last"] is None


def test_unix_socket_timer_observations_are_not_engine_host_proof(monkeypatch):
    monkeypatch.setattr(inventory.sys, "platform", "linux")
    monkeypatch.setattr(inventory.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(inventory, "_run_command", lambda *args, **kwargs: "[]")
    timers = inventory._collect_timers("local_unix")
    assert timers["host_scope"] == "collector"


def test_real_docker_string_reference_counts_are_preserved(monkeypatch):
    monkeypatch.setattr(inventory, "_run_docker", lambda *args, **kwargs: json.dumps({"Volumes": [
        {"Name": "unused", "Links": "0", "Size": "0B"},
        {"Name": "used", "Links": "1", "Size": "1kB"},
        {"Name": "unknown", "Links": "N/A", "Size": "N/A"},
    ]}))
    volumes, _, _ = inventory._collect_volume_rows("approved-production")
    counts = {volume["name"]: volume["links"] for volume in volumes}
    assert counts == {"unused": 0, "used": 1, "unknown": None}
