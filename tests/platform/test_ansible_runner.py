from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.platform import ansible_runner
from tools.platform.ansible_runner import RunnerBlocked, validate_docker_selection, validate_host_verify_inputs


def test_container_runner_rejects_remote_docker_contexts():
    with pytest.raises(RunnerBlocked, match="local Docker endpoint"):
        validate_docker_selection(
            "fixture-local",
            {"fixture-local"},
            "tcp://192.0.2.10:2375",
            "remote_or_unknown",
            "inactive",
        )


def test_container_runner_requires_an_explicit_context_allowlist():
    with pytest.raises(RunnerBlocked, match="allowlisted"):
        validate_docker_selection(
            "fixture-local",
            set(),
            "unix:///var/run/docker.sock",
            "local_unix",
            "inactive",
        )


def test_container_runner_refuses_a_swarm_enabled_docker_daemon():
    with pytest.raises(RunnerBlocked, match="Swarm"):
        validate_docker_selection(
            "fixture-local",
            {"fixture-local"},
            "unix:///var/run/docker.sock",
            "local_unix",
            "active",
        )


def test_host_runner_blocks_before_mutation_when_vm_inputs_are_missing():
    with pytest.raises(RunnerBlocked, match="PLATFORM_VM_INVENTORY"):
        validate_host_verify_inputs("lab", "vm", {})


def test_automation_connection_user_overrides_inventory_user(tmp_path: Path):
    inventory = tmp_path / "hosts.ini"
    inventory.write_text(
        "[platform_target]\n"
        "platform-target ansible_connection=local ansible_user=bootstrap\n",
        encoding="utf-8",
    )
    playbook = tmp_path / "assert-user.yml"
    playbook.write_text(
        "---\n"
        "- name: Verify the automation connection user\n"
        "  hosts: platform_target\n"
        "  gather_facts: false\n"
        "  tasks:\n"
        "    - name: Require the automation user\n"
        "      ansible.builtin.assert:\n"
        "        that: ansible_user == 'platform-automation'\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["ANSIBLE_CONFIG"] = str(ansible_runner.REPO_ROOT / "ansible" / "ansible.cfg")
    private_key = tmp_path / "unused-automation-key"
    private_key.write_text("", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ansible.cli.playbook",
            "--inventory",
            str(inventory),
            *ansible_runner._automation_connection_arguments(private_key),
            str(playbook),
        ],
        cwd=ansible_runner.REPO_ROOT / "ansible",
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_ansible_environment_uses_selected_collection_directory():
    selected_collections = ansible_runner.REPO_ROOT / ".artifacts" / "custom-collections"

    child_environment = ansible_runner._ansible_environment(
        {"PLATFORM_ANSIBLE_COLLECTIONS_PATH": str(selected_collections)}
    )

    assert Path(child_environment["ANSIBLE_COLLECTIONS_PATH"]) == selected_collections.resolve()


def test_container_runner_refuses_unowned_molecule_fixture(monkeypatch):
    class FakeLabError(Exception):
        pass

    lab = SimpleNamespace(
        FORBIDDEN_CREDENTIAL_ENV=(),
        LabError=FakeLabError,
        _parse_context_allowlist=lambda value: {"fixture-local"},
        _docker_context_endpoint=lambda context: ("unix:///var/run/docker.sock", "local_unix"),
        _run=lambda command: "inactive",
        _docker_command=lambda context, *arguments: ["docker", "--context", context, *arguments],
    )
    visible_commands = []

    def inspect_existing_fixture(command, *, cwd, environ):
        expected_name = "platform-ansible-20261111t000000z-abcdef12-ubuntu-2404"
        assert command[-1] == expected_name
        assert environ["PLATFORM_MOLECULE_RUN_ID"] == "20261111t000000z-abcdef12"
        assert environ["PLATFORM_MOLECULE_INSTANCE_NAME"] == expected_name
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"platform-owner":"someone-else","platform-run-id":"another-run"}',
            stderr="",
        )

    monkeypatch.setattr(ansible_runner, "_import_lab_helpers", lambda: lab)
    monkeypatch.setattr(ansible_runner, "_validate_ansible_toolchain", lambda environ, helpers: {})
    monkeypatch.setattr(ansible_runner, "_syntax_check_playbooks", lambda environ: None)
    monkeypatch.setattr(ansible_runner, "_new_run_id", lambda: "20261111t000000z-abcdef12")
    monkeypatch.setattr(ansible_runner, "_run_capture", inspect_existing_fixture)
    monkeypatch.setattr(
        ansible_runner,
        "_run_visible",
        lambda command, *, cwd, environ: visible_commands.append(command),
    )

    with pytest.raises(RunnerBlocked, match="ownership"):
        ansible_runner.run_container_test(
            "lab",
            {
                "PLATFORM_DOCKER_CONTEXT": "fixture-local",
                "PLATFORM_ALLOWED_DOCKER_CONTEXTS": "fixture-local",
            },
        )

    assert visible_commands == []
