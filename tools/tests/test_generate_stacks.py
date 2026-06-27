"""Tests for tools/generate_stacks.py — written before implementation (TDD)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
import sys
import textwrap
from typing import Any, Dict

import pytest
import yaml

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


# ---------------------------------------------------------------------------
# 14. main — --dry-run prints valid YAML to stdout, writes no files
# ---------------------------------------------------------------------------
MODULE = os.path.join(os.path.dirname(__file__), "..", "generate_stacks.py")


def test_main_dry_run(tmp_path: Path):
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

    result = subprocess.run(
        [
            sys.executable,
            MODULE,
            "--dry-run",
            "--stacks",
            "test",
            "--repo-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "stack: test" in result.stdout
    assert "image: nginx" in result.stdout
    assert not (tmp_path / "stacks").exists()


# ---------------------------------------------------------------------------
# 15. main --dry-run — output is structurally valid YAML
# ---------------------------------------------------------------------------
def test_main_dry_run_yaml_valid(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        textwrap.dedent(
            """\
            x-stack: test
            services:
              web:
                image: nginx
                volumes:
                  - app-data:/data
            volumes:
              app-data:
                driver: local
            """
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            MODULE,
            "--dry-run",
            "--stacks",
            "test",
            "--repo-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"

    # Strip the "# --- stack: test ---" header line
    yaml_text = result.stdout
    lines = yaml_text.splitlines()
    # Find the first non-comment, non-empty line as YAML start
    yaml_lines = [line for line in lines if not line.strip().startswith("#") and line.strip()]
    yaml_block = "\n".join(yaml_lines)

    data = yaml.safe_load(yaml_block)
    assert isinstance(data, dict)
    assert "services" in data
    assert "volumes" in data
    assert "networks" in data
    assert data["services"]["web"]["image"] == "nginx"


# ---------------------------------------------------------------------------
# 16. generate_stack — preserves env_file path as relative
# ---------------------------------------------------------------------------
def test_generate_stack_preserves_env_file_path(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        textwrap.dedent(
            """\
            x-stack: test
            services:
              web:
                image: nginx
                env_file: ./.env
            """
        )
    )

    result = generate_stack("test", [str(compose_file)], str(tmp_path))
    svc = result["services"]["web"]
    assert "env_file" in svc, "env_file key must be preserved in output service"
    env_file = svc["env_file"]
    assert isinstance(env_file, str)
    assert env_file.startswith("./"), (
        f"env_file should be a relative path starting with './', got: {env_file}"
    )
