#!/usr/bin/env python3
"""Fail-closed entry point for the isolated Docker platform lab."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import secrets
import socket
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import yaml


ENVIRONMENTS = ("lab", "rehearsal", "production", "legacy")
FORBIDDEN_CREDENTIAL_ENV = (
    "HCLOUD_TOKEN",
    "HETZNER_TOKEN",
    "PULUMI_ACCESS_TOKEN",
    "SOPS_AGE_KEY",
    "TAILSCALE_AUTHKEY",
    "DOKPLOY_API_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AZURE_CLIENT_SECRET",
    "GOOGLE_APPLICATION_CREDENTIALS",
)
MIN_LAB_MEMORY_BYTES = 2 * 1024**3
MIN_LAB_DISK_BYTES = 2 * 1024**3
LAB_ARTIFACT_ROOT = Path(".artifacts/platform/lab")
LAB_RUN_SCHEMA = "anitrend.platform.lab-run.v1"
ACTIVE_RUN_SCHEMA = "anitrend.platform.lab-active-run.v1"
RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
LAB_SOURCE_PATHS = (
    ".gitignore",
    ".node-version",
    ".python-version",
    "Makefile",
    "ansible/requirements.yml",
    "infra/pulumi/docker",
    "infra/pulumi/shared",
    "tools/platform/lab.py",
    "tools/platform/pulumi-version.txt",
    "tools/platform/requirements.in",
    "tools/platform/requirements.lock",
)
RUN_RESOURCE_TYPES = {
    "docker:index/container:Container",
    "docker:index/network:Network",
    "docker:index/remoteImage:RemoteImage",
    "docker:index/volume:Volume",
    "pulumi:providers:docker",
    "pulumi:pulumi:Stack",
}


class LabError(Exception):
    """A fail-closed lab check with a safe message."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run_result(
    command: Sequence[str],
    timeout: int = 30,
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError as error:
        raise LabError("required local executable is unavailable") from error
    except subprocess.TimeoutExpired as error:
        raise LabError("a local prerequisite check exceeded its timeout") from error


def _run(
    command: Sequence[str],
    timeout: int = 30,
    *,
    cwd: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> str:
    result = _run_result(command, timeout, cwd=cwd, env=env)
    if result.returncode != 0:
        raise LabError("a local prerequisite check failed")
    return result.stdout.strip()


def _git_bytes(repo_root: Path, arguments: Sequence[str]) -> bytes:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise LabError("Git source identity is unavailable") from error
    except subprocess.TimeoutExpired as error:
        raise LabError("Git source identity check timed out") from error
    if result.returncode != 0:
        raise LabError("Git source identity could not be read")
    return result.stdout


def _version(command: Sequence[str], pattern: str) -> str:
    output = _run(command)
    match = re.search(pattern, output)
    if match is None:
        raise LabError("a pinned tool reported an unrecognized version")
    return match.group(1)

def _pulumi_binary(repo_root: Path) -> str:
    configured = os.environ.get("PLATFORM_PULUMI_BIN", "pulumi")
    if Path(configured).is_absolute():
        return configured
    if os.sep in configured or (os.altsep is not None and os.altsep in configured):
        return str((repo_root / configured).resolve())
    return configured


def _read_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LabError(label + " is missing or invalid") from error
    if not isinstance(value, dict):
        raise LabError(label + " must contain a JSON object")
    return value


def _read_text(path: Path, label: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise LabError(label + " is missing or unreadable") from error
    if not value:
        raise LabError(label + " is empty")
    return value


def _locked_versions(path: Path) -> Dict[str, str]:
    versions = {}
    requirement = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^\s;]+)")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise LabError("the platform Python lockfile is missing or unreadable") from error
    for line in lines:
        match = requirement.match(line.strip())
        if match:
            versions[match.group(1).lower().replace("_", "-")] = match.group(2)
    return versions


def _locked_ansible_collections(path: Path) -> Dict[str, str]:
    try:
        requirements = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise LabError("the Ansible collection requirements file is missing or invalid") from error
    if not isinstance(requirements, dict) or not isinstance(requirements.get("collections"), list):
        raise LabError("the Ansible collection requirements file must declare pinned collections")

    versions: Dict[str, str] = {}
    for collection in requirements["collections"]:
        if not isinstance(collection, dict):
            raise LabError("the Ansible collection requirements file contains an invalid entry")
        name = collection.get("name")
        version = collection.get("version")
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", name) is None
            or not isinstance(version, str)
            or re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version) is None
            or name in versions
        ):
            raise LabError("the Ansible collection requirements file must pin unique collection versions")
        versions[name] = version
    if not versions:
        raise LabError("the Ansible collection requirements file must not be empty")
    return versions


def _local_ansible_collection_versions(
    executable: str,
    collections_path: Path,
) -> Dict[str, str]:
    try:
        output = _run(
            [
                executable,
                "collection",
                "list",
                "--format",
                "json",
                "--collections-path",
                str(collections_path),
            ]
        )
        listing = json.loads(output)
    except (LabError, json.JSONDecodeError) as error:
        raise LabError("the project-local Ansible collection inventory is unavailable or invalid") from error
    if not isinstance(listing, dict):
        raise LabError("the project-local Ansible collection inventory must be a JSON object")

    local_collection_root = str(collections_path / "ansible_collections")
    installed = listing.get(local_collection_root)
    if not isinstance(installed, dict):
        return {}

    versions: Dict[str, str] = {}
    for name, metadata in installed.items():
        if isinstance(name, str) and isinstance(metadata, dict):
            version = metadata.get("version")
            if isinstance(version, str):
                versions[name] = version
    return versions


def _parse_context_allowlist(value: Optional[str]) -> set[str]:
    if value is None:
        return set()
    return {context.strip() for context in value.split(",") if context.strip()}

def _normalize_architecture(value: str) -> Optional[str]:
    if value.lower() in ("x86_64", "amd64"):
        return "amd64"
    if value.lower() in ("aarch64", "arm64"):
        return "arm64"
    return None


def _docker_command(context: str, *arguments: str) -> List[str]:
    return ["docker", "--context", context, *arguments]


def _docker_context_endpoint(context: str) -> Tuple[str, str]:
    try:
        output = _run(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker}}", context])
        endpoint_data = json.loads(output)
    except (LabError, json.JSONDecodeError) as error:
        raise LabError("the selected Docker context could not be inspected") from error
    if not isinstance(endpoint_data, dict):
        raise LabError("the selected Docker context returned invalid endpoint metadata")
    endpoint = endpoint_data.get("Host", "")
    if not isinstance(endpoint, str):
        raise LabError("the selected Docker endpoint is invalid")
    if endpoint.startswith("unix://"):
        return endpoint, "local_unix"
    if endpoint.startswith("npipe://"):
        return endpoint, "local_npipe"
    return "", "remote_or_unknown"


