"""Tests for tools/generate_stacks.py — written before implementation (TDD)."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import textwrap
from typing import Any, Dict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from generate_stacks import (
    apply_logging_defaults,
    collect_named_volumes,
    deep_merge,
    generate_stack,
    load_compose,
    load_fragment,
    strip_compose_only_keys,
)


# ---------------------------------------------------------------------------
# 1. deep_merge — scalars
# ---------------------------------------------------------------------------
def test_deep_merge_scalars():
    base = {"a": 1, "b": 2}
    override = {"b": 3, "c": 4}
    result = deep_merge(base, override)
    assert result == {"a": 1, "b": 3, "c": 4}


# ---------------------------------------------------------------------------
# 2. deep_merge — nested dicts are merged recursively
# ---------------------------------------------------------------------------
def test_deep_merge_nested_dict():
    base = {"deploy": {"resources": {"limits": {"memory": "128M"}}}}
    override: Dict[str, Any] = {
        "deploy": {
            "mode": "global",
            "resources": {"limits": {"memory": "512M"}},
        }
    }
    result = deep_merge(base, override)
    assert result == {
        "deploy": {
            "mode": "global",
            "resources": {"limits": {"memory": "512M"}},
        }
    }


# ---------------------------------------------------------------------------
# 3. deep_merge — lists are REPLACED, not appended
# ---------------------------------------------------------------------------
def test_deep_merge_list_replaces():
    base = {"command": ["a", "b"]}
    override = {"command": ["c"]}
    result = deep_merge(base, override)
    assert result == {"command": ["c"]}


# ---------------------------------------------------------------------------
# 4. strip_compose_only_keys removes container_name / restart / build
# ---------------------------------------------------------------------------
def test_strip_compose_only_keys():
    service = {
        "container_name": "foo",
        "restart": "unless-stopped",
        "build": ".",
        "image": "nginx",
    }
    result = strip_compose_only_keys(service)
    assert result == {"image": "nginx"}


# ---------------------------------------------------------------------------
# 5. collect_named_volumes — bind mounts filtered out
# ---------------------------------------------------------------------------
def test_collect_named_volumes_basic():
    volumes = [
        "postgres-data:/var/lib/postgresql/data",
        "/host/path:/container",
        "./rel:/container",
    ]
    result = collect_named_volumes(volumes)
    assert result == {"postgres-data"}


# ---------------------------------------------------------------------------
# 6. load_compose — extracts x-stack and removes it from returned data
# ---------------------------------------------------------------------------
def test_load_compose_extracts_x_stack(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        textwrap.dedent(
            """\
            x-stack: infrastructure
            services:
              web:
                image: nginx
            """
        )
    )
    data, stack_name = load_compose(str(compose_file))
    assert stack_name == "infrastructure"
    assert "x-stack" not in data
    assert "services" in data


# ---------------------------------------------------------------------------
# 7. load_compose — raises ValueError when x-stack is missing
# ---------------------------------------------------------------------------
def test_load_compose_missing_x_stack(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        textwrap.dedent(
            """\
            services:
              web:
                image: nginx
            """
        )
    )
    with pytest.raises(ValueError):
        load_compose(str(compose_file))


# ---------------------------------------------------------------------------
# 8. load_fragment — returns {} when swarm.fragment.yml is absent
# ---------------------------------------------------------------------------
def test_load_fragment_absent(tmp_path: Path):
    result = load_fragment(str(tmp_path))
    assert result == {}


# ---------------------------------------------------------------------------
# 9. load_fragment — returns parsed dict when swarm.fragment.yml is present
# ---------------------------------------------------------------------------
def test_load_fragment_present(tmp_path: Path):
    frag_file = tmp_path / "swarm.fragment.yml"
    frag_file.write_text(
        textwrap.dedent(
            """\
            services:
              web:
                deploy:
                  mode: global
            """
        )
    )
    result = load_fragment(str(tmp_path))
    assert result == {"services": {"web": {"deploy": {"mode": "global"}}}}


# ---------------------------------------------------------------------------
# 10. ${VAR} placeholders in labels are NOT resolved — preserved for render step
# ---------------------------------------------------------------------------
def test_env_vars_kept_as_placeholders(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("HOST=myhost.local\n")

    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        textwrap.dedent(
            """\
            x-stack: test
            services:
              web:
                image: nginx
                env_file: ./.env
                labels:
                  - "traefik.rule=Host(`${HOST}`)"
            """
        )
    )

    result = generate_stack("test", [str(compose_file)], str(tmp_path))

    svc = result["services"]["web"]
    labels = svc.get("labels", [])
    # Labels must keep the ${HOST} placeholder — NOT resolved at generate time
    assert any("${HOST}" in str(label) for label in labels), (
        f"Expected '${{HOST}}' placeholder in labels, got: {labels}"
    )
    assert not any("myhost.local" in str(label) for label in labels), (
        "Secret/env values must not be pre-resolved into generated stack files"
    )
    # env_file directive must still be present (needed by Swarm runtime + render step)
    assert "env_file" in svc, "env_file key must be preserved in output service"


# ---------------------------------------------------------------------------
# 11. apply_logging_defaults — injects defaults when no logging block present
# ---------------------------------------------------------------------------
def test_logging_defaults_injected():
    svc = {"image": "nginx"}
    result = apply_logging_defaults(svc)
    assert "logging" in result
    assert result["logging"]["driver"] == "local"
    assert result["logging"]["options"]["max-size"] == "10m"


# ---------------------------------------------------------------------------
# 12. apply_logging_defaults — does NOT overwrite an existing logging block
# ---------------------------------------------------------------------------
def test_logging_defaults_not_overwritten():
    existing: Dict[str, Any] = {"driver": "json-file", "options": {"max-size": "5m"}}
    svc: Dict[str, Any] = {"image": "nginx", "logging": existing}
    result = apply_logging_defaults(svc)
    assert result["logging"] == existing


# ---------------------------------------------------------------------------
# 13. generate_stack injects logging into services without a logging block
# ---------------------------------------------------------------------------
def test_generate_stack_injects_logging(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        textwrap.dedent(
            """\
            x-stack: test
            services:
              web:
                image: nginx
            """
        )
    )

    result = generate_stack("test", [str(compose_file)], str(tmp_path))
    svc = result["services"]["web"]
    assert "logging" in svc
    assert svc["logging"]["driver"] == "local"
