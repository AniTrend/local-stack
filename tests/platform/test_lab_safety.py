from __future__ import annotations

import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Optional, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_CLI = REPO_ROOT / "tools" / "platform" / "lab.py"
PRODUCTION_SECRET = "fixture-only-secret-canary"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def make_fake_toolchain(tmp_path: Path, endpoint: str) -> Tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    docker_log = tmp_path / "docker-commands.log"
    _write_executable(
        bin_dir / "docker",
        textwrap.dedent(
            f"""\
            #!/bin/sh
            printf '%s\\n' "$*" >> "$PLATFORM_TEST_DOCKER_LOG"
            case "$*" in
              *"context inspect"*) printf '{{"Host":"%s"}}\\n' "$PLATFORM_TEST_ENDPOINT" ;;
              *"compose version"*) printf 'Docker Compose version v2.39.1\\n' ;;
              *"version"*) printf '{{"client_version":"29.9.1","server_version":"29.9.1"}}\\n' ;;
              *"info"*) if [ "$PLATFORM_TEST_DOCKER_FAIL_INFO" = "1" ]; then exit 1; fi; printf '{{"operating_system":"Ubuntu 24.04 LTS","architecture":"x86_64","swarm_state":"inactive","swarm_manager":false,"cpu_count":4,"memory_total_bytes":8589934592}}\\n' ;;
              *) printf 'unexpected Docker query\\n' >&2; exit 64 ;;
            esac
            """
        ),
    )
    tool_outputs = {
        "node": "v24.22.1",
        "npm": "11.19.1",
        "pulumi": "v3.272.0",
        "python3.14": "Python 3.14.9",
        "ansible-playbook": "ansible-playbook [core 2.21.5]",
        "ansible-galaxy": "ansible-galaxy",
        "molecule": "molecule 26.10.0",
        "ssh-keygen": "OpenSSH_9.9p1",
    }
    for command, output in tool_outputs.items():
        if command == "pulumi":
            body = "#!/bin/sh\nif [ \"$1\" = \"version\" ]; then printf 'v3.272.0\\n'; else printf '%s\\n' \"$*\" >> \"$PLATFORM_TEST_PULUMI_LOG\"; fi\n"
        elif command == "python3.14":
            body = "#!/bin/sh\ncase \"$*\" in *molecule-plugins*) printf '26.10.12\\n' ;; *jsonschema*) printf '4.25.1\\n' ;; *) printf 'Python 3.14.9\\n' ;; esac\n"
        elif command == "ansible-galaxy":
            body = "#!/bin/sh\nprintf '%s\\n' \"$PLATFORM_TEST_ANSIBLE_COLLECTIONS_JSON\"\n"
        else:
            body = "#!/bin/sh\nprintf '%s\\n' " + json.dumps(output) + "\n"
        _write_executable(bin_dir / command, body)
    return bin_dir, docker_log


