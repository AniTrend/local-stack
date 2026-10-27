#!/usr/bin/env python3
"""Collect a normalized, secret-safe snapshot of Docker and repository metadata."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple
import uuid

import jsonschema
import yaml


SCHEMA_VERSION = "anitrend.platform.inventory.v1"
ENVIRONMENTS = ("lab", "legacy", "rehearsal", "production")
DEFAULT_ARTIFACT_ROOT = ".artifacts/platform"
EXCLUDED_SOURCE_PARTS = {".git", ".rendered", ".venv", "node_modules", "stacks", "__pycache__"}

CONTAINER_INSPECT_FORMAT = (
    r'{{printf "{\"id\":%s,\"name\":%s,\"image_ref\":%s,'
    r'\"image_id\":%s,\"state\":%s,\"project\":%s,\"service\":%s,'
    r'\"ports\":%s,\"mounts\":%s,\"networks\":%s,'
    r'\"memory_limit_bytes\":%v,\"nano_cpus\":%v,'
    r'\"size_rw_bytes\":%v,\"size_rootfs_bytes\":%v,\"restart_policy\":%s}"'
    r' (json .Id) (json .Name) (json .Config.Image) (json .Image)'
    r' (json .State.Status) (json (index .Config.Labels "com.docker.compose.project"))'
    r' (json (index .Config.Labels "com.docker.compose.service"))'
    r' (json .NetworkSettings.Ports) (json .Mounts) (json .NetworkSettings.Networks)'
    r' (json .HostConfig.Memory) (json .HostConfig.NanoCpus)'
    r' (json .SizeRw) (json .SizeRootFs) (json .HostConfig.RestartPolicy.Name)}}'
)
IMAGE_INSPECT_FORMAT = (
    r'{{printf "{\"id\":%s,\"os\":%s,\"architecture\":%s,\"repo_digests\":%s}"'
    r' (json .Id) (json .Os) (json .Architecture) (json .RepoDigests)}}'
)
DOCKER_VERSION_FORMAT = (
    r'{{printf "{\"client_version\":%s,\"server_version\":%s}"'
    r' (json .Client.Version) (json .Server.Version)}}'
)
DOCKER_INFO_FORMAT = (
    r'{{printf "{\"operating_system\":%s,\"architecture\":%s,'
    r'\"swarm_state\":%s,\"swarm_manager\":%v,\"cpu_count\":%v,'
    r'\"memory_total_bytes\":%v}"'
    r' (json .OperatingSystem) (json .Architecture) (json .Swarm.LocalNodeState)'
    r' (json .Swarm.ControlAvailable) (json .NCPU) (json .MemTotal)}}'
)

SIZE_UNITS = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}
SIZE_PATTERN = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)\s*$")
MEMORY_USAGE_PATTERN = re.compile(r"^\s*(.*?)\s*/\s*(.*?)\s*$")


class InventoryError(Exception):
    """An expected, user-actionable inventory failure without sensitive output."""


def _run_command(command: Sequence[str], timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as error:
        executable = Path(command[0]).name if command else "command"
        raise InventoryError("required executable is unavailable: " + executable) from error
    except subprocess.TimeoutExpired as error:
        executable = Path(command[0]).name if command else "command"
        raise InventoryError(executable + " exceeded the inventory timeout") from error
    if result.returncode != 0:
        executable = Path(command[0]).name if command else "command"
        raise InventoryError(executable + " failed with exit code " + str(result.returncode))
    return result.stdout


def _run_docker(arguments: Sequence[str], context: Optional[str] = None, timeout: int = 30) -> str:
    command = ["docker"]
    if context:
        command.extend(["--context", context])
    command.extend(arguments)
    try:
        return _run_command(command, timeout=timeout)
    except InventoryError as error:
        action = arguments[0] if arguments else "command"
        raise InventoryError("Docker " + action + ": " + str(error)) from error


def _parse_json_records(output: str, label: str) -> List[Dict[str, Any]]:
    if not output.strip():
        return []
    try:
        parsed = json.loads(output)
        records = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        records = []
        for line in output.splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise InventoryError(label + " returned invalid JSON") from error
    if not all(isinstance(record, dict) for record in records):
        raise InventoryError(label + " returned an unexpected JSON shape")
    return records


def _endpoint_kind(endpoint: str) -> str:
    if endpoint.startswith("unix://"):
        return "local_unix"
    if endpoint.startswith("npipe://"):
        return "local_npipe"
    if endpoint.startswith("ssh://"):
        return "remote_ssh"
    if endpoint.startswith(("tcp://", "http://", "https://")):
        return "remote_tcp"
    return "unknown"


def _docker_context(requested_context: Optional[str]) -> Tuple[str, str]:
    context = requested_context
    if context is None:
        context = _run_docker(["context", "show"]).strip()
    if not context:
        raise InventoryError("Docker did not report a selected context")
    output = _run_docker(["context", "inspect", "--format", "{{json .Endpoints.docker}}", context])
    try:
        endpoint_data = json.loads(output)
    except json.JSONDecodeError as error:
        raise InventoryError("Docker context endpoint metadata is invalid") from error
    endpoint = endpoint_data.get("Host", "") if isinstance(endpoint_data, dict) else ""
    return context, _endpoint_kind(endpoint)


def _parse_size_bytes(value: Any) -> Optional[int]:
    if not isinstance(value, str):
        return None
    match = SIZE_PATTERN.match(value)
    if not match:
        return None
    unit = match.group(2).upper()
    multiplier = SIZE_UNITS.get(unit)
    if multiplier is None:
        return None
    try:
        return int(Decimal(match.group(1)) * multiplier)
    except InvalidOperation:
        return None


def _address_classification(value: Any) -> Tuple[str, str]:
    if not isinstance(value, str) or not value:
        return "unknown", "unknown"
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return "unknown", "unknown"
    family = "ipv4" if address.version == 4 else "ipv6"
    if address.is_unspecified:
        scope = "wildcard"
    elif address.is_loopback:
        scope = "loopback"
    elif address.is_private:
        scope = "private"
    elif address.is_global:
        scope = "public"
    else:
        scope = "other"
    return family, scope


def _normalize_ports(raw_ports: Any) -> List[Dict[str, Any]]:
    normalized = []
    if not isinstance(raw_ports, dict):
        return normalized
    for container_port, bindings in raw_ports.items():
        port_value, separator, protocol = str(container_port).rpartition("/")
        if not separator:
            continue
        try:
            container_port_number = int(port_value)
        except ValueError:
            continue
        if not isinstance(bindings, list):
            continue
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            host_ip = binding.get("HostIp", "")
            family, scope = _address_classification(host_ip)
            host_port = binding.get("HostPort")
            try:
                host_port_number = int(host_port) if host_port else None
            except (TypeError, ValueError):
                host_port_number = None
            normalized.append(
                {
                    "container_port": container_port_number,
                    "protocol": protocol,
                    "host_port": host_port_number,
                    "host_address_scope": scope,
                    "address_family": family,
                }
            )
    return sorted(normalized, key=lambda item: (item["container_port"], item["protocol"], item["host_port"] or 0))


def _normalize_mounts(raw_mounts: Any, volume_sizes: Dict[str, Optional[int]]) -> List[Dict[str, Any]]:
    normalized = []
    if not isinstance(raw_mounts, list):
        return normalized
    for mount in raw_mounts:
        if not isinstance(mount, dict):
            continue
        name = mount.get("Name") or None
        size_bytes = volume_sizes.get(name) if name else None
        normalized.append(
            {
                "type": mount.get("Type") or "unknown",
                "name": name,
                "source_path": mount.get("Source") or None,
                "destination": mount.get("Destination") or "",
                "read_only": not bool(mount.get("RW", False)),
                "size_bytes": size_bytes,
                "size_status": "measured" if size_bytes is not None else "unknown",
            }
        )
    return sorted(normalized, key=lambda item: item["destination"])


def _parse_memory_pair(value: Any) -> Tuple[Optional[int], Optional[int]]:
    if not isinstance(value, str):
        return None, None
    match = MEMORY_USAGE_PATTERN.match(value)
    if not match:
        return None, None
    return _parse_size_bytes(match.group(1)), _parse_size_bytes(match.group(2))


def _parse_io_pair(value: Any) -> Tuple[Optional[int], Optional[int]]:
    return _parse_memory_pair(value)


def _normalize_stats(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    cpu_text = raw.get("CPUPerc", "")
    try:
        cpu_percent = float(str(cpu_text).strip().rstrip("%"))
    except ValueError:
        cpu_percent = None
    memory_used, memory_limit = _parse_memory_pair(raw.get("MemUsage"))
    network_received, network_sent = _parse_io_pair(raw.get("NetIO"))
    block_read, block_written = _parse_io_pair(raw.get("BlockIO"))
    try:
        pid_count = int(raw.get("PIDs"))
    except (TypeError, ValueError):
        pid_count = None
    try:
        memory_percent = float(str(raw.get("MemPerc", "")).strip().rstrip("%"))
    except ValueError:
        memory_percent = None
    return {
        "cpu_percent": cpu_percent,
        "memory_used_bytes": memory_used,
        "memory_limit_bytes": memory_limit,
        "memory_percent": memory_percent,
        "network_received_bytes": network_received,
        "network_sent_bytes": network_sent,
        "block_read_bytes": block_read,
        "block_written_bytes": block_written,
        "pid_count": pid_count,
    }


def _collect_timers(endpoint_kind: str) -> Dict[str, Any]:
    if endpoint_kind != "local_unix" or not sys.platform.startswith("linux"):
        return {"status": "not_local_linux", "units": []}
    if shutil.which("systemctl") is None:
        return {"status": "unavailable", "units": []}
    command = ["systemctl", "list-timers", "--all", "--no-pager", "--no-legend", "--output=json"]
    try:
        output = _run_command(command, timeout=15)
        timers = json.loads(output) if output.strip() else []
    except (InventoryError, json.JSONDecodeError):
        return {"status": "unavailable", "units": []}
    if not isinstance(timers, list):
        return {"status": "unavailable", "units": []}
    units = []
    for timer in timers:
        if not isinstance(timer, dict) or not isinstance(timer.get("unit"), str):
            continue
        units.append(
            {
                "unit": timer["unit"],
                "next": timer.get("next") if isinstance(timer.get("next"), str) else None,
                "last": timer.get("last") if isinstance(timer.get("last"), str) else None,
                "activates": timer.get("activates") if isinstance(timer.get("activates"), str) else None,
            }
        )
    return {"status": "collected", "units": sorted(units, key=lambda item: item["unit"])}



def _dependency_names(value: Any) -> List[str]:
    if isinstance(value, dict):
        return sorted(str(name) for name in value.keys())
    if isinstance(value, list):
        return sorted(str(name) for name in value)
    if isinstance(value, str):
        return [value]
    return []


def _env_file_refs(value: Any) -> List[str]:
    refs = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return sorted(str(ref) for ref in refs if isinstance(ref, str))


def _secret_refs(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    refs = []
    for secret in value:
        if isinstance(secret, str):
            refs.append(secret)
        elif isinstance(secret, dict) and isinstance(secret.get("source"), str):
            refs.append(secret["source"])
    return sorted(set(refs))


def _source_mounts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    mounts = []
    for mount in value:
        if isinstance(mount, dict):
            mounts.append(
                {
                    "type": str(mount.get("type", "unknown")),
                    "source": str(mount.get("source", "")),
                    "target": str(mount.get("target", "")),
                    "read_only": bool(mount.get("read_only", False)),
                }
            )
        elif isinstance(mount, str):
            pieces = mount.split(":")
            if len(pieces) >= 2:
                mounts.append(
                    {
                        "type": "declared",
                        "source": pieces[0],
                        "target": pieces[1],
                        "read_only": "ro" in pieces[2:],
                    }
                )
    return mounts


def _source_service_records(repo_root: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    services = []
    errors = []
    compose_paths = []
    for pattern in ("docker-compose*.yml", "docker-compose*.yaml"):
        compose_paths.extend(repo_root.rglob(pattern))
    for path in sorted(set(compose_paths)):
        relative = path.relative_to(repo_root)
        if EXCLUDED_SOURCE_PARTS.intersection(relative.parts):
            continue
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            errors.append(relative.as_posix() + ": compose source could not be parsed")
            continue
        if not isinstance(document, dict) or not isinstance(document.get("services"), dict):
            continue
        stack_extension = document.get("x-stack")
        for name, service in sorted(document["services"].items()):
            if not isinstance(name, str) or not isinstance(service, dict):
                errors.append(relative.as_posix() + ": service declaration is malformed")
                continue
            image = service.get("image")
            container_name = service.get("container_name")
            configuration_refs = []
            configuration_refs.extend(
                {"kind": "env_file", "ref": ref} for ref in _env_file_refs(service.get("env_file"))
            )
            configuration_refs.extend(
                {"kind": "secret", "ref": ref} for ref in _secret_refs(service.get("secrets"))
            )
            configuration_refs.extend(
                {"kind": "config", "ref": ref} for ref in _secret_refs(service.get("configs"))
            )
            services.append(
                {
                    "id": relative.as_posix() + ":" + name,
                    "source_repository": "AniTrend/local-stack",
                    "source_path": relative.as_posix(),
                    "compose_project": path.parent.name,
                    "service": name,
                    "image_ref": image if isinstance(image, str) else None,
                    "container_name": container_name if isinstance(container_name, str) else None,
                    "depends_on": _dependency_names(service.get("depends_on")),
                    "declared_mounts": _source_mounts(service.get("volumes")),
                    "configuration_refs": sorted(configuration_refs, key=lambda item: (item["kind"], item["ref"])),
                    "health_contract": {
                        "status": "unresolved",
                        "source_healthcheck_declared": isinstance(service.get("healthcheck"), dict),
                        "runtime_health_states": [],
                        "evidence_ref": None,
                    },
                    "database_runtime": {
                        "status": "unresolved",
                        "server_version": None,
                        "topology_ref": None,
                        "data_paths": [],
                    },
                    "writer_job_map_ref": None,
                    "external_provider_map_ref": None,
                    "backup_restore_method_ref": None,
                    "ingress_class": "unresolved",
                    "runtime_type": "not_observed",
                    "evidence_refs": ["source:" + relative.as_posix()],
                    "restart_policy": service.get("restart") if isinstance(service.get("restart"), str) else None,
                    "stack_extension": stack_extension if isinstance(stack_extension, str) else None,
                    "runtime_match_status": "not_observed",
                    "runtime_match_method": "not-observed",
                    "runtime_container_ids": [],
                    "current_deployment_owner": "unknown",
                    "target_deployment_owner": "unresolved",
                    "disposition": "unresolved",
                    "data_classification": "unresolved",
                }
            )
    return services, errors


def _collect_volume_rows(context: str) -> Tuple[List[Dict[str, Any]], Dict[str, Optional[int]], str]:
    try:
        output = _run_docker(["system", "df", "--verbose", "--format", "json"], context, timeout=120)
        records = _parse_json_records(output, "Docker disk usage")
    except InventoryError:
        return [], {}, "unavailable"
    payload = records[0] if records else {}
    raw_volumes = payload.get("Volumes", []) if isinstance(payload, dict) else []
    if not isinstance(raw_volumes, list):
        return [], {}, "unavailable"
    volumes = []
    sizes: Dict[str, Optional[int]] = {}
    for volume in raw_volumes:
        if not isinstance(volume, dict) or not isinstance(volume.get("Name"), str):
            continue
        name = volume["Name"]
        size_bytes = _parse_size_bytes(volume.get("Size"))
        sizes[name] = size_bytes
        volumes.append(
            {
                "name": name,
                "driver": volume.get("Driver") if isinstance(volume.get("Driver"), str) else "unknown",
                "scope": volume.get("Scope") if isinstance(volume.get("Scope"), str) else "unknown",
                "links": volume.get("Links") if isinstance(volume.get("Links"), int) else None,
                "size_bytes": size_bytes,
                "size_status": "measured" if size_bytes is not None else "unknown",
            }
        )
    return sorted(volumes, key=lambda item: item["name"]), sizes, "collected"


def _collect_stats(context: str) -> Dict[str, Dict[str, Any]]:
    try:
        output = _run_docker(["stats", "--no-stream", "--format", "json"], context, timeout=60)
        records = _parse_json_records(output, "Docker resource statistics")
    except InventoryError:
        return {}
    stats = {}
    for record in records:
        identifier = record.get("ID")
        if isinstance(identifier, str):
            stats[identifier] = record
    return stats


def _collect_images(image_ids: Sequence[str], context: str) -> Dict[str, Dict[str, Any]]:
    images = {}
    for image_id in sorted(set(image_ids)):
        if not image_id:
            continue
        try:
            output = _run_docker(["image", "inspect", "--format", IMAGE_INSPECT_FORMAT, image_id], context)
            records = _parse_json_records(output, "Docker image metadata")
        except InventoryError:
            continue
        if not records:
            continue
        record = records[0]
        identifier = record.get("id")
        if isinstance(identifier, str):
            repo_digests = record.get("repo_digests")
            images[identifier] = {
                "os": record.get("os") if isinstance(record.get("os"), str) else None,
                "architecture": record.get("architecture") if isinstance(record.get("architecture"), str) else None,
                "repo_digests": sorted(item for item in repo_digests if isinstance(item, str)) if isinstance(repo_digests, list) else [],
            }
    return images


def _status_rows(output: str) -> Dict[str, str]:
    statuses = {}
    for line in output.splitlines():
        fields = line.split("\t", 2)
        if len(fields) == 3:
            statuses[fields[0]] = fields[2]
    return statuses


def _health_status(status: str) -> str:
    normalized = status.lower()
    if "(healthy)" in normalized:
        return "healthy"
    if "(unhealthy)" in normalized:
        return "unhealthy"
    if "(health: starting)" in normalized or "(starting)" in normalized:
        return "starting"
    return "unknown"


def _network_names(raw_networks: Any) -> List[Dict[str, Any]]:
    networks = []
    if not isinstance(raw_networks, dict):
        return networks
    for name, endpoint in sorted(raw_networks.items()):
        aliases = endpoint.get("Aliases", []) if isinstance(endpoint, dict) else []
        networks.append(
            {
                "name": str(name),
                "aliases": sorted(alias for alias in aliases if isinstance(alias, str)) if isinstance(aliases, list) else [],
            }
        )
    return networks


def _normalize_container(
    raw: Dict[str, Any],
    status_text: str,
    image_metadata: Dict[str, Dict[str, Any]],
    stats_rows: Dict[str, Dict[str, Any]],
    volume_sizes: Dict[str, Optional[int]],
) -> Dict[str, Any]:
    identifier = str(raw.get("id", ""))
    image_id = str(raw.get("image_id", ""))
    image = image_metadata.get(image_id, {})
    raw_stats = None
    for short_id, stats in stats_rows.items():
        if identifier.startswith(short_id):
            raw_stats = stats
            break
    name = raw.get("name", "")
    return {
        "id": identifier,
        "name": str(name).lstrip("/"),
        "image_ref": raw.get("image_ref") if isinstance(raw.get("image_ref"), str) else "unknown",
        "image_id": image_id,
        "repo_digests": image.get("repo_digests", []),
        "image_os": image.get("os"),
        "image_architecture": image.get("architecture"),
        "state": raw.get("state") if isinstance(raw.get("state"), str) else "unknown",
        "health": _health_status(status_text),
        "compose_project": raw.get("project") if isinstance(raw.get("project"), str) else None,
        "compose_service": raw.get("service") if isinstance(raw.get("service"), str) else None,
        "source_service_id": None,
        "ports": _normalize_ports(raw.get("ports")),
        "networks": _network_names(raw.get("networks")),
        "mounts": _normalize_mounts(raw.get("mounts"), volume_sizes),
        "resource_limits": {
            "memory_bytes": raw.get("memory_limit_bytes") if isinstance(raw.get("memory_limit_bytes"), int) else 0,
            "nano_cpus": raw.get("nano_cpus") if isinstance(raw.get("nano_cpus"), int) else 0,
        },
        "resource_usage": _normalize_stats(raw_stats),
        "container_layer_size_bytes": raw.get("size_rw_bytes") if isinstance(raw.get("size_rw_bytes"), int) else None,
        "rootfs_size_bytes": raw.get("size_rootfs_bytes") if isinstance(raw.get("size_rootfs_bytes"), int) else None,
        "restart_policy": raw.get("restart_policy") if isinstance(raw.get("restart_policy"), str) else "unknown",
    }


def _match_source_services(
    containers: List[Dict[str, Any]], source_services: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    by_labels: Dict[Tuple[Optional[str], Optional[str]], List[Dict[str, Any]]] = {}
    by_container_name: Dict[str, List[Dict[str, Any]]] = {}
    for service in source_services:
        by_labels.setdefault((service["compose_project"], service["service"]), []).append(service)
        if service["container_name"]:
            by_container_name.setdefault(service["container_name"], []).append(service)
    for container in containers:
        match_method = "compose-labels"
        matches = by_labels.get((container["compose_project"], container["compose_service"]), [])
        if not matches:
            matches = by_container_name.get(container["name"], [])
            match_method = "container-name"
        if len(matches) == 1:
            service = matches[0]
            container["source_service_id"] = service["id"]
            service["runtime_match_status"] = "matched"
            service["runtime_match_method"] = match_method
            service["runtime_type"] = "docker-compose" if match_method == "compose-labels" else "docker-container"
            service["current_deployment_owner"] = "Compose labels observed; deployment operator unknown" if match_method == "compose-labels" else "container name matched; deployment operator unknown"
            service["runtime_container_ids"].append(container["id"])
            service["health_contract"]["runtime_health_states"].append(container["health"])
            service["health_contract"]["evidence_ref"] = "docker-container:" + container["id"]
            service["evidence_refs"].append("docker-container:" + container["id"])
        elif len(matches) > 1:
            for service in matches:
                service["runtime_match_status"] = "ambiguous"
                service["runtime_match_method"] = "ambiguous"
                service["runtime_type"] = "ambiguous"
        else:
            container["source_service_id"] = None
    for service in source_services:
        if service["runtime_match_status"] == "not_observed":
            service["runtime_match_method"] = "not-observed"
            service["runtime_type"] = "not_observed"
            service["current_deployment_owner"] = "not observed on selected Docker engine"
        service["health_contract"]["runtime_health_states"] = sorted(
            set(service["health_contract"]["runtime_health_states"])
        )
    return source_services


def _collect_docker(environment: str, requested_context: Optional[str]) -> Tuple[Dict[str, Any], List[str]]:
    context, endpoint_kind = _docker_context(requested_context)
    if environment == "lab" and endpoint_kind not in ("local_unix", "local_npipe"):
        raise InventoryError("ENV=lab requires an explicitly selected local Docker endpoint")
    version_records = _parse_json_records(
        _run_docker(["version", "--format", DOCKER_VERSION_FORMAT], context), "Docker version"
    )
    info_records = _parse_json_records(
        _run_docker(["info", "--format", DOCKER_INFO_FORMAT], context), "Docker host information"
    )
    if not version_records or not info_records:
        raise InventoryError("Docker did not return required host metadata")
    info = info_records[0]
    listing = _run_docker(
        ["ps", "--all", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}"], context
    )
    status_texts = _status_rows(listing)
    container_ids = list(status_texts.keys())
    raw_containers = []
    if container_ids:
        inspect_output = _run_docker(
            ["inspect", "--size", "--type", "container", "--format", CONTAINER_INSPECT_FORMAT, *container_ids],
            context,
            timeout=120,
        )
        raw_containers = _parse_json_records(inspect_output, "Docker container metadata")
    volume_rows, volume_sizes, volume_status = _collect_volume_rows(context)
    running_containers = [item for item in raw_containers if item.get("state") == "running"]
    stats_rows = _collect_stats(context) if running_containers else {}
    stats_observed = sum(
        1
        for item in running_containers
        if any(str(item.get("id", "")).startswith(short_id) for short_id in stats_rows)
    )
    if not running_containers:
        resource_usage_status = "not_applicable"
    elif stats_observed == len(running_containers):
        resource_usage_status = "collected"
    elif stats_observed:
        resource_usage_status = "partial"
    else:
        resource_usage_status = "unavailable"
    errors = []
    if resource_usage_status in ("partial", "unavailable"):
        errors.append("Docker resource statistics are partial or unavailable")
    image_metadata = _collect_images(
        [str(item.get("image_id", "")) for item in raw_containers], context
    )
    containers = []
    for raw in raw_containers:
        identifier = str(raw.get("id", ""))
        containers.append(
            _normalize_container(
                raw,
                status_texts.get(identifier, ""),
                image_metadata,
                stats_rows,
                volume_sizes,
            )
        )
    timers = _collect_timers(endpoint_kind)
    if volume_status != "collected":
        errors.append("Docker volume sizes could not be collected")
    if any(not container["repo_digests"] for container in containers):
        errors.append("one or more container images have no observed repository digest")
    running_count = sum(1 for container in containers if container["state"] == "running")
    docker = {
        "context_name": context,
        "endpoint_kind": endpoint_kind,
        "client_version": version_records[0].get("client_version", "unknown"),
        "server_version": version_records[0].get("server_version", "unknown"),
        "operating_system": info.get("operating_system", "unknown"),
        "architecture": info.get("architecture", "unknown"),
        "swarm_state": info.get("swarm_state", "unknown"),
        "swarm_manager": bool(info.get("swarm_manager", False)),
        "cpu_count": info.get("cpu_count") if isinstance(info.get("cpu_count"), int) else 0,
        "memory_total_bytes": info.get("memory_total_bytes") if isinstance(info.get("memory_total_bytes"), int) else 0,
        "container_count": len(containers),
        "running_count": running_count,
        "resource_usage_status": resource_usage_status,
        "containers": sorted(containers, key=lambda item: item["name"]),
        "volumes": volume_rows,
        "volume_inventory_status": volume_status,
        "host_timers": timers,
    }
    return docker, errors


def _reconcile_containers(containers: List[Dict[str, Any]], source_services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    source_ids = {service["id"] for service in source_services}
    unmatched = []
    for container in containers:
        source_id = container.get("source_service_id")
        if source_id is None or source_id not in source_ids:
            unmatched.append(
                {
                    "container_id": container["id"],
                    "name": container["name"],
                    "compose_project": container["compose_project"],
                    "compose_service": container["compose_service"],
                    "disposition": "unresolved",
                    "deployment_owner": "unknown",
                    "evidence_ref": "docker-container:" + container["id"],
                }
            )
    return unmatched


def _empty_environment_contract(schema_path: Path) -> Dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        inputs = schema["properties"]["inputs"]["properties"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise InventoryError("environment contract schema could not be loaded") from error
    if not isinstance(inputs, dict) or not inputs:
        raise InventoryError("environment contract schema has no input definitions")
    return {
        "schema_version": "anitrend.platform.environment.v1",
        "target_environment": "production",
        "inputs": {
            name: {"status": "unresolved", "value": None, "evidence_ref": None}
            for name in inputs
        },
    }



def _git_metadata(repo_root: Path) -> Tuple[str, bool]:
    try:
        revision = _run_command(["git", "-C", str(repo_root), "rev-parse", "HEAD"], timeout=5).strip()
        dirty = bool(_run_command(["git", "-C", str(repo_root), "status", "--porcelain"], timeout=5).strip())
    except InventoryError:
        return "unknown", False
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        return "unknown", dirty
    return revision, dirty


def _reconciliation_validation_error(payload: Dict[str, Any]) -> Optional[str]:
    reconciliation = payload["reconciliation"]
    decision = reconciliation["decision"]
    reasons = reconciliation["blocked_reasons"]
    if decision != "pass":
        if decision in ("blocked", "fail", "skipped") and not reasons:
            return "non-passing reconciliation states require a reason"
        return None
    if payload["environment"] == "lab":
        return "reconciliation gate cannot pass from ENV=lab inventory"

    unresolved = not payload["collector_worktree_clean"] or payload["collector_commit"] == "unknown"
    unresolved = unresolved or bool(payload["collection_issues"]) or bool(reasons)
    unresolved = unresolved or payload["docker"]["volume_inventory_status"] != "collected"
    if payload["docker"]["running_count"] and payload["docker"]["resource_usage_status"] != "collected":
        unresolved = True
    for item in payload["environment_contract"]["inputs"].values():
        if item["status"] not in ("confirmed", "not_applicable") or not item["evidence_ref"]:
            unresolved = True
        if item["status"] == "confirmed" and item["value"] is None:
            unresolved = True
        if item["status"] == "not_applicable" and item["value"] is not None:
            unresolved = True
    inputs = payload["environment_contract"]["inputs"]
    if inputs["provider"]["status"] != "confirmed" or inputs["provider"]["value"] != "hcloud":
        unresolved = True
    required_safety_policy = {
        "protect_resources": True,
        "allow_destroy": False,
        "require_environment_approval": True,
        "deny_pull_request_mutations": True,
    }
    if inputs["safety_policy"]["status"] != "confirmed" or inputs["safety_policy"]["value"] != required_safety_policy:
        unresolved = True
    for service in payload["repository_services"]:
        if service["disposition"] == "unresolved" or service["data_classification"] == "unresolved":
            unresolved = True
        if service["runtime_match_status"] == "ambiguous":
            unresolved = True
        for field in ("current_deployment_owner", "target_deployment_owner"):
            if any(token in service[field].lower() for token in ("unknown", "unresolved", "pending")):
                unresolved = True
        if (
            service["ingress_class"] == "unresolved"
            or service["health_contract"]["status"] == "unresolved"
            or service["database_runtime"]["status"] == "unresolved"
            or not service["writer_job_map_ref"]
            or not service["external_provider_map_ref"]
            or not service["backup_restore_method_ref"]
            or not service["evidence_refs"]
        ):
            unresolved = True
    for container in payload["unmatched_containers"]:
        if container["disposition"] == "unresolved" or "unknown" in container["deployment_owner"].lower():
            unresolved = True
    if unresolved:
        return "reconciliation gate cannot pass while required inventory fields are unresolved"
    return None

def _validate_payload(payload: Dict[str, Any], schema_path: Path) -> Optional[str]:
    environment_schema_path = schema_path.with_name("environment.schema.json")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        environment_schema = json.loads(environment_schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator.check_schema(environment_schema)
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        error = next(iter(validator.iter_errors(payload)), None)
        environment_validator = jsonschema.Draft202012Validator(
            environment_schema, format_checker=jsonschema.FormatChecker()
        )
        environment_error = next(
            iter(environment_validator.iter_errors(payload.get("environment_contract", {}))), None
        )
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError):
        return "inventory or environment schema could not be loaded or validated"
    if error is not None:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        description = "additional properties" if error.validator == "additionalProperties" else "invalid field"
        return "inventory schema rejected " + location + ": " + description
    if environment_error is not None:
        location = ".".join(str(part) for part in environment_error.absolute_path) or "$"
        description = "additional properties" if environment_error.validator == "additionalProperties" else "invalid field"
        return "environment contract schema rejected " + location + ": " + description
    return _reconciliation_validation_error(payload)


def _collect_inventory(
    environment: str,
    repo_root: Path,
    artifact_root: Path,
    schema_path: Path,
    requested_context: Optional[str],
) -> Tuple[Dict[str, Any], Path]:
    docker, collection_errors = _collect_docker(environment, requested_context)
    source_services, source_errors = _source_service_records(repo_root)
    collection_errors.extend(source_errors)
    source_services = _match_source_services(docker["containers"], source_services)
    unmatched = _reconcile_containers(docker["containers"], source_services)
    revision, dirty = _git_metadata(repo_root)
    observed = datetime.now(timezone.utc).replace(microsecond=0)
    run_id = observed.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    for service in source_services:
        if not service["runtime_container_ids"]:
            service["evidence_refs"].append("docker-snapshot:" + run_id)
        service["evidence_refs"] = sorted(set(service["evidence_refs"]))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "environment": environment,
        "observed_at_utc": observed.isoformat().replace("+00:00", "Z"),
        "collector_commit": revision,
        "collector_worktree_clean": not dirty,
        "docker": docker,
        "repository_services": source_services,
        "unmatched_containers": unmatched,
        "collection_issues": sorted(collection_errors),
        "environment_contract": _empty_environment_contract(
            schema_path.with_name("environment.schema.json")
        ),
        "reconciliation": {
            "decision": "blocked",
            "blocked_reasons": [
                "The source host role and production identity are not confirmed by owner-supplied evidence.",
                "Service dispositions, ownership, writer/job schedules, external providers, and recovery paths require reconciliation.",
                "Required target, network, credential-reference, backup, and cutover inputs remain unresolved.",
            ],
        },
    }
    error = _validate_payload(payload, schema_path)
    if error:
        raise InventoryError(error)
    output_dir = artifact_root / run_id
    try:
        output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        output_path = output_dir / "inventory.json"
        descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
    except OSError as error:
        raise InventoryError("private inventory artifact could not be written") from error
    return payload, output_path


def _latest_inventory(artifact_root: Path, environment: str) -> Path:
    candidates = []
    for path in artifact_root.glob("*/inventory.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("environment") == environment:
            candidates.append(path)
    if not candidates:
        raise InventoryError("no inventory artifact exists for the requested ENV")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _validate_inventory(environment: str, input_path: Optional[Path], artifact_root: Path, schema_path: Path) -> str:
    path = input_path if input_path is not None else _latest_inventory(artifact_root, environment)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InventoryError("inventory file could not be read as JSON") from error
    if not isinstance(payload, dict):
        raise InventoryError("inventory JSON must contain an object")
    if payload.get("environment") != environment:
        raise InventoryError("inventory ENV does not match the requested ENV")
    error = _validate_payload(payload, schema_path)
    if error:
        raise InventoryError(error)
    decision = payload.get("reconciliation", {}).get("decision", "blocked")
    return "schema=valid gate=" + str(decision)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only, secret-safe platform inventory collection")
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect", help="collect Docker and Compose metadata without changing the daemon")
    collect.add_argument("--environment", required=True, choices=ENVIRONMENTS)
    collect.add_argument("--repo-root", type=Path, default=_repository_root())
    collect.add_argument("--artifact-root", type=Path, default=_repository_root() / DEFAULT_ARTIFACT_ROOT)
    collect.add_argument("--context", help="explicit Docker context; omitted uses the selected context without changing it")
    validate = subparsers.add_parser("validate", help="validate the latest or selected inventory schema")
    validate.add_argument("--environment", required=True, choices=ENVIRONMENTS)
    validate.add_argument("--artifact-root", type=Path, default=_repository_root() / DEFAULT_ARTIFACT_ROOT)
    validate.add_argument("--input", type=Path)
    return parser


def main(arguments: Optional[Sequence[str]] = None) -> int:
    parser = _argument_parser()
    options = parser.parse_args(arguments)
    repo_root = _repository_root()
    schema_path = repo_root / "infra" / "pulumi" / "shared" / "inventory.schema.json"
    try:
        if options.command == "collect":
            payload, path = _collect_inventory(
                options.environment,
                options.repo_root.resolve(),
                options.artifact_root.resolve(),
                schema_path,
                options.context,
            )
            print(
                "inventory=" + path.relative_to(options.artifact_root.resolve()).as_posix()
                + " schema=valid reconciliation=" + payload["reconciliation"]["decision"]
            )
            return 0
        print(_validate_inventory(options.environment, options.input, options.artifact_root, schema_path))
        return 0
    except InventoryError as error:
        print("error: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
