#!/usr/bin/env python3
"""
Render a Docker Compose/Stack YAML by interpolating ${VAR}, ${VAR:-default}, ${VAR-default}
using per-service env_file(s), service.environment, and the current shell environment.

Why: docker stack deploy performs variable interpolation only from the shell/.env at project root.
It does NOT load variables from service-level env_file for interpolation, which breaks labels/commands
that reference ${...} defined in those files. This tool bridges that gap by producing a "rendered"
compose file where strings have been substituted ahead of deployment.

Usage:
    python3 tools/render_compose.py -i stacks/infrastructure.yml -o ./.rendered/docker-compose.infrastructure.rendered.yml

Notes:
    - Output can be placed under ./.rendered to keep the workspace clean (stackctl does this by default); relative paths are preserved.
  - Only string values are interpolated. Unresolved variables are left untouched by default with a warning.
  - Default expansion semantics:
      ${VAR} -> use VAR if defined, else leave as-is
      ${VAR-default} -> use VAR if defined, else use 'default' (empty VAR counts as defined)
      ${VAR:-default} -> use VAR if defined and non-empty, else use 'default'
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any, Dict, List, Mapping, Optional

try:
    import yaml  # type: ignore
except Exception as e:  # pragma: no cover
    sys.stderr.write(
        "ERROR: PyYAML is required. Install with: pip3 install -r tools/requirements.txt\n"
    )
    sys.exit(2)


VAR_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:(?P<sep>:-|-)\s*(?P<default>[^}]*))?\}")
# Also support unbraced $VAR pattern (no default support). Avoid $$ (escaped dollar) by negative lookbehind.
PLAIN_PATTERN = re.compile(r"(?<!\$)\$(?P<name2>[A-Za-z_][A-Za-z0-9_]*)")


def parse_env_file(path: str) -> Dict[str, str]:
    """Parse a .env file (simple KEY=VALUE lines) into a dict. Ignores comments and blanks."""
    result: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Support export KEY=VALUE
                if line.startswith("export "):
                    line = line[len("export ") :]
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                # strip surrounding quotes if present
                val = val.strip().strip("\n")
                if (val.startswith("\"") and val.endswith("\"")) or (
                    val.startswith("'") and val.endswith("'")
                ):
                    val = val[1:-1]
                result[key] = val
    except FileNotFoundError:
        raise
    except Exception as e:
        sys.stderr.write(f"Warning: failed parsing env file {path}: {e}\n")
    return result


def coerce_to_dict(env: Any) -> Dict[str, str]:
    """Normalize service.environment to a dict of strings when provided as either mapping or list."""
    result: Dict[str, str] = {}
    if env is None:
        return result
    if isinstance(env, Mapping):
        for k, v in env.items():
            if v is None:
                v = ""
            result[str(k)] = str(v)
    elif isinstance(env, list):
        for item in env:
            if isinstance(item, str) and "=" in item:
                k, v = item.split("=", 1)
                result[k] = v
            elif isinstance(item, str):
                # Bare keys mean inherit from the environment; skip here
                continue
    return result


def resolve_env_path(rel_path: str, project_dir: str, repo_root: Optional[str]) -> str:
    """Resolve a service env_file path, trying project_dir first then repo_root (if provided)."""
    # Absolute path: return as-is
    if os.path.isabs(rel_path):
        return rel_path
    # Try relative to the compose file directory
    cand = os.path.normpath(os.path.join(project_dir, rel_path))
    if os.path.isfile(cand):
        return cand
    # Try relative to the repository root (helps when stacks/ is used)
    if repo_root:
        # Normalize './' prefixes
        rel_norm = rel_path[2:] if rel_path.startswith("./") else rel_path
        cand2 = os.path.normpath(os.path.join(repo_root, rel_norm))
        if os.path.isfile(cand2):
            return cand2
    return cand  # fall back to project_dir join (will likely not exist)


def build_service_scope_vars(
    service: Dict[str, Any],
    base_env: Mapping[str, str],
    project_dir: str,
    repo_root: Optional[str],
) -> Dict[str, str]:
    """Build the variable map for a service, layering env_file(s) then service.environment over base_env."""
    vars_map: Dict[str, str] = dict(base_env)

    env_files: List[str] = []
    env_file_val = service.get("env_file")
    if isinstance(env_file_val, str):
        env_files = [env_file_val]
    elif isinstance(env_file_val, list):
        env_files = [e for e in env_file_val if isinstance(e, str)]

    for rel_path in env_files:
        env_path = resolve_env_path(rel_path, project_dir, repo_root)
        try:
            vars_map.update(parse_env_file(env_path))
        except FileNotFoundError:
            sys.stderr.write(f"Warning: env_file not found for service: {env_path}\n")

    # Overlay service.environment mapping (values as strings)
    vars_map.update(coerce_to_dict(service.get("environment")))
    return vars_map


def substitute(s: str, vars_map: Mapping[str, str]) -> str:
    """Perform ${VAR}, ${VAR-default}, ${VAR:-default} substitution.
    Unresolved variables are left as-is.
    """

    def repl(match: re.Match[str]) -> str:
        name = match.group("name")
        sep = match.group("sep")
        default = match.group("default")
        has = name in vars_map
        val = vars_map.get(name, "")

        if sep == ":-":
            # use default if unset or empty
            if not has or val == "":
                return default or ""
            return val
        elif sep == "-":
            # use default only if unset (empty counts as set)
            if not has:
                return default or ""
            return val
        else:
            # ${VAR}
            if has:
                return val
            # keep as-is if not found
            return match.group(0)

    out = VAR_PATTERN.sub(repl, s)

    # Handle plain $VAR (no default semantics). Keep as-is if not found.
    def repl_plain(match: re.Match[str]) -> str:
        name = match.group("name2")
        if name in vars_map:
            return vars_map[name]
        return match.group(0)

    out = PLAIN_PATTERN.sub(repl_plain, out)
    return out


def deep_interpolate(obj: Any, vars_map: Mapping[str, str]) -> Any:
    """Recursively interpolate all strings in a Python structure (dict/list/scalars)."""
    if isinstance(obj, str):
        return substitute(obj, vars_map)
    if isinstance(obj, list):
        return [deep_interpolate(x, vars_map) for x in obj]
    if isinstance(obj, dict):
        return {k: deep_interpolate(v, vars_map) for k, v in obj.items()}
    return obj


def render_compose(data: Dict[str, Any], project_dir: str, repo_root: Optional[str]) -> Dict[str, Any]:
    """Produce a new compose dict with per-service interpolation applied."""
    base_env = {k: v for k, v in os.environ.items()}

    services = data.get("services")
    if not isinstance(services, dict):
        return data

    rendered_services: Dict[str, Any] = {}
    for name, svc in services.items():
        if not isinstance(svc, dict):
            rendered_services[name] = svc
            continue
        scope_vars = build_service_scope_vars(svc, base_env, project_dir, repo_root)
        rendered_services[name] = deep_interpolate(svc, scope_vars)

    data = dict(data)
    data["services"] = rendered_services
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a compose file with per-service env interpolation")
    parser.add_argument("-i", "--input", required=True, help="Path to input compose YAML")
    parser.add_argument("-o", "--output", required=True, help="Path to write rendered YAML")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on unresolved ${VAR} references")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root for resolving service env_file paths (defaults to parent of input when input is under stacks/)",
    )
    args = parser.parse_args()

    in_path = os.path.abspath(args.input)
    out_path = os.path.abspath(args.output)
    project_dir = os.path.dirname(in_path)
    # Auto-detect repo root if not provided and input is under stacks/
    repo_root = args.repo_root
    if not repo_root:
        if os.path.basename(project_dir) == "stacks":
            repo_root = os.path.dirname(project_dir)
        else:
            repo_root = project_dir

    with open(in_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    rendered = render_compose(data, project_dir, repo_root)

    # Optional strict check
    if args.strict:
        text_dump = yaml.safe_dump(rendered, sort_keys=False)
        unresolved = VAR_PATTERN.findall(text_dump)
        if unresolved:
            names = ", ".join(sorted(set(n for (n, _sep, _def) in unresolved if n)))
            sys.stderr.write(f"ERROR: Unresolved variables remain: {names}\n")
            return 3

    # Ensure output directory exists
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(rendered, fh, sort_keys=False)

    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
