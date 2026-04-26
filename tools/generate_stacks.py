#!/usr/bin/env python3
"""
Generate Docker Swarm stack YAML files from per-service docker-compose files.

Discovers all docker-compose.yml/yaml files with an ``x-stack:`` extension field,
deep-merges each with its sibling ``swarm.fragment.yml`` (if present), strips
Compose-only keys, injects safe logging defaults, rewrites paths to be repo-root
relative, and writes one YAML per stack under ``stacks/``.

``${VAR}`` placeholders in labels/commands/healthchecks are intentionally kept
as-is so that no secret values are committed.  A separate render step
(``tools/render_compose.py``, called by ``stackctl.sh up``) substitutes them
at deploy time into ``.rendered/``, which is git-ignored.

Usage:
    python3 tools/generate_stacks.py [options]

    -s, --stacks    Comma-separated stack names (default: infrastructure,observability,platform)
    --repo-root     Repository root (default: parent of tools/)
    --output-dir    Directory to write stack files (default: <repo-root>/stacks)
    --dry-run       Print to stdout, do not write files
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Set, Tuple, cast

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: PyYAML is required. pip3 install PyYAML\n")
    sys.exit(2)


class _IndentedSafeDumper(yaml.SafeDumper):
    """PyYAML dumper that indents list items under their parent key.

    Default PyYAML formatting emits:
        key:
        - item

    We prefer:
        key:
          - item
    """

    def increase_indent(self, flow=False, indentless=False):  # type: ignore[override]
        return super().increase_indent(flow, False)

# ---------------------------------------------------------------------------
# Public functions (also imported by tests)
# ---------------------------------------------------------------------------

COMPOSE_ONLY_SERVICE_KEYS: Set[str] = {"container_name", "restart", "build"}

_DEFAULT_LOGGING: Dict[str, Any] = {
    "driver": "local",
    "options": {
        "max-size": "10m",
        "max-file": 3,
    },
}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* into *base*.

    Rules:
    - Dicts: merged recursively (override wins on scalar conflicts).
    - Lists: override **replaces** base (no appending).
    - Scalars: override wins.

    Neither argument is mutated; a new dict is returned.
    """
    result: Dict[str, Any] = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(cast(Dict[str, Any], result[key]), cast(Dict[str, Any], val))
        else:
            # Scalars and lists: override replaces
            result[key] = val
    return result


def strip_compose_only_keys(service: Dict[str, Any]) -> Dict[str, Any]:
    """Remove keys from a service dict that are invalid in Docker Swarm.

    Removes: ``container_name``, ``restart``, ``build``.
    All other keys are preserved unchanged.
    """
    return {k: v for k, v in service.items() if k not in COMPOSE_ONLY_SERVICE_KEYS}


def collect_named_volumes(volumes: List[Any]) -> Set[str]:
    """Return the set of named volume names from a service ``volumes:`` list.

    A volume is *named* (not a bind mount) when its source does **not** start
    with ``.``, ``/``, or ``~``.  Only the part before the first ``:`` is used.
    """
    named: Set[str] = set()
    for v in (volumes or []):
        if isinstance(v, str):
            src = v.split(":")[0]
            if not (src.startswith(".") or src.startswith("/") or src.startswith("~")):
                named.add(src)
        elif isinstance(v, dict):
            vd = cast(Dict[str, Any], v)
            if vd.get("type") == "volume":
                src = vd.get("source")
                if src:
                    named.add(str(src))
    return named


def apply_logging_defaults(service: Dict[str, Any]) -> Dict[str, Any]:
    """Inject ``_DEFAULT_LOGGING`` into *service* when no ``logging:`` block is present.

    This ensures every Swarm service has a bounded log rotation policy baked
    into the generated stack file, regardless of whether the source compose
    file defined one.  Existing ``logging:`` blocks are never overwritten.
    """
    if "logging" not in service:
        service = dict(service)
        service["logging"] = _DEFAULT_LOGGING
    return service


