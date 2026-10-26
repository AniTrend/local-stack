#!/usr/bin/env python3
"""Validate versioned platform inventory and prepare strict SSH trust for Ansible."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import ipaddress
import json
import os
import shlex
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
import jsonschema


REPO_ROOT = Path(__file__).resolve().parents[2]
HCLOUD_INVENTORY_SCHEMA = REPO_ROOT / "infra" / "pulumi" / "shared" / "pulumi-inventory.schema.json"
LAB_VM_INVENTORY_SCHEMA = REPO_ROOT / "infra" / "pulumi" / "shared" / "lab-vm-inventory.schema.json"
SSH_HOST_TRUST_SCHEMA = REPO_ROOT / "infra" / "pulumi" / "shared" / "ssh-host-trust.schema.json"
HCLOUD_INVENTORY_VERSION = "anitrend.platform.pulumi-inventory.v1"
LAB_VM_INVENTORY_VERSION = "anitrend.platform.pulumi-inventory.lab-v1"
SSH_HOST_TRUST_VERSION = "anitrend.platform.ssh-host-trust.v1"


class InventoryError(ValueError):
    """Input inventory or trust data cannot be used safely."""


def _validate_document(value: object, name: str, schema_path: Path) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as error:
        raise InventoryError(f"cannot load the {name} validation schema") from error

    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        location = "/" + "/".join(str(part) for part in errors[0].absolute_path)
        raise InventoryError(f"{name} failed schema validation at {location}")


def _verify_trust_signature(
    trust_value: dict[str, object],
    trust_root_public_key: Ed25519PublicKey,
) -> None:
    signature_text = trust_value["signature"]
    if not isinstance(signature_text, str):
        raise InventoryError("SSH host trust signature is malformed")
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (binascii.Error, ValueError) as error:
        raise InventoryError("SSH host trust signature is malformed") from error
    if len(signature) != 64:
        raise InventoryError("SSH host trust signature is malformed")

    signed_payload = {key: value for key, value in trust_value.items() if key != "signature"}
    message = json.dumps(signed_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        trust_root_public_key.verify(signature, message)
    except InvalidSignature as error:
        raise InventoryError("SSH host trust signature verification failed") from error


def _decode_ed25519_fingerprint(public_key: str) -> str:
    parts = public_key.split()
    if len(parts) != 2 or parts[0] != "ssh-ed25519":
        raise InventoryError("host trust must contain one ssh-ed25519 public key")
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except (binascii.Error, ValueError) as error:
        raise InventoryError("host trust contains malformed public-key data") from error

    key_type = b"ssh-ed25519"
    if len(blob) < 4 or int.from_bytes(blob[:4], "big") != len(key_type):
        raise InventoryError("host trust contains malformed public-key data")
    offset = 4
    if blob[offset : offset + len(key_type)] != key_type:
        raise InventoryError("host trust contains a mismatched public-key type")
    offset += len(key_type)
    if len(blob) < offset + 4 or int.from_bytes(blob[offset : offset + 4], "big") != 32:
        raise InventoryError("host trust contains malformed Ed25519 key data")
    offset += 4
    if len(blob) != offset + 32:
        raise InventoryError("host trust contains malformed Ed25519 key data")

    fingerprint = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")
    return f"SHA256:{fingerprint}"


def _write_private_file(path: Path, contents: str) -> None:
    if not path.is_absolute():
        raise InventoryError("known_hosts output path must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise InventoryError("refusing to overwrite existing Ansible trust output") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(path, 0o600)
    except OSError:
        path.unlink(missing_ok=True)
        raise


def prepare_inventory(
    inventory_value: object,
    trust_value: object,
    expected_environment: str,
    known_hosts_path: Path,
    trust_root_public_key: Ed25519PublicKey,
) -> dict[str, object]:
    if not isinstance(inventory_value, dict):
        raise InventoryError("platform inventory must be a JSON object")
    if not isinstance(trust_value, dict):
        raise InventoryError("SSH host trust must be a JSON object")
    if expected_environment not in {"lab", "rehearsal", "production"}:
        raise InventoryError("unsupported expected environment")

    schema_version = inventory_value.get("schema_version")
    if schema_version == HCLOUD_INVENTORY_VERSION:
        inventory_schema = HCLOUD_INVENTORY_SCHEMA
    elif schema_version == LAB_VM_INVENTORY_VERSION:
        inventory_schema = LAB_VM_INVENTORY_SCHEMA
    else:
        raise InventoryError("unsupported platform inventory schema version")
    _validate_document(inventory_value, "platform inventory", inventory_schema)
    if trust_value.get("schema_version") != SSH_HOST_TRUST_VERSION:
        raise InventoryError("unsupported SSH host trust schema version")
    _validate_document(trust_value, "SSH host trust", SSH_HOST_TRUST_SCHEMA)
    _verify_trust_signature(trust_value, trust_root_public_key)

    environment = inventory_value["environment"]
    if environment != expected_environment:
        raise InventoryError("platform inventory environment does not match the requested environment")
    if trust_value["environment"] != environment:
        raise InventoryError("SSH host trust environment does not match the platform inventory")
    if inventory_value["readiness"] != "ready":
        raise InventoryError("platform inventory is not ready for Ansible")

    hosts = inventory_value["hosts"]
    if len(hosts) != 1:
        raise InventoryError("Ansible host verification requires exactly one inventory host")
    host = hosts[0]
    expected_identity_ref = host["expected_host_identity_ref"]
    if trust_value["identity_ref"] != expected_identity_ref:
        raise InventoryError("SSH host trust identity reference does not match the inventory")

    if schema_version == LAB_VM_INVENTORY_VERSION:
        address = host["connect_address"]
        firewall_policy: dict[str, object] = {
            "ssh_source_cidrs": inventory_value["ssh_source_cidrs"],
            "public_routes": [],
            "private_routes": [],
        }
    else:
        address = host["public_ipv4"] or host["public_ipv6"]
        if address is None:
            raise InventoryError("HCloud inventory has no public SSH address")
        firewall_policy = inventory_value["firewall_policy"]

    try:
        trusted_address = str(ipaddress.ip_address(trust_value["host"]["address"]))
        inventory_address = str(ipaddress.ip_address(address))
        for cidr in firewall_policy["ssh_source_cidrs"]:
            network = ipaddress.ip_network(cidr, strict=True)
            if network.prefixlen == 0:
                raise InventoryError("SSH source policy cannot include a default route")
    except InventoryError:
        raise
    except ValueError as error:
        raise InventoryError("platform inventory contains an invalid SSH address or source CIDR") from error
    if trusted_address != inventory_address:
        raise InventoryError("SSH host trust address does not match the inventory host address")

    public_key = trust_value["host"]["public_key"]
    fingerprint = _decode_ed25519_fingerprint(public_key)
    if fingerprint != trust_value["host"]["fingerprint_sha256"]:
        raise InventoryError("SSH host trust fingerprint does not match its public key")

    known_hosts_text = str(known_hosts_path)
    if any(character in known_hosts_text for character in ("\0", "\n", "\r")):
        raise InventoryError("known_hosts path contains unsupported control characters")
    ssh_config_path = known_hosts_text.replace("\\", "\\\\").replace('"', '\\"')
    user_known_hosts_option = shlex.quote(f'UserKnownHostsFile="{ssh_config_path}"')
    ssh_args = " ".join(
        (
            "-o StrictHostKeyChecking=yes",
            f"-o {user_known_hosts_option}",
            "-o GlobalKnownHostsFile=/dev/null",
            "-o IdentitiesOnly=yes",
        )
    )
    host_vars: dict[str, object] = {
        "ansible_connection": "ssh",
        "ansible_host": inventory_address,
        "ansible_port": 22,
        "ansible_user": host["bootstrap_user"],
        "ansible_host_key_checking": True,
        "ansible_ssh_args": ssh_args,
        "ansible_ssh_common_args": "",
        "ansible_ssh_extra_args": "",
        "platform_environment": environment,
        "platform_inventory_schema_version": schema_version,
        "platform_provider": inventory_value["provider"],
        "platform_stack_identity": inventory_value["stack_identity"],
        "platform_host_identity_ref": expected_identity_ref,
        "platform_architecture": host["architecture"],
        "platform_os_image": host["os_image"],
        "platform_firewall_policy": firewall_policy,
        "platform_volumes": inventory_value["volumes"],
    }
    trust_prefix = "@cert-authority " if trust_value["trust_type"] == "host_ca" else ""
    known_hosts_line = f"{trust_prefix}{inventory_address} {public_key}\n"
    _write_private_file(known_hosts_path, known_hosts_line)

    return {
        "all": {
            "children": {
                "platform_target": {
                    "hosts": {
                        "platform-target": host_vars,
                    }
                }
            }
        }
    }


def _read_json(path: Path, description: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InventoryError(f"cannot read {description} JSON") from error

def _load_trust_root(path: Path) -> Ed25519PublicKey:
    try:
        public_key = load_pem_public_key(path.read_bytes())
    except (OSError, ValueError, UnsupportedAlgorithm) as error:
        raise InventoryError("cannot load the separate SSH trust root") from error
    if not isinstance(public_key, Ed25519PublicKey):
        raise InventoryError("SSH trust root must be an Ed25519 public key")
    return public_key



def _write_inventory(path: Path, inventory: dict[str, object]) -> None:
    serialized = json.dumps(inventory, sort_keys=True, separators=(",", ":")) + "\n"
    _write_private_file(path, serialized)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--trust-bundle", required=True, type=Path)
    parser.add_argument("--environment", required=True, choices=("lab", "rehearsal", "production"))
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--trust-root", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        artifacts_root = (REPO_ROOT / ".artifacts" / "platform").resolve()
        output_dir = args.output_dir.resolve()
        if output_dir == artifacts_root or artifacts_root not in output_dir.parents:
            raise InventoryError("Ansible output directory must be a new child of .artifacts/platform")
        if output_dir.exists():
            raise InventoryError("refusing to reuse an existing Ansible output directory")
        inventory_value = _read_json(args.inventory, "platform inventory")
        trust_value = _read_json(args.trust_bundle, "SSH host trust")
        if args.trust_root.resolve() == args.trust_bundle.resolve():
            raise InventoryError("SSH trust root must be supplied separately from the signed host trust bundle")
        known_hosts_path = output_dir / "known_hosts"
        trust_root_public_key = _load_trust_root(args.trust_root)
        prepared = prepare_inventory(
            inventory_value,
            trust_value,
            args.environment,
            known_hosts_path,
            trust_root_public_key,
        )
        _write_inventory(output_dir / "inventory.json", prepared)
    except InventoryError as error:
        print(f"ansible inventory: {error}", file=sys.stderr)
        return 2
    except OSError:
        print("ansible inventory: cannot write protected output files", file=sys.stderr)
        return 2

    print(f"prepared strict SSH inventory for {args.environment} in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
