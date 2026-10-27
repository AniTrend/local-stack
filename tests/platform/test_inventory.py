from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Optional, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_CLI = REPO_ROOT / "tools" / "platform" / "inventory.py"
CONTAINER_ID = "a" * 64
IMAGE_ID = "sha256:" + "b" * 64
IMAGE_DIGEST = "example/web@sha256:" + "c" * 64
SECRET_SENTINEL = "fixture-only-not-a-real-secret"


def make_toolchain(tmp_path: Path, endpoint: str) -> Tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    log_path = tmp_path / "commands.jsonl"
    docker = bin_dir / "docker"
    docker.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import json
            import os
            import sys

            args = sys.argv[1:]
            if args[:1] == ["--context"]:
                args = args[2:]
            with open(os.environ["DOCKER_TEST_LOG"], "a", encoding="utf-8") as log:
                log.write(json.dumps(args) + "\\n")

            container_id = {CONTAINER_ID!r}
            image_id = {IMAGE_ID!r}
            if args[:2] == ["context", "show"]:
                print("fixture")
            elif args[:2] == ["context", "inspect"]:
                print(json.dumps({{"Host": os.environ["DOCKER_TEST_ENDPOINT"]}}))
            elif args[:1] == ["version"]:
                print(json.dumps({{"client_version": "29.9.1", "server_version": "29.9.1"}}))
            elif args[:1] == ["info"]:
                print(json.dumps({{
                    "operating_system": "Ubuntu 24.04 LTS",
                    "architecture": "x86_64",
                    "swarm_state": "inactive",
                    "swarm_manager": False,
                    "cpu_count": 4,
                    "memory_total_bytes": 8589934592,
                }}))
            elif args[:1] == ["ps"]:
                if "--quiet" in args:
                    print(container_id)
                else:
                    print(container_id + "\\tweb\\tUp 20 minutes (unhealthy)")
            elif args[:1] == ["inspect"]:
                print(json.dumps({{
                    "id": container_id,
                    "name": "/web",
                    "image_ref": "example/web:1.2.3",
                    "image_id": image_id,
                    "state": "running",
                    "project": "sample",
                    "service": "web",
                    "ports": {{
                        "80/tcp": [{{"HostIp": "0.0.0.0", "HostPort": "18080"}}],
                        "443/tcp": [{{"HostIp": "::", "HostPort": "18443"}}],
                    }},
                    "mounts": [{{
                        "Type": "volume",
                        "Name": "fixture-data",
                        "Source": "/private/docker/volumes/fixture-data/_data",
                        "Destination": "/data",
                        "RW": True,
                    }}],
                    "networks": {{
                        "sample_default": {{
                            "Aliases": ["web"],
                            "IPAddress": "10.2.0.7",
                            "GlobalIPv6Address": "2001:db8::7",
                        }}
                    }},
                    "memory_limit_bytes": 0,
                    "nano_cpus": 0,
                    "size_rw_bytes": 4096,
                    "size_rootfs_bytes": 1048576,
                }}))
            elif args[:2] == ["image", "inspect"]:
                print(json.dumps({{
                    "id": image_id,
                    "os": "linux",
                    "architecture": "amd64",
                    "repo_digests": [{IMAGE_DIGEST!r}],
                }}))
            elif args[:1] == ["stats"]:
                print(json.dumps({{
                    "Container": container_id[:12],
                    "ID": container_id[:12],
                    "Name": "web",
                    "CPUPerc": "1.25%",
                    "MemUsage": "24MiB / 1GiB",
                    "MemPerc": "2.34%",
                    "NetIO": "10kB / 20kB",
                    "BlockIO": "30kB / 40kB",
                    "PIDs": "5",
                }}))
            elif args[:2] == ["system", "df"]:
                print(json.dumps({{
                    "Volumes": [
                        {{"Name": "fixture-data", "Driver": "local", "Scope": "local", "Links": 1, "Size": "744MB", "Mountpoint": "/private/docker/root", "Labels": {{"secret": {SECRET_SENTINEL!r}}}}},
                        {{"Name": "fixture-binary", "Driver": "local", "Scope": "local", "Links": 0, "Size": "1.5GiB", "Mountpoint": "/private/docker/root2", "Labels": {{}}}},
                        {{"Name": "fixture-empty", "Driver": "local", "Scope": "local", "Links": 0, "Size": "0B", "Mountpoint": "/private/docker/root3", "Labels": {{}}}},
                    ]
                }}))
            else:
                print("unexpected Docker command", file=sys.stderr)
                sys.exit(64)
            """
        ),
        encoding="utf-8",
    )
    docker.chmod(0o755)

    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            print(json.dumps([
                {"unit": "backup.timer", "next": "2026-10-26 02:00:00 UTC", "last": "2026-10-25 02:00:00 UTC", "activates": "backup.service"}
            ]))
            """
        ),
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    return bin_dir, log_path