def _doctor(environment: str, repo_root: Path) -> Dict[str, Any]:
    if environment != "lab":
        raise LabError("platform-doctor only accepts ENV=lab")
    if any(os.environ.get(name) for name in FORBIDDEN_CREDENTIAL_ENV):
        raise LabError("the lab refuses production credentials in the process environment")

    context = os.environ.get("PLATFORM_DOCKER_CONTEXT", "").strip()
    if not context:
        raise LabError("PLATFORM_DOCKER_CONTEXT must explicitly select a local context")
    if re.search(r"(^|[-_.])(prod(?:uction)?|legacy|rehearsal|hcloud|hetzner|remote)(?:$|[-_.])", context, re.IGNORECASE):
        raise LabError("production and non-lab Docker contexts are refused")
    allowlist = _parse_context_allowlist(os.environ.get("PLATFORM_ALLOWED_DOCKER_CONTEXTS"))
    if not allowlist or context not in allowlist:
        raise LabError("the selected Docker context is not in PLATFORM_ALLOWED_DOCKER_CONTEXTS")
    endpoint, endpoint_kind = _docker_context_endpoint(context)
    if endpoint_kind not in ("local_unix", "local_npipe"):
        raise LabError("ENV=lab requires an explicitly allowlisted local Docker endpoint")

    version_format = '{{printf "{\\"client_version\\":%s,\\"server_version\\":%s}" (json .Client.Version) (json .Server.Version)}}'
    info_format = '{{printf "{\\"operating_system\\":%s,\\"architecture\\":%s,\\"swarm_state\\":%s,\\"cpu_count\\":%v,\\"memory_total_bytes\\":%v}" (json .OperatingSystem) (json .Architecture) (json .Swarm.LocalNodeState) (json .NCPU) (json .MemTotal)}}'
    try:
        version_data = json.loads(_run(_docker_command(context, "version", "--format", version_format)))
        host_data = json.loads(_run(_docker_command(context, "info", "--format", info_format)))
        compose_version = _run(_docker_command(context, "compose", "version", "--short"))
    except (LabError, json.JSONDecodeError) as error:
        raise LabError("Docker Engine API or Compose is unavailable for the selected context") from error

    host_os = platform.system()
    host_architecture = platform.machine()
    docker_os = host_data.get("operating_system")
    docker_architecture = host_data.get("architecture")
    host_arch = _normalize_architecture(host_architecture) if isinstance(host_architecture, str) else None
    docker_arch = _normalize_architecture(docker_architecture) if isinstance(docker_architecture, str) else None
    if host_os not in ("Darwin", "Linux"):
        raise LabError("the platform lab supports only macOS and Linux hosts")
    if host_arch is None or docker_arch is None:
        raise LabError("the host and selected Docker daemon must use amd64 or arm64")
    if not isinstance(docker_os, str) or not docker_os:
        raise LabError("the selected Docker daemon did not report its operating system")
    if host_data.get("swarm_state") != "inactive":
        raise LabError("the platform lab refuses Docker daemons with Swarm enabled or unknown")
    if not isinstance(host_data.get("cpu_count"), int) or host_data["cpu_count"] < 2:
        raise LabError("the selected Docker host has fewer than two CPUs")
    if not isinstance(host_data.get("memory_total_bytes"), int) or host_data["memory_total_bytes"] < MIN_LAB_MEMORY_BYTES:
        raise LabError("the selected Docker host has less than 2 GiB of memory")
    if shutil.disk_usage(repo_root).free < MIN_LAB_DISK_BYTES:
        raise LabError("the local filesystem has less than 2 GiB free for disposable lab resources")

    node_version = _version([os.environ.get("PLATFORM_NODE_BIN", "node"), "--version"], r"v?(\d+\.\d+\.\d+)")
    expected_node = _read_text(repo_root / ".node-version", "Node version pin")
    npm_version = _version([os.environ.get("PLATFORM_NPM_BIN", "npm"), "--version"], r"(\d+\.\d+\.\d+)")
    package_json = _read_json(repo_root / "infra/pulumi/docker/package.json", "Pulumi package manifest")
    package_manager = package_json.get("packageManager", "")
    expected_npm = package_manager.split("@", 1)[1] if "@" in package_manager else ""
    package_lock = _read_json(repo_root / "infra/pulumi/docker/package-lock.json", "Pulumi package lockfile")
    root_lock = package_lock.get("packages", {}).get("", {})
    if root_lock.get("dependencies") != package_json.get("dependencies") or root_lock.get("devDependencies") != package_json.get("devDependencies"):
        raise LabError("Pulumi package-lock dependencies do not match package.json")

    pulumi_version = _version([_pulumi_binary(repo_root), "version"], r"v?(\d+\.\d+\.\d+)")
    expected_pulumi = _read_text(repo_root / "tools/platform/pulumi-version.txt", "Pulumi CLI version pin")
    python_binary = os.environ.get("PLATFORM_PYTHON_BIN", "python3.14")
    python_version = _version([python_binary, "--version"], r"Python (\d+\.\d+\.\d+)")
    expected_python = _read_text(repo_root / ".python-version", "Python version pin")
    requirements = _locked_versions(repo_root / "tools/platform/requirements.lock")
    ansible_version_output = _run([os.environ.get("PLATFORM_ANSIBLE_BIN", "ansible-playbook"), "--version"])
    ansible_match = re.search(r"\[core ([0-9.]+)\]", ansible_version_output)
    molecule_version = _version([os.environ.get("PLATFORM_MOLECULE_BIN", "molecule"), "--version"], r"molecule\s+(\d+\.\d+\.\d+)")
    molecule_plugin_version = _version(
        [python_binary, "-c", "import importlib.metadata; print(importlib.metadata.version('molecule-plugins'))"],
        r"(\d+\.\d+\.\d+)",
    )
    jsonschema_version = _version(
        [python_binary, "-c", "import importlib.metadata; print(importlib.metadata.version('jsonschema'))"],
        r"(\d+\.\d+\.\d+)",
    )
    if ansible_match is None:
        raise LabError("Ansible Core did not report a recognized version")
    ansible_version = ansible_match.group(1)

    required_collections = _locked_ansible_collections(repo_root / "ansible/requirements.yml")
    collection_path_value = os.environ.get(
        "PLATFORM_ANSIBLE_COLLECTIONS_PATH",
        ".tools/platform/collections",
    )
    if not collection_path_value.strip():
        raise LabError("PLATFORM_ANSIBLE_COLLECTIONS_PATH must select a project-local directory")
    collections_path = Path(collection_path_value)
    if not collections_path.is_absolute():
        collections_path = repo_root / collections_path
    collections_path = collections_path.resolve()
    try:
        collections_path.relative_to(repo_root.resolve())
    except ValueError as error:
        raise LabError("Ansible collections must be installed inside the repository") from error
    installed_collections = _local_ansible_collection_versions(
        os.environ.get("PLATFORM_ANSIBLE_GALAXY_BIN", "ansible-galaxy"),
        collections_path,
    )
    missing_collections = [
        f"{name}=={version}"
        for name, version in sorted(required_collections.items())
        if installed_collections.get(name) != version
    ]
    if missing_collections:
        raise LabError(
            "required project-local Ansible collections are missing or mismatched: "
            + ", ".join(missing_collections)
        )

    expected_versions = {
        "node": (node_version, expected_node),
        "npm": (npm_version, expected_npm),
        "pulumi": (pulumi_version, expected_pulumi),
        "python": (python_version, expected_python),
        "ansible-core": (ansible_version, requirements.get("ansible-core", "")),
        "molecule": (molecule_version, requirements.get("molecule", "")),
        "molecule-plugins": (molecule_plugin_version, requirements.get("molecule-plugins", "")),
        "jsonschema": (jsonschema_version, requirements.get("jsonschema", "")),
    }
    mismatches = [name for name, (actual, expected) in expected_versions.items() if not expected or actual != expected]
    if mismatches:
        raise LabError("pinned local tool versions are missing or mismatched: " + ", ".join(sorted(mismatches)))

    server_version = version_data.get("server_version")
    if not isinstance(server_version, str) or not server_version:
        raise LabError("Docker Engine did not report a server version")
    compose_match = re.search(r"\d+\.\d+\.\d+", compose_version)
    if compose_match is None:
        raise LabError("Docker Compose did not report a version")
    image_lock = _read_json(repo_root / "infra/pulumi/docker/images.lock.json", "SSH fixture image lock")
    ssh_fixture = image_lock.get("ssh_fixture", {})
    image_ref = ssh_fixture.get("image", "")
    image_platforms = ssh_fixture.get("platforms", [])
    if not isinstance(image_ref, str) or not re.search(r"@sha256:[0-9a-f]{64}$", image_ref):
        raise LabError("SSH fixture image must be pinned by an immutable digest")
    if not isinstance(image_platforms, list) or set(image_platforms) != {"linux/amd64", "linux/arm64"}:
        raise LabError("SSH fixture image must support native Linux amd64 and arm64")

    image_platform = "linux/" + docker_arch
    if image_platform not in image_platforms:
        raise LabError("SSH fixture image does not support the selected Docker daemon architecture")
    execution_mode = "native" if host_arch == docker_arch else "emulated"
    image_digest = image_ref.split("@", 1)[1]
    if not isinstance(ssh_fixture.get("port"), int) or not 1 <= ssh_fixture["port"] <= 65535:
        raise LabError("SSH fixture lock must declare a valid container port")
    ssh_container_port = ssh_fixture["port"]
    report = [
        "platform-doctor=pass",
        "environment=lab",
        "docker_context=" + context,
        "docker_endpoint_kind=" + endpoint_kind,
        "docker_version=" + server_version,
        "host_os=" + host_os,
        "host_architecture=" + host_architecture,
        "docker_os=" + docker_os,
        "docker_architecture=" + docker_architecture,
        "docker_swarm_state=inactive",
        "image_platform=" + image_platform,
        "execution_mode=" + execution_mode,
        "compose_version=" + compose_match.group(0),
        "node_version=" + node_version,
        "npm_version=" + npm_version,
        "pulumi_version=" + pulumi_version,
        "python_version=" + python_version,
        "ansible_core_version=" + ansible_version,
        "molecule_version=" + molecule_version,
        "jsonschema_version=" + jsonschema_version,
        "molecule_plugins_version=" + molecule_plugin_version,
        *[
            "ansible_collection_" + name.replace(".", "_") + "_version=" + installed_collections[name]
            for name in sorted(required_collections)
        ],
        "ssh_fixture_digest=" + image_digest,
    ]
    return {
        "report": report,
        "docker_context": context,
        "docker_host": endpoint,
        "docker_endpoint_kind": endpoint_kind,
        "host_os": host_os,
        "host_architecture": host_architecture,
        "docker_os": docker_os,
        "docker_architecture": docker_architecture,
        "image_platform": image_platform,
        "execution_mode": execution_mode,
        "image_ref": image_ref,
        "image_digest": image_digest,
        "ssh_container_port": ssh_container_port,
        "tool_versions": {name: actual for name, (actual, _) in expected_versions.items()},
    }


