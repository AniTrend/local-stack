from __future__ import annotations

import pytest

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
