#!/usr/bin/env python3
"""
Local-Stack Python CLI for Swarm stacks

Goals
- Provide a single, portable Python entrypoint to render, deploy, teardown, and inspect stacks
- Support multi-environment overlays and per-service env_file interpolation (reusing tools/render_compose.py)
- Add safe secret workflows via SOPS without exposing plaintext in VCS

This CLI intentionally shells out to Docker where appropriate to avoid re-implementing Swarm semantics.

Usage (examples):
  python3 tools/stackctl_cli.py render --env local
  python3 tools/stackctl_cli.py deploy --stacks infrastructure,observability --env local
  python3 tools/stackctl_cli.py down --stacks platform
  python3 tools/stackctl_cli.py env list
  python3 tools/stackctl_cli.py secrets decrypt --in apisix/api-gateway/.env.enc.yaml --out apisix/api-gateway/.env

Notes
- Rendered files are written to ./.rendered by default and are git-ignored in this repo.
- Overlays: if --env <name> is provided, we will look for:
    environments/<name>/<stack>.overlay.yml (or .yaml) and deep-merge onto stacks/<stack>.yml
  Unknown overlays are ignored with a warning (non-fatal).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table
import yaml

# Optional dependency for deep merges; graceful fallback to a simple merge
try:
    from mergedeep import merge as deep_merge  # type: ignore
except Exception:  # pragma: no cover
    def deep_merge(dst, src, strategy=None):
        """Minimal deep merge fallback: recursively overlay dicts, replace lists/scalars."""
        if not isinstance(dst, dict) or not isinstance(src, dict):
            return src
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                deep_merge(dst[k], v)
            else:
                dst[k] = v
        return dst


APP = typer.Typer(help="Local-Stack management CLI (Swarm)")
console = Console(stderr=True)

REPO_ROOT = Path(__file__).resolve().parents[1]
STACKS_DIR = REPO_ROOT / "stacks"
RENDER_DIR = Path(os.environ.get("RENDER_DIR", REPO_ROOT / ".rendered"))
DEFAULT_STACKS = ["infrastructure", "observability", "platform"]
DEFAULT_LOG_SERVICES = [
    "observability_prometheus",
    "observability_loki",
    "infrastructure_traefik",
]


def require_cmd(cmd: str) -> None:
    if shutil.which(cmd) is None:
        raise typer.Exit(code=2)


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and stream output; returns CompletedProcess."""
    console.log(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def stack_file_for(name: str) -> Optional[Path]:
    for ext in ("yml", "yaml"):
        cand = STACKS_DIR / f"{name}.{ext}"
        if cand.is_file():
            return cand
    return None


def overlay_file_for(env: Optional[str], stack: str) -> Optional[Path]:
    if not env:
        return None
    base = REPO_ROOT / "environments" / env
    for ext in ("yml", "yaml"):
        cand = base / f"{stack}.overlay.{ext}"
        if cand.is_file():
            return cand
    return None


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def save_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def render_with_env_interpolation(base_path: Path, out_path: Path, repo_root: Path) -> Path:
    """Reuse the existing render_compose.py to resolve per-service env vars and absolutize paths."""
    render_script = REPO_ROOT / "tools" / "render_compose.py"
    if not render_script.is_file():
        raise typer.BadParameter("tools/render_compose.py not found")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(render_script),
        "-i",
        str(base_path),
        "-o",
        str(out_path),
        "--repo-root",
        str(repo_root),
    ]
    console.log(f"Rendering compose with env interpolation -> {out_path}")
    subprocess.run(cmd, check=True)
    return out_path


def deep_merge_overlay(base_data: dict, overlay_path: Optional[Path]) -> dict:
    if overlay_path and overlay_path.is_file():
        overlay = load_yaml(overlay_path)
        deep_merge(base_data, overlay)
    return base_data


