from __future__ import annotations

import base64
import hashlib
import json
import shlex
import shutil
import subprocess
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tools.platform.ansible_inventory import prepare_inventory


TRUST_SIGNER = Ed25519PrivateKey.generate()
TRUST_ROOT = TRUST_SIGNER.public_key()


PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
FINGERPRINT = "SHA256:kmYcvdi2GkPeWxB6XLjrZB8JHsy2Hm8luHMFp9GMvqk"


def lab_vm_inventory() -> dict[str, object]:
    return {
        "schema_version": "anitrend.platform.pulumi-inventory.lab-v1",
        "environment": "lab",
        "stack_identity": "external-vm:platform-test-01",
        "provider": "external-vm",
        "ssh_source_cidrs": ["192.0.2.2/32"],
        "hosts": [
            {
                "resource_id": "platform-test-01",
                "name": "platform-test-01",
                "bootstrap_user": "ansible",
                "connect_address": "192.0.2.18",
                "architecture": "amd64",
                "os_image": "ubuntu-24.04",
                "expected_host_identity_ref": "host-identity:lab:platform-test-01",
            }
        ],
        "volumes": [
            {
                "resource_id": "test-volume-01",
                "reference": "lab-storage-test",
                "linux_device": "/dev/disk/by-id/virtio-platform-test",
                "filesystem": "ext4",
                "mount_path": "/mnt/platform-test",
                "size_gb": 10,
                "data_classification": "disposable-test-data",
                "protected": False,
            }
        ],
        "architecture": "amd64",
        "image_ref": "ubuntu-24.04",
        "native_execution": True,
        "readiness": "ready",
    }


def hcloud_inventory() -> dict[str, object]:
    return {
        "schema_version": "anitrend.platform.pulumi-inventory.v1",
        "environment": "rehearsal",
        "stack_identity": "anitrend/platform-rehearsal",
        "provider": "hcloud",
        "resource_ids": [{"logical_id": "server", "provider_id": "101", "kind": "server"}],
        "network_ids": ["201"],
        "firewall_ids": ["301"],
        "firewall_policy": {
            "ssh_source_cidrs": ["198.51.100.10/32"],
            "public_routes": [],
            "private_routes": [],
        },
        "hosts": [
            {
                "resource_id": "101",
                "name": "anitrend-rehearsal-host",
                "bootstrap_user": "ansible",
                "public_ipv4": "198.51.100.17",
                "public_ipv6": None,
                "private_addresses": ["10.42.1.10"],
                "region": "nbg1",
                "server_type": "cx23",
                "architecture": "amd64",
                "os_image": "ubuntu-24.04",
                "ssh_key_refs": ["anitrend-ops"],
                "expected_host_identity_ref": "host-identity:rehearsal:server-101",
            }
        ],
        "volumes": [],
        "architecture": "amd64",
        "image_ref": "ubuntu-24.04",
        "native_execution": True,
        "budget_limit_eur": 100,
        "estimated_monthly_cost_eur": 50,
        "cost_estimate_ref": "approval:rehearsal-cost",
        "ttl_hours": 24,
        "readiness": "ready",
    }


def _sign_trust_bundle(value: dict[str, object]) -> dict[str, object]:
    payload = {key: item for key, item in value.items() if key != "signature"}
    message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["signature"] = base64.b64encode(TRUST_SIGNER.sign(message)).decode("ascii")
    return payload


def _fingerprint_for_key(public_key: str) -> str:
    blob = base64.b64decode(public_key.split()[1], validate=True)
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")
    return f"SHA256:{digest}"


def host_trust(
    environment: str,
    identity_ref: str,
    address: str,
    trust_type: str = "host_key",
) -> dict[str, object]:
    return _sign_trust_bundle(
        {
            "schema_version": "anitrend.platform.ssh-host-trust.v1",
            "environment": environment,
            "identity_ref": identity_ref,
            "trust_type": trust_type,
            "host": {
                "address": address,
                "public_key": PUBLIC_KEY,
                "fingerprint_sha256": FINGERPRINT,
            },
        }
    )


def host_vars(inventory: dict[str, object]) -> dict[str, object]:
    all_group = inventory["all"]
    assert isinstance(all_group, dict)
    children = all_group["children"]
    assert isinstance(children, dict)
    target_group = children["platform_target"]
    assert isinstance(target_group, dict)
    hosts = target_group["hosts"]
    assert isinstance(hosts, dict)
    values = hosts["platform-target"]
    assert isinstance(values, dict)
    return values


