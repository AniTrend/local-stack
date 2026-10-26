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


def test_docker_user_rules_filter_published_dnat_traffic_only(firewall_policy):
    rules = build_docker_rules(firewall_policy, "ipv4")
    route_rule = [
        "-p",
        "tcp",
        "-m",
        "conntrack",
        "--ctstate",
        "DNAT",
        "--ctorigdstport",
        "443",
        "-s",
        "0.0.0.0/0",
        "-j",
        "RETURN",
    ]
    unapproved_dnat_drop = ["-m", "conntrack", "--ctstate", "DNAT", "-j", "DROP"]

    assert route_rule in rules
    assert unapproved_dnat_drop in rules
    assert rules.index(route_rule) < rules.index(unapproved_dnat_drop) < len(rules) - 1
    assert rules[-1] == ["-j", "RETURN"]

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

    assert build_docker_rules(policy, "ipv6")[-2] == ["-m", "conntrack", "--ctstate", "DNAT", "-j", "DROP"]
    assert build_docker_rules(policy, "ipv6")[-1] == ["-j", "RETURN"]


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
    assert build_docker_rules(policy, "ipv6")[-2] == ["-m", "conntrack", "--ctstate", "DNAT", "-j", "DROP"]
    assert build_docker_rules(policy, "ipv6")[-1] == ["-j", "RETURN"]
    assert build_docker_rules(policy, "ipv4")[-2] == ["-m", "conntrack", "--ctstate", "DNAT", "-j", "DROP"]
    assert build_docker_rules(policy, "ipv4")[-1] == ["-j", "RETURN"]


def test_docker_user_routes_apply_to_all_ingress_interfaces(firewall_policy):
    rules = build_docker_rules(firewall_policy, "ipv4")
    route_rule = [
        "-p",
        "tcp",
        "-m",
        "conntrack",
        "--ctstate",
        "DNAT",
        "--ctorigdstport",
        "3000",
        "-s",
        "100.64.0.0/10",
        "-j",
        "RETURN",
    ]
    unapproved_dnat_drop = ["-m", "conntrack", "--ctstate", "DNAT", "-j", "DROP"]

    assert route_rule in rules
    assert rules.index(route_rule) < rules.index(unapproved_dnat_drop)