@APP.command()
def render(
    stacks: str = typer.Option(
        ",".join(DEFAULT_STACKS), "--stacks", "-s", help="Comma-separated list of stacks to render"
    ),
    env: Optional[str] = typer.Option(None, "--env", help="Environment overlay name (environments/<env>/...)"),
    strict: bool = typer.Option(False, "--strict", help="Fail if unresolved ${VAR} remain after render"),
):
    """Render selected stacks to ./.rendered with per-service env interpolation and optional overlays."""
    selected = [s.strip() for s in stacks.split(",") if s.strip()]
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    results: List[Tuple[str, Path]] = []
    for stack in selected:
        src = stack_file_for(stack)
        if not src:
            console.print(f"[yellow]Skip[/yellow] stack '{stack}' (file not found)")
            continue
        # Apply overlay first (in-memory), then feed to render_compose for env substitution
        base = load_yaml(src)
        base = deep_merge_overlay(base, overlay_file_for(env, stack))
        # Write a temp merged file for interpolation
        merged_tmp = RENDER_DIR / f"docker-compose.{stack}.merged.yml"
        save_yaml(merged_tmp, base)
        out_path = RENDER_DIR / f"docker-compose.{stack}.rendered.yml"
        render_with_env_interpolation(merged_tmp, out_path, REPO_ROOT)
        if strict:
            text = out_path.read_text(encoding="utf-8")
            # naive unresolved check
            if "${" in text:
                console.print(f"[red]Unresolved variables remain in {out_path}[/red]")
                raise typer.Exit(code=3)
        results.append((stack, out_path))

    table = Table(title="Rendered Stacks")
    table.add_column("Stack")
    table.add_column("Path")
    for name, path in results:
        table.add_row(name, str(path))
    console.print(table)


def ensure_swarm() -> None:
    try:
        out = subprocess.check_output(["docker", "info", "--format", "{{.Swarm.LocalNodeState}}"], text=True)
    except Exception:
        console.print("[red]Docker not available[/red]")
        raise typer.Exit(code=2)
    if out.strip() != "active":
        console.print("[yellow]Swarm is not active on this host. Run: docker swarm init[/yellow]")


def ensure_network() -> None:
    try:
        out = subprocess.check_output(["docker", "network", "ls", "--format", "{{.Name}}"], text=True)
        if "traefik-public" not in out.splitlines():
            console.print("[cyan]Creating overlay network traefik-public[/cyan]")
            subprocess.run(["docker", "network", "create", "--driver=overlay", "--attachable", "traefik-public"], check=False)
    except Exception:
        pass


@APP.command()
def deploy(
    stacks: str = typer.Option(
        ",".join(DEFAULT_STACKS), "--stacks", "-s", help="Comma-separated list of stacks to deploy"
    ),
    env: Optional[str] = typer.Option(None, "--env", help="Environment overlay name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Only render and validate, do not deploy"),
    follow_logs: bool = typer.Option(
        False,
        "--follow-logs/--no-follow-logs",
        help="After deploy, follow logs for default services",
    ),
):
    """Render and deploy stacks via docker stack deploy."""
    ensure_swarm()
    ensure_network()
    selected = [s.strip() for s in stacks.split(",") if s.strip()]
    # Render first
    for stack in selected:
        src = stack_file_for(stack)
        if not src:
            console.print(f"[yellow]Skip[/yellow] stack '{stack}' (file not found)")
            continue
        base = load_yaml(src)
        base = deep_merge_overlay(base, overlay_file_for(env, stack))
        merged_tmp = RENDER_DIR / f"docker-compose.{stack}.merged.yml"
        save_yaml(merged_tmp, base)
        out_path = RENDER_DIR / f"docker-compose.{stack}.rendered.yml"
        render_with_env_interpolation(merged_tmp, out_path, REPO_ROOT)
        # Validate compose syntax
        cmd = ["docker", "compose", "-f", str(out_path), "config"]
        if dry_run:
            console.print(f"[cyan]DRY-RUN[/cyan] validate: {' '.join(cmd)}")
            subprocess.run(cmd, check=False)
        else:
            subprocess.run(cmd, check=False)
            console.print(f"[green]Deploying[/green] stack: {stack}")
            run(["docker", "stack", "deploy", "-c", str(out_path), stack], check=False)

    # Show services summary
    if not dry_run:
        for stack in selected:
            console.print(f"\n[b]Services in {stack}[/b]")
            run(["docker", "stack", "services", stack], check=False)
        if follow_logs:
            console.print("\n[cyan]Following logs for default services[/cyan]")
            for svc in DEFAULT_LOG_SERVICES:
                try:
                    console.print(f"[b]$ docker service logs -f {svc}[/b]")
                    run(["docker", "service", "logs", "-f", svc], check=False)
                except KeyboardInterrupt:  # pragma: no cover
                    break