def test_lab_vm_inventory_generates_strict_known_hosts_and_redacted_ansible_inventory(tmp_path: Path):
    known_hosts = tmp_path / "private trust" / "known_hosts"
    trust = host_trust("lab", "host-identity:lab:platform-test-01", "192.0.2.18")

    inventory = prepare_inventory(lab_vm_inventory(), trust, "lab", known_hosts, TRUST_ROOT)
    variables = host_vars(inventory)
    assert variables["ansible_host"] == "192.0.2.18"
    assert variables["ansible_user"] == "ansible"
    assert variables["ansible_host_key_checking"] is True
    assert variables["ansible_ssh_common_args"] == ""
    assert variables["ansible_ssh_extra_args"] == ""

    ssh_args = variables["ansible_ssh_args"]
    assert "StrictHostKeyChecking=yes" in ssh_args
    ssh_tokens = shlex.split(ssh_args)
    assert f'UserKnownHostsFile="{known_hosts}"' in ssh_tokens
    ssh_executable = shutil.which("ssh")
    assert ssh_executable is not None
    effective_config = subprocess.run(
        [ssh_executable, "-F", "/dev/null", "-G", *ssh_tokens, "192.0.2.18"],
        check=True,
        capture_output=True,
        text=True,
    )
    known_hosts_setting = next(
        line for line in effective_config.stdout.splitlines() if line.startswith("userknownhostsfile ")
    )
    assert known_hosts_setting == f"userknownhostsfile {known_hosts}"

    assert known_hosts.read_text(encoding="utf-8") == f"192.0.2.18 {PUBLIC_KEY}\n"
    assert stat.S_IMODE(known_hosts.stat().st_mode) == 0o600
    assert PUBLIC_KEY not in json.dumps(inventory)
    assert variables["platform_volumes"][0]["linux_device"] == "/dev/disk/by-id/virtio-platform-test"

def test_host_ca_trust_is_scoped_to_the_exact_inventory_address(tmp_path: Path):
    trust = host_trust(
        "lab",
        "host-identity:lab:platform-test-01",
        "192.0.2.18",
        trust_type="host_ca",
    )
    known_hosts = tmp_path / "known_hosts"

    prepare_inventory(lab_vm_inventory(), trust, "lab", known_hosts, TRUST_ROOT)

    assert known_hosts.read_text(encoding="utf-8") == f"@cert-authority 192.0.2.18 {PUBLIC_KEY}\n"


def test_hcloud_inventory_uses_only_a_bound_public_address_and_preserves_policy(tmp_path: Path):
    trust = host_trust(
        "rehearsal",
        "host-identity:rehearsal:server-101",
        "198.51.100.17",
    )
    known_hosts = tmp_path / "known_hosts"

    inventory = prepare_inventory(hcloud_inventory(), trust, "rehearsal", known_hosts, TRUST_ROOT)
    variables = host_vars(inventory)

    assert variables["ansible_host"] == "198.51.100.17"
    assert variables["platform_firewall_policy"]["ssh_source_cidrs"] == ["198.51.100.10/32"]
    assert known_hosts.read_text(encoding="utf-8") == f"198.51.100.17 {PUBLIC_KEY}\n"


def test_wrong_environment_or_host_identity_fails_before_writing_trust(tmp_path: Path):
    known_hosts = tmp_path / "known_hosts"
    inventory = lab_vm_inventory()
    trust = host_trust("lab", "host-identity:lab:wrong-host", "192.0.2.18")

    with pytest.raises(ValueError, match="environment"):
        prepare_inventory(inventory, trust, "rehearsal", known_hosts, TRUST_ROOT)
    assert not known_hosts.exists()

    with pytest.raises(ValueError, match="identity reference"):
        prepare_inventory(inventory, trust, "lab", known_hosts, TRUST_ROOT)
    assert not known_hosts.exists()


def test_untrusted_address_or_fingerprint_is_rejected(tmp_path: Path):
    inventory = lab_vm_inventory()
    wrong_address = host_trust("lab", "host-identity:lab:platform-test-01", "192.0.2.19")
    with pytest.raises(ValueError, match="address"):
        prepare_inventory(inventory, wrong_address, "lab", tmp_path / "wrong-address", TRUST_ROOT)

    wrong_fingerprint = host_trust("lab", "host-identity:lab:platform-test-01", "192.0.2.18")
    wrong_fingerprint["host"]["fingerprint_sha256"] = "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    wrong_fingerprint = _sign_trust_bundle(wrong_fingerprint)
    with pytest.raises(ValueError, match="fingerprint"):
        prepare_inventory(inventory, wrong_fingerprint, "lab", tmp_path / "wrong-fingerprint", TRUST_ROOT)

def test_unsigned_host_trust_and_replaced_key_are_rejected(tmp_path: Path):
    inventory = lab_vm_inventory()
    trust = host_trust("lab", "host-identity:lab:platform-test-01", "192.0.2.18")
    unsigned = dict(trust)
    del unsigned["signature"]
    with pytest.raises(ValueError, match="schema validation"):
        prepare_inventory(inventory, unsigned, "lab", tmp_path / "unsigned", TRUST_ROOT)

    replaced_key = dict(trust)
    replaced_host = dict(trust["host"])
    key_blob = base64.b64decode(PUBLIC_KEY.split()[1], validate=True)
    alternate_key = "ssh-ed25519 " + base64.b64encode(key_blob[:-1] + bytes([1])).decode("ascii")
    replaced_host["public_key"] = alternate_key
    replaced_host["fingerprint_sha256"] = _fingerprint_for_key(alternate_key)
    replaced_key["host"] = replaced_host
    with pytest.raises(ValueError, match="signature"):
        prepare_inventory(inventory, replaced_key, "lab", tmp_path / "replaced", TRUST_ROOT)