def _artifact_root(repo_root: Path) -> Path:
    return repo_root / LAB_ARTIFACT_ROOT

@contextmanager
def _lifecycle_lock(repo_root: Path) -> Iterator[None]:
    artifact_root = _artifact_root(repo_root)
    artifact_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(artifact_root, 0o700)
    lock_path = artifact_root / "lifecycle.lock"
    if lock_path.is_symlink():
        raise LabError("refusing to use a symlink as the lab lifecycle lock")
    descriptor = -1
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise LabError("another platform lab lifecycle operation is active") from error
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        raise LabError("could not acquire the local lab lifecycle lock") from error
    try:
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _run_stack_name(run_id: str) -> str:
    return "platform-lab-" + run_id


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def _validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise LabError("run ID must use YYYYMMDDTHHMMSSZ-<8 lowercase hex characters>")

def _reserve_loopback_port() -> int:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
    except OSError as error:
        raise LabError("could not reserve a loopback SSH port for the lab") from error
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise LabError("operating system selected an unsupported loopback SSH port")
    return port


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    temporary_path: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        descriptor, temporary_name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        os.chmod(path, mode)
    except OSError as error:
        raise LabError("could not write local lab state") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _validate_lab_artifact(value: Dict[str, Any], definition: str, label: str) -> None:
    try:
        import jsonschema
    except ImportError as error:
        raise LabError("the locked JSON Schema validator is unavailable") from error
    schema = _read_json(_repo_root() / "infra/pulumi/shared/platform-lab.schema.json", "platform lab artifact schema")
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        raise LabError("platform lab artifact schema has no definitions")
    validator_schema = {
        "$schema": schema.get("$schema"),
        "$defs": definitions,
        "$ref": "#/$defs/" + definition,
    }
    try:
        jsonschema.Draft202012Validator.check_schema(validator_schema)
        validator = jsonschema.Draft202012Validator(
            validator_schema,
            format_checker=jsonschema.FormatChecker(),
        )
        error = next(iter(validator.iter_errors(value)), None)
    except jsonschema.SchemaError as error:
        raise LabError("platform lab artifact schema is invalid") from error
    if error is not None:
        location = ".".join(str(part) for part in error.absolute_path) or "root"
        raise LabError(label + " does not match its schema at " + location)


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    if path.name == "manifest.json":
        _validate_lab_artifact(value, "labRun", "lab run manifest")
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")

def _create_active_run(path: Path, value: Dict[str, Any]) -> None:
    temporary_path = path.parent / ("." + path.name + "." + uuid.uuid4().hex)
    _write_json(temporary_path, value)
    try:
        os.link(temporary_path, path)
    except FileExistsError as error:
        raise LabError("another lab run became active concurrently") from error
    except OSError as error:
        raise LabError("could not register the active lab run") from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _source_metadata(repo_root: Path) -> Dict[str, Any]:
    try:
        commit_bytes = _git_bytes(repo_root, ["rev-parse", "HEAD"])
        status = _git_bytes(repo_root, ["status", "--porcelain=v1", "--untracked-files=all", "-z"])
        tracked_diff = _git_bytes(
            repo_root,
            ["diff", "--binary", "--no-ext-diff", "HEAD", "--", *LAB_SOURCE_PATHS],
        )
        untracked_paths = _git_bytes(
            repo_root,
            ["ls-files", "--others", "--exclude-standard", "-z", "--", *LAB_SOURCE_PATHS],
        )
        commit = commit_bytes.decode("ascii").strip()
    except (LabError, UnicodeError) as error:
        raise LabError("Git source identity is unavailable") from error
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise LabError("Git returned an invalid source commit")

    digest = hashlib.sha256()
    digest.update(commit.encode("ascii"))
    digest.update(b"\0")
    digest.update(tracked_diff)
    for relative_path in untracked_paths.split(b"\0"):
        if not relative_path:
            continue
        path = repo_root / os.fsdecode(relative_path)
        try:
            if path.is_symlink():
                content = os.fsencode(os.readlink(path))
            elif path.is_file():
                content = path.read_bytes()
            else:
                content = b""
        except OSError as error:
            raise LabError("untracked source changed while its identity was recorded") from error
        digest.update(b"\0")
        digest.update(relative_path)
        digest.update(b"\0")
        digest.update(content)

    return {
        "commit": commit,
        "worktree_clean": not bool(status),
        "worktree_sha256": digest.hexdigest(),
    }