@APP.command()
def logs(services: List[str] = typer.Argument(None, help="Services to follow (default preset)")):
    """Follow logs for services (docker service logs -f)."""
    svcs = services or DEFAULT_LOG_SERVICES
    for svc in svcs:
        console.print(f"[b]$ docker service logs -f {svc}[/b]")
        try:
            run(["docker", "service", "logs", "-f", svc], check=False)
        except KeyboardInterrupt:  # pragma: no cover
            break


@APP.command()
def down(
    stacks: str = typer.Option(
        ",".join(DEFAULT_STACKS), "--stacks", "-s", help="Comma-separated list of stacks to remove"
    ),
    remove_network: bool = typer.Option(False, "--remove-network", help="Attempt to remove traefik-public after removal"),
):
    """Remove stacks (docker stack rm)."""
    selected = [s.strip() for s in stacks.split(",") if s.strip()]
    for stack in selected:
        console.print(f"[green]Removing[/green] stack: {stack}")
        run(["docker", "stack", "rm", stack], check=False)
    if remove_network:
        run(["docker", "network", "rm", "traefik-public"], check=False)


@APP.command()
def status(
    stacks: str = typer.Option(
        ",".join(DEFAULT_STACKS), "--stacks", "-s", help="Comma-separated list of stacks"
    ),
):
    """List services for stacks."""
    selected = [s.strip() for s in stacks.split(",") if s.strip()]
    for stack in selected:
        console.print(f"\n[b]Services in {stack}[/b]")
        run(["docker", "stack", "services", stack], check=False)


env_app = typer.Typer(help=".env management")
APP.add_typer(env_app, name="env")


def discover_env_example_dirs(root: Path) -> List[Path]:
    return [p.parent for p in root.rglob(".env.example")]


@env_app.command("list")
def env_list(paths: Optional[str] = typer.Option(None, "--paths", help="Comma-separated paths to scan")):
    """List directories that have .env.example and whether .env exists."""
    dirs: List[Path] = []
    if paths:
        for tok in paths.split(","):
            tok = tok.strip()
            if not tok:
                continue
            p = (REPO_ROOT / tok).resolve()
            if p.is_file():
                dirs.append(p.parent)
            elif p.is_dir():
                dirs.append(p)
    else:
        dirs = discover_env_example_dirs(REPO_ROOT)

    rows: List[Tuple[str, str]] = []
    for d in sorted(set(dirs)):
        ex = d / ".env.example"
        cur = d / ".env"
        if ex.is_file():
            status = "OK (.env present)" if cur.is_file() else "MISSING (.env)"
        else:
            status = "SKIP (no .env.example)"
        rows.append((str(d.relative_to(REPO_ROOT)), status))

    table = Table(title=".env scan")
    table.add_column("Directory")
    table.add_column("Status")
    for a, b in rows:
        table.add_row(a, b)
    console.print(table)


@env_app.command("recreate")
def env_recreate(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing .env after backup"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive"),
    paths: Optional[str] = typer.Option(None, "--paths", help="Comma-separated paths to process"),
):
    """Create or overwrite .env from .env.example safely."""
    targets = discover_env_example_dirs(REPO_ROOT) if not paths else [
        ((REPO_ROOT / p.strip()).resolve()) for p in paths.split(",") if p.strip()
    ]
    created, overwritten, skipped, missing = [], [], [], []
    for d in targets:
        ex, envp = d / ".env.example", d / ".env"
        if not ex.is_file():
            missing.append(str(d))
            continue
        if envp.exists() and not force:
            skipped.append(str(envp))
            continue
        if envp.exists() and force:
            if not yes:
                resp = input(f"Overwrite {envp}? [y/N]: ")
                if resp.lower() not in ("y", "yes"):
                    skipped.append(str(envp))
                    continue
            backup = envp.with_suffix(envp.suffix + f".bak.{int(time.time())}")
            shutil.copy2(envp, backup)
            shutil.copy2(ex, envp)
            overwritten.append(str(envp))
        else:
            shutil.copy2(ex, envp)
            created.append(str(envp))
    rprint({
        "created": created,
        "overwritten": overwritten,
        "skipped": skipped,
        "missing_example": missing,
    })


