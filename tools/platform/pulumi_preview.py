#!/usr/bin/env python3
"""Run an explicitly selected non-mutating platform Pulumi preview."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Optional, Sequence
from urllib.parse import urlsplit


ENVIRONMENTS = ("lab", "rehearsal", "production")


def _pulumi_binary(repo_root: Path) -> Path:
    configured = os.environ.get("PLATFORM_PULUMI_BIN", "pulumi")
    candidate = Path(configured)
    if candidate.is_absolute():
        binary = candidate
    elif candidate.parent != Path("."):
        binary = (repo_root / candidate).resolve()
    else:
        discovered = shutil.which(configured)
        if discovered is None:
            raise RuntimeError("the pinned Pulumi CLI is unavailable")
        binary = Path(discovered)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError("the pinned Pulumi CLI is unavailable")
    return binary


def _verify_pulumi_version(repo_root: Path, binary: Path) -> None:
    try:
        expected = (repo_root / "tools" / "platform" / "pulumi-version.txt").read_text(encoding="utf-8").strip()
        result = subprocess.run(
            [str(binary), "version"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("the pinned Pulumi CLI could not be verified") from error
    observed = result.stdout.strip()
    if observed.startswith("v"):
        observed = observed[1:]
    if result.returncode != 0 or not expected or observed != expected:
        raise RuntimeError("Pulumi CLI version does not match the repository pin")

def _verify_pulumi_backend(project_dir: Path, binary: Path) -> None:
    try:
        result = subprocess.run(
            [str(binary), "whoami", "--verbose", "--non-interactive", "--color=never"],
            cwd=project_dir,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Pulumi backend identity could not be verified") from error
    backend_url = next(
        (line.split(":", 1)[1].strip() for line in result.stdout.splitlines() if line.startswith("Backend URL:")),
        "",
    )
    parsed_backend = urlsplit(backend_url)
    if (
        result.returncode != 0
        or parsed_backend.scheme != "https"
        or parsed_backend.hostname not in {"api.pulumi.com", "app.pulumi.com"}
    ):
        raise RuntimeError("HCloud previews require the approved Pulumi Cloud state backend")


def _run_preview(environment: str, repo_root: Path) -> int:
    if environment == "lab":
        command = [
            sys.executable,
            str(repo_root / "tools" / "platform" / "lab.py"),
            "preview",
            "--environment",
            "lab",
            "--repo-root",
            str(repo_root),
        ]
        return subprocess.run(command, cwd=repo_root, check=False, timeout=1800).returncode

    project_dir = repo_root / "infra" / "pulumi" / "hcloud"
    if not (project_dir / "Pulumi.yaml").is_file():
        raise RuntimeError("the HCloud Pulumi project is missing")
    if not (project_dir / "node_modules" / "@pulumi" / "hcloud").is_dir():
        raise RuntimeError("install the locked HCloud project dependencies with npm ci")

    binary = _pulumi_binary(repo_root)
    _verify_pulumi_version(repo_root, binary)
    _verify_pulumi_backend(project_dir, binary)
    return subprocess.run(
        [
            str(binary),
            "preview",
            "--diff",
            "--non-interactive",
            "--stack",
            environment,
        ],
        cwd=project_dir,
        check=False,
        timeout=1800,
    ).returncode


def main(arguments: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run a non-mutating platform Pulumi preview")
    parser.add_argument("--environment", required=True, choices=ENVIRONMENTS)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    options = parser.parse_args(arguments)
    try:
        return _run_preview(options.environment, options.repo_root.resolve())
    except RuntimeError as error:
        print("error: " + str(error), file=sys.stderr)
        return 2
    except OSError:
        print("error: a local Pulumi preview operation failed", file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired:
        print("error: Pulumi preview exceeded its timeout", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