def run_cli(
    tmp_path: Path,
    *,
    environment: Optional[str],
    endpoint: str = "unix:///var/run/docker.sock",
    repo_root: Optional[Path] = None,
    artifact_root: Optional[Path] = None,
    command: str = "collect",
    input_file: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    bin_dir, log_path = make_toolchain(tmp_path, endpoint)
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["DOCKER_TEST_ENDPOINT"] = endpoint
    env["DOCKER_TEST_LOG"] = str(log_path)
    args = [sys.executable, str(INVENTORY_CLI), command]
    if environment is not None:
        args.extend(["--environment", environment])
    if repo_root is not None:
        args.extend(["--repo-root", str(repo_root)])
    if artifact_root is not None:
        args.extend(["--artifact-root", str(artifact_root)])
    if input_file is not None:
        args.extend(["--input", str(input_file)])
    result = subprocess.run(args, text=True, capture_output=True, env=env, check=False)
    result.test_log_path = log_path
    return result


def make_compose_fixture(root: Path) -> None:
    service_dir = root / "sample"
    service_dir.mkdir(parents=True)
    (service_dir / "docker-compose.yml").write_text(
        textwrap.dedent(
            """\
            services:
              web:
                image: example/web:1.2.3
                env_file: .env
                depends_on:
                  db:
                    condition: service_healthy
                volumes:
                  - fixture-data:/data
            volumes:
              fixture-data: {}
            """
        ),
        encoding="utf-8",
    )
    (service_dir / ".env").write_text(
        "UNUSED_CANARY=" + SECRET_SENTINEL + "\n",
        encoding="utf-8",
    )


def latest_inventory(artifact_root: Path, environment: str) -> Path:
    matches = []
    for candidate in artifact_root.glob("*/inventory.json"):
        inventory = json.loads(candidate.read_text(encoding="utf-8"))
        if inventory["environment"] == environment:
            matches.append(candidate)
    assert len(matches) == 1
    return matches[0]


def test_collect_requires_an_explicit_environment_before_running_docker(tmp_path: Path):
    result = run_cli(tmp_path, environment=None)

    assert result.returncode == 2
    assert "--environment" in result.stderr
    assert not result.test_log_path.exists()


def test_inventory_normalizes_runtime_evidence_without_reading_env_or_network_secrets(tmp_path: Path):
    repo_root = tmp_path / "fixture-repository"
    repo_root.mkdir()
    make_compose_fixture(repo_root)
    artifact_root = tmp_path / "artifacts"

    result = run_cli(
        tmp_path / "commands",
        environment="legacy",
        repo_root=repo_root,
        artifact_root=artifact_root,
    )

    assert result.returncode == 0, result.stderr
    inventory_path = latest_inventory(artifact_root, "legacy")
    serialized = inventory_path.read_text(encoding="utf-8")
    inventory = json.loads(serialized)

    assert inventory["docker"]["endpoint_kind"] == "local_unix"
    assert inventory["docker"]["swarm_state"] == "inactive"
    assert inventory["docker"]["resource_usage_status"] == "collected"
    assert inventory["docker"]["containers"][0]["health"] == "unhealthy"
    assert inventory["docker"]["containers"][0]["source_service_id"] == "sample/docker-compose.yml:web"
    service_record = next(
        service for service in inventory["repository_services"]
        if service["id"] == "sample/docker-compose.yml:web"
    )
    assert service_record["source_repository"] == "AniTrend/local-stack"
    assert service_record["runtime_type"] == "docker-compose"
    assert service_record["ingress_class"] == "unresolved"
    assert service_record["configuration_refs"] == [{"kind": "env_file", "ref": ".env"}]
    assert service_record["health_contract"] == {
        "status": "unresolved",
        "source_healthcheck_declared": False,
        "runtime_health_states": ["unhealthy"],
        "evidence_ref": "docker-container:" + CONTAINER_ID,
    }
    assert service_record["database_runtime"] == {
        "status": "unresolved",
        "server_version": None,
        "topology_ref": None,
        "data_paths": [],
    }
    assert service_record["writer_job_map_ref"] is None
    assert service_record["external_provider_map_ref"] is None
    assert service_record["backup_restore_method_ref"] is None
    assert "source:sample/docker-compose.yml" in service_record["evidence_refs"]
    assert "docker-container:" + CONTAINER_ID in service_record["evidence_refs"]
    assert inventory["docker"]["containers"][0]["ports"] == [
        {
            "container_port": 80,
            "protocol": "tcp",
            "host_port": 18080,
            "host_address_scope": "wildcard",
            "address_family": "ipv4",
        },
        {
            "container_port": 443,
            "protocol": "tcp",
            "host_port": 18443,
            "host_address_scope": "wildcard",
            "address_family": "ipv6",
        },
    ]
    container = inventory["docker"]["containers"][0]
    assert container["mounts"][0]["size_bytes"] == 744_000_000
    volumes = {volume["name"]: volume for volume in inventory["docker"]["volumes"]}
    assert volumes["fixture-binary"]["size_bytes"] == 1_610_612_736
    assert volumes["fixture-empty"]["size_bytes"] == 0
    assert container["resource_usage"]["cpu_percent"] == 1.25
    assert container["resource_usage"]["memory_used_bytes"] == 24 * 1024 * 1024
    assert container["repo_digests"] == [IMAGE_DIGEST]
    assert inventory["docker"]["host_timers"]["units"][0]["unit"] == "backup.timer"
    assert inventory["reconciliation"]["decision"] == "blocked"
    assert SECRET_SENTINEL not in serialized
    assert "10.2.0.7" not in serialized
    assert "2001:db8::7" not in serialized
    assert "/private/docker/root" not in serialized

    validation = run_cli(
        tmp_path / "validation",
        environment="legacy",
        artifact_root=artifact_root,
        command="validate",
        input_file=inventory_path,
    )
    assert validation.returncode == 0, validation.stderr
    assert "schema=valid" in validation.stdout
    assert "gate=blocked" in validation.stdout


def test_lab_inventory_refuses_remote_docker_before_enumerating_containers(tmp_path: Path):
    result = run_cli(
        tmp_path,
        environment="lab",
        endpoint="ssh://ops:private@example.invalid",
        repo_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
    )

    assert result.returncode != 0
    assert "local Docker endpoint" in result.stderr
    assert "ops:private" not in result.stderr
    assert not (tmp_path / "artifacts").exists()
    commands = [json.loads(line) for line in result.test_log_path.read_text(encoding="utf-8").splitlines()]
    assert all(command[0] == "context" for command in commands)


def test_validator_rejects_unapproved_raw_container_fields_without_echoing_values(tmp_path: Path):
    repo_root = tmp_path / "fixture-repository"
    repo_root.mkdir()
    make_compose_fixture(repo_root)
    artifact_root = tmp_path / "artifacts"
    result = run_cli(
        tmp_path / "collection",
        environment="legacy",
        repo_root=repo_root,
        artifact_root=artifact_root,
    )
    assert result.returncode == 0, result.stderr
    inventory_path = latest_inventory(artifact_root, "legacy")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["docker"]["containers"][0]["environment"] = {"PRIVATE_TOKEN": SECRET_SENTINEL}
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    validation = run_cli(
        tmp_path / "validation",
        environment="legacy",
        artifact_root=artifact_root,
        command="validate",
        input_file=inventory_path,
    )

    assert validation.returncode != 0
    assert "additional properties" in validation.stderr.lower()
    assert SECRET_SENTINEL not in validation.stderr


def test_validator_rejects_pass_when_required_inventory_inputs_are_unresolved(tmp_path: Path):
    repo_root = tmp_path / "fixture-repository"
    repo_root.mkdir()
    make_compose_fixture(repo_root)
    artifact_root = tmp_path / "artifacts"
    collection = run_cli(
        tmp_path / "collection",
        environment="legacy",
        repo_root=repo_root,
        artifact_root=artifact_root,
    )
    assert collection.returncode == 0, collection.stderr
    inventory_path = latest_inventory(artifact_root, "legacy")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["reconciliation"]["decision"] = "pass"
    inventory["reconciliation"]["blocked_reasons"] = []
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    validation = run_cli(
        tmp_path / "validation",
        environment="legacy",
        artifact_root=artifact_root,
        command="validate",
        input_file=inventory_path,
    )

    assert validation.returncode != 0
    assert "cannot pass" in validation.stderr.lower()


def test_inventory_contains_a_typed_non_secret_environment_contract(tmp_path: Path):
    repo_root = tmp_path / "fixture-repository"
    repo_root.mkdir()
    make_compose_fixture(repo_root)
    artifact_root = tmp_path / "artifacts"
    result = run_cli(
        tmp_path / "collection",
        environment="legacy",
        repo_root=repo_root,
        artifact_root=artifact_root,
    )

    assert result.returncode == 0, result.stderr
    inventory = json.loads(latest_inventory(artifact_root, "legacy").read_text(encoding="utf-8"))
    contract = inventory["environment_contract"]

    assert contract["schema_version"] == "anitrend.platform.environment.v1"
    assert contract["target_environment"] == "production"
    assert set(contract["inputs"]) == {
        "provider",
        "allowed_docker_contexts",
        "safety_policy",
        "source_host_identity_ref",
        "deployment_owner_map_ref",
        "deployment_freeze_steps_ref",
        "service_dependency_map_ref",
        "database_runtime_facts_ref",
        "gateway_policy_export_ref",
        "external_provider_map_ref",
        "backup_restore_matrix_ref",
        "hetzner_project_ref",
        "region",
        "server_type",
        "architecture",
        "os_image",
        "network_cidrs",
        "volumes",
        "public_routes",
        "private_routes",
        "dns_provider_ref",
        "dns_zone_ref",
        "dns_records",
        "private_hostnames",
        "certificate_strategy_ref",
        "tailnet_grants_ref",
        "state_backend_ref",
        "backup_destination_ref",
        "backup_retention_days",
        "credential_refs",
        "recovery_credential_refs",
        "rpo_hours",
        "rto_minutes",
        "maintenance_window_ref",
        "maximum_downtime_minutes",
        "rollback_thresholds",
        "writer_job_map_ref",
    }
    assert all(value == {"status": "unresolved", "value": None, "evidence_ref": None} for value in contract["inputs"].values())
    inventory["environment_contract"]["inputs"]["credential_refs"] = {
        "status": "confirmed",
        "value": ["password=" + SECRET_SENTINEL],
        "evidence_ref": "restricted://fixture-reference",
    }
    inventory_path = latest_inventory(artifact_root, "legacy")
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    validation = run_cli(
        tmp_path / "validation",
        environment="legacy",
        artifact_root=artifact_root,
        command="validate",
        input_file=inventory_path,
    )

    assert validation.returncode != 0
    assert "environment contract schema rejected" in validation.stderr
    assert SECRET_SENTINEL not in validation.stderr