def _assert_source_snapshot(repo_root: Path, manifest: Dict[str, Any]) -> None:
    current_source = _source_metadata(repo_root)
    source = manifest.get("source")
    if (
        not isinstance(source, dict)
        or source.get("commit") != current_source["commit"]
        or source.get("worktree_sha256") != current_source["worktree_sha256"]
    ):
        raise LabError(
            "active lab run source snapshot changed; use platform-lab-down before retrying"
        )


def _read_active_run(repo_root: Path, requested_run_id: Optional[str]) -> Tuple[str, str, Path, Path]:
    artifact_root = _artifact_root(repo_root)
    active_path = artifact_root / "active-run.json"
    if active_path.is_symlink() or not active_path.is_file():
        raise LabError("no active lab run is recorded")
    record = _read_json(active_path, "active lab run record")
    run_id = record.get("run_id")
    if record.get("schema_version") != ACTIVE_RUN_SCHEMA or not isinstance(run_id, str):
        raise LabError("active lab run record is invalid")
    _validate_run_id(run_id)
    if requested_run_id is not None and requested_run_id != run_id:
        raise LabError("requested run ID does not match the active lab run")
    stack_name = _run_stack_name(run_id)
    if record.get("stack_name") != stack_name:
        raise LabError("active lab stack identity does not match its run ID")
    run_dir = artifact_root / run_id
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise LabError("active lab run state directory is missing or invalid")
    return run_id, stack_name, run_dir, active_path


def _read_manifest(run_dir: Path, run_id: str) -> Dict[str, Any]:
    manifest = _read_json(run_dir / "manifest.json", "lab run manifest")
    if manifest.get("schema_version") != LAB_RUN_SCHEMA or manifest.get("run_id") != run_id:
        raise LabError("lab run manifest does not match its active run ID")
    if manifest.get("environment") != "lab" or manifest.get("stack_name") != _run_stack_name(run_id):
        raise LabError("lab run manifest contains a non-lab stack identity")
    return manifest


def _set_lab_assertion(
    manifest: Dict[str, Any],
    manifest_path: Path,
    assertion: str,
    operation: Callable[[], Any],
) -> Any:
    manifest[assertion] = "pending"
    _write_json(manifest_path, manifest)
    try:
        result = operation()
    except Exception:
        manifest[assertion] = "failed"
        _write_json(manifest_path, manifest)
        raise
    manifest[assertion] = "pass"
    _write_json(manifest_path, manifest)
    return result


def _create_ssh_key(run_dir: Path, run_id: str) -> Tuple[Path, str]:
    ssh_dir = run_dir / "ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(ssh_dir, 0o700)
    private_key = ssh_dir / "id_ed25519"
    public_key_path = ssh_dir / "id_ed25519.pub"
    if private_key.exists() or public_key_path.exists():
        if not private_key.is_file() or not public_key_path.is_file():
            raise LabError("lab SSH keypair is incomplete; use platform-lab-down before retrying")
    else:
        _run(
            [
                os.environ.get("PLATFORM_SSH_KEYGEN_BIN", "ssh-keygen"),
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                "platform-lab/" + run_id,
                "-f",
                str(private_key),
            ],
            timeout=30,
        )
    os.chmod(private_key, 0o600)
    os.chmod(public_key_path, 0o600)
    public_key = _read_text(public_key_path, "lab SSH public key")
    if not public_key.startswith("ssh-ed25519 ") or "\n" in public_key:
        raise LabError("ssh-keygen did not create one ed25519 public key")
    return private_key, public_key


def _prepare_run(
    repo_root: Path,
    requested_run_id: Optional[str],
    readiness: Dict[str, Any],
) -> Tuple[str, str, Path, Path, str, Path, str, Dict[str, Any]]:
    artifact_root = _artifact_root(repo_root)
    active_path = artifact_root / "active-run.json"
    if active_path.exists():
        run_id, stack_name, run_dir, active_path = _read_active_run(repo_root, requested_run_id)
        manifest = _read_manifest(run_dir, run_id)
        _assert_source_snapshot(repo_root, manifest)
        passphrase = _read_text(run_dir / "passphrase", "lab state passphrase")
        private_key, public_key = _create_ssh_key(run_dir, run_id)
        ssh_host_port = manifest.get("ssh_host_port")
        if not isinstance(ssh_host_port, int) or not 1024 <= ssh_host_port <= 65535:
            ssh_host_port = _reserve_loopback_port()
        readiness["ssh_host_port"] = ssh_host_port
        manifest_facts = {key: value for key, value in readiness.items() if key != "docker_host"}
        manifest["image_ref"] = readiness["image_ref"]
        manifest["image_digest"] = readiness["image_digest"]
        manifest["image_platform"] = readiness["image_platform"]
        manifest["execution_mode"] = readiness["execution_mode"]
        manifest["tool_versions"] = readiness["tool_versions"]
        manifest["ssh_host_port"] = ssh_host_port
        manifest["environment_facts"] = manifest_facts
        _write_json(run_dir / "manifest.json", manifest)
        return run_id, stack_name, run_dir, active_path, passphrase, private_key, public_key, manifest

    run_id = requested_run_id or _new_run_id()
    _validate_run_id(run_id)
    stack_name = _run_stack_name(run_id)
    run_dir = artifact_root / run_id
    if run_dir.exists() or run_dir.is_symlink():
        raise LabError("run ID already has local lab state; choose a new run ID")
    run_dir.mkdir(parents=True, mode=0o700)
    os.chmod(run_dir, 0o700)
    passphrase = secrets.token_urlsafe(32)
    ssh_host_port = _reserve_loopback_port()
    readiness["ssh_host_port"] = ssh_host_port
    manifest_facts = {key: value for key, value in readiness.items() if key != "docker_host"}
    try:
        _atomic_write(run_dir / "passphrase", passphrase + "\n")
        private_key, public_key = _create_ssh_key(run_dir, run_id)
        manifest = {
            "schema_version": LAB_RUN_SCHEMA,
            "environment": "lab",
            "run_id": run_id,
            "stack_name": stack_name,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": _source_metadata(repo_root),
            "environment_facts": manifest_facts,
            "image_ref": readiness["image_ref"],
            "image_digest": readiness["image_digest"],
            "image_platform": readiness["image_platform"],
            "execution_mode": readiness["execution_mode"],
            "tool_versions": readiness["tool_versions"],
            "pulumi_stack_created": False,
            "ssh_host_port": ssh_host_port,
            "revision": 1,
            "pulumi_preview": "pending",
            "pulumi_up": "pending",
            "pulumi_noop_up": "pending",
            "ssh_validation": "pending",
            "controlled_update": "pending",
            "cleanup_status": "pending",
            "outputs": None,
        }
        _write_json(run_dir / "manifest.json", manifest)
        _create_active_run(
            active_path,
            {"schema_version": ACTIVE_RUN_SCHEMA, "run_id": run_id, "stack_name": stack_name},
        )
    except Exception:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    return run_id, stack_name, run_dir, active_path, passphrase, private_key, public_key, manifest

