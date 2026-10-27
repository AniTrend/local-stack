#!/usr/bin/env python3
"""Apply the platform INPUT and Docker DOCKER-USER firewall policies."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Sequence


DEFAULT_CONFIG = Path("/etc/anitrend-platform/firewall.json")
INTERFACE_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,15}\Z")
PROTOCOLS = {"http": "tcp", "https": "tcp", "tcp": "tcp", "udp": "udp"}


class FirewallError(ValueError):
    """Firewall policy or host firewall operations are invalid."""


@dataclass(frozen=True, slots=True)
class FirewallRoute:
    port: int
    protocol: str
    source_cidrs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FirewallPolicy:
    ssh_source_cidrs: tuple[str, ...]
    public_routes: tuple[FirewallRoute, ...]
    private_routes: tuple[FirewallRoute, ...]
    ipv4_interface: str
    ipv6_enabled: bool
    ipv6_interface: str


@dataclass(frozen=True, slots=True)
class FirewallApplyResult:
    changed: bool
    unavailable_families: tuple[str, ...] = ()


def _canonical_network(value: object, description: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    if not isinstance(value, str):
        raise FirewallError(f"{description} must be a canonical CIDR")
    try:
        network = ipaddress.ip_network(value, strict=True)
    except ValueError as error:
        raise FirewallError(f"{description} must be a canonical CIDR") from error
    if str(network) != value:
        raise FirewallError(f"{description} must be a canonical CIDR")
    return network


def _source_networks(value: object, description: str, *, reject_default: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise FirewallError(f"{description} must be a non-empty CIDR list")
    networks: list[str] = []
    for item in value:
        network = _canonical_network(item, description)
        if reject_default and network.prefixlen == 0:
            raise FirewallError("SSH source CIDRs cannot include a default route")
        networks.append(str(network))
    if len(set(networks)) != len(networks):
        raise FirewallError(f"{description} cannot contain duplicate CIDRs")
    return tuple(networks)


def _routes(value: object, description: str) -> tuple[FirewallRoute, ...]:
    if not isinstance(value, list):
        raise FirewallError(f"{description} must be a list")
    routes: list[FirewallRoute] = []
    for route in value:
        if not isinstance(route, dict):
            raise FirewallError(f"{description} entries must be objects")
        port = route.get("port")
        protocol = route.get("protocol")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise FirewallError(f"{description} ports must be integers from 1 to 65535")
        if not isinstance(protocol, str) or protocol not in PROTOCOLS:
            raise FirewallError(f"{description} protocol is unsupported")
        sources = _source_networks(route.get("source_cidrs"), description, reject_default=False)
        routes.append(FirewallRoute(port, protocol, sources))
    return tuple(routes)


def parse_policy(value: object) -> FirewallPolicy:
    if not isinstance(value, dict):
        raise FirewallError("firewall configuration must be an object")
    expected_fields = {
        "ssh_source_cidrs",
        "public_routes",
        "private_routes",
        "ipv4_interface",
        "ipv6_enabled",
        "ipv6_interface",
    }
    if set(value) != expected_fields:
        raise FirewallError("firewall configuration fields do not match the platform contract")

    ipv4_interface = value["ipv4_interface"]
    ipv6_interface = value["ipv6_interface"]
    ipv6_enabled = value["ipv6_enabled"]
    if not isinstance(ipv4_interface, str) or (ipv4_interface and INTERFACE_PATTERN.fullmatch(ipv4_interface) is None):
        raise FirewallError("the IPv4 default interface is invalid")
    if not isinstance(ipv6_interface, str) or (ipv6_interface and INTERFACE_PATTERN.fullmatch(ipv6_interface) is None):
        raise FirewallError("the IPv6 default interface is invalid")
    if not isinstance(ipv6_enabled, bool):
        raise FirewallError("IPv6 firewall enablement must be boolean")

    return FirewallPolicy(
        ssh_source_cidrs=_source_networks(value["ssh_source_cidrs"], "SSH source CIDRs", reject_default=True),
        public_routes=_routes(value["public_routes"], "public routes"),
        private_routes=_routes(value["private_routes"], "private routes"),
        ipv4_interface=ipv4_interface,
        ipv6_enabled=ipv6_enabled,
        ipv6_interface=ipv6_interface,
    )


def _matches_family(cidr: str, family: str) -> bool:
    version = ipaddress.ip_network(cidr, strict=True).version
    return version == (4 if family == "ipv4" else 6)


def _protocol(protocol: str) -> str:
    return PROTOCOLS[protocol]


def _routes_for(policy: FirewallPolicy) -> tuple[FirewallRoute, ...]:
    return policy.public_routes + policy.private_routes


def build_input_rules(policy: FirewallPolicy, family: str) -> list[list[str]]:
    if family not in {"ipv4", "ipv6"}:
        raise ValueError("family must be ipv4 or ipv6")
    icmp_protocol = "icmp" if family == "ipv4" else "ipv6-icmp"
    rules = [
        ["-i", "lo", "-j", "ACCEPT"],
        ["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT"],
        ["-p", icmp_protocol, "-j", "ACCEPT"],
        ["-i", "tailscale0", "-p", "tcp", "--dport", "22", "-j", "ACCEPT"],
    ]
    for cidr in policy.ssh_source_cidrs:
        if _matches_family(cidr, family):
            rules.append(["-p", "tcp", "-s", cidr, "--dport", "22", "-j", "ACCEPT"])
    for route in _routes_for(policy):
        for cidr in route.source_cidrs:
            if _matches_family(cidr, family):
                rules.append(
                    ["-p", _protocol(route.protocol), "-s", cidr, "--dport", str(route.port), "-j", "ACCEPT"]
                )
    rules.append(["-j", "DROP"])
    return rules


def build_docker_rules(policy: FirewallPolicy, family: str) -> list[list[str]]:
    if family not in {"ipv4", "ipv6"}:
        raise ValueError("family must be ipv4 or ipv6")
    rules = [["-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "RETURN"]]
    for route in _routes_for(policy):
        for cidr in route.source_cidrs:
            if _matches_family(cidr, family):
                rules.append(
                    [
                        "-p",
                        _protocol(route.protocol),
                        "-m",
                        "conntrack",
                        "--ctstate",
                        "DNAT",
                        "--ctorigdstport",
                        str(route.port),
                        "-s",
                        cidr,
                        "-j",
                        "RETURN",
                    ]
                )
    rules.extend(
        [
            ["-m", "conntrack", "--ctstate", "DNAT", "-j", "DROP"],
            ["-j", "RETURN"],
        ]
    )
    return rules


def _run(binary: str, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [binary, "-w", "-t", "filter", *arguments],
        capture_output=True,
        check=False,
        text=True,
    )


def _chain_lines(binary: str, chain: str) -> list[str] | None:
    result = _run(binary, ["-S", chain])
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()


def _policy_matches(binary: str, parent: str, active: str, rules: list[list[str]]) -> bool:
    parent_lines = _chain_lines(binary, parent)
    chain_lines = _chain_lines(binary, active)
    if parent_lines is None or chain_lines is None:
        return False

    parent_rules = [line for line in parent_lines if line.startswith(f"-A {parent} ")]
    jump = f"-A {parent} -j {active}"
    if not parent_rules or parent_rules[0] != jump or parent_rules.count(jump) != 1:
        return False

    actual_rules = [line for line in chain_lines if line.startswith(f"-A {active} ")]
    if len(actual_rules) != len(rules):
        return False

    expected_drop_positions = [
        index for index, rule in enumerate(rules) if rule[-2:] == ["-j", "DROP"]
    ]
    actual_drop_positions = [
        index for index, line in enumerate(actual_rules) if line.endswith(" -j DROP")
    ]
    if actual_drop_positions != expected_drop_positions:
        return False

    for rule in rules:
        if _run(binary, ["-C", active, *rule]).returncode != 0:
            return False
    expected_last_rule = f"-A {active} {' '.join(rules[-1])}"
    if not actual_rules or actual_rules[-1] != expected_last_rule:
        return False
    return True


def _chain_exists(binary: str, chain: str) -> bool:
    return _chain_lines(binary, chain) is not None


def _delete_jumps(binary: str, parent: str, chain: str) -> None:
    while _run(binary, ["-D", parent, "-j", chain]).returncode == 0:
        pass


def _apply_chain(
    binary: str,
    parent: str,
    active: str,
    staging_names: tuple[str, str],
    rules: list[list[str]],
) -> None:
    staging = next((name for name in staging_names if not _run(binary, ["-C", parent, "-j", name]).returncode == 0), None)
    if staging is None:
        staging = next((name for name in staging_names if not _chain_exists(binary, name)), None)
    if staging is None:
        raise FirewallError("no unused staging chain is available for an atomic firewall update")

    if not _chain_exists(binary, staging):
        result = _run(binary, ["-N", staging])
        if result.returncode != 0:
            raise FirewallError("could not create the staging firewall chain")
    else:
        result = _run(binary, ["-F", staging])
        if result.returncode != 0:
            raise FirewallError("could not reset the staging firewall chain")

    for rule in rules:
        if _run(binary, ["-A", staging, *rule]).returncode != 0:
            raise FirewallError("could not populate the staging firewall chain")

    if _run(binary, ["-I", parent, "1", "-j", staging]).returncode != 0:
        raise FirewallError("could not activate the staging firewall chain")

    owned_chains = (active, *staging_names)
    for chain in owned_chains:
        if chain == staging:
            continue
        _delete_jumps(binary, parent, chain)
        if _chain_exists(binary, chain):
            if _run(binary, ["-F", chain]).returncode != 0 or _run(binary, ["-X", chain]).returncode != 0:
                raise FirewallError("could not retire an obsolete firewall chain")

    if _run(binary, ["-E", staging, active]).returncode != 0:
        raise FirewallError("could not publish the new firewall chain")


def _ensure_chain(
    binary: str,
    parent: str,
    active: str,
    staging_names: tuple[str, str],
    rules: list[list[str]],
) -> bool:
    if _policy_matches(binary, parent, active, rules):
        return False
    _apply_chain(binary, parent, active, staging_names, rules)
    if not _policy_matches(binary, parent, active, rules):
        raise FirewallError("firewall policy verification failed after apply")
    return True

def _docker_hook_available(binary: str) -> bool:
    chain_result = _run(binary, ["-S", "DOCKER-USER"])
    chain_error = chain_result.stderr + chain_result.stdout
    if chain_result.returncode != 0:
        if chain_result.returncode == 1 and "No chain/target/match by that name" in chain_error:
            return False
        raise FirewallError(f"could not inspect the {binary} Docker DOCKER-USER hook")

    forward_result = _run(binary, ["-S", "FORWARD"])
    if forward_result.returncode != 0:
        raise FirewallError(f"could not inspect the {binary} FORWARD chain")
    return "-A FORWARD -j DOCKER-USER" in forward_result.stdout.splitlines()


def _docker_families(policy: FirewallPolicy) -> tuple[list[str], tuple[str, ...]]:
    if not _docker_hook_available("iptables"):
        raise FirewallError("Docker IPv4 DOCKER-USER hook is unavailable")

    families = ["ipv4"]
    unavailable: list[str] = []
    if policy.ipv6_enabled:
        if _docker_hook_available("ip6tables"):
            families.append("ipv6")
        else:
            unavailable.append("ipv6")
    return families, tuple(unavailable)


def apply_policy(policy: FirewallPolicy, action: str) -> FirewallApplyResult:
    if action not in {"input", "docker"}:
        raise ValueError("action must be input or docker")

    changed = False
    unavailable_families: tuple[str, ...] = ()
    if action == "input":
        families = ["ipv4"]
        if policy.ipv6_enabled:
            families.append("ipv6")
    else:
        families, unavailable_families = _docker_families(policy)

    for family in families:
        binary = "iptables" if family == "ipv4" else "ip6tables"
        if action == "input":
            parent = "INPUT"
            active = "ANITREND-IN"
            staging_names = ("ANITREND-IN-A", "ANITREND-IN-B")
            rules = build_input_rules(policy, family)
        else:
            parent = "DOCKER-USER"
            active = "ANITREND-DU"
            staging_names = ("ANITREND-DU-A", "ANITREND-DU-B")
            rules = build_docker_rules(policy, family)
        changed = _ensure_chain(binary, parent, active, staging_names, rules) or changed
    return FirewallApplyResult(changed, unavailable_families)


def _read_policy(path: Path) -> FirewallPolicy:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FirewallError("cannot read the protected firewall policy") from error
    return parse_policy(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("input", "docker"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)

    try:
        result = apply_policy(_read_policy(args.config), args.action)
    except FirewallError as error:
        print(f"platform firewall: {error}", file=sys.stderr)
        return 2
    except OSError:
        print("platform firewall: a local netfilter command failed", file=sys.stderr)
        return 2

    for family in result.unavailable_families:
        print(f"platform-firewall-docker-{family}=unavailable")
    print("platform-firewall=changed" if result.changed else "platform-firewall=unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