secrets_app = typer.Typer(help="SOPS helper commands")
APP.add_typer(secrets_app, name="secrets")


@secrets_app.command("decrypt")
def secrets_decrypt(
    input_path: Path = typer.Option(..., "--in", help="Encrypted input file (e.g., .env.enc.yaml)"),
    output_path: Path = typer.Option(..., "--out", help="Destination plaintext file (e.g., .env)"),
    overwrite: bool = typer.Option(False, "--force", help="Overwrite output if exists"),
):
    """Decrypt a SOPS-managed file to a local plaintext file. Will never print secret contents."""
    if shutil.which("sops") is None:
        console.print("[red]sops CLI not found. Install from https://github.com/mozilla/sops[/red]")
        raise typer.Exit(code=2)
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    if output_path.exists() and not overwrite:
        console.print(f"[yellow]Refusing to overwrite existing {output_path}. Use --force to overwrite.[/yellow]")
        raise typer.Exit(code=1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Write directly to file to avoid secrets in stdout
    with output_path.open("wb") as fh:
        subprocess.run(["sops", "-d", str(input_path)], check=True, stdout=fh)
    console.print(f"[green]Decrypted[/green] -> {output_path}")


@secrets_app.command("encrypt")
def secrets_encrypt(
    input_path: Path = typer.Option(..., "--in", help="Plaintext input file (e.g., .env)"),
    output_path: Optional[Path] = typer.Option(None, "--out", help="Encrypted output file (e.g., .env.enc.yaml)"),
):
    """Encrypt a plaintext file using SOPS, honoring .sops.yaml policy in the repo root if present."""
    if shutil.which("sops") is None:
        console.print("[red]sops CLI not found. Install from https://github.com/mozilla/sops[/red]")
        raise typer.Exit(code=2)
    input_path = input_path.resolve()
    if output_path is None:
        output_path = input_path.with_suffix(input_path.suffix + ".enc.yaml")
    output_path = output_path.resolve()
    run(["sops", "-e", str(input_path), "-o", str(output_path)], check=True)
    console.print(f"[green]Encrypted[/green] -> {output_path}")


doctor_app = typer.Typer(help="Preflight checks")
APP.add_typer(doctor_app, name="doctor")


@doctor_app.command("run")
def doctor_run(fix_network: bool = typer.Option(False, "--fix-network")):
    """Validate docker availability, swarm state, traefik-public network, and stack files."""
    # docker
    if shutil.which("docker") is None:
        console.print("[red]docker not found on PATH[/red]")
        raise typer.Exit(code=2)
    try:
        out = subprocess.check_output(["docker", "compose", "version"], text=True)
        console.print("compose: available")
    except Exception:
        console.print("compose: not available, will try docker-compose if needed")
    ensure_swarm()
    # network
    try:
        nets = subprocess.check_output(["docker", "network", "ls", "--format", "{{.Name}}"], text=True).splitlines()
        if "traefik-public" in nets:
            console.print("network: traefik-public exists")
        else:
            console.print("network: traefik-public missing")
            if fix_network:
                ensure_network()
    except Exception:
        pass
    # stacks
    for stack in DEFAULT_STACKS:
        sf = stack_file_for(stack)
        if sf:
            console.print(f"stack: found {sf}")
            # best-effort validation
            subprocess.run(["docker", "compose", "-f", str(sf), "config"], check=False)
        else:
            console.print(f"[yellow]stack: missing file for {stack}[/yellow]")


def main() -> int:
    APP()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