def _pulumi_environment(run_dir: Path, passphrase: str) -> Dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "DOCKER_AUTH_CONFIG",
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "DOCKER_TLS_VERIFY",
        "PULUMI_ACCESS_TOKEN",
        "PULUMI_API",
        "PULUMI_BACKEND_URL",
        "PULUMI_CONFIG_PASSPHRASE_FILE",
        "PULUMI_CREDENTIALS_PATH",
    ):
        environment.pop(name, None)

    pulumi_home = run_dir / "pulumi-home"
    pulumi_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(pulumi_home, 0o700)
    environment["PULUMI_BACKEND_URL"] = "file://" + str((run_dir / "backend").resolve())
    environment["PULUMI_CREDENTIAL_STORE"] = "plaintext"
    environment["PULUMI_HOME"] = str(pulumi_home)
    environment["PULUMI_CONFIG_PASSPHRASE"] = passphrase
    environment["PULUMI_SKIP_UPDATE_CHECK"] = "true"
    return environment


def _pulumi(
    repo_root: Path,
    run_dir: Path,
    passphrase: str,
    arguments: Sequence[str],
    timeout: int = 600,
) -> str:
    project_dir = repo_root / "infra/pulumi/docker"
    command = [_pulumi_binary(repo_root), *arguments]
    return _run(command, timeout, cwd=project_dir, env=_pulumi_environment(run_dir, passphrase))


def _pulumi_login(repo_root: Path, run_dir: Path, passphrase: str) -> None:
    backend = run_dir / "backend"
    backend.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backend, 0o700)
    _pulumi(
        repo_root,
        run_dir,
        passphrase,
        ["login", "--non-interactive", "file://" + str(backend.resolve())],
    )


def _pulumi_select_stack(repo_root: Path, run_dir: Path, passphrase: str, stack_name: str) -> None:
    _pulumi(
        repo_root,
        run_dir,
        passphrase,
        [
            "stack",
            "select",
            stack_name,
            "--create",
            "--secrets-provider=passphrase",
            "--non-interactive",
        ],
    )


def _pulumi_set_config(
    repo_root: Path,
    run_dir: Path,
    passphrase: str,
    stack_name: str,
    key: str,
    value: str,
) -> None:
    _pulumi(
        repo_root,
        run_dir,
        passphrase,
        ["config", "set", "lab:" + key, value, "--stack", stack_name, "--non-interactive"],
    )


def _set_lab_config(
    repo_root: Path,
    run_dir: Path,
    passphrase: str,
    stack_name: str,
    run_id: str,
    revision: int,
    readiness: Dict[str, Any],
    public_key: str,
) -> None:
    allowlist = sorted(_parse_context_allowlist(os.environ.get("PLATFORM_ALLOWED_DOCKER_CONTEXTS")))
    values = {
        "runId": run_id,
        "dockerContext": readiness["docker_context"],
        "allowedDockerContexts": json.dumps(allowlist, separators=(",", ":")),
        "dockerHost": readiness["docker_host"],
        "hostOs": readiness["host_os"],
        "hostArchitecture": readiness["host_architecture"],
        "dockerOs": readiness["docker_os"],
        "dockerArchitecture": readiness["docker_architecture"],
        "imagePlatform": readiness["image_platform"],
        "sshHostPort": str(readiness["ssh_host_port"]),
        "revision": str(revision),
        "publicKey": public_key,
    }
    for key, value in values.items():
        _pulumi_set_config(repo_root, run_dir, passphrase, stack_name, key, value)


def _read_lab_outputs(
    repo_root: Path,
    run_dir: Path,
    passphrase: str,
    stack_name: str,
    run_id: str,
    readiness: Dict[str, Any],
) -> Dict[str, Any]:
    raw = _pulumi(
        repo_root,
        run_dir,
        passphrase,
        ["stack", "output", "labOutputs", "--json", "--stack", stack_name],
    )
    try:
        outputs = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LabError("Pulumi lab outputs are not valid JSON") from error
    if not isinstance(outputs, dict):
        raise LabError("Pulumi lab outputs must be a JSON object")
    _validate_lab_artifact(outputs, "labOutput", "Pulumi lab outputs")
    expected = {
        "schema_version": "anitrend.platform.lab-output.v1",
        "environment": "lab",
        "run_id": run_id,
        "image_ref": readiness["image_ref"],
        "image_digest": readiness["image_digest"],
        "image_platform": readiness["image_platform"],
        "ssh_host_port": readiness["ssh_host_port"],
    }
    if any(outputs.get(key) != value for key, value in expected.items()):
        raise LabError("Pulumi outputs do not match the active lab run and pinned image")
    image_id = outputs.get("image_id")
    if not isinstance(image_id, str) or not image_id.startswith("sha256:"):
        raise LabError("Pulumi did not report the pulled image ID")
    if not all(isinstance(outputs.get(key), str) and outputs[key].startswith("anitrend-platform-lab-" + run_id) for key in ("network_name", "volume_name", "container_name")):
        raise LabError("Pulumi outputs contain resource names outside the active lab run")
    if not isinstance(outputs.get("ssh_host_port"), int) or not 1 <= outputs["ssh_host_port"] <= 65535:
        raise LabError("Pulumi did not report an assigned SSH host port")
    if outputs.get("execution_mode") not in ("native", "emulated"):
        raise LabError("Pulumi did not report the lab execution mode")
    return outputs
def _docker_json(context: str, arguments: Sequence[str]) -> Dict[str, Any]:
    raw = _run(_docker_command(context, *arguments))
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LabError("Docker returned invalid inspection data") from error
    if not isinstance(value, dict):
        raise LabError("Docker inspection data must be a JSON object")
    return value


def _verify_labels(labels: Any, run_id: str, resource: str, revision: int) -> None:
    expected = {
        "anitrend.platform.managed-by": "pulumi",
        "anitrend.platform.environment": "lab",
        "anitrend.platform.run-id": run_id,
        "anitrend.platform.resource": resource,
        "anitrend.platform.revision": str(revision),
    }
    if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected.items()):
        raise LabError("Docker resource labels do not match the active lab run")


