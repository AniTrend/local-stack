from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "infra" / "pulumi" / "shared" / "environment-intent.schema.json"


def valid_intent() -> dict[str, object]:
    return {
        "schema_version": "anitrend.platform.environment-intent.v1",
        "environment": "production",
        "provider": "hcloud",
        "project_ref": "anitrend-prod",
        "region": "nbg1",
        "server_type": "cx23",
        "architecture": "amd64",
        "os_image": "ubuntu-24.04",
        "network_cidrs": [
            {"name": "private", "cidr": "10.42.0.0/16", "subnet_cidr": "10.42.1.0/24", "purpose": "applications"}
        ],
        "volumes": [
            {
                "id_ref": "postgres-data",
                "size_gb": 100,
                "mount_path": "/var/lib/postgresql",
                "data_classification": "restricted",
                "protected": True,
            }
        ],
        "ssh_key_refs": ["anitrend-ops"],
        "bootstrap_user": "ansible",
        "ssh_source_cidrs": ["198.51.100.10/32"],
        "public_routes": [
            {
                "hostname": "api.example.invalid",
                "service_ref": "api",
                "port": 443,
                "protocol": "https",
                "source_cidrs": ["0.0.0.0/0", "::/0"],
            }
        ],
        "private_routes": [],
        "dns_provider_ref": None,
        "dns_zone_ref": None,
        "dns_records": [],
        "private_hostnames": ["dokploy.example.invalid"],
        "certificate_strategy_ref": "cert-policy:private",
        "tailnet_grants_ref": "tailnet:admin",
        "state_backend_ref": "pulumi-cloud:anitrend/platform-production",
        "backup_destination_ref": "backup:offsite-production",
        "backup_retention_days": 7,
        "credential_refs": ["hcloud-token:production"],
        "recovery_credential_refs": ["recovery:operations"],
        "rpo_hours": 24,
        "rto_minutes": 60,
        "maintenance_window_ref": "maintenance:weekly",
        "maximum_downtime_minutes": 120,
        "rollback_thresholds": ["error-rate", "restore-failure"],
        "writer_job_map_ref": "writers:production",
        "source_host_identity_ref": "host:legacy-01",
        "target_host_identity_ref": "ssh-host-ca:anitrend-production",
        "deployment_owner_map_ref": "owners:production",
        "deployment_freeze_steps_ref": "freeze:production",
        "service_dependency_map_ref": "dependencies:production",
        "database_runtime_facts_ref": "database:runtime-facts",
        "gateway_policy_export_ref": "apisix:policy-export",
        "external_provider_map_ref": "providers:production",
        "backup_restore_matrix_ref": "restore:matrix",
        "budget_limit_eur": 500,
        "estimated_monthly_cost_eur": 400,
        "cost_estimate_ref": "approval:cost-estimate:production-01",
        "ttl_hours": None,
        "allowed_docker_contexts": ["default"],
        "safety_policy": {
            "protect_resources": True,
            "allow_destroy": False,
            "require_environment_approval": True,
            "deny_pull_request_mutations": True,
        },
    }


def test_environment_intent_schema_accepts_complete_nonsecret_production_contract():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(valid_intent(), schema)


def test_environment_intent_schema_rejects_wrong_provider_and_unsafe_reference_forms():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    invalid_provider = valid_intent()
    invalid_provider["provider"] = "docker"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid_provider, schema)

    missing_budget_ref = valid_intent()
    del missing_budget_ref["cost_estimate_ref"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(missing_budget_ref, schema)

    non_cloud_backend = valid_intent()
    non_cloud_backend["state_backend_ref"] = "file:///tmp/platform-state"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(non_cloud_backend, schema)

    raw_ssh_key = valid_intent()
    raw_ssh_key["ssh_key_refs"] = ["ssh-ed25519 AAAA test-only"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(raw_ssh_key, schema)

    fractional_volume_size = valid_intent()
    volumes = fractional_volume_size["volumes"]
    assert isinstance(volumes, list)
    volume = volumes[0]
    assert isinstance(volume, dict)
    volume["size_gb"] = 1.5
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(fractional_volume_size, schema)
