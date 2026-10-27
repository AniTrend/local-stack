#!/usr/bin/env python3
"""Run the local Docker Molecule scenario or authenticated Linux VM verification."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid
import platform
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO_ROOT / ".artifacts" / "platform"
MOLECULE_IMAGE = "anitrend/platform-ansible:ubuntu-24.04"
MOLECULE_OWNER_LABEL = "platform-owner"
MOLECULE_OWNER_VALUE = "anitrend-platform-ansible-test"
MOLECULE_RUN_LABEL = "platform-run-id"
FORMAT_CONFIRMATION = "I_UNDERSTAND_THIS_FORMATS_ONLY_DECLARED_EMPTY_VOLUMES"
RESERVED_CONTEXT = re.compile(
    r"(^|[-_.])(prod(?:uction)?|legacy|rehearsal|hcloud|hetzner|remote)(?:$|[-_.])",
    re.IGNORECASE,
)
TAILSCALE_TAG = re.compile(r"tag:[a-z0-9][a-z0-9-]{0,62}\Z")


class RunnerBlocked(ValueError):
    """A required external prerequisite is missing or unsafe."""


class RunnerFailed(RuntimeError):
    """A validation command failed after its prerequisites passed."""


@dataclass(frozen=True, slots=True)
class HostVerifyInputs:
    inventory: Path
    trust_bundle: Path
    trust_root: Path
    bootstrap_private_key: Path
    automation_public_key: str
    automation_private_key: Path
    tailscale_auth_key: str
    tailscale_tag: str
    allow_create_only_format: bool


def validate_docker_selection(
    context: str,
    allowlist: set[str],
    endpoint: str,
    endpoint_kind: str,
    swarm_state: str,
) -> str:
    if not context.strip():
        raise RunnerBlocked("PLATFORM_DOCKER_CONTEXT must explicitly select a local Docker context")
    if RESERVED_CONTEXT.search(context):
        raise RunnerBlocked("production and non-lab Docker contexts are refused")
    if not allowlist or context not in allowlist:
        raise RunnerBlocked("the selected Docker context is not explicitly allowlisted")
    if endpoint_kind != "local_unix" or not endpoint.startswith("unix://"):
        raise RunnerBlocked("ENV=lab requires an explicitly allowlisted local Docker endpoint")
    if swarm_state != "inactive":
        raise RunnerBlocked("the platform Ansible fixture refuses Docker daemons with Swarm enabled or unknown")
    return endpoint


def _private_key_path(name: str, value: str) -> Path:
    path = Path(value).expanduser()
    try:
        metadata = path.stat()
    except OSError as error:
        raise RunnerBlocked(f"{name} must name an existing private-key file") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise RunnerBlocked(f"{name} must name a regular private-key file")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RunnerBlocked(f"{name} must not be readable by group or other users")
    return path.resolve()


def _input_path(name: str, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        raise RunnerBlocked(f"{name} must name an existing file")
    return path.resolve()


def validate_host_verify_inputs(
    environment: str,
    tier: str,
    environ: Mapping[str, str],
) -> HostVerifyInputs:
    if environment != "lab" or tier != "vm":
        raise RunnerBlocked("platform-host-verify accepts only ENV=lab TIER=vm")

    required = (
        "PLATFORM_VM_INVENTORY",
        "PLATFORM_VM_TRUST_BUNDLE",
        "PLATFORM_VM_TRUST_ROOT",
        "PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY",
        "PLATFORM_VM_AUTOMATION_PUBLIC_KEY",
        "PLATFORM_VM_AUTOMATION_PRIVATE_KEY",
        "PLATFORM_TAILSCALE_AUTH_KEY",
        "PLATFORM_TAILSCALE_TAG",
    )
    missing = [name for name in required if not environ.get(name, "").strip()]
    if missing:
        raise RunnerBlocked("missing required VM inputs: " + ", ".join(missing))

    automation_public_key = environ["PLATFORM_VM_AUTOMATION_PUBLIC_KEY"].strip()
    if (
        not automation_public_key.startswith("ssh-ed25519 ")
        or any(character in automation_public_key for character in ("\0", "\n", "\r"))
    ):
        raise RunnerBlocked("PLATFORM_VM_AUTOMATION_PUBLIC_KEY must be one single-line Ed25519 public key")

    tailscale_tag = environ["PLATFORM_TAILSCALE_TAG"].strip()
    if TAILSCALE_TAG.fullmatch(tailscale_tag) is None:
        raise RunnerBlocked("PLATFORM_TAILSCALE_TAG must be one approved tag: value")
    tailscale_auth_key = environ["PLATFORM_TAILSCALE_AUTH_KEY"]
    if any(character in tailscale_auth_key for character in ("\0", "\n", "\r")):
        raise RunnerBlocked("PLATFORM_TAILSCALE_AUTH_KEY must be a single-line value")

    trust_bundle = _input_path("PLATFORM_VM_TRUST_BUNDLE", environ["PLATFORM_VM_TRUST_BUNDLE"])
    trust_root = _input_path("PLATFORM_VM_TRUST_ROOT", environ["PLATFORM_VM_TRUST_ROOT"])
    if trust_bundle == trust_root:
        raise RunnerBlocked("the SSH trust root must be independent of the signed trust bundle")

    return HostVerifyInputs(
        inventory=_input_path("PLATFORM_VM_INVENTORY", environ["PLATFORM_VM_INVENTORY"]),
        trust_bundle=trust_bundle,
        trust_root=trust_root,
        bootstrap_private_key=_private_key_path(
            "PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY",
            environ["PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY"],
        ),
        automation_public_key=automation_public_key,
        automation_private_key=_private_key_path(
            "PLATFORM_VM_AUTOMATION_PRIVATE_KEY",
            environ["PLATFORM_VM_AUTOMATION_PRIVATE_KEY"],
        ),
        tailscale_auth_key=tailscale_auth_key,
        tailscale_tag=tailscale_tag,
        allow_create_only_format=(
            environ.get("PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT", "") == FORMAT_CONFIRMATION
        ),
    )


def _import_lab_helpers():
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from tools.platform import lab

    return lab


def _reject_cloud_credentials(environ: Mapping[str, str], lab) -> None:
    present = [name for name in lab.FORBIDDEN_CREDENTIAL_ENV if environ.get(name)]
    if present:
        raise RunnerBlocked("refusing to run with cloud or production credentials in the environment")


def _tool_path(environ: Mapping[str, str], name: str, default: str) -> str:
    value = environ.get(name, default)
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    rooted_path = REPO_ROOT / path
    if path.parent != Path(".") and rooted_path.exists():
        return str(rooted_path.resolve())
    return value

def _project_collections_path(environ: Mapping[str, str]) -> Path:
    configured = Path(environ.get("PLATFORM_ANSIBLE_COLLECTIONS_PATH", ".tools/platform/collections")).expanduser()
    if not configured.is_absolute():
        configured = REPO_ROOT / configured
    resolved = configured.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as error:
        raise RunnerBlocked("Ansible collections must be installed inside the repository") from error
    return resolved


def _ansible_environment(environ: Mapping[str, str]) -> dict[str, str]:
    result = dict(environ)
    result["ANSIBLE_CONFIG"] = str(REPO_ROOT / "ansible" / "ansible.cfg")
    result["ANSIBLE_ROLES_PATH"] = str(REPO_ROOT / "ansible" / "roles")
    result["ANSIBLE_COLLECTIONS_PATH"] = str(_project_collections_path(environ))
    result["ANSIBLE_HOST_KEY_CHECKING"] = "True"
    tool_directories = [str(Path(sys.executable).resolve().parent)]
    for name, default in (
        ("PLATFORM_ANSIBLE_BIN", "ansible-playbook"),
        ("PLATFORM_MOLECULE_BIN", "molecule"),
        ("PLATFORM_ANSIBLE_GALAXY_BIN", "ansible-galaxy"),
    ):
        executable = Path(_tool_path(environ, name, default))
        if executable.is_absolute() and str(executable.parent) not in tool_directories:
            tool_directories.append(str(executable.parent))
    result["PATH"] = os.pathsep.join([*tool_directories, result.get("PATH", "")])
    return result


def _project_collection_versions(collections_path: Path, names: Sequence[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for collection_name in names:
        namespace, name = collection_name.split(".", 1)
        manifest_path = collections_path / "ansible_collections" / namespace / name / "MANIFEST.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        collection_info = manifest.get("collection_info")
        if isinstance(collection_info, dict) and isinstance(collection_info.get("version"), str):
            versions[collection_name] = collection_info["version"]
    return versions


def _validate_ansible_toolchain(environ: Mapping[str, str], lab) -> dict[str, object]:
    expected_python = (REPO_ROOT / ".python-version").read_text(encoding="utf-8").strip()
    actual_python = platform.python_version()
    if actual_python != expected_python:
        raise RunnerBlocked("the platform Ansible command requires the pinned Python version")

    requirements = lab._locked_versions(REPO_ROOT / "tools" / "platform" / "requirements.lock")
    child_environment = _ansible_environment(environ)
    ansible_playbook = _tool_path(environ, "PLATFORM_ANSIBLE_BIN", "ansible-playbook")
    molecule = _tool_path(environ, "PLATFORM_MOLECULE_BIN", "molecule")
    ansible_version_output = _run_capture(
        [ansible_playbook, "--version"],
        cwd=REPO_ROOT,
        environ=child_environment,
    )
    molecule_version_output = _run_capture(
        [molecule, "--version"],
        cwd=REPO_ROOT,
        environ=child_environment,
    )
    ansible_match = re.search(r"\[core ([0-9.]+)\]", ansible_version_output.stdout)
    molecule_match = re.search(r"\bmolecule\s+([0-9.]+)", molecule_version_output.stdout)
    if ansible_version_output.returncode != 0 or ansible_match is None:
        raise RunnerBlocked("the pinned Ansible Core executable is unavailable")
    if molecule_version_output.returncode != 0 or molecule_match is None:
        raise RunnerBlocked("the pinned Molecule executable is unavailable")

    actual_versions = {
        "ansible-core": ansible_match.group(1),
        "molecule": molecule_match.group(1),
    }
    for distribution, lock_name in (
        ("molecule-plugins", "molecule-plugins"),
        ("PyYAML", "pyyaml"),
        ("jsonschema", "jsonschema"),
        ("cryptography", "cryptography"),
    ):
        try:
            actual_versions[lock_name] = package_version(distribution)
        except PackageNotFoundError as error:
            raise RunnerBlocked(f"the pinned Python package {distribution} is unavailable") from error

    mismatched = [
        name
        for name, version_value in actual_versions.items()
        if requirements.get(name) != version_value
    ]
    if mismatched:
        raise RunnerBlocked("pinned Ansible tool versions are missing or mismatched: " + ", ".join(sorted(mismatched)))

    collections_path = _project_collections_path(environ)

    required_collections = lab._locked_ansible_collections(REPO_ROOT / "ansible" / "requirements.yml")
    installed_collections = _project_collection_versions(collections_path, sorted(required_collections))
    mismatched_collections = [
        f"{name}=={version_value}"
        for name, version_value in sorted(required_collections.items())
        if installed_collections.get(name) != version_value
    ]
    if mismatched_collections:
        raise RunnerBlocked(
            "required project-local Ansible collections are missing or mismatched: "
            + ", ".join(mismatched_collections)
        )

    return {
        "python": actual_python,
        "ansible-core": actual_versions["ansible-core"],
        "molecule": actual_versions["molecule"],
        "molecule-plugins": actual_versions["molecule-plugins"],
        "collections": {
            name: installed_collections[name]
            for name in sorted(required_collections)
        },
    }


def _run_visible(command: Sequence[str], *, cwd: Path, environ: Mapping[str, str]) -> None:
    try:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(environ),
            check=False,
        )
    except OSError as error:
        raise RunnerFailed(f"could not start {Path(command[0]).name}") from error
    if result.returncode != 0:
        raise RunnerFailed(f"{Path(command[0]).name} exited with status {result.returncode}")


def _syntax_check_playbooks(environ: Mapping[str, str]) -> None:
    ansible_playbook = _tool_path(environ, "PLATFORM_ANSIBLE_BIN", "ansible-playbook")
    playbooks = (
        "bootstrap-host.yml",
        "fresh-host.yml",
        "upgrade.yml",
        "reconnect-verify.yml",
        "vm-verify.yml",
        "storage-identity-safety-verify.yml",
        "storage-safety-verify.yml",
    )
    for playbook in playbooks:
        _run_visible(
            [
                ansible_playbook,
                "--inventory",
                "platform_target,",
                "--syntax-check",
                str(REPO_ROOT / "ansible" / playbook),
            ],
            cwd=REPO_ROOT / "ansible",
            environ=environ,
        )


def run_container_test(environment: str, environ: Mapping[str, str]) -> None:
    if environment != "lab":
        raise RunnerBlocked("platform-ansible-test accepts only ENV=lab")
    lab = _import_lab_helpers()
    _reject_cloud_credentials(environ, lab)

    context = environ.get("PLATFORM_DOCKER_CONTEXT", "").strip()
    allowlist = lab._parse_context_allowlist(environ.get("PLATFORM_ALLOWED_DOCKER_CONTEXTS"))
    if RESERVED_CONTEXT.search(context):
        raise RunnerBlocked("production and non-lab Docker contexts are refused")
    if not context or not allowlist or context not in allowlist:
        raise RunnerBlocked("PLATFORM_DOCKER_CONTEXT must be explicitly allowlisted")

    try:
        endpoint, endpoint_kind = lab._docker_context_endpoint(context)
        swarm_state = lab._run(lab._docker_command(context, "info", "--format", "{{.Swarm.LocalNodeState}}")).strip()
    except lab.LabError as error:
        raise RunnerBlocked("the selected local Docker daemon is unavailable") from error
    docker_host = validate_docker_selection(context, allowlist, endpoint, endpoint_kind, swarm_state)

    child_environment = _ansible_environment(environ)
    child_environment["DOCKER_HOST"] = docker_host
    for name in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "DOCKER_API_VERSION", "DOCKER_CONFIG"):
        child_environment.pop(name, None)
    _validate_ansible_toolchain(child_environment, lab)

    molecule_run_id = _new_run_id()
    molecule_instance_name = _molecule_instance_name(molecule_run_id)
    child_environment["PLATFORM_MOLECULE_RUN_ID"] = molecule_run_id
    child_environment["PLATFORM_MOLECULE_INSTANCE_NAME"] = molecule_instance_name
    _preflight_molecule_container(
        lab,
        context,
        molecule_instance_name,
        molecule_run_id,
        child_environment,
    )

    _syntax_check_playbooks(child_environment)

    scenario_directory = REPO_ROOT / "ansible" / "molecule" / "default"
    dockerfile = scenario_directory / "Dockerfile.j2"
    docker_command = lab._docker_command(
        context,
        "build",
        "--network",
        "host",
        "--no-cache",
        "--file",
        str(dockerfile),
        "--tag",
        MOLECULE_IMAGE,
        str(scenario_directory),
    )
    _run_visible(docker_command, cwd=REPO_ROOT, environ=child_environment)

    molecule = _tool_path(child_environment, "PLATFORM_MOLECULE_BIN", "molecule")
    _run_visible(
        [molecule, "test", "-s", "default"],
        cwd=REPO_ROOT / "ansible",
        environ=child_environment,
    )


def _run_capture(
    command: Sequence[str],
    *,
    cwd: Path,
    environ: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(environ),
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        raise RunnerFailed(f"could not start {Path(command[0]).name}") from error


def _recap_changed_counts(output: str) -> list[int]:
    recap = re.compile(
        r"^[^\s:]+\s*:\s+ok=\d+\s+changed=(\d+)\s+unreachable=\d+\s+failed=\d+",
        re.MULTILINE,
    )
    return [int(match.group(1)) for match in recap.finditer(output)]


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _write_manifest(path: Path, value: dict[str, object]) -> None:
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%sz").lower() + "-" + uuid.uuid4().hex[:8]

def _automation_connection_arguments(
    private_key: Path,
    extra_vars: Mapping[str, object] | None = None,
) -> list[str]:
    variables = dict(extra_vars or {})
    variables["ansible_user"] = "platform-automation"
    return [
        "--private-key",
        str(private_key),
        "--user",
        "platform-automation",
        "--extra-vars",
        json.dumps(variables, sort_keys=True, separators=(",", ":")),
    ]


def _molecule_instance_name(run_id: str) -> str:
    return f"platform-ansible-{run_id}-ubuntu-2404"


def _require_molecule_container_ownership(labels: object, run_id: str) -> None:
    if (
        not isinstance(labels, dict)
        or labels.get(MOLECULE_OWNER_LABEL) != MOLECULE_OWNER_VALUE
        or labels.get(MOLECULE_RUN_LABEL) != run_id
    ):
        raise RunnerBlocked("refusing to let Molecule destroy a container with mismatched ownership/run labels")


def _preflight_molecule_container(
    lab,
    context: str,
    instance_name: str,
    run_id: str,
    environ: Mapping[str, str],
) -> None:
    inspect_command = lab._docker_command(
        context,
        "container",
        "inspect",
        "--format",
        "{{json .Config.Labels}}",
        instance_name,
    )
    result = _run_capture(inspect_command, cwd=REPO_ROOT, environ=environ)
    if result.returncode != 0:
        if "No such object" in result.stderr or "No such container" in result.stderr:
            return
        raise RunnerBlocked("could not inspect the Molecule fixture before its destroy phase")
    try:
        labels = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RunnerBlocked("Molecule fixture ownership labels could not be parsed") from error
    _require_molecule_container_ownership(labels, run_id)


def _safe_command_display(name: str, playbook: str, connection: str) -> str:
    return f"ansible-playbook --inventory <generated> --private-key <{connection}> {playbook}"




def run_host_verify(environment: str, tier: str, environ: Mapping[str, str]) -> Path:
    lab = _import_lab_helpers()
    _reject_cloud_credentials(environ, lab)
    inputs = validate_host_verify_inputs(environment, tier, environ)
    safe_tool_environment = dict(environ)
    for name in (
        *lab.FORBIDDEN_CREDENTIAL_ENV,
        "PLATFORM_VM_INVENTORY",
        "PLATFORM_VM_TRUST_BUNDLE",
        "PLATFORM_VM_TRUST_ROOT",
        "PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY",
        "PLATFORM_VM_AUTOMATION_PUBLIC_KEY",
        "PLATFORM_VM_AUTOMATION_PRIVATE_KEY",
        "PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT",
        "PLATFORM_TAILSCALE_AUTH_KEY",
        "PLATFORM_TAILSCALE_TAG",
    ):
        safe_tool_environment.pop(name, None)
    tool_environment = _ansible_environment(safe_tool_environment)
    tool_versions = _validate_ansible_toolchain(tool_environment, lab)

    run_id = _new_run_id()
    run_directory = ARTIFACT_ROOT / run_id
    work_directory = run_directory / "ansible"
    run_directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    work_directory.mkdir(mode=0o700)

    manifest: dict[str, object] = {
        "schema_version": "anitrend.platform.host-verify.v1",
        "run_id": run_id,
        "environment": environment,
        "tier": tier,
        "result": "fail",
        "tested_commit": _git_revision(),
        "inventory": {},
        "steps": [],
        "cleanup_status": "pending",
        "tool_versions": tool_versions,
    }
    child_environment = _ansible_environment(environ)
    child_environment["PLATFORM_VM_AUTOMATION_PUBLIC_KEY"] = inputs.automation_public_key
    child_environment["PLATFORM_TAILSCALE_AUTH_KEY"] = inputs.tailscale_auth_key
    child_environment["PLATFORM_TAILSCALE_TAG"] = inputs.tailscale_tag
    child_environment["PLATFORM_RUN_ID"] = run_id
    child_environment["PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT"] = (
        FORMAT_CONFIRMATION if inputs.allow_create_only_format else ""
    )

    output_directory = work_directory / "inventory"
    inventory_tool = REPO_ROOT / "tools" / "platform" / "ansible_inventory.py"
    adapter_command = [
        sys.executable,
        str(inventory_tool),
        "--inventory",
        str(inputs.inventory),
        "--trust-bundle",
        str(inputs.trust_bundle),
        "--trust-root",
        str(inputs.trust_root),
        "--environment",
        environment,
        "--output-dir",
        str(output_directory),
    ]
    completed_steps: list[dict[str, object]] = []

    def run_step(
        name: str,
        command: Sequence[str],
        *,
        playbook: str,
        connection: str,
        zero_changes: bool = False,
    ) -> None:
        result = _run_capture(command, cwd=REPO_ROOT / "ansible", environ=child_environment)
        step: dict[str, object] = {
            "name": name,
            "command": _safe_command_display(name, playbook, connection),
            "exit_code": result.returncode,
            "state": "pass" if result.returncode == 0 else "fail",
        }
        if zero_changes:
            counts = _recap_changed_counts(result.stdout)
            step["changed_counts"] = counts
            if not counts or any(count != 0 for count in counts):
                step["state"] = "fail"
                step["error"] = "second host convergence reported changes"
        for version_name, pattern in (
            ("tailscale", r"platform-tailscale-version=([0-9]+(?:\.[0-9]+){2})"),
            ("docker-client", r"platform-docker-version=([0-9][A-Za-z0-9.+-]*)"),
        ):
            version_match = re.search(pattern, result.stdout)
            if version_match is not None:
                tool_versions[version_name] = version_match.group(1)
        if name == "systemd_firewall_tailscale_mount_reboot_verification":
            missing_versions = [
                version_name
                for version_name in ("tailscale", "docker-client")
                if version_name not in tool_versions
            ]
            if missing_versions:
                step["state"] = "fail"
                step["error"] = "VM tool version evidence is missing: " + ", ".join(missing_versions)
        completed_steps.append(step)
        manifest["steps"] = completed_steps
        if result.returncode != 0 or step["state"] != "pass":
            raise RunnerFailed(f"host verification step {name} failed; exit={result.returncode}")

    try:
        adapter_result = _run_capture(adapter_command, cwd=REPO_ROOT, environ=child_environment)
        completed_steps.append(
            {
                "name": "validate_inventory_and_trust",
                "command": "ansible_inventory.py validates the versioned inventory and signed host trust",
                "exit_code": adapter_result.returncode,
                "state": "pass" if adapter_result.returncode == 0 else "fail",
            }
        )
        manifest["steps"] = completed_steps
        if adapter_result.returncode != 0:
            raise RunnerFailed("the supplied inventory or authenticated host trust was rejected")

        generated_inventory_path = output_directory / "inventory.json"
        generated_inventory = json.loads(generated_inventory_path.read_text(encoding="utf-8"))
        source_inventory = json.loads(inputs.inventory.read_text(encoding="utf-8"))
        host_variables = generated_inventory["all"]["children"]["platform_target"]["hosts"]["platform-target"]
        if any(
            volume.get("format_policy") == "create-only"
            for volume in host_variables["platform_volumes"]
        ) and not inputs.allow_create_only_format:
            raise RunnerBlocked(
                "inventory permits create-only storage formatting; set the exact PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT confirmation"
            )
        manifest["inventory"] = {
            "schema_version": host_variables["platform_inventory_schema_version"],
            "provider": host_variables["platform_provider"],
            "stack_identity": host_variables["platform_stack_identity"],
            "host_identity_ref": host_variables["platform_host_identity_ref"],
            "architecture": host_variables["platform_architecture"],
            "os_image": host_variables["platform_os_image"],
            "image_ref": source_inventory["image_ref"],
            "native_execution": source_inventory["native_execution"],
            "volume_count": len(host_variables["platform_volumes"]),
            "create_only_format": inputs.allow_create_only_format,
        }

        ansible_playbook = _tool_path(child_environment, "PLATFORM_ANSIBLE_BIN", "ansible-playbook")
        inventory_argument = str(generated_inventory_path)
        automation_connection = _automation_connection_arguments(inputs.automation_private_key)
        automation_recovery_connection = _automation_connection_arguments(
            inputs.automation_private_key,
            {"platform_firewall_recovery_access_verified": True},
        )
        bootstrap_connection = ["--private-key", str(inputs.bootstrap_private_key)]

        run_step(
            "bootstrap_automation_account",
            [ansible_playbook, "-i", inventory_argument, *bootstrap_connection, str(REPO_ROOT / "ansible" / "bootstrap-host.yml")],
            playbook="bootstrap-host.yml",
            connection="PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY",
        )
        run_step(
            "automation_ssh_reconnect_before_firewall",
            [ansible_playbook, "-i", inventory_argument, *automation_connection, str(REPO_ROOT / "ansible" / "reconnect-verify.yml")],
            playbook="reconnect-verify.yml",
            connection="PLATFORM_VM_AUTOMATION_PRIVATE_KEY",
        )
        run_step(
            "storage_device_identity_safety_checks",
            [
                ansible_playbook,
                "-i",
                inventory_argument,
                *automation_connection,
                str(REPO_ROOT / "ansible" / "storage-identity-safety-verify.yml"),
            ],
            playbook="storage-identity-safety-verify.yml",
            connection="PLATFORM_VM_AUTOMATION_PRIVATE_KEY",
        )
        run_step(
            "fresh_host_convergence",
            [
                ansible_playbook,
                "-i",
                inventory_argument,
                *automation_recovery_connection,
                str(REPO_ROOT / "ansible" / "fresh-host.yml"),
            ],
            playbook="fresh-host.yml",
            connection="PLATFORM_VM_AUTOMATION_PRIVATE_KEY",
        )
        run_step(
            "automation_ssh_reconnect_after_firewall",
            [ansible_playbook, "-i", inventory_argument, *automation_connection, str(REPO_ROOT / "ansible" / "reconnect-verify.yml")],
            playbook="reconnect-verify.yml",
            connection="PLATFORM_VM_AUTOMATION_PRIVATE_KEY",
        )
        run_step(
            "storage_safety_and_create_only_checks",
            [ansible_playbook, "-i", inventory_argument, *automation_connection, str(REPO_ROOT / "ansible" / "storage-safety-verify.yml")],
            playbook="storage-safety-verify.yml",
            connection="PLATFORM_VM_AUTOMATION_PRIVATE_KEY",
        )
        run_step(
            "systemd_firewall_tailscale_mount_reboot_verification",
            [ansible_playbook, "-i", inventory_argument, *automation_connection, str(REPO_ROOT / "ansible" / "vm-verify.yml")],
            playbook="vm-verify.yml",
            connection="PLATFORM_VM_AUTOMATION_PRIVATE_KEY",
        )
        run_step(
            "second_host_convergence",
            [
                ansible_playbook,
                "-i",
                inventory_argument,
                *automation_recovery_connection,
                str(REPO_ROOT / "ansible" / "fresh-host.yml"),
            ],
            playbook="fresh-host.yml",
            connection="PLATFORM_VM_AUTOMATION_PRIVATE_KEY",
            zero_changes=True,
        )
        manifest["result"] = "pass"
        manifest["cleanup_status"] = "pass"
    except RunnerBlocked as error:
        manifest["result"] = "blocked"
        manifest["error"] = str(error)
        raise
    except (RunnerFailed, OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        manifest["result"] = "fail"
        manifest["error"] = str(error) if isinstance(error, RunnerFailed) else "host verification evidence could not be collected"
        raise RunnerFailed(manifest["error"]) from error
    finally:
        shutil.rmtree(work_directory, ignore_errors=True)
        _write_manifest(run_directory / "manifest.json", manifest)

    return run_directory / "manifest.json"


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    container = subparsers.add_parser("container-test", help="run the local Docker Molecule scenario")
    container.add_argument("--environment", required=True, choices=("lab",))
    host = subparsers.add_parser("host-verify", help="run the authenticated full Linux VM scenario")
    host.add_argument("--environment", required=True, choices=("lab",))
    host.add_argument("--tier", required=True, choices=("vm",))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _argument_parser()
    options = parser.parse_args(argv)
    try:
        if options.command == "container-test":
            run_container_test(options.environment, os.environ)
            print("platform-ansible-test=pass")
            return 0
        manifest_path = run_host_verify(options.environment, options.tier, os.environ)
        print(f"platform-host-verify=pass evidence={manifest_path.relative_to(REPO_ROOT)}")
        return 0
    except RunnerBlocked as error:
        print(f"blocked: {error}", file=sys.stderr)
        return 2
    except (RunnerFailed, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
