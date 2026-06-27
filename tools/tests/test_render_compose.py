"""Tests for tools/render_compose.py — variable substitution and env-file parsing."""
from __future__ import annotations

import os
import sys
import textwrap
from typing import Any, Dict

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from render_compose import (
    parse_env_file,
    substitute,
    deep_interpolate,
    build_service_scope_vars,
    absolutize_service_paths,
    render_compose,
)


# ---------------------------------------------------------------------------
# 1. substitute — ${VAR} resolved
# ---------------------------------------------------------------------------
def test_substitute_braced_var_resolved():
    result = substitute("${HOST}", {"HOST": "example.com"})
    assert result == "example.com"


# ---------------------------------------------------------------------------
# 2. substitute — ${UNKNOWN} kept as-is
# ---------------------------------------------------------------------------
def test_substitute_braced_var_unresolved_kept():
    result = substitute("${UNKNOWN}", {})
    assert result == "${UNKNOWN}"


# ---------------------------------------------------------------------------
# 3. substitute — ${VAR:-default} when VAR not set
# ---------------------------------------------------------------------------
def test_substitute_default_with_colon_dash_unset():
    result = substitute("${PORT:-8080}", {})
    assert result == "8080"


# ---------------------------------------------------------------------------
# 4. substitute — ${VAR:-default} when VAR is empty string
# ---------------------------------------------------------------------------
def test_substitute_default_with_colon_dash_empty():
    result = substitute("${VAR:-default}", {"VAR": ""})
    assert result == "default"


# ---------------------------------------------------------------------------
# 5. substitute — ${VAR:-default} when VAR is set and non-empty
# ---------------------------------------------------------------------------
def test_substitute_default_with_colon_dash_set():
    result = substitute("${HOST:-localhost}", {"HOST": "example.com"})
    assert result == "example.com"


# ---------------------------------------------------------------------------
# 6. substitute — ${VAR-default} when VAR not set
# ---------------------------------------------------------------------------
def test_substitute_default_with_dash_only_unset():
    result = substitute("${VAR-default}", {})
    assert result == "default"


# ---------------------------------------------------------------------------
# 7. substitute — ${VAR-default} when VAR is empty (dash-only treats empty as set)
# ---------------------------------------------------------------------------
def test_substitute_default_with_dash_only_set_empty():
    result = substitute("${VAR-default}", {"VAR": ""})
    assert result == ""


# ---------------------------------------------------------------------------
# 8. substitute — unbraced $VAR resolved
# ---------------------------------------------------------------------------
def test_substitute_plain_dollar_var():
    result = substitute("$HOST", {"HOST": "example.com"})
    assert result == "example.com"


# ---------------------------------------------------------------------------
# 9. substitute — mixed pattern string
# ---------------------------------------------------------------------------
def test_substitute_mixed():
    result = substitute(
        "Host=${HOST}, Port=${PORT:-8080}",
        {"HOST": "example.com"},
    )
    assert result == "Host=example.com, Port=8080"


# ---------------------------------------------------------------------------
# 10. deep_interpolate — nested dicts and lists
# ---------------------------------------------------------------------------
def test_deep_interpolate_nested():
    data: Dict[str, Any] = {
        "image": "${REGISTRY}/app:${TAG:-latest}",
        "environment": {
            "HOST": "${HOST}",
            "PORT": "${PORT:-8080}",
        },
        "labels": ["host=${HOST}"],
    }
    vars_map = {"REGISTRY": "ghcr.io", "HOST": "example.com"}
    result = deep_interpolate(data, vars_map)
    assert result == {
        "image": "ghcr.io/app:latest",
        "environment": {"HOST": "example.com", "PORT": "8080"},
        "labels": ["host=example.com"],
    }


# ---------------------------------------------------------------------------
# 11. parse_env_file — basic KEY=VALUE parsing
# ---------------------------------------------------------------------------
def test_parse_env_file_basic(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("HOST=example.com\nPORT=8080\n")
    result = parse_env_file(str(env_file))
    assert result == {"HOST": "example.com", "PORT": "8080"}


# ---------------------------------------------------------------------------
# 12. parse_env_file — ignores comments, blank lines, supports export prefix
# ---------------------------------------------------------------------------
def test_parse_env_file_ignores_comments_and_blanks(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        textwrap.dedent(
            """\
            # This is a comment
            HOST=example.com

            export PORT=8080
            # Another comment
            """
        )
    )
    result = parse_env_file(str(env_file))
    assert result == {"HOST": "example.com", "PORT": "8080"}


# ---------------------------------------------------------------------------
# 13. build_service_scope_vars — env_file then service.environment layering
# ---------------------------------------------------------------------------
def test_build_service_scope_vars_layering(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("HOST=envfile.example.com\nPORT=8000\n")

    service: Dict[str, Any] = {
        "env_file": str(env_file),
        "environment": {"HOST": "override.example.com"},
    }
    result = build_service_scope_vars(
        service, {"SHELL_VAR": "shell"}, str(tmp_path), None
    )
    assert result["HOST"] == "override.example.com"
    assert result["PORT"] == "8000"
    assert result["SHELL_VAR"] == "shell"