def test_firewall_drift_detection_rejects_reordered_drop_rules(monkeypatch):
    expected_rules = [
        [
            "-p",
            "tcp",
            "-m",
            "conntrack",
            "--ctstate",
            "DNAT",
            "--ctorigdstport",
            "443",
            "-s",
            "0.0.0.0/0",
            "-j",
            "RETURN",
        ],
        ["-m", "conntrack", "--ctstate", "DNAT", "-j", "DROP"],
        ["-j", "RETURN"],
    ]
    active_rules = [
        "-A ANITREND-DU -m conntrack --ctstate DNAT -j DROP",
        "-A ANITREND-DU -p tcp -m conntrack --ctstate DNAT --ctorigdstport 443 -s 0.0.0.0/0 -j RETURN",
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


@pytest.mark.parametrize("docker_ipv6", [False, True])
def test_docker_hook_discovery_distinguishes_host_ipv6_from_docker_ipv6(
    monkeypatch,
    firewall_policy,
    docker_ipv6,
):
    def inspect_hook(binary, arguments):
        command = [binary, *arguments]
        enabled = binary == "iptables" or docker_ipv6
        if arguments == ["-S", "DOCKER-USER"]:
            if enabled:
                return subprocess.CompletedProcess(command, 0, stdout="-N DOCKER-USER\n", stderr="")
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="iptables: No chain/target/match by that name",
            )
        if arguments == ["-S", "FORWARD"]:
            lines = ["-P FORWARD ACCEPT"]
            if enabled:
                lines.append("-A FORWARD -j DOCKER-USER")
            return subprocess.CompletedProcess(command, 0, stdout="\n".join(lines) + "\n", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(host_firewall, "_run", inspect_hook)

    families, unavailable = host_firewall._docker_families(firewall_policy)

    expected = ["ipv4", "ipv6"] if docker_ipv6 else ["ipv4"]
    assert families == expected
    assert unavailable == (() if docker_ipv6 else ("ipv6",))


def test_docker_hook_discovery_does_not_hide_inspection_failure(monkeypatch, firewall_policy):
    monkeypatch.setattr(
        host_firewall,
        "_run",
        lambda binary, arguments: subprocess.CompletedProcess(
            [binary, *arguments], 4, stdout="", stderr="Permission denied"
        ),
    )

    with pytest.raises(host_firewall.FirewallError, match="inspect"):
        host_firewall._docker_families(firewall_policy)


def test_docker_hook_discovery_rejects_missing_ipv4_hook(monkeypatch, firewall_policy):
    monkeypatch.setattr(
        host_firewall,
        "_run",
        lambda binary, arguments: subprocess.CompletedProcess(
            [binary, *arguments],
            1,
            stdout="",
            stderr="iptables: No chain/target/match by that name",
        ),
    )

    with pytest.raises(host_firewall.FirewallError, match="DOCKER-USER"):
        host_firewall._docker_families(firewall_policy)


def test_docker_hook_discovery_rejects_unattached_ipv4_chain(monkeypatch, firewall_policy):
    def inspect_hook(binary, arguments):
        command = [binary, *arguments]
        if arguments == ["-S", "DOCKER-USER"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="-N DOCKER-USER\n", stderr=""
            )
        if arguments == ["-S", "FORWARD"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="-P FORWARD ACCEPT\n", stderr=""
            )
        raise AssertionError(command)

    monkeypatch.setattr(host_firewall, "_run", inspect_hook)

    with pytest.raises(host_firewall.FirewallError, match="DOCKER-USER"):
        host_firewall._docker_families(firewall_policy)


def test_docker_hook_discovery_does_not_hide_forward_inspection_failure(
    monkeypatch, firewall_policy
):
    def inspect_hook(binary, arguments):
        command = [binary, *arguments]
        if arguments == ["-S", "DOCKER-USER"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="-N DOCKER-USER\n", stderr=""
            )
        if arguments == ["-S", "FORWARD"]:
            return subprocess.CompletedProcess(
                command, 4, stdout="", stderr="Permission denied"
            )
        raise AssertionError(command)

    monkeypatch.setattr(host_firewall, "_run", inspect_hook)

    with pytest.raises(host_firewall.FirewallError, match="FORWARD"):
        host_firewall._docker_families(firewall_policy)


def test_docker_policy_skips_a_missing_ipv6_hook(monkeypatch, firewall_policy):
    installed_families = []

    def install_policy(binary, parent, active, staging_names, rules):
        installed_families.append(binary)
        return False

    monkeypatch.setattr(
        host_firewall,
        "_docker_hook_available",
        lambda binary: binary == "iptables",
        raising=False,
    )
    monkeypatch.setattr(host_firewall, "_ensure_chain", install_policy)

    result = host_firewall.apply_policy(firewall_policy, "docker")

    assert not result.changed
    assert result.unavailable_families == ("ipv6",)
    assert installed_families == ["iptables"]


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

    monkeypatch.setattr(host_firewall, "_docker_hook_available", lambda binary: True)
    monkeypatch.setattr(host_firewall, "_ensure_chain", record_family)

    result = host_firewall.apply_policy(policy, "docker")

    assert not result.changed
    assert result.unavailable_families == ()
    assert families == ["iptables", "ip6tables"]


def test_host_input_keeps_ipv6_filtering_without_a_docker_hook(monkeypatch):
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

    def fail_if_docker_hook_is_checked(binary):
        raise AssertionError("INPUT filtering must not depend on Docker hooks")

    monkeypatch.setattr(host_firewall, "_docker_hook_available", fail_if_docker_hook_is_checked)
    monkeypatch.setattr(host_firewall, "_ensure_chain", record_family)

    result = host_firewall.apply_policy(policy, "input")

    assert not result.changed
    assert result.unavailable_families == ()
    assert families == ["iptables", "ip6tables"]