def _run_cli(
    tmp_path: Path,
    command: str,
    *,
    environment: Optional[str] = "lab",
    endpoint: str = "unix:///var/run/docker.sock",
    context: Optional[str] = "fixture-local",
    allowlist: Optional[str] = "fixture-local",
    extra_env: Optional[dict[str, str]] = None,
    repo_root: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    bin_dir, docker_log = make_fake_toolchain(tmp_path, endpoint)
    pulumi_log = tmp_path / "pulumi-commands.log"
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["PLATFORM_TEST_ENDPOINT"] = endpoint
    collection_manifest_path = (repo_root / ".tools/platform/collections/ansible_collections").resolve()
    ansible_collections_path = repo_root / ".tools/platform/collections"
    env["PLATFORM_ANSIBLE_COLLECTIONS_PATH"] = str(ansible_collections_path)
    env["ANSIBLE_COLLECTIONS_PATH"] = str(ansible_collections_path)
    env["PLATFORM_TEST_ANSIBLE_COLLECTIONS_JSON"] = json.dumps(
        {
            str(collection_manifest_path): {
                "community.docker": {"version": "5.0.0"},
                "community.library_inventory_filtering_v1": {"version": "1.1.5"},
            }
        }
    )
    env["PLATFORM_TEST_DOCKER_LOG"] = str(docker_log)
    env["PLATFORM_TEST_PULUMI_LOG"] = str(pulumi_log)
    if context is not None:
        env["PLATFORM_DOCKER_CONTEXT"] = context
    else:
        env.pop("PLATFORM_DOCKER_CONTEXT", None)
    if allowlist is not None:
        env["PLATFORM_ALLOWED_DOCKER_CONTEXTS"] = allowlist
    else:
        env.pop("PLATFORM_ALLOWED_DOCKER_CONTEXTS", None)
    if extra_env:
        env.update(extra_env)
    args = [sys.executable, str(LAB_CLI), command, "--repo-root", str(repo_root)]
    if environment is not None:
        args.extend(["--environment", environment])
    result = subprocess.run(args, text=True, capture_output=True, env=env, check=False)
    result.test_docker_log = docker_log
    result.test_pulumi_log = pulumi_log
    return result


def run_doctor(
    tmp_path: Path,
    *,
    environment: Optional[str] = "lab",
    endpoint: str = "unix:///var/run/docker.sock",
    context: Optional[str] = "fixture-local",
    allowlist: Optional[str] = "fixture-local",
    extra_env: Optional[dict[str, str]] = None,
    repo_root: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        tmp_path,
        "doctor",
        environment=environment,
        endpoint=endpoint,
        context=context,
        allowlist=allowlist,
        extra_env=extra_env,
        repo_root=repo_root,
    )


def run_lab_command(
    tmp_path: Path,
    command: str,
    *,
    environment: Optional[str] = "lab",
    endpoint: str = "unix:///var/run/docker.sock",
    context: Optional[str] = "fixture-local",
    allowlist: Optional[str] = "fixture-local",
    extra_env: Optional[dict[str, str]] = None,
    repo_root: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        tmp_path,
        command,
        environment=environment,
        endpoint=endpoint,
        context=context,
        allowlist=allowlist,
        extra_env=extra_env,
        repo_root=repo_root,
    )


def test_doctor_requires_explicit_environment_before_docker(tmp_path: Path):
    result = run_doctor(tmp_path, environment=None, context=None, allowlist=None)

    assert result.returncode != 0
    assert "--environment" in result.stderr
    assert not result.test_docker_log.exists()

def test_doctor_requires_explicit_context_and_allowlist_before_docker(tmp_path: Path):
    result = run_doctor(tmp_path, context=None, allowlist=None)

    assert result.returncode != 0
    assert "PLATFORM_DOCKER_CONTEXT" in result.stderr
    assert not result.test_docker_log.exists()

def test_lab_up_rejects_production_before_docker_or_pulumi(tmp_path: Path):
    result = run_lab_command(tmp_path, "up", environment="production")

    assert result.returncode != 0
    assert "ENV=lab" in result.stderr
    assert not result.test_docker_log.exists()
    assert not result.test_pulumi_log.exists()


def test_lab_up_refuses_remote_daemon_before_pulumi(tmp_path: Path):
    endpoint = "ssh://fixture-user:fixture-password@remote.invalid:22"
    result = run_lab_command(tmp_path, "up", endpoint=endpoint)

    assert result.returncode != 0
    assert "local Docker endpoint" in result.stderr
    assert endpoint not in result.stderr
    assert not result.test_pulumi_log.exists()

def test_lab_down_without_active_run_never_invokes_pulumi(tmp_path: Path):
    result = run_lab_command(tmp_path, "down", repo_root=tmp_path)

    assert result.returncode != 0
    assert "active lab run" in result.stderr.lower()
    assert not result.test_pulumi_log.exists()


def test_doctor_rejects_production_environment_before_docker(tmp_path: Path):
    result = run_doctor(tmp_path, environment="production")

    assert result.returncode != 0
    assert "ENV=lab" in result.stderr
    assert not result.test_docker_log.exists()


def test_doctor_rejects_unallowlisted_local_context_before_daemon_queries(tmp_path: Path):
    result = run_doctor(tmp_path, context="fixture-local", allowlist="other-local")

    assert result.returncode != 0
    assert "PLATFORM_ALLOWED_DOCKER_CONTEXTS" in result.stderr
    assert not result.test_docker_log.exists()

def test_doctor_rejects_production_named_context_before_inspecting_it(tmp_path: Path):
    result = run_doctor(tmp_path, context="production", allowlist="production")

    assert result.returncode != 0
    assert "production" in result.stderr.lower()
    assert not result.test_docker_log.exists()


def test_doctor_rejects_missing_daemon_without_mutating_it(tmp_path: Path):
    result = run_doctor(tmp_path, extra_env={"PLATFORM_TEST_DOCKER_FAIL_INFO": "1"})

    assert result.returncode != 0
    assert "Docker Engine API or Compose is unavailable" in result.stderr
    commands = result.test_docker_log.read_text(encoding="utf-8").splitlines()
    assert any(" info " in f" {command} " for command in commands)
    assert all("prune" not in command.lower() and "swarm init" not in command.lower() for command in commands)


def test_doctor_rejects_missing_pinned_tool(tmp_path: Path):
    result = run_doctor(tmp_path, extra_env={"PLATFORM_NODE_BIN": "missing-platform-node"})

    assert result.returncode != 0
    assert "required local executable" in result.stderr
    assert "platform-doctor=pass" not in result.stdout


def test_doctor_reports_host_daemon_and_pinned_runtime_facts(tmp_path: Path):
    result = run_doctor(tmp_path)

    assert result.returncode == 0, result.stderr
    assert f"host_os={platform.system()}" in result.stdout
    assert f"host_architecture={platform.machine()}" in result.stdout
    assert "docker_os=Ubuntu 24.04 LTS" in result.stdout
    assert "docker_architecture=x86_64" in result.stdout
    assert "npm_version=11.19.1" in result.stdout
    assert "compose_version=2.39.1" in result.stdout
    assert "jsonschema_version=4.25.1" in result.stdout
    assert "execution_mode=" in result.stdout


def test_doctor_rejects_remote_context_without_echoing_endpoint(tmp_path: Path):
    endpoint = "ssh://fixture-user:fixture-password@remote.invalid:22"
    result = run_doctor(tmp_path, endpoint=endpoint, allowlist="fixture-local")

    assert result.returncode != 0
    assert "local Docker endpoint" in result.stderr
    assert endpoint not in result.stderr
    commands = result.test_docker_log.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 1
    assert "context inspect" in commands[0]


def test_doctor_refuses_cloud_credentials_without_printing_values(tmp_path: Path):
    result = run_doctor(
        tmp_path,
        extra_env={"HCLOUD_TOKEN": PRODUCTION_SECRET},
    )

    assert result.returncode != 0
    assert "production credentials" in result.stderr.lower()
    assert PRODUCTION_SECRET not in result.stderr
    assert not result.test_docker_log.exists()


def test_doctor_accepts_only_fully_pinned_local_toolchain(tmp_path: Path):
    result = run_doctor(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "platform-doctor=pass" in result.stdout
    assert "fixture-local" in result.stdout
    assert "ansible_collection_community_docker_version=5.0.0" in result.stdout
    assert "ansible_collection_community_library_inventory_filtering_v1_version=1.1.5" in result.stdout
    assert "unix:///var/run/docker.sock" not in result.stdout
    commands = result.test_docker_log.read_text(encoding="utf-8").splitlines()
    assert all("prune" not in command.lower() and "swarm init" not in command.lower() for command in commands)

def test_doctor_rejects_user_level_ansible_collection_only(tmp_path: Path):
    global_collection_json = {
        "/user/collections/ansible_collections": {
            "community.docker": {"version": "5.0.0"},
            "community.library_inventory_filtering_v1": {"version": "1.1.5"},
        }
    }
    result = run_doctor(
        tmp_path,
        extra_env={"PLATFORM_TEST_ANSIBLE_COLLECTIONS_JSON": json.dumps(global_collection_json)},
    )

    assert result.returncode != 0
    assert "community.docker" in result.stderr
    assert "5.0.0" in result.stderr


def test_doctor_rejects_wrong_pinned_ansible_collection_version(tmp_path: Path):
    collection_manifest_path = (
        REPO_ROOT / ".tools/platform/collections/ansible_collections"
    ).resolve()
    wrong_version_json = {
        str(collection_manifest_path): {
            "community.docker": {"version": "4.9.0"},
            "community.library_inventory_filtering_v1": {"version": "1.1.5"},
        }
    }
    result = run_doctor(
        tmp_path,
        extra_env={"PLATFORM_TEST_ANSIBLE_COLLECTIONS_JSON": json.dumps(wrong_version_json)},
    )

    assert result.returncode != 0
    assert "community.docker" in result.stderr
    assert "5.0.0" in result.stderr
def test_doctor_rejects_missing_required_ansible_collection(tmp_path: Path):
    result = run_doctor(
        tmp_path,
        extra_env={"PLATFORM_TEST_ANSIBLE_COLLECTIONS_JSON": "{}"},
    )

    assert result.returncode != 0
    assert "community.docker" in result.stderr
    assert "5.0.0" in result.stderr
    assert "platform-doctor=pass" not in result.stdout