def _inspect_lab_resources(
    readiness: Dict[str, Any],
    outputs: Dict[str, Any],
    run_id: str,
    revision: int,
) -> Dict[str, Any]:
    context = readiness["docker_context"]
    network = _docker_json(context, ["network", "inspect", "--format", "{{json .}}", outputs["network_name"]])
    volume = _docker_json(context, ["volume", "inspect", "--format", "{{json .}}", outputs["volume_name"]])
    container = _docker_json(
        context,
        ["inspect", "--type", "container", "--format", "{{json .}}", outputs["container_name"]],
    )
    _verify_labels(network.get("Labels"), run_id, "network", revision)
    _verify_labels(volume.get("Labels"), run_id, "volume", revision)
    if network.get("Name") != outputs["network_name"] or network.get("Internal") is not False:
        raise LabError("lab network identity or isolation does not match the Pulumi outputs")
    if volume.get("Name") != outputs["volume_name"] or volume.get("Driver") != "local":
        raise LabError("lab scratch volume identity does not match the Pulumi outputs")
    if container.get("Name", "").lstrip("/") != outputs["container_name"]:
        raise LabError("lab SSH container identity does not match the Pulumi outputs")
    if container.get("State", {}).get("Running") is not True:
        raise LabError("lab SSH container is not running")
    config = container.get("Config", {})
    host_config = container.get("HostConfig", {})
    _verify_labels(config.get("Labels"), run_id, "ssh-fixture", revision)
    if container.get("Image") != outputs["image_id"] or host_config.get("Privileged") is not False:
        raise LabError("lab SSH container image or privilege settings do not match the lab contract")

    internal_port = readiness["ssh_container_port"]
    port_bindings = host_config.get("PortBindings", {}).get(f"{internal_port}/tcp")
    if not isinstance(port_bindings, list) or len(port_bindings) != 1:
        raise LabError("lab SSH container must have exactly one published port")
    binding = port_bindings[0]
    if binding.get("HostIp") != "127.0.0.1" or binding.get("HostPort") != str(outputs["ssh_host_port"]):
        raise LabError("lab SSH port is not reserved on loopback at the Pulumi-assigned port")

    mounts = container.get("Mounts", [])
    if not isinstance(mounts, list) or len(mounts) != 1:
        raise LabError("lab SSH container must use only its owned scratch volume")
    mount = mounts[0]
    if mount.get("Type") != "volume" or mount.get("Name") != outputs["volume_name"] or mount.get("Destination") != "/config":
        raise LabError("lab SSH container mount is not the owned configuration volume")
    networks = container.get("NetworkSettings", {}).get("Networks", {})
    if not isinstance(networks, dict) or outputs["network_name"] not in networks:
        raise LabError("lab SSH container is not attached to its isolated network")

    image_id = container.get("Image")
    if not isinstance(image_id, str) or not image_id:
        raise LabError("lab SSH container did not report its image identity")
    image = _docker_json(context, ["image", "inspect", "--format", "{{json .}}", image_id])
    expected_architecture = outputs["image_platform"].split("/", 1)[1]
    if image.get("Architecture") != expected_architecture:
        raise LabError("pulled SSH image architecture does not match the declared lab platform")
    return {"container_id": container.get("Id"), "image_id": image_id, "architecture": image.get("Architecture")}


def _verify_ssh_access(run_dir: Path, private_key: Path, outputs: Dict[str, Any]) -> None:
    known_hosts = run_dir / "ssh" / "known_hosts"
    keyscan = _run(
        [
            os.environ.get("PLATFORM_SSH_KEYSCAN_BIN", "ssh-keyscan"),
            "-T",
            "5",
            "-p",
            str(outputs["ssh_host_port"]),
            "127.0.0.1",
        ],
        timeout=15,
    )
    if not keyscan:
        raise LabError("lab SSH endpoint did not provide a host key")
    _atomic_write(known_hosts, keyscan + "\n")
    ssh_output = _run(
        [
            os.environ.get("PLATFORM_SSH_BIN", "ssh"),
            "-i",
            str(private_key),
            "-p",
            str(outputs["ssh_host_port"]),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            "UserKnownHostsFile=" + str(known_hosts),
            "-o",
            "ConnectTimeout=10",
            "-o",
            "LogLevel=ERROR",
            "ansible@127.0.0.1",
            "uname",
            "-s",
        ],
        timeout=20,
    )
    if ssh_output != "Linux":
        raise LabError("lab SSH fixture did not report a Linux host")


def _print_lab_summary(command: str, run_id: str, stack_name: str, outputs: Dict[str, Any]) -> None:
    print("platform-lab-" + command + "=pass")
    print("run_id=" + run_id)
    print("pulumi_stack=" + stack_name)
    print("network_name=" + outputs["network_name"])
    print("volume_name=" + outputs["volume_name"])
    print("container_name=" + outputs["container_name"])
    print("ssh_host_port=" + str(outputs["ssh_host_port"]))
    print("image_digest=" + outputs["image_digest"])
    print("image_platform=" + outputs["image_platform"])
    print("execution_mode=" + outputs["execution_mode"])


def _lab_up(environment: str, repo_root: Path, requested_run_id: Optional[str]) -> None:
    readiness = _doctor(environment, repo_root)
    run_id, stack_name, run_dir, _, passphrase, _, public_key, manifest = _prepare_run(
        repo_root,
        requested_run_id,
        readiness,
    )
    _pulumi_login(repo_root, run_dir, passphrase)
    _pulumi_select_stack(repo_root, run_dir, passphrase, stack_name)
    manifest["pulumi_stack_created"] = True
    _write_json(run_dir / "manifest.json", manifest)
    revision = manifest.get("pending_revision") or manifest.get("revision", 1)
    if not isinstance(revision, int) or revision < 1:
        raise LabError("lab manifest revision is invalid")
    _set_lab_config(repo_root, run_dir, passphrase, stack_name, run_id, revision, readiness, public_key)
    manifest["pulumi_preview"] = "pending"
    manifest["pulumi_up"] = "pending"
    manifest["pulumi_noop_up"] = "pending"
    _write_json(run_dir / "manifest.json", manifest)
    _pulumi(
        repo_root,
        run_dir,
        passphrase,
        ["preview", "--non-interactive", "--stack", stack_name],
    )
    manifest["pulumi_preview"] = "pass"
    _write_json(run_dir / "manifest.json", manifest)
    _pulumi(
        repo_root,
        run_dir,
        passphrase,
        ["up", "--yes", "--non-interactive", "--stack", stack_name],
    )
    manifest["pulumi_up"] = "pass"
    outputs = _read_lab_outputs(repo_root, run_dir, passphrase, stack_name, run_id, readiness)
    manifest["outputs"] = outputs
    manifest["last_operation"] = "up"
    _write_json(run_dir / "manifest.json", manifest)
    _print_lab_summary("up", run_id, stack_name, outputs)



