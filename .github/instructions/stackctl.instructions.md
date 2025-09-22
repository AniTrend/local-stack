---
applyTo: 'stackctl.sh'
description: Authoritative guidelines for editing the stack control script with safety, portability, and validation requirements.
---

# stackctl.sh Instructions

This file defines guardrails and expectations for any changes to `stackctl.sh`.

## Scope & Purpose
- `stackctl.sh` orchestrates Docker Swarm stacks in this repo and provides utilities for preflight checks, logs, and environment file management.
- The script must remain portable across macOS and Linux (default shells, minimal dependencies).

## Safety & Portability Requirements
1. Shell options
   - Keep `set -euo pipefail` and `IFS=$'\n\t'` at the top.
   - Do not add unguarded command substitutions that can break `-e` (use `|| true` where non-critical).
2. macOS compatibility
   - Avoid GNU-specific flags (e.g., `find -printf`, `sed -r`). Prefer POSIX patterns or guard with fallbacks.
   - Avoid Bash 4–specific features where possible (e.g., prefer while-read loops over `mapfile`).
3. No destructive defaults
   - Any operation that can overwrite user files (e.g., `.env`) must be opt-in (`--force`) and interactive unless `-y/--yes` is provided.
   - Always create timestamped backups before overwrites.
4. Rendering & secrets
   - Rendered compose files must be written to `${RENDER_DIR:-$SCRIPT_DIR/.rendered}` and never committed. The repo `.gitignore` must continue to ignore this directory.
   - Never print secret values in logs; prefer relative paths and summaries.
5. Network & swarm checks
   - Use `ensure_swarm_info` and `ensure_traefik_network` before deploy. Keep these idempotent and safe under `--dry-run`.

## Subcommands (behavioral contract)
- `up`: Renders compose files, deploys stacks, optionally follows logs. Honors `--dry-run` and `-s/--stacks`.
- `down`: Removes stacks, optional `--remove-network`. Honors `--dry-run` and `-y/--yes`.
- `status`: Lists services for selected stacks.
- `logs`: Follows logs for chosen services; cleans up background jobs on exit.
- `doctor`: Validates environment, network, and compose syntax (use rendered files when available).
- `env`: Lists or recreates `.env` files from `.env.example` with safeguards. Must print a summary report.

## Validation & Quality Gates
For any change to `stackctl.sh`, verify:
- Syntax: `bash -n stackctl.sh` returns no errors.
- Basic smoke: `./stackctl.sh help`, `./stackctl.sh doctor --fix-network` (non-destructive), and `./stackctl.sh env --list` succeed.
- On macOS, ensure no GNU-only flags are required. If used, provide a guarded fallback.
- Dry-run paths should not perform side effects.

## Logging & UX
- Keep logs concise and actionable. Prefix errors with `ERROR:` (via `err`).
- For long operations, echo intent first (e.g., “Deploying stack: …”).
- Summaries: `env` subcommand must print a concise summary (counts + key lists).

## Diff Discipline
- Prefer minimal, targeted edits; avoid wholesale rewrites unless necessary.
- Preserve existing behavior and flags; if introducing new flags, document them in `print_usage`.

## Examples (optional checks)
- Compose validation: `docker compose -f <rendered> config` (fallback to `docker-compose`).
- Rendered location: ensure files go to `.rendered/` and are ignored by Git.

## Security
- Do not echo sensitive values from `.env` or rendered compose files.
- Avoid commands that could leak credentials to shell history; follow terminal usage guidelines.
