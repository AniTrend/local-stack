from __future__ import annotations

import subprocess

import pytest

from tools.platform import host_firewall
from tools.platform.host_firewall import build_docker_rules, build_input_rules, parse_policy


@pytest.fixture
def firewall_policy():
    return parse_policy(
        {
            "ssh_source_cidrs": ["192.0.2.10/32"],
            "public_routes": [
                {
                    "port": 443,
                    "protocol": "https",
                    "source_cidrs": ["0.0.0.0/0", "::/0"],
                }
            ],
            "private_routes": [
                {
                    "port": 3000,
                    "protocol": "tcp",
                    "source_cidrs": ["100.64.0.0/10"],
                }
            ],
            "ipv4_interface": "ens3",
            "ipv6_enabled": True,
            "ipv6_interface": "ens3",
        }
    )


def test_host_input_rules_limit_ssh_and_service_ports_to_declared_sources(firewall_policy):
    rules = build_input_rules(firewall_policy, "ipv4")

    assert ["-p", "tcp", "-s", "192.0.2.10/32", "--dport", "22", "-j", "ACCEPT"] in rules
    assert ["-p", "tcp", "-s", "0.0.0.0/0", "--dport", "443", "-j", "ACCEPT"] in rules
    assert ["-p", "tcp", "-s", "100.64.0.0/10", "--dport", "3000", "-j", "ACCEPT"] in rules
    assert rules[-1] == ["-j", "DROP"]
    assert ["-p", "tcp", "--dport", "22", "-j", "ACCEPT"] not in rules


def test_docker_user_rules_filter_published_ports_and_exempt_docker_networks(firewall_policy):
    rules = build_docker_rules(firewall_policy, "ipv4")

    assert ["-i", "docker0", "-j", "RETURN"] in rules
    assert ["-i", "br-+", "-j", "RETURN"] in rules
    assert ["-i", "docker_gwbridge", "-j", "RETURN"] in rules
    assert [
        "-p",
        "tcp",
        "-m",
        "conntrack",
        "--ctstate",
        "NEW",
        "--ctorigdstport",
        "443",
        "-s",
        "0.0.0.0/0",
        "-j",
        "RETURN",
    ] in rules
    assert rules[-1] == ["-j", "DROP"]


def test_firewall_policy_rejects_global_ssh_and_noncanonical_networks():
    policy = {
        "ssh_source_cidrs": ["0.0.0.0/0"],
        "public_routes": [],
        "private_routes": [],
        "ipv4_interface": "ens3",
        "ipv6_enabled": False,
        "ipv6_interface": "",
    }

    with pytest.raises(ValueError, match="SSH source"):
        parse_policy(policy)

    policy["ssh_source_cidrs"] = ["192.0.2.1/24"]
    with pytest.raises(ValueError, match="canonical"):
        parse_policy(policy)


def test_ipv6_input_policy_does_not_require_an_ipv6_default_route():
    policy = parse_policy(
        {
            "ssh_source_cidrs": ["192.0.2.10/32"],
            "public_routes": [],
            "private_routes": [],
            "ipv4_interface": "ens3",
            "ipv6_enabled": True,
            "ipv6_interface": "",
        }
    )

    assert ["-p", "ipv6-icmp", "-j", "ACCEPT"] in build_input_rules(policy, "ipv6")
    assert build_docker_rules(policy, "ipv6")[-1] == ["-j", "DROP"]


def test_firewall_policy_supports_ipv6_only_hosts():
    policy = parse_policy(
        {
            "ssh_source_cidrs": ["2001:db8::10/128"],
            "public_routes": [],
            "private_routes": [],
            "ipv4_interface": "",
            "ipv6_enabled": True,
            "ipv6_interface": "ens3",
        }
    )

    assert ["-p", "tcp", "-s", "2001:db8::10/128", "--dport", "22", "-j", "ACCEPT"] in build_input_rules(
        policy, "ipv6"
    )
    assert build_docker_rules(policy, "ipv6")[-1] == ["-j", "DROP"]
    assert build_docker_rules(policy, "ipv4")[-1] == ["-j", "DROP"]


def test_docker_user_routes_apply_to_all_non_docker_interfaces(firewall_policy):
    rules = build_docker_rules(firewall_policy, "ipv4")

    assert [
        "-p",
        "tcp",
        "-m",
        "conntrack",
        "--ctstate",
        "NEW",
        "--ctorigdstport",
        "3000",
        "-s",
        "100.64.0.0/10",
        "-j",
        "RETURN",
    ] in rules
    assert rules[-1] == ["-j", "DROP"]


def test_firewall_drift_detection_rejects_reordered_drop_rules(monkeypatch):
    expected_rules = [
        ["-p", "tcp", "--dport", "443", "-j", "RETURN"],
        ["-i", "ens3", "-j", "DROP"],
        ["-j", "RETURN"],
    ]
    active_rules = [
        "-A ANITREND-DU -i ens3 -j DROP",
        "-A ANITREND-DU -p tcp --dport 443 -j RETURN",
        "-A ANITREND-DU -j RETURN",
    ]

    def fake_iptables(binary, arguments):
        command = [binary, *arguments]
        if arguments[:2] == ["-S", "DOCKER-USER"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="-A DOCKER-USER -j ANITREND-DU\n",
                stderr="",
            )
        if arguments[:2] == ["-S", "ANITREND-DU"]:
            return subprocess.CompletedProcess(command, 0, stdout="\n".join(active_rules) + "\n", stderr="")
        if arguments[:2] == ["-C", "ANITREND-DU"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(host_firewall, "_run", fake_iptables)

    assert not host_firewall._policy_matches("iptables", "DOCKER-USER", "ANITREND-DU", expected_rules)


def test_docker_policy_applies_ipv6_without_a_default_route(monkeypatch):
    policy = parse_policy(
        {
            "ssh_source_cidrs": ["192.0.2.10/32"],
            "public_routes": [],
            "private_routes": [],
            "ipv4_interface": "ens3",
            "ipv6_enabled": True,
            "ipv6_interface": "",
        }
    )
    families = []

    def record_family(binary, parent, active, staging_names, rules):
        families.append(binary)
        return False

    monkeypatch.setattr(host_firewall, "_ensure_chain", record_family)

    assert not host_firewall.apply_policy(policy, "docker")
    assert families == ["iptables", "ip6tables"]
