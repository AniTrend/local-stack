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
    env["PLATFORM_NODE_BIN"] = str(bin_dir / "node")
    env["PLATFORM_NPM_BIN"] = str(bin_dir / "npm")
    env["PLATFORM_PULUMI_BIN"] = str(bin_dir / "pulumi")
    env["PLATFORM_PYTHON_BIN"] = str(bin_dir / "python3.14")
    env["PLATFORM_ANSIBLE_BIN"] = str(bin_dir / "ansible-playbook")
    env["PLATFORM_ANSIBLE_GALAXY_BIN"] = str(bin_dir / "ansible-galaxy")
    env["PLATFORM_MOLECULE_BIN"] = str(bin_dir / "molecule")
    env["PLATFORM_TEST_ENDPOINT"] = endpoint
    collection_manifest_path = (repo_root / ".tools/platform/collections/ansible_collections").resolve()
    ansible_collections_path = repo_root / ".tools/platform/collections"
    env["PLATFORM_ANSIBLE_COLLECTIONS_PATH"] = str(ansible_collections_path)
    env["ANSIBLE_COLLECTIONS_PATH"] = str(ansible_collections_path)
    env["PLATFORM_TEST_ANSIBLE_COLLECTIONS_JSON"] = json.dumps(
        {
            str(collection_manifest_path): {
                "community.docker": {"version": "5.0.0"},
                "ansible.posix": {"version": "2.2.2"},
                "community.general": {"version": "13.5.0"},
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


def test_lab_preview_without_active_run_fails_before_pulumi(tmp_path: Path):
    result = run_lab_command(tmp_path, "preview")

    assert result.returncode != 0
    assert "active lab run" in result.stderr.lower()
    assert not result.test_pulumi_log.exists()


@pytest.mark.parametrize(
    "existing_resource_type",
    [
        None,
        "docker:index/container:Container",
        "docker:index/network:Network",
        "docker:index/volume:Volume",
    ],
    ids=["no-run-resources", "orphan-container", "orphan-network", "orphan-volume"],
)
def test_empty_preapply_pulumi_state_is_cleanable_only_without_run_resources(
    tmp_path: Path,
    monkeypatch,
    existing_resource_type: Optional[str],
):
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    run_id = "20261025T123456Z-12345678"
    state = {
        "version": 3,
        "deployment": {
            "manifest": {"version": "v3.272.0"},
            "secrets_providers": {"type": "passphrase", "state": {"salt": "fixture"}},
            "metadata": {},
        },
    }
    inspected = []
    monkeypatch.setattr(lab_cli, "_pulumi", lambda *args: json.dumps(state))

    def inspect_resource(context, resource_type, name):
        inspected.append((resource_type, name))
        return {} if resource_type == existing_resource_type else None

    monkeypatch.setattr(lab_cli, "_docker_inspected_resource", inspect_resource)

    if existing_resource_type is None:
        inventory = lab_cli._pulumi_resource_inventory(
            tmp_path,
            tmp_path,
            "fixture-passphrase",
            "platform-lab-" + run_id,
            run_id,
            {"outputs": None, "pulumi_preview": "pending", "pulumi_up": "pending"},
            {
                "docker_context": "fixture-local",
                "docker_host": "unix:///var/run/docker.sock",
            },
        )
        assert inventory == []
        assert set(inspected) == {
            ("docker:index/container:Container", f"anitrend-platform-lab-{run_id}-ssh"),
            ("docker:index/network:Network", f"anitrend-platform-lab-{run_id}-network"),
            ("docker:index/volume:Volume", f"anitrend-platform-lab-{run_id}-config"),
        }
    else:
        with pytest.raises(lab_cli.LabError, match="untracked Docker resource"):
            lab_cli._pulumi_resource_inventory(
                tmp_path,
                tmp_path,
                "fixture-passphrase",
                "platform-lab-" + run_id,
                run_id,
                {"outputs": None, "pulumi_preview": "pending", "pulumi_up": "pending"},
                {
                    "docker_context": "fixture-local",
                    "docker_host": "unix:///var/run/docker.sock",
                },
            )


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
    assert "ansible_collection_ansible_posix_version=2.2.2" in result.stdout
    assert "ansible_collection_community_general_version=13.5.0" in result.stdout
    assert "unix:///var/run/docker.sock" not in result.stdout
    commands = result.test_docker_log.read_text(encoding="utf-8").splitlines()
    assert all("prune" not in command.lower() and "swarm init" not in command.lower() for command in commands)

def test_doctor_rejects_user_level_ansible_collection_only(tmp_path: Path):
    global_collection_json = {
        "/user/collections/ansible_collections": {
            "community.docker": {"version": "5.0.0"},
            "ansible.posix": {"version": "2.2.2"},
            "community.general": {"version": "13.5.0"},
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
            "ansible.posix": {"version": "2.2.2"},
            "community.general": {"version": "13.5.0"},
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


def test_pulumi_environment_isolates_docker_and_backend_selection(tmp_path: Path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setenv("DOCKER_CONTEXT", "production-remote")
    monkeypatch.setenv("DOCKER_HOST", "ssh://remote.invalid:22")
    monkeypatch.setenv("PULUMI_BACKEND_URL", "file:///tmp/unowned-backend")
    monkeypatch.setenv("PULUMI_HOME", "/tmp/unowned-pulumi-home")
    monkeypatch.setenv("PULUMI_CREDENTIALS_PATH", "/tmp/unowned-credentials")
    monkeypatch.setenv("PULUMI_CONFIG_PASSPHRASE_FILE", "/tmp/unowned-passphrase")
    monkeypatch.setenv("PULUMI_CREDENTIAL_STORE", "os")

    environment = lab_cli._pulumi_environment(run_dir, "fixture-passphrase")

    assert "DOCKER_CONTEXT" not in environment
    assert "DOCKER_HOST" not in environment
    assert environment["PULUMI_BACKEND_URL"] == "file://" + str((run_dir / "backend").resolve())
    assert environment["PULUMI_HOME"] == str((run_dir / "pulumi-home").resolve())
    assert "PULUMI_CREDENTIALS_PATH" not in environment
    assert "PULUMI_CONFIG_PASSPHRASE_FILE" not in environment
    assert environment["PULUMI_CREDENTIAL_STORE"] == "plaintext"

def test_project_relative_pulumi_binary_is_resolved_before_changing_directory(tmp_path: Path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    repo_root = tmp_path / "repo"
    project_dir = repo_root / "infra" / "pulumi" / "docker"
    project_dir.mkdir(parents=True)
    pulumi_binary = repo_root / ".tools" / "platform" / "bin" / "pulumi"
    pulumi_binary.parent.mkdir(parents=True)
    _write_executable(pulumi_binary, "#!/bin/sh\nprintf 'v3.272.0\\n'\n")
    monkeypatch.setenv("PLATFORM_PULUMI_BIN", ".tools/platform/bin/pulumi")

    result = lab_cli._pulumi(
        repo_root,
        repo_root / ".artifacts" / "platform" / "lab" / "run",
        "fixture-passphrase",
        ["version"],
    )

    assert result == "v3.272.0"


def test_source_fingerprint_changes_when_dirty_tracked_content_changes(tmp_path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo_root, check=True)
    source_file = repo_root / "infra" / "pulumi" / "docker" / "source.ts"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("export const value = 1;\n", encoding="utf-8")
    subprocess.run(["git", "add", "infra/pulumi/docker/source.ts"], cwd=repo_root, check=True)
    git_environment = os.environ.copy()
    git_environment.update(
        {
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "fixture source"],
        cwd=repo_root,
        env=git_environment,
        check=True,
    )

    original = lab_cli._source_metadata(repo_root)
    source_file.write_text("export const value = 2;\n", encoding="utf-8")
    modified = lab_cli._source_metadata(repo_root)

    assert original["commit"] == modified["commit"]
    assert original["worktree_clean"] is True
    assert modified["worktree_clean"] is False
    assert original["worktree_sha256"] != modified["worktree_sha256"]


def test_source_fingerprint_includes_untracked_file_contents(tmp_path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo_root, check=True)
    tracked_file = repo_root / "infra" / "pulumi" / "docker" / "tracked.ts"
    tracked_file.parent.mkdir(parents=True)
    tracked_file.write_text("export const tracked = true;\n", encoding="utf-8")
    subprocess.run(["git", "add", "infra/pulumi/docker/tracked.ts"], cwd=repo_root, check=True)
    git_environment = os.environ.copy()
    git_environment.update(
        {
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "fixture source"],
        cwd=repo_root,
        env=git_environment,
        check=True,
    )

    untracked_file = repo_root / "infra" / "pulumi" / "docker" / "untracked.ts"
    untracked_file.write_text("export const untracked = 1;\n", encoding="utf-8")
    first = lab_cli._source_metadata(repo_root)
    untracked_file.write_text("export const untracked = 2;\n", encoding="utf-8")
    second = lab_cli._source_metadata(repo_root)

    assert first["commit"] == second["commit"]
    assert first["worktree_sha256"] != second["worktree_sha256"]

    unrelated_file = repo_root / "private-note.txt"
    unrelated_file.write_text("not part of the lab source inputs\n", encoding="utf-8")
    unrelated = lab_cli._source_metadata(repo_root)

    assert unrelated["worktree_sha256"] == second["worktree_sha256"]


def test_source_snapshot_rejects_unknown_git_identity_on_resume(tmp_path: Path):
    import hashlib
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    repo_root = tmp_path / "source"
    repo_root.mkdir()
    unknown_source = {
        "commit": "unknown",
        "worktree_clean": False,
        "worktree_sha256": hashlib.sha256(b"unknown").hexdigest(),
    }

    with pytest.raises(lab_cli.LabError, match="Git source identity"):
        lab_cli._assert_source_snapshot(repo_root, {"source": unknown_source})


def test_lab_up_rejects_new_run_without_git_source_identity(tmp_path: Path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    repo_root = tmp_path / "source"
    repo_root.mkdir()
    run_id = "20261025T123456Z-12345678"
    artifact_root = repo_root / ".artifacts" / "platform" / "lab"
    run_dir = artifact_root / run_id
    monkeypatch.setattr(lab_cli, "_reserve_loopback_port", lambda: 44299)
    monkeypatch.setattr(
        lab_cli,
        "_create_ssh_key",
        lambda run_dir, run_id: (run_dir / "ssh" / "id_ed25519", "ssh-ed25519 AAAA fixture"),
    )
    monkeypatch.setattr(
        lab_cli,
        "_write_json",
        lambda path, value: path.write_text(json.dumps(value), encoding="utf-8"),
    )
    readiness = {
        "image_ref": "fixture@sha256:" + "a" * 64,
        "image_digest": "sha256:" + "a" * 64,
        "image_platform": "linux/amd64",
        "execution_mode": "native",
        "tool_versions": {},
    }

    with pytest.raises(lab_cli.LabError, match="Git source identity"):
        lab_cli._prepare_run(repo_root, run_id, readiness)

    assert not run_dir.exists()
    assert not (artifact_root / "active-run.json").exists()


def test_unrelated_worktree_change_does_not_block_source_resume(tmp_path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo_root, check=True)
    source_file = repo_root / "infra" / "pulumi" / "docker" / "source.ts"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("export const value = 1;\n", encoding="utf-8")
    subprocess.run(["git", "add", "infra/pulumi/docker/source.ts"], cwd=repo_root, check=True)
    git_environment = os.environ.copy()
    git_environment.update(
        {
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "fixture source"],
        cwd=repo_root,
        env=git_environment,
        check=True,
    )
    original_source = lab_cli._source_metadata(repo_root)
    assert original_source["worktree_clean"] is True

    (repo_root / "private-note.txt").write_text("unrelated worktree change\n", encoding="utf-8")
    current_source = lab_cli._source_metadata(repo_root)

    assert current_source["worktree_clean"] is False
    assert current_source["commit"] == original_source["commit"]
    assert current_source["worktree_sha256"] == original_source["worktree_sha256"]
    lab_cli._assert_source_snapshot(repo_root, {"source": original_source})


@pytest.mark.parametrize(
    "current_source",
    [
        {"commit": "b" * 40, "worktree_clean": False, "worktree_sha256": "b" * 64},
        {"commit": "a" * 40, "worktree_clean": False, "worktree_sha256": "b" * 64},
    ],
    ids=["commit-changed", "dirty-source-changed"],
)
def test_lab_up_refuses_to_resume_a_different_source_snapshot(
    tmp_path: Path,
    monkeypatch,
    current_source: dict[str, object],
):
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    run_id = "20261025T123456Z-12345678"
    stack_name = "platform-lab-" + run_id
    artifact_root = tmp_path / ".artifacts" / "platform" / "lab"
    run_dir = artifact_root / run_id
    run_dir.mkdir(parents=True)
    active_path = artifact_root / "active-run.json"
    active_path.write_text(
        json.dumps(
            {
                "schema_version": lab_cli.ACTIVE_RUN_SCHEMA,
                "run_id": run_id,
                "stack_name": stack_name,
            }
        ),
        encoding="utf-8",
    )
    old_source = {"commit": "a" * 40, "worktree_clean": False, "worktree_sha256": "a" * 64}
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": lab_cli.LAB_RUN_SCHEMA,
                "environment": "lab",
                "run_id": run_id,
                "stack_name": stack_name,
                "source": old_source,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(lab_cli, "_source_metadata", lambda repo_root: current_source)

    with pytest.raises(lab_cli.LabError, match="source snapshot"):
        lab_cli._prepare_run(tmp_path, None, {})


def test_failed_ssh_revalidation_persists_failed_status_not_previous_pass(
    tmp_path: Path,
    monkeypatch,
):
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    run_id = "20261025T123456Z-12345678"
    stack_name = "platform-lab-" + run_id
    artifact_root = tmp_path / ".artifacts" / "platform" / "lab"
    run_dir = artifact_root / run_id
    ssh_dir = run_dir / "ssh"
    ssh_dir.mkdir(parents=True)
    active_path = artifact_root / "active-run.json"
    active_path.write_text(
        json.dumps(
            {
                "schema_version": lab_cli.ACTIVE_RUN_SCHEMA,
                "run_id": run_id,
                "stack_name": stack_name,
            }
        ),
        encoding="utf-8",
    )
    source = {"commit": "a" * 40, "worktree_clean": False, "worktree_sha256": "a" * 64}
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": lab_cli.LAB_RUN_SCHEMA,
                "environment": "lab",
                "run_id": run_id,
                "stack_name": stack_name,
                "source": source,
                "ssh_host_port": 44299,
                "pulumi_up": "pass",
                "pending_revision": None,
                "revision": 1,
                "pulumi_noop_up": "pass",
                "ssh_validation": "pass",
                "controlled_update": "pass",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "passphrase").write_text("fixture-passphrase", encoding="utf-8")
    (ssh_dir / "id_ed25519").write_text("fixture-private-key", encoding="utf-8")
    (ssh_dir / "id_ed25519.pub").write_text("ssh-ed25519 AAAA fixture\n", encoding="utf-8")

    monkeypatch.setattr(lab_cli, "_doctor", lambda environment, repo_root: {"report": []})
    monkeypatch.setattr(lab_cli, "_source_metadata", lambda repo_root: source)
    monkeypatch.setattr(lab_cli, "_pulumi_login", lambda *args: None)
    monkeypatch.setattr(lab_cli, "_pulumi_select_stack", lambda *args: None)
    monkeypatch.setattr(lab_cli, "_pulumi", lambda *args, **kwargs: "")
    monkeypatch.setattr(lab_cli, "_read_lab_outputs", lambda *args: {"ssh_host_port": 44299})
    monkeypatch.setattr(lab_cli, "_inspect_lab_resources", lambda *args: {})
    monkeypatch.setattr(
        lab_cli,
        "_verify_ssh_access",
        lambda *args: (_ for _ in ()).throw(lab_cli.LabError("fixture SSH timeout")),
    )
    monkeypatch.setattr(
        lab_cli,
        "_write_json",
        lambda path, value: path.write_text(json.dumps(value), encoding="utf-8"),
    )

    with pytest.raises(lab_cli.LabError, match="fixture SSH timeout"):
        lab_cli._lab_test("lab", tmp_path, None)

    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["pulumi_noop_up"] == "pass"
    assert persisted["ssh_validation"] == "failed"
    assert persisted["controlled_update"] == "pass"


def test_lab_test_refuses_changed_source_before_pulumi(tmp_path: Path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location("platform_lab_cli", LAB_CLI)
    assert spec is not None and spec.loader is not None
    lab_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab_cli)

    run_id = "20261025T123456Z-12345678"
    stack_name = "platform-lab-" + run_id
    artifact_root = tmp_path / ".artifacts" / "platform" / "lab"
    run_dir = artifact_root / run_id
    run_dir.mkdir(parents=True)
    (artifact_root / "active-run.json").write_text(
        json.dumps(
            {
                "schema_version": lab_cli.ACTIVE_RUN_SCHEMA,
                "run_id": run_id,
                "stack_name": stack_name,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": lab_cli.LAB_RUN_SCHEMA,
                "environment": "lab",
                "run_id": run_id,
                "stack_name": stack_name,
                "source": {
                    "commit": "a" * 40,
                    "worktree_clean": True,
                    "worktree_sha256": "a" * 64,
                },
                "ssh_host_port": 44299,
                "pulumi_up": "pass",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(lab_cli, "_doctor", lambda environment, repo_root: {"report": []})
    monkeypatch.setattr(
        lab_cli,
        "_source_metadata",
        lambda repo_root: {
            "commit": "b" * 40,
            "worktree_clean": True,
            "worktree_sha256": "b" * 64,
        },
    )
    pulumi_calls = []
    monkeypatch.setattr(lab_cli, "_pulumi", lambda *args, **kwargs: pulumi_calls.append(args))

    with pytest.raises(lab_cli.LabError, match="source snapshot"):
        lab_cli._lab_test("lab", tmp_path, None)

    assert pulumi_calls == []
