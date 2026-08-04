---
name: project-stackctl-changes
description: Use when working with stack orchestration in this repo, whether through the preferred `stackctl` CLI (see .stackctl) or the root `stackctl.sh` compatibility script, and you need the repo-specific safety, portability, and validation rules
metadata:
  migrated-from: .github/instructions/stackctl.instructions.md
  source-format: .instructions.md
  status: active
---

# Project stackctl Changes

## Overview

The preferred stack orchestration interface is the standalone `stackctl` CLI,
configured by the committed `.stackctl` file at the repository root (project
`local-stack`, stack directory `stacks`, stack names `infrastructure`,
`observability`, `platform`, network `traefik-public`, rendered output
`.rendered`, env `.env`, encrypted env suffix `.env.enc`).

The root `stackctl.sh` script is a **compatibility fallback**, not the primary
interface. It is retained for runtimes that cannot install the CLI, most
notably the Doco-CD Linux deploy container, and for the Python-based
generate/render pipeline that still produces the committed `stacks/` output.
Do not delete it, and do not rewrite its behavior without a separate migration
decision.

## When to Use

- Before editing `.stackctl`, `stackctl.sh`, or the Python stack tools.
- When adding or changing subcommands, flags, rendering paths, or Swarm
  preflight behavior in either interface.
- When validating shell portability for repo automation on macOS and Linux
  (applies to the `stackctl.sh` compatibility path and to deploy scripts).

## Command Distinctions

- `stackctl generate` regenerates `stacks/` from per-service Compose sources.
  Do not edit generated stack output directly.
- `stackctl sync` is **drift validation only**. It compares generated output
  with committed stacks and exits 1 on drift. It never generates or deploys.
- `stackctl.sh generate` and `stackctl.sh sync` keep the same semantics in the
  compatibility path.

## Compatibility Path Rules (stackctl.sh)

1. Preserve shell safety guards: keep `set -euo pipefail` and `IFS=$'\n\t'`.
2. Prefer POSIX-safe or guarded shell features so the script keeps working on macOS.
3. Make destructive behavior opt-in. Overwrites need `--force`, interactive confirmation unless `-y/--yes`, and timestamped backups.
4. Write rendered compose files to `${RENDER_DIR:-$SCRIPT_DIR/.rendered}` and never print secret values.
5. Keep `ensure_swarm_info` and `ensure_traefik_network` in the deployment path, including dry-run-safe behavior.
6. Preserve the behavioral contract of `up`, `down`, `status`, `logs`, `doctor`, and `env`.

## Behavioral Contract (compatibility path)

| Subcommand | Required behavior |
| --- | --- |
| `up` | Render compose files, deploy stacks, optionally follow logs, honor `--dry-run` and stack selection |
| `down` | Remove stacks, optionally remove network, honor `--dry-run` and `-y/--yes` |
| `status` | List services for selected stacks |
| `logs` | Follow logs for chosen services and clean up background jobs on exit |
| `doctor` | Validate environment, network, and compose syntax |
| `env` | List or recreate `.env` files from examples with safeguards and a summary report |

## Known Parity Status

The live CLI's generated output is not yet byte-equivalent to the committed
`stacks/` files produced by `tools/generate_stacks.py` (env_file/bind-mount
path rewriting, volume `name:` keys, YAML serialization differ). Until parity
is proven, CI drift validation and nightly regeneration keep the Python
toolchain, and Doco-CD keeps the `stackctl.sh` compatibility path. Do not
claim CLI/deploy parity in docs or automation without verification.

## Validation

After changing `stackctl.sh` or `.stackctl`, run the relevant checks:

```bash
bash -n stackctl.sh
stackctl doctor
stackctl plan generate   # or `stackctl generate --dry-run --output-dir /tmp/check`
./stackctl.sh help
./stackctl.sh doctor --fix-network
./stackctl.sh env --list
```

## Common Mistakes

- Treating `stackctl.sh` as the primary interface instead of the compatibility path.
- Describing `sync` as generation, synchronization, or deployment (it is drift validation only).
- Introducing GNU-only flags without a macOS-safe fallback.
- Writing rendered output outside `.rendered/` or logging secret values.
- Making overwrite behavior implicit instead of opt-in.
- Breaking dry-run mode with side effects.
- Rewriting large portions of the script instead of using minimal targeted edits.

## See Also

- [AGENTS.md](../../../AGENTS.md)
- [stacks/README.md](../../../stacks/README.md)
- [.stackctl](../../../.stackctl)