def _lab_test(environment: str, repo_root: Path, requested_run_id: Optional[str]) -> None:
    readiness = _doctor(environment, repo_root)
    run_id, stack_name, run_dir, _ = _read_active_run(repo_root, requested_run_id)
    manifest = _read_manifest(run_dir, run_id)
    _assert_source_snapshot(repo_root, manifest)
    manifest_path = run_dir / "manifest.json"
    pending_revision = manifest.get("pending_revision")
    if pending_revision is None:
        manifest["pulumi_noop_up"] = "pending"
        manifest["test_stage"] = "pulumi-noop-up"
    else:
        manifest["test_stage"] = "resume-controlled-update"
    if manifest.get("controlled_update") != "pass":
        manifest["controlled_update"] = "pending"
    manifest["ssh_validation"] = "pending"
    manifest["last_operation"] = "test"
    _write_json(manifest_path, manifest)

    ssh_host_port = manifest.get("ssh_host_port")
    if not isinstance(ssh_host_port, int) or not 1024 <= ssh_host_port <= 65535:
        raise LabError("active lab manifest has no valid reserved SSH port")
    readiness["ssh_host_port"] = ssh_host_port
    if manifest.get("pulumi_up") != "pass":
        raise LabError("run platform-lab-up before platform-lab-test")
    passphrase = _read_text(run_dir / "passphrase", "lab state passphrase")
    private_key = run_dir / "ssh" / "id_ed25519"
    public_key = _read_text(run_dir / "ssh" / "id_ed25519.pub", "lab SSH public key")
    if not private_key.is_file():
        raise LabError("lab SSH private key is missing; run platform-lab-down to clean this run")
    _pulumi_login(repo_root, run_dir, passphrase)
    _pulumi_select_stack(repo_root, run_dir, passphrase, stack_name)

    if pending_revision is None:
        _set_lab_assertion(
            manifest,
            manifest_path,
            "pulumi_noop_up",
            lambda: _pulumi(
                repo_root,
                run_dir,
                passphrase,
                ["up", "--yes", "--expect-no-changes", "--non-interactive", "--stack", stack_name],
            ),
        )
        manifest["test_stage"] = "docker-resource-inspection"
        _write_json(manifest_path, manifest)
        outputs = _read_lab_outputs(repo_root, run_dir, passphrase, stack_name, run_id, readiness)
        evidence = _inspect_lab_resources(readiness, outputs, run_id, manifest["revision"])
        manifest["resource_evidence"] = evidence
        manifest["test_stage"] = "ssh-validation"
        _write_json(manifest_path, manifest)
        _set_lab_assertion(
            manifest,
            manifest_path,
            "ssh_validation",
            lambda: _verify_ssh_access(run_dir, private_key, outputs),
        )
    else:
        outputs = _read_lab_outputs(repo_root, run_dir, passphrase, stack_name, run_id, readiness)

    if manifest.get("controlled_update") != "pass":
        revision = 2
        manifest["pending_revision"] = revision
        manifest["test_stage"] = "controlled-update"
        _write_json(manifest_path, manifest)

        def apply_controlled_update() -> Tuple[Dict[str, Any], Dict[str, Any]]:
            _set_lab_config(repo_root, run_dir, passphrase, stack_name, run_id, revision, readiness, public_key)
            _pulumi(
                repo_root,
                run_dir,
                passphrase,
                ["preview", "--diff", "--non-interactive", "--stack", stack_name],
            )
            _pulumi(
                repo_root,
                run_dir,
                passphrase,
                ["up", "--yes", "--non-interactive", "--stack", stack_name],
            )
            manifest["test_stage"] = "controlled-update-inspection"
            _write_json(manifest_path, manifest)
            updated_outputs = _read_lab_outputs(repo_root, run_dir, passphrase, stack_name, run_id, readiness)
            evidence = _inspect_lab_resources(readiness, updated_outputs, run_id, revision)
            _set_lab_assertion(
                manifest,
                manifest_path,
                "ssh_validation",
                lambda: _verify_ssh_access(run_dir, private_key, updated_outputs),
            )
            manifest["revision"] = revision
            manifest["pending_revision"] = None
            manifest["resource_evidence"] = evidence
            return updated_outputs, evidence

        outputs, _ = _set_lab_assertion(
            manifest,
            manifest_path,
            "controlled_update",
            apply_controlled_update,
        )
    else:
        manifest["test_stage"] = "final-resource-inspection"
        _write_json(manifest_path, manifest)
        outputs = _read_lab_outputs(repo_root, run_dir, passphrase, stack_name, run_id, readiness)
        evidence = _inspect_lab_resources(readiness, outputs, run_id, manifest["revision"])
        _set_lab_assertion(
            manifest,
            manifest_path,
            "ssh_validation",
            lambda: _verify_ssh_access(run_dir, private_key, outputs),
        )
        manifest["resource_evidence"] = evidence

    manifest["outputs"] = outputs
    manifest["last_operation"] = "test"
    manifest["test_stage"] = "complete"
    _write_json(manifest_path, manifest)
    _print_lab_summary("test", run_id, stack_name, outputs)
    print("pulumi_noop_up=pass")
    print("ssh_linux=pass")
    print("controlled_update=pass")


def _lab_preview(environment: str, repo_root: Path, requested_run_id: Optional[str]) -> None:
    run_id, stack_name, run_dir, _ = _read_active_run(repo_root, requested_run_id)
    manifest = _read_manifest(run_dir, run_id)
    _assert_source_snapshot(repo_root, manifest)
    outputs = manifest.get("outputs")
    if (
        manifest.get("pulumi_stack_created") is not True
        or manifest.get("pulumi_up") != "pass"
        or not isinstance(outputs, dict)
        or manifest.get("cleanup_status") == "pass"
    ):
        raise LabError("run platform-lab-up before platform-preview")

    readiness = _doctor(environment, repo_root)
    passphrase = _read_text(run_dir / "passphrase", "lab state passphrase")
    _pulumi_login(repo_root, run_dir, passphrase)
    _pulumi_resource_inventory(repo_root, run_dir, passphrase, stack_name, run_id, manifest, readiness)
    preview_output = _pulumi(
        repo_root,
        run_dir,
        passphrase,
        ["preview", "--diff", "--non-interactive", "--stack", stack_name],
    )
    if preview_output:
        print(preview_output)
    print("platform-lab-preview=pass")
    print("run_id=" + run_id)
    print("pulumi_stack=" + stack_name)



def _state_label_map(value: Any) -> Optional[Dict[str, str]]:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    if isinstance(value, list):
        labels: Dict[str, str] = {}
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("label"), str) and isinstance(item.get("value"), str):
                labels[item["label"]] = item["value"]
        return labels
    return None


def _pulumi_resource_inventory(
    repo_root: Path,
    run_dir: Path,
    passphrase: str,
    stack_name: str,
    run_id: str,
    manifest: Dict[str, Any],
    readiness: Dict[str, Any],
) -> List[Dict[str, str]]:
    raw = _pulumi(repo_root, run_dir, passphrase, ["stack", "export", "--stack", stack_name])
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LabError("Pulumi lab state is not valid JSON") from error
    deployment = state.get("deployment") if isinstance(state, dict) else None
    resources = deployment.get("resources") if isinstance(deployment, dict) else None
    outputs = manifest.get("outputs")
    names = {
        "network": outputs.get("network_name") if isinstance(outputs, dict) else f"anitrend-platform-lab-{run_id}-network",
        "volume": outputs.get("volume_name") if isinstance(outputs, dict) else f"anitrend-platform-lab-{run_id}-config",
        "container": outputs.get("container_name") if isinstance(outputs, dict) else f"anitrend-platform-lab-{run_id}-ssh",
    }
    if not isinstance(resources, list):
        empty_preapply_checkpoint = (
            isinstance(state, dict)
            and state.get("version") == 3
            and isinstance(deployment, dict)
            and "resources" not in deployment
            and isinstance(deployment.get("manifest"), dict)
            and isinstance(deployment.get("secrets_providers"), dict)
            and isinstance(deployment.get("metadata"), dict)
            and outputs is None
            and manifest.get("pulumi_preview") != "pass"
            and manifest.get("pulumi_up") != "pass"
        )
        if not empty_preapply_checkpoint:
            raise LabError("Pulumi lab state has no resource inventory")
        resources = []
    roles = {
        "docker:index/container:Container": ("container", "ssh-fixture"),
        "docker:index/network:Network": ("network", "network"),
        "docker:index/volume:Volume": ("volume", "volume"),
    }
    observed: List[Dict[str, str]] = []
    for resource in resources:
        if not isinstance(resource, dict):
            raise LabError("Pulumi lab state contains an invalid resource entry")
        resource_type = resource.get("type")
        if resource_type not in RUN_RESOURCE_TYPES:
            raise LabError("Pulumi lab state contains a resource outside the Docker lab contract")
        inputs = resource.get("inputs", {})
        if not isinstance(inputs, dict):
            inputs = {}
        if resource_type == "pulumi:providers:docker":
            provider_host = inputs.get("host")
            if provider_host is not None and provider_host != readiness["docker_host"]:
                raise LabError("Pulumi Docker provider endpoint does not match the selected local context")
            continue
        if resource_type in ("pulumi:pulumi:Stack",):
            continue
        if resource_type == "docker:index/remoteImage:RemoteImage":
            if inputs.get("name") != manifest.get("image_ref") or inputs.get("keepLocally") is not True:
                raise LabError("Pulumi image state is not the pinned, locally retained SSH fixture")
            observed.append({"type": resource_type, "name": str(inputs.get("name", ""))})
            continue
        role = roles.get(resource_type)
        if role is None:
            raise LabError("Pulumi lab state contains an unsupported Docker resource")
        logical_name, label_role = role
        resource_name = inputs.get("name")
        if resource_name != names[logical_name]:
            raise LabError("Pulumi resource name does not match the active lab run")
        labels = _state_label_map(inputs.get("labels"))
        if labels is None or labels.get("anitrend.platform.run-id") != run_id or labels.get("anitrend.platform.resource") != label_role:
            raise LabError("Pulumi resource labels do not identify the active lab run")
        observed.append({"type": resource_type, "name": resource_name})
    tracked_resources = {(resource["type"], resource["name"]) for resource in observed}
    for resource_type, (logical_name, _) in roles.items():
        resource_name = names[logical_name]
        if (resource_type, resource_name) in tracked_resources:
            continue
        if _docker_inspected_resource(readiness["docker_context"], resource_type, resource_name) is not None:
            raise LabError("untracked Docker resource exists outside the Pulumi lab state")
    return observed