def load_compose(path: str) -> Tuple[Dict[str, Any], str]:
    """Load a docker-compose YAML file and extract the ``x-stack:`` value.

    Returns ``(data, stack_name)`` where *data* is the parsed YAML dict with
    the ``x-stack`` key removed.

    Raises ``ValueError`` if ``x-stack`` is not present.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data: Dict[str, Any] = yaml.safe_load(fh) or {}

    if "x-stack" not in data:
        raise ValueError(f"No 'x-stack:' field in {path}")

    stack_name: str = data.pop("x-stack")
    return data, stack_name


def load_fragment(directory: str) -> Dict[str, Any]:
    """Load ``swarm.fragment.yml`` from *directory*, returning ``{}`` if absent."""
    frag_path = os.path.join(directory, "swarm.fragment.yml")
    if not os.path.isfile(frag_path):
        return {}
    with open(frag_path, "r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    return cast(Dict[str, Any], loaded) if isinstance(loaded, dict) else {}


def _rewrite_env_file(service: Dict[str, Any], project_dir: str, repo_root: str) -> Dict[str, Any]:
    """Rewrite ``env_file`` paths so they are relative to *repo_root* (not *project_dir*).

    ``docker stack deploy`` is run from the repo root, so paths in the final
    stack YAML must be expressed relative to that location.
    """
    if "env_file" not in service:
        return service

    def _to_repo_rel(path: str) -> str:
        if os.path.isabs(path):
            return path
        clean = path[2:] if path.startswith("./") else path
        abs_path = os.path.normpath(os.path.join(project_dir, clean))
        rel = os.path.relpath(abs_path, repo_root)
        return "./" + rel

    service = dict(service)
    ef = service["env_file"]
    if isinstance(ef, str):
        service["env_file"] = _to_repo_rel(ef)
    elif isinstance(ef, list):
        ef_list = cast(List[Any], ef)
        service["env_file"] = [_to_repo_rel(e) if isinstance(e, str) else e for e in ef_list]
    return service


def _rewrite_bind_mount_paths(service: Dict[str, Any], project_dir: str, repo_root: str) -> Dict[str, Any]:
    """Rewrite relative bind-mount source paths to be relative to *repo_root*."""
    if "volumes" not in service:
        return service

    def _to_repo_rel(src: str) -> str:
        if os.path.isabs(src):
            return src
        clean = src[2:] if src.startswith("./") else src
        abs_path = os.path.normpath(os.path.join(project_dir, clean))
        rel = os.path.relpath(abs_path, repo_root)
        return "./" + rel

    service = dict(service)
    new_vols: List[Any] = []
    for v in cast(List[Any], service["volumes"]):
        if isinstance(v, str):
            parts = v.split(":")
            src = parts[0]
            if src.startswith(".") or (src.startswith("/") is False and "/" in src and not src.startswith("~")):
                # relative bind mount
                if src.startswith("."):
                    parts[0] = _to_repo_rel(src)
                    v = ":".join(parts)
            new_vols.append(v)
        elif isinstance(v, dict):
            vd0 = cast(Dict[str, Any], v)
            if vd0.get("type") != "bind":
                new_vols.append(vd0)
                continue
            vd = dict(vd0)
            src = vd.get("source", "")
            src_s = str(src)
            if not os.path.isabs(src_s):
                vd["source"] = _to_repo_rel(src_s)
            new_vols.append(vd)
        else:
            new_vols.append(v)
    service["volumes"] = new_vols
    return service

def generate_stack(
    stack_name: str,
    compose_paths: List[str],
    repo_root: str,
) -> Dict[str, Any]:
    """Build a Swarm stack dict from a list of compose file paths.

    Steps for each compose file:
    1. Load compose + fragment, deep-merge them.
    2. Strip Compose-only service keys (container_name, restart, build).
    3. Inject safe logging defaults for services that have no ``logging:`` block.
    4. Rewrite relative ``env_file`` and bind-mount paths to be repo-root relative.
    5. Collect named volumes (with any ``name:`` metadata from top-level volumes).

    ``${VAR}`` placeholders in labels/commands/healthchecks are preserved as-is.
    They are substituted at deploy time by ``tools/render_compose.py``, which
    reads per-service ``env_file``(s) and writes to ``.rendered/`` (git-ignored).

    Returns a dict suitable for YAML serialisation with top-level ``volumes:``,
    ``networks:``, and ``services:`` keys.
    """
    all_services: Dict[str, Any] = {}
    # volume_key -> optional metadata dict (may contain 'name' override)
    all_volume_meta: Dict[str, Dict[str, Any]] = {}

    for compose_path in sorted(compose_paths):
        project_dir = os.path.dirname(os.path.abspath(compose_path))

        # --- load compose + fragment ---
        try:
            data, _ = load_compose(compose_path)
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"Warning: skipping {compose_path}: {exc}\n")
            continue

        fragment = load_fragment(project_dir)
        merged = deep_merge(data, fragment)

        # --- top-level volume metadata (name overrides) ---
        top_vol_raw = data.get("volumes")
        top_volumes: Dict[str, Any] = cast(Dict[str, Any], top_vol_raw) if isinstance(top_vol_raw, dict) else {}

        # --- process services ---
        services_raw_any = merged.get("services")
        services_raw: Dict[str, Any] = cast(Dict[str, Any], services_raw_any) if isinstance(services_raw_any, dict) else {}
        for svc_name, svc in services_raw.items():
            if not isinstance(svc, dict):
                all_services[svc_name] = svc
                continue
            svc_dict = cast(Dict[str, Any], svc)

            # Strip compose-only keys
            svc = strip_compose_only_keys(svc_dict)

            # Inject logging defaults (no-op if service already has logging:)
            svc = apply_logging_defaults(svc)

            # Rewrite paths (env_file + bind mounts) to be repo-root relative
            svc = _rewrite_env_file(svc, project_dir, repo_root)
            svc = _rewrite_bind_mount_paths(svc, project_dir, repo_root)

            # Collect named volumes for this service
            for vol_key in sorted(collect_named_volumes(svc.get("volumes", []))):
                if vol_key not in all_volume_meta:
                    meta = top_volumes.get(vol_key)
                    all_volume_meta[vol_key] = meta if isinstance(meta, dict) else {}

            all_services[svc_name] = svc

        # Also register volumes from the top-level volumes section that
        # correspond to named volumes used by ANY service in this file
        # (handles cases where volume key differs from mount source — e.g. postgres 'data')
        for vol_key in top_volumes:
            if vol_key not in all_volume_meta:
                # Only include if referenced by a service volume mount
                pass  # already handled above via collect_named_volumes

    # --- assemble output ---
    output: Dict[str, Any] = {}

    # volumes block
    if all_volume_meta:
        volumes_out: Dict[str, Any] = {}
        for vol_key in sorted(all_volume_meta):
            meta = all_volume_meta[vol_key]
            entry: Dict[str, Any] = {"external": True}
            if meta and meta.get("name"):
                entry["name"] = meta["name"]
            volumes_out[vol_key] = entry
        output["volumes"] = volumes_out

    # fixed networks block
    output["networks"] = {
        "default": {
            "name": "traefik-public",
            "external": True,
        }
    }

    output["services"] = all_services

    return output


def _discover_compose_files(repo_root: str) -> Dict[str, List[str]]:
    """Walk *repo_root* and return a dict mapping stack_name -> [compose_paths]."""
    stacks: Dict[str, List[str]] = {}
    for dirpath, dirnames, filenames in os.walk(repo_root):
        # Skip hidden dirs, node_modules, .rendered, stacks/, tools/, environments/
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".")
            and d not in {"node_modules", "stacks", "tools", "environments", "__pycache__"}
        )
        for fname in ("docker-compose.yml", "docker-compose.yaml"):
            if fname not in filenames:
                continue
            compose_path = os.path.join(dirpath, fname)
            try:
                with open(compose_path, "r", encoding="utf-8") as fh:
                    loaded = yaml.safe_load(fh)
                data: Dict[str, Any] = cast(Dict[str, Any], loaded) if isinstance(loaded, dict) else {}
                stack_name = data.get("x-stack")
                if not stack_name:
                    continue
                stacks.setdefault(stack_name, []).append(compose_path)
            except Exception as exc:
                sys.stderr.write(f"Warning: could not read {compose_path}: {exc}\n")
    return stacks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Docker Swarm stack YAML files from service compose files."
    )
    parser.add_argument(
        "-s",
        "--stacks",
        default="infrastructure,observability,platform",
        help="Comma-separated stack names to generate (default: infrastructure,observability,platform)",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root path (default: parent of tools/)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write stack files (default: <repo-root>/stacks)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated YAML to stdout, do not write files",
    )
    args = parser.parse_args()

    # Resolve repo root
    repo_root = args.repo_root
    if not repo_root:
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.abspath(repo_root)

    output_dir = args.output_dir or os.path.join(repo_root, "stacks")
    target_stacks = [s.strip() for s in args.stacks.split(",") if s.strip()]

    # Discover all compose files grouped by stack
    sys.stderr.write(f"Discovering compose files under {repo_root} ...\n")
    stack_map = _discover_compose_files(repo_root)

    for stack_name in target_stacks:
        compose_files = stack_map.get(stack_name, [])
        if not compose_files:
            sys.stderr.write(f"Warning: no compose files found for stack '{stack_name}'\n")
            continue

        sys.stderr.write(
            f"Generating '{stack_name}' from {len(compose_files)} compose file(s):\n"
        )
        for p in sorted(compose_files):
            sys.stderr.write(f"  {os.path.relpath(p, repo_root)}\n")

        stack_data = generate_stack(stack_name, compose_files, repo_root)

        yaml_str = yaml.dump(
            stack_data,
            Dumper=_IndentedSafeDumper,
            default_flow_style=False,
            indent=2,
            sort_keys=False,
            allow_unicode=True,
        )

        if args.dry_run:
            print(f"# --- stack: {stack_name} ---")
            print(yaml_str)
        else:
            os.makedirs(output_dir, exist_ok=True)
            out_path = os.path.join(output_dir, f"{stack_name}.yml")
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(f"# Generated by tools/generate_stacks.py — do not edit manually.\n")
                fh.write(yaml_str)
            sys.stderr.write(f"  -> wrote {os.path.relpath(out_path, repo_root)}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
