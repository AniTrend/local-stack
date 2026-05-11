---
name: project-stackctl-changes
description: Use when modifying stackctl.sh and you need the repo-specific safety, portability, and validation rules for stack orchestration changes
metadata:
  migrated-from: .github/instructions/stackctl.instructions.md
  source-format: .instructions.md
---

# Project stackctl Changes

## Overview

`stackctl.sh` orchestrates rendering, deployment, diagnostics, and environment file management for Swarm stacks in this repo. Changes must stay portable across macOS and Linux, safe by default, and quiet about secrets.

## When to Use

- Before editing `stackctl.sh`.
- When adding or changing subcommands, flags, rendering paths, or Swarm preflight behavior.
- When validating shell portability for repo automation on macOS and Linux.

## Core Pattern

1. Preserve shell safety guards: keep `set -euo pipefail` and `IFS=$'\n\t'`.
2. Prefer POSIX-safe or guarded shell features so the script keeps working on macOS.
3. Make destructive behavior opt-in. Overwrites need `--force`, interactive confirmation unless `-y/--yes`, and timestamped backups.
4. Write rendered compose files to `${RENDER_DIR:-$SCRIPT_DIR/.rendered}` and never print secret values.
5. Keep `ensure_swarm_info` and `ensure_traefik_network` in the deployment path, including dry-run-safe behavior.
6. Preserve the behavioral contract of `up`, `down`, `status`, `logs`, `doctor`, and `env`.

## Behavioral Contract

| Subcommand | Required behavior |
| --- | --- |
| `up` | Render compose files, deploy stacks, optionally follow logs, honor `--dry-run` and stack selection |
| `down` | Remove stacks, optionally remove network, honor `--dry-run` and `-y/--yes` |
| `status` | List services for selected stacks |
| `logs` | Follow logs for chosen services and clean up background jobs on exit |
| `doctor` | Validate environment, network, and compose syntax |
| `env` | List or recreate `.env` files from examples with safeguards and a summary report |

## Validation

Run these after any `stackctl.sh` change:

```bash
bash -n stackctl.sh
./stackctl.sh help
./stackctl.sh doctor --fix-network
./stackctl.sh env --list
```

## Common Mistakes

- Introducing GNU-only flags without a macOS-safe fallback.
- Writing rendered output outside `.rendered/` or logging secret values.
- Making overwrite behavior implicit instead of opt-in.
- Breaking dry-run mode with side effects.
- Rewriting large portions of the script instead of using minimal targeted edits.

## See Also

- [AGENTS.md](../../../AGENTS.md)
- [stacks/README.md](../../../stacks/README.md)