def _docker_inspected_resource(
    context: str,
    resource_type: str,
    name: str,
) -> Optional[Dict[str, Any]]:
    if resource_type == "docker:index/container:Container":
        arguments = ["inspect", "--type", "container", "--format", "{{json .}}", name]
    elif resource_type == "docker:index/network:Network":
        arguments = ["network", "inspect", "--format", "{{json .}}", name]
    elif resource_type == "docker:index/volume:Volume":
        arguments = ["volume", "inspect", "--format", "{{json .}}", name]
    else:
        return None
    result = _run_result(_docker_command(context, *arguments))
    if result.returncode != 0:
        message = result.stderr.lower()
        if "no such" in message or "not found" in message or "does not exist" in message:
            return None
        raise LabError("could not verify an owned Docker resource")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise LabError("Docker returned invalid resource inspection data") from error
    if not isinstance(value, dict):
        raise LabError("Docker resource inspection data must be an object")
    return value


def _verify_live_resource_owner(
    resource_type: str,
    value: Dict[str, Any],
    run_id: str,
) -> None:
    labels = value.get("Config", {}).get("Labels") if resource_type == "docker:index/container:Container" else value.get("Labels")
    label_map = _state_label_map(labels)
    if (
        label_map is None
        or label_map.get("anitrend.platform.managed-by") != "pulumi"
        or label_map.get("anitrend.platform.environment") != "lab"
        or label_map.get("anitrend.platform.run-id") != run_id
    ):
        raise LabError("refusing to remove a Docker resource without matching lab ownership labels")


def _lab_down(environment: str, repo_root: Path, requested_run_id: Optional[str]) -> None:
    run_id, stack_name, run_dir, active_path = _read_active_run(repo_root, requested_run_id)
    readiness = _doctor(environment, repo_root)
    manifest = _read_manifest(run_dir, run_id)
    passphrase = _read_text(run_dir / "passphrase", "lab state passphrase")
    _pulumi_login(repo_root, run_dir, passphrase)
    _pulumi_select_stack(repo_root, run_dir, passphrase, stack_name)

    resources = _pulumi_resource_inventory(repo_root, run_dir, passphrase, stack_name, run_id, manifest, readiness)
    docker_resources = [resource for resource in resources if resource["type"].startswith("docker:index/")]
    for resource in docker_resources:
        inspected = _docker_inspected_resource(readiness["docker_context"], resource["type"], resource["name"])
        if inspected is not None:
            _verify_live_resource_owner(resource["type"], inspected, run_id)

    _pulumi(
        repo_root,
        run_dir,
        passphrase,
        ["destroy", "--yes", "--non-interactive", "--stack", stack_name],
    )
    for resource in docker_resources:
        if _docker_inspected_resource(readiness["docker_context"], resource["type"], resource["name"]) is not None:
            raise LabError("a Pulumi-owned lab resource remained after destroy")
    _pulumi(repo_root, run_dir, passphrase, ["stack", "rm", stack_name, "--yes", "--non-interactive"])

    project_stack_file = repo_root / "infra/pulumi/docker" / ("Pulumi." + stack_name + ".yaml")
    if project_stack_file.is_symlink():
        raise LabError("refusing to remove a symlink at the generated Pulumi stack config path")
    project_stack_file.unlink(missing_ok=True)
    manifest["cleanup_status"] = "pass"
    manifest["pulumi_stack_created"] = False
    manifest["last_operation"] = "down"
    _write_json(run_dir / "manifest.json", manifest)

    for owned_path in (run_dir / "backend", run_dir / "pulumi-home", run_dir / "ssh"):
        if owned_path.is_symlink():
            raise LabError("refusing to remove a symlink from the lab state directory")
        if owned_path.exists():
            shutil.rmtree(owned_path, ignore_errors=False)
    passphrase_path = run_dir / "passphrase"
    if passphrase_path.is_symlink():
        raise LabError("refusing to remove a symlink in the lab state directory")
    passphrase_path.unlink(missing_ok=True)
    active_path.unlink(missing_ok=True)
    print("platform-lab-down=pass")
    print("run_id=" + run_id)
    print("pulumi_stack=" + stack_name)
    print("pulumi_owned_resources_removed=yes")
    print("ssh_private_key_removed=yes")


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and run the isolated local Docker platform lab")
    subparsers = parser.add_subparsers(dest="command", required=True)
    commands = {
        "doctor": "read-only lab prerequisite and safety report",
        "up": "create or resume the isolated Pulumi Docker lab",
        "test": "verify lab resources, SSH access, and a controlled update",
        "down": "destroy only resources in the active lab Pulumi stack",
        "preview": "show a non-mutating preview for the active local Docker lab stack",
    }
    for name, description in commands.items():
        command = subparsers.add_parser(name, help=description)
        command.add_argument("--environment", required=True, choices=ENVIRONMENTS)
        command.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
        if name != "doctor":
            command.add_argument("--run-id")
    return parser


def main(arguments: Optional[Sequence[str]] = None) -> int:
    parser = _argument_parser()
    options = parser.parse_args(arguments)
    repo_root = options.repo_root.resolve()
    try:
        if options.command == "doctor":
            readiness = _doctor(options.environment, repo_root)
            print("\n".join(readiness["report"]))
        else:
            with _lifecycle_lock(repo_root):
                if options.command == "up":
                    _lab_up(options.environment, repo_root, options.run_id)
                elif options.command == "test":
                    _lab_test(options.environment, repo_root, options.run_id)
                elif options.command == "preview":
                    _lab_preview(options.environment, repo_root, options.run_id)
                else:
                    _lab_down(options.environment, repo_root, options.run_id)
        return 0
    except LabError as error:
        print("error: " + str(error), file=sys.stderr)
        return 2
    except OSError:
        print("error: a local lab filesystem operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
