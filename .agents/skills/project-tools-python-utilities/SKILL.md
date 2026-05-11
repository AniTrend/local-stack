---
name: project-tools-python-utilities
description: Use when changing Python utilities under tools/ and you need the repo-specific contracts for rendering, env handling, validation, and secret-safe behavior
metadata:
  migrated-from: .github/instructions/tools.instructions.md
  source-format: .instructions.md
---

# Project Tools Python Utilities

## Overview

Utilities under `tools/` support rendering and deployment workflows for Local-Stack. Keep them dependency-light, safe by default, and strict about avoiding secret leakage or writes back into source compose files.

## When to Use

- Before editing any Python file under `tools/`.
- When changing compose rendering, env interpolation, or helper behavior used by stack workflows.
- When updating dependencies, docs, or tests for repo utilities.

## Core Pattern

1. Stay compatible with Python 3.8+ and prefer the standard library where practical.
2. Use `PyYAML` for YAML parsing and keep dependencies narrow in `tools/requirements.txt`.
3. Never hardcode or print secrets, and do not read `.env` files outside intended `env_file` scope.
4. Write outputs into a dedicated rendered location, not back into source compose files.
5. Keep utilities self-contained and avoid network calls.

## Renderer Contract

For `tools/render_compose.py`:

- Inputs: `-i/--input`, `-o/--output`, optional `--strict`.
- Precedence: `env_file` values load first, current process environment layers on top, inline `environment` values override both.
- Interpolation: support `${VAR}`, `${VAR-default}`, `${VAR:-default}`, and unbraced `$VAR`.
- Unresolved placeholders: leave intact unless `--strict` is set, then fail non-zero.
- Output: preserve YAML structure and do not mutate source file permissions.

## Validation

Run these after tool changes:

```bash
python3 -m py_compile tools/*.py
python3 tools/render_compose.py --help
docker compose -f <rendered-file> config
```

Update [tools/README.md](../../../tools/README.md) and tests under `tools/tests/` when behavior changes.

## Common Mistakes

- Printing full env values or rendered content that contains secrets.
- Writing rendered files back into the source tree.
- Adding heavyweight dependencies or network behavior.
- Changing interpolation precedence without updating docs and tests.

## See Also

- [AGENTS.md](../../../AGENTS.md)
- [tools/README.md](../../../tools/README.md)
